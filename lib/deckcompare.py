"""
deckcompare.py -- two PowerPoint decks compared for what converting one
keeps: a deck and the deck its conversion makes again, its Markdown
through a Markdown deck's pptx target, slide by slide, as
util/compare-output.py compares pages.

Each deck is read as a conversion reads it (pptxsource.py), its equations
through Pandoc's Word reader and the filter's math repair, as a page's
are; and each slide is reduced to what carries its meaning: its title;
its text, each paragraph with its formatting, links, and equations; its
lists, nested, numbered or not; its tables, their cells and header row
and column; its pictures, by their image and alt text or decorative mark;
and its notes. Where each shape sits, the theme, the layout, and the
animations don't survive the trip, by design, and aren't compared.

What the trip changes on its way, by design, is matched first, not
reported: a slide cut into more where Pandoc's PowerPoint writer would
draw a picture over its text (Title, then Title (2), or a slide with no
title into parts with none) is one slide again; a section, which the
writer makes a slide holding only its title, is a section; a heading's
line break, which a Markdown heading can't hold, is a space; and a table
whose header row is empty, which a Markdown table can't keep, has none.
What's left is reported by slide and by what differs (Difference).

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

import pptxsource

HERE = os.path.dirname(os.path.abspath(__file__))
MATH_FILTER = os.path.join(os.path.dirname(HERE), "bin", "math-repair.lua")
# A part a slide is cut into: its title, then " (2)", " (3)".
PART = re.compile(r"^(.*) \((\d+)\)$")
MARKS = {"Strong": "b", "Emph": "i", "Underline": "u", "Strikeout": "s", "SmallCaps": "sc",
         "Superscript": "sup", "Subscript": "sub"}


class Difference:
    """One thing the decks differ in: where (the slide, by its number and
    title in the first deck), what (title, text, notes, ...), and each
    deck's version of it."""

    __slots__ = ("where", "what", "first", "second")

    def __init__(self, where, what, first, second):
        self.where, self.what, self.first, self.second = where, what, first, second

    def __repr__(self):
        return "%s: %s: %r != %r" % (self.where, self.what, self.first, self.second)


# --------------------------------------------------------------------------
# A deck as what carries its meaning
# --------------------------------------------------------------------------

def marked(inlines, ids):
    """Inlines as text with their formatting as tags: <b>, <i>, <u>, <s>,
    <sc>, <sup>, <sub>, <a href> (a link within the deck by its slide's
    title), <br>, and $TeX$ or $$TeX$$; white space one space."""
    out = []
    for inline in inlines:
        kind = inline["t"]
        if kind == "Str":
            out.append(inline["c"])
        elif kind in ("Space", "SoftBreak"):
            out.append(" ")
        elif kind == "LineBreak":
            out.append("<br>")
        elif kind in MARKS:
            tag = MARKS[kind]
            out.append("<%s>%s</%s>" % (tag, marked(inline["c"], ids), tag))
        elif kind == "Math":
            fence = "$$" if inline["c"][0]["t"] == "DisplayMath" else "$"
            out.append(fence + tex_text(inline["c"][1]) + fence)
        elif kind == "Link":
            target, title = inline["c"][2]
            if target.startswith("#"):
                target = "slide:" + ids.get(target[1:], target)
            out.append('<a href="%s"%s>%s</a>' % (
                target, ' title="%s"' % title if title else "", marked(inline["c"][1], ids)))
        elif kind == "Image":
            out.append(picture(inline))
        elif kind == "Span":
            out.append(marked(inline["c"][1], ids))
        elif kind == "Quoted":
            quote = '"' if inline["c"][0]["t"] == "DoubleQuote" else "'"
            out.append(quote + marked(inline["c"][1], ids) + quote)
    return re.sub(r"\s+", " ", "".join(out)).strip()


# Greek letters as texmath writes them in TeX, which a formula made from
# text holds as the letters themselves (math.from_text): one formula to a
# reader either way.
GREEK = dict(zip(
    ("alpha beta gamma delta varepsilon zeta eta theta iota kappa lambda mu nu xi pi rho "
     "varsigma sigma tau upsilon varphi chi psi omega epsilon vartheta phi varpi varrho "
     "Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega").split(),
    "αβγδεζηθικλμνξπρςστυφχψωϵϑϕϖϱΓΔΘΛΞΠΣΥΦΨΩ"))


def tex_text(tex):
    """TeX with no white space but where it ends a control word before a
    letter, which is the only place TeX reads it, and a Greek letter's
    command as the letter."""
    out = ""
    for token in re.findall(r"\\[A-Za-z]+|\\.|\S", tex):
        token = GREEK.get(token[1:], token) if token.startswith("\\") else token
        if token[0].isalpha() and re.search(r"\\[A-Za-z]+$", out):
            out += " "
        out += token
    return out


