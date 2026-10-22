"""
cnx -- read a book from its CNXML source, the format OpenStax writes its
books in and the archive of Connexions books is kept in, and write it as
pages TextbookImprover converts.

A repository in this layout (openstax/osbooks-*, cnx-user-books/*) holds:

    META-INF/books.xml        the books in it: slug, collection, style
    collections/*.xml         each book's outline (collxml)
    modules/m*/index.cnxml    one page each (CNXML)
    media/                    the images and other files the pages use

What OpenStax publishes is not those pages as written but the book after
"baking": numbers given to figures, tables, and exercises, the text of
every link that names one, titles on the notes, and end-of-chapter pages
made from sections moved out of the chapter's pages. Their baking is a
Ruby program per book (openstax/cookbook, MIT License); the parts of it
the books here need are ported in bake/, and say so where they are.

The steps, each a module:

    repo.py       the repository: its books, their outlines, the modules
    cnxml.py      one module's CNXML as HTML, in the shape baking expects
    mathml.py     MathML as Pandoc's reader takes it
    assemble.py   a book's modules as one tree: units, chapters, pages
    exercises.py  exercises from OpenStax's exercise bank, put in
    bake/         numbering, titles, link text, end-of-chapter pages
    pages.py      the baked book cut into pages, named as OpenStax names them
    emit.py       each page as HTML for TextbookImprover's HTML reader
    steptables.py which tables only lay things out (a worked example's
                  steps, a grid of terms, a box of one cell, a form, a
                  matching exercise), layout tables, by what they hold
                  or where they stand and TextbookImprover's header guess;
                  and a worked example's steps written as one formula,
                  made such a table
    mathtex.py    a formula's TeX as Pandoc writes it, for the guess
    project.py    project.yaml, the sidecars the source can fill, the report
    unpack.py     the steps in order, for bin/unpack-cnx.py

And compare.py, for the utilities that check all this against
OpenStax's own tools (util/cnx-compare-cookbook.py and
util/cnx-compare-assembly.py).

Nothing here is needed by the rest of TextbookImprover, and nothing else
in it is needed here but the shared helpers bin/unpack-cnx.py imports.
Needs lxml.

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
