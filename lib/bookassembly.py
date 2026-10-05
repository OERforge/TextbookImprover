"""
bookassembly.py -- a book's pages, read from the filtered intermediates
and assembled into one Pandoc document, for the writers that make one
file of a whole book (EPUB, PDF).

The pages are placed by project.contents, the same tree the cartridge
organization is built from, or by the packager's filename guess when
there is none. A group -- a chapter, a unit, whatever the author calls
it -- becomes a heading, a page a heading at its depth, and the page's
own headings continue below it. Every id in a page takes the page's
prefix, so two pages' "Key Terms" headings don't collide in one book.

What differs between the writers stays with them: the EPUB numbers
titles itself and places a generated contents page as a list of links;
the PDF lets LaTeX number and places \\tableofcontents.

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

import copy
import json
import os
import re
import sys

import oerconfig
from bookcontents import (
    guess_contents, walk_contents, flatten_pages, natural_key, stem_title,
    expand_split_sources, is_generated, numbered_title, toc_blocks,
)

LIB = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(os.path.dirname(LIB), "bin")
CONFIG_NAME = "conversion.yaml"
PROJECT_NAME = "project.yaml"
INTERMEDIATE = ".filtered.json"

# Attributes whose value is a list of ids, kept in step when ids are
# prefixed. headers is what a cell uses to name its header cells when
# scope cannot express the relationship.
ID_LIST_ATTRIBUTES = {"headers", "aria-labelledby", "aria-describedby"}


def page_id(stem):
    """The id a page's heading gets, and the prefix its ids take. A stem
    is a file name and may hold a space; an id may not."""
    return "page-" + re.sub(r"[^\w.-]+", "-", stem)


# --------------------------------------------------------------------------
# reading the intermediates
# --------------------------------------------------------------------------

def page_stems(base):
    return sorted((f[:-len(INTERMEDIATE)] for f in os.listdir(base)
                   if f.endswith(INTERMEDIATE)), key=natural_key)


def load_page(base, stem):
    with open(os.path.join(base, stem + INTERMEDIATE), encoding="utf-8") as fh:
        return json.load(fh)


def stringify(node):
    """The text of an inline tree, as Pandoc's stringify would give it."""
    if isinstance(node, dict):
        kind = node.get("t")
        if kind == "Str":
            return node["c"]
        if kind in ("Space", "SoftBreak", "LineBreak"):
            return " "
        if kind in ("Code", "Math"):
            return node["c"][1]
        if kind in ("RawInline", "Note"):
            return ""
        return stringify(node.get("c", []))
    if isinstance(node, list):
        return "".join(stringify(child) for child in node)
    return ""


def meta_text(meta, key):
    value = meta.get(key)
    if not value:
        return ""
    if value.get("t") == "MetaString":
        return value["c"]
    return " ".join(stringify(value.get("c", [])).split())


def page_title(doc, stem):
    """The page's title from its metadata, falling back to the filename.

    With promote_h1_to_title in effect the filter has moved the page's
    heading here, which is why the intermediate usually opens without one.
    """
    return meta_text(doc.get("meta", {}), "title") or stem_title(stem)


def inlines(text):
    """Str and Space inlines for a plain string."""
    out = []
    for index, word in enumerate(text.split()):
        if index:
            out.append({"t": "Space"})
        out.append({"t": "Str", "c": word})
    return out


def title_heading_inlines(doc):
    """The page's title heading as it said itself, when the filter took it
    out of the body (title-heading), or None."""
    value = (doc.get("meta") or {}).get("title-heading")
    if isinstance(value, dict) and value.get("t") == "MetaInlines":
        return copy.deepcopy(value["c"])
    return None


def header(level, content, identifier):
    return {"t": "Header", "c": [level, [identifier, [], []], content]}


# --------------------------------------------------------------------------
# rewriting a page for its place in the book
# --------------------------------------------------------------------------

