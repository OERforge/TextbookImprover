"""
docxrepair.py -- what a .docx needs done to it before Pandoc reads it,
applied to a copy on the way in and never to the source.

BOOKMARKS BETWEEN BLOCKS

OpenStax's DOCX export bookmarks a paragraph, heading, list, or table by
placing w:bookmarkStart as a child of the body, immediately before the
block, and every cross-reference in the book ("Table 1.11", "Example
2.3") links to that name. Pandoc's reader keeps a bookmark only when it
is inside a paragraph, so all of these are lost and every such link is
dead: 4,231 in one book, 104 of them linked to. Moving each one to the
start of the paragraph that follows it -- after w:pPr, where Word itself
puts a bookmark on a paragraph -- makes the reader emit a Span with that
id, and the links land. A bookmark before a table is left where it is;
the table-headers pre-pass reads those and the filter restores them as
anchors ahead of the table, which a split table keeps.

Everything else in the package is copied byte for byte.

Copyright 2026 Robert Szarka

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

import html
import re
import zipfile

# A run of bookmark starts and ends standing directly before a paragraph.
BEFORE_PARAGRAPH = re.compile(
    r"((?:<w:bookmarkStart\b[^>]*/>\s*|<w:bookmarkEnd\b[^>]*/>\s*)+)"
    r"(<w:p\b[^>]*>)(\s*<w:pPr>(?:(?!</w:pPr>).)*</w:pPr>)?", re.S)
START = re.compile(r"<w:bookmarkStart\b[^>]*/>")
HEADING_STYLE = re.compile(r'<w:pStyle w:val="(?:Heading|Title|Subtitle)[^"]*"')
ZWSP_RUN = "<w:r><w:t>&#8203;</w:t></w:r>"
PARAGRAPH = re.compile(r"<w:p\b[^>]*>.*?</w:p>", re.S)
ADJACENT = re.compile(r"(<w:bookmarkStart\b[^>]*/>)(\s*(?:<w:bookmarkEnd\b[^>]*/>\s*)*)"
                      r"(?=<w:bookmarkStart)")
# A paragraph's own properties, never running on into the next
# paragraph's: unbounded, this matched from a heading to a later paragraph
# that opens with a bookmark and moved that bookmark to the heading.
IN_HEADING = re.compile(r"(<w:p\b[^>]*>)(<w:pPr>(?:(?!</w:pPr>).)*</w:pPr>)"
                        r"((?:<w:bookmarkStart\b[^>]*/>\s*)+)", re.S)
END = re.compile(r"<w:bookmarkEnd\b[^>]*/>")


def move_bookmarks_into_paragraphs(xml):
    """Body-level bookmark starts move into the paragraph they precede.
    Returns (xml, count)."""
    moved = 0

    def fix(match):
        nonlocal moved
        starts = START.findall(match.group(1))
        if not starts:
            return match.group(0)
        moved += len(starts)
        ends = "".join(END.findall(match.group(1)))
        # A bookmark inside a heading paragraph is not kept as an anchor:
        # Pandoc maps its name to the heading's own id for links in the
        # same file and drops the name (docxAnchorMap). A bookmark before
        # a heading goes into an empty paragraph of its own, where it is
        # a plain anchor the keeper links preserve.
        if HEADING_STYLE.search(match.group(3) or ""):
            return (ends + "<w:p>" + "".join(starts) + "</w:p>"
                    + match.group(2) + (match.group(3) or ""))
        # Ends stay where they were; Pandoc ignores them, and Word is
        # happy with an end before its start.
        return (ends + match.group(2) + (match.group(3) or "")
                + "".join(starts))

    # Only the body: a match inside a table cell would be a bookmark
    # already inside a paragraph's container, which Pandoc keeps as is.
    head, sep, body = xml.partition("<w:body>")
    if not sep:
        return xml, 0
    body = BEFORE_PARAGRAPH.sub(fix, body)

    # A bookmark the source itself placed inside a heading paragraph
    # (OpenStax's index terms often are): out to a paragraph of its own
    # before the heading, for the same reason as above.
    def out_of_heading(match):
        nonlocal moved
        opening, props, starts = match.group(1), match.group(2), match.group(3)
        if not HEADING_STYLE.search(props):
            return match.group(0)
        names = START.findall(starts)
        moved += len(names)
        return "<w:p>" + "".join(names) + "</w:p>" + opening + props
    body = IN_HEADING.sub(out_of_heading, body)
    # Two bookmarks in a row collapse into one anchor in Pandoc's reader
    # (docxImmedPrevAnchor): the second name is mapped to the first and
    # dropped. A zero-width run between them keeps both; the filter
    # removes the character.
    # Inside paragraphs only: bookmarks before a table stay together for
    # the pre-pass. The reader's state carries across paragraphs, so a
    # paragraph holding only bookmarks gets the run too.
    def within(par):
        text = ADJACENT.sub(lambda m: m.group(1) + ZWSP_RUN + m.group(2),
                            par.group(0))
        if re.fullmatch(r"<w:p>(?:<w:bookmarkStart\b[^>]*/>)+</w:p>", text):
            # First, not last: the state to reset is the previous
            # paragraph's final bookmark.
            text = "<w:p>" + ZWSP_RUN + text[len("<w:p>"):]
        return text
    body = PARAGRAPH.sub(within, body)
    body = CAPTIONED_DRAWING.sub(_bookmarks_to_caption, body)
    return head + sep + body, moved


# A picture's paragraph followed by its caption is a figure to Pandoc's
# reader only while the picture's paragraph holds the drawing and nothing
# else (Parse.hs, isCaptionable). A bookmark moved in there, as Pandoc's
# own writer places one before every figure with an id, costs the figure
# its caption; in the caption, it keeps the figure's id beside it. The
# zero-width runs that keep adjacent bookmarks apart move with them.
CAPTIONED_DRAWING = re.compile(
    r'(<w:p>\s*(?:<w:pPr>(?:(?!</w:pPr>).)*</w:pPr>)?\s*)'
    r'((?:<w:bookmarkStart\b[^>]*/>\s*|' + re.escape(ZWSP_RUN) + r'\s*)+)'
    r'(<w:r>(?:(?!</w:p>).)*?<w:drawing>(?:(?!</w:p>).)*?</w:drawing>\s*</w:r>\s*</w:p>\s*'
    r'(?:<w:bookmarkEnd\b[^>]*/>\s*)*)'
    r'(<w:p>\s*<w:pPr>(?:(?!</w:pPr>).)*<w:pStyle w:val="(?:Caption|ImageCaption|TableCaption)"'
    r'(?:(?!</w:pPr>).)*</w:pPr>)', re.S)


def _bookmarks_to_caption(m):
    drawing = re.sub(r"<w:drawing>.*?</w:drawing>", "", m.group(3), flags=re.S)
    if "<w:t" in drawing:
        return m.group(0)
    return m.group(1) + m.group(3) + m.group(4) + m.group(2)


BOOKMARK_NAME = re.compile(r'<w:bookmarkStart\b[^>]*\bw:name="([^"]+)"')
ANCHOR_LINK = re.compile(r'<w:hyperlink\b[^>]*\bw:anchor="([^"]+)"')


def keep_unlinked_bookmarks(xml):
    """A paragraph of empty links to every bookmark the document defines
    but never links to itself. Pandoc's reader keeps a bookmark's anchor
    only when a link in the same document points at it
    (removeOrphanAnchors, Readers/Docx.hs); a bookmark that another file
    links to -- an index term, a cross-chapter reference -- is deleted.
    The filter removes the empty links again. Returns (xml, count)."""
    defined = [n for n in dict.fromkeys(BOOKMARK_NAME.findall(xml))
               if not n.startswith("_")]
    linked = set(ANCHOR_LINK.findall(xml))
    unlinked = [n for n in defined if n not in linked]
    if not unlinked:
        return xml, 0
    # A link with no text at all is dropped by the reader before it can
    # record the target, so each carries a zero-width space.
    runs = "".join(f'<w:hyperlink w:anchor="{n}"><w:r><w:t>&#8203;</w:t>'
                   f'</w:r></w:hyperlink>' for n in unlinked)
    paragraph = f"<w:p>{runs}</w:p>"
    at = xml.rfind("<w:sectPr")
    if at < 0 or xml.rfind("</w:body>") < at:
        at = xml.rfind("</w:body>")
    return xml[:at] + paragraph + xml[at:], len(unlinked)


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _words(text):
    return " ".join(text.split())


def screentips(path):
    """[(target, text, tip)]: each hyperlink with a ScreenTip, in document
    order, then those in footnotes and endnotes. Pandoc 3.11's reader drops
    w:tooltip (#11869), which Pandoc's main reads since #11890 (c51b6a6,
    2026-09-25); with a release that includes it, this changes nothing,
    since a link Pandoc gave a title keeps it. target is
    what the reader makes the link's target: the relationship's target, with
    #anchor after it when there is one, or #anchor alone."""
    import xml.etree.ElementTree as ET
    found = []
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile):
        return found
    with z:
        names = set(z.namelist())
        for part in ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml"):
            if part not in names:
                continue
            rels = {}
            relpart = "word/_rels/" + part.split("/")[-1] + ".rels"
            if relpart in names:
                for rel in ET.fromstring(z.read(relpart)).iter(_PR + "Relationship"):
                    rels[rel.get("Id")] = rel.get("Target", "")
            for link in ET.fromstring(z.read(part)).iter(_W + "hyperlink"):
                tip = link.get(_W + "tooltip")
                if not tip:
                    continue
                target = rels.get(link.get(_R + "id"), "")
                anchor = link.get(_W + "anchor")
                if anchor:
                    target += "#" + anchor
                text = "".join(t.text or "" for t in link.iter(_W + "t"))
                found.append((target, _words(text), tip))
    return found


