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

Notes gathered from several pages share a list, so they're numbered
across their group whatever notes.numbering says: page, which restarts
on every page, would number two notes in one list 1.

A group is a top-level entry of the book's contents, the tree the HTML
pages and the EPUB are both built from (groups): a chapter, with every
page under it however deep, or a page on its own, a preface, a chapter
of one page, an appendix, or a book of one page. A part (type: part)
isn't one: each entry in it is, as at the top level. The groups and
their pages go in the contents' order. The HTML had taken a group to
be what the split made of a source, so a page that was a file of its
own was a group of one, and the EPUB a top-level entry, so a part was
one.

An HTML page's notes are headed after their rule, notes.title saying
the word (titled, and render_notes as they're arranged): Pandoc writes
no heading, so a screen reader had none to move to them by, and the Nu
checker says their section lacks one. On the Notes page, in the pages
and the EPUB alike, each group's notes are headed by the group's title.
An EPUB's notes at the end of a chapter have none, since a reading
system may show a note beside its reference. The heading's class,
footnotes-title, is how htmlrepair knows it on a page read again, where
Pandoc's reader would keep it and the section around it.

A note moved from a page in one language to a page in another keeps its
page's, lang on its item (lang and xml:lang on an EPUB's aside), and a
group's heading on the Notes page is in its title's language, as the
contents listings have it (bookcontents.entry_language).

Pandoc cannot be asked to start numbering at 7, so the numbers are
rewritten in the output: the reference's visible number, the note's
number, and the ids that tie them, which stay unique within whichever
page ends up holding the note. So do the ids of a moved note's code,
which Pandoc counts per page, and the page it moves to gets the CSS
Pandoc writes only on a page that holds code when it writes it. A
moved note's link to an id on its page names the page.

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

import highlighting
import languages as languages_lib
from bookcontents import entry_language, is_generated, numbered_title

# Pandoc's HTML writer and its EPUB writer mark the same things in the
# same classes; they differ in the container (an ol of li, or asides).
# Pandoc wraps a long tag's attributes across lines, so whitespace
# between them is any whitespace.
REF = re.compile(r'<a\s+href="([^"]*?)#fn(\d+)"\s+class="footnote-ref"\s+'
                 r'id="fnref(\d+)"([^>]*)>(<sup>)?(\d+)(</sup>)?</a>')
SECTION = re.compile(r'<section id="footnotes"[^>]*>.*?</section>\s*', re.S)
# A note's own item: no item of a list in a note has an id.
NOTE_ITEM = re.compile(r'<li id="fn(\d+)"[^>]*>')
ASIDE = re.compile(r'<aside[^>]*\bid="fn(\d+)"[^>]*>(.*?)</aside>\s*', re.S)
BACK = re.compile(r'href="([^"]*?)#fnref(\d+)"')
# Pandoc's ids for a code block and its lines (cb3, cb3-1), and a line's
# link to itself. Each page counts its code from cb1.
CODE_ID = re.compile(r'(\sid="|\shref="#)(cb\d+(?:-\d+)?)"')
ID = re.compile(r'\sid="([^"]+)"')
FRAGMENT = re.compile(r'(\shref=")#([^"]+)"')
NUMBER_SPAN = re.compile(r'<span class="footnote-number">\d+\.</span>')
# A notes section's rule, as Pandoc's HTML writer writes it, with no
# heading after it yet.
UNTITLED = re.compile(r'(<section id="footnotes"[^>]*>\s*<hr\s*/>)(?!\s*<h2\b)')
HEADING = '<h2 class="footnotes-title">%s</h2>'



def groups(tree, titles):
    """[(stem, key, title)] for each page the book's tree places, in
    reading order: its notes group's key, shared by the group's pages,
    and the group's title, numbered when the tree is. tree is the
    contents as bookcontents builds them, titles each page's own."""
    found = []

    def pages(entries):
        for entry in entries:
            if is_generated(entry):
                continue
            if entry[0] == "group":
                yield from pages(entry[2])
            else:
                yield entry[1]

    def walk(entries, path):
        for index, entry in enumerate(entries):
            kind, a, b = entry
            if is_generated(entry):
                continue
            key = path + (index,)
            if kind == "group" and getattr(entry, "type", None) == "part":
                walk(b, key)
            elif kind == "group":
                found.extend((stem, key, numbered_title(entry, a)) for stem in pages(b))
            else:
                found.append((a, key, numbered_title(entry, b or titles.get(a) or a)))
    walk(tree, ())
    return found


