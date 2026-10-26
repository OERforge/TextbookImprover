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

A sidecar row whose key matches no table is warned about, not silently
dropped: a correction that silently does not apply destroys work
invisibly. The run goes on, since a table edited in its source (a Word
file remediated and then edited, say) changes its key, and stopping every
run on that helps no one. The unmatched rows go to a file of their own,
the sidecar without them to a sample beside it, ready to adopt, and the
report lists the unmatched rows beside the tables no row claimed, so a
person can see "that is my row, the table changed."

`layout` says a table only lines things up, as a page says with
role="presentation": the filter asks no caption of it, and every target
writes it as one. A table the page marks so is listed with that value,
the page's own declaration, as a table whose <th> cells declare its
headers is; a sidecar row naming its headers makes it a data table.

A `headers` value the reader does not recognize is warned about once and
treated as blank. That is what lets `manual`, `list`, and `caption-rows` be
declared before anything acts on them, and what keeps a sidecar written
against a newer version from losing work under an older one.

Exit status: 0; 1 when a sidecar row matched nothing; 2 for usage, or a
sidecar that isn't UTF-8 and can't be rewritten as UTF-8 (the one Excel's
plain "CSV" saves, in Windows-1252 or Mac OS Roman, is rewritten first).

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
import sidecars  # noqa: E402
import tablecensus as tc  # noqa: E402

# The values a sidecar may carry, and what each means to the pipeline:
# where a data table's headers are (none, a data table with nothing to
# declare), or layout, a table that only lines things up.
ALIASES = {"matrix": "both", "grid": "none"}
ACTING = {"first-row", "first-column", "both", "none", "layout"}
RESERVED = {"manual", "list"}
KNOWN = ACTING | RESERVED

SIDECAR_COLUMNS = ["key", "headers", "split-at", "caption-rows",
                   "part-captions", "source", "label", "preview",
                   "drafted-by", "reviewed"]
REPORT_COLUMNS = ["key", "source", "label", "preview", "declared", "supplier",
                  "guess", "reason", "status", "note"]


# ---------------------------------------------------------------------------
# Reading the sidecar
# ---------------------------------------------------------------------------

def has_review_columns(path):
    """Whether a sidecar has drafted-by and reviewed: a header row naming
    them, or a row long enough to hold them. A sidecar from before them
    has neither; an absent or empty one has nothing to bring up to date."""
    if not path or not os.path.exists(path):
        return True
    rows = False
    with open(path, newline="", encoding=sidecars.CSV_ENCODING) as handle:
        for raw in csv.reader(sidecars.csv_lines(handle)):
            if not raw or not raw[0].strip():
                continue
            if raw[0].strip().lower() == "key":
                if "drafted-by" in (c.strip().lower() for c in raw):
                    return True
                continue
            rows = True
            if len(raw) >= len(SIDECAR_COLUMNS):
                return True
    return not rows


def read_sidecar(path, warn):
    """Rows keyed on the key column. Header rows anywhere are skipped, so a
    file assembled by pasting table-headers-new.csv in repeatedly still
    reads."""
    rows = {}
    if not path or not os.path.exists(path):
        return rows
    unknown = set()
    with open(path, newline="", encoding=sidecars.CSV_ENCODING) as handle:
        reader = csv.reader(sidecars.csv_lines(handle))
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
            # A repeated key matters only when the rows disagree: pasting a
            # prefilled file in twice repeats rows that say the same thing.
            decisions = ("headers", "split-at", "caption-rows", "part-captions")
            if row["key"] in rows and any(rows[row["key"]][c] != row[c]
                                          for c in decisions):
                warn("%s: key %s appears more than once, with different "
                     "decisions; the last row wins" % (path, row["key"][:12]))
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










rows_list = tc.rows_list
band_rows = tc.band_rows
repeated_header_rows = tc.repeated_header_rows
inferred_structure = tc.inferred_structure


def no_header_text(grid):
    """Every cell is a value: nothing in the table could serve as a header,
    so no sidecar value can help and the fix belongs in the source."""
    cells = [c for r in grid for c in r]
    return bool(cells) and tc.mostly_values(cells, ratio=1.0)


MARKER = "data-th-marker"
CAPTION_ROWS = "data-caption-rows"
SPLIT_AT = "data-split-at"
SPLIT_AT_DECLARED = "data-split-at-declared"
PART_CAPTIONS = "data-part-captions"


def pandoc_tables(node, out):
    """Every Table in a Pandoc document, outer before inner."""
    if isinstance(node, dict):
        if node.get("t") == "Table":
            out.append(node)
        for value in node.values():
            pandoc_tables(value, out)
    elif isinstance(node, list):
        for value in node:
            pandoc_tables(value, out)
    return out


