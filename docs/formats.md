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

Two repairs change what reading a Word file means, and each is a setting, decided once for the book and applied both to what the conversion reads and to a `source` target's copy, so the book and the author's file agree ([settings](conversion-settings.md)):

- **`word.tracked_deletions`.** Text deleted with Word's tracked changes is dropped on reading by default (`accept`), as Word's Accept All Changes and Pandoc drop it, and the run names each file that has any, since a before-and-after example loses its "before". `strike` keeps it as ordinary struck-through text, which reaches HTML as `<del>`.
- **`word.headings`.** Pandoc reads only `Heading 1` to `Heading 9` as headings. `from-toc` takes each file's heading levels from its own table-of-contents field; a map of style ids, `Title=Heading1,Heading1=Heading2`, is applied all at once, so it doesn't chain. A file the setting can't apply to, with no TOC field or not defining a style the map needs, is left as it is and named.

`util/restyle-headings.py` and `util/untrack-deletions.py` do the same to one file by hand ([Utilities](utilities.md)).

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

A directory of `.md` files whose media keep the author's names, written to be a source again. `merge: groups` makes one file per top-level group of the book's contents instead of one per page. It's packaged as the directory. Pandoc's Markdown writer writes an example list as a numbered list, which reads back as one, so the examples' numbering no longer runs on through the document; the run reports each in `fidelity.csv`.

### AsciiDoc

