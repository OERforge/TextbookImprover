#!/usr/bin/env python3
"""
run-epub-tests.py -- check build-epub.py against the fixture documents.

    python3 tests/run-epub-tests.py           # run every case
    python3 tests/run-epub-tests.py --keep    # leave the output in place

Needs Pandoc 3.9 or later, as convert.py does. The fixtures are converted
to filtered intermediates the way convert.py does it, then assembled.

WHAT IS LOAD-BEARING HERE

The assembler's job is to put pages in the order the contents tree gives,
at the depth it gives, without losing what the filter did to them. Each
of those is a separate check: the nav mirrors the tree; each page is its
own file with its heading as its title; a row header declared through
the sidecar is still a <th scope="row"> in the book; two pages that use
the same id keep their links straight.

The package document's accessibility claims are checked in both
directions. An image without alternative text has to withhold
alternativeText; supplying the text through the sidecar has to restore
it. Pandoc's own default asserts it either way, which is the reason the
assembler computes it.

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
import copy
import importlib.util
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
NEEDED = ["metadata", "tables", "tables-b", "media-a", "math"]
sys.path.insert(0, HERE)
import parallel  # noqa: E402


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


epub = load(os.path.join(BIN, "build-epub.py"), "build_epub")


# --------------------------------------------------------------------------
# building
# --------------------------------------------------------------------------

def run(arguments, cwd, environment=None):
    result = subprocess.run(arguments, cwd=cwd, env=environment,
                            capture_output=True, text=True,
                            stdin=subprocess.DEVNULL)
    if result.returncode:
        raise RuntimeError(f"{' '.join(arguments[:3])} failed:\n"
                           f"{result.stderr}")
    return result


def convert(work, names, sidecars=None):
    """The fixtures as convert.py leaves them: raw and filtered JSON."""
    os.makedirs(work, exist_ok=True)
    environment = dict(os.environ)
    environment.update({
        "TABLE_CAPTIONS": os.path.join(work, "table-captions.csv"),
        "IMAGE_ALT": os.path.join(work, "image-alt.csv"),
        "TABLE_HEADERS": os.path.join(work, "table-headers.csv"),
        "IMAGE_ALT_MISSING": os.path.join(work, "alt-missing.csv"),
        "TABLE_CAPTIONS_MISSING": os.path.join(work, "caps-missing.csv"),
        "SPACER_LOG": os.path.join(work, "spacers.csv"),
        "PROMOTE_H1_TO_TITLE": "always",
        "AUTHOR_BYLINE": "meta",
    })
    for name, content in (sidecars or {}).items():
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(content)
    for name in names:
        shutil.copy(os.path.join(FIXTURES, name + ".docx"), work)
    docx = [n + ".docx" for n in names]
    # The pre-pass, so declared headers reach the filter as they do in a
    # real run. Its guesses are adopted wholesale, which is what makes
    # the first-column declaration on tables.docx produce row headers.
    new = os.path.join(work, "new.csv")
    run(["python3", os.path.join(BIN, "table-headers.py")] + docx
        + ["--sidecar", os.path.join(work, "table-headers.csv"),
           "--new", new, "--report", os.path.join(work, "report.csv"),
           "--resolved", os.path.join(work, "resolved.json")], work)
    if os.path.exists(new):
        shutil.copy(new, os.path.join(work, "table-headers.csv"))
        run(["python3", os.path.join(BIN, "table-headers.py")] + docx
            + ["--sidecar", os.path.join(work, "table-headers.csv"),
               "--new", new, "--report", os.path.join(work, "report.csv"),
               "--resolved", os.path.join(work, "resolved.json")], work)
    environment["TABLE_HEADERS_RESOLVED"] = os.path.join(work, "resolved.json")
    for name in names:
        run(["pandoc", "-f", "docx", "-t", "json", name + ".docx",
             "-o", name + ".json",
             "--lua-filter", os.path.join(BIN, "media-extensions.lua"),
             "--extract-media", name], work, environment)
        run(["pandoc", "-f", "json", "-t", "json", name + ".json",
             "-o", name + ".filtered.json",
             "--lua-filter", os.path.join(BIN, "figures-and-tables.lua")],
            work, environment)


def write_config(work, contents, extra_project="", extra_epub=""):
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  identifier: org.example.fixtures\n"
                 "  title: The Fixture Book\n  language: en\n"
                 + extra_project + "  contents:\n" + contents)
    with open(os.path.join(work, "conversion.yaml"), "w",
              encoding="utf-8") as fh:
        fh.write("targets:\n  html:\n    format: html\n    output_dir: .\n"
                 "  epub:\n    format: epub3\n" + extra_epub)


class Built:
    """An EPUB and the parts of it the checks look at."""

    def __init__(self, work, arguments=()):
        result = subprocess.run(
            ["python3", os.path.join(BIN, "build-epub.py"), "-d", work]
            + list(arguments), capture_output=True, text=True)
        self.status = result.returncode
        self.stderr = result.stderr
        self.files = {}
        path = os.path.join(work, "epub", "org.example.fixtures.epub")
        if os.path.exists(path):
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    if name.endswith((".opf", ".xhtml", ".css")):
                        self.files[name] = archive.read(name).decode("utf-8")

    @property
    def opf(self):
        return self.files.get("EPUB/content.opf", "")

    @property
    def nav(self):
        nav = self.files.get("EPUB/nav.xhtml", "")
        m = re.search(r'<nav epub:type="toc".*?</nav>', nav, re.S)
        return m.group(0) if m else ""

    def nav_entries(self):
        """(depth, text) for each entry, depth counted from the nesting
        of <ol> around it."""
        out, depth = [], 0
        for token in re.findall(r"<ol[^>]*>|</ol>|<a [^>]*>([^<]*)</a>",
                                self.nav):
            if token == "":
                continue
            out.append(token)
        entries, depth = [], 0
        for m in re.finditer(r"(<ol[^>]*>)|(</ol>)|<a [^>]*>(.*?)</a>",
                             self.nav, re.S):
            if m.group(1):
                depth += 1
            elif m.group(2):
                depth -= 1
            else:
                entries.append((depth, re.sub(r"<[^>]+>", "", m.group(3))))
        return entries

    def chapters(self):
        return sorted(n for n in self.files if "/text/ch" in n)

    def titles(self):
        return [re.search(r"<title>([^<]*)</title>", self.files[n]).group(1)
                for n in self.chapters()]

    def claims(self, prop):
        return re.findall(rf'<meta property="schema:{prop}">([^<]*)</meta>',
                          self.opf)

    def body(self):
        return "\n".join(self.files[n] for n in self.chapters())


# --------------------------------------------------------------------------
# the cases
# --------------------------------------------------------------------------

TREE = """\
    - metadata
    - title: Chapter 1 Tables
      items:
        - tables
        - page: tables-b
          title: Tables, Continued
    - title: Chapter 2 Everything Else
      items:
        - media-a
        - math