def _stringify(inlines):
    out = []
    for el in inlines:
        t, c = el.get("t"), el.get("c")
        if t == "Str":
            out.append(c)
        elif t in ("Space", "SoftBreak", "LineBreak"):
            out.append(" ")
        elif t in ("Code", "Math", "RawInline"):
            out.append(c[1])
        elif t in ("Emph", "Strong", "Underline", "Strikeout", "Superscript",
                   "Subscript", "SmallCaps"):
            out.append(_stringify(c))
        elif t in ("Span", "Quoted", "Cite", "Link"):
            out.append(_stringify(c[1]))
    return "".join(out)


def apply_screentips(docx_path, json_path):
    """Give each link Pandoc read without a title its ScreenTip, matched by
    target and text in document order; a link Pandoc merged from pieces of
    one hyperlink matches by target alone, when that target's ScreenTips all
    agree. A link that has a title keeps it, so a Pandoc that reads
    ScreenTips itself changes nothing here. Returns how many were given."""
    import json
    from collections import defaultdict, deque
    from urllib.parse import unquote
    tips = screentips(docx_path)
    if not tips:
        return 0
    by_key, by_target = defaultdict(deque), defaultdict(list)
    for target, text, tip in tips:
        by_key[(unquote(target), text)].append(tip)
        by_target[unquote(target)].append(tip)
    with open(json_path, encoding="utf-8") as fh:
        doc = json.load(fh)
    given = 0

    def walk(node):
        nonlocal given
        if isinstance(node, dict):
            if node.get("t") == "Link":
                attr, inlines, (target, title) = node["c"]
                if not title:
                    key = (unquote(target), _words(_stringify(inlines)))
                    tip = None
                    if by_key.get(key):
                        tip = by_key[key].popleft()
                    elif len(set(by_target.get(key[0], []))) == 1:
                        tip = by_target[key[0]][0]
                    if tip:
                        node["c"][2] = [target, tip]
                        given += 1
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(doc["blocks"])
    if given:
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
    return given


