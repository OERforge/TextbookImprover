#!/usr/bin/env python3
"""
audit.py -- what is wrong with a file, without converting it.

    python3 audit.py FILE-OR-DIRECTORY ... [-o DIR] [--force] [--no-cache]

Takes Word and Markdown sources, PowerPoint decks, HTML pages, EPUBs,
and PDFs, in any mix, and writes two things to the output directory (the first
directory given, or -o): audit.csv, one finding per row in the format
every check here shares, and audit.md, the same findings as a report a
person reads, with each PDF's metadata and claims. A file already
audited where it is, and unchanged since (by SHA-256), is not read again
unless --force says so; and with no file read again, no check run, and
what each check's findings turn on as it was when the report was made,
the report is current, and is left as it is. The reports aren't among
what it reads, nor is a report an audit wrote found in a directory
given, and it writes over nothing in the output directory that an audit
didn't write: a file there by the name of one it writes stops it,
unless an audit wrote it.

Depends on lib/ and on Pandoc (to read a source), and optionally on
pypdf (PDFs), epubcheck, the Nu HTML checker, and veraPDF, each found
the way the output check finds them and reported as absent when they
are. --wcag checks against WCAG's machine-testable criteria as well, as
check-output.py --wcag does, WCAG 2.1 AA unless --wcag-version and
--wcag-level say otherwise: axe-core on the HTML pages and EPUBs, in one
browser for all of them (with Playwright, optional), and veraPDF's WCAG
2.2 machine profile on each PDF. What they find is a note, never an
error, one for each rule a file fails, and the report has a section
saying whether the checks ran; --verbose makes each element axe-core
names and each check veraPDF failed a note, with what the file has
there. With --wcag, DAISY's Ace runs on each EPUB too, when it's
installed, its own checks notes as the rest are. axe-core's findings on
a page are kept in the cache too, and a page isn't checked again while
it and every file it loads are unchanged and so are axe-core,
Playwright, and the rules, nor an EPUB by Ace while it and Ace are, nor
a PDF by veraPDF's WCAG profile while it, veraPDF, and the folder of its
WCAG modules are. A PDF's own checks are kept too, its metadata and
claims and veraPDF's PDF/UA run, and an unchanged PDF isn't read again
while pypdf and veraPDF are the same.

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
import hashlib
import json
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

import acecheck  # noqa: E402
import axecheck  # noqa: E402
import findings as fl  # noqa: E402
import outputcheck  # noqa: E402
import pdfcheck  # noqa: E402
import pptxcheck  # noqa: E402
import pptxparse  # noqa: E402
import sourcecheck  # noqa: E402
import tablecensus  # noqa: E402
import wcag as wcag_lib  # noqa: E402

VERSION = "0.9"
KIND_OF = {".docx": "source-docx", ".md": "source-md", ".html": "html",
           ".xhtml": "html", ".epub": "epub", ".pdf": "pdf", ".pptx": "source-pptx"}
# The report's three forms, by their names in the folder the audit writes
# to, and what one an audit wrote opens with, its tags dropped: the
# report's heading and the line that dates it, as fl.write_report has
# written them since the audit came in (0.6). The CSV opens with the
# columns every findings file shares (fl.read_csv).
REPORTS = ("audit.md", "audit.html", "audit.docx")
REPORT_OPENING = re.compile(r"(?:#\s*)?Accessibility audit\s+Produced\s")
CSV_OPENING = ",".join(fl.COLUMNS[:3])


def opening(path):
    """A file's text from its start, its tags dropped and its spaces made
    one: a Word file's document's, a page's from its body (a report's
    stylesheet is in its head); "" when it can't be read."""
    try:
        if path.lower().endswith(".docx"):
            with zipfile.ZipFile(path) as z:
                text = z.read("word/document.xml").decode("utf-8", "replace")
        else:
            with open(path, encoding="utf-8-sig", errors="replace") as fh:
                text = fh.read()
    except (OSError, KeyError, zipfile.BadZipFile):
        return ""
    if not path.lower().endswith(".md"):
        body = re.search(r"<(?:w:)?body\b", text)
        text = re.sub(r"<[^>]*>", " ", text[body.start():] if body else text)
    return " ".join(text.split())


def written_by_audit(path):
    """Whether a file named as one an audit writes is one an audit wrote:
    a report, in any of its forms, or its CSV."""
    if path.lower().endswith(".csv"):
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as fh:
                return fh.readline().startswith(CSV_OPENING)
        except OSError:
            return False
    return bool(REPORT_OPENING.match(opening(path)))


