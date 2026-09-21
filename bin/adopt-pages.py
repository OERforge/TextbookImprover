#!/usr/bin/env python3
"""
adopt-pages.py -- take a converted book's pages as the sources of a new one.

    python3 adopt-pages.py book/html -o book-2
    cd book-2 && python3 convert.py

The split names a piece after its source and its heading, joined by
"--" (chapter-3--supply.html), and "--" in a source's own name is
reserved for that, so pages the split wrote can't be read back as
sources as they stand. This writes a new directory where they can:

  - each page whose name holds "--" is renamed with one hyphen in its
    place (chapter-3-supply.html), numbered when that name is taken;
  - every reference to a renamed page, in every page, follows it, with
    its fragment; nothing else in a page changes but the next item;
  - the split's record of where a page came from (the source-page,
    page-part, page-parent and similar <meta> elements, or the same keys
    in a Markdown page's metadata) is removed, since the page is a
    source now: read back, the record would describe a split that no
    longer applies, and the tools that group pages by it when the order
    is guessed rather than declared would still follow it;
  - a page the book copied from its pass-through directory goes back
    into one, so it stays a page someone finished;
  - everything else in the directory (media, stylesheets) is copied as
    it is;
  - project.yaml is the book's, with contents naming the pages as they
    are now: the book's own contents, as it resolved, or the order the
    run guessed. The book's sidecars keyed on a table's content or an
    image's path are copied too; page-names.csv isn't, since there are
    no pieces left for it to name.

The pages are HTML from an HTML target, or Markdown from a Markdown
target. The book's directory is the pages' parent unless --book says.
Nothing in the book is changed.

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
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
try:
    import yaml
    from bookcontents import (guess_contents, walk_contents,
                              contents_from_tree, expand_split_sources,
                              page_title, page_provenance, page_role)
except ImportError as exc:
    sys.exit(f"Cannot find the library ({exc}). It should be in a lib/ "
             "directory beside bin/, and PyYAML must be installed.")

PROVENANCE = ("source-page", "source-title", "page-part", "page-parent",
              "page-position")
PROVENANCE_META = re.compile(
    r'[ \t]*<meta\s+name="(?:' + "|".join(PROVENANCE) + r')"[^>]*>\s*?\n?',
    re.I)
PROVENANCE_YAML = re.compile(
    r"^(?:" + "|".join(PROVENANCE) + r"):.*\n(?:[ \t]+-.*\n|[ \t]+.*\n)*",
    re.M)
SIDECARS = ("table-headers.csv", "table-captions.csv", "image-alt.csv")


def new_names(stems):
    """{old: new} for every page whose name holds "--"."""
    taken, names = set(stems), {}
    for stem in sorted(stems):
        if "--" not in stem:
            continue
        base = re.sub(r"-{2,}", "-", stem)
        name, n = base, 2
        while name in taken:
            name, n = f"{base}-{n}", n + 1
        taken.add(name)
        names[stem] = name
    return names


def rewrite(text, names, ext):
    """References to renamed pages follow them. A name holds "--", so a
    match can't be part of an ordinary word; it must stand alone, before
    .html or .md and then a fragment, a query, or the end of the value."""
    if not names:
        return text
    pattern = re.compile(
        r"(?<![\w.-])(" + "|".join(re.escape(n) for n in
                                   sorted(names, key=len, reverse=True))
        + r")\.(html|md)(?=[#?\"')\s>]|$)")
    return pattern.sub(lambda m: names[m.group(1)] + "." + m.group(2), text)


def strip_provenance(text, ext):
    if ext == ".html":
        head, sep, rest = text.partition("</head>")
        return PROVENANCE_META.sub("", head) + sep + rest
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end > 0:
            return "---\n" + PROVENANCE_YAML.sub(
                "", text[4:end + 1]) + text[end + 1:]
    return text


def rename_contents(node, names):
    if isinstance(node, str):
        return names.get(node, node)
    if isinstance(node, list):
        return [rename_contents(n, names) for n in node]
    if isinstance(node, dict):
        out = dict(node)
        if "page" in out:
            out["page"] = names.get(str(out["page"]), out["page"])
        if "items" in out:
            out["items"] = rename_contents(out["items"], names)
        return out
    return node


def main():
    parser = argparse.ArgumentParser(
        description="Take a converted book's pages as the sources of a new "
                    "one: pieces renamed without '--', links rewritten, "
                    "the split's provenance removed, contents written.")
    parser.add_argument("pages", help="a target's output directory")
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("--book", help="the book's directory (default: the "
                                       "pages' parent)")
    args = parser.parse_args()
    pages_dir = os.path.abspath(args.pages)
    book = os.path.abspath(args.book or os.path.dirname(pages_dir))
    out = args.output
    if os.path.exists(out) and os.listdir(out):
        sys.exit(f"{out} exists and is not empty. Name another directory "
                 "with -o.")
    html = [f for f in os.listdir(pages_dir) if f.endswith(".html")]
    md = [f for f in os.listdir(pages_dir) if f.endswith(".md")]
    ext = ".html" if html else ".md"
    stems = sorted(f[:-len(ext)] for f in (html or md))
    if not stems:
        sys.exit(f"No pages in {pages_dir}.")
    names = new_names(stems)

    # The contents, as the book resolved it, before anything is renamed.
    titles, parts, roles = {}, {}, {}
    if ext == ".html":
        for stem in stems:
            path = os.path.join(pages_dir, stem + ext)
            titles[stem] = page_title(path, stem)
            origin = page_provenance(path)
            if origin:
                parts[stem] = origin
            if page_role(path):
                roles[stem] = page_role(path)
    project_path = os.path.join(book, "project.yaml")
    document = {}
    if os.path.isfile(project_path):
        with open(project_path, encoding="utf-8") as fh:
            document = yaml.safe_load(fh) or {}
    project = document.get("project") or {}
    declared = project.get("contents")
    problems = []
    contents = expand_split_sources(declared, stems, titles, parts, roles) \
        if declared else guess_contents(stems, None, titles, parts, roles)
    tree = walk_contents(contents, set(stems), set(), problems)
    project["contents"] = rename_contents(contents_from_tree(tree), names)
    document["project"] = project

    shutil.copytree(pages_dir, out)
    for stem in stems:
        path = os.path.join(out, stem + ext)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        text = strip_provenance(rewrite(text, names, ext), ext)
        os.remove(path)
        where = out
        passthrough = str(project.get("passthrough", "_pt") or "")
        if passthrough and os.path.isfile(os.path.join(book, passthrough,
                                                       stem + ext)):
            where = os.path.join(out, passthrough)
            os.makedirs(where, exist_ok=True)
        with open(os.path.join(where, names.get(stem, stem) + ext), "w",
                  encoding="utf-8") as fh:
            fh.write(text)
    with open(os.path.join(out, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("# Written by adopt-pages.py from " + book + ".\n"
                 + yaml.safe_dump(document, sort_keys=False,
                                  allow_unicode=True, width=1000))
    for name in SIDECARS:
        if os.path.isfile(os.path.join(book, name)):
            shutil.copy2(os.path.join(book, name), os.path.join(out, name))
    for problem in problems:
        print(f"WARNING: {problem}", file=sys.stderr)
    print(f"{len(stems)} page(s) written to {out}/, {len(names)} renamed.")
    for old, new in sorted(names.items()):
        print(f"  {old}{ext} -> {new}{ext}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
