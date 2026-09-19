#!/usr/bin/env python3
"""
build-epub.py -- assemble a book's pages into one EPUB3.

    build-epub.py                  # build every epub3 target in conversion.yaml
    build-epub.py --target epub    # build one of them
    build-epub.py --if-declared    # build them, and be silent if there are none

Reads the filtered intermediates convert.sh writes (<page>.filtered.json)
rather than the HTML pages. Pandoc's HTML reader keeps a cell's scope
attribute but not the element, so a row header read back from a page
would arrive as <td scope="row">; the intermediate still has everything
the filter did. It never runs the filter itself: the filter is per-page
by design, and running it over the assembled book would match no sidecar
declaration.

The book's structure comes from project.contents, the same tree the
cartridge organization is built from, or from the packager's filename
guess when there is none. A group -- a chapter, a unit, whatever the
author calls it -- becomes a heading, a page a heading at its depth, and the page's own headings continue below it, so
the table of contents shows ranks -- chapter, section -- at the same
depth whatever file each came from.

The package document's accessibility claims are computed from what this
run found rather than declared once and left to go stale: the EPUB says
its images have alternative text only when they all do.

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
import copy
import json
import os
import re
import shutil
import zipfile
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))

try:
    import notes as notes_lib
    import oerconfig
except ImportError:
    sys.exit("Cannot find the configuration library. It should be in a "
             "lib/ directory beside bin/.")
from bookcontents import (  # noqa: E402
    guess_contents, walk_contents, flatten_pages, natural_key, stem_title,
    number_tree, numbered_title, is_generated, toc_blocks,
)

CONFIG_NAME = "conversion.yaml"
PROJECT_NAME = "project.yaml"
INTERMEDIATE = ".filtered.json"
PAGE_CSS = os.path.join(HERE, "page.css")

# Attributes whose value is a list of ids, kept in step when ids are
# prefixed. headers is what a cell uses to name its header cells when
# scope cannot express the relationship.
ID_LIST_ATTRIBUTES = {"headers", "aria-labelledby", "aria-describedby"}


def page_id(stem):
    """The id a page's heading gets, and the prefix its ids take. A stem
    is a file name and may hold a space; an id may not."""
    return "page-" + re.sub(r"[^\w.-]+", "-", stem)


# --------------------------------------------------------------------------
# reading the intermediates
# --------------------------------------------------------------------------

def page_stems(base):
    return sorted((f[:-len(INTERMEDIATE)] for f in os.listdir(base)
                   if f.endswith(INTERMEDIATE)), key=natural_key)


def load_page(base, stem):
    with open(os.path.join(base, stem + INTERMEDIATE), encoding="utf-8") as fh:
        return json.load(fh)


def stringify(node):
    """The text of an inline tree, as Pandoc's stringify would give it."""
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
        return stringify(node.get("c", []))
    if isinstance(node, list):
        return "".join(stringify(child) for child in node)
    return ""


def meta_text(meta, key):
    value = meta.get(key)
    if not value:
        return ""
    if value.get("t") == "MetaString":
        return value["c"]
    return " ".join(stringify(value.get("c", [])).split())


def page_title(doc, stem):
    """The page's title from its metadata, falling back to the filename.

    With promote_h1_to_title in effect the filter has moved the page's
    heading here, which is why the intermediate usually opens without one.
    """
    return meta_text(doc.get("meta", {}), "title") or stem_title(stem)


def inlines(text):
    """Str and Space inlines for a plain string."""
    out = []
    for index, word in enumerate(text.split()):
        if index:
            out.append({"t": "Space"})
        out.append({"t": "Str", "c": word})
    return out


def header(level, content, identifier):
    return {"t": "Header", "c": [level, [identifier, [], []], content]}


# --------------------------------------------------------------------------
# rewriting a page for its place in the book
# --------------------------------------------------------------------------

