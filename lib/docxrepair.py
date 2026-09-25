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

import re
import zipfile

# A run of bookmark starts and ends standing directly before a paragraph.
BEFORE_PARAGRAPH = re.compile(
    r"((?:<w:bookmarkStart\b[^>]*/>\s*|<w:bookmarkEnd\b[^>]*/>\s*)+)"
    r"(<w:p\b[^>]*>)(\s*<w:pPr>.*?</w:pPr>)?", re.S)
START = re.compile(r"<w:bookmarkStart\b[^>]*/>")
HEADING_STYLE = re.compile(r'<w:pStyle w:val="(?:Heading|Title|Subtitle)[^"]*"')
ZWSP_RUN = "<w:r><w:t>&#8203;</w:t></w:r>"
PARAGRAPH = re.compile(r"<w:p\b[^>]*>.*?</w:p>", re.S)
ADJACENT = re.compile(r"(<w:bookmarkStart\b[^>]*/>)(\s*(?:<w:bookmarkEnd\b[^>]*/>\s*)*)"
                      r"(?=<w:bookmarkStart)")
IN_HEADING = re.compile(r"(<w:p\b[^>]*>)(<w:pPr>.*?</w:pPr>)"
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
    return head + sep + body, moved


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


def repaired_copy(source, destination):
    """Write a copy of the .docx with the repairs applied to
    word/document.xml and every other part byte for byte. Returns how
    many bookmarks moved."""
    moved = 0
    with zipfile.ZipFile(source) as zin, \
            zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "word/document.xml":
                text, moved = move_bookmarks_into_paragraphs(
                    data.decode("utf-8"))
                text, _ = keep_unlinked_bookmarks(text)
                data = text.encode("utf-8")
            zout.writestr(info, data)
    return moved
