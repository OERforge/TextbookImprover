# Conversion settings

Settings that describe one rendering of the book, under `conversion:` in `packaging.yaml` and per target under `targets:`. Generated from `bin/schema-conversion.yaml` by `util/settings-reference.py`; edit the schema, not this page. A setting marked *target only* can appear only inside a target.

How the book is rendered into one output format.

**`format`**—one of `html`, `epub3`, `pdf`, `latex`, `docx`, `markdown`, `asciidoc`, `source`; default `html`; *target only*

What this target produces. markdown and asciidoc write source again: what the author decided, which the pipeline reads back to the same book. docx writes Word files from the same pages, in compatibility mode 15 with ScreenTips and Word's decorative marker. pdf writes one tagged PDF of the whole book through LaTeX, which needs LuaLaTeX (see the installation page). latex writes the LaTeX the pdf target builds from, as a master file that \include-s a file per chapter, with its images beside them, for an author to go on working in.

**`output_dir`**—`path`; default `""` (empty); *target only*

Where this target writes. Defaults to the target's own name, so two targets in the same format can't overwrite each other.

**`filename`**—`path`; default `""` (empty); *target only*

For a format that produces one file for the whole book, such as epub3, the file to write inside output_dir. Left empty it's worked out afresh on every run from the book's identifier and the format, so renaming the book renames the file. Given without an extension, the one matching the format is added.

**`menu`**—one of `on`, `off`; default `off`

Whether every page of an HTML target carries the book's contents as a menu at its top (collapsed, the current page marked) and links to the previous and next page at its foot. For posting the pages as a site of their own. Off by default, since an LMS gives the pages its own navigation and the EPUB has its reading system's. A page from the pass-through directory is left as it stands.

**`compatibility_mode`**—one of `keep`, `15`; default `keep`

For a target with format source: whether a remediated Word file keeps the compatibility mode its author's file has, or is set to 15, which guides for Word say its Accessibility Checker needs. Kept by default, since the file is the author's.

**`latex_definitions`**—one of `on`, `off`; default `on`

For a target with format source on a LaTeX book: whether the copy gets the definitions in the book's latex.macros file (latex-conversion-macros.tex), written after its preamble as the conversion reads them, so they replace the book's own there too. A person writes that file to say what the book's macros mean, a bar drawn with \rule as \mid, say, which is what a reader of the PDF needs as much as one of the pages. On by default; off keeps them to the conversion, for a file that only helps Pandoc read the book.

**`tagging`**—one of `off`, `on`; default `off`

For a target with format source on a LaTeX book: whether the copy is made to build with LaTeX's own tagging, for an accessible PDF: \DocumentMetadata before \documentclass, pdfTeX-only options and settings taken out, the constructs tagging can't take yet put the way it can, each figure's and table's tags where the text has it, and unicode-math for the formulas' MathML (latex_mathml). A tagged book is built with LuaLaTeX (pdfLaTeX runs out of memory on a book), so this changes the author's build. Off by default; the alt text is written either way.

**`latex_mathml`**—one of `on`, `off`; default `on`

For a target with format source and tagging on, on a LaTeX book: whether the copy loads unicode-math, so each formula carries its MathML, which LaTeX makes only from an OpenType math font. Its Latin Modern fonts are TeX's own design, but their metrics differ a little, so pages can break differently: the calculus notes take 84 pages instead of 85, while GIAM keeps its 434. Off keeps the book's fonts, and its formulas get no MathML. A book that sets its fonts with a package of its own (mathptmx, fontspec) keeps them either way.

**`title_page`**—one of `auto`, `on`, `off`; default `auto`

For a target with format epub3 or pdf: whether the book opens with a title page, its title and authors. auto goes by the book's structure, not its number of files: a title page when the book has more than one top-level entry (chapters, parts), or is one page with more than one top-level heading, or has something before its title heading (a byline, a subtitle); none for a document whose one top-level heading is its title, which then appears once, as that heading, and in the file's metadata.

**`bookmarks`**—one of `linked`, `all`; default `linked`

For a target with format docx: which of Pandoc's bookmarks a Word file keeps. Pandoc's writer bookmarks every heading and section, and NVDA announces "bookmark" at each one, hidden or not. linked keeps those a link somewhere in the book goes to, the table header bookmarks JAWS reads, and the bookmarks that carry a code block's language; all keeps every one.

