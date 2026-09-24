#!/usr/bin/env python3
"""
run-unit-tests.py -- check the small pure functions, and the places where
one fact is written down twice.

    python3 tests/run-unit-tests.py

Needs nothing but Python 3 and PyYAML. Fast enough to run on every save.

TWO KINDS OF CHECK

The first is ordinary: a function, some inputs, the answers. These
functions decide filenames and directory names, which means their mistakes
end up in an LMS rather than in a stack trace. One of them shipped for a
day: a reverse-DNS identifier such as org.example.book-2e was read as a
filename whose extension was ".book-2e", so the archive came out with no
extension at all. That is a three-line assertion here.

The second kind checks that a fact stated in two places still agrees.
lib/bookcontents.py has a built-in back-matter order, and the packaging
schema documents a default for it; they drifted, and the schema's copy was
missing seven entries. A schema exists to be the single description of a
setting, so anywhere a default is also hardcoded is worth asserting about
rather than trusting.

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

import importlib.util
import subprocess
import os
import re
import tempfile
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))
import bookcontents  # noqa: E402

try:
    import yaml
except ImportError:
    sys.exit("This needs PyYAML:\n    sudo apt install python3-yaml")

import oerconfig                                     # noqa: E402


def load(path, name):
    """Import a script by path, since bin/ is not a package."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cartridge = load(os.path.join(ROOT, "bin", "build-cartridge.py"), "cartridge")
validator = load(os.path.join(ROOT, "bin", "validate-manifest.py"), "validator")


# --------------------------------------------------------------------------
# the archive's name
# --------------------------------------------------------------------------

def check_archive_name():
    def name(settings, project, target="cartridge"):
        return cartridge.archive_name(settings, project, target)

    cc = {"format": "common-cartridge", "filename": ""}
    zipped = {"format": "zip", "filename": ""}
    return [
        ("a dotted identifier still gets the format's extension",
         lambda: name(cc, {"identifier": "org.szarka.badm224.ibs2e"})
                 == "org.szarka.badm224.ibs2e.imscc"),
        ("a plain identifier gets it too",
         lambda: name(cc, {"identifier": "ibs2"}) == "ibs2.imscc"),
        ("a filename given in full is used exactly",
         lambda: name({"format": "common-cartridge",
                       "filename": "course.imscc"},
                      {"identifier": "ibs2"}) == "course.imscc"),
        ("a filename given without one gets the format's extension",
         lambda: name({"format": "common-cartridge", "filename": "course"},
                      {"identifier": "ibs2"}) == "course.imscc"),
        ("the extension follows the format",
         lambda: name(zipped, {"identifier": "org.example.book-2e"})
                 == "org.example.book-2e.zip"),
        ("with no identifier it falls back to the target's name",
         lambda: name(cc, {}, "brightspace") == "brightspace.imscc"),
    ]


# --------------------------------------------------------------------------
# the content prefix
# --------------------------------------------------------------------------

def check_content_prefix():
    def prefix(title, identifier, **settings):
        options = {"prefix_content": True, "prefix": ""}
        options.update(settings)
        return cartridge.content_prefix(
            {"title": title, "identifier": identifier}, options)

    return [
        ("readable from the title, unique from the identifier",
         lambda: prefix("Introductory Business Statistics 2e",
                        "org.szarka.badm224.ibs2e")
                 == "introductory-business-statistics-a678320ab5"),
        ("two books sharing a title get different directories",
         lambda: prefix("General Sociology", "a")
                 != prefix("General Sociology", "b")),
        ("the same book gets the same directory every time",
         lambda: prefix("General Sociology", "x")
                 == prefix("General Sociology", "x")),
        # The version is deliberately absent, which keeps an update
        # landing on the same paths. It cannot be asserted directly
        # because it is not an input to this function -- so what is
        # asserted instead is where the uniqueness comes from: the digest
        # is over the identifier, so it survives any change of title.
        ("the digest comes from the identifier, not the title",
         lambda: prefix("One Title", "same-id").rsplit("-", 1)[-1]
                 == prefix("A Quite Different Title", "same-id")
                 .rsplit("-", 1)[-1]),
        ("a title that sanitises to nothing leaves the digest alone",
         lambda: re.fullmatch(r"[0-9a-f]{10}", prefix("課程", "x")) is not None),
        ("punctuation and spacing are reduced, not dropped",
         lambda: prefix("A  Book: Second (Revised) Edition", "x")
                 .startswith("a-book-second-revised-edition-")),
        ("an explicit prefix wins",
         lambda: prefix("Anything", "x", prefix="my-book") == "my-book"),
        ("a leading or trailing slash on an explicit prefix is dropped",
         lambda: prefix("Anything", "x", prefix="/my-book/") == "my-book"),
        ("turning it off gives no prefix at all",
         lambda: prefix("Anything", "x", prefix_content=False) == ""),
    ]


