# Configuration

How `packaging.yaml`, `conversion.yaml`, and `project.yaml` fit together, how a value is settled when several files could supply it, and the parts of the configuration that are structure rather than settings. The settings themselves are listed, one per line with its default and description, in three pages generated from the schemas: [project settings](project-settings.md), [conversion settings](conversion-settings.md), and [packaging settings](packaging-settings.md).

## Configuration

Three files, split by what a setting describes rather than by which script
reads it.

| File | Holds | Read by |
|---|---|---|
| `project.yaml` | Facts about the book: its language, identifier, title, and structure. | both halves |
| `conversion.yaml` | How the book is rendered into an output format. | conversion |
| `packaging.yaml` | How rendered files are assembled into an archive. | packaging |

Every setting is declared in a schema — `lib/schema-project.yaml`,
`bin/schema-conversion.yaml`, `bin/schema-packaging.yaml` — which gives its
type, its default, and a sentence saying what it means. The schema is the
only description: the readers, the validator, the generated sample files,
and this document all derive from it, so there's no second list to drift
out of step with the first.

### Samples

Each file has a sample written from its schema: every setting with its
description, at the value the file gives it or else the default, so a
sample renamed over its file loses nothing set there. With `T` the
directory the tools are in, run in the book's directory:

| Sample | Written by | Rename it to |
|---|---|---|
| `project-sample.yaml` | a run, when nothing names the book; and `build-cartridge.py -d . --pages html --init`, when nothing names the book and no run has written one | `project.yaml` |
| `conversion-sample.yaml` | `python3 $T/bin/read-conversion-config.py -d . --init` | `conversion.yaml` |
| `packaging-sample.yaml` | `python3 $T/bin/build-cartridge.py -d . --init` | `packaging.yaml` |

A run also writes `project-sample.yaml` for review when it worked out the
contents itself: guessed from the file names, taken from a master file's
order, or read from an outline with `--toc`. `--pages` names the directory
the pages are in, `html/` unless an HTML target says otherwise, which
`--init` needs only for the contents it guesses into a project sample.
[Project settings](project-settings.md), [conversion
settings](conversion-settings.md), and [packaging
settings](packaging-settings.md) list the same settings.

### Where the book is named

`project.yaml` names the book for both halves: its identifier, title,
language, and contents. `conversion.yaml` and `packaging.yaml` may each
carry a `project:` block instead, read by that file's half alone, which is
all a book that uses one half needs:

- A book named in `packaging.yaml`'s block alone gets its cartridge. An
  EPUB, a PDF, or a LaTeX target can't see that name, so it isn't written,
  and the run says to name the book in `project.yaml` or in
  `conversion.yaml`'s block too.
- A book named in `conversion.yaml`'s block alone gets its EPUB and its
  pages. With no `packaging.yaml` either, it isn't packaged, and the run
  says so and isn't an error; with a `packaging.yaml` that doesn't name
  it, packaging stops, and its `project-sample.yaml` carries the block's
  values.
- A book named in both blocks gets everything, and the run notes that
  `project.yaml` would say it once.

However many files describe the book, they have to agree. A setting given
two different values, in `project.yaml` and a block or in the two blocks,
stops the run before anything is converted, naming both files; a setting
given in one file and not another is just given.

### Required settings

Two have no useful default: `project.identifier` and `project.title`.
With neither `project.yaml` nor a `project:` block in `packaging.yaml`,
packaging writes `project-sample.yaml` and stops; a `project.yaml` that
leaves either one at its default (`book`, `Untitled`) is warned about. A
target that writes a book, an EPUB, a PDF, or a LaTeX master, needs the
title too. With none configured, it takes the title a master file gives,
an AsciiDoc master's `=` line or a LaTeX master's `\title` (not the first
of several documents `latex.main` lists), or a book of one page takes that
page's, and the run says so; a PDF whose `pdf.metadata` file has a title,
and a LaTeX book's PDF from its own build (`pdf.from: book`), are titled as
those say. With nothing to take it from, or with the title only in
`packaging.yaml`, that target isn't written, the run says where the title
goes, and it ends in an error once the other targets are written.

`identifier` is worth care. Brightspace matches on it when re-importing,
so changing it duplicates a course rather than updating it. Keep it stable
across rebuilds, and change it only when the book is genuinely a different
book.

