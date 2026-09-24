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
import zipfile

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
    output. It lives in _pt/ and its references resolve from the book's
    directory, as though it sat beside the sources."""
    os.makedirs(os.path.join(work, "front"), exist_ok=True)
    os.makedirs(os.path.join(work, "_pt"), exist_ok=True)
    with open(os.path.join(work, "_pt", "frontmatter.html"), "w",
              encoding="utf-8") as fh:
        fh.write(HAND)
    with open(os.path.join(work, "_pt", "notes.md"), "w",
              encoding="utf-8") as fh:
        fh.write("# Notes by hand\n\n![A logo](front/logo.png)\n")
    with open(os.path.join(work, "front", "style.css"), "w") as fh:
        fh.write("body {}\n")
    with open(os.path.join(work, "front", "logo.png"), "wb") as fh:
        fh.write(ONE_PIXEL)
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
        ("a Markdown page in _pt is converted, its image found from the "
         "book's directory",
         lambda: exists(work, "html", "notes.html")
         and 'src="front/logo.png"' in read(work, "html", "notes.html")),
        ("and in the cartridge, with its files",
         lambda: any(n.endswith("/frontmatter.html") for n in names)
         and any(n.endswith("/front/style.css") for n in names)),
        ("and the output check looked at it",
         lambda: "Output check: 7 page(s)" in result.stderr),
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


# A real one-pixel PNG: epubcheck reads the images.
import base64
ONE_PIXEL = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYGAAAAAEAAH2FzhVAAAAAElFTkSuQmCC")

MARKDOWN = """---
title: Costs in the Long Run
---

# Costs in the Long Run

\\frontmatter

