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
    import docxtarget
    import htmlrepair
    import mathjax
    import notes as notes_lib
    import oerconfig
    from bookcontents import (guess_contents, walk_contents, number_tree,
                              is_generated, toc_blocks,
                              expand_split_sources, contents_from_tree)
    from names import safe_path, safe_stem, is_safe
except ImportError:
    sys.exit("Cannot find the configuration library. It should be in a "
             "lib/ directory beside bin/.")

FIGURE_FILTER = os.path.join(HERE, "figures-and-tables.lua")
MEDIA_FILTER = os.path.join(HERE, "media-extensions.lua")
HEADER_FILTER = os.path.join(HERE, "header-includes.lua")
SAFE_MEDIA_FILTER = os.path.join(HERE, "safe-media.lua")
NOT_YET_IMPLEMENTED = ("pdf",)
# Targets whose output is written to be a source again: what the author
# decided, and not what the filter derived from it.
SOURCE_TARGETS = ("markdown", "asciidoc")
TARGET_FILTER = os.path.join(HERE, "target-blocks.lua")
MARKDOWN_FILTER = os.path.join(HERE, "markdown-source.lua")
MARKDOWN_HTML_FILTER = os.path.join(HERE, "markdown-html.lua")
HTML_SOURCE_FILTER = os.path.join(HERE, "html-source.lua")
HTML_RAW_FILTER = os.path.join(HERE, "html-raw.lua")
ASCIIDOC_FILTER = os.path.join(HERE, "asciidoc-source.lua")
INCLUDE = re.compile(r"^include::([^\[\s]+\.(?:adoc|asciidoc|asc))\[", re.M)
SOURCE_EXTENSIONS = (".docx", ".md", ".html", ".adoc", ".asciidoc")
PAGE_CSS = os.path.join(HERE, "page.css")
HEADERS_TOOL = os.path.join(HERE, "table-headers.py")
SPLIT_TOOL = os.path.join(HERE, "split-pages.py")
EPUB_TOOL = os.path.join(HERE, "build-epub.py")
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


def extract_zip(path, work):
    """A plain zip's files, written into work. Folders that wrap everything
    ("My Book/...") are dropped, so the sources sit at the top where
    convert.py finds them; macOS's __MACOSX and .DS_Store are left out; and
    an entry that would land outside the book -- an absolute path, or one
    with .. in it -- is refused rather than written. Returns the report's
    rows."""
    import zipfile
    notes, entries = [], []
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            parts = [p for p in name.split("/") if p not in ("", ".")]
            if name.startswith("__MACOSX/") or (parts and parts[-1] in (
                    ".DS_Store", "Thumbs.db", "desktop.ini")):
                continue
            if (name.startswith("/") or re.match(r"^[A-Za-z]:", name)
                    or ".." in parts):
                notes.append((info.filename, "unsafe-path",
                              "would land outside the book; not extracted"))
                continue
            if info.is_dir() or not parts:
                continue
            entries.append((info, parts))
        strip = 0
        while entries and all(len(parts) > strip + 1 for _, parts in entries) \
                and len({parts[strip] for _, parts in entries}) == 1:
            strip += 1
        for info, parts in entries:
            dest = os.path.join(work, *parts[strip:])
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with archive.open(info) as source, open(dest, "wb") as out:
                shutil.copyfileobj(source, out)
    return notes


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


