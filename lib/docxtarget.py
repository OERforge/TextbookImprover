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
  Word opens the file in Compatibility Mode, in which, according to
  accessibility guides for Word and reports on Microsoft's Q&A (not tested
  here), its Accessibility Checker won't run until the file is converted.
  Mode 15 is set.
- **ScreenTips.** A link's title is a Word hyperlink's ScreenTip
  (w:tooltip); 3.11's writer drops it. Pandoc's release after 3.11
  writes it itself (pandoc#11890), so a hyperlink that has one is left.
- **Decorative images.** An image the book marks decorative has empty
  alt text, which Word's checker reports as missing. Word's own marker
  ("Mark as decorative", documented by Microsoft; Word 2019 and Microsoft
  365 on, per the guides) is added to its drawing.
- **Header columns.** A table whose first column heads its rows gets its
  First Column flag (tblLook), which is also what the table census reads
  when the file is read back as a source.

The file is rewritten as text, part by part, so every part and byte this
doesn't touch is copied through as Pandoc wrote it. Each rule matches
the page's AST to the XML in document order, which is the order Pandoc
writes it; a rule that finds nothing to match changes nothing.
"""

import hashlib
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
    """(body, notes): each a dict of the page's titled links, in the order
    Pandoc writes them into the body part and into the footnotes part.
    A link is matched by its target and text, never by position."""
    parts = {"body": {"links": []}, "notes": {"links": []}}

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


# Nested quotations. Pandoc's writer styles a quotation's paragraphs
# Block Text at every depth, and a list or code inside one not at all, so
# Word shows a quote in a quote as one, and Pandoc's reader, which nests
# by indentation, reads it back as one. mark_quotes wraps each quote's
# content in a Div with an id, which the writer makes a bookmark range;
# indent_quotes indents each paragraph by its depth and takes the
# bookmarks out. A numbered paragraph is left as it is: the reader never
# puts a list inside a quote, however it's indented.
QUOTE_MARK = "tiq-quote-"
QUOTE_STEP = 480                      # the Block Text style's own indent
AFTER_IND = ("w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap",
             "w:jc", "w:textDirection", "w:textAlignment",
             "w:textboxTightWrap", "w:outlineLvl", "w:divId", "w:cnfStyle",
             "w:rPr", "w:sectPr", "w:pPrChange")


QUOTE_SEPARATOR = QUOTE_MARK + "sep-"
TABLE_MARK = "tiq-table-"
DECORATIVE_MARK = "tiq-decorative-"


def _decorative(image):
    attr, alt, _ = image["c"]
    keys = dict(attr[2])
    return not _stringify(alt).strip() and (
        keys.get("aria-hidden") == "true" or keys.get("role") == "presentation")


def _elements(value):
    """A list of AST elements (blocks or inlines), as opposed to an attr,
    a caption's parts, or a table's rows."""
    return isinstance(value, list) and bool(value) and all(
        isinstance(x, dict) and "t" in x for x in value)


def _lone_image(figure):
    body = figure["c"][2]
    if len(body) == 1 and body[0].get("t") in ("Plain", "Para") \
            and len(body[0]["c"]) == 1 and body[0]["c"][0].get("t") == "Image":
        return body[0]["c"][0]
    return None


def mark_blocks(doc):
    """The page's AST with what the post-processing needs marked on the
    elements themselves, never counted: each block quote's content in a
    marked Div, and a paragraph holding only a bookmark between two quotes
    in a row, which Pandoc's reader would otherwise join; each table in a
    marked Div, which the writer makes a bookmark range around it; each
    decorative image in a marked Span, or the figure it's the whole of in
    a marked Div, since a figure holding more than an image is written as
    a table. Matching by position went wrong on Pandoc's own output: a
    figure holding two images is a w:tbl too. Returns (doc, marks)."""
    counts = {"quote": 0, "sep": 0, "table": 0, "decorative": 0}

    def marked(prefix, kind, inner, block):
        counts[kind] += 1
        return {"t": "Div" if block else "Span",
                "c": [[prefix + str(counts[kind]), [], []], inner]}

    def visit(value):
        if isinstance(value, dict):
            if value.get("t") == "BlockQuote":
                value["c"] = [marked(QUOTE_MARK, "quote", visit(value["c"]), True)]
            elif "c" in value:
                value["c"] = visit(value["c"])
            return value
        if not isinstance(value, list):
            return value
        if not _elements(value):
            return [visit(v) for v in value]
        out = []
        for item in value:
            t = item.get("t")
            if t == "Figure" and _lone_image(item) is not None \
                    and _decorative(_lone_image(item)):
                out.append(marked(DECORATIVE_MARK, "decorative", [item], True))
                continue
            item = visit(item)
            if out and t == "BlockQuote" and out[-1].get("t") == "BlockQuote":
                counts["sep"] += 1
                out.append({"t": "Para", "c": [{"t": "Span", "c": [
                    [QUOTE_SEPARATOR + str(counts["sep"]), [], []], []]}]})
            if t == "Table":
                item = marked(TABLE_MARK, "table", [item], True)
            elif t == "Image" and _decorative(item):
                item = marked(DECORATIVE_MARK, "decorative", [item], False)
            out.append(item)
        return out

    doc["blocks"] = visit(doc.get("blocks", []))
    return doc, sum(counts.values())


def table_marks(doc):
    """{n: (header row, header column)} for each table mark_blocks marked.
    A header row is the table's head; a band (a body's own head row, a
    group's heading) is not one."""
    found = {}

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            c = node.get("c")
            if node.get("t") == "Div" and c[0][0].startswith(TABLE_MARK) \
                    and len(c[1]) == 1 and c[1][0].get("t") == "Table":
                table = c[1][0]["c"]
                found[int(c[0][0][len(TABLE_MARK):])] = (
                    bool(table[3][1]), any(body[1] > 0 for body in table[4]))
            walk(c)
    walk(doc.get("blocks", []))
    return found


# JAWS, according to Freedom Scientific's documentation (not tested here),
# reads a table's headers from a bookmark in the table named Title (a
# header row and a header column), ColumnTitle (a header row), or
# RowTitle (a header column):
# https://doccenter.freedomscientific.com/doccenter/archives/training/samplefiles/usethebookmarkfeatureinwordfortableheaders-oldertechnique.htm
# The page calls it an older technique. The table census reads the same
# bookmarks back as the table's declaration, which holds either way.
JAWS_ID = 800000


def apply_markers(xml, tables):
    """What each marked element calls for, applied to the element each
    mark stands before: a table's First Column flag and its JAWS
    bookmark, an image's decorative mark. The marks are then removed.
    Returns (xml, counts)."""
    counts = {"first_columns": 0, "jaws_titles": 0, "decorative": 0}
    marks = re.findall(r'<w:bookmarkStart w:id="(\d+)" w:name="((?:%s|%s)\d+)"\s*/>'
                       % (TABLE_MARK, DECORATIVE_MARK), xml)
    if not marks:
        return xml, counts
    edits = []                    # (start, end, replacement), applied from the end
    for ident, name in marks:
        at = xml.find('w:name="%s"' % name)
        if name.startswith(TABLE_MARK):
            n = int(name[len(TABLE_MARK):])
            row, col = tables.get(n, (False, False))
            start = xml.find("<w:tbl>", at)
            if start < 0:
                continue
            if col:
                look = re.compile(r"<w:tblLook\b[^>]*/>").search(xml, start)
                if look and 'w:firstColumn="1"' not in look.group(0):
                    tag = look.group(0).replace('w:firstColumn="0"', 'w:firstColumn="1"')
                    if "w:firstColumn=" not in tag:
                        tag = tag.replace("<w:tblLook", '<w:tblLook w:firstColumn="1"', 1)
                    val = re.search(r'w:val="([0-9A-Fa-f]{4})"', tag)
                    if val:
                        tag = tag.replace(val.group(0), 'w:val="%04X"'
                                          % (int(val.group(1), 16) | FIRST_COLUMN))
                    edits.append((look.start(), look.end(), tag))
                    counts["first_columns"] += 1
            if row or col:
                cell = xml.find("<w:tc>", start)
                para = xml.find("<w:p>", cell) if cell >= 0 else -1
                if para >= 0:
                    here = para + len("<w:p>")
                    props = re.compile(r"\s*<w:pPr>.*?</w:pPr>", re.S).match(xml, here)
                    if props:
                        here = props.end()
                    title = ("Title" if row and col else "ColumnTitle" if row
                             else "RowTitle") + "_%d" % n
                    edits.append((here, here, '<w:bookmarkStart w:id="%d" w:name="%s" />'
                                  '<w:bookmarkEnd w:id="%d" />' % (JAWS_ID + n, title, JAWS_ID + n)))
                    counts["jaws_titles"] += 1
        else:
            m = re.compile(r"<wp:docPr\b([^>]*?)\s*(/?)>").search(xml, at)
            if m and "decorative" not in xml[m.start():m.start() + 600]:
                if m.group(2):
                    edits.append((m.start(), m.end(), "<wp:docPr%s>%s</wp:docPr>"
                                  % (m.group(1), DECORATIVE)))
                else:
                    edits.append((m.end(), m.end(), DECORATIVE))
                counts["decorative"] += 1
    for start, end, new in sorted(edits, key=lambda e: e[0], reverse=True):
        xml = xml[:start] + new + xml[end:]
    ids = [ident for ident, _ in marks]
    xml = re.sub(r'<w:bookmarkStart w:id="(?:%s)" w:name="(?:%s|%s)\d+"\s*/>'
                 % ("|".join(ids), TABLE_MARK, DECORATIVE_MARK), "", xml)
    xml = re.sub(r'<w:bookmarkEnd w:id="(?:%s)"\s*/>' % "|".join(ids), "", xml)
    return xml, counts


# Pandoc's writer puts a table's caption before the table without "keep
# with next", and its reader pairs a caption paragraph without it with
# the table before, not after (Readers/Docx/Parse.hs, addCaptioned): a
# table with no caption takes the next one's. Word users want a caption
# kept with its table anyway. A workaround pending Pandoc.
def keep_captions(xml):
    """Keep with next on each table caption; returns (xml, count)."""
    count = 0

    def one(m):
        nonlocal count
        count += 1
        return m.group(1) + "<w:keepNext />"
    xml = re.sub(r'(<w:pStyle w:val="TableCaption"\s*/>)(?!\s*<w:keepNext)', one, xml)
    return xml, count


# What a page has that a Word file can't carry, known before writing.
LOSSES = {
    "list-in-quotation": "a list inside a quotation comes back outside it, "
                         "the quotation split around it",
    "numbered-code": "numbered code lines lose their numbers",
    "uncaptioned-figure": "a figure with no caption comes back as an image",
    "layout-table": "a layout table comes back as a data table",
    "cell-headers": "a table's cells lose the header cells they name "
                    "(headers); its header rows and column stay",
}


def losses(doc):
    """[(kind, detail)] for what a page has that its Word file can't carry
    and reading it back won't restore."""
    found = []

    def words(node, n=8):
        return " ".join(_stringify(node if isinstance(node, list) else [node]).split()[:n])

    def walk(node, quoted):
        if isinstance(node, list):
            for item in node:
                walk(item, quoted)
        elif isinstance(node, dict):
            t, c = node.get("t"), node.get("c")
            if t == "BlockQuote":
                walk(c, True)
                return
            if t in ("BulletList", "OrderedList") and quoted:
                items = c if t == "BulletList" else c[1]
                first = items[0][0]["c"] if items and items[0] and items[0][0].get("c") else []
                found.append(("list-in-quotation", words(first)))
            elif t == "CodeBlock" and any(k in c[0][1] for k in ("numberLines", "number-lines")):
                found.append(("numbered-code", c[1].splitlines()[0][:60] if c[1] else ""))
            elif t == "Figure" and not c[1][1]:
                alts = []
                walk_alts(c[2], alts)
                found.append(("uncaptioned-figure", alts[0] if alts else ""))
            elif t == "Table":
                attr = dict(c[0][2])
                if attr.get("role") == "presentation":
                    found.append(("layout-table", ""))
                cells = [cell for body in c[4] for row in body[2] + body[3] for cell in row[1]] \
                    + [cell for row in c[3][1] for cell in row[1]]
                if any(k == "headers" for cell in cells for k, _ in cell[0][2]):
                    found.append(("cell-headers", words(
                        [i for b in c[1][1] for i in (b.get("c") or [])]) if c[1][1] else ""))
            walk(c, quoted)

    def walk_alts(node, out):
        if isinstance(node, list):
            for item in node:
                walk_alts(item, out)
        elif isinstance(node, dict):
            if node.get("t") == "Image":
                out.append(" ".join(_stringify(node["c"][1]).split())[:60])
            walk_alts(node.get("c"), out)
    walk(doc.get("blocks", []), False)
    return found


def _set_indent(paragraph, left, right=None):
    ind = '<w:ind w:left="%d"%s />' % (left, ' w:right="%d"' % right if right else "")
    if "<w:pPr>" not in paragraph:
        return paragraph.replace("<w:p>", "<w:p><w:pPr>" + ind + "</w:pPr>", 1)
    start = paragraph.index("<w:pPr>")
    end = paragraph.index("</w:pPr>", start)
    props = paragraph[start + len("<w:pPr>"):end]
    props = re.sub(r"<w:ind\b[^>]*/>", "", props)
    at = [props.find("<" + name) for name in AFTER_IND]
    at = [i for i in at if i >= 0]
    cut = min(at) if at else len(props)
    props = props[:cut] + ind + props[cut:]
    return paragraph[:start] + "<w:pPr>" + props + paragraph[end:]


def indent_quotes(xml):
    """Each paragraph inside the marked quote ranges indented by its
    depth, the marks removed; returns (xml, count)."""
    if QUOTE_MARK not in xml:
        return xml, 0
    names = dict(re.findall(r'<w:bookmarkStart w:id="(\d+)" w:name="(' + QUOTE_MARK
                            + r'\d+)"\s*/>', xml))
    tokens = re.split(r"(<w:bookmarkStart\b[^>]*/>|<w:bookmarkEnd\b[^>]*/>|"
                      r"<w:tbl>|</w:tbl>|<w:p>.*?</w:p>)", xml, flags=re.S)
    depth, tables, count, out = 0, 0, 0, []
    for token in tokens:
        mark = re.match(r'<w:bookmark(Start|End) w:id="(\d+)"', token)
        if mark and mark.group(2) in names:
            depth += 1 if mark.group(1) == "Start" else -1
            continue
        if token == "<w:tbl>":
            tables += 1
        elif token == "</w:tbl>":
            tables -= 1
        elif token.startswith("<w:p>") and depth and not tables \
                and "<w:numPr>" not in token:
            block_text = 'w:pStyle w:val="BlockText"' in token
            if not (block_text and depth == 1):
                token = _set_indent(token, QUOTE_STEP * depth,
                                    QUOTE_STEP if block_text else None)
                count += 1
        out.append(token)
    return "".join(out), count


# Ids. Pandoc's writer names a bookmark after its id only when the id
# starts with a letter and is at most 40 characters, Word's rule; any
# other becomes X and a SHA-1 of the id (Writers/Docx/OpenXML.hs,
# toBookmarkName). A link within the page follows, but a link from
# another page names the id itself, and read back, the id is the hash:
# 475 dead links in DCIC's round trip, and every cross-reference into an
# Asciidoctor section, whose ids start with an underscore. So the file
# carries the names it hashed, in a custom XML part, which Word keeps,
# and reading Word renames them back (docxrepair.apply_id_map).
ID_MAP_PART = "customXml/item1.xml"
ID_MAP_NS = "https://github.com/OERforge/TextbookImprover/ids"


def bookmark_name(ident):
    """The bookmark name Pandoc's writer gives an id."""
    if ident and ident[0].isalpha() and len(ident) <= 40:
        return ident
    return "X" + hashlib.sha1(ident.encode("utf-8")).hexdigest()[1:]


def id_map(doc):
    """{bookmark name: id} for every id on the page, and every link to one
    within it, whose bookmark name isn't the id."""
    found = {}

    def note(ident):
        if ident and bookmark_name(ident) != ident:
            found[bookmark_name(ident)] = ident

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            c = node.get("c")
            t = node.get("t")
            if t == "Link":
                target = c[2][0]
                if target.startswith("#"):
                    note(target[1:])
            if isinstance(c, list) and c and isinstance(c[0], list) and len(c[0]) == 3 \
                    and isinstance(c[0][0], str):
                note(c[0][0])
            elif t == "Header":
                note(c[1][0])
            walk(c)
    walk(doc.get("blocks", []))
    return found


def _id_map_xml(mapping):
    rows = "".join('<id bookmark="%s" name="%s"/>' % (html.escape(b, quote=True),
                                                     html.escape(n, quote=True))
                   for b, n in sorted(mapping.items()))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<ids xmlns="%s">%s</ids>' % (ID_MAP_NS, rows))


def finish(path, doc):
    """Rewrite the .docx at path with what the page's AST says; returns a
    dict of counts: tooltips, decorative, first_columns, and compat (1
    when the mode was set)."""
    if isinstance(doc, str):
        with open(doc, encoding="utf-8") as fh:
            doc = json.load(fh)
    body, notes = gather(doc)
    tables = table_marks(doc)
    counts = {"compat": 0, "tooltips": 0, "decorative": 0, "first_columns": 0,
              "quotes": 0, "jaws_titles": 0, "ids": 0, "captions_kept": 0}
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
        xml, found = apply_markers(xml, tables)
        for key, n in found.items():
            counts[key] += n
        xml, n = indent_quotes(xml)
        counts["quotes"] += n
        xml, n = keep_captions(xml)
        counts["captions_kept"] += n
        parts[part] = xml.encode("utf-8")
    mapping = id_map(doc)
    if mapping and ID_MAP_PART not in parts:
        parts[ID_MAP_PART] = _id_map_xml(mapping).encode("utf-8")
        names.append(ID_MAP_PART)
        infos[ID_MAP_PART] = zipfile.ZipInfo(ID_MAP_PART)
        rels = "word/_rels/document.xml.rels"
        if rels in parts:
            parts[rels] = text(rels).replace(
                "</Relationships>",
                '<Relationship Id="rIdTiqIds" Type="http://schemas.openxmlformats.org/'
                'officeDocument/2006/relationships/customXml" Target="../%s"/>'
                "</Relationships>" % ID_MAP_PART, 1).encode("utf-8")
        types = text("[Content_Types].xml")
        if 'Extension="xml"' not in types:
            parts["[Content_Types].xml"] = types.replace(
                "</Types>", '<Override PartName="/%s" ContentType="application/xml"/>'
                "</Types>" % ID_MAP_PART, 1).encode("utf-8")
        counts["ids"] = len(mapping)
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
