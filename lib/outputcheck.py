"""
outputcheck.py -- find what is well-formed and wrong in the pages and
EPUBs this pipeline writes, with nothing but the standard library.

The checks are the class of defect that has actually reached this
project's output: a link or fragment that resolves to nothing, an image
with no alt attribute, a heading level that skips, an id used twice, a
table with neither header cells nor a caption, a page with no language
or no title, an EPUB whose manifest and archive disagree. Each is
something a validator would report and no one notices by looking at a
page.

This is not epubcheck, the Nu HTML checker, or Ace, all of which know
their specifications in full and two of which need Java. It is what can
be checked here, every run, on every machine that can run the pipeline.
The findings are a list to work through, not a reason to stop the run.

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
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

EXTERNAL = ("http:", "https:", "mailto:", "tel:", "data:", "javascript:",
            "//")
XHTML = "{http://www.w3.org/1999/xhtml}"


class Finding:
    """One thing wrong: where, which check, and what."""

    __slots__ = ("where", "check", "detail")

    def __init__(self, where, check, detail):
        self.where, self.check, self.detail = where, check, detail

    def row(self):
        return [self.where, self.check, self.detail]


# --------------------------------------------------------------------------
# what a page says about itself
# --------------------------------------------------------------------------

class Page:
    """The facts the checks need from one HTML or XHTML document."""

    def __init__(self, name):
        self.name = name
        self.lang = None
        self.title = None
        self.ids = []               # in document order, duplicates kept
        self.links = []             # href values of <a>
        self.images = []            # (has_alt, alt, role, src)
        self.headings = []          # (level, text)
        self.tables = []            # (has_th, has_caption, role)
        self.parse_error = None


class _Collector(HTMLParser):
    """Tolerant collection from HTML5, where a page need not be XML."""

    def __init__(self, page):
        super().__init__(convert_charrefs=True)
        self.page = page
        self._heading = None
        self._title = None
        self._table = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.page.ids.append(a["id"])
        if tag == "html":
            self.page.lang = a.get("lang") or a.get("xml:lang")
        elif tag == "title":
            self._title = []
        elif tag == "a" and a.get("href") is not None:
            self.page.links.append(a["href"])
        elif tag == "img":
            self.page.images.append(("alt" in a, a.get("alt") or "",
                                     a.get("role"), a.get("src", "")))
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._heading = [int(tag[1]), []]
        elif tag == "table":
            self._table = [False, False, a.get("role")]
        elif tag == "th" and self._table:
            self._table[0] = True
        elif tag == "caption" and self._table:
            self._table[1] = True

    def handle_endtag(self, tag):
        if tag == "title" and self._title is not None:
            self.page.title = " ".join("".join(self._title).split())
            self._title = None
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self._heading:
            level, parts = self._heading
            self.page.headings.append((level, " ".join(
                "".join(parts).split())))
            self._heading = None
        elif tag == "table" and self._table:
            self.page.tables.append(tuple(self._table))
            self._table = None

    def handle_data(self, data):
        if self._title is not None:
            self._title.append(data)
        if self._heading:
            self._heading[1].append(data)


def read_html(name, markup):
    page = Page(name)
    collector = _Collector(page)
    try:
        collector.feed(markup)
        collector.close()
    except Exception as exc:          # html.parser is lenient; be safe
        page.parse_error = str(exc)
    return page


def read_xhtml(name, markup):
    """Strict: an EPUB's content documents must be XML."""
    page = Page(name)
    try:
        root = ET.fromstring(markup)
    except ET.ParseError as exc:
        page.parse_error = str(exc)
        return read_html(name, markup)     # still collect what we can
    xml_lang = "{http://www.w3.org/XML/1998/namespace}lang"
    page.lang = root.get("lang") or root.get(xml_lang)
    for el in root.iter():
        tag = el.tag.replace(XHTML, "")
        if el.get("id"):
            page.ids.append(el.get("id"))
        if tag == "title" and page.title is None:
            page.title = " ".join("".join(el.itertext()).split())
        elif tag == "a" and el.get("href") is not None:
            page.links.append(el.get("href"))
        elif tag == "img":
            page.images.append(("alt" in el.attrib, el.get("alt") or "",
                                el.get("role"), el.get("src", "")))
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            page.headings.append((int(tag[1]),
                                  " ".join("".join(el.itertext()).split())))
        elif tag == "table":
            has_th = any(c.tag.replace(XHTML, "") == "th" for c in el.iter())
            has_caption = any(c.tag.replace(XHTML, "") == "caption"
                              for c in el.iter())
            page.tables.append((has_th, has_caption, el.get("role")))
    return page


