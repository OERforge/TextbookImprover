#!/usr/bin/env python3
"""
stamps -- what a target is built from, as five digests, so that a run can
tell whether a target needs building again by what it's made of, not by
the time a file was saved.

    import stamps
    stamp = stamps.Stamp(
        settings=stamps.settings_digest(schema, resolved, root, "epub3"),
        sources=stamps.tree_digest(os.path.join(root, "src", "book")),
        top=stamps.top_digest(root, "book", named_files),
        software=stamps.software_digest(stamps.software("epub3")),
        options=stamps.options_digest({"--toc": outline}))
    old = stamps.read_stamp(path)
    if old is None or stamps.changed(old, stamp):
        ...build, then...
        stamps.write_stamp(path, stamp)

Nothing calls this yet. It's for the project layout to come, where each
part's sources are in src/<part>/, its sidecars in sidecars/<part>/, and a
target is built beside its folder and swapped in: a run will build a
target only when one of its five digests has changed, and say which.

THE FIVE

  settings  the target's settings as resolved, project-wide and its own,
            less every format section but its own, each path relative to
            the project; and SOURCE_DATE_EPOCH, which isn't a setting but
            changes the dates inside an output.
  sources   every file under the part's folder, by its path there and its
            bytes, but for what SKIPPED says isn't the author's.
  top       what the target reads outside src/: the three settings files,
            the part's sidecars, and each file a setting names.
  software  TextbookImprover's own code, Pandoc, and, where a target uses
            them (a PDF, and every target of a LaTeX book), TeX, the
            drawing and PDF programs, LibreOffice, and the Python packages
            that write output.
  options   the command-line options that change an output.

Each is kept apart, so a run can say which changed, and the stamp is a
digest of the five. By content throughout: copying a project, or checking
it out again, changes no file's bytes, so it rebuilds nothing.

WHY NOT .gitignore

A book that ignores *.pdf while keeping PDF figures in Git would lose
them from the stamp. An author's .aux costs an unneeded rebuild, which is
safe; a missed input gives a wrong result, which isn't.

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

import hashlib
import json
import os
import shutil
import subprocess
import sys

import oerconfig

# The five, in the order a stamp sums them and a run names them.
PARTS = ("settings", "sources", "top", "software", "options")

# The sections of the conversion schema that belong to one format, and the
# sections each format reads. A format not named here keeps every one,
# which can only cost a rebuild. A deck's page, PDF, PowerPoint file, and
# presentation read slides.*, and a latex target writes what a pdf target
# builds from.
FORMAT_SECTIONS = ("html", "docx", "epub", "pdf", "slides")
OWN_SECTIONS = {
    "html": ("html", "slides"),
    "epub3": ("epub",),
    "docx": ("docx",),
    "pdf": ("pdf", "slides"),
    "latex": ("pdf",),
    "pptx": ("slides",),
    "revealjs": ("slides",),
}

# What isn't the author's in a part's folder: an editor's backup
# (name~), Emacs's autosave (#name#), Windows' thumbnails and folder
# settings, and the Zone.Identifier stream Windows leaves beside a file
# saved into WSL (name:Zone.Identifier). A dot file or dot folder is left
# out too unless it's allowed, so reading and the stamp can't disagree.
SKIPPED_NAMES = ("Thumbs.db", "desktop.ini")

# Programs whose versions a target's output depends on, by format: every
# format's pages may hold a drawing rsvg-convert made, and a deck in
# another format is saved as PowerPoint by LibreOffice. A PDF's build runs
# LuaTeX, pdftocairo, and Ghostscript (and through it epstopdf). So does
# every target of a LaTeX book, a page or an EPUB too: its drawings are
# set by pdfLaTeX or LuaLaTeX with the book's preamble and made pictures
# by pdftocairo, whatever the target (lib/latexsource.py's render).
COMMON_TOOLS = ("pandoc", "rsvg-convert", "libreoffice")
TEX_TOOLS = ("luatex", "pdftex", "texlive", "pdftocairo", "gs")
TEX_FORMATS = ("pdf", "latex")

# The Python packages that write output, by their distributions' names.
PACKAGES = ("python-docx", "python-pptx", "pikepdf", "pypdf", "lxml", "Pillow", "PyYAML")

# What each program is asked, and where it answers; Pandoc is asked as
# lib/pandocrun.py asks it, as every Pandoc a script starts is.
VERSION_COMMANDS = {
    "rsvg-convert": ["rsvg-convert", "--version"],
    "libreoffice": ["libreoffice", "--version"],
    "luatex": ["luatex", "--version"],
    "pdftex": ["pdftex", "--version"],
    "pdftocairo": ["pdftocairo", "-v"],
    "gs": ["gs", "--version"],
}

# The folders TextbookImprover's own digest is made from.
OWN_FOLDERS = ("bin", "lib", "vendor")

CHUNK = 1 << 20


# --------------------------------------------------------------------------
# hashing
# --------------------------------------------------------------------------

def file_digest(path):
    """The SHA-256 of a file's bytes, as hex."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def text_digest(value):
    """The SHA-256 of a value written as JSON with its keys sorted, so a
    mapping's order changes nothing."""
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def skipped(name, is_folder=False, allow=()):
    """Whether a file or folder of this name is left out of a part's
    sources: a dot name not in allow, a backup, an autosave, or one of
    Windows' own."""
    if name.startswith(".") and name not in allow:
        return True
    if is_folder:
        return False
    return (name.endswith("~") or (len(name) > 2 and name.startswith("#") and name.endswith("#"))
            or name in SKIPPED_NAMES or name.endswith(":Zone.Identifier"))


