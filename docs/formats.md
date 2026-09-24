# What goes in, what comes out

Every source format the pipeline reads, the ways a book in that format can arrive, what each can be turned into, how far each path has been tested, and how the output is packaged. The details live on each format's own page, linked from here.

## How the paths are rated

- **TESTED**: the test suite covers the path, and real books have gone through it and been checked: the [output check](checking.md) on every run, epubcheck for an EPUB, and `util/compare-output.py` for a round trip.
- **NEEDS MORE TESTING**: covered by the suite or by one book, or a real book showed a problem that isn't fixed yet.
- **NOT TESTED**: the code allows it, but neither a test nor a real book has taken the path.
- **Not available**: nothing produces that output yet.

## At a glance

| Input | HTML | EPUB | Markdown | Round trip to itself |
|---|---|---|---|---|
| Word (`.docx`) | TESTED | TESTED | TESTED | Not available (no Word output) |
| Markdown (`.md`) | TESTED | TESTED | TESTED | TESTED |
| HTML (`.html`) | TESTED | TESTED | NEEDS MORE TESTING | TESTED |
| AsciiDoc (`.adoc`) | TESTED | NEEDS MORE TESTING | NOT TESTED | Not available (no AsciiDoc output) |

PDF and Word output aren't built yet ([roadmap item 2](../ROADMAP.md)). A target declaring `format: pdf` or `format: docx` is accepted and, for now, produces nothing without saying so. PDF is read only by [the audit](auditing.md), which reports on a Word, Markdown, HTML, EPUB, or PDF file without converting it.

## Word

**How it can arrive**

- Files in the book's directory: one `.docx` per chapter or section, or one for the whole book, which [the split](splitting.md) cuts into pages.
- A plain `.zip` of them, such as a publisher's DOCX download, which `convert.py` extracts when it finds the zip alone in a directory ([A book that arrives as an archive](first-run.md#a-book-that-arrives-as-an-archive)).
- Inside a [Common Cartridge](cartridge-input.md): a Word file the course outline names is a source, and with `--linked-documents` so is one a page only links to.

**What it becomes**