# --------------------------------------------------------------------------
# the checks
# --------------------------------------------------------------------------

def check_page(page, findings):
    """Everything about one page that needs no other page."""
    where = page.name
    if page.parse_error:
        findings.append(Finding(where, "not-well-formed", page.parse_error))
    if not page.lang:
        findings.append(Finding(where, "no-lang",
                                "the html element declares no language"))
    if not page.title:
        findings.append(Finding(where, "no-title", "the page has no title"))
    seen = set()
    for identifier in page.ids:
        if identifier in seen:
            findings.append(Finding(where, "duplicate-id", identifier))
        seen.add(identifier)
    for has_alt, alt, role, src in page.images:
        if not has_alt:
            findings.append(Finding(where, "image-without-alt", src))
        elif not alt.strip() and role != "presentation":
            findings.append(Finding(where, "image-empty-alt-not-decorative",
                                    src))
    last = 0
    for level, text in page.headings:
        if not text:
            findings.append(Finding(where, "empty-heading", f"h{level}"))
        if last and level > last + 1:
            findings.append(Finding(where, "heading-skips-level",
                                    f"h{last} to h{level}: {text}"))
        last = level
    for index, (has_th, has_caption, role) in enumerate(page.tables, 1):
        if role == "presentation":
            continue
        if not has_th and not has_caption:
            findings.append(Finding(where, "table-without-headers-or-caption",
                                    f"table {index}"))


def check_links(pages, findings, base_of=None):
    """Every internal link resolves to a file in the set, and every
    fragment to an id in that file."""
    ids = {page.name: set(page.ids) for page in pages.values()}
    for page in pages.values():
        for href in page.links:
            if href.startswith(EXTERNAL) or not href:
                continue
            target, _, fragment = href.partition("#")
            target = unquote(target)
            if target:
                here = posixpath.dirname(page.name)
                name = posixpath.normpath(posixpath.join(here, target))
                if name not in ids:
                    findings.append(Finding(page.name, "link-to-missing-file",
                                            href))
                    continue
            else:
                name = page.name
            if fragment and fragment not in ids[name]:
                findings.append(Finding(page.name, "link-to-missing-fragment",
                                        href))


def check_html_files(paths):
    """The pages a run wrote, checked as a set so links between them
    count. Names are the file names, so a link to another page is
    resolved among them."""
    findings = []
    pages = {}
    for path in paths:
        name = os.path.basename(path)
        with open(path, encoding="utf-8", errors="replace") as fh:
            pages[name] = read_html(name, fh.read())
    for page in pages.values():
        check_page(page, findings)
    check_links(pages, findings)
    return findings


# --------------------------------------------------------------------------
# an EPUB
# --------------------------------------------------------------------------

OPF_NS = "{http://www.idpf.org/2007/opf}"
DC_NS = "{http://purl.org/dc/elements/1.1/}"


