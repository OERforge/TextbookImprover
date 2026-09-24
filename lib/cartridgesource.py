"""Reading an IMS Common Cartridge as a book's source.

A cartridge is a zip whose imsmanifest.xml names every resource -- its
type, its file, the files it uses -- and arranges them in an organization,
the course's outline. Versions 1.0 to 1.3 read the same way here: elements
are matched by their local names, whatever namespace a version gives them.

A webcontent resource whose file is HTML is a page; one whose file is a
Word document is a source the pipeline converts as well; any other file
is kept where it sat. Discussions, assignments, web links, assessments,
and tool links are activities in a course rather than a book's content,
and the unpacker reports them instead of dropping them without a word.

What LMS exports add is handled here too. Canvas writes a link to a
course file as $IMS-CC-FILEBASE$/path and to a page as
$WIKI_REFERENCE$/pages/slug, and follows many with a query of its own
(?canvas_=1&canvas_qs_wrap=1); its modules hold text headers, entries with
no resource and nothing beneath them, which head the entries after them.
Brightspace writes pages with no <title>, leaving the outline's title the
only one they have.
"""
import html
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from urllib.parse import unquote


def local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def children(element, name):
    return [c for c in element if local(c.tag) == name]


def text_of(element):
    return " ".join("".join(element.itertext()).split()) if element is not None else ""


def is_cartridge(path):
    """Whether a file is a Common Cartridge, by what it holds rather than
    its name: a zip whose imsmanifest.xml is a cartridge's."""
    if not zipfile.is_zipfile(path):
        return False
    try:
        with zipfile.ZipFile(path) as archive:
            head = archive.read("imsmanifest.xml")[:6000].decode(
                "utf-8", "replace")
    except (KeyError, zipfile.BadZipFile):
        return False
    return "imsccv1p" in head or "/imscc/" in head or \
        "IMS Common Cartridge" in head


# What each resource type is, by the part of its type that says so.
KINDS = (("imsdt", "discussion"), ("imswl", "web-link"),
         ("assignment", "assignment"), ("imsqti", "assessment"),
         ("learning-application-resource", "assessment"),
         ("assessment", "assessment"), ("lti", "tool-link"))


class Cartridge:
    def __init__(self, path):
        self.zip = zipfile.ZipFile(path)
        self.names = set(self.zip.namelist())
        root = ET.fromstring(self.zip.read("imsmanifest.xml"))
        self.resources = {}
        for element in root.iter():
            if local(element.tag) != "resource":
                continue
            files = [f.get("href") for f in children(element, "file")
                     if f.get("href")]
            self.resources[element.get("identifier")] = {
                "type": element.get("type", ""),
                "href": element.get("href") or (files[0] if files else ""),
                "files": files}
        self.version = text_of(next((e for e in root.iter()
                                     if local(e.tag) == "schemaversion"), None))
        self.title, self.language = "", ""
        metadata = next((e for e in root if local(e.tag) == "metadata"), None)
        if metadata is not None:
            title = next((e for e in metadata.iter() if local(e.tag) == "title"),
                         None)
            if title is not None:
                self.title = text_of(title)
                string = next((e for e in title.iter()
                               if local(e.tag) == "string"), None)
                if string is not None:
                    self.language = string.get("language", "")
            if not self.language:
                self.language = text_of(next((e for e in metadata.iter()
                                              if local(e.tag) == "language"),
                                             None))
        self.organizations = [e for e in root.iter()
                              if local(e.tag) == "organization"]

    def read(self, path):
        return self.zip.read(path)

    def kind(self, identifier):
        """page, source, file, or the kind of activity a resource is."""
        resource = self.resources.get(identifier)
        if resource is None:
            return "missing"
        kind = resource["type"].lower()
        href = resource["href"].lower()
        if kind.startswith("webcontent"):
            if href.endswith((".html", ".htm")):
                return "page"
            if href.endswith(".docx"):
                return "source"
            return "file"
        for part, name in KINDS:
            if part in kind:
                return name
        return "other"

    def outline(self):
        """(depth, title, resource identifier or None) for every entry, in
        order. The organization's untitled root item is not an entry. A
        Canvas text header -- no resource, nothing beneath it -- heads the
        entries after it at its level, until the next header."""
        out = []

        def walk(items, depth):
            under = False
            for item in items:
                title = text_of(next(iter(children(item, "title")), None))
                ref = item.get("identifierref")
                nested = children(item, "item")
                if not ref and not nested:
                    if title:
                        out.append((depth, title, None))
                        under = True
                    continue
                level = depth + (1 if under else 0)
                out.append((level, title, ref))
                walk(nested, level + 1)
        for organization in self.organizations:
            for item in children(organization, "item"):
                if not text_of(next(iter(children(item, "title")), None)) \
                        and not item.get("identifierref"):
                    walk(children(item, "item"), 0)
                else:
                    walk([item], 0)
        return out

    def web_link(self, identifier):
        """(title, url) of a web link resource."""
        resource = self.resources[identifier]
        try:
            root = ET.fromstring(self.read(resource["href"]))
        except (KeyError, ET.ParseError):
            return "", ""
        title = text_of(next((e for e in root.iter() if local(e.tag) == "title"),
                             None))
        url = next((e.get("href", "") for e in root.iter()
                    if local(e.tag) == "url"), "")
        return title, url


