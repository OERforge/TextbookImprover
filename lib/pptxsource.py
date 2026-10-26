"""
pptxsource.py -- a PowerPoint deck read as a deck written in Markdown is
read: into Pandoc's JSON, the intermediate every target a deck has writes
from (decks.py), so a PowerPoint deck becomes a page, a PDF, a reveal.js
presentation, or Markdown as a Markdown deck does.

Pandoc has a PowerPoint reader, which keeps too little to repair around:
no speaker notes, no inline formatting or links, no lists a placeholder
inherits, no equations, and nothing in a shape PowerPoint wraps in
mc:AlternateContent, which every table holding an equation is. This one
reads the deck with the standard library, as pptxparse.py does for the
checks and the copy, and keeps:

- each slide, in the presentation's order, at the slide level (2), a
  hidden one left out as PowerPoint leaves it out of a show and of a PDF
  it exports; PowerPoint's sections as headings above the slides (1);
- a slide's title, its title placeholder's text, as its heading, with its
  formatting; a slide with none begins with a horizontal rule, which is
  how Pandoc's slide writers begin a slide with no title;
- its shapes in the shape tree's order, which is PowerPoint's reading
  order, a group's pieces in their places and a shape in
  mc:AlternateContent read from its Choice, as PowerPoint shows it; the
  date, footer, slide number, and header placeholders left out;
- text with its runs' own bold, italic, underline, strikethrough, small
  capitals, superscripts, and subscripts, line breaks, and links, to an
  address (with its ScreenTip as the link's title) and to another slide;
  formatting a placeholder takes from its layout or master is the deck's
  design, and isn't read as emphasis;
- lists: a paragraph's bullet or number is its own, else its shape's list
  style's for its level, else what its placeholder inherits from the
  layout, the master, and the presentation (pptxtitle.Chains), nested by
  the paragraphs' levels, a numbered list starting where PowerPoint's
  numbering does;
- tables, with their cells' spans and their header row and column,
  declared to the filter as a page's header cells are (data-th-marker);
- pictures, each image written once to media/ under the key its alt text
  is decided by (the first 16 characters of its SHA-256), with its alt
  text, or PowerPoint's decorative mark as the class decorative;
- equations, Office math, through Pandoc's Word reader: PowerPoint keeps
  them in the same OMML a Word file does, so each deck's go into one stub
  Word file, a paragraph each, and come back as TeX, a display equation
  (m:oMathPara) as display math, each of a display paragraph's equations
  a display of its own;
- speaker notes, as a ::: notes div after the slide's content, read as
  the slide's text is, a list's bullets inherited from the notes master;
- the title slide, the first slide when its title is a ctrTitle
  placeholder, as the deck's title and subtitle, which is where Pandoc's
  slide writers take a title slide from; its notes go first, before the
  first slide's heading, which Pandoc's PowerPoint writer gives the title
  slide; the deck's language, from its text.

The decisions a person made for the deck's copy (pptxremediate.py) are
the conversion's too, read from the same sidecars with the same keys and
taken as the copy takes them: alt text and the decorative mark, a table's
headers, a slide's title (replacing one only where another slide has it
too), and its reading order; a decision for a shape whose id its slide
repeats is skipped, as the copy skips it. A bare link's replacement and
title are the filter's to write, from the same sidecar, as for a book's
page.

What a deck holds that a deck in Markdown can't is reported, not guessed
at (Record.losses): the rest of the title slide (its pictures, a text box
beside its title), charts, SmartArt, video and audio, a group's
arrangement, a picture in a format browsers don't show, a picture's crop,
and a link that does something other than go to an address or a slide,
or goes to a slide that's hidden or has no title.

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

import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from collections import Counter, OrderedDict
from xml.etree import ElementTree as ET

import decks as decklib
import docxrepair
import pptxcheck
import pptxparse
import pptxremediate
import pptxtitle

q = pptxparse.q
NS = pptxparse.NS
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

# A PowerPoint deck's slides are headings at level 2, its sections at 1.
SLIDE_LEVEL = 2
# The JSON's version of Pandoc's types, when the run gives none: what
# Pandoc 3.9 to 3.12.1 read and write (pandoc-types 1.23.1).
API_VERSION = [1, 23, 1]
# Where a deck's pictures are written beside it: each under its image's
# key (pptxremediate.image_key), which is the path the alt-text report
# names it by too.
MEDIA = "media"
# Image formats a browser shows; a picture in another (an EMF, a WMF, a
# TIFF) is kept, and reported.
SHOWN_FORMATS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp")
# PowerPoint's numbering schemes as Pandoc's list styles and delimiters;
# one of the others (circled, East Asian, Thai, Hindi) is numbered 1, 2,
# 3, and reported.
NUMBERING = re.compile(r"^(alphaLc|alphaUc|arabic|romanLc|romanUc)(ParenBoth|ParenR|Period|Plain)$")
STYLES = {"alphaLc": "LowerAlpha", "alphaUc": "UpperAlpha", "arabic": "Decimal",
          "romanLc": "LowerRoman", "romanUc": "UpperRoman"}
DELIMITERS = {"ParenBoth": "TwoParens", "ParenR": "OneParen", "Period": "Period",
              "Plain": "DefaultDelim"}
BULLETS = (q("a:buNone"), q("a:buChar"), q("a:buAutoNum"), q("a:buBlip"))
# A run's own formatting, outermost first, as the inlines are nested.
FORMATS = ("Strikeout", "Underline", "Strong", "Emph", "SmallCaps", "Superscript", "Subscript")
WHITESPACE = re.compile(r"[ \t\r\n\x0b\x0c]+")
# A link PowerPoint follows by moving through the show, as a slide of the
# deck's: ppaction://hlinkshowjump?jump=...
JUMPS = ("firstslide", "lastslide", "nextslide", "previousslide")
TRUE = ("1", "true", "on")


# --------------------------------------------------------------------------
# Pandoc's JSON
# --------------------------------------------------------------------------

def attr(ident="", classes=(), pairs=()):
    return [ident, list(classes), [list(p) for p in pairs]]


def Str(text):
    return {"t": "Str", "c": text}


def space():
    return {"t": "Space"}


def line_break():
    return {"t": "LineBreak"}


def words(text):
    """Text as Pandoc's Str and Space inlines, a run of white space one
    Space; a no-break space stays in its word."""
    out, pos = [], 0
    for gap in WHITESPACE.finditer(text):
        if gap.start() > pos:
            out.append(Str(text[pos:gap.start()]))
        out.append(space())
        pos = gap.end()
    if pos < len(text):
        out.append(Str(text[pos:]))
    return out


def blank(inline):
    return inline["t"] in ("Space", "SoftBreak", "LineBreak")


def trimmed(inlines):
    """inlines without white space or line breaks at either end."""
    start, end = 0, len(inlines)
    while start < end and blank(inlines[start]):
        start += 1
    while end > start and blank(inlines[end - 1]):
        end -= 1
    return inlines[start:end]


def wrapped(kind, inlines):
    """inlines in an element of kind, the white space at either end left
    outside it, where Markdown needs it."""
    start, end = 0, len(inlines)
    while start < end and inlines[start]["t"] == "Space":
        start += 1
    while end > start and inlines[end - 1]["t"] == "Space":
        end -= 1
    if start == end:
        return inlines
    return inlines[:start] + [{"t": kind, "c": inlines[start:end]}] + inlines[end:]


def nested(items, formats):
    """[(formats, inlines)] as inlines, each run of items sharing the
    first of formats in one element of it, then the next within each."""
    if not formats:
        return [inline for _fmt, inlines in items for inline in inlines]
    first, rest = formats[0], formats[1:]
    out, i = [], 0
    while i < len(items):
        has = first in items[i][0]
        j = i
        while j < len(items) and (first in items[j][0]) == has:
            j += 1
        if has:
            out.extend(wrapped(first, nested([(f - {first}, inl) for f, inl in items[i:j]],
                                             rest)))
        else:
            out.extend(nested(items[i:j], rest))
        i = j
    return out


def tidied(inlines):
    """inlines without a space beside a line break, at every depth."""
    out = []
    for inline in inlines:
        if inline["t"] in FORMATS:
            inline = {"t": inline["t"], "c": tidied(inline["c"])}
        if inline["t"] == "Space" and out and out[-1]["t"] == "LineBreak":
            continue
        if inline["t"] == "LineBreak":
            while out and out[-1]["t"] == "Space":
                out.pop()
        out.append(inline)
    return out


def text_of(inlines):
    """Inlines as text, as Pandoc's stringify gives it."""
    out = []
    for inline in inlines:
        kind = inline["t"]
        if kind == "Str":
            out.append(inline["c"])
        elif kind in ("Space", "SoftBreak", "LineBreak"):
            out.append(" ")
        elif kind == "Math":
            out.append(inline["c"][1])
        elif kind in ("Link", "Image", "Span"):
            out.append(text_of(inline["c"][1]))
        elif kind in FORMATS:
            out.append(text_of(inline["c"]))
    return "".join(out)


