"""
cnx.exercises -- the exercises a book keeps in OpenStax's exercise bank,
put in where its pages embed them, as OpenStax's assembly puts them in.

A page embeds an exercise as a link with nothing in it,

    <link class="os-embed" url="#exercise/MBT_Ch1_Sec1_KC1"/>

naming it by its nickname ("#exercise/") or by a tag ("#ost/api/ex/").
The bank's public API (https://exercises.openstax.org/api/exercises)
gives each as JSON: its questions, their answer choices, and, for a book
whose solutions are public, which choice is right, why, and a worked
solution. A book whose solutions aren't public gets its questions
without them; a token the bank's owners issue (the environment variable
OPENSTAX_EXERCISES_TOKEN) brings them.

Each exercise is fetched once and kept, as the API gave it, in a cache
directory (by default ~/.cache/textbookimprover/cnx-exercises), so a
book is fetched once and unpacked after without the network, and the
cache can be copied to a machine that has none. An exercise that can't
be had is a sentence saying so where it would stand, and a line in the
report.

An exercise the cache has isn't asked for again, so a change OpenStax
makes to it in the bank isn't seen, unless the bank is asked to check
(update, unpack-cnx.py's --update-exercises): then each exercise the book
embeds that the cache has is fetched again and compared with the cache's
copy, and the bank's is kept in its place where it's newer, a later
version of an exercise the two share by number, or other exercises; at
the same versions the cache's copy stays, whatever else the answers
differ in. Nothing short of asking says whether it's changed: the cache
keeps the API's answer, which carries each exercise's version and the
time it was published, and not the reply's headers, and a file's own
time in the cache is when it was fetched. A picture is fetched by its
address and kept, and isn't fetched again, which is right for a picture
at an S3 key, the SHA-256 of its bytes (all 283 such keys among the 26
books' exercises, fetched on 2026-11-03), and presumed for one at the
bank's own address, which names an upload.

What's written in the link's place is the shape OpenStax's assembly
writes, which the recipes' directions read:

    div data-type="injected-exercise"
      div data-type="exercise-context"     (when the exercise refers to
                                            a figure or table of the book)
      div data-type="exercise-stimulus"
      div data-type="exercise-question" id="auto_<page>_<question id>"
        div data-type="question-stimulus"
        div data-type="question-stem"
        ol data-type="question-answers" type="a"
          li data-type="question-answer" data-correctness="1.0"
            div data-type="answer-content"
            div data-type="answer-feedback"
        div data-type="question-solution" data-solution-type="detailed"

An exercise's text is HTML; it's read as HTML and copied in element by
element, an attribute whose name XML doesn't allow left out and
reported. Its formulas are TeX (a span or div with data-math), made
MathML by Pandoc's TeX reader; one Pandoc can't read is read again with
the forms MathJax takes and Pandoc doesn't rewritten in LaTeX's
(cnx.texforms), and one it can't read either way left as its TeX and
reported. Its pictures are fetched into the cache and copied to
media/exercises/.

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

import concurrent.futures
import hashlib
import http.client
import json
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from lxml import etree
from lxml import html as lxml_html

from epubsource import sniff
import pandocversion
import pandocrun

from .cnxml import E, append_text, code_lines
from .mathml import MATHML
from .texforms import latex_forms, mathjax_rows

HOST = "exercises.openstax.org"
TOKEN_VARIABLE = "OPENSTAX_EXERCISES_TOKEN"
# How a link names its exercise, and what the API is asked for.
PREFIXES = (("#exercise/", "nickname"), ("#ost/api/ex/", "tag"))
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
# What a fetch can fail with: the network's errors (URLError is an
# OSError), an answer that isn't JSON or UTF-8 (ValueError), and a reply cut
# off or garbled (http.client's IncompleteRead and BadStatusLine, which are
# neither).
FETCH_ERRORS = (urllib.error.URLError, OSError, ValueError, http.client.HTTPException)
# The extension a picture's bytes call for, as epubsource.sniff names them.
FORMATS = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
           "image/webp": ".webp", "image/svg+xml": ".svg"}


def default_cache():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache")
    return os.path.join(base, "textbookimprover", "cnx-exercises")


def embedded(url):
    """(kind, code) for a link that embeds an exercise, else None."""
    for prefix, kind in PREFIXES:
        if url.startswith(prefix) and len(url) > len(prefix):
            return kind, url[len(prefix):]
    return None


def _items(data):
    items = data.get("items") if isinstance(data, dict) else None
    return [item for item in items or [] if isinstance(item, dict)]


def _why(exc):
    """What an error says, or its kind where it says nothing."""
    return str(exc) or type(exc).__name__


def versions(data):
    """An answer's exercises, as {number: version}."""
    return {item.get("number"): item.get("version") or 0 for item in _items(data)}


