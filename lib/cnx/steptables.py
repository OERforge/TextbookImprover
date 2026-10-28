"""
cnx.steptables -- which of a book's tables only lay things out, with
nothing to head them: layout tables, which unpack-cnx.py marks
role="presentation". OpenStax's own HTML marks a table so (enki's
cnxml-to-html5.xsl) when it has no head, no caption or title, and no
label of OpenStax's, whatever its class. Here it's a table with no head
(no thead, no th), for what it holds or for where it stands
(layout_reason). And a worked example's steps that a book writes as one
formula, a step's reason in words beside its math, are made such a table
(formula_steps, at the end).

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

And for the page it's on, an inquiry organizer (organizer_page), each
chapter's first in Life, Liberty, and the Pursuit of Happiness, which
marks each kind of page with an emoji in its title: its key to the emoji
(symbol_key), each row an emoji, the kind's name, and what it's for, has
its first column declared as row headers (head_rows), the emoji heading
the row it explains; the organizer itself, the chapter's question and
objectives across it and each supporting question beside its resources,
is a layout table. 16 of each, and a person's description to write for
each key, as for any data table without a caption.

Other tables are data tables: an accounting book's exercises and journal
entries, whose debit and credit columns a layout table would lose,
tables of values, and the like. A table kept as data where its place
would make it a layout table is reported, for a person to settle with a
row of table-headers.csv.

The guess is lib/tablecensus.py's, made as convert.py makes it: of the
table's cells as Pandoc's HTML reader gives them to it, after
html-source.lua (a short row padded, an empty column dropped), a
picture's text its description and a formula its TeX (cnx.mathtex), and
a table of nothing but pictures no text at all, as the filter makes it a
figure. The guess made here is the one convert.py makes for each of the
3,011 tables in the dev-math books, and for 663 in four more.

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

import copy
import re
import unicodedata

from lxml import etree

import mathstyle
import tablecensus as tc
from mathstyle import DISPLAY_CLASS

from .bake.core import classes
from .mathml import MATHML
from .mathtex import tex

LAYOUT_STYLES = {"dev-math", "precalculus-coreq", "hs-physics"}
# The books whose tables of any class are laid out, the guess allowing,
# when OpenStax gave them no label: a dev-math book writes some of its
# steps without the class.
ANY_CLASS_STYLES = {"dev-math"}
# The books whose tables laid out for where they stand are a worked
# example's steps for the most part, outside their Key Equations: the
# dev-math books' (821 of Prealgebra 2e's 860, in solutions, the rest a box
# of properties, a comparison, or a problem laid out so), and College
# Algebra with Corequisite Support 2e's, whose worked examples and
# corequisite skills set theirs out the same way. Physics' tables so laid
# out are its grids of key terms.
STEPS_STYLES = {"dev-math", "precalculus-coreq"}
# The class steps_table gives them.
STEPS_CLASS = "steps"
# OpenStax's corn design, its math books' (cnx.project.DESIGNS, which the
# CNX suite holds these to), draws a light gray rule under every row of the
# body of a table it classes unstyled (ce-styles' design-settings/corn/
# parts/_table-settings.scss, UnnumberedUnstyledTable: each data cell's
# bottom border, 0.09rem of Grey3, #757474; a header cell has none), and the
# calculus and algebra-1 styles draw it in Grey1, #F1F1F1, a gray so light
# it's hardly seen, in Key Equations (their book.scss, KeyEquations, whose
# rule reaches only a table classed unstyled). Such a table gets the class
# row-rules, which every format but Word draws so, a Key Equations table
# in those styles row-rules-faint too, for the lighter gray; and so does a
# dev-math book's table of steps of another class, which OpenStax draws in
# a grid, a rule under each row among its lines (Rob, 2026-10-27, of a
# light rule under each step: "Everywhere OpenStax rules").
RULED_STYLES = {"additive-manufacturing", "algebra-1", "calculus", "contemporary-math",
                "dev-math", "precalculus", "precalculus-coreq", "statistics"}
FAINT_KEY_EQUATIONS = {"algebra-1", "calculus"}
ROW_RULES_CLASS = "row-rules"
FAINT_CLASS = "row-rules-faint"


def cell_text(cell, alt=True):
    """A cell's text as tablecensus reads it from Pandoc's AST (_stringify):
    a picture's description (none, with alt false), a line break as a
    space, a formula as its TeX."""
    parts = []

    def walk(el):
        name = etree.QName(el).localname
        if name == "math":
            parts.append(tex(el))
            return
        if name == "img":
            parts.append((el.get("alt") or "") if alt else "")
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
    words = False                   # any text but pictures' descriptions
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
            words = words or bool(cell_text(cell, alt=False))
            out.extend([made] * span)
            if rowspan > 1:
                for offset in range(span):
                    pending[column + offset] = rowspan - 1
            column += span
        grid.append(out)
    # A table of nothing but pictures has no text of its own, whatever
    # their descriptions say, as view_from_pandoc reads it: the filter
    # makes it a figure.
    if not words:
        for row in grid:
            for made in row:
                made.text = ""
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


def row_rules(source, style, steps):
    """The classes that draw a table with a light rule under each row of
    its body, as OpenStax draws it: ROW_RULES_CLASS for one it classes
    unstyled in a book of its corn design (RULED_STYLES), or a table of
    steps (steps) in such a book, and FAINT_CLASS beside it for one so
    classed in Key Equations in a book of FAINT_KEY_EQUATIONS; [] for any
    other."""
    unstyled = "unstyled" in classes(source)
    if style not in RULED_STYLES or not (unstyled or steps):
        return []
    faint = unstyled and style in FAINT_KEY_EQUATIONS and in_key_equations(source)
    return [ROW_RULES_CLASS] + ([FAINT_CLASS] if faint else [])


def steps_table(source, style):
    """Whether a table laid out for where it stands (layout_reason's
    "place") is given the class steps (STEPS_CLASS): in a book of
    STEPS_STYLES, outside its Key Equations, where such a table is a worked
    example's steps, each step's words beside its result, or else a box of
    properties, a comparison, or a problem laid out as it stands. Every
    format draws them without the rules a table of data has, as it draws
    the steps the unpacker lays out itself (formula_steps), while they're
    a layout table, and every format but Word with a light rule under each
    row, as OpenStax does (row_rules)."""
    return style in STEPS_STYLES and not in_key_equations(source)


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


# The style of Life, Liberty, and the Pursuit of Happiness, which marks
# each kind of page with an emoji in its title and opens each chapter with
# an inquiry organizer: a key to the emoji, and a table of the chapter's
# question, its objectives, and its supporting questions beside their
# resources.
ORGANIZER_STYLES = {"ap-history"}
_ORGANIZER = re.compile(r"(?:^|\s)Inquiry Organizer$")


def organizer_page(style, title):
    """Whether a page is an inquiry organizer, by its title, which is all
    that marks one: "10.1 📎 Inquiry Organizer"."""
    return style in ORGANIZER_STYLES and bool(
        _ORGANIZER.search(" ".join((title or "").split())))


def _symbol(text):
    """Whether a text is a symbol alone: an emoji or another of Unicode's
    symbols, with the variation selectors and joiners that dress one."""
    text = "".join(text.split())
    return 0 < len(text) <= 8 and \
        any(unicodedata.category(c) == "So" for c in text) and \
        all(unicodedata.category(c) in ("So", "Sk", "Mn", "Cf") for c in text)


def symbol_key(table):
    """Whether a table is a key to symbols: two rows or more, each opening
    with a cell that holds a symbol alone, beside words. Its first column
    heads its rows, the symbol being what each row explains."""
    rows = _rows(table)
    return len(rows) >= 2 and all(
        len(row) >= 2 and not _holds(row[0], "img", "math", "table")
        and _symbol("".join(row[0].itertext()))
        and any(cell_text(c) for c in row[1:]) for row in rows)


def head_rows(table):
    """Make each row's first cell its row header, as a key's symbol is."""
    for row in _rows(table):
        row[0].tag = "th"
        row[0].set("scope", "row")


def layout_reason(table, source, style, captioned, organizer=False):
    """Why a table as the emitter writes it is a layout table, if it may be
    one: "shape" when what it holds says so, whatever the header guess
    reads (one cell, lines to fill in, pictures with their labels, two
    lists to match); "page" when it's on an inquiry organizer (organizer),
    the organizer itself, its key having its row headers declared;
    "place" when where it stands says so, unless the guess reads a header
    row in it (HEADED): a chapter's Key Equations, one OpenStax classes
    unstyled in a book of LAYOUT_STYLES, and one with no label of
    OpenStax's in a book of ANY_CLASS_STYLES, each with no caption of its
    own (captioned: one besides the number baking gave it). None for a
    data table. A table with a head or a header cell declares its
    headers, and is one."""
    if table.find(".//thead") is not None or table.find(".//th") is not None:
        return None
    if (one_cell(table) or lines_to_fill(table) or pictures_alone(table)
            or matching_exercise(table)):
        return "shape"
    if organizer:
        return "page"
    if captioned:
        return None
    if (in_key_equations(source)
            or style in LAYOUT_STYLES and "unstyled" in classes(source)
            or style in ANY_CLASS_STYLES and not source.get("data-aria-label")):
        return "place"
    return None


# --------------------------------------------------------------------------
# a worked example's steps written as one formula
# --------------------------------------------------------------------------

# College Algebra 2e and the books written as it is set a worked example's
# steps as one formula, an mtable, a step to a row: what's worked on, the
# relation, and the result each in a column, and the step's reason in
# words in a column of its own after a wide space ("Commutative and
# associative laws of multiplication"), or an instruction in the first
# column ("Find the Fahrenheit temperature for a Celsius temperature of
# 0"). A formula's words don't wrap, so such a formula ran past its line
# in a PDF, by up to 224 points in College Algebra 2e's first chapter, and
# past a narrow window. It's set as the dev-math books set their steps: a
# layout table, its math cell for cell, each a formula, its columns
# aligned as the formula aligned them, and its words text, which wraps in
# its column (formula_steps). Lines labeled in words written as one
# formula are so too, as Chemistry 2e labels a cell's half-reactions
# ("oxidation half-reaction:").

# What only groups a formula's pieces, which the steps are read through.
GROUPING = {"mrow", "mstyle", "mpadded"}
# A word, as a step's reason or instruction has words: three letters or
# more, small letters after the first, so that a chemical formula's
# symbols (Pb, OH, aq) and an acronym aren't words.
WORD = re.compile(r"[^\W\d_]{3,}")
# The relations an equation's side stands beside: words beside one are
# the side, written in words ("Total damage = ..."), not a step's words.
RELATIONS = set("=<>\u2264\u2265\u2248\u2260\u2192\u21d2\u2261\u221d\u2243\u2245")
# Punctuation a formula sets as an operator, which ends a step's words
# ("Simplify" and an mo of ".").
PUNCTUATION = set(".,;:!?")
# Spaces in a formula's text, which keeps them with no-break spaces
# (OpenStax's "Commutative and associative", U+00A0 each) and thin ones,
# all of them Python's \s, and a zero-width space, which isn't.
SPACES = re.compile(r"[\s\u200b]+")
ALIGNMENTS = {"left", "right", "center"}
# What a formula's text set in a style is in HTML.
STYLED = {"bold": "strong", "italic": "em", "bold-italic": "strong"}


def _name(el):
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def _text(el):
    return "".join(el.itertext())


def _blank_text(text):
    return not SPACES.sub("", text or "")


def _spacing(piece):
    """Whether a piece of a formula is space alone: an mspace, or text or
    an operator that's spaces."""
    name = _name(piece)
    return name == "mspace" or (name in ("mtext", "mo", "mi") and _blank_text(_text(piece)))