def tree_entries(folder, allow=()):
    """Each file under folder that the stamp counts, as [path, digest], its
    path relative to folder with / between the names, sorted. A link is
    counted by where it points and, for a file, by the bytes there too; a
    link to a folder isn't followed, since the read checks stop a link
    that leads outside the project and one inside is counted where it
    leads."""
    entries = []
    if not os.path.isdir(folder):
        return entries
    for here, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not skipped(d, True, allow))
        for name in sorted(names) + [d for d in dirs if os.path.islink(os.path.join(here, d))]:
            path = os.path.join(here, name)
            if os.path.isdir(path) and not os.path.islink(path):
                continue
            if skipped(name, False, allow):
                continue
            relative = os.path.relpath(path, folder).replace(os.sep, "/")
            if os.path.islink(path):
                target = os.readlink(path)
                content = file_digest(path) if os.path.isfile(path) else ""
                entries.append([relative, "link:" + target + ":" + content])
            else:
                entries.append([relative, file_digest(path)])
        # A linked folder is counted above, as a link, and not walked.
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(here, d))]
    entries.sort()
    return entries


def tree_digest(folder, allow=()):
    """The digest of a part's sources: every file tree_entries counts."""
    return text_digest(tree_entries(folder, allow))


# --------------------------------------------------------------------------
# the five
# --------------------------------------------------------------------------

def _relative(value, root):
    """A path setting's value as the stamp keeps it: relative to the
    project where it's inside it, so a project copied elsewhere has the
    same stamp."""
    if not isinstance(value, str) or not value:
        return value
    if os.path.isabs(value):
        real = os.path.normpath(value)
        top = os.path.normpath(root)
        if real == top or real.startswith(top + os.sep):
            return os.path.relpath(real, top).replace(os.sep, "/")
        return real
    return os.path.normpath(value).replace(os.sep, "/")


def _paths_relative(node, values, root):
    """values with every path setting the schema node declares relative to
    root."""
    out = {}
    for name, value in (values or {}).items():
        child = node.keys.get(name) if node is not None and node.keys else None
        if child is not None and child.is_section and isinstance(value, dict):
            out[name] = _paths_relative(child, value, root)
        elif child is not None and child.type == "path":
            out[name] = _relative(value, root)
        elif child is not None and child.type == "list" and child.item == "path" \
                and isinstance(value, list):
            out[name] = [_relative(v, root) for v in value]
        else:
            out[name] = value
    return out


def own_sections(fmt):
    """The format sections a target of this format reads."""
    return OWN_SECTIONS.get(fmt, FORMAT_SECTIONS)


def settings_values(schema, project_schema, resolved, root, fmt, epoch=None, extra=None):
    """What the settings digest is made of: the project's settings and the
    target's, less the format sections it doesn't read, paths relative to
    root; SOURCE_DATE_EPOCH (the environment's unless given); and extra,
    any value a run takes from the environment or the command line in
    place of a setting's."""
    keep = own_sections(fmt)
    settings = {k: v for k, v in resolved.settings.items()
                if k not in FORMAT_SECTIONS or k in keep}
    if epoch is None:
        epoch = os.environ.get("SOURCE_DATE_EPOCH", "")
    return {
        "project": _paths_relative(project_schema.root, resolved.project, root),
        "settings": _paths_relative(schema.root, settings, root),
        "SOURCE_DATE_EPOCH": str(epoch),
        "extra": extra or {},
    }


