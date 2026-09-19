#!/usr/bin/env python3
"""
read-conversion-config.py -- resolve the conversion configuration and hand
it to convert.sh as shell assignments.

    python3 bin/read-conversion-config.py -d . --target html OUT_DIR
    python3 bin/read-conversion-config.py -d . --init

Writes OUT_DIR/settings.sh, which convert.sh sources. With --init, writes
a conversion.yaml holding every setting at its default with a line of
documentation above it, and stops. There is no example configuration to
copy: the schema is the only description, so the file you start from is
generated from it and cannot be out of date.

WHY THIS EXISTS SEPARATELY

Until v0.2 this was a flag on build-cartridge.py, which meant the
conversion half could not read its own configuration without the
packaging half present. That is the wrong way round: conversion is the
more basic job, and remediating a folder of documents has nothing to do
with cartridges. Both now depend on the same configuration library and
neither depends on the other.

Header and footer are the one thing that needs doing rather than
reporting. A block scalar in the YAML is written out as a Markdown file
here; a single line naming an existing file is taken as a path and passed
through. Either way convert.sh receives a path, so it does not have to
know which form was used.

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

try:
    import oerconfig
except ImportError:
    sys.exit("Cannot find the configuration library. It should be in a "
             "lib/ directory beside bin/.")

CONFIG_NAME = "conversion.yaml"
PROJECT_NAME = "project.yaml"
LEGACY_NAME = "imsmanifest.yaml"


def shell_quote(value):
    return "'" + str(value).replace("'", "'\\''") + "'"


def as_list(value):
    return ",".join(str(v) for v in value) if isinstance(value, (list, tuple)) \
        else str(value)


def fragment_path(text, key, config_dir, out_dir):
    """A path to Markdown for header/footer, or an empty string."""
    if not text:
        return ""
    text = str(text)
    candidate = os.path.join(config_dir or ".", text.strip())
    if "\n" not in text.strip() and os.path.isfile(candidate):
        return os.path.abspath(candidate)
    path = os.path.join(out_dir, key + ".md")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text.rstrip() + "\n")
    return os.path.abspath(path)


def main():
    parser = argparse.ArgumentParser(
        description="Resolve the conversion config into shell settings.")
    parser.add_argument("out_dir", nargs="?",
                        help="directory to write settings.sh into")
    parser.add_argument("--init", action="store_true",
                        help="write a conversion.yaml of documented "
                             "defaults and stop")
    parser.add_argument("-d", "--dir", default=".",
                        help="directory holding the config (default: .)")
    parser.add_argument("--target", default=None,
                        help="which conversion target to resolve")
    parser.add_argument("--format", default=None,
                        help="with several targets, resolve the one of "
                             "this format (html, epub3, ...)")
    parser.add_argument("--allow-unknown-keys", action="store_true",
                        help="report settings this version does not know "
                             "about instead of refusing them")
    args = parser.parse_args()
    if not args.init and not args.out_dir:
        parser.error("give a directory to write settings.sh into, or --init")

    base = args.dir
    config_path = os.path.join(base, CONFIG_NAME)

    legacy = os.path.join(base, LEGACY_NAME)
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
        project_path = os.path.join(base, PROJECT_NAME)
        if os.path.isfile(project_path):
            documents.append(
                oerconfig.load_document(project_path, project_schema))
        if os.path.isfile(config_path):
            documents.append(oerconfig.load_document(config_path, schema))
    except oerconfig.ConfigError as exc:
        sys.exit(str(exc))

    target = args.target
    if target is None:
        names = oerconfig.target_names(documents)
        if len(names) == 1:
            target = names[0]
        elif names and args.format:
            # One target at a time: convert.py builds every target itself
            # through the library, and this reader serves whoever wants
            # one target's settings as shell assignments.
            try:
                matching = [
                    name for name in names
                    if oerconfig.resolve(schema, project_schema, documents,
                                         target=name,
                                         allow_unknown=True)["format"]
                    == args.format]
            except oerconfig.ConfigError as exc:
                sys.exit(str(exc))
            if len(matching) == 1:
                target = matching[0]
            elif not matching:
                sys.exit(f"None of the targets ({', '.join(names)}) has "
                         f"format: {args.format}.")
            else:
                sys.exit(f"Several targets have format: {args.format} ("
                         + ", ".join(matching) + "). Choose one with "
                         "--target.")
        elif names:
            sys.exit("This configuration defines several targets (" +
                     ", ".join(names) + "). Choose one with --target.")

    try:
        resolved = oerconfig.resolve(schema, project_schema, documents,
                                     target=target,
                                     allow_unknown=args.allow_unknown_keys)
    except oerconfig.ConfigError as exc:
        sys.exit(str(exc))

    for warning in resolved.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)

    if args.init:
        out = os.path.join(base, CONFIG_NAME)
        if os.path.exists(out):
            sys.exit(f"{out} already exists. Move it aside first; this "
                     "will not overwrite a config you may have edited.")
        targets = {}
        for doc in documents:
            targets.update({n: b or {} for n, b in doc.targets.items()})
        if not targets:
            targets["html"] = {"format": "html", "output_dir": "."}
        oerconfig.write_config(
            schema, project_schema, resolved, targets, out,
            notes=["Written by --init. Every setting is at its default;",
                   "delete any line you do not want to override."])
        print(f"Wrote {out}.")
        return 0

    os.makedirs(args.out_dir, exist_ok=True)

    settings = {
        # The page language. One declared value, so a book in Spanish
        # cannot end up with pages saying lang="en" inside a package
        # saying es -- which is what a separate hardcoded default gave
        # before, and which no report would have caught.
        "LANGUAGE": resolved.project["language"],

        "HEADER_MD": fragment_path(resolved["header"], "header",
                                   base, args.out_dir),
        "FOOTER_MD": fragment_path(resolved["footer"], "footer",
                                   base, args.out_dir),

        "PROMOTE_H1_TO_TITLE": resolved["promote_h1_to_title"],
        "AUTHOR_BYLINE": resolved["author_byline"],

        "SPACER_BELOW": resolved["images.spacer_below"],
        "STRIP_SPACER": "true" if resolved["images.strip_spacer"] else "false",
        "ALT_MAX_CHARS": resolved["images.alt_max_chars"],
        "RESPONSIVE_IMAGES":
            "true" if resolved["images.responsive"] else "false",
        "WRAP_TABLES": "true" if resolved["tables.wrap"] else "false",
        "TABLE_MARKERS": ",".join(f"{k}={v}" for k, v in
                                  (resolved["tables.markers"] or {}).items()),
        "MEDIA_STRICT": "1" if resolved["media.strict"] else "",

        "TABLE_LABEL_PREFIXES": as_list(resolved["captions.table_prefixes"]),
        "FIGURE_LABEL_PREFIXES": as_list(resolved["captions.figure_prefixes"]),

        # Names rather than paths: convert.sh keeps its reports and
        # sidecars beside the scripts, not in the content directory, and
        # it is the one that knows where that is.
        "TABLE_CAPTIONS_NAME": resolved["sidecars.table_captions"],
        "IMAGE_ALT_NAME": resolved["sidecars.image_alt"],
        "TABLE_CAPTIONS_MISSING_NAME":
            resolved["reports.table_captions_missing"],
        "IMAGE_ALT_MISSING_NAME": resolved["reports.image_alt_missing"],
        "TABLE_HEADERS_NAME": resolved["sidecars.table_headers"],
        "TABLE_HEADERS_NEW_NAME": resolved["reports.table_headers_new"],
        "TABLE_HEADERS_REPORT_NAME":
            resolved["reports.table_headers_report"],
        "SPLIT_LEVEL": resolved["pages.split_level"],
        "PAGE_NAMES_NAME": resolved["sidecars.page_names"],
        "PAGE_NAMES_NEW_NAME": resolved["reports.page_names_new"],
        "PAGE_NAMES_REPORT_NAME": resolved["reports.page_names_report"],
        "OUTPUT_CHECK_NAME": resolved["reports.output_check"],
        "MEDIA_UNRESOLVED_NAME": resolved["reports.media_unresolved"],
        "SPACER_LOG_NAME": resolved["reports.spacer_images"],

        "OUTPUT_DIR": resolved["output_dir"],
        "TARGET_FORMAT": resolved["format"],
        "TARGET_NAME": target or "",
    }

    with open(os.path.join(args.out_dir, "settings.sh"), "w",
              encoding="utf-8") as handle:
        handle.write("# Written by read-conversion-config.py. "
                     "Edit the YAML, not this.\n")
        for key, value in settings.items():
            handle.write(f"{key}={shell_quote(value)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