**`title_block`**—one of `on`, `off`; default `on`

Whether a page's own subtitle, date, abstract, and include-before render on it for this target. A source's opening page carries the document's, which makes it a title page; off leaves the author to lay the front matter out by hand.

**`numbering`**—one of `project`, `on`, `off`; default `project`

Whether this target shows the book's structure numbered (see project.numbering). project follows the book; on and off decide for this target alone, so an EPUB can carry chapter numbers while a web edition doesn't, or the reverse. The cartridge follows the book's setting.

**`header`**—`text`; default `""` (empty)

Markdown placed at the top of every page, or the path to a file holding it. Inserted by the template after the filters have run, so nothing in it's processed: give any image explicit alt text.

**`footer`**—`text`; default `""` (empty)

Markdown placed at the bottom of every page, or the path to a file holding it. The usual use is an attribution line. Same caveat as header: it isn't processed by the filters.

**`promote_h1_to_title`**—one of `always`, `if-absent`, `longer`, `shorter`, `never`; default `if-absent`

Which title a page has when it declares one and its only H1 says something else. A declared title is Markdown's title or title-meta, HTML's <title>, or a Word paragraph styled Title, which Pandoc's reader takes out of the body as the title. if-absent keeps the declared title, and the H1 stays a heading of its own; the H1 is the title only when none is declared, or when it says the same. always makes the H1 the title, as for the OpenStax books, whose Title paragraph repeats the H1 without its section number; longer does only when the H1 contains the declared title; shorter takes the H1 when the declared title contains it and more, which cleans up a page saved from the web whose <title> adds the site's name; never keeps the declared title and every H1 a heading. An H1 that says the declared title, the same or one inside the other, is the page's title heading whichever text is the title. A format source copy keeps the author's own title whatever this says: the source writers never write a page's title. Whichever H1 is the title, every output shows it as the page's own H1 (the HTML's, the Word file's Heading 1, the EPUB's and PDF's chapter heading), never twice.

**`author_byline`**—one of `meta`, `visible`, `drop`; default `meta`

What to do with author metadata from the source. Reading .docx this comes from a paragraph styled Author, which Pandoc consumes out of the body the same way it consumes a Title-styled one. meta keeps it in the page head and suppresses the visible byline Pandoc's template would otherwise print under every title; visible keeps both; drop removes it.

## math

Math the source wrote in the wrong characters, or as text. Every change is a row in reports.math_repaired.

**`math.repair_equations`**—`bool`; default `true`

Give each equation the characters it means: mu for the micro sign, Delta for the increment sign, a minus for an en dash, a bar for an en dash or macron set over a letter, y with a hat for the one-character y-hat, and 0 for the slashed O of H sub 0. Word's equation editor lets an author type a character that looks right and means something else; a screen reader reads the one that's there, and a PDF's math fonts have no glyph for some of them.

**`math.from_text`**—`bool`; default `true`

Make an equation of math typed as ordinary text: a relation (=, <, >, and the rest) between operands, with at least one variable, an italic letter or a Greek one (mu = 34, P(x < 160) = 0.3); and a Greek letter, or an italic letter with a sub- or superscript, standing alone (mu, H sub 0). A plain letter is a word, and a lone italic letter is left alone, since outside math it's mostly emphasis. Conservative on purpose: text becomes math only when it's clearly math.

## images

How images extracted from the source are handled.

**`images.spacer_below`**—`float`; default `0`

Width in inches below which an image is treated as a layout spacer rather than content. 0 disables the rule and reports candidates instead.

**`images.strip_spacer`**—`bool`; default `false`

Remove spacer images rather than hiding them from assistive technology.

**`images.alt_max_chars`**—`int`; default `120`

Alt text longer than this is reported so it can be shortened, with the detail moved into the surrounding prose where every reader benefits from it.

**`images.responsive`**—`bool`; default `true`

Let images shrink on narrow viewports rather than reproducing the source's fixed dimensions (WCAG 1.4.10).

## tables

How data tables are rendered.

**`tables.bands`**—one of `auto`, `split`, `group`, `column`; default `auto`

