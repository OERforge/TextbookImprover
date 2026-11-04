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

# The Pandoc whose --math-method says how math is written (3.11), and
# whose --mathml is deprecated.
MATH_METHOD = (3, 11)


@functools.lru_cache(maxsize=None)
def version(pandoc="pandoc"):
    """The version of the Pandoc a command runs (pandoc, the one on the
    PATH, by default), as a tuple of up to three numbers; () when there's
    none."""
    try:
        words = subprocess.run([pandoc, "--version"], capture_output=True,
                               text=True).stdout.split()
    except OSError:
        return ()
    return tuple(int(p) for p in re.findall(r"\d+", words[1] if len(words) > 1 else "")[:3])


def mathml(pandoc="pandoc"):
    """The options that have that Pandoc write math as MathML:
    --math-method=mathml from 3.11 on (MATH_METHOD), --mathml before."""
    return ["--math-method=mathml"] if version(pandoc) >= MATH_METHOD else ["--mathml"]
