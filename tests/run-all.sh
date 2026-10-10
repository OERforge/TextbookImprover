#!/usr/bin/env bash
#
# run-all.sh -- run every check in this directory.
#
#     bash tests/run-all.sh          # cases side by side, half the processors
#     bash tests/run-all.sh -j 4     # four at a time; -j 1, one at a time
#
# Exits non-zero if anything failed, so it works as a pre-commit hook or a
# CI step. Each suite is independent and runs even if an earlier one
# failed, because knowing everything that broke is more useful than
# knowing the first thing that broke. -j goes to the suites whose cases
# can run side by side (convert, LaTeX, EPUB) and to the PDF suite, which
# builds its two books at once; each prints its cases in its own order.
#
# WHAT EACH ONE COVERS (docs/testing.md says more)
#
#   run-portability-test.py  every Python file parses on Python 3.9, the
#                          oldest supported; first, since a file that
#                          doesn't parse makes every other result
#                          meaningless on someone else's machine.
#   settings-reference.py  the docs/*-settings.md pages are current with
#                          the schemas they're written from.
#   run-spelling-tests.py  US spelling in every tracked text file.
#   run-config-tests.py    the configuration cascade, a fixture a decision.
#   run-roundtrip-test.py  writing a configuration and reading it back
#                          changes nothing.
#   run-unit-tests.py      the small functions, and the places where one
#                          fact is written down twice and could drift.
#   run-census-tests.py    the table-header guess, on tables built as OOXML.
#   run-check-tests.py     the output check, and the validators' findings.
#   run-headers-tests.py   the table-headers pre-pass end to end, a key
#                          that matches nothing set aside, the run going on.
#   run-unpack-tests.py    unpack-epub.py and unpack-jekyll.py, and an
#                          unpacked book converted.
#   run-slides-tests.py    PowerPoint decks read, checked, and remediated,
#                          and convert.py on folders of them, which needs
#                          no Pandoc (a deck in a book's folder skipped
#                          without Pandoc 3.9).
#   run-site-tests.py      unpack-site.py on saves, WARCs, and captures.
#   run-mathjax-tests.py   formulas as MathJax 2, 3, and 4 drew them.
#
#   With Pandoc 3.9 or later:
#   run-filter-tests.py    the Lua filters on six .docx fixtures.
#   run-convert-tests.py   convert.py, every source and target.
#   run-epub-tests.py      build-epub.py: the book's shape and claims.
#   run-pdf-tests.py       the pdf target, tagged; needs LuaLaTeX.
#   run-split-tests.py     split-pages.py, and what reads its pieces.
#   run-audit-tests.py     the audit, and convert.py --check-only.
#   run-latex-tests.py     LaTeX as a source, and the copies and PDFs
#                          made from it; its drawings need a TeX.
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

# This script needs bash: it reads PIPESTATUS to gate on a suite's exit
# code rather than tee's. If it was started as `sh tests/run-all.sh`,
# Ubuntu and WSL run it under dash -- re-exec under bash so it works
# either way. Must stay POSIX-parseable and above anything bash-specific.
if [ -z "${BASH_VERSION:-}" ]; then
  exec bash "$0" "$@"
fi

set -u

usage () {
  echo "usage: bash tests/run-all.sh [-j N]   (N cases at once; default half the processors)"
}

jobs=""
while [ $# -gt 0 ]; do
  case "$1" in
    -j|--jobs) [ $# -gt 1 ] || { usage >&2; exit 2; }; jobs="$2"; shift 2 ;;
    -j*) jobs="${1#-j}"; shift ;;
    --jobs=*) jobs="${1#--jobs=}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
case "$jobs" in
  "") ;;
  *[!0-9]*|0) echo "run-all.sh: -j wants a number of cases, 1 or more" >&2; exit 2 ;;
esac
# For the suites that take it; empty when -j wasn't given, so each uses
# its own default. A number alone, so it splits into two words safely.
side=""
if [ -n "$jobs" ]; then side="-j $jobs"; fi

here="$(cd "$(dirname "$0")" && pwd)"
failures=0
failed=""
skipped=""
summary="$(mktemp)"
skips="$(mktemp)"
trap 'rm -f "$summary" "$summary.suite" "$skips"' EXIT

run () {
  local script="$1"
  shift
  printf '\n=== %s\n' "$script"
  # Show the suite's output as it runs, and keep its FAIL and ERROR
  # lines for a summary at the end, where they are findable after ten
  # suites have scrolled past.
  python3 "$here/$script" "$@" 2>&1 | tee "$summary.suite"
  local status="${PIPESTATUS[0]}"
  # A check skipped for want of a tool or a library passes, and a summary
  # that says only "passed" hides it, so the skips are listed at the end.
  grep -E '^ *skip\b|\bskip: ' "$summary.suite" \
    | sed -E "s/^ *(ok +)?//; s|^|  $script: |" >> "$skips"
  if [ "$status" -ne 0 ]; then
    failures=$((failures + 1))
    failed="$failed $script"
    grep -E '^ *(FAIL|ERROR)\b' "$summary.suite" \
      | sed "s|^ *|  $script: |" >> "$summary"
  fi
  rm -f "$summary.suite"
}

# First, because a file that does not parse makes every other result
# meaningless on someone else's machine.
run run-portability-test.py

# The three settings reference pages under docs/ are written from the
# schemas; this fails when a schema changed and nobody regenerated them.
printf '\n=== settings-reference.py --check\n'
if ! python3 "$here/../util/settings-reference.py" --check; then
  failures=$((failures + 1))
  failed="$failed settings-reference.py"
fi

run run-spelling-tests.py
run run-config-tests.py
run run-roundtrip-test.py
run run-unit-tests.py
run run-census-tests.py
run run-check-tests.py
run run-headers-tests.py
run run-unpack-tests.py
run run-slides-tests.py
run run-site-tests.py
run run-mathjax-tests.py

# These convert real documents, so they need Pandoc. Skipping is
# reported rather than silent: a suite that quietly does not run is worse
# than one that fails.
needs_pandoc="run-filter-tests.py, run-convert-tests.py, run-epub-tests.py, run-pdf-tests.py, run-split-tests.py, run-audit-tests.py, and run-latex-tests.py"
if ! command -v pandoc >/dev/null 2>&1; then
  skipped="$needs_pandoc (pandoc not found)"
elif [ "$(printf '%s\n3.9\n' \
          "$(pandoc --version | head -1 | awk '{print $2}')" \
          | sort -V | head -1)" != "3.9" ]; then
  skipped="$needs_pandoc (pandoc $(pandoc --version | head -1 \
           | awk '{print $2}') is older than 3.9)"
else
  run run-filter-tests.py
  run run-convert-tests.py $side
  run run-epub-tests.py $side
  run run-pdf-tests.py $side
  run run-split-tests.py
  run run-audit-tests.py
  run run-latex-tests.py $side
fi

printf '\n'
if [ -n "$skipped" ]; then
  echo "skipped: $skipped" >&2
fi
if [ -s "$skips" ]; then
  echo "$(wc -l < "$skips") check(s) skipped, which passing doesn't cover:" >&2
  cat "$skips" >&2
fi
if [ "$failures" -gt 0 ]; then
  echo "$failures suite(s) failed:$failed" >&2
  cat "$summary" >&2
  exit 1
fi
echo "All suites passed."
