"""
cnx.bake.core -- what every baking step works with: the book's tree and
the elements in it, by OpenStax's names for them.

Each direction in directions.py is a port of one of openstax/cookbook's
(MIT License; see ../LICENSE-cookbook.txt), and these helpers are the
small part of cookbook's "Kitchen" they lean on: finding a book's
chapters, pages, notes, and figures; counting an element among its kind
in its chapter; remembering the text a link to an element should show
(cookbook's "pantry"); and making a composite page, the page baking
builds from parts of others. Cookbook wraps Nokogiri in a vocabulary of
its own; this is lxml and XPath, with the names kept so the two can be
read side by side.

A search's later steps say "/descendant::div[...]" where "//div[...]"
would mean the same: libxml2 reads "//" as "every node below each
element found so far", and merging those lists, many elements deep, took
minutes on a whole book.

Copyright 2026 Robert Szarka. Portions ported from openstax/cookbook,
Copyright (c) 2020 Rice University, under the MIT License, whose text is
in lib/cnx/LICENSE-cookbook.txt.

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

import copy
import re
import unicodedata

from ..cnxml import E, append_text
from ..repo import CMLNLE, CXLXT


# Selectors, as XPath. Cookbook's Standard1 set, by name.
CHAPTER = "div[@data-type='chapter']"
UNIT = "div[@data-type='unit']"
PAGE = "div[@data-type='page']"
COMPOSITE_PAGE = "div[@data-type='composite-page']"
COMPOSITE_CHAPTER = "div[@data-type='composite-chapter']"
NOTE = "div[@data-type='note']"
EXAMPLE = "div[@data-type='example']"
EXERCISE = "div[@data-type='exercise']"
SOLUTION = "div[@data-type='solution']"
TERM = "span[@data-type='term']"

# A Polish book's grammatical cases, in which a link may name its
# target, as cookbook's target_label lists them.
CASES = ("nominative", "genitive", "dative", "accusative", "instrumental",
         "locative", "vocative")


def extra_attribute(element, name):
    """An attribute the Polish books add, as the unpacker writes it
    (data-case) or as OpenStax's assembly keeps it (cmlnle:case, in
    either namespace, or with none)."""
    for key in (f"data-{name}", f"{{{CMLNLE}}}{name}", f"{{{CXLXT}}}{name}",
                name):
        if element.get(key) is not None:
            return element.get(key)
    return None


def has_class(element, name):
    return name in (element.get("class") or "").split()


def classes(element):
    return (element.get("class") or "").split()


def add_class(element, name):
    current = classes(element)
    if name not in current:
        current.append(name)
        element.set("class", " ".join(current))


def remove_class(element, name):
    current = [c for c in classes(element) if c != name]
    if current:
        element.set("class", " ".join(current))
    elif "class" in element.attrib:
        del element.attrib["class"]


def class_test(name):
    """An XPath predicate for an element having a class."""
    return f"contains(concat(' ', normalize-space(@class), ' '), ' {name} ')"


def text_of(element):
    return " ".join("".join(element.itertext()).split())


def detach(element):
    """Take an element out of the tree, leaving its tail text where it
    was. Returns the element, tail cleared."""
    parent = element.getparent()
    if parent is None:
        return element
    tail = element.tail
    previous = element.getprevious()
    if tail:
        if previous is not None:
            previous.tail = (previous.tail or "") + tail
        else:
            parent.text = (parent.text or "") + tail
    parent.remove(element)
    element.tail = None
    return element


def trash(element):
    detach(element)


def replace(old, new):
    """Put new where old was, old's tail kept after new."""
    parent = old.getparent()
    new.tail = old.tail
    old.tail = None
    parent.replace(old, new)


def wrap(element, wrapper):
    """Put element inside wrapper, wrapper where element was."""
    parent = element.getparent()
    wrapper.tail = element.tail
    element.tail = None
    parent.replace(element, wrapper)
    wrapper.append(element)
    return wrapper


def wrap_children(element, wrapper):
    """Put element's content (text included) inside wrapper, the only
    child of element."""
    wrapper.text = element.text
    element.text = None
    for child in list(element):
        wrapper.append(child)
    element.append(wrapper)
    return wrapper


def prepend(parent, child):
    """child as parent's first child, before its text."""
    child.tail = (child.tail or "") + (parent.text or "")
    parent.text = None
    parent.insert(0, child)


