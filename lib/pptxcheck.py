"""
pptxcheck.py -- what's wrong with a PowerPoint deck, for a person to fix
or decide.

The checks follow what PowerPoint's own Accessibility Checker reports, as
WebAIM's guide to it lists them (https://webaim.org/resources/evaloffice/2019),
so a deck the pipeline passes doesn't fail there: a slide with no title, an
object with no alt text, a table with no header row, and a section left
with its default name are errors; merged cells, reading order, and media
are warnings; duplicate titles and section names are notes. Alt text
holding a file name or extension is an error too, since PowerPoint counts
it as missing. To those it adds what the pipeline checks elsewhere: alt text
that says nothing (punctuation, a word such as "image", a clip-art id, a
shape's default name, Office's generated descriptions, or a pattern a
project lists in images.alt_placeholders), alt text copied from a web page
with its picture (the page's title, or a stock site's caption), one alt
text on copies of a picture cropped to show different parts of it, alt
text over images.alt_max_chars, a deck with no language, links whose text
is their address, hidden slides, and what older decks are made of: diagrams drawn
as dozens of loose shapes, and columns of text laid out with tabs. And
XML PowerPoint can't read as written, which Pandoc's writer leaves; and a
font whose license keeps the deck from being edited where the font isn't
installed (pptxfonts.py).

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
import re
from collections import Counter

import alttext
import findings as fl
import pptxfonts
import pptxorder

# The alt text rules, a book's too (alttext.py), named here as they were.
from alttext import (  # noqa: E402,F401
    ALT_MAX_CHARS, IMAGE_EXTENSIONS, FILE_NAME, GENERIC_WORDS, GENERIC_PATTERNS,
    AUTO_GENERATED, STOCK_SITES, STOCK_WORDS, PAGE_TITLE, placeholder_rules, page_title)

# Copies of an image cropped alike, to within a twentieth of the image on
# every side (pptxparse._crop's units), show the same part of it.
CROP_SLACK = 5000
UNCROPPED = (0, 0, 100000, 100000)
SECTION_DEFAULTS = re.compile(r"(default section|untitled section|section \d+)$", re.I)
# A slide with this many loose shapes without text or alt text, or tiny
# labels, is a diagram drawn with shapes.
DRAWN_SHAPES = 8


_clean = alttext.clean


def same_title(title):
    """A slide's title as two are compared for being the same: case,
    spacing, and closing punctuation aside."""
    return _clean(title)


def alt_problem(alt, name=None, rules=None, limit=ALT_MAX_CHARS):
    """(check, detail) for an alt text that needs a person, or None
    (alttext.problem). rules: placeholder_rules() of the project's own
    patterns."""
    text = " ".join((alt or "").split())
    found = alttext.problem(text, rules, limit)
    if found is None:
        return None
    kind, reason = found
    if kind in ("auto-generated", "page-title", "credit"):
        detail = text
    elif kind == "too-long":
        detail = reason
    else:
        detail = "%s: %s" % (reason, text)
    return ("pptx-alt-" + kind, detail)


def needs_alt(shape):
    """Whether PowerPoint's checker asks for alt text on a shape, and how
    firmly: "object" for a picture, chart, SmartArt, embedded object, or
    media; "shape" for a group or a shape with no text; None otherwise,
    and for a shape with no non-visual properties, which can hold no alt
    text (pptx-malformed names it)."""
    if shape.malformed:
        return None
    if shape.kind == "pic" or shape.image or shape.media:
        return "object"
    if shape.kind == "graphicFrame":
        return None if shape.frame == "table" else "object"
    if shape.kind == "contentPart":
        return "object"
    if shape.kind == "grpSp":
        return "shape"
    if shape.kind in ("sp", "cxnSp") and not shape.placeholder and not shape.text.strip():
        return "shape"
    return None


def what(shape):
    """A shape's kind in words."""
    if shape.media:
        return shape.media
    if shape.kind == "pic" or shape.image and shape.kind == "sp":
        return "picture"
    if shape.kind == "graphicFrame":
        if shape.frame == "ole":
            prog = shape.prog_id or "embedded object"
            if prog.startswith("Equation."):
                return "old Equation Editor object (%s)" % prog
            return "embedded %s object" % prog
        return {"chart": "chart", "smartart": "SmartArt graphic", "table": "table"}.get(
            shape.frame, "graphic frame")
    if shape.kind == "grpSp":
        return "group of %d shapes" % len(shape.children)
    if shape.kind == "cxnSp":
        return "connector"
    return "shape"


def where(slide, shape=None):
    head = "slide %d" % slide.number if slide else "layout or master"
    if shape is not None and shape.name:
        head += ", %s" % shape.name
    return head


