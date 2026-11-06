"""
headercells.py -- a table's empty header cell written as a data cell.

Pandoc's HTML writer makes every cell of a table's head row a <th>, and
every cell of a body's row-head columns, whatever the cell holds
(tableRowToHtml and tableCellToHtml, Writers/HTML.hs, read at 3.13): a
table whose rows' labels run down its first column has an empty <th> at
its top left, which says it heads a column and names it nothing. A Lua
filter can't change that, since the writer picks the element by the
row, not the cell. axe-core reports such a cell (empty-table-header, one
of its best-practice rules, under --best-practice), and W3C's tables
tutorial codes a corner as an empty <td>
(https://www.w3.org/WAI/tutorials/tables/two-headers/), so a page, an
EPUB's chapter file, and a presentation have each empty <th> written as
a <td> after the writer, its attributes kept but scope and abbr, which a
data cell doesn't take. Chrome then exposes the cell as a cell rather
than as a column header with no name (measured, 2026-11-06).

Empty means holding nothing but white space and no-break spaces: a cell
with a picture, a formula, or any element at all is left as it is.

Pandoc's stylesheets, a page's and an EPUB's, draw a line over each <th>,
a head row's and a row head's, with more room above its text than a
<td> has. A page's and an EPUB chapter's cell is marked (class
empty-header), and page.css draws them over it, so the table looks as it
did: an empty row head is the first cell of its row, where a data cell
can be empty too. A presentation's theme draws a <th> as it draws a
<td>, and the copy of an HTML source has the author's stylesheet, whose
cell was a <td> before the sidecar made its row a head row, so those
aren't marked.

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

# A <th> start tag, its attributes whatever their quotes hold, then nothing
# but white space or a no-break space, as a character or as each of the
# references Pandoc's writers and Word's HTML write for one, before </th>.
EMPTY = re.compile(r"<th\b((?:[^<>\"']|\"[^\"]*\"|'[^']*')*)>"
                   r"((?:\s|\u00a0|&nbsp;|&#160;|&#x0*a0;)*)</th\s*>", re.I)
# The attributes a <td> doesn't take.
HEADER_ONLY = re.compile(r"""\s+(?:scope|abbr)\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'>]+)""",
                         re.I)
CLASS = re.compile(r"""(\sclass\s*=\s*)(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""", re.I)
MARK = "empty-header"


def _marked(attributes):
    """The attributes with MARK among their classes."""
    found = CLASS.search(attributes)
    if not found:
        return ' class="%s"' % MARK + attributes
    names = next(g for g in found.groups()[1:] if g is not None).split()
    if MARK not in names:
        names.append(MARK)
    return (attributes[:found.start()] + '%s"%s"' % (found.group(1), " ".join(names))
            + attributes[found.end():])


def empty_as_data(html, marked=False):
    """(html, count): each empty <th> in html written as a <td>, what
    white space it holds kept, of class empty-header if marked."""
    count = 0

    def cell(match):
        nonlocal count
        count += 1
        attributes = HEADER_ONLY.sub("", match.group(1))
        return "<td%s>%s</td>" % (_marked(attributes) if marked else attributes,
                                  match.group(2))
    return EMPTY.sub(cell, html), count