def is_attr(value):
    """Pandoc's Attr is the only three-element list that starts with a
    string and continues with a list of strings and a list of pairs."""
    return (isinstance(value, list) and len(value) == 3
            and isinstance(value[0], str)
            and isinstance(value[1], list)
            and all(isinstance(c, str) for c in value[1])
            and isinstance(value[2], list)
            and all(isinstance(kv, list) and len(kv) == 2
                    and isinstance(kv[0], str) and isinstance(kv[1], str)
                    for kv in value[2]))


def prefix_ids(node, prefix, pages=()):
    """Give every id in a page the page's prefix, and every link to one
    the same, so that two pages with a "Key Terms" heading do not collide
    once they share a book. Pandoc rewrites #id links to the chapter file
    holding the id by its first occurrence, so a collision would send a
    link to the wrong page without a word.

    A link to another page of the book -- <stem>.html or <stem>.html#id,
    which is how split-pages.py links the pieces of a source -- becomes
    a link into the book the same way, so it resolves to that page's
    chapter file instead of to a file the EPUB does not contain."""
    if isinstance(node, dict):
        if node.get("t") == "Link":
            target = node["c"][2]
            url = target[0]
            if url.startswith("#") and len(url) > 1:
                target[0] = "#" + prefix + url[1:]
            elif url.endswith(".html") and url[:-5] in pages:
                target[0] = "#" + page_id(url[:-5])
            elif ".html#" in url and url.split(".html#", 1)[0] in pages:
                stem, fragment = url.split(".html#", 1)
                target[0] = "#" + page_id(stem) + "--" + fragment
        for value in node.values():
            prefix_ids(value, prefix, pages)
    elif is_attr(node):
        if node[0]:
            node[0] = prefix + node[0]
        for pair in node[2]:
            if pair[0] in ID_LIST_ATTRIBUTES and pair[1].strip():
                pair[1] = " ".join(prefix + token
                                   for token in pair[1].split())
    elif isinstance(node, list):
        for value in node:
            prefix_ids(value, prefix, pages)


def strip_comments(node):
    """Raw HTML comments, dropped. The filter drops them for every
    target now; this still matters for a hand-written page, which is
    read into an intermediate without the filter, and a comment
    holding "--" is fatal in XHTML, which is what an EPUB is made of."""
    if isinstance(node, dict):
        for key, value in list(node.items()):
            if isinstance(value, list):
                node[key] = [v for v in value if not is_comment(v)]
                for v in node[key]:
                    strip_comments(v)
            elif isinstance(value, dict):
                strip_comments(value)
    elif isinstance(node, list):
        node[:] = [v for v in node if not is_comment(v)]
        for v in node:
            strip_comments(v)


def is_comment(node):
    return (isinstance(node, dict) and node.get("t") in ("RawInline",
                                                          "RawBlock")
            and isinstance(node.get("c"), list) and len(node["c"]) == 2
            and node["c"][0] in ("html", "html5", "html4")
            and node["c"][1].lstrip().startswith("<!--"))


def shift_headers(node, by):
    if isinstance(node, dict):
        if node.get("t") == "Header":
            node["c"][0] = min(6, node["c"][0] + by)
        for value in node.values():
            shift_headers(value, by)
    elif isinstance(node, list):
        for value in node:
            shift_headers(value, by)


def opens_with_h1(blocks):
    return bool(blocks) and blocks[0].get("t") == "Header" \
        and blocks[0]["c"][0] == 1


def count_images(node, found):
    """Tally images and the ones with no alternative text.

    An image the filter marked decorative -- alt="" with
    aria-hidden="true" (role="presentation" in older intermediates) --
    has been described, as having nothing to say. An image with an empty
    alt and no such marker has not.
    """
    if isinstance(node, dict):
        if node.get("t") == "Image":
            attr, alt, _ = node["c"]
            found["images"] += 1
            decorative = ["aria-hidden", "true"] in attr[2] \
                or ["role", "presentation"] in attr[2]
            if not decorative and not stringify(alt).strip():
                found["without_alt"] += 1
        elif node.get("t") == "Math":
            found["math"] += 1
        elif node.get("t") == "Note":
            found["notes"] += 1
        for value in node.values():
            count_images(value, found)
    elif isinstance(node, list):
        for value in node:
            count_images(value, found)