def identifier(text, used):
    """The id Pandoc's Markdown reader gives a heading of this text, and
    its writer leaves out as its own (uniqueIdent and textToIdentifier in
    Shared.hs, 3.12.1, with auto_identifiers): lowercased, its letters,
    numbers, _, -, and . kept, its words joined by -, anything before its
    first letter dropped; "section" for none; numbered after one used."""
    kept = "".join(c for c in text.lower() if c.isspace() or c.isalnum() or c in "_-.")
    ident = "-".join(kept.split())
    while ident and not ident[0].isalpha():
        ident = ident[1:]
    ident = ident or "section"
    if ident in used:
        n = 1
        while "%s-%d" % (ident, n) in used:
            n += 1
        ident = "%s-%d" % (ident, n)
    used.add(ident)
    return ident


# --------------------------------------------------------------------------
# What a deck's conversion leaves out, and counts
# --------------------------------------------------------------------------

class Record:
    """What reading a deck kept and what it left out: counts by kind, and
    losses, (kind, where) a person can find."""

    def __init__(self):
        self.counts = Counter()
        self.losses = []

    def lose(self, kind, where):
        self.losses.append((kind, where))


# --------------------------------------------------------------------------
# What a paragraph inherits: its bullet
# --------------------------------------------------------------------------

def bullet_value(element):
    """A bullet element as (kind, scheme, start): kind none, bullet, or
    number; scheme and start a number's."""
    if element is None:
        return None
    name = element.tag.split("}")[-1]
    if name == "buNone":
        return ("none", None, None)
    if name == "buAutoNum":
        try:
            start = int(element.get("startAt") or 1)
        except ValueError:
            start = 1
        return ("number", element.get("type") or "arabicPeriod", start)
    return ("bullet", None, None)


BULLET_XML = re.compile(r"<a:(buNone|buChar|buAutoNum|buBlip)\b([^>]*)")


def bullet_of_xml(text):
    """The same of a bullet element as pptxtitle's Props keep it: its XML."""
    match = BULLET_XML.match(text or "")
    if match is None:
        return None
    name, attrs = match.group(1), pptxtitle.attributes("<x%s>" % match.group(2))
    if name == "buNone":
        return ("none", None, None)
    if name == "buAutoNum":
        try:
            start = int(attrs.get("startAt") or 1)
        except ValueError:
            start = 1
        return ("number", attrs.get("type") or "arabicPeriod", start)
    return ("bullet", None, None)


def own_levels(body):
    """{level: bullet} of a text body's own list style (a:lstStyle), a
    level being a paragraph's lvl + 1; a:defPPr's for every level it
    doesn't give."""
    style = body.find(q("a:lstStyle")) if body is not None else None
    levels, default = {}, None
    for child in (style if style is not None else ()):
        name = child.tag.split("}")[-1]
        found = next((c for c in child if c.tag in BULLETS), None)
        match = re.fullmatch(r"lvl(\d)pPr", name)
        if match and found is not None:
            levels[int(match.group(1))] = bullet_value(found)
        elif name == "defPPr" and found is not None:
            default = bullet_value(found)
    if default is not None:
        for n in range(1, 10):
            levels.setdefault(n, default)
    return levels