# --------------------------------------------------------------------------
# the wrapper module's name
# --------------------------------------------------------------------------

def check_wrapper_title():
    def title(template, project=None, manifest=None):
        return cartridge.wrapper_title(
            project or {"title": "Stats"},
            {"module_title": template},
            manifest or {"version": "1.3", "title": "Stats"})

    return [
        ("the default template names the book and its version",
         lambda: title("{title} ({version})") == "Stats (1.3)"),
        ("a template may name the book alone",
         lambda: title("{title}") == "Stats"),
        ("a template naming something unknown does not stop the build",
         lambda: title("{title} {nonsense}") == "Stats"),
        ("an empty template falls back to the title",
         lambda: title("") == "Stats"),
    ]


# --------------------------------------------------------------------------
# identifiers, which IMS types as xs:ID
# --------------------------------------------------------------------------

def check_identifiers():
    good = ["org.szarka.badm224.ibs2e", "ibs2", "_private",
            "i3f2504e04f8911d39a0c0305e82c3301", "a-b_c.d"]
    bad = ["3f2504e0-4f89-11d3-9a0c-0305e82c3301",
           "urn:uuid:3f2504e0", "general sociology", "", "-leading-dash"]
    return [
        ("valid XML names are accepted",
         lambda: all(validator.NCNAME_RE.match(v) for v in good)),
        ("a bare UUID is refused, because it starts with a digit",
         lambda: not validator.NCNAME_RE.match(bad[0])),
        ("a urn: form is refused, because of the colons",
         lambda: not validator.NCNAME_RE.match(bad[1])),
        ("anything else invalid is refused too",
         lambda: not any(validator.NCNAME_RE.match(v) for v in bad)),
    ]


# --------------------------------------------------------------------------
# facts written down twice
# --------------------------------------------------------------------------

def check_consistency():
    schema = yaml.safe_load(
        open(os.path.join(ROOT, "bin", "schema-packaging.yaml"),
             encoding="utf-8"))
    declared = (schema["keys"]["grouping"]["keys"]["back_matter"]["default"])
    source = open(os.path.join(ROOT, "lib", "bookcontents.py"),
                  encoding="utf-8").read()
    builtin = re.findall(
        r'"([^"]+)"',
        re.search(r"BACK_MATTER_ORDER = \[(.*?)\]", source, re.S).group(1))


    return [
        ("the schema's back-matter default matches the built-in order",
         lambda: list(declared) == builtin),
        ("every schema loads and declares its keys",
         lambda: all("keys" in yaml.safe_load(open(p, encoding="utf-8"))
                     for p in (
                         os.path.join(ROOT, "bin", "schema-packaging.yaml"),
                         os.path.join(ROOT, "bin", "schema-conversion.yaml"),
                         os.path.join(ROOT, "lib", "schema-project.yaml")))),
        ("every declared setting has a description",
         lambda: not undescribed()),
    ]


def undescribed():
    """Settings with no description, which would appear in a generated
    configuration as a bare key with nothing saying what it is."""
    missing = []
    for path in (os.path.join(ROOT, "bin", "schema-packaging.yaml"),
                 os.path.join(ROOT, "bin", "schema-conversion.yaml"),
                 os.path.join(ROOT, "lib", "schema-project.yaml")):
        schema = oerconfig.load_schema(path)

        def walk(node, prefix=""):
            for name, child in node.keys.items():
                where = f"{prefix}{name}"
                if not child.description:
                    missing.append(f"{os.path.basename(path)}:{where}")
                if child.is_section:
                    walk(child, where + ".")
        walk(schema.root)
    return missing