def wants_title_page(setting, tree, assembly):
    """title_page for an EPUB or PDF: on and off as said; auto by the
    book's structure, not its number of files. A book with more than one
    top-level entry of its own (chapters, parts) gets one; a book that is
    one page gets one when that page has more than one top-level heading,
    or something before its title heading (a byline, a subtitle), as a
    title page would; otherwise none, the title then in the file's
    metadata only."""
    if setting in ("on", "off"):
        return setting == "on"
    entries = [e for e in tree if not is_generated(e)]
    if len(entries) > 1:
        return True
    tops = [b for b in assembly.blocks if b.get("t") == "Header" and b["c"][0] == 1]
    if len(tops) > 1:
        return True
    return assembly.title_preceded


class Assembly:
    """The book being built: blocks, and what was learned building them."""

    def __init__(self, base, pages, tree=(), titles=None):
        self.base = base
        self.tree = tree
        self.titles = titles or {}
        self.book_pages = frozenset(pages)   # stems a link may point at
        self.blocks = []
        self.depth = 1              # deepest heading level a page sits at
        self.pages = []
        self.found = {"images": 0, "without_alt": 0, "math": 0, "notes": 0}
        self.groups = {}             # page stem -> (group key, group title)
        self.notes_placed = False    # the Notes chapter, where contents put it
        self.title_preceded = False  # a one-page book's title heading had something before it
        self.aliases = {}            # a page heading's own id -> the page's id

    def add_tree(self, tree, depth=1):
        for index, entry in enumerate(tree):
            kind, a, b = entry
            self.before_entry(entry, depth)
            if is_generated(entry):
                self.add_generated(entry, depth)
                continue
            if kind == "page" and a == "notes" and not os.path.exists(
                    os.path.join(self.base, "notes" + INTERMEDIATE)):
                # The Notes chapter, placed where contents lists it and
                # filled after the writer runs.
                self.blocks.append(header(depth, inlines(b or "Notes"),
                                          page_id("notes")))
                self.notes_placed = True
                continue
            if depth == 1:
                # A top-level group is a notes group; so is a top-level
                # page, on its own.
                key = f"top-{index}"
                if kind == "group":
                    for stem in flatten_pages([(kind, a, b)]):
                        self.groups[stem] = (key, a)
                else:
                    doc = load_page(self.base, a)
                    self.groups[a] = (key, b or page_title(doc, a))
            if kind == "group":
                # A group whose first page bears its own title -- a
                # heading's introduction, placed under it by the split --
                # opens with that page's content rather than repeating the
                # heading. The group takes the page's id so links to the
                # page still land.
                opener = None
                if b and b[0][0] == "page" and not is_generated(b[0]) \
                        and b[0][1] != "notes":
                    stem, override = b[0][1], b[0][2]
                    doc = load_page(self.base, stem)
                    if (override or page_title(doc, stem)) == a:
                        opener = stem
                self.blocks.append(header(
                    depth, inlines(numbered_title(entry, a)),
                    page_id(opener) if opener else group_id(a, depth, self)))
                if opener:
                    self.add_page(opener, None, depth, heading=False)
                self.add_tree(b[1:] if opener else b, depth + 1)
            else:
                self.add_page(a, b, depth, number=entry.number)

    def before_entry(self, entry, depth):
        """Called before each entry of the tree is placed; a writer that
        marks where the book's divisions change does it here."""

    def add_generated(self, entry, depth):
        """A page the run writes: the contents page, as blocks."""
        kind, name, title = entry
        if entry.generate == "toc":
            self.blocks.append(header(depth, inlines(title), page_id(name)))
            self.blocks.extend(toc_blocks(
                self.tree, self.titles, lambda stem: "#" + page_id(stem)))
            self.pages.append((name, title, depth))

    def add_page(self, stem, title_override, depth, heading=True,
                 number=None):
        doc = load_page(self.base, stem)
        blocks = copy.deepcopy(doc["blocks"])
        title = title_override or page_title(doc, stem)
        if number:
            title = f"{number} {title}"
        prefix = page_id(stem) + "--"
        strip_comments(blocks)
        prefix_ids(blocks, prefix, self.book_pages)
        # A page's own headings continue below its entry. The page's title
        # heading is usually in its metadata, moved there by the filter;
        # when the body still opens with one, that is the page's heading
        # and it is used rather than doubled.
        shift_headers(blocks, depth - 1)
        if not heading:
            pass                    # the group's heading stands for it
        elif opens_with_h1(doc["blocks"]):
            # The heading takes the page's id; a link to the id it had (a
            # LaTeX chapter's \label, say) is sent to the page by finish().
            self.alias("", blocks[0]["c"][1][0], stem)
            blocks[0]["c"][1][0] = page_id(stem)
            blocks[0]["c"][2] = inlines(title) if (title_override or number) \
                else blocks[0]["c"][2]
        else:
            # The page's own title heading, as it said itself ("1.1 ..."),
            # unless the contents renames or numbers it.
            own = title_heading_inlines(doc)
            self.alias(prefix, meta_text(doc.get("meta", {}), "title-id"), stem)
            blocks.insert(0, header(depth, own if own is not None and not
                                    (title_override or number) else inlines(title),
                                    page_id(stem)))
        count_images(blocks, self.found)
        self.depth = max(self.depth, depth)
        self.pages.append((stem, title, depth))
        self.blocks.extend(blocks)

    def alias(self, prefix, own_id, stem):
        """Record that the page heading whose id was own_id (prefix + own_id
        once the page's ids are prefixed) now has the page's id."""
        if own_id and prefix + own_id != page_id(stem):
            self.aliases[prefix + own_id] = page_id(stem)

    def finish(self):
        """Links to a page heading's own id, which the heading gave up for
        the page's (add_page), pointed at the page. Run once every page is
        in, since a link can come before the page it points at."""
        if not self.aliases:
            return 0
        moved = 0

        def walk(node):
            nonlocal moved
            if isinstance(node, dict):
                if node.get("t") == "Link":
                    target = node["c"][2]
                    if target[0].startswith("#") and \
                            target[0][1:] in self.aliases:
                        target[0] = "#" + self.aliases[target[0][1:]]
                        moved += 1
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)
        walk(self.blocks)
        return moved

    def add_single_page(self, stem, title_override):
        """A contents tree that is one page is the book itself: its title
        is the book's, its headings are the book's, and nothing sits
        above them."""
        doc = load_page(self.base, stem)
        blocks = copy.deepcopy(doc["blocks"])
        strip_comments(blocks)
        prefix_ids(blocks, page_id(stem) + "--", self.book_pages)
        title = title_override or page_title(doc, stem)
        # A page whose title is its own H1 (title-heading, from the filter)
        # gets it back, as every page of a longer book does in add_page.
        own = title_heading_inlines(doc)
        if own is not None and not opens_with_h1(blocks):
            self.alias(page_id(stem) + "--",
                       meta_text(doc.get("meta", {}), "title-id"), stem)
            blocks.insert(0, header(1, inlines(title) if title_override else own,
                                    page_id(stem)))
            try:
                self.title_preceded = int(meta_text(doc["meta"], "title-index") or 0) > 0
            except ValueError:
                pass
        count_images(blocks, self.found)
        self.pages.append((stem, title, 1))
        self.blocks.extend(blocks)


