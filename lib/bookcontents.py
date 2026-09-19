"""
bookcontents.py -- the book's structure: the contents tree, and the guess
made from filenames when no tree is declared.

Shared by both halves of the pipeline. project.contents is declared once
because a cartridge organisation and an EPUB table of contents are the
same structure expressed twice, and the code that reads and guesses it has
to be shared for the same reason: two copies would drift, and then the
two outputs would disagree about the order of the book.

Nothing here reads a page. The packager passes the titles it took from
each page's <title>, the EPUB assembler the ones from each intermediate's
metadata, and the guess uses whatever it is given.

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
import re


# The order back matter appears in within a chapter. Different books use
# different names for these -- Statistics has "chapter-review" and
# "homework", Economics has "key-concepts-and-summary" and "problems" -- so
# this is the union of both, and anything unrecognised is sorted after the
# names listed here and reported rather than silently misplaced.
#
# Override it in the config with:
#   grouping:
#     back_matter: [key-terms, summary, exercises]
BACK_MATTER_ORDER = [
    "key-terms",
    "chapter-review",
    "key-concepts-and-summary",
    "formula-review",
    "practice",
    "self-check-questions",
    "review-questions",
    "critical-thinking-questions",
    "bringing-it-together-practice",
    "homework",
    "bringing-it-together-homework",
    "problems",
    "references",
    "solutions",
]



def slugify(text):
    """Filename form of an outline title.

    OpenStax names its files after its headings, so "Key Concepts and
    Summary" is "key-concepts-and-summary" and "Self-Check Questions" is
    "self-check-questions". Deriving the name rather than listing known
    headings is what lets one rule serve books that use different words
    for the same sections.
    """
    text = clean_title(text).lower()
    text = re.sub(r"['\u2019\u2018`]", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def clean_title(text):
    """Unescape entities and drop the invisible characters Word leaves."""
    text = html_module.unescape(text)
    text = re.sub(r"[\u200b\u200c\u200d\ufeff\u00ad]", "", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return " ".join(text.split())


# What separates a source's name from a piece's in a split page:
# chapter-7--economies-of-scale. Reserved: split-pages.py refuses a source
# whose own name contains it.
PIECE_SEPARATOR = "--"


def piece_source(stem):
    """The source a piece was cut from, judged by its name alone, or None.

    A caller that has read the piece's own provenance -- the source-page
    and page-part metadata every piece carries -- should prefer that; the
    name is the fallback for pages made somewhere else.
    """
    if PIECE_SEPARATOR not in stem:
        return None
    return stem.split(PIECE_SEPARATOR, 1)[0]


def nest_pieces(members, titles):
    """Arrange a source's pieces by the headings above them.

    members are (stem, parents, position) in reading order: parents the
    titles of the cut headings enclosing each, position its place among
    them ("3.2"), which is what keeps two chapters' "Introduction"
    groups apart. A heading that is itself a page --
    the H1 with an introduction under it -- is the first item of the
    group that holds its sections; a heading that is not a page is a
    group all the same, since its sections carry its title.
    """
    root = []
    groups = {}                     # position prefix -> item list
    for stem, parents, position in members:
        container = root
        steps = position.split(".") if position else []
        for depth, title in enumerate(parents):
            path = tuple(steps[:depth + 1])
            if path not in groups:
                group = {"title": title, "items": []}
                # The heading's own page, placed just before, opens it.
                if container and isinstance(container[-1], str) \
                        and titles.get(container[-1]) == title:
                    group["items"].append(container.pop())
                container.append(group)
                groups[path] = group["items"]
            container = groups[path]
        container.append(stem)
    return root


def group_pieces(tree, pieces, titles):
    """Replace each source stem in a guessed tree with a group holding the
    source's own page (when it has one) and its pieces, nested by the
    headings above them."""
    out = []
    for node in tree:
        if isinstance(node, dict):
            node = dict(node)
            node["items"] = group_pieces(node["items"], pieces, titles)
            # A chapter whose only page is a split source would nest one
            # group inside another with nothing else in either. Keep the
            # chapter's heading unless it is the bare fallback and the
            # source has a real title.
            only = node["items"][0] if len(node["items"]) == 1 else None
            if (isinstance(only, dict) and len(node.get("items", [])) == 1
                    and only.get("source")):
                if re.match(r"^Chapter \d+$", node.get("title", "")) \
                        and only["source"] in titles:
                    node["title"] = only["title"]
                node["items"] = only["items"]
            out.append(node)
        elif node in pieces:
            source_page, ordered = pieces[node]
            items = ([node] if source_page else []) + \
                nest_pieces(ordered, titles)
            out.append({"title": titles.get(node) or stem_title(node),
                        "items": items, "source": node})
        else:
            out.append(node)
    return out


def strip_source(tree):
    """Drop the bookkeeping key group_pieces leaves on a group."""
    for node in tree:
        if isinstance(node, dict):
            node.pop("source", None)
            strip_source(node["items"])
    return tree


def stem_title(stem):
    """A readable title for a page that has none of its own."""
    return stem.replace("-", " ").replace("_", " ").title()


def natural_key(text):
    """Sort key where runs of digits compare numerically.

    Plain sort puts chapter 10 between chapters 1 and 2, which scrambles a
    book. This keeps 1-1, 1-2, 2-1, 10-1 in the order a reader expects.
    """
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", text)]


def chapter_of(stem):
    """Chapter number this page belongs to, or None.

    Two shapes carry it: a numeric prefix ("12-3-...", "12-key-terms") and
    a chapter opener page ("chapter-12"). Everything else -- appendices,
    preface, index -- has no chapter.
    """
    m = re.match(r"^chapter-(\d+)$", stem)
    if m:
        return int(m.group(1))
    m = re.match(r"^(\d+)-", stem)
    if m:
        return int(m.group(1))
    return None


def within_chapter_key(stem, back_matter):
    """Sort key for one page inside its chapter.

    Opener, then introduction, then numbered sections in order, then back
    matter in the configured order, then anything unrecognised.
    """
    if re.match(r"^chapter-\d+$", stem):
        return (0, 0, "")

    tail = re.sub(r"^\d+-", "", stem)

    # "1-introduction" and "1-introduction-to-choice-in-a-world-of-scarcity"
    # are the same thing under different naming conventions.
    if tail == "introduction" or tail.startswith("introduction-to-"):
        return (1, 0, "")

    m = re.match(r"^(\d+)-", tail)
    if m:
        return (2, int(m.group(1)), "")

    if tail in back_matter:
        return (3, back_matter.index(tail), "")

    # Unrecognised: after the known back matter, alphabetically, and
    # reported so the name can be added to the configured order.
    return (4, 0, tail)


def unrecognised_roles(stems, back_matter):
    """Chapter pages whose role name is not in the configured order."""
    found = set()
    for stem in stems:
        if chapter_of(stem) is None:
            continue
        if within_chapter_key(stem, back_matter)[0] == 4:
            found.add(re.sub(r"^\d+-", "", stem))
    return sorted(found)




FRONT_MATTER = ("frontmatter", "front-matter", "preface", "about", "titlepage")
BACK_MATTER_PAGES = ("notes", "index", "references", "bibliography", "glossary",
                     "solutions", "answer-key")


# Words that stay lowercase inside a derived heading unless they lead it.
MINOR_WORDS = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "of",
               "on", "or", "the", "to", "with", "versus", "vs"}


def title_from_slug(slug):
    """Turn "choice-in-a-world-of-scarcity" into "Choice in a World of
    Scarcity" -- readable enough for a heading you are going to review."""
    words = [w for w in slug.split("-") if w]
    out = []
    for index, word in enumerate(words):
        if index > 0 and word in MINOR_WORDS:
            out.append(word)
        elif len(word) <= 3 and word.isupper():
            out.append(word)
        else:
            out.append(word[:1].upper() + word[1:])
    return " ".join(out)


