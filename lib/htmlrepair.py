"""
htmlrepair -- what an HTML source needs done to it before Pandoc reads it,
on a copy. The HTML counterpart of docxrepair.py, and for the same reason:
the reader loses things a book's links depend on, and nothing downstream
can put back what it never saw.

**An id survives reading only on an element the AST can hang it on.**
Pandoc's HTML reader keeps the id of a div, a section, a span, a heading,
a link, an image, a figure, a table, and code. It builds a paragraph, a
list item, a definition, a table cell, a caption, a block quote, and
every inline mark from their contents alone (pPara and its neighbors in
Readers/HTML.hs take the tag's contents and none of its attributes), so
`<p id="fs-id1167">` comes back as a paragraph with no name and every
link to it is dead. Measured; it is how publishers anchor footnotes
(`<li id="footnote-3">`), glossary terms (`<dt id=…>`), and every
cross-referenced paragraph in an OpenStax book.

The repair: the id moves to an empty `<span>` opening the element, which
the reader keeps and the writers write, and the link lands on the same
spot. For a list, where a span cannot open the element, the anchor is an
empty `<div>` before it. The file is edited as text, tag by tag: an EPUB's
pages are not reliably well-formed and a saved web page is not reliably
anything, and an opening tag is an opening tag in both.

One id is left where it is: the one a note reference names. The reader
turns a footnote into a real note when it can match a reference
(role="doc-noteref", or epub:type="noteref") to the element holding the
note by that element's own id (eNoteref and eFootnote), which is how it
reads the endnotes Pandoc writes and the ones a careful EPUB carries.
Moving such an id turned every note on a page into an empty one, with
the text gone; a fixed-point test on a page with footnotes is what
showed it.

The source is never touched. Standard library only.

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

import html
import re

INSIDE = ("p|li|dt|dd|td|th|caption|figcaption|blockquote|em|strong|b|i|u|s|"
          "cite|q|sup|sub|small|mark|abbr|dfn|kbd|samp|var|ins|del|summary")
BEFORE = "ul|ol|dl"
_ID = r"""\sid\s*=\s*("[^"]*"|'[^']*')"""
_INSIDE = re.compile(rf"<({INSIDE})\b((?:[^<>\"']|\"[^\"]*\"|'[^']*')*?)"
                     rf"{_ID}((?:[^<>\"']|\"[^\"]*\"|'[^']*')*)>", re.I)
_BEFORE = re.compile(rf"<({BEFORE})\b((?:[^<>\"']|\"[^\"]*\"|'[^']*')*?)"
                     rf"{_ID}((?:[^<>\"']|\"[^\"]*\"|'[^']*')*)>", re.I)


_NOTEREF = re.compile(r"<a\b[^<>]*\bnoteref\b[^<>]*>", re.I)
_HREF = re.compile(r"""\bhref\s*=\s*["']#([^"']+)["']""", re.I)


def note_ids(markup):
    """The ids note references point at, which stay on their elements."""
    found = set()
    for tag in _NOTEREF.findall(markup):
        target = _HREF.search(tag)
        if target:
            found.add(target.group(1))
    return found


def repaired(markup):
    """(markup, count): the page with every id the reader would lose moved
    onto an empty span (or, for a list, a div before it)."""
    count = 0
    keep = note_ids(markup)

    def inside(match):
        nonlocal count
        tag, lead, name, rest = match.groups()
        if name[1:-1] in keep:
            return match.group(0)
        count += 1
        if rest.rstrip().endswith("/"):          # <p id="x"/>, in XHTML
            return f"<{tag}{lead}{rest.rstrip()[:-1]}><span id={name}>" \
                   f"</span></{tag}>"
        return f"<{tag}{lead}{rest}><span id={name}></span>"

    def before(match):
        nonlocal count
        tag, lead, name, rest = match.groups()
        count += 1
        return f"<div id={name}></div><{tag}{lead}{rest}>"

    markup = _INSIDE.sub(inside, markup)
    markup = _BEFORE.sub(before, markup)
    markup, marked = decorative_images(markup)
    markup, titled = title_block_id(markup)
    markup = NOTES_HEADING.sub("", markup)
    markup = words_as_text(markup)[0]
    markup = body_out_of_head(markup)[0]
    return auto_id_headings(markup), count + marked + titled