def _pieces(el, style=None):
    """What an element of a formula holds, through what only groups, each
    with the style (mathvariant) it's set in, or None. Words the source
    broke over lines, a table of one column each of whose rows opens with
    text ("Commutative and associative" over "properties of
    multiplication", in College Algebra 2e's 1.2), are its rows' pieces,
    a space between each and the next."""
    out = []
    for child in el:
        name = _name(child)
        if name in GROUPING:
            out += _pieces(child, child.get("mathvariant") or style)
        elif name == "mtable" and _lines(child):
            for at, line in enumerate(_lines(child)):
                if at:
                    out.append((etree.Element("{%s}mspace" % MATHML), None))
                out += _pieces(line, child.get("mathvariant") or style)
        elif name:
            out.append((child, child.get("mathvariant") or style))
    return out


def _lines(table):
    """A table's cells, when it's one column of lines of words, each
    opening with text, after any space; or []."""
    rows = [r for r in table if _name(r)]
    cells = [[c for c in r if _name(c)] for r in rows]
    if not rows or any(_name(r) != "mtr" or len(c) != 1 or _name(c[0]) != "mtd"
                       for r, c in zip(rows, cells)):
        return []
    for (cell,) in cells:
        pieces = [p for p, _ in _pieces(cell) if not _spacing(p)]
        if not pieces or _name(pieces[0]) != "mtext":
            return []
    return [c[0] for c in cells]


