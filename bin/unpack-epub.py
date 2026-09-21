#!/usr/bin/env python3
"""
unpack-epub.py -- turn an EPUB into a directory convert.py can convert.

    python3 unpack-epub.py book.epub            # writes ./book/
    python3 unpack-epub.py book.epub -o ~/books/infosys

The directory gets one .html per content document, named for it and in
no other way changed except that its references point at where things
now are; the book's images and other files at the paths they had beside
the package document; and a project.yaml holding what the package said
about the book and, as contents, what its navigation document said about
the order, every page marked as a source to convert. Then:

    cd book && python3 convert.py

The EPUB is read, never written. What the unpacking noticed and did not
decide is in unpack-report.csv: a file in the spine the navigation never
names, a page that looks like the book's own table of contents, an image
that is not an image, a navigation entry that points inside a page.

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
import os
import posixpath
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
try:
    import epubsource
    from names import safe_stem
except ImportError:
    sys.exit("Cannot find the library. It should be in a lib/ directory "
             "beside bin/.")

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")


def page_names(package):
    """{archive path: page name} for the spine, the navigation document
    left out. A name is the file's own, made safe for a link; two files
    of one name in different directories take their directory as well."""
    names, taken = {}, set()
    for path, _linear in package.spine:
        if path == package.nav_path:
            continue
        stem = safe_stem(posixpath.splitext(posixpath.basename(path))[0])
        if stem in taken:
            stem = safe_stem(posixpath.splitext(
                posixpath.relpath(path, package.root or "."))[0]
                .replace("/", "-"))
        taken.add(stem)
        names[path] = stem
    return names


def xml_name(text):
    """A project identifier has to be an XML name with no colon; a
    package's is usually a URL or a UUID."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "-",
                  re.sub(r"^[a-z]+:/*", "", text.strip())).strip("-.")
    return name if re.match(r"[A-Za-z_]", name or "") else "book-" + name