def chapter_heading(number, pages, titles):
    """Best available heading for a chapter group.

    An introduction page named after its subject gives the chapter's real
    title -- "Introduction to Choice in a World of Scarcity" is chapter 2's
    heading with three words removed. That is preferred over a
    "chapter-12" page, whose title varies by book: sometimes the chapter
    opener, sometimes the answer key for it.
    """
    for page in pages:
        if not re.match(rf"^{number}-introduction", page):
            continue

        # The page's own title when it has a real one.
        m = re.match(r"^introduction to (?:the\s+)?(.+)$",
                     titles.get(page, ""), re.I)
        if m:
            return f"Chapter {number} {m.group(1)}"

        # Otherwise the filename, which carries the same words. Pages whose
        # source has no H1 end up titled after the file, so the title is no
        # better a source than the name itself.
        m = re.match(rf"^{number}-introduction-to-(?:the-)?(.+)$", page)
        if m:
            return f"Chapter {number} {title_from_slug(m.group(1))}"

    opener = next((p for p in pages if re.match(r"^chapter-\d+$", p)), None)
    if opener and titles.get(opener):
        return titles[opener]

    return f"Chapter {number}"


def guess_contents(stems, back_matter=None, titles=None, parts=None):
    """Best-effort contents tree from filenames alone.

    parts maps a piece's stem to (source stem, part number, parent
    titles, position) when the caller has read that from the page; otherwise
    pieces are recognised by the separator in their names and ordered by
    name, which is right only by luck. Either way the pieces of a source are grouped under
    it, with the source's own page first when it has one, and the group
    then takes the source's place in whatever chapter grouping applies.

    Chapter grouping only fires when the filenames actually encode it.
    "BC-01".."BC-16" have no internal structure and stay flat; OpenStax
    names like "12-3-the-f-distribution" and "chapter-12" group.

    Detection is by shape, not by vocabulary: anything with a numeric
    chapter prefix belongs to that chapter, whatever the rest of the name
    says. Only the *order* of back matter within a chapter depends on
    knowing the names, and unrecognised ones sort last rather than
    preventing the grouping.
    """
    back_matter = back_matter or BACK_MATTER_ORDER
    titles = titles or {}
    parts = parts or {}

    pieces = {}
    plain = []
    for stem in stems:
        if stem in parts:
            source, number, parents, position = \
                (tuple(parts[stem]) + (None, ""))[:4]
        elif piece_source(stem):
            source, number, parents, position = (piece_source(stem), None,
                                                 None, "")
        else:
            plain.append(stem)
            continue
        pieces.setdefault(source, []).append(
            (number, stem, parents or [], position or ""))
    if pieces:
        ordered = {}
        for source, members in pieces.items():
            members.sort(key=lambda m: (m[0] is None, m[0] or 0,
                                        natural_key(m[1])))
            ordered[source] = (source in plain,
                               [(m[1], m[2], m[3]) for m in members])
        stems = plain + [s for s in ordered if s not in plain]
        tree = strip_source(group_pieces(
            guess_contents(stems, back_matter, titles), ordered, titles))
        # A book that is one source is the source: a group for it would
        # only push every page one level down.
        if len(tree) == 1 and isinstance(tree[0], dict) \
                and len(ordered) == 1 and not [s for s in plain
                                               if s not in ordered]:
            return tree[0]["items"]
        return tree

    chapters = {}
    loose = []
    for stem in stems:
        number = chapter_of(stem)
        if number is None:
            loose.append(stem)
        else:
            chapters.setdefault(number, []).append(stem)

    # Not enough structure to be worth grouping.
    grouped_pages = sum(len(v) for v in chapters.values())
    if len(chapters) < 2 or grouped_pages < max(3, len(stems) // 4):
        return sorted(stems, key=natural_key)

    front = [s for s in loose if s.lower().startswith(FRONT_MATTER)]
    tail = [s for s in loose
            if s.lower().startswith(BACK_MATTER_PAGES) and s not in front]
    middle = [s for s in loose if s not in front and s not in tail]

    tree = sorted(front, key=natural_key)

    for number in sorted(chapters):
        pages = sorted(chapters[number],
                       key=lambda s: within_chapter_key(s, back_matter))
        tree.append({"title": chapter_heading(number, pages, titles),
                     "items": pages})

    tree.extend(sorted(middle, key=natural_key))
    tree.extend(sorted(tail, key=natural_key))
    return tree




def walk_contents(nodes, available, used, problems, depth=0,
                  suffix=".html"):
    """Normalise the configured tree into (kind, ...) records.

    available is the set of page stems that exist; suffix is only used to
    name a missing one in the way the caller's directory would show it,
    since the packager works from .html files and the EPUB assembler from
    the filtered .json intermediates.
    """
    out = []
    for node in nodes:
        if isinstance(node, str):
            node = {"page": node}
        if not isinstance(node, dict):
            problems.append(f"contents entry is not a page or a group: {node!r}")
            continue

        if "items" in node:
            children = walk_contents(node["items"], available, used,
                                     problems, depth + 1, suffix)
            if depth >= 2:
                problems.append(
                    f"group '{node.get('title', '')}' nests more than three "
                    "levels deep; some LMSs flatten this")
            out.append(("group", node.get("title", ""), children))
            continue

        stem = str(node.get("page", "")).strip()
        if stem.endswith(".html"):
            stem = stem[:-5]           # a config may name the file, not the stem
        if not stem:
            problems.append("contents entry has no page name")
            continue
        if stem not in available:
            problems.append(f"page listed in contents but not on disk: "
                            f"{stem}{suffix}")
            continue
        if stem in used:
            problems.append(f"page listed more than once: {stem}{suffix}")
            continue
        used.add(stem)
        out.append(("page", stem, node.get("title")))
    return out




def flatten_pages(tree):
    for kind, a, b in tree:
        if kind == "page":
            yield a
        else:
            yield from flatten_pages(b)




def contents_from_tree(tree):
    """Turn the resolved tree back into plain YAML-shaped data."""
    out = []
    for kind, a, b in tree:
        if kind == "page":
            out.append(a if not b else {"page": a, "title": b})
        else:
            out.append({"title": a, "items": contents_from_tree(b)})
    return out