def _kind(cell):
    """A cell of the steps: ("empty", 0); ("words", how many), when it
    opens with text, after any space, and its text holds a word; or
    ("math", 0)."""
    pieces = [p for p, _ in _pieces(cell) if not _spacing(p)]
    if not pieces:
        return ("empty", 0) if _blank_text(_text(cell)) else ("math", 0)
    if _name(pieces[0]) != "mtext":
        return ("math", 0)
    words = [w for p in pieces if _name(p) == "mtext"
             for w in WORD.findall(_text(p)) if w[1:].islower()]
    return ("words", len(words)) if words else ("math", 0)


def _relation(cell, end):
    """Whether a cell opens (end 0) or ends (end -1) with a relation, an
    operator or text."""
    pieces = [p for p, _ in _pieces(cell) if not _spacing(p)]
    if not pieces or _name(pieces[end]) not in ("mo", "mtext"):
        return False
    text = SPACES.sub("", _text(pieces[end]))
    return bool(text) and text[end] in RELATIONS


def _sole_table(math):
    """The mtable that's all a formula holds, through what only groups,
    an annotation (another form of the formula) aside; or None."""
    el = math
    while True:
        kids = [k for k in el if _name(k) and _name(k) not in ("annotation", "annotation-xml")]
        if len(kids) != 1:
            return None
        el = kids[0]
        if _name(el) == "mtable":
            return el
        if _name(el) not in GROUPING and _name(el) != "semantics":
            return None


