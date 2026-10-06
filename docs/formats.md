# What goes in, what comes out

Every source format the pipeline reads, the ways a book in that format can arrive, what each can be turned into, how far each path has been tested, and how the output is packaged. The details live on each format's own page, linked from here.

## How the paths are rated

- **TESTED**: the test suite covers the path, and real books have gone through it and been checked: the [output check](checking.md) on every run, epubcheck for an EPUB, and `util/compare-output.py` for a round trip.
- **NEEDS MORE TESTING**: covered by the suite or by one book, or a real book showed a problem that isn't fixed yet.
- **NOT TESTED**: the code allows it, but neither a test nor a real book has taken the path.
- **NOT YET IMPLEMENTED**: an output the configuration names but nothing produces yet. A target declaring it is skipped with a warning. None is, now.
- **Not available**: an output no one has planned.

## At a glance

| Input | HTML | EPUB | Markdown | AsciiDoc | PDF | Word | LaTeX | Round trip to itself |
|---|---|---|---|---|---|---|---|---|
| Word (`.docx`) | TESTED | TESTED | TESTED | TESTED | TESTED | TESTED | NOT TESTED | TESTED, with losses (see [Word output](#word-output)) |
| Markdown (`.md`) | TESTED | TESTED | TESTED | TESTED | TESTED | TESTED | NEEDS MORE TESTING | TESTED |
| HTML (`.html`) | TESTED | TESTED | TESTED | TESTED | NEEDS MORE TESTING | TESTED | NOT TESTED | TESTED |
| AsciiDoc (`.adoc`) | TESTED | TESTED | TESTED | TESTED | TESTED | TESTED | NOT TESTED | TESTED |
| LaTeX (`.tex`) | TESTED | TESTED | NEEDS MORE TESTING | NEEDS MORE TESTING | TESTED | TESTED, with losses (see [Word output](#word-output)) | TESTED, with losses (see [LaTeX](#latex)) | TESTED, through the `latex` target, with losses (see [LaTeX](#latex)) |

LaTeX as an input is measured on *A Gentle Introduction to the Art of Mathematics* (GIAM) and a set of calculus notes ([LaTeX sources](latex.md)). Both PDFs pass veraPDF's PDF/UA-2 profile, GIAM's with the placeholder alt text LaTeX gives a figure until its image-alt sidecar is filled in, which the output check reports (`pdf-figure-alt-is-file-name`). Written out and read back, GIAM's 10 chapters give 9 identical pages through Markdown (one table's row headers come back as a header row), 8 through LaTeX (two figures holding a table come back as captioned tables), and 5 through AsciiDoc, where two figures holding a table come back as captioned tables, as through LaTeX, and a footnote, an image, and one table's inner cells still differ. [PDF output](#pdf) is new, and has been measured on a book from each input: the statistics book (Word), the economics book (Markdown), DCIC (HTML), and the security textbook (AsciiDoc). PDF is read only by [the audit](auditing.md), which reports on a Word, Markdown, HTML, EPUB, or PDF file without converting it.

## Word

**How it can arrive**

- Files in the book's directory: one `.docx` per chapter or section, or one for the whole book, which [the split](splitting.md) cuts into pages.
- A plain `.zip` of them, such as a publisher's DOCX download, which `convert.py` extracts when it finds the zip alone in a directory ([A book that arrives as an archive](first-run.md#a-book-that-arrives-as-an-archive)). Tested on OpenStax's download of *Introductory Business Statistics 2e*, its 169 files two folders deep: the same 169 pages and 253 images as the files converted from a folder.
- Inside a [Common Cartridge](cartridge-input.md): a Word file the course outline names is a source, and with `--linked-documents` so is one a page only links to.

A hyperlink's ScreenTip becomes the link's title, which the HTML and EPUB targets write as a tooltip and the Markdown and AsciiDoc targets keep. Pandoc 3.11's reader drops ScreenTips, so the pipeline recovers them itself. Pandoc 3.12's reader and writer handle them, with the change this project contributed ([pandoc#11890](https://github.com/jgm/pandoc/pull/11890)); the pipeline's own recovery is then a no-op, and stays for older versions.

Two repairs change what reading a Word file means, and each is a setting, decided once for the book and applied both to what the conversion reads and to a `source` target's copy, so the book and the author's file agree ([settings](conversion-settings.md)):

- **`word.tracked_deletions`.** Text deleted with Word's tracked changes is dropped on reading by default (`accept`), as Word's Accept All Changes and Pandoc drop it, and the run names each file that has any, since a before-and-after example loses its "before". `strike` keeps it as ordinary struck-through text, which reaches HTML as `<del>`.
- **`word.headings`.** Pandoc reads only `Heading 1` to `Heading 9` as headings. `from-toc` takes each file's heading levels from its own table-of-contents field; a map of style ids, `Title=Heading1,Heading1=Heading2`, is applied all at once, so it doesn't chain. A file the setting can't apply to, with no TOC field or not defining a style the map needs, is left as it is and named.

`util/restyle-headings.py` and `util/untrack-deletions.py` do the same to one file by hand ([Utilities](utilities.md)).

**What it becomes**

- **HTML: TESTED.** The census has read all nine books of the test corpus (1,782 files); the statistics, nursing, marketing, business communication, and programming books have been converted, and cartridges this pipeline builds have been imported into Brightspace. Lost on the way: a hyperlink's ScreenTip, which Pandoc's reader discards ([#11869](https://github.com/jgm/pandoc/issues/11869), agreed upstream), and the document's properties, since the title and author come from paragraphs styled Title and Author. Bookmarks Pandoc's reader would drop are repaired before it reads the file, and table headers come from Word's marks, the [sidecar](sidecars.md), or the guess.
- **EPUB: TESTED**, on the same books and the suite's fixtures. It loses what [every EPUB loses](#epub), as well.
- **Markdown: TESTED**, on the statistics book (merged by chapter) and the suite's round trip: read back, it gives the same HTML, and written again it's the same file. The first write normalizes Word's residue (paragraphs holding only a non-breaking space, stray spaces), so the second write is the fixed point. A table with merged cells, and a figure with an id, are written as fenced HTML, since Pandoc's Markdown can't express them; a banded table is kept as one table.
- **AsciiDoc: TESTED**, on the statistics book: read back, 166 of its 169 pages are identical to the book converted directly. Two lost a root with an index (`\sqrt[n]{…}`), which Pandoc's AsciiDoc reader can't read; the pipeline now reads around that, measured on a test page but not yet on that book again; and one lost a list's depth ([AsciiDoc as a target](asciidoc.md#asciidoc-as-a-target)).
- **Word: TESTED**, on the statistics book: 169 files, valid against Word's schema, with 229 header columns flagged. Read back as a book, 167 of its 169 pages give the same HTML, with no dead links; the other two are solutions pages, each with one list fewer ([Word output](#word-output)).
- **PDF: TESTED**, by the suite and on the statistics book: 948 pages, in which veraPDF finds nothing under the profiles it chooses for a PDF/UA-2 claim, with 3,046 header cells across its 342 tables, its cross-references given their visible text, its 270 figures in the reading order, 338 of its table captions tagged as captions, and its statistical tables' 79 cells that span rows tagged so. With its math repaired, every character in its equations is drawn; before, 54 were missing, the micro sign where μ was meant among them ([PDF](#pdf)).

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
- **PDF: TESTED.** The suite's book, and the whole economics book, pass veraPDF's PDF/UA-2, PDF/A-4f, and WTPDF profiles, and the economics book's structure matches its author's own build ([PDF](#pdf)).

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
- **Word: TESTED**, on DCIC: 80 files, valid against Word's schema, with 38 decorative images marked. Read back, 57 of 80 pages give the same HTML, with no dead links; on most of the rest an image comes back under the name Word gives it, and on others a list or a layout table differs. Every page but four has the source's number of quotations.
- **PDF: NEEDS MORE TESTING**, on DCIC, from its WARC: 509 pages. It needed two fixes before it would build cleanly: headings below a subsection that run in to a following section had stopped LaTeX's tagging, and five blocks of code set as quotations inside table cells broke a PDF structure rule. 16 black-flag emoji remain undrawn, as no installed font draws one in a way veraPDF accepts ([PDF](#pdf)).

## AsciiDoc

**How it can arrive**

- Files in the book's directory, with a master file whose `include::`s give the book's order ([AsciiDoc sources](asciidoc.md)).
- An AsciiDoc target's output from an earlier conversion, which is written to be a source.
- A plain `.zip` of them.

**What it becomes**

- **HTML: TESTED**, on the security textbook (14 pages, its 54 cross-references by title resolved) and the suite. Asciidoctor's own settings (`:toc:`, `:icons:`, `:stylesheet:`, `:sectnums:`) are dropped. A block's `width` goes to the image it holds, or goes if it holds none, and a diagram's `target` goes: Pandoc passes both through onto elements where HTML doesn't allow them.
- **EPUB: TESTED.** The security textbook's EPUB passes epubcheck with no errors or warnings, and the suite builds one from a chapter with a sized image, a listing, and a table.
- **Markdown: TESTED.** The security textbook goes to Markdown and back with all 14 pages identical, and the suite converts a chapter the same way.
- **Word: TESTED**, on the security textbook: 14 files, valid against Word's schema. Read back, 12 of 14 pages give the same HTML, with no dead links; the other two have tables with merged cells, or figures holding more than one block, which Pandoc's writer lays out as a table.
- **PDF: TESTED**, by the suite and on the security textbook: 161 pages, passing veraPDF, its SVG diagrams converted with their alt text kept, and its code callouts drawn with the DejaVu Sans fallback. Its 22 images have no alt text in the source, which the output check reports for the PDF as for the HTML ([PDF](#pdf)).
- **AsciiDoc: TESTED.** The security textbook goes to AsciiDoc and back with all 14 pages identical, and the suite round-trips a chapter holding every case the target writes itself ([AsciiDoc as a target](asciidoc.md#asciidoc-as-a-target)). Writing it again gives the same files.

## LaTeX

**How it can arrive**

- A master file in the book's directory, with `\documentclass` and `\begin{document}`, that `\include`s the chapters; `latex.main` names it when there are several ([LaTeX sources](latex.md)).

**What it becomes**

- **HTML: NEEDS MORE TESTING**, on the suite's book and on GIAM: 10 pages, its 93 xfig drawings rendered by LaTeX, its 19 references between chapters resolved, all but 6 of about 4,500 formulas made MathML, and the Nu checker finding nothing the book doesn't lack itself (alt text, table descriptions).
- **EPUB: NEEDS MORE TESTING**, on GIAM: epubcheck passes, with the same findings as the HTML.
- **PDF: NEEDS MORE TESTING.** Through Pandoc, as for any source. GIAM's long division, a table inside a table, stopped LaTeX until the PDF target wrote a nested table as lines of text. The book's own PDF, made by LaTeX from its own source with tagging on, is next on the [roadmap](../ROADMAP.md).
- **Markdown, AsciiDoc, Word: NOT TESTED.**
- **A round trip to itself: Not available.** There is no LaTeX target yet.

## The outputs, and how each is packaged

### HTML

A directory of pages, one per target (`output_dir`), each page's images and linked files copied beside it under names that need no encoding in a link. `menu: on` adds a menu for posting the pages as a site. Packaged by [`build-cartridge.py`](packaging.md), which `convert.py` runs once `packaging.yaml` exists:

- **A Common Cartridge** (`format: common-cartridge`), written to the 1.1 profile, which every major LMS imports. `--zip` builds the `.imscc`; without it, the manifest is written with the `zip` command that would build it. A cartridge this pipeline builds converts back to the same pages and files.
- **The same package named `.zip`** (`format: zip`): the manifest and the pages as in the cartridge, in an archive named `.zip`.

SCORM packaging is planned once SCORM is taken up as output.

### A page's title

A page's title heading, the H1 that names it, is its own heading in every output: the HTML's body `<h1>`, with the title in `<title>`; a Word file's Heading 1, with the title in the file's properties; Markdown's and AsciiDoc's `#` heading; the EPUB's and PDF's chapter heading. Inside the pipeline it's kept in the page's metadata, where the split, the contents, and the numbering read it, and each writer puts it back in its own words, with its id.

A title the source declares stands (`promote_h1_to_title: if-absent`, the default): Markdown's `title`, HTML's `<title>`, a Word paragraph styled Title. The page's only H1 is its title heading when it says that title, the same or one inside the other, judged as a reader would (curly and straight quotes alike, case aside), as "1.1 Definitions of Statistics" under a Word Title "Definitions of Statistics" does, or "A Web Page" under a `<title>` of "A Web Page -- The Site"; it is shown once, and the declared title is the page's `<title>`. An H1 that says something else is a heading of its own, and the declared title is shown above it. `shorter` takes the H1 as the title when the declared one is it plus more, as a site's name; `always` takes it in any case. The run says when pages keep a declared title without the section number their heading puts before it, as an OpenStax book's do: their `<title>`, and the names a cartridge gives them, then have no number, and `always` keeps it. A `format: source` copy keeps the author's title whatever the setting.

An EPUB or PDF opens with a title page (`title_page: auto`) when the book's structure calls for one, whatever its number of files: more than one top-level entry, or one page with more than one top-level heading or something before its title heading, as a byline. A document whose one top-level heading is its title has none, and the title is in the file's metadata.

### EPUB

One `.epub` per `epub3` target, built by [`build-epub.py`](epub.md) from the same pages and the same contents, its accessibility claims computed from the build. An EPUB holds its own resources and a reading system follows links only among its pages, so every EPUB, whatever the input:

- makes an image on another server a link to it, named by its alt text;
- makes a frame a link to what it shows, a YouTube or Vimeo video's own page for a video;
- keeps a link to a local file (a PDF, a Word file) as its text only, and the output check lists each one as `link-to-file-dropped`;
- has no menu from `menu: on`, which HTML targets add for posting the pages as a site.

The first three are reported in `fidelity.csv`, each by what it names (the image's address, the frame's title, the file), since the EPUB is built from the whole book at once.

The `.epub` is itself the package: there's nothing further to package it in.

### Markdown

A directory of `.md` files whose media keep the author's names, written to be a source again. `merge: groups` makes one file per top-level group of the book's contents instead of one per page. It's packaged as the directory. Pandoc's Markdown writer writes an example list as a numbered list, which reads back as one, so the examples' numbering no longer runs on through the document; the run reports each in `fidelity.csv`.

### AsciiDoc

A directory of `.adoc` files whose media keep the author's names, written to be a source again, as for Markdown. `merge: groups` works the same way. It's packaged as the directory. What the target writes itself, and the few things it changes, are in [AsciiDoc as a target](asciidoc.md#asciidoc-as-a-target); each change is reported in `fidelity.csv` as well as on the terminal.

### Word output

`format: docx` writes a Word file per page, or with `merge: groups` one per chapter, with the media inside each file. Pandoc's writer marks a header row to repeat, writes an image's alt text as its description, sets the language and title, and writes equations as Word's own. The target adds what it leaves out (`lib/docxtarget.py`). What each addition is for rests on documentation, not on tests with Word or a screen reader here; the files themselves are tested, and validate against Word's schema.

- **Compatibility mode 15.** Pandoc's reference document declares none, so Word opens its files in Compatibility Mode, and according to accessibility guides for Word ([Texas Governor's Committee on People with Disabilities](https://gov.texas.gov/uploads/files/organization/disabilities/02_AccChecker.pdf)) and [reports on Microsoft's Q&A](https://learn.microsoft.com/en-us/answers/questions/5386194/unable-to-run-accessibility-checker), the Accessibility Checker won't run until the file is converted.
- **A link's title as its ScreenTip**, which Pandoc 3.11's writer drops and 3.12's writes.
- **Word's "Mark as decorative"** on a decorative image ([Microsoft's documentation](https://support.microsoft.com/en-us/accessibility/office-accessibility/add-alternative-text-to-a-shape-picture-chart-smartart-graphic-or-other-object)); without it, the checker reports the empty description as missing alt text. Guides describe the checkbox from Word 2019 and Microsoft 365 on, and an earlier Word reports the image as undescribed.
- **The First Column flag** on a table whose first column heads its rows, and **a bookmark naming the table's headers**, `Title`, `ColumnTitle`, or `RowTitle`: the convention [Freedom Scientific documents](https://doccenter.freedomscientific.com/doccenter/archives/training/samplefiles/usethebookmarkfeatureinwordfortableheaders-oldertechnique.htm) for JAWS, on a page it calls an older technique. A [2017 Freedom Scientific bulletin](https://support.freedomscientific.com/support/technicalsupport/bulletin/1633) says JAWS otherwise reads a Word table's first row and first column both as headers. Neither is tested with JAWS here. The table census reads the same bookmarks back as the table's declaration, which is tested.
- **An indent for each level of a quotation**, and for the code inside one, which Pandoc's writer gives every level alike, with a blank paragraph between two quotations in a row, and between two code blocks in a row, which Pandoc's reader would otherwise join. A list inside a quotation is indented a quotation's step beyond its own level, which Pandoc's writer leaves at the margin, and the file says so in a document variable (`TextbookImproverQuotedLists`), which Word keeps and shows nowhere: Pandoc's reader never puts a list in a quotation, and reading such a file puts it back. The same indent, and the same variable, carry a quotation inside a list item, which Pandoc's reader would give back one quotation a paragraph, and code in a quotation, which it gives one level however deep; reading such a file nests each again. A quoted list's own paragraphs are written Body Text, with the quotation's indent, rather than Block Text, which the reader would quote again. And two quotations that only Divs kept apart get the blank paragraph between them too, since Word keeps no Divs. An author's own Word file, without the variable, may indent a list for other reasons, a numbered step's sub-items, and is read as Pandoc reads it.
- **Numbered code lines**, as text: each line's number in a run of Word's own "Line Number" character style, so a reader of the Word file sees them, from the block's first number. Reading the file back takes them out and numbers the block again. Copying code out of Word copies the numbers with it.
- **A code block's language**, which its highlighting depends on, in a hidden bookmark in its paragraph (`_tiqCode_python_1`), read back by matching the block's text. A language whose name holds anything but letters and digits can't go in a bookmark name, and is reported instead.
- **"Keep with next" on a table's caption.** Pandoc writes the caption before the table without it, and its reader pairs such a caption with the table before, so a table with no caption took the next one's. A workaround until Pandoc's writer or reader changes.
- **A map of the ids Pandoc renamed.** Pandoc's writer renames an id that isn't a valid Word bookmark name, one that doesn't start with a letter, like every Asciidoctor section id, or that runs past 40 characters, to `X` and a hash. The target records each such name in a custom XML part of the file, so the ids come back as they were and a link from another page still lands. That Word keeps such a part when it saves an edited file isn't tested here; if it doesn't, the ids come back hashed, as before the map.
- **Only the bookmarks something uses** (`bookmarks: linked`, the default). Pandoc's writer bookmarks every heading and section, and NVDA announced "bookmark" at each, at the end of a section with Pandoc 3.12's placement and at the heading with a bookmark moved into it. The target keeps a bookmark a link in the book goes to, from its own page or another, JAWS's table header bookmarks, and the bookmarks that carry a code block's language, and removes the rest; then NVDA announced none, in the tables too. `bookmarks: all` keeps every one.

The post-processing finds what it changes by marks the target puts on the elements before Pandoc writes them, bookmarks around each table, decorative image, quotation, and code block, never by counting: a figure holding two images is written as a table, so a page's third Word table can be its second table. The marks are removed afterward.

**What a Word file can't carry** is known before it's written, and each run reports it in `fidelity.csv`, a row per page and kind, with a line per target on the terminal:

| Loss | What happens |
|---|---|
| `uncaptioned-figure` | A figure with no caption comes back as an image. |
| `figure-table` | A figure holding a table comes back as the table, the figure's caption as the table's description. |
| `code-language` | A code block's language, and so its highlighting, is lost, when its name holds more than letters and digits. |
| `layout-table` | A layout table comes back as a data table, since Word keeps no mark of one. |
| `frame` | A frame, a video say, becomes a link to what it shows. |
| `cell-headers` | A table's cells lose the header cells they name (`headers`); its header rows and column stay. |

Read back as a source, a Word file gives back its text, headings, images and alt text, captioned figures, tables and header rows, link titles, decorative images, math, nested quotations and the lists and code inside them, a quotation inside a list item, a list item's second paragraph or code block, and numbered and highlighted code. A term with no definition, such as a review question, reads back as a term. Measured on four books: the statistics book gives the same HTML on 167 of its 169 pages, DCIC on 57 of 80, and the security textbook on 12 of 14, with no dead links in any. The schema check is `tools/validate-docx.sh` from Pandoc's source, which wrongly rejects `m:sty` in an equation, as `PANDOC-NOTES.md` explains.

### Source

`format: source` gives the book's own files back, remediated, one copy of each in the target's folder under its original name; the originals are never touched. What it writes is only what a person decided in the sidecars, never a guess: a guess written into the author's file would read back as the file's own declaration, and nothing would say it was never reviewed.

For a Word file, it's the remediated copy described under [Utilities](utilities.md#a-remediated-copy-of-a-word-file): each table's header declaration from the table-headers sidecar; a table's description from the table-captions sidecar, as a paragraph in Word's Caption style above a table with no label, kept with it, or joined to the end of a label paragraph beside it; alt text and decorative marks from the image-alt sidecar; a link's title from the bare-links sidecar, and its replacement address, in the link's address and a bare link's text; the book's language as the document's default when the file declares none; and the book's `word.headings` and `word.tracked_deletions`, as the conversion reads it ([Word](#word)). It's all written into the file's XML, with every part nothing decided copied byte for byte. On the statistics book, with its prefilled header rows adopted and a placeholder description for every table: 308 tables got header rows and 229 a header column, all 262 descriptions were joined to their tables' label paragraphs (OpenStax wraps each table in a bookmark, which the matching passes over), and the copies sampled fail Word's schema check with exactly their originals' errors, OpenStax's own. So the first run on a book changes no table: the census's guesses go to `table-headers-new.csv` as usual, the run says how many tables it left to their guess, and adopting their rows into `table-headers.csv` is what gets them written on the next run. `compatibility_mode` keeps the author's compatibility mode unless it's set to `"15"`.

For a hand-maintained HTML page, the same decisions are written into its markup as text edits, the rest of the page exactly as the author wrote it, comments and indentation included: a declared header row's cells become `<th scope="col">` and a header column's `<th scope="row">`, an image gets its `alt` (`alt=""` for `[decorative]`), a bare link its title and its replacement address, which replaces both the address and the text, and `<html>` gets the book's language as `lang` when it has none. A table with no label anywhere gets its description from the table-captions sidecar as its `<caption>`, and one whose label is a paragraph beside it gets the description joined to the end of that paragraph, where it stands, as the rendered page joins it. The sidecar's key names a table as the pipeline sees the page, which can differ from the file (the reader splits a table at a header row in its body, and a table holding only an image isn't counted), so the filter records which table it gave each description to, and which side of it a label paragraph was on, and the copy finds that table by position, row count, and first cell, as it does for headers. A table or label paragraph that isn't what the filter saw is skipped, and the run says how many. A page saved from a platform (Pressbooks, EdTech Books, a WACZ archive) is better fixed in the platform, since that's where it's maintained.

For a Markdown file, the same decisions are written into the text where each element is, and nothing else changes: nothing is parsed and written again, so every construct Pandoc Markdown has survives exactly as the author wrote it. An image gets its alt text between `![` and `]`, and `[decorative]` empties it and adds `.decorative` to the image's own attributes; a bare link, `<url>` or `[url](url)`, becomes `[replacement](replacement "title")`, since `<url>` can't carry a title; a table with no caption gets a `Table:` line after it, inside its div if it's in one, or a label paragraph beside it gets the description joined; and the front matter gets `lang`. Each element is found by rules that follow Pandoc's own, not CommonMark's (an image's path runs to the parenthesis that balances the opening one, spaces and all), and changed only when Pandoc's reading confirms it: an image or link only when the text holds its syntax as many times as Pandoc reads it, which rules out the same syntax inside code, and a table only in a stretch of lines Pandoc's reader reads as exactly that table. Anything unconfirmed is left as it is, and the run says how many.

On the author's own Pandoc Markdown book, 34 chapters, with a bare-links sidecar built by pairing its links with the version the author had already fixed by other means: all 30 bare links in the copy match that version, 19 of them with a shortDOI, every changed line is a link or an image, and every image, bare link, and table in the book (50, 30, and 21, 8 of the tables in the author's own marker divs) can be found.

For a LaTeX book, every `.tex` file the master reaches is written at the same path under the target's folder, ready to lay over the author's tree, and each image and drawing gets its alt text from the image-alt sidecar as the `alt` key LaTeX's own tagging reads: `\includegraphics[alt={...}]`, `\begin{picture}[alt={...}]`, `\begin{tikzpicture}[alt={...}]`, beside the author's own keys, and `artifact` for `[decorative]`. The book's `latex-conversion-macros.tex` goes after the copy's preamble, as the conversion reads it, unless `latex_definitions` is `"off"`; with `tagging: "on"`, the copy is made to build with LaTeX's tagging, and each table a person decided gets its header declaration. The rest is written as the author wrote it ([LaTeX sources](latex.md#the-source-target)).

A copy gets the book's language only when the book declares one (`project.language`), for Word, HTML, and Markdown alike: the default isn't anyone's decision.

AsciiDoc sources aren't written yet; the run names them as left out. The `markdown` and `asciidoc` targets are close for a Markdown or AsciiDoc source, since they write back what the sidecars decided, but they write the book's pages, not its files, and Pandoc's writer re-serializes the rest, so line wrapping and markup choices change.

```yaml
targets:
  html:
    format: html
  fixed:
    format: source
```

The target's name is yours, and names its folder. Two `source` targets write the same copies unless their `compatibility_mode` differs, since the sidecars are the book's, not a target's; a run with two that would write the same copies warns that one would do.

### PDF

One tagged PDF of the whole book, assembled from the pages as the EPUB is and written by Pandoc's LaTeX writer and LuaLaTeX, with LaTeX's tagging switched on by the PDF/UA standard the target declares (`pdf.standard`, `ua-2` by default). It needs LuaLaTeX from TeX Live 2026 ([installation](installation.md#for-a-pdf-target-lualatex)); the output check runs [veraPDF](installation.md#optional-verapdf) on it when that's installed.

```yaml
targets:
  pdf:
    format: pdf
```

**What the run adds to Pandoc's writer**, each because the writer has no way to say it (read in Pandoc 3.11's and 3.12's `Writers/LaTeX.hs` and `Writers/LaTeX/Table.hs`):

- A table's declared header column is tagged as row headers. The writer folds a body's row-head cells into ordinary cells, so the run sets latex-lab's `table/header-columns` around the table. Header rows need nothing: the writer puts the head in `longtable`'s repeated head, which latex-lab tags as header cells.
- A decorative image is an artifact. latex-lab tags an image with no alternative text as a figure described by its own file name (the `alt-text-missing` warning in `latex-lab-testphase-graphic.sty`), which veraPDF accepts; the output check reports any figure so described as `pdf-figure-alt-is-file-name`.
- Every link the book's text makes gets a `/Contents`: its visible text, then its description in parentheses when it has one (its title, which is where the [bare-links sidecar](bare-links.md) puts a description). The visible text comes first because [WCAG 2.5.3](https://www.w3.org/WAI/WCAG21/Understanding/label-in-name.html) wants the accessible name to hold what is seen. LaTeX's own links, the contents lines and footnote marks, get none, since hyperref's default is the address or "Go to destination" and an id.
- Each formula carries its MathML twice: as structure elements under the formula, and as a MathML file attached to it (`math/setup={mathml-SE,mathml-AF}`).
- Characters the fonts lack are drawn. Latin Modern, the template's fonts when none is chosen, has no Greek and few mathematical symbols, and the statistics book writes μ, σ, ≤, ≈, and a dozen others as text. Latin Modern Math has them, and fills in for each font family the `pdf.metadata` file doesn't choose, and DejaVu Sans after it when it's installed, for what neither Latin Modern font has: the circled digits an AsciiDoc book's code callouts are, 58 of them in the security textbook. A character no font has is still lost, in one of two ways: in an OpenType font it's drawn as the blank `.notdef` glyph, which veraPDF reports (PDF/UA-2 clause 8.4.5.9); in LaTeX's older math fonts, which an equation falls back to for a character unicode-math doesn't handle, it's dropped without a trace, and veraPDF finds nothing. Either way the build names each missing character in one warning with its code point and count. The statistics book had 54 of the second kind, the micro sign µ where the Greek μ was meant among them, all in math typed as text; [repaired](#word), its equations have none.

**Structure comes from the book, numbering from LaTeX.** Pages are placed by `project.contents`, as for the EPUB, and a page's role becomes the division command it stands for (`\frontmatter`, `\mainmatter`, `\appendix`, `\backmatter`) where the role changes; the source's own copies of those commands, read into the roles when the book was converted, are dropped. The book opens in the front matter, so its title page and contents are numbered in roman with the rest of the front matter. LaTeX numbers chapters and sections when the book's `numbering` is on; titles carry no numbers of their own. A book whose titles already carry numbers, as OpenStax's do, keeps `numbering` off, or each heading is numbered twice. A `generate: toc` entry in `project.contents` is where the contents go; without one, they follow the title page.

**A book written for a Pandoc PDF build keeps its settings.** `pdf.metadata` names the file that held its YAML, a `_preamble.md` say, and whatever it sets (class, class options, `header-includes`, fonts, `include-before`, `toc-depth`) goes to the writer, ahead of `project.yaml` and the target's settings. The page made from that file, when it's titled by the book's title as a preamble is, gets no heading: the title block LaTeX draws is its heading. Its packages have to be installed, and a class without `\frontmatter` gets only `\appendix` from the roles.

**Figures stay where the text has them** (`pdf.figures: in_place`, the default). LaTeX's tagging gathers the tags of every figure that floats into one place at the end of the document, where a screen reader reaches them after everything else; in the statistics textbook's PDF that was 246 of its 270 figures, and veraPDF doesn't report it. `in_place` places each figure H, as the economics book's preamble already did, so it stays put on the page and in the reading order. `section` lets a figure float within its section and puts its tags right after the section's text; `float` is LaTeX's own placement, tags at the end.

**Table captions are retagged after LaTeX** (`pdf.repair_captions`, on by default, needs `pikepdf`). LaTeX's tagging code writes a `longtable` caption as a first row of one header cell spanning the table, and leaves an empty copy of the repeated head inside the table ([latex3/tagging-project#1583](https://github.com/latex3/tagging-project/issues/1583)); NVDA in Acrobat Reader read the caption as row 1, and counted four rows and six columns in a three-by-three table. `lib/pdfretag.py` makes that cell the table's Caption and takes the empty copy out, and NVDA then read "Caption. Table 1 Output and price by year. Out of caption." and three rows and three columns. Only a table the book gave a caption is touched, matched to the PDF's tables in order, and nothing at all when the PDF's tables don't number the book's; only the first row, and only a row of one header cell. On the statistics textbook: 338 of its 342 captions retagged and 308 empty heads taken out.

**Paragraph elements LaTeX leaves empty are removed** (`pdf.remove_empty_paragraphs`, on by default, needs `pikepdf`). Its tagging code opens a paragraph element around a longtable caption, in a header cell whose text wraps, in the repeated head, and around an image scaled to fit, and puts nothing in it. NVDA read a test file the same with them and without, but [PDF4WCAG](https://pdf4wcag.com/)'s WCAG 2.2 Machine profile reports each one (its rule 4.1.2-16), and the same file without them came back clean there. `lib/pdfparagraphs.py`, run after the caption repair, deletes them and turns what they marked into artifacts. On the economics textbook it removed 120 and on the statistics textbook 3,449, with each book's page text, read back with `pdftotext`, exactly as before, the same tables, figures, formulas, and links, and veraPDF still passing. `util/fix-empty-paragraphs.py` does it to a PDF made some other way.

**Headings below a subsection stand on their own line** (Pandoc's `block-headings`, on unless the `pdf.metadata` file says otherwise). LaTeX runs such a heading in to the text after it, and two of them followed straight by another section left its paragraph tagging one paragraph short, which stopped DCIC's PDF.

**A quotation inside a table cell is unwrapped** to what it holds, since a PDF's structure doesn't allow a block quotation in a table cell (ISO/TS 32005; veraPDF reports it). DCIC sets code side by side in a table that way.

**PDF/UA-1 too** (`pdf.standard: [ua-1]`), for checkers such as PAC that test only PDF/UA-1. The file is PDF 1.7. PDF 1.7 has no standard way to tag MathML, so each formula is tagged as a Formula with LaTeX's own alternative text (its TeX source, between "LaTeX formula starts" and "ends", which a screen reader reads as written) and its MathML attached as a file; `pdf.ua1_math: office` also writes the MathML as Microsoft Office's own attribute on the formula, the one Word puts in the PDFs it saves, through LaTeX's `mathml-MS` option. A book with equations gets a warning saying so. PDF/UA-1 also asks for a description on every link: LaTeX's own links (contents lines, cross-references it makes) get hyperref's, "Go to destination" and its name, while the book's own links keep their text and description, and a footnote mark isn't made a link. The security textbook built this way passes veraPDF's PDF/UA-1 profile, and so does a one-page book, whose title is its level-1 heading.

**A title page when the book's structure calls for one** (`title_page: auto`): a book of more than one top-level entry, or a page with more than one top-level heading or something before its title heading. A document whose one top-level heading is its title has none, and its title is the PDF's metadata title and its first heading ([A page's title](#a-pages-title)). A one-page book is in the main matter, numbered 1, 2, 3, unless its page is front matter.

**A cell that spans rows is tagged so.** Pandoc sets it with `\multirow`, which LaTeX's tagging doesn't follow: the cell would be tagged as its first row's only, and each row it covers given an empty cell of its own. The run says `table/multirow` in each such cell, and since LaTeX's record of the cells a span covers outlives a long table, so that the next table would lose its cells at the same places, it clears that record as each table begins. The statistics book's statistical tables have 79 such cells.

**What it loses, or can't yet do:**

- latex-lab's table tagging supports header rows and columns only, so a table whose cells need a `Headers` list to name their headers (headers at several levels, or headers mid-table) can't be tagged fully. The table-headers work splits banded tables for PDF, as for HTML, which removes the commonest case.
- An SVG image needs `rsvg-convert`: Pandoc turns it into a PDF before LaTeX sees it, and it keeps its alternative text. Without `rsvg-convert` Pandoc's LaTeX writer would fall back to `\includesvg`, which passes no alternative text at all, so a book with an SVG stops before LaTeX and says what to install.
- `notes.placement` and `notes.numbering` don't apply: LaTeX puts each note at the foot of its page.

Measured on Pandoc 3.11, LaTeX 2026-06-01, and veraPDF 1.30.2: the suite's book, and the whole Markdown economics textbook (431 pages, 1,141 formulas, 50 figures, 21 tables), pass PDF/UA-2 with Tagged PDF, PDF/A-4f, and both WTPDF 1.0 profiles with no rule failed. Under Pandoc 3.12, the Word statistics textbook (948 pages, 3,609 formulas, 342 tables), with its math repaired, passes the profiles veraPDF chooses for its PDF/UA-2 claim with nothing found. The economics book rebuilt under Pandoc 3.12 has the same structure, element for element. The economics book's PDF has the same structure as the one its author builds with his own Pandoc command (the same chapters, sections, contents entries, formulas, figures, and table cells), with a `/Contents` on every external link, and without the second run of roman page numbers that command's front matter produced.

A book whose `contents` isn't declared gets the filename guess. For the economics book, one file per chapter, the guess gives the same structure as its author's build: each file a chapter, the preamble front matter, the appendices after `\appendix`, and the glossary in the back matter.


### LaTeX

The LaTeX the [PDF](#pdf) is built from, for an author to go on working in: a master file named for the book's identifier, which `\include`s a file per entry at the top of `project.contents` (a chapter's page, or a group under its first page's name), with the images they show beside them at their own paths. What stands between chapters stays in the master: the preamble, with `\DocumentMetadata` and the tagging setup the PDF target writes, the division commands, and the contents.

```yaml
targets:
  latex:
    format: latex
```

The run's decisions are where LaTeX's tagging reads them, as in the PDF: alt text on each `\includegraphics`, `artifact` for a decorative image, a table's header columns declared around it, and header rows in `longtable`'s head. An SVG image is made a PDF beside it with `rsvg-convert`, as Pandoc's own PDF route does, since the writer would give it `\includesvg`, which needs Inkscape and takes no alt text. Nothing is built; `latexmk -lualatex <identifier>.tex` in the folder builds it, running LuaLaTeX, BibTeX, and makeindex as many times as the book needs. Read back as a [LaTeX source](latex.md), each chapter gives the same page it was written from: the suite's book, and 8 of GIAM's 10 chapters, by `util/compare-output.py`; the master's own content, the title and contents, becomes a page of its own. What it can't carry is what the PDF can't either: a figure holding only a table is written as the table with the figure's caption, since a longtable can't float, and a figure inside a figure as one figure with one caption, the inner one's caption a paragraph under its content. A table inside a table's cell is a `tabular`, its head declared for tagging.