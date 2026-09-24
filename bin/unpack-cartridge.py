#!/usr/bin/env python3
"""Unpack an IMS Common Cartridge into a book's sources.

A course exported from an LMS, or a publisher's course cartridge, holds its
content as web pages and files arranged by an outline of modules. This
writes each HTML page as a source page and each Word document as a source,
keeps every other file where the cartridge had it, and writes project.yaml
with the outline as the book's contents: a module is a group, and a Canvas
text header groups the entries after it. The directory is the book from
then on; convert.py converts it, and does the unpacking itself when it
finds a cartridge alone in a directory.

What a course holds that a book doesn't -- discussions, assignments, web
links, quizzes and test banks, tool links -- is listed in
unpack-report.csv, as are files the outline names that aren't pages (slides,
PDFs), entries that name a resource twice, and pages that only link out to
another site.

A document a page only links to -- a Word checklist, say -- is kept as a
file, which the HTML carries and an EPUB can't. With --linked-documents,
each linked file the pipeline converts (Word, Markdown, AsciiDoc, HTML)
becomes a page of the book instead, beneath the first page that links to
it and titled by that link's text, and the link leads to the page.

Usage:
    python3 unpack-cartridge.py course.imscc -o book/
    python3 unpack-cartridge.py course.imscc -o book/ --linked-documents
"""
import argparse
import os
import posixpath
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
try:
    import cartridgesource as cs
    import epubsource
    from unpacking import contents_tree, project_yaml, write_report, summarize
    from names import safe_stem
except ImportError:
    sys.exit("Cannot find the library. It should be in a lib/ directory "
             "beside bin/.")

ACTIVITY = {
    "discussion": "a discussion topic: an activity in the course, not converted",
    "assignment": "an assignment: an activity in the course, not converted",
    "assessment": "a quiz or test bank: not converted",
    "tool-link": "a link to an external tool (LTI): not converted",
    "other": "a resource of a kind this doesn't read: not converted",
    "missing": "the outline names a resource the manifest doesn't have",
}


