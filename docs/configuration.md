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
    output_dir: .
```

`convert.sh` renders the pages from the one `html` target, and an
`epub3` target beside it is built by `build-epub.py` (see [Building an
EPUB](epub.md)); the two are told apart by `format`. The shape allows
more than that because there will be more: a print PDF alongside a
screen one, each needing its own settings and its own output directory.

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