Text with a [reference](https://doi.org/10.1017/x){aria-label="DOI for Seidel 2014"}.
<!-- a citation, 28--29, which XHTML forbids in a comment -->

![A pipe vs. a tube](assets/Pipe Sizes.png)

![Written on Windows](assets\\Curve.png) ![Escaped away](assets\\_under.png)

::: matrix
|      | Left | Right |
|------|------|-------|
| Up   | 1    | 2     |
| Down | 3    | 4     |
:::

| Plain | Table |
|-------|-------|
| a     | b     |

## Economies of Scale

More text.
"""


def case_markdown(work):
    """A Markdown source is a page like a .docx is."""
    os.makedirs(os.path.join(work, "assets"), exist_ok=True)
    with open(os.path.join(work, "long run.md"), "w", encoding="utf-8") as fh:
        fh.write(MARKDOWN)            # a space in the name, on purpose
    for image in ("Pipe Sizes.png", "Curve.png", "_under.png"):
        with open(os.path.join(work, "assets", image), "wb") as fh:
            fh.write(ONE_PIXEL)
    # A leftover from v0.1: an .md with the same name as a .docx.
    with open(os.path.join(work, "tables.md"), "w", encoding="utf-8") as fh:
        fh.write("# old\n")
    result = convert(work, "defaults:\n  pages:\n    split_level: 2\n"
                           "targets:\n  html:\n    format: html\n"
                           "  epub:\n    format: epub3\n")
    # "long run.md" is the page long-run: no space reaches an href.
    page = read(work, "html", "long-run.html") if exists(
        work, "html", "long-run.html") else ""
    section = read(work, "html", "long-run--economies-of-scale.html") \
        if exists(work, "html", "long-run--economies-of-scale.html") else ""
    epub_path = os.path.join(work, "epub", "org.example.fixtures.epub")
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import outputcheck
    epubcheck = outputcheck.find_validator("epubcheck")
    validated = None
    if epubcheck and os.path.exists(epub_path):
        validated = outputcheck.run_epubcheck(epubcheck, epub_path)
    else:
        print("  skip  epubcheck not installed (EPUBCHECK_JAR)")
    return [
        ("a stem with a space gives ids without one, and epubcheck agrees",
         lambda: validated == [] if validated is not None else True),
        ("the run succeeds", lambda: result.returncode == 0),
        ("the Markdown source becomes a page, split like any other",
         lambda: page and section),
        ("its title is the promoted heading",
         lambda: "<title>Costs in the Long Run</title>" in page),
        ("a ::: matrix table gets row headers, a plain one does not",
         lambda: page.count('<th scope="row">') == 2
         and '<th scope="col">Plain</th>' in page),
        ("a link's aria-label survives",
         lambda: 'aria-label="DOI for Seidel 2014"' in page),
        ("an image named by path is copied beside the page under a safe "
         "name, and the page refers to that",
         lambda: exists(work, "html", "assets", "Pipe-Sizes.png")
         and 'src="assets/Pipe-Sizes.png"' in page
         and not exists(work, "html", "assets", "Pipe Sizes.png")),
        ("an image path written with a backslash is read with a slash, "
         "and the run says so",
         lambda: 'src="assets/Curve.png"' in page
         and 'src="assets/_under.png"' in page
         and result.stderr.count("a path only Windows resolves") == 2),
        ("raw LaTeX is dropped, not shown",
         lambda: "frontmatter" not in page),
        ("a raw HTML comment is dropped, so a -- inside one reaches no "
         "output",
         lambda: "<!--" not in page and "28--29" not in page),
        ("no non-breaking space after \"vs.\" in alt text",
         lambda: 'alt="A pipe vs. a tube"' in page),
        ("an .md with a same-named .docx is a leftover, not a source",
         lambda: not exists(work, "html", "tables.md")
         and "tables.md is left over" in result.stderr),
        ("the EPUB has the page",
         lambda: exists(work, "epub", "org.example.fixtures.epub")),
    ]


WEB = """<!DOCTYPE html><html lang="en"><head><title>A Web Page -- The Site</title></head>
<body><nav><ul><li><a href="other.html">Other</a></li></ul></nav>
<main><div class="chapter"><div class="wrap"><p></p><h1>A Web Page</h1></div></div>
<table><thead><tr><th>Country</th><th>GDP</th></tr></thead>
<tbody><tr><th>Brazil</th><td>3,153</td></tr>
<tr><th>Canada</th><td>1,827</td></tr></tbody></table>
<table><tbody><tr><td>1</td><td>2</td></tr><tr><td>3</td><td>4</td></tr></tbody></table>
<table><tbody><tr><th>Prefix</th><th>Represents</th></tr>
<tr><td>kilo</td><td>one thousand</td></tr></tbody></table>
<iframe src="https://example.invalid/embed/x" title="A video"></iframe>
</main></body></html>
"""


def run_in(directory, contents=None):
    if contents is not None:
        with open(os.path.join(directory, "project.yaml"), "w",
                  encoding="utf-8") as fh:
            fh.write("project:\n  identifier: org.example.fixtures\n"
                     "  title: The Fixture Book\n" + contents)
    return subprocess.run(
        ["python3", os.path.join(BIN, "convert.py"), "--quiet"],
        cwd=directory, capture_output=True, text=True,
        stdin=subprocess.DEVNULL)


def same_pages(one, two):
    names = sorted(n for n in os.listdir(one) if n.endswith(".html"))
    return bool(names) and all(
        open(os.path.join(one, n), "rb").read()
        == open(os.path.join(two, n), "rb").read() for n in names)


def case_asciidoc(work):
    """An AsciiDoc book: a master file that includes its chapters."""
    os.makedirs(os.path.join(work, "images"))
    with open(os.path.join(work, "images", "lock.png"), "wb") as fh:
        fh.write(ONE_PIXEL)
    files = {
        "index.adoc": "= The Book\nAnn Author <ann@example.org>; Bo Writer\n"
                      ":imagesdir: images\n:toc: left\n:lang: en-GB\n\n"
                      "include::one.adoc[]\n\ninclude::two.adoc[]\n",
        "one.adoc": "= Chapter One\n\n== Keys\n\nSee <<Locks>> and "
                    "<<Chapter Two>>.\n\nimage::lock.png[A lock]\n",
        "two.adoc": "= Chapter Two\n\n[[locks-id]]\n== Locks\n\nBack to "
                    "<<Keys>>. Write to mailto:ann@example.org[Ann], or "
                    "try the `ftp://` scheme.\n",
    }
    for name, text in files.items():
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    result = convert(work, "targets:\n  html:\n    format: html\n")
    one = read(work, "html", "one.html") if exists(work, "html",
                                                    "one.html") else ""
    sample = read(work, "contents-sample.yaml") if exists(
        work, "contents-sample.yaml") else ""
    return [
        ("each included file is a page, and the master isn't",
         lambda: result.returncode == 0 and one
         and exists(work, "html", "two.html")
         and not exists(work, "html", "index.html")),
        ("the chapter's = line is its title, its == sections are h2",
         lambda: "<title>Chapter One</title>" in one
         and re.search(r"<h2[^>]*>Keys</h2>", one)),
        ("an image takes the master's imagesdir",
         lambda: 'src="images/lock.png"' in one),
        ("Asciidoctor's own settings don't reach the page",
         lambda: 'id="TOC"' not in one),
        ("a reference by section title or chapter title lands, across "
         "chapters",
         lambda: 'href="two.html#locks-id"' in one
         and 'href="two.html"' in one
         and 'href="one.html#_keys"' in read(work, "html", "two.html")),
        ("the master's order is offered as contents",
         lambda: sample.index("- one") < sample.index("- two")),
        ("and its title, authors, and language with it",
         lambda: "title: The Book" in sample
         and "- Ann Author" in sample and "- Bo Writer" in sample
         and "language: en-GB" in sample),
        ("a mailto: link keeps its scheme; a scheme in code is code, not a "
         "link",
         lambda: 'href="mailto:ann@example.org"' in read(work, "html",
                                                         "two.html")
         and "<code>ftp://</code>" in read(work, "html", "two.html")
         and 'href="ftp://"' not in read(work, "html", "two.html")),
    ]


def case_stem_collisions(work):
    """Two files that would be one page stop the run; the leftover rules
    still hold; and an image's alt text isn't lent to a file that merely
    shares its stem."""
    def book(name, files, config="targets:\n  html:\n    format: html\n"):
        where = os.path.join(work, name)
        for path, text in files.items():
            os.makedirs(os.path.dirname(os.path.join(where, path)) or where,
                        exist_ok=True)
            mode = "wb" if isinstance(text, bytes) else "w"
            with open(os.path.join(where, path), mode) as fh:
                fh.write(text)
        return where, convert(where, config)
    md, adoc = "# One\n\nText.\n", "= One\n\nText.\n"
    with open(os.path.join(FIXTURES, "tables.docx"), "rb") as fh:
        docx = fh.read()
    a, same = book("formats", {"ch1.md": md, "ch1.adoc": adoc})
    b, safe = book("safe", {"Chapter 1.md": md, "Chapter-1.adoc": adoc})
    c, passthrough = book("pt", {"about.docx": docx, "_pt/about.md": md})
    d, variant = book("variants", {"ch1.md": md, "ch1.print.md": md,
                                   "ch1.print.adoc": adoc},
                      "targets:\n  html:\n    format: html\n"
                      "  print:\n    format: html\n")
    e, leftover = book("leftover", {"x.docx": docx, "x.md": md})
    g, _ = book("adoc-variant", {"ch1.adoc": "= One\n\nWeb text.\n",
                                 "ch1.print.adoc": "= One\n\nPrint text.\n"},
                "targets:\n  web:\n    format: html\n"
                "  print:\n    format: html\n")
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'
    f, logos = book("logos", {
        "pics.md": "# Pics\n\n![](assets/logo.png)\n\n![](assets/logo.svg)\n",
        "assets/logo.png": ONE_PIXEL, "assets/logo.svg": svg,
        "image-alt.csv": "Image,Alt\nassets/logo.png,A logo\n"})
    h, spaced = book("spaced", {
        "pics.md": "# Pics\n\n![One](assets/a%20b.png)\n\n![Two](assets/a-b.png)\n",
        "assets/a b.png": ONE_PIXEL, "assets/a-b.png": ONE_PIXEL + b"\0"})
    page = read(f, "html", "pics.html") if exists(f, "html", "pics.html") \
        else ""
    missing = read(f, "image-alt-missing.csv") if exists(
        f, "image-alt-missing.csv") else ""
    said = lambda r: r.stdout + r.stderr
    return [
        ("ch1.md and ch1.adoc stop the run, both named, nothing converted",
         lambda: same.returncode != 0 and "ch1: ch1.adoc, ch1.md" in said(same)
         and not exists(a, "html") and not exists(a, "ch1.json")),
        ("names that differ only until made safe for a link meet too",
         lambda: safe.returncode != 0
         and "Chapter 1.md" in said(safe) and "Chapter-1.adoc" in said(safe)),
        ("a pass-through page can't share a source's name",
         lambda: passthrough.returncode != 0
         and "_pt/about.md" in said(passthrough)
         and "about.docx" in said(passthrough)),
        ("two variants of one page for one target stop the run",
         lambda: variant.returncode != 0
         and "variant of the same page" in said(variant)),
        ("an .md beside its .docx is still a v0.1 leftover, not a clash",
         lambda: leftover.returncode in (0, 1) and exists(e, "html", "x.html")),
        ("an AsciiDoc variant replaces its page for its target, and isn't "
         "a page of its own",
         lambda: "Print text." in read(g, "print", "ch1.html")
         and "Web text." in read(g, "web", "ch1.html")
         and not exists(g, "web", "ch1.print.html")),
        ("two images an HTML target would write under one name stop the run",
         lambda: spaced.returncode != 0
         and "would both be written as assets/a-b.png" in said(spaced)
         and not exists(h, "html")),
        ("an image's alt text goes to that image, not one sharing its stem",
         lambda: re.search(r'src="assets/logo\.png"[^>]*alt="A logo"|'
                           r'alt="A logo"[^>]*src="assets/logo\.png"', page)
         and not re.search(r'src="assets/logo\.svg"[^>]*alt="A logo"|'
                           r'alt="A logo"[^>]*src="assets/logo\.svg"', page)),
        ("and the other is reported as needing its own",
         lambda: "assets/logo.svg" in missing
         and "assets/logo.png" not in missing),
    ]


def case_adopt(work):
    """A split book's pages adopted as the sources of a new one."""
    os.makedirs(os.path.join(work, "_pt"))
    with open(os.path.join(work, "ch1.md"), "w", encoding="utf-8") as fh:
        fh.write("# Chapter One\n\nOpening.\n\n## First Part\n\nSee "
                 "[the second](#second-part).\n\n## Second Part\n\nEnd.\n")
    with open(os.path.join(work, "_pt", "about.html"), "w",
              encoding="utf-8") as fh:
        fh.write(HAND.replace("Front Matter", "About"))
    convert(work, "defaults:\n  pages:\n    split_level: 2\n"
                  "targets:\n  html:\n    format: html\n")
    out = work + "-adopted"
    adopted = subprocess.run(
        ["python3", os.path.join(BIN, "adopt-pages.py"),
         os.path.join(work, "html"), "-o", out],
        capture_output=True, text=True)
    first = read(out, "ch1-first-part.html") if exists(
        out, "ch1-first-part.html") else ""
    import yaml
    project = yaml.safe_load(read(out, "project.yaml"))["project"] if exists(
        out, "project.yaml") else {}
    again = run_in(out)
    return [
        ("the pieces are renamed with one hyphen",
         lambda: adopted.returncode == 0 and first
         and not any("--" in n for n in os.listdir(out))),
        ("a link between pieces follows the rename",
         lambda: 'href="ch1-second-part.html#second-part"' in first),
        ("the split's provenance is gone from the page",
         lambda: 'name="source-page"' not in first
         and 'name="page-part"' not in first),
        ("contents names the pages as they are now, grouped as before",
         lambda: next(e["items"] for e in project["contents"]
                      if isinstance(e, dict) and e.get("title")
                      == "Chapter One")
         == ["ch1", "ch1-first-part", "ch1-second-part"]),
        ("a finished page goes back into _pt/",
         lambda: exists(out, "_pt", "about.html")
         and not exists(out, "about.html")),
        ("the adopted book converts, every page in contents, links landing",
         lambda: again.returncode in (0, 1)
         and "not listed in contents" not in again.stdout + again.stderr
         and exists(out, "html", "ch1-first-part.html")
         and 'href="ch1-second-part.html#second-part"'
         in read(out, "html", "ch1-first-part.html")),
    ]


HEADED = """<!DOCTYPE html><html lang="en"><head><title>Data</title></head>
<body><main><h1>Data</h1>
<table><tr><td><b>Set</b></td><td><b>Hours</b></td></tr>
<tr><td>Alpha</td><td>9.8</td></tr><tr><td>Beta</td><td>5.3</td></tr></table>
<table><thead><tr><th>Country</th><th>GDP</th></tr></thead>
<tbody><tr><td>Brazil</td><td>3,153</td></tr></tbody></table>
<table><tr><td><span style="font-weight: bold">Method</span></td>
<td><span class="hspace">&nbsp;&nbsp;</span></td>
<td><span style="font-weight: bold">Cost</span></td></tr>
<tr><td>Memoization</td><td>&nbsp;</td><td>Space</td></tr></table>
<table><tr><td></td></tr></table>
<table><tr><td>Government purchases</td><td>$120 billion</td></tr>
<tr><td>Depreciation</td><td>$40 billion</td></tr>
<tr><td>Consumption</td><td>$400 billion</td></tr></table>
</main></body></html>
"""


def case_html_headers(work):
    """An HTML source's tables go through the header pre-pass: the guess
    where the page says nothing, the page's own <th> where it does, and
    the sidecar over both."""
    os.makedirs(work)
    with open(os.path.join(work, "data.html"), "w", encoding="utf-8") as fh:
        fh.write(HEADED)
    first = run_in(work, "")
    page = read(work, "html", "data.html") if exists(
        work, "html", "data.html") else ""
    new_rows = read(work, "table-headers-new.csv") if exists(
        work, "table-headers-new.csv") else ""
    import csv
    with open(os.path.join(work, "table-headers-report.csv"),
              encoding="utf-8") as fh:
        report = list(csv.DictReader(fh))
    country = next((r for r in report if "Country" in r["preview"]), {})
    with open(os.path.join(work, "table-headers.csv"), "w",
              encoding="utf-8") as fh:
        fh.write("key,headers\n" + country.get("key", "x") + ",none\n")
    run_in(work)
    again = read(work, "html", "data.html") if exists(
        work, "html", "data.html") else ""
    return [
        ("an unmarked bold row is guessed a header row",
         lambda: re.search(r'<th scope="col">(<strong>)?Set', page)),
        ("labels over values get row headers by the guess",
         lambda: '<th scope="row">Government purchases</th>' in page),
        ("the report says who supplied each: the guess, or the page",
         lambda: sorted(r["supplier"] for r in report)
         == ["guess", "guess", "guess", "source"]),
        ("every HTML table is in the new-rows file, keyed",
         lambda: len(new_rows.splitlines()) == 5),
        ("bold written as a style is bold, a column with nothing in it goes, "
         "and the guess then sees the header row",
         lambda: re.search(r'<th scope="col">(<strong>)?Method', page)
         and "&nbsp;" not in page.split("Method")[1].split("</table>")[0]
         and page.split("Method")[1].split("</table>")[0].count("<td") == 2),
        ("a table with nothing in it is dropped",
         lambda: "<td></td>" not in page),
        ("a sidecar row outranks the page's own <th>",
         lambda: '<th scope="col">Country</th>' in page
         and "Country</th>" not in again and "<td>Country</td>" in again),
    ]


def case_menu(work):
    """menu: on gives every rendered page the book's contents and a
    previous/next pager; a pass-through page is left as it stands."""
    os.makedirs(os.path.join(work, "_pt"))
    with open(os.path.join(work, "ch1.md"), "w", encoding="utf-8") as fh:
        fh.write("# Chapter One\n\nOpening.\n\n## First Part\n\nA.\n\n"
                 "## Second Part\n\nB.\n")
    with open(os.path.join(work, "_pt", "about.html"), "w",
              encoding="utf-8") as fh:
        fh.write(HAND.replace("Front Matter", "About"))
    result = convert(work, "defaults:\n  pages:\n    split_level: 2\n"
                           "targets:\n  html:\n    format: html\n"
                           "    menu: \"on\"\n"
                           "  plain:\n    format: html\n")
    first = read(work, "html", "ch1--first-part.html") if exists(
        work, "html", "ch1--first-part.html") else ""
    checks = read(work, "output-check.csv") if exists(
        work, "output-check.csv") else ""
    return [
        ("a page carries the book's contents as a collapsed menu, its own "
         "entry marked current",
         lambda: result.returncode in (0, 1)
         and '<nav class="book-menu" aria-label="Contents">' in first
         and '<summary>Contents</summary>' in first
         and 'href="ch1--first-part.html" aria-current="page"' in first
         and first.count('aria-current="page"') == 1),
        ("and previous and next pages at its foot, by title",
         lambda: 'rel="prev" href="ch1.html"' in first
         and 'rel="next" href="ch1--second-part.html">Next: Second Part'
         in first),
        ("every link the menu adds leads somewhere",
         lambda: "link-to-missing" not in checks),
        ("a pass-through page is left as it stands",
         lambda: read(work, "html", "about.html")
         == HAND.replace("Front Matter", "About")),
        ("a target without menu: on has none",
         lambda: '<nav class="book-menu"' not in read(
             work, "plain", "ch1--first-part.html")),
    ]


RAW_MD = """---
title: Raw HTML
---

# Raw HTML

Energy is mc<sup>2</sup>, and <span href="http://purl.org/dc/dcmitype/Text"
rel="dct:type">this work</span> is licensed.<br>A new line.

<p align="center"><img src="assets/Curve.png" alt="A curve" align="left"></p>

<details><summary>Answer</summary>

Hidden *until asked*.

</details>

<table>
<tr><th>Year</th><th>Output</th></tr>
<tr><td align="right">2000</td><td>10</td></tr>
</table>

A remote badge: <img src="https://example.invalid/badge.png" alt="A badge">

<iframe src="https://www.youtube.com/embed/abc123?start=30"></iframe>

<iframe src="https://player.vimeo.com/video/76979871" title="A film"></iframe>

<iframe src="https://www.youtube-nocookie.com/embed/videoseries?list=PL123"
title="A playlist"></iframe>

Code stays: `<p align="center">` and

```
<img src="/logo.png" align="left">
```
"""


def case_markdown_html(work):
    """Raw HTML in a Markdown source is read as HTML and cleaned the way
    an HTML source is; code is left exactly as written."""
    os.makedirs(os.path.join(work, "assets"))
    with open(os.path.join(work, "assets", "Curve.png"), "wb") as fh:
        fh.write(ONE_PIXEL)
    with open(os.path.join(work, "raw.md"), "w", encoding="utf-8") as fh:
        fh.write(RAW_MD)
    result = convert(work, "targets:\n  html:\n    format: html\n"
                           "  md:\n    format: markdown\n"
                           "  epub:\n    format: epub3\n")
    page = read(work, "html", "raw.html") if exists(
        work, "html", "raw.html") else ""
    chapter, epub_text = "", ""
    for name in (os.listdir(os.path.join(work, "epub"))
                 if exists(work, "epub") else []):
        with zipfile.ZipFile(os.path.join(work, "epub", name)) as book:
            epub_text += "".join(book.read(n).decode("utf-8", "replace")
                                 for n in book.namelist()
                                 if n.endswith(".xhtml"))
        with zipfile.ZipFile(os.path.join(work, "epub", name)) as book:
            chapter = "".join(book.read(n).decode("utf-8")
                              for n in book.namelist() if "badge" in
                              book.read(n).decode("utf-8", "replace"))
    return [
        ("a superscript written in HTML is a superscript",
         lambda: result.returncode in (0, 1) and "mc<sup>2</sup>" in page),
        ("an HTML image is an image: copied, and without align",
         lambda: re.search(r'<img src="assets/Curve\.png"[^>]*alt="A curve"',
                           page) and 'align="left"' not in page
         and exists(work, "html", "assets", "Curve.png")),
        ("RDFa's href leaves the span, the text stays",
         lambda: "this work" in page
         and "purl.org/dc/dcmitype/Text" not in page),
        ("details and summary are kept, the summary's text plain",
         lambda: re.search(r"<summary>\s*Answer\s*</summary>", page)
         and "<details>" in page),
        ("an HTML table is a table, its th row the header, no align",
         lambda: re.search(r'<th[^>]*scope="col"[^>]*>Year</th>', page)
         and 'align="right"' not in page),
        ("a remote image stays an image in HTML and is a link in the EPUB",
         lambda: 'src="https://example.invalid/badge.png"' in page
         and '<a href="https://example.invalid/badge.png">A badge</a>'
         in chapter and "<img" not in chapter.split("A badge")[0][-200:]),
        ("a video's frame stays the player in HTML, and in the EPUB links to "
         "the video's own page, start time and playlist kept",
         lambda: 'src="https://www.youtube.com/embed/abc123?start=30"' in page
         and all(link in epub_text for link in (
             'href="https://www.youtube.com/watch?v=abc123&amp;t=30s"',
             'href="https://vimeo.com/76979871"',
             'href="https://www.youtube.com/playlist?list=PL123"'))),
        ("code is left exactly as written",
         lambda: "<code>&lt;p align=&quot;center&quot;&gt;</code>" in page
         or '<code>&lt;p align="center"&gt;</code>' in page),
        ("and so is a code block",
         lambda: '&lt;img src=&quot;/logo.png&quot; align=&quot;left&quot;&gt;'
         in page or '&lt;img src="/logo.png" align="left"&gt;' in page),
    ]


BANDED = """<!DOCTYPE html><html lang="en"><head><title>Bands</title></head>
<body><main><h1>Bands</h1>
<table><tr><td colspan="3"><b>The Message Triangle</b></td></tr>
<tr><td><b>Element</b></td><td><b>Focus</b></td><td><b>Example</b></td></tr>
<tr><td>Purpose</td><td>The core idea</td><td>A request</td></tr>
<tr><td>Clarity</td><td>How simply</td><td>A number</td></tr></table>
<table><tr><td></td><td><b>Labor</b></td><td><b>Total</b></td></tr>
<tr><td colspan="3">Example A: workers cost $40</td></tr>
<tr><td>Tech 1</td><td>$400</td><td>$560</td></tr>
<tr><td>Tech 2</td><td>$280</td><td>$600</td></tr>
<tr><td colspan="3">Example B: workers cost $55</td></tr>
<tr><td>Tech 1</td><td>$550</td><td>$710</td></tr>
<tr><td>Tech 2</td><td>$385</td><td>$705</td></tr></table>
<table><tbody><tr><th colspan="2" scope="rowgroup">Group one</th></tr>
<tr><td>a</td><td>1</td></tr></tbody>
<tbody><tr><th colspan="2" scope="rowgroup">Group two</th></tr>
<tr><td>b</td><td>2</td></tr></tbody></table>
</main></body></html>
"""


def case_bands(work):
    """An HTML source's title rows and bands: split for an HTML target,
    kept as one grouped table for a Markdown one, and the grouped table
    read back splits the same way. And a page with no title stays one."""
    os.makedirs(work)
    with open(os.path.join(work, "bands.html"), "w", encoding="utf-8") as fh:
        fh.write(BANDED)
    with open(os.path.join(work, "untitled.html"), "w", encoding="utf-8") as fh:
        fh.write('<!DOCTYPE html><html lang="en"><head></head><body>'
                 "<p>No title here.</p></body></html>\n")
    def run_with(where, config):
        with open(os.path.join(where, "conversion.yaml"), "w",
                  encoding="utf-8") as fh:
            fh.write(config)
        return run_in(where, "  contents:\n    - bands\n    - untitled\n")
    run_with(work, "targets:\n  html:\n    format: html\n"
                   "  md:\n    format: markdown\n")
    page = read(work, "html", "bands.html") if exists(
        work, "html", "bands.html") else ""
    md = read(work, "md", "bands.md") if exists(work, "md", "bands.md") else ""
    captions = lambda text: [" ".join(re.sub(r"<[^>]+>", "", c).split())
                             for c in re.findall(r"<caption>(.*?)</caption>",
                                                 text, re.S)]
    back = work + "-from-md"
    shutil.copytree(os.path.join(work, "md"), back)
    run_with(back, "targets:\n  html:\n    format: html\n")
    again = read(back, "html", "bands.html") if exists(
        back, "html", "bands.html") else ""
    # A person's part captions, in the row the run prefilled for the table.
    captioned = work + "-captioned"
    shutil.copytree(work, captioned, ignore=shutil.ignore_patterns(
        "html", "md", "*.json"))
    import csv
    with open(os.path.join(work, "table-headers-new.csv"),
              encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        if "Labor" in row["preview"]:
            row["part-captions"] = "Cost at $40 a worker | Cost at $55 a worker"
    with open(os.path.join(captioned, "table-headers.csv"), "w",
              encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    run_with(captioned, "targets:\n  html:\n    format: html\n")
    with_parts = read(captioned, "html", "bands.html") if exists(
        captioned, "html", "bands.html") else ""
    # tables.bands: column, and its output converted again.
    column = work + "-column"
    shutil.copytree(work, column, ignore=shutil.ignore_patterns(
        "html", "md", "*.json", "*.csv"))
    column_config = ("targets:\n  html:\n    format: html\n"
                     "    tables:\n      bands: column\n")
    run_with(column, column_config)
    in_column = read(column, "html", "bands.html") if exists(
        column, "html", "bands.html") else ""
    column_again = column + "-again"
    os.makedirs(column_again)
    for name in ("bands.html", "untitled.html"):
        shutil.copy(os.path.join(column, "html", name), column_again)
    run_with(column_again, column_config)
    cells = lambda text: re.findall(r"<t[hd][^>]*>[^<]*", text)
    fixed = work + "-from-html"
    os.makedirs(fixed)
    for name in ("bands.html", "untitled.html"):
        shutil.copy(os.path.join(work, "html", name), fixed)
    run_with(fixed, "targets:\n  html:\n    format: html\n")
    return [
        ("a merged title row is the caption, and the header row beneath it "
         "is the header row",
         lambda: "The Message Triangle" in captions(page)
         and re.search(r'<th scope="col">(<strong>)?Element', page)),
        ("bands split an HTML target's table, one header row heading each "
         "part",
         lambda: [c for c in captions(page) if c.startswith("Example")]
         == ["Example A: workers cost $40", "Example B: workers cost $55"]
         and page.count('scope="col">(<strong>)?Labor') == 0
         and len(re.findall(r'<th scope="col">(?:<strong>)?Labor', page)) == 2),
        ("groups the source already made split the same way",
         lambda: "Group one" in captions(page) and "Group two" in captions(page)),
        ("a Markdown target keeps each banded table whole, a body per band "
         "headed by the band",
         lambda: len(re.findall(r'<tbody>\s*<tr>\s*<th colspan="\d">'
                                r'(Example|Group)', md)) == 4
         and not any(c.startswith("Example") for c in captions(md))),
        ("read back from Markdown, the groups split into the same captions",
         lambda: captions(again) == captions(page) and captions(page)),
        ("a page with no title is named by itself, and converting it again "
         "adds no heading",
         lambda: "<title>untitled</title>" in read(work, "html", "untitled.html")
         and "<h1" not in read(fixed, "html", "untitled.html")
         and "filtered" not in read(work, "html", "untitled.html")),
        ("a person's part captions, in the sidecar, name the parts of an "
         "HTML table",
         lambda: [c for c in captions(with_parts) if "worker" in c]
         == ["Cost at $40 a worker", "Cost at $55 a worker"]
         and not any(c.startswith("Example") for c in captions(with_parts))),
        ("tables.bands: column keeps one table, each band a row-group "
         "header spanning its rows beside the row headers",
         lambda: '<th rowspan="2" scope="rowgroup">Example A' in in_column
         and '<th rowspan="2" scope="rowgroup">Example B' in in_column
         and '<th scope="rowgroup">Group one' in in_column
         and in_column.count('<th scope="row">Tech') == 4
         and not any(c.startswith("Example") for c in captions(in_column))),
        ("and converting that output again gives the same cells",
         lambda: cells(in_column) and cells(read(
             column_again, "html", "bands.html")) == cells(in_column)),
        ("converting the HTML output again gives the same tables",
         lambda: captions(read(fixed, "html", "bands.html")) == captions(page)),
    ]


def case_compare_blocks(work):
    """compare-output.py sees a quotation that became a paragraph and a
    list that lost an item, which change no heading, table, or image."""
    page = ('<!DOCTYPE html><html lang="en"><head><title>Q</title></head><body>'
            '<h1>Q</h1>%s<ul><li>one</li><li>two<ol><li>a</li><li>b</li></ol>'
            '</li>%s</ul></body></html>')
    for name, quote, item in (("one", "<blockquote><p>Said.</p></blockquote>",
                               "<li>three</li>"),
                              ("two", "<p>Said.</p>", "")):
        os.makedirs(os.path.join(work, name))
        with open(os.path.join(work, name, "q.html"), "w",
                  encoding="utf-8") as fh:
            fh.write(page % (quote, item))
    run = subprocess.run(["python3", os.path.join(ROOT, "util", "compare-output.py"),
                          os.path.join(work, "one"), os.path.join(work, "two")],
                         capture_output=True, text=True)
    same = subprocess.run(["python3", os.path.join(ROOT, "util", "compare-output.py"),
                           os.path.join(work, "one"), os.path.join(work, "one")],
                          capture_output=True, text=True)
    return [
        ("a blockquote turned paragraph is reported",
         lambda: "blockquote_count" in run.stdout),
        ("a lost list item is reported, with each list's kind, depth, and items",
         lambda: "list_outline" in run.stdout and "ul1:3,ol2:2" in run.stdout
         and "ul1:2,ol2:2" in run.stdout),
        ("a page compared with itself still agrees",
         lambda: "Runs agree" in same.stdout),
    ]


def case_warc_direct(work):
    """convert.py in a directory holding a web archive and nothing else
    unpacks it and converts the pages; later runs leave the pages, the
    book from then on, alone."""
    import importlib.util
    if not (importlib.util.find_spec("html5lib") or importlib.util.find_spec("lxml")):
        return [("skip: unpacking needs html5lib or lxml", lambda: True)]
    spec = importlib.util.spec_from_file_location(
        "site_tests", os.path.join(HERE, "run-site-tests.py"))
    site = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(site)
    page = ('<html lang="en"><head><title>{t}</title></head><body><nav><ul>'
            '<li><a href="/book/one.html">One</a></li>'
            '<li><a href="/book/two.html">Two</a></li></ul></nav>'
            '<main><h1>{t}</h1><p>The {t} page.</p></main></body></html>')
    archive = b"".join(site.warc_record(
        "https://example.org/book/%s.html" % name,
        "200 OK\r\nContent-Type: text/html", page.format(t=name.title()).encode())
        for name in ("one", "two"))
    config = "targets:\n  html:\n    format: html\n"

    def fresh(where, extra=None):
        os.makedirs(where)
        with open(os.path.join(where, "crawl.warc.gz"), "wb") as fh:
            fh.write(archive)
        with open(os.path.join(where, "conversion.yaml"), "w") as fh:
            fh.write(config)
        for name, text in (extra or {}).items():
            with open(os.path.join(where, name), "w") as fh:
                fh.write(text)

    def run(where, *flags):
        return subprocess.run(["python3", os.path.join(BIN, "convert.py"),
                               "--quiet", *flags], cwd=where,
                              capture_output=True, text=True,
                              stdin=subprocess.DEVNULL)
    fresh(work)
    first = run(work)
    pages = sorted(n for n in os.listdir(work) if n.endswith(".html"))
    converted = sorted(n for n in os.listdir(os.path.join(work, "html"))
                       if n.endswith(".html")) if os.path.isdir(
        os.path.join(work, "html")) else []
    corrected = ""
    if pages:
        path = os.path.join(work, pages[0])
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace("page.", "page, corrected."))
        second = run(work)
        with open(os.path.join(work, "html", pages[0]), encoding="utf-8") as fh:
            corrected = fh.read()
    kept = work + "-kept"
    fresh(kept, {"project.yaml": "project:\n  title: Mine\n"})
    run(kept)
    checked = work + "-checked"
    fresh(checked)
    check = run(checked, "--check-only")
    return [
        ("a directory holding only a WARC is unpacked into it, project.yaml "
         "and all", lambda: len(pages) == 2 and os.path.isfile(
             os.path.join(work, "project.yaml"))),
        ("and its pages are converted in the same run",
         lambda: len(converted) >= 2),
        ("a later run converts the corrected page and doesn't unpack again",
         lambda: "corrected" in corrected),
        ("a project.yaml already there is kept, the unpacker's beside it",
         lambda: "Mine" in open(os.path.join(kept, "project.yaml")).read()
         and os.path.isfile(os.path.join(kept, "project-unpacked.yaml"))),
        ("--check-only unpacks nothing",
         lambda: not [n for n in os.listdir(checked) if n.endswith(".html")]),
    ]


CC_MANIFEST = """<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="m" xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1">
<metadata><schema>IMS Common Cartridge</schema><schemaversion>1.1.0</schemaversion>
<lom xmlns="http://ltsc.ieee.org/xsd/imsccv1p1/LOM/manifest"><general><title>
<string language="en-US">A Course</string></title></general></lom></metadata>
<organizations><organization identifier="o" structure="rooted-hierarchy"><item identifier="root">
<item identifier="w1"><title>Week 1</title>
<item identifier="h1"><title>Readings</title></item>
<item identifier="i1" identifierref="ra"><title>Page A</title></item>
<item identifier="i2" identifierref="rb"><title>Read this week</title></item>
<item identifier="i3" identifierref="rd"><title>Discuss</title></item>
<item identifier="i4" identifierref="rl"><title>A site</title></item>
<item identifier="i5" identifierref="rp"><title>The guide</title></item>
</item>
<item identifier="w2"><title>Week 2</title>
<item identifier="i6" identifierref="rw"><title>The reading</title></item>
<item identifier="i7" identifierref="ra"><title>Page A again</title></item>
</item></item></organization></organizations>
<resources>
<resource identifier="ra" type="webcontent" href="wiki_content/a.html"><file href="wiki_content/a.html"/></resource>
<resource identifier="rb" type="webcontent" href="content/Read this week..html"><file href="content/Read this week..html"/></resource>
<resource identifier="rd" type="imsdt_xmlv1p1"><file href="d.xml"/></resource>
<resource identifier="rl" type="imswl_xmlv1p1"><file href="l.xml"/></resource>
<resource identifier="rp" type="webcontent" href="web_resources/The Guide.pdf"><file href="web_resources/The Guide.pdf"/></resource>
<resource identifier="rw" type="webcontent" href="web_resources/reading.docx"><file href="web_resources/reading.docx"/></resource>
<resource identifier="rc" type="webcontent" href="wiki_content/c.html"><file href="wiki_content/c.html"/></resource>
<resource identifier="re" type="webcontent" href="wiki_content/e.html"><file href="wiki_content/e.html"/></resource>
<resource identifier="rq" type="associatedcontent/imscc_xmlv1p1/learning-application-resource"><file href="non_cc_assessments/q.qti"/></resource>
<resource identifier="rpic" type="webcontent" href="web_resources/Uploaded Media/pic.png"><file href="web_resources/Uploaded Media/pic.png"/></resource>
<resource identifier="rchk" type="webcontent" href="web_resources/Setup Checklist.docx"><file href="web_resources/Setup Checklist.docx"/></resource>
</resources></manifest>"""


def case_cartridge(work):
    """A Common Cartridge unpacked and converted: Canvas's placeholders,
    queries, and text headers, a Brightspace page with no title, what
    isn't a page reported, and our own cartridge read back as the book it
    was built from."""
    import importlib.util
    import zipfile
    if not (importlib.util.find_spec("html5lib") or importlib.util.find_spec("lxml")):
        return [("skip: HTML sources need html5lib or lxml", lambda: True)]
    os.makedirs(work)
    page_a = ('<html><head><title>Page A</title></head><body><h2>A</h2>'
              '<p><img src="$IMS-CC-FILEBASE$/Uploaded%20Media/pic.png?canvas_=1&amp;canvas_qs_wrap=1" alt="A picture"></p>'
              '<p><a href="$IMS-CC-FILEBASE$/The%20Guide.pdf?canvas_download=1">the guide</a> and '
              '<a href="$WIKI_REFERENCE$/pages/e">page E</a>, with '
              '<a href="$IMS-CC-FILEBASE$/Setup%20Checklist.docx?canvas_=1">the checklist</a></p>'
              '</body></html>')
    page_b = ('<!DOCTYPE html><html><head><link rel="stylesheet" '
              'href="https://s.brightspace.com/lib/fonts/0.6.1/fonts.css"></head>'
              '<body><p>Read the chapter.</p></body></html>')
    unpublished = ('<html><head><title>C</title><meta name="workflow_state" '
                   'content="unpublished"/></head><body><p>Draft.</p></body></html>')
    listed_nowhere = '<html><head><title>E</title></head><body><p>E.</p></body></html>'
    course = os.path.join(work, "course.imscc")
    with zipfile.ZipFile(course, "w") as z:
        z.writestr("imsmanifest.xml", CC_MANIFEST)
        z.writestr("wiki_content/a.html", page_a)
        z.writestr("content/Read this week..html", page_b)
        z.writestr("wiki_content/c.html", unpublished)
        z.writestr("wiki_content/e.html", listed_nowhere)
        z.writestr("d.xml", "<topic/>")
        z.writestr("l.xml", '<webLink><title>A site</title><url href="https://example.org/"/></webLink>')
        z.writestr("web_resources/The Guide.pdf", b"%PDF-1.4 guide")
        z.writestr("web_resources/Uploaded Media/pic.png", ONE_PIXEL)
        z.write(os.path.join(FIXTURES, "metadata.docx"), "web_resources/reading.docx")
        z.write(os.path.join(FIXTURES, "tables.docx"), "web_resources/Setup Checklist.docx")
        z.writestr("non_cc_assessments/q.qti", "<questestinterop/>")
    book = os.path.join(work, "book")
    os.makedirs(book)
    shutil.copy(course, book)
    with open(os.path.join(book, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n"
                 "  epub:\n    format: epub3\n")
    run = subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quiet"],
                         cwd=book, capture_output=True, text=True,
                         stdin=subprocess.DEVNULL)
    project = open(os.path.join(book, "project.yaml")).read() if exists(
        book, "project.yaml") else ""
    report = open(os.path.join(book, "unpack-report.csv")).read() if exists(
        book, "unpack-report.csv") else ""
    page_b_out = read(book, "Read-this-week.html") if exists(
        book, "Read-this-week.html") else ""
    a_out = read(book, "html", "a.html") if exists(book, "html", "a.html") else ""
    checked = open(os.path.join(book, "output-check.csv")).read() if exists(
        book, "output-check.csv") else ""
    epub_text = ""
    for root_dir, _, files in os.walk(book):
        for name in files:
            if name.endswith(".epub"):
                with zipfile.ZipFile(os.path.join(root_dir, name)) as z:
                    epub_text = "".join(z.read(n).decode("utf-8", "replace")
                                        for n in z.namelist()
                                        if n.endswith(".xhtml"))

    # The same cartridge with --linked-documents.
    linked = os.path.join(work, "linked")
    os.makedirs(linked)
    shutil.copy(course, linked)
    with open(os.path.join(linked, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n"
                 "  epub:\n    format: epub3\n")
    subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quiet",
                    "--linked-documents"], cwd=linked, capture_output=True,
                   text=True, stdin=subprocess.DEVNULL)
    linked_project = open(os.path.join(linked, "project.yaml")).read() if exists(
        linked, "project.yaml") else ""
    linked_a = read(linked, "html", "a.html") if exists(linked, "html", "a.html") else ""
    linked_checked = open(os.path.join(linked, "output-check.csv")).read() if exists(
        linked, "output-check.csv") else ""

    # Our own cartridge, read back.
    ours = os.path.join(work, "ours")
    convert(ours, "targets:\n  html:\n    format: html\n", arguments=["--zip"])
    back = os.path.join(work, "back")
    os.makedirs(back)
    built = os.path.join(ours, "org.example.fixtures.imscc")
    if os.path.exists(built):
        shutil.copy(built, back)
    with open(os.path.join(back, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quiet"],
                   cwd=back, capture_output=True, text=True,
                   stdin=subprocess.DEVNULL)
    agree = subprocess.run(["python3", os.path.join(ROOT, "util", "compare-output.py"),
                            os.path.join(ours, "html"), os.path.join(back, "html")],
                           capture_output=True, text=True).stdout
    return [
        ("a cartridge alone in a directory is unpacked and converted",
         lambda: run.returncode == 0 and exists(book, "html", "a.html")),
        ("modules are groups, and a Canvas text header groups the entries "
         "after it", lambda: re.search(r'title: "Week 1"\s+items:\s+- title: '
                                       r'"Readings"\s+items:\s+- page: a', project)),
        ("a Word file in the outline is a source, and converts",
         lambda: exists(book, "reading.docx") and exists(book, "html", "reading.html")),
        ("a page with no title takes the outline's, and a dotted file name "
         "ends cleanly", lambda: "<title>Read this week</title>" in page_b_out),
        ("Canvas's placeholders and queries resolve, and the linked file is "
         "copied with the page under its safe name",
         lambda: "Uploaded-Media/pic.png" in a_out
         and 'href="web_resources/The-Guide.pdf"' in a_out
         and exists(book, "html", "web_resources", "The-Guide.pdf")
         and 'href="e.html"' in a_out),
        ("the output check counts a linked file that's on disk as there",
         lambda: checked and "html/a.html,link-to-missing-file" not in checked),
        ("an EPUB keeps a link to a file as its text, and the output check "
         "reports it", lambda: "the guide" in epub_text
         and re.search(r'data-file="web_resources/The[ -]Guide\.pdf"', epub_text)
         and not re.search(r'href="[^"]*Guide\.pdf"', epub_text)
         and "link-to-file-dropped" in checked),
        ("a linked Word file stays a file by default, and the report says "
         "the switch would make it a page",
         lambda: 'href="web_resources/Setup-Checklist.docx"' in a_out
         and "linked-document-kept" in report),
        ("with --linked-documents it's a page beneath the page linking to it, "
         "titled by the link, in the HTML and the EPUB",
         lambda: re.search(r'- title: "Page A"\s+items:\s+- page: a\s+'
                           r'title: "Page A"\s+- page: Setup-Checklist\s+'
                           r'title: "the checklist"', linked_project)
         and 'href="Setup-Checklist.html"' in linked_a
         and exists(linked, "html", "Setup-Checklist.html")
         and "Setup Checklist.docx" not in linked_checked
         and "Setup-Checklist.docx" not in linked_checked),
        ("a page listed twice is in the book once, and the report says so",
         lambda: project.count("page: a\n") == 1 and "listed-twice" in report),
        ("what isn't a page is reported: discussion, web link, file, test bank",
         lambda: all(k in report for k in ("discussion", "web-link",
                                           "file-in-outline",
                                           "unlisted-assessment"))),
        ("an unpublished page is left out; one the outline doesn't list is kept",
         lambda: not exists(book, "c.html") and "page: e" in project
         and "not-in-outline" in report),
        ("our own cartridge converts back to the book it was built from",
         lambda: os.path.exists(built) and "Runs agree" in agree),
    ]


def case_zip(work):
    """A plain zip of a book's files, alone in a directory: extracted with
    the folder around it dropped, nothing let outside the book, the
    directory's own settings kept, and nothing done with a zip holding no
    sources or with a slide deck, which is a zip too."""
    import zipfile
    os.makedirs(work)
    book = os.path.join(work, "book")
    os.makedirs(book)
    with zipfile.ZipFile(os.path.join(book, "My Book.zip"), "w") as z:
        z.writestr("My Book/ch1.md", "# One\n\n![A dot](images/dot.png)\n")
        z.writestr("My Book/ch2.md", "# Two\n\nThe first draft.\n")
        z.writestr("My Book/images/dot.png", ONE_PIXEL)
        z.writestr("My Book/conversion.yaml", "targets:\n  md:\n    format: markdown\n")
        z.writestr("My Book/.DS_Store", "junk")
        z.writestr("__MACOSX/My Book/._ch1.md", "junk")
        z.writestr("../evil.txt", "outside")
    with open(os.path.join(book, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n")

    def run(where):
        return subprocess.run(["python3", os.path.join(BIN, "convert.py"),
                               "--quiet"], cwd=where, capture_output=True,
                              text=True, stdin=subprocess.DEVNULL)
    first = run(book)
    if exists(book, "ch2.md"):
        with open(os.path.join(book, "ch2.md"), "w") as fh:
            fh.write("# Two\n\nThe corrected draft.\n")
    second = run(book)
    empty = os.path.join(work, "empty")
    os.makedirs(empty)
    with zipfile.ZipFile(os.path.join(empty, "handouts.zip"), "w") as z:
        z.writestr("handouts/slides.pdf", b"%PDF-1.4")
    none = run(empty)
    deck = os.path.join(work, "deck")
    os.makedirs(deck)
    with zipfile.ZipFile(os.path.join(deck, "talk.pptx"), "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
    deck_run = run(deck)
    saved = os.path.join(work, "saved")
    os.makedirs(saved)
    with zipfile.ZipFile(os.path.join(saved, "site.zip"), "w") as z:
        z.writestr("Intro _ Site.html", '<!DOCTYPE html>\n<!-- saved from url=(0036)'
                   'https://example.org/book/intro.html -->\n<html lang="en"><head>'
                   '<title>Intro | Site</title></head><body><main><h1>Intro</h1>'
                   '<p>Hello.</p></main></body></html>')
        z.writestr("Intro _ Site_files/style.css", "body { }")
    with open(os.path.join(saved, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    saved_run = run(saved)
    saved_pages = [n for n in os.listdir(saved) if n.endswith(".html")]
    report = open(os.path.join(book, "unpack-report.csv")).read() if exists(
        book, "unpack-report.csv") else ""
    return [
        ("a zip alone in a directory is extracted, the folder around it "
         "dropped, and converted", lambda: "Unpacked My Book.zip" in first.stderr
         and exists(book, "ch1.md") and exists(book, "images", "dot.png")
         and not exists(book, "My Book") and exists(book, "html", "ch1.html")),
        ("macOS's litter stays out", lambda: not exists(book, "__MACOSX")
         and not exists(book, ".DS_Store")),
        ("an entry that would land outside the book is refused and reported",
         lambda: not os.path.exists(os.path.join(work, "evil.txt"))
         and "unsafe-path" in report),
        ("the directory's own conversion.yaml is kept, the zip's beside it",
         lambda: "html" in open(os.path.join(book, "conversion.yaml")).read()
         and exists(book, "conversion-unpacked.yaml")),
        ("a later run converts a correction and doesn't extract again",
         lambda: "corrected" in read(book, "html", "ch2.html")
         and "not read" in second.stdout + second.stderr),
        ("a zip with no sources stops the run, saying what it holds",
         lambda: none.returncode != 0 and "slides.pdf" in none.stdout + none.stderr
         and not exists(empty, "slides.pdf")),
        ("a zip of a browser's save goes through unpack-site.py: pages named "
         "from their addresses, not the browser's file names",
         lambda: "saved from a browser" in saved_run.stderr
         and len(saved_pages) == 1 and "_" not in saved_pages[0]
         and exists(saved, "project.yaml")),
        ("a slide deck is a zip but not an archive to unpack",
         lambda: "talk.pptx" not in deck_run.stdout + deck_run.stderr
         and not exists(deck, "[Content_Types].xml")),
    ]


MATHJAX2 = """<!DOCTYPE html><html lang="en"><head><title>Growth</title></head><body><main><h1>Growth</h1>
<p>Inline <span class="MathJax" id="MathJax-Element-1-Frame"><nobr><span class="math" id="MathJax-Span-1"><span><span class="mrow" id="MathJax-Span-2"><span class="msubsup" id="MathJax-Span-3"><span style="position: absolute; top: -4.0em;"><span class="mi" id="MathJax-Span-4">k</span></span><span style="position: absolute; top: -4.4em;"><span class="mn" id="MathJax-Span-5">2</span></span></span><span class="mo" id="MathJax-Span-6">+</span><span class="mfrac" id="MathJax-Span-7"><span style="position: absolute; top: -3.4em;"><span class="mn" id="MathJax-Span-9">2</span></span><span style="position: absolute; top: -4.6em;"><span class="mn" id="MathJax-Span-8">1</span></span></span></span></span></span></nobr></span> ends here.</p>
<div class="MathJax_Display" style="text-align: center;"><span class="MathJax" id="MathJax-Element-2-Frame"><span class="math" id="MathJax-Span-10"><span class="mrow" id="MathJax-Span-11"><span class="mtable" id="MathJax-Span-12"><span style="position: absolute; top: -5.0em;"><span class="mtd" id="MathJax-Span-13"><span class="mn" id="MathJax-Span-14">4</span></span></span><span style="position: absolute; top: -3.0em;"><span class="mtd" id="MathJax-Span-17"><span class="mn" id="MathJax-Span-18">11</span></span></span><span style="position: absolute; top: -5.0em;"><span class="mtd" id="MathJax-Span-15"><span class="mtext" id="MathJax-Span-16">base</span></span></span><span style="position: absolute; top: -3.0em;"><span class="mtd" id="MathJax-Span-19"><span class="mtext" id="MathJax-Span-20">step</span></span></span></span></span></span></span></div>
<p>With its TeX <span class="MathJax" id="MathJax-Element-3-Frame"><span class="math" id="MathJax-Span-21"><span class="mi" id="MathJax-Span-22">x</span></span></span><script type="math/tex" id="MathJax-Element-3">x+1</script> kept.</p>
</main></body></html>
"""


def case_mathjax2(work):
    """A formula as MathJax 2 drew it is rebuilt as MathML: children in
    the formula's order, a lone script named by where it sits, a table's
    rows found again; a rendering beside its TeX is dropped. And the
    Markdown the page becomes reads back."""
    import importlib.util
    if not (importlib.util.find_spec("html5lib") or importlib.util.find_spec("lxml")):
        return [("skip: HTML sources need html5lib or lxml", lambda: True)]
    os.makedirs(work)
    with open(os.path.join(work, "growth.html"), "w", encoding="utf-8") as fh:
        fh.write(MATHJAX2)
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n  md:\n    format: markdown\n")
    run = subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quiet"],
                         cwd=work, capture_output=True, text=True,
                         stdin=subprocess.DEVNULL)
    page = read(work, "html", "growth.html") if exists(work, "html", "growth.html") else ""
    back = work + "-back"
    if exists(work, "md"):
        shutil.copytree(os.path.join(work, "md"), back)
        with open(os.path.join(back, "conversion.yaml"), "w") as fh:
            fh.write("targets:\n  html:\n    format: html\n")
        try:
            subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quiet"],
                           cwd=back, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=120)
        except subprocess.TimeoutExpired:
            pass
    again = read(back, "html", "growth.html") if exists(back, "html", "growth.html") else ""
    fraction = re.search(r"<mfrac>\s*<mn>1</mn>\s*<mn>2</mn>\s*</mfrac>", page)
    return [
        ("MathJax's rendering becomes MathML, and none of it is left",
         lambda: page.count("<math") == 3 and 'class="MathJax' not in page
         and "formula(s) rebuilt" in run.stderr),
        ("children follow the formula's order, not the layout's",
         lambda: bool(fraction)),
        ("a lone script drawn as msubsup is a superscript",
         lambda: re.search(r"<msup>\s*<mi>k</mi>\s*<mn>2</mn>\s*</msup>", page)),
        ("a table's rows are found again from its cells' heights",
         lambda: len(re.findall(r"<mtr>", page)) == 2
         and re.search(r"<mtr>\s*<mtd[^>]*>\s*<mn>4</mn>\s*</mtd>\s*<mtd[^>]*>"
                       r"\s*<mtext[^>]*>base", page)),
        ("a rendering beside its TeX is dropped, so the formula is there once",
         lambda: "x+1" in page.replace(" ", "") and page.count(">x<") <= 1),
        ("the Markdown the page becomes reads back, math and all",
         lambda: again.count("<math") == 3),
    ]


def case_asciidoc_layout(work):
    """An AsciiDoc block's width and target don't reach an element XHTML
    forbids them on; an image block's size goes to its image."""
    os.makedirs(work)
    with open(os.path.join(work, "ch.adoc"), "w", encoding="utf-8") as fh:
        fh.write("= A chapter\n\n[width=300,float=right]\nimage::dot.png[A dot]\n\n"
                 "[source,python,width=400]\n----\nprint('hi')\n----\n\n"
                 "[width=50%,float=left]\n|===\n|Name |Count\n|a |1\n|===\n")
    with open(os.path.join(work, "dot.png"), "wb") as fh:
        fh.write(ONE_PIXEL)
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n  epub:\n    format: epub3\n")
    subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quiet"],
                   cwd=work, capture_output=True, text=True,
                   stdin=subprocess.DEVNULL)
    page = read(work, "html", "ch.html") if exists(work, "html", "ch.html") else ""
    import zipfile
    epub_text = ""
    for root_dir, _, files in os.walk(os.path.join(work, "epub")):
        for name in files:
            if name.endswith(".epub"):
                with zipfile.ZipFile(os.path.join(root_dir, name)) as z:
                    epub_text = "".join(z.read(n).decode("utf-8", "replace")
                                        for n in z.namelist() if n.endswith(".xhtml"))
    checked = open(os.path.join(work, "output-check.csv")).read() if exists(
        work, "output-check.csv") else ""
    bad = r"<(figure|div|pre|table)\b[^>]*\b(width|target)="
    return [
        ("no width or target on a block, in the HTML or the EPUB",
         lambda: page and epub_text and not re.search(bad, page)
         and not re.search(bad, epub_text)),
        ("an image block's width is its image's",
         lambda: re.search(r'<img [^>]*width="300"', page)),
        ("epubcheck finds nothing to object to, where it's installed",
         lambda: "epubcheck:RSC-005" not in checked),
    ]


def case_not_implemented(work):
    """A pdf or docx target says it's not implemented and is skipped;
    with nothing else to build, the run stops and says why."""
    os.makedirs(work)
    with open(os.path.join(work, "ch.md"), "w") as fh:
        fh.write("# One\n\nText.\n")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  web:\n    format: html\n  print:\n    format: pdf\n"
                 "  word:\n    format: docx\n")
    mixed = subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quiet"],
                           cwd=work, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)
    only = work + "-only"
    os.makedirs(only)
    shutil.copy(os.path.join(work, "ch.md"), only)
    with open(os.path.join(only, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  print:\n    format: pdf\n")
    alone = subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quiet"],
                           cwd=only, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)
    return [
        ("each pdf or docx target is named NOT YET IMPLEMENTED and skipped",
         lambda: mixed.stderr.count("NOT YET IMPLEMENTED") == 2
         and exists(work, "web", "ch.html")
         and not exists(work, "print") and not exists(work, "word")),
        ("a book with only such targets stops and says why",
         lambda: alone.returncode != 0
         and "NOT YET IMPLEMENTED" in alone.stdout + alone.stderr),
    ]


def case_html_ids(work):
    """An id with a space in it -- Scribble writes them -- becomes one
    without, and every link to it follows, from its own page or another."""
    import importlib.util
    if not (importlib.util.find_spec("html5lib") or importlib.util.find_spec("lxml")):
        return [("skip: HTML sources need html5lib or lxml", lambda: True)]
    os.makedirs(work)
    with open(os.path.join(work, "a.html"), "w", encoding="utf-8") as fh:
        fh.write('<html lang="en"><head><title>A</title></head><body><h1>A</h1>'
                 '<h2 id="section 15">Fifteen</h2><p>See <a href="#section 15">here</a> '
                 'and <a href="#section%2015">there</a>.</p></body></html>')
    with open(os.path.join(work, "b.html"), "w", encoding="utf-8") as fh:
        fh.write('<html lang="en"><head><title>B</title></head><body><h1>B</h1>'
                 '<p>Back to <a href="a.html#section 15">fifteen</a>.</p></body></html>')
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n  epub:\n    format: epub3\n")
    subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quiet"],
                   cwd=work, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    a = read(work, "html", "a.html") if exists(work, "html", "a.html") else ""
    b = read(work, "html", "b.html") if exists(work, "html", "b.html") else ""
    checked = open(os.path.join(work, "output-check.csv")).read() if exists(
        work, "output-check.csv") else ""
    return [
        ("an id's whitespace becomes a hyphen",
         lambda: 'id="section-15"' in a and 'id="section 15"' not in a),
        ("links to it follow, encoded or not, from its page or another",
         lambda: a.count('href="#section-15"') == 2
         and 'href="a.html#section-15"' in b),
        ("nothing is reported missing, and epubcheck has no complaint",
         lambda: exists(work, "epub") and "missing-fragment" not in checked
         and "RSC-005" not in checked),
    ]


def case_html_images(work):
    """An HTML source's decorative images stay decorative: an empty alt,
    or Canvas's role="presentation" with none. An image with no alt is
    still reported, and a frame's size is made valid."""
    import importlib.util
    if not (importlib.util.find_spec("html5lib") or importlib.util.find_spec("lxml")):
        return [("skip: HTML sources need html5lib or lxml", lambda: True)]
    os.makedirs(work)
    with open(os.path.join(work, "d.png"), "wb") as fh:
        fh.write(ONE_PIXEL)
    with open(os.path.join(work, "p.html"), "w", encoding="utf-8") as fh:
        fh.write('<!DOCTYPE html><html lang="en"><head><title>P</title></head><body><h1>P</h1>'
                 '<p><img src="d.png" alt=""> empty</p>'
                 '<p><img src="d.png" role="presentation"> Canvas</p>'
                 '<p><img src="d.png" alt="A dot"> described</p>'
                 '<p><img src="d.png"> missing</p>'
                 '<p><iframe src="https://example.org/x" width="1200px" height="100%" '
                 'style="border: 0"></iframe></p></body></html>')
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quiet"],
                   cwd=work, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    page = read(work, "html", "p.html") if exists(work, "html", "p.html") else ""
    images = re.findall(r"<img[^>]*>", page)
    report = open(os.path.join(work, "output-check.csv")).read() if exists(
        work, "output-check.csv") else ""
    frame = (re.findall(r"<iframe[^>]*>", page) or [""])[0]
    return [
        ("an empty alt, and role=presentation without one, are decorative: "
         "alt=\"\", no role", lambda: len(images) == 4
         and all('alt=""' in i and "role=" not in i for i in images[:2])),
        ("a described image keeps its alt; one without is still reported",
         lambda: 'alt="A dot"' in images[2] and "alt=" not in images[3]
         and report.count("image-without-alt") == 1),
        ("a frame's width in px loses the unit, and a percentage is a style",
         lambda: 'width="1200"' in frame and "height=" not in frame
         and "height: 100%" in frame),
    ]


def case_asciidoc_markdown(work):
    """An AsciiDoc chapter written as Markdown reads back as the same page."""
    os.makedirs(work)
    with open(os.path.join(work, "ch.adoc"), "w", encoding="utf-8") as fh:
        fh.write("= A chapter\n\nIntro with *strong* and a https://example.org[link].\n\n"
                 "== A section\n\n* one\n* two\n\n[source,python]\n----\nprint('hi')\n----\n\n"
                 "|===\n|Name |Count\n|a |1\n|b |2\n|===\n\nimage::dot.png[A dot]\n")
    with open(os.path.join(work, "dot.png"), "wb") as fh:
        fh.write(ONE_PIXEL)
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n  md:\n    format: markdown\n")
    subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quiet"],
                   cwd=work, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    back = work + "-back"
    if exists(work, "md"):
        shutil.copytree(os.path.join(work, "md"), back)
        with open(os.path.join(back, "conversion.yaml"), "w") as fh:
            fh.write("targets:\n  html:\n    format: html\n")
        subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quiet"],
                       cwd=back, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    agree = subprocess.run(["python3", os.path.join(ROOT, "util", "compare-output.py"),
                            os.path.join(work, "html"), os.path.join(back, "html")],
                           capture_output=True, text=True).stdout
    return [
        ("AsciiDoc to Markdown and back gives the same page",
         lambda: exists(back, "html", "ch.html") and "Runs agree" in agree),
    ]


def case_html_source(work):
    """An HTML page is a source when the book says so, and converting
    what this pipeline wrote changes nothing."""
    # The fixtures and a Markdown page, converted; then their pages as the
    # sources of a second book, and that book's pages as a third's.
    os.makedirs(os.path.join(work, "assets"), exist_ok=True)
    with open(os.path.join(work, "long run.md"), "w", encoding="utf-8") as fh:
        fh.write(MARKDOWN.replace("assets\\Curve.png", "assets/Curve.png")
                 .replace("assets\\_under.png", "assets/_under.png"))
    for image in ("Pipe Sizes.png", "Curve.png", "_under.png"):
        with open(os.path.join(work, "assets", image), "wb") as fh:
            fh.write(ONE_PIXEL)
    with open(os.path.join(work, "noted.md"), "w", encoding="utf-8") as fh:
        fh.write(NOTED)
    convert(work, "targets:\n  html:\n    format: html\n")
    second, third = work + "-second", work + "-third"
    shutil.copytree(os.path.join(work, "html"), second)
    again = run_in(second)
    shutil.copytree(os.path.join(second, "html"), third)
    run_in(third)
    compared = subprocess.run(
        ["python3", os.path.join(ROOT, "util", "compare-output.py"),
         os.path.join(work, "html"), os.path.join(second, "html")],
        capture_output=True, text=True)
    page = read(second, "html", "long-run.html") if exists(
        second, "html", "long-run.html") else ""

    # A page from somewhere else, marked in contents, beside one that is not.
    mixed = work + "-mixed"
    os.makedirs(mixed)
    shutil.copy(os.path.join(FIXTURES, "tables.docx"), mixed)
    os.makedirs(os.path.join(mixed, "_pt"))
    for name in ("web.html", os.path.join("_pt", "finished.html")):
        with open(os.path.join(mixed, name), "w", encoding="utf-8") as fh:
            fh.write(WEB)
    # Titles with no heading behind them: one repeats the book's name after
    # its own, one names another site, one is only the book's name.
    for name, title in (("cover", "Cover -- The Fixture Book"),
                        ("elsewhere", "Notes | Another Site"),
                        ("bookname", "The Fixture Book")):
        with open(os.path.join(mixed, name + ".html"), "w",
                  encoding="utf-8") as fh:
            fh.write(f"<!DOCTYPE html><html lang=\"en\"><head><title>{title}"
                     "</title></head><body><p>Text.</p></body></html>\n")
    with open(os.path.join(mixed, "conversion.yaml"), "w",
              encoding="utf-8") as fh:
        fh.write("targets:\n  html:\n    format: html\n"
                 "  epub:\n    format: epub3\n")
    marked = run_in(mixed, "  contents:\n    - tables\n    - web\n"
                           "    - finished\n    - cover\n    - elsewhere\n"
                           "    - bookname\n")
    web = read(mixed, "html", "web.html") if exists(
        mixed, "html", "web.html") else ""
    epub_page = ""
    for name in (os.listdir(os.path.join(mixed, "epub"))
                 if exists(mixed, "epub") else []):
        with zipfile.ZipFile(os.path.join(mixed, "epub", name)) as book:
            epub_page = "".join(book.read(n).decode("utf-8")
                                for n in book.namelist()
                                if n.endswith(".xhtml") and "example.invalid"
                                in book.read(n).decode("utf-8"))
    return [
        ("a directory of nothing but .html is read as sources",
         lambda: exists(second, "html", "tables.html")
         and exists(second, "tables.json")),
        ("converting our own pages gives the same book",
         lambda: "Runs agree" in compared.stdout),
        ("the second write is the third, byte for byte",
         lambda: same_pages(os.path.join(second, "html"),
                            os.path.join(third, "html"))),
        # The second write equalling the third says nothing about what the
        # first reading lost: a footnote's text once went missing between
        # the first write and the second, and the second and third agreed.
        ("a footnote is still a footnote, text and all",
         lambda: "Note C." in read(second, "html", "noted.html")
         and read(second, "html", "noted.html")
         == read(work, "html", "noted.html")),
        ("the title is written once and a table is wrapped once",
         lambda: page.count("<h1") == 1
         and page.count('class="table-wrapper"') == page.count("<table")),
        ("an .html beside a .docx is a source, and the run says how to keep "
         "one as it stands",
         lambda: "belongs in _pt/" in marked.stdout + marked.stderr),
        ("a page's only h1, inside wrappers, is its title: one h1, and "
         "the <title> the site gave it goes",
         lambda: web.count("<h1") == 1 and "<title>A Web Page</title>" in web),
        ("a page's title loses the book's name when it repeats it after "
         "its own; another site's name, and a title that is only the "
         "book's, stay",
         lambda: "<title>Cover</title>" in read(mixed, "html", "cover.html")
         and "<title>Notes | Another Site</title>"
         in read(mixed, "html", "elsewhere.html")
         and "<title>The Fixture Book</title>"
         in read(mixed, "html", "bookname.html")),
        ("a page beside the sources is converted",
         lambda: marked.returncode in (0, 1)
         and 'class="table-wrapper"' in web),
        ("a th in every body row is a row header again, and a thead's "
         "cells column headers",
         lambda: 'scope="row">Brazil' in web and 'scope="row">Canada' in web
         and 'scope="col">Country' in web),
        ("a header row written inside tbody is the table's head",
         lambda: re.search(r'<thead>\s*<tr>\s*<th scope="col">Prefix', web)
         is not None),
        ("only what is in <main> is the page, and no iframe is fetched",
         lambda: "other.html" not in web
         and "Could not fetch" not in marked.stdout + marked.stderr),
        ("an iframe stays an iframe in an HTML target, and nothing else "
         "raw is left",
         lambda: '<iframe src="https://example.invalid/embed/x" '
         'title="A video"></iframe>' in web
         and "</nav>" not in web and "iframe x1" in marked.stderr),
        ("in the EPUB it is a link to what it framed, named by its title",
         lambda: epub_page and "<iframe" not in epub_page
         and '<a href="https://example.invalid/embed/x">A video</a>'
         in re.sub(r"\s+", " ", epub_page)),
        ("a table of bare numbers is guessed to have no headers, and listed "
         "for review",
         lambda: "needs-source" in read(mixed, "table-headers-report.csv")
         and "as <th> cells" in read(mixed, "table-headers-report.csv")
         and len(read(mixed, "table-headers-new.csv").splitlines()) >= 2),
        ("a page in _pt is copied as it stands",
         lambda: read(mixed, "html", "finished.html") == WEB),
    ]


NOTED = """# Chapter One

Text.[^a] More.[^b]

## First Section

Section text.[^c]

## Second Section

Another.[^d]

[^a]: Note A.
[^b]: Note B.
[^c]: Note C.
[^d]: Note D.
"""


def case_notes(work):
    """notes.numbering and notes.placement, on a chapter cut into pages."""
    import zipfile

    def build(sub, numbering, placement):
        d = os.path.join(work, sub)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "ch1.md"), "w", encoding="utf-8") as fh:
            fh.write(NOTED)
        with open(os.path.join(d, "ch2.md"), "w", encoding="utf-8") as fh:
            fh.write("# Chapter Two\n\nTwo.[^e]\n\n[^e]: Note E.\n")
        r = convert(d, "defaults:\n  pages:\n    split_level: 2\n  notes:\n"
                       f"    numbering: {numbering}\n    placement: "
                       f"{placement}\ntargets:\n  html:\n    format: html\n"
                       "  epub:\n    format: epub3\n")
        nav = ""
        e = os.path.join(d, "epub", "org.example.fixtures.epub")
        if os.path.exists(e):
            with zipfile.ZipFile(e) as z:
                nav = z.read("EPUB/nav.xhtml").decode("utf-8")
        return d, r, nav

    gp, r1, _ = build("group-page", "group", "page")
    gg, r2, _ = build("group-group", "group", "group")
    gb, r3, nav = build("group-book", "group", "book")
    return [
        ("group numbering continues across a chapter's pages",
         lambda: r1.returncode == 0
         and 'id="fn3"' in read(gp, "html", "ch1--first-section.html")
         and 'id="fn4"' in read(gp, "html", "ch1--second-section.html")
         and 'id="fn1"' in read(gp, "html", "ch2.html")),
        ("with a value on each item so the browser numbers agree",
         lambda: 'value="4"' in read(gp, "html", "ch1--second-section.html")),
        ("group placement gathers the notes on the chapter's last page",
         lambda: r2.returncode == 0
         and "footnotes" not in read(gg, "html", "ch1.html")
         and read(gg, "html", "ch1--second-section.html").count('<li id="fn')
         == 4),
        ("and references cross to them, notes link back",
         lambda: 'href="ch1--second-section.html#fn1"' in read(gg, "html",
                                                                "ch1.html")
         and 'href="ch1.html#fnref1"' in read(gg, "html",
                                              "ch1--second-section.html")),
        # The fixture .docx pages are in the book too and form groups of
        # one with no notes, so two groups have headings on the page.
        ("book placement makes a Notes page with a heading per group",
         lambda: r3.returncode == 0
         and read(gb, "html", "notes.html").count("<h2>") == 2
         and re.search(r'id="g\d+-fn1"', read(gb, "html", "notes.html"))),
        ("and the EPUB gets a Notes chapter",
         lambda: ">Notes<" in nav),
        ("no reference or return link is left dangling in any of them",
         lambda: not any(re.search(r"link-to-missing|duplicate-id",
                                   r.stderr) for r in (r1, r2, r3))),
    ]


BOOK = {
    "_preamble.md": "---\ntitle: The Book\n---\n\nAn epigraph.\n\n\\frontmatter\n\n"
                    "# To the Reader\n\nHello.\n\n# Thanks\n\nTo all.\n\n"
                    "\\mainmatter\n",
    "01 One.md": "# Chapter One\n\nIntro.\n\n## First\n\nA.\n\n## Second\n\nB.\n",
    "02 Two.md": "# Chapter Two\n\n## Only\n\nC.\n",
    "A1 Extra.md": "# Extra Material {.appendix}\n\n## Details\n\nD.\n",
    "Z1 Glossary.md": "\\backmatter\n\n# Glossary {-}\n\nTerms.\n",
}


def case_structure(work):
    """Roles from the source's markers, numbering, and a generated
    contents page."""
    import yaml
    os.makedirs(work, exist_ok=True)
    for name, text in BOOK.items():
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    # First run: no contents, so the guess reads the markers.
    first = convert(work, "defaults:\n  pages:\n    split_level: 2\n"
                          "targets:\n  html:\n    format: html\n"
                          "  epub:\n    format: epub3\n")
    sample = yaml.safe_load(open(os.path.join(work, "packaging-sample.yaml"),
                                 encoding="utf-8"))["project"]["contents"]
    roles = {str(n.get("title", n.get("page"))): n.get("role")
             for n in sample if isinstance(n, dict)}
    # Second run: adopt it, number the book, and ask for a contents page.
    for n in sample:
        if isinstance(n, dict) and n.get("role") == "front":
            n["items"].insert(0, {"generate": "toc"})
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        yaml.safe_dump({"project": {"identifier": "org.example.fixtures",
                                    "title": "The Book", "numbering": True,
                                    "contents": sample}}, fh, sort_keys=False)
    second = subprocess.run(
        ["python3", os.path.join(BIN, "convert.py"), "--quiet"], cwd=work,
        capture_output=True, text=True, stdin=subprocess.DEVNULL)
    toc = read(work, "html", "toc.html") if exists(work, "html", "toc.html") \
        else ""
    entries = re.findall(r'<li><a href="([^"]*)">([^<]*)</a>', toc)
    import zipfile
    nav = ""
    e = os.path.join(work, "epub", "org.example.fixtures.epub")
    if os.path.exists(e):
        with zipfile.ZipFile(e) as z:
            nav = z.read("EPUB/nav.xhtml").decode("utf-8")
    manifest = read(work, "imsmanifest.xml") if exists(work,
                                                       "imsmanifest.xml") else ""
    return [
        ("the runs succeed", lambda: first.returncode == 0
         and second.returncode == 0),
        ("the guess reads \\frontmatter, {.appendix}, and \\backmatter",
         lambda: roles.get("The Book") == "front"
         and roles.get("Extra Material") == "appendix"
         and roles.get("Z1-Glossary") == "back"),
        ("the contents page numbers chapters, sections, and appendices",
         lambda: ("01-One.html", "1 Chapter One") in entries
         and ("01-One--first.html", "1.1 First") in entries
         and ("A1-Extra--details.html", "A.1 Details") in entries),
        ("and leaves front and back matter unnumbered",
         lambda: any(t == "To the Reader" for _, t in entries)
         and any(t == "Glossary" for _, t in entries)),
        ("a chapter's opening page is its group line, not a second entry",
         lambda: [t for _, t in entries if t == "1 Chapter One"] ==
         ["1 Chapter One"]),
        ("the EPUB's nav carries the numbers",
         lambda: ">1 Chapter One<" in nav and ">A Extra Material<" in nav
         and ">Contents<" in nav),
        ("and back matter declared by \\backmatter in an unsplit page is "
         "not numbered",
         lambda: ">Glossary<" in nav
         and not re.search(r">\d+ Glossary<", nav)),
        ("and so does the cartridge organization",
         lambda: "<title>1 Chapter One</title>" in manifest
         and "<title>A.1 Details</title>" in manifest),
        ("the output check finds no dead link in the contents page",
         lambda: "link-to-missing" not in second.stderr),
    ]


EDITIONS = {
    "about.md": "# About This Book\n\nFor every edition.\n",
    "about.print.md": "# About This Book\n\nFor the print edition only.\n",
    "access.md": ("# Accessibility\n\nChecked. See [about](https://openstax.org"
                  "/books/x/pages/about#here) and [not ours](https://openstax.org"
                  "/books/x/pages/elsewhere).\n\n"
                  "::: {targets=\"web\"}\nUse the web edition with a screen "
                  "reader.\n:::\n\n::: {targets=\"!web\"}\nThis edition was "
                  "validated.\n:::\n"),
    "front.html": "<!DOCTYPE html><html lang=\"en\"><head><title>Front</title>"
                  "</head><body><h1>Front</h1><p>Web front.</p></body></html>\n",
    "front.print.html": "<!DOCTYPE html><html lang=\"en\"><head><title>Front"
                        "</title></head><body><h1>Front</h1><p>Print front."
                        "</p></body></html>\n",
    "titled.md": "---\ntitle: Titled\nsubtitle: A subtitle\n---\n\nBody.\n",
}


def case_editions(work):
    """Two editions from one directory: a variant file, a passage for
    some targets, a hand-written variant, and the title-block switch."""
    os.makedirs(work, exist_ok=True)
    for name, text in EDITIONS.items():
        # A finished page and its variant live in _pt/.
        if name.startswith("front"):
            name = os.path.join("_pt", name)
            os.makedirs(os.path.join(work, "_pt"), exist_ok=True)
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    result = convert(work, "targets:\n  web:\n    format: html\n"
                           "  print:\n    format: html\n"
                           "    title_block: \"off\"\n"
                           "  epub:\n    format: epub3\n")

    def page(target, stem):
        return read(work, target, stem + ".html") if exists(
            work, target, stem + ".html") else ""
    return [
        ("the run succeeds", lambda: result.returncode == 0),
        ("a publisher link to a page of the book points at the page here",
         lambda: 'href="about.html#here"' in page("web", "access")
         and "openstax.org/books/x/pages/elsewhere" in page("web", "access")),
        ("a variant file replaces the page for its target only",
         lambda: "For the print edition only." in page("print", "about")
         and "For every edition." in page("web", "about")),
        ("the variant is not a page of its own",
         lambda: not exists(work, "web", "about.print.html")
         and not exists(work, "print", "about.print.html")),
        ("a passage for some targets appears there and nowhere else",
         lambda: "with a screen reader" in page("web", "access")
         and "with a screen reader" not in page("print", "access")
         and "was validated" in page("print", "access")
         and "was validated" not in page("web", "access")),
        ("the targets attribute never reaches the output",
         lambda: "targets=" not in page("web", "access")),
        ("a hand-written variant is copied for its target",
         lambda: "Print front." in page("print", "front")
         and "Web front." in page("web", "front")),
        ("title_block off drops the subtitle for that target",
         lambda: "A subtitle" in page("web", "titled")
         and "A subtitle" not in page("print", "titled")),
    ]


def case_markdown_target(work):
    """Markdown written back as source: read again, it gives the same
    HTML; written again, it is the same file."""
    import filecmp
    first = os.path.join(work, "first")
    result = convert(first, "targets:\n  html:\n    format: html\n"
                            "  src:\n    format: markdown\n")
    second = os.path.join(work, "second")
    os.makedirs(second, exist_ok=True)
    for name in os.listdir(os.path.join(first, "src")):
        src = os.path.join(first, "src", name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(second, name), dirs_exist_ok=True)
        else:
            shutil.copy(src, os.path.join(second, name))
    for name in ("project.yaml", "conversion.yaml"):
        shutil.copy(os.path.join(first, name), os.path.join(second, name))
    again = subprocess.run(
        ["python3", os.path.join(BIN, "convert.py"), "--quiet"], cwd=second,
        capture_output=True, text=True, stdin=subprocess.DEVNULL)
    compare = subprocess.run(
        ["python3", os.path.join(ROOT, "util", "compare-output.py"),
         os.path.join(first, "html"), os.path.join(second, "html")],
        capture_output=True, text=True)
    # A source from Word settles after one write (Word's whitespace,
    # grid-table widths rounded to characters); the second write is the
    # fixed point, so the third must equal it.
    third = os.path.join(work, "third")
    os.makedirs(third, exist_ok=True)
    for name in os.listdir(os.path.join(second, "src")):
        src = os.path.join(second, "src", name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(third, name), dirs_exist_ok=True)
        else:
            shutil.copy(src, os.path.join(third, name))
    for name in ("project.yaml", "conversion.yaml"):
        shutil.copy(os.path.join(first, name), os.path.join(third, name))
    subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quiet"],
                   cwd=third, capture_output=True, text=True,
                   stdin=subprocess.DEVNULL)
    mds = [n for n in os.listdir(os.path.join(first, "src"))
           if n.endswith(".md")]
    same = [n for n in mds if filecmp.cmp(os.path.join(second, "src", n),
                                          os.path.join(third, "src", n),
                                          shallow=False)]
    md = read(first, "src", "tables.md")
    return [
        ("a markdown target writes one file per source",
         lambda: result.returncode == 0 and len(mds) == len(NEEDED)),
        ("the row-header table carries its marker and Word's exact widths, "
         "the caption stays",
         lambda: re.search(r"::: \{\.matrix widths=\"[0-9. ]+\"\}", md)
         and ": Table 1.1" in md),
        ("tables are pipe tables, so no width is rounded to a character",
         lambda: "|---" in md or "|:--" in md or "|--" in md),
        ("the first write is already the fixed point for a widths table",
         lambda: filecmp.cmp(os.path.join(first, "src", "tables-b.md"),
                             os.path.join(second, "src", "tables-b.md"),
                             shallow=False)),
        ("no scope, wrapper, or bookkeeping reaches the Markdown",
         lambda: "scope=" not in md and "table-wrapper" not in md
         and "data-th" not in md),
        ("read back as a book, the Markdown gives the same HTML",
         lambda: again.returncode == 0 and "Runs agree" in compare.stdout),
        ("the second write is the fixed point: the third equals it",
         lambda: len(same) == len(mds)),
    ]


