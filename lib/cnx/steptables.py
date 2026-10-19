"""
cnx.steptables -- which of a book's tables only lay things out, with
nothing to head them: layout tables, which unpack-cnx.py marks
role="presentation". OpenStax's own HTML marks a table so (enki's
cnxml-to-html5.xsl) when it has no head, no caption or title, and no
label of OpenStax's, whatever its class. Here it's a table with no head
(no thead, no th), for what it holds or for where it stands
(layout_reason).

For what it holds, in any book, of any class, with any caption, and
whatever the header guess reads:

- One cell (one_cell): a byline in Life, Liberty, and the Pursuit of
  Happiness, an estimate of the time a section takes in the College
  Success books, a formula alone in a Chemistry book's Key Equations, a
  template or a peer-review form in Writing Guide with Handbook. One
  cell has nothing to head. Of the 453 tables of one cell in the 67
  books, all but 2 with a head (Entrepreneurship's) are layout tables.
- Lines to fill in and nothing else (lines_to_fill): the recording
  sheets of the labs in Statistics (10) and Introductory Statistics 2e
  (1), blanks in every cell.
- Pictures, each with a label at most (pictures_alone): graphs and
  diagrams side by side to compare, most labeled with a letter, in
  Algebra 1 (10) and Contemporary Mathematics (2). The filter makes a
  table of pictures and nothing else a figure.
- Two lists to match (matching_exercise): Microbiology's (13),
  Principles of Financial Accounting's (10) and Managerial Accounting's
  (8), Biology 2e's (2), and Algebra 1's (1). A row is no record, since
  the item beside another isn't its match, so neither column heads the
  other; the guess read a header column in 23 of the 34, which would
  have announced each item of the second list under the one beside it.

For where it stands, with no caption but its number, unless the guess
reads a header row in it (HEADED):

- In a dev-math book (Prealgebra 2e, Elementary Algebra 2e, and
  Intermediate Algebra 2e), whose worked examples set out their steps
  so, each step's words beside its result: a table OpenStax classes
  unstyled, and one of another class with no label of OpenStax's
  (ANY_CLASS_STYLES), as OpenStax's own HTML has it. Of the 2,541
  tables those books class unstyled, 2,536 have no head and no caption
  but a number, and the guess reads a header row in 7 of those: 5
  tables of data ("Binomial Squares | Product of Conjugates") and 2 of
  steps it misreads. The other 2,529 are layout tables. Of the 112
  tables of other classes with no head, no caption but a number, and
  no label, the guess reads a header row in 2 (Prealgebra 2e's
  properties of equality in a box, Elementary Algebra 2e's steps across
  three problems), and the other 110 are steps and boxes of properties
  written without the class, Elementary Algebra 2e's 103 most of them.
  The 102 with a label are tables of values and of data most of them
  ("x | y | (x, y)" under its equation, "Monday | -504"), and stay data
  tables, as OpenStax's own HTML has them; the guess reads no header
  row in 22 of those, 12 of them data.
- In College Algebra with Corequisite Support 2e (precalculus-coreq),
  whose worked examples and corequisite skills do the same, and Physics
  (hs-physics), whose sections open with their key terms in a grid, a
  table OpenStax classes unstyled (LAYOUT_STYLES): 89 of the 93 such
  tables outside the corequisite book's Key Equations, the other 4
  having a head, and Physics' 75 grids. The corequisite book's tables
  of other classes are tables of values and forms.
- A table of a chapter's Key Equations (in_key_equations), in any book,
  of any class: a formula's name beside the formula, a layout table as
  OpenStax's own HTML has it. 480 in 16 books, 477 of them layout
  tables, the guess reading a header row in the other 3, and 2 of the
  477 classed unnumbered, not unstyled (University Physics Volume 2's
  chapter 13 and Volume 3's chapter 10). As data tables with a header
  column, which the review of the layout tables said they could as well
  be, each would want a caption and a row of table-headers.csv.

Other tables are data tables: an accounting book's exercises and journal
entries, whose debit and credit columns a layout table would lose,
tables of values, and the like. A table kept as data where its place
would make it a layout table is reported, for a person to settle with a
row of table-headers.csv.

The guess is lib/tablecensus.py's, made as convert.py makes it: of the
table's cells as Pandoc's HTML reader gives them to it, after
html-source.lua (a short row padded, an empty column dropped), a
picture's text its description and a formula its TeX (cnx.mathtex). The
guess made here is the one convert.py makes for each of the 3,011 tables
in the dev-math books, and for 663 in four more.

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

from lxml import etree

import tablecensus as tc

from .bake.core import classes
from .mathtex import tex

LAYOUT_STYLES = {"dev-math", "precalculus-coreq", "hs-physics"}
# The books whose tables of any class are laid out, the guess allowing,
# when OpenStax gave them no label: a dev-math book writes some of its
# steps without the class.
ANY_CLASS_STYLES = {"dev-math"}


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


def _rows(table):
    """A table's rows as the emitter writes them, each a list of its cells."""
    return [[c for c in tr if isinstance(c.tag, str) and c.tag in ("td", "th")]
            for tr in table.xpath("./tr | ./thead/tr | ./tbody/tr | ./tfoot/tr")]


