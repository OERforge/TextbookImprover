#!/usr/bin/env python3
"""
table-headers.py -- the table-headers pre-pass: read the sidecar, guess the
rest, write the report.

    python3 bin/table-headers.py *.docx \\
        --sidecar table-headers.csv \\
        --new table-headers-new.csv \\
        --report table-headers-report.csv

Runs before Pandoc, on the .docx files themselves, because the evidence the
guess reads -- repeat-header rows, bold, shading -- does not survive
Pandoc's reader. For every data table it computes the sidecar key, asks the
sidecar what a person declared, asks lib/tablecensus what the file
suggests, and records both.

Three files share the name and do different jobs:

  table-headers.csv         the sidecar. Human-owned; read here, never written.
  table-headers-new.csv     one prefilled row for every table the sidecar has
                            no row for. Written when there are any, meant to
                            be pasted into the sidecar. Removed when there
                            are none, so the file existing is the signal.
  table-headers-report.csv  what happened to every table this run. Written
                            every run, never edited.

With --resolved, also writes a JSON file for the filter: for each source
document, the value in effect for each data table -- the sidecar's where
one was declared, the guess otherwise -- with the table's position among
all the document's tables, its shape, and its first cell, so the filter
can confirm it is applying the value to the table it was computed for.

A sidecar row whose key matches no table is an error, and the run stops
after writing the report: a correction that silently does not apply is
worse than a failed run, because it destroys work invisibly. The report
lists the unmatched rows beside the tables no row claimed, so a person can
see "that is my row, the table changed."

A `headers` value the reader does not recognise is warned about once and
treated as blank. That is what lets `manual`, `list`, and `caption-rows` be
declared before anything acts on them, and what keeps a sidecar written
against a newer version from losing work under an older one.

Exit status: 0; 1 when a sidecar row matched nothing; 2 for usage.

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
import csv
import json
import os
import sys
import zipfile
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import tablecensus as tc  # noqa: E402

# The values a sidecar may carry, and what each means to the pipeline.
ALIASES = {"matrix": "both", "grid": "none"}
ACTING = {"first-row", "first-column", "both", "none"}
RESERVED = {"manual", "list"}
KNOWN = ACTING | RESERVED

SIDECAR_COLUMNS = ["key", "headers", "split-at", "caption-rows",
                   "part-captions", "source", "label", "preview"]
REPORT_COLUMNS = ["key", "source", "label", "preview", "declared", "supplier",
                  "guess", "reason", "status", "note"]


# ---------------------------------------------------------------------------
# Reading the sidecar
# ---------------------------------------------------------------------------

def read_sidecar(path, warn):
    """Rows keyed on the key column. Header rows anywhere are skipped, so a
    file assembled by pasting table-headers-new.csv in repeatedly still
    reads."""
    rows = {}
    if not path or not os.path.exists(path):
        return rows
    unknown = set()
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        for raw in reader:
            if not raw or not raw[0].strip():
                continue
            if raw[0].strip().lower() == "key":
                continue
            raw = raw + [""] * (len(SIDECAR_COLUMNS) - len(raw))
            row = dict(zip(SIDECAR_COLUMNS, (v.strip() for v in raw)))
            value = row["headers"].lower()
            value = ALIASES.get(value, value)
            if value and value not in KNOWN:
                unknown.add(row["headers"])
                value = ""
            row["headers"] = value
            if row["key"] in rows:
                warn("%s: key %s appears more than once; the last row wins"
                     % (path, row["key"][:12]))
            rows[row["key"]] = row
    for value in sorted(unknown):
        warn("%s: headers value %r is not one this version understands; "
             "treated as blank" % (path, value))
    return rows


# ---------------------------------------------------------------------------
# Looking at one document
# ---------------------------------------------------------------------------

def preview_of(grid):
    cells = [c.text.replace("\n", " ") for c in grid[0][:3]] if grid else []
    text = " | ".join(t[:24] for t in cells)
    return text


def label_for(body, tbl, depth, parents):
    if depth == 0:
        return tc.nearby_label(body, tbl)
    outer = parents.get(id(tbl))
    label = tc.nearby_label(body, outer) if outer is not None else ""
    return ("inside %s" % label) if label else ""


def inferred_caption_rows(grid):
    """A merged full-width first row with text is a title, not a header
    row: caption-rows=1, inferred, so the remediator can see and remove
    it."""
    if not grid or max(len(r) for r in grid) < 2:
        return ""
    first = grid[0]
    if tc.is_full_width_band(first) and first[0].text:
        return "1"
    return ""


def no_header_text(grid):
    """Every cell is a value: nothing in the table could serve as a header,
    so no sidecar value can help and the fix belongs in Word."""
    cells = [c for r in grid for c in r]
    return bool(cells) and tc.mostly_values(cells, ratio=1.0)


def tables_in(path):
    """Every data table in the document, with everything the sidecar and
    the report want to know about it."""
    try:
        body = tc.read_body(path)
    except (KeyError, OSError, zipfile.BadZipFile, ET.ParseError) as exc:
        raise RuntimeError("%s: cannot read (%s)" % (path, exc))
    if body is None:
        return []
    parents = {}
    for outer, depth in tc.all_tables(body):
        if depth == 0:
            for inner in outer.findall(".//" + tc.q("tbl")):
                parents[id(inner)] = outer
    keys = {}
    found = []
    for index, (tbl, depth) in enumerate(tc.all_tables(body)):
        kind, ev, nrows, ncols = tc.classify(tbl)
        value, reason = tc.explain(tbl, kind, ev)
        if value is None:
            continue
        grid = tc.build_grid(tbl)
        first = grid[0][0].text if grid and grid[0] else ""
        found.append({
            "key": tc.table_key(tbl, keys),
            "rows": nrows,
            "cols": ncols,
            "first": " ".join(first.split())[:40],
            "source": os.path.basename(path),
            "index": index,
            "label": label_for(body, tbl, depth, parents),
            "preview": preview_of(grid),
            "guess": "" if value == "unknown" else value,
            "reason": reason,
            "caption-rows": inferred_caption_rows(grid),
            "needs-word": value == "none" and no_header_text(grid),
            "summary-row": "trailing row with no label" in reason,
        })
    return found


# ---------------------------------------------------------------------------
# Deciding
# ---------------------------------------------------------------------------

def caption_rows_in_effect(info, row):
    """The rows to fold into the caption: the sidecar's list where a row
    exists (a blank there means none, so a person can remove the inferred
    one), else the pre-pass's inference for a table with no row yet."""
    text = row["caption-rows"] if row is not None else info["caption-rows"]
    rows = []
    for part in (text or "").split(","):
        part = part.strip()
        if part.isdigit() and int(part) > 0:
            rows.append(int(part))
    return rows


