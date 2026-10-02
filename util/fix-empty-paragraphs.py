#!/usr/bin/env python3
"""
fix-empty-paragraphs.py -- remove content-free paragraph structure elements
from a tagged PDF, as the PDF target does itself (pdf.remove_empty_paragraphs).
For a PDF made some other way, such as a Pandoc command of your own.

    fix-empty-paragraphs.py book.pdf fixed.pdf
    fix-empty-paragraphs.py book.pdf --list      # count them, per page

See lib/pdfparagraphs.py for what is removed and why. Needs pikepdf.

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

import argparse
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import pdfparagraphs  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Remove content-free paragraph "
                                 "structure elements from a tagged PDF.")
    ap.add_argument("input")
    ap.add_argument("output", nargs="?")
    ap.add_argument("--list", action="store_true",
                    help="report what would be removed and exit")
    args = ap.parse_args()
    if not args.list and not args.output:
        ap.error("give an output path, or use --list")
    if pdfparagraphs.pikepdf is None:
        sys.exit("pikepdf isn't installed (pip install pikepdf, or sudo apt "
                 "install python3-pikepdf).")
    pdf = pdfparagraphs.pikepdf.open(args.input)
    if "/StructTreeRoot" not in pdf.Root:
        sys.exit("no structure tree -- is this a tagged PDF?")
    if args.list:
        fixer = pdfparagraphs.find(pdf)
        counts = defaultdict(int)
        for _elem, _parent, pgnum, _n in fixer.doomed:
            counts[pgnum] += 1
        print(f"content-free paragraph elements: {len(fixer.doomed)}")
        for pgnum in sorted(counts, key=lambda x: (x is None, x)):
            print(f"  page {pgnum}: {counts[pgnum]}")
        return 0
    count = pdfparagraphs.remove(pdf)
    if count is None:
        sys.exit("its parent tree is a number tree with kids, which this "
                 "doesn't rewrite; nothing written.")
    pdf.save(args.output)
    print(f"content-free paragraph elements removed: {count}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