def settings_digest(schema, project_schema, resolved, root, fmt, epoch=None, extra=None):
    """The digest of a target's settings (settings_values)."""
    return text_digest(settings_values(schema, project_schema, resolved, root, fmt,
                                       epoch, extra))


SETTINGS_FILES = ("project.yaml", "conversion.yaml", "packaging.yaml")


def top_entries(root, part, named=()):
    """What a target reads outside its part's sources, as [path, digest]:
    the settings files, the part's sidecars, and each file named (by a
    setting, resolved), each path relative to root. A file that isn't
    there is counted as missing, so making it is a change."""
    entries = []
    for name in SETTINGS_FILES:
        path = os.path.join(root, name)
        entries.append([name, file_digest(path) if os.path.isfile(path) else "missing"])
    sidecars = os.path.join(root, "sidecars", part)
    entries += [["sidecars/" + part + "/" + path, digest]
                for path, digest in tree_entries(sidecars)]
    for path in sorted(set(named)):
        full = path if os.path.isabs(path) else os.path.join(root, path)
        key = _relative(os.path.abspath(full), root)
        entries.append([key, file_digest(full) if os.path.isfile(full) else "missing"])
    return entries


def top_digest(root, part, named=()):
    """The digest of what a target reads at the project's top."""
    return text_digest(top_entries(root, part, named))


def software(fmt, latex_book=False):
    """The programs a target of this format depends on; latex_book for a
    target of a LaTeX book, whose drawings TeX and pdftocairo make for
    every format."""
    return COMMON_TOOLS + (TEX_TOOLS if fmt in TEX_FORMATS or latex_book else ())


_VERSIONS = {}


def tool_version(name):
    """What a program says its version is, the first line it writes, or
    "absent" when it isn't installed; texlive is a digest of TeX Live's
    package database where there is one (TinyTeX and TeX Live from tug.org
    have it, Debian's and Ubuntu's texlive packages don't). Asked once a
    run."""
    if name in _VERSIONS:
        return _VERSIONS[name]
    if name == "texlive":
        answer = "absent"
        kpsewhich = shutil.which("kpsewhich")
        if kpsewhich:
            done = subprocess.run([kpsewhich, "-var-value=SELFAUTOPARENT"],
                                  capture_output=True, text=True, stdin=subprocess.DEVNULL)
            database = os.path.join(done.stdout.strip(), "tlpkg", "texlive.tlpdb")
            answer = file_digest(database) if done.stdout.strip() and \
                os.path.isfile(database) else "no tlpdb"
    else:
        if name == "pandoc":
            import pandocrun
            command = pandocrun.VERSION
        else:
            command = VERSION_COMMANDS[name]
        if not shutil.which(command[0]):
            answer = "absent"
        else:
            try:
                done = subprocess.run(command, capture_output=True, text=True,
                                      stdin=subprocess.DEVNULL, timeout=60)
                text = (done.stdout.strip() or done.stderr.strip()).splitlines()
                answer = text[0].strip() if text else "no answer"
            except (OSError, subprocess.TimeoutExpired):
                answer = "no answer"
    _VERSIONS[name] = answer
    return answer


def package_versions(packages=PACKAGES):
    """Each Python package's version, or "absent"."""
    try:
        from importlib import metadata
    except ImportError:                      # Python before 3.8
        metadata = None
    out = {}
    for name in packages:
        try:
            out[name] = metadata.version(name) if metadata else "unknown"
        except Exception:
            out[name] = "absent"
    return out


_OWN = {}


def own_digest(root=None):
    """TextbookImprover's own digest: the sorted paths and contents of
    bin/, lib/, and vendor/, never a __pycache__ or a .pyc. Made from the
    files, so a release archive, with no Git, gives the same as its
    checkout."""
    root = root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root in _OWN:
        return _OWN[root]
    entries = []
    for folder in OWN_FOLDERS:
        top = os.path.join(root, folder)
        for here, dirs, names in os.walk(top):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            for name in sorted(names):
                if name.endswith((".pyc", ".pyo")):
                    continue
                path = os.path.join(here, name)
                if os.path.isfile(path):
                    entries.append([os.path.relpath(path, root).replace(os.sep, "/"),
                                    file_digest(path)])
    _OWN[root] = text_digest(sorted(entries))
    return _OWN[root]