def uids(data):
    """An answer's exercises as the bank names each version, number@version
    (84@9), or "none"."""
    found = [str(item.get("uid") or f"{item.get('number')}@{item.get('version')}")
             for item in _items(data)]
    return ", ".join(found) or "none"


class Bank:
    """The exercise bank, through its cache. With offline set, only the
    cache is read; with update, each exercise is asked of the bank again
    (refresh), once."""

    def __init__(self, cache=None, offline=False, token=None, host=HOST,
                 timeout=30, update=False):
        self.cache = cache or default_cache()
        self.offline = offline
        self.update = update and not offline
        self.token = token if token is not None else os.environ.get(
            TOKEN_VARIABLE) or None
        self.host = host
        self.timeout = timeout
        # A response made with a token holds what one made without
        # doesn't, so the two are kept apart.
        self.root = os.path.join(self.cache,
                                 "with-token" if self.token else "public")
        self.failures = {}      # (kind, code) -> why it couldn't be had
        # With update: each (kind, code) a book embeds, asked again or, not
        # in the cache, fetched as on a first unpacking; those whose copy in
        # the cache the bank's replaced, as (the cache's uids, the bank's);
        # those the bank had at the cache's versions; those whose copy in
        # the cache was kept, and why; and, among them, those the bank
        # couldn't be asked about. Sets and dicts, which threads add to
        # safely.
        self.asked = set()
        self.updated = {}
        self.unchanged = set()
        self.not_updated = {}
        self.unreachable = set()

    def url(self, kind, code):
        query = urllib.parse.quote(f"{kind}:{code}", safe=":")
        return f"https://{self.host}/api/exercises?q={query}"

    def path(self, kind, code):
        name = urllib.parse.quote(code, safe="") + ".json"
        return os.path.join(self.root, kind, name)

    def cached(self, kind, code):
        path = self.path(kind, code)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def get(self, kind, code):
        """The API's answer for one exercise, from the cache or fetched,
        or None (the reason kept in failures). With update, the bank is
        asked first (refresh)."""
        if self.update and (kind, code) not in self.asked:
            self.refresh(kind, code)
        data = self.cached(kind, code)
        if data is not None:
            return data
        if self.offline:
            self.failures[(kind, code)] = "not in the cache, and offline"
            return None
        try:
            data = json.loads(self._fetch(self.url(kind, code)).decode(
                "utf-8"))
        except FETCH_ERRORS as exc:
            self.failures[(kind, code)] = f"couldn't be fetched: {_why(exc)}"
            return None
        self._write(kind, code, data)
        self.failures.pop((kind, code), None)       # a failure asking before
        return data

    def refresh(self, kind, code):
        """Ask the bank again for an exercise the cache has, and keep its
        answer in the cache's copy's place where it's newer: a later version
        of an exercise the two share by number, none earlier, or other
        exercises. At the same versions the cache's copy stays (unchanged),
        whatever else the answers differ in, since a version the bank has
        published doesn't change. The cache's copy stays too where the bank
        has none now, or an earlier version, or can't be asked (not_updated,
        with why; unreachable). One the cache hasn't is left to get, which
        fetches it as a first unpacking does."""
        self.asked.add((kind, code))
        old = self.cached(kind, code)
        if old is None:
            return
        try:
            new = json.loads(self._fetch(self.url(kind, code)).decode("utf-8"))
        except FETCH_ERRORS as exc:
            self.not_updated[(kind, code)] = f"the bank couldn't be asked: {_why(exc)}"
            self.unreachable.add((kind, code))
            return
        if new == old:
            self.unchanged.add((kind, code))
            return
        was, now = versions(old), versions(new)
        if not now:
            if not was:                 # none in the cache either
                self.unchanged.add((kind, code))
            else:
                self.not_updated[(kind, code)] = (
                    f"the bank has none now, where the cache has {uids(old)}")
            return
        shared = now.keys() & was.keys()
        if any(now[number] < was[number] for number in shared):
            self.not_updated[(kind, code)] = (
                f"the bank's is an earlier version ({uids(new)}) than the "
                f"cache's ({uids(old)})")
            return
        if now.keys() == was.keys() and all(now[number] == was[number] for number in shared):
            self.unchanged.add((kind, code))
            return
        self._write(kind, code, new)
        self.updated[(kind, code)] = (uids(old), uids(new))

    def prefetch(self, wanted, workers=8):
        """Fetch every (kind, code) not yet cached, or with update every
        one, several at once."""
        todo = [w for w in dict.fromkeys(wanted)
                if self.update or not os.path.exists(self.path(*w))]
        if not todo or self.offline:
            return 0
        with concurrent.futures.ThreadPoolExecutor(workers) as pool:
            list(pool.map(lambda w: self.get(*w), todo))
        return len(todo)

    def image(self, url):
        """A picture an exercise shows, from the cache or fetched: its
        path, or None."""
        ext = os.path.splitext(urllib.parse.urlsplit(url).path)[1].lower()
        if ext not in IMAGE_TYPES:
            ext = ".png"
        name = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] + ext
        path = os.path.join(self.cache, "images", name)
        if os.path.exists(path):
            return path
        if self.offline:
            return None
        try:
            self._keep(path, self._fetch(url, auth=False))
        except FETCH_ERRORS:
            return None
        return path

    def _fetch(self, url, auth=True):
        headers = {"User-Agent": "TextbookImprover unpack-cnx.py",
                   "Accept": "application/json"}
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=self.timeout) as reply:
            return reply.read()

    def _write(self, kind, code, data):
        self._keep(self.path(kind, code), json.dumps(
            data, ensure_ascii=False, indent=1).encode("utf-8"))

    @staticmethod
    def _keep(path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)


