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
            if not os.path.exists(os.path.join(work, name + ".docx")):
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
            # The filter writes JSON and the writer reads it, as in
            # convert.sh, so the filtered intermediate is what the EPUB
            # assembler will see and what case_intermediate checks.
            self._pandoc([
                "-f", "json", "-t", "json", name + ".json",
                "-o", name + ".filtered.json",
                "--lua-filter", os.path.join(BIN, "figures-and-tables.lua"),
            ], environment, work)
            # The stylesheet goes in the way convert.sh puts it in. It
            # matters: --include-in-header would silently discard the
            # author <meta> the case_metadata checks look for.
            with open(os.path.join(work, "head.html"), "w",
                      encoding="utf-8") as fh:
                fh.write("<style>/* test */</style>\n")
            environment["HEADER_INCLUDES_FILE"] = os.path.join(work,
                                                               "head.html")
            self._pandoc([
                "-f", "json", "-t", "html5", name + ".filtered.json",
                "-o", name + ".html",
                "--standalone", "--ascii", "--math-method=mathml",
                "--lua-filter", os.path.join(BIN, "header-includes.lua"),
                "-M", "lang=en",
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
        ("the stylesheet and the author meta both reach the head",
         lambda: "/* test */" in page and 'name="author"' in page),
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

    These pin what the filter does with no declaration in reach, which
    is how these cases run: no resolved file, so a merged full-width row
    stays a spanning header and a table with no header signal keeps the
    first row Pandoc's reader promoted. What a declaration does instead
    is pinned in case_headers and case_split, which run the pre-pass the
    way convert.sh does. A change is only checkable if the
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
        # With no pre-pass in reach, as here, the reader's spanning header
        # cell stands. With one, caption-rows=1 is inferred and the row
        # becomes the caption; case_headers covers that.
        ("a merged full-width first row becomes a header spanning the table",
         lambda: 'colspan="3"' in head
                 and "Table 2.1 Sample results" in head),
        ("the real header row below it is still marked up as headers",
         lambda: Converted.cells(head, "th") == 4
                 and head.count('scope="col"') == 4),
        ("its label is reported, keyed by position because it is merged",
         lambda: any("table-1" in key for key in
                     out.report_column("caps-missing.csv", 0))),
        # With no pre-pass in reach, as here, the filter leaves the table
        # as Pandoc's reader gave it. Declaring none is covered by
        # case_headers; this pins the no-declaration behavior.
        ("a table with no header signal still gets its first row promoted",
         lambda: Converted.cells(plain, "th") == 2),
    ]


def case_split(work):
    """split-at: one table per band, each with the header row and the
    band as its caption, and the header declaration applied per part.

    The fixture is built here as OOXML, through the pre-pass suite's
    builder, because the shape -- a band, its own header row beneath it,
    three data rows, again twice -- is the one 7-5-costs-in-the-long-run
    has and nothing in tests/fixtures does.
    """
    import csv
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "headers_tests", os.path.join(HERE, "run-headers-tests.py"))
    hb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hb)

    def block(letter, wage):
        return [hb.row([hb.cell("Example %s: workers cost $%d" % (letter, wage),
                                bold=True, span=4)]),
                hb.row([hb.cell(""), hb.cell("Labor Cost"), hb.cell("Machine Cost"),
                        hb.cell("Total Cost")]),
                hb.row([hb.cell("Technology 1"), hb.cell("$%d" % (10 * wage)),
                        hb.cell("$160"), hb.cell("$%d" % (10 * wage + 160))]),
                hb.row([hb.cell("Technology 2"), hb.cell("$%d" % (7 * wage)),
                        hb.cell("$320"), hb.cell("$%d" % (7 * wage + 320))])]
    banded = hb.table(block("A", 40) + block("B", 55) + block("C", 90))
    # The other shape: one header row marked in Word, then bands partway
    # down with plain rows beneath. BC-12's "Front Matter / Body / Back
    # Matter" table. Each part must carry the original head.
    headed = hb.table([
        hb.row([hb.cell("Part"), hb.cell("Purpose"), hb.cell("Length")], header=True),
        hb.row([hb.cell("Front matter", bold=True, span=3)]),
        hb.row([hb.cell("Title page"), hb.cell("Identifies the report"), hb.cell("1")]),
        hb.row([hb.cell("Abstract"), hb.cell("Summarizes it"), hb.cell("1")]),
        hb.row([hb.cell("Body", bold=True, span=3)]),
        hb.row([hb.cell("Introduction"), hb.cell("States the problem"), hb.cell("2")]),
        hb.row([hb.cell("Methods"), hb.cell("Says what was done"), hb.cell("3")]),
    ])
    # The third shape: a bold header row that repeats, with a group name
    # in its corner. Table 7.2 of the sociology book. The repeated row is
    # each part's header, and only the corner goes into the caption.
    grouped = hb.table([
        hb.row([hb.cell("Functionalism", bold=True), hb.cell("Theorist", bold=True),
                hb.cell("Deviance arises from", bold=True)]),
        hb.row([hb.cell("Strain theory"), hb.cell("Merton"), hb.cell("Blocked goals")]),
        hb.row([hb.cell("Disorganization"), hb.cell("Chicago school"), hb.cell("Weak ties")]),
        hb.row([hb.cell("Conflict theory", bold=True), hb.cell("Theorist", bold=True),
                hb.cell("Deviance arises from", bold=True)]),
        hb.row([hb.cell("Unequal system"), hb.cell("Marx"), hb.cell("Inequality")]),
        hb.row([hb.cell("Power elite"), hb.cell("Mills"), hb.cell("Power")]),
    ])
    os.makedirs(work, exist_ok=True)
    hb.docx(os.path.join(work, "banded.docx"),
            [hb.para("Table 7.14 Total cost with rising labor costs"), banded,
             hb.para("Prose between the tables, as there always is."),
             hb.para("Table 1.1 Report parts"), headed,
             hb.para("More prose."),
             hb.para("Table 7.2 Theoretical perspectives"), grouped])

    tool = os.path.join(BIN, "table-headers.py")
    resolved = os.path.join(work, "table-headers.json")
    subprocess.run([sys.executable, tool, "banded.docx",
                    "--sidecar", os.path.join(work, "table-headers.csv"),
                    "--new", os.path.join(work, "table-headers-new.csv"),
                    "--report", os.path.join(work, "table-headers-report.csv"),
                    "--resolved", resolved],
                   cwd=work, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    with open(os.path.join(work, "table-headers-new.csv"), newline="", encoding="utf-8") as fh:
        new = list(csv.DictReader(fh))
    out = Converted(work, ["banded"], {"TABLE_HEADERS_RESOLVED": resolved})
    everything = out.tables("banded")
    tables, headed_parts, grouped_parts = everything[:3], everything[3:5], everything[5:]
    headed_heads = [re.search(r"<thead>.*?</thead>", t, re.S) for t in headed_parts]
    grouped_heads = [re.search(r"<thead>.*?</thead>", t, re.S) for t in grouped_parts]
    grouped_new = [r for r in new if r["label"] == "Table 7.2"]
    flat = lambda t: " ".join(re.sub(r"<[^>]+>", " ", t).split())
    caps = [" ".join(re.sub(r"<[^>]+>", "",
                            re.search(r"<caption>(.*?)</caption>", t, re.S).group(1)).split())
            if "<caption>" in t else "" for t in tables]
    heads = [re.search(r"<thead>.*?</thead>", t, re.S) for t in tables]
    return [
        ("the pre-pass infers split-at for the bands, row 1 included",
         lambda: new and new[0]["split-at"] == "1,5,9"),
        ("and does not mistake the first band for a title",
         lambda: new and new[0]["caption-rows"] == ""),
        ("and guesses the value part by part",
         lambda: new and new[0]["headers"] == "both"),
        ("the table becomes one table per band",
         lambda: len(tables) == 3),
        ("each part's caption is the table's caption and its band",
         lambda: all(c.startswith("Table 7.14 Total cost with rising labor costs: Example")
                     for c in caps) and "Example C" in caps[2]),
        ("each part has its own header row, promoted",
         lambda: all(h and Converted.cells(h.group(0), "th") == 4 for h in heads)),
        ("and row headers on every body row",
         lambda: all(t.count('<th scope="row">') == 2 for t in tables)),
        ("no band survives as a cell",
         lambda: all('colspan="4"' not in t for t in tables)),
        # The headed shape.
        ("a table with a marked header row and bands below splits into its parts",
         lambda: len(headed_parts) == 2),
        ("and each part carries a copy of the original header row",
         lambda: all(h and "Purpose" in h.group(0) and Converted.cells(h.group(0), "th") == 3
                     for h in headed_heads)),
        # The repeated-header shape.
        ("a repeating bold header row with a group name in its corner is inferred as a split",
         lambda: grouped_new and grouped_new[0]["split-at"] == "1,4"),
        ("and splits into a table per group",
         lambda: len(grouped_parts) == 2),
        ("each headed by its own repeated row, not captioned by it",
         lambda: all(h and "Theorist" in h.group(0) and Converted.cells(h.group(0), "th") == 3
                     for h in grouped_heads)),
        ("with only the corner cell composed into the caption",
         lambda: len(grouped_parts) == 2
                 and "Table 7.2 Theoretical perspectives: Functionalism" in flat(grouped_parts[0])
                 and "Table 7.2 Theoretical perspectives: Conflict theory" in flat(grouped_parts[1])
                 and "Theorist" not in re.search(r"<caption>.*?</caption>", grouped_parts[0], re.S).group(0)),
        ("with the table's caption and the band as each part's caption",
         lambda: len(headed_parts) == 2
                 and all("Table 1.1 Report parts:" in " ".join(
                     re.sub(r"<[^>]+>", "", t).split()) for t in headed_parts)
                 and "Front matter" in headed_parts[0] and "Body" in headed_parts[1]
                 and 'colspan="3"' not in headed_parts[0]),
    ]


def case_headers(work):
    """The filter applies what the table-headers pre-pass resolved.

    Runs the pre-pass the way convert.sh does -- once with no sidecar to
    get the prefilled rows, then with a sidecar a remediator edited --
    and converts with the resolved values in reach of the filter. Each
    value is declared on a table whose reader-built shape would have
    given something else, so the assertion is on the declaration and not
    on what Pandoc did anyway.
    """
    import csv
    os.makedirs(work, exist_ok=True)
    for name in ("tables", "tables-b"):
        shutil.copy(os.path.join(FIXTURES, name + ".docx"), work)
    tool = os.path.join(BIN, "table-headers.py")
    sidecar = os.path.join(work, "table-headers.csv")
    resolved = os.path.join(work, "table-headers.json")

    def prepass():
        subprocess.run([sys.executable, tool, "tables.docx", "tables-b.docx",
                        "--sidecar", sidecar,
                        "--new", os.path.join(work, "table-headers-new.csv"),
                        "--report", os.path.join(work, "table-headers-report.csv"),
                        "--resolved", resolved],
                       cwd=work, capture_output=True, text=True,
                       stdin=subprocess.DEVNULL)

    prepass()
    with open(os.path.join(work, "table-headers-new.csv"), newline="",
              encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    # Table 1.1: the guess says both; keep it. Table 1.2 has a repeat-header
    # row and is declared first-column, so its head must come down and its
    # first column go up. tables-b's second table is declared none.
    by_label = {r["label"]: r for r in rows}
    by_label["Table 1.2"]["headers"] = "first-column"
    plain = [r for r in rows if r["source"] == "tables-b.docx"][-1]
    plain["headers"] = "none"
    with open(sidecar, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    prepass()

    out = Converted(work, ["tables", "tables-b"],
                    {"TABLE_HEADERS_RESOLVED": resolved})
    t11, t12 = out.tables("tables")[:2]
    titled_html, plain_html = out.tables("tables-b")[:2]
    body_rows = t11.count("<tr>") - 1
    titled_head = re.search(r"<thead>.*?</thead>", titled_html, re.S)
    titled_head = titled_head.group(0) if titled_head else ""

    # A resolved entry whose shape does not match the table it points at
    # must not be applied: the filter's count of tables and the pre-pass's
    # could disagree, and a declaration on the wrong table is worse than
    # none. Doctor the entry for Table 1.2 and convert again.
    import json
    with open(resolved, encoding="utf-8") as fh:
        doctored = json.load(fh)
    doctored["tables"][1]["cols"] = 9
    wrong = os.path.join(work, "wrong.json")
    with open(wrong, "w", encoding="utf-8") as fh:
        json.dump(doctored, fh)
    again = Converted(os.path.join(work, "again"), ["tables"],
                      {"TABLE_HEADERS_RESOLVED": wrong})
    t12_again = again.tables("tables")[1]
    return [
        ("a table declared both keeps its header row",
         lambda: "<thead>" in t11 and 'scope="col"' in t11),
        ("and gets scope=\"row\" on the first cell of every body row",
         lambda: t11.count('<th scope="row">') == body_rows and body_rows > 0),
        ("a table declared first-column loses its reader-built header row",
         lambda: "<thead>" not in t12),
        ("and gains row headers instead",
         lambda: t12.count('<th scope="row">') == t12.count("<tr>")),
        ("a table declared none has no header cells at all",
         lambda: Converted.cells(plain_html, "th") == 0),
        ("the pre-pass report records the declarations",
         lambda: out.reports.get("table-headers-report.csv", "").count("declared") >= 2),
        # The merged title row: caption-rows=1 is inferred by the pre-pass
        # and written into the prefilled row, which the remediator kept.
        ("a merged title row becomes the caption",
         lambda: "<caption>" in titled_html
                 and "Table 2.1 Sample results" in
                 re.search(r"<caption>.*?</caption>", titled_html, re.S).group(0)),
        ("and is no longer a header cell spanning the table",
         lambda: 'colspan="3"' not in titled_head
                 and "Sample results" not in titled_head),
        ("the real header row beneath it is the head",
         lambda: Converted.cells(titled_head, "th") == 3
                 and titled_head.count('scope="col"') == 3),
        ("a resolved entry whose shape does not match is not applied",
         lambda: "<thead>" in t12_again
                 and t12_again.count('<th scope="row">') == 0),
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


def case_intermediate(work):
    """Filtering to JSON and rendering that must give the same page as
    filtering while rendering.

    convert.sh does the former so that every output format reads one
    remediated intermediate. The filter has one branch that looks at the
    output format -- the byline goes into the head only for HTML writers
    -- and this is where a second such branch would show up as a page
    that differs by which route produced it. Byte equality is the test,
    since the comparator's tolerance would hide exactly that."""
    out = Converted(work, ["metadata", "tables"])
    direct = {}
    for name in ("metadata", "tables"):
        environment = dict(os.environ)
        environment.update({
            "TABLE_CAPTIONS": os.path.join(work, "table-captions.csv"),
            "IMAGE_ALT": os.path.join(work, "image-alt.csv"),
            "IMAGE_ALT_MISSING": os.path.join(work, "alt-direct.csv"),
            "TABLE_CAPTIONS_MISSING": os.path.join(work, "caps-direct.csv"),
            "PROMOTE_H1_TO_TITLE": "always",
            "AUTHOR_BYLINE": "meta",
            "HEADER_INCLUDES_FILE": os.path.join(work, "head.html"),
        })
        Converted._pandoc([
            "-f", "json", "-t", "html5", name + ".json",
            "-o", name + ".direct.html",
            "--standalone", "--ascii", "--math-method=mathml",
            "-M", "lang=en",
            "--lua-filter", os.path.join(BIN, "figures-and-tables.lua"),
            "--lua-filter", os.path.join(BIN, "header-includes.lua"),
        ], environment, work)
        with open(os.path.join(work, name + ".direct.html"),
                  encoding="utf-8") as fh:
            direct[name] = fh.read()
    return [
        ("a page with author metadata renders the same either way",
         lambda: out.pages["metadata"] == direct["metadata"]),
        ("a page with declared-header tables renders the same either way",
         lambda: out.pages["tables"] == direct["tables"]),
        ("the intermediate carries the byline as a head include",
         lambda: 'name=\\"author\\"' in open(
             os.path.join(work, "metadata.filtered.json"),
             encoding="utf-8").read()),
    ]


CASES = [
    ("document metadata", case_metadata),
    ("the filtered intermediate", case_intermediate),
    ("promotion and byline modes", case_metadata_modes),
    ("table labels and empty tables", case_tables),
    ("merged title rows and unclassifiable tables", case_tables_b),
    ("declared table headers", case_headers),
    ("split at grouping bands", case_split),
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
