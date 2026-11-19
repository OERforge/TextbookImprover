"""Where a project's files are.

One object, made from the project's folder, answers every question a
script has about a path in it: where the settings are, where a part's
sources, sidecars, reports, and intermediates are, where a target's or a
package's folder is, where a temporary folder goes, and which folder
Pandoc and LaTeX run in. A script asks; it doesn't put a project's path
together itself, so the layout is written down once, here.

    paths = projectpaths.of(args.dir)
    out_dir = paths.target_dir(name, resolved["output_dir"])
    work = paths.temp_dir("build-epub-")
    subprocess.run(command, cwd=paths.run_dir())

A function that is handed the book's folder asks through of(), which
takes a folder or the object itself, so the same function serves when
its caller has the object to give.

The answers are today's layout: the sources, the sidecars, the reports,
and the intermediates all in the project's folder, and each target's
folder beside them. The suites ask the same object where to look for
what a run wrote.

A part is a book, a set of decks, or another collection with sources of
its own. Every question that depends on one takes it, though today each
part's files are in the one folder and the answer is the same for all.

Copyright (C) 2026 Robert Szarka

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
import tempfile

PROJECT_NAME = "project.yaml"
CONFIG_NAME = "conversion.yaml"
PACKAGING_NAME = "packaging.yaml"
# A source's document as Pandoc read it, and as the filters left it.
RAW = ".json"
INTERMEDIATE = ".filtered.json"
BOOK = "book"


class Project:
    """A project's folder, and where everything in it is.

    root is kept as it was given, so a path made from "." reads as it
    always has in a message ("./epub/book.epub")."""

    def __init__(self, root="."):
        self.root = root

    def _in(self, *names):
        return os.path.join(self.root, *names)

    # -- the settings ------------------------------------------------------

    def project_file(self):
        return self._in(PROJECT_NAME)

    def config_file(self):
        return self._in(CONFIG_NAME)

    def packaging_file(self):
        return self._in(PACKAGING_NAME)

    def top(self, *names):
        """A file or folder at the project's top that isn't a setting's:
        a configuration from an earlier version, say."""
        return self._in(*names)

    def named(self, value):
        """The file or folder a setting names: from the project's folder,
        or as written when it's a full path."""
        return self._in(str(value))

    def settings_folder(self):
        """The folder a setting's path is read from, for a module that
        still resolves one itself."""
        return self.root

    # -- a part's files ----------------------------------------------------

    def sources(self, part=BOOK):
        """The folder holding a part's sources."""
        return self.root

    def source(self, *names, part=BOOK):
        """A source, a folder of them, or a file a source names, by its
        path from the part's folder; a pattern for glob too."""
        return os.path.join(self.sources(part), *names)

    def sidecar(self, value, part=BOOK):
        """A part's sidecar, by the name its setting gives."""
        return self.named(value)

    def report(self, value, part=BOOK):
        """A draft or a report of a part's, by the name its setting gives."""
        return self.named(value)

    def pages(self, part=BOOK, own=None):
        """The folder holding a part's intermediates; own, the folder a
        target was given for its own, where its filters differ."""
        return own or self.root

    def page(self, stem, part=BOOK, own=None, suffix=INTERMEDIATE):
        """One page's intermediate, as the filters left it."""
        return os.path.join(self.pages(part, own), stem + suffix)

    def raw(self, stem, part=BOOK):
        """One source's document as Pandoc read it, before the filters."""
        return os.path.join(self.pages(part), stem + RAW)

    def referenced(self, *names, part=BOOK):
        """The file a page names by a path from its part's folder: a
        picture or a linked file among the sources, or one the run
        extracted or rendered for the part."""
        return os.path.join(self.run_dir(part), *names)

    def media(self, *names, part=BOOK):
        """What a run extracts or renders for a part beside its
        intermediates, by the path a page names it by: a Word file's
        pictures, a LaTeX book's rendered drawings, a deck saved as
        PowerPoint."""
        return os.path.join(self.run_dir(part), *names)

    def work_file(self, name, part=BOOK):
        """A file one step of a run leaves for a later one (the table
        headers as resolved, say), which no person reads."""
        return self._in(name)

    # -- what a run writes -------------------------------------------------

    def target_dir(self, name, output_dir=None):
        """A target's folder: named after it unless output_dir says."""
        return self._in(str(output_dir or name))

    def target_file(self, name, filename, output_dir=None):
        return os.path.join(self.target_dir(name, output_dir), filename)

    def package_file(self, name, package=None):
        """A file a package's build writes: its manifest, its list of
        files, the cartridge itself."""
        return self._in(str(name))

    def temp_dir(self, prefix="ti-", suffix=""):
        """A new temporary folder, the caller's to delete."""
        return mkdtemp(prefix=prefix, suffix=suffix)

    def temp_file(self, prefix="ti-", suffix="", beside=None, text=False):
        """A new temporary file, as tempfile.mkstemp gives it (an open
        handle and a path); beside, a file or folder it must share a disk
        with, so that it can be renamed into place."""
        return mkstemp(prefix=prefix, suffix=suffix, text=text,
                       dir=os.path.dirname(beside) if beside else None)

    def unpack_dir(self, part=BOOK):
        """A new folder to unpack an archive of sources into, on the disk
        the sources are on, so its files can be renamed into place."""
        return mkdtemp(prefix=".unpacking-", dir=self.sources(part))

    def run_dir(self, part=BOOK):
        """The folder Pandoc and LaTeX run in for a part: where a page's
        pictures are found by the paths its intermediate names."""
        return self.root

    # -- what a part may read ----------------------------------------------

    def inside(self, path):
        """Whether path, its links followed, is in the project."""
        root = os.path.realpath(self.root)
        real = os.path.realpath(path if os.path.isabs(path) else self._in(path))
        return real == root or real.startswith(root.rstrip(os.sep) + os.sep)


_KNOWN = {}


def of(folder="."):
    """The Project for a folder, the same object each time it's asked
    for; a Project is given back as it is."""
    if isinstance(folder, Project):
        return folder
    if folder not in _KNOWN:
        _KNOWN[folder] = Project(folder)
    return _KNOWN[folder]


# -- temporary files ---------------------------------------------------------
#
# Every temporary folder and file a script makes is made here, with
# tempfile's own names and arguments, so that where they go is decided in
# one place.

def mkdtemp(suffix=None, prefix=None, dir=None):
    return tempfile.mkdtemp(suffix=suffix, prefix=prefix, dir=dir)


def mkstemp(suffix=None, prefix=None, dir=None, text=False):
    return tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=dir, text=text)


def TemporaryDirectory(*args, **kwargs):
    return tempfile.TemporaryDirectory(*args, **kwargs)


def NamedTemporaryFile(*args, **kwargs):
    return tempfile.NamedTemporaryFile(*args, **kwargs)