"""


def case_structure(work):
    """The book has the shape project.contents gives it."""
    convert(work, NEEDED)
    # No fixture has a heading below its title, so give one a section to
    # show the page's own headings continuing below its entry.
    path = os.path.join(work, "tables.filtered.json")
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    doc["blocks"].append({"t": "Header", "c": [
        2, ["sub", [], []], [{"t": "Str", "c": "Subsection"}]]})
    # And a footnote, which the writer leaves unnumbered.
    doc["blocks"].append({"t": "Para", "c": [
        {"t": "Str", "c": "Noted."},
        {"t": "Note", "c": [{"t": "Para", "c": [{"t": "Str", "c": "The note."}]}]}]})
    # And a body that opens with its own H1, emphasis and all, as a page
    # does when the filter's promotion did not fire: the heading keeps
    # the emphasis, and the chapter <title> must not.
    doc["blocks"].insert(0, {"t": "Header", "c": [
        1, ["own", [], []], [{"t": "Str", "c": "Prac"},
                             {"t": "Emph", "c": [{"t": "Str", "c": "tice"}]}]]})
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    write_config(work, TREE, "  authors: [A. Writer, B. Writer]\n"
                             "  publisher: OERforge\n")
    out = Built(work)
    entries = out.nav_entries()
    return [
        ("the build succeeds", lambda: out.status == 0),
        ("the nav lists groups at level 1 and their pages at level 2",
         lambda: entries == [
             (1, "1.3 Levels of Measurement"),
             (1, "Chapter 1 Tables"), (2, "Practice"),
             (2, "Tables, Continued"),
             (1, "Chapter 2 Everything Else"), (2, "Media A"),
             (2, "Conditional probability")]),
        ("a title given in contents overrides the page's own",
         lambda: (2, "Tables, Continued") in entries),
        ("every page and every group is its own file",
         lambda: len(out.chapters()) == 7),
        ("each file is titled by its heading, not its file name",
         lambda: out.titles() == [e[1] for e in entries]),
        ("a footnote is numbered where it appears, with a return link",
         lambda: '<span class="footnote-number">1.</span> The note.'
         in out.files[out.chapters()[2]]
         and 'href="#fnref1" class="footnote-back" role="doc-backlink"'
         in out.files[out.chapters()[2]]),
        ("a heading with emphasis gives a plain-text title",
         lambda: "<title>Practice</title>" in out.files[out.chapters()[2]]
         and "<h2>Prac<em>tice</em></h2>" in out.files[out.chapters()[2]]),
        # The writer puts a heading's id on the <section> it opens.
        ("a page inside a group is an h2 and its own sections h3",
         lambda: re.search(r'<section id="page-tables"[^>]*>\s*<h2>',
                           out.body())
         and re.search(r'<section id="page-tables--sub"[^>]*>\s*<h3>',
                       out.files[out.chapters()[2]])),
        ("a top-level page is an h1",
         lambda: re.search(r'<section id="page-metadata"[^>]*>\s*<h1>',
                           out.body())),
        ("the book's identifier is the project's, not a fresh UUID",
         lambda: ">org.example.fixtures</dc:identifier>" in out.opf),
        ("each author is a creator",
         lambda: out.opf.count("<dc:creator") == 2
         and ">B. Writer</dc:creator>" in out.opf),
        ("the publisher is recorded",
         lambda: "<dc:publisher>OERforge</dc:publisher>" in out.opf),
    ]


def case_tables_survive(work):
    """What the filter did to a table is still there in the book."""
    convert(work, ["tables", "tables-b"])
    write_config(work, "    - tables\n    - tables-b\n")
    out = Built(work)
    body = out.body()
    return [
        ("a declared row header is a th with scope=row",
         lambda: body.count('<th scope="row">') == 2),
        ("column headers keep scope=col",
         lambda: '<th scope="col">' in body),
        ("the scroll wrapper and its label survive",
         lambda: 'class="table-wrapper" tabindex="0"' in body),
        ("the page stylesheet is appended to Pandoc's",
         lambda: ".table-wrapper:focus-visible {" in out.files.get(
             "EPUB/styles/stylesheet1.css", "")),
    ]


def case_claims(work):
    """The package document says only what this build can stand behind."""
    convert(os.path.join(work, "bare"), ["media-a", "math"])
    write_config(os.path.join(work, "bare"), "    - media-a\n    - math\n")
    bare = Built(os.path.join(work, "bare"))

    # The same two pages with every image described or marked decorative.
    convert(os.path.join(work, "described"), ["media-a", "math"], sidecars={
        "image-alt.csv": "Image,Alt\n"
                         "media-a/media/image1,A described image\n"
                         "media-a/media/image2,[decorative]\n"
                         "math/media/image1,An equation stored as a picture\n"})
    write_config(os.path.join(work, "described"),
                 "    - media-a\n    - math\n",
                 extra_epub="    epub:\n      accessibility_summary: "
                            "Written by hand.\n")
    described = Built(os.path.join(work, "described"))
    return [
        ("an image without alt text withholds alternativeText",
         lambda: "alternativeText" not in bare.claims("accessibilityFeature")),
        ("and says text alone is not sufficient",
         lambda: bare.claims("accessModeSufficient") == ["textual,visual"]),
        ("a book with images has visual among its access modes",
         lambda: bare.claims("accessMode") == ["textual", "visual"]),
        ("equations are claimed as MathML",
         lambda: "MathML" in bare.claims("accessibilityFeature")),
        ("the derived summary counts the images still undescribed",
         lambda: re.search(r"\d+ of \d+ images have no alternative text",
                           bare.claims("accessibilitySummary")[0])),
        ("describing every image restores alternativeText",
         lambda: "alternativeText" in described.claims(
             "accessibilityFeature")),
        ("and makes text sufficient on its own",
         lambda: described.claims("accessModeSufficient") == ["textual"]),
        ("a summary set in the config is used as written",
         lambda: described.claims("accessibilitySummary")
         == ["Written by hand."]),
    ]


def case_contents_edges(work):
    """Pages the tree does not place, pages it names that do not exist,
    and a book that is one page."""
    convert(work, ["metadata", "tables", "math"])
    write_config(work, "    - metadata\n    - ghost\n    - tables\n")
    out = Built(work)
    single = os.path.join(work, "single")
    convert(single, ["metadata"])
    write_config(single, "    - metadata\n")
    one = Built(single)
    guessed = os.path.join(work, "guessed")
    convert(guessed, ["tables", "math"])
    write_config(guessed, "")
    with open(os.path.join(guessed, "project.yaml"), "w",
              encoding="utf-8") as fh:
        fh.write("project:\n  identifier: org.example.fixtures\n"
                 "  title: The Fixture Book\n")
    guess = Built(guessed)
    return [
        ("a page listed but not on disk is a warning, not a failure",
         lambda: out.status == 0
         and "not on disk: ghost.filtered.json" in out.stderr),
        ("a page on disk but not in contents is named and left out",
         lambda: "not in project.contents" in out.stderr
         and "  math" in out.stderr
         and "page-math" not in out.body()),
        # Its title was its own H1, taken into the metadata by the filter;
        # it comes back as the page's heading, once, with nothing above it.
        ("a one-page book has its own title heading back, once, and none above it",
         lambda: one.status == 0 and len(re.findall(r"<h1[ >]", one.body())) == 1),
        ("with no contents the order is guessed and said to be",
         lambda: guess.status == 0
         and "guessed order" in guess.stderr
         and len(guess.chapters()) == 2),
    ]


def case_targets(work):
    """Which targets get built, and how convert.py keeps its own."""
    convert(work, ["tables"])
    write_config(work, "    - tables\n")
    with open(os.path.join(work, "conversion.yaml"), "w",
              encoding="utf-8") as fh:
        fh.write("targets:\n  html:\n    format: html\n    output_dir: .\n")
    none = Built(work)
    quiet = subprocess.run(
        ["python3", os.path.join(BIN, "build-epub.py"), "-d", work,
         "--if-declared"], capture_output=True, text=True)
    with open(os.path.join(work, "conversion.yaml"), "w",
              encoding="utf-8") as fh:
        fh.write("targets:\n  html:\n    format: html\n    output_dir: .\n"
                 "  epub:\n    format: epub3\n    output_dir: books\n"
                 "    filename: fixtures\n")
    named = subprocess.run(
        ["python3", os.path.join(BIN, "build-epub.py"), "-d", work],
        capture_output=True, text=True)
    reader = subprocess.run(
        ["python3", os.path.join(BIN, "read-conversion-config.py"),
         "-d", work, os.path.join(work, "settings"), "--format", "html"],
        capture_output=True, text=True)
    settings = open(os.path.join(work, "settings", "settings.sh"),
                    encoding="utf-8").read() if reader.returncode == 0 else ""
    return [
        ("with no epub3 target the tool says how to declare one",
         lambda: none.status == 1 and "format: epub3" in none.stderr),
        ("--if-declared is silent instead",
         lambda: quiet.returncode == 0 and not quiet.stderr.strip()),
        ("output_dir and filename name the file, with the extension added",
         lambda: named.returncode == 0
         and os.path.exists(os.path.join(work, "books", "fixtures.epub"))),
        ("the settings reader picks the html target among several",
         lambda: reader.returncode == 0 and "TARGET_NAME='html'" in settings),
    ]


def case_rewriting(work):
    """The pure functions, on documents small enough to read."""
    doc = {"t": "Div", "c": [["intro", ["note"], [["headers", "a b"]]], [
        {"t": "Header", "c": [2, ["a", [], []], [{"t": "Str", "c": "A"}]]},
        {"t": "Para", "c": [
            {"t": "Link", "c": [["", [], []], [{"t": "Str", "c": "up"}],
                                ["#a", ""]]},
            {"t": "Link", "c": [["", [], []], [{"t": "Str", "c": "out"}],
                                ["https://example.org/#a", ""]]},
        ]},
    ]]}
    rewritten = copy.deepcopy(doc)
    epub.prefix_ids(rewritten, "p--")
    shifted = copy.deepcopy(doc)
    epub.shift_headers(shifted, 3)
    found = {"images": 0, "without_alt": 0, "math": 0}
    epub.count_images([
        {"t": "Image", "c": [["", [], []], [], ["x.png", ""]]},
        {"t": "Image", "c": [["", [], [["aria-hidden", "true"]]], [],
                             ["y.png", ""]]},
        {"t": "Image", "c": [["", [], []], [{"t": "Str", "c": "z"}],
                             ["z.png", ""]]},
    ], found)
    return [
        ("ids get the page prefix",
         lambda: rewritten["c"][0][0] == "p--intro"
         and rewritten["c"][1][0]["c"][1][0] == "p--a"),
        ("a headers attribute is rewritten token by token",
         lambda: rewritten["c"][0][2] == [["headers", "p--a p--b"]]),
        ("a same-page link follows its target",
         lambda: rewritten["c"][1][1]["c"][0]["c"][2][0] == "#p--a"),
        ("a link elsewhere is left alone",
         lambda: rewritten["c"][1][1]["c"][1]["c"][2][0]
         == "https://example.org/#a"),
        ("headings shift by the page's depth and stop at h6",
         lambda: shifted["c"][1][0]["c"][0] == 5
         and (epub.shift_headers(shifted, 3) or
              shifted["c"][1][0]["c"][0] == 6)),
        ("an empty alt counts as missing unless the image is decorative",
         lambda: found == {"images": 3, "without_alt": 1, "math": 0}),
        ("the derived summary reads the counts",
         lambda: "1 of 3 images" in epub.derived_summary(found)),
    ]


def case_outline(work):
    """The packager reads the book's table of contents back out of the
    EPUB, the way it reads a PDF's bookmarks."""
    convert(work, NEEDED)
    write_config(work, TREE)
    out = Built(work)
    cartridge = load(os.path.join(ROOT, "bin", "build-cartridge.py"),
                     "cartridge")
    path = os.path.join(work, "epub", "org.example.fixtures.epub")
    entries = cartridge.epub_outline(path)
    # The same book with no navigation document declared, so toc.ncx is
    # all there is: what an EPUB 2 offers.
    ncx_only = os.path.join(work, "ncx-only.epub")
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(ncx_only, "w") as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename.endswith(".opf"):
                data = data.replace(b' properties="nav"', b"")
            dst.writestr(info, data)
    fallback = cartridge.epub_outline(ncx_only)
    stems = [s for s in NEEDED]
    titles = {}
    for stem in stems:
        with open(os.path.join(work, stem + ".filtered.json"),
                  encoding="utf-8") as fh:
            titles[stem] = epub.page_title(json.load(fh), stem)
    tree, placed, unmapped = cartridge.contents_from_outline(path, stems,
                                                             titles)
    return [
        ("the build succeeds", lambda: out.status == 0),
        ("the navigation document gives the entries at their depths",
         lambda: entries == [
             (0, "1.3 Levels of Measurement"), (0, "Chapter 1 Tables"),
             (1, "Practice"), (1, "Tables, Continued"),
             (0, "Chapter 2 Everything Else"), (1, "Media A"),
             (1, "Conditional probability")]),
        ("without a navigation document, toc.ncx gives the same, after "
         "the title page it also lists",
         lambda: fallback[-len(entries):] == entries),
        # A page is found by the filename its heading derives (how
        # OpenStax names files) or, failing that, by its own title.
        # tables-b is titled "More tables" and the contents renamed it
        # "Tables, Continued" in the nav, so that entry names no page.
        ("every page whose title the outline uses is placed under its group",
         lambda: placed == set(stems) - {"tables-b"}
         and tree == ["metadata",
                      {"title": "Chapter 1 Tables", "items": ["tables"]},
                      {"title": "Chapter 2 Everything Else",
                       "items": ["media-a", "math"]}]),
        ("an entry that names no page is reported, not guessed at",
         lambda: unmapped == ["Tables, Continued"]),
    ]


