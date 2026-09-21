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
import shutil
import subprocess
import sys
import tempfile
import zipfile

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
    with open(os.path.join(out, "unpack-report.csv"), encoding="utf-8") as fh:
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
    stopped = subprocess.run(["python3", os.path.join(BIN, "convert.py"),
                              "--quiet"], cwd=out, capture_output=True,
                             text=True, stdin=subprocess.DEVNULL)
    gate = read(out, "media-unresolved.csv") if os.path.exists(
        os.path.join(out, "media-unresolved.csv")) else ""
    chapter = os.path.join(out, "chapter-1.html")
    with open(chapter, encoding="utf-8") as fh:
        text = fh.read()
    with open(chapter, "w", encoding="utf-8") as fh:
        fh.write(text.replace('<img src="images/file1.html" alt="Lost"/>', ""))
    result = subprocess.run(["python3", os.path.join(BIN, "convert.py"),
                             "--quiet"], cwd=out, capture_output=True,
                            text=True, stdin=subprocess.DEVNULL)
    page = read(out, "html", "chapter-1.html") if os.path.exists(
        os.path.join(out, "html", "chapter-1.html")) else ""
    # The report exists only when something was found.
    checks = []
    if os.path.exists(os.path.join(out, "output-check.csv")):
        with open(os.path.join(out, "output-check.csv"),
                  encoding="utf-8") as fh:
            checks = [r["Check"] for r in csv.DictReader(fh)]
    return [
        ("an image that is an HTML page stops the run at the media gate, "
         "named for what it is",
         lambda: stopped.returncode != 0 and "images/file1.html" in gate
         and "an HTML page where an image should be" in gate),
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
    code = page[page.index("```"):page.rindex("```")]
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
         and "$$\nE = mc^2\n$$" in page),
        ("an attribute list goes",
         lambda: "{: .blue}" not in page),
        ("code is left exactly as written",
         lambda: "`<img src=\"/logo.png\">`" in page and "`$$x$$`" in page
         and '<img src="/logo.png">' in code and "{: .kept}" in code
         and "$$kept$$" in code),
        ("root-relative paths are relative, a page's to its flat name",
         lambda: 'src="assets/a.png"' in page
         and "](index.html)" in page),
        ("the site's own 404.html isn't copied; the assets are",
         lambda: not os.path.exists(os.path.join(out, "404.html"))
         and os.path.exists(os.path.join(out, "assets", "a.png"))),
        ("an image indented in a list isn't mistaken for code",
         lambda: "indented-code-risk" not in read(out, "unpack-report.csv")),
    ]


CASES = [
    ("unpacking", case_unpack),
    ("a declared page that was split", case_split_source),
    ("converting what was unpacked", case_convert),
    ("a Jekyll site's Markdown", case_jekyll),
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
