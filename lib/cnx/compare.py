"""
cnx.compare -- reading two baked books as words, page by page, for the
utilities that check unpack-cnx.py against OpenStax's own tools:
util/cnx-compare-cookbook.py (cookbook's sample books) and
util/cnx-compare-assembly.py (a book as OpenStax's assembly writes it).

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

import difflib
import re
import sys

from lxml import etree

XHTML = "http://www.w3.org/1999/xhtml"

# What's left out of a comparison, being what the unpacker does
# differently on purpose: the book's metadata; the link cookbook writes
# beside an embedded video for print (BakeIframes, left to
# TextbookImprover); a footnote, which is Pandoc's here and an aside at
# its place there, and its number (but not a Polish book's reference,
# which both bake into the chapter's references); an inline list's
# separators, which the unpacker writes as it reads the source; the
# content MathML OpenStax's assembly adds to each formula as an
# annotation; the words cookbook writes for screen readers alone
# (BakeScreenreaderSpans: "underline ... end underline"), which a page
# without OpenStax's stylesheet would show; the running heads it writes
# for print (BakeFolio: "1.13.4 • Creating a Table from an Equation");
# and what it writes as the title of a note whose kind the locale has no
# title for ("unknown title for note with classes ...", the Polish
# nursing sample's), where the unpacker writes none.
DELIBERATE = (".//div[@data-type='metadata']"
              " | .//span[@class='os-title-label'][starts-with("
              "normalize-space(.), 'unknown title for note with classes')]"
              " | .//span[@data-media='screenreader']"
              " | .//p[starts-with(@class, 'folio-')]"
              " | .//a[contains(@class, 'os-is-link')]"
              " | .//div[@data-type='footnote-number']"
              " | .//span[@class='-os-inline-list-separator']"
              " | .//section[@role='doc-endnotes']"
              " | .//aside[@role='doc-footnote'][not(contains("
              "concat(' ', @class, ' '), ' reference '))]"
              " | .//*[local-name()='annotation-xml' or "
              "local-name()='annotation']")


def load(path):
    """An XHTML file as the unpacker's trees are: HTML's elements in no
    namespace, MathML's in its own. One that isn't well formed (cookbook's
    nursing-internal sample, cut short without its closing tags) is read
    as libxml2 recovers it, which is what cookbook's Nokogiri reads."""
    parser = etree.XMLParser(huge_tree=True, remove_comments=True)
    try:
        root = etree.parse(path, parser).getroot()
    except etree.XMLSyntaxError as error:
        print(f"  {path} isn't well formed ({error}); read as recovered",
              file=sys.stderr)
        parser = etree.XMLParser(huge_tree=True, remove_comments=True,
                                 recover=True)
        root = etree.parse(path, parser).getroot()
    for el in root.iter():
        if isinstance(el.tag, str) and el.tag.startswith("{%s}" % XHTML):
            el.tag = el.tag.split("}", 1)[1]
    etree.cleanup_namespaces(root)
    return root


def drop(el):
    """Take an element out, the text after it kept."""
    parent = el.getparent()
    if el.tail:
        previous = el.getprevious()
        if previous is not None:
            previous.tail = (previous.tail or "") + el.tail
        else:
            parent.text = (parent.text or "") + el.tail
    parent.remove(el)


def _split(text):
    """Text as words, an em dash a word of its own, so the space on
    either side of one counts for nothing: the unpacker closes up the
    dash in a title cookbook's UseSectionTitle writes ("Chemistry
    Matters—Organic Foods"), where cookbook's templates leave line
    breaks."""
    return text.replace("\u2014", " \u2014 ").split()


# Elements a word runs through ("B<sub>12</sub>", "<em>accessible</em>),",
# a word of another language), whose edges aren't a break: cookbook's
# Polish glossaries keep a meaning's text alone, the unpacker its markup
# too.
INLINE = ("sub", "sup", "em", "i", "strong", "b", "u")


def _runs_through(node):
    return etree.QName(node).localname in INLINE or (
        etree.QName(node).localname == "span"
        and node.get("data-type") == "foreign")


def words(el):
    """The element's words, each element's edges a break, so the spaces
    one side indents its markup with count for nothing, but for the
    formatting a word runs through (INLINE)."""
    parts = []

    def walk(node):
        joined = isinstance(node.tag, str) and _runs_through(node) \
            and node is not el
        parts.append("" if joined else " ")
        parts.append(node.text or "")
        for child in node:
            if isinstance(child.tag, str):
                walk(child)
            parts.append(child.tail or "")
        parts.append("" if joined else " ")

    walk(el)
    return _split("".join(parts))


def title_of(page):
    for child in page:
        if isinstance(child.tag, str) and child.get("data-type") in (
                "document-title", "title"):
            return " ".join(_split("".join(child.itertext())))
    return ""


# A link made of an address written as text (post_bake's), whose edges
# aren't compared: where the unpacker ends one before a closing quotation
# mark, or makes none of an address with no host's name, cookbook's goes
# on, and the words are the same.
ADDRESS = re.compile(r"(?:https?://|www\.|mailto:)\S*$|[^\s@]+@[^\s@]+$", re.I)


def unwrap(el):
    """Replace an element with its text, which joins the text around it."""
    parent = el.getparent()
    text = (el.text or "") + (el.tail or "")
    previous = el.getprevious()
    if previous is not None:
        previous.tail = (previous.tail or "") + text
    else:
        parent.text = (parent.text or "") + text
    parent.remove(el)


def pages(body):
    """The baked book's pages, in order, with what's left out taken out:
    [(page, its words)]. A page baking built (a chapter's "Key Terms")
    is one too."""
    for el in body.xpath(DELIBERATE):
        drop(el)
    for link in body.xpath(".//a[not(*)]"):
        if ADDRESS.match((link.text or "").strip()) and \
                ADDRESS.match(link.get("href") or ""):
            unwrap(link)
    for ref in body.xpath(".//a[@role='doc-noteref']"):
        for child in list(ref):
            ref.remove(child)
        ref.text = ""
    noblanks(body)
    return [(el, words(el)) for el in body.iter("div")
            if el.get("data-type") in ("page", "composite-page")]


def noblanks(body):
    """libxml2's noblanks, which cookbook's tests read their expected
    output with (its scripts/normalize), done to both sides: spaces alone
    between elements go when what holds them opens with an element, not
    words ("<strong>Wybór</strong> <strong>cech.</strong>" runs
    together)."""
    for el in body.iter():
        if not isinstance(el.tag, str) or not len(el) or \
                (el.text or "").strip():
            continue
        el.text = None
        for child in el:
            if child.tail is not None and not child.tail.strip():
                child.tail = None


def show(matcher, ours, theirs, limit, label):
    """Up to limit of the places two pages differ."""
    shown = 0
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal" or shown >= limit:
            continue
        print(f"      ours:{' ' * (len(label) - 4)} {' '.join(ours[i1:i2])[:150]}")
        print(f"      {label}: {' '.join(theirs[j1:j2])[:150]}")
        shown += 1


def matcher(ours, theirs):
    return difflib.SequenceMatcher(None, ours, theirs, autojunk=False)
