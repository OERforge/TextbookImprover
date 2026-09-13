#!/usr/bin/env python3
"""
run-census-tests.py -- check the sidecar guess in util/table-census.py.

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
pin behaviour the rule must NOT have: a table of descriptions and a table
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

import importlib.util
import os
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
CENSUS = os.path.join(HERE, os.pardir, "util", "table-census.py")

spec = importlib.util.spec_from_file_location("table_census", CENSUS)
tc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tc)

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


def main():
    failures = 0
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
    print("")
    if failures:
        print("%d of %d census checks failed." % (failures, len(CASES)),
              file=sys.stderr)
        return 1
    print("all %d census checks passed" % len(CASES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
