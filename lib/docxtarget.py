# TextbookImprover -- tools for converting OER textbooks into accessible
# formats.
# Copyright (C) 2026 Robert Szarka
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""What a docx target adds to the Word file Pandoc writes.

Pandoc 3.11's writer marks a header row to repeat, writes an image's alt
text as its description, and sets the language and the title. Four
things it doesn't do, each of which Word's Accessibility Checker or a
reader of the file notices:

- **Compatibility mode.** Pandoc's reference document declares none, so
  Word opens the file in Compatibility Mode, and won't run its
  Accessibility Checker until the file is converted. Mode 15 is set.
- **ScreenTips.** A link's title is a Word hyperlink's ScreenTip
  (w:tooltip); 3.11's writer drops it. Pandoc's release after 3.11
  writes it itself (pandoc#11890), so a hyperlink that has one is left.
- **Decorative images.** An image the book marks decorative has empty
  alt text, which Word's checker reports as missing. Word's own marker
  (Office 2019 and later) is added to its drawing.
- **Header columns.** A table whose first column heads its rows gets its
  First Column flag (tblLook), which is also what the table census reads
  when the file is read back as a source.

The file is rewritten as text, part by part, so every part and byte this
doesn't touch is copied through as Pandoc wrote it. Each rule matches
the page's AST to the XML in document order, which is the order Pandoc
writes it; a rule that finds nothing to match changes nothing.
"""

import html
import json
import os
import re
import shutil
import tempfile
import zipfile

W_URI = "http://schemas.microsoft.com/office/word"
SETTING = ('<w:compatSetting w:name="compatibilityMode" w:uri="%s" '
           'w:val="15"/>' % W_URI)
COMPAT = "<w:compat>" + SETTING + "</w:compat>"
# CT_Settings is a sequence: w:compat has to precede these.
AFTER_COMPAT = ("w:docVars", "w:rsids", "m:mathPr", "w:attachedSchema",
                "w:themeFontLang", "w:clrSchemeMapping",
                "w:doNotIncludeSubdocsInStats", "w:doNotAutoCompressPictures",
                "w:forceUpgrade", "w:captions", "w:readModeInkLockDown",
                "w:smartTagType", "sl:schemaLibrary", "w:shapeDefaults",
                "w:doNotEmbedSmartTags", "w:decimalSymbol", "w:listSeparator")
DECORATIVE = ('<a:extLst xmlns:a="http://schemas.openxmlformats.org/'
              'drawingml/2006/main"><a:ext uri="{C183D7F6-B498-43B3-948B-'
              '1728B52AA6E4}"><adec:decorative xmlns:adec="http://schemas.'
              'microsoft.com/office/drawing/2017/decorative" val="1"/>'
              '</a:ext></a:extLst>')
FIRST_COLUMN = 0x0080


def compat_mode(settings):
    """settings.xml with compatibilityMode 15, in the place the schema
    gives it; an existing setting is replaced."""
    found = re.search(r'<w:compatSetting[^>]*w:name="compatibilityMode"[^>]*/>',
                      settings)
    if found:
        mode = re.sub(r'w:val="[^"]*"', 'w:val="15"', found.group(0))
        return settings[:found.start()] + mode + settings[found.end():]
    if "</w:compat>" in settings:
        # CT_Compat puts Word's legacy options first, every compatSetting
        # after them.
        return settings.replace("</w:compat>", SETTING + "</w:compat>", 1)
    positions = [settings.find("<" + name) for name in AFTER_COMPAT]
    positions = [p for p in positions if p >= 0]
    at = min(positions) if positions else settings.rfind("</w:settings>")
    if at < 0:
        return settings
    return settings[:at] + COMPAT + settings[at:]


# ---------------------------------------------------------------------------
# What the page says, in the order Pandoc writes it
# ---------------------------------------------------------------------------

def _stringify(inlines):
    out = []
    for el in inlines or []:
        t, c = el.get("t"), el.get("c")
        if t == "Str":
            out.append(c)
        elif t in ("Space", "SoftBreak", "LineBreak"):
            out.append(" ")
        elif t in ("Code", "Math"):
            out.append(c[1])
        elif t in ("Emph", "Strong", "Underline", "Strikeout", "SmallCaps",
                   "Superscript", "Subscript"):
            out.append(_stringify(c))
        elif t in ("Link", "Span"):
            out.append(_stringify(c[1]))
        elif t == "Quoted":
            out.append(_stringify(c[1]))
    return "".join(out)


def _words(text):
    return "".join(text.split())


def gather(doc):
    """(body, notes): each a dict of the page's titled links, decorative
    images, and tables, in the order Pandoc writes them into the body
    part and into the footnotes part."""
    parts = {"body": {"links": [], "images": [], "tables": []},
             "notes": {"links": [], "images": [], "tables": []}}

    def walk(node, where):
        if isinstance(node, list):
            for item in node:
                walk(item, where)
            return
        if not isinstance(node, dict):
            return
        t, c = node.get("t"), node.get("c")
        if t == "Note":
            walk(c, "notes")
            return
        if t == "Link":
            attr, content, (target, title) = c
            if title:
                parts[where]["links"].append(
                    (target, _words(_stringify(content)), title))
            walk(content, where)
            return
        if t == "Image":
            attr, alt, _ = c
            keys = dict(attr[2])
            parts[where]["images"].append(
                not _stringify(alt).strip()
                and (keys.get("aria-hidden") == "true"
                     or keys.get("role") == "presentation"))
            return
        if t == "Table":
            bodies = c[4]
            parts[where]["tables"].append(
                any(body[1] > 0 for body in bodies))
            walk(c, where)
            return
        for value in (c if isinstance(c, list) else [c]):
            walk(value, where)
    walk(doc.get("blocks", []), "body")
    return parts["body"], parts["notes"]


# ---------------------------------------------------------------------------
# The XML
# ---------------------------------------------------------------------------

def _relationships(rels):
    return {m.group(1): html.unescape(m.group(2)) for m in re.finditer(
        r'<Relationship\b[^>]*?Id="([^"]+)"[^>]*?Target="([^"]*)"', rels)} | {
        m.group(2): html.unescape(m.group(1)) for m in re.finditer(
            r'<Relationship\b[^>]*?Target="([^"]*)"[^>]*?Id="([^"]+)"', rels)}


def screentips(xml, rels, links):
    """Each titled link's hyperlink given its w:tooltip; returns (xml,
    count). A hyperlink is matched by its target (an external address,
    or #anchor) and its text, first come first served."""
    if not links:
        return xml, 0
    targets = _relationships(rels)
    queue = list(links)
    count = 0

    def one(m):
        nonlocal count
        attrs, inner = m.group(1), m.group(2)
        if "w:tooltip=" in attrs:
            return m.group(0)
        rid = re.search(r'r:id="([^"]+)"', attrs)
        anchor = re.search(r'w:anchor="([^"]+)"', attrs)
        target = targets.get(rid.group(1), "") if rid else ""
        if anchor:
            target = (target + "#" + html.unescape(anchor.group(1))
                      if target else "#" + html.unescape(anchor.group(1)))
        text = _words(html.unescape("".join(
            re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", inner))))
        for i, (want, words, title) in enumerate(queue):
            if want == target and words == text:
                del queue[i]
                count += 1
                return ('<w:hyperlink%s w:tooltip="%s">%s</w:hyperlink>'
                        % (attrs, html.escape(title, quote=True), inner))
        return m.group(0)
    xml = re.sub(r"<w:hyperlink\b([^>]*)>(.*?)</w:hyperlink>", one, xml,
                 flags=re.S)
    return xml, count


def decorative(xml, flags):
    """The drawings of decorative images marked decorative, the nth
    wp:docPr for the nth image; returns (xml, count)."""
    if not any(flags):
        return xml, 0
    it = iter(flags)
    count = 0

    def one(m):
        nonlocal count
        if not next(it, False) or "decorative" in m.group(0):
            return m.group(0)
        count += 1
        tag = m.group(1)
        if m.group(0).endswith("/>"):
            return "<wp:docPr%s>%s</wp:docPr>" % (tag.rstrip(" /"), DECORATIVE)
        return m.group(0) + DECORATIVE
    xml = re.sub(r"<wp:docPr\b([^>]*?)\s*/?>", one, xml)
    return xml, count


def first_columns(xml, flags):
    """tblLook's firstColumn set on each table whose rows have a header
    column, the nth w:tblLook for the nth table; returns (xml, count)."""
    if not any(flags):
        return xml, 0
    it = iter(flags)
    count = 0

    def one(m):
        nonlocal count
        if not next(it, False):
            return m.group(0)
        look = m.group(0)
        if 'w:firstColumn="1"' in look:
            return look
        look = re.sub(r'w:firstColumn="0"', 'w:firstColumn="1"', look)
        if "w:firstColumn=" not in look:
            look = look.replace("<w:tblLook", '<w:tblLook w:firstColumn="1"', 1)
        val = re.search(r'w:val="([0-9A-Fa-f]{4})"', look)
        if val:
            look = look.replace(val.group(0), 'w:val="%04X"'
                                % (int(val.group(1), 16) | FIRST_COLUMN))
        count += 1
        return look
    xml = re.sub(r"<w:tblLook\b[^>]*/>", one, xml)
    return xml, count


def finish(path, doc):
    """Rewrite the .docx at path with what the page's AST says; returns a
    dict of counts: tooltips, decorative, first_columns, and compat (1
    when the mode was set)."""
    if isinstance(doc, str):
        with open(doc, encoding="utf-8") as fh:
            doc = json.load(fh)
    body, notes = gather(doc)
    counts = {"compat": 0, "tooltips": 0, "decorative": 0, "first_columns": 0}
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        parts = {n: z.read(n) for n in names}
        infos = {i.filename: i for i in z.infolist()}
    text = lambda n: parts[n].decode("utf-8") if n in parts else ""
    if "word/settings.xml" in parts:
        new = compat_mode(text("word/settings.xml"))
        counts["compat"] = int(new != text("word/settings.xml"))
        parts["word/settings.xml"] = new.encode("utf-8")
    for part, rels, facts in (
            ("word/document.xml", "word/_rels/document.xml.rels", body),
            ("word/footnotes.xml", "word/_rels/footnotes.xml.rels", notes)):
        if part not in parts:
            continue
        xml = text(part)
        xml, n = screentips(xml, text(rels), facts["links"])
        counts["tooltips"] += n
        xml, n = decorative(xml, facts["images"])
        counts["decorative"] += n
        xml, n = first_columns(xml, facts["tables"])
        counts["first_columns"] += n
        parts[part] = xml.encode("utf-8")
    handle, temporary = tempfile.mkstemp(suffix=".docx",
                                         dir=os.path.dirname(os.path.abspath(path)))
    os.close(handle)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as out:
            for name in names:
                out.writestr(infos[name], parts[name])
        shutil.move(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    return counts
