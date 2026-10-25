# Sidecars and reports

A run writes reports naming what still needs a person, and reads sidecar files holding what a person decided. Reports are regenerated every run and live beside the book; sidecars are read, never written, and hold the only thing in the pipeline no script can reproduce.

## Bare links

`bare-links.csv` decides each link whose text is its own address: a URL Replacement (a shortDOI, say) replaces the address and the text, other text replaces only the text, and a Title sets the link's title. `bare-links-new.csv` reports the undecided ones, one row per address with the citation before it. [Bare links](bare-links.md) has the detail, the shortDOI helper, and why a description can't do what it seems it should.

## Math kept as it was

`math-keep.csv` lists math the [math repairs](configuration.md#math) would change and shouldn't: a micro sign that really means micro, text that looks like an expression and isn't. Its rows are copied from `math-repaired.csv`, whose first three columns (`Kind`, `Page`, `Before`) name each change; any column after those is ignored, so a whole row can be pasted. An `equation` row keeps that equation unrepaired, and an `expression` or `symbol` row keeps that text as text, the whole of it. A blank `Page` keeps it on every page. A Word source's remediated copy follows the sidecar too: a kept equation is left as it was, found by the TeX Pandoc reads from it, and kept text is never made an equation. So does a deck's copy, and its page, where a row's `Page` is the deck's file name without `.pptx`, and its `Before` the equation's TeX, as a deck's report writes it; a row naming the equation written out in one line, as the report wrote it before, keeps it in the copy alone ([Slides](slides.md#the-reports-and-the-sidecars)). A row that keeps nothing in a run, since the book no longer has that math as written there, or the repairs wouldn't change it, is warned about and listed, unless the setting that makes its kind is off in every target, when it couldn't have kept anything.

```csv
Kind,Page,Before
equation,chapter-2,5 µm
symbol,,μ
```

## A page's language

Every page has a language, worked out once and given to every target. It's the page's row in `languages.csv` if it has one; otherwise the language its own file declares; otherwise the project's (`project.language`). A file's own language that differs from the project's only in region, `en-GB` in a book in `en-US`, or `es` in one in `es-MX`, doesn't override it, since a Word file's language is often just the one the copy of Word that made it was set to, whatever the book is in.

What a file declares depends on its kind:

- **A Word file**: the language most of its letters are in, as Word resolves each one's, from the run's own properties, its character style, its paragraph style, and the document's default. A Chinese, Japanese, or Korean letter takes the East Asian language, and a letter of a right-to-left or complex script the complex-script one. Pandoc reads no language from a Word file at all, so this is read here. A file with no language on any letter is in the language in its core properties, if it has one.
- **A PowerPoint deck**: the language most of its runs say, else its default text style's, else its masters'.
- **A Word file or a deck from OpenStax**: the custom property `language`, when the custom property `company` is `OpenStax`. OpenStax's Word files are Pandoc's output on OpenStax's own template, whose default is US English, and nothing in them says otherwise, so a section of a Spanish book is English throughout to Word (as one section of *Precálculo 2ed* shows; others aren't checked here). OpenStax writes the language in that property, which Word doesn't read. Other producers are added when their files are known to carry their language there too.
- **A Markdown file**: `lang` in its YAML. **An HTML page**: the `lang` of its `<body>`, else of its `<html>`, as Pandoc's reader takes it, so a page the CNX unpacker writes for a module in another language than its book is in the module's. **An AsciiDoc file**: its `lang` attribute. **A LaTeX book's pages**: the language its preamble gives, as babel's main language, polyglossia's, or `\DocumentMetadata`'s.

A page in another language than the book's says so in every target, and the book's packages keep the book's language: the EPUB's and the cartridge's, and the PDF's catalog.

