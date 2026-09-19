# Pandoc notes

What Pandoc does, as read from its source or established by test, for the questions this project keeps asking. Separate from PROJECT-NOTES.md because it's about Pandoc, not about us. Read this before answering a "what does Pandoc do when…" question, and read the source before running an experiment: a shallow clone of `jgm/pandoc` at the version in use (3.11 as written) lives in the working container at `~/pandoc-src`, and the files below are where the answers are. Each entry says whether it was read from the source or measured.

## Where things are

- `src/Text/Pandoc/Readers/Docx.hs` — the DOCX reader's document walk: bookmarks, links, anchors, tables, styles to headers.
- `src/Text/Pandoc/Readers/Docx/Parse.hs` — the OOXML parse: what becomes a `BodyPart`, `ParPart`, `Run`; what is ignored.
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

**A style based on `Heading N` is a heading.** `Heading2Grey` (OpenStax) becomes a level-2 `Header` with the style as a class. Measured.

## The DOCX writer

**Drops a table's `id`.** Measured. **Writes `w:styleId` before `w:type`** in `styles.xml`, the reverse of Word's order; parse attributes by name. Measured. **The bundled `reference.docx` declares no `compatibilityMode`**, so every `.docx` Pandoc writes opens in Word's Compatibility Mode; deliberate (#5645, #5358).

## The Markdown reader and writer

**A plain raw HTML block is read one tag at a time.** `<table>…</table>` written as bare HTML comes back as dozens of `RawBlock`s (125 on one page). A fenced raw block (` ```{=html} `) is one `RawBlock`. Measured. Our Markdown target writes with `-raw_html` so every raw block is fenced.

**The writer drops cell spans silently.** A table with `colspan`/`rowspan` is written as a grid table with the spans removed and no warning (48 on one page, to none). Measured on 3.11; `Writers/Markdown/Table.hs` has no span handling. Our target writes such a table as HTML.

**A figure with attributes is written as a div.** `Writers/Markdown.hs` writes a `Figure` whose `Attr` is non-null as `::: {#id .figure}` holding the image and a `::: caption` div; the reader returns that as a `Div` around a `Figure`, not as the figure. Read from the source and measured. Our reading filter folds it back.

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

**`AttributeList` is not a plain table**: `next()` on it errors; iterate with `pairs`. Measured. **A filter's table of attributes is iterated in hash order**, so build an `Attr` from a list of pairs for stable output. Measured. **Filters in a returned list run in order**, each over the whole document; a handler returning `{}` removes the element, `nil` leaves it. **`pandoc.read(text, 'html')`** reads MathML into `Math` and `<thead>` into head rows; **`pandoc.write(doc, 'html', {html_math_method = 'mathml'})`** writes math as MathML. Measured.

## Upstream

Filed: #11869 (ScreenTip). Candidates, tracker searched, not filed: body-level bookmarks dropped (#6178 and #6781 unread, rate-limited); the orphan-anchor removal deleting cross-file targets (no search yet); the Markdown writer dropping spans without a warning; the EPUB chapter `<title>`.