def insert_after(element, new):
    parent = element.getparent()
    new.tail = element.tail
    element.tail = None
    parent.insert(parent.index(element) + 1, new)


def insert_before(element, new):
    parent = element.getparent()
    parent.insert(parent.index(element), new)


def children_copy(element):
    """A copy of an element's content: (text, [children])."""
    return element.text, [copy.deepcopy(c) for c in element]


def move_children(src, dst):
    """src's content appended to dst (text included); src left empty."""
    append_text(dst, src.text)
    src.text = None
    for child in list(src):
        dst.append(child)


def span(cls, text=None, **attrs):
    attrib = {"class": cls}
    attrib.update({k.replace("_", "-"): v for k, v in attrs.items()})
    return E("span", attrib, text)


def title_span(text_or_element):
    """<span class="os-text">...</span>, from text or an element's
    content (copied)."""
    out = span("os-text")
    if isinstance(text_or_element, str):
        out.text = text_or_element
    else:
        out.text, kids = children_copy(text_or_element)
        for kid in kids:
            out.append(kid)
    return out


class Book:
    """The tree being baked, with what the steps share: the link texts
    and the strings a recipe's locale gives."""

    def __init__(self, body, strings, style="", language="en"):
        self.body = body
        self.strings = strings
        self.style = style
        self.language = language
        self.labels = {}         # id -> the text a link to it shows
        # id -> {case: text}, a Polish book's link texts, a link naming
        # the case its sentence wants ("Ilustracji 1.2", of Figure 1.2)
        self.case_labels = {}
        self.link_types = {}     # id -> class a link to it gets
        # id -> a page's number alone, for a link that shows only that
        # ("LO 3.1", BakeLOLinkLabels)
        self.label_numbers = {}
        # Baking adds and moves pages but never a chapter, so the list
        # is read once; holding it also keeps lxml handing back the same
        # objects for the same elements, which index() needs.
        self._chapters = None

    # finding ----------------------------------------------------------

    def chapters(self):
        if self._chapters is None:
            self._chapters = self.body.xpath(f".//{CHAPTER}")
        return self._chapters

    def units(self):
        return self.body.xpath(f".//{UNIT}")

    def pages(self, within=None, cls=None):
        root = within if within is not None else self.body
        test = f"[{class_test(cls)}]" if cls else ""
        return root.xpath(f".//{PAGE}{test}")

    def top_level_pages(self):
        """Pages that are no chapter's or unit's: preface, appendices,
        back matter."""
        return [p for p in self.pages()
                if self.chapter_of(p) is None and self.unit_of(p) is None]

    def chapter_of(self, element):
        for ancestor in element.iterancestors("div"):
            if ancestor.get("data-type") == "chapter":
                return ancestor
        return None

    def unit_of(self, element):
        for ancestor in element.iterancestors("div"):
            if ancestor.get("data-type") == "unit":
                return ancestor
        return None

    def page_of(self, element):
        for ancestor in element.iterancestors("div"):
            if ancestor.get("data-type") in ("page", "composite-page"):
                return ancestor
        return None

    def chapter_number(self, chapter):
        return self.chapters().index(chapter) + 1

    def title_text(self):
        """The book's title as a recipe reads it, from the <title> in
        the document's head (book.first('head').first('title')), which
        OpenStax's assembly writes; ours writes it as the body's first
        heading."""
        root = self.body.getparent()
        title = root.find("head/title") if root is not None else None
        if title is None:
            found = self.body.xpath(
                "./*[@data-type='document-title'] | "
                "./div[@data-type='metadata']/*[@data-type='document-title']")
            title = found[0] if found else None
        return " ".join(text_of(title).split()) if title is not None else ""

    def is_introduction(self, page):
        return has_class(page, "introduction")

    def introduction_page(self, chapter):
        pages = [p for p in self.pages(chapter) if self.is_introduction(p)]
        return pages[0] if pages else None

    def non_introduction_pages(self, chapter):
        return [p for p in self.pages(chapter) if not self.is_introduction(p)]

    def page_number(self, page):
        """A page's number in its chapter, counting its introduction
        out: 3.1 is the first page after chapter 3's introduction."""
        chapter = self.chapter_of(page)
        if chapter is None:
            return None
        pages = self.non_introduction_pages(chapter)
        return f"{self.chapter_number(chapter)}.{pages.index(page) + 1}"

    def page_title(self, page):
        """The page's own title element, not the one in its metadata."""
        for child in page:
            if (isinstance(child.tag, str) and
                    child.get("data-type") == "document-title"):
                return child
        # As cookbook's PageElement#title, one in the page's metadata
        # skipped.
        found = [title for title in
                 page.xpath(".//*[@data-type='document-title']")
                 if title.getparent().get("data-type") != "metadata"]
        return found[0] if found else None

    def notes(self, within=None, cls=None):
        root = within if within is not None else self.body
        test = f"[{class_test(cls)}]" if cls else ""
        return root.xpath(f".//{NOTE}{test}")

    def exercises(self, within):
        return within.xpath(f".//{EXERCISE}")

    def figures(self, within=None):
        root = within if within is not None else self.body
        return root.xpath(".//figure")

    def tables(self, within=None):
        root = within if within is not None else self.body
        return root.xpath(".//table[not(@data-type='entrytbl')]")

    def sections(self, within, cls):
        return within.xpath(f".//section[{class_test(cls)}]")

    # strings ----------------------------------------------------------

    def t(self, key, **values):
        """A string from the recipe's locale, as cookbook's I18n.t; for a
        word given in its cases, the nominative, as a recipe that asks
        for the cases shows it ("Ilustracja 1.2")."""
        value = self.strings
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                raise KeyError(f"no string {key!r} for this book's style")
            value = value[part]
        if isinstance(value, dict) and "nominative" in value:
            value = value["nominative"]
        if values:
            value = re.sub(r"%\{(\w+)\}",
                           lambda m: str(values.get(m.group(1), "")), value)
        return value

    def has_string(self, key):
        try:
            self.t(key)
            return True
        except KeyError:
            return False

    # link text (cookbook's target_label and pantry) ---------------------

    def target_label(self, element, text, label_type=None):
        ident = element.get("id")
        if ident:
            self.labels[ident] = " ".join(text.split())
            if label_type:
                self.link_types[ident] = label_type

    def target_label_cases(self, element, key, content, label_type=None):
        """Cookbook's target_label with cases: a link's text in each of
        the cases, the word the locale gives in that case and the content
        after it ("Ilustracji 1.2"). The nominative is the link text too,
        for a link from another book of the repository."""
        ident = element.get("id")
        if not ident:
            return
        texts = {}
        for case in CASES:
            texts[case] = " ".join(
                f"{self.t(f'{key}.{case}')} {content}".split())
        self.case_labels[ident] = texts
        self.labels[ident] = texts["nominative"]
        if label_type:
            self.link_types[ident] = label_type


