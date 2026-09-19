#!/usr/bin/env python3
"""
run-check-tests.py -- check the output checker.

    python3 tests/run-check-tests.py

Each check is exercised by a page that breaks it and, where it matters,
one that does not: the checker's job is to find what is wrong, and a
finding on a correct page is as bad as silence on a wrong one. The EPUB
half builds a small book with Pandoc and breaks a link inside the
archive by hand, since the assembler would not write one.

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

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))
import outputcheck  # noqa: E402

GOOD = """<!DOCTYPE html><html lang="en"><head><title>A page</title></head>
<body><h1 id="top">Top</h1><h2>Second</h2>
<img src="x.png" alt="A thing"><img src="y.png" alt="" role="presentation">
<table><caption>Data</caption><tr><th scope="col">H</th></tr></table>
<table role="presentation"><tr><td>layout</td></tr></table>
<a href="#top">up</a><a href="other.html#there">over</a>
<a href="https://example.org/#x">out</a></body></html>"""

OTHER = """<!DOCTYPE html><html lang="en"><head><title>Other</title></head>
<body><h1 id="there">There</h1></body></html>"""

BAD = """<!DOCTYPE html><html><head><title></title></head>
<body><h1 id="a">A</h1><h3 id="a">Skipped</h3><h2></h2>
<img src="p.png"><img src="q.png" alt="">
<table><tr><td>1</td></tr></table>
<a href="#nowhere">x</a><a href="gone.html">y</a><a href="other.html#no">z</a>
</body></html>"""


def checks(findings):
    return sorted(f.check for f in findings)


def main():
    work = tempfile.mkdtemp(prefix="check-tests-")
    failed = 0
    try:
        for name, markup in (("good.html", GOOD), ("other.html", OTHER),
                             ("bad.html", BAD)):
            with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
                fh.write(markup)
        good = outputcheck.check_html_files(
            [os.path.join(work, "good.html"), os.path.join(work, "other.html")])
        bad = outputcheck.check_html_files(
            [os.path.join(work, "bad.html"), os.path.join(work, "other.html")])
        cases = [
            ("a correct pair of pages produces no finding",
             lambda: checks(good) == []),
            ("every check fires on the page that breaks it",
             lambda: checks(bad) == sorted([
                 "no-lang", "no-title", "duplicate-id", "heading-skips-level",
                 "empty-heading", "image-without-alt",
                 "image-empty-alt-not-decorative",
                 "table-without-headers-or-caption",
                 "link-to-missing-fragment", "link-to-missing-file",
                 "link-to-missing-fragment"])),
            ("a finding says where and what",
             lambda: any(f.where == "bad.html" and f.detail == "gone.html"
                         for f in bad)),
        ]
        if shutil.which("pandoc"):
            with open(os.path.join(work, "b.md"), "w", encoding="utf-8") as fh:
                fh.write("---\ntitle: B\nlang: en\n---\n\n# One\n\n"
                         "See [two](#two).\n\n# Two {#two}\n\ntext\n")
            epub = os.path.join(work, "b.epub")
            subprocess.run(["pandoc", "b.md", "-t", "epub3", "-o", epub],
                           cwd=work, check=True)
            clean = outputcheck.check_epub(epub)
            # Break the link inside the archive.
            broken = os.path.join(work, "broken.epub")
            with zipfile.ZipFile(epub) as src, \
                    zipfile.ZipFile(broken, "w") as dst:
                for info in src.infolist():
                    data = src.read(info.filename)
                    if info.filename.endswith("ch001.xhtml"):
                        data = data.replace(b"#two", b"#gone")
                    dst.writestr(info, data)
            damaged = outputcheck.check_epub(broken)
            cases += [
                ("a Pandoc EPUB passes apart from its known omissions",
                 lambda: set(checks(clean)) <= {"no-accessibility-metadata"}
                 or checks(clean) == []),
                ("a fragment broken inside the archive is found",
                 lambda: "link-to-missing-fragment" in checks(damaged)),
                ("the EPUB's own structure is read: manifest, spine, nav",
                 lambda: not any(c.startswith(("manifest", "spine", "no-nav",
                                               "file-not", "mimetype"))
                                 for c in checks(damaged))),
            ]
        for label, predicate in cases:
            try:
                ok = predicate()
            except Exception as exc:
                ok, label = False, f"{label}  ({exc})"
            print(("  ok    " if ok else "  FAIL  ") + label)
            failed += not ok
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"\n{failed} check(s) failed" if failed else "\nall output checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
