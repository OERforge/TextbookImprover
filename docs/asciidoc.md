# AsciiDoc sources

An `.adoc` file beside the sources is a page of the book, read with Pandoc's AsciiDoc reader into the same intermediate a `.docx` gets. Three things are done on reading that Asciidoctor would have done and the reader (Pandoc 3.11's, which is the `asciidoc` library's) doesn't:

- **`imagesdir` is applied.** `image::hats.png[]` under `:imagesdir: images` names `images/hats.png`. A chapter that sets none takes its master file's.
- **A chapter's `=` line is its title** and its `==` sections become `h2`, so a page has one `h1`. Asciidoctor's own settings (`:toc:`, `:icons:`, `:stylesheet:`, `:sectnums:`) are dropped from the metadata, where Pandoc's template would read `toc` as a switch.
- **Cross-references land.** `<<Unix File Permissions>>` names a section by its title and `<<Malware>>` a chapter by its title; Asciidoctor resolves both, the reader leaves the title as the fragment. After reading, each goes to the heading, or the page, that holds it, on whichever chapter that is, when exactly one does. On the security textbook this resolved 22 references, plus the references to whole chapters.
- **Links are repaired.** `mailto:someone@example.org[Name]` gets back the `mailto:` the reader drops, and a code span holding a URL scheme (`` `ftp://` ``), which the reader wraps in a link, is just code again.

## A master file

- **A block's layout attributes are made valid.** Pandoc's reader passes `[width=300, float=right]` and a diagram's `target=` onto the block, and its HTML writer then puts `width` and `target` on `<figure>`, `<pre>`, `<div>`, and `<table>`, where neither HTML nor XHTML allows them (an EPUB with them fails epubcheck). A block's width and height go to the image it holds, as attributes when they're whole numbers and as a style otherwise; on a block with no image they go, and so does `target`. `float` and the others arrive as `data-` attributes, which are valid, and stay.

A book is usually one file that `include::`s its chapters. Read through that file, the reader loses each chapter's `=` title (it is neither a heading nor the document's metadata there) and ignores `:leveloffset:`. So a file that includes others isn't read: it's the book's order, each file it includes is a source in its own right, and the run says so. With no `contents` declared, the run writes `contents-sample.yaml` in the shape `project.yaml` takes: the order the master includes its chapters in, and what its header says about the book (its `=` title, the author line beneath it, and `:lang:`). Nothing else carries those, since the master isn't read as a page, so without them the book's EPUB is called "Untitled". Copy the sample into `project.yaml`. Anything else the master holds besides its includes, such as a cover shown only to HTML (`ifdef::backend-html5[]`), isn't part of the book.

## Measured against the book's EPUB

The security textbook is published as an Asciidoctor EPUB and its source is public. The two routes give the same 14 chapters and the same text. What they disagree about is instructive: the EPUB's images have alt text and the source's don't. 49 of the EPUB's 51 alt texts are the image's file name ("db locked" for `db-locked.png`), which is what Asciidoctor writes when the author gave none. The output check now reports that (`image-alt-is-file-name`), so both routes say the same thing: 22 figures need describing.

## AsciiDoc as a target

A target with `format: asciidoc` writes the book as AsciiDoc to be read again as a source, the way a `markdown` target writes Markdown: what the author decided, and nothing the filter derived from it. It writes one `.adoc` per page, or with `merge: groups` one per top-level group of the book's contents. Its media keep the author's names, and a banded table stays one table (`tables.bands: group`). It's written in modern AsciiDoc as Asciidoctor reads it, and read back through Pandoc's reader, which is what the round trip is measured with: converting the written files gives the same pages as converting the book, and writing them again gives the same files.

Pandoc's AsciiDoc writer and reader disagree with each other in many places, and with Asciidoctor in some, so much of what the target writes it writes itself. Each form below reads back to what was written, in Pandoc's reader and in Asciidoctor:

