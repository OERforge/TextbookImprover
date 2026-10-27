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

`::: matrix` means both a header row and a header column, so the first column comes out as `<th scope="row">` and the head as `<th scope="col">`. `tables.markers` in `conversion.yaml` maps classes to the values `table-headers.csv` takes (`first-row`, `first-column`, `both`, `none`), defaulting to `{matrix: both, row-headers: first-column}`; a book that marks tables another way changes the map. A Markdown table with no marker is left as Pandoc read it, header row included: the guess and the report run on Word, HTML, and LaTeX sources, not on Markdown.

**Links.** `[text](url){aria-label="…"}` carries into the HTML and the EPUB unchanged. Only the `markdown` and `commonmark_x` flavors keep the attribute; `gfm` rewrites the link as raw HTML.

**Images.** `![alt](assets/figure.png)` names a file by path. It is checked before anything is rendered, copied beside the page in every HTML target at the same relative path, and packed into the EPUB. A space in a file name is written `%20` in the Markdown, as a link must be, and the file on disk has the space; both ends handle it. A path with backslashes (`assets\figure.png`) resolves nowhere but Windows, and a name in another case than its file's (`assets/Figure.PNG` for `assets/figure.png`) nowhere but macOS and Windows: when the same path with forward slashes, or the name in its file's case, is a file, the run reads it that way and warns, naming the source and the path. The fix is still to change the source, since a Pandoc build anywhere else won't find the image. An image that resolves neither way stops the run at the media gate. A link to a file the page offers, a PDF or a spreadsheet beside it, is copied beside the page as an image is and found the same way, its fragment kept, from a Word, HTML, or AsciiDoc source too; one that resolves neither way isn't checked at the media gate, but the packager stops on it. Alt text comes from the Markdown itself; `image-alt.csv` still applies, keyed on the path.