def chain_levels(lists):
    """{level: bullet} of pptxtitle's list styles, laid one over another."""
    return {n: bullet_of_xml(props.groups.get("bu"))
            for n, props in pptxtitle.chain(lists).items() if props.groups.get("bu")}


# --------------------------------------------------------------------------
# A deck
# --------------------------------------------------------------------------

class Reader:
    """One deck, read slide by slide into Pandoc's blocks."""

    def __init__(self, path, base, alts=None, tables=None, titles=None, orders=None,
                 media=MEDIA):
        self.path, self.base, self.media_dir = path, base, media
        self.alts, self.tables = alts or {}, tables or {}
        self.titles, self.orders = titles or {}, orders or {}
        self.deck = pptxparse.read(path)
        self.name = pptxremediate.deck_name(path)
        self.record = Record()
        self.zip = zipfile.ZipFile(path)
        self.texts = {}
        self.chains = {}
        self.equations = []         # (OMML element, display, where)
        self.used_ids = set()
        self.slide_ids = {}         # slide part: its heading's id
        self.pending_links = []     # (link inline, slide part, where it is)
        self.slide = None
        self.rels = {}
        self.order = {}             # slide part: the slide shown before and after it
        self.dry = False            # reading what's left out, with nothing written
        self.repeated = set()       # the ids the slide gives more than one shape

    # ---- parts ----------------------------------------------------------

    def text(self, part):
        """A part's XML as text, for pptxtitle's chains."""
        if part not in self.texts:
            try:
                self.texts[part] = pptxparse.part_text(self.zip.read(part))[0]
            except KeyError:
                self.texts[part] = None
        return self.texts[part]

    def master_of(self, layout):
        if not layout:
            return None
        return pptxparse.rel_target(pptxparse.relationships(self.zip, layout), "slideMaster")

    def inherited(self, slide, shape):
        """{level: bullet} a shape's text inherits: a placeholder's from
        its layout, master, and the presentation; a text box's or a table
        cell's from the presentation's default text style."""
        ph = (shape.ph_type, shape.ph_idx) if shape is not None and shape.placeholder else (None, None)
        layout = slide.layout_part if slide is not None else None
        key = (ph, layout)
        if key not in self.chains:
            chains = pptxtitle.Chains(ph[0], ph[1], self.text(layout) if layout else None,
                                      self.text(self.master_of(layout)) if layout else None,
                                      self.text(self.deck.presentation_part))
            self.chains[key] = chain_levels(chains.lists)
        return self.chains[key]

    def notes_inherited(self, notes_part):
        """{level: bullet} a notes slide's body inherits from its notes
        master: its body placeholder's list style over the master's notes
        style."""
        master = pptxparse.rel_target(pptxparse.relationships(self.zip, notes_part), "notesMaster")
        key = ("notes", master)
        if key not in self.chains:
            xml = self.text(master) if master else None
            lists = []
            if xml:
                style = re.search(r"<p:notesStyle\b", xml)
                if style:
                    lists.append(pptxtitle.list_levels(xml, style.start()))
                body = pptxtitle.matching(xml, "body", None)
                if body is not None:
                    span = pptxtitle._sub(xml, body, ["p:txBody", "a:lstStyle"])
                    if span:
                        lists.append(pptxtitle.list_levels(xml, span[0]))
            self.chains[key] = chain_levels(lists)
        return self.chains[key]

    def where(self, slide=None):
        slide = slide or self.slide
        return "%s slide %d" % (os.path.basename(self.path), slide.number) if slide else \
            os.path.basename(self.path)

    # ---- links ----------------------------------------------------------

    def link_of(self, click):
        """A link's key: ("url", address, title), ("slide", part, title),
        or None, from an a:hlinkClick."""
        if click is None:
            return None
        rid, action = click.get(q("r:id")), click.get("action") or ""
        title = " ".join((click.get("tooltip") or "").split())
        target = self.rels.get(rid) if rid else None
        if action.startswith("ppaction://hlinksldjump"):
            if target and not target[2]:
                return ("slide", target[1], title)
            self.record.lose("link", self.where() + ": a link to a slide not in the deck")
            return None
        if action.startswith("ppaction://hlinkshowjump"):
            jump = re.search(r"jump=(\w+)", action)
            jump = jump.group(1).lower() if jump else ""
            if jump in JUMPS:
                return ("jump", jump, title)
            self.record.lose("link", "%s: a link that %s" % (
                self.where(), "ends the show" if jump == "endshow" else
                "goes to the slide last shown" if jump == "lastslideviewed" else
                "moves through the show"))
            return None
        if action.startswith("ppaction://"):
            if target and target[2]:
                return ("url", target[1], title)
            self.record.lose("link", "%s: a link that runs %s" % (
                self.where(), action[len("ppaction://"):].split("?")[0] or "an action"))
            return None
        if target and target[2]:
            return ("url", target[1], title)
        if target:
            # A link to a part of the file: a slide, as PowerPoint writes
            # one without an action.
            if target[1].startswith("ppt/slides/"):
                return ("slide", target[1], title)
            self.record.lose("link", self.where() + ": a link to " + target[1])
        return None

    def link_inline(self, key, inlines):
        kind, target, title = key
        link = {"t": "Link", "c": [attr(), inlines, ["", title]]}
        if kind == "url":
            link["c"][2][0] = target
        else:
            if kind == "jump":
                target = self.order.get(self.slide.part, {}).get(target)
            self.pending_links.append((link, target, self.where()))
        return link

    def resolve_links(self, node):
        """Each link to a slide in node (the blocks, the metadata) given
        its heading's id; one to a slide with no heading, or none shown, is
        its words."""
        unresolved = {}
        for link, part, where in self.pending_links:
            ident = self.slide_ids.get(part)
            if ident:
                link["c"][2][0] = "#" + ident
            else:
                unresolved[id(link)] = where
        if not unresolved:
            return node

        def walk(node):
            if isinstance(node, list):
                out = []
                for item in node:
                    if isinstance(item, dict) and id(item) in unresolved:
                        out.extend(walk(item["c"][1]))
                        self.record.lose("link", unresolved[id(item)] + ": a link to a slide "
                                         "with no title, or to none shown")
                    else:
                        out.append(walk(item))
                return out
            if isinstance(node, dict):
                return {k: walk(v) for k, v in node.items()}
            return node
        return walk(node)

    # ---- text -----------------------------------------------------------

    def pieces(self, paragraph):
        """A paragraph's runs, breaks, and equations, in order: (kind,
        value, formatting, link)."""
        out = []

        def run_format(rpr):
            if rpr is None:
                return ()
            found = []
            if (rpr.get("strike") or "noStrike") != "noStrike":
                found.append("Strikeout")
            if (rpr.get("u") or "none") != "none":
                found.append("Underline")
            if rpr.get("b") in TRUE:
                found.append("Strong")
            if rpr.get("i") in TRUE:
                found.append("Emph")
            if rpr.get("cap") == "small":
                found.append("SmallCaps")
            try:
                baseline = int(rpr.get("baseline") or 0)
            except ValueError:
                baseline = 0
            if baseline > 0:
                found.append("Superscript")
            elif baseline < 0:
                found.append("Subscript")
            return tuple(found)

        for child in paragraph:
            tag = child.tag
            if tag in (q("a:r"), q("a:fld")):
                rpr = child.find(q("a:rPr"))
                click = rpr.find(q("a:hlinkClick")) if rpr is not None else None
                out.append(("text", child.findtext(q("a:t")) or "", run_format(rpr),
                            self.link_of(click)))
            elif tag == q("a:br"):
                rpr = child.find(q("a:rPr"))
                click = rpr.find(q("a:hlinkClick")) if rpr is not None else None
                out.append(("br", None, (), self.link_of(click)))
            elif tag == q("a14:m"):
                # An equation, in a shape PowerPoint wraps in
                # mc:AlternateContent, whose Choice pptxparse reads. A
                # display paragraph's equations are each a display of its
                # own: Pandoc's Word reader reads a paragraph of two as one
                # formula, the two run together ({a = 1}{b = 2}), where
                # the deck holds two equations, which the copy repairs, and
                # its report names, each on its own.
                for math in child:
                    if math.tag == q("m:oMathPara"):
                        found = [(m, True) for m in math if m.tag == q("m:oMath")] \
                            or [(math, True)]
                    elif math.tag == q("m:oMath"):
                        found = [(math, False)]
                    else:
                        continue
                    for element, display in found:
                        self.equations.append((element, display, self.where()))
                        out.append(("math", len(self.equations) - 1, (), None))
        return out

    def inlines(self, paragraph):
        """A paragraph's inlines: its runs' own formatting, its links."""
        pieces = self.pieces(paragraph)
        out, i = [], 0
        while i < len(pieces):
            link = pieces[i][3]
            j = i
            while j < len(pieces) and pieces[j][3] == link:
                j += 1
            inner = self.formatted(pieces[i:j])
            start, end = 0, len(inner)
            while start < end and blank(inner[start]):
                start += 1
            while end > start and blank(inner[end - 1]):
                end -= 1
            if link is None or start == end:
                out.extend(inner)
            else:
                # White space at a link's ends is outside it.
                out.extend(inner[:start] + [self.link_inline(link, inner[start:end])]
                           + inner[end:])
            i = j
        return out

    def formatted(self, pieces):
        """Pieces with one link, as inlines: runs of the same formatting
        joined, since PowerPoint splits a run where nothing shows, and
        runs that share a format nested in one element of it, so italic H
        and an italic subscript 0 are one emphasis holding both. The white
        space beside a line break goes, as Pandoc's readers leave none, and
        a break takes the formatting the runs either side of it share, a
        run of only white space beside it left out first: an indent after
        a break, which shows no format, doesn't part two bold lines."""
        segments = []
        for kind, value, fmt, _link in pieces:
            if kind == "text" and segments and segments[-1][0] == "text" \
                    and segments[-1][2] == set(fmt):
                segments[-1][1] += value
            elif kind == "text" and not WHITESPACE.sub("", value) and segments \
                    and segments[-1][0] == "br":
                continue
            else:
                if kind == "br":
                    while segments and segments[-1][0] == "text" \
                            and not WHITESPACE.sub("", segments[-1][1]):
                        segments.pop()
                segments.append([kind, value, set(fmt)])
        for i, segment in enumerate(segments):
            if segment[0] == "br":
                before = segments[i - 1][2] if i else set()
                after = segments[i + 1][2] if i + 1 < len(segments) else set()
                segment[2] = before & after
            elif segment[0] == "math":
                segment[2] = set()
        items = []
        for kind, value, fmt in segments:
            if kind == "br":
                inlines = [line_break()]
            elif kind == "math":
                inlines = [{"t": "Math", "c": [{"t": "InlineMath"}, "\x00%d\x00" % value]}]
            else:
                inlines = words(value)
            items.append((fmt, inlines))
        return tidied(nested(items, FORMATS))

    def paragraphs(self, body, inherited):
        """A text body's paragraphs as (level, bullet, inlines)."""
        own = own_levels(body)
        out = []
        for paragraph in body.findall(q("a:p")):
            ppr = paragraph.find(q("a:pPr"))
            try:
                level = int(ppr.get("lvl") or 0) if ppr is not None else 0
            except ValueError:
                level = 0
            found = next((c for c in ppr if c.tag in BULLETS), None) if ppr is not None else None
            bullet = bullet_value(found) if found is not None else (
                own.get(level + 1) or inherited.get(level + 1))
            if bullet and bullet[0] == "none":
                bullet = None
            out.append((level, bullet, trimmed(self.inlines(paragraph))))
        return out

    def list_attributes(self, bullet):
        """An OrderedList's start, style, and delimiter for PowerPoint's
        numbering."""
        _kind, scheme, start = bullet
        match = NUMBERING.match(scheme or "")
        if match is None:
            self.record.lose("numbering", "%s: numbered %s, shown 1, 2, 3" % (self.where(), scheme))
            style, delim = "Decimal", "Period"
        else:
            style, delim = STYLES[match.group(1)], DELIMITERS[match.group(2)]
        return [start, {"t": style}, {"t": delim}]

    def blocks(self, paragraphs):
        """(level, bullet, inlines) as Pandoc's blocks: a paragraph each, a
        run of bulleted or numbered ones a list, nested by their levels,
        a paragraph with neither under an item of a shallower list a
        paragraph of that item, and an empty paragraph, which PowerPoint
        shows as space and no bullet, nothing."""
        out, stack = [], []

        def same(a, b):
            return a[0] == b[0] and (a[0] != "number" or a[1] == b[1])

        def close():
            entry = stack.pop()
            items = entry["items"]
            if any(len(item) > 1 and any(b["t"] == "Para" for b in item) for item in items):
                # Loose, every item's paragraphs as such.
                for item in items:
                    for block in item:
                        if block["t"] == "Plain":
                            block["t"] = "Para"
            if entry["bullet"][0] == "number":
                block = {"t": "OrderedList", "c": [self.list_attributes(entry["bullet"]), items]}
            else:
                block = {"t": "BulletList", "c": items}
            if stack:
                stack[-1]["items"][-1].append(block)
            else:
                out.append(block)

        for level, bullet, inlines in paragraphs:
            if not inlines:
                continue
            if bullet is None:
                while stack and stack[-1]["level"] >= level:
                    close()
                if stack:
                    stack[-1]["items"][-1].append({"t": "Para", "c": inlines})
                else:
                    out.append({"t": "Para", "c": inlines})
                continue
            while stack and stack[-1]["level"] > level:
                close()
            if stack and stack[-1]["level"] == level and same(stack[-1]["bullet"], bullet):
                stack[-1]["items"].append([{"t": "Plain", "c": inlines}])
                continue
            if stack and stack[-1]["level"] == level:
                close()
            stack.append({"level": level, "bullet": bullet,
                          "items": [[{"t": "Plain", "c": inlines}]]})
        while stack:
            close()
        return out

    def text_blocks(self, slide, shape):
        body = shape.element.find(q("p:txBody"))
        if body is None:
            body = shape.element.find(".//" + q("a:txBody"))
        if body is None:
            return []
        return self.blocks(self.paragraphs(body, self.inherited(slide, shape)))

    # ---- pictures -------------------------------------------------------

    def media(self, part, digest, ext):
        """The image's path in the intermediate, written beside the decks
        once under its key."""
        name = pptxremediate.image_key(digest) + ext
        target = os.path.join(self.base, *name.split("/"))
        if not self.dry and not os.path.exists(target):
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as fh:
                fh.write(self.zip.read(part))
        return name

    def picture(self, slide, shape):
        """A picture as a paragraph holding its image, its alt text the
        sidecar's decision, else the deck's own; decorative, the class."""
        part, digest, ext = shape.image
        if not digest:
            self.record.lose("picture", "%s: a picture linked from %s, not in the file" % (
                self.where(), part))
            return []
        src = self.media(part, digest, ext)
        known, alt = pptxremediate.decision(self.alts, self.name, slide, shape) \
            if shape.id not in self.repeated else (False, None)
        if known:
            decorative = alt is None
            text = shape.descr if alt == "" else alt
        else:
            decorative, text = shape.decorative, shape.descr
        if ext not in SHOWN_FORMATS:
            self.record.lose("format", "%s: a picture in %s, which a browser doesn't show" % (
                self.where(), ext.lstrip(".").upper() or "an unknown format"))
        if shape.crop and shape.crop != (0, 0, pptxparse.FULL, pptxparse.FULL):
            self.record.lose("crop", self.where() + ": a picture shown whole, which the slide "
                             "shows cropped")
        image = {"t": "Image", "c": [attr("", ["decorative"] if decorative else []),
                                     [] if decorative else words(" ".join((text or "").split())),
                                     [src, ""]]}
        # A picture that is a link, as its own non-visual properties say.
        click = shape.element.find(".//" + q("p:cNvPr") + "/" + q("a:hlinkClick"))
        key = self.link_of(click) if click is not None else None
        if key:
            image = self.link_inline(key, [image])
        return [{"t": "Para", "c": [image]}]

    # ---- tables ---------------------------------------------------------

    def table(self, slide, shape):
        """A table, its header row and column as the deck flags them or
        the sidecar decides, and its cells' spans."""
        tbl = shape.element.find(".//" + q("a:tbl"))
        if tbl is None:
            return []
        grid = tbl.find(q("a:tblGrid"))
        columns = len(grid.findall(q("a:gridCol"))) if grid is not None else 0
        pr = tbl.find(q("a:tblPr"))
        first_row = pr is not None and pr.get("firstRow") in TRUE
        first_col = pr is not None and pr.get("firstCol") in TRUE
        decided = self.tables.get(shape.table.key()) \
            if shape.table is not None and shape.id not in self.repeated else None
        if decided:
            first_row = decided in ("first-row", "both")
            first_col = decided in ("first-column", "both")
        # Declared for the filter as a page's <th> cells are
        # (figures-and-tables.lua's data-th-marker), which keeps a header
        # column it would otherwise take for the reader's guess; a table
        # flagged with neither, and not decided, is left undeclared.
        marker = decided or {(True, True): "both", (True, False): "first-row",
                             (False, True): "first-column"}.get((first_row, first_col))
        inherited = self.inherited(slide, None)
        rows = []
        for tr in tbl.findall(q("a:tr")):
            cells = []
            for tc in tr.findall(q("a:tc")):
                if tc.get("hMerge") in TRUE or tc.get("vMerge") in TRUE:
                    continue
                try:
                    colspan = max(1, int(tc.get("gridSpan") or 1))
                    rowspan = max(1, int(tc.get("rowSpan") or 1))
                except ValueError:
                    colspan = rowspan = 1
                body = tc.find(q("a:txBody"))
                blocks = self.blocks(self.paragraphs(body, inherited)) if body is not None else []
                if len(blocks) == 1 and blocks[0]["t"] == "Para":
                    blocks[0]["t"] = "Plain"
                cells.append([attr(), {"t": "AlignDefault"}, rowspan, colspan, blocks])
            rows.append([attr(), cells])
        columns = columns or max((sum(c[3] for c in row[1]) for row in rows), default=0)
        head = rows[:1] if first_row and rows else []
        body_rows = rows[len(head):]
        return [{"t": "Table", "c": [
            attr(pairs=[["data-th-marker", marker]] if marker else []), [None, []],
            [[{"t": "AlignDefault"}, {"t": "ColWidthDefault"}]] * columns,
            [attr(), head], [[attr(), 1 if first_col else 0, [], body_rows]], [attr(), []]]}]

    # ---- a slide --------------------------------------------------------

    def ordered(self, slide):
        """A slide's top-level shapes in the order its reading-order row
        gives, each named shape in the place of one named before it, as
        the copy puts them: the order a person decided is the order a
        page, a PDF, or Markdown reads them in, though the copy leaves one
        that would draw overlapping shapes the other way round."""
        order = self.orders.get(pptxremediate.slide_key(self.name, slide))
        if not order:
            return list(slide.shapes)
        ids = [s.id for s in slide.shapes]
        if len(set(order)) != len(order) or any(ids.count(i) != 1 for i in order):
            return list(slide.shapes)
        named = [s for s in slide.shapes if s.id in order]
        by_id = {s.id: s for s in named}
        queue = [by_id[i] for i in order]
        return [queue.pop(0) if s.id in by_id else s for s in slide.shapes]

    def content(self, slide, skip=()):
        """A slide's content, in reading order, without its title and the
        shapes in skip."""
        out = []

        def visit(shape):
            if id(shape) in skip or shape.malformed and not shape.children:
                return
            if shape.kind == "grpSp":
                if shape.descr and not shape.decorative:
                    self.record.lose("group", "%s: a group described as %r" % (
                        self.where(slide), shape.descr))
                for child in shape.children:
                    visit(child)
                return
            if shape.hidden or shape.furniture or shape.is_title:
                return
            if shape.media:
                self.record.lose("media", "%s: %s" % (self.where(slide), {
                    "video": "a video", "audio": "a sound"}.get(shape.media, "a video or sound")))
                return
            if shape.kind == "graphicFrame":
                if shape.frame == "table":
                    out.extend(self.table(slide, shape))
                elif shape.image:
                    out.extend(self.picture(slide, shape))
                else:
                    self.record.lose(shape.frame or "object", "%s: %s" % (
                        self.where(slide), {"chart": "a chart", "smartart": "a SmartArt graphic",
                                            "ole": "an embedded object"}.get(
                                                shape.frame, "an object")))
                return
            if shape.kind == "contentPart":
                self.record.lose("ink", self.where(slide) + ": ink")
                return
            if shape.image:
                out.extend(self.picture(slide, shape))
            if shape.kind in ("sp", "cxnSp"):
                out.extend(self.text_blocks(slide, shape))

        for shape in self.ordered(slide):
            visit(shape)
        return out

    def notes(self, slide):
        """A slide's speaker notes, its notes slide's body as blocks, in a
        ::: notes div."""
        if not slide.notes_part:
            return []
        try:
            root = pptxparse.parse_xml(self.zip.read(slide.notes_part))
        except KeyError:
            return []
        saved = self.rels
        self.rels = pptxparse.relationships(self.zip, slide.notes_part)
        inherited = self.notes_inherited(slide.notes_part)
        blocks = []
        for sp in root.iter(q("p:sp")):
            ph = sp.find(".//" + q("p:ph"))
            if ph is None or ph.get("type") != "body":
                continue
            body = sp.find(q("p:txBody"))
            if body is not None:
                blocks += self.blocks(self.paragraphs(body, inherited))
        self.rels = saved
        if not blocks:
            return []
        return [{"t": "Div", "c": [attr("", ["notes"]), blocks]}]

    def title(self, slide):
        """(the slide's heading as inlines, or None for none, and the shape
        it is): the title placeholder's text, unless the slide-titles
        sidecar gives the slide another, as the copy writes it."""
        key = pptxremediate.slide_key(self.name, slide)
        decided = self.titles.get(key)
        shape = slide.title_shape
        if shape is not None:
            own = self.title_inlines(slide, shape)
            if decided and decided != slide.title and self.shared[
                    pptxcheck.same_title(slide.title)] > 1 and shape.id not in self.repeated:
                return words(decided), shape
            return own, shape
        if decided:
            # None for a heading whose id the slide repeats (pptxtitle's
            # _texts), above which the copy adds the title.
            heading, _added = pptxtitle.heading_for(slide, decided)
            return words(decided), heading
        return None, None

    def title_inlines(self, slide, shape):
        """A title placeholder's text, its paragraphs one line each."""
        body = shape.element.find(q("p:txBody"))
        out = []
        for paragraph in (body.findall(q("a:p")) if body is not None else ()):
            inlines = trimmed(self.inlines(paragraph))
            if inlines:
                if out:
                    out.append(line_break())
                out.extend(inlines)
        return out

    def subtitle(self, slide):
        for shape in slide.all_shapes():
            if shape.ph_type == "subTitle" and shape.text.strip():
                return self.title_inlines(slide, shape), shape
        return None, None

    def read(self):
        """The deck as Pandoc's JSON document, with a record of what it
        left out."""
        deck = self.deck
        shown = [s for s in deck.slides if not s.hidden]
        for slide in deck.slides:
            if slide.hidden:
                self.record.lose("hidden", self.where(slide))
        for i, slide in enumerate(shown):
            self.order[slide.part] = {
                "firstslide": shown[0].part, "lastslide": shown[-1].part,
                "nextslide": shown[i + 1].part if i + 1 < len(shown) else None,
                "previousslide": shown[i - 1].part if i else None}
        self.shared = Counter(pptxcheck.same_title(s.title) for s in deck.slides if s.title)
        meta = OrderedDict()
        blocks = []
        sections = {}
        for n, (name, ids) in enumerate(deck.sections):
            for sid in ids:
                sections.setdefault(sid, (n, name))
        opened = set()
        title_slide = None
        if shown and shown[0].title_shape is not None and shown[0].title_shape.ph_type == "ctrTitle":
            title_slide = shown[0]
        for slide in shown:
            self.slide = slide
            self.rels = pptxparse.relationships(self.zip, slide.part)
            # A decision for a shape whose id the slide repeats is skipped,
            # as the copy skips it (pptxremediate.remediate).
            self.repeated = {i for i, n in Counter(
                s.id for s in slide.all_shapes() if s.id).items() if n > 1}
            # A section's heading before its first slide, but the title
            # slide, which is the deck's metadata, its notes before any
            # heading.
            section = sections.get(slide.slide_id)
            if section is not None and section not in opened and slide is not title_slide:
                opened.add(section)
                blocks.append({"t": "Header", "c": [
                    SLIDE_LEVEL - 1, attr(identifier(section[1], self.used_ids)),
                    words(section[1])]})
                self.record.counts["sections"] += 1
            if slide is title_slide:
                inlines, shape = self.title(slide)
                meta["title"] = {"t": "MetaInlines", "c": inlines}
                sub, sub_shape = self.subtitle(slide)
                if sub:
                    meta["subtitle"] = {"t": "MetaInlines", "c": sub}
                self.dry = True
                rest = self.content(slide, skip={id(s) for s in (shape, sub_shape) if s})
                self.dry = False
                if rest:
                    self.record.lose("title-slide", "%s: %s" % (self.where(slide),
                                                                 describe(rest)))
                blocks += self.notes(slide)
                self.record.counts["slides"] += 1
                continue
            inlines, shape = self.title(slide)
            if inlines:
                ident = identifier(text_of(inlines), self.used_ids)
                self.slide_ids[slide.part] = ident
                blocks.append({"t": "Header", "c": [SLIDE_LEVEL, attr(ident), inlines]})
            elif blocks:
                blocks.append({"t": "HorizontalRule"})
            blocks += self.content(slide, skip={id(shape)} if shape else ())
            blocks += self.notes(slide)
            self.record.counts["slides"] += 1
        self.slide = None
        if title_slide is None and deck.core_title:
            meta["title-meta"] = {"t": "MetaString", "c": deck.core_title}
        if deck.language:
            meta["lang"] = {"t": "MetaString", "c": deck.language}
        resolved = self.resolve_links({"blocks": blocks, "meta": dict(meta)})
        blocks, meta = resolved["blocks"], resolved["meta"]
        meta[decklib.LEVEL_KEY] = {"t": "MetaString", "c": str(SLIDE_LEVEL)}
        if decklib.slide_level(blocks) != SLIDE_LEVEL:
            # Pandoc would work out another for the deck's Markdown: a deck
            # whose slides hold only their titles.
            meta["slide-level"] = {"t": "MetaString", "c": str(SLIDE_LEVEL)}
        return {"pandoc-api-version": list(API_VERSION), "meta": meta, "blocks": blocks}

    def close(self):
        self.zip.close()