What a table whose rows are grouped under bands becomes: a merged row across the table labeling the rows beneath it, as in a Word table, or a tbody headed by one in HTML. split makes one table per band, the band's text in each part's caption, which NVDA reads on arrival (tested in Chrome and Firefox). Of HTML's grouped forms, NVDA names a group for a data cell only when its heading is a column of its own spanning its rows, and then only moving down a column; a band as a row of its own it never names there. group keeps one table with a body per band, each band a row-group header, which is the author's form and reads back as it was written. auto derives from the target's format: split for html, epub3, and pdf; group for markdown, asciidoc, and docx, whose output becomes a source. column, never the default, keeps one table and gives the bands a column of their own at its left, each a row-group header spanning its rows: the form NVDA names with the row header on every data cell moving down (W3C's pattern for irregular headers), for trying in HTML. Only a table whose parts share their column headers takes it; any other is split. In testing NVDA announced the column header inconsistently in this form, and no other screen reader has been tried.

**`tables.wrap`**—`bool`; default `true`

Put wide tables in a focusable scroll container so a long table doesn't force the whole page to scroll sideways (WCAG 1.4.10).

**`tables.markers`**—`opaque`; default `{matrix: both, row-headers: first-column}`

What a fenced div around a table in a Markdown source declares about its headers, class by class: "::: matrix" means both a header row and a header column, "::: row-headers" a header column and no header row, unless this says otherwise. The values are the ones table-headers.csv takes (first-row, first-column, both, none); a header row alone and no headers need no marker, since a pipe or grid table says those itself. An open block in an AsciiDoc source ([.matrix] then --) declares the same way. A Markdown or AsciiDoc target writes these markers back. A Markdown table with no marker is left as Pandoc read it; the guess and the report run only on Word sources.

## pages

What a page is, when the source's files are not already the pages you want.

**`pages.split_level`**—`int`; default `0`

Cut every source into one page per heading of this level or shallower, after the filter has run and before anything is rendered. 0 leaves each file as one page. A book that arrived as one file per chapter gets one page per section with 2, and the packager groups the pieces under their source without being told. Each piece is named after its heading unless the page_names sidecar says otherwise, its heading becomes its title, and links between pieces are rewritten to follow.

## links

What happens to links on the way through.

**`links.rewrite_publisher`**—`bool`; default `true`

A link to a page of this book on the publisher's site -- https://openstax.org/books/<book>/pages/<page>#anchor, the shape OpenStax's export uses for its index and its cross-references -- becomes a link to the page here, anchor and all, when the book has that page. A link to a page the book doesn't have is left as it is.

**`merge`**—one of `False`, `groups`; default `false`

For a markdown, asciidoc, or docx target: off writes one file per page, as the rest of the run sees pages. groups writes one file per top-level entry of the book's contents, with each page under it as a section, so a book whose sources are one file per section comes back as one file per chapter. Links between merged pages become links inside the file, and links to a page in another file name that file.

## notes

Where footnotes go and how they count, once a source has been cut into pages. Pandoc numbers them per page and keeps each page's at its end; these settings rearrange that in the rendered pages and in the EPUB alike.

**`notes.numbering`**—one of `page`, `group`; default `page`

page restarts the numbers on every page. group continues them across the pages of the enclosing group, in reading order, whatever a group is called; a page that was not split is a group of one.

**`notes.placement`**—one of `page`, `group`, `book`; default `page`

page keeps each page's notes at its end. group gathers a group's notes at the end of its last page. book gathers every note on one Notes page at the end, with a heading for each group, numbered per group. A reference always links to its note wherever it went, and the note links back.

## epub

Settings read only by an epub3 target. One EPUB holds the whole book: every page in project.contents, in that order, with each group a heading over its pages and the table of contents built from the same tree the cartridge organization uses.

**`epub.toc_depth`**—`int`; default `2`

How many levels the table of contents shows. A group at the top of project.contents is level 1, a page inside it level 2, and a page's own headings continue below its entry, so 2 shows the groups and their pages, whatever a group is called. The depth is a rank in the book, not a fact about the file a heading came from, so a book assembled from files split at different depths still reads evenly.

**`epub.cover_image`**—`path`; default `""` (empty)

An image for the cover page, JPEG or PNG, as an absolute path or one relative to the content directory. Left empty the book has no cover page. A path that doesn't exist stops the build.

