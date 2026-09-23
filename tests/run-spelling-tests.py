#!/usr/bin/env python3
"""
run-spelling-tests.py -- US spelling, held by a check rather than by rereading.

Prose here is US English (recognize, behavior, labeled, color), and so are
the names of our own functions, settings, and checks. UK spellings crept
in repeatedly and were corrected by hand, and some sat in code for months
because nothing looked. This scans every tracked text file and fails on
any, naming the file and line.

Left alone, on purpose:
  - a released section of CHANGELOG.md, which is what went into a
    release's notes and is history;
  - names that aren't ours: ARIA's aria-labelledby, and the title of an
    IMS document ("Notice and Licence");
  - util/contrib/, which holds scripts contributed from elsewhere, and
    the IMS schemas, which must stay byte-identical;
  - an old name kept working until 1.0 (bookcontents.unrecognised_roles),
    which is listed below with the file it may appear in.

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
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TEXT = (".md", ".py", ".lua", ".yaml", ".yml", ".sh", ".css", ".txt")
SKIP_DIRS = ("util/contrib/", "schemas/")

# UK spellings, as word pieces. -ise verbs are listed by stem so that
# "precise", "otherwise", and "exercise" never match.
UK = re.compile(
    r"\b(\w*(?:behaviour|colour|favour|honour|labour|neighbour|flavour|"
    r"centre|licence|catalogue|artefact|programme)\w*|"
    r"\w*(?:recognis|organis|normalis|summaris|categoris|prioritis|"
    r"optimis|initialis|customis|minimis|maximis|serialis|visualis|"
    r"standardis|utilis|authoris|finalis|apologis|emphasis(?:e|ed|es|ing)\b)"
    r"\w*|analys(?:e|ed|es|ing)|\w*(?:labelled|labelling|modelling|"
    r"travelled|travelling|cancelled|cancelling|signalled|totalled))\b",
    re.I)

# Names that aren't ours, or an old name kept until 1.0: (file, word).
ALLOWED = {
    (None, "aria-labelledby"), (None, "labelledby"),
    (None, "Licence"),                      # "Notice and Licence", IMS
    ("lib/bookcontents.py", "unrecognised_roles"),
    ("CHANGELOG.md", "unrecognised_roles"),     # the entries announcing
    ("CHANGELOG.md", "normalise"),              # the renames name the old
    ("CHANGELOG.md", "NORMALISE_MATH_ALT"),     # spellings
    ("tests/run-spelling-tests.py", None),  # this file names them all
}


def tracked():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                         text=True)
    if out.returncode != 0:
        return None
    return [p for p in out.stdout.split("\n")
            if p.endswith(TEXT) and not p.startswith(SKIP_DIRS)]


def unreleased_lines(path, lines):
    """For CHANGELOG.md, only the lines above the first released version."""
    if path != "CHANGELOG.md":
        return lines
    for index, line in enumerate(lines):
        if re.match(r"## \[\d", line):
            return lines[:index]
    return lines


def allowed(path, word, line):
    if (path, None) in ALLOWED:
        return True
    if (None, word) in ALLOWED or (path, word) in ALLOWED:
        return True
    if "aria-labelledby" in line and "labelledby" in word.lower():
        return True
    if word == "Licence" and "Notice and Licence" in line:
        return True
    return False


def main():
    files = tracked()
    if files is None:
        print("  skip  not a git checkout, so there is no list of files")
        return 0
    found = []
    for path in files:
        full = os.path.join(ROOT, path)
        try:
            with open(full, encoding="utf-8") as fh:
                lines = fh.read().split("\n")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(unreleased_lines(path, lines), 1):
            for m in UK.finditer(line):
                word = m.group(1)
                if (None, word) in ALLOWED and word != "Licence":
                    continue
                if not allowed(path, word, line):
                    found.append((path, number, word))
    checks = [
        ("no UK spelling in the prose or the names", not found),
        ("the checker sees a UK spelling when there is one",
         bool(UK.search("the colour was normalised")) and not UK.search(
             "precise, otherwise, exercise, analysis, emphasis")),
    ]
    failed = 0
    for name, ok in checks:
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
        failed += not ok
    for path, number, word in found:
        print(f"        {path}:{number}: {word}")
    print(f"\n{'all spelling checks passed' if not failed else str(failed) + ' check(s) failed'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
