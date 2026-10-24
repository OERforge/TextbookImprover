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

import argparse
import csv
import html as html_lib
import glob
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
sys.path.insert(0, HERE)
import parallel  # noqa: E402
NEEDED = ["metadata", "tables", "tables-b", "media-a", "math"]

MULTI = """\
targets:
  html:
    format: html
    output_dir: .
  print:
    format: html
    header: "A *course* banner."
    footer: "Printed edition."
  wide:
    format: html
    archive: zip
    tables:
      wrap: false
  epub:
    format: epub3
"""


def convert(work, config=None, project=True, arguments=(), fixtures=NEEDED):
    """convert.py in work, with the Word fixtures named (all five unless a
    case says), the configuration given, and a project.yaml naming the
    book unless project is false."""
    os.makedirs(work, exist_ok=True)
    for name in fixtures:
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
        ["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"]
        + list(arguments), cwd=work, capture_output=True, text=True,
        stdin=subprocess.DEVNULL)


def walk_json(node):
    """Every element of a Pandoc JSON document, depth first."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk_json(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk_json(value)


def exists(*parts):
    return os.path.exists(os.path.join(*parts))


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


def epubcheck(path):
    """epubcheck's findings for the EPUB at path, run here, since the
    suite's runs leave the validators out (--quick): None, and a skip
    said, where epubcheck isn't installed or there's no EPUB."""
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import outputcheck
    command = outputcheck.find_validator("epubcheck")
    if not command:
        print("  skip  epubcheck not installed (EPUBCHECK_JAR)")
        return None
    return outputcheck.run_epubcheck(command, path) if os.path.exists(path) else None


def case_bare(work):
    """No configuration at all: one page per document, in html/."""
    result = convert(work, config=None, project=False)
    return [
        ("a bare directory converts into html/",
         lambda: all(exists(work, "html", n + ".html") for n in NEEDED)
         and not exists(work, "tables.html")),
        ("and stops at the project's sample, as a first run does, with the "
         "commands for the other two",
         lambda: result.returncode != 0
         and exists(work, "project-sample.yaml")
         and not exists(work, "packaging-sample.yaml")
         and "--init    writes packaging-sample.yaml" in result.stderr
         and "--init    writes conversion-sample.yaml" in result.stderr),
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
                     arguments=["--zip"], fixtures=())
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
        ("--zip, which the driver doesn't know, reaches the packager",
         lambda: exists(work, "org.example.fixtures.imscc")),
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
         lambda: "Output check: 2 page(s)" in result.stderr),
    ]


def case_targets(work):
    """Four targets: three HTML renderings and an EPUB."""
    result = convert(work, MULTI, fixtures=("tables", "media-a"))
    return [
        ("the run succeeds", lambda: result.returncode == 0),
        ("the html target writes beside the sources when told to",
         lambda: exists(work, "tables.html")),
        ("a second html target writes into its own directory",
         lambda: exists(work, "print", "tables.html")),
        ("with its footer",
         lambda: "Printed edition." in read(work, "print", "tables.html")
         and "Printed edition." not in read(work, "tables.html")),
        ("a page's own content is its main landmark, its header setting a "
         "banner before it and its footer setting a contentinfo landmark "
         "after it, and a page with neither has its main landmark alone",
         lambda: re.search(r"<body>\s*<header>\s*<p>A <em>course</em> banner\.</p>"
                           r"\s*</header>\s*<main>\s*<h1", read(work, "print", "tables.html"))
         and re.search(r"</main>\s*<footer>\s*<p>Printed edition\.</p>\s*</footer>"
                       r"\s*</body>", read(work, "print", "tables.html"))
         and re.search(r"<body>\s*<main>\s*<h1", read(work, "tables.html"))
         and re.search(r"</main>\s*</body>", read(work, "tables.html"))
         and all(read(*parts).count("<main>") == 1 for parts in (
             (work, "print", "tables.html"), (work, "tables.html")))),
        ("and the banner looks as it did as a paragraph, not centered over a "
         "wide space as Pandoc's stylesheet has a header",
         lambda: re.search(r"body > header \{\s*margin-bottom: 0;\s*text-align: inherit;",
                           read(work, "print", "tables.html"))),
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
        ("its archive holds its pages, not the intermediates kept in its folder",
         lambda: (lambda names: "wide/tables.html" in names
                  and not any(n.startswith("wide/intermediates") for n in names))(
             zipfile.ZipFile(os.path.join(work, "wide.zip")).namelist()
             if exists(work, "wide.zip") else [])),
        ("the epub target builds",
         lambda: exists(work, "epub", "org.example.fixtures.epub")),
        ("the reports are written once, for the book",
         lambda: exists(work, "image-alt-missing.csv")
         and not exists(work, "print", "image-alt-missing.csv")),
        ("the output check covers every target's pages",
         lambda: re.search(r"Output check: 6 page\(s\) and 1 EPUB",
                           result.stderr)),
        ("the packager packages the target beside the sources",
         lambda: exists(work, "imsmanifest.xml")),
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
                           "  epub:\n    format: epub3\n", fixtures=("tables",))
    # "long run.md" is the page long-run: no space reaches an href.
    page = read(work, "html", "long-run.html") if exists(
        work, "html", "long-run.html") else ""
    section = read(work, "html", "long-run--economies-of-scale.html") \
        if exists(work, "html", "long-run--economies-of-scale.html") else ""
    validated = epubcheck(os.path.join(work, "epub", "org.example.fixtures.epub"))
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
        ["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"],
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
    result = convert(work, "targets:\n  html:\n    format: html\n", fixtures=())
    one = read(work, "html", "one.html") if exists(work, "html",
                                                    "one.html") else ""
    import yaml
    sample = yaml.safe_load(read(work, "project-sample.yaml"))["project"] \
        if exists(work, "project-sample.yaml") else {}
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
        ("the master's order is offered as contents in the project's sample",
         lambda: sample.get("contents") == ["one", "two"]),
        ("and its authors and language with it, the title project.yaml "
         "gives kept",
         lambda: sample.get("title") == "The Fixture Book"
         and sample.get("authors") == ["Ann Author", "Bo Writer"]
         and sample.get("language") == "en-GB"),
        ("a mailto: link keeps its scheme; a scheme in code is code, not a "
         "link",
         lambda: 'href="mailto:ann@example.org"' in read(work, "html",
                                                         "two.html")
         and "<code>ftp://</code>" in read(work, "html", "two.html")
         and 'href="ftp://"' not in read(work, "html", "two.html")),
    ]


def case_lowercase_names(work):
    """media.lowercase: each file a page names copied under its name in
    lowercase and named so, beside an html target's pages and in a
    markdown target's copy, where the rest of each name is the author's;
    a target without it keeps the names; and two files whose names
    differ only in case stop the run before anything is written."""
    def book(name, files, targets="  html:\n    format: html\n  md:\n    format: markdown\n"
                                   "  plain:\n    format: html\n    media:\n"
                                   "      lowercase: false\n"):
        where = os.path.join(work, name)
        for path, data in files.items():
            os.makedirs(os.path.dirname(os.path.join(where, path)), exist_ok=True)
            with open(os.path.join(where, path), "wb") as fh:
                fh.write(data)
        return where, convert(where, "defaults:\n  media:\n    lowercase: true\ntargets:\n"
                              + targets, fixtures=())
    a, run = book("lower", {
        "page.md": b"# Page\n\n![A rising line](Assets/Fig1.PNG)\n\n![Two dots](Assets/My%20Pic.png)"
                   b"\n\nThe [handout](Docs/Handout.PDF).\n",
        "Assets/Fig1.PNG": ONE_PIXEL, "Assets/My Pic.png": ONE_PIXEL + b"\0",
        "Docs/Handout.PDF": b"%PDF-1.4\n%%EOF\n"})
    b, clash = book("clash", {
        "page.md": b"# Page\n\n![One](Assets/Fig1.PNG)\n\n![Two](Assets/fig1.png)\n",
        "Assets/Fig1.PNG": ONE_PIXEL, "Assets/fig1.png": ONE_PIXEL + b"\0"})
    # Two files a page links to, as a target copies them too.
    e, linked = book("linked", {
        "page.md": b"# Page\n\nThe [first data](Data/Results.csv) and the "
                   b"[second](Data/results.csv).\n",
        "Data/Results.csv": b"a,b\n", "Data/results.csv": b"x,y\n"})
    # A target that copies no files under their names: nothing to stop.
    f, unnamed = book("epub-only", {
        "page.md": b"# Page\n\n![One](Assets/Fig1.PNG)\n\n![Two](Assets/fig1.png)\n",
        "Assets/Fig1.PNG": ONE_PIXEL, "Assets/fig1.png": ONE_PIXEL + b"\0"},
        "  book:\n    format: epub3\n")
    page = read(a, "html", "page.html") if exists(a, "html", "page.html") else ""
    copy = read(a, "md", "page.md") if exists(a, "md", "page.md") else ""
    plain = read(a, "plain", "page.html") if exists(a, "plain", "page.html") else ""
    # Pages written beside the sources, where the name in lowercase is
    # the source's own file, as a file system that ignores case finds it,
    # and the page names it both ways: a second name for the file stands
    # in for such a file system here.
    c = os.path.join(work, "beside")
    os.makedirs(os.path.join(c, "Assets"))
    os.makedirs(os.path.join(c, "assets"))
    with open(os.path.join(c, "Assets", "Fig1.PNG"), "wb") as fh:
        fh.write(ONE_PIXEL)
    os.link(os.path.join(c, "Assets", "Fig1.PNG"), os.path.join(c, "assets", "fig1.png"))
    with open(os.path.join(c, "page.md"), "w", encoding="utf-8") as fh:
        fh.write("# Page\n\n![A rising line](Assets/Fig1.PNG)\n\n![Again](assets/fig1.png)\n")
    with open(os.path.join(c, "more.md"), "w", encoding="utf-8") as fh:
        fh.write("# More\n\n![A rising line](Assets/Fig1.PNG)\n")
    beside = convert(c, "defaults:\n  media:\n    lowercase: true\ntargets:\n  html:\n"
                        "    format: html\n    output_dir: .\n", fixtures=())
    return [
        ("an html target copies each file a page names under its name in lowercase, and names "
         "it so",
         lambda: run.returncode == 0
         and all(exists(a, "html", *p.split("/"))
                 for p in ("assets/fig1.png", "assets/my-pic.png", "docs/handout.pdf"))
         and all(f'="{p}"' in page
                 for p in ("assets/fig1.png", "assets/my-pic.png", "docs/handout.pdf"))),
        ("a markdown target too, the rest of each name the author's",
         lambda: all(exists(a, "md", *p.split("/"))
                     for p in ("assets/fig1.png", "assets/my pic.png", "docs/handout.pdf"))
         and all(f"({p})" in copy
                 for p in ("assets/fig1.png", "assets/my%20pic.png", "docs/handout.pdf"))),
        ("a target without it keeps the names",
         lambda: exists(a, "plain", "Assets", "Fig1.PNG") and 'src="Assets/Fig1.PNG"' in plain
         and not exists(a, "plain", "assets")),
        ("where the name in lowercase is the source's own file beside the pages, it's one "
         "file, left as it is, and the run says a server that tells case apart won't find it",
         lambda: beside.returncode == 0
         and "WARNING: 1 file(s)" in beside.stdout + beside.stderr
         and "(Assets/Fig1.PNG)" in beside.stdout + beside.stderr
         and "a server that doesn't ignore case won't find them" in beside.stdout + beside.stderr
         and os.path.samefile(os.path.join(c, "Assets", "Fig1.PNG"),
                              os.path.join(c, "assets", "fig1.png"))),
        ("two files whose names differ only in case stop the run, nothing written, files a "
         "page links to as well as its images",
         lambda: clash.returncode != 0
         and "would both be written as assets/fig1.png" in clash.stdout + clash.stderr
         and not exists(b, "html")
         and linked.returncode != 0
         and "would both be written as data/results.csv" in linked.stdout + linked.stderr
         and not exists(e, "html")),
        ("but not in a run whose targets copy no files under their names",
         lambda: unnamed.returncode == 0 and exists(f, "book")),
    ]


def case_downsample(work):
    """images.downsample: at 0, the default, the run says how many images
    are wider in pixels than the pages show them, and by how much the
    widest; set, an html, an EPUB, and a Word target carry copies scaled
    down to that many times the width shown, which is the page's width, a
    percentage of the column, or a height and the image's proportions,
    while a markdown target and the original keep the author's file; a
    copy of a drawing, an original of few colors, has a palette of 256,
    its transparency kept, an alpha channel's or an RGB PNG's transparent
    color's, and a photograph's its colors; and without
    Pillow, a run with it set stops and says what to install."""
    import random
    import struct
    import zlib
    try:
        from PIL import Image
    except ImportError:
        Image = None
    noise = random.Random(7)

    def png(path, width, height, palette=False):
        """A PNG of noise, which scaling makes smaller, written without an
        imaging library: RGB, or with a palette of 256 colors."""
        def chunk(kind, data):
            return (struct.pack(">I", len(data)) + kind + data
                    + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
        per = 1 if palette else 3
        raw = b"".join(b"\x00" + noise.randbytes(width * per) for _ in range(height))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8,
                                                  3 if palette else 2, 0, 0, 0))
                     + (chunk(b"PLTE", noise.randbytes(768)) if palette else b"")
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))

    def size(data):
        """A PNG's width and height, from its header."""
        return struct.unpack(">II", data[16:24]) if data[:8] == b"\x89PNG\r\n\x1a\n" else None

    def file_size(*parts):
        path = os.path.join(*parts)
        if not os.path.exists(path):
            return None
        with open(path, "rb") as fh:
            return size(fh.read(64))

    def zipped(path, folder):
        """The width and height of each PNG in a zip's folder."""
        if not os.path.exists(path):
            return []
        with zipfile.ZipFile(path) as z:
            return [size(z.read(n)) for n in z.namelist()
                    if n.startswith(folder) and n.endswith(".png")]

    page = ("# Page\n\n![A wide band of noise](assets/big.png){width=100px}\n\n"
            "![A long strip of noise](assets/strip.png){width=50%}\n\n"
            "![A small square](assets/small.png)\n")
    if Image is not None:
        page += ("\n![Colored noise](assets/colors.png){width=100px}\n\n"
                 "![A photograph of noise](assets/photo.jpg){height=50px}\n\n"
                 "![A drawing in eight colors](assets/drawing.png){width=100px}\n\n"
                 "![A drawing half clear](assets/clear.png){width=100px}\n\n"
                 "![A drawing half in a clear color](assets/key.png){width=100px}\n")

    def drawing(path, clear=False, key=False):
        """A drawing: squares of two pixels in eight flat colors, which a
        copy's smoothed edges give thousands, the left half's clear where
        clear says, in an alpha channel, or where key says, in white, the
        color an RGB PNG names as transparent (its tRNS chunk)."""
        from PIL import ImageDraw
        colors = [(230, 25, 75), (60, 180, 75), (255, 225, 25), (0, 130, 200),
                  (245, 130, 48), (145, 30, 180), (70, 240, 240), (0, 0, 0)]
        im = Image.new("RGBA" if clear else "RGB", (400, 200))
        pen = ImageDraw.Draw(im)
        for x in range(0, 400, 2):
            for y in range(0, 200, 2):
                color = colors[noise.randrange(8)]
                if clear:
                    color += (0 if x < 200 else 255,)
                elif key and x < 200:
                    color = (255, 255, 255)
                pen.rectangle((x, y, x + 1, y + 1), fill=color)
        im.save(path, **({"transparency": (255, 255, 255)} if key else {}))

    def book(name, config, env=None):
        where = os.path.join(work, name)
        png(os.path.join(where, "assets", "big.png"), 400, 200)
        png(os.path.join(where, "assets", "strip.png"), 800, 100)
        png(os.path.join(where, "assets", "small.png"), 4, 4)
        if Image is not None:
            png(os.path.join(where, "assets", "colors.png"), 400, 200, palette=True)
            Image.frombytes("RGB", (300, 150), noise.randbytes(300 * 150 * 3)).save(
                os.path.join(where, "assets", "photo.jpg"), quality=95)
            drawing(os.path.join(where, "assets", "drawing.png"))
            drawing(os.path.join(where, "assets", "clear.png"), clear=True)
            drawing(os.path.join(where, "assets", "key.png"), key=True)
        with open(os.path.join(where, "page.md"), "w", encoding="utf-8") as fh:
            fh.write(page)
        with open(os.path.join(where, "assets", "big.png"), "rb") as fh:
            original = fh.read()
        if env is None:
            return where, original, convert(where, config, fixtures=())
        with open(os.path.join(where, "conversion.yaml"), "w", encoding="utf-8") as fh:
            fh.write(config)
        with open(os.path.join(where, "project.yaml"), "w", encoding="utf-8") as fh:
            fh.write("project:\n  identifier: org.example.fixtures\n"
                     "  title: The Fixture Book\n")
        return where, original, subprocess.run(
            ["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"], cwd=where,
            capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env)

    every = ("  html:\n    format: html\n  epub:\n    format: epub3\n"
             "  word:\n    format: docx\n  md:\n    format: markdown\n")
    a, _, whole = book("whole", "targets:\n" + every)
    whole_said = whole.stdout + whole.stderr
    checks = [
        ("at 0, the default, the run says how many images are wider than they're shown, and "
         "the widest for its size, where the setting is documented",
         lambda: whole.returncode == 0
         and re.search(r"WARNING: \d image\(s\) are wider in pixels than the pages show them, "
                       r"\d of them more than twice as wide, up to 4\.0 times \(assets/big\.png, "
                       r"400 pixels shown 100 wide\); the outputs carry them whole", whole_said)
         and "docs/configuration.md#images-larger-than-theyre-shown" in whole_said
         and file_size(a, "html", "assets", "big.png") == (400, 200)),
    ]
    if Image is None:
        print("  skip  Pillow not installed (python3-pil); images aren't scaled")
        return checks

    # images.responsive drops an image's height, which the pages then show
    # at its own width: with it off, the height is the photograph's size.
    b, original, scaled = book("scaled", "defaults:\n  images:\n    downsample: 2\n"
                                         "    responsive: false\n"
                                         "targets:\n" + every
                               + "  full:\n    format: html\n    images:\n"
                                 "      downsample: 0\n")
    said = scaled.stdout + scaled.stderr
    epub = os.path.join(b, "epub", "org.example.fixtures.epub")
    words = glob.glob(os.path.join(b, "word", "*.docx"))

    def opened(*parts):
        path = os.path.join(b, *parts)
        if not os.path.exists(path):
            return None
        with Image.open(path) as im:
            return im.format, im.mode, im.size

    def alpha(*parts):
        """The opacity of a copy's pixels at the left and at the right."""
        path = os.path.join(b, *parts)
        if not os.path.exists(path):
            return None
        with Image.open(path) as im:
            im = im.convert("RGBA")
            return im.getpixel((10, 50))[3], im.getpixel((190, 50))[3]

    # A Python that can't import Pillow, which a folder named PIL whose
    # import fails stands in for.
    blocked = os.path.join(work, "no-pillow")
    os.makedirs(os.path.join(blocked, "PIL"))
    with open(os.path.join(blocked, "PIL", "__init__.py"), "w") as fh:
        fh.write("raise ImportError('Pillow is blocked here')\n")
    c, _, without = book("without", "defaults:\n  images:\n    downsample: 2\n"
                                    "targets:\n  html:\n    format: html\n",
                         env=dict(os.environ, PYTHONPATH=blocked))
    d, _, unscaled = book("unscaled", "targets:\n  html:\n    format: html\n",
                          env=dict(os.environ, PYTHONPATH=blocked))
    return checks + [
        ("set to 2, an html target carries a copy at twice the width it's shown, a width in "
         "pixels, a percentage of the column (36em), or a height and the image's proportions",
         lambda: scaled.returncode == 0
         and file_size(b, "html", "assets", "big.png") == (200, 100)
         and file_size(b, "html", "assets", "strip.png") == (576, 72)
         and opened("html", "assets", "photo.jpg") == ("JPEG", "RGB", (200, 100))),
        ("an image no wider than that is copied as it is, and a palette's image has a "
         "palette again",
         lambda: file_size(b, "html", "assets", "small.png") == (4, 4)
         and opened("html", "assets", "colors.png") == ("PNG", "P", (200, 100))),
        ("a drawing's copy has a palette, a drawing's with transparency too, in an alpha "
         "channel or a transparent color, its clear half still clear, and a photograph's "
         "keeps its colors",
         lambda: opened("html", "assets", "drawing.png") == ("PNG", "P", (200, 100))
         and opened("html", "assets", "clear.png") == ("PNG", "P", (200, 100))
         and opened("html", "assets", "key.png") == ("PNG", "P", (200, 100))
         # The palette's opaque colors may hold an edge's alpha in their
         # average: 254 measured, where the original's is 255.
         and all((lambda a: a is not None and a[0] < 8 and a[1] > 247)(
             alpha("html", "assets", name)) for name in ("clear.png", "key.png"))
         and opened("html", "assets", "big.png") == ("PNG", "RGB", (200, 100))),
        ("the EPUB and the Word file carry the copies",
         lambda: (200, 100) in zipped(epub, "EPUB/media/")
         and (400, 200) not in zipped(epub, "EPUB/media/")
         and len(words) == 1
         and (200, 100) in zipped(words[0], "word/media/")
         and (400, 200) not in zipped(words[0], "word/media/")),
        ("the original stays as it is, and so does a markdown target's copy, the author's",
         lambda: open(os.path.join(b, "assets", "big.png"), "rb").read() == original
         and open(os.path.join(b, "md", "assets", "big.png"), "rb").read() == original),
        ("the run says how many it scaled and how many of them were drawings given a "
         "palette, and a target set to 0 is named as carrying them whole",
         lambda: re.search(r"images\.downsample 2: 7 of 8 image\(s\) scaled down to 2 times "
                           r"the width they're shown at, [\d.]+ [kM]B to [\d.]+ [kM]B, 3 of "
                           r"them drawings given a palette of 256 colors\.", said)
         and "the outputs (full) carry them whole" in said
         and file_size(b, "full", "assets", "big.png") == (400, 200)),
        ("without Pillow, a run with it set stops before writing and says what to install; "
         "at 0 the run measures without it",
         lambda: without.returncode != 0
         and "images.downsample needs Python's Pillow" in without.stdout + without.stderr
         and "sudo apt install python3-pil" in without.stdout + without.stderr
         and not exists(c, "html", "page.html")
         and unscaled.returncode == 0
         and "up to 4.0 times (assets/big.png" in unscaled.stdout + unscaled.stderr),
    ]


def case_white_marks(work):
    """White space with nothing to show (figures-and-tables.lua): an
    editor's subscript holding only a space, which Pandoc's HTML reader
    makes an empty subscript between two spaces, is one space, on the page
    and in the Word file, which had shown two, as is a link holding only a
    space, which the filter drops, emphasis holding only such a link, and
    an emphasized space at a subscript's end, inside bold or not; a
    superscript holding a no-break space is the space; no mark is emptied
    to make two spaces one, so a span with a style holding only a space
    keeps it, while one holding words loses the space at its end beside
    another, outside it or at the start of the next span; and a table's
    cell holding only a no-break space is empty, where a PDF had a space
    character for it."""
    os.makedirs(work, exist_ok=True)
    with open(os.path.join(work, "marks.html"), "w", encoding="utf-8") as fh:
        fh.write("<!DOCTYPE html>\n<html lang=\"en\"><head><title>Marks</title></head><body>\n"
                 "<h1>Marks</h1>\n"
                 "<p>Here S<sub>mb</sub><sub><em> </em></sub>= 0, and x<sup>&nbsp;</sup>y.</p>\n"
                 "<p>As shown in<a href=\"https://example.org/x\"> </a>Figure 2, and "
                 "<em><a href=\"https://example.org/y\"> </a></em> Figure 3.</p>\n"
                 "<p>And A<sub><em>SX</em><em> </em></sub>is 0.41, and "
                 "B<sub><strong><em>SX</em><em> </em></strong></sub>is 0.5.</p>\n"
                 "<p>The value <span style=\"color:#000000;\"> </span> is 0.6, and "
                 "<span style=\"color:#000000;\">red </span> is 0.7, <span style=\"color:#000000;\">"
                 "and so </span><span style=\"color:#000000;\"> on</span>.</p>\n"
                 "<table><caption>Values</caption>\n"
                 "<tr><th>z</th><th>0.00</th><th>0.01</th></tr>\n"
                 "<tr><td>3.0</td><td>0.00135</td><td>&nbsp;</td></tr>\n"
                 "</table>\n</body></html>\n")
    result = convert(work, "targets:\n  html:\n    format: html\n"
                           "  word:\n    format: docx\n", fixtures=())
    page = read(work, "html", "marks.html") if exists(work, "html", "marks.html") else ""
    words = glob.glob(os.path.join(work, "word", "*.docx"))
    said = ""
    if words:
        with zipfile.ZipFile(words[0]) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        # The Word file's text, a paragraph a line.
        said = "\n".join("".join(re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", p))
                         for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S))
    return [
        ("a subscript holding only a space is the space alone, on the page",
         lambda: result.returncode == 0
         and "S<sub>mb</sub> = 0" in page and "<sub></sub>" not in page
         and "<sub><em></em></sub>" not in page and "<sup>" not in page
         and "<em></em>" not in page),
        ("and in the Word file one space, where Pandoc's writer gave its two a run each, "
         "and one where a link held only a space, inside emphasis or not, or a subscript "
         "ended in an emphasized one, inside bold or not",
         lambda: "Here Smb = 0, and x\u00a0y." in said
         and "As shown in Figure 2, and Figure 3." in said
         and "And ASX is 0.41, and BSX is 0.5." in said),
        ("no mark is emptied to make two spaces one: a span with a style holding only a "
         "space keeps it, and one holding a word loses the space at its end, beside "
         "another outside it or at the start of the next span",
         lambda: re.search(r'<span\s+style="color:#000000;"> </span>', page) is not None
         and re.search(r'<span\s+style="color:#000000;">red</span> is 0\.7', page) is not None
         and "and red is 0.7, and so on." in said),
        ("a table's cell holding only a no-break space is empty",
         lambda: re.search(r"<td>0\.00135</td>\s*<td></td>", page) is not None
         and "\u00a0</td>" not in page and "&nbsp;</td>" not in page),
    ]


def case_linked_paths(work):
    """A link to a file beside the pages that names it with backslashes,
    as only Windows resolves it, or in another case, as macOS and Windows
    find it, is read as the file, as an image is, from a Markdown, an
    HTML, an AsciiDoc, and a Word source, and an HTML page's variant for a
    target: the file is copied beside the page and the page links to it,
    its fragment kept, and the run says so. On a295ec3, the packager
    stopped the run, the files not found."""
    os.makedirs(os.path.join(work, "Docs"))
    os.makedirs(os.path.join(work, "Data"))
    files = {"Docs/Handout.pdf": b"%PDF-1.4\n%%EOF\n", "Data/Results.csv": b"a,b\n",
             "notes.pdf": b"%PDF-1.4\n%%EOF\n"}
    pages = {
        "md.md": "# Markdown\n\nThe [handout](docs/handout.PDF), its [second page]"
                 "(docs/handout.PDF#page=2), the [data](Data\\Results.csv), and the "
                 "[notes](notes.pdf). And [the HTML page](html.html).\n",
        "html.html": '<!DOCTYPE html><html lang="en"><head><title>HTML</title></head><body>'
                     '<h1>HTML</h1><p>The <a href="Docs\\Handout.pdf">handout</a> and the '
                     '<a href="DATA/results.csv">data</a>.</p></body></html>\n',
        "adoc.adoc": "= AsciiDoc\n\nThe link:DOCS/HANDOUT.pdf[handout].\n",
        "html.print.html": '<!DOCTYPE html><html lang="en"><head><title>HTML</title></head>'
                           '<body><h1>HTML</h1><p>The printed <a href="docs/HANDOUT.pdf">'
                           'handout</a>.</p></body></html>\n',
    }
    for path, data in files.items():
        with open(os.path.join(work, path), "wb") as fh:
            fh.write(data)
    for path, text in pages.items():
        with open(os.path.join(work, path), "w", encoding="utf-8") as fh:
            fh.write(text)
    subprocess.run(["pandoc", "-f", "markdown", "-o", os.path.join(work, "word.docx")],
                   input="# Word\n\nThe [handout](docs/HANDOUT.PDF).\n", text=True,
                   capture_output=True)
    result = convert(work, "targets:\n  html:\n    format: html\n  print:\n    format: html\n",
                     fixtures=())
    page = {stem: read(work, "html", stem + ".html") if exists(work, "html", stem + ".html")
            else "" for stem in ("md", "html", "adoc", "word")}
    printed = read(work, "print", "html.html") if exists(work, "print", "html.html") else ""
    said = result.stdout + result.stderr
    return [
        ("the run succeeds", lambda: result.returncode == 0),
        ("each source's link to a file named in another case, or with backslashes, links "
         "to the file, which is copied beside the pages",
         lambda: all('href="Docs/Handout.pdf"' in page[stem] for stem in page)
         and 'href="Data/Results.csv"' in page["md"] and 'href="Data/Results.csv"' in page["html"]
         and exists(work, "html", "Docs", "Handout.pdf")
         and exists(work, "html", "Data", "Results.csv")),
        ("a variant's too, for its target",
         lambda: 'href="Docs/Handout.pdf"' in printed and "The printed" in printed
         and exists(work, "print", "Docs", "Handout.pdf")),
        ("a link's fragment is kept",
         lambda: 'href="Docs/Handout.pdf#page=2"' in page["md"]),
        ("a link that names its file is as it was",
         lambda: 'href="notes.pdf"' in page["md"] and exists(work, "html", "notes.pdf")),
        # A page is the split's and the packager's: copied as a file, the
        # source would replace the page made of it.
        ("and a link to a page is to the page, not a copy of its source",
         lambda: 'href="html.html"' in page["md"]
         and 'name="generator" content="pandoc' in page["html"]),
        ("the run names each link it read so",
         lambda: said.count(", a path only Windows resolves; read as ") == 2
         and said.count(", a name in another case, which macOS and Windows find and a "
                        "server that tells case apart doesn't") == 6
         and "md.md links to docs/handout.PDF#page=2, and the file is Docs/Handout.pdf" in said
         and "word.docx links to docs/HANDOUT.PDF" in said
         and "html.print.html links to docs/HANDOUT.pdf" in said),
    ]


def case_stem_collisions(work):
    """Two files that would be one page stop the run, and an image's alt
    text isn't lent to a file that merely shares its stem. (An .md beside
    its .docx, v0.1's leftover, is no clash: a Markdown source's case.)"""
    def book(name, files, config="targets:\n  html:\n    format: html\n"):
        where = os.path.join(work, name)
        for path, text in files.items():
            os.makedirs(os.path.dirname(os.path.join(where, path)) or where,
                        exist_ok=True)
            mode = "wb" if isinstance(text, bytes) else "w"
            with open(os.path.join(where, path), mode) as fh:
                fh.write(text)
        return where, convert(where, config, fixtures=())
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
                  "targets:\n  html:\n    format: html\n", fixtures=())
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


LAYOUT = """<!DOCTYPE html><html lang="en"><head><title>Steps</title></head>
<body><h1>Steps</h1>
<p>Marked presentation:</p>
<table role="presentation"><tr><td>Subtract 3 from each side.</td><td>x = 4</td></tr>
<tr><td>Divide each side by 2.</td><td>x = 2</td></tr></table>
<p>Marked none, ARIA's other name for it:</p>
<table role="none"><tr><td>Add 5 to each side.</td><td>x = 9</td></tr>
<tr><td>Divide each side by 3.</td><td>x = 3</td></tr></table>
<p>Not marked:</p>
<table><tr><td>Multiply each side by 4.</td><td>x = 8</td></tr>
<tr><td>Subtract 1 from each side.</td><td>x = 7</td></tr></table>
<p>A layout table holding a data table:</p>
<table role="presentation"><tr><td>Read the price off the table.</td><td>
<table><tr><th>Year</th><th>Price</th></tr><tr><td>2020</td><td>10</td></tr></table>
</td></tr></table>
</body></html>
"""


LAYOUT_NOT_TABLES = """<!DOCTYPE html><html lang="en"><head><title>Checks</title></head>
<body><h1>Checks</h1>
<table role="presentation"><tr><td>Add 2 to each side.</td><td>x = 6</td></tr>
<tr><td>Halve each side.</td><td>x = 3</td></tr></table>
<p>Check:</p>
<table role="presentation"><tr><td>2 \u00b7 3 = 6</td></tr></table>
<table role="presentation"><tr><td><img src="dot.png" alt=""></td>
<td><img src="dot.png" alt=""></td></tr></table>
</body></html>
"""


def narrow_layout_rules(page):
    """The page's narrow-screen rules for a layout table: the @media block
    whose first rule is for one, braces counted."""
    m = re.search(r'@media \(max-width: 36em\) \{\s*table\[role="presentation"\]', page)
    if not m:
        return ""
    depth = 0
    for i in range(m.start(), len(page)):
        if page[i] == "{":
            depth += 1
        elif page[i] == "}":
            depth -= 1
            if depth == 0:
                return page[m.start():i + 1]
    return ""