def is_attr(value):
    """Pandoc's Attr is the only three-element list that starts with a
    string and continues with a list of strings and a list of pairs."""
    return (isinstance(value, list) and len(value) == 3
            and isinstance(value[0], str)
            and isinstance(value[1], list)
            and all(isinstance(c, str) for c in value[1])
            and isinstance(value[2], list)
            and all(isinstance(kv, list) and len(kv) == 2
                    and isinstance(kv[0], str) and isinstance(kv[1], str)
                    for kv in value[2]))


def prefix_ids(node, prefix, pages=()):
    """Give every id in a page the page's prefix, and every link to one
    the same, so that two pages with a "Key Terms" heading do not collide
    once they share a book. Pandoc rewrites #id links to the chapter file
    holding the id by its first occurrence, so a collision would send a
    link to the wrong page without a word.

    A link to another page of the book -- <stem>.html or <stem>.html#id,
    which is how split-pages.py links the pieces of a source -- becomes
    a link into the book the same way, so it resolves to that page's
    chapter file instead of to a file the EPUB does not contain."""
    if isinstance(node, dict):
        if node.get("t") == "Link":
            target = node["c"][2]
            url = target[0]
            if url.startswith("#") and len(url) > 1:
                target[0] = "#" + prefix + url[1:]
            elif url.endswith(".html") and url[:-5] in pages:
                target[0] = "#" + page_id(url[:-5])
            elif ".html#" in url and url.split(".html#", 1)[0] in pages:
                stem, fragment = url.split(".html#", 1)
                target[0] = "#" + page_id(stem) + "--" + fragment
        for value in node.values():
            prefix_ids(value, prefix, pages)
    elif is_attr(node):
        if node[0]:
            node[0] = prefix + node[0]
        for pair in node[2]:
            if pair[0] in ID_LIST_ATTRIBUTES and pair[1].strip():
                pair[1] = " ".join(prefix + token
                                   for token in pair[1].split())
    elif isinstance(node, list):
        for value in node:
            prefix_ids(value, prefix, pages)


def strip_comments(node):
    """Raw HTML comments, dropped. A Markdown source may carry one -- a
    citation beside an epigraph -- and a comment holding "--" is fatal in
    XHTML, which is what an EPUB is made of. A comment says nothing to a
    reader either way."""
    if isinstance(node, dict):
        for key, value in list(node.items()):
            if isinstance(value, list):
                node[key] = [v for v in value if not is_comment(v)]
                for v in node[key]:
                    strip_comments(v)
            elif isinstance(value, dict):
                strip_comments(value)
    elif isinstance(node, list):
        node[:] = [v for v in node if not is_comment(v)]
        for v in node:
            strip_comments(v)


def is_comment(node):
    return (isinstance(node, dict) and node.get("t") in ("RawInline",
                                                          "RawBlock")
            and isinstance(node.get("c"), list) and len(node["c"]) == 2
            and node["c"][0] in ("html", "html5", "html4")
            and node["c"][1].lstrip().startswith("<!--"))


def shift_headers(node, by):
    if isinstance(node, dict):
        if node.get("t") == "Header":
            node["c"][0] = min(6, node["c"][0] + by)
        for value in node.values():
            shift_headers(value, by)
    elif isinstance(node, list):
        for value in node:
            shift_headers(value, by)


def opens_with_h1(blocks):
    return bool(blocks) and blocks[0].get("t") == "Header" \
        and blocks[0]["c"][0] == 1


def count_images(node, found):
    """Tally images and the ones with no alternative text.

    An image the filter marked decorative -- alt="" with
    aria-hidden="true" (role="presentation" in older intermediates) --
    has been described, as having nothing to say. An image with an empty
    alt and no such marker has not.
    """
    if isinstance(node, dict):
        if node.get("t") == "Image":
            attr, alt, _ = node["c"]
            found["images"] += 1
            decorative = ["aria-hidden", "true"] in attr[2] \
                or ["role", "presentation"] in attr[2]
            if not decorative and not stringify(alt).strip():
                found["without_alt"] += 1
        elif node.get("t") == "Math":
            found["math"] += 1
        elif node.get("t") == "Note":
            found["notes"] += 1
        for value in node.values():
            count_images(value, found)
    elif isinstance(node, list):
        for value in node:
            count_images(value, found)


