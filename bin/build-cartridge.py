#!/usr/bin/env python3
"""
build-cartridge.py -- build an IMS Common Cartridge manifest (and
optionally the .imscc archive) from a directory of HTML pages.

    build-cartridge.py                     # write imsmanifest.xml
    build-cartridge.py --check             # validate, write nothing
    build-cartridge.py --zip               # also build the archive
    build-cartridge.py --init              # write a sample config and stop
    build-cartridge.py --includeallhtml    # adopt unlisted pages

This script is read-only with respect to page content: it never edits an
HTML file, an image, or anything under a media directory. It writes only
the manifest, the file list, the sample config, and the archive. That is
what makes it safe to run repeatedly, and what lets it work on any tidy
directory of HTML rather than only on output from convert.py.

Configuration lives in packaging.yaml, with the book's own details in
project.yaml. Everything that can be derived
is derived: page titles come from each page's <title>, and the files a
page needs come from the src and href attributes it actually uses.

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
import hashlib
import html as html_module
import os
import re
import sys
import zipfile
from datetime import date
from urllib.parse import quote, unquote

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("PyYAML is required.  Install it with:\n"
             "    sudo apt install python3-yaml\n"
             "  or: pip3 install pyyaml")

CONFIG_NAME = "packaging.yaml"
PROJECT_NAME = "project.yaml"
SAMPLE_NAME = "packaging-sample.yaml"
LEGACY_NAME = "imsmanifest.yaml"

# The configuration library lives beside bin/. Found by path rather than
# installed, so the project stays clone-and-run.
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
try:
    import oerconfig
except ImportError:
    oerconfig = None
# The contents tree and the filename guess live in the library because the
# EPUB assembler builds its table of contents from the same declaration.
from bookcontents import (  # noqa: E402
    natural_key, chapter_of, within_chapter_key, unrecognised_roles,
    guess_contents, walk_contents, flatten_pages, contents_from_tree,
    stem_title, slugify, clean_title, number_tree, numbered_title,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import importlib
    validate_manifest = importlib.import_module("validate-manifest")
except ImportError:
    validate_manifest = None
FILE_LIST_NAME = "cartridge-files.txt"

CRLF = "\r\n"

# src/href values that are not local files.
EXTERNAL = ("http://", "https://", "//", "data:", "mailto:", "tel:", "#",
            "javascript:")

SRC_RE = re.compile(r'\b(?:src|href)\s*=\s*"([^"]+)"', re.I)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
# What a page split by split-pages.py says about where it came from.
META_RE = re.compile(r'<meta\s+name="(source-page|source-title|page-part|'
                     r'page-parent|page-position|page-role)"\s+content="([^"]*)"',
                     re.I)

REQUIRED = ["identifier", "title"]

# Outline entries that name no page of their own.
TOC_SKIP = {"contents", "table-of-contents", "chapter-objectives",
            "learning-objectives", "about-openstax"}


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def href_of(path):
    """A file path as a manifest href: percent-encoded, then XML-escaped.
    A raw space in an href is not a valid URI reference."""
    return xml_escape(quote(path, safe="/"))


def ncname(text):
    """An identifier IMS types as xs:ID: letters, digits, . - _ only, so
    a page stem with a space or anything else in it is still a name."""
    out = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-")
    return out if out and out[0].isalpha() else "p-" + out


def xml_escape(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


def page_title(path, stem):
    """Title from the page's own <title>, falling back to the filename."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            markup = handle.read(20000)
    except OSError:
        return stem
    m = TITLE_RE.search(markup)
    if m:
        title = clean_title(m.group(1))
        if title:
            return title
    return stem_title(stem)


def page_provenance(path):
    """(source stem, part number, parent titles, position, source title)
    for a page split-pages.py wrote, from the <meta> elements it put in
    the head, or None."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            markup = handle.read(20000)
    except OSError:
        return None
    found, parents = {}, []
    for name, value in META_RE.findall(markup.split("</head>", 1)[0]):
        value = html_module.unescape(value)
        if name == "page-parent":
            parents.append(value)
        else:
            found[name] = value
    if not found.get("source-page"):
        return None
    m = re.match(r"(\d+)/", found.get("page-part", ""))
    return (found["source-page"], int(m.group(1)) if m else None, parents,
            found.get("page-position", ""), found.get("source-title", ""),
            found.get("page-role", ""))


def page_role(path):
    """A page's own role, from the <meta> the filter wrote when it
    promoted a heading carrying one ({.appendix})."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            markup = handle.read(20000)
    except OSError:
        return ""
    found = dict(META_RE.findall(markup.split("</head>", 1)[0]))
    return found.get("page-role", "")


def page_references(path, base_dir):
    """Local files a page refers to, in document order, deduplicated."""
    with open(path, encoding="utf-8", errors="replace") as handle:
        markup = handle.read()

    found, seen = [], set()
    for raw in SRC_RE.findall(markup):
        ref = html_module.unescape(raw).strip()
        if not ref or ref.startswith(EXTERNAL):
            continue
        # A file name with a space is written %20 in a page, as a link
        # must be; what is on disk, and what goes in the archive, has the
        # space. The manifest encodes it again on the way out (href_of).
        ref = unquote(ref.split("#", 1)[0].split("?", 1)[0])
        if not ref or ref in seen:
            continue
        seen.add(ref)
        found.append(ref)
    return found


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------

def pdf_outline(path):
    """(depth, title) for each bookmark of a PDF, in order."""
    try:
        from pypdf import PdfReader
    except ImportError:
        sys.exit("Reading a PDF outline needs pypdf. Install it with:\n"
                 "    pip3 install pypdf")

    reader = PdfReader(path)
    if not reader.outline:
        sys.exit(f"{path} has no bookmarks, so there is no outline to read.")

    entries = []

    def walk(node, depth):
        for item in node:
            if isinstance(item, list):
                walk(item, depth + 1)
            else:
                entries.append((depth, clean_title(str(item.title))))

    walk(reader.outline, 0)
    return entries


