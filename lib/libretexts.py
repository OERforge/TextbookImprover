"""
libretexts -- a LibreTexts book, read as the site shows it.

LibreTexts (libretexts.org) runs on NICE CXone Expert, formerly
MindTouch. A book is a tree of pages under its home page; a page's text
is its section.mt-content-container; and a landing page (the home page,
a chapter) lists the pages under it in the site's order, in the HTML the
server sends. The rest of what a reader sees, the site's scripts make
after the page loads, from the page's own text or from data they fetch:

  - MathJax (version 4 on the pages this was written from) typesets the
    TeX, numbers every display formula ("tags: all") as the page's
    number, a dot, and a count (14.4.2 on page 14.4), resolves \\ref and
    \\eqref written in the text to those numbers, expands
    \\PageIndex{2} to 14.4.2 (Figure \\(\\PageIndex{2}\\)), and reads
    mhchem's \\ce;
  - the Table of Contents, the Index, and Detailed Licensing are empty
    pages a script fills: from the book's tree, from the site's tag
    directory, and from LibreTexts' license report.

So read() does each from what the archive holds, as the scripts do it
(read from the scripts themselves, which the archive also holds):

  - the order is the listings', from the home page down; the Front
    Matter's and Back Matter's pages are the book's front and back
    matter, their own landing pages left out, as the site's contents
    leaves them out;
  - TitlePage is left out, since the run makes the title page from the
    book's title and authors (what TitlePage adds is a QR code drawn by
    script); Table of Contents is the run's own contents page, at its
    name; Index and Detailed Licensing are made from their data when
    the archive holds it, and left out when it doesn't;
  - the home page is left out too: its listing is the contents, and its
    text is the book's description;
  - each page's formulas are numbered and its references resolved as
    MathJax does it, \\PageIndex expanded (in text, formulas, alt
    text), and \\ce rewritten (mhchem.py). A display formula with a
    number or a label is written as a LaTeX book's is read (an
    equation span: the labels' anchors, the formula with its number as
    a \\tag, the number), so every target sets the numbers where a LaTeX
    book's go; the formula is a <math> carrying its TeX as an
    annotation, which Pandoc's reader takes as the formula (3.4 and
    later), where a <script> would close the span around it.

Verified on Instrumental Analysis (chem.libretexts.org, archived with
ArchiveWeb.page in October 2026): the numbers and references match
MathJax 4.1.3's own, run with the pages' configuration on every page.
Anything this doesn't read is reported, never guessed.

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

import html as html_module
import json
import re
from urllib.parse import unquote, urljoin, urlsplit

import htmlparse as hp
import latexsource
import mhchem
import sitesource

MATTER = {"Front Matter": "front", "Back Matter": "back"}
# Attributes the site's scripts and editor use and a book has no use for:
# a table cell's copy of its column's header (for narrow screens), and
# where a section was transcluded from.
NOISE = ("data-th", "mt-section-origin", "data-page-id",
         "data-user-can-edit", "data-title-editor-available")
REF = re.compile(r"\\(eq)?ref\s*\{([^{}]*)\}")
PAGE_INDEX = re.compile(r"\\PageIndex\s*\{([^{}]*)\}")
ONLY_PAGE_INDEX = re.compile(r"\s*\\PageIndex\s*\{([^{}]*)\}\s*")
DELIMITED_PAGE_INDEX = re.compile(r"\\\(\s*\\PageIndex\s*\{([^{}]*)\}\s*\\\)")
STRIP = re.compile(r"\\(?:nonumber|notag)(?![A-Za-z@])")
# MathJax's environments that take tags: one numbered among them suppresses
# the display formula's own number (AllTags.finalize), and each numbers its
# rows, or not when it's starred, as LaTeX does.
TAGGABLE = re.compile(r"\\begin\s*\{(equation|align|gather|multline|alignat|"
                      r"flalign|eqnarray|xalignat|xxalignat)\*?\}")
COUNTS = {
    "numbered-formulas": "display formula(s) numbered or labeled as MathJax "
                         "does it, set as a LaTeX book's numbered formula is",
    "references": "\\ref or \\eqref in the text made a link to its formula",
    "page-index": "\\PageIndex expanded to the page's number",
    "page-index-attribute": "alt or title text with \\PageIndex expanded",
    "mhchem": "\\ce written as plain TeX (mhchem.py)",
    "index-terms": "Index entries made from the site's tag directory",
    "boxes": "example, exercise, note, and other box(es) given class box, "
             "which an HTML target and an EPUB draw",
    "line-breaks": "formula(s) broken into lines by a bare \\\\, which MathJax "
                   "takes and texmath and LaTeX don't, set in a gathered environment",
    "editor-marks": "mark(s) the site's editor draws between paragraphs, saved into "
                    "a page, taken out",
}


def _classes(element):
    return (element.get("class") or "").split()


def content_of(root):
    found = hp.select(root, "section.mt-content-container")
    return found[0] if found else None


def _script_value(text, name):
    """A string the page's setup script assigns, window.Name = "..."."""
    m = re.search(r'window\.%s\s*=\s*"((?:[^"\\]|\\.)*)"' % name, text)
    return m.group(1).replace('\\"', '"') if m else None