def _alignment(table, row, cell, column):
    """A cell's alignment as MathML reads it: the cell's own, its row's
    for its column, its table's, or center. A row's and a table's are
    lists, their last for the columns after."""
    for value, listed in ((cell.get("columnalign"), False),
                          (row.get("columnalign"), True),
                          (table.get("columnalign"), True)):
        values = (value or "").split()
        if values:
            value = values[min(column, len(values) - 1)] if listed else values[0]
            if value in ALIGNMENTS:
                return value
    return "center"


def _beside(kinds, column, side):
    """The column of the next cell holding anything on a row, from a
    column toward a side (1, -1), or None."""
    at = column + side
    while 0 <= at < len(kinds):
        if kinds[at][0] != "empty":
            return at
        at += side
    return None


def _math_of(cell):
    """Whether a cell holds math, more than text and space: a token of
    math, an identifier, number, or operator, outside text."""
    return any(_name(e) in ("mi", "mn", "mo") and not _spacing(e)
               for e in cell.iter())


def _span(cell, attribute):
    """Whether a cell spans more than one column (columnspan) or row
    (rowspan)."""
    return (cell.get(attribute) or "1").strip() != "1"


def _trim_space(el, end):
    """The space at one end of what an element holds (end 0, its first;
    -1, its last), an mspace or text or an operator that's spaces, taken
    out, through what only groups."""
    while True:
        kids = [k for k in el if isinstance(k.tag, str)]
        if not kids:
            return
        if _spacing(kids[end]):
            el.remove(kids[end])
        elif _name(kids[end]) in GROUPING:
            el = kids[end]
        else:
            return


def _formula(cell, display, ends):
    """A cell of math as a formula of its own, in display style where the
    table set its cells so, and without the space that set it apart from
    words beside it, at the ends that have them (0, its first; -1, its
    last)."""
    math = etree.Element("{%s}math" % MATHML, nsmap={None: MATHML})
    holder = math
    if display:
        holder = etree.SubElement(math, "{%s}mstyle" % MATHML, displaystyle="true")
    for child in cell:
        if isinstance(child.tag, str):
            holder.append(copy.deepcopy(child))
    for end in ends:
        _trim_space(holder, end)
    return math


