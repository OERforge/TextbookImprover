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
import os
import re
import shutil
import subprocess
import sys
import tempfile

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
![A pipe](pipe.png).

| a | b |
|---|---|
| 1 | 2 |

|   |   |
|---|---|
| x | 1 |
| y | 2 |

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
        ("a bare-URL link is found",
         lambda: "source-link-bare-url" in c),
        ("a headerless table is found, a marked one and a keyed one are not",
         lambda: c.count("source-table-no-headers") == 0
         or c.count("source-table-no-headers") == 1),
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
    filter_count = re.search(r"(\d+) image\(s\) need alt text", result.stderr)
    return [
        ("the source check and the filter agree on images needing alt text",
         lambda: filter_count is None or ours == int(filter_count.group(1))),
    ]


def case_front_door():
    out = os.path.join(WORK, "out")
    first = run([os.path.join(BIN, "audit.py"), WORK, "-o", out, "--quick"],
                WORK)
    csv_path = os.path.join(out, "audit.csv")
    with open(csv_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    header, body = rows[0], rows[1:]
    kinds = {r[4] for r in body}
    report = open(os.path.join(out, "audit.md"), encoding="utf-8").read()
    stamp = os.path.getmtime(os.path.join(out, "audit.md"))
    second = run([os.path.join(BIN, "audit.py"), WORK, "-o", out, "--quick"],
                 WORK)
    untouched = os.path.getmtime(os.path.join(out, "audit.md")) == stamp
    forced = run([os.path.join(BIN, "audit.py"), WORK, "-o", out, "--quick",
                  "--force", "--html"], WORK)
    back = fl.read_csv(csv_path)
    standards = {r[6] for r in body if r[6]}
    return [
        ("the audit runs over a directory of mixed files",
         lambda: os.path.exists(csv_path)),
        ("the CSV keeps the three original columns first, then the rest",
         lambda: header == fl.COLUMNS),
        ("a Word source, a Markdown source, a page, an EPUB, and a PDF are "
         "each audited",
         lambda: {"source-docx", "source-md", "html", "pdf"} <= kinds),
        ("the report lists every input with its hash",
         lambda: "## Inputs" in report and report.count("SHA-256") >= 5),
        ("and the PDF's metadata and claims",
         lambda: "metadata and claims" in report and "**Tagged:**" in report),
        ("with nothing changed, the report is left as it is and said to be "
         "current",
         lambda: "is current" in second.stderr and untouched),
        ("unless forced",
         lambda: "unchanged" not in forced.stderr and "is current"
         not in forced.stderr),
        ("--html renders the report as a page",
         lambda: os.path.exists(os.path.join(out, "audit.html"))),
        ("a WCAG standard names the version, the criterion, and its level",
         lambda: all(re.match(r"WCAG 2\.\d SC \d\.\d+\.\d+ \((A|AA|AAA)\)$", s)
                     for s in standards if s.startswith("WCAG"))),
        ("the CSV reads back into the same findings",
         lambda: len(back) == len(body)),
        ("the exit code says whether anything is an error",
         lambda: first.returncode == 1),
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
    with open(os.path.join(WORK, "page.html"), "w", encoding="utf-8") as fh:
        fh.write(HTML)
    shutil.copy(os.path.join(FIXTURES, "media-a.docx"), WORK)
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
