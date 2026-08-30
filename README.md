# TextbookImprover

Converts a directory of Word documents into more-accessible HTML pages and packages them as an IMS Common Cartridge for import into Brightspace or another LMS.

Licensed GPL 3.0. See `LICENSE` for more info.

The initial versions of these scripts was created by Robert Szarka and supported by a grant from the West Virginia Higher Education Policy Commission.

## The pieces

| File | What it does |
|---|---|
| `convert.sh` | Runs the whole pipeline: DOCX → Markdown → HTML, then hands off to the cartridge builder. |
| `figures-and-tables.lua` | Pandoc filter doing the accessibility work on each page. |
| `build-cartridge.py` | Builds `imsmanifest.xml` and, optionally, the `.imscc` archive. Usable on its own. |
| `manifest-to-yaml.py` | One-time migration: turns an existing manifest into `imsmanifest.yaml`. |
| `untrack-deletions.py` | One-time source repair: turns Word tracked deletions into ordinary strikethrough. |
| `imsmanifest.yaml` | Your configuration. See `imsmanifest.example.yaml`. |

## Requirements

| Tool | Needed for | Install |
|---|---|---|
| `pandoc` | Everything. Version 3 or later. | `sudo apt install pandoc` |
| `file` | Detecting real image types | usually present |
| `python3` | The manifest and the cartridge | usually present |
| PyYAML | Reading `imsmanifest.yaml` | `sudo apt install python3-yaml` |
| `pypdf` | `--toc` only | `pip3 install pypdf` |
| `zip` | Only if you package with the printed command instead of `--zip` | `sudo apt install zip` |

Pandoc versions differ in ways that show up here: newer releases read Word
caption paragraphs into table captions, older ones do not, so the same
document can produce different reports on different machines. Neither is
wrong; the sidecar files absorb the difference.

## Quick start

```bash
cd /path/to/your/docx/files
cp /path/to/tools/{convert.sh,figures-and-tables.lua,build-cartridge.py} .

./convert.sh                    # convert, report, build the manifest
# edit the imsmanifest-sample.yaml it writes, rename to imsmanifest.yaml
./convert.sh --zip              # convert and build the cartridge
```

`convert.sh` passes any arguments straight through to `build-cartridge.py`,
so `--zip`, `--check`, `--toc` and `--includeallhtml` all work on the front
script.

