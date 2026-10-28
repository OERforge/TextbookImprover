"""
mathstyle -- where a formula's MathML sets in display style something
display style draws otherwise than text style does, for a worked example's
steps the CNX unpacker lays out (cnx.steptables) and a formula in running
text an HTML page sets so (marked_in_text), which math-repair.lua sets in
display style where math.display_style_in_text says to.

Pandoc's reader drops MathML's display style, an mstyle with displaystyle,
or a math element's own (texmath's MathML reader), so every output sets
such a formula in text style: a fraction's parts and an integral's limits
small, a sum's limits beside it as scripts. A formula in a span of class
displaystyle (DISPLAY_CLASS) html-source.lua sets in display style,
\\displaystyle opening its TeX, which target-blocks.lua writes as an
mstyle on a page and in an EPUB. Display style changes a formula only
where it holds a fraction, a large operator, or an operator's limits under
and over it, set so (style_set); a fraction's parts, a script, and a
table's cells are in text style or smaller whatever the formula's style,
as MathML sets them, unless a table says its cells are in display style.

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

import re
from html.parser import HTMLParser

# What MathML draws larger in display style: an integral, a sum, a product,
# a union, and their kin, as MathML's operator dictionary has them
# (largeop).
LARGE_OPERATORS = set("∫∬∭∮∯∰∱∲∳⨋⨌⨍⨎⨏⨐⨑⨒⨓⨔⨕⨖⨗⨘⨙⨚⨛⨜"
                      "∑∏∐⋀⋁⋂⋃⨀⨁⨂⨃⨄⨅⨆⨉")
# What makes an element an operator still, holding one alone (MathML's
# embellished operators).
EMBELLISHING = ("mrow", "mstyle", "mpadded", "mphantom")
# What holds scripts, which are in text style or smaller after the first
# of what it holds, its base.
SCRIPTED = {"msub", "msup", "msubsup", "munder", "mover", "munderover",
            "mmultiscripts", "mroot"}
# The class of a span around a formula set in display style, which
# html-source.lua reads: a worked example's step the CNX unpacker marks.
DISPLAY_CLASS = "displaystyle"
# The class of a span around a formula in running text a page sets in
# display style (marked_in_text), which math-repair.lua sets so, or not, as
# math.display_style_in_text says.
TEXT_CLASS = "displaystyle-text"


def name(el):
    """An element's local name, whatever its namespace: lxml's and
    html5lib's MathML alike; '' for a comment."""
    return el.tag.rsplit("}", 1)[-1] if isinstance(el.tag, str) else ""


def text(el):
    return "".join(el.itertext())


def large(el):
    """Whether an mo is a large operator: as its largeop says, or else as
    LARGE_OPERATORS has it."""
    if el.get("largeop") in ("true", "false"):
        return el.get("largeop") == "true"
    return text(el).strip() in LARGE_OPERATORS


def style_set(el):
    """Whether display style draws an element otherwise than text style
    does: a fraction, its parts at full size; a large operator, at its
    larger size; and an operator's limits, a sum's or a limit's (a large
    operator, or one named in letters), under and over it, where text
    style sets them as scripts. An accent over a letter, a brace under
    it, or words over an arrow are drawn the same in both."""
    kind = name(el)
    if kind == "mfrac":
        return True
    if kind in ("munder", "mover", "munderover"):
        base = next((k for k in el if name(k)), None)
        while base is not None and name(base) in EMBELLISHING:
            kids = [k for k in base if name(k)]
            base = kids[0] if len(kids) == 1 else None
        return base is not None and name(base) == "mo" and (
            large(base) or text(base).strip().isalpha())
    return kind == "mo" and large(el)


def displayed(pieces, starts):
    """Whether a formula, made of pieces, holds something display style
    draws otherwise (style_set) set in display style: under an mstyle with
    displaystyle "true", nearer than one with "false", or where a piece
    starts in it (starts(piece), a piece's style where nothing in it says
    otherwise). A fraction's parts, a script, and a table's cells are in
    text style or smaller, as MathML sets them, whatever the formula's
    style, unless a table says its cells are in display style."""
    def walk(el, on):
        kind = name(el)
        if kind == "mstyle" and el.get("displaystyle") in ("true", "false"):
            on = el.get("displaystyle") == "true"
        if on and style_set(el):
            return True
        if kind == "mfrac":
            on = False
        elif kind == "mtable":
            on = el.get("displaystyle") == "true"
        for at, kid in enumerate(k for k in el if name(k)):
            if walk(kid, on and not (at and kind in SCRIPTED)):
                return True
        return False
    return any(walk(piece, starts(piece)) for piece in pieces)


def in_display(math):
    """Whether a formula in running text, a math element, sets in display
    style something display style changes: as an mstyle in it says, or
    the math element's own displaystyle, text style otherwise."""
    pieces = [k for k in math if name(k) and name(k) not in ("annotation", "annotation-xml")]
    on = math.get("displaystyle") == "true"
    return displayed(pieces, lambda piece: on)


# A formula's display, and a span of either class just before one, which
# marks it already: the CNX unpacker's, around a step's formula, or this
# one's, in a page an earlier run wrote.
BLOCK = re.compile(r"""\sdisplay\s*=\s*["']?block""", re.I)
MARKED = re.compile(r"""<span\s+class\s*=\s*["'](?:%s|%s)["']\s*>\s*$"""
                    % (DISPLAY_CLASS, TEXT_CLASS), re.I)


class _Formulas(HTMLParser):
    """Where each formula is in a page's markup, as an HTML parser reads
    it: (start, end) of each math element, from its start tag through its
    end tag, not one in a comment, a script, or a style sheet, nor the
    words <math> in an attribute's value, which a pattern had taken for a
    formula's start, its span then cutting into the comment or the
    attribute. MathML doesn't nest one math element in another, and an
    empty one (<math/>) holds nothing."""

    def __init__(self, markup):
        super().__init__(convert_charrefs=False)
        self.markup, self.spans, self.opened = markup, [], None
        self.lines = [0] + [m.end() for m in re.finditer("\n", markup)]
        self.feed(markup)
        self.close()

    def _at(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if tag == "math" and self.opened is None:
            self.opened = self._at()

    def handle_endtag(self, tag):
        if tag == "math" and self.opened is not None:
            end = self.markup.find(">", self._at())
            if end >= 0:
                self.spans.append((self.opened, end + 1))
            self.opened = None


def marked_in_text(markup):
    """(markup, how many): a page's markup with each formula in running
    text that sets in display style something display style changes
    (in_display), and isn't marked already, in a span of class
    displaystyle-text (TEXT_CLASS), which math-repair.lua sets in display
    style where math.display_style_in_text says to. A display formula
    (display="block") is in display style anyway. The markup is edited as
    text, a formula at a time, each found as an HTML parser finds it
    (_Formulas), and the rest left as it was."""
    if "displaystyle" not in markup:
        return markup, 0
    import htmlparse as hp
    out, last, count = [], 0, 0
    for start, end in _Formulas(markup).spans:
        whole = markup[start:end]
        if BLOCK.search(whole[:whole.index(">") + 1]) or "displaystyle" not in whole \
                or MARKED.search(markup[max(0, start - 80):start]):
            continue
        math = next((e for e in hp.parse("<body>" + whole + "</body>").iter()
                     if name(e) == "math"), None)
        if math is None or not in_display(math):
            continue
        out.append(markup[last:start])
        out.append('<span class="%s">%s</span>' % (TEXT_CLASS, whole))
        last = end
        count += 1
    out.append(markup[last:])
    return "".join(out), count
