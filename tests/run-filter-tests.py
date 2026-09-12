#!/usr/bin/env python3
"""
run-filter-tests.py -- convert the fixture documents and check the
accessibility work the Lua filters are supposed to do.

    python3 tests/run-filter-tests.py
    python3 tests/run-filter-tests.py --keep   # leave the output to look at

Needs Pandoc 3.9 or later and nothing else. The fixtures under
tests/fixtures/ are committed; tests/make-filter-fixtures.py rebuilds them
and is the only thing that needs python-docx.

WHY THESE EXIST

Every filter bug fixed in v0.2 was silent. Alt text applied to the wrong
image; two H1 elements on a page; a caption that stopped being found; a
ten-row table reduced to one empty cell; three equations per page lost
because they contained a vertical bar. Nothing raised an error and
nothing in the reports showed it.

They were found by converting a whole book with two versions of the
pipeline and comparing, which works only while the previous version is
still installed and a corpus is on hand. These assert the same things
against six small documents, so the check survives the version it was
written for.

Some cases pin behaviour that is about to change -- a merged title row,
a table with no header signal -- rather than behaviour that is right.
Those say so. A change is only checkable if the starting point was
written down.

Each case names the behaviour rather than the bug, because a test that
says what should happen is readable by someone who never saw the bug.

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
import glob
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

NEEDED = ("metadata", "tables", "tables-b", "math", "media-a", "media-b")


class Converted:
    """One conversion run, and what came out of it."""

    def __init__(self, work, names, settings=None, sidecars=None):
        os.makedirs(work, exist_ok=True)
        self.work = work
        self.pages = {}
        self.reports = {}

        environment = dict(os.environ)
        environment.update({
            "TABLE_CAPTIONS": os.path.join(work, "table-captions.csv"),
            "IMAGE_ALT": os.path.join(work, "image-alt.csv"),
            "TABLE_CAPTIONS_MISSING": os.path.join(work, "caps-missing.csv"),
            "IMAGE_ALT_MISSING": os.path.join(work, "alt-missing.csv"),
            "TABLE_HEADERS_MISSING": os.path.join(work, "heads-missing.csv"),
            "MEDIA_UNRESOLVED": os.path.join(work, "media-unresolved.csv"),
            "SPACER_LOG": os.path.join(work, "spacers.csv"),
            "PROMOTE_H1_TO_TITLE": "always",
            "AUTHOR_BYLINE": "meta",
        })
        environment.update(settings or {})

        for name, content in (sidecars or {}).items():
            with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
                fh.write(content)

        for name in names:
            shutil.copy(os.path.join(FIXTURES, name + ".docx"), work)
            # Run from the working directory with relative paths, because
            # that is what convert.sh does and it shows up in the output:
            # --extract-media given an absolute path puts absolute paths
            # into the sidecar keys, which would differ between machines.
            self._pandoc([
                "-f", "docx", "-t", "json", name + ".docx",
                "-o", name + ".json",
                "--lua-filter", os.path.join(BIN, "media-extensions.lua"),
                "--extract-media", name,
            ], environment, work)
            self._pandoc([
                "-f", "json", "-t", "html5", name + ".json",
                "-o", name + ".html",
                "--standalone", "--ascii", "--math-method=mathml",
                "-M", "lang=en",
                "--lua-filter", os.path.join(BIN, "figures-and-tables.lua"),
            ], environment, work)
            with open(os.path.join(work, name + ".html"),
                      encoding="utf-8") as fh:
                self.pages[name] = fh.read()

        for path in glob.glob(os.path.join(work, "*.csv")):
            with open(path, encoding="utf-8") as fh:
                self.reports[os.path.basename(path)] = fh.read()

    @staticmethod
    def single_pass(work, names, settings=None):
        """Convert .docx straight to HTML with the figure filter attached.

        The README documents running the filter this way, and it is the
        only arrangement in which it sees Pandoc's own mediabag paths --
        "media/image1.png" rather than "media-a/media/image1.png",
        because --extract-media rewrites them after filters run. Two
        documents then present identically named media, which is the
        collision that applied one document's alt text to another's
        image. The two-step pipeline convert.sh uses does not reach this,
        so nothing else here covers it.
        """
        out = Converted.__new__(Converted)
        os.makedirs(work, exist_ok=True)
        out.work, out.pages, out.reports = work, {}, {}
        environment = dict(os.environ)
        environment.update({
            "TABLE_CAPTIONS": os.path.join(work, "table-captions.csv"),
            "IMAGE_ALT": os.path.join(work, "image-alt.csv"),
            "IMAGE_ALT_MISSING": os.path.join(work, "alt-missing.csv"),
            "TABLE_CAPTIONS_MISSING": os.path.join(work, "caps-missing.csv"),
            "TABLE_HEADERS_MISSING": os.path.join(work, "heads-missing.csv"),
            "PROMOTE_H1_TO_TITLE": "always",
        })
        environment.update(settings or {})
        for name in names:
            shutil.copy(os.path.join(FIXTURES, name + ".docx"), work)
            Converted._pandoc([
                "-f", "docx", "-t", "html5", name + ".docx",
                "-o", name + ".html", "--standalone", "--ascii",
                "-M", "lang=en", "--extract-media", name,
                "--lua-filter", os.path.join(BIN, "figures-and-tables.lua"),
            ], environment, work)
            with open(os.path.join(work, name + ".html"),
                      encoding="utf-8") as fh:
                out.pages[name] = fh.read()
        for path in glob.glob(os.path.join(work, "*.csv")):
            with open(path, encoding="utf-8") as fh:
                out.reports[os.path.basename(path)] = fh.read()
        return out

    @staticmethod
    def _pandoc(arguments, environment, cwd):
        result = subprocess.run(["pandoc"] + arguments, env=environment,
                                cwd=cwd, capture_output=True, text=True,
                                stdin=subprocess.DEVNULL)
        if result.returncode:
            raise RuntimeError("pandoc failed: " + result.stderr[-400:])

    # -- things the assertions ask about -----------------------------------

    def title(self, name):
        found = re.search(r"<title>(.*?)</title>", self.pages[name], re.S)
        return " ".join(found.group(1).split()) if found else ""

    def count(self, name, needle):
        return self.pages[name].count(needle)

    def captions(self, name):
        return [" ".join(re.sub(r"<[^>]+>", "", c).split())
                for c in re.findall(r"<caption[^>]*>(.*?)</caption>",
                                    self.pages[name], re.S)]

    def tables(self, name):
        return re.findall(r"<table.*?</table>", self.pages[name], re.S)

    def media(self, name):
        return sorted(os.path.basename(p) for p in
                      glob.glob(os.path.join(self.work, name, "media", "*")))

    def alt_texts(self, name):
        return re.findall(r'<img[^>]*\balt="([^"]*)"', self.pages[name])

    @staticmethod
    def cells(markup, tag):
        """Count th or td elements. Not a substring count: "<th" also
        matches "<thead", which quietly inflated this by one."""
        return len(re.findall(r"<%s[ >]" % tag, markup))

    def report_column(self, report, column):
        """One column of a report the filter appended to.

        These files carry no header row -- convert.sh adds one when it
        consolidates them -- so every line is data. Skipping the first,
        as for a normal CSV, silently halved what the assertions saw.
        """
        values = []
        for row in self.reports.get(report, "").splitlines():
            if not row.strip():
                continue
            field = row.split(",")[column].strip().strip('"')
            if field.lower() in ("label", "image", "file", "source"):
                continue
            values.append(field)
        return values


# --------------------------------------------------------------------------
# the cases
# --------------------------------------------------------------------------

def case_metadata(work):
    """Word's own title and author must not displace the page's heading."""
    out = Converted(work, ["metadata"])
    page = out.pages["metadata"]
    return [
        ("the page title keeps the section number the heading carries",
         lambda: out.title("metadata") == "1.3 Levels of Measurement"),
        ("the page has exactly one h1",
         lambda: out.count("metadata", "<h1") == 1),
        ("the author is kept as document metadata",
         lambda: 'name="author"' in page),
        ("the author is not printed as a visible byline",
         lambda: 'class="author"' not in page),
        ("a heading behind a leading layout table is still found",
         lambda: "1.3 Levels of Measurement" in page),
        ("the layout table holding the opening figure became a figure",
         lambda: "<figure" in page and not out.tables("metadata")),
    ]


def case_metadata_modes(work):
    """The promotion and byline modes do what they say."""
    def variant(name, settings):
        return Converted(os.path.join(work, name), ["metadata"], settings)

    never = variant("never", {"PROMOTE_H1_TO_TITLE": "never"})
    visible = variant("visible", {"AUTHOR_BYLINE": "visible"})
    dropped = variant("drop", {"AUTHOR_BYLINE": "drop"})
    return [
        ("promote_h1_to_title=never leaves the heading in the body",
         lambda: never.count("metadata", "<h1") == 2),
        ("author_byline=visible keeps the byline",
         lambda: 'class="author"' in visible.pages["metadata"]),
        ("author_byline=drop removes the metadata as well",
         lambda: 'name="author"' not in dropped.pages["metadata"]),
    ]


def case_tables(work):
    """Labels Word stored oddly, and tables Markdown used to destroy."""
    out = Converted(work, ["tables"], sidecars={
        # Keyed by position, as v0.1 reported it. The label resolves now,
        # so this only applies if the lookup still tries both.
        "table-captions.csv":
            'tables#table-1,"A description written against a position key"\n',
    })
    captions = out.captions("tables")
    tables = out.tables("tables")
    worksheet = tables[-1] if tables else ""
    return [
        ("a label Word stored as a one-item list is found",
         lambda: any(c.startswith("Table 1.1") for c in captions)),
        ("a caption written against a position key still applies",
         lambda: any("position key" in c for c in captions)),
        ("a table whose data cells are all empty survives intact",
         lambda: worksheet.count("<tr") == 6),
        ("its header row is marked up as headers",
         lambda: Converted.cells(worksheet, "th") == 2
                 and 'scope="col"' in worksheet),
        ("the reports name the tables by label, not by position",
         lambda: all("#table-" not in key for key in
                     out.report_column("caps-missing.csv", 0))),
    ]


def case_tables_b(work):
    """A merged title row, and a table with nothing to classify it by.

    These pin what the filter does today rather than what it should do.
    Roadmap item 1 changes both -- a merged full-width row ought to become
    the caption, and a table with no header signal ought to be declarable
    rather than guessed at -- and a change is only checkable if the
    starting point is written down.
    """
    out = Converted(work, ["tables-b"])
    tables = out.tables("tables-b")
    titled = tables[0] if tables else ""
    plain = tables[1] if len(tables) > 1 else ""
    head = re.search(r"<thead>.*?</thead>", titled, re.S)
    head = head.group(0) if head else ""
    return [
        ("both tables are present",
         lambda: len(tables) == 2),
        # Today: a spanning header cell. Item 1 should make this a caption.
        ("a merged full-width first row becomes a header spanning the table",
         lambda: 'colspan="3"' in head
                 and "Table 2.1 Sample results" in head),
        ("the real header row below it is still marked up as headers",
         lambda: Converted.cells(head, "th") == 4
                 and head.count('scope="col"') == 4),
        ("its label is reported, keyed by position because it is merged",
         lambda: any("table-1" in key for key in
                     out.report_column("caps-missing.csv", 0))),
        # Today: Pandoc's reader promotes the first row regardless. Item 1
        # should let a person declare that this table has no headers.
        ("a table with no header signal still gets its first row promoted",
         lambda: Converted.cells(plain, "th") == 2),
    ]


def case_math(work):
    """Equations, MathSpeak descriptions, and spacer images."""
    out = Converted(work, ["math"], {"SPACER_BELOW": "0.3in",
                                     "STRIP_SPACER": "false"})
    page = out.pages["math"]
    text = re.sub(r"<[^>]+>", "", page)
    return [
        ("an equation is written as MathML",
         lambda: "<math" in page),
        ("an equation containing a vertical bar survives",
         lambda: "|" in text),
        ("a MathSpeak description is rejoined into readable text",
         lambda: any("sigma" in alt for alt in out.alt_texts("math"))),
        ("a hair-thin image is marked decorative rather than described",
         lambda: "" in out.alt_texts("math")),
        ("spacers are logged so the setting is discoverable",
         lambda: "spacers.csv" in out.reports),
    ]


def case_media(work):
    """Word's content types, alt text, and keys that must stay distinct."""
    out = Converted(work, ["media-a", "media-b"])
    keys = out.report_column("alt-missing.csv", 0)
    return [
        ("media is named by what it is, not by what Word declared",
         lambda: out.media("media-a") == ["image1.png"]),
        ("an image is an img, not an embed",
         lambda: out.count("media-a", "<img") == 2
                 and out.count("media-a", "<embed") == 0),
        ("alt text is trimmed before it is used",
         lambda: "Alt text with a leading space" in out.alt_texts("media-a")
                 and all(a == a.strip() for a in out.alt_texts("media-a"))),
        ("two documents whose media is named alike get distinct keys",
         lambda: len(keys) >= 2 and len(set(keys)) == len(keys)),
        ("each key names the document the image belongs to",
         lambda: keys and all(k.startswith(("media-a/", "media-b/"))
                              for k in keys)),
    ]


