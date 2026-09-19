#!/usr/bin/env python3
"""
split-pages.py -- cut filtered intermediates into one page per heading.

    split-pages.py --level 2 chapter-7.filtered.json ...
    split-pages.py --level 2 --sidecar page-names.csv --new page-names-new.csv ...

Runs between the filter and the render, on the filtered intermediates
convert.sh writes, and writes one <source>--<name>.filtered.json per
piece. Everything downstream -- the HTML render, the packager, the EPUB
assembler -- sees ordinary pages. The paths of the pieces are printed to
stdout, one per line, in reading order; that is what convert.sh renders.

WHY AFTER THE FILTER

The filter is per-document. The table-headers pre-pass hands it
declarations keyed by source file and table index, the alt-text sidecar
is keyed on the source's media path, and every report names the source.
Split the raw intermediate first and none of that matches; split after
and the pieces carry remediated tables while the reports still name the
file the author has to fix.

WHAT A PIECE IS

Everything from a top-level heading of the chosen level or shallower up
to the next one. The heading itself becomes the piece's title, the way
promote_h1_to_title makes a source's H1 its page title, and its id is
kept as an empty anchor at the top of the piece so links to the section
still land. Body headings shift up so each piece starts its own
structure at H2. Whatever precedes the first cut -- a chapter's own
introduction -- is a piece of its own, named after the source and titled
by it, unless it is empty.

STRUCTURE

Cut headings nest: with level 2, an H1 and the H2s under it are all
pages, and the H2 pages belong under the H1. Each piece records that --
its source, its part n of m, and the headings above it -- in its
metadata and in the page's <head> as <meta> elements, so the packager
and the EPUB assembler group the pieces under their source and under
their enclosing headings without being told. A heading with nothing of
its own before the next cut is not a page; it survives as a group,
through the provenance of the pages under it.

NAMES

A piece is named after its source and its heading, the way OpenStax
names files after headings: "Economies of Scale" under chapter-7
becomes chapter-7--economies-of-scale, with the enclosing heading added
when that alone would repeat. That survives reordering and changes when
the heading does. The page-names sidecar replaces the whole name, keyed
on the source, the enclosing headings, and the heading text, so an
author who wants OpenStax-style names writes them once; a report is
written with a prefilled row for every piece the sidecar has no row
for, with the piece's position (1.2.3) beside it to derive them from.
Pages a previous run wrote are found in its report and replaced, so a
renamed page does not leave its old self behind.

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
import copy
import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
from bookcontents import slugify, stem_title, PIECE_SEPARATOR  # noqa: E402

INTERMEDIATE = ".filtered.json"
SIDECAR_COLUMNS = ["source", "parents", "heading", "position", "name"]
REPORT_COLUMNS = ["source", "parents", "heading", "name", "position",
                  "part", "parts"]
PARENT_JOIN = " > "
ANCHOR_CLASS = "page-title-anchor"
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


# --------------------------------------------------------------------------
# inlines and metadata
# --------------------------------------------------------------------------

def stringify(node):
    if isinstance(node, dict):
        kind = node.get("t")
        if kind == "Str":
            return node["c"]
        if kind in ("Space", "SoftBreak", "LineBreak"):
            return " "
        if kind in ("Code", "Math"):
            return node["c"][1]
        if kind in ("RawInline", "Note"):
            return ""
        return stringify(node.get("c", []))
    if isinstance(node, list):
        return "".join(stringify(child) for child in node)
    return ""


def heading_text(inlines):
    return " ".join(stringify(inlines).split())


def meta_string(text):
    return {"t": "MetaString", "c": str(text)}


def meta_text(meta, key):
    value = meta.get(key)
    if not value:
        return ""
    if value.get("t") == "MetaString":
        return value["c"]
    return heading_text(value.get("c", []))


def html_escape(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


def add_head_meta(meta, pairs):
    """Record provenance in the page's <head> as well as its metadata.

    The packager reads only the HTML, and a <meta> element is where a
    page can say where it came from without saying it on the page.
    """
    tags = "\n".join(f'<meta name="{name}" content="{html_escape(value)}" />'
                     for name, value in pairs)
    block = {"t": "MetaBlocks", "c": [{"t": "RawBlock", "c": ["html", tags]}]}
    existing = meta.get("header-includes")
    if existing is None:
        meta["header-includes"] = {"t": "MetaList", "c": [block]}
    elif existing.get("t") == "MetaList":
        existing["c"].append(block)
    else:
        meta["header-includes"] = {"t": "MetaList", "c": [existing, block]}


# --------------------------------------------------------------------------
# ids and links
# --------------------------------------------------------------------------

def is_attr(value):
    return (isinstance(value, list) and len(value) == 3
            and isinstance(value[0], str)
            and isinstance(value[1], list)
            and all(isinstance(c, str) for c in value[1])
            and isinstance(value[2], list)
            and all(isinstance(kv, list) and len(kv) == 2
                    and isinstance(kv[0], str) and isinstance(kv[1], str)
                    for kv in value[2]))


def collect_ids(node, out):
    if isinstance(node, dict):
        for value in node.values():
            collect_ids(value, out)
    elif is_attr(node):
        if node[0]:
            out.append(node[0])
    elif isinstance(node, list):
        for value in node:
            collect_ids(value, out)


def rewrite_links(node, own, home):
    """Point a #id link at the piece its target moved to."""
    if isinstance(node, dict):
        if node.get("t") == "Link":
            target = node["c"][2]
            if target[0].startswith("#"):
                where = home.get(target[0][1:])
                if where is not None and where != own:
                    target[0] = where + ".html" + target[0]
        for value in node.values():
            rewrite_links(value, own, home)
    elif isinstance(node, list):
        for value in node:
            rewrite_links(value, own, home)


