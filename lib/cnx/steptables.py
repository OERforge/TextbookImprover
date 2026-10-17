"""
cnx.steptables -- which of a book's tables only lay things out, with
nothing to head them: layout tables, which unpack-cnx.py marks
role="presentation". OpenStax's own HTML marks a table so (enki's
cnxml-to-html5.xsl) when it has no head, no caption or title, and no
label of OpenStax's, whatever its class. Here it's a table OpenStax
classes unstyled, with no head and no caption but its number, of one of
three kinds:

- In a book whose style lays things out in such tables (LAYOUT_STYLES):
  the dev-math books, Prealgebra 2e, Elementary Algebra 2e, and
  Intermediate Algebra 2e, whose worked examples set out their steps so,
  each step's words beside its result; College Algebra with Corequisite
  Support 2e (precalculus-coreq), whose worked examples and corequisite
  skills do; and Physics (hs-physics), whose sections open with their key
  terms in a grid.
- A table of a chapter's Key Equations (in_key_equations), in any book: a
  formula's name beside the formula, a layout table as OpenStax's own HTML
  has it. 478 in 16 books, 475 of them layout tables, the header guess
  reading a header row in the other 3. As data tables with a header
  column, which the review of the layout tables said they could as well
  be, each would want a caption and a row of table-headers.csv.
- A table of one cell (one_cell), in any book: a byline in Life, Liberty,
  and the Pursuit of Happiness, an estimate of the time a section takes
  in the College Success books, a formula in a Chemistry book's Key
  Equations. A table of one cell has nothing to head.

Other books' tables of that class are left data tables: an accounting
book's exercises and journal entries, whose debit and credit columns a
layout table would lose, Microbiology's matching exercises, and the like.

A table of the first two kinds that TextbookImprover's header guess reads
a header row in is left a data table. The guess is lib/tablecensus.py's,
made as convert.py makes it: of the table's cells as Pandoc's HTML
reader gives them to it, after html-source.lua (a short row padded, an
empty column dropped), a picture's text its description and a formula
its TeX (cnx.mathtex). Of the 2,541 tables the dev-math books class
unstyled, 2,536 have no head and no caption but a number, and the guess
reads a header row in 7 of those: 5 tables of data ("Binomial Squares |
Product of Conjugates") and 2 of steps it misreads. The other 2,529 are
layout tables. The guess made here is the one convert.py makes for each
of the 3,011 tables in those books, and for 663 in four more. In
College Algebra with Corequisite Support 2e, 89 of the 93 such tables
outside its Key Equations are layout tables, the other 4 having a
head; in Physics, 75 grids of key terms. Tables of one cell: 259 in
Life, Liberty, 137 in the three College Success books, and 17 in each
Chemistry book's Key Equations.

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

from lxml import etree

import tablecensus as tc

from .bake.core import classes
from .mathtex import tex

LAYOUT_STYLES = {"dev-math", "precalculus-coreq", "hs-physics"}


def cell_text(cell):
    """A cell's text as tablecensus reads it from Pandoc's AST (_stringify):
    a picture's description, a line break as a space, a formula as its
    TeX."""
    parts = []

    def walk(el):
        name = etree.QName(el).localname
        if name == "math":
            parts.append(tex(el))
            return
        if name == "img":
            parts.append(el.get("alt") or "")
            return
        if name == "br":
            parts.append(" ")
        parts.append(el.text or "")
        for child in el:
            if isinstance(child.tag, str):
                walk(child)
            parts.append(child.tail or "")
    walk(cell)
    return " ".join("".join(parts).split())


def _bold(cell):
    """Whether all a cell's text is bold (Pandoc's Strong)."""
    text = cell_text(cell)
    strong = " ".join(" ".join(cell_text(s) for s in cell.iter("strong", "b")).split())
    return bool(text) and strong == text


def _number(text):
    try:
        return max(1, int(text or 1))
    except ValueError:
        return 1


def _blank(cell):
    """Whether a cell is empty, as html-source.lua's blank_cell judges:
    no picture, formula, code, or table, and no text but spaces (Lua's
    %s, and a no-break space)."""
    if any(etree.QName(e).localname in ("img", "math", "code", "pre", "table")
           for e in cell.iter() if isinstance(e.tag, str) and e is not cell):
        return False
    return not "".join(cell.itertext()).translate(
        {ord(c): None for c in " \t\n\r\f\v\u00a0"})


def _slots(rows):
    """(row, column) -> (cell, the row it starts in, whether this is
    where it starts), each cell over the columns and rows it spans."""
    at = {}
    for r, cells in enumerate(rows):
        c = 0
        for cell in cells:
            while (r, c) in at:
                c += 1
            span, rowspan = _number(cell.get("colspan")), _number(cell.get("rowspan"))
            for dr in range(rowspan):
                for dc in range(span):
                    at[(r + dr, c + dc)] = (cell, r, dr == 0 and dc == 0)
            c += span
    return at


def _padded(rows):
    """Rows with an empty cell for each column a row doesn't reach, as
    Pandoc's reader pads a short row."""
    at = _slots(rows)
    width = max((c + 1 for r, c in at if r < len(rows)), default=0)
    return [cells + [etree.Element("td") for c in range(width) if (r, c) not in at]
            for r, cells in enumerate(rows)]