def epub_outline(path):
    """(depth, title) for each entry of an EPUB's table of contents.

    EPUB 3 keeps it in the navigation document, a nested <ol> inside
    <nav epub:type="toc">; EPUB 2 in toc.ncx, as nested navPoint
    elements. The container says where the package document is, and
    the package document says which item is which. Nothing but the
    standard library, so this needs no pypdf.
    """
    import xml.etree.ElementTree as ET
    import zipfile
    import posixpath

    NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container",
          "opf": "http://www.idpf.org/2007/opf",
          "x": "http://www.w3.org/1999/xhtml",
          "epub": "http://www.idpf.org/2007/ops",
          "ncx": "http://www.daisy.org/z3986/2005/ncx/"}
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        sys.exit(f"{path} is not an EPUB (not a zip archive).")
    with archive:
        try:
            container = ET.fromstring(archive.read("META-INF/container.xml"))
            opf_name = container.find(".//c:rootfile", NS).get("full-path")
            opf = ET.fromstring(archive.read(opf_name))
        except (KeyError, ET.ParseError, AttributeError) as exc:
            sys.exit(f"{path} has no readable package document: {exc}")
        opf_dir = posixpath.dirname(opf_name)
        nav_item = ncx_item = None
        spine = opf.find("opf:spine", NS)
        toc_id = spine.get("toc") if spine is not None else None
        for item in opf.iter("{%s}item" % NS["opf"]):
            if "nav" in (item.get("properties") or "").split():
                nav_item = item.get("href")
            if item.get("media-type") == "application/x-dtbncx+xml" \
                    or item.get("id") == toc_id:
                ncx_item = item.get("href")

        def read(href):
            return ET.fromstring(archive.read(
                posixpath.normpath(posixpath.join(opf_dir, href))))

        entries = []
        if nav_item:
            nav = read(nav_item)
            toc = None
            for candidate in nav.iter("{%s}nav" % NS["x"]):
                if candidate.get("{%s}type" % NS["epub"]) == "toc":
                    toc = candidate
                    break
            if toc is not None:
                def walk_ol(ol, depth):
                    for li in ol.findall("x:li", NS):
                        label = li.find("x:a", NS)
                        if label is None:
                            label = li.find("x:span", NS)
                        if label is not None:
                            entries.append((depth, clean_title(
                                "".join(label.itertext()))))
                        for child in li.findall("x:ol", NS):
                            walk_ol(child, depth + 1)
                first = toc.find("x:ol", NS)
                if first is not None:
                    walk_ol(first, 0)
        if not entries and ncx_item:
            ncx = read(ncx_item)

            def walk_nav(node, depth):
                for point in node.findall("ncx:navPoint", NS):
                    text = point.find("ncx:navLabel/ncx:text", NS)
                    entries.append((depth, clean_title(
                        "".join(text.itertext()) if text is not None
                        else "")))
                    walk_nav(point, depth + 1)
            nav_map = ncx.find("ncx:navMap", NS)
            if nav_map is not None:
                walk_nav(nav_map, 0)
    if not entries:
        sys.exit(f"{path} has no table of contents to read: no toc nav in "
                 "its navigation document, and no toc.ncx.")
    return entries


def contents_from_outline(path, stems, titles, parts=None):
    """Build a contents tree from a book's own table of contents.

    The outline of a textbook PDF, or the navigation document of its
    EPUB, is its table of contents in the order the book actually uses
    -- which no filename heuristic can match. Pages are found by deriving
    a filename from each heading, so this works for any book whose files
    are named after its headings rather than only for ones whose section
    names are known in advance. OpenStax publishes both, and the EPUB
    needs nothing installed.

    Returns (tree, placed, unmapped). Anything the outline does not cover
    is left for the caller to append as usual.
    """
    if path.lower().endswith(".epub"):
        entries = epub_outline(path)
    else:
        entries = pdf_outline(path)
    parts = parts or {}
    # An entry with no text names nothing; one holding a page's worth of
    # text is a broken navigation document, and is reported rather than
    # matched against every title in the book.
    kept = []
    for depth, title in entries:
        if not title.strip():
            continue
        if len(title) > 200:
            print(f"WARNING: an outline entry is {len(title)} characters "
                  f"long, which is not a heading: {title[:60]!r}...; "
                  "skipped.", file=sys.stderr)
            continue
        kept.append((depth, title))
    entries = kept

    available = set(stems)
    placed, unmapped = set(), []

    # A page is also found by its own title, normalised the way a heading
    # is, so files named BC-01 or cut from a chapter by split_level match
    # the entries that name them. A title two pages share is settled by
    # provenance -- the page from the source the rest of this group came
    # from -- and failing that by reading order, since the outline is in
    # reading order too.
    by_title = {}
    for stem in stems:
        by_title.setdefault(slugify(titles.get(stem, "")), []).append(stem)

    def source_of(stem):
        origin = parts.get(stem)
        return origin[0] if origin else stem

    def order_of(stem):
        origin = parts.get(stem)
        return (natural_key(source_of(stem)),
                origin[1] if origin and origin[1] is not None else 0,
                natural_key(stem))

    group_source = [None]           # the source this top-level entry uses

    def take(*candidates):
        for name in candidates:
            if name and name in available and name not in placed:
                placed.add(name)
                return name
        return None

    def take_title(title):
        hits = [s for s in by_title.get(slugify(title), [])
                if s in available and s not in placed]
        if not hits:
            return None
        if len(hits) > 1 and group_source[0]:
            same = [s for s in hits if source_of(s) == group_source[0]]
            hits = same or hits
        hit = min(hits, key=order_of)
        placed.add(hit)
        if group_source[0] is None:
            group_source[0] = source_of(hit)
        return hit

    def by_prefix(prefix):
        hits = sorted(p for p in available
                      if p.startswith(prefix) and p not in placed)
        if len(hits) == 1:
            placed.add(hits[0])
            return hits[0]
        return None

    def resolve_child(title, chapter):
        slug = slugify(title)
        if slug in TOC_SKIP:
            return None

        # "12.3 The F Distribution and the F-Ratio"
        m = re.match(r"^(\d+)\.(\d+)\b", title)
        if m:
            return by_prefix(f"{m.group(1)}-{m.group(2)}-")

        if chapter is not None:
            # "Introduction" and "Introduction to Demand and Supply" are
            # the same section under two naming conventions.
            if slug == "introduction" or slug.startswith("introduction-to"):
                return (take(f"{chapter}-{slug}", f"{chapter}-introduction")
                        or by_prefix(f"{chapter}-introduction"))
            found = take(f"{chapter}-{slug}")
            if found:
                return found

        return take(slug) or take_title(title)

    tree, i = [], 0
    while i < len(entries):
        depth, title = entries[i]
        i += 1
        if depth != 0:
            continue
        if slugify(title) in TOC_SKIP:
            while i < len(entries) and entries[i][0] > 0:
                i += 1
            continue

        chapter = None
        m = re.match(r"^Chapter\s+(\d+)\b", title)
        if m:
            chapter = m.group(1)

        letter = re.match(r"^Appendix\s+([A-Za-z])\b", title)

        # A top-level entry that is itself a page -- Preface, References,
        # Index, an appendix -- takes the page and its children are
        # sections within it, not separate pages.
        own = None
        group_source[0] = None
        if chapter is None:
            own = take(slugify(title)) or take_title(title)
            if own:
                group_source[0] = source_of(own)
            if own is None and letter:
                own = by_prefix(letter.group(1).lower() + "-")

        # A top-level entry that is itself a page -- Preface, References,
        # an appendix -- takes the page, and its children are headings
        # within it unless they are pages too: a chapter cut into pages
        # by split_level has its own page first and its sections after.
        items = [own] if own else []
        children_unmapped = []
        while i < len(entries) and entries[i][0] > 0:
            child = resolve_child(entries[i][1], chapter)
            if child:
                items.append(child)
            elif slugify(entries[i][1]) not in TOC_SKIP:
                children_unmapped.append(entries[i][1])
            i += 1

        if own and len(items) == 1:
            tree.append(own)            # its children are headings within it
        elif items:
            tree.append({"title": title, "items": items})
            unmapped.extend(children_unmapped)
        else:
            unmapped.extend(children_unmapped)
            if chapter is not None:
                unmapped.append(title)

    return tree, placed, unmapped


