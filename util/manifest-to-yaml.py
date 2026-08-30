#!/usr/bin/env python3
"""
manifest-to-yaml.py -- convert an existing imsmanifest.xml (or the old
imsmanifest-template.xml) into the imsmanifest.yaml that build-cartridge.py
reads.

    python3 manifest-to-yaml.py imsmanifest-template.xml -o imsmanifest.yaml

Run this once per book. It preserves the part that took work to produce --
the order and grouping of pages, and the metadata -- and drops the part
that is now generated: the <file> entries, which build-cartridge.py
rediscovers from the pages themselves on every run.

Titles are omitted when they match what the page's own <title> already
says, so the resulting config carries only the overrides you actually
need.

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
import sys
import xml.etree.ElementTree as ET

NS = {
    "cp": "http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1",
    "lom": "http://ltsc.ieee.org/xsd/imsccv1p1/LOM/manifest",
}

TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def strip_ns(tag):
    return tag.split("}", 1)[-1] if "}" in tag else tag


def find_text(node, *names):
    """First descendant with one of these local names, ignoring namespaces."""
    for element in node.iter():
        if strip_ns(element.tag) in names and element.text:
            return element.text.strip()
    return ""


def lom_text(node, container):
    """Text of a LOM field, which wraps its value in a <string> child.

    <lomimscc:title><lomimscc:string>...</lomimscc:string></lomimscc:title>
    -- the outer element holds only whitespace, so reading it directly
    yields nothing.
    """
    if node is None:
        return ""
    for element in node.iter():
        if strip_ns(element.tag) == container:
            value = find_text(element, "string")
            if value:
                return value
            if element.text and element.text.strip():
                return element.text.strip()
    return ""


def page_title(base, stem):
    path = os.path.join(base, stem + ".html")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as handle:
        m = TITLE_RE.search(handle.read(20000))
    if not m:
        return None
    import html as html_module
    text = html_module.unescape(m.group(1))
    text = re.sub(r"[\u200b\u200c\u200d\ufeff\u00ad]", "", text)
    return " ".join(text.split())


def quote(value):
    text = str(value)
    if text == "":
        return '""'
    if re.search(r'[:#\n"\'{}\[\]&*!|>%@`]', text) or text != text.strip():
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    parser.add_argument("-o", "--output", default="imsmanifest.yaml")
    parser.add_argument("-d", "--dir", default=".",
                        help="directory holding the pages, used to skip "
                             "titles that the pages already carry")
    args = parser.parse_args()

    tree = ET.parse(args.manifest)
    root = tree.getroot()

    identifier = root.get("identifier") or "course"

    metadata = root.find("cp:metadata", NS)
    title = lom_text(metadata, "title")
    description = lom_text(metadata, "description")
    language = find_text(metadata, "language") if metadata is not None else "en"
    version = lom_text(metadata, "version")
    keywords = []
    if metadata is not None:
        for element in metadata.iter():
            if strip_ns(element.tag) == "keyword":
                word = find_text(element, "string")
                if word:
                    keywords.append(word)

    # href for each resource, so items can be turned back into page stems.
    hrefs = {}
    for resource in root.iter():
        if strip_ns(resource.tag) != "resource":
            continue
        rid = resource.get("identifier")
        href = resource.get("href")
        if rid and href and href.endswith(".html"):
            hrefs[rid] = href[:-5]

    lines = []
    skipped = [0]

    def walk(item, depth):
        pad = "  " * depth
        ref = item.get("identifierref")
        label = ""
        for child in item:
            if strip_ns(child.tag) == "title" and child.text:
                label = child.text.strip()
                break
        children = [c for c in item if strip_ns(c.tag) == "item"]

        if ref and ref in hrefs and not children:
            stem = hrefs[ref]
            actual = page_title(args.dir, stem)
            if actual is not None and actual == label:
                skipped[0] += 1
                lines.append(f"{pad}  - {quote(stem)}")
            else:
                lines.append(f"{pad}  - page: {quote(stem)}")
                if label:
                    lines.append(f"{pad}    title: {quote(label)}")
            return

        if children:
            lines.append(f"{pad}  - title: {quote(label)}")
            lines.append(f"{pad}    items:")
            for child in children:
                walk(child, depth + 2)

    organization = None
    for element in root.iter():
        if strip_ns(element.tag) == "organization":
            organization = element
            break
    if organization is None:
        sys.exit("No <organization> found; is this a Common Cartridge manifest?")

    top = [c for c in organization if strip_ns(c.tag) == "item"]
    # A single unnamed outer container is a wrapper, not a real group.
    while len(top) == 1:
        inner = [c for c in top[0] if strip_ns(c.tag) == "item"]
        if not inner or top[0].get("identifierref"):
            break
        top = inner

    for item in top:
        walk(item, 0)

    out = [
        "# Converted from " + os.path.basename(args.manifest) + ".",
        "# The <file> entries were dropped: build-cartridge.py rediscovers",
        "# them from the pages on every run.",
        "",
        "manifest:",
        f"  identifier: {quote(identifier)}",
        f"  title: {quote(title or identifier)}",
        f"  description: {quote(description)}",
        f"  version: {quote(version or '1.0')}",
        f"  language: {quote(language or 'en')}",
        f"  cartridge: {quote(identifier + '.imscc')}",
    ]
    if keywords:
        out.append("  keywords:")
        out += [f"    - {quote(k)}" for k in keywords]
    else:
        out.append("  keywords: []")
    out += ["", "contents:"] + lines + [""]

    with open(args.output, "w", encoding="utf-8") as handle:
        handle.write("\n".join(out))

    pages = sum(1 for line in lines if "- " in line and "title:" not in line)
    print(f"Wrote {args.output}: {pages} page entries.")
    if skipped[0]:
        print(f"{skipped[0]} title(s) omitted because the pages already "
              "carry them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
