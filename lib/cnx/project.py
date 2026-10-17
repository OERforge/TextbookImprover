"""
cnx.project -- what unpack-cnx.py writes beside the pages: project.yaml
with the book's metadata and its outline as contents, the media the
pages use, the sidecars the source can fill, and the report.

The outline is the book's own: a chapter is a group titled as the book
titles it ("Chapter 3 Demand and Supply") holding its introduction, its
sections, and its end-of-chapter pages; a unit is a group of chapters;
the answer key a group of its chapters' pages; the preface, appendices,
references, and index stand at the top, typed so an EPUB marks them.
The pages' own titles carry their numbers, so the book's numbering
setting stays off.

A table's summary, which OpenStax writes for every table in some books
and which their Word files lose, goes to table-captions.csv for each
table TextbookImprover asks a description for: one whose caption is its
label alone, under the label, and one with no caption at all (OpenStax
leaves a table in an answer unnumbered), under the key TextbookImprover
gives it, its place on its page ("chapter-12#table-5"). Every summary is
in cnx-table-summaries.csv besides, for anyone who wants them where a
table has a title.

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
import re
import shutil

import alttext

from .emit import C1_AS_WINDOWS_1252
from .pages import Group

BARE_LABEL = re.compile(r"^(Table)\s+[A-Z]?\d+(\.\d+)*$")


def yaml_string(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def identifier(collection, slug):
    """An identifier no other book uses: the collection's UUID, which
    OpenStax keeps across a book's versions, as an XML name."""
    if collection.uuid:
        return "book-" + collection.uuid
    return "book-" + re.sub(r"[^A-Za-z0-9._-]+", "-", slug).strip("-")


def contents_lines(items, indent):
    pad = " " * indent
    lines = []
    for item in items:
        if isinstance(item, Group):
            lines.append(f"{pad}- title: {yaml_string(item.title)}")
            if item.kind == "answer-key":
                lines.append(f"{pad}  role: back")
            if item.kind == "unit":
                # A unit is a part: its chapters are groups of their own,
                # each numbering its notes apart (notes.numbering).
                lines.append(f"{pad}  type: part")
            lines.append(f"{pad}  items:")
            lines.extend(contents_lines(item.items, indent + 4))
        else:
            extra = []
            if item.role and item.group is None:
                extra.append(("role", item.role))
            if item.type:
                extra.append(("type", item.type))
            if extra:
                lines.append(f"{pad}- page: {item.name}")
                for key, value in extra:
                    lines.append(f"{pad}  {key}: {value}")
            else:
                lines.append(f"{pad}- {item.name}")
    return lines


def project_yaml(source, collection, slug, outline, publisher=None,
                 authors=None):
    lines = [f"# Written by {source}; yours to edit.", "project:",
             f"  identifier: {identifier(collection, slug)}",
             f"  title: {yaml_string(collection.title or slug)}",
             f"  language: {yaml_string(collection.language or 'en')}"]
    if publisher:
        lines.append(f"  publisher: {yaml_string(publisher)}")
    if collection.license_text or collection.license_url:
        license_text = collection.license_text or collection.license_url
        if collection.license_url and collection.license_url not in \
                license_text:
            license_text += f" ({collection.license_url})"
        lines.append(f"  description: {yaml_string('Licensed ' + license_text)}")
    if authors:
        lines.append("  authors:")
        lines.extend(f"    - {yaml_string(a)}" for a in authors)
    lines.append("  contents:")
    lines.extend(contents_lines(outline, 4))
    return "\n".join(lines) + "\n"


def openstax_conversion(source, figure_word="Figure", table_word="Table"):
    """conversion.yaml for an OpenStax book: the footer OpenStax asks
    for, footnotes numbered through each chapter as OpenStax numbers
    them, and the words the book's captions open with where they aren't
    TextbookImprover's own (*Principles of Management*'s "Exhibit",
    a Polish book's "Ilustracja" and "Tabela")."""
    lines = [f"# Written by {source}; yours to edit.",
             "# OpenStax asks that every page of a book made from theirs say where it",
             "# can be read for free; this footer does that on every page of every",
             "# target.",
             "defaults:",
             '  footer: "Access for free at [openstax.org](https://openstax.org)."',
             "  # Footnotes numbered through each chapter, as OpenStax numbers them;",
             "  # each unit is a part in project.yaml, so its chapters number apart.",
             "  notes:",
             "    numbering: group"]
    if figure_word != "Figure" or table_word != "Table":
        lines += ["  # The word each caption's own label opens with, as the book has it.",
                  "  captions:"]
        if figure_word != "Figure":
            lines.append(f"    figure_prefixes: [{yaml_string(figure_word)}]")
        if table_word != "Table":
            lines.append(f"    table_prefixes: [{yaml_string(table_word)}]")
    return "\n".join(lines) + "\n"


