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
element. Its formulas are TeX (a span or div with data-math), made
MathML by Pandoc's TeX reader, one Pandoc can't read left as its TeX and
reported; its pictures are fetched into the cache and copied to
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
import json
import os
import posixpath
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from lxml import etree
from lxml import html as lxml_html

from .cnxml import E, append_text
from .mathml import MATHML

HOST = "exercises.openstax.org"
TOKEN_VARIABLE = "OPENSTAX_EXERCISES_TOKEN"
# How a link names its exercise, and what the API is asked for.
PREFIXES = (("#exercise/", "nickname"), ("#ost/api/ex/", "tag"))
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}


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


class Bank:
    """The exercise bank, through its cache. With offline set, only the
    cache is read."""

    def __init__(self, cache=None, offline=False, token=None, host=HOST,
                 timeout=30):
        self.cache = cache or default_cache()
        self.offline = offline
        self.token = token if token is not None else os.environ.get(
            TOKEN_VARIABLE) or None
        self.host = host
        self.timeout = timeout
        # A response made with a token holds what one made without
        # doesn't, so the two are kept apart.
        self.root = os.path.join(self.cache,
                                 "with-token" if self.token else "public")
        self.failures = {}      # (kind, code) -> why it couldn't be had

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
        or None (the reason kept in failures)."""
        data = self.cached(kind, code)
        if data is not None:
            return data
        if self.offline:
            self.failures[(kind, code)] = "not in the cache, and offline"
            return None
        try:
            data = json.loads(self._fetch(self.url(kind, code)).decode(
                "utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self.failures[(kind, code)] = f"couldn't be fetched: {exc}"
            return None
        self._keep(self.path(kind, code), json.dumps(
            data, ensure_ascii=False, indent=1).encode("utf-8"))
        return data

    def prefetch(self, wanted, workers=8):
        """Fetch every (kind, code) not yet cached, several at once."""
        todo = [w for w in dict.fromkeys(wanted)
                if not os.path.exists(self.path(*w))]
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
        except (urllib.error.URLError, OSError, ValueError):
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

    @staticmethod
    def _keep(path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)


# HTML from the bank, into the tree -------------------------------------

def html_children(text):
    """An HTML fragment as (leading text, [elements]) in the tree's own
    elements: what the bank writes copied element by element, since
    lxml's HTML elements don't mix with the rest."""
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
            out.append(_copy(part))
    return lead, out


def _copy(element):
    tag = element.tag if isinstance(element.tag, str) else None
    if tag is None:                      # a comment
        holder = E("span")
        holder.tail = element.tail
        return holder
    out = E(tag.lower(), {k: v for k, v in element.attrib.items()
                          if isinstance(k, str) and ":" not in k})
    out.text = element.text
    for child in element:
        if isinstance(child.tag, str):
            out.append(_copy(child))
        else:
            append_text(out, child.tail)
    out.tail = element.tail
    return out


def fill(holder, html):
    """holder's content: the HTML fragment, as elements."""
    lead, children = html_children(html)
    append_text(holder, lead)
    for child in children:
        holder.append(child)
    return holder


# One exercise ----------------------------------------------------------

def render(item, page_key, link_class, url, context=None):
    """The bank's item as OpenStax's assembly writes it."""
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
                        item["stimulus_html"]))
    for question in item.get("questions") or []:
        q = E("div", {"data-type": "exercise-question",
                      "data-is-answer-order-important": str(bool(
                          question.get("is_answer_order_important"))).lower(),
                      "data-formats": " ".join(question.get("formats")
                                               or []),
                      "id": f"auto_{page_key}_{question.get('id')}"})
        if (question.get("stimulus_html") or "").strip():
            q.append(fill(E("div", {"data-type": "question-stimulus"}),
                          question["stimulus_html"]))
        q.append(fill(E("div", {"data-type": "question-stem"}),
                      question.get("stem_html") or ""))
        answers = question.get("answers") or []
        if answers:
            ol = E("ol", {"data-type": "question-answers", "type": "a"})
            for answer in answers:
                li = E("li", {"data-type": "question-answer",
                              "data-correctness": answer.get("correctness")})
                li.append(fill(E("div", {"data-type": "answer-content"}),
                               answer.get("content_html") or ""))
                if (answer.get("feedback_html") or "").strip():
                    li.append(fill(E("div", {"data-type": "answer-feedback"}),
                                   answer["feedback_html"]))
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
            q.append(fill(holder, solution.get("content_html") or ""))
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
        if module and page.getroottree().xpath(
                f"//*[@id='{module}__{feature}']"):
            return f"{module}__{feature}"
    return None


