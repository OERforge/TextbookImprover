#!/usr/bin/env python3
"""
convert.py -- convert a directory of Word documents into accessible pages
and books, one output per target, and hand off to the packager.

    python3 convert.py                  # every target in conversion.yaml
    python3 convert.py --zip            # ... and build the cartridge archive
    python3 convert.py --toc book.pdf   # passed through to the packager
    python3 convert.py --quiet          # without the command trace

Run in the directory holding the .docx files. That directory keeps the
sources, the intermediates, the sidecars, and the reports; every target
writes into a directory of its own, html/ for the one implied when no
configuration says otherwise. A page the author wrote by hand -- an
.html here with no .docx behind it -- is copied into every HTML
target's directory as it stands, with the local files it refers to, and
read into an intermediate so the EPUB has it too. Such a page lives in
the pass-through directory (_pt/ unless project.yaml says otherwise); an
.html beside the sources is a source, read like any other.

THE RUN

  0.   read the configuration and resolve the sidecar paths
  0.5  the table-headers pre-pass, on the .docx files
  1.   .docx, .md, .html -> .json                 (once per document)
  2.   check every media reference resolves       (the gate)
  3.   render header and footer fragments         (per target)
  4.   filter the .json -> .filtered.json         (once per filter stage)
  4.5  cut sources into pages, when asked         (once per filter stage)
  4.7  render .filtered.json -> .html             (per html target)
  5.   write the reports                          (once per book)
  5.5  assemble the EPUBs                         (per epub3 target)
  5.7  check what was written                     (per target)
  6.   build the cartridge                        (the packager)

Two targets share a filtered intermediate when every setting the
schema marks stage: filter agrees between them; otherwise the filter
runs again into a directory of that target's own. Reports and sidecars
are about the source and are written once per book, whatever the
targets. This used to be convert.sh, and the comments that carried what
the shell script had learned are carried here in turn.

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

import argparse
import glob
import json
import os
import csv
import re
import shutil
import copy
import subprocess
import sys
import tempfile
from urllib.parse import unquote

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
try:
    import docxrepair
    import docxremediate
    import htmlremediate
    import mdremediate
    import texremediate
    import docxtarget
    import htmlrepair
    import mathjax
    import notes as notes_lib
    import oerconfig
    from bookcontents import (guess_contents, walk_contents, number_tree,
                              is_generated, toc_blocks, stem_title, declared_titles,
                              expand_split_sources, contents_from_tree, opener_types)
    from names import safe_path, safe_stem, is_safe
except ImportError:
    sys.exit("Cannot find the configuration library. It should be in a "
             "lib/ directory beside bin/.")

FIGURE_FILTER = os.path.join(HERE, "figures-and-tables.lua")
MATH_FILTER = os.path.join(HERE, "math-repair.lua")
MEDIA_FILTER = os.path.join(HERE, "media-extensions.lua")
HEADER_FILTER = os.path.join(HERE, "header-includes.lua")
SAFE_MEDIA_FILTER = os.path.join(HERE, "safe-media.lua")
# Formats the schema names before a target can build them; none now.
NOT_YET_IMPLEMENTED = ()
# Targets whose output is written to be a source again: what the author
# decided, and not what the filter derived from it.
SOURCE_TARGETS = ("markdown", "asciidoc")
TARGET_FILTER = os.path.join(HERE, "target-blocks.lua")
MARKDOWN_FILTER = os.path.join(HERE, "markdown-source.lua")
MARKDOWN_HTML_FILTER = os.path.join(HERE, "markdown-html.lua")
HTML_SOURCE_FILTER = os.path.join(HERE, "html-source.lua")
HTML_RAW_FILTER = os.path.join(HERE, "html-raw.lua")
ASCIIDOC_FILTER = os.path.join(HERE, "asciidoc-source.lua")
LATEX_FILTER = os.path.join(HERE, "latex-source.lua")
# Markdown files a LaTeX book's repository holds about itself (GitHub's
# community health files), which aren't pages of the book: OpenIntro
# Statistics has a LICENSE.md beside its master.
REPOSITORY_FILES = ("readme.md", "license.md", "contributing.md", "changelog.md",
                    "code_of_conduct.md", "security.md")
INCLUDE = re.compile(r"^include::([^\[\s]+\.(?:adoc|asciidoc|asc))\[", re.M)
SOURCE_EXTENSIONS = (".docx", ".md", ".html", ".adoc", ".asciidoc")
# PowerPoint decks: sources of a slides run, not a book's pages (deckrun.py).
DECK_EXTENSIONS = (".pptx",)
# A tar, compressed or not, which a plain archive of a book's files can be
# as well as a zip.
TAR_EXTENSIONS = (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")
PAGE_CSS = os.path.join(HERE, "page.css")
HEADERS_TOOL = os.path.join(HERE, "table-headers.py")
SPLIT_TOOL = os.path.join(HERE, "split-pages.py")
EPUB_TOOL = os.path.join(HERE, "build-epub.py")
PDF_TOOL = os.path.join(HERE, "build-pdf.py")
CHECK_TOOL = os.path.join(HERE, "check-output.py")
CARTRIDGE_TOOL = os.path.join(HERE, "build-cartridge.py")

CONFIG_NAME = "conversion.yaml"
PROJECT_NAME = "project.yaml"
PACKAGING_NAME = "packaging.yaml"
LEGACY_NAME = "imsmanifest.yaml"
INTERMEDIATE = ".filtered.json"

TRACE = True


def say(text):
    print(text, file=sys.stderr)


def archive_entry(name):
    """An archive entry's path as parts, None for what a system leaves
    behind (macOS's __MACOSX and ._ files, .DS_Store, Thumbs.db), or
    "unsafe" for one that would land outside the book: an absolute path,
    or one with .. in it."""
    name = name.replace("\\", "/")
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if name.startswith("__MACOSX/") or (parts and (
            parts[-1] in (".DS_Store", "Thumbs.db", "desktop.ini")
            or parts[-1].startswith("._"))):
        return None
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name) or ".." in parts:
        return "unsafe"
    return parts


def unwrapped(entries):
    """How many leading folders every entry shares and nothing else sits
    beside ("My Book/..."), which extraction drops."""
    strip = 0
    while entries and all(len(parts) > strip + 1 for _, parts in entries) \
            and len({parts[strip] for _, parts in entries}) == 1:
        strip += 1
    return strip


def extract_zip(path, work):
    """A plain zip's files, written into work. Folders that wrap everything
    ("My Book/...") are dropped, so the sources sit at the top where
    convert.py finds them; what macOS and Windows leave behind is left out;
    and an entry that would land outside the book -- an absolute path, or
    one with .. in it -- is refused rather than written. Returns the
    report's rows."""
    import stat
    import zipfile
    notes, entries = [], []
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            parts = archive_entry(info.filename)
            if parts == "unsafe":
                notes.append((info.filename, "unsafe-path",
                              "would land outside the book; not extracted"))
                continue
            if info.is_dir() or not parts:
                continue
            # A link, which a zip made on Unix can hold, as a tar can: its
            # target is a path on someone else's machine, not a file.
            if stat.S_ISLNK(info.external_attr >> 16):
                notes.append((info.filename, "not-a-file",
                              "a link or a special file, not a file; not extracted"))
                continue
            entries.append((info, parts))
        strip = unwrapped(entries)
        for info, parts in entries:
            dest = os.path.join(work, *parts[strip:])
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with archive.open(info) as source, open(dest, "wb") as out:
                shutil.copyfileobj(source, out)
    return notes


def extract_tar(path, work):
    """A tar's files, compressed or not, written into work as a zip's are
    (extract_zip). Only files: a link, a device, or a pipe is nothing a
    book is made of, and a link could point anywhere, so each is left out
    and reported. Returns the report's rows."""
    import tarfile
    notes, entries = [], []
    with tarfile.open(path) as archive:
        for info in archive.getmembers():
            parts = archive_entry(info.name)
            if parts == "unsafe":
                notes.append((info.name, "unsafe-path",
                              "would land outside the book; not extracted"))
                continue
            if info.isdir() or not parts:
                continue
            if not info.isfile():
                notes.append((info.name, "not-a-file",
                              "a link or a special file, not a file; not extracted"))
                continue
            entries.append((info, parts))
        strip = unwrapped(entries)
        for info, parts in entries:
            dest = os.path.join(work, *parts[strip:])
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with archive.extractfile(info) as source, open(dest, "wb") as out:
                shutil.copyfileobj(source, out)
    return notes


def archive_stem(path):
    """An archive's path without its extension: remediated.tar.gz ->
    remediated."""
    lower = path.lower()
    for ext in sorted(TAR_EXTENSIONS + (".zip", ".imscc"), key=len, reverse=True):
        if lower.endswith(ext):
            return path[:-len(ext)]
    return path


def archive_targets(targets, base):
    """Each target whose archive setting asks for it packed into one file
    beside its folder and named after it (html.zip, remediated.tar.gz),
    the folder inside it. Written whole, then put in place, so a run that
    stops leaves the last one, never half of one."""
    import tarfile
    import zipfile
    for target in targets:
        kind = str(target["archive"] or "none")
        folder = os.path.abspath(target.output_dir)
        if kind == "none" or not os.path.isdir(folder):
            continue
        if folder == os.path.abspath(base) or \
                os.path.abspath(base).startswith(folder + os.sep):
            say(f"NOTE: target {target.name} writes into the content directory, which "
                "isn't archived; give it an output_dir of its own.")
            continue
        path = folder + (".zip" if kind == "zip" else ".tar.gz")
        root = os.path.basename(folder)
        files = sorted(os.path.relpath(os.path.join(here, name), folder)
                       for here, dirs, names in os.walk(folder) for name in names)
        handle, temp = tempfile.mkstemp(prefix=".archive-", dir=os.path.dirname(folder))
        os.close(handle)
        try:
            if kind == "zip":
                with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as archive:
                    for rel in files:
                        archive.write(os.path.join(folder, rel),
                                      root + "/" + rel.replace(os.sep, "/"))
            else:
                with tarfile.open(temp, "w:gz") as archive:
                    for rel in files:
                        archive.add(os.path.join(folder, rel),
                                    root + "/" + rel.replace(os.sep, "/"), recursive=False)
            # mkstemp's file is the owner's alone; an archive is for handing on
            mask = os.umask(0o022)
            os.umask(mask)
            os.chmod(temp, 0o666 & ~mask)
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.remove(temp)
        say(f"{target.name}: {len(files)} file(s) packed into {os.path.relpath(path, base)}.")


def browser_save(directory):
    """Whether a directory holds pages a browser saved: an .mhtml, or a page
    whose files sit beside it in <name>_files, or one Chrome or Edge marked
    with the address it was saved from."""
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        if name.lower().endswith((".mhtml", ".mht")):
            return True
        if name.lower().endswith((".html", ".htm")) and os.path.isfile(path):
            if os.path.isdir(os.path.splitext(path)[0] + "_files"):
                return True
            with open(path, encoding="utf-8", errors="replace") as fh:
                if "saved from url=" in fh.read(2048):
                    return True
    return False


def pass_on(run):
    """An unpacker's notes and warnings, which say something worth knowing
    even when it succeeds (that lxml, not html5lib, parsed the pages)."""
    for line in (run.stderr or "").splitlines():
        if line.startswith(("NOTE", "WARNING")):
            say(line)


LATEX_MAIN_SET = re.compile(
    r"^([ \t]*)latex:[ \t]*\n(?:\1[ \t]+[^\n]*\n|[ \t]*\n)*?\1[ \t]+main:", re.M)


def latex_book_here(base):
    """Whether base holds a LaTeX book: a master file at its top, or a
    conversion.yaml that names one (latex.main)."""
    import latexsource
    try:
        if latexsource.masters(base):
            return True
    except OSError:
        pass
    path = os.path.join(base, "conversion.yaml")
    if os.path.isfile(path):
        with open(path, encoding="utf-8", errors="replace") as fh:
            return bool(LATEX_MAIN_SET.search(fh.read()))
    return False


def unpack_archives(base, check_only=False, linked_documents=False):
    """A web archive -- a WARC, compressed or not, or a WACZ, recognized
    by its first bytes -- or a Common Cartridge, recognized by its
    manifest, or a plain .zip or tar (.tar.gz, .tgz, ...) of a book's
    files or a set of slides, in a directory with no sources is unpacked
    there first, as unpack-site.py or unpack-cartridge.py would or by
    extracting the archive, and its sources are then converted. From then
    on they're the book: they're where corrections are made, so a later
    run, finding sources, never reads the archive again. A project.yaml or
    conversion.yaml already here is kept, and the archive's is written
    beside it (project-unpacked.yaml). For an unpacker's own options (a
    profile, whole pages), run it yourself. A plain archive is known by
    its name, since Word files, slide decks, EPUBs, and cartridges are
    zips too, and a compressed WARC is a gzip as a .tar.gz is."""
    import sitesource
    import cartridgesource
    import tarfile
    skip = SOURCE_EXTENSIONS + DECK_EXTENSIONS + (".yaml", ".yml", ".csv", ".json", ".css",
                                                  ".lua", ".txt", ".pdf", ".epub")
    candidates = sorted(p for p in glob.glob(os.path.join(base, "*"))
                        if os.path.isfile(p) and not p.lower().endswith(skip))
    cartridges = [p for p in candidates if cartridgesource.is_cartridge(p)]
    archives = [p for p in candidates
                if p not in cartridges and sitesource.is_warc(p)]
    import zipfile
    zips = [p for p in candidates
            if p not in cartridges and p not in archives
            and p.lower().endswith(".zip") and zipfile.is_zipfile(p)]
    tars = [p for p in candidates
            if p not in cartridges and p not in archives
            and p.lower().endswith(TAR_EXTENSIONS) and tarfile.is_tarfile(p)]
    zips += tars        # a plain archive either way, extracted alike
    unused = ("--linked-documents applies when a run unpacks a cartridge, "
              "and this one doesn't: ")
    if not archives and not cartridges and not zips:
        if linked_documents:
            say(unused + "there's no cartridge here.")
        return
    # A directory with sources is a book already: nothing in it is read,
    # however many archives sit there (a cartridge --zip built, say, beside
    # the download it came from). A LaTeX book's are its masters, here or
    # where latex.main names them (FINC 308's src/), whose own cartridge,
    # built beside them, was taken for a book to unpack.
    if any(p.lower().endswith(SOURCE_EXTENSIONS + DECK_EXTENSIONS)
           for p in glob.glob(os.path.join(base, "*"))) or latex_book_here(base):
        # Beside a folder of its own name, an archive is that folder
        # packed, as a target's archive setting packs one: the run's own
        # output, which needs no word on every run.
        found = [p for p in cartridges + zips + archives
                 if not (archive_stem(p) != p and os.path.isdir(archive_stem(p)))]
        if not found:
            return
        slides_here = not any(p.lower().endswith(SOURCE_EXTENSIONS)
                              for p in glob.glob(os.path.join(base, "*"))) \
            and not latex_book_here(base)
        say(", ".join(os.path.basename(p) for p in found)
            + ": not read, since this directory has sources, which are the "
            + ("slides" if slides_here else "book") + " once an archive is unpacked. To unpack "
            + ("it afresh, " if len(found) == 1 else "one afresh, ")
            + ("extract it into a new directory." if len(found) == 1 and zips
               else "use unpack-cartridge.py or unpack-site.py, or extract "
               "it, into a new directory." if len(found) > 1 else
               f"use {'unpack-cartridge.py' if cartridges else 'unpack-site.py'}"
               " into a new directory."))
        if linked_documents:
            say(unused + "the pages here are the book already, and "
                "unpacking again into a new directory is how to change that.")
        return
    if (cartridges or zips) and (archives or len(cartridges + zips) > 1):
        die("More than one thing to unpack here ("
            + ", ".join(os.path.basename(p) for p in cartridges + zips + archives)
            + "); a book comes from one cartridge, zip, or tar, or from web "
            "archives. Unpack them into directories of their own.")
    tool = ("unpack-cartridge.py" if cartridges else
            "tar" if tars else "zip" if zips else "unpack-site.py")
    archives = cartridges or zips or archives
    if linked_documents and tool != "unpack-cartridge.py":
        say(unused + ("an archive's files are the book as they are." if zips
                      else "a web archive's pages keep their links to files."))
    names = ", ".join(os.path.basename(p) for p in archives)
    if check_only:
        say(f"{names} would be unpacked here and its pages converted.")
        return
    work = tempfile.mkdtemp(prefix=".unpacking-", dir=base)
    try:
        if tool in ("zip", "tar"):
            notes = (extract_tar if tool == "tar" else extract_zip)(archives[0], work)
            # A zip of pages a browser saved is a capture of a site, like a
            # WARC: unpack-site.py strips the site's chrome and names pages
            # from their addresses, where converting the saved files would
            # keep "| Site" in every title and the browser's file names.
            if browser_save(work):
                site = tempfile.mkdtemp(prefix=".unpacking-", dir=base)
                run = subprocess.run([sys.executable,
                                      os.path.join(HERE, "unpack-site.py"),
                                      work, "-o", site],
                                     capture_output=True, text=True)
                if run.returncode != 0:
                    shutil.rmtree(site, ignore_errors=True)
                    die(f"Unpacking the pages saved in {names} failed:\n"
                        + (run.stderr.strip() or run.stdout.strip()))
                pass_on(run)
                shutil.rmtree(work, ignore_errors=True)
                work = site
                say(f"{names} holds pages saved from a browser; they're "
                    "unpacked as unpack-site.py unpacks a browser's save.")
            held = sorted(os.listdir(work))
            if not any(n.lower().endswith(SOURCE_EXTENSIONS + DECK_EXTENSIONS)
                       for n in held):
                inside = [n for n in held if n.lower().endswith(
                    (".imscc", ".warc", ".gz", ".wacz", ".epub", ".zip")
                    + TAR_EXTENSIONS)]
                die(f"{names} holds no source convert.py reads at its top "
                    "(" + (", ".join(held[:8]) + (", ..." if len(held) > 8
                                                   else "") or "nothing")
                    + ")." + (" To convert " + ", ".join(inside) + ", put it "
                              "in a directory of its own." if inside else ""))
            if notes:
                with open(os.path.join(work, "unpack-report.csv"), "w",
                          newline="", encoding="utf-8") as fh:
                    writer = csv.writer(fh)
                    writer.writerow(["Where", "Check", "Detail"])
                    writer.writerows(notes)
        else:
            run = subprocess.run([sys.executable, os.path.join(HERE, tool),
                                  *archives, "-o", work]
                                 + (["--linked-documents"] if linked_documents
                                    and tool == "unpack-cartridge.py" else []),
                                 capture_output=True, text=True)
            if run.returncode != 0:
                die(f"Unpacking {names} failed:\n"
                    + (run.stderr.strip() or run.stdout.strip()))
            pass_on(run)
        kept = {"project.yaml": "project-unpacked.yaml",
                "conversion.yaml": "conversion-unpacked.yaml"}
        # Every name is checked before anything moves, so a clash leaves
        # the directory as it was, not half unpacked.
        moves = []
        for name in sorted(os.listdir(work)):
            target = os.path.join(base, name)
            if name in kept and os.path.exists(target):
                target = os.path.join(base, kept[name])
            if os.path.exists(target):
                die(f"{os.path.basename(target)} is already here; unpacking "
                    f"{names} would overwrite it. Unpack it into a new "
                    "directory instead.")
            moves.append((name, target))
        for name, target in moves:
            if name in kept and os.path.basename(target) == kept[name]:
                say(f"{name} was already here and is kept; the archive's is "
                    f"{kept[name]}.")
            shutil.move(os.path.join(work, name), target)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    sources = sum(1 for p in glob.glob(os.path.join(base, "*"))
                  if p.lower().endswith(SOURCE_EXTENSIONS))
    decks = sum(1 for p in glob.glob(os.path.join(base, "*"))
                if p.lower().endswith(DECK_EXTENSIONS))
    held = (f"{decks} PowerPoint deck(s), which are the slides" if decks and not sources
            else f"{sources} source(s)" + (f" and {decks} PowerPoint deck(s)" if decks else "")
            + ", which are the book")
    say(f"Unpacked {names}: {held} from now on. Correct them, not the archive: "
        "later runs don't read it again."
        + (" unpack-report.csv says what the unpacking found."
           if os.path.exists(os.path.join(base, "unpack-report.csv")) else ""))


def die(text, code=1):
    say(text)
    sys.exit(code)


def run(command, env=None, cwd=None, check=True, capture=False):
    """Run a command, tracing it the way `set -x` did.

    Seeing every Pandoc invocation as it happens has been useful more
    than once, so the trace is on unless --quiet.
    """
    if TRACE:
        say("+ " + " ".join(shell_quote(c) for c in command))
    result = subprocess.run(command, env=env, cwd=cwd, text=True,
                            capture_output=capture)
    if check and result.returncode:
        die(f"{os.path.basename(command[0])} failed with exit code "
            f"{result.returncode}.")
    return result


def shell_quote(value):
    value = str(value)
    if re.fullmatch(r"[\w./=:@%,+-]+", value):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


# --------------------------------------------------------------------------
# 0. the configuration
# --------------------------------------------------------------------------

class Target:
    """One conversion target, resolved."""

    def __init__(self, name, resolved, base):
        self.name = name
        self.resolved = resolved
        self.format = resolved["format"]
        self.output_dir = os.path.normpath(
            os.path.join(base, str(resolved["output_dir"] or name)))
        self.fingerprint = None      # set once every target is known
        # tables.bands: auto derives from the format, and is resolved here,
        # before targets are compared, so two targets that differ in it
        # don't share a filtered intermediate.
        self.derived = {}
        if resolved["tables.bands"] == "auto":
            self.derived["tables.bands"] = ("group" if self.format in
                                            ("markdown", "asciidoc", "docx")
                                            else "split")
        self.pages_dir = None        # where its filtered intermediates are

    def __getitem__(self, key):
        if key in self.derived:
            return self.derived[key]
        return self.resolved[key]


def book_sources(base):
    """The files at the top of base a book is read from, by their
    extension, apart from a repository's files about itself (README.md and
    the rest), which a folder of decks may have too."""
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(base, "*"))
                  if os.path.isfile(p) and p.lower().endswith(SOURCE_EXTENSIONS)
                  and os.path.basename(p).lower() not in REPOSITORY_FILES)


def slides_run(base, decks, targets, project, paths, reports, args, first):
    """A folder of PowerPoint decks: each checked, the decisions it needs
    written to the reports, and each format: source target given a copy of
    each deck with the decisions made so far written in (deckrun.py), the
    copies then checked. No pages and no cartridge: those come with the
    slides' later phases (ROADMAP.md)."""
    import deckrun
    if not decks:
        die("project.kind is slides, but there's no PowerPoint deck (.pptx) here to "
            "check or remediate.")
    others = book_sources(base)
    if others:
        say(f"NOTE: {len(others)} file(s) here are left out ("
            + ", ".join(others[:4]) + (", ..." if len(others) > 4 else "")
            + "): this folder is slides (project.kind), and a slides run reads "
            "PowerPoint decks.")
    say(f"Slides: {len(decks)} PowerPoint deck(s), each checked and remediated on its own"
        + (" (project.kind)." if KIND_DECLARED == "slides" else
           ", since they're all this folder holds."))
    code = deckrun.run(
        base, decks, targets, paths, reports,
        # Written into a copy only when the project declares it, as a
        # book's copies get it: the schema's default is nobody's decision.
        language=project["language"] if LANGUAGE_DECLARED else None,
        alt_max_chars=first["images.alt_max_chars"],
        alt_placeholders=first["images.alt_placeholders"] or (),
        check_only=args.check_only, say=say)
    warn_unreviewed(paths)
    if not args.check_only and code == 0:
        archive_targets([t for t in targets if t.format == "source"], base)
    elif not args.check_only and any(str(t["archive"] or "none") != "none" for t in targets):
        say("NOTE: nothing was archived, since a deck couldn't be read or a copy couldn't be "
            "read back; the copies that were written are in their folders.")
    return code


def declared_kind(documents):
    """project.kind as the files give it, the later winning, or None when
    none does: a folder of decks alone is slides without saying so, but
    one that says book is a book."""
    kind = None
    for doc in documents:
        if (doc.project or {}).get("kind") is not None:
            kind = str(doc.project["kind"])
    return kind