class Assembly:
    """The book being built: blocks, and what was learned building them."""

    def __init__(self, base, pages, tree=(), titles=None):
        self.base = base
        self.tree = tree
        self.titles = titles or {}
        self.book_pages = frozenset(pages)   # stems a link may point at
        self.blocks = []
        self.depth = 1              # deepest heading level a page sits at
        self.pages = []
        self.found = {"images": 0, "without_alt": 0, "math": 0, "notes": 0}
        self.groups = {}             # page stem -> (group key, group title)
        self.notes_placed = False    # the Notes chapter, where contents put it

    def add_tree(self, tree, depth=1):
        for index, entry in enumerate(tree):
            kind, a, b = entry
            if is_generated(entry):
                self.add_generated(entry, depth)
                continue
            if kind == "page" and a == "notes" and not os.path.exists(
                    os.path.join(self.base, "notes" + INTERMEDIATE)):
                # The Notes chapter, placed where contents lists it and
                # filled after the writer runs.
                self.blocks.append(header(depth, inlines(b or "Notes"),
                                          page_id("notes")))
                self.notes_placed = True
                continue
            if depth == 1:
                # A top-level group is a notes group; so is a top-level
                # page, on its own.
                key = f"top-{index}"
                if kind == "group":
                    for stem in flatten_pages([(kind, a, b)]):
                        self.groups[stem] = (key, a)
                else:
                    doc = load_page(self.base, a)
                    self.groups[a] = (key, b or page_title(doc, a))
            if kind == "group":
                # A group whose first page bears its own title -- a
                # heading's introduction, placed under it by the split --
                # opens with that page's content rather than repeating the
                # heading. The group takes the page's id so links to the
                # page still land.
                opener = None
                if b and b[0][0] == "page" and not is_generated(b[0]) \
                        and b[0][1] != "notes":
                    stem, override = b[0][1], b[0][2]
                    doc = load_page(self.base, stem)
                    if (override or page_title(doc, stem)) == a:
                        opener = stem
                self.blocks.append(header(
                    depth, inlines(numbered_title(entry, a)),
                    page_id(opener) if opener else group_id(a, depth, self)))
                if opener:
                    self.add_page(opener, None, depth, heading=False)
                self.add_tree(b[1:] if opener else b, depth + 1)
            else:
                self.add_page(a, b, depth, number=entry.number)

    def add_generated(self, entry, depth):
        """A page the run writes: the contents page, as blocks."""
        kind, name, title = entry
        if entry.generate == "toc":
            self.blocks.append(header(depth, inlines(title), page_id(name)))
            self.blocks.extend(toc_blocks(
                self.tree, self.titles, lambda stem: "#" + page_id(stem)))
            self.pages.append((name, title, depth))

    def add_page(self, stem, title_override, depth, heading=True,
                 number=None):
        doc = load_page(self.base, stem)
        blocks = copy.deepcopy(doc["blocks"])
        title = title_override or page_title(doc, stem)
        if number:
            title = f"{number} {title}"
        prefix = page_id(stem) + "--"
        strip_comments(blocks)
        prefix_ids(blocks, prefix, self.book_pages)
        # A page's own headings continue below its entry. The page's title
        # heading is usually in its metadata, moved there by the filter;
        # when the body still opens with one, that is the page's heading
        # and it is used rather than doubled.
        shift_headers(blocks, depth - 1)
        if not heading:
            pass                    # the group's heading stands for it
        elif opens_with_h1(doc["blocks"]):
            blocks[0]["c"][1][0] = page_id(stem)
            blocks[0]["c"][2] = inlines(title) if (title_override or number) \
                else blocks[0]["c"][2]
        else:
            blocks.insert(0, header(depth, inlines(title), page_id(stem)))
        count_images(blocks, self.found)
        self.depth = max(self.depth, depth)
        self.pages.append((stem, title, depth))
        self.blocks.extend(blocks)

    def add_single_page(self, stem, title_override):
        """A contents tree that is one page is the book itself: its title
        is the book's, its headings are the book's, and nothing sits
        above them."""
        doc = load_page(self.base, stem)
        blocks = copy.deepcopy(doc["blocks"])
        strip_comments(blocks)
        prefix_ids(blocks, page_id(stem) + "--", self.book_pages)
        count_images(blocks, self.found)
        self.pages.append((stem, title_override or page_title(doc, stem), 1))
        self.blocks.extend(blocks)


