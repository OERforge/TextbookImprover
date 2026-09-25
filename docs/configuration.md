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

To see every setting with its documentation, generate a sample:

```bash
python3 /path/to/tools/bin/build-cartridge.py -d . --init
```

`project.yaml` is optional. Both other files may carry a `project:` block
inline, so a directory holding only a conversion config still stands on
its own. Declare it in one place or the other; declaring it in both means
one copy goes stale, and the tools warn when the two disagree.

### Required settings

Two have no useful default: `project.identifier` and `project.title`.
Without them the build writes a sample and stops.

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
- An unknown key is an error, with a suggestion if one is close. Pass
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
    role: back
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
ones that are, and is reported rather than silently misplaced. The guess is written to
`packaging-sample.yaml` for you to correct. It's a starting point, not a
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
template renders: that is its title page. `title_block: off` on a
target leaves them out, for an author laying the front matter out by
hand.

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
