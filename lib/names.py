"""
names.py -- safe names for the files an output holds.

A page's name and an image's path travel into a manifest, an EPUB, and
an LMS as hrefs. Percent-encoding a space is correct and not enough: at
least one LMS takes the href literally and finds no file. So the files
an output holds get names that need no encoding, derived from the
source's names by one rule, applied identically in Python and in the
Lua filter that rewrites a page's references at render time. With
media.lowercase, the names a target copies files under are lowercased
too, the ASCII letters only, as Lua lowercases them.

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
import string

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


ASCII_LOWER = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)


def output_path(path, safe=True, lower=False):
    """The name a file a page names is copied under, beside the page: its
    safe name (safe_path) beside a page, its own beside a Markdown or
    AsciiDoc copy; lower, with media.lowercase, its ASCII letters
    lowercased."""
    path = safe_path(path) if safe else path
    return path.translate(ASCII_LOWER) if lower else path


def safe_stem(stem):
    """A page name: no slashes either."""
    return _segment(stem.replace("/", "-")) if stem.strip("/") else "page"


def is_safe(path):
    return safe_path(path) == path


def case_match(base, path):
    """path, relative to base, found as a file system that ignores case
    finds it (macOS's and Windows's, where a book or a deck was likely
    made), a part at a time, where exactly one entry matches each part;
    or None."""
    found, current = [], base
    for part in os.path.normpath(path).split(os.sep):
        if part in ("", "."):
            continue
        if part != "..":
            try:
                entries = os.listdir(current)
            except OSError:
                return None
            if part not in entries:
                matches = [e for e in entries if e.lower() == part.lower()]
                if len(matches) != 1:
                    return None
                part = matches[0]
        found.append(part)
        current = os.path.join(current, part)
    return os.path.join(*found) if found and os.path.isfile(current) else None
