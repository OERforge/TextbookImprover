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


def case_renamed():
    """The cache keeps a file's findings by where it is: one renamed is
    read again and named by its new name, and the audit doesn't take the
    report for current; a copy is read as a file of its own; one made
    again replaces its entry; and an entry as audits kept them before, by
    a SHA-256 alone, is dropped, as one that isn't what an audit wrote is
    passed over."""
    audit = os.path.join(BIN, "audit.py")
    d = os.path.join(WORK, "renamed")
    os.makedirs(d)
    with open(os.path.join(d, "draft.html"), "w", encoding="utf-8") as fh:
        fh.write(HTML)

    def files():
        return sorted(f.file for f in fl.read_csv(os.path.join(d, "audit.csv")))

    def cache():
        with open(os.path.join(d, "audit-cache.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def save(data):
        with open(os.path.join(d, "audit-cache.json"), "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    run([audit, d, "--quick"], d)
    os.rename(os.path.join(d, "draft.html"), os.path.join(d, "final.html"))
    renamed = run([audit, d, "--quick"], d)
    renamed_files = files()
    with open(os.path.join(d, "audit.md"), encoding="utf-8") as fh:
        report = fh.read()
    shutil.copy(os.path.join(d, "final.html"), os.path.join(d, "copy.html"))
    copied = run([audit, d, "--quick"], d)
    copied_files = files()

    def entries():
        return sorted(key for key in cache() if not key.startswith("__"))
    before = entries()
    with open(os.path.join(d, "final.html"), "w", encoding="utf-8") as fh:
        fh.write(HTML.replace("</body>", '<img src="q.png"></body>'))
    rebuilt = run([audit, d, "--quick"], d)
    after = entries()
    data = cache()
    sha = fl.digest(os.path.join(d, "copy.html"))
    data[sha] = {"findings": [["copy.html", "image-without-alt", "p.png", "copy.html", "html"]],
                 "options": {"quick": True}, "when": "2026-01-01T00:00:00+00:00"}
    save(data)
    old = run([audit, d, "--quick", "--force"], d)
    dropped = sha not in cache()
    data = cache()
    data[os.path.realpath(os.path.join(d, "copy.html"))]["findings"] = "not findings"
    data[os.path.realpath(os.path.join(d, "final.html"))] = "not an entry"
    save(data)
    broken = run([audit, d, "--quick"], d)
    return [
        ("a file renamed is read again, named by its new name, and the report isn't taken for "
         "current",
         lambda: "unchanged" not in renamed.stderr and "is current" not in renamed.stderr
         and renamed_files == ["final.html"] and "draft.html" not in report
         or fail("got: " + renamed.stderr)),
        ("a copy is read as a file of its own, each finding filed under its own file",
         lambda: "copy.html: 1 finding(s)" in copied.stderr
         and copied_files == ["copy.html", "final.html"] or fail("got: " + copied.stderr)),
        ("a file made again replaces its entry, by where it is",
         lambda: "final.html: 2 finding(s)" in rebuilt.stderr and after == before
         and os.path.realpath(os.path.join(d, "final.html")) in after
         or fail(repr(after))),
        ("an entry by a SHA-256 alone, as audits kept them before, is dropped",
         lambda: dropped and old.returncode == 1 or fail("got: " + old.stderr)),
        ("and an entry that isn't what an audit wrote has its file read again",
         lambda: "Traceback" not in broken.stderr and "copy.html: 1 finding(s)" in broken.stderr
         and "final.html: 2 finding(s)" in broken.stderr or fail("got: " + broken.stderr)),
    ]


def case_wcag():
    """--wcag, with a stand-in for veraPDF: a note for each rule of the
    WCAG profile a PDF fails, counting its failed checks, and with
    --verbose one for each failed check, an item in the report under its
    rule's, notes that leave the exit status the other findings', a
    section of the report saying the checks ran and may be wrong, a run
    with --wcag never taking the report for current, since what it finds
    turns on what's installed too, a report made with other
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


def case_verapdf_cache():
    """veraPDF's WCAG findings on each PDF kept in the cache, with the
    stand-in for veraPDF: the next audit gives an unchanged PDF no run of
    the profile, has the first's findings, and says so, veraPDF asked
    once which it is; another level and --verbose read what was kept; a
    PDF changed is checked again, and only it, its entry replacing its
    last; a part that isn't what the audit wrote is started again; one
    renamed is named by its new name; a changed folder of modules,
    --force, each setting veraPDF's run turns on, and another veraPDF
    check every PDF again; a PDF written again as veraPDF read it, a run
    with a warning, a veraPDF that doesn't say which it is, and a folder
    with a file that can't be read keep nothing; and --no-cache leaves
    the cache as it was."""
    sys.path.insert(0, HERE)
    import fakeverapdf
    import pdfcheck
    try:
        import pypdf
    except ImportError:
        print("  skip  pypdf not installed; veraPDF's WCAG checks aren't asked of a PDF")
        return []
    folder = os.path.join(WORK, "vcache")
    out = os.path.join(WORK, "vcache-out")
    os.makedirs(folder)
    probe = os.path.join(WORK, "vcache-probe.pdf")
    with open(probe, "wb") as fh:
        fh.write(pdfcheck.wcag_probe())

    def pdf(name, title):
        writer = pypdf.PdfWriter(clone_from=probe)
        writer.add_metadata({"/Title": title})
        with open(os.path.join(folder, name), "wb") as fh:
            writer.write(fh)
    pdf("book.pdf", "A Book")
    pdf("other.pdf", "Another")
    log = os.path.join(WORK, "vcache-log.jsonl")
    modules = fakeverapdf.modules(os.path.join(WORK, "vcache-modules"))
    env = dict(os.environ, VERAPDF=fakeverapdf.install(os.path.join(WORK, "vcache-fake")),
               VERAPDF_WCAG=modules, FAKE_VERAPDF_LOG=log)

    def audit(*flags, program=os.path.join(BIN, "audit.py"), **more):
        open(log, "w").close()
        result = subprocess.run([sys.executable, program, folder,
                                 "-o", out, *flags], cwd=WORK, capture_output=True,
                                text=True, stdin=subprocess.DEVNULL, env=dict(env, **more))
        with open(log, encoding="utf-8") as fh:
            runs = [json.loads(line)["args"] for line in fh if line.strip()]
        checked = sorted(os.path.basename(arg) for args in runs if "-p" in args
                         for arg in args if arg.endswith(".pdf")
                         and os.path.basename(arg) != "wcag-probe.pdf")
        wcag = sorted((f.where, f.check, f.detail) for f in fl.read_csv(
            os.path.join(out, "audit.csv")) if f.check.startswith("verapdf-wcag:"))
        with open(os.path.join(out, "audit.md"), encoding="utf-8") as fh:
            report = fh.read()
        return {"result": result, "checked": checked, "wcag": wcag, "report": report,
                "asked": sum("--version" in args for args in runs)}
    first = audit("--wcag")
    second = audit("--wcag")
    aaa = audit("--wcag", "--wcag-level", "AAA")
    loud = audit("--wcag", "--verbose")
    pdf("other.pdf", "Another, changed")
    changed = audit("--wcag")
    cache_file = os.path.join(out, "audit-cache.json")

    def part():
        with open(cache_file, encoding="utf-8") as fh:
            return json.load(fh)["__verapdf-wcag__"]
    entries = len(part()["pdfs"])
    with open(cache_file, encoding="utf-8") as fh:
        broken = json.load(fh)
    broken["__verapdf-wcag__"]["pdfs"] = None
    with open(cache_file, "w", encoding="utf-8") as fh:
        json.dump(broken, fh)
    unbroken = audit("--wcag")
    unbroken_entries = len(part()["pdfs"])
    os.rename(os.path.join(folder, "book.pdf"), os.path.join(folder, "renamed.pdf"))
    renamed = audit("--wcag")
    open(os.path.join(modules, "extra-1.0.jar"), "w").close()
    remodeled = audit("--wcag")
    with open(os.path.join(modules, "WCAG-2-2-Machine.xml"), "a", encoding="utf-8") as fh:
        fh.write("<!-- edited -->\n")
    reprofiled = audit("--wcag")
    forced = audit("--wcag", "--force")
    # Each setting in turn, the ones before it kept: every PDF checked
    # again shows that one is in the key.
    settings, java = {}, os.path.join(WORK, "vcache-java")
    os.makedirs(java)
    with open(os.path.join(java, "java"), "w", encoding="utf-8") as fh:
        fh.write("#!/bin/sh\nexit 1\n")
    os.chmod(os.path.join(java, "java"), 0o755)
    shutil.copytree(modules, os.path.join(WORK, "vcache-modules-2"))
    second_fake = fakeverapdf.install(os.path.join(WORK, "vcache-fake-2"))
    steps = []
    for name, value in (("CLASSPATH_PREFIX", os.path.join(WORK, "nowhere", "*")),
                        ("JAVACMD", os.path.join(java, "java")),
                        ("JAVA_HOME", os.path.join(WORK, "no-java")),
                        ("JAVA_OPTS", "-Xmx512m"),
                        ("JAVA_TOOL_OPTIONS", "-Dfile.encoding=UTF-8"),
                        ("JDK_JAVA_OPTIONS", "-Duser.language=en"),
                        ("PATH", java + os.pathsep + os.environ.get("PATH", "")),
                        ("VERAPDF", second_fake),
                        ("VERAPDF_WCAG", os.path.join(WORK, "vcache-modules-2"))):
        settings[name] = value
        steps.append((name, audit("--wcag", **settings)["checked"]))
    with open(second_fake, "a", encoding="utf-8") as fh:
        fh.write("# edited\n")
    steps.append(("the launcher edited", audit("--wcag", **settings)["checked"]))
    code = os.path.join(WORK, "vcache-code")
    for name in ("bin", "lib"):
        shutil.copytree(os.path.join(ROOT, name), os.path.join(code, name))
    with open(os.path.join(code, "lib", "pdfcheck.py"), "a", encoding="utf-8") as fh:
        fh.write("# edited\n")
    steps.append(("pdfcheck.py edited", audit("--wcag", program=os.path.join(
        code, "bin", "audit.py"), **settings)["checked"]))
    steps.append(("all of them again", audit("--wcag", program=os.path.join(
        code, "bin", "audit.py"), **settings)["checked"]))
    # A PDF a build writes again as veraPDF reads it: what veraPDF found
    # isn't kept for the bytes it had before.
    open(os.path.join(modules, "extra-1.5.jar"), "w").close()
    saved = {name: open(os.path.join(folder, name), "rb").read()
             for name in ("other.pdf", "renamed.pdf")}
    rewritten = audit("--wcag", FAKE_VERAPDF_REWRITE="1")
    for name, data in saved.items():
        with open(os.path.join(folder, name), "wb") as fh:
            fh.write(data)
    after_rewritten = audit("--wcag")
    upgraded = audit("--wcag", FAKE_VERAPDF_VERSION="1.30.4")
    # Each of these after a file more in the folder, so the cache has
    # nothing for the setup, and what the run keeps is all there is.
    open(os.path.join(modules, "extra-2.0.jar"), "w").close()
    garbled = audit("--wcag", FAKE_VERAPDF_GARBLED="1")
    after_garbled = audit("--wcag")
    open(os.path.join(modules, "extra-3.0.jar"), "w").close()
    error = 'Exception in thread "main" java.lang.IllegalStateException: a check undone\n'
    erred = audit("--wcag", FAKE_VERAPDF_STDERR=error)
    after_erred = audit("--wcag")
    unsaid = [audit("--wcag", FAKE_VERAPDF_NO_VERSION="1") for _ in range(2)]
    # A file in the folder that can't be read: no key, so nothing kept.
    pdfcheck._SAID[(fakeverapdf.install(os.path.join(WORK, "vcache-fake-3")),)] = "veraPDF 1.30.3"
    held_digest = pdfcheck.digest

    def unreadable(path):
        raise PermissionError(13, "Permission denied", path)
    pdfcheck.digest = unreadable
    try:
        no_key = pdfcheck.wcag_setup([os.path.join(WORK, "vcache-fake-3", "verapdf")], modules)
    finally:
        pdfcheck.digest = held_digest
    with open(cache_file, encoding="utf-8") as fh:
        kept = fh.read()
    uncached = audit("--wcag", "--no-cache")
    with open(cache_file, encoding="utf-8") as fh:
        kept_after = fh.read()
    both = ["book.pdf", "other.pdf"]
    held = "1 PDF(s) weren't checked again: each is unchanged since the audit that checked it ("
    return [
        ("the first audit runs the profile on each PDF, a note for its rule within WCAG 2.1 "
         "AA",
         lambda: first["checked"] == both and [w[:2] for w in first["wcag"]] == [
             ("book.pdf", "verapdf-wcag:1.3.1-1"), ("other.pdf", "verapdf-wcag:1.3.1-1")]),
        ("the second runs it on neither, its findings the first's, saying each PDF wasn't "
         "checked again, and asks veraPDF once which it is",
         lambda: second["checked"] == [] and second["wcag"] == first["wcag"]
         and second["result"].stderr.count(held) == 2
         and second["result"].stderr.count("WCAG 2.2 machine checks ran on no PDF again") == 2
         and second["asked"] == 1 and held in second["report"]),
        ("at AAA, the rule beyond AA is a note too, from what was kept, veraPDF not run",
         lambda: aaa["checked"] == [] and [w[:2] for w in aaa["wcag"]] == [
             ("book.pdf", "verapdf-wcag:1.3.1-1"), ("book.pdf", "verapdf-wcag:2.4.9-1"),
             ("other.pdf", "verapdf-wcag:1.3.1-1"), ("other.pdf", "verapdf-wcag:2.4.9-1")]),
        ("with --verbose, each failed check a note at its page, from what was kept",
         lambda: loud["checked"] == [] and [w[:2] for w in loud["wcag"]] == [
             ("book.pdf#page=653", "verapdf-wcag:1.3.1-1"),
             ("other.pdf#page=653", "verapdf-wcag:1.3.1-1")]),
        ("a PDF changed is checked again, and only it, its entry in the cache replacing the "
         "last, by where the PDF is",
         lambda: changed["checked"] == ["other.pdf"] and entries == 2),
        ("a part of the cache that isn't what the audit wrote is started again",
         lambda: "Traceback" not in unbroken["result"].stderr
         and unbroken["checked"] == ["book.pdf", "other.pdf"] and unbroken_entries == 2),
        ("one renamed isn't, and its findings have its new name",
         lambda: renamed["checked"] == [] and [w[:2] for w in renamed["wcag"]] == [
             ("other.pdf", "verapdf-wcag:1.3.1-1"), ("renamed.pdf", "verapdf-wcag:1.3.1-1")]
         and "book.pdf" not in renamed["report"]),
        ("a file more in the modules' folder has every PDF checked again, and so does a "
         "profile edited there",
         lambda: remodeled["checked"] == ["other.pdf", "renamed.pdf"]
         and reprofiled["checked"] == ["other.pdf", "renamed.pdf"]),
        ("and so does --force",
         lambda: forced["checked"] == ["other.pdf", "renamed.pdf"]),
        ("and CLASSPATH_PREFIX, each setting the Java veraPDF runs turns on, the java on the "
         "path, another launcher, the modules' folder at another place, the launcher edited, "
         "and pdfcheck.py edited, each in turn, all of them the same after",
         lambda: steps == [(name, ["other.pdf", "renamed.pdf"]) for name, _ in steps[:-1]]
         + [("all of them again", [])] and len(steps) == 12
         or fail(repr(steps))),
        ("a PDF written again as veraPDF read it isn't kept for the bytes it had",
         lambda: rewritten["checked"] == ["other.pdf", "renamed.pdf"]
         and after_rewritten["checked"] == ["other.pdf", "renamed.pdf"]),
        ("and another veraPDF, which the summary names",
         lambda: upgraded["checked"] == ["other.pdf", "renamed.pdf"]
         and "veraPDF 1.30.4's WCAG 2.2 machine checks ran on 1 PDF(s)"
         in upgraded["result"].stderr),
        ("a run that veraPDF didn't report on keeps nothing, so the next checks every PDF",
         lambda: "veraPDF didn't report on" in garbled["result"].stderr
         and after_garbled["checked"] == ["other.pdf", "renamed.pdf"]),
        ("nor does one with an error veraPDF wrote as it checked",
         lambda: "veraPDF wrote an error as it checked" in erred["result"].stderr
         and erred["checked"] == ["other.pdf", "renamed.pdf"]
         and after_erred["checked"] == ["other.pdf", "renamed.pdf"]),
        ("a veraPDF that doesn't say which it is has nothing kept, nor read from the cache",
         lambda: [u["checked"] for u in unsaid] == [["other.pdf", "renamed.pdf"]] * 2),
        ("nor does a folder holding a file that can't be read",
         lambda: no_key is None),
        ("--no-cache checks every PDF and leaves the cache as it was",
         lambda: uncached["checked"] == ["other.pdf", "renamed.pdf"] and kept_after == kept),
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
    or with --force; a part of the cache that isn't what the audit wrote
    is started again; with --no-cache, every page, the cache untouched."""
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

    def broken(change):
        """An audit after the cache's part for axe-core is changed so."""
        cache_file = os.path.join(out, "audit-cache.json")
        with open(cache_file, encoding="utf-8") as fh:
            data = json.load(fh)
        change(data["__axe__"])
        with open(cache_file, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return audit("--best-practice")[0]
    no_items = broken(lambda part: part.update(items=None))
    no_ready = broken(lambda part: part.update(ready="not a report"))
    one_entry = broken(lambda part: part["items"].update(
        {next(key for key in part["items"] if "two.html" in key): "not an entry"}))
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
        ("a part of the cache that isn't what the audit wrote, or its kept setup, is "
         "started again, and an entry that isn't one has its page checked again",
         lambda: "Traceback" not in no_items + no_ready + one_entry
         and f"its best practices on {everything}," in no_items
         and f"its best practices on {everything}," in no_ready
         and "its best practices on 1 page(s)," in one_entry
         or fail("got: " + no_items + no_ready + one_entry)),
        ("--no-cache checks every page, and leaves the cache as it was",
         lambda: f"its best practices on {everything}," in uncached
         and after_bytes == kept_bytes or fail("got: " + uncached)),
    ]


def case_ace():
    """--wcag runs DAISY's Ace on each EPUB, a stand-in here
    (tests/fakeace.py): its own findings notes, filed under the EPUB, a
    section of the report saying it ran; the next audit keeps each
    unchanged EPUB's result, Ace not run, and runs it again on an EPUB
    that has changed, its entry replacing its last, and on every one
    with --force; a part of the cache that isn't what the audit wrote is
    started again; --no-cache runs it and leaves the cache alone; an
    EPUB renamed isn't checked again, and has its new name; another Ace
    checks every EPUB again; an Ace that doesn't say its version, and an
    EPUB written again as Ace read it, have nothing kept; --quick and no
    --wcag don't run it."""
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

    def audit(*flags, **more):
        before = runs()
        result = subprocess.run([sys.executable, os.path.join(BIN, "audit.py"), folder,
                                 "-o", out, *flags], cwd=WORK, capture_output=True, text=True,
                                stdin=subprocess.DEVNULL,
                                env=dict(os.environ, ACE=fake, FAKE_ACE_LOG=log, **more))
        found = sorted((f.where, f.check, f.file, f.severity)
                       for f in fl.read_csv(os.path.join(out, "audit.csv")) if f.tool == "ace")
        with open(os.path.join(out, "audit.md"), encoding="utf-8") as fh:
            return result.stderr, found, fh.read(), runs() - before

    def part():
        with open(os.path.join(out, "audit-cache.json"), encoding="utf-8") as fh:
            return json.load(fh)["__ace__"]
    plain = audit()
    quick = audit("--wcag", "--quick")
    first = audit("--wcag")
    second = audit("--wcag")
    book("two.epub", "Two, again")
    changed = audit("--wcag")
    entries = sorted(os.path.basename(key) for key in part()["epubs"])
    forced = audit("--wcag", "--force")

    def broken(change):
        """An audit after the cache's part for Ace is changed so."""
        cache_file = os.path.join(out, "audit-cache.json")
        with open(cache_file, encoding="utf-8") as fh:
            data = json.load(fh)
        change(data["__ace__"])
        with open(cache_file, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return audit("--wcag")
    no_epubs = broken(lambda part: part.update(epubs=None))
    one_entry = broken(lambda part: part["epubs"].update(
        {next(iter(sorted(part["epubs"]))): "not an entry"}))
    # An entry as the audit wrote one before it kept the EPUB's SHA-256,
    # and one whose result isn't one.
    no_sha = broken(lambda part: part["epubs"].update(
        {key: {"result": entry["result"], "when": entry["when"]}
         for key, entry in sorted(part["epubs"].items())[:1]}))
    no_result = broken(lambda part: [entry.update(result="not a result")
                                     for _, entry in sorted(part["epubs"].items())[:1]])
    with open(os.path.join(out, "audit-cache.json"), "rb") as fh:
        kept_bytes = fh.read()
    uncached = audit("--wcag", "--no-cache")
    with open(os.path.join(out, "audit-cache.json"), "rb") as fh:
        after_bytes = fh.read()
    os.rename(os.path.join(folder, "one.epub"), os.path.join(folder, "renamed.epub"))
    renamed = audit("--wcag")
    upgraded = [audit("--wcag", FAKE_ACE_VERSION="1.4.7") for _ in range(2)]
    unsaid = [audit("--wcag", FAKE_ACE_NO_VERSION="1") for _ in range(2)]
    # A build that writes an EPUB again as Ace reads it: what Ace found
    # isn't kept for the bytes it had before. Another Ace first, so the
    # cache has nothing for the setup, and what the run keeps is all there is.
    saved = {name: open(os.path.join(folder, name), "rb").read()
             for name in ("renamed.epub", "two.epub")}
    rewritten = audit("--wcag", FAKE_ACE_VERSION="1.4.8", FAKE_ACE_REWRITE="1")
    for name, data in saved.items():
        with open(os.path.join(folder, name), "wb") as fh:
            fh.write(data)
    after_rewritten = audit("--wcag", FAKE_ACE_VERSION="1.4.8")
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
        ("its entry in the cache replaces its last, by where the EPUB is",
         lambda: entries == ["one.epub", "two.epub"] or fail(repr(entries))),
        ("a part of the cache that isn't what the audit wrote is started again, and an entry "
         "that isn't one has its EPUB checked again, and said to be",
         lambda: "Traceback" not in no_epubs[0] + one_entry[0] and no_epubs[3] == 2
         and one_entry[3] == 1 and no_epubs[1] == one_entry[1] == expected
         and "checked 1 EPUB(s)" in one_entry[0]
         and "1 EPUB(s) weren't checked again" in one_entry[0]
         or fail("got: " + no_epubs[0] + one_entry[0])),
        ("and so does one without the EPUB's SHA-256, or whose result isn't one",
         lambda: "Traceback" not in no_sha[0] + no_result[0] and no_sha[3] == no_result[3] == 1
         and no_sha[1] == no_result[1] == expected or fail("got: " + no_sha[0] + no_result[0])),
        ("--no-cache runs it, and leaves the cache as it was",
         lambda: uncached[3] == 2 and after_bytes == kept_bytes),
        ("an EPUB renamed isn't checked again, and its findings have its new name",
         lambda: renamed[3] == 0 and [f[2] for f in renamed[1]] == [
             "renamed.epub", "two.epub", "renamed.epub", "two.epub"]
         and "one.epub" not in renamed[2] or fail("got: " + renamed[0])),
        ("another Ace checks every EPUB again, and keeps what it found",
         lambda: [u[3] for u in upgraded] == [2, 0]
         and "Ace by DAISY 1.4.7 checked 2 EPUB(s)" in upgraded[0][0]
         or fail("got: " + upgraded[0][0])),
        ("an Ace that doesn't say its version has nothing kept, nor read from the cache",
         lambda: [u[3] for u in unsaid] == [2, 2] or fail("got: " + unsaid[1][0])),
        ("nor is an EPUB written again as Ace read it kept for the bytes it had",
         lambda: rewritten[3] == 2 and after_rewritten[3] == 2
         or fail("got: " + after_rewritten[0])),
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
                       ("a file renamed, copied, or made again", case_renamed),
                       ("a file's own text in the report", case_report_text),
                       ("veraPDF's WCAG checks, asked for", case_wcag),
                       ("veraPDF's WCAG findings, cached", case_verapdf_cache),
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