def _parse_int(part):
    """JavaScript's parseInt(part, 10), as a string."""
    m = re.match(r"\s*([+-]?\d+)", part)
    return str(int(m.group(1))) if m else "NaN"


def numbering(text):
    """(front, offset): what the page's MathJax setup puts before a
    formula's count and before \\PageIndex's argument, and what it adds to
    the count. As the setup script does it: PageNum when it isn't "auto";
    otherwise the page's name up to its colon, each part with a 0 in it
    read as a number (14.04 is 14.4), and a dot after it ("14.4."); with
    no colon, nothing. InitialOffset, when it reads as a nonzero number,
    is added to each count."""
    front = (_script_value(text, "PageNum") or "auto").strip()
    if front == "auto":
        name = (_script_value(text, "PageName") or "").replace('"', '\\"', 1).strip()
        if ":" in name:
            front = name.split(":")[0].strip()
            if "." in front:
                front = ".".join(_parse_int(p) if "0" in p else p
                                 for p in front.split("."))
            front += "."
        else:
            front = ""
    offset = (_script_value(text, "InitialOffset") or "").strip()
    try:
        offset = float(offset) if offset else 0
    except ValueError:
        offset = 0
    return front.strip(), (int(offset) if offset == int(offset) else offset)


# ------------------------------------------------------------------ the book

