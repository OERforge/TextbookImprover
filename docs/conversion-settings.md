# Conversion settings

Settings that describe one rendering of the book, under `conversion:` in `packaging.yaml` and per target under `targets:`. Generated from `bin/schema-conversion.yaml` by `util/settings-reference.py`; edit the schema, not this page. A setting marked *target only* can appear only inside a target.

How the book is rendered into one output format.

**`format`**—one of `html`, `epub3`, `pdf`, `docx`, `markdown`; default `html`; *target only*

What this target produces.

**`output_dir`**—`path`; default `""` (empty); *target only*

Where this target writes. Defaults to the target's own name, so two targets in the same format can't overwrite each other.

**`filename`**—`path`; default `""` (empty); *target only*

For a format that produces one file for the whole book, such as epub3, the file to write inside output_dir. Left empty it's worked out afresh on every run from the book's identifier and the format, so renaming the book renames the file. Given without an extension, the one matching the format is added.

**`header`**—`text`; default `""` (empty)

Markdown placed at the top of every page, or the path to a file holding it. Inserted by the template after the filters have run, so nothing in it's processed: give any image explicit alt text.

**`footer`**—`text`; default `""` (empty)

Markdown placed at the bottom of every page, or the path to a file holding it. The usual use is an attribution line. Same caveat as header: it isn't processed by the filters.

**`promote_h1_to_title`**—one of `always`, `if-absent`, `longer`, `never`; default `always`

Whether a page's leading H1 becomes its title. Reading .docx, the existing title comes from a paragraph styled Title, which Pandoc's reader consumes out of the body as metadata. In the OpenStax books that paragraph says the same thing as the H1 without its section number, so the H1 is the more complete of the two and always is right. Reading Markdown or HTML a title is deliberate, so if-absent is. longer promotes only when the H1 contains the existing title; never leaves both alone.

**`author_byline`**—one of `meta`, `visible`, `drop`; default `meta`

What to do with author metadata from the source. Reading .docx this comes from a paragraph styled Author, which Pandoc consumes out of the body the same way it consumes a Title-styled one. meta keeps it in the page head and suppresses the visible byline Pandoc's template would otherwise print under every title; visible keeps both; drop removes it.

## images

How images extracted from the source are handled.

**`images.spacer_below`**—`float`; default `0`

Width in inches below which an image is treated as a layout spacer rather than content. 0 disables the rule and reports candidates instead.

**`images.strip_spacer`**—`bool`; default `false`

Remove spacer images rather than hiding them from assistive technology.

**`images.alt_max_chars`**—`int`; default `120`

Alt text longer than this is reported so it can be shortened, with the detail moved into the surrounding prose where every reader benefits from it.

**`images.responsive`**—`bool`; default `true`

Let images shrink on narrow viewports rather than reproducing the source's fixed dimensions (WCAG 1.4.10).

## tables

How data tables are rendered.

**`tables.wrap`**—`bool`; default `true`

Put wide tables in a focusable scroll container so a long table doesn't force the whole page to scroll sideways (WCAG 1.4.10).

## pages

What a page is, when the source's files are not already the pages you want.

**`pages.split_level`**—`int`; default `0`

Cut every source into one page per heading of this level or shallower, after the filter has run and before anything is rendered. 0 leaves each file as one page. A book that arrived as one file per chapter gets one page per section with 2, and the packager groups the pieces under their source without being told. Each piece is named after its heading unless the page_names sidecar says otherwise, its heading becomes its title, and links between pieces are rewritten to follow.

## epub

Settings read only by an epub3 target. One EPUB holds the whole book: every page in project.contents, in that order, with each group a heading over its pages and the table of contents built from the same tree the cartridge organization uses.

**`epub.toc_depth`**—`int`; default `2`

How many levels the table of contents shows. A group at the top of project.contents is level 1, a page inside it level 2, and a page's own headings continue below its entry, so 2 shows the groups and their pages, whatever a group is called. The depth is a rank in the book, not a fact about the file a heading came from, so a book assembled from files split at different depths still reads evenly.

**`epub.cover_image`**—`path`; default `""` (empty)

An image for the cover page, JPEG or PNG, as an absolute path or one relative to the content directory. Left empty the book has no cover page. A path that doesn't exist stops the build.

**`epub.cover_alt`**—`string`; default `""` (empty)

