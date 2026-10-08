#!/usr/bin/env python3
"""
run-portability-test.py -- check that every Python file here parses on the
oldest interpreter the project supports.

    python3 tests/run-portability-test.py

WHY THIS EXISTS

A line in lib/oerconfig.py read:

    f"name{hint or '. Use letters, digits, and . - _ only, starting '
    'with a letter.'}"

which is valid Python 3.12 and a syntax error on everything before it.
PEP 701 lifted the rule that an f-string replacement field cannot span
lines or reuse the delimiting quote; until then the tokenizer stopped at
the end of the line still inside the string. It compiled on the machine it
was written on and broke three of four test suites on the machine that ran
them.

Nothing caught it, because a syntax error is invisible to an interpreter
new enough to accept the syntax. py_compile passes, the tests pass, and
the file is unusable elsewhere. So this checks the source rather than the
interpreter.

WHAT IT CHECKS

Compiling with the oldest supported interpreter would be better, and if
one is installed (python3.9) this uses it. Nothing newer will do: 3.11
accepts what 3.10 and 3.11 added, so it can't vouch for 3.9. Otherwise it
falls back to scanning for the constructs that a newer interpreter
accepts silently:

  - f-string replacement fields spanning lines, reusing the delimiting
    quote, or containing a backslash    (3.12, PEP 701; by the tokenizer)
  - match statements                     (3.10; in the syntax tree)
  - str.removeprefix / removesuffix      (3.9)

And always, interpreter or not, since 3.9 compiles it and fails only when
the definition runs: X | Y in an annotation (3.10), found in the syntax
tree, not in the text, where a pattern's alternation in a raw string
looks like one. A module that begins with
"from __future__ import annotations" never evaluates its annotations, and
may write them so.

The scan is a heuristic and says so. A real interpreter is the authority,
which is why it is preferred when available.

The other direction too: what a newer interpreter deprecates. Python 3.13
warns when re.split is given maxsplit, or re.sub and re.subn count, as a
positional argument, and a run on 3.13 printed that warning in the middle
of convert.py's trace. An interpreter older than 3.13 says nothing, so
that is checked in the source, always.

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

import ast
import glob
import io
import os
import re
import shutil
import subprocess
import sys
import tokenize

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# The oldest interpreter the project supports. 3.9 covers RHEL 9 and
# Debian 11 as well as every Ubuntu LTS still in service, and nothing here
# needs anything newer, so there is no reason to exclude them.
MINIMUM = (3, 9)

# Constructs a newer interpreter accepts that MINIMUM does not, other than
# the f-string rules, which need the tokenizer, and those found in the
# syntax tree (later_tree).
LATER_SYNTAX = [
    (re.compile(r"\.removeprefix\(|\.removesuffix\("),
     "str.removeprefix / removesuffix", (3, 9)),
]


def sources():
    for folder in ("bin", "lib", "util", os.path.join("util", "contrib"),
                   "tests"):
        yield from sorted(glob.glob(os.path.join(ROOT, folder, "*.py")))


def older_interpreter():
    """The oldest supported interpreter, if one is installed: that version
    and no other, since a newer one accepts what came after it."""
    label = f"{MINIMUM[0]}.{MINIMUM[1]}"
    if sys.version_info[:2] == MINIMUM:
        return sys.executable, label
    found = shutil.which(f"python{label}")
    return (found, label) if found else (None, None)


def fstring_problems(path):
    """f-string constructs that need 3.12.

    Inside an f-string, 3.12's tokenizer emits the replacement field as
    ordinary tokens between FSTRING_START and FSTRING_END. That makes the
    three lifted restrictions detectable: a token on a later line than the
    brace that opened its field, a nested string reusing the delimiting
    quote, or a backslash.
    """
    problems = []
    if not hasattr(tokenize, "FSTRING_START"):
        return problems                      # too old to tell us anything

    with open(path, "rb") as handle:
        try:
            tokens = list(tokenize.tokenize(handle.readline))
        except tokenize.TokenError as exc:
            return [(0, f"could not be tokenised: {exc}")]

    quote, start_row, depth, field_row = None, 0, 0, 0
    for token in tokens:
        if token.type == tokenize.FSTRING_START:
            quote = token.string.lstrip("fFrRbB")
            start_row, depth = token.start[0], 0
        elif token.type == tokenize.FSTRING_END:
            quote = None
        elif quote is not None:
            if token.type == tokenize.OP and token.string == "{":
                depth += 1
                field_row = token.start[0]
            elif token.type == tokenize.OP and token.string == "}":
                depth = max(0, depth - 1)
            elif depth > 0:
                if token.start[0] != field_row:
                    problems.append((
                        field_row,
                        "an f-string replacement field spans lines, which "
                        "needs Python 3.12 (PEP 701)"))
                    field_row = token.start[0]
                if token.type == tokenize.STRING and token.string[:1] in quote:
                    problems.append((
                        token.start[0],
                        "an f-string replacement field reuses the "
                        f"delimiting quote {quote}, which needs Python 3.12"))
                if "\\" in token.string:
                    problems.append((
                        token.start[0],
                        "an f-string replacement field contains a "
                        "backslash, which needs Python 3.12"))
    return problems


def later_syntax(path):
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    found = []
    for pattern, what, version in LATER_SYNTAX:
        if version <= MINIMUM:
            continue
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            found.append((line, f"{what} needs Python "
                                f"{version[0]}.{version[1]}"))
    return found


def syntax_tree(path):
    """The file's syntax tree, or None and the problem when the running
    interpreter can't parse it."""
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    try:
        return ast.parse(text, filename=path), None
    except SyntaxError as exc:
        return None, (exc.lineno or 0, "doesn't parse on Python "
                      f"{sys.version_info[0]}.{sys.version_info[1]}: {exc.msg}")