# HTML from the bank, into the tree -------------------------------------

def html_children(text, dropped=None):
    """An HTML fragment as (leading text, [elements]) in the tree's own
    elements: what the bank writes copied element by element, since
    lxml's HTML elements don't mix with the rest. What XML doesn't allow
    is said in dropped: an attribute whose name it doesn't, left out; an
    element whose name it doesn't, its content kept in a span; and a
    character it doesn't (a control character, half a surrogate pair),
    left out."""
    text = _xml_text(text, dropped)
    if not text or not text.strip():
        return (text or "", [])
    try:
        parts = lxml_html.fragments_fromstring(text)
    except (etree.ParserError, ValueError):
        return (text, [])
    lead = ""
    out = []
    for part in parts:
        if isinstance(part, str):
            lead += part
        else:
            out.append(_copy(part, dropped))
    return _xml_text(lead, dropped), out


# What XML doesn't allow in text, which lxml's tree refuses: a control
# character but a tab or a line's end, half a surrogate pair, U+FFFE, and
# U+FFFF. HTML's parser keeps one, written as it is or as a character
# reference (&#1;).
_NOT_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def _xml_text(text, dropped=None):
    """text without the characters XML doesn't allow, each said in
    dropped."""
    if not text or not _NOT_XML.search(text):
        return text
    if dropped is not None:
        dropped.extend(f"a character U+{ord(c):04X}, left out"
                       for c in _NOT_XML.findall(text))
    return _NOT_XML.sub("", text)


