# Sidecars and reports

A run writes reports naming what still needs a person, and reads sidecar files holding what a person decided. Reports are regenerated every run and live beside the book; sidecars are read, never written, and hold the only thing in the pipeline no script can reproduce.

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
| `output-check.csv` | Fixing what it names: dead links, images with no alt, headings that skip, tables with no headers. Written when the [output check](checking.md) finds anything. |
| `media-unresolved.csv` | Replacing the images named in it. Written only when the run stops. |

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
table stops the run, since a correction that silently fails to apply
destroys work invisibly; the report names the row. Values this version does
not act on yet (`manual`, `list`) are accepted and kept, so a book can
start carrying them. The value in effect—the sidecar's where one was declared, the guess
otherwise—is applied when the page is built.

An HTML source's tables are in the same sidecar, the same report, and the same new-rows file. The key is computed the same way from the table as Pandoc reads it. A table whose page marks its header cells with `<th>` says so itself, and the report names `source` as the supplier; the sidecar outranks that as it outranks the guess. The rest are guessed from what survives reading, which is the cells' text and their bold. Their merged title rows and grouping bands are inferred as a Word table's are (`caption-rows`, `split-at`), and a table the page already groups, a `<tbody>` headed by one cell across the table, counts as banded without being told.

What a banded table becomes is `tables.bands`, per target. `split`, the default for HTML, EPUB, and PDF, makes one table per band with the band in each part's caption; that's what a screen reader announces, since NVDA, tested in Chrome and Firefox, names none of the ways HTML marks a row group. `group`, the default for Markdown and DOCX, keeps the author's one table with a body per band, so a Markdown target's output reads back as the table it was, and splits again for HTML. A header row above the first band, marked as such or not, heads every part. A status of `needs-source` in
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

A markdown target writes every decision a sidecar holds into the source: captions as captions, alt text and `{.decorative}` on the images, the header declaration as the marker div. A book maintained from that Markdown needs no sidecar for those decisions, and a report that lists them again is listing what the source already says; the sidecars stay useful for a book whose source stays Word.