def check_epub(path):
    findings = []
    where = os.path.basename(path)
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        return [Finding(where, "not-a-zip", str(exc))]
    with archive:
        names = archive.namelist()
        infos = archive.infolist()
        if not names or names[0] != "mimetype":
            findings.append(Finding(where, "mimetype-not-first",
                                    "the first entry must be mimetype"))
        elif infos[0].compress_type != zipfile.ZIP_STORED:
            findings.append(Finding(where, "mimetype-compressed", ""))
        elif archive.read("mimetype") != b"application/epub+zip":
            findings.append(Finding(where, "mimetype-wrong",
                                    archive.read("mimetype")[:40].decode(
                                        "ascii", "replace")))
        try:
            container = ET.fromstring(archive.read("META-INF/container.xml"))
        except (KeyError, ET.ParseError) as exc:
            return findings + [Finding(where, "no-container", str(exc))]
        rootfile = container.find(
            ".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile")
        opf_name = rootfile.get("full-path") if rootfile is not None else None
        if not opf_name or opf_name not in names:
            return findings + [Finding(where, "no-package-document",
                                       str(opf_name))]
        try:
            opf = ET.fromstring(archive.read(opf_name))
        except ET.ParseError as exc:
            return findings + [Finding(opf_name, "not-well-formed", str(exc))]
        opf_dir = posixpath.dirname(opf_name)

        metadata = opf.find(OPF_NS + "metadata")
        for element in ("title", "identifier", "language"):
            if metadata is None or metadata.find(DC_NS + element) is None \
                    or not (metadata.find(DC_NS + element).text or "").strip():
                findings.append(Finding(opf_name, "no-dc-" + element, ""))
        props = {m.get("property") for m in (metadata or []) if m.tag
                 == OPF_NS + "meta"}
        for wanted in ("schema:accessMode", "schema:accessModeSufficient",
                       "schema:accessibilityFeature",
                       "schema:accessibilityHazard",
                       "schema:accessibilitySummary"):
            if wanted not in props:
                findings.append(Finding(opf_name, "no-accessibility-metadata",
                                        wanted))

        manifest = {}
        for item in opf.iter(OPF_NS + "item"):
            href = posixpath.normpath(posixpath.join(opf_dir,
                                                     unquote(item.get("href",
                                                                      ""))))
            manifest[item.get("id")] = (href, item.get("media-type", ""),
                                        item.get("properties", ""))
            if href not in names:
                findings.append(Finding(opf_name, "manifest-item-missing",
                                        item.get("href", "")))
        listed = {h for h, _, _ in manifest.values()}
        for name in names:
            if name in ("mimetype", opf_name) or name.startswith("META-INF/"):
                continue
            if name not in listed:
                findings.append(Finding(where, "file-not-in-manifest", name))
        if not any("nav" in p.split() for _, _, p in manifest.values()):
            findings.append(Finding(opf_name, "no-nav-document", ""))
        for ref in opf.iter(OPF_NS + "itemref"):
            if ref.get("idref") not in manifest:
                findings.append(Finding(opf_name, "spine-idref-unknown",
                                        ref.get("idref", "")))

        pages = {}
        for name, media, _ in manifest.values():
            if media == "application/xhtml+xml" and name in names:
                pages[name] = read_xhtml(name, archive.read(name).decode(
                    "utf-8", "replace"))
        for page in pages.values():
            check_page(page, findings)
        # Links may also point at non-XHTML files (images, CSS); those
        # count as files without ids.
        all_files = {n: set() for n in names}
        all_files.update({n: set(p.ids) for n, p in pages.items()})
        check_links_among(pages, all_files, findings)
    return findings


def check_links_among(pages, files, findings):
    for page in pages.values():
        for href in page.links:
            if href.startswith(EXTERNAL) or not href:
                continue
            target, _, fragment = href.partition("#")
            target = unquote(urlsplit(target).path)
            if target:
                name = posixpath.normpath(posixpath.join(
                    posixpath.dirname(page.name), target))
                if name not in files:
                    findings.append(Finding(page.name, "link-to-missing-file",
                                            href))
                    continue
            else:
                name = page.name
            if fragment and fragment not in files[name]:
                findings.append(Finding(page.name, "link-to-missing-fragment",
                                        href))


def summarize(findings):
    """check -> count, most frequent first."""
    counts = {}
    for finding in findings:
        counts[finding.check] = counts.get(finding.check, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


# Kept for callers that only have a regex to hand: what a check name means.
DESCRIPTIONS = {
    "link-to-missing-file": "a link names a file that is not in the set",
    "link-to-missing-fragment": "a link's #fragment matches no id",
    "image-without-alt": "an img element has no alt attribute",
    "image-empty-alt-not-decorative":
        "alt is empty but the image is not marked role=presentation",
    "heading-skips-level": "a heading is more than one level below the last",
    "empty-heading": "a heading with no text",
    "duplicate-id": "an id used more than once in one document",
    "table-without-headers-or-caption":
        "a data table with no th and no caption",
    "no-lang": "the html element declares no language",
    "no-title": "no title element, or an empty one",
    "not-well-formed": "the document could not be parsed",
}
