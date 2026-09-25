# Utilities

Tools in `util/` that aren't part of a conversion but help before or around one: surveying a corpus, checking a source, comparing two runs.

| Tool | Purpose |
| --- | --- |
| `migrate-config.py` | One-time: splits a v0.1 `imsmanifest.yaml` into the three v0.2 files. |
| `manifest-to-yaml.py` | One-time: turns an existing `imsmanifest.xml` into `project.yaml` and `packaging.yaml`. |
| `untrack-deletions.py` | One-time source repair: turns Word tracked deletions into ordinary strikethrough. |
| `compare-output.py` | Compares two runs semantically, so a pipeline change can be checked rather than trusted. |
| `table-census.py` | Surveys table structure across a corpus of DOCX files: the command line over `lib/tablecensus.py`. |
| `table-samples.py` | Collects one real example of each table shape into a single Word document, copied from the sources rather than rebuilt. |
| `docx-compat.py` | Reads, and optionally sets, the Word compatibility mode of a DOCX. |
| `restyle-headings.py` | Reports the paragraph styles a DOCX uses, and rewrites its heading styles from a map: the repair a book whose top level is styled `Title` needs before its structure can be seen. |
| `settings-reference.py` | Writes the three settings reference pages under `docs/` from the schemas; `--check` says whether they're current. |
| `remediate-docx.py` | Writes remediated copies of an author's Word files: the pipeline's decisions about tables, images, and links written into the files themselves. A first version, run by hand. |

Each takes `--help`. The census and sample tools read Word files directly and need no Pandoc; `compare-output.py` reads HTML; `docx-compat.py` touches nothing but `word/settings.xml`; `restyle-headings.py` nothing but the paragraph styles.

