#!/usr/bin/env python3
"""
run-unpack-tests.py -- check unpack-epub.py and what convert.py makes of
what it writes.

    python3 tests/run-unpack-tests.py

The EPUB is built here, by hand, and is shaped like the three publishers'
EPUBs the unpacker was written against rather than like anything this
project writes: its package sits in a directory of its own with the pages
one level further down, a page refers to an image above it and to a
place inside another page, the navigation nests a chapter's sections
under it and names one place inside a page, one page is not well-formed
XML, one "image" is a web server's error page, and the spine holds a
page the navigation never names. Unpacking needs nothing but Python;
the last case converts the result and needs Pandoc.

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

import base64
import csv
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

# Pandoc 3.14 looks in the folders PANDOC_DATA_DIRS names for templates,
# init.lua, and its other data files, and --data-dir doesn't stop it. The
# suites check TextbookImprover, not what a machine has put there.
os.environ.pop("PANDOC_DATA_DIRS", None)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin")
sys.path.insert(0, os.path.join(ROOT, "lib"))

ONE_PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYGAAAAAEAAH2"
    "FzhVAAAAAElFTkSuQmCC")
XHTML = ('<?xml version="1.0" encoding="UTF-8"?>\n<html xmlns="http://www.w3.'
         'org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en">'
         '<head><title>{title}</title></head><body>{body}</body></html>')

OPF = """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="id">https://example.org/books/a-small-book</dc:identifier>
<dc:title>A "Small" Book</dc:title><dc:language>en-CA</dc:language>
<dc:creator>First Author</dc:creator><dc:creator>Second Author</dc:creator>
<dc:publisher>The Press</dc:publisher>
<meta property="dcterms:modified">2026-01-01T00:00:00Z</meta>
</metadata>
<manifest>
<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
<item id="c1" href="text/chapter%201.xhtml" media-type="application/xhtml+xml"/>
<item id="s1" href="text/section-1-1.xhtml" media-type="application/xhtml+xml"/>
<item id="cr" href="text/credits.xhtml" media-type="application/xhtml+xml"/>
<item id="im" href="images/curve.png" media-type="image/png"/>
<item id="bad" href="images/file1.html" media-type="text/html"/>
<item id="css" href="style.css" media-type="text/css"/>
</manifest>
<spine><itemref idref="nav"/><itemref idref="c1"/><itemref idref="s1"/>
<itemref idref="cr"/></spine>
</package>
"""

NAV = XHTML.format(title="Contents", body="""
<nav epub:type="toc"><ol>
<li><a href="text/chapter%201.xhtml">Chapter 1</a><ol>
  <li><a href="text/section-1-1.xhtml">Section 1.1</a><ol>
    <li><a href="text/section-1-1.xhtml#deep">A place inside</a></li></ol></li>