- **An HTML page** has the page's `lang`, and what the book puts on every page, the `header` setting's banner, the `footer` setting's footer, the menu, and the notes' heading, the book's.
- **An EPUB** has the page's language on the root of each of its chapter files, and the `footer` setting's footer the book's. Pandoc's writer gives every chapter file the book's language, so it's set after the EPUB is built.
- **A listing of the book's pages** has the page's title in the page's language: an entry of the contents page (`generate: toc`), of the menu, and of an EPUB's contents and its navigation, and a link to the page in the pager, `lang` on each (and `xml:lang` too in an EPUB). A group's title is in the language of the page its line stands for, its opening page's, or else the one all its pages are in. On the Notes page (`notes.placement: book`), so is the heading over a page's notes.
- **A note moved to another page** (`notes.placement: group` or `book`) keeps its page's language where the page it's moved to is in another.
- **A PDF** has the page in a passage of its language, tagged as any passage in another language is ([Formats](formats.md#pdf)): its text in its language, its headings' words too.
- **A Word, Markdown, or AsciiDoc target's file** has the page's language as its own. A Markdown or AsciiDoc file keeps its source's `lang` where it differs from the page's only in region, since it's what the author wrote, and says none where the page is in the project's language and its source gave none. A file `merge: groups` makes of pages in more than one language is in the book's, each page in another language a passage in its own.
- **A deck's outputs** are in the deck's language: its page, its PDF, its PowerPoint file, and its reveal.js presentation.
- **A `source` target's copy** gets the page's language where it declares none. Where a row of `languages.csv` gives the page another language than its own, the copy gets the row's in its place: a Word file's default and every run, style, and part that said the language the file was in, a deck's default text style, its masters', and every run that said it, an HTML page's `lang`, and a Markdown file's. So does a copy whose file says it's in another language than OpenStax's property, or the project's, gives it: an OpenStax Word file's US English is Spanish in a Spanish book's copy. A passage marked in a third language keeps it. A LaTeX book's copy gets the project's language, when the project declares one: its pages can't each declare their own.

`languages.csv` is keyed on the page's source, as `page-names.csv` is: the page's name, which is its file's name without the extension, made safe for a link, or the file's name itself. A deck's row can name it as its other sidecars do, by its file's name without `.pptx`. Its columns are the report's, of which the run reads the first two: the page and its language, a BCP 47 tag such as `es`, `fr-CA`, or `zh-Hant`.

```csv
source,language,found,drafted-by,reviewed
chapter-3,es,chapter-3.docx: most of its text,TI,RS 2026-10-23
intro,fr-CA,,,
```

The run says which pages are in another language than the book's, and where each one's language came from. `languages-new.csv` drafts a row for each page whose own file put it there and that `languages.csv` has no row for, `found` saying where in the file the language was found, `TI` in `drafted-by`. A drafted language is used as it stands, whether or not it's in `languages.csv`, since it's the file's own; append a row there to keep it, or correct it, and fill in `reviewed` once a person has checked it. A row whose source names no page, or whose language isn't a tag, is warned about and not used. Of two rows for one page, the later is used. A hand-written page in the pass-through directory is copied into an HTML target as it stands, its `lang` too; in an EPUB or a PDF, its language is decided as any page's is.

Where the project declares no language, the book's is `en`, the default. When every page's own file says it's in one other language, the run says so, since `project.language` would make that the book's.

## Reports

Each run writes only the reports that have something in them, and deletes
the others. A report existing at all means there's work outstanding.

| Report | Fix it by |
|---|---|
| `image-alt-missing.csv` | Filling in the `Alt` column and appending the rows to `image-alt.csv`. |
| `table-captions-missing.csv` | Filling in the `Description` column and appending to `table-captions.csv`. |
| `table-headers-new.csv` | Pasting its rows into `table-headers.csv`. It holds a prefilled sidecar row for every data table the sidecar has none for, and exists only while there are any. |
| `table-headers-report.csv` | Nothing directly: it records, for every data table, what the sidecar declared, what the guess said and why, and a status. Written every run. |
| `page-names-new.csv` | Editing the `name` column and appending the rows to `page-names.csv`, if the names derived from headings aren't the ones you want. Written only when `pages.split_level` is on; see [Splitting pages](splitting.md#naming-the-pages). |
| `page-names-report.csv` | Nothing: it records every page the split wrote, its source, and which part of how many it is. |
| `spacer-images.csv` | Nothing — it records what the spacer rule did. |
| `math-repaired.csv` | Nothing, unless a row shouldn't have changed: it records each equation whose characters were repaired, a deck's too, and each piece of text made an equation ([Math](configuration.md#math), [Slides](slides.md#the-reports-and-the-sidecars)). Copy a row into `math-keep.csv` to keep that one as it was; `math.repair_equations` and `math.from_text` turn a whole kind off. |
| `ids-renamed.csv` | Nothing, unless a link meant the element renamed: two elements on a page had each id in it, and it names the page, the element that kept the id, the one renamed, and its new id. A link to the id reaches the one that kept it, so where it meant the other, give one of them another id in the source. An HTML page's heading with no id of its own gives way to anything else's without a row: Pandoc made its id from its words, so nothing can link to it. |
| `output-check.csv` | Fixing what it names: dead links, images with no alt, headings that skip, tables with no headers. Written when the [output check](checking.md) finds anything. |
| `media-unresolved.csv` | Replacing the images named in it. Written only when the run stops. |
| `table-headers-unmatched.csv` | Looking at each row, whose key matches no table now: the table's text or shape changed, or it's gone. The table's row as it is now is in `table-headers-new.csv`. |
| `table-headers-sample.csv` | Renaming it to `table-headers.csv` once you've looked: the sidecar without the unmatched rows, and with `drafted-by` and `reviewed` added if it had no such columns. Written with `table-headers-unmatched.csv`, or when the sidecar predates the two columns. |
| `fidelity.csv` | Nothing in the book: it says what a target's files can't carry, a row per page and kind, so reading them back won't restore it. See [Word output](formats.md#word-output). |
| `slide-titles-new.csv` | Filling in the `Title` column and appending the rows to `slide-titles.csv`: a PowerPoint deck's slides with no title, and those with a title an earlier slide has, whose rows are drafted ([Slides](slides.md#the-reports-and-the-sidecars)). |
| `reading-order-new.csv` | Checking each drafted `Order` and appending the rows to `reading-order.csv`: a PowerPoint deck's slides read in another order than they're laid out ([Slides](slides.md#the-reports-and-the-sidecars)). |
| `slides-check.csv` | Fixing what it names, in the deck or through the sidecars: every finding in a folder of PowerPoint decks, written every slides run ([Slides](slides.md#whats-checked)). |
| `languages-new.csv` | Checking each drafted `language` and appending the rows to `languages.csv`: a page in another language than the book's, as its own file says, that the sidecar has no row for ([A page's language](#a-pages-language)). |

### Who drafted a value, and whether it's been reviewed

The reports a person fills in, and so the sidecars their rows are pasted into, end with two columns: `Drafted by` and `Reviewed` (`drafted-by` and `reviewed` in `table-headers.csv` and `languages.csv`, whose columns are lowercase). `Drafted by` is blank when a person wrote the value, `TI` when TextbookImprover guessed it, as it does every table's headers, and a model's name when a model suggested it. `Reviewed` is blank until a person has checked the value; then a name or initials, and a date if you like. A row without the columns, as in every sidecar written before them, counts as a person's. That is true of `image-alt.csv`, `table-captions.csv`, and `bare-links.csv`, whose values only a person ever wrote, so they need nothing. It isn't of `table-headers.csv`, whose rows were mostly pasted from `table-headers-new.csv`, TextbookImprover's guesses unchecked: when it has no `drafted-by` column, the run writes `table-headers-sample.csv`, the sidecar with the two columns added, `TI` on each row that says what the guess says now and blank on each that differs, since a person changed it. The sidecar itself is left alone; rename the sample to `table-headers.csv` once you've looked.

A drafted value is used whether or not it's been reviewed, as the table-header guesses always have been: a plausible description serves a reader better than none. The run says how many drafted values haven't been reviewed, sidecar by sidecar, so they can be found and checked. Filling in `Reviewed` once you've checked a value, whether you kept it or changed it, keeps the record of where it came from as well as who stands behind it.

### Sidecar files

`image-alt.csv`, `table-captions.csv`, `table-headers.csv`, `page-names.csv`, and `languages.csv` hold your corrections. All five are plain CSV, read afresh each run, and survive re-conversion from updated Word files. `page-names.csv` is read only when `pages.split_level` is on; see [Splitting pages](splitting.md).

**In a spreadsheet.** Every report starts with a UTF-8 byte-order mark, and so does every file of rows written to become a sidecar (`table-headers-sample.csv`, the CNX unpacker's `table-captions.csv`). Excel opens a UTF-8 CSV with the mark normally, as Microsoft documents ([Opening CSV UTF-8 files correctly in Excel](https://support.microsoft.com/en-us/excel/opening-csv-utf-8-files-correctly-in-excel)); one without it, it reads in the computer's code page, Windows-1252 in the US, where an en dash shows as "â€“" and a minus sign as "âˆ’", as a sidecar written without the mark showed. To keep a sidecar's characters when you save it from Excel, choose "CSV UTF-8 (Comma delimited)", which by many accounts writes the mark, not plain "CSV", which saves in the code page; neither is tried here. A sidecar that isn't UTF-8 stops the run before anything is converted, whether or not the run reads it, naming its file and the line, and so do the tools that read one on their own (`table-headers.py`, `split-pages.py`, `util/remediate.py`, `util/round-trip-decks.py`, and `util/shortdoi.py`). A sidecar is read with the mark or without it, at the file's start and at the start of any line, where appending a report to a sidecar, its header row and all, leaves one.

**Where to keep them.** By default they sit in the book's own directory,
next to the reports that name what still needs filling in. That is the
convenient default and it keeps two books' decisions apart, but it isn't
where they belong long-term. The book's directory also holds the
generated HTML, the extracted media, and the intermediates: it's the
directory you delete to rebuild from scratch, and the one you replace
wholesale when the publisher reissues the source. These files are the
only things in it that no script can reproduce.

So once you have spent real time on them, move them somewhere you can put
under version control and point the configuration at them:

```yaml
defaults:
  sidecars:
    table_captions: ../corrections/ibs2e/table-captions.csv
    image_alt: ../corrections/ibs2e/image-alt.csv
    table_headers: ../corrections/ibs2e/table-headers.csv
```

An absolute path works too. A relative one resolves against the book's
directory, not against the tools. A path that doesn't exist stops the
run rather than converting the book and discarding every correction in
the file, which is what happened before v0.2 when an absolute path was
given.

`table-headers.csv` says where each data table's headers are, or that a
table is a layout table, and is the one sidecar the run helps you write.
Its `headers` column takes `first-row`, `first-column`, `both`, `none`, or
`layout`; `matrix` and `grid` are accepted for `both` and `none`. The key is a hash of the table's content
and shape, so a row survives anything the pipeline does to the table and
detaches only when the source table itself changes. You never type a key:
the first run writes `table-headers-new.csv` with a prefilled row for every
data table—the guess in `headers`, the source file and first cells beside
it so you can find the table—and you rename that file, or paste its rows
in on later runs when tables have been added. A row whose key matches no
table, because the table's text or shape changed or it's gone, isn't
silently dropped: the run warns and goes on, the row goes to
`table-headers-unmatched.csv`, the table's row as it is now to
`table-headers-new.csv`, and `table-headers-sample.csv` is the sidecar
without the unmatched rows, to adopt once you've looked. This happens
whenever a table is edited in its source, as when a Word file converted
once is edited in Word and converted again. Values this version does
not act on yet (`manual`, `list`) are accepted and kept, so a book can
start carrying them. The value in effect—the sidecar's where one was declared, the guess
otherwise—is applied when the page is built.

The guess is `none` only with evidence that a table has no headers: every filled cell is a number or an amount, the cells are a list laid out in columns, reading in order down each one, or a note on the rows above it runs across the table before its last row (below), which no column could head, and nothing marks a header row. Where no rule recognizes a table's headers and nothing shows it has none, the guess is `unknown`, the reason says so, and the table is converted as the source marks it, so the report sends a person to look rather than claiming to know. Across the nine books in the test corpus, 20 of 1,045 data tables are `unknown`: payoff matrices, tables laid on their side, and formula glossaries, among others.

`layout` says a table only lines things up: a worked example's steps beside their results, say, or a picture beside its words. It has no headers to declare and no caption to write, and every target writes it as one. It has no header cells either: a head it comes with, a row Word repeats as a header, say, which Pandoc's reader puts in the table's head, is written as rows like the others. The pages and the EPUB give it `role="presentation"`, with no scroll region around it, which only a data table needs, and on a narrow screen its cells stack, each row's one under another; the PDF tags it as a division of paragraphs, a row's cells in turn, not a table (LaTeX's `table/tagging=div`), its caption, if it has one, a paragraph before it; and a Markdown target writes it as HTML with its role, so it reads back as one. Nothing asks a description of it, and the output check doesn't count it as a table without headers. It keeps its place among its page's tables, so the keys `table-captions.csv` gives the tables after it don't move; a description that file has for it isn't used, and the run says so. A page can say so itself, with `role="presentation"` or `role="none"` on the table (ARIA's two names for the same thing), and so can a LaTeX book, with `\tagpdfsetup{table/tagging=div}` before it: such a table is in `table-headers-new.csv` as `layout`, the report naming `source` as the supplier, and a row naming its headers, `none` among them, makes it a data table. One the header guess counts no table at all isn't listed, as an unmarked one isn't: a single cell, or pictures alone, which become a figure. A table of one cell is a layout table whatever its source, since one cell has nothing to head (a Word file's box around a note, a byline), unless its source makes the cell a header cell (a page's `<th>`, a LaTeX longtable's head, a Markdown table's header row, a Word table's row marked to repeat as a header, but not the header row Word's table look makes of a box's, as Word makes one of every table it inserts), or a caption, its own or a label beside it ("Table 25.5"), presents it as a table, which a PDF numbers. Word records nothing for its "Mark as layout table" ([Troubleshooting](troubleshooting.md)), so a Word table of more cells than one is a layout table only by a row here. A `source` target writes a row's `layout` into an HTML page, as its role, and into a LaTeX book, as its tagging, but can't into a Word file, and says so. A deck's tables don't take it.

A Word table can declare its own headers too, with the bookmarks [Freedom Scientific documents for JAWS](https://doccenter.freedomscientific.com/doccenter/archives/training/samplefiles/usethebookmarkfeatureinwordfortableheaders-oldertechnique.htm): `Title` for a header row and a header column, `ColumnTitle` for a header row, `RowTitle` for a header column, anything after it keeping the name unique (`ColumnTitle_2`), in one of the table's cells. Such a table is declared, not guessed, and the report names `source` as the supplier. A Word target writes them, so its tables read back as declared. What JAWS does with them is documented, on a page that calls the method an older technique, and not tested here.

An HTML source's tables are in the same sidecar, the same report, and the same new-rows file. The key is computed the same way from the table as Pandoc reads it. A table whose page marks its header cells with `<th>` says so itself, and the report names `source` as the supplier; the sidecar outranks that as it outranks the guess. A row of the table's head that is one cell across it is its title or a band, not a header row. The rest are guessed from what survives reading, which is the cells' text and their bold. Their merged title rows and grouping bands are inferred as a Word table's are (`caption-rows`, `split-at`), captions for the parts can be written in `part-captions` as for a Word table, and a table the page already groups counts as banded without being told: a `<tbody>` headed by one cell across the table, or, in a table with no `<thead>`, `<tbody>`s that each open with a row of `<th>` like the others but for the group's name in its first cell, a group's own header row, which heads its part.

What a banded table becomes is `tables.bands`, per target. `split`, the default for HTML, EPUB, and PDF, makes one table per band with the band in each part's caption; that's what NVDA handles fully, tested in Chrome and Firefox: it reads a part's caption on arrival. NVDA announces only the header of the dimension that changed (the row header moving down, the column header moving across), and of HTML's grouped forms it names a group for a data cell only when the group's heading is a column of its own spanning its rows, and then only moving down; a band as a row of its own, with or without `headers` ids, it names only on the band's own cell. `column`, never the default, keeps one table and gives the bands a column of their own at its left, each spanning its rows: the form NVDA names with the row header on every data cell moving down, for trying in HTML before anything relies on it, since NVDA announced the column header inconsistently in it and no other screen reader has been tried. Only a table whose parts share their column headers takes it; any other is split. `group`, the default for Markdown, AsciiDoc, and DOCX, keeps the author's one table with a body per band, so a Markdown or AsciiDoc target's output reads back as the table it was, and splits again for HTML. A table whose groups each open with a header row of their own reads back as it was too, written as HTML in either, and splits again for HTML into the same parts. A header row above the first band, marked as such or not, heads every part, and a row of several cells named in `split-at`, a group's own header row with the group's name in its corner, heads its part, the corner's words in the part's caption. What a split repeats keeps its ids in one place, which a link to them names: the table's own id on the first part, the others numbered from 2 (`costs-2`); a header row's, and those of its cells, on the first part's copy, the table's caption's on the first part's caption, and a corner's on its row. A part laid out on fewer columns than the table, each of its cells across two (*Foundations of Information Systems*' normal forms), loses the columns no cell of it begins in, which HTML doesn't allow, each cell spanning one fewer. A band heads the rows under it, so a merged row with nothing but bands under it to the table's end, a note across a table's foot, stays a row of the table, and a merged first row right over another band is the table's title, which the guess makes a caption row, unless a band stands right over another further down, which makes the pair at the top a group of groups too. Nor is a note on the rows above it a band: a merged row that ends as a sentence does, right after a row of the table's cells, in a table that ends with such a row, as *Prealgebra 2e*'s Table 3.1 closes each pair of its cases, stays a row of the table, and since no cell of a note's row could head it, the guess gives a table with one before its last row no header column: a guess of `both` is `first-row`; one of `first-column` is `first-row` where the source marks a header row, as a `<thead>`, a Word table's first row its table look formats, or a row marked to repeat does, and `none` where nothing does; and one of `unknown` is `none` where nothing marks a header row and none is below a data row. A table that opens with such a sentence is one of bands, as a self-test closed by its total's line is, and a line at a table's foot that says where it comes from ("Adapted from …") is no note, nor a row a note comes before. A band right over another names a group of groups: both go into the caption of the part below ("Table 3.2: Part Two: Group B"), or into its body's head in `group`. A row named in `split-at` that heads no rows of its own is named in the run's output, and the table isn't split there, and so is a `part-captions` that gives more or fewer captions than the table has parts. A table's foot, an HTML table's `<tfoot>`, comes after its last part, or stays at the foot of the table kept whole, and the guess makes none of its rows a band. A band at the end of the table's head, where Pandoc's Word reader puts a first row Word's table look formats (Word's default), heads the first part alone. A merged first row over a header row every part shares, in the table's head or with nothing marking the header row and the first band right under it, is the table's title, which the guess makes a caption row; where a band below has a header row of its own, the header row again or one reading as a header row over its rows, or rows with their cells elsewhere, it's the first band, and from the head it takes the header row under it to the first part. Any other band above a header row in the head stays in every part's head with it. A status of `needs-source` in
the report means no cell of the table could serve as a header, so no value
can help and headers have to be written in the source, in Word or as an HTML
page's `<th>` cells; that's the one thing the
old `table-headers-missing.csv` reported, and it's now a row in the report
rather than a file.

`image-alt.csv` keys on the image path. A row whose path doesn't match exactly still applies when it differs only by extension, because conversion renames Word's extracted media by content type, but only when no other file in that directory shares the name: `images/logo.png` and `images/logo.svg` are two images, and a row for one doesn't describe the other. Four states for the `Alt` column:

| Value | Meaning |
|---|---|
| text | Use this instead of the Word alt text |
| *(blank)* | Reviewed; keep what Word supplied |
| `[decorative]` | Emit `alt=""` so assistive technology skips it |
| *(no row)* | Unreviewed; reported if absent, over the length limit, or saying nothing about the image |

A blank cell deliberately doesn't mean decorative. "I checked this and it
is fine" and "this image carries no meaning" are different decisions.

Alt text that says nothing about its image is reported as a missing one is, by the rules a deck's pictures are judged by ([Slides](slides.md#whats-checked), `lib/alttext.py`), with the reason in the `Reason` column: a file name or extension (`chart.png`), punctuation alone, a word such as "image" or "picture", a camera's or tool's name for a file (`IMG_2041`), a shape's default name (`Picture 3`), a clip-art id, a description Office generated ("Description automatically generated", which Office asks a person to review), a web page's title copied with the picture (`Marketing Mix Explained | Quizlet`), a credit in place of a description (`By Jane Roe - Own work, CC BY-SA 4.0`), or a pattern the project lists in `images.alt_placeholders`. So is alt text no other rule names that a different image of the book has too (`shared with 1 other image`), case and closing punctuation aside, or, in a folder of decks written in Markdown, of the deck: images are told apart by their files' content, so the same picture in two pages' files isn't named, and the alt text a row of `image-alt.csv` gives is what's compared, so describing one of two images anew settles the other. A row with a blank `Alt` says the alt text was reviewed and stands, and the image isn't reported again.

`table-captions.csv` keys on the table's label, such as `Table 2.1`,
whether the label is a paragraph beside the table or the table's own
caption: an HTML page's `<caption>Table 2.1</caption>`, a Markdown
table's `Table: Table 2.1`, or a Word paragraph in a caption style beside
the table, which Pandoc reads as its caption. A label that says nothing
more is reported for a description either way. A table the source never
labeled has no such key, so it's reported under a positional one
instead:

```
BC-08#table-1,Comparison of chart types and when to use each
```

That is page stem, then which table it's on the page. The key is stable
as long as no table is inserted or removed above it on that page — the
trade for being able to caption a table the source never named. Labeled
tables are unaffected and keep their label as the key.

One alt per image file. If the same image appears twice on a page with
different alt text, you get a warning and the first entry wins.

A PowerPoint deck's rows are in the same `image-alt.csv`, with the same
four states, keyed differently: a picture on its image's content
(`media/` and the first 16 characters of its SHA-256), so one row covers
every copy of it in every deck, and any other object on its deck, slide,
and shape (`deck/slide-N/shape-M`), as is a copy of a picture cropped to
show another part of its image than the image's other copies show. Its
tables are in `table-headers.csv` as a book's are, its untitled slides,
and slides titled as an earlier one is, get titles from
`slide-titles.csv`, its slides a reading order from `reading-order.csv`,
and its bare links and the equations it keeps as they were are in
`bare-links.csv` and `math-keep.csv`, as a book's are
([Slides](slides.md#the-reports-and-the-sidecars)).

## After a Markdown round trip

A markdown target writes every decision a sidecar holds into the source: captions as captions, alt text and `{.decorative}` on the images, the header declaration as the marker div. An asciidoc target does the same in AsciiDoc's forms: a named alt, `role=decorative`, and the marker as an open block's role. A book maintained from that Markdown needs no sidecar for those decisions, and a report that lists them again is listing what the source already says; the sidecars stay useful for a book whose source stays Word.
