# Pandoc notes

What Pandoc does, as read from its source or established by test, for the questions this project keeps asking. Separate from PROJECT-NOTES.md because it's about Pandoc, not about us. Read this before answering a "what does Pandoc do when…" question, and read the source before running an experiment: a shallow clone of `jgm/pandoc` at the version in use (3.11 as written) lives in the working container at `~/pandoc-src`, and the files below are where the answers are. Each entry says whether it was read from the source or measured.

## Where things are

- `src/Text/Pandoc/Readers/Docx.hs` — the DOCX reader's document walk: bookmarks, links, anchors, tables, styles to headers.
- `src/Text/Pandoc/Readers/Docx/Parse.hs` — the OOXML parse: what becomes a `BodyPart`, `ParPart`, `Run`; what is ignored.
- `src/Text/Pandoc/Readers/HTML.hs` (and `Readers/HTML/`) — what becomes a `Div`, what is skipped, `extractMain`, iframes, MathJax, math in `<script>`.
- `src/Text/Pandoc/Readers/EPUB.hs` — 300 lines: the spine walk, the id and link rewriting, what metadata is read.
- `src/Text/Pandoc/Writers/EPUB.hs` — chunking, the chapter template's variables, the OPF and nav, accessibility metadata.
- `src/Text/Pandoc/Writers/Markdown.hs` (and `Writers/Markdown/Table.hs`) — which table form is written, what becomes raw HTML, how figures are written.
- `src/Text/Pandoc/Readers/Markdown.hs` — raw HTML blocks, implicit figures, the `figure` div.
- `src/Text/Pandoc/Lua/Marshal/` — what a filter sees: `AttributeList`, `List`, the `Attr` constructor.
- `data/templates/default.epub3`, `data/epub.css`, `data/docx/` (the reference document).

## The DOCX reader

**Bookmarks become anchors only when linked from the same document.** `parPartToInlines'` turns a bookmark into a `Span` with class `anchor`; `rewriteLinks` records every `#target` a link in the document uses in `docxAnchorSet`; `removeOrphanAnchors` then deletes every anchor span whose id is not in that set (`Readers/Docx.hs` 870–899). Consequence: a bookmark that only *another* file links to — every index term, every cross-chapter reference in an OpenStax export — is gone. Read from the source; measured on *Clinical Nursing Skills* (`term-00044`). Our repair adds an invisible link per unlinked bookmark so the set contains it.

**A bookmark inside a heading paragraph does not keep its name.** In a header, the reader records `bookmark → header id` in `docxAnchorMap` and rewrites same-file links to the header's auto id; the name itself never appears in the output (the `inHdrBool` branch of `parPartToInlines'`). So a bookmark that has to be addressable by name from another file cannot sit in a heading; our repair puts one before a heading into an empty paragraph of its own. Read from the source.

**Two bookmarks in a row collapse into one anchor.** `docxImmedPrevAnchor` holds the last bookmark seen until a non-bookmark part resets it; a bookmark seen while it is set is mapped to the previous name and dropped. The state carries across paragraphs. Read from the source (`parPartToInlines'`); measured on `term-00022`, which followed another bookmark. Our repair puts a zero-width run between adjacent bookmarks inside a paragraph, and at the start of a bookmark-only paragraph, and the filter removes the character.

**Body-level bookmarks are dropped.** `w:bookmarkStart` as a direct child of `w:body` (between blocks, which is where OpenStax puts one for a paragraph, list, heading, or table) is not a `ParPart` of any paragraph, so nothing makes an anchor of it. Measured (4,231 in one book); consistent with the parse. Our repair moves them into the following paragraph, or hands the ones before a table to the filter through the pre-pass.

**A link with no text is dropped before its target is recorded.** An empty hyperlink run yields no inlines and no `Link`; the anchor set never sees it. Measured. The keeper links carry a zero-width space.

**Metadata comes from `Title`/`Author`-styled paragraphs, not `docProps/core.xml`.** Measured on 3.11; open upstream as #3034. The first `Title` paragraph becomes the title, later ones plain paragraphs.

**A hyperlink's ScreenTip (`w:tooltip`) is discarded** in both directions. Measured; filed as #11869.

**`w:tblHeader w:val="0"` read as a header row until 3.10.** Measured across versions.

