#!/usr/bin/env python3
"""
unpack-jekyll.py -- turn a Jekyll site's Markdown source into a book
directory convert.py can convert.

    python3 unpack-jekyll.py textbook/ -o cs168-md

A Jekyll book (just-the-docs is the usual theme) keeps a page per .md in
directories of their own, orders them in each page's front matter
(parent, grand_parent, nav_order), and writes a little Markdown Pandoc
reads differently. The directory this writes has:

  - one .md per page, flat, named from its path the way unpack-site.py
    names the saved page for the same URL (end-to-end/dhcp.md is
    end-to-end-dhcp.md, intro/index.md is intro-index.md), so the two
    routes to one book can be compared page by page;
  - in each: the front matter reduced to its title; kramdown's inline
    math ($$x$$ inside a sentence, which Pandoc reads as display math)
    written $x$; kramdown's attribute lists ({: .blue}) removed, which
    Pandoc would print; and root-relative paths (/assets/x.png,
    /routing/bgp.html) made relative to the flat directory. None of it
    inside code: a fenced block or a code span is left exactly as it
    was, since a textbook about the web shows <img src="/logo.png"> as
    an example. (An indented code block isn't recognized; the report
    counts any line that looks like one and holds something these
    rewrites would touch.) Raw HTML is left for convert.py, which reads
    it as HTML when the page is read (markdown-html.lua);
  - the files those pages use, where they were;
  - project.yaml: the site's title and language from _config.yml, and
    contents from the front matter's tree.

The source is read, never written.

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
import posixpath
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
try:
    import yaml
    from names import safe_stem
    from unpacking import write_report, summarize
except ImportError as exc:
    sys.exit(f"Cannot find the library ({exc}). It should be in a lib/ "
             "directory beside bin/, and PyYAML must be installed.")

SKIP_DIRS = {"_site", "_includes", "_layouts", "_sass", "vendor",
             "node_modules", ".git", ".github", ".jekyll-cache"}
SKIP_FILES = {"README.md", "LICENSE.md", "CONTRIBUTING.md", "CHANGELOG.md"}
# The closing --- may end the file: a section's page is often nothing
# but its front matter.
FRONT = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
IAL = re.compile(r"^[ \t]*\{:[^}\n]*\}[ \t]*\n?|\{:[^}\n]*\}", re.M)
LINK = re.compile(r"(\]\(|src=\"|href=\")(/[^)\"\s#?]*)([#?][^)\"\s]*)?")
INLINE_MATH = re.compile(r"\$\$(.+?)\$\$")
# Code, which no rewrite may touch: a fenced block, or a code span.
CODE = re.compile(r"^(```+|~~~+)[^\n]*\n.*?^\1[ \t]*$|(`+)[^`].*?(?<!`)\2(?!`)",
                  re.M | re.S)
INDENTED_RISK = re.compile(r"^(?: {4}|\t).*(?:\$\$|\{:|src=\"/|href=\"/|\]\(/)",
                           re.M)


LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")


def in_list_item(text, offset):
    """Whether the indented line at offset continues a list item, which
    makes it the item's content rather than a code block: the nearest
    line above it that is less indented opens an item."""
    lines = text[:offset].split("\n")[:-1]
    for line in reversed(lines):
        if line.strip() and not line.startswith(("    ", "\t")):
            return bool(LIST_ITEM.match(line))
    return False


def outside_code(text, rewrite):
    """rewrite applied to everything but code, which is kept byte for byte."""
    out, last = [], 0
    for m in CODE.finditer(text):
        out.append(rewrite(text[last:m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(rewrite(text[last:]))
    return "".join(out)


def page_name(relative):
    """The same rule unpack-site.py applies to a page's URL path."""
    stem = re.sub(r"\.(md|markdown)$", "", relative).replace("/", "-")
    return safe_stem(stem) or "page"


def kramdown_math(text):
    """$$..$$ inside a line of prose is kramdown's inline math; a $$ block
    on lines of its own stays display math. Called on text with no code
    in it (see outside_code)."""
    out = []
    for line in text.split("\n"):
        stripped = line.strip()
        if (stripped.startswith("$$") and stripped.endswith("$$")) \
                or stripped == "$$":
            out.append(line)
            continue
        out.append(INLINE_MATH.sub(lambda m: "$" + m.group(1).strip() + "$",
                                   line))
    return "\n".join(out)


def localize(text, pages_by_path, root_files):
    """Root-relative references, made relative to the flat directory: a
    page becomes its flat name, anything else keeps its path."""
    def fix(match):
        lead, path, rest = match.group(1), match.group(2), match.group(3) or ""
        bare = path.strip("/")
        for candidate in (bare, bare + ".md", bare + "/index.md",
                          re.sub(r"\.html$", ".md", bare)):
            if candidate in pages_by_path:
                return lead + pages_by_path[candidate] + ".html" + rest
        return lead + bare + rest
    return LINK.sub(fix, text)


