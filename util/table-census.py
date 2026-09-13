#!/usr/bin/env python3
"""Census the tables in a set of DOCX files and guess each one's header shape.

Reads word/document.xml directly, so it needs nothing but the standard
library and can run anywhere Python 3 does.

Two columns describe each table, and they answer different questions.

`Kind` is what the file says: first-row, first-column, both, or none, plus
the shapes no sidecar value covers -- layout tables, tables whose header
band is not the first row, and tables with no header signal at all.

`Guess` is the value a table-headers sidecar would be prefilled with, and
is one of first-row, first-column, both, or none. It reads content as well
as formatting, because these books rarely mark a row-header column in any
way a file can be asked about. See guess() for the rule.

The value names say which line of the table holds headers, which is how
LaTeX's table/header-rows and table/header-columns are named and how
Pandoc's row_head_columns is named. Earlier drafts called these col, row,
matrix, and grid, where col meant a header *row*; that reads as the
opposite of the LaTeX keys and is gone.

Usage:
    python3 table-census.py *.docx > table-census.csv
    python3 table-census.py --verbose 1-3-foo.docx    # per-table detail

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

import csv
import re
import sys
import zipfile
from collections import Counter

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


def cell_text(tc):
    return "".join(t.text or "" for t in tc.iter(q("t")))


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
    """The value a table-headers sidecar would be prefilled with.

    Four values, which are the ones the sidecar accepts: first-row,
    first-column, both, and none (no headers, deliberately). Returns None
    for a table the sidecar does not cover, which today means layout
    tables -- distinct from "none", which is a declaration that this is a
    data table with nothing to declare.

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
        return None

    grid = build_grid(tbl)
    if not grid:
        return None

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
        return None

    marked = [i for i, tr in enumerate(tbl.findall(q("tr"))) if repeats_as_header(tr)]
    has_head = (start in marked
                or (not is_full_width_band(rows[0])
                    and looks_like_header_band(rows[0], allow_blank_corner=True)))

    # Formatting that already proves a header column wins over the key
    # rule below, which would otherwise demote those tables to col.
    if kind == "both":
        return "both"
    if kind == "first-column":
        return "first-column"

    if not has_head and kind == "no-header-signal":
        return "none"

    ncols = max(len(r) for r in rows)
    body = [r for r in rows[1 if has_head else 0:]
            if r and not is_full_width_band(r)]
    if ncols < 2 or len(body) < 2:
        return "first-row" if has_head else "none"

    rest = [c for r in body for c in r[1:]]
    if has_head and keys_rows([r[0] for r in body]) and mostly_numeric(rest):
        return "both"
    if has_head:
        return "first-row"
    return "none"


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

def census(paths, verbose=False):
    import xml.etree.ElementTree as ET

    out = csv.writer(sys.stdout)
    out.writerow(["Source", "Label", "Kind", "Guess", "Rows", "Columns",
                  "Depth", "Evidence"])
    tally = Counter()
    guesses = Counter()

    for path in paths:
        try:
            with zipfile.ZipFile(path) as z:
                xml = z.read("word/document.xml")
        except (KeyError, OSError, zipfile.BadZipFile) as exc:
            print(f"{path}: cannot read ({exc})", file=sys.stderr)
            continue

        root = ET.fromstring(xml)
        body = root.find(q("body"))
        if body is None:
            continue

        for tbl, depth in all_tables(body):
            kind, ev, nrows, ncols = classify(tbl)
            g = guess(tbl, kind, ev)
            label = nearby_label(body, tbl) if depth == 0 else ""
            tally[kind] += 1
            if g:
                guesses[g] += 1
            out.writerow([path, label, kind, g or "", nrows, ncols, depth,
                          "; ".join(ev)])
            if verbose:
                print(f"  {path} {label or '(unlabeled)'}: {kind} -> {g or '-'} "
                      f"{nrows}x{ncols} [{'; '.join(ev)}]", file=sys.stderr)

    print("", file=sys.stderr)
    print("Totals:", file=sys.stderr)
    for kind, n in tally.most_common():
        print(f"  {n:5d}  {kind}", file=sys.stderr)
    covered = sum(n for k, n in tally.items() if k in ("first-row", "first-column", "both"))
    total = sum(tally.values())
    layout = sum(n for k, n in tally.items() if k.startswith("layout"))
    data = total - layout
    if data:
        print(f"\n  {covered}/{data} data tables ({100 * covered / data:.0f}%) "
              f"have a header row or column by formatting alone.", file=sys.stderr)
    total_guessed = sum(guesses.values())
    if total_guessed:
        print("\nSidecar guess:", file=sys.stderr)
        for value, n in guesses.most_common():
            print(f"  {n:5d}  ({100 * n / total_guessed:4.1f}%)  {value}",
                  file=sys.stderr)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--verbose"]
    if not args:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    census(args, verbose="--verbose" in sys.argv)
