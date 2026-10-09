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

sys.path.insert(0, os.path.join(ROOT, "lib"))
import pdfparagraphs  # noqa: E402

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

And an eqnarray*, which the writer would wrap in display math:

$$\begin{eqnarray*}
a &=& b + c
\end{eqnarray*}$$

And a poor man's bold, as a LaTeX book writes one: $\pmb{\hat{p}_1 - b}$.

And amssymb's squares, which unicode-math has no names for: $\square \blacksquare$.

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

| Year | Price |
|------|-------|
| 2020 | 10    |
| 2021 | 12    |

Table: Price by year

+----------------------+
| Both columns         |
+-----------+----------+
| Left      | Right    |
+===========+==========+
| 1         | 2        |
+-----------+----------+

+-------------------+-------------------+
| Racket            | Pyret             |
+===================+===================+
| > (define x 1)    | x = 1             |
+-------------------+-------------------+

+-------+-------+
| Group | Value |
+=======+=======+
| Alpha | 1     |
+       +-------+
|       | 2     |
+-------+-------+
| Beta  | 3     |
+-------+-------+

| After | Spans |
|-------|-------|
| a     | b     |
| c     | d     |
| e     | f     |

#### Deep

##### Run-in one

###### Run-in two

## After the run-in headings

A heading below a subsection is run in to the text after it, and two of
them followed by a section had left LaTeX's paragraph tagging one short.

## A section whose title runs longer than the line a running head has beside the page number, as a topic's can

Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is.

Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is.

Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is.

Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is.

Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is.

Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is.

Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is.

Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is.

Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is.

Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is.

Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is.

Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is.
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


UA1_PAGE = r"""# Old Standard

## A section

A [described link](https://example.org/ "Example, a test site") and a
formula, $a^2 + b^2 = c^2$, with a note.[^1]

[^1]: The note.
"""


