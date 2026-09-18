"""
tablecensus -- read the tables in a Word document and say what shape they are.

The classification and the guess behind util/table-census.py and
bin/table-headers.py, in one place so the census tool and the conversion
pre-pass cannot drift apart. Reads word/document.xml directly through the
standard library; needs no Pandoc, and can run anywhere Python 3 does.

Three things live here:

- classify(tbl): what the file says about a table. Returns a kind --
  first-row, first-column, both, or one of the shapes no sidecar value
  covers -- with the evidence it read and the table's dimensions.

- explain(tbl): the value a table-headers sidecar would be prefilled
  with, and the reason. guess(tbl) is the value alone. See explain() for
  the rule, which reads content as well as formatting because these books
  rarely mark a row-header column in any way a file can be asked about.

- table_key(tbl): the sidecar key, a SHA-256 over the table as it sits in
  the source. See table_key() for exactly what is hashed.

The value names say which line of the table holds headers, which is how
LaTeX's table/header-rows and table/header-columns are named and how
Pandoc's row_head_columns is named.

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

import hashlib
import re
import zipfile
import xml.etree.ElementTree as ET

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def q(tag):
    return f"{{{W}}}{tag}"


# --------------------------------------------------------------------------
# XML walking
# --------------------------------------------------------------------------

def top_level_tables(body):
    """Tables that are not nested inside another table's cell."""
    for child in body:
        if child.tag == q("tbl"):
            yield child


def all_tables(body, depth=0):
    """Every table, with its nesting depth."""
    for child in body:
        if child.tag == q("tbl"):
            yield child, depth
            for row in child.findall(q("tr")):
                for cell in row.findall(q("tc")):
                    yield from all_tables(cell, depth + 1)


MATH = "http://schemas.openxmlformats.org/officeDocument/2006/math"


def cell_text(tc):
    """Everything readable in a cell, including equations.

    A cell's visible content can be an OMML equation rather than runs of
    text, and then w:t finds nothing: 336 cells across the five books look
    empty to a w:t-only reader and are not. That misleads the guess -- an
    equation body is not a prose body and not an empty one -- and it is
    worse for a key computed from cell text, since two tables differing
    only in their equations hash the same. Three tables in the statistics
    book do exactly that.

    Paragraphs and line breaks are separated rather than run together, so
    a cell holding two paragraphs does not read as one word and does not
    hash the same as the cell that genuinely holds the concatenation.
    """
    parts = []
    for node in tc.iter():
        tag = node.tag
        if tag == q("t") or tag == "{%s}t" % MATH:
            parts.append(node.text or "")
        elif tag in (q("br"), q("cr")):
            parts.append("\n")
        elif tag == q("tab"):
            parts.append("\t")
        elif tag == q("p") and parts and parts[-1] != "\n":
            parts.append("\n")
    return "".join(parts).strip("\n")


def cell_has_image(tc):
    for tag in ("drawing", "pict", "object"):
        if tc.find(f".//{q(tag)}") is not None:
            return True
    return False


def grid_span(tc):
    tcpr = tc.find(q("tcPr"))
    if tcpr is None:
        return 1
    gs = tcpr.find(q("gridSpan"))
    if gs is None:
        return 1
    try:
        return int(gs.get(q("val"), "1"))
    except ValueError:
        return 1


def v_merge(tc):
    """Return None, 'restart', or 'continue'."""
    tcpr = tc.find(q("tcPr"))
    if tcpr is None:
        return None
    vm = tcpr.find(q("vMerge"))
    if vm is None:
        return None
    return "restart" if vm.get(q("val")) == "restart" else "continue"


def is_shaded(tc):
    tcpr = tc.find(q("tcPr"))
    if tcpr is None:
        return False
    shd = tcpr.find(q("shd"))
    if shd is None:
        return False
    fill = (shd.get(q("fill")) or "auto").lower()
    val = (shd.get(q("val")) or "clear").lower()
    if fill not in ("auto", "ffffff", "") or val not in ("clear", "nil"):
        return True
    return False


def is_bold(tc):
    """All text-bearing runs in the cell are bold."""
    runs = [r for r in tc.iter(q("r")) if "".join(t.text or "" for t in r.iter(q("t"))).strip()]
    if not runs:
        return False
    for r in runs:
        rpr = r.find(q("rPr"))
        if rpr is None:
            return False
        b = rpr.find(q("b"))
        if b is None or b.get(q("val")) in ("0", "false"):
            return False
    return True