def main():
    parser = argparse.ArgumentParser(
        description="Unpack an IMS Common Cartridge into a book's sources.")
    parser.add_argument("cartridge")
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("--linked-documents", action="store_true",
                        help="make each document a page links to, when the "
                        "pipeline can convert it, a page of the book")
    args = parser.parse_args()
    out = args.output
    if os.path.exists(out) and os.listdir(out):
        sys.exit(f"{out} exists and is not empty; unpacking would mix two "
                 "books. Name another directory with -o.")
    if not cs.is_cartridge(args.cartridge):
        sys.exit(f"{args.cartridge} isn't a Common Cartridge: no "
                 "imsmanifest.xml of one in it.")
    cartridge = cs.Cartridge(args.cartridge)
    os.makedirs(out, exist_ok=True)
    notes = []
    archive = cartridge.names

    # Name every page and Word source, in outline order, then any page the
    # outline doesn't list. A name is the file's own, made safe for a link;
    # a second file with that name takes a number.
    names, taken, order = {}, set(), []

    def name(path):
        if path in names:
            return names[path]
        # Brightspace names files after titles, dots and all ("... week..html",
        # "... week. - Copy.html"): runs of dots and hyphens become one
        # hyphen, and a name ends on a letter or digit, since Windows drops
        # a trailing dot.
        stem = re.sub(r"[.-]{2,}", "-", safe_stem(
            os.path.splitext(posixpath.basename(path))[0])).strip(".-") or "page"
        candidate, n = stem, 2
        while candidate.lower() in taken:
            candidate, n = f"{stem}-{n}", n + 1
        taken.add(candidate.lower())
        names[path] = candidate
        order.append(path)
        return candidate

    outline = cartridge.outline()
    listed, entries = set(), []
    for depth, title, ref in outline:
        if ref is None:
            entries.append((depth, title, None, None))
            continue
        kind = cartridge.kind(ref)
        if kind in ("page", "source"):
            path = cs.path_in(archive, cartridge.resources[ref]["href"])
            if path not in archive:
                notes.append((title, "missing-from-archive",
                              f"the manifest names {path}, which the "
                              "cartridge lacks"))
                continue
            if ref in listed:
                notes.append((title, "listed-twice",
                              "the outline names this resource again; the "
                              "book holds it once, where it first appears"))
                continue
            listed.add(ref)
            name(path)
            entries.append((depth, title, path, None))
        elif kind == "file":
            href = cartridge.resources[ref]["href"]
            notes.append((title, "file-in-outline",
                          f"kept at {cs.path_in(archive, href)}; a file, not "
                          "a page, so not in contents"))
        elif kind == "web-link":
            link_title, url = cartridge.web_link(ref)
            notes.append((title or link_title, "web-link",
                          f"a link to {url or 'an address it does not give'}; "
                          "not in contents"))
        else:
            notes.append((title, kind, ACTIVITY.get(kind, ACTIVITY["other"])))

    # Pages the outline never names: kept at the end, unless Canvas marks
    # them unpublished.
    for identifier, resource in cartridge.resources.items():
        if identifier in listed or cartridge.kind(identifier) != "page":
            continue
        path = cs.path_in(archive, resource["href"])
        if path not in archive or path in names:
            continue
        markup = cartridge.read(path).decode("utf-8", "replace")
        if cs.unpublished(markup):
            notes.append((path, "unpublished",
                          "a page students don't see; left out"))
            continue
        name(path)
        notes.append((names[path] + ".html", "not-in-outline",
                      "a page the outline doesn't list; at the end of "
                      "contents"))

    # Documents the pages link to that the pipeline can convert: pages of
    # the book with --linked-documents, beneath the first page linking to
    # each; otherwise files, which the report names.
    children, kept = {}, {}
    queue = [p for p in order if p.lower().endswith((".html", ".htm"))]
    while queue:
        page_path = queue.pop(0)
        markup = cartridge.read(page_path).decode("utf-8", "replace")
        markup, _ = cs.resolve_placeholders(markup, page_path)
        for target, text in cs.local_links(markup, page_path):
            target = cs.path_in(archive, target)
            if (target not in archive or target in names
                    or not target.lower().endswith(cs.CONVERTIBLE)):
                continue
            if not args.linked_documents:
                kept.setdefault(target, page_path)
                continue
            name(target)
            # Canvas's link text is often the file's own name; a title
            # doesn't keep its extension.
            stem, ext = os.path.splitext(posixpath.basename(target))
            if text.lower().endswith(ext.lower()):
                text = text[:-len(ext)].strip()
            children.setdefault(page_path, []).append((text or stem, target))
            notes.append((names[target] + os.path.splitext(target)[1].lower(),
                          "linked-document",
                          f"linked from {names[page_path]}.html; a page of the "
                          "book beneath it"))
            if target.lower().endswith((".html", ".htm")):
                queue.append(target)
    for target, page_path in sorted(kept.items()):
        notes.append((target, "linked-document-kept",
                      f"linked from {names[page_path]}.html and kept as a file, "
                      "which an EPUB can't carry; --linked-documents makes it "
                      "a page"))
    if children:
        placed = []

        def place(depth, title, path):
            placed.append((depth, title, path, None))
            for text, doc in children.get(path, []):
                place(depth + 1, text, doc)
        for depth, title, path, fragment in entries:
            if path is None:
                placed.append((depth, title, path, fragment))
            else:
                place(depth, title, path)
        entries = placed

    # What the outline never lists, by kind: a course's test banks sit
    # outside its modules, and matter for anyone making them into output.
    referenced = {ref for _, _, ref in outline if ref}
    unlisted = {}
    for identifier in cartridge.resources:
        kind = cartridge.kind(identifier)
        if identifier not in referenced and kind not in ("page", "source", "file"):
            unlisted[kind] = unlisted.get(kind, 0) + 1
    for kind, count in sorted(unlisted.items()):
        notes.append(("cartridge", "unlisted-" + kind,
                      f"{count} {kind} resource(s) the outline doesn't list: "
                      + ACTIVITY.get(kind, ACTIVITY["other"]).split(": ", 1)[-1]
                      if kind in ACTIVITY else
                      f"{count} {kind} resource(s) the outline doesn't list"))

    # The book's root: the one directory that holds every file the web
    # content uses, when there is one -- the content prefix of a cartridge
    # this project built, Brightspace's content folder -- so that paths
    # inside the book don't carry it. Canvas keeps pages and files in
    # sibling directories, and its root stays the archive's.
    files = set(order)
    for identifier, resource in cartridge.resources.items():
        if resource["type"].lower().startswith("webcontent"):
            files.update(cs.path_in(archive, h)
                         for h in resource["files"] or [resource["href"]])
    root = posixpath.dirname(sorted(files)[0]) if files else ""
    while root and not all(f.startswith(root + "/") for f in files):
        root = posixpath.dirname(root)

    titles = {path: title for _, title, path, _ in entries if path}
    unresolved = set()
    for path in order:
        if not path.lower().endswith((".html", ".htm")):
            # A source the pipeline converts from its own format.
            with open(os.path.join(out, names[path]
                                   + os.path.splitext(path)[1].lower()),
                      "wb") as fh:
                fh.write(cartridge.read(path))
            continue
        markup = cartridge.read(path).decode("utf-8", "replace")
        markup, missing = cs.resolve_placeholders(markup, path)
        unresolved |= missing
        markup = cs.with_title(markup, titles.get(path, ""))
        markup = epubsource.rewrite_references(markup, path, names, root)
        with open(os.path.join(out, names[path] + ".html"), "w",
                  encoding="utf-8") as fh:
            fh.write(markup)
        host = cs.links_out(markup)
        if host:
            notes.append((names[path] + ".html", "links-out",
                          f"little more than links to {host}: a reading list "
                          "pointing at the reading, which isn't here"))
    for placeholder in sorted(unresolved):
        notes.append(("pages", "lms-reference",
                      f"${placeholder}$ points into the LMS the course came "
                      "from; left as it is"))

    # Every other file a webcontent resource uses, where it sat.
    pages = set(order)
    copied = 0
    for identifier, resource in cartridge.resources.items():
        if not cartridge.resources[identifier]["type"].lower().startswith(
                "webcontent"):
            continue
        for href in resource["files"] or [resource["href"]]:
            path = cs.path_in(archive, href)
            if path in pages or path not in archive:
                continue
            dest = os.path.join(out, *posixpath.relpath(path, root or ".")
                                .split("/"))
            if os.path.exists(dest):
                continue
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
            with open(dest, "wb") as fh:
                fh.write(cartridge.read(path))
            copied += 1

    tree, named = contents_tree(entries, names, notes)
    unnamed = [names[p] for p in order if names[p] not in named]
    title = cartridge.title or os.path.basename(os.path.abspath(out))
    meta = {"title": [title]}
    if cartridge.language:
        meta["language"] = [cartridge.language]
    with open(os.path.join(out, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write(project_yaml("unpack-cartridge.py from "
                              + os.path.basename(args.cartridge)
                              + (f" (Common Cartridge {cartridge.version})"
                                 if cartridge.version else ""),
                              meta, tree, {}, unnamed, title))
    write_report(os.path.join(out, "unpack-report.csv"), notes)
    summarize(notes, out, len(order))
    if copied:
        print(f"{copied} other file(s) kept where the cartridge had them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
