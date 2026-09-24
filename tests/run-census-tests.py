#!/usr/bin/env python3
"""
run-census-tests.py -- check the sidecar guess in lib/tablecensus.py.

    python3 tests/run-census-tests.py

Needs nothing but the standard library. The tables are built as
word/document.xml directly rather than with python-docx, so each case
carries exactly the bold, shading, and tblHeader signals it means to and
nothing else. That matters here more than elsewhere: the guess turns on
whether formatting is present, and a library that helpfully applies a
table style would decide the answer before the rule ran.

WHY THESE EXIST

The guess decides what several hundred sidecar rows say before a person
looks at them, and every one it gets wrong is a correction someone has to
notice and make. It is also the part of the census that reads content
rather than the file, so a corpus is the only other way to check it, and a
corpus is not something a test can carry.

Each case names a table shape rather than a rule, and two of them exist to
pin behavior the rule must NOT have: a table of descriptions and a table
with a repeating first column both stay col, because a first column that
keys its rows only means something when the rest of the table is values.

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
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "lib"))
import tablecensus as tc  # noqa: E402

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def cell(text, bold=False, shaded=False, span=1):
    pr = "<w:tcPr>"
    if span > 1:
        pr += '<w:gridSpan w:val="%d"/>' % span
    if shaded:
        pr += '<w:shd w:val="clear" w:fill="D9D9D9"/>'
    pr += "</w:tcPr>"
    rpr = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return "<w:tc>%s<w:p><w:r>%s<w:t>%s</w:t></w:r></w:p></w:tc>" % (pr, rpr, text)


def row(cells, header=False):
    pr = "<w:trPr><w:tblHeader/></w:trPr>" if header else ""
    return "<w:tr>%s%s</w:tr>" % (pr, "".join(cells))


def table(rows):
    doc = '<w:document %s><w:body><w:tbl><w:tblPr/>%s</w:tbl></w:body></w:document>'
    body = ET.fromstring(doc % (W, "".join(rows))).find(tc.q("body"))
    return next(tc.all_tables(body))[0]


CASES = []


def case(name, expect, rows):
    CASES.append((name, expect, rows))


# The case the content rule exists for: a blank corner, a first column of
# unique labels, a numeric body, and nothing in the file marking that
# column as anything. Formatting calls this col; it is a matrix table.
case("a contingency table with an unformatted row-header column", "both", [
    row([cell(""), cell("Speeding"), cell("No speeding"), cell("Total")],
        header=True),
    row([cell("Uses cell phone"), cell("25"), cell("280"), cell("305")]),
    row([cell("Does not use"), cell("45"), cell("405"), cell("450")]),
    row([cell("Total"), cell("70"), cell("685"), cell("755")]),
])

# Same shape, prose body. A list of descriptions is not a matrix.
case("a table of descriptions stays first-row", "first-row", [
    row([cell("Retail Type"), cell("Product Focus"), cell("Example")],
        header=True),
    row([cell("Department store"), cell("Wide assortment"), cell("Macy's")]),
    row([cell("Specialty store"), cell("One category"), cell("Foot Locker")]),
])

# A column that repeats a value does not key its rows.
case("a repeating first column stays first-row", "first-row", [
    row([cell("Region"), cell("Year"), cell("Output")], header=True),
    row([cell("North"), cell("2019"), cell("14")]),
    row([cell("North"), cell("2020"), cell("17")]),
    row([cell("South"), cell("2019"), cell("11")]),
])

# A numeric first column that still keys its rows marks both axes, because a
# supply schedule's price labels its row the same way a country name does.
# The consequence of that decision, and the branch worth sampling first.
case("a numeric key column marks both axes", "both", [
    row([cell("Price"), cell("Quantity"), cell("Revenue")], header=True),
    row([cell("1"), cell("10"), cell("10")]),
    row([cell("2"), cell("9"), cell("18")]),
    row([cell("3"), cell("8"), cell("24")]),
])

# Three columns of measurements with no label column at all. The first
# column is as unique as any label column, so only its disorder
# distinguishes it. 32 tables in the three books look like this.
case("an unordered numeric first column stays first-row", "first-row", [
    row([cell("Group A"), cell("Group B"), cell("Group C")], header=True),
    row([cell("101"), cell("108"), cell("98")]),
    row([cell("98"), cell("112"), cell("104")]),
    row([cell("107"), cell("99"), cell("110")]),
])

# A bin column is labels, not numbers, and does not have to be ordered
# to prove it: most of its values will not parse as numbers at all.
case("a column of bins is a key column", "both", [
    row([cell("Family size"), cell("Compact"), cell("Mid-size")],
        header=True),
    row([cell("1"), cell("20"), cell("35")]),
    row([cell("2"), cell("20"), cell("50")]),
    row([cell("3-4"), cell("20"), cell("50")]),
    row([cell("5+"), cell("20"), cell("30")]),
])

# An empty spacer row above the real header row. Three tables in the data
# science book open like this, and reading it as the header row calls an
# ordinary table headerless. Grade level then keys the rows, so this lands
# on both; what matters is that it no longer lands on none.
case("an empty first row is read past", "both", [
    row([cell(""), cell(""), cell("")]),
    row([cell("Grade level", bold=True), cell("Students", bold=True),
         cell("Average rating", bold=True)]),
    row([cell("9th"), cell("60"), cell("8.1")]),
    row([cell("10th"), cell("60"), cell("7.4")]),
    row([cell("11th"), cell("58"), cell("7.9")]),
])

# Every row of a one-column table spans its width, so the title-row test
# must not fire: without the guard this table is consumed entirely and
# gets no value at all.
case("a one-column table is not all title rows", "first-row", [
    row([cell("Hours studied", bold=True)], header=True),
    row([cell("2")]),
    row([cell("5")]),
])

# A column of labels over a body of values heads its rows even with no
# header row above it: a list of makes against their market share.
case("labels over values with no header row", "first-column", [
    row([cell("Honda"), cell("10%")]),
    row([cell("Nissan"), cell("7%")]),
    row([cell("Hyundai"), cell("5%")]),
    row([cell("Kia"), cell("4%")]),
])

# The same shape with a numeric first column is not enough. With no header
# row to fix the orientation, an ordered numeric column is as likely to be
# the first data series as a lookup axis, and this one is a bare grid.
case("numbers over values with no header row stays none", "none", [
    row([cell("94.2"), cell("75.2"), cell("69.6")]),
    row([cell("77.3"), cell("74.1"), cell("70.2")]),
    row([cell("76.3"), cell("73.8"), cell("71.1")]),
])

# A blank corner with labels along both edges is a matrix, whatever the
# body holds. A normal-form game written without spanning player names is
# this shape, and so is a confusion matrix.
case("a blank corner with labels on both edges", "both", [
    row([cell(""), cell("Firm B colludes"), cell("Firm B cheats")]),
    row([cell("Firm A colludes"), cell("A gets $1,000"), cell("A gets $200")]),
    row([cell("Firm A cheats"), cell("A gets $1,500"), cell("A gets $400")]),
])

# The guard: a table of descriptions has a heading over its first column,
# so the corner is not blank and the rule never fires.
case("a heading over the first column is not a matrix", "first-row", [
    row([cell("Retail type", bold=True), cell("Product focus", bold=True),
         cell("Example", bold=True)]),
    row([cell("Department store"), cell("Wide assortment"), cell("Macy's")]),
    row([cell("Specialty store"), cell("One category"), cell("Foot Locker")]),
])

# A row of words over rows of numbers is a header row even though nothing
# in the file says so. Here the first column is unordered, so it stops at
# first-row.
case("words over numbers is a header row", "first-row", [
    row([cell("Group A"), cell("Group B"), cell("Group C")]),
    row([cell("101"), cell("108"), cell("98")]),
    row([cell("98"), cell("112"), cell("104")]),
    row([cell("107"), cell("99"), cell("110")]),
])

# Same signal, but the first column is an ordered key, so the row-header
# rule fires on top of it and the table lands on both.
case("words over numbers with a key column is both", "both", [
    row([cell("Labor"), cell("Wage")]),
    row([cell("1"), cell("1")]),
    row([cell("2"), cell("3")]),
    row([cell("3"), cell("5")]),
    row([cell("4"), cell("7")]),
])

# Values with their units written out are still values, so a label column
# over a column of dollar amounts heads its rows.
case("labels over amounts with units", "first-column", [
    row([cell("Government purchases"), cell("$120 billion")]),
    row([cell("Depreciation"), cell("$40 billion")]),
    row([cell("Consumption"), cell("$400 billion")]),
    row([cell("Business investment"), cell("$60 billion")]),
])

# The guard: a first column of dollar amounts is a data series, not
# labels, so a bare grid of money stays none.
case("a grid of money is not a label column", "none", [
    row([cell("$46,500.00"), cell("$0"), cell("$40,966.50")]),
    row([cell("$19,500.00"), cell("$181,557.20"), cell("$2,900")]),
    row([cell("$3,600"), cell("$1,243,900"), cell("$10,900")]),
])

# A trailing total row usually has nothing in its label cell, and one
# blank cell would otherwise disqualify the whole first column.
case("a trailing total row does not break the key column", "both", [
    row([cell("Streaming services", bold=True), cell("Frequency", bold=True)],
        header=True),
    row([cell("0"), cell("66")]),
    row([cell("1"), cell("119")]),
    row([cell("2"), cell("340")]),
    row([cell("4+"), cell("15")]),
    row([cell(""), cell("Total = 540")]),
])

# A data row above the real header row. Nothing can be declared about
# this, and "none" would be a false claim that the table has no headers.
case("a header band below a data row is unknown", "unknown", [
    row([cell("Population estimates, July 1, 2019"), cell("328,239,523")]),
    row([cell("Race and Hispanic Origin", bold=True),
         cell("Percentage (%)", bold=True)]),
    row([cell("White alone"), cell("76.3")]),
    row([cell("Black or African American alone"), cell("13.4")]),
    row([cell("Asian alone"), cell("5.9")]),
])

# A merged title, a bold header row, and a bold first column all at once.
# The title-row branch of classify() reports the title and not the
# column, so the guess has to ask about the column itself.
case("a title row does not hide a formatted header column", "both", [
    row([cell("The Message Triangle", span=3)]),
    row([cell("Element", bold=True), cell("Focus", bold=True),
         cell("Example", bold=True)]),
    row([cell("Purpose", bold=True), cell("What is the core idea?"),
         cell("We are requesting approval")]),
    row([cell("Clarity", bold=True), cell("How simply can it be stated?"),
         cell("The change will reduce time")]),
    row([cell("Tone", bold=True), cell("How will it sound?"),
         cell("We appreciate your support")]),
])

# Half categories, half counts. The counts are a column of measurements
# and the neighborhood heads its row, so the mix does not make it prose.
case("a mixed body with one column of values", "both", [
    row([cell("Neighborhood", bold=True), cell("Income Level", bold=True),
         cell("Number of Participants", bold=True)]),
    row([cell("Northside"), cell("Low Income"), cell("35")]),
    row([cell("Southside"), cell("Middle Income"), cell("50")]),
    row([cell("Eastside"), cell("High Income"), cell("45")]),
])

# Every row of a one-column table spans the full width, so the tests that
# look for a merged header row have to stand aside for them. Here the only
# signal is that row 1 is bold.
case("a bold header row in a one-column table", "first-row", [
    row([cell("Compound Operator", bold=True)]),
    row([cell("+=")]),
    row([cell("-=")]),
    row([cell("*=")]),
])

# And with no formatting at all, a word over a column of measurements.
case("words over numbers in a one-column table", "first-row", [
    row([cell("Weight in ounces")]),
    row([cell("15.65")]),
    row([cell("16.09")]),
    row([cell("15.98")]),
])

case("a bare data array is none", "none", [
    row([cell("3.1"), cell("4.2"), cell("5.9")]),
    row([cell("2.6"), cell("5.3"), cell("5.8")]),
])

# A merged full-width first row becomes a caption, so the value has to
# describe the table that is left rather than the one in the file.
case("a title row is read past, not read as a header", "both", [
    row([cell("Example A: workers cost $40", span=3)]),
    row([cell(""), cell("Machines"), cell("Output")], header=True),
    row([cell("Workers 1"), cell("2"), cell("14")]),
    row([cell("Workers 2"), cell("3"), cell("22")]),
])

# Formatting that already proves both axes wins over the content rule,
# which would call this col because the first column repeats.
case("formatting beats the key rule where they disagree", "both", [
    row([cell(""), cell("2019", bold=True), cell("2020", bold=True)],
        header=True),
    row([cell("North", bold=True), cell("14"), cell("17")]),
    row([cell("North", bold=True), cell("11"), cell("13")]),
])

case("a header column with no header row is first-column", "first-column", [
    row([cell("Population", bold=True), cell("331"), cell("334")]),
    row([cell("Labor force", bold=True), cell("161"), cell("164")]),
])

# Layout tables are not the sidecar's business and get no value at all.
case("an image-only table gets no value", None, [
    row(["<w:tc><w:tcPr/><w:p><w:r><w:drawing/></w:r></w:p></w:tc>",
         "<w:tc><w:tcPr/><w:p><w:r><w:drawing/></w:r></w:p></w:tc>"]),
])


# ---------------------------------------------------------------------------
# The key: what must and must not change it
# ---------------------------------------------------------------------------

# What the fallback does when no header rule fires: a shape it knows, or
# none with evidence, or unknown.
case("two columns of short labels beside longer values head their rows",
     "first-column",
     [row([cell("Nursing Notes"), cell("1300: Patient reports shortness of breath")]),
      row([cell("Flow Chart"), cell("1330: Blood pressure 120/80, pulse 88")])])
case("labels beside amounts head their rows", "first-column",
     [row([cell("In the labor force"), cell("162.052 million")]),
      row([cell("Employed"), cell("155.175 million")]),
      row([cell("Unemployed"), cell("6.877 million")])])
case("under a title, a row of short labels over data is the header row",
     "first-row",
     [row([cell("Beginning Data", span=3)]),
      row([cell("OrderID"), cell("Product"), cell("TotalPrice")]),
      row([cell("101"), cell("Shirt"), cell("$75")]),
      row([cell("102"), cell("Hat"), cell("$50")])])
case("a label that begins with a number is a value, not a header",
     "first-column",
     [row([cell("Market shares", span=2)]),
      row([cell("Smooth as Glass"), cell("16% of the market")]),
      row([cell("Auto Glass Doctor"), cell("10% of the market")])])
case("a grid of amounts has no headers", "none",
     [row([cell("$46,500.00"), cell("$0"), cell("$40,966.50")]),
      row([cell("$29,050.00"), cell("$19,500.00"), cell("$181,557.20")])])
case("terms in order down each column are a list, with no headers", "none",
     [row([cell("Class"), cell("JavaDoc"), cell("private")]),
      row([cell("Code Block"), cell("Keywords"), cell("public")]),
      row([cell("Comments"), cell("Local Variables"), cell("Scope")])])
case("a table no rule recognizes is unknown, not none", "unknown",
     [row([cell("Tuesday"), cell("Apple"), cell("Seven")]),
      row([cell("Monday"), cell("Pear"), cell("Three")]),
      row([cell("Friday"), cell("Plum"), cell("Nine")])])


def part_checks():
    """guess_table: a banded table guessed part by part."""
    def band(text):
        return row([cell(text, span=3)])
    # Parts of bare amounts vote none on their own, so without the header
    # row above the first band shared with them, none outvotes it.
    shared_header = [row([cell("Year", bold=True), cell("Sales", bold=True),
                          cell("Costs", bold=True)]),
                     band("East"),
                     row([cell("2019"), cell("$1,200"), cell("$800")]),
                     row([cell("2020"), cell("$1,350"), cell("$900")]),
                     band("West"),
                     row([cell("2019"), cell("$700"), cell("$650")]),
                     row([cell("2020"), cell("$760"), cell("$640")])]
    got = tc.guess_table(table(shared_header))
    yield ("one header row above the first band heads every part, and the "
           "parts vote first-row", got[0] == "first-row", str(got[:2]))
    # The first band is partway down, so the whole table has no title and
    # only the part under the band can find its header row.
    under_bands = [row([cell("OrderID"), cell("Product"), cell("Price")]),
                   row([cell("101"), cell("Shirt"), cell("$75")]),
                   row([cell("102"), cell("Hat"), cell("$50")]),
                   band("Customers"),
                   row([cell("CustomerID"), cell("Name"), cell("City")]),
                   row([cell("1"), cell("John Doe"), cell("Boston")]),
                   row([cell("2"), cell("Jane Roe"), cell("Denver")])]
    got = tc.guess_table(table(under_bands))
    yield ("a part that opens under a band reads it as a title, so its row of "
           "short labels is its header row", got[0] == "first-row", str(got[:2]))


def key_checks():
    """Each returns (name, ok, detail)."""
    base = [row([cell("Year"), cell("GDP")]),
            row([cell("1960"), cell("543")]),
            row([cell("1965"), cell("743")])]
    k = tc.table_key(table(base))
    yield "key is a full SHA-256 hex digest", len(k) == 64, k
    yield ("identical tables share a key",
           tc.table_key(table(base)) == k, "")
    padded = [row([cell(" Year "), cell("GDP\t")]),
              row([cell("1960"), cell(" 543")]),
              row([cell("1965"), cell("743 ")])]
    yield ("leading and trailing whitespace does not change the key",
           tc.table_key(table(padded)) == k, "")
    cased = [row([cell("year"), cell("GDP")]),
             row([cell("1960"), cell("543")]),
             row([cell("1965"), cell("743")])]
    yield ("case changes the key",
           tc.table_key(table(cased)) != k, "")
    inner = [row([cell("Year"), cell("GDP")]),
             row([cell("1960"), cell("543")]),
             row([cell("1965"), cell("7 43")])]
    yield ("internal spacing changes the key",
           tc.table_key(table(inner)) != k, "")
    merged = [row([cell("Year and GDP", span=2)]),
              row([cell("1960"), cell("543")]),
              row([cell("1965"), cell("743")])]
    yield ("a merge changes the key even where text does not",
           tc.table_key(table(merged)) != k, "")
    empty = [row([cell("Year"), cell("GDP")]),
             row([cell("1960"), cell("")]),
             row([cell("1965"), cell("743")])]
    moved = [row([cell("Year"), cell("GDP")]),
             row([cell(""), cell("1960")]),
             row([cell("1965"), cell("743")])]
    yield ("an empty cell counts by position",
           tc.table_key(table(empty)) != tc.table_key(table(moved)), "")

    # Nested: the container's key depends on the inner table's key, not on
    # its text, and two containers with different inner tables differ.
    def box(text):
        return ("<w:tc><w:tcPr/><w:tbl><w:tblPr/><w:tr><w:tc><w:tcPr/>"
                "<w:p><w:r><w:t>%s</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
                "<w:p/></w:tc>" % text)
    outer_a = table([row([cell("Key"), cell("Value")]),
                     row([cell("133"), box("print(x)")])])
    outer_b = table([row([cell("Key"), cell("Value")]),
                     row([cell("133"), box("print(y)")])])
    ka, kb = tc.table_key(outer_a), tc.table_key(outer_b)
    yield ("containers with different inner tables have different keys",
           ka != kb, "")
    inner_key = tc.table_key(outer_a.find(".//" + tc.q("tbl")))
    yield ("the inner table has its own key, distinct from the container",
           inner_key != ka and len(inner_key) == 64, "")


def pandoc_checks():
    """The same rules on a table Pandoc read from HTML, through
    view_from_pandoc. Skipped without Pandoc."""
    import json
    import shutil
    import subprocess
    if shutil.which("pandoc") is None:
        return
    shapes = [
        ("html: an unmarked bold header row", "first-row",
         "<tr><td><b>HW Set</b></td><td><b>1</b></td><td><b>2</b></td></tr>"
         "<tr><td>Time (hr)</td><td>9.8</td><td>5.3</td></tr>"),
        ("html: a thead over a first column keying numbers", "both",
         "<thead><tr><th>Acres</th><th>Cost</th><th>Benefit</th></tr></thead>"
         "<tr><td>North</td><td>$0</td><td>$0</td></tr>"
         "<tr><td>South</td><td>$20</td><td>$140</td></tr>"
         "<tr><td>East</td><td>$80</td><td>$240</td></tr>"),
        ("html: row labels over values, no header row", "first-column",
         "<tr><td>Government purchases</td><td>$120 billion</td></tr>"
         "<tr><td>Depreciation</td><td>$40 billion</td></tr>"
         "<tr><td>Consumption</td><td>$400 billion</td></tr>"
         "<tr><td>Exports</td><td>$100 billion</td></tr>"),
        ("html: one cell is layout, not data", None,
         "<tr><td>Just a box of text.</td></tr>"),
    ]
    for name, expect, rows in shapes:
        doc = json.loads(subprocess.run(
            ["pandoc", "-f", "html", "-t", "json"],
            input=f"<table>{rows}</table>", capture_output=True, text=True,
            check=True).stdout)
        table = next(b for b in doc["blocks"] if b["t"] == "Table")
        got = tc.guess(tc.view_from_pandoc(table))
        yield name, got == expect, f"guess={got}, expected {expect}"
    doc = json.loads(subprocess.run(
        ["pandoc", "-f", "html", "-t", "json"],
        input="<table><tr><td rowspan='2'>A</td><td>1</td><td>2</td></tr>"
              "<tr><td>3</td><td>4</td></tr>"
              "<tr><td colspan='2'>B</td><td>5</td></tr></table>",
        capture_output=True, text=True, check=True).stdout)
    grid = tc.view_from_pandoc(next(b for b in doc["blocks"]
                                    if b["t"] == "Table")).grid
    yield ("html: a row span and a column span keep the columns aligned",
           [len(r) for r in grid] == [3, 3, 3]
           and grid[1][0].vmerge == "continue" and grid[1][1].text == "3"
           and grid[2][0] is grid[2][1],
           f"widths={[len(r) for r in grid]}")


def script_checks():
    """util/table-census.py itself: directories, books, and --help."""
    import csv
    import io
    import shutil
    import subprocess
    import tempfile
    here = os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(os.path.dirname(here), "util", "table-census.py")
    fixtures = os.path.join(here, "fixtures")
    # Fixtures that hold tables: a file with none writes no rows.
    names = ["metadata.docx", "tables-b.docx", "tables.docx"]
    with tempfile.TemporaryDirectory() as tmp:
        corpus = os.path.join(tmp, "corpus")
        os.makedirs(os.path.join(corpus, "econ"))
        os.makedirs(os.path.join(corpus, "stats", "chapters"))
        shutil.copy(os.path.join(fixtures, names[0]), os.path.join(corpus, "econ"))
        shutil.copy(os.path.join(fixtures, names[1]),
                    os.path.join(corpus, "stats", "chapters"))
        shutil.copy(os.path.join(fixtures, names[2]), corpus)
        with open(os.path.join(corpus, "econ", "~$lock.docx"), "w") as fh:
            fh.write("not a zip")
        run = subprocess.run([sys.executable, script, corpus],
                             capture_output=True, text=True)
        rows = list(csv.DictReader(io.StringIO(run.stdout)))
        books = {os.path.basename(r["Source"]): r["Book"] for r in rows}
        yield ("a directory is searched at any depth, each file in the book "
               "its subdirectory names",
               run.returncode == 0 and books.get(names[0]) == "econ"
               and books.get(names[1]) == "stats"
               and books.get(names[2]) == "corpus", str(books))
        yield ("Word's lock files are skipped",
               "~$" not in run.stdout + run.stderr, run.stderr[-200:])
        yield ("the summary gives each book's totals",
               "By book:" in run.stderr and all(
                   ("  %s " % b) in run.stderr for b in ("econ", "stats")),
               run.stderr[:300])
        # slim-corpus.py: a book as a folder and a book as a zip download,
        # slimmed, give the census the same totals as the originals.
        slimmer = os.path.join(os.path.dirname(here), "util", "slim-corpus.py")
        books = os.path.join(tmp, "books")
        os.makedirs(os.path.join(books, "econ"))
        os.makedirs(os.path.join(books, "stats"))
        for name in names[:2]:
            shutil.copy(os.path.join(fixtures, name), os.path.join(books, "econ"))
        shutil.copy(os.path.join(fixtures, names[2]), os.path.join(books, "stats"))
        import zipfile
        with zipfile.ZipFile(os.path.join(tmp, "more.zip"), "w") as zf:
            zf.write(os.path.join(fixtures, names[2]), "More/" + names[2])
        shutil.move(os.path.join(tmp, "more.zip"), books)
        slim_zip = os.path.join(tmp, "slim.zip")
        made = subprocess.run([sys.executable, slimmer, books, slim_zip],
                              capture_output=True, text=True)
        slim_dir = os.path.join(tmp, "slim")
        parts = set()
        if made.returncode == 0:
            with zipfile.ZipFile(slim_zip) as zf:
                zf.extractall(slim_dir)
            for dirpath, _, files in os.walk(slim_dir):
                for f in files:
                    with zipfile.ZipFile(os.path.join(dirpath, f)) as docx:
                        parts.update(docx.namelist())
        yield ("slim-corpus.py keeps each document.xml and nothing else, a "
               "zipped book included", made.returncode == 0
               and parts == {"word/document.xml"}
               and os.path.isdir(os.path.join(slim_dir, "more.zip".replace(".zip", ""))),
               made.stdout[-200:] + made.stderr[-200:])

        def totals(where):
            err = subprocess.run([sys.executable, script, where],
                                 capture_output=True, text=True).stderr
            return {line.split()[0]: line.split()[1:] for line in err.splitlines()
                    if line.startswith("  ") and "files" in line}
        before, after = totals(books), totals(slim_dir)
        yield ("the census gives a slim copy the same totals book by book",
               bool(before) and all(after.get(b) == v for b, v in before.items())
               and after.get("more", [None])[2:] == before.get("stats", [None])[2:],
               "%s | %s" % (before, after))
        missing = subprocess.run([sys.executable, slimmer,
                                  os.path.join(tmp, "nowhere"),
                                  os.path.join(tmp, "none.zip")],
                                 capture_output=True, text=True)
        yield ("slim-corpus.py names a missing folder and writes no zip",
               missing.returncode == 1 and "no such folder" in missing.stdout
               and not os.path.exists(os.path.join(tmp, "none.zip")),
               missing.stdout[-200:])
        helped = subprocess.run([sys.executable, script, "--help"],
                                capture_output=True, text=True)
        yield ("--help prints the usage and reads no file",
               helped.returncode == 0 and "Usage:" in helped.stdout
               and not helped.stderr, helped.stderr[-200:])


def main():
    failures = 0
    for name, ok, detail in (list(key_checks()) + list(pandoc_checks())
                             + list(script_checks()) + list(part_checks())):
        if ok:
            print("  ok    %s" % name)
        else:
            failures += 1
            print("  FAIL  %s" % name)
            if detail:
                print("          %s" % detail)
    for name, expect, rows in CASES:
        tbl = table(rows)
        kind, ev, _, _ = tc.classify(tbl)
        got = tc.guess(tbl, kind, ev)
        if got == expect:
            print("  ok    %s" % name)
        else:
            failures += 1
            print("  FAIL  %s" % name)
            print("          kind=%s guess=%s, expected %s" % (kind, got, expect))
            print("          evidence: %s" % "; ".join(ev))
    total = len(CASES) + sum(1 for _ in key_checks()) + \
        sum(1 for _ in pandoc_checks()) + sum(1 for _ in script_checks()) + \
        sum(1 for _ in part_checks())
    print("")
    if failures:
        print("%d of %d census checks failed." % (failures, total),
              file=sys.stderr)
        return 1
    print("all %d census checks passed" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