**Heading ids are made unique against the anchor map's values, and a bookmark can hold the next candidate.** `makeHeaderAnchor'` computes a heading's id with `uniqueIdent`, checking each candidate (`base`, `base-1`, `base-2`, …) against `M.elems docxAnchorMap` (`Readers/Docx.hs` 589; `Shared.hs` 616). OpenStax names the bookmark for a repeated heading `site-selection-1`, which is exactly the candidate the second "Site Selection" heading is offered, so two headings got one id. Read from the source; measured on *Clinical Nursing Skills* (16 pages). Our filter renumbers duplicates as its last pass.

**A style based on `Heading N` is a heading.** `Heading2Grey` (OpenStax) becomes a level-2 `Header` with the style as a class. Measured.

## The HTML reader

**One `<main>` is the whole document.** `extractMain` keeps only the contents of the element with `role="main"` (a `<main>` gets that role on read) when the page has exactly one, and everything otherwise (`Readers/HTML.hs`, after `parseDoc`). Read from the source; measured on 60 just-the-docs pages, where the site navigation is gone with no work from us. A generator that marks its content with a `div` and a class gets no such help.

**`<nav>` and `<footer>` leave no trace of themselves.** `isDivLike` is `div`, `section`, `header`, `main`, `aside`; `section`, `header`, and `aside` become a `Div` with that class. A `<nav>`'s tags are skipped and its list is read as an ordinary `BulletList`, so a filter cannot tell a menu from content. Read from the source; measured (a page's own table of contents inside `<main>` arrives as a list of links). What has to go has to go from the DOM, before Pandoc.

**An `<iframe src>` is fetched over the network unless `raw_html` is on**, which it isn't by default for this reader: `pIframe` is guarded by `guardDisabled Ext_raw_html`, opens the URL, and reads what comes back into a `Div` with class `iframe`. With `-f html+raw_html` the tag is two `RawBlock`s and nothing is fetched. Read from the source and measured (the fetch attempt is logged as `Could not fetch resource`). The EPUB reader turns `raw_html` on itself.

**MathJax's rendering is skipped, its source is read.** Spans with class `mjx-chtml`, `MathJax_CHTML`, or `MathJax_Preview` are dropped (#10673), and `<script type="math/tex">` becomes `Math`, display when the type ends in `display`. Measured: 36 scripts, 36 `Math`, no duplicates. Not covered: MathJax 2's HTML-CSS output (class `MathJax`, with `mi`/`mo`/`mrow` spans), which is read as nested spans of text. A page saved as MHTML has no scripts, so there the TeX is gone and only that rendering is left.

**A `<th>` in every body row is a header column; the reader works it out.** `pTableBody` counts the leading `<th>` cells of each row and sets `RowHeadColumns` when every row agrees, 0 when they don't (`Readers/HTML/Table.hs`, citing #8984 and #8634); `scope` rides along as an attribute on the cell. A row of `<th>` alone at the top is the head even with no `<thead>`. Read from the source and measured. So the roadmap's old note that the reader "keeps the attribute but not the element" was wrong for the ordinary case, and what lost our own pages' row headers on reading them back was our filter, which sets `row_head_columns` to 0 on any table with no declaration, because a Word table never arrives with one. `html-source.lua` turns what the reader found into a declaration.

**A paragraph keeps none of its attributes.** `pPara` builds a `Para` from the inlines and discards the tag's class and id. `<p class="subtitle">` and `<p class="date">` in Pandoc's own title block come back as bare paragraphs, and so does a web page's `<p class="caption">`. Read from the source and measured. Anything a paragraph's class has to say must be said before Pandoc reads it, or read out of the file.

**Pandoc's own title block is content to the reader**: `<header id="title-block-header">` becomes a `Div` with that id, while `<title>` and the `<meta name=…>` elements become metadata. Measured: reading our own page and writing it again gave two titles.

**An inline `<svg>` becomes an `Image` with a `data:` URI** (`pSvg`), including a twelve-pixel link icon inside a heading. Measured.

**The reader is lenient where an XML parser is not.** An EPUB content document with an unclosed `<br>` (Asciidoctor's, in one of our samples) reads without complaint; `xml.etree` refuses the file and epubcheck calls it fatal (RSC-016). Measured.

## The EPUB reader

**The spine is concatenated into one document**, each file preceded by an empty `Span` whose id is the file's name, and non-linear items are dropped (`parseSpine`). Only `dc:` elements become metadata: no `meta property=` (so none of the `schema:accessibility*` claims), and each file's own `<title>` and `lang` are lost. Read from the source.

**Every id is rewritten to `<file>_<id>`, but only on `Div`, `Header`, `CodeBlock`, `Span`, `Code`, and `Link`** (`fixBlockIRs`, `fixInlineIRs`), while every internal link is rewritten to `#<file>_<fragment>`. A `Figure`, `Table`, or `Image` keeps its bare id, so a link to a figure or a table is dead after reading. Read from the source; measured on a Pressbooks EPUB (117 figure ids and 6 table ids unprefixed). Candidate upstream report; tracker not searched yet.

**Every `epub:` attribute is removed** (`removeEPUBAttrs`), so `epub:type="footnote"`, `noteref`, and the landmarks leave nothing. Read from the source.

**The navigation document is not read** unless the spine lists it, and then it is content.

## The DOCX writer

**Drops a table's `id`.** Measured. **Writes `w:styleId` before `w:type`** in `styles.xml`, the reverse of Word's order; parse attributes by name. Measured. **The bundled `reference.docx` declares no `compatibilityMode`**, so every `.docx` Pandoc writes opens in Word's Compatibility Mode; deliberate (#5645, #5358).