def _copy(element, dropped=None):
    """element in the tree's own elements. A name lxml's tree refuses, as
    XML does, comes of a tag the bank's HTML leaves open, which HTML's
    parser reads on: "c<", an attribute's name, from '<code
    class="python" c< code data-lang="python">' in Introduction to
    Python Programming's CPL-ch05-m02-p03, which stopped the book's
    unpacking; an element's, "b<i" from '<b<i>'. The attribute is left
    out, the element a span, its content kept; each said in dropped."""
    tag = element.tag if isinstance(element.tag, str) else None
    if tag is None:                      # a comment
        holder = E("span")
        holder.tail = _xml_text(element.tail, dropped)
        return holder
    try:
        out = E(tag.lower())
    except ValueError:
        out = E("span")
        if dropped is not None:
            dropped.append(f"an element named {tag!r}, its content kept")
    for name, value in element.attrib.items():
        if not isinstance(name, str) or ":" in name:
            continue
        try:
            out.set(name, _xml_text(value, dropped))
        except ValueError:
            if dropped is not None:
                dropped.append(f"an attribute named {name!r}, left out")
    out.text = _xml_text(element.text, dropped)
    for child in element:
        if isinstance(child.tag, str):
            out.append(_copy(child, dropped))
        else:
            append_text(out, _xml_text(child.tail, dropped))
    out.tail = _xml_text(element.tail, dropped)
    return out


def fill(holder, html, dropped=None):
    """holder's content: the HTML fragment, as elements."""
    lead, children = html_children(html, dropped)
    append_text(holder, lead)
    for child in children:
        holder.append(child)
    return holder


# One exercise ----------------------------------------------------------

def render(item, page_key, link_class, url, context=None, dropped=None):
    """The bank's item as OpenStax's assembly writes it; an attribute's
    name XML doesn't allow, left out, added to dropped."""
    out = E("div", {"data-type": "injected-exercise",
                    "class": link_class or None,
                    "data-injected-from-nickname": item.get("nickname"),
                    "data-injected-from-version": str(item.get("version",
                                                               "")),
                    "data-injected-from-url": url,
                    "data-tags": " ".join(item.get("tags") or []),
                    "data-is-vocab": str(bool(item.get("is_vocab"))).lower()})
    if context is not None:
        holder = E("div", {"data-type": "exercise-context"})
        holder.append(E("a", {"class": "autogenerated-content",
                              "href": f"#{context}"}))
        out.append(holder)
    if (item.get("stimulus_html") or "").strip():
        out.append(fill(E("div", {"data-type": "exercise-stimulus"}),
                        item["stimulus_html"], dropped))
    for question in item.get("questions") or []:
        q = E("div", {"data-type": "exercise-question",
                      "data-is-answer-order-important": str(bool(
                          question.get("is_answer_order_important"))).lower(),
                      "data-formats": " ".join(question.get("formats")
                                               or []),
                      "id": f"auto_{page_key}_{question.get('id')}"})
        if (question.get("stimulus_html") or "").strip():
            q.append(fill(E("div", {"data-type": "question-stimulus"}),
                          question["stimulus_html"], dropped))
        q.append(fill(E("div", {"data-type": "question-stem"}),
                      question.get("stem_html") or "", dropped))
        answers = question.get("answers") or []
        if answers:
            ol = E("ol", {"data-type": "question-answers", "type": "a"})
            for answer in answers:
                li = E("li", {"data-type": "question-answer",
                              "data-correctness": answer.get("correctness")})
                li.append(fill(E("div", {"data-type": "answer-content"}),
                               answer.get("content_html") or "", dropped))
                if (answer.get("feedback_html") or "").strip():
                    li.append(fill(E("div", {"data-type": "answer-feedback"}),
                                   answer["feedback_html"], dropped))
                ol.append(li)
            q.append(ol)
        for solution in question.get("collaborator_solutions") or []:
            holder = E("div", {
                "data-type": "question-solution",
                "data-solution-source": "collaborator",
                "data-solution-type": solution.get("solution_type")})
            # The space OpenStax's template leaves before a solution,
            # which parts the letter of the right choice from it.
            holder.text = " "
            q.append(fill(holder, solution.get("content_html") or "", dropped))
        out.append(q)
    return out


