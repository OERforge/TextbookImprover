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
import json
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

![A line of sales rising each year](sales.png)

![A line of sales rising each year](sales-3.png)

![Sales by year](sales-2.png){alt="Sales rose from two units to nine"}

![Source: the census (2020)](census.png)

![A border](border.png){.decorative}

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
         == [1, 1, 1, 2]),
        ("and one alt text on different pictures, told apart by their files' bytes, so "
         "two files holding one picture are one",
         lambda: [f.detail for f in md if f.check == "source-image-alt-shared"] == [
             "up.png: 'A rising line' (shared with 1 other image)",
             "up-2.png: 'A rising line' (shared with 1 other image)",
             "down.png: 'A rising line.' (shared with 1 other image)",
             "sales.png: 'A line of sales rising each year' (shared with 1 other image)",
             "sales-3.png: 'A line of sales rising each year' (shared with 1 other image)"]),
        # Pandoc's Markdown reader gives a figure's image its caption for
        # alt text when it has none, and a tagged PDF says it twice.
        ("a figure's image whose alt text is its caption, as Pandoc copies it, is found, "
         "and not one given alt text of its own or marked decorative",
         lambda: [f.detail for f in md if f.check == "source-image-alt-is-caption"]
         == ["sales.png: 'A line of sales rising each year'",
             "sales-3.png: 'A line of sales rising each year'"]),
        # A rule that finds more to say of the caption's words names what's
        # wrong with them (a review); two such pictures' alt text is still
        # compared with the others' (the shared check above).
        ("and one whose caption another rule finds is found by that rule alone",
         lambda: [f.check for f in md if f.detail.startswith("census.png")]
         == ["source-image-alt-credit"]),
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