def group_id(title, depth, assembly):
    """An id for a group heading that no page can produce and no two
    groups share: page ids start with page-, this with group-."""
    slug = "".join(c if c.isalnum() else "-" for c in title.lower())
    slug = "-".join(part for part in slug.split("-") if part) or "untitled"
    ordinal = sum(1 for b in assembly.blocks
                  if b.get("t") == "Header" and b["c"][1][0].startswith("group-"))
    return f"group-{ordinal + 1}-{slug}"


# --------------------------------------------------------------------------
# metadata
# --------------------------------------------------------------------------

def meta_string(text):
    return {"t": "MetaString", "c": str(text)}


def meta_list(items):
    return {"t": "MetaList", "c": [meta_string(i) for i in items]}


def accessibility_claims(found):
    """What the package document may say about this build.

    Pandoc's own defaults assert textual access, sufficient on its own,
    with alternative text present -- for every EPUB it writes. A catalog
    acts on those words, so each is made only when this run can stand
    behind it.
    """
    modes = ["textual"]
    if found["images"]:
        modes.append("visual")
    alt_complete = found["without_alt"] == 0
    # accessModeSufficient lists sets, one entry each. "textual" alone says
    # a reader who cannot see the page misses nothing, which is true only
    # when every image has been described (or marked decorative).
    sufficient = ["textual"] if alt_complete else ["textual,visual"]
    features = ["structuralNavigation", "tableOfContents", "readingOrder"]
    if found["images"] and alt_complete:
        features.append("alternativeText")
    if found["math"]:
        features.append("MathML")
    return {
        "accessModes": modes,
        "accessModeSufficient": sufficient,
        "accessibilityFeatures": features,
        # No video, audio, animation, or script comes out of a Word file.
        "accessibilityHazards": ["none"],
    }


def derived_summary(found):
    parts = ["Headings and a table of contents for navigation; data tables "
             "carry captions and header cells."]
    if found["images"]:
        if found["without_alt"] == 0:
            parts.append(f"All {found['images']} images have alternative "
                         "text or are marked decorative.")
        else:
            parts.append(f"{found['without_alt']} of {found['images']} "
                         "images have no alternative text yet.")
    if found["math"]:
        parts.append("Equations are MathML.")
    return " ".join(parts)


def book_metadata(project, resolved, found, base):
    meta = {
        "title": meta_string(project["title"]),
        "lang": meta_string(project["language"]),
        # The book's own identifier rather than a fresh UUID per build, so
        # a reading system recognises a rebuilt edition as the same book.
        "identifier": meta_string(project["identifier"]),
    }
    if project.get("publisher"):
        meta["publisher"] = meta_string(project["publisher"])
    if project.get("description"):
        meta["description"] = meta_string(project["description"])
    authors = [str(a) for a in (project.get("authors") or []) if str(a)]
    if authors:
        meta["creator"] = meta_list(authors)
    for key, value in accessibility_claims(found).items():
        meta[key] = meta_list(value)
    summary = str(resolved["epub.accessibility_summary"] or "").strip()
    meta["accessibilitySummary"] = meta_string(summary or
                                               derived_summary(found))
    cover = str(resolved["epub.cover_image"] or "").strip()
    if cover:
        path = cover if os.path.isabs(cover) else os.path.join(base, cover)
        if not os.path.isfile(path):
            sys.exit(f"epub.cover_image is set to {cover}, which does not "
                     f"exist (looked at {os.path.abspath(path)}).")
        meta["cover-image"] = meta_string(os.path.abspath(path))
        alt = str(resolved["epub.cover_alt"] or "").strip()
        meta["cover-alt"] = meta_string(alt or f"Cover of {project['title']}")
    return meta