def default_config(stems, identifier="course", title="Course"):
    return {
        "manifest": {
            "identifier": identifier,
            "title": title,
            "description": f"{title} converted for import as a Common Cartridge.",
            "keywords": [],
            "version": "1.0",
            "language": "en",
            "cartridge": f"{identifier}.imscc",
        },
        "contents": guess_contents(stems),
    }


# --------------------------------------------------------------------------
# configuration
#
# Everything below the adapter still works from a flat dictionary shaped
# like the v0.1 config, because that is what a thousand lines of manifest
# building already expects. What changed is where that dictionary comes
# from: the library resolves the cascade against a schema, and the
# adapter projects the result back into the old shape. Reading, writing,
# validating, and documenting the settings now all derive from one
# declaration, which is what stops the sample writer from quietly
# dropping keys the reader accepts.
# --------------------------------------------------------------------------

def _schema_dir():
    return os.path.dirname(os.path.abspath(__file__))


def _lib_dir():
    return os.path.join(os.path.dirname(_schema_dir()), "lib")


def load_schemas():
    """The packaging schema and the shared project schema."""
    if oerconfig is None:
        sys.exit("Cannot find the configuration library. It should be in a "
                 "lib/ directory beside bin/.")
    return (oerconfig.load_schema(
                os.path.join(_schema_dir(), "schema-packaging.yaml")),
            oerconfig.load_schema(
                os.path.join(_lib_dir(), "schema-project.yaml")))


def config_documents(base, config_path):
    """The configuration files to read, in increasing precedence.

    A project file is optional: both halves carry a project block inline
    so that a directory holding only one of them still stands alone.
    """
    documents = []
    packaging_schema, project_schema = load_schemas()
    try:
        project_path = os.path.join(base, PROJECT_NAME)
        if os.path.isfile(project_path):
            documents.append(
                oerconfig.load_document(project_path, project_schema))
        if os.path.isfile(config_path):
            documents.append(
                oerconfig.load_document(config_path, packaging_schema))
    except oerconfig.ConfigError as exc:
        sys.exit(str(exc))
    return documents


def choose_target(documents, requested):
    """Which package to build.

    With one package defined there is nothing to choose. With several,
    naming one is required rather than guessed, because building the
    wrong archive silently is worse than stopping.
    """
    names = oerconfig.target_names(documents)
    if requested:
        return requested
    if len(names) == 1:
        return names[0]
    if not names:
        return None
    sys.exit("This configuration defines several packages (" +
             ", ".join(names) + "). Choose one with --target.")


# What each package format's archive is called. The configuration library
# fills an unset filename with the target's own name and stops there,
# because it has no business knowing that a Common Cartridge is a .imscc.
# Supplying the extension is this tool's job.
FORMAT_EXTENSIONS = {
    "common-cartridge": ".imscc",
    "zip": ".zip",
}


def archive_name(settings, project, target):
    """The file to write.

    Derived from the book's identifier rather than from the package's
    name, which is what v0.1 did and is the more useful of the two: a
    directory usually holds one book and several ways of packaging it, so
    the identifier is the part worth seeing in the filename. Two packages
    of the same format would collide, and that is reported rather than
    worked around with a naming convention nobody asked for.
    """
    extension = FORMAT_EXTENSIONS.get(settings.get("format"), ".zip")
    name = settings.get("filename") or project.get("identifier") or target
    # Not os.path.splitext: a reverse-DNS identifier such as
    # org.example.dept.course-2e has a dot in it, and splitext would read
    # ".course-2e" as an extension and leave the archive without one.
    # Only an extension this tool actually writes counts as one.
    if any(name.lower().endswith(known)
           for known in FORMAT_EXTENSIONS.values()):
        return name
    return name + extension


def legacy_view(resolved, target):
    """Project the resolved configuration into the v0.1 shape.

    A translation layer rather than a rewrite. The manifest building below
    reads config["manifest"]["language"] in a dozen places, and changing
    all of them would be a large edit with nothing to show for it.
    """
    project, settings = resolved.project, resolved.settings
    return {
        "numbering": bool(project["numbering"]),
        "manifest": {
            "identifier": project["identifier"],
            "title": project["title"],
            "description": project["description"],
            "language": project["language"],
            "version": settings["version"],
            "modified": settings["modified"],
            "keywords": list(settings["keywords"]),
            "cartridge": archive_name(settings, project, target),
        },
        "contents": project["contents"],
        "common_files": list(settings["common_files"]),
        "grouping": dict(settings["grouping"]),
        "organization": dict(settings.get("organization") or {}),
        "project": dict(project),
        "content_prefix": content_prefix(project,
                                         settings.get("paths") or {}),
    }