def in_effect(info, row):
    """The value the filter should apply: the sidecar's if it declared
    one of the acting values, else the guess. manual, list, and a blank
    all mean "as Pandoc gives it", which is the empty string here."""
    if row is not None and row["headers"] in ACTING:
        return row["headers"]
    if row is not None and row["headers"] in RESERVED:
        return ""
    return info["guess"]


def decide(info, row):
    """(declared, supplier, status, note) for one table."""
    notes = []
    if info["summary-row"]:
        notes.append("the trailing row with no label keeps an empty "
                     "header cell; see the roadmap")
    if not info["guess"]:
        notes.append(info["reason"])
    if row is None:
        status = "new"
        declared, supplier = "", ("guess" if info["guess"] else "")
    else:
        declared = row["headers"]
        if declared == "manual":
            status, supplier = "manual", "sidecar"
        elif declared:
            status, supplier = "declared", "sidecar"
        else:
            status, supplier = "blank", ("guess" if info["guess"] else "")
    if status in ("new", "blank") and info["needs-word"]:
        status = "needs-word"
        notes.append("no cell in this table could serve as a header, so "
                     "no value can help; author headers in Word")
    return declared, supplier, status, "; ".join(notes)


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def write_csv(path, columns, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([row.get(c, "") for c in columns])


def remove_if_present(path):
    if path and os.path.exists(path):
        os.remove(path)


def main():
    ap = argparse.ArgumentParser(
        description="Table-headers pre-pass: keys, guesses, sidecar, report.")
    ap.add_argument("files", nargs="+", help=".docx files")
    ap.add_argument("--sidecar", default="table-headers.csv",
                    help="the sidecar to read (default table-headers.csv)")
    ap.add_argument("--new", dest="new_path", default="table-headers-new.csv",
                    help="where prefilled rows for unclaimed tables go")
    ap.add_argument("--report", default="table-headers-report.csv",
                    help="where the per-table report goes")
    ap.add_argument("--resolved", default=None,
                    help="JSON of the value in effect per table, for the filter")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    def warn(message):
        print("table-headers: " + message, file=sys.stderr)

    sidecar = read_sidecar(args.sidecar, warn)
    tables = []
    for path in args.files:
        try:
            tables.extend(tables_in(path))
        except RuntimeError as exc:
            warn(str(exc))

    report, new_rows = [], []
    resolved = {}
    claimed = set()
    for info in tables:
        row = sidecar.get(info["key"])
        if row is not None:
            claimed.add(info["key"])
        declared, supplier, status, note = decide(info, row)
        # Keyed by stem, not filename: the filter runs on the JSON
        # intermediate named after the .docx, and knows only the stem.
        caption_rows = caption_rows_in_effect(info, row)
        resolved.setdefault(os.path.splitext(info["source"])[0], []).append({
            "index": info["index"], "headers": in_effect(info, row),
            "caption_rows": caption_rows,
            "rows": info["rows"], "cols": info["cols"], "first": info["first"],
        })
        if caption_rows:
            note = (note + "; " if note else "") + (
                "caption-rows=%s: row%s folded into the caption"
                % (",".join(str(n) for n in caption_rows),
                   "s" if len(caption_rows) > 1 else ""))
            if row is None:
                note += " (inferred: a merged full-width first row is a title)"
        report.append({
            "key": info["key"], "source": info["source"],
            "label": info["label"], "preview": info["preview"],
            "declared": declared, "supplier": supplier,
            "guess": info["guess"], "reason": info["reason"],
            "status": status, "note": note,
        })
        if row is None:
            new_rows.append({
                "key": info["key"], "headers": info["guess"],
                "split-at": "", "caption-rows": info["caption-rows"],
                "part-captions": "", "source": info["source"],
                "label": info["label"], "preview": info["preview"],
            })

    unmatched = [r for k, r in sidecar.items() if k not in claimed]
    for row in unmatched:
        report.append({
            "key": row["key"], "source": row["source"], "label": row["label"],
            "preview": row["preview"], "declared": row["headers"],
            "supplier": "sidecar", "guess": "", "reason": "",
            "status": "unmatched",
            "note": "this sidecar row matches no table in the run; if the "
                    "table changed, its new row is in %s"
                    % os.path.basename(args.new_path),
        })

    if args.resolved:
        with open(args.resolved, "w", encoding="utf-8") as handle:
            json.dump(resolved, handle, indent=1, sort_keys=True)
    if report:
        write_csv(args.report, REPORT_COLUMNS, report)
    else:
        remove_if_present(args.report)
    if new_rows:
        write_csv(args.new_path, SIDECAR_COLUMNS, new_rows)
    else:
        remove_if_present(args.new_path)

    counts = {}
    for row in report:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    summary = ", ".join("%d %s" % (n, s) for s, n in sorted(counts.items()))
    print("table-headers: %d data table(s): %s" % (len(tables), summary),
          file=sys.stderr)
    if new_rows:
        print("table-headers: %d table(s) have no sidecar row; prefilled "
              "rows are in %s -- paste them into %s"
              % (len(new_rows), args.new_path, args.sidecar), file=sys.stderr)
    if unmatched:
        print("table-headers: ERROR: %d sidecar row(s) match no table. The "
              "run stops here rather than silently discard a correction; "
              "see the 'unmatched' rows in %s" % (len(unmatched), args.report),
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