def case_layout_tables(work):
    """A table the page marks as layout, role="presentation" or "none", is
    one in every target and every check, and a row in table-headers.csv
    makes a table one, or a data table again, in the pages and in a
    remediated copy."""
    import csv
    os.makedirs(work)
    with open(os.path.join(work, "steps.html"), "w", encoding="utf-8") as fh:
        fh.write(LAYOUT)
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  html:\n    format: html\n  md:\n    format: markdown\n"
                 "  docx:\n    format: docx\n")
    first = run_in(work, "")
    said = first.stdout + first.stderr

    def rows(name):
        path = os.path.join(work, name)
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    def tables(*parts):
        page = read(*parts) if exists(*parts) else ""
        return re.findall(r'(<div class="table-wrapper"[^>]*>\s*)?<table([^>]*)>', page)

    missing = sorted(r["Label"] for r in rows("table-captions-missing.csv"))
    new = rows("table-headers-new.csv")
    report = rows("table-headers-report.csv")
    # The page as html-source.lua read it, the pre-pass's marks in it: each
    # table's role and mark.
    read_as = []
    if exists(work, "steps.json"):
        with open(os.path.join(work, "steps.json"), encoding="utf-8") as fh:
            def walk(node):
                if isinstance(node, dict):
                    if node.get("t") == "Table":
                        found = dict(node["c"][0][2])
                        read_as.append((found.get("role"), found.get("data-th-marker")))
                    for value in node.values():
                        walk(value)
                elif isinstance(node, list):
                    for value in node:
                        walk(value)
            walk(json.load(fh))
    # The filter on its own, on the page as Pandoc reads it, with no pre-pass
    # and no reading filter: the role alone says what's a layout table.
    alone = subprocess.run(
        "pandoc -f html -t json steps.html | pandoc -f json -t html5 --lua-filter="
        + os.path.join(BIN, "figures-and-tables.lua"), shell=True, cwd=work,
        capture_output=True, text=True).stdout
    alone = re.findall(r'(<div class="table-wrapper"[^>]*>\s*)?<table([^>]*)>', alone)
    checked = rows("output-check.csv")
    page = tables(work, "html", "steps.html")
    markdown = read(work, "md", "steps.md") if exists(work, "md", "steps.md") else ""
    fidelity = [r for r in rows("fidelity.csv") if "layout" in str(r)]
    # The Markdown target's page, read back as a book.
    back = os.path.join(work, "back")
    os.makedirs(back)
    if markdown:
        with open(os.path.join(back, "steps.md"), "w", encoding="utf-8") as fh:
            fh.write(markdown)
    run_in(back, "")
    again = tables(back, "html", "steps.html")
    # A person's rows: the unmarked table is layout, and the first one, which
    # the page marks so, a data table with nothing to declare.
    keys = {r["preview"][:8]: r["key"] for r in new}
    with open(os.path.join(work, "table-headers.csv"), "w", encoding="utf-8") as fh:
        fh.write("key,headers\n%s,layout\n%s,none\n"
                 % (keys.get("Multiply", "x"), keys.get("Subtract", "y")))
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  html:\n    format: html\n  copy:\n    format: source\n")
    second = run_in(work)
    decided = tables(work, "html", "steps.html")
    copied = read(work, "copy", "steps.html") if exists(work, "copy", "steps.html") else ""
    missing_after = sorted(r["Label"] for r in rows("table-captions-missing.csv"))
    # A page whose layout tables include what the census counts no table: one
    # cell, and pictures alone.
    others = os.path.join(work, "others")
    os.makedirs(others)
    with open(os.path.join(others, "checks.html"), "w", encoding="utf-8") as fh:
        fh.write(LAYOUT_NOT_TABLES)
    with open(os.path.join(others, "dot.png"), "wb") as fh:
        fh.write(ONE_PIXEL)
    with open(os.path.join(others, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    run_in(others, "")
    listed = []
    if os.path.exists(os.path.join(others, "table-headers-new.csv")):
        with open(os.path.join(others, "table-headers-new.csv"), encoding="utf-8",
                  newline="") as fh:
            listed = [(r["preview"], r["headers"]) for r in csv.DictReader(fh)]
    return [
        ("a table marked as layout, role presentation or none, is asked no caption, "
         "where one marked nothing and a data table inside a layout table are",
         lambda: missing == ["steps#table-3", "steps#table-5"]),
        ("each is a row of table-headers-new.csv with the value layout, the page "
         "its supplier, and the run counts them apart",
         lambda: [r["headers"] for r in new] == ["layout", "layout", "", "layout", "first-row"]
         and [r["supplier"] for r in report if r["guess"] == "layout"] == ["source"] * 3
         and "2 data table(s) and 3 layout table(s)" in said),
        ("on the page it has role presentation, none made so, and no scroll "
         "region; a data table does, inside a layout table too",
         lambda: [(bool(w), a) for w, a in page]
         == [(False, ' role="presentation"'), (False, ' role="presentation"'),
             (True, ""), (False, ' role="presentation"'), (True, "")]),
        # page.css: the cells stacked on a narrow screen, and the caption a
        # line of its own after them, where a wide screen puts it; left a
        # table's caption in a table made a block, it was a column as wide
        # as its longest word (Chromium, "Table" over "3.2").
        ("on a narrow screen its cells stack, and its caption is a line of its "
         "own after them",
         lambda: (lambda narrow: re.search(r'table\[role="presentation"\] \{\s*display: flex;'
                                           r'\s*flex-direction: column;', narrow)
                  and re.search(r'table\[role="presentation"\] > caption \{\s*display: block;'
                                r'\s*order: 1;', narrow))(
             narrow_layout_rules(read(work, "html", "steps.html")
                                 if exists(work, "html", "steps.html") else ""))),
        ("read, a table marked none is marked presentation and declared a layout "
         "table, as one marked presentation is, so every step after sees one mark",
         lambda: read_as[:2] == [("presentation", "layout")] * 2),
        ("the filter run on its own, with no pre-pass, takes the role as the mark",
         lambda: [(bool(w), a) for w, a in alone][:1] == [(False, ' role="presentation"')]
         and bool(alone[2][0])),
        ("the output check finds only the unmarked table",
         lambda: [r["Detail"] for r in checked if r["Check"].startswith("table-")]
         == ["table 3"]),
        ("the Markdown target writes it as HTML with its role, and read back "
         "it's a layout table again",
         lambda: markdown.count('role="presentation"') == 3
         and [a for _, a in again] == [a for _, a in page]
         and [bool(w) for w, _ in again] == [bool(w) for w, _ in page]),
        ("the Word target notes each as what it can't carry, none too",
         lambda: len(fidelity) == 3),
        ("a row in table-headers.csv makes a table layout, or a data table "
         "with no role, whatever the page says",
         lambda: second.returncode == 0
         and [(bool(w), a) for w, a in decided]
         == [(True, ""), (False, ' role="presentation"'), (False, ' role="presentation"'),
             (False, ' role="presentation"'), (True, "")]
         and missing_after == ["steps#table-1", "steps#table-5"]),
        ("a layout table the census counts no table, one cell or pictures alone, "
         "isn't listed, as an unmarked one isn't",
         lambda: listed == [("Add 2 to each side. | x = 6", "layout")]),
        ("and a remediated page has both decisions, the page's own role left on "
         "a table no row decides",
         lambda: re.findall(r"<table[^>]*>", copied)
         == ["<table>", '<table role="none">', '<table role="presentation">',
             '<table role="presentation">', "<table>"]),
    ]


def case_layout_word_head(work):
    """A Word table a person declares a layout table, whose first row Word
    repeats as a header, which Pandoc's reader puts in the table's head:
    every row is a body row, and no cell a header cell, on the page and in
    the Markdown target's copy."""
    import csv
    os.makedirs(work)
    with open(os.path.join(work, "src.md"), "w", encoding="utf-8") as fh:
        fh.write("# Resume\n\n| Diploma in game design | Sept. 2015 to Apr. 2018 |\n"
                 "|---|---|\n| Certificate in illustration | Sept. 2014 to Apr. 2015 |\n")
    subprocess.run(["pandoc", "src.md", "-o", "resume.docx"], cwd=work, check=True)
    os.remove(os.path.join(work, "src.md"))
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  html:\n    format: html\n  md:\n    format: markdown\n")
    run_in(work, "")
    keys = []
    if exists(work, "table-headers-new.csv"):
        with open(os.path.join(work, "table-headers-new.csv"), encoding="utf-8",
                  newline="") as fh:
            keys = [r["key"] for r in csv.DictReader(fh)]
    with open(os.path.join(work, "table-headers.csv"), "w", encoding="utf-8") as fh:
        fh.write("key,headers\n%s,layout\n" % (keys[0] if keys else "x"))
    second = run_in(work)
    page = read(work, "html", "resume.html") if exists(work, "html", "resume.html") else ""
    markdown = read(work, "md", "resume.md") if exists(work, "md", "resume.md") else ""
    table = re.search(r"<table\b.*?</table>", page, re.S)
    table = table.group(0) if table else ""
    copy = re.search(r"<table\b.*?</table>", markdown, re.S)
    copy = copy.group(0) if copy else ""
    return [
        ("a Word table declared layout, its repeating header row in Pandoc's head, "
         "is written with no head and no header cell, its rows in order",
         lambda: second.returncode == 0 and len(keys) == 1
         and re.match(r'<table\b[^>]*\brole="presentation"', table)
         and "<th" not in table and "<thead" not in table
         and table.index("Diploma in game design") < table.index("Certificate in illustration")),
        ("and the Markdown target's copy too",
         lambda: 'role="presentation"' in copy and "<th" not in copy and "<thead" not in copy),
    ]


def word_with_body(path, body):
    """A Word file Pandoc writes, its body replaced by the OOXML given, so
    it has Pandoc's styles and namespaces and exactly that body."""
    subprocess.run(["pandoc", "-o", path], input="# Title\n\nText.\n", text=True,
                   check=True)
    with zipfile.ZipFile(path) as z:
        items = [(i, z.read(i.filename)) for i in z.infolist()]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for info, data in items:
            if info.filename == "word/document.xml":
                data = re.sub(r"<w:body>.*?(<w:sectPr>)", lambda m: "<w:body>" + body + m.group(1),
                              data.decode("utf-8"), count=1, flags=re.S).encode("utf-8")
            z.writestr(info, data)


def ooxml_paragraph(*parts):
    return "<w:p>%s</w:p>" % "".join(
        p if p.startswith("<") else '<w:r><w:t xml:space="preserve">%s</w:t></w:r>' % p
        for p in parts)


def ooxml_table(rows):
    """rows: lists of cells, each a list of paragraphs' OOXML."""
    width = max(len(row) for row in rows)
    return "<w:tbl><w:tblPr/><w:tblGrid>%s</w:tblGrid>%s</w:tbl>" % (
        '<w:gridCol w:w="2400"/>' * width,
        "".join("<w:tr>%s</w:tr>" % "".join("<w:tc>%s</w:tc>" % "".join(cell) for cell in row)
                for row in rows))


def case_word_table_matching(work):
    """A row of table-headers.csv reaches the Word table it names when the
    table's first cell holds a no-break space, two paragraphs, or a
    formula: the filter, finding the table the pre-pass listed, compared
    the cell's first 20 bytes with the pre-pass's, which takes a no-break
    space for a space, as Lua's %s doesn't, and a paragraph's end for one,
    as stringify doesn't, and reads a formula's letters where the filter
    read its TeX, so each declaration was set aside with a warning."""
    import csv
    os.makedirs(work)
    p, table = ooxml_paragraph, ooxml_table
    formula = ('<m:oMath><m:sSub><m:e><m:r><m:t>x</m:t></m:r></m:e>'
               '<m:sub><m:r><m:t>n</m:t></m:r></m:sub></m:sSub></m:oMath>')
    word_with_body(os.path.join(work, "kinds.docx"), "".join([
        p("Burns by depth:"),
        table([[[p("Burn type")], [p("Depth")]],
               [[p("Superficial")], [p("Epidermis")]],
               [[p("Partial")], [p("Dermis")]]]),
        p("A message, outlined:"),
        table([[[p("Message"), p("Outline")], [p("Draft")]],
               [[p("Interested")], [p("Our details")]],
               [[p("Closing")], [p("Thanks")]]]),
        p("A sequence's terms:"),
        table([[[p(formula, " is the nth term")], [p("Rule")]],
               [[p("First")], [p("Start at one")]],
               [[p("Next")], [p("Add two")]]]),
    ]))
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    run_in(work, "")
    keys = []
    if exists(work, "table-headers-new.csv"):
        with open(os.path.join(work, "table-headers-new.csv"), encoding="utf-8",
                  newline="") as fh:
            keys = [r["key"] for r in csv.DictReader(fh)]
    with open(os.path.join(work, "table-headers.csv"), "w", encoding="utf-8") as fh:
        fh.write("key,headers\n" + "".join("%s,layout\n" % k for k in keys))
    second = run_in(work)
    page = read(work, "html", "kinds.html") if exists(work, "html", "kinds.html") else ""
    tables = re.findall(r"<table\b.*?</table>", page, re.S)
    return [
        ("a Word table declared layout is one whatever its first cell holds: a "
         "no-break space, two paragraphs, a formula",
         lambda: len(keys) == 3 and len(tables) == 3
         and all(re.match(r'<table\b[^>]*\brole="presentation"', t) for t in tables)),
        ("and the run says nothing of a table that doesn't match the pre-pass",
         lambda: second.returncode == 0
         and "does not match the pre-pass" not in second.stdout + second.stderr),
    ]


def case_word_box_anchor(work):
    """A bookmark between blocks before a Word table the header guess
    doesn't list, a box of one cell, as OpenStax's export bookmarks every
    table and links to a box, which Pandoc's reader drops: the pre-pass
    handed the filter those before a listed table only, so a link to the
    box went nowhere. And the box is a layout table, as a table of one
    cell is whatever its source, where the filter made it a data table,
    wanting a caption and wrapped in a scroll region: one whose cell
    Word's table look formats as a header row too, which Pandoc's reader
    puts in the table's head. One whose row is marked to repeat as a
    header row is declared so, and stays a data table."""
    import csv
    os.makedirs(work)
    p, table = ooxml_paragraph, ooxml_table
    # Word's table look as Word sets it on a table it inserts.
    headed = ('<w:tbl><w:tblPr><w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" '
              'w:firstColumn="1" w:lastColumn="0" w:noHBand="0" w:noVBand="1"/></w:tblPr>'
              '<w:tblGrid><w:gridCol w:w="2400"/></w:tblGrid><w:tr><w:tc>%s</w:tc></w:tr>'
              '</w:tbl>' % p("Back up your files, too."))
    # And one whose row the author marked to repeat as a header row.
    repeated = headed.replace("<w:tr>", "<w:tr><w:trPr><w:tblHeader/></w:trPr>").replace(
        "Back up your files, too.", "Totals")
    word_with_body(os.path.join(work, "box.docx"), "".join([
        p("As ", '<w:hyperlink w:anchor="save-note"><w:r><w:t>the note</w:t></w:r>'
              "</w:hyperlink>", " says, save often."),
        '<w:bookmarkStart w:id="1" w:name="save-note"/><w:bookmarkEnd w:id="1"/>',
        table([[[p("Remember to save your work.")]]]),
        p("And another:"),
        headed,
        p("And a data table:"),
        '<w:bookmarkStart w:id="2" w:name="costs"/><w:bookmarkEnd w:id="2"/>',
        table([[[p("Year")], [p("Cost")]], [[p("2020")], [p("10")]], [[p("2021")], [p("12")]]]),
        p("As ", '<w:hyperlink w:anchor="costs"><w:r><w:t>the costs</w:t></w:r></w:hyperlink>',
          " show."),
        p("And a header row alone:"),
        repeated,
    ]))
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    result = run_in(work, "")
    page = read(work, "html", "box.html") if exists(work, "html", "box.html") else ""
    checked = []
    if exists(work, "output-check.csv"):
        with open(os.path.join(work, "output-check.csv"), encoding="utf-8", newline="") as fh:
            checked = [r["Check"] for r in csv.DictReader(fh)]
    listed = []
    if exists(work, "table-headers-new.csv"):
        with open(os.path.join(work, "table-headers-new.csv"), encoding="utf-8",
                  newline="") as fh:
            listed = [r["preview"] for r in csv.DictReader(fh)]
    missing = []
    if exists(work, "table-captions-missing.csv"):
        with open(os.path.join(work, "table-captions-missing.csv"), encoding="utf-8",
                  newline="") as fh:
            missing = [r["Label"] for r in csv.DictReader(fh)]
    tables = re.findall(r'(<div class="table-wrapper"[^>]*>\s*)?<table([^>]*)>', page)
    boxes = page.split("And a data table")[0]

    def before(anchor, words):
        return anchor in page and words in page and page.index(anchor) < page.index(words)
    return [
        ("a box of one cell keeps the bookmark before it, which a link goes to",
         lambda: result.returncode == 0 and 'href="#save-note"' in page
         and before('id="save-note"', "Remember to save your work.")
         and "link-to-missing-fragment" not in checked),
        ("as a data table does, and the box still isn't listed",
         lambda: 'href="#costs"' in page and before('id="costs"', "2020")
         and len(listed) == 1 and "Year" in listed[0]),
        ("and each box is a layout table, one Word's table look heads too: no "
         "scroll region, no caption asked of it, and no header cell, where the "
         "data table has a scroll region and is asked a caption",
         lambda: [(bool(w), 'role="presentation"' in a) for w, a in tables][:3]
         == [(False, True), (False, True), (True, False)]
         and "Back up your files, too." in boxes and "<th" not in boxes
         and missing[:1] == ["box#table-3"]),
        ("and a box whose row is marked to repeat as a header row is a data table, "
         "its cell a header cell",
         lambda: [(bool(w), 'role="presentation"' in a) for w, a in tables][3:]
         == [(True, False)]
         and re.search(r"<th[^>]*>\s*Totals", page) is not None
         and missing == ["box#table-3", "box#table-4"]),
    ]


ONE_CELL_PAGE = """<!DOCTYPE html><html lang="en"><head><title>Boxes</title></head>
<body><h1>Boxes</h1>
<p>A box:</p>
<table><tr><td>Remember to save your work.</td></tr></table>
<p>A header cell alone:</p>
<table><tr><th>Totals</th></tr></table>
<p>Two cells:</p>
<table><tr><td>Name</td><td>Ann Smith</td></tr></table>
<p>And data:</p>
<table><tr><td>Year</td><td>Cost</td></tr><tr><td>2020</td><td>10</td></tr>
<tr><td>2021</td><td>12</td></tr></table>
<p>A box with a caption of its own, and one a label names:</p>
<table><caption>Grades</caption><tr><td>An A is 90 or more.</td></tr></table>
<table><tr><td>Strength is graded from 0 to 5.</td></tr></table>
<p>Table 2 Muscle strength</p>
</body></html>
"""


def case_one_cell_tables(work):
    """A table of one cell has nothing to head, so it's a layout table
    whatever its source, as the header guess counts it no table: an HTML
    page's box, which nothing marks, was a data table, wanting a caption
    and wrapped in a scroll region. One whose cell the page makes a header
    cell declares its headers, and stays a data table; so does one with a
    caption, its own or a label beside it, which its author numbered."""
    import csv
    os.makedirs(work)
    with open(os.path.join(work, "boxes.html"), "w", encoding="utf-8") as fh:
        fh.write(ONE_CELL_PAGE)
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    result = run_in(work, "")
    page = read(work, "html", "boxes.html") if exists(work, "html", "boxes.html") else ""
    pattern = r'(<div class="table-wrapper"[^>]*>\s*)?<table([^>]*)>'
    tables = re.findall(pattern, page)
    # The filter on its own, with no pre-pass and no reading filter: one
    # cell is the mark, and two aren't.
    alone = re.findall(pattern, subprocess.run(
        "pandoc -f html -t json boxes.html | pandoc -f json -t html5 --lua-filter="
        + os.path.join(BIN, "figures-and-tables.lua"), shell=True, cwd=work,
        capture_output=True, text=True).stdout)

    def rows(name, column):
        if not exists(work, name):
            return []
        with open(os.path.join(work, name), encoding="utf-8", newline="") as fh:
            return [r[column] for r in csv.DictReader(fh)]
    return [
        ("an HTML page's box of one cell is a layout table, asked no caption and "
         "not listed, where a header cell the page declares makes one a data table",
         lambda: result.returncode == 0
         and [(bool(w), 'role="presentation"' in a) for w, a in tables][:4]
         == [(False, True), (True, False), (True, False), (True, False)]
         and rows("table-captions-missing.csv", "Label")
         == ["boxes#table-2", "boxes#table-3", "boxes#table-4"]
         and rows("table-headers-new.csv", "preview")
         == ["Totals", "Name | Ann Smith", "Year | Cost"]),
        ("a box with a caption of its own, or a label beside it, stays a data table, "
         "captioned as its author numbered it",
         lambda: [(bool(w), 'role="presentation"' in a) for w, a in tables][4:]
         == [(True, False), (True, False)]
         and "<caption>Grades</caption>" in page
         and "<caption>Table 2 Muscle strength</caption>" in page),
        ("so is a box the filter reads alone, where a header cell, the head Pandoc reads "
         "a row of them as, two cells, and a box with a caption aren't",
         lambda: [(bool(w), 'role="presentation"' in a) for w, a in alone]
         == [(False, True)] + [(True, False)] * 5),
    ]


def case_menu(work):
    """menu: on gives every rendered page the book's contents and a
    previous/next pager; a pass-through page is left as it stands. The
    target has a header and a footer too, and a page its own epigraph and
    closing line, in its metadata."""
    os.makedirs(os.path.join(work, "_pt"))
    with open(os.path.join(work, "ch1.md"), "w", encoding="utf-8") as fh:
        fh.write("# Chapter One\n\nOpening.\n\n## First Part\n\nA.\n\n"
                 "## Second Part\n\nB.\n")
    with open(os.path.join(work, "ch2.md"), "w", encoding="utf-8") as fh:
        fh.write("---\ntitle: Chapter Two\ninclude-before: |\n  > A line before the "
                 "chapter.\ninclude-after: A closing line.\n---\n\n# Chapter Two\n\nTwo.\n")
    with open(os.path.join(work, "_pt", "about.html"), "w",
              encoding="utf-8") as fh:
        fh.write(HAND.replace("Front Matter", "About"))
    result = convert(work, "defaults:\n  pages:\n    split_level: 2\n"
                           "targets:\n  html:\n    format: html\n"
                           "    menu: \"on\"\n"
                           "    header: \"Course site.\"\n"
                           "    footer: \"Shared under CC BY.\"\n"
                           "  plain:\n    format: html\n"
                           "    footer: \"<footer>Ours already.</footer>\"\n", fixtures=())
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
        ("the menu between the page's banner and its main landmark, and the "
         "pager between that and its footer, each a landmark of its own",
         lambda: all(tag in first for tag in ("<header>", "<main>", "<footer>"))
         and first.index("<header>") < first.index('<nav class="book-menu"')
         < first.index("<main>") < first.index("</main>")
         < first.index('<nav class="book-pager"') < first.index("<footer>")),
        ("a page's own include-before and include-after, an epigraph its metadata "
         "gives, are on it beside the target's header and footer, inside its main "
         "landmark, and without them",
         lambda: all(re.search(r"<main>\s*<blockquote>\s*<p>A line before the chapter\.</p>"
                               r"\s*</blockquote>\s*<h1[^>]*>Chapter Two</h1>.*"
                               r"A closing line\.\s*</main>", read(work, name, "ch2.html"), re.S)
                     for name in ("html", "plain") if exists(work, name, "ch2.html"))
         and exists(work, "plain", "ch2.html")
         and "Course site." in read(work, "html", "ch2.html")),
        ("a footer setting that is a <footer> already, as one had to be to make a "
         "landmark, is the page's footer as it stands, not a footer in a footer",
         lambda: re.search(r"</main>\s*<footer>\s*Ours already\.\s*</footer>\s*</body>",
                           read(work, "plain", "ch1--first-part.html"))
         and read(work, "plain", "ch1--first-part.html").count("<footer") == 1),
        ("every link the menu adds leads somewhere",
         lambda: "link-to-missing" not in checks),
        ("a pass-through page is left as it stands",
         lambda: read(work, "html", "about.html")
         == HAND.replace("Front Matter", "About")),
        ("a target without menu: on has none",
         lambda: '<nav class="book-menu"' not in read(
             work, "plain", "ch1--first-part.html")),
    ]


def case_page_footer(work):
    """The footer setting on every page of every format, not an HTML
    target's alone: the last thing in each of an EPUB's content documents
    but its cover and its navigation document, after the notes a group
    gathers; every
    page of a Word file, in a footer part of its own; the end of a
    Markdown or AsciiDoc file, which reading the file back as a source
    takes out again, since the target's own setting puts it back; and the
    LaTeX a latex target writes. A picture is its alternative text in all
    of them, and so is a link to one of the book's own files, which none
    of them carries; any link is its words in a Word file's footer and the
    LaTeX. A line break is one in each, and an id is left out."""
    first = os.path.join(work, "first")
    os.makedirs(first, exist_ok=True)
    for name, text in (("ch1.md", "# Chapter One\n\nOpening.[^1]\n\n[^1]: A note.\n"),
                       ("ch2.md", "# Chapter Two\n\nTwo.[^2]\n\n[^2]: Another.\n")):
        with open(os.path.join(first, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    with open(os.path.join(first, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  identifier: org.example.fixtures\n"
                 "  title: The Fixture Book\n  contents:\n"
                 "    - title: Part\n      items: [ch1, ch2]\n")
    for name in ("cover.png", "cc.png"):
        with open(os.path.join(first, name), "wb") as fh:
            fh.write(ONE_PIXEL)
    footer = ("defaults:\n  footer: |\n    Read *this book*, and the others in its series, "
              "free at [example.org](https://example.org){#site},\\\n"
              "    under [the license](license.md). ![CC BY](cc.png)\n")
    result = convert(first, footer + "targets:\n  html:\n    format: html\n"
                     '    footer: "Read *this book* free at [example.org](https://example.org)."\n'
                     "  epub:\n    format: epub3\n    title_page: \"on\"\n"
                     "    notes:\n      placement: group\n"
                     "    epub:\n      cover_image: cover.png\n"
                     "  word:\n    format: docx\n  md:\n    format: markdown\n"
                     "  adoc:\n    format: asciidoc\n  tex:\n    format: latex\n"
                     "  linked:\n    format: asciidoc\n"
                     '    footer: "Shared under [the license [CC BY]](https://example.org/l)."\n',
                     project=False, fixtures=())

    docs = {}
    epub = os.path.join(first, "epub", "org.example.fixtures.epub")
    if os.path.exists(epub):
        with zipfile.ZipFile(epub) as z:
            docs = {n: z.read(n).decode("utf-8") for n in z.namelist()
                    if n.endswith(".xhtml")}
    nav = [t for t in docs.values() if 'epub:type="toc"' in t]
    cover = [t for t in docs.values() if '<body id="cover">' in t]
    content = [t for t in docs.values() if t not in nav and t not in cover]
    ending = re.compile(r'<footer> <p>Read <em>this book</em>, and the others in its '
                        r'series, free at <a href="https://example\.org">example\.org</a>,'
                        r'<br /> under the license\. CC BY</p> </footer> </body> </html> ?$')

    def flat(text):
        return re.sub(r"\s+", " ", text)
    noted = [t for t in content if 'role="doc-footnote"' in t]
    validated = epubcheck(epub)

    def word_footer(name):
        """Whether the Word file has the footer's words in a footer part of
        its own, which every section names first, as the schema orders a
        section's children, related, typed, and styled."""
        import xml.dom.minidom
        with zipfile.ZipFile(os.path.join(first, "word", name)) as z:
            parts = {n: z.read(n).decode("utf-8") for n in z.namelist()
                     if n.endswith((".xml", ".rels"))}
        part = parts.get("word/tiqfooter.xml", "")
        for text in (part, parts["word/document.xml"]):
            xml.dom.minidom.parseString(text.encode("utf-8"))
        sections = re.findall(r"<w:sectPr\b.*?</w:sectPr>", parts["word/document.xml"], re.S)
        return ("".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", part))
                == "Read this book, and the others in its series, free at example.org,"
                "under the license. CC BY"
                and "w:hyperlink" not in part and '<w:pStyle w:val="Footer" />' in part
                and sections and all(
                    re.match(r'<w:sectPr\b[^>]*>\s*<w:footerReference w:type="default" '
                             r'r:id="rIdTiqFooter" />', s)
                    and s.count("<w:footerReference") == 1 for s in sections)
                and re.search(r'<Relationship Id="rIdTiqFooter" Type="[^"]*/relationships/'
                              r'footer" Target="tiqfooter\.xml"',
                              parts["word/_rels/document.xml.rels"])
                and 'PartName="/word/tiqfooter.xml" ContentType="application/vnd.'
                    'openxmlformats-officedocument.wordprocessingml.footer+xml"'
                in parts["[Content_Types].xml"]
                and 'w:styleId="Footer"' in parts["word/styles.xml"])

    words = sorted(n for n in os.listdir(os.path.join(first, "word"))
                   if n.endswith(".docx")) if exists(first, "word") else []

    def word_part(name):
        """A Word file's footer part, as written."""
        with zipfile.ZipFile(os.path.join(first, "word", name)) as z:
            return z.read("word/tiqfooter.xml").decode("utf-8") \
                if "word/tiqfooter.xml" in z.namelist() else ""

    def text_of(folder, ext):
        found = {}
        if exists(first, folder):
            for name in sorted(os.listdir(os.path.join(first, folder))):
                if name.endswith(ext):
                    found[name] = read(first, folder, name)
        return found
    markdown, asciidoc = text_of("md", ".md"), text_of("adoc", ".adoc")
    linked = text_of("linked", ".adoc")
    master = read(first, "tex", "org.example.fixtures.tex") \
        if exists(first, "tex", "org.example.fixtures.tex") else ""

    def read_back(folder, ext):
        """The target's files converted again as the book's sources, the
        footer set as before: each page's HTML, by its name."""
        again = os.path.join(work, "back-" + folder)
        os.makedirs(again, exist_ok=True)
        if not exists(first, folder):
            return {}
        for name in os.listdir(os.path.join(first, folder)):
            if name.endswith(ext):
                shutil.copy(os.path.join(first, folder, name), again)
        shutil.copy(os.path.join(first, "project.yaml"), again)
        with open(os.path.join(again, "conversion.yaml"), "w", encoding="utf-8") as fh:
            fh.write(footer + "targets:\n  html:\n    format: html\n")
        subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"],
                       cwd=again, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        return {name: read(again, "html", name) for name in ("ch1.html", "ch2.html")
                if exists(again, "html", name)}

    def footer_once(pages):
        """Each page has the footer once, after its main landmark, and none
        within it."""
        return len(pages) == 2 and all(
            t.count("<footer") == 1 and re.search(r"</main>\s*<footer>", t)
            and "free at" not in t[t.find("<main>"):t.find("</main>")]
            for t in pages.values())
    md_back, adoc_back = read_back("md", ".md"), read_back("adoc", ".adoc")

    # A book whose pages, merged a file to each, include one named footer.
    merged = os.path.join(work, "merged")
    os.makedirs(merged, exist_ok=True)
    for name, text in (("ch1.md", "# Chapter One\n\nOne.\n"),
                       ("footer.md", "# Footer Studies\n\nThe study of feet.\n")):
        with open(os.path.join(merged, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    with open(os.path.join(merged, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  identifier: org.example.merged\n  title: Merged\n"
                 "  contents: [ch1, footer]\n")
    convert(merged, 'defaults:\n  footer: "Shared under CC BY."\n'
            "targets:\n  md:\n    format: markdown\n    merge: groups\n",
            project=False, fixtures=())
    studies = read(merged, "md", "footer.md") if exists(merged, "md", "footer.md") else ""
    return [
        ("the book converts in every format",
         lambda: result.returncode in (0, 1) and docs and words and markdown
         and asciidoc and master),
        ("each of an EPUB's content documents, its title page among them, ends "
         "with the footer, a link in it a link and a picture its alternative text, "
         "and its cover and its navigation document have none",
         lambda: len(content) >= 3 and all(ending.search(flat(t)) and t.count("<footer") == 1
                                           and "cc.png" not in t for t in content)
         and any('epub:type="titlepage"' in t for t in content)
         and len(nav) == 1 and "<footer" not in nav[0]
         and len(cover) == 1 and "<footer" not in cover[0]),
        ("and epubcheck finds nothing in it",
         lambda: validated == [] if validated is not None else True),
        ("the notes a group gathers are in its last page's section, before the footer",
         lambda: len(noted) == 1 and re.search(
             r'role="doc-footnote".*</aside>\s*</section>\s*</section>\s*<footer>',
             noted[0], re.S)),
        ("a Word file has the footer on every page, in a footer part of its own that "
         "every section names, its links their words and its picture its alternative text",
         lambda: words == ["ch1.docx", "ch2.docx"] and all(word_footer(n) for n in words)),
        ("a Markdown file's text ends with the footer in a div of class oer-footer, its "
         "notes after it, an AsciiDoc file with it in an open block of that role, its "
         "lines as long as the file's own, a picture its alternative text",
         lambda: len(markdown) == 2 and all(re.search(re.escape(
             "\n::: oer-footer\nRead *this book*, and the others in its series, free at "
             "[example.org](https://example.org),\\\nunder the license. CC BY\n:::\n")
             + r"(\n\[\^\w+\]: .+\n)+\Z", t) for t in markdown.values())
         and len(asciidoc) == 2 and all(re.search(re.escape(
             "\n[.oer-footer]\n--\nRead _this book_, and the others in its series, free at "
             "https://example.org[example.org], +\nunder the license. CC BY\n--\n")
             + r"\s*\Z", t) for t in asciidoc.values())),
        ("an AsciiDoc file's footer is written as the rest of the file is, a bracket in "
         "a link's text a character reference",
         lambda: len(linked) == 2 and all(re.search(re.escape(
             "\n[.oer-footer]\n--\nShared under https://example.org/l[the license "
             "&#91;CC BY&#93;].\n--\n") + r"\s*\Z", t) for t in linked.values())),
        ("read back as the book's sources, the Markdown and the AsciiDoc give pages "
         "with the footer once, the target's own, not in their content",
         lambda: footer_once(md_back) and footer_once(adoc_back)),
        ("a latex target's master carries it for the foot of every page, its links "
         "their words and its picture its alternative text",
         lambda: "\\newcommand\\OERFooterText{Read \\emph{this book}, and the others in its "
         "series, free at example.org,\\\\\nunder the license. CC BY}" in master
         and "\\OER@addfooter" in master),
        ("a link to one of the book's own files, which no target carries, is its words "
         "outside an HTML page, where a link to a site stays a link",
         lambda: content and markdown and asciidoc
         and all("under the license." in flat(t) and "license.md" not in t
                 and 'href="https://example.org"' in flat(t) for t in content)
         and all("under the license." in t and "license.md" not in t
                 and "https://example.org" in t
                 for t in list(markdown.values()) + list(asciidoc.values()))),
        ("a line break in the footer is a line break in each format",
         lambda: content and words and markdown and asciidoc
         and all(",<br /> under the license" in flat(t) for t in content)
         and all('example.org,</w:t></w:r><w:r><w:br /></w:r><w:r><w:t xml:space="preserve">'
                 'under the license' in word_part(n) for n in words)
         and all(",\\\nunder the license" in t for t in markdown.values())
         and all(", +\nunder the license" in t for t in asciidoc.values())
         and ",\\\\\nunder the license" in master),
        ("a merged file named footer is its page, with the footer at its end",
         lambda: "The study of feet." in studies
         and studies.endswith("::: oer-footer\nShared under CC BY.\n:::\n")),
        ("an id in the footer is left out, since the footer is on every page",
         lambda: content and markdown and asciidoc
         and not any('id="site"' in t for t in content)
         and not any("#site" in t for t in markdown.values())
         and not any("site]" in t or "#site" in t for t in asciidoc.values())),
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
                           "  epub:\n    format: epub3\n", fixtures=())
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
         lambda: result.returncode == 0 and "mc<sup>2</sup>" in page),
        ("an HTML image is an image: copied, and without align",
         lambda: re.search(r'<img\s+src="assets/Curve\.png"[^>]*alt="A curve"',
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
<p>The <a href="#costs">costs</a> follow.</p>
<table id="costs"><tr><td></td><td><b>Labor</b></td><td><b>Total</b></td></tr>
<tr><td colspan="3">Example A: workers cost $40</td></tr>
<tr><td>Tech 1</td><td>$400</td><td>$560</td></tr>
<tr><td>Tech 2</td><td>$280</td><td>$600</td></tr>
<tr><td colspan="3">Example B: workers cost $55</td></tr>
<tr><td>Tech 1</td><td>$550</td><td>$710</td></tr>
<tr><td>Tech 2</td><td>$385</td><td>$705</td></tr></table>
<table><tbody><tr><th colspan="2" scope="rowgroup">Group one</th></tr>
<tr><td>a</td><td>1</td></tr></tbody>
<tbody><tr><th colspan="2" scope="rowgroup">Group two</th></tr>
<tr><td>b</td><td>2</td></tr></tbody>
<tfoot><tr><td colspan="2">Source: a survey made up for the test</td></tr></tfoot></table>
</main></body></html>
"""

# Tables whose head is one cell across: a band, a title, and a title over
# the header row.
HEADS = """<!DOCTYPE html><html lang="en"><head><title>Heads</title></head>
<body><main><h1>Heads</h1>
<p>Table 3.4 Plans</p>
<table><thead><tr><th colspan="2">Plan A</th></tr></thead>
<tbody><tr><td>Rent</td><td>$900</td></tr><tr><td>Food</td><td>$400</td></tr>
<tr><td colspan="2"><b>Plan B</b></td></tr>
<tr><td>Rent</td><td>$700</td></tr><tr><td>Food</td><td>$500</td></tr></tbody></table>
<p>Table 3.5</p>
<table><thead><tr><th colspan="2">Survey results</th></tr></thead>
<tbody><tr><td>Yes</td><td>12</td></tr><tr><td>No</td><td>3</td></tr>
<tr><td>Maybe</td><td>5</td></tr></tbody></table>
<p>Table 3.6</p>
<table><thead><tr><th colspan="2">Answers</th></tr><tr id="answer-row"><th id="answer">Answer</th><th id="count">Count</th></tr></thead>
<tbody><tr><td colspan="2"><b>Group A</b></td></tr><tr><td>Yes</td><td>12</td></tr>
<tr><td>No</td><td>3</td></tr><tr><td colspan="2"><b>Group B</b></td></tr>
<tr><td>Yes</td><td>7</td></tr><tr><td>No</td><td>9</td></tr></tbody></table>
<p>Table 3.7 Each field holds one value.</p>
<table><thead><tr><th>Field</th><th>Value</th></tr></thead>
<tbody><tr><td colspan="2"><b>Before</b></td></tr><tr><td>Name</td><td>Ada</td></tr>
<tr><td colspan="2"><b>After</b></td></tr><tr><td>Name</td><td>Grace</td></tr></tbody></table>
</main></body></html>
"""


def case_bands(work):
    """An HTML source's title rows and bands: split for an HTML target,
    kept as one grouped table for a Markdown one, and the grouped table
    read back splits the same way, a table's foot kept in each, and a head
    that is one cell across, a band or a title. And a page with no title
    stays one."""
    os.makedirs(work)
    with open(os.path.join(work, "bands.html"), "w", encoding="utf-8") as fh:
        fh.write(BANDED)
    with open(os.path.join(work, "heads.html"), "w", encoding="utf-8") as fh:
        fh.write(HEADS)
    with open(os.path.join(work, "untitled.html"), "w", encoding="utf-8") as fh:
        fh.write('<!DOCTYPE html><html lang="en"><head></head><body>'
                 "<p>No title here.</p></body></html>\n")
    pages = ("bands.html", "heads.html", "untitled.html")
    def run_with(where, config):
        with open(os.path.join(where, "conversion.yaml"), "w",
                  encoding="utf-8") as fh:
            fh.write(config)
        return run_in(where, "  contents:\n    - bands\n    - heads\n    - untitled\n")
    run_with(work, "targets:\n  html:\n    format: html\n"
                   "  md:\n    format: markdown\n")
    page = read(work, "html", "bands.html") if exists(
        work, "html", "bands.html") else ""
    heads = read(work, "html", "heads.html") if exists(
        work, "html", "heads.html") else ""
    md = read(work, "md", "bands.md") if exists(work, "md", "bands.md") else ""
    captions = lambda text: [" ".join(re.sub(r"<[^>]+>", "", c).split())
                             for c in re.findall(r"<caption>(.*?)</caption>",
                                                 text, re.S)]
    back = work + "-from-md"
    shutil.copytree(os.path.join(work, "md"), back)
    run_with(back, "targets:\n  html:\n    format: html\n")
    again = read(back, "html", "bands.html") if exists(
        back, "html", "bands.html") else ""
    heads_again = read(back, "html", "heads.html") if exists(
        back, "html", "heads.html") else ""
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
    for name in pages:
        shutil.copy(os.path.join(column, "html", name), column_again)
    run_with(column_again, column_config)
    cells = lambda text: re.findall(r"<t[hd][^>]*>[^<]*", text)
    fixed = work + "-from-html"
    os.makedirs(fixed)
    for name in pages:
        shutil.copy(os.path.join(work, "html", name), fixed)
    run_with(fixed, "targets:\n  html:\n    format: html\n")
    flat = lambda text: " ".join(re.sub(r"<[^>]+>", " ", text).split())
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
        ("a split table's first part keeps the table's id, so a link to the "
         "table lands",
         lambda: re.search(r'<table id="costs"', page)
         and re.search(r'<table id="costs-2"', page)
         and 'href="#costs"' in page),
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
        # A table's foot went with every part it was split into, and with
        # the table grouped or in a column.
        ("a split table's foot comes after its last part, grouped or in a "
         "column, and read back",
         lambda: all(text.count("Source: a survey made up for the test") == 1
                     for text in (page, md, again, in_column))
                 and re.search(r"Group two</caption>.*?<tfoot>.*?Source: a survey",
                               page, re.S)
                 and not re.search(r"Group one</caption>(?:(?!</table>).)*<tfoot>",
                                   page, re.S)
                 and re.search(r'<tfoot>\s*<tr>\s*<td colspan="3"[^>]*>Source: a survey',
                               in_column)),
        # A band that was the table's head headed every part, the first
        # captioned "Part 1"; a title there declared a header row, which the
        # first row of data became once the title was the caption.
        ("a band that is a table's head heads the first part alone, and the "
         "rows under it stay data",
         lambda: [c for c in captions(heads) if c.startswith("Table 3.4")]
         == ["Table 3.4 Plans: Plan A", "Table 3.4 Plans: Plan B"]
         and flat(heads).count("Plan A") == 1
         and not re.search(r'<th scope="col">(<strong>)?(Rent|\$)', heads)),
        ("a title that is a table's head is its caption, and the row under it "
         "stays data",
         lambda: "Table 3.5 Survey results" in captions(heads)
         and not re.search(r'<th scope="col">(<strong>)?(Yes|12)', heads)
         and re.search(r'<th scope="row">(<strong>)?Yes', heads)),
        ("a title over the header row in a table's head is its caption, and "
         "the header row heads each part",
         lambda: [c for c in captions(heads) if c.startswith("Table 3.6")]
         == ["Table 3.6 Answers: Group A", "Table 3.6 Answers: Group B"]
         and len(re.findall(r'<th scope="col">(?:<span id="answer">'
                            r'</span>)?(?:<strong>)?Answer<', heads)) == 2
         and "colspan" not in heads),
        # Each part's copy of the header row kept its ids.
        ("a header row's ids, and its cells', stay with the first part, not "
         "repeated in the next",
         lambda: all(heads.count(f'id="{name}"') == 1
                     for name in ("answer-row", "answer", "count"))
         and re.search(r'Group A(?:</strong>)?</caption>\s*<thead>\s*'
                       r'<tr id="answer-row">',
                       heads)
         and "<span></span>" not in heads),
        ("a part's words follow a caption that ends a sentence after a space, not a "
         "colon",
         lambda: [c for c in captions(heads) if c.startswith("Table 3.7")]
         == ["Table 3.7 Each field holds one value. Before",
             "Table 3.7 Each field holds one value. After"]),
        ("and read back from Markdown or HTML, they split into the same captions",
         lambda: captions(heads) and captions(heads_again) == captions(heads)
         and captions(read(fixed, "html", "heads.html")) == captions(heads)),
    ]


# A table whose groups each open with a header row of their own, the first
# row's but for its first cell, as in OpenStax's economics books, its
# caption and each group's first cell holding an id, as a book unpacked
# from CNXML has them.
GROUP_HEADS = """<!DOCTYPE html><html lang="en"><head><title>Aggregates</title></head>
<body><main><h1>Aggregates</h1>
<table id="money"><caption><span id="money-cap"></span>Table 3.7 Money</caption>
<tbody><tr><td id="m1"><b>Elements of M1</b></td><td><b>Millions</b></td></tr>
<tr><td>Cash</td><td>350</td></tr><tr><td>Deposits</td><td>1210</td></tr>
<tr><td id="m2"><b>Elements of M2</b></td><td><b>Millions</b></td></tr>
<tr><td>M1</td><td>1560</td></tr><tr><td>Savings</td><td>562</td></tr></tbody></table>
</main></body></html>
"""

# The same table as a page can group it, each group a <tbody> opening
# with a row of <th>, as a Markdown target writes it.
GROUPED_BY_PAGE = """<!DOCTYPE html><html lang="en"><head><title>Aggregates</title></head>
<body><main><h1>Aggregates</h1>
<table id="money"><caption><span id="money-cap"></span>Table 3.7 Money</caption>
<tbody><tr><th><span id="m1"></span><b>Elements of M1</b></th><th><b>Millions</b></th></tr>
<tr><th>Cash</th><td>350</td></tr><tr><th>Deposits</th><td>1210</td></tr></tbody>
<tbody><tr><th><span id="m2"></span><b>Elements of M2</b></th><th><b>Millions</b></th></tr>
<tr><th>M1</th><td>1560</td></tr><tr><th>Savings</th><td>562</td></tr></tbody></table>
</main></body></html>
"""


# Bands one cell across, each over a group's own header row, the first's
# but for its first cell: the guess splits at the bands and makes each
# part's first row its header row, and its first column a header column.
BANDED_HEADS = """<!DOCTYPE html><html lang="en"><head><title>Measures</title></head>
<body><main><h1>Measures</h1>
<table id="measures"><caption>Table 3.8 Money</caption>
<tbody><tr><td colspan="2"><b>Narrow money</b></td></tr>
<tr><td><b>Elements of M1</b></td><td><b>Millions</b></td></tr>
<tr><td>Cash</td><td>350</td></tr><tr><td>Deposits</td><td>1210</td></tr>
<tr><td colspan="2"><b>Broad money</b></td></tr>
<tr><td><b>Elements of M2</b></td><td><b>Millions</b></td></tr>
<tr><td>M1</td><td>1560</td></tr><tr><td>Savings</td><td>562</td></tr></tbody></table>
</main></body></html>
"""


def case_group_heads(work):
    """A table split where each group's own header row begins, the words
    of the row's first cell in its part's caption and the table's caption
    in every part's: what's copied keeps no id, which the row and the
    first part's caption keep. And a Markdown target, which keeps the
    table whole, keeps its groups and the rows that head them, which split
    it again when it's read back, as they do a page's that groups it so,
    and as they do under bands."""
    os.makedirs(work)
    for name, text in (("money", GROUP_HEADS), ("measures", BANDED_HEADS)):
        with open(os.path.join(work, name + ".html"), "w", encoding="utf-8") as fh:
            fh.write(text)
    def run_with(where, config, pages=("money", "measures")):
        with open(os.path.join(where, "conversion.yaml"), "w",
                  encoding="utf-8") as fh:
            fh.write(config)
        return run_in(where, "  contents:\n"
                      + "".join(f"    - {name}\n" for name in pages))
    def output(where, target, name):
        ext = "md" if target == "md" else "html"
        return read(where, target, f"{name}.{ext}") if exists(
            where, target, f"{name}.{ext}") else ""
    both = "targets:\n  html:\n    format: html\n  md:\n    format: markdown\n"
    run_with(work, both)
    page, md = output(work, "html", "money"), output(work, "md", "money")
    back = work + "-from-md"
    shutil.copytree(os.path.join(work, "md"), back)
    run_with(back, both)
    grouped = work + "-grouped"
    os.makedirs(grouped)
    with open(os.path.join(grouped, "money.html"), "w", encoding="utf-8") as fh:
        fh.write(GROUPED_BY_PAGE)
    run_with(grouped, "targets:\n  html:\n    format: html\n", ("money",))
    body = lambda text: text[text.find("<body>"):]
    captions = lambda text: [" ".join(re.sub(r"<[^>]+>", "", c).split())
                             for c in re.findall(r"<caption>(.*?)</caption>",
                                                 text, re.S)]
    headed = lambda text, n: re.search(
        r'<tbody>\s*<tr>\s*<th>(?:<span id="m%d"></span>)?(?:<strong>)?'
        r'Elements of M%d' % (n, n), text)
    measures = output(work, "html", "measures")
    return [
        # The ids went with the words into the captions: the table's
        # caption's into the second part's, each row's into its part's.
        ("a group's own header row's ids, and the table's caption's, aren't "
         "repeated in the parts' captions",
         lambda: captions(page) == ["Table 3.7 Money: Elements of M1",
                                    "Table 3.7 Money: Elements of M2"]
         and all(page.count(f'id="{name}"') == 1
                 for name in ("money-cap", "m1", "m2"))
         and "<span></span>" not in page),
        # Pandoc's Markdown writer makes a body's head an ordinary row of
        # one body: the groups went, and the rows that headed them, so the
        # table read back had neither.
        ("a Markdown target keeps the groups, each headed by its own header "
         "row",
         lambda: md.count("<tbody>") == 2
         and all(headed(md, n) for n in (1, 2))),
        # Read back, a row heading a group was a band only one cell across,
        # so the HTML was one table, grouped, where the page's was split;
        # and a page grouping the table so, its <th> cells declaring a
        # header column alone, split it into parts with no header row.
        ("read back, and from a page that groups the table so, the groups "
         "split as they did, and a Markdown target writes them again as it did",
         lambda: "<thead>" in page and body(output(back, "html", "money")) == body(page)
         and body(output(grouped, "html", "money")) == body(page)
         and output(back, "md", "money") == md),
        # Under its band, a group's header row read back was a row of data,
        # or, declared with the header column alone, a part's header row
        # moved into its body: the parts had no header row, and the copy no
        # groups.
        ("so do groups under bands, each part headed by its group's header row",
         lambda: captions(measures) == ["Table 3.8 Money: Narrow money",
                                        "Table 3.8 Money: Broad money"]
         and len(re.findall(r'<thead>\s*<tr>\s*<th scope="col">', measures)) == 2
         and body(output(back, "html", "measures")) == body(measures)
         and output(back, "md", "measures") == output(work, "md", "measures")),
    ]


# Headings the page gives no id, whose ids Pandoc makes from their words:
# one over a table with the same id, which a link names, and one inside a
# div with its own. And headings given an id of the page's: by a section,
# whose id the reader moves to its heading when the two agree, and by an
# anchor in a heading the reader left with none; each over a table with
# the same.
HEADING_IDS = """<!DOCTYPE html><html lang="en"><head><title>Costs</title></head>
<body><main><h1>Costs</h1>
<p>See <a href="#costs">the table</a> and <a href="#notes">the notes</a>.</p>
<h2>Prices</h2>
<table id="costs"><caption>Table 1.1 Costs</caption><tr><th>Item</th><th>Cost</th></tr>
<tr><td>Rent</td><td>900</td></tr></table>
<div id="notes"><p>Two notes.</p><h2>Notes</h2><p>The first.</p></div>
<section id="sources"><h2>Sources</h2><p>A list.</p></section>
<table id="sources"><caption>Table 1.2 Sources</caption><tr><th>Name</th><th>Year</th></tr>
<tr><td>A survey</td><td>2020</td></tr></table>
<section id="faq"><h2><a id="questions"></a>FAQ</h2><p>Ask.</p></section>
<table id="questions"><caption>Table 1.3 Questions</caption><tr><th>Question</th><th>Answer</th></tr>
<tr><td>Why?</td><td>Because.</td></tr></table>
</main></body></html>
"""

# A Markdown heading over a table with its id: [Prices] links to the
# heading by the id Pandoc gives it.
HEADING_IDS_MD = """# Prices

See [the table](#prices) and [Prices].

| Item | Cost |
|------|------|
| Rent | 900  |

: Table 2.1 Prices {#prices}
"""


# Headings that skip levels, as LibreTexts sets a box's legend and its
# solution under a section's heading: a page with a title, and one without.
LEVELS_TITLED = """# The Page

Text.

### A Section

#### Its Subsection

##### Deeper

## Second

Text.

###### A Legend

::: box
##### Example 2.1

A question.

###### Solution

An answer.
:::

### Third
"""

LEVELS_UNTITLED = """## Only Second

#### Fourth
"""


def case_heading_levels(work):
    """heading_levels: outline, the default, lifts a heading that skips a
    level to one below the heading it's under, and what's under it with
    it, a page's first under its title to H2, a box's legend too; one that
    skips nothing keeps its level; the run says how many moved; the output
    check finds no skip; and source keeps the source's levels."""
    def book(name, setting=""):
        where = os.path.join(work, name)
        os.makedirs(where)
        for stem, text in (("levels", LEVELS_TITLED), ("untitled", LEVELS_UNTITLED)):
            with open(os.path.join(where, stem + ".md"), "w", encoding="utf-8") as fh:
                fh.write(text)
        result = convert(where, setting + "targets:\n  html:\n    format: html\n"
                                          "  md:\n    format: markdown\n",
                         fixtures=())
        pages = {stem: read(where, "html", stem + ".html")
                 if exists(where, "html", stem + ".html") else ""
                 for stem in ("levels", "untitled")}
        check = os.path.join(where, "output-check.csv")
        skips = 0
        if os.path.exists(check):
            with open(check, encoding="utf-8", newline="") as fh:
                skips = sum(1 for row in csv.DictReader(fh)
                            if row["Check"] == "heading-skips-level"
                            or row["Check"] == "vnu:error" and "skipping" in row["Detail"])
        return where, result, pages, skips

    def levels(page):
        return [(int(level), html_lib.unescape(re.sub(r"<[^>]+>", "", text)).strip())
                for level, text in re.findall(r"<h([1-6])[^>]*>(.*?)</h\1>", page, re.S)]
    a, outline, pages, skips = book("outline")
    said = outline.stdout + outline.stderr
    b, source, kept, kept_skips = book("source", "defaults:\n  heading_levels: source\n")
    return [
        ("a heading that skips a level is lifted to one below the heading it's under, what's "
         "under it with it, a page's first under its title to H2, and a box's legend too",
         lambda: outline.returncode == 0
         and levels(pages["levels"]) == [(1, "The Page"), (2, "A Section"),
                                         (3, "Its Subsection"), (4, "Deeper"),
                                         (2, "Second"), (3, "A Legend"), (3, "Example 2.1"),
                                         (4, "Solution"), (3, "Third")]),
        ("a page without a title keeps its first heading's level, and what's under it closes up",
         lambda: levels(pages["untitled"])[-2:] == [(2, "Only Second"), (3, "Fourth")]),
        ("the run says how many moved, and the output check finds no skip",
         lambda: "7 heading(s) on 2 page(s) moved up to close the levels they skipped" in said
         and "(levels: h3 to h2 (A Section))" in said
         and skips == 0),
        ("heading_levels: source keeps the source's levels, and the output check names "
         "each skip",
         lambda: source.returncode == 0
         and levels(kept["levels"]) == [(1, "The Page"), (3, "A Section"),
                                        (4, "Its Subsection"), (5, "Deeper"),
                                        (2, "Second"), (6, "A Legend"), (5, "Example 2.1"),
                                        (6, "Solution"), (3, "Third")]
         and "moved up to close" not in source.stdout + source.stderr
         and kept_skips == 3),
    ]


def case_heading_ids(work):
    """A heading an HTML page gave no id, whose id Pandoc makes from its
    words, gives way to a table's or a div's, before it or around it,
    which an author's link names. One with an id of the page's keeps it
    and the table after it is renamed, as a Markdown heading keeps its,
    and each such rename is a row of ids-renamed.csv."""
    os.makedirs(work)
    with open(os.path.join(work, "costs.html"), "w", encoding="utf-8") as fh:
        fh.write(HEADING_IDS)
    with open(os.path.join(work, "prices.md"), "w", encoding="utf-8") as fh:
        fh.write(HEADING_IDS_MD)
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  html:\n    format: html\n  md:\n    format: markdown\n")
    run_in(work, "  contents:\n    - costs\n    - prices\n")
    def output(target, name):
        ext = "md" if target == "md" else "html"
        return read(work, target, f"{name}.{ext}") if exists(
            work, target, f"{name}.{ext}") else ""
    costs, prices = output("html", "costs"), output("html", "prices")
    rows = []
    if exists(work, "ids-renamed.csv"):
        with open(os.path.join(work, "ids-renamed.csv"), encoding="utf-8",
                  newline="") as fh:
            rows = list(csv.reader(fh))
    tag = lambda text, name: (re.search(r'<(\w+)[^>]*\bid="%s"' % name, text)
                              or [None, None])[1]
    return [
        ("a heading whose id is from its words gives way to the table's and "
         "the div's, so the links reach them",
         lambda: tag(costs, "costs") == "table" and tag(costs, "notes") == "div"
         and tag(costs, "costs-1") == "h1" and tag(costs, "notes-1") == "h2"
         and 'href="#costs"' in costs),
        ("one with an id of the page's keeps it, as a Markdown heading does, "
         "and the table renamed is reported",
         lambda: tag(costs, "sources") == "h2" and tag(costs, "sources-1") == "table"
         and tag(costs, "questions") == "h2"
         and tag(costs, "questions-1") == "table"
         and tag(prices, "prices") == "h1" and tag(prices, "prices-1") == "table"
         and rows == [["Page", "Id", "Kept by", "Renamed", "New id"],
                      ["costs", "questions", "heading: FAQ",
                       "table: Table 1.3 Questions", "questions-1"],
                      ["costs", "sources", "heading: Sources",
                       "table: Table 1.2 Sources", "sources-1"],
                      ["prices", "prices", "heading: Prices",
                       "table: Table 2.1 Prices", "prices-1"]]),
        ("and the mark htmlrepair.py puts on a heading with no id is gone",
         lambda: costs and all("ti-auto-id" not in text for text in
                               (costs, prices, output("md", "costs"),
                                output("md", "prices")))),
    ]


# A table split at its bands whose second group is laid out on half its
# columns, each cell across two, as Foundations of Information Systems'
# normal forms are.
NARROW_GROUP = """<!DOCTYPE html><html lang="en"><head><title>Forms</title></head>
<body><main><h1>Forms</h1>
<table><caption>Table 3.7 Third Normal Form</caption>
<colgroup><col style="width: 10%"><col style="width: 40%"><col style="width: 20%">
<col style="width: 30%"></colgroup>
<thead><tr><th colspan="4">Orders</th></tr></thead>
<tbody><tr><td>OrderID</td><td>Product</td><td>Price</td><td>CustomerID</td></tr>
<tr><td>101</td><td>Shirt</td><td>$75</td><td>1</td></tr>
<tr><td>102</td><td>Hat</td><td>$50</td><td>2</td></tr>
<tr><td colspan="4">Customers</td></tr>
<tr><td colspan="2">CustomerID</td><td colspan="2">CustomerName</td></tr>
<tr><td colspan="2">1</td><td colspan="2">John Doe</td></tr>
<tr><td colspan="2">2</td><td colspan="2">Jane Smith</td></tr></tbody></table>
</main></body></html>
"""


def case_narrow_group(work):
    """A part of a split table laid out on fewer columns than the table:
    a column no cell of the part begins in is closed up."""
    os.makedirs(work)
    with open(os.path.join(work, "forms.html"), "w", encoding="utf-8") as fh:
        fh.write(NARROW_GROUP)
    with open(os.path.join(work, "conversion.yaml"), "w",
              encoding="utf-8") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    run_in(work, "  contents:\n    - forms\n")
    page = read(work, "html", "forms.html") if exists(
        work, "html", "forms.html") else ""
    parts = re.findall(r"<table.*?</table>", page, re.S)
    return [
        # The second part's cells each spanned two columns, columns 2 and 4
        # began in no cell: the Nu checker's "Table column 2 established
        # by element th has no cells beginning in it".
        ("a part laid out on fewer columns than the table spans none it "
         "doesn't begin a cell in, each column's width the two's",
         lambda: len(parts) == 2 and "colspan" not in parts[1]
         and re.findall(r'<col style="width: (\d+)%"', parts[1]) == ["50", "50"]
         and len(re.findall(r"<col ", parts[0])) == 4),
    ]

def case_scheme_case(work):
    """A link whose scheme is in capitals, as a source may type it, is a
    link to another site, not a file of the book's."""
    os.makedirs(work)
    with open(os.path.join(work, "caps.html"), "w", encoding="utf-8") as fh:
        fh.write('<!DOCTYPE html><html lang="en"><head><title>Capitals</title>'
                 '</head><body><main><h1>Capitals</h1><p>The <a href='
                 '"Http://example.org/study.pdf">study</a>, <a href='
                 '"HTTPS://example.org/">its site</a>, and <a href='
                 '"MAILTO:a@example.org">its authors</a>.</p><p><img src='
                 '"Http://example.org/chart.png" alt="A chart of the study\'s '
                 'findings"></p></main></body></html>\n')
    with open(os.path.join(work, "conversion.yaml"), "w",
              encoding="utf-8") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    run = run_in(work, "  contents:\n    - caps\n")
    check = read(work, "output-check.csv") if exists(
        work, "output-check.csv") else ""
    return [
        # Each was taken for a file the book lacks: the output check's
        # link-to-missing-file, and the packager stopped the run.
        ("a link or a picture whose scheme is in capitals names no missing "
         "file, and the run packages the book",
         lambda: run.returncode == 0 and "link-to-missing-file" not in check
         and "not on disk" not in run.stdout + run.stderr
         and 'href="Http://example.org/study.pdf"' in read(
             work, "html", "caps.html")),
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
        return subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick",
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
    # Both names an unpacked project.yaml could take are here: the run
    # stops, and stops before moving anything, the pages included.
    clash = work + "-clash"
    fresh(clash, {"project.yaml": "project:\n  title: Mine\n",
                  "project-unpacked.yaml": "project:\n  title: Older\n"})
    clashed = run(clash)
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
        ("a name the archive's files would take, here already, stops the "
         "run before anything is moved",
         lambda: clashed.returncode != 0
         and "project-unpacked.yaml is already here" in clashed.stderr
         + clashed.stdout
         and not [n for n in os.listdir(clash) if n.endswith(".html")]
         and "Older" in open(os.path.join(clash,
                                          "project-unpacked.yaml")).read()),
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
    run = subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"],
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
    subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet",
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
    subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"],
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
        return subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick",
                               "--quiet"], cwd=where, capture_output=True,
                              text=True, stdin=subprocess.DEVNULL)
    first = run(book)
    if exists(book, "ch2.md"):
        with open(os.path.join(book, "ch2.md"), "w") as fh:
            fh.write("# Two\n\nThe corrected draft.\n")
    second = run(book)
    with zipfile.ZipFile(os.path.join(book, "another.zip"), "w") as z:
        z.writestr("other.md", "# Other\n")
    second_run = run(book)
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
    # An OpenStax DOCX download: two folders around the Word files.
    openstax = os.path.join(work, "openstax")
    os.makedirs(openstax)
    with zipfile.ZipFile(os.path.join(openstax, "Book_-_DOCX_Customization.zip"), "w") as z:
        for name in ("tables.docx", "metadata.docx"):
            z.write(os.path.join(FIXTURES, name),
                    "Book_-_DOCX_Customization/book/" + name)
    with open(os.path.join(openstax, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    run(openstax)
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
        ("Word files two folders deep, as OpenStax zips them, are sources "
         "and convert", lambda: exists(openstax, "tables.docx")
         and exists(openstax, "html", "tables.html")
         and exists(openstax, "html", "metadata.html")
         and not exists(openstax, "Book_-_DOCX_Customization")),
        ("with sources here, a second archive beside the first (a cartridge "
         "--zip built, say) isn't read, and the run goes on",
         lambda: second_run.returncode == second.returncode
         and "More than one thing" not in second_run.stderr),
        ("a slide deck is a zip but not an archive to unpack: a folder of decks is "
         "slides, and one that isn't a deck says so",
         lambda: "Unpacked" not in deck_run.stderr
         and not exists(deck, "[Content_Types].xml")
         and "Slides: 1 PowerPoint deck(s)" in deck_run.stderr
         and "talk.pptx couldn't be read as a PowerPoint deck" in deck_run.stderr),
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
    run = subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"],
                         cwd=work, capture_output=True, text=True,
                         stdin=subprocess.DEVNULL)
    page = read(work, "html", "growth.html") if exists(work, "html", "growth.html") else ""
    back = work + "-back"
    if exists(work, "md"):
        shutil.copytree(os.path.join(work, "md"), back)
        with open(os.path.join(back, "conversion.yaml"), "w") as fh:
            fh.write("targets:\n  html:\n    format: html\n")
        try:
            subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"],
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


MATH_WORDS = """<!DOCTYPE html><html lang="en"><head><title>Value</title></head><body><main><h1>Value</h1>
<p>Value is <math xmlns="http://www.w3.org/1998/Math/MathML"><mi mathvariant="normal">Value</mi><mo>=</mo><mfrac><mi mathvariant="normal">Benefits</mi><mi mathvariant="normal">Price</mi></mfrac></math>, and the area is <math xmlns="http://www.w3.org/1998/Math/MathML"><mo>&#x222B;</mo><mi>sin</mi><mi>x</mi><mi>dx</mi></math>.</p>
</main></body></html>
"""
MATH_WORDS_MATHJAX = """<!DOCTYPE html><html lang="en"><head><title>Moles</title></head><body><main><h1>Moles</h1>
<p>A mole is <span class="MathJax" id="MathJax-Element-1-Frame"><nobr><span class="math" id="MathJax-Span-1"><span><span class="mrow" id="MathJax-Span-2"><span class="mn" id="MathJax-Span-3">1</span><span class="mi" id="MathJax-Span-4">mol</span></span></span></span></nobr></span> of it.</p>
</main></body></html>
"""


def case_math_words(work):
    """A word in a formula's identifier, an <mi> of more than two letters,
    is written whole and upright, as the page shows it, where Pandoc made
    it italic letters; two letters, and a name Pandoc keeps whole, are
    left to it. A formula MathJax drew gets the same once it's MathML
    again, on a page of its own, so each is seen to."""
    import importlib.util
    if not (importlib.util.find_spec("html5lib") or importlib.util.find_spec("lxml")):
        return [("skip: HTML sources need html5lib or lxml", lambda: True)]
    os.makedirs(work)
    for name, markup in (("value.html", MATH_WORDS), ("moles.html", MATH_WORDS_MATHJAX)):
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(markup)
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"],
                   cwd=work, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    page = read(work, "html", "value.html") if exists(work, "html", "value.html") else ""
    moles = read(work, "html", "moles.html") if exists(work, "html", "moles.html") else ""
    return [
        ("a word is text, whole and upright",
         lambda: all(re.search(r'<mtext mathvariant="normal">%s</mtext>' % w, page)
                     for w in ("Value", "Benefits", "Price"))
         and "<mi>V</mi>" not in page),
        ("a name Pandoc keeps whole, and two letters, are Pandoc's",
         lambda: re.search(r"<mi[^>]*>sin</mi>", page)
         and re.search(r"<mi>d</mi>\s*<mi>x</mi>", page)),
        ("so is a word in a formula MathJax drew, once it's MathML again",
         lambda: re.search(r"<mn>1</mn>\s*<mtext[^>]*>mol</mtext>", moles)),
    ]


EMPTY_ROWS = """<!DOCTYPE html><html lang="en"><head><title>Bars</title></head><body><main><h1>Bars</h1>
<p>Evaluated, <math xmlns="http://www.w3.org/1998/Math/MathML"><msubsup><mo>|</mo><mtable><mtr><mtd><mn>0</mn></mtd></mtr><mtr><mtd></mtd></mtr></mtable><mtable><mtr><mtd></mtd></mtr><mtr><mtd><mn>2</mn></mtd></mtr></mtable></msubsup></math> is the bar.</p>
<p>And in a display, <math xmlns="http://www.w3.org/1998/Math/MathML" display="block"><msubsup><mo>|</mo><mtable><mtr><mtd><mn>1</mn></mtd></mtr><mtr><mtd></mtd></mtr></mtable><mtable><mtr><mtd></mtd></mtr><mtr><mtd><mn>3</mn></mtd></mtr></mtable></msubsup></math> too.</p>
</main></body></html>
"""


def case_empty_rows(work):
    """An evaluation bar as OpenStax writes it, its limits in mtables of
    two rows, one empty, which texmath writes with an empty line before the
    matrix's end: the markdown target writes the empty line as {}, so the
    page reads back with each formula whole, where the Markdown reader had
    ended the paragraph there, the formula read back as text and raw TeX;
    and the asciidoc target, which writes a formula in text on one line,
    writes the row as {} too, so LaTeX, for which \\\\ before a matrix's end
    makes no row, sets it."""
    import importlib.util
    if not (importlib.util.find_spec("html5lib") or importlib.util.find_spec("lxml")):
        return [("skip: HTML sources need html5lib or lxml", lambda: True)]
    os.makedirs(work)
    with open(os.path.join(work, "bars.html"), "w", encoding="utf-8") as fh:
        fh.write(EMPTY_ROWS)
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  md:\n    format: markdown\n  adoc:\n    format: asciidoc\n")
    subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"],
                   cwd=work, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    md = read(work, "md", "bars.md") if exists(work, "md", "bars.md") else ""
    adoc = read(work, "adoc", "bars.adoc") if exists(work, "adoc", "bars.adoc") else ""

    def back(source, reader):
        """The MathML Pandoc makes of the target's file read back."""
        done = subprocess.run(["pandoc", "-f", reader, "-t", "html", "--mathml"], input=source,
                              capture_output=True, text=True)
        return done.stdout if done.returncode == 0 else ""
    md_back, adoc_back = back(md, "markdown"), back(adoc, "asciidoc")
    rows = r"<mtr>\s*<mtd[^>]*>\s*</mtd>\s*</mtr>"
    return [
        ("the markdown target writes an empty row as {}, no empty line in a formula",
         lambda: md.count("\\\\\n{}\n\\end{matrix}") == 2 and "$|_{" in md
         and not re.search(r"\\\\\s*\n\s*\n\s*\\end", md)),
        ("read back, each formula is whole, its empty rows kept",
         lambda: md_back.count("<math") == 2 and len(re.findall(rows, md_back)) == 4
         and "$" not in re.sub(r"<[^>]+>", "", md_back)),
        ("the asciidoc target writes the row as {} in a formula in text and a display, "
         "which reads back with its empty rows",
         lambda: "0 \\\\ {} \\end{matrix}" in adoc and "1 \\\\\n{}\n\\end{matrix}" in adoc
         and adoc_back.count("<math") == 2 and len(re.findall(rows, adoc_back)) == 4),
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
    subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"],
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
    validated = epubcheck((glob.glob(os.path.join(work, "epub", "*.epub")) or [""])[0])
    bad = r"<(figure|div|pre|table)\b[^>]*\b(width|target)="
    return [
        ("no width or target on a block, in the HTML or the EPUB",
         lambda: page and epub_text and not re.search(bad, page)
         and not re.search(bad, epub_text)),
        ("an image block's width is its image's",
         lambda: re.search(r'<img [^>]*width="300"', page)),
        ("epubcheck finds nothing to object to, where it's installed",
         lambda: validated == [] if validated is not None else True),
    ]


def case_quick(work):
    """--quick: the output check without epubcheck, the Nu checker, and
    veraPDF, saying so; --wcag, with --verbose, in a run that made no PDF,
    saying there was none to check; and --verbose alone saying it changes
    nothing. The run without --quick has the
    validators hidden (each variable naming a file that isn't there), so
    it asks for them and is told they're missing, without starting Java."""
    os.makedirs(work)
    with open(os.path.join(work, "ch.md"), "w") as fh:
        fh.write("# One\n\nText.\n")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n")

    def run(*flags, env=None):
        result = subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quiet", *flags],
                                cwd=work, capture_output=True, text=True,
                                stdin=subprocess.DEVNULL, env=env)
        return result.stdout + result.stderr
    quick = run("--quick", "--wcag", "--verbose")
    unasked = run("--quick", "--verbose")
    nowhere = os.path.join(work, "no-such-validator")
    full = run(env=dict(os.environ, EPUBCHECK_JAR=nowhere, VNU_JAR=nowhere, VERAPDF=nowhere))
    return [
        ("--quick checks the pages without the validators, and says so",
         lambda: "Output check: 1 page(s)" in quick
         and "epubcheck, the Nu HTML checker, and veraPDF not run (--quick)." in quick
         and "VNU_JAR" not in quick),
        ("and --wcag, in a run that made no PDF, says there was none to check, after the "
         "verdict, without passing --wcag on",
         lambda: "veraPDF's WCAG checks not run: the run made no PDF." in quick
         and quick.index("Output check: 1 page(s)")
         < quick.index("veraPDF's WCAG checks not run: the run made no PDF.")
         and "veraPDF's WCAG checks not run (--quick)." not in quick),
        ("and --verbose without --wcag says it changes nothing",
         lambda: "--verbose lists veraPDF's WCAG checks one by one, with --wcag; without it, "
                 "it changes nothing." in unasked and "WCAG checks not run" not in unasked),
        ("without it, the run looks for them",
         lambda: "VNU_JAR" in full and "not run (--quick)" not in full),
    ]


def case_pdf_without_latex(work):
    """A pdf target on a machine without LuaLaTeX: the HTML is written,
    and the run stops saying what's missing and where to read about it,
    rather than a bare exit code. (pdf was NOT YET IMPLEMENTED until it
    was built; no format is now, so that path has no case.)"""
    os.makedirs(work)
    with open(os.path.join(work, "ch.md"), "w") as fh:
        fh.write("# One\n\nText.\n")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  web:\n    format: html\n  print:\n    format: pdf\n")
    # A path holding Pandoc and Python and nothing else, so LuaLaTeX
    # can't be found wherever it's installed.
    tools = work + "-bin"
    os.makedirs(tools)
    for program in ("pandoc", "python3", "file"):
        found = shutil.which(program)
        if found:
            os.symlink(found, os.path.join(tools, program))
    result = subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"],
                            cwd=work, capture_output=True, text=True,
                            stdin=subprocess.DEVNULL,
                            env=dict(os.environ, PATH=tools))
    said = result.stdout + result.stderr
    return [
        ("without LuaLaTeX, the HTML is written and the run stops",
         lambda: exists(work, "web", "ch.html") and result.returncode != 0),
        ("and says LuaLaTeX is missing and where to read about it",
         lambda: "lualatex is not on the path" in said
         and "installation" in said),
    ]


def case_word_bookmarks(work):
    """A docx target keeps the bookmarks a link goes to, from its own page
    or another, and JAWS's table bookmarks, and drops the rest, which NVDA
    announces; bookmarks: all keeps every one."""
    os.makedirs(work)
    with open(os.path.join(work, "a.md"), "w") as fh:
        fh.write("# Alpha\n\n## Linked here {#here}\n\nSee [below](#also) and "
                 "[the other page](b.md#there).\n\n## Not linked\n\nText.\n\n"
                 "## Also linked {#also}\n\n| Year | Output |\n|------|--------|\n"
                 "| 2020 | 5 |\n\nBack to [the top](#here).\n")
    with open(os.path.join(work, "b.md"), "w") as fh:
        fh.write("# Beta\n\n## Over there {#there}\n\nText.\n\n## Nobody comes here\n\nText.\n")

    def build(setting):
        with open(os.path.join(work, "conversion.yaml"), "w") as fh:
            fh.write("targets:\n  word:\n    format: docx\n" + setting)
        result = subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"],
                                cwd=work, capture_output=True, text=True,
                                stdin=subprocess.DEVNULL)
        names = {}
        for page in ("a", "b"):
            path = os.path.join(work, "word", page + ".docx")
            if os.path.exists(path):
                with zipfile.ZipFile(path) as z:
                    xml = z.read("word/document.xml").decode("utf-8")
                names[page] = set(re.findall(r'<w:bookmarkStart w:id="\d+" w:name="([^"]+)"', xml))
        return result.stdout + result.stderr, names
    said, linked = build("")
    _, every = build("    bookmarks: all\n")
    a, b = linked.get("a", set()), linked.get("b", set())
    return [
        ("a heading linked from its own page keeps its bookmark",
         lambda: {"_here", "_also"} <= a),
        ("a heading linked from another page keeps its bookmark",
         lambda: "_there" in b),
        ("headings nothing links to lose theirs",
         lambda: not any("not-linked" in n or "nobody" in n for n in a | b)
         and len(a) == 3 and len(b) == 1),
        ("JAWS's table bookmark stays",
         lambda: any(n.startswith("ColumnTitle_") for n in a)),
        ("the run says how many went", lambda: "no link goes to removed" in said),
        ("bookmarks: all keeps every one",
         lambda: len(every.get("a", set())) > len(a) and len(every.get("b", set())) > len(b)),
    ]


def case_pdf_svg_without_converter(work):
    """A book with an SVG image and a pdf target, on a machine without
    rsvg-convert: the run stops before LaTeX, saying what to install. The
    LuaLaTeX here is a script that answers the release probe and nothing
    else, so nothing past the check could run anyway."""
    os.makedirs(work)
    with open(os.path.join(work, "ch.md"), "w") as fh:
        fh.write("# One\n\n![A diagram](diagram.svg)\n")
    with open(os.path.join(work, "diagram.svg"), "w") as fh:
        fh.write('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
                 '<rect width="10" height="10"/></svg>\n')
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  web:\n    format: html\n  print:\n    format: pdf\n")
    tools = work + "-bin"
    os.makedirs(tools)
    for program in ("pandoc", "python3", "file"):
        found = shutil.which(program)
        if found:
            os.symlink(found, os.path.join(tools, program))
    fake = os.path.join(tools, "lualatex")
    with open(fake, "w") as fh:
        fh.write("#!/bin/sh\necho 'OERFMT:2026-06-01'\n")
    os.chmod(fake, 0o755)
    result = subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"],
                            cwd=work, capture_output=True, text=True,
                            stdin=subprocess.DEVNULL,
                            env=dict(os.environ, PATH=tools))
    said = result.stdout + result.stderr
    return [
        ("an SVG without rsvg-convert stops the PDF, naming what to install",
         lambda: result.returncode != 0 and "rsvg-convert" in said
         and "librsvg2-bin" in said and not exists(work, "print")),
    ]


def case_pdf_with_old_latex(work):
    """A LuaLaTeX whose LaTeX is older than the tagging code needs: the run
    stops saying which release it found and which it needs, before LaTeX
    fails on a test-phase package it can't find. The LuaLaTeX here is a
    script that answers the release probe and nothing else."""
    os.makedirs(work)
    with open(os.path.join(work, "ch.md"), "w") as fh:
        fh.write("# One\n\nText.\n")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  web:\n    format: html\n  print:\n    format: pdf\n")
    tools = work + "-bin"
    os.makedirs(tools)
    for program in ("pandoc", "python3", "file"):
        found = shutil.which(program)
        if found:
            os.symlink(found, os.path.join(tools, program))
    fake = os.path.join(tools, "lualatex")
    with open(fake, "w") as fh:
        fh.write("#!/bin/sh\necho 'OERFMT:2023-11-01'\n")
    os.chmod(fake, 0o755)
    result = subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"],
                            cwd=work, capture_output=True, text=True,
                            stdin=subprocess.DEVNULL,
                            env=dict(os.environ, PATH=tools))
    said = result.stdout + result.stderr
    return [
        ("an old LaTeX stops the PDF, naming the release found and the one needed",
         lambda: result.returncode != 0 and "2023-11-01" in said
         and "2026-06-01" in said and "tlmgr update --self --all" in said
         and not exists(work, "print")),
    ]


# What LuaHBTeX 1.24 (TeX Live 2026) writes in its log when a book outgrows
# one of TeX's tables: three million names fill its strings, a table of
# fixed size; a macro that calls itself without end fills the input stack.
CAPACITY_LOGS = {
    "strings": "! TeX capacity exceeded, sorry [number of strings=475604].\n"
               "\\iterate ->\\expandafter \\def \\csname x\\the \\n \n"
               "                                              \\endcsname {} \\advance \\n 1 \\i...\n"
               "l.4 ...name{} \\advance\\n1 \\ifnum\\n<3000000 \\repeat\n",
    "recursion": "! TeX capacity exceeded, sorry [input stack size=10000].\n"
                 "\\a ->\\a \n"
                 "        \\relax \n"
                 "l.4 \\def\\a{\\a\\relax}\\a\n",
}


def case_pdf_capacity(work):
    """A book that outgrows one of TeX's tables, and one whose macro calls
    itself without end: the PDF target names each for what it is. The
    LuaLaTeX here answers the release probe and fails a build as LuaTeX
    does, its log in LuaTeX's words; the real thing takes Pandoc's four
    LaTeX runs a build (it reruns while there's a .toc, which the pages'
    LaTeX always has, whatever the exit status), about eight seconds a run
    for the strings."""
    said = {}
    for name, log in CAPACITY_LOGS.items():
        book = os.path.join(work, name)
        os.makedirs(book)
        with open(os.path.join(book, "page.md"), "w") as fh:
            fh.write("# Page\n\nText.\n")
        with open(os.path.join(book, "conversion.yaml"), "w") as fh:
            fh.write("targets:\n  pdf:\n    format: pdf\n")
        tools = book + "-bin"
        os.makedirs(tools)
        for program in ("pandoc", "python3", "file"):
            found = shutil.which(program)
            if found:
                os.symlink(found, os.path.join(tools, program))
        # The shell's own commands only: the path holds nothing else.
        fake = os.path.join(tools, "lualatex")
        with open(fake, "w") as fh:
            fh.write("#!/bin/sh\n"
                     "case \"$*\" in *OERFMT*) echo 'OERFMT:2026-06-01'; exit 0 ;; esac\n"
                     "out=.\n"
                     "while [ $# -gt 1 ]; do\n"
                     "  [ \"$1\" = -output-directory ] && out=\"$2\"\n"
                     "  shift\n"
                     "done\n"
                     "name=${1##*/}\n"
                     "printf '%s\\n' " + " ".join("'%s'" % line for line in log.splitlines())
                     + " > \"$out/${name%.tex}.log\"\n"
                     "exit 1\n")
        os.chmod(fake, 0o755)
        result = subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"],
                                cwd=book, capture_output=True, text=True,
                                stdin=subprocess.DEVNULL, env=dict(os.environ, PATH=tools))
        said[name] = result.stdout + result.stderr
    return [
        ("a book too big for TeX's tables is named as that, with the way to raise them",
         lambda: "LaTeX ran out of number of strings" in said["strings"]
         and "max_strings" in said["strings"] and "wasn't built" in said["strings"]),
        ("a macro that calls itself without end is named as that, not as size",
         lambda: "LaTeX ran out of input stack size" in said["recursion"]
         and "calls itself without end" in said["recursion"]
         and "max_strings" not in said["recursion"]),
    ]


# A link to another site's text fragment, as OpenStax's references have
# one: its escapes are the address's own.
TEXT_FRAGMENT = ("https://example.org/apple#:~:text=Now%20worth%20a%20cool%20"
                 "%242.2,96%25%20of%20countries")


def case_html_ids(work):
    """An id with a space in it -- Scribble writes them -- becomes one
    without, and every link to it follows, from its own page or another,
    its escaped letters decoded and its other escapes kept; a link to
    another site's fragment, by its scheme or its host, is left as it is."""
    import importlib.util
    if not (importlib.util.find_spec("html5lib") or importlib.util.find_spec("lxml")):
        return [("skip: HTML sources need html5lib or lxml", lambda: True)]
    os.makedirs(work)
    with open(os.path.join(work, "a.html"), "w", encoding="utf-8") as fh:
        fh.write('<html lang="en"><head><title>A</title></head><body><h1>A</h1>'
                 '<h2 id="section 15">Fifteen</h2><p>See <a href="#section 15">here</a> '
                 'and <a href="#section%2015">there</a>, and <a href="' + TEXT_FRAGMENT
                 + '">a site</a>, and <a href="' + TEXT_FRAGMENT[len("https:"):]
                 + '">the site by its host</a>.</p>'
                 '<h2 id="caf\u00e9 1">Caf\u00e9</h2><p>To <a href="#caf%C3%A9%201">the '
                 'caf\u00e9</a>.</p><h2 id="na\u00efve">Na\u00efve</h2></body></html>')
    with open(os.path.join(work, "b.html"), "w", encoding="utf-8") as fh:
        fh.write('<html lang="en"><head><title>B</title></head><body><h1>B</h1>'
                 '<p>Back to <a href="a.html#section 15">fifteen</a>, to <a '
                 'href="a.html#caf%C3%A9%201">the caf\u00e9</a>, and to <a '
                 'href="a.html#na%C3%AFve">the na\u00efve</a>.</p></body></html>')
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n  epub:\n    format: epub3\n")
    with open(os.path.join(work, "project.yaml"), "w") as fh:
        fh.write("project:\n  identifier: org.example.ids\n  title: Ids\n")
    subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"],
                   cwd=work, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    a = read(work, "html", "a.html") if exists(work, "html", "a.html") else ""
    b = read(work, "html", "b.html") if exists(work, "html", "b.html") else ""
    checked = open(os.path.join(work, "output-check.csv")).read() if exists(
        work, "output-check.csv") else ""
    validated = epubcheck(os.path.join(work, "epub", "org.example.ids.epub"))
    # An escaped percent sign beside a space, in a book of its own, since an
    # id holding a % isn't one an EPUB takes.
    percent = work + "-percent"
    os.makedirs(percent)
    with open(os.path.join(percent, "c.html"), "w", encoding="utf-8") as fh:
        fh.write('<html lang="en"><head><title>C</title></head><body><h1>C</h1>'
                 '<h2 id="100% done">Done</h2><p>All <a href="#100%25%20done">done</a>.'
                 '</p></body></html>')
    with open(os.path.join(percent, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    with open(os.path.join(percent, "project.yaml"), "w") as fh:
        fh.write("project:\n  identifier: org.example.percent\n  title: Percent\n")
    subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"],
                   cwd=percent, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    c = read(percent, "html", "c.html") if exists(percent, "html", "c.html") else ""
    c_checked = open(os.path.join(percent, "output-check.csv")).read() if exists(
        percent, "output-check.csv") else ""
    return [
        ("an id's whitespace becomes a hyphen",
         lambda: 'id="section-15"' in a and 'id="section 15"' not in a),
        ("links to it follow, encoded or not, from its page or another",
         lambda: a.count('href="#section-15"') == 2
         and 'href="a.html#section-15"' in b),
        ("a link to another site's fragment is left as it is, escapes and all, "
         "by its scheme or its host",
         lambda: 'href="' + TEXT_FRAGMENT + '"' in a
         and 'href="' + TEXT_FRAGMENT[len("https:"):] + '"' in a),
        ("a link's escaped letters are decoded, as the id holds them, from its "
         "page or another, a space among them or not",
         lambda: re.search(r'id="caf(?:\u00e9|&#xE9;|&#233;)-1"', a)
         and re.search(r'href="#caf(?:\u00e9|&#xE9;|&#233;)-1"', a)
         and re.search(r'href="a\.html#caf(?:\u00e9|&#xE9;|&#233;)-1"', b)
         and re.search(r'href="a\.html#na(?:\u00ef|&#xEF;|&#239;)ve"', b)),
        ("its other escapes stay as written: a %25 beside a space is still one, "
         "and the output check finds its id",
         lambda: 'href="#100%25-done"' in c and 'id="100%-done"' in c
         and "missing-fragment" not in c_checked),
        ("nothing is reported missing, and epubcheck has no complaint",
         lambda: exists(work, "epub", "org.example.ids.epub") and "missing-fragment" not in checked
         and (validated == [] if validated is not None else True)),
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
                 'style="border: 0"></iframe></p>'
                 '<p><iframe src="https://example.org/y" title="Y" width="660" '
                 'height="371.4"></iframe></p></body></html>')
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"],
                   cwd=work, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    page = read(work, "html", "p.html") if exists(work, "html", "p.html") else ""
    images = re.findall(r"<img[^>]*>", page)
    report = open(os.path.join(work, "output-check.csv")).read() if exists(
        work, "output-check.csv") else ""
    frames = re.findall(r"<iframe[^>]*>", page) + ["", ""]
    frame = frames[0]
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
        ("a frame's size with a fraction of a pixel is rounded, not a style",
         lambda: 'width="660"' in frames[1] and 'height="371"' in frames[1]
         and "style=" not in frames[1]),
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
    subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"],
                   cwd=work, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    back = work + "-back"
    if exists(work, "md"):
        shutil.copytree(os.path.join(work, "md"), back)
        with open(os.path.join(back, "conversion.yaml"), "w") as fh:
            fh.write("targets:\n  html:\n    format: html\n")
        subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"],
                       cwd=back, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    agree = subprocess.run(["python3", os.path.join(ROOT, "util", "compare-output.py"),
                            os.path.join(work, "html"), os.path.join(back, "html")],
                           capture_output=True, text=True).stdout
    return [
        ("AsciiDoc to Markdown and back gives the same page",
         lambda: exists(back, "html", "ch.html") and "Runs agree" in agree),
    ]


RICH_MD = """# Rich

A word[^1] and a [link to the anchor](#here). An anchor []{#here} sits here.

![A dot](d.png){#fig-dot}

Decorative ![](d.png){.decorative} inline, math $x^2 + 1$.

<details><summary>Answer</summary>

Hidden text.

</details>

<iframe src="https://example.org/v" title="A video" width="400px"></iframe>

<table><tbody><tr><td rowspan="2">Tall</td><td>a</td></tr><tr><td>b</td></tr></tbody></table>

<table><tbody><tr><td>no</td><td>header</td></tr><tr><td>row</td><td>here</td></tr></tbody></table>

::: matrix
|       | Labor | Total |
|-------|-------|-------|
| Tech 1| $400  | $560  |
| Tech 2| $280  | $600  |
:::

.8 of a paragraph starts with a period.

// starts this one, which isn't a comment.

NOTE: is only a word here, and `std::cout` and std::cout make no list.

1. first
2. .5 is an item that starts with a period

See [the ::after page](https://developer.mozilla.org/en-US/docs/Web/CSS/::after).

A linked image with no alt: [![](d.png)](https://example.org/linked), a second note[^2],
_an italic $k_{0}$ here_, and an interval $x \\in [0,1]$.

<figure id="fig-two"><img src="d.png" alt="Supply, demand, and y = 2"><figcaption>Figure 2<br>second line</figcaption></figure>

Midpoint
:   Defined as $$\\frac{a}{[b]}$$ for short.

<table><thead><tr><th>Measure</th><th>Value</th></tr></thead>
<tbody><tr><th colspan="2">Weight</th></tr><tr><td>1 lb</td><td>16 oz</td></tr></tbody>
<tbody><tr><th colspan="2">Volume</th></tr><tr><td>1 qt</td><td>2 pt</td></tr></tbody></table>

Part\u00a0<span class="stt">I</span> and a margin note <span class="refelem"><span class="refcolumn">see <a href="rich.html#(part._x)">the part</a> later</span></span> with a label <span class="lbl"></span>.

<table role="presentation"><tbody><tr><td>T(k)</td><td>=</td><td>1</td></tr></tbody></table>

- An item that goes on:

    > A quotation in it.

- A second item.

> Do Now!
>
> > A quotation in a quotation.

[^1]: The note.

[^2]: See Friedman ([1976] 2007).

    A second paragraph.
"""

FRONT_MD = """---
title: A Book
subtitle: Copyright 2026 An Author
include-before: |
  > An epigraph that isn't short.
---

# To the Reader

Text.

# Acknowledgements

More text.
"""

SKIPS_MD = """---
title: Skipping
---

### Level three

Text.

#### Level four

More.
"""


def case_asciidoc_target(work):
    """AsciiDoc written as source: what Pandoc's AsciiDoc reader can't read
    back is written so it can, the pages read back as the same book, and
    the second write is the third."""
    import importlib.util
    if not (importlib.util.find_spec("html5lib") or importlib.util.find_spec("lxml")):
        return [("skip: raw HTML needs html5lib or lxml", lambda: True)]
    os.makedirs(work)
    for name in ("tables.docx", "metadata.docx"):
        shutil.copy(os.path.join(FIXTURES, name), work)
    with open(os.path.join(work, "d.png"), "wb") as fh:
        fh.write(ONE_PIXEL)
    with open(os.path.join(work, "rich.md"), "w", encoding="utf-8") as fh:
        fh.write(RICH_MD)
    with open(os.path.join(work, "front.md"), "w", encoding="utf-8") as fh:
        fh.write(FRONT_MD)
    with open(os.path.join(work, "skips.md"), "w", encoding="utf-8") as fh:
        fh.write(SKIPS_MD)
    with open(os.path.join(work, "cells.html"), "w", encoding="utf-8") as fh:
        fh.write('<!DOCTYPE html><html lang="en"><head><title>Cells</title></head><body>'
                 '<h1>Cells</h1><table><tbody><tr><td><pre><code>data Point:\n'
                 '  | pt(x, y)\nend</code></pre></td><td>a listing</td></tr></tbody>'
                 '</table><ul><li><p>An item holding a labeled listing:</p>'
                 '<div id="labeled" class="label-box"><p>A label.</p><pre><code>'
                 'print("in the item")</code></pre></div></li><li><p>Another.</p>'
                 '</li></ul><p>See <a href="#labeled">the listing</a>.</p>'
                 '</body></html>')

    def convert_in(where, config):
        with open(os.path.join(where, "conversion.yaml"), "w") as fh:
            fh.write(config)
        subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"],
                       cwd=where, capture_output=True, text=True,
                       stdin=subprocess.DEVNULL)

    def carry(src, dst):
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("intermediates"))
    # The source's levels, so a page whose headings skip one is written
    # as AsciiDoc that says so (heading_levels: outline closes the gap).
    both = ("defaults:\n  heading_levels: source\n"
            "targets:\n  html:\n    format: html\n  adoc:\n    format: asciidoc\n")
    convert_in(work, both)
    back, again = work + "-back", work + "-again"
    if exists(work, "adoc"):
        carry(os.path.join(work, "adoc"), back)
        convert_in(back, both)
    if exists(back, "adoc"):
        carry(os.path.join(back, "adoc"), again)
        convert_in(again, "defaults:\n  heading_levels: source\n"
                          "targets:\n  adoc:\n    format: asciidoc\n")
    rich = read(work, "adoc", "rich.adoc") if exists(work, "adoc", "rich.adoc") else ""
    meta = read(work, "adoc", "metadata.adoc") if exists(work, "adoc", "metadata.adoc") else ""
    front = read(work, "adoc", "front.adoc") if exists(work, "adoc", "front.adoc") else ""
    page = read(work, "html", "rich.html") if exists(work, "html", "rich.html") else ""
    agree = subprocess.run(["python3", os.path.join(ROOT, "util", "compare-output.py"),
                            os.path.join(work, "html"), os.path.join(back, "html")],
                           capture_output=True, text=True).stdout

    def fixed():
        names = [n for n in os.listdir(os.path.join(back, "adoc")) if n.endswith(".adoc")]
        return names and all(
            open(os.path.join(back, "adoc", n), "rb").read()
            == open(os.path.join(again, "adoc", n), "rb").read() for n in names)
    return [
        ("a footnote after a word, an anchor, and a decorative image are "
         "written as the reader reads them", lambda: "word{empty}footnote:" in rich
         and "[[here]]" in rich and "role=decorative" in rich),
        ("text AsciiDoc would read as markup is kept as text, and an address "
         "with :: in it is percent-encoded", lambda: "{empty}.8 of" in rich
         and "++//++ starts" in rich and "std:{empty}:cout" in rich
         and "CSS/%3A%3Aafter" in rich),
        ("a table with no header row says so, and a header column rides on "
         "its marker", lambda: 'options="noheader"' in rich and "[.matrix]\n--" in rich),
        ("raw HTML, a frame, and a row-spanned table go in passthrough blocks",
         lambda: "++++\n<details>" in rich and "++++\n<iframe" in rich
         and 'rowspan="2"' in rich),
        ("an image with no alt keeps none, not its file name, and an alt "
         "is written whole", lambda: "image::metadata/media/image1.png[width=" in meta
         and "media/image1\"" not in meta and 'alt="A dot"' in rich),
        ("a footnote's brackets and paragraphs, italic math, an interval, and "
         "a figure caption's line break are written as the reader reads them",
         lambda: "{startsb}1976{endsb}" in rich and "__an italic" in rich
         and "\\lbrack 0,1\\rbrack" in rich and ".Figure 2 second line" in rich),
        ("a linked image with no alt is kept, and written with its link",
         lambda: '<a href="https://example.org/linked"><img' in page
         and 'link="https://example.org/linked"' in rich),
        ("a subtitle, an epigraph, and headings at the title's level are "
         "written so they read back", lambda: ":subtitle: Copyright" in front
         and "[.include-before]" in front and ":heading-offset: -1" in front),
        ("spans are written so a link inside them survives, a trailing "
         "non-breaking space is {nbsp}, and a heading that skips a level says so",
         lambda: "[.refelem.refcolumn]##" in rich and "[.lbl]##{empty}##" in rich
         and "Part{nbsp}" in rich and ":heading-offset: 1" in read(work, "adoc", "skips.adoc")),
        ("a div's id stays as an anchor, and a quotation in a quotation has "
         "the longer delimiter", lambda: "[[labeled]]" in read(work, "adoc", "cells.adoc")
         and "______\nDo Now!" in rich),
        ("a table with a listing in a cell, or with a role, goes as HTML",
         lambda: "<pre><code>data Point:" in read(work, "adoc", "cells.adoc")
         and 'role="presentation"' in rich),
        ("read back, the AsciiDoc gives the same pages", lambda: "Runs agree" in agree),
        ("and written again, it's the same files", fixed),
    ]


def case_title_id(work):
    """A page whose title is also its first section's heading reads back
    without Pandoc warning of a duplicate id."""
    import importlib.util
    if not (importlib.util.find_spec("html5lib") or importlib.util.find_spec("lxml")):
        return [("skip: HTML sources need html5lib or lxml", lambda: True)]
    os.makedirs(work)
    with open(os.path.join(work, "sets.md"), "w", encoding="utf-8") as fh:
        fh.write("---\ntitle: Sets\n---\n\n## Sets\n\nText.\n")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"],
                   cwd=work, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    again = work + "-again"
    if exists(work, "html"):
        shutil.copytree(os.path.join(work, "html"), again)
        with open(os.path.join(again, "conversion.yaml"), "w") as fh:
            fh.write("targets:\n  html:\n    format: html\n")
    run = subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick"], cwd=again,
                         capture_output=True, text=True, stdin=subprocess.DEVNULL)
    page = read(again, "html", "sets.html") if exists(again, "html", "sets.html") else ""
    return [
        ("our own page, read back, raises no duplicate-id warning",
         lambda: exists(again, "html", "sets.html")
         and "Duplicate identifier" not in run.stderr),
        ("and the id given to its title doesn't reach the output",
         lambda: page and "title-block-title" not in page),
    ]


def case_link_titles(work):
    """A link's title survives from every source through every target:
    Markdown and AsciiDoc titles, HTML's title attribute, and Word's
    ScreenTip, which Pandoc's reader drops; and the Markdown and AsciiDoc
    targets, whose writers drop it, write it so it reads back."""
    import importlib.util, zipfile as zf
    if not (importlib.util.find_spec("html5lib") or importlib.util.find_spec("lxml")):
        return [("skip: HTML sources need html5lib or lxml", lambda: True)]
    os.makedirs(work)
    pages = {
        "md.md": '# Markdown page\n\nBare: [https://doi.org/10.5555/md](https://doi.org/10.5555/md "DOI for Markdown").\n'
                 'Hard: [Smith, J. 2005](https://example.org/md "Smith\'s study, 2005").\n',
        "html.html": '<!DOCTYPE html><html lang="en"><head><title>HTML page</title></head><body><h1>HTML page</h1>'
                     '<p>Bare: <a href="https://doi.org/10.5555/html" title="DOI for HTML">https://doi.org/10.5555/html</a>.</p></body></html>',
        "adoc.adoc": '= AsciiDoc page\n\nNamed: link:https://example.org/adoc["the AsciiDoc site",title="Named in AsciiDoc"].\n',
    }
    for name, text in pages.items():
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    word = os.path.join(work, "word.docx")
    subprocess.run(["pandoc", "-f", "markdown", "-o", word], input=
                   "# Word page\n\nBare: [https://doi.org/10.5555/docx](https://doi.org/10.5555/docx).\n"
                   "Internal: [the heading](#word-page).\n", text=True, capture_output=True)
    with zf.ZipFile(word) as z:
        items = [(i, z.read(i.filename)) for i in z.infolist()]
    fixed = []
    for info, data in items:
        if info.filename == "word/document.xml":
            xml = data.decode("utf-8")
            xml = re.sub(r'(<w:hyperlink r:id="[^"]+")', r'\1 w:tooltip="DOI for Word"', xml, count=1)
            # The anchor is the bookmark name Pandoc's writer gave the id,
            # which is word-page in 3.11 and a hash in 3.12 (#11845).
            xml = re.sub(r'(<w:hyperlink w:anchor="(?:word-page|_[0-9a-f]{39})")',
                         r'\1 w:tooltip="Internal, in Word"', xml, count=1)
            data = xml.encode("utf-8")
        fixed.append((info, data))
    with zf.ZipFile(word, "w", zf.ZIP_DEFLATED) as z:
        for info, data in fixed:
            z.writestr(info, data)

    def convert_in(where, config):
        with open(os.path.join(where, "conversion.yaml"), "w") as fh:
            fh.write(config)
        subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"],
                       cwd=where, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    convert_in(work, "targets:\n  html:\n    format: html\n  md:\n    format: markdown\n"
                     "  adoc:\n    format: asciidoc\n")
    back = {}
    for t in ("md", "adoc"):
        where = work + "-" + t
        if exists(work, t):
            shutil.copytree(os.path.join(work, t), where,
                            ignore=shutil.ignore_patterns("intermediates"))
            convert_in(where, "targets:\n  html:\n    format: html\n")
        back[t] = where

    def titles(where):
        found = {}
        for name in sorted(os.listdir(os.path.join(where, "html"))) if exists(where, "html") else []:
            if name.endswith(".html"):
                s = read(where, "html", name)
                for m in re.finditer(r'<a\b([^>]*)>(.*?)</a>', s, re.S):
                    title = re.search(r'title="([^"]*)"', m.group(1))
                    if title:
                        found[(name, re.sub(r"<[^>]+>|\s+", " ", m.group(2)).strip())] = title.group(1)
        return found
    direct = titles(work)
    expected = {"DOI for Markdown", "Smith&#39;s study, 2005", "DOI for HTML",
                "Named in AsciiDoc", "DOI for Word", "Internal, in Word"}
    return [
        ("every source's link titles reach the HTML, Word's ScreenTips "
         "included", lambda: set(direct.values()) == expected),
        ("written as Markdown and read back, every title is the same",
         lambda: titles(back["md"]) == direct),
        ("written as AsciiDoc and read back, every title is the same",
         lambda: titles(back["adoc"]) == direct),
    ]


def case_html_table_repairs(work):
    """A table with a second header row partway down is two tables; a
    scope Pandoc can't place and an impossible attribute name are dropped."""
    import importlib.util
    if not (importlib.util.find_spec("html5lib") or importlib.util.find_spec("lxml")):
        return [("skip: HTML sources need html5lib or lxml", lambda: True)]
    os.makedirs(work)
    with open(os.path.join(work, "t.html"), "w", encoding="utf-8") as fh:
        fh.write('<!DOCTYPE html><html lang="en"><head><title>T</title></head><body><h1>T</h1>'
                 '<table id="tab"><tbody id="body1"><tr id="r1"><th scope="col">Nouns</th>'
                 '<th scope="col">Not</th></tr><tr><td>Mom</td><td>mom</td></tr>'
                 '<tr id="r3"><th scope="col">Adjectives</th><th scope="col">Not</th></tr>'
                 '<tr><td>French</td><td>french fries</td></tr></tbody></table>'
                 '<table><tr><th>K</th><th>V</th></tr><tr><th scope="col">a</th><td>1</td></tr>'
                 '<tr><td>b</td><td>2</td></tr></table>'
                 '<div style="color: red" font-family:\'montserrat\',sans-serif;"="">Styled.</div>'
                 '</body></html>')
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"],
                   cwd=work, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    page = read(work, "html", "t.html") if exists(work, "html", "t.html") else ""
    return [
        ("a second header row partway down makes a second table, headed by it",
         lambda: page.count("<table") == 3 and page.count("<thead") == 3
         and page.index("Nouns") < page.index("Adjectives")),
        ("no cell keeps a scope as a td, and no id is written twice",
         lambda: "<td scope" not in page and page.count('id="body1"') <= 1
         and page.count('id="r1"') == 1),
        ("an attribute name that can't be one is dropped",
         lambda: "montserrat" not in page and "Styled." in page),
    ]



HEAD_ONLY = """<!DOCTYPE html><html lang="en"><head><title>Heads</title></head><body>
<h1>Heads</h1>
<table><caption>Charges</caption><thead>
<tr><th scope="col">peak</th><th scope="col">m/z</th><th scope="col">Z</th></tr>
<tr><td>M1</td><td>1112</td><td>9</td></tr>
<tr><td>M2</td><td>1001</td><td>10</td></tr>
<tr><td>M3</td><td>910</td><td>&#x2014;</td></tr>
</thead></table>
<table><caption>Pennies</caption><thead>
<tr><th colspan="2">First</th><th colspan="2">Second</th></tr>
<tr><th>Penny</th><th>Mass</th><th>Penny</th><th>Mass</th></tr>
<tr><td>1</td><td>3.080</td><td>1</td><td>3.052</td></tr>
<tr><td>2</td><td>3.094</td><td>2</td><td>3.141</td></tr>
</thead></table>
<table><caption>Plates</caption><thead>
<tr><th></th><th colspan="2">R = 1.00</th><th colspan="2">R = 1.25</th></tr>
<tr><td>k</td><td>a = 1.05</td><td>a = 1.10</td><td>a = 1.05</td><td>a = 1.10</td></tr>
</thead><tbody>
<tr><td>0.5</td><td>63500</td><td>17400</td><td>99200</td><td>27200</td></tr>
<tr><td>1.0</td><td>28200</td><td>7740</td><td>44100</td><td>12100</td></tr>
</tbody></table>
<table><caption>Grid</caption><thead>
<tr><td></td><th>A</th><th>B</th></tr>
<tr><th>x</th><td>1</td><td>2</td></tr>
<tr><th>y</th><td>3</td><td>4</td></tr>
</thead></table>
<table><caption>Prices</caption><thead>
<tr><td>Year</td><td>Price</td></tr>
<tr><td>2020</td><td>10</td></tr>
<tr><td>2021</td><td>12</td></tr>
</thead></table>
</body></html>
"""


def case_head_only_tables(work):
    """A table whose <thead> holds every row, its rows of data too, as
    LibreTexts' editor writes one: Pandoc's reader made every row a header
    row, so every cell was a <th>, the table had no body, and a Word file
    repeated every row as a header. Its rows of data are its body now, and
    its header rows, two of them or one, an empty <td> in a corner among
    them, its head; a head whose first row is data is all body, which the
    header guess reads; and a head with a body after it stays as its
    author divided it, a row of <td> in it a header still."""
    import importlib.util
    if not (importlib.util.find_spec("html5lib") or importlib.util.find_spec("lxml")):
        return [("skip: HTML sources need html5lib or lxml", lambda: True)]
    os.makedirs(work, exist_ok=True)
    with open(os.path.join(work, "heads.html"), "w", encoding="utf-8") as fh:
        fh.write(HEAD_ONLY)
    result = convert(work, "targets:\n  html:\n    format: html\n"
                           "  word:\n    format: docx\n", fixtures=())
    page = read(work, "html", "heads.html") if exists(work, "html", "heads.html") else ""

    def rows(table, part):
        """How many rows a table of the page holds in its head or its body."""
        return sum(m.group(0).count("<tr") for m in re.finditer(
            r"<%s\b.*?</%s>" % (part, part), table, re.S))
    tables = re.findall(r"<table\b.*?</table>", page, re.S)
    shape = [(rows(t, "thead"), rows(t, "tbody"), t.count("<td")) for t in tables]
    words = glob.glob(os.path.join(work, "word", "*.docx"))
    repeated = []
    if words:
        with zipfile.ZipFile(words[0]) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        repeated = [len(re.findall(r"<w:tblHeader\b", t))
                    for t in re.findall(r"<w:tbl>.*?</w:tbl>", xml, re.S)]
    found = []
    if exists(work, "output-check.csv"):
        with open(os.path.join(work, "output-check.csv"), encoding="utf-8") as fh:
            found = [row["Check"] for row in csv.DictReader(fh)]
    return [
        ("a table whose head held every row has a body of its rows of data, its header "
         "row its head",
         lambda: result.returncode == 0 and len(shape) == 5 and shape[0] == (1, 3, 9)),
        ("two header rows stay its head, and so does a header row with an empty <td> in "
         "its corner, its body's rows headed by a <th> each",
         lambda: len(shape) == 5 and shape[1] == (2, 2, 8) and shape[3] == (1, 2, 4)
         and tables[3].count('<th scope="row">') == 2),
        ("a head whose first row is data is all body, which the header guess reads",
         lambda: len(shape) == 5 and shape[4][1] >= 2 and shape[4][2] >= 4),
        ("a head with a body after it is as its author divided it, a row of <td> in it a "
         "header still",
         lambda: len(shape) == 5 and shape[2] == (2, 2, 10)),
        ("and a Word file repeats only the header rows",
         lambda: repeated[:4] == [1, 2, 2, 1] and len(repeated) == 5 and repeated[4] <= 1),
        ("the output check finds no table without a data cell",
         lambda: "table-without-data-cells" not in found),
    ]

BARE_MD = """# References

Klein and Stern. 2005. "Professors and Their Politics." [https://doi.org/10.1080/08913810508443640](https://doi.org/10.1080/08913810508443640).

Data and Story Library. [dasl.datadescription.com/datafile/cars](https://dasl.datadescription.com/datafile/cars).

An archive at [ftp://ftp.example.org/pub/data.csv](ftp://ftp.example.org/pub/data.csv) and a titled one [https://example.org/titled](https://example.org/titled "The source's own title").

A [named link](https://example.org/named), and the DOI again: [https://doi.org/10.1080/08913810508443640](https://doi.org/10.1080/08913810508443640).
"""


def case_bare_links(work):
    """Bare links are reported once per address, and the sidecar replaces
    an address and its text, or the text alone, or sets a title, or keeps
    the link and the source's title."""
    import csv as csvmod
    os.makedirs(work)
    with open(os.path.join(work, "refs.md"), "w", encoding="utf-8") as fh:
        fh.write(BARE_MD)
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n")

    def run():
        return subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick"], cwd=work,
                              capture_output=True, text=True, stdin=subprocess.DEVNULL)
    first = run()
    report = []
    if exists(work, "bare-links-new.csv"):
        with open(os.path.join(work, "bare-links-new.csv"), encoding="utf-8") as fh:
            report = list(csvmod.DictReader(fh))
    by_url = {r["URL"]: r for r in report}
    with open(os.path.join(work, "bare-links.csv"), "w", encoding="utf-8") as fh:
        fh.write("URL,Replacement,Title\n"
                 "https://doi.org/10.1080/08913810508443640,https://doi.org/10/b8xx35,DOI for Klein and Stern 2005\n"
                 "https://dasl.datadescription.com/datafile/cars,The Data and Story Library's cars data,\n"
                 "ftp://ftp.example.org/pub/data.csv,,Car data as CSV\n"
                 "https://example.org/titled,,\n"
                 "https://example.org/not-in-the-book,,\n")
    second = run()
    page = read(work, "html", "refs.html") if exists(work, "html", "refs.html") else ""
    links = [(" ".join(m.group(1).split()), " ".join(m.group(2).split()))
             for m in re.finditer(r"<a\b(.*?)>(.*?)</a>", page, re.S)]
    return [
        ("each bare address is reported once, text without https:// included, "
         "and a named link isn't", lambda: sorted(by_url) == [
            "ftp://ftp.example.org/pub/data.csv",
            "https://dasl.datadescription.com/datafile/cars",
            "https://doi.org/10.1080/08913810508443640",
            "https://example.org/titled"]),
        ("a row has the text before the link, and the link's own title",
         lambda: "Professors and Their Politics" in by_url[
             "https://doi.org/10.1080/08913810508443640"]["Context"]
         and by_url["https://example.org/titled"]["Title"] == "The source's own title"),
        ("a URL replacement replaces the address and text everywhere, with "
         "the title", lambda: links.count(('href="https://doi.org/10/b8xx35" '
                                           'title="DOI for Klein and Stern 2005"',
                                           "https://doi.org/10/b8xx35")) == 2),
        ("text replaces only the text; a title alone leaves a link bare",
         lambda: ('href="https://dasl.datadescription.com/datafile/cars"',
                  "The Data and Story Library's cars data") in links
         and ('href="ftp://ftp.example.org/pub/data.csv" title="Car data as CSV"',
              "ftp://ftp.example.org/pub/data.csv") in links),
        ("a blank row keeps the link and the source's title; a named link is "
         "untouched", lambda: ('href="https://example.org/titled" '
                               'title="The source&#39;s own title"',
                               "https://example.org/titled") in links
         and ('href="https://example.org/named"', "named link") in links),
        ("with every bare link decided there's no report, and a row matching "
         "none is named", lambda: not exists(work, "bare-links-new.csv")
         and "not-in-the-book" in second.stderr),
    ]


PNG_1PX = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                        "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def solid_png(path, width=40, height=20, rgb=(0, 0, 128)):
    """A PNG of one color, navy unless given, written without an imaging
    library: Pillow isn't one of the requirements, and a machine without
    it erred in three cases."""
    import struct
    import zlib

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n"
                 + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                 + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def run_tool(cwd, args, util=False):
    """One of the pipeline's scripts, from bin/ or util/, run in cwd."""
    script = os.path.join(ROOT, "util" if util else "bin", args[0])
    return subprocess.run([sys.executable, "-B", script] + args[1:], cwd=cwd,
                          capture_output=True, text=True)


# Word's own equations as the statistics textbook writes them: a bar as an
# upper limit holding a macron, an en dash for a minus, the micro sign, a
# slashed O for H's zero, a one-character y-hat, and the increment sign,
# with an en dash inside normal text, which is text and stays; and an
# accent of the macron, as LibreOffice writes a bar, which reads as \bar.
WORD_EQUATION = (
    '<m:oMath><m:sSub><m:e><m:r><m:t>\u00b5</m:t></m:r></m:e><m:sub><m:limUpp>'
    '<m:e><m:r><m:t>x</m:t></m:r></m:e><m:lim><m:r><m:rPr><m:sty m:val="p" /></m:rPr>'
    '<m:t>\u00af</m:t></m:r></m:lim></m:limUpp></m:sub></m:sSub>'
    '<m:r><m:rPr><m:sty m:val="p" /></m:rPr><m:t>\u2013</m:t></m:r>'
    '<m:sSub><m:e><m:r><m:t>H</m:t></m:r></m:e><m:sub><m:r><m:t>\u00d8</m:t></m:r></m:sub></m:sSub>'
    '<m:r><m:t>\u0177=a</m:t></m:r>'
    '<m:acc><m:accPr><m:chr m:val="\u00af" /></m:accPr><m:e><m:r><m:t>z</m:t></m:r></m:e></m:acc>'
    '<m:r><m:rPr><m:nor /></m:rPr><m:t>pages 1\u20135 %\u2206Q</m:t></m:r></m:oMath>')


def case_word_equations(work):
    """format: source writes math.repair_equations into a Word file's own
    equations, and with the setting off leaves them as they were."""
    os.makedirs(work)
    subprocess.run(["pandoc", "-o", os.path.join(work, "eq.docx")],
                   input="# Equations\n\nThe test: $a$.\n", text=True, check=True)
    path = os.path.join(work, "eq.docx")
    with zipfile.ZipFile(path) as z:
        items = [(i, z.read(i.filename)) for i in z.infolist()]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for info, data in items:
            if info.filename == "word/document.xml":
                data = re.sub(r"<m:oMath>.*?</m:oMath>", WORD_EQUATION,
                              data.decode("utf-8"), count=1, flags=re.S).encode("utf-8")
            z.writestr(info, data)

    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import docxrepair

    def tex_of(path, as_pipeline=True):
        # As a conversion reads a Word file, through docxrepair's copy, or
        # as Pandoc alone does.
        if as_pipeline:
            copy = os.path.join(work, "read-" + os.path.basename(path))
            docxrepair.repaired_copy(path, copy)
            path = copy
        back = subprocess.run(["pandoc", "-f", "docx", "-t", "json", path],
                              capture_output=True, text=True)
        tex = [n["c"][1] for n in walk_json(json.loads(back.stdout)) if n.get("t") == "Math"]
        return tex[0] if tex else ""

    def build(setting):
        with open(os.path.join(work, "conversion.yaml"), "w") as fh:
            fh.write("targets:\n  source:\n    format: source\n" + setting)
        result = subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"],
                                cwd=work, capture_output=True, text=True,
                                stdin=subprocess.DEVNULL)
        return result, tex_of(os.path.join(work, "source", "eq.docx"))
    on_result, on = build("")
    on_alone = tex_of(os.path.join(work, "source", "eq.docx"), as_pipeline=False)
    with zipfile.ZipFile(os.path.join(work, "source", "eq.docx")) as z:
        on_xml = z.read("word/document.xml").decode("utf-8")
    # The keep sidecar names the equation by its Before in the report, the
    # TeX the filter read; a second row names nothing.
    with open(os.path.join(work, "math-repaired.csv"), encoding="utf-8", newline="") as fh:
        before = next((row["Before"] for row in csv.DictReader(fh)
                       if row["Kind"] == "equation"), "")
    off_result, off = build("    math:\n      repair_equations: false\n")
    with open(os.path.join(work, "math-keep.csv"), "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows([["Kind", "Page", "Before"], ["equation", "eq", before],
                                  ["expression", "", "\u03b2 = 7"]])
    kept_result, kept = build("")
    kept_said = kept_result.stdout + kept_result.stderr
    off_kept_result, _ = build("    math:\n      repair_equations: false\n")
    off_kept_said = off_kept_result.stdout + off_kept_result.stderr
    return [
        # As a conversion reads it back: \mu for the Greek letter, - for the
        # minus, and \bar for the accent of the macron, which Narrator reads
        # in Word where it said nothing for the overline Pandoc writes.
        ("the copy's equation reads back with a bar, mu, a minus, H sub 0, "
         "a hatted y, and Delta",
         lambda: all(part in on for part in ("\\mu_{\\bar{x}} - H_{0}",
                                             "\\hat{y}", "\\bar{z}", "\u0394"))
         and not any(c in on for c in "\u00b5\u00d8\u0177\u2206")),
        ("the bar is an accent of the macron, the limit gone, which Pandoc alone reads as "
         "\\overline",
         lambda: '<m:acc><m:accPr><m:chr m:val="\u00af" /></m:accPr><m:e><m:r><m:t>x</m:t>'
         in on_xml and "<m:limUpp>" not in on_xml and on_xml.count("<m:acc>") == 3
         and "\\mu_{\\overline{x}}" in on_alone),
        ("an en dash in normal text stays an en dash",
         lambda: "1\u20135" in on),
        ("the run says how many equations it repaired, and how many characters: mu, the "
         "bar, the minus, the zero, the hat, and Delta",
         lambda: "1 Word equation(s) given the characters they mean (6 change(s))"
         in on_result.stdout + on_result.stderr),
        ("with math.repair_equations off, the equation is as it was",
         lambda: "\u00b5" in off and "\\overset" in off),
        ("an equation the keep sidecar names by the report's Before, its accent of "
         "the macron read as \\bar, is as it was in the copy, and the run says so",
         lambda: "\\bar{z}" in before and kept == tex_of(os.path.join(work, "eq.docx"))
         and "\\overset" in kept and "1 equation(s) kept as they were" in kept_said),
        ("a row of the keep sidecar that keeps nothing is warned about",
         lambda: "1 row(s) of math-keep.csv kept nothing" in kept_said
         and "expression,,\u03b2 = 7" in kept_said),
        ("but not an equation's with math.repair_equations off, since it couldn't keep "
         "anything; text's still is",
         lambda: "1 row(s) of math-keep.csv kept nothing" in off_kept_said
         and "expression,,\u03b2 = 7" in off_kept_said and "equation,eq," not in off_kept_said),
    ]


def case_word_text_math(work):
    """format: source writes math.from_text into a Word file: the runs of
    math typed as text replaced by Word's equation, what's around them kept
    as it was, and the same text in two paragraphs told apart."""
    os.makedirs(work)
    subprocess.run(["pandoc", "-o", os.path.join(work, "tm.docx")], check=True, text=True,
                   input="# Math as text\n\n"
                         "We know *μ* = 34, and **so** *H*~0~: *μ* ≠ 34, with $x$ < 5 here.\n\n"
                         "The same: $y$ < 5 here.\n\n"
                         "The same: $z$ < 5 here.\n\n"
                         "A lone *a*, a [link](https://example.org), and 3 < 5 stay.\n\n"
                         "ONE-RUN\n\nTWO-RUN\n\n"
                         "No\u00a0break before *σ* = 2 here.\n")
    # Word keeps a run of plain text together, where Pandoc writes a run a
    # word: the equation begins and ends inside this one.
    path = os.path.join(work, "tm.docx")
    with zipfile.ZipFile(path) as z:
        items = [(i, z.read(i.filename)) for i in z.infolist()]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for info, data in items:
            if info.filename == "word/document.xml":
                data = re.sub(r"<w:r>(?:(?!</w:r>).)*ONE-RUN</w:t></w:r>",
                              '<w:r><w:rPr><w:color w:val="C00000" /></w:rPr>'
                              '<w:t xml:space="preserve">Level '
                              '\u03b1 = 0.05 here.</w:t></w:r>',
                              data.decode("utf-8"), flags=re.S).encode("utf-8")
                # Two equations in one run of text.
                data = re.sub(r"<w:r>(?:(?!</w:r>).)*TWO-RUN</w:t></w:r>",
                              '<w:r><w:rPr><w:color w:val="0000C0" /></w:rPr>'
                              '<w:t xml:space="preserve">Let \u03b1 = 0.05 and '
                              '\u03b2 = 0.2 here.</w:t></w:r>',
                              data.decode("utf-8"), flags=re.S).encode("utf-8")
            z.writestr(info, data)

    def build(setting):
        with open(os.path.join(work, "conversion.yaml"), "w") as fh:
            fh.write("targets:\n  source:\n    format: source\n" + setting)
        result = subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"],
                                cwd=work, capture_output=True, text=True,
                                stdin=subprocess.DEVNULL)
        back = subprocess.run(["pandoc", "-f", "docx", "-t", "markdown", "--wrap=none",
                               os.path.join(work, "source", "tm.docx")],
                              capture_output=True, text=True)
        return result.stdout + result.stderr, back.stdout
    said, on = build("")
    with zipfile.ZipFile(os.path.join(work, "source", "tm.docx")) as z:
        copy = z.read("word/document.xml").decode("utf-8")
    colored = re.findall(r'<w:color w:val="C00000" /></w:rPr><w:t xml:space="preserve">([^<]*)</w:t>', copy)
    blue = re.findall(r'<w:color w:val="0000C0" /></w:rPr><w:t xml:space="preserve">([^<]*)</w:t>', copy)
    _, off = build("    math:\n      from_text: false\n")
    return [
        ("each expression is an equation in the copy, what's between them text",
         lambda: "We know $\\mu = 34$, and **so** $H_{0}:\\mu \\neq 34$, with $x < 5$ here." in on),
        ("paragraphs with the same text each get their own equation",
         lambda: "The same: $y < 5$ here." in on and "The same: $z < 5$ here." in on),
        ("a lone italic letter, a link, and numbers alone stay as they were",
         lambda: "A lone *a*, a [link](https://example.org), and 3 \\< 5 stay." in on),
        ("an equation inside one run of text splits it, its formatting on "
         "both sides", lambda: "Level $\\alpha = 0.05$ here." in on
         and colored == ["Level ", " here."]),
        ("two equations in one run of text split it three ways, its formatting "
         "on each piece", lambda: "Let $\\alpha = 0.05$ and $\\beta = 0.2$ here." in on
         and blue == ["Let ", " and ", " here."]),
        ("a paragraph with a no-break space is found, as the filter keeps one",
         lambda: "$\\sigma = 2$ here." in on),
        ("the run says how many it wrote, and none was left",
         lambda: "9 equation(s) made of math typed as text" in said
         and "not written into the Word file" not in said),
        ("with math.from_text off, the copy's text is as it was",
         lambda: "We know *μ* = 34" in off and "$x$ \\< 5" in off),
    ]


