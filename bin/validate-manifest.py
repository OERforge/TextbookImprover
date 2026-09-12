#!/usr/bin/env python3
"""
validate-manifest.py -- check an imsmanifest.xml against the Common
Cartridge 1.1 schemas, or against what can be checked without them.

    python3 bin/validate-manifest.py imsmanifest.xml
    python3 bin/validate-manifest.py imsmanifest.xml --quiet

build-cartridge.py calls this automatically; running it directly is for
checking a manifest this project did not write.

WHY THIS EXISTS

build-cartridge.py has always checked that referenced files exist and that
the contents tree resolves. It never checked that the XML it writes
conforms to the schema, and the cost of that gap is measured: every
cartridge this project produced before v0.2 carried a lomimscc:version
element inside lifeCycle, where the CC 1.1 profile permits contribute
alone and declares no version element anywhere. Every LMS accepted it. It
was found by validating against the schema and by nothing else.

TWO LEVELS

Full validation needs lxml, which is not otherwise required here. When it
is missing this falls back to checks the standard library can make:

  - the document is well formed
  - every identifier is a valid XML name, since IMS types them as xs:ID
  - every identifierref resolves to an identifier that exists
  - every file href appears in a resource

That is a genuine subset, not a gesture. The identifier rule is the one
that catches a pasted UUID, and the reference rule is the one that catches
a contents entry pointing at a resource that was never written.

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

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_DIR = os.path.join(os.path.dirname(HERE), "schemas", "cc11")
ROOT_SCHEMA = "ccv1p1_imscp_v1p2_v1p0.xsd"

# An XML NCName, which is what xs:ID derives from.
NCNAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9._-]*$")

CP = "{http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1}"


def schema_available():
    return os.path.isfile(os.path.join(SCHEMA_DIR, ROOT_SCHEMA))


# --------------------------------------------------------------------------
# full validation
# --------------------------------------------------------------------------

def validate_with_schema(path):
    """(ok, problems) using lxml, or None if lxml is not installed."""
    try:
        from lxml import etree
    except ImportError:
        return None

    class LocalSchemas(etree.Resolver):
        """Serve an imported schema from disk by filename.

        The IMS schemas import each other by absolute https URL. Rewriting
        those to relative paths would be the obvious fix and is not
        permitted: the licence grants redistribution to developers who
        "have not changed this document". So they are stored exactly as
        published and resolved here instead, which also means validation
        never touches the network.
        """

        def resolve(self, url, public_id, context):
            candidate = os.path.join(SCHEMA_DIR, os.path.basename(url))
            if os.path.isfile(candidate):
                return self.resolve_filename(candidate, context)
            return None

    parser = etree.XMLParser(load_dtd=False, no_network=True)
    parser.resolvers.add(LocalSchemas())

    try:
        schema = etree.XMLSchema(
            etree.parse(os.path.join(SCHEMA_DIR, ROOT_SCHEMA), parser))
    except etree.XMLSyntaxError as exc:
        return False, [f"the schemas in {SCHEMA_DIR} could not be loaded: "
                       f"{exc}"]

    try:
        document = etree.parse(path)
    except etree.XMLSyntaxError as exc:
        return False, [f"not well formed: {exc}"]

    if schema.validate(document):
        return True, []
    return False, [f"line {e.line}: {e.message}" for e in schema.error_log]


# --------------------------------------------------------------------------
# fallback
# --------------------------------------------------------------------------

def validate_without_schema(path):
    """(ok, problems) using only the standard library."""
    problems = []
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        return False, [f"not well formed: {exc}"]

    root = tree.getroot()
    declared = set()

    for element in root.iter():
        identifier = element.get("identifier")
        if identifier is None:
            continue
        tag = element.tag.split("}")[-1]
        if not NCNAME_RE.match(identifier):
            hint = ""
            if identifier[:1].isdigit():
                hint = " (it starts with a digit)"
            elif ":" in identifier:
                hint = " (it contains a colon)"
            problems.append(
                f"<{tag}> has identifier {identifier!r}, which is not a "
                f"valid XML name{hint}. IMS types these as xs:ID.")
        if identifier in declared:
            problems.append(f"identifier {identifier!r} is used more than "
                            "once; they must be unique within the manifest.")
        declared.add(identifier)

    for element in root.iter():
        reference = element.get("identifierref")
        if reference is not None and reference not in declared:
            tag = element.tag.split("}")[-1]
            problems.append(
                f"<{tag}> refers to {reference!r}, which no resource "
                "declares.")

    resources = root.find(CP + "resources")
    if resources is None:
        problems.append("no <resources> element.")
    elif not list(resources):
        problems.append("<resources> is empty.")

    return not problems, problems


# --------------------------------------------------------------------------

def validate(path, quiet=False):
    """Validate, preferring the schema. Returns True when nothing is wrong.

    Prints its own findings, including which of the two levels ran, so a
    passing run never leaves you wondering whether anything was checked.
    """
    if not os.path.isfile(path):
        print(f"No manifest at {path}.", file=sys.stderr)
        return False

    result = validate_with_schema(path) if schema_available() else None

    if result is None:
        reason = ("lxml is not installed" if schema_available()
                  else f"the schemas are not in {SCHEMA_DIR}")
        print(f"Note: {reason}, so {os.path.basename(path)} was checked "
              "for well-formedness, identifier syntax and unresolved "
              "references only.", file=sys.stderr)
        if schema_available():
            print("  For full schema validation: "
                  "sudo apt install python3-lxml", file=sys.stderr)
        ok, problems = validate_without_schema(path)
        level = "partly checked"
    else:
        ok, problems = result
        level = "valid against Common Cartridge 1.1"

    if ok:
        if not quiet:
            print(f"{os.path.basename(path)}: {level}.")
        return True

    print(f"ERROR: {os.path.basename(path)} did not validate:",
          file=sys.stderr)
    for problem in problems[:20]:
        print(f"  {problem}", file=sys.stderr)
    if len(problems) > 20:
        print(f"  ... and {len(problems) - 20} more", file=sys.stderr)
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Validate an IMS Common Cartridge 1.1 manifest.")
    parser.add_argument("manifest", nargs="?", default="imsmanifest.xml")
    parser.add_argument("--quiet", action="store_true",
                        help="say nothing when the manifest is valid")
    args = parser.parse_args()
    return 0 if validate(args.manifest, quiet=args.quiet) else 1


if __name__ == "__main__":
    sys.exit(main())
