#!/usr/bin/env python3
"""
settings-reference.py -- write the settings reference pages from the schemas.

    python3 util/settings-reference.py            # rewrites docs/*-settings.md
    python3 util/settings-reference.py --check    # exit 1 if they are stale

The three schemas -- lib/schema-project.yaml, bin/schema-conversion.yaml,
bin/schema-packaging.yaml -- carry a description for every setting, and
they are what the tools read, so a reference written from them cannot say
something the tools do not do. This turns each into a Markdown page:
one heading per group, one entry per setting with its type, default, and
description, nested keys indented under their parent.

Run it after changing a schema. --check is what run-all.sh uses to notice
when someone forgot.

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

try:
    import yaml
except ImportError:
    sys.exit("settings-reference.py needs PyYAML (sudo apt install python3-yaml).")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PAGES = [
    {
        "schema": "lib/schema-project.yaml",
        "output": "docs/project-settings.md",
        "title": "Project settings",
        "intro": (
            "Settings that describe the book rather than any one rendering "
            "or package of it, at the top level of `packaging.yaml`. Both "
            "halves of the pipeline read them. Generated from "
            "`lib/schema-project.yaml` by `util/settings-reference.py`; "
            "edit the schema, not this page."),
    },
    {
        "schema": "bin/schema-conversion.yaml",
        "output": "docs/conversion-settings.md",
        "title": "Conversion settings",
        "intro": (
            "Settings that describe one rendering of the book, under "
            "`conversion:` in `packaging.yaml` and per target under "
            "`targets:`. Generated from `bin/schema-conversion.yaml` by "
            "`util/settings-reference.py`; edit the schema, not this page. "
            "A setting marked *target only* can appear only inside a "
            "target."),
    },
    {
        "schema": "bin/schema-packaging.yaml",
        "output": "docs/packaging-settings.md",
        "title": "Packaging settings",
        "intro": (
            "Settings that describe one package of the book, under "
            "`packaging:` in `packaging.yaml` and per target under "
            "`targets:`. Generated from `bin/schema-packaging.yaml` by "
            "`util/settings-reference.py`; edit the schema, not this page."),
    },
]


def fmt_default(value):
    if value is None:
        return "*(none)*"
    if value == "":
        return "`\"\"` (empty)"
    if isinstance(value, bool):
        return "`%s`" % str(value).lower()
    if isinstance(value, (list, dict)):
        return "`%s`" % yaml.safe_dump(value, default_flow_style=True).strip()
    return "`%s`" % value


def one_line(text):
    return " ".join(str(text or "").split())


def render_keys(keys, path, depth, out):
    for name, spec in keys.items():
        full = ".".join(path + [name])
        spec = spec or {}
        if "keys" in spec:
            out.append("%s %s" % ("#" * min(depth + 2, 6), full))
            out.append("")
            if spec.get("description"):
                out.append(one_line(spec["description"]))
                out.append("")
            if spec.get("book_level"):
                out.append("*Book level:* set these under `defaults:`, never in a target, "
                           "since the whole book shares them; in a target they stop the run.")
                out.append("")
            render_keys(spec["keys"], path + [name], depth + 1, out)
            continue
        bits = []
        if spec.get("type"):
            t = spec["type"]
            if t == "enum" and spec.get("values"):
                t = "one of " + ", ".join("`%s`" % v for v in spec["values"])
            else:
                t = "`%s`" % t
            bits.append(t)
        if "default" in spec:
            bits.append("default " + fmt_default(spec["default"]))
        if spec.get("target_only"):
            bits.append("*target only*")
        if spec.get("book_level"):
            bits.append("*book level: in defaults, never a target*")
        if spec.get("required"):
            bits.append("**required**")
        out.append("**`%s`**—%s" % (full, "; ".join(bits)) if bits
                   else "**`%s`**" % full)
        out.append("")
        if spec.get("description"):
            out.append(one_line(spec["description"]))
            out.append("")


def render(page):
    with open(os.path.join(ROOT, page["schema"]), encoding="utf-8") as fh:
        schema = yaml.safe_load(fh)
    out = ["# " + page["title"], "", page["intro"], ""]
    if schema.get("description"):
        out.append(one_line(schema["description"]))
        out.append("")
    render_keys(schema.get("keys", {}), [], 0, out)
    return "\n".join(out).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if any page differs from the schema")
    args = ap.parse_args()
    stale = []
    for page in PAGES:
        text = render(page)
        target = os.path.join(ROOT, page["output"])
        current = None
        if os.path.exists(target):
            with open(target, encoding="utf-8") as fh:
                current = fh.read()
        if args.check:
            if current != text:
                stale.append(page["output"])
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("wrote %s" % page["output"])
    if stale:
        print("stale: %s -- run util/settings-reference.py" % ", ".join(stale),
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