def tree_from_front_matter(pages):
    """just-the-docs' navigation: top-level pages by nav_order, a page's
    children those whose parent is its title (and grand_parent its
    parent's), a page with children a group opened by itself."""
    def order(p):
        n = p["meta"].get("nav_order")
        return (0 if isinstance(n, (int, float)) else 1,
                n if isinstance(n, (int, float)) else 0, p["title"])

    def children(title, parent=None):
        return sorted((p for p in pages if p["meta"].get("parent") == title
                       and (parent is None or p["meta"].get("grand_parent")
                            in (None, parent))), key=order)

    def node(p, parent=None):
        kids = children(p["title"], parent)
        if not kids:
            return {"page": p["name"], "title": p["title"]}
        return {"title": p["title"],
                "items": [{"page": p["name"], "title": p["title"]}]
                + [node(k, p["title"]) for k in kids]}
    top = sorted((p for p in pages if not p["meta"].get("parent")
                  and not p["meta"].get("nav_exclude")), key=order)
    return [node(p) for p in top]


def main():
    parser = argparse.ArgumentParser(
        description="Turn a Jekyll site's Markdown source into a book "
                    "directory: flat pages, relative paths, contents from "
                    "the front matter.")
    parser.add_argument("source")
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args()
    src, out = os.path.abspath(args.source), args.output
    if os.path.exists(out) and os.listdir(out):
        sys.exit(f"{out} exists and is not empty. Name another directory "
                 "with -o.")
    config = {}
    if os.path.isfile(os.path.join(src, "_config.yml")):
        with open(os.path.join(src, "_config.yml"), encoding="utf-8") as fh:
            config = yaml.safe_load(fh) or {}

    pages, notes = [], []
    for directory, dirs, files in os.walk(src):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS
                         and not d.startswith("."))
        for name in sorted(files):
            if not name.endswith((".md", ".markdown")) or name in SKIP_FILES:
                continue
            path = os.path.join(directory, name)
            relative = os.path.relpath(path, src).replace(os.sep, "/")
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            m = FRONT.match(text)
            if not m:
                notes.append((relative, "no-front-matter",
                              "not a page of the site; left out"))
                continue
            meta = yaml.safe_load(m.group(1)) or {}
            pages.append({"relative": relative, "name": page_name(relative),
                          "meta": meta, "body": text[m.end():],
                          "title": str(meta.get("title") or page_name(relative))})
    by_path = {p["relative"]: p["name"] for p in pages}

    os.makedirs(out, exist_ok=True)
    counts = {"attribute-list": 0, "indented-code-risk": 0}
    for page in pages:
        body = page["body"]
        counts["attribute-list"] += len(IAL.findall(CODE.sub("", body)))
        prose = CODE.sub("", body)
        for m in INDENTED_RISK.finditer(prose):
            if in_list_item(prose, m.start()):
                continue
            counts["indented-code-risk"] += 1
            notes.append((page["name"] + ".md", "indented-code-risk",
                          "an indented line holds something rewritten "
                          "outside code; if it's code, check it"))
        body = outside_code(body, lambda t: localize(
            kramdown_math(IAL.sub("", t)), by_path, None))
        front = yaml.safe_dump({"title": page["title"]}, allow_unicode=True,
                               sort_keys=False)
        with open(os.path.join(out, page["name"] + ".md"), "w",
                  encoding="utf-8") as fh:
            fh.write("---\n" + front + "---\n\n" + body.lstrip("\n"))
    if counts["attribute-list"]:
        notes.append(("site", "attribute-list", f"{counts['attribute-list']} "
                      "kramdown attribute list(s) removed"))

    # The files the pages use: everything outside the skipped directories
    # that isn't a page or the site's own machinery.
    for directory, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS
                   and not d.startswith(".")]
        for name in files:
            if name.endswith((".md", ".markdown", ".yml", ".yaml", ".gemspec",
                              ".lock")) or name in ("Gemfile", "CNAME"):
                continue
            path = os.path.join(directory, name)
            # A Jekyll page written in HTML (404.html) is the site's, not
            # the book's: it begins with front matter.
            if name.endswith((".html", ".htm")):
                with open(path, "rb") as fh:
                    if fh.read(3) == b"---":
                        continue
            dest = os.path.join(out, os.path.relpath(path, src))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(path, dest)

    tree = tree_from_front_matter(pages)
    project = {"project": {
        "identifier": re.sub(r"[^A-Za-z0-9._-]+", "-",
                             str(config.get("url") or config.get("title")
                                 or "book")).strip("-") or "book",
        "title": str(config.get("title") or os.path.basename(src)),
        "language": str(config.get("lang") or "en"),
        "contents": tree}}
    with open(os.path.join(out, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("# Written by unpack-jekyll.py from " + src + "; yours to "
                 "edit.\n" + yaml.safe_dump(project, allow_unicode=True,
                                            sort_keys=False, width=1000))
    named = set()

    def collect(nodes):
        for n in nodes:
            if "page" in n:
                named.add(n["page"])
            collect(n.get("items", []))
    collect(tree)
    for page in pages:
        if page["name"] not in named:
            notes.append((page["name"] + ".md", "not-in-navigation",
                          "no nav_order or parent places it"))
    write_report(os.path.join(out, "unpack-report.csv"), notes)
    summarize(notes, out, len(pages))
    return 0


if __name__ == "__main__":
    sys.exit(main())