def case_source_target(work):
    """format: source: the book's own Word files, remediated into the
    target's folder, with only what a person decided in the sidecars, never
    a guess; the author's files untouched."""
    import zipfile, hashlib
    os.makedirs(os.path.join(work, "assets"), exist_ok=True)
    solid_png(os.path.join(work, "assets", "a.png"))
    for n in (1, 2):
        with open(os.path.join(work, f"ch{n}.md"), "w", encoding="utf-8") as fh:
            fh.write(f"---\ntitle: Chapter {n}\nlang: en\n---\n\n# Chapter {n}\n\n"
                     f"| Name | Score |\n|------|------:|\n| Ana | 9{n} |\n| Ben | 8{n} |\n| Cy | 7{n} |\n\n"
                     + ("Table 2.1\n\n" if n == 2 else "See <https://doi.org/10.1000/xyz123>.\n\n"
                        # A caption that is its label alone, which Pandoc writes as a
                        # Table Caption paragraph before the table and reads back as
                        # the table's caption.
                        "| Term | Count |\n|------|------:|\n| Fall | 12 |\n\nTable: Table 1.4\n\n")
                     + "![](assets/a.png)\n\nText.\n")
        subprocess.run(["pandoc", f"ch{n}.md", "-o", f"ch{n}.docx"], cwd=work, check=True)
        os.remove(os.path.join(work, f"ch{n}.md"))
    shutil.rmtree(os.path.join(work, "assets"))
    # Chapter 2 declares no language, for the copy to be given the book's.
    with zipfile.ZipFile(os.path.join(work, "ch2.docx")) as z:
        parts = {i: z.read(i.filename) for i in z.infolist()}
    with zipfile.ZipFile(os.path.join(work, "ch2.docx"), "w", zipfile.ZIP_DEFLATED) as z:
        for info, data in parts.items():
            if info.filename == "word/styles.xml":
                data = re.sub(rb"<w:lang\b[^>]*/>", b"", data)
            z.writestr(info, data)
    with open(os.path.join(work, "notes.md"), "w", encoding="utf-8") as fh:
        fh.write("---\ntitle: Notes\nlang: en\n---\n\n# Notes\n\nA Markdown chapter.\n")
    os.makedirs(os.path.join(work, "img"), exist_ok=True)
    solid_png(os.path.join(work, "img", "bar.png"), rgb=(0, 128, 128))  # teal
    with open(os.path.join(work, "page.html"), "w", encoding="utf-8") as fh:
        fh.write("<!DOCTYPE html>\n<html>\n<head><meta charset=\"utf-8\"><title>Scores</title></head>\n"
                 "<body>\n<h1>Scores</h1>\n<!-- the author's comment -->\n<table>\n"
                 "  <tr><td>Name</td><td>Score</td></tr>\n  <tr><td>Ana</td><td>90</td></tr>\n"
                 "  <tr><td>Ben</td><td>85</td></tr>\n  <tr><td>Cy</td><td>70</td></tr>\n</table>\n"
                 "<p><img src=\"img/bar.png\"></p>\n<table>\n  <tr><td>Term</td><td>Count</td></tr>\n"
                 "  <tr><td>Fall</td><td>12</td></tr>\n</table>\n<p>Table 1.2</p>\n<p>More text.</p>\n"
                 "<table>\n  <caption>Table 1.3</caption>\n  <tr><td>Section</td><td>Grade</td></tr>\n"
                 "  <tr><td>A</td><td>88</td></tr>\n</table>\n<p>See <a href=\"https://doi.org/10.1000/xyz123\">"
                 "https://doi.org/10.1000/xyz123</a>.</p>\n</body>\n</html>\n")
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  language: en\n")
    digest = lambda n: hashlib.sha256(open(os.path.join(work, n), "rb").read()).hexdigest()
    before = {n: digest(n) for n in ("ch1.docx", "ch2.docx", "page.html")}

    def conf(extra=""):
        with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
            fh.write("targets:\n  html:\n    format: html\n  fixed:\n    format: source\n" + extra)

    def run():
        return subprocess.run([sys.executable, "-B", os.path.join(BIN, "convert.py"), "--quick"],
                              cwd=work, capture_output=True, text=True)

    def differ(n):
        with zipfile.ZipFile(os.path.join(work, n)) as a, \
                zipfile.ZipFile(os.path.join(work, "fixed", n)) as b:
            return [p for p in a.namelist() if a.read(p) != b.read(p)]

    conf()
    first = run()
    first_page = read(work, "fixed", "page.html") if exists(work, "fixed", "page.html") else ""
    first_missing = read(work, "table-captions-missing.csv") if exists(
        work, "table-captions-missing.csv") else ""
    first_differ = {n: differ(n) for n in ("ch1.docx", "ch2.docx")} \
        if os.path.exists(os.path.join(work, "fixed", "ch1.docx")) else None
    shutil.copy(os.path.join(work, "table-headers-new.csv"), os.path.join(work, "table-headers.csv"))
    with open(os.path.join(work, "table-headers.csv"), encoding="utf-8") as fh:
        rows = fh.read().splitlines()
    with open(os.path.join(work, "table-headers.csv"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(r for r in rows if "ch2.docx" not in r) + "\n")
    with zipfile.ZipFile(os.path.join(work, "ch1.docx")) as z:
        rid = re.search(r'r:embed="([^"]+)"', z.read("word/document.xml").decode()).group(1)
    with open(os.path.join(work, "image-alt.csv"), "w", encoding="utf-8") as fh:
        fh.write(f"Image,Alt\nch1/media/{rid}.png,A navy rectangle\nimg/bar.png,A bar chart of the scores\n")
    with open(os.path.join(work, "table-captions.csv"), "w", encoding="utf-8") as fh:
        fh.write("Label,Description\npage#table-1,Scores by student\nTable 1.2,Enrollment by term\n"
                 "ch1#table-1,Scores in chapter one\nTable 2.1,Scores in chapter two\n"
                 "Table 1.3,Grades by section\nTable 1.4,Terms by season\n")
    with open(os.path.join(work, "bare-links.csv"), "w", encoding="utf-8") as fh:
        fh.write("URL,Replacement,Title\nhttps://doi.org/10.1000/xyz123,https://doi.org/10/abcd,The source study\n")
    second = run()
    page = read(work, "fixed", "page.html") if exists(work, "fixed", "page.html") else ""
    page_html = read(work, "html", "page.html") if exists(work, "html", "page.html") else ""
    ch1_html = read(work, "html", "ch1.html") if exists(work, "html", "ch1.html") else ""

    def xml(n):
        with zipfile.ZipFile(os.path.join(work, "fixed", n)) as z:
            return z.read("word/document.xml").decode()
    one, two = xml("ch1.docx"), xml("ch2.docx")
    kept_compat = "word/settings.xml" not in differ("ch1.docx")
    with zipfile.ZipFile(os.path.join(work, "fixed", "ch1.docx")) as z:
        one_rels = z.read("word/_rels/document.xml.rels").decode()
    with zipfile.ZipFile(os.path.join(work, "fixed", "ch2.docx")) as z:
        two_styles = z.read("word/styles.xml").decode()
    one_read = subprocess.run(["pandoc", os.path.join(work, "fixed", "ch1.docx"), "-t", "html"],
                              capture_output=True, text=True).stdout
    conf('    compatibility_mode: "15"\n')
    third = run()
    set_compat = "word/settings.xml" in differ("ch1.docx") and 'w:name="compatibilityMode"' in \
        zipfile.ZipFile(os.path.join(work, "fixed", "ch1.docx")).read("word/settings.xml").decode()
    conf("  again:\n    format: source\n")
    fourth = run()
    return [
        ("a first run, with no sidecar, changes only a missing language, and says what's left to a guess",
         lambda: first_differ == {"ch1.docx": [], "ch2.docx": ["word/styles.xml"]}
         and "left as they are, with only the census's guess" in first.stderr),
        ("once a table's row is adopted, its headers are written; a table with none is left alone",
         lambda: re.search(r'w:name="(?:Column|Row)?Title_\d+"', one)
         and not re.search(r'w:name="(?:Column|Row)?Title_\d+"', two)
         and "1 table(s) left as they are" in second.stderr),
        ("an image described in the sidecar gets its alt text",
         lambda: 'descr="A navy rectangle"' in one),
        ("the author's files never change, and the copy's compatibility mode is theirs",
         lambda: {n: digest(n) for n in before} == before and kept_compat),
        ("compatibility_mode: 15 sets it",
         lambda: set_compat),
        ("an HTML page's copy: on a first run only lang, from the book's language, the rest as written",
         lambda: '<html lang="en">' in first_page and "<td>Name</td>" in first_page
         and first_page.replace(' lang="en"', "") == read(work, "page.html")),
        ("once decided, its header cells, alt text, and the link's replacement and title are written",
         lambda: '<th scope="col">Name</th>' in page and '<th scope="row">Ana</th><td>90</td>' in page
         and 'alt="A bar chart of the scores"' in page
         and '<a href="https://doi.org/10/abcd" title="The source study">https://doi.org/10/abcd</a>' in page
         and "<!-- the author's comment -->" in page),
        ("two source targets that would write the same copies are warned about, and one alone isn't",
         lambda: "WARNING: fixed and again both have format source" in fourth.stderr
         and "both have format source" not in third.stderr),
        ("a table with no label gets its sidecar description as its caption, in the copy",
         lambda: "<table><caption>Scores by student</caption>" in page),
        ("a description joined to a label paragraph is joined to it where it stands",
         lambda: "<p>Table 1.2 Enrollment by term</p>" in page and "not written" not in second.stderr),
        ("a table whose own caption is its label alone is reported for a description, then given "
         "it, on the page and in the copy's caption",
         lambda: re.search(r"^Table 1\.3,,page,", first_missing, re.M)
         and re.search(r"<caption>\s*Table 1\.3 Grades by section\s*</caption>", page_html)
         and "<caption>Table 1.3 Grades by section</caption>" in page),
        ("a Word table with no label gets a Caption paragraph, which Pandoc reads as its caption",
         lambda: re.search(r'<w:pStyle w:val="Caption"/><w:keepNext/></w:pPr><w:r><w:t xml:space="preserve">'
                           r'Scores in chapter one</w:t></w:r></w:p><w:tbl>', one)
         and re.search(r"<caption>\s*<p>Scores in chapter one</p>\s*</caption>", one_read)),
        ("a Word label paragraph gets its description joined",
         lambda: re.search(r"Table 2\.1</w:t></w:r>(?:(?!</w:p>).)*Scores in chapter two", two, re.S)),
        ("a Word table whose caption paragraph is its label alone gets its description, on the "
         "page and joined to the paragraph in the copy, which Pandoc reads back as the caption",
         lambda: re.search(r"<caption>\s*Table 1\.4 Terms by season\s*</caption>", ch1_html)
         and re.search(r"Table 1\.4</w:t></w:r>(?:(?!</w:p>).)*Terms by season</w:t></w:r></w:p>\s*<w:tbl>",
                       one, re.S)
         and re.search(r"<caption>\s*<p>Table 1\.4 Terms by season</p>\s*</caption>", one_read)),
        ("a Word link gets its replacement address and text, and its title",
         lambda: 'Target="https://doi.org/10/abcd"' in one_rels
         and "https://doi.org/10.1000/xyz123" not in one and "https://doi.org/10/abcd" in one
         and 'w:tooltip="The source study"' in one),
        ("a Word file declaring no language gets the book's",
         lambda: re.search(r'<w:docDefaults>(?:(?!</w:docDefaults>).)*<w:lang w:val="en"/>', two_styles, re.S)),
        ("a Markdown source is remediated too, into the same folder",
         lambda: "and 1 Markdown file(s) remediated" in third.stderr
         and exists(work, "fixed", "notes.md")),
    ]


def case_word_repairs(work):
    """word.tracked_deletions and word.headings: decided once, applied to
    the copy the conversion reads and to a source target's copy."""
    import zipfile
    os.makedirs(work, exist_ok=True)
    with open(os.path.join(work, "ch.md"), "w", encoding="utf-8") as fh:
        fh.write("---\ntitle: Repairs\nlang: en\n---\n\n::: {custom-style=\"Title\"}\nModule One\n:::\n\n"
                 "# Section A\n\nKeep this.\n\nCut the extra words.\n")
    subprocess.run(["pandoc", "ch.md", "-o", "ch.docx"], cwd=work, check=True)
    os.remove(os.path.join(work, "ch.md"))
    path = os.path.join(work, "ch.docx")
    with zipfile.ZipFile(path) as z:
        parts = {i: z.read(i.filename) for i in z.infolist()}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for info, data in parts.items():
            if info.filename == "word/document.xml":
                data = data.replace(b"Cut the extra words.</w:t></w:r>",
                                    b'Cut the extra words.</w:t></w:r><w:del w:id="901" w:author="A" '
                                    b'w:date="2026-01-01T00:00:00Z"><w:r><w:delText xml:space="preserve">'
                                    b' Very much so.</w:delText></w:r></w:del>', 1)
            z.writestr(info, data)

    def run(config):
        with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
            fh.write(config)
        result = subprocess.run([sys.executable, "-B", os.path.join(BIN, "convert.py"), "--quick"],
                                cwd=work, capture_output=True, text=True)
        pages = "".join(read(work, "html", f) for f in sorted(os.listdir(os.path.join(work, "html")))
                        if f.endswith(".html")) if exists(work, "html") else ""
        return result, pages

    plain, plain_html = run("targets:\n  html:\n    format: html\n")
    fixed, fixed_html = run("defaults:\n  word:\n    tracked_deletions: strike\n"
                            "    headings: Title=Heading1,Heading1=Heading2\n"
                            "targets:\n  html:\n    format: html\n  mine:\n    format: source\n")
    copy = ""
    if exists(work, "mine", "ch.docx"):
        with zipfile.ZipFile(os.path.join(work, "mine", "ch.docx")) as z:
            copy = z.read("word/document.xml").decode("utf-8")
    missing, _ = run("defaults:\n  word:\n    headings: Title=Heading10\ntargets:\n  html:\n    format: html\n")
    return [
        ("by default, tracked deletions are dropped, and the run names the file",
         lambda: "Very much so" not in plain_html
         and re.search(r"WARNING: 1 Word file\(s\) have text deleted with tracked changes.*ch\.docx",
                       plain.stderr)),
        ("tracked_deletions: strike keeps the deleted text, struck through, and warns no more",
         lambda: re.search(r"<del>\s*Very much so\.?\s*</del>", fixed_html)
         and "deleted with tracked changes" not in fixed.stderr),
        ("headings: a map makes the Title paragraph a heading, one level above the old Heading 1",
         lambda: re.search(r"<h(\d)[^>]*>Module One", fixed_html)
         and re.search(r"<h(\d)[^>]*>Section A", fixed_html)
         and int(re.search(r"<h(\d)[^>]*>Module One", fixed_html).group(1))
         < int(re.search(r"<h(\d)[^>]*>Section A", fixed_html).group(1))),
        ("a source target's copy gets the same repairs: the styles mapped, the deletion struck",
         lambda: re.search(r'<w:pStyle w:val="Heading1"\s*/>(?:(?!</w:p>).)*Module One', copy, re.S)
         and re.search(r'<w:pStyle w:val="Heading2"\s*/>(?:(?!</w:p>).)*Section A', copy, re.S)
         and "<w:del " not in copy and re.search(r"<w:strike/>(?:(?!</w:r>).)*Very much so", copy, re.S)),
        ("a map to a style the file doesn't define leaves it as it is, and names it",
         lambda: "WARNING: ch.docx: word.headings not applied" in missing.stderr
         and "Heading10" in missing.stderr),
    ]


def case_markdown_source(work):
    """format: source for a Markdown file: the sidecars' decisions written
    where each element is, confirmed against Pandoc's reading, the rest of
    the file exactly as written."""
    import zipfile
    os.makedirs(os.path.join(work, "img"), exist_ok=True)
    for name in ("my chart", "rule", "code"):
        solid_png(os.path.join(work, "img", name + ".png"))
    original = (
        "---\ntitle: Chapter\n---\n\nSetext Heading\n==============\n\nSome _emphasis_ kept as written.\n\n"
        "![](img/my chart.png)\n\n![Rule](img/rule.png){ width=50% }\n\n"
        "![A code image](img/code.png)\n\n```\n![A code image](img/code.png)\n```\n\n"
        "See <https://doi.org/10.1000/xyz123>.\n\n"
        "| A | B |\n|---|---|\n| 1 | 2 |\n\n"
        "::: matrix\n|   | X | Y |\n|---|---|---|\n| P | 1 | 2 |\n:::\n\n"
        "| C | D |\n|---|---|\n| 3 | 4 |\n\nTable 1.2\n\n"
        "| E | F |\n|---|---|\n| 5 | 6 |\n\nTable: Table 1.3\n\n"
        "| G | H |\n|---|---|\n| 7 | 8 |\n\ntable: Table 1.4\n\n"
        "| I | J |\n|---|---|\n| 9 | 0 |\n\nTable: Table 1.5 {#tbl:five}\n\nThe end.\n")
    with open(os.path.join(work, "ch.md"), "w", encoding="utf-8") as fh:
        fh.write(original)

    def run():
        with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
            fh.write("targets:\n  html:\n    format: html\n  mine:\n    format: source\n")
        return subprocess.run([sys.executable, "-B", os.path.join(BIN, "convert.py"), "--quick"],
                              cwd=work, capture_output=True, text=True)

    first = run()
    first_copy = read(work, "mine", "ch.md") if exists(work, "mine", "ch.md") else None
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  language: en\n")
    with open(os.path.join(work, "image-alt.csv"), "w", encoding="utf-8") as fh:
        fh.write('Image,Alt\n"img/my chart.png",A chart of the data\nimg/rule.png,[decorative]\n'
                 "img/code.png,A described code image\n")
    with open(os.path.join(work, "bare-links.csv"), "w", encoding="utf-8") as fh:
        fh.write("URL,Replacement,Title\nhttps://doi.org/10.1000/xyz123,https://doi.org/10/abcd,The study\n")
    with open(os.path.join(work, "table-captions.csv"), "w", encoding="utf-8") as fh:
        fh.write("Label,Description\nch#table-1,First table\nch#table-2,Second table\n"
                 "Table 1.2,Third table\nTable 1.3,Fourth table\nTable 1.4,Fifth table\n"
                 "Table 1.5,Sixth table\n")
    second = run()
    copy = read(work, "mine", "ch.md") if exists(work, "mine", "ch.md") else ""
    copy_html = subprocess.run(["pandoc", "-f", "markdown", "-t", "html"], input=copy,
                               capture_output=True, text=True).stdout
    return [
        ("with nothing decided and no language declared, the copy is the file, byte for byte",
         lambda: first.returncode in (0, 1) and first_copy == original),
        ("an image's alt text is written where it is, a path with spaces included",
         lambda: "![A chart of the data](img/my chart.png)" in copy),
        ("a decorative image loses its alt and gains .decorative in its own attributes",
         lambda: "![](img/rule.png){ width=50% .decorative }" in copy),
        ("an image whose syntax also appears inside code is left as it is, and counted",
         lambda: copy.count("![A code image](img/code.png)") == 2
         and "left as they are" in second.stderr),
        ("a bare link becomes its replacement, with its title",
         lambda: '[https://doi.org/10/abcd](https://doi.org/10/abcd "The study")' in copy),
        ("a table with no caption gets a Table: line, inside its div when it's in one",
         lambda: "| 1 | 2 |\n\nTable: First table\n" in copy
         and "| P | 1 | 2 |\n\nTable: Second table\n:::" in copy),
        ("a label paragraph gets its description joined, where it stands",
         lambda: "\nTable 1.2 Third table\n" in copy),
        ("a caption that's the table's label alone gets its description joined",
         lambda: "\nTable: Table 1.3 Fourth table\n" in copy),
        ("so does one written table:, and one with attributes, before them, which Pandoc "
         "reads back as the caption and the table's id",
         lambda: "\ntable: Table 1.4 Fifth table\n" in copy
         and "\nTable: Table 1.5 Sixth table {#tbl:five}\n" in copy
         and re.search(r'<table id="tbl:five">\s*<caption>(?:<p>)?Table 1\.5 Sixth table', copy_html)
         and "not written" not in second.stderr),
        ("the declared language goes in the front matter, and the rest is as written",
         lambda: copy.startswith("---\ntitle: Chapter\nlang: en\n---")
         and "Setext Heading\n==============\n\nSome _emphasis_ kept as written." in copy),
        ("read back, the copy's changes are only the decisions",
         lambda: subprocess.run(["pandoc", "-f", "markdown", "-t", "plain"], input=copy,
                                capture_output=True, text=True).stdout.count("First table") == 1),
    ]


def adoc_root_reads_back(work):
    """adoc/ch.adoc read back as a source gives the cube root as written:
    the index in brackets, which Pandoc's reader alone loses."""
    back = os.path.join(work, "adoc-back")
    shutil.copytree(os.path.join(work, "adoc"), back)
    with open(os.path.join(back, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    subprocess.run([sys.executable, "-B", os.path.join(BIN, "convert.py"), "--quick"],
                   cwd=back, capture_output=True, text=True)
    page = os.path.join(back, "html", "ch.html")
    return os.path.exists(page) and "<mroot>" in open(page, encoding="utf-8").read()


def case_fidelity_writers(work):
    """fidelity.csv for markdown and asciidoc targets: what the writing
    changes, as each run also says on the terminal."""
    os.makedirs(work, exist_ok=True)
    with open(os.path.join(work, "ch.md"), "w", encoding="utf-8") as fh:
        fh.write("---\ntitle: Chapter\nlang: en\n---\n\n# Chapter\n\n(@) An example.\n(@) Another.\n\n"
                 "A cube root, $\\sqrt[3]{x}$.\n")
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  md:\n    format: markdown\n  adoc:\n    format: asciidoc\n")
    run = subprocess.run([sys.executable, "-B", os.path.join(BIN, "convert.py"), "--quick"],
                         cwd=work, capture_output=True, text=True)
    report = read(work, "fidelity.csv") if exists(work, "fidelity.csv") else ""
    return [
        ("a Markdown target reports an example list, which comes back a numbered list",
         lambda: "md,ch,example-list,An example." in report),
        ("an AsciiDoc target's root with an index isn't a loss: read back, it's there",
         lambda: "root-index" not in report and adoc_root_reads_back(work)),
        ("and the Markdown target says so on the terminal",
         lambda: "md: 1 thing(s) its files can't carry" in run.stderr),
    ]


def case_cut_characters(work):
    """What a report quotes of a page, cut short, is cut between two
    characters, not inside one: a minus sign is three bytes, and the
    first of them alone isn't UTF-8, which stopped the run reading the
    report's rows back."""
    os.makedirs(work, exist_ok=True)
    cell = "a" * 56 + "−" + "b" * 10
    note = "c" * 59 + "−" + "d"
    example = "e" * 59 + "−" + "f"
    with open(os.path.join(work, "cut.md"), "w", encoding="utf-8") as fh:
        fh.write("---\ntitle: Cut\nlang: en\n---\n\n# Cut\n\n"
                 f"| {cell} | Count |\n|---|---|\n| Yes | 12 |\n\n"
                 f"A claim.[^1]\n\n[^1]: {note}\n\n    A second paragraph.\n\n"
                 f"(@) {example}\n(@) Another.\n")
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  html:\n    format: html\n  md:\n    format: markdown\n"
                 "  adoc:\n    format: asciidoc\n")
    run = run_in(work, "  contents:\n    - cut\n")
    missing = read(work, "table-captions-missing.csv") if exists(
        work, "table-captions-missing.csv") else ""
    report = read(work, "fidelity.csv") if exists(work, "fidelity.csv") else ""
    return [
        ("a table's excerpt in the captions report is cut between characters, "
         "and the run reads it back",
         lambda: run.returncode == 0
         and "a" * 56 + "−..." in missing),
        ("and so is what fidelity.csv quotes of a footnote or an example",
         lambda: run.returncode == 0
         and "adoc,cut,footnote-paragraphs," + "c" * 59 + "−" in report
         and "md,cut,example-list," + "e" * 59 + "−" in report),
    ]

def case_fidelity_epub(work):
    """fidelity.csv for an EPUB target, and a frame in Word: what the
    target filter turns into a link or text as it writes."""
    os.makedirs(work, exist_ok=True)
    with open(os.path.join(work, "handout.pdf"), "wb") as fh:
        fh.write(b"%PDF-1.4\n%%EOF\n")
    with open(os.path.join(work, "page.html"), "w", encoding="utf-8") as fh:
        fh.write('<!DOCTYPE html><html lang="en"><head><title>Page</title></head><body><h1>Page</h1>'
                 '<iframe src="https://www.youtube.com/embed/abc123" title="A lecture"></iframe>'
                 '<p><img src="https://example.org/chart.png" alt="A remote chart"></p>'
                 '<p>The <a href="handout.pdf">handout</a>.</p></body></html>')
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  epub:\n    format: epub3\n  word:\n    format: docx\n")
    run = subprocess.run([sys.executable, "-B", os.path.join(BIN, "convert.py"), "--quick"],
                         cwd=work, capture_output=True, text=True)
    report = read(work, "fidelity.csv") if exists(work, "fidelity.csv") else ""
    return [
        ("an EPUB reports a frame, a remote image, and a link to a local file, each by name",
         lambda: "epub,(book),frame,A lecture" in report
         and "epub,(book),remote-image,https://example.org/chart.png" in report
         and "epub,(book),file-link,handout.pdf" in report),
        ("and a Word target reports the frame it writes as a link",
         lambda: "word,page,frame,A lecture" in report),
    ]


def contrast(first, second):
    """WCAG 2's contrast ratio of two #rrggbb colors."""
    def luminance(color):
        channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


# Office's description of a picture, in an older version's words, over
# images.alt_max_chars's 120 characters.
LONG_GENERATED = ("A picture containing text, outdoor, grass, sky, tree, building, person, "
                  "standing, road, street, sign, car, white Description automatically generated")


def case_alt_text(work):
    """A book's alt text judged by the rules a deck's pictures are judged
    by (lib/alttext.py), images.alt_placeholders among them, each that
    needs a person in image-alt-missing.csv with why; one a sidecar row
    says was reviewed, and one that says something, not."""
    os.makedirs(os.path.join(work, "img"))
    alts = {"a": "image", "b": "IMG_2041", "c": "A dog on a lawn Description automatically "
            "generated", "d": LONG_GENERATED, "e": "chart.png", "f": "Slide figure",
            "g": "A bar chart of sales by region, highest in the west", "h": "Picture 3"}
    for name in alts:
        solid_png(os.path.join(work, "img", name + ".png"))
    with open(os.path.join(work, "page.md"), "w", encoding="utf-8") as fh:
        fh.write("# Pictures\n\n" + "".join("![%s](img/%s.png)\n\n" % (alt, name)
                                             for name, alt in alts.items()))
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  title: Alt\n  identifier: org.example.alt\n  language: en-US\n")
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("defaults:\n  images:\n    alt_placeholders: [\"slide figure\"]\n"
                 "targets:\n  html:\n    format: html\n")
    with open(os.path.join(work, "image-alt.csv"), "w", encoding="utf-8") as fh:
        fh.write("Image,Alt\nimg/h.png,\n")
    subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick"], cwd=work,
                   capture_output=True, text=True, stdin=subprocess.DEVNULL)
    rows = []
    if exists(work, "image-alt-missing.csv"):
        with open(os.path.join(work, "image-alt-missing.csv"), encoding="utf-8", newline="") as fh:
            rows = [(r["Image"], r["Reason"], r["CurrentAlt"]) for r in csv.DictReader(fh)]
    return [
        ("alt text that says nothing, a camera's name for a file, Office's descriptions, a file "
         "name, and the project's own placeholder are each reported with why, the long one's "
         "reasons together",
         lambda: rows == [
             ("img/a.png", "says nothing", "image"),
             ("img/b.png", "says nothing (a camera's or tool's name for a file)", "IMG_2041"),
             ("img/c.png", "generated by Office", alts["c"]),
             ("img/d.png", "too long (%d characters); generated by Office" % len(LONG_GENERATED),
              LONG_GENERATED),
             ("img/e.png", "a file name or extension", "chart.png"),
             ("img/f.png", "says nothing", "Slide figure")]),
    ]


def case_alt_shared(work):
    """Alt text that is only a credit, and one alt text on different
    images of a book: each in image-alt-missing.csv, the images told
    apart by their files' bytes, so the same picture in two files, or in
    two Word files' media, is one; alt text a sidecar decided is compared
    but not reported."""
    book = os.path.join(work, "md")
    os.makedirs(os.path.join(book, "img"))
    for name, rgb in (("s", (1, 1, 1)), ("up", (2, 2, 2)), ("up-copy", (2, 2, 2)),
                      ("down", (3, 3, 3)), ("dots", (4, 4, 4)), ("fall", (5, 5, 5)),
                      ("kept", (6, 6, 6))):
        solid_png(os.path.join(book, "img", name + ".png"), rgb=rgb)
    with open(os.path.join(book, "one.md"), "w", encoding="utf-8") as fh:
        fh.write("# One\n\n![Source: Roe and Doe (2020)](img/s.png)\n\n![A rising line](img/up.png)"
                 "\n\n![A rising line](img/up-copy.png)\n\n![Two dots](img/dots.png)\n\n"
                 "![A falling line](img/fall.png)\n")
    with open(os.path.join(book, "two.md"), "w", encoding="utf-8") as fh:
        fh.write("# Two\n\n![a rising line.](img/down.png)\n\n![Two dots](img/dots.png)\n\n"
                 "![A falling line](img/kept.png)\n")
    with open(os.path.join(book, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  title: Alike\n  identifier: org.example.alike\n  language: en-US\n")
    with open(os.path.join(book, "image-alt.csv"), "w", encoding="utf-8") as fh:
        fh.write("Image,Alt\nimg/kept.png,\n")

    def fail(found):
        raise AssertionError(repr(found)[:800])

    def reasons(where):
        subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick"], cwd=where,
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if not exists(where, "image-alt-missing.csv"):
            return []
        with open(os.path.join(where, "image-alt-missing.csv"), encoding="utf-8",
                  newline="") as fh:
            return sorted((r["Image"], r["Source"], r["Reason"]) for r in csv.DictReader(fh))
    md = reasons(book)
    # Two Word files holding one picture, with one alt text, then each
    # its own picture.
    word = os.path.join(work, "word")
    os.makedirs(word)
    with zipfile.ZipFile(os.path.join(FIXTURES, "media-a.docx")) as z:
        alt = re.search(r'descr="([^"]*)"', z.read("word/document.xml").decode("utf-8")).group(1)
    for name in ("media-a", "media-b"):
        with zipfile.ZipFile(os.path.join(FIXTURES, name + ".docx")) as src, \
                zipfile.ZipFile(os.path.join(word, name + ".docx"), "w") as dst:
            for info in src.infolist():
                data = src.read(info.filename)
                if info.filename == "word/document.xml":
                    data = re.sub(rb'descr="[^"]*"', b'descr="%s"' % alt.encode("utf-8"), data)
                dst.writestr(info, data)
    with open(os.path.join(word, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  title: Alike\n  identifier: org.example.word\n  language: en-US\n")
    one = [r for r in reasons(word) if "shared" in r[2]]
    with zipfile.ZipFile(os.path.join(word, "media-b.docx")) as src:
        entries = [(info, src.read(info.filename)) for info in src.infolist()]
    solid_png(os.path.join(work, "other.png"), width=1, height=1, rgb=(9, 9, 9))
    with open(os.path.join(work, "other.png"), "rb") as fh:
        other = fh.read()
    with zipfile.ZipFile(os.path.join(word, "media-b.docx"), "w") as dst:
        for info, data in entries:
            dst.writestr(info, other if info.filename == "word/media/image1.png" else data)
    two = [r for r in reasons(word) if "shared" in r[2]]
    return [
        ("alt text that is only a credit is reported, and one alt text on different pictures "
         "on each, case and closing punctuation aside; not the same picture in two files, nor "
         "the one a sidecar row decided, which is compared",
         lambda: md == [
             ("img/down.png", "two", "shared with 1 other image"),
             ("img/fall.png", "one", "shared with 1 other image"),
             ("img/s.png", "one", "a credit or a source"),
             ("img/up-copy.png", "one", "shared with 1 other image"),
             ("img/up.png", "one", "shared with 1 other image")] or fail(md)),
        ("two Word files' media holding one picture are one picture, and two aren't",
         lambda: one == [] and [r[0] for r in two] == ["media-a/media/image1.png",
                                                       "media-b/media/image1.png"]
         or fail((one, two))),
    ]


def case_highlighting(work):
    """Highlighted code in bin/highlighting.theme's colors in a page, an
    EPUB, and a Word file (lib/highlighting.py), and page.css's color for
    each token after Pandoc's, clearing 4.5:1 on the backgrounds the
    page's and the EPUB's own stylesheets give, light and dark."""
    os.makedirs(work)
    with open(os.path.join(work, "page.md"), "w", encoding="utf-8") as fh:
        fh.write("# Code\n\n```{.python .numberLines}\ntotal = 0  # a running sum\n```\n")
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  title: Code\n  identifier: org.example.code\n  language: en-US\n")
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  html:\n    format: html\n  epub:\n    format: epub3\n"
                 "  word:\n    format: docx\n")
    subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick"], cwd=work,
                   capture_output=True, text=True, stdin=subprocess.DEVNULL)
    with open(os.path.join(BIN, "highlighting.theme"), encoding="utf-8") as fh:
        theme = json.load(fh)
    comment = theme["text-styles"]["Comment"]["text-color"]
    number = theme["text-styles"]["DecVal"]["text-color"]
    page = read(work, "html", "page.html") if exists(work, "html", "page.html") else ""
    chapter = sheet = styles = ""
    if exists(work, "epub", "org.example.code.epub"):
        with zipfile.ZipFile(os.path.join(work, "epub", "org.example.code.epub")) as z:
            chapter = next((z.read(n).decode("utf-8") for n in z.namelist()
                            if n.endswith(".xhtml") and b'class="sourceCode' in z.read(n)), "")
            sheet = "".join(z.read(n).decode("utf-8") for n in z.namelist() if n.endswith(".css"))
    if exists(work, "word", "page.docx"):
        with zipfile.ZipFile(os.path.join(work, "word", "page.docx")) as z:
            styles = z.read("word/styles.xml").decode("utf-8")

    def pandocs(text):
        """The colors Pandoc's highlighting CSS gives a comment, a number,
        and a line's number, and where the CSS ends (-1 if there's none)."""
        start = text.find("/* CSS for syntax highlighting */")
        if start < 0:
            return [], -1
        end = text.find("</style>", start)
        block = text[start:end]
        found = [re.search(r"code span\.%s \{ color: (#[0-9a-f]{6});" % c, block) for c in ("co", "dv")]
        found.append(re.search(r"a:first-child::before\s*\{[^}]*?color: (#[0-9a-f]{6});", block))
        return [f.group(1) if f else None for f in found], end

    def ours(text):
        """page.css's colors for the tokens, light and dark, and where they start."""
        return (re.findall(r"code span\.\w\w \{ color: light-dark\((#[0-9a-f]{6}), (#[0-9a-f]{6})\); \}",
                           text), text.find("code span.al { color: light-dark("))

    def backgrounds(text):
        """The light and dark backgrounds a stylesheet gives the document;
        an EPUB's transparent one is the reading system's, white as a rule."""
        found = re.search(r"html \{[^}]*background-color: light-dark\((transparent|#[0-9a-f]{6}), "
                          r"(#[0-9a-f]{6})\)", text)
        return [("#ffffff" if c == "transparent" else c) for c in found.groups()] if found else []

    def word_color(style):
        found = re.search(r'<w:style [^>]*w:styleId="%s">(?:(?!</w:style>).)*?<w:color w:val="([0-9a-fA-F]{6})"'
                          % style, styles, re.S)
        return "#" + found.group(1).lower() if found else None
    page_pairs, page_ours = ours(page)
    sheet_pairs = ours(sheet)[0]
    return [
        ("a page's highlighted comment and number, and its lines' numbers, are in the theme's colors",
         lambda: pandocs(page)[0] == [comment, number, theme["line-number-color"]]),
        ("and page.css's colors for its tokens come after Pandoc's, so they're the ones a browser uses",
         lambda: len(page_pairs) == 28 and page_ours > pandocs(page)[1] > 0),
        ("an EPUB's are in the theme's colors, and its stylesheet, with page.css's, linked after them",
         lambda: pandocs(chapter)[0] == [comment, number, theme["line-number-color"]]
         and chapter.find('<link rel="stylesheet"') > pandocs(chapter)[1] > 0
         and sheet_pairs == page_pairs),
        ("page.css's colors clear 4.5:1 on the backgrounds the page's stylesheet and the "
         "EPUB's give, light and dark",
         lambda: len(backgrounds(page)) == len(backgrounds(sheet)) == 2 and all(
             contrast(light, page_bg) >= 4.5 and contrast(dark, dark_bg) >= 4.5
             for light, dark in page_pairs
             for page_bg, dark_bg in (backgrounds(page), backgrounds(sheet)))),
        ("a Word file's token styles are in the theme's colors",
         lambda: word_color("CommentTok") == comment and word_color("DecValTok") == number),
    ]


def case_remediate_docx(work):
    """A remediated copy of a Word file: the pre-pass's table declarations,
    and alt text from the image-alt sidecar, written into the author's own
    file, every other part left as it was (util/remediate.py)."""
    import zipfile
    import json
    os.makedirs(os.path.join(work, "assets"), exist_ok=True)
    for name in ("chart", "rule"):
        solid_png(os.path.join(work, "assets", name + ".png"))
    with open(os.path.join(work, "src.md"), "w", encoding="utf-8") as fh:
        fh.write("# Remediate\n\n| Name | Score |\n|------|------:|\n| Ana | 90 |\n| Ben | 85 |\n| Cy | 70 |\n\n"
                 "![](assets/chart.png)\n\nText.\n\n![](assets/rule.png){title=\"A rule\"}\n")
    subprocess.run(["pandoc", "src.md", "-o", "ch1.docx"], cwd=work, check=True)
    with zipfile.ZipFile(os.path.join(work, "ch1.docx")) as z:
        doc = z.read("word/document.xml").decode("utf-8")
        embeds = re.findall(r'r:embed="([^"]+)"', doc)
    with open(os.path.join(work, "image-alt.csv"), "w", encoding="utf-8") as fh:
        fh.write("Image,Alt\nch1/media/%s.png,Scores by student\nch1/media/%s.png,[decorative]\n"
                 % (embeds[0], embeds[1]))
    headers = run_tool(work, ["table-headers.py", "ch1.docx", "--sidecar", "none.csv",
                              "--new", "new.csv", "--report", "report.csv",
                              "--resolved", "resolved.json"])
    plain = run_tool(work, ["remediate.py", "ch1.docx", "--resolved", "resolved.json",
                            "--out", "plain"], util=True)
    plain_xml = ""
    if os.path.exists(os.path.join(work, "plain", "ch1.docx")):
        with zipfile.ZipFile(os.path.join(work, "plain", "ch1.docx")) as z:
            plain_xml = z.read("word/document.xml").decode("utf-8")
    rem = run_tool(work, ["remediate.py", "ch1.docx", "--resolved", "resolved.json",
                          "--alt", "image-alt.csv", "--include-guesses", "--out", "out"], util=True)
    refused = run_tool(work, ["remediate.py", "ch1.docx", "--out", "."], util=True)
    out = os.path.join(work, "out", "ch1.docx")
    changed, xml = [], ""
    if os.path.exists(out):
        with zipfile.ZipFile(os.path.join(work, "ch1.docx")) as a, zipfile.ZipFile(out) as b:
            changed = [n for n in a.namelist() if a.read(n) != b.read(n)]
            xml = b.read("word/document.xml").decode("utf-8")
    back = run_tool(os.path.join(work, "out"), ["table-headers.py", "ch1.docx", "--sidecar", "none.csv",
                                                "--new", "new.csv", "--report", "report.csv"]) \
        if os.path.exists(out) else None
    report = read(work, "out", "report.csv") if exists(work, "out", "report.csv") else ""
    resolved = ""
    if exists(work, "resolved.json"):
        entries = json.loads(read(work, "resolved.json")).get("ch1", [])
        resolved = entries[0]["headers"] if entries else ""
    # A person's row saying the table is a layout table, which Word can't hold.
    key = next((line.split(",")[0] for line in read(work, "new.csv").splitlines()[1:]),
               "x") if exists(work, "new.csv") else "x"
    with open(os.path.join(work, "layout.csv"), "w", encoding="utf-8") as fh:
        fh.write("key,headers\n%s,layout\n" % key)
    run_tool(work, ["table-headers.py", "ch1.docx", "--sidecar", "layout.csv",
                    "--new", "new2.csv", "--report", "report2.csv",
                    "--resolved", "layout.json"])
    layout = run_tool(work, ["remediate.py", "ch1.docx", "--resolved", "layout.json",
                             "--out", "layout"], util=True)
    layout_xml = ""
    if os.path.exists(os.path.join(work, "layout", "ch1.docx")):
        with zipfile.ZipFile(os.path.join(work, "layout", "ch1.docx")) as z:
            layout_xml = z.read("word/document.xml").decode("utf-8")
    return [
        ("a person's layout table isn't written into a Word file, which records nothing "
         "of one, and the run says so",
         lambda: layout.returncode == 0 and "<w:tblHeader/>" not in layout_xml
         and "1 layout table decision(s) not written into a Word file" in layout.stderr),
        ("with no sidecar row, the table is left alone, and the guess counted as left",
         lambda: plain.returncode == 0 and "1 left to their guess" in plain.stderr
         and not re.search(r'w:name="(?:Column|Row)?Title_\d+"', plain_xml)),
        ("the copy is written, and only word/document.xml differs from the original",
         lambda: rem.returncode == 0 and changed == ["word/document.xml"]),
        ("with --include-guesses, the table's header row is Word's repeating header row, with the bookmark for JAWS",
         lambda: "<w:tblHeader/>" in xml and re.search(r'w:name="(?:Column|Row)?Title_\d+"', xml)),
        ("read back, the pre-pass finds the table declared by the file itself, as it resolved it",
         lambda: back is not None and resolved and f",source,{resolved},"  in report),
        ("an image gets its alt text; a decorative one Word's mark and no title",
         lambda: 'descr="Scores by student"' in xml and "adec:decorative" in xml
         # and the decorative image has no description or title at all, as
         # Word leaves one it marks decorative
         and all('descr=' not in tag and 'title=' not in tag for tag in re.findall(
             r"<wp:docPr\b[^>]*>(?=<a:extLst[^>]*><a:ext uri=\"\{C183D7F6)", xml))
         and re.search(r"<wp:docPr\b[^>]*><a:extLst[^>]*><a:ext uri=\"\{C183D7F6", xml)
         and 'title="A rule"' not in xml),
        ("it won't write over the file it reads",
         lambda: refused.returncode == 2 and "overwritten" in refused.stderr),
    ]


def case_side_by_side(work):
    """Pictures in a row in a figure (<figure><div class="row"><figure>, as
    LibreTexts sets two): in a browser, side by side in a wide window, one
    under another in a phone's. Needs Playwright and its Chromium, and
    skips without them."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  skip  Playwright not installed; pictures in a row aren't laid out")
        return []
    os.makedirs(os.path.join(work, "img"))
    for name in ("left.png", "right.png"):
        with open(os.path.join(work, "img", name), "wb") as fh:
            fh.write(ONE_PIXEL)
    with open(os.path.join(work, "pair.html"), "w", encoding="utf-8") as fh:
        fh.write('<!DOCTYPE html><html lang="en"><head><title>Pair</title></head><body>'
                 "<h1>Pair</h1><figure><div class=\"row\"><figure>"
                 '<img src="img/left.png" alt="A left square" width="300" height="300"></figure>'
                 '<figure><img src="img/right.png" alt="A right square" width="300" height="300">'
                 "</figure></div><figcaption>Two squares, left and right</figcaption></figure>"
                 "</body></html>")
    result = convert(work, "targets:\n  html:\n    format: html\n", fixtures=())
    boxes = {}
    page = os.path.join(work, "html", "pair.html")
    if result.returncode == 0 and os.path.exists(page):
        try:
            with sync_playwright() as play:
                browser = play.chromium.launch()
                for width in (1000, 360):
                    view = browser.new_page(viewport={"width": width, "height": 800})
                    view.goto("file://" + page)
                    boxes[width] = [view.locator(f'img[alt="{alt}"]').bounding_box()
                                    for alt in ("A left square", "A right square")]
                    view.close()
                browser.close()
        except Exception as exc:
            print(f"  skip  Playwright's Chromium doesn't start ({str(exc)[:100]})")
            return []
    wide, narrow = boxes.get(1000), boxes.get(360)
    return [
        ("in a wide window the pictures in a figure's row stand side by side, left and right",
         lambda: wide and abs(wide[0]["y"] - wide[1]["y"]) < 1
         and wide[0]["x"] + wide[0]["width"] <= wide[1]["x"]),
        ("and in a phone's, one under another, each within the window",
         lambda: narrow and narrow[0]["y"] + narrow[0]["height"] <= narrow[1]["y"]
         and all(b["x"] + b["width"] <= 360 for b in narrow)),
    ]


# A worked example's steps as the CNX unpacker lays out a formula of them
# (lib/cnx/steptables.py's formula_steps): its math cell for cell, the
# second step's left side empty, and each step's reason in words; and a
# table of data after them.
STEPS_PAGE = (
    '<!DOCTYPE html><html lang="en"><head><title>Steps</title></head><body><h1>Steps</h1>'
    '<table role="presentation" class="formula-steps"><tbody>' + "".join(
        '<tr><td style="text-align: right">%s</td><td style="text-align: center">'
        '<math xmlns="http://www.w3.org/1998/Math/MathML"><mo>=</mo></math></td>'
        '<td style="text-align: left"><math xmlns="http://www.w3.org/1998/Math/MathML">'
        "%s</math></td><td style=\"text-align: left\">%s</td></tr>" % row for row in (
            ('<math xmlns="http://www.w3.org/1998/Math/MathML"><mrow><mn>3</mn><mi>x</mi>'
             "<mo>+</mo><mn>4</mn><mi>x</mi></mrow></math>",
             "<mrow><mn>7</mn><mi>x</mi></mrow>",
             "Combine like terms, the terms whose variables and powers are the same, "
             "into one term"),
            ("", "<mrow><mn>7</mn><mo>\u22c5</mo><mn>2</mn></mrow>",
             "Substitute two for x, as the question gives it")))
    + "</tbody></table><table><caption>Values</caption><thead><tr><th>Term</th>"
    "<th>Value</th></tr></thead><tbody><tr><td>x</td><td>2</td></tr></tbody></table>"
    "</body></html>")


def case_formula_steps_reflow(work):
    """A worked example's steps the CNX unpacker lays out in a table (class
    formula-steps), in a browser: in a wide window, in their columns, the
    relations one over another, and no rule above or below them, where a
    table of data has its rules; in a phone's, each step's math on a line,
    and its words wrapping within the window, where a layout table's cells
    stack, each on a line of its own. Needs Playwright and its Chromium,
    and skips without them."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  skip  Playwright not installed; steps aren't laid out")
        return []
    os.makedirs(work)
    with open(os.path.join(work, "steps.html"), "w", encoding="utf-8") as fh:
        fh.write(STEPS_PAGE)
    result = convert(work, "targets:\n  html:\n    format: html\n", fixtures=())
    boxes, rules = {}, {}
    page = os.path.join(work, "html", "steps.html")
    if result.returncode == 0 and os.path.exists(page):
        try:
            with sync_playwright() as play:
                browser = play.chromium.launch()
                for width in (1000, 360):
                    view = browser.new_page(viewport={"width": width, "height": 800})
                    view.goto("file://" + page)
                    rows = view.locator("table.formula-steps tr")
                    boxes[width] = [[rows.nth(r).locator("td").nth(c).bounding_box()
                                     for c in range(4)] for r in range(2)]
                    if width == 1000:
                        # The rules above and below each table's body.
                        rules.update(view.evaluate(
                            "() => Object.fromEntries([...document.querySelectorAll("
                            "'table')].map(t => [t.className || 'data', ["
                            "getComputedStyle(t.tBodies[0]).borderTopWidth, "
                            "getComputedStyle(t.tBodies[0]).borderBottomWidth]]))"))
                    view.close()
                browser.close()
        except Exception as exc:
            print(f"  skip  Playwright's Chromium doesn't start ({str(exc)[:100]})")
            return []
    wide, narrow = boxes.get(1000), boxes.get(360)

    def on_a_line(cells):
        """Whether cells stand side by side, left to right, their tops alike."""
        return all(abs(a["y"] - b["y"]) < 8 and a["x"] + a["width"] <= b["x"] + 1
                   for a, b in zip(cells, cells[1:]))
    return [
        ("in a wide window a worked example's steps laid out as a table are in their "
         "columns, each step on a line, the relations one over another",
         lambda: wide and all(on_a_line(row) for row in wide)
         and abs(wide[0][1]["x"] - wide[1][1]["x"]) < 1),
        ("with no rule above them or below, as OpenStax sets the formula, where a "
         "table of data has both",
         lambda: rules.get("formula-steps") == ["0px", "0px"]
         and rules.get("data") == ["1px", "1px"]),
        ("and in a phone's, a step's math on a line, not a cell to a line, an empty "
         "cell no gap, and its words within the window",
         lambda: narrow and on_a_line(narrow[0][:3]) and on_a_line(narrow[1][1:3])
         and narrow[1][1]["x"] <= narrow[0][0]["x"] + 1
         and all(cell is None or cell["x"] + cell["width"] <= 360
                 for row in narrow for cell in row if cell and cell["width"])),
    ]


def case_word_box(work):
    """A box (a div of class box) in a Word file: each paragraph in it,
    its legend, a list's item, and a formula's paragraph alike, given the
    same border, which Word draws around them as one, in its place among
    the paragraph's properties; a table in it keeps its own, the text
    outside it has none, and the mark that found it is gone."""
    os.makedirs(work)
    with open(os.path.join(work, "page.md"), "w", encoding="utf-8") as fh:
        fh.write("# Boxes\n\nBefore the box.\n\n::: box\n### Example 1.1\n\nA question.\n\n"
                 "- a step\n- another\n\n$$x^2 + y^2 = z^2$$\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n"
                 "#### Solution\n\nAn answer.\n:::\n\nAfter the box.\n")
    result = convert(work, "targets:\n  word:\n    format: docx\n", fixtures=())
    xml = ""
    if exists(work, "word", "page.docx"):
        with zipfile.ZipFile(os.path.join(work, "word", "page.docx")) as z:
            xml = z.read("word/document.xml").decode("utf-8")
    order = ("pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl",
             "numPr", "suppressLineNumbers", "pBdr", "shd", "tabs", "spacing", "ind", "jc",
             "rPr")

    def paragraphs(inside_tables):
        found, depth = [], 0
        for token in re.split(r"(<w:tbl>|</w:tbl>|<w:p>.*?</w:p>)", xml, flags=re.S):
            if token == "<w:tbl>":
                depth += 1
            elif token == "</w:tbl>":
                depth -= 1
            elif token.startswith("<w:p>") and (depth > 0) == inside_tables:
                found.append(("".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", token)),
                              "<w:pBdr>" in token, re.search(r"<w:pPr>(.*?)</w:pPr>", token, re.S)))
        return found

    def in_order(props):
        names = [n for n in re.findall(r"<w:(\w+)", props.group(1)) if n in order]
        return names == sorted(names, key=order.index)
    outside = paragraphs(False)
    return [
        ("each paragraph in a box has its border, its legend, a list's items, and a formula's "
         "paragraph alike, and the text outside has none",
         lambda: result.returncode == 0
         and [text for text, bordered, _ in outside if bordered]
         == ["Example 1.1", "A question.", "a step", "another", "", "Solution", "An answer."]
         and all(not bordered for text, bordered, _ in outside
                 if text in ("Boxes", "Before the box.", "After the box."))),
        ("in its place among the paragraph's properties, a table in the box keeps its own, and "
         "the mark is gone",
         lambda: all(in_order(props) for _, bordered, props in outside if bordered and props)
         and not any(bordered for _, bordered, _ in paragraphs(True))
         and "tiqBox" not in xml),
    ]


def case_docx_target(work):
    """A docx target: Pandoc's Word file, then compatibility mode 15,
    ScreenTips, Word's decorative marker, the First Column flag, and a bar
    Narrator reads; and the file read back as a source gives the book
    back."""
    import zipfile as zf
    os.makedirs(os.path.join(work, "assets"))
    for name in ("chart.png", "rule.png"):
        with open(os.path.join(work, "assets", name), "wb") as fh:
            fh.write(PNG_1PX if name == "chart.png" else PNG_1PX + b"\0")
    with open(os.path.join(work, "one.md"), "w", encoding="utf-8") as fh:
        fh.write("---\ntitle: One\nlang: en\n---\n\n# One\n\n"
                 'See [the data](https://example.org/data "The data, as a CSV file").[^1]\n\n'
                 "![A navy bar standing for the chart](assets/chart.png)\n\n![](assets/rule.png)\n\n"
                 "![Chart of the data](assets/chart.png){#fig-chart}\n\nAs [the chart](#fig-chart) shows.\n\n"
                 "- one\n- two, first paragraph\n\n  two, second paragraph\n- three\n\nThen code:\n\n"
                 "- alpha\n- beta\n\n  ```\n  code in beta\n  ```\n- gamma\n\n"
                 "> Outer quote.\n>\n> ```\n> quoted code\n> ```\n>\n> > Inner quote.\n> >\n> > Inner, second paragraph.\n\n> A second quote, right after.\n\nAfter the quotes.\n\n"
                 "What is a set?\n:   \n\nWhy is order irrelevant?\n:   \n\n"
                 "```{.python .numberLines startFrom=\"5\"}\ntotal = 0\nfor x in data:\n    total += x\n```\n\n"
                 "```js\nlet shown = true;\n```\n\n"
                 "```{.my-lang}\nno bookmark for this one\n```\n\n"
                 "The mean $\\bar{x}$, the segment $\\overline{AB}$, and the estimate $\\hat{y}$.\n\n"
                 "## Foundations {#_foundations}\n\nSee [the foundations](#_foundations).\n\n"
                 "## Long {#an-identifier-well-past-the-forty-characters-word-allows}\n\n"
                 "Back to [the long one](#an-identifier-well-past-the-forty-characters-word-allows).\n\n"
                 '[^1]: The [source](https://example.org/source "Where the data came from") explains it,'
                 ' with its mean $\\bar{y}$.\n')
    with open(os.path.join(work, "two.html"), "w", encoding="utf-8") as fh:
        fh.write('<!DOCTYPE html><html lang="en"><head><title>Two</title></head><body><h1>Two</h1>'
                 "<table><caption>Costs by year</caption><thead><tr><th>Item</th><th>2024</th>"
                 "<th>2025</th></tr></thead><tbody><tr><th>Labor</th><td>10</td><td>12</td></tr>"
                 "<tr><th>Parts</th><td>4</td><td>5</td></tr></tbody></table>"
                 '<p>See <a href="one.html#_foundations">foundations</a> and '
                 '<a href="one.html#an-identifier-well-past-the-forty-characters-word-allows">the long one</a>.</p>'
                 "</body></html>")
    with open(os.path.join(work, "three.html"), "w", encoding="utf-8") as fh:
        fh.write('<!DOCTYPE html><html lang="en"><head><title>Three</title></head><body><h1>Three</h1>'
                 '<table role="presentation"><tr><td><p>Layout, left.</p></td><td><p>Layout, right.</p></td></tr></table>'
                 '<figure><img src="assets/chart.png" alt="Before"><img src="assets/chart.png" alt="After">'
                 "<figcaption>Before and after</figcaption></figure>"
                 '<figure><img src="assets/rule.png" alt=""></figure>'
                 "<blockquote><p>Try these:</p><ul><li>sorting</li><li>reversing</li></ul></blockquote>"
                 "<blockquote><ul><li><ul><li>a list that opens with a list</li></ul></li></ul></blockquote>"
                 "<table><caption>Addresses used</caption><thead><tr><th>Name</th><th>IP address</th></tr></thead>"
                 "<tbody><tr><td>server</td><td>172.20.0.5</td></tr><tr><td>victim</td><td>172.20.0.6</td></tr>"
                 "<tr><td>attacker</td><td>172.20.0.7</td></tr></tbody></table>"
                 "<table><caption>Two groups</caption><tbody><tr><th colspan=\"2\">Group A</th></tr>"
                 "<tr><td>1</td><td>2</td></tr></tbody><tbody><tr><th colspan=\"2\">Group B</th></tr>"
                 "<tr><td>3</td><td>4</td></tr></tbody></table>"
                 '<table><caption>Nested</caption><tbody><tr><td style="text-align: center">'
                 '<table><tbody><tr><td style="text-align: right">inner right</td><td>inner plain</td></tr>'
                 '</tbody></table></td><td style="text-align: right">outer right</td></tr></tbody></table>'
                 "</body></html>")
    with open(os.path.join(work, "image-alt.csv"), "w", encoding="utf-8") as fh:
        fh.write("Image,Alt\nassets/rule.png,[decorative]\n")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  word:\n    format: docx\n")
    run = subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick"], cwd=work,
                         capture_output=True, text=True, stdin=subprocess.DEVNULL)

    def part(name, inside):
        path = os.path.join(work, "word", name)
        if not os.path.exists(path):
            return ""
        with zf.ZipFile(path) as z:
            return z.read(inside).decode("utf-8") if inside in z.namelist() else ""
    one = part("one.docx", "word/document.xml") + part("one.docx", "word/footnotes.xml")
    two = part("two.docx", "word/document.xml")
    # Read the Word files back, as a book of their own.
    back = os.path.join(work, "back")
    os.makedirs(back)
    for name in ("one.docx", "two.docx", "three.docx"):
        if os.path.exists(os.path.join(work, "word", name)):
            shutil.copy(os.path.join(work, "word", name), back)
    with open(os.path.join(back, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick"], cwd=back,
                   capture_output=True, text=True, stdin=subprocess.DEVNULL)
    one_back = read(back, "html", "one.html") if exists(back, "html", "one.html") else ""
    two_back = read(back, "html", "two.html") if exists(back, "html", "two.html") else ""
    three = part("three.docx", "word/document.xml")
    fidelity = read(work, "fidelity.csv") if exists(work, "fidelity.csv") else ""

    def table_with(xml, text):
        return next((t for t in re.findall(r"<w:tbl>.*?</w:tbl>", xml, re.S) if text in t), "")

    def html_table_with(page, text):
        return next((t for t in re.findall(r"<table\b.*?</table>", page, re.S) if text in t), "")

    def para_with(xml, text):
        return next((p for p in re.findall(r"<w:p\b.*?</w:p>", xml, re.S) if text in p), "")
    three_back =read(back, "html", "three.html") if exists(back, "html", "three.html") else ""
    return [
        ("a docx target writes a Word file per page, in compatibility mode 15",
         lambda: "3 Word file(s)" in run.stderr and all(
             'w:name="compatibilityMode"' in part(n, "word/settings.xml")
             and 'w:val="15"' in part(n, "word/settings.xml") for n in ("one.docx", "two.docx"))),
        ("a bar is an accent of the macron, which Narrator reads, where Pandoc wrote the "
         "overline; the segment's overbar and the hat are as Pandoc wrote them",
         lambda: one.count('<m:chr m:val="\u00af" />') == 2 and "\u203e" not in one
         and '<m:bar><m:barPr><m:pos m:val="top" /></m:barPr>' in one
         and '<m:chr m:val="\u0302" />' in one
         and "2 bar accent(s) given the macron, which Narrator reads" in run.stderr),
        ("read back as a source, the bar is \\bar again, in the text and in a note, and "
         "the segment \\overline",
         lambda: "\\bar{x}</annotation>" in one_back and "\\bar{y}</annotation>" in one_back
         and "\\overline{AB}</annotation>" in one_back and "\\hat{y}</annotation>" in one_back),
        ("a link's title is its ScreenTip, in the body and in a footnote",
         lambda: 'w:tooltip="The data, as a CSV file"' in one
         and 'w:tooltip="Where the data came from"' in one),
        ("a decorative image carries Word's marker and no description or title, as "
         "Word leaves it; a described one its description",
         lambda: one.count("adec:decorative") == 1
         and re.search(r'<wp:docPr id="\d+" name="[^"]*"><a:extLst[^>]*><a:ext uri="\{C183D7F6', one)
         and 'descr="A navy bar standing for the chart"' in one),
        ("a table's header row repeats and its header column is flagged",
         lambda: "<w:tblHeader" in two and 'w:firstColumn="1"' in two and 'w:val="00A0"' in two),
        ("read back as a source, the links have their titles and the image is decorative",
         lambda: 'title="The data, as a CSV file"' in one_back
         and 'title="Where the data came from"' in one_back
         and re.search(r'<img[^>]*alt=""[^>]*aria-hidden="true"', one_back)),
        ("a captioned figure with an id reads back as a figure with its caption, "
         "and a link to it still lands", lambda: re.search(
             r"<figure\b[^>]*>(?:(?!</figure>).)*<figcaption[^>]*>(?:(?!</figcaption>).)*Chart of the data", one_back, re.S)
         and re.search(r'href="#([^"]+)"[^>]*>the chart<', one_back)
         and 'id="' + re.search(r'href="#([^"]+)"[^>]*>the chart<', one_back).group(1) + '"' in one_back),
        ("a list item's second paragraph and its code block stay in the item, the lists whole",
         lambda: re.search(r"<li>\s*<p>two, first paragraph</p>\s*<p>two, second paragraph</p>\s*</li>", one_back)
         and re.search(r"<li>\s*<p>beta</p>\s*<pre[^>]*>(?:(?!</li>).)*code in beta", one_back, re.S)
         and len(re.findall(r"<ul\b", one_back)) == 2),
        ("a quote keeps its code and the quote nested in it, and no marker is left",
         lambda: re.search(r"<blockquote>\s*<p>Outer quote\.</p>\s*<pre[^>]*>(?:(?!</blockquote>).)*"
                           r"quoted code(?:(?!</blockquote>).)*<blockquote>\s*<p>Inner quote\.</p>\s*"
                           r"<p>Inner, second paragraph\.</p>\s*</blockquote>",
                           one_back, re.S)
         and "tiqQuote1" not in one and "tiqQuote" not in one_back),
        ("two quotes in a row come back as two",
         lambda: re.search(r"<p>Inner, second paragraph\.</p>\s*</blockquote>\s*</blockquote>\s*"
                           r"<blockquote>\s*<p>A second quote, right after\.</p>\s*</blockquote>", one_back)),
        ("terms with no definition, like review questions, read back as one description list",
         lambda: re.search(r"<dl>\s*<dt>What is a set\?</dt>(?:(?!</dl>).)*<dt>Why is order irrelevant\?</dt>",
                           one_back, re.S)),
        ("ids Pandoc's writer hashes are mapped in the Word file and read back as they were",
         lambda: "OERforge/TextbookImprover/ids" in part("one.docx", "customXml/item1.xml")
         and 'id="_foundations"' in one_back
         and 'id="an-identifier-well-past-the-forty-characters-word-allows"' in one_back
         and 'href="#_foundations"' in one_back),
        ("so a link from another page still lands on it",
         lambda: all(f'href="one.html#{i}"' in two_back and f'id="{i}"' in one_back
                     for i in ("_foundations",
                               "an-identifier-well-past-the-forty-characters-word-allows"))),
        ("numbered code shows its numbers in Word, in Word's Line Number style, from its first number",
         lambda: re.search(r'LineNumber" /></w:rPr><w:t xml:space="preserve">5  </w:t>', one)
         and re.search(r'LineNumber" /></w:rPr><w:t xml:space="preserve">7  </w:t>', one)
         and 'w:styleId="LineNumber"' in part("one.docx", "word/styles.xml")),
        ("read back, it's numbered again from 5, without the numbers in its text, and keeps its language",
         lambda: re.search(r'<pre\s+class="[^"]*python[^"]*numberLines[^"]*">', one_back)
         and "counter-reset: source-line 4" in one_back and "5  total" not in one_back),
        ("a code block keeps its language through Word, and one whose name can't go in a bookmark is reported",
         lambda: re.search(r'<code class="sourceCode (?:js|javascript)"', one_back)
         and "word,one,code-language,my-lang" in fidelity),
        ("each table carries the bookmark JAWS reads as its headers, and a banded table with no header row none",
         lambda: 'w:name="Title_1"' in two
         and re.search(r'w:name="ColumnTitle_\d+"', table_with(three, "172.20.0.5"))
         and not re.search(r'Title_\d+', table_with(three, "Group A"))),
        ("the marks land on the table they belong to, not by position: a figure written "
         "as a table and a layout table carry none",
         lambda: not re.search(r'Title_\d+|w:firstColumn="1"', table_with(three, "Layout, left"))
         and "<w:drawing>" in three and not any(
             "Title_" in t or 'w:firstColumn="1"' in t
             for t in re.findall(r"<w:tbl>.*?</w:tbl>", three, re.S) if "<w:drawing>" in t)
         and "tiqTable" not in three and "tiqDecorative" not in three),
        ("a decorative image that is a figure's whole content stays a picture, marked decorative",
         lambda: three.count("adec:decorative") == 1 and not any(
             "adec:decorative" in t for t in re.findall(r"<w:tbl>.*?</w:tbl>", three, re.S))),
        ("a table's caption is kept with it, so the table before doesn't take it on reading",
         lambda: 'TableCaption" /><w:keepNext' in three
         and re.search(r"<caption>(?:(?!</table>).)*Addresses used(?:(?!</table>).)*172\.20\.0\.5",
                       three_back, re.S)
         and not re.search(r"<caption>(?:(?!</table>).)*Layout, left", three_back, re.S)),
        ("a cell of a table in an aligned table's cell has one alignment, its own, as the schema allows",
         lambda: all(p.count("<w:jc ") <= 1 for p in re.findall(r"<w:pPr>.*?</w:pPr>", three, re.S))
         and '<w:jc w:val="right" />' in para_with(three, "inner right")
         and 'w:val="center"' not in para_with(three, "inner right")),
        ("what the Word files can't carry is reported, page by page",
         lambda: all(k in fidelity for k in ("word,three,layout-table",
                                              "word,three,uncaptioned-figure"))
         and "list-in-quotation" not in fidelity),
        # Pandoc's reader never puts a list in a quote; the Word target
        # indents a quote's list a quote step beyond its level, says so in a
        # document variable, and reading Word puts the list back.
        ("a list inside a quotation is indented inside it in Word, and read back it's in the quotation again",
         lambda: re.search(r'<w:ind w:left="1200" w:hanging="360" />(?:(?!</w:p>).)*sorting', three, re.S)
         and "TextbookImproverQuotedLists" in part("three.docx", "word/settings.xml")
         and re.search(r"<blockquote>\s*<p>Try these:</p>\s*<ul>\s*<li>\s*(?:<p>)?sorting", three_back)
         and re.search(r"<blockquote>\s*<ul>\s*<li>\s*<ul>\s*<li>\s*(?:<p>)?a list that opens", three_back)),
        ("read back, a table declared with a header row only has no header column, "
         "and the bookmark leaves no anchor", lambda: html_table_with(three_back, "172.20.0.5").count('<th scope="col"') == 2
         and 'scope="row"' not in html_table_with(three_back, "172.20.0.5") and "ColumnTitle" not in three_back
         and "Title_1" not in two_back),
        ("and the table has its header row and header column",
         lambda: '<th scope="col">' in two_back and '<th scope="row">Labor</th>' in two_back),
    ]


def case_title_heading(work):
    """A page's title heading is its own H1 in every output, shown once; a
    declared title that isn't one of its headings is shown above them; the
    EPUB's title page follows the book's structure (title_page: auto)."""
    said = {}

    def book(name, pages, targets, extra="", project=""):
        path = os.path.join(work, name)
        os.makedirs(path)
        for stem, text in pages:
            with open(os.path.join(path, stem + ".md"), "w", encoding="utf-8") as fh:
                fh.write(text)
        with open(os.path.join(path, "project.yaml"), "w", encoding="utf-8") as fh:
            fh.write("project:\n  title: The Book\n  identifier: org.example.%s\n"
                     "  language: en-US\n  contents:\n" % name
                     + "".join("    - %s\n" % stem for stem, _ in pages) + project)
        with open(os.path.join(path, "conversion.yaml"), "w", encoding="utf-8") as fh:
            fh.write("targets:\n" + targets + extra)
        result = subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"], cwd=path,
                                capture_output=True, text=True, stdin=subprocess.DEVNULL)
        said[name] = result.stdout + result.stderr
        return path

    def epub_files(path):
        found = glob.glob(os.path.join(path, "epub", "*.epub"))
        if not found:
            return {}
        with zipfile.ZipFile(found[0]) as z:
            return {n: z.read(n).decode("utf-8") for n in z.namelist() if n.endswith(".xhtml")}

    every = ("  html:\n    format: html\n  word:\n    format: docx\n"
             "  md:\n    format: markdown\n  epub:\n    format: epub3\n")
    one = book("one", [("first", "# First Chapter\n\nOpening.\n\n## A Section\n\nText.\n")], every)
    html = read(one, "html", "first.html") if exists(one, "html", "first.html") else ""
    markdown = read(one, "md", "first.md") if exists(one, "md", "first.md") else ""
    word_styles, core = [], ""
    if exists(one, "word", "first.docx"):
        with zipfile.ZipFile(os.path.join(one, "word", "first.docx")) as z:
            document = z.read("word/document.xml").decode("utf-8")
            core = z.read("docProps/core.xml").decode("utf-8")
        word_styles = re.findall(r'<w:pStyle w:val="([^"]+)"', document)
    one_epub = epub_files(one)
    two = book("two", [("a", "# Alpha\n\nText.\n"), ("b", "# Beta\n\nText.\n")],
               "  epub:\n    format: epub3\n")
    off = book("off", [("a", "# Alpha\n\nText.\n"), ("b", "# Beta\n\nText.\n")],
               "  epub:\n    format: epub3\n    title_page: \"off\"\n")
    report = book("report", [("report", "---\ntitle: A Short Report\n---\n\n# Background\n\n"
                                        "Text.\n\n# Method\n\nText.\n\n# Results\n\nText.\n")],
                  "  html:\n    format: html\n  epub:\n    format: epub3\n")
    report_html = read(report, "html", "report.html") if exists(report, "html", "report.html") else ""
    numbered = book("numbered", [("defs", "---\ntitle: Definitions\n---\n\n# 1.1 Definitions\n\nText.\n")],
                    "  html:\n    format: html\n")
    numbered_html = read(numbered, "html", "defs.html") if exists(numbered, "html", "defs.html") else ""
    kept = book("kept", [("defs", "---\ntitle: Definitions\n---\n\n# 1.1 Definitions\n\nText.\n")],
                "  html:\n    format: html\n", "defaults:\n  promote_h1_to_title: always\n")
    kept_html = read(kept, "html", "defs.html") if exists(kept, "html", "defs.html") else ""
    # A declared title that is the numbered heading, number and all, and one
    # shorter than its heading that keeps the number.
    same = book("same", [("defs", "---\ntitle: 1.1 Definitions\n---\n\n# 1.1 Definitions\n\nText.\n")],
                "  html:\n    format: html\n")
    same_html = read(same, "html", "defs.html") if exists(same, "html", "defs.html") else ""
    shorter = book("shorter", [("defs", "---\ntitle: 1.1 Definitions\n---\n\n"
                                        "# 1.1 Definitions and Notation\n\nText.\n")],
                   "  html:\n    format: html\n")
    shorter_html = read(shorter, "html", "defs.html") if exists(shorter, "html", "defs.html") else ""
    # A Word Title with a curly apostrophe over a heading with a straight one.
    quoted = book("quoted", [("cohen", "---\ntitle: Cohen\u2019s Standards\n---\n\n"
                                       "# 10.2 Cohen\\'s standards\n\nText.\n")],
                  "  html:\n    format: html\n")
    quoted_html = read(quoted, "html", "cohen.html") if exists(quoted, "html", "cohen.html") else ""
    # A numbered book whose page title is long enough for the writer to wrap.
    long_title = "A Chapter Title Long Enough That the HTML Writer Wraps It Across Two Lines"
    wrapped = book("wrapped", [("a", "# %s\n\nText.\n" % long_title), ("b", "# Beta\n\nText.\n")],
                   "  html:\n    format: html\n", project="  numbering: true\n")
    wrapped_html = " ".join(read(wrapped, "html", "a.html").split()) if exists(wrapped, "html", "a.html") else ""
    return [
        ("the HTML has the page's H1 in its body, with its id, and no title block",
         lambda: '<h1 id="first-chapter">First Chapter</h1>' in html
         and "title-block-header" not in html and "<title>First Chapter</title>" in html),
        ("the Word file has it as a Heading 1, not a Title paragraph, and the title in "
         "its properties", lambda: word_styles[:1] == ["Heading1"] and "Title" not in word_styles
         and "<dc:title>First Chapter</dc:title>" in core),
        ("the Markdown has it as a # heading, and the title in its metadata",
         lambda: "\n# First Chapter\n" in markdown and "title: First Chapter" in markdown),
        ("a one-page book's EPUB has no title page, and its one chapter's heading is the page's",
         lambda: one_epub and not any("title_page" in n for n in one_epub)
         and any(">First Chapter</h1>" in t for t in one_epub.values())),
        ("a book of two chapters has a title page; title_page off takes it away",
         lambda: any("title_page" in n for n in epub_files(two))
         and epub_files(off) and not any("title_page" in n for n in epub_files(off))),
        ("a declared title that isn't one of the page's headings is shown above them, "
         "and its EPUB, three chapters, has a title page",
         lambda: '<h1 class="title">A Short Report</h1>' in report_html
         and report_html.count("<h1") == 4
         and any("title_page" in n for n in epub_files(report))),
        ("the run says when a title stands without its heading's number, and "
         "always keeps the number", lambda: "without the number their heading" in said["numbered"]
         and "<title>1.1 Definitions</title>" in kept_html
         and "without the number their heading" not in said["kept"]),
        ("and says nothing of it when the title has the number, whether it's the heading or "
         "shorter", lambda: "<title>1.1 Definitions</title>" in same_html
         and "<title>1.1 Definitions</title>" in shorter_html
         and "without the number their heading" not in said["same"] + said["shorter"]),
        ("curly and straight apostrophes, and case, don't keep a heading from "
         "saying the title", lambda: quoted_html.count("<h1") == 1),
        ("a numbered book numbers the page's own heading, wrapped or not",
         lambda: ">1 " + long_title + "</h1>" in wrapped_html),
        ("an H1 that says the declared title with a number before it is the title "
         "heading, and the declared title stands",
         lambda: "<title>Definitions</title>" in numbered_html
         and numbered_html.count("<h1") == 1 and ">1.1 Definitions</h1>" in numbered_html),
    ]