def _display_at(el, display):
    """Whether an element of a cell stands in display style: as the
    nearest mstyle above it that sets displaystyle says, or, where none
    is nearer than the cell, as its table sets its cells: the table of
    steps as display says, and a table in a cell as its own displaystyle
    says, text style unless it says otherwise."""
    for above in el.iterancestors():
        name = _name(above)
        if name == "mtd":
            table = next((a for a in above.iterancestors() if _name(a) == "mtable"), None)
            if any(_name(a) == "mtd" for a in above.iterancestors()):
                return table is not None and table.get("displaystyle") == "true"
            return display
        if name == "mstyle" and above.get("displaystyle") in ("true", "false"):
            return above.get("displaystyle") == "true"
    return display


def _displayed(pieces, display):
    """Whether a formula, the pieces of a cell it's made of, holds
    something display style draws otherwise set in display style
    (mathstyle.displayed): under an mstyle with displaystyle "true",
    nearer than one with "false", or anywhere where the table set its
    cells so (display, _display_at). OpenStax sets most such formulas'
    integral sign alone so, the integrand in text style (54 of the 97
    parts in display style in Calculus Volume 2's steps)."""
    return mathstyle.displayed(pieces, lambda piece: _display_at(piece, display))


def _display_marked(math, parent=None):
    """A formula in a span of class displaystyle (DISPLAY_CLASS), as a
    child of parent where one is given: html-source.lua sets it in display
    style, which MathML's own mstyle can't tell Pandoc's reader."""
    span = etree.Element("span", {"class": DISPLAY_CLASS}) if parent is None \
        else etree.SubElement(parent, "span", {"class": DISPLAY_CLASS})
    span.append(math)
    return span


def _words(cell, td, display=False):
    """A cell of words into an HTML cell: its text, each run of spaces one
    space, which a line can break at, bold or italic where it's set so,
    its math, each run of it a formula, in display style where the source
    set it so (_displayed, display the table's), and punctuation that ends
    a run of math text."""
    pieces = _pieces(cell)
    runs = []                       # (text, style) or [math pieces]
    for at, (piece, style) in enumerate(pieces):
        name = _name(piece)
        after = pieces[at + 1][0] if at + 1 < len(pieces) else None
        if name == "mtext" or _spacing(piece) or (
                name == "mo" and _text(piece).strip() in PUNCTUATION
                and (after is None or _name(after) == "mtext" or _spacing(after))):
            text = " " if name == "mspace" else _text(piece)
            style = STYLED.get(piece.get("mathvariant") or style) if name == "mtext" else None
            if runs and isinstance(runs[-1], tuple) and runs[-1][1] == style:
                runs[-1] = (runs[-1][0] + text, style)
            else:
                runs.append((text, style))
        elif runs and isinstance(runs[-1], list):
            runs[-1].append(piece)
        else:
            runs.append([piece])

    def add(text):
        if len(td):
            td[-1].tail = (td[-1].tail or "") + text
        else:
            td.text = (td.text or "") + text
    for run in runs:
        if isinstance(run, tuple):
            text, style = SPACES.sub(" ", run[0]), run[1]
            if style and text.strip():
                lead, body, trail = (text[:len(text) - len(text.lstrip())], text.strip(),
                                     text[len(text.rstrip()):])
                add(lead)
                etree.SubElement(td, style).text = body
                add(trail)
            else:
                add(text)
            continue
        math = etree.Element("{%s}math" % MATHML, nsmap={None: MATHML})
        for piece in run:
            kept = copy.deepcopy(piece)
            kept.tail = None
            math.append(kept)
        if _displayed(run, display):
            _display_marked(math, td)
        else:
            td.append(math)
    for el in [td] + list(td):
        if el.text:
            el.text = SPACES.sub(" ", el.text)
        if el is not td and el.tail:
            el.tail = SPACES.sub(" ", el.tail)
    if td.text:
        td.text = td.text.lstrip() or None
    if len(td) and td[-1].tail:
        td[-1].tail = td[-1].tail.rstrip() or None
    elif not len(td) and td.text:
        td.text = td.text.rstrip() or None


