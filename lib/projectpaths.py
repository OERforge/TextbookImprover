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
import re
import tempfile

PROJECT_NAME = "project.yaml"
CONFIG_NAME = "conversion.yaml"
PACKAGING_NAME = "packaging.yaml"
# A source's document as Pandoc read it, and as the filters left it.
RAW = ".json"
INTERMEDIATE = ".filtered.json"
BOOK = "book"
# The folders at a project's top that no setting's file is read from:
# what runs write, what was taken out of the sources, the sidecars, and
# the files as a publisher sent them.
NOT_NAMED = ("output", "originals", "sidecars", "upstream")


# A part's name, as the project's schema has it: it's a folder's name
# and goes into the search paths Pandoc and LaTeX are given, where a
# colon would start another folder.
PART_NAME = re.compile(r"[a-z][a-z0-9_-]*\Z")


class Refused(SystemExit):
    """A path the settings give that a run won't read; raised, it stops
    the script with its message, as sys.exit does."""


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

    def named(self, value, part=None, setting=None):
        """The file or folder a setting names: from the project's folder,
        or as written when it's a full path."""
        return self._in(str(value))

    def named_file(self, value, part=None):
        """The file a setting names where the setting may be text
        instead (a header's or a footer's): its path when it's a file
        the settings may name, and otherwise None."""
        path = self.named(value, part)
        return path if os.path.isfile(path) else None

    def settings_folder(self):
        """The folder a setting's path is read from, for a module that
        still resolves one itself."""
        return self.root

    # -- a part's files ----------------------------------------------------

    def sources(self, part=None):
        """The folder holding a part's sources."""
        return self.root

    def source(self, *names, part=None):
        """A source, a folder of them, or a file a source names, by its
        path from the part's folder; a pattern for glob too."""
        return os.path.join(self.sources(part), *names)

    def source_arg(self, *names, part=None):
        """A source as a program run in run_dir names it: its path from
        that folder."""
        return os.path.relpath(self.source(*names, part=part), self.run_dir(part))

    def sidecar(self, value, part=None):
        """A part's sidecar, by the name its setting gives."""
        return self.named(value)

    def report(self, value, part=None):
        """A draft or a report of a part's, by the name its setting gives."""
        return self.named(value)

    def pages(self, part=None, own=None):
        """The folder holding a part's intermediates; own, the folder a
        target was given for its own, where its filters differ."""
        return own or self.root

    def page(self, stem, part=None, own=None, suffix=INTERMEDIATE):
        """One page's intermediate, as the filters left it."""
        return os.path.join(self.pages(part, own), stem + suffix)

    def raw(self, stem, part=None):
        """One source's document as Pandoc read it, before the filters."""
        return os.path.join(self.pages(part), stem + RAW)

    def referenced(self, *names, part=None):
        """The file a page names by a path from its part's folder: a
        picture or a linked file among the sources, or one the run
        extracted or rendered for the part."""
        return os.path.join(self.run_dir(part), *names)

    def media(self, *names, part=None):
        """What a run extracts or renders for a part beside its
        intermediates, by the path a page names it by: a Word file's
        pictures, a LaTeX book's rendered drawings, a deck saved as
        PowerPoint."""
        return os.path.join(self.run_dir(part), *names)

    def work_file(self, name, part=None):
        """A file one step of a run leaves for a later one (the table
        headers as resolved, say), which no person reads."""
        return self._in(name)

    # -- what a run writes -------------------------------------------------

    def target_dir(self, name, output_dir=None):
        """A target's folder: named after it unless output_dir says."""
        return self._in(str(output_dir or name))

    def target_pages(self, name, output_dir=None):
        """A target's own intermediates, where its filters differ from
        the first target's."""
        return os.path.join(self.target_dir(name, output_dir), "intermediates")

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

    def unpack_dir(self, part=None):
        """A new folder to unpack an archive of sources into, on the disk
        the sources are on, so its files can be renamed into place."""
        return mkdtemp(prefix=".unpacking-", dir=self.sources(part))

    def run_dir(self, part=None):
        """The folder Pandoc and LaTeX run in for a part: where a page's
        pictures are found by the paths its intermediate names."""
        return self.root

    def originals(self, part=None):
        """The folders, from run_dir, that a page's pictures are looked
        for in after any copies made of them: Pandoc's resource path's
        last entries."""
        return (".",)

    def reference_folders(self, part=None):
        """The folders a path a page names is looked for in, in order:
        what referenced() goes through."""
        return [self.run_dir(part)]

    def tex_env(self, env=None, part=None):
        """The environment for a LaTeX, BibTeX, or Biber run in run_dir
        that reads the book's own files: env, or the run's own, with the
        sources' folder on the programs' search paths when it isn't the
        folder they run in."""
        env = dict(os.environ if env is None else env)
        folders = [os.path.abspath(os.path.join(self.run_dir(part), o))
                   for o in self.originals(part) if o != "."]
        if folders:
            for name in ("TEXINPUTS", "BIBINPUTS", "BSTINPUTS"):
                env[name] = os.pathsep.join(["."] + folders + [env.get(name, "")])
        return env

    # -- what a part may read ----------------------------------------------

    def inside(self, path):
        """Whether path, its links followed, is in the project."""
        root = os.path.realpath(self.root)
        real = os.path.realpath(path if os.path.isabs(path) else self._in(path))
        return real == root or real.startswith(root.rstrip(os.sep) + os.sep)



