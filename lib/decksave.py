"""
decksave.py -- decks in other formats saved as PowerPoint, through
LibreOffice, for a slides run to read.

A slides run reads PowerPoint decks (.pptx). An OpenDocument presentation
(.odp), which LibreOffice Impress saves and Google Slides exports, and a
PowerPoint 97-2003 deck (.ppt) are saved as PowerPoint once, by
LibreOffice, each beside its original, which is left as it is. From then
on the PowerPoint file is the deck, as an archive's files are the book
once it's unpacked (convert.py's unpack_archives): it's what the run
reads, what the sidecars' rows name, and where a person corrects the
deck, and a later run doesn't save the original again. A deck whose
PowerPoint file is beside it already (Google Slides' other export, or
the file an earlier run saved) isn't read, and the run says so, warning
when the original is the newer of the two.

LibreOffice is found as LIBREOFFICE names it, a path or a command on the
path, or as soffice or libreoffice on the path. Each deck is saved with
a profile of its own, so a LibreOffice the person has open doesn't take
the request and do nothing, and into a folder of its own, so a failed
save leaves nothing beside the deck; both are removed after, and a save
that takes too long has LibreOffice's whole process group stopped, since
soffice is a script that starts the program it waits for. A file that
isn't a deck of its kind (an empty one, or an ODP saved with a password)
is said to be before LibreOffice sees it, which would otherwise save an
empty file as a blank deck.

What the save loses, measured with LibreOffice 24.2: an embedded object
has no picture in its PowerPoint file, a PowerPoint 97-2003 deck's
equations (Equation Editor 3.0 and MathType objects, in one real deck)
and an ODP's embedded spreadsheet alike, so the reader leaves it out and
says so, where PowerPoint's own Save As keeps a .ppt's pictures. From the
real ODP decks measured, eight of Google Slides' exports and three of
LibreOffice Impress's, the slides, titles, text, lists, tables, pictures,
links, notes and their links, and hidden slides came through as the ODP
had them, a picture's alt text (svg:desc) as its description, a picture
marked decorative still marked, and the title slide as a title beside a
subtitle, which the reader takes as the title slide when it holds
nothing else (pptxsource.py). Of Google Slides' two exports, its
PowerPoint file serves better: it gives the text its language, which
LibreOffice's save of the ODP export didn't, its titles aren't bold,
where the ODP export makes most of them bold, and its title slide is
PowerPoint's own.

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
import pathlib
import re
import shutil
import signal
import subprocess
import tempfile
import zipfile
from xml.etree import ElementTree

# What each format is, in a message, by its extension.
FORMATS = {".odp": "an OpenDocument presentation", ".ppt": "a PowerPoint 97-2003 deck"}
EXTENSIONS = tuple(FORMATS)
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
# An OLE compound file's first bytes, which a PowerPoint 97-2003 deck has.
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ODP_TYPE = b"application/vnd.oasis.opendocument.presentation"
# How long one deck may take: LibreOffice saved each of 13 real decks,
# up to 9 MB, in about two seconds.
TIMEOUT = 300


class SaveError(Exception):
    """A deck LibreOffice didn't save as PowerPoint, and why."""


def other_decks(base):
    """The decks at the top of a folder that a run saves as PowerPoint
    first, in name order: all but the lock files PowerPoint keeps beside
    a deck it has open (~$NAME). LibreOffice's (.~lock.NAME#) end in #."""
    return [name for name in sorted(os.listdir(base))
            if name.lower().endswith(EXTENSIONS) and not name.startswith("~$")
            and os.path.isfile(os.path.join(base, name))]


def powerpoint_name(name):
    """The name a deck's PowerPoint file has: its own, as .pptx."""
    return os.path.splitext(name)[0] + ".pptx"


class Plan:
    """What a run does with each deck in another format, each list in name
    order: to_save, (deck, the name its PowerPoint file will have);
    in_place, (deck, its PowerPoint file beside it already, as the folder
    spells it); looks, (deck, the decks' reference document its PowerPoint
    name is); blocked, (deck, something at its PowerPoint name that isn't
    a file, a folder or a link to nothing); clashes, {name: decks} that
    would each be saved under one name (talk.odp and talk.ppt), which none
    is."""

    def __init__(self):
        self.to_save, self.in_place, self.looks, self.blocked = [], [], [], []
        self.clashes = {}


def plan(base, looks=()):
    """The Plan for a folder's decks in other formats. looks: the paths
    of the decks' reference documents (slides.reference_doc), which aren't
    decks, so an original whose PowerPoint name is one isn't read."""
    here = {name.lower(): name for name in os.listdir(base)}
    looks = {os.path.normcase(os.path.abspath(path)) for path in looks}
    result = Plan()
    wanted = {}
    for name in other_decks(base):
        target = powerpoint_name(name)
        existing = here.get(target.lower())
        if existing is None:
            wanted.setdefault(target.lower(), []).append((name, target))
            continue
        path = os.path.join(base, existing)
        if os.path.normcase(os.path.abspath(path)) in looks:
            result.looks.append((name, existing))
        elif os.path.isfile(path):
            result.in_place.append((name, existing))
        else:
            result.blocked.append((name, existing))
    result.to_save = sorted(pairs[0] for pairs in wanted.values() if len(pairs) == 1)
    result.clashes = {pairs[0][1]: [name for name, _ in pairs]
                      for pairs in wanted.values() if len(pairs) > 1}
    return result