def match_statements(tree):
    """match statements (3.10). The class exists only in a parser new
    enough to make one, so it's looked for by name."""
    return [(node.lineno, "match statement needs Python 3.10")
            for node in ast.walk(tree) if type(node).__name__ == "Match"]


def union_annotations(tree):
    """X | Y in an annotation Python evaluates (3.10): a parameter's or a
    return's, which are evaluated where the function is defined, and a
    variable's at a module's or a class's top level; a function's own
    variables' annotations are never evaluated. None in a module that
    begins with "from __future__ import annotations"."""
    if any(isinstance(node, ast.ImportFrom) and node.module == "__future__"
           and any(alias.name == "annotations" for alias in node.names)
           for node in tree.body):
        return []
    found = []

    def check(annotation):
        if annotation is not None and any(
                isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr)
                for n in ast.walk(annotation)):
            found.append((annotation.lineno,
                          "X | Y in an annotation needs Python 3.10"))

    def visit(node, in_function):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                arguments = child.args
                for argument in (arguments.posonlyargs + arguments.args
                                 + arguments.kwonlyargs
                                 + [arguments.vararg, arguments.kwarg]):
                    if argument is not None:
                        check(argument.annotation)
                check(child.returns)
                visit(child, True)
            elif isinstance(child, ast.ClassDef):
                visit(child, False)
            else:
                if isinstance(child, ast.AnnAssign) and not in_function:
                    check(child.annotation)
                visit(child, in_function)
    visit(tree, False)
    return found


# Arguments a newer interpreter deprecates passing by position: the
# number of positional arguments beyond which a call is warned about.
POSITIONAL_LIMITS = {"split": 2, "sub": 3, "subn": 3}


def newer_deprecations(tree):
    """Calls Python 3.13 deprecates: re.split with maxsplit, re.sub or
    re.subn with count, given by position rather than by name."""
    found = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "re"
                and node.func.attr in POSITIONAL_LIMITS
                and len(node.args) > POSITIONAL_LIMITS[node.func.attr]):
            name = "maxsplit" if node.func.attr == "split" else "count"
            found.append((node.lineno, f"re.{node.func.attr} with {name} "
                                       "passed by position, which Python "
                                       "3.13 deprecates"))
    return found


def main():
    files = list(sources())
    if not files:
        print("No Python files found.")
        return 1

    interpreter, label = older_interpreter()
    problems = []

    if interpreter:
        print(f"Compiling {len(files)} file(s) with Python {label}.")
        for path in files:
            result = subprocess.run(
                [interpreter, "-m", "py_compile", path],
                capture_output=True, text=True, stdin=subprocess.DEVNULL)
            if result.returncode:
                last = [l for l in result.stderr.splitlines() if l.strip()]
                problems.append((path, 0, last[-1] if last else "failed"))
    else:
        print(f"No Python {MINIMUM[0]}.{MINIMUM[1]} interpreter installed, "
              "so scanning the source instead.")
        print("  This is a heuristic; a real interpreter is the authority.")

    for path in files:
        tree, problem = syntax_tree(path)
        found = [problem] if problem else (
            union_annotations(tree) + newer_deprecations(tree))
        if not interpreter:
            found += fstring_problems(path) + later_syntax(path)
            if tree is not None:
                found += match_statements(tree)
        for line, what in sorted(found):
            problems.append((path, line, what))

    for path, line, what in problems:
        where = os.path.relpath(path, ROOT)
        print(f"  FAIL  {where}"
              + (f":{line}" if line else "") + f": {what}")

    if problems:
        print(f"\n{len(problems)} portability problem(s). The project "
              f"supports Python {MINIMUM[0]}.{MINIMUM[1]} and later, and "
              "runs without warnings on the newest.")
        return 1
    print(f"\nall {len(files)} file(s) are portable to Python "
          f"{MINIMUM[0]}.{MINIMUM[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