PLACEHOLDER = re.compile(r"(?:\$|%24)([A-Z_-]+)(?:\$|%24)")
CANVAS_QUERY = re.compile(r"\?canvas_[^\"'#\s>]*")


def resolve_placeholders(markup, page_path):
    """A page's LMS placeholders as paths relative to the page: a course
    file ($IMS-CC-FILEBASE$) is under web_resources/, a page
    ($WIKI_REFERENCE$/pages/slug) is wiki_content/slug.html. Canvas's own
    queries on local references go. Returns the markup and the names of
    placeholders nothing here resolves, for the report."""
    here = posixpath.dirname(page_path) or "."
    unresolved = set()

    def relative(target):
        return posixpath.relpath(target, here)

    def wiki(match):
        return relative("wiki_content/%s.html" % match.group(1))
    markup = re.sub(r"(?:\$|%24)WIKI_REFERENCE(?:\$|%24)/pages/([^\"'#?\s>]+)",
                    wiki, markup)

    def swap(match):
        name = match.group(1).replace("_", "-")
        if name == "IMS-CC-FILEBASE":
            return relative("web_resources")
        unresolved.add(match.group(1))
        return match.group(0)
    markup = PLACEHOLDER.sub(swap, markup)
    return CANVAS_QUERY.sub("", markup), unresolved


def with_title(markup, title):
    """The page with the outline's title in <title> when it has none of
    its own."""
    found = re.search(r"<title[^>]*>(.*?)</title>", markup, re.S | re.I)
    if found and found.group(1).strip() or not title:
        return markup
    element = "<title>%s</title>" % html.escape(title)
    if found:
        return markup[:found.start()] + element + markup[found.end():]
    head = re.search(r"<head[^>]*>", markup, re.I)
    if head:
        return markup[:head.end()] + element + markup[head.end():]
    opening = re.search(r"<html[^>]*>", markup, re.I)
    if opening:
        return (markup[:opening.end()] + "<head>" + element + "</head>"
                + markup[opening.end():])
    return "<html><head>%s</head><body>%s</body></html>" % (element, markup)


def unpublished(markup):
    """Canvas marks a page that students don't see."""
    return bool(re.search(r'<meta name="workflow_state" content="unpublished"',
                          markup))


def links_out(markup):
    """The one host every link on a page goes to, when the page is little
    more than those links: a reading list pointing at the reading."""
    hosts = re.findall(r'href="https?://([^/"]+)', markup)
    words = len(re.sub(r"<[^>]+>", " ", markup).split())
    if len(hosts) >= 3 and len(set(hosts)) == 1 and words < 40 * len(hosts):
        return hosts[0]
    return ""


def path_in(archive_names, href):
    """An href from the manifest as the archive holds it: manifests write
    some paths percent-encoded and some not."""
    if href in archive_names:
        return href
    decoded = unquote(href)
    return decoded if decoded in archive_names else href