def load_targets(base, allow_unknown, decks_only=False):
    """Every conversion target, resolved, plus the project block. A slides
    run with no target declared has one implied, remediated, format source,
    where a book has html: decks_only says the folder's sources are
    PowerPoint decks alone."""
    schema = oerconfig.load_schema(os.path.join(HERE, "schema-conversion.yaml"))
    project_schema = oerconfig.load_schema(
        os.path.join(os.path.dirname(HERE), "lib", "schema-project.yaml"))

    legacy = os.path.join(base, LEGACY_NAME)
    config_path = os.path.join(base, CONFIG_NAME)
    if os.path.isfile(legacy) and not os.path.isfile(config_path):
        die(f"{LEGACY_NAME} is the v0.1 configuration and is no longer read.\n"
            "  Split it into project.yaml, conversion.yaml and packaging.yaml:\n"
            f"    python3 {os.path.dirname(HERE)}/util/migrate-config.py -d .\n"
            "  It reports what it will do first with --dry-run, and never\n"
            "  changes the original.")

    documents = []
    project_path = os.path.join(base, PROJECT_NAME)
    try:
        if os.path.isfile(project_path):
            documents.append(oerconfig.load_document(project_path,
                                                     project_schema))
        if os.path.isfile(config_path):
            documents.append(oerconfig.load_document(config_path, schema))
    except oerconfig.ConfigError as exc:
        # A directory with no configuration converts with the defaults. A
        # configuration that exists and cannot be read is a different
        # matter, and stops the run: the alternative is converting a whole
        # book with settings the user thought they had changed, which looks
        # like success and is not. v0.2.0 tolerated both cases alike, so a
        # footer written at the top level -- where v0.1 put it -- was
        # reported and then ignored.
        die(f"{exc}\n\nStopping: the configuration could not be read.\n"
            "  Nothing was converted. Fix the problem above and re-run,\n"
            "  or move the file aside to convert with the defaults.")

    declared = oerconfig.target_names(documents)
    # Whether the book declares its language: a source target writes it
    # into the author's files only then, never the schema's default.
    global LANGUAGE_DECLARED, TITLE_DECLARED, DECLARED_PROJECT, KIND_DECLARED
    LANGUAGE_DECLARED = any((doc.project or {}).get("language") for doc in documents)
    KIND_DECLARED = declared_kind(documents)
    if not declared and (KIND_DECLARED == "slides" or (KIND_DECLARED is None and decks_only)):
        # The target a slides folder means when it names none: a copy of
        # each deck with its decisions written in. First, so it is the
        # weakest, and the files a message names are still the person's.
        documents.insert(0, oerconfig.Document(
            {"targets": {"remediated": {"format": "source"}}}, "(the implied target)"))
        declared = ["remediated"]
    # Whether the book is named where conversion reads: an EPUB or a PDF
    # needs a title, and the schema's default, "Untitled", names nothing.
    DECLARED_PROJECT = oerconfig.declared_project(documents)
    TITLE_DECLARED = bool(DECLARED_PROJECT.get("title"))
    # A project: block in conversion.yaml names the book for conversion,
    # as one in packaging.yaml does for packaging: enough for a book that
    # uses one half. Without project.yaml, the packager's sample gets it.
    own = oerconfig.inline_project(config_path)
    if own and not os.path.isfile(project_path):
        BOOK_HINT["project"] = own
        BOOK_HINT["project_source"] = f"{CONFIG_NAME}'s project: block"
    # The book is one book in every file that describes it. resolve() has
    # held project.yaml and conversion.yaml to that; packaging.yaml's block
    # is held to it here, before anything is converted, since the packager
    # reads it only at the end.
    packaging_path = os.path.join(base, PACKAGING_NAME)
    packaged = oerconfig.inline_project(packaging_path)
    if packaged:
        conflicts = oerconfig.project_conflicts(
            documents + [oerconfig.Document({"project": packaged}, packaging_path)])
        if conflicts:
            die("\n".join(f"project.{key} is {a!r} in {first} and {b!r} in "
                          f"{second}." for key, (first, second), a, b in conflicts)
                + "\n\nStopping: a book is described once. Give each setting "
                "the same value in every file, or set it in one file only.\n"
                "  Nothing was converted.")
        if own:
            say(f"NOTE: {CONFIG_NAME} and {PACKAGING_NAME} each describe the "
                f"book in a project: block. They agree; {PROJECT_NAME}, which "
                "both halves read, would say it once, so the two can't come "
                "to disagree.")
    targets = []
    try:
        for name in declared or [None]:
            resolved = oerconfig.resolve(schema, project_schema, documents,
                                         target=name,
                                         allow_unknown=allow_unknown)
            if name is None:
                # No targets declared: one implied html target, which
                # writes into html/ like any other target would.
                name = "html"
            targets.append(Target(name, resolved, base))
    except oerconfig.ConfigError as exc:
        die(str(exc))
    # A format the schema names before a target can build it is skipped,
    # and said to be, rather than read, filtered, and then quietly never
    # written. (pdf was one until it was built.)
    for target in targets:
        if target.format in NOT_YET_IMPLEMENTED:
            say(f"WARNING: target {target.name} is format {target.format}, "
                "which is NOT YET IMPLEMENTED (see ROADMAP.md); nothing is "
                "written for it.")
    targets = [t for t in targets if t.format not in NOT_YET_IMPLEMENTED]
    if not targets:
        die("Every target here is a format that is NOT YET IMPLEMENTED "
            f"({', '.join(NOT_YET_IMPLEMENTED)}); add an html, epub3, or "
            "markdown target to conversion.yaml.")
    for warning in targets[0].resolved.warnings if targets else []:
        say(f"WARNING: {warning}")

    # Stage fingerprints: targets whose filter-stage settings agree share
    # a filtered intermediate. The first target with a fingerprint owns
    # the content directory; a later one with a different fingerprint gets
    # its own directory under its output directory.
    stages = {}

    def walk(node):
        if node.keys:
            for child in node.keys.values():
                walk(child)
        else:
            stages[node.path] = node.stage
    walk(schema.root)
    names = {t.name for t in targets}
    for target in targets:
        values = {path: target[path] for path, stage in stages.items()
                  if stage == "filter"}
        # A variant source for this target -- <stem>.<target>.md -- makes
        # its intermediates its own, so it goes into the fingerprint.
        target.variants = variant_sources(base, target.name)
        values["variants"] = sorted(target.variants.values())
        target.fingerprint = json.dumps(values, sort_keys=True, default=str)
    all_variants = {os.path.basename(p) for t in targets
                    for p in t.variants.values()}
    for target in targets:
        target.variant_files = all_variants
    globals()["VARIANT_FILES"] = all_variants
    globals()["TARGET_NAMES"] = names
    owners = {}
    for target in targets:
        if target.fingerprint not in owners:
            owners[target.fingerprint] = target
            target.pages_dir = base if len(owners) == 1 else \
                os.path.join(target.output_dir, "intermediates")
        else:
            target.pages_dir = owners[target.fingerprint].pages_dir
    return targets, targets[0].resolved.project


def resolve_path(base, name):
    """A setting's path: absolute as given, otherwise against the
    content directory.

    Resolving "$PWD/$name" unconditionally turned an absolute setting into
    "/book//home/you/sidecars/table-captions.csv", which no filter could
    read and nothing reported except an instruction to append your work
    to a path that did not exist.
    """
    name = str(name)
    return name if os.path.isabs(name) else os.path.join(base, name)


def check_sidecar(path, setting, default, base):
    """A sidecar the config names but the filter cannot read is almost
    always a wrong path rather than a deliberately empty one, and the run
    would otherwise succeed while silently discarding every correction in
    it. The default names are exempt: not having written one yet is the
    normal starting state."""
    if os.path.exists(path):
        return
    if os.path.basename(path) == default and \
            os.path.dirname(os.path.abspath(path)) == os.path.abspath(base):
        return
    die(f"ERROR: {setting} is set to {path}, which does not exist.\n"
        f"       A relative name resolves against {os.path.abspath(base)}.\n"
        f"       Create the file, or remove the setting to use ./{default}.")


# --------------------------------------------------------------------------
# 1. .docx -> .json
# --------------------------------------------------------------------------

VARIANT_FILES = set()       # every <stem>.<target>.<ext> in the directory
TARGET_NAMES = set()
# The book's word.headings and word.tracked_deletions, read once.
WORD_HEADINGS, WORD_DELETIONS = "keep", "accept"
LATEX_MAIN = []
LATEX_MACROS = "latex-conversion-macros.tex"
LANGUAGE_DECLARED = False
KIND_DECLARED = None        # project.kind as a file gives it, if one does
TITLE_DECLARED = False
DECLARED_PROJECT = {}
# What the sources say about the book, read from a master file: its title,
# authors, language, and order (master_hint).
BOOK_HINT = {}
# The targets not written for want of the book's name: the run ends with
# an error once everything else is written.
UNNAMED = []
# A LaTeX book's own \definecolor statements, for a PDF built from its
# pages, where a formula can still name one (\color{redcards}).
LATEX_COLORS = []
# The first master's page layout (latexsource.page_layout), for a PDF
# built from the pages.
LATEX_LAYOUT = {}
# A PDF figure written with its fonts embedded (latexbuild.embed_figure_fonts),
# by its path in the book, for the next copy that needs it.
EMBEDDED_FIGURES = {}


def variant_sources(base, target_name):
    """{stem: path} of the files that replace a source for one target:
    <stem>.<target>.md, .docx, or .html. The page keeps the stem, so
    contents, links, and sidecars don't know which file produced it."""
    found, clashes = {}, []
    where = [base] + ([os.path.join(base, PASSTHROUGH)] if PASSTHROUGH
                      else [])
    for directory in where:
        for ext in SOURCE_EXTENSIONS:
            for path in sorted(glob.glob(os.path.join(
                    directory, f"*.{target_name}{ext}"))):
                stem = os.path.basename(path)[:-len(f".{target_name}{ext}")]
                if safe_stem(stem) in found:
                    clashes.append((found[safe_stem(stem)], path))
                found[safe_stem(stem)] = path
    for one, other in clashes:
        die(f"{os.path.relpath(one, base)} and {os.path.relpath(other, base)} "
            f"are both target {target_name}'s variant of the same page. "
            "Keep one. Nothing was converted.")
    return found


def in_passthrough(base, path):
    return bool(PASSTHROUGH) and os.path.dirname(os.path.abspath(path)) \
        == os.path.abspath(os.path.join(base, PASSTHROUGH))


def is_variant(name):
    """A file whose second-to-last name segment is a target's name."""
    return name in VARIANT_FILES


def markdown_sources(base, fragments):
    """The .md files this run converts: a page each, the way a .docx is,
    those in the pass-through directory too (named by its path, since
    they're read from the book's directory as though they sat there).

    One with a same-named .docx beside it is what a v0.1 run left behind
    and is not a source; neither is a file the header or footer setting
    names. Everything else written in Markdown is a page of the book."""
    found = []
    here = sorted(glob.glob(os.path.join(base, "*.md")))
    passthrough = passthrough_dir(base)
    if passthrough:
        here += sorted(glob.glob(os.path.join(passthrough, "*.md")))
    for path in here:
        name = os.path.relpath(path, base).replace(os.sep, "/")
        if os.path.abspath(path) in fragments or is_variant(name):
            continue
        if os.path.exists(os.path.join(base, name[:-3] + ".docx")):
            continue
        # A LaTeX book's repository files, which aren't the book's pages.
        if name.lower() in REPOSITORY_FILES and latex_master(base, quiet=True):
            continue
        found.append(name)
    return found


def page_name_of(name):
    """The page a source file becomes: its name without the extension,
    made safe for a link. Every format is named the same way, so this is
    where two of them can meet."""
    return safe_stem(os.path.splitext(os.path.basename(name))[0])


def check_page_names(groups):
    """Stop when two files would be one page. The leftover rules have run
    by now (an .md beside a same-named .docx is v0.1's, an .html named
    after another source is an older layout's), so what's left is two
    files someone means as sources: ch1.md and ch1.adoc, Chapter 1.docx
    and Chapter-1.html, _pt/about.md and about.docx. One would silently
    overwrite the other's intermediate, and every sidecar keyed on the
    page (page-names.csv, a table caption's fallback key) would describe
    whichever won."""
    seen = {}
    for names in groups:
        for name in names:
            seen.setdefault(page_name_of(name), []).append(name)
    clashes = sorted((page, sorted(set(names))) for page, names in seen.items()
                     if len(set(names)) > 1)
    if clashes:
        lines = "\n".join(f"  {page}: " + ", ".join(names)
                          for page, names in clashes)
        die("These files would each be the same page:\n" + lines + "\n\n"
            "A page is named after its file, without the extension and made "
            "safe for a link, so two files can't both be one page. Rename "
            "one, or move the one that isn't a source out of the "
            "directory. Nothing was converted.")


def latex_master(base, quiet=False):
    """The LaTeX book's first master file, or None (latex_masters)."""
    found = latex_masters(base, quiet)
    return found[0] if found else None


def latex_masters(base, quiet=False, skip=()):
    """The LaTeX book's master files, in order, or []: the one .tex file
    in the book's directory with \\documentclass and \\begin{document}, or
    those latex.main names, by path or pattern, when there are several:
    the textbook when one set of chapters makes a textbook and a workbook,
    or every document when the book is a set of documents each built on
    its own (FINC 308's topics). A master that only gathers PDFs with
    \\includepdf has nothing to convert, and the run says which documents
    to name instead. skip: folders a .tex file there is a copy in (a
    run's output), not a source."""
    import latexsource
    found = latexsource.masters(base)
    chosen = []
    for entry in LATEX_MAIN:
        if os.path.isfile(os.path.join(base, entry)):
            matches = [os.path.normpath(entry)]
        else:
            matches = sorted(os.path.relpath(p, base) for p in
                             glob.glob(os.path.join(glob.escape(base), entry))
                             if os.path.isfile(p))
        whole = [m for m in matches
                 if latexsource.is_master(latexsource.read_text(os.path.join(base, m)))]
        if not whole:
            if quiet:
                return []
            die(f"latex.main names {entry}, which "
                + ("isn't here" if not matches else
                   "isn't a whole LaTeX document (one with \\documentclass and "
                   "\\begin{document})" if len(matches) == 1 else
                   "matches no whole LaTeX document (one with \\documentclass "
                   "and \\begin{document})")
                + (": " + ", ".join(found) + (" is." if len(found) == 1 else " are.")
                   if found else "."))
        chosen += [m for m in whole if m not in chosen]
    if not chosen:
        if len(found) > 1:
            if quiet:
                return []
            die(f"{len(found)} files here are each a whole LaTeX document: "
                + ", ".join(found) + ". Set latex.main to the one that is the "
                "book, or list them all when each is a part of it.")
        chosen = found[:1]
    for master in chosen:
        pdfs = latexsource.binder(base, master)
        if not pdfs:
            continue
        if quiet:
            return []
        sources, without = latexsource.binder_sources(base, pdfs, skip)
        die(f"{master} gathers {len(pdfs)} PDF(s) with \\includepdf and holds no "
            "LaTeX of its own to convert: each PDF is a document built on its "
            "own. "
            + (f"{len(sources)} of them have the LaTeX they're built from here, a "
               "whole document of the same name. To convert those, in the order "
               f"{master} gives them, name them in conversion.yaml:\n\n"
               "defaults:\n  latex:\n    main:\n"
               + "".join(f'      - "{s}"\n' for s in sources) + "\n"
               if sources else "None of them has a whole LaTeX document of the "
               "same name here; latex.main can name the documents to convert. ")
            + (f"{len(without)} have no LaTeX here: "
               + ", ".join(os.path.basename(p) for p in without[:6])
               + (", ..." if len(without) > 6 else "") + ". "
               if without and sources else "")
            + "Nothing was converted.")
    return chosen


LATEXMATH = re.compile(r"latexmath:\[((?:\\.|[^\]\\])*)\]")