def describe(blocks):
    """What blocks hold, in a few words: a picture, a table, text."""
    kinds = []
    for block in blocks:
        inlines = block["c"] if block["t"] == "Para" else []
        if len(inlines) == 1 and inlines[0]["t"] == "Link":
            inlines = inlines[0]["c"][1]
        kind = ("a table" if block["t"] == "Table" else
                "a picture" if len(inlines) == 1 and inlines[0]["t"] == "Image" else "text")
        if kind not in kinds:
            kinds.append(kind)
    return " and ".join(kinds) or "something"


# --------------------------------------------------------------------------
# Equations, through Pandoc's Word reader
# --------------------------------------------------------------------------

MARK = "OERFORMULA%d"
CONTENT_TYPES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                 '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                 '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
                 'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
                 '<Override PartName="/word/document.xml" ContentType="application/vnd.'
                 'openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
PACKAGE_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                'relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
                'officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                '</Relationships>')


def omml_text(element):
    """An equation's OMML as text, its namespaces declared on it, the
    prefixes PowerPoint uses."""
    for prefix in ("m", "a", "a14"):
        ET.register_namespace(prefix, NS[prefix])
    return ET.tostring(element, encoding="unicode")


def stub_docx(path, equations):
    """A Word file of each equation, a paragraph each, after a paragraph
    marking which it is."""
    body = []
    for n, (element, _display, _where) in enumerate(equations):
        body.append('<w:p><w:r><w:t>%s</w:t></w:r></w:p>' % (MARK % n))
        body.append("<w:p>%s</w:p>" % omml_text(element))
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<w:document xmlns:w="%s"><w:body>%s</w:body></w:document>'
                % (W_NS, "".join(body)))
    # An accent of the macron is a bar, as a Word file's is read
    # (docxrepair.bar_accents), where texmath reads it as an overline: the
    # pptx target writes a bar so, which Narrator reads.
    document = docxrepair.bar_accents(document)[0]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES)
        zf.writestr("_rels/.rels", PACKAGE_RELS)
        zf.writestr("word/document.xml", document)


