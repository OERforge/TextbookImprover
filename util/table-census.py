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
way a file can be asked about. See lib/tablecensus.py, which holds the classification and the guess;
this is the command line over it.

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
import os
import sys
import zipfile
from collections import Counter

# The classification lives beside bin/ in lib/, shared with the
# conversion pre-pass so the two cannot drift apart. Found by path rather
# than installed, so the project stays clone-and-run.
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
from tablecensus import (q, all_tables, classify, guess,  # noqa: E402
                         nearby_label)


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
