"""
sitesource -- a book saved from the web, read as what it was: a set of
URLs, each with bytes.

However the pages arrived, the first step makes them the same thing. A
browser's "complete" save is an .html per page that says in a comment
which URL it was, and a <name>_files directory beside it holding what
the page used, under names the browser chose. An .mhtml is one message
per page, each resource a part that names its URL. A WARC, which every
archiving crawler writes (wget, Browsertrix, ArchiveWeb.page, Heritrix),
is the best of the three: each URL with the bytes the server sent,
before any script ran. A WACZ is WARCs in a zip. From there on, one
pipeline:

  - every reference in every page is resolved: against the saved file's
    directory when the browser rewrote it to a local copy, otherwise
    against the page's own URL;
  - a reference to a page of the book becomes a reference to its file,
    one to a resource we hold becomes one to its copy, and one to
    anything else is left as it is. A reference to the book's own site
    that we don't hold is reported, since it will be broken offline; one
    to a host the project lists as third-party (a CDN serving a
    framework) is expected and isn't;
  - the generator is recognized from what the pages say about
    themselves, and its profile says where the content is and what
    around it is chrome;
  - the order is read from the pages' own menus.

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

import email
import glob
import gzip
import hashlib
import io
import zlib
import zipfile
import os
import posixpath
import re
from email import policy
from urllib.parse import quote, unquote, urldefrag, urljoin, urlsplit

import htmlparse as hp

REFERENCE_ATTRIBUTES = ("href", "src", "poster", "data",
                        "{http://www.w3.org/1999/xlink}href", "xlink:href")

# A profile: how to recognize a generator from a page's text, where its
# content is, and what inside the content is chrome. Selectors are one
# simple part each (see htmlparse.matches). Recognition is by what the
# generator writes about itself, never by asking.
PROFILES = [
    {"name": "just-the-docs",
     "detect": [r'<meta name="generator" content="Jekyll', r"just-the-docs"],
     "content": ["main"],
     "chrome": ["nav.js-toc", "a.anchor-heading", "nav.breadcrumb-nav",
                "footer", "div.search"]},
    {"name": "scribble",
     "detect": [r'class="navsettop"'],
     "transform": "scribble_tables",
     "content": ["div.main"],
     "authors": ["p.author"],
     "chrome": ["div.navsettop", "div.navsetbottom", "span.button-group",
                "a.heading-anchor", "div.tocset", "div.versionbox"]},
    {"name": "oercommons",
     "detect": [r'class="js-courseware-ct"'],
     "content": ["article.lesson-task-slide", "div.js-courseware-ct"],
     "title": "h2.lesson-task-title",
     "chrome": ["div.lesson-task-slides-controls"]},
    {"name": "asciidoctor",
     "detect": [r'<meta name="generator" content="Asciidoctor'],
     "content": ["div#content"],
     "chrome": ["div#toc", "div#footer", "a.anchor"]},
    {"name": "wordpress",
     "detect": [r'<meta name="generator" content="WordPress'],
     "content": ["main", "div#content", "article"],
     "chrome": ["nav", "footer", "aside", "div.sharedaddy"]},
    {"name": "generic",
     "detect": [],
     "content": ["main", "[role=main]", "article", "body"],
     "chrome": ["nav", "footer"]},
]

# Elements whose reference is fetched to show the page; anything else
# with an href (a link, an RDFa property on a span) is only a pointer.
FRAME_TAGS = ("iframe", "embed", "object")
RESOURCE_TAGS = ("img", "script", "link", "source", "video", "audio",
                 "track", "iframe", "embed", "object", "input", "image")

def _replace(element, replacements, parent_of):
    """Put replacements where element was, keeping its tail."""
    parent = parent_of.get(element)
    if parent is None:
        return
    index = list(parent).index(element)
    tail = element.tail
    parent.remove(element)
    for offset, new in enumerate(replacements):
        parent.insert(index + offset, new)
        parent_of[new] = parent
    if replacements:
        last = replacements[-1]
        last.tail = (last.tail or "") + (tail or "")
    elif tail:
        if index > 0:
            before = parent[index - 1]
            before.tail = (before.tail or "") + tail
        else:
            parent.text = (parent.text or "") + tail


def _owner(element, parent_of):
    """The table an element (a row) belongs to: its nearest table."""
    node = parent_of.get(element)
    while node is not None and hp.local(node.tag) != "table":
        node = parent_of.get(node)
    return node


def scribble_tables(content):
    """Scribble lays out things that aren't tables as tables. Of DCIC's
    335: a REPL interaction (prompt, code, result) is its cells' contents;
    a section's local table of contents (nothing but toclink links) is
    navigation, and goes; a verbatim block or a Racket block (one line a
    row) is one <pre>; and a Python/Pyret comparison, the one kind that
    is data, gets its language labels as header cells: the first row
    when the languages are columns (TwoColumn), each row's first cell
    when they are rows (TwoColumnAsRows).

    Three more have no class to go by, only their shape: code a line a
    row (each line a span.stt) is one <pre>; the book's contents, a link
    a row and nothing else, is a list; and a derivation laid out to line
    up its equals signs (T(k) | = | T(k-1) + c, and a relation alone in
    the middle column of every row) is marked a layout table.

    A REPL interaction nests: its result can hold another. So its cells
    are moved, not copied, and an inner table keeps a parent in the tree
    to be rewritten in turn. Returns how many of each were changed."""
    parent_of = hp.parents(content)
    counts = {"repl": 0, "local-toc": 0, "verbatim": 0, "comparison": 0,
              "code": 0, "contents": 0, "derivation": 0}
    relations = {"=", "<", ">", "\u2264", "\u2265", "\u2248", "\u2261",
                 "\u2192", "\u21d2", "<=", ">="}

    def own_rows(table):
        return [[c for c in r if hp.local(c.tag) in ("td", "th")]
                for r in table.iter() if hp.local(r.tag) == "tr"
                and _owner(r, parent_of) is table]

    def spaced_text(element):
        return "".join(element.itertext()).replace("\u00a0", " ")

    def short_label(cell):
        return len(hp.text_of(cell)) <= 20 and not any(
            hp.local(x.tag) in ("pre", "code", "table") for x in cell.iter())
    for table in [e for e in content.iter() if hp.local(e.tag) == "table"]:
        classes = (table.get("class") or "").split()
        cells = [c for c in table.iter() if hp.local(c.tag) in ("td", "th")]
        links = [a for a in table.iter() if hp.local(a.tag) == "a"]
        if "PyretReplInteraction" in classes:
            own = [c for row in table.iter() if hp.local(row.tag) == "tr"
                   and _owner(row, parent_of) is table
                   for c in row if hp.local(c.tag) in ("td", "th")]
            for cell in own:
                cell.tag = "div"
                cell.attrib.clear()
            _replace(table, own, parent_of)
            counts["repl"] += 1
        elif links and all("toclink" in (a.get("class") or "").split()
                           for a in links) and not classes:
            _replace(table, [], parent_of)
            counts["local-toc"] += 1
        elif "SVerbatim" in classes or "RktBlk" in classes:
            pre = table.makeelement("pre", {})
            # A line of code keeps its indentation, which Scribble writes
            # as non-breaking spaces.
            pre.text = "\n".join(
                "".join(row.itertext()).replace("\u00a0", " ").rstrip()
                for row in table.iter() if hp.local(row.tag) == "tr")
            _replace(table, [pre], parent_of)
            counts["verbatim"] += 1
        elif not classes and own_rows(table) and all(
                len(r) == 1 for r in own_rows(table)) and all(
                "".join(t for s in r[0].iter()
                        if hp.local(s.tag) == "span"
                        and "stt" in (s.get("class") or "").split()
                        for t in s.itertext()).strip()
                == spaced_text(r[0]).strip() != ""
                for r in own_rows(table)):
            pre = table.makeelement("pre", {})
            pre.text = "\n".join(spaced_text(r[0]).rstrip()
                                  for r in own_rows(table))
            _replace(table, [pre], parent_of)
            counts["code"] += 1
        elif not classes and own_rows(table) and all(
                not spaced_text(r[0]).strip() and len(r) == 1
                or len(r) == 1 and len([a for a in r[0].iter()
                                        if hp.local(a.tag) == "a"]) == 1
                and " ".join(spaced_text(r[0]).split()) == " ".join(
                    spaced_text(next(a for a in r[0].iter()
                                     if hp.local(a.tag) == "a")).split())
                for r in own_rows(table)):
            listing = table.makeelement("ul", {"class": "contents"})
            for r in own_rows(table):
                if not spaced_text(r[0]).strip():
                    continue                     # a spacer between parts
                item = listing.makeelement("li", {})
                link = next(a for a in r[0].iter() if hp.local(a.tag) == "a")
                link.tail = None
                item.append(link)
                listing.append(item)
            _replace(table, [listing], parent_of)
            counts["contents"] += 1
        elif not classes and own_rows(table) and all(
                len(r) == 3 and spaced_text(r[1]).strip() in relations
                for r in own_rows(table)):
            table.set("role", "presentation")
            counts["derivation"] += 1
        elif "TwoColumn" in classes or "TwoColumnAsRows" in classes:
            rows = [r for r in table.iter() if hp.local(r.tag) == "tr"
                    and _owner(r, parent_of) is table]
            grid = [[c for c in r if hp.local(c.tag) in ("td", "th")]
                    for r in rows]
            if "TwoColumn" in classes:
                labels, scope = (grid[0] if grid else []), "col"
            else:
                labels, scope = [r[0] for r in grid if r], "row"
            if labels and all(short_label(c) for c in labels):
                for cell in labels:
                    cell.tag = "th"
                    cell.set("scope", scope)
                counts["comparison"] += 1
    return counts


# Words that say where a link goes rather than what is there. "Home" and
# "Contents" are left out: they are what a page is called as often as
# they are a direction to it.
NAVIGATION_WORDS = {"up", "prev", "previous", "next", "top", "back"}

MATH_SCRIPT = re.compile(r"math/(tex|mml)", re.I)


def detect_profile(texts):
    """The profile whose every detection pattern appears in most pages."""
    for profile in PROFILES:
        if not profile["detect"]:
            continue
        hits = sum(1 for t in texts
                   if all(re.search(p, t) for p in profile["detect"]))
        if hits * 2 > len(texts):
            return profile
    return PROFILES[-1]


def canonical(url):
    """A page's URL for comparing: no fragment, and a directory named for
    its index file. The query stays, since some sites tell their pages
    apart by nothing else (OER Commons's ?section=3); page_key() tries a
    reference without it when it matches no page with it."""
    base, _, query = urldefrag(url)[0].partition("?")
    if base.endswith("/"):
        base += "index.html"
    return base + ("?" + query if query else "")


def page_key(site, url):
    """The page a reference names, or None: its canonical URL, or that
    URL without its query (a tracking parameter, or ?section=0 naming the
    lesson page that holds section 0)."""
    key = canonical(url)
    if key in site.pages:
        return key
    bare = key.split("?", 1)[0]
    return bare if bare in site.pages else None


class Page:
    def __init__(self, url, text, path=None, local=None):
        self.url = canonical(url)
        self.text = text
        self.path = path            # the saved file, when there is one
        self.local = local or {}    # local reference -> resource key
        self.root = None
        self.name = None


class Site:
    """Pages by canonical URL; resources by key (a URL, or a content hash
    for a browser's local copy), each (bytes, suggested file name)."""

    def __init__(self):
        self.pages = {}
        self.resources = {}
        self.by_url = {}            # resource URL -> key
        self.redirects = {}         # URL -> where it redirected
        self.notes = []
        self.kind = ""

    def add_resource(self, data, name, url=None):
        key = "sha1:" + hashlib.sha1(data).hexdigest()
        self.resources.setdefault(key, (data, name))
        if url:
            self.by_url[urldefrag(url)[0]] = key
        return key


SAVED_FROM = re.compile(r"<!--\s*saved from url=\(\d+\)(\S+?)\s*-->")
CANONICAL = re.compile(r'<link[^>]*rel="canonical"[^>]*href="([^"]+)"', re.I)


def load_saved(directory):
    """A browser's "complete" saves: X.html beside X_files/."""
    site = Site()
    site.kind = "browser save"
    for path in sorted(glob.glob(os.path.join(directory, "*.htm*"))):
        with open(path, "rb") as fh:
            raw = fh.read()
        text = raw.decode("utf-8", errors="replace")
        m = SAVED_FROM.search(text[:2000]) or CANONICAL.search(text[:20000])
        url = m.group(1) if m else "file:///" + os.path.basename(path)
        if not m:
            site.notes.append((os.path.basename(path), "no-url",
                               "the file says nowhere what URL it was saved "
                               "from; links to it from other pages won't "
                               "find it"))
        page = Page(url, text, path)
        files = os.path.splitext(path)[0] + "_files"
        if os.path.isdir(files):
            for resource in sorted(glob.glob(os.path.join(files, "**", "*"),
                                             recursive=True)):
                if not os.path.isfile(resource):
                    continue
                relative = os.path.relpath(resource, directory).replace(
                    os.sep, "/")
                with open(resource, "rb") as fh:
                    data = fh.read()
                name = os.path.basename(resource)
                if name.endswith(".download"):     # Chrome's name for a script
                    name = name[:-len(".download")]
                page.local[relative] = site.add_resource(data, name)
        if page.url in site.pages:
            site.notes.append((os.path.basename(path), "duplicate-page",
                               f"saved twice as {page.url}; the first is used"))
            continue
        site.pages[page.url] = page
    return site


def load_mhtml(paths):
    """One .mhtml per page, as Chrome writes it."""
    site = Site()
    site.kind = "MHTML"
    for path in sorted(paths):
        with open(path, "rb") as fh:
            message = email.message_from_binary_file(fh, policy=policy.default)
        url = message["Snapshot-Content-Location"] or ""
        html = None
        for part in message.walk():
            if part.is_multipart():
                continue
            location = part["Content-Location"] or ""
            data = part.get_payload(decode=True) or b""
            if part.get_content_type() == "text/html" and location == url \
                    and html is None:
                charset = part.get_content_charset() or "utf-8"
                html = data.decode(charset, errors="replace")
            elif location:
                name = posixpath.basename(urlsplit(location).path) or "file"
                site.add_resource(data, name, location)
        if html is None:
            site.notes.append((os.path.basename(path), "no-page",
                               "no HTML part at the snapshot's own URL"))
            continue
        page = Page(url, html, path)
        if page.url in site.pages:
            site.notes.append((os.path.basename(path), "duplicate-page",
                               f"saved twice as {page.url}; the first is used"))
            continue
        site.pages[page.url] = page
    return site


def _warc_records(stream):
    """(headers, block) for each record of a WARC, gzipped per record or
    not: a version line, headers, a blank line, Content-Length bytes."""
    while True:
        line = stream.readline()
        if not line:
            return
        if not line.strip():
            continue
        if not line.startswith(b"WARC/"):
            raise ValueError(f"not a WARC record: {line[:40]!r}")
        headers = {}
        while True:
            line = stream.readline()
            if not line or not line.strip():
                break
            name, _, value = line.decode("utf-8", "replace").partition(":")
            headers[name.strip().lower()] = value.strip()
        length = int(headers.get("content-length", "0"))
        yield headers, stream.read(length)


def _http_response(block):
    """(status, headers, body) from an HTTP response as a WARC holds it:
    chunked transfer undone, gzip or deflate content decoded."""
    head, _, body = block.partition(b"\r\n\r\n")
    lines = head.decode("iso-8859-1").split("\r\n")
    parts = lines[0].split(" ", 2)
    status = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    if "chunked" in headers.get("transfer-encoding", "").lower():
        out, rest = b"", body
        while rest:
            size_line, _, rest = rest.partition(b"\r\n")
            size = int(size_line.split(b";")[0].strip() or b"0", 16)
            if size == 0:
                break
            out, rest = out + rest[:size], rest[size + 2:]
        body = out
    encoding = headers.get("content-encoding", "").lower()
    if encoding in ("gzip", "x-gzip"):
        body = gzip.decompress(body)
    elif encoding == "deflate":
        try:
            body = zlib.decompress(body)
        except zlib.error:
            body = zlib.decompress(body, -zlib.MAX_WBITS)
    elif encoding and encoding != "identity":
        raise ValueError(f"content encoded as {encoding}, which the "
                         "standard library can't decode")
    return status, headers, body


def _warc_streams(path):
    """Each WARC in path: the file itself, or a WACZ's archive/*.warc*."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for name in sorted(archive.namelist()):
                if name.startswith("archive/") and ".warc" in name:
                    data = archive.read(name)
                    yield name, (gzip.GzipFile(fileobj=io.BytesIO(data))
                                 if name.endswith(".gz") else io.BytesIO(data))
        return
    with open(path, "rb") as fh:
        head = fh.read(2)
    yield path, (gzip.open(path) if head == b"\x1f\x8b" else open(path, "rb"))


def load_warc(paths):
    """Response records from one or more WARC or WACZ files. An HTML
    response on the host of the first page is a page; anything else a
    resource. A redirect is followed when a reference is looked up."""
    site = Site()
    site.kind = "WARC"
    htmls, aliases, seeds, parts = [], [], [], []
    for path in sorted(paths):
        seeds += _recorded_pages(path)
        for name, stream in _warc_streams(path):
            with stream:
                for headers, block in _warc_records(stream):
                    kind_of_record = headers.get("warc-type")
                    if kind_of_record not in ("response", "revisit"):
                        continue
                    url = headers.get("warc-target-uri", "").strip("<>")
                    if not url.startswith(("http://", "https://")):
                        continue
                    if kind_of_record == "revisit":
                        # A browser's archive stores a redirect, and a
                        # payload it has already recorded, as a revisit:
                        # the HTTP headers, and a pointer to the earlier
                        # record in place of the body.
                        try:
                            status, http, _ = _http_response(block)
                        except ValueError:
                            continue
                        if 300 <= status < 400 and http.get("location"):
                            site.redirects[urldefrag(url)[0]] = urljoin(
                                url, http["location"])
                        elif 200 <= status < 300:
                            earlier = headers.get("warc-refers-to-target-uri",
                                                  "").strip("<>")
                            if earlier and earlier != url:
                                aliases.append((url, earlier))
                        continue
                    try:
                        status, http, body = _http_response(block)
                    except ValueError as exc:
                        site.notes.append((url, "unreadable-response",
                                           str(exc)))
                        continue
                    if 300 <= status < 400 and http.get("location"):
                        site.redirects[urldefrag(url)[0]] = urljoin(
                            url, http["location"])
                        continue
                    if status != 200:
                        continue
                    kind = http.get("content-type", "").split(";")[0].strip()
                    fragment = _html_in_json(body) if "json" in kind else None
                    if fragment is not None:
                        parts.append((url, fragment, body))
                    elif kind in ("text/html", "application/xhtml+xml"):
                        charset = re.search(r"charset=([\w-]+)",
                                            http.get("content-type", ""))
                        htmls.append((url, body.decode(
                            charset.group(1) if charset else "utf-8",
                            errors="replace")))
                    else:
                        leaf = posixpath.basename(urlsplit(url).path)
                        site.add_resource(body, leaf or "file", url)
    for url, earlier in aliases:
        key = site.by_url.get(urldefrag(earlier)[0])
        if key:
            site.by_url.setdefault(urldefrag(url)[0], key)
    # The book's site: the first page the archive says was recorded (a
    # WACZ lists them), or else the first HTML fetched, which for a crawl
    # is where it started. A browser fetches other sites' HTML first
    # often enough (a sign-in relay, a share widget).
    host = urlsplit(seeds[0]).netloc if seeds else (
        urlsplit(htmls[0][0]).netloc if htmls else "")
    for url, text in htmls:
        if urlsplit(url).netloc == host:
            page = Page(url, text)
            site.pages.setdefault(page.url, page)
        else:
            site.add_resource(text.encode("utf-8"),
                              posixpath.basename(urlsplit(url).path)
                              or "page.html", url)
    # HTML delivered as JSON is a page only when it's part of a page the
    # archive holds: the same address with another query, as a lesson
    # fetches its sections. Anything else carrying HTML in JSON (an
    # oEmbed answer, a widget) is a resource like any JSON.
    for url, fragment, body in parts:
        bare = canonical(url).split("?", 1)[0]
        if bare in site.pages and canonical(url) not in site.pages:
            page = Page(url, fragment)
            site.pages[page.url] = page
        else:
            site.add_resource(body, posixpath.basename(urlsplit(url).path)
                              or "data.json", url)
    return site


def _recorded_pages(path):
    """The pages a WACZ says were recorded, in order."""
    if not zipfile.is_zipfile(path):
        return []
    import json
    with zipfile.ZipFile(path) as archive:
        if "pages/pages.jsonl" not in archive.namelist():
            return []
        urls = []
        for line in archive.read("pages/pages.jsonl").decode(
                "utf-8", "replace").splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict) and entry.get("url"):
                urls.append(entry["url"])
        return urls


def _html_in_json(body):
    """A page of HTML delivered as JSON, as a site that draws its pages
    by script fetches them (OER Commons: {"template": "<div ...>"}), as
    a document with its first heading for a title; None for any other
    JSON."""
    import json
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    for key in ("template", "html", "content"):
        value = data.get(key)
        if isinstance(value, str) and value.lstrip().startswith("<"):
            m = re.search(r"<h[1-3][^>]*>(.*?)</h[1-3]>", value, re.S)
            title = " ".join(re.sub(r"<[^>]+>", " ", m.group(1)).split()) \
                if m else ""
            return ("<!DOCTYPE html><html><head><title>" + title +
                    "</title></head><body>" + value + "</body></html>")
    return None


def follow(site, url):
    """A URL after any redirects the archive recorded."""
    seen = set()
    while url in site.redirects and url not in seen:
        seen.add(url)
        url = site.redirects[url]
    return url


def is_warc(path):
    """Whether a file holds WARC records, by its first bytes rather than
    its name: an upload or a download may have renamed it
    (cs168_warc.gz), and a WACZ is a zip of them."""
    if not os.path.isfile(path):
        return False
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            return any(name.startswith("archive/") and ".warc" in name
                       for name in archive.namelist())
    with open(path, "rb") as fh:
        head = fh.read(2)
    try:
        if head == b"\x1f\x8b":
            with gzip.open(path) as fh:
                return fh.read(5) == b"WARC/"
        with open(path, "rb") as fh:
            return fh.read(5) == b"WARC/"
    except OSError:
        return False


def load(inputs):
    """A directory of saves, a directory of .mhtml, .mhtml files, or WARC
    and WACZ files, whatever they are called."""
    if all(is_warc(p) for p in inputs):
        return load_warc(inputs)
    if len(inputs) == 1 and os.path.isdir(inputs[0]):
        mhtml = glob.glob(os.path.join(inputs[0], "*.mhtml")) + \
            glob.glob(os.path.join(inputs[0], "*.mht"))
        if mhtml:
            return load_mhtml(mhtml)
        return load_saved(inputs[0])
    return load_mhtml(inputs)


# ---------------------------------------------------------------- naming

def page_names(site):
    """A file name for each page: its URL's path below what every page
    shares, made safe for a link and flat, since convert.py reads the
    sources of one directory."""
    from names import safe_stem
    paths = [urlsplit(u).path for u in site.pages]
    dirs = [posixpath.dirname(p) or "/" for p in paths]
    common = posixpath.commonpath(dirs) if dirs else "/"
    # A landing page above the book (a site root offering editions) would
    # make every name carry the edition's directory; the directory most
    # pages share is the book's, when nearly all of them share it.
    if dirs:
        top = max(set(dirs), key=dirs.count)
        if dirs.count(top) >= 0.8 * len(dirs):
            common = top
    site.root = common
    one_path = len({urlsplit(u).path for u in site.pages}) == 1
    # The page with no query, among pages numbered by one (?section=1,
    # ?section=2), is the one a menu calls ?section=0: named so.
    numbered = {m.group(1) for u in site.pages for m in
                [re.fullmatch(r"(\w+)=\d+", urlsplit(u).query)] if m}
    zero = numbered.pop() + "=0" if one_path and len(numbered) == 1 else ""
    taken = set()
    for url, page in site.pages.items():
        path = urlsplit(url).path
        rest = posixpath.relpath(path, common) if (
            path + "/").startswith(common.rstrip("/") + "/") \
            else path.lstrip("/")
        stem = re.sub(r"\.x?html?$", "", rest).replace("/", "-")
        # Pages told apart by their query take it into their names; when
        # every page has one path, the query alone names them.
        query = urlsplit(url).query or zero
        if query:
            stem = query if one_path else stem + "-" + query
        stem = safe_stem(stem) or "page"
        base, n = stem, 2
        while stem in taken:
            stem, n = f"{base}-{n}", n + 1
        taken.add(stem)
        page.name = stem


def resource_names(site, used):
    """A file under assets/ for each resource a page uses: its own name,
    unless two different files share it."""
    from names import safe_stem
    from epubsource import sniff
    extensions = {"image/png": ".png", "image/jpeg": ".jpg",
                  "image/gif": ".gif", "image/webp": ".webp",
                  "image/svg+xml": ".svg"}
    names, taken = {}, {}
    for key in sorted(used):
        data, name = site.resources[key]
        stem, ext = os.path.splitext(name)
        # An image served under another format's name (a JPEG as .png)
        # takes the name its bytes have; a reading system trusts the
        # extension, and epubcheck says so.
        right = extensions.get(sniff(data) or "")
        if right and ext.lower() in extensions.values() and \
                ext.lower() not in (right, ".jpeg" if right == ".jpg" else ""):
            site.notes.append((name, "extension-corrected",
                               f"the file is {right[1:].upper()}; written "
                               f"as {stem}{right}"))
            ext = right
        stem = safe_stem(stem) or "file"
        candidate = stem + ext.lower()
        if candidate in taken and taken[candidate] != key:
            candidate = f"{stem}-{key[5:13]}{ext.lower()}"
        taken[candidate] = key
        names[key] = "assets/" + candidate
    return names


# ----------------------------------------------------------------- order

def _href(element):
    return element.get("href")


USES_MATHJAX = re.compile(r"mathjax|math/tex", re.I)
TEX = re.compile(r"\\\((.+?)\\\)|\\\[(.+?)\\\]", re.S)
NO_MATH_IN = ("pre", "code", "script", "style", "textarea", "kbd", "samp")


def _tex_parts(text):
    """[(literal, tex, display)]: the text split at MathJax's delimiters."""
    parts, last = [], 0
    for m in TEX.finditer(text):
        parts.append((text[last:m.start()], m.group(1) or m.group(2),
                      m.group(1) is None))
        last = m.end()
    if parts:
        parts.append((text[last:], None, False))
    return parts


def mathjax_math(content):
    """MathJax's delimiters, as the page's own HTML carries them before
    any script has run, written as the <script type="math/tex"> Pandoc's
    HTML reader takes for math. A browser's save has the rendering and
    not the TeX; an archive of the site has the TeX, which is the whole
    reason to prefer one.

    Only text is looked at, and never inside code: \\( is a character
    pair a programming book may print, and Pandoc's own
    tex_math_single_backslash extension would read it as math there too
    (measured). Returns how many formulas were found."""
    found = 0

    def script(tex, display):
        el = content.makeelement(
            "script", {"type": "math/tex; mode=display" if display
                       else "math/tex"})
        el.text = tex
        return el

    def walk(element):
        nonlocal found
        if hp.local(element.tag) in NO_MATH_IN:
            return
        for child in list(element):
            walk(child)
        # Each part holds the text before a formula, so that text is the
        # tail of whatever was inserted for the formula before it.
        def append(parts, into):
            nonlocal found
            for index, (literal, tex, display) in enumerate(parts):
                if index and into:
                    into[-1].tail = literal
                if tex is not None:
                    into.append(script(tex, display))
                    found += 1

        children = []
        parts = _tex_parts(element.text or "")
        if parts:
            element.text = parts[0][0]
            append(parts, children)
        for child in list(element):
            children.append(child)
            parts = _tex_parts(child.tail or "")
            if parts:
                child.tail = parts[0][0]
                append(parts, children)
        if children:
            element[:] = children
    walk(content)
    return found


def order(site, titles=None):
    """The book's order from its own menus, as (depth, title, url) for
    each page the menu names, and a note on where it came from.

    Every element holding links to at least three pages is a candidate,
    on every page. What separates a table of contents from an index,
    which may reach every page too, isn't how often it links a page: a
    detailed contents links a chapter once and each of its sections
    again. It's that a contents keeps a page's links together (the
    chapter, then its sections) and an index scatters them through the
    alphabet. So the links, read in order with repeats of the same page
    collapsed, must come to not much more than one run per page. Among
    the candidates left, the one reaching most pages wins; a tie goes to
    the smaller element."""
    best = None
    seen = {}
    containers = ("nav", "ul", "ol", "div", "table", "aside", "section",
                  "header", "main", "body", "dl")
    for url, page in site.pages.items():
        for element in page.root.iter():
            if hp.local(element.tag) not in containers:
                continue
            links, sequence = [], []
            for a in element.iter():
                if hp.local(a.tag) != "a" or not _href(a):
                    continue
                target = page_key(site, urljoin(url, _href(a)))
                if target:
                    links.append(target)
                    if target not in sequence:
                        sequence.append(target)
            if len(sequence) < 3:
                continue
            runs = sum(1 for i, t in enumerate(links)
                       if i == 0 or links[i - 1] != t)
            if runs > 1.25 * len(sequence) + 1:
                continue
            key = tuple(sequence)
            seen[key] = seen.get(key, 0) + 1
            size = sum(1 for _ in element.iter())
            rank = (len(sequence), size)
            if best is None or rank[0] > best[0][0] or \
                    (rank[0] == best[0][0] and rank[1] < best[0][1]):
                best = (rank, element, url)
    if best is None:
        return [], "no menu reaching three pages; pages are in file order"
    (reach, _), container, where = best
    entries, placed = [], set()
    parent_of = hp.parents(container)
    for a in container.iter():
        if hp.local(a.tag) != "a" or not _href(a):
            continue
        target = page_key(site, urljoin(where, _href(a)))
        if target is None or target in placed:
            continue
        placed.add(target)
        depth, node = 0, parent_of.get(a)
        while node is not None and node is not container:
            if hp.local(node.tag) in ("ul", "ol"):
                depth += 1
            node = parent_of.get(node)
        title = hp.text_of(a)
        if not re.search(r"\w", title) or \
                title.strip("←→«»<> ").lower() in NAVIGATION_WORDS:
            title = (titles or {}).get(target) or title
            # An icon (🔗, a heading's anchor) or a word that says where
            # the link goes rather than what's there: the page's own title.
            title = next((hp.text_of(e) for e in
                          site.pages[target].root.iter()
                          if hp.local(e.tag) == "title"), title)
        entries.append([depth, title, target])
    if entries and len({e[0] for e in entries}) == 1:
        # One level of list, or none: read depth from numbering, "5.2 …",
        # with a part numbered in roman numerals above the chapters.
        roman = re.compile(r"^[IVXLC]+\s")
        parts = any(roman.match(e[1]) for e in entries)
        for entry in entries:
            m = re.match(r"^(\d+(?:\.\d+)*)\.?\s", entry[1])
            entry[0] = (m.group(1).count(".") + parts) if m else 0
    else:
        low = min(e[0] for e in entries)
        for entry in entries:
            entry[0] -= low
        # A site's name, linking home, above a menu that is otherwise one
        # level deeper: the home page is the menu's first entry, not the
        # parent of everything.
        if entries[0][0] == 0 and all(e[0] > 0 for e in entries[1:]):
            entries[0][0] = min(e[0] for e in entries[1:])
            low = min(e[0] for e in entries)
            for entry in entries:
                entry[0] -= low
    note = (f"from a {hp.local(container.tag)} on "
            f"{site.pages[where].name}.html reaching {reach} of "
            f"{len(site.pages)} pages")
    return [tuple(e) for e in entries], note


# ------------------------------------------------------------ rewriting

def rewrite(site, page, keep_hosts, resource_key_names, used, missing):
    """Point every reference in the page at what we hold."""
    origin = "{0.scheme}://{0.netloc}".format(urlsplit(page.url))
    base_dir = os.path.dirname(page.path) if page.path else ""
    for element in page.root.iter():
        if not isinstance(element.tag, str):
            continue
        for attribute in REFERENCE_ATTRIBUTES:
            value = element.get(attribute)
            if not value or value.startswith(("#", "data:", "mailto:",
                                              "javascript:", "tel:")):
                continue
            tag = hp.local(element.tag)
            if tag in FRAME_TAGS and attribute in ("src", "data"):
                # A frame shows something that lives elsewhere (a video's
                # player) and stays pointed there, even when the archive
                # recorded what it showed; it's never reported missing.
                absolute = urljoin(page.url, value)
                if absolute != value and not value.startswith("//"):
                    element.set(attribute, absolute)
                continue
            is_link = tag not in RESOURCE_TAGS or (
                tag == "link" and "stylesheet" not in (element.get("rel")
                                                       or "")
                and "icon" not in (element.get("rel") or ""))
            new = localize(site, page, value, origin, base_dir, keep_hosts,
                           used, missing, is_link)
            if new is not None:
                element.set(attribute, new)
        srcset = element.get("srcset")
        if srcset:
            parts = []
            for candidate in srcset.split(","):
                bits = candidate.strip().split()
                if bits:
                    new = localize(site, page, bits[0], origin, base_dir,
                                   keep_hosts, used, missing, False)
                    parts.append(" ".join([new or bits[0]] + bits[1:]))
            element.set("srcset", ", ".join(parts))


def localize(site, page, value, origin, base_dir, keep_hosts, used, missing,
             is_link):
    """The reference to use for value, or None to leave it. What can't be
    held is recorded in missing as (page, kind, url): a link to a page of
    the book's own site that wasn't saved, or a resource (an image, a
    stylesheet, a script) on any host but a listed third party."""
    plain, fragment = urldefrag(value)
    # A browser's local copy, named relative to the saved file.
    local = unquote(plain).lstrip("./") if plain.startswith("./") or \
        not re.match(r"^[a-z][a-z0-9+.-]*:|^//|^/", plain, re.I) else None
    if local is not None and page.local:
        for candidate in (unquote(plain)[2:] if plain.startswith("./")
                          else unquote(plain), local):
            key = page.local.get(candidate)
            if key:
                used.add(key)
                return PLACEHOLDER + key
    absolute = urljoin(page.url, value)
    target, fragment = urldefrag(absolute)
    # A redirect may have been recorded for the URL as written or for its
    # canonical form (a directory, before index.html was added).
    target = follow(site, target)
    absolute = target + ("#" + fragment if fragment else "")
    key = page_key(site, absolute) or page_key(
        site, follow(site, canonical(absolute)))
    target_page = site.pages.get(key) if key else None
    if target_page is not None:
        return target_page.name + ".html" + ("#" + fragment_href(fragment)
                                             if fragment else "")
    key = site.by_url.get(target)
    if key:
        used.add(key)
        return PLACEHOLDER + key + ("#" + fragment if fragment else "")
    host = urlsplit(target).netloc
    if is_link:
        if absolute.startswith(origin + "/") and re.search(
                r"(/|\.x?html?)$", urlsplit(target).path):
            missing.append((page.name + ".html", "page-not-saved", target))
    elif host and host not in keep_hosts:
        missing.append((page.name + ".html", "resource-not-held", target))
    return absolute if absolute != value and urlsplit(value).scheme == "" \
        and not value.startswith("//") else None


PLACEHOLDER = "oer-resource:"


def fragment_id(fragment):
    """An id, from a fragment or a name, in the one form both sides use.
    Scribble writes <a name="(part._x)"> and links to #%28part._x%29: a
    browser decodes the fragment before looking, epubcheck and our own
    check don't. And a name may hold a space ("section 5.2"), which an
    id can't. So: decoded, whitespace made underscores, and in a link
    only what a URL can't hold is encoded again."""
    return re.sub(r"\s+", "_", unquote(fragment).strip())


def fragment_href(fragment):
    return quote(fragment_id(fragment), safe="!$&'()*+,;=:@/?-._~")


def finish_references(markup, names):
    """Replace each placeholder with the resource's file."""
    return re.sub(re.escape(PLACEHOLDER) + r"(sha1:[0-9a-f]{40})",
                  lambda m: names.get(m.group(1), m.group(0)), markup)