DECORATIVE_MARK = re.compile(r'<\w+:decorative\b[^>]*\bval="(?:1|true)"')


def decorative_media(docx_path):
    """For each picture the body and footnotes embed, whether Word marks
    each use of it decorative (Office 2019 and later write the mark in the
    drawing's properties), in document order: {key: [flag, ...]}, keyed
    both by the file's name in the package and by the SHA-1 of its bytes,
    which is how Pandoc names what it extracts."""
    import hashlib
    import posixpath
    from collections import defaultdict
    out = defaultdict(list)
    with zipfile.ZipFile(docx_path) as z:
        names = set(z.namelist())
        for part, rels in (("word/document.xml", "word/_rels/document.xml.rels"),
                           ("word/footnotes.xml", "word/_rels/footnotes.xml.rels")):
            if part not in names:
                continue
            xml = z.read(part).decode("utf-8")
            relxml = z.read(rels).decode("utf-8") if rels in names else ""
            targets = {}
            for m in re.finditer(r"<Relationship\b[^>]*>", relxml):
                ident = re.search(r'Id="([^"]+)"', m.group(0))
                target = re.search(r'Target="([^"]+)"', m.group(0))
                if ident and target:
                    targets[ident.group(1)] = target.group(1)
            for m in re.finditer(r"<w:drawing\b.*?</w:drawing>", xml, re.S):
                blip = re.search(r'<a:blip\b[^>]*r:embed="([^"]+)"', m.group(0))
                if not blip or blip.group(1) not in targets:
                    continue
                inside = posixpath.normpath(posixpath.join(
                    "word", targets[blip.group(1)]))
                flag = bool(DECORATIVE_MARK.search(m.group(0)))
                out[posixpath.basename(inside)].append(flag)
                if inside in names:
                    out[hashlib.sha1(z.read(inside)).hexdigest()].append(flag)
    return out