def repeats_as_header(tr):
    """True when the row is marked to repeat as a header.

    The element's presence is not enough: w:val="0" or "false" turns the
    property off, and a reader that only checks for the tag counts those
    rows as headers. Pandoc had this exact bug until 3.10. None of the
    899 files in the three OpenStax books carry a disabled tblHeader, so
    the counts were unaffected -- but the next corpus may.
    """
    trpr = tr.find(q("trPr"))
    if trpr is None:
        return False
    header = trpr.find(q("tblHeader"))
    if header is None:
        return False
    return header.get(q("val")) not in ("0", "false", "off")


def tbl_look(tbl):
    """Table-style conditional formatting flags, e.g. firstRow / firstColumn."""
    tblpr = tbl.find(q("tblPr"))
    look = {}
    if tblpr is None:
        return look
    el = tblpr.find(q("tblLook"))
    if el is None:
        return look
    for name in ("firstRow", "lastRow", "firstColumn", "lastColumn"):
        v = el.get(q(name))
        if v is None:
            # Older files pack the flags into a hex val attribute.
            continue
        look[name] = v in ("1", "true")
    val = el.get(q("val"))
    if val and not look:
        try:
            bits = int(val, 16)
            look["firstRow"] = bool(bits & 0x0020)
            look["lastRow"] = bool(bits & 0x0040)
            look["firstColumn"] = bool(bits & 0x0080)
            look["lastColumn"] = bool(bits & 0x0100)
        except ValueError:
            pass
    return look


def table_style(tbl):
    tblpr = tbl.find(q("tblPr"))
    if tblpr is None:
        return ""
    st = tblpr.find(q("tblStyle"))
    return st.get(q("val"), "") if st is not None else ""


# --------------------------------------------------------------------------
# Grid model
# --------------------------------------------------------------------------

class Cell:
    __slots__ = ("text", "bold", "shaded", "image", "span", "vmerge")

    def __init__(self, tc):
        self.text = " ".join(cell_text(tc).split())
        self.bold = is_bold(tc)
        self.shaded = is_shaded(tc)
        self.image = cell_has_image(tc)
        self.span = grid_span(tc)
        self.vmerge = v_merge(tc)


def build_grid(tbl):
    """Rows of Cell, expanded across gridSpan so columns line up."""
    grid = []
    for tr in tbl.findall(q("tr")):
        row = []
        for tc in tr.findall(q("tc")):
            c = Cell(tc)
            row.extend([c] * c.span)
        grid.append(row)
    return grid


def looks_like_header_band(cells, allow_blank_corner=False):
    """A run of cells that reads as headers: text in all of them, and either
    uniformly bold or uniformly shaded.

    A matrix table's top-left cell is normally blank -- it belongs to neither
    band -- so when checking row 1 or column 1 the corner is allowed to be
    empty, and is then excluded from the bold/shaded test.
    """
    if not cells:
        return False
    if allow_blank_corner and not cells[0].text:
        cells = cells[1:]
    if not cells:
        return False
    if any(not c.text for c in cells):
        return False
    return all(c.bold for c in cells) or all(c.shaded for c in cells)


def is_full_width_band(row):
    """One cell spanning the whole row -- a title row or a grouping row."""
    if not row:
        return False
    return len(set(id(c) for c in row)) == 1


NUMERIC = re.compile(r"^[-+(]?[\d.,]+[)%]?$")


def mostly_numeric(cells):
    vals = [c.text for c in cells if c.text]
    if not vals:
        return False
    hits = sum(1 for v in vals if NUMERIC.match(v))
    return hits >= max(1, int(0.6 * len(vals)))


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------

