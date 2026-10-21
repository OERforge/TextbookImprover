"""
cnx.emit -- each baked page as an HTML file for TextbookImprover.

The baked tree is in OpenStax's shape, with their wrappers and spans;
what's written is plain HTML that Pandoc's reader takes well, and that
reads well to a person:

    the page's title the one <h1>, first, as in <title>
    a section's title an <h2> to <h6>, by its depth on the page
    a note a box, <div class="os-note ... box">, its kind and its own
        title one heading a level below where it stands ("Big Picture: A
        Global Culture?")
    a figure a <figure> with its image and a <figcaption> that reads
        "Figure 3.2 A Demand Curve for Gasoline The demand schedule ..."
    a table a <table> whose <caption> reads "Table 3.1 Price and Quantity
        Demanded of Gasoline"
    a numbered exercise a div whose first paragraph opens with its
        number, linking to its solution; a solution the same, linking back
    a term's defining use bold, with its id, for the index's links
    a glossary one <dl>
    a footnote a note as Pandoc writes one, which its reader takes back
    math MathML, unprefixed

A paragraph CNXML let hold a list, a table, or a figure is cut around
it, since HTML's can't, and its id stays with its first part. A chapter
introduction's title comes first, ahead of the chapter's opening figure
and objectives, where OpenStax puts it after them: a page's heading
opens it.

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

import collections
import copy
import unicodedata

from lxml import etree

from .bake.core import (class_test, classes, detach, has_class, prepend,
                        text_of)
from .cnxml import E, append_text
from .mathml import MATHML
from .steptables import (HEADED, head_rows, header_guess, layout_reason,
                         organizer_page, symbol_key)

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "source", "track", "wbr"}

# What a <p> can't hold: cut the paragraph around any of these.
BLOCK = {"address", "article", "aside", "blockquote", "details", "div",
         "dl", "fieldset", "figcaption", "figure", "footer", "form", "h1",
         "h2", "h3", "h4", "h5", "h6", "header", "hgroup", "hr", "main",
         "menu", "nav", "ol", "p", "pre", "section", "table", "ul"}

# Windows-1252's characters, where a source holds their codes as the C1
# controls those codes are in Unicode ("\x96" for "–"): text from Word,
# read as Latin-1 somewhere along the way. An HTML parser makes the same
# substitution for a character reference ("&#150;"); an EPUB's XHTML, a
# PDF, and a Word file don't. The five codes Windows-1252 leaves unused
# stay as they are.
def _windows_1252():
    table = {}
    for code in range(0x80, 0xA0):
        try:
            table[code] = bytes([code]).decode("cp1252")
        except UnicodeDecodeError:
            pass
    return table


C1_AS_WINDOWS_1252 = _windows_1252()

# The Symbol font's characters where Word wrote them in Unicode's private
# use area, as Windows writes a symbol font's: its code there plus F000
# (U+F061 for the font's alpha, 0x61), which no font but that one draws,
# so a PDF has nothing to draw it with. Each is the character the font
# draws, as Adobe's mapping of the font has it (unicode.org's
# VENDORS/ADOBE/symbol.txt), where that's a character of Unicode's own;
# where it's Adobe's private use, the character Unicode has since added
# (the pieces of a tall bracket or arrow, ⎛ and the rest, the radical's
# extension an overline, and ® © ™); and the horizontal line, which
# Word's users set for a dash, an em dash. Of the ten in OpenStax's
# repositories here, two are such dashes (Life, Liberty's "ailments—a
# sprained right ankle"), and the statistics books' are minus signs and
# alphas. A dingbat font, Wingdings say, writes its characters there too,
# which would be made wrong, so each one made is reported as taken for
# the Symbol font's (symbol_report). In the Connexions archive's books
# here, 659 of 660 are the Symbol font's by their sense, a Vietnamese
# book's Greek letters and relations among them, and the one left, a
# 0x34 alone in a checklist's cell, is likely a dingbat's.
SYMBOL_FONT_LOW = (
    " !\u2200#\u2203%&\u220b"  # 20
    "()\u2217+,\u2212./"  # 28
    "01234567"  # 30
    "89:;<=>?"  # 38
    "\u2245\u0391\u0392\u03a7\u0394\u0395\u03a6\u0393"  # 40
    "\u0397\u0399\u03d1\u039a\u039b\u039c\u039d\u039f"  # 48
    "\u03a0\u0398\u03a1\u03a3\u03a4\u03a5\u03c2\u03a9"  # 50
    "\u039e\u03a8\u0396[\u2234]\u22a5_"  # 58
    "\u203e\u03b1\u03b2\u03c7\u03b4\u03b5\u03c6\u03b3"  # 60
    "\u03b7\u03b9\u03d5\u03ba\u03bb\u03bc\u03bd\u03bf"  # 68
    "\u03c0\u03b8\u03c1\u03c3\u03c4\u03c5\u03d6\u03c9"  # 70
    "\u03be\u03c8\u03b6{|}\u223c"  # 78
    )
SYMBOL_FONT_HIGH = (
    "\u20ac\u03d2\u2032\u2264\u2044\u221e\u0192\u2663"  # A0
    "\u2666\u2665\u2660\u2194\u2190\u2191\u2192\u2193"  # A8
    "\u00b0\u00b1\u2033\u2265\u00d7\u221d\u2202\u2022"  # B0
    "\u00f7\u2260\u2261\u2248\u2026\u23d0\u2014\u21b5"  # B8
    "\u2135\u2111\u211c\u2118\u2297\u2295\u2205\u2229"  # C0
    "\u222a\u2283\u2287\u2284\u2282\u2286\u2208\u2209"  # C8
    "\u2220\u2207\u00ae\u00a9\u2122\u220f\u221a\u22c5"  # D0
    "\u00ac\u2227\u2228\u21d4\u21d0\u21d1\u21d2\u21d3"  # D8
    "\u25ca\u27e8\u00ae\u00a9\u2122\u2211\u239b\u239c"  # E0
    "\u239d\u23a1\u23a2\u23a3\u23a7\u23a8\u23a9\u23aa"  # E8
    "\0\u27e9\u222b\u2320\u23ae\u2321\u239e\u239f"  # F0
    "\u23a0\u23a4\u23a5\u23a6\u23ab\u23ac\u23ad"  # F8
    )
SYMBOL_FONT = {0xF020 + i: c for i, c in enumerate(SYMBOL_FONT_LOW)}
SYMBOL_FONT.update({0xF0A0 + i: c for i, c in enumerate(SYMBOL_FONT_HIGH)
                    if c != "\0"})
TEXT_FIXES = {**C1_AS_WINDOWS_1252, **SYMBOL_FONT}


def symbol_counts(text):
    """How many of each of the Symbol font's characters text holds."""
    return collections.Counter(c for c in text if ord(c) in SYMBOL_FONT)


def symbol_report(counts, where=""):
    """The report's words for the Symbol font's characters made what they
    stand for (symbol_counts), where they were if not the page's text."""
    return [f"U+{ord(char):04X} ({count}){where}, taken as the Symbol font's, made "
            f"{SYMBOL_FONT[ord(char)]} (U+{ord(SYMBOL_FONT[ord(char)]):04X}, "
            f"{unicodedata.name(SYMBOL_FONT[ord(char)], '').lower()})"
            for char, count in sorted(counts.items())]