def build_ua1(work):
    """A one-chapter book claiming PDF/UA-1, its math as Office writes it:
    (the PDF's path, what the run said, the output check's rows)."""
    os.makedirs(work)
    with open(os.path.join(work, "old.md"), "w", encoding="utf-8") as fh:
        fh.write(UA1_PAGE)
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  title: Old Standard\n  identifier: org.example.ua1\n"
                 "  language: en-US\n")
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  pdf:\n    format: pdf\n    pdf:\n      standard: [ua-1]\n"
                 "      ua1_math: office\n")
    converted = subprocess.run(["python3", os.path.join(BIN, "convert.py")], cwd=work,
                               capture_output=True, text=True, stdin=subprocess.DEVNULL)
    report = os.path.join(work, "output-check.csv")
    rows = []
    if os.path.exists(report):
        with open(report, encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
    return os.path.join(work, "pdf", "org.example.ua1.pdf"), converted.stdout + converted.stderr, rows


def ua1_formulas(path):
    """Each Formula's alt text, its attribute owners, and its kids' kinds."""
    pdf = pdfparagraphs.pikepdf.open(path)
    found = []

    def walk(element):
        if not pdfparagraphs.is_struct_elem(element):
            return
        if str(element["/S"]) == "/Formula":
            attributes = element.get("/A")
            attributes = attributes if isinstance(attributes, pdfparagraphs.pikepdf.Array) \
                else ([attributes] if attributes is not None else [])
            found.append((str(element.get("/Alt", "")),
                          [str(a.get("/O")) for a in attributes
                           if isinstance(a, pdfparagraphs.pikepdf.Dictionary)],
                          [str(k["/S"]) for k in pdfparagraphs.kids_of(element)
                           if pdfparagraphs.is_struct_elem(k)]))
        for kid in pdfparagraphs.kids_of(element):
            walk(kid)
    for kid in pdfparagraphs.kids_of(pdf.Root.StructTreeRoot):
        walk(kid)
    links = ["/Contents" in annot for page in pdf.pages for annot in page.get("/Annots") or []
             if str(annot.get("/Subtype")) == "/Link"]
    role = pdfparagraphs.make_role_resolver(pdf.Root.StructTreeRoot)
    kinds = []

    def roles(element):
        if pdfparagraphs.is_struct_elem(element):
            kinds.append(role(str(element["/S"])))
            for kid in pdfparagraphs.kids_of(element):
                roles(kid)
    for kid in pdfparagraphs.kids_of(pdf.Root.StructTreeRoot):
        roles(kid)
    found.append(("roles", kinds))
    return found, pdf.pdf_version, links


def page_label_styles(path):
    """The numbering style of each run of pages, in order: /D for 1, 2,
    3; /r for i, ii, iii."""
    pdf = pdfparagraphs.pikepdf.open(path)
    labels = pdf.Root.get("/PageLabels")
    if labels is None:
        return []
    nums = list(labels.get("/Nums") or [])
    return [str(nums[i + 1].get("/S")) for i in range(0, len(nums), 2)]


def spanning_table(path, index):
    """The index-th table's rows, each as a list of its cells' RowSpan (1
    when the cell has none), from the class map and the cells' own
    attributes."""
    import pdfretag
    pdf = pdfparagraphs.pikepdf.open(path)
    classes = pdf.Root.StructTreeRoot.get("/ClassMap") or {}
    found = pdfretag.tables(pdf.Root.StructTreeRoot)
    if len(found) <= index:
        return []

    def span(cell):
        names = cell.get("/C")
        names = list(names) if isinstance(names, pdfparagraphs.pikepdf.Array) else ([names] if names is not None else [])
        owned = [classes.get(str(n)) for n in names] + [cell.get("/A")]
        for attributes in owned:
            for one in (attributes if isinstance(attributes, pdfparagraphs.pikepdf.Array) else [attributes]):
                if isinstance(one, pdfparagraphs.pikepdf.Dictionary) and "/RowSpan" in one:
                    return int(one["/RowSpan"])
        return 1
    rows = []
    for row in pdfretag._kids(found[index]):
        if pdfretag._kind(row) == "/TR":
            rows.append([span(c) for c in pdfretag._cells(row)])
    return rows


def quoted_cells(path):
    """BlockQuote elements under a table cell, by their standard role."""
    pdf = pdfparagraphs.pikepdf.open(path)
    role = pdfparagraphs.make_role_resolver(pdf.Root.StructTreeRoot)
    found = []

    def walk(element, in_cell):
        if not pdfparagraphs.is_struct_elem(element):
            return
        kind_here = role(str(element["/S"]))
        if in_cell and kind_here == "/BlockQuote":
            found.append(element)
        for kid in pdfparagraphs.kids_of(element):
            walk(kid, in_cell or kind_here in ("/TD", "/TH"))
    for kid in pdfparagraphs.kids_of(pdf.Root.StructTreeRoot):
        walk(kid, False)
    return found


def children(element):
    """An element's own structure elements, in order."""
    kids = resolve(element.get("/K"))
    kids = kids if isinstance(kids, list) else [kids]
    return [resolve(k) for k in kids if isinstance(resolve(k), dict) and "/S" in resolve(k)]


def inside(everything, outer, inner):
    """The inner elements that sit anywhere under an outer one."""
    found = []
    for element in everything:
        if kind(element) == outer:
            found += [e for e in elements(element) if kind(e) == inner]
    return found


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


def font_names(reader):
    """The base font names the PDF's pages draw with, form XObjects too."""
    names = set()

    def walk(resources):
        if resources is None:
            return
        resources = resources.get_object()
        for ref in (resources.get("/Font") or {}).values():
            names.add(str(ref.get_object().get("/BaseFont", "")))
        for ref in (resources.get("/XObject") or {}).values():
            xobject = ref.get_object()
            if xobject.get("/Subtype") == "/Form":
                walk(xobject.get("/Resources"))
    for page in reader.pages:
        walk(page.get("/Resources"))
    return names


def head_sizes(reader, words):
    """The size each page's running head holding words is drawn at, its
    font's size as the page scales it."""
    import math
    sizes = []
    for page in reader.pages:
        def visit(text, cm, tm, font, size):
            if words in text:
                sizes.append(size * math.hypot(tm[0], tm[1]) * math.hypot(cm[0], cm[1]))
        page.extract_text(visitor_text=visit)
    return sizes


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
    # The other two figure placements, as LaTeX gets them: written only,
    # since LaTeX takes a while and the in_place default is built above.
    placements = {}
    for choice in ("section", "float"):
        with open(os.path.join(work, "conversion.yaml"), "w") as fh:
            fh.write(CONVERSION + "      figures: %s\n" % choice)
        run(["python3", os.path.join(BIN, "build-pdf.py"), "--latex-only"], work)
        with open(tex, encoding="utf-8") as fh:
            placements[choice] = fh.read()
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write(CONVERSION)
    report = os.path.join(work, "output-check.csv")
    rows = []
    if os.path.exists(report):
        with open(report, encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
    return pypdf.PdfReader(pdf), source, rows, converted.stderr, placements


def checks(work):
    reader, source, rows, log, placements = build(work)
    ua1_path, ua1_said, ua1_rows = build_ua1(work + "-ua1")
    ua1_math, ua1_version, ua1_links = ua1_formulas(ua1_path) if os.path.exists(ua1_path) \
        else ([], "", [])
    ua1_roles = dict(f for f in ua1_math if f[0] == "roles").get("roles", [])
    ua1_math = [f for f in ua1_math if f[0] != "roles"]
    pdf_path = os.path.join(work, "pdf", "org.example.pdf.pdf")
    root = reader.trailer["/Root"]
    tree = elements(root["/StructTreeRoot"])
    kinds = [kind(e) for e in tree]
    figures = [e for e in tree if kind(e) == "/Figure"]
    formulas = [e for e in tree if kind(e) == "/Formula"]
    found = links(reader)
    by_uri = {uri: contents for s, uri, contents in found if s == "/URI"}
    goto = [contents for s, uri, contents in found if s != "/URI"]
    tabled = tables(tree)
    table_elements = [e for e in tree if kind(e) == "/Table"]

    def shape(table):
        """A table's own children, and for each row its cells' count."""
        return [kind(k) if kind(k) != "/TR" else len(children(k)) for k in children(table)]
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
        ("a section's title too long for the running head beside the page number is "
         "scaled to fit there, not run past the margin",
         lambda: head_sizes(reader, "SECTION WHOSE TITLE RUNS")
         and all(size < 9.5 for size in head_sizes(reader, "SECTION WHOSE TITLE RUNS"))),
        ("it claims PDF/UA-2 in its metadata",
         lambda: re.search(r"pdfuaid:part[^0-9]{1,5}2",
                           resolve(root["/Metadata"]).get_data().decode(
                               "utf-8", "replace")) is not None),
        # The matrix marker declares a header column; latex-lab tags the
        # first cell of each body row TH-row only if pdf-target.lua set
        # table/header-columns around it.
        ("the matrix table's first column is row headers",
         lambda: len(tabled) == 7 and row_headers(tabled[0]) == 2),
        ("the plain table has header cells and no row headers",
         lambda: len(tabled) == 7 and row_headers(tabled[1]) == 0
         and any(kind(e) == "/TH" for e in tabled[1])),
        # LaTeX writes a longtable's caption as a first row of one header
        # cell, and leaves the empty copy of the head it repeats inside the
        # table; pdfretag.py makes the one a Caption and takes the other out.
        # The caption's wrapper also holds paragraph elements that stay
        # empty, which pdfparagraphs.py removes.
        ("headings below a subsection, followed by a section, don't stop "
         "LaTeX's tagging", lambda: "automatic begin" not in log
         and "xxxSubParagraphNoStar" in source),
        # Pandoc sets a cell spanning rows with \\multirow, which LaTeX's
        # tagging doesn't follow; pdf-target.lua says table/multirow in it.
        ("a cell spanning two rows is tagged so, and the row it covers has "
         "no cell of its own there",
         lambda: spanning_table(pdf_path, 5) == [[1, 1], [2, 1], [1], [1, 1]]),
        # LaTeX's record of the cells a span covers outlived its table, and
        # the next table lost the cells at the same places (build-pdf.py).
        ("and the table after it keeps every cell",
         lambda: spanning_table(pdf_path, 6) == [[1, 1]] * 4),
        ("a quotation in a table cell is unwrapped, since a cell can't hold one",
         lambda: not quoted_cells(pdf_path)),
        # PDF/UA-1 is PDF 1.7: no MathML structure elements, a TeX alt text
        # on each formula, Office's MathML attribute when asked for, and a
        # /Contents on every link, LaTeX's own included.
        ("a PDF/UA-1 book is PDF 1.7, and veraPDF finds nothing in it",
         lambda: ua1_version == "1.7" and os.path.exists(ua1_path)
         and (not shutil.which("verapdf") and not os.environ.get("VERAPDF") or not ua1_rows)),
        ("its formula has alt text and Office's MathML attribute, and no "
         "MathML structure elements",
         lambda: len(ua1_math) == 1 and ua1_math[0][0] and "/MSFT_Office" in ua1_math[0][1]
         and not ua1_math[0][2]),
        ("every link in it has a /Contents",
         lambda: ua1_links and all(ua1_links)),
        # A one-page book whose heading is its title: no title page, and the
        # heading is its first, at level 1 (title_page: auto).
        ("a one-page book has no title page, and its title is its level-1 heading",
         lambda: "/Title" not in ua1_roles and "/H1" in ua1_roles),
        # The divisions are written between entries, so its one page never
        # reached the main matter: numbered i, its chapter unnumbered.
        ("and its page is in the main matter, numbered 1, 2, 3",
         lambda: os.path.exists(ua1_path) and page_label_styles(ua1_path)[-1:] == ["/D"]),
        ("the run warns that its equations are tagged as PDF/UA-1 allows",
         lambda: "PDF/UA-1 has no standard way to tag MathML" in ua1_said),
        ("no paragraph element is left empty",
         lambda: not pdfparagraphs.find(pdfparagraphs.pikepdf.open(pdf_path)).doomed),
        ("a captioned table's caption is its Caption, before its rows",
         lambda: shape(table_elements[2]) == ["/Caption", 2, 2, 2]),
        ("a table whose first header row is one spanning cell, with no "
         "caption, keeps that row",
         lambda: shape(table_elements[3])[:2] == [1, 2]
         and "/Caption" not in shape(table_elements[3])),
        ("no table holds an empty artifact",
         lambda: not any(kind(k) == "/Artifact" for t in table_elements for k in children(t))),
        # pdf.figures in_place: H, so the tags stay where the text has them,
        # not gathered in a container at the end of the document.
        ("pdf.figures section flushes each section's figure tags, and lets "
         "figures float within it",
         lambda: "float/flush=section" in placements["section"]
         and "\\usepackage[section]{placeins}" in placements["section"]
         and "floatplacement" not in placements["section"]),
        ("pdf.figures float leaves LaTeX's placement alone",
         lambda: not any(word in placements["float"] for word in
                         ("floatplacement", "placeins", "float/flush"))),
        ("and the default keeps figures in place",
         lambda: "\\floatplacement{figure}{H}" in source),
        ("each figure's tags sit where the text has it",
         lambda: figures and not inside(tree, "/figures", "/Figure")),
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
        # pypdf reads the squares from TeX's AMS font by its glyph names; the
        # font's ToUnicode, which a screen reader and pdftotext go by, maps
        # them to control characters once the formula's MathML is made. So
        # the check is that no square is drawn from that font at all.
        ("amssymb's squares, which unicode-math has no names for, are the characters "
         "they are, from the OpenType math font, not TeX's AMS font",
         lambda: "□" in text and "■" in text and not any(
             "MSAM" in name or "MSBM" in name for name in font_names(reader))),
        # The one character no fallback has is reported once, in a line
        # of its own, rather than as one warning per occurrence.
        ("a character no font has is reported in one line, with its code",
         lambda: [line for line in log.splitlines()
                  if "missing from the PDF" in line]
         == [line for line in log.splitlines() if "U+6F22" in line]
         and log.count("missing from the PDF") == 1
         and "Missing character" not in log),
        # An eqnarray* among them, which the writer wrapped in \[ \] and
        # LaTeX stopped on, before pdf-target.lua wrote it as it is; and a
        # \pmb, on which LuaTeX's tagging of the formula stopped.
        ("every formula, an eqnarray* and a \\pmb among them, has MathML structure "
         "elements and a MathML file",
         lambda: len(formulas) == 5
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
    version = subprocess.run(["pandoc", "--version"], capture_output=True,
                             text=True).stdout.split()[1]
    if tuple(int(p) for p in re.findall(r"\d+", version)[:3]) < (3, 9):
        sys.exit(f"Pandoc {version} is too old; these tests need 3.9 or "
                 "later, as convert.py does.")
    if shutil.which("lualatex") is None or pypdf is None or pdfparagraphs.pikepdf is None:
        print("  skip  " + ("lualatex is not on the path"
                            if shutil.which("lualatex") is None
                            else "pypdf is not installed" if pypdf is None
                            else "pikepdf is not installed, and the PDF's repairs need it")
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