- **HTML: TESTED.** The census has read all nine books of the test corpus (1,782 files); the statistics, nursing, marketing, business communication, and programming books have been converted, and cartridges this pipeline builds have been imported into Brightspace. Lost on the way: a hyperlink's ScreenTip, which Pandoc's reader discards ([#11869](https://github.com/jgm/pandoc/issues/11869), agreed upstream), and the document's properties, since the title and author come from paragraphs styled Title and Author. Bookmarks Pandoc's reader would drop are repaired before it reads the file, and table headers come from Word's marks, the [sidecar](sidecars.md), or the guess.
- **EPUB: TESTED**, on the same books and the suite's fixtures. It loses what [every EPUB loses](#epub), as well.
- **Markdown: TESTED**, on the statistics book (merged by chapter) and the suite's round trip: read back, it gives the same HTML, and written again it's the same file. The first write normalizes Word's residue (paragraphs holding only a non-breaking space, stray spaces), so the second write is the fixed point. A table with merged cells, and a figure with an id, are written as fenced HTML, since Pandoc's Markdown can't express them; a banded table is kept as one table.
- **Word: Not available.** Word output is roadmap item 2.

## Markdown

**How it can arrive**

- Files in the book's directory, with images wherever they name them ([Markdown sources](markdown.md)), including a book set up for a Pandoc PDF build.
- A plain `.zip` of them.
- A Jekyll site's source (just-the-docs), through [`unpack-jekyll.py`](site-input.md#a-sites-own-source), which writes a book directory of Markdown.
- A Markdown target's output from an earlier conversion, which is written to be a source.

**What it becomes**

- **HTML: TESTED**, on the economics book, the 33-chapter Markdown textbook, and the suite. HTML written into the Markdown is read as HTML and cleaned the way an HTML source is.
- **EPUB: TESTED.** The economics book's 34 pages build an EPUB epubcheck passes without an error or a warning.
- **Markdown (round trip): TESTED**, by the suite and on the economics book: the second write equals the third.

## HTML

**How it can arrive**

- Files in the book's directory: every `.html` beside the sources is a source ([HTML sources](html.md)), and a finished page that shouldn't be converted goes in `_pt/`, copied as it is.
- A plain `.zip` of them.
- A website saved from a browser, or saved as `.mhtml`, through [`unpack-site.py`](site-input.md). Tested on CS168 and DCIC. A browser's `.mhtml` save holds only MathJax's rendering of a formula, not its TeX, so formulas can't become math.
- A WARC or WACZ, which `convert.py` unpacks when it finds one alone in a directory ([Making a WARC](making-warcs.md)). Tested on DCIC, CS168, and the OER Commons business communication book.
- An EPUB, through [`unpack-epub.py`](epub-input.md), whose content documents become pages. Tested on three publishers' EPUBs: Pressbooks, OER Commons, and Asciidoctor's.
- A Common Cartridge exported from an LMS or a publisher, which `convert.py` unpacks when it finds one alone ([A course cartridge as the source](cartridge-input.md)). Tested on a Brightspace export and OpenStax's Canvas cartridge. Discussions, assignments, web links, test banks, and tool links are reported, not converted.

Whatever the route, scripts don't run, so a page a script draws in the browser has nothing to read; only what's inside a page's `<main>` is read when it has one; tags Pandoc has no element for (`<footer>`, `<nav>`, `<cite>`) go, their contents kept; and a paragraph's class is lost. The full list is in [HTML sources](html.md).

**What it becomes**

- **HTML (round trip): TESTED.** Converting this pipeline's own pages changes nothing, which the suite checks. Real books: DCIC (80 pages), CS168 (a browser save, a WARC, and the site's own source agree on 62 pages), *Information Systems for Business and Beyond*, the business communication book, and both cartridges, including one this pipeline built, which converts back to the book it came from.
- **EPUB: TESTED.** epubcheck finds no errors in DCIC's, the business communication book's, or OpenStax's sociology cartridge's; the five in *Information Systems* are the publisher's own.
- **Markdown: NEEDS MORE TESTING.** The suite converts HTML to Markdown and back, and a banded table survives the trip. But on DCIC's pages, one page held a formula as MathJax 2 draws it, eleven spans deep, and Pandoc's Markdown reader didn't finish reading back what its own writer wrote: its time grows steeply with how deeply spans nest.

## AsciiDoc

**How it can arrive**

- Files in the book's directory, with a master file whose `include::`s give the book's order ([AsciiDoc sources](asciidoc.md)).
- A plain `.zip` of them.

**What it becomes**

- **HTML: TESTED**, on the security textbook (14 pages, its 54 cross-references by title resolved) and the suite. Asciidoctor's own settings (`:toc:`, `:icons:`, `:stylesheet:`, `:sectnums:`) are dropped, and a block's layout attributes are passed through as they are (next item).
- **EPUB: NEEDS MORE TESTING.** The security textbook's EPUB fails epubcheck with 43 errors, all one cause: Pandoc's AsciiDoc reader turns a block's `width`, and a diagram's `target`, into attributes the HTML writer puts on `<figure>`, `<pre>`, `<div>`, and `<table>`, where XHTML doesn't allow them. Not fixed yet.
- **Markdown: NOT TESTED.**
- **AsciiDoc: Not available.**

## The outputs, and how each is packaged

### HTML

A directory of pages, one per target (`output_dir`), each page's images and linked files copied beside it under names that need no encoding in a link. `menu: on` adds a menu for posting the pages as a site. Packaged by [`build-cartridge.py`](packaging.md), which `convert.py` runs once `packaging.yaml` exists:

- **A Common Cartridge** (`format: common-cartridge`), written to the 1.1 profile, which every major LMS imports. `--zip` builds the `.imscc`; without it, the manifest is written with the `zip` command that would build it. A cartridge this pipeline builds converts back to the same pages and files.
- **The same package named `.zip`** (`format: zip`): the manifest and the pages as in the cartridge, in an archive named `.zip`.

SCORM packaging is planned once SCORM is taken up as output.

### EPUB

One `.epub` per `epub3` target, built by [`build-epub.py`](epub.md) from the same pages and the same contents, its accessibility claims computed from the build. An EPUB holds its own resources and a reading system follows links only among its pages, so every EPUB, whatever the input:

- makes an image on another server a link to it, named by its alt text;
- makes a frame a link to what it shows, a YouTube or Vimeo video's own page for a video;
- keeps a link to a local file (a PDF, a Word file) as its text only, and the output check lists each one as `link-to-file-dropped`;
- has no menu from `menu: on`, which HTML targets add for posting the pages as a site.

The `.epub` is itself the package: there's nothing further to package it in.

### Markdown

A directory of `.md` files whose media keep the author's names, written to be a source again. `merge: groups` makes one file per top-level group of the book's contents instead of one per page. It's packaged as the directory.

### PDF and Word

Not available: [roadmap item 2](../ROADMAP.md). PDF waits on LaTeX's tagging support for complex table headers, and Word output is the riskier of the two, for the reasons the roadmap gives.