def gather(paths):
    """The files to audit, from files and directories given. A report an
    audit wrote, found in a directory, isn't one: an audit of a folder
    writes its reports into it unless -o says otherwise."""
    out = []
    for path in paths:
        if os.path.isdir(path):
            for name in sorted(os.listdir(path)):
                full = os.path.join(path, name)
                kind = KIND_OF.get(os.path.splitext(name)[1].lower())
                if kind and os.path.isfile(full) and not name.startswith("~$") \
                        and not (name.lower() in REPORTS and written_by_audit(full)):
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


class Tally:
    """What an audit's checks did, which says whether its report is
    current: how many times one read a file or ran on one (ran), and what
    each one's findings turned on besides the files (said): its setup's
    key, or, from a check that couldn't run, what it said."""

    def __init__(self):
        self.ran, self.said = 0, []

    def add(self, check, part, lines, path=""):
        """A check's part of the tally, the dict it was given ("setup",
        "ran"), and the lines it said; path names the file it checked,
        for a check that runs on each file alone."""
        self.ran += part.get("ran", 0)
        self.said.append([check, path, part.get("setup") or lines])

    def digest(self):
        return hashlib.sha256(json.dumps(self.said).encode("utf-8")).hexdigest()


def audit_one(path, kind, validators, wcag=False, verbose=False,
              version=wcag_lib.DEFAULT_VERSION, level=wcag_lib.DEFAULT_LEVEL,
              wcag_cache=None, reuse=True, pdf_cache=None, tally=None):
    """(findings, sections, ran) for one file; ran: how many of its
    checks read it or ran on it, 0 for a PDF whose checks the cache kept.
    wcag: a PDF is checked against veraPDF's WCAG 2.2 machine profile
    too, for the criteria of WCAG version at level, its own section
    saying whether the checks ran; verbose: each of its failed checks a
    finding, and an item in the section, where each rule's are counted
    in one. wcag_cache: the audit cache's part for those checks, a PDF's
    kept there and, with reuse, read again while it, veraPDF, and its
    WCAG modules are the same (pdfcheck.wcag_setup); pdf_cache: its part
    for a PDF's own checks, its metadata and claims, read with pypdf,
    and veraPDF's PDF/UA run, kept there and, with reuse, read again
    while it, pypdf, and veraPDF are the same (pdfcheck.own_checks).
    tally: a Tally, given what a PDF's checks did. A page's and an EPUB's
    WCAG checks are audit_pages'."""
    name = os.path.basename(path)
    if tally is None:
        tally = Tally()
    if kind in ("source-docx", "source-md"):
        found = sourcecheck.check(path, kind)
        if kind == "source-docx":
            found += sourcecheck.census_findings(path, tablecensus)
        return found, [], 1
    if kind == "source-pptx":
        # What PowerPoint's own checker reports, and more (pptxcheck.py),
        # with the defaults for alt text's length and placeholders: a
        # project's own are read by convert.py, which checks decks too.
        try:
            deck = pptxparse.read(path)
        except Exception as exc:       # a deck with a password, or no deck at all
            return [fl.Finding(name, "source-unreadable", str(exc)[:200], file=name,
                               kind="source-pptx")], [], 1
        return pptxcheck.check(deck, name), [], 1
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
        return found, [], 1
    if kind == "epub":
        found = [fl.Finding(f.where, f.check, f.detail, file=name, kind="epub")
                 for f in outputcheck.check_epub(path)]
        if validators:
            more, notes = outputcheck.run_validators([], [path])
            found += [fl.Finding(f.where, f.check, f.detail, file=name,
                                 kind="epub", tool="epubcheck") for f in more]
            for note in notes:
                print(f"  {note}", file=sys.stderr)
        return found, [], 1
    if kind == "pdf":
        command = outputcheck.find_validator("verapdf") if validators else None
        part = {}
        facts, found, kept = pdfcheck.own_checks(path, command, pdf_cache, reuse, part)
        tally.add("pdf", part, [], path)
        ran = part["ran"]
        lines = pdfcheck.facts_lines(facts)
        if kept:
            lines.append(f"- **Not read again:** the PDF is unchanged since the audit that read "
                         f"it ({fl.md_text(kept)}), as pypdf is"
                         + (" and veraPDF" if command else "")
                         + ", so this section and the PDF's own findings are that audit's.")
        sections = [(f"{name}: metadata and claims", lines)]
        if wcag:
            part = {}
            if not validators:
                lines = ["veraPDF's WCAG checks not run (--quick)."]
            elif not command:
                lines = ["veraPDF's WCAG checks not run: veraPDF not found (set "
                         "VERAPDF, or put verapdf on the path)."]
            else:
                more, lines = pdfcheck.run_verapdf_wcag(command, [path], verbose=verbose,
                                                        wcag_version=version,
                                                        wcag_level=level, cache=wcag_cache,
                                                        reuse=reuse, tally=part)
                found += more
            tally.add("verapdf-wcag", part, lines, path)
            ran += part.get("ran", 0)
            for line in lines:
                print(f"  {line}", file=sys.stderr)
            # A failed check's line, with --verbose, an item under its rule's;
            # each as text, since it may quote the PDF's.
            sections.append((f"{name}: veraPDF's WCAG 2.2 checks",
                             [f"  - {fl.md_text(line.strip())}" if line.startswith("  ")
                              else f"- {fl.md_text(line)}" for line in lines]))
        return found, sections, ran
    return [], [], 1