def read_shapes(slide, width=0, height=0, decorative=()):
    """The shapes at the top of a slide's tree that a screen reader reads
    and the order is about, in the tree's order: not the date, footer, or
    slide number, nothing hidden or decorative, nothing off the slide, and
    nothing with neither text nor a need for alt text, but the title even
    when it's empty. decorative: the ids of shapes a sidecar marks
    decorative, which aren't read either."""
    return [s for s in slide.shapes
            if not s.furniture and not s.hidden and not s.decorative
            and (s.id is None or s.id not in decorative) and s.box is not None
            and (not width or s.box.on_slide(width, height))
            and (s.text.strip() or needs_alt(s) or s.is_title)]


def reading_order(slide, width=0, height=0, decorative=()):
    """(read, visual): the shapes a screen reader reads, in the tree's
    order and in the order they're laid out (pptxorder.visual()), when the
    title isn't first or the tree has a shape before one laid out before
    it (pptxorder.before()); else None. decorative as read_shapes()
    takes it."""
    shapes = read_shapes(slide, width, height, decorative)
    if len(shapes) < 2:
        return None
    before = pptxorder.before
    # The title is meant to be read first wherever it sits, so a pair
    # with the title in it is never out of order on that account.
    inverted = any(before(shapes[j], shapes[i])
                   for i in range(len(shapes)) for j in range(i + 1, len(shapes))
                   if not shapes[i].is_title and not shapes[j].is_title)
    titles = [s for s in shapes if s.is_title]
    title_late = bool(titles) and shapes[0] is not titles[0]
    if not inverted and not title_late:
        return None
    return shapes, pptxorder.visual(shapes)


def drawn(slide):
    """The loose shapes on a slide that look like the pieces of a drawn
    diagram: lines, connectors, and shapes without text or alt text, and
    labels of a word or two, outside placeholders and groups."""
    pieces = []
    for s in slide.shapes:
        if s.placeholder or s.decorative or s.descr:
            continue
        if s.kind in ("cxnSp",) or (s.kind == "sp" and not s.image and not s.text.strip()):
            pieces.append(s)
        elif s.kind == "sp" and not s.image and len(s.text.split()) <= 2:
            pieces.append(s)
    return pieces


def tab_table(shape):
    """Whether a shape's text is laid out in columns with tabs."""
    lines = [p for p in shape.paragraphs if "\t" in p.strip("\t ")]
    return len(lines) >= 2 or any(p.count("\t") >= 3 for p in shape.paragraphs)


def alt_items(slide, rules=None, limit=ALT_MAX_CHARS, loose=frozenset()):
    """(shape, check, detail) for each shape on a slide whose alt text
    needs a person: none where PowerPoint asks for some, or one that says
    nothing. A shape marked decorative needs nothing, nor do its pieces; a
    group's pieces without text are the group's to describe, so only the
    group is named, but a picture or chart inside it still needs its own.
    loose: the pieces of a drawn diagram, named by that finding instead."""
    quiet = set()
    for top in slide.shapes:
        for shape in top.walk():
            if id(shape) in quiet:
                continue
            firmness = needs_alt(shape)
            descr = (shape.descr or "").strip()
            if shape.decorative:
                if descr:
                    yield shape, "pptx-decorative-with-alt", descr
                quiet.update(id(c) for c in shape.walk())
                continue
            if firmness and not descr:
                if id(shape) not in loose:
                    yield shape, ("pptx-object-no-alt" if firmness == "object"
                                  else "pptx-shape-no-alt"), what(shape)
                if shape.kind == "grpSp":
                    quiet.update(id(c) for c in shape.walk()
                                 if c is not shape and needs_alt(c) == "shape")
            elif firmness and descr:
                problem = alt_problem(descr, shape.name, rules, limit)
                if problem:
                    yield shape, problem[0], problem[1]
                # A described group describes its textless pieces; a
                # picture or chart in it is read on its own, and
                # PowerPoint's checker asks for its alt text all the same.
                if shape.kind == "grpSp":
                    quiet.update(id(c) for c in shape.walk()
                                 if c is not shape and needs_alt(c) == "shape")


def master_items(deck, rules=None, limit=ALT_MAX_CHARS):
    """(shape, check, detail) for pictures on layouts and masters whose
    alt text needs a person. PowerPoint's checker doesn't look there, but
    a decision made there applies to every slide's copy of the picture."""
    for _part, shapes in deck.masters:
        for top in shapes:
            for shape in top.walk():
                if not shape.image or shape.decorative or shape.placeholder:
                    continue
                descr = (shape.descr or "").strip()
                if not descr:
                    yield shape, "pptx-master-image-no-alt", what(shape)
                else:
                    problem = alt_problem(descr, shape.name, rules, limit)
                    if problem:
                        yield shape, problem[0], problem[1]


