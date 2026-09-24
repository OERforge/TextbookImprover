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

**A hyperlink's ScreenTip (`w:tooltip`) is discarded** in both directions. Measured; filed as #11869. jgm replied on 2026-09-22: he treats a ScreenTip as the counterpart of HTML's `title` and would map it to the `Link` title in both directions, by default with no extension, and for internal links too if feasible. `w:hyperlinkRuby` and the question about contributing a patch drafted with Claude went unanswered. The *Introductory Business Statistics* files hold 2,324 hyperlinks and no ScreenTip, so for OpenStax books the change will bring nothing in; its value is for authors who write them.

**`w:tblHeader w:val="0"` read as a header row until 3.10.** Measured across versions.

**Heading ids are made unique against the anchor map's values, and a bookmark can hold the next candidate.** `makeHeaderAnchor'` computes a heading's id with `uniqueIdent`, checking each candidate (`base`, `base-1`, `base-2`, …) against `M.elems docxAnchorMap` (`Readers/Docx.hs` 589; `Shared.hs` 616). OpenStax names the bookmark for a repeated heading `site-selection-1`, which is exactly the candidate the second "Site Selection" heading is offered, so two headings got one id. Read from the source; measured on *Clinical Nursing Skills* (16 pages). Our filter renumbers duplicates as its last pass.

**A style based on `Heading N` is a heading.** `Heading2Grey` (OpenStax) becomes a level-2 `Header` with the style as a class. Measured.

**Row 1 is a header row whenever Word's table look says the table has one.** `splitHeaderRows (firstRowFormatting look)` in `Readers/Docx.hs`: with the first-row flag set in `w:tblLook`, row 1 is the head, and the rows after it join the head while they're marked to repeat (`w:tblHeader`) or continue a cell merged down from one; without the flag, only rows marked to repeat do, and when the first such row comes after unmarked ones, those are promoted with it so the order holds. So a header row can be declared by nothing but the table's style. The header pre-pass counts it as shared by every part of a banded table, as the filter copies it, and a declared `none` turns it back into ordinary cells: *Business Communication*'s Table 22.6 lost its header row that way until the per-part guess learned this. Read from the source (3.11).

## The HTML reader

**One `<main>` is the whole document.** `extractMain` keeps only the contents of the element with `role="main"` (a `<main>` gets that role on read) when the page has exactly one, and everything otherwise (`Readers/HTML.hs`, after `parseDoc`). Read from the source; measured on 60 just-the-docs pages, where the site navigation is gone with no work from us. A generator that marks its content with a `div` and a class gets no such help.

**`<nav>` and `<footer>` leave no trace of themselves.** `isDivLike` is `div`, `section`, `header`, `main`, `aside`; `section`, `header`, and `aside` become a `Div` with that class. A `<nav>`'s tags are skipped and its list is read as an ordinary `BulletList`, so a filter cannot tell a menu from content. Read from the source; measured (a page's own table of contents inside `<main>` arrives as a list of links). What has to go has to go from the DOM, before Pandoc.

**An `<iframe src>` is fetched over the network unless `raw_html` is on**, which it isn't by default for this reader: `pIframe` is guarded by `guardDisabled Ext_raw_html`, opens the URL, and reads what comes back into a `Div` with class `iframe`. With `-f html+raw_html` the tag is two `RawBlock`s and nothing is fetched. Read from the source and measured (the fetch attempt is logged as `Could not fetch resource`). The EPUB reader turns `raw_html` on itself.

**MathJax's rendering is skipped, its source is read.** Spans with class `mjx-chtml`, `MathJax_CHTML`, or `MathJax_Preview` are dropped (#10673), and `<script type="math/tex">` becomes `Math`, display when the type ends in `display`. Measured: 36 scripts, 36 `Math`, no duplicates. Not covered: MathJax 2's HTML-CSS output (class `MathJax`, with `mi`/`mo`/`mrow` spans), which is read as nested spans of text. A page saved as MHTML has no scripts, so there the TeX is gone and only that rendering is left. So a CommonHTML formula in an `.mhtml` save vanishes with no trace, and an SVG one leaves nothing to read. `lib/mathjax.py` replaces every MathJax rendering, of any version, before Pandoc reads the page.

**A `<th>` in every body row is a header column; the reader works it out.** `pTableBody` counts the leading `<th>` cells of each row and sets `RowHeadColumns` when every row agrees, 0 when they don't (`Readers/HTML/Table.hs`, citing #8984 and #8634); `scope` rides along as an attribute on the cell. A row of `<th>` alone at the top is the head even with no `<thead>`. Read from the source and measured. So the roadmap's old note that the reader "keeps the attribute but not the element" was wrong for the ordinary case, and what lost our own pages' row headers on reading them back was our filter, which sets `row_head_columns` to 0 on any table with no declaration, because a Word table never arrives with one. `html-source.lua` turns what the reader found into a declaration.

**Footnotes are read back into notes, keyed on the id of the element that holds the note.** A link with `role="doc-noteref"` (always) or `epub:type="noteref"` (with `epub_html_exts`) becomes a placeholder; inside an element with `role="doc-endnotes"` or `epub:type="footnotes"`, each child's content is filed under that child's own `id` (`eNoteref`, `eFootnotes`, `eFootnote`); `replaceNotes` joins them, and a reference with no match is an empty `Note` and a warning, `Reference not found`. So Pandoc's own endnotes round-trip, and anything that moves a note's id off its `<li>` empties every note on the page with the text gone. Read from the source; measured the hard way. The same block drops an element whose `epub:type` contains `titlepage`, with or without the extension.

**An id survives only where the AST has somewhere to put it**: div, section, span, heading, link, image, figure, table, code. `<p>`, `<li>`, `<dt>`, `<dd>`, `<td>`, `<th>`, `<caption>`, `<figcaption>`, `<blockquote>`, and the inline marks (`em`, `strong`, `sup`, …) lose theirs. Measured: a link to `<p id="deep">` was dead after reading. `lib/htmlrepair.py` moves those ids onto empty spans first.

**With `raw_html` on, a tag the reader has no element for is a fragment of raw markup**, opening and closing tags separately: `<footer>`, `<nav epub:type="toc">`, `<cite>`, and an unbalanced `</code>` the author never opened, which the writers then pass through. Measured: that last one made an EPUB that was not well-formed. `html-source.lua` drops the fragments and keeps what was between them, which is what the reader does with `raw_html` off.

**The HTML reader gives a heading an id from its text when it has none** (`auto_identifiers` is on for it), so an anchor inside a heading can't simply take the heading's place: it has one already. Measured.

**The EPUB writer builds each navigation entry from the heading's inlines**, attributes and all, so an empty `<span id>` inside a heading is an empty span inside `<nav>`, which epubcheck rejects. Measured on 11 headings.

**An id with whitespace in it is kept as it is**, from `<a name="section 15">` or `id="section 15"`, though neither HTML nor XHTML allows one; the writers then emit it, and epubcheck rejects each (RSC-005, 469 in DCIC). Measured. `html-source.lua` makes the whitespace a hyphen, in ids and in links' fragments.

**An empty alt and no alt read the same.** `<img alt="">` and `<img>` both become an `Image` with an empty caption, and the HTML writer writes that with no `alt` at all. In HTML an empty alt is the author saying the image is decorative, so without help every deliberately decorative image comes out undescribed, and a screen reader reads its file name. Measured. `lib/htmlrepair.py` gives such an image, and one with `role="presentation"` and no alt (Canvas's way), the class `decorative` before Pandoc reads the page, which the filter writes as `alt=""`.

**A paragraph keeps none of its attributes.** `pPara` builds a `Para` from the inlines and discards the tag's class and id. `<p class="subtitle">` and `<p class="date">` in Pandoc's own title block come back as bare paragraphs, and so does a web page's `<p class="caption">`. Read from the source and measured. Anything a paragraph's class has to say must be said before Pandoc reads it, or read out of the file.

**Pandoc's own title block is content to the reader**: `<header id="title-block-header">` becomes a `Div` with that id, while `<title>` and the `<meta name=…>` elements become metadata. Measured: reading our own page and writing it again gave two titles.

**An inline `<svg>` becomes an `Image` with a `data:` URI** (`pSvg`), including a twelve-pixel link icon inside a heading. Measured.

**The reader is lenient where an XML parser is not.** An EPUB content document with an unclosed `<br>` (Asciidoctor's, in one of our samples) reads without complaint; `xml.etree` refuses the file and epubcheck calls it fatal (RSC-016). Measured.

**`<details>` and `<summary>` have no element.** With `raw_html` they arrive as raw fragments, a tag at a time, and a summary's text between them becomes a `Para`, which is invalid inside `<summary>` once written back. Without `raw_html` the tags are dropped and the answer they hid sits open on the page. Measured; the Markdown reader does the same.

**Pandoc's own math markup doesn't read back as math.** `<span class="math inline">\(k^2\)</span>`, which the HTML writer produces for MathJax, is read as a `Span` with those classes holding the literal text `\(k^2\)`. Measured. What does read as math is `<script type="math/tex">` (MathJax 2's markup), or the delimiters themselves with `tex_math_single_backslash`, next.

**`tex_math_single_backslash` finds math inside `<code>`.** `<code>\(not math\)</code>` comes back as `Math InlineMath "not math"`. Measured. So the extension is unsafe for a programming book; `unpack-site.py` converts MathJax's delimiters itself, outside code, into `<script type="math/tex">`. Candidate upstream report.

**A table grouped by `<tbody>` keeps its groups.** Each `<tbody>` whose first row holds a `<th>` becomes a table body with that row as its own head row, and the HTML writer writes it back as a `<tbody>` with the row as `<th>` cells, attributes kept (`scope="rowgroup"`). So HTML to HTML preserves row groups exactly. Measured.

**Bold or italic written as a style isn't read as bold or italic.** `<span style="font-weight: bold">` is a `Span` keeping its `style` attribute, not `Strong`, which is how Scribble and many exporters write a header row. Measured; `html-source.lua` makes it `Strong` and `Emph`.

## The EPUB reader

**The spine is concatenated into one document**, each file preceded by an empty `Span` whose id is the file's name, and non-linear items are dropped (`parseSpine`). Only `dc:` elements become metadata: no `meta property=` (so none of the `schema:accessibility*` claims), and each file's own `<title>` and `lang` are lost. Read from the source.

**Every id is rewritten to `<file>_<id>`, but only on `Div`, `Header`, `CodeBlock`, `Span`, `Code`, and `Link`** (`fixBlockIRs`, `fixInlineIRs`), while every internal link is rewritten to `#<file>_<fragment>`. A `Figure`, `Table`, or `Image` keeps its bare id, so a link to a figure or a table is dead after reading. Read from the source; measured on a Pressbooks EPUB (117 figure ids and 6 table ids unprefixed). Candidate upstream report; tracker not searched yet.