MERGE_BOOK = {
    "ch1.md": ("# Chapter One\n\nIntro.\n\n## First\n\nA. See "
               "[Second](ch1--second.html) and [Two](ch2.html).\n\n"
               "### Deeper\n\nD.\n\n## Second\n\n[]{#dup}B [x](#dup).\n"),
    "ch2.md": "# Chapter Two\n\n## Only\n\n[]{#dup}C [y](#dup).\n",
}


def case_merge(work):
    """A markdown target that merges: one file per chapter."""
    os.makedirs(work, exist_ok=True)
    for name, text in MERGE_BOOK.items():
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    result = convert(work, "defaults:\n  pages:\n    split_level: 2\n"
                           "targets:\n  src:\n    format: markdown\n"
                           "    merge: groups\n")
    one = read(work, "src", "ch1.md") if exists(work, "src", "ch1.md") else ""
    two = read(work, "src", "ch2.md") if exists(work, "src", "ch2.md") else ""
    levels = [len(m.group(1)) for m in re.finditer(r"^(#+) ", one, re.M)]
    return [
        ("the run succeeds", lambda: result.returncode == 0),
        ("a chapter's pages come back as one file",
         lambda: one and two
         and not exists(work, "src", "ch1--first.md")),
        ("the file is titled for the chapter, its pages are sections",
         lambda: "title: Chapter One" in one
         and "## First {#ch1--first}" in one),
        ("nesting follows the book, not the page count",
         lambda: levels == [2, 3, 2]),
        ("a link to a merged page becomes a link inside the file",
         lambda: "](#ch1--second)" in one),
        # ch2 kept no page of its own, so a link to it lands on its first
        # piece, which the merge then finds inside ch2.md.
        ("a link to another file names that file, where its target went",
         lambda: "](ch2.md#ch2--only)" in one),
        ("two groups from one source get a file each, not one file",
         lambda: len([n for n in os.listdir(os.path.join(work, "src"))
                      if n.endswith(".md")]) >= 2),
        ("an id two pages shared is renamed, and its page's link follows",
         lambda: one.count("#dup)") == 1 and two.count("#dup)") == 1),
    ]


