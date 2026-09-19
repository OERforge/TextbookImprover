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
        # Ends stay where they were; Pandoc ignores them, and Word is
        # happy with an end before its start.
        return ("".join(END.findall(match.group(1))) + match.group(2)
                + (match.group(3) or "") + "".join(starts))

    # Only the body: a match inside a table cell would be a bookmark
    # already inside a paragraph's container, which Pandoc keeps as is.
    head, sep, body = xml.partition("<w:body>")
    if not sep:
        return xml, 0
    return head + sep + BEFORE_PARAGRAPH.sub(fix, body), moved


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
                data = text.encode("utf-8")
            zout.writestr(info, data)
    return moved
