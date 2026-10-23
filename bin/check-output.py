#!/usr/bin/env python3
"""
check-output.py -- report what is wrong with the pages, EPUBs, PDFs, and
PowerPoint files a run wrote, using nothing but Python.

    check-output.py --pages LIST --report output-check.csv [--epub FILE ...]
    check-output.py page1.html page2.html ...
    check-output.py --epub book.epub
    check-output.py --pptx deck.pptx

Runs at the end of convert.py over the pages of this run and any EPUB
built from them, and writes the findings to a report beside the other
reports. The run is not stopped by a finding: the output exists, and
the report is the list to work through. With no findings the report is
removed, so the file existing is the signal (notes from --wcag, below,
keep it, though the summary's verdict leaves them out).

The checks are in lib/outputcheck.py: links and fragments that resolve
to nothing, images with no alt attribute, headings that skip a level,
duplicate ids, tables with neither header cells nor a caption, pages
with no language or title, and an EPUB whose manifest, spine, and
archive disagree or whose package document lacks the metadata every
EPUB needs; and a PowerPoint file a deck's pptx target wrote as a
PowerPoint deck is checked (lib/pptxcheck.py). They are not epubcheck,
the Nu HTML checker, or Ace, which know their specifications in full. epubcheck and the Nu checker are run
as well when they are installed -- named by EPUBCHECK_JAR and VNU_JAR,
or as commands on the path -- and their findings go into the same
report with the tool's own message id as the check; --quick skips them,
and veraPDF, and convert.py --quick passes it on.

--wcag runs veraPDF's WCAG 2.2 machine profile on each PDF as well, with
the WCAG modules its release lacks, from the folder VERAPDF_WCAG names
(docs/installation.md). The checks are experimental and wrong at times,
so what they find is a note, never an error, and the summary says so;
and since veraPDF without the modules passes the profile's own rules
without checking them, and says nothing of it, a probe of its own in the
same run says whether they loaded, and the summary warns when they
didn't. Each rule a PDF fails is one note, with how many of its checks
failed and on which pages; --verbose makes each failed check a note,
with what the PDF has there that veraPDF's report doesn't say (a link's
address, the line repeated characters are on), and lists them in the
summary. Given nothing to check, --wcag runs the probe alone, which
checks the setup. convert.py --wcag and --verbose pass them on.

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
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
import outputcheck  # noqa: E402
import pdfcheck  # noqa: E402
import pptxcheck  # noqa: E402
import pptxparse  # noqa: E402
import findings as findings_lib  # noqa: E402


def main():
    parser = argparse.ArgumentParser(
        description="Check the pages, EPUBs, PDFs, and PowerPoint files a run wrote.")
    parser.add_argument("pages", nargs="*", help="HTML pages to check")
    parser.add_argument("--pages", dest="pages_file",
                        help="a file listing pages, one per line; a "
                             ".filtered.json name stands for its .html")
    parser.add_argument("--epub", action="append", default=[],
                        help="an EPUB to check (repeatable)")
    parser.add_argument("--pdf", action="append", default=[],
                        help="a PDF to check (repeatable)")
    parser.add_argument("--pptx", action="append", default=[],
                        help="a PowerPoint file to check (repeatable)")
    parser.add_argument("--documents",
                        help="a JSON file naming each page's document, {page: name}: one alt "
                             "text on different images is looked for within a document, and "
                             "the pages are one without it")
    parser.add_argument("--report", help="write findings here as CSV")
    parser.add_argument("--quick", action="store_true",
                        help="skip epubcheck, the Nu checker, and veraPDF "
                             "even if installed")
    parser.add_argument("--wcag", action="store_true",
                        help="run veraPDF's WCAG 2.2 machine profile on each PDF too, with "
                             "its WCAG modules from VERAPDF_WCAG; experimental, so what it "
                             "finds is a note, never an error; with nothing else to check, "
                             "check the setup")
    parser.add_argument("--verbose", action="store_true",
                        help="with --wcag, a note for each failed check of veraPDF's WCAG "
                             "profile, listed in the summary too, with what the PDF has "
                             "there (a link's address, the line repeated characters are "
                             "on), where each rule's are otherwise counted in one")
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

    documents = None
    if args.documents:
        with open(args.documents, encoding="utf-8") as fh:
            documents = json.load(fh)
    findings = []
    if pages:
        findings += outputcheck.check_html_files(pages, documents)
    epubs = [p for p in args.epub if os.path.exists(p)]
    for path in epubs:
        findings += outputcheck.check_epub(path)
    notes = []
    if not args.quick:
        more, notes = outputcheck.run_validators(pages, epubs)
        findings += more
    else:
        # Said, so a summary that found nothing isn't taken for theirs.
        notes.append("epubcheck, the Nu HTML checker, and veraPDF not run "
                     "(--quick).")
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
    # veraPDF's WCAG 2.2 checks, when asked for: information, never a
    # verdict, so they're counted and summarized apart from the rest.
    wcag_findings, wcag_lines = [], []
    if args.verbose and not args.wcag:
        notes.append(pdfcheck.WCAG_ALONE)
    if args.wcag:
        command = None if args.quick else outputcheck.find_validator("verapdf")
        if args.quick:
            wcag_lines.append("veraPDF's WCAG checks not run (--quick).")
        elif not command:
            wcag_lines.append("veraPDF's WCAG checks not run: veraPDF not found (set "
                              "VERAPDF, or put verapdf on the path).")
        elif not pdfs and (args.pages or args.pages_file or args.epub or args.pdf
                           or args.pptx):
            wcag_lines.append("veraPDF's WCAG checks not run: no PDF to check.")
        else:
            # With nothing named to check, the setup alone.
            wcag_findings, wcag_lines = pdfcheck.run_verapdf_wcag(command, pdfs,
                                                                  verbose=args.verbose)
    # A PowerPoint file's, as a PowerPoint deck's are found.
    pptxs = [p for p in args.pptx if os.path.exists(p)]
    pptx_findings = []
    for path in pptxs:
        pptx_findings += pptxcheck.check(pptxparse.read(path), os.path.basename(path),
                                         kind="pptx")

    written = bool(findings or pdf_findings or pptx_findings or wcag_findings)
    if args.report:
        if written:
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
                for f in findings] + pdf_findings + pptx_findings + wcag_findings)
        elif os.path.exists(args.report):
            os.remove(args.report)

    parts = [f"{len(pages)} page(s)"] + (
        [f"{len(epubs)} EPUB(s)"] if epubs else []) + (
        [f"{len(pdfs)} PDF(s)"] if pdfs else []) + (
        [f"{len(pptxs)} PowerPoint file(s)"] if pptxs else [])
    checked = parts[0] if len(parts) == 1 else (
        f"{parts[0]} and {parts[1]}" if len(parts) == 2
        else ", ".join(parts[:-1]) + f", and {parts[-1]}")
    for line in summary(checked, notes, findings, pdf_findings, pptx_findings, wcag_lines,
                        args.report if args.report and written else None):
        print(line, file=sys.stderr)
    return 0


def summary(checked, notes, findings, pdf_findings, pptx_findings, wcag_lines,
            report=None):
    """The run's summary: what didn't run, the verdict and its findings,
    then, outside the verdict's count, what veraPDF's WCAG profile found
    or why it didn't run, and where the report went."""
    lines = [f"  {note}" for note in notes]
    if not findings and not pdf_findings and not pptx_findings:
        lines.append(f"Output check: {checked}, nothing found.")
    else:
        lines.append(f"Output check: {checked}, "
                     f"{len(findings) + len(pdf_findings) + len(pptx_findings)} finding(s):")
        for check, count in outputcheck.summarize(findings):
            lines.append(f"  {count:5}  {check}: "
                         f"{outputcheck.DESCRIPTIONS.get(check) or findings_lib.describe(check)}")
        lines += pdf_summary(pdf_findings) + pdf_summary(pptx_findings, by_file=True)
    lines += [f"  {line}" for line in wcag_lines]
    if report:
        lines.append(f"Written to {report}.")
    return lines


def pdf_summary(pdf_findings, by_file=False):
    """The PDF findings' lines in the run's summary: one for each finding,
    its detail beside it, unless a PDF has the same one more than once,
    as every figure LaTeX gave a placeholder for alt text does (195 on
    GIAM), which is one line with the count and what the check means.
    The report has every one. by_file: the findings are a PowerPoint
    file's, each where on a slide, gathered by the file instead."""
    groups = {}
    for finding in pdf_findings:
        key = finding.file if by_file else finding.where
        groups.setdefault((key, finding.check), []).append(finding)
    lines = []
    for (where, check), found in groups.items():
        if len(found) == 1:
            place = f"{where}, {found[0].where}" if by_file else where
            lines.append(f"  {place}: {check}: {found[0].detail}")
        else:
            lines.append(f"  {where}: {len(found)} {check}: "
                         f"{findings_lib.describe(check)}")
    return lines


if __name__ == "__main__":
    sys.exit(main())
