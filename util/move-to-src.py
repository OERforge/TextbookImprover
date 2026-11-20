#!/usr/bin/env python3
"""
move-to-src.py -- move a book from the layout earlier versions read into
the one the next release reads: each part's sources in src/<part>/, its
sidecars in sidecars/<part>/, and the settings files at the top.

    python3 util/move-to-src.py --dry-run          # say what it would do
    python3 util/move-to-src.py                    # do it
    python3 util/move-to-src.py -d path/to/book --slides 'lecture-*.md'

Run it from the book's folder, or give -d. That folder becomes the
project's: the settings files stay at its top, and so does every file a
setting names (a template, a stylesheet, a cover). This version's
convert.py still reads the old layout, so run the move when you take up
the release that reads the new one, or with --dry-run to see what it
would do.

WHERE THE SOURCES GO

A folder of one kind goes whole: a book's into src/book/, a folder of
decks alone into src/slides/ (or when project.kind says slides), and a
LaTeX book that keeps its sources in its own src/ has that folder's
files in src/book/. A folder holding a book and decks is split, each
source placed by the first of these that places it:

  1. By its type: a PowerPoint or Impress file is a deck, a Word file the
     book's, and an HTML or AsciiDoc file the book's, since no deck is
     one.
  2. By the book's contents: a Markdown or LaTeX file it names is the
     book's, by its own name or its page's (01-Intro for "01 Intro.md"),
     and so is a LaTeX master and each .tex a master of the book's
     includes.
  3. By --slides PATTERN, for decks written in Markdown.

If a Markdown or LaTeX source is left unplaced, it moves nothing and
names them. Split, each part gets a copy of every file its sources name,
so a picture both use is in both and no reference is rewritten; a file
no source names is named and left where it is. A LaTeX book takes its
.latexmkrc, its file of definitions (latex.macros), and any package,
class, or bibliography style it keeps beside its sources.

SIDECARS

Each sidecar goes to sidecars/<part>/ under its standard name, and the
sidecars: and reports: settings come out of conversion.yaml, since the
next release keeps them at fixed names. One outside the book's folder is
copied in and the original named. Split, a sidecar's rows are divided by
what they're keyed on: a row keyed by a file goes to the part with the
file, or to both where both have it; one keyed by a page the split cut
from a source goes where page-names-report.csv says that page came
from; one keyed by a table's content, its label, or a deck's picture by
its bytes, and every row of bare-links.csv and math-keep.csv, goes to
both. The original is left, and named. The first build after the move
reports a row that matches nothing in its part.

WHAT'S LEFT

An outside template, stylesheet, or other file a setting names is copied
into the project (templates/, or fonts/ for a font) and its setting
rewritten. output_dir: . is dropped from a target, which then writes into
a folder named after it. What earlier runs wrote beside the sources (the
intermediates, the reports and drafts, a Word file's media, rendered
drawings, the targets' folders) is named for you to delete, since it can't
be told for sure from your own files. Nothing is deleted.

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
import csv
import fnmatch
import io
import json
import os
import re
import shutil
import subprocess
import sys
from urllib.parse import unquote, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))

try:
    import yaml
except ImportError:
    sys.exit("This needs PyYAML. Install it with:\n"
             "    sudo apt install python3-yaml\n"
             "  or\n"
             "    pip3 install pyyaml")

import bookcontents                                  # noqa: E402
import decksave                                      # noqa: E402
import names                                         # noqa: E402
import oerconfig                                     # noqa: E402

SETTINGS_FILES = ("project.yaml", "conversion.yaml", "packaging.yaml")
LEGACY_NAME = "imsmanifest.yaml"
# The names the layout keeps at a project's top.
RESERVED_TOP = ("src", "output", "sidecars", "upstream", "originals")
# A book's sources, as convert.py's SOURCE_EXTENSIONS has them, with
# LaTeX's; and the decks.
SOURCE_EXTENSIONS = (".docx", ".md", ".html", ".adoc", ".asciidoc")
LATEX_EXTENSIONS = (".tex",)
DECK_EXTENSIONS = (".pptx",) + decksave.EXTENSIONS
# The one dot file that's a book's: latexmk reads it from the book's
# folder, and it's honored only when the run's told to.
BOOK_DOT_FILES = (".latexmkrc",)
# Files a repository holds about itself, which aren't a book's pages
# (convert.py's REPOSITORY_FILES).
REPOSITORY_FILES = ("readme.md", "license.md", "contributing.md", "changelog.md",
                    "code_of_conduct.md", "security.md")
# What earlier runs wrote beside the sources, beyond the reports the
# settings name and the targets' folders.
RUN_FILES = ("imsmanifest.xml", "cartridge-files.txt", "table-headers-sample.csv",
             "table-headers-unmatched.csv", "project-sample.yaml",
             "conversion-sample.yaml", "packaging-sample.yaml")
RUN_FOLDERS = ("rendered", "intermediates")
FONT_EXTENSIONS = (".otf", ".ttf", ".woff", ".woff2", ".ttc")
PICTURE_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".svg", ".gif")
# Each sidecar's setting, and how its rows are keyed when a folder is
# split: by a file, by a page, or by content or a label.
SIDECAR_KEYS = {
    "image_alt": "picture",
    "table_captions": "caption",
    "slide_titles": "deck",
    "reading_order": "deck",
    "page_names": "source",
    "languages": "source",
    "table_headers": "content",
    "bare_links": "content",
    "math_keep": "content",
}


def say(text=""):
    print(text)


class Stop(Exception):
    """Why the move can't go on, said to the person, nothing moved."""


# --------------------------------------------------------------------------
# where a project may be
# --------------------------------------------------------------------------

def tex_tree():
    """The TeX tree's folder, where kpsewhich says, or None."""
    kpsewhich = shutil.which("kpsewhich")
    if not kpsewhich:
        return None
    done = subprocess.run([kpsewhich, "-var-value=TEXMFROOT"], capture_output=True,
                          text=True, stdin=subprocess.DEVNULL)
    found = done.stdout.strip()
    return os.path.realpath(found) if found else None


