"""
sidecars.py -- what a sidecar's values mean, read the same way by every
part of the pipeline that reads them.

The filter (figures-and-tables.lua) and the Python that writes a book's
decisions back into its sources read the same image-alt sidecar. They
had each their own idea of the decorative marker: the filter took
"[decorative]" or "decorative" in any case, the Python only the exact
"[decorative]", so a row saying "Decorative" made an image decorative
on the pages and gave the author's copy the alt text "Decorative".

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

# Accepted spellings of the decorative marker, matched case-insensitively
# after trimming. figures-and-tables.lua's DECORATIVE_MARKERS is the same
# list; tests/run-unit-tests.py holds the two together.
DECORATIVE_MARKERS = ("[decorative]", "decorative")


def is_decorative(value):
    """Whether a sidecar's alt text is the decorative marker."""
    return (value or "").strip().lower() in DECORATIVE_MARKERS


# The schemes a bare link's Replacement can be an address in, as the
# filter's BARE_SCHEMES: an address replaces the link's address and its
# text, and anything else replaces only its text.
ADDRESS_SCHEMES = ("http", "https", "ftp")


def is_address(value):
    """Whether a bare-links sidecar's Replacement is an address, as
    figures-and-tables.lua's web_scheme tells: a scheme it names, then ://."""
    match = re.match(r"([A-Za-z][A-Za-z0-9+.-]*)://", (value or "").strip())
    return bool(match) and match.group(1).lower() in ADDRESS_SCHEMES
