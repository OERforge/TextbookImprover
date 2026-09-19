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

Only top-level headings cut. A heading inside a Div, a list item, or a table cell is part of whatever contains it.

Links between pieces are rewritten: a link to `#economies-of-scale` from a piece that no longer holds that section becomes `chapter-7--economies-of-scale.html#economies-of-scale`, and the EPUB assembler turns that into a link within the book. Links within a piece are left alone.

## Names

A piece is named after the source and its heading, the way OpenStax names files after headings: *Economies of Scale* under `chapter-7.docx` becomes `chapter-7--economies-of-scale.html`. That name survives moving the section and changes when the heading does. The source's name stays in front because it's what lets a later run find the pieces of a source it's cutting again and replace them, whatever the level was last time.

To change the part after the separator, write `page-names.csv`:

```
source,heading,name
chapter-7,Choice of Production Technology,technology
```

It's keyed on the source and the heading text as written. A first run writes `page-names-new.csv` with a prefilled row for every piece the sidecar doesn't name; edit the `name` column and append the rows. A row whose heading the source doesn't have is reported, since it means the heading was edited or the row mistyped. Two sections with the same heading both match a row for it, and the later one gets a number.

`page-names-report.csv` lists every piece the run wrote, with its source, its heading, and which part of how many it is. Two dashes in a row (`--`) are reserved for the separator: a source whose own name contains them is refused.

## Where the pieces came from

Each piece records its source and its part number in its metadata and in the page's `<head>`:

```html
<meta name="source-page" content="chapter-7" />
<meta name="page-part" content="3/4" />
```

The packager and the EPUB assembler read that, so with no `contents` declared the pieces of a source are grouped under the source's title, in reading order, and the source's own page comes first when it has one. The guess written to `packaging-sample.yaml` shows the result and is the place to adjust it.

## Splitting your source files

Nothing here changes a source file. But once a format round-trips (Markdown, once it's an input as well as an output), the same step can produce split sources rather than split pages: the pieces are Pandoc documents, and any writer can render them. DOCX may stay the exception, since a Pandoc round trip discards what Pandoc doesn't model.