Work on the Linux filesystem, not under `/mnt/c` or `/mnt/h`. See
[Converting on a cloud-synced drive](#converting-on-a-cloud-synced-drive).

## A first conversion, start to finish

```bash
# 1. Check the source before converting anything.
for f in *.docx; do python3 untrack-deletions.py "$f" --check; done | grep -v ': 0 '

# 2. First run. There is no config yet, so it stops with a sample.
./convert.sh

# 3. Fill in identifier and title, then rename.
mv imsmanifest-sample.yaml imsmanifest.yaml

# 4. Order the pages. With the book's PDF:
./convert.sh --toc book.pdf
#    Without one, let it guess and correct the sample:
./convert.sh --includeallhtml

# 5. Adopt the order it worked out.
mv imsmanifest-sample.yaml imsmanifest.yaml

# 6. Work through the reports, appending rows to the sidecar files.
#    Re-run after each pass; the reports shrink.
./convert.sh

# 7. When the reports you care about are gone, build the cartridge.
./convert.sh --zip
```

Steps 6 and 7 are the loop you will spend the most time in. Everything else
is done once per book.

## What a run creates

```
1-3-levels-of-measurement.md          intermediate Markdown, kept for inspection
1-3-levels-of-measurement.html        the page
1-3-levels-of-measurement/media/      its images, renamed by real content type
imsmanifest.xml                       the manifest
cartridge-files.txt                   every file the archive must contain
imsmanifest-sample.yaml               written when the script worked something out
*-missing.csv                         what still needs a human
course.imscc                          only with --zip
```

The Markdown is intermediate but not disposable — it is what the reports
name, and what the media-resolution step repairs. Deleting it just means
the next run regenerates it.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Everything ran. Reports may still list outstanding work. |
| 1 | The run stopped: no `.docx` present, unresolved media, a missing required config value, or a referenced file not on disk. |

A non-zero exit on a first run is normal — there is no config yet, so the
manifest step writes a sample and stops. The HTML is already written by
that point.

## What conversion does to your pages

Beyond the Word-to-HTML translation, each page gets:

- **Layout tables become figures.** Word positions images with a one-cell
  table and puts the caption in a paragraph underneath. That produces a
  `<table>` with no header and no caption, which fails WCAG 1.3.1. These
  become `<figure>` / `<figcaption>`, and cross-reference anchors move onto
  the figure so existing links still resolve.
- **Data tables get a real `<caption>`**, `scope="col"` on header cells, and
  a focusable scroll wrapper. Pandoc's own stylesheet sets `display: block`
  on tables, which strips the table role from the accessibility tree; the
  wrapper restores it.
- **Captions are found above or below the table.** Either `**Table 2.1:
  Message Transmission Mediums**` on one line, or a bare `**Table 7.1**`
  followed by `*Sample Code of Conduct*`. Prose that merely mentions a
  table is not consumed, nor is a sentence that merely *begins* with the
  label word: "Table 48.1 provides an example of..." continues with a
  lowercase verb, where a caption continues with a capital or a colon.
  Which side a book captions on is measured across the whole document
  first, because two adjacent tables with one label between them are
  genuinely ambiguous and only the document's own habit resolves it.
  Which words introduce a caption is configurable: some books label their
  tables `Figure 1.1`, and an unrecognised label means no caption at all.
- **Media files are renamed to match their real content type.** Word stores
  images with whatever extension the DOCX declares, often `.so` from a
  content type of `application/octet-stream`.
- **Equation images** whose alt text is MathSpeak get their spelled-out
  identifiers rejoined, so a screen reader says "Customer Lifetime Value"
  rather than "upper C u s t o m e r".
- **Caption contrast** is set to `#555`, which measures 7.33:1 against
  Pandoc's `#fdfdfd` background. The widely quoted `#767676` is only
  4.47:1 there, because it is computed against pure white.
- **The leading H1 becomes the page title**, giving a meaningful `<title>`
  instead of a filename slug, and one H1 rather than two.

Conversion stops before writing any HTML if an image reference cannot be
resolved, and writes `media-unresolved.csv` naming each one with what it
was detected as. The commonest cause is EMF/WMF: Word's vector formats,
used for equations, SmartArt and pasted Office charts, which no browser
renders. Replace them in Word (right-click, Save as Picture, PNG) or
convert them with `libreoffice --headless --convert-to png`. A dead image link is invisible in the output — Pandoc emits
`<embed>` rather than `<img>` for an extension it does not recognise — so
failing loudly is better than shipping a cartridge that looks fine.

## Reports

Each run writes only the reports that have something in them, and deletes
the others. A report existing at all means there is work outstanding.

| Report | Fix it by |
|---|---|
| `image-alt-missing.csv` | Filling in the `Alt` column and appending the rows to `image-alt.csv`. |
| `table-captions-missing.csv` | Filling in the `Description` column and appending to `table-captions.csv`. |
| `table-headers-missing.csv` | Marking the header row in Word. No sidecar: header text cannot be invented. |
| `spacer-images.csv` | Nothing — it records what the spacer rule did. |
| `media-unresolved.csv` | Replacing the images named in it. Written only when the run stops. |

### Sidecar files

`image-alt.csv` and `table-captions.csv` hold your corrections. Both are
plain CSV, read afresh each run, and survive re-conversion from updated
Word files.

`image-alt.csv` keys on the image path **ignoring the extension**, because
conversion renames files by content type. Four states for the `Alt` column:

| Value | Meaning |
|---|---|
| text | Use this instead of the Word alt text |
| *(blank)* | Reviewed; keep what Word supplied |
| `[decorative]` | Emit `alt=""` so assistive technology skips it |
| *(no row)* | Unreviewed; reported if absent or over the length limit |

A blank cell deliberately does not mean decorative. "I checked this and it
is fine" and "this image carries no meaning" are different decisions.

`table-captions.csv` keys on the table's label, such as `Table 2.1`. A
table the source never labelled has no such key, so it is reported under a
positional one instead:

```
BC-08#table-1,Comparison of chart types and when to use each
```

That is page stem, then which table it is on the page. The key is stable
as long as no table is inserted or removed above it on that page — the
trade for being able to caption a table the source never named. Labelled
tables are unaffected and keep their label as the key.

One alt per image file. If the same image appears twice on a page with
different alt text, you get a warning and the first entry wins.

## Configuration

Everything variable lives in `imsmanifest.yaml`. `imsmanifest.example.yaml`
documents every key. The two with no default are `manifest.identifier` and
`manifest.title`; without them the build writes a sample and stops.

| `manifest` key | Default | Notes |
|---|---|---|
| `identifier` | none — **required** | Keep it stable across rebuilds. Brightspace matches on it when re-importing; changing it duplicates content rather than updating it. |
| `title` | none — **required** | Shown on import. |
| `description` | derived from the title | Appears in the import dialogue. Worth a real sentence. |
| `keywords` | empty | List of strings. |
| `version` | `1.0` | **Quote it.** Unquoted `1.10` parses as the number 1.1. |
| `language` | `en` | Manifest language. Page `lang` is set separately by `convert.sh`. |
| `cartridge` | `<identifier>.imscc` | Archive filename used by `--zip`. |
| `modified` | today | Set it to keep rebuilds byte-identical. |

### Contents

```yaml
contents:
  - BC-01                          # title comes from the page's <title>
  - page: 1-key-terms
    title: Key Terms               # override when <title> is wrong
  - title: Chapter 1 Sampling and Data
    items:
      - 1-introduction
      - 1-1-definitions-of-statistics-probability-and-key-terms
```

A group is a container only. In Common Cartridge an item pointing at a page
should be a leaf, so a unit with its own introduction lists that page as
its first child rather than pointing at it directly. Three levels of
nesting are supported; deeper is accepted with a warning, since LMS support
for deep hierarchies is uneven.

Omit `contents` and the order is guessed from the filenames — natural sort,
so chapter 10 does not land between chapters 1 and 2, plus chapter grouping
when the filenames encode it. `--includeallhtml` groups the pages it
appends the same way.

Chapters are detected by shape, not vocabulary: a numeric prefix
(`12-3-the-f-distribution`, `12-key-terms`) or a `chapter-12` opener page,
whose own `<title>` becomes the group heading. Within a chapter the order
is opener, introduction, numbered sections, then back matter in the order
set by `grouping.back_matter`. A role name not in that list sorts after the
ones that are, and is reported rather than silently misplaced. The guess is written to
`imsmanifest-sample.yaml` for you to correct. It is a starting point, not a
finished book.

### Header and footer

Injected into every page, as the first and last thing in `<body>`. Either
inline Markdown or the name of a Markdown file:

```yaml
footer: |
  *Your Textbook Here* is licensed
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
```

The fragment is inserted after the Pandoc filter has run, so nothing in it
is processed — no alt checking, no spacer rule. Write its markup correctly
by hand, and list any images it uses under `common_files`.

### Caption labels

```yaml
captions:
  table_prefixes: [Table, Figure, Exhibit]
  figure_prefixes: [Figure]
```

The words that introduce a caption. One book here labels every table
`Figure 1.1`, and with the default of `Table` alone those tables got no
caption. Listing `Figure` under `table_prefixes` is safe: which rule
applies is decided by what the table contains, not by the word.

### Shared files

```yaml
common_files:
  - shared/banner.png
  - shared/course.css
```

Files used by more than one page. They are declared once in a
`common_files` resource that every page depends on, instead of being
repeated in each page's file list.

Files a page references on its own are found automatically and do not
belong here. This list is for files you want shared, and for anything
reached from the header or footer — the page scan sees those on every page
and cannot attribute them to one.

Common Cartridge `<dependency>` support varies between systems. Test a
small cartridge before relying on it; removing `common_files` falls back to
per-page entries.

### Spacer images

Word documents often use a tiny transparent GIF as a bullet. One book here
had 274 of them across 487 images.

```yaml
images:
  spacer_below: 0.3in     # anything narrower is a spacer; 0 disables
  strip_spacer: true      # true removes them, false marks them decorative
  spacer_log: spacer-images.csv
```

With the rule off, suspected spacers are still counted and reported so the
setting is discoverable. Images with no readable width cannot be judged and
are reported separately.

```yaml
images:
  alt_max_chars: 120
```

Alt text longer than this is reported for shortening. It is a length at
which a short equivalent has become a long description, and long
descriptions belong in the prose where every reader gets them. Raising it
silences the report rather than fixing anything.

## Building the cartridge

```bash
python3 build-cartridge.py                 # write imsmanifest.xml
python3 build-cartridge.py --check         # validate, write nothing
python3 build-cartridge.py --zip           # also build the .imscc
python3 build-cartridge.py --init          # write a sample config and stop
python3 build-cartridge.py --toc book.pdf  # order from the PDF's outline
```

### Ordering from the book's own table of contents

`--toc book.pdf` reads the PDF's bookmark outline, which is the table of
contents in the order the book actually uses — better than any filename
heuristic can manage, and it supplies the real chapter titles. Pages are
matched by deriving a filename from each heading ("Key Concepts and
Summary" to `key-concepts-and-summary`), so it works for any book whose
files are named after its headings rather than only for known section
names. Needs `pypdf` (`pip3 install pypdf`).

It supplies the order for pages `contents` does not already place; it does
not replace a curated tree. Anything you listed stays exactly where you put
it, the outline orders the rest into the same destination, and only pages
in neither the config nor the outline reach `Unsorted`. With no `contents`
at all, the outline orders everything. The result goes to
`imsmanifest-sample.yaml` for review, and outline entries matching no page
are reported.

Note that it follows the book faithfully. If the PDF puts per-chapter
answer pages under an "Answer Key" section, that is where they land —
move them if you would rather keep them with their chapters.

| Option | Default | Effect |
|---|---|---|
| `-d`, `--dir` | `.` | Directory holding the pages and media |
| `-c`, `--config` | `<dir>/imsmanifest.yaml` | Configuration file |
| `-o`, `--output` | `<dir>/imsmanifest.xml` | Manifest to write |
| `--toc PDF` | — | Order from a PDF's bookmark outline |
| `--includeallhtml` | off | Place pages the config does not list |
| `--zip` | off | Also build the `.imscc` |
| `--check` | off | Validate; write nothing |
| `--init` | off | Write a sample config and stop |

There is also `--emit-conversion-config DIR`, which `convert.sh` uses to
read header, footer and image settings out of the config without parsing
YAML in shell. It writes only into `DIR` and is not otherwise useful.

`build-cartridge.py` is **read-only with respect to page content**. It
never edits an HTML file or anything under a media directory; it writes
only the manifest, the file list, the sample config, and the archive. That
is what makes it safe to run repeatedly, and what lets it work on any tidy
directory of HTML rather than only on output from `convert.sh`.

Which files each page needs is discovered from the `src` and `href`
attributes the page actually uses, so a stray file left in a media
directory is not shipped, and a referenced file missing from disk is an
error that writes nothing. Links to other pages in the cartridge are
skipped — each page is already its own resource.

Pages in the directory that `contents` does not list are reported and left
out. `--includeallhtml` adds them, placing each one as precisely as the
filename allows:

- A page whose chapter already has a group in `contents` joins that group,
  in back-matter order. This is what makes re-running after converting a
  few more files cheap.
- A page naming a chapter with no group yet gets a new chapter group at the
  top level.
- Only a page with no chapter in its name goes under `Unsorted` — set the
  heading with `grouping.unsorted_title`.

New groups are added inside the group named by `grouping.append_to`. Left
unset, a contents tree that is a single group and nothing else is treated
as the book container and appended into; any other shape appends at the top
level. Naming a group that does not exist is a warning, not an error.

On a 420-page book that leaves 34 chapter groups and 8 entries in
`Unsorted` (appendices, preface, index, references) rather than everything
in one pile. Move those where they belong in the sample config it writes,
and the group disappears on the next run.

Without `--zip` the script prints the equivalent `zip` command. The archive
puts `imsmanifest.xml` at the root with media directories beneath, which is
what the LMS expects.

## Running the Pandoc filter on its own

`figures-and-tables.lua` is an ordinary Pandoc filter and works outside
`convert.sh`. Everything configurable is read from the environment, which
is how `convert.sh` passes settings from `imsmanifest.yaml`:

| Variable | Default | Effect |
|---|---|---|
| `TABLE_CAPTIONS` | `table-captions.csv` | Sidecar of table descriptions to read |
| `IMAGE_ALT` | `image-alt.csv` | Sidecar of replacement alt text to read |
| `TABLE_CAPTIONS_MISSING` | unset | Where to append rows for tables needing a description |
| `IMAGE_ALT_MISSING` | unset | Where to append rows for images needing alt text |
| `TABLE_HEADERS_MISSING` | unset | Where to append rows for tables with no header row |
| `SPACER_LOG` | unset | Where to append rows for spacer images handled |
| `SPACER_BELOW` | `0` (off) | Width under which an image is a spacer |
| `STRIP_SPACER` | `false` | Remove spacers rather than marking them decorative |
| `ALT_MAX_CHARS` | `120` | Alt text longer than this is reported |
| `TABLE_LABEL_PREFIXES` | `Table` | Comma-separated words that introduce a table caption |
| `FIGURE_LABEL_PREFIXES` | `Figure` | The same for figures |

The `*_MISSING` and `SPACER_LOG` files are appended to, not truncated, and
carry no header row — `convert.sh` collects them across a whole run, sorts
and deduplicates, then writes the header. Point them at a temporary file if
you are running the filter yourself.

```bash
TABLE_CAPTIONS_MISSING=/tmp/rows.csv SPACER_BELOW=0.3in \
  pandoc -f markdown-implicit_figures -t html5 page.md \
    --lua-filter=figures-and-tables.lua -o page.html
```

There are also two toggles near the top of the filter that are not exposed
through the config, because no book has yet needed them to differ:
`RESPONSIVE_IMAGES` (strip fixed heights so images reflow) and
`NORMALISE_MATH_ALT` (rejoin MathSpeak identifiers).

## Migrating an existing manifest

```bash
python3 manifest-to-yaml.py imsmanifest.xml -o imsmanifest.yaml
```

Keeps the part that took work — the order, the grouping, the metadata — and
drops the `<file>` entries, which are now rediscovered on every run. Titles
matching what the page already carries are omitted, so the config holds
only real overrides. Run it once per book, check the result, and retire the
old XML.

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

## Files that are not documents

A glob of `*.docx` picks up things that are not documents, and both
`convert.sh` and `untrack-deletions.py` skip them by name with a message
rather than failing:

| What | Why it appears |
|---|---|
| `~$Name.docx` | Word's owner file, written while a document is open. Not a zip. |
| Empty file | On a cloud-synced drive, usually a placeholder not yet downloaded. |
| No `PK` signature | An older `.doc` renamed to `.docx`. Open it in Word and use Save As. |

Skipping is per file, so one bad file no longer takes the whole run down.

## Converting on a cloud-synced drive

Both the rename and the reference rewrite in step 2 are checked after the
fact rather than trusted. `mv` and `sed` report success as soon as the
kernel accepts the write, which on a network or cloud-synced mount is not
the same as the change being visible to the next command. Each is retried
once, and the run reports how often that was needed:

```
Note: 3 media write(s) had to be retried before the change
  was visible. That is a filesystem symptom, not a conversion one.
```

Any count above zero means the working directory is not giving a
consistent view of its own writes. A Google Drive, OneDrive or Dropbox
folder mounted into WSL (`/mnt/h/...`) is the usual cause, and the
symptoms are erratic: a run fails, the next run fails differently, the
third succeeds. **Convert on the Linux filesystem** (`~/work`, not
`/mnt/...`) and copy the finished `.imscc` back.

If a write is lost twice, the run stops naming the exact file and
operation rather than letting it surface later as a missing image.

## Troubleshooting

**`set: Illegal option -o pipefail`** — the script is running under dash.
Use `bash convert.sh` or `./convert.sh`, not `sh convert.sh`. It re-execs
itself under bash, so this should only appear with a very old copy.

**`\r: not found`, then syntax errors** — CRLF line endings from a Windows
editor. `sed -i 's/\r$//' convert.sh`, and set
`git config --global core.autocrlf input`.

**`couldn't unpack docx container`** — a file that is not a DOCX. Word lock
files (`~$Name.docx`), empty cloud placeholders and renamed `.doc` files
are skipped by name, size and signature; anything else reaching Pandoc is
genuinely malformed.

**`Stopping: N media reference(s) could not be resolved`** — see
`media-unresolved.csv`. Usually EMF/WMF.

**A page appears in no report but looks wrong** — check
`imsmanifest-sample.yaml`. If a run worked out an ordering, the sample
holds what it decided.

**Keys like `page#table-3` do not match what you see** — the number counts
data tables only, in reading order; image-only tables become figures and
are not counted. The `Excerpt` column identifies the row.

**Reports keep listing things you fixed** — check the sidecar key. Table
descriptions key on the label (`Table 2.1`) or a positional key; image alt
keys on the media path ignoring its extension.

## Known limits

- **Header row text cannot be invented.** A table with no header row is
  reported, not fixed. Add the header in Word, where it benefits every
  downstream format.
- **Equation images stay images.** Rejoining MathSpeak identifiers is a
  mitigation. The real fix is authoring them as Word equations, which
  convert to MathML.
- **Identical files in different media directories are separate files.**
  Each page gets its own copy from Word. Content-level deduplication would
  require rewriting page markup, which would break the read-only guarantee.
- **Cross-page links are not rewritten** for the LMS's internal link
  format, so links between sections may not resolve after import.
- **Strikethrough conveys meaning visually.** `<del>` is not announced by
  most screen readers by default, so a before-and-after table should say so
  in its column heading or caption.
