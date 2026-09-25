# What goes in, what comes out

Every source format the pipeline reads, the ways a book in that format can arrive, what each can be turned into, how far each path has been tested, and how the output is packaged. The details live on each format's own page, linked from here.

## How the paths are rated

- **TESTED**: the test suite covers the path, and real books have gone through it and been checked: the [output check](checking.md) on every run, epubcheck for an EPUB, and `util/compare-output.py` for a round trip.
- **NEEDS MORE TESTING**: covered by the suite or by one book, or a real book showed a problem that isn't fixed yet.
- **NOT TESTED**: the code allows it, but neither a test nor a real book has taken the path.
- **NOT YET IMPLEMENTED**: an output the configuration names but nothing produces yet. A target declaring it is skipped with a warning.
- **Not available**: an output no one has planned.

## At a glance

| Input | HTML | EPUB | Markdown | AsciiDoc | PDF | Word | Round trip to itself |
|---|---|---|---|---|---|---|---|
| Word (`.docx`) | TESTED | TESTED | TESTED | TESTED | NOT YET IMPLEMENTED | TESTED | TESTED, with losses (see [Word output](#word-output)) |
| Markdown (`.md`) | TESTED | TESTED | TESTED | TESTED | NOT YET IMPLEMENTED | TESTED | TESTED |
| HTML (`.html`) | TESTED | TESTED | TESTED | TESTED | NOT YET IMPLEMENTED | TESTED | TESTED |
| AsciiDoc (`.adoc`) | TESTED | TESTED | TESTED | TESTED | NOT YET IMPLEMENTED | TESTED | TESTED |

PDF output is NOT YET IMPLEMENTED ([on the roadmap](../ROADMAP.md)): a target declaring `format: pdf` is skipped with a warning saying so, and a book with no other target stops. PDF is read only by [the audit](auditing.md), which reports on a Word, Markdown, HTML, EPUB, or PDF file without converting it.

## Word

**How it can arrive**

- Files in the book's directory: one `.docx` per chapter or section, or one for the whole book, which [the split](splitting.md) cuts into pages.
- A plain `.zip` of them, such as a publisher's DOCX download, which `convert.py` extracts when it finds the zip alone in a directory ([A book that arrives as an archive](first-run.md#a-book-that-arrives-as-an-archive)). Tested on OpenStax's download of *Introductory Business Statistics 2e*, its 169 files two folders deep: the same 169 pages and 253 images as the files converted from a folder.
- Inside a [Common Cartridge](cartridge-input.md): a Word file the course outline names is a source, and with `--linked-documents` so is one a page only links to.

A hyperlink's ScreenTip becomes the link's title, which the HTML and EPUB targets write as a tooltip and the Markdown and AsciiDoc targets keep. Pandoc 3.11's reader drops ScreenTips, so the pipeline recovers them itself. Pandoc's own reader and writer handle them from its first release after 3.11, which includes the change this project contributed ([pandoc#11890](https://github.com/jgm/pandoc/pull/11890)).

**What it becomes**

- **HTML: TESTED.** The census has read all nine books of the test corpus (1,782 files); the statistics, nursing, marketing, business communication, and programming books have been converted, and cartridges this pipeline builds have been imported into Brightspace. Lost on the way: a hyperlink's ScreenTip, which Pandoc's reader discards ([#11869](https://github.com/jgm/pandoc/issues/11869), agreed upstream), and the document's properties, since the title and author come from paragraphs styled Title and Author. Bookmarks Pandoc's reader would drop are repaired before it reads the file, and table headers come from Word's marks, the [sidecar](sidecars.md), or the guess.
- **EPUB: TESTED**, on the same books and the suite's fixtures. It loses what [every EPUB loses](#epub), as well.
- **Markdown: TESTED**, on the statistics book (merged by chapter) and the suite's round trip: read back, it gives the same HTML, and written again it's the same file. The first write normalizes Word's residue (paragraphs holding only a non-breaking space, stray spaces), so the second write is the fixed point. A table with merged cells, and a figure with an id, are written as fenced HTML, since Pandoc's Markdown can't express them; a banded table is kept as one table.
- **AsciiDoc: TESTED**, on the statistics book: read back, 166 of its 169 pages are identical to the book converted directly. Two lose a root with an index (`\sqrt[n]{…}`), which Pandoc's AsciiDoc reader can't read, and one a list's depth ([AsciiDoc as a target](asciidoc.md#asciidoc-as-a-target)).
- **Word: TESTED**, on the statistics book: 169 files, valid against Word's schema, with 229 header columns flagged. Read back as a book, 135 of its 169 pages give the same HTML; the rest lose what Word has no structure for ([Word output](#word-output)), almost all of it figures without a caption, which come back as images.
- **PDF: NOT YET IMPLEMENTED**, [on the roadmap](../ROADMAP.md).

## Markdown

**How it can arrive**

- Files in the book's directory, with images wherever they name them ([Markdown sources](markdown.md)), including a book set up for a Pandoc PDF build.
- A plain `.zip` of them.
- A Jekyll site's source (just-the-docs), through [`unpack-jekyll.py`](site-input.md#a-sites-own-source), which writes a book directory of Markdown.
- A Markdown target's output from an earlier conversion, which is written to be a source.

**What it becomes**

- **HTML: TESTED**, on the economics book, the 33-chapter Markdown textbook, and the suite. HTML written into the Markdown is read as HTML and cleaned the way an HTML source is.
- **EPUB: TESTED.** The economics book's 34 pages build an EPUB epubcheck passes without an error or a warning.
- **Markdown (round trip): TESTED**, by the suite and on the economics book: the second write equals the third.
- **AsciiDoc: TESTED**, on the economics book and the suite: read back, 31 of the book's 34 pages are identical to the book converted directly. The other three hold a footnote with a list or a quotation inside, which an AsciiDoc footnote can't keep; the words stay.
- **Word: TESTED**, on *Principles of Economics*: 34 files, valid against Word's schema, with 37 ScreenTips.
- **PDF: NOT YET IMPLEMENTED.**

## HTML

**How it can arrive**

- Files in the book's directory: every `.html` beside the sources is a source ([HTML sources](html.md)), and a finished page that shouldn't be converted goes in `_pt/`, copied as it is.
- A plain `.zip` of them. A zip holding a browser's save (pages marked with the address they were saved from, or with a `_files` folder beside them, or `.mhtml` files) goes through `unpack-site.py`, as the save itself would. Tested on CS168 as a browser's save zipped: 62 pages, named from their addresses and ordered by the site's menus.
- A website saved from a browser, or saved as `.mhtml`, through [`unpack-site.py`](site-input.md). Tested on CS168 and DCIC. A browser's `.mhtml` save holds only MathJax's rendering of a formula, not its TeX, and each rendering is made math again from what it still holds ([HTML sources](html.md) says how). MathJax 2's HTML-CSS rendering is TESTED, on DCIC's 410 formulas. The rest NEEDS MORE TESTING: MathJax 2's CommonHTML and SVG, and MathJax 3's and 4's CommonHTML and SVG, with and without the MathML they hide for screen readers, have been tested only on renderings MathJax itself produced, not on a page saved from a real book. MathJax 2's SVG without that hidden MathML can't be read back at all; such a formula is marked `[formula]`, and the output check reports it.
- A WARC or WACZ, which `convert.py` unpacks when it finds one alone in a directory ([Making a WARC](making-warcs.md)). Tested on DCIC, CS168, and the OER Commons business communication book.
- An EPUB, through [`unpack-epub.py`](epub-input.md), whose content documents become pages. Tested on three publishers' EPUBs (Pressbooks, OER Commons, and Asciidoctor's) and on one this pipeline built: DCIC's, unpacked and converted again, keeps all 410 formulas and builds an EPUB epubcheck passes.
- A Common Cartridge exported from an LMS or a publisher, which `convert.py` unpacks when it finds one alone ([A course cartridge as the source](cartridge-input.md)). Tested on a Brightspace export and OpenStax's Canvas cartridge. Discussions, assignments, web links, test banks, and tool links are reported, not converted.

Pages are parsed with html5lib, or with lxml where html5lib isn't installed; DCIC's WARC unpacked and converted with each gives the same 80 pages. Whatever the route, scripts don't run, so a page a script draws in the browser has nothing to read; only what's inside a page's `<main>` is read when it has one; tags Pandoc has no element for (`<footer>`, `<nav>`, `<cite>`) go, their contents kept; a paragraph's class is lost; and an id with a space in it, which HTML doesn't allow, has its spaces made hyphens, links to it following. The full list is in [HTML sources](html.md).

**What it becomes**

- **HTML (round trip): TESTED.** Converting this pipeline's own pages changes nothing, which the suite checks. Real books: DCIC (80 pages), CS168 (a browser save, a WARC, and the site's own source agree on 62 pages), *Information Systems for Business and Beyond*, the business communication book, and both cartridges, including one this pipeline built, which converts back to the book it came from.
- **EPUB: TESTED.** epubcheck finds no errors in DCIC's, the business communication book's, or OpenStax's sociology cartridge's; the five in *Information Systems* are the publisher's own.
- **Markdown: TESTED.** The suite converts HTML to Markdown and back, formulas and banded tables included, and DCIC's 80 pages come back identical. They didn't until two fixes: a formula as MathJax 2 drew it nests spans eleven deep, which Pandoc's Markdown reader never got through, and a link to an id with a space in it isn't a link to that reader, so its address came back as words.
- **AsciiDoc: TESTED**, on DCIC: read back, 74 of its 80 pages are identical to the book converted directly. The other six each held a list with no items, which AsciiDoc can't write. Scribble's markup, spans nested in spans around links, code laid out in tables, quotations in quotations, is what most of the target's own forms were built against ([AsciiDoc as a target](asciidoc.md#asciidoc-as-a-target)).
- **Word: TESTED**, on DCIC: 80 files, valid against Word's schema, with 38 decorative images marked. Read back, 49 of 80 pages give the same HTML; most of the rest put a list inside a quotation, which Pandoc's reader takes back out.
- **PDF: NOT YET IMPLEMENTED.**

## AsciiDoc

**How it can arrive**

- Files in the book's directory, with a master file whose `include::`s give the book's order ([AsciiDoc sources](asciidoc.md)).
- An AsciiDoc target's output from an earlier conversion, which is written to be a source.
- A plain `.zip` of them.

**What it becomes**

- **HTML: TESTED**, on the security textbook (14 pages, its 54 cross-references by title resolved) and the suite. Asciidoctor's own settings (`:toc:`, `:icons:`, `:stylesheet:`, `:sectnums:`) are dropped. A block's `width` goes to the image it holds, or goes if it holds none, and a diagram's `target` goes: Pandoc passes both through onto elements where HTML doesn't allow them.
- **EPUB: TESTED.** The security textbook's EPUB passes epubcheck with no errors or warnings, and the suite builds one from a chapter with a sized image, a listing, and a table.
- **Markdown: TESTED.** The security textbook goes to Markdown and back with all 14 pages identical, and the suite converts a chapter the same way.
- **Word: TESTED**, on the security textbook: 14 files, valid against Word's schema. Read back, 9 of 14 pages give the same HTML; the rest have tables with merged cells, or figures holding more than one block, which Pandoc's writer lays out as a table.
- **PDF: NOT YET IMPLEMENTED.**
- **AsciiDoc: TESTED.** The security textbook goes to AsciiDoc and back with all 14 pages identical, and the suite round-trips a chapter holding every case the target writes itself ([AsciiDoc as a target](asciidoc.md#asciidoc-as-a-target)). Writing it again gives the same files.

## The outputs, and how each is packaged

### HTML

A directory of pages, one per target (`output_dir`), each page's images and linked files copied beside it under names that need no encoding in a link. `menu: on` adds a menu for posting the pages as a site. Packaged by [`build-cartridge.py`](packaging.md), which `convert.py` runs once `packaging.yaml` exists:

- **A Common Cartridge** (`format: common-cartridge`), written to the 1.1 profile, which every major LMS imports. `--zip` builds the `.imscc`; without it, the manifest is written with the `zip` command that would build it. A cartridge this pipeline builds converts back to the same pages and files.
- **The same package named `.zip`** (`format: zip`): the manifest and the pages as in the cartridge, in an archive named `.zip`.

SCORM packaging is planned once SCORM is taken up as output.

### EPUB

One `.epub` per `epub3` target, built by [`build-epub.py`](epub.md) from the same pages and the same contents, its accessibility claims computed from the build. An EPUB holds its own resources and a reading system follows links only among its pages, so every EPUB, whatever the input:

- makes an image on another server a link to it, named by its alt text;
- makes a frame a link to what it shows, a YouTube or Vimeo video's own page for a video;
- keeps a link to a local file (a PDF, a Word file) as its text only, and the output check lists each one as `link-to-file-dropped`;
- has no menu from `menu: on`, which HTML targets add for posting the pages as a site.

The `.epub` is itself the package: there's nothing further to package it in.

### Markdown

A directory of `.md` files whose media keep the author's names, written to be a source again. `merge: groups` makes one file per top-level group of the book's contents instead of one per page. It's packaged as the directory.

### AsciiDoc

A directory of `.adoc` files whose media keep the author's names, written to be a source again, as for Markdown. `merge: groups` works the same way. It's packaged as the directory. What the target writes itself, and the few things it changes, are in [AsciiDoc as a target](asciidoc.md#asciidoc-as-a-target).

### Word output

`format: docx` writes a Word file per page, or with `merge: groups` one per chapter. Pandoc's writer marks a header row to repeat, writes an image's alt text as its description, sets the language and title, and writes equations as Word's own. The target adds what it leaves out (`lib/docxtarget.py`): compatibility mode 15, without which Word opens the file in Compatibility Mode and won't run its Accessibility Checker; a link's title as its ScreenTip; Word's marker on a decorative image, without which the checker reports its empty description as missing; the First Column flag on a table whose first column heads its rows, and the bookmark JAWS reads as the table's headers (JAWS otherwise takes a Word table's first row and first column both for headers); and an indent for each level of a quotation, and for the code inside one, which Pandoc's writer gives every level alike, so a quote within a quote showed as one, with a blank paragraph between two quotations in a row, which Pandoc's reader would otherwise join. The media goes inside each file.

Read back as a source, a Word file gives back its text, headings, images and alt text, captioned figures, tables and header rows, link titles, decorative images, and math. What Word has no structure for is lost: a list inside a quotation comes back outside it, since Pandoc's reader never puts a numbered paragraph in a quote; a layout table becomes a data table, since Word keeps no mark of one; and a figure with no caption comes back as an image. Nested quotations, and a list item's second paragraph or code block, come back as they were. A table's headers read back as declared, from its JAWS bookmark, and a term with no definition, such as a review question, reads back as a term. The files validate against Word's schema with `tools/validate-docx.sh` from Pandoc's source, which wrongly rejects `m:sty` in an equation, as `PANDOC-NOTES.md` explains.

### PDF

NOT YET IMPLEMENTED: [on the roadmap](../ROADMAP.md). A target naming it is skipped with a warning. PDF waits on LaTeX's tagging support for complex table headers.