# --------------------------------------------------------------------------

def check_sidecar_paths():
    """How convert.py turns a configured sidecar name into a path.

    convert.py built "$PWD/$name" unconditionally, so an absolute setting
    became "/book//srv/corrections/table-captions.csv". The filter read
    nothing, every correction in the file was discarded, and the only
    trace was an instruction telling the user to append their work to a
    path that did not exist. Sidecars are the one thing here that no
    script can reproduce, so failing to read one silently is the worst
    failure this pipeline has. The Python has one helper for it, called
    directly here.
    """
    convert = load(os.path.join(ROOT, "bin", "convert.py"), "convert")
    base = tempfile.mkdtemp(prefix="sidecar-paths-")

    import contextlib
    import io
    said = []

    def stops(path, setting, default):
        # What convert.py prints on the way out is the check's to read,
        # not the terminal's: an expected error shouldn't look like one.
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                convert.check_sidecar(path, setting, default, base)
        except SystemExit:
            said.append(err.getvalue())
            return True
        return False

    return [
        ("an absolute sidecar path is used as given",
         lambda: convert.resolve_path(base, "/srv/corrections/t.csv")
                 == "/srv/corrections/t.csv"),
        ("a bare name resolves against the content directory",
         lambda: convert.resolve_path(base, "table-captions.csv")
                 == os.path.join(base, "table-captions.csv")),
        ("a path escaping the content directory stays relative to it",
         lambda: convert.resolve_path(base, "../corrections/t.csv")
                 == os.path.join(base, "../corrections/t.csv")),
        ("a configured sidecar that does not exist stops the run, naming "
         "the setting and the file",
         lambda: stops(os.path.join(base, "corrections", "t.csv"),
                       "sidecars.table_captions", "table-captions.csv")
         and "sidecars.table_captions" in said[-1] and "t.csv" in said[-1]),
        ("the default name, not yet written, is the normal starting state",
         lambda: not stops(os.path.join(base, "table-captions.csv"),
                           "sidecars.table_captions", "table-captions.csv")),
    ]