def sample_inputs(resolved, documents, target, contents):
    """What dump_sample needs: the resolved config with the contents this
    run worked out, and the target blocks to write back.

    guess_contents produces an ordering from the filenames when the config
    has none, and putting it in the sample is the whole point of writing
    one -- a user who accepts the guess can adopt it by renaming a file
    rather than by typing out a hundred pages.
    """
    settled = oerconfig.Resolved(dict(resolved.project),
                                 dict(resolved.settings),
                                 resolved.target, resolved.warnings)
    settled.project["contents"] = contents
    targets = {}
    for doc in documents:
        for name, block in doc.targets.items():
            targets[name] = block or {}
    if not targets:
        targets[target or "cartridge"] = {"format": "common-cartridge",
                                          "includes": ["html"]}
    return settled, targets


def dump_sample(config, path, notes, unknown_roles=None,
                schema=None, project_schema=None, resolved=None,
                targets=None):
    """Write a complete sample configuration.

    Complete is the point, and it is why this goes through the schema
    rather than building YAML by hand. The v0.1 version emitted a list of
    keys someone had remembered to add, and that list was missing three of
    them -- captions, grouping, and manifest.modified -- so a run that hit
    any error wrote a "complete" sample without them and told the user to
    rename it over their real config. Deriving the file from the same
    declaration the reader uses removes the possibility rather than
    patching the instance; tests/run-roundtrip-test.py asserts it.
    """
    extra = list(notes)
    if unknown_roles:
        extra.append("These page roles are not in the back-matter order: "
                     + ", ".join(sorted(unknown_roles)) + ". They sort last "
                     "until they are listed under grouping.back_matter.")
    oerconfig.write_config(schema, project_schema, resolved, targets or {},
                           path, notes=extra)


