"""
cnx.assemble -- a book's modules as one tree: units, chapters, pages.

A subcollection holding modules only is a chapter; one holding other
subcollections is a unit, and a module directly inside it is a page of
the unit's own (Principles of Marketing opens each unit so). Modules at
the top of the outline are front or back matter, by their class:
OpenStax marks a preface and an appendix, and a page after the last
chapter that isn't an appendix is back matter.

Links are resolved here, while every module's place is known: a link to
an element of a module in this book is a fragment (#m63601__fig-3), to
a module of another book in the same repository a link to that book on
openstax.org (see Assembly.foreign_link), and to a module nowhere here
the archive's address, reported. Media paths are made relative to the
book's output directory and every file used is recorded, so only those
are copied.

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
import posixpath
import re
from urllib.parse import unquote, urlsplit

from lxml import etree

from epubsource import sniff

from . import cnxml
from .cnxml import E

# A picture's extension, by the format its bytes are (epubsource.sniff):
# the formats whose first bytes say so. An SVG file may open with a
# comment or a doctype, which sniff doesn't read, so it isn't checked.
IMAGE_EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg",
                    "image/gif": ".gif", "image/webp": ".webp"}

LEGACY_CONTENT = re.compile(
    r"^(?:https?://(?:legacy\.)?cnx\.org)?/content/(m\d+)(?:/[^#?]*)?"
    r"(?:#(.*))?$")


class Assembly:
    """The book being assembled: what links and media resolve against,
    and the report."""

    def __init__(self, repo, book):
        self.repo = repo
        self.book = book
        self.collection = book.collection
        self.module_ids = [n.module for n in self.collection.modules()]
        self.in_book = set(self.module_ids)
        modules_dir = os.path.join(repo.root, "modules")
        self.in_repo = set(os.listdir(modules_dir)) if os.path.isdir(
            modules_dir) else set()
        self.notes = []               # (where, check, detail)
        self.media = {}               # output path -> source path
        self.missing_media = {}       # output path -> module
        self.foreign_links = []       # (module, document, target)
        self.modules = {}             # module id -> cnxml.Module
        self.named = {}               # source path -> output path

    def report(self, where, check, detail):
        self.notes.append((where, check, detail))

    # links ------------------------------------------------------------

    def link_href(self, module, document, target):
        document = document or module.id
        if document in self.in_book:
            if target:
                return f"#{document}__{target}"
            return f"#page_{document}"
        self.foreign_links.append((module.id, document, target))
        if document in self.in_repo:
            # Rewritten once the other book's pages are known, or left
            # pointing at the archive; see unpack.py.
            return f"cnx-module:{document}" + (f"#{target}" if target else "")
        self.report(module.id, "link-outside-repository",
                    f"to module {document}" + (f", #{target}" if target
                                               else ""))
        return f"https://cnx.org/content/{document}" + (
            f"#{target}" if target else "")

    def url_href(self, module, url):
        url = url.strip()
        if url.startswith("#"):
            return self.link_href(module, module.id, url[1:])
        m = LEGACY_CONTENT.match(url)
        if m:
            return self.link_href(module, m.group(1), m.group(2) or "")
        if url.lower().startswith("www."):
            # A web address written without its scheme (*Life, Liberty,
            # and the Pursuit of Happiness*'s "www.quillproject.net"),
            # which a browser and TextbookImprover take for a file of the
            # book's: linked as an address written as text is.
            self.report(module.id, "link-without-scheme",
                        f"{url}, linked as https://{url}")
            return f"https://{url}"
        return url

    # media ------------------------------------------------------------

    def media_href(self, module, src):
        """The path a page uses for a file the module names, relative
        to the book's directory, and the file recorded for copying."""
        src = unquote((src or "").strip())
        if not src:
            return ""
        parts = urlsplit(src)
        if parts.scheme in ("http", "https", "ftp", "mailto", "data"):
            return src
        source = os.path.normpath(os.path.join(module.dir, parts.path))
        media_root = self.repo.media_dir
        if source.startswith(media_root + os.sep):
            rel = posixpath.join("media", *os.path.relpath(
                source, media_root).split(os.sep))
        else:
            # A file kept beside the module (the archive's older books do
            # this): under media/ in a directory named for the module.
            rel = posixpath.join("media", module.id,
                                 posixpath.basename(parts.path))
        if not (os.path.isfile(source) and self._inside(source)):
            source = self._found_elsewhere(module, parts.path)
        if source:
            rel = self._named_for_its_bytes(module, rel, source)
            self.media[rel] = source
        else:
            self.missing_media[rel] = module.id
        return rel + (("#" + parts.fragment) if parts.fragment else "")

    def _named_for_its_bytes(self, module, rel, source):
        """rel, or, for a picture in another format than its name says (a
        JPEG named .png: Prealgebra 2e's fourteen, Contemporary
        Mathematics' five PNGs named .jpg), rel with the extension its
        bytes have, as unpack-site.py names one: a reading system goes by
        the extension, and epubcheck rejects the file (OPF-029). A picture
        whose bytes are no picture's (a JPEG's bytes each written as two,
        as text read in one encoding and written in another, as two files
        in the biology bundle's media are, which no page names) is
        reported, as unpack-epub.py reports one."""
        if source in self.named:
            return self.named[source]
        stem, ext = posixpath.splitext(rel)
        known = set(IMAGE_EXTENSIONS.values()) | {".jpeg"}
        named = rel
        if ext.lower() in known:
            with open(source, "rb") as fh:
                data = fh.read(2048)
            kind = sniff(data)
            right = IMAGE_EXTENSIONS.get(kind or "")
            if kind is None:
                self.report(module.id, "image-is-not-an-image",
                            f"{rel}: begins "
                            + repr(data[:12].decode("latin-1")))
            elif right and ext.lower() not in (
                    right, ".jpeg" if right == ".jpg" else right):
                named = stem + right
                taken = {path for path in self.named.values()}
                if named in taken or os.path.exists(os.path.join(
                        self.repo.media_dir, posixpath.basename(named))):
                    named = f"{stem}-{ext[1:].lower()}{right}"
                self.report(module.id, "extension-corrected",
                            f"{rel}: the file is {right[1:].upper()}; "
                            f"written as {named}")
        self.named[source] = named
        return named

    def _found_elsewhere(self, module, path):
        """A file named by its bare name that sits in media/: the
        archive's books moved their files there and kept old names in
        some references."""
        name = posixpath.basename(path)
        candidate = os.path.join(self.repo.media_dir, name)
        return candidate if os.path.isfile(candidate) and self._inside(candidate) \
            else None

    def _inside(self, path):
        """Whether a file is the repository's own. A path that climbs out
        of it, or a link in it to a file elsewhere, names a file of the
        machine the book is unpacked on, which the book would carry to
        wherever it's posted."""
        root = os.path.realpath(self.repo.root)
        return os.path.realpath(path).startswith(root + os.sep)