def inside(path, folder):
    path, folder = os.path.realpath(path), os.path.realpath(folder)
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def refused_root(root):
    """Why root can't be a project's folder, or None. A hostile book's
    ![](.ssh/id_rsa) would otherwise be inside the project."""
    real = os.path.realpath(root)
    home = os.path.realpath(os.path.expanduser("~"))
    if real == os.sep:
        return "it's the file system's root"
    if real == home:
        return "it's your home folder; make a folder for the book and run it there"
    if re.match(r"^/mnt/[a-zA-Z](/|$)", real):
        return ("it's on a Windows drive (" + real[:6] + "); WSL reads those slowly and "
                "can't keep their files' permissions. Copy the book into your WSL home")
    if ":" in real:
        return ("its path holds a colon, which TEXINPUTS and Pandoc's resource path take "
                "as a separator")
    if inside(ROOT, real):
        return "it holds TextbookImprover's own folder"
    tree = tex_tree()
    if tree and inside(tree, real):
        return "it holds the TeX tree"
    parent = os.path.dirname(real)
    while parent and parent != os.path.dirname(parent):
        marker = os.path.join(parent, "output", ".textbookimprover")
        if os.path.isfile(marker) or (os.path.isdir(os.path.join(parent, "src")) and any(
                os.path.isfile(os.path.join(parent, name)) for name in SETTINGS_FILES)):
            return f"it's inside another project, {parent}"
        parent = os.path.dirname(parent)
    return None


# --------------------------------------------------------------------------
# the configuration
# --------------------------------------------------------------------------

class Config:
    """The book's settings as this version reads them."""

    def __init__(self, root):
        self.root = root
        schemas = {name: oerconfig.load_schema(os.path.join(ROOT, folder, name))
                   for name, folder in (("schema-conversion.yaml", "bin"),
                                        ("schema-packaging.yaml", "bin"),
                                        ("schema-project.yaml", "lib"))}
        self.conversion = schemas["schema-conversion.yaml"]
        self.packaging = schemas["schema-packaging.yaml"]
        self.project_schema = schemas["schema-project.yaml"]
        self.documents = {}
        for name in SETTINGS_FILES:
            path = os.path.join(root, name)
            if os.path.isfile(path):
                self.documents[name] = oerconfig.load_document(path)
        converting = [self.documents[n] for n in ("project.yaml", "conversion.yaml")
                      if n in self.documents]
        packaging = [self.documents[n] for n in ("project.yaml", "packaging.yaml")
                     if n in self.documents]
        self.defaults = oerconfig.resolve(self.conversion, self.project_schema, converting)
        self.project = self.defaults.project
        names = oerconfig.target_names(converting) or ["html"]
        self.targets = {}
        for name in names:
            if name == "html" and not oerconfig.target_names(converting):
                self.targets[name] = self.defaults
                continue
            self.targets[name] = oerconfig.resolve(self.conversion, self.project_schema,
                                                   converting, target=name)
        self.packages = {}
        if "packaging.yaml" in self.documents:
            for name in oerconfig.target_names(packaging):
                self.packages[name] = oerconfig.resolve(self.packaging, self.project_schema,
                                                        packaging, target=name)

    def setting(self, section, key):
        return self.defaults.settings.get(section, {}).get(key)

    def output_dirs(self):
        """Each target's folder as it's named, html for the implied one."""
        return {name: str(t.settings.get("output_dir") or name)
                for name, t in self.targets.items()}

    def named_paths(self):
        """Each file a setting names, other than a sidecar or a report, as
        (where, the setting's dotted name, its value)."""
        found = []

        def walk(node, values, where, prefix=""):
            for key, child in node.keys.items():
                dotted = prefix + key
                value = (values or {}).get(key)
                if child.is_section:
                    if key not in ("sidecars", "reports"):
                        walk(child, value or {}, where, dotted + ".")
                elif child.type == "path" and key not in ("output_dir", "filename") \
                        and isinstance(value, str) and value.strip():
                    found.append((where, dotted, value.strip()))
                elif child.type == "text" and key in ("header", "footer") \
                        and isinstance(value, str) and value.strip() \
                        and "\n" not in value.strip() \
                        and os.path.isfile(os.path.join(self.root, value.strip())):
                    found.append((where, dotted, value.strip()))
        walk(self.conversion.root, self.defaults.settings, "defaults")
        for name, target in self.targets.items():
            walk(self.conversion.root, target.settings, f"target {name}")
        out, kept = [], set()
        for item in found:
            if (item[1], item[2]) not in kept:
                kept.add((item[1], item[2]))
                out.append(item)
        return out


def raw_block(document, path):
    """The raw value at a dotted path in a document's data, or None."""
    node = document.data
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


# --------------------------------------------------------------------------
# editing a settings file, keeping its comments
# --------------------------------------------------------------------------

def _indent(line):
    return len(line) - len(line.lstrip(" "))


def _find_key(lines, path):
    """The index of the line holding the last key of path, where each key
    is nested in the one before it, or None."""
    start, end, depth = 0, len(lines), -1
    found = None
    for key in path:
        found = None
        pattern = re.compile(r"^( *)" + re.escape(str(key)) + r"\s*:(\s|$)")
        for index in range(start, end):
            line = lines[index]
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if _indent(line) <= depth:
                break
            match = pattern.match(line)
            if match and len(match.group(1)) > depth:
                found = index
                break
        if found is None:
            return None
        depth = _indent(lines[found])
        start = found + 1
        end = start
        while end < len(lines) and (not lines[end].strip() or lines[end].lstrip().startswith("#")
                                    or _indent(lines[end]) > depth):
            end += 1
    return found


def remove_key(text, path):
    """text with the setting or block at path taken out, and the comment
    lines right above it, which describe it; None where it isn't there."""
    lines = text.split("\n")
    index = _find_key(lines, path)
    if index is None:
        return None
    depth = _indent(lines[index])
    end = index + 1
    while end < len(lines) and (not lines[end].strip() or _indent(lines[end]) > depth):
        if lines[end].strip() and lines[end].lstrip().startswith("#") \
                and _indent(lines[end]) <= depth:
            break
        end += 1
    # Trailing blank lines stay, as the file's spacing between settings.
    while end > index + 1 and not lines[end - 1].strip():
        end -= 1
    start = index
    while start > 0 and lines[start - 1].lstrip().startswith("#") \
            and _indent(lines[start - 1]) == depth:
        start -= 1
    if start > 0 and not lines[start - 1].strip() and end < len(lines) \
            and not lines[end].strip():
        start -= 1
    return "\n".join(lines[:start] + lines[end:])