def word_from_markdown(path, text, *metadata):
    """A Word file Pandoc writes from Markdown, with metadata given as -M,
    which its writer writes where it writes each: lang as the document's
    language, any other field a custom property."""
    command = ["pandoc", "-f", "markdown", "-t", "docx", "-o", path]
    for field in metadata:
        command += ["-M", field]
    subprocess.run(command, input=text, text=True, check=True, capture_output=True)


def word_language(path):
    """A Word file's default language, its document defaults' w:lang."""
    if not os.path.exists(path):
        return ""
    with zipfile.ZipFile(path) as z:
        styles = z.read("word/styles.xml").decode("utf-8")
    defaults = re.search(r"<w:docDefaults>.*?</w:docDefaults>", styles, re.S)
    found = re.search(r"<w:lang\b[^>]*>", defaults.group(0)) if defaults else None
    return found.group(0) if found else ""


def root_language(text):
    """An HTML or XHTML file's root's lang, and xml:lang when it has one."""
    root = re.search(r"<html\b[^>]*>", text or "")
    if not root:
        return None
    found = dict(re.findall(r'\s((?:xml:)?lang)="([^"]*)"', root.group(0)))
    return found.get("lang"), found.get("xml:lang")


LANGUAGE_PAGES = {
    "deutsch.md": "---\ntitle: Deutsch\n---\n\nEin Satz in der Sprache des Buches.\n",
    "chapitre.md": "---\ntitle: Chapitre\nlang: fr\n---\n\nUne phrase en français.\n",
}


