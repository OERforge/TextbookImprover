#!/usr/bin/env python3
"""
audit.py -- what is wrong with a file, without converting it.

    python3 audit.py FILE-OR-DIRECTORY ... [-o DIR] [--force] [--no-cache]

Takes Word and Markdown sources, PowerPoint decks, HTML pages, EPUBs,
and PDFs, in any mix, and writes two things to the output directory (the first
directory given, or -o): audit.csv, one finding per row in the format
every check here shares, and audit.md, the same findings as a report a
person reads, with each PDF's metadata and claims. A file already
audited and unchanged since (by SHA-256) is not read again unless
--force says so.

Depends on lib/ and on Pandoc (to read a source), and optionally on
pypdf (PDFs), epubcheck, the Nu HTML checker, and veraPDF, each found
the way the output check finds them and reported as absent when they
are. --wcag checks each PDF against veraPDF's WCAG 2.2 machine profile
as well, as check-output.py --wcag does: what it finds is a note, never
an error, one for each rule a PDF fails, and the report says whether the
checks ran; --verbose makes each failed check a note, with what the PDF
has there.

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
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

import findings as fl  # noqa: E402
import outputcheck  # noqa: E402
import pdfcheck  # noqa: E402
import pptxcheck  # noqa: E402
import pptxparse  # noqa: E402
import sourcecheck  # noqa: E402
import tablecensus  # noqa: E402

VERSION = "0.9"
KIND_OF = {".docx": "source-docx", ".md": "source-md", ".html": "html",
           ".xhtml": "html", ".epub": "epub", ".pdf": "pdf", ".pptx": "source-pptx"}


def gather(paths):
    """The files to audit, from files and directories given."""
    out = []
    for path in paths:
        if os.path.isdir(path):
            for name in sorted(os.listdir(path)):
                full = os.path.join(path, name)
                kind = KIND_OF.get(os.path.splitext(name)[1].lower())
                if kind and os.path.isfile(full) and not name.startswith("~$"):
                    out.append((full, kind))
        elif os.path.isfile(path):
            kind = KIND_OF.get(os.path.splitext(path)[1].lower())
            if kind:
                out.append((path, kind))
            else:
                print(f"Skipping {path}: not a kind of file this audits.",
                      file=sys.stderr)
        else:
            print(f"No such file: {path}", file=sys.stderr)
    return out


def audit_one(path, kind, validators, wcag=False, verbose=False):
    """(findings, sections) for one file. wcag: a PDF is checked against
    veraPDF's WCAG 2.2 machine profile too, its own section saying
    whether the checks ran; verbose: each of its failed checks a finding,
    and an item in the section, where each rule's are counted in one."""
    name = os.path.basename(path)
    if kind in ("source-docx", "source-md"):
        found = sourcecheck.check(path, kind)
        if kind == "source-docx":
            found += sourcecheck.census_findings(path, tablecensus)
        return found, []
    if kind == "source-pptx":
        # What PowerPoint's own checker reports, and more (pptxcheck.py),
        # with the defaults for alt text's length and placeholders: a
        # project's own are read by convert.py, which checks decks too.
        try:
            deck = pptxparse.read(path)
        except Exception as exc:       # a deck with a password, or no deck at all
            return [fl.Finding(name, "source-unreadable", str(exc)[:200], file=name,
                               kind="source-pptx")], []
        return pptxcheck.check(deck, name), []
    if kind == "html":
        pages = outputcheck.check_html_files([path])
        found = [fl.Finding(f.where, f.check, f.detail, file=name, kind="html")
                 for f in pages]
        if validators:
            more, notes = outputcheck.run_validators([path], [])
            found += [fl.Finding(f.where, f.check, f.detail, file=name,
                                 kind="html", tool="vnu") for f in more]
            for note in notes:
                print(f"  {note}", file=sys.stderr)
        return found, []
    if kind == "epub":
        found = [fl.Finding(f.where, f.check, f.detail, file=name, kind="epub")
                 for f in outputcheck.check_epub(path)]
        if validators:
            more, notes = outputcheck.run_validators([], [path])
            found += [fl.Finding(f.where, f.check, f.detail, file=name,
                                 kind="epub", tool="epubcheck") for f in more]
            for note in notes:
                print(f"  {note}", file=sys.stderr)
        return found, []
    if kind == "pdf":
        facts, found = pdfcheck.inspect(path)
        sections = [(f"{name}: metadata and claims", pdfcheck.facts_lines(facts))]
        command = outputcheck.find_validator("verapdf") if validators else None
        if command:
            found = pdfcheck.settle_claims(
                found, pdfcheck.run_verapdf(command, path))
        if wcag:
            if not validators:
                lines = ["veraPDF's WCAG checks not run (--quick)."]
            elif not command:
                lines = ["veraPDF's WCAG checks not run: veraPDF not found (set "
                         "VERAPDF, or put verapdf on the path)."]
            else:
                more, lines = pdfcheck.run_verapdf_wcag(command, [path], verbose=verbose)
                found += more
            for line in lines:
                print(f"  {line}", file=sys.stderr)
            # A failed check's line, with --verbose, an item under its rule's.
            sections.append((f"{name}: veraPDF's WCAG 2.2 checks",
                             [f"  - {line.strip()}" if line.startswith("  ") else f"- {line}"
                              for line in lines]))
        return found, sections
    return [], []


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("paths", nargs="+")
    parser.add_argument("-o", "--output", help="directory for audit.csv, "
                        "audit.md, and the cache (default: the first "
                        "directory given, else the current one)")
    parser.add_argument("--force", action="store_true",
                        help="audit every file, cached or not")
    parser.add_argument("--no-cache", action="store_true",
                        help="neither read nor write the cache")
    parser.add_argument("--quick", action="store_true",
                        help="skip the external validators")
    parser.add_argument("--wcag", action="store_true",
                        help="check each PDF against veraPDF's WCAG 2.2 machine profile "
                             "too, with its WCAG modules from VERAPDF_WCAG; experimental, "
                             "so what it finds is a note, never an error")
    parser.add_argument("--verbose", action="store_true",
                        help="with --wcag, a note for each of its failed checks, listed in "
                             "the report too, with what the PDF has there (a link's address, "
                             "the line repeated characters are on), where each rule's are "
                             "otherwise counted in one")
    parser.add_argument("--report-html", action="store_true",
                        help="also write the report as audit.html")
    parser.add_argument("--report-docx", action="store_true",
                        help="also write the report as audit.docx, in the "
                             "current Word format so Word's own checker "
                             "runs on it")
    args = parser.parse_args()

    files = gather(args.paths)
    if not files:
        sys.exit("Nothing to audit.")
    out_dir = args.output or next(
        (p for p in args.paths if os.path.isdir(p)), ".")
    os.makedirs(out_dir, exist_ok=True)
    cache = None if args.no_cache else fl.Cache(os.path.join(out_dir,
                                                             "audit-cache.json"))
    inputs = [fl.describe_input(path) for path, _ in files]
    report_md = os.path.join(out_dir, "audit.md")
    # What changes what a report says, besides its inputs, and what a
    # file's findings are; --wcag changes only a PDF's, which is always
    # read again.
    if args.verbose and not args.wcag:
        print(pdfcheck.WCAG_ALONE, file=sys.stderr)
    options = {"quick": bool(args.quick), "wcag": bool(args.wcag)}
    per_file = {"quick": bool(args.quick)}
    # Nothing changed since the last audit: say so and leave the report
    # as it is, so its date stays the date of the audit it records. Not
    # with --wcag, whose findings turn on veraPDF's WCAG modules, which the
    # cache can't see: a report made before they were set up isn't current
    # once they are.
    if cache is not None and not args.force and not args.wcag \
            and os.path.exists(report_md) \
            and all(cache.lookup(i["sha256"], per_file) is not None for i in inputs) \
            and cache.same_inputs((i["sha256"] for i in inputs), options):
        when = cache.audited_at()
        print(f"Nothing has changed since the audit of {when}; "
              f"{report_md} is current. --force audits again.",
              file=sys.stderr)
        found = [f for i in inputs for f in cache.lookup(i["sha256"], per_file)]
        return 1 if any(f.severity == "error" for f in found) else 0
    all_found, sections = [], []
    for (path, kind), item in zip(files, inputs):
        cached = None if (args.force or cache is None) else cache.lookup(
            item["sha256"], per_file)
        if cached is not None and kind != "pdf":
            print(f"  {os.path.basename(path)}: unchanged, {len(cached)} "
                  "finding(s) from the last audit", file=sys.stderr)
            all_found += cached
            continue
        found, extra = audit_one(path, kind, not args.quick, args.wcag, args.verbose)
        print(f"  {os.path.basename(path)}: {len(found)} finding(s)",
              file=sys.stderr)
        all_found += found
        sections += extra
        if cache is not None:
            cache.store(item["sha256"], found, per_file)
    if cache is not None:
        cache.note_inputs((i["sha256"] for i in inputs), options)
        cache.save()
    fl.write_csv(os.path.join(out_dir, "audit.csv"), all_found)
    fl.write_report(report_md, all_found, inputs, sections, version=VERSION)
    if args.report_html:
        fl.render_html(report_md, os.path.join(out_dir, "audit.html"),
                       os.path.join(HERE, "page.css"))
    if args.report_docx:
        fl.render_docx(report_md, os.path.join(out_dir, "audit.docx"),
                       os.path.join(HERE, "..", "util", "docx-compat.py"))
    print("\n".join(fl.summary_lines(all_found)), file=sys.stderr)
    print(f"Written to {os.path.join(out_dir, 'audit.csv')} and audit.md.",
          file=sys.stderr)
    return 1 if any(fl.upgrade(f).severity == "error" for f in all_found) \
        else 0


if __name__ == "__main__":
    sys.exit(main())
