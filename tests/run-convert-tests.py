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


WEB = """<!DOCTYPE html><html lang="en"><head><title>A Web Page</title></head>
<body><nav><ul><li><a href="other.html">Other</a></li></ul></nav>
<main><h1>A Web Page</h1>
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
    for name in ("web.html", "finished.html"):
        with open(os.path.join(mixed, name), "w", encoding="utf-8") as fh:
            fh.write(WEB)
    marked = run_in(mixed, "  contents:\n    - tables\n"
                           "    - page: web\n      convert: true\n"
                           "    - finished\n")
    web = read(mixed, "html", "web.html") if exists(
        mixed, "html", "web.html") else ""
    return [
        ("a directory of nothing but .html is read as sources, and says so",
         lambda: "as sources" in again.stdout + again.stderr
         and exists(second, "html", "tables.html")),
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
        ("a page contents marks convert: true is converted",
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
        ("an iframe is a link to what it framed, named by its title, and "
         "no raw tag is left",
         lambda: '<a href="https://example.invalid/embed/x">A video</a>'
         in re.sub(r"\s+", " ", web) and "<iframe" not in web
         and "iframe x1" in marked.stderr),
        ("a table with no th anywhere is reported, not guessed",
         lambda: "no header row and no declaration"
         in marked.stdout + marked.stderr),
        ("a page contents does not mark is copied as it stands",
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
