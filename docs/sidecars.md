# Sidecars and reports

A run writes reports naming what still needs a person, and reads sidecar files holding what a person decided. Reports are regenerated every run and live beside the book; sidecars are read, never written, and hold the only thing in the pipeline no script can reproduce.

## Bare links

`bare-links.csv` decides each link whose text is its own address: a URL Replacement (a shortDOI, say) replaces the address and the text, other text replaces only the text, and a Title sets the link's title. `bare-links-new.csv` reports the undecided ones, one row per address with the citation before it. [Bare links](bare-links.md) has the detail, the shortDOI helper, and why a description can't do what it seems it should.

## Math kept as it was

`math-keep.csv` lists math the [math repairs](configuration.md#math) would change and shouldn't: a micro sign that really means micro, text that looks like an expression and isn't. Its rows are copied from `math-repaired.csv`, whose first three columns (`Kind`, `Page`, `Before`) name each change; any column after those is ignored, so a whole row can be pasted. An `equation` row keeps that equation unrepaired, and an `expression` or `symbol` row keeps that text as text, the whole of it. A blank `Page` keeps it on every page. A Word source's remediated copy follows the sidecar too: a kept equation is left as it was, found by the TeX Pandoc reads from it, and kept text is never made an equation. A row that keeps nothing in a run, since the book no longer has that math as written there, is warned about and listed.

```csv
Kind,Page,Before
equation,chapter-2,5 µm
symbol,,μ
```

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
| `math-repaired.csv` | Nothing, unless a row shouldn't have changed: it records each equation whose characters were repaired and each piece of text made an equation ([Math](configuration.md#math)). Copy a row into `math-keep.csv` to keep that one as it was; `math.repair_equations` and `math.from_text` turn a whole kind off. |
| `output-check.csv` | Fixing what it names: dead links, images with no alt, headings that skip, tables with no headers. Written when the [output check](checking.md) finds anything. |
| `media-unresolved.csv` | Replacing the images named in it. Written only when the run stops. |
| `table-headers-unmatched.csv` | Looking at each row, whose key matches no table now: the table's text or shape changed, or it's gone. The table's row as it is now is in `table-headers-new.csv`. |
| `table-headers-sample.csv` | Renaming it to `table-headers.csv` once you've looked: the sidecar without the unmatched rows, and with `drafted-by` and `reviewed` added if it had no such columns. Written with `table-headers-unmatched.csv`, or when the sidecar predates the two columns. |
| `fidelity.csv` | Nothing in the book: it says what a target's files can't carry, a row per page and kind, so reading them back won't restore it. See [Word output](formats.md#word-output). |

### Who drafted a value, and whether it's been reviewed

The reports a person fills in, and so the sidecars their rows are pasted into, end with two columns: `Drafted by` and `Reviewed` (`drafted-by` and `reviewed` in `table-headers.csv`, whose columns are lowercase). `Drafted by` is blank when a person wrote the value, `TI` when TextbookImprover guessed it, as it does every table's headers, and a model's name when a model suggested it. `Reviewed` is blank until a person has checked the value; then a name or initials, and a date if you like. A row without the columns, as in every sidecar written before them, counts as a person's. That is true of `image-alt.csv`, `table-captions.csv`, and `bare-links.csv`, whose values only a person ever wrote, so they need nothing. It isn't of `table-headers.csv`, whose rows were mostly pasted from `table-headers-new.csv`, TextbookImprover's guesses unchecked: when it has no `drafted-by` column, the run writes `table-headers-sample.csv`, the sidecar with the two columns added, `TI` on each row that says what the guess says now and blank on each that differs, since a person changed it. The sidecar itself is left alone; rename the sample to `table-headers.csv` once you've looked.

A drafted value is used whether or not it's been reviewed, as the table-header guesses always have been: a plausible description serves a reader better than none. The run says how many drafted values haven't been reviewed, sidecar by sidecar, so they can be found and checked. Filling in `Reviewed` once you've checked a value, whether you kept it or changed it, keeps the record of where it came from as well as who stands behind it.

### Sidecar files

`image-alt.csv`, `table-captions.csv`, `table-headers.csv`, and
`page-names.csv` hold your corrections. All four are plain CSV, read
afresh each run, and survive re-conversion from updated Word files.
`page-names.csv` is read only when `pages.split_level` is on; see
[Splitting pages](splitting.md).

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

`table-headers.csv` says where each data table's headers are, and is the
one sidecar the run helps you write. Its `headers` column takes
`first-row`, `first-column`, `both`, or `none`; `matrix` and `grid` are
accepted for `both` and `none`. The key is a hash of the table's content
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

The guess is `none` only with evidence that a table has no headers: every filled cell is a number or an amount, or the cells are a list laid out in columns, reading in order down each one. Where no rule recognizes a table's headers and nothing shows it has none, the guess is `unknown`, the reason says so, and the table is converted as the source marks it, so the report sends a person to look rather than claiming to know. Across the nine books in the test corpus, 20 of 1,045 data tables are `unknown`: payoff matrices, tables laid on their side, and formula glossaries, among others.

A Word table can declare its own headers too, with the bookmarks [Freedom Scientific documents for JAWS](https://doccenter.freedomscientific.com/doccenter/archives/training/samplefiles/usethebookmarkfeatureinwordfortableheaders-oldertechnique.htm): `Title` for a header row and a header column, `ColumnTitle` for a header row, `RowTitle` for a header column, anything after it keeping the name unique (`ColumnTitle_2`), in one of the table's cells. Such a table is declared, not guessed, and the report names `source` as the supplier. A Word target writes them, so its tables read back as declared. What JAWS does with them is documented, on a page that calls the method an older technique, and not tested here.

An HTML source's tables are in the same sidecar, the same report, and the same new-rows file. The key is computed the same way from the table as Pandoc reads it. A table whose page marks its header cells with `<th>` says so itself, and the report names `source` as the supplier; the sidecar outranks that as it outranks the guess. The rest are guessed from what survives reading, which is the cells' text and their bold. Their merged title rows and grouping bands are inferred as a Word table's are (`caption-rows`, `split-at`), captions for the parts can be written in `part-captions` as for a Word table, and a table the page already groups, a `<tbody>` headed by one cell across the table, counts as banded without being told.

What a banded table becomes is `tables.bands`, per target. `split`, the default for HTML, EPUB, and PDF, makes one table per band with the band in each part's caption; that's what NVDA handles fully, tested in Chrome and Firefox: it reads a part's caption on arrival. NVDA announces only the header of the dimension that changed (the row header moving down, the column header moving across), and of HTML's grouped forms it names a group for a data cell only when the group's heading is a column of its own spanning its rows, and then only moving down; a band as a row of its own, with or without `headers` ids, it names only on the band's own cell. `column`, never the default, keeps one table and gives the bands a column of their own at its left, each spanning its rows: the form NVDA names with the row header on every data cell moving down, for trying in HTML before anything relies on it, since NVDA announced the column header inconsistently in it and no other screen reader has been tried. Only a table whose parts share their column headers takes it; any other is split. `group`, the default for Markdown, AsciiDoc, and DOCX, keeps the author's one table with a body per band, so a Markdown or AsciiDoc target's output reads back as the table it was, and splits again for HTML. A header row above the first band, marked as such or not, heads every part. A status of `needs-source` in
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
| *(no row)* | Unreviewed; reported if absent or over the length limit |

A blank cell deliberately doesn't mean decorative. "I checked this and it
is fine" and "this image carries no meaning" are different decisions.

`table-captions.csv` keys on the table's label, such as `Table 2.1`. A
table the source never labeled has no such key, so it's reported under a
positional one instead:

```
BC-08#table-1,Comparison of chart types and when to use each
```

That is page stem, then which table it's on the page. The key is stable
as long as no table is inserted or removed above it on that page — the
trade for being able to caption a table the source never named. Labeled
tables are unaffected and keep their label as the key.

One alt per image file. If the same image appears twice on a page with
different alt text, you get a warning and the first entry wins.

## After a Markdown round trip

A markdown target writes every decision a sidecar holds into the source: captions as captions, alt text and `{.decorative}` on the images, the header declaration as the marker div. An asciidoc target does the same in AsciiDoc's forms: a named alt, `role=decorative`, and the marker as an open block's role. A book maintained from that Markdown needs no sidecar for those decisions, and a report that lists them again is listing what the source already says; the sidecars stay useful for a book whose source stays Word.