**`epub.cover_alt`**—`string`; default `""` (empty)

What a screen reader says for the cover image. Left empty it is "Cover of" followed by the book's title, which is what a cover usually is; give the text when the picture says more.

**`epub.accessibility_summary`**—`text`; default `""` (empty)

The sentence or two a reading system shows a reader about the book's accessibility, alongside the claims the run computes for itself (see the docs). Left empty it's derived from what this run found: how many images lack alternative text, whether equations are MathML, and so on, so it stays true as the sidecars are filled in.

## pdf

Settings read only by a pdf target. One PDF holds the whole book, assembled from the pages the way the EPUB is, and written by Pandoc's LaTeX writer and LuaLaTeX with LaTeX's tagging on, so the file carries its structure, its images' alternative text, its tables' header cells, and its equations as MathML. A LaTeX book's PDF is built from the book's own LaTeX instead, unless from says pages.

**`pdf.from`**—one of `book`, `pages`; default `book`

What a LaTeX book's PDF is built from. book builds the book's own LaTeX with latexmk and LuaLaTeX, from a copy of its folder with the book's files as a source target with tagging on writes them (alt text, header declarations, the definitions file, MathML), the census's header guesses declared too, as the pages have them: the author's pages, index, and bibliography, as their LaTeX makes them. It needs latexmk, and a book that builds with LaTeX's tagging; the PDF claims PDF/UA-2, and the settings below that shape Pandoc's LaTeX (metadata, figures, repair_captions, remove_empty_paragraphs, ua1_math, toc_depth) don't apply. pages builds from the converted pages through Pandoc's LaTeX writer, as for any other source. A book from any other source is built from its pages either way.

**`pdf.standard`**—`list`; default `[ua-2]`

The standards the PDF declares, as Pandoc's pdfstandard variable takes them: ua-2 for PDF/UA-2 (PDF 2.0), or ua-1 for PDF/UA-1 (PDF 1.7), which is what PAC checks, and optionally a PDF/A part such as a-4f with ua-2 or a-2u with ua-1. PDF/UA turns LaTeX's tagging on. A standard declared here is a claim the file makes about itself; veraPDF, when the output check finds it, is what tests the claim.

**`pdf.metadata`**—`path`; default `""` (empty)

A YAML file, or a Markdown file that opens with a YAML block, whose metadata goes to Pandoc's LaTeX writer: documentclass, classoption, header-includes, include-before, fonts, geometry, and the rest of Pandoc's LaTeX variables. A book written for a Pandoc PDF build names the file that held its YAML (a _preamble.md, say), and its settings carry over. What it sets wins over what project.yaml says; what it leaves out comes from project.yaml and from these settings. A path that doesn't exist stops the build.

**`pdf.figures`**—one of `in_place`, `section`, `float`; default `in_place`

Where a figure goes, on the page and in the order a screen reader reads. in_place keeps it where the text has it, on both, as the float package's H placement does. section lets it float within its section, flushed before the next one starts (placeins), and puts its tags after the section's text. float is LaTeX's own placement, wherever a figure fits, and LaTeX's tagging then gathers every figure's tags at the end of the document, where a screen reader reaches them after everything else: in the statistics textbook, 246 of its 270 figures. section needs the placeins package installed.

**`pdf.repair_captions`**—`bool`; default `true`

Retag each table's caption, which LaTeX's tagging code writes as a first row of one header cell spanning the table, as the table's Caption, and take out the empty copy of the table's head it leaves inside the table, so a screen reader reads the caption as one and counts the table's rows and columns right. Only a table the book gave a caption, matched in order. Needs pikepdf; without it the run says so and leaves the tags as LaTeX wrote them.

**`pdf.ua1_math`**—one of `alt`, `office`; default `alt`

How a PDF/UA-1 file carries its math. PDF 1.7, which PDF/UA-1 is built on, has no standard way to tag MathML, so alt gives each formula its TeX source as alternative text and attaches its MathML as a file, as LaTeX does by itself for PDF/UA-1; a screen reader reads the TeX as written. office also writes the MathML as Microsoft Office's own attribute on each formula, the one Word puts in the PDFs it saves, which some readers use. PDF/UA-2 tags the MathML itself, and neither applies there.