def tables_in_json(path):
    """The data tables of a Pandoc intermediate, for a source whose
    evidence survives Pandoc's reader: an HTML page's <th> cells, which
    html-source.lua turned into a marker, and its bold, which is Strong;
    a LaTeX page's tagging declaration, which latex-source.lua did.
    The value in effect is written back into the intermediate as the
    table's marker (see apply_to_json), which the filter obeys, so no
    position has to be matched afterwards."""
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    stem = os.path.splitext(os.path.basename(path))[0]
    found = []
    for index, table in enumerate(pandoc_tables(doc["blocks"], [])):
        attributes = dict(table["c"][0][2])
        view = tc.view_from_pandoc(table)
        kind, ev, nrows, ncols = tc.classify(view)
        source = attributes.get(MARKER)
        # A layout table the page marks so, which html-source.lua declared
        # (role="presentation", or "none" made "presentation"), or
        # latex-source.lua did (a LaTeX page's table/tagging=div): listed, so
        # a person sees it and a sidecar row can make it a data table, with
        # nothing guessed. Not one the census counts no table at all, as it
        # counts an empty one, one cell, or pictures alone, which the filter
        # makes a figure: no row would change what it is.
        if source == "layout" or attributes.get("role") in ("presentation", "none"):
            if tc.guess_table(view, kind, ev)[0] is None:
                continue
            source = "layout"
            value, reason, inferred = source, (
                "the page marks it a layout table (role=\"presentation\")"), ("", "")
        else:
            value, reason, inferred = tc.guess_table(view, kind, ev)
        if source and source != "layout":
            value, reason = source, "the page marks its header cells (<th>)"
        if value is None:
            continue
        grid = view.grid
        first = grid[0][0].text if grid and grid[0] else ""
        caption = tc._stringify(table["c"][1][1]) if table["c"][1] else ""
        found.append({
            "key": tc.key_from_pandoc(table), "rows": nrows, "cols": ncols,
            "first": " ".join(first.split())[:40],
            # A LaTeX page's table carries its place in the book's files;
            # its page is named, since its file is the chapter's own.
            "source": stem + (".tex" if attributes.get("data-latex-table") else ".html"),
            "index": index, "latex": attributes.get("data-latex-table", ""),
            "label": " ".join(caption.split())[:60],
            "preview": preview_of(grid),
            "guess": "" if value == "unknown" else value,
            "reason": reason, "caption-rows": inferred[0],
            "split-at": inferred[1],
            "anchors": [],
            "needs-source": value == "none" and no_header_text(grid),
            "summary-row": "trailing row with no label" in reason,
            "json": path, "from-source": bool(source),
        })
    return found


def apply_to_json(infos):
    """Write each HTML table's value in effect into its intermediate as
    its marker, for the filter. The intermediate is read from the page
    again every run, so what the page itself said is never lost."""
    by_path = {}
    for info in infos:
        by_path.setdefault(info["json"], []).append(info)
    for path, entries in by_path.items():
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        tables = pandoc_tables(doc["blocks"], [])
        for info in entries:
            attr = tables[info["index"]]["c"][0]
            pairs = [p for p in attr[2] if p[0] not in
                     (MARKER, CAPTION_ROWS, SPLIT_AT, SPLIT_AT_DECLARED, PART_CAPTIONS)]
            if info["in-effect"]:
                pairs.append([MARKER, info["in-effect"]])
            # Title rows and bands, as the filter reads them for a Word
            # table from the resolved file: row numbers, 1-based, counted
            # over head, bodies, and foot in that order.
            for name, rows in ((CAPTION_ROWS, info["caption-rows-in-effect"]),
                               (SPLIT_AT, info["split-at-in-effect"])):
                if rows:
                    pairs.append([name, ",".join(str(r) for r in rows)])
            # Whether a person named those split rows, or the guess did.
            if info.get("split-at-declared"):
                pairs.append([SPLIT_AT_DECLARED, "1"])
            # A person's caption for each part, "|" between them, as the
            # sidecar's part-captions column has them.
            if info.get("part-captions-in-effect"):
                pairs.append([PART_CAPTIONS,
                              "|".join(info["part-captions-in-effect"])])
            attr[2] = pairs
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)


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
        value, reason, inferred = tc.guess_table(tbl, kind, ev)
        # The bookmarks JAWS reads as a table's headers are the author's
        # declaration, as <th> cells are a page's.
        jaws, mark = tc.jaws_declaration(tbl)
        if jaws:
            value, reason = jaws, f"the table's {mark} bookmark declares its headers (JAWS's bookmark convention)"
        anchors = tc.anchors_before(body, tbl) if depth == 0 else []
        # A box of one cell whose row Word's table look formats, as Word
        # formats a table it inserts, and no row is marked to repeat:
        # Pandoc's reader puts the row in the table's head, which the filter
        # would take for a header cell its source declares.
        look_head = (kind == "layout(single-cell)" and "tblLook:firstRow" in ev
                     and not tc.view(tbl).marked)
        if value is None and not anchors and not look_head:
            continue
        grid = tc.build_grid(tbl)
        first = grid[0][0].text if grid and grid[0] else ""
        if value is None:
            # One the census counts no table, one cell or pictures alone,
            # isn't listed, but the bookmarks before it go to the filter as
            # a listed table's do: a link to a boxed note, which is a table
            # of one cell, goes to them. So does a box's head that is Word's
            # table look's.
            found.append({"anchors-only": True, "rows": nrows, "cols": ncols,
                          "first": " ".join(first.split())[:40],
                          "source": os.path.basename(path), "index": index,
                          "anchors": anchors, "look-head": look_head})
            continue
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
            "caption-rows": inferred[0],
            "split-at": inferred[1],
            "anchors": anchors,
            "needs-source": value == "none" and no_header_text(grid),
            "summary-row": "trailing row with no label" in reason,
            "from-source": bool(jaws),
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