def unpack_archives(base, check_only=False, linked_documents=False):
    """A web archive -- a WARC, compressed or not, or a WACZ, recognized
    by its first bytes -- or a Common Cartridge, recognized by its
    manifest, or a plain .zip of a book's files, in a directory with no
    sources is unpacked there first, as unpack-site.py or
    unpack-cartridge.py would or by extracting the zip, and its sources
    are then converted. From then on they're the book: they're where
    corrections are made, so a later run, finding sources, never reads the
    archive again. A project.yaml or conversion.yaml already here is kept,
    and the archive's is written beside it (project-unpacked.yaml). For an
    unpacker's own options (a profile, whole pages), run it yourself. A
    plain zip is known by its name, since Word files, slide decks, EPUBs,
    and cartridges are zips too."""
    import sitesource
    import cartridgesource
    skip = SOURCE_EXTENSIONS + (".yaml", ".yml", ".csv", ".json", ".css",
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
    unused = ("--linked-documents applies when a run unpacks a cartridge, "
              "and this one doesn't: ")
    if not archives and not cartridges and not zips:
        if linked_documents:
            say(unused + "there's no cartridge here.")
        return
    # A directory with sources is a book already: nothing in it is read,
    # however many archives sit there (a cartridge --zip built, say, beside
    # the download it came from).
    if any(p.lower().endswith(SOURCE_EXTENSIONS)
           for p in glob.glob(os.path.join(base, "*"))):
        found = cartridges + zips + archives
        say(", ".join(os.path.basename(p) for p in found)
            + ": not read, since this directory has sources, which are the "
            "book once an archive is unpacked. To unpack "
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
            + "); a book comes from one cartridge or zip, or from web "
            "archives. Unpack them into directories of their own.")
    tool = ("unpack-cartridge.py" if cartridges else
            "zip" if zips else "unpack-site.py")
    archives = cartridges or zips or archives
    if linked_documents and tool != "unpack-cartridge.py":
        say(unused + ("a zip's files are the book as they are." if zips
                      else "a web archive's pages keep their links to files."))
    names = ", ".join(os.path.basename(p) for p in archives)
    if any(p.lower().endswith(SOURCE_EXTENSIONS)
           for p in glob.glob(os.path.join(base, "*"))):
        say(f"{names}: not read, since this directory has sources, which "
            "are the book once an archive is unpacked. To unpack it afresh, "
            + ("extract it into a new directory." if tool == "zip" else
               f"use {tool} into a new directory."))
        if linked_documents:
            say(unused + "the pages here are the book already, and "
                "unpacking again into a new directory is how to change that.")
        return
    if check_only:
        say(f"{names} would be unpacked here and its pages converted.")
        return
    work = tempfile.mkdtemp(prefix=".unpacking-", dir=base)
    try:
        if tool == "zip":
            notes = extract_zip(archives[0], work)
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
            if not any(n.lower().endswith(SOURCE_EXTENSIONS) for n in held):
                inside = [n for n in held if n.lower().endswith(
                    (".imscc", ".warc", ".gz", ".wacz", ".epub", ".zip"))]
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
        for name in sorted(os.listdir(work)):
            target = os.path.join(base, name)
            if name in kept and os.path.exists(target):
                target = os.path.join(base, kept[name])
                say(f"{name} was already here and is kept; the archive's is "
                    f"{kept[name]}.")
            if os.path.exists(target):
                die(f"{name} is already here; unpacking {names} would "
                    "overwrite it. Unpack it into a new directory instead.")
            shutil.move(os.path.join(work, name), target)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    sources = sum(1 for p in glob.glob(os.path.join(base, "*"))
                  if p.lower().endswith(SOURCE_EXTENSIONS))
    say(f"Unpacked {names}: {sources} source(s), which are the book from now "
        "on. Correct them, not the archive: later runs don't read it again."
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


def load_targets(base, allow_unknown):
    """Every conversion target, resolved, plus the project block."""
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
    # pdf and docx are names the schema reserves for outputs not built
    # yet. A target naming one is skipped, and said to be, rather than
    # read, filtered, and then quietly never written.
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
        run(["pandoc", "-f", "asciidoc", "-t", "json", name,
             "-o", stem + ".json", "--lua-filter=" + MARKDOWN_HTML_FILTER,
             "--lua-filter=" + ASCIIDOC_FILTER,
             "--lua-filter=" + MEDIA_FILTER], env=env, cwd=base)
        portable_media_paths(os.path.join(base, stem + ".json"), base, name)
        stems.append(stem)
    return stems


def resolve_asciidoc_xrefs(base, stems):
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
        say(f"{resolved} AsciiDoc cross-reference(s) resolved to the "
            "section or id they name.")
    return resolved


def write_order_sample(order, header=None):
    """What a master AsciiDoc file says about the book, in the shape
    project.yaml takes: its title, authors, and language, and as
    contents the order it includes its chapters in. Not applied: the
    project is the author's, and a run with none declared goes on as it
    always has (an EPUB called "Untitled") until it is."""
    import yaml
    stems = [safe_stem(os.path.splitext(n)[0]) for n in order]
    project = dict(header or {})
    project["contents"] = stems
    with open(CONTENTS_SAMPLE, "w", encoding="utf-8") as fh:
        fh.write("# Written by convert.py from the master AsciiDoc file: the "
                 "book's title,\n# authors, and language, and the order it "
                 "includes its chapters in.\n# Copy them into project.yaml "
                 "to use them.\n" + yaml.safe_dump(
                     {"project": project}, sort_keys=False,
                     allow_unicode=True))
    say(f"No contents declared: {CONTENTS_SAMPLE} holds the order the "
        "master file gives" + (", and its title and authors" if header
                               else "") + ". Copy it into project.yaml to "
        "use it.")


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
        moved = docxrepair.repaired_copy(os.path.join(base, name), repaired)
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
        # A term with no definition, which the reader reads as a Div.
        docxrepair.apply_definition_terms(os.path.join(base, stem + ".json"))
        # Ids Pandoc's writer hashed, named again from the file's own map.
        docxrepair.apply_id_map(repaired, os.path.join(base, stem + ".json"))
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
            docxrepair.repaired_copy(path, repaired)
            run(["pandoc", "-f", "docx", "-t", "json", repaired, "-o", out,
                 "--lua-filter=" + MEDIA_FILTER, "--extract-media=" + stem],
                env=env, cwd=base)
            docxrepair.apply_screentips(repaired, os.path.join(base, out)
                                        if not os.path.isabs(out) else out)
            docxrepair.apply_decorative(repaired, os.path.join(base, out)
                                        if not os.path.isabs(out) else out)
            docxrepair.apply_definition_terms(os.path.join(base, out)
                                              if not os.path.isabs(out) else out)
            docxrepair.apply_id_map(repaired, os.path.join(base, out)
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
             "--lua-filter=" + FIGURE_FILTER], env=env, cwd=base)
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


def render_markdown(target, pages, base, work, project, env, losses=None):
    """Markdown or AsciiDoc files as source: what the author decided, in
    Pandoc's own flavor of each, and nothing the filter derived. Or Word
    files, from the same intermediates, finished by docxtarget. One file
    per page, or with merge: groups, one per top-level entry of the book's
    contents, each page a section under it."""
    env = dict(env, TARGET_NAME=target.name)
    os.makedirs(target.output_dir, exist_ok=True)
    jobs = [(os.path.basename(p)[:-len(INTERMEDIATE)], p) for p in pages]
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
            run(["pandoc", "-f", "json", "-t", "docx", page, "-o", out,
                 "--lua-filter=" + TARGET_FILTER], env=env, cwd=base)
            for key, n in docxtarget.finish(out, page).items():
                added[key] = added.get(key, 0) + n
            written.append(out)
            continue
        if asciidoc:
            # Pandoc's modern AsciiDoc, as Asciidoctor reads it. What its
            # reader can't read back (a row span, raw HTML, an anchor as
            # it writes one) the filter writes as AsciiDoc it can; see
            # markdown-source.lua.
            run(["pandoc", "-f", "json", "-t", "asciidoc", page, "-o", out,
                 "--standalone", "--wrap=none",
                 "--lua-filter=" + TARGET_FILTER,
                 "--lua-filter=" + MARKDOWN_FILTER], env=env, cwd=base)
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
        run(["pandoc", "-f", "json",
             "-t", "markdown-simple_tables-multiline_tables-raw_html",
             page, "-o", out,
             "--standalone", "--wrap=none", "--markdown-headings=atx",
             "--lua-filter=" + TARGET_FILTER,
             "--lua-filter=" + MARKDOWN_FILTER], env=env, cwd=base)
        written.append(out)
    if word:
        say(f"{target.name}: {len(written)} Word file(s), compatibility mode "
            f"15; {added['tooltips']} ScreenTip(s), {added['decorative']} "
            f"decorative image(s) marked, {added['first_columns']} header "
            "column(s) flagged.")
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
            new = re.sub(r"(<title>)(" + re.escape(title) + r")(</title>)",
                         lambda m: m.group(1) + number + " " + m.group(2)
                         + m.group(3), new, count=1)
            new = re.sub(r'(<h1 class="title"[^>]*>)(' + re.escape(title)
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
               TITLE_BLOCK=str(target["title_block"]))
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


def meta_text(meta, key):
    value = meta.get(key)
    if not value:
        return ""
    if value.get("t") == "MetaString":
        return value["c"]
    return " ".join("".join(i.get("c", " ") if i["t"] == "Str" else " "
                            for i in value.get("c", [])).split())


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
    if project.get("numbering") if numbered is None else numbered:
        number_tree(tree, titles)
    return tree, titles, api


CONTENTS_SAMPLE = "contents-sample.yaml"


def write_contents_sample(project, tree):
    """contents names a page the split cut, so it stood for its pieces.
    What it resolved to is written out, in the shape project.yaml takes,
    for anyone who means to arrange the pieces themselves: copied into
    project.yaml, it names every piece, and a declared piece is left as
    declared. Written once per run, and only when it would differ from
    what project.yaml says; the run's own output never reads it."""
    global CONTENTS_SAMPLE_WRITTEN
    if CONTENTS_SAMPLE_WRITTEN:
        return
    CONTENTS_SAMPLE_WRITTEN = True
    import yaml
    sample = contents_from_tree(tree)
    path = os.path.join(os.getcwd(), CONTENTS_SAMPLE)
    body = yaml.safe_dump({"project": {"contents": sample}},
                          sort_keys=False, allow_unicode=True, width=1000)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# Written by convert.py: project.yaml's contents names a "
                 "page the split cut,\n# so the page stood for its pieces. "
                 "This is what it resolved to. Copy\n# the contents into "
                 "project.yaml to arrange the pieces yourself.\n" + body)
    say(f"contents names a page the split cut; {CONTENTS_SAMPLE} lists "
        "its pieces, to copy into project.yaml if you mean to arrange them.")


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
        target = re.split(r"[#?]", ref, 1)[0]
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
        with open(rows_file, encoding="utf-8") as fh:
            rows = sorted({line.rstrip("\n") for line in fh
                           if line.strip()})
    if not rows:
        if os.path.exists(report):
            os.remove(report)
        return rows
    with open(report, "w", encoding="utf-8") as fh:
        fh.write(header + "\n" + "\n".join(rows) + "\n")
    say(f"Wrote {report} ({len(rows)} {noun}).")
    if sidecar:
        say(f"Fill in the second column, then append the rows to {sidecar}.")
    if hint:
        say(hint)
    return rows


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
            w.writerow([target, page, kind, detail, docxtarget.LOSSES[kind]])
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
            w.writerow(["URL", "Replacement", "Title", "Source", "Context"])
            for url in sorted(new):
                e = new[url]
                w.writerow([url, "", e["title"], "; ".join(e["sources"]),
                            e["context"]])
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
    args, passthrough = parser.parse_known_args()
    TRACE = not args.quiet
    base = os.getcwd()

    for required in (FIGURE_FILTER, MEDIA_FILTER, HEADER_FILTER, PAGE_CSS):
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
    targets, project = load_targets(base, args.allow_unknown_keys)
    global PASSTHROUGH
    PASSTHROUGH = str(project.get("passthrough", "_pt") or "").strip("/")
    for target in targets:
        target.variants = variant_sources(base, target.name)
    language = project["language"]
    first = targets[0]        # sidecars and reports are book-level settings

    paths = {key: resolve_path(base, first[f"sidecars.{key}"])
             for key in ("table_captions", "image_alt", "table_headers",
                         "page_names", "bare_links")}
    for key, default in (("table_captions", "table-captions.csv"),
                         ("image_alt", "image-alt.csv"),
                         ("bare_links", "bare-links.csv"),
                         ("table_headers", "table-headers.csv"),
                         ("page_names", "page-names.csv")):
        check_sidecar(paths[key], f"sidecars.{key}", default, base)
    reports = {key: resolve_path(base, first[f"reports.{key}"])
               for key in ("table_captions_missing", "image_alt_missing",
                           "bare_links_new", "fidelity",
                           "table_headers_new", "table_headers_report",
                           "page_names_new", "page_names_report",
                           "media_unresolved", "spacer_images",
                           "output_check")}

    work = tempfile.mkdtemp(prefix="convert-")
    try:
        collected = {key: os.path.join(work, key) for key in
                     ("captions_missing", "alt_missing", "spacers",
                      "media_unresolved", "bare_links")}
        env = dict(os.environ)
        env.update({
            # For html-source.lua: a page's <title> that repeats the
            # book's name after its own loses it.
            "BOOK_TITLE": str(project.get("title") or ""),
            "TABLE_CAPTIONS_MISSING": collected["captions_missing"],
            "IMAGE_ALT_MISSING": collected["alt_missing"],
            "BARE_LINKS_FOUND": collected["bare_links"],
            "SPACER_LOG": collected["spacers"],
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
        if adoc_order and not project.get("contents"):
            write_order_sample(adoc_order, adoc_header)
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
        prepass = list(docs) + [os.path.join(base, s + ".json")
                                for s in html_stems]
        if prepass:
            env["TABLE_HEADERS_RESOLVED"] = os.path.join(work,
                                                        "table-headers.json")
            run(["python3", HEADERS_TOOL] + prepass
                + ["--sidecar", paths["table_headers"],
                   "--new", reports["table_headers_new"],
                   "--report", reports["table_headers_report"],
                   "--resolved", env["TABLE_HEADERS_RESOLVED"]], cwd=base)
        if not stems:
            die("No .docx, .md, .adoc, or .html files here, so there is "
                "nothing to convert.")
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
                    "spacer_images"):
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
        write_fidelity(losses, reports["fidelity"])
        missing = write_report(
            collected["captions_missing"], reports["table_captions_missing"],
            "Label,Description,Source,Excerpt",
            "table(s) needing a description", paths["table_captions"])
        write_report(
            collected["alt_missing"], reports["image_alt_missing"],
            "Image,Alt,Source,Reason,CurrentAlt",
            "image(s) needing alt text", paths["image_alt"],
            "Use [decorative] in the Alt column for images that carry no "
            "meaning.")
        write_bare_links(collected["bare_links"], reports["bare_links_new"],
                         paths["bare_links"])
        write_report(collected["spacers"], reports["spacer_images"],
                     "Image,Source,Width,Action", "spacer image(s) handled")
        labels = {row.split(",")[0] for row in missing}
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
            result = run(["python3", EPUB_TOOL, "-d", base,
                          "--target", target.name,
                          "--intermediates", target.pages_dir],
                         capture=True)
            sys.stderr.write(result.stderr)
            epubs += [line for line in result.stdout.split("\n")
                      if line.strip()]

        # ---- 5.7 check, per target -------------------------------------------
        # Findings go to one report beside the others and never stop the
        # run: the output exists, and the list is what to work through.
        command = ["python3", CHECK_TOOL, "--report", reports["output_check"]]
        for pages in written.values():
            command += [p for p in pages if p.endswith(".html")]
        for epub in epubs:
            command += ["--epub", epub]
        if os.path.isfile(CHECK_TOOL):
            run(command, check=False)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    # ---- 6. the cartridge --------------------------------------------------
    # Handed off to build-cartridge.py, which is read-only with respect to
    # page content and can be run on its own against any directory of
    # HTML. Arguments not recognized here are passed straight through, so
    # `--zip` builds the archive too. It reads its configuration here and
    # its pages from the first html target's directory; a package whose
    # includes name another html target is a roadmap item.
    if not os.path.isfile(CARTRIDGE_TOOL):
        say(f"No {CARTRIDGE_TOOL}, so skipping the manifest.")
        return 0
    html_targets = [t for t in targets if t.format == "html"]
    if not html_targets:
        say("No html target, so there is nothing for the packager to read; "
            "skipping the manifest.")
        return 0
    command = ["python3", CARTRIDGE_TOOL, "-d", base]
    if os.path.abspath(html_targets[0].output_dir) != os.path.abspath(base):
        command += ["--pages", html_targets[0].output_dir]
    result = run(command + passthrough, check=False)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
