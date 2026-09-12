#!/usr/bin/env python3
"""
migrate-config.py -- split a v0.1 imsmanifest.yaml into the three scoped
configuration files.

    python3 util/migrate-config.py
    python3 util/migrate-config.py -d path/to/book --dry-run

Writes project.yaml, conversion.yaml, and packaging.yaml. The original is
never touched and never removed: this prints what it did and leaves the
old file where it was, so a bad migration costs nothing but three files
you can delete.

WHY THE NAMES CHANGED

imsmanifest.yaml read as though it were the manifest, when it was the
configuration that produces one. That was survivable while producing a
manifest was the only job. It stops being survivable once the same
settings also produce an EPUB, whose package document is not a manifest
and has nothing to do with IMS.

WHERE EACH SETTING WENT

The split is by what a setting describes, not by which script reads it.
Anything true of the book however it is rendered -- its language, its
identifier, its structure -- is project-scoped, and both halves read it.
Anything describing one rendering is conversion-scoped. Anything
describing one distributable archive is packaging-scoped.

That moves `contents` somewhere that may surprise: it used to live with
the cartridge settings, but a cartridge organisation and an EPUB table of
contents are the same book's structure written twice, so it belongs to
the book.

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
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))

try:
    import yaml
except ImportError:
    sys.exit("This needs PyYAML. Install it with:\n"
             "    sudo apt install python3-yaml")

import oerconfig as oc                               # noqa: E402

LEGACY_NAME = "imsmanifest.yaml"
PROJECT_SCHEMA = os.path.join(ROOT, "lib", "schema-project.yaml")
CONVERSION_SCHEMA = os.path.join(ROOT, "bin", "schema-conversion.yaml")
PACKAGING_SCHEMA = os.path.join(ROOT, "bin", "schema-packaging.yaml")

# Every v0.1 key, and where it goes. A key absent from this table is
# reported rather than dropped -- silently losing a setting during a
# migration is the same failure the schema was written to prevent.
MOVES = [
    # (legacy dotted key, destination file, destination dotted key)
    ("manifest.identifier",   "project",    "identifier"),
    ("manifest.title",        "project",    "title"),
    ("manifest.language",     "project",    "language"),
    ("manifest.description",  "project",    "description"),
    ("contents",              "project",    "contents"),

    ("header",                "conversion", "header"),
    ("footer",                "conversion", "footer"),
    ("images.spacer_below",   "conversion", "images.spacer_below"),
    ("images.strip_spacer",   "conversion", "images.strip_spacer"),
    ("images.alt_max_chars",  "conversion", "images.alt_max_chars"),
    ("images.spacer_log",     "conversion", "reports.spacer_images"),
    ("captions.table_prefixes",  "conversion", "captions.table_prefixes"),
    ("captions.figure_prefixes", "conversion", "captions.figure_prefixes"),

    ("manifest.version",      "packaging",  "version"),
    ("manifest.modified",     "packaging",  "modified"),
    ("manifest.keywords",     "packaging",  "keywords"),
    ("common_files",          "packaging",  "common_files"),
    ("grouping.back_matter",  "packaging",  "grouping.back_matter"),
    ("grouping.unsorted_title", "packaging", "grouping.unsorted_title"),
    ("grouping.append_to",    "packaging",  "grouping.append_to"),
]

# manifest.cartridge named the archive, which is now a property of one
# package rather than of the configuration as a whole.
CARTRIDGE_KEY = "manifest.cartridge"


def get_dotted(data, path):
    node = data
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None, False
        node = node[part]
    return node, True


def set_dotted(data, path, value):
    parts = path.split(".")
    node = data
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def leaf_keys(data, prefix=""):
    """Every dotted leaf in the legacy file, so nothing goes unaccounted."""
    out = []
    for key, value in (data or {}).items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            out.extend(leaf_keys(value, path + "."))
        else:
            out.append(path)
    return out


def main():
    parser = argparse.ArgumentParser(
        description="Split a v0.1 imsmanifest.yaml into scoped config files.")
    parser.add_argument("-d", "--dir", default=".",
                        help="directory holding the config (default: .)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report the split without writing anything")
    args = parser.parse_args()

    legacy_path = os.path.join(args.dir, LEGACY_NAME)
    if not os.path.isfile(legacy_path):
        sys.exit(f"No {LEGACY_NAME} in {args.dir}. Nothing to migrate.")

    with open(legacy_path, encoding="utf-8") as handle:
        legacy = yaml.safe_load(handle) or {}

    if set(legacy) & {"defaults", "targets"}:
        sys.exit(f"{legacy_path} already uses the new shape. Nothing to do.")

    buckets = {"project": {}, "conversion": {}, "packaging": {}}
    moved, missing = [], []

    for source, bucket, destination in MOVES:
        value, present = get_dotted(legacy, source)
        if not present:
            continue
        set_dotted(buckets[bucket], destination, value)
        moved.append((source, bucket, destination))

    cartridge, has_cartridge = get_dotted(legacy, CARTRIDGE_KEY)

    accounted = {source for source, _, _ in MOVES} | {CARTRIDGE_KEY}
    for key in leaf_keys(legacy):
        if key in accounted:
            continue
        # contents is a nested list, so its leaves are not dotted keys.
        if key.startswith("contents"):
            continue
        missing.append(key)

    project_schema = oc.load_schema(PROJECT_SCHEMA)
    conversion_schema = oc.load_schema(CONVERSION_SCHEMA)
    packaging_schema = oc.load_schema(PACKAGING_SCHEMA)

    # v0.1 produced one thing: a directory of HTML, packaged as one
    # cartridge. That becomes one conversion target and one package which
    # includes it, which is the smallest configuration that still says
    # out loud what it is building.
    conversion_doc = {
        "project": dict(buckets["project"]),  # read, then written to
                                              # project.yaml only
        "defaults": buckets["conversion"],
        "targets": {"html": {"format": "html", "output_dir": "."}},
    }
    packaging_doc = {
        "project": dict(buckets["project"]),
        "defaults": buckets["packaging"],
        "targets": {"cartridge": {
            "format": "common-cartridge",
            "includes": ["html"],
            **({"filename": cartridge} if has_cartridge and cartridge else {}),
        }},
    }
    project_doc = {"project": buckets["project"]}

    outputs = []
    for name, schema, doc in (
            ("conversion.yaml", conversion_schema, conversion_doc),
            ("packaging.yaml", packaging_schema, packaging_doc)):
        path = os.path.join(args.dir, name)
        resolved = oc.resolve(schema, project_schema,
                              [oc.Document(doc, legacy_path)])
        outputs.append((path, schema, resolved, doc["targets"]))

    project_path = os.path.join(args.dir, "project.yaml")

    print(f"Read {legacy_path}")
    print()
    width = max((len(s) for s, _, _ in moved), default=0)
    for source, bucket, destination in moved:
        arrow = "" if source == destination else f" -> {destination}"
        print(f"  {source:<{width}}  to {bucket}.yaml{arrow}")
    if has_cartridge:
        print(f"  {CARTRIDGE_KEY:<{width}}  to packaging.yaml -> "
              "targets.cartridge.filename")
    if missing:
        print()
        print("  NOT MOVED -- no home in the new schema:")
        for key in missing:
            print(f"    {key}")

    if args.dry_run:
        print()
        print("Dry run: nothing written.")
        return 0

    for path, schema, resolved, targets in outputs:
        if os.path.exists(path):
            sys.exit(f"{path} already exists. Move it aside first; this "
                     "will not overwrite a config you may have edited.")

    if os.path.exists(project_path):
        sys.exit(f"{project_path} already exists. Move it aside first.")

    for path, schema, resolved, targets in outputs:
        oc.write_config(schema, project_schema, resolved, targets, path,
                        notes=[f"Migrated from {LEGACY_NAME}."],
                        include_project=False)
        print(f"\nWrote {path}")

    # The project file repeats what the other two already carry inline, so
    # that either directory can be lifted out on its own. Writing it is
    # still worth doing: with all three present it is the one place to
    # change the language.
    resolved_project = oc.resolve(project_schema, project_schema,
                                  [oc.Document(project_doc, legacy_path)])
    lines = ["# Project configuration, migrated from " + LEGACY_NAME,
             "#",
             "# Facts about the book itself. Both halves read this, and",
             "# both also carry a copy inline so either can stand alone.",
             "",
             "project:"]
    oc._write_tree(project_schema.root, resolved_project.project, lines, 1,
                   skip_target_only=True)
    with open(project_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines).rstrip() + "\n")
    print(f"Wrote {project_path}")

    print()
    print(f"{LEGACY_NAME} was not changed and is no longer read. Check the "
          "three new files, then delete it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
