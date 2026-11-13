#!/usr/bin/env bash
#
# run-all.sh -- run every check in this directory.
#
#     bash tests/run-all.sh          # side by side, on half the processors
#     bash tests/run-all.sh -j 4     # four things at a time; -j 1, one at a time
#     PATH="$PWD/tests/pandoc39:$PATH" bash tests/run-all.sh
#                                    # as Pandoc 3.9 would (tests/pandoc39/pandoc)
#
# Exits non-zero if anything failed, so it works as a pre-commit hook or a
# CI step. Each suite is independent and runs even if another failed,
# because knowing everything that broke is more useful than knowing the
# first thing that broke.
#
# -j is how many things run at once in the whole run. The suites that do
# one thing at a time run in turn, in the order below, as one of the
# run's workers. Beside them, from the start, run the suites whose cases
# can run side by side (convert, EPUB, LaTeX, decks) and the PDF suite,
# which builds its books so: a case or a book holds one of the other
# workers while it runs (tests/parallel.py), and of them all once the
# suites run in turn are done. Each suite's output is printed whole, in
# the order below, the suite being waited for as it comes. With -j 1
# every suite runs in turn, each printing as it goes.
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
#   run-slides-tests.py    PowerPoint decks read, checked, remediated, and
#                          converted, and convert.py on folders of them,
#                          which needs no Pandoc but to convert (a deck
#                          converted, or in a book's folder, skipped
#                          without Pandoc 3.9; a deck's PDF without
#                          LuaLaTeX, ltx-talk, or what the deck loads).
#   run-site-tests.py      unpack-site.py on saves, WARCs, and captures.
#   run-cnx-tests.py       unpack-cnx.py on books written in CNXML, baked
#                          as OpenStax bakes them, and one converted, which
#                          needs Pandoc 3.9 (skipped without).
#   run-mathjax-tests.py   formulas as MathJax 2, 3, and 4 drew them.
#
#   With Pandoc 3.9 or later:
#   run-filter-tests.py    the Lua filters on six .docx fixtures.
#   run-split-tests.py     split-pages.py, and what reads its pieces.
#   run-audit-tests.py     the audit, and convert.py --check-only.
#   run-convert-tests.py   convert.py, every source and target.
#   run-epub-tests.py      build-epub.py: the book's shape and claims.
#   run-latex-tests.py     LaTeX as a source, and the copies and PDFs
#                          made from it; its drawings and builds need a
#                          TeX with the packages its books load (skipped
#                          without).
#   run-decks-tests.py     decks written in Markdown: each deck's page,
#                          its copies, its PDF through ltx-talk, which
#                          needs LuaLaTeX, ltx-talk, and what the decks
#                          load (skipped without),
#                          its PowerPoint file, which needs Pandoc
#                          3.10.1, and its reveal.js presentation, which
#                          needs 3.12 (each skipped with an older one),
#                          twelve of whose checks open it in a browser
#                          with the optional Playwright and its Chromium
#                          (skipped without).
#   run-pdf-tests.py       the pdf target, tagged; needs LuaLaTeX and the
#                          packages its books load (skipped without).
#                          Last, as the longest: its books are built
#                          before any is checked, so it has nothing to
#                          print until near its end.
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
# code rather than tee's, and keeps its list of suites in arrays. If it
# was started as `sh tests/run-all.sh`,
# Ubuntu and WSL run it under dash -- re-exec under bash so it works
# either way. Must stay POSIX-parseable and above anything bash-specific.
if [ -z "${BASH_VERSION:-}" ]; then
  exec bash "$0" "$@"
fi

set -u

# Pandoc 3.14 looks in the folders PANDOC_DATA_DIRS names for templates,
# init.lua, and its other data files; each suite drops it too, for when
# it's run by itself.
unset PANDOC_DATA_DIRS

usage () {
  echo "usage: bash tests/run-all.sh [-j N]   (N things at once; default half the processors)"
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
  *[!0-9]*|0) echo "run-all.sh: -j wants a number, 1 or more" >&2; exit 2 ;;
esac

here="$(cd "$(dirname "$0")" && pwd)"

# Without -j, the suites' own default: half the processors.
if [ -z "$jobs" ]; then
  jobs="$(python3 "$here/parallel.py" --default-jobs 2>/dev/null)"
  case "$jobs" in ""|*[!0-9]*|0) jobs=1 ;; esac
fi