def markdown_page(work, name, text):
    """A page from Markdown, as convert.py leaves one: raw and filtered."""
    environment = dict(os.environ, PROMOTE_H1_TO_TITLE="always", AUTHOR_BYLINE="meta",
                       IMAGE_ALT_MISSING=os.path.join(work, "alt-missing.csv"),
                       TABLE_CAPTIONS_MISSING=os.path.join(work, "caps-missing.csv"))
    with open(os.path.join(work, name + ".md"), "w", encoding="utf-8") as fh:
        fh.write(text)
    run(["pandoc", "-f", "markdown", "-t", "json", name + ".md", "-o", name + ".json"],
        work, environment)
    run(["pandoc", "-f", "json", "-t", "json", name + ".json", "-o", name + ".filtered.json",
         "--lua-filter", os.path.join(BIN, "figures-and-tables.lua")], work, environment)


def case_divisions(work):
    """Each chapter file's body says its division, from the page's role in
    contents or, with none, from what its heading says the page is, which
    its section carries with the ARIA role; a page's own sections, in
    files of their own, are in its division with no type; and the
    landmarks name the contents, the start of the body, and a glossary.
    A book without a contents page names no contents there, which would
    be a file outside the spine, and a book of one page is left as
    Pandoc's writer made it."""
    convert(work, ["metadata", "tables"])
    markdown_page(work, "preface", "# Preface {epub:type=preface}\n\nWhy this book.[^1]\n\n"
                                   "## Who this is for\n\nReaders.\n\n[^1]: A note.\n")
    markdown_page(work, "roman", '# IV {epub:type="title z3998:roman"}\n\nA chapter numbered so.\n')
    markdown_page(work, "terms", "# Terms & Symbols {.glossary}\n\nWords.\n\n## G1\n\nMore words.\n")
    write_config(work, "    - page: preface\n      role: front\n    - generate: toc\n"
                       "    - metadata\n    - roman\n"
                       "    - page: terms\n      role: back\n"
                       "    - title: Appendices\n      role: appendix\n      items:\n"
                       "        - tables\n",
                 extra_epub="    notes:\n      placement: book\n")
    out = Built(work)

    def chapter(ident):
        """The chapter file whose section has this id."""
        return next((t for n, t in sorted(out.files.items()) if "/text/" in n
                     and re.search(r'<section\b[^>]*\bid="%s"' % re.escape(ident), t)), "")

    def body(ident):
        m = re.search(r'<body epub:type="([^"]+)"', chapter(ident))
        return m.group(1) if m else None

    def section(ident):
        m = re.search(r'<section\b[^>]*\bid="%s"[^>]*>' % re.escape(ident), chapter(ident))
        return m.group(0) if m else ""

    def file_of(ident):
        return next((n.split("EPUB/", 1)[1] for n, t in sorted(out.files.items())
                     if "/text/" in n and t == chapter(ident)), None)

    def sub(prefix):
        """The id of a page's section whose id starts so."""
        return next((i for t in out.files.values()
                     for i in re.findall(r'<section\b[^>]*\bid="(%s[^"]+)"' % re.escape(prefix), t)),
                    "")

    def landmarks(built):
        nav = built.files.get("EPUB/nav.xhtml", "")
        marks = re.search(r'<nav epub:type="landmarks".*?</nav>', nav, re.S)
        marks = marks.group(0) if marks else ""
        return marks, dict((kind, (href, label)) for href, kind, label in re.findall(
            r'<a href="([^"]+)" epub:type="([^"]+)">([^<]*)</a>', marks))
    marks, named = landmarks(out)
    written = subprocess.run(
        ["pandoc", "-f", "json", "-t", "markdown", "preface.filtered.json",
         "--lua-filter", os.path.join(BIN, "target-blocks.lua")], cwd=work,
        capture_output=True, text=True, env=dict(os.environ, TITLE_WRITER="markdown"))

    # The same pages with no contents page, and Pandoc's own types in a
    # book of one page.
    bare = os.path.join(work, "bare")
    convert(bare, ["metadata"])
    markdown_page(bare, "terms", "# Terms {.glossary}\n\nWords.\n")
    write_config(bare, "    - metadata\n    - terms\n")
    plain = Built(bare)
    one = os.path.join(work, "one")
    os.makedirs(one)
    markdown_page(one, "book", "# Preface {epub:type=preface}\n\nWhy.\n\n# Chapter one\n\nText.\n\n"
                               "# Index {epub:type=index}\n\nTerms.\n")
    write_config(one, "    - book\n")
    single = Built(one)
    single_bodies = [re.search(r'<body epub:type="([^"]+)"', single.files[n]).group(1)
                     for n in single.chapters()]
    single_roles = [re.search(r'<section\b[^>]*>', single.files[n]).group(0)
                    for n in single.chapters()]

    epubcheck = os.environ.get("EPUBCHECK_JAR")

    def passes(built_dir):
        if not (epubcheck and os.path.exists(epubcheck) and shutil.which("java")):
            return True
        return subprocess.run(["java", "-jar", epubcheck, os.path.join(
            built_dir, "epub", "org.example.fixtures.epub")], capture_output=True).returncode == 0
    return [
        ("a front-matter page whose heading says it's a preface is front matter, its "
         "section a preface with its ARIA role",
         lambda: out.status == 0 and body("page-preface") == "frontmatter"
         and 'epub:type="preface"' in section("page-preface")
         and 'role="doc-preface"' in section("page-preface")),
        ("a page's own section, in a file of its own, is in the page's division with no type",
         lambda: sub("page-preface--") and body(sub("page-preface--")) == "frontmatter"
         and "epub:type" not in section(sub("page-preface--"))
         and body(sub("page-terms--")) == "backmatter"
         and "epub:type" not in section(sub("page-terms--"))),
        ("the generated contents, with no role, is in the division of the page before it",
         lambda: body("page-toc") == "frontmatter"),
        ("a page in the main matter is body matter, its section left as Pandoc wrote it",
         lambda: body("page-metadata") == "bodymatter"
         and "epub:type" not in section("page-metadata")),
        ("a heading's epub:type that names the heading, not the page (title z3998:roman), "
         "isn't the page's", lambda: body("page-roman") == "bodymatter"
         and "epub:type" not in section("page-roman")),
        ("an appendix group and its page are back matter, the page an appendix",
         lambda: body("group-1-appendices") == "backmatter"
         and 'epub:type="appendix"' not in section("group-1-appendices")
         and body("page-tables") == "backmatter"
         and 'role="doc-appendix"' in section("page-tables")),
        ("the Notes chapter after the appendices is back matter and no appendix",
         lambda: body("page-notes") == "backmatter" and "epub:type" not in section("page-notes")),
        ("a page whose heading's class says it's a glossary is one, its role from contents",
         lambda: body("page-terms") == "backmatter"
         and 'epub:type="glossary" role="doc-glossary"' in section("page-terms")),
        ("the landmarks name the contents page, the start of the body, and the glossary by "
         "its title, the title page still first",
         lambda: marks.index('epub:type="titlepage"') < marks.index('epub:type="toc"')
         and named.get("toc", ("",))[0] == file_of("page-toc")
         and named.get("bodymatter", ("",))[0] == file_of("page-metadata")
         and named.get("glossary") == (file_of("page-terms"), "Terms &amp; Symbols")),
        ("a Markdown target puts the page's type back on its heading",
         lambda: written.returncode == 0
         and re.search(r'^# Preface \{[^}]*epub:type="preface"', written.stdout, re.M)),
        ("with no contents page, the landmarks name no contents, and the start of the body",
         lambda: plain.status == 0 and 'epub:type="toc"' not in landmarks(plain)[0]
         and "bodymatter" in landmarks(plain)[1]),
        ("a book of one page keeps the divisions Pandoc's writer gives its headings' types, "
         "and each typed section gets its ARIA role",
         lambda: single.status == 0
         and single_bodies == ["frontmatter", "bodymatter", "backmatter"]
         and 'role="doc-preface"' in single_roles[0] and "role=" not in single_roles[1]
         and 'role="doc-index"' in single_roles[2]),
        ("epubcheck passes all three", lambda: passes(work) and passes(bare) and passes(one)),
    ]