def shift_headers(node, by):
    if by == 0:
        return
    if isinstance(node, dict):
        if node.get("t") == "Header":
            node["c"][0] = max(1, node["c"][0] - by)
        for value in node.values():
            shift_headers(value, by)
    elif isinstance(node, list):
        for value in node:
            shift_headers(value, by)


# --------------------------------------------------------------------------
# the sidecar
# --------------------------------------------------------------------------

def read_sidecar(path):
    """(source, parents, heading) -> name. Columns are matched by header
    name, so a column this version does not know is ignored and a
    missing one reads as empty."""
    names = {}
    if not path or not os.path.exists(path):
        return names
    with open(path, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            row = {k.strip().lower(): (v or "").strip()
                   for k, v in row.items() if k}
            if row.get("source") and row.get("heading"):
                # position is part of the key only when the row gives
                # one: the prefilled rows carry it for headings the path
                # cannot tell apart, and nowhere else, so that moving a
                # section does not orphan its name.
                key = (row["source"], row.get("parents", ""), row["heading"],
                       row.get("position", ""))
                names[key] = row.get("name", "")
    return names


def previous_pages(report):
    """Names a previous run's report lists, so they can be replaced."""
    if not report or not os.path.exists(report):
        return []
    with open(report, encoding="utf-8", newline="") as fh:
        return [row.get("name", "") for row in csv.DictReader(fh)
                if row.get("name")]


# --------------------------------------------------------------------------
# splitting
# --------------------------------------------------------------------------

def cut(blocks, level):
    """[(heading block or None, parents, position, blocks)] in reading
    order, where parents are the titles of the cut headings enclosing
    this one and position is its place among them, "1.2.3". Only
    top-level headings cut: a heading inside a Div or a list item is
    part of what contains it, as it is for the filter's title
    promotion."""
    pieces, current, head = [], [], None
    stack = []                      # [(level, title, index)] enclosing
    parents, position = [], ""

    def close():
        if head is not None or current:
            pieces.append((head, list(parents), position, current))

    for block in blocks:
        # An empty heading is Word cruft, not a section: it cuts nothing
        # and is nobody's parent.
        if block.get("t") == "Header" and block["c"][0] <= level \
                and heading_text(block["c"][2]):
            close()
            head, current = block, []
            own = block["c"][0]
            while stack and stack[-1][0] >= own:
                stack.pop()
            index = 1
            if pieces:
                # Count earlier siblings: cut headings at this level under
                # the same parents.
                index = 1 + sum(1 for h, p, _, _ in pieces
                                if h is not None and h["c"][0] == own
                                and p == [t for _, t, _ in stack])
            parents = [t for _, t, _ in stack]
            position = ".".join(str(i) for _, _, i in stack) + \
                ("." if stack else "") + str(index)
            stack.append((own, heading_text(block["c"][2]), index))
        else:
            current.append(block)
    close()
    return pieces


def split_document(doc, stem, level, names, taken, problems):
    """The pieces of one source: [(piece_stem, title, key, position, doc)].

    taken holds every page name in use across the run, so a sidecar
    cannot give two pieces of different sources one name."""
    parts = cut(doc["blocks"], level)
    if len(parts) <= 1 and (not parts or parts[0][0] is None):
        return []                       # nothing at that level to cut at
    source_title = meta_text(doc.get("meta", {}), "title") \
        or stem_title(stem)
    out = []
    paths = {}                      # default name -> parents it was given
    for n, (head, parents, position, blocks) in enumerate(parts):
        if head is None:
            if not blocks:
                continue
            piece, title, key, anchor = stem, source_title, None, None
        else:
            title = heading_text(head["c"][2])
            # A heading with nothing of its own before the next cut is a
            # group, not a page; the pages under it carry it as a parent.
            following = parts[n + 1] if n + 1 < len(parts) else None
            if not blocks and following and following[0] is not None \
                    and following[1][:len(parents) + 1] == parents + [title]:
                continue
            key = (stem, PARENT_JOIN.join(parents), title)
            declared = names.get(key + (position,)) or names.get(key + ("",),
                                                                 "")
            if declared and not SAFE_NAME.match(declared):
                problems.append(
                    f"page-names: {stem} / {title!r}: {declared!r} is not "
                    "a usable name (letters, digits, . _ - only); the "
                    "heading's is used")
                declared = ""
            if declared and declared in taken:
                problems.append(
                    f"page-names: {stem} / {title!r}: {declared!r} is "
                    "already a page; the heading's name is used")
                declared = ""
            piece = declared
            if not piece:
                piece = stem + PIECE_SEPARATOR + (slugify(title) or "part")
                # The same heading under a different parent takes the
                # parent's name; under the same parent, a number.
                if piece in taken and parents and paths.get(piece) != parents:
                    piece = (stem + PIECE_SEPARATOR + slugify(parents[-1])
                             + PIECE_SEPARATOR + (slugify(title) or "part"))
                if piece in taken:
                    base, k = piece, 2
                    while f"{base}-{k}" in taken:
                        k += 1
                    piece = f"{base}-{k}"
                    problems.append(f"{stem}: {title!r} under "
                                    f"{PARENT_JOIN.join(parents) or 'the top'}"
                                    f" repeats an earlier name; it is {piece}")
            anchor = head["c"][1][0]
        taken.add(piece)
        paths[piece] = parents
        out.append((piece, title, key, parents, position, blocks, anchor))

    total = len(out)
    pieces = []
    for index, (piece, title, key, parents, position, blocks, anchor) \
            in enumerate(out, 1):
        body = copy.deepcopy(blocks)
        shift_headers(body, level - 1)
        if anchor:
            body.insert(0, {"t": "Div", "c": [[anchor, [ANCHOR_CLASS], []],
                                              []]})
        meta = copy.deepcopy(doc.get("meta", {}))
        meta["title"] = {"t": "MetaInlines", "c": [{"t": "Str", "c": w}
                                                    if i % 2 == 0 else
                                                    {"t": "Space"}
                                                    for i, w in enumerate(
                                                        interleave(title))]}
        meta["source-page"] = meta_string(stem)
        meta["source-title"] = meta_string(source_title)
        meta["page-part"] = meta_string(f"{index}/{total}")
        meta["page-parents"] = {"t": "MetaList",
                                "c": [meta_string(t) for t in parents]}
        meta["page-position"] = meta_string(position)
        add_head_meta(meta, [("source-page", stem),
                             ("page-part", f"{index}/{total}"),
                             ("page-position", position)]
                      + [("page-parent", t) for t in parents])
        pieces.append((piece, title, key, parents, position, {
            "pandoc-api-version": doc["pandoc-api-version"],
            "meta": meta, "blocks": body}))
    return pieces


def interleave(text):
    words = text.split()
    out = []
    for word in words:
        out.extend([word, " "])
    return out[:-1] if out else []


def main():
    parser = argparse.ArgumentParser(
        description="Cut filtered intermediates into one page per heading.")
    parser.add_argument("files", nargs="+", help="<page>.filtered.json")
    parser.add_argument("--level", type=int, required=True,
                        help="cut at headings of this level or shallower; "
                             "0 leaves every file whole")
    parser.add_argument("--sidecar", default=None,
                        help="page-names.csv: source,heading,name")
    parser.add_argument("--new", default=None,
                        help="where to write prefilled rows for pieces the "
                             "sidecar does not name")
    parser.add_argument("--report", default=None,
                        help="every piece written, with its source and part")
    args = parser.parse_args()

    names = read_sidecar(args.sidecar)
    problems, new_rows, report_rows, written = [], [], [], []
    seen_keys = set()
    sources = {os.path.basename(p)[:-len(INTERMEDIATE)] for p in args.files
               if p.endswith(INTERMEDIATE)}
    taken = set(sources)

    # Pages the previous run cut are this run's to replace, whatever they
    # were named: a renamed or re-levelled page would otherwise survive.
    if args.level > 0:
        for old in previous_pages(args.report):
            if old in sources:
                continue
            for suffix in (INTERMEDIATE, ".html"):
                for path in args.files:
                    candidate = os.path.join(os.path.dirname(path) or ".",
                                             old + suffix)
                    if os.path.exists(candidate):
                        os.remove(candidate)
                    break

    for path in args.files:
        if not path.endswith(INTERMEDIATE):
            sys.exit(f"{path} is not a {INTERMEDIATE} file.")
        stem = os.path.basename(path)[:-len(INTERMEDIATE)]
        directory = os.path.dirname(path) or "."
        if PIECE_SEPARATOR in stem:
            sys.exit(f"{path}: {PIECE_SEPARATOR!r} in a source name is "
                     "reserved for the pieces this tool writes.")
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        pieces = split_document(doc, stem, args.level, names, taken,
                                problems) if args.level > 0 else []
        if not pieces:
            written.append(path)
            continue

        # Links between pieces. An id that occurs twice in the source
        # keeps its first home, as the browser would have resolved it.
        home = {}
        for piece, _, _, _, _, pdoc in pieces:
            ids = []
            collect_ids(pdoc["blocks"], ids)
            for identifier in ids:
                home.setdefault(identifier, piece)
        total = len(pieces)
        for index, (piece, title, key, parents, position, pdoc) \
                in enumerate(pieces, 1):
            rewrite_links(pdoc["blocks"], piece, home)
            out = os.path.join(directory, piece + INTERMEDIATE)
            with open(out, "w", encoding="utf-8") as fh:
                json.dump(pdoc, fh)
            written.append(out)
            joined = PARENT_JOIN.join(parents)
            report_rows.append([stem, joined, title if key else "", piece,
                                position, str(index), str(total)])
            if key:
                seen_keys.add(key)
                shared = sum(1 for _, _, k, _, _, _ in pieces if k == key) > 1
                if key + (position,) not in names and key + ("",) not in names:
                    new_rows.append([stem, joined, title,
                                     position if shared else "", piece])
        # The source's own intermediate is superseded by its pieces. Left
        # behind, anything that reads every intermediate -- the EPUB
        # assembler -- would take it for a page holding the whole source.
        # (When the content before the first cut is a page, it took the
        # source's name and overwrote it.)
        if stem not in {piece for piece, _, _, _, _, _ in pieces}:
            os.remove(path)
        print(f"split-pages: {stem}: {total} page(s)", file=sys.stderr)

    for key in names:
        if key[:3] not in seen_keys and key[0] in sources:
            where = f" under {key[1]!r}" if key[1] else ""
            problems.append(f"page-names: {key[0]} has no heading "
                            f"{key[2]!r}{where}; the row did not apply")

    for problem in problems:
        print(f"WARNING: {problem}", file=sys.stderr)
    if args.new:
        if new_rows:
            with open(args.new, "w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(SIDECAR_COLUMNS)
                writer.writerows(new_rows)
            print(f"Wrote {args.new} ({len(new_rows)} page(s) named by "
                  "their headings). Edit the name column and append the "
                  f"rows to {args.sidecar or 'page-names.csv'} to keep "
                  "them.", file=sys.stderr)
        elif os.path.exists(args.new):
            os.remove(args.new)
    if args.report:
        if report_rows:
            with open(args.report, "w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(REPORT_COLUMNS)
                writer.writerows(report_rows)
        elif os.path.exists(args.report):
            os.remove(args.report)

    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