def context_of(item, page, pages_by_uuid):
    """The element an exercise refers to (its tags name a module and an
    element in it), as an id in the assembled book, or None."""
    modules, feature = [], ""
    for tag in item.get("tags") or []:
        if tag.startswith("context-cnxmod:"):
            modules.append(tag.split(":", 1)[1])
        elif tag.startswith("context-cnxfeature:"):
            feature = tag.split(":", 1)[1]
    if not feature:
        return None
    own = page.get("data-module")
    candidates = [own] + [pages_by_uuid[m] for m in modules
                          if m in pages_by_uuid]
    for module in candidates:
        if not module:
            continue
        # The id as an XPath variable, so that a quote in a tag doesn't end
        # the expression; one XML can't hold names nothing.
        try:
            found = page.getroottree().xpath("//*[@id=$id]",
                                             id=f"{module}__{feature}")
        except (ValueError, etree.XPathError):
            return None
        if found:
            return f"{module}__{feature}"
    return None


def missing(kind, code, why):
    """What stands where an exercise couldn't be put: a paragraph that
    says which, and where it's kept."""
    p = E("p", {"data-type": "missing-exercise"})
    p.text = (f"Exercise {code} is in OpenStax's exercise bank "
              f"({kind} {code}) and couldn't be put in here: {why}.")
    return p


def embed_links(body):
    """The links an assembled book embeds an exercise with, in order."""
    return [a for a in body.iter("a")
            if a.get("data-type") == "embed"
            and embedded(a.get("data-embed") or "")]


def wanted(body):
    """(kind, code) for each exercise an assembled book embeds, in order,
    once each."""
    return list(dict.fromkeys(embedded(a.get("data-embed")) for a in embed_links(body)))


def inject(asm, body, bank):
    """Every embedded exercise of the assembled book, put in. Returns
    (injected, missing, formulas read once rewritten in LaTeX's forms,
    the pictures the bank marks decorative for report_decorative)."""
    links = embed_links(body)
    bank.prefetch(wanted(body))
    pages_by_uuid = {}
    for module_id, module in asm.modules.items():
        if getattr(module, "uuid", None):
            pages_by_uuid[module.uuid] = module_id
    done = 0
    lost = 0
    formulas = []
    decorative = {}
    for link in links:
        url = link.get("data-embed")
        kind, code = embedded(url)
        page = next((p for p in link.iterancestors("div")
                     if p.get("data-type") == "page"), None)
        data = bank.get(kind, code)
        items = (data or {}).get("items") or []
        where = page.get("data-module") if page is not None else ""
        if (kind, code) in bank.updated:
            was, now = bank.updated[(kind, code)]
            asm.report(where, "exercise-updated",
                       f"{url}: the bank's {now} kept in place of the cache's {was}")
        elif (kind, code) in bank.not_updated:
            asm.report(where, "exercise-not-updated",
                       f"{url}: {bank.not_updated[(kind, code)]}; the cache's copy is used")
        if not items:
            why = bank.failures.get((kind, code)) or "the bank has none"
            asm.report(page.get("data-module") if page is not None else "",
                       "exercise-missing", f"{url}: {why}")
            new = missing(kind, code, why)
            lost += 1
        else:
            item = items[0]
            page_key = page.get("data-module") if page is not None else ""
            context = context_of(item, page, pages_by_uuid) \
                if page is not None else None
            dropped = []
            try:
                new = render(item, page_key,
                             _without(link.get("class"), "autogenerated-content"),
                             bank.url(kind, code), context, dropped)
            except ValueError as exc:
                # Something of the bank's XML can't hold, which no field of
                # the cache has: one exercise doesn't stop the book.
                why = "its item has what XML can't hold"
                asm.report(page_key, "exercise-html", f"{url}: {why} ({exc})")
                _replace_link(link, missing(kind, code, why))
                lost += 1
                continue
            if dropped:
                asm.report(page_key, "exercise-html",
                           f"{code}: its HTML has what XML doesn't allow (a "
                           "tag left open, a stray character): "
                           + "; ".join(dict.fromkeys(dropped)))
            _code_blocks(new)
            _pictures(asm, new, bank, code, page_key, decorative)
            _formulas(asm, new, page_key, code, formulas)
            if not item.get("solutions_are_public", True) and not bank.token:
                asm.report(page_key, "exercise-solutions-not-public",
                           f"{url}: the bank gives its question, not its "
                           "answer")
            done += 1
        _replace_link(link, new)
    rewritten = tex_to_mathml(asm, formulas)
    return done, lost, rewritten, decorative