def case_page_languages(work):
    """Each page's language, decided once for every target: a row of
    languages.csv, else what its own file declares (a Word file's text, the
    language property OpenStax's Word files carry, a Markdown file's lang, a
    hand-written page's), else the book's, a file's that differs from the
    book's only in region the book's; what the book puts on a page in
    another language marked in the book's; the copies; and the report."""
    os.makedirs(os.path.join(work, "_pt"))
    for name, text in LANGUAGE_PAGES.items():
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    word_from_markdown(os.path.join(work, "espanol.docx"),
                       "# Español\n\nUn texto bastante largo en español.\n", "lang=es-ES")
    # As OpenStax's are: Pandoc's output, its language a custom property,
    # the document's language the reference document's US English.
    word_from_markdown(os.path.join(work, "funciones.docx"),
                       "# Funciones\n\nUna función asigna a cada entrada una salida.\n",
                       "company=OpenStax", "language=es")
    word_from_markdown(os.path.join(work, "osterreich.docx"),
                       "# Österreich\n\nEin Satz aus Wien.\n", "lang=de-AT")
    with open(os.path.join(work, "_pt", "about.html"), "w", encoding="utf-8") as fh:
        fh.write('<!DOCTYPE html><html lang="it"><head><title>Chi siamo</title></head><body>'
                 "<h1>Chi siamo</h1><p>Un testo scritto a mano.</p></body></html>")
    # An HTML page that says it's in English, which a row corrects.
    with open(os.path.join(work, "seite.html"), "w", encoding="utf-8") as fh:
        fh.write('<!DOCTYPE html>\n<html lang="en"><head><title>Seite</title></head><body>'
                 "<h1>Seite</h1><p>Ein Absatz aus Zürich.</p></body></html>\n")
    with open(os.path.join(work, "languages.csv"), "w", encoding="utf-8") as fh:
        fh.write("source,language\nchapitre,fr-CA\nseite.html,de-CH\nnothing,it\n"
                 "broken,French\n")
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  identifier: org.example.languages\n  title: Sprachen\n"
                 "  language: de\n")
    first = convert(work, 'defaults:\n  footer: "A *footer*."\n'
                    "targets:\n  html:\n    format: html\n    header: \"A *banner*.\"\n"
                    "  md:\n    format: markdown\n  word:\n    format: docx\n"
                    "  epub:\n    format: epub3\n  src:\n    format: source\n",
                    project=False, fixtures=())
    pages = {stem: read(work, "html", stem + ".html") if exists(work, "html", stem + ".html")
             else "" for stem in ("deutsch", "chapitre", "espanol", "funciones", "osterreich")}
    sources = {stem: read(work, "md", stem + ".md") if exists(work, "md", stem + ".md") else ""
               for stem in ("deutsch", "chapitre", "espanol", "funciones", "osterreich")}
    epub = os.path.join(work, "epub", "org.example.languages.epub")
    chapters, package = {}, ""
    if os.path.exists(epub):
        with zipfile.ZipFile(epub) as z:
            for name in z.namelist():
                text = z.read(name).decode("utf-8", "replace")
                if name.endswith(".opf"):
                    package = text
                found = re.search(r'<section id="page-([^"]+)"', text)
                if "/text/ch" in name and found:
                    chapters[found.group(1)] = text
    validated = epubcheck(epub)
    drafted = []
    if exists(work, "languages-new.csv"):
        with open(os.path.join(work, "languages-new.csv"), encoding="utf-8", newline="") as fh:
            drafted = list(csv.reader(fh))
    said = first.stdout + first.stderr
    # A person adopts the drafted rows as they stand.
    with open(os.path.join(work, "languages.csv"), "a", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(drafted[1:])
    second = convert(work, project=False, fixtures=())
    again = second.stdout + second.stderr
    footer = re.compile(r'<footer lang="de"( xml:lang="de")?>\s*<p>A <em>footer</em>')

    def chapter(stem):
        return chapters.get(stem, "")
    return [
        ("the book converts", lambda: first.returncode == 0 and all(pages.values())),
        ("each page is in its language: a row's, else its file's, a Word file's text's, "
         "OpenStax's property's, or a Markdown file's lang, else the book's; a file's in "
         "another region of the book's language is the book's",
         lambda: [root_language(pages[s])[0] for s in ("deutsch", "chapitre", "espanol",
                                                        "funciones", "osterreich")]
         == ["de", "fr-CA", "es-ES", "es", "de"]),
        ("a page in another language has the book's banner and footer marked in the book's, "
         "a page in the book's language not",
         lambda: '<header lang="de">' in pages["espanol"] and footer.search(pages["espanol"])
         and "<header>" in pages["deutsch"] and "<footer>" in pages["deutsch"]),
        ("a Markdown target's file says its page's language, unless it's the book's and the "
         "source said none",
         lambda: "lang: fr-CA" in sources["chapitre"] and "lang: es-ES" in sources["espanol"]
         and "lang: es" in sources["funciones"]
         and "lang:" not in sources["deutsch"] and "lang:" not in sources["osterreich"]),
        ("a Word target's file has its page's language as its default, the book's where the "
         "page is in it, not the reference document's US English",
         lambda: 'w:val="es-ES"' in word_language(os.path.join(work, "word", "espanol.docx"))
         and 'w:val="es"' in word_language(os.path.join(work, "word", "funciones.docx"))
         and 'w:val="de"' in word_language(os.path.join(work, "word", "deutsch.docx"))
         and 'w:val="fr-CA"' in word_language(os.path.join(work, "word", "chapitre.docx"))),
        ("the EPUB is in the book's language, and each chapter file of a page in another "
         "says so on its root, a hand-written page's its own, the footer the book's",
         lambda: "<dc:language>de</dc:language>" in package
         and [root_language(chapter(s)) for s in ("deutsch", "chapitre", "espanol", "about")]
         == [("de", "de"), ("fr-CA", "fr-CA"), ("es-ES", "es-ES"), ("it", "it")]
         and footer.search(chapter("espanol")) and "<footer>" in chapter("deutsch")),
        ("and epubcheck agrees", lambda: validated == [] if validated is not None else True),
        ("an HTML page a row gives another region of the book's language is in it, and so is "
         "its copy, in place of the language it said",
         lambda: root_language(read(work, "html", "seite.html"))[0] == "de-CH"
         and '<html lang="de-CH">' in read(work, "src", "seite.html")
         and "seite" not in said.split("NOTE:", 1)[-1].split("\n", 1)[0]),
        ("a copy is given its row's language in place of its own, and OpenStax's property's "
         "in place of the US English its marks say; one in its own keeps it, and one that "
         "says none gets the book's",
         lambda: 'w:val="es"' in word_language(os.path.join(work, "src", "funciones.docx"))
         and 'w:val="en-US"' not in word_language(os.path.join(work, "src", "funciones.docx"))
         and 'w:val="es-ES"' in word_language(os.path.join(work, "src", "espanol.docx"))
         and 'w:val="de-AT"' in word_language(os.path.join(work, "src", "osterreich.docx"))
         and "lang: fr-CA" in read(work, "src", "chapitre.md")
         and "lang: fr\n" not in read(work, "src", "chapitre.md")
         and "lang: de" in read(work, "src", "deutsch.md")),
        ("the run names each page in another language and where its language came from",
         lambda: "4 page(s) are in another language than the book's, de" in said
         and "chapitre fr-CA (languages.csv)" in said and "espanol es-ES (its file)" in said
         and "funciones es (its producer's property)" in said and "about it (its file)" in said),
        ("languages-new.csv drafts a row for each one a file put there that the sidecar has "
         "none for, saying where it was found",
         lambda: drafted[0] == ["source", "language", "found", "drafted-by", "reviewed"]
         and sorted(r[:2] + r[3:] for r in drafted[1:])
         == [["about", "it", "TI", ""], ["espanol", "es-ES", "TI", ""],
             ["funciones", "es", "TI", ""]]
         and any(r[0] == "funciones" and "OpenStax" in r[2] for r in drafted)
         and any(r[0] == "about" and r[2] == "_pt/about.html: its lang" for r in drafted)),
        ("a row naming no page, and a row whose language isn't a tag, are warned about",
         lambda: "row(s) name no page of the book (nothing)" in said
         and "the row for broken gives 'French', which isn't a language tag" in said),
        ("adopted, the rows leave no draft, and are said to be drafted and not yet reviewed",
         lambda: second.returncode == 0 and not exists(work, "languages-new.csv")
         and "languages.csv 3" in again),
    ]


def case_merged_languages(work):
    """A file merge: groups makes of pages in two languages: in the book's,
    each page in another a div in its own, in a Markdown file and a Word
    file alike; and one made of pages in one other language is in it."""
    os.makedirs(work)
    for name, text in dict(LANGUAGE_PAGES, **{
            "page.md": "---\ntitle: Page\nlang: fr\n---\n\nEncore une phrase.\n"}).items():
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  identifier: org.example.merged\n  title: Gemischt\n"
                 "  language: de\n  contents:\n    - title: Gemischt\n"
                 "      items: [deutsch, chapitre]\n    - title: Ganz\n      items: [page]\n")
    result = convert(work, "targets:\n  md:\n    format: markdown\n    merge: groups\n"
                     "  word:\n    format: docx\n    merge: groups\n", project=False, fixtures=())
    mixed = read(work, "md", "Gemischt.md") if exists(work, "md", "Gemischt.md") else ""
    # A group whose pages are all one source's file is named for it.
    whole = read(work, "md", "page.md") if exists(work, "md", "page.md") else ""
    word = os.path.join(work, "word", "Gemischt.docx")
    runs = ""
    if os.path.exists(word):
        with zipfile.ZipFile(word) as z:
            runs = z.read("word/document.xml").decode("utf-8")
    return [
        ("the book merges", lambda: result.returncode == 0 and mixed and whole),
        ("a Markdown file of pages in two languages says none, the book's, and its page in "
         "another is a div in its own",
         lambda: "lang:" not in mixed.split("\n---", 1)[0]
         and re.search(r'::: \{lang="fr"\}\s*\n## Chapitre', mixed)
         and "Ein Satz" not in mixed.split('lang="fr"', 1)[1]),
        ("and a Word file's default is the book's, the page in another in its own",
         lambda: 'w:val="de"' in word_language(word)
         and re.search(r'<w:lang w:val="fr"\s*/>.*Une phrase', runs, re.S)),
        ("a file of pages in one other language is in it",
         lambda: "lang: fr" in whole and ":::" not in whole
         and 'w:val="fr"' in word_language(os.path.join(work, "word", "page.docx"))),
    ]


