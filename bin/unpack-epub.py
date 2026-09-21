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
    from unpacking import contents_tree, project_yaml, write_report, summarize
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

    meta = dict(package.metadata)
    title = (meta["title"] or [os.path.basename(out)])[0]
    with open(os.path.join(out, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write(project_yaml("unpack-epub.py from "
                              + os.path.basename(args.epub), meta, tree,
                              flagged, unnamed, title))
    write_report(os.path.join(out, "unpack-report.csv"), notes)
    summarize(notes, out, len(names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
