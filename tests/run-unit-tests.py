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

import atexit
import importlib.util
import subprocess
import os
import csv
import json
import re
import shutil
import struct
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


def scratch(prefix="unit-tests-"):
    """A temporary folder, removed when the suite ends, since some checks
    read it when they're run, after their case has returned."""
    path = tempfile.mkdtemp(prefix=prefix)
    atexit.register(shutil.rmtree, path, ignore_errors=True)
    return path


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
        ("a title that sanitizes to nothing leaves the digest alone",
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
# the page stylesheet's contrast, light and dark
# --------------------------------------------------------------------------

def contrast(a, b):
    """WCAG's contrast ratio of two #rrggbb colors."""
    def luminance(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def expand(color):
    return "#" + "".join(ch * 2 for ch in color[1:]) if len(color) == 4 else color


def check_page_css():
    """Pandoc's background is #fdfdfd, and #1a1a1a in the dark mode its
    3.12 stylesheet follows. page.css is an EPUB's too, whose stylesheet
    leaves the light background to the reading system, white as a rule,
    and gives dark mode #232629. Every color page.css gives text has to
    clear WCAG AA against the background it lands on, in each, and a
    table's row rule 3:1, WCAG's for a line that tells something, but the
    one OpenStax draws hardly seen."""
    import re as _re
    with open(os.path.join(ROOT, "bin", "page.css"), encoding="utf-8") as fh:
        css = _re.sub(r"/\*.*?\*/", "", fh.read(), flags=_re.S)
    screen = css.split("@media print")[0]
    pairs = _re.findall(r"(?<![-\w])color:\s*light-dark\((#[0-9a-fA-F]{3,6}),\s*"
                        r"(#[0-9a-fA-F]{3,6})\)", screen)
    fixed = _re.findall(r"(?<![-\w])color:\s*(#[0-9a-fA-F]{3,6})\s*;", screen)
    outlines = _re.findall(r"outline:[^;]*?(#[0-9a-fA-F]{3,6})", screen)
    # A rule's colors, a table's row rules': OpenStax's gray, and the gray
    # it draws a calculus book's Key Equations in, Grey1, hardly seen.
    rules = _re.findall(r"border[-\w]*:[^;]*?light-dark\((#[0-9a-fA-F]{3,6}),\s*"
                        r"(#[0-9a-fA-F]{3,6})\)", screen)
    backgrounds = (("#fdfdfd", "#1a1a1a"), ("#ffffff", "#232629"))
    return [
        ("each light-dark() color text is given clears 4.5:1 in light and dark mode, a "
         "page's and an EPUB's",
         lambda: pairs and all(contrast(expand(l), light) >= 4.5
                               and contrast(expand(d), dark) >= 4.5
                               for l, d in pairs for light, dark in backgrounds)),
        ("a table's row rule clears 3:1, as a line that tells something does, in both modes, "
         "but the rule OpenStax draws Key Equations with in a calculus book, its Grey1, "
         "hardly seen in either",
         lambda: rules == [("#757474", "#9a9a9a"), ("#f1f1f1", "#2e2e2e")]
         and all(contrast("#757474", light) >= 3 and contrast("#9a9a9a", dark) >= 3
                 and contrast("#f1f1f1", light) < 1.5 and contrast("#2e2e2e", dark) < 1.5
                 for light, dark in backgrounds)),
        ("a fixed text color has a light-dark() form beside it",
         lambda: all(any(expand(c) == expand(l) for l, _ in pairs) for c in fixed)),
        ("no outline is a fixed color that dark mode's background matches",
         lambda: not outlines),
    ]


# Pandoc's class for each of skylighting's token types, as its CSS names them.
TOKEN_CLASSES = {
    "Alert": "al", "Annotation": "an", "Attribute": "at", "BaseN": "bn", "BuiltIn": "bu",
    "ControlFlow": "cf", "Char": "ch", "Constant": "cn", "Comment": "co", "CommentVar": "cv",
    "Documentation": "do", "DataType": "dt", "DecVal": "dv", "Error": "er", "Extension": "ex",
    "Float": "fl", "Function": "fu", "Import": "im", "Information": "in", "Keyword": "kw",
    "Operator": "op", "Other": "ot", "Preprocessor": "pp", "SpecialChar": "sc",
    "SpecialString": "ss", "String": "st", "Variable": "va", "VerbatimString": "vs",
    "Warning": "wa"}


def check_highlighting():
    """The theme every writer highlights code in (lib/highlighting.py)
    clears 4.5:1 on a white page and on Pandoc's #fdfdfd, and page.css
    gives each token the theme's color for light mode, with the dark
    one check_page_css holds to a page's and an EPUB's dark mode."""
    import re as _re
    with open(os.path.join(ROOT, "bin", "highlighting.theme"), encoding="utf-8") as fh:
        theme = json.load(fh)
    colors = {name: style["text-color"] for name, style in theme["text-styles"].items()
              if style.get("text-color")}
    with open(os.path.join(ROOT, "bin", "page.css"), encoding="utf-8") as fh:
        css = _re.sub(r"/\*.*?\*/", "", fh.read(), flags=_re.S).split("@media print")[0]
    pairs = dict(_re.findall(r"code span\.(\w+) \{ color: light-dark\((#[0-9a-f]{6}), #[0-9a-f]{6}\); \}",
                             css))
    numbers = _re.search(r"pre\.numberSource code > span > a:first-child::before \{\s*"
                         r"color: light-dark\((#[0-9a-f]{6}),", css)
    import highlighting
    return [
        ("every token's color, and a line number's, clears 4.5:1 on white and on #fdfdfd",
         lambda: colors and all(contrast(c, page) >= 4.5 for c in
                                list(colors.values()) + [theme["line-number-color"]]
                                for page in ("#ffffff", "#fdfdfd"))),
        ("page.css gives each colored token the theme's color for light mode",
         lambda: all(pairs.get(TOKEN_CLASSES[name]) == color for name, color in colors.items())
         and len(pairs) == len(colors)),
        ("and a line number its color",
         lambda: numbers and numbers.group(1) == theme["line-number-color"]),
        ("the writers are given the theme",
         lambda: highlighting.ARGS == ["--syntax-highlighting="
                                       + os.path.join(ROOT, "bin", "highlighting.theme")]
         and os.path.isfile(highlighting.THEME)),
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
    # The newest release, as the changelog's first dated section, the
    # audit's version, and the installation page's download example
    # name it; the release commit changes all three.
    changelog = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
    released = re.search(r"^## \[(\d+\.\d+)\] - ", changelog, re.M).group(1)
    audit = re.search(r'^VERSION = "([^"]+)"', open(
        os.path.join(ROOT, "bin", "audit.py"), encoding="utf-8").read(), re.M).group(1)
    installation = open(os.path.join(ROOT, "docs", "installation.md"),
                        encoding="utf-8").read()
    named = set(re.findall(r"TextbookImprover-(\d+\.\d+)", installation)
                + re.findall(r"refs/tags/v(\d+\.\d+)\.tar\.gz", installation)
                + re.findall(r"replace `v(\d+\.\d+)`", installation))
    # The oldest Pandoc convert.py takes, which each suite that runs it
    # checks first, as run-all.sh does, so an older one says why.
    pandoc_minimums = set()
    for folder in ("bin", "tests"):
        for name in sorted(os.listdir(os.path.join(ROOT, folder))):
            if name.endswith(".py"):
                text = open(os.path.join(ROOT, folder, name), encoding="utf-8").read()
                pandoc_minimums.update(re.findall(r"\)\[:3\]\) < \((\d+), (\d+)\)", text))
    run_all = open(os.path.join(HERE, "run-all.sh"), encoding="utf-8").read()
    pandoc_minimums.update(tuple(v.split(".")) for v in
                           re.findall(r"!= \"(\d+\.\d+)\" \]", run_all))
    # The page types the filter reads from a heading are the ones the
    # contents vocabulary declares (bookcontents.PAGE_TYPES), which the
    # EPUB writes.
    lua = open(os.path.join(ROOT, "bin", "figures-and-tables.lua"), encoding="utf-8").read()
    lua_types = set()
    for table in ("PAGE_TYPE_CLASSES", "PAGE_TYPE_VALUES"):
        body = re.search(r"local %s = \{(.*?)\n\}" % table, lua, re.S).group(1)
        lua_types.update(re.findall(r"\[?'?([a-z-]+)'?\]?\s*=\s*true", body))
    import bookcontents as contents_lib
    pandoc_checked = {name for name in os.listdir(HERE)
                      if name.startswith("run-") and name.endswith(".py")
                      and ") < (" in open(os.path.join(HERE, name), encoding="utf-8").read()}
    # The least part of its size the PDF's fit sets a table in to fit its
    # line, by which the filter shares a short line among a worked
    # example's steps.
    import latexbuild
    filter_floor = re.search(r"^local FIT_FLOOR = ([\d.]+)", open(
        os.path.join(ROOT, "bin", "pdf-target.lua"), encoding="utf-8").read(), re.M)

    return [
        ("the schema's back-matter default matches the built-in order",
         lambda: list(declared) == builtin),
        ("the newest release is the one the audit reports and the installation page "
         "downloads", lambda: audit == released and named == {released}),
        ("the oldest Pandoc is the same everywhere it's checked, and every suite that runs "
         "convert.py checks it", lambda: len(pandoc_minimums) == 1
         and {"run-convert-tests.py", "run-latex-tests.py", "run-pdf-tests.py",
              "run-unpack-tests.py", "run-epub-tests.py", "run-split-tests.py",
              "run-filter-tests.py", "run-slides-tests.py", "run-decks-tests.py"}
         <= pandoc_checked),
        ("the page types a heading can give are the ones contents can, a tree written back "
         "keeps an entry's type, and a type with no role puts it where it usually is", lambda: lua_types == set(contents_lib.PAGE_TYPES)
         and contents_lib.contents_from_tree(contents_lib.walk_contents(
             [{"page": "a", "type": "glossary"}, {"title": "G", "type": "part", "items": ["b"]}],
             {"a", "b"}, set(), [])) == [{"page": "a", "type": "glossary"},
                                         {"title": "G", "items": ["b"], "type": "part"}]
         and [contents_lib.role_of(e) for e in contents_lib.walk_contents(
             [{"page": "a", "type": "glossary"}, {"page": "b", "type": "glossary", "role": "main"},
              {"page": "c", "type": "appendix"}, "d"], {"a", "b", "c", "d"}, set(), [])]
         == ["back", "main", "appendix", "main"]),
        ("every schema loads and declares its keys",
         lambda: all("keys" in yaml.safe_load(open(p, encoding="utf-8"))
                     for p in (
                         os.path.join(ROOT, "bin", "schema-packaging.yaml"),
                         os.path.join(ROOT, "bin", "schema-conversion.yaml"),
                         os.path.join(ROOT, "lib", "schema-project.yaml")))),
        ("every declared setting has a description",
         lambda: not undescribed()),
        ("the PDF filter's least size for a fit to the line is the build's",
         lambda: filter_floor is not None
         and float(filter_floor.group(1)) == latexbuild.FIT_FLOOR),
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
    base = scratch("sidecar-paths-")

    import contextlib
    import io
    said = []

    nowhere_link = os.path.join(base, "alt-link.csv")
    os.symlink("/nowhere/alt.csv", nowhere_link)
    default_link = os.path.join(base, "bare-links.csv")
    os.symlink("/nowhere/links.csv", default_link)
    noted = []

    def goes_on(path, setting, default):
        """check_sidecar's run going on, what it says caught."""
        saved_say, convert.say = convert.say, noted.append
        try:
            return not stops(path, setting, default)
        finally:
            convert.say = saved_say

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
        ("a setting naming a folder stops the run, saying so, where the check of its "
         "encoding had stopped it with a traceback",
         lambda: stops(base, "sidecars.image_alt", "image-alt.csv")
         and "sidecars.image_alt" in said[-1] and "a folder, not a file" in said[-1]),
        ("a setting naming a link to nothing stops the run as one naming nothing does, saying "
         "where it leads",
         lambda: stops(nowhere_link, "sidecars.image_alt", "image-alt.csv")
         and "which does not exist, a link to /nowhere/alt.csv, which isn't there" in said[-1]),
        ("but at the default name, the run goes on without it, saying so",
         lambda: goes_on(default_link, "sidecars.bare_links", "bare-links.csv")
         and any("bare-links.csv is a link to /nowhere/links.csv, which isn't there, so this "
                 "run goes on without it" in line for line in noted)),
    ]


def check_deck_math_note():
    """The note on math-repaired.csv's form in a run that converts decks:
    its hint says some rows are written out in one line when the copies'
    were (deckrun hands that over in DECK_MATH), and only then. The
    slides suite runs convert.py whole, where Pandoc reads every
    equation, so the hint's other branch is called directly here."""
    import contextlib
    import io
    convert = load(os.path.join(ROOT, "bin", "convert.py"), "convert")
    work = scratch("deck-math-note-")
    report = os.path.join(work, "math-repaired.csv")
    collected = {"math": os.path.join(work, "none"), "math_kept": os.path.join(work, "none")}

    def hint(in_one_line):
        convert.DECK_MATH = {"rows": [("equation", "deck", "z=(x\u2013\u00b5)/\u03c3",
                                       "z=(x\u2212\u03bc)/\u03c3")],
                             "in_one_line": in_one_line}
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            convert.deck_math_report(collected, {"math_repaired": report}, {"math_keep": None},
                                     [], work)
        return err.getvalue()

    written_out, tex = hint(True), hint(False)
    return [
        ("a deck's row written out in one line, the report's hint says so",
         lambda: "Wrote %s (1 math repair(s))." % report in written_out
         and "or written out in one line" in written_out),
        ("and with every row TeX, it doesn't",
         lambda: "Wrote %s (1 math repair(s))." % report in tex
         and "written out in one line" not in tex),
    ]


def check_docx_repair():
    """Bookmarks between blocks move into the block that follows."""
    import xml.etree.ElementTree as ET
    import docxrepair
    import docxremediate
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
        ("a label paragraph past a table's bookmark and an empty paragraph gets its description",
         lambda: (lambda x: "Table 1.1</w:t></w:r><w:r><w:t xml:space=\"preserve\"> A description" in x)(
             docxremediate.remediate_captions(
                 '<w:body><w:bookmarkStart w:id="1" w:name="t1"/><w:tbl><w:tr><w:tc><w:p><w:r><w:t>a'
                 '</w:t></w:r></w:p></w:tc></w:tr></w:tbl><w:bookmarkEnd w:id="1"/><w:p><w:pPr>'
                 '<w:spacing/></w:pPr></w:p><w:p><w:r><w:t>Table 1.1</w:t></w:r></w:p></w:body>',
                 [(0, "label-after", "Table 1.1", "A description")], [])[0])),
        ("a bookmark opening a paragraph after a heading stays in that paragraph",
         lambda: (lambda f: re.search(r'<w:pStyle w:val="SourceCode"/></w:pPr>'
                                      r'(?:<w:r><w:t>&#8203;</w:t></w:r>)?<w:bookmarkStart w:id="7" '
                                      r'w:name="code-7"/>', f) and f.count("code-7") == 1)(
                      docxrepair.move_bookmarks_into_paragraphs(
                          '<w:document xmlns:w="%s"><w:body><w:p><w:pPr>'
                          '<w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Heading</w:t></w:r></w:p>'
                          '<w:p><w:pPr><w:pStyle w:val="BodyText"/></w:pPr><w:r><w:t>Text'
                          '</w:t></w:r></w:p><w:p><w:pPr><w:pStyle w:val="SourceCode"/></w:pPr>'
                          '<w:bookmarkStart w:id="7" w:name="code-7"/><w:r><w:t>x = 1</w:t>'
                          '</w:r></w:p></w:body></w:document>' % W)[0])),
        ("bookmarks no link in the document points at get a keeper link",
         lambda: count == 2 and 'w:anchor="fs-one"' in kept
         and 'w:anchor="fs-tbl"' in kept),
        ("a bookmark already linked, or Word's own, gets none",
         lambda: 'w:anchor="_GoBack"' not in kept
         and docxrepair.keep_unlinked_bookmarks(heading)[1] == 0),
        ("one bookmark moved, the one before a paragraph",
         lambda: moved == 1),
        ("it sits after the paragraph's properties, a zero-width run keeping it apart",
         lambda: '</w:pPr><w:r><w:t>&#8203;</w:t></w:r><w:bookmarkStart w:id="1" w:name="fs-one"/>'
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


# A list's numbering as Pandoc's writer writes it: 1000 the list of no
# marker (baseListId), its marker a blank, and 1001 a bulleted list, each
# level's text a step of 720 further in.
LIST_NUMBERING = (
    '<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    + "".join('<w:abstractNum w:abstractNumId="%d">%s</w:abstractNum>' % (n, "".join(
        '<w:lvl w:ilvl="%d"><w:numFmt w:val="bullet"/><w:lvlText w:val="%s"/>'
        '<w:pPr><w:ind w:left="%d" w:hanging="360"/></w:pPr></w:lvl>'
        % (level, marker, 720 * (level + 1)) for level in range(3)))
        for n, marker in ((990, " "), (991, "•")))
    + '<w:num w:numId="1000"><w:abstractNumId w:val="990"/></w:num>'
    '<w:num w:numId="1001"><w:abstractNumId w:val="991"/></w:num></w:numbering>')
LIST_STYLES = ('<w:styles><w:style w:type="paragraph" w:styleId="BodyText"><w:name w:val="Body Text"/>'
               '</w:style><w:style w:type="paragraph" w:styleId="ListContinue">'
               '<w:basedOn w:val="ListContinueBase"/></w:style>'
               '<w:style w:type="paragraph" w:styleId="ListContinueBase"><w:pPr>'
               '<w:ind w:left="720"/></w:pPr></w:style></w:styles>')


def list_paragraph(text, style="BodyText", number=None, indent=None):
    """A paragraph as Pandoc's writer writes one: its style, its numbering
    (numId, ilvl), and its own w:ind's attributes."""
    props = '<w:pStyle w:val="%s"/>' % style
    if number:
        props += '<w:numPr><w:ilvl w:val="%s"/><w:numId w:val="%s"/></w:numPr>' % (number[1],
                                                                                  number[0])
    if indent:
        props += "<w:ind %s/>" % indent
    return '<w:p><w:pPr>%s</w:pPr><w:r><w:t>%s</w:t></w:r></w:p>' % (props, text)


def quote_list_item(text, left):
    """A list's item in a quote as the Word target writes it, moved a
    quote step in."""
    return list_paragraph(text, "BodyText", ("1001", "0"), 'w:left="%d" w:hanging="360"' % left)


def check_list_continuations():
    """A list item's later paragraphs as Pandoc's writer sets them from
    3.13 on, unnumbered and lined up with the item's text, and its reader
    reads them: what the Word target does with its own in that form, and
    what reading a file it wrote does before the reader gets it."""
    import zipfile
    import docxrepair
    import docxtarget
    item = lambda text, level=0, indent=None: list_paragraph(
        text, "FirstParagraph", ("1001", str(level)), indent)
    later = lambda text, left, style="BodyText", extra="": list_paragraph(
        text, style, None, 'w:left="%d"%s w:firstLine="0"' % (left, extra))
    table = ('<w:tbl><w:tr><w:tc><w:p/></w:tc><w:tc>%s</w:tc></w:tr></w:tbl>'
             % list_paragraph("cell", "Compact"))
    rule = ('<w:p><w:r><w:pict><v:rect style="width:0;height:1.5pt" o:hralign="center" '
            'o:hrstd="t" o:hr="t" /></w:pict></w:r></w:p>')
    body = (item("A") + later("A1", 720) + item("B", 1) + later("B1", 1440) + later("A2", 720)
            + later("Q", 1200, "BlockText", ' w:right="480"') + table + later("A3", 720)
            + item("C") + later("C1", 720) + rule + later("X", 720)
            + item("D") + list_paragraph("D1", "ListContinue")
            + list_paragraph("D2", "Heading2", None, 'w:left="720" w:firstLine="0"')
            + later("Y", 720) + item("E") + list_paragraph("", "BodyText") + later("Z", 720)
            + item("F") + '<w:p/>' + later("W", 720))

    def found(xml, quoted, held=()):
        return [("".join(re.findall(r"<w:t>([^<]*)</w:t>", xml[s:e])), level, text, inside, after)
                for s, e, level, text, inside, after in docxrepair.item_paragraphs(
                    xml, LIST_NUMBERING, LIST_STYLES, quoted, held)]
    marked, marks = docxrepair.mark_continuations(body, LIST_NUMBERING, LIST_STYLES, True,
                                                  {("t", 0)})
    unmarked, _ = docxrepair.mark_continuations(body, LIST_NUMBERING, LIST_STYLES, True,
                                                {("t", 0)}, marks=False)
    everyone, _ = docxrepair.mark_continuations(body, LIST_NUMBERING, LIST_STYLES, True,
                                                {("t", 0)}, every=True)
    paragraph_of = lambda xml, text: next(p for p in re.findall(r"<w:p>.*?</w:p>", xml)
                                          if "<w:t>%s</w:t>" % text in p)
    # The Word target: a formula in an item, and quotes and lists in each
    # other, as the writer sets an item's later paragraphs from 3.13 on.
    formula = ('<w:bookmarkStart w:id="5" w:name="tiqMath1d1"/><w:p><w:pPr>'
               '<w:pStyle w:val="FirstParagraph"/></w:pPr><m:oMathPara/></w:p>'
               '<w:bookmarkEnd w:id="5"/>')
    quote = lambda inner, n: ('<w:bookmarkStart w:id="%d" w:name="tiqQuote%d"/>%s'
                              '<w:bookmarkEnd w:id="%d"/>' % (900 + n, n, inner, 900 + n))
    levels = docxtarget.level_indents(LIST_NUMBERING)
    blanks = docxtarget.level_indents(LIST_NUMBERING, blank=True)
    in_item, _, in_item_items = docxtarget.indent_quotes(
        item("item") + quote(later("in its quote", 720, "BlockText"), 1), levels, blanks)
    # The writer styles every paragraph in a quote Block Text, a list's
    # items too.
    quoted_item = lambda text: list_paragraph(text, "BlockText", ("1001", "0"))
    quoted_list, _, _ = docxtarget.indent_quotes(quote(
        quoted_item("quoted item") + later("its next paragraph", 720, "BlockText")
        + later("its code", 720, "SourceCode"), 2), levels, blanks)
    # A quoted list, then one outside every quote whose item holds a quote:
    # the second list's isn't the first's depth.
    after_quoted, _, _ = docxtarget.indent_quotes(
        quote(quoted_item("quoted item"), 3) + item("plain item")
        + quote(later("plain item's quote", 720, "BlockText"), 4), levels, blanks)
    settings = ('<w:settings><w:compat><w:compatSetting w:name="compatibilityMode"/></w:compat>'
                "</w:settings>")
    both = docxtarget.continuations_var(docxtarget.quoted_lists_var(settings))
    # What quoted_code finds in a file the target wrote, the code's quote
    # depth beyond its item's text.
    work = tempfile.mkdtemp()
    code_body = (item("one") + later("Load it:", 1200, "BlockText", ' w:right="480"')
                 + later("include csv", 1200, "SourceCode")
                 + quote_list_item("quoted", 1200) + later("acct1", 1200, "SourceCode"))

    def code_file(name, settings_xml):
        path = os.path.join(work, name)
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("word/document.xml", '<w:document><w:body>%s</w:body></w:document>'
                       % code_body)
            z.writestr("word/numbering.xml", LIST_NUMBERING)
            z.writestr("word/styles.xml", LIST_STYLES)
            z.writestr("word/settings.xml", settings_xml)
        return path
    indented_code = docxrepair.quoted_code(code_file("indented.docx", both))
    numbered_code = docxrepair.quoted_code(code_file(
        "numbered.docx", docxtarget.quoted_lists_var(settings)))
    # Code in a quote in a quote after a table its item holds.
    code_body = (item("one") + table + later("Outer:", 1200, "BlockText", ' w:right="480"')
                 + later("Inner:", 1680, "BlockText", ' w:right="480"')
                 + later("two deep", 1680, "SourceCode"))
    held_code_path = code_file("held.docx", both)
    with zipfile.ZipFile(held_code_path, "a") as z:
        z.writestr("customXml/item1.xml", '<ids xmlns="https://github.com/OERforge/TextbookImprover/'
                   'ids"><listBlock kind="t" n="0" follow="3" continues="0"/></ids>')
    held_code = docxrepair.quoted_code(held_code_path)
    # A file the target wrote, as reading it gets it ready for the reader.
    repaired = os.path.join(work, "repaired.docx")
    source = os.path.join(work, "source.docx")
    with zipfile.ZipFile(source, "w") as z:
        z.writestr("word/document.xml", '<w:document><w:body>%s</w:body></w:document>' % body)
        z.writestr("word/numbering.xml", LIST_NUMBERING)
        z.writestr("word/styles.xml", LIST_STYLES)
        z.writestr("word/settings.xml", both)
        z.writestr("customXml/item1.xml", '<ids xmlns="https://github.com/OERforge/TextbookImprover/'
                   'ids"><listBlock kind="t" n="0" follow="1" continues="1"/></ids>')
        # A note holding a list, its item's later paragraph in the
        # writer's form.
        z.writestr("word/footnotes.xml", '<w:footnotes><w:footnote w:id="2">%s</w:footnote>'
                   '</w:footnotes>' % (item("note's item") + later("note's later", 720)))

    def repaired_for(version, part="word/document.xml"):
        """The copy reading makes of source for a reader of the Pandoc
        version given: the part named."""
        saved = docxtarget.pandoc_version
        docxtarget.pandoc_version = lambda: version
        try:
            docxrepair.repaired_copy(source, repaired)
        finally:
            docxtarget.pandoc_version = saved
        with zipfile.ZipFile(repaired) as z:
            return z.read(part).decode("utf-8")
    repaired_xml = repaired_for((3, 13))
    repaired_old = repaired_for((3, 12, 1))
    notes_xml = repaired_for((3, 13), "word/footnotes.xml")
    notes_old = repaired_for((3, 12, 1), "word/footnotes.xml")
    # Figures, a picture's paragraph (Captioned Figure, unnumbered, so the
    # reader pairs it with its caption) and its caption, as the writer sets
    # one in an item from 3.13 on: one before the list, one an item holds
    # (the body's second), one in a table's cell, one an item opens
    # (numbered), and one no item holds, which ends the list.
    picture = lambda left, extra="": (
        '<w:p><w:pPr><w:pStyle w:val="CaptionedFigure"/>%s%s</w:pPr><w:r><w:drawing>'
        '<wp:inline/></w:drawing></w:r></w:p>'
        % (extra, '<w:ind w:left="%d" w:firstLine="0"/>' % left if left else ""))
    figure_caption = lambda text, left: list_paragraph(
        text, "ImageCaption", None, 'w:left="%d" w:firstLine="0"' % left if left else None)
    figures_body = (picture(0) + figure_caption("before", 0)
                    + item("G") + picture(720) + figure_caption("in G", 720) + later("G1", 720)
                    + item("H") + later("H1", 720)
                    + '<w:tbl><w:tr><w:tc>%s</w:tc></w:tr></w:tbl>' % (picture(0) + figure_caption(
                        "in a cell", 0))
                    + item("J") + picture(0, '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1001"/>'
                                             '</w:numPr>') + figure_caption("J's", 720)
                    + later("J1", 720)
                    + item("K") + picture(720) + figure_caption("in K", 720) + later("K1", 720))
    figures_held = {("f", 1)}
    figures_marked, _ = docxrepair.mark_continuations(figures_body, LIST_NUMBERING, LIST_STYLES,
                                                      False, figures_held)
    # The target's count, by the mark before a figure an item holds, after
    # a figure no list holds, one in a table's cell, and one a numbered
    # picture opens, which the reader doesn't pair with its caption.
    figures_target, figures_listed = docxtarget.item_tables(
        picture(0) + figure_caption("before", 0)
        + '<w:tbl><w:tr><w:tc>%s</w:tc></w:tr></w:tbl>' % (picture(0) + figure_caption(
            "in a cell", 0))
        + item("J") + picture(0, '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1001"/>'
                                 '</w:numPr>') + figure_caption("J's", 720)
        + item("G") + '<w:bookmarkStart w:id="7" w:name="%s1kff1c1"/>' % docxtarget.ITEM_TABLE_MARK
        + picture(720) + '<w:bookmarkEnd w:id="7"/>' + figure_caption("in G", 720))
    # And the figure put back in its item after the reader, which ends the
    # list at it: a list, the figure, the item's paragraph after it, and the
    # list begun again.
    para = lambda text: {"t": "Para", "c": [{"t": "Str", "c": text}]}
    read_back = {"pandoc-api-version": [1, 23, 1], "meta": {}, "blocks": [
        {"t": "Figure", "c": [["", [], []], [None, [para("before")]], [para("picture")]]},
        {"t": "OrderedList", "c": [[1, {"t": "Decimal"}, {"t": "Period"}], [[para("G")]]]},
        {"t": "Figure", "c": [["", [], []], [None, [para("in G")]], [para("picture")]]},
        para("G1"),
        {"t": "OrderedList", "c": [[2, {"t": "Decimal"}, {"t": "Period"}], [[para("H")]]]}]}
    figure_docx = os.path.join(work, "figure.docx")
    figure_json = os.path.join(work, "figure.json")
    with zipfile.ZipFile(figure_docx, "w") as z:
        z.writestr("customXml/item1.xml", '<ids xmlns="https://github.com/OERforge/TextbookImprover/'
                   'ids"><listBlock kind="f" n="1" follow="1" continues="1"/></ids>')
    with open(figure_json, "w", encoding="utf-8") as fh:
        json.dump(read_back, fh)
    figures_moved = docxrepair.apply_list_tables(figure_docx, figure_json)
    with open(figure_json, encoding="utf-8") as fh:
        figures_put_back = json.load(fh)["blocks"]
    # An item the writer numbers nowhere, one that opens with an anchor
    # before a list, its words after the list lined up with its text, no
    # level of the reader's theirs; and a table's caption in a tight list's item style,
    # before a table the item holds.
    orphan_body = (item("a") + table + item("i", 1) + item("ii", 1) + later("b's words", 720)
                   + item("c"))
    caption_body = (item("x") + list_paragraph("Table 1", "Compact") + table
                    + later("x after", 720) + item("y"))
    caption_quote = (item("x") + list_paragraph("Table 1", "Compact") + table
                     + later("quote after", 1200, "BlockText", ' w:right="480"'))

    def put_back(blocks, marks):
        """blocks after the reader, given the target's listBlock marks, as
        apply_list_tables leaves them."""
        with zipfile.ZipFile(figure_docx, "w") as z:
            z.writestr("customXml/item1.xml", '<ids xmlns="https://github.com/OERforge/'
                       'TextbookImprover/ids">%s</ids>' % "".join(
                           '<listBlock kind="%s" n="%d" follow="%d" continues="%s"/>' % m
                           for m in marks))
        with open(figure_json, "w", encoding="utf-8") as fh:
            json.dump(dict(read_back, blocks=blocks), fh)
        docxrepair.apply_list_tables(figure_docx, figure_json)
        with open(figure_json, encoding="utf-8") as fh:
            return json.load(fh)["blocks"]
    alpha = lambda start, entries: {"t": "OrderedList", "c": [
        [start, {"t": "LowerAlpha"}, {"t": "Period"}], entries]}
    table_block = {"t": "Table", "c": [["", [], []], [None, []], [], ["", [], []], [],
                                       ["", [], []]]}
    caption_put_back = put_back([alpha(1, [[para("x")]]), para("Table 1"), table_block,
                                 para("x after"), alpha(2, [[para("y")]])], [("t", 0, 1, "1")])
    figure = {"t": "Figure", "c": [["", [], []], [None, []], [para("picture")]]}
    roman = {"t": "OrderedList", "c": [[1, {"t": "LowerRoman"}, {"t": "Period"}],
                                       [[para("i")], [para("ii")]]]}
    nested_put_back = put_back([alpha(1, [[para("a")]]), figure, roman, alpha(3, [[para("c")]])],
                               [("f", 0, 0, "1")])
    # A table's caption the reader gave it from w:tblCaption, its words the
    # paragraph's before it: the paragraph becomes the caption.
    captioned_table = json.loads(json.dumps(table_block))
    captioned_table["c"][1] = [None, [{"t": "Plain", "c": [{"t": "Str", "c": "Table"},
                                                           {"t": "Space"},
                                                           {"t": "Str", "c": "1"}]}]]
    caption_words = {"t": "Para", "c": [{"t": "Emph", "c": [{"t": "Str", "c": "Table"}]},
                                         {"t": "Space"}, {"t": "Str", "c": "1"}]}
    caption_merged = put_back([alpha(1, [[para("x")]]), caption_words, captioned_table,
                               para("x after"), alpha(2, [[para("y")]])], [("t", 0, 1, "1")])
    # What the reader does that ends a list, mirrored: a rule an item
    # holds; a note, whose paragraphs end every list where its reference
    # is, the item's paragraphs before it then list paragraphs too, with
    # no indent; a deeper item's list ended by an item outside it; a
    # quote off the quote step; a picture with a bookmark or a caption that
    # keeps with the next, which the reader doesn't pair; a caption after
    # a table, which it does; a quote or a paragraph with an indent of its
    # own before a table an item holds, which is no caption; the reader's
    # lists ended by a table an item holds, an inner item opening again
    # after it; and a list in a table's cell.
    note = lambda paragraph: paragraph.replace(
        "</w:p>", '<w:r><w:footnoteReference w:id="2"/></w:r></w:p>')
    rule_body = item("r") + rule + later("after the rule", 720)
    note_body = (note(item("n")) + later("n1", 720) + item("m") + later("m1", 720)
                 + note(later("m2", 720)) + later("m3", 720) + item("o"))
    note_marked, _ = docxrepair.mark_continuations(note_body, LIST_NUMBERING, LIST_STYLES)
    deeper_body = item("a") + item("b", 1) + item("c") + later("c deep", 1440)
    off_step = item("s") + later("off the step", 960, "BlockText")
    bookmarked = lambda left: picture(left).replace(
        "<w:r><w:drawing>", '<w:bookmarkStart w:id="9" w:name="fig"/><w:r><w:drawing>')
    kept_caption = lambda text: list_paragraph(text, "ImageCaption", None,
                                               'w:left="720" w:firstLine="0"').replace(
        "</w:pPr>", "<w:keepNext/></w:pPr>")
    unpaired_body = (item("p") + bookmarked(720) + figure_caption("its caption", 720)
                     + later("p1", 720) + item("k") + picture(720) + kept_caption("kept")
                     + later("k1", 720))
    after_table = item("v") + table + figure_caption("the table's", 720) + later("v1", 720)
    after_marked, _ = docxrepair.mark_continuations(after_table, LIST_NUMBERING, LIST_STYLES,
                                                    False, {("t", 0)})
    no_caption = (item("t") + later("quote before", 1200, "BlockText") + table
                  + later("t1", 720) + item("u") + list_paragraph("own", "Compact", None,
                                                                  'w:left="360"')
                  + table + later("u1", 720))
    reopened = item("A") + item("B", 1) + table + item("C", 1) + later("A after", 720)
    orphan_after = (item("a") + table + item("i", 1) + later("b1", 720) + later("b2", 720)
                    + later("b's quote", 1200, "BlockText"))
    cell_list = ("<w:tbl><w:tr><w:tc>%s</w:tc></w:tr></w:tbl>"
                 % (item("in a cell") + later("the cell's later", 720)))
    cell_every, _ = docxrepair.mark_continuations(cell_list, LIST_NUMBERING, LIST_STYLES,
                                                  every=True)
    cell_kept, _ = docxrepair.mark_continuations(cell_list, LIST_NUMBERING, LIST_STYLES)
    # The target: which figures it holds, a mark around a figure the reader
    # makes none of left out, and a table's caption in its own style.
    image = lambda: {"t": "Image", "c": [["", [], []], [], ["a.png", ""]]}
    lone = lambda caption: {"t": "Figure", "c": [["", [], []], [None, caption],
                                                [{"t": "Plain", "c": [image()]}]]}
    two = {"t": "Figure", "c": [["", [], []], [None, [para("two")]],
                                [{"t": "Plain", "c": [image(), {"t": "Space"}, image()]}]]}
    uncaptioned = ('<w:p><w:pPr><w:pStyle w:val="Figure"/><w:ind w:left="720" w:firstLine="0"/>'
                   '</w:pPr><w:r><w:drawing><wp:inline/></w:drawing></w:r></w:p>')
    _, stray_listed = docxtarget.item_tables(
        item("G") + '<w:bookmarkStart w:id="7" w:name="%s1kff1c1"/>' % docxtarget.ITEM_TABLE_MARK
        + uncaptioned + '<w:bookmarkEnd w:id="7"/>' + later("G1", 720) + picture(0)
        + figure_caption("a figure outside the list", 0))
    compact_caption = lambda text: list_paragraph(text, "Compact")
    plain_table = "<w:tbl><w:tr><w:tc><w:p/></w:tc></w:tr></w:tbl>"
    marked_table = lambda n, inner: ('<w:bookmarkStart w:id="%d" w:name="%s%d"/>%s'
                                     '<w:bookmarkEnd w:id="%d"/>'
                                     % (300 + n, docxtarget.TABLE_MARK, n, inner, 300 + n))
    restyled, restyled_count = docxtarget.table_captions(
        marked_table(1, compact_caption("Prices &amp; costs")
                     + '<w:p><w:pPr><w:pStyle w:val="Compact"/></w:pPr><m:oMath/></w:p>'
                     + plain_table)
        + compact_caption("Something else") + plain_table
        + marked_table(2, compact_caption("A mark with no table"))
        + compact_caption("A tight list's item") + plain_table)
    quoted_doc = {"blocks": [{"t": "BlockQuote", "c": [{"t": "Para", "c": [
        {"t": "Span", "c": [["tiqItemQuote1x1", [], []], []]}, {"t": "Str", "c": "Q"}]}]}]}
    quote_marks = docxrepair.nest_item_quotes(quoted_doc)
    # An outer item's paragraph holding a note after its list: a
    # continuation the reader keeps, which a list paragraph would not be.
    note_after = (item("A") + item("B", 1) + note(later("A2", 720)) + later("A3", 720))
    # What the reader gives back after a held block: a paragraph after a
    # list folds into the list's last item, up to a block that isn't one.
    plain = lambda text: {"t": "Plain", "c": [{"t": "Str", "c": text}]}
    bullets = {"t": "BulletList", "c": [[plain("x")]]}
    heading = {"t": "Header", "c": [3, ["", [], []], [{"t": "Str", "c": "h"}]]}
    # A list whose item holds a table is the parts the reader splits it
    # into, and a paragraph after a table, at any depth, folds into
    # nothing; one after a list begun again after it folds into that.
    ends_held = {"t": "BulletList", "c": [[plain("x"), table_block, para("after")]]}
    deep_held = {"t": "BulletList", "c": [[plain("x"), {"t": "BulletList", "c": [
        [plain("y"), table_block]]}]]}
    held_then_list = {"t": "BulletList", "c": [[plain("x"), table_block, bullets]]}
    two_items = {"t": "BulletList", "c": [[plain("x"), table_block], [plain("x2")]]}
    in_divs = {"t": "Div", "c": [["", ["box"], []], [para("one"), para("two")]]}
    # An item that opens with a table, which the target gives a paragraph
    # for its number first (_number_anchored): an item, then the table.
    table_first = {"t": "BulletList", "c": [[table_block, para("p")], [plain("q")]]}
    other_list = {"t": "BulletList", "c": [[plain("z")]]}
    read_back_counts = [docxtarget._read_back(blocks, True) for blocks in (
        [para("p"), bullets, para("q"), para("r")],
        [bullets, para("q"), table_block, para("s")],
        [bullets, heading, para("t")],
        [ends_held, para("u")], [deep_held, para("v")], [held_then_list, para("w")],
        [two_items, para("y")], [in_divs], [{"t": "Div", "c": [["a0", [], []], []]}, para("a")],
        [table_first, para("r")], [bullets, other_list])] + [
        docxtarget._read_back([bullets, json.loads(json.dumps(two)), para("s")], False)]
    # An item that opens with anchors before a list gets a paragraph for its
    # number; one with words after its anchors doesn't need one.
    anchor_div = lambda name: {"t": "Div", "c": [[name, [], []], []]}
    anchored = [anchor_div("a1"), anchor_div("a2"), bullets]
    worded = [anchor_div("a3"), para("words"), bullets]
    anchored_counts = (docxtarget._number_anchored(anchored), docxtarget._number_anchored(worded))
    # And one that opens with a table, alone in a div too, gets an empty
    # paragraph first, as the writer gives one that opens with a list.
    tabled = [{"t": "Div", "c": [["", ["table-wrapper"], []], [table_block]]}, para("after")]
    tabled_count = docxtarget._number_anchored(tabled)
    ruled = [{"t": "HorizontalRule"}, para("after")]
    ruled_count = docxtarget._number_anchored(ruled)
    pictured = [json.loads(json.dumps(two)), para("after")]
    pictured_count = docxtarget._number_anchored(pictured)
    # A formula alone in a Plain, or in a span, is a display paragraph too.
    display = {"t": "Math", "c": [{"t": "DisplayMath"}, "x"]}
    plain_math = {"t": "Plain", "c": [display]}
    span_math = {"t": "Para", "c": [{"t": "Span", "c": [["eq", [], []], [display]]}]}
    split_plain = docxtarget._split_display({"t": "Plain", "c": [{"t": "Str", "c": "so"}, {"t": "Space"},
                                                                 display]})
    # The target's count of figures as reading will have the file: a
    # bookmark in a picture's paragraph moved into its caption, as reading
    # moves one, so the reader pairs it.
    bookmarked_count = docxtarget.item_tables(
        "<w:body>" + bookmarked(0) + figure_caption("bookmarked", 0) + item("G")
        + '<w:bookmarkStart w:id="7" w:name="%s1kff0c0"/>' % docxtarget.ITEM_TABLE_MARK
        + picture(720) + '<w:bookmarkEnd w:id="7"/>' + figure_caption("in G", 720) + "</w:body>")[1]
    # After the reader: an outer item's table takes back its blocks after
    # it as the reader gave them back, the parts of the list it holds among
    # them, and then an inner item's goes back in the part before it; and
    # blocks the reader made more of than the count, before the list begun
    # again, the item's.
    nested_blocks = [alpha(1, [[para("one")]]), table_block, para("after one's table"),
                     {"t": "BulletList", "c": [[para("sub")]]}, table_block, para("after sub's"),
                     {"t": "BulletList", "c": [[para("sub two")]]}, alpha(2, [[para("two")]])]
    nested_back = put_back(nested_blocks, [("t", 0, 5, "1"), ("t", 1, 1, "11")])
    leftover_back = put_back([alpha(1, [[para("x")]]), table_block, para("y"), para("extra"),
                              alpha(2, [[para("z")]])], [("t", 0, 1, "1")])
    # A table the outer item holds after its list, which the outer item's
    # table took back with its blocks, stays where it is; the outer item's
    # blocks are back in it where its list doesn't go on, which no block
    # left over would mend; and an inner item's table after a list that
    # item holds goes back in that item, not in the list's.
    placed_back = put_back([alpha(1, [[para("one")]]), table_block,
                            {"t": "BulletList", "c": [[para("sub")]]}, table_block,
                            {"t": "BulletList", "c": [[para("sub two")]]}, table_block,
                            para("after the third"), alpha(2, [[para("two")]])],
                           [("t", 0, 5, "1"), ("t", 1, 0, "11"), ("t", 2, 1, "1")])
    last_back = put_back([alpha(1, [[para("one")]]), table_block,
                          {"t": "BulletList", "c": [[para("sub")]]}, table_block,
                          para("after sub's"), para("one's after its list")],
                         [("t", 0, 4, "0"), ("t", 1, 1, "00")])
    walk_back = put_back([alpha(1, [[para("one")]]), table_block,
                          {"t": "BulletList", "c": [[para("sub"), {"t": "BulletList", "c": [
                              [para("sub-sub")]]}]]}, table_block, para("after sub's"),
                          alpha(2, [[para("two")]])],
                         [("t", 0, 3, "1"), ("t", 1, 1, "10")])
    shutil.rmtree(work, ignore_errors=True)
    return [
        ("an item's later paragraph lined up with its text continues it, the lists inside it "
         "ended, as Pandoc's reader from 3.13 has it; one beyond the text, a quote's, only in a "
         "file the target wrote, by a quote step; a table the item holds keeps the list, its "
         "paragraphs after it flagged, to the item's end",
         lambda: found(body, True, {("t", 0)})[:6] == [
             ("A1", ("1001", "0"), 720, 0, False), ("B1", ("1001", "1"), 1440, 0, False),
             ("A2", ("1001", "0"), 720, 0, False), ("Q", ("1001", "0"), 720, 1, False),
             ("A3", ("1001", "0"), 720, 0, True), ("C1", ("1001", "0"), 720, 0, False)]),
        ("a rule, a heading, an empty paragraph, and a table no item holds end the lists, and an "
         "item's paragraph after one, in the writer's form, which the reader would take for a "
         "quotation, is a list paragraph at the level its indent names, as the writer before "
         "3.13 numbered it; a style's indent counts as the paragraph's own",
         lambda: [(f[0], f[1], f[4]) for f in found(body, True, {("t", 0)})] == [
             ("A1", ("1001", "0"), False), ("B1", ("1001", "1"), False),
             ("A2", ("1001", "0"), False), ("Q", ("1001", "0"), False),
             ("A3", ("1001", "0"), True), ("C1", ("1001", "0"), False), ("X", (None, "0"), True),
             ("D1", ("1001", "0"), False), ("Y", (None, "0"), True), ("Z", (None, "0"), True),
             ("W", (None, "0"), True)]
         and [(f[0], f[1]) for f in found(body, True)][4] == ("A3", (None, "0"))),
        ("in a file without quoted lists, a quote's paragraph beyond the item's text ends the "
         "list, as the reader takes it, and isn't the item's",
         lambda: [f[0] for f in found(body, False, {("t", 0)})] == [
             "A1", "B1", "A2", "A3", "C1", "X", "D1", "Y", "Z", "W"]),
        ("reading a file the target wrote, a quote's paragraph in an item is lined up with the "
         "item's text, marked with its depth for nest_item_quotes, and the item's paragraph after "
         "its table numbered as a list paragraph; the rest as they were",
         lambda: marks == 6
         and re.search(r'<w:ind w:left="720" w:right="480" w:firstLine="0"/></w:pPr>'
                       r'<w:r><w:t>&#8203;</w:t></w:r><w:bookmarkStart w:id="\d+" '
                       r'w:name="tiqItemQuote1x1"/>', paragraph_of(marked, "Q"))
         and all('<w:numPr><w:ilvl w:val="0"/><w:numId w:val="4000000"/></w:numPr>'
                 in paragraph_of(marked, t) for t in ("A3", "X", "Y", "Z", "W"))
         and all(paragraph_of(marked, t) == paragraph_of(body, t) for t in ("A1", "B1", "C1", "D1"))),
        ("for a reader before 3.13, which would read each as a quote, every item's later "
         "paragraph is a list paragraph, the paragraphs that aren't one as they were",
         lambda: all('<w:numPr><w:ilvl w:val="%s"/><w:numId w:val="4000000"/></w:numPr>'
                     % level in paragraph_of(everyone, t)
                     for t, level in (("A1", 0), ("B1", 1), ("A2", 0), ("Q", 0), ("A3", 0),
                                      ("C1", 0), ("D1", 0)))
         and "tiqItemQuote1x" in paragraph_of(everyone, "Q")
         and all(paragraph_of(everyone, t) == paragraph_of(body, t) for t in ("C", "D2", "cell"))),
        ("in the notes, the quote is lined up but not marked",
         lambda: "tiqItemQuote" not in unmarked
         and '<w:ind w:left="720" w:right="480" w:firstLine="0"/>' in paragraph_of(unmarked, "Q")),
        ("the writer's later paragraph is unnumbered and indented with a first line of 0; "
         "nothing else is one",
         lambda: docxtarget.continuation_left(later("x", 1440)) == 1440
         and docxtarget.continuation_left(item("x")) is None
         and docxtarget.continuation_left(list_paragraph("x", "BodyText", None,
                                                         'w:left="720" w:hanging="360"')) is None
         and docxtarget.continuation_left(list_paragraph("x", "BodyText", None,
                                                         'w:left="720"')) is None),
        ("a formula in an item's later paragraph is lined up with the item's text, unnumbered, "
         "where the writer indents an item's later paragraphs, and numbered with no marker where "
         "it numbers them",
         lambda: docxtarget.list_math(formula, True) == (
             '<w:p><w:pPr><w:pStyle w:val="FirstParagraph"/><w:ind w:left="1440" '
             'w:firstLine="0" /></w:pPr><m:oMathPara/></w:p>', 1)
         and docxtarget.list_math(formula, False) == (
             '<w:p><w:pPr><w:pStyle w:val="FirstParagraph"/><w:numPr><w:ilvl w:val="1" />'
             '<w:numId w:val="1000" /></w:numPr></w:pPr><m:oMathPara/></w:p>', 1)),
        ("a quote in an item stands a quote step beyond the item's text, counted for the "
         "file's variable",
         lambda: '<w:ind w:left="1200" w:right="480" w:firstLine="0" />' in in_item
         and in_item_items == 1),
        ("a list in a quote: the item a quote step in, its later paragraph lined up with it in "
         "Body Text, its code too",
         lambda: '<w:pStyle w:val="BodyText"/><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1001"/>'
         '</w:numPr><w:ind w:left="1200" w:hanging="360" />' in quoted_list
         and '<w:pStyle w:val="BodyText"/><w:ind w:left="1200" w:firstLine="0" /></w:pPr><w:r>'
         '<w:t>its next paragraph' in quoted_list
         and '<w:pStyle w:val="SourceCode"/><w:ind w:left="1200" w:firstLine="0" /></w:pPr><w:r>'
         '<w:t>its code' in quoted_list),
        ("a list outside every quote isn't the quoted list's before it",
         lambda: '<w:pStyle w:val="BlockText"/><w:ind w:left="1200" w:right="480" '
         'w:firstLine="0" /></w:pPr><w:r><w:t>plain item' in after_quoted),
        ("a file says its lists' later paragraphs are indented beside its quoted lists, once",
         lambda: both.count("<w:docVars>") == 1
         and '<w:docVar w:name="TextbookImproverContinuations" w:val="indent"/>' in both
         and '<w:docVar w:name="TextbookImproverQuotedLists" w:val="480"/>' in both
         and docxtarget.continuations_var(both) == both),
        ("code in an item's quote is found with the quote's depth; a quoted list's own code "
         "isn't quoted again; and in a file that doesn't say its items' later paragraphs are "
         "indented, the rules for numbered ones hold, code beyond two quote steps outside "
         "any list one quote deeper than the reader quotes it",
         lambda: indented_code == [("include csv", 1)]
         and numbered_code == [("include csv", 1), ("acct1", 1)]),
        ("reading a file the target wrote, the quote is lined up and marked, and the paragraph "
         "after the item's table a list paragraph; for a reader before 3.13, every item's "
         "later paragraph a list paragraph",
         lambda: "tiqItemQuote1x1" in repaired_xml
         and '<w:numId w:val="4000000"/>' in paragraph_of(repaired_xml, "A3")
         and '<w:numId w:val="4000000"/>' not in paragraph_of(repaired_xml, "A1")
         and all('<w:numPr><w:ilvl w:val="%s"/><w:numId w:val="4000000"/></w:numPr>' % level
                 in paragraph_of(repaired_old, t)
                 for t, level in (("A1", 0), ("B1", 1), ("A2", 0), ("Q", 0), ("A3", 0)))
         and re.search(r"tiqItemQuote1x\d+", paragraph_of(repaired_old, "Q"))),
        ("a figure an item holds keeps its list, the paragraphs after it list paragraphs to the "
         "item's end; its picture and caption are none of the item's; one no item holds ends "
         "the list, the item's paragraphs after it list paragraphs of no list open, one in a "
         "cell is passed over, and a caption beside a numbered picture, which the reader "
         "doesn't pair with it, continues the item",
         lambda: [(f[0], f[1][0], f[4]) for f in found(figures_body, False, figures_held)]
         == [("G1", "1001", True), ("H1", "1001", False), ("J's", "1001", False),
             ("J1", "1001", False), ("K1", None, True)]
         and [(f[0], f[1][0]) for f in found(figures_body, False)][0] == ("G1", None)),
        ("the held figure's picture and caption lose their indent, so the reader doesn't take "
         "the caption's words for a quotation; the others keep theirs",
         lambda: "<w:ind" not in paragraph_of(figures_marked, "in G")
         and "<w:ind" not in re.findall(r"<w:p>.*?</w:p>", figures_marked)[3]
         and "<w:drawing>" in re.findall(r"<w:p>.*?</w:p>", figures_marked)[3]
         and '<w:numId w:val="4000000"/>' in paragraph_of(figures_marked, "G1")
         and "<w:ind" in paragraph_of(figures_marked, "in K")
         and paragraph_of(figures_marked, "before") == paragraph_of(figures_body, "before")),
        ("the target counts a figure the reader pairs with its caption, outside tables and "
         "unnumbered, as the reading does",
         lambda: figures_listed == [("f", 1, 1, "1")]
         and docxtarget.ITEM_TABLE_MARK not in figures_target),
        ("the words of an item the writer numbers nowhere, after its list, are a list paragraph "
         "at the item's level, where no level the reader keeps open is theirs; not a quote's "
         "paragraph so lined up, nor one in the writer's form only by its style's indent",
         lambda: [(f[0], f[1], f[3], f[4]) for f in found(orphan_body, False)]
         == [("b's words", ("1001", "0"), 0, True)]
         and found(item("q") + rule + later("deep quote", 2160, "BlockText", ' w:right="480"'),
                   False) == []
         and found(item("r") + list_paragraph("Head", "Heading2")
                   + list_paragraph("styled", "ListContinue"), False) == []),
        ("a table's caption in the item's style, before a table the item holds, keeps the list, "
         "and the item's paragraph after the table is a list paragraph of the item's list; "
         "where the item doesn't hold the table, the caption ends the list, and the paragraph "
         "is a list paragraph of none",
         lambda: [(f[0], f[1], f[4]) for f in found(caption_body, False, {("t", 0)})]
         == [("x after", ("1001", "0"), True)]
         and [(f[0], f[1], f[4]) for f in found(caption_body, False)]
         == [("x after", (None, "0"), True)]
         and [(f[0], f[3], f[4]) for f in found(caption_quote, True, {("t", 0)})]
         == [("quote after", 1, True)]),
        ("after the reader, a table's caption paragraph goes back in the item with the table; "
         "and a list of another numbering after a figure, the next item's own, stays in the "
         "item, the list of the item's own numbering joining it",
         lambda: [b["t"] for b in caption_put_back] == ["OrderedList"]
         and [[b["t"] for b in item] for item in caption_put_back[0]["c"][1]]
         == [["Para", "Para", "Table", "Para"], ["Para"]]
         and [b["t"] for b in nested_put_back] == ["OrderedList"]
         and [[b["t"] for b in item] for item in nested_put_back[0]["c"][1]]
         == [["Para", "Figure", "OrderedList"], ["Para"]]),
        ("after the reader, the figure an item holds and the paragraph after it go back in the "
         "item, and the list begun again after them joins it",
         lambda: figures_moved == 1 and [b["t"] for b in figures_put_back] == ["Figure",
                                                                              "OrderedList"]
         and [[b["t"] for b in item] for item in figures_put_back[1]["c"][1]]
         == [["Para", "Figure", "Para"], ["Para"]]),
        ("after the reader, a caption paragraph whose words are the table's caption becomes "
         "that caption, its emphasis kept, and isn't the item's paragraph",
         lambda: [[b["t"] for b in item] for item in caption_merged[0]["c"][1]]
         == [["Para", "Table", "Para"], ["Para"]]
         and caption_merged[0]["c"][1][0][1]["c"][1][1][0]["c"][0]["t"] == "Emph"),
        ("a rule an item holds keeps the list, the paragraph after it a list paragraph of the "
         "item's list; one no item holds ends it",
         lambda: [(f[0], f[1], f[4]) for f in found(rule_body, False, {("r", 0)})]
         == [("after the rule", ("1001", "0"), True)]
         and [(f[0], f[1], f[4]) for f in found(rule_body, False)]
         == [("after the rule", (None, "0"), True)]),
        ("a note ends the reader's lists where its reference is: the item's paragraphs after "
         "it are list paragraphs, and so are those before it since the item's own; every list "
         "paragraph with no indent, which the reader could take for a continuation",
         lambda: [(f[0], f[2], f[4]) for f in found(note_body, False)]
         == [("n1", 720, True), ("m1", None, True), ("m2", None, True), ("m3", 720, True)]
         and all('<w:numId w:val="4000000"/>' in paragraph_of(note_marked, t)
                 and "<w:ind" not in paragraph_of(note_marked, t)
                 for t in ("n1", "m1", "m2", "m3"))),
        ("an item ends the reader's lists inside the one before it: a paragraph lined up with "
         "a deeper item's text after it is no continuation of that item",
         lambda: [(f[0], f[1], f[4]) for f in found(deeper_body, False)]
         == [("c deep", ("1001", "1"), True)]),
        ("a quote's paragraph beyond an item's text by other than quote steps isn't the item's",
         lambda: found(off_step, True) == []),
        ("a picture with a bookmark beside it, and a caption that keeps with the next paragraph "
         "after a picture, are no pair to the reader: an item's paragraphs like any other",
         lambda: [f[0] for f in found(unpaired_body, False)]
         == ["", "its caption", "p1", "", "kept", "k1"]),
        ("a caption after a table is the table's to the reader, ending the list, and with the "
         "table an item holds no paragraph of the item, its indent taken off",
         lambda: [(f[0], f[1], f[4]) for f in found(after_table, False)]
         == [("v1", (None, "0"), True)]
         and [(f[0], f[1], f[4]) for f in found(after_table, False, {("t", 0)})]
         == [("v1", ("1001", "0"), True)]
         and "<w:ind" not in paragraph_of(after_marked, "the table's")
         and '<w:numId w:val="4000000"/>' in paragraph_of(after_marked, "v1")),
        ("a quote, or a paragraph indented its own way, before a table an item holds is no "
         "caption of it, and ends the list",
         lambda: [(f[0], f[1]) for f in found(no_caption, False, {("t", 0), ("t", 1)})]
         == [("t1", (None, "0")), ("u1", (None, "0"))]),
        ("after a table an item holds, an inner item opening again leaves the outer item's "
         "list ended to the reader, its paragraph after a list paragraph",
         lambda: [(f[0], f[1], f[4]) for f in found(reopened, False, {("t", 0)})]
         == [("A after", ("1001", "0"), True)]),
        ("after an item's paragraph no open list takes, the paragraphs lined up with it, and a "
         "quote a step beyond it, are that item's list paragraphs too",
         lambda: [(f[0], f[1], f[3], f[4]) for f in found(orphan_after, True)]
         == [("b1", ("1001", "0"), 0, True), ("b2", ("1001", "0"), 0, True),
             ("b's quote", ("1001", "0"), 1, True)]),
        ("code in a quote in a quote after a table its item holds is found at its quote's depth "
         "beyond the item's text, not counted from the margin",
         lambda: held_code == [("two deep", 2)]),
        ("a list in a table's cell: its item's later paragraph is the item's, a list paragraph "
         "for a reader before 3.13 only",
         lambda: [(f[0], f[4]) for f in found(cell_list, False)] == [("the cell's later", False)]
         and '<w:numId w:val="4000000"/>' in paragraph_of(cell_every, "the cell's later")
         and paragraph_of(cell_kept, "the cell's later")
         == paragraph_of(cell_list, "the cell's later")),
        ("in a note, an item's later paragraph is a list paragraph for a reader before 3.13, "
         "and left for one from 3.13",
         lambda: '<w:numId w:val="4000000"/>' in paragraph_of(notes_old, "note's later")
         and '<w:numId w:val="4000000"/>' not in paragraph_of(notes_xml, "note's later")),
        ("the target holds a figure of a picture and a caption as one, one of two pictures, "
         "written as a table, as a table, and one with no caption not at all, where the writer "
         "indents an item's later paragraphs; and none where it numbers them",
         lambda: docxtarget._held(lone([para("cap")]), True) == "f"
         and docxtarget._held(two, True) == "t" and docxtarget._held(lone([]), True) is None
         and docxtarget._held(lone([para("cap")])) is None and docxtarget._held(two) is None),
        ("a mark around a figure the reader makes no figure of is left out, not taken for the "
         "next figure the reader makes",
         lambda: stray_listed == []),
        ("a table's caption the writer wrote in Compact, each paragraph its mark holds before the "
         "table, a formula's too, is styled Table Caption; a paragraph before a table outside "
         "any table's mark isn't, nor one past a mark whose range holds no table",
         lambda: restyled_count == 2
         and paragraph_of(restyled, "Prices &amp; costs").count('w:val="TableCaption"') == 1
         and '<w:pStyle w:val="TableCaption"/></w:pPr><m:oMath/>' in restyled
         and 'w:val="Compact"' in paragraph_of(restyled, "Something else")
         and 'w:val="Compact"' in paragraph_of(restyled, "A tight list's item")),
        ("after a list in an item, a paragraph holding a note is a continuation the reader "
         "keeps, not made a list paragraph, which it would fold into the inner list's item",
         lambda: [(f[0], f[4]) for f in found(note_after, False)]
         == [("A2", False), ("A3", True)]),
        ("the blocks the reader gives back after a held block: a paragraph after a list "
         "folds into its last item, up to a table, a heading, or another list; a list whose "
         "item holds a table, at any depth, is its parts, the paragraphs after the table "
         "blocks of their own, an item that opens with one among them, and a figure the writer "
         "writes as one a table to any reader; a list after another begins another; a div is "
         "what it holds, an anchor nothing",
         lambda: read_back_counts == [2, 3, 3, 4, 3, 3, 3, 2, 1, 4, 2, 3]),
        ("an item that opens with anchors before a list gets a paragraph of them, which the "
         "writer numbers, and one that opens with a table, a figure the writer writes as one, or "
         "a rule an empty paragraph first; one whose "
         "anchors come before words keeps them",
         lambda: anchored_counts == (1, 0) and anchored[0]["t"] == "Plain"
         and [x["c"][0][0] for x in anchored[0]["c"]] == ["a1", "a2"] and len(anchored) == 2
         and worded[0]["t"] == "Div"
         and tabled_count == 1 and [b["t"] for b in tabled] == ["Plain", "Div", "Para"]
         and tabled[0]["c"] == [{"t": "Str", "c": ""}]
         and ruled_count == 1 and [b["t"] for b in ruled] == ["Plain", "HorizontalRule", "Para"]
         and pictured_count == 1 and [b["t"] for b in pictured] == ["Plain", "Figure", "Para"]),
        ("a formula alone in a Plain or in a span is a display paragraph, and a Plain with "
         "words and a formula is cut into Plains",
         lambda: docxtarget._display_math_para(plain_math)
         and docxtarget._display_math_para(span_math)
         and [b["t"] for b in split_plain] == ["Plain", "Plain"]),
        ("the target counts a captioned picture with a bookmark in its paragraph as a figure, "
         "the bookmark moved into its caption as reading moves it",
         lambda: bookmarked_count == [("f", 1, 0, "0")]),
        ("after the reader, an outer item's table takes back its blocks, the parts of the inner "
         "list among them, and the inner item's goes back in its item; and a block the reader "
         "made beyond the count goes back in the item whose list goes on",
         lambda: [b["t"] for b in nested_back] == ["OrderedList"]
         and [[b["t"] for b in item] for item in nested_back[0]["c"][1]]
         == [["Para", "Table", "Para", "BulletList"], ["Para"]]
         and [[b["t"] for b in item] for item in nested_back[0]["c"][1][0][3]["c"]]
         == [["Para", "Table", "Para"], ["Para"]]
         and [[b["t"] for b in item] for item in leftover_back[0]["c"][1]]
         == [["Para", "Table", "Para", "Para"], ["Para"]]),
        ("a table the outer item's table took back with its blocks stays in that item; the "
         "outer item's blocks go back in it where its list doesn't go on; and an inner item's "
         "table after a list that item holds goes back in the item, not the list",
         lambda: [b["t"] for b in placed_back] == ["OrderedList"]
         and [[b["t"] for b in item] for item in placed_back[0]["c"][1]]
         == [["Para", "Table", "BulletList", "Table", "Para"], ["Para"]]
         and [[b["t"] for b in item] for item in placed_back[0]["c"][1][0][2]["c"]]
         == [["Para", "Table"], ["Para"]]
         and [b["t"] for b in last_back] == ["OrderedList"]
         and [[b["t"] for b in item] for item in last_back[0]["c"][1]]
         == [["Para", "Table", "BulletList", "Para"]]
         and [[b["t"] for b in item] for item in last_back[0]["c"][1][0][2]["c"]]
         == [["Para", "Table", "Para"]]
         and [[b["t"] for b in item] for item in walk_back[0]["c"][1]]
         == [["Para", "Table", "BulletList"], ["Para"]]
         and [[b["t"] for b in item] for item in walk_back[0]["c"][1][0][2]["c"]]
         == [["Para", "BulletList", "Table", "Para"]]),
        ("a quote mark at depth one is taken off and counted, so the page is saved without it",
         lambda: quote_marks == 1 and quoted_doc["blocks"][0]["c"][0]["c"]
         == [{"t": "Str", "c": "Q"}]),
    ]


def check_word_equation_text():
    """Normal text in Word's equation, \\text{} in TeX, gets only the
    characters that are characters for others, as math-repair.lua gives
    \\text{} only those."""
    import docxremediate
    math = ('<m:oMath><m:r><m:t>ŷ=µ·x</m:t></m:r>'
            '<m:r><m:rPr><m:nor /></m:rPr><m:t>ŷ 1–5 µ·</m:t></m:r></m:oMath>')
    fixed, counts = docxremediate.remediate_equations(math)
    return [
        ("a y-hat in math is a hat over y, the micro sign mu, and a middle dot the "
         "dot operator Pandoc writes for \\cdot",
         lambda: fixed.startswith('<m:oMath><m:acc>') and "<m:t>=μ⋅x</m:t>" in fixed),
        ("in normal text the y-hat, the en dash, and the middle dot stay, and the micro "
         "sign is mu",
         lambda: "<m:t>ŷ 1–5 μ·</m:t>" in fixed and fixed.count("<m:acc>") == 1),
        ("each character changed is counted",
         lambda: counts == {"equations_repaired": 1, "equation_characters": 4}),
    ]


def check_equation_bars():
    """A bar written as an upper limit: an accent of the macron in a Word
    file, and in a deck still a limit, a macron in place of an en dash. A
    limit inside another's base is repaired with it, and a limit of any
    other character is left."""
    import docxremediate

    def limit(base, char, props=""):
        return ("<m:limUpp>%s<m:e>%s</m:e><m:lim><m:r><m:rPr><m:sty m:val=\"p\" /></m:rPr>"
                "<m:t>%s</m:t></m:r></m:lim></m:limUpp>" % (props, base, char))

    def run(text):
        return "<m:r><m:t>%s</m:t></m:r>" % text

    def bar(base):
        return '<m:acc><m:accPr><m:chr m:val="\u00af" /></m:accPr><m:e>%s</m:e></m:acc>' % base

    x, y = run("x"), run("y")
    one = ("<m:oMath>" + limit(x, "¯", "<m:limUppPr><m:ctrlPr /></m:limUppPr>") + run("–")
           + limit(y, "–") + run("+") + limit(x, "→") + "</m:oMath>")
    nested = ("<m:oMath>" + limit("<m:sSub><m:e>" + limit(x, "–") + "</m:e><m:sub>" + run("1")
                                  + "</m:sub></m:sSub>", "¯") + "</m:oMath>")
    macron = "<m:oMath>" + limit(x, "¯") + "</m:oMath>"
    word, word_counts = docxremediate.remediate_equations(one)
    deck, deck_counts = docxremediate.remediate_equations(one, macron_bars=True)
    word_nested, word_nested_counts = docxremediate.remediate_equations(nested)
    deck_nested, deck_nested_counts = docxremediate.remediate_equations(nested, macron_bars=True)
    kept, kept_counts = docxremediate.remediate_equations(macron, macron_bars=True)
    return [
        ("in a Word file, a macron's limit and an en dash's are each an accent of the "
         "macron, the en dash between them a minus, and an arrow's limit left",
         lambda: word == "<m:oMath>" + bar(x) + run("−") + bar(y) + run("+")
         + limit(x, "→") + "</m:oMath>"
         and word_counts == {"equations_repaired": 1, "equation_characters": 3}),
        ("in a deck, the macron's limit stays, the en dash's is a macron, the en dash between "
         "them a minus, and the arrow's left",
         lambda: deck == one.replace("<m:t>–</m:t></m:r></m:lim>",
                                     "<m:t>¯</m:t></m:r></m:lim>")
         .replace(run("–"), run("−"))
         and deck_counts == {"equations_repaired": 1, "equation_characters": 2}),
        ("a limit inside another's base is repaired with it, in a Word file and in a deck",
         lambda: word_nested == "<m:oMath>" + bar("<m:sSub><m:e>" + bar(x) + "</m:e><m:sub>"
                                                  + run("1") + "</m:sub></m:sSub>") + "</m:oMath>"
         and word_nested_counts["equation_characters"] == 2
         and deck_nested == nested.replace("–", "¯")
         and deck_nested_counts["equation_characters"] == 1),
        ("a deck's bar that's already a macron is no repair at all",
         lambda: kept == macron and kept_counts == {"equations_repaired": 0,
                                                    "equation_characters": 0}),
    ]


def check_bar_accents():
    """Pandoc's \\bar, an accent of the overline, is the macron's in a
    docx target's file, and reading a Word file the macron's is the
    overline's again: only an accent's character, either way."""
    import zipfile
    import docxrepair
    import docxtarget

    def accent(char, props=""):
        return ('<m:acc><m:accPr>%s<m:chr m:val="%s" /></m:accPr><m:e><m:r><m:t>x</m:t></m:r>'
                '</m:e></m:acc>' % (props, char))
    group = ('<m:groupChr><m:groupChrPr><m:chr m:val="%s" /></m:groupChrPr><m:e><m:r><m:t>x'
             '</m:t></m:r></m:e></m:groupChr>')
    bar = '<m:bar><m:barPr><m:pos m:val="top" /></m:barPr><m:e><m:r><m:t>x</m:t></m:r></m:e></m:bar>'
    pandoc = ("<m:oMath>" + accent("\u203e") + accent("\u0302") + group % "\u203e" + bar
              + accent("\u203e", "<m:ctrlPr />") + "</m:oMath>")
    written, n_written = docxtarget.bar_accents(pandoc)
    read, n_read = docxrepair.bar_accents(written)
    others = ("<m:oMath>" + accent("&#175;") + accent("&#xAF;") + group % "\u00af"
              + accent("\u0304") + "</m:oMath>")
    others_read, n_others = docxrepair.bar_accents(others)
    # A conversion's copy of a Word file: the body, the footnotes, and the
    # endnotes read so, and a header, which Pandoc doesn't read, as it was.
    folder = tempfile.mkdtemp()
    source, copy = os.path.join(folder, "notes.docx"), os.path.join(folder, "copy.docx")
    body = '<w:document><w:body><w:p>%s</w:p></w:body></w:document>' % accent("\u00af")
    note = '<w:footnotes><w:footnote w:id="1"><w:p>%s</w:p></w:footnote></w:footnotes>' % accent("\u00af")
    endnote = '<w:endnotes><w:endnote w:id="1"><w:p>%s</w:p></w:endnote></w:endnotes>' % accent("\u00af")
    header = '<w:hdr><w:p>%s</w:p></w:hdr>' % accent("\u00af")
    with zipfile.ZipFile(source, "w") as z:
        z.writestr("word/document.xml", body)
        z.writestr("word/footnotes.xml", note)
        z.writestr("word/endnotes.xml", endnote)
        z.writestr("word/header1.xml", header)
    docxrepair.repaired_copy(source, copy)
    with zipfile.ZipFile(copy) as z:
        copied = {n: z.read(n).decode("utf-8") for n in z.namelist()}
    shutil.rmtree(folder)
    return [
        ("the docx target gives Pandoc's two accents of the overline the macron, and leaves "
         "the hat, a group character of the overline, and Office's overbar",
         lambda: written == pandoc.replace(accent("\u203e"), accent("\u00af")).replace(
             accent("\u203e", "<m:ctrlPr />"), accent("\u00af", "<m:ctrlPr />"))
         and n_written == 2),
        ("reading a Word file, each accent of the macron is the overline's again, so the "
         "file reads as Pandoc wrote it",
         lambda: read == pandoc and n_read == 2),
        ("a macron written as a character reference is one too, a group character of the "
         "macron isn't an accent, and the combining macron, which Pandoc reads as \\bar "
         "already, is left",
         lambda: others_read == others.replace(accent("&#175;"), accent("\u203e")).replace(
             accent("&#xAF;"), accent("\u203e")) and n_others == 2),
        ("a conversion's copy reads the body's, the footnotes', and the endnotes' so, and "
         "leaves a header's, which Pandoc doesn't read",
         lambda: all(accent("\u203e") in copied[n] for n in
                     ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml"))
         and copied["word/header1.xml"] == header),
    ]


def check_link_replacements():
    """A bare link's Replacement in a source target's copy, as the filter
    reads it on the pages: an address replaces the link's address and its
    text, and any other text its text alone. The copies had written text
    as the address: an href or a relationship's Target of words."""
    import docxremediate
    import htmlremediate
    import mdremediate
    url, words, short = "https://example.org/data", "The [cars] data", "https://doi.org/10/x"
    page = '<p><a href="%s">%s</a></p>' % (url, url)
    html_words = htmlremediate.remediate_links(page, {url: (words, "")})[0]
    html_short = htmlremediate.remediate_links(page, {url: (short, "")})[0]
    xml = '<w:hyperlink r:id="rId9"><w:r><w:t>%s</w:t></w:r></w:hyperlink>' % url
    rels = ('<Relationship Id="rId9" Type="x/hyperlink" Target="%s" TargetMode="External"/>'
            % url)
    word_words = docxremediate.replace_links(xml, rels, {url: words})
    word_short = docxremediate.replace_links(xml, rels, {url: short})
    doc = {"blocks": [{"t": "Para", "c": [{"t": "Link", "c": [
        ["", [], []], [{"t": "Str", "c": url}], [url, ""]]}]}]}
    md_words = mdremediate.remediate_links("See <%s>." % url, doc, {url: (words, "")})[0]
    md_marks = mdremediate.remediate_links("See <%s>." % url, doc,
                                           {url: ("Smith's *Nature* `cars` paper", "")})[0]
    md_short = mdremediate.remediate_links("See <%s>." % url, doc, {url: (short, "")})[0]
    return [
        ("HTML: text replaces the link's text, an address its address and text",
         lambda: html_words == '<p><a href="%s">The [cars] data</a></p>' % url
         and html_short == '<p><a href="%s">%s</a></p>' % (short, short)),
        ("Word: text replaces the hyperlink's text, an address its relationship's target too",
         lambda: "<w:t>The [cars] data</w:t>" in word_words[0]
         and 'Target="%s"' % url in word_words[1]
         and 'Target="%s"' % short in word_short[1] and "<w:t>%s</w:t>" % short in word_short[0]),
        ("Markdown: text replaces the link's text, its markup escaped, an address both",
         lambda: md_words == "See [The \\[cars\\] data](%s)." % url
         and md_marks == "See [Smith's \\*Nature\\* \\`cars\\` paper](%s)." % url
         and md_short == "See [%s](%s)." % (short, short)),
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



def check_project_sample():
    """project-sample.yaml as oerconfig writes it: every project setting
    with its description, and read back, the values it was given; and the
    project: block another file holds, read leniently."""
    import yaml
    work = tempfile.mkdtemp(prefix="project-sample-")
    try:
        schema = oerconfig.load_schema(os.path.join(ROOT, "lib", "schema-project.yaml"))
        values = dict(oerconfig.resolve(schema, schema, []).project,
                      identifier="org.example.unit", title="A Book",
                      contents=[{"page": "preface", "type": "preface"}, "one"])
        path = os.path.join(work, "project-sample.yaml")
        text = oerconfig.write_project(schema, values, path, notes=["A note."])
        back = oerconfig.load_document(path, schema).project
        blocks = {}
        for name, body in (("with.yaml", "project:\n  title: T\ndefaults: {}\n"),
                           ("without.yaml", "defaults: {}\n"),
                           ("broken.yaml", "project: [\n"),
                           ("listed.yaml", "project:\n  - a\n")):
            with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
                fh.write(body)
            blocks[name] = oerconfig.inline_project(os.path.join(work, name))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    described = [k for k in schema.root.keys if k in yaml.safe_load(text)["project"]]
    return [
        ("it reads back as the values written, contents and all",
         lambda: back == {k: v for k, v in values.items()}),
        ("every project setting is in it, the notes at the top",
         lambda: set(described) == set(schema.root.keys)
         and text.startswith("# Configuration for project") and "# A note." in text),
        ("another file's project block is found, and none in a file without "
         "one, a broken one, or one that isn't a mapping",
         lambda: blocks == {"with.yaml": {"title": "T"}, "without.yaml": None,
                            "broken.yaml": None, "listed.yaml": None}),
        ("an identifier or a title at its default isn't declared",
         lambda: oerconfig.declared_project([
             oerconfig.Document({"project": {"identifier": "book", "title": "T"}}, "a"),
             oerconfig.Document({"project": {"title": "Untitled", "language": "de"}}, "b")])
         == {"language": "de"}),
        ("the sample takes another file's block and a master's details where "
         "nothing declares them, and says so",
         lambda: (lambda v: v[0]["title"] == "Its Own" and v[0]["authors"] == ["A"]
                  and v[0]["contents"] == ["z", "a"] and v[0]["language"] == "en"
                  and v[2] == ["authors", "contents"]
                  and any("From conversion.yaml's block" in n for n in v[1]))(
             oerconfig.project_sample_values(
                 dict(values, language="en"), {"language": "en"},
                 {"project": {"title": "Its Own"}, "project_source": "conversion.yaml's block",
                  "title": "The Master's", "authors": ["A"], "language": "de",
                  "contents": ["z", "a"], "source": "the master"}, ["a", "z"], True))),
        ("a sample's inline block holds the file's own settings and no others",
         lambda: (lambda b: "language: de" in b and "identifier:" not in b
                  and "title:" not in b)((lambda t: t.split("\nproject:", 1)[1].split(
                      "\ndefaults:", 1)[0])(
             oerconfig.write_config(
                 oerconfig.load_schema(os.path.join(ROOT, "bin", "schema-packaging.yaml")),
                 schema, oerconfig.resolve(
                     oerconfig.load_schema(os.path.join(ROOT, "bin", "schema-packaging.yaml")),
                     schema, []), {}, os.path.join(scratch(), "s.yaml"),
                 include_project={"language": "de"})))),
    ]

def check_types_by_title():
    """A page whose title names what it is gets the type in a guessed
    contents, the role the type implies dropped and one it doesn't kept."""
    titles = {"preface": "Preface", "1-introduction": "Introduction",
              "1-1-a": "1.1 A", "1-key-terms": "Key Terms",
              "1-references": "References", "2-1-b": "2.1 B",
              "2-introduction": "Introduction", "index": "Index"}
    order = bookcontents.guess_contents(list(titles), titles=titles)
    chapter = order[1]["items"]
    typed = bookcontents.typed_by_title(
        [{"page": "g", "role": "front"}, {"page": "h", "type": "index"},
         {"generate": "toc"}, {"page": "a", "title": "Appendix B Tables"}],
        {"g": "Glossary", "h": "Glossary"})
    return [
        ("a title's words name a type, an appendix by its first word, and "
         "an Introduction none",
         lambda: [bookcontents.type_of_title(t) for t in
                  ("Key Terms", "works cited.", "Appendix A Statistical Tables",
                   "Appendixes", "Introduction")]
         == ["glossary", "bibliography", "appendix", None, None]),
        ("every type a title can name is a page type",
         lambda: set(bookcontents.TITLE_TYPES.values())
         <= set(bookcontents.PAGE_TYPES)),
        ("the guess types the preface and the index, whose types say "
         "they're front and back matter",
         lambda: order[0] == {"page": "preface", "type": "preface"}
         and order[-1] == {"page": "index", "type": "index"}),
        ("and a chapter's Key Terms and References, nothing else in it",
         lambda: {"page": "1-key-terms", "type": "glossary"} in chapter
         and {"page": "1-references", "type": "bibliography"} in chapter
         and "1-introduction" in chapter and "1-1-a" in chapter),
        ("a role the type doesn't imply stays, a declared type isn't "
         "replaced, a generated page is left, and a title in the contents "
         "counts",
         lambda: typed == [{"page": "g", "role": "front", "type": "glossary"},
                           {"page": "h", "type": "index"}, {"generate": "toc"},
                           {"page": "a", "title": "Appendix B Tables",
                            "type": "appendix"}]),
    ]


def check_one_file_chapters():
    """A book written one file per numbered chapter: each file is its
    chapter, not a page under a "Chapter N" of its own; a chapter of
    several files is still a group; an appendix keeps its role."""
    order = bookcontents.guess_contents(
        # Page names as a run makes them from "01 BigPicture.md" and the
        # rest; the chapter number is read from the leading digits.
        ["_preamble", "01-BigPicture", "02-Models", "03-Questions",
         "04-Trade", "A1-Intro", "A2-Math", "Z1-Glossary"],
        roles={"A1-Intro": "appendix", "A2-Math": "appendix"})
    grouped = bookcontents.guess_contents(
        ["1-1-a", "1-2-b", "2-1-c", "2-2-d", "3-1-e"])
    return [
        ("each one-file chapter is a page at the top",
         lambda: order[1:5] == ["01-BigPicture", "02-Models",
                                "03-Questions", "04-Trade"]),
        ("front, appendix, and back matter keep their roles",
         lambda: order[0] == {"page": "_preamble", "role": "front"}
         and order[5:] == [{"page": "A1-Intro", "role": "appendix"},
                           {"page": "A2-Math", "role": "appendix"},
                           {"page": "Z1-Glossary", "role": "back"}]),
        ("a chapter of several files is still a group, one of one file isn't",
         lambda: [isinstance(e, dict) and "items" in e for e in grouped]
         == [True, True, False]),
    ]


def check_output_names():
    """The names a target copies the files a page names under
    (names.output_path) are the names safe-media.lua writes into the page:
    safe or the author's own, lowercased or not (media.lowercase), the
    letters A to Z alone."""
    import json
    from urllib.parse import unquote
    import names
    refs = ["Assets/Fig 1.PNG", "Assets/My%20Pic.png", "Über/Été.JPG", "a/b.png"]
    api = json.loads(subprocess.run(["pandoc", "-f", "markdown", "-t", "json"], input="",
                                    capture_output=True, text=True).stdout)["pandoc-api-version"]
    doc = {"pandoc-api-version": api, "meta": {}, "blocks": [
        {"t": "Para", "c": [{"t": "Image", "c": [["", [], []], [], [ref, ""]]} for ref in refs]}]}
    found = {}
    for safe in (True, False):
        for lower in (True, False):
            env = dict(os.environ, MEDIA_SAFE="1" if safe else "0",
                       MEDIA_LOWERCASE="1" if lower else "")
            result = subprocess.run(["pandoc", "-f", "json", "-t", "json", "--lua-filter",
                                     os.path.join(ROOT, "bin", "safe-media.lua")],
                                    input=json.dumps(doc), capture_output=True, text=True,
                                    env=env)
            written = [i["c"][2][0] for i in json.loads(result.stdout)["blocks"][0]["c"]]
            found[(safe, lower)] = [(unquote(w) if not safe else w,
                                     names.output_path(unquote(r), safe, lower))
                                    for w, r in zip(written, refs)]
    return [
        ("Python and the Lua filter name each file alike, every way",
         lambda: all(w == p for pairs in found.values() for w, p in pairs)
         or print("    %r" % found)),
        ("lowercased, a safe name is ASCII, and the author's keeps its other letters",
         lambda: [p for _w, p in found[(True, True)]] == [
             "assets/fig-1.png", "assets/my-pic.png", "ber/t.jpg", "a/b.png"]
         and [p for _w, p in found[(False, True)]] == [
             "assets/fig 1.png", "assets/my pic.png", "Über/Été.jpg", "a/b.png"]),
    ]


def check_notes_heading():
    """An HTML page's notes section, as Pandoc's writer leaves it, headed
    after its rule, once however often it's given one, the heading's text
    escaped; none, given no heading."""
    import htmlrepair
    import notes
    page = ('<p>Text.</p>\n<section id="footnotes" class="footnotes footnotes-end-of-document"\n'
            'role="doc-endnotes">\n<hr />\n<ol>\n<li id="fn1"><p>A note.</p></li>\n</ol>\n'
            '</section>\n')
    once = notes.titled(page, "Notes & <More>")
    return [
        ("the heading goes after the rule, its text escaped",
         lambda: '<hr />\n<h2 class="footnotes-title">Notes &amp; &lt;More&gt;</h2>\n<ol>'
         in once),
        ("a section with its heading isn't given another",
         lambda: notes.titled(once, "Notes & <More>") == once),
        ("an empty title gives none",
         lambda: notes.titled(page, "") == page),
        # Pandoc's reader keeps a heading in the notes' section, and the
        # section around it, so a page converted again had both.
        ("a page read again loses the heading the run gave its notes, and keeps any other",
         lambda: htmlrepair.repaired(once)[0] == htmlrepair.repaired(page)[0]
         and "<h2" in htmlrepair.repaired(page.replace("<hr />", "<hr />\n<h2>Sources</h2>"))[0]),
    ]


def check_notes_groups():
    """A page's notes group, the same for the HTML pages and the EPUB:
    the top-level entry of the contents holding it, a chapter however
    deep its pages sit, a page on its own, or a group of pages, or in a
    part (type: part) the part's entry holding it; the generated contents
    page left out; and titles numbered as the tree is."""
    import notes
    contents = [
        "preface", {"generate": "toc"},
        {"title": "Part One", "type": "part", "items": [
            "opening",
            {"title": "Chapter 1", "items": [
                "c1", {"title": "Deeper", "items": ["c1-a", "c1-b"]}, "c1-z"]},
            {"title": "Chapter 2", "items": ["c2"]}]},
        {"title": "Unit Two", "items": [{"title": "Chapter 3", "items": ["c3"]}]},
        {"page": "extra", "role": "appendix"}]
    stems = {"preface", "opening", "c1", "c1-a", "c1-b", "c1-z", "c2", "c3", "extra"}
    titles = {stem: stem.capitalize() for stem in stems}

    def tree():
        return bookcontents.walk_contents(contents, stems, set(), [])
    found = notes.groups(tree(), titles)
    numbered = notes.groups(bookcontents.number_tree(tree(), titles), titles)
    return [
        ("every page in reading order, the generated contents page not among them",
         lambda: [stem for stem, _, _ in found]
         == ["preface", "opening", "c1", "c1-a", "c1-b", "c1-z", "c2", "c3", "extra"]),
        ("a chapter in a part is a group with all its pages, a group in it too, the part's "
         "own page one of its own, and a group that isn't a part is one whole",
         lambda: [(key, title) for _, key, title in found] == [
             ((0,), "Preface"), ((2, 0), "Opening"), ((2, 1), "Chapter 1"),
             ((2, 1), "Chapter 1"), ((2, 1), "Chapter 1"), ((2, 1), "Chapter 1"),
             ((2, 2), "Chapter 2"), ((3,), "Unit Two"), ((4,), "Extra")]),
        ("a group's title numbered as the tree is",
         lambda: [title for _, _, title in numbered][:2] == ["1 Preface", "2.1 Opening"]
         and [title for _, _, title in numbered][-2:] == ["3 Unit Two", "A Extra"]),
    ]


def check_notes_languages():
    """A title's language in a contents listing and on the Notes page: a
    page's own, a group's opening page's where the group's line stands for
    it, else the one all its pages share; and a note gathered onto a page
    in another language keeps its own page's."""
    import notes
    contents = [{"title": "Chapitre", "items": ["fr1", "fr2"]},
                {"title": "Gemischt", "items": ["de1", "fr3"]},
                "fr4", "de2",
                {"title": "Ouverture", "items": ["ouverture", "de3"]}]
    stems = {"fr1", "fr2", "de1", "fr3", "fr4", "de2", "ouverture", "de3"}
    titles = {stem: stem.capitalize() for stem in stems}
    others = {"fr1": "fr", "fr2": "fr", "fr3": "fr", "fr4": "fr", "ouverture": "fr"}
    tree = bookcontents.walk_contents(contents, stems, set(), [])
    listed = bookcontents.toc_blocks(tree, titles, lambda s: s + ".html", others, xml=True)
    links = {}

    def walk(node):
        if isinstance(node, dict):
            if node.get("t") == "Link":
                links[node["c"][2][0]] = node["c"][0][2]
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(listed)

    def page(language, words, note):
        return ('<html lang="%s"><body><main><p>%s<a href="#fn1" class="footnote-ref" '
                'id="fnref1" role="doc-noteref"><sup>1</sup></a></p>\n<section id="footnotes" '
                'class="footnotes footnotes-end-of-document" role="doc-endnotes">\n<hr />\n<ol>\n'
                '<li id="fn1"><p>%s<a href="#fnref1" class="footnote-back" '
                'role="doc-backlink">&#x21A9;</a></p></li>\n</ol>\n</section>\n</main></body>'
                '</html>\n' % (language, words, note))
    first = notes.Page("fr.html", page("fr", "Un.", "Une note."), (0,), "Gemischt", "html")
    last = notes.Page("de.html", page("de", "Ein.", "Eine Anmerkung."), (0,), "Gemischt",
                      "html")
    notes.arrange([first, last], "group", "group")
    return [
        ("a group's title is in the language all its pages share, or its opening page's "
         "where its line stands for that page, and a page's in its own",
         lambda: notes.title_languages(tree, titles, others) == {
             (0,): "fr", (2,): "fr", (4,): "fr"}),
        ("a contents listing's entries are marked so, lang and xml:lang, a page in the "
         "book's language not",
         lambda: links["fr1.html"] == [["lang", "fr"], ["xml:lang", "fr"]]
         and links["de1.html"] == [] and links["fr3.html"] == [["lang", "fr"], ["xml:lang", "fr"]]
         and links["ouverture.html"] == [["lang", "fr"], ["xml:lang", "fr"]]
         and links["de2.html"] == [] and links["de3.html"] == []),
        ("a note gathered at the end of its group, on a page in another language, keeps its "
         "page's, and the last page's own note none",
         lambda: '<li id="fn1" value="1" lang="fr"><p>Une note.' in last.text
         and '<li id="fn2" value="2"><p>Eine Anmerkung.' in last.text),
    ]


def check_notes_before_footer():
    """An EPUB's chapter file's notes go in its last section, before the
    footer setting's <footer> after it, whatever the footer holds."""
    import notes
    page = ('<body>\n<section id="c">\n<p>Text.</p>\n</section>\n<footer>\n<section>\n'
            '<p>Shared under CC BY.</p>\n</section>\n</footer>\n</body>\n')
    placed = notes.insert_before_end(page, "<aside>A note.</aside>\n", "xhtml")
    return [
        ("a chapter's notes go in its last section, before the footer, a section in the "
         "footer too",
         lambda: placed == page.replace("<p>Text.</p>\n</section>",
                                         "<p>Text.</p>\n<aside>A note.</aside>\n</section>", 1)),
    ]


def check_page_footer():
    """The footer setting outside an HTML page (lib/pagefooter.py): a Word
    footer's line keeps a no-break space, where its other white space runs
    together, and no part of a table keeps its id, the footer being on
    every page."""
    import pagefooter
    base = scratch()
    lines = pagefooter.paragraphs("Shared under CC\\ BY, p.\\ 5.\n\n- One\n- Two", base)
    table = pagefooter.xhtml(
        '<table id="t"><thead id="h"><tr id="hr"><th id="c1">A</th></tr></thead>'
        '<tbody id="b"><tr id="r"><td id="c2">x</td></tr></tbody></table>', base)
    return [
        ("a Word footer keeps a no-break space",
         lambda: lines == ["Shared under CC\u00a0BY, p.\u00a05.", "- One\n- Two"]),
        ("no part of a table in the footer keeps its id",
         lambda: "<td>x</td>" in table and " id=" not in table),
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


# A table of two bodies, each headed by a row of <th>: its group's own
# header row, the group's name in its corner, then the same with another
# word in the second cell, and with the same corner.
def grouped_table(second="Millions", corner="M2"):
    return ('<table><tbody><tr><th>Elements of M1</th><th>Millions</th></tr>'
            '<tr><td>Cash</td><td>350</td></tr></tbody>'
            f'<tbody><tr><th>Elements of {corner}</th><th>{second}</th></tr>'
            '<tr><td>Savings</td><td>562</td></tr></tbody></table>')


def check_group_heads():
    """A table whose bodies are each headed by a row like the others but
    for the group's name in its first cell is split there, each part
    headed by its row; rows that differ in another cell too, or are alike
    in their first cells as well, group nothing, and the table stays
    whole."""
    def tables(markup):
        out = subprocess.run(
            ["pandoc", "-f", "html", "-t", "html", "--lua-filter",
             os.path.join(ROOT, "bin", "figures-and-tables.lua")],
            input=markup, capture_output=True, text=True).stdout
        return out.count("<table"), out
    split, parts = tables(grouped_table())
    other, _ = tables(grouped_table(second="Billions"))
    same, _ = tables(grouped_table(corner="M1"))
    return [
        ("a group's own header row heading each body splits the table there",
         lambda: split == 2 and parts.count("<thead>") == 2),
        ("rows that differ in another cell too don't", lambda: other == 1),
        ("nor does a header row repeated, its first cell and all", lambda: same == 1),
    ]


DUPLICATE_IDS = ('<h4 id="site-selection">One</h4>'
                 '<p><span id="term-1" class="anchor"></span></p>'
                 '<h4 id="site-selection-1">Two</h4>'
                 '<h4 id="site-selection-1">Three</h4>')


# Headings an HTML page gave no id, marked so by htmlrepair.py, one before
# a table and one inside a div that have the id Pandoc gave the heading
# from its words; an anchor with the id renaming the first would take; and
# a table and a heading the page gave the same id.
GIVES_WAY = ('<h2 data-ti-auto-id="">Money</h2>'
             '<table id="money"><tr><th>A</th></tr><tr><td>1</td></tr></table>'
             '<div id="notes"><p>Intro.</p><h2 data-ti-auto-id="">Notes</h2></div>'
             '<p><span id="money-1"></span></p>'
             '<table id="costs"><caption>Costs</caption><tr><th>A</th></tr>'
             '<tr><td>1</td></tr></table>'
             '<h2 id="costs">Costs</h2>')


def check_unique_ids():
    """No id twice on a page, and an anchor keeps its name. A heading whose
    id Pandoc made from its words on an HTML page gives way to anything
    else's, unreported, and any other rename is a row of the report."""
    out = subprocess.run(
        ["pandoc", "-f", "html", "-t", "html", "--lua-filter",
         os.path.join(ROOT, "bin", "figures-and-tables.lua")],
        input=DUPLICATE_IDS, capture_output=True, text=True)
    ids = re.findall(r'id="([^"]*)"', out.stdout)
    work = scratch("unique-ids-")
    with open(os.path.join(work, "page.html"), "w", encoding="utf-8") as fh:
        fh.write(GIVES_WAY)
    report = os.path.join(work, "renamed.csv")
    given = subprocess.run(
        ["pandoc", "-f", "html", "-t", "html", "page.html", "--lua-filter",
         os.path.join(ROOT, "bin", "figures-and-tables.lua")],
        capture_output=True, text=True, cwd=work,
        env=dict(os.environ, IDS_RENAMED=report))
    tags = dict((m.group(2), m.group(1)) for m in
                re.finditer(r'<(\w+)[^>]*\bid="([^"]*)"', given.stdout))
    rows = []
    if os.path.exists(report):
        with open(report, encoding="utf-8", newline="") as fh:
            rows = list(csv.reader(fh))
    return [
        ("every id on the page is unique",
         lambda: len(ids) == len(set(ids))),
        ("the anchor keeps the name another file may link to",
         lambda: "term-1" in ids),
        ("the repeated heading is the one renumbered",
         lambda: ids.count("site-selection-1") == 1
         and "site-selection-2" in ids),
        ("a heading whose id Pandoc made gives way to a table's and a div's, "
         "before them or inside, to an id nothing on the page has",
         lambda: tags.get("money") == "table" and tags.get("notes") == "div"
         and tags.get("money-2") == "h2" and tags.get("notes-1") == "h2"
         and tags.get("money-1") == "span"),
        ("an id the page gave twice stays with the first, and the rename is "
         "the report's one row",
         lambda: tags.get("costs") == "table" and tags.get("costs-1") == "h2"
         and rows == [["page", "costs", "table: Costs", "heading: Costs",
                       "costs-1"]]),
        ("and the mark goes", lambda: given.stdout and "ti-auto-id" not in given.stdout),
    ]


def check_shortdoi():
    """util/shortdoi.py against a local stand-in for the shortDOI service:
    the DOIs without a Replacement get https://doi.org/ and the shortDOI,
    and nothing else in the sidecar changes."""
    import http.server
    import threading
    import tempfile
    seen = []
    busy = {"once": True}

    class Service(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            seen.append((self.path, self.headers.get("User-Agent", "")))
            path = self.path.split("?")[0]
            if path == "/10.1080/08913810508443640":
                body = {"DOI": "10.1080/08913810508443640", "ShortDOI": "10/b8xx35",
                        "IsNew": False}
            elif path == "/10.1002/(SICI)1097:15%3C1661%3E":
                if busy["once"]:
                    busy["once"] = False
                    self.send_response(429)
                    self.send_header("Retry-After", "0")
                    self.end_headers()
                    return
                body = {"DOI": "x", "ShortDOI": "10/zz99", "IsNew": True}
            else:
                self.send_response(404)
                self.end_headers()
                return
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)
    server = http.server.HTTPServer(("127.0.0.1", 0), Service)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    work = scratch("shortdoi-")
    sidecar = os.path.join(work, "bare-links.csv")
    with open(sidecar, "w", encoding="utf-8", newline="") as fh:
        fh.write("URL,Replacement,Title\n"
                 "https://doi.org/10.1080/08913810508443640,,DOI for Klein and Stern 2005\n"
                 "http://dx.doi.org/10.1002/(SICI)1097:15%3C1661%3E,,\n"
                 "https://doi.org/10.5555/decided,Kept as the author wrote it,\n"
                 "https://example.org/not-a-doi,,\n")
    tool = os.path.join(ROOT, "util", "shortdoi.py")
    service = "http://127.0.0.1:%d" % server.server_address[1]
    dry = subprocess.run([sys.executable, tool, sidecar, "--dry-run", "--service", service],
                         capture_output=True, text=True)
    asked_dry = len(seen)
    real = subprocess.run([sys.executable, tool, sidecar, "--wait", "0", "--service", service],
                          capture_output=True, text=True)
    # As Excel saves it, its mark first, with a row appended from a file
    # saved without a header, after a mark of its own; and as Excel's plain
    # "CSV" saves it, in Windows-1252.
    excel = os.path.join(work, "excel.csv")
    with open(excel, "w", encoding="utf-8", newline="") as fh:
        fh.write("\ufeffURL,Replacement,Title\r\nhttps://example.org/not-a-doi,,\r\n"
                 "\ufeffhttps://doi.org/10.1080/08913810508443640,,\r\n")
    from_excel = subprocess.run([sys.executable, tool, excel, "--wait", "0", "--service", service],
                                capture_output=True, text=True)
    ansi = os.path.join(work, "ansi.csv")
    with open(ansi, "w", encoding="cp1252", newline="") as fh:
        fh.write("URL,Replacement,Title\r\nhttps://doi.org/10.1080/08913810508443640,,"
                 "Klein \u2013 Stern\r\n")
    from_ansi = subprocess.run([sys.executable, tool, ansi, "--wait", "0", "--service", service],
                               capture_output=True, text=True)
    # A dry run of one Excel saved as plain CSV, which writes nothing.
    dry_file = os.path.join(work, "dry.csv")
    dry_bytes = ("URL,Replacement,Title\r\nhttps://doi.org/10.1080/08913810508443640,,"
                 "Klein \u2013 Stern\r\n").encode("cp1252")
    with open(dry_file, "wb") as fh:
        fh.write(dry_bytes)
    from_dry = subprocess.run([sys.executable, tool, dry_file, "--dry-run", "--service", service],
                              capture_output=True, text=True)
    with open(dry_file, "rb") as fh:
        dry_left = fh.read()
    # And one that reads as neither, as "CSV (MS-DOS)" saves Müller: a
    # byte Windows-1252 has no character for, and a capital Mac OS Roman
    # reads inside a word.
    odd = os.path.join(work, "odd.csv")
    stopping = b"URL,Replacement,Title\r\nhttps://doi.org/10.1080/08913810508443640,,M\x81ller's b\r\n"
    with open(odd, "wb") as fh:
        fh.write(stopping)
    from_odd = subprocess.run([sys.executable, tool, odd, "--wait", "0", "--service", service],
                              capture_output=True, text=True)
    with open(odd, "rb") as fh:
        odd_left = fh.read()
    # One it can't write the shortDOIs to, read-only, which root too is
    # kept from writing: it stops before asking anything, the file left as
    # it was. And a pipe, which reading would wait on: never read.
    readonly = os.path.join(work, "readonly.csv")
    readonly_bytes = ("URL,Replacement,Title\r\nhttps://doi.org/10.1080/08913810508443640,,"
                      "Klein \u2013 Stern\r\n").encode("cp1252")
    with open(readonly, "wb") as fh:
        fh.write(readonly_bytes)
    os.chmod(readonly, 0o444)
    asked = len(seen)
    from_readonly = subprocess.run([sys.executable, tool, readonly, "--wait", "0", "--service",
                                    service], capture_output=True, text=True)
    asked_readonly = len(seen) - asked
    with open(readonly, "rb") as fh:
        readonly_left = fh.read()
    pipe = os.path.join(work, "pipe.csv")
    os.mkfifo(pipe)
    from_pipe = subprocess.run([sys.executable, tool, pipe, "--wait", "0", "--service", service],
                               capture_output=True, text=True, timeout=60)
    # Nor one with another link to it, which writing it would part from it.
    linked = os.path.join(work, "linked.csv")
    linked_bytes = ("\ufeffURL,Replacement,Title\r\n"
                    "https://doi.org/10.1080/08913810508443640,,\r\n").encode("utf-8")
    with open(linked, "wb") as fh:
        fh.write(linked_bytes)
    os.link(linked, os.path.join(work, "linked-too.csv"))
    asked = len(seen)
    from_linked = subprocess.run([sys.executable, tool, linked, "--wait", "0", "--service",
                                  service], capture_output=True, text=True)
    asked_linked = len(seen) - asked
    with open(linked, "rb") as fh:
        linked_left = fh.read()
    with open(os.path.join(work, "linked-too.csv"), "rb") as fh:
        linked_too = fh.read()
    from_readonly_dry = subprocess.run([sys.executable, tool, readonly, "--dry-run", "--service",
                                        service], capture_output=True, text=True)
    # Nothing found, the lookups failing, leaves no copy behind: the sidecar
    # isn't written.
    unknown = os.path.join(work, "unknown.csv")
    with open(unknown, "w", encoding="utf-8", newline="") as fh:
        fh.write("URL,Replacement,Title\nhttps://doi.org/10.9999/not-there,,\n")
    from_unknown = subprocess.run([sys.executable, tool, unknown, "--wait", "0", "--retries", "0",
                                   "--service", service], capture_output=True, text=True)
    # A write that fails partway, as a disk full fails one, made by an open
    # whose file takes half the bytes: the original's put back.
    shortdoi = load(tool, "shortdoi_cut")
    cut = os.path.join(work, "cut.csv")
    cut_bytes = linked_bytes
    with open(cut, "wb") as fh:
        fh.write(cut_bytes)
    opened_files = []

    class Half:
        def __init__(self, fh):
            self.fh = fh

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.fh.close()
            return False

        def write(self, data):
            self.fh.write(data[:len(data) // 2])
            raise OSError(28, "No space left on device")

    def cutting(file, mode="r", *args, **kwargs):
        fh = open(file, mode, *args, **kwargs)
        opened_files.append(mode)
        return Half(fh) if len(opened_files) == 1 else fh
    shortdoi.open = cutting
    cut_said = shortdoi.write_in_place(cut, b"\xef\xbb\xbf" + cut_bytes * 3, cut_bytes)
    with open(cut, "rb") as fh:
        cut_left = fh.read()
    # A copy kept by an earlier run is kept: the sidecar as it was goes
    # under the next name.
    again = os.path.join(work, "again.csv")
    with open(again, "wb") as fh:
        fh.write(linked_bytes)
    with open(again + ".bak", "wb") as fh:
        fh.write(b"an earlier run's")
    from_again = subprocess.run([sys.executable, tool, again, "--wait", "0", "--service", service],
                                capture_output=True, text=True)
    with open(again + ".bak", "rb") as fh:
        again_bak = fh.read()
    again_bak2 = b""
    if os.path.exists(again + ".bak.2"):
        with open(again + ".bak.2", "rb") as fh:
            again_bak2 = fh.read()
    server.shutdown()
    with open(sidecar, "rb") as fh:
        marked = fh.read(6) == b"\xef\xbb\xbfURL"
    with open(sidecar, encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))
    with open(excel, "rb") as fh:
        excel_data = fh.read()
    with open(ansi, "rb") as fh:
        ansi_data = fh.read()
    kept_ansi = b""
    if os.path.exists(ansi + ".bak"):
        with open(ansi + ".bak", "rb") as fh:
            kept_ansi = fh.read()
    return [
        ("--dry-run names the two DOIs and asks nothing",
         lambda: asked_dry == 0 and dry.stdout.count("would look up") == 2),
        ("each DOI without a Replacement gets https://doi.org/ and its shortDOI",
         lambda: rows[1][1] == "https://doi.org/10/b8xx35"
         and rows[2][1] == "https://doi.org/10/zz99"),
        ("a Replacement already there, and an address that isn't a DOI, are left alone",
         lambda: rows[3][1] == "Kept as the author wrote it" and rows[4][1] == ""
         and rows[1][2] == "DOI for Klein and Stern 2005"),
        ("a 429 is waited out and asked again; a created shortDOI is counted",
         lambda: real.returncode == 0 and "1 of them created" in real.stdout),
        ("the DOI is sent encoded once, its parentheses and colons as they are, "
         "with the tool's User-Agent", lambda: any(
             p.startswith("/10.1002/(SICI)1097:15%3C1661%3E?format=json")
             and "TextbookImprover" in agent for p, agent in seen)),
        ("the sidecar as it was is kept beside it",
         lambda: os.path.exists(sidecar + ".bak")),
        ("and the sidecar is written with a byte-order mark, for Excel", lambda: marked),
        ("a sidecar Excel saved is read, a row after a mark of its own too, and written with "
         "one mark", lambda: from_excel.returncode == 0
         and excel_data.decode("utf-8").split("\n")[2].startswith(
             "https://doi.org/10.1080/08913810508443640,https://doi.org/10/b8xx35")
         and excel_data.count(b"\xef\xbb\xbf") == 1 and excel_data.startswith(b"\xef\xbb\xbf")),
        ("one Excel saved as plain CSV, in Windows-1252, is read as written, and written as "
         "UTF-8, the file as it was kept beside it",
         lambda: from_ansi.returncode == 0
         and "ansi.csv isn't UTF-8: it's read as Windows-1252, and written as UTF-8 with the "
         "shortDOIs." in from_ansi.stderr
         and "Traceback" not in from_ansi.stderr
         and ansi_data.startswith(b"\xef\xbb\xbfURL,")
         and "https://doi.org/10/b8xx35,Klein \u2013 Stern" in ansi_data.decode("utf-8")
         and kept_ansi == "URL,Replacement,Title\r\nhttps://doi.org/10.1080/08913810508443640,,"
         "Klein \u2013 Stern\r\n".encode("cp1252")),
        ("a dry run of one Excel saved as plain CSV reads it as the run would and writes nothing",
         lambda: from_dry.returncode == 0
         and "dry.csv isn't UTF-8: it's read as Windows-1252" in from_dry.stderr
         and "would look up https://doi.org/10.1080/08913810508443640" in from_dry.stdout
         and dry_left == dry_bytes
         and not any(n.startswith("dry.csv.") for n in os.listdir(work))),
        ("and one that reads as neither stops it, saying how each reads it, the file left as "
         "it was", lambda: from_odd.returncode != 0
         and "odd.csv isn't UTF-8, and doesn't read as Windows-1252" in from_odd.stderr
         and "Traceback" not in from_odd.stderr and odd_left == stopping),
        ("one it can't write is read, but stops it before anything is looked up, the file left "
         "as it was",
         lambda: from_readonly.returncode != 0 and asked_readonly == 0
         and "readonly.csv can't be written (it's read-only), so no shortDOI could be written "
         "to it, and nothing is looked up." in from_readonly.stderr
         and "Traceback" not in from_readonly.stderr and readonly_left == readonly_bytes
         and not any(n.startswith("readonly.csv.") for n in os.listdir(work))),
        ("and a dry run says a run would stop",
         lambda: from_readonly_dry.returncode == 1
         and "But %s can't be written (it's read-only), so a run without --dry-run would stop "
         "before looking anything up." % readonly in from_readonly_dry.stdout),
        ("and one that can't be read, a pipe here, stops it, never read",
         lambda: from_pipe.returncode != 0
         and "pipe.csv isn't a file but a pipe or a device. Nothing is looked up." in from_pipe.stderr),
        ("one with another link to it is written in its place, so that the other name has it "
         "too, the file as it was kept beside it",
         lambda: from_linked.returncode == 0 and asked_linked == 1
         and linked_left == linked_too
         and linked_left.startswith(b"\xef\xbb\xbfURL,Replacement,Title\n")
         and b"https://doi.org/10/b8xx35" in linked_left
         and os.path.exists(linked + ".bak")),
        ("lookups that all fail write nothing, and leave no copy beside it",
         lambda: from_unknown.returncode == 1 and "0 shortDOI(s) written" in from_unknown.stdout
         and "1 lookup(s) failed" in from_unknown.stdout
         and not any(n.startswith("unknown.csv.") for n in os.listdir(work))),
        ("a write that fails partway, a disk full, gives the file its original back, saying so",
         lambda: cut_said == "No space left on device, and the file is as it was"
         and cut_left == cut_bytes),
        ("a copy an earlier run kept is kept, the sidecar as it was kept under the next name",
         lambda: from_again.returncode == 0 and again_bak == b"an earlier run's"
         and again_bak2 == linked_bytes and "the original is %s.bak.2" % again in from_again.stdout),
    ]


def check_report_rows():
    """A report's rows are sorted whole: a field holding a line end, as an
    image's current alt text can, stays in its row."""
    convert = load(os.path.join(ROOT, "bin", "convert.py"), "convert")
    convert.say = lambda text: None
    work = tempfile.mkdtemp(prefix="report-rows-")
    rows_file = os.path.join(work, "rows.csv")
    report = os.path.join(work, "image-alt-missing.csv")
    with open(rows_file, "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh, lineterminator="\n").writerows([
            ["b.png", "too long", "Its first paragraph.\n\nIts second, after a line end"],
            ["a.png", "missing", ""],
            ["b.png", "too long", "Its first paragraph.\n\nIts second, after a line end"]])
    convert.write_report(rows_file, report, "Image,Reason,CurrentAlt", "image(s)")
    with open(report, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    shutil.rmtree(work, ignore_errors=True)
    return [
        ("each row is whole, the line end in its field kept, sorted and once each",
         lambda: [r["Image"] for r in rows] == ["a.png", "b.png"]
         and rows[1]["CurrentAlt"] == "Its first paragraph.\n\nIts second, after a line end"),
    ]


def check_pdf_summary():
    """The output check's summary gives a PDF's repeated finding once,
    counted, and a single one with its detail."""
    import findings as findings_lib
    check_output = load(os.path.join(ROOT, "bin", "check-output.py"), "check_output")
    found = [findings_lib.Finding("book.pdf", "pdf-figure-alt-is-placeholder",
                                  "picture environment") for _ in range(3)]
    found += [findings_lib.Finding("book.pdf", "pdf-figure-alt-is-file-name", "a.pdf"),
              findings_lib.Finding("other.pdf", "pdf-figure-alt-is-placeholder",
                                   "picture environment")]
    lines = check_output.pdf_summary(found)
    return [
        ("a finding a PDF has three times is one line, counted, saying what it means",
         lambda: lines[0] == "  book.pdf: 3 pdf-figure-alt-is-placeholder: "
         + findings_lib.describe("pdf-figure-alt-is-placeholder")),
        ("one found once keeps its detail, and each PDF is counted apart",
         lambda: lines[1:] == ["  book.pdf: pdf-figure-alt-is-file-name: a.pdf",
                               "  other.pdf: pdf-figure-alt-is-placeholder: picture environment"]),
    ]


def check_pdf_read_quietly():
    """Reading a PDF whose page holds a key twice, as LaTeX writes an
    included figure's transparency group, prints nothing: pypdf's word on
    it isn't a finding."""
    import contextlib
    import io
    import pdfcheck
    if pdfcheck.pypdf is None:
        return [("a PDF with a key twice is read without a word",
                 lambda: print("  skip  no pypdf to read a PDF") or True)]
    work = tempfile.mkdtemp(prefix="pdf-quiet-")
    path = os.path.join(work, "twice.pdf")
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] "
               b"/Group << /S /Transparency >> /Group << /S /Transparency /K false >> >>"]
    data, offsets = bytearray(b"%PDF-1.7\n"), []
    for number, body in enumerate(objects, 1):
        offsets.append(len(data))
        data += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(data)
    data += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    data += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    data += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, xref)
    with open(path, "wb") as fh:
        fh.write(data)
    said = io.StringIO()
    with contextlib.redirect_stderr(said):
        facts, found = pdfcheck.inspect(path)
    shutil.rmtree(work, ignore_errors=True)
    return [
        ("a PDF with a key twice is read without a word, and checked as any other",
         lambda: said.getvalue() == "" and facts.get("pages") == 1
         and "pdf-not-tagged" in {f.check for f in found}),
    ]


def check_pdf_formula_headers():
    """A header cell holding only formulas is found in a PDF's structure,
    and one LaTeX pads with empty marked content; one with words or a
    figure beside its formula isn't, nor a data cell. Types role-mapped to
    TH and Formula count as those, and a formula's content may be an MCR."""
    import pdfcheck
    if pdfcheck.pypdf is None:
        return [("header cells holding only formulas are found",
                 lambda: print("  skip  no pypdf to read a PDF") or True)]
    stream = (b"/Span <</MCID 0>> BDC BT /F1 10 Tf 10 180 Td (q) Tj ET EMC\n"
              b"/Span <</MCID 1>> BDC BT /F1 10 Tf 30 180 Td (Revenue) Tj ET EMC\n"
              b"/Span <</MCID 2>> BDC BT /F1 10 Tf 80 180 Td (p) Tj ET EMC\n"
              b"/Span <</MCID 3>> BDC EMC\n"
              b"/Span <</MCID 4>> BDC BT /F1 10 Tf 10 160 Td (x) Tj ET EMC\n"
              b"/Span <</MCID 5>> BDC BT /F1 10 Tf 30 160 Td (y) Tj ET EMC\n"
              b"/Span <</MCID 6>> BDC BT /F1 10 Tf 60 160 Td (z) Tj ET EMC\n"
              b"/Figure <</MCID 7>> BDC EMC\n"
              b"/Span <</MCID 8>> BDC BT /F1 10 Tf 90 160 Td (w) Tj ET EMC\n")
    elem = b"<< /Type /StructElem /S /%s /P %d 0 R /Pg 3 0 R /K %s >>"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R /StructTreeRoot 5 0 R /MarkInfo << /Marked true >> >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R "
        b"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"endstream",
        b"<< /Type /StructTreeRoot /K 6 0 R /RoleMap << /Equation /Formula /HeaderCell /TH >> >>",
        elem % (b"Document", 5, b"[7 0 R]"),
        elem % (b"Table", 6, b"[8 0 R]"),
        elem % (b"TR", 7, b"[9 0 R 11 0 R 13 0 R 15 0 R 17 0 R 19 0 R]"),
        elem % (b"TH", 8, b"[10 0 R]"),                  # a formula alone
        elem % (b"Formula", 9, b"0"),
        elem % (b"TH", 8, b"[1 12 0 R]"),                # words, then a formula
        elem % (b"Formula", 11, b"2"),
        elem % (b"TH", 8, b"[3 14 0 R]"),                # padding that shows nothing
        elem % (b"Formula", 13, b"4"),
        elem % (b"HeaderCell", 8, b"[16 0 R]"),          # role-mapped, an MCR inside
        elem % (b"Equation", 15, b"<< /Type /MCR /Pg 3 0 R /MCID 5 >>"),
        elem % (b"TD", 8, b"[18 0 R]"),                  # a data cell
        elem % (b"Formula", 17, b"6"),
        elem % (b"TH", 8, b"[20 0 R 21 0 R]"),           # a figure beside a formula
        elem % (b"Figure", 19, b"7"),
        elem % (b"Formula", 19, b"8"),
    ]
    data, offsets = bytearray(b"%PDF-1.7\n"), []
    for number, body in enumerate(objects, 1):
        offsets.append(len(data))
        data += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(data)
    data += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    data += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    data += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, xref)
    work = tempfile.mkdtemp(prefix="pdf-headers-")
    path = os.path.join(work, "headers.pdf")
    with open(path, "wb") as fh:
        fh.write(data)
    _, found = pdfcheck.inspect(path)
    shutil.rmtree(work, ignore_errors=True)
    headers = [f.detail for f in found if f.check == "pdf-table-header-is-formula"]
    return [
        ("a header cell holding only a formula, or padding beside it, is found, "
         "a role-mapped one too; one with words or a figure isn't, nor a data cell",
         lambda: headers == ["page 1, table 1, header 1", "page 1, table 1, header 3",
                             "page 1, table 1, header 4"]
         or print("        got %r" % (headers,))),
    ]


def check_drawings_without_preview():
    """A LaTeX book's drawings, where LaTeX lacks the preview package each
    is made a page of: said once, as what to install, not as LaTeX's log
    for each; any other failure is still LaTeX's own words."""
    import latexsource
    work = tempfile.mkdtemp(prefix="drawings-")
    tools = os.path.join(work, "bin")
    os.makedirs(tools)
    os.makedirs(os.path.join(work, "book"))

    def fake(error):
        with open(os.path.join(tools, "pdflatex"), "w") as fh:
            fh.write("#!/bin/sh\ncat <<'END'\n%s\nEND\nexit 1\n" % error)
        with open(os.path.join(tools, "pdftocairo"), "w") as fh:
            fh.write("#!/bin/sh\nexit 1\n")
        for name in ("pdflatex", "pdftocairo"):
            os.chmod(os.path.join(tools, name), 0o755)

    def said(error):
        fake(error)
        lines = []
        path = os.environ.get("PATH", "")
        os.environ["PATH"] = tools + os.pathsep + path
        try:
            latexsource.render(os.path.join(work, "book"), os.path.join(work, "w"),
                               "\\documentclass{article}\n\\begin{document}",
                               [("rendered/a.svg", "\\begin{picture}(1,1)\\end{picture}"),
                                ("rendered/b.svg", "\\begin{picture}(2,2)\\end{picture}")],
                               lines.append)
        finally:
            os.environ["PATH"] = path
        return "\n".join(lines)
    missing = said("! LaTeX Error: File `preview.sty' not found.")
    other = said("! Undefined control sequence.")
    shutil.rmtree(work, ignore_errors=True)
    return [
        ("without the preview package, the drawings say what to install, once",
         lambda: "tlmgr install preview" in missing and missing.count("WARNING") == 1
         and "The end of its output" not in missing),
        ("and another failure is LaTeX's own words",
         lambda: "Undefined control sequence" in other and "preview package" not in other),
    ]


def check_tlmgr_command():
    """A tlmgr command the run suggests has sudo before it where the TeX
    tree isn't the user's to write (TeX Live installed with sudo), and
    tlmgr named by its path, the one beside kpsewhich, since sudo looks
    for a program in folders of its own (Ubuntu's secure_path); and none
    where it is (TinyTeX in the home folder) or where there's no TeX to
    ask."""
    import latexbuild
    work = tempfile.mkdtemp(prefix="tex-root-")
    bin_dir = os.path.join(work, "tex live", "bin")
    os.makedirs(bin_dir)
    for name in ("kpsewhich", "tlmgr"):
        open(os.path.join(bin_dir, name), "w").close()
    saved_root, saved_access = list(latexbuild._TEX_ROOT), os.access
    saved_which = latexbuild.shutil.which
    try:
        latexbuild._TEX_ROOT[:] = [work]
        own = latexbuild.tlmgr_command("install preview")
        os.access = lambda path, mode: False
        # A distribution's tlmgr first on the path, as sudo would find it,
        # and TeX Live's beside the kpsewhich that named the tree.
        latexbuild.shutil.which = lambda name: {"kpsewhich": os.path.join(bin_dir, name),
                                                "tlmgr": "/usr/bin/tlmgr"}.get(name)
        system = latexbuild.tlmgr_command("install preview")
        latexbuild.shutil.which = lambda name: None
        unfound = latexbuild.tlmgr_command("install preview")
        latexbuild._TEX_ROOT[:] = [""]
        unknown = latexbuild.tlmgr_command("install preview")
    finally:
        latexbuild._TEX_ROOT[:] = saved_root
        os.access = saved_access
        latexbuild.shutil.which = saved_which
        shutil.rmtree(work, ignore_errors=True)
    return [
        ("a TeX the user can write is managed without sudo",
         lambda: own == "tlmgr install preview"),
        ("one installed with sudo gets sudo, and tlmgr by its path, the one beside "
         "kpsewhich, quoted",
         lambda: system == "sudo '%s' install preview" % os.path.join(bin_dir, "tlmgr")),
        ("and by its name where it can't be found",
         lambda: unfound == "sudo tlmgr install preview"),
        ("and with no TeX to ask, the plain command",
         lambda: unknown == "tlmgr install preview"),
    ]


def check_fitted_blanks():
    """The build's count of lines too wide for their text, read from what
    LaTeX said: a line whose fill-in blank PDF_MACROS drew shorter to fit,
    which LaTeX had reported as too wide, is as wide as it is now, matched
    by the width LaTeX gave and the line of LaTeX its paragraph ended on;
    and the Lua that draws it has nothing TeX would read as its own, since
    TeX reads it before Lua does, its lines joined."""
    import latexbuild
    source = "\n".join(["\\label{page-quiz}"] + ["Words."] * 60)
    said = ("Overfull \\hbox (24.27022pt too wide) in paragraph at lines 10--13\n"
            "[]\\TU/LatinModernRoman(0)/m/n/10 The Rat-ing ... ________________ \n"
            "TextbookImprover blank: 24.27022pt over at line 13, now 0.0pt\n\n"
            "Overfull \\hbox (12.5pt too wide) in paragraph at lines 20--22\n"
            "TextbookImprover blank: 12.5pt over at line 22, now 4.25pt\n\n"
            "Overfull \\hbox (8.0pt too wide) in paragraph at lines 30--33\n"
            "TextbookImprover blank: 8.0pt over at line 34, now 0.0pt\n\n"
            "Overfull \\hbox (9.0pt too wide) in paragraph at lines 40--41\n"
            "Overfull \\hbox (6.0pt too wide) in paragraph at lines 40--41\n"
            "TextbookImprover blank: 6.0pt over at line 41, now 0.0pt\n")
    found = latexbuild.overfull_lines(said, source, {"page-quiz": "quiz"})
    # And a line too wide in the contents, and one in a list of figures,
    # which TeX reports at a line of the list's own file, between the marks
    # PDF_MACROS has LaTeX write around each list.
    listed = ("TextbookImprover list: toc\n"
              "Overfull \\hbox (8.67996pt too wide) detected at line 6\n"
              " []\\TU/LatinModernRoman(0)/m/n/10 xxviii\n\n"
              "TextbookImprover list end\n"
              "TextbookImprover list: lof\n"
              "Overfull \\hbox (12.0pt too wide) in paragraph at lines 3--3\n"
              "TextbookImprover list end\n"
              "Overfull \\hbox (5.0pt too wide) in paragraph at lines 20--22\n")
    lists = latexbuild.overfull_lines(listed, source, {"page-quiz": "quiz"})
    warning = latexbuild.overfull_warning(lists) or ""
    # Each chunk of Lua PDF_MACROS gives \directlua{...} at its own level,
    # the blanks' and the fitting's, to its closing brace; the calls inside
    # a macro, \directlua { ... }, hold its arguments (#1).
    macros = latexbuild.PDF_MACROS
    chunks = []
    for opening in re.finditer(r"\\directlua\{", macros):
        depth, end = 1, opening.end()
        while depth and end < len(macros):
            depth += {"{": 1, "}": -1}.get(macros[end], 0)
            end += 1
        chunks.append(macros[opening.end():end - 1])
    lua = "\n".join(chunks)
    return [
        ("a line whose blank was drawn shorter to fit it isn't counted",
         lambda: not any(points == 24.27022 for points, _kind, _page in found)),
        ("one still too wide is counted as wide as it is now",
         lambda: (4.25, "text", "quiz") in found
         and not any(points == 12.5 for points, _kind, _page in found)),
        ("a fitted line is matched by its paragraph's last line and its width, "
         "and no other line is taken for it",
         lambda: sorted(found) == [(4.25, "text", "quiz"), (8.0, "text", "quiz"),
                                   (9.0, "text", "quiz")]),
        ("a line too wide in the contents or a list of figures is the list's, on no page",
         lambda: sorted(lists, key=lambda f: f[0]) == [
             (5.0, "text", "quiz"), (8.67996, "contents", None), (12.0, "list", None)]),
        ("and the warning says so",
         lambda: "1 line(s) of text, 1 in the contents, 1 in a list of figures or tables; "
         "the widest is in a list of figures or tables, 12 points too wide; on 1 page(s), "
         "widest first: quiz." in warning),
        ("the Lua has no percent sign, hash, tilde, or backslash, and no comment, the "
         "blanks' or the fitting's",
         lambda: len(chunks) == 2 and all(c.strip() for c in chunks)
         and not re.search(r"[%#~\\]|--", lua)),
    ]


def check_code_fit_report():
    """The build's reports of what FIT_MACROS fitted and what's still too
    wide, read from what LaTeX said, with blocks of code among them, each
    between the lines \\OERFitCode and \\OERFitCodeEnd print: a line of
    LaTeX's verbatim still too wide, which LaTeX reports as a line of text,
    isn't counted among the lines too wide, nor a footnote's, which LaTeX
    reports at a line of the file it's read from, here the book's fourth, a
    line of text; a footnote's own paragraph, which LaTeX reports at the
    line its text ends on, the footnote's last block's \\OERFitCodeEnd, is,
    and so is a line of text after it; and the fit report names a block as
    code running into the margin, and warns of a block too wide for the
    paper with the tables and formulas."""
    import latexbuild
    source = "\n".join(["\\label{page-code}", "Words one.", "", "Words two.", "",
                        "\\OERFitCode{1}", "", "\\begin{verbatim}", "Marginline",
                        "\\end{verbatim}", "", "\\OERFitCodeEnd{1}", "",
                        "Words.\\footnote{Its words.", "", "\\OERFitCode{2}",
                        "\\OERCodeFile{oer-code-1.tex}", "\\OERFitCodeEnd{2}}"])
    said = ("TextbookImprover code\n"
            "Overfull \\hbox (43.1pt too wide) in paragraph at lines 9--9\n"
            "TextbookImprover code end\n"
            "Overfull \\hbox (202.0pt too wide) in paragraph at lines 18--18\n"
            "TextbookImprover code\n"
            "(./oer-code-1.tex\n"
            "Overfull \\hbox (44.0pt too wide) in paragraph at lines 4--4\n"
            ")\n"
            "TextbookImprover code end\n"
            "Overfull \\hbox (5.0pt too wide) in paragraph at lines 14--18\n"
            "TextbookImprover fit: run 2, 0 narrowed, 2 smaller, smallest 0.5\n"
            "TextbookImprover fit wide: c 43.1 6 0.75 0 1 0\n"
            "TextbookImprover fit wide: c 301.0 6 0.5 0 0 0\n")
    owners = {"page-code": "code"}
    found = latexbuild.overfull_lines(said, source, owners)
    report = latexbuild.fit_report(said, source, owners)
    return [
        ("a line of a block of code LaTeX reports as too wide isn't counted among the lines "
         "too wide, nor a footnote's, reported at a line of its own file, and a footnote's "
         "words, reported at the line of its last block's mark, are, and a line of text "
         "after them",
         lambda: found == [(202.0, "text", "code"), (5.0, "text", "code")]),
        ("the fit report counts the blocks of code it fitted, names one still wider than the "
         "text, running into the margin, and warns of one too wide for the paper",
         lambda: report == [
             "Fitted 2 table(s), formula(s), and block(s) of code too wide for their lines to "
             "them: 2 in smaller type, the smallest at 50% of its size.",
             "1 block(s) of code, still wider than the text in smaller type, the smallest at "
             "75% of its size, runs into the margin on its right, the widest 43 points wider: "
             "on code.",
             "WARNING: 1 table(s), formula(s), or block(s) of code are too wide for the paper "
             "even in smaller type, the smallest at 50% of its size, and run to within a "
             "quarter inch of its edge or past it, the widest 301 points wider than the text: "
             "on code."]),
        ("a block of code wider than its line, a quotation's, but not past the text's edge, "
         "isn't named as running into the margin",
         lambda: latexbuild.fit_report(
             "TextbookImprover fit: run 2, 0 narrowed, 1 smaller, smallest 0.75\n"
             "TextbookImprover fit wide: c 0.0 6 0.75 0 1 0\n", source, owners)
         == ["Fitted 1 table(s), formula(s), and block(s) of code too wide for their lines "
             "to them: 1 in smaller type, the smallest at 75% of its size."]),
    ]


def check_tex_packages():
    """The installation page's commands for TeX install every package the
    run and the suites check for, what a deck's PDF needs and what the
    LaTeX, PDF, and decks suites' books and decks load, each line a command
    of its own: copied, two names at a line break had once run together
    ("soultabto-ltx")."""
    page = open(os.path.join(ROOT, "docs", "installation.md"), encoding="utf-8").read()
    section = page.split("### Everything at once", 1)[-1].split("\n### ", 1)[0]
    block = re.search(r"```bash\n(.*?)```", section, re.S)
    lines = block.group(1).splitlines() if block else []
    named = {word for line in lines if line.startswith("tlmgr install ")
             for word in line.split()[2:]}
    books = []
    for name in ("run-latex-tests.py", "run-pdf-tests.py", "run-decks-tests.py"):
        suite = open(os.path.join(HERE, name), encoding="utf-8").read()
        listed = re.search(r"^SUITE_TEX = \[(.*?)\]$", suite, re.S | re.M)
        books.append(re.findall(r'\("([\w-]+)", "[^"]+"\)', listed.group(1)) if listed else [])
    import decks
    talk = [package for _, package in decks.LTX_TALK_FILES]
    return [
        ("the installation page installs every TeX package a deck's PDF and the LaTeX, "
         "PDF, and decks suites' books and decks need",
         lambda: all(books) and set(sum(books, []) + talk) <= named),
        ("each line of it a command of its own",
         lambda: named and not any(line.rstrip().endswith("\\") for line in lines)),
    ]


def check_default_page():
    """The PDF target's default page is written down twice: in
    bin/pdf-layout.yaml, which build-pdf.py reads and unpack-cnx.py copies
    into an OpenStax book's folder, and on the configuration page, for a
    person to read and copy. The two agree, comments and all; and so do
    the page for WCAG 1.4.8 (AAA), bin/pdf-layout-wcag-aaa.yaml, and its
    copy there. That page is the default with larger type and more space:
    every field the default sets, the same paper and margins."""
    page = open(os.path.join(ROOT, "docs", "configuration.md"), encoding="utf-8").read()
    section = page.split("\n### The PDF's page\n", 1)[-1].split("\n### ", 1)[0]
    blocks = re.findall(r"```yaml\n(.*?)```", section, re.S)
    with open(os.path.join(ROOT, "bin", "pdf-layout.yaml"), encoding="utf-8") as fh:
        default = fh.read()
    with open(os.path.join(ROOT, "bin", "pdf-layout-wcag-aaa.yaml"), encoding="utf-8") as fh:
        aaa = fh.read()
    fields, aaa_fields = yaml.safe_load(default), yaml.safe_load(aaa)
    return [
        ("the configuration page shows bin/pdf-layout.yaml as it is",
         lambda: "\n### The PDF's page\n" in page and blocks and blocks[0] == default),
        ("and bin/pdf-layout-wcag-aaa.yaml as it is",
         lambda: aaa in blocks),
        ("which sets every field the default does, on the default's paper and margins",
         lambda: set(fields) <= set(aaa_fields)
         and all(aaa_fields[k] == fields[k] for k in ("papersize", "geometry"))),
    ]


def check_ua1_math():
    """A PDF/UA-1 file's formulas get Office's MathML attribute by default,
    which NVDA read as math in Acrobat where it read the TeX alt text
    aloud; the alt text and attached file alone stay a choice."""
    build_pdf = load(os.path.join(ROOT, "bin", "build-pdf.py"), "build_pdf")
    schema = oerconfig.load_schema(os.path.join(ROOT, "bin", "schema-conversion.yaml"))
    project = oerconfig.load_schema(os.path.join(ROOT, "lib", "schema-project.yaml"))

    def chosen(pdf):
        document = oerconfig.Document(
            {"targets": {"pdf": {"format": "pdf", "pdf": pdf}}}, "conversion.yaml")
        return str(oerconfig.resolve(schema, project, [document], target="pdf")["pdf.ua1_math"])

    return [
        ("office is the default", lambda: chosen({"standard": ["ua-1"]}) == "office"),
        ("alt can still be chosen",
         lambda: chosen({"standard": ["ua-1"], "ua1_math": "alt"}) == "alt"),
        ("office writes Office's attribute beside the attached file",
         lambda: build_pdf.math_setup(["ua-1"], "office") == "mathml-AF,mathml-MS"),
        ("alt writes the attached file alone",
         lambda: build_pdf.math_setup(["ua-1"], "alt") == "mathml-AF"),
        ("PDF/UA-2 takes structure elements whichever is set",
         lambda: build_pdf.math_setup(["ua-2"], "office")
         == build_pdf.math_setup(["ua-2"], "alt") == "mathml-SE,mathml-AF"),
    ]


def check_display_style_in_text():
    """lib/mathstyle.py: a formula in running text an HTML page sets in
    display style, where display style changes it, put in a span of class
    displaystyle-text for math-repair.lua; the rest of the page as it was,
    a comment, an attribute, and a script whatever they hold; and no HTML
    parser needed to read the formula."""
    import mathstyle
    m = '<math xmlns="http://www.w3.org/1998/Math/MathML">%s</math>'
    on = '<mstyle displaystyle="true">%s</mstyle>'
    fraction = m % (on % "<mfrac><mn>1</mn><mn>2</mn></mfrac>")
    sum_ = m % (on % "<munderover><mo>&#x2211;</mo><mi>i</mi><mi>n</mi></munderover>")
    letter = m % (on % "<mi>x</mi>")
    scripted = m % (on % "<msup><mi>y</mi><mfrac><mn>1</mn><mn>3</mn></mfrac></msup>")
    accent = m % (on % '<mover><mi>x</mi><mo>&#x2192;</mo></mover>')
    off_inside = m % (on % '<mstyle displaystyle="false"><mfrac><mn>1</mn><mn>4</mn></mfrac>'
                      '</mstyle>')
    own = ('<math xmlns="http://www.w3.org/1998/Math/MathML" displaystyle="true">'
           '<mfrac><mn>1</mn><mn>5</mn></mfrac></math>')
    block = fraction.replace("<math ", '<math display="block" ')
    marked = '<span class="displaystyle">%s</span>' % fraction
    page = ("<p>" + " | ".join((fraction, sum_, letter, scripted, accent, off_inside, own,
                                 block, marked)) + "<br/></p>")
    out, count = mathstyle.marked_in_text(page)

    def wrapped(formula):
        return '<span class="displaystyle-text">%s</span>' % formula

    def without_parser():
        """The page marked the same with no HTML parser installed, where
        reading each formula with one (htmlparse) had stopped the run."""
        import htmlparse
        kept = htmlparse.BACKEND
        htmlparse.BACKEND = None
        try:
            return mathstyle.marked_in_text(page) == (out, count)
        except SystemExit:
            return False
        finally:
            htmlparse.BACKEND = kept
    return [
        ("a fraction, a sum's limits, and a formula whose math element says so are marked",
         lambda: count == 3 and all(wrapped(f) in out for f in (fraction, sum_, own))),
        ("a letter, a fraction in a script, an accent, and a fraction display style turns "
         "off again aren't, nor a display formula, nor one marked already",
         lambda: all(wrapped(f) not in out
                     for f in (letter, scripted, accent, off_inside, block))
         and out.count("displaystyle-text") == 3
         and out.count('<span class="displaystyle">') == 1),
        ("the rest of the page is as it was, a formula at a time edited as text",
         lambda: out.replace('<span class="displaystyle-text">', "").replace(
             "</span>", "") == page.replace("</span>", "")),
        ("a page with no display style is returned as it was",
         lambda: mathstyle.marked_in_text("<p>" + m % "<mi>x</mi>" + "</p>")
         == ("<p>" + m % "<mi>x</mi>" + "</p>", 0)),
        ("a formula is found as an HTML parser finds it: the words <math> in a comment, in "
         "an attribute's value, an empty formula, and a formula in a script are left as "
         "they are, and the formula after each is marked, its span its own",
         lambda: all(mathstyle.marked_in_text(before + fraction + " after</p>")
                     == (before + wrapped(fraction) + " after</p>", 1)
                     for before in ('<p lang="fr">Before <!-- the <math> element --> then ',
                                    '<p><img alt="Diagram of the <math> element"/> then ',
                                    '<p><math/> then ',
                                    '<p><script type="math/mml">%s</script> then ' % fraction))),
        ("and the page as it marks it is marked no more",
         lambda: mathstyle.marked_in_text(out) == (out, 0)),
        ("and it's marked the same with no HTML parser installed, html5lib or lxml",
         without_parser),
    ]


def check_math_words():
    """A word or a unit an HTML page's formula holds as an <mi> of more than
    two letters, or of two set upright or applied as a function, is made an
    <mtext>, which Pandoc reads whole and upright, where it read the <mi> as
    italic letters. What could be a product, a name Pandoc keeps whole, and
    a style it would write as TeX it can't read back are left to it."""
    import htmlrepair

    def made(mi):
        return htmlrepair.words_as_text("<math>%s</math>" % mi)[0][6:-7]

    page = ('<p><math><mi mathvariant="normal">Value</mi><mo>=</mo><mi>dx</mi>'
            '</math> and <m:math xmlns:m="http://www.w3.org/1998/Math/MathML">'
            '<m:mi>MeV</m:mi></m:math></p>')
    once, count = htmlrepair.words_as_text(page)
    return [
        ("a word of more than two letters is text, with what else its tag says",
         lambda: made('<mi mathvariant="normal">Value</mi>')
         == '<mtext mathvariant="normal">Value</mtext>'
         and made('<mi class="unit">MeV</mi>') == '<mtext class="unit">MeV</mtext>'),
        ("in bold too, which Pandoc writes \\textbf",
         lambda: made('<mi mathvariant="bold">Total</mi>')
         == '<mtext mathvariant="bold">Total</mtext>'),
        ("words with spaces, a no-break space among them, in any letters",
         lambda: made("<mi>rozpad na sekundę</mi>") == "<mtext>rozpad na sekundę</mtext>"
         and made("<mi>miliardów&#xa0;lat</mi>") == "<mtext>miliardów&#xa0;lat</mtext>"),
        ("two letters stay, as a product might be, in bold too",
         lambda: made("<mi>dx</mi>") == "<mi>dx</mi>"
         and made("<mi>dx</mi><mo>+</mo>") == "<mi>dx</mi><mo>+</mo>"
         and made('<mi mathvariant="bold">AB</mi>') == '<mi mathvariant="bold">AB</mi>'),
        ("but two set upright are text, as a unit or an element's symbol is, "
         "one letter twice among them",
         lambda: made('<mi mathvariant="normal">kg</mi>')
         == '<mtext mathvariant="normal">kg</mtext>'
         and made('<mi mathvariant="normal">mm</mi>')
         == '<mtext mathvariant="normal">mm</mtext>'),
        ("and so are two applied as a function, the Polish tangent",
         lambda: made("<mi>tg</mi> <mo> \u2061 </mo><mi>x</mi>")
         == "<mtext>tg</mtext> <mo> \u2061 </mo><mi>x</mi>"
         and made('<mi>tg</mi><mo form="prefix">&#x2061;</mo>')
         == '<mtext>tg</mtext><mo form="prefix">&#x2061;</mo>'
         and made("<mi>tg</mi><mo>&ApplyFunction;</mo>")
         == "<mtext>tg</mtext><mo>&ApplyFunction;</mo>"),
        ("a name Pandoc keeps whole stays, an operator",
         lambda: made("<mi>sin</mi>") == "<mi>sin</mi>"
         and made("<mi>lim</mi>") == "<mi>lim</mi>"),
        ("one letter over and over stays, a product written out",
         lambda: made("<mi>xxxxx</mi>") == "<mi>xxxxx</mi>"),
        ("an italic or bold italic word stays: Pandoc's \\textit{\\textbf{}} is TeX "
         "it can't read back",
         lambda: made('<mi mathvariant="italic">Value</mi>') == '<mi mathvariant="italic">Value</mi>'
         and made('<mi mathvariant="bold-italic">Value</mi>')
         == '<mi mathvariant="bold-italic">Value</mi>'),
        ("anything but letters and spaces stays",
         lambda: made("<mi>(CPA)</mi>") == "<mi>(CPA)</mi>"),
        ("a prefixed element keeps its prefix, and each is counted once",
         lambda: '<m:mtext>MeV</m:mtext>' in once and count == 2
         and htmlrepair.words_as_text(once) == (once, 0)),
        ("a page's repair does it",
         lambda: htmlrepair.repaired(page)[0] == once),
    ]



def check_head_only_tables():
    """A table whose <thead> holds every row, its rows of data too, is
    given a body of them before Pandoc reads it, which made every row in a
    <thead> a header row: from the first row holding a data cell with
    something in it, a picture or a formula as much as words. A head with a
    body after it, or holding a table, is left as it is."""
    import htmlrepair

    def divided(head, after="</table>"):
        return htmlrepair.body_out_of_head("<table><thead>%s</thead>%s" % (head, after))
    header = "<tr><th>K</th><th>V</th></tr>"
    data = "<tr><td>a</td><td>1</td></tr>"
    return [
        ("the rows from the first of data are a body after the head",
         lambda: divided(header + data + data)
         == ("<table><thead>" + header + "</thead><tbody>" + data + data + "</tbody></table>", 1)),
        ("a row of header cells with an empty <td> in its corner stays the head, as does "
         "a second header row, but a row of a <th> and data is the body's",
         lambda: divided("<tr><td> &nbsp;</td><th>A</th></tr>" + header
                         + "<tr><th>x</th><td>1</td></tr>")[0]
         == ("<table><thead><tr><td> &nbsp;</td><th>A</th></tr>" + header
             + "</thead><tbody><tr><th>x</th><td>1</td></tr></tbody></table>")),
        ("a data cell holding only a picture or a formula is data",
         lambda: divided(header + '<tr><td><img src="a.png" alt="A"></td><td></td></tr>')[1] == 1
         and divided(header + "<tr><td><math><mi>x</mi></math></td></tr>")[1] == 1),
        ("a head whose first row is data is all body, its attributes kept",
         lambda: htmlrepair.body_out_of_head('<table><THEAD class="h">' + data + data
                                             + "</THEAD></table>")
         == ('<table><tbody class="h">' + data + data + "</tbody></table>", 1)),
        ("a head with a body after it, or with rows of the table's own, stays as it is",
         lambda: divided(header + data, "<tbody>" + data + "</tbody></table>")[1] == 0
         and divided(header + data, data + "</table>")[1] == 0),
        ("so does a head holding a table, and one of header rows only",
         lambda: divided("<tr><th><table><tr><td>1</td></tr></table></th></tr>" + data)[1] == 0
         and divided(header + header)[1] == 0),
        ("a page's repair does it, to each such table on the page",
         lambda: htmlrepair.repaired("<table><thead>" + header + data + "</thead></table>"
                                     "<table><thead>" + header + data + "</thead></table>")[0]
         .count("<tbody>") == 2),
    ]

def check_decorative_marker():
    """The decorative marker, read alike by the filter and the Python.

    The filter took "decorative" in any case; the Python that writes a
    book's decisions into its sources took only "[decorative]", so a row
    saying "Decorative" made the image decorative on the pages and gave
    the author's copy the alt text "Decorative".
    """
    import sidecars
    import docxremediate
    import htmlremediate
    work = tempfile.mkdtemp(prefix="decorative-")
    sidecar = os.path.join(work, "image-alt.csv")
    with open(sidecar, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Image", "Alt"])
        writer.writerow(["ch1/media/rId7.png", "Decorative"])
        writer.writerow(["ch1/media/rId8.png", " [DECORATIVE] "])
        writer.writerow(["ch1/media/rId9.png", "A decorative border"])
    word = docxremediate.alt_rows(sidecar).get("ch1", {})
    pages = htmlremediate.alt_rows(sidecar)
    with open(os.path.join(ROOT, "bin", "figures-and-tables.lua"), encoding="utf-8") as fh:
        lua = fh.read()
    block = re.search(r"local DECORATIVE_MARKERS = \{(.*?)\}", lua, re.S)
    lua_markers = set(re.findall(r"\['([^']*)'\]\s*=\s*true", block.group(1))) if block else set()
    shutil.rmtree(work, ignore_errors=True)
    return [
        ("the Word copies take the marker in any case",
         lambda: word.get("rId7", "") is None and word.get("rId8", "") is None),
        ("and so do the HTML, Markdown, and LaTeX copies",
         lambda: pages.get("ch1/media/rId7", "") is None
         and pages.get("ch1/media/rId8", "") is None),
        ("a description that only mentions the word is a description",
         lambda: word.get("rId9") == "A decorative border"
         and pages.get("ch1/media/rId9") == "A decorative border"),
        ("the filter's list and the Python's are the same list",
         lambda: lua_markers == set(sidecars.DECORATIVE_MARKERS)),
    ]


def check_sidecar_marks():
    """Sidecars as Excel saves them, a byte-order mark first, with files
    appended to them as a person adds rows: a report, its header row
    after a mark of its own, and rows saved without a header, a mark
    before the first. Every reader takes each row, keyed as written.

    The readers had read a sidecar as plain UTF-8, or dropped only the
    mark at the file's start. page-names.csv saved by Excel named no page
    at all, its first column the mark and "source", and table-headers.py
    warned of a header row's "headers". A header row after a mark was a
    row: of languages.csv, whose language isn't a tag; of
    slide-titles.csv, a slide no deck has; and of reading-order.csv, an
    order that isn't a list of ids. math-keep.csv's header row was a row
    anywhere but first, math that kept nothing. And a row after a mark
    was keyed on the mark and its key.
    """
    import docxremediate
    import htmlremediate
    import languages
    import pptxremediate
    import sidecars
    convert = load(os.path.join(ROOT, "bin", "convert.py"), "convert_marks")
    headers = load(os.path.join(ROOT, "bin", "table-headers.py"), "table_headers_marks")
    split = load(os.path.join(ROOT, "bin", "split-pages.py"), "split_pages_marks")
    work = scratch("sidecar-marks-")
    mark = "\ufeff"

    def sidecar(name, header, first, second, third):
        """The header and a row as Excel saves them, a report appended
        whole, and a row Excel saved without a header appended."""
        path = os.path.join(work, name)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(mark + header + "\r\n" + first + "\r\n" + mark + header + "\r\n"
                     + second + "\r\n" + mark + third + "\r\n")
        return path

    alt = sidecar("image-alt.csv", "Image,Alt,Source,Reason,CurrentAlt,Drafted by,Reviewed",
                  "ch1/media/rId7.png,One,ch1,missing,,claude,",
                  "ch1/media/rId8.png,Two,ch1,missing,,claude,",
                  "ch1/media/rId9.png,Three,ch1,missing,,claude,RS")
    links = sidecar("bare-links.csv", "URL,Replacement,Title,Source,Context,Drafted by,Reviewed",
                    "https://example.org/a,,Page A,ch1,,,",
                    "https://example.org/b,,Page B,ch1,,,",
                    "https://example.org/c,,Page C,ch1,,,")
    tables = sidecar("table-headers.csv", ",".join(headers.SIDECAR_COLUMNS),
                     "aaa,first-row,,,,ch1.docx,,,TI,",
                     "bbb,both,,,,ch1.docx,,,TI,",
                     "ccc,none,,,,ch1.docx,,,,RS")
    names = sidecar("page-names.csv", "source,parents,heading,position,name",
                    "ch1.docx,,Introduction,,intro",
                    "ch1.docx,,Methods,,methods",
                    "ch2.docx,,Results,,results")
    language = sidecar("languages.csv", ",".join(languages.SIDECAR_COLUMNS),
                       "ch1,fr,,,", "ch2,de,,,", "ch3,es-MX,,,")
    titles = sidecar("slide-titles.csv", "Slide,Title,Source,Drafted by,Reviewed",
                     "deck/slide-256,One,,,", "deck/slide-257,Two,,,", "deck/slide-258,Three,,,")
    orders = sidecar("reading-order.csv", "Slide,Order,Source,Shapes,Note,Drafted by,Reviewed",
                     "deck/slide-256,2 3,,,,,", "deck/slide-257,3 2,,,,,", "deck/slide-258,4,,,,,")
    keep = sidecar("math-keep.csv", "Kind,Page,Before,After",
                   "symbol,,\u03bc,\u03bc", "expression,,\u03bc = 5.51,\u03bc=5.51",
                   "equation,ch1,5 \u00b5m,")
    found = os.path.join(work, "bare-links-found")
    with open(found, "w", encoding="utf-8", newline="") as fh:
        for url in ("https://example.org/a", "https://example.org/b", "https://example.org/c"):
            fh.write("decided,%s,,ch1,See\n" % url)
    said = []
    convert.say = said.append
    convert.write_bare_links(found, os.path.join(work, "bare-links-new.csv"), links)
    warned = []
    table_rows = headers.read_sidecar(tables, warned.append)
    unknown = set()
    deck_tables = pptxremediate.header_rows(tables, unknown)
    language_rows, problems = languages.read_rows(language)
    bad = []
    order_rows = pptxremediate.order_rows(orders, bad)
    ansi = os.path.join(work, "ansi.csv")
    with open(ansi, "w", encoding="cp1252", newline="") as fh:
        fh.write("Image,Alt\r\nch1/media/rId7.png,Caf\u00e9\r\n")
    mac = os.path.join(work, "mac.csv")
    with open(mac, "w", encoding="cp1252", newline="") as fh:
        fh.write("Image,Alt\rch1/media/rId7.png,One\rch1/media/rId8.png,Caf\u00e9\r")
    return [
        ("image-alt.csv's rows are each read, by the pages', the Word copies', and the decks' "
         "readers, the header row after a mark no row of any",
         lambda: htmlremediate.alt_rows(alt) == {"ch1/media/rId%d" % n: alt_text for n, alt_text
                                                 in ((7, "One"), (8, "Two"), (9, "Three"))}
         and docxremediate.alt_rows(alt) == {"ch1": {"rId7": "One", "rId8": "Two",
                                                     "rId9": "Three"}}
         and set(pptxremediate.alt_rows(alt)) == {"ch1/media/rId7", "ch1/media/rId8",
                                                  "ch1/media/rId9"}),
        ("and so are bare-links.csv's, and none is named a row matching no bare link",
         lambda: htmlremediate.link_rows(links)
         == {"https://example.org/" + x: ("", "Page " + x.upper()) for x in "abc"}
         and docxremediate.link_titles(links) == {"https://example.org/" + x: "Page " + x.upper()
                                                  for x in "abc"}
         and set(pptxremediate.link_rows(links)) == {"https://example.org/" + x for x in "abc"}
         and said == []),
        ("table-headers.csv's, with no warning of a header row's value, and with its "
         "review columns", lambda: set(table_rows) == {"aaa", "bbb", "ccc"} and warned == []
         and headers.has_review_columns(tables)
         and deck_tables == {"aaa": "first-row", "bbb": "both", "ccc": "none"}
         and unknown == set()),
        ("page-names.csv's, as split-pages.py keys them, the header row after a mark no row",
         lambda: split.read_sidecar(names)
         == {("ch1.docx", "", "Introduction", ""): "intro",
             ("ch1.docx", "", "Methods", ""): "methods",
             ("ch2.docx", "", "Results", ""): "results"}),
        ("languages.csv's, its header row after a mark no row",
         lambda: dict(language_rows) == {"ch1": "fr", "ch2": "de", "ch3": "es-MX"}
         and problems == []),
        ("slide-titles.csv's and reading-order.csv's, no header row among them",
         lambda: pptxremediate.title_rows(titles) == {"deck/slide-256": "One",
                                                      "deck/slide-257": "Two",
                                                      "deck/slide-258": "Three"}
         and order_rows == {"deck/slide-256": ["2", "3"], "deck/slide-257": ["3", "2"],
                            "deck/slide-258": ["4"]} and bad == []),
        ("math-keep.csv's, a header row anywhere skipped",
         lambda: sidecars.math_keep_rows(keep) == [("symbol", "", "\u03bc"),
                                                   ("expression", "", "\u03bc = 5.51"),
                                                   ("equation", "ch1", "5 \u00b5m")]),
        ("the run counts the drafted rows not reviewed, the header rows none of them",
         lambda: convert.unreviewed_rows(alt, convert.REVIEW_COLUMNS["image_alt"]) == 2
         and convert.unreviewed_rows(tables, convert.REVIEW_COLUMNS["table_headers"]) == 2),
        ("a sidecar saved in Windows-1252 isn't UTF-8 at its line, a CR alone ending each "
         "line or not, and one with marks is",
         lambda: sidecars.rewrite_as_utf8(ansi)[0][1:2] == ["  line 2: ch1/media/rId7.png,Caf\u00e9"]
         and sidecars.rewrite_as_utf8(mac)[0][1:2] == ["  line 3: ch1/media/rId8.png,Caf\u00e9"]
         and sidecars.rewrite_as_utf8(alt) == ([], None)),
        ("and a folder is said to be one, which the run goes on without",
         lambda: sidecars.rewrite_as_utf8(os.path.dirname(alt))
         == (["WARNING: %s is a folder, not a file, so this run goes on without it, and leaves it "
              "as it is." % os.path.dirname(alt)], None)),
    ]


def check_sidecars_another_user():
    """Sidecars root owns, read by a run as another user, where root runs
    these and can be someone else (setpriv): the run's checks as they are,
    os.access and the euid unpatched, which the other checks stand in for.
    Root's file that nothing but whose it is keeps the run from rewriting
    is warned of, of ASCII alone too, the run saying it isn't given the
    mark or rewritten, not that it can't be (Rob, 2026-10-27), whether the
    user may write it or only root may, said to be root's, not read-only,
    which it isn't; in a folder with the sticky bit, as /tmp has, it's
    root's to put right, a copy of one's own unable to replace it there,
    as it can in a plain folder and in one with the sticky bit that's the
    user's, made with cp -p and moved with mv -f, as the run and the docs
    say; one in a folder only root may write can't be, said to be; a link
    says whose file it leads to, and whether a copy can take its place,
    the user's own link in root's folder with the sticky bit as well; the
    user's own file in root's folder with the sticky bit is given the
    mark; one with the mark already is read without a word; one only root
    may read is gone without, said to be root's; and a run as root in a
    user namespace, which can't give a new file root as its owner, leaves
    root's file as it was, said to be another user's, and one it may not
    write, which it sees as nobody's, said to be theirs, not marked
    immutable."""
    import json
    import sidecars
    if os.geteuid() != 0 or not shutil.which("setpriv"):
        return [("a run as another user, which only root can make here",
                 lambda: print("  skip  not root, or no setpriv") or True)]
    # In /tmp, which anyone may go into, as TMPDIR needn't be, the module
    # copied there, as the clone and its folders needn't be anyone's either.
    work = tempfile.mkdtemp(prefix="sidecar-another-user-", dir="/tmp")
    atexit.register(shutil.rmtree, work, True)
    # A shared folder, anyone's to write, as /tmp is, with its sticky bit;
    # one without it; one only root's; and the user's own with the bit.
    os.chmod(work, 0o1777)
    for name, mode in (("shared", 0o777), ("locked", 0o755), ("own", 0o1777)):
        os.mkdir(os.path.join(work, name))
        os.chmod(os.path.join(work, name), mode)
    os.chown(os.path.join(work, "own"), 65534, 65534)
    lib = os.path.join(work, "lib")
    os.mkdir(lib)
    shutil.copy(os.path.join(ROOT, "lib", "sidecars.py"), lib)
    os.chmod(lib, 0o755)
    os.chmod(os.path.join(lib, "sidecars.py"), 0o644)
    user = ["setpriv", "--reuid=65534", "--regid=65534", "--clear-groups"]
    who = user + [sys.executable]
    probe = subprocess.run(who + ["-c", "import sys; sys.path.insert(0, %r); import sidecars; "
                                  "print('ready')" % lib], capture_output=True, text=True,
                           env=dict(os.environ, HOME=work))
    if probe.stdout.strip() != "ready":
        return [("a run as another user, which this Python can't be run as here",
                 lambda: print("  skip  uid 65534 can't run %s: %s" % (
                     sys.executable, (probe.stderr.strip().splitlines() or ["?"])[-1])) or True)]
    rows = "Image,Alt\r\none.png,A red square – large\r\n"
    ascii_rows = b"Image,Alt\r\none.png,A red square\r\n"
    files = {"theirs-ansi.csv": (rows.encode("cp1252"), 0o644),
             "theirs-utf8.csv": (rows.encode("utf-8"), 0o666),
             "theirs-ascii.csv": (ascii_rows, 0o644),
             "theirs-hidden.csv": (rows.encode("utf-8"), 0o600),
             "shared/open-ascii.csv": (ascii_rows, 0o666),
             "shared/open-utf8.csv": (rows.encode("utf-8"), 0o666),
             "shared/open-ansi.csv": (rows.encode("cp1252"), 0o666),
             "shared/closed-ascii.csv": (ascii_rows, 0o644),
             "shared/closed-ansi.csv": (rows.encode("cp1252"), 0o644),
             "shared/marked.csv": (b"\xef\xbb\xbf" + rows.encode("utf-8"), 0o666),
             "locked/theirs-locked.csv": (rows.encode("cp1252"), 0o644),
             "locked/open-locked.csv": (rows.encode("utf-8"), 0o666),
             "own/theirs.csv": (ascii_rows, 0o666),
             "own-ascii.csv": (ascii_rows, 0o644),
             "shared/target.csv": (ascii_rows, 0o666),
             "target-sticky.csv": (ascii_rows, 0o666),
             "shared/namespace.csv": (ascii_rows, 0o666),
             "shared/namespace-closed.csv": (ascii_rows, 0o644),
             "shared/target-mine.csv": (ascii_rows, 0o666)}
    for name, (raw, mode) in files.items():
        with open(os.path.join(work, name), "wb") as fh:
            fh.write(raw)
        os.chmod(os.path.join(work, name), mode)
    # The user's own, in root's folder with the sticky bit.
    os.chown(os.path.join(work, "own-ascii.csv"), 65534, 65534)
    # Root's link, in its folder with the sticky bit, to its file in the
    # plain folder; the user's, in the user's own folder, to root's file in
    # root's folder with the sticky bit.
    os.symlink(os.path.join(work, "shared", "target.csv"), os.path.join(work, "link-to-shared.csv"))
    os.symlink(os.path.join(work, "target-sticky.csv"), os.path.join(work, "own", "link-to-sticky.csv"))
    os.lchown(os.path.join(work, "own", "link-to-sticky.csv"), 65534, 65534)
    # And the user's own link in root's folder with the sticky bit, which
    # the user may replace there, the link being theirs, to root's file in
    # the plain folder.
    os.symlink(os.path.join(work, "shared", "target-mine.csv"), os.path.join(work, "mine-link.csv"))
    os.lchown(os.path.join(work, "mine-link.csv"), 65534, 65534)
    run_names = sorted(n for n in files if "target" not in n and "namespace" not in n) + [
        "link-to-shared.csv", "own/link-to-sticky.csv", "mine-link.csv"]
    script = ("import json, os, sys; sys.path.insert(0, %r); import sidecars; "
              "print(json.dumps({n: [sidecars.rewrite_as_utf8(os.path.join(%r, n)), "
              "sidecars.text(os.path.join(%r, n))] for n in %r}))"
              % (lib, work, work, run_names))
    run = subprocess.run(who + ["-c", script], capture_output=True, text=True,
                         env=dict(os.environ, HOME=work))
    try:
        said = json.loads(run.stdout)
    except ValueError:
        print(run.stderr)
        said = {}
    # What the run says to do with root's file of ASCII alone the user can't
    # write, done as the user, and the run again: a copy made with cp -p
    # moved into its place with mv -f, the user's now, which the run gives
    # the mark, in the plain folder and in the user's own with the sticky
    # bit; and in root's folder with the sticky bit, which won't let the
    # copy in.
    copied = {}
    for name in ("shared/copied-ascii.csv", "own/copied-ascii.csv", "copied-ascii.csv"):
        with open(os.path.join(work, name), "wb") as fh:
            fh.write(ascii_rows)
        os.chmod(os.path.join(work, name), 0o644)
        mine = os.path.join(os.path.dirname(os.path.join(work, name)), "mine.csv")
        moved = subprocess.run(user + ["sh", "-c", 'cp -p "$1" "$2" && mv -f "$2" "$1"', "sh",
                                       os.path.join(work, name), mine],
                               capture_output=True, text=True, cwd=work, stdin=subprocess.DEVNULL)
        again = subprocess.run(who + ["-c", "import json, sys; sys.path.insert(0, %r); "
                                      "import sidecars; print(json.dumps(sidecars.rewrite_as_utf8"
                                      "(%r)))" % (lib, os.path.join(work, name))],
                               capture_output=True, text=True, env=dict(os.environ, HOME=work))
        status = os.stat(os.path.join(work, name))
        try:
            copied[name] = (moved.returncode, json.loads(again.stdout), status.st_uid,
                            status.st_mode & 0o7777)
        except ValueError:
            print(again.stderr)
            copied[name] = None
    # Root in a user namespace, as a rootless container runs, made of the
    # user (unshare -r): it seems root, and can't give a new file root,
    # whom it sees as nobody, as its owner.
    namespaced = subprocess.run(
        user + ["unshare", "-U", "-r", sys.executable, "-c",
                "import json, os, sys; sys.path.insert(0, %r); import sidecars; "
                "print(json.dumps([os.geteuid()] + [sidecars.rewrite_as_utf8(p) for p in %r]))"
                % (lib, [os.path.join(work, "shared", n)
                         for n in ("namespace.csv", "namespace-closed.csv")])],
        capture_output=True, text=True, env=dict(os.environ, HOME=work)) \
        if shutil.which("unshare") else None
    try:
        euid_inside, namespace_said, closed_said = json.loads(namespaced.stdout)
    except (AttributeError, ValueError):
        euid_inside, namespace_said, closed_said = None, None, None

    def path(name):
        return os.path.join(work, name)

    def data(name):
        with open(path(name), "rb") as fh:
            return fh.read()

    def left(name):
        return data(name) == files[name][0] and os.stat(path(name)).st_uid == 0

    def one(name, line):
        """The run said line alone of name, which it read as written and
        left as it was."""
        text = files[name][0].decode("cp1252" if "ansi" in name else "utf-8")
        return said[name][0] == [[line], None] and said[name][1] == text and left(name)

    def warned(name, start, end):
        """The run warned of name, its first line starting so and its last
        ending so, and read it as written, leaving it as it was."""
        lines = said[name][0][0]
        return (said[name][0][1] is None and lines[0].startswith(start)
                and lines[-1].endswith(end) and said[name][1] == rows and left(name))

    def ascii_warned(name, reason, remedy, kind="WARNING", given="isn't given one"):
        return one(name, "%s: %s has no byte-order mark, and %s: %s. It holds nothing outside "
                   "ASCII, which reads the same either way. To have the mark added, %s."
                   % (kind, path(name), given, reason, remedy))

    def skipped(why):
        print("  skip  " + why)
        return True
    unmarked = "%s has no byte-order mark, which Excel needs to open it as UTF-8, and "
    coded = ("%s isn't UTF-8: 1 line(s) of it are read as Windows-1252, as Windows Excel's plain "
             "\"CSV\" saves a file in the US and Western Europe, but it ")
    return [
        ("root's file in Windows-1252 is read in it by another user and left to root, said "
         "to be root's, not read-only, which it isn't, in a folder with the sticky bit, where "
         "only a file's owner may replace it, so that it's root's to put right",
         lambda: run.returncode == 0
         and warned("theirs-ansi.csv", "WARNING: " + coded % path("theirs-ansi.csv")
                    + "isn't rewritten as UTF-8: %s. This run reads it so" % (STICKY % "root"),
                    "To have the run rewrite it, %s." % (ASK % "root"))),
        ("one in UTF-8 without the mark that anyone may write there is read as it is and left "
         "to root, the same said of it",
         lambda: warned("theirs-utf8.csv", "WARNING: " + unmarked % path("theirs-utf8.csv")
                        + "isn't given one: %s. It's read as UTF-8" % (STICKY % "root"),
                        "To have the mark added, %s." % (ASK % "root"))),
        ("and one of ASCII alone is warned of, whose it is all that keeps it so",
         lambda: ascii_warned("theirs-ascii.csv", STICKY % "root", ASK % "root")),
        ("in a shared folder without the bit, one of ASCII alone the user may write is warned "
         "of, the run leaving it to root, though nothing in it reads otherwise",
         lambda: ascii_warned("shared/open-ascii.csv", CHOSEN % "root", THEIRS % "root")),
        ("and one in UTF-8, and one in Windows-1252, said not to be given the mark or "
         "rewritten, not that they can't be, and why",
         lambda: warned("shared/open-utf8.csv", "WARNING: " + unmarked % path("shared/open-utf8.csv")
                        + "isn't given one: %s. It's read as UTF-8" % (CHOSEN % "root"),
                        "To have the mark added, %s." % (THEIRS % "root"))
         and warned("shared/open-ansi.csv", "WARNING: " + coded % path("shared/open-ansi.csv")
                    + "isn't rewritten as UTF-8: %s. This run reads it so" % (CHOSEN % "root"),
                    "To have the run rewrite it, %s." % (THEIRS % "root"))),
        ("and one only root may write, as the usual 0644 is, warned of too, of ASCII alone as "
         "in Windows-1252, its being root's all that keeps it so",
         lambda: ascii_warned("shared/closed-ascii.csv", OWNED % "root", THEIRS % "root")
         and warned("shared/closed-ansi.csv", "WARNING: " + coded % path("shared/closed-ansi.csv")
                    + "isn't rewritten as UTF-8: %s. This run reads it so" % (OWNED % "root"),
                    "To have the run rewrite it, %s." % (THEIRS % "root"))),
        ("and root's with the mark already is read as it is without a word",
         lambda: said["shared/marked.csv"] == [[[], None], rows] and left("shared/marked.csv")),
        ("one in a folder only root may write can't be rewritten or given the mark, which a "
         "copy of one's own needs the folder for, root's to put right",
         lambda: warned("locked/theirs-locked.csv",
                        "WARNING: " + coded % path("locked/theirs-locked.csv")
                        + "can't be rewritten as UTF-8: %s; its folder can't be written. This run "
                        "reads it so" % (OWNED % "root"),
                        "To have the run rewrite it, %s." % (ASK % "root"))
         and warned("locked/open-locked.csv",
                    "WARNING: " + unmarked % path("locked/open-locked.csv")
                    + "can't be given one: %s; its folder can't be written. It's read as UTF-8"
                    % (OWNED % "root"), "To have the mark added, %s." % (ASK % "root"))),
        ("in the user's own folder with the sticky bit, root's file can be replaced with a copy "
         "of one's own, as the run says",
         lambda: ascii_warned("own/theirs.csv", CHOSEN % "root", THEIRS % "root")),
        ("and the user's own file in root's folder with the sticky bit is given the mark",
         lambda: said["own-ascii.csv"][0] == [["%s had no byte-order mark: one is added, as "
                                               "Excel's \"CSV UTF-8\" writes one, and nothing "
                                               "else in it changes." % path("own-ascii.csv")], None]
         and data("own-ascii.csv") == b"\xef\xbb\xbf" + ascii_rows),
        ("a link says whose file it leads to: root's, in root's folder with the sticky bit, can't "
         "be replaced there, and the user's, in the user's own folder, can",
         lambda: said["link-to-shared.csv"][0] == [[
             "WARNING: %s has no byte-order mark, and isn't given one: it's a link to %s, which "
             "belongs to another user, root, and though the user running this may write it, a "
             "rewrite would take it from them. It holds nothing outside ASCII, which reads the "
             "same either way. To have the mark added, %s."
             % (path("link-to-shared.csv"), path("shared/target.csv"), ASK % "root")], None]
         and said["own/link-to-sticky.csv"][0] == [[
             "WARNING: %s has no byte-order mark, and isn't given one: it's a link to %s, which "
             "belongs to another user, root, in a folder where only a file's owner, or the "
             "folder's owner, may replace it. It holds nothing outside ASCII, which reads the "
             "same either way. To have the mark added, %s."
             % (path("own/link-to-sticky.csv"), path("target-sticky.csv"), THEIRS % "root")],
             None]
         and data("shared/target.csv") == ascii_rows and data("target-sticky.csv") == ascii_rows),
        ("and the user's own link in root's folder with the sticky bit, which the user may "
         "replace there, can be replaced with a copy of one's own",
         lambda: said["mine-link.csv"][0] == [[
             "WARNING: %s has no byte-order mark, and isn't given one: it's a link to %s, which "
             "belongs to another user, root, and though the user running this may write it, a "
             "rewrite would take it from them. It holds nothing outside ASCII, which reads the "
             "same either way. To have the mark added, %s."
             % (path("mine-link.csv"), path("shared/target-mine.csv"), THEIRS % "root")], None]
         and data("shared/target-mine.csv") == ascii_rows),
        ("a copy made with cp -p moved into root's file's place with mv -f, as the run says, is "
         "the user's, its mode kept, which the run gives the mark; in a plain folder, and in the "
         "user's own with the sticky bit",
         lambda: all(copied[name] == (
             0, [["%s had no byte-order mark: one is added, as Excel's \"CSV UTF-8\" writes one, "
                  "and nothing else in it changes." % path(name)], None], 65534, 0o644)
             and data(name) == b"\xef\xbb\xbf" + ascii_rows
             for name in ("shared/copied-ascii.csv", "own/copied-ascii.csv"))),
        ("but not in root's folder with the sticky bit, which keeps root's file root's",
         lambda: copied["copied-ascii.csv"] is not None and copied["copied-ascii.csv"][0] != 0
         and copied["copied-ascii.csv"][2:] == (0, 0o644)
         and data("copied-ascii.csv") == ascii_rows),
        ("one only root may read is gone without, said to be root's",
         lambda: said["theirs-hidden.csv"] == [[[
             "WARNING: %s can't be read (Permission denied); it belongs to root, so this run goes "
             "on without it, and leaves it as it is. To use it, give the user running this "
             "permission to read it." % path("theirs-hidden.csv")], None], ""]
         and data("theirs-hidden.csv") == files["theirs-hidden.csv"][0]),
        ("a run as root in a user namespace, which sees root as nobody and can't give a new file "
         "root as its owner, leaves root's file as it was, said to be another user's, and one it "
         "may not write, said to be theirs, not marked immutable",
         lambda: skipped("no user namespaces here: %s" % (
             (namespaced.stderr.strip().splitlines() or ["?"])[-1] if namespaced else "no unshare"))
         if euid_inside != 0 else
         namespace_said == [[
             "WARNING: %s has no byte-order mark, and isn't given one: %s. It holds nothing "
             "outside ASCII, which reads the same either way. To have the mark added, %s."
             % (path("shared/namespace.csv"), CHOSEN % "nobody", THEIRS % "nobody")], None]
         and data("shared/namespace.csv") == ascii_rows
         and os.stat(path("shared/namespace.csv")).st_uid == 0
         and closed_said == [[
             "WARNING: %s has no byte-order mark, and isn't given one: %s. It holds nothing "
             "outside ASCII, which reads the same either way. To have the mark added, %s."
             % (path("shared/namespace-closed.csv"), OWNED % "nobody", THEIRS % "nobody")], None]
         and data("shared/namespace-closed.csv") == ascii_rows
         and sorted(os.listdir(path("shared"))) == sorted(
             n for n in os.listdir(path("shared")) if not n.startswith("."))),
    ]


def check_sidecars_left_as_they_are():
    """Every reader reads a sidecar the run can't rewrite as UTF-8 as the
    run reads it (sidecars.opened), not with open: Rob, 2026-10-26, "upgrade
    all sidecars to UTF-8 and read UTF-8 for all of them", and "assume that
    users will be sloppy about permissions but files in the directory are
    there for a reason". Each kind, as Excel's plain "CSV" saves it, in
    Windows-1252, and read-only, so that a run as root leaves it as it is
    too, is read as written, a character outside ASCII in its row; and one
    that can't be read is read as none, by every reader, none stopping.
    Read with open, such a file had been read as UTF-8, which it isn't.
    """
    import docxremediate
    import htmlremediate
    import languages
    import pptxremediate
    import sidecars
    convert = load(os.path.join(ROOT, "bin", "convert.py"), "convert_kept")
    headers = load(os.path.join(ROOT, "bin", "table-headers.py"), "table_headers_kept")
    split = load(os.path.join(ROOT, "bin", "split-pages.py"), "split_pages_kept")
    work = scratch("sidecar-kept-")
    cafe = "Caf\u00e9 \u2013 one"

    def sidecar(name, header, row):
        path = os.path.join(work, name)
        with open(path, "w", encoding="cp1252", newline="") as fh:
            fh.write(header + "\r\n" + row + "\r\n")
        os.chmod(path, 0o444)
        return path

    def data(path):
        with open(path, "rb") as fh:
            return fh.read()

    alt = sidecar("image-alt.csv", "Image,Alt,Source,Reason,CurrentAlt,Drafted by,Reviewed",
                  "ch1/media/rId7.png,%s,ch1,missing,,claude," % cafe)
    links = sidecar("bare-links.csv", "URL,Replacement,Title,Source,Context,Drafted by,Reviewed",
                    "https://example.org/a,,%s,ch1,,," % cafe)
    tables = sidecar("table-headers.csv", ",".join(headers.SIDECAR_COLUMNS),
                     "aaa,first-row,,,,caf\u00e9.docx,,,TI,")
    names = sidecar("page-names.csv", "source,parents,heading,position,name",
                    "ch1.docx,,%s,,intro" % cafe)
    language = sidecar("languages.csv", ",".join(languages.SIDECAR_COLUMNS),
                       "caf\u00e9,fr,,,")
    titles = sidecar("slide-titles.csv", "Slide,Title,Source,Drafted by,Reviewed",
                     "deck/slide-256,%s,,," % cafe)
    orders = sidecar("reading-order.csv", "Slide,Order,Source,Shapes,Note,Drafted by,Reviewed",
                     "deck/slide-256,2 3,,,%s,," % cafe)
    keep = sidecar("math-keep.csv", "Kind,Page,Before,After", "equation,ch1,5 \u00b5m \u2013 x,")
    every = [alt, links, tables, names, language, titles, orders, keep]
    before = {path: data(path) for path in every}
    said = {path: sidecars.rewrite_as_utf8(path) for path in every}

    def read_all():
        warned, unknown, bad = [], set(), []
        return {
            "alt": (docxremediate.alt_rows(alt), htmlremediate.alt_rows(alt),
                    pptxremediate.alt_rows(alt), convert.unreviewed_rows(
                        alt, convert.REVIEW_COLUMNS["image_alt"])),
            "links": (htmlremediate.link_rows(links), docxremediate.link_titles(links),
                      pptxremediate.link_rows(links)),
            "tables": (headers.read_sidecar(tables, warned.append),
                       pptxremediate.header_rows(tables, unknown)),
            "names": split.read_sidecar(names),
            "languages": languages.read_rows(language),
            "titles": pptxremediate.title_rows(titles),
            "orders": pptxremediate.order_rows(orders, bad),
            "keep": sidecars.math_keep_rows(keep),
        }
    read = read_all()

    def refusing(file, mode="r", *args, **kwargs):
        if file in every:
            raise PermissionError(13, "Permission denied", file)
        return open(file, mode, *args, **kwargs)
    found = os.path.join(work, "bare-links-found")
    with open(found, "w", encoding="utf-8", newline="") as fh:
        fh.write("decided,https://example.org/a,,ch1,See\n")
    stale = []
    convert.say = stale.append
    convert.write_bare_links(found, os.path.join(work, "bare-links-new.csv"), links)
    sidecars.open = refusing
    try:
        unread = read_all()
        has_columns = headers.has_review_columns(tables)
    finally:
        del sidecars.open
    # The sidecars the filters read themselves, which convert.py gives them
    # a copy of where one's left in a code page: each setting the filters
    # read by its key upper-cased.
    lua = ""
    for name in sorted(os.listdir(os.path.join(ROOT, "bin"))):
        if name.endswith(".lua"):
            with open(os.path.join(ROOT, "bin", name), encoding="utf-8") as fh:
                lua += fh.read()
    read_by_filters = set(re.findall(r"os\.getenv\('([A-Z_]+)'\)", lua))
    keys = ("table_captions", "image_alt", "table_headers", "page_names", "bare_links",
            "math_keep", "slide_titles", "reading_order", "languages")
    return [
        ("each kind, read-only in Windows-1252, is left as it is, the run saying it's read in "
         "its code page all the same",
         lambda: all(said[path][1] is None and said[path][0][0].startswith(
             "WARNING: %s isn't UTF-8: 1 line(s) of it are read as Windows-1252" % path)
             and "it can't be rewritten as UTF-8: it's read-only" in said[path][0][0]
             and data(path) == before[path] for path in every)),
        ("image-alt.csv is read so by the Word, page, and deck copies, and its drafted row counted",
         lambda: read["alt"] == ({"ch1": {"rId7": cafe}}, {"ch1/media/rId7": cafe},
                                 pptxremediate.alt_rows(alt), 1)
         and list(read["alt"][2].values()) == [cafe]),
        ("and bare-links.csv",
         lambda: read["links"][:2] == ({"https://example.org/a": ("", cafe)},
                                       {"https://example.org/a": cafe})
         and set(read["links"][2]) == {"https://example.org/a"}),
        ("table-headers.csv, by table-headers.py and the decks",
         lambda: set(read["tables"][0]) == {"aaa"} and read["tables"][1] == {"aaa": "first-row"}),
        ("page-names.csv, by split-pages.py",
         lambda: read["names"] == {("ch1.docx", "", cafe, ""): "intro"}),
        ("languages.csv", lambda: read["languages"] == ({"caf\u00e9": "fr"}, [])),
        ("slide-titles.csv and reading-order.csv",
         lambda: read["titles"] == {"deck/slide-256": cafe}
         and read["orders"] == {"deck/slide-256": ["2", "3"]}),
        ("and math-keep.csv",
         lambda: read["keep"] == [("equation", "ch1", "5 \u00b5m \u2013 x")]),
        ("and the run's bare links match bare-links.csv's row, none of its rows matching none",
         lambda: stale == []),
        ("the filters are given a copy of each sidecar they read themselves",
         lambda: {k for k in keys if k.upper() in read_by_filters} == set(convert.FILTER_SIDECARS)),
        ("one that can't be read is read as none by every reader, none stopping",
         lambda: unread == {"alt": ({}, {}, {}, 0), "links": ({}, {}, {}), "tables": ({}, {}),
                            "names": {}, "languages": ({}, []), "titles": {}, "orders": {},
                            "keep": []} and has_columns),
    ]


# What the run says to do with another user's sidecar it reads and leaves
# as it is, its owner's name for %s: where its name's place can't be taken
# by a copy of one's own, a folder with the sticky bit that isn't this
# user's say, ask its owner (ASK); elsewhere, a copy of one's own too
# (THEIRS). And why it leaves one that nothing but whose it is keeps it
# from rewriting: theirs (OWNED); one this user may write too (CHOSEN);
# and one in a folder with the sticky bit (STICKY).
ASK = "ask its owner, %s, to save it as UTF-8 with the mark"
THEIRS = "replace it with a copy of your own made with cp -p, which keeps its mode, or " + ASK
OWNED = "it belongs to another user, %s"
CHOSEN = OWNED + (", and though the user running this may write it, a rewrite would take it "
                  "from them")
STICKY = OWNED + ", in a folder where only a file's owner, or the folder's owner, may replace it"


def check_sidecar_code_pages():
    """A sidecar Excel saved as plain "CSV", in a code page, not UTF-8, is
    rewritten as UTF-8 (sidecars.rewrite_as_utf8): its lines that aren't
    UTF-8 read in the code page Excel saves in, Windows-1252 or Mac OS
    Roman, the one with fewer characters misplaced, or, where they have as
    many, the one its lines' ends tell, a CR alone Mac OS Roman's; each
    line that is UTF-8, as rows appended from a report are, kept as it is,
    and shown; the file as it was kept beside it. Lines all misplaced in
    both stop it, as saved in another code page. A sidecar so saved had
    stopped the run, its characters having been U+FFFD on the pages and a
    traceback before that. And every sidecar is made UTF-8 with the mark
    (Rob, 2026-10-26: "upgrade all sidecars to UTF-8 and read UTF-8 for all
    of them"): one without the mark given it, of ASCII alone too; one the
    run can't rewrite, read-only, another user's, linked, held open, or in
    a folder that can't be written, read as it is, in its code page or as
    UTF-8, and left so, the run saying why; and one that's there and can't
    be read gone without, said to be, never opened if it's a pipe.
    """
    import signal
    import sidecars
    work = scratch("sidecar-code-pages-")
    # A person's uid and gid: 1000 where root runs these, the user's own
    # where a user does.
    person = (1000, 1000) if os.geteuid() == 0 else (os.getuid(), os.getgid())

    def write(name, data):
        path = os.path.join(work, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def data(path):
        with open(path, "rb") as fh:
            return fh.read()

    def rewritten(name, raw):
        path = write(name, raw)
        said, why = sidecars.rewrite_as_utf8(path)
        return path, said, why

    def beside(name):
        return sorted(n for n in os.listdir(work) if n.startswith(name) and n != name
                      or n.startswith("." + name))

    header = "Image,Alt\r\n"
    ansi_rows = header + "one.png,A red square \u2013 large\r\n"
    report_rows = "\ufefftwo.png,A blue caf\u00e9\r\n"
    ansi, ansi_said, ansi_why = rewritten(
        "ansi.csv", ansi_rows.encode("cp1252") + report_rows.encode("utf-8"))
    again = write("again.csv", ansi_rows.encode("cp1252"))
    write("again.csv.windows-1252", b"taken")
    again_said, _ = sidecars.rewrite_as_utf8(again)
    # As Excel for Mac saves it now, its lines ending with CR LF.
    mac_rows = header + "one.png,Don\u2019t \u2013 \u201cquoted\u201d\r\n"
    mac, mac_said, _ = rewritten("mac.csv", mac_rows.encode("mac_roman"))
    french_rows = header + "one.png,Tr\u00e8s bien\r\n"
    french, french_said, _ = rewritten("french.csv", french_rows.encode("mac_roman"))
    french_cr_rows = "Image,Alt\rone.png,Tr\u00e8s bien, gar\u00e7on\r"
    french_cr, french_cr_said, _ = rewritten("french-cr.csv", french_cr_rows.encode("mac_roman"))
    # Neither code page tells: a CR alone ending the lines, as Excel 2011
    # for Mac saved them, tells Mac OS Roman; else it's Windows-1252.
    tie = b"Image,Alt%sone.png,The company\x92s%s"
    tie_cr, _, _ = rewritten("tie-cr.csv", tie % (b"\r", b"\r"))
    tie_crlf, _, _ = rewritten("tie-crlf.csv", tie % (b"\r\n", b"\r\n"))
    tie_report, _, _ = rewritten("tie-report.csv", tie % (b"\r", b"\r")
                                 + "\ufefftwo.png,Caf\u00e9\r\n".encode("utf-8"))
    # As "CSV (MS-DOS)" saves M\u00fcller: a byte Windows-1252 has no
    # character for, and a capital Mac OS Roman reads inside a word.
    undefined, undefined_said, undefined_why = rewritten(
        "undefined.csv", b"Image,Alt\r\none.png,M\x81ller's square\r\n")
    # A sign each code page reads alike tells neither, and stops neither.
    alike, _, alike_why = rewritten("alike.csv", b"Image,Alt\r\none.png,M\xb1SD \x96 by group\r\n")
    # Greek, in Windows-1253, as Excel in Greece saves it, two lines of it.
    greek_rows = ("Image,Alt\r\none.png,\u0393\u03b5\u03b9\u03ac \u03c3\u03bf\u03c5\r\n"
                  "two.png,\u03ba\u03b1\u03bb\u03ac\r\n")
    greek, _, greek_why = rewritten("greek.csv", greek_rows.encode("cp1253"))
    # A file whose one line is misplaced in both is read in the one with
    # fewer: \u00d1 alone in Windows-1252, a letter's name, against two in
    # Mac OS Roman.
    one_odd_rows = header + "one.png,la letra \u00d1, na\u00efve caf\u00e9\r\n"
    one_odd, _, one_odd_why = rewritten("one-odd.csv", one_odd_rows.encode("cp1252"))
    # Saved in Mac OS Roman with CR LF, it reads with fewer there, and the
    # line ends, which prefer Windows-1252, don't decide.
    mac_odd, _, mac_odd_why = rewritten("mac-odd.csv", one_odd_rows.encode("mac_roman"))
    # And one of two lines, the other misplaced in neither: no stop either.
    two_odd_rows = one_odd_rows + "two.png,don\u2019t\r\n"
    two_odd, _, two_odd_why = rewritten("two-odd.csv", two_odd_rows.encode("cp1252"))
    # A line misplaced as Windows-1252 among lines that aren't, as a line
    # of a sentence's own is: the file's other lines tell.
    four_rows = (header + "a.png,firm\u2019s output, 1990\u20132000\r\n"
                 "b.png,yen (\u00a5) per US dollar\r\nc.png,GDP per capita \u2013 a comparison\r\n"
                 "d.png,see World Bank.\u00b9\r\n")
    four, _, four_why = rewritten("four.csv", four_rows.encode("cp1252"))
    # Czech, in Windows-1250, as Excel in Central Europe saves it:
    # \u017elu\u0165ou\u010dk\u00fd.
    other, other_said, other_why = rewritten("other.csv",
                                             b"Image,Alt\r\none.png,\x9elu\x9dou\xe8k\xfd\r\n")
    control, control_said, control_why = rewritten(
        "control.csv", b"Image,Alt\r\none.png,A \xe9\x01 square\r\n")
    utf16, utf16_said, utf16_why = rewritten(
        "utf16.csv", "Image\tAlt\r\none.png\tCaf\u00e9\r\n".encode("utf-16"))
    # One in UTF-8 without the mark, as a text editor saves one, given it,
    # its mode kept, and nothing else changed: its lines ending as Notepad,
    # Unix, and an old Mac end them, a mark partway, as rows appended from
    # a report have, and no end to its last line. One with the mark is
    # left as it is.
    plain_bytes = ("Image,Alt\r\none.png,Caf\u00e9\rtwo.png,A red square\n"
                   "\ufeffthree.png,G\u00f6del\u00a0and Escher").encode("utf-8")
    plain = write("plain.csv", plain_bytes)
    os.chmod(plain, 0o640)
    plain_said = sidecars.rewrite_as_utf8(plain)
    marked = write("marked.csv", "\ufeffImage,Alt\r\none.png,Caf\u00e9\r\n".encode("utf-8"))
    marked_said = sidecars.rewrite_as_utf8(marked)
    empty = write("empty.csv", b"")
    empty_said = sidecars.rewrite_as_utf8(empty)
    ascii_bytes = b"Image,Alt\none.png,A red square\n"
    ascii = write("ascii.csv", ascii_bytes)
    ascii_said = sidecars.rewrite_as_utf8(ascii)
    long_rows = header + "".join("p%d.png,Caf\u00e9 %d\r\n" % (n, n) for n in range(12))
    many, many_said, _ = rewritten("many.csv", long_rows.encode("cp1252"))
    # A mark at the start of a line that isn't UTF-8 is UTF-8's.
    mark_first, mark_said, _ = rewritten("mark-first.csv", b"\xef\xbb\xbfone.png,Caf\xe9\r\n")
    # Windows-1252 that happens to be UTF-8 at a line, Gau\u00df\u2019s being
    # UTF-8's Gau\u07d2s, beside a line that isn't: kept as UTF-8, as a
    # report's row is, and shown with them.
    chance_rows = header + "one.png,Gau\u00df\u2019s law\r\ntwo.png,Caf\u00e9 \u2013 red\r\n"
    chance, chance_said, _ = rewritten("chance.csv", chance_rows.encode("cp1252"))
    # And a report's row in UTF-8 with a character text seldom has there,
    # and with ones that show as nothing.
    kept_rows = "two.png,na\u2022ve\u00a0inter\u00adnal\r\n"
    kept_utf8, kept_said, _ = rewritten("kept-utf8.csv",
                                        ansi_rows.encode("cp1252") + kept_rows.encode("utf-8"))
    # A file that can't be written: one another program holds open, as Excel
    # holds one on Windows, a disk full partway, and one in a folder that
    # can't be written, which only root, who runs these here, can write.
    cases = {}
    saved = (os.replace, os.fdopen, os.access)

    class Full:
        def __init__(self, handle, *args, **kwargs):
            os.close(handle)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def write(self, text):
            raise OSError(28, "No space left on device")

    def held(source, target):
        # As Windows refuses to replace a file another program has open, a
        # sharing violation, which Python makes a PermissionError.
        exc = PermissionError(13, "The process cannot access the file", target)
        exc.winerror = 32
        raise exc

    folder = os.path.realpath(work)
    for name, patch in (("held.csv", {"replace": held}), ("full.csv", {"fdopen": Full}),
                        ("folder.csv", {"access": lambda path, mode: (
                            os.path.realpath(path) != folder and saved[2](path, mode))})):
        for attribute, value in patch.items():
            setattr(os, attribute, value)
        try:
            cases[name] = rewritten(name, ansi_rows.encode("cp1252"))
        finally:
            os.replace, os.fdopen, os.access = saved

    class FullCopy:
        def __init__(self, fh):
            self.fh = fh

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.fh.close()
            return False

        def write(self, data):
            self.fh.write(data[:5])
            raise OSError(28, "No space left on device")

    def copying(file, mode="r", *args, **kwargs):
        fh = open(file, mode, *args, **kwargs)
        return FullCopy(fh) if mode == "xb" else fh
    sidecars.open = copying
    try:
        cases["full-copy.csv"] = rewritten("full-copy.csv", ansi_rows.encode("cp1252"))
    finally:
        del sidecars.open
    # The file as it was kept under the next name when a dangling link has
    # the first; a link's file rewritten, the link kept; and its mode kept.
    dangling = write("dangling.csv", ansi_rows.encode("cp1252"))
    os.symlink(os.path.join(work, "nowhere"), dangling + ".windows-1252")
    dangling_said, dangling_why = sidecars.rewrite_as_utf8(dangling)
    target = write("target.csv", ansi_rows.encode("cp1252"))
    link = os.path.join(work, "link.csv")
    os.symlink(target, link)
    link_said, link_why = sidecars.rewrite_as_utf8(link)
    moded = write("moded.csv", ansi_rows.encode("cp1252"))
    os.chmod(moded, 0o640)
    sidecars.rewrite_as_utf8(moded)
    # A person's file, rewritten by root, stays theirs, the copy kept too.
    owned = write("owned.csv", ansi_rows.encode("cp1252"))
    os.chown(owned, *person)
    sidecars.rewrite_as_utf8(owned)
    # On a disk that keeps no mode (FAT), the rewrite goes on without one.
    def unmoded(path, mode):
        raise PermissionError(1, "Operation not permitted", path)
    fat = write("fat.csv", ansi_rows.encode("cp1252"))
    os.chmod, saved_chmod = unmoded, os.chmod
    try:
        fat_said, fat_why = sidecars.rewrite_as_utf8(fat)
    finally:
        os.chmod = saved_chmod
    # One without the mark that can't be given it, read as it is: one held
    # open, as Excel holds one on Windows; one read-only, which root, who
    # runs these here, could write; another user's, whose owner a run that
    # isn't root can't keep, a run by someone else made with the euid, which
    # this user may write, so that the run leaves it by choice; and one with
    # another link to it. And one of ASCII alone that can't be.
    unmarked = {}
    for name, patch in (("held-utf8.csv", {"replace": held}),
                        ("theirs-utf8.csv", {"geteuid": None})):
        theirs = write(name, plain_bytes)
        owner = os.stat(theirs).st_uid
        saved_euid = os.geteuid
        for attribute, value in patch.items():
            setattr(os, attribute, value or (lambda: owner + 1))
        try:
            unmarked[name] = sidecars.rewrite_as_utf8(theirs)
        finally:
            os.replace, os.fdopen, os.access = saved
            os.geteuid = saved_euid
    theirs_name = sidecars.owner_of(os.stat(os.path.join(work, "theirs-utf8.csv")))
    # Another user's that nothing but whose it is keeps the run from
    # rewriting, warned of whatever it holds (Rob, 2026-10-27): of ASCII
    # alone, which this user may write, and one that only its owner may
    # write, as the usual 0644 is; and in a folder with the sticky bit that
    # isn't this user's, where only a file's owner, or the folder's, may
    # replace it, so that a copy of one's own can't either. And those it
    # couldn't rewrite were they this user's, noted when of ASCII alone,
    # as one's own is: one read-only, one with another link to it, and one
    # in a folder this user can't write, which a copy of one's own needs.
    # A link says whose file it leads to; a link in a plain folder can be
    # replaced with a copy, one of another user's in a folder with the
    # sticky bit can't.
    for folder, mode in (("unwritable", 0o755), ("sticky", 0o1777)):
        os.mkdir(os.path.join(work, folder))
        os.chmod(os.path.join(work, folder), mode)
    unmarked_ascii = {}
    saved_euid, saved_access = os.geteuid, os.access
    for name, raw, mode, refused in (
            ("theirs-ascii.csv", ascii_bytes, 0o644, None),
            ("theirs-closed-ascii.csv", ascii_bytes, 0o644, "theirs-closed-ascii.csv"),
            ("theirs-readonly-utf8.csv", plain_bytes, 0o444, None),
            ("theirs-linked-utf8.csv", plain_bytes, 0o666, None),
            ("unwritable/theirs-utf8.csv", plain_bytes, 0o666, "unwritable"),
            ("sticky/theirs-utf8.csv", plain_bytes, 0o666, None),
            ("sticky/linked-to.csv", plain_bytes, 0o666, None),
            ("plain-to.csv", plain_bytes, 0o666, None)):
        subject = write(name, raw)
        os.chmod(subject, mode)
        if name == "theirs-linked-utf8.csv":
            os.link(subject, os.path.join(work, "hard-link-theirs"))
        if name == "sticky/linked-to.csv":
            os.symlink(subject, os.path.join(work, "link-to-sticky.csv"))
            subject = os.path.join(work, "link-to-sticky.csv")
        if name == "plain-to.csv":
            os.symlink(subject, os.path.join(work, "sticky", "link-to-plain.csv"))
            subject = os.path.join(work, "sticky", "link-to-plain.csv")
        uid = os.stat(subject).st_uid
        os.geteuid = lambda uid=uid: uid + 1
        if refused:
            os.access = lambda p, m, refused=os.path.join(work, refused): (
                os.path.realpath(p) != os.path.realpath(refused) and saved_access(p, m))
        try:
            (unmarked if raw == plain_bytes else unmarked_ascii)[
                os.path.relpath(subject, work)] = sidecars.rewrite_as_utf8(subject)
        finally:
            os.geteuid, os.access = saved_euid, saved_access
    # A run that seems able to give a rewritten file its owner and can't,
    # as root in a user namespace (a rootless container) can't give one a
    # user outside it has: the file is left as it was, and said to be
    # theirs, the new file gone.
    lost = write("lost-utf8.csv", plain_bytes)
    saved_stat, saved_chown = os.stat, os.chown

    class Theirs:
        """A file's status as another user's (uid one more)."""
        def __init__(self, status):
            self.status, self.st_uid = status, status.st_uid + 1

        def __getattr__(self, name):
            return getattr(self.status, name)

    def refused_chown(p, uid, gid, *args, **kwargs):
        raise PermissionError(1, "Operation not permitted", p)
    os.stat = lambda p, *args, **kwargs: (
        Theirs(saved_stat(p, *args, **kwargs))
        if isinstance(p, str) and os.path.realpath(p) == os.path.realpath(lost)
        else saved_stat(p, *args, **kwargs))
    os.chown, os.geteuid = refused_chown, lambda: 0
    try:
        unmarked["lost-utf8.csv"] = sidecars.rewrite_as_utf8(lost)
        lost_name = sidecars.owner_of(os.stat(lost))
    finally:
        os.stat, os.chown, os.geteuid = saved_stat, saved_chown, saved_euid
    # A file of a user outside the user namespace root runs in, which root
    # sees as the kernel's overflow uid and may not write: another user's,
    # as the run in a namespace (check_sidecars_another_user) finds it, not
    # one marked immutable.
    outside = write("outside-utf8.csv", plain_bytes)
    os.chmod(outside, 0o644)

    class Outside:
        """A file's status as a user outside the namespace has it."""
        def __init__(self, status):
            self.status, self.st_uid = status, sidecars._overflow_uid()

        def __getattr__(self, name):
            return getattr(self.status, name)
    os.stat = lambda p, *args, **kwargs: (
        Outside(saved_stat(p, *args, **kwargs))
        if isinstance(p, str) and os.path.realpath(p) == os.path.realpath(outside)
        else saved_stat(p, *args, **kwargs))
    os.geteuid = lambda: 0
    os.access = lambda p, mode: (os.path.realpath(p) != os.path.realpath(outside)
                                 and saved_access(p, mode))
    try:
        unmarked["outside-utf8.csv"] = sidecars.rewrite_as_utf8(outside)
        outside_name = sidecars.owner_of(os.stat(outside))
    finally:
        os.stat, os.geteuid, os.access = saved_stat, saved_euid, saved_access
    # Another user's that this user can't write either, as root's 0644 file
    # is to anyone else: its owner's alone said, not that it's read-only,
    # which it isn't. One's own that this user may not write, though it has
    # a write bit. And one whose replacing is refused (EACCES), not by a
    # program holding it open.
    saved_euid, saved_access = os.geteuid, os.access
    # One's own a user may not write is made a person's, uid 1000, where
    # root runs these, the run made theirs; and one that root can't write,
    # as one marked immutable is, though it has a write bit.
    for name, euid in (("theirs-closed.csv", "another"), ("closed-utf8.csv", "owner"),
                       ("immutable-utf8.csv", "root")):
        subject = write(name, plain_bytes)
        os.chmod(subject, 0o644)
        if euid == "owner" and os.geteuid() == 0:
            os.chown(subject, *person)
        uid = os.stat(subject).st_uid
        os.geteuid = {"another": lambda: uid + 1, "owner": lambda: uid, "root": lambda: 0}[euid]
        os.access = lambda p, mode, subject=subject: (os.path.realpath(p) != os.path.realpath(subject)
                                                      and saved_access(p, mode))
        try:
            unmarked[name] = sidecars.rewrite_as_utf8(subject)
        finally:
            os.geteuid, os.access = saved_euid, saved_access
    # One on a disk mounted read-only, which nothing on it gets past.
    mounted = write("mounted-utf8.csv", plain_bytes)

    class ReadOnly:
        f_flag = getattr(os, "ST_RDONLY", 1)
    saved_statvfs = getattr(os, "statvfs", None)
    os.statvfs = lambda p: ReadOnly() if os.path.realpath(p) == os.path.realpath(mounted) \
        else saved_statvfs(p)
    try:
        unmarked["mounted-utf8.csv"] = sidecars.rewrite_as_utf8(mounted)
    finally:
        if saved_statvfs is None:
            del os.statvfs
        else:
            os.statvfs = saved_statvfs

    def denied(source, target):
        raise PermissionError(13, "Permission denied", target)

    def denied_on_windows(source, target):
        # As Windows answers replacing a file another program has open.
        exc = PermissionError(13, "Access is denied", target)
        exc.winerror = 5
        raise exc
    for name, refusal in (("denied-utf8.csv", denied), ("windows-utf8.csv", denied_on_windows)):
        os.replace = refusal
        try:
            unmarked[name] = sidecars.rewrite_as_utf8(write(name, plain_bytes))
        finally:
            os.replace, os.fdopen, os.access = saved
    # Its extended attributes kept, an access control list among them,
    # where the disk keeps them (Linux): a person given a shared file
    # keeps it.
    noted = write("noted.csv", ascii_bytes)
    os.chmod(noted, 0o664)
    acl = struct.pack("<I", 2) + b"".join(struct.pack("<HHI", tag, perm, uid) for tag, perm, uid in (
        (0x01, 6, 0xFFFFFFFF), (0x02, 6, 1000), (0x04, 4, 0xFFFFFFFF), (0x10, 6, 0xFFFFFFFF),
        (0x20, 4, 0xFFFFFFFF)))
    attributes, measured = {}, False
    for name, value in (("user.note", b"kept"), ("system.posix_acl_access", acl)):
        try:
            os.setxattr(noted, name, value)
            attributes[name] = value
        except (AttributeError, OSError):
            pass
    # One that describes the old contents, as integrity measurement's do,
    # isn't kept; a trusted one stands in for it, where root can set one.
    try:
        os.setxattr(noted, "trusted.measured", b"old contents")
        measured = True
    except (AttributeError, OSError):
        pass
    synced = []
    saved_fsync = os.fsync
    os.fsync = lambda fd: synced.append(fd) or saved_fsync(fd)
    try:
        sidecars.rewrite_as_utf8(noted)
        synced_mark = len(synced)
        sidecars.rewrite_as_utf8(write("synced.csv", ansi_rows.encode("cp1252")))
        synced_rewrite = len(synced) - synced_mark
    finally:
        os.fsync = saved_fsync
    attributes_after = {name: os.getxattr(noted, name) for name in attributes
                        if name in os.listxattr(noted)} if attributes else {}
    measured_after = measured and "trusted.measured" in os.listxattr(noted)
    readonly_utf8 = write("readonly-utf8.csv", plain_bytes)
    os.chmod(readonly_utf8, 0o444)
    unmarked["readonly-utf8.csv"] = sidecars.rewrite_as_utf8(readonly_utf8)
    linked_utf8 = write("linked-utf8.csv", plain_bytes)
    os.link(linked_utf8, os.path.join(work, "hard-link-utf8"))
    unmarked["linked-utf8.csv"] = sidecars.rewrite_as_utf8(linked_utf8)
    readonly_ascii = write("readonly-ascii.csv", ascii_bytes)
    os.chmod(readonly_ascii, 0o444)
    readonly_ascii_said = sidecars.rewrite_as_utf8(readonly_ascii)
    # Two reasons at once, each with what would let a run rewrite it.
    both = write("both.csv", plain_bytes)
    os.chmod(both, 0o444)
    os.link(both, os.path.join(work, "hard-link-both"))
    both_said, _ = sidecars.rewrite_as_utf8(both)
    # A link in a folder that can't be written, to a file in one that can:
    # one in UTF-8 without the mark is given it, the file the link leads to
    # written; one in a code page, whose file as it was is kept beside the
    # link, isn't rewritten.
    away = os.path.join(work, "away")
    os.mkdir(away)
    linked_folder = os.path.realpath(work)
    for name, raw in (("marked-away.csv", plain_bytes), ("ansi-away.csv", ansi_rows.encode("cp1252"))):
        with open(os.path.join(away, name), "wb") as fh:
            fh.write(raw)
        os.symlink(os.path.join(away, name), os.path.join(work, name))
    saved_access = os.access
    os.access = lambda p, mode: os.path.realpath(p) != linked_folder and saved_access(p, mode)
    try:
        marked_away = sidecars.rewrite_as_utf8(os.path.join(work, "marked-away.csv"))
        ansi_away = sidecars.rewrite_as_utf8(os.path.join(work, "ansi-away.csv"))
    finally:
        os.access = saved_access
    # One in a code page with a report's rows in UTF-8, left as it is.
    readonly_kept = write("readonly-kept.csv", ansi_rows.encode("cp1252") + report_rows.encode("utf-8"))
    os.chmod(readonly_kept, 0o444)
    readonly_kept_said, _ = sidecars.rewrite_as_utf8(readonly_kept)
    # A field that holds a line end, read as written, CR LF and all.
    quoted = write("quoted.csv", "\ufeffImage,Alt\r\none.png,\"A red\r\nsquare\"\r\n".encode("utf-8"))
    quoted_rows = list(csv.reader(sidecars.csv_lines(sidecars.opened(quoted))))
    # And one whose lines end with a CR alone, as Excel 2011 for Mac ended
    # them, which a rewrite keeps.
    cr_ended = write("cr-ended.csv", "\ufeffImage,Alt\rone.png,Caf\u00e9\r".encode("utf-8"))
    cr_rows = list(csv.reader(sidecars.csv_lines(sidecars.opened(cr_ended))))
    # A read-only file in a code page is read so all the same, for root as
    # for anyone, and left as it is.
    readonly_ansi = write("readonly-ansi.csv", ansi_rows.encode("cp1252"))
    os.chmod(readonly_ansi, 0o444)
    readonly_ansi_said, readonly_ansi_why = sidecars.rewrite_as_utf8(readonly_ansi)
    # And another user's, read so and left to them.
    theirs_ansi = write("theirs-ansi.csv", ansi_rows.encode("cp1252"))
    saved_euid = os.geteuid
    os.geteuid = lambda: os.stat(theirs_ansi).st_uid + 1
    try:
        theirs_ansi_said, theirs_ansi_why = sidecars.rewrite_as_utf8(theirs_ansi)
    finally:
        os.geteuid = saved_euid
    # One that's there but can't be read: one this user may not read, as
    # root may read any, made by an open that refuses it; another user's
    # likewise, said to be theirs; a pipe, which reading would wait on; a
    # link to nothing; and a folder. Each is gone without, said to be, and
    # read as nothing, the filters given no file to read.
    unread = write("unread.csv", ansi_rows.encode("cp1252"))

    def refusing(file, mode="r", *args, **kwargs):
        if file == unread:
            raise PermissionError(13, "Permission denied", file)
        return open(file, mode, *args, **kwargs)
    sidecars.open = refusing
    saved_euid = os.geteuid
    try:
        unread_said = sidecars.rewrite_as_utf8(unread)
        unread_read = (sidecars.text(unread), sidecars.filter_copy(unread, work))
        unread_tool = sidecars.unreadable(unread)
        os.geteuid = lambda: os.stat(unread).st_uid + 1
        unread_theirs_said = sidecars.rewrite_as_utf8(unread)
    finally:
        os.geteuid = saved_euid
        del sidecars.open
    # A disk's error is said as it is, nothing for a person to allow.
    faulty = write("faulty.csv", ascii_bytes)

    def failing(file, mode="r", *args, **kwargs):
        if file == faulty:
            raise OSError(5, "Input/output error", file)
        return open(file, mode, *args, **kwargs)
    sidecars.open = failing
    try:
        faulty_said = sidecars.rewrite_as_utf8(faulty)
        faulty_tool = sidecars.unreadable(faulty)
    finally:
        del sidecars.open
    pipe = os.path.join(work, "pipe.csv")
    os.mkfifo(pipe)

    # Not an OSError, as TimeoutError is, which a reader would take for a
    # file it can't read and go on to open the pipe again; and again every
    # five seconds, should one be taken all the same.
    class Waited(RuntimeError):
        pass

    def waited(*_):
        raise Waited("reading %s waited for a writer" % pipe)
    alarm = signal.signal(signal.SIGALRM, waited)
    signal.setitimer(signal.ITIMER_REAL, 20, 5)
    try:
        pipe_said = sidecars.rewrite_as_utf8(pipe)
        pipe_read = (sidecars.text(pipe), sidecars.filter_copy(pipe, work))
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, alarm)
    nowhere = os.path.join(work, "nowhere.csv")
    os.symlink(os.path.join(work, "gone.csv"), nowhere)
    nowhere_said = sidecars.rewrite_as_utf8(nowhere)
    # A run that can't give a file its owner gives it its group.
    calls = []

    def chown(path, uid, gid):
        calls.append((uid, gid))
        if uid != -1:
            raise PermissionError(1, "Operation not permitted", path)
    grouped = write("grouped.csv", ansi_rows.encode("cp1252"))
    os.chown(grouped, *person)
    os.chown, saved_chown = chown, os.chown
    try:
        sidecars.rewrite_as_utf8(grouped)
    finally:
        os.chown = saved_chown
    # What a separate review of the rewrite found read wrong or stopped:
    # each read right now, in the code page it's saved in, alone in a file
    # with the line ends that code page's Excel writes.
    found = [("Bond length 1.54 \u00c5", "cp1252", "\r\n"),
             ("Bornholm \u00e4r en \u00f6", "cp1252", "\r\n"),
             ("an n\u00d7n matrix, A\u00d7B, 3x\u00b2y, M\u00b1SD", "cp1252", "\r\n"),
             ("Pipe \u00d8 25 mm, 3 \u00f3 4, the letter \u00f1, en \u00e5", "cp1252", "\r\n"),
             ("\u00e1, \u00e9, \u00ed, \u00f3, \u00fa; \u00c4\u00d6\u00dc", "cp1252", "\r\n"),
             ("inter\u00adnational", "cp1252", "\r\n"),
             ("p \u2264 0.05", "mac_roman", "\r\n"), ("area \u03c0 r", "mac_roman", "\r"),
             ("\u2206x", "mac_roman", "\r"), ("25\u00baC", "mac_roman", "\r\n"),
             ("10 k\u03a9", "mac_roman", "\r\n"), ("\u00d8 25 mm", "mac_roman", "\r\n"),
             ("5000 \u00c5", "mac_roman", "\r\n"), ("100 \u00b0C", "mac_roman", "\r\n"),
             ("the 1990\u2019s", "mac_roman", "\r\n"), ("\u2022 item", "mac_roman", "\r\n"),
             ("x\u2264y", "mac_roman", "\r"), ("Coca-Cola\u2122", "mac_roman", "\r\n"),
             ("Sales in \u20ac", "mac_roman", "\r\n"),
             ("\u00c0 la recherche", "mac_roman", "\r\n"), ("The \u00c9cole", "mac_roman", "\r\n"),
             ("\u00a1Atenci\u00f3n!", "mac_roman", "\r\n"), ("Ele \u00e9 o professor", "mac_roman", "\r\n"),
             ("see World Bank.\u00b9", "cp1252", "\r\n"), ("\u00c4, \u00d6 und \u00dc", "cp1252", "\r\n"),
             ("the 1990\u00b4s", "cp1252", "\r\n"), ("yen (\u00a5)", "cp1252", "\r\n"),
             ("yen (\u00a5)", "mac_roman", "\r"), ("C = 2\u03c0R, C = \u03c0D", "mac_roman", "\r"),
             ("25\u02daC and 98.6\u02daF, 45\u02da", "mac_roman", "\r"), ("\u00d6 island", "mac_roman", "\r"),
             ("Figure 3.2 \u2014 the supply curve", "mac_roman", "\r\n"),
             ("Prices in \u00a5 and $", "cp1252", "\r\n"), ("\u00c4\u00d6\u00dc \u00e4\u00f6\u00fc \u00df", "cp1252", "\r\n"),
             ("x\u00af = 5, 5\u00b4 tall", "mac_roman", "\r"), ("\u02c6 caret", "mac_roman", "\r"),
             ("O\u2019Neill and D\u2019Angelo", "mac_roman", "\r\n"),
             ("5\u2030 alcohol, the \u2030 rate", "mac_roman", "\r\n"), ("C = 2\u03c0r", "mac_roman", "\r\n"),
             ("a \u2013 b \u2014 c", "mac_roman", "\r\n")]
    read_found = []
    for n, (text, codec, end) in enumerate(found):
        raw = ("Image,Alt" + end + "one.png," + text + end).encode(codec)
        path, said, why = rewritten("found-%d.csv" % n, raw)
        read_found.append(why is None and data(path) == ("\ufeff" + raw.decode(codec)).encode("utf-8"))
    odd = sidecars.misplaced

    def unwritten(name, reasons, remedy, result=None, rewritten="can't be"):
        """A file in Windows-1252 the run couldn't rewrite: the run says why,
        reading it so all the same, and it's as it was, nothing beside it.
        result: what the rewrite returned, a patched case's in cases;
        rewritten, "isn't" for another user's that nothing but whose it is
        keeps the run from rewriting."""
        path = os.path.join(work, name)
        said, why = result or cases[name][1:]
        return (why is None and said == [
            "WARNING: %s isn't UTF-8: 1 line(s) of it are read as Windows-1252, as Windows Excel's "
            "plain \"CSV\" saves a file in the US and Western Europe, but it %s rewritten as "
            "UTF-8: %s. This run reads it so, and leaves it as it is. As read:"
            % (path, rewritten, reasons),
            "  line 2: one.png,A red square \u2013 large",
            "  A character there that isn't the one written means the file was saved in another "
            "code page: save it from Excel as \"CSV UTF-8 (Comma delimited)\". To have the run "
            "rewrite it, %s." % remedy]
            and data(path) == ansi_rows.encode("cp1252") and beside(name) == []
            and sidecars.text(path) == ansi_rows)

    def unmarkable(name, reasons, remedy, given="can't be given one"):
        """A file in UTF-8 without the mark that couldn't be given it, or,
        given "isn't given one", another user's that nothing but whose it
        is keeps the run from giving it."""
        path = os.path.join(work, name)
        return (unmarked[name] == (
            ["WARNING: %s has no byte-order mark, which Excel needs to open it as UTF-8, and %s: "
             "%s. It's read as UTF-8, as it is. Its lines outside ASCII, as they read:"
             % (path, given, reasons),
             "  line 2: one.png,Caf\u00e9",
             "  line 4: three.png,G\u00f6del<U+00A0>and Escher",
             "  A character there that isn't the one written means Excel saved the file in a code "
             "page whose bytes happen to read as UTF-8. To have the mark added, %s." % remedy], None)
            and data(path) == plain_bytes and beside(name) == []
            and sidecars.text(path) == plain_bytes.decode("utf-8"))
    return [
        ("a sidecar in Windows-1252 is rewritten as UTF-8, a mark first and its lines' ends as "
         "they were, a line in UTF-8 appended from a report kept as it was",
         lambda: ansi_why is None
         and data(ansi) == ("\ufeff" + ansi_rows + report_rows).encode("utf-8")),
        ("the file as it was is kept beside it, byte for byte",
         lambda: data(ansi + ".windows-1252") == ansi_rows.encode("cp1252")
         + report_rows.encode("utf-8")),
        ("and the run says so, showing the lines it read in the code page as now read, and "
         "what to do if a character is wrong",
         lambda: "%s wasn't UTF-8: 1 line(s) of it are read as Windows-1252, as Windows Excel's "
         "plain \"CSV\" saves a file" % ansi in ansi_said[0]
         and ansi + ".windows-1252" in ansi_said[0]
         and ansi_said[1] == "  line 2: one.png,A red square \u2013 large"
         and ansi_said[2:4] == ["  These were UTF-8, and are kept as they were:",
                                "  line 3: two.png,A blue caf\u00e9"]
         and "CSV UTF-8 (Comma delimited)" in ansi_said[-1] and len(ansi_said) == 5),
        ("a name taken keeps the one already there, the file as it was kept under the next",
         lambda: data(again + ".windows-1252") == b"taken"
         and data(again + ".windows-1252.2") == ansi_rows.encode("cp1252")
         and again + ".windows-1252.2" in again_said[0]),
        ("and the next after a dangling link, which the first name is",
         lambda: dangling_why is None and os.path.islink(dangling + ".windows-1252")
         and data(dangling + ".windows-1252.2") == ansi_rows.encode("cp1252")),
        ("a file Excel for Mac saved, in Mac OS Roman, is read so, though its lines end with CR "
         "LF, its characters misplaced in Windows-1252",
         lambda: data(mac) == ("\ufeff" + mac_rows).encode("utf-8")
         and "as Mac OS Roman, as Excel for Mac's plain \"CSV\" saves a file" in mac_said[0]
         and os.path.exists(mac + ".mac-roman")),
        ("and so is one with a byte Windows-1252 has no character for, its lines ending with CR "
         "LF or with a CR alone",
         lambda: data(french) == ("\ufeff" + french_rows).encode("utf-8")
         and "as Mac OS Roman" in french_said[0]
         and data(french_cr) == ("\ufeff" + french_cr_rows).encode("utf-8")
         and "as Mac OS Roman" in french_cr_said[0]),
        ("where neither code page has a character misplaced, a CR alone ending the lines tells "
         "Mac OS Roman, and CR LF Windows-1252",
         lambda: data(tie_cr) == "\ufeffImage,Alt\rone.png,The company\u00eds\r".encode("utf-8")
         and data(tie_crlf) == "\ufeffImage,Alt\r\none.png,The company\u2019s\r\n".encode("utf-8")),
        ("the lines read in the code page tell it so, though rows appended from a report end "
         "with CR LF",
         lambda: data(tie_report).startswith(
             "\ufeffImage,Alt\rone.png,The company\u00eds\r".encode("utf-8"))),
        ("a line that is UTF-8 is kept as it is, and shown apart, one of the code page's that "
         "happens to be UTF-8 among them",
         lambda: data(chance) == ("\ufeff" + header).encode("utf-8")
         + "one.png,Gau\u00df\u2019s law\r\n".encode("cp1252")
         + "two.png,Caf\u00e9 \u2013 red\r\n".encode("utf-8")
         and "  These were UTF-8, and are kept as they were:" in chance_said
         and "  line 2: one.png,Gau\u07d2s law" in chance_said),
        ("and a report's row is kept, a character that shows as nothing named where it's shown",
         lambda: data(kept_utf8) == ("\ufeff" + ansi_rows + kept_rows).encode("utf-8")
         and "  line 3: two.png,na\u2022ve<U+00A0>inter<U+00AD>nal" in kept_said),
        ("what the review found read wrong or stopped is read right, each line in the code page "
         "it's saved in",
         lambda: read_found == [True] * len(found)),
        ("ten lines are shown, and how many more there are",
         lambda: len(many_said) == 13 and many_said[10] == "  line 11: p9.png,Caf\u00e9 9"
         and many_said[11] == "  and 2 more"),
        ("a mark at the start of a line that isn't UTF-8 is read as UTF-8's, and kept, the "
         "file given no other",
         lambda: data(mark_first) == "\ufeffone.png,Caf\u00e9\r\n".encode("utf-8")
         and mark_said[1] == "  line 1: one.png,Caf\u00e9"),
        ("lines that read with a character misplaced in each code page stop it, saying how each "
         "reads them and how to save the file, which is left as it was",
         lambda: undefined_said is None
         and undefined_why.startswith("%s isn't UTF-8, and doesn't read as Windows-1252 (line 2 "
                                      "has byte 0x81, which is no character in it) or as Mac OS "
                                      "Roman (line 2 reads \"one.png,M\u00c5ller's square\", a "
                                      "character misplaced)" % undefined)
         and "CSV UTF-8 (Comma delimited)" in undefined_why
         and data(undefined) == b"Image,Alt\r\none.png,M\x81ller's square\r\n"
         and beside("undefined.csv") == []),
        ("as does one saved in another code page, Windows-1250 say",
         lambda: other_said is None
         and "Windows-1252 (line 2 has byte 0x9D, which is no character in it) or as Mac OS "
         "Roman (line 2 reads \"one.png,\u00fblu\u00f9ou\u00cbk\u02dd\", a character misplaced)"
         in other_why
         and "saved in another" in other_why and beside("other.csv") == []),
        ("and one in Greek, Windows-1253, which reads as Latin letters in a row",
         lambda: greek_why is not None and "Windows-1252 (line 2 reads \"" in greek_why
         and beside("greek.csv") == []),
        ("but a file whose one line is misplaced in each is read in the one with fewer, whichever "
         "its line ends prefer",
         lambda: one_odd_why is None and data(one_odd) == ("\ufeff" + one_odd_rows).encode("utf-8")
         and mac_odd_why is None and data(mac_odd) == ("\ufeff" + one_odd_rows).encode("utf-8")
         and os.path.exists(mac_odd + ".mac-roman")),
        ("and one whose line misplaced in each is among lines that aren't doesn't stop",
         lambda: two_odd_why is None and data(two_odd) == ("\ufeff" + two_odd_rows).encode("utf-8")),
        ("and a line misplaced as Windows-1252 among lines that aren't doesn't make the file Mac "
         "OS Roman",
         lambda: four_why is None and data(four) == ("\ufeff" + four_rows).encode("utf-8")),
        ("but a sign each reads alike stops neither, M\u00b1SD in a statistics caption",
         lambda: alike_why is None
         and data(alike) == "\ufeffImage,Alt\r\none.png,M\u00b1SD \u2013 by group\r\n".encode("utf-8")),
        ("and so does a control character, which no sidecar holds",
         lambda: control_said is None
         and control_why.startswith("%s: line 2 isn't UTF-8, and holds a control character "
                                    "(byte 0x01)" % control)
         and beside("control.csv") == []),
        ("a file another program holds open is read in its code page all the same, left as it "
         "was, with no copy beside it, the run saying why and to close it",
         lambda: unwritten("held.csv", "it couldn't be written (The process cannot access the "
                           "file)", "close the program that has it open")),
        ("and so is one a disk full partway kept from being written, the file not cut short",
         lambda: unwritten("full.csv", "it couldn't be written (No space left on device)",
                           "put right what kept it from being written")),
        ("and one whose copy beside it failed partway, which goes",
         lambda: unwritten("full-copy.csv", "it couldn't be written (No space left on device)",
                           "put right what kept it from being written")),
        ("and one in a folder that can't be written, before anything is written",
         lambda: unwritten("folder.csv", "its folder can't be written",
                           "make its folder writable")),
        ("a link's file is rewritten, and the link kept, the file as it was beside the link",
         lambda: link_why is None and os.path.islink(link)
         and data(target).startswith(b"\xef\xbb\xbfImage,Alt")
         and data(link + ".windows-1252") == ansi_rows.encode("cp1252")),
        ("and a file's mode is kept, and its owner, the copy beside it given them too",
         lambda: os.stat(moded).st_mode & 0o777 == 0o640
         and (os.stat(owned).st_uid, os.stat(owned).st_gid) == person
         and (os.stat(owned + ".windows-1252").st_uid, os.stat(owned + ".windows-1252").st_gid)
         == person),
        ("and where a mode can't be set, the file's rewritten without it",
         lambda: fat_why is None and data(fat).startswith(b"\xef\xbb\xbf")),
        ("a file in UTF-16, as Excel's Unicode Text saves one, is said to be no CSV",
         lambda: utf16_said is None and "is UTF-16" in utf16_why and beside("utf16.csv") == []),
        ("a sidecar in UTF-8 with the mark is left as it is, and nothing said",
         lambda: marked_said == ([], None)
         and data(marked) == "\ufeffImage,Alt\r\none.png,Caf\u00e9\r\n".encode("utf-8")
         and beside("marked.csv") == []),
        ("and one without the mark is given it, which Excel needs to open it as UTF-8, its bytes "
         "otherwise as they were, every line end and a mark partway among them, its mode kept, no "
         "copy beside it, and the run says so, showing its lines outside ASCII as they read",
         lambda: plain_said == (["%s had no byte-order mark, which Excel needs to open it as "
                                 "UTF-8: one is added, and nothing else in it changes. Its lines "
                                 "outside ASCII, as they read:" % plain,
                                 "  line 2: one.png,Caf\u00e9",
                                 "  line 4: three.png,G\u00f6del<U+00A0>and Escher",
                                 "  A character there that isn't the one written means Excel saved "
                                 "the file in a code page whose bytes happen to read as UTF-8: put it "
                                 "right in Excel, which opens the file as UTF-8 from now on."], None)
         and data(plain) == b"\xef\xbb\xbf" + plain_bytes
         and os.stat(plain).st_mode & 0o777 == 0o640 and beside("plain.csv") == []),
        ("and one of ASCII alone, which Excel reads the same either way, is given it too, and an "
         "empty one, so that every sidecar has it, the run saying so",
         lambda: ascii_said == (["%s had no byte-order mark: one is added, as Excel's \"CSV "
                                 "UTF-8\" writes one, and nothing else in it changes." % ascii], None)
         and data(ascii) == b"\xef\xbb\xbf" + ascii_bytes and beside("ascii.csv") == []
         and empty_said == (["%s had no byte-order mark: one is added, as Excel's \"CSV UTF-8\" "
                             "writes one, and nothing else in it changes." % empty], None)
         and data(empty) == b"\xef\xbb\xbf" and beside("empty.csv") == []),
        ("one that can't be given it is read as UTF-8 as it is, the run saying why, showing its "
         "lines outside ASCII, and what would let a run mark it: one held open",
         lambda: unmarkable("held-utf8.csv", "it couldn't be written (The process cannot access "
                            "the file)", "close the program that has it open")),
        ("another user's, which a run that isn't root leaves to them, nothing else keeping it "
         "from marking it, is warned of, the run saying that it isn't given the mark, and why",
         lambda: unmarkable("theirs-utf8.csv", CHOSEN % theirs_name, THEIRS % theirs_name,
                            "isn't given one")),
        ("and one of ASCII alone is warned of all the same, not noted",
         lambda: unmarked_ascii["theirs-ascii.csv"] == (
             ["WARNING: %s has no byte-order mark, and isn't given one: %s. It holds nothing "
              "outside ASCII, which reads the same either way. To have the mark added, %s."
              % (os.path.join(work, "theirs-ascii.csv"), CHOSEN % theirs_name,
                 THEIRS % theirs_name)], None)
         and data(os.path.join(work, "theirs-ascii.csv")) == ascii_bytes),
        ("and so is one only its owner may write, as the usual 0644 is, whose it is the only "
         "reason this user may not write it",
         lambda: unmarked_ascii["theirs-closed-ascii.csv"] == (
             ["WARNING: %s has no byte-order mark, and isn't given one: %s. It holds nothing "
              "outside ASCII, which reads the same either way. To have the mark added, %s."
              % (os.path.join(work, "theirs-closed-ascii.csv"), OWNED % theirs_name,
                 THEIRS % theirs_name)], None)
         and data(os.path.join(work, "theirs-closed-ascii.csv")) == ascii_bytes),
        ("and one in a folder with the sticky bit, where only a file's owner or the folder's may "
         "replace it, is its owner's to put right, a copy of one's own unable to replace it",
         lambda: unmarkable("sticky/theirs-utf8.csv", STICKY % theirs_name, ASK % theirs_name,
                            "isn't given one")),
        ("but another user's that a rewrite couldn't replace were it this user's, read-only or "
         "with another link to it, can't be given it, each reason said, a copy of one's own "
         "made writable",
         lambda: unmarkable("theirs-readonly-utf8.csv", OWNED % theirs_name + "; it's read-only",
                            "replace it with a copy of your own made with cp -p, which keeps its "
                            "mode, and make the copy writable, or " + ASK % theirs_name)
         and unmarkable("theirs-linked-utf8.csv", OWNED % theirs_name + "; another name links to "
                        "it, which a rewrite would leave as it was", THEIRS % theirs_name)),
        ("as one in a folder this user can't write can't, its owner's to put right, which no "
         "copy of one's own can take the place of",
         lambda: unmarkable("unwritable/theirs-utf8.csv", OWNED % theirs_name + "; its folder "
                            "can't be written", ASK % theirs_name)),
        ("a link says whose file it leads to: one in a plain folder, to a file in a folder with "
         "the sticky bit, can be replaced with a copy of one's own",
         lambda: unmarkable("link-to-sticky.csv", "it's a link to %s, which belongs to another "
                            "user, %s, in a folder where only a file's owner, or the folder's "
                            "owner, may replace it" % (os.path.join(work, "sticky", "linked-to.csv"),
                                                       theirs_name),
                            THEIRS % theirs_name, "isn't given one")),
        ("and another user's link in a folder with the sticky bit can't, its file's owner's to "
         "put right",
         lambda: unmarkable(os.path.join("sticky", "link-to-plain.csv"), "it's a link to %s, which "
                            "belongs to another user, %s, and though the user running this may "
                            "write it, a rewrite would take it from them"
                            % (os.path.join(work, "plain-to.csv"), theirs_name),
                            ASK % theirs_name, "isn't given one")),
        ("a rewritten file that can't be given its owner, as root in a user namespace can't give "
         "one a user outside it has, is left as it was, nothing beside it, the file said to be "
         "theirs",
         lambda: unmarkable("lost-utf8.csv", CHOSEN % lost_name, THEIRS % lost_name,
                            "isn't given one")),
        ("and one of a user outside the namespace, which root there may not write, is "
         "theirs, not marked immutable",
         lambda: unmarkable("outside-utf8.csv", OWNED % outside_name, THEIRS % outside_name,
                            "isn't given one")),
        ("a read-only one, as root too",
         lambda: unmarkable("readonly-utf8.csv", "it's read-only", "make it writable")),
        ("and one with another link to it, which a rewrite would part from it",
         lambda: unmarkable("linked-utf8.csv", "another name links to it, which a rewrite would "
                            "leave as it was", "make it a file of its own")),
        ("another user's that this user can't write either is said to be theirs, not "
         "read-only, which it isn't, and to be replaced with a copy of one's own",
         lambda: unmarkable("theirs-closed.csv", OWNED
                            % sidecars.owner_of(os.stat(os.path.join(work, "theirs-closed.csv"))),
                            THEIRS % sidecars.owner_of(os.stat(os.path.join(work, "theirs-closed.csv"))),
                            "isn't given one")),
        ("one's own that this user may not write, though it has a write bit, is said to be that",
         lambda: unmarkable("closed-utf8.csv", "this user may not write it",
                            "give the user running this permission to write it")),
        ("and one root can't write, though it has a write bit, as one marked immutable",
         lambda: unmarkable("immutable-utf8.csv", "it can't be written, though it has a write bit "
                            "(marked immutable, say)", "make it writable")),
        ("one on a disk mounted read-only is said to be, that alone",
         lambda: unmarkable("mounted-utf8.csv", "the disk it's on is mounted read-only",
                            "copy the book to a disk that can be written")),
        ("and one Windows won't let be replaced, as it answers for a file another program has "
         "open, is said to be either",
         lambda: unmarkable("windows-utf8.csv", "it couldn't be written (Access is denied)",
                            "close any program that has it open, or give the user running this "
                            "permission to write it and its folder")),
        ("and one whose replacing is refused, not by a program holding it, says so",
         lambda: unmarkable("denied-utf8.csv", "it couldn't be written (Permission denied)",
                            "give the user running this permission to write it and its folder")),
        ("a file's extended attributes are kept, an access control list among them, where the "
         "disk keeps them, but not one that describes its old contents",
         lambda: (attributes_after == attributes and not measured_after) if attributes
         else print("  skip  no extended attributes on this disk") or True),
        ("and what's rewritten is flushed to the disk before it's moved into place, the copy "
         "kept beside it too",
         lambda: synced_mark == 1 and synced_rewrite == 2),
        ("and one with two reasons gives both, and what would let a run mark it for each",
         lambda: both_said[0] == ("WARNING: %s has no byte-order mark, which Excel needs to open "
                                  "it as UTF-8, and can't be given one: it's read-only; another "
                                  "name links to it, which a rewrite would leave as it was. It's "
                                  "read as UTF-8, as it is. Its lines outside ASCII, as they read:"
                                  % both)
         and both_said[-1].endswith("To have the mark added, make it writable, and make it a "
                                    "file of its own.")),
        ("a link in a folder that can't be written leads to a file given the mark, but not to "
         "one rewritten from a code page, whose file as it was is kept beside the link",
         lambda: marked_away[0][0].startswith("%s had no byte-order mark"
                                              % os.path.join(work, "marked-away.csv"))
         and data(os.path.join(away, "marked-away.csv")) == b"\xef\xbb\xbf" + plain_bytes
         and "it can't be rewritten as UTF-8: its folder can't be written" in ansi_away[0][0]
         and data(os.path.join(away, "ansi-away.csv")) == ansi_rows.encode("cp1252")),
        ("one in a code page left as it is shows its lines in UTF-8 as read as they are",
         lambda: readonly_kept_said[2:4] == ["  These are UTF-8, and read as they are:",
                                             "  line 3: two.png,A blue caf\u00e9"]
         and sidecars.text(readonly_kept) == ansi_rows + report_rows),
        ("every reader reads a sidecar without the mark at its start, a field's line end as "
         "written, and lines that end with a CR alone",
         lambda: sidecars.text(marked) == "Image,Alt\r\none.png,Caf\u00e9\r\n"
         and quoted_rows == [["Image", "Alt"], ["one.png", "A red\r\nsquare"]]
         and cr_rows == [["Image", "Alt"], ["one.png", "Caf\u00e9"]]),
        ("and one of ASCII alone that can't be marked is noted, nothing in it reading otherwise",
         lambda: readonly_ascii_said == (["NOTE: %s has no byte-order mark, and can't be given one: "
                                          "it's read-only. It holds nothing outside ASCII, which "
                                          "reads the same either way. To have the mark added, make "
                                          "it writable." % readonly_ascii], None)
         and data(readonly_ascii) == ascii_bytes),
        ("a read-only file in a code page is read in it all the same, as root too, and left as it "
         "is; and a run that can't give a rewritten file its owner gives it its group",
         lambda: unwritten("readonly-ansi.csv", "it's read-only", "make it writable",
                           (readonly_ansi_said, readonly_ansi_why))
         and calls[:2] == [person, (-1, person[1])]),
        ("and another user's in a code page is read in it, and left to them, the run saying that "
         "it isn't rewritten, which it could be, and why",
         lambda: unwritten("theirs-ansi.csv", CHOSEN % sidecars.owner_of(os.stat(theirs_ansi)),
                           THEIRS % sidecars.owner_of(os.stat(theirs_ansi)),
                           (theirs_ansi_said, theirs_ansi_why), "isn't")),
        ("the filters read a copy in UTF-8 of one in a code page left as it is, and the file "
         "itself otherwise",
         lambda: data(sidecars.filter_copy(readonly_ansi, work))
         == ("\ufeff" + ansi_rows).encode("utf-8")
         and sidecars.filter_copy(readonly_utf8, work) == readonly_utf8
         and sidecars.filter_copy(os.path.join(work, "none.csv"), work)
         == os.path.join(work, "none.csv")),
        ("one that's there and can't be read is gone without, said to be, read as nothing, and "
         "given the filters as no file, left as it is",
         lambda: unread_said == (["WARNING: %s can't be read (Permission denied), so this run goes "
                                  "on without it, and leaves it as it is. To use it, give the user "
                                  "running this permission to read it." % unread], None)
         and unread_read == ("", "") and data(unread) == ansi_rows.encode("cp1252")
         and beside("unread.csv") == []),
        ("a tool that can do nothing without it says the same, and what would let it read it",
         lambda: unread_tool == "%s can't be read (Permission denied). To use it, give the user "
         "running this permission to read it." % unread),
        ("a disk's error stops the run, which going on would make a book without what the "
         "sidecar holds, nothing for a person to allow",
         lambda: faulty_said == (None, "%s can't be read (Input/output error), so the run stops "
                                       "rather than go on without what it holds. Run it again "
                                       "once it can be read." % faulty)
         and faulty_tool == "%s can't be read (Input/output error)." % faulty),
        ("and another user's is said to be theirs",
         lambda: unread_theirs_said == (["WARNING: %s can't be read (Permission denied); it belongs "
                                         "to %s, so this run goes on without it, and leaves it as "
                                         "it is. To use it, give the user running this permission "
                                         "to read it." % (unread, sidecars.owner_of(os.stat(unread)))],
                                        None)),
        ("a pipe is never read, which would wait for a writer, and is said not to be a file",
         lambda: pipe_said == (["WARNING: %s isn't a file but a pipe or a device, so this run goes "
                                "on without it, and leaves it as it is." % pipe], None)
         and pipe_read == ("", "")),
        ("and a link to nothing is said to be one",
         lambda: nowhere_said == (["WARNING: %s is a link to %s, which isn't there, so this run "
                                   "goes on without it, and leaves it as it is."
                                   % (nowhere, os.path.join(work, "gone.csv"))], None)),
        ("a path with nothing there is no sidecar to rewrite, and a folder is said to be one",
         lambda: sidecars.rewrite_as_utf8(os.path.join(work, "none.csv")) == ([], None)
         and sidecars.rewrite_as_utf8(work) == (["WARNING: %s is a folder, not a file, so this run "
                                                 "goes on without it, and leaves it as it is."
                                                 % work], None)),
        ("a Latin capital after a small letter, after a letter before a small one, between capitals "
         "before a small one, or after a digit before a small one is misplaced, but not in a word all "
         "in capitals",
         lambda: odd("don\u00d5t") == 1 and odd("caf\u00c8") == 1 and odd("M\u0178ller") == 1
         and odd("the 1990\u00d5s") == 1 and odd("O\u00d5Neill") == 1
         and odd("CAF\u00c9 NO\u00cbL \u00c9cole 10 k\u03a9 4\u00c9 A\u00c7\u00d5ES") == 0),
        ("and a capital before a capital and a small letter",
         lambda: odd("\u00c1Atenci\u00f3n") == 1 and odd("\u00c9COLE \u00c9cole") == 0),
        ("and a small Latin letter before a capital, but \u00df (\u00aa and \u00ba are no Latin "
         "letters), and \u00aa after a small letter",
         lambda: odd("\u00ecHello") == 1 and odd("25\u00fbC") == 1 and odd("Cola\u00aa") == 1
         and odd("STRA\u00dfE N\u00baA 25\u00baC D\u00aa 2\u03c0R \u03bcF") == 0),
        ("and a letter text doesn't have alone, alone, but not one it has",
         lambda: [odd(t) for t in ("a \u00d0 b", "3.2 \u00d1 the", "\u00ef item", "Ele \u017d o",
                                   "Section \u00db 4")] == [1] * 5
         and odd("1.54 \u00c5, \u00d8 25, en \u00e5, en \u00f6, \u00f1, 3 \u00f3 4, \u00e0 la, "
                 "\u00c9 isso, \u00c7, \u00c4, \u00d6") == 0),
        ("and \u00e4 after a number but in a word, as Mac OS Roman's \u2030 reads there, but not "
         "alone elsewhere",
         lambda: odd("5 \u00e4 alcohol") == 1 and odd("0,5\u00e4") == 1
         and odd("Fotos u. \u00e4., Symbole o. \u00e4., the letter \u00e4, \u00e5, \u00e4 och \u00f6") == 0
         and odd("\u00e4 52") == 0 and odd("5 \u00e4hnliche F\u00e4lle") == 0),
        ("and a Latin letter between digits, and \u00e0 or \u00fb after a digit but in a word, as "
         "Mac OS Roman's \u2021 and \u02da read there",
         lambda: odd("1990\u00f12000") == 1 and odd("6\u00d62") == 1 and odd("Table 1\u00e0") == 1
         and odd("A 45\u00fb angle") == 1
         and odd("2\u03c03 1990\u20132000 1.54\u00c5 2\u00e8me 1\u00ba Le 2\u00e8 \u00e9tage, 5\u00e8 "
                 "curs, 17\u00df-estradiol, y = 2\u0192(x)") == 0),
        ("and \u0192 beside a letter, but not alone",
         lambda: odd("\u0192cole") == 1 and odd("CAF\u0192") == 1 and odd("\u0192(x) = 2") == 0),
        ("and a third letter outside ASCII in a row, a small one among them, or a fourth, of any "
         "script",
         lambda: odd("\u00cf\u00f0\u00e8\u00e2\u00e5\u00f2") == 4 and odd("\u00aa\u00e2\u00f0") == 1
         and odd("\u00d6\u00d0\u00ce\u00c4") == 1
         and odd("Gr\u00f6\u00dfe cr\u00e9\u00e9e a\u00e7\u00e3o \u00e9\u00e9\u2013\u00e9\u00e9 "
                 "\u00c4\u00d6\u00dc") == 0),
        ("and a mark or a sign between letters, but an apostrophe, a dash, a middle dot, an "
         "ellipsis, a soft hyphen, a superscript, or a math sign",
         lambda: odd("M\u2030rz") == 1 and odd("a\u25cab") == 1 and odd("na\u2022ve") == 1
         and odd("don\u2019t Hawai\u2018i test\u2013retest l\u00b7l well\u2014known wait\u2026what "
                 "inter\u00adnational a\u00d7b a\u00f7b x\u00b2y a\u2264b") == 0),
        ("and a spacing accent beside a letter or another character outside ASCII, or before "
         "a number, but \u00b4 after a letter or a digit, \u00af after a letter, and \u02da after "
         "a digit",
         lambda: odd("\u00af 25 mm") == 1 and odd("sch\u02c6n") == 1 and odd("f\u00b8r") >= 1
         and odd("\u2030\u02c6\u00b8") == 2 and odd("\u02daC") == 1
         and odd("don\u00b4t 1990\u00b4s 5\u00b4 tall 25\u02daC 45\u02da x\u00af = 5 "
                 "\u02c6 caret \u00a8 diaeresis") == 0),
        ("and a superscript after a space, \u00b9 between a digit and a letter, a soft hyphen but "
         "in a word, and a fraction after a letter or before a capital",
         lambda: odd("p \u00b2 0.05") == 1 and odd("\u00b9 r") == 1 and odd("2\u00b9r") == 1
         and odd("a \u00ad b") == 1
         and odd("10 k\u00bd") == 1 and odd("25\u00bcC") == 1
         and odd("x\u00b2 10\u00b3 kg (a+b)\u00b2 Bank.\u00b9 inter\u00adnal 2\u00bd cups 10\u00b3m "
                 "6.02\u00d710\u00b2\u00b3mol, 2019\u00b9 and 2020\u00b2") == 0),
        ("and \u00a1 or \u00bf after a letter or a digit, or with no ! or ? after it",
         lambda: odd("100 \u00a1C") == 1 and odd("3\u00a1C!") == 1 and odd("s\u00bfx?") == 1
         and odd("\u00a1Hola! Y \u00bfqu\u00e9?") == 0),
        ("and \u00a5 at a field's start before a space and a letter, as a bullet is, and \u00a4 "
         "or \u00a6 anywhere",
         lambda: odd("\u00a5 item") == 1 and odd("x.png,\u00a5 item") == 1
         and odd("Section \u00a4 4.2") == 1
         and odd("\u00a5500, 500 \u00a5, yen (\u00a5), \u00a5/$, Prices in \u00a5 and $") == 0),
        ("and a character each code page reads alike counts for nothing, wherever it sits",
         lambda: odd("M\u00b1SD Pearson\u00a9s 10 \u00b5M 5\u00a2c \u00a3k") == 0),
    ]


def check_report_marks():
    """Every CSV a run writes for a person starts with a byte-order mark,
    once, which Excel needs to read it as UTF-8: without one, an en dash
    shows as "â€“". Each is read back as written, the output check's
    findings by findings.read_csv among them."""
    import deckrun
    import findings as findings_lib
    import unpacking
    convert = load(os.path.join(ROOT, "bin", "convert.py"), "convert_report_marks")
    convert.say = lambda text: None
    headers = load(os.path.join(ROOT, "bin", "table-headers.py"), "table_headers_reports")
    work = scratch("report-marks-")
    path = lambda name: os.path.join(work, name)
    rows_file = path("rows")
    with open(rows_file, "w", encoding="utf-8", newline="") as fh:
        fh.write("ch1/media/rId7.png,,ch1,missing,\u03b1 \u2013 \u03b2,,\n")
    convert.write_report(rows_file, path("image-alt-missing.csv"),
                         "Image,Alt,Source,Reason,CurrentAlt,Drafted by,Reviewed", "image(s)")
    links_file = path("links")
    with open(links_file, "w", encoding="utf-8", newline="") as fh:
        fh.write("new,https://example.org/a,,ch1,See \u2013\n")
    convert.write_bare_links(links_file, path("bare-links-new.csv"), path("bare-links.csv"))
    convert.write_fidelity([("docx", "ch1", "frame", "\u2013")], path("fidelity.csv"))
    found = [findings_lib.Finding("html/ch1.html", "image-without-alt", "\u03b1.png")]
    findings_lib.write_csv(path("output-check.csv"), found)
    back = findings_lib.read_csv(path("output-check.csv"))
    unpacking.write_report(path("unpack-report.csv"), [("ch1", "a-check", "\u2013")])
    headers.write_csv(path("table-headers-new.csv"), headers.SIDECAR_COLUMNS,
                      [{"key": "aaa", "headers": "both", "preview": "\u03b1 | \u03b2"}])
    deckrun.write_rows(path("slide-titles-new.csv"), deckrun.TITLE_COLUMNS,
                       [["deck/slide-256", "", "deck", "", ""]])
    written = sorted(n for n in os.listdir(work) if n.endswith(".csv"))

    def starts(name):
        with open(path(name), "rb") as fh:
            data = fh.read()
        return data.startswith(b"\xef\xbb\xbf") and not data[3:].startswith(b"\xef\xbb\xbf")
    with open(path("image-alt-missing.csv"), encoding="utf-8-sig", newline="") as fh:
        alt_rows = list(csv.DictReader(fh))
    return [
        ("each report is written",
         lambda: written == ["bare-links-new.csv", "fidelity.csv", "image-alt-missing.csv",
                             "output-check.csv", "slide-titles-new.csv",
                             "table-headers-new.csv", "unpack-report.csv"]),
        ("and starts with one byte-order mark", lambda: all(starts(n) for n in written)),
        ("a report reads back as it was written, its first column by name",
         lambda: [(r["Image"], r["CurrentAlt"]) for r in alt_rows]
         == [("ch1/media/rId7.png", "\u03b1 \u2013 \u03b2")]),
        ("and the output check's findings, each where it was",
         lambda: [(f.where, f.check) for f in back] == [("html/ch1.html", "image-without-alt")]),
    ]


def check_cased_images_in_copies():
    """An image a source names in another case than its file's, in the
    source's copy.

    The conversion reads such an image as its file, and its alt text is
    keyed on the file's path; a Markdown source's copy found the row, and
    an HTML source's didn't, keying on the src as written, so the site's
    page had the alt text and the author's copy of the page didn't.
    """
    import htmlremediate
    import mdremediate
    work = tempfile.mkdtemp(prefix="cased-images-")
    os.makedirs(os.path.join(work, "Assets"))
    for name in ("red.png", "my pic.png"):
        with open(os.path.join(work, "Assets", name), "wb") as fh:
            fh.write(b"")
    alts = {"Assets/red": "A red square", "Assets/my pic": "A picture"}
    page = ('<p><img src="assets/Red.png"> <img src="./Assets/my%20pic.png" alt="">'
            ' <img src="assets/blue.png"></p>')
    copied = htmlremediate.remediate_images(page, alts, work)
    shutil.rmtree(work, ignore_errors=True)
    return [
        ("an HTML page's image in another case takes its file's alt text, spaces decoded",
         lambda: '<img src="assets/Red.png" alt="A red square">' in copied[0]
         and 'alt="A picture"' in copied[0] and copied[1]["described"] == 2),
        ("one naming no file in any case is left as it is",
         lambda: '<img src="assets/blue.png">' in copied[0]),
        ("the Markdown copy's key and the HTML copy's agree",
         lambda: htmlremediate.image_key("assets/Red.png", None) == "assets/Red"
         and mdremediate.sidecar_key("assets/my%20pic.png") == "assets/my pic"
         == htmlremediate.image_key("./assets/my%20pic.png")),
    ]


def check_media_keys_in_copies():
    """A picture in a book's own media/ folder, in a source's copy.

    The filter keys a picture whose path is in media/ under its page's
    name, as it keys a Word file's media (figures-and-tables.lua's
    qualify_media), and the report gives that key, the path as Pandoc's
    reader writes it, a space as %20; the pages took such a row, and an
    HTML or a Markdown copy keyed the path alone, so the author's copy of
    an unpacked OpenStax page kept none of them.
    """
    import htmlremediate
    import mdremediate
    import sidecars
    alts = {"p/media/red": "A red square", "p/media/my%20pic": "A picture",
            "media/green": "A green square"}
    page = ('<p><img src="media/red.png"> <img src="media/my pic.png" alt="">'
            ' <img src="media/green.png"></p>')
    html_p = htmlremediate.remediate_images(page, alts, None, "p")
    html_q = htmlremediate.remediate_images(page, alts, None, "q")
    text = "![](media/red.png) and ![](<media/my pic.png>)\n"
    doc = {"blocks": [{"t": "Para", "c": [
        {"t": "Image", "c": [["", [], []], [], ["media/red.png", ""]]},
        {"t": "Space"}, {"t": "Str", "c": "and"}, {"t": "Space"},
        {"t": "Image", "c": [["", [], []], [], ["media/my%20pic.png", ""]]}]}]}
    md_p = mdremediate.remediate_images(text, doc, alts, None, "p")
    # And each copy's remediate() gives its file's name as the page's.
    work = scratch("media-keys-")
    for name, content in (("p.html", page), ("p.md", text)):
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(content)
    htmlremediate.remediate(os.path.join(work, "p.html"), os.path.join(work, "p-copy.html"),
                            alts=alts)
    mdremediate.remediate(os.path.join(work, "p.md"), os.path.join(work, "p-copy.md"), alts=alts)

    def copied(name):
        with open(os.path.join(work, name), encoding="utf-8") as fh:
            return fh.read()
    return [
        ("an HTML copy's picture in media/ takes the row the report keys it by, its page's "
         "name first and a space as Pandoc's reader writes it",
         lambda: '<img src="media/red.png" alt="A red square">' in html_p[0]
         and '<img src="media/my pic.png" alt="A picture">' in html_p[0]),
        ("and one keyed by its path alone still takes that row",
         lambda: '<img src="media/green.png" alt="A green square">' in html_p[0]
         and html_p[1]["described"] == 3),
        ("another page's rows aren't its",
         lambda: html_q[1]["described"] == 1 and "A red square" not in html_q[0]),
        ("a Markdown copy's likewise",
         lambda: md_p[0] == "![A red square](media/red.png) and ![A picture](<media/my pic.png>)\n"
         and md_p[1]["described"] == 2),
        ("and each copy written is keyed by its file's name, as its page is",
         lambda: 'alt="A picture"' in copied("p-copy.html")
         and "![A picture](<media/my pic.png>)" in copied("p-copy.md")),
        ("a path as Pandoc's readers write it, as its HTML reader was found to",
         lambda: sidecars.pandoc_uri("media/a[1] b^c{d}|e.png")
         == "media/a%5B1%5D%20b%5Ec%7Bd%7D%7Ce.png"
         and sidecars.pandoc_uri("media/n\u00a0b\u2003.png") == "media/n%C2%A0b%E2%80%83.png"
         and sidecars.page_media_key("p", "images/x.png") is None),
    ]


def check_alt_text_rules():
    """Every kind of alt text lib/alttext.py finds has its finding in each
    checker that applies its rules, declared in lib/findings.py; and one
    alt text on different pictures is found by what tells them apart,
    asked only of pictures whose alt text another has."""
    import alttext
    import findings as findings_lib
    source = open(os.path.join(ROOT, "lib", "alttext.py"), encoding="utf-8").read()
    kinds = set(re.findall(r'return \("([a-z-]+)", ', source))
    pdf = {"placeholder": "pdf-figure-alt-is-placeholder"}
    wanted = {"pptx-alt-" + k for k in kinds} | {"pptx-alt-shared"}
    for prefix in ("image-alt-", "source-image-alt-"):
        wanted |= {prefix + k for k in kinds - {"too-long"}} | {prefix + "shared"}
    wanted |= {pdf.get(k, "pdf-figure-alt-" + k) for k in kinds - {"too-long"}}
    asked = []

    def identity(key):
        asked.append(key)
        return {"a": 1, "b": 2, "c": 1}.get(key, key)
    found = alttext.shared([("a", "A line"), ("b", "a line."), ("c", "A line"), ("d", "Dots"),
                            ("e", "Dots"), ("f", "Alone"), ("g", "")], identity)
    copies = alttext.shared([("a", "A line"), ("c", "A line")], identity)
    return [
        ("a picture's name no file system takes is its own identity, not a crash",
         lambda: alttext.digest("a\x00.png", "a\x00.png") == "a\x00.png"),
        ("each kind's finding is declared, for pages, sources, decks, and PDFs",
         lambda: "credit" in kinds and not wanted - set(findings_lib.CHECKS)
         or print("    undeclared: %s" % sorted(wanted - set(findings_lib.CHECKS)))),
        ("one alt text on different pictures, case and closing punctuation aside, is "
         "found with how many others have it; identity is asked only of pictures sharing one",
         lambda: found == {0: 1, 1: 1, 2: 1, 3: 1, 4: 1} and sorted(asked[:5]) == [
             "a", "b", "c", "d", "e"]),
        ("two files holding one picture are one picture",
         lambda: copies == {}),
        ("the reason says how many, in the report's words",
         lambda: alttext.shared_reason(1) == "shared with 1 other image"
         and alttext.shared_reason(2, "picture") == "shared with 2 other pictures"),
    ]


def check_wcag_criteria():
    """WCAG 2.2's criteria as W3C's source has them (lib/wcag.py), and
    every WCAG standard a finding names agreeing with them: a fact
    written down twice."""
    import findings as findings_lib
    import wcag
    numbers = list(wcag.CRITERIA)
    standards = {}
    for check, meaning in findings_lib.CHECKS.items():
        if meaning[2].startswith("WCAG"):
            found = re.match(r"WCAG 2\.\d SC (\d\.\d+\.\d+) \((?:A|AA|AAA)\)$", meaning[2])
            standards[check] = (meaning[2], wcag.standard(found.group(1)) if found else None)
    return [
        ("87 criteria, 61 from WCAG 2.0, 17 from 2.1, and 9 from 2.2, each number once",
         lambda: len(numbers) == len(set(numbers)) == 87
         and [sum(1 for entry in wcag.CRITERIA.values() if entry[2] == version)
              for version in ("2.0", "2.1", "2.2")] == [61, 17, 9]),
        ("each at a level but 4.1.1, obsolete and removed",
         lambda: [n for n, entry in wcag.CRITERIA.items()
                  if entry[1] not in ("A", "AA", "AAA")] == ["4.1.1"]),
        ("the criteria of veraPDF's machine profiles, each by its name and level, and "
         "one 2.0 hadn't by the version that brought it",
         lambda: [wcag.named(n) for n in ("1.3.1", "1.4.3", "1.4.4", "1.4.10", "2.4.9",
                                          "4.1.2")] == [
             "1.3.1 Info and Relationships (A)", "1.4.3 Contrast (Minimum) (AA)",
             "1.4.4 Resize Text (AA)", "1.4.10 Reflow (AA, WCAG 2.1)",
             "2.4.9 Link Purpose (Link Only) (AAA)", "4.1.2 Name, Role, Value (A)"]),
        ("a criterion's Understanding document, and its standard as findings name one",
         lambda: wcag.url("2.4.9")
         == "https://www.w3.org/WAI/WCAG22/Understanding/link-purpose-link-only.html"
         and wcag.standard("1.4.10") == "WCAG 2.1 SC 1.4.10 (AA)"),
        ("a number WCAG 2.2 doesn't have points at WCAG 2.2 itself",
         lambda: wcag.url("9.9.9") == "https://www.w3.org/TR/WCAG22/"
         and wcag.standard("9.9.9") == "WCAG 2.2 SC 9.9.9" and wcag.named("9.9.9") == "9.9.9"),
        ("every WCAG standard a finding names is its criterion's, the version and level W3C's",
         lambda: len(standards) > 50
         and [check for check, (ours, theirs) in standards.items() if ours != theirs] == []),
    ]


def check_wcag_report():
    """veraPDF's JSON report of its WCAG profile read as findings: only
    the profile's own rules, each a note counting its failed checks, or,
    verbose, each failed check a note at its page with what veraPDF found
    and the criterion; nothing but a warning when the probe, in the same
    run, passed, since then no WCAG rule was checked."""
    import findings as findings_lib
    import pdfcheck
    probe, book = "/w/wcag-probe.pdf", "/books/ia/book.pdf"

    def job(name, rules):
        return {"itemDetails": {"name": name, "size": 1}, "validationResult": [
            {"profileName": "WCAG 2.2 machine validation profile",
             "details": {"ruleSummaries": rules}}]}

    def rule(spec, clause, test, description, checks, failed=None, kind="SATextChunk"):
        return {"specification": spec, "clause": clause, "testNumber": test, "status": "failed",
                "failedChecks": len(checks) if failed is None else failed, "object": kind,
                "description": description, "checks": checks}

    def check(message, context="", location=None):
        return dict({"status": "failed", "context": context, "errorMessage": message},
                    **({"location": location} if location else {}))
    build = {"releaseDetails": [{"id": "core", "version": "1.30.3"},
                                {"id": "apps", "version": "1.30.3"}]}
    repeated = rule("WCAG2.2", "1.3.1", 1, "Text should not contain repeated non space characters",
                    [check("Text contains 10 repeated non space characters",
                           "root/doc[0]/repeatedCharacters[0]",
                           '{"bbox":[{"p":0,"rect":[72.0,717.3,138.72,731.172]}]}')],
                    kind="SARepeatedCharacters")
    span = ("root/doc[0]/StructTreeRoot[0]/children[0](11 0 obj Document Document)"
            "/children[5](17 0 obj Span Span)")
    text = ("root/doc[0]/StructTreeRoot[0]/children[0](11 0 obj Document Document)"
            "/children[2](14 0 obj P P)/children[0]{text too  small to read}")
    rules = [
        rule("ISO_14289_2", "8.2.5.2", 2, "A PDF/UA rule", [check("a message")]),
        rule("WCAG2.2", "4.1.2", 17, "Redundant span",
             [check("score = 1, correct type = null", span)]),
        rule("WCAG2.2", "2.4.9", 1, "Links shall contain an alternate description",
             [check("A link annotation does not include an alternate description",
                    "root/doc[0]/pages[2]/annots[0]")]),
        rule("WCAG2.2", "1.4.4", 1, "Font size is too small",
             [check("textSize = 3", text, '{"bbox":[{"p":652,"rect":[72,679,99,682]}]}')]),
        rule("WCAG2.2", "1.4.3", 1, "Contrast",
             [check("contrastRatio = 3.1", "",
                    '{"bbox":[{"p":10,"rect":[0,0,1,1]},{"p":9,"rect":[0,0,1,1]}]}'),
              check("contrastRatio = 2.8", "", '{"bbox":[{"p":11,"rect":[0,0,1,1]}]}')],
             failed=150),
    ]
    modules = {"wcag-validation": ["1.30.3"], "wcag-algorithms": ["1.30.3"]}
    read = pdfcheck.wcag_report({"report": {"buildInformation": build, "jobs": [
        job(probe, [repeated]), job(book, rules)]}}, probe, "/tools/verapdf-wcag", modules,
        verbose=True)
    by = {}
    for found in read["findings"]:
        by.setdefault(found.check, []).append(found)
    lines = [group[0] for _, group in sorted(read["rules"])]
    listed = [line for _, group in sorted(read["rules"]) for line in group]
    counted = pdfcheck.wcag_report({"report": {"buildInformation": build, "jobs": [
        job(probe, [repeated]), job(book, rules)]}}, probe, "/tools/verapdf-wcag", modules)
    thirty = rule("WCAG2.2", "2.4.9", 1, "Links",
                  [check("a message", f"root/doc[0]/pages[{n}]/annots[0]") for n in range(30)])
    many, many_pages, _ = pdfcheck.wcag_rule_findings("book.pdf", thirty)
    many_line = pdfcheck.wcag_rule_line("book.pdf", thirty, many_pages)
    older = pdfcheck.wcag_report({"report": {"buildInformation": build, "jobs": [
        job(probe, [rule("ISO_14289_2", "8.2.5.2", 2, "A PDF/UA rule", [check("a message")])]),
        job(book, rules)]}}, probe, "/tools/verapdf-wcag",
        dict(modules, **{"wcag-validation": ["1.30.2"]}))
    read_back = findings_lib.Finding("b.pdf", "verapdf-wcag:1.4.10-1", "")
    # A report without the probe's job, and one whose probe failed a WCAG
    # rule on an object veraPDF has without the modules, are no proof.
    unprobed = pdfcheck.wcag_report({"report": {"buildInformation": build, "jobs": [
        job(book, rules)]}}, probe, "/tools/verapdf-wcag", modules)
    core = pdfcheck.wcag_report({"report": {"buildInformation": build, "jobs": [
        job(probe, [rule("WCAG2.2", "1.3.4", 1, "Pages shall have the same orientation",
                         [check("a message")], kind="PDPage")])]}},
        probe, "/tools/verapdf-wcag", modules)
    # A module's version not veraPDF's, a file veraPDF skipped, and one it
    # couldn't check, each a warning beside what was read.
    told = pdfcheck.wcag_report({"report": {"buildInformation": build, "jobs": [
        job(probe, [repeated]), job(book, rules),
        {"itemDetails": {"name": "/books/ia/broken.pdf"},
         "taskException": {"type": "PARSE", "exceptionMessage": "Couldn't parse stream"}}]}},
        probe, "/tools/verapdf-wcag", dict(modules, **{"wcag-validation": ["1.30.2"]}),
        expected=[book, "/books/ia/broken.pdf", "/books/ia/skipped.pdf"], verbose=True)
    # Reports no veraPDF writes: none of them stops the run.
    shapes = [None, {"report": None}, {"report": {"jobs": None}},
              {"report": {"buildInformation": {"releaseDetails": None}, "jobs": [None, 5]}},
              {"report": {"jobs": [{"itemDetails": None, "validationResult": None}]}},
              {"report": {"jobs": [job(probe, [repeated]), job(book, [
                  None, {"specification": "WCAG2.2", "clause": "1.4.3", "testNumber": "1a",
                         "failedChecks": "many", "checks": [None, {"status": "failed",
                                                                    "location": {"bbox": 5},
                                                                    "context": None}]}]),
                  {"itemDetails": {"name": "/w/a#page=b.pdf"}, "validationResult": [
                      {"details": {"ruleSummaries": [rule(
                          "WCAG2.2", "4.1.2", 17, "Redundant span", [check("x")])]}}]},
                  {"itemDetails": {"name": book}, "validationResult": [
                      {"details": None}, "nonsense"]}]}}]
    survived = []
    for shape in shapes:
        try:
            survived.append(pdfcheck.wcag_report(shape, probe, "f", modules,
                                                 expected=[book]))
        except Exception as exc:
            survived.append(exc)
    return [
        ("the probe failed a WCAG rule, so the modules loaded, and the book was checked",
         lambda: read["loaded"] and read["checked"] == 1 and read["version"] == "1.30.3"),
        ("each rule a note of its own, counting its failed checks and naming their pages, "
         "where veraPDF gives them",
         lambda: [(f.where, f.check, f.severity) for f in counted["findings"]] == [
             ("book.pdf", "verapdf-wcag:4.1.2-17", "note"),
             ("book.pdf", "verapdf-wcag:2.4.9-1", "note"),
             ("book.pdf", "verapdf-wcag:1.4.4-1", "note"),
             ("book.pdf", "verapdf-wcag:1.4.3-1", "note")]
         and counted["findings"][3].detail == (
             "Contrast: 150 failed check(s), the first 2 on pages 10, 12; --verbose lists "
             "the 2 veraPDF listed, with what the PDF has there. 1.4.3 Contrast (Minimum) (AA): "
             "https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html. veraPDF's "
             "WCAG checks are experimental and may be wrong.")
         and counted["findings"][0].detail.startswith("Redundant span: 1 failed check(s); ")
         and counted["findings"][1].detail.startswith(
             "Links shall contain an alternate description: 1 failed check(s), page 3; ")),
        ("the first 20 pages named, and how many more, and 8 in its line in the summary",
         lambda: len(many) == 1 and many[0].detail.startswith(
             "Links: 30 failed check(s), pages 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, "
             "15, 16, 17, 18, 19, 20, and 10 more; --verbose lists each")
         and "30 failed check(s), pages 1, 2, 3, 4, 5, 6, 7, 8, and 22 more: Links." in many_line),
        ("and its line in the summary, the same as verbose's, without the checks'",
         lambda: [group for _, group in sorted(counted["rules"])]
         == [[line] for line in lines]),
        ("verbose, each listed check a line after its rule's, saying where and what veraPDF "
         "found", lambda: listed[:4] == [
             lines[0], "  book.pdf#page=10: contrastRatio = 3.1",
             "  book.pdf#page=12: contrastRatio = 2.8",
             "  book.pdf: 148 more failed check(s), which veraPDF didn't list (it lists about "
             "10,000 of a PDF's at most)"]
         and listed[-1] == '  book.pdf: score = 1, correct type = null (Span, object 17)'),
        ("only the profile's own rules are reported, and nothing of the probe",
         lambda: sorted(by) == ["verapdf-wcag:1.4.3-1", "verapdf-wcag:1.4.4-1",
                                "verapdf-wcag:2.4.9-1", "verapdf-wcag:4.1.2-17"]),
        ("each failed check a note, by veraPDF, its criterion the standard",
         lambda: {f.severity for f in read["findings"]} == {"note"}
         and {f.tool for f in read["findings"]} == {"verapdf"}
         and by["verapdf-wcag:2.4.9-1"][0].standard == "WCAG 2.0 SC 2.4.9 (AAA)"),
        ("its page counted from 1: its boxes' first, or the page an annotation is on",
         lambda: [by[c][0].where for c in ("verapdf-wcag:1.4.4-1", "verapdf-wcag:2.4.9-1",
                                           "verapdf-wcag:1.4.3-1")]
         == ["book.pdf#page=653", "book.pdf#page=3", "book.pdf#page=10"]),
        ("and none where veraPDF gives none",
         lambda: by["verapdf-wcag:4.1.2-17"][0].where == "book.pdf"),
        ("the detail: the rule, veraPDF's message, the text and its element, the criterion, "
         "its Understanding document, and the caveat",
         lambda: by["verapdf-wcag:1.4.4-1"][0].detail == (
             'Font size is too small: textSize = 3, "text too small to read" (P, object 14). '
             "1.4.4 Resize Text (AA): https://www.w3.org/WAI/WCAG22/Understanding/"
             "resize-text.html. veraPDF's WCAG checks are experimental and may be wrong.")
         and "(Span, object 17)" in by["verapdf-wcag:4.1.2-17"][0].detail),
        ("a rule failed more often than veraPDF lists says how many more",
         lambda: len(by["verapdf-wcag:1.4.3-1"]) == 3
         and by["verapdf-wcag:1.4.3-1"][2].detail.startswith(
             "Contrast: 148 more failed check(s), which veraPDF didn't list (it lists about "
             "10,000 of a PDF's at most).")),
        ("a summary line a rule, in the criteria's order, with the count and the pages, of "
         "the checks veraPDF listed when it didn't list them all",
         lambda: [line.split(",")[0] for line in lines] == [
             "book.pdf: verapdf-wcag:1.4.3-1", "book.pdf: verapdf-wcag:1.4.4-1",
             "book.pdf: verapdf-wcag:2.4.9-1", "book.pdf: verapdf-wcag:4.1.2-17"]
         and "150 failed check(s), the first 2 on pages 10, 12: Contrast." in lines[0]
         and ": 1 failed check(s), page 3: " in lines[2]),
        ("a probe that passed is a warning, saying the modules' version isn't veraPDF's, "
         "and nothing else",
         lambda: not older["loaded"] and older["findings"] == [] and older["rules"] == []
         and len(older["warnings"]) == 1 and "1.30.2" in older["warnings"][0]
         and "silently" in older["warnings"][0]),
        ("a finding read back from a report is a note with its criterion, described",
         lambda: read_back.severity == "note"
         and read_back.standard == "WCAG 2.1 SC 1.4.10 (AA)"
         and "1.4.10 Reflow (AA, WCAG 2.1)" in findings_lib.describe("verapdf-wcag:1.4.10-1")),
        ("a report without the probe's job isn't taken for one whose modules loaded",
         lambda: not unprobed["loaded"] and unprobed["findings"] == []),
        ("nor one whose probe failed a WCAG rule on an object of veraPDF's own",
         lambda: not core["loaded"]),
        ("a module of another version than veraPDF's is a warning, as are a file veraPDF "
         "couldn't check, with its reason, and one it skipped",
         lambda: told["loaded"] and len(told["findings"]) == len(read["findings"])
         and len(told["warnings"]) == 3
         and told["warnings"][0].startswith("WARNING: --wcag: veraPDF 1.30.3 loaded "
                                             "wcag-validation 1.30.2 from")
         and told["warnings"][1] == ("WARNING: --wcag: veraPDF couldn't check broken.pdf: "
                                     "Couldn't parse stream")
         and told["warnings"][2].startswith("WARNING: --wcag: veraPDF didn't check "
                                            "skipped.pdf, and said nothing of it")),
        ("a report no veraPDF writes is read as far as it goes, never stopping the run",
         lambda: not [s for s in survived if isinstance(s, Exception)]),
        ("a test number that isn't a number, a count that isn't one, and a check that's "
         "nothing are read past, not taken for a report that can't be read",
         lambda: not [w for w in survived[5]["warnings"] if "couldn't be read" in w]
         and [f.check for f in survived[5]["findings"] if f.file == "book.pdf"]
         == ["verapdf-wcag:1.4.3-1a"]),
        ("a file whose name holds #page= keeps its findings' places",
         lambda: [f.where for f in survived[-1]["findings"] if "a#page" in f.file]
         == ["a#page=b.pdf"]),
    ]


def check_wcag_context():
    """What a PDF has where veraPDF's failed checks are, for --verbose: a
    link annotation's address, its description when that isn't the
    address, an address outside ASCII as UTF-8, one in UTF-16, and one
    kept in an object of its own; and the line of text a box of repeated
    characters is on, its words in order, a subscript and a superscript
    among them, under a transformation too, cut short past 120 characters;
    nothing for a page or an annotation the PDF hasn't, or a check of
    another kind; and a verbose report on the PDF with what it has there.
    On a PDF written here: questions ending in a blank, each blank in
    marked content of its own, as a tagged PDF's is, around which pypdf
    gives some runs no place; a blank drawn shorter to fit its line; and
    five links."""
    import pdfcheck
    import pypdf
    # Each run in a text object of its own, placed with Tm, and a blank in
    # marked content of its own, as LuaLaTeX writes a tagged page.
    stream = (b"/P <</MCID 0>> BDC BT /F1 12 Tf 1 0 0 1 72 720 Tm "
              b"(Core nations are also known as ) Tj ET EMC "
              b"/Span <</MCID 1>> BDC BT /F1 12 Tf 1 0 0 1 252.1 720 Tm (__________) Tj ET EMC "
              b"/P <</MCID 2>> BDC BT /F1 12 Tf 1 0 0 1 318.8 720 Tm (.) Tj ET EMC "
              b"BT /F1 12 Tf 1 0 0 1 72 706 Tm (The next line.) Tj ET "
              # A blank drawn shorter to fit its line, its underscores overlapping.
              b"BT /F1 12 Tf 1 0 0 1 72 650 Tm (Fitted: ) Tj ET "
              b"/Span <</MCID 3>> BDC BT /F1 12 Tf 1 0 0 1 120 650 Tm "
              b"[(_) 400 (_) 400 (_) 400 (_)] TJ ET EMC "
              # A subscript before a blank, lower than its line's baseline.
              # Each run up to the blank starts where the one before it ends,
              # by Helvetica's widths, as a typesetter sets a subscript: pypdf
              # 5.9 and 6 read a gap of half a space between runs as a space,
              # and from 6.4.1 pypdf knows those widths.
              b"BT /F1 12 Tf 1 0 0 1 72 600 Tm (The formula for water is H) Tj ET "
              b"BT /F1 8 Tf 1 0 0 1 210.04 597 Tm (2) Tj ET "
              b"BT /F1 12 Tf 1 0 0 1 214.49 600 Tm (O, and the gas we breathe out is ) Tj ET "
              b"/Span <</MCID 4>> BDC BT /F1 12 Tf 1 0 0 1 420 600 Tm (________) Tj ET EMC "
              b"BT /F1 12 Tf 1 0 0 1 473 600 Tm (.) Tj ET "
              # A question under a transformation, 20 points down, a list
              # item's label before it, as LuaLaTeX writes one.
              b"q 1 0 0 1 0 -20 cm "
              b"/Lbl <</MCID 8>> BDC BT /F1 12 Tf 1 0 0 1 50 560 Tm (1.) Tj ET EMC "
              b"/P <</MCID 5>> BDC BT /F1 12 Tf 1 0 0 1 72 560 Tm (Under a transform, ) Tj "
              b"ET EMC /Span <</MCID 6>> BDC BT /F1 12 Tf 1 0 0 1 200 560 Tm (________) Tj ET "
              b"EMC /P <</MCID 7>> BDC BT /F1 12 Tf 1 0 0 1 253 560 Tm (.) Tj ET EMC Q "
              # A superscript as high as a footnote's mark at 12 points, and a
              # subscript, before a blank, either nearer the box's foot or
              # top than the line's baseline, each run up to the blank where
              # the one before it ends.
              b"BT /F1 12 Tf 1 0 0 1 72 450 Tm (E = mc) Tj ET "
              b"BT /F1 8 Tf 1 0 0 1 109.68 454.3 Tm (2) Tj ET "
              b"BT /F1 12 Tf 1 0 0 1 114.13 450 Tm (, and water is H) Tj ET "
              b"BT /F1 8 Tf 1 0 0 1 197.5 447 Tm (2) Tj ET "
              b"BT /F1 12 Tf 1 0 0 1 201.95 450 Tm (O: ) Tj ET "
              b"/Span <</MCID 9>> BDC BT /F1 12 Tf 1 0 0 1 240 450 Tm (________) Tj ET EMC "
              # Two blanks a space apart, and a question shown with ', which
              # moves to the next line first.
              b"BT /F1 12 Tf 1 0 0 1 72 420 Tm (Name: ____ ____) Tj ET "
              b"BT /F1 12 Tf 1 0 0 1 72 400 Tm (A first line, of the question.) Tj ET "
              b"BT /F1 12 Tf 14 TL 1 0 0 1 72 386 Tm (Then the blank, ______.) ' ET "
              # A line too long to give whole.
              b"BT /F1 6 Tf 1 0 0 1 20 480 Tm (" + b"word " * 26 + b") Tj ET "
              b"BT /F1 6 Tf 1 0 0 1 420 480 Tm (__________) Tj ET")
    utf16 = "https://example.org/utf16".encode("utf-16-be").hex().upper().encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> "
        b"/Annots [6 0 R 7 0 R 8 0 R 9 0 R 10 0 R] >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Annot /Subtype /Link /Rect [72 690 200 702] /Contents "
        b"(https://example.org/fill) /A << /S /URI /URI (https://example.org/fill) >> >>",
        b"<< /Type /Annot /Subtype /Link /Rect [72 670 200 682] /Contents (The census page) "
        b"/A << /S /URI /URI (https://example.org/census) >> >>",
        b"<< /Type /Annot /Subtype /Link /Rect [72 650 200 662] "
        b"/A << /S /URI /URI (https://example.org/isn\\342\\200\\231t) >> >>",
        b"<< /Type /Annot /Subtype /Link /Rect [72 630 200 642] "
        b"/A << /S /URI /URI <FEFF" + utf16 + b"> >> >>",
        b"<< /Type /Annot /Subtype /Link /Rect [72 610 200 622] "
        b"/A << /S /URI /URI 11 0 R >> >>",
        b"(https://example.org/indirect)",
    ]
    data, offsets = b"%PDF-2.0\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(data))
        data += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    start = len(data)
    data += (b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
             + b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
             + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
             % (len(objects) + 1, start))
    path = os.path.join(scratch("wcag-context-"), "quiz.pdf")
    with open(path, "wb") as fh:
        fh.write(data)
    context = pdfcheck._WcagContext(path)

    def link(page, number):
        return context.about("SALinkAnnotation",
                             {"context": f"root/doc[0]/pages[{page}]/annots[{number}]"})

    def repeated(rect):
        return context.about("SARepeatedCharacters",
                             {"location": json.dumps({"bbox": [{"p": 0, "rect": rect}]})})
    long_line = context.line(0, [420, 478.6, 450, 485.6])

    # Where pypdf itself places the run shown with ': on the next line, 14
    # points down, or not.
    quoted = []
    pypdf.PdfReader(path).pages[0].extract_text(visitor_text=lambda text, cm, tm, font, size: (
        quoted.append(tm[5] * cm[3] + tm[4] * cm[1] + cm[5]) if "Then the blank" in text
        else None))
    quoted = quoted[0] if quoted else 0

    # A page pypdf reads partway, then stops on.
    class Half:
        def extract_text(self, visitor_operand_before=None, visitor_operand_after=None,
                         visitor_text=None):
            visitor_text("Half a line", [1, 0, 0, 1, 0, 0], [1, 0, 0, 1, 72, 300], None, 12)
            raise ValueError("a broken stream")
    half = pdfcheck._WcagContext(path)
    half.page = lambda index: Half()
    # veraPDF's report on the PDF, read verbose: the PDF's own words in it.
    report = {"report": {"jobs": [
        {"itemDetails": {"name": "/w/wcag-probe.pdf"}, "validationResult": [{"details": {
            "ruleSummaries": [{"specification": "WCAG2.2", "clause": "1.3.1",
                               "testNumber": 1, "object": "SARepeatedCharacters",
                               "failedChecks": 1, "checks": [{"status": "failed"}]}]}}]},
        {"itemDetails": {"name": path}, "validationResult": [{"details": {"ruleSummaries": [
            {"specification": "WCAG2.2", "clause": "2.4.9", "testNumber": 1,
             "object": "SALinkAnnotation", "description": "Links", "failedChecks": 1,
             "checks": [{"status": "failed", "errorMessage": "No description",
                         "context": "root/doc[0]/pages[0]/annots[0]"}]},
            {"specification": "WCAG2.2", "clause": "1.3.1", "testNumber": 1,
             "object": "SARepeatedCharacters", "description": "Repeated", "failedChecks": 1,
             "checks": [{"status": "failed", "errorMessage": "Text contains 10",
                         "location": '{"bbox":[{"p":0,"rect":[252.1,717.3,318.8,731.2]}]}'}]},
        ]}}]}]}}
    read = pdfcheck.wcag_report(report, "/w/wcag-probe.pdf", "f", verbose=True)
    lines = [line for _, group in sorted(read["rules"]) for line in group]
    return [
        ("a link's address, and its description when that isn't the address",
         lambda: [link(0, 0), link(0, 1)] == [
             "the link to https://example.org/fill",
             'the link to https://example.org/census, described as "The census page"']),
        ("an address outside ASCII read as UTF-8, as PDF 2.0 has it, one in UTF-16 as that, "
         "and one in an object of its own",
         lambda: [link(0, 2), link(0, 3), link(0, 4)] == [
             "the link to https://example.org/isn’t",
             "the link to https://example.org/utf16",
             "the link to https://example.org/indirect"]),
        ("the line a box of repeated characters is on, its words in order",
         lambda: repeated([252.1, 717.3, 318.8, 731.2])
         == 'on the line "Core nations are also known as __________."'),
        ("a blank drawn shorter to fit its line read as one run, not spaced",
         lambda: repeated([120, 647.3, 140, 661.2]) == 'on the line "Fitted: ____"'),
        ("the line, not a subscript on it, though the subscript is nearer the box's foot",
         lambda: repeated([420, 597.3, 473, 611.2])
         == 'on the line "The formula for water is H2O, and the gas we breathe out is '
            '________."'),
        ("and under a transformation, each run in its place, after a label too",
         lambda: repeated([200, 537.3, 253, 551.2]).replace("1.Under", "1. Under")
         == 'on the line "1. Under a transform, ________."'),
        ("a superscript and a subscript on the line, wherever the box's foot is",
         lambda: repeated([240, 447.3, 293, 461.2])
         == 'on the line "E = mc2, and water is H2O: ________"'),
        ("two blanks a space apart kept apart",
         lambda: repeated([109, 417.3, 133, 431.2]) == 'on the line "Name: ____ ____"'),
        ("a run shown with ' read where it moved to, on the next line, where pypdf places it "
         "there (5.9 moves it by its leading times the type's size)",
         lambda: repeated([180, 369.3, 220, 383.2])
         == ('on the line "Then the blank, ______."' if abs(quoted - 372) < 1 else "")),
        ("a line past 120 characters cut short",
         lambda: len(long_line) > 120 and long_line.endswith("__________")
         and repeated([420, 478.6, 450, 485.6]) == f'on the line "{long_line[:117]}…"'),
        ("nothing for a page or an annotation the PDF hasn't, or a check of another kind",
         lambda: [link(0, 9), link(3, 0), link(-1, 0),
                  context.about("SATextChunk", {"context": "root/doc[0]/pages[0]/annots[0]"}),
                  context.about("SARepeatedCharacters", {"location": "nonsense"})]
         == ["", "", "", "", ""]),
        ("nor for a page read partway, then or after",
         lambda: [half.about("SARepeatedCharacters",
                             {"location": '{"bbox":[{"p":0,"rect":[72,297.3,100,311.2]}]}'})
                  for _ in range(2)] == ["", ""]),
        ("nor for a PDF that isn't there, which isn't tried again",
         lambda: (lambda missing: [missing.about(
             "SALinkAnnotation", {"context": "root/doc[0]/pages[0]/annots[0]"})
             for _ in range(2)] == ["", ""] and missing.reader is False)(
             pdfcheck._WcagContext("/no/such.pdf"))),
        ("a verbose report on the PDF says what it has where each check failed",
         lambda: sorted(f.detail.split(". 1.3.1")[0].split(". 2.4.9")[0]
                        for f in read["findings"]) == [
             "Links: No description (the link to https://example.org/fill)",
             'Repeated: Text contains 10 (on the line "Core nations are also known as '
             '__________.")']
         and f"  quiz.pdf#page=1: No description (the link to https://example.org/fill)"
         in lines),
    ]


def check_output_check_flags():
    """What convert.py gives the output check: --quick when asked, and
    --wcag and --verbose only when the run made a PDF, --verbose only with
    --wcag."""
    import argparse
    convert = load(os.path.join(ROOT, "bin", "convert.py"), "convert_flags")

    def flags(pdfs, **given):
        args = argparse.Namespace(**dict({"quick": False, "wcag": False, "verbose": False},
                                         **given))
        return convert.output_check_flags(args, pdfs)
    return [
        ("--wcag and --verbose passed on with a PDF to check",
         lambda: flags(["b.pdf"], wcag=True, verbose=True) == ["--wcag", "--verbose"]
         and flags(["b.pdf"], quick=True, wcag=True) == ["--quick", "--wcag"]),
        ("and neither without one, nor --verbose without --wcag",
         lambda: flags([], wcag=True, verbose=True) == []
         and flags(["b.pdf"], verbose=True) == []
         and flags([], quick=True) == ["--quick"]),
    ]


def check_wcag_probe():
    """The probe is a PDF, its cross-reference table right, of one page
    whose one tagged paragraph is ten underscores; a PDF 2.0 header gets
    that version's profile; and no folder of modules, or one without
    their jars, is a warning before veraPDF is run."""
    import pdfcheck
    data = pdfcheck.wcag_probe()
    work = scratch("wcag-probe-")
    path, newer = os.path.join(work, "probe.pdf"), os.path.join(work, "newer.pdf")
    with open(path, "wb") as fh:
        fh.write(data)
    with open(newer, "wb") as fh:
        fh.write(data.replace(b"%PDF-1.7", b"%PDF-2.0", 1))
    start = int(re.search(rb"startxref\n(\d+)", data).group(1))
    offsets = [int(o) for o in re.findall(rb"^(\d{10}) 00000 n ", data, re.M)]
    nowhere = [os.path.join(work, "no-such-verapdf")]
    unset = pdfcheck.run_verapdf_wcag(nowhere, [path], folder="")
    empty = pdfcheck.run_verapdf_wcag(nowhere, [path], folder=work)
    text = None
    if pdfcheck.pypdf is not None:
        reader = pdfcheck.pypdf.PdfReader(path)
        text = (len(reader.pages), reader.pages[0].extract_text().strip())
    return [
        ("its cross-reference table points at each of its nine objects",
         lambda: data[start:start + 4] == b"xref" and len(offsets) == 9
         and all(data[o:].startswith(b"%d 0 obj" % n) for n, o in enumerate(offsets, 1))),
        ("pypdf reads one page of ten underscores",
         lambda: text == (1, "__________") if text is not None
         else print("  skip  no pypdf to read the probe") or True),
        ("a header saying PDF 2.0 gets that profile, any other the 1.x one",
         lambda: pdfcheck.pdf_major(newer) == "2" and pdfcheck.pdf_major(path) == "1"),
        ("no folder is a warning naming VERAPDF_WCAG, veraPDF not run",
         lambda: unset[0] == [] and len(unset[1]) == 1
         and "aren't installed (VERAPDF_WCAG names no folder" in unset[1][0]),
        ("a folder without the modules' jars, a warning naming them",
         lambda: empty[0] == [] and len(empty[1]) == 1
         and "has no wcag-validation or wcag-algorithms jar" in empty[1][0]),
    ]


def check_wcag_setup():
    """The folder of veraPDF's WCAG modules read as Java would load it,
    two versions of a module a warning; the setup check saying which
    PDFs the checks run on, and naming a missing profile, or one that
    isn't XML; a warning's list of files; and the output check's
    summary, where veraPDF's WCAG notes follow the verdict and stay out
    of its count, and keep the report. With the suites' stand-in for
    veraPDF."""
    sys.path.insert(0, HERE)
    import fakeverapdf
    import pdfcheck
    check_output = load(os.path.join(ROOT, "bin", "check-output.py"), "check_output_wcag")
    work = scratch("wcag-setup-")
    fake = [fakeverapdf.install(os.path.join(work, "fake"))]
    twice = fakeverapdf.modules(os.path.join(work, "twice"))
    for name in ("wcag-algorithms-1.30.2.jar", "wcag-validation-1.30.3-sources.jar",
                 "wcag-validationX.jar"):
        open(os.path.join(twice, name), "w").close()
    one = fakeverapdf.modules(os.path.join(work, "one"),
                              profiles=("WCAG-2-2-Machine-PDF20.xml",))
    other = fakeverapdf.modules(os.path.join(work, "other"), profiles=("WCAG-2-2-Machine.xml",))
    neither = fakeverapdf.modules(os.path.join(work, "neither"), profiles=())
    unloaded_one = fakeverapdf.modules(os.path.join(work, "unloaded-one"), loads=False,
                                       profiles=("WCAG-2-2-Machine-PDF20.xml",))
    # Profiles that can't be read: XML cut short, and XML in an encoding
    # Python doesn't know and in one expat can't read.
    unreadable = {}
    for name, text in (("cut short", "<profile>"),
                       ("UTF-8x", '<?xml version="1.0" encoding="UTF-8x"?><profile/>'),
                       ("Shift_JIS", '<?xml version="1.0" encoding="Shift_JIS"?><profile/>')):
        folder = fakeverapdf.modules(os.path.join(work, "unreadable", name))
        with open(os.path.join(folder, "WCAG-2-2-Machine.xml"), "w") as fh:
            fh.write(text)
        unreadable[folder] = pdfcheck.run_verapdf_wcag(fake, [], folder=folder)
    doubled = pdfcheck.run_verapdf_wcag(fake, [], folder=twice)
    lacking = pdfcheck.run_verapdf_wcag(fake, [], folder=one)
    lacking_other = pdfcheck.run_verapdf_wcag(fake, [], folder=other)
    complete = pdfcheck.run_verapdf_wcag(fake, [], folder=twice)
    lacking_both = pdfcheck.run_verapdf_wcag(fake, [], folder=neither)
    lacking_unloaded = pdfcheck.run_verapdf_wcag(fake, [], folder=unloaded_one)
    # A rule's summary line: without pages, listed whole and cut short, and
    # with one of many failed checks listed, as veraPDF does past its cap.
    def rule(failed, checks, clause="4.1.2", test=17, description="Redundant span"):
        return {"clause": clause, "testNumber": test, "failedChecks": failed,
                "description": description, "checks": checks}
    pageless = {"status": "failed", "context": "root/doc[0]/redundant[0]"}
    paged = {"status": "failed", "context": "root/doc[0]/repeatedCharacters[0]",
             "location": '{"bbox":[{"p":0,"rect":[1,2,3,4]}]}'}
    span_url = "https://www.w3.org/WAI/WCAG22/Understanding/name-role-value.html"
    rule_lines = [pdfcheck.wcag_rule_line("book.pdf", rule(1, [pageless]), []),
                  pdfcheck.wcag_rule_line("book.pdf", rule(5, [pageless, pageless]), []),
                  pdfcheck.wcag_rule_line("book.pdf", rule(11000, [paged], "1.3.1", 1,
                                                           "Repeated"), [1])]
    os.environ["FAKE_VERAPDF_SLEEP"] = "5"
    try:
        slow = pdfcheck.run_verapdf_wcag(fake, [], folder=twice, timeout=1)
    finally:
        del os.environ["FAKE_VERAPDF_SLEEP"]
    lines = check_output.summary("0 page(s) and 1 PDF(s)", [], [], [], [],
                                 ["veraPDF 1.30.3's WCAG 2.2 machine checks ran on 1 PDF(s)",
                                  "book.pdf: verapdf-wcag:1.3.1-1, 1.3.1 Info and "
                                  "Relationships (A): 1 failed check(s), page 653"],
                                 "output-check.csv")
    return [
        ("a module's jars by their names, a sources jar or another name not one",
         lambda: pdfcheck.wcag_modules(twice) == {"wcag-validation": ["1.30.3"],
                                                  "wcag-algorithms": ["1.30.2", "1.30.3"]}),
        ("two versions of a module are a warning, since Java loads one, saying not which",
         lambda: any("has wcag-algorithms 1.30.2 and 1.30.3" in line for line in doubled[1])),
        ("veraPDF stopped after the time it's given is a warning saying so",
         lambda: any("veraPDF hadn't finished with WCAG-2-2-Machine-PDF20.xml after 1 "
                     "seconds, and was stopped." in line for line in slow[1])),
        ("the setup check says the checks run on PDF 2.0 and PDF 1.x files, with both "
         "profiles", lambda: complete[1][0].startswith("veraPDF 1.30.3 loaded its WCAG modules")
         and "so its WCAG 2.2 machine checks run on PDF 2.0 and PDF 1.x files alike; "
             in complete[1][0]),
        ("with one, which files they run on and which they don't, and the warning names the "
         "profile missing and the files it's for",
         lambda: "so its WCAG 2.2 machine checks run on a PDF 2.0 file, as a PDF/UA-2 build "
                 "is, but not on a PDF 1.x file; " in lacking[1][0]
         and lacking[1][1] == f"WARNING: --wcag: {one} (VERAPDF_WCAG) has no "
                              "WCAG-2-2-Machine.xml, so the WCAG checks won't run on a PDF 1.x "
                              "file, as a PDF/UA-1 build is (docs/installation.md, Optional: "
                              "veraPDF's WCAG modules)."
         and "so its WCAG 2.2 machine checks run on a PDF 1.x file, as a PDF/UA-1 build "
             "is, but not on a PDF 2.0 file; " in lacking_other[1][0]
         and any("has no WCAG-2-2-Machine-PDF20.xml, so the WCAG checks won't run on a PDF "
                 "2.0 file, as a PDF/UA-2 build is" in line for line in lacking_other[1])),
        ("with neither, a warning for each and no veraPDF run",
         lambda: lacking_both[0] == [] and lacking_both[1] == [
             f"WARNING: --wcag: {neither} (VERAPDF_WCAG) has no WCAG-2-2-Machine-PDF20.xml, so "
             "the WCAG checks won't run on a PDF 2.0 file, as a PDF/UA-2 build is "
             "(docs/installation.md, Optional: veraPDF's WCAG modules).",
             f"WARNING: --wcag: {neither} (VERAPDF_WCAG) has no WCAG-2-2-Machine.xml, so the "
             "WCAG checks won't run on a PDF 1.x file, as a PDF/UA-1 build is "
             "(docs/installation.md, Optional: veraPDF's WCAG modules)."]),
        ("with one, and modules that don't load, the warning that they didn't comes first",
         lambda: len(lacking_unloaded[1]) == 2
         and "didn't load its WCAG modules" in lacking_unloaded[1][0]
         and "has no WCAG-2-2-Machine.xml, so the WCAG checks won't run on a PDF 1.x file"
             in lacking_unloaded[1][1]),
        ("a rule's line without pages, listed whole or cut short, and with one of many "
         "listed", lambda: rule_lines == [
             "book.pdf: verapdf-wcag:4.1.2-17, 4.1.2 Name, Role, Value (A): 1 failed check(s): "
             f"Redundant span. {span_url}",
             "book.pdf: verapdf-wcag:4.1.2-17, 4.1.2 Name, Role, Value (A): 5 failed check(s): "
             f"Redundant span. {span_url}",
             "book.pdf: verapdf-wcag:1.3.1-1, 1.3.1 Info and Relationships (A): 11000 failed "
             "check(s), the first on page 1: Repeated. "
             "https://www.w3.org/WAI/WCAG22/Understanding/info-and-relationships.html"]),
        ("a warning's list of files: three at most, then how many more",
         lambda: [pdfcheck._listed(["/a/one.pdf", "b/two.pdf", "three.pdf", "4.pdf", "5.pdf"]
                                   [:count]) for count in (1, 2, 3, 4, 5)]
         == ["one.pdf", "one.pdf and two.pdf", "one.pdf, two.pdf, and three.pdf",
             "one.pdf, two.pdf, three.pdf, and 1 more",
             "one.pdf, two.pdf, three.pdf, and 2 more"]),
        ("and one that can't be read as one, cut short or in an encoding that can't be read, "
         "the other run",
         lambda: all(lines[0].startswith("veraPDF 1.30.3 loaded its WCAG modules")
                     and any("WCAG-2-2-Machine.xml in " + folder + " (VERAPDF_WCAG) can't be "
                             "read as a profile" in line for line in lines)
                     for folder, (_, lines) in unreadable.items())),
        ("veraPDF's WCAG notes alone: nothing found, their lines after it, the report kept",
         lambda: lines == [
             "Output check: 0 page(s) and 1 PDF(s), nothing found.",
             "  veraPDF 1.30.3's WCAG 2.2 machine checks ran on 1 PDF(s)",
             "  book.pdf: verapdf-wcag:1.3.1-1, 1.3.1 Info and Relationships (A): 1 failed "
             "check(s), page 653",
             "Written to output-check.csv."]),
    ]


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def word_file(path, runs, defaults=None, styles="", custom=None, core=None):
    """A Word file of one paragraph per run, for its language to be read:
    runs, [(text, its paragraph's style or None, its run properties)];
    defaults, the docDefaults' w:lang attributes; styles, more w:style
    elements; custom, {name: value} custom properties; core, dc:language."""
    import zipfile
    lang = "".join(' w:%s="%s"' % item for item in (defaults or {}).items())
    styles_xml = ('<w:styles xmlns:w="%s"><w:docDefaults><w:rPrDefault><w:rPr>%s</w:rPr>'
                  '</w:rPrDefault></w:docDefaults>'
                  '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"/>%s'
                  '</w:styles>' % (W_NS, "<w:lang%s/>" % lang if lang else "", styles))
    body = "".join('<w:p>%s<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r></w:p>' % (
        '<w:pPr><w:pStyle w:val="%s"/></w:pPr>' % style if style else "",
        "<w:rPr>%s</w:rPr>" % rpr if rpr else "", text) for text, style, rpr in runs)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/styles.xml", styles_xml)
        z.writestr("word/document.xml", '<w:document xmlns:w="%s"><w:body>%s</w:body>'
                   '</w:document>' % (W_NS, body))
        if custom:
            z.writestr("docProps/custom.xml", (
                '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
                'custom-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/'
                '2006/docPropsVTypes">' + "".join(
                    '<property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="%d" '
                    'name="%s"><vt:lpwstr>%s</vt:lpwstr></property>' % (i, k, v)
                    for i, (k, v) in enumerate(custom.items(), 2)) + "</Properties>"))
        if core:
            z.writestr("docProps/core.xml", (
                '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/'
                'metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">'
                '<dc:language>%s</dc:language></cp:coreProperties>' % core))
    return path


def check_title_page_languages():
    """A one-page book's title page, by its top-level headings, where its
    page is in another language than the book's: the PDF puts the page in
    a div of its language (build-pdf.py's in_language), and its headings
    are the book's still."""
    from bookassembly import wants_title_page

    class Book:
        title_preceded = False

    def heading(text):
        return {"t": "Header", "c": [1, [text, [], []], [{"t": "Str", "c": text}]]}
    spoken, plain = Book(), Book()
    spoken.blocks = [{"t": "Div", "c": [["", [], [["lang", "fr"]]],
                                        [heading("a"), heading("b")]]}]
    plain.blocks = [{"t": "Div", "c": [["box", ["note"], []], [heading("a"), heading("b")]]}]
    tree = [("page", "one", None)]
    return [
        ("a page in a div of its language has its headings at the top level still",
         lambda: wants_title_page("auto", tree, spoken)),
        ("and a div of any other kind holds its headings",
         lambda: not wants_title_page("auto", tree, plain)),
    ]


def check_page_languages():
    """A page's language (lib/languages.py): a tag as a page carries it,
    the region rule, a Word file's own and a deck's, a producer's
    property, the sidecar, what's decided, and what a copy and a Markdown
    or AsciiDoc target are given.

    Pandoc's Word reader reads no language at all, so a Word file's is
    read here, as Word resolves each letter's: OpenStax's Spanish Word
    files are English to Word throughout, their reference document's
    default, with es in a custom property Pandoc's writer doesn't read."""
    import collections
    import languages
    work = scratch("languages-")
    spanish = word_file(os.path.join(work, "spanish.docx"), [
        ("Texto en español, bastante largo.", None, ""),
        ("One English line.", None, '<w:lang w:val="en-US"/>')],
        defaults={"val": "es-ES_tradnl", "eastAsia": "zh-CN", "bidi": "ar-SA"})
    quoted = word_file(os.path.join(work, "quoted.docx"), [
        ("Une longue citation en français, toute entière.", "Quote", ""),
        ("Short.", None, "")], defaults={"val": "en-US"},
        styles='<w:style w:type="paragraph" w:styleId="Quote"><w:basedOn w:val="Base"/>'
               '</w:style><w:style w:type="paragraph" w:styleId="Base"><w:rPr>'
               '<w:lang w:val="fr-FR"/></w:rPr></w:style>')
    styled = word_file(os.path.join(work, "styled.docx"), [
        ("Ein ganzer Satz auf Deutsch, lang genug.", None, '<w:rStyle w:val="Foreign"/>'),
        ("Short.", None, "")], defaults={"val": "en-US"},
        styles='<w:style w:type="character" w:styleId="Foreign"><w:rPr>'
               '<w:lang w:val="de-DE"/></w:rPr></w:style>')
    japanese = word_file(os.path.join(work, "japanese.docx"), [
        ("日本語の文章がここにあります", None, ""), ("A few words", None, "")],
        defaults={"val": "en-US", "eastAsia": "ja-JP"})
    arabic = word_file(os.path.join(work, "arabic.docx"), [
        ("نص عربي طويل هنا", None, '<w:lang w:bidi="ar-EG"/>'),
        ("Latin", None, "")], defaults={"val": "en-US", "bidi": "ar-SA"})
    # A run marked complex script is in the complex-script language, its
    # letters whatever they are (ECMA-376, 17.3.2.7, cs).
    flagged = word_file(os.path.join(work, "flagged.docx"), [
        ("Letters Word sets as complex script", None, '<w:cs/><w:lang w:bidi="he-IL"/>'),
        ("Latin", None, "")], defaults={"val": "en-US", "bidi": "ar-SA"})
    openstax = word_file(os.path.join(work, "openstax.docx"), [
        ("Funciones y notación de funciones", None, "")],
        defaults={"val": "en-US", "eastAsia": "en-US", "bidi": "ar-SA"},
        custom={"company": "OpenStax", "language": "es"})
    other = word_file(os.path.join(work, "other.docx"), [("Funciones", None, "")],
                      defaults={"val": "en-US"}, custom={"company": "Acme", "language": "es"})
    cored = word_file(os.path.join(work, "cored.docx"), [("Texte", None, "")], core="fr")
    bare = word_file(os.path.join(work, "bare.docx"), [("Text", None, "")])
    owns = {name: languages.docx_own(path) for name, path in (
        ("spanish", spanish), ("quoted", quoted), ("styled", styled), ("japanese", japanese),
        ("arabic", arabic), ("flagged", flagged), ("openstax", openstax), ("other", other),
        ("cored", cored),
        ("bare", bare))}

    class Deck:
        """What languages.deck_own reads of a pptxparse.Deck."""
        def __init__(self, runs=(), default=None, masters=()):
            self.languages = collections.Counter(dict(runs))
            self.default_language = default
            self.master_languages = collections.Counter(dict(masters))

    decks = [languages.deck_own(Deck({"en-US": 5, "zxx": 9}), {}, "a.pptx"),
             languages.deck_own(Deck((), "fr-FR"), {}, "b.pptx"),
             languages.deck_own(Deck((), None, {"de-DE": 3}), {}, "c.pptx"),
             languages.deck_own(Deck({"en-US": 5}), {"company": "openstax", "language": "es"},
                                "d.pptx"),
             languages.deck_own(Deck(), {}, "e.pptx")]
    Own = languages.Own
    word_es = Own("es-ES", "file", "s.docx: most of its text", "es-ES")
    producer = Own("es", "producer", "o.docx: its custom property language", "en-US")
    decide = languages.decide
    sidecar = os.path.join(work, "languages.csv")
    with open(sidecar, "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows([
            languages.SIDECAR_COLUMNS, ["chapter-1", "es-mx", "", "TI", ""],
            ["Week 1.pptx", "fr"], ["intro.docx", "de"], ["Chapter 2.md", "pt-BR"],
            ["notes", "French"], ["blank", ""], ["gone", "it"]])
    rows, problems = languages.read_rows(sidecar)
    matched, unmatched = languages.match_rows(rows, {"chapter-1": [], "Week-1": ["Week 1"],
                                                     "intro": [], "Chapter-2": [], "notes": [],
                                                     "blank": []})
    appended = os.path.join(work, "languages-appended.csv")
    with open(appended, "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows([["intro", "fr"], ["intro.docx", "de"], ["intro", "es"],
                                  ["Week 1", "it"], ["Week-1", "pt"]])
    later, _ = languages.match_rows(languages.read_rows(appended)[0],
                                    {"Week-1": ["Week 1"], "intro": []})
    convert = load(os.path.join(ROOT, "bin", "convert.py"), "convert_languages")
    with open(os.path.join(ROOT, "bin", "target-blocks.lua"), encoding="utf-8") as fh:
        target_lua = fh.read()
    with open(os.path.join(ROOT, "bin", "markdown-source.lua"), encoding="utf-8") as fh:
        source_lua = fh.read()
    accepted = ["en", "en-US", "es-419", "zh-Hant-TW", "sr-Latn-RS", "de-CH-1996",
                "en-US-x-twain", "yue", "zh-yue-HK"]
    return [
        ("a tag is in BCP 47's usual case, Word's sort suffix gone and an underscore a hyphen; "
         "a word, a code for no language, and a blank are none",
         lambda: [languages.tag(v) for v in ("en-us", "es-ES_tradnl", "en_US", "zh-hant-tw",
                                             "SR-LATN-rs", "English", "x-none", "zxx", "und",
                                             "", None)]
         == ["en-US", "es-ES", "en-US", "zh-Hant-TW", "sr-Latn-RS"] + [None] * 6),
        ("every tag a page's language takes, the configuration takes",
         lambda: all(languages.tag(v) and oerconfig.LANGUAGE_RE.match(languages.tag(v))
                     for v in accepted)),
        ("two tags are one language whatever their regions, but not in two scripts",
         lambda: [languages.same_language(a, b) for a, b in (
             ("en-GB", "en-US"), ("es", "es-MX"), ("sr-Latn", "sr-Cyrl"), ("zh", "zh-Hant"),
             ("en", "fr"), ("English", "English"))]
         == [True, True, False, False, False, False]),
        ("a Word file's own is the language most of its letters are in, the default's where "
         "no run says another, its sort suffix gone",
         lambda: owns["spanish"] == Own("es-ES", "file", "spanish.docx: its default, which "
                                        "most of its text has", "es-ES")),
        ("a paragraph style's language, by the style it's based on, and a character style's",
         lambda: owns["quoted"][:2] == ("fr-FR", "file")
         and owns["quoted"].found == "quoted.docx: most of its text"
         and owns["styled"][:2] == ("de-DE", "file")),
        ("Japanese letters take the East Asian language, and Arabic letters, and a run "
         "marked complex script, the complex-script language",
         lambda: owns["japanese"].language == "ja-JP" and owns["arabic"].language == "ar-EG"
         and owns["flagged"].language == "he-IL"),
        ("OpenStax's language property is the file's, its marks the reference document's "
         "US English; another company's isn't trusted",
         lambda: owns["openstax"][:2] == ("es", "producer")
         and owns["openstax"].marks == "en-US" and "OpenStax" in owns["openstax"].found
         and owns["other"][:2] == ("en-US", "file")),
        ("with no language on any letter, the core properties' language; with none at all, "
         "none",
         lambda: owns["cored"][:3] == ("fr", "file", "cored.docx: its core properties' "
                                                     "language")
         and owns["bare"] is None),
        ("a deck's own is the language most of its runs say, a code for none aside, else its "
         "default's, else its masters'; and a trusted producer's property",
         lambda: [(d.language, d.source, d.found.split(": ", 1)[1]) if d else None
                  for d in decks[:4]]
         == [("en-US", "file", "most of its text"), ("fr-FR", "file", "its default"),
             ("de-DE", "file", "its masters' text styles"),
             ("es", "producer", "its custom property language, which openstax's files carry")]
         and decks[3].marks == "en-US" and decks[4] is None),
        ("an HTML page's language is its body's, else its root's, as Pandoc's reader reads it",
         lambda: [languages.html_language(t) for t in (
             '<html lang="en"><body lang="es">', '<html xml:lang="fr"><body>',
             "<html><body>")] == ["es", "fr", None]),
        ("a row decides; else the file's own; else the project's",
         lambda: decide("fr", word_es, "de") == ("fr", "sidecar", word_es)
         and decide(None, word_es, "de") == ("es-ES", "file", word_es)
         and decide(None, None, "de") == ("de", "project", None)),
        ("a file's own that differs from the project's language only in region doesn't "
         "override it, declared or the default",
         lambda: decide(None, word_es, "es-MX")[:2] == ("es-MX", "project")
         and decide(None, Own("en-US", "file", "", "en-US"), "en")[:2]
         == ("en", "project")),
        ("a page is in another language than the book's when its language is another, not "
         "its region",
         lambda: languages.other_than(decide(None, word_es, "de"), "de")
         and not languages.other_than(decide(None, word_es, "es-MX"), "es-MX")),
        ("a Markdown or AsciiDoc target keeps its reader's language where it's the page's but "
         "for its region, and says none where the page is the project's and the reader gave "
         "none; a row is written as it is",
         lambda: [languages.for_source_targets(d, r) for d, r in (
             (decide(None, Own("en-GB", "file", "", "en-GB"), "en-US"), "en-GB"),
             (decide(None, None, "de"), None),
             (decide("fr-CA", Own("fr", "file", "", "fr"), "de"), "fr"),
             (decide(None, producer, "en"), "en-US"))]
         == ["en-GB", None, "fr-CA", "es"]),
        ("the sidecar's rows by page, a deck's own name, or a file's name, made safe as a "
         "page's is, a row whose language is no tag said and set aside, a blank one passed "
         "over",
         lambda: rows == {"chapter-1": "es-MX", "Week 1.pptx": "fr", "intro.docx": "de",
                          "Chapter 2.md": "pt-BR", "gone": "it"}
         and len(problems) == 1 and "'French'" in problems[0]
         and matched == {"chapter-1": "es-MX", "Week-1": "fr", "intro": "de",
                         "Chapter-2": "pt-BR"}
         and unmatched == ["gone"]),
        ("of two rows for one page, however each names it, the later one is used",
         lambda: later == {"intro": "es", "Week-1": "pt"}),
        ("a drafted row is the sidecar's own columns, marked TI",
         lambda: languages.report_row("ch", decide(None, word_es, "de"))
         == ["ch", "es-ES", "s.docx: most of its text", "TI", ""]
         and len(languages.SIDECAR_COLUMNS) == 5),
        ("the sidecar's value and review columns are where convert.py reads them",
         lambda: convert.REVIEW_COLUMNS["languages"] == languages.REVIEW
         and [languages.SIDECAR_COLUMNS[i] for i in (1, 3, 4)]
         == ["language", "drafted-by", "reviewed"]
         and "source" in convert.HEADER_WORDS),
        ("the key a page's language rides in is one key in convert.py and the filters",
         lambda: "local LANGUAGE_KEY = '%s'" % convert.LANGUAGE_KEY in target_lua
         and "'%s'" % convert.LANGUAGE_KEY in re.search(
             r"PIPELINE_META = \{(.*?)\}", source_lua, re.S).group(1)),
    ]


def check_copy_languages():
    """What a source's copy is given of its page's language
    (languages.for_copy), and how a Word, deck, HTML, and Markdown copy
    say it: a row's in place of the file's own marks, a producer's or the
    project's in place of marks in another language, not another region,
    and otherwise the page's only where the file has none."""
    import languages
    import docxremediate
    import htmlremediate
    import mdremediate
    import pptxremediate
    Own, decide = languages.Own, languages.decide
    word_es = Own("es-ES", "file", "s.docx: most of its text", "es-ES")
    producer = Own("es", "producer", "o.docx: its custom property language", "en-US")
    styles = ('<w:docDefaults><w:rPrDefault><w:rPr><w:lang w:val="en-US" w:eastAsia="en-US" '
              'w:bidi="ar-SA" /></w:rPr></w:rPrDefault></w:docDefaults>'
              '<w:style><w:rPr><w:lang w:val="en-US"/></w:rPr></w:style>'
              '<w:style><w:rPr><w:lang w:val="de-DE"/></w:rPr></w:style>')
    replaced, n = docxremediate.replace_language_marks(styles, "en-US", "es")
    defaulted, m = docxremediate.set_default_language(replaced, "es")
    asian, _ = docxremediate.set_default_language(styles, "ja")
    slides = ('<a:p><a:r><a:rPr lang="en-US" b="1"/><a:t>A</a:t></a:r><a:r><a:rPr lang="de-DE"/>'
              '<a:t>B</a:t></a:r><a:endParaRPr lang="en-US"/></a:p>')
    deck_text, k = pptxremediate.replace_language_marks(slides, "en-US", "es")
    presentation = ('<p:presentation><p:notesSz cx="1" cy="1"/><p:defaultTextStyle><a:defPPr>'
                    '<a:defRPr lang="en-US"/></a:defPPr><a:lvl1pPr><a:defRPr lang="en-US"/>'
                    '</a:lvl1pPr><a:lvl2pPr><a:defRPr/></a:lvl2pPr></p:defaultTextStyle>'
                    '</p:presentation>')
    kept, _ = pptxremediate.set_default_language(presentation, "es")
    forced, _ = pptxremediate.set_default_language(presentation, "es", replace=True)
    html_pages = [htmlremediate.replace_language_of(page, "es") for page in (
        '<html lang="en-US" xml:lang="en-US"><body lang="en-US"><p>Hola</p></body></html>',
        '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en"><body><p>Hola</p></body>',
        "<html><body><p>Hola</p></body></html>",
        '<html lang="es"><body><p>Hola</p></body></html>')]
    md_files = [mdremediate.replace_language(text, "es") for text in (
        "---\ntitle: Hola\nlang: en-US\n---\n\nHola\n", "Hola\n", "---\nlang: es\n---\n\nHola\n")]
    return [
        ("a copy is given a row's language in place of its marks', a producer's or the "
         "project's in place of marks in another language, not another region, and "
         "otherwise a language only where it has none, the project's only when it declares "
         "one",
         lambda: [languages.for_copy(d, declared) for d, declared in (
             (decide("fr", word_es, "de"), True),
             (decide("es-ES", word_es, "de"), True),
             (decide("fr", None, "de"), True),
             (decide(None, producer, "en"), False),
             (decide(None, Own("es", "producer", "", "es-ES"), "en"), False),
             (decide(None, producer, "es-MX"), True),
             (decide(None, word_es, "de"), True),
             (decide(None, None, "de"), True),
             (decide(None, None, "en"), False))]
         == [("fr", "es-ES"), ("es-ES", None), ("fr", ""), ("es", "en-US"), ("es", None),
             ("es-MX", "en-US"), ("es-ES", None), ("de", None), (None, None)]),
        ("a Word copy's language goes where Pandoc's writer writes it: East Asian for "
         "Chinese, Japanese, and Korean, complex script for Hebrew and Arabic",
         lambda: [docxremediate.language_slot(v) for v in ("ja", "zh-Hant", "ko-KR", "he",
                                                           "ar-EG", "es", "en-US")]
         == ["eastAsia"] * 3 + ["bidi"] * 2 + ["val"] * 2),
        ("a Word copy's marks of its own language say the new one, a passage's other kept, "
         "and its default says it, the rest of the element as it was",
         lambda: n == 2 and m == 0
         and '<w:lang w:val="es" w:eastAsia="en-US" w:bidi="ar-SA" />' in defaulted
         and '<w:lang w:val="de-DE"/>' in defaulted
         and '<w:lang w:val="en-US" w:eastAsia="ja" w:bidi="ar-SA" />' in asian),
        ("a deck copy's runs of its own language say the new one, a passage's other kept, "
         "and with replace every default says it",
         lambda: k == 2 and 'lang="de-DE"' in deck_text and deck_text.count('lang="es"') == 2
         and kept.count('lang="es"') == 1 and kept.count('lang="en-US"') == 2
         and forced.count('lang="es"') == 3 and 'lang="en-US"' not in forced),
        ("an HTML copy's lang and xml:lang say the new one, on <html> and on a <body> that "
         "says one, and <html> gets a lang where it has none, beside an xml:lang too",
         lambda: html_pages[0] == ('<html lang="es" xml:lang="es"><body lang="es"><p>Hola</p>'
                                   '</body></html>', 1)
         and html_pages[1] == ('<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="es" '
                               'lang="es"><body><p>Hola</p></body>', 1)
         and html_pages[2] == ('<html lang="es"><body><p>Hola</p></body></html>', 1)
         and html_pages[3][1] == 0),
        ("a Markdown copy's front matter says the new one, or gets it where it has none",
         lambda: md_files[0] == ("---\ntitle: Hola\nlang: es\n---\n\nHola\n", 1)
         and md_files[1] == ("---\nlang: es\n---\n\nHola\n", 1) and md_files[2][1] == 0),
    ]


GROUPS = [
    ("a report's rows", check_report_rows),
    ("alt text's rules, and their findings", check_alt_text_rules),
    ("a PDF read without pypdf's warnings", check_pdf_read_quietly),
    ("the PDF findings in the output check's summary", check_pdf_summary),
    ("WCAG 2.2's criteria, as W3C has them", check_wcag_criteria),
    ("veraPDF's WCAG profile's report, read as findings", check_wcag_report),
    ("what a PDF has where its WCAG checks failed, for --verbose", check_wcag_context),
    ("the output check's flags from convert.py", check_output_check_flags),
    ("the WCAG probe, and the setup checked before veraPDF runs", check_wcag_probe),
    ("the WCAG modules' folder, and the summary their notes go in", check_wcag_setup),
    ("tlmgr, with sudo where it needs it", check_tlmgr_command),
    ("a PDF's lines too wide, and its fitted blanks", check_fitted_blanks),
    ("a PDF's blocks of code fitted, and still too wide", check_code_fit_report),
    ("the installation page's TeX packages", check_tex_packages),
    ("drawings without the preview package", check_drawings_without_preview),
    ("layout tables", check_layout_tables),
    ("a group's own header rows", check_group_heads),
    ("unique ids", check_unique_ids),
    ("front and back matter by name", check_matter_by_name),
    ("types by title", check_types_by_title),
    ("the project's sample", check_project_sample),
    ("caption contrast", check_contrast),
    ("manifest names", check_manifest_names),
    ("repairing a .docx on the way in", check_docx_repair),
    ("a list item's later paragraphs, indented as Pandoc 3.13 writes them",
     check_list_continuations),
    ("normal text in a Word equation", check_word_equation_text),
    ("a bar in a Word equation and in a deck's", check_equation_bars),
    ("Pandoc's bar accent, written and read", check_bar_accents),
    ("a bare link's replacement in a source copy", check_link_replacements),
    ("the archive's name", check_archive_name),
    ("the content prefix", check_content_prefix),
    ("the wrapper module's name", check_wrapper_title),
    ("the page stylesheet's contrast, light and dark", check_page_css),
    ("highlighted code's colors", check_highlighting),
    ("one file per chapter", check_one_file_chapters),
    ("a page's notes group", check_notes_groups),
    ("a title's and a moved note's language", check_notes_languages),
    ("a page's notes heading", check_notes_heading),
    ("a chapter's notes, before the footer", check_notes_before_footer),
    ("the footer outside an HTML page", check_page_footer),
    ("the names a target copies files under", check_output_names),
    ("identifiers", check_identifiers),
    ("facts written down twice", check_consistency),
    ("sidecar paths", check_sidecar_paths),
    ("a deck's math report's note on its form", check_deck_math_note),
    ("shortDOIs for a bare-links sidecar", check_shortdoi),
    ("the decorative marker", check_decorative_marker),
    ("sidecars Excel saved, with files appended", check_sidecar_marks),
    ("sidecars the run can't rewrite, read by every reader", check_sidecars_left_as_they_are),
    ("sidecars root owns, read by a run as another user", check_sidecars_another_user),
    ("a sidecar Excel saved as plain CSV", check_sidecar_code_pages),
    ("the byte-order mark on every report", check_report_marks),
    ("the PDF target's default page", check_default_page),
    ("PDF/UA-1's math", check_ua1_math),
    ("a formula's words, in an HTML source", check_math_words),
    ("display style in running text, in an HTML source", check_display_style_in_text),
    ("a table whose head holds every row, in an HTML source", check_head_only_tables),
    ("header cells holding only formulas, in a PDF", check_pdf_formula_headers),
    ("an image named in another case, in a source's copy", check_cased_images_in_copies),
    ("a picture in a book's media folder, in a source's copy", check_media_keys_in_copies),
    ("a page's language", check_page_languages),
    ("a page's language in its source's copy", check_copy_languages),
    ("a one-page book's title page, its page in another language", check_title_page_languages),
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