def adoc_root_index_text(path):
    """The text of an AsciiDoc file with each latexmath:[...] that holds an
    escaped bracket, \\], given its brackets as character references, or
    None when there's none. A root's index in brackets, \\sqrt[3]{2}, is
    written \\sqrt[3\\]{2}, as Asciidoctor reads it (markdown-source.lua);
    Pandoc's reader ends the macro at that \\], and in a footnote loses the
    whole footnote (GIAM's). With &#91; and &#93; it reads to the end, and
    asciidoc-source.lua turns them back into the brackets."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if "\\]" not in text:
        return None

    def fix(m):
        tex = m.group(1)
        if "\\]" not in tex:
            return m.group(0)
        return "latexmath:[" + tex.replace("\\]", "&#93;").replace("[", "&#91;") + "]"
    fixed = LATEXMATH.sub(fix, text)
    return fixed if fixed != text else None


LATEX_READ_CHANGES = (
    ("ifthenelse", "\\ifthenelse on a boolean read as a toggle"),
    ("unbraced_input", "\\input without braces braced"),
    ("partial_rule", "\\cline or \\cmidrule read as a whole rule"),
    ("header_declared", "table header declaration for tagging read as the pipeline's"),
    ("longtable_head", "longtable's head of one row read as its header row"),
    ("repeated_head", "longtable's head repeated for later pages read once"),
    ("longtable_head_rows", "longtable's head of more than one row left to the census"),
    ("bounded", "\\pandocbounded image read as the image it holds"),
    ("link_contents", "link's /Contents for the PDF left out"),
    ("stacked_lines", "table cell's lines stacked in \\vtop read as lines"),
    ("minipage_breaks", "line break in a minipage read as \\newline"),
    ("multicolumn_edge", "\\multicolumn's edge spacing (@{...}) left out, so its table is read"),
    ("word_spaces", "space between words a command sets (\\hspace, \\quad, \\hfill) kept as a "
     "space, which the reader dropped, running the words together"),
    ("floatrow_boxes", "floatrow box read as the figure or table it holds, with its caption, "
     "a row of them as figures side by side"),
    ("environment_arguments", "environment of a package the reader doesn't know begun without "
     "the arguments it would print (multicols's column count), a preface before it"),
    ("artifact", "image marked artifact made decorative"),
    ("image_macro_calls", "call of the book's own macro for an image written out, "
     "so its file is found"),
    ("graphics_converted", "PDF or EPS image made SVG"),
    ("graphics_case", "image named in a different case from its file found as macOS and "
     "Windows find it (LaTeX on Linux doesn't)"),
    ("visual_title", "title set as large type read as the page's title, its "
     "sections under it"),
    ("boxes", "table of one column of prose, a box around a passage, read as a "
     "division, not a table"),
    ("column_types", "table's column type defined with \\newcolumntype "
     "written out"),
    ("item_refs", "\\ref to an enumerated item written as the item's number"),
    ("include_macro_calls", "call of the book's own macro that \\include-s a file "
     "written out, so the page begins where its file does"),
    ("environment_definitions", "environment the book defines written as the commands "
     "LaTeX makes of it, so the reader can balance its groups"),
    ("group_commands", "\\begingroup and \\endgroup read as braces"),
    ("kept_groups", "group or number after a command the reader takes whole kept "
     "apart from it, so it's read"),
    ("boxes_unwrapped", "box (\\fbox, \\makebox, \\resizebox, and the like) read as "
     "what it holds, which the reader dropped with it"),
    ("titlesec", "titlesec setting for how a heading looks left out"),
    ("colors", "color the book defines written as CSS"),
    ("nameref", "\\nameref read as a link to the label, its text the section's title"),
    ("split_floats", "float holding two captions of its own (two figures side by side) "
     "read as a float for each, as LaTeX numbers them"),
    ("subfigures", "\\subfigure or \\subfloat read as a subfigure environment, so its "
     "label and caption are kept"),
    ("wrapped_floats", "wrapfigure or wraptable read as a figure or a table, so its "
     "caption is kept"),
    ("captionof", "\\captionof read as the caption of a figure or a table around what "
     "it captions, so it's kept"),
    ("table_floats", "table float holding no table, two, or subtables read as a figure "
     "numbered as a table, so its caption is kept, once, and each subtable's"),
    ("named_refs", "\\autoref or cleveref's reference read with the name LaTeX prints "
     "before its number (Figure 1.2, figs. 1.1 to 1.3)"),
    ("bibliography", "bibliography entry written out from BibTeX's .bbl, in the book's "
     "style, where the bibliography is"),
    ("bibliography_own", "bibliography entry the book writes itself (thebibliography) "
     "written out as LaTeX sets it"),
    ("citations", "citation written as the label LaTeX prints, linked to its entry"),
    ("full_citations", "biblatex full citation (\\fullcite, \\footfullcite) written out as "
     "its entry, from BibTeX's .bbl in plain's style, where the reader dropped it"),
    ("cite_macro_calls", "call of a macro of the book's own that cites written out, so its "
     "citation is among the book's for BibTeX"),
    ("label_keys", "label or reference with whitespace in its key written without"),
    ("counter_keys", "label or reference whose key LaTeX makes of its counters "
     "(\\arabic{chapter}) written as LaTeX makes it"),
    ("counter_values", "reference or counter given the value LaTeX gives it"),
    ("equation_numbers", "display formula numbered as LaTeX numbers it, its labels "
     "anchors a reference finds"),
    ("headings_hoisted", "heading set inside a box or another environment taken out "
     "to the page's level, where its title and sections are found"),
    ("headings_raised", "page continuing a chapter, its headings below the top level, "
     "given its first heading as its H1 and title"))


def read_latex_to_json(base, masters, env, work, titles=None):
    """A LaTeX book, read whole through each of its masters by Pandoc,
    from a copy put right where Pandoc's reader can't take it
    (lib/latexsource.py), and cut into a page per \\include-d file; a
    master that \\include-s nothing is one page. titles: {page: title}, the
    ones project.yaml's contents give, for a page with no heading of its
    own. Returns (stems, order, header, parts): the pages, the book's order
    as contents entries, what the first preamble to say so says about the
    book, and [(master, its pages)], each master's in latex.main's order."""
    import latexsource
    if isinstance(masters, str):
        masters = [masters]
    stems, order, header, parts, preps, counts = [], [], {}, [], [], {}
    untitled = []
    for index, master in enumerate(masters):
        _, missing = latexsource.reached(base, master)
        if missing:
            makefiles = sorted({os.path.relpath(os.path.join(d, "Makefile"), base)
                                for d in [base] + [os.path.join(base, os.path.dirname(m))
                                                   for m in missing]
                                if os.path.isfile(os.path.join(d, "Makefile"))})
            die(f"{master} reaches {len(missing)} file(s) that aren't here: "
                + ", ".join(missing[:8]) + (", ..." if len(missing) > 8 else "")
                + ". A book's own build often makes files like these (figures "
                "drawn by another program, say), and it has to run before the "
                "book is converted, since what it makes is what the conversion "
                "reads." + (f" A Makefile is here, {makefiles[0]}: run make "
                            "there." if len(makefiles) == 1 else
                            " Makefiles are here, " + ", ".join(makefiles)
                            + ": run make in the one that makes them."
                            if makefiles else
                            " Run the book's build as its README says.")
                + " Nothing was converted.")
        prep = latexsource.prepare(base, os.path.join(work, f"latex-{index}")
                                   if len(masters) > 1 else work, master, say, LATEX_MACROS)
        preps.append(prep)
        LATEX_COLORS.extend(c for c in prep["colors"] if c not in LATEX_COLORS)
        if not LATEX_LAYOUT:
            LATEX_LAYOUT.update(prep["layout"])
        for key, n in prep["counts"].items():
            counts[key] = counts.get(key, 0) + n
        out = os.path.join(work, f"latex-book-{index}.json")
        done = run(["pandoc", "-f", "latex", "-t", "json",
                    os.path.relpath(prep["master"], prep["copy"]), "-o", out,
                    "--lua-filter=" + LATEX_FILTER], env=env, cwd=prep["copy"], check=False)
        if done.returncode:
            # A brace the book never closes reads to the end of the book:
            # Pandoc says only "unexpected end of input".
            braces = latexsource.brace_problems(base, prep["files"])
            die(f"pandoc failed with exit code {done.returncode}, reading {master}."
                + (" A brace isn't matched in the book's files, which Pandoc reads "
                   "to the end of the book: " + "; ".join(braces[:5])
                   + ". LaTeX can't build it as it is either, if it's in the preamble "
                   "(\"Loading a class or package in a group\"). Match it in the "
                   "book's file, and run again." if braces else "")
                + " Nothing was converted.")
        # A book's citations Pandoc's citeproc makes: one under biblatex, or
        # with no BibTeX here to make its bibliography as it does.
        citations = prep["citations"] or {}
        if citations.get("citeproc"):
            with open(out, encoding="utf-8") as fh:
                cites = '"t":"Cite"' in fh.read().replace(" ", "")
            if cites and latexsource.cite_with_citeproc(out, citations, env, prep["copy"]):
                counts["citeproc"] = counts.get("citeproc", 0) + 1
                if citations.get("said"):
                    say(citations["said"])
        with open(out, encoding="utf-8") as fh:
            doc = json.load(fh)
        if citations.get("found") is not None:
            made = latexsource.resolve_citations(doc["blocks"], citations)
            if made:
                counts["citations"] = counts.get("citations", 0) + made
        keys, values = latexsource.resolve_counters(doc["blocks"], prep["counters"],
                                                     counts)
        counts["counter_keys"] = counts.get("counter_keys", 0) + keys
        counts["counter_values"] = counts.get("counter_values", 0) + values
        # xcolor's svgnames and x11names, when the book loads them, for a
        # mix that names one.
        sets = latexsource.xcolor_sets(prep["layout"].get("classoption", []))
        recolored = latexsource.color_spans(
            doc["blocks"], latexsource.color_values(prep["colors"], sets), sets)
        if recolored:
            counts["colors"] = counts.get("colors", 0) + recolored
        latexsource.bibliography_heading(doc["blocks"])
        keyed = latexsource.normalize_keys(doc["blocks"])
        if keyed:
            counts["label_keys"] = counts.get("label_keys", 0) + keyed
        meta = doc.get("meta", {})
        master_stem = safe_stem(os.path.splitext(os.path.basename(master))[0])
        # The levels the reader gives a part and a chapter: one the master
        # sets between its \include-s begins a page of its own.
        levels = prep["counters"]["levels"]
        part_levels = {level for level, name in levels.items() if name == "part"}
        chapter_level = next((level for level, name in levels.items()
                              if name == "chapter"), None)
        pages = latexsource.cut_pages(doc, prep["order"], master_stem,
                                      prep["front_role"],
                                      part_levels | {chapter_level})
        own, empty, held, group = [], [], [], None
        for stem, role, blocks, master_own in pages:
            stem = safe_stem(stem)
            blocks, hoisted = latexsource.hoist_headings(
                blocks, set(prep["counters"]["theorems"]) | {"proof"})
            if hoisted:
                counts["headings_hoisted"] = counts.get("headings_hoisted", 0) + hoisted
            # An unnumbered heading with nothing in it and no label, which a
            # book sets to start a page (OpenIntro's copyright page opens
            # with \chapter*{}), and a file with nothing to read once it's
            # gone: one the master \include-s for its definitions
            # (OpenIntro's headers.tex), or for an index the pages don't have.
            blocks = [b for b in blocks if not (
                b.get("t") == "Header" and not b["c"][2] and "unnumbered" in b["c"][1][1]
                and re.fullmatch(r"section(-\d+)?", b["c"][1][0]))]
            if not blocks:
                if not master_own:
                    empty.append(stem)
                continue
            if stem in stems:
                first = next(m for m, s in parts if stem in s)
                die(f"{master} and {first} both have a page {stem}: each file is a "
                    "page, so the documents latex.main names can't share one. Name "
                    "only one of them, or documents that don't share chapters. "
                    "Nothing was converted.")
            # A part's page, which a \part the master sets begins, or a file
            # opening with one: the contents sample groups the pages after it
            # under it, until the next part or another part of the book.
            opens_part = blocks[0].get("t") == "Header" and blocks[0]["c"][0] in part_levels
            page_meta = {}
            if stem == master_stem:
                blocks, _ = latexsource.title_heading(blocks)
                if meta.get("title"):
                    page_meta["title"] = meta["title"]
            else:
                raised = latexsource.promote_headings(blocks)
                # A chapter's page in a book with parts opens a level down,
                # by design; one continuing a chapter is worth saying.
                if raised and not (chapter_level and raised == chapter_level - 1):
                    counts["headings_raised"] = counts.get("headings_raised", 0) + 1
            # A page with no one heading at its top to be its title, none at
            # all (OpenIntro's copyright page, whose \chapter*{} holds
            # nothing) or several (an article's sections, the calculus
            # notes' 22): titled as project.yaml's contents say, by the PDF
            # title a document gives hyperref (pdftitle), or by its file's
            # name written as words, where the HTML's had been the bare name.
            first = None if "title" in page_meta or latexsource.has_title_heading(blocks) \
                else latexsource.numbered_title(blocks)
            if first:
                # The one numbered heading, first at the top: the filter
                # takes it for the title, as it takes a page's only H1.
                page_meta["title-from"] = {"t": "MetaString", "c": first}
            elif "title" not in page_meta and not latexsource.has_title_heading(blocks):
                pdftitle = latexsource.pdf_title(prep["preamble"]) if stem == master_stem \
                    else None
                title = (titles or {}).get(stem) or pdftitle or stem_title(stem)
                page_meta["title"] = {"t": "MetaInlines", "c": latexsource.tag_inlines(title)}
                untitled.append((stem, title, "declared" if stem in (titles or {}) else
                                 "pdftitle" if pdftitle else "name",
                                 latexsource.has_heading(blocks)))
            with open(os.path.join(base, stem + ".json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"pandoc-api-version": doc["pandoc-api-version"],
                           "meta": page_meta, "blocks": blocks}, fh)
            own.append(stem)
            if master_own:
                held.append(stem)
            # A bibliography the run wrote out as a page of its own is one,
            # which the sample says, so adopted it's back matter.
            bibliography = bool(blocks) and blocks[0].get("t") == "Header" \
                and "bibliography" in blocks[0]["c"][1][1]
            entry = stem
            if role != "main" or bibliography:
                entry = {"page": stem}
                # A bibliography's type places it, in the back matter at the
                # top level, out of a part or the appendices it follows; a
                # \frontmatter or \backmatter before it still does.
                if role != "main" and not (bibliography and role == "appendix"):
                    entry["role"] = role
                if bibliography:
                    entry["type"] = "bibliography"
            if opens_part:
                group = {"title": latexsource.stringify(blocks[0]["c"][2])}
                if role != "main":
                    group["role"] = role
                group["items"] = [stem]
                group_role = role
                order.append(group)
            elif group is not None and role == group_role and not bibliography:
                group["items"].append(stem)
            else:
                group = None
                order.append(entry)
        stems += own
        parts.append((master, own))
        if meta.get("title") and "title" not in header:
            header["title"] = latexsource.stringify(meta["title"]["c"])
        authors = meta.get("author")
        if authors and "authors" not in header:
            items = authors["c"] if authors.get("t") == "MetaList" else [authors]
            header["authors"] = [name for a in items
                                 for name in latexsource.author_names(a.get("c", []))]
        language = latexsource.preamble_language(prep["preamble"])
        if language and "language" not in header:
            header["language"] = language
        if len(masters) == 1:
            if not prep["order"]:
                say(f"{master} is the book, one page: it \\include-s no chapters.")
            else:
                say(f"{master} is the book: {len(own)} page(s), one for each file "
                    "it \\include-s"
                    + ("" if not held else ", and one for what it holds itself"
                       if len(held) == 1 else
                       f", and {len(held)} for what it holds itself, each part or "
                       "chapter it sets between them a page of its own")
                    + (f"; {len(empty)} file(s) it \\include-s have nothing to read, "
                       "definitions or an index, and aren't pages: " + ", ".join(empty)
                       if empty else "") + ".")
    if len(masters) > 1:
        whole = sum(1 for (_, own), prep in zip(parts, preps) if not prep["order"])
        say(f"{len(masters)} LaTeX documents are the book, in the order latex.main "
            f"gives: {len(stems)} page(s)"
            + (", one for each document" if whole == len(masters) else
               f", {whole} document(s) a page each and the others a page for each "
               "file they \\include")
            + ".")
    for headed, what in ((False, "no heading of their own"),
                         (True, "no one heading at their top level to be their title, "
                                "but several")):
        guessed = [(s, t) for s, t, source, h in untitled if source == "name" and h == headed]
        if guessed:
            say(f"{len(guessed)} page(s) have {what}, so each is titled by its file's name, "
                "as words: " + ", ".join(f"{s} as \"{t}\"" for s, t in guessed[:5])
                + (", ..." if len(guessed) > 5 else "")
                + ". A heading or a \\title in the LaTeX, or a title for the page in "
                "project.yaml's contents, says it better.")
    for source, how in (("pdftitle", "by the PDF title the document gives hyperref "
                                     "(pdftitle)"),
                        ("declared", "as project.yaml's contents say")):
        titled = [(s, t) for s, t, found, _ in untitled if found == source]
        if titled:
            say(f"{len(titled)} page(s) have no one heading to be their title, so each is "
                f"titled {how}: " + ", ".join(f"{s} as \"{t}\"" for s, t in titled[:5])
                + (", ..." if len(titled) > 5 else "") + ".")
    if counts.get("drawings"):
        say(f"{counts.get('drawings_made', 0)} of {counts['drawings']} "
            "drawing(s) made images by LaTeX, in "
            f"{latexsource.RENDERED}/.")
    changed = [f"{counts[k]} {what}" for k, what in LATEX_READ_CHANGES if counts.get(k)]
    if counts.get("macros_file"):
        changed.append(f"the definitions in {LATEX_MACROS} read after the "
                       "preamble")
    if changed:
        say("Read from a copy of the LaTeX: " + "; ".join(changed) + ".")
    if counts.get("header_other"):
        say(f"WARNING: {counts['header_other']} table header declaration(s) "
            "for tagging name rows or columns past the first, which the "
            "pipeline's declarations can't say; table-headers.csv can "
            "declare those tables.")
    if counts.get("ifthenelse_left"):
        say(f"WARNING: {counts['ifthenelse_left']} \\ifthenelse with a "
            "condition other than a boolean, which Pandoc drops, both "
            "branches with it.")
    suggested, left, alt = latexsource.macro_sample(base, preps, LATEX_FILTER,
                                                    LATEX_MACROS, say)
    if suggested or left or alt:
        say(f"Wrote {latexsource.SAMPLE}: "
            + (f"{suggested + left} macro(s) whose formulas texmath can't make "
               f"MathML of, with a definition suggested for {suggested} and {left} "
               "for a person to define" if suggested or left else "")
            + ("; " if (suggested or left) and alt else "")
            + (f"{len(alt)} of the book's macros for an image ("
               + ", ".join("\\" + n for n in alt) + ") with an argument they don't "
               "use, which most calls give a phrase in, as alt text might be, and the "
               "definition that would pass it on" if alt else "")
            + f". Check it, then save it as {LATEX_MACROS}.")
    return stems, order, header, parts


def asciidoc_sources(base):
    """(sources, order, attributes): the AsciiDoc files this run converts,
    the order a master file gives them, and the master's imagesdir, which
    the files it includes would have inherited.

    A master is a file that include::s others. Read through it, Pandoc's
    reader (3.11) loses each included chapter's title and ignores
    :leveloffset:, so the master isn't read. Each file it includes is a
    source in its own right, whose title is its = line, and the order
    it includes them in is the book's order."""
    sources, order, masters, imagesdir = [], [], [], ""
    header = {}
    for path in sorted(glob.glob(os.path.join(base, "*.adoc"))
                       + glob.glob(os.path.join(base, "*.asciidoc"))):
        name = os.path.basename(path)
        if is_variant(name):
            continue
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        included = [n for n in INCLUDE.findall(text)
                    if os.path.isfile(os.path.join(base, n)) and "/" not in n]
        if included:
            masters.append(name)
            m = re.search(r"^:imagesdir:\s*(\S+)\s*$", text, re.M)
            imagesdir = imagesdir or (m.group(1) if m else "")
            header = header or asciidoc_header(text)
            order += [n for n in included if n not in order]
        else:
            sources.append(name)
    for name in masters:
        say(f"{name} includes other files, so it is the book's order and "
            "not a page: each file it includes is read on its own.")
    return sources, order, imagesdir, header


def asciidoc_header(text):
    """What a master file's header says about the book: its = title, the
    author line beneath it (names separated by ";", an email in angle
    brackets after each), and :lang:. None of it reaches the book any
    other way, since the master isn't read as a page."""
    found = {}
    lines = text.replace("\r\n", "\n").split("\n")
    for index, line in enumerate(lines):
        if line.startswith("= ") and "title" not in found:
            found["title"] = line[2:].strip()
            after = lines[index + 1].strip() if index + 1 < len(lines) else ""
            if after and not after.startswith((":", "//", "=")):
                names = [re.sub(r"\s*<[^>]*>\s*$", "", part).strip()
                         for part in after.split(";")]
                found["authors"] = [n for n in names if n]
            break
    m = re.search(r"^:lang:\s*(\S+)\s*$", text, re.M)
    if m:
        found["language"] = m.group(1)
    return found


def read_asciidoc_to_json(base, docs, env, imagesdir=""):
    """An AsciiDoc source, read into the same intermediate a .docx gets.
    asciidoc-source.lua applies imagesdir, moves the sections below the
    title, and drops Asciidoctor's own settings from the metadata."""
    stems = []
    env = dict(env, ASCIIDOC_IMAGESDIR=imagesdir)
    for name in docs:
        stem = safe_stem(os.path.splitext(name)[0])
        fixed = adoc_root_index_text(os.path.join(base, name))
        if fixed is None:
            run(["pandoc", "-f", "asciidoc", "-t", "json", name,
                 "-o", stem + ".json", "--lua-filter=" + MARKDOWN_HTML_FILTER,
                 "--lua-filter=" + ASCIIDOC_FILTER,
                 "--lua-filter=" + MEDIA_FILTER], env=env, cwd=base)
        else:
            # The text given on stdin, read from the file's own directory,
            # where its includes are found as they would be from the file.
            folder = os.path.join(base, os.path.dirname(name))
            done = subprocess.run(
                ["pandoc", "-f", "asciidoc", "-t", "json",
                 "-o", os.path.join(base, stem + ".json"),
                 "--lua-filter=" + MARKDOWN_HTML_FILTER,
                 "--lua-filter=" + ASCIIDOC_FILTER,
                 "--lua-filter=" + MEDIA_FILTER],
                input=fixed, text=True, env=env, cwd=folder,
                capture_output=True)
            sys.stderr.write(done.stderr)
            if done.returncode:
                die(f"pandoc couldn't read {name}.")
        portable_media_paths(os.path.join(base, stem + ".json"), base, name)
        stems.append(stem)
    return stems


def fill_namerefs(base, stems):
    """Each \\nameref in a LaTeX book's pages, which the copy Pandoc reads
    wrote as a link to the label with latexsource.NAMEREF_MARK for its
    text (Pandoc's reader drops \\nameref, and the text with it: OpenIntro
    Statistics's data appendix titles its sections \\section{\\nameref{...}},
    nine headings with nothing in them), given what LaTeX prints, on
    whichever page the label is: a figure's or a table's caption for its
    label, a heading's title for one in or after it, and otherwise the
    title of the section the label is in. Returns the number filled."""
    import latexsource
    docs, titles = {}, {}

    def caption(c):
        """A caption's inlines: its short form, or its first paragraph."""
        short, long = c
        if short:
            return short
        return next((b["c"] for b in long if b.get("t") in ("Plain", "Para")), [])

    def collect(node, current):
        """The title in force after node, each id's recorded on the way."""
        if isinstance(node, dict):
            kind, c = node.get("t"), node.get("c")
            if kind == "Header":
                current = c[2]
                for ident in [c[1][0]] + [s["c"][0][0] for s in c[2]
                                          if s.get("t") == "Span" and s["c"][0][0]]:
                    if ident:
                        titles.setdefault(ident, current)
                return current
            if kind in ("Figure", "Table") and c[0][0]:
                titles.setdefault(c[0][0], caption(c[1]) or current)
            elif kind in ("Div", "Span", "CodeBlock", "Code", "Link", "Image") \
                    and c and c[0][0]:
                titles.setdefault(c[0][0], current)
            for value in node.values():
                current = collect(value, current)
            return current
        if isinstance(node, list):
            for value in node:
                current = collect(value, current)
        return current
    for stem in stems:
        with open(os.path.join(base, stem + ".json"), encoding="utf-8") as fh:
            docs[stem] = json.load(fh)
        collect(docs[stem]["blocks"], [])

    def plain(inlines):
        """A title's inlines as a link's text: no link in a link, no note,
        and no id, which the title keeps: a label's empty span is left out,
        and another span keeps its text."""
        out = []
        for i in inlines:
            kind = i.get("t")
            if kind == "Note":
                continue
            if kind == "Link":
                out.extend(plain(i["c"][1]))
            elif kind == "Span":
                if i["c"][1]:
                    out.append({"t": "Span", "c": [["", i["c"][0][1], i["c"][0][2]],
                                                   plain(i["c"][1])]})
            else:
                out.append(i)
        return out
    filled, unknown = 0, []

    def title_of(label, seen):
        """The label's title as a link's text, any \\nameref in it filled
        first (a heading that is itself \\section{\\nameref{...}}), or None."""
        if label in seen or not titles.get(label):
            return None
        title = json.loads(json.dumps(titles[label]))
        fill(title, seen | {label}, count=False)
        return plain(title) or None

    def fill(node, seen=frozenset(), count=True):
        nonlocal filled
        if isinstance(node, dict):
            if node.get("t") == "Link" and node["c"][1] == [
                    {"t": "Str", "c": latexsource.NAMEREF_MARK}]:
                label = node["c"][2][0][1:]
                title = title_of(label, seen)
                if title:
                    node["c"][1] = title
                    filled += count
                else:
                    node["c"][1] = [{"t": "Str", "c": label}]
                    if count:
                        unknown.append(label)
                return
            for value in node.values():
                fill(value, seen, count)
        elif isinstance(node, list):
            for value in node:
                fill(value, seen, count)
    for stem, doc in docs.items():
        before = filled + len(unknown)
        fill(doc["blocks"])
        if filled + len(unknown) != before:
            with open(os.path.join(base, stem + ".json"), "w", encoding="utf-8") as fh:
                json.dump(doc, fh)
    if filled:
        say(f"{filled} \\nameref given the title of the section, or the caption, its "
            "label is in.")
    if unknown:
        say(f"WARNING: {len(unknown)} \\nameref name a label in no section of the book, "
            "and show the label: " + ", ".join(sorted(set(unknown))[:8]) + ".")
    return filled


def resolve_asciidoc_xrefs(base, stems, kind="AsciiDoc"):
    """Cross-references between the chapters of an AsciiDoc book, which
    were one document when Asciidoctor built it and are pages here.

    <<Unix File Permissions>> names a section by its title; Asciidoctor
    resolves that to the section's id, and Pandoc's reader (3.11) leaves
    the title as the fragment. <<crypto_review>> names an id that may
    now be in another chapter. Each such link goes to the heading or the
    id, on whichever page holds it, when exactly one does. Returns the
    number resolved."""
    docs, ids, titles = {}, {}, {}

    def text(inlines):
        return " ".join("".join(i.get("c", " ") if i["t"] == "Str" else " "
                                for i in inlines).split())

    def collect(node, stem):
        if isinstance(node, dict):
            kind, c = node.get("t"), node.get("c")
            if kind == "Header":
                ids.setdefault(c[1][0], set()).add(stem)
                titles.setdefault(text(c[2]), set()).add((stem, c[1][0]))
            elif kind in ("Div", "Span", "Figure", "Table", "CodeBlock",
                          "Code", "Link", "Image") and c and c[0][0]:
                ids.setdefault(c[0][0], set()).add(stem)
            for value in node.values():
                collect(value, stem)
        elif isinstance(node, list):
            for value in node:
                collect(value, stem)
    for stem in stems:
        with open(os.path.join(base, stem + ".json"), encoding="utf-8") as fh:
            docs[stem] = json.load(fh)
        collect(docs[stem]["blocks"], stem)
        # <<Malware>> names a chapter, whose title is its = line: metadata.
        title = docs[stem].get("meta", {}).get("title")
        if title and title.get("t") == "MetaInlines":
            titles.setdefault(text(title["c"]), set()).add((stem, ""))
    resolved = 0

    def fix(node, stem):
        nonlocal resolved
        if isinstance(node, dict):
            if node.get("t") == "Link":
                target = node["c"][2]
                if target[0].startswith("#"):
                    fragment = target[0][1:]
                    if stem not in ids.get(fragment, ()):
                        where = None
                        if len(titles.get(fragment, ())) == 1:
                            where = next(iter(titles[fragment]))
                        elif len(ids.get(fragment, ())) == 1:
                            where = (next(iter(ids[fragment])), fragment)
                        if where:
                            page, anchor = where
                            target[0] = ("" if page == stem
                                         else page + ".html") + (
                                "#" + anchor if anchor else "")
                            resolved += 1
            for value in node.values():
                fix(value, stem)
        elif isinstance(node, list):
            for value in node:
                fix(value, stem)
    for stem, doc in docs.items():
        before = resolved
        fix(doc["blocks"], stem)
        if resolved != before:
            with open(os.path.join(base, stem + ".json"), "w",
                      encoding="utf-8") as fh:
                json.dump(doc, fh)
    if resolved:
        say(f"{resolved} {kind} cross-reference(s) resolved to the "
            "section or id they name.")
    return resolved


def master_hint(order, header=None, kind="AsciiDoc", documents=False,
                contents_declared=False):
    """What a master file says about the book -- its title, authors, and
    language, and as contents the order it includes its chapters in -- for
    project-sample.yaml, which the packager writes (or this run, when
    there's no packager), and for naming an EPUB or a PDF that nothing
    else names. Not applied as contents: the project is the author's, and
    a run with none declared goes on with the guess until it declares
    them. documents: the order is latex.main's, a book of LaTeX documents
    each built on its own, not one master's."""
    hint = dict(header or {})
    if documents:
        # The first document's \title, which isn't the book's.
        hint.pop("title", None)
    hint["source"] = ("the LaTeX documents latex.main names" if documents
                      else f"the master {kind} file")
    if not contents_declared:
        hint["contents"] = [n if isinstance(n, dict) else
                            safe_stem(os.path.splitext(n)[0]) for n in order]
    return hint


def source_documents(base):
    """The .docx files this run converts, with the ones to skip named.

    Word writes an owner file beside any document it has open: the same
    name prefixed with "~$", the same extension, and not a zip at all.
    Pandoc fails on it and takes the whole run down with it. An empty
    file on a cloud-synced drive is usually a placeholder that has not
    been downloaded yet. A .docx is a zip, so it starts with "PK"; an old
    .doc renamed to .docx does not, and neither does a placeholder.
    """
    found = []
    for path in sorted(glob.glob(os.path.join(base, "*.docx"))):
        name = os.path.basename(path)
        if is_variant(name):
            continue                    # read for its target, below
        if name.startswith("~$"):
            say(f"Skipping {name}: Word lock file, not a document.")
            say("  Close the document in Word, or delete the file.")
            continue
        if os.path.getsize(path) == 0:
            say(f"Skipping {name}: empty file.")
            say("  On a cloud-synced drive this is usually a placeholder "
                "that has")
            say("  not been downloaded yet.")
            continue
        with open(path, "rb") as fh:
            if fh.read(2) != b"PK":
                say(f"Skipping {name}: not a .docx (no zip signature).")
                say("  An older .doc renamed to .docx looks like this. Open "
                    "it in Word")
                say("  and use Save As to convert it.")
                continue
        found.append(name)
    return found


def portable_media_paths(path, base, name):
    """A Markdown source written on Windows may name an image
    assets\\figure.png. Windows resolves that, and so does a browser;
    nothing else does, an EPUB least of all. When the same path with
    forward slashes is a file here, the intermediate takes that path and
    the run says so; the source stays the author's to fix. A backslash
    before punctuation is a Markdown escape and never reaches the path
    (assets\\_fig.png reads as assets_fig.png), so a reference that
    resolves once a separator follows a directory's name is the same
    mistake and is treated the same way. Anything else is left for the
    media gate."""
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    fixed = []

    def candidate(ref):
        if os.path.isfile(os.path.join(base, unquote(ref))):
            return None
        swapped = ref.replace("\\", "/").replace("%5C", "/") \
                     .replace("%5c", "/")
        if swapped != ref and os.path.isfile(
                os.path.join(base, unquote(swapped))):
            return swapped
        for entry in sorted(os.listdir(base)):
            rest = ref[len(entry):]
            if ref.startswith(entry) and rest \
                    and os.path.isdir(os.path.join(base, entry)) \
                    and os.path.isfile(os.path.join(base, entry,
                                                    unquote(rest))):
                return entry + "/" + rest
        return None

    def walk(node):
        if isinstance(node, dict):
            if node.get("t") == "Image":
                ref = node["c"][2][0]
                better = None if ref.startswith(EXTERNAL_REF) \
                    else candidate(ref)
                if better:
                    fixed.append((ref, better))
                    node["c"][2][0] = better
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(doc["blocks"])
    if fixed:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        for ref, better in fixed:
            say(f"WARNING: {name} names an image {ref}, a path only "
                f"Windows resolves; read as {better}. Changing it in the "
                "source is the fix.")
    return fixed


def read_markdown_to_json(base, docs, env):
    """A Markdown source is read as Pandoc's markdown, into the same
    intermediate a .docx gets. Its images are files it names by path,
    so there is nothing to extract; they are copied to each target with
    the page. Raw LaTeX in it -- \\frontmatter, \\chaptermark -- rides
    along and is dropped by the HTML and EPUB writers."""
    stems = []
    for name in docs:
        # A page is named after its source, made safe for an href: the
        # cartridge's, the EPUB's, an LMS's. "01 BigPicture.md" is the
        # page 01-BigPicture.
        stem = safe_stem(os.path.basename(name)[:-3])
        run(["pandoc", "-f", "markdown", "-t", "json", name,
             "-o", stem + ".json", "--lua-filter=" + MARKDOWN_HTML_FILTER,
             "--lua-filter=" + MEDIA_FILTER],
            env=env, cwd=base)
        portable_media_paths(os.path.join(base, stem + ".json"), base, name)
        stems.append(stem)
    return stems


def html_sources(base, others, hand):
    """The .html files this run converts: every one beside the sources,
    except what a run left there. A page named after another source is
    the page an older layout wrote beside it; a piece's name (with --)
    is the split's; a page named after one in the pass-through
    directory is a target's copy of it. A page finished by hand belongs
    in the pass-through directory, where it's copied as it stands."""
    found = []
    for path in sorted(glob.glob(os.path.join(base, "*.html"))):
        name = os.path.basename(path)
        stem = name[:-5]
        if is_variant(name) or stem in hand or stem in others \
                or safe_stem(stem) in others:
            continue
        if "--" in stem:
            if stem.split("--", 1)[0] not in others:
                say(f"WARNING: {name} is not read: '--' in a page's name "
                    "is reserved for the pages the split writes. Rename it "
                    "to convert it.")
            continue
        found.append(name)
    if found and others:
        say(f"Reading {len(found)} .html file(s) as sources alongside the "
            f"others. A page finished by hand belongs in {PASSTHROUGH}/, "
            "which is copied as it stands.")
    return found