CASES = [
    ("a bare directory", case_bare),
    ("a markdown target that merges", case_merge),
    ("a Markdown target, round trip", case_markdown_target),
    ("two editions from one directory", case_editions),
    ("roles, numbering, and a contents page", case_structure),
    ("footnote numbering and placement", case_notes),
    ("a Markdown source", case_markdown),
    ("an HTML source", case_html_source),
    ("an AsciiDoc source", case_asciidoc),
    ("two files, one page", case_stem_collisions),
    ("adopting a split book's pages", case_adopt),
    ("an HTML source's tables and the header sidecar", case_html_headers),
    ("a menu for pages posted as a site", case_menu),
    ("raw HTML in a Markdown source", case_markdown_html),
    ("title rows and bands, split and grouped", case_bands),
    ("compare-output sees lists and blockquotes", case_compare_blocks),
    ("a web archive converted directly", case_warc_direct),
    ("a Common Cartridge", case_cartridge),
    ("a plain zip of a book's files", case_zip),
    ("formulas as MathJax 2 drew them", case_mathjax2),
    ("AsciiDoc layout attributes", case_asciidoc_layout),
    ("formats not yet implemented", case_not_implemented),
    ("ids with spaces in HTML sources", case_html_ids),
    ("decorative images and frame sizes in HTML sources", case_html_images),
    ("AsciiDoc to Markdown and back", case_asciidoc_markdown),
    ("a hand-written page", case_hand_written),
    ("several targets", case_targets),
    ("arguments passed to the packager", case_passthrough),
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
