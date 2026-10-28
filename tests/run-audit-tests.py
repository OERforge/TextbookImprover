#!/usr/bin/env python3
"""
run-audit-tests.py -- the audit: one file of each kind, the shared
findings format, the cache, and that the source check agrees with the
filter about what an image without alt text is. Needs Pandoc.

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
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin")
FIXTURES = os.path.join(HERE, "fixtures")
sys.path.insert(0, os.path.join(ROOT, "lib"))
import findings as fl  # noqa: E402
import sourcecheck  # noqa: E402

MARKDOWN = """---
title: A Page
---

# A Page

Text with a bare [https://example.org/](https://example.org/) link and
an image ![](nothing.png) with no alt, one that is
![](spacer.png){.decorative} decorative, and one described
![A pipe](pipe.png). And alt text that says nothing, ![Picture 3](shape.png),
one Office generated, ![A dog on a lawn Description automatically
generated](dog.png), one copied from a web page with its picture,
![Marketing Mix Explained | Quizlet](mix.png), and one holding a file's
name, ![Figure 2 (fig2.png)](fig2.png). One that is only a credit,
![Source: Roe and Doe (2020)](roe.png), and one alt text on two pictures,
![A rising line](up.png) and ![A rising line](up-2.png), which are one
picture, and ![A rising line.](down.png), which isn't.

And one whose scheme is in capitals,
[HTTPS://example.org/report](HTTPS://example.org/report).

| a | b |
|---|---|
| 1 | 2 |

|   |   |
|---|---|
| x | 1 |
| y | 2 |

|   |   |
|---|---|
| a | 1 |
| a | 2 |

::: row-headers
|   |   |
|---|---|
| p | 1 |
| q | 2 |
:::

### Skipped a level

$$x = 1\\ $$
"""

HTML = """<!DOCTYPE html><html lang="en"><head><title>T</title></head>
<body><h1>T</h1><img src="p.png"></body></html>
"""


def run(arguments, cwd):
    return subprocess.run([sys.executable] + arguments, cwd=cwd,
                          capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)


def checks_of(findings):
    return sorted(f.check for f in findings)


def case_sources():
    md = sourcecheck.check(os.path.join(WORK, "page.md"), "source-md")
    c = checks_of(md)
    return [
        ("an image with no alt and no decorative marker is found, once",
         lambda: c.count("source-image-no-alt") == 1),
        # By the rules a deck's pictures are judged by (alttext.py).
        ("and alt text that says nothing, why named, one Office generated, one copied from a "
         "web page, and one holding a file's name, each once",
         lambda: [f.detail for f in md if f.check == "source-image-alt-placeholder"]
         == ["shape.png: 'Picture 3' (a default shape name)"]
         and [c.count("source-image-alt-" + k) for k in ("auto-generated", "page-title",
                                                          "is-file-name", "credit")]
         == [1, 1, 1, 1]),
        ("and one alt text on different pictures, told apart by their files' bytes, so "
         "two files holding one picture are one",
         lambda: [f.detail for f in md if f.check == "source-image-alt-shared"] == [
             "up.png: 'A rising line' (shared with 1 other image)",
             "up-2.png: 'A rising line' (shared with 1 other image)",
             "down.png: 'A rising line.' (shared with 1 other image)"]),
        ("a Word file's image is told apart by its file in the archive",
         lambda: sourcecheck.picture(os.path.join(FIXTURES, "media-a.docx"), "source-docx")(
             "media/image1.png") == hashlib.sha256(zipfile.ZipFile(os.path.join(
                 FIXTURES, "media-a.docx")).read("word/media/image1.png")).hexdigest()),
        ("a bare-URL link is found",
         lambda: "source-link-bare-url" in c),
        # Compared as written, a scheme in capitals wasn't a scheme.
        ("and so is one whose scheme is in capitals",
         lambda: [f.detail for f in md if f.check == "source-link-bare-url"]
         == ["https://example.org/", "HTTPS://example.org/report"]),
        # The keyed one's first column names each row once; the found
        # one's doesn't.
        ("a headerless table is found, a marked one and a keyed one are not",
         lambda: [f.where for f in md if f.check == "source-table-no-headers"]
         == ["table 3"]),
        ("a skipped heading level is found",
         lambda: "source-heading-skips-level" in c),
        ("math ending in a thin space is found",
         lambda: "source-math-trailing-space" in c),
    ]


def case_agreement():
    """The filter's alt report and the source check count the same
    images on the fixture book."""
    docx = os.path.join(FIXTURES, "media-a.docx")
    source = sourcecheck.check(docx, "source-docx")
    ours = sum(1 for f in source if f.check == "source-image-no-alt")
    result = subprocess.run(
        ["pandoc", "-f", "docx", "-t", "html", docx,
         "--lua-filter", os.path.join(BIN, "figures-and-tables.lua")],
        capture_output=True, text=True)
    # The filter says so once an image (it had said a count, which this
    # went on looking for, and so agreed with anything).
    filter_count = result.stderr.count("image has no alt text:")
    return [
        ("the source check and the filter agree on images needing alt text",
         lambda: result.returncode == 0 and ours == filter_count > 0),
    ]


def case_front_door():
    out = os.path.join(WORK, "out")
    first = run([os.path.join(BIN, "audit.py"), WORK, "-o", out, "--quick"],
                WORK)
    csv_path = os.path.join(out, "audit.csv")
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))
    header, body = rows[0], rows[1:]
    kinds = {r[4] for r in body}
    report = open(os.path.join(out, "audit.md"), encoding="utf-8").read()
    stamp = os.path.getmtime(os.path.join(out, "audit.md"))
    second = run([os.path.join(BIN, "audit.py"), WORK, "-o", out, "--quick"],
                 WORK)
    untouched = os.path.getmtime(os.path.join(out, "audit.md")) == stamp
    forced = run([os.path.join(BIN, "audit.py"), WORK, "-o", out, "--quick",
                  "--force", "--report-html", "--report-docx"], WORK)
    back = fl.read_csv(csv_path)
    standards = {r[6] for r in body if r[6]}
    # The PDF, which pypdf writes (main): none without it.
    pdf = os.path.exists(os.path.join(WORK, "blank.pdf"))
    no_pdf = "no pypdf to write a PDF to audit (sudo apt install python3-pypdf)"
    return [
        ("the audit runs over a directory of mixed files",
         lambda: os.path.exists(csv_path)),
        ("the CSV keeps the three original columns first, then the rest",
         lambda: header == fl.COLUMNS),
        ("a Word source, a Markdown source, a page, and an EPUB are each audited",
         lambda: {"source-docx", "source-md", "html", "epub"} <= kinds),
        ("and a PDF",
         lambda: "pdf" in kinds if pdf else print("  skip  " + no_pdf) or True),
        ("the report lists every input with its hash",
         lambda: "## Inputs" in report and sorted(re.findall(
             r"^- `[^`]*/([^/`]+)` \u2014 [\d,]+ bytes, SHA-256 `", report, re.M))
         == ["blank.pdf"] * pdf + ["book.epub", "media-a.docx", "page.html", "page.md"]),
        ("and the PDF's metadata and claims",
         lambda: "metadata and claims" in report and "**Tagged:**" in report
         if pdf else print("  skip  " + no_pdf) or True),
        ("with nothing changed, the report is left as it is and said to be "
         "current",
         lambda: "is current" in second.stderr and untouched),
        ("unless forced",
         lambda: "unchanged" not in forced.stderr and "is current"
         not in forced.stderr),
        ("--report-html and --report-docx render the report",
         lambda: os.path.exists(os.path.join(out, "audit.html"))
         and os.path.exists(os.path.join(out, "audit.docx"))),
        ("a WCAG standard names the version, the criterion, and its level",
         lambda: all(re.match(r"WCAG 2\.\d SC \d\.\d+\.\d+ \((A|AA|AAA)\)$", s)
                     for s in standards if s.startswith("WCAG"))),
        ("the CSV reads back into the same findings",
         lambda: len(back) == len(body)),
        ("the exit code says whether anything is an error",
         lambda: first.returncode == 1),
    ]


def case_wcag():
    """--wcag, with a stand-in for veraPDF: a note for each rule of the
    WCAG profile a PDF fails, counting its failed checks, and with
    --verbose one for each failed check, an item in the report under its
    rule's, notes that leave the exit status the other findings', a
    section of the report saying the checks ran and may be wrong, a run
    with --wcag never taking the report for current, since what it finds
    turns on a setup the cache can't see, a report made with other
    options not taken for the one asked for, and a page read with
    another --quick read again."""
    sys.path.insert(0, HERE)
    import fakeverapdf
    import pdfcheck
    try:
        import pypdf
        from pypdf.generic import BooleanObject, DictionaryObject, NameObject
    except ImportError:
        print("  skip  pypdf not installed; veraPDF's WCAG checks aren't asked of a PDF")
        return []
    folder = os.path.join(WORK, "wcag")
    os.makedirs(folder)
    probe = os.path.join(WORK, "probe.pdf")
    with open(probe, "wb") as fh:
        fh.write(pdfcheck.wcag_probe())
    # A tagged PDF with a title it displays, so no finding of its own is
    # an error, and the exit status says whether the profile's are.
    writer = pypdf.PdfWriter(clone_from=probe)
    writer.add_metadata({"/Title": "A Book"})
    writer._root_object[NameObject("/ViewerPreferences")] = DictionaryObject(
        {NameObject("/DisplayDocTitle"): BooleanObject(True)})
    with open(os.path.join(folder, "book.pdf"), "wb") as fh:
        writer.write(fh)
    with open(os.path.join(folder, "page.html"), "w", encoding="utf-8") as fh:
        fh.write('<!DOCTYPE html><html lang="en"><head><title>A page</title></head>'
                 "<body><h1>A page</h1><p>Text.</p></body></html>\n")
    out = os.path.join(WORK, "wcag-out")
    env = dict(os.environ, VERAPDF=fakeverapdf.install(os.path.join(WORK, "fake-verapdf")),
               VERAPDF_WCAG=fakeverapdf.modules(os.path.join(WORK, "wcag-modules")))

    def audit(*flags):
        result = subprocess.run([sys.executable, os.path.join(BIN, "audit.py"), folder,
                                 "-o", out, *flags], cwd=WORK, capture_output=True,
                                text=True, stdin=subprocess.DEVNULL, env=env)
        found = fl.read_csv(os.path.join(out, "audit.csv"))
        with open(os.path.join(out, "audit.md"), encoding="utf-8") as fh:
            return result, found, fh.read()
    plain, plain_found, _ = audit()
    ran, found, report = audit("--wcag")
    loud, loud_found, loud_report = audit("--wcag", "--verbose")
    alone, _, _ = audit("--verbose")
    again, _, _ = audit("--wcag")
    without, without_found, without_report = audit()
    quick, _, _ = audit("--quick")
    quick_again, _, _ = audit("--quick")
    wcag = [f for f in found if f.check.startswith("verapdf-wcag:")]
    return [
        ("--wcag adds a note for each rule of the profile the PDF fails",
         lambda: sorted((f.where, f.check, f.severity) for f in wcag) == [
             ("book.pdf", "verapdf-wcag:1.3.1-1", "note"),
             ("book.pdf", "verapdf-wcag:2.4.9-1", "note")]),
        ("and with --verbose, one for each failed check, at its page, an item in the report "
         "under its rule's",
         lambda: sorted((f.where, f.check, f.severity) for f in loud_found
                        if f.check.startswith("verapdf-wcag:")) == [
             ("book.pdf#page=3", "verapdf-wcag:2.4.9-1", "note"),
             ("book.pdf#page=653", "verapdf-wcag:1.3.1-1", "note")]
         and "\n- book.pdf: verapdf-wcag:1.3.1-1, " in loud_report
         and "\n  - book.pdf#page=653: Text contains 7 repeated non space characters\n"
         in loud_report and "--verbose" not in loud_report
         and "run again with --verbose" in report),
        ("--verbose without --wcag says it changes nothing",
         lambda: pdfcheck.WCAG_ALONE in alone.stderr),
        ("and leaves the exit status the other findings', none of them an error",
         lambda: plain.returncode == ran.returncode == 0
         and not [f for f in plain_found if f.severity == "error"]),
        ("the report has a section on them, saying they ran and may be wrong",
         lambda: "## book.pdf: veraPDF's WCAG 2.2 checks" in report
         and "experimental and may be wrong" in report),
        ("a second audit with --wcag doesn't take the report for current, and checks "
         "the PDF again, the page coming from the cache",
         lambda: "is current" not in again.stderr
         and "book.pdf: " in again.stderr and "page.html: unchanged" in again.stderr),
        ("one without --wcag doesn't take it for current either, and leaves the profile out",
         lambda: "is current" not in without.stderr
         and not any(f.check.startswith("verapdf-wcag:") for f in without_found)
         and "WCAG 2.2 checks" not in without_report),
        ("one with --quick after one without reads the page again, its findings found "
         "with the validators",
         lambda: "is current" not in quick.stderr
         and "page.html: unchanged" not in quick.stderr),
        ("and another with --quick finds the report current",
         lambda: "is current" in quick_again.stderr),
    ]


def case_check_only():
    d = os.path.join(WORK, "book")
    os.makedirs(d, exist_ok=True)
    shutil.copy(os.path.join(FIXTURES, "tables.docx"), d)
    with open(os.path.join(d, "project.yaml"), "w") as fh:
        fh.write("project:\n  identifier: org.example.c\n  title: C\n")
    result = run([os.path.join(BIN, "convert.py"), "--quiet", "--check-only"],
                 d)
    return [
        ("convert.py --check-only writes the reports and stops",
         lambda: result.returncode == 0
         and os.path.exists(os.path.join(d, "table-headers-new.csv"))
         and not os.path.exists(os.path.join(d, "html"))),
    ]


def main():
    global WORK
    keep = "--keep" in sys.argv
    WORK = tempfile.mkdtemp(prefix="audit-tests-")
    with open(os.path.join(WORK, "page.md"), "w", encoding="utf-8") as fh:
        fh.write(MARKDOWN)
    for name, data in (("up.png", b"up"), ("up-2.png", b"up"), ("down.png", b"down")):
        with open(os.path.join(WORK, name), "wb") as fh:
            fh.write(data)
    with open(os.path.join(WORK, "page.html"), "w", encoding="utf-8") as fh:
        fh.write(HTML)
    shutil.copy(os.path.join(FIXTURES, "media-a.docx"), WORK)
    # An EPUB, as Pandoc writes one, which says nothing of its
    # accessibility: one finding at least, so its kind is in the report.
    subprocess.run(["pandoc", "-f", "markdown", "-t", "epub3", "-o",
                    os.path.join(WORK, "book.epub"), "--metadata", "title=A Book",
                    "--metadata", "lang=en"], input="# A Chapter\n\nText.\n",
                   capture_output=True, text=True)
    # A minimal PDF: pypdf writes one.
    try:
        import pypdf
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=200, height=200)
        with open(os.path.join(WORK, "blank.pdf"), "wb") as fh:
            writer.write(fh)
    except ImportError:
        print("  skip  pypdf not installed; no PDF in this run")
    failed = 0
    for name, case in [("what a source says about itself", case_sources),
                       ("the source check agrees with the filter",
                        case_agreement),
                       ("the front door", case_front_door),
                       ("veraPDF's WCAG checks, asked for", case_wcag),
                       ("convert.py --check-only", case_check_only)]:
        print(f"\n{name}")
        try:
            checks = case()
        except Exception as exc:                # noqa: BLE001
            print(f"  ERROR {name}: {exc}")
            failed += 1
            continue
        for label, check in checks:
            try:
                ok = bool(check())
            except Exception as exc:            # noqa: BLE001
                ok, label = False, f"{label}  ({exc})"
            print(f"  {'ok  ' if ok else 'FAIL'}  {label}")
            failed += 0 if ok else 1
    if not keep:
        shutil.rmtree(WORK, ignore_errors=True)
    print()
    print("all audit checks passed" if not failed
          else f"{failed} check(s) failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
