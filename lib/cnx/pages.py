"""
cnx.pages -- the baked book cut into pages, each named as OpenStax names
it, and the outline the pages make.

A page is a module (div data-type="page") or a page baking built
(div data-type="composite-page"). Its name is the one OpenStax's Word
files and web addresses use, so a book's existing configuration and
sidecars, and any link to openstax.org, carry over:

    3-1-demand-supply-and-...      a chapter's section: its number, title
    3-introduction-to-demand-...   a chapter's introduction
    3-key-terms                    a chapter's end-of-chapter page
    chapter-3                      its page in the answer key
    preface, references, index     the book's own
    a-the-use-of-mathematics-...   an appendix: its letter, its title

A module used twice in one book (OpenStax's books don't) is named the
second time with "-2" after.

Every id was prefixed with its module's name so modules could share a
book; here each element's id goes back to the module's own wherever no
other element on its page has it, and every link is rewritten to the
page and id its target ended on.

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

import re

from .bake.core import class_test, has_class, slug, text_of

PREFIXED = re.compile(r"^(m[0-9A-Za-z]+)__(.+)$")


class Page:
    def __init__(self, element, kind, name, title, group, role=None,
                 page_type=None, module=None):
        self.element = element
        self.kind = kind            # "page" or "composite"
        self.name = name            # the file's stem
        self.title = title          # as the page's H1 shows it
        self.group = group          # the Group it's in, or None
        self.role = role            # front, main, appendix, back
        self.type = page_type       # preface, glossary, index, ...
        self.module = module

    def __repr__(self):
        return f"Page({self.name!r})"


class Group:
    def __init__(self, title, kind, parent=None, number=None):
        self.title = title
        # "unit", "chapter", "answer-key", or "review", a chapter's group
        # of its end-of-chapter pages
        self.kind = kind
        self.parent = parent
        self.number = number
        self.items = []             # Pages and Groups, in order


def title_text(title):
    """A baked title's text: its numbered spans read as a reader sees
    them, "3.1 Demand, Supply, ..." or "Chapter 3 Demand and Supply"."""
    if title is None:
        return ""
    return text_of(title)


def own_title(book, element):
    """The title element of a page, a composite page, a chapter, or a
    unit: the first child naming it, not the one in its metadata."""
    for child in element:
        if not isinstance(child.tag, str):
            continue
        if child.get("data-type") in ("document-title", "title"):
            return child
    # An introduction's title moved inside it when baked.
    found = element.xpath(".//*[@id and contains(@id, "
                          "'_titlecreatedbycookbook')]")
    if found:
        return found[0]
    return None


def bare_title(title):
    """The title's own words, without the number baking put before
    them."""
    if title is None:
        return ""
    texts = title.xpath(".//*[@class='os-text']")
    return text_of(texts[0]) if texts else text_of(title)


PAGE_TYPES = {
    "glossary": "glossary",
    "references": "bibliography",
    "index": "index",
}


def collect(book):
    """Walk the baked book in order. Returns (outline, pages): the
    outline a list of Pages and Groups, pages every Page in reading
    order."""
    body = book.body
    pages = []
    names = {}
    # Keyed by the elements themselves, which keeps lxml's proxies alive
    # and so the same objects when the walk meets them again.
    chapter_numbers = {c: n for n, c in enumerate(book.chapters(), 1)}
    unit_numbers = {u: n for n, u in enumerate(book.units(), 1)}

    def unique(name):
        base, n = name or "page", 2
        while name in names:
            name, n = f"{base}-{n}", n + 1
        names[name] = True
        return name

    def page_record(el, group, chapter_n):
        kind = "composite" if el.get("data-type") == "composite-page" \
            else "page"
        title_el = own_title(book, el)
        title = title_text(title_el)
        role, ptype = None, None
        module = el.get("data-module")
        if kind == "page":
            if has_class(el, "preface"):
                name = slug(bare_title(title_el))
                ptype = "preface"
            elif has_class(el, "appendix"):
                number = title_el.xpath(".//*[@class='os-number']") \
                    if title_el is not None else []
                letter = text_of(number[0]) if number else ""
                name = slug(f"{letter} {bare_title(title_el)}")
                role = "appendix"
            elif chapter_n is not None and has_class(el, "introduction"):
                name = slug(f"{chapter_n} {bare_title(title_el)}")
            elif chapter_n is not None and el.get("data-toc-title"):
                # Retitled by BakeCustomSections after OpenStax's
                # contents were made: named by its own title.
                number = title_el.xpath(f".//*[{class_test('os-number')}]") \
                    if title_el is not None else []
                name = slug(f"{text_of(number[0]) if number else ''} "
                            f"{el.get('data-toc-title')}")
            elif chapter_n is not None:
                name = slug(title)
            elif group is not None and group.kind == "unit":
                # A unit's own page, "1-unit-introduction", as OpenStax
                # names it: the unit's number and the page's title.
                name = slug(f"{group.number} {bare_title(title_el)}")
            else:
                name = slug(bare_title(title_el))
        else:
            container = next((c for c in el.get("class", "").split()
                              if c.startswith("os-") and
                              c.endswith("-container")), "")
            key = container[3:-len("-container")]
            ptype = PAGE_TYPES.get(key)
            if group is not None and group.kind in ("chapter", "review"):
                name = slug(f"{chapter_n} {bare_title(title_el)}")
            else:
                name = slug(bare_title(title_el))
            if key in ("references", "index") and group is None:
                role = "back"
        record = Page(el, kind, unique(name), title, group, role, ptype,
                      module)
        pages.append(record)
        return record

    def walk(element, group, chapter_n, out):
        for child in element:
            if not isinstance(child.tag, str):
                continue
            dtype = child.get("data-type")
            if dtype in ("page", "composite-page"):
                out.append(page_record(child, group, chapter_n))
            elif dtype in ("chapter", "unit", "composite-chapter"):
                kind = {"chapter": "chapter", "unit": "unit",
                        "composite-chapter": "answer-key"}[dtype]
                if kind == "answer-key" and group is not None \
                        and group.kind == "chapter":
                    # A chapter's own group of its end-of-chapter pages
                    # ("Chapter Review"), not the book's answer key.
                    kind = "review"
                if kind == "chapter":
                    n = chapter_numbers.get(child)
                    number = n
                elif kind == "unit":
                    n = chapter_n
                    # The number baking gave the unit, which isn't its
                    # place where units before it go unnumbered
                    # (Algebra 1's "Unit 1" is its third).
                    title_el = own_title(book, child)
                    baked = title_el.xpath(".//*[@class='os-number']") \
                        if title_el is not None else []
                    number = text_of(baked[0]) if baked \
                        else unit_numbers.get(child)
                else:
                    n = number = chapter_n
                sub = Group(title_text(own_title(book, child)), kind, group,
                            number)
                walk(child, sub, n, sub.items)
                if sub.items:
                    out.append(sub)
            elif dtype is None or dtype in ("metadata",):
                if child.tag in ("div", "section"):
                    walk(child, group, chapter_n, out)

    outline = []
    walk(body, None, None, outline)
    return outline, pages


def resolve(book, pages, report):
    """Every id back to the module's own where its page allows; every
    link to the page and id its target landed on. Returns {old id:
    (page name, new id)}."""
    where = {}                 # prefixed id -> (Page, element)
    for page in pages:
        for el in page.element.xpath(".//*[@id]"):
            if _owner(el, page) is not page:
                continue
            where[el.get("id")] = (page, el)
    final = {}
    for page in pages:
        taken = {}
        elements = [el for el in page.element.xpath(".//*[@id]")
                    if _owner(el, page) is page]
        counts = {}
        for el in elements:
            plain = _plain(el.get("id"))
            counts[plain] = counts.get(plain, 0) + 1
        for el in elements:
            old = el.get("id")
            plain = _plain(old)
            new = plain if counts[plain] == 1 else old.replace("__", "-", 1)
            n = 2
            while new in taken:
                new = f"{plain}-{n}"
                n += 1
            taken[new] = True
            el.set("id", new)
            final[old] = (page.name, new)
        # The page's own id names the page itself.
        page_id = page.element.get("id")
        if page_id:
            final[page_id] = (page.name, None)
    for page in pages:
        for link in page.element.xpath(".//a[@href]"):
            if _owner(link, page) is not page:
                continue
            href = link.get("href")
            if not href.startswith("#"):
                continue
            target = href[1:]
            if target.endswith("_titlecreatedbycookbook"):
                target = target[:-len("_titlecreatedbycookbook")]
            found = final.get(target)
            if found is None:
                report(page.name, "link-to-nothing",
                       f"{href} names no element of the book")
                continue
            name, ident = found
            if name == page.name:
                link.set("href", "#" + ident if ident else "#")
                if ident is None:
                    link.set("href", f"{name}.html")
            else:
                link.set("href", f"{name}.html" + (f"#{ident}" if ident
                                                    else ""))
    return final


def _owner(element, page):
    """The page an element is on: the nearest enclosing page or
    composite page."""
    for ancestor in element.iterancestors():
        if ancestor.get("data-type") in ("page", "composite-page"):
            return page if ancestor is page.element else None
    return None


def _plain(ident):
    m = PREFIXED.match(ident or "")
    return m.group(2) if m else ident
