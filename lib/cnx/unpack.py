"""
cnx.unpack -- the steps unpack-cnx.py runs, in order: read the
repository, assemble the book, bake it, cut it into pages, write them.

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

import csv
import os

import sidecars

from . import exercises
from . import pages as P
from .assemble import assemble
from .bake import bake
from .bake.recipes import RECIPES
from .emit import Emitter, serialize
from .project import (PDF_LAYOUT, openstax_conversion, openstax_pdf_layout,
                      copy_media, project_yaml, write_captions)
from .repo import Repo


class Result:
    def __init__(self):
        self.pages = 0
        self.media = 0
        self.notes = []
        self.prefilled = 0
        self.summaries = 0
        self.empty_summaries = 0
        self.summaries_read_out = 0
        self.layout_tables = 0
        self.style = ""
        self.baked = False
        self.exercises = 0
        self.exercises_missing = 0
        self.boxes = 0
        self.formula_steps = 0
        self.merged_titles = 0
        self.kind_alone = 0
        self.title_alone = 0


def resolve_other_books(repo, book, baked, report):
    """A link to a module of another book of the repository (Principles
    of Microeconomics to a chapter only Principles of Economics has):
    to that book's page at openstax.org, named as OpenStax names it, and
    showing what the page or its target is called there when the link
    has no text. The other book is assembled and baked to learn the
    names, which only baking gives."""
    links = [a for a in baked.body.iter("a")
             if (a.get("href") or "").startswith("cnx-module:")]
    if not links:
        return
    others = [b for b in repo.books if b.slug != book.slug]
    modules = {}
    known = {}
    for link in links:
        holder = baked.page_of(link)
        where = holder.get("data-module") if holder is not None else ""
        document, _, target = link.get("href")[len("cnx-module:"):] \
            .partition("#")
        other = next((b for b in others if document in modules.setdefault(
            b.slug, {n.module for n in b.collection.modules()})), None)
        if other is None or not other.style:
            link.set("href", f"https://cnx.org/content/{document}"
                     + (f"#{target}" if target else ""))
            report(where, "link-to-other-book",
                   f"to module {document}, in no book OpenStax publishes; "
                   "to the Connexions archive's address")
            continue
        if other.slug not in known:
            known[other.slug] = _names(repo, other)
        page_of, labels = known[other.slug]
        page = page_of.get(document)
        link.set("href", f"https://openstax.org/books/{other.slug}/pages/"
                 f"{page.name if page else ''}"
                 + (f"#{target}" if target else ""))
        if not len(link) and not (link.text or "").strip():
            link.text = labels.get(f"{document}__{target}") if target \
                else None
            link.text = link.text or (page.title if page else document)
        report(where, "link-to-other-book",
               f"to {other.slug}: {link.get('href')}")


def _names(repo, other):
    """{module: Page} and the link texts baking gives, for another book
    of the repository."""
    _, body = assemble(repo, other)
    baked = bake(body, other.style, other.collection.language)
    _, pages = P.collect(baked)
    return ({p.module: p for p in pages if p.module}, baked.labels)


def unpack(repo_dir, out, slug=None, source_name=None, bank=None, boxes=True):
    """Unpack one book of a repository into out, which must be empty or
    absent. bank is the exercises.Bank its embedded exercises come from
    (by default, the cache, then the network); boxes, whether its notes
    are boxes (class box). Returns a Result."""
    repo = Repo(repo_dir)
    book = repo.book(slug)
    result = Result()
    result.style = book.style
    result.baked = book.style in RECIPES
    asm, body = assemble(repo, book)
    result.exercises, result.exercises_missing = exercises.inject(
        asm, body, bank or exercises.Bank())
    baked = bake(body, book.style, book.collection.language)
    outline, pages = P.collect(baked)
    notes = asm.notes

    def report(where, check, detail):
        notes.append((where, check, detail))

    P.resolve(baked, pages, report)
    resolve_other_books(repo, book, baked, report)
    os.makedirs(out, exist_ok=True)
    language = book.collection.language or "en"
    emitter = Emitter(baked, pages, language, report, boxes=boxes)
    for page in pages:
        html = emitter.page_html(page)
        with open(os.path.join(out, page.name + ".html"), "w",
                  encoding="utf-8") as fh:
            fh.write(serialize(html))
    result.pages = len(pages)
    result.boxes = emitter.boxed
    result.formula_steps = emitter.formula_steps
    result.merged_titles = emitter.merged_titles
    result.kind_alone = emitter.kind_alone
    result.title_alone = emitter.title_alone
    result.media = copy_media(asm, out, notes)
    source = "unpack-cnx.py from " + (source_name or os.path.basename(
        os.path.abspath(repo_dir))) + f" ({book.slug})"
    is_openstax = bool(book.style)
    with open(os.path.join(out, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write(project_yaml(source, book.collection, book.slug, outline,
                             publisher="OpenStax" if is_openstax else None,
                             authors=["OpenStax"] if is_openstax else None))
    if is_openstax and not os.path.exists(os.path.join(out,
                                                       "conversion.yaml")):
        with open(os.path.join(out, "conversion.yaml"), "w",
                  encoding="utf-8") as fh:
            fh.write(openstax_conversion(
                source,
                *(baked.t(key) if baked.has_string(key) else default
                  for key, default in (("figure", "Figure"), ("table", "Table")))))
        # The PDF's page, which that conversion.yaml names.
        if not os.path.exists(os.path.join(out, PDF_LAYOUT)):
            with open(os.path.join(out, PDF_LAYOUT), "w", encoding="utf-8") as fh:
                fh.write(openstax_pdf_layout(source, book.style))
    (result.prefilled, result.summaries, result.empty_summaries,
     result.summaries_read_out) = write_captions(out, emitter.tables, report)
    result.layout_tables = sum(1 for t in emitter.tables if t[4])
    if not result.baked and book.style:
        notes.append(("book", "style-not-baked",
                      f"style {book.style!r} has no recipe here yet; numbered "
                      "within each page, nothing moved"))
    result.notes = notes
    with open(os.path.join(out, "unpack-report.csv"), "w", newline="",
              encoding=sidecars.CSV_ENCODING) as fh:
        writer = csv.writer(fh)
        writer.writerow(["Where", "Check", "Detail"])
        writer.writerows(notes)
    return result
