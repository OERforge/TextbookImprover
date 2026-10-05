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
    or #anchor) and its text, first come first served. Pandoc 3.12's
    writer writes the ScreenTip itself (#11869); a hyperlink that has one
    already keeps it and uses up its link, so the rest still match and the
    count is of the file's ScreenTips, whichever wrote them."""
    if not links:
        return xml, 0
    targets = _relationships(rels)
    queue = list(links)
    count = 0

    def one(m):
        nonlocal count
        attrs, inner = m.group(1), m.group(2)
        rid = re.search(r'r:id="([^"]+)"', attrs)
        anchor = re.search(r'w:anchor="([^"]+)"', attrs)
        target = targets.get(rid.group(1), "") if rid else ""
        if anchor:
            target = (target + "#" + html.unescape(anchor.group(1))
                      if target else "#" + html.unescape(anchor.group(1)))
        text = _words(html.unescape("".join(
            re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", inner))))
        # An anchor is the bookmark name the writer gave the id, which
        # isn't the id when either version hashes it or 3.12 hides it.
        name = html.unescape(anchor.group(1)) if anchor else None
        for i, (want, words, title) in enumerate(queue):
            if (want == target or (name and not rid and want.startswith("#")
                                   and name in bookmark_names(want[1:]))) \
                    and words == text:
                del queue[i]
                count += 1
                if "w:tooltip=" in attrs:
                    return m.group(0)
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
# bookmarks out. A numbered paragraph, a list's item, keeps its numbering
# level's own indent and gains the quote's beyond it, so Word shows the list
# inside the quote; Pandoc's reader never puts a list inside a quote,
# however it's indented, and reading Word puts it back by that indent
# (docxrepair.mark_quoted_lists).
# Marks are ids the writer turns into bookmarks, found again in its XML by
# name. Letters and digits only, and none the start of another: Pandoc 3.11
# names a bookmark after an id that starts with a letter, and 3.12 (#11845)
# puts an underscore before one of letters, digits, and underscores and
# hashes anything else, so a hyphen in a mark would lose it. Each is found
# with or without the underscore.
QUOTE_MARK = "tiqQuote"
QUOTE_STEP = 480                      # the Block Text style's own indent
AFTER_IND = ("w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap",
             "w:jc", "w:textDirection", "w:textAlignment",
             "w:textboxTightWrap", "w:outlineLvl", "w:divId", "w:cnfStyle",
             "w:rPr", "w:sectPr", "w:pPrChange")


QUOTE_SEPARATOR = "tiqSepQuote"
# Pandoc's reader joins adjacent code paragraphs into one code block, as it
# joins adjacent quotes: two code blocks in a row get the same separator.
CODE_SEPARATOR = "tiqSepCode"
TABLE_MARK = "tiqTable"
DECORATIVE_MARK = "tiqDecorative"
LINES_MARK = "tiqLines"
CODE_MARK = "tiqLang"
# A paragraph holding only a display formula, after the first block of a
# list item. Pandoc's writer gives such a paragraph no numbering at all
# (getParaProps's displayMathPara, Writers/Docx/OpenXML.hs, 3.12), where
# the item's other paragraphs get its no-marker numbering; so the item,
# and the list, end at the formula when the file is read. The mark carries
# the list's depth, which becomes the paragraph's numbering level.
MATH_MARK = "tiqMath"
BASE_LIST_ID = 1000          # Pandoc's numbering with no marker (baseListId)
# A table or a horizontal rule inside an item of a list that isn't itself
# in a list. Word can't put a table in a numbered paragraph, and Pandoc's
# reader takes its own rule only from a paragraph with no properties, so
# with no numbering (Readers/Docx/Parse.hs); either way the reader ends the
# list there (Readers/Docx/Lists.hs folds only paragraphs into an item),
# so the file
# says which of its tables belong to an item, with how many blocks of the
# item follow it and whether the list goes on after the item, in the same
# part as the id map; docxrepair.apply_list_tables puts them back.
ITEM_TABLE_MARK = "tiqItemTable"
NUMBER_CLASSES = ("numberLines", "number-lines")
# A code block's language, the class Pandoc highlights by, has nowhere to
# go in Word either. It goes in a hidden bookmark (a name starting with an
# underscore) in the code's paragraph, _tiqCode_<language>_<n>, which
# reading Word matches back to the block by its text. Bookmark names hold
# letters, digits, and underscores, to 40 characters; a language that
# doesn't fit is reported instead.
CODE_BOOKMARK = "_tiqCode_"
NOT_LANGUAGES = NUMBER_CLASSES + ("sourceCode", "numberSource")


def code_language(block):
    """The language a code block is highlighted as, or None."""
    return next((k for k in block["c"][0][1] if k not in NOT_LANGUAGES), None)


def _bookmarkable(language):
    return bool(re.fullmatch(r"[A-Za-z0-9]{1,24}", language or ""))


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


def _separator(prefix, n):
    """A paragraph Pandoc's reader keeps, to keep two blocks apart: a
    zero-width space and a bookmark. A bookmark alone was kept in one place
    and dropped in another, the blocks on either side joined."""
    return {"t": "Para", "c": [{"t": "Str", "c": "\u200b"},
                               {"t": "Span", "c": [[prefix + str(n), [], []], []]}]}


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
    counts = {"quote": 0, "sep": 0, "table": 0, "decorative": 0, "lines": 0, "code": 0}

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
            if out and _edge(item, True) == "CodeBlock" and _edge(out[-1], False) == "CodeBlock":
                counts["sep"] += 1
                out.append(_separator(CODE_SEPARATOR, counts["sep"]))
            if t == "Figure" and _lone_image(item) is not None \
                    and _decorative(_lone_image(item)):
                out.append(marked(DECORATIVE_MARK, "decorative", [item], True))
                continue
            item = visit(item)
            if out and _edge(item, True) == "BlockQuote" and _edge(out[-1], False) == "BlockQuote":
                counts["sep"] += 1
                out.append(_separator(QUOTE_SEPARATOR, counts["sep"]))
            if t == "Table":
                item = marked(TABLE_MARK, "table", [item], True)
            elif t == "CodeBlock":
                if _bookmarkable(code_language(item)):
                    item = marked(CODE_MARK, "code", [item], True)
                if any(k in item["c"][1][0]["c"][0][1] if item.get("t") == "Div" else k in item["c"][0][1]
                       for k in NUMBER_CLASSES):
                    item = marked(LINES_MARK, "lines", [item], True)
            elif t == "Image" and _decorative(item):
                item = marked(DECORATIVE_MARK, "decorative", [item], False)
            out.append(item)
        return out

    doc["blocks"] = visit(doc.get("blocks", []))
    counts["math"] = _mark_list_math(doc["blocks"], -1)
    return doc, sum(counts.values())


def _display_math_para(block):
    """A paragraph Pandoc's writer gives no numbering in a list item: one
    holding only a display formula."""
    return block.get("t") == "Para" and len(block["c"]) == 1 \
        and block["c"][0].get("t") == "Math" \
        and block["c"][0]["c"][0].get("t") == "DisplayMath"


def _split_display(block):
    """A paragraph holding display formulas among other inlines, as
    Pandoc's writer will write it: each run of formulas and each run of
    the rest its own paragraph, spaces at their edges dropped."""
    if block.get("t") != "Para":
        return [block]
    inlines = block["c"]
    shown = [i.get("t") == "Math" and i["c"][0].get("t") == "DisplayMath"
             for i in inlines]
    if not any(shown) or all(shown):
        return [block]
    groups, current, kind = [], [], None
    for inline, display in zip(inlines, shown):
        if current and display != kind:
            groups.append(current)
            current = []
        current.append(inline)
        kind = display
    groups.append(current)
    space = ("Space", "SoftBreak", "LineBreak")
    out = []
    for group in groups:
        while group and group[0].get("t") in space:
            group = group[1:]
        while group and group[-1].get("t") in space:
            group = group[:-1]
        if group:
            out.append({"t": "Para", "c": group})
    return out


def _mark_item(blocks, depth, counter, opens_item):
    """Within a list item's blocks, and the divs among them: each
    paragraph of display formulas cut out, and each one but the item's
    very first block marked with the item's depth."""
    blocks[:] = [piece for inner in blocks for piece in _split_display(inner)]
    for i, inner in enumerate(blocks):
        if _display_math_para(inner) and not (opens_item and i == 0):
            counter[0] += 1
            blocks[i] = {"t": "Div", "c": [["%s%dd%d" % (
                MATH_MARK, counter[0], depth), [], []], [inner]]}
        elif inner.get("t") == "Div":
            _mark_item(inner["c"][1], depth, counter, opens_item and i == 0)


def _held(block):
    """"t" for a table, "r" for a horizontal rule, or a div holding nothing
    but one, at any depth; None otherwise."""
    while block.get("t") == "Div" and len(block["c"][1]) == 1:
        block = block["c"][1][0]
    return {"Table": "t", "HorizontalRule": "r"}.get(block.get("t"))


def _mark_item_tables(item, counter, continues):
    """Mark each table after the first block of a top-level list item with
    how many of the item's blocks follow it and whether the list goes on."""
    for i in range(len(item) - 1, 0, -1):
        kind = _held(item[i])
        if kind:
            counter[0] += 1
            item[i] = {"t": "Div", "c": [["%s%dk%sf%dc%d" % (
                ITEM_TABLE_MARK, counter[0], kind, len(item) - i - 1,
                int(continues)), [], []], [item[i]]]}


def item_tables(xml):
    """[(kind, ordinal, follow, continues)] for each table ("t") or rule
    ("r") mark_blocks marked as in a list item, the ordinal counting the
    body's tables, or its rules, outside tables, from 0. The marks are
    then removed. Returns (xml, found)."""
    pattern = re.compile(r'<w:bookmarkStart w:id="(\d+)" w:name="_?%s\d+k([tr])f(\d+)c(\d)"\s*/>'
                         % ITEM_TABLE_MARK)
    found = []
    while True:
        m = pattern.search(xml)
        if not m:
            break
        kind = m.group(2)
        target = "<w:tbl>" if kind == "t" else 'o:hr="t"'
        at = xml.find(target, m.end())
        if at >= 0:
            depth, ordinal = 0, 0
            for tag in re.finditer(r'<w:tbl>|</w:tbl>|o:hr="t"', xml[:at]):
                if tag.group(0) == "<w:tbl>":
                    if depth == 0 and kind == "t":
                        ordinal += 1
                    depth += 1
                elif tag.group(0) == "</w:tbl>":
                    depth -= 1
                elif depth == 0 and kind == "r":
                    ordinal += 1
            found.append((kind, ordinal, int(m.group(3)), int(m.group(4))))
        xml = xml[:m.start()] + xml[m.end():]
        xml = re.sub(r'<w:bookmarkEnd w:id="%s"\s*/>' % m.group(1), "", xml, count=1)
    return xml, found


def _mark_list_math(blocks, depth, counter=None):
    """Mark each display-formula paragraph that follows the first block of
    a list item, with the item's depth (MATH_MARK). Returns how many."""
    counter = counter if counter is not None else [0]

    def items_of(block):
        if block.get("t") == "OrderedList":
            return block["c"][1]
        if block.get("t") == "BulletList":
            return block["c"]
        return None
    for block in blocks:
        items = items_of(block) if isinstance(block, dict) else None
        if items is not None:
            for j, item in enumerate(items):
                # The writer cuts a paragraph holding a display formula and
                # text into paragraphs (fixDisplayMath, Writers/Shared.hs);
                # cut here the same way, so the formula's own is marked.
                _mark_item(item, depth + 1, counter, True)
                if depth == -1:
                    _mark_item_tables(item, counter, j < len(items) - 1)
                _mark_list_math(item, depth + 1, counter)
        elif isinstance(block, dict) and block.get("t") in ("Div", "BlockQuote"):
            inner = block["c"][1] if block["t"] == "Div" else block["c"]
            _mark_list_math(inner, depth, counter)
    return counter[0]


def list_math(xml):
    """Each paragraph mark_blocks marked as a display formula in a list
    item numbered as the item's other paragraphs are: the item's level,
    with no marker. The marks are then removed. Returns (xml, count)."""
    pattern = re.compile(r'<w:bookmarkStart w:id="(\d+)" w:name="_?%s(\d+)d(\d+)"\s*/>'
                         % MATH_MARK)
    count = 0
    while True:
        m = pattern.search(xml)
        if not m:
            break
        ident, level = m.group(1), m.group(3)
        end = re.compile(r'<w:bookmarkEnd w:id="%s"\s*/>' % ident)
        para = xml.find("<w:p>", m.end())
        props = re.compile(r"<w:pPr>(.*?)</w:pPr>", re.S).match(xml, para + len("<w:p>")) \
            if para >= 0 else None
        numbering = ('<w:numPr><w:ilvl w:val="%s" /><w:numId w:val="%d" /></w:numPr>'
                     % (level, BASE_LIST_ID))
        if para >= 0 and not (props and "<w:numPr>" in props.group(1)):
            if props:
                inner = props.group(1)
                style = re.match(r"\s*<w:pStyle [^>]*/>", inner)
                at = props.start(1) + (style.end() if style else 0)
                xml = xml[:at] + numbering + xml[at:]
            else:
                at = para + len("<w:p>")
                xml = xml[:at] + "<w:pPr>" + numbering + "</w:pPr>" + xml[at:]
            count += 1
        # The mark itself goes, start and end.
        xml = xml[:m.start()] + xml[m.end():]
        xml = end.sub("", xml, count=1)
    return xml, count


def _edge(block, first):
    """The kind of block Word sees at the start (or end) of this one: a
    Div writes no paragraph of its own, so two quotes in Divs side by side,
    as DCIC's are, come out adjacent and need the separator too."""
    while isinstance(block, dict) and block.get("t") == "Div" and block["c"][1]:
        block = block["c"][1][0 if first else -1]
    return block.get("t") if isinstance(block, dict) else None


def lines_marks(doc):
    """{n: first line's number} for each numbered code block mark_blocks
    marked."""
    found = {}

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            c = node.get("c")
            if node.get("t") == "Div" and c[0][0].startswith(LINES_MARK) and len(c[1]) == 1:
                block = c[1][0]
                # Inside the language's mark, when the block has one.
                while block.get("t") == "Div" and len(block["c"][1]) == 1:
                    block = block["c"][1][0]
                keys = dict(block["c"][0][2]) if block.get("t") == "CodeBlock" else {}
                start = keys.get("startFrom") or keys.get("start-from") or "1"
                found[int(c[0][0][len(LINES_MARK):])] = int(start) if start.isdigit() else 1
            walk(c)
    walk(doc.get("blocks", []))
    return found


# Numbered code lines. Word has no numbering for a block (its line
# numbering is a section's), and a code block's numberLines class has
# nowhere to go, so the numbers are written as text, each line's in a run
# of Word's own "Line Number" character style: a reader of the Word file
# sees them, and reading the file back takes them out again and numbers
# the block (docxrepair.apply_number_lines). Copying the code out of Word
# copies the numbers with it.
LINE_NUMBER_STYLE = ('<w:style w:type="character" w:styleId="LineNumber">'
                     '<w:name w:val="line number" /><w:basedOn w:val="DefaultParagraphFont" />'
                     '<w:uiPriority w:val="99" /><w:semiHidden /><w:unhideWhenUsed />'
                     '</w:style>')


def _number_run(text):
    return ('<w:r><w:rPr><w:rStyle w:val="LineNumber" /></w:rPr>'
            '<w:t xml:space="preserve">%s</w:t></w:r>' % text)


def number_lines(xml, at, start):
    """The code paragraph after position at with each line's number at
    its start; returns (xml, lines numbered)."""
    para = xml.find("<w:p>", at)
    end = xml.find("</w:p>", para)
    if para < 0 or end < 0 or 'w:val="SourceCode"' not in xml[para:end]:
        return xml, 0
    body = xml[para:end]
    breaks = [m.end() for m in re.finditer(r"<w:r><w:br\s*/></w:r>", body)]
    width = len(str(start + len(breaks)))
    head = re.compile(r"<w:p>\s*(?:<w:pPr>.*?</w:pPr>)?", re.S).match(body).end()
    points = [head] + breaks
    for i, point in reversed(list(enumerate(points))):
        body = body[:point] + _number_run("%*d  " % (width, start + i)) + body[point:]
    return xml[:para] + body + xml[end:], len(points)


def code_marks(doc):
    """{n: language} for each code block mark_blocks marked for its
    language."""
    found = {}

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            c = node.get("c")
            if node.get("t") == "Div" and c[0][0].startswith(CODE_MARK):
                found[int(c[0][0][len(CODE_MARK):])] = code_language(c[1][0])
            walk(c)
    walk(doc.get("blocks", []))
    return found


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
CODE_ID = 850000


def apply_markers(xml, tables, lines=None, codes=None):
    """What each marked element calls for, applied to the element each
    mark stands before: a table's First Column flag and its JAWS
    bookmark, an image's decorative mark. The marks are then removed.
    Returns (xml, counts)."""
    counts = {"first_columns": 0, "jaws_titles": 0, "decorative": 0, "code_lines": 0,
              "code_languages": 0}
    lines, codes = lines or {}, codes or {}
    marks = re.findall(r'<w:bookmarkStart w:id="(\d+)" w:name="(_?)((?:%s|%s|%s|%s)\d+)"\s*/>'
                       % (TABLE_MARK, DECORATIVE_MARK, LINES_MARK, CODE_MARK), xml)
    if not marks:
        return xml, counts
    edits = []                    # (start, end, replacement), applied from the end
    for ident, under, name in marks:
        at = xml.find('w:name="%s%s"' % (under, name))
        if name.startswith(LINES_MARK):
            continue
        if name.startswith(CODE_MARK):
            n = int(name[len(CODE_MARK):])
            para = xml.find("<w:p>", at)
            if para >= 0 and n in codes:
                here = para + len("<w:p>")
                props = re.compile(r"\s*<w:pPr>.*?</w:pPr>", re.S).match(xml, here)
                if props:
                    here = props.end()
                edits.append((here, here, '<w:bookmarkStart w:id="%d" w:name="%s%s_%d" />'
                              '<w:bookmarkEnd w:id="%d" />' % (CODE_ID + n, CODE_BOOKMARK,
                                                               codes[n], n, CODE_ID + n)))
                counts["code_languages"] += 1
            continue
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
                # No description and no title, as Word leaves an image it
                # marks decorative. NVDA says "graphic picture decorative"
                # either way, in Word's own file as in ours.
                attributes = re.sub(r'\s(?:descr|title)="[^"]*"', "", m.group(1))
                edits.append((m.start(), m.end(), "<wp:docPr%s>%s%s"
                              % (attributes, DECORATIVE, "</wp:docPr>" if m.group(2) else "")))
                counts["decorative"] += 1
    for start, end, new in sorted(edits, key=lambda e: e[0], reverse=True):
        xml = xml[:start] + new + xml[end:]
    # Code last, from the end: each numbering changes the text after it.
    for ident, under, name in reversed(marks):
        if name.startswith(LINES_MARK):
            n = int(name[len(LINES_MARK):])
            xml, numbered = number_lines(xml, xml.find('w:name="%s%s"' % (under, name)),
                                         lines.get(n, 1))
            counts["code_lines"] += numbered
    ids = [ident for ident, _, _ in marks]
    xml = re.sub(r'<w:bookmarkStart w:id="(?:%s)" w:name="_?(?:%s|%s|%s|%s)\d+"\s*/>'
                 % ("|".join(ids), TABLE_MARK, DECORATIVE_MARK, LINES_MARK, CODE_MARK), "", xml)
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
    "uncaptioned-figure": "a figure with no caption comes back as an image",
    "code-language": "a code block's language (its highlighting) is lost; "
                     "only letters and digits fit in the bookmark that carries one",
    "layout-table": "a layout table comes back as a data table",
    "cell-headers": "a table's cells lose the header cells they name "
                    "(headers); its header rows and column stay",
}


def losses(doc):
    """[(kind, detail)] for what a page has that its Word file can't carry
    and reading it back won't restore."""
    found = []

    def words(node, n=8):
        # Any node: a list item can open with a list or a Div, not only a
        # paragraph's inlines.
        out = []

        def collect(x):
            if isinstance(x, list):
                for y in x:
                    collect(y)
            elif isinstance(x, dict):
                t = x.get("t")
                if t == "Str":
                    out.append(x["c"])
                elif t in ("Space", "SoftBreak", "LineBreak"):
                    out.append(" ")
                elif t in ("Code", "Math"):
                    out.append(x["c"][1])
                else:
                    collect(x.get("c"))
        collect(node)
        return " ".join("".join(out).split()[:n])

    def walk(node, quoted):
        if isinstance(node, list):
            for item in node:
                walk(item, quoted)
        elif isinstance(node, dict):
            t, c = node.get("t"), node.get("c")
            if t == "BlockQuote":
                walk(c, True)
                return
            if t == "CodeBlock" and code_language(node) and not _bookmarkable(code_language(node)):
                found.append(("code-language", code_language(node)))
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


def level_indents(numbering, blank=False):
    """{(numId, ilvl): (left, hanging)} from word/numbering.xml: the
    indent each list level gives its items. A level whose marker is blank
    isn't a list's own: Pandoc's writer and OpenStax's export number an
    item's second paragraph, or its code or figure, with one, to keep it
    in the item, so it's left out, unless blank asks for those alone."""
    found = {}
    abstracts = {m.group(1): m.group(0) for m in re.finditer(
        r'<w:abstractNum\b[^>]*w:abstractNumId="(\d+)".*?</w:abstractNum>', numbering, re.S)}
    for m in re.finditer(r'<w:num w:numId="(\d+)"[^>]*>.*?</w:num>', numbering, re.S):
        ref = re.search(r'w:abstractNumId w:val="(\d+)"', m.group(0))
        if not ref or ref.group(1) not in abstracts:
            continue
        for lvl in re.finditer(r'<w:lvl w:ilvl="(\d+)".*?</w:lvl>', abstracts[ref.group(1)], re.S):
            ind = re.search(r'<w:ind\b([^>]*)/>', lvl.group(0))
            text = re.search(r'<w:lvlText w:val="([^"]*)"', lvl.group(0))
            if not ind or (text is not None and not html.unescape(text.group(1)).strip()) != blank:
                continue
            left = re.search(r'w:(?:left|start)="(-?\d+)"', ind.group(1))
            hanging = re.search(r'w:hanging="(\d+)"', ind.group(1))
            found[(m.group(1), lvl.group(1))] = (int(left.group(1)) if left else 0,
                                                 int(hanging.group(1)) if hanging else 0)
    return found


def _numbering(paragraph):
    """(numId, ilvl) of a numbered paragraph, or None."""
    m = re.search(r'<w:numPr>\s*<w:ilvl w:val="(\d+)"\s*/>\s*<w:numId w:val="(\d+)"', paragraph)
    return (m.group(2), m.group(1)) if m else None


def _set_indent(paragraph, left, right=None, hanging=None):
    ind = '<w:ind w:left="%d"%s%s />' % (left, ' w:right="%d"' % right if right else "",
                                        ' w:hanging="%d"' % hanging if hanging else "")
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


def indent_quotes(xml, levels=None, blanks=None):
    """Each paragraph inside the marked quote ranges indented by its
    depth, a list's items beyond their level's own indent (levels, from
    level_indents), and code that a list item holds in a quote beyond its
    blank level's (blanks, level_indents with blank), the marks removed;
    returns (xml, count, list items and code)."""
    if QUOTE_MARK not in xml:
        return xml, 0, 0
    names = dict(re.findall(r'<w:bookmarkStart w:id="(\d+)" w:name="(_?' + QUOTE_MARK
                            + r'\d+)"\s*/>', xml))
    tokens = re.split(r"(<w:bookmarkStart\b[^>]*/>|<w:bookmarkEnd\b[^>]*/>|"
                      r"<w:tbl>|</w:tbl>|<w:p>.*?</w:p>)", xml, flags=re.S)
    depth, tables, count, items, out = 0, 0, 0, 0, []
    list_depth = 0                    # the quotes around the list being written
    for token in tokens:
        mark = re.match(r'<w:bookmark(Start|End) w:id="(\d+)"', token)
        if mark and mark.group(2) in names:
            depth += 1 if mark.group(1) == "Start" else -1
            continue
        if token.startswith("<w:p>") and "<w:numPr>" not in token:
            list_depth = 0
        if token == "<w:tbl>":
            tables += 1
        elif token == "</w:tbl>":
            tables -= 1
        elif token.startswith("<w:p>") and depth and not tables \
                and "<w:numPr>" in token:
            numbered = _numbering(token)
            # A list's own paragraphs in a quote are the list's, not quoted
            # again: Pandoc's writer styles them Block Text, and its reader
            # would wrap each in a quote of its own. Body Text, with the
            # quote's indent, says the same to the eye.
            own = 'w:pStyle w:val="BlockText"'
            if numbered and levels and numbered in levels:
                list_depth = depth
                left, hanging = levels[numbered]
                token = _set_indent(token.replace(own, 'w:pStyle w:val="BodyText"'),
                                    left + QUOTE_STEP * depth, hanging=hanging)
                count += 1
                items += 1
            elif numbered and blanks and numbered in blanks and own in token \
                    and depth == list_depth:
                left, hanging = blanks[numbered]
                token = _set_indent(token.replace(own, 'w:pStyle w:val="BodyText"'),
                                    left + QUOTE_STEP * depth, hanging=hanging)
                count += 1
            elif numbered and blanks and numbered in blanks and own in token:
                # A paragraph of a quote inside a list item: the reader
                # quotes it by its style, one level whatever its depth; the
                # indent gives the depth, which reading Word restores
                # (docxrepair.mark_quoted_lists, nest_item_quotes).
                left, hanging = blanks[numbered]
                token = _set_indent(token, left + QUOTE_STEP * depth, QUOTE_STEP, hanging)
                count += 1
                items += 1
            elif numbered and blanks and numbered in blanks \
                    and 'w:pStyle w:val="SourceCode"' in token:
                # Code a list item holds in a quote: numbered at a blank
                # level to stay in the item, which the reader keeps it in,
                # but nothing tells it of the quote; this indent does, and
                # reading Word wraps the code in its quote again
                # (docxrepair.apply_quoted_code).
                left, hanging = blanks[numbered]
                token = _set_indent(token, left + QUOTE_STEP * depth, hanging=hanging)
                count += 1
                items += 1
        elif token.startswith("<w:p>") and depth and not tables:
            block_text = 'w:pStyle w:val="BlockText"' in token
            if not (block_text and depth == 1):
                token = _set_indent(token, QUOTE_STEP * depth,
                                    QUOTE_STEP if block_text else None)
                count += 1
                # Code in a quote in a quote: the reader quotes code once,
                # however far it's indented; reading Word nests it again
                # (docxrepair.apply_quoted_code), in a file that says so.
                if depth >= 2 and 'w:pStyle w:val="SourceCode"' in token:
                    items += 1
        out.append(token)
    return "".join(out), count, items


# A file whose quotes hold lists says so in a document variable, which
# Word keeps and shows nowhere: reading it, a list's items indented a quote
# step beyond their level are put back in the quote (docxrepair). An
# author's own file, without it, can indent a list for other reasons, a
# step's sub-items under a numbered step, and is left as Pandoc reads it.
QUOTED_LISTS_VAR = "TextbookImproverQuotedLists"


def quoted_lists_var(settings):
    """settings.xml with the document variable, after w:compat, where the
    schema puts w:docVars."""
    if QUOTED_LISTS_VAR in settings:
        return settings
    var = '<w:docVar w:name="%s" w:val="%d"/>' % (QUOTED_LISTS_VAR, QUOTE_STEP)
    if "<w:docVars>" in settings:
        return settings.replace("<w:docVars>", "<w:docVars>" + var, 1)
    at = settings.find("</w:compat>")
    if at < 0:
        return settings
    at += len("</w:compat>")
    return settings[:at] + "<w:docVars>" + var + "</w:docVars>" + settings[at:]


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


def bookmark_names(ident):
    """The bookmark names Pandoc's writer gives an id: 3.11's, which keeps
    one that starts with a letter, and 3.12's (#11845), which puts an
    underscore before one of letters, digits, and underscores, so Word
    hides it; either hashes the rest. Both go in the map, so a file from
    either version reads back."""
    digest = hashlib.sha1(ident.encode("utf-8")).hexdigest()[1:]
    older = ident if ident and ident[0].isalpha() and len(ident) <= 40 \
        else "X" + digest
    newer = "_" + ident if ident and len(ident) < 40 and all(
        c.isalnum() or c == "_" for c in ident) else "_" + digest
    return (older, newer)


def id_map(doc):
    """{bookmark name: id} for every id on the page, and every link to one
    within it, whose bookmark name isn't the id."""
    found = {}

    def note(ident):
        for name in bookmark_names(ident) if ident else ():
            if name != ident:
                found[name] = ident

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


def _id_map_xml(mapping, listed_tables=()):
    rows = "".join('<id bookmark="%s" name="%s"/>' % (html.escape(b, quote=True),
                                                     html.escape(n, quote=True))
                   for b, n in sorted(mapping.items()))
    rows += "".join('<listBlock kind="%s" n="%d" follow="%d" continues="%d"/>' % row
                    for row in sorted(listed_tables))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<ids xmlns="%s">%s</ids>' % (ID_MAP_NS, rows))


# Bookmarks the Word target writes for a reason of its own, kept whatever
# links there are: JAWS's table header names, and a code block's language.
OWN_BOOKMARKS = re.compile(r"(?:Title|ColumnTitle|RowTitle)_\d+$|" + re.escape(CODE_BOOKMARK))
BOOKMARK_START = re.compile(r'<w:bookmarkStart w:id="(\d+)" w:name="([^"]*)"\s*/>')


def linked_ids(docs):
    """Every id a link in the book goes to, within its page or to another."""
    found = set()

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            if node.get("t") == "Link":
                target = node["c"][2][0]
                if "#" in target:
                    found.add(target.split("#", 1)[1])
            walk(node.get("c"))
    for doc in docs:
        walk(doc.get("blocks", []))
    return found


def keep_bookmarks(ids):
    """The bookmark names to keep for links to these ids, as either
    version of Pandoc names them."""
    return {name for ident in ids for name in bookmark_names(ident)} | set(ids)


def prune_bookmarks(xml, keep):
    """xml without the bookmarks no link goes to, keeping the target's own;
    returns (xml, how many went). NVDA announces every bookmark, hidden or
    not, so one that nothing uses is only noise to a screen reader."""
    drop = [ident for ident, name in BOOKMARK_START.findall(xml)
            if name not in keep and not OWN_BOOKMARKS.match(name)]
    for ident in drop:
        xml = re.sub(r'\s*<w:bookmarkStart w:id="%s" w:name="[^"]*"\s*/>' % ident, "", xml)
        xml = re.sub(r'\s*<w:bookmarkEnd w:id="%s"\s*/>' % ident, "", xml)
    return xml, len(drop)


def page_title_text(doc):
    """The page's title as plain text, from its metadata."""
    def text(node):
        if isinstance(node, list):
            return "".join(text(n) for n in node)
        if isinstance(node, dict):
            kind = node.get("t")
            if kind == "Str":
                return node["c"]
            if kind in ("Space", "SoftBreak", "LineBreak"):
                return " "
            if kind == "MetaString":
                return node["c"]
            return text(node.get("c"))
        return ""
    return text((doc.get("meta") or {}).get("title")).strip()


def finish(path, doc, keep=None):
    """Rewrite the .docx at path with what the page's AST says; returns a
    dict of counts: tooltips, decorative, first_columns, and compat (1
    when the mode was set). keep: the bookmark names links go to, when
    the others are to go (bookmarks: linked); None keeps them all."""
    if isinstance(doc, str):
        with open(doc, encoding="utf-8") as fh:
            doc = json.load(fh)
    body, notes = gather(doc)
    tables = table_marks(doc)
    lines = lines_marks(doc)
    codes = code_marks(doc)
    quoted_items = 0
    counts = {"compat": 0, "tooltips": 0, "decorative": 0, "first_columns": 0,
              "quotes": 0, "jaws_titles": 0, "ids": 0, "captions_kept": 0,
              "code_lines": 0, "code_languages": 0, "bookmarks_removed": 0}
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        parts = {n: z.read(n) for n in names}
        infos = {i.filename: i for i in z.infolist()}
    text = lambda n: parts[n].decode("utf-8") if n in parts else ""
    if "word/settings.xml" in parts:
        new = compat_mode(text("word/settings.xml"))
        counts["compat"] = int(new != text("word/settings.xml"))
        parts["word/settings.xml"] = new.encode("utf-8")
    listed_tables = []
    for part, rels, facts in (
            ("word/document.xml", "word/_rels/document.xml.rels", body),
            ("word/footnotes.xml", "word/_rels/footnotes.xml.rels", notes)):
        if part not in parts:
            continue
        xml = text(part)
        xml, n = screentips(xml, text(rels), facts["links"])
        counts["tooltips"] += n
        xml, found = apply_markers(xml, tables, lines, codes)
        for key, n in found.items():
            counts[key] += n
        xml, n = list_math(xml)
        counts["list_math"] = counts.get("list_math", 0) + n
        if part == "word/document.xml":
            xml, listed_tables = item_tables(xml)
        numbering = text("word/numbering.xml") if "word/numbering.xml" in parts else ""
        xml, n, items = indent_quotes(xml, level_indents(numbering) if numbering else None,
                                      level_indents(numbering, blank=True) if numbering else None)
        counts["quotes"] += n
        quoted_items += items
        xml, n = keep_captions(xml)
        counts["captions_kept"] += n
        if keep is not None:
            xml, n = prune_bookmarks(xml, keep)
            counts["bookmarks_removed"] += n
        parts[part] = xml.encode("utf-8")
    if quoted_items and "word/settings.xml" in parts:
        parts["word/settings.xml"] = quoted_lists_var(
            parts["word/settings.xml"].decode("utf-8")).encode("utf-8")
    # The page's title is its Heading 1, not a Title paragraph
    # (target-blocks.lua), so Pandoc wrote no title into the file's
    # properties; it goes there, where Word and a screen reader find it.
    title = page_title_text(doc)
    if title and "docProps/core.xml" in parts:
        core = parts["docProps/core.xml"].decode("utf-8")
        if not re.search(r"<dc:title>[^<]", core):
            entry = "<dc:title>%s</dc:title>" % html.escape(title, quote=False)
            core = re.sub(r"<dc:title\s*/>|<dc:title>\s*</dc:title>", "", core)
            core = core.replace("</cp:coreProperties>", entry + "</cp:coreProperties>")
            parts["docProps/core.xml"] = core.encode("utf-8")
    if counts["code_lines"] and "word/styles.xml" in parts \
            and 'w:styleId="LineNumber"' not in text("word/styles.xml"):
        parts["word/styles.xml"] = text("word/styles.xml").replace(
            "</w:styles>", LINE_NUMBER_STYLE + "</w:styles>", 1).encode("utf-8")
    mapping = id_map(doc)
    if (mapping or listed_tables) and ID_MAP_PART not in parts:
        parts[ID_MAP_PART] = _id_map_xml(mapping, listed_tables).encode("utf-8")
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