def read_html_to_json(base, docs, env, work):
    """An HTML source is read with raw_html on, which is what stops the
    reader fetching every <iframe> over the network (Readers/HTML.hs,
    pIframe), and through html-source.lua, which turns what the page says
    about its tables into declarations and takes out what an earlier run
    of this pipeline derived. epub_html_exts lets the reader match an
    EPUB page's epub:type="noteref" to its footnote, as it matches the
    role="doc-noteref" Pandoc writes without being asked; a page with
    neither is read the same either way. Its images are files it names
    by path."""
    stems = []
    repaired_dir = os.path.join(work, "repaired-html")
    os.makedirs(repaired_dir, exist_ok=True)
    for name in docs:
        stem = safe_stem(name[:-5])
        # Pandoc reads a repaired copy -- ids moved to where its reader
        # keeps them; see lib/htmlrepair.py -- run from the book's
        # directory, so the paths the page names are still the files'.
        repaired = os.path.join(repaired_dir, name)
        moved = htmlrepair.repaired_copy(os.path.join(base, name), repaired)
        if moved and TRACE:
            say(f"# {name}: {moved} id(s) moved onto anchors the reader "
                "keeps")
        # A formula as MathJax drew it is made math again, from whatever
        # the rendering still holds; see lib/mathjax.py.
        with open(repaired, encoding="utf-8") as fh:
            markup = fh.read()
        markup, counts = mathjax.rebuilt(markup)
        if any(counts.values()):
            with open(repaired, "w", encoding="utf-8") as fh:
                fh.write(markup)
            said = {"hidden-mathml": "taken from the MathML MathJax hid "
                                     "for screen readers",
                    "tex": "read from the TeX the rendering carried",
                    "rebuilt": "rebuilt as MathML from MathJax's rendering",
                    "tex-follows": "dropped beside their TeX, which is read",
                    "lost": "lost, marked [formula]: nothing in the "
                            "rendering can be read back"}
            say(f"{name}: " + "; ".join(f"{n} formula(s) {said[k]}"
                                        for k, n in counts.items() if n))
        run(["pandoc", "-f", "html+raw_html+epub_html_exts", "-t", "json",
             repaired,
             "-o", stem + ".json", "--lua-filter=" + HTML_RAW_FILTER,
             "--lua-filter=" + HTML_SOURCE_FILTER,
             "--lua-filter=" + MEDIA_FILTER], env=env, cwd=base)
        portable_media_paths(os.path.join(base, stem + ".json"), base, name)
        stems.append(stem)
    return stems


def read_to_json(base, docs, env, work):
    """JSON rather than Markdown. Markdown is a format with opinions, and
    everything has to survive its grammar: it has no syntax for a cell
    attribute or for a header column, which are precisely what the
    remediation produces. It also picks the simplest table layout that
    fits, which silently destroys a table whose cells are all empty --
    three of them in these books, where a blank worksheet table came back
    as a paragraph break. The JSON is Pandoc's own AST, so nothing is
    lost, and `pandoc -f json -t markdown` renders it back to something
    readable whenever a human wants to look.

    The media filter runs here rather than afterwards. Word stores images
    with whatever content type the DOCX declares, which is routinely
    application/octet-stream; Pandoc turns that into a ".so" extension
    and then writes <embed> instead of <img> -- a page that validates and
    shows nothing. Renaming inside the mediabag, before --extract-media
    writes anything, means the file and the reference cannot disagree.

    --extract-media has to be on this run for the same reason: it is what
    rewrites each src to "<base>/media/...", and that path is the key the
    alt-text sidecar is stored under.
    """
    stems = []
    repaired_dir = os.path.join(work, "repaired")
    os.makedirs(repaired_dir, exist_ok=True)
    for name in docs:
        stem = safe_stem(name[:-5])
        # Pandoc reads a repaired copy -- bookmarks moved to where its
        # reader keeps them; see lib/docxrepair.py -- and the source is
        # never touched. The copy keeps the name so nothing downstream
        # sees a difference.
        repaired = os.path.join(repaired_dir, name)
        notes = []
        moved = docxrepair.repaired_copy(os.path.join(base, name), repaired,
                                         WORD_HEADINGS, WORD_DELETIONS, notes)
        for note in notes:
            say(f"WARNING: {name}: word.headings not applied: {note}.")
        if moved and TRACE:
            say(f"# {name}: {moved} bookmark(s) moved into the paragraphs "
                "they precede")
        run(["pandoc", "-f", "docx", "-t", "json", repaired,
             "-o", stem + ".json",
             "--lua-filter=" + MEDIA_FILTER, "--extract-media=" + stem],
            env=env, cwd=base)
        # ScreenTips, which Pandoc's reader drops, as the links' titles.
        tips = docxrepair.apply_screentips(repaired, os.path.join(base, stem + ".json"))
        # Word's decorative marker, which Pandoc's reader doesn't read.
        docxrepair.apply_decorative(repaired, os.path.join(base, stem + ".json"))
        # Code a list item holds in a quote, the quote the reader drops.
        docxrepair.apply_quoted_code(os.path.join(base, name), os.path.join(base, stem + ".json"))
        # A term with no definition, which the reader reads as a Div.
        docxrepair.apply_definition_terms(os.path.join(base, stem + ".json"))
        # Ids Pandoc's writer hashed, named again from the file's own map.
        docxrepair.apply_id_map(repaired, os.path.join(base, stem + ".json"))
        docxrepair.apply_list_tables(repaired, os.path.join(base, stem + ".json"))
        # Numbered code a Word target wrote, numbered again.
        docxrepair.apply_number_lines(repaired, os.path.join(base, stem + ".json"))
        if tips and TRACE:
            say(f"# {name}: {tips} ScreenTip(s) kept as link titles")
        stems.append(stem)
    return stems


LOCAL_REF = re.compile(r'\b(?:src|href)\s*=\s*"([^"]+)"', re.I)
EXTERNAL_REF = ("http://", "https://", "//", "data:", "mailto:", "tel:", "#",
                "javascript:")


PASSTHROUGH = "_pt"


def passthrough_dir(base):
    """The pass-through directory, when the project has one and it's here."""
    if not PASSTHROUGH:
        return None
    path = os.path.join(base, PASSTHROUGH)
    return path if os.path.isdir(path) else None


def hand_path(base, stem):
    return os.path.join(base, PASSTHROUGH, stem + ".html")


def hand_pages(base, stems):
    """Pages someone finished: the .html files in the pass-through
    directory. They are final, so they are copied rather than rendered,
    and their references resolve from the book's directory, as though
    they sat beside the sources."""
    found = []
    passthrough = passthrough_dir(base)
    for path in sorted(glob.glob(os.path.join(passthrough, "*.html"))
                       if passthrough else []):
        stem = os.path.basename(path)[:-5]
        if is_variant(os.path.basename(path)):
            continue
        if not is_safe(stem):
            say(f"WARNING: {stem}.html has a space or other character in "
                "its name that an LMS may not resolve in a link; renaming "
                "the file is the fix, since its own links are yours.")
        found.append(stem)
    return found


def local_references(path):
    """Local files a hand-written page refers to, for copying with it."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        markup = fh.read()
    refs = []
    for raw in LOCAL_REF.findall(markup):
        ref = raw.strip().split("#", 1)[0].split("?", 1)[0]
        if ref and not ref.startswith(EXTERNAL_REF) and ref not in refs:
            refs.append(ref)
    return refs


def copy_hand_pages(base, hand, target_dir, variants=None):
    """A hand-written page and what it refers to, byte for byte, into a
    target's directory; the target's own variant of it when there is
    one. A page linking another page of the book is left to that page; a
    file that isn't there is reported and skipped."""
    variants = variants or {}
    os.makedirs(target_dir, exist_ok=True)
    copied = []
    for stem in hand:
        source = variants.get(stem) if str(variants.get(stem, "")).endswith(
            ".html") else hand_path(base, stem)
        shutil.copy2(source, os.path.join(target_dir, stem + ".html"))
        copied.append(os.path.join(target_dir, stem + ".html"))
        for ref in local_references(source):
            if ref.endswith(".html"):
                continue
            src = os.path.normpath(os.path.join(base, ref))
            if not os.path.isfile(src) or not src.startswith(
                    os.path.abspath(base)):
                say(f"WARNING: {stem}.html refers to {ref}, which is not "
                    "here; not copied.")
                continue
            dest = os.path.join(target_dir, ref)
            if os.path.abspath(dest) == os.path.abspath(src):
                continue                # a target writing beside the sources
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(src, dest)
    return copied


def read_hand_pages(base, hand, pages_dir, env, variants=None):
    """An intermediate for each hand-written page, read from its HTML, so
    the EPUB can hold it. A person finished this page, so the only filter
    is html-raw.lua: raw tags the EPUB can't hold go, and an <iframe> is
    carried so the EPUB gets a link to it (the HTML target copies the
    page as it stands)."""
    variants = variants or {}
    out = []
    for stem in hand:
        target = os.path.join(pages_dir, stem + INTERMEDIATE)
        source = variants.get(stem) if str(variants.get(stem, "")).endswith(
            ".html") else os.path.relpath(hand_path(base, stem), base)
        # raw_html, or the reader fetches every <iframe> over the network
        # to read it into the page (Readers/HTML.hs, pIframe).
        run(["pandoc", "-f", "html+raw_html", "-t", "json", source,
             "-o", target, "--lua-filter=" + HTML_RAW_FILTER],
            env=env, cwd=base)
        out.append(target)
    return out


def read_variants(base, target, work, env):
    """This target's variant sources, read to raw JSON of their own, so
    filter_pages can take them instead of the shared ones."""
    raw = {}
    for stem, path in target.variants.items():
        name = os.path.basename(path)
        if name.endswith(".html") and in_passthrough(base, path):
            continue                    # a hand page: copied, not read
        out_dir = os.path.join(work, "variants", target.name)
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, stem + ".json")
        if name.endswith(".docx"):
            repaired = os.path.join(out_dir, name)
            docxrepair.repaired_copy(path, repaired, WORD_HEADINGS, WORD_DELETIONS)
            run(["pandoc", "-f", "docx", "-t", "json", repaired, "-o", out,
                 "--lua-filter=" + MEDIA_FILTER, "--extract-media=" + stem],
                env=env, cwd=base)
            docxrepair.apply_screentips(repaired, os.path.join(base, out)
                                        if not os.path.isabs(out) else out)
            docxrepair.apply_decorative(repaired, os.path.join(base, out)
                                        if not os.path.isabs(out) else out)
            docxrepair.apply_quoted_code(path, os.path.join(base, out)
                                         if not os.path.isabs(out) else out)
            docxrepair.apply_definition_terms(os.path.join(base, out)
                                              if not os.path.isabs(out) else out)
            docxrepair.apply_id_map(repaired, os.path.join(base, out)
                                    if not os.path.isabs(out) else out)
            docxrepair.apply_list_tables(repaired, os.path.join(base, out)
                                         if not os.path.isabs(out) else out)
            docxrepair.apply_number_lines(repaired, os.path.join(base, out)
                                          if not os.path.isabs(out) else out)
        elif name.endswith((".adoc", ".asciidoc")):
            run(["pandoc", "-f", "asciidoc", "-t", "json", path, "-o", out,
                 "--lua-filter=" + MARKDOWN_HTML_FILTER,
                 "--lua-filter=" + ASCIIDOC_FILTER,
                 "--lua-filter=" + MEDIA_FILTER], env=env, cwd=base)
            portable_media_paths(out, base, name)
        elif name.endswith(".html"):
            repaired = os.path.join(out_dir, name)
            htmlrepair.repaired_copy(path, repaired)
            run(["pandoc", "-f", "html+raw_html+epub_html_exts", "-t", "json",
                 repaired, "-o", out, "--lua-filter=" + HTML_RAW_FILTER,
                 "--lua-filter=" + HTML_SOURCE_FILTER,
                 "--lua-filter=" + MEDIA_FILTER], env=env, cwd=base)
        else:
            run(["pandoc", "-f", "markdown", "-t", "json", path, "-o", out,
                 "--lua-filter=" + MARKDOWN_HTML_FILTER,
                 "--lua-filter=" + MEDIA_FILTER], env=env, cwd=base)
            portable_media_paths(out, base, name)
        raw[stem] = out
    return raw


def warn_about_leftovers(base, stems, fragments, web=()):
    """An intermediate with no matching .docx is not this run's output.
    Say so and leave it alone rather than treating its stale state as an
    error. Markdown from a v0.1 run is no longer read by anything; it is
    named rather than removed, since deleting a user's files is not this
    script's decision to make."""
    for path in sorted(glob.glob(os.path.join(base, "*.json"))):
        name = os.path.basename(path)
        if name.endswith(INTERMEDIATE) or name[:-5] in stems:
            continue
        say(f"Skipping {name}: no matching .docx in this directory.")
        say("  It is left over from an earlier run, or its .docx has moved.")
    for path in sorted(glob.glob(os.path.join(base, "*.md"))):
        if os.path.abspath(path) in fragments:
            continue
        if not os.path.exists(path[:-3] + ".docx"):
            continue                      # a Markdown source, read above
        say(f"Note: {os.path.basename(path)} is left over from a v0.1 run "
            "and is no longer read.")
    # Pages an earlier version wrote beside the sources. They are named
    # rather than removed, since deleting a user's files is not this
    # script's decision; but they are not this run's pages, which go to
    # each target's directory.
    old = [os.path.basename(p) for p in glob.glob(os.path.join(base, "*.html"))
           if os.path.basename(p) not in web
           and (os.path.basename(p)[:-5] in stems
                or os.path.basename(p)[:-5].split("--", 1)[0] in stems)]
    if old:
        say(f"Note: {len(old)} page(s) beside the sources ({old[0]}, ...) are "
            "from an earlier run; pages now go to each target's directory.")


# --------------------------------------------------------------------------
# 2. the media gate
# --------------------------------------------------------------------------

def media_references(path):
    """Every media path the intermediate refers to. Read out of the AST
    rather than with grep, because an image path that happens to appear
    in prose is not a reference. An absolute URL is not ours to resolve."""
    refs = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("t") == "Image":
                try:
                    refs.append(node["c"][2][0])
                except (KeyError, IndexError, TypeError):
                    pass
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    with open(path, encoding="utf-8") as fh:
        walk(json.load(fh))
    return sorted(r for r in set(refs)
                  if not r.startswith(("http://", "https://", "//", "data:")))


def media_gate(base, stems, media_rows, report_path, safe=True):
    """A dead image link is invisible in the generated HTML -- Pandoc
    emits an <embed> rather than an <img> for an extension it does not
    recognize. Stopping here is deliberate: broken output that looks fine
    is worse than no output.

    v0.1 spent this step repairing as well as checking, because the
    renaming happened after extraction and the two could drift apart. They
    cannot now, so what is left is a check. It is kept because the failure
    it guards against is silent, and because the media filter still
    cannot identify every format Word stores: EMF and WMF have no
    browser-renderable equivalent and have to go back to the author.
    """
    problems, rows = [], []
    # Two files an HTML target would copy to one name: "a b.png" and
    # "a-b.png" are both written as a-b.png, and the second copy would
    # replace the first under every page that shows either.
    written = {}
    for stem in stems:
        for ref in media_references(os.path.join(base, stem + ".json")):
            # A Markdown source writes a space in a file name as %20, as a
            # link must; the file on disk has the space.
            path = os.path.join(base, unquote(ref))
            if safe and os.path.isfile(path):
                name = safe_path(unquote(ref))
                real = os.path.realpath(path)
                other = written.setdefault(name, (real, unquote(ref)))
                if other[0] != real:
                    problems.append(f"UNRESOLVED: {other[1]} and "
                                    f"{unquote(ref)} would both be written "
                                    f"as {name}.")
                    rows.append(f"{ref},{stem}.json,,would be written as "
                                f"{name}, the name {other[1]} is written as")
            if not os.path.isfile(path):
                problems.append(f"UNRESOLVED: {stem}.json references "
                                f"missing {ref}.")
                rows.append(f"{ref},{stem}.json,,referenced but not on disk")
                continue
            # On disk and not an image: an exporter that could not fetch a
            # picture has been seen to save the server's error page under
            # the picture's name, 120 times in one EPUB. Only a positive
            # identification stops the run; a format this does not know
            # is not evidence of anything.
            with open(path, "rb") as fh:
                head = fh.read(512).lstrip().lower()
            if head.startswith((b"<!doctype html", b"<html", b"<head")):
                problems.append(f"UNRESOLVED: {stem}.json shows {ref} as an "
                                "image, and it is an HTML page.")
                rows.append(f"{ref},{stem}.json,text/html,an HTML page where "
                            "an image should be")
    # Anything the media filter could not identify. Its rows are already
    # in the right shape, so they are folded in here and one gate covers
    # both.
    if os.path.exists(media_rows):
        with open(media_rows, encoding="utf-8") as fh:
            for row in fh:
                row = row.strip()
                if row:
                    rows.append(row)
                    problems.append(f"UNRESOLVED: {row.split(',')[0]} could "
                                    "not be identified.")
    if not problems:
        return
    say("")
    say("===================================================")
    for problem in problems:
        say(problem)
    say("===================================================")
    say(f"Stopping: {len(problems)} media reference(s) could not be "
        "resolved.")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("File,Source,Detected,Problem\n")
        fh.write("\n".join(sorted(set(rows))) + "\n")
    say(f"Written to {report_path}.")
    if re.search(r"metafile|EMF|WMF", "\n".join(rows), re.I):
        say("")
        say("EMF/WMF are Word's vector formats, used for equations, SmartArt")
        say("and pasted Office charts. No browser renders them, so they have")
        say("to be replaced. In Word: right-click the image, Save as Picture,")
        say("choose PNG, then re-insert. Or convert in place:")
        say("  libreoffice --headless --convert-to png --outdir DIR FILE")
        say("and rename the result to the name the document expects.")
    die("No HTML was generated.")


# --------------------------------------------------------------------------
# 3. header and footer fragments
# --------------------------------------------------------------------------

def fragment_source(text, base, work, key):
    """The setting is Markdown, or the name of a file holding it."""
    if not text:
        return None
    text = str(text)
    candidate = os.path.join(base, text.strip())
    if "\n" not in text.strip() and os.path.isfile(candidate):
        return os.path.abspath(candidate)
    path = os.path.join(work, key + ".md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text.rstrip() + "\n")
    return path


def render_fragment(source, out):
    """Pandoc's --include-before-body and --include-after-body take HTML,
    so Markdown from the config is rendered once here and reused for every
    page. The fragment is inserted by the template, after the Lua filter
    has run, which is why promoting the leading H1 to the page title still
    works -- but also why nothing in the fragment is processed by the
    filter. Author its images with explicit alt text."""
    if not source:
        return None
    run(["pandoc", "-f", "markdown-implicit_figures", "-t", "html5",
         "--ascii", source, "-o", out])
    return out


# --------------------------------------------------------------------------
# 4. filter, split, render
# --------------------------------------------------------------------------

def filter_env(target, base, paths, env):
    """What the filter reads: the settings that change the intermediate,
    and where the sidecars and the collected report rows are."""
    r = target.resolved
    out = dict(env)
    out.update({
        "SPACER_BELOW": str(r["images.spacer_below"]),
        "STRIP_SPACER": "true" if r["images.strip_spacer"] else "false",
        "ALT_MAX_CHARS": str(r["images.alt_max_chars"]),
        "RESPONSIVE_IMAGES": "true" if r["images.responsive"] else "false",
        "WRAP_TABLES": "true" if r["tables.wrap"] else "false",
        "TABLE_MARKERS": ",".join(f"{k}={v}" for k, v in
                                  (r["tables.markers"] or {}).items()),
        "MEDIA_STRICT": "1" if r["media.strict"] else "",
        "TABLE_LABEL_PREFIXES": ",".join(map(str, r["captions.table_prefixes"])),
        "FIGURE_LABEL_PREFIXES": ",".join(map(str,
                                              r["captions.figure_prefixes"])),
        "AUTHOR_BYLINE": str(r["author_byline"]),
        "PROMOTE_H1_TO_TITLE": str(r["promote_h1_to_title"]),
        "TABLE_BANDS": str(target["tables.bands"]),
        "MATH_REPAIR_EQUATIONS": "true" if r["math.repair_equations"] else "false",
        "MATH_FROM_TEXT": "true" if r["math.from_text"] else "false",
        "MATH_KEEP": paths["math_keep"] if os.path.exists(paths["math_keep"]) else "",
        "TABLE_CAPTIONS": paths["table_captions"],
        "IMAGE_ALT": paths["image_alt"],
        "BARE_LINKS": paths["bare_links"],
        "TABLE_HEADERS": paths["table_headers"],
    })
    return out


def filter_pages(base, stems, target, env, raw=None):
    """Two Pandoc runs per page rather than one. The filter writes its
    result back out as JSON -- <page>.filtered.json -- and the HTML writer
    reads that. The extra run costs a fraction of a second per page and
    buys the thing every other output format needs: a page that has
    already been remediated, on disk, in a form any writer can consume.
    The filter is per-page by design -- its sidecar keys, its table
    numbering, and its title promotion all assume one document -- so it
    cannot simply be run over the assembled book."""
    pages_dir = target.pages_dir
    os.makedirs(pages_dir, exist_ok=True)
    written = []
    for stem in stems:
        # Pieces this source was cut into by an earlier run are this run's
        # to replace: the separator marks them as generated from it.
        for old in glob.glob(os.path.join(pages_dir, stem + "--*")):
            if old.endswith((INTERMEDIATE, ".html")):
                os.remove(old)
        out = os.path.join(pages_dir, stem + INTERMEDIATE)
        source = (raw or {}).get(stem) or os.path.join(base, stem + ".json")
        run(["pandoc", "-f", "json", "-t", "json", source, "-o", out,
             "--lua-filter=" + FIGURE_FILTER,
             "--lua-filter=" + MATH_FILTER], env=env, cwd=base)
        written.append(out)
    return written


PUBLISHER_PAGE = re.compile(r"^https?://[^/]+/books/[^/]+/pages/([^#?/]+)([#?].*)?$")


def rewrite_publisher_links(pages):
    """A link to one of this book's pages becomes a link to the page
    here: from the publisher's site, or from a Markdown source naming
    another source by file name. Runs on the filtered intermediates
    before the split, so the split and the assembler treat it as any
    other link between pages; a markdown target turns it back into a
    link to the .md file when it merges."""
    stems = {os.path.basename(p)[:-len(INTERMEDIATE)] for p in pages}
    total = 0
    for path in pages:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        count = 0

        def walk(node):
            nonlocal count
            if isinstance(node, dict):
                if node.get("t") == "Link":
                    target = node["c"][2][0]
                    m = PUBLISHER_PAGE.match(target)
                    if m and safe_stem(m.group(1)) in stems:
                        node["c"][2][0] = safe_stem(m.group(1)) + ".html" \
                            + (m.group(2) or "")
                        count += 1
                    else:
                        # A Markdown source naming another source: the
                        # page is what a reader wants, in whatever the
                        # target writes.
                        local = re.match(r"^([^/#?:]+)\.md(#.*)?$", target)
                        if local and safe_stem(local.group(1)) in stems:
                            node["c"][2][0] = (safe_stem(local.group(1))
                                               + ".html"
                                               + (local.group(2) or ""))
                            count += 1
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)
        walk(doc["blocks"])
        if count:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(doc, fh)
            total += count
    if total:
        say(f"{total} publisher link(s) now point at pages of this book.")


def split_pages(target, pages, paths, reports):
    """split-pages.py runs on the filtered intermediates, after the
    filter and before the render, so the pieces carry everything the
    filter did while the sidecar keys and the reports still name the
    source. It prints the pages to render, in reading order."""
    level = int(target["pages.split_level"])
    if level <= 0:
        for name in ("page_names_new", "page_names_report"):
            if os.path.exists(reports[name]):
                os.remove(reports[name])
        return pages
    result = run(["python3", SPLIT_TOOL, "--level", str(level),
                  "--sidecar", paths["page_names"],
                  "--new", reports["page_names_new"],
                  "--report", reports["page_names_report"]] + pages,
                 capture=True)
    sys.stderr.write(result.stderr)
    return [line for line in result.stdout.split("\n") if line.strip()]


def inline_text(text):
    """A string as Pandoc inlines."""
    out = []
    for index, word in enumerate(text.split()):
        if index:
            out.append({"t": "Space"})
        out.append({"t": "Str", "c": word})
    return out


def with_depth(entry, titles, depth):
    """(stem, title, depth) for a contents entry and everything under
    it, so a merged file keeps the nesting the book declares: a
    chapter's sections are one level down, their own pages another."""
    kind, a, b = entry
    if kind == "page":
        return [(a, titles.get(a, a), depth)]
    out = []
    for index, child in enumerate(b):
        # A group's own opening page is the group, not a level below it.
        child_depth = depth if (index == 0 and child[0] == "page"
                                and (child[2] or titles.get(child[1]))
                                == a) else depth + 1
        out += with_depth(child, titles, child_depth)
    return out