def check_docx_repair():
    """Bookmarks between blocks move into the block that follows."""
    import xml.etree.ElementTree as ET
    import docxrepair
    import tablecensus
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    xml = ('<w:document xmlns:w="%s"><w:body>'
           '<w:p><w:r><w:t>before</w:t></w:r></w:p>'
           '<w:bookmarkStart w:id="1" w:name="fs-one"/>'
           '<w:bookmarkEnd w:id="1"/>'
           '<w:p><w:pPr><w:pStyle w:val="BodyText"/></w:pPr>'
           '<w:r><w:t>target</w:t></w:r></w:p>'
           '<w:bookmarkStart w:id="2" w:name="fs-tbl"/>'
           '<w:bookmarkStart w:id="3" w:name="_GoBack"/>'
           '<w:tbl><w:tblGrid><w:gridCol/></w:tblGrid><w:tr><w:tc>'
           '<w:p><w:r><w:t>cell</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
           '</w:body></w:document>' % W)
    fixed, moved = docxrepair.move_bookmarks_into_paragraphs(xml)
    body = ET.fromstring(fixed).find("{%s}body" % W)
    tbl = body.find("{%s}tbl" % W)
    heading = ('<w:document xmlns:w="%s"><w:body>'
               '<w:bookmarkStart w:id="1" w:name="note-1"/>'
               '<w:p><w:pPr><w:pStyle w:val="Heading2Grey"/></w:pPr>'
               '<w:r><w:t>Case Study</w:t></w:r></w:p>'
               '<w:hyperlink w:anchor="note-1"><w:r><w:t>x</w:t></w:r>'
               '</w:hyperlink></w:body></w:document>' % W)
    fixed_heading, _ = docxrepair.move_bookmarks_into_paragraphs(heading)
    kept, count = docxrepair.keep_unlinked_bookmarks(xml)
    return [
        ("a bookmark before a heading gets a paragraph of its own",
         lambda: '<w:p><w:r><w:t>&#8203;</w:t></w:r>'
         '<w:bookmarkStart w:id="1" w:name="note-1"/></w:p>'
         '<w:p><w:pPr><w:pStyle w:val="Heading2Grey"/>' in fixed_heading),
        ("a bookmark the source put inside a heading is moved out before it",
         lambda: (lambda f: '<w:p><w:r><w:t>&#8203;</w:t></w:r>'
                  '<w:bookmarkStart w:id="9" w:name="term-9"/>'
                  '</w:p><w:p><w:pPr><w:pStyle w:val="Heading3Grey"/></w:pPr>'
                  '<w:r>' in f)(docxrepair.move_bookmarks_into_paragraphs(
                      '<w:document xmlns:w="%s"><w:body><w:p><w:pPr>'
                      '<w:pStyle w:val="Heading3Grey"/></w:pPr>'
                      '<w:bookmarkStart w:id="9" w:name="term-9"/>'
                      '<w:r><w:t>Term</w:t></w:r></w:p></w:body></w:document>'
                      % W)[0])),
        ("bookmarks no link in the document points at get a keeper link",
         lambda: count == 2 and 'w:anchor="fs-one"' in kept
         and 'w:anchor="fs-tbl"' in kept),
        ("a bookmark already linked, or Word's own, gets none",
         lambda: 'w:anchor="_GoBack"' not in kept
         and docxrepair.keep_unlinked_bookmarks(heading)[1] == 0),
        ("one bookmark moved, the one before a paragraph",
         lambda: moved == 1),
        ("it sits after the paragraph's properties",
         lambda: '</w:pPr><w:bookmarkStart w:id="1" w:name="fs-one"/>'
         in fixed),
        ("it is no longer at body level",
         lambda: '<w:bookmarkEnd w:id="1"/><w:p>' in fixed
         and '<w:bookmarkStart w:id="1" w:name="fs-one"/><w:bookmarkEnd'
         not in fixed),
        ("a bookmark before a table stays, for the pre-pass to read",
         lambda: tablecensus.anchors_before(body, tbl) == ["fs-tbl"]),
        ("Word's own _-prefixed bookmarks are not anchors",
         lambda: "_GoBack" not in tablecensus.anchors_before(body, tbl)),
    ]


def check_manifest_names():
    """What a file name with a space does to a manifest."""
    return [
        ("an href percent-encodes a space and escapes the rest",
         lambda: cartridge.href_of("assets/Pipe Sizes & more.png")
         == "assets/Pipe%20Sizes%20%26%20more.png"),
        ("an identifier becomes an XML name",
         lambda: cartridge.ncname("01 BigPicture--a b") == "01-BigPicture--a-b"
         or cartridge.ncname("01 BigPicture--a b") == "p-01-BigPicture--a-b"),
        ("and always starts with a letter",
         lambda: cartridge.ncname("01 Big")[0].isalpha()),
    ]


def check_contrast():
    """Every color page.css sets on text, against the backgrounds it can
    sit on. WCAG 1.4.3 wants 4.5:1; the caption color is chosen to clear
    AAA (7:1). No checker we run measures this on the output, so it is
    measured here, on the stylesheet, where it is decided."""
    css = open(os.path.join(ROOT, "bin", "page.css"), encoding="utf-8").read()
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    colors = re.findall(r"(?<![-\w])color:\s*(#[0-9a-fA-F]{3,6})", css)

    def channel(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    def luminance(hexcolor):
        h = hexcolor.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)

    def ratio(a, b):
        la, lb = sorted((luminance(a), luminance(b)), reverse=True)
        return (la + 0.05) / (lb + 0.05)

    backgrounds = ("#fdfdfd", "#ffffff")     # Pandoc's page, and white
    worst = min((ratio(c, bg) for c in colors for bg in backgrounds),
                default=21)
    return [
        ("page.css sets at least one text color", lambda: bool(colors)),
        ("every text color clears 4.5:1 on Pandoc's background and on white",
         lambda: worst >= 4.5),
        ("the caption color clears 7:1 (AAA)",
         lambda: all(ratio(c, bg) >= 7 for c in colors for bg in backgrounds)),
    ]


