# Markdown sources

A `.md` file beside the sources is a page of the book, read the way a `.docx` is: Pandoc turns it into the same intermediate, the filter runs on it, `pages.split_level` cuts it, and every target renders it. A book can be some chapters in Word and some in Markdown, with a hand-written `.html` for the front matter, and each output holds all of them.

## What a Markdown page can say for itself

Word says nothing about which cells head a table or what a link is for; a Markdown source can, and the conversion reads it.

**Tables.** A fenced div around a table declares its headers, by class:

```markdown
::: matrix
|      | Left | Right |
|------|------|-------|
| Up   | 1    | 2     |
| Down | 3    | 4     |
:::
```

`::: matrix` means both a header row and a header column, so the first column comes out as `<th scope="row">` and the head as `<th scope="col">`. `tables.markers` in `conversion.yaml` maps classes to the values `table-headers.csv` takes (`first-row`, `first-column`, `both`, `none`), defaulting to `{matrix: both}`; a book that marks tables another way changes the map. A Markdown table with no marker is left as Pandoc read it, header row included; the guess and the report run only on Word sources, because the evidence they read is Word's.

**Links.** `[text](url){aria-label="…"}` carries into the HTML and the EPUB unchanged. Only the `markdown` and `commonmark_x` flavors keep the attribute; `gfm` rewrites the link as raw HTML.

**Images.** `![alt](assets/figure.png)` names a file by path. It is checked before anything is rendered, copied beside the page in every HTML target at the same relative path, and packed into the EPUB. A space in a file name is written `%20` in the Markdown, as a link must be, and the file on disk has the space; both ends handle it. A path with backslashes (`assets\figure.png`) resolves nowhere but Windows and stops the run at the media gate. Alt text comes from the Markdown itself; `image-alt.csv` still applies, keyed on the path.

**Raw LaTeX.** `\frontmatter`, `\chaptermark{…}`, and the like pass through Pandoc as raw blocks, which the HTML and EPUB writers drop. A PDF target, when there is one, would carry them.

## A book written for a Pandoc PDF build

A Markdown book is often set up for `pandoc *.md -o book.pdf`: a `_preamble.md` opening with a YAML block (title, author, LaTeX `header-includes`, `toc: true`, `pdfstandard`) and the front-matter chapters, then one file per chapter, then a back-matter file. Nothing about that needs changing for this pipeline, and only its structure is read: `\frontmatter`, `\mainmatter`, `\appendix`, `\backmatter`, and `{.appendix}` on a heading give the pages their `role` (see [Contents](configuration.md#contents)), and with `numbering: true` the HTML, EPUB, and cartridge count chapters and appendices the way the PDF does; `generate: toc` in `contents` makes the full table of contents a page. The preamble is a page like the others: its YAML becomes that page's metadata (the title is its title; epigraphs in `include-before` appear on that page in HTML), and with `split_level: 2` its front-matter chapters become pages of their own. The book's title, author, and structure come from `project.yaml`, as for any book. The PDF build stays the author's own Pandoc invocation until the PDF target exists, and that target is what would consume the preamble as written.

Two things about such a book are worth knowing. A chapter file with one `# Heading` gets it promoted to the page title, as a Word page's H1 is, and its `##` sections become the pages under it. And a file name with a space (`01 BigPicture.md`) gives a page named `01-BigPicture`, with its pieces `01-BigPicture--learning-objectives` and so on: spaces and other characters an href would have to encode are replaced, because an LMS may take an href literally. The same rule renames media a page refers to, in the copy beside the page; the source files keep their names.

## Markdown as a target

A target with `format: markdown` writes the book back as source, in Pandoc's own flavor: one `.md` per source document, or one per page when the target has a split level, with the images beside them.

```yaml
targets:
  src:
    format: markdown
    pages:
      split_level: 0      # one file per source, even if defaults split
```

The rule for what goes in the file: Markdown holds what the author decided; the filter holds what follows from it. So a decision the pipeline made from a sidecar, a pre-pass, or a marker is written as markup that reads back to the same decision, and after one round trip every correction that lived in a sidecar is in the source: which cells head a table, as the `tables.markers` class (`::: matrix` for a header row and column, `::: row-headers` for a header column alone; a header row alone and no headers need none); a table's caption, as its caption; alt text on the image, and `{.decorative}` on a decorative one; an anchor restored from a Word bookmark, as an empty span; the author in the YAML. What the filter derived is left out and rebuilt on the next read: the scroll wrapper, `scope` on header cells, `aria-hidden`, the split's provenance.

Two things Pandoc's Markdown can't say are written as fenced HTML blocks and read back into what they were: a table with merged cells (Pandoc's Markdown writer drops the spans silently otherwise) and a figure that carries an id. A lone image is marked `![alt](x.png)[]{.inline}` so it doesn't read back as a figure; the reading filter removes the mark.

The checks, which the driver's test suite runs on the fixtures: read the Markdown back as a book and the HTML is the same (`compare-output.py` says `Runs agree`; on *Introductory Business Statistics 2e*, 169 pages, every page identical); write it again and nothing changes. A source that came from Word settles after one write, from Word's stray spaces and from grid-table widths rounded to characters, so the second write is the fixed point and the third equals it. A Markdown source is normalized the same way on its first pass: a promoted heading becomes the YAML `title:`, `_italics_` becomes `*italics*`, hard-wrapped lines are joined, and a pipe table wide enough to have been read with column widths comes back as a grid table. Content is unchanged; form is Pandoc's.

What is lossy, and known: grid-table widths are Pandoc's approximation to the character; a merged-cell table round-trips in structure but is the manual case it always was.

## What isn't here yet

A Markdown table with no marker gets no guess and no report; the census that makes the guess reads Word files. And merging sections into their chapter (one file per `contents` group from sources cut at the section level, as OpenStax ships them) is the next thing a Markdown target should do.