**Every `epub:` attribute is removed** (`removeEPUBAttrs`), so `epub:type="footnote"`, `noteref`, and the landmarks leave nothing. Read from the source.

**The navigation document is not read** unless the spine lists it, and then it is content.

## The DOCX writer

**Drops a table's `id`.** Measured. **Writes `w:styleId` before `w:type`** in `styles.xml`, the reverse of Word's order; parse attributes by name. Measured. **The bundled `reference.docx` declares no `compatibilityMode`**, so every `.docx` Pandoc writes opens in Word's Compatibility Mode; deliberate (#5645, #5358).

**The DOCX writer flattens a table's bodies into one.** A body's head row becomes an ordinary row, and a head row that is one cell spanning the table becomes a merged cell (`w:gridSpan`): Word's own form for a band. Read back, it's one body with that row as a spanning `<td>`, which is the shape the header pre-pass infers bands from. So a grouped table survives a trip through Word in meaning, not in markup. Measured.

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

**The reader parses `<span>` and `<div>` and keeps every other tag raw, one tag at a time.** `x<sup>2</sup>` is a raw `<sup>`, `Str "2"`, and a raw `</sup>`; `<span href="…" rel="…">` is a `Span` whose `href` is an ordinary attribute, which the HTML writer then passes through where XHTML forbids it. Measured. `markdown-html.lua` reassembles the tags and reads each element with the HTML reader.

