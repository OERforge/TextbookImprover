#!/usr/bin/env python3
"""
unpack-cnx.py -- turn a book written in CNXML, as OpenStax writes its
books and the Connexions archive keeps its own, into a directory
convert.py can convert.

    python3 unpack-cnx.py osbooks-principles-economics-bundle --list
    python3 unpack-cnx.py osbooks-principles-economics-bundle \\
        --book principles-economics-3e -o ~/books/econ

The repository is a clone of one of OpenStax's osbooks-* repositories or
of a cnx-user-books one, or any directory in their layout. A repository
holding several books (a "bundle") needs --book; --list names them.

What's written:

  - one .html per page of the book as OpenStax publishes it: its sections,
    each chapter's introduction and end-of-chapter pages, the answer key,
    references, and index, named as OpenStax names them, numbered, and
    linked, as their "baking" makes them (see lib/cnx/); a table that
    only lays things out a layout table (role="presentation"), as
    OpenStax's own HTML marks it: a worked example's steps in the
    dev-math books and College Algebra with Corequisite Support, a
    grid of key terms in Physics, and a Key Equations table, a
    formula's name beside it, and a box of one cell in any book;
  - the media those pages use, under media/;
  - project.yaml, with the book's title, language, license, and contents;
  - for an OpenStax book, conversion.yaml with the footer OpenStax asks
    every page to carry, in its words, footnotes numbered through each
    chapter, the PDF's page, and the words its captions open with where
    they aren't Figure and Table; and pdf-layout.yaml, that page:
    OpenStax's paper and margins, with 12pt type on lines 1.5 times its
    size apart, set ragged right;
  - table-captions.csv, a description for each table whose caption is
    only its label, from the summary OpenStax wrote for it where it says
    something ("No Summary" doesn't), one that reads the table out named
    in the report, and cnx-table-summaries.csv, every summary;
  - unpack-report.csv, what the unpacking noticed and didn't decide.

A newer OpenStax book keeps many of its exercises (a section's
"Knowledge Check", say) in OpenStax's exercise bank rather than its
repository. They're fetched from the bank's public API
(exercises.openstax.org) the first time a book is unpacked and kept in a
cache, ~/.cache/textbookimprover/cnx-exercises by default, so later runs
need no network; --offline uses the cache alone. Where the bank keeps an
exercise's answers private, its question comes without them, and the
report says so.

The repository is read, never written. Needs lxml (python3-lxml).

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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
try:
    import lxml  # noqa: F401
except ImportError:
    sys.exit("unpack-cnx.py needs lxml: sudo apt install python3-lxml "
             "(or pip install lxml).")
try:
    from cnx.exercises import Bank, default_cache
    from cnx.repo import Repo
    from cnx.unpack import unpack
except ImportError:
    sys.exit("Cannot find the library. It should be in a lib/ directory "
             "beside bin/.")


def main():
    parser = argparse.ArgumentParser(
        description="Unpack a book written in CNXML (an OpenStax osbooks-* "
                    "or cnx-user-books repository) into HTML pages and a "
                    "project.yaml for convert.py.")
    parser.add_argument("repository",
                        help="the repository's directory (a git clone)")
    parser.add_argument("--book", help="the book's slug, when the "
                        "repository holds more than one")
    parser.add_argument("--list", action="store_true",
                        help="list the repository's books and stop")
    parser.add_argument("-o", "--output",
                        help="directory to write (default: the book's slug)")
    parser.add_argument("--exercises-cache", metavar="DIR",
                        help="where exercises from OpenStax's exercise bank "
                        f"are kept (default: {default_cache()})")
    parser.add_argument("--offline", action="store_true",
                        help="don't fetch exercises; use the cache alone")
    args = parser.parse_args()
    try:
        repo = Repo(args.repository)
    except ValueError as exc:
        sys.exit(str(exc))
    if args.list:
        for book in repo.books:
            style = f"  (style: {book.style})" if book.style else ""
            print(f"{book.slug}{style}")
        return 0
    try:
        book = repo.book(args.book)
    except LookupError as exc:
        sys.exit(str(exc))
    out = args.output or book.slug
    if os.path.exists(out) and os.listdir(out):
        sys.exit(f"{out} exists and is not empty; unpacking would mix two "
                 "books. Name another directory with -o.")
    bank = Bank(cache=args.exercises_cache, offline=args.offline)
    result = unpack(args.repository, out, book.slug, bank=bank)
    how = (f"baked as OpenStax bakes style {result.style!r}" if result.baked
           else "not baked: numbered within each page")
    print(f"{result.pages} page(s), {result.media} media file(s), and "
          f"project.yaml written to {out}/ ({how}).")
    if result.exercises or result.exercises_missing:
        print(f"{result.exercises} exercise(s) from OpenStax's exercise bank"
              + (f"; {result.exercises_missing} couldn't be had"
                 if result.exercises_missing else "")
              + f" (cache: {bank.cache}).")
    if result.prefilled:
        print(f"table-captions.csv: {result.prefilled} description(s) from "
              "the tables' summaries, for tables whose caption is their "
              "label alone or that have none, drafted for review.")
    if result.summaries_read_out:
        print(f"{result.summaries_read_out} of them read the table out, a row or a "
              "cell at a time (\"Two rows and five columns. The first row is "
              "labeled...\"), which a screen reader hears before the table itself: "
              "each is a table-summary-reads-out row of the report, to put what the "
              "table shows in its place in table-captions.csv.")
    if result.empty_summaries:
        print(f"{result.empty_summaries} table summary(ies) say nothing "
              "(\"No Summary\", \".\", and the like), so no description was drafted "
              "from them.")
    if result.layout_tables:
        print(f"{result.layout_tables} table(s) that only lay things out (a worked "
              "example's steps, a Key Equations table, a grid of terms, a box of one "
              "cell, a form of blank lines, pictures with their labels, a matching "
              "exercise, an inquiry organizer) marked as layout tables "
              "(role=\"presentation\"), which ask for no description.")
    counts = {}
    for _where, check, _detail in result.notes:
        counts[check] = counts.get(check, 0) + 1
    for check, count in sorted(counts.items()):
        print(f"  {count:5d}  {check}")
    if result.notes:
        print(f"Details in {os.path.join(out, 'unpack-report.csv')}.")
    print(f"Next: cd {out} && python3 {os.path.join(HERE, 'convert.py')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