def case_declared_types(work):
    """A type in contents: on a page a Word file can't type itself, on a
    group, over what a heading says; a top-level entry with no role in
    the division its type implies, and a page inside a chapter in the
    chapter's, a glossary or not, and not among the book's landmarks."""
    convert(work, ["metadata", "tables", "math"])
    markdown_page(work, "terms", "# Key Terms {.glossary}\n\nA chapter's words.\n")
    markdown_page(work, "words", "# Words {.glossary}\n\nThe book's words.\n")
    markdown_page(work, "late", "# Thanks\n\nAt the end, as some books have them.\n")
    markdown_page(work, "said", "# Sayings {.glossary}\n\nA heading's word for it.\n")
    write_config(work, "    - page: metadata\n      type: preface\n"
                       "    - title: Part One\n      type: part\n      items:\n"
                       "        - title: Chapter 1\n          items:\n"
                       "            - tables\n            - terms\n"
                       "    - math\n    - said\n"
                       "    - page: late\n      type: acknowledgments\n      role: back\n"
                       "    - page: words\n      type: index\n"
                       "    - page: ghostly\n      type: postscript\n",
                 extra_project="  numbering: true\n")
    out = Built(work)
    numbered = out.nav_entries()
    # A declared split source, and a group's opening page, each with a
    # type: the group that stands for them is what they are.
    cut = os.path.join(work, "cut")
    convert(cut, ["metadata"])
    markdown_page(cut, "key-terms", "# Key Terms\n\nIntro.\n\n## A\n\nAbacus.\n\n## B\n\nBeam.\n")
    run(["python3", os.path.join(BIN, "split-pages.py"), "--level", "2",
         "--sidecar", os.path.join(cut, "page-names.csv"),
         "--new", os.path.join(cut, "page-names-new.csv"),
         "--report", os.path.join(cut, "page-names-report.csv"),
         os.path.join(cut, "key-terms.filtered.json")], cut)
    write_config(cut, "    - metadata\n    - page: key-terms\n      type: glossary\n",
                 extra_project="  numbering: true\n")
    split_book = Built(cut)
    opened = os.path.join(work, "opened")
    convert(opened, ["metadata"])
    markdown_page(opened, "gloss", "# Glossary\n\nTerms, A to M.\n")
    markdown_page(opened, "more", "# More Terms\n\nN to Z.\n")
    write_config(opened, "    - metadata\n    - title: Glossary\n      items:\n"
                         "        - page: gloss\n          type: glossary\n        - more\n"
                         "    - page: odd\n      type: [glossary]\n",
                 extra_project="  numbering: true\n")
    opener_book = Built(opened)

    def typed_group(built, ident):
        files = [t for n, t in sorted(built.files.items()) if "/text/" in n
                 and re.search(r'<section\b[^>]*\bid="%s"' % re.escape(ident), t)]
        if not files:
            return None
        tag = re.search(r'<section\b[^>]*\bid="%s"[^>]*>' % re.escape(ident), files[0]).group(0)
        body_type = re.search(r'<body epub:type="([^"]+)"', files[0]).group(1)
        marks_of = re.search(r'<nav epub:type="landmarks".*?</nav>',
                             built.files.get("EPUB/nav.xhtml", ""), re.S)
        return (body_type, 'epub:type="glossary" role="doc-glossary"' in tag,
                bool(marks_of) and 'epub:type="glossary"' in marks_of.group(0),
                [t for _, t in built.nav_entries()])

    def chapter(ident):
        return next((t for n, t in sorted(out.files.items()) if "/text/" in n
                     and re.search(r'<section\b[^>]*\bid="%s"' % re.escape(ident), t)), "")

    def body(ident):
        m = re.search(r'<body epub:type="([^"]+)"', chapter(ident))
        return m.group(1) if m else None

    def section(ident):
        m = re.search(r'<section\b[^>]*\bid="%s"[^>]*>' % re.escape(ident), chapter(ident))
        return m.group(0) if m else ""
    nav = out.files.get("EPUB/nav.xhtml", "")
    marks = re.search(r'<nav epub:type="landmarks".*?</nav>', nav, re.S)
    marks = marks.group(0) if marks else ""

    def labelled_by(ident):
        """The text of the heading a section's aria-labelledby names."""
        m = re.search(r'aria-labelledby="([^"]+)"', section(ident))
        if not m:
            return None
        h = re.search(r'<h[1-6]\b[^>]*\bid="%s"[^>]*>(.*?)</h[1-6]>' % re.escape(m.group(1)),
                      chapter(ident), re.S)
        return " ".join(re.sub(r"<[^>]+>", "", h.group(1)).split()) if h else None
    return [
        ("a Word page that contents calls a preface is one, in the front matter",
         lambda: out.status == 0 and body("page-metadata") == "frontmatter"
         and 'epub:type="preface" role="doc-preface"' in section("page-metadata")),
        ("a group that contents calls a part is one, and its chapters aren't parts",
         lambda: 'epub:type="part" role="doc-part"' in section("group-1-part-one")
         and "epub:type" not in section("group-2-chapter-1")
         and body("group-1-part-one") == "bodymatter"),
        ("a chapter's own glossary is one, in the chapter's body matter, and not the book's "
         "landmark", lambda: body("page-terms") == "bodymatter"
         and 'epub:type="glossary" role="doc-glossary"' in section("page-terms")
         and 'epub:type="glossary"' not in marks),
        ("acknowledgments with role back are back matter, the role outranking the type's "
         "front", lambda: body("page-late") == "backmatter"
         and 'role="doc-acknowledgments"' in section("page-late")),
        ("what contents says a page is outranks its heading, and a book-level index is a "
         "landmark", lambda: 'epub:type="index" role="doc-index"' in section("page-words")
         and "glossary" not in section("page-words") and body("page-words") == "backmatter"
         and 'epub:type="index"' in marks),
        ("a page whose heading alone says it's a glossary is marked one, in the part of the "
         "book contents puts it", lambda: body("page-said") == "bodymatter"
         and 'epub:type="glossary" role="doc-glossary"' in section("page-said")),
        ("a type that isn't one is a warning naming the types",
         lambda: "type 'postscript' is not one of" in out.stderr),
        ("each typed section is named by its own heading, so a screen reader's list of "
         "landmarks names it, and an untyped one isn't named",
         lambda: [labelled_by(i) for i in ("page-metadata", "group-1-part-one", "page-terms",
                                           "page-words")]
         == ["1.3 Levels of Measurement", "1 Part One", "Key Terms", "Words"]
         and "aria-labelledby" not in section("page-math")),
        ("numbered, the preface and the book's index count as the front and back matter "
         "their types put them in, and the part as a part",
         lambda: any(t.startswith("1 Part One") for _, t in numbered)
         and not any(re.match(r"\d+ ", t) and "Words" in t for _, t in numbered)
         and [t for _, t in numbered][0] == "1.3 Levels of Measurement"
         and "Words" in [t for _, t in numbered] and "2 Conditional probability"
         in [t for _, t in numbered]),
        ("a split source contents calls a glossary is one, the group its pieces make, in the "
         "back matter and unnumbered, and the book's landmark",
         lambda: split_book.status == 0 and (typed_group(split_book, "group-1-key-terms")
                                             or typed_group(split_book, "page-key-terms"))[:3]
         == ("backmatter", True, True)
         and not any(re.match(r"\d", t) for t in (typed_group(split_book, "page-key-terms")
                                                   or typed_group(split_book, "group-1-key-terms"))[3]
                     if "Key Terms" in t)),
        ("a group whose opening page contents calls a glossary is one, in the back matter and "
         "unnumbered", lambda: opener_book.status == 0
         and typed_group(opener_book, "page-gloss")[:3] == ("backmatter", True, True)
         and "Glossary" in typed_group(opener_book, "page-gloss")[3]),
        ("a type that isn't a word is a warning, not a crash",
         lambda: opener_book.status == 0 and "type ['glossary'] is not one of" in opener_book.stderr),
        ("epubcheck passes it", lambda: not (os.environ.get("EPUBCHECK_JAR") and shutil.which("java"))
         or subprocess.run(["java", "-jar", os.environ["EPUBCHECK_JAR"], os.path.join(
             work, "epub", "org.example.fixtures.epub")], capture_output=True).returncode == 0),
    ]