# --------------------------------------------------------------------------
# running Pandoc
# --------------------------------------------------------------------------

def pandoc_default(argument):
    return subprocess.run(["pandoc", argument], capture_output=True,
                          text=True, check=True).stdout


def chapter_template(work):
    """Pandoc's epub3 template with each chapter titled by its heading.

    The writer fills $pagetitle$ with the chapter file's name, so every
    chapter's <title> reads "ch002.xhtml" -- a WCAG 2.4.2 failure that
    Ace reports. The chapter's own title variable holds its heading.
    """
    template = pandoc_default("-Depub3")
    # The chapter <title> is left as the writer fills it -- the file name
    # -- and rewritten from the chapter's heading once the archive
    # exists (retitle_chapters). $title$ here would render a heading's
    # <em> or <sup> inside <title>, which XHTML forbids, and the writer
    # offers no plain-text form of a chapter's heading.
    # The cover is an SVG holding the image, with no text alternative at
    # all: a screen reader meets the book with a silent page. Give the
    # SVG a name, and a title element for readers that look there.
    svg = re.search(r'<svg [^>]*viewBox="0 0 \$cover-image-width\$ '
                    r'\$cover-image-height\$"[^>]*>', template)
    if svg:
        opened = svg.group(0)
        template = template.replace(
            opened,
            opened[:-1] + ' role="img" aria-label="$cover-alt$">'
            "\n<title>$cover-alt$</title>", 1)
    else:
        print("WARNING: Pandoc's epub3 template has changed its cover "
              "page; the cover will have no accessible name.",
              file=sys.stderr)
    path = os.path.join(work, "epub3.template")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(template)
    return path


NOTE = re.compile(r'(<aside epub:type="footnote"[^>]*\bid="fn(\d+)"[^>]*>)'
                  r'(.*?)(</aside>)', re.S)


def number_notes(text):
    """A number at the start of each footnote and a return link at its
    end, as Pandoc's HTML writer gives them.

    The EPUB writer writes each note as an aside with epub:type
    "footnote" and nothing else: a reading system that pops notes up on
    tap needs no number, and one that lists them at the end of the
    section leaves the reader with anonymous paragraphs. Numbers restart
    per chapter file, as the references do.
    """
    count = 0

    def fix(match):
        nonlocal count
        opening, number, body, closing = match.groups()
        if 'class="footnote-number"' in body:
            return match.group(0)
        count += 1
        body = re.sub(r"<p\b([^>]*)>",
                      r'<p\1><span class="footnote-number">%s.</span> ' % number,
                      body, count=1)
        back = (' <a href="#fnref%s" class="footnote-back" '
                'role="doc-backlink" aria-label="Back to reference %s">'
                '\u21a9\ufe0e</a>' % (number, number))
        last = body.rfind("</p>")
        body = body[:last] + back + body[last:] if last >= 0 else body + back
        return opening + body + closing

    return NOTE.sub(fix, text), count


def retitle_chapters(path):
    """Give each chapter file a <title> that is its heading's text, and
    its footnotes their numbers.

    Pandoc titles every chapter file by its file name ("ch002.xhtml"), a
    WCAG 2.4.2 failure on every page and what Ace reports first. The
    archive is rewritten in place, mimetype first and stored as the
    container rules require.
    """
    heading = re.compile(r"<h[1-6]\b[^>]*>(.*?)</h[1-6]>", re.S)
    title = re.compile(r"<title>.*?</title>", re.S)
    tmp = path + ".tmp"
    retitled = 0
    with zipfile.ZipFile(path) as zin, \
            zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "mimetype":
                zout.writestr(info, data, compress_type=zipfile.ZIP_STORED)
                continue
            if info.filename.endswith(".xhtml") and "/text/" in info.filename:
                text = data.decode("utf-8")
                found = heading.search(text)
                if found:
                    plain = " ".join(re.sub(r"<[^>]+>", "", found.group(1))
                                     .split())
                    if plain:
                        text = title.sub("<title>" + plain + "</title>",
                                         text, count=1)
                        retitled += 1
                text, _ = number_notes(text)
                data = text.encode("utf-8")
            zout.writestr(info, data)
    os.replace(tmp, path)
    return retitled