def copy_media(asm, out, notes):
    copied = 0
    for rel, source in sorted(asm.media.items()):
        dest = os.path.join(out, *rel.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(source, dest)
        copied += 1
    for rel, module in sorted(asm.missing_media.items()):
        notes.append((module, "media-missing",
                      f"{rel}: named by the module, not in the repository; "
                      "its description stands in its place"))
    return copied


# What OpenStax writes for a table's summary when it has none to give. Of
# the 6,214 summaries in 41 of its book repositories (June 2026), 1,604 say
# nothing: 671 that alt text's rules catch (".", "---", and the like), and
# 933 these words: "No Summary" 575, "Assessment data" 124, "Some cells are
# left blank for visual design purposes." 75 (Principles of Finance, which
# says why a cell is empty and not what the table holds), "key equations
# table" 51 (the chemistry books'), "Assessment information" 34, "Table" and
# the like 26, "summary" 21, "no alt text" 13, "table x.x" 5, "No-Summary"
# 5, and a Polish template's "The table is called...Opis tabeli" 4.
EMPTY_SUMMARIES = alttext.placeholder_rules(
    ("No Summary", "No-Summary", "Assessment data", "Assessment information",
     "summary", "no alt text", "table", "table x.x", "key equations table",
     "Some cells are left blank for visual design purposes",
     "The table is called...Opis tabeli"))


def says_nothing(summary):
    """Whether a table's summary says nothing about it: a placeholder by
    the rules alt text is judged by (lib/alttext.py), or one of OpenStax's
    own (EMPTY_SUMMARIES)."""
    found = alttext.problem(summary, EMPTY_SUMMARIES, limit=None)
    return bool(found) and found[0] == "placeholder"


# A summary that reads its table out, a row or a cell at a time, rather
# than saying what the table shows: "Two rows and five columns. The first
# row is labeled, “x”, and the second is labeled, “g(x)”. The values of x
# are 2, 4, 6, and 8", "Top left cell reads: Essential Knowledge", "Reading
# the columns as ordered pairs, we have: (1, 31), (2, 28)…". Drafted as a
# caption, it's read before the table it repeats. Of the 4,610 summaries
# that say something in 41 of OpenStax's repositories (June 2026), these
# rules name 1,580, 1,056 of them on a table with no title, whose summary
# is drafted; 70 of them were read, and every one reads its table out. They leave
# out one that names the columns and not their cells ("This table
# presents the year in the first column and percent of workers paid
# hourly rates in the second column"), and some that read a table out in
# words they don't know ("Row 2 describes…", "rows two through five
# contain…").
_NUMBER = (r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
           r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|\d+)")
_NUMBER_PL = (r"(?:jedn\w*|dw\w+|trzy|trzech|czter\w+|pię\w+|sześ\w+|siedem\w*|"
              r"osiem\w*|dziewię\w+|dziesię\w+|\d+)")
_ORDINAL = (r"(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
            r"next|last|top|bottom|header|data|final|1st|2nd|3rd|\d+th)")
_SHAPE = re.compile(_NUMBER + r"[\s-]+(?:rows?|columns?)\b|"
                    + _NUMBER_PL + r"\s+(?:kolumn\w*|wiersz\w*|rzęd\w*)", re.I)
_PAIRS = re.compile(r"\bordered (?:pairs|triples)\b"
                    r"|(?:\([^()]{1,40},[^()]{1,40}\)\s*[,;]?\s*(?:and\s+)?){3,}", re.I)
_A_ROW_READ = re.compile(
    r"\b" + _ORDINAL + r"(?:\s+data)?\s+row\b[^.]{0,40}?\b(?:contains?|has|reads?|"
    r"is labell?ed|lists?|shows?|includes?|states?)\b"
    r"|\b" + _ORDINAL + r"\s+row\s*:"
    r"|\brows?\s+(?:\d+|one|two|three)\s*[:,]"
    r"|\b" + _ORDINAL + r"\s+column,?\s+" + _ORDINAL + r"\s+row\b"
    r"|\bentries\s+in\s+the\s+" + _ORDINAL + r"\s+row\b"
    r"|\bcells?\s+reads?\b|\bcells\s+contain\b"
    r"|\bfrom (?:left to right|top to bottom|bottom to top)\b"
    r"|\bunder (?:the|it|this)\b[^.]{0,60}?\b(?:are|is|reads?|lists?)\b"
    r"|\b(?:wiersz\w*|komórk\w*)\b[^.]{0,40}?\bzawiera\b|\bkolejno\b"
    r"|\bnagłówek\b[^.]{0,80}\bwpis\w*", re.I)
_A_COLUMN_NAMED = re.compile(r"\bcolumn\s+(?:\d+|one|two|three)\s+(?:lists?|shows?|"
                             r"is labell?ed|contains?|has)\b", re.I)
_VALUES = re.compile(
    r"-?\$?\d[\d,]*(?:\.\d+)?%?(?:\s*[,;]\s*(?:and\s+|i\s+)?-?\$?\d[\d,]*(?:\.\d+)?%?){3,}"
    r"|(?:[“\"'‘][^”\"'’]{1,60}[”\"'’]\s*[,;]?\s*(?:and\s+|i\s+)?){3,}"
    r"|(?:[\w)]\s*=\s*-?\$?\d[^.;]*?[.;,]\s*){3,}", re.I)


def reads_out(summary):
    """Whether a table's summary reads the table out, a row or a cell at a
    time: its rows or columns as ordered pairs, a row's or a cell's words,
    or its shape or a column's name and then its values."""
    if _PAIRS.search(summary) or _A_ROW_READ.search(summary):
        return True
    return bool((_SHAPE.search(summary) or _A_COLUMN_NAMED.search(summary))
                and _VALUES.search(summary))


def write_captions(out, tables, report=None):
    """table-captions.csv, prefilled where a table's caption is its label
    alone, or it has none, and the source has a summary that says
    something; not for a layout table, which needs none. A summary that
    reads its table out (reads_out) is drafted as any other is, and named
    in the report, for a person to put what the table shows in its place.
    cnx-table-summaries.csv, every summary, and which read their tables
    out. `tables` is the emitter's: (page, label, caption text, summary,
    layout, place, excerpt). Returns (prefilled, summaries, summaries that
    say nothing, drafted summaries that read their tables out)."""
    prefilled = empty = read_out = 0
    rows = []
    summaries = []
    for page, label, caption, summary, layout, place, excerpt in tables:
        if not summary:
            continue
        caption, summary, excerpt = (
            (text or "").translate(C1_AS_WINDOWS_1252)
            for text in (caption, summary, excerpt))
        reading = reads_out(summary)
        summaries.append((page, label or "", caption, summary, "yes" if reading else ""))
        if says_nothing(summary):
            empty += 1
            continue
        if layout:
            continue
        if label and BARE_LABEL.match(caption.strip()):
            key = label
            rows.append((label, summary, page, "", "OpenStax", ""))
        elif not caption.strip() and place:
            key = f"{page}#table-{place}"
            rows.append((key, summary, page, excerpt, "OpenStax", ""))
        else:
            continue
        prefilled += 1
        if reading:
            read_out += 1
            if report:
                words = summary.split()
                report(page, "table-summary-reads-out",
                       f"{key}: its description in table-captions.csv, OpenStax's "
                       "summary, reads the table out, which a screen reader hears "
                       "before the table itself: “" + " ".join(words[:12])
                       + ("…" if len(words) > 12 else "") + "”")
    if rows:
        with open(os.path.join(out, "table-captions.csv"), "w", newline="",
                  encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["Label", "Description", "Source", "Excerpt",
                             "Drafted by", "Reviewed"])
            writer.writerows(rows)
    if summaries:
        with open(os.path.join(out, "cnx-table-summaries.csv"), "w",
                  newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["Page", "Label", "Caption", "Summary", "Reads out"])
            writer.writerows(summaries)
    return prefilled, len(summaries), empty, read_out