def yaml_scalar(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    if text == "":
        return '""'
    if re.search(r'[:#\n"\'{}\[\]&*!|>%@`]', text) or text != text.strip():
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def render_contents(nodes, depth):
    pad = "  " * depth
    lines = []
    for node in nodes:
        if isinstance(node, str):
            lines.append(f"{pad}  - {yaml_scalar(node)}")
        elif "items" in node:
            lines.append(f"{pad}  - title: {yaml_scalar(node.get('title', ''))}")
            lines.append(f"{pad}    items:")
            lines += render_contents(node["items"], depth + 2)
        else:
            lines.append(f"{pad}  - page: {yaml_scalar(node.get('page', ''))}")
            if node.get("title"):
                lines.append(f"{pad}    title: {yaml_scalar(node['title'])}")
    return lines


# --------------------------------------------------------------------------
# contents tree
# --------------------------------------------------------------------------

def chapter_groups(tree, found=None):
    """Map chapter number -> the group node that holds it.

    A group represents a chapter when the pages directly inside it all
    belong to the same one. That is how an already-sorted chapter is
    recognised on a later run, so newly converted pages join it instead of
    starting a second group with the same heading.
    """
    if found is None:
        found = {}
    for kind, a, b in tree:
        if kind != "group":
            continue
        numbers = {chapter_of(stem) for k, stem, _ in b if k == "page"}
        numbers.discard(None)
        if len(numbers) == 1:
            found.setdefault(numbers.pop(), b)
        chapter_groups(b, found)
    return found


def find_group(tree, title, depth=0):
    """Locate a group by its title. Returns (children, depth) or None."""
    for kind, a, b in tree:
        if kind != "group":
            continue
        if a == title:
            return b, depth
        found = find_group(b, title, depth + 1)
        if found:
            return found
    return None


def append_destination(tree, requested):
    """Where newly appended pages should go.

    Named explicitly by grouping.append_to when set. Otherwise, a contents
    tree that is a single group and nothing else is a book container -- the
    shape you get when everything lives under one module -- so append
    inside it rather than beside it. Anything else appends at the top.
    """
    if requested:
        found = find_group(tree, requested)
        if found:
            return found[0], found[1], requested
        return tree, -1, None            # named group not found; report it

    if len(tree) == 1 and tree[0][0] == "group":
        return tree[0][2], 0, tree[0][1]
    return tree, -1, None


# --------------------------------------------------------------------------
# manifest
# --------------------------------------------------------------------------

MANIFEST_HEAD = """<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="{identifier}"
  xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1"
  xmlns:lom="http://ltsc.ieee.org/xsd/imsccv1p1/LOM/resource"
  xmlns:lomimscc="http://ltsc.ieee.org/xsd/imsccv1p1/LOM/manifest"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1 http://www.imsglobal.org/profile/cc/ccv1p1/ccv1p1_imscp_v1p2_v1p0.xsd http://ltsc.ieee.org/xsd/imsccv1p1/LOM/resource http://www.imsglobal.org/profile/cc/ccv1p1/LOM/ccv1p1_lomresource_v1p0.xsd http://ltsc.ieee.org/xsd/imsccv1p1/LOM/manifest http://www.imsglobal.org/profile/cc/ccv1p1/LOM/ccv1p1_lommanifest_v1p0.xsd">
  <metadata>
    <schema>IMS Common Cartridge</schema>
    <schemaversion>1.1.0</schemaversion>
    <lomimscc:lom>
      <lomimscc:general>
        <lomimscc:title>
          <lomimscc:string>{title}</lomimscc:string>
        </lomimscc:title>
        <lomimscc:description>
          <lomimscc:string>{description}{version_note}</lomimscc:string>
        </lomimscc:description>
        <lomimscc:language>{language}</lomimscc:language>
{keywords}      </lomimscc:general>
      <lomimscc:lifeCycle>
        <lomimscc:contribute>
          <lomimscc:date>
            <lomimscc:dateTime>{modified}</lomimscc:dateTime>
          </lomimscc:date>
        </lomimscc:contribute>
      </lomimscc:lifeCycle>
    </lomimscc:lom>
  </metadata>
  <organizations>
    <organization identifier="org-{identifier}" structure="rooted-hierarchy">
      <item identifier="root">
"""

MANIFEST_TAIL = """      </item>
    </organization>
  </organizations>
  <resources>
{resources}  </resources>
</manifest>
"""


# --------------------------------------------------------------------------
# content prefix
# --------------------------------------------------------------------------

# How much of the title to keep in the prefix. Long enough to be
# recognisable in a file manager, short enough that the longest page name
# plus its media directory stays well inside any path limit.
PREFIX_TITLE_CHARS = 32

# Hex characters of the digest. Ten gives roughly one chance in two
# million of a collision across a thousand books, and one in two hundred
# across a hundred thousand.
PREFIX_DIGEST_CHARS = 10


def content_prefix(project, settings):
    """The directory every file in the package sits under, or "".

    Two halves, doing two jobs. The title makes the folder mean something
    to whoever opens the LMS file manager. The digest makes it unique, and
    it has to be the digest rather than the title because two books can
    perfectly well share a title -- and it is taken over the identifier,
    which IMS asks to be globally unique, because hashing anything less
    would only redistribute the ambiguity rather than remove it.

    The version is deliberately absent. A prefix that changed between
    releases would relocate every file, turning each update into a fresh
    import that the instructor has to reconcile by hand.
    """
    if not settings.get("prefix_content"):
        return ""
    explicit = (settings.get("prefix") or "").strip().strip("/")
    if explicit:
        return explicit

    identifier = str(project.get("identifier") or "")
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
    digest = digest[:PREFIX_DIGEST_CHARS]

    readable = re.sub(r"[^A-Za-z0-9._-]+", "-",
                      str(project.get("title") or "")).strip("-._").lower()
    readable = re.sub(r"-{2,}", "-", readable)[:PREFIX_TITLE_CHARS]
    readable = readable.strip("-._")
    return f"{readable}-{digest}" if readable else digest


def under_prefix(prefix, ref):
    """A package-relative path, inside the prefix when there is one."""
    return f"{prefix}/{ref}" if prefix else ref


def wrapper_title(project, settings, manifest):
    """The wrapper module's name, from the template."""
    template = settings.get("module_title") or "{title}"
    values = {"title": project.get("title") or manifest.get("title") or "",
              "version": manifest.get("version") or "",
              "identifier": project.get("identifier") or ""}
    try:
        return template.format(**values).strip()
    except (KeyError, IndexError, ValueError):
        # A template naming something that does not exist should not take
        # the build down; the module still needs a name.
        return str(values["title"])


def render_items(tree, depth, wrapper=None):
    """The organization tree, optionally inside one wrapper module.

    An LMS does not merge an imported organization with one already in the
    course; it appends. So a re-import always leaves a second copy, and
    the only question is how much of one. Wrapped, it is a single module
    to remove; flat, it is one per chapter.
    """
    pad = "  " * (depth + 4)
    lines = []
    counter = [0]
    if wrapper:
        lines.append(f'{pad}<item identifier="group-book">')
        lines.append(f"{pad}  <title>{xml_escape(wrapper)}</title>")
        pad += "  "

    def emit(nodes, pad):
        for entry in nodes:
            kind, a, b = entry
            if kind == "page":
                title = numbered_title(entry, b or TITLES[a])
                lines.append(f'{pad}<item identifier="item-{ncname(a)}" '
                             f'identifierref="res-{ncname(a)}">')
                lines.append(f"{pad}  <title>{xml_escape(title)}</title>")
                lines.append(f"{pad}</item>")
            else:
                counter[0] += 1
                lines.append(f'{pad}<item identifier="group-{counter[0]}">')
                lines.append(f"{pad}  <title>"
                             f"{xml_escape(numbered_title(entry, a))}</title>")
                emit(b, pad + "  ")
                lines.append(f"{pad}</item>")

    emit(tree, pad)
    if wrapper:
        lines.append(("  " * (depth + 4)) + "</item>")
    return lines


TITLES = {}
PARTS = {}      # piece stem -> (source stem, part number, parent titles)
ROLES = {}      # page stem -> role, for a page that was not split


def build_manifest(config, tree, page_files, common_files):
    """Assemble imsmanifest.xml.

    A note on where the version goes. Full LOM puts it in lifeCycle, but
    the CC 1.1 manifest profile restricts LifeCycle.Type to `contribute`
    alone and declares no `version` element anywhere -- so a manifest with
    one does not validate. Until v0.2 this emitted one, and every cartridge
    this project has ever produced was invalid because of it. LMSes accept
    it, which is why nobody noticed.

    There is nowhere legal to put a version, so it is appended to the
    description, which General.Type does permit. Lossy, and visible on
    import, but honest; a silently invalid manifest is neither.
    """
    manifest = config["manifest"]
    keywords = ""
    for word in manifest.get("keywords") or []:
        keywords += ("        <lomimscc:keyword>\n"
                     f"          <lomimscc:string>{xml_escape(str(word))}"
                     "</lomimscc:string>\n"
                     "        </lomimscc:keyword>\n")

    head = MANIFEST_HEAD.format(
        identifier=xml_escape(manifest["identifier"]),
        title=xml_escape(manifest["title"]),
        version_note=(" (version " + xml_escape(str(manifest.get("version", "")))
                      + ")") if manifest.get("version") else "",
        description=xml_escape(manifest.get("description", "")),
        language=xml_escape(manifest.get("language", "en")),
        version=xml_escape(str(manifest.get("version", "1.0"))),
        modified=manifest.get("modified") or date.today().isoformat(),
        keywords=keywords,
    )

    organization = config.get("organization") or {}
    project = config.get("project") or {}
    wrapper = (wrapper_title(project, organization, manifest)
               if organization.get("wrap_in_module") else None)
    items = render_items(tree, 0, wrapper)

    # Every href is package-relative, so prefixing them all moves the whole
    # tree together and no relative reference inside a page changes.
    prefix = config.get("content_prefix") or ""

    resources = []
    if common_files:
        resources.append('    <resource identifier="common_files" '
                         'type="webcontent">')
        for ref in common_files:
            resources.append('      <file href="'
                             + href_of(under_prefix(prefix, ref)) + '"/>')
        resources.append("    </resource>")

    for stem in flatten_pages(tree):
        page = href_of(under_prefix(prefix, stem + ".html"))
        resources.append(f'    <resource identifier="res-{ncname(stem)}" '
                         f'type="webcontent" href="{page}">')
        resources.append(f'      <file href="{page}"/>')
        for ref in page_files[stem]:
            resources.append('      <file href="'
                             + href_of(under_prefix(prefix, ref)) + '"/>')
        if common_files:
            resources.append('      <dependency identifierref="common_files"/>')
        resources.append("    </resource>")

    # Convert the templates to CRLF *before* substituting, otherwise the
    # already-CRLF item and resource blocks pick up a second carriage
    # return and the file ends up with blank lines everywhere.
    body = CRLF.join(items) + CRLF
    tail = MANIFEST_TAIL.replace("\n", CRLF).format(
        resources=CRLF.join(resources) + CRLF)
    return head.replace("\n", CRLF) + body + tail


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Build an IMS Common Cartridge manifest from HTML pages.")
    parser.add_argument("--pages", default=None,
                        help="read the pages from this directory rather "
                             "than from --dir, which keeps the configuration, "
                             "the sample, the manifest, and the archive; "
                             "convert.py passes an html target's output_dir")
    parser.add_argument("-d", "--dir", default=".",
                        help="directory holding the pages (default: .)")
    parser.add_argument("-c", "--config", default=None,
                        help=f"config file (default: <dir>/{CONFIG_NAME})")
    parser.add_argument("-o", "--output", default=None,
                        help="manifest to write (default: <dir>/imsmanifest.xml)")
    parser.add_argument("--zip", action="store_true",
                        help="also build the .imscc archive")
    parser.add_argument("--includeallhtml", action="store_true",
                        help="append pages that the config does not list, "
                             "and write an updated sample config")
    parser.add_argument("--toc", metavar="PDF-OR-EPUB",
                        help="take the order and the headings from this "
                             "PDF's bookmark outline or EPUB's navigation "
                             "document, which is the book's own table of "
                             "contents. Overrides contents in "
                             "the config; the result is written to the "
                             "sample for review.")
    parser.add_argument("--no-validate", action="store_true",
                        help="skip checking the manifest against the "
                             "Common Cartridge schemas")
    parser.add_argument("--target", default=None, metavar="NAME",
                        help="which package to build, when the config "
                             "defines more than one")
    parser.add_argument("--allow-unknown-keys", action="store_true",
                        help="report settings this version does not know "
                             "about instead of refusing them, and keep "
                             "them if the config is rewritten")
    parser.add_argument("--init", action="store_true",
                        help="write a sample config and stop")
    parser.add_argument("--check", action="store_true",
                        help="validate only; write nothing")
    parser.add_argument("--emit-conversion-config", metavar="DIR",
                        # Retired in v0.2: conversion reads its own config
                        # now, so the packaging tool no longer has to be
                        # present for a folder of documents to convert.
                        help="write the conversion-time settings (header and "
                             "footer sources, spacer rules) into DIR for "
                             "convert.py to read, then stop. Writes only into "
                             "DIR, never into the content directory.")
    args = parser.parse_args()

    base = args.dir
    config_path = args.config or os.path.join(base, CONFIG_NAME)
    sample_path = os.path.join(base, SAMPLE_NAME)
    output_path = args.output or os.path.join(base, "imsmanifest.xml")

    if args.emit_conversion_config:
        sys.exit("--emit-conversion-config was retired in v0.2. Conversion "
                 "reads its own configuration:\n"
                 "    python3 bin/read-conversion-config.py -d . DIR")

    pages_dir = args.pages or base
    stems = sorted((f[:-5] for f in os.listdir(pages_dir) if f.endswith(".html")),
                   key=natural_key)
    if not stems:
        sys.exit(f"No .html files in {pages_dir}.")

    for stem in stems:
        path = os.path.join(pages_dir, stem + ".html")
        TITLES[stem] = page_title(path, stem)
        origin = page_provenance(path)
        role = page_role(path)
        if role:
            ROLES[stem] = role
        if origin:
            PARTS[stem] = origin
            # A source with no page of its own still has a title, and its
            # pieces carry it; that is what a group over them is called.
            if origin[4] and origin[0] not in TITLES:
                TITLES[origin[0]] = origin[4]

    # ---- configuration ---------------------------------------------------
    config, notes, fatal = {}, [], []
    schema, project_schema = load_schemas()
    resolved, documents, target = None, [], None

    legacy_path = os.path.join(base, LEGACY_NAME)
    if os.path.isfile(legacy_path) and not os.path.isfile(config_path):
        sys.exit(
            f"{legacy_path} is the v0.1 configuration and is no longer "
            f"read.\n"
            f"Split it into {PROJECT_NAME}, conversion.yaml, and "
            f"{CONFIG_NAME} with:\n"
            f"    python3 util/migrate-config.py -d {base}\n"
            "It reports what it will do first with --dry-run, and never "
            "changes the original.")

    if not args.init:
        documents = config_documents(base, config_path)
        if documents:
            target = choose_target(documents, args.target)
            try:
                resolved = oerconfig.resolve(
                    schema, project_schema, documents, target=target,
                    allow_unknown=args.allow_unknown_keys)
            except oerconfig.ConfigError as exc:
                sys.exit(str(exc))
            for warning in resolved.warnings:
                print(f"WARNING: {warning}", file=sys.stderr)
            config = legacy_view(resolved, target)

            # Two packages of the same format both derive the same
            # filename from the identifier. Reporting it costs one loop
            # and saves a build that silently overwrites another.
            names = oerconfig.target_names(documents)
            if len(names) > 1:
                seen = {}
                for other in names:
                    try:
                        settled = oerconfig.resolve(
                            schema, project_schema, documents, target=other,
                            allow_unknown=args.allow_unknown_keys)
                    except oerconfig.ConfigError:
                        continue
                    archive = archive_name(settled.settings,
                                           settled.project, other)
                    if archive in seen:
                        fatal.append(
                            f"packages {seen[archive]} and {other} would "
                            f"both be written to {archive}. Give at least "
                            "one of them its own filename.")
                    seen[archive] = other
        else:
            fatal.append(f"{config_path} not found.")
    else:
        notes.append("Generated by --init.")

    if resolved is None:
        # Nothing to resolve, but the code below still needs the schema's
        # own defaults so that a sample can be written from them.
        resolved = oerconfig.resolve(schema, project_schema, [])
        if not config:
            config = legacy_view(resolved, None)

    # No `or` fallbacks here. The configuration library has already
    # applied the schema's defaults, so an empty value at this point is
    # one somebody chose, and `x or default` would quietly overrule it --
    # which is precisely the bug that used to make `unsorted_title: ""`
    # come out as "Unsorted".
    grouping = config.get("grouping") or {}
    back_matter = [str(r) for r in grouping.get("back_matter", [])]
    unsorted_title = str(grouping.get("unsorted_title", ""))

    # Computed from every page, not only appended ones, so the block lands
    # in the sample whenever the ordering was worked out by the script --
    # which is exactly when knowing about unplaced roles is useful.
    unknown_roles = unrecognised_roles(stems, back_matter)

    manifest = config.get("manifest") or {}
    guessed = default_config(stems)["manifest"]
    for key in REQUIRED:
        if not manifest.get(key):
            # --init is explicitly asking for a starting point, so a missing
            # required value there is expected rather than an error.
            if not args.init:
                fatal.append(f"manifest.{key} is required and has no default.")
            else:
                notes.append(f"manifest.{key} must be filled in by hand.")
            manifest[key] = guessed[key]
    for key, value in guessed.items():
        if key not in manifest or manifest[key] in (None, ""):
            manifest[key] = value
            if key not in REQUIRED:
                notes.append(f"manifest.{key} defaulted to {value!r}.")
    config["manifest"] = manifest

    # ---- contents --------------------------------------------------------
    available = set(stems)
    used, problems = set(), []

    guessed_contents = False
    if config.get("contents"):
        tree = walk_contents(config["contents"], available, used, problems)
    elif args.toc:
        # Nothing curated and an outline to follow: start empty so every
        # page counts as unplaced and the outline orders all of them.
        tree = []
    else:
        notes.append("contents was missing, so the order below is a guess "
                     "from the filenames. Check it.")
        problems.append("contents not specified; using guessed order.")
        guessed_contents = True
        tree = walk_contents(guess_contents(stems, back_matter, TITLES, PARTS, ROLES),
                             available, used, problems)

    extra = [s for s in stems if s not in used]
    if args.toc and not extra:
        # The outline orders only pages the config does not place, and the
        # config placed all of them -- usually because the first run's
        # guessed sample was adopted as packaging.yaml before --toc was
        # tried. Saying nothing here left the outline silently unused and
        # the sample looking exactly like the config.
        print(f"WARNING: {os.path.basename(args.toc)} was not used. contents "
              "already places every page, and the outline orders only pages "
              "it does not.", file=sys.stderr)
        print("  To order the whole book from the outline, remove the "
              "contents block from packaging.yaml and run --toc again; the "
              "sample it writes is the outline's order, with the book's own "
              "chapter titles.", file=sys.stderr)
        notes.append(f"{os.path.basename(args.toc)} was not used: contents "
                     "already placed every page. Remove contents and run "
                     "--toc again to order from the outline.")
    if extra:
        if args.toc:
            # The outline supplies the order for pages the config did not
            # already place. What the config placed stays exactly where it
            # was put -- an outline is a source of ordering, not a reason
            # to discard a curated tree.
            destination, dest_depth, dest_title = append_destination(
                tree, grouping.get("append_to"))

            from_pdf, placed, unmapped = contents_from_outline(
                args.toc, extra, TITLES, PARTS)
            destination.extend(
                walk_contents(from_pdf, available, used, problems))

            leftover = [s for s in extra if s not in used]
            if leftover:
                destination.extend(walk_contents(
                    [{"title": unsorted_title,
                      "items": guess_contents(leftover, back_matter,
                                              TITLES, PARTS, ROLES)}],
                    available, used, problems))

            print(f"Read {os.path.basename(args.toc)}: {len(placed)} of "
                  f"{len(extra)} unplaced page(s) ordered from the outline.")
            if unmapped:
                print(f"WARNING: {len(unmapped)} outline entry/entries "
                      "matched no page:", file=sys.stderr)
                for entry in unmapped[:20]:
                    print(f"  {entry}", file=sys.stderr)
                if len(unmapped) > 20:
                    print(f"  ... and {len(unmapped) - 20} more",
                          file=sys.stderr)

            where = f" inside \"{dest_title}\"" if dest_title else ""
            note = (f"{len(placed)} page(s) ordered from "
                    f"{os.path.basename(args.toc)}{where}")
            if leftover:
                note += (f"; {len(leftover)} the outline does not mention are "
                         f"under \"{unsorted_title}\"")
            notes.append(note + ".")
        elif args.includeallhtml:
            # A page whose filename names its chapter can be placed
            # without guessing, so place it: into the chapter's existing
            # group if there is one, otherwise into a new chapter group at
            # the top level. Only pages with no detectable chapter are left
            # for the reader to sort.
            destination, dest_depth, dest_title = append_destination(
                tree, grouping.get("append_to"))
            if grouping.get("append_to") and dest_title is None:
                problems.append(
                    f"grouping.append_to names \"{grouping['append_to']}\", "
                    "which is not a group in contents; appending at the top "
                    "level instead")
            if dest_depth >= 2:
                problems.append(
                    f"appending into \"{dest_title}\" puts new chapters more "
                    "than three levels deep; some LMSs flatten this")

            existing = chapter_groups(tree)
            joining, created, unplaceable = {}, [], []

            for stem in extra:
                number = chapter_of(stem)
                if number is None:
                    unplaceable.append(stem)
                elif number in existing:
                    joining.setdefault(number, []).append(stem)
                else:
                    created.append(stem)

            joined = 0
            for number, stems_for_chapter in sorted(joining.items()):
                # Ordered among themselves before being appended, so a
                # chapter's back matter still reads in the configured order
                # rather than the order the filenames happened to sort in.
                for stem in sorted(stems_for_chapter,
                                   key=lambda s: within_chapter_key(
                                       s, back_matter)):
                    existing[number].append(("page", stem, None))
                    used.add(stem)
                    joined += 1

            # Pages ordered within each new chapter; the chapter groups
            # themselves land in number order after what is already there.
            if created:
                new_tree = walk_contents(
                    guess_contents(created, back_matter, TITLES, PARTS, ROLES),
                    available, used, problems)
                destination.extend(new_tree)

            if unplaceable:
                destination.extend(walk_contents(
                    [{"title": unsorted_title,
                      "items": sorted(unplaceable, key=natural_key)}],
                    available, used, problems))

            where = f" inside \"{dest_title}\"" if dest_title else ""
            summary = []
            if joined:
                summary.append(f"{joined} added to chapters already in "
                               "contents")
            if created:
                summary.append(f"{len(created)} grouped into new "
                               f"chapters{where}")
            if unplaceable:
                summary.append(f"{len(unplaceable)} under "
                               f"\"{unsorted_title}\"{where} (no chapter in "
                               "the filename)")
            notes.append(f"{len(extra)} page(s) were not listed in contents: "
                         + "; ".join(summary) + ".")
            if unknown_roles:
                print("NOTE: these page roles are not in the configured "
                      "back-matter order, so they sort last within their "
                      "chapter:", file=sys.stderr)
                for role in unknown_roles:
                    print(f"  {role}", file=sys.stderr)
                print(f"  A block to paste is at the end of {SAMPLE_NAME}.",
                      file=sys.stderr)
        else:
            print(f"WARNING: {len(extra)} .html file(s) are not listed in "
                  "contents and were left out:", file=sys.stderr)
            for stem in extra:
                print(f"  {stem}.html", file=sys.stderr)
            print("  Use --includeallhtml to append them.", file=sys.stderr)

    for problem in problems:
        print(f"WARNING: {problem}", file=sys.stderr)

    # ---- referenced files ------------------------------------------------
    common_files = [str(f) for f in (config.get("common_files") or [])]
    page_files, missing = {}, []

    for stem in flatten_pages(tree):
        refs = []
        for ref in page_references(os.path.join(pages_dir, stem + ".html"),
                                   pages_dir):
            if ref[:-5] in available and ref.endswith(".html"):
                continue        # a link to another page: its own resource
            if ref in common_files:
                continue        # declared once, in the shared resource
            if not os.path.isfile(os.path.join(pages_dir, ref)):
                missing.append((stem, ref))
                continue
            refs.append(ref)
        page_files[stem] = refs

    for ref in common_files:
        if not os.path.isfile(os.path.join(pages_dir, ref)):
            missing.append(("common_files", ref))

    if missing:
        print(f"ERROR: {len(missing)} referenced file(s) are not on disk:",
              file=sys.stderr)
        for stem, ref in missing:
            print(f"  {stem} -> {ref}", file=sys.stderr)
        fatal.append("referenced files are missing.")

    # ---- act on what we found -------------------------------------------
    if fatal or args.init:
        sample = dict(config)
        # The tree already holds the best order available -- the config's,
        # the outline's with leftovers appended, or the guess -- so the
        # sample says what a run would do. Building the guess afresh here
        # threw the outline away on exactly the first run --toc is for.
        sample["contents"] = contents_from_tree(tree) if tree else \
            guess_contents(stems, back_matter, TITLES, PARTS, ROLES)
        settled, sample_targets = sample_inputs(
            resolved, documents, target, sample["contents"])
        dump_sample(sample, sample_path, notes, unknown_roles,
                    schema, project_schema, settled, sample_targets)
        for problem in fatal:
            print(f"ERROR: {problem}", file=sys.stderr)
        print(f"\nWrote {sample_path}.", file=sys.stderr)
        print(f"Edit it, rename it to {CONFIG_NAME}, and run again.",
              file=sys.stderr)
        print("Every setting is in there with its description, so nothing "
              "you had set is lost by renaming it.", file=sys.stderr)
        return 0 if args.init else 1

    if config.get("numbering"):
        number_tree(tree, TITLES)
    xml = build_manifest(config, tree, page_files, common_files)

    prefix = config.get("content_prefix") or ""
    file_list = ["imsmanifest.xml"]
    for ref in common_files:
        file_list.append(ref)
    for stem in flatten_pages(tree):
        file_list.append(stem + ".html")
        file_list.extend(page_files[stem])
    # Two pages sharing an image list it twice; the archive holds it once.
    file_list = list(dict.fromkeys(file_list))

    pages = len(list(flatten_pages(tree)))
    assets = len(file_list) - pages - 1

    if args.check:
        print(f"OK: {pages} page(s), {assets} asset(s). Nothing written.")
        return 0

    with open(output_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(xml)
    list_path = os.path.join(base, FILE_LIST_NAME)
    with open(list_path, "w", encoding="utf-8") as handle:
        if prefix:
            # zip -@ names each member after the path it reads, so this
            # list cannot build a prefixed package. Saying so is better
            # than letting someone build a flat one that looks right and
            # collides with every other book on import.
            handle.write(
                "# Every file this package contains, as it sits on disk.\n"
                f"# Inside the package they all go under {prefix}/ "
                "(imsmanifest.xml excepted),\n"
                "# which `zip -@` cannot do: it names each member after "
                "the path it read.\n"
                "# Build the archive with --zip instead.\n")
        handle.write("\n".join(file_list) + "\n")

    print(f"Wrote {output_path}: {pages} page(s), {assets} asset(s).")
    print(f"Wrote {list_path}.")

    # Validate before building anything from it. A manifest that does not
    # conform still gets written, so it can be looked at, but the archive
    # is not built from it: shipping an invalid cartridge is the failure
    # this is here to prevent, and every cartridge produced before v0.2
    # was invalid without anyone noticing.
    if not args.no_validate and validate_manifest is not None:
        if not validate_manifest.validate(output_path, quiet=True):
            print("", file=sys.stderr)
            print("The manifest was written so you can inspect it, but no "
                  "archive was built from it.", file=sys.stderr)
            print("  Re-run with --no-validate to build one anyway.",
                  file=sys.stderr)
            return 1

    if (extra and args.includeallhtml) or args.toc or guessed_contents:
        settled, sample_targets = sample_inputs(
            resolved, documents, target, contents_from_tree(tree))
        dump_sample(config, sample_path, notes, unknown_roles,
                    schema, project_schema, settled, sample_targets)
        print(f"Wrote {sample_path} for review.")

    cartridge = os.path.join(base, config["manifest"]["cartridge"])
    if args.zip:
        with zipfile.ZipFile(cartridge, "w", zipfile.ZIP_DEFLATED) as archive:
            # imsmanifest.xml sits at the package root whatever else
            # does; Common Cartridge requires it there.
            archive.write(output_path, "imsmanifest.xml")
            for ref in file_list[1:]:
                archive.write(os.path.join(pages_dir, ref),
                              under_prefix(prefix, ref))
        size = os.path.getsize(cartridge) / 1048576
        print(f"Wrote {cartridge} ({size:.1f} MB, {len(file_list)} entries).")
    else:
        print("\nTo build the cartridge:")
        if prefix:
            # The manual route cannot produce a prefixed layout, so it is
            # not offered as though it could.
            print("  re-run this script with --zip")
            print(f"  ({FILE_LIST_NAME} lists the files, but zip -@ cannot "
                  f"place them under {prefix}/)")
        else:
            print(f"  cd {pages_dir} && zip -q -X "
                  f"{config['manifest']['cartridge']} -@ < {FILE_LIST_NAME}")
            print("  (or re-run this script with --zip)")

    return 0


def shell_quote(value):
    return "'" + str(value).replace("'", "'\\''") + "'"


if __name__ == "__main__":
    sys.exit(main())