class Book:
    """What read() found: the book's title, authors, description, and
    identifier; its contents; the pages left out of it, with why; and the
    numbering of each page's formulas, done in transform()."""

    def __init__(self, site, root, notes):
        self.site, self.root, self.notes = site, root, notes
        self.left_out = {}          # url -> why
        self.made = {}              # url -> what the page was made from
        self.generated = {}         # url -> generate kind, for the contents
        self.types = {}             # url -> type
        self.roles = {}             # url -> role
        self.titles = {}
        self.tree = []
        self.counts = {}

    def count(self, kind, n=1):
        self.counts[kind] = self.counts.get(kind, 0) + n

    def summary(self, profile):
        """What was done, for the unpack report: a note for each kind."""
        return [("site", profile + "-" + kind, f"{count} {COUNTS[kind]}")
                for kind, count in sorted(self.counts.items()) if count]

    def title_of(self, url):
        page = self.site.pages.get(url)
        if page is None:
            return ""
        found = hp.select(page.root, "h1#title")
        return hp.text_of(found[0]) if found else ""

    # -------------------------------------------------------------- reading

    def listing(self, url):
        """[(url, text)]: the pages a landing page lists under it, in its
        content: the home page's ul.mt-sortable-listings-container, a
        chapter's ul.mt-guide-listings."""
        page = self.site.pages[url]
        content = content_of(page.root)
        if content is None:
            return []
        for ul in content.iter():
            if hp.local(ul.tag) != "ul":
                continue
            if "mt-sortable-listings-container" in _classes(ul):
                out = []
                for a in ul.iter():
                    if hp.local(a.tag) == "a" and a.get("href") and \
                            "mt-sortable-listing-link" in _classes(a):
                        label = hp.select(a, "span.mt-sortable-listing-title")
                        out.append((urljoin(url, a.get("href")),
                                    hp.text_of(label[0] if label else a)))
                return out
            if "mt-guide-listings" in _classes(ul):
                out = []
                for dt in ul.iter():
                    if hp.local(dt.tag) == "dt" and \
                            "mt-listing-detailed-title" in _classes(dt):
                        a = next((x for x in dt.iter() if hp.local(x.tag) == "a"
                                  and x.get("href")), None)
                        if a is not None:
                            out.append((urljoin(url, a.get("href")), hp.text_of(a)))
                return out
        return []

    def walk(self, url, seen):
        nodes = []
        for href, text in self.listing(url):
            key = sitesource.page_key(self.site, sitesource.follow(self.site, href))
            if key is None:
                self.notes.append((self.site.pages[url].name + ".html",
                                   "libretexts-not-captured",
                                   f"{text}: {href} is listed and isn't in the archive"))
                continue
            if key in seen:
                continue
            seen.add(key)
            self.titles[key] = self.title_of(key) or text
            nodes.append({"url": key, "items": self.walk(key, seen)})
        return nodes

    def read(self, titles):
        site = self.site
        root_page = site.pages[self.root]
        self.title = self.title_of(self.root) or titles.get(self.root, "")
        self.titles[self.root] = self.title
        self.authors = []
        for e in hp.select(root_page.root, "li.mt-author-information"):
            name = hp.text_of(e)
            if name and name not in self.authors:
                self.authors.append(name)
        content = content_of(root_page.root)
        self.description = ""
        if content is not None:
            # Its paragraphs, but not the attribution in its footer, nor
            # the credit for its thumbnail (on the site, shown in listings).
            footer = [e for f in hp.select(content, "footer") for e in f.iter()]
            words = []
            for p in content.iter():
                if hp.local(p.tag) == "p" and p not in footer and not any(
                        hp.local(x.tag) in ("ul", "div") for x in p.iter()):
                    text = hp.text_of(p)
                    if not text.startswith("Thumbnail:"):
                        words.append(text)
            self.description = " ".join(w for w in words if w)
        parts = urlsplit(self.root)
        self.identifier = parts.netloc + unquote(parts.path)

        seen = {self.root}
        top = self.walk(self.root, seen)
        self.left_out[self.root] = ("the book's home page: its listing is the "
                                    "contents, and its text the description")
        tag_directory, license_report = self.data()
        self.tree = []
        for node in top:
            title = self.titles[node["url"]]
            role = MATTER.get(title)
            if role is None or not node["items"]:
                self.tree.append(node)
                continue
            self.left_out[node["url"]] = (f"the {title}'s own page, a listing of "
                                          "its pages, which are the book's "
                                          f"{role} matter")
            for child in node["items"]:
                url, name = child["url"], self.titles[child["url"]]
                self.roles[url] = role
                if name == "TitlePage":
                    self.left_out[url] = ("the title page: the run makes its own "
                                          "from the book's title and authors")
                    continue
                if name == "Table of Contents":
                    self.generated[url] = "toc"
                elif name == "Index":
                    if tag_directory is None:
                        self.left_out[url] = ("drawn by a script from the site's "
                                              "tag directory, which the archive "
                                              "doesn't hold")
                        continue
                    self.make(url, self.index_page(tag_directory))
                    self.types[url] = "index"
                elif name == "Detailed Licensing":
                    if license_report is None:
                        self.left_out[url] = ("drawn by a script from LibreTexts' "
                                              "license report, which the archive "
                                              "doesn't hold")
                        continue
                    self.make(url, self.licensing_page(license_report))
                self.tree.append(child)
        # A page the archive holds that no listing reaches, at the end.
        for url in site.pages:
            if url not in seen:
                self.titles[url] = self.title_of(url) or titles.get(url, "")
                self.tree.append({"url": url, "items": []})
                self.notes.append((site.pages[url].name + ".html",
                                   "libretexts-not-listed",
                                   "no listing names this page; it's at the "
                                   "end of the contents"))
        self.licensing_link()
        return self

    def contents(self):
        """The contents as unpacking.write_contents takes them: names for
        URLs, and each entry's role, type, or what generates it."""
        def entry(node):
            url = node["url"]
            out = {"title": self.titles.get(url, "")}
            if url in self.generated:
                out.update(generate=self.generated[url],
                           name=self.site.pages[url].name)
            else:
                out["page"] = self.site.pages[url].name
            if url in self.roles:
                out["role"] = self.roles[url]
            if url in self.types:
                out["type"] = self.types[url]
            items = [entry(n) for n in node["items"] if n["url"] not in self.left_out]
            if items:
                out["items"] = items
            return out
        return [entry(n) for n in self.tree if n["url"] not in self.left_out]

    # ----------------------------------------------------------------- data

    def resource(self, test):
        """The bytes of the first resource whose address passes test."""
        for address, key in self.site.by_url.items():
            if test(address):
                return self.site.resources[key][0]
        return None

    def data(self):
        """(tag directory HTML, license report) for the book, each None
        when the archive doesn't hold it: what the Index's script fetches
        (the Tag_directory template's contents for the book's page id)
        and Detailed Licensing's (the license report for its address)."""
        page_id = re.search(r'"pageId"\s*:\s*(\d+)', self.site.pages[self.root].text)
        tags = None
        if page_id:
            raw = self.resource(lambda a: "Tag_directory/contents" in a and re.search(
                r"[?&]pageid=%s(&|$)" % page_id.group(1), a))
            try:
                tags = json.loads(raw).get("body") if raw else None
            except (ValueError, AttributeError):
                tags = None
        book = unquote(self.root).rstrip("/")
        raw = self.resource(lambda a: "/endpoint/licensereport/" in a and unquote(
            a.split("/endpoint/licensereport/", 1)[1]).split("?")[0].rstrip("/") == book)
        try:
            report = json.loads(raw) if raw else None
        except ValueError:
            report = None
        if not isinstance(tags, str):
            tags = None
        if not (isinstance(report, dict) and isinstance(report.get("text"), dict)):
            report = None
        return tags, report

    def make(self, url, markup):
        """The page's content, made: what its script would have drawn."""
        page = self.site.pages[url]
        content = content_of(page.root)
        if content is None:
            return
        made = hp.parse("<!DOCTYPE html><html><body><section>" + markup
                        + "</section></body></html>")
        section = next(e for e in made.iter() if hp.local(e.tag) == "section")
        content[:] = list(section)
        content.text = section.text
        self.made[url] = True

    def index_page(self, body):
        """The Index as dynamicIndexMaker.js draws it: each tag the book's
        pages carry, with the pages that carry it, sorted without regard
        to case and grouped by letter. As the script does: a tag holding
        "source", "lulu", "@", or "-" is left out, as is one beginning
        with anything but a letter; the pages keep the directory's order."""
        tree = hp.parse("<!DOCTYPE html><html><body>" + body + "</body></html>")
        terms = []
        for li in tree.iter():
            if hp.local(li.tag) != "li" or not any(
                    c.startswith("mt-tag-name-") for c in _classes(li)):
                continue
            name = next((hp.text_of(h) for h in li.iter() if hp.local(h.tag) == "h5"), "")
            if not name or any(x in name.lower() for x in ("source", "lulu", "@", "-")):
                continue
            pages = [(a.get("href"), a.get("title") or hp.text_of(a))
                     for a in li.iter() if hp.local(a.tag) == "a" and a.get("href")]
            terms.append((name, pages))
        terms.sort(key=lambda t: t[0].lower())
        esc = html_module.escape
        letters, blocks = [], []
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            mine = [t for t in terms if t[0][:1].upper() == letter]
            if not mine:
                continue
            letters.append(f'<a href="#index-{letter}">{letter}</a>')
            items = "".join(
                "<li>%s: %s</li>" % (esc(name), ", ".join(
                    f'<a href="{esc(href)}">{esc(title)}</a>' for href, title in pages))
                for name, pages in mine)
            blocks.append(f'<h2 id="index-{letter}">{letter}</h2><ul>{items}</ul>')
            self.count("index-terms", len(mine))
        return "<p>" + " \u2022 ".join(letters) + "</p>" + "".join(blocks)

    def licensing_page(self, report):
        """Detailed Licensing as dynamicLicensing.js draws it from the
        license report: an overview, then every page and its license."""
        esc = html_module.escape
        text, meta = report["text"], report.get("meta") or {}

        def link(href, label):
            href = href or ""
            return f'<a href="{esc(href)}">{label}</a>' if href and href != "#" else label

        out = ["<h2>Overview</h2>",
               "<p><strong>Title:</strong> %s</p>" % link(text.get("url"), esc(str(text.get("title", "")))),
               "<p><strong>Webpages:</strong> %s</p>" % esc(str(text.get("totalPages", "")))]
        restrictions = [{"noncommercial": "Noncommercial", "noderivatives": "No Derivatives",
                         "fairuse": "Fair Use"}.get(r) for r in meta.get("specialRestrictions") or []]
        restrictions = [r for r in restrictions if r]
        if restrictions:
            out.append("<p><strong>Applicable Restrictions:</strong> %s</p>"
                       % esc(", ".join(restrictions)))
        out.append("<p><strong>All licenses found:</strong></p><ul>")
        for lic in meta.get("licenses") or []:
            label = esc(str(lic.get("label", ""))) + (" " + esc(str(lic["version"]))
                                                      if lic.get("version") else "")
            count = lic.get("count", 0)
            out.append("<li>%s: %s%% (%s %s)</li>" % (
                link(lic.get("link"), label), esc(str(lic.get("percent", ""))),
                esc(str(count)), "pages" if count != 1 else "page"))
        out.append("</ul><h2>By Page</h2>")

        def entry(node):
            item = link(node.get("url"), esc(str(node.get("title", ""))))
            lic = node.get("license")
            if lic:
                label = "<em>%s %s</em>" % (esc(str(lic.get("label", ""))),
                                            esc(str(lic.get("version") or "")))
                item += " - " + link(lic.get("link"), label.replace(" </em>", "</em>"))
            children = node.get("children") or []
            if children:
                item += "<ul>" + "".join(entry(c) for c in children) + "</ul>"
            return "<li>" + item + "</li>"
        out.append("<ul>" + entry(text) + "</ul>")
        return "".join(out)

    def licensing_link(self):
        """The Licensing page's pointer to Detailed Licensing, which its
        script makes a link: made one here, when the book has the page."""
        target = next((u for u, t in self.titles.items() if t == "Detailed Licensing"
                       and u not in self.left_out), None)
        if target is None:
            return
        for url, page in self.site.pages.items():
            for span in hp.select(page.root, "span#detailed_link"):
                span.tag = "a"
                span.attrib.clear()
                span.set("href", target)

    # ------------------------------------------------------------ each page

    def transform(self, page, content):
        """Everything above that happens on one page, in place, on its
        content after the unpacker has taken the chrome out and written
        its formulas as <script type="math/tex">."""
        title = self.titles.get(page.url) or ""
        heading = content.makeelement("h1", {})
        heading.text = title
        heading.tail = content.text
        content.text = None
        content.insert(0, heading)
        for element in content.iter():
            for name in NOISE:
                if name in element.attrib:
                    del element.attrib[name]
            # The site's boxes (an example, an exercise, a note, an aside
            # it calls emphasis) are shaded by its stylesheet; class box
            # draws one around each in an HTML target and an EPUB. Each is
            # a <section>, which the run opens up as it does every
            # generator's (html-source.lua), so it's a <div>.
            classes = _classes(element)
            if hp.local(element.tag) in ("section", "div") and any(
                    c.startswith("box-") and c != "box-legend" for c in classes) \
                    and "box" not in classes:
                element.tag = "div"
                element.set("class", " ".join(classes + ["box"]))
                self.count("boxes")
        # The content's footer holds the page's attribution, "This page
        # titled ... is shared under ...", which is kept, as LibreTexts'
        # own PDFs keep it; Pandoc's reader has no footer and keeps a
        # footer's contents as they are, so it's the contents.
        parent_of = hp.parents(content)
        for footer in hp.select(content, "footer.mt-content-footer"):
            _unwrap(footer, parent_of)
        self.editor_marks(content, hp.parents(content))
        front, offset = numbering(page.text)
        self.page_index(content, front)
        for element in content.iter():
            if hp.local(element.tag) == "script" and "%" in (element.text or ""):
                element.text = text_percent(element.text)
            if hp.local(element.tag) == "script" and "\\\\" in (element.text or ""):
                new = bare_breaks(element.text)
                if new != element.text:
                    element.text = new
                    self.count("line-breaks")
        self.chemistry(page, content)
        labels = self.number(page, content, front, offset)
        self.references(page, content, labels)

    def editor_marks(self, content, parent_of):
        """CKEditor's magic line, the red mark its editor draws between two
        blocks for adding a paragraph there, which an edit saved into the
        first paragraph of Instrumental Analysis's 11.4: spans marked
        contenteditable="false", the inner one's background the editor's
        icon on the site's server and its text "↵", which every target
        showed, and which the EPUB fetched from the web (epubcheck's
        RSC-006). Each goes, and the paragraph and spans it leaves empty."""
        marks = [e for e in content.iter() if isinstance(e.tag, str)
                 and e.get("contenteditable") == "false"
                 and any("magicline" in (d.get("style") or "") for d in e.iter()
                         if isinstance(d.tag, str))]

        def inside_another(element):
            up = parent_of.get(element)
            while up is not None:
                if any(m is up for m in marks):
                    return True
                up = parent_of.get(up)
            return False
        for mark in [m for m in marks if not inside_another(m)]:
            above = parent_of.get(mark)
            hp.drop(mark, parent_of)
            self.count("editor-marks")
            while above is not None and hp.local(above.tag) in ("span", "p") \
                    and len(above) == 0 and not (above.text or "").strip():
                next_up = parent_of.get(above)
                hp.drop(above, parent_of)
                above = next_up

    def page_index(self, content, front):
        """\\PageIndex{n} as the page's number and n: a formula that is
        nothing else becomes the number as text, and in alt text, where
        MathJax never looks, the delimited form is expanded too."""
        def value(arg):
            return front + "".join(arg.split())
        parent_of = hp.parents(content)
        for element in list(content.iter()):
            if not isinstance(element.tag, str):
                continue
            for name in ("alt", "title"):
                text = element.get(name)
                if text and "\\PageIndex" in text:
                    new = DELIMITED_PAGE_INDEX.sub(lambda m: value(m.group(1)), text)
                    element.set(name, PAGE_INDEX.sub(lambda m: value(m.group(1)), new))
                    self.count("page-index-attribute")
            if hp.local(element.tag) != "script" or "\\PageIndex" not in (element.text or ""):
                continue
            whole = ONLY_PAGE_INDEX.fullmatch(element.text)
            if whole:
                _replace_with_text(element, value(whole.group(1)), parent_of)
                self.count("page-index")
            else:
                element.text = PAGE_INDEX.sub(lambda m: value(m.group(1)), element.text)
                self.count("page-index")

    def chemistry(self, page, content):
        for element in content.iter():
            if hp.local(element.tag) == "script" and "\\ce" in (element.text or ""):
                found = len(mhchem.CE.findall(element.text))
                element.text, unread = mhchem.rewrite(element.text)
                self.count("mhchem", found - len(unread))
                for argument in unread:
                    self.notes.append((page.name + ".html", "mhchem-unread",
                                       "\\ce{%s} is left as it was: mhchem.py doesn't "
                                       "read it" % argument))

    def number(self, page, content, front, offset):
        """Each display formula numbered as MathJax numbers it with the
        pages' tags: "all": {label: number}, the number "" for a label
        on a formula with none."""
        counter = [0]
        labels = {}

        def auto():
            counter[0] += 1
            n = counter[0] + offset
            return front + str(n)

        parent_of = hp.parents(content)
        for script in [e for e in content.iter() if hp.local(e.tag) == "script"
                       and "mode=display" in (e.get("type") or "")]:
            tex = script.text or ""
            edits, keys, shown = [], [], []
            found = TAGGABLE.search(tex)
            rows = latexsource.display_rows(tex, found.start()) if found else None
            if found and rows:
                name, starred, row_spans, stop = rows
                if not starred:
                    # Numbered by \tag from here on, starred, so LaTeX's
                    # own count never runs.
                    ends = list(re.finditer(r"\\end\s*\{%s\}" % name, tex[:stop]))
                    edits.append((found.start(), found.end(), "\\begin{%s*}" % name))
                    if ends:
                        edits.append((ends[-1].start(), ends[-1].end(), "\\end{%s*}" % name))
                for start, end in row_spans:
                    self.row(tex, start, end, starred, auto, edits, keys, labels, shown)
            elif found:
                self.notes.append((page.name + ".html", "libretexts-unnumbered",
                                   "a formula's %s environment isn't read; it has "
                                   "no number" % found.group(1)))
            else:
                self.row(tex, 0, len(tex), False, auto, edits, keys, labels, shown)
            for start, stop, new in sorted(edits, reverse=True):
                tex = tex[:start] + new + tex[stop:]
            tex = STRIP.sub("", tex)
            if not keys and not any(s for s in shown):
                script.text = tex
                continue
            self.count("numbered-formulas")
            _replace(script, _equation(content, tex, keys, shown), parent_of)
        return labels

    def row(self, tex, start, stop, starred, auto, edits, keys, labels, shown):
        commands = latexsource.row_commands(tex, start, stop)
        names = [c[0] for c in commands]
        tag = next((c for c in commands if c[0].startswith("tag")), None)
        if tag:
            number = tag[1]
            shown.append(number if tag[0] == "tag*" else "(%s)" % number)
        elif starred or "nonumber" in names or "notag" in names:
            number = None
            shown.append(None)
        else:
            number = auto()
            shown.append("(%s)" % number)
            edits.append((stop, stop, " \\tag{%s}" % number))
        for command, argument, cstart, cstop in commands:
            if command == "label":
                labels[argument] = number or ""
                keys.append(argument)
                edits.append((cstart, cstop, ""))
        return number

    def references(self, page, content, labels):
        """\\ref{key} and \\eqref{key} written in the text, which MathJax
        resolves on the page (processRefs), as links to the formula: its
        number, and for \\eqref the number in parentheses. One to a label
        the page doesn't number is left as it was, and reported."""
        def make(m):
            key = m.group(2)
            number = labels.get(key)
            if not number:
                self.notes.append((page.name + ".html", "libretexts-reference",
                                   f"{m.group(0)}: no numbered formula on the page "
                                   "has this label; left as it was"))
                return None
            link = content.makeelement("a", {"href": "#" + anchor(key)})
            link.text = "(%s)" % number if m.group(1) else number
            self.count("references")
            return link
        _replace_in_text(content, REF, make)


