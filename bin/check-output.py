#!/usr/bin/env python3
"""
check-output.py -- report what is wrong with the pages and EPUBs a run
wrote, using nothing but Python.

    check-output.py --pages LIST --report output-check.csv [--epub FILE ...]
    check-output.py page1.html page2.html ...
    check-output.py --epub book.epub

Runs at the end of convert.py over the pages of this run and any EPUB
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
know their specifications in full. epubcheck and the Nu checker are run
as well when they are installed -- named by EPUBCHECK_JAR and VNU_JAR,
or as commands on the path -- and their findings go into the same
report with the tool's own message id as the check; --quick skips them.

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
import outputcheck  # noqa: E402
import pdfcheck  # noqa: E402
import findings as findings_lib  # noqa: E402


def main():
    parser = argparse.ArgumentParser(
        description="Check the pages, EPUBs, and PDFs a run wrote.")
    parser.add_argument("pages", nargs="*", help="HTML pages to check")
    parser.add_argument("--pages", dest="pages_file",
                        help="a file listing pages, one per line; a "
                             ".filtered.json name stands for its .html")
    parser.add_argument("--epub", action="append", default=[],
                        help="an EPUB to check (repeatable)")
    parser.add_argument("--pdf", action="append", default=[],
                        help="a PDF to check (repeatable)")
    parser.add_argument("--report", help="write findings here as CSV")
    parser.add_argument("--quick", action="store_true",
                        help="skip epubcheck, the Nu checker, and veraPDF "
                             "even if installed")
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
    epubs = [p for p in args.epub if os.path.exists(p)]
    for path in epubs:
        findings += outputcheck.check_epub(path)
    notes = []
    if not args.quick:
        more, notes = outputcheck.run_validators(pages, epubs)
        findings += more
    # A PDF's findings are in the full format already: what the file
    # says about itself, then veraPDF's rules when it's installed.
    pdfs = [p for p in args.pdf if os.path.exists(p)]
    pdf_findings = []
    for path in pdfs:
        found = pdfcheck.inspect(path)[1]
        command = None if args.quick else outputcheck.find_validator("verapdf")
        if command:
            found = pdfcheck.settle_claims(
                found, pdfcheck.run_verapdf(command, path))
        elif not args.quick:
            notes.append("veraPDF not found (set VERAPDF, or put verapdf on "
                         "the path); skipped.")
        pdf_findings += found

    if args.report:
        if findings or pdf_findings:
            # The shared findings format: the first three columns are
            # the ones this report has always had, the rest say more.
            findings_lib.write_csv(args.report, [
                findings_lib.Finding(
                    f.where, f.check, f.detail,
                    file=f.where.split("#")[0].split("/")[-1],
                    kind="epub" if f.where.startswith("EPUB/") else "html",
                    tool=("vnu" if f.check.startswith("vnu") else
                          "epubcheck" if f.check.startswith("epubcheck")
                          else "oer"))
                for f in findings] + pdf_findings)
        elif os.path.exists(args.report):
            os.remove(args.report)

    parts = [f"{len(pages)} page(s)"] + (
        [f"{len(epubs)} EPUB(s)"] if epubs else []) + (
        [f"{len(pdfs)} PDF(s)"] if pdfs else [])
    checked = parts[0] if len(parts) == 1 else (
        f"{parts[0]} and {parts[1]}" if len(parts) == 2
        else f"{parts[0]}, {parts[1]}, and {parts[2]}")
    for note in notes:
        print(f"  {note}", file=sys.stderr)
    if not findings and not pdf_findings:
        print(f"Output check: {checked}, nothing found.", file=sys.stderr)
        return 0
    print(f"Output check: {checked}, "
          f"{len(findings) + len(pdf_findings)} finding(s):", file=sys.stderr)
    for check, count in outputcheck.summarize(findings):
        print(f"  {count:5}  {check}: "
              f"{outputcheck.DESCRIPTIONS.get(check, '')}", file=sys.stderr)
    for finding in pdf_findings:
        print(f"  {finding.where}: {finding.check}: {finding.detail}",
              file=sys.stderr)
    if args.report:
        print(f"Written to {args.report}.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