def split_in_effect(info, row):
    """The band rows to split at: the sidecar's where a row exists, else
    the inference. And the part captions, if a person wrote any."""
    if row is not None:
        parts = [c.strip() for c in row["part-captions"].split("|")] \
            if row["part-captions"].strip() else []
        return rows_list(row["split-at"]), parts
    return rows_list(info["split-at"]), []


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
    if status in ("new", "blank") and info["needs-source"]:
        status = "needs-source"
        notes.append("no cell in this table could serve as a header, so "
                     "no value can help; author headers "
                     + ("in Word" if info["source"].lower().endswith(".docx")
                        else "in the page, as <th> cells"))
    return declared, supplier, status, "; ".join(notes)


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def write_csv(path, columns, rows):
    with open(path, "w", newline="", encoding=sidecars.CSV_ENCODING) as handle:
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
    ap.add_argument("--resolved-html", default=None,
                    help="where to write the value in effect for each HTML page's tables, "
                         "with who decided it, for a remediated source")
    ap.add_argument("--resolved", default=None,
                    help="JSON of the value in effect per table, for the filter")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    def warn(message):
        print("table-headers: " + message, file=sys.stderr)

    said, why = sidecars.rewrite_as_utf8(args.sidecar) if args.sidecar else ([], None)
    if why:
        warn(why)
        return 2
    for line in said:
        warn(line)
    sidecar = read_sidecar(args.sidecar, warn)
    tables = []
    for path in args.files:
        try:
            tables.extend(tables_in_json(path) if path.endswith(".json")
                          else tables_in(path))
        except RuntimeError as exc:
            warn(str(exc))
    # A table that isn't listed, with bookmarks before it, or a box of one
    # cell whose head is Word's table look's: only those, for the filter,
    # and nothing in the reports.
    unlisted = [info for info in tables if info.get("anchors-only")]
    tables = [info for info in tables if not info.get("anchors-only")]

    report, new_rows = [], []
    resolved = {}
    for info in unlisted:
        resolved.setdefault(os.path.splitext(info["source"])[0], []).append({
            "index": info["index"], "headers": "", "caption_rows": [],
            "split_at": [], "part_captions": [], "split_at_declared": False,
            "rows": info["rows"], "cols": info["cols"], "first": info["first"],
            "anchors": info["anchors"], "supplier": "",
            "look_head": info.get("look-head", False),
        })
    resolved_html = {}
    claimed = set()
    layout = 0
    for info in tables:
        row = sidecar.get(info["key"])
        if row is not None:
            claimed.add(info["key"])
        layout += in_effect(info, row) == "layout"
        declared, supplier, status, note = decide(info, row)
        if info.get("from-source") and supplier == "guess":
            supplier = "source"
        if info.get("json"):
            info["in-effect"] = in_effect(info, row)
            info["caption-rows-in-effect"] = caption_rows_in_effect(info, row)
            info["split-at-in-effect"], info["part-captions-in-effect"] = \
                split_in_effect(info, row)
            info["split-at-declared"] = row is not None and bool(info["split-at-in-effect"])
        # Keyed by stem, not filename: the filter runs on the JSON
        # intermediate named after the .docx, and knows only the stem.
        caption_rows = caption_rows_in_effect(info, row)
        split_at, part_captions = split_in_effect(info, row)
        entry = {
            "index": info["index"], "headers": in_effect(info, row),
            "caption_rows": caption_rows,
            "split_at": split_at, "part_captions": part_captions,
            # A person's split rows, from the sidecar, which the filter names
            # when it can't split at one; it says nothing of the guess's.
            "split_at_declared": row is not None and bool(split_at),
            "rows": info["rows"], "cols": info["cols"], "first": info["first"],
            "anchors": info.get("anchors", []),
            # Who decided: "sidecar" for a person's row, "source" for the
            # file's own declaration, "guess" for the census. A remediated
            # source writes only what a person decided.
            "supplier": supplier,
            "latex": info.get("latex", ""),
        }
        if info.get("json"):
            # An HTML page's, for a remediated source only: the filter
            # reads the page's own marker, never this.
            resolved_html.setdefault(os.path.splitext(info["source"])[0], []).append(entry)
        if not info.get("json"):
            resolved.setdefault(os.path.splitext(info["source"])[0], []).append({
                "index": info["index"], "headers": in_effect(info, row),
                "caption_rows": caption_rows,
                "split_at": split_at, "part_captions": part_captions,
                "split_at_declared": row is not None and bool(split_at),
                "rows": info["rows"], "cols": info["cols"], "first": info["first"],
                "anchors": info.get("anchors", []),
                # Who decided: "sidecar" for a person's row, "source" for
                # the file's own declaration, "guess" for the census. A
                # remediated source writes only what a person decided.
                "supplier": supplier,
            })
        if split_at:
            note = (note + "; " if note else "") + (
                "split-at=%s: one table per band, each with the header row "
                "and the band as its caption"
                % ",".join(str(n) for n in split_at))
            if row is None:
                note += " (inferred: merged full-width rows below row 1 are bands)"
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
        # One row per key: a table that appears twice has one key and one
        # guess, and a second row would only make the pasted file warn.
        if row is None and info["key"] not in {r["key"] for r in new_rows}:
            new_rows.append({
                "key": info["key"], "headers": info["guess"],
                "split-at": info["split-at"],
                "caption-rows": info["caption-rows"],
                "part-captions": "", "source": info["source"],
                "label": info["label"], "preview": info["preview"],
                # The guess is TextbookImprover's; a person who checks it
                # fills in reviewed.
                "drafted-by": "TI" if info["guess"] else "", "reviewed": "",
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

    if args.resolved_html:
        with open(args.resolved_html, "w", encoding="utf-8") as handle:
            json.dump(resolved_html, handle, indent=1, sort_keys=True)
    if args.resolved:
        with open(args.resolved, "w", encoding="utf-8") as handle:
            json.dump(resolved, handle, indent=1, sort_keys=True)
    if report:
        apply_to_json([i for i in tables if i.get("json")])
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
    print("table-headers: %d data table(s)%s: %s"
          % (len(tables) - layout,
             " and %d layout table(s)" % layout if layout else "", summary),
          file=sys.stderr)
    if new_rows:
        print("table-headers: %d table(s) have no sidecar row; prefilled "
              "rows are in %s -- paste them into %s"
              % (len(new_rows), args.new_path, args.sidecar), file=sys.stderr)
    stem = (args.new_path[:-len("-new.csv")] if args.new_path.endswith("-new.csv")
            else os.path.splitext(args.new_path)[0])
    unmatched_path, sample_path = stem + "-unmatched.csv", stem + "-sample.csv"
    # A sidecar from before drafted-by and reviewed reads as a person's
    # decisions, but its rows were mostly pasted from the prefilled file,
    # TextbookImprover's guesses unchecked. The sample has the columns
    # added: TI on a row that says what the guess says now, blank on one a
    # person changed. The sidecar itself is left as it is.
    old_format = bool(sidecar) and not has_review_columns(args.sidecar)
    guessed = 0
    if old_format:
        guesses = {info["key"]: info["guess"] for info in tables}
        for key, row in sidecar.items():
            same = bool(row["headers"]) and row["headers"] == guesses.get(key)
            row["drafted-by"], row["reviewed"] = ("TI" if same else ""), ""
            guessed += same and key in claimed
    if unmatched:
        write_csv(unmatched_path, SIDECAR_COLUMNS, unmatched)
        print("table-headers: WARNING: %d sidecar row(s) match no table, so "
              "nothing applies them: a table's text or shape changed, or it's "
              "gone. They're in %s, and each changed table's row as it is now "
              "is in %s. %s is %s without them, to adopt."
              % (len(unmatched), unmatched_path, args.new_path, sample_path,
                 args.sidecar), file=sys.stderr)
    else:
        remove_if_present(unmatched_path)
    if unmatched or old_format:
        write_csv(sample_path, SIDECAR_COLUMNS,
                  [r for k, r in sidecar.items() if k in claimed])
    else:
        remove_if_present(sample_path)
    if old_format:
        print("table-headers: %s has no drafted-by or reviewed column, so its rows "
              "read as a person's decisions. %s is %s with them added: drafted-by "
              "TI on the %d row(s) that say what the guess says now, blank on the "
              "others, which a person changed. Rename it to %s once you've looked."
              % (args.sidecar, sample_path, args.sidecar, guessed,
                 os.path.basename(args.sidecar)), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