# Attributes baking used and a reader has no use for.
INTERNAL = {"data-type", "data-depth", "data-baked", "data-label-from",
            "data-module", "data-uuid", "data-uuid-key", "data-content-class",
            "data-title-moved", "data-print-placement", "data-rex-keep",
            "data-label", "data-display", "data-alt", "data-media-type",
            "data-summary", "data-document", "data-note-type",
            "data-element-type", "itemprop", "data-lang", "data-colwidths",
            "data-target-id", "data-url", "data-pub-type", "data-frame",
            "data-case", "data-reference", "data-index", "data-name",
            "data-aria-label"}

class Emitter:
    """Writes the pages of one book. `labels` are baking's link texts;
    `titles` each page's title by name, for links that still need
    text."""

    def __init__(self, book, pages, language, report, boxes=True):
        self.book = book
        self.pages = pages
        self.language = language
        self.report = report
        # Whether a note is a box (class box), as TextbookImprover draws
        # one in every format; and how many were, and how many that baking
        # headed by their kind and their own title were headed by one
        # heading: the two, the kind alone, or the title alone.
        self.boxes = boxes
        self.boxed = 0
        self.merged_titles = 0
        self.kind_alone = 0
        self.title_alone = 0
        self.by_name = {p.name: p for p in pages}
        # (page, label, caption text, summary, layout, the words of its
        # body's cells by row, place, excerpt): place is the table's number
        # among its page's tables as TextbookImprover counts them, the key
        # it reports a table with no label under.
        self.tables = []
        self._placing = []       # this page's: (index in tables, element)

    # the page ---------------------------------------------------------

    def page_html(self, page):
        el = page.element
        html = E("html", {"lang": self.language,
                          "xml:lang": None})
        head = E("head")
        head.append(E("meta", {"charset": "utf-8"}))
        head.append(E("title", None, page.title))
        html.append(head)
        body = E("body")
        html.append(body)
        h1 = E("h1", None, page.title)
        title_el = self._own_title(el)
        body.append(h1)
        work = copy.deepcopy(el)
        # The page's title is the h1 above; take it (and an intro's moved
        # one) out of the content.
        for old in work.xpath("./*[@data-type='document-title'] | "
                              "./*[@data-type='title'] | "
                              ".//*[contains(@id, '_titlecreatedbycookbook')]"):
            if old.get("id") and "_titlecreatedbycookbook" not in old.get("id"):
                h1.set("id", old.get("id"))
            detach(old)
        for meta in work.xpath("./div[@data-type='metadata']"):
            detach(meta)
        if title_el is not None and title_el.get("id") and \
                "_titlecreatedbycookbook" not in title_el.get("id"):
            h1.set("id", title_el.get("id"))
        if el.get("lang") and el.get("lang") != self.language:
            body.set("lang", el.get("lang"))
        self._placing = []
        self.convert_children(work, body, 1, page)
        drop_empty_headings(body)
        split_paragraphs(body)
        for words in symbol_report(finish(body)):
            self.report(page.name, "symbol-font-character", words)
        places = table_places(body)
        for index, table in self._placing:
            place = places.get(table)
            self.tables[index] += (place,
                                   table_excerpt(table) if place else "")
        return html

    def _own_title(self, el):
        for child in el:
            if isinstance(child.tag, str) and child.get("data-type") in (
                    "document-title", "title"):
                return child
        return None

    # walking ----------------------------------------------------------

    def convert_children(self, src, dst, level, page):
        append_text(dst, src.text)
        for child in list(src):
            if not isinstance(child.tag, str):
                append_text(dst, child.tail)
                continue
            self.convert(child, dst, level, page)
            append_text(dst, child.tail)

    def convert(self, el, dst, level, page):
        if etree.QName(el).namespace == MATHML:
            dst.append(copy.deepcopy(_without_tail(el)))
            return
        tag = el.tag
        dtype = el.get("data-type")
        cls = classes(el)
        handler = None
        if dtype:
            handler = getattr(self, "dt_" + dtype.replace("-", "_"), None)
        if handler is None and tag in ("section",):
            handler = self.section
        if handler is None and tag == "figure":
            handler = self.figure
        if handler is None and tag == "div":
            for c in cls:
                handler = getattr(self, "div_" + c.replace("-", "_"), None)
                if handler:
                    break
        if handler is None and tag == "a":
            handler = self.link
        if handler is None and tag == "table":
            handler = self.table_alone
        if handler is None and tag == "cite":
            # A citation's words; Pandoc's reader keeps nothing more of a
            # <cite>.
            handler = self.convert_children
        if handler is None and tag == "ul" and "os-abstract" in cls \
                and _numbered_by_place(el):
            handler = self.objectives
        if handler is not None:
            handler(el, dst, level, page)
            return
        out = E(tag)
        for key, value in el.attrib.items():
            if key not in INTERNAL:
                out.set(key, value)
        self.convert_children(el, out, level, page)
        dst.append(out)

    def objectives(self, el, dst, level, page):
        """Learning objectives that baking numbers by their place alone
        (BakeLearningObjectives.v2's count_only_li, Principles of
        Marketing's "1 Define and describe marketing."): a numbered list
        whose numbers are its own. Baking writes each number as a token
        in an item of a bulleted list, whose bullets OpenStax's stylesheet
        hides and a converted page would show beside the numbers.
        Objectives numbered with their section's number (1.1.1) keep it,
        bulleted, as a list can't number so."""
        out = E("ol")
        for key, value in el.attrib.items():
            if key not in INTERNAL:
                out.set(key, value)
        for li in el:
            if not isinstance(li.tag, str):
                continue
            item = E("li")
            for key, value in li.attrib.items():
                if key not in INTERNAL:
                    item.set(key, value)
            for child in li:
                if not isinstance(child.tag, str) \
                        or has_class(child, "os-abstract-token"):
                    continue
                if has_class(child, "os-abstract-content"):
                    self.convert_children(child, item, level, page)
                else:
                    self.convert(child, item, level, page)
                append_text(item, child.tail)
            out.append(item)
        dst.append(out)

    def heading(self, level, attrib=None):
        return E(f"h{min(max(level, 1), 6)}", attrib)

    # structure --------------------------------------------------------

    def section(self, el, dst, level, page):
        if el.get("role") == "doc-endnotes":
            # The page's footnotes, as Pandoc writes them, for its reader
            # to take back as notes.
            out = E("section", {"role": "doc-endnotes",
                                "class": el.get("class")})
            self.convert_children(el, out, level, page)
            dst.append(out)
            return
        title = [c for c in el if isinstance(c.tag, str)
                 and c.get("data-type") == "title"]
        if not title:
            # A page's numbered title, which baking put at the head of a
            # section whose own it took away (BakeReferences.v3's "3.2 The
            # Cytoplasm and Cellular Organelles"), is its heading, and
            # loses the spans baking wrote it in, as a title does.
            title = [c for c in el if isinstance(c.tag, str)
                     and c.get("data-type") == "document-title"][:1]
        if not title or _empty_title(title[0]):
            # A section with no title, or an empty one (<title/>), is no
            # level of the outline: what it holds stands at its parent's
            # level, where a heading of its own would skip one.
            for name in [el.get("id")] + [t.get("id") for t in title]:
                if name:
                    dst.append(E("div", {"id": name}, ""))
            append_text(dst, el.text)
            for child in el:
                if not isinstance(child.tag, str):
                    append_text(dst, child.tail)
                    continue
                if not title or child is not title[0]:
                    self.convert(child, dst, level, page)
                append_text(dst, child.tail)
            return
        title = title[0]
        heading = self.heading(level + 1, {"id": el.get("id")})
        if title.get("id") and el.get("id"):
            heading.append(E("span", {"id": title.get("id")}, ""))
        elif title.get("id"):
            heading.set("id", title.get("id"))
        self.convert_children(title, heading, level, page)
        _flatten_spans(heading)
        dst.append(heading)
        append_text(dst, el.text)
        for child in el:
            if not isinstance(child.tag, str):
                append_text(dst, child.tail)
                continue
            if child is not title:
                self.convert(child, dst, level + 1, page)
            append_text(dst, child.tail)

    def dt_abstract(self, el, dst, level, page):
        """Learning objectives: their heading a level below the page's."""
        out = E("div", {"class": "os-learning-objectives"})
        heading = el.xpath("./*[@data-type='title']")
        if heading:
            h = self.heading(level + 1)
            h.text = text_of(heading[0])
            out.append(h)
            detach(heading[0])
        self.convert_children(el, out, level + 1, page)
        dst.append(out)

    def dt_note(self, el, dst, level, page):
        if not classes(el) and not el.xpath("./*[@data-type='title']") \
                and any(a.tag == "section" and has_class(a, "references")
                        for a in el.iterancestors()):
            # An endnote (Principles of Marketing writes each reference
            # as a note): a paragraph, its number first.
            out = E("p", {"class": "os-reference", "id": el.get("id")})
            body = el.xpath("./div[@class='os-note-body']")
            self.convert_children(body[0] if body else el, out, level, page)
            dst.append(out)
            return
        # A note is a box, which TextbookImprover draws in every format,
        # as OpenStax's stylesheets set every note apart: a border on a page
        # and in an EPUB and a Word file, rules above and below in a PDF.
        # But not a reference, which a book of the business styles writes
        # as a note, each an entry of its references page.
        names = ["os-note"] + classes(el)
        if self.boxes and "reference" not in names:
            names.append("box")
            self.boxed += 1
        out = E("div", {"class": " ".join(names), "id": el.get("id")})
        if el.get("lang"):
            out.set("lang", el.get("lang"))
        inner_level = level
        label = None
        for child in list(el):
            if not isinstance(child.tag, str):
                continue
            if child.get("data-type") == "title" and has_class(child,
                                                               "os-title"):
                h = self.heading(level + 1)
                self.convert_children(child, h, level, page)
                _flatten_spans(h)
                out.append(h)
                inner_level = level + 1
                detach(child)
                if text_of(h):
                    label = h
        body = el.xpath("./div[@class='os-note-body']")
        holder = body[0] if body else el
        for child in list(holder):
            if (isinstance(child.tag, str) and has_class(child, "os-subtitle")
                    and _empty_title(child)):
                # A note's empty title (*Physics*' worked example 22.3,
                # <title/>): no heading, so none a level down for what
                # the note holds, its ids kept.
                for named in child.iter():
                    if isinstance(named.tag, str) and named.get("id"):
                        out.append(E("span", {"id": named.get("id")}, ""))
                detach(child)
            elif (isinstance(child.tag, str)
                    and has_class(child, "os-subtitle") and label is not None):
                # The note's kind, its label, and its own title are one
                # heading ("Big Picture: A Global Culture?"), where they had
                # been a heading with only the title under it: a screen
                # reader's list of a book's headings named each kind as
                # often as it was used, each title a level below. A title
                # that only repeats the kind (Physics' "Teacher Support")
                # leaves the kind alone, and one that opens with the kind
                # ("Try It: The nth Term…" under "Try it") stands alone.
                kind, own = text_of(label).casefold(), text_of(child).casefold()
                if own == kind:
                    # What a link may name in the title (a term the index
                    # links to) stays, an anchor in the heading.
                    for named in child.iter():
                        if isinstance(named.tag, str) and named.get("id"):
                            label.append(E("span", {"id": named.get("id")}, ""))
                    self.kind_alone += 1
                else:
                    if own.startswith(kind) and \
                            not own[len(kind):len(kind) + 1].isalnum():
                        # The label's words go, what a link may name in
                        # them kept, an anchor in the heading.
                        named = [part.get("id") for part in label.iter()
                                 if part is not label and isinstance(part.tag, str)
                                 and part.get("id")]
                        label.text = None
                        for part in list(label):
                            label.remove(part)
                        for name in named:
                            label.append(E("span", {"id": name}, ""))
                        self.title_alone += 1
                    else:
                        _merge_title(label)
                        self.merged_titles += 1
                    self.convert_children(child, label, level, page)
                    _flatten_spans(label)
                    if child.get("id"):
                        label.append(E("span", {"id": child.get("id")}, ""))
                detach(child)
            elif (isinstance(child.tag, str)
                    and has_class(child, "os-subtitle")):
                h = self.heading(inner_level + 1)
                if child.get("id"):
                    h.set("id", child.get("id"))
                self.convert_children(child, h, level, page)
                _flatten_spans(h)
                out.append(h)
                inner_level += 1
                detach(child)
            break
        if not body:
            # A note with its own title left unbaked (a generic book).
            for child in list(el):
                if isinstance(child.tag, str) and \
                        child.get("data-type") == "title":
                    h = self.heading(inner_level + 1)
                    self.convert_children(child, h, level, page)
                    out.append(h)
                    inner_level += 1
                    detach(child)
                break
        self.convert_children(holder, out, inner_level, page)
        dst.append(out)

    def div_os_note_body(self, el, dst, level, page):
        self.convert_children(el, dst, level, page)

    def div_intro_body(self, el, dst, level, page):
        self.convert_children(el, dst, level, page)

    def div_intro_text(self, el, dst, level, page):
        self.convert_children(el, dst, level, page)

    def titled_div(self, el, dst, level, page, cls):
        out = E("div", {"class": " ".join([cls] + classes(el)),
                        "id": el.get("id")})
        inner = level
        for child in list(el):
            # A commentary's title in an example, baked, is marked
            # commentary-title.
            if isinstance(child.tag, str) and \
                    child.get("data-type") in ("title", "commentary-title"):
                h = self.heading(level + 1)
                if child.get("id"):
                    h.set("id", child.get("id"))
                self.convert_children(child, h, level, page)
                _flatten_spans(h)
                out.append(h)
                inner = level + 1
                detach(child)
            break
        self.convert_children(el, out, inner, page)
        dst.append(out)

    def dt_example(self, el, dst, level, page):
        """An example: its heading ("Example 2.3", or its own title in a
        book no recipe baked), then, baked, its own title a level down,
        inside the body baking wrapped it in."""
        bodies = el.xpath(f"./div[{class_test('body')}]")
        if not bodies:
            self.titled_div(el, dst, level, page, "os-example")
            return
        out = E("div", {"class": " ".join(["os-example"] + classes(el)),
                        "id": el.get("id")})
        inner = level
        for child in list(el):
            if isinstance(child.tag, str) and \
                    child.get("data-type") == "title":
                h = self.heading(level + 1)
                self.convert_children(child, h, level, page)
                _flatten_spans(h)
                out.append(h)
                inner = level + 1
                detach(child)
            break
        for child in list(bodies[0]):
            if isinstance(child.tag, str) and \
                    child.get("data-type") == "title":
                h = self.heading(inner + 1)
                if child.get("id"):
                    h.set("id", child.get("id"))
                self.convert_children(child, h, level, page)
                _flatten_spans(h)
                out.append(h)
                inner += 1
                detach(child)
            break
        append_text(out, el.text)
        for child in el:
            if not isinstance(child.tag, str):
                append_text(out, child.tail)
                continue
            if child is bodies[0]:
                self.convert_children(child, out, inner, page)
            else:
                self.convert(child, out, inner, page)
            append_text(out, child.tail)
        dst.append(out)

    def dt_rule(self, el, dst, level, page):
        self.titled_div(el, dst, level, page, "os-rule")

    def dt_statement(self, el, dst, level, page):
        self.titled_div(el, dst, level, page, "os-statement")

    def dt_proof(self, el, dst, level, page):
        self.titled_div(el, dst, level, page, "os-proof")

    def dt_commentary(self, el, dst, level, page):
        self.titled_div(el, dst, level, page, "os-commentary")

    def dt_definition(self, el, dst, level, page):
        out = E("div", {"class": "os-definition", "id": el.get("id")})
        self.convert_children(el, out, level, page)
        dst.append(out)

    # exercises --------------------------------------------------------

    def dt_exercise(self, el, dst, level, page):
        self.titled_div(el, dst, level, page, "os-exercise")

    def dt_problem(self, el, dst, level, page):
        self._numbered(el, dst, level, page, "os-problem",
                       "os-problem-container")

    def dt_solution(self, el, dst, level, page):
        self._numbered(el, dst, level, page, "os-solution",
                       "os-solution-container")

    def _numbered(self, el, dst, level, page, cls, container_cls):
        """A problem or solution baking numbered: the number (a link, when
        there's somewhere to go) opens its first paragraph. Whatever else
        it holds after its content (a question's solution, when no answer
        key took it) follows."""
        out = E("div", {"class": cls, "id": el.get("id")})
        # A number may have a word before it, the two one link: "Problem
        # 1-1" (Organic Chemistry's problem_with_prefix).
        number = el.xpath("./*[" + class_test("os-number") + " or "
                          + class_test("os-prefix") + "]")
        divider = el.xpath("./*[" + class_test("os-divider") + "]")
        label = el.xpath("./*[" + class_test("os-title-label") + "]")
        # A set's prefix before an exercise's number ("EA", Principles of
        # Accounting's BakeExercisePrefixes).
        prefix = el.xpath("./span[" + class_test("os-text") + "]")
        container = el.xpath(f"./div[{class_test(container_cls)}]")
        if not container:
            self.titled_div(el, dst, level, page, cls)
            return
        titles = el.xpath("./*[@data-type='problem-title' or "
                          "@data-type='solution-title']")
        rest = [c for c in el if isinstance(c.tag, str)
                and c not in number + divider + label + container + titles
                + prefix]
        if titles or not (number or divider or label):
            # An example's problem and solution, under "Problem" and
            # "Solution"; or an exercise baking left unnumbered (a note's).
            inner = level
            if titles:
                h = self.heading(level + 1)
                h.text = text_of(titles[0])
                out.append(h)
                inner = level + 1
            self.convert_children(container[0], out, inner, page)
            _paragraphs(out)
            for child in rest:
                self.convert(child, out, inner, page)
            dst.append(out)
            return
        lead = E("span", {"class": "os-number-lead"})
        for part in prefix + label + number + divider:
            detach(part)
        for part in prefix:
            lead.append(E("span", {"class": "os-number-prefix"},
                          text_of(part) + " "))
        for part in label:
            lead.append(E("span", {"class": "os-title-label"},
                          text_of(part) + " "))
        for part in number:
            if part.tag == "a":
                link = E("a", {"href": part.get("href"),
                               "class": "os-number"})
                link.text = text_of(part)
                self.link(link, lead, level, page)
            else:
                lead.append(E("span", {"class": "os-number"},
                              text_of(part)))
        for part in divider:
            append_text(lead, part.text or "")
        if not divider:
            # An appendix's exercise has no divider after its number;
            # OpenStax sets the problem below it, a paragraph here.
            append_text(lead, " ")
        self.convert_children(container[0], out, level, page)
        _paragraphs(out)
        _lead_into_first_paragraph(out, lead)
        for child in rest:
            self.convert(child, out, level, page)
        dst.append(out)

    def dt_local_interactive(self, el, dst, level, page):
        """A frame of the repository's own (a code runner): a link to the
        page of the online book, where it runs, for an OpenStax book;
        words saying what was there, for another."""
        slug = self.book.body.get("data-slug")
        text = text_of(el) or "Interactive"
        if self.book.body.get("data-style") and slug:
            link = E("a", {"href": f"https://openstax.org/books/{slug}/"
                                   f"pages/{page.name}"})
            link.text = f"{text} (in the online book at openstax.org)"
            dst.append(link)
        else:
            append_text(dst, f"[{text}: shown in the online version]")

    # exercises from OpenStax's exercise bank ----------------------------

    def dt_injected_exercise(self, el, dst, level, page):
        out = E("div", {"class": "os-exercise", "id": el.get("id")})
        self.convert_children(el, out, level, page)
        dst.append(out)

    def dt_exercise_question(self, el, dst, level, page):
        """A question: its number opening its stem, then its choices."""
        self._numbered(el, dst, level, page, "os-problem",
                       "os-problem-container")

    def dt_question_solution(self, el, dst, level, page):
        """A question's solution: its number, the letter of the right
        choice, and the worked answer."""
        self._numbered(el, dst, level, page, "os-solution",
                       "os-solution-container")

    def dt_alphabetical_question_multipart(self, el, dst, level, page):
        """A lettered part of a question: its letter opening its stem."""
        self._lettered(el, dst, level, page, "os-problem-part",
                       "os-problem-container")

    def dt_solution_part(self, el, dst, level, page):
        """A lettered part's solution, its letter first."""
        self._lettered(el, dst, level, page, "os-solution-part",
                       "os-solution-container")

    def _lettered(self, el, dst, level, page, cls, container_cls):
        out = E("div", {"class": cls, "id": el.get("id")})
        container = el.xpath(f"./div[{class_test(container_cls)}]")
        holder = container[0] if container else el
        marks = el.xpath("./*[" + class_test("problem-letter") + "]") or \
            holder.xpath("./*[" + class_test("problem-letter") + "]")
        lead = E("span", {"class": "os-number-lead"})
        for mark in marks[:1]:
            after = mark.getnext()
            if mark.tag == "a":
                link = E("a", {"href": mark.get("href"),
                               "class": "problem-letter"})
                link.text = text_of(mark)
                self.link(link, lead, level, page)
            else:
                lead.append(E("span", {"class": "problem-letter"},
                              text_of(mark)))
            append_text(lead, " ")
            detach(mark)
            if after is not None and has_class(after, "os-divider"):
                detach(after)
        rest = [c for c in el if isinstance(c.tag, str)
                and c is not holder] if holder is not el else []
        self.convert_children(holder, out, level, page)
        _paragraphs(out)
        if marks:
            _lead_into_first_paragraph(out, lead)
        for child in rest:
            self.convert(child, out, level, page)
        dst.append(out)

    def _blocks(self, el, dst, level, page):
        """Content the bank wrote, maybe bare words: as paragraphs."""
        holder = E("div")
        self.convert_children(el, holder, level, page)
        _paragraphs(holder)
        append_text(dst, holder.text)
        for child in list(holder):
            dst.append(child)

    def dt_question_stem(self, el, dst, level, page):
        self._blocks(el, dst, level, page)

    def dt_question_stimulus(self, el, dst, level, page):
        self._blocks(el, dst, level, page)

    def dt_exercise_stimulus(self, el, dst, level, page):
        self._blocks(el, dst, level, page)

    def dt_question_answers(self, el, dst, level, page):
        out = E("ol", {"type": "a", "class": "os-choices"})
        for item in el:
            if isinstance(item.tag, str):
                li = E("li")
                self.convert_children(item, li, level, page)
                out.append(li)
        dst.append(out)

    def dt_answer_content(self, el, dst, level, page):
        self.convert_children(el, dst, level, page)

    def dt_exercise_context(self, el, dst, level, page):
        out = E("p", {"class": "os-exercise-context"})
        self.convert_children(el, out, level, page)
        dst.append(out)

    def div_os_solution_area(self, el, dst, level, page):
        """A section's solutions in the answer key, under its title: a
        title of its own, or a page's numbered title, bare or in a div
        (MoveSolutionsFromAutotitledNote.v2's "1.1 Real Numbers")."""
        for child in el:
            if not isinstance(child.tag, str):
                continue
            title = _area_title(child)
            if title is not None:
                h = self.heading(level + 1)
                h.text = text_of(title)
                dst.append(h)
            else:
                self.convert(child, dst, level + 1, page)

    def div_os_module_reset_solution_area(self, el, dst, level, page):
        """The answer key's area for one kind of note's solutions ("Try
        It"), a page's at a time, each a solution area in it."""
        self.div_os_solution_area(el, dst, level, page)

    def div_os_eos(self, el, dst, level, page):
        """A section's exercises at its end, under the title baking gave
        them ("1.2 Section Exercises"), their own sections a level down."""
        self.div_os_solution_area(el, dst, level, page)

    def div_os_chapter_outline(self, el, dst, level, page,
                               cls="os-chapter-outline"):
        """A chapter's outline, its sections each a link, under its own
        heading."""
        out = E("div", {"class": cls})
        for child in el:
            if not isinstance(child.tag, str):
                continue
            if has_class(child, "os-title"):
                h = self.heading(level + 1)
                h.text = text_of(child)
                out.append(h)
            else:
                self.convert(child, out, level + 1, page)
        dst.append(out)

    def div_os_handbook_outline(self, el, dst, level, page):
        """A handbook's outline (*Writing Guide*'s), as a chapter's."""
        self.div_os_chapter_outline(el, dst, level, page,
                                    cls="os-handbook-outline")

    # figures ----------------------------------------------------------

    def figure(self, el, dst, level, page):
        out = E("figure", {"id": el.get("id"),
                           "class": el.get("class")})
        caption = None
        for child in el:
            if not isinstance(child.tag, str):
                continue
            if child.tag == "figcaption":
                caption = child
                continue
            if child.get("data-type") == "title":
                continue
            self.convert(child, out, level, page)
        if caption is not None:
            fc = E("figcaption")
            self._caption_parts(caption, fc, level, page)
            out.append(fc)
        dst.append(out)

    def _caption_parts(self, container, dst, level, page):
        """The spans baking put in a caption, as words: "Figure 3.2 A
        Demand Curve for Gasoline The demand schedule ...", the label,
        title, and caption each a span of its own."""
        label = []
        parts = []
        for child in container:
            if not isinstance(child.tag, str):
                continue
            c = classes(child)
            if "os-title-label" in c or "os-number" in c:
                label.append(text_of(child))
            elif "os-divider" in c:
                continue
            elif "os-title" in c:
                parts.append(("os-title", child))
            elif "os-caption" in c:
                parts.append(("os-caption", child))
            else:
                parts.append((None, child))
        if label:
            dst.append(E("span", {"class": "os-label"},
                         " ".join(" ".join(label).split())))
        for cls, child in parts:
            if dst.text or len(dst):
                append_text(dst, " ")
            if cls is None:
                self.convert(child, dst, level, page)
                continue
            out = E("span", {"class": cls})
            self.convert_children(child, out, level, page)
            _strip_edges(out)
            dst.append(out)

    def dt_media(self, el, dst, level, page):
        """What a media element holds, with the element's id, which a link
        can name (Calculus Volume 1's "See ... the Richter scale"): on the
        picture or video it holds, or an anchor before what it holds."""
        start = len(dst)
        self.convert_children(el, dst, level, page)
        if not el.get("id"):
            return
        made = [c for c in dst[start:] if isinstance(c.tag, str)]
        if len(made) == 1 and not made[0].get("id"):
            made[0].set("id", el.get("id"))
        else:
            dst.insert(start, E("span", {"id": el.get("id")}, ""))

    # tables -----------------------------------------------------------

    def div_os_table(self, el, dst, level, page):
        table = el.xpath("./table")
        container = el.xpath("./div[" + class_test("os-caption-container")
                             + "]")
        # The title above it: a top-titled table's head row, or a
        # top-captioned one's caption title (a Polish book's).
        title = el.xpath("./div[" + class_test("os-table-title") + " or "
                         + class_test("os-top-caption") + "]")
        if not table:
            self.convert_children(el, dst, level, page)
            return
        out = E("table", {"id": table[0].get("id"),
                          "class": table[0].get("class")})
        label = None
        if container:
            numbered = container[0].xpath(
                "./span[" + class_test("os-title-label") + " or "
                + class_test("os-number") + "]")
            if numbered:
                label = " ".join(" ".join(text_of(n) for n in numbered)
                                 .split())
        if container or title:
            caption = E("caption")
            if title:
                self.convert_children(title[0], caption, level, page)
            if container:
                if caption.text or len(caption):
                    append_text(caption, " ")
                self._caption_parts(container[0], caption, level, page)
            out.append(caption)
        for child in table[0]:
            if isinstance(child.tag, str) and child.tag != "caption":
                self.convert(child, out, level, page)
        caption = out.find("caption")
        # An inquiry organizer's key to the emoji in its book's page titles
        # is headed by them, row by row; the organizer itself is laid out.
        organizer = organizer_page(self.book.style, page.title)
        if organizer and symbol_key(out):
            head_rows(out)
        layout = self._layout(out, table[0], page, caption is not None and " ".join(
            text_of(caption).split()) not in ("", label), organizer)
        self._record(out, table[0], page, label, layout)
        dst.append(out)

    def table_alone(self, el, dst, level, page):
        """A table outside OpenStax's container (div_os_table), where
        baking leaves it: one of no class, which no recipe numbers or
        wraps, in an exercise's solution in the answer key (the economics
        books' 6, Prealgebra 2e's 1, Elementary Algebra 2e's 1); an
        unnumbered one in a style whose recipe doesn't bake one
        (BakeUnnumberedTables; 16 styles, among them ap-physics, whose
        College Physics for AP Courses 2e has 2 in its test prep, the only
        ones in the 67 books); and CALS's entrytbl, a table in another's
        cell. Decided and listed as a contained table is, its caption, if
        it has one, its own, so its summary is drafted as its
        description."""
        out = E("table")
        for key, value in el.attrib.items():
            if key not in INTERNAL:
                out.set(key, value)
        self.convert_children(el, out, level, page)
        caption = out.find("caption")
        organizer = organizer_page(self.book.style, page.title)
        if organizer and symbol_key(out):
            head_rows(out)
        layout = self._layout(out, el, page, caption is not None and bool(
            " ".join(text_of(caption).split())), organizer)
        self._record(out, el, page, None, layout)
        dst.append(out)

    def _record(self, out, source, page, label, layout):
        """A table in the book's list: its caption's text, its summary,
        whether it's laid out, and its cells' words, for the sidecars the
        unpacker drafts (cnx.project); its place on the page is counted
        once the page is whole."""
        caption = out.find("caption")
        self._placing.append((len(self.tables), out))
        self.tables.append((page.name, label,
                            text_of(caption) if caption is not None else "",
                            source.get("data-summary") or "", layout,
                            [[text_of(cell) for cell in row if cell.tag in ("td", "th")]
                             for row in out.xpath("./tbody/tr | ./tr | ./tfoot/tr")]))

    def _layout(self, out, source, page, captioned, organizer=False):
        """Whether a table is a layout table, given role="presentation"
        (cnx.steptables): for what it holds, a box of one cell, a form of
        lines to fill in, pictures with their labels, or a matching
        exercise; for the page it's on, an inquiry organizer (organizer);
        for where it stands, a worked example's steps, a Key Equations
        table, or a grid of key terms, unless the header guess reads a
        header row in it, which leaves it a data table, reported.
        OpenStax's HTML marks a table so only when it has no label of
        OpenStax's (aria-label), with which a browser would ignore the
        role. The labels, written in 2023 from the tables' summaries,
        describe a table as a picture, at length ("The top row of this
        table, which is a header row, contains..."). None is written:
        TextbookImprover's description of a table is its caption, which
        every format carries, and a screen reader would read a label on
        entering the table, before its caption. Each is in the report."""
        name = out.get("id") or "a table"
        layout = False
        reason = layout_reason(out, source, self.book.style, captioned, organizer)
        if reason in ("shape", "page"):
            layout = True
            out.set("role", "presentation")
        elif reason == "place":
            guess = header_guess(out)
            layout = guess not in HEADED
            if layout:
                out.set("role", "presentation")
            else:
                first = " | ".join(" ".join(text_of(c).split())
                                   for c in out.xpath("(.//tr)[1]/td"))
                self.report(page.name, "table-kept-as-data",
                            f"{name} (\u201c{first}\u201d): the header guess reads a "
                            f"header row in it ({guess})")
        label = source.get("data-aria-label")
        if label:
            self.report(page.name, "table-label-left-out",
                        f"{name}" + (", a layout table" if layout else "") + f": {label}")
        return layout

    # glossaries, indexes, summaries -----------------------------------

    def div_os_glossary_list(self, el, dst, level, page):
        dl = E("dl", {"class": "os-glossary"})
        for item in el.xpath("./div/dl"):
            self._definition(item, dl, level, page)
        _join_repeated_terms(dl)
        dst.append(dl)

    def _definition(self, item, dl, level, page):
        """A definition's dt and dd, its id (which a dl holding one
        definition can't keep in a list of many) on a span in its term."""
        first = True
        for child in item:
            if not isinstance(child.tag, str):
                continue
            start = len(dl)
            self.convert(child, dl, level, page)
            if first and item.get("id") and len(dl) > start:
                anchor = E("span", {"id": item.get("id")}, "")
                prepend(dl[start], anchor)
            first = False

    def dt_glossary(self, el, dst, level, page):
        """A glossary no recipe moved: kept at the page's end, under a
        heading of its own."""
        h = self.heading(level + 1)
        h.text = "Glossary"
        dst.append(h)
        dl = E("dl", {"class": "os-glossary"})
        for item in el.xpath("./dl"):
            self._definition(item, dl, level, page)
        _join_repeated_terms(dl)
        dst.append(dl)

    def div_group_by(self, el, dst, level, page):
        label = el.xpath("./span[@class='group-label']")
        h = self.heading(level + 1)
        h.text = text_of(label[0]) if label else ""
        dst.append(h)
        ul = E("ul", {"class": "os-index"})
        for item in el.xpath("./div[@class='os-index-item']"):
            li = E("li")
            self.convert_children(item, li, level, page)
            ul.append(li)
        dst.append(ul)

    def div_os_chapter_area(self, el, dst, level, page):
        for child in el:
            if not isinstance(child.tag, str):
                continue
            if child.get("data-type") == "document-title":
                h = self.heading(level + 1)
                h.text = text_of(child)
                dst.append(h)
            elif child.tag == "a" and \
                    child.xpath("./*[@data-type='document-title']"):
                # The chapter's title as a link to it (BakeReferences.v4):
                # a heading holding the link, as a summary's is.
                self.dt_section_link(child, dst, level, page)
            else:
                self.convert(child, dst, level + 1, page)

    def dt_section_link(self, el, dst, level, page):
        """A summary's title, linking to its section."""
        heading = el.xpath("./*[@data-type='document-title']")
        h = self.heading(level + 1)
        link = E("a", {"href": el.get("href")})
        link.text = text_of(heading[0]) if heading else text_of(el)
        self.link(link, h, level, page)
        dst.append(h)

    # inline -----------------------------------------------------------

    def dt_term(self, el, dst, level, page):
        cls = classes(el)
        plain = "no-emphasis" in cls or ("no" in cls and "emphasis" in cls)
        inner = E("span", {"class": "os-term", "id": el.get("id")})
        self.convert_children(el, inner, level, page)
        if plain:
            dst.append(inner)
        else:
            strong = E("strong")
            strong.append(inner)
            dst.append(strong)

    def dt_title(self, el, dst, level, page):
        """A paragraph's title, run in, with its id, which a link can
        name (Statistics' labs: "the Procedure section")."""
        strong = E("strong", {"id": el.get("id")})
        self.convert_children(el, strong, level, page)
        dst.append(strong)
        append_text(dst, " ")

    def dt_list_title(self, el, dst, level, page):
        p = E("p", {"class": "os-list-title", "id": el.get("id")})
        strong = E("strong")
        self.convert_children(el, strong, level, page)
        p.append(strong)
        dst.append(p)

    def dt_label(self, el, dst, level, page):
        self.convert_children(el, dst, level, page)

    def dt_list(self, el, dst, level, page):
        out = E("span", {"class": "os-inline-list", "id": el.get("id")})
        self.convert_children(el, out, level, page)
        dst.append(out)

    def dt_item(self, el, dst, level, page):
        self.convert_children(el, dst, level, page)

    def dt_cite_title(self, el, dst, level, page):
        """The title of a work cited, a journal's or a newspaper's in the
        books seen, in italics, as such a title is set. (Pandoc's reader
        drops a <cite> and keeps nothing of it but its words.)"""
        out = E("em")
        self.convert_children(el, out, level, page)
        dst.append(out)

    def dt_foreign(self, el, dst, level, page):
        out = E("span", {"lang": el.get("lang")})
        self.convert_children(el, out, level, page)
        dst.append(out)

    def link(self, el, dst, level, page):
        out = E("a")
        for key, value in el.attrib.items():
            if key not in INTERNAL:
                out.set(key, value)
        if out.get("class"):
            kept = [c for c in out.get("class").split()
                    if c not in ("autogenerated-content",)]
            if kept:
                out.set("class", " ".join(kept))
            else:
                del out.attrib["class"]
        self.convert_children(el, out, level, page)
        if not len(out) and not (out.text or "").strip():
            out.text = self.text_for(out.get("href", ""), page)
        dst.append(out)

    def text_for(self, href, page):
        """Text for a link baking left without any: the title of the page
        it goes to, or its address."""
        name = href.split("#")[0]
        if name.endswith(".html") and name[:-5] in self.by_name:
            return self.by_name[name[:-5]].title
        self.report(page.name, "link-without-text", href)
        return href or "link"


