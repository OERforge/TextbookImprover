#!/usr/bin/env python3
"""
manifest-to-yaml.py -- convert an existing imsmanifest.xml (or the old
imsmanifest-template.xml) into the project.yaml and packaging.yaml that
build-cartridge.py
reads.

    python3 manifest-to-yaml.py imsmanifest-template.xml -d .

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

# The configuration library lives beside bin/, found by path rather than
# installed so the project stays clone-and-run.
BIN_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
LIB_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
sys.path.insert(0, LIB_DIR)

try:
    import yaml
except ImportError:
    sys.exit("This needs PyYAML:\n    sudo apt install python3-yaml")

try:
    import oerconfig
except ImportError:
    sys.exit("Cannot find the configuration library; it belongs in lib/.")

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
    parser.add_argument("-d", "--dir", default=".",
                        help="directory holding the pages; the configs are "
                             "written here too (default: .)")
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

    # Written through the configuration library rather than assembled by
    # hand, so a key added to a schema appears here without anyone having
    # to remember this file exists. Hand-built YAML in one place and a
    # schema in another is how the v0.1 sample writer came to be missing
    # three settings.
    contents = yaml.safe_load("\n".join(["contents:"] + lines))["contents"]

    project_doc = {"project": {
        "identifier": identifier,
        "title": title or identifier,
        "description": description,
        "language": language or "en",
        "contents": contents or [],
    }}
    packaging_doc = {
        "project": dict(project_doc["project"]),
        "defaults": {"version": version or "1.0",
                     "keywords": list(keywords)},
        "targets": {"cartridge": {"format": "common-cartridge",
                                  "includes": ["html"],
                                  "filename": identifier + ".imscc"}},
    }

    project_schema = oerconfig.load_schema(
        os.path.join(LIB_DIR, "schema-project.yaml"))
    packaging_schema = oerconfig.load_schema(
        os.path.join(BIN_DIR, "schema-packaging.yaml"))

    note = "Converted from " + os.path.basename(args.manifest) + ". The " \
           "<file> entries were dropped: build-cartridge.py rediscovers " \
           "them from the pages on every run."

    packaging_path = os.path.join(args.dir, "packaging.yaml")
    project_path = os.path.join(args.dir, "project.yaml")
    for path in (packaging_path, project_path):
        if os.path.exists(path):
            sys.exit(f"{path} already exists. Move it aside first.")

    resolved = oerconfig.resolve(packaging_schema, project_schema,
                                 [oerconfig.Document(packaging_doc,
                                                     args.manifest)])
    oerconfig.write_config(packaging_schema, project_schema, resolved,
                           packaging_doc["targets"], packaging_path,
                           notes=[note], include_project=False)

    resolved_project = oerconfig.resolve(
        project_schema, project_schema,
        [oerconfig.Document(project_doc, args.manifest)])
    lines_out = ["# " + note, "", "project:"]
    oerconfig._write_tree(project_schema.root, resolved_project.project,
                          lines_out, 1, skip_target_only=True)
    with open(project_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines_out).rstrip() + "\n")

    print(f"Wrote {project_path} and {packaging_path}.")

    pages = sum(1 for line in lines if "- " in line and "title:" not in line)
    print(f"{pages} page entries.")
    if skipped[0]:
        print(f"{skipped[0]} title(s) omitted because the pages already "
              "carry them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