`table-census.py`, `table-samples.py`, and `docx-compat.py` are the ones to reach for before converting a book you haven't seen: the census says what shapes its tables take and what the run will guess about each (given a directory, it reads every `.docx` in it and gives each book's totals, a subdirectory being a book, so `table-census.py corpus/` surveys a whole corpus, and the sample generator takes directories the same way), and `slim-corpus.py` makes a copy of a corpus small enough to send somewhere to be measured (each `.docx` reduced to the one part the census reads, a book's folder or zip download kept as its own folder, so the census reports the copy with the same totals; nine books came to 10.5 MB, and a slim copy is no good for converting or for the sample generator, which need the originals), the sample document shows one real example of every shape so you can see what would be lost, and the compatibility check says whether Word will open the sources in Compatibility Mode.

## Repairing heading styles in the source

Pandoc's DOCX reader reads `Heading 1` through `Heading 9` as headings and nothing else. A book whose top level is styled `Title` loses it on the way in: the first `Title` paragraph becomes the document's metadata title and every later one becomes a plain paragraph, so the page split, the contents guess, and the EPUB's table of contents all see sections with no chapters over them. The all-in-one programming text in the corpus is exactly that, and its own table-of-contents field says so: `TOC \h \z \t "Heading 1,2,Heading 2,3,...,Title,1"`.

```bash
python3 util/restyle-headings.py book.docx              # report the styles in use
python3 util/restyle-headings.py book.docx --from-toc   # what the TOC field declares, and what would change
python3 util/restyle-headings.py book.docx --from-toc -o book-restyled.docx
```

Three ways to say what to do, and they don't chain: the map is applied to every paragraph at once, so `Heading1=Heading2,Heading2=Heading3` does what it says.

- `--from-toc` reads the levels from the document's own TOC field and builds the map from them.
- `--promote STYLE` makes `STYLE` the level-1 heading and moves every heading in use down one.
- `--demote` moves every heading in use down one, for a book with several `Heading 1` sections and nothing over them; `--title "Text"` then inserts a `Heading 1` holding that text at the top of the body and records it as the document's `dc:title` property. One paragraph serves as both title and heading here: `promote_h1_to_title` makes a lone H1 the page's metadata title, and after a split it titles the preamble page and the group.
- `--map FROM=TO,...` is explicit, in style ids (`Title`, `Heading1`).

Empty paragraphs of a remapped style are dropped, since an empty `Title` paragraph would become an empty heading and Word leaves plenty of those (46 in that book); `--keep-empty` keeps them. Every target style has to exist in `word/styles.xml`, which Word writes only once a style has been used, so a shift that needs a `Heading 5` the document has never used is refused with a note saying what to do in Word. Everything else is copied byte for byte.

Restyling removes the `Title` paragraphs, so the converted pages take their titles from their headings and the EPUB takes the book's from `project.title`, which is where it should come from anyway. After restyling, `pages.split_level: 2` gives one page per section with the modules as groups; see [Splitting pages](splitting.md).

## A remediated copy of a Word file

`remediate-docx.py` writes the decisions the pipeline makes about a Word source back into a copy of the file, so the author can go on working in Word from an accessible document. It edits the file's XML as text, changing only what it names; every part it doesn't change is copied byte for byte.

```sh
table-headers.py *.docx --sidecar table-headers.csv --new new.csv \
    --report report.csv --resolved resolved.json
remediate-docx.py *.docx --resolved resolved.json \
    --alt image-alt.csv --links bare-links.csv --out remediated
```

- **Tables** get the header declaration in effect, the sidecar's where it has a row and the guess otherwise. A header row becomes Word's repeating header row, with any title rows above it, since Word's header rows start at the top of a table. A header column becomes the table style's First Column flag. Either gets a bookmark naming the table's headers, `Title`, `ColumnTitle`, or `RowTitle`, the convention [Freedom Scientific documents for JAWS](https://doccenter.freedomscientific.com/doccenter/archives/training/samplefiles/usethebookmarkfeatureinwordfortableheaders-oldertechnique.htm). Each table is found by its position among the file's tables and changed only when its row count and first cell are what the pre-pass saw; any other is skipped and counted.
- **Images** get their alt text from the image-alt sidecar, as the picture's description, and `[decorative]` gets Word's "Mark as decorative", with no description or title.
- **Links** get their title from the bare-links sidecar, as a ScreenTip.
- **Compatibility mode 15** is set only with `--compat`.

Measured on the statistics book's 169 Word files: 308 of its 332 data tables got header rows and 229 a header column, none was skipped, and the header pre-pass, run again on the copies, reads every one of the 332 as declared with the same value, from the file's own bookmarks. Only `word/document.xml` changed, and only in the 57 files that have tables; the others are the originals byte for byte. OpenStax's files fail Word's schema check on their own, mostly for a paragraph style out of place, and the copies fail it with exactly the same errors. What Word and screen readers do with the changes is documented, not tested here.

Not yet: bands and table splits have no Word equivalent and are left alone; a table's caption, a link's replacement address (a shortDOI), and anything the pipeline decides in the filter rather than a sidecar aren't written. `convert.py` doesn't call it yet.

## Repairing tracked deletions in the source

Some authors use Word's tracked-deletion mark as *content* — a
before-and-after table showing which words to cut from a sentence. That is
revision history carrying meaning, and anything that resolves revisions
destroys it: Word's own "Accept All Changes", most converters, and Pandoc,
which accepts changes by default. A before-and-after example then shows two
identical sentences.

```bash
# Scan a directory. --check writes nothing, so -o is not needed.
for f in *.docx; do python3 untrack-deletions.py "$f" --check; done

# Repair one file.
python3 untrack-deletions.py BC-14.docx -o BC-14-fixed.docx
```

Each `<w:del>` becomes ordinary runs with `<w:strike/>`, so the appearance
is unchanged in Word but the meaning no longer depends on a revision being
left unresolved. Only `word/document.xml` is touched; every other part of
the package is copied through byte for byte. Strikethrough reaches the HTML
as `<del>`.

`--track-changes=all` on the Pandoc call is the non-destructive
alternative, but it only fixes this pipeline, leaves the document fragile
for every other consumer, and emits `<span class="deletion">` needing CSS.

## Files that aren't documents

A glob of `*.docx` picks up things that aren't documents, and both
`convert.py` and `untrack-deletions.py` skip them by name with a message
rather than failing:

| What | Why it appears |
|---|---|
| `~$Name.docx` | Word's owner file, written while a document is open. Not a zip. |
| Empty file | On a cloud-synced drive, usually a placeholder not yet downloaded. |
| No `PK` signature | An older `.doc` renamed to `.docx`. Open it in Word and use Save As. |

Skipping is per file, so one bad file no longer takes the whole run down.