## The Markdown reader and writer

**The reader keeps duplicate ids and warns.** `[WARNING] Duplicate identifier 'x' at file.md line N` on stderr; both elements keep the id. Measured on a merged file with 733 of them. Relevant because Pandoc's HTML writer then emits invalid HTML without complaint.


**A plain raw HTML block is read one tag at a time.** `<table>…</table>` written as bare HTML comes back as dozens of `RawBlock`s (125 on one page). A fenced raw block (` ```{=html} `) is one `RawBlock`. Measured. Our Markdown target writes with `-raw_html` so every raw block is fenced.

**The writer drops cell spans silently.** A table with `colspan`/`rowspan` is written as a grid table with the spans removed and no warning (48 on one page, to none). Measured on 3.11; `Writers/Markdown/Table.hs` has no span handling. Our target writes such a table as HTML.

**A figure with attributes is written as a div.** `Writers/Markdown.hs` writes a `Figure` whose `Attr` is non-null as `::: {#id .figure}` holding the image and a `::: caption` div; the reader returns that as a `Div` around a `Figure`, not as the figure. Read from the source and measured. Our reading filter folds it back.

**A tight list item holds a `Plain`, and reads back loose.** A one-item list in a grid cell written as `- ![…]` comes back as a `Para` in the item, and a lone image in a `Para` is a figure. Measured. Our not-a-figure mark goes on `Plain` as well as `Para`.

**A lone image is a figure on read (`implicit_figures`).** The documented way to say "not a figure" is a non-breaking space after it (`\ `), which becomes a hard line break when a grid cell wraps at it. Measured. Our target writes an empty `[]{.inline}` span instead; an empty span with no attributes is not written at all.

**`smart` puts a non-breaking space after an abbreviation** ("vs.", "e.g."), including inside image alt text. Measured. The filter plainifies alt text.

**A wide pipe table is read with relative widths** (a row longer than `--columns`), and a table with widths is written as a grid table whose dashes round the width to a character, drifting by one per write. Measured. Our target carries widths as an attribute and writes pipe tables.

**Math ending in `\ ` before the closing `$` is not math.** The closing `$` may not follow whitespace. Measured.

**Table attributes** are written and read on the caption line (`: Caption {#id}`) and, for us, on a wrapping div.

## The EPUB writer

**Chapter files are titled by file name**: the template's `<title>$pagetitle$</title>` is filled with `ch002.xhtml` by the writer's own variables (`Writers/EPUB.hs`), and `title-meta` is empty in a chapter. Read from the source and measured. Our assembler rewrites each `<title>` from the chapter's heading after the archive exists.

**Accessibility metadata is read from document metadata** (`accessModes`, `accessModeSufficient`, `accessibilityFeatures`, `accessibilityHazards`, `accessibilitySummary`) since 3.1.12; `--epub-metadata` drops `schema:` properties. Measured on 3.11.

**`--css` replaces `epub.css`** rather than adding to it. **Chapter splitting is by heading level only.** **The heading's id goes on the `<section>`**, not the heading. **Every image gets an `alt`**, so decorative and undescribed look alike. **Footnotes are `<aside epub:type="footnote">` with no number.** **A footnote number restarts per chapter file.** **The cover is an SVG `<image>` with no text alternative.** **The footnotes `<section>` has no heading.** All measured.

**Several JSON inputs concatenate; the last file's metadata wins.** Measured.

## The HTML writer

**Emits a bare `<th>` for a row-header column** (`row_head_columns`), never `<th scope="row">`; scope is the filter's to add. **`--include-in-header` replaces the `header-includes` metadata field** rather than merging. **`$title$` in a template renders inlines**, so a heading's `<em>` lands inside `<title>`. **Small lengths are written in scientific notation** (`5.0e-2in`). All measured.

## The Lua filter environment

**Within one filter table, every inline is walked before any block.** So a `Div`/`Span` handler pair that renames ids sees every span before every heading; a handler that must see elements in document order has to walk the blocks itself. Measured (`figures-and-tables.lua`, `make_ids_unique`).


**`AttributeList` is not a plain table**: `next()` on it errors; iterate with `pairs`. Measured. **A filter's table of attributes is iterated in hash order**, so build an `Attr` from a list of pairs for stable output. Measured. **Filters in a returned list run in order**, each over the whole document; a handler returning `{}` removes the element, `nil` leaves it. **`pandoc.read(text, 'html')`** reads MathML into `Math` and `<thead>` into head rows; **`pandoc.write(doc, 'html', {html_math_method = 'mathml'})`** writes math as MathML. Measured.

## Upstream

Filed: #11869 (ScreenTip). Candidates, tracker searched, not filed: body-level bookmarks dropped (#6178 and #6781 unread, rate-limited); the orphan-anchor removal deleting cross-file targets (no search yet); the Markdown writer dropping spans without a warning; the EPUB chapter `<title>`.
