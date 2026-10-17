#!/usr/bin/env python3
"""
cnx-compare-cookbook.py -- compare unpack-cnx.py's baking with cookbook's
own, on the sample books cookbook tests its recipes with.

    git clone https://github.com/openstax/cookbook
    python3 util/cnx-compare-cookbook.py cookbook
    python3 util/cnx-compare-cookbook.py cookbook statistics --show 5

openstax/cookbook keeps, for each recipe, a sample book as OpenStax's
assembly writes one (spec/recipes_spec/books/<book>/input.xhtml) and the
same book as the recipe bakes it (expected_output.xhtml): a few chapters
of the real book, cut down, and in most of them exercises from the
exercise bank, already put in. Each is baked here with the unpacker's
port of the recipe and compared with cookbook's, page by page, as the
words of each page in order. A page is matched by its id, a page baking
builds (a chapter's "Key Terms", an answer key's "Chapter 3") by its
place among those and its title. Every page that differs is listed, and
with --show, where.

What the unpacker does differently on purpose is left out on both
sides (lib/cnx/compare.py, DELIBERATE): the book's metadata, the link
cookbook writes beside an embedded video for print ("Access multimedia
content"), footnotes (Pandoc's notes here), an inline list's
separators, which the unpacker writes when it reads the source, the
words cookbook writes for screen readers alone, its running heads for
print, and its "unknown title" for a note whose kind its locale doesn't
name. Spaces alone between elements are dropped on both sides, as
cookbook's tests drop them reading the samples.

With no style named, every sample whose recipe has a port is compared.
The exit status is 1 if any page differs. Use it when a recipe is
ported, and when the ports are brought up to a later cookbook: the
samples are cookbook's tests, so they change with its recipes.

Needs lxml. Copyright 2026 Robert Szarka

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
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))

from cnx import compare as C  # noqa: E402
from cnx.bake import bake  # noqa: E402
from cnx.bake.recipes import RECIPES  # noqa: E402

# Samples baked with another book's recipe, as cookbook's own tests bake
# them (spec/recipes_spec/main_spec.rb); every other sample is its
# recipe's name. Trigonometry's isn't among cookbook's tests, but it's
# the precalculus recipe's book.
SAMPLES = {
    "college-algebra": "precalculus",
    "college-algebra-coreq": "precalculus-coreq",
    "trigonometry": "precalculus",
    "prealgebra": "dev-math",
    "elementary-algebra": "dev-math",
    "intermediate-algebra": "dev-math",
    "business-law": "business-ethics",
    "intellectual-property": "business-ethics",
    "organizational-behavior": "principles-management",
    "pl-microeconomics": "pl-economics",
}


def keyed(body):
    """{key: words}: a page by its id, a page baking built (which has no
    id here) by its place among those and its title."""
    found = {}
    built = 0
    for page, page_words in C.pages(body):
        if page.get("data-type") == "page" and page.get("id"):
            found.setdefault(page.get("id"), page_words)
        elif page.get("data-type") == "composite-page":
            built += 1
            found[f"built page {built}: {C.title_of(page)}"] = page_words
    return found


def compare(cookbook, sample, show=0):
    """Bake the sample and compare it with cookbook's. Returns the number
    of pages that differ, or are on one side only."""
    style = SAMPLES.get(sample, sample)
    folder = os.path.join(cookbook, "spec", "recipes_spec", "books", sample)
    root = C.load(os.path.join(folder, "input.xhtml"))
    ours = root.find("body")
    # Cookbook's locale is the document's lang, English without one.
    bake(ours, style, root.get("lang") or "en")
    theirs = C.load(os.path.join(folder, "expected_output.xhtml")).find("body")
    a, b = keyed(ours), keyed(theirs)
    only_theirs = [k for k in b if k not in a]
    only_ours = [k for k in a if k not in b]
    differ = []
    for key in b:
        if key in a and a[key] != b[key]:
            m = C.matcher(a[key], b[key])
            differ.append((m.ratio(), key, m))
    print(f"{sample} ({style}): {len(b)} page(s); "
          + (f"{len(differ)} differ" if differ else "none differ")
          + (f", {len(only_theirs)} only cookbook's" if only_theirs else "")
          + (f", {len(only_ours)} only ours" if only_ours else ""))
    for key in only_theirs:
        print(f"  only cookbook's: {key}")
    for key in only_ours:
        print(f"  only ours: {key}")
    for ratio, key, m in sorted(differ, key=lambda d: d[0]):
        print(f"  {ratio:.4f}  {key}")
        C.show(m, a[key], b[key], show, "cookbook")
    return len(differ) + len(only_theirs) + len(only_ours)


def main():
    parser = argparse.ArgumentParser(
        description="Compare unpack-cnx.py's baking with cookbook's, on "
                    "cookbook's sample books.")
    parser.add_argument("cookbook", help="a clone of openstax/cookbook")
    parser.add_argument("samples", nargs="*",
                        help="samples to compare (default: every one "
                             "whose recipe has a port)")
    parser.add_argument("--show", type=int, default=0, metavar="N",
                        help="show where, up to N places a page")
    args = parser.parse_args()
    folder = os.path.join(args.cookbook, "spec", "recipes_spec", "books")
    if not os.path.isdir(folder):
        sys.exit(f"{folder} isn't there; name a clone of openstax/cookbook")
    samples = args.samples or sorted(
        name for name in os.listdir(folder)
        if SAMPLES.get(name, name) in RECIPES)
    failed = 0
    for sample in samples:
        if SAMPLES.get(sample, sample) not in RECIPES:
            print(f"{sample}: no port of its recipe")
            failed += 1
            continue
        failed += compare(args.cookbook, sample, args.show) > 0
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