### Targets

Both `conversion.yaml` and `packaging.yaml` have the same shape: a
`defaults:` block, then a `targets:` block naming one or more things to
build. A target inherits the defaults and overrides what it needs.

```yaml
defaults:
  promote_h1_to_title: always

targets:
  html:
    format: html
```

Every target is built, each into its own `output_dir`, named after the
target unless it says otherwise: `html/` for the one implied when no
configuration exists, and several HTML renderings with different
headers, footers, or options, an EPUB, and whatever else the schema's
`format` lists when they're declared: `html`, `epub3`, and `markdown`
build today. The content directory keeps the sources, the
intermediates, the sidecars, and the reports. A page you wrote by hand
(an `.html` there with no source behind it) is copied into every HTML
target with the local files it refers to, and read into an intermediate
so the EPUB has it too. Two targets whose settings that
change the filtered intermediate agree (the schema marks these `stage:
filter`; images, tables, captions, the split, the sidecars) share one
intermediate; a target that differs gets its own under its output
directory. Settings that only change how a target writes (`header`,
`footer`, `output_dir`) or assemble a book (`epub.*`) cost nothing to
vary. The packager reads the first HTML target's directory; a package
whose `includes` name another is on the roadmap. `output_dir: .` keeps
the layout earlier versions used, pages beside the sources.

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

A target can also decide `title_block`, `numbering`, and the footnote
settings for itself; the [conversion settings](conversion-settings.md)
reference says which settings are a target's and which are the book's.

### How values are settled

Four layers, in this order: the schema's default, the `project:` block,
the file's `defaults:` block, then the target's own block. Five rules
govern the rest, kept few on purpose:

- The schema decides what nests. A section merges key by key; anything
  else is replaced whole.
- Lists replace. They never append.
- An explicit `null` clears an inherited value back to the schema default.
  An absent key inherits.
- No coercion happens during the merge; each resolved value is checked
  once at the end against its declared type.
- An unknown key is an error, with a suggestion if one is close, and
  where it went if an earlier version had it or where it belongs if it's
  another block's setting (`version` is packaging.yaml's). Pass
  `--allow-unknown-keys` to report and ignore them instead, which is for
  reading a config written for a newer version of the tools.

Two kinds of setting have a place of their own. One that has to differ
between targets, such as `format` and `output_dir`, is an error in
`defaults:`. One the whole book shares, the `sidecars:` and `reports:`
paths, is an error in a target: they're read once, for the whole book, so
in a target they'd apply everywhere or nowhere depending on the order of
the targets. Set them under `defaults:`.

### Two YAML traps

Both bite in this configuration specifically, and both are now caught
rather than silently accepted.

**`language: no` is the boolean false.** YAML reads unquoted `no`, `yes`,
`on`, and `off` as booleans, so Norwegian becomes `False`. There's no way
to recover which word was written, so it's refused. Quote it.

**`version: 1.10` is the number 1.1.** The trailing zero is gone before
any program sees it. Quote it.

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

A group is a container only. In Common Cartridge an item pointing at a page
should be a leaf, so a unit with its own introduction lists that page as
its first child rather than pointing at it directly. Three levels of
nesting are supported; deeper is accepted with a warning, since LMS support
for deep hierarchies is uneven.

A group or page can carry a `role`: `front`, `main` (the default),
`appendix`, or `back`. It says what part of the book the entry is, which
a group's pages inherit. With `numbering: true` on the project, the
book counts the way a printed one does: main groups and top-level pages
1, 2, 3 and their pages 1.1, 1.2; appendices A, B and A.1; front and
back matter unnumbered, a chapter's own opening page taking the
chapter's number. The numbers show in the EPUB's table of contents and
headings, the cartridge organization, the generated contents page, and
each page's own heading and `<title>`; a target can say `numbering: on`
or `off` for itself. A Markdown book
written for a Pandoc PDF build declares its parts already, with
`\frontmatter`, `\mainmatter`, `\appendix`, `\backmatter`, and
`{.appendix}` on a heading, and the guess reads those, so the sample
comes out with the roles in place.

