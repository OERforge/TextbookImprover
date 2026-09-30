#!/usr/bin/env python3
"""
run-pdf-tests.py -- check the pdf target against a small Markdown book.

    python3 tests/run-pdf-tests.py           # run every check
    python3 tests/run-pdf-tests.py --keep    # leave the output in place

Needs Pandoc 3.9 or later, LuaLaTeX with LaTeX's tagging code (TeX Live
2026 or later; see docs/installation.md), and pypdf to read the result.
Without LuaLaTeX or pypdf it says so and skips; veraPDF, when found
through VERAPDF or on the path, is run by the output check and its
findings are checked too.

WHAT IS LOAD-BEARING HERE

Each thing pdf-target.lua and build-pdf.py add to what Pandoc's LaTeX
writer does has a check that fails without it: a declared header
column tagged as row headers, a decorative image an artifact rather
than a figure, every link's /Contents its visible text with any
description after it and nothing left over for a link LaTeX makes on
its own, the division commands written once each from the roles, the
page the metadata file made given no heading, and every formula's
MathML both as structure and as an attached file. The book is small
because a LaTeX run is slow; it holds one of each thing, and two of the
things that come in kinds.

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
import csv
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin")

try:
    import pypdf
except ImportError:
    pypdf = None

FRONT = r"""---
title: The Test Book
subtitle: A book for checking the PDF target
---

\frontmatter

# Preface

