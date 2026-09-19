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
    for stem, parents, position, _ in members:
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


def group_pieces(tree, pieces, titles, roles=None):
    """Replace each source stem in a guessed tree with a group holding the
    source's own page (when it has one) and its pieces, nested by the
    headings above them."""
    out = []
    for node in tree:
        explicit = None
        if isinstance(node, dict) and "items" not in node:
            # A page entry with a role. If it is a split source, its
            # pieces still belong under it.
            if node.get("page") in pieces:
                explicit, node = node.get("role"), node["page"]
            else:
                out.append(node)
                continue
        if isinstance(node, dict):
            node = dict(node)
            node["items"] = group_pieces(node["items"], pieces, titles, roles)
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
            group = {"title": titles.get(node) or stem_title(node),
                     "items": items, "source": node}
            # The source's markers say what part of the book it is; a
            # name that says so is the fallback.
            role = explicit or next((m[3] for m in ordered if m[3]), "") \
                or (roles or {}).get(node, "") or matter_role(node)
            if role in ("front", "appendix", "back"):
                group["role"] = role
            out.append(group)
        else:
            out.append(node)
    return out


def strip_source(tree):
    """Drop the bookkeeping key group_pieces leaves on a group."""
    for node in tree:
        if isinstance(node, dict) and "items" in node:
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
# A word in a file name that says where the page belongs, whatever the
# rest of the name is: "_preamble", "Z1 Glossary", "A3 Appendix Tables".
FRONT_WORDS = {"frontmatter", "preamble", "preface", "foreword", "titlepage",
               "about"}
BACK_WORDS = {"notes", "index", "references", "bibliography", "glossary",
              "solutions", "appendix", "backmatter", "colophon"}


def matter_role(stem):
    """front, back, or middle, from the words of a file name. A leading
    underscore is the Pandoc-book convention for a preamble."""
    if stem.startswith("_"):
        return "front"
    words = set(re.split(r"[^a-z0-9]+", stem.lower()))
    if words & FRONT_WORDS:
        return "front"
    if words & BACK_WORDS:
        return "back"
    return "middle"


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


