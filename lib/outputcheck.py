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

import json
import os
import posixpath
import shutil
import subprocess
import tempfile
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

def is_decorative(attributes):
    """Declared decorative: aria-hidden="true", which is what the filter
    writes, or role="presentation", which it used to and which some
    other pipeline may."""
    return attributes.get("aria-hidden") == "true" \
        or attributes.get("role") == "presentation"


class Page:
    """The facts the checks need from one HTML or XHTML document."""

    def __init__(self, name):
        self.name = name
        self.lang = None
        self.title = None
        self.ids = []               # in document order, duplicates kept
        self.links = []             # href values of <a>
        self.images = []            # (has_alt, alt, decorative, src)
        self.headings = []          # (level, text)
        self.tables = []            # (has_th, has_caption, role, wrapped)
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
                                     is_decorative(a), a.get("src", "")))
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._heading = [int(tag[1]), []]
        elif tag == "div" and "table-wrapper" in (a.get("class") or ""):
            self._in_wrapper = True
        elif tag == "table":
            self._table = [False, False, a.get("role"),
                           getattr(self, "_in_wrapper", False)]
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
            self._in_wrapper = False

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
                                is_decorative(el.attrib), el.get("src", "")))
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            page.headings.append((int(tag[1]),
                                  " ".join("".join(el.itertext()).split())))
        elif tag == "table":
            has_th = any(c.tag.replace(XHTML, "") == "th" for c in el.iter())
            has_caption = any(c.tag.replace(XHTML, "") == "caption"
                              for c in el.iter())
            page.tables.append((has_th, has_caption, el.get("role"), None))
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
        if any(c.isspace() for c in identifier):
            findings.append(Finding(where, "invalid-id", identifier))
    for has_alt, alt, decorative, src in page.images:
        if not has_alt:
            findings.append(Finding(where, "image-without-alt", src))
        elif not alt.strip() and not decorative:
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
    for index, (has_th, has_caption, role, wrapped) in enumerate(page.tables,
                                                                 1):
        if role == "presentation":
            continue
        if not has_th and not has_caption:
            findings.append(Finding(where, "table-without-headers-or-caption",
                                    f"table {index}"))
        if wrapped is False:
            # The filter's own invariant, checked on the output: a data
            # table sits in the focusable scroll region (WCAG 1.4.10).
            findings.append(Finding(where, "table-not-in-scroll-region",
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
        # Named by their path below the working directory, so a run with
        # several targets can tell print/tables.html from tables.html;
        # a page elsewhere is named by its file name alone.
        relative = os.path.relpath(path)
        name = relative.replace(os.sep, "/") if not relative.startswith("..") \
            else os.path.basename(path)
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
        "alt is empty but the image is not marked aria-hidden=\"true\"",
    "heading-skips-level": "a heading is more than one level below the last",
    "empty-heading": "a heading with no text",
    "duplicate-id": "an id used more than once in one document",
    "invalid-id": "an id containing whitespace, which no id may",
    "table-without-headers-or-caption":
        "a data table with no th and no caption",
    "table-not-in-scroll-region":
        "a data table outside the focusable scroll wrapper (HTML pages)",
    "no-lang": "the html element declares no language",
    "no-title": "no title element, or an empty one",
    "not-well-formed": "the document could not be parsed",
}


# --------------------------------------------------------------------------
# the full validators, when they are installed
# --------------------------------------------------------------------------
#
# epubcheck and the Nu HTML checker know their specifications in full and
# need Java, so they are optional: found through an environment variable
# naming the jar, or a command on the path, and skipped otherwise. Their
# findings are folded into the same report in the same shape, with the
# tool's own message id as the check name, so one file lists everything.

VALIDATORS = {
    "epubcheck": ("EPUBCHECK_JAR", "epubcheck"),
    "vnu": ("VNU_JAR", "vnu"),
}


def find_validator(name):
    """The command to run, as a list, or None.

    An environment variable naming the jar wins (EPUBCHECK_JAR, VNU_JAR);
    otherwise a command of that name on the path, which is what a
    package manager's epubcheck provides. Either needs java for a jar.
    """
    variable, command = VALIDATORS[name]
    jar = os.environ.get(variable, "").strip()
    if jar:
        if os.path.isfile(jar) and shutil.which("java"):
            return ["java", "-jar", jar]
        return None
    found = shutil.which(command)
    return [found] if found else None


def run_epubcheck(command, path):
    """epubcheck's messages as findings, or a finding that it failed."""
    findings = []
    with tempfile.TemporaryDirectory() as work:
        report = os.path.join(work, "epubcheck.json")
        try:
            subprocess.run(command + ["--json", report, path],
                           capture_output=True, text=True, timeout=600)
            with open(report, encoding="utf-8") as fh:
                result = json.load(fh)
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            return [Finding(os.path.basename(path), "epubcheck:failed",
                            str(exc))]
    for message in result.get("messages", []):
        severity = str(message.get("severity", "")).upper()
        if severity not in ("FATAL", "ERROR", "WARNING"):
            continue
        locations = message.get("locations") or [{}]
        for location in locations[:5]:
            where = location.get("path") or os.path.basename(path)
            line = location.get("line")
            detail = message.get("message", "")
            if line and line > 0:
                detail = f"line {line}: {detail}"
            findings.append(Finding(where, f"epubcheck:{message.get('ID')}",
                                    f"{severity.lower()}: {detail}"))
    return findings


def run_vnu(command, paths):
    """The Nu HTML checker's errors and warnings as findings.

    Its "info" messages -- Pandoc's trailing slashes on void elements,
    mostly -- are counted, not listed; they change nothing for a reader.
    """
    if not paths:
        return [], 0
    try:
        # --stdout: the checker writes its report to stderr otherwise,
        # where Java's own notices ("Picked up JAVA_TOOL_OPTIONS") land
        # too. The report is the first { onward, whatever precedes it.
        result = subprocess.run(
            command + ["--format", "json", "--stdout", "--exit-zero-always"]
            + paths, capture_output=True, text=True, timeout=600)
        text = result.stdout if "{" in result.stdout else result.stderr
        parsed = json.loads(text[text.index("{"):])
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        detail = str(exc)
        if isinstance(exc, ValueError):
            # The tool crashed before reporting. Its exception line says
            # why -- a Java too old for it, a jar that is not a jar -- so
            # that is what to show, in full.
            output = result.stdout + result.stderr
            crash = next((line for line in output.splitlines()
                          if "Exception" in line or "Error" in line), "")
            detail = ("the checker produced no report; it said: "
                      + (crash.strip() or repr(output[:200])))
        return [Finding("", "vnu:failed", detail)], 0
    findings, infos = [], 0
    for message in parsed.get("messages", []):
        kind = message.get("type")
        if kind == "error":
            check = "vnu:error"
        elif message.get("subType") == "warning":
            check = "vnu:warning"
        else:
            infos += 1
            continue
        where = os.path.basename(message.get("url", "").replace("file:", ""))
        line = message.get("lastLine")
        detail = message.get("message", "")
        if line:
            detail = f"line {line}: {detail}"
        findings.append(Finding(where, check, detail))
    return findings, infos


def run_validators(pages, epubs):
    """Run whichever of the two is installed. Returns (findings, notes),
    notes being one line per tool saying whether it ran."""
    findings, notes = [], []
    if epubs:
        command = find_validator("epubcheck")
        if command:
            for path in epubs:
                findings += run_epubcheck(command, path)
            notes.append(f"epubcheck ran on {len(epubs)} EPUB(s).")
        else:
            notes.append("epubcheck not found (set EPUBCHECK_JAR, or put "
                         "epubcheck on the path); skipped.")
    if pages:
        command = find_validator("vnu")
        if command:
            found, infos = run_vnu(command, pages)
            findings += found
            if any(f.check == "vnu:failed" for f in found):
                notes.append("The Nu HTML checker was found but failed to "
                             "run; see vnu:failed in the report (it needs "
                             "Java 17 or later).")
            else:
                notes.append(f"The Nu HTML checker ran on {len(pages)} "
                             "page(s)"
                             + (f"; {infos} informational message(s) not "
                                "listed." if infos else "."))
        else:
            notes.append("The Nu HTML checker not found (set VNU_JAR); "
                         "skipped.")
    return findings, notes
