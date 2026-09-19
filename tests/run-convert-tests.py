#!/usr/bin/env python3
"""
run-convert-tests.py -- check convert.py, the driver, on the fixtures.

    python3 tests/run-convert-tests.py

Needs Pandoc 3.9 or later. Each case is a directory of the fixture
documents with a configuration, run through convert.py, and read back:
that a bare directory converts beside the sources as it always has, that
several targets each land in their own directory, that two targets whose
filter settings agree share one intermediate and two whose settings
differ do not, that a target away from the sources gets its media, and
that the reports are written once per book.

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
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin")
FIXTURES = os.path.join(HERE, "fixtures")
NEEDED = ["metadata", "tables", "tables-b", "media-a", "math"]

MULTI = """\
targets:
  html:
    format: html
    output_dir: .
  print:
    format: html
    footer: "Printed edition."
  wide:
    format: html
    tables:
      wrap: false
  epub:
    format: epub3
"""


def convert(work, config=None, project=True, arguments=()):
    os.makedirs(work, exist_ok=True)
    for name in NEEDED:
        shutil.copy(os.path.join(FIXTURES, name + ".docx"), work)
    if config is not None:
        with open(os.path.join(work, "conversion.yaml"), "w",
                  encoding="utf-8") as fh:
            fh.write(config)
    if project:
        with open(os.path.join(work, "project.yaml"), "w",
                  encoding="utf-8") as fh:
            fh.write("project:\n  identifier: org.example.fixtures\n"
                     "  title: The Fixture Book\n")
    return subprocess.run(
        ["python3", os.path.join(BIN, "convert.py"), "--quiet"]
        + list(arguments), cwd=work, capture_output=True, text=True,
        stdin=subprocess.DEVNULL)


def exists(*parts):
    return os.path.exists(os.path.join(*parts))


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


def case_bare(work):
    """No configuration at all: one page per document, in html/."""
    result = convert(work, config=None, project=False)
    return [
        ("a bare directory converts into html/",
         lambda: all(exists(work, "html", n + ".html") for n in NEEDED)
         and not exists(work, "tables.html")),
        ("and stops at the packager's sample, as a first run does",
         lambda: result.returncode != 0
         and exists(work, "packaging-sample.yaml")),
        ("the intermediates and the reports sit beside the sources",
         lambda: exists(work, "tables.filtered.json")
         and exists(work, "image-alt-missing.csv")
         and exists(work, "table-headers-new.csv")
         and not exists(work, "html", "image-alt-missing.csv")),
        ("the media go with the pages",
         lambda: exists(work, "html", "media-a", "media", "image1.png")),
    ]


HAND = """<!DOCTYPE html><html lang="en"><head><title>Front Matter</title>
<link rel="stylesheet" href="front/style.css"></head>
<body><h1>Front Matter</h1><p>By hand. <img src="front/logo.png" alt="Logo"></p>
</body></html>
"""


def case_hand_written(work):
    """A page the author wrote is copied, not rendered, and is in every
    output."""
    os.makedirs(os.path.join(work, "front"), exist_ok=True)
    with open(os.path.join(work, "frontmatter.html"), "w",
              encoding="utf-8") as fh:
        fh.write(HAND)
    with open(os.path.join(work, "front", "style.css"), "w") as fh:
        fh.write("body {}\n")
    shutil.copy(os.path.join(FIXTURES, "media-a.docx"),
                os.path.join(work, "front", "logo.png"))   # any bytes
    result = convert(work, "targets:\n  html:\n    format: html\n"
                           "  epub:\n    format: epub3\n",
                     arguments=["--zip"])
    import zipfile
    names = []
    if exists(work, "org.example.fixtures.imscc"):
        with zipfile.ZipFile(os.path.join(work, "org.example.fixtures.imscc")) as z:
            names = z.namelist()
    nav = ""
    if exists(work, "epub", "org.example.fixtures.epub"):
        with zipfile.ZipFile(os.path.join(work, "epub",
                                          "org.example.fixtures.epub")) as z:
            nav = z.read("EPUB/nav.xhtml").decode("utf-8")
    return [
        ("the run succeeds", lambda: result.returncode == 0),
        ("the page is copied into the html target byte for byte",
         lambda: read(work, "html", "frontmatter.html") == HAND),
        ("with the files it refers to",
         lambda: exists(work, "html", "front", "style.css")
         and exists(work, "html", "front", "logo.png")),
        ("it is in the EPUB",
         lambda: "Front Matter" in nav),
        ("and in the cartridge, with its files",
         lambda: any(n.endswith("/frontmatter.html") for n in names)
         and any(n.endswith("/front/style.css") for n in names)),
        ("and the output check looked at it",
         lambda: "Output check: 6 page(s)" in result.stderr),
    ]


def case_targets(work):
    """Four targets: three HTML renderings and an EPUB."""
    result = convert(work, MULTI)
    return [
        ("the run succeeds", lambda: result.returncode == 0),
        ("the html target writes beside the sources when told to",
         lambda: exists(work, "tables.html")),
        ("a second html target writes into its own directory",
         lambda: exists(work, "print", "tables.html")),
        ("with its footer",
         lambda: "Printed edition." in read(work, "print", "tables.html")
         and "Printed edition." not in read(work, "tables.html")),
        ("and its media beside its pages",
         lambda: exists(work, "print", "media-a", "media", "image1.png")),
        ("a target whose filter settings agree shares the intermediate",
         lambda: not exists(work, "print", "intermediates")),
        ("a target whose filter settings differ gets its own",
         lambda: exists(work, "wide", "intermediates",
                        "tables.filtered.json")
         and "table-wrapper" not in read(work, "wide", "intermediates",
                                         "tables.filtered.json")),
        ("and its pages come from it",
         lambda: 'class="table-wrapper"' not in read(work, "wide",
                                                     "tables.html")
         and 'class="table-wrapper"' in read(work, "tables.html")),
        ("the epub target builds",
         lambda: exists(work, "epub", "org.example.fixtures.epub")),
        ("the reports are written once, for the book",
         lambda: exists(work, "image-alt-missing.csv")
         and not exists(work, "print", "image-alt-missing.csv")),
        ("the output check covers every target's pages",
         lambda: re.search(r"Output check: 15 page\(s\) and 1 EPUB",
                           result.stderr)),
        ("the packager packages the target beside the sources",
         lambda: exists(work, "imsmanifest.xml")),
    ]


def case_passthrough(work):
    """Arguments the driver does not know go to the packager."""
    result = convert(work, MULTI, arguments=["--zip"])
    return [
        ("--zip reaches the packager",
         lambda: result.returncode == 0
         and exists(work, "org.example.fixtures.imscc")),
    ]


def case_wrapper(work):
    """convert.sh runs convert.py for one release."""
    os.makedirs(work, exist_ok=True)
    for name in NEEDED:
        shutil.copy(os.path.join(FIXTURES, name + ".docx"), work)
    result = subprocess.run(["bash", os.path.join(BIN, "convert.sh"),
                             "--quiet"], cwd=work, capture_output=True,
                            text=True, stdin=subprocess.DEVNULL)
    return [
        ("the wrapper converts the directory",
         lambda: exists(work, "html", "tables.html")),
        ("and passes its arguments on",
         lambda: "+ " not in result.stderr),
    ]


CASES = [
    ("a bare directory", case_bare),
    ("a hand-written page", case_hand_written),
    ("several targets", case_targets),
    ("arguments passed to the packager", case_passthrough),
    ("the convert.sh wrapper", case_wrapper),
]


def main():
    if shutil.which("pandoc") is None:
        sys.exit("pandoc is not on the path.")
    work = tempfile.mkdtemp(prefix="convert-tests-")
    failed = 0
    try:
        for label, case in CASES:
            directory = os.path.join(work, re.sub(r"[^\w-]+", "-", label))
            try:
                checks = case(directory)
            except Exception as exc:
                print(f"  ERROR {label}: {exc}")
                failed += 1
                continue
            for name, predicate in checks:
                try:
                    ok = predicate()
                except Exception as exc:
                    ok, name = False, f"{name}  ({exc})"
                print(("  ok    " if ok else "  FAIL  ") + name)
                failed += not ok
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"\n{failed} check(s) failed across {len(CASES)} case(s)"
          if failed else "\nall convert checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