def _without(classes, name):
    kept = [c for c in (classes or "").split() if c != name]
    return " ".join(kept) or None


def _replace_link(link, new):
    """The exercise where the link was, with the id the link carried (an
    exercise's, cnxml.py gives it), which OpenStax's assembly drops. A
    link alone in its paragraph takes the paragraph's place, so no
    paragraph holds the exercise's blocks."""
    if link.get("id") and not new.get("id"):
        new.set("id", link.get("id"))
    parent = link.getparent()
    alone = (parent.tag == "p" and len(parent) == 1
             and not (parent.text or "").strip()
             and not (link.tail or "").strip())
    if alone:
        new.tail = parent.tail
        parent.getparent().replace(parent, new)
        return
    new.tail = link.tail
    parent.replace(link, new)


# What a program's pre holds as text: a line break, and words set apart
# (a span, a link, bold, italics), whose text a code block keeps.
TEXT_IN_CODE = {"br", "span", "a", "b", "strong", "i", "em", "u", "sub", "sup",
                "small", "code"}


def _code_blocks(exercise):
    """A program the bank writes as preformatted text, a pre with no code
    in it (274 of Introduction to Python Programming's code blocks), as
    cnxml.do_code writes a page's own block of code of text alone: its
    text in a code element of its classes, which Pandoc's HTML reader
    reads as code, where from Pandoc 3.11 it reads a pre without one as
    text set apart, each space a no-break space and each line a line
    break, so no format had them as code; its no-break spaces, the bank's
    way of keeping indentation, spaces; its indentation kept, the
    program's own, where code_lines takes off what a page's every line
    shares, its source's markup's (the bank indents the methods a
    question offers to sit in their class, Python's CPL-ch11-m04-p06);
    and lines the questions name by number ("After line 1"), class
    line-numbering, numbered as Pandoc numbers a code block's
    (numberLines). A picture in it, which a code block can't hold
    (Principles of Data Science's DS_Ch05_Sec03_QP4 shows a plot after
    its program, in the pre), stands after the code before it, and the
    code after it is a block of its own; a pre holding more than text
    inside the words it sets apart is left as it is."""
    for pre in list(exercise.iter("pre")):
        if pre.find("code") is not None or any(
                isinstance(el.tag, str) and el.tag not in TEXT_IN_CODE
                for child in pre if child.tag in TEXT_IN_CODE
                for el in child.iterdescendants()):
            continue
        for part in _parts_of(pre):
            if part.tag == "pre":
                _as_code(part)


def _parts_of(pre):
    """pre split, in its place, at each child that isn't text: a pre for
    each run of text and words (one of nothing but spaces left out), the
    child between them. Returns the parts."""
    if all(not isinstance(child.tag, str) or child.tag in TEXT_IN_CODE
           for child in pre):
        return [pre]
    parts = []
    current = E("pre", dict(pre.attrib))
    current.text = pre.text
    for child in list(pre):
        if not isinstance(child.tag, str) or child.tag in TEXT_IN_CODE:
            current.append(child)
            continue
        after, child.tail = child.tail, None
        parts += [current, child]
        current = E("pre", {k: v for k, v in pre.attrib.items() if k != "id"})
        current.text = after
    parts.append(current)
    parts = [p for p in parts if p.tag != "pre" or len(p)
             or (p.text or "").strip()]
    if pre.get("id") and parts and pre.get("id") not in (
            p.get("id") for p in parts):
        first = next((p for p in parts if not p.get("id")), None)
        if first is not None:
            first.set("id", pre.get("id"))
    parent, tail = pre.getparent(), pre.tail
    index = parent.index(pre)
    parent.remove(pre)
    for k, part in enumerate(parts):
        parent.insert(index + k, part)
    if parts:
        parts[-1].tail = tail
    return parts