TEXT_MODE = re.compile(r"\\(?:text|textrm|textit|textbf|textsf|texttt|textup|"
                       r"textnormal|mbox)\s*\{")


def text_percent(tex):
    """A % inside \\text{...}, which MathJax takes as itself (the
    argument is read as text, braces counted, before anything else) and
    LaTeX and texmath as the start of a comment, escaped: \\%. On
    Instrumental Analysis, \\text{confidence interval (%)} \\nonumber was
    numbered for want of it."""
    out, at = [], 0
    for m in TEXT_MODE.finditer(tex):
        if m.start() < at:
            continue
        close = latexsource.matching_brace(tex, m.end() - 1)
        if close < 0:
            continue
        inner = re.sub(r"(?<!\\)%", r"\\%", tex[m.end():close - 1])
        out.append(tex[at:m.end()] + inner + "}")
        at = close
    out.append(tex[at:])
    return "".join(out)


def bare_breaks(tex):
    """The formula with a \\\\ outside any group and environment, which
    MathJax 4 sets as a line break and texmath and LaTeX refuse, set as
    lines in a gathered environment, as it shows; otherwise as it was."""
    depth, envs, i, n = 0, 0, 0, len(tex)
    while i < n:
        if tex.startswith("\\\\", i):
            if depth == 0 and envs == 0:
                return "\\begin{gathered}" + tex + "\\end{gathered}"
            i += 2
            continue
        edge = re.compile(r"\\(begin|end)\s*\{[^{}]*\}").match(tex, i)
        if edge:
            envs += 1 if edge.group(1) == "begin" else -1
            i = edge.end()
            continue
        if tex[i] == "\\":
            i += 2
            continue
        depth += 1 if tex[i] == "{" else -1 if tex[i] == "}" else 0
        i += 1
    return tex


