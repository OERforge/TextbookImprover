"""
pandocversion.py -- which Pandoc is installed, and the options that
depend on it.

TextbookImprover runs with Pandoc 3.9 or later, which convert.py
checks. Where a later release changed an option it passes, the option
is chosen here by the version on the PATH, so that every script passes
the same one.

Math is the one so far. Pandoc 3.11 added --math-method, made MathML
the default way of writing math in HTML, an EPUB, and a reveal.js
presentation, where it had been plain text, and deprecated --mathml,
which says so on every run; 3.9 and 3.10 know --mathml alone, and stop
on --math-method as an unknown option. So a call that writes any of
those formats asks for MathML with mathml(), whichever Pandoc it is,
and never leaves it to the default. A Lua filter's pandoc.write gives
html_math_method = 'mathml', which every release takes.

What a reader or a writer makes is another matter from the options a
Pandoc takes, and a script may run one release's readers and writers
behind another's options: the test suites' stand-in for Pandoc 3.9
(tests/pandoc39/pandoc) does. Its --version says so in a line of its
own, "Readers and writers: pandoc 3.14", and engine() gives that
release. Code that goes by what a Word file's writer wrote, or by what
the reader will make of one, asks engine(); code choosing an option
asks version().

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

import functools
import re
import subprocess

import pandocrun

# The Pandoc whose --math-method says how math is written (3.11), and
# whose --mathml is deprecated.
MATH_METHOD = (3, 11)


# The line of --version's output in which a script that runs one release's
# readers and writers behind another's options names that release.
ENGINE_LINE = "Readers and writers: "


@functools.lru_cache(maxsize=None)
def _said(pandoc):
    """What that command's --version prints; "" when it can't be run."""
    try:
        return subprocess.run(pandocrun.version(pandoc), capture_output=True,
                              text=True).stdout
    except OSError:
        return ""


def _numbers(words):
    """The version in "pandoc 3.14.1", as a tuple of up to three numbers."""
    return tuple(int(p) for p in re.findall(r"\d+", words[1] if len(words) > 1 else "")[:3])


def version(pandoc="pandoc"):
    """The version of the Pandoc a command runs (pandoc, the one on the
    PATH, by default), as a tuple of up to three numbers; () when there's
    none. It's the release whose options the command takes."""
    return _numbers(_said(pandoc).split())


def engine(pandoc="pandoc"):
    """The release whose readers and writers that command runs, as a
    tuple like version()'s: its version, unless its --version names
    another in a line of its own (ENGINE_LINE), as the suites' stand-in
    for Pandoc 3.9 does."""
    for line in _said(pandoc).splitlines()[1:]:
        if line.startswith(ENGINE_LINE):
            return _numbers(line[len(ENGINE_LINE):].split()) or version(pandoc)
    return version(pandoc)


def mathml(pandoc="pandoc"):
    """The options that have that Pandoc write math as MathML:
    --math-method=mathml from 3.11 on (MATH_METHOD), --mathml before."""
    return ["--math-method=mathml"] if version(pandoc) >= MATH_METHOD else ["--mathml"]
