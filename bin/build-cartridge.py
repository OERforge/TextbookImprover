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
directory of HTML rather than only on output from convert.sh.

Configuration lives in imsmanifest.yaml. Everything that can be derived
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
import html as html_module
import os
import re
import sys
import zipfile
from datetime import date

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("PyYAML is required.  Install it with:\n"
             "    sudo apt install python3-yaml\n"
             "  or: pip3 install pyyaml")

CONFIG_NAME = "imsmanifest.yaml"
SAMPLE_NAME = "imsmanifest-sample.yaml"
FILE_LIST_NAME = "cartridge-files.txt"

CRLF = "\r\n"

# src/href values that are not local files.
EXTERNAL = ("http://", "https://", "//", "data:", "mailto:", "tel:", "#",
            "javascript:")

SRC_RE = re.compile(r'\b(?:src|href)\s*=\s*"([^"]+)"', re.I)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)

# The order back matter appears in within a chapter. Different books use
# different names for these -- Statistics has "chapter-review" and
# "homework", Economics has "key-concepts-and-summary" and "problems" -- so
# this is the union of both, and anything unrecognised is sorted after the
# names listed here and reported rather than silently misplaced.
#
# Override it in the config with:
#   grouping:
#     back_matter: [key-terms, summary, exercises]
BACK_MATTER_ORDER = [
    "key-terms",
    "chapter-review",
    "key-concepts-and-summary",
    "formula-review",
    "practice",
    "self-check-questions",
    "review-questions",
    "critical-thinking-questions",
    "bringing-it-together-practice",
    "homework",
    "bringing-it-together-homework",
    "problems",
    "references",
    "solutions",
]

REQUIRED = ["identifier", "title"]

# Outline entries that name no page of their own.
TOC_SKIP = {"contents", "table-of-contents", "chapter-objectives",
            "learning-objectives", "about-openstax"}


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def natural_key(text):
    """Sort key where runs of digits compare numerically.

    Plain sort puts chapter 10 between chapters 1 and 2, which scrambles a
    book. This keeps 1-1, 1-2, 2-1, 10-1 in the order a reader expects.
    """
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", text)]


def chapter_of(stem):
    """Chapter number this page belongs to, or None.

    Two shapes carry it: a numeric prefix ("12-3-...", "12-key-terms") and
    a chapter opener page ("chapter-12"). Everything else -- appendices,
    preface, index -- has no chapter.
    """
    m = re.match(r"^chapter-(\d+)$", stem)
    if m:
        return int(m.group(1))
    m = re.match(r"^(\d+)-", stem)
    if m:
        return int(m.group(1))
    return None


def within_chapter_key(stem, back_matter):
    """Sort key for one page inside its chapter.

    Opener, then introduction, then numbered sections in order, then back
    matter in the configured order, then anything unrecognised.
    """
    if re.match(r"^chapter-\d+$", stem):
        return (0, 0, "")

    tail = re.sub(r"^\d+-", "", stem)

    # "1-introduction" and "1-introduction-to-choice-in-a-world-of-scarcity"
    # are the same thing under different naming conventions.
    if tail == "introduction" or tail.startswith("introduction-to-"):
        return (1, 0, "")

    m = re.match(r"^(\d+)-", tail)
    if m:
        return (2, int(m.group(1)), "")

    if tail in back_matter:
        return (3, back_matter.index(tail), "")

    # Unrecognised: after the known back matter, alphabetically, and
    # reported so the name can be added to the configured order.
    return (4, 0, tail)


def unrecognised_roles(stems, back_matter):
    """Chapter pages whose role name is not in the configured order."""
    found = set()
    for stem in stems:
        if chapter_of(stem) is None:
            continue
        if within_chapter_key(stem, back_matter)[0] == 4:
            found.add(re.sub(r"^\d+-", "", stem))
    return sorted(found)