def anchor(key):
    """A label's anchor: MathJax's mjx-eqn:key, as an id that needs no
    escaping in a link."""
    return "eq-" + "-".join(key.replace("{}", "").split())


def _equation(content, tex, keys, shown):
    """A numbered display formula as a LaTeX book's is read: a span of
    class equation holding its labels' anchors, the formula, and its
    numbers, a row's under the row before's."""
    span = content.makeelement("span", {"class": "equation"})
    for key in keys:
        span.append(content.makeelement("span", {"id": anchor(key)}))
    math = content.makeelement("math", {"display": "block"})
    semantics = content.makeelement("semantics", {})
    annotation = content.makeelement("annotation", {"encoding": "application/x-tex"})
    annotation.text = tex
    semantics.append(annotation)
    math.append(semantics)
    span.append(math)
    while shown and shown[-1] is None:
        shown.pop()
    if shown:
        number = content.makeelement("span", {"class": "equation-number"})
        last = None
        for index, text in enumerate(shown):
            if index:
                last = content.makeelement("br", {})
                number.append(last)
            if text:
                if last is None:
                    number.text = (number.text or "") + text
                else:
                    last.tail = (last.tail or "") + text
        span.append(number)
    return span


def _replace(element, new, parent_of):
    parent = parent_of[element]
    index = list(parent).index(element)
    new.tail = element.tail
    parent.remove(element)
    parent.insert(index, new)
    parent_of[new] = parent