def read_tex(equations, work, pandoc="pandoc", env=None):
    """[(display, TeX) or None] for each equation, as Pandoc's Word reader
    reads its OMML: None for one it didn't, or when Pandoc couldn't read
    the file."""
    if not equations:
        return []
    folder = tempfile.mkdtemp(prefix="equations-", dir=work)
    try:
        stub = os.path.join(folder, "equations.docx")
        stub_docx(stub, equations)
        try:
            result = subprocess.run([pandoc, "-f", "docx", "-t", "json", stub],
                                    capture_output=True, text=True, env=env)
        except OSError:
            return [None] * len(equations)
        if result.returncode:
            return [None] * len(equations)
        try:
            doc = json.loads(result.stdout)
        except ValueError:
            return [None] * len(equations)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    found, current = {}, None
    for block in doc.get("blocks", []):
        if block.get("t") not in ("Para", "Plain"):
            continue
        inlines = block["c"]
        text = "".join(i.get("c", "") for i in inlines if i.get("t") == "Str")
        mark = re.fullmatch(r"OERFORMULA(\d+)", text)
        if mark:
            current = int(mark.group(1))
            continue
        maths = [i for i in inlines if i.get("t") == "Math"]
        if current is not None and len(maths) == 1:
            found[current] = (maths[0]["c"][0]["t"] == "DisplayMath", maths[0]["c"][1])
        current = None
    return [found.get(n) for n in range(len(equations))]