def _strip_edges(element):
    """Whitespace at a span's ends taken off: OpenStax's titles carry
    the space before the closing tag that a caption's parts then
    doubled."""
    if element.text:
        element.text = element.text.lstrip()
    last = element[-1] if len(element) else None
    if last is not None:
        if last.tail:
            last.tail = last.tail.rstrip()
    elif element.text:
        element.text = element.text.rstrip()


def _without_tail(el):
    out = copy.deepcopy(el)
    out.tail = None
    return out


def _numbered_by_place(ul):
    """Whether each item of a list of learning objectives opens with
    baking's token for its place alone, 1 to the last."""
    items = [c for c in ul if isinstance(c.tag, str)]
    if not items:
        return False
    for place, li in enumerate(items, 1):
        first = next((c for c in li if isinstance(c.tag, str)), None)
        if li.tag != "li" or (li.text or "").strip() or first is None \
                or not has_class(first, "os-abstract-token") \
                or "".join(first.itertext()).strip() != str(place):
            return False
    return True


def _join_repeated_terms(dl):
    """A term the definition before it has too, one term with two
    definitions: two of a chapter's sections define "pancreas" (*Concepts
    of Biology*), and its Key Terms lists both, as cookbook lists them,
    each its own dl in OpenStax's markup and one dl here, where the Nu
    checker warns of a term given twice. The second dt goes, an empty
    anchor for each id it held put at the head of its dd, and the two dds
    follow the one dt, as HTML has a term with more than one meaning."""
    def words(el):
        return " ".join("".join(el.itertext()).split())
    last = None
    for child in list(dl):
        if child.tag != "dt":
            continue
        previous = child.getprevious()
        if last is not None and previous is not None \
                and previous.tag == "dd" and words(child) == words(last):
            ids = [e.get("id") for e in child.iter() if e.get("id")]
            following = child.getnext()
            if following is not None and following.tag == "dd":
                for name in reversed(ids):
                    prepend(following, E("span", {"id": name}, ""))
                dl.remove(child)
                continue
        last = child