def _unwrap(element, parent_of):
    """The element's contents in its place."""
    parent = parent_of.get(element)
    if parent is None:
        return
    index = list(parent).index(element)
    children = list(element)
    lead = element.text or ""
    if index:
        before = parent[index - 1]
        before.tail = (before.tail or "") + lead
    else:
        parent.text = (parent.text or "") + lead
    parent.remove(element)
    for offset, child in enumerate(children):
        parent.insert(index + offset, child)
        parent_of[child] = parent
    tail = element.tail or ""
    if children:
        children[-1].tail = (children[-1].tail or "") + tail
    elif index:
        parent[index - 1].tail = (parent[index - 1].tail or "") + tail
    else:
        parent.text = (parent.text or "") + tail


def _replace_with_text(element, text, parent_of):
    parent = parent_of[element]
    index = list(parent).index(element)
    joined = text + (element.tail or "")
    parent.remove(element)
    if index:
        before = parent[index - 1]
        before.tail = (before.tail or "") + joined
    else:
        parent.text = (parent.text or "") + joined


def _replace_in_text(root, pattern, make):
    """Each match of pattern in the text under root (outside code and
    scripts) replaced by the element make returns, or left when it
    returns None."""
    skip = sitesource.NO_MATH_IN

    def split(text):
        parts, last = [], 0
        for m in pattern.finditer(text):
            new = make(m)
            if new is None:
                continue
            parts.append((text[last:m.start()], new))
            last = m.end()
        return parts, text[last:]

    def walk(element):
        if hp.local(element.tag) in skip:
            return
        for child in list(element):
            walk(child)
        children = []
        if element.text:
            parts, rest = split(element.text)
            if parts:
                element.text = parts[0][0]
                for index, (before, new) in enumerate(parts):
                    if index:
                        children[-1].tail = before
                    children.append(new)
                children[-1].tail = rest
        for child in list(element):
            children.append(child)
            if child.tail:
                parts, rest = split(child.tail)
                if parts:
                    child.tail = parts[0][0]
                    for index, (before, new) in enumerate(parts):
                        if index:
                            children[-1].tail = before
                        children.append(new)
                    children[-1].tail = rest
        if children:
            element[:] = children
    walk(root)


# ------------------------------------------------------------------ entry

def root_page(site):
    """The book's home: the page most pages are under, when it holds at
    least half of them; None otherwise."""
    paths = {url: urlsplit(url).path.rstrip("/") for url in site.pages}
    best = None
    for url, path in paths.items():
        under = sum(1 for p in paths.values() if p.startswith(path + "/"))
        if under and (best is None or under > best[0]
                      or (under == best[0] and len(path) < len(paths[best[1]]))):
            best = (under, url)
    if best and best[0] * 2 >= len(paths) - 1:
        return best[1]
    return None


def read(site, titles, notes):
    """The Book the archive's pages make, or None when they aren't one
    book under one home page, and the generic order applies."""
    root = root_page(site)
    if root is None:
        notes.append(("site", "libretexts-no-book",
                      "no page holds half the others under it; the order is "
                      "read from the pages' menus instead"))
        return None
    return Book(site, root, notes).read(titles)