def place_equations(blocks, tex, equations, record):
    """Each equation's placeholder given its TeX, display math where the
    deck's is a display; one Pandoc didn't read is its characters, as
    PowerPoint's linear format writes them."""
    def walk(node):
        if isinstance(node, list):
            return [walk(item) for item in node]
        if isinstance(node, dict):
            if node.get("t") == "Math":
                mark = re.fullmatch("\x00(\\d+)\x00", node["c"][1])
                if mark:
                    n = int(mark.group(1))
                    found = tex[n] if n < len(tex) else None
                    if found is None:
                        record.lose("equation", "%s: an equation Pandoc's Word reader couldn't "
                                    "read, kept as its characters" % equations[n][2])
                        return Str(pptxremediate.equation_text(omml_text(equations[n][0])))
                    display = equations[n][1]
                    return {"t": "Math", "c": [{"t": "DisplayMath" if display else "InlineMath"},
                                               found[1]]}
            return {k: walk(v) for k, v in node.items()}
        return node
    return walk(blocks)


def split_displays(node):
    """A paragraph of nothing but display equations, as a display paragraph
    of several is read (Reader.pieces), a paragraph each, as Pandoc's
    PowerPoint writer writes them and a deck written so reads back."""
    if isinstance(node, list):
        out = []
        for item in node:
            if isinstance(item, dict) and item.get("t") in ("Para", "Plain"):
                inlines = [i for i in item["c"] if i.get("t") not in ("Space", "SoftBreak")]
                if len(inlines) > 1 and all(i.get("t") == "Math" and
                                            i["c"][0]["t"] == "DisplayMath" for i in inlines):
                    out += [{"t": item["t"], "c": [i]} for i in inlines]
                    continue
            out.append(split_displays(item))
        return out
    if isinstance(node, dict):
        return {k: split_displays(v) for k, v in node.items()}
    return node


