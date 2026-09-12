#!/usr/bin/env python3
"""
run-config-tests.py -- check an implementation of the configuration
cascade against the conformance fixtures.

    python3 tests/run-config-tests.py

Each fixture in tests/config/ is a directory holding the input files and
an expected.yaml saying what resolving them must produce. The fixtures
are the merge rules written down in a form a machine can check, which
matters because the rules will eventually be implemented more than once:
a second time if the conversion and packaging halves ever become separate
repositories on separate release cadences, and a third time in whatever
the web front end is written in. Prose in a comment cannot tell you
whether two implementations agree. These can.

expected.yaml keys:

    target           resolve this target; omit to resolve defaults only
    expect           dotted setting path -> value it must resolve to
    expect_project   the same, for the project layer
    allow_unknown    tolerate keys the schema does not declare
    warns            substring that must appear in a warning
    error            substring that must appear in the error raised

A fixture with `error` must fail; one without must succeed.

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

import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))

import yaml                                          # noqa: E402
import oerconfig as oc                               # noqa: E402

SCHEMAS = {
    "conversion.yaml": os.path.join(os.path.dirname(HERE), "bin",
                                    "schema-conversion.yaml"),
    "packaging.yaml": os.path.join(os.path.dirname(HERE), "bin",
                                   "schema-packaging.yaml"),
}
PROJECT_SCHEMA = os.path.join(os.path.dirname(HERE), "lib",
                              "schema-project.yaml")


def dotted(values, path):
    node = values
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(path)
        node = node[part]
    return node


def run(case):
    """Return a list of failure descriptions, empty when the case passes."""
    expected = yaml.safe_load(
        open(os.path.join(case, "expected.yaml"), encoding="utf-8")) or {}

    documents, schema_path = [], None
    want_error = expected.get("error")

    # Loading can fail on its own account -- a file that is not YAML, or
    # one that sets the same key twice -- so a fixture may expect an error
    # from this step rather than from the merge. Letting it escape here
    # turned such a fixture into a traceback instead of a result.
    try:
        # A project file is always the lower-precedence layer.
        for name in ("project.yaml", "conversion.yaml", "packaging.yaml"):
            path = os.path.join(case, name)
            if not os.path.isfile(path):
                continue
            documents.append(oc.load_document(path))
            if name in SCHEMAS:
                schema_path = SCHEMAS[name]
    except oc.ConfigError as exc:
        if want_error and want_error in str(exc):
            return []
        return [f"reading the configuration failed: {exc}"]

    if schema_path is None:
        schema_path = SCHEMAS["conversion.yaml"]

    schema = oc.load_schema(schema_path)
    project_schema = oc.load_schema(PROJECT_SCHEMA)

    try:
        resolved = oc.resolve(schema, project_schema, documents,
                              target=expected.get("target"),
                              allow_unknown=expected.get("allow_unknown",
                                                         False))
    except oc.ConfigError as exc:
        if want_error and want_error in str(exc):
            return []
        if want_error:
            return [f"expected an error mentioning {want_error!r}, got:\n"
                    f"      {exc}"]
        return [f"unexpected error: {exc}"]

    if want_error:
        return [f"expected an error mentioning {want_error!r}, but it "
                "resolved cleanly"]

    problems = []
    for path, want in (expected.get("expect") or {}).items():
        try:
            got = dotted(resolved.settings, path)
        except KeyError:
            problems.append(f"{path} is not in the resolved settings")
            continue
        if got != want:
            problems.append(f"{path}: expected {want!r}, got {got!r}")

    for path, want in (expected.get("expect_project") or {}).items():
        try:
            got = dotted(resolved.project, path)
        except KeyError:
            problems.append(f"project.{path} is not in the resolved project")
            continue
        if got != want:
            problems.append(
                f"project.{path}: expected {want!r}, got {got!r}")

    warns = expected.get("warns")
    if warns and not any(warns in w for w in resolved.warnings):
        problems.append(f"expected a warning mentioning {warns!r}; warnings "
                        f"were {resolved.warnings}")

    return problems


def main():
    cases = sorted(glob.glob(os.path.join(HERE, "config", "*")))
    if not cases:
        sys.exit("No fixtures found under tests/config/.")

    failed = 0
    for case in cases:
        name = os.path.basename(case)
        problems = run(case)
        if problems:
            failed += 1
            print(f"FAIL  {name}")
            for problem in problems:
                print(f"      {problem}")
        else:
            print(f"ok    {name}")

    print()
    print(f"{len(cases) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