def guess_contents(stems, back_matter=None, titles=None, parts=None,
                   roles=None):
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
    roles = roles or {}          # stem -> role, for a page that was not split

    pieces = {}
    plain = []
    for stem in stems:
        if stem in parts:
            padded = tuple(parts[stem]) + (None, "", "", "")
            source, number, parents, position = padded[:4]
            role = padded[5] if len(padded) > 5 else ""
        elif piece_source(stem):
            source, number, parents, position, role = (piece_source(stem),
                                                       None, None, "", "")
        else:
            plain.append(stem)
            continue
        pieces.setdefault(source, []).append(
            (number, stem, parents or [], position or "", role or ""))
    if pieces:
        ordered = {}
        for source, members in pieces.items():
            members.sort(key=lambda m: (m[0] is None, m[0] or 0,
                                        natural_key(m[1])))
            ordered[source] = (source in plain,
                               [(m[1], m[2], m[3], m[4]) for m in members])
        stems = plain + [s for s in ordered if s not in plain]
        tree = strip_source(group_pieces(
            guess_contents(stems, back_matter, titles, None, roles), ordered,
            titles, roles))
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

    # Not enough structure to be worth grouping: a plain order, with what
    # the names say is front or back matter first and last.
    grouped_pages = sum(len(v) for v in chapters.values())
    if len(chapters) < 2 or grouped_pages < max(3, len(stems) // 4):
        by_role = {"front": [], "middle": [], "back": [], "appendix": []}
        for stem in sorted(stems, key=natural_key):
            by_role[roles.get(stem) or matter_role(stem)].append(stem)
        return ([{"page": s, "role": "front"} for s in by_role["front"]]
                + by_role["middle"]
                + [{"page": s, "role": "appendix"} for s in by_role["appendix"]]
                + [{"page": s, "role": "back"} for s in by_role["back"]])

    front = [s for s in loose if s.lower().startswith(FRONT_MATTER)
             or matter_role(s) == "front"]
    tail = [s for s in loose
            if (s.lower().startswith(BACK_MATTER_PAGES)
                or matter_role(s) == "back") and s not in front]
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




ROLES = ("front", "main", "appendix", "back")
GENERATED = {"toc": ("toc", "Contents")}       # kind -> (default name, title)


class Entry(tuple):
    """A tree record, ("group", title, children) or ("page", stem, title),
    that also carries what a plain tuple could not: its role, its
    number once numbering has run, and what generates it. Unpacking as
    kind, a, b still works everywhere."""

    def __new__(cls, record, role=None, generate=None):
        self = tuple.__new__(cls, record)
        self.role = role
        self.generate = generate
        self.number = None
        return self


def walk_contents(nodes, available, used, problems, depth=0,
                  suffix=".html", inherited=None):
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

        role = node.get("role")
        if role is not None and role not in ROLES:
            problems.append(f"role {role!r} is not one of "
                            + ", ".join(ROLES))
            role = None
        role = role or inherited          # a page under a front group is front
        if "generate" in node:
            kind = str(node["generate"])
            if kind not in GENERATED:
                problems.append(f"cannot generate {kind!r}; known: "
                                + ", ".join(GENERATED))
                continue
            name = str(node.get("name") or GENERATED[kind][0])
            if name in used:
                problems.append(f"page listed more than once: {name}")
                continue
            used.add(name)
            out.append(Entry(("page", name,
                              node.get("title") or GENERATED[kind][1]),
                             role=role, generate=kind))
            continue
        if "items" in node:
            children = walk_contents(node["items"], available, used,
                                     problems, depth + 1, suffix, role)
            if depth >= 2:
                problems.append(
                    f"group '{node.get('title', '')}' nests more than three "
                    "levels deep; some LMSs flatten this")
            out.append(Entry(("group", node.get("title", ""), children),
                             role=role))
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
        out.append(Entry(("page", stem, node.get("title")), role=role))
    return out




def role_of(entry):
    return getattr(entry, "role", None) or "main"


def is_generated(entry):
    return getattr(entry, "generate", None)


def letter(n):
    """1 -> A, 26 -> Z, 27 -> AA."""
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def number_tree(tree, titles=None):
    """Give each entry its number, the way a printed book counts.

    Top-level groups and pages with the main role count 1, 2, 3 and
    appendices A, B; front and back matter and generated pages get none.
    Inside a numbered group its pages count N.1, N.2, except the group's
    own opening page (titled as the group is), which takes the group's
    number. Numbers are set on the entries; nothing else changes."""
    titles = titles or {}
    main = appendix = 0
    for entry in tree:
        entry.number = None
        if is_generated(entry) or role_of(entry) in ("front", "back"):
            continue
        if role_of(entry) == "appendix":
            appendix += 1
            entry.number = letter(appendix)
        else:
            main += 1
            entry.number = str(main)
        if entry[0] == "group":
            count = 0
            for child in entry[2]:
                child.number = None
                if child[0] != "page" or is_generated(child):
                    continue
                own = (child[2] or titles.get(child[1]))
                if count == 0 and own and own == entry[1]:
                    child.number = entry.number      # the opening page
                    continue
                count += 1
                child.number = f"{entry.number}.{count}"
    return tree


def numbered_title(entry, title):
    """The title with its number in front, when it has one."""
    number = getattr(entry, "number", None)
    return f"{number} {title}" if number and title else title


def toc_blocks(tree, titles, link_for):
    """The tree as Pandoc blocks: a nested bullet list of links, one
    entry per page or group, numbered when numbering has run. link_for
    maps a page stem to the target a link should carry for the output
    being written (page.html, #page-stem, page.md); a group with no page
    of its own links to its first page."""
    def inlines(text):
        out = []
        for index, word in enumerate(text.split()):
            if index:
                out.append({"t": "Space"})
            out.append({"t": "Str", "c": word})
        return out

    def link(text, target):
        return {"t": "Link", "c": [["", [], []], inlines(text), [target, ""]]}

    def items(nodes):
        out = []
        for entry in nodes:
            kind, a, b = entry
            if kind == "page":
                if is_generated(entry) and is_generated(entry) == "toc":
                    continue                 # the contents page itself
                text = numbered_title(entry, b or titles.get(a) or a)
                out.append([{"t": "Plain", "c": [link(text, link_for(a))]}])
            else:
                first = next((s for s in flatten_pages(b)
                              if not any(is_generated(e) and e[1] == s
                                         for e in b)), None)
                text = numbered_title(entry, a)
                head = [link(text, link_for(first))] if first else inlines(text)
                item = [{"t": "Plain", "c": head}]
                # A group's own opening page is the group line; listing it
                # again below would repeat the chapter.
                rest = b
                if b and b[0][0] == "page" and not is_generated(b[0]) \
                        and (b[0].number == entry.number
                             or (b[0][2] or titles.get(b[0][1])) == a):
                    rest = b[1:]
                children = items(rest)
                if children:
                    item.append({"t": "BulletList", "c": children})
                out.append(item)
        return out

    return [{"t": "BulletList", "c": items(tree)}]


def flatten_pages(tree):
    for kind, a, b in tree:
        if kind == "page":
            yield a
        else:
            yield from flatten_pages(b)




def contents_from_tree(tree):
    """The YAML shape of a tree, roles and generated pages included."""
    out = []
    for entry in tree:
        kind, a, b = entry
        role = getattr(entry, "role", None)
        generate = getattr(entry, "generate", None)
        if generate:
            node = {"generate": generate}
            if a != GENERATED[generate][0]:
                node["name"] = a
            if b and b != GENERATED[generate][1]:
                node["title"] = b
        elif kind == "group":
            node = {"title": a, "items": contents_from_tree(b)}
        elif b:
            node = {"page": a, "title": b}
        else:
            node = a
        if role and role != "main":
            if not isinstance(node, dict):
                node = {"page": node}
            node["role"] = role
        out.append(node)
    return out