def assemble(repo, book):
    """The book as one tree: a <body data-type="book"> holding its pages,
    chapters, and units, in outline order. Returns (Assembly, body)."""
    asm = Assembly(repo, book)
    collection = book.collection
    body = E("body", {"data-type": "book",
                      "data-slug": book.slug or collection.slug,
                      "data-style": book.style})
    title = E("h1", {"data-type": "document-title"}, collection.title)
    body.append(title)

    def build(node, parent):
        for child in node.children:
            if child.kind == "module":
                parent.append(_page(asm, child))
            else:
                has_groups = any(c.kind == "group" for c in child.children)
                group = E("div", {"data-type": "unit" if has_groups
                                  else "chapter"})
                heading = E("h1", {"data-type": "document-title"},
                            child.title)
                group.append(heading)
                build(child, group)
                parent.append(group)

    build(collection.root, body)
    return asm, body


def _page(asm, node):
    try:
        module, page = cnxml.module_page(asm.repo, node.module, asm,
                                         asm.report, node.title)
    except (OSError, etree.XMLSyntaxError) as exc:
        asm.report(node.module, "module-unreadable", str(exc))
        page = E("div", {"data-type": "page", "id": "page_" + node.module,
                         "data-module": node.module})
        page.append(E("h1", {"data-type": "document-title"},
                      node.title or node.module))
        return page
    asm.modules[node.module] = module
    return page