What a screen reader says for the cover image. Left empty it is "Cover of" followed by the book's title, which is what a cover usually is; give the text when the picture says more.

**`epub.accessibility_summary`**—`text`; default `""` (empty)

The sentence or two a reading system shows a reader about the book's accessibility, alongside the claims the run computes for itself (see the docs). Left empty it's derived from what this run found: how many images lack alternative text, whether equations are MathML, and so on, so it stays true as the sidecars are filled in.

## captions

How table and figure labels are recognised in the source.

**`captions.table_prefixes`**—`list`; default `[Table]`

Words that begin a table label. Books that say Exhibit rather than Table need this.

**`captions.figure_prefixes`**—`list`; default `[Figure]`

Words that begin a figure label.

## media

How media extracted from the source is handled.

**`media.strict`**—`bool`; default `false`

Abort as soon as an image can't be identified, rather than collecting every such image and stopping once at the gate.

## sidecars

CSV files holding decisions a person made about the source. These describe the book rather than one rendering, so a target should rarely override them. These files are read, never written, and hold work no script can reproduce. A bare name resolves against the content directory, which is convenient but leaves them among the generated HTML, the extracted media, and the disposable reports: the directory you would delete to rebuild, and the one replaced wholesale when the publisher reissues the source. An absolute path, or one relative to the content directory such as "../corrections/ibs2e/table-captions.csv", keeps them somewhere you can put under version control. A path set here that doesn't exist stops the run, because the alternative is converting the whole book while silently discarding every correction in it.

**`sidecars.table_captions`**—`path`; default `table-captions.csv`

Descriptive captions, keyed on the table's label. A bare label is a valid caption but describes nothing, and no script can invent the description.

**`sidecars.image_alt`**—`path`; default `image-alt.csv`

Alt text, keyed on the image path with the extension ignored. Use [decorative] for an image that carries no meaning.

**`sidecars.table_headers`**—`path`; default `table-headers.csv`

Where each table's headers are, keyed on a hash of the table's content: first-row, first-column, both, or none. A first run writes prefilled rows to the table_headers_new report; rename or paste them here. Values this version doesn't act on yet (manual, list) are accepted and kept. A row whose key matches no table stops the run, because a correction that silently fails to apply destroys work invisibly.

**`sidecars.page_names`**—`path`; default `page-names.csv`

Names for the pages split_level cuts, keyed on the source and the heading text: source, heading, name. Only needed when the name derived from the heading is not the one you want. A row whose source and heading match nothing is reported, since it means a heading was edited or the row was mistyped.

## reports

Where the run records what still needs human attention. Removing a report when nothing is outstanding is deliberate: the file existing at all is the signal that there's work to do.

**`reports.table_captions_missing`**—`path`; default `table-captions-missing.csv`

Tables whose caption is a bare label with no description.

**`reports.image_alt_missing`**—`path`; default `image-alt-missing.csv`

Images with no alt text, or with alt text over the length limit.

**`reports.table_headers_new`**—`path`; default `table-headers-new.csv`

Prefilled sidecar rows for every data table the table_headers sidecar has no row for, in the sidecar's own format. Written when there are any and removed when there are none, so the file existing is the signal that there are rows to paste in.

**`reports.table_headers_report`**—`path`; default `table-headers-report.csv`

What happened to every data table this run: what the sidecar declared, what the guess said and why, and a status of declared, new, blank, manual, needs-word, or unmatched.

**`reports.page_names_new`**—`path`; default `page-names-new.csv`

Prefilled page_names rows for every page split_level cut that the sidecar has no row for, with the derived name filled in. Written when there are any and removed when there are none.

**`reports.page_names_report`**—`path`; default `page-names-report.csv`

Every page split_level wrote this run: its source, the heading it was cut at, its name, and which part of how many it is.

**`reports.output_check`**—`path`; default `output-check.csv`

What the output check found wrong with the pages and any EPUB this run wrote: links and fragments that resolve to nothing, images with no alt attribute, headings that skip a level, duplicate ids, tables with neither header cells nor a caption, pages with no language or title. Written when there are any findings and removed when there are none. The run isn't stopped by them; they're a list to work through.

**`reports.media_unresolved`**—`path`; default `media-unresolved.csv`

Media that could not be identified. EMF and WMF are the usual cause and have to go back to the author.

**`reports.spacer_images`**—`path`; default `spacer-images.csv`

Spacer images found, and what was done with each.