def crop_views(crops):
    """Which part of its image each copy shows, as an index for each of
    their crops (pptxparse._crop): copies cropped alike, to within
    CROP_SLACK on every side, share one."""
    kept, out = [], []
    for crop in crops:
        crop = crop or UNCROPPED
        for index, seen in enumerate(kept):
            if all(abs(a - b) <= CROP_SLACK for a, b in zip(seen, crop)):
                out.append(index)
                break
        else:
            kept.append(crop)
            out.append(len(kept) - 1)
    return out


def crop_items(deck, flagged=frozenset()):
    """(slide, shape, check, detail) for each copy of a picture on a deck's
    slides whose alt text a copy cropped to show another part of the image
    has too: one alt text for what are different pictures, which a picture
    copied and cropped again keeps. flagged: the ids of shapes whose alt
    text another finding names already."""
    copies = {}
    for slide in deck.slides:
        for shape in slide.all_shapes():
            if shape.image and shape.image[1]:
                copies.setdefault(shape.image[1], []).append((slide, shape))
    for where_ in copies.values():
        views = crop_views([shape.crop for _slide, shape in where_])
        if len(set(views)) < 2:
            continue
        shown = {}
        for (_slide, shape), view in zip(where_, views):
            if _clean(shape.descr) and not shape.decorative:
                shown.setdefault(_clean(shape.descr), set()).add(view)
        for slide, shape in where_:
            text = _clean(shape.descr)
            if text and not shape.decorative and len(shown[text]) > 1 \
                    and id(shape) not in flagged:
                yield slide, shape, "pptx-alt-same-for-crops", " ".join(shape.descr.split())


def shared_items(deck, flagged=frozenset(), alt_of=None):
    """(slide, shape, check, detail) for each copy of a picture on a deck's
    slides whose alt text a different picture has too, its image's
    content another (alttext.shared): a description copied to a picture
    it may not fit, or the same picture in two files. flagged: the ids of
    shapes whose alt text another finding names already. alt_of(slide,
    shape): a picture's alt text as a sidecar decides it, None for one
    decided decorative; its own, if not given."""
    copies = []
    for slide in deck.slides:
        for shape in slide.all_shapes():
            if not (shape.image and shape.image[1]) or id(shape) in flagged:
                continue
            alt = alt_of(slide, shape) if alt_of else (None if shape.decorative
                                                       else shape.descr)
            if (alt or "").strip():
                copies.append((slide, shape, " ".join(alt.split())))
    found = alttext.shared([(shape.image[1], alt) for _slide, shape, alt in copies])
    for index, others in sorted(found.items()):
        slide, shape, alt = copies[index]
        yield slide, shape, "pptx-alt-shared", "%s: %s" % (
            alttext.shared_reason(others, "picture"), alt)


def loose_pieces(slide):
    """The pieces of a slide's drawn diagram, or none."""
    pieces = drawn(slide)
    return pieces if len(pieces) >= DRAWN_SHAPES else []