**The reader's time grows steeply with how deeply bracketed spans nest.** `[[[x]{.a}]{.a}]{.a}`, nested: 9 ms at depth 4, 144 ms at 8, 1.8 s at 12, and a real page never finished. That page was HTML holding a formula as MathJax 2 draws it (eleven spans deep, each with a style), which the Markdown writer wrote faithfully and the reader couldn't read back. Measured on 3.11. Candidate upstream report. Our side: `lib/mathjax.py` rebuilds a MathJax rendering as MathML before Pandoc reads the page, so the spans never reach the writer.

## The AsciiDoc reader

The reader is the `asciidoc` library (jgm/asciidoc-hs), not part of Pandoc's tree, so everything here is measured on 3.11 against a real Asciidoctor book (Computer Systems Security) rather than read from source.

**`include::` is followed**, each included file wrapped in a `Div` with class `included`. **But through a master file, an included chapter's `= Title` is lost**: it's neither a heading nor metadata. Read on its own, a chapter's title is its metadata and its `==` sections are level 1. So `convert.py` reads each included file as a source and takes the master only for its order and header.

**`:leveloffset:` is ignored**, **`:imagesdir:` is kept as metadata and not applied** to image paths, and the document's other attributes (`toc`, `icons`, `stylesheet`, `sectnums`) arrive as metadata too.