A directory of `.adoc` files whose media keep the author's names, written to be a source again, as for Markdown. `merge: groups` works the same way. It's packaged as the directory. What the target writes itself, and the few things it changes, are in [AsciiDoc as a target](asciidoc.md#asciidoc-as-a-target); each change is reported in `fidelity.csv` as well as on the terminal.

### Word output

`format: docx` writes a Word file per page, or with `merge: groups` one per chapter, with the media inside each file. Pandoc's writer marks a header row to repeat, writes an image's alt text as its description, sets the language and title, and writes equations as Word's own. The target adds what it leaves out (`lib/docxtarget.py`). What each addition is for rests on documentation, not on tests with Word or a screen reader here; the files themselves are tested, and validate against Word's schema.

- **Compatibility mode 15.** Pandoc's reference document declares none, so Word opens its files in Compatibility Mode, and according to accessibility guides for Word ([Texas Governor's Committee on People with Disabilities](https://gov.texas.gov/uploads/files/organization/disabilities/02_AccChecker.pdf)) and [reports on Microsoft's Q&A](https://learn.microsoft.com/en-us/answers/questions/5386194/unable-to-run-accessibility-checker), the Accessibility Checker won't run until the file is converted.
- **A link's title as its ScreenTip**, which Pandoc 3.11's writer drops.
- **Word's "Mark as decorative"** on a decorative image ([Microsoft's documentation](https://support.microsoft.com/en-us/accessibility/office-accessibility/add-alternative-text-to-a-shape-picture-chart-smartart-graphic-or-other-object)); without it, the checker reports the empty description as missing alt text. Guides describe the checkbox from Word 2019 and Microsoft 365 on, and an earlier Word reports the image as undescribed.
- **The First Column flag** on a table whose first column heads its rows, and **a bookmark naming the table's headers**, `Title`, `ColumnTitle`, or `RowTitle`: the convention [Freedom Scientific documents](https://doccenter.freedomscientific.com/doccenter/archives/training/samplefiles/usethebookmarkfeatureinwordfortableheaders-oldertechnique.htm) for JAWS, on a page it calls an older technique. A [2017 Freedom Scientific bulletin](https://support.freedomscientific.com/support/technicalsupport/bulletin/1633) says JAWS otherwise reads a Word table's first row and first column both as headers. Neither is tested with JAWS here. The table census reads the same bookmarks back as the table's declaration, which is tested.
- **An indent for each level of a quotation**, and for the code inside one, which Pandoc's writer gives every level alike, with a blank paragraph between two quotations in a row, and between two code blocks in a row, which Pandoc's reader would otherwise join.
- **Numbered code lines**, as text: each line's number in a run of Word's own "Line Number" character style, so a reader of the Word file sees them, from the block's first number. Reading the file back takes them out and numbers the block again. Copying code out of Word copies the numbers with it.
- **A code block's language**, which its highlighting depends on, in a hidden bookmark in its paragraph (`_tiqCode_python_1`), read back by matching the block's text. A language whose name holds anything but letters and digits can't go in a bookmark name, and is reported instead.
- **"Keep with next" on a table's caption.** Pandoc writes the caption before the table without it, and its reader pairs such a caption with the table before, so a table with no caption took the next one's. A workaround until Pandoc's writer or reader changes.
- **A map of the ids Pandoc renamed.** Pandoc's writer renames an id that isn't a valid Word bookmark name, one that doesn't start with a letter, like every Asciidoctor section id, or that runs past 40 characters, to `X` and a hash. The target records each such name in a custom XML part of the file, so the ids come back as they were and a link from another page still lands. That Word keeps such a part when it saves an edited file isn't tested here; if it doesn't, the ids come back hashed, as before the map.

The post-processing finds what it changes by marks the target puts on the elements before Pandoc writes them, bookmarks around each table, decorative image, quotation, and code block, never by counting: a figure holding two images is written as a table, so a page's third Word table can be its second table. The marks are removed afterward.

**What a Word file can't carry** is known before it's written, and each run reports it in `fidelity.csv`, a row per page and kind, with a line per target on the terminal:

| Loss | What happens |
|---|---|
| `list-in-quotation` | A list inside a quotation comes back outside it, the quotation split around it: Pandoc's reader never puts a numbered paragraph in a quote. |
| `uncaptioned-figure` | A figure with no caption comes back as an image. |
| `code-language` | A code block's language, and so its highlighting, is lost, when its name holds more than letters and digits. |
| `layout-table` | A layout table comes back as a data table, since Word keeps no mark of one. |
| `cell-headers` | A table's cells lose the header cells they name (`headers`); its header rows and column stay. |

Read back as a source, a Word file gives back its text, headings, images and alt text, captioned figures, tables and header rows, link titles, decorative images, math, nested quotations, a list item's second paragraph or code block, and numbered and highlighted code. A term with no definition, such as a review question, reads back as a term. Measured on four books: the statistics book gives the same HTML on 135 of its 169 pages, DCIC on 49 of 80, and the security textbook on 9 of 14, with no dead links in any. The schema check is `tools/validate-docx.sh` from Pandoc's source, which wrongly rejects `m:sty` in an equation, as `PANDOC-NOTES.md` explains.

### Source

`format: source` gives the book's own files back, remediated, one copy of each in the target's folder under its original name; the originals are never touched. What it writes is only what a person decided in the sidecars, never a guess: a guess written into the author's file would read back as the file's own declaration, and nothing would say it was never reviewed.

For a Word file, it's the remediated copy described under [Utilities](utilities.md#a-remediated-copy-of-a-word-file): each table's header declaration from the table-headers sidecar; a table's description from the table-captions sidecar, as a paragraph in Word's Caption style above a table with no label, kept with it, or joined to the end of a label paragraph beside it; alt text and decorative marks from the image-alt sidecar; a link's title from the bare-links sidecar, and its replacement address, in the link's address and a bare link's text; the book's language as the document's default when the file declares none; and the book's `word.headings` and `word.tracked_deletions`, as the conversion reads it ([Word](#word)). It's all written into the file's XML, with every part nothing decided copied byte for byte. On the statistics book, with its prefilled header rows adopted and a placeholder description for every table: 308 tables got header rows and 229 a header column, all 262 descriptions were joined to their tables' label paragraphs (OpenStax wraps each table in a bookmark, which the matching passes over), and the copies sampled fail Word's schema check with exactly their originals' errors, OpenStax's own. So the first run on a book changes no table: the census's guesses go to `table-headers-new.csv` as usual, the run says how many tables it left to their guess, and adopting their rows into `table-headers.csv` is what gets them written on the next run. `compatibility_mode` keeps the author's compatibility mode unless it's set to `"15"`.

For a hand-maintained HTML page, the same decisions are written into its markup as text edits, the rest of the page exactly as the author wrote it, comments and indentation included: a declared header row's cells become `<th scope="col">` and a header column's `<th scope="row">`, an image gets its `alt` (`alt=""` for `[decorative]`), a bare link its title and its replacement address, which replaces both the address and the text, and `<html>` gets the book's language as `lang` when it has none. A table with no label anywhere gets its description from the table-captions sidecar as its `<caption>`, and one whose label is a paragraph beside it gets the description joined to the end of that paragraph, where it stands, as the rendered page joins it. The sidecar's key names a table as the pipeline sees the page, which can differ from the file (the reader splits a table at a header row in its body, and a table holding only an image isn't counted), so the filter records which table it gave each description to, and which side of it a label paragraph was on, and the copy finds that table by position, row count, and first cell, as it does for headers. A table or label paragraph that isn't what the filter saw is skipped, and the run says how many. A page saved from a platform (Pressbooks, EdTech Books, a WACZ archive) is better fixed in the platform, since that's where it's maintained.

For a Markdown file, the same decisions are written into the text where each element is, and nothing else changes: nothing is parsed and written again, so every construct Pandoc Markdown has survives exactly as the author wrote it. An image gets its alt text between `![` and `]`, and `[decorative]` empties it and adds `.decorative` to the image's own attributes; a bare link, `<url>` or `[url](url)`, becomes `[replacement](replacement "title")`, since `<url>` can't carry a title; a table with no caption gets a `Table:` line after it, inside its div if it's in one, or a label paragraph beside it gets the description joined; and the front matter gets `lang`. Each element is found by rules that follow Pandoc's own, not CommonMark's (an image's path runs to the parenthesis that balances the opening one, spaces and all), and changed only when Pandoc's reading confirms it: an image or link only when the text holds its syntax as many times as Pandoc reads it, which rules out the same syntax inside code, and a table only in a stretch of lines Pandoc's reader reads as exactly that table. Anything unconfirmed is left as it is, and the run says how many.

On the author's own Pandoc Markdown book, 34 chapters, with a bare-links sidecar built by pairing its links with the version the author had already fixed by other means: all 30 bare links in the copy match that version, 19 of them with a shortDOI, every changed line is a link or an image, and every image, bare link, and table in the book (50, 30, and 21, 8 of the tables in the author's own marker divs) can be found.

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

NOT YET IMPLEMENTED: [on the roadmap](../ROADMAP.md). A target naming it is skipped with a warning. PDF waits on LaTeX's tagging support for complex table headers.
