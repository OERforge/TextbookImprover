# How it works

The pieces, what each one does to a page, and how to run the central filter on its own.

## The pieces

The project is a box of tools that happen to work together. Conversion
turns source documents into accessible pages; packaging assembles pages
into something an LMS can import; the audit says what is wrong with a
file and changes nothing. Each is useful alone: remediating a folder of
documents needs nothing from the cartridge side, building a cartridge
from pages this project never converted needs nothing from the
conversion side, and auditing a PDF needs neither. The rule that keeps
it so: a `bin/` script depends on `lib/` and on external programs, never
on another `bin/` script.

**`bin/` — conversion**

| File | What it does |
|---|---|
| `convert.py` | Runs the pipeline: each source (`.docx` through a repaired copy, `.md` as it is) → JSON → filtered JSON → (split) → every target's output, then hands off to the packaging side. Every setting comes from `conversion.yaml` through the schema. |
| `figures-and-tables.lua` | Pandoc filter doing the accessibility work on each page. |
| `media-extensions.lua` | Pandoc filter naming extracted images by their real content type. |
| `safe-media.lua` | Rewrites a page's local media references at render time to names that need no encoding in a link, matching what `convert.py` copies beside the page. |
| `target-blocks.lua` | At render time, keeps a passage marked for some targets and drops it for the rest, and applies `title_block`. |
| `asciidoc-source.lua` | When an AsciiDoc source is read: `imagesdir` applied, sections moved below the title, Asciidoctor's own settings dropped from the metadata. |
| `markdown-html.lua` | When a Markdown source is read: raw HTML reassembled a tag with its match, read as HTML, and cleaned by `html-raw.lua` and `html-source.lua`, loaded from their files. |
| `html-source.lua` | When an HTML source is read: what the page says about its tables becomes a declaration, and what an earlier run derived (the title block, a table's scroll wrapper) is taken out. |
| `markdown-source.lua` | For a markdown target: takes out what the filter derived and writes what it decided as source markup. |
| `header-includes.lua` | Adds the stylesheet to a page's `header-includes` at render time, alongside what the page already carries there; `--include-in-header` would replace it. |
| `unpack-epub.py` | Turns an EPUB into a directory `convert.py` converts: a page per content document, the media, and a `project.yaml` with the package's metadata and its navigation as `contents`. See [An EPUB as the source](epub-input.md). |
| `unpack-cartridge.py` | Turns a Common Cartridge into a directory `convert.py` converts: its HTML pages and Word documents as sources, its other files, and a `project.yaml` with its modules as `contents`. See [A course cartridge as the source](cartridge-input.md). |
| `adopt-pages.py` | Takes a converted book's pages as the sources of a new one: pieces renamed without `--`, references rewritten, the split's provenance removed, `contents` written. |
| `unpack-jekyll.py` | Turns a Jekyll site's Markdown source into a book directory: flat pages named as `unpack-site.py` names them, contents from the front matter, kramdown's quirks fixed outside code. |
| `unpack-site.py` | Turns pages saved from the web into a directory `convert.py` converts, or with `--whole-pages` into an offline copy of the site. See [A book saved from the web](site-input.md). |
| `lib/sitesource.py` | A saved site as URLs with bytes: the loaders (browser saves, MHTML), the generator profiles, reading the order from menus, and pointing every reference at what is held. |
| `lib/htmlparse.py` | Parsing and serializing HTML with html5lib, or lxml when that's all there is, behind one interface. |
| `lib/unpacking.py` | What both unpackers write: `project.yaml` and `unpack-report.csv`. |
| `lib/epubsource.py` | The package document, the spine, the navigation, and the rewriting of a page's references, for the unpacker. Parses no content document. |
| `lib/htmlrepair.py` | What an HTML source needs done to it before Pandoc reads it, on a copy: an id on a paragraph, a list item, a cell, or an inline mark moves onto an anchor the reader keeps. |
| `lib/docxrepair.py` | What a `.docx` needs done to it before Pandoc reads it, on a copy: bookmarks moved to where the reader keeps them, invisible links so bookmarks only other files point at survive. |
| `lib/notes.py` | Footnote numbering and placement across pages, after rendering, for HTML and EPUB alike. |
| `lib/findings.py` | One format for everything a check finds: the CSV, the Markdown report, the input hashes, the cache. |
| `lib/sourcecheck.py` | What a Word or Markdown source says about itself, from Pandoc's unfiltered reading. |
| `lib/pdfcheck.py` | What a PDF states about itself: metadata, claims, structure, with veraPDF when installed. |
| `lib/names.py` | The one rule for a safe file name, shared with `safe-media.lua`. |
| `split-pages.py` | Cuts filtered intermediates into one page per heading, names the pieces, rewrites links between them and links into them from the book's other pages, and records where each came from. |
| `page.css` | The rules every page carries beyond Pandoc's own stylesheet: caption contrast, real table display, the scroll wrapper. |
| `read-conversion-config.py` | Resolves `conversion.yaml` into settings `convert.py` reads. |
| `check-output.py` | Checks the pages and EPUBs a run wrote for dead links, missing alt text, skipped headings, and the like; the command line over `lib/outputcheck.py`. |
| `build-epub.py` | Assembles the filtered intermediates into one EPUB3, ordered by `project.contents`, with accessibility claims computed from the build. |
| `schema-conversion.yaml` | Declares every conversion setting, its type, default, and meaning. |

**`bin/` — auditing**

| File | What it does |
|---|---|
| `audit.py` | The audit's front door: any mix of Word, Markdown, HTML, EPUB, and PDF files, in; `audit.csv` and `audit.md` out. See [Auditing](auditing.md). |

**`bin/` — packaging**

| File | What it does |
|---|---|
| `build-cartridge.py` | Builds `imsmanifest.xml` and, optionally, the `.imscc` archive. |
| `table-headers.py` | The table-headers pre-pass: runs on the DOCX before Pandoc, reads `table-headers.csv`, guesses where every other table's headers are, and writes the report. |
| `validate-manifest.py` | Checks a manifest against the Common Cartridge 1.1 schemas. Run automatically. |
| `schema-packaging.yaml` | Declares every packaging setting. |

**`schemas/cc11/`** holds the IMS Common Cartridge 1.1 schemas, unmodified
and redistributed under their own terms. See the README there.

**`lib/` — shared**

| File | What it does |
|---|---|
| `oerconfig.py` | Loads, merges, validates, and writes configuration. Both halves use it; neither uses the other. |
| `tablecensus.py` | Reads the tables in a Word document and says what shape they're: the classification, the guess, and the sidecar key. Used by the pre-pass and by `table-census.py`. |
| `outputcheck.py` | The output checks, in nothing but the standard library. |
| `bookcontents.py` | Reads `project.contents` into a tree, and guesses one from the filenames when it's absent. The packager builds the cartridge organization from it; `build-epub.py` builds the table of contents from the same tree. |
| `schema-project.yaml` | Declares the settings that describe the book itself, which both halves read. |

**`util/` — tools you run occasionally**

| File | What it does |
|---|---|
| `migrate-config.py` | One-time: splits a v0.1 `imsmanifest.yaml` into the three v0.2 files. |
| `manifest-to-yaml.py` | One-time: turns an existing `imsmanifest.xml` into `project.yaml` and `packaging.yaml`. |
| `untrack-deletions.py` | One-time source repair: turns Word tracked deletions into ordinary strikethrough. |
| `compare-output.py` | Compares two runs semantically, so a pipeline change can be checked rather than trusted. |
| `table-census.py` | Surveys table structure across a corpus of DOCX files: the command line over `lib/tablecensus.py`. |
| `table-samples.py` | Collects one real example of each table shape into a single Word document, copied from the sources rather than rebuilt. |
| `docx-compat.py` | Reads, and optionally sets, the Word compatibility mode of a DOCX. |
| `restyle-headings.py` | Rewrites a DOCX's heading styles from a map or from its TOC field, for a book whose top level is styled `Title`. |
| `settings-reference.py` | Writes the settings reference pages under `docs/` from the schemas. |

**`tests/`** holds the configuration conformance fixtures and the two test
runners. See [Testing](testing.md).

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
- **A merged title row becomes the caption.** Word has no caption feature
  for tables, so authors put the title in a merged first row, and Pandoc
  makes it a header cell spanning the table. The run recognizes the shape,
  writes `caption-rows=1` into the table's prefilled sidecar row so the
  decision is visible and reversible, and folds the row into the caption:
  after the label if there's one, so "Table 2.14" becomes "Table 2.14
  Number of hours my classmates spent playing video games on weekends".
  Equations in the row stay equations. `caption-rows=N,M` in the sidecar
  does the same for any rows a person names.
- **A table with grouping bands becomes one table per band.** A merged row
  partway down a table—"Example B", "Higher Income Countries", "Year 2"
 —labels the rows beneath it, and no header markup expresses that in
  every format. The run infers `split-at` for those rows, writes it into
  the prefilled sidecar row, and splits there: each part gets the band as
  its caption, composed onto the table's own ("Table 17.4: Year 2"), a
  copy of the header row where the table had one marked, and the header
  declaration applied on its own. Where the bands each sit over their own
  header row, as in the cost tables of Economics 3e, each part keeps its
  own. `part-captions` in the sidecar overrides the composed captions.
- **Tables get the headers they were declared to have.** `table-headers.csv`
  says, per table, whether the headers are in the first row, the first
  column, both, or nowhere (see [Sidecar files](sidecars.md#sidecar-files)), and for a
  table it doesn't cover the run guesses from the file. A header row is
  marked up as `<th scope="col">` whether or not Word marked it to repeat;
  a header column becomes `<th scope="row">` on the first cell of every
  body row, which is what lets a screen reader say which country a figure
  belongs to; a table declared to have no headers gets none, however Word
  formatted it.
- **Captions are found above or below the table.** Either `**Table 2.1:
  Message Transmission Mediums**` on one line, or a bare `**Table 7.1**`
  followed by `*Sample Code of Conduct*`. Prose that merely mentions a
  table isn't consumed, nor is a sentence that merely *begins* with the
  label word: "Table 48.1 provides an example of..." continues with a
  lowercase verb, where a caption continues with a capital or a colon.
  Which side a book captions on is measured across the whole document
  first, because two adjacent tables with one label between them are
  genuinely ambiguous and only the document's own habit resolves it.
  Which words introduce a caption is configurable: some books label their
  tables `Figure 1.1`, and an unrecognized label means no caption at all.
- **Media files are renamed to match their real content type.** Word stores
  images with whatever extension the DOCX declares, often `.so` from a
  content type of `application/octet-stream`.
- **Equation images** whose alt text is MathSpeak get their spelled-out
  identifiers rejoined, so a screen reader says "Customer Lifetime Value"
  rather than "upper C u s t o m e r".
- **Caption contrast** is set to `#555`, which measures 7.33:1 against
  Pandoc's `#fdfdfd` background. The widely quoted `#767676` is only
  4.47:1 there, because it's computed against pure white.
- **The leading H1 becomes the page title**, giving a meaningful `<title>`
  instead of a filename slug, and one H1 rather than two.

Conversion stops before writing any HTML if an image reference can't be
resolved, and writes `media-unresolved.csv` naming each one with what it
was detected as. The commonest cause is EMF/WMF: Word's vector formats,
used for equations, SmartArt and pasted Office charts, which no browser
renders. Replace them in Word (right-click, Save as Picture, PNG) or
convert them with `libreoffice --headless --convert-to png`. A dead image link is invisible in the output — Pandoc emits
`<embed>` rather than `<img>` for an extension it doesn't recognize — so
failing loudly is better than shipping a cartridge that looks fine.

## Running the Pandoc filter on its own

`figures-and-tables.lua` is an ordinary Pandoc filter and works outside
`convert.py`, with two things missing that `convert.py` does before it
runs: the repair of the `.docx` (so bookmarks between blocks and
bookmarks only other files link to are lost that way) and the
table-headers pre-pass. Everything configurable is read from the
environment, which is how `convert.py` passes settings from
`conversion.yaml`:

| Variable | Default | Effect |
|---|---|---|
| `TABLE_CAPTIONS` | `table-captions.csv` | Sidecar of table descriptions to read |
| `IMAGE_ALT` | `image-alt.csv` | Sidecar of replacement alt text to read |
| `TABLE_CAPTIONS_MISSING` | unset | Where to append rows for tables needing a description |
| `IMAGE_ALT_MISSING` | unset | Where to append rows for images needing alt text |
| `TABLE_HEADERS_RESOLVED` | unset | JSON from `table-headers.py --resolved`: the header value to apply per table |
| `SPACER_LOG` | unset | Where to append rows for spacer images handled |
| `SPACER_BELOW` | `0` (off) | Width under which an image is a spacer |
| `STRIP_SPACER` | `false` | Remove spacers rather than marking them decorative |
| `ALT_MAX_CHARS` | `120` | Alt text longer than this is reported |
| `TABLE_LABEL_PREFIXES` | `Table` | Comma-separated words that introduce a table caption |
| `FIGURE_LABEL_PREFIXES` | `Figure` | The same for figures |
| `TABLE_MARKERS` | `matrix=both,row-headers=first-column` | What a fenced div's class declares about a Markdown table's headers |

The `*_MISSING` and `SPACER_LOG` files are appended to, not truncated, and
carry no header row — `convert.py` collects them across a whole run, sorts
and deduplicates, then writes the header. Point them at a temporary file if
you're running the filter yourself.

```bash
TABLE_CAPTIONS_MISSING=/tmp/rows.csv SPACER_BELOW=0.3in \
  pandoc -f json -t html5 page.json \
    --lua-filter=figures-and-tables.lua -o page.html
```

There's also one toggle near the top of the filter that isn't exposed
through the config, because no book has yet needed it to differ:
`NORMALIZE_MATH_ALT`, which rejoins MathSpeak identifiers. Responsive
images used to sit beside it and are now the `images.responsive` setting.