</ol></li>
</ol></nav>""")

PAGES = {
    "OEBPS/text/chapter 1.xhtml": XHTML.format(title="Chapter 1", body=(
        '<section><h1>Chapter 1</h1><p>See <a href="section-1-1.xhtml#deep">'
        'the deep place</a> and <a href="https://example.org/x.xhtml">out'
        '</a>.</p><p><img src="../images/curve.png" alt="A curve"/> '
        '<img src="../images/file1.html" alt="Lost"/></p></section>')),
    # Not well-formed: an unclosed <br>, as Asciidoctor wrote one.
    "OEBPS/text/section-1-1.xhtml": XHTML.format(title="Section 1.1", body=(
        '<section><h1>Section 1.1</h1><p id="deep">Deep,<br>and back to '
        '<a href="chapter%201.xhtml">the chapter</a>.</p></section>')),
    "OEBPS/text/credits.xhtml": XHTML.format(title="Credits", body=(
        "<h1>Credits</h1><p>Thanks.</p>")),
}


def build_epub(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container version="1.0" xmlns="urn:'
                   'oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
                   '<rootfile full-path="OEBPS/book.opf" media-type="applic'
                   'ation/oebps-package+xml"/></rootfiles></container>')
        z.writestr("OEBPS/book.opf", OPF)
        z.writestr("OEBPS/nav.xhtml", NAV)
        for name, text in PAGES.items():
            z.writestr(name, text)
        z.writestr("OEBPS/images/curve.png", ONE_PIXEL)
        z.writestr("OEBPS/images/file1.html",
                   "<html>\r\n<head><title>403 Forbidden</title></head>")
        z.writestr("OEBPS/style.css", "body {}\n")


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


def case_unpack(work):
    os.makedirs(work)
    epub = os.path.join(work, "small.epub")
    build_epub(epub)
    out = os.path.join(work, "small")
    result = subprocess.run(["python3", os.path.join(BIN, "unpack-epub.py"),
                             epub, "-o", out], capture_output=True, text=True)
    again = subprocess.run(["python3", os.path.join(BIN, "unpack-epub.py"),
                            epub, "-o", out], capture_output=True, text=True)
    import yaml
    project = yaml.safe_load(read(out, "project.yaml"))["project"]
    chapter = read(out, "chapter-1.html")
    with open(os.path.join(out, "unpack-report.csv"), encoding="utf-8-sig") as fh:
        report = {(r["Where"], r["Check"]) for r in csv.DictReader(fh)}
    return [
        ("the run succeeds, a page per content document, the navigation "
         "document not among them",
         lambda: result.returncode == 0
         and sorted(n for n in os.listdir(out) if n.endswith(".html"))
         == ["chapter-1.html", "credits.html", "section-1-1.html"]),
        ("a page's name needs no encoding in a link",
         lambda: os.path.exists(os.path.join(out, "chapter-1.html"))),
        ("a link to another page of the book is a link to that page, its "
         "fragment kept",
         lambda: 'href="section-1-1.html#deep"' in chapter
         and 'href="chapter-1.html"' in read(out, "section-1-1.html")),
        ("a link out of the book is left alone",
         lambda: 'href="https://example.org/x.xhtml"' in chapter),
        ("an image is where it was beside the package, and the page says so",
         lambda: 'src="images/curve.png"' in chapter
         and os.path.exists(os.path.join(out, "images", "curve.png"))),
        ("a page that is not well-formed XML is unpacked all the same, "
         "unchanged but for its references",
         lambda: "Deep,<br>and back" in read(out, "section-1-1.html")),
        ("the package's metadata is the project's, the identifier made an "
         "XML name",
         lambda: project["title"] == 'A "Small" Book'
         and project["language"] == "en-CA"
         and project["authors"] == ["First Author", "Second Author"]
         and project["identifier"] == "example.org-books-a-small-book"
         and project["publisher"] == "The Press"),
        ("the navigation is the contents: a chapter's page opens its group",
         lambda: project["contents"][0]["title"] == "Chapter 1"
         and [i["page"] for i in project["contents"][0]["items"]]
         == ["chapter-1", "section-1-1"]),
        ("no group around the whole book, and no marks to say the pages "
         "are sources",
         lambda: project["contents"][0]["title"] == "Chapter 1"
         and "convert" not in read(out, "project.yaml")),
        ("a spine page the navigation never names is listed last and "
         "reported",
         lambda: project["contents"][-1]["page"] == "credits"
         and ("credits.html", "not-in-navigation") in report),
        ("an image that is an error page is reported as what it is",
         lambda: ("images/file1.html", "image-is-not-an-image") in report),
        ("a navigation entry inside a page is reported, not made a page",
         lambda: ("navigation", "entries-inside-pages") in report),
        ("a directory that already holds a book is refused",
         lambda: again.returncode != 0 and "not empty" in again.stderr),
    ]


def case_convert(work):
    """What convert.py makes of it, with the pages cut at their headings."""
    if shutil.which("pandoc") is None:
        print("  skip  pandoc not found")
        return []
    version = subprocess.run(["pandoc", "--version"], capture_output=True,
                             text=True).stdout.split()[1]
    if tuple(int(p) for p in re.findall(r"\d+", version)[:3]) < (3, 9):
        print(f"  skip  Pandoc {version} is too old; convert.py needs 3.9 or later")
        return []
    os.makedirs(work)
    epub = os.path.join(work, "small.epub")
    build_epub(epub)
    out = os.path.join(work, "small")
    subprocess.run(["python3", os.path.join(BIN, "unpack-epub.py"), epub,
                    "-o", out], capture_output=True, text=True)
    with open(os.path.join(out, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n  epub:\n"
                 "    format: epub3\n")
    # As unpacked, a page shows an error page as an image: the gate's.
    stopped = subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick",
                              "--quiet"], cwd=out, capture_output=True,
                             text=True, stdin=subprocess.DEVNULL)
    gate = read(out, "media-unresolved.csv") if os.path.exists(
        os.path.join(out, "media-unresolved.csv")) else ""
    chapter = os.path.join(out, "chapter-1.html")
    with open(chapter, encoding="utf-8") as fh:
        text = fh.read()
    with open(chapter, "w", encoding="utf-8") as fh:
        fh.write(text.replace('<img src="images/file1.html" alt="Lost"/>', ""))
    result = subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick",
                             "--quiet"], cwd=out, capture_output=True,
                            text=True, stdin=subprocess.DEVNULL)
    page = read(out, "html", "chapter-1.html") if os.path.exists(
        os.path.join(out, "html", "chapter-1.html")) else ""
    # The report exists only when something was found.
    checks = []
    if os.path.exists(os.path.join(out, "output-check.csv")):
        with open(os.path.join(out, "output-check.csv"),
                  encoding="utf-8-sig") as fh:
            checks = [r["Check"] for r in csv.DictReader(fh)]
    return [
        ("an image that is an HTML page stops the run at the media gate, "
         "named for what it is",
         lambda: stopped.returncode != 0 and "images/file1.html" in gate
         and "an HTML page where an image should be" in gate),
        ("its report starts with a byte-order mark, for Excel",
         lambda: gate.startswith("\ufeffFile,")),
        ("the unpacked book converts, pages and an EPUB",
         lambda: result.returncode == 0 and page
         and os.path.exists(os.path.join(
             out, "epub", "example.org-books-a-small-book.epub"))),
        ("the page's title is its own, and its heading is not doubled",
         lambda: "<title>Chapter 1</title>" in page
         and page.count("<h1") == 1),
        ("a link between two files of the EPUB is a link between two pages, "
         "and lands",
         lambda: 'href="section-1-1.html#deep"' in page
         and "link-to-missing-file" not in checks
         and "link-to-missing-fragment" not in checks),
        ("a link to a paragraph's id lands: the id is on an anchor the "
         "reader keeps",
         lambda: '<span id="deep"></span>' in read(out, "html",
                                                    "section-1-1.html")),
        ("the image went with the page",
         lambda: os.path.exists(os.path.join(out, "html", "images",
                                             "curve.png"))),
    ]


def case_split_source(work):
    """A declared page that the split cut stands for its pieces."""
    from bookcontents import expand_split_sources
    stems = ["book", "book--one", "book--two", "toc"]
    parts = {"book": ("book", 1, [], ""), "book--one": ("book", 2, [], ""),
             "book--two": ("book", 3, [], "")}
    declared = [{"page": "book", "title": "The Book", "convert": True}, "toc"]
    tree = expand_split_sources(declared, stems, {"book": "The Book"}, parts)
    arranged = [{"title": "Mine", "items": ["book--two", "book--one"]}]
    return [
        ("the entry becomes a group of the source's pieces, in reading "
         "order, its opening page first",
         lambda: tree[0]["items"] == ["book", "book--one", "book--two"]
         and tree[0]["title"] == "The Book" and tree[1] == "toc"),
        ("contents that already names the pieces is left as declared",
         lambda: expand_split_sources(arranged, stems, {}, parts)
         is arranged),
        ("and so is a book with nothing split",
         lambda: expand_split_sources(declared, ["book", "toc"], {}, {})
         is declared),
    ]


JEKYLL = {
    "_config.yml": "title: The Site Book\nlang: en-GB\n",
    "index.md": "---\ntitle: Home\nnav_order: 0\n---\n\n# Home\n\nWelcome.\n",
    "sec/index.md": "---\ntitle: Section\nnav_order: 1\nhas_children: true\n---",
    "sec/page.md": """---