def picture(image):
    """A picture as its image and its alt text, or the decorative mark."""
    src = image["c"][2][0].rsplit("/", 1)[-1].rsplit(".", 1)[0]
    if "decorative" in image["c"][0][1]:
        return "[picture %s, decorative]" % src
    return "[picture %s: %s]" % (src, marked(image["c"][1], {}))


def item_blocks(blocks, ids):
    """Blocks as what they hold: ("text", marked), ("list", kind, items),
    ("table", ...), each picture and paragraph its own."""
    out = []
    for block in blocks:
        kind = block["t"]
        if kind in ("Para", "Plain"):
            text = marked(block["c"], ids)
            if text:
                out.append(("text", text))
        elif kind == "BulletList":
            out.append(("list", "bullet", [item_blocks(item, ids) for item in block["c"]]))
        elif kind == "OrderedList":
            start, style, delim = block["c"][0]
            out.append(("list", "number %d %s %s" % (start, style["t"], delim["t"]),
                        [item_blocks(item, ids) for item in block["c"][1]]))
        elif kind == "Table":
            out.append(table(block, ids))
        elif kind == "Div":
            out += item_blocks(block["c"][1], ids)
        elif kind == "BlockQuote":
            out.append(("quote", item_blocks(block["c"], ids)))
    return out


def table(block, ids):
    """A table as its rows of cells' text, its header row's count, its
    header column's, and its cells' spans; an empty header row, which a
    Markdown table can't hold, is no header row."""
    _attr, _caption, _specs, head, bodies, foot = block["c"]
    rows = []

    def cells(row):
        return [(" / ".join(marked(b["c"], ids) for b in cell[4] if b["t"] in ("Para", "Plain")),
                 cell[2], cell[3]) for cell in row[1]]
    head_rows = [cells(r) for r in head[1]]
    if head_rows and all(not text for row in head_rows for text, _r, _c in row):
        head_rows = []
    rows += head_rows
    columns = 0
    for body in bodies:
        columns = max(columns, body[1])
        rows += [cells(r) for r in body[2] + body[3]]
    rows += [cells(r) for r in foot[1]]
    spans = any(r > 1 or c > 1 for row in rows for _t, r, c in row)
    return ("table", len(head_rows), columns, [[t for t, _r, _c in row] for row in rows],
            "spans" if spans else "")


class Slide:
    __slots__ = ("title", "items", "notes", "number", "section")

    def __init__(self, title, number, section=False):
        self.title, self.number, self.section = title, number, section
        self.items, self.notes = [], []

    def __repr__(self):
        return "<Slide %d %r>" % (self.number, self.title)


def heading(inlines, ids):
    """A heading's marked text, a line break a space, and line breaks in a
    row one: a Markdown heading can't hold one, and Pandoc's Markdown
    writer writes each as a space, which its reader reads as one."""
    return re.sub(r"(?:\s*<br>)+\s*", " ", marked(inlines, ids))


def slides_of(doc):
    """(title, subtitle, the title slide's notes, [Slide]) of a deck's
    intermediate."""
    meta = doc.get("meta", {})
    ids = {}
    for block in doc["blocks"]:
        if block["t"] == "Header" and block["c"][1][0]:
            ids[block["c"][1][0]] = heading(block["c"][2], {})

    def meta_text(key):
        value = meta.get(key)
        return marked(value["c"], ids) if value and value.get("t") == "MetaInlines" else ""
    slides, opening = [], []
    current = None
    # Slides as they're shown, the title slide first when there's a title
    # (a section's isn't one, in the first deck).
    number = 1 if meta_text("title") else 0
    for block in doc["blocks"]:
        kind = block["t"]
        if kind == "Header" and block["c"][0] <= pptxsource.SLIDE_LEVEL:
            section = block["c"][0] < pptxsource.SLIDE_LEVEL
            number += 0 if section else 1
            current = Slide(heading(block["c"][2], ids), number, section=section)
            slides.append(current)
            continue
        if kind == "HorizontalRule":
            number += 1
            current = Slide("", number)
            slides.append(current)
            continue
        if kind == "Div" and "notes" in block["c"][0][1]:
            notes = item_blocks(block["c"][1], ids)
            if current is None:
                opening += notes
            else:
                current.notes += notes
            continue
        if current is None:
            number += 1
            current = Slide("", number)
            slides.append(current)
        current.items += item_blocks([block], ids)
    return meta_text("title"), meta_text("subtitle"), opening, slides