# The spans baking writes a heading in, which say nothing to a reader.
BAKED_SPANS = ("os-number", "os-text", "os-subtitle-label", "os-title-label",
               "os-divider", "os-part-text")


def _area_title(child):
    """The title an answer key's area or a section's exercises opens
    with, or None: an element of data-type title or document-title, or a
    div holding one alone."""
    if child.get("data-type") in ("title", "document-title"):
        return child
    if child.tag == "div" and not child.get("class") and len(child) == 1 \
            and isinstance(child[0].tag, str) \
            and child[0].get("data-type") == "document-title" \
            and not (child.text or "").strip() \
            and not (child[0].tail or "").strip():
        return child[0]
    return None


def _merge_title(label):
    """A note's label heading made ready to take its title after it: the
    label's words in a span of class os-note-label, then a colon, unless
    the label ends in punctuation of its own ("Who Knew?", "Disorders of
    the...")."""
    span = E("span", {"class": "os-note-label"})
    span.text = label.text
    label.text = None
    for child in list(label):
        span.append(child)
    label.append(span)
    # Baking may leave a space at the label's end ("Theorem 2.1 ", its
    # divider's), which would stand before the colon.
    _rstrip(span)
    append_text(label, " " if text_of(span)[-1:] in ":?!." else ": ")


