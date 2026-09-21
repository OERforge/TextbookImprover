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
        "index.adoc": "= The Book\n:imagesdir: images\n:toc: left\n\n"
                      "include::one.adoc[]\n\ninclude::two.adoc[]\n",
        "one.adoc": "= Chapter One\n\n== Keys\n\nSee <<Locks>> and "
                    "<<Chapter Two>>.\n\nimage::lock.png[A lock]\n",
        "two.adoc": "= Chapter Two\n\n[[locks-id]]\n== Locks\n\nBack to "
                    "<<Keys>>.\n",
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
         == ["guess", "guess", "source"]),
        ("every HTML table is in the new-rows file, keyed",
         lambda: len(new_rows.splitlines()) == 4),
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
    chapter = ""
    for name in (os.listdir(os.path.join(work, "epub"))
                 if exists(work, "epub") else []):
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
        ("code is left exactly as written",
         lambda: "<code>&lt;p align=&quot;center&quot;&gt;</code>" in page
         or '<code>&lt;p align="center"&gt;</code>' in page),
        ("and so is a code block",
         lambda: '&lt;img src=&quot;/logo.png&quot; align=&quot;left&quot;&gt;'
         in page or '&lt;img src="/logo.png" align="left"&gt;' in page),
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
    with open(os.path.join(mixed, "conversion.yaml"), "w",
              encoding="utf-8") as fh:
        fh.write("targets:\n  html:\n    format: html\n"
                 "  epub:\n    format: epub3\n")
    marked = run_in(mixed, "  contents:\n    - tables\n    - web\n"
                           "    - finished\n")
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
         lambda: "needs-word" in read(mixed, "table-headers-report.csv")
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
