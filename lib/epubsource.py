"""
epubsource -- read an EPUB as what it is: a zip of XHTML pages, a package
document that orders them, and a navigation document that names them.

Pandoc's own EPUB reader is not used, for reasons read from its source
(Readers/EPUB.hs at 3.11; see PANDOC-NOTES.md): it concatenates the spine
into one document, rewrites every id to "<file>_<id>" on some elements
and every internal link to match, so a link to a figure or a table dies;
it drops each file's title and language; and it reads none of the
navigation document. Unpacked here instead, each content document is a
page Pandoc's HTML reader takes as it takes any other, ids as the
publisher wrote them, and a link between two files of the book is a link
between two pages.

Nothing here parses a content document. One of the three EPUBs this was
built against is not well-formed XML (an unclosed <br>, which epubcheck
calls fatal and every reading system shrugs at), so references are
rewritten in the text, attribute by attribute, and the page is otherwise
byte for byte what the publisher shipped. The package and navigation
documents are parsed as XML; a book whose package is not XML is not an
EPUB any reading system opens.

Standard library only.

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

import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from urllib.parse import quote, unquote, urldefrag

NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container",
      "opf": "http://www.idpf.org/2007/opf",
      "dc": "http://purl.org/dc/elements/1.1/",
      "x": "http://www.w3.org/1999/xhtml",
      "epub": "http://www.idpf.org/2007/ops",
      "ncx": "http://www.daisy.org/z3986/2005/ncx/"}
PAGE_TYPES = ("application/xhtml+xml", "text/html")

# What the first bytes of a file say it is, for the resources a page
# shows. A manifest's media-type is the publisher's claim; an exporter
# that could not fetch an image has been seen to package the server's
# error page under an image's name and declare it text/html.
SIGNATURES = ((b"\x89PNG", "image/png"), (b"\xff\xd8\xff", "image/jpeg"),
              (b"GIF8", "image/gif"), (b"RIFF", "image/webp"),
              (b"<svg", "image/svg+xml"), (b"<?xml", "image/svg+xml"))


class Package:
    """What the package document says: metadata, manifest, spine, and
    where the navigation is. Paths are as the archive names them."""

    def __init__(self, path):
        self.path = path
        self.archive = zipfile.ZipFile(path)
        container = ET.fromstring(self.archive.read("META-INF/container.xml"))
        rootfile = container.find(".//c:rootfile", NS)
        if rootfile is None:
            raise ValueError(f"{path} names no package document")
        self.opf_path = rootfile.get("full-path")
        self.root = posixpath.dirname(self.opf_path)
        opf = ET.fromstring(self.archive.read(self.opf_path))
        self.version = opf.get("version", "")

        meta = opf.find("opf:metadata", NS)
        def every(tag):
            return [" ".join((e.text or "").split())
                    for e in meta.findall("dc:" + tag, NS)
                    if (e.text or "").strip()]
        self.metadata = {key: every(key) for key in
                         ("title", "language", "creator", "identifier",
                          "publisher", "description", "rights", "date")}

        self.manifest = {}                 # id -> (archive path, type, props)
        for item in opf.find("opf:manifest", NS):
            if not isinstance(item.tag, str):
                continue
            href = unquote(item.get("href", ""))
            self.manifest[item.get("id")] = (
                posixpath.normpath(posixpath.join(self.root, href)),
                item.get("media-type", ""),
                (item.get("properties") or "").split())

        spine = opf.find("opf:spine", NS)
        self.spine = []                    # (archive path, linear)
        for ref in spine:
            entry = self.manifest.get(ref.get("idref"))
            if entry and entry[1] in PAGE_TYPES:
                self.spine.append((entry[0], ref.get("linear") != "no"))
        self.nav_path = next((p for p, _, props in self.manifest.values()
                              if "nav" in props), None)
        ncx = self.manifest.get(spine.get("toc") or "")
        self.ncx_path = ncx[0] if ncx else None

    def read(self, name):
        return self.archive.read(name)

    def outline(self):
        """The table of contents as (depth, title, archive path, fragment),
        from the navigation document, or toc.ncx when there is none."""
        entries = []
        if self.nav_path:
            base = posixpath.dirname(self.nav_path)
            nav = ET.fromstring(self.read(self.nav_path))
            toc = next((n for n in nav.iter("{%s}nav" % NS["x"])
                        if n.get("{%s}type" % NS["epub"]) == "toc"), None)
            if toc is None:
                toc = next(nav.iter("{%s}nav" % NS["x"]), None)

            def walk(ol, depth):
                for li in ol.findall("x:li", NS):
                    label = li.find("x:a", NS)
                    if label is None:
                        label = li.find("x:span", NS)
                    if label is not None:
                        href, fragment = urldefrag(label.get("href") or "")
                        target = posixpath.normpath(posixpath.join(
                            base, unquote(href))) if href else None
                        entries.append((depth, " ".join(
                            "".join(label.itertext()).split()), target,
                            fragment))
                    for sub in li.findall("x:ol", NS):
                        walk(sub, depth + 1)
            if toc is not None and toc.find("x:ol", NS) is not None:
                walk(toc.find("x:ol", NS), 0)
        elif self.ncx_path:
            base = posixpath.dirname(self.ncx_path)
            ncx = ET.fromstring(self.read(self.ncx_path))

            def walk_points(node, depth):
                for point in node.findall("ncx:navPoint", NS):
                    text = point.find("ncx:navLabel/ncx:text", NS)
                    content = point.find("ncx:content", NS)
                    href, fragment = urldefrag(
                        content.get("src") if content is not None else "")
                    entries.append((depth, " ".join(
                        (text.text or "").split()) if text is not None else "",
                        posixpath.normpath(posixpath.join(
                            base, unquote(href))) if href else None,
                        fragment))
                    walk_points(point, depth + 1)
            nav_map = ncx.find("ncx:navMap", NS)
            if nav_map is not None:
                walk_points(nav_map, 0)
        return entries


def sniff(data):
    """The media type the bytes have, or None when they are not something
    a page can show."""
    head = data[:256].lstrip()
    for magic, kind in SIGNATURES:
        if head.startswith(magic):
            if kind == "image/webp" and b"WEBP" not in head[:16]:
                continue
            if magic == b"<?xml" and b"<svg" not in data[:2048]:
                continue
            return kind
    return None


REFERENCE = re.compile(
    r"""(\b(?:src|href|poster|data|xlink:href)\s*=\s*)(["'])(.*?)\2""",
    re.I | re.S)
EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//|#)", re.I)


def rewrite_references(markup, doc_path, page_names, root):
    """A content document's references, rewritten for where the page now
    sits: at the top of the unpacked directory, with the book's other
    files at their paths relative to the package document. A reference
    to another content document becomes a reference to its page."""
    here = posixpath.dirname(doc_path)

    def fix(match):
        lead, mark, value = match.groups()
        if not value or EXTERNAL.match(value):
            return match.group(0)
        target, fragment = urldefrag(value)
        resolved = posixpath.normpath(posixpath.join(here, unquote(target))) \
            if target else doc_path
        if resolved in page_names:
            new = page_names[resolved] + ".html" if target else ""
        else:
            new = quote(posixpath.relpath(resolved, root or "."))
        if fragment:
            new += "#" + fragment
        return f"{lead}{mark}{new}{mark}"
    return REFERENCE.sub(fix, markup)