def _rstrip(element):
    """The space at the end of an element's words taken off, after its
    last child or inside it, but not inside a formula."""
    if len(element):
        last = element[-1]
        if (last.tail or "").strip():
            last.tail = last.tail.rstrip()
        else:
            last.tail = None
            if isinstance(last.tag, str) and etree.QName(last).localname != "math":
                _rstrip(last)
    else:
        element.text = (element.text or "").rstrip() or None


def _flatten_spans(element):
    """A heading's baked spans taken away, their words left as they
    read ("3.1 Demand and Supply"), and what's inside them kept: a term
    a title holds keeps its id, which the index links to; a formula
    stays a formula."""
    test = " or ".join(class_test(name) for name in BAKED_SPANS)
    for span in element.xpath(f".//span[{test}]"):
        _unwrap(span)
    element.text = (element.text or "").lstrip() or None


def _unwrap(element):
    """The element replaced by what it holds, text and all."""
    parent = element.getparent()
    index = parent.index(element)
    previous = element.getprevious()
    if element.text:
        if previous is not None:
            previous.tail = (previous.tail or "") + element.text
        else:
            parent.text = (parent.text or "") + element.text
    children = list(element)
    for offset, child in enumerate(children):
        parent.insert(index + offset, child)
    tail = element.tail
    parent.remove(element)
    if tail:
        last = children[-1] if children else parent[index - 1] \
            if index > 0 else None
        if last is not None:
            last.tail = (last.tail or "") + tail
        else:
            parent.text = (parent.text or "") + tail