def classify(tbl):
    grid = build_grid(tbl)
    if not grid:
        return "empty", [], 0, 0

    nrows = len(grid)
    ncols = max(len(r) for r in grid)
    ev = []

    look = tbl_look(tbl)
    style = table_style(tbl)
    if style:
        ev.append(f"style={style}")
    if look.get("firstRow"):
        ev.append("tblLook:firstRow")
    if look.get("firstColumn"):
        ev.append("tblLook:firstColumn")

    # Layout table: nothing but images (and blank cells).
    flat = [c for r in grid for c in r]
    if any(c.image for c in flat) and not any(c.text for c in flat):
        return "layout(image-only)", ev, nrows, ncols
    if nrows == 1 and ncols == 1:
        return "layout(single-cell)", ev, nrows, ncols

    marked = [i for i, tr in enumerate(tbl.findall(q("tr"))) if repeats_as_header(tr)]
    if marked:
        ev.append("tblHeader row " + ",".join(str(i + 1) for i in marked))

    first_row = grid[0]
    first_col = [r[0] for r in grid if r]

    title_row = is_full_width_band(first_row) and bool(first_row[0].text)
    if title_row:
        ev.append("row 1 is one merged cell")

    # Which row, if any, reads as a header band?
    header_rows = [i for i, r in enumerate(grid)
                   if not is_full_width_band(r)
                   and looks_like_header_band(r, allow_blank_corner=(i == 0))]

    has_row1 = 0 in header_rows or 0 in marked
    blank_corner = bool(first_row) and not first_row[0].text
    if has_row1 and blank_corner:
        ev.append("blank corner cell")

    # Which column? Skip the header row so it does not poison the scan.
    body_start = 1 if has_row1 else 0
    col0 = [r[0] for r in grid[body_start:] if r and not is_full_width_band(r)]
    header_col = (looks_like_header_band(col0, allow_blank_corner=(body_start == 0))
                  and not mostly_numeric(col0))
    if header_col:
        ev.append("first column bold/shaded, non-numeric")

    # Grouping rows partway down: a merged full-width row below row 1.
    grouping = [i for i, r in enumerate(grid[1:], start=1)
                if is_full_width_band(r) and r[0].text]
    if grouping:
        ev.append(f"full-width band at row {','.join(str(i + 1) for i in grouping)}")

    if header_rows:
        ev.append(f"header-looking row {','.join(str(i + 1) for i in header_rows)}")

    if title_row and (1 in header_rows or 1 in marked):
        kind = "title-row-then-headers"
    elif has_row1 and header_col:
        kind = "both"
    elif has_row1:
        kind = "first-row"
    elif header_col:
        kind = "first-column"
    elif header_rows:
        kind = f"headers-not-in-row-1(row {header_rows[0] + 1})"
    else:
        kind = "no-header-signal"

    # Merged cells anywhere in the top two rows suggest a stacked header.
    top = grid[:2]
    if any(c.span > 1 for r in top for c in r) or any(
            c.vmerge for r in grid for c in r):
        ev.append("merged cells present")

    # A first column of non-numeric labels over an otherwise numeric body is
    # the population that may want scope="row" as well. Formatting cannot
    # settle it -- a frequency table's interval column and a contingency
    # table's category column look identical in the DOCX -- so this is
    # reported for review rather than acted on.
    if kind == "first-row":
        body_rows = [r for r in grid[1:] if r and not is_full_width_band(r)]
        if len(body_rows) >= 2:
            c0 = [r[0] for r in body_rows]
            rest = [c for r in body_rows for c in r[1:]]
            if (all(c.text for c in c0) and not mostly_numeric(c0)
                    and rest and mostly_numeric(rest)):
                ev.append("REVIEW: first column is a non-numeric label column")

    return kind, ev, nrows, ncols


def parse_number(text):
    m = NUMERIC.match(text)
    if not m:
        return None
    try:
        return float(re.sub(r"[^\d.-]", "", text) or "x")
    except ValueError:
        return None


def text_row_over_numbers(rows):
    """A row of words with nothing but numbers underneath it.

    The change of type is the signal. Nothing in the file marks these rows
    -- no bold, no shading, no repeat-header setting -- but a row reading
    Labor | Wage above six rows of figures is a header row by any reading,
    and 275 tables across five books have this shape. 271 of them the rest
    of the rule already treats as having a header row, which is what makes
    the other four safe to treat the same way.

    Strict on the top row: every cell filled, and not one of them parsing
    as a number. A transposed table opening `# Lumberjacks | 1 | 2 | 3`
    has numbers in row 1 and must not reach here, because its headers run
    down the side.

    One column counts. `Weight in ounces` over eleven measurements is a
    header row, and a one-column table has no other way to show one:
    every row of it spans the full width, so the merged-row tests cannot
    help and formatting is otherwise the only signal.
    """
    if len(rows) < 3:
        return False
    top = rows[0]
    if any(not c.text for c in top):
        return False
    if any(NUMERIC.match(c.text) for c in top):
        return False
    body = [c for r in rows[1:] for c in r]
    return bool(body) and mostly_numeric(body)