- A table's header column is declared the way a Markdown target declares it: an open block whose role names the marker (`[.matrix]`, `[.row-headers]`). A table with no header row says `options="noheader"`, since Pandoc's reader otherwise takes the first row as one.
- A table with a row span, grouped into bodies (a banded table), carrying a role (a layout table), or with a cell holding more than paragraphs (a listing, a list) or code containing `|`, is written as HTML in a passthrough block, as are raw HTML, a frame, and a `<details>` answer. Pandoc's reader drops row spans and flattens groups, AsciiDoc has no table role, and a `|` ends a cell even inside a listing.
- A span is written `[.role]##…##`, which a `#` inside it (a link's fragment) can't end. A quotation's delimiter is longer than any inside it, which is how AsciiDoc nests one quotation in another. A `div` is unwrapped, as the writer would, but with its blocks kept inside a list item, and its id as an anchor.
- A non-breaking space at the end of a stretch of text is `{nbsp}`, which the reader doesn't strip.
- An image is written with a named alt (`alt="…"`), which keeps commas and `=`, or `role=decorative`, or no alt at all when it has none: Pandoc's writer puts the file name there. A linked image carries its `link`. A figure is its id, its caption on one line, and the image.
- A link with a title is `link:…["its text",title="its title"]`, which reads back with both; Pandoc's writer drops every link's title. The text is quoted so a comma doesn't split it.
- An anchor is `[[id]]`. A footnote after a word has `{empty}` before it, and a bracket inside one is `{startsb}` or `{endsb}`.
- Text AsciiDoc would read as markup keeps its characters: a leading `.`, `=`, `//`, `NOTE:`, or `:name:`; a `::` anywhere (Pandoc's reader makes a description list of any line holding one, `std::cout` included); Asciidoctor's replacements, so an apostrophe stays straight, `--` stays two hyphens, and a choice labeled "(C)" isn't a copyright sign; a URL in plain text, which would become a link; link text that starts with a number and a period.
- Inline code is literal (`` `+code+` ``), and math in italics uses `__…__`. In inline math, brackets are `\lbrack` and `\rbrack`, and in a table cell a bar is `\vert`.
- Headings sit one level below a page's title, as AsciiDoc numbers them. A page whose headings start elsewhere, at the title's own level or a level lower than expected, says by how much (`:heading-offset: -1`), and reading puts them back; AsciiDoc can't skip a level under a title, and Pandoc's reader renumbers a first heading that does. A page's subtitle is an attribute entry, and the blocks the pipeline shows before and after its content (`include-before`, `include-after`) are open blocks of those names.

Some things have no form that reads back, and the target changes them and says so on the terminal:

- An address containing `::` (MDN's `::after` page, for instance) is written with the colons percent-encoded (`%3A%3A`), which a web server reads as the same address.
- An alt text containing double quotes is written with typographic ones.
- A footnote of several paragraphs becomes one, and a list or a quotation inside one keeps its words and loses its structure: an AsciiDoc footnote is one paragraph.
- Display math inside a definition list is written inline: Pandoc's writer indents the math block's delimiters there, which breaks the list.
- A root with an index (`\sqrt[3]{x}`) is written as Asciidoctor reads it, and Pandoc's reader cuts the formula short.
- A span inside another span is merged into it, the outer taking the inner's classes, since both would be written `##…##`. Only layout spans nest this way in practice (Scribble's margin notes); the text stays.
- A list with no items at all is dropped.

One disagreement isn't handled: a list item holding other lists and continued paragraphs can come back with one of its lists at a different depth. On the statistics book that's one list of 169 pages.

Measured by converting each book to HTML and to AsciiDoc, converting the AsciiDoc, and comparing the two HTML runs with `compare-output.py`: the security textbook gives 14 of 14 pages identical, *Introductory Business Statistics* (from Word) 166 of 169, the economics textbook (from Markdown) 31 of 34, and DCIC (from HTML) 74 of 80, the differences being the cases above.