CASES = [
    ("the shape of the book", case_structure),
    ("the table of contents read back", case_outline),
    ("tables survive assembly", case_tables_survive),
    ("accessibility claims", case_claims),
    ("contents edge cases", case_contents_edges),
    ("targets and file names", case_targets),
    ("rewriting a page for the book", case_rewriting),
    ("divisions and landmarks", case_divisions),
    ("types declared in contents", case_declared_types),
]


# --------------------------------------------------------------------------

def run_cases(cases, keep):
    """The cases one after another, here: how many checks failed."""
    work = tempfile.mkdtemp(prefix="epub-tests-")
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
                    passed = predicate()
                except Exception as exc:
                    passed, name = False, f"{name}  ({exc})"
                print(("  ok    " if passed else "  FAIL  ") + name)
                failed += not passed
    finally:
        if keep:
            print(f"\nOutput left in {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
    return failed


def main():
    parser = argparse.ArgumentParser(
        description="Check build-epub.py against the fixture documents.")
    parser.add_argument("--keep", action="store_true",
                        help="leave the built output in place")
    parallel.add_options(parser)
    arguments = parser.parse_args()

    if shutil.which("pandoc") is None:
        sys.exit("pandoc is not on the path.")
    version = subprocess.run(["pandoc", "--version"], capture_output=True,
                             text=True).stdout.split()[1]
    if tuple(int(p) for p in re.findall(r"\d+", version)[:3]) < (3, 9):
        sys.exit(f"Pandoc {version} is too old; these tests need 3.9 or "
                 "later, as convert.py does.")
    missing = [n for n in NEEDED
               if not os.path.isfile(os.path.join(FIXTURES, n + ".docx"))]
    if missing:
        sys.exit("Missing fixtures: " + ", ".join(missing) +
                 "\nRebuild them with tests/make-filter-fixtures.py")
    if arguments.case_index is not None:
        # One case, for a run with them side by side: its lines, and how
        # many failed as the exit status.
        return min(run_cases([CASES[arguments.case_index]], arguments.keep), parallel.MOST)
    if arguments.jobs > 1:
        failed = parallel.run(os.path.abspath(__file__), CASES, (), arguments.jobs,
                              extra=["--keep"] if arguments.keep else [])
    else:
        failed = run_cases(CASES, arguments.keep)
    print(f"\n{failed} check(s) failed across {len(CASES)} case(s)"
          if failed else "\nall EPUB checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