def mark_decorative(doc, flags):
    """Give each image Word marked decorative the class decorative, which
    is how a Markdown source says it and what the filter and the audit
    read. An image is matched by its file, by name or by the hash Pandoc
    named it with, each use in turn. Returns how many were marked."""
    import posixpath
    if not any(any(v) for v in flags.values()):
        return 0
    queues = {key: list(values) for key, values in flags.items()}
    marked = 0

    def walk(node):
        nonlocal marked
        if isinstance(node, dict):
            if node.get("t") == "Image":
                attr = node["c"][0]
                name = posixpath.basename(node["c"][2][0])
                for key in (name, name.rsplit(".", 1)[0]):
                    if queues.get(key):
                        if queues[key].pop(0) and "decorative" not in attr[1]:
                            attr[1].append("decorative")
                            marked += 1
                        break
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(doc.get("blocks", []))
    return marked


def apply_decorative(docx_path, json_path):
    """mark_decorative on a page's JSON, read from and written back to
    json_path. Returns how many images were marked."""
    import json
    flags = decorative_media(docx_path)
    if not any(any(v) for v in flags.values()):
        return 0
    with open(json_path, encoding="utf-8") as fh:
        doc = json.load(fh)
    marked = mark_decorative(doc, flags)
    if marked:
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
    return marked


# A list item's second paragraph, or its code block or figure, is a
# numbered paragraph whose level has no marker: an invisible bullet
# (Pandoc's writer uses one, lvlText " ", and so does OpenStax's export),
# indenting it under the item's text. Pandoc's reader takes it for an
# item of another list and splits the list there. Numbered with an id
# that has no definition, it's what the reader calls a list paragraph,
# which it folds into the item before it (Readers/Docx/Lists.hs).
NO_DEFINITION = "4000000"
NUM_PR = re.compile(r'(<w:numPr>\s*<w:ilvl w:val="(\d+)"\s*/>\s*<w:numId w:val=")(\d+)("\s*/>)')