def merge_plan(tree, titles, pages):
    """[(file stem, group title, [(page stem, page title)])] for a
    markdown target that merges: one file per top-level contents entry,
    the pages under it in reading order. A page not in contents is a
    file of its own, so nothing is lost."""
    have = {os.path.basename(p)[:-len(INTERMEDIATE)]: p for p in pages}
    plan, placed, used_names = [], set(), set()
    for entry in tree:
        kind, a, b = entry
        if is_generated(entry):
            continue
        members = [(s, t, d) for s, t, d in with_depth(entry, titles, 0)
                   if s in have]
        if not members:
            continue
        title = a if kind == "group" else titles.get(a, a)
        # The file takes the name of the source its pages came from, so a
        # chapter keeps the name the author knows -- but only when they
        # are all of that source. A single-file book cut into chapters
        # has one source for every group, and each file is named for its
        # own entry instead.
        sources = {m[0].split("--", 1)[0] for m in members}
        stem = None
        if len(sources) == 1:
            source = next(iter(sources))
            whole = sum(1 for s in have if s.split("--", 1)[0] == source)
            if whole == len(members):
                stem = source
        stem = stem or safe_stem(title) or safe_stem(members[0][0])
        if stem in used_names:
            n = 2
            while f"{stem}-{n}" in used_names:
                n += 1
            stem = f"{stem}-{n}"
        used_names.add(stem)
        plan.append((stem, title, members))
        placed.update(m[0] for m in members)
    for stem in have:
        if stem not in placed:
            plan.append((stem, titles.get(stem, stem),
                         [(stem, titles.get(stem, stem), 0)]))
    return plan


def header_levels(node, found):
    if isinstance(node, dict):
        if node.get("t") == "Header":
            found.append(node["c"][0])
        for value in node.values():
            header_levels(value, found)
    elif isinstance(node, list):
        for item in node:
            header_levels(item, found)


def shift_headers(blocks, by):
    for block in blocks:
        if isinstance(block, dict):
            if block.get("t") == "Header":
                block["c"][0] = max(1, min(6, block["c"][0] + by))
            for value in block.values():
                if isinstance(value, (list, dict)):
                    shift_headers(value if isinstance(value, list)
                                  else [value], by)


def retarget_links(blocks, where):
    """A link to a page becomes a link to the file that page is in:
    inside this file, just the fragment; in another, that file and the
    page's anchor."""
    def walk(node, here):
        if isinstance(node, dict):
            if node.get("t") == "Link":
                target = node["c"][2][0]
                m = re.match(r"^([^/#?]+)\.html(#.*)?$", target)
                if m and m.group(1) in where:
                    stem, fragment = m.group(1), m.group(2) or ""
                    holder = where[stem]
                    names_file = stem == holder    # the file, not a page
                    if holder == here:
                        node["c"][2][0] = fragment or (
                            "" if names_file else "#" + stem)
                    else:
                        node["c"][2][0] = holder + ".md" + (
                            fragment or ("" if names_file else "#" + stem))
            for value in node.values():
                walk(value, here)
        elif isinstance(node, list):
            for item in node:
                walk(item, here)
    walk(blocks, where.get("__here__"))


def ids_in(node, found):
    if isinstance(node, dict):
        attr = None
        if node.get("t") in ("Header", "Div", "Span", "Table", "Figure",
                             "CodeBlock", "Code", "Link", "Image"):
            c = node.get("c")
            if isinstance(c, list):
                for part in c:
                    if (isinstance(part, list) and len(part) == 3
                            and isinstance(part[0], str)):
                        attr = part
                        break
        if attr and attr[0]:
            found.append(attr)
        for value in node.values():
            ids_in(value, found)
    elif isinstance(node, list):
        for item in node:
            ids_in(item, found)


def unique_within_file(body, seen):
    """Rename ids this file has already used, and repoint the links in
    this page that named them. Two pages of a chapter each carry an
    anchor the export numbered per file; merged, one has to move, and
    only here is it known which links belong with which copy."""
    attrs = []
    ids_in(body, attrs)
    renamed = {}
    raw_blocks = []

    def collect_raw(node):
        if isinstance(node, dict):
            if node.get("t") in ("RawBlock", "RawInline") \
                    and isinstance(node.get("c"), list) \
                    and node["c"][0] in ("html", "html5"):
                raw_blocks.append(node)
            for value in node.values():
                collect_raw(value)
        elif isinstance(node, list):
            for item in node:
                collect_raw(item)
    collect_raw(body)
    for attr in attrs:
        old = attr[0]
        if old not in seen:
            seen.add(old)
            continue
        base_id = re.sub(r"-\d+$", "", old)
        n = 1
        while f"{base_id}-{n}" in seen:
            n += 1
        attr[0] = f"{base_id}-{n}"
        seen.add(attr[0])
        renamed[old] = attr[0]
    # Ids inside a fenced HTML block (a merged-cell table the Markdown
    # target wrote that way) collide too, and no attribute holds them.
    for node in raw_blocks:
        def rename_raw(m):
            old_id = m.group(2)
            if old_id in seen and old_id not in renamed:
                base_id = re.sub(r"-\d+$", "", old_id)
                n = 1
                while f"{base_id}-{n}" in seen:
                    n += 1
                renamed[old_id] = f"{base_id}-{n}"
                seen.add(renamed[old_id])
            elif old_id not in seen:
                seen.add(old_id)
            return m.group(1) + renamed.get(old_id, old_id) + m.group(3)
        node["c"][1] = re.sub(r'(\sid=")([^"]+)(")', rename_raw, node["c"][1])
    for node in raw_blocks:
        node["c"][1] = re.sub(
            r'(href="#)([^"]+)(")',
            lambda m: m.group(1) + renamed.get(m.group(2), m.group(2))
            + m.group(3), node["c"][1])

    if renamed:
        def walk(node):
            if isinstance(node, dict):
                if node.get("t") == "Link":
                    target = node["c"][2][0]
                    if target.startswith("#") and target[1:] in renamed:
                        node["c"][2][0] = "#" + renamed[target[1:]]
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)
        walk(body)
    return len(renamed)


def merged_document(members, title, where, holder, base):
    """One document from several pages: the group's title as its own
    heading, each page a section under it, every page anchored by its
    stem so a link can still name it."""
    api, blocks, seen, moved = None, [], set(), 0
    for index, (stem, page_title, depth) in enumerate(members):
        with open(os.path.join(base, stem + INTERMEDIATE),
                  encoding="utf-8") as fh:
            doc = json.load(fh)
        api = api or doc["pandoc-api-version"]
        body = copy.deepcopy(doc["blocks"])
        level = min(6, depth + 1)
        # The page's own headings continue below its heading in the
        # merged file, whatever level they started at: a page whose
        # first heading is an h2 under a section at h2 becomes h3, not
        # h4. Shifting by the level alone skipped a level per page.
        levels = []
        header_levels(body, levels)
        shift = (level + 1 - min(levels)) if levels else 0
        shift_headers(body, shift)
        # The page's own anchor, which a previous merge wrote as the
        # heading's id and the split preserved: the heading below
        # carries it again, so one copy is enough.
        body = [b for b in body
                if not (isinstance(b, dict) and b.get("t") in ("Div", "Plain")
                        and not json.dumps(b.get("c", [])).count('"Str"')
                        and stem in json.dumps(b.get("c", []))[:200])]
        seen.add(stem)
        moved += unique_within_file(body, seen)
        opens_group = index == 0 and page_title == title
        heading = {"t": "Header", "c": [level, [stem, [], []],
                                        inline_text(page_title)]}
        if opens_group:
            # The group's own opening page: its content follows the
            # file's heading rather than repeating the title.
            blocks += body
        else:
            blocks += [heading] + body
    where = dict(where); where["__here__"] = holder
    retarget_links(blocks, where)
    if moved:
        say(f"  {holder}: {moved} id(s) renamed where two pages used one")
    return {"pandoc-api-version": api,
            "meta": {"title": {"t": "MetaString", "c": title}},
            "blocks": blocks}


def noheader(text):
    """An AsciiDoc table with no header row, said to have none. Pandoc's
    reader takes a table's first row as its header unless the table says
    noheader (Asciidoctor wants a blank line after the row as well), and
    its writer never says it, so a table with no header row came back
    with one. A table opens and closes with |===, and the writer puts
    options="header" in the attribute line before the opening one when
    there is a header row; otherwise that line gets noheader, or the table
    a line saying it."""
    lines = text.split("\n")
    out, inside = [], False
    for line in lines:
        if line == "|===":
            if not inside:
                before = out[-1] if out else ""
                if before.startswith("[") and before.endswith("]"):
                    if "header" not in before:
                        out[-1] = before[:-1].rstrip(",") + ',options="noheader"]'
                else:
                    out.append('[options="noheader"]')
            inside = not inside
        out.append(line)
    return "\n".join(out)


def math_keep_rows(path):
    """The keep sidecar's rows, (kind, page, before), each once."""
    rows = []
    if path and os.path.exists(path):
        with open(path, encoding="utf-8-sig", newline="") as fh:
            for n, row in enumerate(csv.reader(fh)):
                if n == 0 and row and row[0].strip().lower() == "kind":
                    continue
                if len(row) >= 3 and row[2]:
                    rows.append((row[0], row[1], row[2]))
    return list(dict.fromkeys(rows))


# Where each sidecar keeps its value, and its Drafted by and Reviewed
# columns, by position, since the readers read by position: the report
# a sidecar's rows are pasted from puts them last.
REVIEW_COLUMNS = {
    "image_alt": ((1,), 5, 6),
    "table_captions": ((1,), 4, 5),
    "table_headers": ((1,), 8, 9),
    "bare_links": ((1, 2), 5, 6),
    "slide_titles": ((1,), 3, 4),
    "reading_order": ((1,), 5, 6),
}
HEADER_WORDS = {"image", "label", "table", "file", "key", "url", "slide"}


def unreviewed_rows(path, columns):
    """The rows of a sidecar whose value was drafted by TextbookImprover
    or a model (Drafted by filled in) and that nobody has reviewed. A row
    without the columns was written by a person."""
    values, drafted, reviewed = columns
    found = 0
    if not path or not os.path.exists(path):
        return found
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.reader(fh):
            if not row or row[0].strip().lower() in HEADER_WORDS:
                continue
            row = row + [""] * (max(values + (drafted, reviewed)) + 1 - len(row))
            if any(row[i].strip() for i in values) and row[drafted].strip() \
                    and not row[reviewed].strip():
                found += 1
    return found


def warn_unreviewed(paths):
    """Values drafted by TextbookImprover or a model and not yet reviewed,
    said once: they're used as they stand, as the table-header guesses
    always have been, and named so a person can look at them."""
    counts = [(os.path.basename(paths[key]), unreviewed_rows(paths[key], columns))
              for key, columns in REVIEW_COLUMNS.items() if paths.get(key)]
    counts = [(name, n) for name, n in counts if n]
    if counts:
        say("%d value(s) in the sidecars were drafted by TextbookImprover or a model "
            "and not yet reviewed (%s); they're used as they stand. Put a name or "
            "initials in a row's Reviewed column once a person has checked it."
            % (sum(n for _, n in counts),
               ", ".join("%s %d" % (name, n) for name, n in counts)))


def warn_title_numbers(found):
    """Pages whose declared title stands without the section number their
    heading puts before it, said once: their <title>, and the names a
    cartridge gives them, have no number where the heading has one."""
    if not os.path.exists(found):
        return
    with open(found, encoding="utf-8") as fh:
        pairs = list(dict.fromkeys(line.rstrip("\n") for line in fh if "\t" in line))
    if pairs:
        heading, title = pairs[0].split("\t", 1)
        say(f"{len(pairs)} page(s) keep their declared title without the number their "
            f"heading puts before it (\"{heading}\" is titled \"{title}\"), in <title> "
            "and in the names a cartridge gives its pages; promote_h1_to_title: always "
            "titles them with the number.")


def warn_math_keep(sidecar, kept_file):
    """A row of the keep sidecar that kept nothing in this run: the text it
    names isn't in the book any more, or no longer reads that way."""
    rows = math_keep_rows(sidecar)
    if not rows:
        return
    matched = set()
    if os.path.exists(kept_file):
        with open(kept_file, encoding="utf-8", newline="") as fh:
            matched = {tuple(r[:3]) for r in csv.reader(fh) if len(r) >= 3}
    stale = [r for r in rows if r not in matched]
    if stale:
        say(f"WARNING: {len(stale)} row(s) of {os.path.basename(sidecar)} kept nothing in "
            "this run; the math they name isn't in the book as written there:")
        for kind, page, before in stale[:10]:
            say(f"  {kind},{page},{before}")


def remediate_sources(target, base, docs, paths, env, html_stems=(), language=None,
                      work=None, markdown=(), latex_parts=(), outputs=()):
    """A target with format source: the book's own files, remediated, one
    copy each in the target's folder under the source's name. A Word file
    gets what a person decided in the sidecars written into it, and nothing
    else changed (lib/docxremediate.py); a guess is never written, since
    in the file it would read back as the author's own. An HTML page gets
    the same (lib/htmlremediate.py), and lang when it has none; a Markdown
    file the same, edited where each element is and confirmed against
    Pandoc's reading (lib/mdremediate.py); a LaTeX book's files the alt
    text, as keys LaTeX's tagging reads (lib/texremediate.py). AsciiDoc
    sources aren't written yet. outputs: the targets' folders, which hold
    no file of the book's."""
    os.makedirs(target.output_dir, exist_ok=True)
    resolved = {}
    if env.get("TABLE_HEADERS_RESOLVED") and os.path.exists(env["TABLE_HEADERS_RESOLVED"]):
        with open(env["TABLE_HEADERS_RESOLVED"], encoding="utf-8") as fh:
            resolved = json.load(fh)
    alts = docxremediate.alt_rows(paths["image_alt"])
    titles = docxremediate.link_titles(paths["bare_links"])
    links = htmlremediate.link_rows(paths["bare_links"])
    captions = htmlremediate.caption_rows(os.path.join(work, "captions_applied")) if work else {}
    places = docxremediate.math_places(os.path.join(work, "math_places")) \
        if work and target["math.from_text"] else {}
    keep_rows = math_keep_rows(paths.get("math_keep"))
    written, totals = [], {}
    for name in docs:
        stem = os.path.splitext(name)[0]
        out = os.path.join(target.output_dir, name)
        counts = docxremediate.remediate(os.path.join(base, name), out, resolved.get(stem, []),
                                         alts.get(stem, {}), titles,
                                         str(target["compatibility_mode"]) == "15",
                                         captions=captions.get(stem, []),
                                         replacements={u: r for u, (r, _) in links.items() if r},
                                         language=language, headings=WORD_HEADINGS,
                                         deletions=WORD_DELETIONS,
                                         equations=bool(target["math.repair_equations"]),
                                         places=places.get(stem, []),
                                         keep_equations={b for k, p, b in keep_rows
                                                         if k == "equation" and p in ("", stem)})
        for key, n in counts.items():
            totals[key] = totals.get(key, 0) + n
        written.append(out)
    resolved_html = {}
    html_json = os.path.join(work, "table-headers-html.json") if work else ""
    if html_json and os.path.exists(html_json):
        with open(html_json, encoding="utf-8") as fh:
            resolved_html = json.load(fh)
    page_alts = htmlremediate.alt_rows(paths["image_alt"])
    pages = 0
    for stem in html_stems:
        name = stem + ".html"
        if not os.path.exists(os.path.join(base, name)):
            continue
        counts = htmlremediate.remediate(os.path.join(base, name),
                                         os.path.join(target.output_dir, name),
                                         resolved_html.get(stem, []), page_alts, links, language,
                                         captions.get(stem, []))
        for key, n in counts.items():
            totals[key] = totals.get(key, 0) + n
        written.append(os.path.join(target.output_dir, name))
        pages += 1
    md_files = 0
    for name in markdown:
        counts = mdremediate.remediate(
            os.path.join(base, name), os.path.join(target.output_dir, name), page_alts, links,
            captions.get(safe_stem(os.path.basename(name)[:-3]), []), language)
        for key, n in counts.items():
            totals[key] = totals.get(key, 0) + n
        written.append(os.path.join(target.output_dir, name))
        md_files += 1
    if latex_parts:
        import latexsource
        master = latex_parts[0][0]
        tagging = str(target["tagging"]) == "on"
        mathml = str(target["latex_mathml"]) == "on"
        definitions = None
        macros_path = os.path.join(base, LATEX_MACROS) if LATEX_MACROS else ""
        if str(target["latex_definitions"]) == "on" and os.path.isfile(macros_path):
            definitions = latexsource.read_text(macros_path)
        # Each master the book is read through (latex.main's, in order), with
        # a person's header decisions for its tables, by each table's place in
        # its files (latexsource.table_place), and the images and drawings its
        # pages show, by the sidecar's key, so a decision the copy couldn't
        # write is counted, not lost. A file an earlier master reaches is as
        # that master's copy wrote it.
        counts, files, written_files = {}, [], set()
        for one, stems in latex_parts:
            one_files, _ = latexsource.reached(base, one)
            decisions = {e["latex"]: e["headers"] for stem in stems
                         for e in resolved_html.get(stem, [])
                         if e.get("latex") and e.get("supplier") == "sidecar"}
            seen = set()
            for stem in stems:
                page = os.path.join(base, stem + ".json")
                if os.path.exists(page):
                    seen.update(os.path.splitext(ref)[0] for ref in media_references(page))
            merge_counts(counts, texremediate.remediate(
                base, target.output_dir, one, one_files, page_alts, tagging=tagging,
                language=language, headers=decisions, definitions=definitions,
                definitions_name=LATEX_MACROS, seen=seen, mathml=mathml,
                written=written_files))
            written_files.update(one_files)
            files += [f for f in one_files if f not in files]
        counts["unplaced"] = len(counts.get("unplaced_keys", []))
        # The book's other masters (GIAM's workbook and solutions manual),
        # since the copy is laid over the whole tree: each master beside one
        # of the book's that latex.main doesn't name, written with the files
        # only it reaches, alt text by key, and the same tagging setup.
        listed, others = {m for m, _ in latex_parts}, []
        for folder in dict.fromkeys(os.path.dirname(m) for m, _ in latex_parts):
            for other in latexsource.masters(os.path.join(base, folder) if folder else base):
                other = os.path.normpath(os.path.join(folder, other))
                if other in listed:
                    continue
                other_files, other_missing = latexsource.reached(base, other)
                if other_missing:
                    say(f"{target.name}: {other}, another master here, wasn't written: it "
                        f"reaches {len(other_missing)} file(s) that aren't here "
                        f"({', '.join(other_missing[:3])}), which its own build makes.")
                    continue
                other_counts = texremediate.remediate(
                    base, target.output_dir, other, other_files, page_alts, tagging=tagging,
                    language=language, definitions=definitions,
                    definitions_name=LATEX_MACROS, mathml=mathml, written=written_files)
                others.append((other, len([f for f in other_files
                                           if f not in written_files and f != other]),
                               other_counts))
                written_files.update(other_files)
                files += [f for f in other_files if f not in files]
        # A copy built with LaTeX's tagging, by this target or by the
        # book's own \DocumentMetadata, is where a package's tagging
        # status matters: advice from the tagging project's list.
        if tagging or any(latexsource.code_matches(
                texremediate.DOCUMENT_METADATA,
                latexsource.read_text(os.path.join(base, m))) for m, _ in latex_parts):
            import taggingstatus
            taggingstatus.check(base, [m for m, _ in latex_parts], say)
        documents = len(latex_parts)
        say(f"{target.name}: {counts['files']} LaTeX file(s) written"
            + (f" for the book's {documents} documents" if documents > 1 else "")
            + f", {counts['changed']} of them changed: {counts.get('described', 0)} "
            f"image(s) and drawing(s) given alt text and {counts.get('decorative', 0)} "
            "marked artifact, as keys LaTeX's tagging reads."
            + (f" {counts['macro_calls']} of them are calls of the book's own macros for an "
               "image, each given its key at the call, the macros left as they are."
               if counts.get("macro_calls") else "")
            + (f" {counts['definitions']} definition(s) from {LATEX_MACROS} written after "
               "the preamble, as the conversion reads them." if counts.get("definitions") else "")
            + (f" {counts.get('header_rows', 0)} table(s) declared with a header row and "
               f"{counts.get('header_columns', 0)} with a header column, from the sidecar."
               if counts.get("header_rows") or counts.get("header_columns") else "")
            + (f" {counts['declared_already']} table(s) the book declares already were left."
               if counts.get("declared_already") else "")
            + (f" {counts['headers_untagged']} table header decision(s) weren't written: "
               "a declaration needs LaTeX's tagging, which this copy doesn't have "
               "(tagging: \"on\")." if counts.get("headers_untagged") else "")
            + (" Made to build with LaTeX's tagging, with LuaLaTeX: "
               + ("\\DocumentMetadata added" if counts.get("tag_metadata")
                  else f"its own \\DocumentMetadata given {counts['tag_metadata_added']}"
                  if counts.get("tag_metadata_added")
                  else "its own \\DocumentMetadata kept")
               + f", {counts.get('tag_pdftex_options', 0)} pdftex option(s) and "
               f"{counts.get('tag_pdftex_settings', 0)} pdfTeX setting(s) taken out, "
               + ("luatex85 loaded for LuaLaTeX"
                  + (f" in {counts['tag_luatex85']} of the documents" if documents > 1 else "")
                  + ", so a test for pdfTeX (\\ifx\\pdfoutput\\undefined) takes it for "
                  "pdfTeX and pdfTeX's commands work, " if counts.get("tag_luatex85") else "")
               + f"{counts.get('tag_theorems', 0)} starred theorem(s) defined only "
               "when tagging hasn't, "
               + ("\\centerline on a line of its own made a centered paragraph, "
                  if counts.get("tag_centerline") else "")
               + ("unicode-math loaded, so each formula carries its MathML, with the "
                  "OpenType Latin Modern fonts (TeX's own design) and a fallback for "
                  "characters they lack, "
                  if counts.get("tag_math") else "")
               + (f"{counts['tag_math_stand_in']}'s symbols drawn as the Unicode characters "
                  "they are, which its own font doesn't give them, "
                  + ("so unicode-math could be loaded, " if counts.get("tag_math") else
                     "from the OpenType Latin Modern fonts and their fallback, ")
                  if counts.get("tag_math_stand_in") else "")
               + (f"the book's bold ({counts['tag_math_bold']}) made unicode-math's bold "
                  "italic, whose letters the fonts have, "
                  if counts.get("tag_math_bold") else "")
               + (f"the PostScript font families the book names ({counts['tag_gyre']}) set "
                  "in TeX Gyre's OpenType clones, where installed, which the OpenType fonts' "
                  "encoding has, "
                  if counts.get("tag_gyre") else "")
               + ("MathML set up for the book's unicode-math, "
                  if counts.get("tag_math_setup") else "")
               + (f"{counts['tag_floats']} figure(s) and table(s) tagged where the text has "
                  "them, not gathered at the end of the document, "
                  if counts.get("tag_floats") else "")
               + (f"{counts['tag_boxes']} table(s) of one column of prose, a box around a "
                  "passage, tagged as a division, not a table, "
                  if counts.get("tag_boxes") else "")
               + enumitem_message(counts.get("tag_enumitem"))
               + (f"a \\title for the PDF's title given {counts['tag_title']} document(s) "
                  "that name none"
                  + (f", {counts['tag_title_visual']} of them from the title their large "
                     "type sets" if counts.get("tag_title_visual") else "") + ", "
                  if counts.get("tag_title") else "")
               + (f"hyperref loaded in {counts['tag_hyperref']} document(s), for the PDF's "
                  "bookmarks, "
                  if counts.get("tag_hyperref") else "")
               + f"and {counts.get('tag_formulas', 0)} display formula(s) opening a "
               "paragraph in a center environment given \\leavevmode." if tagging else "")
            + (f" The formulas get no MathML: the book sets its fonts or symbols with "
               f"{counts['tag_math_kept']}, which unicode-math, which LaTeX makes MathML "
               "with, would replace." if tagging and counts.get("tag_math_kept") else "")
            + (" The formulas get no MathML, since latex_mathml is \"off\"."
               if tagging and counts.get("tag_math_off") else "")
            + (f" {counts['generated']} of them are in files the book's own build "
               "makes (beside an xfig source); building it again writes over them."
               if counts.get("generated") else "")
            + (f" {counts['pspicture']} pspicture(s) have no key for alt text and "
               "were left alone." if counts.get("pspicture") else ""))
        warn_stand_ins(target.name, [counts] + [c for _, _, c in others], "the copy")
        if others:
            say(f"{target.name}: the book's other master(s) written too, "
                + "; ".join(f"{name}" + (f" with {only} file(s) only it reaches" if only
                                         else ", which reaches no file the others don't")
                            + f", {c.get('described', 0)} image(s) and drawing(s) given alt "
                            f"text and {c.get('decorative', 0)} marked artifact"
                            for name, only, c in others)
                + (", each made to build with LaTeX's tagging as the book's is"
                   + ("; luatex85 loaded for LuaLaTeX in "
                      + ", ".join(name for name, _, c in others if c.get("tag_luatex85"))
                      + ", for a test for pdfTeX (\\ifx\\pdfoutput\\undefined) and "
                      "pdfTeX's commands"
                      if any(c.get("tag_luatex85") for _, _, c in others) else "")
                   if tagging else "") + ".")
        unplaced_warning(target.name, counts, paths, "the copy")
        written.extend(os.path.join(target.output_dir, f) for f in files)
        if tagging:
            written.extend(embed_figures(
                target, base, target.output_dir,
                list(outputs) + [os.path.join(base, latexsource.RENDERED)], "the copy"))
    others = sorted(f for f in os.listdir(base) if f.endswith(".adoc") and not f.startswith("."))
    if docs or pages or md_files or not latex_parts:
        say(f"{target.name}: {len(docs)} Word file(s), {pages} HTML page(s), and "
            f"{md_files} Markdown file(s) remediated: "
            f"{totals.get('header_rows', 0)} table(s) given header rows and "
            f"{totals.get('header_columns', 0)} a header column from the sidecar, "
            f"{totals.get('captions', 0)} caption(s) added and "
            f"{totals.get('labels_joined', 0)} description(s) joined to a label, "
            f"{totals.get('described', 0)} image(s) described, "
            f"{totals.get('decorative', 0)} marked decorative, "
            f"{totals.get('links', 0)} link title(s), "
            f"{totals.get('replaced', 0)} link(s) given their replacement address, "
            f"the language set in {totals.get('language', 0)}"
            + (f", {totals['equations_repaired']} Word equation(s) given the "
               f"characters they mean ({totals['equation_characters']} change(s))"
               if totals.get("equations_repaired") else "")
            + (f", {totals['text_equations']} equation(s) made of math typed as text"
               if totals.get("text_equations") else "")
            + (f", {totals['equations_kept']} equation(s) kept as they were by the "
               "math-keep sidecar" if totals.get("equations_kept") else "")
            + (f"; {totals['skipped']} table(s) skipped as changed since the pre-pass"
               if totals.get("skipped") else "")
            + ".")
    if totals.get("text_equations_left"):
        say(f"{target.name}: {totals['text_equations_left']} equation(s) the pages make of "
            "math typed as text not written into the Word file: its runs there aren't "
            "what the filter read, or hold a field, a tracked change, a note, or a "
            "picture. They're in math-repaired.csv.")
    if totals.get("captions_left"):
        say(f"{target.name}: {totals['captions_left']} table description(s) not written: "
            "the table, or the label paragraph beside it, isn't what the filter saw.")
    if totals.get("undecided"):
        say(f"{target.name}: {totals['undecided']} table(s) left as they are, with only "
            "the census's guess; adopt their rows from the table_headers_new report "
            "to have them written.")
    if others:
        say(f"{target.name}: {len(others)} AsciiDoc source(s) left out; format source "
            "writes Word, HTML, and Markdown sources so far.")
    skipped = totals.get("images_skipped", 0) + totals.get("links_skipped", 0)
    if skipped:
        say(f"{target.name}: {skipped} Markdown image(s) or link(s) left as they are: the "
            "text doesn't hold them as many times as Pandoc reads them, as when the same "
            "syntax also appears inside code.")
    return written


