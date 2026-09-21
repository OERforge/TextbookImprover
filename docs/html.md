# HTML sources

An `.html` file beside the sources is one of two things, and the book says which. By default it's a page someone finished: it's copied into every HTML target as it stands and read only so the EPUB can carry it. Marked `convert: true` in `contents`, it's a source: read into the same intermediate a `.docx` gets, filtered, split, and rendered by every target.

```yaml
project:
  contents:
    - frontmatter            # a finished page, copied
    - title: Chapter 1
      convert: true          # everything in the group is a source
      items:
        - 1-1-supply
        - 1-2-demand
        - page: 1-3-credits
          convert: false     # except this one
```

The mark is inherited the way a role is, from a group to what's in it. One case needs no mark: a directory holding no `.docx` or `.md` and a project with no `contents` yet, where reading the pages is the only thing a conversion could mean. The run says it's doing so.

A target that writes its pages beside the sources (`output_dir: .`) would overwrite an HTML source with the page made from it, so the run refuses that combination.

## What is read, and what isn't

Pandoc's HTML reader does the reading, with two things set for it.

**`raw_html` is on.** Without it the reader fetches every `<iframe>` over the network to read its contents into the page. With it an `<iframe>` passes through as it is and nothing is fetched. The same now holds for a finished page read for the EPUB.

**`html-source.lua` runs first**, and turns what the page says about itself into declarations:

- A table with a header row (a `<thead>`, or a first row of nothing but `<th>`) and a `<th>` opening every body row is declared `both`; with one and not the other, `first-row` or `first-column`. That is the same declaration a `::: matrix` div makes for a Markdown table, and it outranks the guess. A table with no `<th>` anywhere is left undeclared and reported like any other; `table-headers.csv` doesn't reach HTML tables yet.
- What an earlier run of this pipeline derived is taken out so it can be derived again: Pandoc's title block (its subtitle and date are kept as metadata) and the scroll wrapper around a table.

The reader itself decides one more thing: when a page has exactly one `<main>` (or `role="main"`), only what's inside it is the page. Site navigation outside `<main>` is gone; a menu inside it is content as far as anyone can tell, since the reader keeps no trace of `<nav>`.

Images are files the page names by path, checked at the media gate and copied with the page, as for Markdown.

## Converting this pipeline's own pages changes nothing

That is the test this rests on: convert a book, convert the pages that produced, and the two runs agree under `compare-output.py`; convert those pages again and the third write equals the second byte for byte. Measured on *Introductory Business Statistics 2e* (169 pages, 228 tables, one difference: a caption the DOCX export wrote as a one-item list, which the second reading takes for the table's) and on a 34-page Markdown textbook (no difference). The first write from a Word source isn't the fixed point, for the reason it isn't for Markdown: Word's residue, a trailing space in a heading, is normalized on the way through.

## What this doesn't do yet

Pages saved from a website arrive with their navigation, their scripts' leftovers, links that point at the live site, and no order in their file names. Reading the order from the pages' own menus, stripping what isn't the book, and unpacking an EPUB or an `.mhtml` set into pages are the rest of the roadmap's first item.
