#!/usr/bin/env python3
"""
make-import-tests.py -- build three Common Cartridges that differ in
exactly one way each, to find out what an LMS does on re-import.

    python3 make-import-tests.py -o /some/directory

Three questions, and the cartridges are designed so each import answers
one without confounding the others. Everything is held constant that can
be: the same manifest identifier, the same resource identifiers, the same
page titles, the same number of pages. Only the thing under test moves.

  1-flat.imscc        chapters at the top level, files at the package root
  2-wrapped.imscc     the same chapters inside one module, same file paths
  3-prefixed.imscc    the same wrapped structure, files under a directory

Import them in order and look at what happened after each.

  After 1  Two modules, "Chapter One" and "Chapter Two", at the top level.
           foo.html reads VERSION ONE.

  After 2  Did the two chapters move inside a "Test Book" module, or is
           there now a "Test Book" module alongside the original two?
           That is the question the wrapper proposal turns on. And does
           foo.html now read VERSION TWO -- did a second cartridge with
           the same path overwrite the first?

  After 3  Same structure question again, plus: does foo.html still read
           VERSION TWO, with VERSION THREE landing separately under
           test-book/? If so, a path prefix does prevent the collision,
           which is the point of the second proposal.

Every page says which cartridge it came from in its heading and its body,
so the answer is readable without opening anything.

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
import zipfile

IDENTIFIER = "cc-import-test"
TITLE = "Test Book"

MANIFEST = """<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="{identifier}"
  xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1"
  xmlns:lom="http://ltsc.ieee.org/xsd/imsccv1p1/LOM/resource"
  xmlns:lomimscc="http://ltsc.ieee.org/xsd/imsccv1p1/LOM/manifest"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1 \
http://www.imsglobal.org/profile/cc/ccv1p1/ccv1p1_imscp_v1p2_v1p0.xsd \
http://ltsc.ieee.org/xsd/imsccv1p1/LOM/resource \
http://www.imsglobal.org/profile/cc/ccv1p1/LOM/ccv1p1_lomresource_v1p0.xsd \
http://ltsc.ieee.org/xsd/imsccv1p1/LOM/manifest \
http://www.imsglobal.org/profile/cc/ccv1p1/LOM/ccv1p1_lommanifest_v1p0.xsd">
  <metadata>
    <schema>IMS Common Cartridge</schema>
    <schemaversion>1.1.0</schemaversion>
    <lomimscc:lom>
      <lomimscc:general>
        <lomimscc:title>
          <lomimscc:string>{title}</lomimscc:string>
        </lomimscc:title>
        <lomimscc:description>
          <lomimscc:string>{description}</lomimscc:string>
        </lomimscc:description>
        <lomimscc:language>en</lomimscc:language>
      </lomimscc:general>
      <lomimscc:lifeCycle>
        <lomimscc:contribute>
          <lomimscc:date>
            <lomimscc:dateTime>2026-09-11</lomimscc:dateTime>
          </lomimscc:date>
        </lomimscc:contribute>
      </lomimscc:lifeCycle>
    </lomimscc:lom>
  </metadata>
  <organizations>
    <organization identifier="org-{identifier}" structure="rooted-hierarchy">
      <item identifier="root">
{items}      </item>
    </organization>
  </organizations>
  <resources>
{resources}  </resources>
</manifest>
"""

PAGE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="en" xml:lang="en">
<head>
  <meta charset="utf-8" />
  <title>{title}</title>
</head>
<body>
  <h1>{title}</h1>
  <p style="font-size:1.4em"><strong>{marker}</strong></p>
  <p>{note}</p>
</body>
</html>
"""

# (stem, title, chapter) -- identical in all three cartridges, so nothing
# but the structure and the paths can account for a difference.
PAGES = [
    ("page-1a", "Section 1.1", "Chapter One"),
    ("page-1b", "Section 1.2", "Chapter One"),
    ("page-2a", "Section 2.1", "Chapter Two"),
    ("foo", "Foo", None),
]

VARIANTS = [
    ("1-flat", "VERSION ONE (flat)", False, "",
     "Chapters sit at the top level. Files are at the package root."),
    ("2-wrapped", "VERSION TWO (wrapped)", True, "",
     "The same chapters, inside one module. Same file paths as cartridge 1."),
    ("3-prefixed", "VERSION THREE (wrapped and prefixed)", True, "test-book",
     "The same structure as cartridge 2, but every file lives under "
     "test-book/ inside the package."),
]


def items_xml(wrapped):
    """The organization tree, flat or inside one wrapper module."""
    pad = "          " if wrapped else "        "
    lines = []
    if wrapped:
        lines.append('        <item identifier="group-book">')
        lines.append(f"          <title>{TITLE}</title>")

    for chapter in ("Chapter One", "Chapter Two"):
        lines.append(f'{pad}<item identifier="group-{chapter[-3:].lower()}">')
        lines.append(f"{pad}  <title>{chapter}</title>")
        for stem, title, belongs in PAGES:
            if belongs != chapter:
                continue
            lines.append(f'{pad}  <item identifier="item-{stem}" '
                         f'identifierref="res-{stem}">')
            lines.append(f"{pad}    <title>{title}</title>")
            lines.append(f"{pad}  </item>")
        lines.append(f"{pad}</item>")

    # foo belongs to no chapter, which is what makes it the file both
    # cartridges put at the same path.
    for stem, title, belongs in PAGES:
        if belongs is not None:
            continue
        lines.append(f'{pad}<item identifier="item-{stem}" '
                     f'identifierref="res-{stem}">')
        lines.append(f"{pad}  <title>{title}</title>")
        lines.append(f"{pad}</item>")

    if wrapped:
        lines.append("        </item>")
    return "\n".join(lines) + "\n"


def resources_xml(prefix):
    lines = []
    for stem, _title, _belongs in PAGES:
        href = f"{prefix}/{stem}.html" if prefix else f"{stem}.html"
        lines.append(f'    <resource identifier="res-{stem}" '
                     f'type="webcontent" href="{href}">')
        lines.append(f'      <file href="{href}"/>')
        lines.append("    </resource>")
    return "\n".join(lines) + "\n"


def build(out_dir, name, marker, wrapped, prefix, note):
    path = os.path.join(out_dir, name + ".imscc")
    manifest = MANIFEST.format(
        identifier=IDENTIFIER, title=TITLE,
        description=f"Import test: {note}",
        items=items_xml(wrapped), resources=resources_xml(prefix))

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        # imsmanifest.xml is always at the package root, prefix or not.
        archive.writestr("imsmanifest.xml", manifest)
        for stem, title, _belongs in PAGES:
            member = f"{prefix}/{stem}.html" if prefix else f"{stem}.html"
            archive.writestr(member, PAGE.format(
                title=title, marker=marker, note=note))
    return path


def main():
    parser = argparse.ArgumentParser(
        description="Build three cartridges for an LMS re-import test.")
    parser.add_argument("-o", "--out-dir", default=".",
                        help="where to write them (default: .)")
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    for name, marker, wrapped, prefix, note in VARIANTS:
        path = build(args.out_dir, name, marker, wrapped, prefix, note)
        size = os.path.getsize(path)
        print(f"{path}  ({size} bytes)  {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