def case_media_keys_single_pass(work):
    """Keys must stay distinct even when Pandoc has not yet qualified the
    paths, which is what happens converting straight from .docx."""
    out = Converted.single_pass(work, ["media-a", "media-b"])
    keys = out.report_column("alt-missing.csv", 0)
    sources = out.report_column("alt-missing.csv", 2)
    return [
        ("both documents report an image needing alt text",
         lambda: len(sources) == 2 and set(sources) == {"media-a", "media-b"}),
        ("their keys are distinct despite identically named media",
         lambda: len(set(keys)) == 2),
        ("each key names the document the image came from",
         lambda: all(k.startswith(("media-a/", "media-b/")) for k in keys)),
    ]


CASES = [
    ("document metadata", case_metadata),
    ("promotion and byline modes", case_metadata_modes),
    ("table labels and empty tables", case_tables),
    ("merged title rows and unclassifiable tables", case_tables_b),
    ("equations, MathSpeak, and spacers", case_math),
    ("media naming, alt text, and keys", case_media),
    ("media keys when converting in one pass", case_media_keys_single_pass),
]


# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Check the Lua filters against the fixture documents.")
    parser.add_argument("--keep", action="store_true",
                        help="leave the converted output in place")
    arguments = parser.parse_args()

    if shutil.which("pandoc") is None:
        sys.exit("pandoc is not on the path.")

    # The same requirement convert.sh enforces. Without this check an
    # older Pandoc fails with "Unknown option --math-method", which says
    # nothing about the actual problem.
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

    work = tempfile.mkdtemp(prefix="filter-tests-")
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
          if failed else "\nall filter checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