_IMG = re.compile(r"<img\b((?:[^<>\"']|\"[^\"]*\"|'[^']*')*)>", re.I)
_ATTR = r"""\b%s\s*=\s*("[^"]*"|'[^']*'|[^\s"'>]+)"""


def decorative_images(markup):
    """(markup, count): each image its author marked decorative given the
    class the pipeline reads as that. In HTML an empty alt says so (it
    isn't an omission, as it is in a Word file), and so does
    role="presentation" or role="none" with no alt, which is how Canvas
    marks one. Pandoc's reader can't tell an empty alt from none, so without
    the class the image came out with no alt at all, and a screen reader
    read its file name. The role goes: an image with alt="" may carry
    none."""
    count = 0

    def mark(match):
        nonlocal count
        attrs = match.group(1)
        alt = re.search(_ATTR % "alt", attrs, re.I)
        role = re.search(_ATTR % "role", attrs, re.I)
        role_value = role.group(1).strip("\"'").strip().lower() if role else ""
        if alt is not None and alt.group(1).strip("\"'").strip():
            return match.group(0)              # a description: not decorative
        if alt is None and role_value not in ("presentation", "none"):
            return match.group(0)              # an omission: reported, not decided
        if role is not None:
            attrs = attrs[:role.start()] + attrs[role.end():]
        cls = re.search(_ATTR % "class", attrs, re.I)
        if cls is not None:
            value = cls.group(1).strip("\"'")
            if "decorative" in value.split():
                return "<img" + attrs + ">"
            attrs = attrs[:cls.start()] + 'class="%s decorative"' % value + attrs[cls.end():]
        else:
            attrs = ' class="decorative"' + attrs
        count += 1
        return "<img" + attrs + ">"
    return _IMG.sub(mark, markup), count


_TITLE_H1 = re.compile(
    r'(<header\s+id="title-block-header"\s*>\s*<h1\b)((?:(?!\bid=)[^>])*>)', re.I)


def title_block_id(markup):
    """(markup, count): the title in the title block of a page Pandoc wrote,
    given an id. Pandoc's reader makes one from a heading's text when it has
    none, and a book's page title is usually its first heading's text too:
    DCIC's "6.2 Collections of Structured Data" became
    collections-of-structured-data, the id its h3 already had, and Pandoc
    warned of a duplicate on 79 of 80 pages. The title block becomes the
    page's metadata on reading, so the id goes no further."""
    new, n = _TITLE_H1.subn(r'\1 id="title-block-title"\2', markup, count=1)
    return new, n


# The heading the run gives a page's notes (notes.py), which Pandoc's
# reader would keep, with the section around it, on a page converted
# again: the page's own notes come back as notes, and get the heading the
# run gives them, so converting the run's pages changes nothing.
NOTES_HEADING = re.compile(
    r"""<(h[1-6])\b(?:[^<>"']|"[^"]*"|'[^']*')*\bclass\s*=\s*["']footnotes-title["']"""
    r"""(?:[^<>"']|"[^"]*"|'[^']*')*>.*?</\1\s*>\s*""", re.I | re.S)


AUTO_ID = "data-ti-auto-id"
_HEADING = re.compile(r"<(h[1-6])\b((?:[^<>\"']|\"[^\"]*\"|'[^']*')*)>", re.I)
_ATTRIBUTE = re.compile(r"""([^\s"'<>/=]+)(?:\s*=\s*("[^"]*"|'[^']*'|[^\s"'=<>`]+))?""")