title: A Page
parent: Section
nav_order: 1
---

# A Page

Space is $$3.4 \\times 10^{38}$$ addresses.
{: .blue}

{: .note}
> A quote kramdown styles.
>
> Its second paragraph.

$$
E = mc^2
$$

Write `<img src="/logo.png">` or `$$x$$` in code.

```
<img src="/logo.png">
{: .kept}
$$kept$$
```

1. A step:

    <img width="800px" src="/assets/a.png">

See [the home page](/index.html).

An indented code block:

    $$code$$ and src="/y" and {: .z}
""",
    "404.html": "---\nlayout: default\n---\nNot found\n",
    "assets/a.png": ONE_PIXEL,
    "README.md": "# Repository readme\n",
}


def case_jekyll(work):
    """A Jekyll site's Markdown, flattened into a book's sources."""
    src = os.path.join(work, "site")
    for name, text in JEKYLL.items():
        path = os.path.join(src, *name.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb" if isinstance(text, bytes) else "w") as fh:
            fh.write(text)
    out = os.path.join(work, "book")
    result = subprocess.run(["python3", os.path.join(BIN, "unpack-jekyll.py"),
                             src, "-o", out], capture_output=True, text=True)
    import yaml
    project = yaml.safe_load(read(out, "project.yaml"))["project"]
    page = read(out, "sec-page.md")
    report = read(out, "unpack-report.csv")
    return [
        ("a page per .md with front matter, named from its path; a readme "
         "isn't one",
         lambda: result.returncode == 0 and sorted(
             n for n in os.listdir(out) if n.endswith(".md"))
         == ["index.md", "sec-index.md", "sec-page.md"]),
        ("a section whose page is only front matter is a group, ordered "
         "by nav_order",
         lambda: project["contents"][0]["page"] == "index"
         and project["contents"][1]["title"] == "Section"
         and [i["page"] for i in project["contents"][1]["items"]]
         == ["sec-index", "sec-page"]),
        ("the site's title and language are the book's",
         lambda: project["title"] == "The Site Book"
         and project["language"] == "en-GB"),
        ("inline $$..$$ is $..$, display math stays display",
         lambda: "$3.4 \\times 10^{38}$ addresses" in page
         and re.search(r"(?:^|\n\n)\$\$\s*E = mc\^2\s*\$\$(?:\n\n|$)", page)),
        ("an attribute list goes",
         lambda: "{: .blue}" not in page),
        ("code is left exactly as written",
         lambda: "`<img src=\"/logo.png\">`" in page and "`$$x$$`" in page
         and '    <img src="/logo.png">' in page and "    {: .kept}" in page
         and "    $$kept$$" in page),
        ("an indented code block is left exactly as written",
         lambda: '    $$code$$ and src="/y" and {: .z}' in page),
        ("root-relative paths are relative, a page's to its flat name",
         lambda: 'src="assets/a.png"' in page
         and "](index.html)" in page),
        ("the site's own 404.html isn't copied; the assets are",
         lambda: not os.path.exists(os.path.join(out, "404.html"))
         and os.path.exists(os.path.join(out, "assets", "a.png"))),
        ("the report counts what was changed",
         lambda: "2 root-relative path(s)" in report
         and "1 kramdown inline formula(s)" in report
         and "2 kramdown attribute list(s)" in report),
        ("an attribute list above a blockquote leaves the quote a quote",
         lambda: "> A quote kramdown styles." in page
         and "> Its second paragraph." in page and "\\>" not in page),
    ]


SMALL_CARTRIDGE = """<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="m" xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1">
<metadata><schema>IMS Common Cartridge</schema><schemaversion>1.1.0</schemaversion>
<lom xmlns="http://ltsc.ieee.org/xsd/imsccv1p1/LOM/manifest"><general><title>
<string language="en-US">A Course</string></title></general></lom></metadata>
<organizations><organization identifier="o" structure="rooted-hierarchy"><item identifier="root">
<item identifier="i1" identifierref="ra"><title>Page A</title></item>
</item></organization></organizations>
<resources>
<resource identifier="ra" type="webcontent" href="a.html"><file href="a.html"/></resource>
</resources></manifest>"""


def tool(name, *arguments):
    return subprocess.run(["python3", os.path.join(BIN, name), *arguments],
                          capture_output=True, text=True, stdin=subprocess.DEVNULL)


def listing(folder):
    found = []
    for directory, _dirs, files in os.walk(folder):
        found += [os.path.relpath(os.path.join(directory, n), folder).replace(os.sep, "/")
                  for n in files]
    return sorted(found)


def case_part(work):
    """An unpacker given --part writes a project laid out with src/: the
    sources in the part's folder, the report under output/, the file it
    unpacked in upstream/ and named as the part's from, and nothing of a
    project that is there already replaced."""
    import yaml
    import zipfile
    os.makedirs(work)
    epub = os.path.join(work, "small.epub")
    build_epub(epub)
    proj = os.path.join(work, "proj")
    first = tool("unpack-epub.py", epub, "-o", proj, "--part", "book")
    laid = listing(proj)
    project_text = read(proj, "project.yaml")
    project = yaml.safe_load(project_text)["project"]
    again = tool("unpack-epub.py", epub, "-o", proj, "--part", "book")
    after_again = listing(proj)
    # A sidecar there already, and a second part: nothing of the first's
    # is touched, and project.yaml is the person's by now.
    second = tool("unpack-epub.py", epub, "-o", proj, "--part", "teacher")
    kept_project = read(proj, "project.yaml") == project_text
    sample = os.path.join(proj, "output", "reports", "teacher", "project-sample.yaml")
    sampled = yaml.safe_load(read(sample))["project"] if os.path.exists(sample) else {}
    # A file in the project's upstream/ already is named, not copied.
    inside = os.path.join(work, "inside")
    os.makedirs(os.path.join(inside, "upstream", "from-the-press"))
    held = os.path.join(inside, "upstream", "from-the-press", "small.epub")
    shutil.copyfile(epub, held)
    from_inside = tool("unpack-epub.py", held, "-o", inside, "--part", "book")
    inside_from = yaml.safe_load(read(inside, "project.yaml"))["project"]["parts"]["book"]["from"]
    # Another file of the upstream file's name is never replaced.
    other = os.path.join(work, "other")
    os.makedirs(os.path.join(other, "upstream"))
    with open(os.path.join(other, "upstream", "small.epub"), "w") as fh:
        fh.write("another file")
    clash = tool("unpack-epub.py", epub, "-o", other, "--part", "book")
    # Folders that can't take a part.
    flat = os.path.join(work, "flat")
    os.makedirs(flat)
    with open(os.path.join(flat, "chapter.md"), "w") as fh:
        fh.write("# A chapter\n")
    in_flat = tool("unpack-epub.py", epub, "-o", flat, "--part", "book")
    unmarked = os.path.join(work, "unmarked")
    os.makedirs(os.path.join(unmarked, "output"))
    with open(os.path.join(unmarked, "output", "mine.txt"), "w") as fh:
        fh.write("a person's file\n")
    in_unmarked = tool("unpack-epub.py", epub, "-o", unmarked, "--part", "book")
    linked = os.path.join(work, "linked")
    elsewhere = os.path.join(work, "elsewhere")
    os.makedirs(os.path.join(linked, "src"))
    os.makedirs(elsewhere)
    os.symlink(elsewhere, os.path.join(linked, "src", "book"))
    in_linked = tool("unpack-epub.py", epub, "-o", linked, "--part", "book")
    bad_name = tool("unpack-epub.py", epub, "-o", os.path.join(work, "named"),
                    "--part", "../up")
    # A cartridge, with an option that changes what's written.
    course = os.path.join(work, "course.imscc")
    with zipfile.ZipFile(course, "w") as z:
        z.writestr("imsmanifest.xml", SMALL_CARTRIDGE)
        z.writestr("a.html", "<html><head><title>Page A</title></head>"
                             "<body><p>A page.</p></body></html>")
    lms = os.path.join(work, "lms")
    cartridge = tool("unpack-cartridge.py", course, "-o", lms, "--part", "book",
                     "--linked-documents")
    lms_from = yaml.safe_load(read(lms, "project.yaml"))["project"]["parts"]["book"]["from"]
    # The settings the unpacker wrote, and the part's sources where it
    # put them, pass the run's own check.
    lms_checked = tool("convert.py", "-d", lms, "--check-only")
    # A Jekyll site is a folder: it's copied in whole, but for Git's own
    # folder and a link, and one of its name already there is left alone.
    site = os.path.join(work, "site")
    for name, text in JEKYLL.items():
        path = os.path.join(site, *name.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb" if isinstance(text, bytes) else "w") as fh:
            fh.write(text)
    os.makedirs(os.path.join(site, ".git"))
    with open(os.path.join(site, ".git", "config"), "w") as fh:
        fh.write("[remote]\n\turl = https://token@example.org/site.git\n")
    os.symlink(epub, os.path.join(site, "linked.epub"))
    pages = os.path.join(work, "pages")
    jekyll = tool("unpack-jekyll.py", site, "-o", pages, "--part", "book")
    jekyll_project = yaml.safe_load(read(pages, "project.yaml"))["project"]
    site_files = [n for n in listing(site) if not n.startswith(".git/") and n != "linked.epub"]
    pages_then = listing(pages)
    jekyll_again = tool("unpack-jekyll.py", site, "-o", pages, "--part", "second")
    from_copy = tool("unpack-jekyll.py", os.path.join(pages, "upstream", "site"),
                     "-o", pages, "--part", "second")
    around = tool("unpack-jekyll.py", work, "-o", os.path.join(work, "within"), "--part", "book")
    return [
        ("with --part the sources are the part's, the report is under output/, and "
         "the project's own files are at its top",
         lambda: first.returncode == 0
         and {"src/book/chapter-1.html", "src/book/images/curve.png", "project.yaml",
              "output/reports/book/unpack-report.csv", "output/.textbookimprover",
              "upstream/small.epub"} <= set(laid)
         and not [n for n in laid if n.endswith(".html") and "/" not in n]),
        ("the file unpacked is copied to upstream/ and named as the part's from, with "
         "its unpacker",
         lambda: open(os.path.join(proj, "upstream", "small.epub"), "rb").read()
         == open(epub, "rb").read()
         and project["parts"] == {"book": {"kind": "book", "from": {
             "file": "upstream/small.epub", "unpacker": "epub"}}}
         and project["contents"][0]["title"] == "Chapter 1"),
        ("a part that holds sources already is refused, and nothing is written",
         lambda: again.returncode != 0 and "not empty" in again.stderr
         and "Nothing was unpacked" in again.stderr and after_again == laid),
        ("a second part is unpacked beside the first; project.yaml is left as it is, "
         "what would have been written is a sample, and the lines to add are said",
         lambda: second.returncode == 0 and kept_project
         and os.path.exists(os.path.join(proj, "src", "teacher", "chapter-1.html"))
         and sampled.get("parts", {}).get("teacher", {}).get("from", {}).get("file")
         == "upstream/small.epub"
         and "left as it is" in second.stdout and "    teacher:" in second.stdout),
        ("the project written passes the run's own check, its settings and its "
         "sources read",
         lambda: lms_checked.returncode == 0),
        ("a file already in the project's upstream/ is named where it is, not copied",
         lambda: from_inside.returncode == 0
         and inside_from["file"] == "upstream/from-the-press/small.epub"
         and "copied" not in from_inside.stdout
         and not os.path.exists(os.path.join(inside, "upstream", "small.epub"))),
        ("another file of that name in upstream/ is never replaced: the unpacking "
         "stops before it writes",
         lambda: clash.returncode != 0 and "never replaced" in clash.stderr
         and read(other, "upstream", "small.epub") == "another file"
         and not os.path.exists(os.path.join(other, "src"))),
        ("a folder that holds a book's sources at its top is refused",
         lambda: in_flat.returncode != 0 and "util/move-to-src.py" in in_flat.stderr
         and sorted(os.listdir(flat)) == ["chapter.md"]),
        ("an output/ that a run didn't make is refused, and the part's folder isn't left",
         lambda: in_unmarked.returncode != 0 and "wasn't made by a run" in in_unmarked.stderr
         and not os.path.exists(os.path.join(unmarked, "src", "book"))
         and listing(unmarked) == ["output/mine.txt"]),
        ("a part's folder that is a link is refused, and nothing is written through it",
         lambda: in_linked.returncode != 0 and "is a link" in in_linked.stderr
         and os.listdir(elsewhere) == []),
        ("a part's name that isn't one is refused",
         lambda: bad_name.returncode != 0 and "part's name" in bad_name.stderr
         and not os.path.exists(os.path.join(work, "named"))),
        ("a cartridge's from carries the option that changes what's written",
         lambda: cartridge.returncode == 0
         and lms_from == {"file": "upstream/course.imscc", "unpacker": "cartridge",
                          "options": ["--linked-documents"]}
         and os.path.exists(os.path.join(lms, "src", "book", "a.html"))),
        ("a folder unpacked from outside the project is copied to upstream/ and named as "
         "the part's from, without Git's folder or a link, and the unpacker says what it "
         "left out",
         lambda: jekyll.returncode == 0
         and jekyll_project["parts"] == {"book": {"kind": "book", "from": {
             "file": "upstream/site", "unpacker": "jekyll"}}}
         and listing(os.path.join(pages, "upstream", "site")) == site_files
         and ".git/" in jekyll.stdout and "1 link(s)" in jekyll.stdout
         and os.path.exists(os.path.join(pages, "src", "book", "sec-page.md"))),
        ("a folder of that name in upstream/ already is never added to: the unpacking "
         "stops before it writes, and from the copy itself it goes on",
         lambda: jekyll_again.returncode != 0 and "never replaced" in jekyll_again.stderr
         and from_copy.returncode == 0
         and set(pages_then) < set(listing(pages))
         and os.path.exists(os.path.join(pages, "src", "second", "sec-page.md"))),
        ("a folder that holds the project's own can't be copied into it",
         lambda: around.returncode != 0 and "holds the project's folder" in around.stderr
         and not os.path.exists(os.path.join(work, "within"))),
    ]


CASES = [
    ("unpacking", case_unpack),
    ("a declared page that was split", case_split_source),
    ("converting what was unpacked", case_convert),
    ("a Jekyll site's Markdown", case_jekyll),
    ("an unpacker writing a part of a project", case_part),
]


def main():
    work = tempfile.mkdtemp(prefix="unpack-tests-")
    failed = 0
    try:
        for label, case in CASES:
            print(f"\n{label}")
            try:
                checks = case(os.path.join(work, label.replace(" ", "-")))
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
    print(f"\n{failed} check(s) failed" if failed
          else "\nall unpack checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