def blank_corner_matrix(rows):
    """A blank top-left cell with labels along both edges: a matrix table.

    An author who leaves the corner empty has said something: the first
    column does not belong under the first row's heading, because the two
    label different axes. Nothing else in the file has to agree -- this
    fires with no bold, no shading, and no repeat-header row, which is the
    state most of these tables are in.

    The corner is the guard that makes the rest safe to relax. A table of
    descriptions has a heading over its first column, so it never reaches
    here, and the body does not have to be numeric: a normal-form game
    whose cells read "A gets $1,000, B gets $800" is as much a matrix as a
    contingency table, and a confusion matrix labeled Predicted Positive
    over Actual Positive is the same shape again.

    Across five books this matches 62 tables. 45 of them the rest of the
    rule already calls both, which is the evidence that it picks out the
    shape it means to.
    """
    if len(rows) < 3 or max(len(r) for r in rows) < 3:
        return False
    corner = rows[0][0]
    if corner.text or corner.image:
        return False
    top = rows[0][1:]
    side = [r[0] for r in rows[1:]]
    if not top or not side:
        return False
    if any(not c.text for c in top) or any(not c.text for c in side):
        return False
    if mostly_numeric(top) or mostly_numeric(side):
        return False
    inner = [c for r in rows[1:] for c in r[1:]]
    return bool(inner) and all(c.text or c.image for c in inner)


QUANTITY = re.compile(r"""^[(\[]?[-+\u2212]?[$\u00a3\u20ac\u00a5]?\s*
                          [\d][\d,. ]*
                          \s*(?:%|[a-zA-Z][a-zA-Z./\u00b2\u00b3]{0,11}
                                 (?:\s+[a-zA-Z]{1,10})?)?
                          [)\]]?$""", re.X)


def mostly_values(cells, ratio=0.8):
    """A body of measurements rather than prose.

    Wider than mostly_numeric, which wants a bare number: this also takes
    a currency symbol, a unit, or both -- `$120 billion`, `3.0 million`,
    `$1 per hour`, `18,100 clicks`, `21.4%`. Those are values with their
    units written out, and a table of them is as much a matrix as a table
    of bare figures. 24 tables in five books turn on the difference, all
    of them shapes like `Government purchases | $120 billion`.

    Deliberately strict about what follows the number: one word, or two
    short ones. `Reducing pollution by the first 25%` starts with no digit
    and never reaches here, but the ratio is what stops a column of
    sentences that happen to open with a figure.
    """
    values = [c.text.strip() for c in cells if c.text.strip()]
    if not values:
        return False
    hits = sum(1 for v in values if QUANTITY.match(v))
    return hits >= ratio * len(values)


def holds_values(rows):
    """Is there something being measured to the right of the first column?

    Asked per column, not over the whole body. `Neighborhood | Income
    Level | Number of Participants` is half categories and half counts,
    so over the whole body fewer than 80% of the cells parse as values
    and the table read as prose -- but Number of Participants is a column
    of measurements and Neighborhood heads its rows. 45 tables in seven
    books turn on the difference.

    The original whole-body test is kept as an alternative, since a body
    can be mostly values without any single column reaching the
    threshold.

    What this still excludes is the case the test exists for: `Retail
    Type | Product Focus | Example` has no column of values anywhere, so
    it stays a list of descriptions rather than becoming a matrix.
    """
    if not rows:
        return False
    if mostly_values([c for r in rows for c in r[1:]]):
        return True
    for j in range(1, max(len(r) for r in rows)):
        column = [r[j] for r in rows if j < len(r)]
        if column and mostly_values(column):
            return True
    return False