def _as_code(pre):
    classes = (pre.get("class") or "").split()
    code = E("code", {"class": " ".join(classes) or None})
    code.text, pre.text = pre.text, None
    for child in list(pre):
        code.append(child)
    pre.append(code)
    for node in code.iter():
        if node.text:
            node.text = node.text.replace("\u00a0", " ")
        if node is not code and node.tail:
            node.tail = node.tail.replace("\u00a0", " ")
    code_lines(code, dedent=False)
    if "line-numbering" in classes and "numberLines" not in classes:
        pre.set("class", " ".join(classes + ["numberLines"]))


def _pictures(asm, exercise, bank, code, page_key="", decorative=None):
    """Each picture an exercise shows, fetched into the cache and copied
    to media/exercises/. One the bank marks decorative, its alt empty,
    goes in decorative, {path: [(img, exercise)]}, for
    report_decorative."""
    for img in exercise.iter("img"):
        src = img.get("src") or ""
        if not src.startswith(("http://", "https://")):
            continue
        path = bank.image(src)
        if path is None:
            asm.report(page_key, "exercise-image-missing",
                       f"{code}: {src} couldn't be fetched")
            continue
        rel = posixpath.join("media", "exercises", _named_for_bytes(path))
        asm.media[rel] = path
        img.set("src", rel)
        alt = img.get("alt")
        if decorative is not None and alt is not None and not alt.strip():
            decorative.setdefault(rel, []).append((img, code))


def report_decorative(pages, decorative, report):
    """Each picture an exercise shows that the bank marks decorative
    (decorative, from inject), reported on the page that shows it, once
    baking has put each part of an exercise where it goes and left out
    what it drops (an answer's feedback, a solution its recipe doesn't
    keep): every format hides such a picture from a screen reader, and
    the bank marks some so that the question is about (Biology for AP
    Courses' apbio-ch03-ex065 asks of a Western blot "What is the
    relationship between the green line and the red line?"; 174 of that
    book's pictures, in 177 places, are marked so), which a row of
    image-alt.csv describes, under the page's name and the picture's
    path, or the path alone for every page. A row names the exercise that
    showed the picture there, or, where baking copied it, every exercise
    that showed that picture."""
    owner = {page.element: page for page in pages}
    for page in pages:
        for img in page.element.iter("img"):
            src, alt = img.get("src") or "", img.get("alt")
            if src not in decorative or alt is None or alt.strip():
                continue
            if next((a for a in img.iterancestors() if a in owner),
                    None) is not page.element:
                continue                 # a page inside this one says it
            shown = decorative[src]
            codes = ", ".join(dict.fromkeys(
                [code for el, code in shown if el is img]
                or [code for _, code in shown]))
            report(page.name, "exercise-image-decorative",
                   f"{codes}: {src} is marked decorative in the bank "
                   "(alt=\"\"), so no format gives it to a screen reader; if "
                   "the question needs it, describe it in image-alt.csv")


def _named_for_bytes(path):
    """A cached picture's name with the extension its bytes call for. The
    bank's address for a picture often has none (an S3 key), so the cache
    keeps it as .png, which 316 JPEGs and 80 SVGs of the 3,869 pictures
    the 26 books' exercises show weren't (Algebra 1's 187 JPEGs and 80
    SVGs, Biology for AP Courses' 126 JPEGs, and Contemporary
    Mathematics' 3): a browser shows no SVG so named, a PDF stops on one,
    and epubcheck rejects the EPUB (OPF-029), as a page's own misnamed
    picture is renamed for (assemble.Assembly._named_for_its_bytes). The
    cache's name stays, so that the address finds it."""
    name = os.path.basename(path)
    stem, ext = os.path.splitext(name)
    with open(path, "rb") as fh:
        right = FORMATS.get(sniff(fh.read(2048)))
    if right and ext.lower() not in (right, ".jpeg" if right == ".jpg"
                                     else right):
        return stem + right
    return name


