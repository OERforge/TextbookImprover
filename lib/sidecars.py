"""
sidecars.py -- what a sidecar's values mean, read the same way by every
part of the pipeline that reads them.

The filter (figures-and-tables.lua) and the Python that writes a book's
decisions back into its sources read the same image-alt sidecar. They
had each their own idea of the decorative marker: the filter took
"[decorative]" or "decorative" in any case, the Python only the exact
"[decorative]", so a row saying "Decorative" made an image decorative
on the pages and gave the author's copy the alt text "Decorative".

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

# Accepted spellings of the decorative marker, matched case-insensitively
# after trimming. figures-and-tables.lua's DECORATIVE_MARKERS is the same
# list; tests/run-unit-tests.py holds the two together.
DECORATIVE_MARKERS = ("[decorative]", "decorative")


def is_decorative(value):
    """Whether a sidecar's alt text is the decorative marker."""
    return (value or "").strip().lower() in DECORATIVE_MARKERS


# Excel opens a CSV that starts with a byte-order mark as UTF-8, and one
# that doesn't in the computer's code page, Windows-1252 in the US, where
# an en dash shows as "â€“" and a minus sign as "âˆ’"; its "CSV UTF-8"
# writes the mark. So every CSV a run writes for a person, a report or
# rows to adopt as a sidecar, is written in CSV_ENCODING, which puts the
# mark first. A sidecar is read in it too, which drops the mark at the
# file's start, and through csv_lines, which drops one at a line's start,
# where appending a report to a sidecar, its header row and all, leaves
# it. figures-and-tables.lua and math-repair.lua drop both as they read.
CSV_ENCODING = "utf-8-sig"
BOM = "\ufeff"


def csv_lines(fh):
    """A CSV file's lines, for csv.reader or csv.DictReader, each without
    a byte-order mark at its start."""
    for line in fh:
        yield line.lstrip(BOM)


def not_utf8(path):
    """What to tell a person whose sidecar at path isn't UTF-8, naming the
    line and saying how to save it, or None. Excel's plain "CSV" saves in
    the computer's code page, so any character outside ASCII is a byte
    UTF-8 can't read there: the filter would hand it to Pandoc, which
    shows U+FFFD in its place, and a Python reader would stop with a
    traceback. Lines are counted as the csv module ends them, so a file
    with a CR alone at each line's end ("CSV (Macintosh)") is too."""
    with open(path, "rb") as fh:
        data = fh.read()
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        line = len(re.split(rb"\r\n?|\n", data[:exc.start]))
        return ("%s: line %d isn't UTF-8 (byte 0x%02X), so it can't be read. Save it as UTF-8: "
                "from Excel, as \"CSV UTF-8 (Comma delimited)\"." % (path, line, data[exc.start]))
    return None


# The schemes a bare link's Replacement can be an address in, as the
# filter's BARE_SCHEMES: an address replaces the link's address and its
# text, and anything else replaces only its text.
ADDRESS_SCHEMES = ("http", "https", "ftp")


def is_address(value):
    """Whether a bare-links sidecar's Replacement is an address, as
    figures-and-tables.lua's web_scheme tells: a scheme it names, then ://."""
    match = re.match(r"([A-Za-z][A-Za-z0-9+.-]*)://", (value or "").strip())
    return bool(match) and match.group(1).lower() in ADDRESS_SCHEMES


# The setting that makes each kind of math-repaired.csv's rows, and so
# each kind of math-keep.csv's.
MATH_SETTINGS = {"equation": "math.repair_equations", "expression": "math.from_text",
                 "symbol": "math.from_text"}


def math_keep_rows(path):
    """The keep sidecar's rows, (kind, page, before), each once: math a run
    would repair, kept as it was (math-keep.csv, its rows copied from
    math-repaired.csv), a header row anywhere skipped, as appending the
    report again and again carries one along each time."""
    rows = []
    if path and os.path.exists(path):
        with open(path, encoding=CSV_ENCODING, newline="") as fh:
            for row in csv.reader(csv_lines(fh)):
                if row and row[0].strip().lower() == "kind":
                    continue
                if len(row) >= 3 and row[2]:
                    rows.append((row[0], row[1], row[2]))
    return list(dict.fromkeys(rows))


def keep_warning(name, stale, where="the book", off=()):
    """What a run says of the keep sidecar's rows that kept nothing: the
    math they name isn't in the book, or the decks, as written there, or
    the repairs wouldn't change it. A row of a kind only a setting the run
    has off makes (off: those settings, MATH_SETTINGS) couldn't keep
    anything, and isn't said."""
    stale = [row for row in stale if MATH_SETTINGS.get(row[0]) not in off]
    if not stale:
        return []
    return (["WARNING: %d row(s) of %s kept nothing in this run; the math they name isn't in "
             "%s as written there, or the repairs wouldn't change it:"
             % (len(stale), name, where)]
            + ["  %s,%s,%s" % tuple(row) for row in stale[:10]])