def arrange_epub_notes(path, assembly, numbering, placement):
    """notes.numbering and notes.placement, applied to the chapter files.

    Each chapter file opens with the section the writer made of its
    heading, whose id says what it is: page-<stem>, group-N-..., or
    book-notes. Links between chapter files are by file name, since they
    share a directory."""
    with zipfile.ZipFile(path) as archive:
        names = sorted(n for n in archive.namelist()
                       if "/text/ch" in n and n.endswith(".xhtml"))
        texts = {n: archive.read(n).decode("utf-8") for n in names}
    pages, notes_page = [], None
    for name in names:
        text = texts[name]
        first = re.search(r'<section id="([^"]+)"', text)
        ident = first.group(1) if first else ""
        short = name.rsplit("/", 1)[1]
        if ident == page_id("notes"):
            notes_page = notes_lib.Page(short, text, "notes", "Notes", "xhtml")
            continue
        stem = None
        for candidate, (key, title) in assembly.groups.items():
            if ident == page_id(candidate) or ident.startswith(
                    page_id(candidate) + "--"):
                stem = candidate
                break
        if stem is None:
            continue                    # a group heading's own chapter
        key, title = assembly.groups[stem]
        pages.append(notes_lib.Page(short, text, key, title, "xhtml"))
    changed = notes_lib.arrange(pages, numbering, placement, notes_page)
    if not changed:
        return
    updates = {"EPUB/text/" + p.name: p.text for p in changed}
    for name in names:
        texts[name] = updates.get(name, texts[name])
    tmp = path + ".tmp"
    with zipfile.ZipFile(path) as zin, \
            zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "mimetype":
                zout.writestr(info, data, compress_type=zipfile.ZIP_STORED)
                continue
            if info.filename in updates:
                data = updates[info.filename].encode("utf-8")
            elif info.filename.endswith(".opf"):
                # A note that moved may have taken the file's only MathML
                # with it, or brought some; the manifest says per file.
                data = mark_mathml(data.decode("utf-8"), texts).encode("utf-8")
            zout.writestr(info, data)
    os.replace(tmp, path)


def mark_mathml(opf, texts):
    """The mathml property on each text item, as its content now is."""
    def fix(match):
        tag = match.group(0)
        href = re.search(r'href="([^"]+)"', tag).group(1)
        has_math = "<math" in texts.get("EPUB/" + href, "")
        props = re.search(r'properties="([^"]*)"', tag)
        tokens = props.group(1).split() if props else []
        tokens = [t for t in tokens if t != "mathml"]
        if has_math:
            tokens.append("mathml")
        if props:
            if tokens:
                return tag.replace(props.group(0),
                                   'properties="%s"' % " ".join(tokens))
            return tag.replace(" " + props.group(0), "")
        if tokens:
            return tag.replace("<item ", '<item properties="mathml" ', 1)
        return tag
    return re.sub(r'<item [^>]*href="text/[^"]+\.xhtml"[^>]*/>', fix, opf)


def stylesheet(work):
    """Pandoc's EPUB stylesheet followed by ours. --css replaces the
    default rather than adding to it."""
    path = os.path.join(work, "book.css")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(pandoc_default("--print-default-data-file=epub.css"))
        fh.write("\n\n/* From TextbookImprover's page.css */\n")
        with open(PAGE_CSS, encoding="utf-8") as page_css:
            fh.write(page_css.read())
    return path


def output_name(resolved, project, target):
    """<identifier>.epub unless the target names a file."""
    name = str(resolved["filename"] or "").strip() \
        or project["identifier"] or target
    if not name.lower().endswith(".epub"):
        name += ".epub"
    return name


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------