**A cross-reference by title isn't resolved.** `<<Unix File Permissions>>` and `<<Malware>>` are links whose fragment is the title itself; Asciidoctor resolves them to the section's id or the chapter. 54 in one book.

**`mailto:someone@example.org[Name]` loses its scheme**: a link to a file called `someone@example.org`. **A code span holding a URL scheme** (`` `ftp://` ``) becomes a link to `ftp://` around the code.

**A block's layout attributes become element attributes.** `[width=300, float=right]` on an image, a listing, or a table, and a diagram's `target=`, arrive as attributes of the block, and the HTML writer writes `width` and `target` as they are, on `<figure>`, `<pre>`, `<div>`, and `<table>`, where XHTML allows neither: epubcheck's RSC-005, 43 times in the security textbook's EPUB. Measured; `asciidoc-source.lua` moves a block's size to its image and drops the rest. Other names (`float`, `format`, `wrapper`, `link`, `align`) are written as `data-` attributes, which are valid.

## The AsciiDoc writer, against the AsciiDoc reader

Measured on 3.11 by writing each case with Pandoc's `asciidoc` writer and reading it back, for the AsciiDoc target. The writer is Pandoc's; the reader is `jgm/asciidoc-hs`, so its entries are candidates there. Asciidoctor's behavior is from its documentation, not run here. What the target does about each is in `docs/asciidoc.md`.

**The writer and the reader disagree.** Each of these is written by the writer and misread by the reader:

- A footnote after a word is joined to it (`notefootnote:[…]`), which the reader doesn't take for the macro.
- An empty span with an id (an anchor) is `[#id]##`, which reads back as a highlighted span holding `id]`.
- An image's alt is the macro's first value, unquoted: a comma splits it and an `=` makes it a named attribute. With no alt, the file name less its extension is written as the alt.
- A table with no header row is written with no `noheader`, and the reader takes row 1 for a header whenever `noheader` is absent (Asciidoctor wants a blank line after the row as well).
- A heading one level below the document title is `===`, skipping `==`; the reader then numbers it 1, and `====` 3.
- A figure caption with a line break is a block title over two lines; the second starts a paragraph, which takes the image macro in as inline text.
- Display math inside a description list is indented with the definition, delimiters and all, and an indented `++++` isn't a delimiter.
- Text that means something at the start of a line isn't escaped: a leading `.` (a block title; in a list item the whole file fails to read), `=`, `//`, `----`, `NOTE:`, `:name:`. Nor are Asciidoctor's replacements other than `->`: `'`, `--`, `...`, `(C)`, `(R)`, `(TM)`, `=>`, `<=`, `<-`.