def warn_stand_ins(name, all_counts, where):
    """The warning for the packages a tagged copy doesn't load, which
    texremediate.tag counts as shims, from the counts of each master."""
    shimmed = []
    for counts in all_counts:
        shimmed += [n.strip() for n in (counts.get("tag_shims") or "").split(",")
                    if n.strip() and n.strip() not in shimmed]
    if shimmed:
        say(f"WARNING: {name}: {where} loads none of "
            + ", ".join(shimmed) + ", since LaTeX's tagging can't build a tagged PDF "
            "with them or can't tag what they make (the tagging project's status list "
            "rates each currently incompatible or never to be supported). Their commands "
            "are defined in the copy instead, to keep what the book says, not how it "
            "looks, so its PDF looks different from the book's own: "
            + texremediate.shim_changes(shimmed) + ".")


def embed_figures(target, root, out_root, skip, where):
    """The book's PDF figures under root that don't embed their fonts,
    written to out_root with them embedded (latexbuild.embed_figure_fonts),
    and said; skip: folders that aren't the book's. Returns the paths
    written."""
    import latexbuild
    names = latexbuild.figure_pdfs(root, skip)
    if not names:
        return []
    try:
        import pypdf  # noqa: F401
    except ImportError:
        say(f"{target.name}: pypdf isn't installed, so the book's {len(names)} PDF file(s) "
            "weren't checked for fonts they don't embed, which PDF/UA requires.")
        return []
    written, failed, tool = latexbuild.embed_figure_fonts(root, out_root, names,
                                                          EMBEDDED_FIGURES)
    if written:
        say(f"{target.name}: {len(written)} of the book's PDF figures written in {where} "
            "with their fonts embedded ("
            + ("Ghostscript" if tool == "gs" else "poppler's pdftocairo")
            + "), which PDF/UA requires; they drew text with fonts they didn't embed, "
            "as R's pdf() device leaves out Helvetica.")
    if failed:
        say(f"WARNING: {target.name}: {len(failed)} PDF figure(s) draw text with fonts they "
            "don't embed, which PDF/UA requires, and "
            + ("neither Ghostscript nor poppler's pdftocairo is installed to embed them"
               if tool is None else "couldn't be written with them embedded")
            + ": " + ", ".join(failed[:5]) + (", ..." if len(failed) > 5 else "") + ".")
    return [os.path.join(out_root, n) for n in written]


def merge_counts(totals, counts):
    """counts added into totals, for a book of several documents: numbers
    summed, {name: number} merged and summed, lists and comma-separated
    names joined without repeats."""
    for key, value in counts.items():
        if isinstance(value, bool) or isinstance(value, (int, float)):
            totals[key] = totals.get(key, 0) + value
        elif isinstance(value, dict):
            merged = dict(totals.get(key) or {})
            for name, n in value.items():
                merged[name] = merged.get(name, 0) + n
            totals[key] = merged
        elif isinstance(value, (list, tuple)):
            totals[key] = sorted(set(totals.get(key) or []) | set(value))
        elif isinstance(value, str):
            names = [n.strip() for n in ((totals.get(key) or "") + "," + value).split(",")
                     if n.strip()]
            totals[key] = ", ".join(dict.fromkeys(names))
    return totals


def enumitem_message(found):
    """The part of a tagged copy's message about the enumitem settings
    LaTeX's tagging's emulation of enumitem lacks (texremediate
    .enumitem_settings), ending in ", ", or "" when the book uses none."""
    if not found:
        return ""
    parts = []
    defaults = [f"{k} ({found[k]})" for k in texremediate.ENUMITEM_DEFAULTS if found.get(k)]
    if defaults:
        parts.append(", ".join(defaults) + " laid out by its defaults")
    resumed = sum(found.get(k, 0) for k in ("resume", "resume*"))
    if resumed:
        parts.append(f"resume ({resumed}) continuing the numbering")
    left_out = [f"{k} ({found[k]})" for k in texremediate.ENUMITEM_LEFT_OUT if found.get(k)]
    if left_out:
        parts.append(", ".join(left_out) + " left out")
    return (f"{sum(found.values())} list setting(s) taken that the emulation of enumitem "
            "LaTeX's tagging uses lacks, so the lists build (" + "; ".join(parts) + "), ")


def unplaced_warning(name, counts, paths, where):
    """The alt text decisions a LaTeX copy couldn't write, named
    (texremediate.remediate's unplaced_keys); where says what lacks them:
    the copy, or the PDF built from it."""
    if not counts.get("unplaced"):
        return
    keys = counts["unplaced_keys"]
    say(f"WARNING: {name}: {counts['unplaced']} image(s) and drawing(s) with alt text in "
        f"{os.path.basename(paths['image_alt'] or 'image-alt.csv')} didn't get it in "
        f"{where}: " + ", ".join(keys[:5]) + (", ..." if len(keys) > 5 else "")
        + ". The copy writes alt text at each \\includegraphics, drawing, and call "
        "of a macro the book defines around one image; these are reached another "
        "way (a macro it can't follow), are in a caption or heading, which LaTeX "
        "writes to a file and reads back, or come through a macro that sets alt "
        "text of its own. The pages have their alt text; the LaTeX needs it "
        "written in by hand.")


UNDEFINED = re.compile(r"(Reference|Citation) `([^']+)' on page \d+ undefined")


def pdf_env():
    """The environment build-pdf.py runs in: this one, and a LaTeX book's
    own colors, which its formulas can name (BOOK_LATEX_COLORS), and the
    layout its preamble gives its pages, as Pandoc's variables
    (BOOK_LATEX_LAYOUT, JSON)."""
    if not LATEX_COLORS and not LATEX_LAYOUT:
        return None
    env = dict(os.environ)
    if LATEX_COLORS:
        # A statement a line, as build-pdf.py reads them.
        env["BOOK_LATEX_COLORS"] = "\n".join(" ".join(c.split()) for c in LATEX_COLORS)
    if LATEX_LAYOUT:
        env["BOOK_LATEX_LAYOUT"] = json.dumps(LATEX_LAYOUT)
    return env


def latex_book_pdf(target, base, latex_parts, paths, work, language, project, targets):
    """A LaTeX book's PDF, built by LaTeX from the book's own files
    (pdf.from: book): the book's folder copied, the files its master
    reaches written over the copy as a source target with tagging on
    writes them, with the census's header guesses declared beside a
    person's decisions, as the pages have them, and latexmk run with
    LuaLaTeX. A book of several documents (latex.main's list) gets a PDF
    for each, named as its page is, built side by side. latex_parts:
    [(master, its pages)]. Returns the PDFs' paths; a failed build stops
    the run, with LaTeX's first errors, once every document has been
    tried."""
    import concurrent.futures
    import latexbuild
    import latexsource
    standards = [str(s).strip().lower() for s in (target["pdf.standard"] or []) if str(s).strip()]
    if "ua-2" not in standards or any(s.startswith("ua-1") for s in standards):
        die(f"The PDF for target {target.name} is built from the book's own LaTeX "
            "(pdf.from: book), which claims PDF/UA-2, and pdf.standard asks for "
            f"{', '.join(standards) or 'none'}. pdf.from: pages builds it from the "
            "converted pages, which can claim the others.")
    for program in ("latexmk", latexbuild.ENGINE):
        if shutil.which(program) is None:
            die(f"{program} is not on the path, and the PDF for target {target.name} "
                "is built from the book's own LaTeX with it (pdf.from: book; see "
                "docs/installation.md). pdf.from: pages builds it from the converted "
                "pages instead.")
    problem = latexbuild.latex_problem(say)
    if problem:
        die(problem)

    # The book's folder, but not what this run writes into it.
    build = os.path.join(work, f"pdf-{target.name}")
    if os.path.isdir(build):
        shutil.rmtree(build)
    outputs = {os.path.abspath(t.output_dir) for t in targets} | {
        os.path.abspath(os.path.join(base, latexsource.RENDERED))}

    # A version control folder and an operating system's own files aren't
    # the book's; a .latexmkrc is, with what the book's build needs.
    def leave_out(directory, names):
        return [n for n in names if n in (".git", ".hg", ".svn", ".DS_Store", "__MACOSX")
                or os.path.abspath(os.path.join(directory, n)) in outputs]
    shutil.copytree(base, build, ignore=leave_out, symlinks=True)
    # A link the book makes to something beside it (figs -> ../shared/figs)
    # would point beside the copy, where nothing is: it points where the
    # book's did. A link inside the book still finds its copy.
    root = os.path.abspath(base)
    for folder, dirs, names in os.walk(build):
        for name in dirs + names:
            link = os.path.join(folder, name)
            if not os.path.islink(link):
                continue
            pointed = os.readlink(link)
            if os.path.isabs(pointed):
                continue
            original = os.path.join(root, os.path.relpath(folder, build))
            resolved = os.path.normpath(os.path.join(original, pointed))
            if resolved != root and not resolved.startswith(root + os.sep):
                os.remove(link)
                os.symlink(resolved, link)

    resolved_html = {}
    html_json = os.path.join(work, "table-headers-html.json")
    if os.path.exists(html_json):
        with open(html_json, encoding="utf-8") as fh:
            resolved_html = json.load(fh)
    definitions = None
    macros_path = os.path.join(base, LATEX_MACROS) if LATEX_MACROS else ""
    if os.path.isfile(macros_path):
        definitions = latexsource.read_text(macros_path)
    alts = htmlremediate.alt_rows(paths["image_alt"])
    counts, written_files = {}, set()
    for master, stems in latex_parts:
        files, _ = latexsource.reached(base, master)
        # What the pages have: a person's header decision, or the census's guess.
        headers = {e["latex"]: e["headers"] for stem in stems
                   for e in resolved_html.get(stem, []) if e.get("latex") and e.get("headers")}
        seen = set()
        for stem in stems:
            page = os.path.join(base, stem + ".json")
            if os.path.exists(page):
                seen.update(os.path.splitext(ref)[0] for ref in media_references(page))
        merge_counts(counts, texremediate.remediate(
            base, build, master, files, alts, tagging=True, language=language,
            headers=headers, definitions=definitions, definitions_name=LATEX_MACROS,
            seen=seen, standard=standards, written=written_files))
        written_files.update(files)
    counts["unplaced"] = len(counts.get("unplaced_keys", []))
    warn_stand_ins(target.name, [counts], "the copy LaTeX builds")
    # The book's PDF figures with their fonts embedded, in the copy LaTeX
    # builds, where the output folders aren't.
    embed_figures(target, build, build, (), "the copy LaTeX builds")

    def one(master):
        folder = os.path.join(build, os.path.dirname(master))
        # The PDF and the log where they're looked for, whatever the book's
        # .latexmkrc says ($out_dir); the command line wins over it.
        command = ["latexmk", "-lualatex", "-outdir=.", "-auxdir=.",
                   "-interaction=nonstopmode", "-halt-on-error", "-file-line-error",
                   os.path.basename(master)]
        if TRACE:
            say("+ (in a copy of the book) " + " ".join(shell_quote(c) for c in command))
        result = subprocess.run(command, cwd=folder, capture_output=True, text=True,
                                errors="replace", stdin=subprocess.DEVNULL)
        stem = os.path.splitext(os.path.basename(master))[0]
        log_path = os.path.join(folder, stem + ".log")
        log = latexsource.read_text(log_path) if os.path.exists(log_path) else ""
        pdf = os.path.join(folder, stem + ".pdf")
        ok = result.returncode == 0 and os.path.exists(pdf)
        return master, ok, pdf, log or result.stdout

    masters = [m for m, _ in latex_parts]
    workers = max(1, min(len(masters), os.cpu_count() or 1, 4))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, masters))
    failed = [(m, log) for m, ok, _, log in results if not ok]
    for master, log in failed:
        if len(masters) > 1:
            say(f"LaTeX stopped on {master}:")
        for error in latexbuild.first_errors(log):
            say(error)
        for advice in latexbuild.failure_advice(log):
            say(advice)

    os.makedirs(target.output_dir, exist_ok=True)
    written, pages, unnamed, missing, unresolved = [], 0, 0, {}, {"reference": [], "citation": []}
    for master, ok, pdf, log in results:
        if not ok:
            continue
        # What LaTeX couldn't resolve, which the PDF prints as ?? or [?].
        for kind, name in UNDEFINED.findall(log):
            if name not in unresolved[kind.lower()]:
                unresolved[kind.lower()].append(name)
        if len(masters) == 1:
            name = str(target["filename"] or "").strip() or \
                str(project.get("identifier") or target.name)
            if not name.lower().endswith(".pdf"):
                name += ".pdf"
        else:
            name = safe_stem(os.path.splitext(os.path.basename(master))[0]) + ".pdf"
        out_path = os.path.join(target.output_dir, name)
        shutil.copyfile(pdf, out_path)
        written.append(out_path)
        found = re.search(r"Output written on .*?\((\d+) pages?", log)
        pages += int(found.group(1)) if found else 0
        unnamed += log.count("Alternative text for graphic is missing")
        for character, n in latexbuild.missing_characters(log.splitlines())[0].items():
            missing[character] = missing.get(character, 0) + n
    if missing:
        say(latexbuild.missing_warning(
            missing, "A font that has them, chosen in the book's preamble, would "
            "draw them."))
    if unresolved["reference"] or unresolved["citation"]:
        refs, cites = unresolved["reference"], unresolved["citation"]
        say(f"WARNING: LaTeX couldn't resolve {len(refs)} reference(s) and {len(cites)} "
            "citation(s), which the PDF prints as ?? and [?]: "
            + "; ".join(part for part in (
                ", ".join(refs[:5]) + (", ..." if len(refs) > 5 else "") if refs else "",
                "cited " + ", ".join(cites[:5]) + (", ..." if len(cites) > 5 else "")
                if cites else "") if part)
            + ". A label the book doesn't define, or a bibliography file that isn't "
            "beside it, would; the book's own build prints them the same way.")
    if written:
        say((f"Wrote {written[0]}: " if len(masters) == 1 else
             f"Wrote {len(written)} PDF(s) in {target.output_dir}, one for each of the "
             "book's documents, named as its page is: ")
            + (f"{pages} page(s){' in all' if len(masters) > 1 else ''}, " if pages else "")
            + "built by LaTeX from the book's own files, made to build with LaTeX's "
            f"tagging as a source target would make them: {counts.get('described', 0)} "
            f"image(s) and drawing(s) with alt text and {counts.get('decorative', 0)} "
            f"marked artifact, {counts.get('header_rows', 0)} table(s) with a header row "
            f"and {counts.get('header_columns', 0)} with a header column declared, a "
            "person's or the census's, "
            + ("each formula with its MathML, " if counts.get("tag_math") or
               counts.get("tag_math_setup") else "")
            + ("its figures and tables tagged where the text has them, "
               if counts.get("tag_floats") else "")
            + (f"{counts['tag_boxes']} table(s) of one column of prose tagged as a "
               "division, "
               if counts.get("tag_boxes") else "")
            + enumitem_message(counts.get("tag_enumitem"))
            + f"and {unnamed} figure(s) LaTeX gave a placeholder for alt text, which "
            "image-alt.csv can describe.")
    if failed:
        die((f"The PDF for target {target.name} wasn't built" if len(masters) == 1 else
             f"{len(failed)} of the {len(masters)} PDFs for target {target.name} weren't "
             "built (" + ", ".join(m for m, _ in failed[:4])
             + (", ..." if len(failed) > 4 else "") + ")")
            + ": LaTeX stopped on the book's own files, made to build with LaTeX's "
            "tagging. A book can need changes of its own to build that way "
            "(docs/latex.md says which the copy makes); pdf.from: pages builds the "
            "PDF from the converted pages instead.")
    unplaced_warning(target.name, counts, paths, "the PDF")
    return written


def render_markdown(target, pages, base, work, project, env, losses=None):
    """Markdown or AsciiDoc files as source: what the author decided, in
    Pandoc's own flavor of each, and nothing the filter derived. Or Word
    files, from the same intermediates, finished by docxtarget. One file
    per page, or with merge: groups, one per top-level entry of the book's
    contents, each page a section under it."""
    env = dict(env, TARGET_NAME=target.name)
    os.makedirs(target.output_dir, exist_ok=True)
    jobs = [(os.path.basename(p)[:-len(INTERMEDIATE)], p) for p in pages]
    # bookmarks: linked keeps the bookmarks a link anywhere in the book goes
    # to, within its page or from another, and the Word target's own.
    keep = None
    if str(target["format"]) == "docx" and str(target["bookmarks"]) == "linked":
        docs = []
        for path in pages:
            with open(path, encoding="utf-8") as fh:
                docs.append(json.load(fh))
        keep = docxtarget.keep_bookmarks(docxtarget.linked_ids(docs))
    if str(target["merge"]) == "groups":
        tree, titles, _ = book_tree(project, pages,
                                    numbering_for(target, project))
        plan = merge_plan(tree, titles, pages)
        where = {stem: holder for holder, _, members in plan
                 for stem, _, _ in members}
        # A link may name the file itself (the source a chapter's pages
        # were cut from), which is no longer a page of its own.
        for holder, _, _ in plan:
            where.setdefault(holder, holder)
        jobs = []
        for holder, title, members in plan:
            document = merged_document(members, title, where, holder,
                                       os.path.dirname(pages[0]))
            if target.format == "docx":
                # Word's outline opens at Heading 1, the group's title, as
                # a page's does (target-blocks.lua), not at its pages'
                # Heading 2 under a Title paragraph, which no outline has.
                document["meta"]["title-heading"] = {"t": "MetaInlines",
                                                     "c": inline_text(title)}
            source = os.path.join(work, f"{target.name}-{holder}.json")
            with open(source, "w", encoding="utf-8") as fh:
                json.dump(document, fh)
            jobs.append((holder, source))
        say(f"{target.name}: {len(pages)} page(s) merged into "
            f"{len(jobs)} file(s).")
    written = []
    asciidoc = target.format == "asciidoc"
    word = target.format == "docx"
    added = {"compat": 0, "tooltips": 0, "decorative": 0, "first_columns": 0}
    for stem, page in jobs:
        out = os.path.join(target.output_dir, stem + (
            ".adoc" if asciidoc else ".docx" if word else ".md"))
        if word:
            # Pandoc's writer, then what it leaves out; see docxtarget.
            # The media goes inside the file, so none is copied beside it.
            with open(page, encoding="utf-8") as fh:
                source = json.load(fh)
            if losses is not None:
                losses.extend((target.name, stem, kind, detail)
                              for kind, detail in docxtarget.losses(source))
            marked, marks = docxtarget.mark_blocks(source)
            if marks:
                page = os.path.join(work, f"{target.name}-{stem}.docx.json")
                with open(page, "w", encoding="utf-8") as fh:
                    json.dump(marked, fh)
            found = os.path.join(work, f"fidelity-{target.name}-{stem}.tsv")
            if os.path.exists(found):
                os.remove(found)
            run(["pandoc", "-f", "json", "-t", "docx", page, "-o", out,
                 "--lua-filter=" + TARGET_FILTER],
                env=dict(env, FIDELITY_FOUND=found, TITLE_WRITER="docx"), cwd=base)
            collect_losses(found, target.name, stem, losses)
            for key, n in docxtarget.finish(out, page, keep).items():
                added[key] = added.get(key, 0) + n
            written.append(out)
            continue
        if asciidoc:
            # Pandoc's modern AsciiDoc, as Asciidoctor reads it. What its
            # reader can't read back (a row span, raw HTML, an anchor as
            # it writes one) the filter writes as AsciiDoc it can; see
            # markdown-source.lua.
            found = os.path.join(work, f"fidelity-{target.name}-{stem}.tsv")
            if os.path.exists(found):
                os.remove(found)
            run(["pandoc", "-f", "json", "-t", "asciidoc", page, "-o", out,
                 "--standalone", "--wrap=none",
                 "--lua-filter=" + TARGET_FILTER,
                 "--lua-filter=" + MARKDOWN_FILTER],
                env=dict(env, FIDELITY_FOUND=found, TITLE_WRITER="asciidoc"),
                cwd=base)
            collect_losses(found, target.name, stem, losses)
            with open(out, encoding="utf-8") as fh:
                text = fh.read()
            fixed = noheader(text)
            if fixed != text:
                with open(out, "w", encoding="utf-8") as fh:
                    fh.write(fixed)
            written.append(out)
            continue
        # Pipe or grid tables, which keep an empty cell and a
        # multi-paragraph one. What Markdown cannot say (a merged-cell
        # table, a figure with an id) is written as a fenced HTML block,
        # which the reader keeps whole and the filter reads back into
        # the table or figure it was; plain raw HTML would come back one
        # tag at a time.
        found = os.path.join(work, f"fidelity-{target.name}-{stem}.tsv")
        if os.path.exists(found):
            os.remove(found)
        run(["pandoc", "-f", "json",
             "-t", "markdown-simple_tables-multiline_tables-raw_html",
             page, "-o", out,
             "--standalone", "--wrap=none", "--markdown-headings=atx",
             "--lua-filter=" + TARGET_FILTER,
             "--lua-filter=" + MARKDOWN_FILTER],
            env=dict(env, FIDELITY_FOUND=found, TITLE_WRITER="markdown"), cwd=base)
        collect_losses(found, target.name, stem, losses)
        written.append(out)
    if word:
        say(f"{target.name}: {len(written)} Word file(s), compatibility mode "
            f"15; {added['tooltips']} ScreenTip(s), {added['decorative']} "
            f"decorative image(s) marked, {added['first_columns']} header "
            "column(s) flagged"
            + (f", {added['bookmarks_removed']} bookmark(s) no link goes to removed"
               if added.get("bookmarks_removed") else "") + ".")
        return written
    copy_media(base, target.output_dir, pages, safe=False)
    return written