def load_documents(base, allow_unknown):
    schema = oerconfig.load_schema(os.path.join(HERE, "schema-conversion.yaml"))
    project_schema = oerconfig.load_schema(
        os.path.join(os.path.dirname(HERE), "lib", "schema-project.yaml"))
    documents = []
    project_path = os.path.join(base, PROJECT_NAME)
    if os.path.isfile(project_path):
        documents.append(oerconfig.load_document(project_path, project_schema))
    config_path = os.path.join(base, CONFIG_NAME)
    if os.path.isfile(config_path):
        documents.append(oerconfig.load_document(config_path, schema))
    return schema, project_schema, documents


def epub_targets(schema, project_schema, documents, requested, allow_unknown):
    names = [requested] if requested else oerconfig.target_names(documents)
    targets = []
    for name in names:
        resolved = oerconfig.resolve(schema, project_schema, documents,
                                     target=name, allow_unknown=allow_unknown)
        if resolved["format"] == "epub3":
            targets.append((name, resolved))
        elif requested:
            sys.exit(f"Target {name} has format: {resolved['format']}, "
                     "not epub3.")
    return targets


# --------------------------------------------------------------------------

def build(base, name, resolved, keep, intermediates=None):
    project = resolved.project
    for warning in resolved.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)

    # Where the filtered intermediates are: the content directory unless
    # a run with several targets put this target's elsewhere. Media paths
    # inside them are relative to the content directory either way.
    pages_dir = intermediates or base
    stems = page_stems(pages_dir)
    if not stems:
        sys.exit(f"No {INTERMEDIATE} files in {pages_dir}: run the "
                 "conversion first.")
    titles, parts, roles = {}, {}, {}
    for stem in stems:
        doc = load_page(pages_dir, stem)
        titles[stem] = page_title(doc, stem)
        if meta_text(doc.get("meta", {}), "page-role"):
            roles[stem] = meta_text(doc["meta"], "page-role")
        source = meta_text(doc.get("meta", {}), "source-page")
        if source:
            # A source with no page of its own -- a chapter whose sections
            # start right under its heading -- still has a title, and its
            # pieces carry it; the group over them is called that.
            if source not in titles and meta_text(doc["meta"], "source-title"):
                titles[source] = meta_text(doc["meta"], "source-title")
            m = re.match(r"(\d+)/", meta_text(doc["meta"], "page-part"))
            parents = [p.get("c", "") for p in
                       doc["meta"].get("page-parents", {}).get("c", [])]
            parts[stem] = (source, int(m.group(1)) if m else None, parents,
                           meta_text(doc["meta"], "page-position"),
                           meta_text(doc["meta"], "source-title"),
                           meta_text(doc["meta"], "page-role"))

    available, used, problems = set(stems), set(), []
    if str(resolved["notes.placement"]) == "book":
        available.add("notes")      # the Notes chapter, written after
    contents = project.get("contents") or []
    if contents:
        tree = walk_contents(contents, available, used, problems,
                             suffix=INTERMEDIATE)
    else:
        problems.append("contents not specified; using guessed order. The "
                        "packager's sample config is the place to fix it.")
        tree = walk_contents(guess_contents(stems, None, titles, parts, roles),
                             available, used, problems, suffix=INTERMEDIATE)
    for problem in problems:
        print(f"WARNING: {problem}", file=sys.stderr)
    unplaced = [s for s in stems if s not in used]
    if unplaced:
        print(f"{len(unplaced)} page(s) are not in project.contents, so "
              "they are not in the EPUB (nor in the cartridge):",
              file=sys.stderr)
        for stem in unplaced:
            print(f"  {stem}", file=sys.stderr)
    placed = list(flatten_pages(tree))
    real = [s for s in placed if s in available]
    if not real:
        sys.exit("No page in project.contents exists on disk; nothing to "
                 "build.")
    choice = str(resolved["numbering"])
    numbered = choice in ("on", "True") if choice in ("on", "off", "True",
                                                        "False") \
        else bool(project["numbering"])
    if numbered:
        number_tree(tree, titles)

    assembly = Assembly(pages_dir, placed, tree, titles)
    if len(tree) == 1 and tree[0][0] == "page":
        assembly.add_single_page(tree[0][1], tree[0][2])
    else:
        assembly.add_tree(tree)
    numbering = str(resolved["notes.numbering"])
    placement = str(resolved["notes.placement"])
    if placement == "book" and assembly.found["notes"] \
            and not assembly.notes_placed:
        # A chapter of its own for the notes, filled after the writer runs.
        assembly.blocks.append(header(1, inlines("Notes"), page_id("notes")))

    document = {
        "pandoc-api-version": load_page(pages_dir,
                                        real[0])["pandoc-api-version"],
        "meta": book_metadata(project, resolved, assembly.found, base),
        "blocks": assembly.blocks,
    }

    out_dir = os.path.join(base, str(resolved["output_dir"] or name))
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, output_name(resolved, project, name))
    toc_depth = int(resolved["epub.toc_depth"])

    work = tempfile.mkdtemp(prefix="build-epub-")
    try:
        book_json = os.path.join(work, "book.json")
        with open(book_json, "w", encoding="utf-8") as fh:
            json.dump(document, fh)
        command = [
            "pandoc", "-f", "json", "-t", "epub3", book_json,
            "-o", os.path.abspath(out_path),
            "--template", chapter_template(work),
            "--css", stylesheet(work),
            # One file per page: split at every level a page heading uses.
            f"--split-level={assembly.depth}",
            f"--toc-depth={toc_depth}",
            "--math-method=mathml",
        ]
        # Run in the content directory: image paths in the intermediates
        # are relative to it.
        result = subprocess.run(command, cwd=base, capture_output=True,
                                text=True)
        if result.stderr.strip():
            print(result.stderr.rstrip(), file=sys.stderr)
        if result.returncode != 0:
            sys.exit(f"pandoc failed building {out_path}.")
        retitle_chapters(out_path)
        if numbering != "page" or placement != "page":
            arrange_epub_notes(out_path, assembly, numbering, placement)
        if keep:
            shutil.copy(book_json, os.path.join(out_dir, "book.json"))
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print(os.path.abspath(out_path))          # for whatever runs next
    found = assembly.found
    claims = accessibility_claims(found)
    print(f"Wrote {out_path}: {len(assembly.pages)} page(s), "
          f"{found['images']} image(s), {found['without_alt']} without "
          "alternative text.", file=sys.stderr)
    print("  Claims: accessMode " + ", ".join(claims["accessModes"])
          + "; sufficient " + "; ".join(claims["accessModeSufficient"])
          + "; features " + ", ".join(claims["accessibilityFeatures"]) + ".",
          file=sys.stderr)
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Assemble the filtered intermediates into an EPUB3.")
    parser.add_argument("-d", "--dir", default=".",
                        help="the content directory (default: .)")
    parser.add_argument("--target", default=None,
                        help="build this epub3 target only")
    parser.add_argument("--intermediates", default=None,
                        help="read the filtered intermediates from here "
                             "rather than from the content directory")
    parser.add_argument("--if-declared", action="store_true",
                        help="exit quietly when no epub3 target is declared")
    parser.add_argument("--keep", action="store_true",
                        help="leave the assembled book.json beside the EPUB")
    parser.add_argument("--allow-unknown-keys", action="store_true",
                        help="report settings this version does not know "
                             "about instead of refusing them")
    args = parser.parse_args()

    if shutil.which("pandoc") is None:
        sys.exit("pandoc is not on the path.")

    try:
        schema, project_schema, documents = load_documents(
            args.dir, args.allow_unknown_keys)
        targets = epub_targets(schema, project_schema, documents,
                               args.target, args.allow_unknown_keys)
    except oerconfig.ConfigError as exc:
        sys.exit(str(exc))

    if not targets:
        if args.if_declared:
            return 0
        print("No target with format: epub3 in conversion.yaml. Declare "
              "one to build an EPUB:", file=sys.stderr)
        print("  targets:\n    epub:\n      format: epub3", file=sys.stderr)
        return 1

    status = 0
    for name, resolved in targets:
        status = build(args.dir, name, resolved, args.keep,
                       args.intermediates) or status
    return status


if __name__ == "__main__":
    sys.exit(main())