**`pdf.remove_empty_paragraphs`**—`bool`; default `true`

Remove the paragraph structure elements LaTeX's tagging code leaves empty: around a longtable's caption, in a header cell whose text wraps, in the repeated head, and around an image scaled to fit. NVDA reads a file the same with them and without, but PDF4WCAG's WCAG 2.2 Machine profile reports each one. Each orphaned piece of content becomes an artifact; the page's text is unchanged. Needs pikepdf; without it the run says so.

**`pdf.toc_depth`**—`int`; default `2`

How many levels the printed table of contents shows, counted as the EPUB's are: a group at the top of project.contents is level 1. The bookmarks a PDF viewer shows follow the same depth. The metadata file's toc-depth, when it sets one, wins.

## captions

How table and figure labels are recognized in the source.

**`captions.table_prefixes`**—`list`; default `[Table]`

Words that begin a table label. Books that say Exhibit rather than Table need this.

**`captions.figure_prefixes`**—`list`; default `[Figure]`

Words that begin a figure label.

## media

How media extracted from the source is handled.

**`media.strict`**—`bool`; default `false`

Abort as soon as an image can't be identified, rather than collecting every such image and stopping once at the gate.

## word

Repairs to a Word source that change what reading it means, decided once for the book and applied both to the copy the conversion reads and, with a source target, to the author's remediated copy, so the book and the file agree. They're what util/restyle-headings.py and util/untrack-deletions.py do by hand.

*Book level:* set these under `defaults:`, never in a target, since the whole book shares them; in a target they stop the run.

**`word.tracked_deletions`**—one of `accept`, `strike`; default `accept`

What becomes of text deleted with Word's tracked changes. accept drops it, as Word's Accept All Changes and Pandoc do, and the run names each file that has any, since a before-and-after example loses its "before". strike keeps it as ordinary struck-through text, which reaches HTML as <del>.

**`word.headings`**—`string`; default `keep`

Which paragraph styles are headings, for a book whose top level is styled Title, or otherwise not Heading 1 to 9, which is all Pandoc reads as headings. keep leaves the styles as they are; from-toc takes the levels each file's own table-of-contents field declares; or a map of style ids, FROM=TO,..., applied all at once (Title=Heading1,Heading1=Heading2). A file the setting can't apply to, with no TOC field, or not defining a style the map needs, is left as it is and named.

## latex

A LaTeX book, read through its master file: the one in the book's directory with \documentclass and \begin{document}, which \include-s the chapters, each a page.

*Book level:* set these under `defaults:`, never in a target, since the whole book shares them; in a target they stop the run.

**`latex.main`**—`string`; default `""` (empty)

The master file, when more than one file in the book's directory is a whole document, as when one set of chapters makes a textbook, a workbook, and a solutions manual (GIAM.tex). Blank takes the only one, and stops the run when there are several.

**`latex.macros`**—`string`; default `latex-conversion-macros.tex`

A file of LaTeX definitions read after the book's own preamble, so they win over the book's: for a macro that draws what it means, where only a person can say what that is: \renewcommand{\suchthat}{\mid} for a bar drawn with \rule. Read when it's there. The book's own files are never changed; a source target writes the definitions into its copy unless its latex_definitions is off.

## sidecars

CSV files holding decisions a person made about the source. These describe the book rather than one rendering, so a target should rarely override them. These files are read, never written, and hold work no script can reproduce. A bare name resolves against the content directory, which is convenient but leaves them among the generated HTML, the extracted media, and the disposable reports: the directory you would delete to rebuild, and the one replaced wholesale when the publisher reissues the source. An absolute path, or one relative to the content directory such as "../corrections/ibs2e/table-captions.csv", keeps them somewhere you can put under version control. A path set here that doesn't exist stops the run, because the alternative is converting the whole book while silently discarding every correction in it.

*Book level:* set these under `defaults:`, never in a target, since the whole book shares them; in a target they stop the run.

**`sidecars.table_captions`**—`path`; default `table-captions.csv`

Descriptive captions, keyed on the table's label. A bare label is a valid caption but describes nothing, and no script can invent the description.

**`sidecars.image_alt`**—`path`; default `image-alt.csv`

Alt text, keyed on the image path with the extension ignored. Use [decorative] for an image that carries no meaning.

