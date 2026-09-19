#!/usr/bin/env python3
"""
check-output.py -- report what is wrong with the pages and EPUBs a run
wrote, using nothing but Python.

    check-output.py --pages LIST --report output-check.csv [--epub FILE ...]
    check-output.py page1.html page2.html ...
    check-output.py --epub book.epub

Runs at the end of convert.sh over the pages of this run and any EPUB
built from them, and writes the findings to a report beside the other
reports. The run is not stopped by a finding: the output exists, and
the report is the list to work through. With no findings the report is
removed, so the file existing is the signal.

The checks are in lib/outputcheck.py: links and fragments that resolve
to nothing, images with no alt attribute, headings that skip a level,
duplicate ids, tables with neither header cells nor a caption, pages
with no language or title, and an EPUB whose manifest, spine, and
archive disagree or whose package document lacks the metadata every
EPUB needs. They are not epubcheck, the Nu HTML checker, or Ace, which
know their specifications in full; run those where they are installed.

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
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
import outputcheck  # noqa: E402


def main():
    parser = argparse.ArgumentParser(
        description="Check the pages and EPUBs a run wrote.")
    parser.add_argument("pages", nargs="*", help="HTML pages to check")
    parser.add_argument("--pages", dest="pages_file",
                        help="a file listing pages, one per line; a "
                             ".filtered.json name stands for its .html")
    parser.add_argument("--epub", action="append", default=[],
                        help="an EPUB to check (repeatable)")
    parser.add_argument("--report", help="write findings here as CSV")
    args = parser.parse_args()

    pages = list(args.pages)
    if args.pages_file:
        with open(args.pages_file, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.endswith(".filtered.json"):
                    line = line[:-len(".filtered.json")] + ".html"
                if line:
                    pages.append(line)
    pages = [p for p in pages if os.path.exists(p)]

    findings = []
    if pages:
        findings += outputcheck.check_html_files(pages)
    for path in args.epub:
        if os.path.exists(path):
            findings += outputcheck.check_epub(path)

    if args.report:
        if findings:
            with open(args.report, "w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["Where", "Check", "Detail"])
                writer.writerows(f.row() for f in findings)
        elif os.path.exists(args.report):
            os.remove(args.report)

    checked = f"{len(pages)} page(s)" + (
        f" and {len(args.epub)} EPUB(s)" if args.epub else "")
    if not findings:
        print(f"Output check: {checked}, nothing found.", file=sys.stderr)
        return 0
    print(f"Output check: {checked}, {len(findings)} finding(s):",
          file=sys.stderr)
    for check, count in outputcheck.summarize(findings):
        print(f"  {count:5}  {check}: "
              f"{outputcheck.DESCRIPTIONS.get(check, '')}", file=sys.stderr)
    if args.report:
        print(f"Written to {args.report}.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