**The writer drops:** a `Div` (its content stays), a raw HTML block, a footnote of several paragraphs (replaced by the words "[multiblock footnote omitted]"), a table's header column (it could write `cols="1h,…"`, which the reader doesn't read either), a row span, a table's groups, and the `subtitle` field. The standalone template writes `include-before` as plain blocks at the top.

**The reader:**

- Makes a description list of any line holding `::`, anywhere and with nothing after it: `std::cout`, `3::4`, an address with `::`. Asciidoctor wants a space or the line's end after it. `:{empty}:` prevents it in text; in an address nothing does, since `{empty}` isn't expanded there, and `link:++…++[]` is split too.
- Ends `latexmath:[…]` and `footnote:[…]` at the first `]`, escaped or not; `\]` makes a footnote unrecognized. `{startsb}` and `{endsb}` work in a footnote; `\lbrack` and `\rbrack` in math.
- Drops `latexmath:[…]` inside constrained italics (`_…_`), not inside `__…__` or bold.
- Applies Asciidoctor's replacements to text and to inline code, and splits inline code at its spaces into several `Code` elements. `` `+…+` `` keeps code literal but is still split.
- Reads `link:x.html[9.1 Null and]` with the text "9"; `{empty}9.1` or quoting keeps it.
- Expands `{empty}` before deciding a line is a comment, so `{empty}//` is still one; `++//++` isn't.
- Reads no inline passthrough (`pass:[…]`), though `++…++` works in text.
- Loses an open block (`--`) when a blank line comes before its closing delimiter after another delimited block inside it.
- Fails on a block anchor (`[[id]]` alone on a line) with no block after it.
- Puts a block image's id, alt, size, and `link` on a `Div` marked `wrapper="1"` around the figure, and an inline image's `alt=` and `link=` in its attributes rather than its caption and a `Link`.
- Honors no escaped quote in an attribute value, and doesn't take single quotes as quotes, so an alt with a double quote can't be written.
- Reads an attribute entry anywhere, header or body, as metadata; so a document can say something to a filter.
- Doesn't read `\root n \of`; neither does Pandoc's TeX reader, so a root with an index has no bracket-free form.
- Ends a constrained span (`#…#`) at a `#` inside it, a link's fragment included; the unconstrained `##…##` holds one. Reads `[.a.b]` as one class, `a b`. Reads an empty span, `[.x]####`, as text.
- Hangs, rather than failing, on a listing whose delimiter is never closed: a table cell whose listing holds a `|` breaks the cell there and leaves one. The process had to be killed.
- Strips a non-breaking space at the end of a text element as trailing space; `{nbsp}` stays.
- Reads a nested quotation written with a longer delimiter (`______` around `____`).

**The writer, again:** it writes a `Div`'s blocks with blank lines between them, so inside a list item every block after the first falls out of the item; it nests a quotation in a quotation by wrapping the inner in an open block, which the reader loses (the blank line before `--`); it writes nested spans with the same delimiter, which is ambiguous; and a span that starts a line is `[.role]#…#`, which the reader takes for a block attribute line.

**Open, not traced:** in a Markdown source, raw HTML holding a table whose cell has a `<pre>` listing with a line starting `  |` lost the listing on reading, from Markdown as a source and before any target. Seen once, in a test; the cause isn't established.

## The EPUB writer

**Chapter files are titled by file name**: the template's `<title>$pagetitle$</title>` is filled with `ch002.xhtml` by the writer's own variables (`Writers/EPUB.hs`), and `title-meta` is empty in a chapter. Read from the source and measured. Our assembler rewrites each `<title>` from the chapter's heading after the archive exists.

**Accessibility metadata is read from document metadata** (`accessModes`, `accessModeSufficient`, `accessibilityFeatures`, `accessibilityHazards`, `accessibilitySummary`) since 3.1.12; `--epub-metadata` drops `schema:` properties. Measured on 3.11.

**`--css` replaces `epub.css`** rather than adding to it. **Chapter splitting is by heading level only.** **The heading's id goes on the `<section>`**, not the heading. **Every image gets an `alt`**, so decorative and undescribed look alike. **Footnotes are `<aside epub:type="footnote">` with no number.** **A footnote number restarts per chapter file.** **The cover is an SVG `<image>` with no text alternative.** **The footnotes `<section>` has no heading.** All measured.

