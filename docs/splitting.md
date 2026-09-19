# Splitting pages

A page is the unit the book's structure arranges, and a page starts out as a file. That's right for OpenStax, which exports one file per section, and wrong for a book that arrived as one file per chapter or one file for everything: every output gets one page per file, and a chapter's sections are visible only as headings inside it. `pages.split_level` cuts each source into one page per heading instead.

```yaml
# in conversion.yaml
defaults:
  pages:
    split_level: 2       # one page per heading of level 2 or shallower
```

The cut happens on the filtered intermediate, after the filter has done its work and before anything is rendered, so the pieces carry everything the [remediation](architecture.md#what-conversion-does-to-your-pages) produced while the sidecar keys and the reports still name the source file, which is the file you'd open to fix something. Everything downstream, the HTML render, the packager, and the EPUB assembler, sees ordinary pages.

## What a piece is

Everything from a top-level heading of the chosen level or shallower up to the next one. The heading becomes the piece's title, the way `promote_h1_to_title` makes a source's H1 its page title, and its id is kept as an empty anchor at the top of the piece so links to the section still land. The piece's own headings move up so that each page starts its own structure at H2. Whatever precedes the first cut (a chapter's introduction, say) is a piece of its own, named after the source and titled by it, unless there's nothing there. A source with no heading at that level is left as it was.

Cut headings nest. With level 2, an H1 and the H2s under it are all pages, and the H2 pages belong under the H1. An H1 with nothing of its own before its first H2 isn't a page at all: it survives as a group, because the pages under it record it as their parent. Only top-level headings cut; a heading inside a Div, a list item, or a table cell is part of whatever contains it, and an empty heading (Word leaves these behind) cuts nothing.

Links between pieces are rewritten: a link to `#economies-of-scale` from a piece that no longer holds that section becomes `chapter-7--economies-of-scale.html#economies-of-scale`, and the EPUB assembler turns that into a link within the book. Links within a piece are left alone.

## Where the pieces came from

Each piece records its source, its part number, its position among the cut headings, and the headings above it, in its metadata and in the page's `<head>`:

```html
<meta name="source-page" content="chapter-7" />
<meta name="page-part" content="3/12" />
<meta name="page-position" content="2.1" />
<meta name="page-parent" content="Economies of Scale" />
```

The packager and the EPUB assembler read that, so with no `contents` declared the pieces are grouped under the headings they sat beneath, in reading order, with a heading's own page first in its group. A book that is a single source isn't wrapped in a group for the source, since the book is the source. The guess is written to `packaging-sample.yaml` and is the place to adjust it.

## Naming the pages

A piece starts out named after the source and its heading, the way OpenStax names files after headings: *Economies of Scale* under `chapter-7.docx` is `chapter-7--economies-of-scale.html`. A heading that repeats under a different parent takes the parent's name as well; one that repeats under the same parent gets a number, and the run says so. Those names are stable and usable, and for many books they're enough.

To choose your own, the workflow is:

1. Convert with `split_level` on. The run writes `page-names-new.csv`, one row per piece the sidecar doesn't name, with the derived name filled in:

   ```
   source,parents,heading,position,name
   chapter-7,,What is Java?,,chapter-7--what-is-java
   chapter-7,What is Java?,Java Goals,,chapter-7--java-goals
   chapter-7,Introduction,Learning Objectives,2.1,chapter-7--learning-objectives
   ```

2. Edit the `name` column to the names you want (`1-1-what-is-java`, say) and append the rows to `page-names.csv`. Rows you don't want to rename can be left out; the derived name stands.

3. Convert again. The pieces are written under the new names, the pages the previous run wrote under the old ones are removed (the run keeps their list in `page-names-report.csv`), and `packaging-sample.yaml` shows the new names in the guessed order. Copy its `contents` into `project.yaml` when the order is right, or edit it there.

A row is keyed on the source, the headings above (joined with ` > `), and the heading's text, so it survives the section moving and stops matching when the heading is edited, which is reported. The `position` column is filled in only for pieces the other three columns can't tell apart, two sections both called *Introduction* under the same parent, and it's the one thing that does change when a section moves. Names must be usable as file names: letters, digits, `.`, `_`, and `-`.

`page-names-report.csv` lists every piece the run wrote, with its source, parents, heading, position, and part.

## Footnotes across pages

Pandoc numbers footnotes per document, and every page it renders is a document to it, so a source cut into pages restarts at 1 on each page and keeps each page's notes at its end. Two settings change that in the rendered pages and in the EPUB alike:

```yaml
defaults:
  notes:
    numbering: group     # page (restart on every page) or group
    placement: book      # page, group, or book
```

`numbering: group` continues the numbers across the pages of the enclosing group in reading order, whatever a group is called; a page that wasn't split is a group of one. `placement: group` gathers a group's notes at the end of its last page; `placement: book` gathers every note on a `notes` page at the end, with a heading for each group and the numbers per group. A reference always links to its note wherever it went, and every note ends with a link back to its reference, labelled for a screen reader ("Back to reference 3"). Pandoc can't be asked to start counting at 7, so the numbers are rewritten in the output, ids and all, which is why the EPUB's per-file MathML bookkeeping is redone when a note with an equation moves.

The `notes` page is back matter to the packager's guess and to the EPUB; list it in `contents` where you want it if that isn't the end.

## Headings that aren't headings

The splitter cuts at what Pandoc reads as headings, and Pandoc's DOCX reader reads `Heading 1` through `Heading 9`. A book whose top level is styled `Title` (one text in reach uses `Title` for its modules and `Heading 1` for their sections, and its own TOC field says so: `Title,1,Heading 1,2,...`) loses that level on the way in: the first `Title` paragraph becomes the document's metadata title and the rest become plain paragraphs. The result is a flat list of sections with no modules over them, and every module's *Introduction* colliding with every other's. The fix is in the source: restyle `Title` to `Heading 1` and shift the rest down. [`util/restyle-headings.py`](utilities.md#repairing-heading-styles-in-the-source) does that from a map, or from what the TOC field declares, and drops the empty `Title` paragraphs Word leaves behind. `pandoc -f docx+styles` shows what was being lost, as `Div` blocks with `custom-style="Title"`.

## Splitting your source files

Nothing here changes a source file. But once a format round-trips (Markdown, once it's an input as well as an output), the same step can produce split sources rather than split pages: the pieces are Pandoc documents, and any writer can render them. DOCX may stay the exception, since a Pandoc round trip discards what Pandoc doesn't model.
