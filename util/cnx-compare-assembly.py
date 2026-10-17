#!/usr/bin/env python3
"""
cnx-compare-assembly.py -- compare unpack-cnx.py's reading of a book with
OpenStax's own, each baked by the unpacker's port of its recipe.

    python3 util/cnx-compare-assembly.py osbooks-principles-of-management \\
        principles-management principles-management.assembled.xhtml
    python3 util/cnx-compare-assembly.py REPOSITORY BOOK ASSEMBLED --show 5

OpenStax's assembly ("neb assemble", from openstax/nebuchadnezzar, a
tool of theirs that isn't part of TextbookImprover) reads a repository
into one XHTML file per book, which their recipes then bake. This bakes
that file and the unpacker's own reading of the same book with the same
port, and compares the two page by page, in order, as words. Since the
baking is the same, a difference is in the reading: a table's foot read
before its body, a note's opening words lost (both found so in
Principles of Management).

What's different on purpose is left out (lib/cnx/compare.py,
DELIBERATE), as the content MathML OpenStax's assembly adds beside each
formula. Some differences remain that are deliberate too: an inline
list's separators and letters, and a labeled item's label ("____"),
which the unpacker writes as text, where OpenStax's stylesheet shows
them; and an exercise from the exercise bank, which either side may not
have had.

Needs lxml. Copyright 2026 Robert Szarka

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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))

from cnx import compare as C  # noqa: E402
from cnx import exercises  # noqa: E402
from cnx.assemble import assemble  # noqa: E402
from cnx.bake import bake  # noqa: E402
from cnx.repo import Repo  # noqa: E402


def main():
    parser = argparse.ArgumentParser(
        description="Compare unpack-cnx.py's reading of a book with "
                    "OpenStax's assembly of it.")
    parser.add_argument("repository", help="the book's osbooks-… repository")
    parser.add_argument("book", help="the book's slug, as --list names it")
    parser.add_argument("assembled",
                        help="the book as OpenStax's assembly wrote it "
                             "(<slug>.assembled.xhtml)")
    parser.add_argument("--show", type=int, default=0, metavar="N",
                        help="show where, up to N places a page")
    args = parser.parse_args()

    repo = Repo(args.repository)
    book = repo.book(args.book)
    asm, body = assemble(repo, book)
    # The cache only: a bank exercise this can't have, OpenStax's
    # assembly probably couldn't either.
    exercises.inject(asm, body, exercises.Bank(offline=True))
    language = book.collection.language
    bake(body, book.style, language)
    theirs = C.load(args.assembled).find("body")
    bake(theirs, book.style, language)
    ours, others = C.pages(body), C.pages(theirs)
    print(f"{args.book} ({book.style}): {len(ours)} page(s) here, "
          f"{len(others)} from OpenStax's assembly")
    differ = 0
    for i, ((page, a), (other, b)) in enumerate(zip(ours, others), 1):
        if a == b:
            continue
        differ += 1
        m = C.matcher(a, b)
        title = C.title_of(page) or C.title_of(other)
        print(f"  {m.ratio():.4f}  page {i}: {title[:60]}")
        C.show(m, a, b, args.show, "OpenStax")
    if len(ours) != len(others):
        print("  the books have different numbers of pages; compared as far "
              "as the shorter goes")
    print(f"{differ} page(s) differ" if differ else "no page differs")
    return 1 if differ or len(ours) != len(others) else 0


if __name__ == "__main__":
    sys.exit(main())