# --------------------------------------------------------------------------
# The whole of it
# --------------------------------------------------------------------------

def read(path, base, work, alts=None, tables=None, titles=None, orders=None, pandoc="pandoc",
         api_version=None, env=None):
    """(Pandoc's JSON document, Record) for a deck: its pictures written to
    base's media/, its equations read through Pandoc."""
    reader = Reader(path, base, alts, tables, titles, orders)
    try:
        doc = reader.read()
    finally:
        reader.close()
    tex = read_tex(reader.equations, work, pandoc, env)
    doc["blocks"] = split_displays(place_equations(doc["blocks"], tex, reader.equations,
                                                   reader.record))
    doc["meta"] = place_equations(doc["meta"], tex, reader.equations, reader.record)
    if api_version:
        doc["pandoc-api-version"] = list(api_version)
    tally(doc, reader.record)
    return doc, reader.record


def api_version(pandoc="pandoc"):
    """The version of Pandoc's types the installed Pandoc writes, or None."""
    try:
        result = subprocess.run([pandoc, "-f", "markdown", "-t", "json"], input="",
                                capture_output=True, text=True)
        return json.loads(result.stdout)["pandoc-api-version"]
    except (OSError, ValueError, KeyError):
        return None


def tally(doc, record):
    """What the deck's intermediate holds, counted: pictures described and
    marked decorative, tables, equations, lists, links, and slides with
    notes."""
    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        kind = node.get("t")
        if kind == "Image":
            record.counts["decorative" if "decorative" in node["c"][0][1] else "pictures"] += 1
        elif kind == "Table":
            record.counts["tables"] += 1
        elif kind == "Math":
            record.counts["equations"] += 1
        elif kind in ("BulletList", "OrderedList"):
            record.counts["lists"] += 1
        elif kind == "Link":
            record.counts["links"] += 1
        elif kind == "Div" and "notes" in node["c"][0][1]:
            record.counts["notes"] += 1
        for value in node.values():
            if isinstance(value, (list, dict)):
                walk(value)
    walk(doc.get("blocks", []))