def yaml_string(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def contents_tree(outline, names, notes):
    """The navigation's entries as a contents tree. An entry that names a
    page is that page; one with entries beneath it is a group, opened by
    its own page when it has one. An entry that points inside a page
    (a fragment, after the page has already been named) is not a page
    and is reported: that is the split's work."""
    tree, stack, seen, inside = [], [], set(), 0
    for depth, title, path, fragment in outline:
        page = names.get(path)
        if page is None or page in seen:
            if page is not None:
                inside += 1
            node = {"title": title, "items": []}
        else:
            seen.add(page)
            node = {"title": title, "page": page, "items": []}
        del stack[depth:]
        (stack[-1]["items"] if stack else tree).append(node)
        stack.append(node)
    if inside:
        notes.append(("navigation", "entries-inside-pages",
                      f"{inside} navigation entries point inside a page "
                      "already named; pages.split_level in conversion.yaml "
                      "cuts a page at its headings"))

    def prune(nodes):
        out = []
        for node in nodes:
            node["items"] = prune(node["items"])
            if "page" in node or node["items"]:
                out.append(node)
        return out
    return prune(tree), seen


def write_contents(nodes, lines, indent, flagged, top=True):
    """Every top-level entry says convert: true, which its pages inherit.
    One group around the whole book would say it once, and would push
    every page a level down in the cartridge and the EPUB's contents."""
    pad = " " * indent
    for node in nodes:
        page, items = node.get("page"), node["items"]
        if items:
            lines.append(f"{pad}- title: {yaml_string(node['title'])}")
            if top:
                lines.append(f"{pad}  convert: true")
            lines.append(f"{pad}  items:")
            if page:
                lines.append(f"{pad}    - page: {page}")
                lines.append(f"{pad}      title: {yaml_string(node['title'])}")
            write_contents(items, lines, indent + 4, flagged, False)
        else:
            lines.append(f"{pad}- page: {page}" + (
                "        # " + flagged[page] if page in flagged else ""))
            lines.append(f"{pad}  title: {yaml_string(node['title'])}")
            if top:
                lines.append(f"{pad}  convert: true")


def main():
    parser = argparse.ArgumentParser(
        description="Unpack an EPUB into HTML sources, its media, and a "
                    "project.yaml with the book's metadata and contents.")
    parser.add_argument("epub")
    parser.add_argument("-o", "--output",
                        help="directory to write (default: the EPUB's name)")
    args = parser.parse_args()
    out = args.output or os.path.splitext(os.path.basename(args.epub))[0]
    if os.path.exists(out) and os.listdir(out):
        sys.exit(f"{out} exists and is not empty; unpacking would mix two "
                 "books. Name another directory with -o.")
    os.makedirs(out, exist_ok=True)

    package = epubsource.Package(args.epub)
    names = page_names(package)
    notes = []                           # (where, check, detail)

    # The pages: text as shipped, references moved.
    links_to_pages = {}
    for path, linear in package.spine:
        if path not in names:
            continue
        markup = package.read(path).decode("utf-8", errors="replace")
        rewritten = epubsource.rewrite_references(markup, path, names,
                                                  package.root)
        links_to_pages[path] = len(set(re.findall(
            r'href="([^"#]+\.html)', rewritten)))
        with open(os.path.join(out, names[path] + ".html"), "w",
                  encoding="utf-8") as fh:
            fh.write(rewritten)
        if not linear:
            notes.append((names[path] + ".html", "not-linear",
                          "the spine marks this file as outside the reading "
                          "order"))

    # Everything else the manifest names, where it sat.
    pages = {p for p, _ in package.spine}
    for path, kind, _props in package.manifest.values():
        if path in pages or path in (package.nav_path, package.ncx_path):
            continue
        try:
            data = package.read(path)
        except KeyError:
            notes.append((path, "missing-from-archive",
                          "the manifest names a file the archive lacks"))
            continue
        relative = posixpath.relpath(path, package.root or ".")
        dest = os.path.join(out, *relative.split("/"))
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(data)
        shown = kind.startswith("image/") or relative.lower().endswith(
            IMAGE_EXTENSIONS) or "/images/" in "/" + relative.lower()
        if shown and epubsource.sniff(data) is None:
            notes.append((relative, "image-is-not-an-image",
                          f"declared {kind or 'nothing'}; begins "
                          + repr(data[:40].decode("latin-1").strip())))

    # The order, from the navigation.
    tree, named = contents_tree(package.outline(), names, notes)
    flagged = {}
    for path, count in links_to_pages.items():
        if len(names) >= 6 and count >= 0.6 * (len(names) - 1):
            flagged[names[path]] = ("links to most of the book: the book's "
                                    "own contents page? generate: toc "
                                    "writes one")
            notes.append((names[path] + ".html", "looks-like-contents",
                          f"links to {count} of {len(names)} pages; if it is "
                          "the book's own table of contents, 'generate: toc' "
                          "in contents replaces it"))
    unnamed = [names[p] for p, _ in package.spine
               if p in names and names[p] not in named]
    for page in unnamed:
        notes.append((page + ".html", "not-in-navigation",
                      "in the spine, named by no navigation entry; listed "
                      "at the end of contents"))

    meta = package.metadata
    title = (meta["title"] or [os.path.basename(out)])[0]
    lines = ["# Written by unpack-epub.py from " + os.path.basename(args.epub)
             + "; yours to edit.", "project:",
             "  identifier: " + xml_name((meta["identifier"] or [title])[0]),
             "  title: " + yaml_string(title),
             "  language: " + yaml_string((meta["language"] or ["en"])[0])]
    for key in ("description", "publisher"):
        if meta[key]:
            lines.append(f"  {key}: " + yaml_string(meta[key][0]))
    if meta["creator"]:
        lines.append("  authors:")
        lines += ["    - " + yaml_string(a) for a in meta["creator"]]
    lines += ["  # convert: true marks an .html as a source to convert, not a "
              "finished page;", "  # a group's pages inherit it.",
              "  contents:"]
    write_contents(tree, lines, 4, flagged)
    for page in unnamed:
        lines.append(f"    - page: {page}" + (
            "        # " + flagged[page] if page in flagged else ""))
        lines.append("      convert: true")
    with open(os.path.join(out, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    with open(os.path.join(out, "unpack-report.csv"), "w", newline="",
              encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Where", "Check", "Detail"])
        writer.writerows(notes)

    print(f"{len(names)} page(s) and project.yaml written to {out}/")
    counts = {}
    for _where, check, _detail in notes:
        counts[check] = counts.get(check, 0) + 1
    for check, count in sorted(counts.items()):
        print(f"  {count:5d}  {check}")
    if notes:
        print(f"Details in {os.path.join(out, 'unpack-report.csv')}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
