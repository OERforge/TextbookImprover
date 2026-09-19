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
data table -- the guess in `headers`, the source file and first cells beside
it so you can find the table -- and you rename that file, or paste its rows
in on later runs when tables have been added. A row whose key matches no
table stops the run, since a correction that silently fails to apply
destroys work invisibly; the report names the row. Values this version does
not act on yet (`manual`, `list`) are accepted and kept, so a book can
start carrying them. The value in effect -- the sidecar's where one was declared, the guess
otherwise -- is applied when the page is built. A status of `needs-word` in
the report means no cell of the table could serve as a header, so no value
can help and headers have to be written in Word; that's the one thing the
old `table-headers-missing.csv` reported, and it's now a row in the report
rather than a file.

`image-alt.csv` keys on the image path **ignoring the extension**, because
conversion renames files by content type. Four states for the `Alt` column:

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
trade for being able to caption a table the source never named. Labelled
tables are unaffected and keep their label as the key.

One alt per image file. If the same image appears twice on a page with
different alt text, you get a warning and the first entry wins.