def slugify(text):
    """Filename form of an outline title.

    OpenStax names its files after its headings, so "Key Concepts and
    Summary" is "key-concepts-and-summary" and "Self-Check Questions" is
    "self-check-questions". Deriving the name rather than listing known
    headings is what lets one rule serve books that use different words
    for the same sections.
    """
    text = clean_title(text).lower()
    text = re.sub(r"['\u2019\u2018`]", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def clean_title(text):
    """Unescape entities and drop the invisible characters Word leaves."""
    text = html_module.unescape(text)
    text = re.sub(r"[\u200b\u200c\u200d\ufeff\u00ad]", "", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return " ".join(text.split())


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
    return stem.replace("-", " ").replace("_", " ").title()


def page_references(path, base_dir):
    """Local files a page refers to, in document order, deduplicated."""
    with open(path, encoding="utf-8", errors="replace") as handle:
        markup = handle.read()

    found, seen = [], set()
    for raw in SRC_RE.findall(markup):
        ref = html_module.unescape(raw).strip()
        if not ref or ref.startswith(EXTERNAL):
            continue
        ref = ref.split("#", 1)[0].split("?", 1)[0]
        if not ref or ref in seen:
            continue
        seen.add(ref)
        found.append(ref)
    return found


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------

def contents_from_pdf(path, stems, titles):
    """Build a contents tree from a PDF's bookmark outline.

    The outline of a textbook PDF is its table of contents, in the order
    the book actually uses -- which no filename heuristic can match. Pages
    are found by deriving a filename from each heading, so this works for
    any book whose files are named after its headings rather than only for
    ones whose section names are known in advance.

    Returns (tree, placed, unmapped). Anything the outline does not cover
    is left for the caller to append as usual.
    """
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

    available = set(stems)
    placed, unmapped = set(), []

    def take(*candidates):
        for name in candidates:
            if name and name in available and name not in placed:
                placed.add(name)
                return name
        return None

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

        return take(slug)

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
        if chapter is None:
            own = take(slugify(title))
            if own is None and letter:
                own = by_prefix(letter.group(1).lower() + "-")

        if own:
            tree.append(own)
            while i < len(entries) and entries[i][0] > 0:
                i += 1
            continue

        items = []
        while i < len(entries) and entries[i][0] > 0:
            child = resolve_child(entries[i][1], chapter)
            if child:
                items.append(child)
            elif slugify(entries[i][1]) not in TOC_SKIP:
                unmapped.append(entries[i][1])
            i += 1

        if items:
            tree.append({"title": title, "items": items})
        elif chapter is not None:
            unmapped.append(title)

    return tree, placed, unmapped


FRONT_MATTER = ("frontmatter", "front-matter", "preface", "about", "titlepage")
BACK_MATTER_PAGES = ("index", "references", "bibliography", "glossary",
                     "solutions", "answer-key")


# Words that stay lowercase inside a derived heading unless they lead it.
MINOR_WORDS = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "of",
               "on", "or", "the", "to", "with", "versus", "vs"}


def title_from_slug(slug):
    """Turn "choice-in-a-world-of-scarcity" into "Choice in a World of
    Scarcity" -- readable enough for a heading you are going to review."""
    words = [w for w in slug.split("-") if w]
    out = []
    for index, word in enumerate(words):
        if index > 0 and word in MINOR_WORDS:
            out.append(word)
        elif len(word) <= 3 and word.isupper():
            out.append(word)
        else:
            out.append(word[:1].upper() + word[1:])
    return " ".join(out)


def chapter_heading(number, pages, titles):
    """Best available heading for a chapter group.

    An introduction page named after its subject gives the chapter's real
    title -- "Introduction to Choice in a World of Scarcity" is chapter 2's
    heading with three words removed. That is preferred over a
    "chapter-12" page, whose title varies by book: sometimes the chapter
    opener, sometimes the answer key for it.
    """
    for page in pages:
        if not re.match(rf"^{number}-introduction", page):
            continue

        # The page's own title when it has a real one.
        m = re.match(r"^introduction to (?:the\s+)?(.+)$",
                     titles.get(page, ""), re.I)
        if m:
            return f"Chapter {number} {m.group(1)}"

        # Otherwise the filename, which carries the same words. Pages whose
        # source has no H1 end up titled after the file, so the title is no
        # better a source than the name itself.
        m = re.match(rf"^{number}-introduction-to-(?:the-)?(.+)$", page)
        if m:
            return f"Chapter {number} {title_from_slug(m.group(1))}"

    opener = next((p for p in pages if re.match(r"^chapter-\d+$", p)), None)
    if opener and titles.get(opener):
        return titles[opener]

    return f"Chapter {number}"


def guess_contents(stems, back_matter=None, titles=None):
    """Best-effort contents tree from filenames alone.

    Chapter grouping only fires when the filenames actually encode it.
    "BC-01".."BC-16" have no internal structure and stay flat; OpenStax
    names like "12-3-the-f-distribution" and "chapter-12" group.

    Detection is by shape, not by vocabulary: anything with a numeric
    chapter prefix belongs to that chapter, whatever the rest of the name
    says. Only the *order* of back matter within a chapter depends on
    knowing the names, and unrecognised ones sort last rather than
    preventing the grouping.
    """
    back_matter = back_matter or BACK_MATTER_ORDER
    titles = titles or {}

    chapters = {}
    loose = []
    for stem in stems:
        number = chapter_of(stem)
        if number is None:
            loose.append(stem)
        else:
            chapters.setdefault(number, []).append(stem)

    # Not enough structure to be worth grouping.
    grouped_pages = sum(len(v) for v in chapters.values())
    if len(chapters) < 2 or grouped_pages < max(3, len(stems) // 4):
        return sorted(stems, key=natural_key)

    front = [s for s in loose if s.lower().startswith(FRONT_MATTER)]
    tail = [s for s in loose
            if s.lower().startswith(BACK_MATTER_PAGES) and s not in front]
    middle = [s for s in loose if s not in front and s not in tail]

    tree = sorted(front, key=natural_key)

    for number in sorted(chapters):
        pages = sorted(chapters[number],
                       key=lambda s: within_chapter_key(s, back_matter))
        tree.append({"title": chapter_heading(number, pages, titles),
                     "items": pages})

    tree.extend(sorted(middle, key=natural_key))
    tree.extend(sorted(tail, key=natural_key))
    return tree


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


def dump_sample(config, path, notes, unknown_roles=None):
    """Write a commented sample config. Deterministic: no timestamps."""
    manifest = config.get("manifest", {})
    lines = [
        "# Sample configuration written by build-cartridge.py.",
        "#",
        "# Rename this file to imsmanifest.yaml and edit it. Every value",
        "# below is either taken from your existing config or a default,",
        "# so renaming it unchanged reproduces exactly this build.",
        "#",
    ]
    lines += [f"# {note}" for note in notes]
    lines += [
        "",
        "manifest:",
        f"  identifier: {yaml_scalar(manifest.get('identifier', 'course'))}",
        f"  title: {yaml_scalar(manifest.get('title', 'Course'))}",
        f"  description: {yaml_scalar(manifest.get('description', ''))}",
        f"  version: {yaml_scalar(str(manifest.get('version', '1.0')))}",
        f"  language: {yaml_scalar(manifest.get('language', 'en'))}",
        f"  cartridge: {yaml_scalar(manifest.get('cartridge', 'course.imscc'))}",
    ]
    keywords = manifest.get("keywords") or []
    if keywords:
        lines.append("  keywords:")
        lines += [f"    - {yaml_scalar(k)}" for k in keywords]
    else:
        lines.append("  keywords: []")

    for key in ("header", "footer"):
        if config.get(key):
            lines.append("")
            lines.append(f"{key}: {yaml_scalar(config[key])}")

    if config.get("common_files"):
        lines.append("")
        lines.append("common_files:")
        lines += [f"  - {yaml_scalar(f)}" for f in config["common_files"]]

    if config.get("images"):
        lines.append("")
        lines.append("images:")
        for key, value in config["images"].items():
            lines.append(f"  {key}: {yaml_scalar(value)}")

    if unknown_roles:
        # Written commented out and in the order they were found, so the
        # list can be reordered and uncommented rather than typed from
        # scratch. Different books use different words for these sections,
        # which is why there is no useful default to fall back on.
        lines.append("")
        lines.append("# These page roles are not in the back-matter order,")
        lines.append("# so they currently sort last within their chapter.")
        lines.append("# Uncomment and put them in the order they should")
        lines.append("# appear, then re-run.")
        lines.append("#")
        lines.append("# grouping:")
        lines.append("#   back_matter:")
        for role in unknown_roles:
            lines.append(f"#     - {role}")

    lines.append("")
    lines.append("contents:")
    lines += render_contents(config.get("contents", []), 0)
    lines.append("")

    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


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

def walk_contents(nodes, available, used, problems, depth=0):
    """Normalise the configured tree into (kind, ...) records."""
    out = []
    for node in nodes:
        if isinstance(node, str):
            node = {"page": node}
        if not isinstance(node, dict):
            problems.append(f"contents entry is not a page or a group: {node!r}")
            continue

        if "items" in node:
            children = walk_contents(node["items"], available, used,
                                     problems, depth + 1)
            if depth >= 2:
                problems.append(
                    f"group '{node.get('title', '')}' nests more than three "
                    "levels deep; some LMSs flatten this")
            out.append(("group", node.get("title", ""), children))
            continue

        stem = str(node.get("page", "")).strip()
        if stem.endswith(".html"):
            stem = stem[:-5]
        if not stem:
            problems.append("contents entry has no page name")
            continue
        if stem not in available:
            problems.append(f"page listed in contents but not on disk: "
                            f"{stem}.html")
            continue
        if stem in used:
            problems.append(f"page listed more than once: {stem}.html")
            continue
        used.add(stem)
        out.append(("page", stem, node.get("title")))
    return out


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


def flatten_pages(tree):
    for kind, a, b in tree:
        if kind == "page":
            yield a
        else:
            yield from flatten_pages(b)


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
          <lomimscc:string>{description}</lomimscc:string>
        </lomimscc:description>
        <lomimscc:language>{language}</lomimscc:language>
{keywords}      </lomimscc:general>
      <lomimscc:lifeCycle>
        <lomimscc:version>
          <lomimscc:string>{version}</lomimscc:string>
        </lomimscc:version>
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


def render_items(tree, depth):
    pad = "  " * (depth + 4)
    lines = []
    counter = [0]

    def emit(nodes, pad):
        for kind, a, b in nodes:
            if kind == "page":
                title = b or TITLES[a]
                lines.append(f'{pad}<item identifier="item-{a}" '
                             f'identifierref="res-{a}">')
                lines.append(f"{pad}  <title>{xml_escape(title)}</title>")
                lines.append(f"{pad}</item>")
            else:
                counter[0] += 1
                lines.append(f'{pad}<item identifier="group-{counter[0]}">')
                lines.append(f"{pad}  <title>{xml_escape(a)}</title>")
                emit(b, pad + "  ")
                lines.append(f"{pad}</item>")

    emit(tree, pad)
    return lines


TITLES = {}


def build_manifest(config, tree, page_files, common_files):
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
        description=xml_escape(manifest.get("description", "")),
        language=xml_escape(manifest.get("language", "en")),
        version=xml_escape(str(manifest.get("version", "1.0"))),
        modified=manifest.get("modified") or date.today().isoformat(),
        keywords=keywords,
    )

    items = render_items(tree, 0)

    resources = []
    if common_files:
        resources.append('    <resource identifier="common_files" '
                         'type="webcontent">')
        for ref in common_files:
            resources.append(f'      <file href="{xml_escape(ref)}"/>')
        resources.append("    </resource>")

    for stem in flatten_pages(tree):
        resources.append(f'    <resource identifier="res-{stem}" '
                         f'type="webcontent" href="{stem}.html">')
        resources.append(f'      <file href="{stem}.html"/>')
        for ref in page_files[stem]:
            resources.append(f'      <file href="{xml_escape(ref)}"/>')
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
    parser.add_argument("--toc", metavar="PDF",
                        help="take the order and the headings from this "
                             "PDF's bookmark outline, which is the book's "
                             "own table of contents. Overrides contents in "
                             "the config; the result is written to the "
                             "sample for review.")
    parser.add_argument("--init", action="store_true",
                        help="write a sample config and stop")
    parser.add_argument("--check", action="store_true",
                        help="validate only; write nothing")
    parser.add_argument("--emit-conversion-config", metavar="DIR",
                        help="write the conversion-time settings (header and "
                             "footer sources, spacer rules) into DIR for "
                             "convert.sh to read, then stop. Writes only into "
                             "DIR, never into the content directory.")
    args = parser.parse_args()

    base = args.dir
    config_path = args.config or os.path.join(base, CONFIG_NAME)
    sample_path = os.path.join(base, SAMPLE_NAME)
    output_path = args.output or os.path.join(base, "imsmanifest.xml")

    if args.emit_conversion_config:
        return emit_conversion_config(config_path,
                                      args.emit_conversion_config)

    stems = sorted((f[:-5] for f in os.listdir(base) if f.endswith(".html")),
                   key=natural_key)
    if not stems:
        sys.exit(f"No .html files in {base}.")

    for stem in stems:
        TITLES[stem] = page_title(os.path.join(base, stem + ".html"), stem)

    # ---- configuration ---------------------------------------------------
    config, notes, fatal = {}, [], []

    if os.path.isfile(config_path) and not args.init:
        with open(config_path, encoding="utf-8") as handle:
            config = yaml.safe_load(handle) or {}
        if not isinstance(config, dict):
            sys.exit(f"{config_path} does not contain a mapping.")
    else:
        if args.init:
            notes.append("Generated by --init.")
        else:
            fatal.append(f"{config_path} not found.")

    grouping = config.get("grouping") or {}
    back_matter = [str(r) for r in (grouping.get("back_matter")
                                    or BACK_MATTER_ORDER)]
    unsorted_title = str(grouping.get("unsorted_title") or "Unsorted")

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
        tree = walk_contents(guess_contents(stems, back_matter, TITLES),
                             available, used, problems)

    extra = [s for s in stems if s not in used]
    if extra:
        if args.toc:
            # The outline supplies the order for pages the config did not
            # already place. What the config placed stays exactly where it
            # was put -- an outline is a source of ordering, not a reason
            # to discard a curated tree.
            destination, dest_depth, dest_title = append_destination(
                tree, grouping.get("append_to"))

            from_pdf, placed, unmapped = contents_from_pdf(
                args.toc, extra, TITLES)
            destination.extend(
                walk_contents(from_pdf, available, used, problems))

            leftover = [s for s in extra if s not in used]
            if leftover:
                destination.extend(walk_contents(
                    [{"title": unsorted_title,
                      "items": sorted(leftover, key=natural_key)}],
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
                    guess_contents(created, back_matter, TITLES),
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
        for ref in page_references(os.path.join(base, stem + ".html"), base):
            if ref[:-5] in available and ref.endswith(".html"):
                continue        # a link to another page: its own resource
            if ref in common_files:
                continue        # declared once, in the shared resource
            if not os.path.isfile(os.path.join(base, ref)):
                missing.append((stem, ref))
                continue
            refs.append(ref)
        page_files[stem] = refs

    for ref in common_files:
        if not os.path.isfile(os.path.join(base, ref)):
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
        sample["contents"] = (config.get("contents")
                              or guess_contents(stems, back_matter, TITLES))
        if args.includeallhtml or not config.get("contents"):
            sample["contents"] = guess_contents(stems, back_matter, TITLES)
        dump_sample(sample, sample_path, notes, unknown_roles)
        for problem in fatal:
            print(f"ERROR: {problem}", file=sys.stderr)
        print(f"\nWrote {sample_path}.", file=sys.stderr)
        print(f"Edit it, rename it to {CONFIG_NAME}, and run again.",
              file=sys.stderr)
        return 0 if args.init else 1

    xml = build_manifest(config, tree, page_files, common_files)

    file_list = ["imsmanifest.xml"]
    for ref in common_files:
        file_list.append(ref)
    for stem in flatten_pages(tree):
        file_list.append(stem + ".html")
        file_list.extend(page_files[stem])

    pages = len(list(flatten_pages(tree)))
    assets = len(file_list) - pages - 1

    if args.check:
        print(f"OK: {pages} page(s), {assets} asset(s). Nothing written.")
        return 0

    with open(output_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(xml)
    list_path = os.path.join(base, FILE_LIST_NAME)
    with open(list_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(file_list) + "\n")

    print(f"Wrote {output_path}: {pages} page(s), {assets} asset(s).")
    print(f"Wrote {list_path}.")

    if (extra and args.includeallhtml) or args.toc or guessed_contents:
        dump_sample({**config, "contents": contents_from_tree(tree)},
                    sample_path, notes, unknown_roles)
        print(f"Wrote {sample_path} for review.")

    cartridge = os.path.join(base, config["manifest"]["cartridge"])
    if args.zip:
        with zipfile.ZipFile(cartridge, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(output_path, "imsmanifest.xml")
            for ref in file_list[1:]:
                archive.write(os.path.join(base, ref), ref)
        size = os.path.getsize(cartridge) / 1048576
        print(f"Wrote {cartridge} ({size:.1f} MB, {len(file_list)} entries).")
    else:
        print("\nTo build the cartridge:")
        print(f"  cd {base} && zip -q -X "
              f"{config['manifest']['cartridge']} -@ < {FILE_LIST_NAME}")
        print("  (or re-run this script with --zip)")

    return 0


def emit_conversion_config(config_path, out_dir):
    """Hand convert.sh the settings that affect conversion.

    Kept here so there is one config file and one parser, but written into
    a directory convert.sh owns -- the content directory is never touched.
    A block scalar in the YAML is written out as a Markdown file; a plain
    string is treated as a path and copied through as-is.
    """
    config = {}
    if os.path.isfile(config_path):
        with open(config_path, encoding="utf-8") as handle:
            config = yaml.safe_load(handle) or {}

    os.makedirs(out_dir, exist_ok=True)
    images = config.get("images") or {}
    captions = config.get("captions") or {}

    def prefixes(key, fallback):
        value = captions.get(key, fallback)
        if isinstance(value, (list, tuple)):
            return ",".join(str(v) for v in value)
        return str(value)

    def resolve(key):
        """Return a path to Markdown for header/footer, or ''."""
        value = config.get(key)
        if not value:
            return ""
        text = str(value)
        # A single line with no newline that names an existing file is a
        # path; anything else is inline Markdown.
        candidate = os.path.join(os.path.dirname(config_path) or ".", text.strip())
        if "\n" not in text.strip() and os.path.isfile(candidate):
            return os.path.abspath(candidate)
        path = os.path.join(out_dir, key + ".md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text.rstrip() + "\n")
        return os.path.abspath(path)

    settings = {
        "HEADER_MD": resolve("header"),
        "FOOTER_MD": resolve("footer"),
        "SPACER_BELOW": str(images.get("spacer_below", "0")),
        "STRIP_SPACER": "true" if images.get("strip_spacer") else "false",
        "SPACER_LOG_NAME": str(images.get("spacer_log", "spacer-images.csv")),
        "ALT_MAX_CHARS": str(images.get("alt_max_chars", "120")),
        "TABLE_LABEL_PREFIXES": prefixes("table_prefixes", "Table"),
        "FIGURE_LABEL_PREFIXES": prefixes("figure_prefixes", "Figure"),
    }
    with open(os.path.join(out_dir, "settings.sh"), "w",
              encoding="utf-8") as handle:
        for key, value in settings.items():
            handle.write(f"{key}={shell_quote(value)}\n")
    return 0


def shell_quote(value):
    return "'" + str(value).replace("'", "'\\''") + "'"


def contents_from_tree(tree):
    """Turn the resolved tree back into plain YAML-shaped data."""
    out = []
    for kind, a, b in tree:
        if kind == "page":
            out.append(a if not b else {"page": a, "title": b})
        else:
            out.append({"title": a, "items": contents_from_tree(b)})
    return out


if __name__ == "__main__":
    sys.exit(main())