def missing(kind, code, why):
    """What stands where an exercise couldn't be put: a paragraph that
    says which, and where it's kept."""
    p = E("p", {"data-type": "missing-exercise"})
    p.text = (f"Exercise {code} is in OpenStax's exercise bank "
              f"({kind} {code}) and couldn't be put in here: {why}.")
    return p


def inject(asm, body, bank):
    """Every embedded exercise of the assembled book, put in. Returns
    (injected, missing)."""
    links = [a for a in body.iter("a")
             if a.get("data-type") == "embed"
             and embedded(a.get("data-embed") or "")]
    wanted = [embedded(a.get("data-embed")) for a in links]
    bank.prefetch(wanted)
    pages_by_uuid = {}
    for module_id, module in asm.modules.items():
        if getattr(module, "uuid", None):
            pages_by_uuid[module.uuid] = module_id
    done = 0
    lost = 0
    formulas = []
    for link in links:
        url = link.get("data-embed")
        kind, code = embedded(url)
        page = next((p for p in link.iterancestors("div")
                     if p.get("data-type") == "page"), None)
        data = bank.get(kind, code)
        items = (data or {}).get("items") or []
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
            new = render(item, page_key, _without(link.get("class"),
                                                  "autogenerated-content"),
                         bank.url(kind, code), context)
            _pictures(asm, new, bank, code)
            _formulas(asm, new, page_key, code, formulas)
            if not item.get("solutions_are_public", True) and not bank.token:
                asm.report(page_key, "exercise-solutions-not-public",
                           f"{url}: the bank gives its question, not its "
                           "answer")
            done += 1
        _replace_link(link, new)
    tex_to_mathml(asm, formulas)
    return done, lost


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


def _pictures(asm, exercise, bank, code):
    for img in exercise.iter("img"):
        src = img.get("src") or ""
        if not src.startswith(("http://", "https://")):
            continue
        path = bank.image(src)
        if path is None:
            asm.report("", "exercise-image-missing",
                       f"{code}: {src} couldn't be fetched")
            continue
        rel = posixpath.join("media", "exercises", os.path.basename(path))
        asm.media[rel] = path
        img.set("src", rel)


def _formulas(asm, exercise, page_key, code, found):
    """The formulas of an exercise (TeX, in a data-math attribute or as
    an element's text), gathered to be made MathML together."""
    for el in exercise.iter():
        if isinstance(el.tag, str) and el.get("data-math") is not None:
            tex = el.get("data-math") or "".join(el.itertext())
            found.append((el, tex.strip(), page_key, code))


def tex_to_mathml(asm, found, pandoc=None):
    """Each formula made MathML by Pandoc's TeX reader, as the page's
    formulas are; one Pandoc can't read, or every one when there's no
    Pandoc, left as its TeX and reported."""
    pandoc = pandoc or shutil.which("pandoc")
    made = {}
    if pandoc and found:
        made = _through_pandoc(pandoc, [tex for _, tex, _, _ in found])
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


def _through_pandoc(pandoc, formulas):
    """{index: <math>} for the formulas Pandoc read; one call for all,
    each formula a paragraph of its own, then one call each for any the
    first didn't give back one for one."""
    def run(texs):
        source = "\n\n".join(f"\\({tex}\\)" for tex in texs)
        try:
            done = subprocess.run([pandoc, "-f", "latex", "-t", "html",
                                   "--mathml"], input=source,
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
