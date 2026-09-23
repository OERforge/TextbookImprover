"""
unpacking -- what unpack-epub.py and unpack-site.py both write: a
project.yaml holding a book's metadata and its outline as contents, and
unpack-report.csv. Standard library only.

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
    """No group around the whole book: it would push every page a level
    down in the cartridge and the EPUB's contents."""
    pad = " " * indent
    for node in nodes:
        page, items = node.get("page"), node["items"]
        if items:
            lines.append(f"{pad}- title: {yaml_string(node['title'])}")
            lines.append(f"{pad}  items:")
            if page:
                lines.append(f"{pad}    - page: {page}")
                lines.append(f"{pad}      title: {yaml_string(node['title'])}")
            write_contents(items, lines, indent + 4, flagged, False)
        else:
            lines.append(f"{pad}- page: {page}" + (
                "        # " + flagged[page] if page in flagged else ""))
            lines.append(f"{pad}  title: {yaml_string(node['title'])}")


def project_yaml(source, meta, tree, flagged, unnamed, title):
    """project.yaml's text. meta holds lists under title, language,
    creator, identifier, publisher, description."""
    lines = ["# Written by " + source + "; yours to edit.", "project:",
             "  identifier: " + xml_name((meta.get("identifier") or [title])[0]),
             "  title: " + yaml_string(title),
             "  language: " + yaml_string((meta.get("language") or ["en"])[0])]
    for key in ("description", "publisher"):
        if meta.get(key):
            lines.append(f"  {key}: " + yaml_string(meta[key][0]))
    if meta.get("creator"):
        lines.append("  authors:")
        lines += ["    - " + yaml_string(a) for a in meta["creator"]]
    lines += ["  contents:"]
    write_contents(tree, lines, 4, flagged)
    for page in unnamed:
        lines.append(f"    - page: {page}" + (
            "        # " + flagged[page] if page in flagged else ""))
    return "\n".join(lines) + "\n"


def write_report(path, notes):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Where", "Check", "Detail"])
        writer.writerows(notes)


def summarize(notes, out, pages):
    print(f"{pages} page(s) and project.yaml written to {out}/")
    counts = {}
    for _where, check, _detail in notes:
        counts[check] = counts.get(check, 0) + 1
    for check, count in sorted(counts.items()):
        print(f"  {count:5d}  {check}")
    if notes:
        print(f"Details in {os.path.join(out, 'unpack-report.csv')}.")
