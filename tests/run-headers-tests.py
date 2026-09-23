#!/usr/bin/env python3
"""
run-headers-tests.py -- check the table-headers pre-pass end to end.

    python3 tests/run-headers-tests.py

Builds small .docx files as OOXML, runs bin/table-headers.py over them
the way convert.py does, and reads back what it wrote. Needs nothing but
the standard library.

WHY THESE EXIST

The pre-pass is the first thing in the pipeline that reads a file a
person wrote by hand and decides what to do with it. Every rule about that
file -- which values it accepts, what a blank means, what happens to a row
whose key matches nothing -- is a rule about someone's work surviving,
and the failure mode for each is silent. So each is pinned here, and the
unmatched-key case in particular is checked for the exit status and not
just the report, because the exit status is what stops the run.

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

import csv
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, os.pardir, "bin", "table-headers.py")

W = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
     'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')


# ---------------------------------------------------------------------------
# Building documents
# ---------------------------------------------------------------------------

def cell(text, bold=False, span=1, inner=None):
    pr = "<w:tcPr>" + ('<w:gridSpan w:val="%d"/>' % span if span > 1 else "") + "</w:tcPr>"
    rpr = "<w:rPr><w:b/></w:rPr>" if bold else ""
    body = "<w:p><w:r>%s<w:t xml:space=\"preserve\">%s</w:t></w:r></w:p>" % (rpr, text)
    if inner:
        body = inner + "<w:p/>"
    return "<w:tc>%s%s</w:tc>" % (pr, body)


def row(cells, header=False):
    pr = "<w:trPr><w:tblHeader/></w:trPr>" if header else ""
    return "<w:tr>%s%s</w:tr>" % (pr, "".join(cells))


def table(rows):
    """A w:tbl with a w:tblGrid, which Word always writes and Pandoc's
    reader relies on for the column count: without it a table whose
    first row is one spanning cell reads as one column wide."""
    import re
    width = 0
    for row in rows:
        cells = re.findall(r"<w:tc>(.*?)</w:tc>", row, re.S)
        spans = sum(int(m) for m in re.findall(r'w:gridSpan w:val="(\d+)"', row))
        plain = sum(1 for c in cells if "gridSpan" not in c)
        width = max(width, spans + plain)
    grid = "<w:tblGrid>%s</w:tblGrid>" % ('<w:gridCol w:w="2400"/>' * width)
    return "<w:tbl><w:tblPr/>%s%s</w:tbl>" % (grid, "".join(rows))


def para(text):
    return "<w:p><w:r><w:t xml:space=\"preserve\">%s</w:t></w:r></w:p>" % text


def docx(path, blocks):
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document %s><w:body>%s<w:sectPr/></w:body></w:document>'
           % (W, "".join(blocks)))
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
          '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)


CONTINGENCY = table([
    row([cell(""), cell("Speeding"), cell("No speeding")], header=True),
    row([cell("Phone"), cell("25"), cell("280")]),
    row([cell("No phone"), cell("45"), cell("405")]),
])
TITLED = table([
    row([cell("The Message Triangle", span=3)]),
    row([cell("Element", bold=True), cell("Focus", bold=True), cell("Example", bold=True)]),
    row([cell("Purpose"), cell("The core idea"), cell("We request approval")]),
    row([cell("Clarity"), cell("How simply stated"), cell("The change reduces time")]),
])
GRID = table([
    row([cell("1.5"), cell("2.4"), cell("3.6")]),
    row([cell("3.5"), cell("2.5"), cell("1.8")]),
    row([cell("2.6"), cell("1.6"), cell("2.2")]),
])
# Two rows, so it is a data table and not a single-cell code box, which
# the census rightly leaves out.
INNER = table([row([cell("Code", bold=True)]), row([cell("print(x)")])])
BANDED = table([
    row([cell("Part"), cell("Purpose"), cell("Length")], header=True),
    row([cell("Front matter", bold=True, span=3)]),
    row([cell("Title page"), cell("Identifies the report"), cell("1")]),
    row([cell("Abstract"), cell("Summarizes it"), cell("1")]),
    row([cell("Body", bold=True, span=3)]),
    row([cell("Introduction"), cell("States the problem"), cell("2")]),
    row([cell("Methods"), cell("Says what was done"), cell("3")]),
])
GROUPED = table([
    row([cell("Australia", bold=True), cell("2011", bold=True), cell("2012", bold=True)]),
    row([cell("Real GDP per capita"), cell("2.3%"), cell("1.5%")]),
    row([cell("Real GDP per hour"), cell("1.7%"), cell("-0.1%")]),
    row([cell("Belgium", bold=True), cell("2011", bold=True), cell("2012", bold=True)]),
    row([cell("Real GDP per capita"), cell("0.9"), cell("-0.6")]),
    row([cell("Real GDP per hour"), cell("-0.5"), cell("-0.3")]),
])
NESTED = table([
    row([cell("Key", bold=True), cell("Value", bold=True)]),
    row([cell("133"), cell("", inner=INNER)]),
])


def run(workdir, *extra):
    files = sorted(f for f in os.listdir(workdir) if f.endswith(".docx"))
    proc = subprocess.run(
        [sys.executable, TOOL] + files + ["--sidecar", "table-headers.csv",
                                          "--new", "table-headers-new.csv",
                                          "--report", "table-headers-report.csv",
                                          "--resolved", "resolved.json"]
        + list(extra),
        cwd=workdir, capture_output=True, text=True)
    return proc.returncode, proc.stderr


def read(workdir, name):
    path = os.path.join(workdir, name)
    if not os.path.exists(path):
        return None
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------

def checks(workdir):
    docx(os.path.join(workdir, "a.docx"), [para("Table 3.1"), CONTINGENCY,
                                           para("Some prose."), TITLED,
                                           para("Table 3.3"), GRID])
    docx(os.path.join(workdir, "b.docx"), [para("Table 7.3"), NESTED,
                                           para("Table 8.1"), BANDED,
                                           para("Table 9.1"), GROUPED])

    # First run: nothing declared, everything new.
    code, err = run(workdir)
    report = read(workdir, "table-headers-report.csv")
    new = read(workdir, "table-headers-new.csv")
    yield "a first run exits 0", code == 0, err
    yield "the report has one row per data table", report is not None and len(report) == 7, \
        report and len(report)
    yield "every table is new on a first run", all(r["status"] in ("new", "needs-source") for r in report), \
        [r["status"] for r in report]
    yield "the new file has the same rows in sidecar form", new is not None and len(new) == 7, ""
    yield "the new file's columns are the sidecar's", new and list(new[0].keys()) == [
        "key", "headers", "split-at", "caption-rows", "part-captions", "source", "label", "preview"], \
        new and list(new[0].keys())
    by_label = {r["label"]: r for r in report}
    yield "labels come from the prose", "Table 3.1" in by_label and "Table 7.3" in by_label, \
        sorted(by_label)
    yield "the contingency table is guessed both", by_label["Table 3.1"]["guess"] == "both", \
        by_label["Table 3.1"]["guess"]
    titled = [r for r in new if r["preview"].startswith("The Message Triangle")]
    yield "a merged title row is written as caption-rows=1", titled and titled[0]["caption-rows"] == "1", \
        titled and titled[0]["caption-rows"]
    grid = by_label["Table 3.3"]
    yield "a bare grid is needs-source, fixed in Word", grid["status"] == "needs-source" and "in Word" in grid["note"], grid["status"]
    inner = [r for r in report if r["label"].startswith("inside")]
    yield "a nested table borrows its container's label", inner and inner[0]["label"] == "inside Table 7.3", \
        [r["label"] for r in report]
    yield "keys are full digests", all(len(r["key"]) == 64 for r in report), ""
    banded = [r for r in new if r["label"] == "Table 8.1"]
    yield "bands below a marked header row are written as split-at", \
        banded and banded[0]["split-at"] == "2,5", banded and banded[0]["split-at"]
    yield "and the guess is taken part by part with the header row in place", \
        banded and banded[0]["headers"] == "both", banded and banded[0]["headers"]
    grouped = [r for r in new if r["label"] == "Table 9.1"]
    yield "a repeated header row with a group name in its corner is inferred as a split", \
        grouped and grouped[0]["split-at"] == "1,4", grouped and grouped[0]["split-at"]
    yield "and its parts are guessed with their own header rows in place", \
        grouped and grouped[0]["headers"] == "both", grouped and grouped[0]["headers"]
    yield "a banded table's report row says so", \
        any("split-at=2,5" in r["note"] and "inferred" in r["note"]
            for r in report if r["label"] == "Table 8.1"), ""

    # Adopt the new rows as the sidecar, then edit like a remediator.
    shutil.move(os.path.join(workdir, "table-headers-new.csv"),
                os.path.join(workdir, "table-headers.csv"))
    rows = [dict(r) for r in new]
    k = {r["preview"]: r for r in rows}
    k[" | Speeding | No speeding"]["headers"] = "first-row"          # override
    k["The Message Triangle | The Message Triangle | The Message Triangle"]["headers"] = "manual"
    k["1.5 | 2.4 | 3.6"]["headers"] = "grid"                          # alias
    k["Key | Value"]["headers"] = "bogus"                             # unknown
    k["Code"]["headers"] = ""                                         # cleared
    k["The Message Triangle | The Message Triangle | The Message Triangle"]["caption-rows"] = ""  # inferred, removed
    k[" | Speeding | No speeding"]["caption-rows"] = "1"              # declared by hand
    cols = list(new[0].keys())
    with open(os.path.join(workdir, "table-headers.csv"), "w", newline="", encoding="utf-8") as h:
        w = csv.writer(h)
        w.writerow(cols)
        for r in rows[:2]:
            w.writerow([r[c] for c in cols])
        w.writerow(cols)                       # a pasted-in header row, mid-file
        for r in rows[2:]:
            w.writerow([r[c] for c in cols])

    code, err = run(workdir)
    report = read(workdir, "table-headers-report.csv")
    status = {r["preview"]: r for r in report}
    yield "a run with a complete sidecar exits 0", code == 0, err
    yield "an unknown value is warned about once", err.count("bogus") == 1, err
    yield "no new file when every table has a row", read(workdir, "table-headers-new.csv") is None, ""
    yield "an override is declared with the sidecar as supplier", \
        status[" | Speeding | No speeding"]["status"] == "declared" and \
        status[" | Speeding | No speeding"]["declared"] == "first-row" and \
        status[" | Speeding | No speeding"]["supplier"] == "sidecar", status[" | Speeding | No speeding"]
    yield "manual is its own status", \
        status["The Message Triangle | The Message Triangle | The Message Triangle"]["status"] == "manual", ""
    yield "an alias is resolved to the canonical value", status["1.5 | 2.4 | 3.6"]["declared"] == "none", \
        status["1.5 | 2.4 | 3.6"]["declared"]
    yield "an unknown value reads as blank", status["Key | Value"]["status"] == "blank", \
        status["Key | Value"]["status"]
    yield "a cleared cell is blank and the guess is still reported", \
        status["Code"]["status"] == "blank" and status["Code"]["guess"] == "first-row", \
        status["Code"]
    yield "a header row pasted mid-file is skipped", len(report) == 7, len(report)
    import json
    with open(os.path.join(workdir, "resolved.json"), encoding="utf-8") as h:
        resolved = json.load(h)
    entries = {e["first"]: e for doc in resolved.values() for e in doc}
    yield "an inferred caption-rows the remediator removed is not applied", \
        entries["The Message Triangle"]["caption_rows"] == [], entries["The Message Triangle"]
    yield "a caption-rows declared by hand reaches the resolved file", \
        entries[""]["caption_rows"] == [1] if "" in entries else False, \
        {k: v["caption_rows"] for k, v in entries.items()}
    yield "the resolved file carries the value in effect", \
        entries[""]["headers"] == "first-row" if "" in entries else False, ""

    # A stale key stops the run, after writing the report.
    with open(os.path.join(workdir, "table-headers.csv"), "a", newline="", encoding="utf-8") as h:
        csv.writer(h).writerow(["0" * 64, "both", "", "", "", "gone.docx", "Table 9.9", "not here"])
    code, err = run(workdir)
    report = read(workdir, "table-headers-report.csv")
    stale = [r for r in report if r["status"] == "unmatched"]
    yield "a sidecar row matching no table exits 1", code == 1, err
    yield "the report is still written and names the unmatched row", \
        len(stale) == 1 and stale[0]["label"] == "Table 9.9", [r["status"] for r in report]
    yield "the error names the report", "table-headers-report.csv" in err, err


def main():
    workdir = tempfile.mkdtemp(prefix="headers-test-")
    failures = total = 0
    try:
        for name, ok, detail in checks(workdir):
            total += 1
            if ok:
                print("  ok    %s" % name)
            else:
                failures += 1
                print("  FAIL  %s" % name)
                if detail:
                    print("          %s" % str(detail)[:200])
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    print("")
    if failures:
        print("%d of %d pre-pass checks failed." % (failures, total), file=sys.stderr)
        return 1
    print("all %d pre-pass checks passed" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