**Raw LaTeX.** `\frontmatter`, `\chaptermark{…}`, and the like pass through Pandoc as raw blocks, which the HTML and EPUB writers drop. A [PDF target](formats.md#pdf) carries them, except the four division commands, which it writes from the pages' roles instead.

### Merging sections into chapters

A book whose sources are one file per section, as OpenStax ships them, comes back as one file per chapter when the target says so:

```yaml
targets:
  src:
    format: markdown
    merge: groups
```

One file per top-level entry of the book's [contents](configuration.md#contents), named after the source its pages came from when they share one and after the entry's title otherwise; each page becomes a section under it, nested the way the book is, so a chapter's sections are one level down and pages cut from them another. A page the contents never names is a file of its own, so nothing is dropped. On *Introductory Business Statistics 2e* that is 853 pages into 17 files.

What merging follows is the book's declared structure, so it's worth declaring it: with no `contents`, the guess is used, and for a single source cut into pages that is mostly a flat list, which gives one file per page and merges little. Declare the chapters as groups and each becomes a file.

Media travel under the names the author gave them, since what a markdown target writes is source; every other target copies them under names that need no encoding in a link. With `media.lowercase`, each target copies them under their names in lowercase, the letters A to Z, and the pages and the copy name them so; two files whose names differ only in case then stop the run before anything is written, as two that one safe name would cover do. A target written into the folder that holds the sources, on a file system that ignores case, finds a source's own file under its lowercase name and leaves it as it's named, which a server that tells case apart won't find; the run warns of it, and a folder of the target's own is the fix. A `source` target's copies keep the author's references, since they name the author's own files.

Links follow: a link to a page now in the same file becomes a link to its anchor, one to a page in another file names that file, and a link naming a file that no longer has a page of its own points at the file. Each merged page keeps an anchor of its own name, so a link can still reach it. Where two pages of a chapter used the same id (the export numbers some anchors per file), the later one is renamed and the links in that page follow it, which can only be done here, while the page boundary is still known.

## A book written for a Pandoc PDF build

A Markdown book is often set up for `pandoc *.md -o book.pdf`: a `_preamble.md` opening with a YAML block (title, author, LaTeX `header-includes`, `toc: true`, `pdfstandard`) and the front-matter chapters, then one file per chapter, then a back-matter file. Nothing about that needs changing for this pipeline, and only its structure is read: `\frontmatter`, `\mainmatter`, `\appendix`, `\backmatter`, and `{.appendix}` on a heading give the pages their `role` (see [Contents](configuration.md#contents)), and with `numbering: true` the HTML, EPUB, and cartridge count chapters and appendices the way the PDF does; `generate: toc` in `contents` makes the full table of contents a page. The preamble is a page like the others: its YAML becomes that page's metadata (the title is its title; epigraphs in `include-before` appear on that page in HTML), and with `split_level: 2` its front-matter chapters become pages of their own. A YAML block never reaches another file: the book's title, author, language, and structure come from `project.yaml`, as for any book, and each file's YAML describes that file: its `lang`, the page's language, where it's another than the book's ([A page's language](sidecars.md#a-pages-language)). A raw HTML comment in a source is dropped by the filter for every output, since a comment says nothing to a reader and one holding `--` breaks XHTML. A [PDF target](formats.md#pdf) consumes the preamble as written: `pdf.metadata: _preamble.md` gives its YAML to the LaTeX writer, the class, `header-includes`, epigraphs and all, and the preamble page draws no heading of its own, since its title is the book's. What the YAML doesn't set of the page, the PDF target's default page does, its line spacing and ragged right among them, and margins or line spacing the `header-includes` set themselves are kept ([The PDF's page](configuration.md#the-pdfs-page)).

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

Four things Pandoc's Markdown can't say are written as fenced HTML blocks and read back into what they were: a table with merged cells (Pandoc's Markdown writer drops the spans silently otherwise), a table whose groups each open with a header row of their own (the writer makes those rows ordinary ones, and the groups one), a layout table, with its `role="presentation"`, which a pipe table has nowhere to keep, and a figure that carries an id. A lone image is marked `![alt](x.png)[]{.inline}` so it doesn't read back as a figure; the reading filter removes the mark. And a numbered list inside a list's item that starts past its first number, such as `b.` under `5.`, or `3.` under `B.` where a list goes on from a page or a slide before, is written from its first number, its own start an empty span at its first item, `1.  []{start="3"}`, which the reading filter puts back: since 3.10.1, Pandoc's Markdown reader reads a list inside an item that starts anywhere else as text ([its manual](https://pandoc.org/MANUAL.html#extension-fancy_lists): "ordered sublists must start with `1`"), though its writer still writes one. So it is for a list in a definition, which the reader reads as it reads an item, and in a quotation or a div inside an item; a list in none of these keeps its own start. Emphasis, bold, underline, strikethrough, a superscript, or a subscript that ends in a line break, a span with no attributes at its end holding the break included (an HTML page's `<em><span>for any<br></span></em>`), is closed before the break, `*for any*\`: Pandoc's writer closes it after the break's backslash, `*for any\*`, which its reader takes for an escaped asterisk, so the mark was lost and its asterisks were text (measured, Pandoc 3.12.1). A superscript or a subscript with a break inside it is cut at the break, `x^a^\` and `^b^` on the next line, since the reader takes a break back nowhere in a script, which ends before a space or a line's end. A break inside another mark or at its start, or at the end of a span or a link, stays where it is, since the reader takes those back.

Tables are pipe tables, and a table's column widths (Word's, or a wide pipe table's) travel as an attribute on the wrapping div, `::: {.matrix widths="0.28 0.36 0.36"}`, exact to four places and applied on the next read; a grid table appears only where a cell holds a block or a line break. That is also the route a DOCX target will take the same widths back by. Pandoc's writer before 3.13 writes such a table as a grid table only where the line has room for 8 characters a column, 72 by default, and a wider one as the text `[TABLE]`, without a warning, so with such a Pandoc a table of 10 columns or more with a block or a line break in a cell is written as a fenced HTML block, which reads back as the table it was; 3.13 writes it as a grid table at any width ([#11945](https://github.com/jgm/pandoc/issues/11945)).

The checks, which the driver's test suite runs on the fixtures: read the Markdown back as a book and the HTML is the same (`compare-output.py` says `Runs agree`; on *Introductory Business Statistics 2e*, 169 pages, every page identical); write it again and nothing changes. A source that came from Word settles after one write, from Word's own residue (paragraphs holding only a non-breaking space, leading and trailing spaces, an escaped `a\.`), so the second write is the fixed point and the third equals it. A Markdown source is normalized the same way on its first pass: a promoted heading becomes the YAML `title:`, `_italics_` becomes `*italics*`, hard-wrapped lines are joined. Content is unchanged; form is Pandoc's.

What is lossy, and known: a merged-cell table round-trips in structure but is the manual case it always was.

A link keeps its title. Pandoc's writer writes a link whose text is its own address as an autolink, `<https://…>`, which has no room for one, so a titled one is written in full: `[https://…](https://… "its title")`.

## What isn't here yet

A Markdown table with no marker gets no guess and no report: the census that makes the guess reads Word, HTML, and LaTeX sources, and a Markdown table's own marker is the way to declare its headers.

## Raw HTML

HTML written into a Markdown source gets what an HTML source's HTML gets. Pandoc's Markdown reader keeps it a tag at a time (`x<sup>2</sup>` is a raw `<sup>`, the text `2`, and a raw `</sup>`), so `markdown-html.lua` puts each opening tag back together with its closing tag and what lies between, and reads the whole with Pandoc's HTML reader: the superscript is a superscript, an `<img>` an image the media gate checks and the run copies, a `<table>` a table the header sidecar reaches. What comes back is cleaned by the same two filters an HTML source goes through, loaded from their own files: HTML's obsolete presentational attributes (`align`, `valign`, `bgcolor`, and their kind) go, an `href` on a `<span>` goes, a frame becomes an embed, a tag with no element and no match is dropped with what it wrapped kept, and `<details>` and `<summary>` are kept.

Code is never touched: a code span or block is a Code element and holds no raw HTML to find, and a raw `<pre>`, `<code>`, `<script>`, or `<style>` is left as written. On CS168's Markdown, 796 raw HTML elements were read this way and the book's EPUB went from 103 epubcheck errors to none.