def _without_empty_columns(rows):
    """Each cell's column span once the columns every cell of which is
    empty are dropped, as html-source.lua's drop_empty_columns drops
    them: a cell in such a column dropped, a cell spanning one narrowed.
    A dropped cell isn't in what's returned."""
    at = _slots(rows)
    spans = {cell: _number(cell.get("colspan")) for cells in rows for cell in cells}
    width = max((c + 1 for _, c in at), default=0)
    if width < 2:
        return spans
    empty = []
    for c in range(width):
        lone, ok = 0, True
        for r in range(len(rows)):
            slot = at.get((r, c))
            if slot and spans[slot[0]] == 1:
                if _blank(slot[0]):
                    lone += 1
                else:
                    ok = False
        empty.append(ok and lone > 0)
    if not any(empty) or all(empty):
        return spans
    out = dict(spans)
    for c in range(width):
        if not empty[c]:
            continue
        for r in range(len(rows)):
            slot = at.get((r, c))
            if slot and slot[2] and spans[slot[0]] == 1:
                out.pop(slot[0], None)
            elif slot and spans[slot[0]] > 1 and r == slot[1] and slot[0] in out:
                out[slot[0]] = max(1, out[slot[0]] - 1)
    return out


def view(table):
    """A tablecensus View of a table as the emitter writes it, read as
    tablecensus.view_from_pandoc reads one Pandoc read from the page: the
    head's rows marked, a row span as Word's vertical merge, so the grid
    lines up the same."""
    rows, marked, foot = [], [], []
    for part in table:
        if not isinstance(part.tag, str):
            continue
        if part.tag in ("thead", "tbody", "tfoot"):
            found = part.findall("tr")
        elif part.tag == "tr":
            found = [part]
        else:
            continue
        for tr in found:
            if part.tag == "thead":
                marked.append(len(rows))
            elif part.tag == "tfoot":
                foot.append(len(rows))
            rows.append(tr)
    rows = _padded([[c for c in tr if isinstance(c.tag, str) and c.tag in ("td", "th")]
                    for tr in rows])
    spans = _without_empty_columns(rows)
    grid, pending = [], {}          # column -> rows still covered
    for cells in rows:
        out, column = [], 0
        cells = [c for c in cells if c in spans]
        while cells or any(c >= column for c in pending):
            if column in pending:
                out.append(tc.Cell.of("", vmerge="continue"))
                pending[column] -= 1
                if not pending[column]:
                    del pending[column]
                column += 1
                continue
            if not cells:
                break
            cell = cells.pop(0)
            span = spans[cell]
            rowspan = _number(cell.get("rowspan"))
            made = tc.Cell.of(cell_text(cell), bold=_bold(cell),
                              image=cell.find(".//img") is not None, span=span,
                              vmerge="restart" if rowspan > 1 else None)
            out.extend([made] * span)
            if rowspan > 1:
                for offset in range(span):
                    pending[column + offset] = rowspan - 1
            column += span
        grid.append(out)
    return tc.View(grid, marked=marked, foot=foot)


def header_guess(table):
    """The header guess's value for a table (tablecensus.guess_table):
    first-row, first-column, both, unknown, and so on."""
    v = view(table)
    kind, ev, _, _ = tc.classify(v)
    return tc.guess_table(v, kind, ev)[0]


# The header guess's values for a table with a header row.
HEADED = ("first-row", "both")


def one_cell(table):
    """Whether a table as the emitter writes it is one cell: one row of
    its own, of one cell."""
    rows = table.xpath("./tr | ./thead/tr | ./tbody/tr | ./tfoot/tr")
    return len(rows) == 1 and len([c for c in rows[0]
                                   if isinstance(c.tag, str) and c.tag in ("td", "th")]) == 1


def in_key_equations(source):
    """Whether a source table is in a chapter's Key Equations (OpenStax's
    section key-equations, which baking moves to the chapter's end)."""
    return any("key-equations" in classes(a) for a in source.iterancestors())


def may_be_layout(table, source, style, captioned):
    """Whether a table as the emitter writes it may only lay things out:
    classed unstyled by OpenStax (the source table's classes), with no
    caption of its own (captioned: one besides the number baking gave it)
    and no head, and of one cell, in a chapter's Key Equations, or in a
    book of LAYOUT_STYLES. One of more cells is a layout table unless the
    header guess reads a header row in it (HEADED)."""
    if (captioned or "unstyled" not in classes(source)
            or table.find(".//thead") is not None or table.find(".//th") is not None):
        return False
    return one_cell(table) or in_key_equations(source) or style in LAYOUT_STYLES