def blank_marker_levels(numbering):
    """{(numId, ilvl)} of the bullet levels whose marker is blank."""
    blank = set()
    abstracts = {m.group(1): m.group(0) for m in re.finditer(
        r'<w:abstractNum\b[^>]*w:abstractNumId="(\d+)".*?</w:abstractNum>',
        numbering, re.S)}
    for m in re.finditer(r'<w:num w:numId="(\d+)"[^>]*>.*?</w:num>', numbering, re.S):
        ref = re.search(r'w:abstractNumId w:val="(\d+)"', m.group(0))
        if not ref or ref.group(1) not in abstracts:
            continue
        for lvl in re.finditer(r'<w:lvl w:ilvl="(\d+)".*?</w:lvl>',
                               abstracts[ref.group(1)], re.S):
            fmt = re.search(r'<w:numFmt w:val="([^"]*)"', lvl.group(0))
            text = re.search(r'<w:lvlText w:val="([^"]*)"', lvl.group(0))
            if fmt and fmt.group(1) in ("bullet", "none") and text is not None \
                    and not html.unescape(text.group(1)).strip():
                blank.add((m.group(1), lvl.group(1)))
    return blank


def join_continuations(xml, blank):
    """Paragraphs numbered at a blank-marker level renumbered with an id
    that has no definition. Returns (xml, count)."""
    if not blank:
        return xml, 0
    count = 0

    def one(m):
        nonlocal count
        if (m.group(3), m.group(2)) not in blank:
            return m.group(0)
        count += 1
        return m.group(1) + NO_DEFINITION + m.group(4)
    return NUM_PR.sub(one, xml), count


def join_definition_terms(doc):
    """Runs of lone terms made a description list again. A term with no
    definition (a review question, say) is written in Word as a
    Definition Term paragraph with nothing after it, and Pandoc's reader
    builds a description list only from a term followed by a definition,
    so each comes back as a Div of class Definition-Term. Each becomes a
    term with one empty definition, as it was. Returns how many terms."""
    count = 0

    def lone_term(block):
        if block.get("t") != "Div":
            return None
        attr, blocks = block["c"]
        if attr[1] != ["Definition-Term"] or len(blocks) != 1 \
                or blocks[0].get("t") not in ("Para", "Plain"):
            return None
        return blocks[0]["c"]

    def fix(blocks):
        # A joined run next to a description list the reader built is one
        # list with it, as the source's was; two the reader built are
        # left as they are.
        nonlocal count
        out, run, made = [], [], set()

        def add(block, joined):
            prev = out[-1] if out else None
            if prev is not None and prev.get("t") == "DefinitionList" \
                    and block.get("t") == "DefinitionList" \
                    and (joined or id(prev) in made):
                prev["c"].extend(block["c"])
                made.add(id(prev))
                return
            out.append(block)
            if joined:
                made.add(id(block))
        for block in blocks + [None]:
            term = lone_term(block) if block is not None else None
            if term is not None:
                run.append(term)
                continue
            if run:
                add({"t": "DefinitionList", "c": [[t, [[]]] for t in run]}, True)
                count += len(run)
                run = []
            if block is not None:
                add(block, False)
        return out

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, list) and value and all(
                        isinstance(b, dict) and "t" in b for b in value):
                    node[key] = fix(value)
                walk(node[key])
        elif isinstance(node, list):
            for i, value in enumerate(node):
                if isinstance(value, list) and value and all(
                        isinstance(b, dict) and "t" in b for b in value):
                    node[i] = fix(value)
                walk(node[i])
    doc["blocks"] = fix(doc.get("blocks", []))
    walk(doc["blocks"])
    return count