def check_matter_by_name():
    """A file name that says where its page belongs."""
    order = bookcontents.guess_contents(
        ["03 Third", "Z1 Glossary", "01 First", "_preamble", "A1 Intro"])
    return [
        ("a leading underscore or a front-matter word goes first, as front",
         lambda: order[0] == {"page": "_preamble", "role": "front"}),
        ("a back-matter word goes last, as back matter",
         lambda: order[-1] == {"page": "Z1 Glossary", "role": "back"}),
        ("everything else keeps its natural order",
         lambda: order[1:-1] == ["01 First", "03 Third", "A1 Intro"]),
    ]


LIST_WRAPPED = ('<table><tr><td><ul><li><img src="x.png" alt="An eye"></li>'
                '</ul></td></tr></table>')
PLAIN_CELL = '<table><tr><td><img src="x.png" alt="An eye"></td></tr></table>'
WITH_TEXT = ('<table><tr><td><ul><li><img src="x.png" alt="An eye"></li>'
             '<li>A caption-like sentence.</li></ul></td></tr></table>')


def check_layout_tables():
    """A one-cell table holding only an image is a figure, whatever the
    export wrapped the image in."""
    def render(markup):
        out = subprocess.run(
            ["pandoc", "-f", "html", "-t", "html",
             "--lua-filter", os.path.join(ROOT, "bin",
                                          "figures-and-tables.lua")],
            input=markup, capture_output=True, text=True)
        return out.stdout
    wrapped, plain, with_text = (render(LIST_WRAPPED), render(PLAIN_CELL),
                                 render(WITH_TEXT))
    return [
        ("a plain image cell becomes a figure",
         lambda: "<figure" in plain and "<table" not in plain),
        ("so does one whose image the export wrapped in a list",
         lambda: "<figure" in wrapped and "<table" not in wrapped),
        ("a cell with anything else in it stays a table",
         lambda: "<table" in with_text),
    ]

DUPLICATE_IDS = ('<h4 id="site-selection">One</h4>'
                 '<p><span id="term-1" class="anchor"></span></p>'
                 '<h4 id="site-selection-1">Two</h4>'
                 '<h4 id="site-selection-1">Three</h4>')


def check_unique_ids():
    """No id twice on a page, and an anchor keeps its name."""
    out = subprocess.run(
        ["pandoc", "-f", "html", "-t", "html", "--lua-filter",
         os.path.join(ROOT, "bin", "figures-and-tables.lua")],
        input=DUPLICATE_IDS, capture_output=True, text=True)
    ids = re.findall(r'id="([^"]*)"', out.stdout)
    return [
        ("every id on the page is unique",
         lambda: len(ids) == len(set(ids))),
        ("the anchor keeps the name another file may link to",
         lambda: "term-1" in ids),
        ("the repeated heading is the one renumbered",
         lambda: ids.count("site-selection-1") == 1
         and "site-selection-2" in ids),
    ]


GROUPS = [
    ("layout tables", check_layout_tables),
    ("unique ids", check_unique_ids),
    ("front and back matter by name", check_matter_by_name),
    ("caption contrast", check_contrast),
    ("manifest names", check_manifest_names),
    ("repairing a .docx on the way in", check_docx_repair),
    ("the archive's name", check_archive_name),
    ("the content prefix", check_content_prefix),
    ("the wrapper module's name", check_wrapper_title),
    ("identifiers", check_identifiers),
    ("facts written down twice", check_consistency),
    ("sidecar paths", check_sidecar_paths),
]


def main():
    failed = 0
    for label, group in GROUPS:
        print(f"{label}:")
        try:
            checks = group()
        except Exception as exc:
            print(f"  ERROR building the checks: {exc}")
            failed += 1
            continue
        for name, predicate in checks:
            try:
                passed = predicate()
            except Exception as exc:
                passed, name = False, f"{name}  ({exc})"
            print(("  ok    " if passed else "  FAIL  ") + name)
            failed += not passed
    if failed:
        extra = undescribed()
        if extra:
            print("\nsettings with no description:")
            for item in extra:
                print("  " + item)
    print(f"\n{failed} failed" if failed else "\nall unit checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