def audit_ace(files, validators, cache=None, reuse=True, tally=None):
    """(findings, sections) of DAISY's Ace on the EPUBs among the files,
    when it's installed, its section saying whether it ran; for --wcag.
    cache: the audit cache's part for it, each EPUB's result kept by where
    the EPUB is, with its SHA-256, and, with reuse, used again while it
    and Ace are the same (acecheck.check). tally: a Tally, given what
    Ace did."""
    epubs = [path for path, kind in files if kind == "epub"]
    if not epubs:
        return [], []
    found, lines, part = [], [acecheck.NOT_RUN_QUICK], {}
    if validators:
        command, why = acecheck.find()
        lines = [why]
        if command:
            found, lines = acecheck.check(command, epubs, by_epub=True, cache=cache,
                                          reuse=reuse, tally=part)
    if tally is not None:
        tally.add("ace", part, lines)
    for line in lines:
        print(f"  {line}", file=sys.stderr)
    return found, [("EPUBs: DAISY's Ace", [f"- {fl.md_text(line)}" for line in lines])]


def audit_pages(files, validators, verbose, version, level, best_practice, experimental,
                cache=None, reuse=True, tally=None):
    """(findings, sections) of axe-core's rules on the HTML pages and EPUBs
    among the files, in one worker for all of them, its section saying
    whether they ran; for --wcag. cache: the audit cache's part for them,
    each page's result kept there and, with reuse, used again where the
    page hasn't changed (axecheck.kept). tally: a Tally, given what
    axe-core did."""
    pages = [path for path, kind in files if kind == "html"]
    epubs = [path for path, kind in files if kind == "epub"]
    if not pages and not epubs:
        return [], []
    found, lines, part = [], [axecheck.NOT_RUN_QUICK], {}
    if validators:
        # Each finding filed under the file audited, an EPUB's under the EPUB.
        found, lines = axecheck.check(pages, epubs, version=version, level=level,
                                      best_practice=best_practice, experimental=experimental,
                                      verbose=verbose, by_epub=True, cache=cache, reuse=reuse,
                                      tally=part)
    if tally is not None:
        tally.add("axe", part, lines)
    for line in lines:
        print(f"  {line}", file=sys.stderr)
    return found, [("HTML pages and EPUBs: axe-core's WCAG checks",
                    [f"  - {fl.md_text(line.strip())}" if line.startswith("  ")
                     else f"- {fl.md_text(line)}" for line in lines])]


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
                        help="check against WCAG's machine-testable criteria too: axe-core "
                             "on the HTML pages and EPUBs, with Playwright, veraPDF's "
                             "WCAG 2.2 machine profile on each PDF, with its WCAG modules "
                             "from VERAPDF_WCAG, and DAISY's Ace on each EPUB, when it's "
                             "installed; what they find is a note, never an error")
    wcag_lib.add_choices(parser)
    parser.add_argument("--verbose", action="store_true",
                        help="with --wcag, a note for each element axe-core names and each "
                             "check veraPDF failed, listed in the report too, with what the "
                             "file has there (an element's markup, a link's address), where "
                             "each rule's are otherwise counted in one")
    parser.add_argument("--report-html", action="store_true",
                        help="also write the report as audit.html")
    parser.add_argument("--report-docx", action="store_true",
                        help="also write the report as audit.docx, in the "
                             "current Word format so Word's own checker "
                             "runs on it")
    args = parser.parse_args()

    out_dir = args.output or next(
        (p for p in args.paths if os.path.isdir(p)), ".")
    # What this audit writes goes over nothing in its folder that an
    # audit didn't write (a book's chapter named audit.md, say), and none
    # of it is read as a file to audit, even named.
    names = ["audit.csv", "audit.md"]
    if args.report_html:
        names.append("audit.html")
    if args.report_docx:
        names.append("audit.docx")
    writes = [os.path.join(out_dir, name) for name in names]
    for target in writes:
        if os.path.exists(target) and not written_by_audit(target):
            sys.exit(f"{target} wasn't written by an audit, and this one would write "
                     "over it: -o names another folder for what it writes.")
    files = []
    for path, kind in gather(args.paths):
        if any(os.path.exists(target) and os.path.samefile(path, target)
               for target in writes):
            print(f"Skipping {path}: it's this audit's own report.", file=sys.stderr)
        else:
            files.append((path, kind))
    if not files:
        sys.exit("Nothing to audit.")
    os.makedirs(out_dir, exist_ok=True)
    cache = None if args.no_cache else fl.Cache(os.path.join(out_dir,
                                                             "audit-cache.json"))
    inputs = [fl.describe_input(path) for path, _ in files]
    report_md = os.path.join(out_dir, "audit.md")
    if args.verbose and not args.wcag:
        print(pdfcheck.WCAG_ALONE, file=sys.stderr)
    if wcag_lib.choices_given(args) and not args.wcag:
        print(wcag_lib.CHOICES_ALONE, file=sys.stderr)
    version, level, best_practice, experimental = wcag_lib.chosen(args)
    # What the report says turns on, besides its files: --quick, and
    # --wcag with what it's asked to check against, which a page's and a
    # PDF's findings turn on too, kept in parts of their own.
    options = {"quick": bool(args.quick), "wcag": bool(args.wcag)}
    if args.wcag:
        options.update({"version": version, "level": level, "best-practice": best_practice,
                        "experimental": experimental, "verbose": bool(args.verbose)})
    per_file = {"quick": bool(args.quick)}
    tally = Tally()
    all_found, sections = [], []
    for (path, kind), item in zip(files, inputs):
        cached = None if (args.force or cache is None or kind == "pdf") else cache.lookup(
            path, item["sha256"], per_file)
        if cached is not None:
            print(f"  {os.path.basename(path)}: unchanged, {len(cached)} "
                  "finding(s) from the last audit", file=sys.stderr)
            all_found += cached
            continue
        pdf = cache is not None and kind == "pdf"
        found, extra, ran = audit_one(path, kind, not args.quick, args.wcag, args.verbose,
                                      version, level,
                                      cache.part("verapdf-wcag") if pdf and args.wcag else None,
                                      not args.force, cache.part("pdf") if pdf else None, tally)
        if kind != "pdf":
            tally.ran += ran
        print(f"  {os.path.basename(path)}: " + ("unchanged, " if not ran else "")
              + f"{len(found)} finding(s)" + (" from the last audit" if not ran else ""),
              file=sys.stderr)
        all_found += found
        sections += extra
        if cache is not None and kind != "pdf":
            cache.store(path, item["sha256"], found, per_file)
    if args.wcag:
        # After the cache has each file's own findings: axe-core's turn on
        # what's installed too, and on every file a page loads, so they're
        # kept apart, with what they turn on.
        found, extra = audit_pages(files, not args.quick, args.verbose, version, level,
                                   best_practice, experimental,
                                   None if cache is None else cache.part("axe"),
                                   not args.force, tally)
        all_found += found
        sections += extra
        found, extra = audit_ace(files, not args.quick,
                                 None if cache is None else cache.part("ace"), not args.force,
                                 tally)
        all_found += found
        sections += extra
    # Nothing read again, nor checked, and what the checks found turning
    # on what it did when the report was made: the report is current, so
    # it's left as it is, its date the date of the audit it records. Its
    # files are named as given, as the report names them.
    state = {"inputs": [[item["path"], item["sha256"]] for item in inputs],
             "options": options, "said": tally.digest()}
    if cache is not None and not args.force and not tally.ran \
            and all(os.path.exists(target) for target in writes) \
            and cache.report_current(state, names):
        print(f"Nothing has changed since the audit of {cache.audited_at()}; "
              f"{report_md} is current. --force audits again.", file=sys.stderr)
        return 1 if any(fl.upgrade(f).severity == "error" for f in all_found) else 0
    if cache is not None:
        cache.note_report(state, names)
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
