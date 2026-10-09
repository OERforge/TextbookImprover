#!/usr/bin/env python3
"""
build-epub.py -- assemble a book's pages into one EPUB3.

    build-epub.py                  # build every epub3 target in conversion.yaml
    build-epub.py --target epub    # build one of them
    build-epub.py --if-declared    # build them, and be silent if there are none

Reads the filtered intermediates convert.py writes (<page>.filtered.json)
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
from html import escape as html_escape, unescape as html_unescape
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
from bookcontents import number_tree, is_generated, PAGE_TYPES  # noqa: E402
from bookassembly import (  # noqa: E402
    INTERMEDIATE, page_id, load_page, inlines, header, Assembly, meta_text,
    load_documents, targets_of, plan_book, wants_title_page,
    # not used here, but the EPUB tests reach them through this module
    count_images, page_title, prefix_ids, shift_headers,  # noqa: F401
)

PAGE_CSS = os.path.join(HERE, "page.css")

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
        # a reading system recognizes a rebuilt edition as the same book.
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
                    # A formula's TeX, kept in its MathML as an annotation,
                    # is no part of the title's text; and the title is put in
                    # as it is, not as a pattern's template, where a
                    # backslash in it (\pmb) was an escape.
                    words = re.sub(r"<annotation\b.*?</annotation>", "",
                                   found.group(1), flags=re.S)
                    plain = " ".join(re.sub(r"<[^>]+>", "", words).split())
                    if plain:
                        text = title.sub(lambda m: "<title>" + plain + "</title>",
                                         text, count=1)
                        retitled += 1
                text, _ = number_notes(text)
                data = text.encode("utf-8")
            zout.writestr(info, data)
    os.replace(tmp, path)
    return retitled


ID = re.compile(r'\sid="([^"]+)"')
FRAGMENT_LINK = re.compile(r'(<a\b[^>]*?\shref=")#([^"]+)(")')


def link_across_chapters(path):
    """A link to an id in another chapter file, given that file's name,
    and the navigation document's mathml property when its entries hold
    a formula. Returns the number of links fixed.

    Pandoc's writer splits the book into chapter files and gives a link
    the file its target is in, but finds only the ids of a Div, a Header,
    a Table, a Span, a Link, an Image, and raw HTML (getBlockIdent and
    getInlineIdent, Text/Pandoc/Chunks.hs, 3.12): a link to a figure's id
    in another chapter kept its bare #fragment, which epubcheck reports
    as RSC-012 (13 on OpenIntro Statistics, whose chapters cite each
    other's figures). And a heading with a formula puts the formula in the
    navigation document too, whose manifest item then lacks the mathml
    property (OPF-014)."""
    tmp = path + ".tmp"
    where, files = {}, {}
    with zipfile.ZipFile(path) as zin:
        for info in zin.infolist():
            if info.filename.endswith(".xhtml"):
                text = zin.read(info.filename).decode("utf-8")
                files[info.filename] = text
                for ident in set(ID.findall(text)):
                    # An id in two files (each chapter's fn1) names neither.
                    where[ident] = None if ident in where else info.filename
    fixed = 0
    changed = {}
    for name, text in files.items():

        def fix(m):
            nonlocal fixed
            target = where.get(m.group(2))
            if not target or target == name:
                return m.group(0)
            fixed += 1
            relative = os.path.relpath(target, os.path.dirname(name)).replace(os.sep, "/")
            return m.group(1) + relative + "#" + m.group(2) + m.group(3)
        new = FRAGMENT_LINK.sub(fix, text)
        if new != text:
            changed[name] = new
    nav_math = any(name.endswith("nav.xhtml") and "<math" in text for name, text in files.items())
    if not changed and not nav_math:
        return 0
    with zipfile.ZipFile(path) as zin, \
            zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "mimetype":
                zout.writestr(info, data, compress_type=zipfile.ZIP_STORED)
                continue
            if info.filename in changed:
                data = changed[info.filename].encode("utf-8")
            elif nav_math and info.filename.endswith(".opf"):
                data = re.sub(r'(<item\b[^>]*\bproperties=")nav(")', r"\1nav mathml\2",
                              data.decode("utf-8")).encode("utf-8")
            zout.writestr(info, data)
    os.replace(tmp, path)
    return fixed


# A page's division, as the body of its chapter file says it (epub:type),
# from its top-level entry's role in contents; and what a page is (its type
# in contents, or its heading's), with the DPUB-ARIA role, which Ace
# expects beside it (bookcontents.PAGE_TYPES). Only those types, unprefixed
# and naming a whole section, are taken from a heading: an EPUB source's
# headings also carry values like title or z3998:roman, which name the
# heading, and a prefix the package would have to declare.
MATTER = {"front": "frontmatter", "main": "bodymatter", "appendix": "backmatter",
          "back": "backmatter"}
# The pages the landmarks name besides the start of the body and the
# contents, as EPUB's landmarks vocabulary has them.
LANDMARK_TYPES = ("bibliography", "glossary", "index")


def section_type(value):
    """The first of a heading's epub:type values that names a section."""
    return next((v for v in str(value or "").split() if v in PAGE_TYPES), "")


class EpubAssembly(Assembly):
    """The book for the EPUB: as any assembly, and recording where each
    entry of contents starts, with the role contents gives it (its own,
    or its group's) and its type, and what each page's heading says it
    is."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.marks = []           # (index in blocks, depth, role, type, kind of entry)
        self.page_types = {}      # a page's heading id -> the epub:type its heading gave
        self.page_ids = set()     # every page's heading id
        self.contents_id = None   # the generated contents page's heading id

    def before_entry(self, entry, depth):
        kind = "contents" if is_generated(entry) else entry[0]
        self.marks.append((len(self.blocks), depth, getattr(entry, "role", None),
                           getattr(entry, "type", None), kind))

    def mark_notes(self):
        """The Notes chapter, added after contents is placed: back matter."""
        self.marks.append((len(self.blocks), 1, "back", None, "notes"))

    def add_generated(self, entry, depth):
        start = len(self.blocks)
        super().add_generated(entry, depth)
        if entry.generate == "toc" and len(self.blocks) > start:
            self.contents_id = self.blocks[start]["c"][1][0]

    def add_page(self, stem, title_override, depth, heading=True, number=None):
        start = len(self.blocks)
        super().add_page(stem, title_override, depth, heading=heading, number=number)
        self.page_ids.add(page_id(stem))
        doc = load_page(self.base, stem)
        kind = section_type(meta_text(doc.get("meta", {}), "page-type"))
        first = self.blocks[start] if len(self.blocks) > start else None
        if not kind and heading and first and first.get("t") == "Header":
            kind = section_type(dict(first["c"][1][2]).get("epub:type"))
        if kind:
            self.page_types[page_id(stem)] = kind

    def divisions(self):
        """heading id -> (body epub:type, the section's epub:type or "")
        for each heading after the first entry starts.

        The division is the top-level entry's, as numbering and the PDF
        read it: its role, or with none the division the type contents
        gives it implies (a book-level glossary is back matter), the
        contents page's the entry's before it, and otherwise the main
        matter; a type from a heading marks the section and no more. Everything
        inside it is in that division whatever it is: a chapter's Key
        Terms page, a glossary, is in the chapter's. An entry's type is
        what contents says, or what its heading said, on its own heading
        only, the first after its mark; the headings after that, the
        page's own sections, which the writer puts in files of their own
        when groups make the split deeper, have no type. A heading that
        carries an epub:type itself is left as the writer made it."""
        out, previous, division = {}, None, None
        marks = list(self.marks)
        current, starting = None, False
        for index, block in enumerate(self.blocks):
            while marks and marks[0][0] <= index:
                _, depth, role, declared, entry_kind = marks.pop(0)
                current, starting = (depth, role, declared, entry_kind), True
            if current is None or block.get("t") != "Header":
                continue
            ident, _, attributes = block["c"][1]
            if not ident or ident in out:
                continue
            if not starting:
                if "epub:type" not in dict(attributes):
                    out[ident] = (division, "")
                continue
            starting = False
            depth, role, declared, entry_kind = current
            kind = declared or self.page_types.get(ident, "")
            if not kind and role == "appendix" and ident in self.page_ids:
                kind = "appendix"
            if depth == 1:
                # Where the entry is in the book is contents' to say, as
                # numbering, the PDF, and the cartridge read it: its role,
                # or the type contents gives it, not one its heading gives.
                if role:
                    division = MATTER.get(role, "bodymatter")
                elif entry_kind == "contents":
                    # The contents, with no role of its own, is in the
                    # division of the entry before it, or the front matter
                    # when it's first.
                    division = previous or "frontmatter"
                elif ident == page_id("notes"):
                    division = "backmatter"
                else:
                    division = MATTER[PAGE_TYPES.get(declared, ("main",))[0]]
                previous = division
            out[ident] = (division, kind)
        return out


SECTION = re.compile(r'<section\b[^>]*\bid="([^"]+)"[^>]*>')
BODY = re.compile(r'<body\b[^>]*>')
TITLE = re.compile(r"<title>(.*?)</title>", re.S)
LANDMARKS = re.compile(r'\s*<nav epub:type="landmarks"[^>]*>.*?</nav>', re.S)


def mark_divisions(path, divisions, contents_id):
    """Each chapter file's body says the division its page is in, its
    section what the page is, with the ARIA role; and the landmarks name
    the start of the body, the contents page, and a bibliography,
    glossary, or index. Pandoc's writer calls every chapter bodymatter
    unless its heading has one of the epub:type values it lists, and its
    landmarks hold only the title page and cover, and the navigation
    document's contents when it builds them itself (--toc), which also
    puts that document in the spine; this assembly doesn't, so a landmark
    pointing there would name a file outside the spine (epubcheck's
    RSC-011). Returns the number of chapter files changed."""
    tmp = path + ".tmp"
    marked, landmarks, nav_name = 0, [], None
    changed = {}
    with zipfile.ZipFile(path) as zin:
        for name in [i.filename for i in zin.infolist()]:
            if not name.endswith(".xhtml"):
                continue
            text = zin.read(name).decode("utf-8")
            if name.endswith("nav.xhtml"):
                nav_name = name
                continue
            if "/text/" not in name:
                continue
            section = SECTION.search(text)
            if not section:
                continue
            # A file the assembly didn't start (a book of one page, a
            # heading that has an epub:type of its own) keeps the writer's
            # division, and gets the ARIA role its type has.
            matter, kind = divisions.get(section.group(1), (None, ""))
            tag = section.group(0)
            new = text
            if matter:
                new = BODY.sub('<body epub:type="%s">' % matter, new, count=1)
            own = re.search(r'\bepub:type="([^"]*)"', tag)
            retagged = tag
            if own and kind and kind not in own.group(1).split():
                # What contents says the page is outranks its heading.
                retagged = tag.replace(own.group(0), 'epub:type="%s"' % kind, 1)
            elif own:
                kind = section_type(own.group(1))
            extra = ""
            if kind and not own:
                extra += ' epub:type="%s"' % kind
            aria = PAGE_TYPES.get(kind, (None, None))[1] if kind else None
            if aria and " role=" not in tag:
                extra += ' role="%s"' % aria
            if extra or retagged != tag:
                new = new.replace(tag, retagged[:-1] + extra + ">", 1)
            title = TITLE.search(new)
            label = html_unescape(" ".join(re.sub(r"<[^>]+>", "", title.group(1)).split())) \
                if title else ""
            if matter:
                landmarks.append((name, section.group(1), matter, kind, label))
            if new != text:
                changed[name] = new
                marked += 1
        nav = zin.read(nav_name).decode("utf-8") if nav_name else None
    if nav is not None:
        nav_dir = os.path.dirname(nav_name)
        items = []
        existing = LANDMARKS.search(nav)
        if existing:
            items = re.findall(r"<li>\s*(<a\b.*?</a>)\s*</li>", existing.group(0), re.S)
        have = {m for item in items for m in re.findall(r'epub:type="([^"]+)"', item)}

        def link(name, kind, label):
            href = os.path.relpath(name, nav_dir).replace(os.sep, "/")
            return '<a href="%s" epub:type="%s">%s</a>' % (
                html_escape(href), kind, html_escape(label))
        contents = next((entry for entry in landmarks if entry[1] == contents_id), None)
        if contents and "toc" not in have:
            items.append(link(contents[0], "toc", contents[4]))
        body = next((entry for entry in landmarks if entry[2] == "bodymatter"), None)
        if body and "bodymatter" not in have:
            items.append(link(body[0], "bodymatter", body[4]))
        for name, ident, matter, kind, label in landmarks:
            # The book's glossary, not a chapter's Key Terms.
            if kind in LANDMARK_TYPES and kind not in have and matter != "bodymatter":
                items.append(link(name, kind, label))
                have.add(kind)
        if items:
            block = ('\n<nav epub:type="landmarks" id="landmarks" hidden="hidden">\n  <ol>\n'
                     + "".join("    <li>\n      %s\n    </li>\n" % item for item in items)
                     + "  </ol>\n</nav>")
            if existing:
                new_nav = nav[:existing.start()] + block + nav[existing.end():]
            else:
                toc_end = re.search(r'<nav epub:type="toc".*?</nav>', nav, re.S)
                at = toc_end.end() if toc_end else nav.index("</body>")
                new_nav = nav[:at] + block + nav[at:]
            if new_nav != nav:
                changed[nav_name] = new_nav
    if not changed:
        return 0
    with zipfile.ZipFile(path) as zin, \
            zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "mimetype":
                zout.writestr(info, data, compress_type=zipfile.ZIP_STORED)
                continue
            if info.filename in changed:
                data = changed[info.filename].encode("utf-8")
            zout.writestr(info, data)
    os.replace(tmp, path)
    return marked


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

def epub_targets(schema, project_schema, documents, requested, allow_unknown):
    return targets_of(schema, project_schema, documents, requested,
                      allow_unknown, "epub3")


# --------------------------------------------------------------------------

def build(base, name, resolved, keep, intermediates=None):
    project = resolved.project
    for warning in resolved.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)

    # Where the filtered intermediates are: the content directory unless
    # a run with several targets put this target's elsewhere. Media paths
    # inside them are relative to the content directory either way.
    pages_dir = intermediates or base
    tree, titles, placed, numbered = plan_book(pages_dir, resolved, "EPUB")
    real = [s for s in placed if os.path.exists(
        os.path.join(pages_dir, s + INTERMEDIATE))]
    if numbered:
        number_tree(tree, titles)

    assembly = EpubAssembly(pages_dir, placed, tree, titles)
    if len(tree) == 1 and tree[0][0] == "page":
        assembly.add_single_page(tree[0][1], tree[0][2])
    else:
        assembly.add_tree(tree)
    assembly.finish()
    title_page = wants_title_page(str(resolved["title_page"]), tree, assembly)
    numbering = str(resolved["notes.numbering"])
    placement = str(resolved["notes.placement"])
    if placement == "book" and assembly.found["notes"] \
            and not assembly.notes_placed:
        # A chapter of its own for the notes, filled after the writer runs.
        assembly.mark_notes()
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
            # Without a title page the title is the package's dc:title, and
            # the book's first heading says it (title_page).
            "--epub-title-page=%s" % ("true" if title_page else "false"),
            # A passage for some editions, and the title-block switch,
            # resolved for this target.
            "--lua-filter", os.path.join(HERE, "target-blocks.lua"),
        ]
        environment = dict(os.environ, TARGET_NAME=name,
                           TITLE_BLOCK=str(resolved["title_block"]))
        # Run in the content directory: image paths in the intermediates
        # are relative to it.
        result = subprocess.run(command, cwd=base, capture_output=True,
                                text=True, env=environment)
        if result.stderr.strip():
            print(result.stderr.rstrip(), file=sys.stderr)
        if result.returncode != 0:
            sys.exit(f"pandoc failed building {out_path}.")
        retitle_chapters(out_path)
        if numbering != "page" or placement != "page":
            arrange_epub_notes(out_path, assembly, numbering, placement)
        link_across_chapters(out_path)
        mark_divisions(out_path, assembly.divisions(), assembly.contents_id)
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