def libreoffice():
    """The program to run, as a list, or None: what LIBREOFFICE names, a
    path or a command on the path, which wins; else soffice or
    libreoffice on the path."""
    named = os.environ.get("LIBREOFFICE", "").strip()
    if named:
        if os.sep not in named:
            found = shutil.which(named)
            return [found] if found else None
        return [named] if os.path.isfile(named) and os.access(named, os.X_OK) else None
    found = shutil.which("soffice") or shutil.which("libreoffice")
    return [found] if found else None


def _package(path):
    """(its mimetype, its manifest, whether it's a PowerPoint file) for a
    zip; None for a file that isn't one, or can't be read."""
    if not zipfile.is_zipfile(path):
        return None
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            kind = archive.read("mimetype").strip() if "mimetype" in names else b""
            manifest = (archive.read("META-INF/manifest.xml")
                        if "META-INF/manifest.xml" in names else b"")
            powerpoint = "ppt/presentation.xml" in names
    except (OSError, zipfile.BadZipFile, KeyError):
        return None
    return kind, manifest, powerpoint


def problem(path):
    """Why the file at path isn't a deck LibreOffice can save, in words a
    person can act on, or None: an empty file, an ODP that isn't one or is
    saved with a password, or a .ppt that isn't PowerPoint 97-2003's; one
    that's another kind of deck says so, with the name that reads it."""
    with open(path, "rb") as fh:
        head = fh.read(8)
    if not head:
        return "the file is empty"
    package = _package(path)
    other = ""
    if package and package[2]:
        other = " (it's a PowerPoint file: renamed .pptx, it can be read)"
    elif package and package[0] == ODP_TYPE:
        other = " (it's an OpenDocument presentation: renamed .odp, it can be read)"
    if path.lower().endswith(".odp"):
        if package is None:
            why = "it isn't an OpenDocument presentation (an .odp is a zip, and this isn't one)"
            if head == OLE:
                why += "; it may be a PowerPoint 97-2003 deck: renamed .ppt, it can be read"
            return why
        if package[0] != ODP_TYPE:
            return "it isn't an OpenDocument presentation" + other
        if b"encryption-data" in package[1]:
            return ("it's saved with a password; saved again from LibreOffice Impress without "
                    "one, it can be read")
        return None
    if head != OLE:
        return "it isn't a PowerPoint 97-2003 deck" + other
    return None


def save(program, path, target):
    """Save the deck at path as the PowerPoint file target, through
    LibreOffice, or raise SaveError saying why it couldn't be."""
    with tempfile.TemporaryDirectory(prefix="decksave-") as work:
        profile = os.path.join(work, "profile")
        out = os.path.join(work, "out")
        os.makedirs(out)
        command = program + ["--headless", "--norestore", "--nologo", "--nolockcheck",
                             "-env:UserInstallation=" + pathlib.Path(profile).as_uri(),
                             "--convert-to", "pptx", "--outdir", out, os.path.abspath(path)]
        try:
            # A session of its own, so that a save that takes too long stops
            # the program soffice starts as well as soffice.
            run = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   stdin=subprocess.DEVNULL, text=True, start_new_session=True)
        except OSError as exc:
            raise SaveError(f"LibreOffice couldn't be run ({exc})")
        try:
            stdout, stderr = run.communicate(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(run.pid, signal.SIGKILL)
            except OSError:
                pass
            run.communicate()
            raise SaveError(f"LibreOffice took more than {TIMEOUT} seconds")
        written = os.path.join(out, powerpoint_name(os.path.basename(path)))
        if not os.path.isfile(written) or not zipfile.is_zipfile(written):
            said = [line.strip() for line in (stderr.strip() or stdout.strip()).splitlines()
                    if line.strip()]
            why = ([f"exit status {run.returncode}"] if run.returncode else []) + said[:1]
            hint = ("; a deck saved with a password can't be, and LibreOffice needs its Impress "
                    "(libreoffice-impress) for any" if any("could not be loaded" in line
                                                           for line in said) else "")
            raise SaveError("LibreOffice wrote no PowerPoint file"
                            + (" (" + "; ".join(why) + hint + ")" if why else ""))
        shutil.move(written, target)


def objects_without_pictures(path):
    """How many embedded objects (p:oleObj) a PowerPoint file's slides hold
    with no picture of them, as LibreOffice saves any deck's: what the
    reader leaves out. An object in an mc:Choice is PowerPoint's, whose
    mc:Fallback has the picture."""
    count = 0
    with zipfile.ZipFile(path) as archive:
        for part in archive.namelist():
            if not re.fullmatch(r"ppt/slides/slide\d+\.xml", part):
                continue
            root = ElementTree.fromstring(archive.read(part))
            choices = {id(el) for choice in root.iter(MC + "Choice") for el in choice.iter()}
            count += sum(1 for obj in root.iter(P + "oleObj")
                         if id(obj) not in choices and obj.find(P + "pic") is None)
    return count