def _paragraphs(element):
    """Each run of words and inline elements at the element's top that
    isn't in a paragraph put in one, so a number can lead it and a reader
    takes it for a paragraph."""
    nodes = []
    if element.text:
        nodes.append(element.text)
    for child in list(element):
        nodes.append(child)
        if child.tail:
            nodes.append(child.tail)
            child.tail = None
    if not any(isinstance(n, str) and n.strip() or
               (not isinstance(n, str) and n.tag not in BLOCK)
               for n in nodes):
        return
    element.text = None
    for child in list(element):
        element.remove(child)
    run = []

    def flush():
        if not any((isinstance(n, str) and n.strip()) or
                   not isinstance(n, str) for n in run):
            run.clear()
            return
        p = E("p")
        for n in run:
            if isinstance(n, str):
                append_text(p, n)
            else:
                p.append(n)
        if p.text:
            p.text = p.text.lstrip()
        element.append(p)
        run.clear()

    for n in nodes:
        if not isinstance(n, str) and n.tag in BLOCK:
            flush()
            element.append(n)
        else:
            run.append(n)
    flush()


def _lead_into_first_paragraph(out, lead):
    """Put the number at the start of the first paragraph, or in a
    paragraph of its own when the problem opens with something else."""
    first = None
    for child in out:
        if isinstance(child.tag, str):
            first = child
            break
    if first is not None and first.tag == "p" and not (out.text or "").strip():
        text = first.text
        first.text = None
        lead_children = list(lead)
        for i, kid in enumerate(lead_children):
            first.insert(i, kid)
        last = lead_children[-1] if lead_children else None
        joiner = lead.text or ""
        if last is not None:
            last.tail = (last.tail or "") + joiner + (text or "")
        else:
            first.text = joiner + (text or "")
        return
    p = E("p")
    p.text = lead.text
    for kid in list(lead):
        p.append(kid)
    prepend(out, p)