# What each kind of loss is, in the run's words: (WARNING or NOTE, what
# it is, what happens), the count and the decks put before it.
LOSSES = OrderedDict([
    ("hidden", ("NOTE", "hidden slide(s)", "are left out, as PowerPoint leaves a hidden slide "
                "out of a show and out of a PDF it exports")),
    ("title-slide", ("NOTE", "title slide(s) holding more than a title and a subtitle",
                     "lose the rest, since a deck's title slide is its title and subtitle in "
                     "every format a deck has, as Pandoc's slide writers make one")),
    ("chart", ("WARNING", "chart(s)", "aren't converted yet, and are left out")),
    ("smartart", ("WARNING", "SmartArt graphic(s)", "aren't converted yet, and are left out")),
    ("ole", ("WARNING", "embedded object(s) with no picture", "are left out")),
    ("object", ("WARNING", "other object(s)", "are left out")),
    ("media", ("WARNING", "video(s) and sound(s)", "aren't converted yet, and are left out")),
    ("ink", ("WARNING", "ink drawing(s)", "are left out")),
    ("picture", ("WARNING", "picture(s) linked from outside the file", "are left out")),
    ("format", ("WARNING", "picture(s) in a format a browser doesn't show",
                "are kept as they are, and a page or a presentation shows nothing for them")),
    ("crop", ("NOTE", "picture(s) a slide shows cropped", "are shown whole")),
    ("group", ("NOTE", "group(s) of shapes with alt text of their own",
               "are read a piece at a time, as a screen reader reads them in a show, and the "
               "group's alt text is left out")),
    ("link", ("NOTE", "link(s) that don't go to an address or to a slide shown",
              "are their words")),
    ("numbering", ("NOTE", "list(s) numbered in a scheme Pandoc has no style for",
                   "are numbered 1, 2, 3")),
    ("equation", ("WARNING", "equation(s) Pandoc's Word reader couldn't read",
                  "are their characters, as PowerPoint's linear format writes them")),
])


def loss_lines(records):
    """The run's lines about what converting the decks left out, a line a
    kind: [(deck file, Record)] to lines."""
    lines = []
    for kind, (severity, what, happens) in LOSSES.items():
        found = [(name, where) for name, record in records
                 for lost, where in record.losses if lost == kind]
        if not found:
            continue
        decks = len({name for name, _ in found})
        examples = "; ".join(where for _, where in found[:3]) + ("; ..." if len(found) > 3 else "")
        lines.append("%s: %d %s in %d deck(s) %s (%s)." % (
            severity, len(found), what, decks, happens, examples))
    return lines