def join_nested_quotes(doc):
    """Adjacent quotes inside a quote joined, at every depth. Pandoc's
    reader wraps each quote paragraph in a quote of its own, and one more
    for each level of indent beyond its style, then joins adjacent quotes
    only where they sit: an outer quote's paragraphs come back as one
    quote, and the paragraphs of a quote inside it as a quote each.
    Returns how many were joined."""
    joined = 0

    def separator(block):
        # What a Word target writes between two quotes in a row to keep
        # them apart: a paragraph holding only a bookmark, which the
        # reader reads as an empty paragraph or an empty anchor.
        # a zero-width space and a bookmark, which the reader reads as the
        # space and an empty anchor, or the space alone.
        if block.get("t") != "Para" or not block["c"]:
            return False
        return all((el.get("t") == "Str" and not el["c"].strip("\u200b"))
                   or (el.get("t") == "Span" and el["c"][0][0].startswith(
                       ("tiq-quote-sep-", "tiq-code-sep-")) and not el["c"][1])
                   for el in block["c"])

    def fix(blocks, inside):
        nonlocal joined
        out = []
        for block in blocks:
            if block.get("t") == "BlockQuote":
                block["c"] = fix(block["c"], True)
                if inside and out and out[-1].get("t") == "BlockQuote":
                    out[-1]["c"] = fix(out[-1]["c"] + block["c"], True)
                    joined += 1
                    continue
            elif isinstance(block.get("c"), list):
                walk(block["c"])
            out.append(block)
        # The separators, once they've kept their quotes, or their code
        # blocks, apart.
        return [b for i, b in enumerate(out)
                if not (separator(b) and 0 < i < len(out) - 1
                        and out[i - 1].get("t") == out[i + 1].get("t")
                        and out[i - 1].get("t") in ("BlockQuote", "CodeBlock"))]

    def walk(node):
        if isinstance(node, list):
            if node and all(isinstance(b, dict) and "t" in b for b in node):
                node[:] = fix(node, False)
            else:
                for item in node:
                    walk(item)
        elif isinstance(node, dict) and isinstance(node.get("c"), list):
            walk(node["c"])
    doc["blocks"] = fix(doc.get("blocks", []), False)
    return joined


def id_map(docx_path):
    """{bookmark name: id} from the map a Word target writes into its
    file (docxtarget.ID_MAP_PART), or {} for any other file."""
    with zipfile.ZipFile(docx_path) as z:
        for name in z.namelist():
            if name.startswith("customXml/") and name.endswith(".xml"):
                data = z.read(name).decode("utf-8", "replace")
                if "OERforge/TextbookImprover/ids" in data:
                    return {html.unescape(b): html.unescape(n) for b, n in re.findall(
                        r'<id bookmark="([^"]*)" name="([^"]*)"\s*/>', data)}
    return {}


def apply_id_map(docx_path, json_path):
    """The page's ids, and its links to them, renamed from the bookmark
    names Pandoc's writer hashed back to what they were. Returns how many
    were renamed."""
    import json
    mapping = id_map(docx_path)
    if not mapping:
        return 0
    with open(json_path, encoding="utf-8") as fh:
        doc = json.load(fh)
    renamed = 0

    def walk(node):
        nonlocal renamed
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            c = node.get("c")
            if node.get("t") == "Link" and c[2][0].startswith("#") \
                    and c[2][0][1:] in mapping:
                c[2][0] = "#" + mapping[c[2][0][1:]]
                renamed += 1
            attr = None
            if isinstance(c, list) and c and isinstance(c[0], list) and len(c[0]) == 3 \
                    and isinstance(c[0][0], str):
                attr = c[0]
            elif node.get("t") == "Header":
                attr = c[1]
            if attr is not None and attr[0] in mapping:
                attr[0] = mapping[attr[0]]
                renamed += 1
            walk(c)
    walk(doc.get("blocks", []))
    if renamed:
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
    return renamed