def keys_rows(cells):
    """True when this column reads as a label for its rows rather than as
    data.

    Three conditions, and the third is the one that took measuring. Every
    cell filled, no value repeated -- a column that repeats a value is not
    keying anything. Then: a column of text labels is a key, but a column
    of numbers is only a key if it is ordered.

    Without that last test, `Group A | Group B | Group C` over three
    columns of measurements is read as having a header column, because the first column
    of data is as unique as any label column. 110 tables in the three
    OpenStax books turn on this and they split 78/32. The ordered side is
    lookup axes -- Year, Price Level, Quantity, z, a frequency table's
    Data column. The unordered side is homogeneous data columns, where
    row 1 names three groups and there is no label column at all.

    A column that is mostly unparseable (`1`, `2`, `3-4`, `5+`) is treated
    as labels, not numbers: those are bins, and bins label their rows.
    """
    texts = [c.text for c in cells]
    if not texts or not all(texts) or len(set(texts)) != len(texts):
        return False
    values = [parse_number(t) for t in texts]
    parsed = [v for v in values if v is not None]
    if len(parsed) < 0.8 * len(values):
        return True
    if len(parsed) < 3:
        return False
    return (all(b > a for a, b in zip(parsed, parsed[1:]))
            or all(b < a for a, b in zip(parsed, parsed[1:])))


# --------------------------------------------------------------------------
# The sidecar guess
# --------------------------------------------------------------------------

def guess(tbl, kind=None, ev=None):
    """The sidecar value alone. See explain() for the value and the reason."""
    return explain(tbl, kind, ev)[0]