def software_values(tools, packages=PACKAGES, root=None):
    """What the software digest is made of."""
    return {
        "textbookimprover": own_digest(root),
        "tools": {name: tool_version(name) for name in tools},
        "packages": package_versions(packages),
        "python": sys.version.split()[0],
    }


def software_digest(tools, packages=PACKAGES, root=None):
    """The digest of the software a target is built with."""
    return text_digest(software_values(tools, packages, root))


def options_digest(options):
    """The digest of the command-line options that change an output, a
    mapping of each to its value (--toc to its outline's digest, say)."""
    return text_digest(options or {})


# --------------------------------------------------------------------------
# an outline, for a package's --toc
# --------------------------------------------------------------------------

def outline_digest(entries):
    """The digest of a book's outline, each entry its level and its title,
    as build-cartridge.py's pdf_outline and epub_outline give them: a PDF
    rebuilt with the same bookmarks has the same one."""
    return text_digest([[int(level), str(title)] for level, title in entries])


class OutlineCache:
    """Each file's outline digest, kept with the file's own digest, so an
    outline is read again only when the file's bytes change. Reading one
    took 0.08 s for a 1,200-page PDF of 980 bookmarks and 0.4 s for a
    346-page tagged PDF of 7.5 MB, with pypdf 6.17.0 (measured
    2026-11-18); hashing the file is quicker."""

    def __init__(self, path):
        self.path = path
        try:
            with open(path, encoding="utf-8") as fh:
                self.known = json.load(fh)
            if not isinstance(self.known, dict):
                self.known = {}
        except (OSError, ValueError):
            self.known = {}

    def digest(self, path, reader):
        """The outline digest of the file at path, reader(path) giving its
        entries when they aren't known for its bytes."""
        key = os.path.abspath(path)
        content = file_digest(path)
        known = self.known.get(key)
        if isinstance(known, dict) and known.get("file") == content:
            return known["outline"]
        outline = outline_digest(reader(path))
        self.known[key] = {"file": content, "outline": outline}
        _write_json(self.path, self.known)
        return outline


# --------------------------------------------------------------------------
# a stamp
# --------------------------------------------------------------------------

class Stamp:
    """The five digests of what a target is built from, and their sum."""

    def __init__(self, settings, sources, top, software, options):
        self.parts = {"settings": settings, "sources": sources, "top": top,
                      "software": software, "options": options}

    @property
    def digest(self):
        text = "".join(f"{name}={self.parts[name]}\n" for name in PARTS)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def as_dict(self):
        return dict(self.parts, stamp=self.digest)

    @classmethod
    def from_dict(cls, values):
        return cls(*(str(values[name]) for name in PARTS))


def changed(old, new):
    """Which of the five differ between two stamps, in PARTS' order; all
    of them when there's no old one."""
    if old is None:
        return list(PARTS)
    return [name for name in PARTS if old.parts.get(name) != new.parts.get(name)]


def read_stamp(path):
    """The stamp recorded at path, or None where there's none or it can't
    be read, which builds the target again."""
    try:
        with open(path, encoding="utf-8") as fh:
            values = json.load(fh)
        stamp = Stamp.from_dict(values)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return stamp if values.get("stamp") == stamp.digest else None


def write_stamp(path, stamp):
    """Record a stamp, written whole and then put in place, so a run that
    stops leaves the last one or none, never half of one."""
    _write_json(path, stamp.as_dict())


def _write_json(path, values):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    temporary = os.path.join(folder, "." + os.path.basename(path) + ".partial")
    with open(temporary, "w", encoding="utf-8") as fh:
        json.dump(values, fh, sort_keys=True, indent=1, ensure_ascii=False)
        fh.write("\n")
    os.replace(temporary, path)


def stamp_name(kind, name):
    """The name a target's or a package's stamp file is kept under, which
    the naming rule keeps to one folder's name."""
    if kind not in ("target", "package") or oerconfig.name_problem(name, kind):
        raise ValueError(f"no stamp for {kind} {name!r}")
    return f"{kind}-{name}.json"