def numbered_code(docx_path):
    """[(text as Pandoc reads it, text without the numbers, first number or
    0, language or None)] for each code paragraph a Word target numbered
    (each line opening with a run in the Line Number character style,
    docxtarget.number_lines) or gave its language (a _tiqCode_ bookmark)."""
    with zipfile.ZipFile(docx_path) as z:
        if "word/document.xml" not in z.namelist():
            return []
        xml = z.read("word/document.xml").decode("utf-8")
    found = []
    for para in re.findall(r"<w:p>(?:(?!</w:p>).)*?(?:LineNumber|_tiqCode_)(?:(?!</w:p>).)*</w:p>", xml, re.S):
        if 'w:val="SourceCode"' not in para:
            continue
        full, plain, numbers = [], [], []
        language = re.search(r'w:name="_tiqCode_([A-Za-z0-9]+)_\d+"', para)
        for run in re.findall(r"<w:r>.*?</w:r>", para, re.S):
            text = html.unescape("".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", run)))
            text += "\t" * len(re.findall(r"<w:tab\s*/>", run))
            if re.search(r"<w:br\s*/>", run):
                full.append("\n"), plain.append("\n")
                continue
            full.append(text)
            if 'w:rStyle w:val="LineNumber"' in run:
                numbers.append(text.strip())
            else:
                plain.append(text)
        if (numbers and numbers[0].isdigit()) or language:
            numbers = numbers or ["0"]
            found.append(("".join(full), "".join(plain), int(numbers[0]),
                          language.group(1) if language else None))
    return found


def apply_number_lines(docx_path, json_path):
    """Each code block a Word target numbered or gave a language, found by
    its text as read, given its text without the numbers, its numbering
    from its first number, and its language. Returns how many."""
    import json
    entries = numbered_code(docx_path)
    if not entries:
        return 0
    with open(json_path, encoding="utf-8") as fh:
        doc = json.load(fh)
    done = 0

    def walk(node):
        nonlocal done
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            if node.get("t") == "CodeBlock":
                for i, (full, plain, start, language) in enumerate(entries):
                    if node["c"][1] == full:
                        attr = node["c"][0]
                        node["c"][1] = plain
                        if language and language not in attr[1]:
                            attr[1].insert(0, language)
                        if start and "numberLines" not in attr[1]:
                            attr[1].append("numberLines")
                        if start and start != 1:
                            attr[2] = [kv for kv in attr[2] if kv[0] != "startFrom"] \
                                + [["startFrom", str(start)]]
                        del entries[i]
                        done += 1
                        break
                return
            walk(node.get("c"))
    walk(doc.get("blocks", []))
    if done:
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
    return done


def apply_definition_terms(json_path):
    """join_definition_terms and join_nested_quotes on a page's JSON
    file. Returns how many terms and quotes were joined."""
    import json
    with open(json_path, encoding="utf-8") as fh:
        doc = json.load(fh)
    count = join_definition_terms(doc) + join_nested_quotes(doc)
    if count:
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
    return count


JAWS_TITLE = re.compile(r'<w:bookmarkStart\b[^>]*\bw:id="(\d+)"[^>]*\bw:name="((?:Column|Row)?Title[^"]*)"[^>]*/>', re.I)


def drop_jaws_titles(xml):
    """The bookmarks JAWS reads as a table's headers, once the header
    pre-pass has read them from the original, out of the copy Pandoc
    reads, where each would be a stray anchor; one a link names stays."""
    linked = set(ANCHOR_LINK.findall(xml))
    ids = []

    def one(m):
        if m.group(2) in linked:
            return m.group(0)
        ids.append(m.group(1))
        return ""
    xml = JAWS_TITLE.sub(one, xml)
    for ident in ids:
        xml = re.sub(r'<w:bookmarkEnd\b[^>]*\bw:id="%s"[^>]*/>' % ident, "", xml)
    return xml


def repaired_copy(source, destination):
    """Write a copy of the .docx with the repairs applied to
    word/document.xml and word/footnotes.xml and every other part byte
    for byte. Returns how many bookmarks moved."""
    moved = 0
    with zipfile.ZipFile(source) as zin, \
            zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as zout:
        names = zin.namelist()
        blank = blank_marker_levels(
            zin.read("word/numbering.xml").decode("utf-8", "replace")
            if "word/numbering.xml" in names else "")
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "word/document.xml":
                text, moved = move_bookmarks_into_paragraphs(
                    drop_jaws_titles(data.decode("utf-8")))
                text, _ = keep_unlinked_bookmarks(text)
                text, _ = join_continuations(text, blank)
                data = text.encode("utf-8")
            elif info.filename == "word/footnotes.xml" and blank:
                text, _ = join_continuations(data.decode("utf-8"), blank)
                data = text.encode("utf-8")
            zout.writestr(info, data)
    return moved