def replace_value(text, path, value):
    """text with the setting at path given value; None where it isn't a
    one-line setting there."""
    lines = text.split("\n")
    index = _find_key(lines, path)
    if index is None:
        return None
    match = re.match(r"^( *[^:#]+:\s*)(.*?)(\s+#.*)?$", lines[index])
    if not match or not match.group(2) or match.group(2) in ("|", ">", "|-", ">-"):
        return None
    lines[index] = match.group(1) + json.dumps(value) + (match.group(3) or "")
    return "\n".join(lines)


def delete_path(data, path):
    node = data
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    parent = data
    for key in path[:-2]:
        parent = parent[key]
    if len(path) > 1 and node == {}:
        del parent[path[-2]]


def set_path(data, path, value):
    node = data
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value


# --------------------------------------------------------------------------
# what a source names
# --------------------------------------------------------------------------

RAW_ATTRIBUTES = re.compile(
    r"""\b(?:src|href|data|poster)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.I)
SRCSET = re.compile(r"""\bsrcset\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.I)
CSS_URL = re.compile(r"""url\(\s*['"]?([^'")]+)['"]?\s*\)""", re.I)
LATEX_NAMES = re.compile(
    r"\\(includegraphics|input|include|subfile|bibliography|addbibresource|"
    r"lstinputlisting|verbatiminput|includepdf|includesvg|usepackage|RequirePackage|"
    r"documentclass|LoadClass|bibliographystyle)\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}")
# A package, class, or bibliography style a book keeps beside its sources
# is found by its name and this extension; one TeX's own tree supplies
# isn't there, and nothing is copied for it.
LATEX_OWN = {"usepackage": ".sty", "RequirePackage": ".sty", "documentclass": ".cls",
             "LoadClass": ".cls", "bibliographystyle": ".bst"}
GRAPHICSPATH = re.compile(r"\\graphicspath\s*\{((?:\{[^}]*\})+)\}")
ASCIIDOC_NAMES = re.compile(r"(?:image::?|include::|video::|audio::|link:)([^\[\s]+)\[")


def local_target(target):
    """A reference's file, unquoted, or None for an address, a fragment,
    or an empty one."""
    target = (target or "").strip()
    if not target or target.startswith("#"):
        return None
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or target.startswith("//"):
        if not re.match(r"^[A-Za-z]:[\\/]", target):
            return None
    path = unquote(parts.path if not re.match(r"^[A-Za-z]:[\\/]", target) else target)
    return path or None


def _walk_json(node, found):
    if isinstance(node, dict):
        kind = node.get("t")
        content = node.get("c")
        if kind in ("Image", "Link") and isinstance(content, list) and len(content) == 3:
            found.append(content[2][0])
        elif kind in ("RawInline", "RawBlock") and isinstance(content, list) \
                and len(content) == 2 and str(content[0]).lower() == "html":
            found.extend(_html_names(content[1]))
        for value in node.values():
            _walk_json(value, found)
    elif isinstance(node, list):
        for value in node:
            _walk_json(value, found)


def _html_names(text):
    names = [next(g for g in m.groups() if g is not None) for m in RAW_ATTRIBUTES.finditer(text)]
    for match in SRCSET.finditer(text):
        for item in (match.group(1) or match.group(2) or "").split(","):
            if item.strip():
                names.append(item.strip().split()[0])
    names += CSS_URL.findall(text)
    return names


def pandoc_names(path, reader):
    """What a Markdown or HTML source names, through Pandoc's reader."""
    import pandocrun
    done = subprocess.run(pandocrun.PANDOC + ["-f", reader, "-t", "json", path],
                          capture_output=True, stdin=subprocess.DEVNULL)
    if done.returncode != 0:
        raise Stop(f"Pandoc couldn't read {path}: "
                   + done.stderr.decode("utf-8", "replace").strip())
    found = []
    document = json.loads(done.stdout.decode("utf-8"))
    _walk_json(document.get("blocks", []), found)
    meta = document.get("meta", {})
    for key in ("bibliography", "css", "csl"):
        if key in meta:
            texts = []
            _strings(meta[key], texts)
            found.extend(texts)
    if reader == "html":
        with open(path, encoding="utf-8", errors="replace") as fh:
            found.extend(_html_names(fh.read()))
    return found


def _strings(node, out):
    if isinstance(node, dict):
        if node.get("t") == "Str":
            out.append(node["c"])
            return
        if node.get("t") in ("MetaInlines", "MetaString"):
            text = []
            _inline_text(node.get("c"), text)
            out.append("".join(text))
            return
        for value in node.values():
            _strings(value, out)
    elif isinstance(node, list):
        for value in node:
            _strings(value, out)


def _inline_text(node, out):
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, dict):
        if node.get("t") == "Str":
            out.append(node["c"])
        elif node.get("t") == "Space":
            out.append(" ")
        else:
            _inline_text(node.get("c"), out)
    elif isinstance(node, list):
        for value in node:
            _inline_text(value, out)