def check(deck, name=None, kind="source-pptx", alt_max_chars=ALT_MAX_CHARS,
          alt_placeholders=(), tables=None, orders=None, links=None, restricted=None):
    """Findings for a parsed deck. tables: a table-headers sidecar's
    decisions by key (pptxremediate.header_rows()), for a copy they were
    written into: one decided to have no headers isn't missing them.
    orders: the reading-order sidecar's orders for this deck's slides, by
    the slide's id: a slide whose shapes are in its order was decided, in
    whatever order a person put them. links: the addresses the bare-links
    sidecar decides, and those it replaces them with: a bare link to one
    was decided, kept bare or not. restricted: {typeface: fsType} of the
    fonts other decks of the run embed restricted (font_items())."""
    tables, orders, links = tables or {}, orders or {}, links or set()
    name = name or os.path.basename(deck.path)
    rules = placeholder_rules(alt_placeholders)
    out = []

    def add(where_, check_, detail, **kw):
        out.append(fl.Finding(where_, check_, detail, file=name, kind=kind, **kw))

    titles = Counter()
    flagged = set()     # the shapes an alt-text finding names
    for slide in deck.slides:
        title = slide.title
        if title:
            titles[same_title(title)] += 1
        else:
            add(where(slide), "pptx-slide-no-title",
                "no title" + (" (layout %s)" % slide.layout if slide.layout else ""))
        if slide.hidden:
            add(where(slide), "pptx-hidden-slide", title or "untitled")
        pieces = loose_pieces(slide)
        if pieces:
            add(where(slide), "pptx-drawn-diagram",
                "%d loose shapes and labels (%s)" % (len(pieces), ", ".join(
                    p.text.strip() for p in pieces if p.text.strip())[:120] or "no labels"))
        for shape, check_, detail in alt_items(slide, rules, alt_max_chars,
                                               frozenset(id(p) for p in pieces)):
            add(where(slide, shape), check_, detail)
            flagged.add(id(shape))
        for shape in slide.all_shapes():
            if shape.table is not None:
                if not shape.table.first_row and tables.get(shape.table.key()) != "none":
                    add(where(slide, shape), "pptx-table-no-header",
                        "%d by %d table" % (len(shape.table.rows),
                                            max((len(r) for r in shape.table.rows), default=0)))
                if shape.table.merged:
                    add(where(slide, shape), "pptx-merged-cells", "a table with merged cells")
            if shape.media and not _captioned(shape):
                add(where(slide, shape), "pptx-media-no-captions", shape.media + (
                    ", whose caption track holds no captions" if shape.tracks else ""))
            if shape.kind == "sp" and shape.paragraphs and tab_table(shape):
                add(where(slide, shape), "pptx-tab-table",
                    " | ".join(p.replace("\t", " / ") for p in shape.paragraphs[:2])[:120])
            for link in shape.links:
                text = " ".join(link.text.split())
                if text and link.external and bare(text, link.target) \
                        and link.target not in links:
                    add(where(slide, shape), "pptx-link-bare-url", link.target)
        order = reading_order(slide, deck.width, deck.height)
        decided = orders.get(slide.slide_id)
        if order and decided and [s.id for s in slide.shapes if s.id in set(decided)] == decided:
            order = None
        if order:
            read, visual = order
            add(where(slide), "pptx-reading-order",
                "read: %s; on the slide: %s" % (
                    ", ".join(s.name or s.id or "?" for s in read)[:200],
                    ", ".join(s.name or s.id or "?" for s in visual)[:200]))
    for slide, shape, check_, detail in crop_items(deck, flagged):
        add(where(slide, shape), check_, detail)
        flagged.add(id(shape))
    for slide, shape, check_, detail in shared_items(deck, flagged):
        add(where(slide, shape), check_, detail)
    for title, count in titles.items():
        if count > 1:
            add("deck", "pptx-duplicate-title", "%d slides titled %s" % (count, title))
    names = Counter()
    for section, _ids in deck.sections:
        names[section.strip().lower()] += 1
        if SECTION_DEFAULTS.match(section.strip() or "Untitled Section"):
            add("deck", "pptx-section-default-name", section or "(no name)")
    for section, count in names.items():
        if count > 1:
            add("deck", "pptx-duplicate-section", "%d sections named %s" % (count, section))
    if not deck.language:
        add("deck", "pptx-no-language", "no run, master, or default says what language the text is in")
    if not deck.core_title:
        add("deck", "pptx-no-core-title", "the file's properties give no title")
    for check_, detail in font_items(deck, restricted):
        add("deck", check_, detail)
    for shape, check_, detail in master_items(deck, rules, alt_max_chars):
        add(where(None, shape), check_, detail)
    numbers = {slide.part: slide.number for slide in deck.slides}
    for part, problem in deck.malformed:
        add("slide %d" % numbers[part] if part in numbers else part, "pptx-malformed", problem)
    return out


def font_items(deck, restricted=None):
    """(check, detail) for each font a license restricts that a deck embeds
    so, and each that restricted ({typeface: fsType}, from the run's other
    decks) names that it uses without embedding it, when it's set to embed
    its fonts, which PowerPoint can't do where the font isn't installed."""
    out = []
    own = deck.fonts.restricted()
    for typeface, fstype in own.items():
        out.append(("pptx-font-restricted", "%s, embedded %s: PowerPoint opens the deck "
                    "read-only where %s isn't installed" % (typeface, pptxfonts.license(fstype),
                                                            typeface)))
    for typeface, fstype in (restricted or {}).items():
        if typeface not in deck.fonts.embedded and deck.fonts.used.get(typeface) \
                and deck.fonts.embedding:
            out.append(("pptx-font-unembedded", "%s, which another deck embeds %s, used without "
                        "being embedded: the deck is set to embed its fonts, so PowerPoint won't "
                        "save it where %s isn't installed" % (typeface, pptxfonts.license(fstype),
                                                              typeface)))
    return out


def _captioned(shape):
    """Whether a video or audio shape carries captions: a caption track,
    as PowerPoint's Insert Captions keeps one (pptxparse), whose WebVTT
    file in the deck holds at least one cue."""
    return any(cues for _, _, _, cues in shape.tracks)


def bare(text, target):
    """Whether a link's text is its own address: a scheme, www., a
    trailing slash, and case aside."""
    def squash(value):
        value = re.sub(r"^(https?://)?(www\.)?", "", value.strip().lower())
        return value.rstrip("/")
    return squash(text) == squash(target)