def group_id(title, depth, assembly):
    """An id for a group heading that no page can produce and no two
    groups share: page ids start with page-, this with group-."""
    slug = "".join(c if c.isalnum() else "-" for c in title.lower())
    slug = "-".join(part for part in slug.split("-") if part) or "untitled"
    ordinal = sum(1 for b in assembly.blocks
                  if b.get("t") == "Header" and b["c"][1][0].startswith("group-"))
    return f"group-{ordinal + 1}-{slug}"


def load_documents(base, allow_unknown):
    schema = oerconfig.load_schema(os.path.join(BIN, "schema-conversion.yaml"))
    project_schema = oerconfig.load_schema(
        os.path.join(LIB, "schema-project.yaml"))
    documents = []
    project_path = os.path.join(base, PROJECT_NAME)
    if os.path.isfile(project_path):
        documents.append(oerconfig.load_document(project_path, project_schema))
    config_path = os.path.join(base, CONFIG_NAME)
    if os.path.isfile(config_path):
        documents.append(oerconfig.load_document(config_path, schema))
    return schema, project_schema, documents


def targets_of(schema, project_schema, documents, requested, allow_unknown,
               fmt):
    """The declared targets in one format, resolved; a target asked for
    by name that is in another format stops the run."""
    names = [requested] if requested else oerconfig.target_names(documents)
    targets = []
    for name in names:
        resolved = oerconfig.resolve(schema, project_schema, documents,
                                     target=name, allow_unknown=allow_unknown)
        if resolved["format"] == fmt:
            targets.append((name, resolved))
        elif requested:
            sys.exit(f"Target {name} has format: {resolved['format']}, "
                     f"not {fmt}.")
    return targets