**Several JSON inputs concatenate; the last file's metadata wins.** Measured.

**An image the EPUB writer can't fetch is written with `../` before its source**, as if it were a path relative to the chapter's directory: `../https://example.invalid/badge.png`. Measured. An EPUB can't hold a remote image anyway, so `target-blocks.lua` turns one into a link before the writer sees it.

## The HTML writer

**Emits a bare `<th>` for a row-header column** (`row_head_columns`), never `<th scope="row">`; scope is the filter's to add. **`--include-in-header` replaces the `header-includes` metadata field** rather than merging. **`$title$` in a template renders inlines**, so a heading's `<em>` lands inside `<title>`. **Small lengths are written in scientific notation** (`5.0e-2in`). All measured.

**With no title, the page's `<title>` is the input file's name.** Rendering `costs.filtered.json`, a page without a title gets `<title>costs.filtered</title>`. Measured; `target-blocks.lua` sets `pagetitle` to the page's own name first.

## The Lua filter environment

**Within one filter table, every inline is walked before any block.** So a `Div`/`Span` handler pair that renames ids sees every span before every heading; a handler that must see elements in document order has to walk the blocks itself. Measured (`figures-and-tables.lua`, `make_ids_unique`).


**`AttributeList` is not a plain table**: `next()` on it errors; iterate with `pairs`. Measured. **A filter's table of attributes is iterated in hash order**, so build an `Attr` from a list of pairs for stable output. Measured. **Filters in a returned list run in order**, each over the whole document; a handler returning `{}` removes the element, `nil` leaves it. **`pandoc.read(text, 'html')`** reads MathML into `Math` and `<thead>` into head rows; **`pandoc.write(doc, 'html', {html_math_method = 'mathml'})`** writes math as MathML. Measured.

**A metadata value has no `.t` in Pandoc 3.** A `MetaBlocks` field arrives in a filter as a `Blocks` list and a `MetaInlines` one as `Inlines`, so `value.t == 'MetaBlocks'` is never true and code testing it silently does nothing; `pandoc.utils.type(value)` says `Blocks`, `Inlines`, `List`, `string`, or `boolean`. Measured, the hard way (`include-before` in the AsciiDoc target).

**Inline handlers run before block handlers, so a block handler sees what the inline ones made.** A `Table` handler that writes its table as HTML with `pandoc.write` loses every raw AsciiDoc inline the inline pass put in its cells, since the HTML writer drops raw content of another format. A filter file can return two filters that run in turn; the AsciiDoc target writes those tables in the first. Measured.

**A filter file that returns a table of filters ignores its global functions.** `target-blocks.lua` ends `return { {Div = …}, {Meta = …} }`, so a global `function Image` added to it never ran, and nothing said so. Measured, the hard way. A handler has to be in the returned table.

**A handler that returns `nil` keeps the element as it was, including changes made to it in place.** `html-source.lua`'s `Table` dropped empty columns from the table it was given and then returned `nil` when it had no headers to declare, and the columns came back. Return the element whenever it was changed.

## Upstream

Filed: #11869 (ScreenTip), which jgm agreed to on 2026-09-22 (above); next, ask whether he'd like a pull request or will make the change himself. Candidates, tracker not yet searched: the AsciiDoc writer's and reader's disagreements above, the writer's for Pandoc and the reader's for jgm/asciidoc-hs, of which the eager description list, `]` ending a macro whatever its escape, and a leading period failing a whole file are the ones worth filing first; the HTML reader's `tex_math_single_backslash` reading math inside `<code>`; the Markdown reader's time on nested bracketed spans; and, for jgm/asciidoc-hs rather than Pandoc, a chapter's title lost through `include::`, `:leveloffset:` and `:imagesdir:` not applied, cross-references by title unresolved, and `mailto:` dropped. Candidates, tracker searched, not filed: body-level bookmarks dropped (#6178 and #6781 unread, rate-limited); the orphan-anchor removal deleting cross-file targets (no search yet); the Markdown writer dropping spans without a warning; the EPUB chapter `<title>`.
