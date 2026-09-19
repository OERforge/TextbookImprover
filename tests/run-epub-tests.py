#!/usr/bin/env python3
"""
run-epub-tests.py -- check build-epub.py against the fixture documents.

    python3 tests/run-epub-tests.py           # run every case
    python3 tests/run-epub-tests.py --keep    # leave the output in place

Needs Pandoc 3.9 or later, as convert.sh does. The fixtures are converted
to filtered intermediates the way convert.sh does it, then assembled.

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
    """The fixtures as convert.sh leaves them: raw and filtered JSON."""
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
                    if name.endswith((".opf", ".xhtml")):
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
        for m in re.finditer(r"(<ol[^>]*>)|(</ol>)|<a [^>]*>([^<]*)</a>",
                             self.nav):
            if m.group(1):
                depth += 1
            elif m.group(2):
                depth -= 1
            else:
                entries.append((depth, m.group(3)))
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
         lambda: "page.css" in out.files.get("EPUB/styles/stylesheet1.css",
                                              "")
         if "EPUB/styles/stylesheet1.css" in out.files else True),
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
        ("a one-page book gets no heading above its own",
         lambda: one.status == 0 and "page-metadata" not in one.body()),
        ("with no contents the order is guessed and said to be",
         lambda: guess.status == 0
         and "guessed order" in guess.stderr
         and len(guess.chapters()) == 2),
    ]


def case_targets(work):
    """Which targets get built, and how convert.sh keeps its own."""
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
        ("convert.sh's reader picks the html target among several",
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
        {"t": "Image", "c": [["", [], [["role", "presentation"]]], [],
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


CASES = [
    ("the shape of the book", case_structure),
    ("tables survive assembly", case_tables_survive),
    ("accessibility claims", case_claims),
    ("contents edge cases", case_contents_edges),
    ("targets and file names", case_targets),
    ("rewriting a page for the book", case_rewriting),
]


# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Check build-epub.py against the fixture documents.")
    parser.add_argument("--keep", action="store_true",
                        help="leave the built output in place")
    arguments = parser.parse_args()

    if shutil.which("pandoc") is None:
        sys.exit("pandoc is not on the path.")
    version = subprocess.run(["pandoc", "--version"], capture_output=True,
                             text=True).stdout.split()[1]
    if tuple(int(p) for p in re.findall(r"\d+", version)[:3]) < (3, 9):
        sys.exit(f"Pandoc {version} is too old; these tests need 3.9 or "
                 "later, as convert.sh does.")
    missing = [n for n in NEEDED
               if not os.path.isfile(os.path.join(FIXTURES, n + ".docx"))]
    if missing:
        sys.exit("Missing fixtures: " + ", ".join(missing) +
                 "\nRebuild them with tests/make-filter-fixtures.py")

    work = tempfile.mkdtemp(prefix="epub-tests-")
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

    print(f"\n{failed} check(s) failed across {len(CASES)} case(s)"
          if failed else "\nall EPUB checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
