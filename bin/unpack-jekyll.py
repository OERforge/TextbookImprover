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
  - in each: the front matter reduced to its title, and the body read
    with Pandoc and written back as Pandoc's Markdown, changed on the
    way through: kramdown's attribute lists ({: .blue}), which Pandoc
    would print, removed before it reads the page, never on a line of a
    code block as Pandoc's own CommonMark reader places them;
    kramdown's inline math ($$x$$ inside a sentence, which Pandoc reads
    as display math) made inline; root-relative paths (/assets/x.png,
    /routing/bgp.html) in links, images, and raw HTML made relative to
    the flat directory. Those two are made on Pandoc's document tree,
    where code of every kind (a code span, a fenced block, an indented
    block) is an element neither looks inside: a textbook about the web
    shows <img src="/logo.png"> as an example. Raw HTML is left for convert.py, which reads it as HTML
    when the page is read (markdown-html.lua);
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
import json
import os
import posixpath
import re
import shutil
import subprocess
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
ATTRIBUTE_LIST = re.compile(r"^\s*\{:[^}]*\}\s*$")
RAW_PATH = re.compile(r"""(\b(?:src|href)\s*=\s*["'])(/[^/"'][^"']*|/)(["'])""",
                      re.I)


def pandoc(arguments, text):
    result = subprocess.run(["pandoc"] + arguments, input=text,
                            capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit("pandoc failed: " + result.stderr.strip())
    return result.stdout


def _text(inlines):
    out = []
    for node in inlines:
        kind = node.get("t")
        if kind == "Str":
            out.append(node["c"])
        elif kind in ("Space", "SoftBreak", "LineBreak"):
            out.append(" ")
        else:
            return None                    # anything else isn't a plain {: }
    return "".join(out)


def code_lines(text):
    """The lines of text that are code blocks, as Pandoc's CommonMark
    reader places them (with sourcepos, each block carries its own line
    range; an end at column 1 is the start of the line after). Fenced and
    indented blocks alike, in a list or out."""
    doc = json.loads(pandoc(["-f", "commonmark_x+sourcepos", "-t", "json"],
                            text))
    lines = set()

    def walk(node):
        if isinstance(node, dict):
            if node.get("t") == "CodeBlock":
                spans = [v for k, v in node["c"][0][2] if k == "data-pos"]
                m = re.match(r"(\d+):\d+-(\d+):(\d+)", spans[-1]) \
                    if spans else None
                if m:
                    first, last, column = map(int, m.groups())
                    lines.update(range(first, last + (column > 1)))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(doc["blocks"])
    return lines


def drop_attribute_lists(text, counts):
    """kramdown's attribute lists, a line of their own each ({: .blue}),
    removed before Pandoc reads the page. It has to be before: one on the
    line above a blockquote applies to the quote in kramdown, and Pandoc,
    which doesn't know them, reads that line and the quote's > lines as
    one paragraph of text, so the quote is gone from the tree. A line
    inside a code block is never touched."""
    skip = code_lines(text)
    kept = []
    for number, line in enumerate(text.split("\n"), 1):
        if number not in skip and ATTRIBUTE_LIST.match(line):
            counts["attribute-list"] += 1
            continue
        kept.append(line)
    return "\n".join(kept)


def fix_tree(node, relative, counts):
    """The kramdown fixes, made on Pandoc's document tree. Code and
    CodeBlock hold strings, not elements, so nothing here reaches into
    code; a Math, a Link, an Image, or raw HTML is never inside one."""
    if isinstance(node, list):
        for item in node:
            if isinstance(item, dict) and item.get("t") in ("Para", "Plain"):
                inlines = item["c"]
                if any(n.get("t") not in ("Math", "Space", "SoftBreak")
                       for n in inlines):
                    for n in inlines:
                        if n.get("t") == "Math" and \
                                n["c"][0]["t"] == "DisplayMath":
                            n["c"][0] = {"t": "InlineMath"}
                            counts["inline-math"] += 1
            fix_tree(item, relative, counts)
    elif isinstance(node, dict):
        kind = node.get("t")
        if kind in ("Link", "Image"):
            target = node["c"][2][0]
            if target.startswith("/") and not target.startswith("//"):
                node["c"][2][0] = relative(target)
                counts["path"] += 1
        elif kind in ("RawInline", "RawBlock") and node["c"][0] == "html":
            def fix(m):
                counts["path"] += 1
                return m.group(1) + relative(m.group(2)) + m.group(3)
            node["c"][1] = RAW_PATH.sub(fix, node["c"][1])
        for value in node.values():
            if isinstance(value, (list, dict)):
                fix_tree(value, relative, counts)


def page_name(relative):
    """The same rule unpack-site.py applies to a page's URL path."""
    stem = re.sub(r"\.(md|markdown)$", "", relative).replace("/", "-")
    return safe_stem(stem) or "page"


def localize(target, pages_by_path):
    """A root-relative reference, made relative to the flat directory: a
    page becomes its flat name, anything else keeps its path."""
    path, _, rest = target.partition("#")
    path, _, query = path.partition("?")
    bare = path.strip("/")
    tail = ("?" + query if query else "") + ("#" + rest if rest else "")
    for candidate in (bare, bare + ".md", bare + "/index.md",
                      re.sub(r"\.html$", ".md", bare)):
        if candidate in pages_by_path:
            return pages_by_path[candidate] + ".html" + tail
    return (bare or ".") + tail


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
    counts = {"attribute-list": 0, "inline-math": 0, "path": 0}
    for page in pages:
        tree = json.loads(pandoc(["-f", "markdown", "-t", "json"],
                                 drop_attribute_lists(page["body"], counts)))
        fix_tree(tree["blocks"], lambda t: localize(t, by_path), counts)
        body = pandoc(["-f", "json", "-t", "markdown", "--wrap=none"],
                      json.dumps(tree))
        front = yaml.safe_dump({"title": page["title"]}, allow_unicode=True,
                               sort_keys=False)
        with open(os.path.join(out, page["name"] + ".md"), "w",
                  encoding="utf-8") as fh:
            fh.write("---\n" + front + "---\n\n" + body)
    for kind, label in (("inline-math", "kramdown inline formula(s) made "
                         "inline"), ("attribute-list", "kramdown attribute "
                         "list(s) removed"), ("path", "root-relative "
                         "path(s) made relative")):
        if counts[kind]:
            notes.append(("site", kind, f"{counts[kind]} {label}"))

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
