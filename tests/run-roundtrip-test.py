#!/usr/bin/env python3
"""
run-roundtrip-test.py -- prove that writing a configuration and reading it
back changes nothing.

    python3 tests/run-roundtrip-test.py

This is the test that would have caught the bug this schema exists to
prevent. The old sample writer built YAML by hand from a list of keys it
knew about, and that list was missing three of them -- captions, grouping,
and manifest.modified -- so any run that hit a fatal error wrote a
"complete" sample without them and told the user to rename it over their
real config. Nothing failed; the settings just quietly stopped existing.

Rather than checking for those three keys, this walks the schema, sets
every declared setting to a value that is not its default, writes the
file, reads it back, and compares. A setting the writer forgets fails
here whether or not anyone remembered to test for it, and a setting added
later is covered the day it is declared.

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

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))

import oerconfig as oc                               # noqa: E402

PROJECT_SCHEMA = os.path.join(ROOT, "lib", "schema-project.yaml")
TOOL_SCHEMAS = [os.path.join(ROOT, "bin", "schema-conversion.yaml"),
                os.path.join(ROOT, "bin", "schema-packaging.yaml")]


def unusual(node):
    """A value for this setting that is not its default.

    Deliberately awkward where the type allows it: text that would be read
    as a boolean, a string that looks like a number, a value with a comma
    in it. A writer that quotes carelessly passes on tidy values and fails
    on these.
    """
    kind = node.type
    if kind == "bool":
        return not bool(node.default)
    if kind == "int":
        return int(node.default or 0) + 7
    if kind == "float":
        return float(node.default or 0) + 0.25
    if kind == "enum":
        for value in node.values:
            if value != node.default:
                return value
        return node.default
    if kind == "list":
        return ["no", "1.10", "a, b"]
    if kind == "language":
        return "es-MX"
    if kind == "ncname":
        return "org.example.dept.course-2e"
    if kind == "date":
        return "2026-01-02"
    if kind == "path":
        return "sub dir/file, with comma.csv"
    if kind == "opaque":
        return [{"page": "one"}, {"title": "Group", "children": [
            {"page": "two"}]}]
    if kind == "text":
        return "Line one.\nLine two with a colon: here.\n"
    return "no"           # string: the word YAML would make a boolean of


def populate(node, target_only):
    out = {}
    for name, child in node.keys.items():
        if child.is_section:
            out[name] = populate(child, target_only)
        elif bool(child.target_only) == target_only:
            out[name] = unusual(child)
    return out


def flatten(values, prefix=""):
    flat = {}
    for key, value in (values or {}).items():
        if isinstance(value, dict):
            flat.update(flatten(value, f"{prefix}{key}."))
        else:
            flat[f"{prefix}{key}"] = value
    return flat


def check(schema_path):
    schema = oc.load_schema(schema_path)
    project_schema = oc.load_schema(PROJECT_SCHEMA)
    name = os.path.basename(schema_path)

    everything = {
        "project": populate(project_schema.root, target_only=False),
        "defaults": populate(schema.root, target_only=False),
        "targets": {"awkward": populate(schema.root, target_only=True)},
    }

    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        first = os.path.join(tmp, "config.yaml")
        with open(first, "w", encoding="utf-8") as handle:
            import yaml
            yaml.safe_dump(everything, handle, sort_keys=False,
                           allow_unicode=True)

        before = oc.resolve(schema, project_schema,
                            [oc.load_document(first)], target="awkward")

        second = os.path.join(tmp, "written.yaml")
        oc.write_config(schema, project_schema, before,
                        {"awkward": everything["targets"]["awkward"]}, second)

        after = oc.resolve(schema, project_schema,
                           [oc.load_document(second)], target="awkward")

    for layer in ("project", "settings"):
        was = flatten(getattr(before, layer))
        now = flatten(getattr(after, layer))
        for key in sorted(set(was) | set(now)):
            if key not in now:
                problems.append(f"{layer}.{key} was dropped by the writer")
            elif key not in was:
                problems.append(f"{layer}.{key} appeared from nowhere")
            elif was[key] != now[key]:
                problems.append(
                    f"{layer}.{key}: {was[key]!r} became {now[key]!r}")

    declared = len(flatten(before.settings)) + len(flatten(before.project))
    return name, declared, problems


def main():
    failed = 0
    for schema_path in TOOL_SCHEMAS:
        name, declared, problems = check(schema_path)
        if problems:
            failed += 1
            print(f"FAIL  {name} ({declared} settings)")
            for problem in problems:
                print(f"      {problem}")
        else:
            print(f"ok    {name}: {declared} settings survived the "
                  "round trip unchanged")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