def title_languages(tree, titles, languages):
    """{group key: language} for each group whose title is in another
    language than the book's, as groups() keys them: languages gives the
    pages in one ({stem: language}), and a group's title is in its
    language as a contents listing's entry is (entry_language)."""
    found = {}
    if not languages:
        return found

    def walk(entries, path):
        for index, entry in enumerate(entries):
            if is_generated(entry):
                continue
            key = path + (index,)
            if entry[0] == "group" and getattr(entry, "type", None) == "part":
                walk(entry[2], key)
                continue
            language = entry_language(entry, titles, languages)
            if language:
                found[key] = language
    walk(tree, ())
    return found


class Page:
    """One rendered page: its text, where it sits in the book, and its
    language, its root's unless given (an EPUB's chapter file has the
    book's until the run marks it)."""

    def __init__(self, name, text, group, group_title, flavor, language=None):
        self.name = name                # what a link to it looks like
        self.text = text
        self.group = group              # a key shared by the group's pages
        self.group_title = group_title
        self.flavor = flavor            # "html" or "xhtml"
        self.notes = []                 # [(old number, item html)]
        self.language = language or languages_lib.html_language(
            text.split("<body", 1)[0] + "<body>")

    def take_notes(self):
        """Cut the notes out of the page, keeping them."""
        match = SECTION.search(self.text)
        if not match:
            return
        section = match.group(0)
        items = note_items(section) if self.flavor == "html" \
            else ASIDE.findall(section)
        self.notes = [(int(n), body) for n, body in items]
        self.text = self.text[:match.start()] + self.text[match.end():]


def note_items(section):
    """(number, body) for each note in the HTML writer's notes section:
    from a note's own item to the next one's, or to the section's last
    </ol>, less its closing </li>. So a list in a note ends where it
    ends: taken to the first </li> before an </ol>, a note holding a
    numbered list was cut off after the list's last item, its way back
    lost and the next note left inside its list."""
    starts = list(NOTE_ITEM.finditer(section))
    end = section.rfind("</ol>")
    items = []
    for index, start in enumerate(starts):
        stop = starts[index + 1].start() if index + 1 < len(starts) else end
        items.append((start.group(1), re.sub(r"</li>\s*$", "", section[start.end():stop])))
    return items


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
        if dest != page.name:
            # A note leaving its page takes its code's ids with it, named
            # for the note, so they're unique where it lands: notes from
            # two pages would each bring a cb1, and the page's own code
            # may have one.
            body = CODE_ID.sub(lambda m: f'{m.group(1)}{prefix}fn{new}-{m.group(2)}"', body)
            # And a link to an id on its page is a link to the page now.
            own = set(ID.findall(body))
            body = FRAGMENT.sub(lambda m: m.group(0) if m.group(2) in own
                                else f'{m.group(1)}{page.name}#{m.group(2)}"', body)
        rebuilt.append((new, body))
    page.notes = rebuilt
    return page


def _in_language(language, flavor):
    """The attributes that put an element in a language: lang, and
    xml:lang too in an EPUB's XHTML, as Pandoc's EPUB writer gives a
    chapter's root."""
    if not language:
        return ""
    value = html.escape(language, quote=True)
    return f' lang="{value}"' + (f' xml:lang="{value}"' if flavor == "xhtml" else "")