This preface points to [the first section](one.html#first) and cites
[https://doi.org/10/b8xx35](https://doi.org/10/b8xx35 "Crandall 2019 via doi.org"),
then [a plain link](https://example.org/).[^n]

[^n]: A note, whose mark is a link LaTeX makes on its own.

# Acknowledgements

Two headings, so neither is promoted to the page's title: the page is
titled by its metadata, which is the book's title, as a preamble is.
"""

ONE = r"""# One

## First {#first}

Greek and symbols as text, and not math, which the math repair would make
of a Greek letter alone: the letters αβγ as one word, and ≤ and ≈ named on
their own. And 漢, which no Latin Modern font has.

Inline math $x^2 + y^2 = z^2$, and a display:

$$\frac{a}{b}$$

::: matrix
|      | Left | Right |
|------|------|-------|
| Up   | 1    | 3     |
| Down | 2    | 4     |
:::

| Year | Output |
|------|--------|
| 2020 | 5      |
| 2021 | 6      |

![A small red square](assets/red.png)

A rule between paragraphs: ![](assets/rule.png){.decorative}

![](assets/blank.png)
"""

APPENDIX = r"""\appendix

# Tables of Values

Nothing more than a heading and this.
"""

PROJECT = """project:
  identifier: org.example.pdf
  title: The Test Book
  language: en
  contents:
    - page: front
      role: front
    - generate: toc
    - one
    - page: appendix
      role: appendix
"""

CONVERSION = """targets:
  html:
    format: html
  pdf:
    format: pdf
    pdf:
      metadata: front.md
"""


def png(path, rgb):
    """A 4x4 PNG of one color, written without an imaging library."""
    raw = b"".join(b"\x00" + bytes(rgb) * 4 for _ in range(4))

    def chunk(kind, data):
        body = kind + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xffffffff))
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n"
                 + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0))
                 + chunk(b"IDAT", zlib.compress(raw))
                 + chunk(b"IEND", b""))


def write_book(work):
    os.makedirs(os.path.join(work, "assets"))
    for name, text in (("front.md", FRONT), ("one.md", ONE),
                       ("appendix.md", APPENDIX), ("project.yaml", PROJECT),
                       ("conversion.yaml", CONVERSION)):
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    png(os.path.join(work, "assets", "red.png"), (200, 0, 0))
    png(os.path.join(work, "assets", "rule.png"), (0, 0, 0))
    png(os.path.join(work, "assets", "blank.png"), (255, 255, 255))


# --------------------------------------------------------------------------
# reading the PDF
# --------------------------------------------------------------------------

def resolve(obj):
    return obj.get_object() if hasattr(obj, "get_object") else obj


def elements(node, found=None):
    """Every structure element under node, in order."""
    found = [] if found is None else found
    node = resolve(node)
    if not isinstance(node, dict):
        return found
    if "/S" in node:
        found.append(node)
    kids = node.get("/K")
    if kids is None:
        return found
    kids = resolve(kids)
    for kid in (kids if isinstance(kids, list) else [kids]):
        if not isinstance(kid, int):
            elements(kid, found)
    return found


def kind(element):
    return str(element.get("/S", ""))


def classes(element):
    value = resolve(element.get("/C")) if "/C" in element else None
    if value is None:
        return []
    return [str(v) for v in value] if isinstance(value, list) else [str(value)]


def tables(everything):
    """Each /Table's elements, the table's own and not a nested one's."""
    out = []
    for element in everything:
        if kind(element) == "/Table":
            out.append(elements(element))
    return out


def links(reader):
    out = []
    for page in reader.pages:
        for annot in page.get("/Annots") or []:
            annot = resolve(annot)
            if annot.get("/Subtype") != "/Link":
                continue
            action = resolve(annot.get("/A")) if "/A" in annot else {}
            out.append((str(action.get("/S", "/Dest")),
                        str(action.get("/URI", "")),
                        str(annot["/Contents"]) if "/Contents" in annot
                        else None))
    return out


def outline_titles(reader):
    titles = []

    def walk(items):
        for item in items:
            if isinstance(item, list):
                walk(item)
            else:
                titles.append(item.title)
    walk(reader.outline)
    return titles


# --------------------------------------------------------------------------

def run(arguments, cwd, environment=None):
    return subprocess.run(arguments, cwd=cwd, env=environment,
                          capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)


def build(work):
    """The book converted by convert.py, then its LaTeX written again on
    its own so the division commands can be counted."""
    write_book(work)
    converted = run(["python3", os.path.join(BIN, "convert.py")], work)
    pdf = os.path.join(work, "pdf", "org.example.pdf.pdf")
    if not os.path.exists(pdf):
        raise RuntimeError("no PDF was written:\n" + converted.stderr[-3000:])
    latex = run(["python3", os.path.join(BIN, "build-pdf.py"),
                 "--latex-only"], work)
    tex = os.path.join(work, "pdf", "book.tex")
    if not os.path.exists(tex):
        raise RuntimeError("no LaTeX was written:\n" + latex.stderr[-3000:])
    with open(tex, encoding="utf-8") as fh:
        source = fh.read()
    report = os.path.join(work, "output-check.csv")
    rows = []
    if os.path.exists(report):
        with open(report, encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
    return pypdf.PdfReader(pdf), source, rows, converted.stderr


def checks(work):
    reader, source, rows, log = build(work)
    root = reader.trailer["/Root"]
    tree = elements(root["/StructTreeRoot"])
    kinds = [kind(e) for e in tree]
    figures = [e for e in tree if kind(e) == "/Figure"]
    formulas = [e for e in tree if kind(e) == "/Formula"]
    found = links(reader)
    by_uri = {uri: contents for s, uri, contents in found if s == "/URI"}
    goto = [contents for s, uri, contents in found if s != "/URI"]
    tabled = tables(tree)
    pdf_rows = [r for r in rows if r.get("Kind") == "pdf"]
    verapdf_ran = shutil.which("verapdf") or os.environ.get("VERAPDF")
    body = source.split("\\begin{document}", 1)[-1]
    text = "".join(page.extract_text() or "" for page in reader.pages)

    def division(command):
        return len(re.findall(re.escape(command) + r"(?![a-zA-Z])", source))

    def row_headers(table):
        return sum(1 for e in table if kind(e) == "/TH"
                   and any("TH-row" in c for c in classes(e)))

    items = [
        ("the PDF is tagged, with a structure tree and a language",
         lambda: "/StructTreeRoot" in root
         and bool(resolve(root["/MarkInfo"])["/Marked"])
         and str(root["/Lang"]) == "en"),
        ("it claims PDF/UA-2 in its metadata",
         lambda: re.search(r"pdfuaid:part[^0-9]{1,5}2",
                           resolve(root["/Metadata"]).get_data().decode(
                               "utf-8", "replace")) is not None),
        # The matrix marker declares a header column; latex-lab tags the
        # first cell of each body row TH-row only if pdf-target.lua set
        # table/header-columns around it.
        ("the matrix table's first column is row headers",
         lambda: len(tabled) == 2 and row_headers(tabled[0]) == 2),
        ("the plain table has header cells and no row headers",
         lambda: len(tabled) == 2 and row_headers(tabled[1]) == 0
         and any(kind(e) == "/TH" for e in tabled[1])),
        ("the described image is a figure with its alt text",
         lambda: any(str(f.get("/Alt")) == "A small red square"
                     for f in figures)),
        ("the decorative image is no figure",
         lambda: len(figures) == 2),
        ("an image with no alt text is reported by the output check",
         lambda: [r["Check"] for r in pdf_rows].count(
             "pdf-figure-alt-is-file-name") == 1),
        ("a link with a description reads its text, then the description",
         lambda: by_uri.get("https://doi.org/10/b8xx35")
         == "https://doi.org/10/b8xx35 (Crandall 2019 via doi.org)"),
        ("a link without one reads its text",
         lambda: by_uri.get("https://example.org/") == "a plain link"),
        ("a link within the book reads its text",
         lambda: "the first section" in goto),
        # The footnote mark, and the contents lines, are links LaTeX
        # makes itself; the reset keeps the last description off them.
        ("a link LaTeX makes on its own gets no /Contents",
         lambda: goto.count(None) >= 1
         and all(c in (None, "the first section") for c in goto)),
        # Latin Modern has no Greek; without the fallback font these are
        # drawn blank.
        ("Greek and symbols written as text are in the PDF's text",
         lambda: all(c in text for c in "αβγ≤≈")),
        # The one character no fallback has is reported once, in a line
        # of its own, rather than as one warning per occurrence.
        ("a character no font has is reported in one line, with its code",
         lambda: [line for line in log.splitlines()
                  if "missing from the PDF" in line]
         == [line for line in log.splitlines() if "U+6F22" in line]
         and log.count("missing from the PDF") == 1
         and "Missing character" not in log),
        ("every formula has MathML structure elements and a MathML file",
         lambda: len(formulas) == 2
         and all("/AF" in f for f in formulas)
         and "/math" in kinds),
        # Once each in the whole file: the template's own are switched
        # off, the book opens in the front matter from the preamble, and
        # the source's \frontmatter and \appendix are dropped.
        ("each division command is written once, from the roles",
         lambda: [division(c) for c in ("\\frontmatter", "\\mainmatter",
                                        "\\appendix", "\\backmatter")]
         == [1, 1, 1, 0]),
        # The class decides whether level 1 is a chapter, and the writer
        # reads the class from the metadata by its text.
        ("a page at the top of contents is a chapter",
         lambda: "\\chapter{One}" in body
         and "\\chapter{Tables of Values}" in body),
        ("the contents sit in the front matter, where contents puts them",
         lambda: body.index("Preface") < body.index("\\tableofcontents")
         < body.index("\\mainmatter") < body.index("{One}")),
        ("the page the metadata file made has no heading of its own",
         lambda: "The Test Book" not in outline_titles(reader)
         and {"Preface", "Acknowledgements"} <= set(outline_titles(reader))),
        # A roman i on the title page and again on the preface was what
        # the template's \mainmatter before a front page produced.
        ("no page label is used twice",
         lambda: len(reader.page_labels) == len(set(reader.page_labels))),
    ]
    if verapdf_ran:
        # The one character no font has is drawn as .notdef, which
        # veraPDF reports, and that's the only rule it finds failed.
        items.append(("veraPDF finds only the character no font has",
                      lambda: {r["Check"] for r in pdf_rows
                               if r["Tool"] == "verapdf"}
                      == {"verapdf:8.4.5.9-1"}))
        items.append(("and so the claims aren't reported as unverified",
                      lambda: not [r for r in pdf_rows if r["Check"]
                                   == "pdf-claims-unverified"]))
    else:
        print("  skip  veraPDF not found (set VERAPDF); its verdict is "
              "not checked")
    return items


def main():
    parser = argparse.ArgumentParser(
        description="Check the pdf target against a small Markdown book.")
    parser.add_argument("--keep", action="store_true",
                        help="leave the built output in place")
    arguments = parser.parse_args()

    if shutil.which("pandoc") is None:
        sys.exit("pandoc is not on the path.")
    if shutil.which("lualatex") is None or pypdf is None:
        print("  skip  " + ("lualatex is not on the path"
                            if shutil.which("lualatex") is None
                            else "pypdf is not installed")
              + "; the pdf target is not checked")
        print("\nall PDF checks skipped")
        return 0

    # A LaTeX too old to tag is a machine to set up, not a failure of the
    # target: build-pdf.py refuses it (run-convert-tests.py checks that),
    # and this suite says why it can't run.
    spec = importlib.util.spec_from_file_location(
        "build_pdf", os.path.join(BIN, "build-pdf.py"))
    build_pdf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_pdf)
    problem = build_pdf.latex_problem()
    if problem:
        print(f"  skip  {problem}")
        print("\nall PDF checks skipped")
        return 0

    work = tempfile.mkdtemp(prefix="pdf-tests-")
    failed = 0
    try:
        try:
            items = checks(work)
        except Exception as exc:
            print(f"  ERROR building the book: {exc}")
            return 1
        for name, predicate in items:
            try:
                passed = predicate()
            except Exception as exc:
                passed, name = False, f"{name}  ({exc})"
            print(("  ok    " if passed else "  FAIL  ") + name)
            failed += not passed
    finally:
        if arguments.keep:
            print(f"\nOutput left in {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
    print(f"\n{failed} check(s) failed" if failed
          else "\nall PDF checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