def explain(tbl, kind=None, ev=None):
    """The value a table-headers sidecar would be prefilled with.

    Four values, which are the ones the sidecar accepts: first-row,
    first-column, both, and none (no headers, deliberately). Returns None
    for a table the sidecar does not cover, which today means layout
    tables -- distinct from "none", which is a declaration that this is a
    data table with nothing to declare.

    Returns "unknown" where the file shows a header band the four values
    cannot place. That is a third state on purpose: "none" is a claim
    about the table and "unknown" is a claim about the guess, and a report
    that conflates them tells a person nothing about where to look.

    The key-column rule fires with or without a header row above it, but
    not on the same terms: see the comment where it does.

    This is deliberately not the same question classify() answers.
    classify() reports what the file says; these books hardly ever bold or
    shade a row-header column, so formatting alone finds 16 matrix tables
    where a reading of the content finds several hundred. The rule here is
    that a first column which keys its rows, over a body of values, is
    headers -- a contingency table's category column, a
    frequency table's interval column, a table of countries and their
    union density. The numeric-body condition is what keeps it from firing
    on a table of descriptions, where the first column is a key but the
    rest is prose and the whole thing reads as a list.

    It is still a guess, and the ambiguous population is real: a frequency
    table's interval column and a contingency table's category column are
    byte-for-byte identical in the DOCX. The value exists to be corrected.
    """
    if kind is None:
        kind, ev, _, _ = classify(tbl)
    if kind == "empty" or kind.startswith("layout"):
        return None, "not a data table"

    grid = build_grid(tbl)
    if not grid:
        return None, "no cells"

    # Read past what the table opens with but does not mean. A merged
    # full-width first row becomes a <caption>, so the value describes the
    # table as it will be once that has happened; and a wholly empty first
    # row is a spacer, which three tables in the data science book use
    # above their real header row.
    # In a one-column table every row spans the width trivially, so the
    # title-row test has to be off for those or it consumes the table.
    wide = max(len(r) for r in grid) > 1
    start = 0
    while start < len(grid):
        first = grid[start]
        if wide and is_full_width_band(first) and first[0].text:
            start += 1
        elif not any(c.text or c.image for c in first):
            start += 1
        else:
            break
    rows = grid[start:]
    if not rows:
        return None, "nothing left after the opening rows"
    skipped = ("read past %d opening row(s); " % start) if start else ""

    marked = [i for i, tr in enumerate(tbl.findall(q("tr"))) if repeats_as_header(tr)]
    # Ignoring full-width rows would empty a one-column table, where every
    # row spans the width by definition.
    plain = [r for r in rows if not wide or not is_full_width_band(r)]
    if start in marked:
        head_why = "row 1 is set to repeat as a header (w:tblHeader)"
    elif ((not wide or not is_full_width_band(rows[0]))
          and looks_like_header_band(rows[0], allow_blank_corner=True)):
        head_why = "every cell in row 1 has text and they are uniformly bold or shaded"
    elif text_row_over_numbers(plain):
        head_why = "row 1 is words and everything under it is numbers"
    else:
        head_why = ""
    has_head = bool(head_why)

    # Formatting that already proves a header column wins over the key
    # rule below, which would otherwise demote those tables to col.
    # classify() found a header band, and not where we could use it: not
    # row 1, not a title row, not a blank spacer. `11-5-race-and-ethnicity`
    # opens with a stray data row above its real header row. There is no
    # value for that, and asserting one would be worse than saying so --
    # the guess reported first-column here, which is a claim that this
    # table has no header row when the file plainly shows one.
    if not has_head and kind.startswith("headers-not-in-row-1"):
        return "unknown", (skipped + "there is a header band, but below row 1 "
                           "and with content above it, which no value describes")

    # Whether the first column is formatted as headers, asked directly
    # rather than read off `kind`. classify() computes this and then, on
    # the title-row branch, reports the title row instead: BC-07's Message
    # Triangle has a merged title, a bold header row, and a bold first
    # column, and the column finding was in the evidence string and
    # nowhere else. A bold first column is the strongest signal there is
    # for both, and there are only 19 of them in seven books.
    col_cells = [r[0] for r in rows[1 if has_head else 0:]
                 if r and not is_full_width_band(r)]
    header_col = bool(col_cells) and (
        looks_like_header_band(col_cells, allow_blank_corner=not has_head)
        and not mostly_numeric(col_cells))

    if kind == "both" or (has_head and header_col):
        return "both", (skipped + "formatting marks both a header row and a "
                        "header column")
    if kind == "first-column" or header_col:
        return "first-column", (skipped + "formatting marks a header column "
                                "and no header row")

    if blank_corner_matrix(plain):
        return "both", (skipped + "the corner cell is blank with labels along the top "
                        "row and down the first column, so the two axes label each other")

    ncols = max(len(r) for r in rows)
    body = [r for r in rows[1 if has_head else 0:]
            if r and not is_full_width_band(r)]
    if ncols < 2 or len(body) < 2:
        if has_head:
            return "first-row", skipped + head_why
        return "none", skipped + "too small to read, and nothing marks a header"

    # A trailing summary row ("Total = 600") often has nothing in its
    # label cell, and one blank is enough to make the whole first column
    # fail the every-cell-filled test. Set it aside for the key rule; it
    # is a footer for the table, not one of the rows being keyed. Five
    # tables in five books turn on this, all frequency or contingency
    # tables that want both.
    keyed_rows = body
    summary = ""
    if (len(body) > 2 and not body[-1][0].text
            and any(c.text for c in body[-1][1:])):
        keyed_rows = body[:-1]
        summary = ", setting aside a trailing row with no label"
    col0 = [r[0] for r in keyed_rows]
    rest = [c for r in keyed_rows for c in r[1:]]
    keyed = keys_rows(col0)
    valued = holds_values(keyed_rows)
    sample = next((c.text for c in rest if c.text and QUANTITY.match(c.text.strip())),
                  next((c.text for c in rest if c.text), ""))
    over = ("over a body holding values" + (' such as "%s"' % sample[:24] if sample else ""))
    key_why = "the first column fills every cell without repeating a value, " + over
    if keyed and valued:
        if has_head:
            return "both", skipped + head_why + ", and " + key_why + summary
        # No header row at all. A column of labels over a body of values
        # still heads its rows -- a transposed table whose first column
        # holds the field names, or a list of makes against their market
        # share. But a *numeric* first column is not enough on its own
        # here: with no header row to fix the orientation, an ordered
        # numeric column is as likely to be the first data series as a
        # lookup axis. 17 tables reach this point and the split is 13/4,
        # with the 4 numeric ones including a bare grid whose first column
        # happens to descend.
        # mostly_values rather than mostly_numeric: a first column of
        # dollar amounts is a data series with its units written out, and
        # two tables in the corpus are bare grids of money that the
        # narrower test would have read as labels.
        if not mostly_values(col0):
            return "first-column", (
                skipped + "nothing marks a header row, but the first column reads as "
                "labels rather than values and fills every cell without repeating, "
                + over)
    if has_head:
        return "first-row", skipped + head_why + (
            ", and the first column does not key its rows over a body of values")
    return "none", skipped + "no header row, no header column, and no keying first column"