def number_page_headings(target, tree, titles):
    """The book's numbers on each page's own heading and <title>, when
    the book is numbered: "1.2 Data, Sampling, and Variation", as the
    EPUB's headings and the tables of contents already say. A post-edit
    of the rendered page, since the number is a fact about the book's
    structure, which the page doesn't know until the tree is built."""
    changed = []

    def walk(nodes):
        for entry in nodes:
            kind, a, b = entry
            if kind == "group":
                walk(b)
                continue
            if is_generated(entry) or not getattr(entry, "number", None):
                continue
            path = os.path.join(target.output_dir, a + ".html")
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            title = b or titles.get(a, a)
            number = entry.number
            new = text
            # Either may be wrapped across lines by the writer.
            new = re.sub(r"(<title>)(" + r"\s+".join(map(re.escape, title.split()))
                         + r")(</title>)",
                         lambda m: m.group(1) + number + " " + m.group(2)
                         + m.group(3), new, count=1)
            new = re.sub(r'(<h1(?:\s[^>]*)?>)(' + r"\s+".join(map(re.escape, title.split()))
                         + r")(</h1>)",
                         lambda m: m.group(1) + number + " " + m.group(2)
                         + m.group(3), new, count=1)
            if new != text:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(new)
                changed.append(path)
    walk(tree)
    return changed


def render_html(target, pages, base, fragments, language, env):
    env = dict(env, TARGET_NAME=target.name,
               TITLE_BLOCK=str(target["title_block"]), TITLE_WRITER="html")
    """--lua-filter figures-and-tables ran already; what remains is the
    writer. -M lang sets the html lang attribute (WCAG 3.1.1), from the
    project's declared language. v0.1 hardcoded "en" while the manifest
    read its own separate setting, so a book in any other language shipped
    pages that disagreed with the package describing them, and nothing
    checked.

    The stylesheet goes in through header-includes.lua rather than
    --include-in-header, because that option replaces the page's own
    header-includes metadata -- the author <meta>, a split page's
    provenance -- instead of adding to it.

    --math-method=mathml rather than --mathml, which Pandoc 3.11
    deprecated. MathML is now the default, so the option is stated only
    to keep the intent visible.

    --embed-resources is deliberately NOT used. Base64 data URIs inflate
    every page and Brightspace does not render them reliably from an
    imported Common Cartridge, so each page links to its extracted images
    at <page>/media/... instead.
    """
    os.makedirs(target.output_dir, exist_ok=True)
    header, footer = fragments
    written = []
    for page in pages:
        stem = os.path.basename(page)[:-len(INTERMEDIATE)]
        out = os.path.join(target.output_dir, stem + ".html")
        command = ["pandoc", "-f", "json", "-t", "html5", page, "-o", out,
                   "--standalone", "--ascii", "--math-method=mathml",
                   "--lua-filter=" + TARGET_FILTER,
                   "--lua-filter=" + SAFE_MEDIA_FILTER,
                   "--lua-filter=" + HEADER_FILTER, "-M", f"lang={language}"]
        if header:
            command.append("--include-before-body=" + header)
        if footer:
            command.append("--include-after-body=" + footer)
        run(command, env=env, cwd=base)
        written.append(out)
    copy_media(base, target.output_dir, pages)
    return written