# Under the stand-in for Pandoc 3.9 (tests/pandoc39 first on the PATH),
# the Pandoc it runs, named in PANDOC39_REAL for every suite: the first
# pandoc on the PATH that isn't a stand-in, as the stand-in finds it. A
# check that hides the PATH's other programs from a run keeps a link to
# the stand-in, which would find no other Pandoc there.
stand_in () { head -c 512 "$1" 2>/dev/null | grep -qF "pandoc -- a stand-in for Pandoc 3.9"; }
if [ -z "${PANDOC39_REAL:-}" ] && stand_in "$(command -v pandoc 2>/dev/null)"; then
  IFS=: read -r -a folders <<< "$PATH"
  for folder in "${folders[@]}"; do
    candidate="${folder:-.}/pandoc"
    if [ -f "$candidate" ] && [ -x "$candidate" ] && ! stand_in "$candidate"; then
      PANDOC39_REAL="$(cd "${folder:-.}" && pwd)/pandoc"
      export PANDOC39_REAL
      break
    fi
  done
  echo "Running as Pandoc 3.9 would, through tests/pandoc39/pandoc, which runs" \
       "${PANDOC39_REAL:-no other Pandoc: none is on the PATH}."
fi

failures=0
failed=""
skipped=""
summary="$(mktemp)"
skips="$(mktemp)"
outs="$(mktemp -d)"
trap 'rm -rf "$summary" "$skips" "$outs"' EXIT
# Ctrl-C ends the run here too, with its files removed: the suites take
# the signal themselves, and the ones run in turn stop when the folder
# they write to is gone.
trap 'exit 130' INT TERM

# The suites, in the order their output is printed, and how each runs
# side by side with the rest: "cases" for one that takes -j and has each
# of its cases or builds hold one of the run's workers, "whole" for one
# that does one thing at a time, which run in turn, in this order, as
# one worker.
names=()
kinds=()
suite () { names+=("$1"); kinds+=("${2:-whole}"); }

# First, because a file that does not parse makes every other result
# meaningless on someone else's machine.
suite run-portability-test.py
# The three settings reference pages under docs/ are written from the
# schemas; this fails when a schema changed and nobody regenerated them.
suite settings-reference.py
suite run-spelling-tests.py
suite run-config-tests.py
suite run-roundtrip-test.py
suite run-unit-tests.py
suite run-census-tests.py
suite run-check-tests.py
suite run-headers-tests.py
suite run-unpack-tests.py
suite run-slides-tests.py
suite run-site-tests.py
suite run-cnx-tests.py
suite run-mathjax-tests.py

# These convert real documents, so they need Pandoc. Skipping is
# reported rather than silent: a suite that quietly does not run is worse
# than one that fails.
needs_pandoc="run-filter-tests.py, run-split-tests.py, run-audit-tests.py, run-convert-tests.py, run-epub-tests.py, run-latex-tests.py, run-decks-tests.py, and run-pdf-tests.py"
if ! command -v pandoc >/dev/null 2>&1; then
  skipped="$needs_pandoc (pandoc not found)"
elif [ "$(printf '%s\n3.9\n' \
          "$(pandoc --version | head -1 | awk '{print $2}')" \
          | sort -V | head -1)" != "3.9" ]; then
  skipped="$needs_pandoc (pandoc $(pandoc --version | head -1 \
           | awk '{print $2}') is older than 3.9)"
else
  suite run-filter-tests.py
  suite run-split-tests.py
  suite run-audit-tests.py
  suite run-convert-tests.py cases
  suite run-epub-tests.py cases
  suite run-latex-tests.py cases
  suite run-decks-tests.py cases
  suite run-pdf-tests.py cases
fi

# A suite's command, in the array `command`: the settings pages' check is
# a utility's, the rest are this folder's. What follows the suite's kind
# goes before its script: parallel.py, side by side.
command_of () {
  local script="$1" kind="$2"
  shift 2
  if [ "$script" = settings-reference.py ]; then
    command=(python3 "$@" "$here/../util/settings-reference.py" --check)
  elif [ "$kind" = cases ]; then
    command=(python3 "$@" "$here/$script" -j "$jobs")
  else
    command=(python3 "$@" "$here/$script")
  fi
}

# What a suite's output and exit status add to the summary at the end.
account () {
  local script="$1" status="$2" output="$3"
  if [ "$script" = settings-reference.py ]; then
    if [ "$status" -ne 0 ]; then
      failures=$((failures + 1))
      failed="$failed $script"
    fi
    return
  fi
  # A check skipped for want of a tool or a library passes, and a summary
  # that says only "passed" hides it, so the skips are listed at the end.
  grep -E '^ *skip\b|\bskip: ' "$output" \
    | sed -E "s/^ *(ok +)?//; s|^|  $script: |" >> "$skips"
  if [ "$status" -ne 0 ]; then
    failures=$((failures + 1))
    failed="$failed $script"
    # Its FAIL and ERROR lines, for a summary at the end, where they are
    # findable after twenty suites have scrolled past.
    grep -E '^ *(FAIL|ERROR)\b' "$output" \
      | sed "s|^ *|  $script: |" >> "$summary"
  fi
}