def latex_names(path):
    """What a LaTeX file names, and the folders its \\graphicspath gives."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = re.sub(r"(?<!\\)%.*", "", fh.read())
    folders = [""]
    for match in GRAPHICSPATH.finditer(text):
        folders += re.findall(r"\{([^}]*)\}", match.group(1))
    names = []
    for command, argument in LATEX_NAMES.findall(text):
        for item in argument.split(","):
            item = item.strip()
            if item:
                names.append((command, item))
    return names, folders


def asciidoc_names(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return ASCIIDOC_NAMES.findall(fh.read())


# --------------------------------------------------------------------------
# the move
# --------------------------------------------------------------------------

class Move:
    """Everything the move would do, worked out before anything's done."""

    def __init__(self, root, slides_patterns):
        self.root = root
        self.slides_patterns = slides_patterns
        self.renames = []          # (from, to), each a top entry or a folder
        self.sidecar_renames = []  # (from, to), done before the renames
        self.copies = []           # (from, to)
        self.writes = []           # (path, text)
        self.restores = []         # (from, to): a named file put back after its folder moved
        self.said = []             # lines saying what's done
        self.leftovers = []        # what earlier runs left, for the person to delete
        self.unnamed = []          # files no source names, left
        self.copied_from = []      # files copied into a part, the original left
        self.unmatched = []        # sidecar rows kept in both parts
        self.outside = []          # files a source names outside the book's folder
        self.config_text = {}      # settings file -> its rewritten text
        self.parts = {}            # part -> its sources, as top names

    # ---- sizing up ------------------------------------------------------

    def survey(self):
        root = self.root
        why = refused_root(root)
        if why:
            raise Stop(f"{root} can't be a project's folder: {why}.")
        if os.path.isfile(os.path.join(root, LEGACY_NAME)) and not any(
                os.path.isfile(os.path.join(root, n)) for n in SETTINGS_FILES):
            raise Stop(f"{LEGACY_NAME} here is a configuration from v0.1. Run "
                       "util/migrate-config.py first, then this.")
        try:
            self.config = Config(root)
        except oerconfig.ConfigError as exc:
            raise Stop(f"{exc}\n\nThe configuration doesn't read with this version, so "
                       "nothing was moved. Fix it first, as convert.py's message would say.")
        for link in RESERVED_TOP[1:]:
            path = os.path.join(root, link)
            if os.path.islink(path):
                raise Stop(f"{link} here is a link, which a project's {link}/ can't be.")
        self.entries = sorted(e for e in os.listdir(root))
        self.passthrough = str(self.config.project.get("passthrough") or "_pt").strip("/")
        self.kind = self.config.project.get("kind")
        # What a setting names stays where the setting finds it, and isn't
        # a source, whatever its extension (a footer's Markdown file).
        self.named_by_settings = []
        for where, dotted, value in self.config.named_paths():
            full = value if os.path.isabs(value) else os.path.join(root, value)
            if inside(full, root) and os.path.exists(full):
                self.named_by_settings.append(
                    os.path.relpath(os.path.realpath(full), os.path.realpath(root)))
        # A file a setting names that the contents also list as a page (a
        # preamble a PDF's metadata is read from, set as a page too) is a
        # source: it goes with the book, where a setting's file is looked
        # for when the top has none of its name.
        listed = set()

        def pages(node):
            if isinstance(node, str):
                listed.add(node)
            elif isinstance(node, list):
                for item in node:
                    pages(item)
            elif isinstance(node, dict):
                if isinstance(node.get("page"), str):
                    listed.add(node["page"])
                pages(node.get("items"))
        pages(self.config.project.get("contents"))
        self.named_pages = [n for n in self.named_by_settings
                            if os.sep not in n and self.is_source(n) and self.stem(n) in listed]
        self.named_by_settings = [n for n in self.named_by_settings
                                  if n not in self.named_pages]
        self.src_layout()
        top_sources = [e for e in self.entries if self.is_source(e)
                       and e not in self.named_by_settings]
        self.top_sources = top_sources
        if self.own_src is None and not top_sources:
            raise Stop("There are no sources here to move: no Word, Markdown, HTML, "
                       "AsciiDoc, or LaTeX file, and no deck.")

    def src_layout(self):
        """What a src/ folder here is: None where there's none, "own" where
        it's a LaTeX book's own folder of sources, and a stop where it's
        the new layout's already."""
        self.own_src = None
        path = os.path.join(self.root, "src")
        if os.path.islink(path):
            raise Stop("src here is a link, which a project's src/ can't be.")
        if not os.path.isdir(path):
            return
        names = os.listdir(path)
        loose = [n for n in names if os.path.isfile(os.path.join(path, n))
                 and n.lower().endswith(SOURCE_EXTENSIONS + LATEX_EXTENSIONS + DECK_EXTENSIONS)]
        top = [e for e in self.entries if self.is_source(e)
               and e.lower() not in REPOSITORY_FILES]
        if loose and not top:
            self.own_src = "src"
            return
        folders = [n for n in names if os.path.isdir(os.path.join(path, n))]
        parts = self.config.project.get("parts") or {}
        known = set(parts) if isinstance(parts, dict) and parts else {"book", "slides"}
        if (folders and not top and not loose) or (not loose and known & set(folders)):
            raise Stop("This project is in the new layout already: src/ holds "
                       f"{', '.join(sorted(folders))}/.")

    def is_source(self, name):
        path = os.path.join(self.root, name)
        if not os.path.isfile(path) or name.startswith("."):
            return False
        lower = name.lower()
        return lower.endswith(SOURCE_EXTENSIONS + LATEX_EXTENSIONS + DECK_EXTENSIONS)

    def stem(self, name):
        return os.path.splitext(name)[0]

    # ---- what stays at the top -----------------------------------------

    def stays(self):
        """Each top entry that isn't the book's, mapped to why: the
        settings, what the layout keeps, the sidecars and reports, what
        settings name, and what earlier runs wrote."""
        root, config = self.root, self.config
        staying = {}
        for name in SETTINGS_FILES + (LEGACY_NAME,):
            staying[name] = "settings"
        for name in RESERVED_TOP:
            if name != "src" or self.own_src is None:
                staying[name] = "layout"
        for name in self.entries:
            if name.startswith(".") and name not in BOOK_DOT_FILES:
                staying[name] = "dot"
            if name.endswith(":Zone.Identifier"):
                staying[name] = "zone"
        self.sidecar_files = {}
        for key in config.conversion.node("sidecars").keys:
            value = str(config.setting("sidecars", key) or "").strip()
            if value:
                self.sidecar_files[key] = value
                top = value.replace("\\", "/").split("/")[0]
                if not os.path.isabs(value) and top not in ("..",):
                    if os.path.isfile(os.path.join(root, value)) and "/" not in value:
                        staying[top] = "sidecar"
        reports = []
        for key in config.conversion.node("reports").keys:
            value = str(config.setting("reports", key) or "").strip()
            if value and "/" not in value and os.path.exists(os.path.join(root, value)):
                reports.append(value)
        for name in reports + list(RUN_FILES):
            if os.path.exists(os.path.join(root, name)):
                staying[name] = "run"
        for name in self.entries:
            lower = name.lower()
            if lower.endswith(("-sample.yaml",)) or lower.endswith(".imscc"):
                staying[name] = "run"
        for name in RUN_FOLDERS:
            if os.path.isdir(os.path.join(root, name)):
                staying[name] = "run"
        for target, folder in config.output_dirs().items():
            folder = folder.strip("/")
            if folder and folder not in (".", "") and os.path.exists(os.path.join(root, folder)):
                staying[folder.split("/")[0]] = "run"
            for ext in (".zip", ".tar.gz"):
                if os.path.isfile(os.path.join(root, folder + ext)):
                    staying[folder + ext] = "run"
        for package in config.packages.values():
            name = str(package.settings.get("filename") or "").strip()
            if name and os.path.isfile(os.path.join(root, name)):
                staying[name] = "run"
        stems = {self.stem(n) for n in self.top_sources if not n.lower().endswith(".html")}
        source_stems = {self.stem(n) for n in self.top_sources}
        for name in self.entries:
            stem, ext = os.path.splitext(name)
            lower = name.lower()
            if lower.endswith(".json") and (
                    lower.endswith(".filtered.json") or stem in source_stems
                    or os.path.isfile(os.path.join(root, stem + ".filtered.json"))):
                staying[name] = "run"
            elif lower.endswith(".html") and (stem in stems or (
                    "--" in stem and stem.split("--", 1)[0] in source_stems)):
                staying[name] = "run"
            elif ext.lower() == ".pptx" and any(
                    os.path.isfile(os.path.join(root, stem + other))
                    for other in decksave.EXTENSIONS):
                staying[name] = "run"
            elif os.path.isdir(os.path.join(root, name)) and stem in {
                    self.stem(n) for n in self.top_sources if n.lower().endswith(".docx")} \
                    and os.path.isdir(os.path.join(root, name, "media")) \
                    and set(os.listdir(os.path.join(root, name))) <= {"media"}:
                staying[name] = "run"
        for named in self.named_by_settings:
            if os.sep not in named:
                staying[named] = "named"
        # A folder holding only what settings name (templates/) stays too.
        for name in self.entries:
            path = os.path.join(root, name)
            if name in staying or not os.path.isdir(path) or os.path.islink(path):
                continue
            files = [os.path.relpath(os.path.join(here, f), root)
                     for here, _, names in os.walk(path) for f in names]
            if files and all(f in self.named_by_settings for f in files):
                staying[name] = "named"
        return staying

    # ---- placing --------------------------------------------------------

    def place(self):
        """Each source's part, or a stop naming those left unplaced."""
        config, root = self.config, self.root
        sources = self.top_sources
        decks = [n for n in sources if n.lower().endswith(DECK_EXTENSIONS)]
        book = [n for n in sources if n not in decks]
        meaningful = [n for n in book if n.lower() not in REPOSITORY_FILES]
        if self.own_src is not None and not meaningful and not decks:
            return "own"
        if self.kind == "slides" and not self.slides_patterns:
            self.parts = {"slides": sources}
            return "whole"
        if not decks and not self.slides_patterns:
            self.parts = {"book": sources}
            return "whole"
        if decks and not meaningful and not self.slides_patterns:
            self.parts = {"slides": sources}
            return "whole"
        contents = bookcontents.declared_pages(config.project.get("contents") or [])
        placed, unplaced = {"book": [], "slides": []}, []
        latex_book = set()
        masters = [n for n in book if n.lower().endswith(".tex")
                   and _is_master(os.path.join(root, n))]
        for master in masters:
            latex_book |= self.latex_closure(master)
        # The book's file of definitions (latex.macros) is the book's too.
        macros = str(config.setting("latex", "macros") or "").strip()
        if masters and macros in book:
            latex_book.add(macros)
        for name in sources:
            lower = name.lower()
            stem = self.stem(name)
            if lower.endswith(DECK_EXTENSIONS):
                placed["slides"].append(name)
            elif lower.endswith((".docx", ".html", ".adoc", ".asciidoc")):
                placed["book"].append(name)
            elif stem in contents or names.safe_stem(stem) in contents \
                    or name in latex_book:
                placed["book"].append(name)
            elif any(fnmatch.fnmatch(name, p) for p in self.slides_patterns) \
                    and lower.endswith(".md"):
                placed["slides"].append(name)
            elif lower in REPOSITORY_FILES:
                continue
            else:
                unplaced.append(name)
        if unplaced:
            raise Stop("These sources can't be placed in the book or the decks, so nothing "
                       "was moved:\n  " + "\n  ".join(unplaced) + "\n\nName a page of the "
                       "book in project.yaml's contents, or give --slides a pattern that "
                       "matches the decks' files (--slides 'lecture-*.md').")
        self.parts = {k: v for k, v in placed.items() if v}
        if len(self.parts) == 1:
            return "whole"
        return "split"

    def latex_closure(self, master):
        """Each .tex at the top a master includes, itself among them."""
        found, todo = set(), [master]
        while todo:
            name = todo.pop()
            if name in found:
                continue
            found.add(name)
            names, _ = latex_names(os.path.join(self.root, name))
            for command, item in names:
                if command in ("input", "include", "subfile"):
                    candidate = item if item.endswith(".tex") else item + ".tex"
                    if os.path.isfile(os.path.join(self.root, candidate)) and "/" not in candidate:
                        todo.append(candidate)
        return found

    def names(self, part, name):
        """The files under the book's folder a source names, as paths from
        it, and what it names outside, from a source at the top or in the
        pass-through folder, whose references read from the top."""
        path = os.path.join(self.root, name)
        lower = name.lower()
        found, outside = set(), []

        def add(reference, candidates=None):
            target = local_target(reference)
            if target is None:
                return
            options = candidates or [target]
            # A backslash between folders is read as a slash, as the run
            # reads it, so the file comes with the source that names it.
            options = options + [o.replace("\\", "/") for o in options if "\\" in o]
            for option in options:
                full = option if os.path.isabs(option) else os.path.join(self.root, option)
                if not inside(full, self.root):
                    outside.append(option)
                    return
                if os.path.isfile(full):
                    found.add(os.path.relpath(os.path.realpath(full),
                                              os.path.realpath(self.root)))
                    return
        if lower.endswith(".md"):
            for reference in pandoc_names(path, "markdown"):
                add(reference)
        elif lower.endswith(".html"):
            for reference in pandoc_names(path, "html"):
                add(reference)
        elif lower.endswith((".adoc", ".asciidoc")):
            for reference in asciidoc_names(path):
                add(reference)
        elif lower.endswith(".tex"):
            references, folders = latex_names(path)
            for command, item in references:
                if command == "includegraphics" or command in ("includepdf", "includesvg"):
                    stem_has_ext = os.path.splitext(item)[1].lower() in PICTURE_EXTENSIONS
                    options = [os.path.join(f, item + ("" if stem_has_ext else ext))
                               for f in folders
                               for ext in ([""] if stem_has_ext else PICTURE_EXTENSIONS)]
                    add(item, options)
                elif command in ("input", "include", "subfile"):
                    add(item, [item, item + ".tex"])
                elif command in ("bibliography",):
                    add(item, [item + ".bib", item])
                elif command in LATEX_OWN:
                    add(item, [item + LATEX_OWN[command]])
                else:
                    add(item)
            for included in sorted(found):
                if included.endswith(".tex") and included != name:
                    more, far = self.names(part, included)
                    found |= more
                    outside += far
        return found, outside

    # ---- the plan -------------------------------------------------------

    def plan(self):
        root = self.root
        staying = self.stays()
        # A page an earlier run wrote beside the sources isn't one.
        self.top_sources = [s for s in self.top_sources if s not in staying]
        if self.own_src is None and not self.top_sources:
            raise Stop("There are no sources here to move, only what earlier runs wrote.")
        how = self.place()
        self.how = how
        top = self.entries
        src = os.path.join(root, "src")
        if how == "own":
            self.renames.append(("src", os.path.join("src", "book")))
            self.said.append("src/ holds the LaTeX book's sources: its files go into src/book/.")
            for name in top:
                if name not in staying and name != "src":
                    self.unnamed.append(name)
            self.parts = {"book": ["src/"]}
        elif how == "whole":
            part = next(iter(self.parts))
            for name in top:
                if name in staying:
                    continue
                self.renames.append((name, os.path.join("src", part, name)))
            self.said.append(f"The folder is one {('book' if part == 'book' else 'set of decks')}: "
                             f"its {len(self.renames)} file(s) and folder(s) go into src/{part}/.")
            # A file a setting names, in a folder that moves, is put back
            # where the setting finds it.
            for named in self.named_by_settings:
                first = named.split(os.sep)[0]
                if first not in staying and os.sep in named:
                    self.restores.append((os.path.join("src", part, named), named))
        else:
            for part, sources in self.parts.items():
                for name in sources:
                    self.renames.append((name, os.path.join("src", part, name)))
            if os.path.isdir(os.path.join(root, self.passthrough)):
                self.renames.append((self.passthrough, os.path.join("src", "book",
                                                                    self.passthrough)))
                self.parts["book"] = self.parts.get("book", []) + [self.passthrough + "/"]
            named = {part: set() for part in self.parts}
            for part, sources in self.parts.items():
                for name in sources:
                    if name.endswith("/"):
                        folder = os.path.join(root, name)
                        for here, _, files in os.walk(folder):
                            for f in files:
                                if f.lower().endswith((".md", ".html")):
                                    rel = os.path.relpath(os.path.join(here, f), root)
                                    more, far = self.names(part, rel)
                                    named[part] |= more
                                    self.outside += far
                        continue
                    more, far = self.names(part, name)
                    named[part] |= more
                    self.outside += far
            # A LaTeX book's .latexmkrc and its file of definitions
            # (latex.macros) are read from the book's folder though no
            # source names them, so they go with the book.
            if any(s.lower().endswith(LATEX_EXTENSIONS) for s in self.parts.get("book", [])):
                macros = str(self.config.setting("latex", "macros") or "").strip()
                for name in BOOK_DOT_FILES + ((macros,) if macros else ()):
                    if os.sep not in name and "/" not in name \
                            and os.path.isfile(os.path.join(root, name)):
                        named["book"].add(name)
            moving = {s for sources in self.parts.values() for s in sources}
            moved_tops = {m.rstrip("/").split("/")[0] for m in moving}
            everything = set()
            for part, files in named.items():
                for relative in sorted(files):
                    first = relative.split(os.sep)[0]
                    if first in moved_tops or first in staying:
                        continue
                    self.copies.append((relative, os.path.join("src", part, relative)))
                    everything.add(relative)
            self.copied_from = sorted(everything)
            self.named_files = named
            for name in top:
                if name in staying or name in moved_tops:
                    continue
                path = os.path.join(root, name)
                if os.path.isdir(path):
                    for here, _, files in os.walk(path):
                        for f in files:
                            rel = os.path.relpath(os.path.join(here, f), root)
                            if rel not in everything and rel not in self.named_by_settings:
                                self.unnamed.append(rel)
                elif name not in everything and name not in self.named_by_settings:
                    self.unnamed.append(name)
            self.said.append("The folder holds a book and decks: "
                             + "; ".join(f"{len([s for s in v if not s.endswith('/')])} "
                                         f"source(s) go into src/{k}/"
                                         for k, v in self.parts.items()) + ".")
        self.leftovers = sorted(n for n, why in staying.items()
                                if why == "run" and os.path.exists(os.path.join(root, n)))
        self.plan_sidecars()
        self.plan_settings()
        for source, target in self.renames + self.copies + self.sidecar_renames:
            if os.path.lexists(os.path.join(root, target)) and not (
                    how == "own" and target == os.path.join("src", "book")):
                raise Stop(f"{target} is there already, so nothing was moved. Move it "
                           "aside first.")
        if os.path.isdir(src) and how != "own":
            for part in self.parts:
                if os.path.lexists(os.path.join(src, part)):
                    raise Stop(f"src/{part} is there already, so nothing was moved.")

    # ---- sidecars -------------------------------------------------------

    def plan_sidecars(self):
        root = self.root
        node = self.config.conversion.node("sidecars")
        parts = list(self.parts)
        self.sidecar_moves = []
        for key in node.keys:
            standard = str(node.keys[key].default)
            value = self.sidecar_files.get(key)
            if not value:
                continue
            full = value if os.path.isabs(value) else os.path.join(root, value)
            if not os.path.isfile(full):
                continue
            outside = not inside(full, root)
            if self.how != "split":
                part = parts[0]
                target = os.path.join("sidecars", part, standard)
                if outside:
                    self.copies.append((full, target))
                    self.said.append(f"{value} is outside the book's folder: copied to "
                                     f"{target}, the original left where it is.")
                else:
                    relative = os.path.relpath(full, root)
                    self.sidecar_renames.append((relative, target))
                    self.said.append(f"{relative} goes to {target}"
                                     + (", its standard name." if relative != standard else "."))
                continue
            with open(full, "rb") as fh:
                data = fh.read()
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                for part in parts:
                    self.copies.append((full, os.path.join("sidecars", part, standard)))
                self.said.append(f"{value} isn't UTF-8, so it's copied whole into each part's "
                                 "sidecars; the first run reads it as before.")
                continue
            rows = list(csv.reader(io.StringIO(text, newline="")))
            if not rows:
                continue
            header, body = rows[0], rows[1:]
            divided = {part: [] for part in parts}
            for row in body:
                if not row or not "".join(row).strip():
                    continue
                homes = self.row_parts(key, row[0])
                if homes is None:
                    homes = parts
                    self.unmatched.append(f"{standard}: {row[0]}")
                for part in homes:
                    divided[part].append(row)
            for part in parts:
                if not divided[part]:
                    continue
                out = io.StringIO(newline="")
                writer = csv.writer(out, lineterminator="\r\n")
                writer.writerow(header)
                writer.writerows(divided[part])
                self.writes.append((os.path.join("sidecars", part, standard),
                                    "\ufeff" + out.getvalue()))
            self.said.append(f"{value}'s rows go to "
                             + " and ".join(f"sidecars/{p}/{standard} ({len(divided[p])})"
                                            for p in parts if divided[p])
                             + f"; {value} is left where it is.")

    def row_parts(self, key, cell):
        """The parts a sidecar's row belongs to, or None where its key says
        nothing of a part: kept in both, and named."""
        kind = SIDECAR_KEYS.get(key, "content")
        cell = (cell or "").strip()
        stems = {part: {self.stem(s.rstrip("/")) for s in sources}
                 for part, sources in self.parts.items()}
        if kind == "content":
            return list(self.parts)
        if kind == "deck":
            deck = cell.split("/")[0]
            homes = [p for p, s in stems.items() if deck in s or self.stem(deck) in s]
            return homes or None
        if kind == "source":
            name = self.stem(cell) if cell.lower().endswith(
                SOURCE_EXTENSIONS + LATEX_EXTENSIONS + DECK_EXTENSIONS) else cell
            homes = [p for p, s in stems.items() if name in s or cell in s]
            return homes or None
        if kind == "caption":
            match = re.match(r"^(.+)#table-\d+$", cell)
            if not match:
                return list(self.parts)
            page = match.group(1)
            source = self.piece_sources().get(page) or bookcontents.piece_source(page) or page
            homes = [p for p, s in stems.items() if source in s]
            return homes or None
        # A picture: a deck's by its bytes goes to both; one on a deck's
        # slide to the deck's part; a Word file's or a page's media to the
        # part with that file; any other to each part whose sources name
        # the picture.
        if re.match(r"^media/[0-9a-f]{16}", cell):
            return list(self.parts)
        match = re.match(r"^(.+)/slide-\d+/shape-\d+$", cell)
        if match:
            homes = [p for p, s in stems.items() if match.group(1) in s]
            return homes or None
        path = unquote(cell).replace("\\", "/")
        first = path.split("/")[0]
        homes = [p for p, s in stems.items() if first in s and "/" in path]
        if homes:
            return homes
        named = getattr(self, "named_files", {})
        base = os.path.splitext(path)[0]
        homes = [p for p, files in named.items()
                 if any(f.replace(os.sep, "/") == path
                        or os.path.splitext(f.replace(os.sep, "/"))[0] == base for f in files)]
        return homes or None

    def piece_sources(self):
        """Each piece's source, as an earlier run's page-names-report.csv
        says, where there's one."""
        if hasattr(self, "_pieces"):
            return self._pieces
        self._pieces = {}
        value = str(self.config.setting("reports", "page_names_report") or "").strip()
        path = os.path.join(self.root, value) if value else None
        if path and os.path.isfile(path):
            with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
                for row in csv.DictReader(fh):
                    name, source = (row.get("name") or "").strip(), \
                        (row.get("source") or "").strip()
                    if name and source:
                        self._pieces[name] = self.stem(source) if source.lower().endswith(
                            SOURCE_EXTENSIONS + LATEX_EXTENSIONS) else source
        return self._pieces

    # ---- the settings files --------------------------------------------

    def plan_settings(self):
        root, config = self.root, self.config
        for name in ("conversion.yaml", "project.yaml"):
            document = config.documents.get(name)
            if document is None:
                continue
            path = os.path.join(root, name)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            data = yaml.safe_load(text) or {}
            changes = []
            for section in ("sidecars", "reports"):
                if raw_block(document, ["defaults", section]) is not None:
                    changes.append(("remove", ["defaults", section]))
            for target, block in (document.targets or {}).items():
                if isinstance(block, dict) and str(block.get("output_dir", "")).strip() \
                        in (".", "./"):
                    changes.append(("remove", ["targets", target, "output_dir"]))
            # A file a setting names outside the folder is copied in.
            for prefix in [["defaults"]] + [["targets", t] for t in (document.targets or {})]:
                block = raw_block(document, prefix) or {}
                for dotted, value in _path_values(config.conversion.root, block):
                    full = value if os.path.isabs(value) else os.path.join(root, value)
                    if inside(full, root) or not os.path.isfile(full):
                        continue
                    folder = "fonts" if value.lower().endswith(FONT_EXTENSIONS) else "templates"
                    target = os.path.join(folder, os.path.basename(full))
                    if os.path.lexists(os.path.join(root, target)) or target in [
                            t for _, t in self.copies]:
                        stem, ext = os.path.splitext(target)
                        target = f"{stem}-{len(self.copies) + 1}{ext}"
                    self.copies.append((full, target))
                    changes.append(("set", prefix + dotted.split("."), target))
                    self.said.append(f"{'.'.join(prefix + [dotted])} named {value}, outside the "
                                     f"book's folder: copied to {target} and the setting "
                                     "rewritten.")
            if not changes:
                continue
            for change in changes:
                if change[0] == "remove":
                    edited = remove_key(text, change[1])
                    delete_path(data, change[1])
                else:
                    edited = replace_value(text, change[1], change[2])
                    set_path(data, change[1], change[2])
                if edited is None:
                    raise Stop(f"{name} couldn't be edited where it sets "
                               f"{'.'.join(change[1])}, so nothing was moved. Take it out "
                               "by hand and run this again.")
                text = edited
            if (yaml.safe_load(text) or {}) != data:
                raise Stop(f"{name} couldn't be edited cleanly, so nothing was moved. Take "
                           "out " + ", ".join(".".join(c[1]) for c in changes)
                           + " by hand and run this again.")
            self.config_text[name] = text
            removed = [".".join(c[1]) for c in changes if c[0] == "remove"]
            if removed:
                self.said.append(f"{name}: took out " + ", ".join(removed)
                                 + ", which the next release doesn't read.")

    # ---- doing it -------------------------------------------------------

    def report(self, dry):
        would = "would " if dry else ""
        for line in self.said:
            say(("Would: " if dry else "") + line)
        if self.renames:
            say("\nWhat " + ("would move:" if dry else "moved:"))
            for source, target in self.renames:
                say(f"  {source} -> {target}")
        if self.copied_from:
            say(f"\n{len(self.copied_from)} file(s) the sources name "
                + ("would be" if dry else "were") + " copied into "
                "their part(s), the originals left at the top, where nothing reads them "
                "after the move:")
            for name in self.copied_from:
                say("  " + name)
        if self.unnamed:
            say(f"\n{len(self.unnamed)} file(s) no source names, left where they are:")
            for name in self.unnamed:
                say("  " + name)
        if self.outside:
            say("\nThe sources name these outside the book's folder, which the next release "
                "won't read; copy each in and name it there:")
            for name in sorted(set(self.outside)):
                say("  " + name)
        if self.unmatched:
            say(f"\n{len(self.unmatched)} sidecar row(s) {would}go to both parts, since "
                "their keys don't say which; the first run reports a row that matches "
                "nothing in its part:")
            for row in self.unmatched:
                say("  " + row)
        if self.leftovers:
            say("\nWhat earlier runs wrote, left here for you to delete once you're "
                "satisfied:")
            for name in self.leftovers:
                say("  " + name + ("/" if os.path.isdir(os.path.join(self.root, name)) else ""))

    def execute(self):
        root = self.root
        for source, target in self.copies:
            full = source if os.path.isabs(source) else os.path.join(root, source)
            os.makedirs(os.path.dirname(os.path.join(root, target)), exist_ok=True)
            shutil.copy2(full, os.path.join(root, target))
        for path, text in self.writes:
            os.makedirs(os.path.dirname(os.path.join(root, path)), exist_ok=True)
            with open(os.path.join(root, path), "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
        for source, target in self.sidecar_renames:
            os.makedirs(os.path.dirname(os.path.join(root, target)), exist_ok=True)
            os.rename(os.path.join(root, source), os.path.join(root, target))
        if self.how == "own":
            temporary = os.path.join(root, ".move-to-src-" + str(os.getpid()))
            os.rename(os.path.join(root, "src"), temporary)
            os.makedirs(os.path.join(root, "src"))
            os.rename(temporary, os.path.join(root, "src", "book"))
            renames = self.renames[1:]
        else:
            renames = self.renames
        moving_src = [r for r in renames if r[0] == "src"]
        if moving_src:
            temporary = os.path.join(root, ".move-to-src-" + str(os.getpid()))
            os.rename(os.path.join(root, "src"), temporary)
            renames = [(temporary if r[0] == "src" else r[0], r[1]) for r in renames]
        for source, target in renames:
            full = source if os.path.isabs(source) else os.path.join(root, source)
            os.makedirs(os.path.dirname(os.path.join(root, target)), exist_ok=True)
            os.rename(full, os.path.join(root, target))
        for source, target in self.restores:
            os.makedirs(os.path.dirname(os.path.join(root, target)), exist_ok=True)
            shutil.copy2(os.path.join(root, source), os.path.join(root, target))
        for name, text in self.config_text.items():
            path = os.path.join(root, name)
            temporary = path + ".move-to-src"
            with open(temporary, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
            os.replace(temporary, path)


def _path_values(node, values, prefix=""):
    """(dotted, value) for each path setting in a raw block, but a
    sidecar's, a report's, output_dir, and filename."""
    for key, value in (values or {}).items():
        child = node.keys.get(key) if node.keys else None
        if child is None:
            continue
        if child.is_section and isinstance(value, dict):
            if key not in ("sidecars", "reports"):
                yield from _path_values(child, value, prefix + key + ".")
        elif child.type == "path" and key not in ("output_dir", "filename") \
                and isinstance(value, str) and value.strip():
            yield prefix + key, value.strip()


def _is_master(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return bool(re.search(r"^[^%\n]*\\documentclass", fh.read(), re.M))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Move a book into the layout the next release reads: each part's "
                    "sources in src/<part>/, its sidecars in sidecars/<part>/.")
    parser.add_argument("-d", "--dir", default=".",
                        help="the book's folder, which becomes the project's "
                             "(default: this one)")
    parser.add_argument("--slides", action="append", default=[], metavar="PATTERN",
                        help="a pattern matching the file names of decks written in "
                             "Markdown, in a folder holding a book too ('lecture-*.md'); "
                             "may be given again")
    parser.add_argument("--dry-run", action="store_true",
                        help="say what it would do, and do nothing")
    args = parser.parse_args(argv)
    root = os.path.abspath(args.dir)
    if not os.path.isdir(root):
        say(f"{args.dir} isn't a folder.")
        return 2
    move = Move(root, args.slides)
    try:
        move.survey()
        move.plan()
    except Stop as exc:
        print(str(exc), file=sys.stderr)
        return 1
    move.report(args.dry_run)
    if args.dry_run:
        say("\nNothing was moved (--dry-run).")
        return 0
    move.execute()
    say("\nMoved. This version's convert.py still reads the old layout; the next release "
        "reads this one.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
