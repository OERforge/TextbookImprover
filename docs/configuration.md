# Configuration

How `packaging.yaml`, `conversion.yaml`, and `project.yaml` fit together, how a value is settled when several files could supply it, and the parts of the configuration that are structure rather than settings. The settings themselves are listed, one per line with its default and description, in three pages generated from the schemas: [project settings](project-settings.md), [conversion settings](conversion-settings.md), and [packaging settings](packaging-settings.md).

## Configuration

Three files, split by what a setting describes rather than by which script reads it. The work has two halves, and these pages call them that: conversion (`convert.py`, which turns the sources into pages, an EPUB, a PDF, and the other outputs) and packaging (`build-cartridge.py`, which turns the pages into a Common Cartridge for an LMS). Each has a file of its own, and one file describes the book for both. [Terms these pages use](glossary.md) explains the other words these pages rely on.

| File | Holds | Read by |
|---|---|---|
| `project.yaml` | Facts about the book: its language, identifier, title, and structure. | both |
| `conversion.yaml` | How the book is rendered into an output format. | conversion |
| `packaging.yaml` | How rendered files are assembled into an archive. | packaging |

Every setting is declared in a schema — `lib/schema-project.yaml`, `bin/schema-conversion.yaml`, `bin/schema-packaging.yaml` — which gives its type, its default, and a sentence saying what it means. The schema is the only description: the readers, the validator, the generated sample files, and this document all derive from it, so there's no second list to drift out of step with the first.

### Samples

Each file has a sample written from its schema: every setting with its description, at the value the file gives it or else the default, so a sample renamed over its file loses nothing set there. With `T` the directory the tools are in, run in the book's directory:

| Sample | Written by | Rename it to |
|---|---|---|
| `project-sample.yaml` | a run, when nothing names the book; and `build-cartridge.py -d . --pages html --init`, when nothing names the book and no run has written one | `project.yaml` |
| `conversion-sample.yaml` | `python3 $T/bin/read-conversion-config.py -d . --init` | `conversion.yaml` |
| `packaging-sample.yaml` | `python3 $T/bin/build-cartridge.py -d . --init` | `packaging.yaml` |

A run also writes `project-sample.yaml` for review when it worked out the contents itself: guessed from the file names, taken from a master file's order, read from an outline with `--toc`, or resolved from a page the split cut. For an order the packager works out, guessed or read with `--toc`, a book named in `packaging.yaml`'s own `project:` block gets `packaging-sample.yaml` instead, the contents in its block, since that's where the book is named. `--pages` names the directory the pages are in, `html/` unless an HTML target says otherwise, which `--init` needs only for the contents it guesses into a project sample. [Project settings](project-settings.md), [conversion settings](conversion-settings.md), and [packaging settings](packaging-settings.md) list the same settings.

### Where the book is named

`project.yaml` names the book for both halves: its identifier, title, language, and contents. `conversion.yaml` and `packaging.yaml` may each carry a `project:` block instead, read by that file's half alone, which is all a book that uses one half needs:

- A book named in `packaging.yaml`'s block alone gets its cartridge. An EPUB, a PDF, or a LaTeX target can't see that name, so it isn't written, and the run says to name the book in `project.yaml` or in `conversion.yaml`'s block too.
- A book named in `conversion.yaml`'s block alone gets its EPUB and its pages. With no `packaging.yaml` either, it isn't packaged, and the run says so and isn't an error, unless an option meant for the packager (`--zip`, `--toc`) asks for a package; with that, or with a `packaging.yaml` that doesn't name it, packaging stops, and its `project-sample.yaml` carries the block's values.
- A book named in both blocks gets everything, and the run notes that `project.yaml` would say it once.

However many files describe the book, they have to agree. A setting given two different values, in `project.yaml` and a block or in the two blocks, stops the run before anything is converted, naming both files; a setting given in one file and not another is just given.

### Required settings

Two have no useful default: `project.identifier` and `project.title`. With neither `project.yaml` nor a `project:` block in `packaging.yaml`, packaging writes `project-sample.yaml` and stops; a `project.yaml` that leaves either one at its default (`book`, `Untitled`) is warned about. A target that writes a book, an EPUB, a PDF, or a LaTeX master, needs the title too. With none configured, it takes the title a master file gives, an AsciiDoc master's `=` line or a LaTeX master's `\title` (not the first of several documents `latex.main` lists), or a book of one page takes that page's, and the run says so; a PDF whose `pdf.metadata` file has a title, and a LaTeX book's PDF from its own build (`pdf.from: book`), are titled as those say. With nothing to take it from, or with the title only in `packaging.yaml`, that target isn't written, the run says where the title goes, and it ends in an error once the other targets are written.

`identifier` is worth care. Brightspace matches on it when re-importing, so changing it duplicates a course rather than updating it. Keep it stable across rebuilds, and change it only when the book is genuinely a different book.

### Targets

Both `conversion.yaml` and `packaging.yaml` have the same shape: a `defaults:` block, then a `targets:` block naming one or more things to build. A target inherits the defaults and overrides what it needs.

```yaml
defaults:
  promote_h1_to_title: always

targets:
  html:
    format: html
```