def formula_steps(math):
    """A formula that's a worked example's steps as an HTML table that lays
    them out (role="presentation", class formula-steps), or None. The
    formula is an mtable and nothing else; its columns, but those empty in
    every row, two or more; and its first or its last column words, a
    step's reason or instruction, in every cell of it that holds anything,
    two words or more in one at least, and not an equation's side written
    in words, beside its relation. No column between the first and the
    last holds two words in a cell, which a table of words written as a
    formula would, and one holds math. Not a table with lines between its
    rows or columns, which a layout table would lose, one with an
    equation's label, or one with a cell across columns or rows, which the
    layout table wouldn't span; and nothing but rows of cells, so that
    nothing is lost. Each cell
    of math is a formula of its own, in display style where the table set
    its cells so, each column aligned as the table aligned its first cell
    holding anything, and the space that set it apart from the words
    beside it left to the table's columns; each cell of words is text,
    left aligned, its spaces ones a line can break at, and its math
    formulas. A formula that holds something display style draws
    otherwise set in display style, all of it or a part, as the table set
    its cells or the source set the part (_displayed), is in a span of
    class displaystyle, which sets it all in display style
    (html-source.lua): Pandoc's reader drops MathML's display style, and
    with it the part can't be told from the rest."""
    table = _sole_table(math)
    if table is None or any(table.get(a, "none") != "none"
                            for a in ("rowlines", "columnlines", "frame")):
        return None
    rows = [r for r in table if _name(r)]
    if not rows or any(_name(r) != "mtr" for r in rows):
        return None
    cells = [[c for c in r if _name(c)] for r in rows]
    if any(_name(c) != "mtd" or _span(c, "columnspan") or _span(c, "rowspan")
           for row in cells for c in row):
        return None
    kinds = [[_kind(c) for c in row] for row in cells]
    width = max(len(row) for row in cells)

    def column(j):
        return [(i, kinds[i][j]) for i in range(len(rows)) if j < len(kinds[i])]
    used = [j for j in range(width) if any(k[0] != "empty" for _, k in column(j))]
    if len(used) < 2:
        return None
    wordy = []
    for j, side in ((used[0], 1), (used[-1], -1)):
        found = [(i, k) for i, k in column(j) if k[0] != "empty"]
        if any(k[0] != "words" for _, k in found) or max(k[1] for _, k in found) < 2:
            continue
        beside = [(i, _beside(kinds[i], j, side)) for i, _ in found]
        if any(at is not None and _relation(cells[i][at], 0 if side == 1 else -1)
               for i, at in beside):
            continue
        wordy.append(j)
    if not wordy:
        return None
    if any(k[0] == "words" and k[1] >= 2 for j in used[1:-1] for _, k in column(j)):
        return None
    maths = [j for j in used if j not in wordy]
    if not any(_math_of(cells[i][j]) for j in maths for i, _ in column(j)):
        return None
    # A row of values under a column of their names ("Integer | -2 | -1 |
    # 0"), a table of values written as a formula: three columns of math
    # or more, none of them a relation's.
    if len(maths) >= 3 and not any(all(_relation(cells[i][j], 0) and len(
            [p for p, _ in _pieces(cells[i][j]) if not _spacing(p)]) == 1
            for i, k in column(j) if k[0] != "empty") for j in maths):
        return None
    display = table.get("displaystyle") == "true"
    align = {}
    for j in used:
        first = next(i for i, k in column(j) if k[0] != "empty")
        align[j] = "left" if j in wordy else _alignment(table, rows[first], cells[first][j], j)
    out = etree.Element("table", {"role": "presentation", "class": "formula-steps"})
    body = etree.SubElement(out, "tbody")
    for i, row in enumerate(cells):
        tr = etree.SubElement(body, "tr")
        for j in used:
            td = etree.SubElement(tr, "td", {"style": "text-align: %s" % align[j]})
            if j >= len(row) or kinds[i][j][0] == "empty":
                continue
            if j in wordy:
                _words(row[j], td, display)
                continue
            ends = [end for end, side in ((0, -1), (-1, 1))
                    if _beside(kinds[i], j, side) in wordy]
            formula = _formula(row[j], display, ends)
            if _displayed([k for k in row[j] if _name(k)], display):
                _display_marked(formula, td)
            else:
                td.append(formula)
    return out