def auto_id_headings(markup):
    """The page with each heading that has no id of its own marked
    data-ti-auto-id. Pandoc's reader makes such a heading's id from its
    words, checking only the headings before it (registerHeader, in
    Parsing/General.hs), so a table or a div after it can carry the same
    one: <h1>Money</h1> over <table id="money">. Nothing on an HTML page
    can have meant an id its author never wrote, so the filter's
    uniqueness pass renames the heading, wherever it stands, and the id
    stays where the author's link points. The mark goes there too, and
    html-source.lua takes it off a heading it gives an id of the page's
    own. Not counted: nothing has moved."""
    def mark(match):
        tag, attributes = match.groups()
        for name, value in _ATTRIBUTE.findall(attributes):
            if name.lower() == "id" and value.strip("\"'").strip():
                return match.group(0)
        return f'<{tag} {AUTO_ID}=""{attributes}>'
    return _HEADING.sub(mark, markup)


# The names texmath, Pandoc's math reader, keeps whole in an <mi>: LaTeX's
# named operators, which it writes as \sin, \log, and the rest.
OPERATOR_NAMES = frozenset(
    "arccos arcsin arctan arg cos cosh cot coth csc deg det dim exp gcd hom "
    "inf ker lg lim liminf limsup ln log max min Pr sec sin sinh sup tan "
    "tanh".split())
_MI = re.compile(r"<((?:[A-Za-z_][\w.-]*:)?)mi(\s(?:[^<>\"']|\"[^\"]*\"|'[^']*')*)?>"
                 r"([^<]*)</\1mi\s*>", re.I)
# A function applied: MathML's U+2061 in an <mo> after its name, written
# as the character or a reference to it.
_APPLIED = re.compile(r"\s*<((?:[A-Za-z_][\w.-]*:)?)mo(?:\s(?:[^<>\"']|\"[^\"]*\"|'[^']*')*)?>"
                      r"\s*(?:\u2061|&#x0*2061;|&#0*8289;|&ApplyFunction;|&af;)\s*"
                      r"</\1mo\s*>", re.I)


def words_as_text(markup):
    """(markup, count): each word or unit a formula holds as an identifier
    (<mi>Value</mi>, <mi>MeV</mi>) made the text it is, an <mtext>. MathML
    sets an <mi> of more than one letter whole and upright, but Pandoc's
    reader reads it as letters and writes each back as an italic identifier
    of its own, which a screen reader spells out: "Value = Benefits/Price",
    in Principles of Marketing, came out as italic letters. An <mtext> is
    \\text{Value}, whole and upright.

    Only an <mi> of more than two letters, and of nothing but letters and
    spaces: one of two is as likely a product (dx, xy) as a unit (cm), and
    stays as it is, unless the source sets it upright (mathvariant="normal"),
    as a unit or an element's symbol is and a product of variables isn't, or
    applies it as a function (the Polish tg, before U+2061). So do a name
    the reader keeps whole (sin, log, lim), one letter over and over
    (xxxxx, x to the fifth written out, in College Algebra with Corequisite
    Support) but for two set upright (mm), and an <mi> styled other than
    normal or bold, which would be \\textit{} or the like, and
    \\textit{\\textbf{}} is TeX the reader can't read back.
    In sixteen of OpenStax's math and physics books and Marketing, 1,528 in
    1,130 formulas: units (MeV, mol, rad, atm), names the reader doesn't
    know (cis, the Polish arctg), words (Revenue, the Polish rok), and
    labels (net, the y-intercept's int). The one product among them was the
    repeated letter. Of two letters, in OpenStax's 49 public repositories,
    4,154 set upright and 17 applied, all in Fizyka dla szkół wyższych but
    14: units (cm, kg, eV, µF, the Polish zł), elements' symbols (He), and
    words (or, in); of the 988 others, most are products (rω, mc, w = mg in
    College Physics), and some are units (mg, mL, and cm in the nursing and
    math books), which nothing tells from a product, and stay."""
    count = 0

    def mark(match):
        nonlocal count
        prefix, attributes, text = match.group(1), match.group(2) or "", match.group(3)
        upright = False
        for name, value in _ATTRIBUTE.findall(attributes):
            if name.lower() == "mathvariant":
                style = value.strip("\"'").strip().lower()
                if style not in ("normal", "bold"):
                    return match.group(0)
                upright = style == "normal"
        words = html.unescape(text).strip()
        letters = [c for c in words if c.isalpha()]
        if words in OPERATOR_NAMES \
                or not all(c.isalpha() or c.isspace() for c in words):
            return match.group(0)
        if len(letters) == 2:
            if not upright and not _APPLIED.match(match.string, match.end()):
                return match.group(0)
        elif len(letters) < 3 or len({c.lower() for c in letters}) < 2:
            return match.group(0)
        count += 1
        return f"<{prefix}mtext{attributes}>{text}</{prefix}mtext>"
    return _MI.sub(mark, markup), count


