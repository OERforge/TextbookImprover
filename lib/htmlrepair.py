"""
htmlrepair -- what an HTML source needs done to it before Pandoc reads it,
on a copy. The HTML counterpart of docxrepair.py, and for the same reason:
the reader loses things a book's links depend on, and nothing downstream
can put back what it never saw.

**An id survives reading only on an element the AST can hang it on.**
Pandoc's HTML reader keeps the id of a div, a section, a span, a heading,
a link, an image, a figure, a table, and code. It builds a paragraph, a
list item, a definition, a table cell, a caption, a block quote, and
every inline mark from their contents alone (pPara and its neighbours in
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
    return _BEFORE.sub(before, markup), count


def repaired_copy(source, destination):
    """Write the repaired page to destination; returns how many ids moved."""
    with open(source, encoding="utf-8", errors="replace") as fh:
        markup, count = repaired(fh.read())
    with open(destination, "w", encoding="utf-8") as fh:
        fh.write(markup)
    return count