class Tree(Project):
    """A project in the layout with a folder for each part's sources:

        src/<part>/               a part's sources
        sidecars/<part>/          its sidecars, under their standard names
        output/<target>/          a target's folder
        output/packages/<name>/   a package's
        output/reports/<part>/    drafts, reports, and samples
        output/work/parts/<part>/ intermediates and what a run extracts
                                  or renders, where Pandoc and LaTeX run
        output/work/targets/<target>/  a target's own intermediates
    """

    def __init__(self, root):
        super().__init__(root)
        # The sources' folder goes into TEXINPUTS and Pandoc's resource
        # path whole, where the separator would begin a folder of the
        # path's own choosing.
        if os.pathsep in os.path.abspath(root):
            raise Refused(f"{os.path.abspath(root)} has a {os.pathsep!r} in its path, which "
                          "the programs a run starts read as the end of a folder's name. "
                          "Move or rename the project's folder.")

    def part(self, part=None):
        """The part meant: the one named, or the project's own when it
        has one alone (book, or the one folder under src/). A name that
        isn't a part's stops the run: it's a folder's name here and part
        of a search path for Pandoc and LaTeX."""
        if not part:
            if not hasattr(self, "_only"):
                try:
                    found = sorted(e.name for e in os.scandir(self._in("src")) if e.is_dir())
                except OSError:
                    found = []
                self._only = BOOK if BOOK in found or len(found) != 1 else found[0]
            part = self._only
        if not PART_NAME.match(str(part)):
            raise Refused(
                f"src/{part}/ in {os.path.abspath(self.root)} can't be a part of a project: a "
                "part's name is a lowercase letter, then lowercase letters, digits, - and _. "
                "Rename the folder (src/book/ for a book), or, for a book that keeps a src/ "
                "of its own, move it into the new layout with util/move-to-src.py.")
        return part

    def _made(self, *names):
        folder = self._in(*names)
        os.makedirs(folder, exist_ok=True)
        return folder

    def sources(self, part=None):
        part = self.part(part)
        return self._in("src", part)

    def sidecar(self, value, part=None):
        part = self.part(part)
        return self._in("sidecars", part, os.path.basename(str(value)))

    def report(self, value, part=None):
        part = self.part(part)
        return os.path.join(self._made("output", "reports", part),
                            os.path.basename(str(value)))

    def pages(self, part=None, own=None):
        part = self.part(part)
        return own or self.run_dir(part)

    def target_pages(self, name, output_dir=None):
        return self._made("output", "work", "targets", name)

    def referenced(self, *names, part=None):
        part = self.part(part)
        made = os.path.join(self.run_dir(part), *names)
        return made if os.path.lexists(made) else self.source(*names, part=part)

    def work_file(self, name, part=None):
        part = self.part(part)
        return os.path.join(self.run_dir(part), name)

    def target_dir(self, name, output_dir=None):
        return self._in("output", str(output_dir or name))

    def package_file(self, name, package=None):
        return os.path.join(self._made("output", "packages", package or "cartridge"),
                            str(name))

    def run_dir(self, part=None):
        part = self.part(part)
        return self._made("output", "work", "parts", part)

    def _unnamed(self, value, part=None):
        """Why the settings may not name value, or None when they may.

        A setting's path is read from the project's top and nowhere else:
        one name is one file, so nothing put among the sources (which may
        be a publisher's package, unpacked) can stand in for a file the
        settings name. It may lead to the top, to a folder of the
        person's own there, or into the sources of the part being built,
        when it says so (src/book/preamble.md). It may not lead out of
        the project, a link followed; into what a run wrote, what was
        taken out of the sources, the sidecars, the publisher's files, or
        another part; or to a name beginning with a dot, which is where
        a checkout keeps what was never meant for a book."""
        value = str(value)
        if not value.strip() or "\0" in value:
            return "which is no file's name"
        if os.path.isabs(value) or value.startswith(("\\", "~")) \
                or (len(value) > 1 and value[1] == ":"):
            return "a full path, where a setting's path is from the project's folder"
        root = os.path.realpath(self.root)
        real = os.path.realpath(os.path.join(root, value))
        if real == root or not real.startswith(root.rstrip(os.sep) + os.sep):
            return "which leads out of the project's folder"
        names = os.path.relpath(real, root).split(os.sep)
        written = [n for n in value.replace("\\", "/").split("/") if n not in ("", ".")]
        if any(n.startswith(".") for n in names + written):
            return "which has a name beginning with a dot"
        first = names[0].casefold()
        if first in NOT_NAMED:
            return f"which is in {names[0]}/"
        if first == "src":
            own = self.part(part)
            if len(names) < 3 or names[1] != own:
                return f"which is in src/ and not among the sources of the part built (src/{own}/)"
        return None

    def named(self, value, part=None, setting=None):
        """The file or folder a setting names, from the project's top;
        a path the settings may not name stops the run (_unnamed)."""
        why = self._unnamed(value, part)
        if why:
            raise Refused(
                f"{setting or 'A setting'} names {value}, {why}. A file a setting names is "
                "kept in the project's folder: at its top, in a folder of its own there "
                f"(templates/), or among the sources of the part being built (src/"
                f"{self.part(part)}/); copy it there and name the copy.")
        return self._in(str(value))

    def named_file(self, value, part=None):
        if self._unnamed(value, part):
            return None
        path = self._in(str(value))
        return path if os.path.isfile(path) else None

    def reference_folders(self, part=None):
        part = self.part(part)
        return [self.run_dir(part), self.sources(part)]

    def originals(self, part=None):
        part = self.part(part)
        return (".", os.path.relpath(self.sources(part), self.run_dir(part)))


def is_tree(folder):
    """Whether a folder is a project in the layout with src/<part>/: it
    has a src/ that holds at least one folder and no file, since a part
    is a folder there and nothing else belongs beside the parts. A book
    kept in one folder with a src/ of its own (a course's documents in
    src/, their shared files in folders below) has files there, and is
    read as today's layout while both are read. A dot file isn't
    counted: a .gitkeep or a .DS_Store says nothing of the layout."""
    src = os.path.join(folder, "src")
    try:
        entries = [e for e in os.scandir(src) if not e.name.startswith(".")]
    except OSError:
        return False
    return any(e.is_dir() for e in entries) and all(e.is_dir() for e in entries)


_KNOWN = {}


def of(folder="."):
    """The Project for a folder, the same object each time it's asked
    for; a Project is given back as it is."""
    if isinstance(folder, Project):
        return folder
    if folder not in _KNOWN:
        _KNOWN[folder] = (Tree if is_tree(folder) else Project)(folder)
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