def case_variant_languages(work):
    """A target's variant of a page is the page, in its language; a page
    only a variant gives is in its own."""
    os.makedirs(work)
    for name, text in (("deutsch.md", LANGUAGE_PAGES["deutsch.md"]),
                       ("deutsch.print.md", "---\ntitle: Deutsch\nlang: fr\n---\n\nGedruckt.\n"),
                       ("nur.print.md", "---\ntitle: Nur\nlang: it\n---\n\nSolo stampato.\n")):
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  identifier: org.example.variants\n  title: Varianten\n"
                 "  language: de\n")
    result = convert(work, "targets:\n  html:\n    format: html\n  print:\n    format: html\n",
                     project=False, fixtures=())

    def lang(*parts):
        return root_language(read(work, *parts))[0] if exists(work, *parts) else None
    return [
        ("the book converts", lambda: result.returncode == 0),
        ("a variant of a page is the page, in the page's language",
         lambda: lang("html", "deutsch.html") == "de" and lang("print", "deutsch.html") == "de"
         and "Gedruckt" in read(work, "print", "deutsch.html")),
        ("a page only a variant gives is in its own, and the run names it",
         lambda: lang("print", "nur.html") == "it"
         and "nur it (its file)" in result.stdout + result.stderr),
    ]


def case_review_columns(work):
    """Every report a person fills in has Drafted by and Reviewed columns;
    the table-header guesses are drafted by TI; a sidecar value drafted
    and not reviewed is used, and the run counts it."""
    import struct
    import zlib

    def png(path):
        def chunk(kind, data):
            return (struct.pack(">I", len(data)) + kind + data
                    + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
        raw = b"".join(b"\x00" + b"\xff\x00\x00" * 4 for _ in range(4))
        with open(path, "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))

    os.makedirs(work)
    png(os.path.join(work, "one.png"))
    png(os.path.join(work, "two.png"))
    with open(os.path.join(work, "page.md"), "w", encoding="utf-8") as fh:
        fh.write("# Page\n\n![](one.png)\n\n![](two.png)\n\n"
                 "| Country | GDP |\n|---|---|\n| Brazil | 3,153 |\n| Canada | 1,827 |\n\n"
                 "See <https://example.org/a-page>.\n")
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  title: Review\n  identifier: org.example.review\n"
                 "  language: en-US\n  contents:\n    - page\n    - tables\n")
    # A Word file's tables, which the header pre-pass guesses at.
    shutil.copy(os.path.join(FIXTURES, "tables.docx"), work)
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  html:\n    format: html\n")

    def run():
        return subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"], cwd=work,
                              capture_output=True, text=True, stdin=subprocess.DEVNULL)

    def header(name):
        path = os.path.join(work, name)
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8", newline="") as fh:
            return next(csv.reader(fh), [])

    run()
    headers = {name: header(name) for name in ("image-alt-missing.csv", "table-captions-missing.csv",
                                               "table-headers-new.csv", "bare-links-new.csv")}
    guessed = []
    if os.path.exists(os.path.join(work, "table-headers-new.csv")):
        with open(os.path.join(work, "table-headers-new.csv"), encoding="utf-8", newline="") as fh:
            guessed = list(csv.DictReader(fh))
    missing = []
    if os.path.exists(os.path.join(work, "image-alt-missing.csv")):
        with open(os.path.join(work, "image-alt-missing.csv"), encoding="utf-8", newline="") as fh:
            missing = [r for r in csv.reader(fh)][1:]
    # One description drafted by a model and not reviewed, one reviewed.
    with open(os.path.join(work, "image-alt.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(headers.get("image-alt-missing.csv") or ["Image", "Alt"])
        for row, (alt, reviewed) in zip(missing, (("A red square", ""), ("Another red square", "RS"))):
            w.writerow([row[0], alt, row[2], row[3], row[4], "claude-sonnet-5-5", reviewed])
    second = run()
    said = second.stdout + second.stderr
    page = read(work, "html", "page.html") if exists(work, "html", "page.html") else ""
    return [
        ("each report a person fills in ends with Drafted by and Reviewed",
         lambda: all(h[-2:] == ["Drafted by", "Reviewed"] for name, h in headers.items()
                     if name != "table-headers-new.csv" and h)
         and headers["image-alt-missing.csv"] and headers["bare-links-new.csv"]
         and missing and all(len(r) == len(headers["image-alt-missing.csv"]) for r in missing)
         and headers["table-headers-new.csv"][-2:] == ["drafted-by", "reviewed"]),
        ("a table-header guess is drafted by TI and not reviewed",
         lambda: guessed and all(r["drafted-by"] == "TI" and r["reviewed"] == "" for r in guessed if r["headers"])),
        ("a drafted value is used, reviewed or not, and the run counts the one not reviewed",
         lambda: len(missing) == 2 and 'alt="A red square"' in page and 'alt="Another red square"' in page
         and "1 value(s) in the sidecars were drafted" in said and "image-alt.csv 1" in said),
    ]


QUOTED_LISTS = """# Quotes

> - opens with a list
> - second
>
> Then a paragraph.

Between.

> A paragraph, then a list that ends the quote:
>
> 1. one
> 2. two

> A different quote right after.

Between again.

> Outer paragraph.
>
> > Inner paragraph.
> >
> > - inner list
> > - inner second
> >
> > Inner after.
>
> Outer after.

A plain list, outside any quote:

- plain one
- plain two

> Quoted list with a nested list:
>
> - top
>     - nested
> - top two
>
> End.

> A loose list, whose items are paragraphs:
>
> - loose one
>
> - loose two
>
> After it.

A list outside any quote, one of whose items holds a quote:

- item one

    > A quote inside the item.
    >
    > Its second paragraph.

- item two

- An item holding a quote of a paragraph and code:

    > Load it from a file:
    >
    > ```
    > include csv
    > ```

- And one holding a quote with a quote inside it:

    > Exercise
    >
    > > Why does rec work here but not above?
    >
    > Back in the outer quote.

- And one holding a quote of code alone:

    > ```
    > include gdrive-sheets
    > ```

> A list in a quote, whose item holds code of its own, not quoted again:
>
> - an item
>
>     ```
>     acct1
>     ```
>
> - another

> A quote whose inner quote holds a list and nothing else:
>
> > - first in the inner quote
> > - second

> Code in a quote in a quote, at two depths:
>
> > Inner paragraph.
> >
> > ```
> > depth two
> > ```
> >
> > > ```
> > > depth three
> > > ```

Code with a language, alone and in a quote:

```python
x = 1
```

> ```python
> y = 2
> ```
"""


def case_quoted_lists(work):
    """Lists in quotations through the Word target and back: a quote that
    opens with a list, one that ends with one before another quote, a list
    in a quote in a quote, and a nested list. And an author's Word file,
    without the target's document variable, read as Pandoc reads it."""
    import zipfile as zf

    def book(path, files, targets):
        os.makedirs(path)
        for name, data in files.items():
            mode = "wb" if isinstance(data, bytes) else "w"
            with open(os.path.join(path, name), mode, **({} if mode == "wb" else {"encoding": "utf-8"})) as fh:
                fh.write(data)
        with open(os.path.join(path, "project.yaml"), "w", encoding="utf-8") as fh:
            fh.write("project:\n  title: Quotes\n  identifier: org.example.%s\n  language: en-US\n"
                     % os.path.basename(path))
        with open(os.path.join(path, "conversion.yaml"), "w", encoding="utf-8") as fh:
            fh.write("targets:\n" + targets)
        subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"], cwd=path,
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)

    def markdown(path, stem):
        json_path = os.path.join(path, stem + ".filtered.json")
        if not os.path.exists(json_path):
            return ""
        return subprocess.run(["pandoc", "-f", "json", json_path, "-t", "markdown"],
                              capture_output=True, text=True).stdout

    source = os.path.join(work, "source")
    # Two quotes kept apart only by the Divs they're in, which Word doesn't
    # keep: they come back two quotes, not one.
    divs = "Before.\n\n::: one\n> Quote A.\n:::\n\n::: two\n> Quote B.\n:::\n\nAfter.\n"
    book(source, {"page.md": QUOTED_LISTS, "divs.md": divs},
         "  word:\n    format: docx\n  html:\n    format: html\n")
    written = os.path.join(source, "word", "page.docx")
    data = open(written, "rb").read() if os.path.exists(written) else b""
    written_divs = os.path.join(source, "word", "divs.docx")
    back = os.path.join(work, "back")
    book(back, {"page.docx": data,
                "divs.docx": open(written_divs, "rb").read() if os.path.exists(written_divs) else b""},
         "  html:\n    format: html\n")
    divs_back = read(back, "html", "divs.html") if exists(back, "html", "divs.html") else ""
    # The same file as an author's, without the variable.
    plain = b""
    if data:
        import io
        buffer = io.BytesIO()
        with zf.ZipFile(io.BytesIO(data)) as zin, zf.ZipFile(buffer, "w", zf.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                part = zin.read(info.filename)
                if info.filename == "word/settings.xml":
                    part = re.sub(rb"<w:docVars>.*?</w:docVars>", b"", part)
                zout.writestr(info, part)
        plain = buffer.getvalue()
    author = os.path.join(work, "author")
    book(author, {"page.docx": plain}, "  html:\n    format: html\n")
    return [
        # And a list item's quote comes back one quote, not one a paragraph;
        # the code it holds comes back in it; a code block's language
        # leaves no zero-width space at its start.
        ("every list in a quotation comes back in it, at its depth, and the plain lists outside; "
         "a list item's quote comes back whole, code and all",
         lambda: data and markdown(source, "page") and markdown(back, "page") == markdown(source, "page")),
        ("two quotes that only their Divs kept apart come back two quotes",
         lambda: divs_back.count("<blockquote") == 2),
        ("an author's file, without the variable, is read as Pandoc reads it: the lists outside",
         lambda: plain and markdown(author, "page") != markdown(source, "page")
         and "> - opens with a list" not in markdown(author, "page")),
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
    # Main elements the reader keeps whole: a <main> with an id and a
    # class, as WordPress writes it, and a div with role="main", as
    # Sphinx's is. Each page has a <main> of its own; read back, a page
    # with two had its text twice.
    mains = work + "-mains"
    os.makedirs(mains)
    with open(os.path.join(mains, "press.html"), "w", encoding="utf-8") as fh:
        fh.write('<!DOCTYPE html><html lang="en"><head><title>Press</title></head><body>'
                 '<nav><a href="#main">Skip to the content</a></nav>'
                 '<main id="main" class="site-main"><h1>Press</h1><p>Said once.</p>'
                 '<p><a href="#main">Back to the top</a></p></main></body></html>\n')
    with open(os.path.join(mains, "sphinx.html"), "w", encoding="utf-8") as fh:
        fh.write('<!DOCTYPE html><html lang="en"><head><title>Sphinx</title></head><body>'
                 '<div class="document"><div class="body" role="main"><h1>Sphinx</h1>'
                 '<p>Also said once.</p></div></div><div class="sphinxsidebar">'
                 '<p>A sidebar.</p></div></body></html>\n')
    mains_run = run_in(mains, "  contents:\n    - press\n    - sphinx\n")
    mains_back = mains + "-back"
    if exists(mains, "html", "press.html"):
        shutil.copytree(os.path.join(mains, "html"), mains_back)
        run_in(mains_back, "  contents:\n    - press\n    - sphinx\n")

    def one_main(*parts):
        """The page one main landmark, its text once."""
        if not exists(*parts):
            return False
        page = read(*parts)
        return page.count("<main") == 1 and 'role="main"' not in page \
            and page.count("<p>Said once.</p>") + page.count("<p>Also said once.</p>") == 1
    # The same page with promote_h1_to_title: shorter, which takes the H1 as
    # the title when the <title> is it plus the site's name, and a format
    # source copy, which keeps the author's own <title> whatever that says.
    shorter = work + "-shorter"
    os.makedirs(shorter)
    with open(os.path.join(shorter, "web.html"), "w", encoding="utf-8") as fh:
        fh.write(WEB)
    with open(os.path.join(shorter, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("defaults:\n  promote_h1_to_title: shorter\ntargets:\n"
                 "  html:\n    format: html\n  copy:\n    format: source\n")
    run_in(shorter, "  contents:\n    - web\n")
    shorter_page = read(shorter, "html", "web.html") if exists(shorter, "html", "web.html") else ""
    copies = glob.glob(os.path.join(shorter, "copy", "**", "web.html"), recursive=True)
    shorter_copy = open(copies[0], encoding="utf-8").read() if copies else ""
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
        # The <title> is the H1 and the site's name: the H1 is the page's
        # title heading, shown once, and the declared title stands.
        ("a page's only h1, inside wrappers, is its title heading: one h1, "
         "and the <title> the site gave it stands",
         lambda: web.count("<h1") == 1 and "<title>A Web Page -- The Site</title>" in web),
        ("promote_h1_to_title: shorter drops the site's name from the title",
         lambda: shorter_page.count("<h1") == 1 and "<title>A Web Page</title>" in shorter_page),
        ("and a format source copy keeps the author's own title",
         lambda: "<title>A Web Page -- The Site</title>" in shorter_copy),
        ("a page's title loses the book's name when it repeats it after "
         "its own; another site's name, and a title that is only the "
         "book's, stay",
         lambda: "<title>Cover</title>" in read(mixed, "html", "cover.html")
         and "<title>Notes | Another Site</title>"
         in read(mixed, "html", "elsewhere.html")
         and "<title>The Fixture Book</title>"
         in read(mixed, "html", "bookname.html")),
        ("a main element the reader keeps whole, a <main> with an id and a class or a "
         "div with role=\"main\", is opened up, its id an anchor, so the page has one "
         "main landmark, its own, and the page read back has its text once",
         lambda: mains_run.returncode == 0
         and all(one_main(d, "html", n + ".html") for d in (mains, mains_back)
                 for n in ("press", "sphinx"))
         and 'id="main"' in read(mains, "html", "press.html")
         and "A sidebar." not in read(mains, "html", "sphinx.html")),
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
    """notes.numbering and notes.placement, on a chapter cut into pages.
    Notes gathered in one list are numbered across their group whatever
    notes.numbering says, so the builds that gather them say page. A
    note with code, on the chapter's second page and in the second
    chapter, takes its code's ids and CSS where it goes, which on the
    chapter's last page is beside code of the page's own, and its link to
    its page; and one ends in a numbered list."""
    import zipfile
    code = "    ```{.python .numberLines}\n    x = 1\n    ```\n"

    def build(sub, numbering, placement, title=None, footer=None):
        d = os.path.join(work, sub)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "ch1.md"), "w", encoding="utf-8") as fh:
            fh.write(NOTED.replace("[^c]: Note C.\n", "[^c]: Note C, on [this section]"
                                   "(#first-section).\n\n" + code + "\n")
                     .replace("Another.[^d]\n", "Another.[^d]\n\n```python\ny = 2\n```\n")
                     .replace("[^b]: Note B.\n", "[^b]: Note B, in steps:\n\n    1. One.\n"
                              "    2. Two.\n\n"))
        with open(os.path.join(d, "ch2.md"), "w", encoding="utf-8") as fh:
            fh.write("# Chapter Two\n\nTwo.[^e]\n\n[^e]: Note E.\n\n" + code)
        r = convert(d, "defaults:\n  pages:\n    split_level: 2\n  notes:\n"
                       f"    numbering: {numbering}\n    placement: "
                       f"{placement}\n" + (f"    title: {title}\n" if title else "")
                       + "targets:\n  html:\n    format: html\n"
                       + (f"    footer: {footer}\n" if footer else "")
                       + "  epub:\n    format: epub3\n", fixtures=())
        nav = ""
        e = os.path.join(d, "epub", "org.example.fixtures.epub")
        if os.path.exists(e):
            with zipfile.ZipFile(e) as z:
                nav = z.read("EPUB/nav.xhtml").decode("utf-8")
        return d, r, nav

    def epub_links_land(d):
        """Every #fragment link in the EPUB goes to a file with the id (the
        one it names, or its own), and every note it goes to links back to
        the reference: two chapter files may each have an fn1."""
        import posixpath
        e = os.path.join(d, "epub", "org.example.fixtures.epub")
        if not os.path.exists(e):
            return False
        with zipfile.ZipFile(e) as z:
            texts = {n: z.read(n).decode("utf-8") for n in z.namelist()
                     if n.endswith(".xhtml")}

        def resolve(name, f):
            return posixpath.normpath(posixpath.join(posixpath.dirname(name), f)) \
                if f else name
        ids = {n: set(re.findall(r'\sid="([^"]+)"', t)) for n, t in texts.items()}
        links = [(resolve(n, f), i) for n, t in texts.items()
                 for f, i in re.findall(r'href="([^"#:]*)#([^"]+)"', t)]
        refs = [(n, resolve(n, f), note, ref) for n, t in texts.items()
                for f, note, ref in re.findall(
                    r'href="([^"#:]*)#([^"]+)" class="footnote-ref" id="([^"]+)"', t)]

        def back(name, target, note, ref):
            aside = re.search(r'<(aside|li)\b[^>]*\bid="%s"[^>]*>(.*?)</\1>'
                              % re.escape(note), texts.get(target, ""), re.S)
            return aside is not None and any(
                resolve(target, f) == name
                for f in re.findall(r'href="([^"#]*)#%s"' % re.escape(ref),
                                    aside.group(2)))
        return links and refs and all(i in ids.get(t, ()) for t, i in links) \
            and all(back(*r) for r in refs)

    def code_css(*parts):
        """The CSS for highlighted code in a page's first style element,
        Pandoc's own, before the stylesheet's: where Pandoc writes it on a
        page that holds code. None if it isn't there."""
        first = re.search(r"<style>(.*?)</style>", read(*parts), re.S)
        found = first and re.search(r"/\* CSS for syntax highlighting \*/\n(.*)",
                                    first.group(1), re.S)
        return found.group(1).rstrip() if found else None

    def well_formed(*parts):
        """Every element of a page closed, in the order it was opened: a
        note moved whole, and nothing of the notes' list left in it."""
        from html.parser import HTMLParser
        void = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
                "source", "track", "wbr"}
        stack, stray = [], []

        class Nesting(HTMLParser):
            def handle_starttag(self, tag, attrs):
                if tag not in void:
                    stack.append(tag)

            def handle_startendtag(self, tag, attrs):
                pass                # <hr />, closed as it opens

            def handle_endtag(self, tag):
                if stack and stack[-1] == tag:
                    stack.pop()
                else:
                    stray.append(tag)
        Nesting().feed(read(*parts))
        return not stack and not stray

    def notes_chapter(d):
        """The EPUB's Notes chapter."""
        with zipfile.ZipFile(os.path.join(d, "epub", "org.example.fixtures.epub")) as z:
            return next((t for t in (z.read(n).decode("utf-8") for n in z.namelist()
                                     if "/text/" in n) if 'id="page-notes"' in t), "")

    def chapters(d):
        """The EPUB's chapter files' text, together."""
        with zipfile.ZipFile(os.path.join(d, "epub", "org.example.fixtures.epub")) as z:
            return "".join(z.read(n).decode("utf-8") for n in z.namelist() if "/text/ch" in n)

    def in_main(*parts):
        """The page's notes in its main landmark, the last of its content,
        with its footer, if it has one, after them."""
        main = re.search(r"<body>\s*<main>(.*)</main>\s*(<footer>.*</footer>\s*)?</body>",
                         read(*parts), re.S)
        return bool(main) and bool(re.search(r'<section id="[\w-]*footnotes" class="footnotes',
                                             main.group(1))) \
            and main.group(1).rstrip().endswith("</section>")

    def headed(text, heading):
        """Each notes section's heading, after its rule: none for a
        section without one."""
        return [h for _, h in re.findall(r'<section id="([\w-]*footnotes)"[^>]*>\s*<hr ?/>\s*'
                                         r'(?:<h2 class="footnotes-title">(.*?)</h2>)?', text)] \
            == heading

    gp, r1, _ = build("group-page", "group", "page")
    gg, r2, _ = build("page-group", "page", "group", footer="Course pages.")
    gb, r3, nav = build("page-book", "page", "book", footer="Course pages.")
    pp, r4, _ = build("page-page", "page", "page", "Anmerkungen")
    # Quotes and an @, which Markdown would read as curly quotes and a
    # citation, and the title is given as it's written.
    tb, r5, tnav = build("page-book-titled", "page", "book", "'Translator''s \"Notes\" @home'")
    return [
        ("a page's notes are headed, Pandoc's own as the notes arranged, in the word "
         "notes.title gives",
         lambda: r4.returncode == 0
         and headed(read(pp, "html", "ch1--first-section.html"), ["Anmerkungen"])
         and headed(read(gp, "html", "ch1--first-section.html"), ["Notes"])
         and headed(read(gg, "html", "ch1--second-section.html"), ["Notes"])),
        ("an EPUB chapter's own notes have none, as Pandoc wrote them or arranged, since a "
         "reading system may show a note beside its reference",
         lambda: all(chapters(d).count('epub:type="footnotes"') >= 2
                     and headed(chapters(d), [""] * chapters(d).count('epub:type="footnotes"'))
                     for d in (pp, gp))),
        ("the Notes page heads each group's notes with the group's title, in its section, "
         "and the EPUB's Notes chapter does too",
         lambda: headed(read(gb, "html", "notes.html"), ["Chapter One", "Chapter Two"])
         and headed(notes_chapter(gb), ["Chapter One", "Chapter Two"])),
        ("the Notes page is titled with notes.title as it's written, in the pages and the EPUB",
         lambda: r5.returncode == 0 and "<title>Notes</title>" in read(gb, "html", "notes.html")
         and """<title>Translator's "Notes" @home</title>""" in read(tb, "html", "notes.html")
         and """<h1 id="notes">Translator's "Notes" @home</h1>"""
         in read(tb, "html", "notes.html")
         and """>Translator's "Notes" @home<""" in html_lib.unescape(tnav)
         and ">Notes<" not in tnav),
        ("group numbering continues across a chapter's pages",
         lambda: r1.returncode == 0
         and 'id="fn3"' in read(gp, "html", "ch1--first-section.html")
         and 'id="fn4"' in read(gp, "html", "ch1--second-section.html")
         and 'id="fn1"' in read(gp, "html", "ch2.html")),
        ("with a value on each item so the browser numbers agree",
         lambda: 'value="4"' in read(gp, "html", "ch1--second-section.html")),
        ("a note that stays on its page keeps its code's ids as Pandoc wrote them",
         lambda: 'id="cb1"' in read(gp, "html", "ch1--first-section.html")),
        ("group placement gathers the notes on the chapter's last page, numbered across "
         "the chapter",
         lambda: r2.returncode == 0
         and "footnotes" not in read(gg, "html", "ch1.html")
         and re.findall(r'<li id="(fn\d+)"', read(gg, "html", "ch1--second-section.html"))
         == ["fn1", "fn2", "fn3", "fn4"]),
        ("the notes gathered on a chapter's last page or on the Notes page go in its main "
         "landmark, at the end of its content, before its footer, and a page's own notes "
         "are there too",
         lambda: in_main(gg, "html", "ch1--second-section.html")
         and in_main(gb, "html", "notes.html") and in_main(pp, "html", "ch1--first-section.html")
         and "Course pages." in read(gg, "html", "ch1--second-section.html")
         and "Course pages." in read(gb, "html", "notes.html")),
        ("a note that ends in a numbered list goes whole, its way back with it, and the "
         "page it goes to is well formed",
         lambda: read(gg, "html", "ch1--second-section.html").count('class="footnote-back"') == 4
         and well_formed(gg, "html", "ch1--second-section.html")
         and well_formed(gb, "html", "notes.html")
         and read(gb, "html", "notes.html").count('class="footnote-back"') == 5
         and re.search(r'<li>Two\.</li>\s*</ol>\s*(<p>)?<a href="ch1\.html#g1-fnref2"',
                       read(gb, "html", "notes.html"))),
        ("a note's code goes with it, its ids named for the note beside the page's own, and "
         "the page has the CSS Pandoc wrote for it on its own, once, a page left with no code "
         "none",
         lambda: 'id="fn3-cb1"' in read(gg, "html", "ch1--second-section.html")
         and 'id="cb1"' in read(gg, "html", "ch1--second-section.html")
         and 'href="#fn3-cb1-1"' in read(gg, "html", "ch1--second-section.html")
         and code_css(gg, "html", "ch1--second-section.html") is not None
         and code_css(gg, "html", "ch1--second-section.html")
         == code_css(gg, "html", "ch1--first-section.html")
         and code_css(gg, "html", "ch1.html") is None),
        ("and references cross to them, notes link back",
         lambda: 'href="ch1--second-section.html#fn1"' in read(gg, "html",
                                                                "ch1.html")
         and 'href="ch1.html#fnref1"' in read(gg, "html",
                                              "ch1--second-section.html")),
        # Both chapters have notes, so each has its heading there.
        ("book placement makes a Notes page with a heading per group, numbered per group",
         lambda: r3.returncode == 0
         and read(gb, "html", "notes.html").count('<h2 class="footnotes-title">') == 2
         and re.findall(r'<li id="(g\d+-fn\d+)"', read(gb, "html", "notes.html"))
         == ["g1-fn1", "g1-fn2", "g1-fn3", "g1-fn4", "g2-fn1"]),
        ("a note's link to an id on its page names the page where the note goes",
         lambda: 'href="ch1--first-section.html#first-section"' in read(
             gg, "html", "ch1--second-section.html")
         and 'href="ch1--first-section.html#first-section"' in read(gb, "html", "notes.html")),
        ("on it, two chapters' notes with code keep ids of their own, and the page has the "
         "code's CSS",
         lambda: all(f'id="{note}-cb1"' in read(gb, "html", "notes.html")
                     for note in ("g1-fn3", "g2-fn1"))
         and code_css(gb, "html", "notes.html") is not None
         and code_css(gb, "html", "notes.html") == code_css(gb, "html", "ch2.html")),
        ("and the EPUB gets a Notes chapter, its notes' code the same",
         lambda: ">Notes<" in nav
         and all(f'id="{note}-cb1"' in notes_chapter(gb) for note in ("g1-fn3", "g2-fn1"))
         and "/* CSS for syntax highlighting */" in notes_chapter(gb).split("</style>")[0]),
        ("a note's way back, a symbol labeled with what it does, isn't a link whose label "
         "leaves out its text",
         lambda: not any("link-label-without-text" in r.stderr for r in (r1, r2, r3))),
        ("no reference or return link is left dangling in any of them",
         lambda: not any(re.search(r"link-to-missing|duplicate-id",
                                   r.stderr) for r in (r1, r2, r3))),
        ("in the EPUBs, every note's link goes to the file its note is in",
         lambda: all(epub_links_land(d) for d in (gp, gg, gb))),
    ]


def case_notes_groups(work):
    """notes.* group a book's pages as its contents do, in the HTML pages
    and the EPUB alike: a book of a file per page, named in another order
    than its contents', its chapters in a part (type: part) with a page
    of its own, and a page the contents leave out, a group of its own
    after the rest in the pages; one file cut at its H1s, H2s, and H3s,
    each chapter's own page in its group; and chapter files cut so too.
    The HTML had taken a
    page's group to be what the split made of its source, so a file of
    its own was a group of one, a chapter's own page was apart from its
    sections, and so were a section's subsections; the EPUB a top-level
    entry, so a part was one."""
    import zipfile

    def page(title, count, level=1):
        return (f"{'#' * level} {title}\n\n"
                + "".join(f"{title}, claim {i}.[^{i}]\n\n" for i in range(1, count + 1))
                + "".join(f"[^{i}]: {title}, note {i}.\n\n" for i in range(1, count + 1)))

    def build(sub, files, settings, contents=""):
        d = os.path.join(work, sub)
        os.makedirs(d, exist_ok=True)
        for name, text in files.items():
            with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
                fh.write(text)
        with open(os.path.join(d, "project.yaml"), "w", encoding="utf-8") as fh:
            fh.write("project:\n  identifier: org.example.fixtures\n"
                     "  title: The Fixture Book\n" + contents)
        r = convert(d, "defaults:\n" + settings + "targets:\n  html:\n    format: html\n"
                       "  epub:\n    format: epub3\n", project=False, fixtures=())
        return d, r

    def outputs(d):
        """For the HTML pages and for the EPUB's chapter files: each
        page's title with its references' numbers and the ids of the notes
        it holds, and the Notes page's headings and notes."""
        with zipfile.ZipFile(os.path.join(d, "epub", "org.example.fixtures.epub")) as z:
            epub = [z.read(n).decode("utf-8") for n in sorted(z.namelist()) if "/text/ch" in n]
        html = [read(p) for p in sorted(glob.glob(os.path.join(d, "html", "*.html")))]
        found = []
        for texts in (html, epub):
            pages, notes = {}, None
            for text in texts:
                title = re.search(r"<title>([^<]*)</title>", text).group(1)
                held = re.findall(r'<(?:li|aside)\b[^>]*\bid="((?:g\d+-)?fn\d+)"', text)
                if title == "Notes" or title == "notes":
                    notes = (re.findall(r"<h2[^>]*>([^<]*)</h2>", text), held)
                    continue
                refs = re.findall(r'class="footnote-ref"[^>]*>(?:<sup>)?(\d+)', text)
                if refs or held:
                    pages[title] = (refs, held)
            found.append((pages, notes))
        return found

    files = {"preface.md": page("Preface", 1), "opening.md": page("Opening", 1),
             "zebra.md": page("Zebra", 2), "mango.md": page("Mango", 1),
             "apple.md": page("Apple", 2), "stray.md": page("Stray", 1)}
    contents = ("  contents:\n    - preface\n    - title: Part One\n      type: part\n"
                "      items:\n        - opening\n        - title: Chapter 1\n"
                "          items: [zebra, mango]\n        - title: Chapter 2\n"
                "          items: [apple]\n")
    pages_dir, r1 = build("files", files, "  notes:\n    placement: book\n", contents)
    one = page("Chapter One", 1) + page("Section A", 1, 2) + page("Section A.1", 1, 3) \
        + page("Section B", 1, 2) + page("Chapter Two", 1) + page("Section C", 1, 2)
    one_dir, r2 = build("one-file", {"book.md": one},
                        "  pages:\n    split_level: 3\n  notes:\n    placement: group\n")
    chapters_dir, r3 = build("chapter-files", {
        "ch1.md": page("Chapter One", 1) + page("Section A", 1, 2)
        + page("Section A.1", 1, 3) + page("Section B", 1, 2),
        "ch2.md": page("Chapter Two", 1) + page("Section C", 1, 2)},
        "  pages:\n    split_level: 3\n  notes:\n    numbering: group\n")
    expected_files = ({"Preface": (["1"], []), "Opening": (["1"], []),
                       "Zebra": (["1", "2"], []), "Mango": (["3"], []),
                       "Apple": (["1", "2"], [])},
                      (["Preface", "Opening", "Chapter 1", "Chapter 2"],
                       ["g1-fn1", "g2-fn1", "g3-fn1", "g3-fn2", "g3-fn3", "g4-fn1", "g4-fn2"]))
    # The page contents leave out is a page all the same, but not in the EPUB.
    expected_pages = ({**expected_files[0], "Stray": (["1"], [])},
                      (expected_files[1][0] + ["Stray"], expected_files[1][1] + ["g5-fn1"]))
    expected_one = {"Chapter One": (["1"], []), "Section A": (["2"], []),
                    "Section A.1": (["3"], []),
                    "Section B": (["4"], ["fn1", "fn2", "fn3", "fn4"]),
                    "Chapter Two": (["1"], []), "Section C": (["2"], ["fn1", "fn2"])}
    expected_chapters = {"Chapter One": (["1"], ["fn1"]), "Section A": (["2"], ["fn2"]),
                         "Section A.1": (["3"], ["fn3"]), "Section B": (["4"], ["fn4"]),
                         "Chapter Two": (["1"], ["fn1"]), "Section C": (["2"], ["fn2"])}
    return [
        ("a book of a file per page is numbered per chapter, a part's own page on its own, "
         "and its Notes page has a heading per chapter, in the contents' order, in the "
         "pages and the EPUB alike, a page the contents leave out last in the pages",
         lambda: r1.returncode == 0
         and outputs(pages_dir) == [expected_pages, expected_files]),
        ("a file cut at its H1s, H2s, and H3s gathers each chapter's notes on its last "
         "page, its own page's and its subsections' with the rest, numbered across it",
         lambda: r2.returncode == 0 and outputs(one_dir) == [(expected_one, None)] * 2),
        ("chapter files cut so number across each chapter, its sections' subsections too",
         lambda: r3.returncode == 0
         and outputs(chapters_dir) == [(expected_chapters, None)] * 2),
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
                          "  epub:\n    format: epub3\n", fixtures=())
    sample = yaml.safe_load(open(os.path.join(work, "project-sample.yaml"),
                                 encoding="utf-8"))["project"]["contents"]
    roles = {str(n.get("title", n.get("page"))): n.get("role")
             for n in sample if isinstance(n, dict)}
    types = {str(n.get("title", n.get("page"))): n.get("type")
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
        ["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"], cwd=work,
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
        ("the guess reads \\frontmatter, {.appendix}, and \\backmatter, "
         "the Glossary's back matter said by the type its title names",
         lambda: roles.get("The Book") == "front"
         and roles.get("Extra Material") == "appendix"
         and roles.get("Z1-Glossary") is None
         and types.get("Z1-Glossary") == "glossary"),
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
                           "  epub:\n    format: epub3\n", fixtures=())

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
        ["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"], cwd=second,
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
    subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"],
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


LIST_STARTS = """\
# Continued Lists

A list going on from the page before, its item repeated.

<ol type="A" start="2"><li>Pluralism<ol start="3"><li>Third question</li>\
<li>Fourth question</li></ol></li></ol>

And one whose letters go on, under a number.

<ol start="5"><li>Regulation<ol type="a" start="2"><li>Labor<ol type="i">\
<li>Hiring</li></ol></li></ol></li></ol>

<blockquote><ol><li>Quoted<ol start="3"><li>Third, quoted</li></ol></li></ol></blockquote>

A definition holds a list as an item does.

<dl><dt>Defined</dt><dd><ol start="6"><li>Sixth, defined</li></ol></dd></dl>

A list in a note.[^listed]

[^listed]: <ol><li>Noted<ol start="7"><li>Seventh, noted</li></ol></li></ol>

And one in a data table's cell, since a table of one cell is laid out, written as HTML.

<table><tr><th>Listed</th></tr><tr><td><ol><li>Celled<ol start="8"><li>Eighth, in a cell</li>\
</ol></li></ol></td></tr></table>

And lists in a quotation and a div that an item holds, which the reader reads as the item's.

<ol><li>Quoting<blockquote><ol start="9"><li>Ninth, quoted in an item</li></ol></blockquote>\
</li><li>Holding<div class="aside"><ol start="10"><li>Tenth, in an item's div</li></ol></div>\
</li></ol>

And one under a bullet.

<ul><li>Bulleted<ol start="11"><li>Eleventh, under a bullet</li></ol></li></ul>
"""

# A nested list whose first item opens with code, which the target can't
# mark in a paragraph of the item's own: the mark a paragraph before it.
# And spans an author wrote that only look like the mark, one whose start
# is no whole number and one holding words, which stay the author's.
LIST_STARTS_CODE = """\
# Code First

<ol><li>Steps<ol start="4"><li><pre><code>make all</code></pre></li>\
<li>Then the rest.</li></ol></li></ol>

1.  Odd
    1.  []{start="3.5"}A start that isn't whole
2.  Spanned
    1.  [Kept words]{start="2"} and more
"""


def case_list_starts(work):
    """A numbered list nested in a list's item and starting past its first
    number, which Pandoc's Markdown reader reads as text since 3.10.1, through
    a Markdown target and back: written from one, its start an empty span
    beside it, it gives the same HTML, and the second write is the first."""
    import filecmp
    first = os.path.join(work, "first")
    os.makedirs(first)
    with open(os.path.join(first, "lists.md"), "w", encoding="utf-8") as fh:
        fh.write(LIST_STARTS)
    result = convert(first, "targets:\n  html:\n    format: html\n"
                            "  src:\n    format: markdown\n", fixtures=())
    copies = []
    for name in ("second", "third"):
        folder = os.path.join(work, name)
        os.makedirs(folder)
        source = copies[-1] if copies else first
        if os.path.isfile(os.path.join(source, "src", "lists.md")):
            shutil.copy(os.path.join(source, "src", "lists.md"), folder)
        for config in ("project.yaml", "conversion.yaml"):
            shutil.copy(os.path.join(first, config), folder)
        run_in(folder)
        copies.append(folder)
    compare = subprocess.run(
        ["python3", os.path.join(ROOT, "util", "compare-output.py"),
         os.path.join(first, "html"), os.path.join(copies[0], "html")],
        capture_output=True, text=True)
    md = read(first, "src", "lists.md") if exists(first, "src", "lists.md") else ""
    page = read(copies[0], "html", "lists.html") if exists(copies[0], "html",
                                                              "lists.html") else ""
    coded = os.path.join(work, "coded")
    os.makedirs(coded)
    with open(os.path.join(coded, "code.md"), "w", encoding="utf-8") as fh:
        fh.write(LIST_STARTS_CODE)
    coded_run = convert(coded, "targets:\n  src:\n    format: markdown\n", fixtures=())
    coded_back = os.path.join(work, "coded-back")
    os.makedirs(coded_back)
    if exists(coded, "src", "code.md"):
        shutil.copy(os.path.join(coded, "src", "code.md"), coded_back)
    shutil.copy(os.path.join(coded, "project.yaml"), coded_back)
    with open(os.path.join(coded_back, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    run_in(coded_back)
    code_md = read(coded, "src", "code.md") if exists(coded, "src", "code.md") else ""
    code_page = read(coded_back, "html", "code.html") if exists(coded_back, "html",
                                                                  "code.html") else ""
    return [
        ("the Markdown writes a nested list that starts past one from one, its start an "
         "empty span at its first item, and a list in no item from its own start",
         lambda: result.returncode == 0 and "1.  []{start=\"3\"}Third question" in md
         and "a.  []{start=\"2\"}Labor" in md and "B.  Pluralism" in md
         and "5.  Regulation" in md and "i.  Hiring" in md),
        ("and one in a definition, one nested in a note's list or a cell's, one in a quotation "
         "or a div an item holds, and one under a bullet, as the reader reads them as an item's",
         lambda: "1.  []{start=\"6\"}Sixth, defined" in md
         and "1.  []{start=\"7\"}Seventh, noted" in md
         and "1.  []{start=\"8\"}Eighth, in a cell" in md
         and "1.  []{start=\"9\"}Ninth, quoted in an item" in md
         and "1.  []{start=\"10\"}Tenth, in an item's div" in md
         and "1.  []{start=\"11\"}Eleventh, under a bullet" in md),
        ("read back as a book, each list starts where it did, the span gone, a quoted one's "
         "too, and those in a definition, a note, a cell, and a quotation and a div in an item",
         lambda: page.count('start="3"') == 2 and 'start="2"' in page
         and all('<ol start="%d"' % n in page for n in (6, 7, 8, 9, 10, 11))
         and "<span start=" not in page),
        ("an item that opens with code has the mark as a paragraph before the code, and read "
         "back the list starts where it did, the code its first item's, the mark gone",
         lambda: re.search(r'1\.  \[\]\{start="4"\}\n\n +make all', code_md) is not None
         and re.search(r'<ol start="4"[^>]*>\s*<li>\s*<pre', code_page) is not None
         and '<span start="4"' not in code_page and "<p></p>" not in code_page),
        ("an author's span with a start that isn't a whole number, or with words in it, is "
         "no mark, and stays",
         lambda: coded_run.returncode == 0 and '<span start="3.5"></span>' in code_page
         and '<span start="2">Kept words</span>' in code_page),
        ("and the Markdown gives the same HTML",
         lambda: "Runs agree" in compare.stdout),
        ("the second write is the fixed point: the third equals it",
         lambda: filecmp.cmp(os.path.join(copies[0], "src", "lists.md"),
                             os.path.join(copies[1], "src", "lists.md"), shallow=False)
         if exists(copies[1], "src", "lists.md") else False),
    ]


# Marks that end in a line break, which Pandoc's Markdown writer closes
# after the break's backslash and its AsciiDoc writer after its " +", where
# their readers take the mark for text; and a span's, which both write so
# that their readers take it back.
MARK_BREAKS = """\
# Marks and Breaks

Before *for any\\
*after, **bold then\\
**after, ***both\\
***after, ~~struck\\
~~out, [under\\
]{.underline}lined, [small\\
]{.smallcaps}caps, and [a span\\
]{lang=fr}here.
"""


def case_mark_breaks(work):
    """A mark that ends in a line break, through a Markdown target and an
    AsciiDoc target and back: each mark closed before the break, so its
    reader takes it back, and a span's break left inside it."""
    first = os.path.join(work, "first")
    os.makedirs(first)
    with open(os.path.join(first, "marks.md"), "w", encoding="utf-8") as fh:
        fh.write(MARK_BREAKS)
    result = convert(first, "targets:\n  src:\n    format: markdown\n"
                            "  adoc:\n    format: asciidoc\n", fixtures=())
    md = read(first, "src", "marks.md") if exists(first, "src", "marks.md") else ""
    adoc = read(first, "adoc", "marks.adoc") if exists(first, "adoc", "marks.adoc") else ""
    # A span with no attributes ending a mark, as Pandoc's HTML reader reads
    # <em><span>...<br></span></em>.
    page = os.path.join(work, "page")
    os.makedirs(page)
    with open(os.path.join(page, "spans.html"), "w", encoding="utf-8") as fh:
        fh.write("<!DOCTYPE html>\n<html lang=\"en\"><head><title>Spans</title></head><body>\n"
                 "<h1>Spans</h1>\n<p>Before <em><span>for any<br></span></em>after.</p>\n"
                 "</body></html>\n")
    spans = convert(page, "targets:\n  src:\n    format: markdown\n"
                          "  adoc:\n    format: asciidoc\n", fixtures=())
    spans_md = read(page, "src", "spans.md") if exists(page, "src", "spans.md") else ""
    spans_adoc = read(page, "adoc", "spans.adoc") if exists(page, "adoc", "spans.adoc") else ""
    pages = {}
    for name, sub, written in (("from-md", "src", "marks.md"), ("from-adoc", "adoc",
                                                                "marks.adoc")):
        folder = os.path.join(work, name)
        os.makedirs(folder)
        if exists(first, sub, written):
            shutil.copy(os.path.join(first, sub, written), folder)
        shutil.copy(os.path.join(first, "project.yaml"), folder)
        with open(os.path.join(folder, "conversion.yaml"), "w") as fh:
            fh.write("targets:\n  html:\n    format: html\n")
        run_in(folder)
        pages[name] = read(folder, "html", "marks.html") if exists(folder, "html",
                                                                     "marks.html") else ""

    def marked_again(page, *marks):
        body = re.sub(r"\s+", " ", page)
        return all(re.search(r"<%s>%s</%s>(?:</\w+>)*<br ?/?> ?\w" % (tag, words, tag), body)
                   for tag, words in marks)
    return [
        ("the Markdown target closes each mark before its line break, a mark in a mark too, "
         "where Pandoc's writer closes it after the break's backslash; a span's break stays "
         "inside it, small caps' too, which it writes as a span",
         lambda: result.returncode == 0
         and all(s in md for s in ("*for any*\\\n", "**bold then**\\\n", "***both***\\\n",
                                   "~~struck~~\\\n", "[under]{.underline}\\\n"))
         and all(s in md for s in ('[small\\\n]{.smallcaps}', '[a span\\\n]{lang="fr"}'))),
        ("and one at the end of a span with no attributes that ends a mark, from an HTML page",
         lambda: spans.returncode == 0 and "Before *for any*\\\nafter." in spans_md
         and "Before _for any_ +\nafter." in spans_adoc),
        ("and the AsciiDoc target before its \" +\", where Pandoc's writer puts that inside it",
         lambda: all(s in adoc for s in ("_for any_ +\n", "*bold then* +\n",
                                         "[line-through]#struck# +\n",
                                         "[.underline]#under# +\n",
                                         "[smallcaps]#small# +\n"))),
        ("read back, each is its mark again, the line break after it, and none of their "
         "characters is text",
         lambda: marked_again(pages["from-md"], ("em", "for any"), ("strong", "bold then"),
                              ("em", "both"), ("del", "struck"), ("u", "under"))
         and marked_again(pages["from-adoc"], ("em", "for any"), ("strong", "bold then"),
                          ("em", "both"))
         and re.search(r'<span class="smallcaps">small</span><br ?/?> ?\w',
                       re.sub(r"\s+", " ", pages["from-adoc"]))
         and re.search(r'<span class="smallcaps">small<br ?/?> ?</span>\w',
                       re.sub(r"\s+", " ", pages["from-md"]))
         and not re.search(r"\*\*?for|any\*|then\*|both\*|~~|\+</|then \+", pages["from-md"]
                           + pages["from-adoc"])),
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
                           "    merge: groups\n", fixtures=())
    one = read(work, "src", "ch1.md") if exists(work, "src", "ch1.md") else ""
    two = read(work, "src", "ch2.md") if exists(work, "src", "ch2.md") else ""
    levels = [len(m.group(1)) for m in re.finditer(r"^(#+) ", one, re.M)]
    # Two groups whose pages are all one source's: neither file holds all
    # of the source's pages, so neither is named for it, and both survive.
    single = work + "-one-source"
    os.makedirs(single)
    with open(os.path.join(single, "book.md"), "w", encoding="utf-8") as fh:
        fh.write("# Book\n\nIntro.\n\n## One\n\nA.\n\n## Two\n\nB.\n")
    with open(os.path.join(single, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  identifier: org.example.halves\n  title: Halves\n"
                 "  contents:\n    - title: First Half\n      items: [book, book--one]\n"
                 "    - title: Second Half\n      items: [book--two]\n")
    convert(single, "defaults:\n  pages:\n    split_level: 2\n"
                    "targets:\n  src:\n    format: markdown\n    merge: groups\n",
            project=False, fixtures=())
    halves = {n: read(single, "src", n) for n in os.listdir(os.path.join(single, "src"))
              if n.endswith(".md")} if exists(single, "src") else {}
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
         lambda: len(halves) == 2 and "book.md" not in halves
         and any("A." in t and "B." not in t for t in halves.values())
         and any("B." in t and "A." not in t for t in halves.values())),
        ("an id two pages shared is renamed, and its page's link follows",
         lambda: one.count("#dup)") == 1 and two.count("#dup)") == 1),
    ]



def case_book_name(work):
    """Where the book is named: project.yaml for both halves, or a half's
    own project: block, files that disagree stopping the run. A target that
    writes a book takes a master's title with a warning and isn't written
    with nothing to name it; the first run writes project-sample.yaml and
    the commands for the other two samples, which --init writes keeping
    what the files set."""
    import yaml
    import zipfile

    def book(name, files):
        """A book of two pages and the files given, None leaving one out."""
        folder = os.path.join(work, name)
        os.makedirs(folder)
        pages = {"one.md": "---\ntitle: One\nlang: en\n---\n\n# One\n\nText.\n",
                 "two.md": "---\ntitle: Two\nlang: en\n---\n\n# Two\n\nMore.\n"}
        for file, text in dict(pages, **files).items():
            if text is None:
                continue
            with open(os.path.join(folder, file), "w", encoding="utf-8") as fh:
                fh.write(text)
        done = subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"],
                              cwd=folder, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL)
        return folder, done, done.stdout + done.stderr

    both = "targets:\n  html:\n    format: html\n  epub:\n    format: epub3\n"
    bare, bare_run, bare_said = book("bare", {"conversion.yaml": both})
    moved, moved_run, moved_said = book("moved", {
        "conversion.yaml": both,
        "packaging.yaml": "project:\n  identifier: org.example.moved\n"
                          "  title: The Moved Book\n"})
    adoc, adoc_run, adoc_said = book("adoc", {
        "conversion.yaml": both,
        "index.adoc": "= The Master Book\nAnn Author\n:lang: en\n\n"
                      "include::three.adoc[]\n",
        "three.adoc": "= Three\n\nText.\n"})
    alone, alone_run, alone_said = book("alone", {
        "conversion.yaml": "targets:\n  epub:\n    format: epub3\n"})
    named_conv = ("project:\n  identifier: org.example.conv\n"
                  "  title: The Conv Book\n  contents: [two, one]\n")
    conv, conv_run, conv_said = book("conv", {"conversion.yaml": named_conv + both})
    conv2, conv2_run, conv2_said = book("conv2", {
        "conversion.yaml": named_conv + both,
        "packaging.yaml": "defaults:\n  version: \"2.0\"\n"})
    agree, agree_run, agree_said = book("agree", {
        "conversion.yaml": named_conv + both,
        "packaging.yaml": "project:\n  identifier: org.example.conv\n"
                          "  title: The Conv Book\n"})
    differ, differ_run, differ_said = book("differ", {
        "conversion.yaml": named_conv + both,
        "packaging.yaml": "project:\n  identifier: org.example.conv\n"
                          "  title: Another Book\n"})
    over, over_run, over_said = book("over", {
        "conversion.yaml": both,
        "project.yaml": "project:\n  identifier: org.example.o\n  title: O\n"
                        "  language: en\n",
        "packaging.yaml": "project:\n  language: de\n"})
    untitled, untitled_run, untitled_said = book("untitled", {
        "conversion.yaml": both,
        "project.yaml": "project:\n  identifier: org.example.u\n  title: Untitled\n"})
    lone, lone_run, lone_said = book("lone", {"conversion.yaml": both, "two.md": None})
    checked = os.path.join(work, "checked")
    os.makedirs(checked)
    for file, text in {"index.adoc": "= A Checked Book\n\ninclude::b.adoc[]\n\n"
                                     "include::a.adoc[]\n",
                       "a.adoc": "= A\n\nText.\n", "b.adoc": "= B\n\nText.\n"}.items():
        with open(os.path.join(checked, file), "w", encoding="utf-8") as fh:
            fh.write(text)
    subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet", "--check-only"],
                   cwd=checked, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    title = ""
    epubs = glob.glob(os.path.join(adoc, "epub", "*.epub"))
    if epubs:
        with zipfile.ZipFile(epubs[0]) as z:
            opf = [n for n in z.namelist() if n.endswith(".opf")]
            title = z.read(opf[0]).decode("utf-8") if opf else ""
    # --init: each sample keeps what its file sets, and the project block
    # stays where it is.
    init = subprocess.run(["python3", os.path.join(BIN, "build-cartridge.py"),
                           "-d", moved, "--pages", os.path.join(moved, "html"),
                           "--init"], capture_output=True, text=True)
    with open(os.path.join(bare, "conversion.yaml"), "a", encoding="utf-8") as fh:
        fh.write("defaults:\n  footer: Our footer.\n")
    conversion_init = subprocess.run(
        ["python3", os.path.join(BIN, "read-conversion-config.py"), "-d", bare,
         "--init"], capture_output=True, text=True)
    before_init = read(bare, "project-sample.yaml") if exists(bare, "project-sample.yaml") else ""
    bare_init = subprocess.run(["python3", os.path.join(BIN, "build-cartridge.py"),
                                "-d", bare, "--pages", os.path.join(bare, "html"),
                                "--init"], capture_output=True, text=True)
    # --init with one package chosen writes its overrides in its own block,
    # and with no pages, a project block's contents as declared.
    two = os.path.join(work, "two-packages")
    os.makedirs(two)
    with open(os.path.join(two, "packaging.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  identifier: org.example.two\n  title: Two\n"
                 "  contents: [b, a]\ntargets:\n  cartridge:\n"
                 "    format: common-cartridge\n    version: \"2.5\"\n"
                 "  zipped:\n    format: zip\n")
    two_init = subprocess.run(["python3", os.path.join(BIN, "build-cartridge.py"),
                               "-d", two, "--init", "--target", "cartridge"],
                              capture_output=True, text=True)

    def sample(folder, name):
        path = os.path.join(folder, name)
        return yaml.safe_load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    return [
        ("with nothing naming the book, the EPUB isn't written, the pages are, "
         "and the run says where the title goes and ends in an error",
         lambda: bare_run.returncode != 0
         and not glob.glob(os.path.join(bare, "epub", "*.epub"))
         and exists(bare, "html", "one.html")
         and "target epub needs the book's title" in bare_said),
        ("and the first run writes project-sample.yaml, with the commands "
         "that write the other two samples",
         lambda: exists(bare, "project-sample.yaml")
         and "writes packaging-sample.yaml" in bare_said
         and "writes conversion-sample.yaml" in bare_said),
        ("a book named only in packaging.yaml gets its cartridge, with no "
         "note, and the EPUB isn't written, the run saying where conversion "
         "reads the name",
         lambda: exists(moved, "imsmanifest.xml")
         and not glob.glob(os.path.join(moved, "epub", "*.epub"))
         and "where conversion reads it too" in moved_said
         and "NOTE" not in moved_said and moved_run.returncode != 0),
        ("an AsciiDoc master's title names the EPUB, and the run says so",
         lambda: "The Master Book" in title
         and "is titled \"The Master Book\", as the master AsciiDoc file says"
         in adoc_said),
        ("and the project's sample has the master's title and author",
         lambda: sample(adoc, "project-sample.yaml").get("project", {}).get("title")
         == "The Master Book"
         and sample(adoc, "project-sample.yaml")["project"].get("authors") == ["Ann Author"]),
        ("with no html target, the run writes the project's sample itself",
         lambda: alone_run.returncode != 0 and exists(alone, "project-sample.yaml")),
        ("--init writes packaging-sample.yaml with the block packaging.yaml "
         "holds, and no project sample beside it",
         lambda: init.returncode == 0
         and sample(moved, "packaging-sample.yaml").get("project", {}).get("title")
         == "The Moved Book"),
        ("and without a block it writes none, and a project sample beside it",
         lambda: bare_init.returncode == 0
         and "project" not in sample(bare, "packaging-sample.yaml")
         and exists(bare, "project-sample.yaml")),
        ("--init keeps the project sample a run wrote",
         lambda: "Kept" in bare_init.stdout
         and read(bare, "project-sample.yaml") == before_init),
        ("--init writes a chosen package's settings in its block, not as the "
         "defaults, and declared contents with no pages as declared",
         lambda: two_init.returncode == 0
         and sample(two, "packaging-sample.yaml")["defaults"]["version"] != "2.5"
         and sample(two, "packaging-sample.yaml")["targets"]["cartridge"]["version"] == "2.5"
         and sample(two, "packaging-sample.yaml")["project"]["contents"] == ["b", "a"]),
        ("a book named in conversion.yaml's block, with no packaging.yaml, "
         "gets its EPUB, no note, and no cartridge, and that's no error",
         lambda: glob.glob(os.path.join(conv, "epub", "*.epub"))
         and conv_run.returncode == 0 and "NOTE" not in conv_said
         and "nothing is packaged" in conv_said
         and not exists(conv, "imsmanifest.xml")),
        ("with a packaging.yaml that doesn't name it, packaging stops, saying "
         "conversion.yaml names it, and the project's sample carries its values",
         lambda: conv2_run.returncode != 0
         and "names it for conversion alone" in conv2_said
         and sample(conv2, "project-sample.yaml")["project"]["title"] == "The Conv Book"
         and sample(conv2, "project-sample.yaml")["project"]["contents"] == ["two", "one"]),
        ("two blocks that agree build everything, with a note that "
         "project.yaml would say it once",
         lambda: agree_run.returncode == 0 and exists(agree, "imsmanifest.xml")
         and glob.glob(os.path.join(agree, "epub", "*.epub"))
         and "each describe the book in a project: block. They agree" in agree_said),
        ("two that disagree stop the run before anything is converted, "
         "naming both files",
         lambda: differ_run.returncode != 0 and not exists(differ, "html")
         and "'The Conv Book' in" in differ_said and "'Another Book' in" in differ_said),
        ("and so does packaging.yaml disagreeing with project.yaml, which the "
         "packager alone stops for too",
         lambda: over_run.returncode != 0 and not exists(over, "html")
         and "project.language is 'en'" in over_said
         and "project.language is 'en'" in subprocess.run(
             ["python3", os.path.join(BIN, "build-cartridge.py"), "-d", over, "--init"],
             capture_output=True, text=True).stderr),
        ("a title left at the default names nothing: the EPUB isn't written, "
         "and the run says to set it in project.yaml",
         lambda: not glob.glob(os.path.join(untitled, "epub", "*.epub"))
         and "Set title in project.yaml" in untitled_said
         and "doesn't set the book's title" in untitled_said),
        ("a book of one page is titled by it, in the EPUB and the sample",
         lambda: glob.glob(os.path.join(lone, "epub", "*.epub"))
         and "as its one page says" in lone_said
         and sample(lone, "project-sample.yaml")["project"]["title"] == "One"),
        ("a master's order is written with --check-only, which packages nothing",
         lambda: sample(checked, "project-sample.yaml").get("project", {}).get("contents")
         == ["b", "a"]),
        ("conversion's --init writes conversion-sample.yaml with the file's "
         "own values, and leaves conversion.yaml as it was",
         lambda: conversion_init.returncode == 0
         and sample(bare, "conversion-sample.yaml")["defaults"]["footer"]
         == "Our footer."
         and "epub" in sample(bare, "conversion-sample.yaml")["targets"]
         and read(bare, "conversion.yaml").endswith("footer: Our footer.\n")),
    ]

CASES = [
    ("a bare directory", case_bare),
    ("the output check, with --quick and without", case_quick),
    ("where the book is named", case_book_name),
    ("a markdown target that merges", case_merge),
    ("a Markdown target, round trip", case_markdown_target),
    ("a formula's empty row, through Markdown and AsciiDoc", case_empty_rows),
    ("a nested list that starts past one, through Markdown", case_list_starts),
    ("a mark that ends in a line break, through Markdown and AsciiDoc", case_mark_breaks),
    ("two editions from one directory", case_editions),
    ("roles, numbering, and a contents page", case_structure),
    ("footnote numbering and placement", case_notes),
    ("footnotes grouped as the contents group the pages", case_notes_groups),
    ("a Markdown source", case_markdown),
    ("an HTML source", case_html_source),
    ("an AsciiDoc source", case_asciidoc),
    ("two files, one page", case_stem_collisions),
    ("file names lowercased", case_lowercase_names),
    ("images scaled down to a set number of times the width shown", case_downsample),
    ("white space with nothing to show: an empty mark, a cell of a no-break space",
     case_white_marks),
    ("a link to a file in another case, or with backslashes", case_linked_paths),
    ("adopting a split book's pages", case_adopt),
    ("an HTML source's tables and the header sidecar", case_html_headers),
    ("layout tables, marked and decided", case_layout_tables),
    ("a Word layout table with a repeating header row", case_layout_word_head),
    ("a Word table's declaration whatever its first cell holds", case_word_table_matching),
    ("a Word box's bookmark, which a link goes to", case_word_box_anchor),
    ("a table of one cell, a layout table whatever its source", case_one_cell_tables),
    ("a menu for pages posted as a site", case_menu),
    ("the footer on every page of every format", case_page_footer),
    ("raw HTML in a Markdown source", case_markdown_html),
    ("title rows and bands, split and grouped", case_bands),
    ("a group's own header row, split", case_group_heads),
    ("a heading's id from its words gives way", case_heading_ids),
    ("headings that skip a level", case_heading_levels),
    ("a part laid out on fewer columns", case_narrow_group),
    ("a link's scheme in capitals", case_scheme_case),
    ("compare-output sees lists and blockquotes", case_compare_blocks),
    ("a web archive converted directly", case_warc_direct),
    ("a Common Cartridge", case_cartridge),
    ("a plain zip of a book's files", case_zip),
    ("formulas as MathJax 2 drew them", case_mathjax2),
    ("a formula's words", case_math_words),
    ("AsciiDoc layout attributes", case_asciidoc_layout),
    ("a pdf target without LuaLaTeX", case_pdf_without_latex),
    ("a pdf target with a LaTeX too old to tag", case_pdf_with_old_latex),
    ("a pdf target with an SVG and no rsvg-convert", case_pdf_svg_without_converter),
    ("a pdf target whose LaTeX runs out of room", case_pdf_capacity),
    ("a docx target's bookmarks", case_word_bookmarks),
    ("a page's title heading, and the title page", case_title_heading),
    ("who drafted a sidecar value, and whether it's reviewed", case_review_columns),
    ("a page's language, decided once for every target", case_page_languages),
    ("a merged file of pages in two languages", case_merged_languages),
    ("a variant's language", case_variant_languages),
    ("lists in quotations through Word", case_quoted_lists),
    ("ids with spaces in HTML sources", case_html_ids),
    ("decorative images and frame sizes in HTML sources", case_html_images),
    ("AsciiDoc to Markdown and back", case_asciidoc_markdown),
    ("an AsciiDoc target", case_asciidoc_target),
    ("a page title that is also a heading", case_title_id),
    ("link titles from every source through every target", case_link_titles),
    ("HTML table repairs", case_html_table_repairs),
    ("a table whose <thead> holds every row", case_head_only_tables),
    ("bare links and their sidecar", case_bare_links),
    ("a docx target", case_docx_target),
    ("a box in a Word file", case_word_box),
    ("pictures side by side in a figure", case_side_by_side),
    ("a worked example's steps laid out as a table, in a wide window and a phone's",
     case_formula_steps_reflow),
    ("a remediated copy of a Word file", case_remediate_docx),
    ("format: source", case_source_target),
    ("format: source repairs Word's equations", case_word_equations),
    ("format: source makes equations of math typed as text in Word", case_word_text_math),
    ("word.tracked_deletions and word.headings", case_word_repairs),
    ("format: source for Markdown", case_markdown_source),
    ("fidelity.csv for markdown and asciidoc targets", case_fidelity_writers),
    ("fidelity.csv for an EPUB target", case_fidelity_epub),
    ("a report's quotation cut between characters", case_cut_characters),
    ("highlighted code's colors in a page, an EPUB, and a Word file", case_highlighting),
    ("alt text that says nothing, in a book", case_alt_text),
    ("alt text that is a credit, or another image's, in a book", case_alt_shared),
    ("a hand-written page", case_hand_written),
    ("several targets", case_targets),
]


# The longest cases, started first when they run side by side.
SLOW = {"where the book is named", "an HTML source", "two files, one page",
        "a page's title heading, and the title page", "a Common Cartridge",
        "roles, numbering, and a contents page"}


def run_cases(cases):
    """The cases one after another, here: how many checks failed."""
    work = tempfile.mkdtemp(prefix="convert-tests-")
    failed = 0
    try:
        for label, case in cases:
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
    return failed


def main():
    parser = argparse.ArgumentParser(
        description="Check convert.py, the driver, on the fixtures.")
    parser.add_argument("--case", action="append", default=[], metavar="LABEL",
                        help="run only the case with this label, as CASES names it; "
                             "may be given again")
    parallel.add_options(parser)
    arguments = parser.parse_args()
    if shutil.which("pandoc") is None:
        sys.exit("pandoc is not on the path.")
    version = subprocess.run(["pandoc", "--version"], capture_output=True,
                             text=True).stdout.split()[1]
    if tuple(int(p) for p in re.findall(r"\d+", version)[:3]) < (3, 9):
        sys.exit(f"Pandoc {version} is too old; these tests need 3.9 or "
                 "later, as convert.py does.")
    if arguments.case_index is not None:
        # One case, for a run with them side by side: its lines, and how
        # many failed as the exit status.
        return min(run_cases([CASES[arguments.case_index]]), parallel.MOST)
    chosen = arguments.case
    cases = [c for c in CASES if not chosen or c[0] in chosen]
    if chosen and len(cases) != len(set(chosen)):
        sys.exit("no case is called " + ", ".join(
            repr(c) for c in chosen if c not in {label for label, _ in CASES}))
    if arguments.jobs > 1 and len(cases) > 1:
        failed = parallel.run(os.path.abspath(__file__), CASES, chosen,
                              arguments.jobs, first=SLOW)
    else:
        failed = run_cases(cases)
    print(f"\n{failed} check(s) failed across {len(cases)} case(s)"
          if failed else "\nall convert checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