def render_notes(notes, flavor, prefix="", heading=None, heading_language=None):
    """The notes as one footnotes section in the writer's own shape, with
    a heading after its rule if one is given, in heading_language when
    that's given. A note (number, body, its language or None) is in its
    language when one's given, as a note moved from a page in another
    language than the one it's put on is."""
    if not notes:
        return ""
    notes = [(n[0], n[1], n[2] if len(n) > 2 else None) for n in notes]
    head = (HEADING.replace('">', '"%s>' % _in_language(heading_language, flavor), 1)
            % html.escape(heading) + "\n") if heading else ""
    if flavor == "html":
        items = "\n".join(f'<li id="{prefix}fn{n}" value="{n}"{_in_language(lang, flavor)}>'
                          f'{body}</li>' for n, body, lang in notes)
        return (f'<section id="{prefix}footnotes" class="footnotes '
                'footnotes-end-of-document" role="doc-endnotes">\n<hr />\n'
                f'{head}<ol>\n{items}\n</ol>\n</section>\n')
    items = "\n".join(
        f'<aside epub:type="footnote" role="doc-footnote" '
        f'id="{prefix}fn{n}"{_in_language(lang, flavor)}>{body}</aside>'
        for n, body, lang in notes)
    return (f'<section id="{prefix}footnotes" class="footnotes '
            'footnotes-end-of-document" epub:type="footnotes">\n<hr />\n'
            f'{head}{items}\n</section>\n')


def titled(text, title):
    """An HTML page with its notes section headed (notes.title), as
    Pandoc's writer leaves it without a heading."""
    if not title:
        return text
    return UNTITLED.sub(lambda m: m.group(1) + "\n" + HEADING % html.escape(title), text)


def insert_before_end(text, block, flavor):
    """Put a block at the end of the page's content: in a page's main
    landmark, before its footer, where it has one; in an EPUB's chapter
    file, in its last section, before the footer setting's <footer>
    after it (pagefooter)."""
    if flavor == "html":
        marker = "</main>" if "</main>" in text else "</body>"
    else:
        marker = "</section>\n</body>"
        footer = re.search(r"</section>\s*<footer>(?:(?!<footer[\s>]).)*</footer>\s*</body>",
                           text, re.S)
        if footer:
            marker = footer.group(0)
    at = text.rfind(marker)
    if at < 0:
        at = text.rfind("</body>")
    return text[:at] + block + text[at:] if at >= 0 else text + block


def arrange(pages, numbering, placement, notes_page=None, title=None, title_languages=None):
    """Apply the two settings to a book's pages, in reading order.

    pages: [Page]; notes_page: a Page to hold everything when placement
    is "book" (its text gets the sections, each headed by its group, in
    the group title's language when title_languages, {group key:
    language}, gives one). title: the heading of each page's notes
    (notes.title), given for HTML pages and not for an EPUB's chapter
    files. A note moved to a page in another language than its own keeps
    its page's. Returns the pages whose text changed.
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

    def moved(page, holder):
        """A page's notes as they go to holder's page, each in the page's
        language when holder's is another."""
        own = page.language
        keep = own if own and holder is not None and holder.language \
            and not languages_lib.same_tag(own, holder.language) else None
        return [(n, body, keep) for n, body in page.notes]

    # Notes gathered in one list are numbered across their group.
    continuing = numbering == "group" or placement != "page"
    book_sections = []
    for index, (key, group_title, members) in enumerate(groups, 1):
        offset = 0
        gathered = []
        prefix = f"g{index}-" if placement == "book" else ""
        dest = members[-1].name if placement == "group" else \
            (notes_page.name if placement == "book" else None)
        holder = members[-1] if placement == "group" else notes_page
        for page in members:
            page_offset = offset if continuing else 0
            renumber(page, page_offset, dest or page.name, prefix)
            if page.notes:
                changed.append(page)
            if continuing:
                offset += len(page.notes)
            if placement == "page":
                page.text = insert_before_end(
                    page.text, render_notes(page.notes, page.flavor, heading=title),
                    page.flavor)
            else:
                gathered.extend(moved(page, holder))
        if placement == "group" and gathered:
            last = members[-1]
            last.text = insert_before_end(
                last.text, render_notes(gathered, last.flavor, heading=title), last.flavor)
            if last not in changed:
                changed.append(last)
        elif placement == "book" and gathered:
            heading_language = (title_languages or {}).get(key)
            if heading_language and notes_page.language and languages_lib.same_tag(
                    heading_language, notes_page.language):
                heading_language = None
            book_sections.append(render_notes(
                gathered, notes_page.flavor, prefix, heading=group_title,
                heading_language=heading_language))
    if placement == "book" and notes_page is not None and book_sections:
        notes_page.text = insert_before_end(
            notes_page.text, "".join(book_sections), notes_page.flavor)
        changed.append(notes_page)
    for page in changed:
        page.text = highlighting.with_page_css(page.text)
    return changed