def figure_to_number(figure):
    """Cookbook's FigureElement#figure_to_number?: not a subfigure, not
    unnumbered, and with an id (a figure no link can name gets no
    number)."""
    parent = figure.getparent()
    if parent is not None and parent.tag == "figure":
        return False
    return not has_class(figure, "unnumbered") and bool(figure.get("id"))


def unnumbered_figure_to_bake(figure):
    return has_class(figure, "unnumbered") or not figure.get("id")


def note_title(note):
    """Cookbook's NoteElement#title: the note's first child, or the first
    child of a paragraph that opens it, when it's a title."""
    body = note.xpath("./div[@class='os-note-body']")
    holder = body[0] if body else note
    kids = [c for c in holder if isinstance(c.tag, str)]
    if not kids:
        return None
    first = kids[0]
    if first.get("data-type") == "title":
        return first
    if first.tag == "p":
        grandkids = [c for c in first if isinstance(c.tag, str)]
        if grandkids and grandkids[0].get("data-type") == "title":
            return grandkids[0]
    return None


# What OpenStax's names turn some symbols into: each spelled in ASCII, as
# the transliteration their tools use does ("Excel®" is "excel-r").
SPELLED = {"®": "(r)", "©": "(c)", "™": "(tm)",
           "ß": "ss", "æ": "ae", "Æ": "AE", "œ": "oe",
           "Œ": "OE", "ø": "o", "Ø": "O", "ł": "l",
           "Ł": "L", "đ": "d", "Đ": "D"}


def slug(text):
    """A page's name as OpenStax makes one from its title: letters and
    digits, lowercase, everything else one hyphen; apostrophes dropped,
    so "Cohen's" is "cohens"; accents taken off. Checked against the
    names of the 583 numbered sections of seven books' Word files."""
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("'", "")
    text = "".join(SPELLED.get(c, c) for c in text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return text