LABEL = re.compile(r"\b(Table|Exhibit)\s+([A-Z]?[\d.]+[a-z]?)", re.I)


def nearby_label(body, tbl):
    """Best-effort label from the paragraph just before or just after."""
    kids = list(body)
    try:
        i = kids.index(tbl)
    except ValueError:
        return ""
    def label_at(j):
        if not (0 <= j < len(kids)) or kids[j].tag != q("p"):
            return ""
        text = " ".join("".join(t.text or "" for t in kids[j].iter(q("t"))).split())
        m = LABEL.search(text)
        return f"{m.group(1).title()} {m.group(2)}" if m else ""

    # A caption above the table wins. One below is only this table's caption
    # if another table does not follow it -- otherwise it belongs to that one.
    above = label_at(i - 1)
    if above:
        return above
    if i + 2 < len(kids) and kids[i + 2].tag == q("tbl"):
        return ""
    return label_at(i + 1)




# --------------------------------------------------------------------------
# The sidecar key
# --------------------------------------------------------------------------

def keyed_text(tc, keys):
    """A cell's text for hashing: its own text, with any nested table
    replaced by that table's key.

    Everything readable in the cell, in document order, with paragraphs
    and breaks separated as cell_text() does it -- except that a w:tbl
    inside the cell contributes its key rather than its text. The inner
    table's cells are not this cell's cells, so its text does not belong
    in this table's hash; but a fixed placeholder would leave a container
    of four code boxes hashing the same as every other such container.
    The inner key does both jobs.
    """
    parts = []

    def walk(node):
        for child in node:
            tag = child.tag
            if tag == q("tbl"):
                parts.append("\x00" + keys[id(child)] + "\x00")
                continue
            if tag == q("t") or tag == "{%s}t" % MATH:
                parts.append(child.text or "")
            elif tag in (q("br"), q("cr")):
                parts.append("\n")
            elif tag == q("tab"):
                parts.append("\t")
            elif tag == q("p") and parts and parts[-1] != "\n":
                parts.append("\n")
            walk(child)

    walk(tc)
    return "".join(parts).strip()


def table_key(tbl, keys=None):
    """The sidecar key: SHA-256 over the table as it sits in the source.

    Hashed, in order: every cell's text, row-major, empty cells included
    as empty strings so that position counts; then the shape, as the row
    count, the column count, and the number of cells in each row, which
    is what catches a horizontal merge. Each cell's text has its leading
    and trailing whitespace stripped -- Word adds and drops that on its
    own and no cell has ever meant something by it -- and is otherwise
    exactly what the file says: case, internal spacing, and punctuation
    all count, because a programming textbook can have two cells that
    differ only there.

    Computed on the source before any transformation. A title row that
    becomes a caption, a split, a promoted header: none of it changes the
    key, so a sidecar row survives everything the pipeline does and only
    a change to the source file itself detaches it. Measured against one
    chapter Word had rewritten on save, all six tables kept their keys
    while every media part was renamed.

    A cell holding a table contributes that table's key (see keyed_text),
    so keys are computed bottom-up; pass `keys` -- a dict from id(tbl) to
    key -- when hashing a document with nested tables, or let this build
    it.
    """
    if keys is None:
        keys = {}
    for inner in tbl.findall(".//" + q("tbl")):
        if id(inner) not in keys:
            keys[id(inner)] = table_key(inner, keys)
    rows = tbl.findall(q("tr"))
    counts = []
    digest = hashlib.sha256()
    for tr in rows:
        cells = tr.findall(q("tc"))
        counts.append(len(cells))
        for tc in cells:
            digest.update(keyed_text(tc, keys).encode("utf-8"))
            digest.update(b"\x1f")
        digest.update(b"\x1e")
    ncols = max(counts) if counts else 0
    digest.update(("%d;%d;%s" % (len(rows), ncols,
                                  ",".join(str(c) for c in counts))).encode())
    key = digest.hexdigest()
    keys[id(tbl)] = key
    return key


def read_body(path):
    """The w:body of a .docx, or None if there is no document to read."""
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    root = ET.fromstring(xml)
    return root.find(q("body"))