def plan_book(pages_dir, resolved, output):
    """The book's tree, its pages' titles, and which pages it places.

    Returns (tree, titles, placed, numbered). output names the file
    being built in the message about pages contents leaves out. numbered
    is the book's numbering setting as this target resolves it; whether
    titles carry the numbers or the writer adds them is the caller's
    choice.
    """
    project = resolved.project
    stems = page_stems(pages_dir)
    if not stems:
        sys.exit(f"No {INTERMEDIATE} files in {pages_dir}: run the "
                 "conversion first.")
    titles, parts, roles = {}, {}, {}
    for stem in stems:
        doc = load_page(pages_dir, stem)
        titles[stem] = page_title(doc, stem)
        if meta_text(doc.get("meta", {}), "page-role"):
            roles[stem] = meta_text(doc["meta"], "page-role")
        source = meta_text(doc.get("meta", {}), "source-page")
        if source:
            # A source with no page of its own -- a chapter whose sections
            # start right under its heading -- still has a title, and its
            # pieces carry it; the group over them is called that.
            if source not in titles and meta_text(doc["meta"], "source-title"):
                titles[source] = meta_text(doc["meta"], "source-title")
            m = re.match(r"(\d+)/", meta_text(doc["meta"], "page-part"))
            parents = [p.get("c", "") for p in
                       doc["meta"].get("page-parents", {}).get("c", [])]
            parts[stem] = (source, int(m.group(1)) if m else None, parents,
                           meta_text(doc["meta"], "page-position"),
                           meta_text(doc["meta"], "source-title"),
                           meta_text(doc["meta"], "page-role"))

    available, used, problems = set(stems), set(), []
    if str(resolved["notes.placement"]) == "book":
        available.add("notes")      # the Notes chapter, written after
    contents = project.get("contents") or []
    if contents:
        tree = walk_contents(
            expand_split_sources(contents, stems, titles, parts, roles),
            available, used, problems, suffix=INTERMEDIATE)
    else:
        problems.append("contents not specified; using guessed order. The "
                        "packager's sample config is the place to fix it.")
        tree = walk_contents(guess_contents(stems, None, titles, parts, roles),
                             available, used, problems, suffix=INTERMEDIATE)
    for problem in problems:
        print(f"WARNING: {problem}", file=sys.stderr)
    unplaced = [s for s in stems if s not in used]
    if unplaced:
        print(f"{len(unplaced)} page(s) are not in project.contents, so "
              f"they are not in the {output} (nor in the cartridge):",
              file=sys.stderr)
        for stem in unplaced:
            print(f"  {stem}", file=sys.stderr)
    placed = list(flatten_pages(tree))
    if not [s for s in placed if s in available]:
        sys.exit("No page in project.contents exists on disk; nothing to "
                 "build.")
    choice = str(resolved["numbering"])
    numbered = choice in ("on", "True") if choice in ("on", "off", "True",
                                                        "False") \
        else bool(project["numbering"])
    return tree, titles, placed, numbered
