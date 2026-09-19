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

Two things about such a book are worth knowing. A chapter file with one `# Heading` gets it promoted to the page title, as a Word page's H1 is, and its `##` sections become the pages under it. And a file name with a space (`01 BigPicture.md`) works everywhere, but the pages it produces are called `01 BigPicture.html` and `01 BigPicture--learning-objectives.html`; `page-names.csv` renames the pieces, and renaming the file renames the page.

## What isn't here yet

Markdown as an *output*, so a book converted from Word can be maintained in Markdown, is the other half of roadmap item 1. And a Markdown table with no marker gets no guess and no report; the census that makes the guess reads Word files.