**`sidecars.bare_links`**—`path`; default `bare-links.csv`

What to do with each bare link, one whose text is its own address, keyed on the address: a Replacement that is a URL (http, https, or ftp) replaces the address and the text; any other Replacement replaces only the text; a blank one keeps the link bare. A Title sets the link's title (a tooltip in HTML); a blank one keeps the source's. See docs/bare-links.md.

**`sidecars.math_keep`**—`path`; default `math-keep.csv`

Math the math settings would change, kept as it was: rows copied from the math_repaired report (Kind, Page, Before; the After column is ignored), each keeping that equation unrepaired or that text as text. A blank Page keeps it on every page. A row that keeps nothing, since the source changed, is warned about.

**`sidecars.table_headers`**—`path`; default `table-headers.csv`

Where each table's headers are, keyed on a hash of the table's content: first-row, first-column, both, or none. A first run writes prefilled rows to the table_headers_new report; rename or paste them here. Values this version doesn't act on yet (manual, list) are accepted and kept. A row whose key matches no table, since the table changed or is gone, is warned about and written to table-headers-unmatched.csv, with the sidecar without it as table-headers-sample.csv, to adopt.

**`sidecars.page_names`**—`path`; default `page-names.csv`

Names for the pages split_level cuts, keyed on the source and the heading text: source, heading, name. Only needed when the name derived from the heading is not the one you want. A row whose source and heading match nothing is reported, since it means a heading was edited or the row was mistyped.

## reports

Where the run records what still needs human attention. Removing a report when nothing is outstanding is deliberate: the file existing at all is the signal that there's work to do.

*Book level:* set these under `defaults:`, never in a target, since the whole book shares them; in a target they stop the run.

**`reports.table_captions_missing`**—`path`; default `table-captions-missing.csv`

Tables whose caption is a bare label with no description.

**`reports.image_alt_missing`**—`path`; default `image-alt-missing.csv`

Images with no alt text, or with alt text over the length limit.

**`reports.fidelity`**—`path`; default `fidelity.csv`

What a target's files can't carry, one row per page and kind of loss: for a docx target, a list inside a quotation, a figure with no caption, a layout table, a table's per-cell headers, and a code block's language when its name can't go in a bookmark; for markdown and asciidoc targets, what the writing changes, as each run also says on the terminal (an example list, a footnote of several paragraphs in AsciiDoc). Nothing to fix in the book; it says what reading the files back won't restore.

**`reports.bare_links_new`**—`path`; default `bare-links-new.csv`

Bare links with no row in the bare-links sidecar, one row per address, with the pages it's on and the text before it; paste the rows into the sidecar.

**`reports.table_headers_new`**—`path`; default `table-headers-new.csv`

Prefilled sidecar rows for every data table the table_headers sidecar has no row for, in the sidecar's own format. Written when there are any and removed when there are none, so the file existing is the signal that there are rows to paste in.

**`reports.table_headers_report`**—`path`; default `table-headers-report.csv`

What happened to every data table this run: what the sidecar declared, what the guess said and why, and a status of declared, new, blank, manual, needs-source, or unmatched.

**`reports.page_names_new`**—`path`; default `page-names-new.csv`

Prefilled page_names rows for every page split_level cut that the sidecar has no row for, with the derived name filled in. Written when there are any and removed when there are none.

**`reports.page_names_report`**—`path`; default `page-names-report.csv`

Every page split_level wrote this run: its source, the heading it was cut at, its name, and which part of how many it is.

**`reports.output_check`**—`path`; default `output-check.csv`

What the output check found wrong with the pages and any EPUB this run wrote: links and fragments that resolve to nothing, images with no alt attribute, headings that skip a level, duplicate ids, tables with neither header cells nor a caption, pages with no language or title. Written when there are any findings and removed when there are none. The run isn't stopped by them; they're a list to work through.

**`reports.media_unresolved`**—`path`; default `media-unresolved.csv`

Media that could not be identified. EMF and WMF are the usual cause and have to go back to the author.

**`reports.spacer_images`**—`path`; default `spacer-images.csv`

Spacer images found, and what was done with each.

**`reports.math_repaired`**—`path`; default `math-repaired.csv`

Each change the math settings made: an equation's characters repaired, or text made an equation, with the page and the text before and after.
