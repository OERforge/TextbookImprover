#!/usr/bin/env python3
"""
cnx-compare-word.py -- compare a book unpack-cnx.py wrote with the Word
files OpenStax exports for the same book, page by page, as text.

    python3 util/cnx-compare-word.py ~/books/econ ~/corpus/Economics3e_docx
    python3 util/cnx-compare-word.py ~/books/econ ~/corpus/Economics3e_docx \\
        --page 3-1-demand-supply-and-equilibrium-in-markets-for-goods-and-services

OpenStax's Word files are their baked book, cut into pages: the nearest
thing to an answer key for what unpack-cnx.py's baking should produce.
Each side is read as a stream of words (a Word file's paragraphs, the
page's text), the two aligned, and every page that differs listed with
how much and where. Names on one side only are listed first. With
--page, every difference on that page is shown.

Math is left out on both sides unless --math is given: the Word file
has it as Office Math, whose brackets and spacing aren't text, or as a
picture, and the page as MathML, so the two never read alike. The Word
file's title paragraph and "OpenStax" byline are skipped too, and a
table's caption is read after the table, where the Word file has it. A "slim"
Word file, its word/document.xml alone, is read as well as a whole one.

Needs lxml. Copyright 2026 Robert Szarka

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

import argparse
import difflib
import os
import re
import sys
import zipfile
from collections import Counter

from lxml import etree, html as lxml_html

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
SKIP_STYLES = {"Title", "Author"}
WORD = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def tokens(text):
    text = text.replace(" ", " ").replace("​", "")
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    return WORD.findall(text)


def drop(el):
    """Take an element out, its tail (the text after it) kept."""
    parent = el.getparent()
    if el.tail:
        previous = el.getprevious()
        if previous is not None:
            previous.tail = (previous.tail or "") + el.tail
        else:
            parent.text = (parent.text or "") + el.tail
    parent.remove(el)


def word_tokens(path, math=False):
    with zipfile.ZipFile(path) as z:
        root = etree.fromstring(z.read("word/document.xml"))
    if not math:
        for el in root.xpath("//m:oMathPara | //m:oMath[not(ancestor::m:oMathPara)]",
                             namespaces={"m": M}):
            drop(el)
    out = []
    for p in root.iter(f"{{{W}}}p"):
        style = p.find(f"{{{W}}}pPr/{{{W}}}pStyle")
        if style is not None and style.get(f"{{{W}}}val") in SKIP_STYLES:
            continue
        parts = []
        for el in p.iter(f"{{{W}}}t", f"{{{M}}}t", f"{{{W}}}tab"):
            if el.tag == f"{{{W}}}tab":
                parts.append(" ")
            else:
                parts.append(el.text or "")
        out.extend(tokens("".join(parts)))
    return out


MATHML = "http://www.w3.org/1998/Math/MathML"


def html_tokens(path, math=False):
    # The pages are well-formed XML, read as XML so a formula is found by
    # its namespace; a page that isn't is read as HTML, its formulas kept.
    try:
        doc = etree.parse(path).getroot()
    except etree.XMLSyntaxError:
        with open(path, encoding="utf-8") as fh:
            doc = lxml_html.fromstring(fh.read().encode("utf-8"))
    for el in doc.iter():
        if isinstance(el.tag, str) and el.tag.startswith("{"):
            if not math and etree.QName(el).localname == "math":
                el.set("data-drop", "math")
            el.tag = etree.QName(el).localname
    body = doc.find("body")
    if body is None:
        body = doc
    for bad in body.xpath(".//script | .//style | .//*[@data-drop]"):
        drop(bad)
    # Learning objectives numbered by place are a numbered list here, the
    # numbers its own; OpenStax's Word files have each number as a word,
    # as baking wrote it, so they're read with theirs.
    for ol in body.xpath(".//ol[contains(concat(' ', @class, ' '), "
                         "' os-abstract ')]"):
        for number, li in enumerate(ol.xpath("./li"), 1):
            li.text = f"{number} " + (li.text or "")
    # A note's kind and its own title are one heading here, a colon
    # between them ("Big Picture: A Global Culture?"), and two in the Word
    # files, so they're read without the colon. A note headed by its kind
    # alone, its title repeating it, or by its title alone, which opens
    # with its kind, has both in the Word file, so the kind's words are
    # the Word file's alone ("Careers in IS", in Foundations of
    # Information Systems).
    for label in body.xpath(".//span[contains(concat(' ', @class, ' '), "
                            "' os-note-label ')]"):
        label.tail = re.sub(r"^:", " ", label.tail or "")
    # A table's caption is read after it, where OpenStax puts it.
    for caption in body.xpath(".//table/caption"):
        table = caption.getparent()
        drop(caption)
        caption.tail = table.tail
        table.tail = None
        table.addnext(caption)
    # The text in reading order, a space where a block ends and nowhere
    # else, so a subscript stays joined to what it follows (E0).
    texts = []

    def walk(el):
        block = isinstance(el.tag, str) and el.tag in BLOCKS
        if block:
            texts.append(" ")
        if el.text:
            texts.append(el.text)
        for child in el:
            walk(child)
            if child.tail:
                texts.append(child.tail)
        if block:
            texts.append(" ")

    walk(body)
    return tokens("".join(texts))


BLOCKS = {"p", "li", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "dt",
          "dd", "figcaption", "caption", "br", "div", "tr", "figure",
          "table", "ul", "ol", "dl", "pre", "blockquote", "section"}


def compare(ours, theirs):
    matcher = difflib.SequenceMatcher(None, ours, theirs, autojunk=False)
    diffs = [op for op in matcher.get_opcodes() if op[0] != "equal"]
    return matcher.ratio(), diffs


def unmatched(ours, theirs):
    """The words one side has more of than the other, order aside: what
    was lost or added rather than moved."""
    a, b = Counter(ours), Counter(theirs)
    return a - b, b - a


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("pages", help="the directory unpack-cnx.py wrote")
    parser.add_argument("word", help="a directory of OpenStax's Word files")
    parser.add_argument("--page", help="show every difference on one page")
    parser.add_argument("--below", type=float, default=0.98,
                        help="list pages whose similarity is below this "
                        "(default 0.98)")
    parser.add_argument("--math", action="store_true",
                        help="compare the words of formulas too")
    parser.add_argument("--words", type=int, default=4,
                        help="list pages where more words than this are on "
                        "one side only, order aside (default 4)")
    args = parser.parse_args()
    ours = {f[:-5] for f in os.listdir(args.pages) if f.endswith(".html")}
    theirs = {f[:-5] for f in os.listdir(args.word) if f.endswith(".docx")}
    only_ours = sorted(ours - theirs)
    only_theirs = sorted(theirs - ours)
    if only_ours:
        print(f"{len(only_ours)} page(s) only here: " + ", ".join(only_ours))
    if only_theirs:
        print(f"{len(only_theirs)} Word file(s) with no page: "
              + ", ".join(only_theirs))
    names = [args.page] if args.page else sorted(ours & theirs)
    worst = []
    total = 0
    for name in names:
        a = html_tokens(os.path.join(args.pages, name + ".html"), args.math)
        b = word_tokens(os.path.join(args.word, name + ".docx"), args.math)
        ratio, diffs = compare(a, b)
        total += 1
        extra, missing = unmatched(a, b)
        if args.page:
            print(f"{name}: similarity {ratio:.4f}, {len(diffs)} difference(s)")
            print(f"  only ours: {dict(extra.most_common(30))}")
            print(f"  only Word: {dict(missing.most_common(30))}")
            for tag, i1, i2, j1, j2 in diffs:
                print(f"  {tag:7s} ours: {' '.join(a[i1:i2])[:200]!r}")
                print(f"          Word: {' '.join(b[j1:j2])[:200]!r}")
            continue
        lost = sum(extra.values()) + sum(missing.values())
        if ratio < args.below or lost > args.words:
            worst.append((ratio, name, diffs, a, b, extra, missing))
    if args.page:
        return 0
    worst.sort()
    print(f"{total} page(s) compared; {len(worst)} below {args.below}:")
    for ratio, name, diffs, a, b, extra, missing in worst:
        print(f"  {ratio:.4f}  {name}  {len(diffs)} difference(s); "
              f"words only here {sum(extra.values())}: "
              f"{' '.join(list(extra.elements())[:12])!r}; "
              f"only in Word {sum(missing.values())}: "
              f"{' '.join(list(missing.elements())[:12])!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
