#!/usr/bin/env python3
"""
build-epub.py -- assemble a book's pages into one EPUB3.

    build-epub.py                  # build every epub3 target in conversion.yaml
    build-epub.py --target epub    # build one of them
    build-epub.py --if-declared    # build them, and be silent if there are none

Reads the filtered intermediates convert.py writes (<page>.filtered.json)
rather than the HTML pages. Pandoc's HTML reader keeps a cell's scope
attribute but not the element, so a row header read back from a page
would arrive as <td scope="row">; the intermediate still has everything
the filter did. It never runs the filter itself: the filter is per-page
by design, and running it over the assembled book would match no sidecar
declaration.

The book's structure comes from project.contents, the same tree the
cartridge organization is built from, or from the packager's filename
guess when there is none. A group -- a chapter, a unit, whatever the
author calls it -- becomes a heading, a page a heading at its depth, and the page's own headings continue below it, so
the table of contents shows ranks -- chapter, section -- at the same
depth whatever file each came from.

The package document's accessibility claims are computed from what this
run found rather than declared once and left to go stale: the EPUB says
its images have alternative text only when they all do.

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

import argparse
import json
import os
import re
import shutil
import zipfile
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))

try:
    import notes as notes_lib
    import oerconfig
except ImportError:
    sys.exit("Cannot find the configuration library. It should be in a "
             "lib/ directory beside bin/.")
from bookcontents import number_tree  # noqa: E402
from bookassembly import (  # noqa: E402
    INTERMEDIATE, page_id, load_page, inlines, header, Assembly,
    load_documents, targets_of, plan_book, wants_title_page,
    # not used here, but the EPUB tests reach them through this module
    count_images, page_title, prefix_ids, shift_headers,  # noqa: F401
)

PAGE_CSS = os.path.join(HERE, "page.css")

# --------------------------------------------------------------------------
# metadata
# --------------------------------------------------------------------------

def meta_string(text):
    return {"t": "MetaString", "c": str(text)}


def meta_list(items):
    return {"t": "MetaList", "c": [meta_string(i) for i in items]}


def accessibility_claims(found):
    """What the package document may say about this build.

    Pandoc's own defaults assert textual access, sufficient on its own,
    with alternative text present -- for every EPUB it writes. A catalog
    acts on those words, so each is made only when this run can stand
    behind it.
    """
    modes = ["textual"]
    if found["images"]:
        modes.append("visual")
    alt_complete = found["without_alt"] == 0
    # accessModeSufficient lists sets, one entry each. "textual" alone says
    # a reader who cannot see the page misses nothing, which is true only
    # when every image has been described (or marked decorative).
    sufficient = ["textual"] if alt_complete else ["textual,visual"]
    features = ["structuralNavigation", "tableOfContents", "readingOrder"]
    if found["images"] and alt_complete:
        features.append("alternativeText")
    if found["math"]:
        features.append("MathML")
    return {
        "accessModes": modes,
        "accessModeSufficient": sufficient,
        "accessibilityFeatures": features,
        # No video, audio, animation, or script comes out of a Word file.
        "accessibilityHazards": ["none"],
    }


def derived_summary(found):
    parts = ["Headings and a table of contents for navigation; data tables "
             "carry captions and header cells."]
    if found["images"]:
        if found["without_alt"] == 0:
            parts.append(f"All {found['images']} images have alternative "
                         "text or are marked decorative.")
        else:
            parts.append(f"{found['without_alt']} of {found['images']} "
                         "images have no alternative text yet.")
    if found["math"]:
        parts.append("Equations are MathML.")
    return " ".join(parts)


def book_metadata(project, resolved, found, base):
    meta = {
        "title": meta_string(project["title"]),
        "lang": meta_string(project["language"]),
        # The book's own identifier rather than a fresh UUID per build, so
        # a reading system recognizes a rebuilt edition as the same book.
        "identifier": meta_string(project["identifier"]),
    }
    if project.get("publisher"):
        meta["publisher"] = meta_string(project["publisher"])
    if project.get("description"):
        meta["description"] = meta_string(project["description"])
    authors = [str(a) for a in (project.get("authors") or []) if str(a)]
    if authors:
        meta["creator"] = meta_list(authors)
    for key, value in accessibility_claims(found).items():
        meta[key] = meta_list(value)
    summary = str(resolved["epub.accessibility_summary"] or "").strip()
    meta["accessibilitySummary"] = meta_string(summary or
                                               derived_summary(found))
    cover = str(resolved["epub.cover_image"] or "").strip()
    if cover:
        path = cover if os.path.isabs(cover) else os.path.join(base, cover)
        if not os.path.isfile(path):
            sys.exit(f"epub.cover_image is set to {cover}, which does not "
                     f"exist (looked at {os.path.abspath(path)}).")
        meta["cover-image"] = meta_string(os.path.abspath(path))
        alt = str(resolved["epub.cover_alt"] or "").strip()
        meta["cover-alt"] = meta_string(alt or f"Cover of {project['title']}")
    return meta


# --------------------------------------------------------------------------
# running Pandoc
# --------------------------------------------------------------------------

def pandoc_default(argument):
    return subprocess.run(["pandoc", argument], capture_output=True,
                          text=True, check=True).stdout


def chapter_template(work):
    """Pandoc's epub3 template with each chapter titled by its heading.

    The writer fills $pagetitle$ with the chapter file's name, so every
    chapter's <title> reads "ch002.xhtml" -- a WCAG 2.4.2 failure that
    Ace reports. The chapter's own title variable holds its heading.
    """
    template = pandoc_default("-Depub3")
    # The chapter <title> is left as the writer fills it -- the file name
    # -- and rewritten from the chapter's heading once the archive
    # exists (retitle_chapters). $title$ here would render a heading's
    # <em> or <sup> inside <title>, which XHTML forbids, and the writer
    # offers no plain-text form of a chapter's heading.
    # The cover is an SVG holding the image, with no text alternative at
    # all: a screen reader meets the book with a silent page. Give the
    # SVG a name, and a title element for readers that look there.
    svg = re.search(r'<svg [^>]*viewBox="0 0 \$cover-image-width\$ '
                    r'\$cover-image-height\$"[^>]*>', template)
    if svg:
        opened = svg.group(0)
        template = template.replace(
            opened,
            opened[:-1] + ' role="img" aria-label="$cover-alt$">'
            "\n<title>$cover-alt$</title>", 1)
    else:
        print("WARNING: Pandoc's epub3 template has changed its cover "
              "page; the cover will have no accessible name.",
              file=sys.stderr)
    path = os.path.join(work, "epub3.template")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(template)
    return path


NOTE = re.compile(r'(<aside epub:type="footnote"[^>]*\bid="fn(\d+)"[^>]*>)'
                  r'(.*?)(</aside>)', re.S)


def number_notes(text):
    """A number at the start of each footnote and a return link at its
    end, as Pandoc's HTML writer gives them.

    The EPUB writer writes each note as an aside with epub:type
    "footnote" and nothing else: a reading system that pops notes up on
    tap needs no number, and one that lists them at the end of the
    section leaves the reader with anonymous paragraphs. Numbers restart
    per chapter file, as the references do.
    """
    count = 0

    def fix(match):
        nonlocal count
        opening, number, body, closing = match.groups()
        if 'class="footnote-number"' in body:
            return match.group(0)
        count += 1
        body = re.sub(r"<p\b([^>]*)>",
                      r'<p\1><span class="footnote-number">%s.</span> ' % number,
                      body, count=1)
        back = (' <a href="#fnref%s" class="footnote-back" '
                'role="doc-backlink" aria-label="Back to reference %s">'
                '\u21a9\ufe0e</a>' % (number, number))
        last = body.rfind("</p>")
        body = body[:last] + back + body[last:] if last >= 0 else body + back
        return opening + body + closing

    return NOTE.sub(fix, text), count


def retitle_chapters(path):
    """Give each chapter file a <title> that is its heading's text, and
    its footnotes their numbers.

    Pandoc titles every chapter file by its file name ("ch002.xhtml"), a
    WCAG 2.4.2 failure on every page and what Ace reports first. The
    archive is rewritten in place, mimetype first and stored as the
    container rules require.
    """
    heading = re.compile(r"<h[1-6]\b[^>]*>(.*?)</h[1-6]>", re.S)
    title = re.compile(r"<title>.*?</title>", re.S)
    tmp = path + ".tmp"
    retitled = 0
    with zipfile.ZipFile(path) as zin, \
            zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "mimetype":
                zout.writestr(info, data, compress_type=zipfile.ZIP_STORED)
                continue
            if info.filename.endswith(".xhtml") and "/text/" in info.filename:
                text = data.decode("utf-8")
                found = heading.search(text)
                if found:
                    # A formula's TeX, kept in its MathML as an annotation,
                    # is no part of the title's text; and the title is put in
                    # as it is, not as a pattern's template, where a
                    # backslash in it (\pmb) was an escape.
                    words = re.sub(r"<annotation\b.*?</annotation>", "",
                                   found.group(1), flags=re.S)
                    plain = " ".join(re.sub(r"<[^>]+>", "", words).split())
                    if plain:
                        text = title.sub(lambda m: "<title>" + plain + "</title>",
                                         text, count=1)
                        retitled += 1
                text, _ = number_notes(text)
                data = text.encode("utf-8")
            zout.writestr(info, data)
    os.replace(tmp, path)
    return retitled


ID = re.compile(r'\sid="([^"]+)"')
FRAGMENT_LINK = re.compile(r'(<a\b[^>]*?\shref=")#([^"]+)(")')


def link_across_chapters(path):
    """A link to an id in another chapter file, given that file's name,
    and the navigation document's mathml property when its entries hold
    a formula. Returns the number of links fixed.

    Pandoc's writer splits the book into chapter files and gives a link
    the file its target is in, but finds only the ids of a Div, a Header,
    a Table, a Span, a Link, an Image, and raw HTML (getBlockIdent and
    getInlineIdent, Text/Pandoc/Chunks.hs, 3.12): a link to a figure's id
    in another chapter kept its bare #fragment, which epubcheck reports
    as RSC-012 (13 on OpenIntro Statistics, whose chapters cite each
    other's figures). And a heading with a formula puts the formula in the
    navigation document too, whose manifest item then lacks the mathml
    property (OPF-014)."""
    tmp = path + ".tmp"
    where, files = {}, {}
    with zipfile.ZipFile(path) as zin:
        for info in zin.infolist():
            if info.filename.endswith(".xhtml"):
                text = zin.read(info.filename).decode("utf-8")
                files[info.filename] = text
                for ident in set(ID.findall(text)):
                    # An id in two files (each chapter's fn1) names neither.
                    where[ident] = None if ident in where else info.filename
    fixed = 0
    changed = {}
    for name, text in files.items():

        def fix(m):
            nonlocal fixed
            target = where.get(m.group(2))
            if not target or target == name:
                return m.group(0)
            fixed += 1
            relative = os.path.relpath(target, os.path.dirname(name)).replace(os.sep, "/")
            return m.group(1) + relative + "#" + m.group(2) + m.group(3)
        new = FRAGMENT_LINK.sub(fix, text)
        if new != text:
            changed[name] = new
    nav_math = any(name.endswith("nav.xhtml") and "<math" in text for name, text in files.items())
    if not changed and not nav_math:
        return 0
    with zipfile.ZipFile(path) as zin, \
            zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "mimetype":
                zout.writestr(info, data, compress_type=zipfile.ZIP_STORED)
                continue
            if info.filename in changed:
                data = changed[info.filename].encode("utf-8")
            elif nav_math and info.filename.endswith(".opf"):
                data = re.sub(r'(<item\b[^>]*\bproperties=")nav(")', r"\1nav mathml\2",
                              data.decode("utf-8")).encode("utf-8")
            zout.writestr(info, data)
    os.replace(tmp, path)
    return fixed


def arrange_epub_notes(path, assembly, numbering, placement):
    """notes.numbering and notes.placement, applied to the chapter files.

    Each chapter file opens with the section the writer made of its
    heading, whose id says what it is: page-<stem>, group-N-..., or
    book-notes. Links between chapter files are by file name, since they
    share a directory."""
    with zipfile.ZipFile(path) as archive:
        names = sorted(n for n in archive.namelist()
                       if "/text/ch" in n and n.endswith(".xhtml"))
        texts = {n: archive.read(n).decode("utf-8") for n in names}
    pages, notes_page = [], None
    for name in names:
        text = texts[name]
        first = re.search(r'<section id="([^"]+)"', text)
        ident = first.group(1) if first else ""
        short = name.rsplit("/", 1)[1]
        if ident == page_id("notes"):
            notes_page = notes_lib.Page(short, text, "notes", "Notes", "xhtml")
            continue
        stem = None
        for candidate, (key, title) in assembly.groups.items():
            if ident == page_id(candidate) or ident.startswith(
                    page_id(candidate) + "--"):
                stem = candidate
                break
        if stem is None:
            continue                    # a group heading's own chapter
        key, title = assembly.groups[stem]
        pages.append(notes_lib.Page(short, text, key, title, "xhtml"))
    changed = notes_lib.arrange(pages, numbering, placement, notes_page)
    if not changed:
        return
    updates = {"EPUB/text/" + p.name: p.text for p in changed}
    for name in names:
        texts[name] = updates.get(name, texts[name])
    tmp = path + ".tmp"
    with zipfile.ZipFile(path) as zin, \
            zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "mimetype":
                zout.writestr(info, data, compress_type=zipfile.ZIP_STORED)
                continue
            if info.filename in updates:
                data = updates[info.filename].encode("utf-8")
            elif info.filename.endswith(".opf"):
                # A note that moved may have taken the file's only MathML
                # with it, or brought some; the manifest says per file.
                data = mark_mathml(data.decode("utf-8"), texts).encode("utf-8")
            zout.writestr(info, data)
    os.replace(tmp, path)


def mark_mathml(opf, texts):
    """The mathml property on each text item, as its content now is."""
    def fix(match):
        tag = match.group(0)
        href = re.search(r'href="([^"]+)"', tag).group(1)
        has_math = "<math" in texts.get("EPUB/" + href, "")
        props = re.search(r'properties="([^"]*)"', tag)
        tokens = props.group(1).split() if props else []
        tokens = [t for t in tokens if t != "mathml"]
        if has_math:
            tokens.append("mathml")
        if props:
            if tokens:
                return tag.replace(props.group(0),
                                   'properties="%s"' % " ".join(tokens))
            return tag.replace(" " + props.group(0), "")
        if tokens:
            return tag.replace("<item ", '<item properties="mathml" ', 1)
        return tag
    return re.sub(r'<item [^>]*href="text/[^"]+\.xhtml"[^>]*/>', fix, opf)


def stylesheet(work):
    """Pandoc's EPUB stylesheet followed by ours. --css replaces the
    default rather than adding to it."""
    path = os.path.join(work, "book.css")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(pandoc_default("--print-default-data-file=epub.css"))
        fh.write("\n\n/* From TextbookImprover's page.css */\n")
        with open(PAGE_CSS, encoding="utf-8") as page_css:
            fh.write(page_css.read())
    return path


def output_name(resolved, project, target):
    """<identifier>.epub unless the target names a file."""
    name = str(resolved["filename"] or "").strip() \
        or project["identifier"] or target
    if not name.lower().endswith(".epub"):
        name += ".epub"
    return name


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------

def epub_targets(schema, project_schema, documents, requested, allow_unknown):
    return targets_of(schema, project_schema, documents, requested,
                      allow_unknown, "epub3")


# --------------------------------------------------------------------------

def build(base, name, resolved, keep, intermediates=None):
    project = resolved.project
    for warning in resolved.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)

    # Where the filtered intermediates are: the content directory unless
    # a run with several targets put this target's elsewhere. Media paths
    # inside them are relative to the content directory either way.
    pages_dir = intermediates or base
    tree, titles, placed, numbered = plan_book(pages_dir, resolved, "EPUB")
    real = [s for s in placed if os.path.exists(
        os.path.join(pages_dir, s + INTERMEDIATE))]
    if numbered:
        number_tree(tree, titles)

    assembly = Assembly(pages_dir, placed, tree, titles)
    if len(tree) == 1 and tree[0][0] == "page":
        assembly.add_single_page(tree[0][1], tree[0][2])
    else:
        assembly.add_tree(tree)
    assembly.finish()
    title_page = wants_title_page(str(resolved["title_page"]), tree, assembly)
    numbering = str(resolved["notes.numbering"])
    placement = str(resolved["notes.placement"])
    if placement == "book" and assembly.found["notes"] \
            and not assembly.notes_placed:
        # A chapter of its own for the notes, filled after the writer runs.
        assembly.blocks.append(header(1, inlines("Notes"), page_id("notes")))

    document = {
        "pandoc-api-version": load_page(pages_dir,
                                        real[0])["pandoc-api-version"],
        "meta": book_metadata(project, resolved, assembly.found, base),
        "blocks": assembly.blocks,
    }

    out_dir = os.path.join(base, str(resolved["output_dir"] or name))
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, output_name(resolved, project, name))
    toc_depth = int(resolved["epub.toc_depth"])

    work = tempfile.mkdtemp(prefix="build-epub-")
    try:
        book_json = os.path.join(work, "book.json")
        with open(book_json, "w", encoding="utf-8") as fh:
            json.dump(document, fh)
        command = [
            "pandoc", "-f", "json", "-t", "epub3", book_json,
            "-o", os.path.abspath(out_path),
            "--template", chapter_template(work),
            "--css", stylesheet(work),
            # One file per page: split at every level a page heading uses.
            f"--split-level={assembly.depth}",
            f"--toc-depth={toc_depth}",
            "--math-method=mathml",
            # Without a title page the title is the package's dc:title, and
            # the book's first heading says it (title_page).
            "--epub-title-page=%s" % ("true" if title_page else "false"),
            # A passage for some editions, and the title-block switch,
            # resolved for this target.
            "--lua-filter", os.path.join(HERE, "target-blocks.lua"),
        ]
        environment = dict(os.environ, TARGET_NAME=name,
                           TITLE_BLOCK=str(resolved["title_block"]))
        # Run in the content directory: image paths in the intermediates
        # are relative to it.
        result = subprocess.run(command, cwd=base, capture_output=True,
                                text=True, env=environment)
        if result.stderr.strip():
            print(result.stderr.rstrip(), file=sys.stderr)
        if result.returncode != 0:
            sys.exit(f"pandoc failed building {out_path}.")
        retitle_chapters(out_path)
        if numbering != "page" or placement != "page":
            arrange_epub_notes(out_path, assembly, numbering, placement)
        link_across_chapters(out_path)
        if keep:
            shutil.copy(book_json, os.path.join(out_dir, "book.json"))
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print(os.path.abspath(out_path))          # for whatever runs next
    found = assembly.found
    claims = accessibility_claims(found)
    print(f"Wrote {out_path}: {len(assembly.pages)} page(s), "
          f"{found['images']} image(s), {found['without_alt']} without "
          "alternative text.", file=sys.stderr)
    print("  Claims: accessMode " + ", ".join(claims["accessModes"])
          + "; sufficient " + "; ".join(claims["accessModeSufficient"])
          + "; features " + ", ".join(claims["accessibilityFeatures"]) + ".",
          file=sys.stderr)
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Assemble the filtered intermediates into an EPUB3.")
    parser.add_argument("-d", "--dir", default=".",
                        help="the content directory (default: .)")
    parser.add_argument("--target", default=None,
                        help="build this epub3 target only")
    parser.add_argument("--intermediates", default=None,
                        help="read the filtered intermediates from here "
                             "rather than from the content directory")
    parser.add_argument("--if-declared", action="store_true",
                        help="exit quietly when no epub3 target is declared")
    parser.add_argument("--keep", action="store_true",
                        help="leave the assembled book.json beside the EPUB")
    parser.add_argument("--allow-unknown-keys", action="store_true",
                        help="report settings this version does not know "
                             "about instead of refusing them")
    args = parser.parse_args()

    if shutil.which("pandoc") is None:
        sys.exit("pandoc is not on the path.")

    try:
        schema, project_schema, documents = load_documents(
            args.dir, args.allow_unknown_keys)
        targets = epub_targets(schema, project_schema, documents,
                               args.target, args.allow_unknown_keys)
    except oerconfig.ConfigError as exc:
        sys.exit(str(exc))

    if not targets:
        if args.if_declared:
            return 0
        print("No target with format: epub3 in conversion.yaml. Declare "
              "one to build an EPUB:", file=sys.stderr)
        print("  targets:\n    epub:\n      format: epub3", file=sys.stderr)
        return 1

    status = 0
    for name, resolved in targets:
        status = build(args.dir, name, resolved, args.keep,
                       args.intermediates) or status
    return status


if __name__ == "__main__":
    sys.exit(main())