# --------------------------------------------------------------------------
# Reading a deck as a conversion does
# --------------------------------------------------------------------------

def read(path, work, pandoc="pandoc", alts=None, tables=None, titles=None, orders=None):
    """A deck's intermediate, as a conversion reads it, with the sidecars'
    decisions (as pptxremediate's alt_rows() and the rest read them), and
    its math repaired as the filter repairs a page's, by default: its
    equations' characters, and math typed as text made equations
    (math.repair_equations and math.from_text)."""
    folder = tempfile.mkdtemp(prefix="compare-", dir=work)
    try:
        doc, _record = pptxsource.read(path, folder, folder, alts, tables, titles, orders,
                                       pandoc=pandoc, api_version=pptxsource.api_version(pandoc))
        source = os.path.join(folder, "deck.json")
        with open(source, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        result = subprocess.run([pandoc, "-f", "json", "-t", "json", source,
                                 "--lua-filter=" + MATH_FILTER], capture_output=True, text=True,
                                env=dict(os.environ, MATH_REPAIR_EQUATIONS="true",
                                         MATH_FROM_TEXT="true"))
        if result.returncode == 0:
            doc = json.loads(result.stdout)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return doc


# --------------------------------------------------------------------------
# Comparing
# --------------------------------------------------------------------------

def aligned(first, second):
    """[(slide of the first deck or None, [slides of the second])]: each
    of the first deck's slides with the second's that make it, a slide
    cut in parts by its parts, matched by title in order; a slide only
    one deck has paired with None or nothing. A titled slide's parts are
    titled as it is, " (2)" after; an untitled one's are untitled too,
    and are its parts while what they hold goes on with what it holds."""
    out, j = [], 0
    for i, slide in enumerate(first):
        if j < len(second) and second[j].title == slide.title:
            parts = [second[j]]
            held = list(second[j].items)
            j += 1
            following = first[i + 1].title if i + 1 < len(first) else None
            while j < len(second) and second[j].title != following:
                part = PART.match(second[j].title)
                if not (part and part.group(1) == slide.title and int(part.group(2)) >= 2):
                    break
                parts.append(second[j])
                j += 1
            while j < len(second) and not slide.title and not second[j].title \
                    and held != slide.items \
                    and slide.items[:len(held) + len(second[j].items)] == held + second[j].items:
                held += second[j].items
                parts.append(second[j])
                j += 1
            out.append((slide, parts))
            continue
        # A slide the second deck doesn't have here: matched later, if at all.
        ahead = next((k for k in range(j, len(second)) if second[k].title == slide.title), None)
        if ahead is None:
            out.append((slide, []))
            continue
        out += [(None, [extra]) for extra in second[j:ahead]]
        j = ahead
        out.append((slide, [second[j]]))
        j += 1
    out += [(None, [extra]) for extra in second[j:]]
    return out


def compare(first_doc, second_doc):
    """The differences between two decks' intermediates, as Differences."""
    title1, subtitle1, opening1, slides1 = slides_of(first_doc)
    title2, subtitle2, opening2, slides2 = slides_of(second_doc)
    found = []
    for what, a, b in (("title", title1, title2), ("subtitle", subtitle1, subtitle2),
                       ("the title slide's notes", opening1, opening2)):
        if a != b:
            found.append(Difference("the title slide", what, a, b))
    for slide, parts in aligned(slides1, slides2):
        if slide is None:
            extra = parts[0]
            found.append(Difference("slide %d of the second deck" % extra.number,
                                    "a slide only it has", None, extra.title))
            continue
        where = ("the section %s" % slide.title if slide.section else
                 "slide %d (%s)" % (slide.number, slide.title or "no title"))
        if not parts:
            found.append(Difference(where, "a slide only the first deck has", slide.title, None))
            continue
        if slide.section:
            # A section, which Pandoc's writer makes a slide of its title.
            if parts[0].items or parts[0].notes:
                found.append(Difference(where, "a section with content", [],
                                        parts[0].items + parts[0].notes))
            continue
        items = [item for part in parts for item in part.items]
        notes = [item for part in parts for item in part.notes]
        if slide.items != items:
            found.append(Difference(where, "content", slide.items, items))
        if slide.notes != notes:
            found.append(Difference(where, "notes", slide.notes, notes))
    return found


def first_difference(a, b):
    """Where two values first differ, as (a's part, b's part), for a
    report a person reads."""
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        for x, y in zip(a, b):
            if x != y:
                return first_difference(x, y)
        if len(a) != len(b):
            return (a[len(b):] or None, b[len(a):] or None)
    return (a, b)
