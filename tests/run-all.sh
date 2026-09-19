#!/usr/bin/env bash
#
# run-all.sh -- run every check in this directory.
#
#     bash tests/run-all.sh
#
# Exits non-zero if anything failed, so it works as a pre-commit hook or a
# CI step. Each suite is independent and runs even if an earlier one
# failed, because knowing everything that broke is more useful than
# knowing the first thing that broke.
#
# WHAT EACH ONE COVERS
#
#   run-config-tests.py    the configuration cascade: what a false
#                          override means, what an explicit null means,
#                          whether lists append, which identifiers are
#                          valid XML names, what happens when a setting is
#                          written twice. Twenty-two fixtures, each
#                          pinning one decision.
#
#   run-roundtrip-test.py  that writing a configuration and reading it
#                          back changes nothing. The test the v0.1 sample
#                          writer needed and did not have: it dropped
#                          three settings from a file it called complete.
#
#   run-unit-tests.py      the small pure functions that decide filenames
#                          and directory names, and the places where one
#                          fact is written down twice and could drift.
#
#   run-headers-tests.py   the table-headers pre-pass end to end: keys,
#                          the sidecar's values and aliases, the new-rows
#                          file, the report, and the unmatched-key stop.
#
#   run-census-tests.py    the sidecar guess in lib/tablecensus.py,
#                          against tables built as OOXML so each carries
#                          exactly the formatting signals it means to.
#
#   settings-reference.py  the docs/*-settings.md pages are current with
#                          the schemas they are written from.
#
#   run-portability-test.py
#                          that every Python file parses on the oldest
#                          interpreter the project supports. A syntax
#                          error is invisible to an interpreter new enough
#                          to accept the syntax, so this cannot be left to
#                          the suites themselves.
#
#   run-filter-tests.py    the accessibility work the Lua filters do,
#                          against four small .docx fixtures. Needs
#                          Pandoc.
#
# Copyright 2026 Robert Szarka
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

set -u

here="$(cd "$(dirname "$0")" && pwd)"
failures=0
skipped=""

run () {
  local script="$1"
  shift
  printf '\n=== %s\n' "$script"
  if ! python3 "$here/$script" "$@"; then
    failures=$((failures + 1))
  fi
}

# First, because a file that does not parse makes every other result
# meaningless on someone else's machine.
run run-portability-test.py

# The three settings reference pages under docs/ are written from the
# schemas; this fails when a schema changed and nobody regenerated them.
printf '\n=== settings-reference.py --check\n'
if ! python3 "$here/../util/settings-reference.py" --check; then
  failures=$((failures + 1))
fi

run run-config-tests.py
run run-roundtrip-test.py
run run-unit-tests.py
run run-census-tests.py
run run-headers-tests.py

# The filter tests convert real documents, so they need Pandoc. Skipping
# is reported rather than silent: a suite that quietly does not run is
# worse than one that fails.
if ! command -v pandoc >/dev/null 2>&1; then
  skipped="run-filter-tests.py and run-epub-tests.py (pandoc not found)"
elif [ "$(printf '%s\n3.9\n' \
          "$(pandoc --version | head -1 | awk '{print $2}')" \
          | sort -V | head -1)" != "3.9" ]; then
  skipped="run-filter-tests.py (pandoc $(pandoc --version | head -1 \
           | awk '{print $2}') is older than 3.9)"
else
  run run-filter-tests.py
  run run-epub-tests.py
fi

printf '\n'
if [ -n "$skipped" ]; then
  echo "skipped: $skipped" >&2
fi
if [ "$failures" -gt 0 ]; then
  echo "$failures suite(s) failed." >&2
  exit 1
fi
echo "All suites passed."