def case_own_reports():
    """The reports in the folder the audit writes to, the first folder
    given unless -o names another, aren't among what it reads, and it
    writes over no file there that an audit didn't write."""
    audit = os.path.join(BIN, "audit.py")
    d = os.path.join(WORK, "own")
    os.makedirs(d)
    with open(os.path.join(d, "one.md"), "w", encoding="utf-8") as fh:
        fh.write("---\ntitle: One\nlang: en\n---\n\n# One\n\nText.\n")
    run([audit, d, "--quick", "--report-html", "--report-docx"], d)
    # --force reads every file again, not the cache's findings.
    again = run([audit, d, "--quick", "--force", "--report-html", "--report-docx"], d)
    report = open(os.path.join(d, "audit.md"), encoding="utf-8").read()
    third = run([audit, d, "--quick"], d)
    # Named from the folder, the report is the file -o's path names.
    named = run([audit, "audit.md", "-o", d, "--quick"], d)
    # A report by a name in other letters is one too.
    shutil.copy(os.path.join(d, "audit.html"), os.path.join(d, "Audit.html"))
    elsewhere = run([audit, d, "-o", os.path.join(WORK, "own-out"), "--quick"], d)
    asked = run([audit, os.path.join(d, "audit.md"), "-o", os.path.join(WORK, "own-out"),
                 "--quick"], d)
    # A book whose own files have the reports' names: a chapter on
    # audits, a page, and a Word file.
    b = os.path.join(WORK, "own-book")
    os.makedirs(b)
    chapter = "---\ntitle: Audits\nlang: en\n---\n\n# Audits\n\nAn audit checks.\n"
    page = ('<!DOCTYPE html><html lang="en"><head><title>Audits</title></head>'
            '<body><h1>Audits</h1><p>An audit checks.</p></body></html>\n')
    for name, text in (("audit.md", chapter), ("audit.html", page)):
        with open(os.path.join(b, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    shutil.copy(os.path.join(FIXTURES, "media-a.docx"), os.path.join(b, "audit.docx"))
    word = open(os.path.join(b, "audit.docx"), "rb").read()

    def same(name, text):
        with open(os.path.join(b, name), "rb") as fh:
            return fh.read() == (text.encode("utf-8") if isinstance(text, str) else text)

    stopped = run([audit, b, "--quick"], b)
    stopped_kept = not os.path.exists(os.path.join(b, "audit.csv")) \
        and same("audit.md", chapter)
    away = run([audit, b, "-o", os.path.join(WORK, "own-book-out"), "--quick"], b)
    os.rename(os.path.join(b, "audit.md"), os.path.join(b, "chapter.md"))
    read = run([audit, b, "--quick"], b)
    read_kept = same("audit.html", page) and same("audit.docx", word)
    html_stopped = run([audit, b, "--quick", "--report-html"], b)
    docx_stopped = run([audit, b, "--quick", "--report-docx"], b)
    stopped_kept_both = same("audit.html", page) and same("audit.docx", word)
    c = os.path.join(WORK, "own-csv")
    os.makedirs(c)
    with open(os.path.join(c, "one.md"), "w", encoding="utf-8") as fh:
        fh.write("---\ntitle: One\nlang: en\n---\n\n# One\n\nText.\n")
    table = "Name,Value\nx,1\n"
    with open(os.path.join(c, "audit.csv"), "w", encoding="utf-8") as fh:
        fh.write(table)
    csv_stopped = run([audit, c, "--quick"], c)
    csv_kept = open(os.path.join(c, "audit.csv"), encoding="utf-8").read() == table

    def lines(result):
        return re.findall(r"^  ([^:\n]+): ", result.stderr, re.M)

    refused = "wasn't written by an audit, and this one would write over it"
    return [
        ("a folder audited again, its reports in it, has its own file read, not the "
         "reports, audit.md, audit.html, and audit.docx",
         lambda: lines(again) == ["one.md"] and again.returncode == 0),
        ("and the report lists that file alone among its inputs",
         lambda: re.findall(r"^- `[^`]*/([^/`]+)` \u2014", report, re.M) == ["one.md"]),
        ("so with nothing changed, the next audit says its report is current",
         lambda: "is current" in third.stderr),
        ("the report named as a file to audit is passed over, as the one this audit "
         "writes",
         lambda: "Skipping audit.md: it's this audit's own report." in named.stderr
         and "Nothing to audit." in named.stderr),
        ("a folder's reports aren't read when the audit writes elsewhere either, nor one "
         "named Audit.html",
         lambda: lines(elsewhere) == ["one.md"]),
        ("but a report named, one this audit doesn't write, is read as asked",
         lambda: lines(asked) == ["audit.md"]),
        ("a chapter of the book named audit.md stops the audit, which says so, writes "
         "nothing, and leaves the chapter as it was",
         lambda: stopped.returncode != 0 and refused in stopped.stderr and stopped_kept),
        ("with -o another folder, it's read as the book's, as are the page and the Word "
         "file",
         lambda: lines(away) == ["audit.docx", "audit.html", "audit.md"]),
        ("a page named audit.html and a Word file named audit.docx are read as the book's "
         "when the audit writes neither",
         lambda: lines(read) == ["audit.docx", "audit.html", "chapter.md"] and read_kept),
        ("and each stops the audit that would write over it",
         lambda: all(r.returncode != 0 and refused in r.stderr
                     for r in (html_stopped, docx_stopped)) and stopped_kept_both),
        ("and so does a CSV of the book's named audit.csv",
         lambda: csv_stopped.returncode != 0 and refused in csv_stopped.stderr and csv_kept),
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
    another --quick read again. At AAA, whose rule for 2.4.9 the stand-in
    fails; a section on axe-core's checks of the page, which say why they
    didn't run without Playwright."""
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
    ran, found, report = audit("--wcag", "--wcag-level", "AAA")
    loud, loud_found, loud_report = audit("--wcag", "--verbose", "--wcag-level", "AAA")
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
        ("and one on axe-core's checks of the page, saying they ran or why not",
         lambda: "## HTML pages and EPUBs: axe-core's WCAG checks" in report
         and re.search(r"\n- (axe-core [\d.]+ ran its \d+ rules for WCAG 2\.1 AAA on 1 "
                       r"page\(s\)|axe's WCAG checks not run on the pages)", report)),
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


def fail(message):
    print("        " + message[:2000])
    return False


def browser_problem():
    """Why a page can't be checked in a browser here, or None."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "Playwright isn't installed"
    try:
        with sync_playwright() as play:
            play.chromium.launch().close()
    except Exception as exc:
        return f"Playwright's Chromium doesn't start ({str(exc).strip()[:200]})"
    return None


def case_axe_cache():
    """--wcag keeps axe-core's results on each page in the cache, and
    checks a page again only when it, or a file it loads, has changed,
    an EPUB's content documents each on its own, or when the rules have,
    or with --force; with --no-cache, every page, the cache untouched."""
    problem = browser_problem()
    if problem:
        print(f"  skip  {problem}: axe-core's results aren't cached here")
        return []
    folder = os.path.join(WORK, "axe-cache")
    os.makedirs(folder)
    out = os.path.join(WORK, "axe-cache-out")
    page = ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Page {0}'
            '</title><link rel="stylesheet" href="page.css"></head><body><main><h1>Page {0}'
            '</h1><p class="faint">Faint {0}.</p>{1}</main></body></html>\n')
    for name, text in (("one.html", page.format(1, '<p><img src="later.png" alt=""></p>')),
                       ("two.html", page.format(2, "")),
                       ("page.css", "body { color: #222; } .faint { color: #bbb; }\n")):
        with open(os.path.join(folder, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    chapter = ('<?xml version="1.0" encoding="UTF-8"?><html xmlns="http://www.w3.org/1999/xhtml" '
               'lang="en" xml:lang="en"><head><title>{0}</title><style>p {{ color: #222; }}'
               '</style></head><body><main><h1>{0}</h1><p>{1}</p></main></body></html>')

    def epub(second):
        with zipfile.ZipFile(os.path.join(folder, "book.epub"), "w") as archive:
            archive.writestr("mimetype", "application/epub+zip")
            archive.writestr("META-INF/container.xml", (
                '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:'
                'opendocument:xmlns:container"><rootfiles><rootfile full-path="EPUB/'
                'content.opf" media-type="application/oebps-package+xml"/></rootfiles>'
                "</container>"))
            archive.writestr("EPUB/content.opf", (
                '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
                'version="3.0"><manifest><item id="a" href="a.xhtml" media-type="application/'
                'xhtml+xml"/><item id="b" href="b.xhtml" media-type="application/xhtml+xml"/>'
                '</manifest><spine><itemref idref="a"/><itemref idref="b"/></spine></package>'))
            archive.writestr("EPUB/a.xhtml", chapter.format("One", "First."))
            archive.writestr("EPUB/b.xhtml", chapter.format("Two", second))
    epub("Second.")

    def audit(*flags):
        result = subprocess.run([sys.executable, os.path.join(BIN, "audit.py"), folder,
                                 "-o", out, "--wcag", *flags], cwd=WORK, capture_output=True,
                                text=True, stdin=subprocess.DEVNULL)
        rows = sorted((f.where.replace(os.sep, "/").split("/")[-1], f.check)
                      for f in fl.read_csv(os.path.join(out, "audit.csv")) if f.tool == "axe")
        return result.stderr, rows
    first, first_rows = audit()
    second, second_rows = audit()
    with open(os.path.join(out, "audit-cache.json"), encoding="utf-8") as fh:
        stored = json.load(fh).get("__axe__", {}).get("items", {})
    with open(os.path.join(folder, "page.css"), "w", encoding="utf-8") as fh:
        fh.write("body { color: #222; } .faint { color: #555; }\n")
    restyled, restyled_rows = audit()
    with open(os.path.join(folder, "later.png"), "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n")
    pictured, _ = audit()
    epub("Second, changed.")
    rebuilt, _ = audit()
    other, _ = audit("--best-practice")
    forced, _ = audit("--best-practice", "--force")
    with open(os.path.join(out, "audit-cache.json"), "rb") as fh:
        kept_bytes = fh.read()
    uncached, _ = audit("--best-practice", "--no-cache")
    with open(os.path.join(out, "audit-cache.json"), "rb") as fh:
        after_bytes = fh.read()
    everything = "2 page(s) and 2 content document(s) of 1 EPUB(s)"
    one = next((entry for key, entry in stored.items() if "one.html" in key), {})
    return [
        ("the first audit checks every page and content document",
         lambda: f"ran its 63 rules for WCAG 2.1 AA on {everything}," in first
         or fail("got: " + first)),
        ("the second checks nothing again, saying why, and has the first's findings",
         lambda: f"checked nothing again, since each of {everything}, and every file it "
                 "loads, is unchanged since the audit that checked it" in second
         and second_rows == first_rows and ("one.html", "axe:color-contrast") in first_rows
         or fail("got: " + second)),
        ("a page's result is kept with what its check read: the page, its stylesheet, and "
         "a picture that isn't there",
         lambda: set(one.get("read") or {}) == {"one.html", "page.css", "later.png"}
         and one["read"]["later.png"] is None),
        ("a changed stylesheet has the pages that load it checked again, and their findings "
         "are the new ones",
         lambda: "ran its 63 rules for WCAG 2.1 AA on 2 page(s)," in restyled
         and "2 content document(s) of 1 EPUB(s) weren't checked again" in restyled
         and ("one.html", "axe:color-contrast") not in restyled_rows
         or fail("got: " + restyled)),
        ("a picture that's there now has its page checked again, and only it",
         lambda: "ran its 63 rules for WCAG 2.1 AA on 1 page(s)," in pictured
         or fail("got: " + pictured)),
        ("an EPUB made again has only the content document that changed checked again",
         lambda: "on 1 content document(s) of 1 EPUB(s)," in rebuilt
         and "1 page(s)" not in rebuilt.split("weren't checked again")[0].split("ran its")[-1]
         or fail("got: " + rebuilt)),
        ("other rules have every page checked again, and so does --force",
         lambda: f"ran its 90 rules for WCAG 2.1 AA and its best practices on {everything},"
                 in other and f"its best practices on {everything}," in forced
         or fail("got: " + other + forced)),
        ("--no-cache checks every page, and leaves the cache as it was",
         lambda: f"its best practices on {everything}," in uncached
         and after_bytes == kept_bytes or fail("got: " + uncached)),
    ]


def case_ace():
    """--wcag runs DAISY's Ace on each EPUB, a stand-in here
    (tests/fakeace.py): its own findings notes, filed under the EPUB, a
    section of the report saying it ran; the next audit keeps each
    unchanged EPUB's result, Ace not run, and runs it again on an EPUB
    that has changed, and on every one with --force; --no-cache runs it
    and leaves the cache alone; --quick and no --wcag don't run it."""
    sys.path.insert(0, HERE)
    import fakeace
    folder = os.path.join(WORK, "ace")
    os.makedirs(folder)
    out = os.path.join(WORK, "ace-out")
    log = os.path.join(WORK, "ace-runs.jsonl")
    fake = fakeace.install(os.path.join(WORK, "fake-ace"))

    def book(name, title):
        document = ('<?xml version="1.0" encoding="UTF-8"?><html xmlns="http://www.w3.org/1999/'
                    'xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en" xml:lang="en">'
                    f'<head><title>{title}</title></head><body><section epub:type="chapter">'
                    f"<h1>{title}</h1><p>Text.</p></section></body></html>")
        with zipfile.ZipFile(os.path.join(folder, name), "w") as archive:
            archive.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
            archive.writestr("META-INF/container.xml", (
                '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:'
                'opendocument:xmlns:container"><rootfiles><rootfile full-path="EPUB/p.opf" '
                'media-type="application/oebps-package+xml"/></rootfiles></container>'))
            archive.writestr("EPUB/p.opf", (
                '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
                'version="3.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
                f"<dc:title>{title}</dc:title><dc:language>en</dc:language></metadata>"
                '<manifest><item id="a" href="a.xhtml" media-type="application/xhtml+xml"/>'
                '</manifest><spine><itemref idref="a"/></spine></package>'))
            archive.writestr("EPUB/a.xhtml", document)
    book("one.epub", "One")
    book("two.epub", "Two")

    def runs():
        if not os.path.exists(log):
            return 0
        with open(log, encoding="utf-8") as fh:
            return sum(1 for line in fh if '"-o"' in line)

    def audit(*flags):
        before = runs()
        result = subprocess.run([sys.executable, os.path.join(BIN, "audit.py"), folder,
                                 "-o", out, *flags], cwd=WORK, capture_output=True, text=True,
                                stdin=subprocess.DEVNULL,
                                env=dict(os.environ, ACE=fake, FAKE_ACE_LOG=log))
        found = sorted((f.where, f.check, f.file, f.severity)
                       for f in fl.read_csv(os.path.join(out, "audit.csv")) if f.tool == "ace")
        with open(os.path.join(out, "audit.md"), encoding="utf-8") as fh:
            return result.stderr, found, fh.read(), runs() - before
    plain = audit()
    quick = audit("--wcag", "--quick")
    first = audit("--wcag")
    second = audit("--wcag")
    book("two.epub", "Two, again")
    changed = audit("--wcag")
    forced = audit("--wcag", "--force")
    with open(os.path.join(out, "audit-cache.json"), "rb") as fh:
        kept_bytes = fh.read()
    uncached = audit("--wcag", "--no-cache")
    with open(os.path.join(out, "audit-cache.json"), "rb") as fh:
        after_bytes = fh.read()
    expected = [("EPUB/a.xhtml", "ace:epub-type-has-matching-role", "one.epub", "note"),
                ("EPUB/a.xhtml", "ace:epub-type-has-matching-role", "two.epub", "note"),
                ("EPUB/p.opf", "ace:metadata-accessmode", "one.epub", "note"),
                ("EPUB/p.opf", "ace:metadata-accessmode", "two.epub", "note")]
    return [
        ("without --wcag, and with --quick, Ace doesn't run",
         lambda: plain[3] == 0 and quick[3] == 0 and "Ace's checks not run (--quick)." in quick[0]
         or fail("got: " + quick[0])),
        ("with --wcag it runs on each EPUB, its own findings notes filed under the EPUB, and the "
         "report has a section saying it ran",
         lambda: first[3] == 2 and first[1] == expected
         and "## EPUBs: DAISY's Ace" in first[2]
         and "- Ace by DAISY 1.4.6 checked 2 EPUB(s): 4 finding(s) of its own" in first[2]
         or fail("got: " + first[0])),
        ("the next audit keeps each unchanged EPUB's result, Ace not run, and says so",
         lambda: second[3] == 0 and second[1] == expected
         and "Ace by DAISY 1.4.6 checked no EPUB again: 4 finding(s) of its own on 2 EPUB(s)"
             in second[0]
         and "2 EPUB(s) weren't checked again: each is unchanged since the audit that checked "
             "it" in second[0] or fail("got: " + second[0])),
        ("an EPUB that has changed is checked again, and only it, and --force checks every one",
         lambda: changed[3] == 1 and "checked 1 EPUB(s)" in changed[0] and forced[3] == 2
         or fail("got: " + changed[0])),
        ("--no-cache runs it, and leaves the cache as it was",
         lambda: uncached[3] == 2 and after_bytes == kept_bytes),
    ]


# Text a file holds that is markup in Markdown: a heading's, and a PDF's
# title. Pandoc passes raw HTML through, and makes a link of [...](...)
# even without it, so the report wrote them into audit.html as markup.
HOSTILE = ('The <script>alert(1)</script> tag, <img src=x onerror="alert(2)">, '
           '[a link](javascript:alert(3)), $x$, \\frac{a}{b}, --verbose, IMG_2041, &lt;')


def case_report_text():
    import html as htmllib
    d = os.path.join(WORK, "hostile")
    out = os.path.join(d, "out")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "page.html"), "w", encoding="utf-8") as fh:
        fh.write('<!DOCTYPE html><html lang="en"><head><title>T</title></head>'
                 f'<body><h1>T</h1><h3>{htmllib.escape(HOSTILE)}</h3></body></html>\n')
    try:
        import pypdf
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.add_metadata({"/Title": '<img src=y onerror="alert(4)"> [t](javascript:alert(5))'})
        with open(os.path.join(d, "titled.pdf"), "wb") as fh:
            writer.write(fh)
        pdf = True
    except ImportError:
        pdf = False
    run([os.path.join(BIN, "audit.py"), d, "-o", out, "--quick", "--force",
         "--report-html", "--report-docx"], d)
    md = open(os.path.join(out, "audit.md"), encoding="utf-8").read()
    page = open(os.path.join(out, "audit.html"), encoding="utf-8").read()
    with zipfile.ZipFile(os.path.join(out, "audit.docx")) as z:
        body = z.read("word/document.xml").decode("utf-8")
        rels = z.read("word/_rels/document.xml.rels").decode("utf-8")
    words = re.sub(r"<[^>]+>", "", body)
    no_pdf = "no pypdf to write a PDF to audit (sudo apt install python3-pypdf)"
    return [
        ("a heading's markup is text in audit.md",
         lambda: "h1 to h3: The \\<script\\>alert(1)\\</script\\> tag" in md),
        ("and in audit.html: no script, no attribute of the page's, no javascript: link, "
         "no math",
         lambda: not re.search(r"<script", page, re.I)
         and not re.search(r"<[a-z][^>]*\bonerror\s*=", page, re.I)
         and not re.search(r"<a\b[^>]*javascript", page, re.I)
         and 'class="math' not in page),
        ("but its words as written, a backslash, two hyphens, an underscore, and an entity's "
         "text among them",
         lambda: htmllib.escape(HOSTILE, quote=False) in page.replace("\n", " ")),
        ("and in audit.docx, with no link to javascript:",
         lambda: HOSTILE in htmllib.unescape(words) and "javascript:" not in rels),
        ("a PDF's title is text too",
         lambda: "**Title:** \\<img src=y onerror=\"alert(4)\"\\> \\[t\\](javascript:alert(5))"
         in md and not re.search(r"<img[^>]*onerror", page)
         if pdf else print("  skip  " + no_pdf) or True),
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
    for name, data in (("up.png", b"up"), ("up-2.png", b"up"), ("down.png", b"down"),
                       ("sales.png", b"sales"), ("sales-3.png", b"other sales")):
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
                       ("the audit's own reports, in the folder it writes to",
                        case_own_reports),
                       ("a file's own text in the report", case_report_text),
                       ("veraPDF's WCAG checks, asked for", case_wcag),
                       ("axe-core's results, cached", case_axe_cache),
                       ("DAISY's Ace, asked for", case_ace),
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
