#!/usr/bin/env python3
"""
read-conversion-config.py -- write conversion-sample.yaml, every
conversion setting with its documentation above it.

    python3 bin/read-conversion-config.py -d . --init

Each setting is at the value conversion.yaml gives it, or else its
default, and each target in its own block; renamed to conversion.yaml,
the sample loses nothing set there. There is no example configuration to
copy: the schema is the only description, so the file you start from is
generated from it and cannot be out of date. convert.py reads the
configuration itself, through lib/oerconfig.py.

WHY THIS EXISTS SEPARATELY

Until v0.2 this was a flag on build-cartridge.py, which meant the
conversion half could not read its own configuration without the
packaging half present. That is the wrong way round: conversion is the
more basic job, and remediating a folder of documents has nothing to do
with cartridges. Both now depend on the same configuration library and
neither depends on the other.

It wrote a file of shell assignments too, settings.sh, for a convert.sh
that was retired when convert.py took over; nothing read it after that
but a check in the EPUB suite, so it went.

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
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
import projectpaths  # noqa: E402

P = projectpaths.of

try:
    import oerconfig
except ImportError:
    sys.exit("Cannot find the configuration library. It should be in a "
             "lib/ directory beside bin/.")

CONFIG_NAME = "conversion.yaml"
SAMPLE_NAME = "conversion-sample.yaml"
PROJECT_NAME = "project.yaml"
LEGACY_NAME = "imsmanifest.yaml"


def main():
    parser = argparse.ArgumentParser(
        description=f"Write {SAMPLE_NAME}: every conversion setting with its "
                    "description.")
    parser.add_argument("out_dir", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument("--init", action="store_true",
                        help=f"write {SAMPLE_NAME}: every setting with its "
                             f"description, at the value {CONFIG_NAME} gives "
                             "it or its default, and stop")
    parser.add_argument("-d", "--dir", default=".",
                        help="directory holding the config (default: .)")
    parser.add_argument("--allow-unknown-keys", action="store_true",
                        help="report settings this version does not know "
                             "about instead of refusing them")
    args = parser.parse_args()
    if args.out_dir:
        parser.error("settings.sh isn't written any more, since nothing read it: "
                     "convert.py reads the configuration itself. --init writes "
                     f"{SAMPLE_NAME}.")
    if not args.init:
        parser.error(f"give --init, to write {SAMPLE_NAME}")

    base = args.dir
    config_path = P(base).config_file()

    legacy = P(base).top(LEGACY_NAME)
    if os.path.isfile(legacy) and not os.path.isfile(config_path):
        sys.exit(
            f"{legacy} is the v0.1 configuration and is no longer read.\n"
            f"Split it with:\n"
            f"    python3 util/migrate-config.py -d {base}")

    schema = oerconfig.load_schema(
        os.path.join(HERE, "schema-conversion.yaml"))
    project_schema = oerconfig.load_schema(
        os.path.join(os.path.dirname(HERE), "lib", "schema-project.yaml"))

    documents = []
    try:
        project_path = P(base).project_file()
        if os.path.isfile(project_path):
            documents.append(
                oerconfig.load_document(project_path, project_schema))
        if os.path.isfile(config_path):
            documents.append(oerconfig.load_document(config_path, schema))
    except oerconfig.ConfigError as exc:
        sys.exit(str(exc))

    # The defaults as the file gives them and every target's block as its
    # own, so it resolves with none chosen: one chosen would write its
    # overrides as every target's defaults.
    try:
        resolved = oerconfig.resolve(schema, project_schema, documents,
                                     target=None,
                                     allow_unknown=args.allow_unknown_keys)
    except oerconfig.ConfigError as exc:
        sys.exit(str(exc))

    for warning in resolved.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)

    out = P(base).report(SAMPLE_NAME)
    targets = {}
    for doc in documents:
        targets.update({n: b or {} for n, b in doc.targets.items()})
    if not targets:
        targets["html"] = {"format": "html"}
    # The project block only when conversion.yaml holds one already, so
    # renaming the sample keeps it; otherwise it's project.yaml's.
    inline = oerconfig.inline_project(config_path)
    oerconfig.write_config(
        schema, project_schema, resolved, targets, out,
        notes=["Written by --init."], include_project=inline or False)
    print(f"Wrote {out}: every conversion setting with its description, "
          f"your own where you set one. Rename it to {CONFIG_NAME} to use "
          "it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