def one_cell(table):
    """Whether a table as the emitter writes it is one cell: one row of
    its own, of one cell."""
    rows = _rows(table)
    return len(rows) == 1 and len(rows[0]) == 1


def in_key_equations(source):
    """Whether a source table is in a chapter's Key Equations (OpenStax's
    section key-equations, which baking moves to the chapter's end)."""
    return any("key-equations" in classes(a) for a in source.iterancestors())


def _holds(cell, *names):
    return any(etree.QName(e).localname in names
               for e in cell.iter() if isinstance(e.tag, str) and e is not cell)


def lines_to_fill(table):
    """Whether every cell is empty or a line to write on, and one at least
    a line: a form to fill in, which has nothing to head."""
    lines = 0
    for cell in (c for row in _rows(table) for c in row):
        if _holds(cell, "img", "math", "code", "pre", "table"):
            return False
        text = "".join(cell.itertext())
        if text.strip(" _\t\n\r\f\v\u00a0"):
            return False
        lines += "_" in text
    return lines > 0


# A picture's label beside it, at most: "Graph A".
LABEL_WORDS = 4


def pictures_alone(table):
    """Whether every cell that holds anything holds a picture, with at most
    a short label beside it: pictures laid out in rows. The filter makes a
    table of pictures and nothing else a figure; one with labels is laid
    out."""
    pictures = 0
    for cell in (c for row in _rows(table) for c in row):
        words = " ".join(cell.itertext()).split()
        if not _holds(cell, "img"):
            if words or _holds(cell, "math", "code", "pre", "table"):
                return False
            continue
        if len(words) > LABEL_WORDS or _holds(cell, "math", "code", "pre", "table"):
            return False
        pictures += 1
    return pictures > 0


_ROMAN = re.compile(r"(?:x{0,3})(?:ix|iv|v?i{0,3})")
_MARK = re.compile(r"\s*(?:(_{2,})|\(?([0-9]{1,3}|[A-Za-z]|[ivxIVX]{1,6})[.)])\s*\S")


def _series(texts):
    """The one series of marks every text opens with, a blank to fill or
    the numbers, capitals, small letters, or roman numerals of a list, or
    None."""
    kinds = set()
    for text in texts:
        found = _MARK.match(text)
        if not found:
            return None
        blank, mark = found.groups()
        if blank:
            kinds.add("blank")
        elif mark.isdigit():
            kinds.add("number")
        elif mark.lower() == mark and _ROMAN.fullmatch(mark) and len(mark) > 1:
            kinds.add("roman")
        elif len(mark) == 1:
            kinds.add("capital" if mark.isupper() else "small")
        else:
            return None
    # A lone i, v, or x is a small letter or a roman numeral, which the
    # column's other marks decide.
    if kinds == {"roman", "small"} and all(
            _ROMAN.fullmatch(_MARK.match(t).group(2) or "") for t in texts):
        return "roman"
    return kinds.pop() if len(kinds) == 1 else None


def matching_exercise(table):
    """Whether a table is two lists side by side, each item to be matched
    with one of the other's: two columns of three items or more, each
    column's items opening with marks of one series (a blank to fill,
    numbers, capitals, small letters, roman numerals), the two series
    different. A row is no record: the item beside another isn't its
    match, so neither column heads the other."""
    rows = _rows(table)
    if len(rows) < 3 or any(len(row) != 2 for row in rows):
        return False
    left = [cell_text(row[0]) for row in rows if cell_text(row[0])]
    right = [cell_text(row[1]) for row in rows if cell_text(row[1])]
    if len(left) < 3 or len(right) < 3:
        return False
    first, second = _series(left), _series(right)
    return first is not None and second is not None and first != second


def layout_reason(table, source, style, captioned):
    """Why a table as the emitter writes it is a layout table, if it may be
    one: "shape" when what it holds says so, whatever the header guess
    reads (one cell, lines to fill in, pictures with their labels, two
    lists to match); "place" when where it stands does, unless the guess
    reads a header row in it (HEADED): a chapter's Key Equations, one
    OpenStax classes unstyled in a book of LAYOUT_STYLES, and one with no
    label of OpenStax's in a book of ANY_CLASS_STYLES, each with no
    caption of its own (captioned: one besides the number baking gave it).
    None for a data table. A table with a head or a header cell declares
    its headers, and is one."""
    if table.find(".//thead") is not None or table.find(".//th") is not None:
        return None
    if (one_cell(table) or lines_to_fill(table) or pictures_alone(table)
            or matching_exercise(table)):
        return "shape"
    if captioned:
        return None
    if (in_key_equations(source)
            or style in LAYOUT_STYLES and "unstyled" in classes(source)
            or style in ANY_CLASS_STYLES and not source.get("data-aria-label")):
        return "place"
    return None