heading () {
  if [ "$1" = settings-reference.py ]; then
    printf '\n=== %s --check\n' "$1"
  else
    printf '\n=== %s\n' "$1"
  fi
}

if [ "$jobs" -eq 1 ]; then
  # In turn: each suite's output shown as it runs.
  for i in "${!names[@]}"; do
    heading "${names[$i]}"
    command_of "${names[$i]}" "${kinds[$i]}"
    "${command[@]}" 2>&1 | tee "$outs/output"
    account "${names[$i]}" "${PIPESTATUS[0]}" "$outs/output"
  done
else
  # Side by side, on one count of workers. The suites that take -j share
  # a folder of files, one a worker, which each case or build holds a
  # lock on while it runs (parallel.py): one fewer than -j, since the
  # suites run in turn are a worker too, whose file is added when they're
  # done.
  mkdir "$outs/slots"
  i=1
  while [ "$i" -lt "$jobs" ]; do
    : > "$outs/slots/$i"
    i=$((i + 1))
  done
  OER_TEST_SLOTS="$outs/slots"
  export OER_TEST_SLOTS
  echo "Running the suites side by side, $jobs thing(s) at a time (-j 1 for one at a time)."
  # Each suite is started through parallel.py, which has it take Ctrl-C
  # though this script isn't waiting on it, writes to a file of its own,
  # and leaves its exit status beside it when it ends.
  start () {
    command_of "${names[$1]}" "${kinds[$1]}" "$here/parallel.py"
    "${command[@]}" > "$outs/$1.output" 2>&1
    # Said to no one once the run is stopped and its folder gone.
    { echo "$?" > "$outs/$1.status"; } 2>/dev/null
  }
  running=()
  for i in "${!names[@]}"; do
    if [ "${kinds[$i]}" = cases ]; then
      start "$i" &
      running[$i]="$!"
    fi
  done
  (
    for i in "${!names[@]}"; do
      if [ "${kinds[$i]}" = whole ]; then
        # Stopped: this script gone, and its folder with it, or the
        # suite ended by Ctrl-C, which this loop doesn't take.
        [ -d "$outs/slots" ] || exit
        start "$i"
        [ "$(cat "$outs/$i.status" 2>/dev/null)" != 130 ] || exit
      fi
    done
    [ ! -d "$outs/slots" ] || : > "$outs/slots/0"
  ) &
  for i in "${!names[@]}"; do
    if [ "${kinds[$i]}" = whole ]; then
      running[$i]="$!"
    fi
  done
  # Printed in the list's order: what the suite being waited for has
  # written so far, as it comes, and the rest of it once it ends.
  for i in "${!names[@]}"; do
    heading "${names[$i]}"
    shown=0
    # Until it says how it ended, or what was running it is gone.
    until [ -s "$outs/$i.status" ] || ! kill -0 "${running[$i]}" 2>/dev/null; do
      if [ -f "$outs/$i.output" ]; then
        size="$(wc -c < "$outs/$i.output")"
        if [ "$size" -gt "$shown" ]; then
          tail -c "+$((shown + 1))" "$outs/$i.output" | head -c "$((size - shown))"
          shown="$size"
        fi
      fi
      sleep 0.5
    done
    if [ ! -s "$outs/$i.status" ]; then
      # Stopped from outside before it could say how it ended.
      echo "  ERROR ${names[$i]} was stopped before it ended" >> "$outs/$i.output"
      echo 1 > "$outs/$i.status"
    fi
    tail -c "+$((shown + 1))" "$outs/$i.output"
    account "${names[$i]}" "$(cat "$outs/$i.status")" "$outs/$i.output"
  done
  wait
fi

printf '\n'
if [ -n "$skipped" ]; then
  echo "skipped: $skipped" >&2
fi
if [ -s "$skips" ]; then
  # A skip line that stands for several checks says how many
  # ("skip  12 checks of ..."), and counts as that many; any other, one.
  count="$(awk '{ if (match($0, /skip +[0-9]+ checks /)) {
                    n += substr($0, RSTART + 4, RLENGTH - 11) + 0 } else n += 1 }
                END { print n }' "$skips")"
  echo "$count check(s) skipped, which passing doesn't cover:" >&2
  cat "$skips" >&2
fi
if [ "$failures" -gt 0 ]; then
  echo "$failures suite(s) failed:$failed" >&2
  cat "$summary" >&2
  exit 1
fi
echo "All suites passed."