Every target is built, each into its own `output_dir`, named after the target unless it says otherwise: `html/` for the one implied when no configuration exists, and several HTML renderings with different headers, footers, or options, an EPUB, and whatever else the schema's `format` lists when they're declared. The content directory keeps the sources, the intermediates, the sidecars, and the reports. A page you finished by hand (an `.html` in the pass-through directory, `_pt/`; one beside the sources is a source like any other: [HTML sources](html.md)) is copied into every HTML target with the local files it refers to, and read into an intermediate so the EPUB has it too. The filtered intermediate is a page after the filter has done its work on it, which every target is written from. Two targets that agree on every setting that changes it (the schema's filter-stage settings: images, tables, captions, the split, the sidecars) share one; a target that differs gets its own under its output directory. Settings that only change how a target writes (`header`, `footer`, `output_dir`) or assemble a book (`epub.*`) cost nothing to vary. The packager reads the first HTML target's directory; a package whose `includes` name another is on the roadmap. `output_dir: .` keeps the layout earlier versions used, pages beside the sources.

```yaml
targets:
  html:
    format: html
  print:
    format: html          # shares the intermediate; only the footer differs
    footer: "Printed edition."
    numbering: "off"      # the book is numbered; this edition isn't
  epub:
    format: epub3
    notes:
      placement: book     # every footnote on one Notes chapter
  src:
    format: markdown      # the book as source, one file per document
    pages:
      split_level: 0
```

A target can also decide `title_block`, `numbering`, and the footnote settings for itself; the [conversion settings](conversion-settings.md) reference says which settings are a target's and which are the book's.

`archive: zip` or `archive: tar.gz` packs a target's folder into one file once it's written, beside the folder and named after it (`html.zip`), for handing the output on whole; the cartridge is the packager's (`--zip`). It leaves out the `intermediates` folder a target keeps there when its filter settings differ from the first target's, which is the run's, not the output. A folder of PowerPoint decks is slides rather than a book (`project.kind`), and implies a `remediated` target with `format: source` when it declares none ([Slides](slides.md)).

### How values are settled

Four layers, in this order: the schema's default, the `project:` block, the file's `defaults:` block, then the target's own block. Five rules govern the rest, kept few on purpose:

- The schema decides what nests. A section merges key by key; anything else is replaced whole.
- Lists replace. They never append.
- An explicit `null` clears an inherited value back to the schema default. An absent key inherits.
- No coercion happens during the merge; each resolved value is checked once at the end against its declared type.
- An unknown key is an error, with a suggestion if one is close, and where it went if an earlier version had it or where it belongs if it's another block's setting (`version` is packaging.yaml's). Pass `--allow-unknown-keys` to report and ignore them instead, which is for reading a config written for a newer version of the tools.

Two kinds of setting have a place of their own. One that has to differ between targets, such as `format` and `output_dir`, is an error in `defaults:`. One the whole book shares, the `sidecars:` and `reports:` paths, is an error in a target: they're read once, for the whole book, so in a target they'd apply everywhere or nowhere depending on the order of the targets. Set them under `defaults:`.

### Two YAML traps

Both bite in this configuration specifically, and both are now caught rather than silently accepted.

**`language: no` is the boolean false.** YAML reads unquoted `no`, `yes`, `on`, and `off` as booleans, so Norwegian becomes `False`. There's no way to recover which word was written, so it's refused. Quote it.

A setting with `on` or `off` among its values (`menu`, `title_page`, `merge`, and the rest) is the exception: there the word meant is plain, so `menu: on` is `"on"` and `merge: off` is `"off"`. Any other setting of fixed values refuses a boolean, as `language` does.

**`version: 1.10` is the number 1.1.** The trailing zero is gone before any program sees it. Quote it.

### Contents

```yaml
# in project.yaml
project:
  contents:
    - BC-01                        # title comes from the page's <title>
    - page: 1-key-terms
      title: Key Terms             # override when <title> is wrong
    - title: Chapter 1 Sampling and Data
      items:
        - 1-introduction
        - 1-1-definitions-of-statistics-probability-and-key-terms
```

A group is a container only. In Common Cartridge an item pointing at a page should be a leaf, so a unit with its own introduction lists that page as its first child rather than pointing at it directly. Three levels of nesting are supported; deeper is accepted with a warning, since LMS support for deep hierarchies is uneven.

A group or page can carry a `role`: `front`, `main` (the default), `appendix`, or `back`. It says what part of the book the entry is, which a group's pages inherit. With `numbering: true` on the project, the book counts the way a printed one does: main groups and top-level pages 1, 2, 3 and their pages 1.1, 1.2; appendices A, B and A.1; front and back matter unnumbered, a chapter's own opening page taking the chapter's number. The numbers show in the EPUB's table of contents and headings, the cartridge organization, the generated contents page, and each page's own heading and `<title>`; a target can say `numbering: on` or `off` for itself. A Markdown book written for a Pandoc PDF build declares its parts already, with `\frontmatter`, `\mainmatter`, `\appendix`, `\backmatter`, and `{.appendix}` on a heading, and the guess reads those, so the sample comes out with the roles in place.

A role says where an entry sits in the book, not where it goes: the order is the order of `contents`, and only a top-level entry's role counts, for numbering, the PDF's divisions, and the EPUB's. A page inside a chapter is in the chapter's part of the book whatever its own role.

A group or page can also carry a `type`, what it is: `preface`, `foreword`, `dedication`, `epigraph`, `acknowledgments`, `prologue`, `abstract`, `introduction`, `copyright-page`, `part`, `chapter`, `conclusion`, `epilogue`, `afterword`, `appendix`, `bibliography`, `glossary`, `index`, or `colophon`, as EPUB's structural semantics name them. The EPUB marks it on the entry's section with its ARIA role and names a book-level bibliography, glossary, or index in its landmarks ([Building an EPUB](epub.md#what-goes-in-and-in-what-order)). A part's footnotes are grouped by its entries, not as a whole, so with `notes.numbering: group` each chapter in it is numbered on its own ([Footnotes across pages](splitting.md#footnotes-across-pages)). A type isn't inherited, since a chapter isn't a glossary because its Key Terms page is one, and a top-level entry with no `role` is in the part of the book its type implies: a glossary page at the end needs `type: glossary` and not `role: back` too, and it's unnumbered as back matter is. The front matter's types are `preface`, `foreword`, `dedication`, `epigraph`, `acknowledgments`, `prologue`, `abstract`, `introduction`, and `copyright-page`; the main matter's `part`, `chapter`, `conclusion`, and `epilogue`; `appendix` is an appendix; and the rest are back matter, so a book's Introduction chapter typed `introduction` is unnumbered front matter unless it says `role: main` too. Any other type is warned of and ignored. A type on a page that a split cut into pieces, or on a group's opening page (titled as the group is), is the group's: the glossary its pieces make up. A Markdown heading can mark a page the same way (`# Preface {epub:type=preface}`, or `{.glossary}`), which the EPUB marks too, but where the page sits is still what `contents` says, read alike by numbering, the PDF, the cartridge, and the EPUB; a Word heading can't say it at all, which is what `type` is for, and `contents` outranks a heading. A LaTeX book's sample gives the bibliography page the run writes out `type: bibliography`, at the top level after any parts and appendices. A guessed `contents`, and one ordered from an outline with `--toc`, gives a type to each page whose title names what it is: Preface, Foreword, Dedication, Epigraph, Acknowledgments, Prologue, Epilogue, Afterword, Abstract, Colophon, and Copyright; Glossary and Key Terms (`glossary`); Bibliography, References, and Works Cited (`bibliography`); Index; and an Appendix by its title's first word. So an OpenStax chapter's Key Terms is a glossary and its References a bibliography, and the preface and index are front and back matter by their types, with no `role` beside them. An Introduction or a Conclusion is as often a chapter's section as the book's, and isn't guessed; nor is a part or a chapter, which the groups already say.

An entry `generate: toc` is a page the run writes: the full table of contents as a nested list of links, numbered when the book is, placed wherever it sits in `contents`. It's named `toc` and titled `Contents` unless `name` and `title` say otherwise.

```yaml
contents:
  - role: front
    title: Front Matter
    items:
      - _preamble
      - generate: toc
      - _preamble--to-the-instructor
  - 01 BigPicture
  - …
  - role: appendix
    title: Math Review
    items: [A2 Math--fractions, …]
  - page: Z1 Glossary
    type: glossary
numbering: true
```

A page cut by `pages.split_level` is listed by its piece name, `chapter-7--economies-of-scale`; see [Splitting pages](splitting.md).

Omit `contents` and the order is guessed from the filenames — natural sort, so chapter 10 doesn't land between chapters 1 and 2, plus chapter grouping when the filenames encode it. `--include-all-html` groups the pages it appends the same way.

Chapters are detected by shape, not vocabulary: a numeric prefix (`12-3-the-f-distribution`, `12-key-terms`) or a `chapter-12` opener page, whose own `<title>` becomes the group heading. Within a chapter the order is opener, introduction, numbered sections, then back matter in the order set by `grouping.back_matter`. A role name not in that list sorts after the ones that are, and is reported rather than silently misplaced. A chapter that is one file (`01 BigPicture.md`, a book written a file per chapter) is that file, with no group heading over it, and a page read as an appendix keeps that role. The guess is written to `project-sample.yaml` for you to correct. It's a starting point, not a finished book.

### Header and footer

Injected into every page an HTML target writes (a page from the pass-through directory is left as it stands): the header in a `<header>` before the page's own content, and the footer in a `<footer>` after it. A screen reader lists them as the page's banner and content information, landmarks apart from its `<main>`, which holds the page's own content, header or no header. A setting that's a `<header>` or a `<footer>` already is used as it stands. With `menu: on`, the menu goes between the header and `<main>`, and the pager between `<main>` and the footer, each a navigation landmark. A page's own `include-before` and `include-after`, an epigraph in a Markdown source's metadata, say, are inside `<main>`. Either inline Markdown or the name of a Markdown file:

```yaml
# in conversion.yaml
defaults:
  footer: |
    *Your Textbook Here* is licensed
    [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
```

The footer is on every page of the other formats too, in the way each format has of putting something on every page:

- **EPUB**: the last thing in each content document, the title page among them, after the notes a chapter's file ends with; not on the cover or in the navigation document.
- **PDF**, and the PDF a `latex` target's master builds: the foot of every page, the title page and each chapter's first page among them, centered in small type under whatever the page style puts there (a chapter's first page has its page number there), and single-spaced whatever the text's line spacing. LaTeX's tagging marks the foot an artifact, outside the document's structure as a page number is, so a link in it would be a link outside the structure: a link is its words. A `pdf.metadata` file that narrows the bottom margin should leave the footer room: geometry's `footskip` sets how far under the text the page number goes, and the footer goes a small line under that. The PDF target's default page does ([The PDF's page](#the-pdfs-page)).
- **Word**: the footer of every page of every file, a paragraph for each of its paragraphs, in Word's Footer style; a link is its words here too.
- **Markdown and AsciiDoc**: the end of every file's text, a Markdown file's notes after it, in a div of class `oer-footer` (in AsciiDoc, an open block with that role), written as the rest of the file is. Reading the file back as a source takes out a div of that class at its end, whoever wrote it, since the target's own setting puts the footer back.

Outside an HTML page, a picture in the footer is its alternative text, a Creative Commons badge its words, and a link to one of the book's own files is its words too, since a target carries neither file. A heading in the footer is a paragraph, which no contents or bookmarks take in, and an id in it is left out, since the footer is on every page.

The header is on an HTML target's pages alone. A deck's PDF, PowerPoint file, and reveal.js presentation have no footer, and nor does a LaTeX book's PDF built from its own LaTeX (`pdf.from: book`), whose pages are the book's own; a `source` target's copy, the author's own file, has none either.

On an HTML page the fragment is inserted after the Pandoc filter has run, so nothing in it is processed — no alt checking, no spacer rule. Write its markup correctly by hand, and list any images it uses under `common_files`.

### The PDF's page

Every book's PDF, and the LaTeX a `latex` target writes, is set on the page `bin/pdf-layout.yaml` gives: US Letter with OpenStax's margins, 1 inch at the sides and 0.8 inch at the top and bottom, 12-point type on lines 1.5 times its size apart, and the text set ragged right, a word never broken at a line's end, in IBM Plex Serif, with its formulas in IBM Plex Math ([the faces](#the-faces), below). The file is the default for every book and the place to read the page's settings. Editing it changes every book's page, but a new version of TextbookImprover brings its own copy, and in a clone `git pull` won't update an edited one, so a copy for a book (below) is the lasting way to change its page:

```yaml
# The PDF target's default page: every book's PDF has it, unless a
# pdf.metadata file says otherwise, a field at a time, or the book is
# LaTeX, whose PDF keeps the book's own layout. To change it for a book,
# copy this file into the book's folder, change what you like, and name
# the copy in conversion.yaml (defaults: pdf: metadata: pdf-layout.yaml).
# A field the copy leaves out keeps its value here.

# OpenStax's paper and margins, which its books' tables were made for,
# with type larger than OpenStax's 9 points: a full line holds about 81
# characters in IBM Plex Serif. Any size works; the book class's own are
# 10pt, 11pt, and 12pt, and another, such as 13.5pt, is set with
# KOMA-Script's scrextend.
fontsize: 12pt
papersize: letter
geometry:
  - left=1in
  - right=1in
  - top=0.8in
  - bottom=0.8in
  # The page number, and the footer setting under it, in the bottom
  # margin: the number this far under the text.
  - footskip=0.3in

# Lines 1.5 times the type's size apart, as OpenStax sets them: 1.25 times
# the book class's own spacing, which is about 1.2 times the type's size.
linestretch: 1.25

# Ragged right, as OpenStax sets its text, and footnotes and captions
# with it, breaking no word at a line's end. TextbookImprover's own
# setting, not Pandoc's: false justifies them, as LaTeX does by itself.
ragged-right: true

# The faces: the text in IBM Plex Serif, sans-serif and monospaced type
# in IBM Plex Sans and Mono, and formulas in IBM Plex Math, where TeX has
# them (TeX Live's plex package), and in Latin Modern, with a warning,
# where it hasn't. A face named here sets its family instead: mainfont,
# sansfont, monofont, or mathfont; mainfont with no mathfont sets
# formulas in Latin Modern Math (docs/configuration.md, "The faces").

# WCAG 1.4.8 (AAA) asks for lines of no more than 80 characters, and for
# lines and paragraphs further apart than this page sets them, footnotes
# and captions too: TextbookImprover's bin/pdf-layout-wcag-aaa.yaml is a
# page that gives them, for a longer book (docs/configuration.md, "The
# PDF's page").
```

To change the page for one book, copy the file into the book's folder, change what you like, and name the copy in `conversion.yaml`:

```yaml
# in conversion.yaml
defaults:
  pdf:
    metadata: pdf-layout.yaml
```

A field the copy leaves out keeps the default's value, so a copy can be as short as the one line it changes (`fontsize: 13.5pt`), and a metadata file a book already has, a `_preamble.md` say, changes the page the same way. A file whose own LaTeX sets the margins or the line spacing, loading geometry or setspace in its `header-includes`, or setting `\linespread`, keeps them: the default's `geometry` or `linestretch` gives way. `ragged-right` is TextbookImprover's own; the others are [Pandoc's variables for LaTeX](https://pandoc.org/MANUAL.html#variables-for-latex), and any other of those can go in the file too (`documentclass`, `mainfont`, `header-includes`). An empty list clears a field: `geometry: []` gives the class's own margins. A type size or a paper given as a class option, `classoption: [11pt, a4paper]`, replaces the default's `fontsize` or `papersize`, as either field would. These four lines give the book class's own page, Pandoc's default, 10-point type, justified, in the class's margins, but for the contents, which leave room for a page number of four digits ([PDF](formats.md#pdf)):

```yaml
fontsize: 10pt
geometry: []
linestretch: 1
ragged-right: false
```

Pandoc reads the file, and Pandoc 3.13 reads it as YAML 1.2, its changelog says: a setting that's on or off is `true` or `false`, and `yes`, `no`, `on`, and `off` are words, which Pandoc's template takes as set, so `toc: no` gives a contents page and `colorlinks: no` colored links, where an older Pandoc read the four as true and false (measured with 3.12.1 and 3.13). `ragged-right`, which TextbookImprover reads itself, takes `no` and `off` as false with either. A key given twice stops the build, Pandoc saying which and where, where 3.12.1 warned and used the last.

- **Type size.** The book class has 10, 11, and 12 points; another size, `13.5pt` or `14pt`, is set by KOMA-Script's scrextend ([installation](installation.md#what-each-is-for)), with the class's other type sizes and its spacing at that size: a list's spacing and indents, and the space between paragraphs, are what the class and parskip give them at their own sizes. A class other than `book`, `report`, or `article`, which `documentclass` can name, is given `fontsize` as its own option.
- **Ragged right** reaches footnotes and captions as well as the text, which LaTeX would set justified whatever the text around them is, and it turns off microtype's font expansion, which justifies a line by drawing its letters a little narrower or wider and which a ragged line doesn't need. `false` justifies them all, as LaTeX does by itself, breaking a word where it must.
- **A LaTeX book** keeps its own layout: its PDF from its pages has the type size, paper, margins, and line spacing its preamble gives, or the class's own page where it gives none ([LaTeX sources](latex.md#the-pdf-target)). A metadata file still changes that a field at a time. A PDF built from the book's own LaTeX is the author's.
- **A face** the file names, `mainfont` for the text, say, has the fallback fonts the default's faces have, for a character it lacks: Latin Modern Math, and DejaVu Sans, New Computer Modern's math font, and Noto Emoji where they're installed. A file that gives a face fallbacks of its own (Pandoc's `mainfontfallback`, say) keeps them. A face the file names that isn't installed stops the build, and the run names it, where the default's give way to Latin Modern ([the faces](#the-faces), below). Named by its family, a face can be matched by another of its weights where only some are installed, without a word, as Debian's and Ubuntu's TeX Live has Noto Sans Medium and not its Regular, which `fonts-noto-core` has; named by its files, as an OpenStax book's is (`mainfont: NotoSans`, with `Extension=.ttf`, `UprightFont=*-Regular`, `BoldFont=*-Bold`, `ItalicFont=*-Italic`, and `BoldItalicFont=*-BoldItalic` in `mainfontoptions`), it can't.
- **An OpenStax book** gets a copy of the file in its folder from `unpack-cnx.py`, named in its `conversion.yaml`, on A4 for the two Polish books OpenStax prints on it, and with its text in its design's face, IBM Plex Serif, IBM Plex Sans, or Noto Sans, named by its files ([A CNXML book as the source](cnx-input.md#typefaces)). A copy keeps the values it was made with, whatever the default becomes.

#### The faces

The default's faces are IBM Plex's: Plex Serif for the text, and in its bold for the headings; Plex Sans and Plex Mono for sans-serif and monospaced type, code among it; and IBM Plex Math for formulas, whose letters are Plex Serif's. They're chosen for a reader with low vision. Of a typeface's features, size has the best support in research on reading, measured as the height of a small letter ([Legge and Bigelow, 2011](https://legge.dl8.umn.edu/sites/legge.psych.umn.edu/files/2020-08/Legge%20Bigelow%202011%20Does%20size%20matter%20for%20reading%3F%20A%20review%20of%20findings%20from%20vision%20science%20and%20typography.pdf)): at 12 points, an x is 2.18 mm tall in Plex Serif, over the 2 mm the UK Association for Accessible Formats gives for 12-point clear print ([UKAAF, 2024](https://www.ukaaf.org/wp-content/uploads/2024/12/G003-UKAAF-Creating-clear-print-and-large-print-documents-v4.pdf)), where it's 1.82 mm in Latin Modern, TeX's own design, the default's face before. Of the nine serif faces tried that TeX Live has with a math font made to match, Plex Serif's small letters are the largest. Its thinnest strokes are two and a half times as thick as Latin Modern's, whose thinnest are a third of a pixel wide at 12 points and 100% zoom. And it draws every Greek and Cyrillic letter itself, and each of 16 symbols books use as text, μ, ≤, ≈, and ∞ among them, where Latin Modern has half the Greek, none of the Cyrillic, and half the symbols, the rest drawn from the fallback fonts, in other designs. What it costs is length: its letters are wider, so a full line holds about 81 characters where Latin Modern's held 88, and a book is about 6 percent longer, *Introduction to Sociology 3e* 1,032 pages where it was 975.

Code is in Plex Mono at the text's size: Pandoc's template scales every face but the text's to the text face's small letters, and Plex Mono's are as tall as Plex Serif's. A line of the default page holds 65 characters of code at 12 points, and a block of code with a longer line is set smaller to fit it, as a table too wide for its line is ([PDF](formats.md#pdf)): to three quarters of its size at least, where a line holds 86, and a block with a line too long even then is set at three quarters, its lines too long for their line wrapped, so that no code runs into the margin. `code_wrap` sets how far a block is set smaller first, from 0.5 to 1 of its size: `code_wrap: 1` wraps every line too long for its line at the code's own size ([Conversion settings](conversion-settings.md)). Beside a face the file names for the text, Plex Mono is scaled to that face's small letters.

A face the file names sets its family in place of the default's, and one for sans-serif type, code, or formulas is scaled to the height of the text face's small letters, Plex Serif's where the file names no face for the text, as Pandoc's template scales it, unless its options give it a `Scale` of their own. The formulas are in Plex Math only where the file names no face for the text and none for formulas, since Plex Math's letters are Plex Serif's: a file that names a face for the text alone gets Latin Modern Math, unicode-math's own, which Pandoc's template scales to the text's small letters. A math font the file names that TeX lacks, or that has no math table (OpenType's MATH, which LaTeX sets a formula by), gives way to Latin Modern Math too, and the run warns, saying which and how to fix it, where LaTeX had stopped on a font TeX lacked; the LaTeX a `latex` target writes does the same when it's built. A math font whose `mathfontoptions` give a `Path`, a font file in the book's own folder, say (`Path=fonts/`), is looked for as that file, its path and name run together, as fontspec runs them together to load it. A face's name, its options, and its fallbacks are written into fontspec's commands as the file gives them, so a file or a folder named with an underscore, as a downloaded face's often are (`Path=fonts/Open_Sans/static/`), is found, where Pandoc's writer had made it `\_` and LaTeX had stopped ("Missing \begin{document}"); a brace in an option is as written too (`RawFeature={+smcp}`), where the writer had made it `\{`; and an apostrophe, two or three hyphens, and three periods are as typed, where Pandoc's reading of the file had made them typographer's marks. An OpenStax book in Noto Sans names Noto Sans Math, which needs its version 3.000 ([Installation](installation.md#noto-sans-math)). Where the file's own LaTeX sets a math font, as `\setmathfont[range=\mathcal]{latinmodern-math.otf}` in `header-includes` sets script capitals from Latin Modern Math, the faces are set ahead of the file's LaTeX, since unicode-math takes a range only after the main math font; set after it, they had stopped LaTeX ("No main maths font has been set up yet") or lost the range.

**A face with a STAT table that isn't a variable font** is embedded in the PDF from its own file, as any face is. A variable font is one whose weight or width can be set anywhere along its axes, and its STAT table names them; a face made from one, at one weight, can keep the table, as Noto Sans 2.008's regular and bold do, and TeX Live's Josefin Sans, but not TeX Live's own Noto Sans (2.005) or IBM Plex. luaotfload, which loads a face for LuaLaTeX, takes any face with the table for a variable font, and such a face had been embedded from luaotfload's own copy of its outlines: without its hinting, which keeps small type crisp on a screen, each accented letter drawn as one shape rather than from a letter and an accent, and the letter's and accent's own glyphs, which the PDF's font still holds, filled with others of the face's. Acrobat said it couldn't extract *Introductory Business Statistics 2e*'s Noto Sans so ("Some characters may not display or print correctly"), and didn't name its italics, embedded from their files; built with the setting, the PDF opens in Acrobat without the message. What Acrobat couldn't extract was the space, which a tagged PDF draws between words: luaotfload's copy gives a glyph with nothing to draw an outline of no contours, where a font gives it none, and the book opened without the message with only those emptied, the hinting, the accented letters, and their parts as they were. A variable font is still embedded from luaotfload's copy, without its hinting, but with its empty glyphs written as a font writes them. The setting goes ahead of the faces in a copy of Pandoc's own LaTeX template, since luaotfload settles how a face is embedded as it first loads it, and the template can load one where it sets the faces, before a `header-includes`; where Pandoc's template hasn't the line it goes before, the run warns, and such a face is embedded as before. A deck's PDF has it too, ahead of a deck's own LaTeX, and so does a LaTeX book's tagged copy, just after `\DocumentMetadata`, before its class ([LaTeX sources](latex.md#the-source-target)).

**A variable font whose outlines are CFF2**, the form a variable font with PostScript's outlines takes (Adobe's are, as `SourceSerif4Variable-Roman.otf`; Google's are TrueType), is embedded with its glyphs drawn. luaotfload keeps no outline of some such faces (it stopped on Source Serif 4's), and a page set in one showed no text at all, though its text could still be copied. Such a face's glyphs are written as luaotfload's HarfBuzz mode writes them (`Renderer=HarfBuzz`), each ending as a CFF glyph must, which that mode had left off every glyph of such a face. That mode reads a face with more than one axis wrongly, so its letters aren't drawn at the weight or optical size asked for (Source Serif 4's regular and bold were both drawn as its regular at its smallest optical size), and the run warns where it writes one, naming it: the face's TrueType version (`SourceSerif4Variable-Roman.ttf`), or its static faces, are drawn as they should be. A face with one axis is drawn at the weight, or the named instance, asked for.

**Where TeX lacks Plex**, or any one of the 13 files the default's faces take, the book is set in Latin Modern, as it was before, and the run warns, naming a file LaTeX couldn't find and the package that has them all, TeX Live's `plex` ([installation](installation.md#what-each-is-for)): `tlmgr install plex` for TinyTeX or TeX Live from tug.org, and `sudo apt install texlive-fonts-extra` for Debian's or Ubuntu's texlive packages. A family the file names keeps its face, and only those it doesn't name give way. The LaTeX a `latex` target writes does the same when it's built, LaTeX's log saying so. To keep Latin Modern without the warning, name its faces in the file: `mainfont: Latin Modern Roman`, `sansfont: Latin Modern Sans`, `monofont: Latin Modern Mono`, and `mathfont: Latin Modern Math`. On the page for WCAG 1.4.8 (AAA), below, which Latin Modern's lines are too long for at its size, the warning says the PDF no longer meets the criterion and names the size that would.

#### WCAG 1.4.8 (AAA)

[Visual Presentation](https://www.w3.org/WAI/WCAG22/Understanding/visual-presentation.html) asks for five things a reader can have of a block of text, and lets the means be the reader's own PDF viewer ("the mechanism can be provided by the browser or other user agent"). Two are a viewer's whatever the page: colors the reader chooses, and text enlarged to twice its size without scrolling sideways, as a viewer's reflow of a tagged PDF gives it. The default page gives a third, text that isn't justified, and lines space-and-a-half apart, and misses the rest: its lines average about 81 characters in IBM Plex Serif, spaces counted, where the criterion asks for no more than 80 (Latin Modern's average 88), and its paragraphs are closer together than it asks, its footnotes' and captions' lines too. `bin/pdf-layout-wcag-aaa.yaml` is a page that gives them, for a book that's to meet the criterion, and a book on it is longer: *Introduction to Sociology 3e* runs to 1,139 pages on it in Plex, where the default gives it 1,032. It's the default page with three changes, below. Copy it into a book's folder and name the copy in `conversion.yaml`, as with a copy of the default, or copy it over `bin/pdf-layout.yaml` to make it every book's page:

```yaml
# A page for a book whose PDF is to meet WCAG 1.4.8, Visual Presentation
# (AAA): the PDF target's default page (bin/pdf-layout.yaml) with larger
# type, paragraphs further apart, and footnotes and captions spaced as
# the text is, which makes a book about 10 percent longer. To use it for
# a book, copy it into the book's folder and name the copy in
# conversion.yaml (defaults: pdf: metadata: pdf-layout-wcag-aaa.yaml); to
# make it every book's page, copy it over bin/pdf-layout.yaml.
# docs/configuration.md, "The PDF's page", says what each setting gives.

# Lines of no more than 80 characters, on average: 12.5-point type in
# OpenStax's margins holds about 77 to a full line in IBM Plex Serif,
# the default's face. Latin Modern holds more to a line at a size: a book
# set in it, as the default is where TeX lacks Plex, or as a book's own
# file can name it, needs 13.5-point type (fontsize: 13.5pt), about 78
# to a full line.
fontsize: 12.5pt
papersize: letter
geometry:
  - left=1in
  - right=1in
  - top=0.8in
  - bottom=0.8in
  - footskip=0.3in

# Lines space-and-a-half apart, 1.5 times the type's size, as W3C's
# technique for the criterion (C21) measures it: 1.25 times the book
# class's own spacing, which is about 1.2 times the type's size.
linestretch: 1.25

# Text not justified.
ragged-right: true

# TextbookImprover's own: the page is meant to meet the criterion, so a
# book's build on it measures the text's full lines as they're set and
# warns where they average more than 80 characters, as a face that holds
# more to a line at this size can make them: Latin Modern, which the
# default gives way to where TeX lacks IBM Plex, holds about 84.
wcag-aaa: true

# Paragraphs 2.5 times the type's size apart, from the top of one
# paragraph's last line to the top of the next one's first, a space of
# 1em between them at this line spacing. And footnotes and captions
# spaced as the text is, 1.5 times their type's size, where setspace and
# the caption package would set them single-spaced. A book's own
# pdf.metadata file that sets header-includes replaces these two lines,
# as it would any setting here, so they go in its list too.
header-includes:
  - '\setlength{\parskip}{1em plus 2pt}'
  - '\SetSinglespace{1.25}'
```

- **Lines of no more than 80 characters**, which W3C's technique for it reads as an average ([C20](https://www.w3.org/WAI/WCAG22/Techniques/css/C20)): 12.5-point type, whose full lines average about 77 in IBM Plex Serif (73 to 81, at the 10th and 90th percentiles), where the default's average 81 (77 to 85), spaces counted, in *Introduction to Sociology 3e*'s section 1.3 and *College Algebra 2e*'s. Latin Modern's letters are narrower, and a full line of it averages 78 at 13.5 points and 88 at 12: a book set in it, as the default is where TeX lacks Plex, needs `fontsize: 13.5pt`, as the page's comment says. The page says it's meant to meet the criterion (`wcag-aaa: true`), so a book's build on it measures the text's full lines as LaTeX sets them, the lines of a paragraph but its last, in the text's own face and width, not a line a line break ends, as a poem's are, and, where it has 20 such lines at least, warns where they average more than 80 characters, naming the type size, to the half point above, at which they'd hold no more: a book in Latin Modern at 12.5 points, whose full lines hold about 84 (86 in the PDF suite's book), is warned of whether TeX lacked Plex (where the warning of the fallback says so) or the book's own file named Latin Modern. A book whose lines hold no more than 80 gets no word of it. Larger type serves a reader with low vision too, but gives a wide table fewer characters' room: in Latin Modern, the default's face when this page was made, *Introductory Business Statistics 2e* had 81 lines that ran into the margin at 13.5 points, where the default gave it 54. Side margins of 1.1 inches with 12-point type would meet the criterion too, about 78 a line (73 to 82), the text then 0.2 inch narrower than the 6.5 inches OpenStax's tables were made for (`geometry: [left=1.1in, right=1.1in, top=0.8in, bottom=0.8in, footskip=0.3in]`). The two sections, 33 pages on the default page, are 36 on this one, 40 on it in 13.5-point type, and 34 on the default page with the wider margins.
- **Lines space-and-a-half apart**, which W3C's technique for line spacing ([C21](https://www.w3.org/WAI/WCAG22/Techniques/css/C21)) measures from the type's size: the default's lines, 1.5 times the type's size apart, are space-and-a-half already, and the page keeps them.
- **Paragraphs further apart than lines**: "paragraph spacing is at least 1.5 times larger than the line spacing", which W3C's explanation of the criterion measures from the top of one paragraph's last line to the top of the next one's first, 250% of single spacing. Measured from the type's size instead, as C21 measures lines, that's 2.5 times the type's size, a space of 1em between paragraphs at this line spacing. The default's paragraphs are 2.1 times the type's size apart, half the class's line apart as parskip sets them (OpenStax's are 2.2).
- **Footnotes and captions spaced as the text is.** setspace sets a footnote single-spaced, 1.2 times its type's size, whatever `linestretch` says, and the caption package does the same to a caption in a book with a table, which every OpenStax book has. setspace's `\SetSinglespace{1.25}` gives them the text's spacing, 1.5 times their type's size.

A book's own `pdf.metadata` file changes this page as it does the default, a setting at a time, so a file that sets `header-includes` replaces the page's two lines of LaTeX, and needs them in its own list: a book with this page copied over `bin/pdf-layout.yaml` and a metadata file of its own loading a package, say. An OpenStax book's own file names its face ([A CNXML book as the source](cnx-input.md#typefaces)), which the page leaves to the default's: to put such a book on this page, make the page's changes in the book's file, or add its face's lines to a copy of the page.

Only the criterion's own words are normative, and they don't say what space-and-a-half is measured from. The technique, one of the criterion's [sufficient techniques](https://www.w3.org/WAI/WCAG22/Understanding/visual-presentation.html#techniques), measures from the type's size, and W3C says of a sufficient technique that [using it meets the criterion](https://www.w3.org/WAI/WCAG22/Understanding/understanding-techniques). Its explanation of the criterion measures from single spacing instead, "the default spacing for the font", which LaTeX makes 1.2 times the type's size, so that space-and-a-half is 1.8 times the type's size and paragraphs 3 times it apart. That reading needs `linestretch: 1.5`, and in `header-includes`, `\setlength{\parskip}{1.2em plus 2pt}` and `\SetSinglespace{1.5}`, and made *Introduction to Sociology 3e* 1,408 pages in Latin Modern.

### Headings that skip a level

```yaml
# in conversion.yaml
defaults:
  heading_levels: source    # outline, the default, closes the gaps
```

A heading more than one level below the heading before it skips a level: a screen reader's list of headings, and an EPUB's or a PDF's outline, have a gap there. WCAG's technique for headings asks for headings "properly nested", an `h2` followed by an `h2` or an `h3` ([G141](https://www.w3.org/WAI/WCAG22/Techniques/general/G141), advisory under 1.3.1), and the Nu checker reports a skip as an error. Sites skip levels for the look of a heading's size: LibreTexts sets the legend of each Example, Exercise, or Note box as an `h5`, and a Solution under it as an `h6`, under sections that are `h2`s and `h3`s, and *A Data-Centric Introduction to Computing* (DCIC) sets a page's sections at the third level under its title.

With `heading_levels: outline`, the default, the run lifts each such heading to one level below the heading it's under, and what's under it with it, so nothing skips and every heading keeps its place in the outline. A heading's parent is the nearest heading before it at a shallower level in the source; a page's title, which every output shows as its H1, is above them all, so a page's first headings are H2 at the deepest. A heading that skips nothing keeps its level, and none goes deeper. The run says how many headings it moved, on how many pages, and the first. With `source`, every heading keeps the source's level, and the output check names each skip (`heading-skips-level`).

The headings move in the pages the run writes, and so in every target and in a `markdown` target's copy; a Word file's own copy (`format: source`) keeps its styles. A deck's headings are its slides and sections, and keep their levels. A page cut at its headings (`pages.split_level`) is cut after they've moved, so a page's sections set a level too deep are cut where they now are.

Verified here: on *Instrumental Analysis*, the 136 headings the output check found skipping a level, and the Nu checker's 68 errors, were all box legends and solutions, and none is left (the run moved 139 headings on 45 pages, a solution under its legend among them); the convert suite checks a page with a title and one without, a box's legend, and `source`.

### Caption labels

```yaml
# in conversion.yaml
defaults:
  captions:
    table_prefixes: [Table, Figure, Exhibit]
    figure_prefixes: [Figure]
```

The words that introduce a caption. One book in the test corpus labels every table `Figure 1.1`, and with the default of `Table` alone those tables got no caption. Listing `Figure` under `table_prefixes` is safe: which rule applies is decided by what the table contains, not by the word.

### Shared files

```yaml
# in packaging.yaml
defaults:
  common_files:
    - shared/banner.png
    - shared/course.css
```

Files used by more than one page. They are declared once in a `common_files` resource that every page depends on, instead of being repeated in each page's file list.

Files a page references on its own are found automatically and don't belong here. This list is for files you want shared, and for anything reached from the header or footer — the page scan sees those on every page and can't attribute them to one.

Common Cartridge `<dependency>` support varies between systems. Test a small cartridge before relying on it; removing `common_files` falls back to per-page entries.

### Spacer images

Word documents often use a tiny transparent GIF as a bullet. One book in the test corpus had 274 of them across 487 images.

```yaml
# in conversion.yaml
defaults:
  images:
    spacer_below: 0.3       # inches; anything narrower is a spacer, 0 disables
    strip_spacer: true      # true removes them, false marks them decorative
  reports:
    spacer_images: spacer-images.csv
```

With the rule off, suspected spacers are still counted and reported so the setting is discoverable. Images with no readable width can't be judged and are reported separately.

```yaml
# in conversion.yaml
defaults:
  images:
    alt_max_chars: 120
```

Alt text longer than this is reported for shortening. It's a length at which a short equivalent has become a long description, and long descriptions belong in the prose where every reader gets them. Raising it silences the report rather than fixing anything.

### Images larger than they're shown

```yaml
# in conversion.yaml
defaults:
  images:
    compress: screen   # print, screen, or small; none, the default, keeps every image as it is
```

A web page often holds an image much larger than it shows it and leaves the browser to scale it down. *Instrumental Analysis* on LibreTexts shows a photograph 2,150 pixels wide at 180, and 442 of its 483 images are wider in pixels than they're shown, 173 of them more than twice as wide. Every output carries an image whole, so an EPUB, a Word file, or a PDF of such a book weighs what all its originals do: that book's images come to 145 MB, its EPUB was 142 MB, and its zip of Word files 155 MB. A photograph's file can also be larger than its pixels need: OpenStax saved 87 of *Principles of Marketing*'s 110 photographs, JPEGs, at quality 99, the most JPEG has but 100, and the 110 weigh 47.9 MB of its images' 59.6; written again at quality 90, they're 22.9 MB.

**Three levels.** `images.compress` makes the images smaller at a level, each two things: how many times an image may be as wide, in pixels, as it's shown, which an image wider than that is scaled down to; and the highest quality a JPEG keeps, which one saved at a higher quality is written again at, at its own size where it isn't scaled, as is a JPEG scaled down.

- `print`: 4 times as wide, and quality 90, a JPEG keeping its color at the resolution the original has it, where `screen` and `small` write it at half resolution each way (4:2:0), libjpeg's default. In a PDF on the default page, a copy keeps at least 354 pixels an inch, more than the 300 printing is usually said to want.
- `screen`: 2 times, and quality 85: as sharp as a screen that draws two of its pixels for each CSS pixel shows it, and at least 177 pixels an inch in a PDF.
- `small`: 1 time, and quality 75: the smallest files, as a screen that draws a pixel for each CSS pixel shows the image, at least 89 pixels an inch in a PDF.

Measured on *Principles of Marketing*'s PDF, 61.3 MB with every image whole: 36.3 MB at `print`, 23.9 MB at `screen`, and 13.4 MB at `small`. At `print`, no image is more than 4 times as wide as it's shown, so only the 110 JPEGs change, written again at quality 90 (47.9 MB to 22.9); at `screen`, 87 images are scaled down and the other 88 JPEGs written again (56.4 MB to 14.9); and at `small`, 225 are scaled down (59.5 MB to 6.6). veraPDF finds nothing in any of the three.

`images.downsample` is the first of the two alone, a number: the most times an image may be as wide, in pixels, as the width it's shown at. Set beside a level, it replaces the level's limit, and the level's quality stands, so a number larger than any image is wider than it's shown, 100 say, keeps every image's pixels and writes the level's JPEGs again all the same; with `compress` at `none`, it's the only limit, a JPEG it scales is written at quality 90, or at its own where that's lower, and no other JPEG is written again. At 0, its default, the limit is the level's, or with `none` there's none.

```yaml
defaults:
  images:
    downsample: 3      # 0, the default, leaves the limit to images.compress
```

The `html`, `epub3`, `docx`, `pdf`, `revealjs`, and `pptx` targets carry the smaller copy. The original stays as it is, and so do the copies that `source`, `markdown`, `asciidoc`, and `latex` targets write, since those are the author's files; so does a LaTeX book's PDF built from its own files (`pdf.from: book`), which sets the images as its LaTeX does. The run says how many images it made smaller, what they weighed before and after, and how many of them were drawings given a palette (below). A copy that comes out larger than its original isn't used, and the run counts those too: mostly an image only a little wider than the limit, whose copy has nearly as many pixels as it has.

At 0 and `none`, the defaults, nothing is made smaller, and when an image is wider than it's shown, or a JPEG saved at a quality over 90, the run says so once, with the widest for its size, the highest quality, and where to read about the settings. *Principles of Marketing* gives:

```
WARNING: 225 image(s) are wider in pixels than the pages show them, 87 of them more than twice as wide, up to 3.4 times (media/MKT_Figure_02_01_003.png, 1939 pixels shown 576 wide), and 110 JPEG(s) are saved at a quality over 90, up to 99; the outputs carry them whole, 59.5 MB in all. images.compress makes them smaller, at a level of print, screen, or small, and images.downsample scales an image down to a set number of times the width it's shown at (docs/configuration.md#images-larger-than-theyre-shown).
```

A target can have values of its own, as with any setting, and one left at the defaults beside others that make images smaller is named in the warning.

**The width an image is shown at** is the one its page gives it, in CSS pixels: its `width`, or, failing that, its `height` and the image's own proportions, in pixels or any length CSS converts to pixels, a percentage being one of the column. An image with neither is shown at its own width. Either way, it's no wider than the column the pages set their text in, 36em in Pandoc's stylesheet, which is 576 pixels at a browser's default text size. With `images.responsive` on, as it is unless turned off, a page keeps no image's height, so an image sized by its height alone is shown at its own width, and measured so. Only an image a page shows as an image is measured, and only a raster one (PNG, JPEG, GIF, WebP, BMP, or TIFF): an SVG has no pixels to spare, an animated GIF or PNG is left whole, and a picture in a page's raw HTML isn't seen.

**Choosing a value.** A CSS pixel is 1/96 of an inch ([CSS Values and Units](https://www.w3.org/TR/css-values-4/#absolute-lengths)), and a high-density screen draws two or three of its own pixels for each one, so 2 serves most screens and 3 the densest. A PDF draws an image no wider than its line, which on the PDF target's default page is 6.5 inches, where the pages' column is 6, and an image its page gives no width at its own size, from its resolution: so a copy keeps at least 89 pixels an inch there for each step of 1, 354 at 4, and more where the PDF draws it narrower. *Principles of Marketing*'s chapter openers, 1,750 pixels wide and drawn across the line, have 269 pixels an inch with every image whole, and 177 at `screen`.

**What a copy keeps.** Its format and its file's name, its color profile, a JPEG's EXIF data, and the size it prints at: its resolution in pixels an inch is scaled with it, in a JPEG's EXIF data as well as its header, since LaTeX and Pandoc's Word writer read it there first, so Word and a PDF set it at the original's size. A JPEG scaled down whose EXIF data has its resolution loses the small preview the data may hold, its thumbnail, which Pillow doesn't write again. It's resampled with a Lanczos filter; a JPEG is written at the level's quality, or at 90 without one, or at its own quality where that's lower, and a PNG or GIF that had a palette gets one again, of at most 256 colors. A PNG copy of a drawing in color gets one too: an original in RGB or RGBA of 4,096 colors or fewer, a drawing's or a chart's flat colors, compresses well, but a copy resampled from it holds thousands of colors along its smoothed edges, which compress worse, so without a palette such a copy can come out larger than its original however small it's scaled. The palette is an adaptive one of 256 colors (median cut, or fast octree for a copy with transparency, an alpha channel or a transparent color, which median cut can't keep). A photograph's copy keeps its colors, since a palette speckles a photograph's smooth shades, and so does a copy of an image in shades of gray. A JPEG's quality is read from its file, from the table it was compressed with, as the quality libjpeg makes that table for: it's the one Pillow saved it at, for each quality from 1 to 100, and the one ImageMagick reports for 109 of *Principles of Marketing*'s 110 JPEGs, one less for the other. Making copies needs [Pillow](https://pillow.readthedocs.io/), Python's imaging library ([Installation](installation.md#requirements)); without it, a run with either setting stops before reading a page and says what to install. The warning at the defaults needs nothing to measure the images, and Pillow to read a JPEG's quality.

**Where the copies go.** The run makes them once for each limit and quality its targets use, in a temporary folder it removes when it's done: an `html` or `revealjs` target copies them beside its pages in the originals' place, and Pandoc, writing an EPUB, a Word file, a PDF, or a deck, finds them before the originals on its [resource path](https://pandoc.org/MANUAL.html#option--resource-path). `build-epub.py` and `build-pdf.py`, run on their own, make their own.

Measured here, on *Instrumental Analysis*: at 2, 173 of its 483 images are more than twice as wide as they're shown, and every one was scaled, 130.3 MB to 26.7 MB, 135 of them drawings given a palette. Without the palette, 77 of those drawings' copies had come out larger than their originals and were kept, and the other 58 drawings' copies came to 5.4 MB, where they're 1.5 MB now. Against the same copies in full color, the worst is 42.5 dB (PSNR), and three times its size on screen showed no difference. At 4, 65 of 73 were scaled, 89.2 MB to 34.0 MB, 45 of them drawings, and 8 were kept: two photographs and a diagram of more than 4,096 colors, and five drawings less than five times as wide as they're shown, whose copies have nearly as many pixels as they do. At 2, its EPUB came to 41.6 MB, its zip of Word files 47.0 MB, and its PDF 54.2 MB, where they had been 142, 155, and 165 with every image whole. The suites check that an html target, an EPUB, a Word file, and a PDF carry a copy, that a drawing's copy has a palette, its transparency kept, and a photograph's doesn't, that a JPEG is written at a level's quality, scaled or at its own size, and one saved at a lower quality left as it is, and that the original and a `markdown` target's copy don't change.

### Math

Three repairs, each on unless turned off, and each recorded row by row in `math-repaired.csv` (its kind, the page, and the text before and after).

**An equation's characters.** Word's equation editor lets an author type a character that looks right and means something else, and a screen reader reads the one that's there: the micro sign `µ` for the Greek `μ`, the increment sign `∆` for `Δ`, an en dash for a minus (read as "en dash"), a bar over x written as an en dash or a macron set above it, `ŷ` as one precomposed character rather than y with a hat, a middle dot `·` for the product's dot operator `⋅`, and `H` with a slashed `Ø` for the null hypothesis's `H₀`. Each has one right form, and `math.repair_equations` writes it. Text inside an equation (`\text{}` in TeX, normal or literal text in Word's equation editor) gets `μ` and `Δ`, and a minus sign for an en dash where the text is math: a number's sign (`\text{–1}`), a charge's, a difference (`\text{16 – 2P}`, as the economics textbook, a draft written in Markdown, types its equations), and a text that's the dash alone, with space, is the operator itself. An en dash stays a dash between two letters (a bond, `H–Cl`), between two digits (a range), beside another dash, and in a text set under or over something as its mark (`\underset{\text{–}}{x}`). A `ŷ` or a middle dot in text stays as typed, since text can't hold the command that would replace it. A Word source's `format: source` copy decides its equations' text as Pandoc reads it, runs side by side as one text, so the copy reads back as the page does. The statistics textbook, OpenStax's *Introductory Business Statistics 2e*, has several hundred; some of them (µ, ŷ, Ø) are also characters no math font in LaTeX maps, so its PDF had dropped them.

**Math typed as text.** Some books type math as ordinary text rather than as an equation: italic letters, Greek letters, sub- and superscripts, and `=` or `<` between them. It reads right on screen, but a screen reader gets `σ²` as "sigma 2", and a PDF's text font may have no Greek. `math.from_text` makes an equation of it, conservatively:

- an expression needs a relation (`=`, `≠`, `<`, `≤`, `>`, `≥`, `≈`, `~`) with an operand at each end and at least one variable, an italic letter or a Greek one: `μ = 34`, `P(x ≤ 160) = 0.3`, `Z ~ N(0, 1)`. A plain letter is a word and ends the expression, except one right before a parenthesis, a function's name (`P` in `P(x ≤ 160)`), and one right before a sub- or superscript, the letter it's set on (`H` in `H₀: σ₁² = σ₂²`), though that's no symbol on its own (`H₂O` stays text), nor is a formula whose script runs into a letter (`2H₂ + O₂ = 2H₂O`). A comma and a space end it too, outside parentheses, so `μ = 5.51, s = 2.15` is two equations, and so do a colon and a space before any variable, a label's: in `Plan 1: n₁ = 4` the equation is `n₁ = 4`, where in `H₀: μ = 34` the colon is the equation's. A run that stops short of its formula, followed straight away by an opening parenthesis or a letter, stays text: `F = MS(Factor)/MS(Error)` isn't `F = MS` and text, and `x = 3cm` isn't `x = 3`; a picture straight after a run isn't a letter, its description not being in the line. A symbol in such a run is still a symbol on its own (below): in `sₚ = 3cm`, `sₚ` is math and the rest text.
- a letter with a hat or a bar, `ŷ` or `x̄`, typed as the letter and the combining mark or as one precomposed `ŷ`, is a variable, and a symbol on its own; and a script after it typed as TeX types one, `x̄_n`, is its script. A run holding one is math, as no plain letter is, so the plain letters in it, one or two after an operator, a relation, or a number's digits and before an operator, a relation, or the run's end, are variables too: `ŷ = a + bx` and `ŷ = 2x + 1` are equations, where `a + b = c` stays text. A letter with a hat in a word (`crêpe`) is the word's. OpenStax's statistics decks type both in their notes ("the regression line ŷ = a + bx", "the running average (x̄_n)"). Read by NVDA, each is read as it's meant as math, and not as text (checked by hand, 2026-10-24).
- a symbol on its own is a Greek letter (`μ`), a letter with a hat or a bar, or an italic letter with a sub- or superscript (`H₀`, `σ²`).
- left alone: a lone italic letter (outside a statistics book it's mostly emphasis or an initial), numbers with no variable (`3 < 5`, a year range), anything cut off at a relation (`A =` before a set in braces), and an ordinal's superscript (the *th* of *n*th).

Measured before it was written: on the statistics textbook, 1,175 expressions and 457 symbols, and in samples every one was math; on 771 files of six other books from the test corpus, three expressions (nursing's dosage formulas) and two symbols.

**An en dash in text for a minus sign.** OpenStax's books write a negative number, and a subtraction, in running text with an en dash rather than a minus sign: a balance of –$922.0, a slope of –1.5, 1 – 0.05 = 0.95. NVDA doesn't say an en dash at its default punctuation level ("some"; its `symbols.dic` puts the en dash at "most"), so –1.5 is heard as 1.5, and it reads one between two numbers as a range: on section 23.1 of Principles of Economics 3e, NVDA read a subtraction's en dash as a range and said nothing for a negative sign's, and it read a minus sign (U+2212) in text as "minus" (checked by hand, 2026-11-06). `math.minus_in_text` makes an en dash outside an equation a minus sign where a range's dash can't be:

- a sign before a number: at the start of a paragraph or of a superscript (10<sup>–4</sup>); after an opening parenthesis or bracket, a relation or an operator, a currency sign, a quotation mark, or a part's circled letter (`(–3, –2)`, `$–5`, `“–1”`, `ⓒ–8`); after a comma, a semicolon, a colon, or a full stop and a space, as in a list of values or a numbered answer (`{0.2, –4.1, –1.6}`, `75. –66.4 kJ`); or after a word and a space (`a slope of –1.5`), but not after a number or a unit, where it's a range's (`24 °C –29 °C`).
- a dash between two numbers in a run of arithmetic that holds a relation (`=`, `<`, `>`, `≈`, `≠`, `≤`, `≥`), or that "equal to" or "equals" opens: `1 – 0.05 = 0.95`, `df = n – 1 = 5 – 1 = 4`, `P = 48 – 3Q`, `($20 billion – $40 billion) = $3,030`, `is equal to $1,046 – $1,562`; and the sign after a relation or an operator in one, with a space after it or not (`$28–$40= –$12`, `r = – 0.2752`). A run is numbers, operators, relations, currency signs, formulas, a number and the letters it multiplies (`3Q`), a quantity's word (`billion`, `percent`), a number's degree sign (`90° – 23° = 67°`), and a lone letter, a variable (`df = n – 1`, `q = 1 – p`), but not a part's label (`(b)`), up to a comma, a semicolon, a colon, or a full stop that ends a clause; the words before a run's first dash are what it subtracts from (`the number of cells – 1 = 4`).
- left alone: a range, spaced or not (`1990–2000`, `pages 3–5`, `(1943 – 2020)`, `$50,000 – $68,999`, `ages 13 – 55+`), and one of whole numbers, the smaller first, after a relation with nothing after it (`n = 2 – 5`); a dash between primes (`5′–3′`), between a word or a letter and a number (`word–5`, `x–1`), or before a word; a dash with a space after it, past a word, which is a sentence's dash as often as a sign (`False – 50 percent of the data`, `runs from – 5 to 5`); a difference no relation follows (`400 – 320, or 80`); code; and an equation's own text (`\text{}`), which the repairs of an equation leave as a dash.

A picture's description gets the same signs, a screen reader reading it as it reads text. Measured before it was written, on ten OpenStax books (the pages of a Principles of Economics 3e and an Introductory Business Statistics 2e run, and the pages the CNX unpacker makes of Astronomy 2e, Biology 2e, Chemistry 2e, College Algebra 2e, Intermediate Algebra 2e, Physics, Principles of Financial Accounting, and Statistics), it made 2,166 minus signs: 793 in Chemistry 2e, 574 in Statistics, 234 in Physics, 183 in College Algebra 2e, 169 in Principles of Economics 3e, 128 in Introductory Business Statistics 2e, and 8 to 51 in each of the others. Every difference it made written with spaces, 277 distinct ones, was a subtraction. Of the en dashes it left beside a number in text, nearly all are ranges; the signs among them have a space after them, past a word (`the image is – 2.00 cm`), or follow a formula, and the subtractions no relation after them (`n – 1 degrees of freedom`, `($8,000 – $1,500 – $120)`) or an operand a run doesn't take (`(r – 1)(c – 1)`, `(°F – 32)`).

```yaml
# in conversion.yaml, to turn any of them off
defaults:
  math:
    repair_equations: false
    from_text: false
    minus_in_text: false
```

To keep one change from happening, when it isn't the math it looks like, copy its row from `math-repaired.csv` into `math-keep.csv` ([Sidecars](sidecars.md#math-kept-as-it-was)); the settings above turn a whole kind off.

For a Word source, `format: source` writes all three into the author's copy. `math.repair_equations` repairs the file's own equations, as Word's equation structures, each the one Pandoc writes for the TeX the pages get, except the bar. Pandoc writes `\bar` as an accent whose character is an overline (U+203E), which Narrator read as nothing in Word, and which LibreOffice 24.2 draws as an acute accent, so a bar is an accent of the macron (U+00AF): Narrator read it as "cap X overbar" and NVDA, with MathCAT, as "X bar", and LibreOffice reads and writes it as its own bar accent. Pandoc's reader takes the macron for `\overline`, so reading a Word file the pipeline gives such an accent the overline first, and the copy reads back as the pages have it, `\bar`; Pandoc alone reads it as `\overline`. `math.from_text` replaces the runs of math typed as text with Word's equation for it, as Pandoc writes one: the filter records each equation's paragraph (its text, with an equation already there as a placeholder), and the copy's paragraph with that text gets it, a run the equation begins or ends inside split with its formatting kept on both sides. What doesn't map exactly is left and counted: a paragraph with a tracked change, a field, or a text box, and an equation that would cross a link's edge or take in a note reference or a picture. `math.minus_in_text` makes each en dash a minus sign in the run of text that holds it, its formatting kept, the paragraph found by its text as for an equation, and in a picture's description, the image-alt sidecar's or its own, the picture found by the file it embeds. On the statistics textbook: 1,641 equations made of text and 5 left, and 443 equations repaired; read back as a book, 168 of the copies' 169 pages give the same HTML as the originals do (the TeX a formula keeps beside its MathML aside), and the other differs only in how a table's headers are guessed, since its header row now holds equations. A PowerPoint deck's copy gets `math.repair_equations` and `math.minus_in_text`, and makes no equation of text ([Slides](slides.md#the-copy)).

## Editions

Two editions of a book usually differ in a page or a passage, not in the book, and neither difference needs a second source directory or a build system.

**A variant file** replaces a page for one target: `about.print.md` stands in for `about.md` when the target named `print` is built, and `about.md` serves every other target. The same works for `.docx` and for `.html`, a source or a page in the pass-through directory. The page keeps its name (`about`), so `contents`, links, and sidecars don't know which file produced it, and a target with a variant gets intermediates of its own.

**A passage for some targets**, in Markdown, is a fenced div naming them; it is unwrapped where it applies and dropped elsewhere, and the attribute never reaches the output:

```markdown
::: {targets="epub print"}
This edition was checked with epubcheck.
:::

::: {targets="!web"}
Prefer the web edition with a screen reader.
:::
```

Names keep; `!name` excludes; a list of only exclusions keeps by default. A span takes the same attribute for a phrase. An HTML source says the same with `data-targets` on a `<div>` or a `<span>` (`<div data-targets="epub print">`), which Pandoc reads as that attribute. Word sources have no such markup, by design.

**The title block.** A source's opening page carries the document's subtitle, date, abstract, and `include-before`, which the page template renders under its title: that is its title page. `title_block: off` on a target leaves them out, for an author laying the front matter out by hand. A page's title itself is its own H1 in every output ([A page's title](formats.md#a-pages-title)), and an EPUB's or a PDF's title page follows the book's structure (`title_page`).

## Upgrading from v0.4

Two changes alter what a run writes, so a directory converted with v0.4 looks different after its first v0.5 run.

**Pages go into `html/`.** Nothing writes beside the sources any more. The pages v0.4 left there are named once on stderr as being from an earlier run and left alone; delete them when you're satisfied, or set `output_dir: .` on the HTML target to keep the old layout. The packager reads `html/` (`--pages`), and its configuration, manifest, and archive stay in the content directory. Sidecars and reports don't move.

**A page name with a space changes.** `01 BigPicture.docx` used to be the page `01 BigPicture`; it is `01-BigPicture` now, because an LMS takes a link literally and a space in it never resolved. `contents` entries and `page-names.csv` rows naming such pages need the new spelling; nothing else does.

Two things are additive and change nothing unless you ask: `role`, `numbering`, and `generate: toc` in `contents`, and the footnote and edition settings. The `convert.sh` wrapper is gone; `convert.py` takes the same arguments and does the same steps.

## Migrating a v0.1 configuration

`imsmanifest.yaml`, version 0.1's one configuration file, is no longer read. Conversion and packaging both stop with directions rather than ignoring it, because a config that looks live and isn't is worse than none.

```bash
python3 /path/to/tools/util/migrate-config.py -d . --dry-run   # show the plan
python3 /path/to/tools/util/migrate-config.py -d .             # do it
```

It prints where every setting lands, lists anything it has no home for rather than dropping it, refuses to overwrite a file you may have edited, and never touches the original. Check the three new files, then delete the old one.

Two settings change shape rather than moving:

- `images.spacer_log` becomes `reports.spacer_images`, alongside the other report filenames.
- `manifest.cartridge` becomes a package's `filename`, because a configuration can now describe more than one package.

Sidecar files need no migration. `image-alt.csv` keys are unchanged, and `table-captions.csv` entries written against a position key such as `2-practice#table-18` still apply even where v0.2 now finds the table's real label.
