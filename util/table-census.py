#!/usr/bin/env python3
"""Census the tables in a set of DOCX files and guess each one's header shape.

Reads word/document.xml directly, so it needs nothing but the standard
library and can run anywhere Python 3 does.

Two columns describe each table, and they answer different questions.

`Kind` is what the file says: first-row, first-column, both, or none, plus
the shapes no sidecar value covers -- layout tables, tables whose header
band is not the first row, and tables with no header signal at all.

`Guess` is the value a table-headers sidecar would be prefilled with, and
is one of first-row, first-column, both, or none, or unknown where no rule
recognizes the table's headers and nothing shows it has none. It reads
content as well
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
    python3 table-census.py corpus/ > table-census.csv  # every book in it
    python3 table-census.py --verbose 1-3-foo.docx      # per-table detail

A directory is searched for .docx files at any depth, Word's ~$ lock files
skipped, so a corpus of any size is one command. Each file belongs to a
book: the subdirectory of the argument it sits in, or the argument itself
when it sits there directly, or, for a file named on its own, the directory
holding it. The summary on stderr gives each book's totals as well as the
whole run's, and the CSV names the book in its last column.

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
from tablecensus import (q, all_tables, classify,  # noqa: E402
                         guess_table, nearby_label)


# --------------------------------------------------------------------------

def book_files(args):
    """(path, book) for every .docx the arguments name, in a stable order."""
    out = []
    for arg in args:
        if os.path.isdir(arg):
            root = os.path.normpath(arg)
            name = os.path.basename(os.path.abspath(root))
            found = []
            for here, dirs, files in os.walk(root):
                dirs.sort()
                found.extend(os.path.join(here, f) for f in sorted(files)
                             if f.lower().endswith(".docx")
                             and not f.startswith("~$"))
            if not found:
                print(f"{arg}: no .docx files", file=sys.stderr)
            for path in found:
                parts = os.path.relpath(path, root).split(os.sep)
                out.append((path, parts[0] if len(parts) > 1 else name))
        else:
            out.append((arg, os.path.basename(
                os.path.dirname(os.path.abspath(arg)))))
    return out


GUESSES = ("both", "first-row", "first-column", "none", "unknown")


def census(items, verbose=False):
    """items: (path, book) pairs, as book_files gives them."""
    import xml.etree.ElementTree as ET

    out = csv.writer(sys.stdout)
    out.writerow(["Source", "Label", "Kind", "Guess", "Rows", "Columns",
                  "Depth", "Evidence", "Book"])
    tally = Counter()
    guesses = Counter()
    books = {}
    for path, book in items:
        per = books.setdefault(book, Counter())
        try:
            with zipfile.ZipFile(path) as z:
                xml = z.read("word/document.xml")
        except (KeyError, OSError, zipfile.BadZipFile) as exc:
            print(f"{path}: cannot read ({exc})", file=sys.stderr)
            continue
        per["files"] += 1
        root = ET.fromstring(xml)
        body = root.find(q("body"))
        if body is None:
            continue
        for tbl, depth in all_tables(body):
            kind, ev, nrows, ncols = classify(tbl)
            g = guess_table(tbl, kind, ev)[0]
            label = nearby_label(body, tbl) if depth == 0 else ""
            tally[kind] += 1
            per["tables"] += 1
            if not kind.startswith("layout"):
                per["data"] += 1
            if kind in ("first-row", "first-column", "both"):
                per["marked"] += 1
            if g:
                guesses[g] += 1
                per[g] += 1
            out.writerow([path, label, kind, g or "", nrows, ncols, depth,
                          "; ".join(ev), book])
            if verbose:
                print(f"  {path} {label or '(unlabeled)'}: {kind} -> {g or '-'} "
                      f"{nrows}x{ncols} [{'; '.join(ev)}]", file=sys.stderr)

    print("", file=sys.stderr)
    if len(books) > 1:
        print("By book:", file=sys.stderr)
        width = max(len(b) for b in books)
        for book in sorted(books):
            per = books[book]
            shown = ", ".join(f"{per[g]} {g}" for g in GUESSES if per[g])
            print(f"  {book:<{width}}  {per['files']:4d} files  "
                  f"{per['tables']:5d} tables  {per['data']:5d} data  "
                  f"{per['marked']:5d} marked"
                  + (f"  guess: {shown}" if shown else ""), file=sys.stderr)
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
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__)
        sys.exit(0)
    args = [a for a in sys.argv[1:] if a != "--verbose"]
    if not args:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    census(book_files(args), verbose="--verbose" in sys.argv)