def _formulas(asm, exercise, page_key, code, found):
    """The formulas of an exercise (TeX, in a data-math attribute or as
    an element's text), gathered to be made MathML together."""
    for el in exercise.iter():
        if isinstance(el.tag, str) and el.get("data-math") is not None:
            tex = el.get("data-math") or "".join(el.itertext())
            found.append((el, tex.strip(), page_key, code))


def tex_to_mathml(asm, found, pandoc=None):
    """Each formula made MathML by Pandoc's TeX reader, as the page's
    formulas are, without a line break just before an environment's end,
    which MathJax ends no row at (texforms.mathjax_rows); one Pandoc
    can't read, read again with MathJax's and plain TeX's forms written
    as LaTeX's (texforms.latex_forms); one it can't read either way, or
    every one when there's no Pandoc, left as its TeX and reported.
    Returns how many were read once rewritten."""
    pandoc = pandoc or shutil.which("pandoc")
    made = {}
    rewritten = 0
    if pandoc and found:
        tried = [mathjax_rows(tex) for _, tex, _, _ in found]
        made = _through_pandoc(pandoc, tried)
        again = {}
        for index, (_, tex, _, _) in enumerate(found):
            if index not in made:
                forms = latex_forms(tex)
                if forms and forms != tried[index]:
                    again[index] = forms
        if again:
            order = list(again)
            read = _through_pandoc(pandoc, [again[i] for i in order])
            for k, math in read.items():
                made[order[k]] = math
            rewritten = len(read)
    for index, (el, tex, page_key, code) in enumerate(found):
        math = made.get(index)
        for child in list(el):
            el.remove(child)
        if math is None:
            el.text = tex
            asm.report(page_key, "exercise-tex",
                       f"{code}: {tex[:80]} left as TeX"
                       + ("" if pandoc else " (no Pandoc to read it)"))
            continue
        el.text = None
        if el.tag == "div":
            math.set("display", "block")
        el.append(math)
    return rewritten


def _through_pandoc(pandoc, formulas):
    """{index: <math>} for the formulas Pandoc read; one call for all,
    each formula a paragraph of its own, then one call each for any the
    first didn't give back one for one."""
    def run(texs):
        source = "\n\n".join(f"\\({tex}\\)" for tex in texs)
        try:
            done = subprocess.run([*pandocrun.command(pandoc), "-f", "latex", "-t", "html",
                                   *pandocversion.mathml(pandoc)], input=source,
                                  capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            return None
        if done.returncode != 0:
            return None
        try:
            paragraphs = lxml_html.fragments_fromstring(done.stdout)
        except (etree.ParserError, ValueError):
            return None
        out = []
        for p in paragraphs:
            if isinstance(p, str):
                continue
            maths = [m for m in p.iter() if isinstance(m.tag, str)
                     and m.tag.split("}")[-1] == "math"]
            out.append(_mathml(maths[0]) if len(maths) == 1 else None)
        return out

    results = run(formulas)
    if results is not None and len(results) == len(formulas):
        return {i: m for i, m in enumerate(results) if m is not None}
    made = {}
    for i, tex in enumerate(formulas):
        one = run([tex])
        if one and len(one) == 1 and one[0] is not None:
            made[i] = one[0]
    return made


def _mathml(math):
    """A <math> lxml's HTML parser read, as MathML in the tree's terms:
    the same elements in MathML's namespace, unprefixed."""
    def copy(el, parent=None):
        name = el.tag.split("}")[-1]
        attrib = {k: v for k, v in el.attrib.items()
                  if isinstance(k, str) and ":" not in k
                  and not k.startswith("xmlns")}
        if parent is None:
            out = etree.Element(f"{{{MATHML}}}{name}", attrib,
                                nsmap={None: MATHML})
        else:
            out = etree.SubElement(parent, f"{{{MATHML}}}{name}", attrib)
        out.text = el.text
        for child in el:
            if isinstance(child.tag, str):
                copy(child, out)
        out.tail = el.tail if parent is not None else None
        return out
    return copy(math)
