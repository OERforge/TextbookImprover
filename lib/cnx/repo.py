"""
cnx.repo -- a repository of CNXML books: which books it holds, each
book's outline, and where its modules and media are.

The layout is the one OpenStax's osbooks-* repositories and the archived
cnx-user-books share:

    META-INF/books.xml          <book slug=... style=... href=...>
    collections/<slug>.collection.xml
    modules/<id>/index.cnxml
    media/

A book's style names its baking recipe; the user books have none, and
are not baked. A collection's outline is nested subcollections ending in
modules; a module may carry a title of its own in the outline, which
wins over the one in its file.

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

import glob
import os

from lxml import etree

CNXML = "http://cnx.rice.edu/cnxml"
COLLXML = "http://cnx.rice.edu/collxml"
MDML = "http://cnx.rice.edu/mdml"
CONTAINER = "https://openstax.org/namespaces/book-container"
NS = {"c": CNXML, "col": COLLXML, "md": MDML, "bk": CONTAINER}
# The namespaces of the attributes Polish books add: a link's case
# (cmlnle:case="genitive"), and a term's form for the index and the
# index it goes in (cmlnle:reference, cxlxt:index, cxlxt:name).
CMLNLE = "http://katalysteducation.org/cmlnle/1.0"
CXLXT = "http://katalysteducation.org/cxlxt/1.0"

PARSER = etree.XMLParser(remove_blank_text=False, resolve_entities=False,
                         no_network=True, huge_tree=True)


def parse(path):
    return etree.parse(path, PARSER)


class Book:
    """One book of a repository, as books.xml names it."""

    def __init__(self, repo, slug, style, href, collection_id):
        self.repo = repo
        self.slug = slug
        self.style = style or ""
        self.collection_path = os.path.normpath(
            os.path.join(repo.root, "META-INF", href)) if href else None
        self.collection_id = collection_id or ""
        self._collection = None

    @property
    def collection(self):
        if self._collection is None:
            self._collection = Collection(self.collection_path)
        return self._collection

    def __repr__(self):
        return f"Book({self.slug!r}, style={self.style!r})"


class Node:
    """A subcollection (title, children) or a module reference (module,
    title or None)."""

    def __init__(self, kind, title=None, module=None, children=None):
        self.kind = kind                  # "group" or "module"
        self.title = title
        self.module = module
        self.children = children if children is not None else []

    def modules(self):
        if self.kind == "module":
            yield self
        for child in self.children:
            yield from child.modules()

    def __repr__(self):
        if self.kind == "module":
            return f"Node(module {self.module})"
        return f"Node(group {self.title!r}, {len(self.children)} children)"


class Collection:
    """A collection file: the book's metadata and its outline."""

    def __init__(self, path):
        self.path = path
        tree = parse(path)
        root = tree.getroot()
        meta = root.find(f"{{{COLLXML}}}metadata")
        self.title = _text(meta, "md:title")
        self.slug = _text(meta, "md:slug")
        self.language = _text(meta, "md:language") or "en"
        self.uuid = _text(meta, "md:uuid")
        lic = meta.find(f"{{{MDML}}}license") if meta is not None else None
        self.license_url = lic.get("url", "") if lic is not None else ""
        self.license_text = ("".join(lic.itertext()).strip()
                             if lic is not None else "")
        content = root.find(f"{{{COLLXML}}}content")
        self.root = Node("group", self.title,
                         children=_children(content) if content is not None
                         else [])

    def modules(self):
        return list(self.root.modules())


def _text(element, path):
    if element is None:
        return ""
    found = element.find(path, NS)
    return "".join(found.itertext()).strip() if found is not None else ""


def _children(content):
    out = []
    for child in content:
        if not isinstance(child.tag, str):
            continue
        local = etree.QName(child).localname
        if local == "module":
            title = child.find(f"{{{MDML}}}title")
            out.append(Node("module", module=child.get("document"),
                            title="".join(title.itertext()).strip()
                            if title is not None else None))
        elif local == "subcollection":
            inner = child.find(f"{{{COLLXML}}}content")
            out.append(Node("group", _text(child, "md:title"),
                            children=_children(inner) if inner is not None
                            else []))
    return out


class Repo:
    """A checked-out repository, or any directory in its layout."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        if not os.path.isdir(os.path.join(self.root, "modules")):
            raise ValueError(f"{root} has no modules/ directory: not a "
                             "repository of CNXML books")
        self.media_dir = os.path.join(self.root, "media")
        self.books = self._books()

    def _books(self):
        container = os.path.join(self.root, "META-INF", "books.xml")
        books = []
        if os.path.isfile(container):
            for el in parse(container).getroot().iter(f"{{{CONTAINER}}}book"):
                books.append(Book(self, el.get("slug"), el.get("style"),
                                  el.get("href"), el.get("collection-id")))
        if not books:
            # No container: every collection file is a book, named for
            # its file, with no style.
            for path in sorted(glob.glob(os.path.join(
                    self.root, "collections", "*.collection.xml"))):
                slug = os.path.basename(path)[:-len(".collection.xml")]
                rel = os.path.relpath(path, os.path.join(self.root,
                                                         "META-INF"))
                books.append(Book(self, slug, "", rel, ""))
        return books

    def book(self, slug=None):
        if slug is None:
            if len(self.books) == 1:
                return self.books[0]
            raise LookupError("this repository holds "
                              f"{len(self.books)} books; name one: "
                              + ", ".join(b.slug for b in self.books))
        for book in self.books:
            if book.slug == slug:
                return book
        raise LookupError(f"no book {slug!r} here; the books are: "
                          + ", ".join(b.slug for b in self.books))

    def module_path(self, module_id):
        return os.path.join(self.root, "modules", module_id, "index.cnxml")
