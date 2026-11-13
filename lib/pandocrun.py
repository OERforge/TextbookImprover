"""
pandocrun.py -- the command every script starts Pandoc with, so that
no run reads Pandoc's data folders.

Pandoc looks for a data file (a format's default template, the Word
reference document, the EPUB stylesheet, the words it inserts, an
init.lua run before every Lua filter) in the user data folder, or the
folder --data-dir names; then, from Pandoc 3.14, in each folder the
environment variable PANDOC_DATA_DIRS lists; and then in its own
copies. TextbookImprover builds on Pandoc's own copies, so a template a
person keeps in their Pandoc folder for other work, or one a package
installed in a PANDOC_DATA_DIRS folder, would otherwise change every
book they convert, and a book would come out differently on another
machine. So every Pandoc a script starts gets --data-dir naming an
empty folder this module makes, and the variable is taken out of this
process's environment as the module is imported, so that no program
started afterward sees it: pandoc -D, which ignores the user data
folder, reads the variable's folders (Pandoc 3.14).

A book's own template, stylesheet, or reference document is given
with a setting instead (html.template, html.css, epub.css,
docx.reference_doc, pdf.template, slides.reference_doc), a file kept
with the book's configuration. notices() says when Pandoc's folders
hold a file one of those settings would take.

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

import atexit
import os
import re
import shutil
import subprocess
import tempfile

# The variable's value as this process found it, before it was taken out.
DATA_DIRS = os.environ.pop("PANDOC_DATA_DIRS", None)

# An empty folder of this process's own, given to every Pandoc as its
# user data folder, and removed when the process ends.
EMPTY = tempfile.mkdtemp(prefix="ti-pandoc-data-")
atexit.register(shutil.rmtree, EMPTY, True)


def command(program="pandoc"):
    """The start of a command line that runs Pandoc (program, the one on
    the PATH by default) with no data folder of its own."""
    return [program, "--data-dir", EMPTY]


PANDOC = command()


def version(program="pandoc"):
    """The command that asks Pandoc (program, the one on the PATH by
    default) its version: --version alone, which reads no data file, as
    a wrapper that answers it for a Pandoc it stands in for expects it."""
    return [program, "--version"]


VERSION = version()

# Files in a Pandoc data folder that change what a run writes, each with
# the setting that gives a book its own.
SETTINGS = (
    ("templates/default.html5", "html.template"),
    ("templates/default.html", "html.template"),
    ("templates/default.latex", "pdf.template"),
    ("templates/styles.html", "html.css"),
    ("epub.css", "epub.css"),
    ("reference.docx", "docx.reference_doc"),
    ("reference.pptx", "slides.reference_doc"),
    ("init.lua", None),
)


def user_folder(program="pandoc"):
    """The user data folder the Pandoc on the PATH would read, as its
    --version says, or None."""
    try:
        done = subprocess.run([program, "--version"], capture_output=True, text=True)
    except OSError:
        return None
    found = re.search(r"^User data directory: (.+)$", done.stdout or "", re.M)
    return found.group(1).strip() if found else None


def notices(program="pandoc"):
    """Lines saying what of Pandoc's data folders a run leaves alone: each
    file in the user data folder or a PANDOC_DATA_DIRS folder that one of
    TextbookImprover's settings would take, with the setting, and that
    the variable is left out when it was set. Empty when there's nothing
    to say."""
    lines = []
    folders = []
    user = user_folder(program)
    if user:
        folders.append(user)
    if DATA_DIRS:
        folders.extend(d for d in DATA_DIRS.split(os.pathsep) if os.path.isabs(d))
        lines.append("NOTE: PANDOC_DATA_DIRS is set; TextbookImprover's runs leave it out, "
                     "as they leave out Pandoc's user data folder, so that a book comes out "
                     "the same on every machine.")
    for folder in folders:
        for name, setting in SETTINGS:
            path = os.path.join(folder, *name.split("/"))
            if not os.path.isfile(path):
                continue
            if setting:
                lines.append(f"NOTE: {path} isn't read: TextbookImprover's runs leave "
                             f"Pandoc's data folders out. To give a book its own, copy "
                             f"the file into a folder beside its configuration, such as "
                             f"templates/, and name it in {setting}.")
            else:
                lines.append(f"NOTE: {path} isn't run: TextbookImprover's runs leave "
                             f"Pandoc's data folders out.")
    return lines