def _empty_title(title):
    """Whether a title has nothing in it: no words, picture, or
    formula."""
    return not "".join(title.itertext()).strip() and not title.xpath(
        ".//img | .//*[local-name()='math']")


def drop_empty_headings(body):
    """A heading with nothing in it (a section's empty <title/>, a
    note's, as the nursing books and Python write some) taken out, an
    anchor left for each id it held: vnu warns of an empty heading, and
    a reader's outline would list it. The page's own h1 stays."""
    tags = " | ".join(f".//h{n}" for n in range(1, 7))
    for h in body.xpath(tags):
        if h is body[0] or "".join(h.itertext()).strip() or \
                h.xpath(".//img | .//*[local-name()='math']"):
            continue
        parent = h.getparent()
        index = parent.index(h)
        ids = [el.get("id") for el in h.iter()
               if isinstance(el.tag, str) and el.get("id")]
        for offset, name in enumerate(ids):
            parent.insert(index + offset, E("div", {"id": name}, ""))
        detach(h)


def split_paragraphs(root):
    """Cut every <p> holding a block element around it: the text before,
    the block, the text after, each where it was, the paragraph's id on
    its first part."""
    for p in list(root.iter("p")):
        if not any(isinstance(c.tag, str) and c.tag in BLOCK for c in p):
            continue
        parent = p.getparent()
        index = parent.index(p)
        pieces = []
        current = E("p", dict(p.attrib))
        current.text = p.text
        for child in list(p):
            if isinstance(child.tag, str) and child.tag in BLOCK:
                tail = child.tail
                child.tail = None
                pieces.append(current)
                pieces.append(child)
                current = E("p", {k: v for k, v in p.attrib.items()
                                  if k != "id"})
                current.text = tail
            else:
                current.append(child)
        pieces.append(current)
        tail = p.tail
        parent.remove(p)
        kept = []
        for piece in pieces:
            if piece.tag == "p" and not len(piece) and \
                    not (piece.text or "").strip():
                if piece.get("id"):
                    kept.append(E("div", {"id": piece.get("id")}, ""))
                continue
            kept.append(piece)
        for offset, piece in enumerate(kept):
            parent.insert(index + offset, piece)
        if kept:
            kept[-1].tail = (kept[-1].tail or "") + (tail or "")
        elif tail:
            if index > 0:
                prev = parent[index - 1]
                prev.tail = (prev.tail or "") + tail
            else:
                parent.text = (parent.text or "") + tail


