"""
names.py -- safe names for the files an output holds.

A page's name and an image's path travel into a manifest, an EPUB, and
an LMS as hrefs. Percent-encoding a space is correct and not enough: at
least one LMS takes the href literally and finds no file. So the files
an output holds get names that need no encoding, derived from the
source's names by one rule, applied identically in Python and in the
Lua filter that rewrites a page's references at render time.

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

import re

# What may stay: ASCII letters and digits, dot, underscore, hyphen, and
# the slash that separates directories. Everything else -- spaces, %,
# =, parentheses, non-ASCII letters -- becomes a hyphen, runs collapsed.
# safe-media.lua applies the same rule; keep the two together.
UNSAFE = re.compile(r"[^A-Za-z0-9._/-]+")


def _segment(part):
    part = UNSAFE.sub("-", part)
    part = re.sub(r"-+(?=\.)", "", part)      # no hyphen before an extension
    return part.strip("-") or "-"


def safe_path(path):
    """A path with every segment made safe; a directory stays one."""
    return "/".join(_segment(part) for part in path.split("/"))


def safe_stem(stem):
    """A page name: no slashes either."""
    return _segment(stem.replace("/", "-")) if stem.strip("/") else "page"


def is_safe(path):
    return safe_path(path) == path
