#!/usr/bin/env python3
"""
round-trip-decks.py -- PowerPoint decks converted to Markdown and back, and
each compared with the deck it was made from, slide by slide: the check
the deck reader (lib/pptxsource.py) is held to.

    round-trip-decks.py decks/              # every deck in the folder
    round-trip-decks.py decks/ --keep trip/ # and keep what the trip wrote

The folder's decks, with its sidecars and its project.yaml, are converted
by convert.py through a markdown target; that Markdown, a deck written in
Markdown, through a pptx target; and each deck compared with its trip as
lib/deckcompare.py compares them, for its titles, text and formatting,
lists, tables, pictures and their alt text, equations, and notes. The
decks themselves aren't touched: the trip is made in a folder of its own.

What Pandoc's PowerPoint writer doesn't write, and the pptx target doesn't
put back, is reported with the rest, as a difference: a merged cell. Exit
status is 0 when every deck came back the same, 1 when one didn't or a run
failed.

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
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

import deckcompare      # noqa: E402
import pptxremediate    # noqa: E402
from names import safe_stem     # noqa: E402

CONVERT = os.path.join(ROOT, "bin", "convert.py")
# The sidecars a deck's conversion reads its decisions from.
SIDECARS = ("image-alt.csv", "table-headers.csv", "slide-titles.csv", "reading-order.csv",
            "bare-links.csv", "math-keep.csv")


def convert(folder):
    """convert.py in folder, quietly; (return code, its messages)."""
    done = subprocess.run([sys.executable, CONVERT, "--quick", "--quiet"], cwd=folder,
                          capture_output=True, text=True)
    return done.returncode, done.stderr


def trip(source, work):
    """The decks in source made Markdown in work/source, and that Markdown
    PowerPoint again in work/trip. Returns ({deck: its trip's file},
    messages of a run that failed)."""
    decks = sorted(n for n in os.listdir(source) if n.lower().endswith(".pptx")
                   and not n.startswith("~$"))
    first = os.path.join(work, "source")
    os.makedirs(first)
    for name in decks + [n for n in SIDECARS + ("project.yaml",)
                         if os.path.isfile(os.path.join(source, n))]:
        shutil.copy2(os.path.join(source, name), first)
    with open(os.path.join(first, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  md:\n    format: markdown\n")
    code, said = convert(first)
    if not os.path.isdir(os.path.join(first, "md")):
        return {}, said
    second = os.path.join(work, "trip")
    shutil.copytree(os.path.join(first, "md"), second)
    language = None
    if os.path.isfile(os.path.join(first, "project.yaml")):
        import yaml
        with open(os.path.join(first, "project.yaml"), encoding="utf-8") as fh:
            language = ((yaml.safe_load(fh) or {}).get("project") or {}).get("language")
    with open(os.path.join(second, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  identifier: org.example.round-trip\n  title: Round trip\n"
                 "  kind: slides\n" + ("  language: %s\n" % language if language else ""))
    with open(os.path.join(second, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  decks:\n    format: pptx\n")
    code2, said2 = convert(second)
    made = {name: os.path.join(second, "decks", safe_stem(name[:-5]) + ".pptx") for name in decks}
    return {k: v for k, v in made.items() if os.path.isfile(v)}, \
        (said if code else "") + (said2 if code2 else "")


def main():
    parser = argparse.ArgumentParser(
        description="Convert a folder's PowerPoint decks to Markdown and back, and compare "
                    "each with its trip.")
    parser.add_argument("folder", help="a folder of PowerPoint decks, with their sidecars")
    parser.add_argument("--keep", metavar="DIR",
                        help="write the trip in DIR, which must not exist, and keep it")
    args = parser.parse_args()
    source = os.path.abspath(args.folder)
    if args.keep and os.path.exists(args.keep):
        sys.exit("%s exists; --keep makes it." % args.keep)
    work = os.path.abspath(args.keep) if args.keep else tempfile.mkdtemp(prefix="round-trip-")
    os.makedirs(work, exist_ok=True)
    try:
        made, failed = trip(source, work)
        if failed:
            print(failed.rstrip(), file=sys.stderr)
        alts = pptxremediate.alt_rows(os.path.join(source, "image-alt.csv"))
        tables = pptxremediate.header_rows(os.path.join(source, "table-headers.csv"))
        titles = pptxremediate.title_rows(os.path.join(source, "slide-titles.csv"))
        orders = pptxremediate.order_rows(os.path.join(source, "reading-order.csv"))
        decks = sorted(n for n in os.listdir(source) if n.lower().endswith(".pptx")
                       and not n.startswith("~$"))
        differing = 0
        for name in decks:
            if name not in made:
                print("%s: no trip was made" % name)
                differing += 1
                continue
            found = deckcompare.compare(
                deckcompare.read(os.path.join(source, name), work, alts=alts, tables=tables,
                                 titles=titles, orders=orders),
                deckcompare.read(made[name], work))
            print("%s: %s" % (name, "the same" if not found else
                              "%d difference(s)" % len(found)))
            for difference in found:
                first, second = deckcompare.first_difference(difference.first,
                                                             difference.second)
                print("  %s, %s:\n    %r\n    %r" % (difference.where, difference.what,
                                                     first, second))
            differing += bool(found)
        print("%d of %d deck(s) came back the same." % (len(decks) - differing, len(decks)))
        return 1 if differing or failed else 0
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