def add_menu(target, tree, titles, written, hand, work):
    """A contents menu at the top of every page this target rendered and
    previous/next links at its foot: for pages posted as a site of their
    own. The menu is the book's tree as the contents page shows it,
    rendered once, and marks each page's own entry aria-current; it sits
    in a <details> so it takes one line until it's wanted, and a <nav>
    so it's a landmark. A pass-through page is someone's finished page
    and isn't touched."""
    from bookcontents import toc_blocks, flatten_pages
    api = json.loads(subprocess.run(
        ["pandoc", "-f", "markdown", "-t", "json"], input="",
        capture_output=True, text=True, check=True).stdout)["pandoc-api-version"]
    doc = {"pandoc-api-version": api, "meta": {},
           "blocks": toc_blocks(tree, titles, lambda s: s + ".html")}
    source = os.path.join(work, f"{target.name}-menu.json")
    with open(source, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    listing = subprocess.run(["pandoc", "-f", "json", "-t", "html5", source,
                              "--ascii"], capture_output=True, text=True,
                             check=True).stdout
    order = [stem for stem in flatten_pages(tree)]
    for path in written:
        stem = os.path.basename(path)[:-5]
        if stem in hand or not path.endswith(".html") or stem not in order:
            continue
        mine = listing.replace(f'href="{stem}.html"',
                               f'href="{stem}.html" aria-current="page"', 1)
        menu = ('<nav class="book-menu" aria-label="Contents">\n'
                '<details>\n<summary>Contents</summary>\n' + mine +
                '</details>\n</nav>\n')
        index = order.index(stem)
        steps = []
        for rel, other, arrow in (("prev", index - 1, "Previous: "),
                                  ("next", index + 1, "Next: ")):
            if 0 <= other < len(order):
                name = order[other]
                title = html_escape(titles.get(name) or name)
                steps.append(f'<a rel="{rel}" href="{name}.html">{arrow}'
                             f'{title}</a>')
        pager = ('<nav class="book-pager" aria-label="Previous and next">\n'
                 + "\n".join(steps) + "\n</nav>\n") if steps else ""
        with open(path, encoding="utf-8") as fh:
            page = fh.read()
        page = re.sub(r"(<body[^>]*>\n?)", lambda m: m.group(1) + menu,
                      page, count=1)
        page = page.replace("</body>", pager + "</body>", 1)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(page)


def html_escape(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def page_group(intermediate):
    """(group key, group title) for a page, from the provenance a split
    left in it. A chapter file's sections share the source; a single-file
    book's sections share the H1 above them; a page that was not split
    is a group of one."""
    with open(intermediate, encoding="utf-8") as fh:
        meta = json.load(fh).get("meta", {})

    def text(key):
        value = meta.get(key)
        if not value:
            return ""
        if value.get("t") == "MetaString":
            return value["c"]
        return " ".join("".join(i.get("c", " ") if i["t"] == "Str" else " "
                                for i in value.get("c", [])).split())
    source = text("source-page")
    parents = [p.get("c", "") for p in
               meta.get("page-parents", {}).get("c", [])]
    stem = os.path.basename(intermediate)[:-len(INTERMEDIATE)]
    if not source:
        return stem, text("title") or stem
    if parents:
        return (source, parents[0]), parents[0]
    return source, text("source-title") or source


def inlines_text(node):
    """The text of an inline tree, as Pandoc's stringify gives it: what's
    inside a Span or an Emph too (a title set in \\textrm, FINC 308's)."""
    if isinstance(node, dict):
        kind = node.get("t")
        if kind == "Str":
            return node["c"]
        if kind in ("Space", "SoftBreak", "LineBreak"):
            return " "
        if kind in ("Code", "Math"):
            return node["c"][1]
        if kind in ("RawInline", "Note"):
            return ""
        return inlines_text(node.get("c", []))
    if isinstance(node, list):
        return "".join(inlines_text(child) for child in node)
    return ""


def meta_text(meta, key):
    value = meta.get(key)
    if not value:
        return ""
    if value.get("t") == "MetaString":
        return value["c"]
    return " ".join(inlines_text(value.get("c", [])).split())


def numbering_for(target, project):
    """The target's say, else the book's."""
    choice = str(target["numbering"])
    if choice in ("on", "off", "True", "False"):
        return choice in ("on", "True")
    return bool(project.get("numbering"))


def book_tree(project, pages, numbered=None):
    """The book's structure over this run's pages: project.contents when
    declared, else the guess from names and provenance; numbered when
    the project says so. Returns (tree, titles, api), api being the
    Pandoc API version the intermediates carry, for a document the run
    writes itself."""
    titles, parts, roles = {}, {}, {}
    stems = []
    api = None
    for intermediate in pages:
        stem = os.path.basename(intermediate)[:-len(INTERMEDIATE)]
        stems.append(stem)
        with open(intermediate, encoding="utf-8") as fh:
            doc = json.load(fh)
        api = api or doc.get("pandoc-api-version")
        meta = doc.get("meta", {})
        titles[stem] = meta_text(meta, "title") or stem
        if meta_text(meta, "page-role"):
            roles[stem] = meta_text(meta, "page-role")
        source = meta_text(meta, "source-page")
        if source:
            m = re.match(r"(\d+)/", meta_text(meta, "page-part"))
            parents = [p.get("c", "") for p in
                       meta.get("page-parents", {}).get("c", [])]
            parts[stem] = (source, int(m.group(1)) if m else None, parents,
                           meta_text(meta, "page-position"),
                           meta_text(meta, "source-title"),
                           meta_text(meta, "page-role"))
            if meta_text(meta, "source-title") and source not in titles:
                titles[source] = meta_text(meta, "source-title")
    available, used, problems = set(stems), set(), []
    available.add("notes")          # a page the run may write itself
    contents = project.get("contents") or []
    if contents:
        expanded = expand_split_sources(contents, stems, titles, parts, roles)
        tree = walk_contents(expanded, available, used, problems,
                             suffix=INTERMEDIATE)
        if expanded is not contents:
            write_contents_sample(project, tree)
    else:
        tree = walk_contents(guess_contents(stems, None, titles, parts, roles),
                             available, used, problems, suffix=INTERMEDIATE)
    for problem in problems:
        say(f"WARNING: {problem}")
    opener_types(tree, titles)
    if project.get("numbering") if numbered is None else numbered:
        number_tree(tree, titles)
    return tree, titles, api


PROJECT_SAMPLE = "project-sample.yaml"


def write_project_sample(project, contents, notes=(), hint_contents=False):
    """project-sample.yaml, every project setting with its description, as
    the packager writes it (oerconfig.project_sample_values): the project as
    settled, with these contents, and what the sources say for what no file
    of conversion's declares. Returns (path, what the hint gave)."""
    project_schema = oerconfig.load_schema(
        os.path.join(os.path.dirname(HERE), "lib", "schema-project.yaml"))
    values, extra, used = oerconfig.project_sample_values(
        project, DECLARED_PROJECT, BOOK_HINT, contents, hint_contents, notes)
    path = os.path.join(os.getcwd(), PROJECT_SAMPLE)
    oerconfig.write_project(project_schema, values, path, notes=extra)
    return path, used


def early_project_sample(base, project, targets, check_only):
    """A master's order, written as project-sample.yaml as soon as it's
    read, so a run that stops before packaging (--check-only, or a target
    that fails) still leaves it. The packager writes the sample again at the
    end, with an outline's order when --toc gives one. Not for a book named
    in packaging.yaml's block, which keeps its packaging-sample.yaml."""
    if oerconfig.inline_project(os.path.join(base, PACKAGING_NAME)) and \
            not os.path.isfile(os.path.join(base, PROJECT_NAME)):
        return
    path, used = write_project_sample(project, [], hint_contents=True)
    packaged = any(t.format == "html" for t in targets) and not check_only
    if not packaged:
        say(f"Wrote {path} for review, with {', '.join(used)} from "
            f"{BOOK_HINT.get('source')}.")


def metadata_title(base, setting):
    """The title in the file pdf.metadata names, as build-pdf.py reads it,
    which a PDF takes over project.yaml's."""
    path = setting if os.path.isabs(setting) else os.path.join(base, setting)
    if not os.path.isfile(path):
        return ""
    if path.lower().endswith((".yaml", ".yml")):
        command = ["pandoc", "-f", "markdown", "-t", "json", "--metadata-file", path]
        stdin = ""
    else:
        command = ["pandoc", "-f", "markdown", "-t", "json", path]
        stdin = None
    result = subprocess.run(command, input=stdin, capture_output=True,
                            text=True, cwd=base)
    if result.returncode:
        return ""
    return " ".join(meta_text(json.loads(result.stdout).get("meta", {}),
                              "title").split())


BOOK_KINDS = {"epub3": "EPUB", "pdf": "PDF", "latex": "LaTeX"}


def one_page_title(pages):
    """The title of a book of one page, which is the book's: a single Word
    file or Markdown file made a book. Empty for a book of several."""
    if len(pages) != 1:
        return ""
    try:
        with open(pages[0], encoding="utf-8") as fh:
            return meta_text(json.load(fh).get("meta", {}), "title")
    except (OSError, ValueError):
        return ""


def name_book_target(target, base, pages):
    """Whether a target that writes a book -- an EPUB, a PDF, a LaTeX
    master -- has the book's name, and the title to give it when no
    configuration does. pages: the target's intermediates. Returns (ok,
    title).

    project.yaml names the book for both halves. Where nothing conversion
    reads names it, a title the sources give (a master file's, or the one
    page's of a book of one) is used, and the run says so; packaging.yaml's project: block names it only for
    packaging, so the run says to move it; and with nothing at all, the
    target isn't written, and the run says where the name goes."""
    if TITLE_DECLARED:
        return True, None
    kind = BOOK_KINDS[target.format]
    has_project = os.path.isfile(os.path.join(base, PROJECT_NAME))
    setting = str(target["pdf.metadata"] or "").strip()
    if target.format in ("pdf", "latex") and setting and metadata_title(base, setting):
        return True, None
    packaged = oerconfig.inline_project(os.path.join(base, PACKAGING_NAME))
    if packaged and packaged.get("title"):
        say(f"ERROR: target {target.name} needs the book's title, which "
            f"{PACKAGING_NAME}'s project: block gives, but only packaging "
            f"reads that file, so the {kind} isn't written. Name the book "
            f"where conversion reads it too: in {PROJECT_NAME}, which both "
            f"halves read, or in a project: block in {CONFIG_NAME}.")
        UNNAMED.append(target.name)
        return False, None
    guess, source = BOOK_HINT.get("title"), BOOK_HINT.get("source")
    if not guess:
        guess, source = one_page_title(pages), "its one page"
        if guess:
            # The sample the run writes takes it too, as the EPUB does.
            BOOK_HINT.setdefault("source", source)
            BOOK_HINT["title"] = guess
    if guess:
        say(f"WARNING: {PROJECT_NAME} doesn't name the book, so the {kind} of "
            f"target {target.name} is titled \"{guess}\", as {source} says, "
            "with the identifier "
            f"\"{target.resolved.project['identifier']}\". Name it in "
            f"{PROJECT_NAME}: its identifier and title.")
        return True, guess
    where = (f"Set title in {PROJECT_NAME}" if has_project else
             f"{PROJECT_NAME} names it, with its identifier: {PROJECT_SAMPLE} "
             "has every project setting to fill in" if not packaged else
             f"Set title in {PACKAGING_NAME}'s project: block and name the "
             f"book where conversion reads it too: in {PROJECT_NAME}, which "
             f"both halves read, or in a project: block in {CONFIG_NAME}")
    say(f"ERROR: target {target.name} needs the book's title, and nothing "
        f"here gives it, so the {kind} isn't written. {where}.")
    UNNAMED.append(target.name)
    return False, None


def write_contents_sample(project, tree):
    """contents names a page the split cut, so it stood for its pieces.
    What it resolved to is written out as project-sample.yaml, for anyone
    who means to arrange the pieces themselves: renamed to project.yaml, it
    names every piece, and a declared piece is left as declared. Written
    once per run, and only when it would differ from what project.yaml
    says; the run's own output never reads it."""
    global CONTENTS_SAMPLE_WRITTEN
    if CONTENTS_SAMPLE_WRITTEN:
        return
    CONTENTS_SAMPLE_WRITTEN = True
    write_project_sample(project, contents_from_tree(tree), [
        "contents names a page the split cut, so the page stood for its "
        "pieces. The contents below are what it resolved to."])
    say(f"contents names a page the split cut; {PROJECT_SAMPLE} has the "
        "contents it resolved to, to rename to project.yaml if you mean to "
        "arrange the pieces yourself.")


CONTENTS_SAMPLE_WRITTEN = False


def generated_pages(tree):
    out = []
    for entry in tree:
        if is_generated(entry):
            out.append(entry)
        elif entry[0] == "group":
            out += generated_pages(entry[2])
    return out


def write_generated(target, tree, titles, api, base, work, fragments,
                    language, env):
    """The pages contents asks the run to write: a contents page, as a
    nested list of links, numbered when the book is."""
    written = []
    for entry in generated_pages(tree):
        kind, name, title = entry
        if entry.generate != "toc":
            continue
        doc = {"pandoc-api-version": api,
               "meta": {"title": {"t": "MetaString", "c": title}},
               "blocks": toc_blocks(tree, titles, lambda s: s + ".html")}
        source = os.path.join(work, f"{target.name}-{name}.json")
        with open(source, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        out = os.path.join(target.output_dir, name + ".html")
        command = ["pandoc", "-f", "json", "-t", "html5", source, "-o", out,
                   "--standalone", "--ascii",
                   "--lua-filter=" + HEADER_FILTER, "-M", f"lang={language}"]
        header, footer = fragments
        if header:
            command.append("--include-before-body=" + header)
        if footer:
            command.append("--include-after-body=" + footer)
        run(command, env=env, cwd=base)
        written.append(out)
    return written


def arrange_notes(target, pages, base, work, fragments, language, env):
    """Apply notes.numbering and notes.placement to a target's rendered
    pages, and write the Notes page when placement is book."""
    numbering = str(target["notes.numbering"])
    placement = str(target["notes.placement"])
    if numbering == "page" and placement == "page":
        return []
    records = []
    for intermediate in pages:
        stem = os.path.basename(intermediate)[:-len(INTERMEDIATE)]
        path = os.path.join(target.output_dir, stem + ".html")
        if not os.path.exists(path):
            continue
        group, title = page_group(intermediate)
        with open(path, encoding="utf-8") as fh:
            records.append(notes_lib.Page(stem + ".html", fh.read(), group,
                                          title, "html"))
    notes_page = None
    if placement == "book":
        source = os.path.join(work, "notes.md")
        with open(source, "w", encoding="utf-8") as fh:
            fh.write("# Notes\n")
        out = os.path.join(target.output_dir, "notes.html")
        command = ["pandoc", "-f", "markdown", "-t", "html5", source,
                   "-o", out, "--standalone", "--ascii",
                   "--lua-filter=" + HEADER_FILTER, "-M", f"lang={language}"]
        header, footer = fragments
        if header:
            command.append("--include-before-body=" + header)
        if footer:
            command.append("--include-after-body=" + footer)
        run(command, env=env, cwd=base)
        with open(out, encoding="utf-8") as fh:
            notes_page = notes_lib.Page("notes.html", fh.read(), "notes",
                                        "Notes", "html")
    changed = notes_lib.arrange(records, numbering, placement, notes_page)
    written = []
    for page in changed:
        path = os.path.join(target.output_dir, page.name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(page.text)
        written.append(path)
    if notes_page is not None and notes_page not in changed:
        os.remove(os.path.join(target.output_dir, "notes.html"))
    elif notes_page is not None:
        written.append(os.path.join(target.output_dir, "notes.html"))
    return written


def linked_files(path):
    """Local files a page links to that aren't pages: the PDF, Word file,
    or slides a course page offers. Copied with the images, but never
    checked by the media gate: a link to a missing file didn't stop a run
    before, and isn't a reason to now."""
    refs = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("t") == "Link":
                try:
                    refs.append(node["c"][2][0])
                except (KeyError, IndexError, TypeError):
                    pass
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    with open(path, encoding="utf-8") as fh:
        walk(json.load(fh))
    out = set()
    for ref in refs:
        if re.match(r"^[a-zA-Z][\w+.-]*:|^//|^#", ref):
            continue
        target = re.split(r"[#?]", ref, maxsplit=1)[0]
        if re.search(r"\.\w+$", target) and not re.search(r"\.x?html?$",
                                                        target.lower()):
            out.add(target)
    return sorted(out)


def copy_media(base, output_dir, pages, safe=True):
    """Every local image a page refers to, copied beside the page at the
    same relative path: <source>/media/... for what was extracted from a
    .docx, assets/... or wherever for what a Markdown source names. A
    copy keeps the target's pages self-contained, which is what the
    packager assumes. So are the local files a page links to."""
    copied = set()
    for page in pages:
        for ref in media_references(page) + linked_files(page):
            if ref in copied:
                continue
            src = os.path.normpath(os.path.join(base, unquote(ref)))
            if not os.path.isfile(src):
                continue
            # Under the safe name safe-media.lua wrote into the page;
            # a markdown target writes source, whose references are the
            # author's, so its copies keep the author's names.
            dest = os.path.join(output_dir,
                                safe_path(unquote(ref)) if safe
                                else unquote(ref))
            if os.path.abspath(dest) == os.path.abspath(src):
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(src, dest)
            copied.add(ref)


# --------------------------------------------------------------------------
# 5. reports
# --------------------------------------------------------------------------

def write_report(rows_file, report, header, noun, sidecar=None, hint=None):
    """Sort and deduplicate the collected rows into a report, or remove a
    stale report when nothing is outstanding -- the file existing at all
    is the signal that there is work to do."""
    rows = []
    if os.path.exists(rows_file):
        # Rows, not lines: a field can hold a line end (an image's current
        # alt text, as OpenIntro writes its descriptions over several lines),
        # and sorting the lines took such a row apart.
        with open(rows_file, encoding="utf-8", newline="") as fh:
            rows = sorted({tuple(row) for row in csv.reader(fh) if any(row)})
    if not rows:
        if os.path.exists(report):
            os.remove(report)
        return rows
    with open(report, "w", encoding="utf-8", newline="") as fh:
        fh.write(header + "\n")
        csv.writer(fh, lineterminator="\n").writerows(rows)
    say(f"Wrote {report} ({len(rows)} {noun}).")
    if sidecar:
        say(f"Fill in the second column, then append the rows to {sidecar}.")
    if hint:
        say(hint)
    return rows


# What the Markdown and AsciiDoc targets can't write as it was, from the
# notes markdown-source.lua makes as it writes them. The Word target's are
# docxtarget.LOSSES.
SOURCE_TARGET_LOSSES = {
    "example-list": "an example list is written as a numbered list: read back, "
                    "its numbering no longer runs on through the document",
    "figure-table": "a figure holding only a table is written as the table, the "
                    "figure's caption and id its own: read back, it's a table",
    "header-column-dropped": "a table's header column is written without it: "
                             "no marker class is set for this combination",
    "footnote-paragraphs": "a footnote of several paragraphs becomes one "
                           "(an AsciiDoc footnote is one paragraph)",
    "math-in-definition-list": "display math in a definition list is written inline",
    "address-colons": "an address's \"::\" is written percent-encoded, which a "
                      "server reads as the same address",
    "title-quotes": "a link title's double quotes become typographic ones",
    "alt-quotes": "an alt text's double quotes become typographic ones",
    "root-index": "a root with an index is written as Asciidoctor reads it; "
                  "Pandoc's reader cuts the formula short",
    # EPUB, and Word for a frame (target-blocks.lua)
    "frame": "a frame becomes a link to what it shows, a video's own page for a video",
    "remote-image": "an image on another server becomes a link to it, named by its alt text",
    "file-link": "a link to a local file keeps only its text (the output check lists it too)",
}
FIDELITY_KINDS = dict(docxtarget.LOSSES, **SOURCE_TARGET_LOSSES)


def collect_losses(path, target, stem, losses):
    """The rows the filter wrote for one page, added to losses."""
    if losses is None or not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            kind, _, detail = line.rstrip("\n").partition("\t")
            if kind:
                losses.append((target, stem, kind, detail))


def write_fidelity(losses, report):
    """What each target's files can't carry, one row per page and kind,
    and a line per target on stderr; or no report when there's nothing.
    Known before writing, from each page's AST; a Word target's so far."""
    import csv
    from collections import Counter
    if not losses:
        if os.path.exists(report):
            os.remove(report)
        return
    with open(report, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["Target", "Page", "Loss", "Detail", "What happens"])
        for target, page, kind, detail in losses:
            w.writerow([target, page, kind, detail, FIDELITY_KINDS.get(kind, "")])
    for target in sorted({row[0] for row in losses}):
        kinds = Counter(kind for t, _, kind, _ in losses if t == target)
        say(f"{target}: {sum(kinds.values())} thing(s) its files can't carry "
            "(" + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items()))
            + f"); see {os.path.basename(report)}.")


def write_bare_links(rows_file, report, sidecar):
    """The bare links no sidecar row decides, one row per address with the
    pages it's on and the text before its first use; or no report when
    there are none. And a word about sidecar rows that match no bare link
    in the book, which are most likely a mistyped address."""
    import csv
    found = []
    if os.path.exists(rows_file):
        with open(rows_file, encoding="utf-8", newline="") as fh:
            found = [row for row in csv.reader(fh) if len(row) >= 5]
    new, seen = {}, set()
    for status, url, title, source, context in (r[:5] for r in found):
        seen.add(url)
        if status != "new":
            continue
        entry = new.setdefault(url, {"title": title, "sources": [],
                                     "context": context})
        if source not in entry["sources"]:
            entry["sources"].append(source)
    if new:
        with open(report, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(["URL", "Replacement", "Title", "Source", "Context",
                        "Drafted by", "Reviewed"])
            for url in sorted(new):
                e = new[url]
                w.writerow([url, "", e["title"], "; ".join(e["sources"]),
                            e["context"], "", ""])
        say(f"Wrote {report} ({len(new)} bare link(s) with no row in "
            f"{os.path.basename(sidecar)}).")
        say(f"Copy the rows into {sidecar}; fill in a Replacement, a Title, "
            "or neither to keep a link as it is.")
    elif os.path.exists(report):
        os.remove(report)
    if sidecar and os.path.exists(sidecar):
        with open(sidecar, encoding="utf-8", newline="") as fh:
            rows = [r for r in csv.reader(fh) if r and r[0].strip()
                    and r[0].strip().lower() != "url"]
        stale = [r[0].strip() for r in rows if r[0].strip() not in seen]
        if stale:
            say(f"{len(stale)} row(s) in {os.path.basename(sidecar)} match no "
                "bare link in the book: "
                + ", ".join(stale[:3]) + (" ..." if len(stale) > 3 else ""))


# --------------------------------------------------------------------------

def main():
    global TRACE
    parser = argparse.ArgumentParser(
        description="Convert the .docx files here, one output per target.",
        epilog="Anything else is passed to build-cartridge.py: --zip, "
               "--toc FILE, --check, --includeallhtml.")
    parser.add_argument("--quiet", action="store_true",
                        help="don't trace each command as it runs")
    parser.add_argument("--linked-documents", action="store_true",
                        help="when this run unpacks a Common Cartridge, make "
                        "each document its pages link to that can be "
                        "converted a page of the book (unpack-cartridge.py "
                        "--linked-documents)")
    parser.add_argument("--check-only", action="store_true",
                        help="read, gate, pre-pass, filter, and write the "
                             "reports, then stop: no output directory is "
                             "written and nothing is packaged")
    parser.add_argument("--allow-unknown-keys", action="store_true",
                        help="report settings this version does not know "
                             "about instead of refusing them")
    parser.add_argument("--quick", action="store_true",
                        help="check the output without epubcheck, the Nu HTML "
                             "checker, and veraPDF, even where they're "
                             "installed (check-output.py --quick)")
    args, passthrough = parser.parse_known_args()
    TRACE = not args.quiet
    base = os.getcwd()

    for required in (FIGURE_FILTER, MATH_FILTER, MEDIA_FILTER, HEADER_FILTER,
                     PAGE_CSS):
        if not os.path.isfile(required):
            die(f"Missing {required} -- save it alongside this script.")

    # Pandoc 3.9 introduced the options this script relies on. Earlier
    # versions accept most of the command line and quietly do something
    # else: 3.6 and older write grid tables without cell spans, so a table
    # with merged cells loses them without any warning.
    if shutil.which("pandoc") is None:
        die("pandoc not found. Version 3.9 or later is required.")
    version = subprocess.run(["pandoc", "--version"], capture_output=True,
                             text=True).stdout.split()[1]
    if tuple(int(p) for p in re.findall(r"\d+", version)[:3]) < (3, 9):
        die(f"Pandoc {version} is too old; 3.9 or later is required.")

    unpack_archives(base, check_only=args.check_only,
                    linked_documents=args.linked_documents)
    import deckrun
    decks = deckrun.deck_sources(base)
    book_here = bool(book_sources(base)) or latex_book_here(base)
    targets, project = load_targets(base, args.allow_unknown_keys,
                                    decks_only=bool(decks) and not book_here)
    # A folder is a book or a set of slides: slides when project.kind says
    # so, or when it says nothing and the folder holds decks alone.
    slides = KIND_DECLARED == "slides" or (KIND_DECLARED is None and bool(decks)
                                           and not book_here)
    if decks and not slides:
        say(f"NOTE: {len(decks)} PowerPoint deck(s) here are left out ("
            + ", ".join(decks[:4]) + (", ..." if len(decks) > 4 else "")
            + "): a deck isn't a page of a book. In a folder of their own, decks "
            "are slides, each checked and remediated (project.kind: slides).")
    global PASSTHROUGH
    PASSTHROUGH = str(project.get("passthrough", "_pt") or "").strip("/")
    for target in targets:
        target.variants = variant_sources(base, target.name)
    language = project["language"]
    first = targets[0]        # sidecars and reports are book-level settings,
    global WORD_HEADINGS, WORD_DELETIONS, LATEX_MAIN, LATEX_MACROS
    WORD_HEADINGS = str(first["word.headings"] or "keep")
    LATEX_MAIN = [str(entry).strip() for entry in (first["latex.main"] or [])
                  if str(entry).strip()]
    LATEX_MACROS = str(first["latex.macros"] or "").strip()
    WORD_DELETIONS = str(first["word.tracked_deletions"] or "accept")
    #                           which the configuration keeps out of targets
    # Two source targets write the same copies unless they differ in the one
    # setting of their own; nothing breaks, but one of them is wasted work.
    seen_sources = {}
    for target in targets:
        if target.format == "source":
            mode = str(target["compatibility_mode"])
            if mode in seen_sources:
                say(f"WARNING: {seen_sources[mode]} and {target.name} both have "
                    f"format source and compatibility_mode {mode}, so they write "
                    "the same copies; one of them would do.")
            else:
                seen_sources[mode] = target.name

    paths = {key: resolve_path(base, first[f"sidecars.{key}"])
             for key in ("table_captions", "image_alt", "table_headers",
                         "page_names", "bare_links", "math_keep", "slide_titles",
                         "reading_order")}
    for key, default in (("table_captions", "table-captions.csv"),
                         ("image_alt", "image-alt.csv"),
                         ("bare_links", "bare-links.csv"),
                         ("table_headers", "table-headers.csv"),
                         ("page_names", "page-names.csv"),
                         ("math_keep", "math-keep.csv"),
                         ("slide_titles", "slide-titles.csv"),
                         ("reading_order", "reading-order.csv")):
        check_sidecar(paths[key], f"sidecars.{key}", default, base)
    reports = {key: resolve_path(base, first[f"reports.{key}"])
               for key in ("table_captions_missing", "image_alt_missing",
                           "bare_links_new", "fidelity",
                           "table_headers_new", "table_headers_report",
                           "page_names_new", "page_names_report",
                           "media_unresolved", "spacer_images",
                           "output_check", "math_repaired",
                           "slide_titles_new", "reading_order_new", "slides_check")}
    if slides:
        return slides_run(base, decks, targets, project, paths, reports, args, first)

    work = tempfile.mkdtemp(prefix="convert-")
    try:
        collected = {key: os.path.join(work, key) for key in
                     ("captions_missing", "alt_missing", "spacers",
                      "media_unresolved", "bare_links", "captions_applied",
                      "math", "math_places", "math_kept", "title_numbers")}
        env = dict(os.environ)
        env.update({
            # For html-source.lua: a page's <title> that repeats the
            # book's name after its own loses it.
            "BOOK_TITLE": str(project.get("title") or ""),
            "TABLE_CAPTIONS_MISSING": collected["captions_missing"],
            "IMAGE_ALT_MISSING": collected["alt_missing"],
            "BARE_LINKS_FOUND": collected["bare_links"],
            "CAPTIONS_APPLIED": collected["captions_applied"],
            "SPACER_LOG": collected["spacers"],
            "MATH_REPAIRED": collected["math"],
            "MATH_PLACES": collected["math_places"],
            "MATH_KEPT": collected["math_kept"],
            "TITLE_NUMBERS": collected["title_numbers"],
            "MEDIA_UNRESOLVED": collected["media_unresolved"],
            "MEDIA_STRICT": "1" if first["media.strict"] else "",
        })

        docs = source_documents(base)

        # ---- 3. fragments, per target ----------------------------------------
        fragments = {}
        fragment_files = set()
        for target in targets:
            pair = []
            for key in ("header", "footer"):
                source = fragment_source(target[key], base, work,
                                         f"{target.name}-{key}")
                if source:
                    fragment_files.add(source)
                pair.append(render_fragment(
                    source, os.path.join(work, f"{target.name}-{key}.html")))
            fragments[target.name] = tuple(pair)

        # ---- 1. read ----------------------------------------------------------
        # Every file that becomes a page is found before any is read, so
        # two that would be one page stop the run before either is.
        markdown = markdown_sources(base, fragment_files)
        adoc, adoc_order, imagesdir, adoc_header = asciidoc_sources(base)
        output_dirs = [t.output_dir for t in targets]
        latex_main = latex_masters(base, skip=output_dirs)
        master = latex_main[0] if latex_main else None
        named = {page_name_of(n) for n in list(docs) + markdown + adoc}
        hand = hand_pages(base, named)
        web = html_sources(base, named, set(hand))
        check_page_names([docs, markdown, adoc, web,
                          [f"{PASSTHROUGH}/{h}.html" for h in hand]])
        stems = read_to_json(base, docs, env, work)
        stems += read_markdown_to_json(base, markdown, env)
        adoc_stems = read_asciidoc_to_json(base, adoc, env, imagesdir)
        resolve_asciidoc_xrefs(base, adoc_stems)
        stems += adoc_stems
        if adoc_order:
            BOOK_HINT.update(master_hint(
                adoc_order, adoc_header,
                contents_declared=bool(project.get("contents"))))
        latex_parts = []
        if master:
            tex_stems, tex_order, tex_header, latex_parts = read_latex_to_json(
                base, latex_main, env, work, declared_titles(project.get("contents")))
            # An .html file with the name of one of the book's pages is one
            # an earlier run wrote beside it, as html_sources takes one named
            # after a Word file; read, it would replace the page it came
            # from (FINC 308's cartridge's pages, which an unpacking that
            # stopped halfway left beside its masters).
            beside = [n for n in web if n[:-5] in tex_stems
                      or safe_stem(n[:-5]) in tex_stems]
            if beside:
                say(f"{len(beside)} .html file(s) here have the names of the "
                    "LaTeX book's pages (" + ", ".join(beside[:3])
                    + (", ..." if len(beside) > 3 else "") + "), so they're "
                    "taken as pages an earlier run wrote beside it, and not read.")
                web = [n for n in web if n not in beside]
            if web and not named:
                say(f"Reading {len(web)} .html file(s) as sources alongside "
                    f"the LaTeX book. A page finished by hand belongs in "
                    f"{PASSTHROUGH}/, which is copied as it stands.")
            check_page_names([docs, markdown, adoc, web,
                              [s + ".tex" for s in tex_stems]])
            fill_namerefs(base, tex_stems)
            resolve_asciidoc_xrefs(base, tex_stems, "LaTeX")
            stems += tex_stems
            BOOK_HINT.update(master_hint(
                tex_order, tex_header, "LaTeX", documents=len(latex_main) > 1,
                contents_declared=bool(project.get("contents"))))
        if BOOK_HINT.get("contents"):
            early_project_sample(base, project, targets, args.check_only)
        for target in targets:
            if web and target.format == "html" and os.path.abspath(
                    target.output_dir) == os.path.abspath(base):
                die(f"Target {target.name} writes its pages beside the "
                    "sources, which would overwrite the .html sources. Give "
                    "it an output_dir of its own.")
        html_stems = read_html_to_json(base, web, env, work)
        stems += html_stems

        # ---- 1.5 the header pre-pass -------------------------------------
        # On the .docx files themselves, because the evidence the guess
        # reads there -- repeat-header rows, bold, shading -- doesn't
        # survive Pandoc's reader; on an HTML source's intermediate, where
        # it does (a <th>, a <strong>). One run, so the book has one
        # report and one new-rows file. A sidecar row whose key matches no
        # table is warned about and set aside, with a sample sidecar
        # without it.
        # Text deleted with tracked changes vanishes on reading unless the
        # book says to keep it; say so, since nothing else would.
        if WORD_DELETIONS == "accept":
            import wordrepairs
            import zipfile
            with_deletions = []
            for name in docs:
                with zipfile.ZipFile(os.path.join(base, name)) as z:
                    if "word/document.xml" in z.namelist() and wordrepairs.count_deletions(
                            z.read("word/document.xml").decode("utf-8", "replace")):
                        with_deletions.append(name)
            if with_deletions:
                say(f"WARNING: {len(with_deletions)} Word file(s) have text deleted with tracked "
                    "changes, which won't appear: " + ", ".join(with_deletions[:5])
                    + (", ..." if len(with_deletions) > 5 else "")
                    + ". word.tracked_deletions: strike keeps it, struck through.")
        prepass = list(docs) + [os.path.join(base, s + ".json")
                                for s in list(html_stems) + (tex_stems if master else [])]
        if prepass:
            env["TABLE_HEADERS_RESOLVED"] = os.path.join(work,
                                                        "table-headers.json")
            run(["python3", HEADERS_TOOL] + prepass
                + ["--sidecar", paths["table_headers"],
                   "--new", reports["table_headers_new"],
                   "--report", reports["table_headers_report"],
                   "--resolved", env["TABLE_HEADERS_RESOLVED"],
                   "--resolved-html", os.path.join(work, "table-headers-html.json")], cwd=base)
        if not stems:
            import latexsource
            below = sorted(os.path.join(d, m) for d in os.listdir(base)
                           if os.path.isdir(os.path.join(base, d)) and not d.startswith(".")
                           and os.path.abspath(os.path.join(base, d)) not in
                           {os.path.abspath(o) for o in output_dirs}
                           for m in latexsource.masters(os.path.join(base, d)))
            die("No .docx, .md, .adoc, .html, or LaTeX files here, so there is "
                "nothing to convert."
                + (f" {len(below)} whole LaTeX document(s) are in a folder below: "
                   + ", ".join(below[:4]) + (", ..." if len(below) > 4 else "")
                   + ". latex.main can name them, by path or pattern "
                   f"({os.path.dirname(below[0])}/*.tex)." if below else ""))
        warn_about_leftovers(base, stems, fragment_files, web)

        # ---- 2. the gate ------------------------------------------------------
        media_gate(base, stems, collected["media_unresolved"],
                   reports["media_unresolved"],
                   safe=any(t.format not in SOURCE_TARGETS for t in targets))

        # Past the gate, this run will finish and the reports at the end
        # will be written with whatever is outstanding. Clear them now so
        # one left behind by an earlier run cannot survive into a run that
        # has nothing to report. Doing it here rather than at the top means
        # a run that stops at the gate leaves the previous reports intact.
        for key in ("table_captions_missing", "image_alt_missing",
                    "spacer_images", "math_repaired"):
            if os.path.exists(reports[key]):
                os.remove(reports[key])

        # ---- 4. filter and split, once per filter stage ---------------------
        css_header = os.path.join(work, "head.html")
        with open(css_header, "w", encoding="utf-8") as fh, \
                open(PAGE_CSS, encoding="utf-8") as css:
            fh.write("<style>\n" + css.read() + "</style>\n")
        pages_by_dir = {}
        for target in targets:
            if target.pages_dir in pages_by_dir:
                continue
            fenv = filter_env(target, base, paths, env)
            raw = read_variants(base, target, work, env)
            variant_stems = [s for s in raw if s not in stems]
            pages = filter_pages(base, stems + variant_stems, target, fenv,
                                 raw)
            if target["links.rewrite_publisher"]:
                rewrite_publisher_links(pages)
            pages_by_dir[target.pages_dir] = split_pages(target, pages,
                                                         paths, reports)

        if args.check_only:
            say("Check only: the reports are written; nothing was rendered "
                "or packaged.")
            return 0

        # ---- 4.6 hand-written pages ------------------------------------------
        hand = hand_pages(base, stems)
        if hand:
            say(f"{len(hand)} hand-written page(s): " + ", ".join(hand))
        for target in targets:
            if target.pages_dir in pages_by_dir and not any(
                    p.endswith(stem + INTERMEDIATE) for stem in hand
                    for p in pages_by_dir[target.pages_dir]):
                pages_by_dir[target.pages_dir] += read_hand_pages(
                    base, hand, target.pages_dir, env, target.variants)
        hand_stems = set(hand)

        # ---- 4.7 render, per html target --------------------------------------
        written = {}
        losses = []
        renv = dict(env, HEADER_INCLUDES_FILE=css_header)
        for target in targets:
            if target.format == "source":
                written[target.name] = remediate_sources(
                    target, base, docs, paths, env, html_stems,
                    language if LANGUAGE_DECLARED else None, work, markdown,
                    latex_parts, [t.output_dir for t in targets])
            if target.format in SOURCE_TARGETS or target.format == "docx":
                written[target.name] = render_markdown(
                    target, [p for p in pages_by_dir[target.pages_dir]
                             if os.path.basename(p)[:-len(INTERMEDIATE)]
                             not in hand_stems], base, work, project, renv,
                    losses)
            if target.format == "html":
                rendered = [p for p in pages_by_dir[target.pages_dir]
                            if os.path.basename(p)[:-len(INTERMEDIATE)]
                            not in hand_stems]
                written[target.name] = render_html(
                    target, rendered, base, fragments[target.name], language,
                    renv)
                written[target.name] += copy_hand_pages(
                    base, hand, target.output_dir, target.variants)
                tree, titles, api = book_tree(
                    project, pages_by_dir[target.pages_dir],
                    numbering_for(target, project))
                if numbering_for(target, project):
                    number_page_headings(target, tree, titles)
                written[target.name] += write_generated(
                    target, tree, titles, api, base, work,
                    fragments[target.name], language, renv)
                for path in arrange_notes(target, rendered, base, work,
                                          fragments[target.name], language,
                                          renv):
                    if path not in written[target.name]:
                        written[target.name].append(path)
                if target["menu"] == "on":
                    add_menu(target, tree, titles, written[target.name],
                             hand_stems, work)

        # ---- 5. reports, once per book ----------------------------------------
        missing = write_report(
            collected["captions_missing"], reports["table_captions_missing"],
            "Label,Description,Source,Excerpt,Drafted by,Reviewed",
            "table(s) needing a description", paths["table_captions"])
        write_report(
            collected["alt_missing"], reports["image_alt_missing"],
            "Image,Alt,Source,Reason,CurrentAlt,Drafted by,Reviewed",
            "image(s) needing alt text", paths["image_alt"],
            "Use [decorative] in the Alt column for images that carry no "
            "meaning.")
        write_bare_links(collected["bare_links"], reports["bare_links_new"],
                         paths["bare_links"])
        warn_math_keep(paths["math_keep"], collected["math_kept"])
        warn_unreviewed(paths)
        warn_title_numbers(collected["title_numbers"])
        write_report(collected["math"], reports["math_repaired"],
                     "Kind,Page,Before,After", "math repair(s)", None,
                     "Each is an equation's characters repaired, or math "
                     "typed as text made an equation; math.repair_equations "
                     "and math.from_text turn them off.")
        write_report(collected["spacers"], reports["spacer_images"],
                     "Image,Source,Width,Action", "spacer image(s) handled")
        labels = {row[0] for row in missing}
        if missing and len(labels) < len(missing):
            # The sidecar is keyed on the label alone, so one description
            # would be applied to every table sharing that label.
            say("Note: the same label appears in more than one document.")
            say("Only one description can apply per label; check the Source "
                "column.")

        # ---- 5.5 EPUBs, per epub3 target -------------------------------------
        epubs = []
        for target in targets:
            if target.format != "epub3":
                continue
            found = os.path.join(work, f"fidelity-{target.name}.tsv")
            if os.path.exists(found):
                os.remove(found)
            named, title = name_book_target(target, base,
                                            pages_by_dir[target.pages_dir])
            if not named:
                continue
            result = run(["python3", EPUB_TOOL, "-d", base,
                          "--target", target.name,
                          "--intermediates", target.pages_dir]
                         + (["--title", title] if title else []),
                         env=dict(os.environ, FIDELITY_FOUND=found),
                         capture=True, check=False)
            # Its own messages first: a failure's reason is in them.
            sys.stderr.write(result.stderr)
            if result.returncode:
                die(f"The EPUB for target {target.name} wasn't built.")
            epubs += [line for line in result.stdout.split("\n")
                      if line.strip()]
            # The EPUB is built from the whole book in one run, so its rows
            # name the item, not the page.
            collect_losses(found, target.name, "(book)", losses)
        # ---- 5.6 PDFs, per pdf target ----------------------------------------
        pdfs = []
        for target in targets:
            if target.format != "pdf":
                continue
            # A LaTeX book's own build titles its PDF as its \title does.
            own_build = master and str(target["pdf.from"]) == "book"
            named, title = (True, None) if own_build else name_book_target(
                target, base, pages_by_dir[target.pages_dir])
            if not named:
                continue
            if own_build:
                pdfs += latex_book_pdf(target, base, latex_parts, paths, work,
                                       language if LANGUAGE_DECLARED else None,
                                       project, targets)
                continue
            result = run(["python3", PDF_TOOL, "-d", base,
                          "--target", target.name,
                          "--intermediates", target.pages_dir]
                         + (["--title", title] if title else []),
                         env=pdf_env(), capture=True, check=False)
            sys.stderr.write(result.stderr)
            if result.returncode:
                die(f"The PDF for target {target.name} wasn't built.")
            pdfs += [line for line in result.stdout.split("\n")
                     if line.strip()]
        # ---- 5.65 LaTeX, per latex target: the PDF target's own LaTeX,
        # a master and a file per chapter, for an author to go on with.
        for target in targets:
            if target.format != "latex":
                continue
            named, title = name_book_target(target, base,
                                            pages_by_dir[target.pages_dir])
            if not named:
                continue
            result = run(["python3", PDF_TOOL, "-d", base, "--latex-target",
                          "--target", target.name,
                          "--intermediates", target.pages_dir]
                         + (["--title", title] if title else []),
                         env=pdf_env(), capture=True, check=False)
            sys.stderr.write(result.stderr)
            if result.returncode:
                die(f"The LaTeX for target {target.name} wasn't written.")
        # After the EPUBs, which report their losses as they're built.
        write_fidelity(losses, reports["fidelity"])

        # ---- 5.7 check, per target -------------------------------------------
        # Findings go to one report beside the others and never stop the
        # run: the output exists, and the list is what to work through.
        command = ["python3", CHECK_TOOL, "--report", reports["output_check"]] \
            + (["--quick"] if args.quick else [])
        for pages in written.values():
            command += [p for p in pages if p.endswith(".html")]
        for epub in epubs:
            command += ["--epub", epub]
        for pdf in pdfs:
            command += ["--pdf", pdf]
        if os.path.isfile(CHECK_TOOL):
            run(command, check=False)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    archive_targets(targets, base)

    # ---- 6. the cartridge --------------------------------------------------
    # Handed off to build-cartridge.py, which is read-only with respect to
    # page content and can be run on its own against any directory of
    # HTML. Arguments not recognized here are passed straight through, so
    # `--zip` builds the archive too. It reads its configuration here and
    # its pages from the first html target's directory; a package whose
    # includes name another html target is a roadmap item.
    unnamed = 1 if UNNAMED else 0
    html_targets = [t for t in targets if t.format == "html"]
    if not os.path.isfile(CARTRIDGE_TOOL) or not html_targets:
        say(f"No {CARTRIDGE_TOOL}, so skipping the manifest."
            if not os.path.isfile(CARTRIDGE_TOOL) else
            "No html target, so there is nothing for the packager to read; "
            "skipping the manifest.")
        # The packager writes project-sample.yaml; with none to run, this
        # run does, when a target needed the book's name (a master's order
        # was written as soon as it was read).
        unnamed_here = UNNAMED and not os.path.isfile(
            os.path.join(base, PROJECT_NAME)) and not oerconfig.inline_project(
                os.path.join(base, PACKAGING_NAME))
        if unnamed_here:
            contents = project.get("contents") or contents_from_tree(
                book_tree(project, pages_by_dir[targets[0].pages_dir])[0])
            path, used = write_project_sample(
                project, contents, hint_contents=not project.get("contents"))
            say(f"Wrote {path}" + (f", with {', '.join(used)} from "
                                   f"{BOOK_HINT.get('source')}" if used else "")
                + ". Edit it, rename it to project.yaml, and run again. The "
                "conversion settings have a sample of their own: python3 "
                f"{os.path.join(HERE, 'read-conversion-config.py')} -d . --init "
                "writes conversion-sample.yaml.")
        return unnamed
    # A book named in conversion.yaml alone, with nothing configuring
    # packaging, uses conversion alone: the manifest isn't asked for, so it
    # isn't an error that the packager couldn't name it. An argument meant
    # for the packager (--zip, --toc) asks for it.
    conversion_names = BOOK_HINT.get("project") or {}
    if (conversion_names.get("title") or conversion_names.get("identifier")) \
            and not passthrough and not os.path.isfile(os.path.join(base, PACKAGING_NAME)):
        say(f"No {PACKAGING_NAME} or {PROJECT_NAME}, and {CONFIG_NAME} names "
            "the book for conversion, so nothing is packaged. A "
            f"{PROJECT_NAME}, or a {PACKAGING_NAME} with a project: block, "
            "would build the cartridge.")
        return unnamed
    command = ["python3", CARTRIDGE_TOOL, "-d", base]
    if os.path.abspath(html_targets[0].output_dir) != os.path.abspath(base):
        command += ["--pages", html_targets[0].output_dir]
    # What the sources said about the book, for the packager's sample.
    hint = None
    if BOOK_HINT:
        handle, hint = tempfile.mkstemp(prefix="project-hint-", suffix=".json")
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            json.dump(BOOK_HINT, fh)
        command += ["--project-hint", hint]
    try:
        result = run(command + passthrough, check=False)
    finally:
        if hint:
            os.remove(hint)
    return result.returncode or unnamed


if __name__ == "__main__":
    sys.exit(main())