def finish(root):
    """Empty non-void elements written open and closed (an <a/> is a
    start tag to an HTML parser), and attributes nothing reads dropped.
    And the words composed (NFC), as HTML wants them: a source can write
    "Ö" as "O" and a combining diaeresis. A formula's are left as they
    are, since how a formula writes an accent is a choice of its own.
    A C1 control is the Windows-1252 character it stands for, and a
    character of the Symbol font in the private use area the character
    the font draws, in a formula too (TEXT_FIXES). Returns how many of
    each of the Symbol font's characters were made so."""
    symbols = collections.Counter()

    def fixed(text):
        symbols.update(c for c in text if ord(c) in SYMBOL_FONT)
        return text.translate(TEXT_FIXES)
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        parent = el.getparent()
        if el.text:
            el.text = fixed(el.text)
        if el.tail:
            el.tail = fixed(el.tail)
        if el.tail and (parent is None or
                        etree.QName(parent).namespace != MATHML):
            el.tail = unicodedata.normalize("NFC", el.tail)
        if etree.QName(el).namespace == MATHML:
            continue
        if el.text:
            el.text = unicodedata.normalize("NFC", el.text)
        for key in list(el.attrib):
            if key in INTERNAL or el.attrib[key] is None:
                del el.attrib[key]
            else:
                el.set(key, fixed(el.attrib[key]))
        if el.tag not in VOID and el.text is None and not len(el):
            el.text = ""
    return symbols


def serialize(html):
    return ("<!DOCTYPE html>\n" +
            etree.tostring(html, encoding="unicode", method="xml") + "\n")


# A table's place on its page ------------------------------------------------
#
# TextbookImprover asks a description of a table with no label under the
# key "page#table-N", N its place among the page's tables
# (figures-and-tables.lua, number_tables and position_key): in document
# order, a table before the tables in its cells, one that holds only
# pictures not counted, since it becomes a figure. A footnote's table,
# which the reader moves into its note, isn't counted either; nothing
# after it on the page is a table.

# What the reader makes a block or a span that a table of pictures may
# have its pictures in (figures-and-tables.lua, scan_blocks).
PICTURE_HOLDERS = {"p", "div", "section", "blockquote", "ul", "ol", "li",
                   "figure", "span"}


def pictures_only(table):
    """Whether TextbookImprover takes the table for a picture's: cells
    holding pictures and nothing else but space, a line break, and a
    figure's caption, which it doesn't look in."""
    pictures = []

    def bare(text):
        return not (text or "").strip()

    def scan(el):
        if not bare(el.text):
            return False
        for child in el:
            if not bare(child.tail):
                return False
            if not isinstance(child.tag, str) or child.tag in (
                    "br", "figcaption"):
                continue
            if child.tag == "img":
                pictures.append(child)
            elif child.tag not in PICTURE_HOLDERS or not scan(child):
                return False
        return True

    for row in table.xpath("./thead/tr | ./tbody/tr | ./tfoot/tr | ./tr"):
        for cell in row:
            if isinstance(cell.tag, str) and not scan(cell):
                return False
    return bool(pictures)


def table_places(body):
    """Each table's place on the page, by element."""
    places = {}
    for table in body.iter("table"):
        if table.xpath("ancestor::section[@role='doc-endnotes']") \
                or table.xpath("ancestor::tfoot") or pictures_only(table):
            continue
        places[table] = len(places) + 1
    return places


def table_excerpt(table):
    """The first cell with text, as TextbookImprover's report of a table
    with no description shows it: the head's rows first, a line break a
    space."""
    def words(el, parts):
        parts.append(el.text or "")
        for child in el:
            if isinstance(child.tag, str):
                if child.tag == "br":
                    parts.append(" ")
                words(child, parts)
            parts.append(child.tail or "")
        return parts

    for row in table.xpath("./thead/tr | ./tbody/tr | ./tr"):
        for cell in row:
            if isinstance(cell.tag, str):
                text = " ".join("".join(words(cell, [])).split())
                if text:
                    return text if len(text) <= 60 else text[:57] + "..."
    return ""
