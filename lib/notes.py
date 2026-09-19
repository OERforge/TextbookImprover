"""
notes.py -- number and place footnotes across the pages of a book.

Pandoc numbers footnotes per document, and every rendered page is a
document to it, so a chapter cut into pages restarts at 1 on each page
and keeps each page's notes at its end. Two settings change that after
rendering, on the HTML of every page and on the XHTML of every EPUB
chapter alike:

    notes.numbering   page   restart on every page (Pandoc's own)
                      group  continue across the pages of the enclosing group
    notes.placement   page   each page's notes at its end (Pandoc's own)
                      group  gathered at the end of the group's last page
                      book   gathered on one Notes page, a heading per group

A group is whatever the split made of a source: a chapter file's
sections, an H1's sections in a single-file book. A page that was not
split is a group of one.

Pandoc cannot be asked to start numbering at 7, so the numbers are
rewritten in the output: the reference's visible number, the note's
number, and the ids that tie them, which stay unique within whichever
page ends up holding the note.

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

# Pandoc's HTML writer and its EPUB writer mark the same things in the
# same classes; they differ in the container (an ol of li, or asides).
# Pandoc wraps a long tag's attributes across lines, so whitespace
# between them is any whitespace.
REF = re.compile(r'<a\s+href="([^"]*?)#fn(\d+)"\s+class="footnote-ref"\s+'
                 r'id="fnref(\d+)"([^>]*)>(<sup>)?(\d+)(</sup>)?</a>')
SECTION = re.compile(r'<section id="footnotes"[^>]*>.*?</section>\s*', re.S)
LI = re.compile(r'<li id="fn(\d+)"[^>]*>(.*?)</li>\s*(?=<li id="fn|</ol>)',
                re.S)
ASIDE = re.compile(r'<aside[^>]*\bid="fn(\d+)"[^>]*>(.*?)</aside>\s*', re.S)
BACK = re.compile(r'href="([^"]*?)#fnref(\d+)"')
NUMBER_SPAN = re.compile(r'<span class="footnote-number">\d+\.</span>')


class Page:
    """One rendered page: its text, and where it sits in the book."""

    def __init__(self, name, text, group, group_title, flavor):
        self.name = name                # what a link to it looks like
        self.text = text
        self.group = group              # a key shared by the group's pages
        self.group_title = group_title
        self.flavor = flavor            # "html" or "xhtml"
        self.notes = []                 # [(old number, item html)]

    def take_notes(self):
        """Cut the notes out of the page, keeping them."""
        match = SECTION.search(self.text)
        if not match:
            return
        section = match.group(0)
        items = LI.findall(section) if self.flavor == "html" \
            else ASIDE.findall(section)
        self.notes = [(int(n), body) for n, body in items]
        self.text = self.text[:match.start()] + self.text[match.end():]


def renumber(page, offset, dest, prefix=""):
    """Give a page's references and notes their new numbers.

    Refs in the page text point at the note's new home (dest, a page
    name, or "" for the same page); the notes' back links point at this
    page. Ids get the new number and a prefix that keeps them unique when
    notes from several groups share a page.
    """
    mapping = {n: n + offset for n, _ in page.notes}
    if not mapping:
        # A page whose notes were already taken, or never had any: its refs
        # may still need re-pointing if numbering is untouched. Nothing to
        # do when the offset is 0 and dest is the page itself.
        pass

    def fix_ref(m):
        old = int(m.group(2))
        new = mapping.get(old, old + offset)
        target = ("" if dest == page.name else dest)
        return (f'<a href="{target}#{prefix}fn{new}" class="footnote-ref" '
                f'id="{prefix}fnref{new}" {" ".join(m.group(4).split())}>'
                f'{m.group(5) or ""}{new}{m.group(7) or ""}</a>')
    page.text = REF.sub(fix_ref, page.text)

    rebuilt = []
    for old, body in page.notes:
        new = mapping[old]
        body = BACK.sub(lambda m: f'href="{"" if dest == page.name else page.name}'
                                  f'#{prefix}fnref{new}"', body)
        body = re.sub(r'(class="footnote-back"[^>]*)>',
                      lambda m: (m.group(1) + f' aria-label="Back to '
                                 f'reference {new}">')
                      if "aria-label" not in m.group(1) else m.group(0), body)
        body = NUMBER_SPAN.sub(
            f'<span class="footnote-number">{new}.</span>', body)
        rebuilt.append((new, body))
    page.notes = rebuilt
    return page


def render_notes(notes, flavor, prefix=""):
    """The notes as one footnotes section in the writer's own shape."""
    if not notes:
        return ""
    if flavor == "html":
        items = "\n".join(f'<li id="{prefix}fn{n}" value="{n}">{body}</li>'
                          for n, body in notes)
        return (f'<section id="{prefix}footnotes" class="footnotes '
                'footnotes-end-of-document" role="doc-endnotes">\n<hr />\n'
                f'<ol>\n{items}\n</ol>\n</section>\n')
    items = "\n".join(
        f'<aside epub:type="footnote" role="doc-footnote" '
        f'id="{prefix}fn{n}">{body}</aside>' for n, body in notes)
    return (f'<section id="{prefix}footnotes" class="footnotes '
            'footnotes-end-of-document" epub:type="footnotes">\n<hr />\n'
            f'{items}\n</section>\n')


def insert_before_end(text, block, flavor):
    """Put a block at the end of the page's content."""
    marker = "</body>" if flavor == "html" else "</section>\n</body>"
    at = text.rfind(marker)
    if at < 0:
        at = text.rfind("</body>")
    return text[:at] + block + text[at:] if at >= 0 else text + block


def arrange(pages, numbering, placement, notes_page=None):
    """Apply the two settings to a book's pages, in reading order.

    pages: [Page]; notes_page: a Page to hold everything when placement
    is "book" (its text gets the sections and a heading per group).
    Returns the pages whose text changed.
    """
    if numbering == "page" and placement == "page":
        return []
    changed = []
    for page in pages:
        page.take_notes()

    groups = []
    for page in pages:
        if not groups or groups[-1][0] != page.group:
            groups.append((page.group, page.group_title, []))
        groups[-1][2].append(page)

    book_sections = []
    for index, (_, title, members) in enumerate(groups, 1):
        offset = 0
        gathered = []
        prefix = f"g{index}-" if placement == "book" else ""
        dest = members[-1].name if placement == "group" else \
            (notes_page.name if placement == "book" else None)
        for page in members:
            page_offset = offset if numbering == "group" else 0
            renumber(page, page_offset, dest or page.name, prefix)
            if page.notes:
                changed.append(page)
            if numbering == "group":
                offset += len(page.notes)
            if placement == "page":
                page.text = insert_before_end(
                    page.text, render_notes(page.notes, page.flavor),
                    page.flavor)
            else:
                gathered.extend(page.notes)
        if placement == "group" and gathered:
            last = members[-1]
            last.text = insert_before_end(
                last.text, render_notes(gathered, last.flavor), last.flavor)
            if last not in changed:
                changed.append(last)
        elif placement == "book" and gathered:
            heading = f"<h2>{html.escape(title)}</h2>\n"
            book_sections.append(heading + render_notes(
                gathered, notes_page.flavor, prefix))
    if placement == "book" and notes_page is not None and book_sections:
        notes_page.text = insert_before_end(
            notes_page.text, "".join(book_sections), notes_page.flavor)
        changed.append(notes_page)
    return changed