# A table's head that the table ends with: no body after it, nor rows of
# its own. The head's contents stop at its first </thead>.
_HEAD_ONLY = re.compile(r"(<thead\b(?:[^<>\"']|\"[^\"]*\"|'[^']*')*>)"
                        r"((?:(?!</thead\s*>).)*)(</thead\s*>)(?=\s*</table\s*>)", re.I | re.S)
_ROW = re.compile(r"<tr\b", re.I)
_CELL = re.compile(r"<(td|th)\b(?:[^<>\"']|\"[^\"]*\"|'[^']*')*>", re.I)
# What a cell shows besides its text.
_SHOWN = re.compile(r"<(?:img|math|svg|object|embed|video|audio|iframe|canvas|input)\b", re.I)


def _data_row(row):
    """Whether a row holds a data cell (a <td>) with something in it."""
    cells = list(_CELL.finditer(row))
    for cell, after in zip(cells, cells[1:] + [None]):
        if cell.group(1).lower() != "td":
            continue
        content = row[cell.end():after.start() if after else len(row)]
        if _SHOWN.search(content) or html.unescape(re.sub(r"<[^<>]*>", "", content)).strip():
            return True
    return False


def body_out_of_head(markup):
    """(markup, count): each table whose <thead> holds every row, its data
    rows too, given a body of them. Pandoc's reader makes every row in a
    <thead> a header row, whatever its cells (pTableHead, in
    Readers/HTML/Table.hs), so every cell of such a table came out a
    header: a <th> in a page's or an EPUB's table with no body, which an
    accessibility checker reports as a table missing its body, a TH in a
    PDF, and a row Word repeats as a header on every page. LibreTexts'
    editor writes tables so, 63 of Instrumental Analysis's. The rows from
    the first holding a data cell (a <td> with something in it) go into a
    <tbody> after the head, and the rows before it, of header cells, an
    empty <td> in a corner among them, stay the head; a head whose first
    row holds data is all body. Only a head the table ends with: a head
    with a body after it, or rows of the table's own, is its author's
    division, and a row of <td> in it a header written so (Table 26.4.1's
    row of values of α, under its columns for each resolution), which
    stays. A head holding a table of its own is left as it is."""
    count = 0

    def divide(match):
        nonlocal count
        opening, inside, closing = match.groups()
        if re.search(r"<table\b", inside, re.I):
            return match.group(0)
        starts = [m.start() for m in _ROW.finditer(inside)]
        first = next((n for n, (a, b) in enumerate(zip(starts, starts[1:] + [len(inside)]))
                      if _data_row(inside[a:b])), None)
        if first is None:
            return match.group(0)
        count += 1
        if first == 0:              # all body: the head becomes one, attributes and all
            return re.sub(r"^<thead", "<tbody", opening, flags=re.I) + inside + "</tbody>"
        return (opening + inside[:starts[first]] + closing
                + "<tbody>" + inside[starts[first]:] + "</tbody>")
    return _HEAD_ONLY.sub(divide, markup), count


def repaired_copy(source, destination):
    """Write the repaired page to destination; returns how many ids moved."""
    with open(source, encoding="utf-8", errors="replace") as fh:
        markup, count = repaired(fh.read())
    with open(destination, "w", encoding="utf-8") as fh:
        fh.write(markup)
    return count