A role says where an entry sits in the book, not where it goes: the
order is the order of `contents`, and only a top-level entry's role
counts, for numbering, the PDF's divisions, and the EPUB's. A page inside
a chapter is in the chapter's part of the book whatever its own role.

A group or page can also carry a `type`, what it is: `preface`,
`foreword`, `dedication`, `epigraph`, `acknowledgments`, `prologue`,
`abstract`, `introduction`, `copyright-page`, `part`, `chapter`,
`conclusion`, `epilogue`, `afterword`, `appendix`, `bibliography`,
`glossary`, `index`, or `colophon`, as EPUB's structural semantics name
them. The EPUB marks it on the entry's section with its ARIA role and
names a book-level bibliography, glossary, or index in its landmarks
([Building an EPUB](epub.md#what-goes-in-and-in-what-order)). A type
isn't inherited, since a chapter isn't a glossary because its Key Terms
page is one, and a top-level entry with no `role` is in the part of the
book its type implies: a glossary page at the end needs `type: glossary`
and not `role: back` too, and it's unnumbered as back matter is. A
type on a page that a split cut into pieces, or on a group's opening
page (titled as the group is), is the group's: the glossary its pieces
make up. A
Markdown heading can mark a page the same way (`# Preface
{epub:type=preface}`, or `{.glossary}`), which the EPUB marks too, but
where the page sits is still what `contents` says, read alike by
numbering, the PDF, the cartridge, and the EPUB; a Word heading can't say
it at all, which is what `type` is for, and `contents` outranks a heading.
A LaTeX book's sample gives the bibliography page the run writes out
`type: bibliography`, at the top level after any parts and appendices.
A guessed `contents`, and one ordered from an outline with `--toc`,
gives a type to each page whose title names what it is: Preface,
Foreword, Dedication, Epigraph, Acknowledgments, Prologue, Epilogue,
Afterword, Abstract, Colophon, and Copyright; Glossary and Key Terms
(`glossary`); Bibliography, References, and Works Cited
(`bibliography`); Index; and an Appendix by its title's first word. So
an OpenStax chapter's Key Terms is a glossary and its References a
bibliography, and the preface and index are front and back matter by
their types, with no `role` beside them. An Introduction or a
Conclusion is as often a chapter's section as the book's, and isn't
guessed; nor is a part or a chapter, which the groups already say.

An entry `generate: toc` is a page the run writes: the full table of
contents as a nested list of links, numbered when the book is, placed
wherever it sits in `contents`. It's named `toc` and titled `Contents`
unless `name` and `title` say otherwise.

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

A page cut by `pages.split_level` is listed by its piece name,
`chapter-7--economies-of-scale`; see [Splitting pages](splitting.md).

Omit `contents` and the order is guessed from the filenames — natural sort,
so chapter 10 doesn't land between chapters 1 and 2, plus chapter grouping
when the filenames encode it. `--includeallhtml` groups the pages it
appends the same way.

Chapters are detected by shape, not vocabulary: a numeric prefix
(`12-3-the-f-distribution`, `12-key-terms`) or a `chapter-12` opener page,
whose own `<title>` becomes the group heading. Within a chapter the order
is opener, introduction, numbered sections, then back matter in the order
set by `grouping.back_matter`. A role name not in that list sorts after the
ones that are, and is reported rather than silently misplaced. A chapter
that is one file (`01 BigPicture.md`, a book written a file per chapter) is
that file, with no group heading over it, and a page read as an appendix
keeps that role. The guess is written to
`project-sample.yaml` for you to correct. It's a starting point, not a
finished book.

### Header and footer

Injected into every page, as the first and last thing in `<body>`. Either
inline Markdown or the name of a Markdown file:

```yaml
# in conversion.yaml
defaults:
  footer: |
    *Your Textbook Here* is licensed
    [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
```

The fragment is inserted after the Pandoc filter has run, so nothing in it
is processed — no alt checking, no spacer rule. Write its markup correctly
by hand, and list any images it uses under `common_files`.

### Caption labels

```yaml
# in conversion.yaml
defaults:
  captions:
    table_prefixes: [Table, Figure, Exhibit]
    figure_prefixes: [Figure]
```

The words that introduce a caption. One book here labels every table
`Figure 1.1`, and with the default of `Table` alone those tables got no
caption. Listing `Figure` under `table_prefixes` is safe: which rule
applies is decided by what the table contains, not by the word.

### Shared files

```yaml
# in packaging.yaml
defaults:
  common_files:
    - shared/banner.png
    - shared/course.css
```

Files used by more than one page. They are declared once in a
`common_files` resource that every page depends on, instead of being
repeated in each page's file list.

Files a page references on its own are found automatically and don't
belong here. This list is for files you want shared, and for anything
reached from the header or footer — the page scan sees those on every page
and can't attribute them to one.

Common Cartridge `<dependency>` support varies between systems. Test a
small cartridge before relying on it; removing `common_files` falls back to
per-page entries.

### Spacer images

Word documents often use a tiny transparent GIF as a bullet. One book here
had 274 of them across 487 images.

```yaml
# in conversion.yaml
defaults:
  images:
    spacer_below: 0.3       # inches; anything narrower is a spacer, 0 disables
    strip_spacer: true      # true removes them, false marks them decorative
  reports:
    spacer_images: spacer-images.csv
```

With the rule off, suspected spacers are still counted and reported so the
setting is discoverable. Images with no readable width can't be judged and
are reported separately.

```yaml
# in conversion.yaml
defaults:
  images:
    alt_max_chars: 120
```

Alt text longer than this is reported for shortening. It's a length at
which a short equivalent has become a long description, and long
descriptions belong in the prose where every reader gets them. Raising it
silences the report rather than fixing anything.

### Math

Two repairs, both on unless turned off, and both recorded row by row in `math-repaired.csv` (its kind, the page, and the text before and after).

**An equation's characters.** Word's equation editor lets an author type a character that looks right and means something else, and a screen reader reads the one that's there: the micro sign `µ` for the Greek `μ`, the increment sign `∆` for `Δ`, an en dash for a minus (read as "en dash"), a bar over x written as an en dash or a macron set above it, `ŷ` as one precomposed character rather than y with a hat, a middle dot `·` for the product's dot operator `⋅`, and `H` with a slashed `Ø` for the null hypothesis's `H₀`. Each has one right form, and `math.repair_equations` writes it. Text inside an equation (`\text{}` in TeX, normal text in Word's equation editor) gets only `μ` and `Δ`: an en dash there is a dash, and a `ŷ` or a middle dot stays as typed, since text can't hold the command that would replace it. The statistics textbook has several hundred; some of them (µ, ŷ, Ø) are also characters no math font in LaTeX maps, so its PDF had dropped them.

**Math typed as text.** Some books type math as ordinary text rather than as an equation: italic letters, Greek letters, sub- and superscripts, and `=` or `<` between them. It reads right on screen, but a screen reader gets `σ²` as "sigma 2", and a PDF's text font may have no Greek. `math.from_text` makes an equation of it, conservatively:

- an expression needs a relation (`=`, `≠`, `<`, `≤`, `>`, `≥`, `≈`, `~`) with an operand at each end and at least one variable, an italic letter or a Greek one: `μ = 34`, `P(x ≤ 160) = 0.3`, `Z ~ N(0, 1)`. A plain letter is a word and ends the expression, except one right before a parenthesis, a function's name (`P` in `P(x ≤ 160)`). A comma and a space end it too, outside parentheses, so `μ = 5.51, s = 2.15` is two equations.
- a symbol on its own is a Greek letter (`μ`), or an italic letter with a sub- or superscript (`H₀`, `σ²`).
- left alone: a lone italic letter (outside a statistics book it's mostly emphasis or an initial), numbers with no variable (`3 < 5`, a year range), anything cut off at a relation (`A =` before a set in braces), and an ordinal's superscript (the *th* of *n*th).

Measured before it was written: on the statistics textbook, 1,175 expressions and 457 symbols, and in samples every one was math; on 771 files of six other books from the test corpus, three expressions (nursing's dosage formulas) and two symbols.

```yaml
# in conversion.yaml, to turn either off
defaults:
  math:
    repair_equations: false
    from_text: false
```

To keep one change from happening, when it isn't the math it looks like, copy its row from `math-repaired.csv` into `math-keep.csv` ([Sidecars](sidecars.md#math-kept-as-it-was)); the settings below turn a whole kind off.

For a Word source, `format: source` writes both into the author's copy. `math.repair_equations` repairs the file's own equations, as Word's equation structures. `math.from_text` replaces the runs of math typed as text with Word's equation for it, as Pandoc writes one: the filter records each equation's paragraph (its text, with an equation already there as a placeholder), and the copy's paragraph with that text gets it, a run the equation begins or ends inside split with its formatting kept on both sides. What doesn't map exactly is left and counted: a paragraph with a tracked change, a field, or a text box, and an equation that would cross a link's edge or take in a note reference or a picture. On the statistics textbook: 1,641 equations made of text and 5 left, and 443 equations repaired; read back as a book, 168 of the copies' 169 pages give the same HTML as the originals do (the TeX a formula keeps beside its MathML aside), and the other differs only in how a table's headers are guessed, since its header row now holds equations.

## Editions

Two editions of a book usually differ in a page or a passage, not in
the book, and neither difference needs a second source directory or a
build system.

**A variant file** replaces a page for one target: `about.print.md`
stands in for `about.md` when the target named `print` is built, and
`about.md` serves every other target. The same works for `.docx` and
for a hand-written `.html`. The page keeps the stem, so `contents`,
links, and sidecars don't know which file produced it, and a target
with a variant gets intermediates of its own.

**A passage for some targets**, in Markdown, is a fenced div naming
them; it is unwrapped where it applies and dropped elsewhere, and the
attribute never reaches the output:

```markdown
::: {targets="epub print"}
This edition was checked with epubcheck.
:::

::: {targets="!web"}
Prefer the web edition with a screen reader.
:::
```

Names keep; `!name` excludes; a list of only exclusions keeps by
default. A span takes the same attribute for a phrase. Word sources
have no such markup, by design; an HTML source, when HTML is an input
format, will take Jinja's block syntax for the same thing.

**The title block.** A source's opening page carries the document's
subtitle, date, abstract, and `include-before`, which the page
template renders under its title: that is its title page. `title_block:
off` on a target leaves them out, for an author laying the front matter
out by hand. A page's title itself is its own H1 in every output
([A page's title](formats.md#a-pages-title)), and an EPUB's or a PDF's
title page follows the book's structure (`title_page`).

## Upgrading from v0.4

Two changes alter what a run writes, so a directory converted with v0.4
looks different after its first v0.5 run.

**Pages go into `html/`.** Nothing writes beside the sources any more.
The pages v0.4 left there are named once on stderr as being from an
earlier run and left alone; delete them when you're satisfied, or set
`output_dir: .` on the HTML target to keep the old layout. The
packager reads `html/` (`--pages`), and its configuration, manifest,
and archive stay in the content directory. Sidecars and reports don't
move.

**A page name with a space changes.** `01 BigPicture.docx` used to be
the page `01 BigPicture`; it is `01-BigPicture` now, because an LMS
takes a link literally and a space in it never resolved. `contents`
entries and `page-names.csv` rows naming such pages need the new
spelling; nothing else does.

Two things are additive and change nothing unless you ask: `role`,
`numbering`, and `generate: toc` in `contents`, and the footnote and
edition settings. The `convert.sh` wrapper is gone; `convert.py` takes
the same arguments and does the same steps.

## Migrating a v0.1 configuration

`imsmanifest.yaml` is no longer read. Both halves stop with directions
rather than ignoring it, because a config that looks live and isn't is
worse than none.

```bash
python3 /path/to/tools/util/migrate-config.py -d . --dry-run   # show the plan
python3 /path/to/tools/util/migrate-config.py -d .             # do it
```

It prints where every setting lands, lists anything it has no home for
rather than dropping it, refuses to overwrite a file you may have edited,
and never touches the original. Check the three new files, then delete the
old one.

Two settings change shape rather than moving:

- `images.spacer_log` becomes `reports.spacer_images`, alongside the other
  report filenames.
- `manifest.cartridge` becomes a package's `filename`, because a
  configuration can now describe more than one package.

Sidecar files need no migration. `image-alt.csv` keys are unchanged, and
`table-captions.csv` entries written against a position key such as
`2-practice#table-18` still apply even where v0.2 now finds the table's
real label.
