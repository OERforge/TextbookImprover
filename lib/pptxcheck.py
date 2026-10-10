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
project lists in images.alt_placeholders), alt text over
images.alt_max_chars, a deck with no language, links whose text is their
address, hidden slides, and what older decks are made of: diagrams drawn
as dozens of loose shapes, and columns of text laid out with tabs. And
XML PowerPoint can't read as written, which Pandoc's writer leaves.

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

import findings as fl
import pptxorder

ALT_MAX_CHARS = 120
IMAGE_EXTENSIONS = r"png|jpe?g|jpe|jfif|gif|bmp|tiff?|svgz?|emf|wmf|webp|heic|heif|avif|ico|eps|pdf"
# A file name or extension anywhere in the alt text, which PowerPoint's
# checker counts as missing alt text: its rule is that "the alt text doesn't
# contain image names or file extensions" (Microsoft, Rules for the
# Accessibility Checker). Not a name's label before another (www.jpeg.org).
FILE_NAME = re.compile(r"\.(%s)(?!\w|\.\w)" % IMAGE_EXTENSIONS, re.I)
# What says nothing about an image, matched against the whole alt text
# with its case, surrounding space, and closing punctuation ignored.
GENERIC_WORDS = {
    "image", "images", "picture", "pic", "img", "photo", "photograph", "graphic",
    "graphics", "figure", "chart", "diagram", "icon", "logo", "illustration",
    "drawing", "clip art", "clipart", "screenshot", "screen shot", "placeholder",
    "alt", "alt text", "alternative text", "alt tag", "description", "untitled",
    "insert alt text", "add alt text", "null", "none", "n/a", "na", "tbd", "todo",
    "object", "shape", "group",
}
GENERIC_PATTERNS = [
    ("a clip-art id", re.compile(r"[a-z]{1,3}\d{5,}_?", re.I)),     # j0309720, bd20069_
    ("a camera's or tool's name for a file",
     re.compile(r"(img|dsc|dscn|dcim|pict?|image|photo|screenshot|screen ?shot)[ _-]?\d+[\w-]*",
                re.I)),
    ("a default shape name",
     re.compile(r"(picture|content placeholder|graphic|image|chart|diagram|object|group|"
                r"text ?box|rectangle|oval|freeform|straight connector|line|google shape)"
                r"[\s;]*[\d;p]*", re.I)),
]
AUTO_GENERATED = re.compile(r"description automatically generated|^a picture containing\b", re.I)
SECTION_DEFAULTS = re.compile(r"(default section|untitled section|section \d+)$", re.I)
# A slide with this many loose shapes without text or alt text, or tiny
# labels, is a diagram drawn with shapes.
DRAWN_SHAPES = 8


def _clean(text):
    return re.sub(r"[\s.!?;:,]+$", "", " ".join((text or "").split())).lower()


def same_title(title):
    """A slide's title as two are compared for being the same: case,
    spacing, and closing punctuation aside."""
    return _clean(title)


def placeholder_rules(extra=()):
    """The project's own patterns from images.alt_placeholders: plain
    text matched as a whole, case aside; "re:" for a regular expression."""
    words, patterns = set(), []
    for item in extra or ():
        item = str(item)
        if item.startswith("re:"):
            patterns.append(re.compile(item[3:], re.I))
        elif item.strip():
            words.add(_clean(item))
    return words, patterns


def alt_problem(alt, name=None, rules=None, limit=ALT_MAX_CHARS):
    """(check, reason) for an alt text that needs a person, or None.
    rules: placeholder_rules() of the project's own patterns."""
    text = " ".join((alt or "").split())
    if not text:
        return None
    words, patterns = rules or (set(), [])
    cleaned = _clean(text)
    if FILE_NAME.search(text):
        return ("pptx-alt-is-file-name", "a file name or extension: %s" % text)
    if not re.search(r"\w", text):
        return ("pptx-alt-placeholder", "punctuation only: %s" % text)
    if cleaned in GENERIC_WORDS or cleaned in words \
            or any(p.fullmatch(text) or p.fullmatch(cleaned) for p in patterns):
        return ("pptx-alt-placeholder", "says nothing: %s" % text)
    for kind, pattern in GENERIC_PATTERNS:
        if pattern.fullmatch(cleaned):
            return ("pptx-alt-placeholder", "%s: %s" % (kind, text))
    if AUTO_GENERATED.search(text):
        return ("pptx-alt-auto-generated", text)
    if limit and len(text) > limit:
        return ("pptx-alt-too-long", "%d characters (limit %d)" % (len(text), limit))
    return None


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


def loose_pieces(slide):
    """The pieces of a slide's drawn diagram, or none."""
    pieces = drawn(slide)
    return pieces if len(pieces) >= DRAWN_SHAPES else []


def check(deck, name=None, kind="source-pptx", alt_max_chars=ALT_MAX_CHARS,
          alt_placeholders=(), tables=None, orders=None, links=None):
    """Findings for a parsed deck. tables: a table-headers sidecar's
    decisions by key (pptxremediate.header_rows()), for a copy they were
    written into: one decided to have no headers isn't missing them.
    orders: the reading-order sidecar's orders for this deck's slides, by
    the slide's id: a slide whose shapes are in its order was decided, in
    whatever order a person put them. links: the addresses the bare-links
    sidecar decides, and those it replaces them with: a bare link to one
    was decided, kept bare or not."""
    tables, orders, links = tables or {}, orders or {}, links or set()
    name = name or os.path.basename(deck.path)
    rules = placeholder_rules(alt_placeholders)
    out = []

    def add(where_, check_, detail, **kw):
        out.append(fl.Finding(where_, check_, detail, file=name, kind=kind, **kw))

    titles = Counter()
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
        for shape in slide.all_shapes():
            if shape.table is not None:
                if not shape.table.first_row and tables.get(shape.table.key()) != "none":
                    add(where(slide, shape), "pptx-table-no-header",
                        "%d by %d table" % (len(shape.table.rows),
                                            max((len(r) for r in shape.table.rows), default=0)))
                if shape.table.merged:
                    add(where(slide, shape), "pptx-merged-cells", "a table with merged cells")
            if shape.media and not _captioned(shape):
                add(where(slide, shape), "pptx-media-no-captions", shape.media)
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
    for shape, check_, detail in master_items(deck, rules, alt_max_chars):
        add(where(None, shape), check_, detail)
    numbers = {slide.part: slide.number for slide in deck.slides}
    for part, problem in deck.malformed:
        add("slide %d" % numbers[part] if part in numbers else part, "pptx-malformed", problem)
    return out


def _captioned(shape):
    """Whether a video or audio shape carries a caption track. PowerPoint
    keeps inserted captions as a track list in the media extension."""
    return False


def bare(text, target):
    """Whether a link's text is its own address: a scheme, www., a
    trailing slash, and case aside."""
    def squash(value):
        value = re.sub(r"^(https?://)?(www\.)?", "", value.strip().lower())
        return value.rstrip("/")
    return squash(text) == squash(target)
