# TextbookImprover

Converts a directory of Word documents into more-accessible HTML pages and packages them as an IMS Common Cartridge for import into Brightspace or another LMS.

Licensed GPL 3.0. See `LICENSE` for more info.

The initial release of these scripts was created by Robert Szarka and supported by a grant from the West Virginia Higher Education Policy Commission.

## The pieces

The project has two halves that no longer depend on each other. Conversion
turns source documents into accessible pages; packaging assembles pages
into something an LMS can import. Either is useful alone — remediating a
folder of documents needs nothing from the cartridge side, and building a
cartridge from pages this project never converted needs nothing from the
conversion side.

**`bin/` — conversion**

| File | What it does |
|---|---|
| `convert.sh` | Runs the pipeline: DOCX → JSON → HTML, then optionally hands off to the packaging side. |
| `figures-and-tables.lua` | Pandoc filter doing the accessibility work on each page. |
| `media-extensions.lua` | Pandoc filter naming extracted images by their real content type. |
| `read-conversion-config.py` | Resolves `conversion.yaml` into settings `convert.sh` reads. |
| `schema-conversion.yaml` | Declares every conversion setting, its type, default, and meaning. |

**`bin/` — packaging**

| File | What it does |
|---|---|
| `build-cartridge.py` | Builds `imsmanifest.xml` and, optionally, the `.imscc` archive. |
| `validate-manifest.py` | Checks a manifest against the Common Cartridge 1.1 schemas. Run automatically. |
| `schema-packaging.yaml` | Declares every packaging setting. |

**`schemas/cc11/`** holds the IMS Common Cartridge 1.1 schemas, unmodified
and redistributed under their own terms. See the README there.

**`lib/` — shared**

| File | What it does |
|---|---|
| `oerconfig.py` | Loads, merges, validates, and writes configuration. Both halves use it; neither uses the other. |
| `schema-project.yaml` | Declares the settings that describe the book itself, which both halves read. |

**`util/` — tools you run occasionally**

| File | What it does |
|---|---|
| `migrate-config.py` | One-time: splits a v0.1 `imsmanifest.yaml` into the three v0.2 files. |
| `manifest-to-yaml.py` | One-time: turns an existing `imsmanifest.xml` into `project.yaml` and `packaging.yaml`. |
| `untrack-deletions.py` | One-time source repair: turns Word tracked deletions into ordinary strikethrough. |
| `compare-output.py` | Compares two runs semantically, so a pipeline change can be checked rather than trusted. |
| `table-census.py` | Surveys table structure across a corpus of DOCX files. |

**`tests/`** holds the configuration conformance fixtures and the two test
runners. See [Testing](#testing).

## Requirements

| Tool | Needed for | Install |
|---|---|---|
| `pandoc` | Everything. Version 3.9 or later. | `sudo apt install pandoc` |
| `file` | Detecting real image types | usually present |
| `python3` | Required, 3.9 or later. Reads the configuration and inspects conversion intermediates. | usually present |
| PyYAML | Reading configuration | `sudo apt install python3-yaml` |
| `lxml` | Optional. Full schema validation of the manifest; without it a smaller set of checks runs. | `sudo apt install python3-lxml` |
| `pypdf` | `--toc` only | `pip3 install pypdf` |
| `zip` | Only if you package with the printed command instead of `--zip` | `sudo apt install zip` |

Pandoc 3.9 is a hard requirement, checked before any work starts. Earlier
versions accept most of the command line and quietly do something else:
3.6 and older write tables without cell spans, so a table with merged
cells loses them with no warning at all.

Pandoc versions still differ in ways that show up here — newer releases
read Word caption paragraphs into table captions, older ones do not — so
the same document can produce different reports on different machines.
Neither is wrong; the sidecar files absorb the difference.

## Quick start

There is no example configuration to copy. The schema is the only
description of the settings, so the file you start from is generated from
it and cannot fall out of date.

```bash
T=/path/to/tools                       # where you cloned this
cd /path/to/your/docx/files
```

**1. Convert.** No configuration is needed for a first run: every setting
has a documented default.

```bash
bash $T/bin/convert.sh
```

You get one `.html` per `.docx`, their images, and a set of `*-missing.csv`
reports naming what still needs a person. The run then stops, because
building a manifest needs a couple of things only you can supply, and
writes `packaging-sample.yaml`.

**2. Fill in the two required settings and rename.** Open
`packaging-sample.yaml`, set `identifier` and `title` near the top, then:

```bash
mv packaging-sample.yaml packaging.yaml
```

Every setting is in that file at its current value with a sentence
explaining it, so this is also how you find out what can be configured.
Edit the line that is already there rather than adding another — the file
is complete, so a second copy of a key would discard the first. (The tools
refuse that rather than let it happen.) Delete any line you are happy to
leave at its default; they fill it back in. Renaming it never loses anything you had already set — that is
asserted by a test, not by care.

`identifier` is worth a moment's thought. Brightspace matches on it when
re-importing, so changing it later duplicates a course rather than
updating it.

**3. Run again.**

```bash
bash $T/bin/convert.sh            # builds imsmanifest.xml
bash $T/bin/convert.sh --zip      # ... and the .imscc archive
```

### Changing how conversion works

Everything above uses the conversion defaults. To change any of them —
the page language, an attribution footer, caption label words, the alt
text length limit — generate a conversion config the same way:

```bash
python3 $T/bin/read-conversion-config.py -d . --init
```

That writes `conversion.yaml` with every setting at its default and a line
of documentation above each. Edit it in place; there is nothing to rename.

### Where settings live

| File | Holds | Generate with |
|---|---|---|
| `packaging.yaml` | How pages become an archive. | first `convert.sh` run, or `build-cartridge.py --init` |
| `conversion.yaml` | How documents become pages. | `read-conversion-config.py --init` |
| `project.yaml` | The book itself: language, identifier, title, structure. | optional — see below |

`project.yaml` is optional. The generated `packaging.yaml` carries the
book's details in a `project:` block at the top, which is enough for most
uses. Split them out only if you want conversion and packaging to read the
same declaration from one place, and if you do, remove the inline block so
there is only one copy. The tools warn when two disagree.

### Notes

`convert.sh` finds its filters, schemas, and the shared library by path
relative to itself, so the tools can stay where you cloned them. There is
no install step.

Run each script with the interpreter that matches it: `bash` for
`convert.sh`, `python3` for anything ending in `.py`. Running a Python
script with `bash` produces a confusing pile of `import: command not
found`. The scripts do carry shebangs, so if the executable bit survived
however you obtained them, `./bin/convert.sh` works too — but it does not
survive a commit made through GitHub's web interface, so the explicit form
is what this document uses throughout.

`convert.sh` passes any arguments straight through to `build-cartridge.py`,
so `--zip`, `--check`, `--toc` and `--includeallhtml` all work on the front
script.

Work on the Linux filesystem, not under `/mnt/c` or `/mnt/h`. See
[Converting on a cloud-synced drive](#converting-on-a-cloud-synced-drive).

## A first conversion, start to finish

```bash
T=/path/to/tools

# 1. Check the source before converting anything.
for f in *.docx; do python3 $T/util/untrack-deletions.py "$f" --check; done \
  | grep -v ': 0 '

# 2. First run. There is no config yet, so it stops with a sample.
bash $T/bin/convert.sh

# 3. Fill in identifier and title, then rename.
mv packaging-sample.yaml packaging.yaml

# 4. Order the pages. With the book's PDF:
bash $T/bin/convert.sh --toc book.pdf
#    Without one, let it guess and correct the sample:
bash $T/bin/convert.sh --includeallhtml

# 5. Adopt the order it worked out.
mv packaging-sample.yaml packaging.yaml

# 6. Work through the reports, appending rows to the sidecar files.
#    Re-run after each pass; the reports shrink.
bash $T/bin/convert.sh

# 7. When the reports you care about are gone, build the cartridge.
bash $T/bin/convert.sh --zip
```

Steps 6 and 7 are the loop you will spend the most time in. Everything else
is done once per book.

The sample written in steps 2 and 4 is complete: every setting appears at
its current value with a comment explaining it, so renaming it over your
own config never loses anything you had set. That is asserted by a test,
not by care — see [Testing](#testing).

## What a run creates

```
1-3-levels-of-measurement.json        intermediate, kept for inspection
1-3-levels-of-measurement.html        the page
1-3-levels-of-measurement/media/      its images, named by real content type
imsmanifest.xml                       the manifest
cartridge-files.txt                   every file the archive must contain
packaging-sample.yaml                 written when the script worked something out
*-missing.csv                         what still needs a human
course.imscc                          only with --zip
```

The intermediate is Pandoc's own document model as JSON, which is lossless
where Markdown was not. It is not meant to be read directly, but it is not
opaque either:

```bash
pandoc -f json -t markdown 1-3-levels-of-measurement.json | less
```

Deleting the `.json` files costs nothing; the next run regenerates them.

If a run leaves `.md` files behind from v0.1, they are named on stderr and
otherwise ignored. Nothing reads them, and this script will not delete
files you may want.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Everything ran. Reports may still list outstanding work. |
| 1 | The run stopped: no `.docx` present, unresolved media, a missing required config value, or a referenced file not on disk. |

A non-zero exit on a first run is normal — there is no config yet, so the
manifest step writes a sample and stops. The HTML is already written by
that point.

## What conversion does to your pages

Beyond the Word-to-HTML translation, each page gets:

- **Layout tables become figures.** Word positions images with a one-cell
  table and puts the caption in a paragraph underneath. That produces a
  `<table>` with no header and no caption, which fails WCAG 1.3.1. These
  become `<figure>` / `<figcaption>`, and cross-reference anchors move onto
  the figure so existing links still resolve.
- **Data tables get a real `<caption>`**, `scope="col"` on header cells, and
  a focusable scroll wrapper. Pandoc's own stylesheet sets `display: block`
  on tables, which strips the table role from the accessibility tree; the
  wrapper restores it.
- **Captions are found above or below the table.** Either `**Table 2.1:
  Message Transmission Mediums**` on one line, or a bare `**Table 7.1**`
  followed by `*Sample Code of Conduct*`. Prose that merely mentions a
  table is not consumed, nor is a sentence that merely *begins* with the
  label word: "Table 48.1 provides an example of..." continues with a
  lowercase verb, where a caption continues with a capital or a colon.
  Which side a book captions on is measured across the whole document
  first, because two adjacent tables with one label between them are
  genuinely ambiguous and only the document's own habit resolves it.
  Which words introduce a caption is configurable: some books label their
  tables `Figure 1.1`, and an unrecognised label means no caption at all.
- **Media files are renamed to match their real content type.** Word stores
  images with whatever extension the DOCX declares, often `.so` from a
  content type of `application/octet-stream`.
- **Equation images** whose alt text is MathSpeak get their spelled-out
  identifiers rejoined, so a screen reader says "Customer Lifetime Value"
  rather than "upper C u s t o m e r".
- **Caption contrast** is set to `#555`, which measures 7.33:1 against
  Pandoc's `#fdfdfd` background. The widely quoted `#767676` is only
  4.47:1 there, because it is computed against pure white.
- **The leading H1 becomes the page title**, giving a meaningful `<title>`
  instead of a filename slug, and one H1 rather than two.

Conversion stops before writing any HTML if an image reference cannot be
resolved, and writes `media-unresolved.csv` naming each one with what it
was detected as. The commonest cause is EMF/WMF: Word's vector formats,
used for equations, SmartArt and pasted Office charts, which no browser
renders. Replace them in Word (right-click, Save as Picture, PNG) or
convert them with `libreoffice --headless --convert-to png`. A dead image link is invisible in the output — Pandoc emits
`<embed>` rather than `<img>` for an extension it does not recognise — so
failing loudly is better than shipping a cartridge that looks fine.

## Reports

Each run writes only the reports that have something in them, and deletes
the others. A report existing at all means there is work outstanding.

| Report | Fix it by |
|---|---|
| `image-alt-missing.csv` | Filling in the `Alt` column and appending the rows to `image-alt.csv`. |
| `table-captions-missing.csv` | Filling in the `Description` column and appending to `table-captions.csv`. |
| `table-headers-missing.csv` | Marking the header row in Word. No sidecar: header text cannot be invented. |
| `spacer-images.csv` | Nothing — it records what the spacer rule did. |
| `media-unresolved.csv` | Replacing the images named in it. Written only when the run stops. |

### Sidecar files

`image-alt.csv` and `table-captions.csv` hold your corrections. Both are
plain CSV, read afresh each run, and survive re-conversion from updated
Word files.

**Where to keep them.** By default they sit in the book's own directory,
next to the reports that name what still needs filling in. That is the
convenient default and it keeps two books' decisions apart, but it is not
where they belong long-term. The book's directory also holds the
generated HTML, the extracted media, and the intermediates: it is the
directory you delete to rebuild from scratch, and the one you replace
wholesale when the publisher reissues the source. These two files are the
only things in it that no script can reproduce.

So once you have spent real time on them, move them somewhere you can put
under version control and point the configuration at them:

```yaml
defaults:
  sidecars:
    table_captions: ../corrections/ibs2e/table-captions.csv
    image_alt: ../corrections/ibs2e/image-alt.csv
```

An absolute path works too. A relative one resolves against the book's
directory, not against the tools. A path that does not exist stops the
run rather than converting the book and discarding every correction in
the file, which is what happened before v0.2.1 when an absolute path was
given.

`image-alt.csv` keys on the image path **ignoring the extension**, because
conversion renames files by content type. Four states for the `Alt` column:

| Value | Meaning |
|---|---|
| text | Use this instead of the Word alt text |
| *(blank)* | Reviewed; keep what Word supplied |
| `[decorative]` | Emit `alt=""` so assistive technology skips it |
| *(no row)* | Unreviewed; reported if absent or over the length limit |

A blank cell deliberately does not mean decorative. "I checked this and it
is fine" and "this image carries no meaning" are different decisions.

`table-captions.csv` keys on the table's label, such as `Table 2.1`. A
table the source never labelled has no such key, so it is reported under a
positional one instead:

```
BC-08#table-1,Comparison of chart types and when to use each
```

That is page stem, then which table it is on the page. The key is stable
as long as no table is inserted or removed above it on that page — the
trade for being able to caption a table the source never named. Labelled
tables are unaffected and keep their label as the key.

One alt per image file. If the same image appears twice on a page with
different alt text, you get a warning and the first entry wins.

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
and this document all derive from it, so there is no second list to drift
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

Today there is one conversion target and one package. The shape exists
because there will be more: a full-book EPUB alongside per-chapter ones, a
print PDF alongside a screen one, each needing its own settings and its
own output directory.

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
`on`, and `off` as booleans, so Norwegian becomes `False`. There is no way
to recover which word was written, so it is refused. Quote it.

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

Omit `contents` and the order is guessed from the filenames — natural sort,
so chapter 10 does not land between chapters 1 and 2, plus chapter grouping
when the filenames encode it. `--includeallhtml` groups the pages it
appends the same way.

Chapters are detected by shape, not vocabulary: a numeric prefix
(`12-3-the-f-distribution`, `12-key-terms`) or a `chapter-12` opener page,
whose own `<title>` becomes the group heading. Within a chapter the order
is opener, introduction, numbered sections, then back matter in the order
set by `grouping.back_matter`. A role name not in that list sorts after the
ones that are, and is reported rather than silently misplaced. The guess is written to
`packaging-sample.yaml` for you to correct. It is a starting point, not a
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

Files a page references on its own are found automatically and do not
belong here. This list is for files you want shared, and for anything
reached from the header or footer — the page scan sees those on every page
and cannot attribute them to one.

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
setting is discoverable. Images with no readable width cannot be judged and
are reported separately.

```yaml
# in conversion.yaml
defaults:
  images:
    alt_max_chars: 120
```

Alt text longer than this is reported for shortening. It is a length at
which a short equivalent has become a long description, and long
descriptions belong in the prose where every reader gets them. Raising it
silences the report rather than fixing anything.

## How an LMS treats an imported cartridge

Worth knowing before you import anything twice, because the behaviour is
not what most people assume and one option is destructive.

**Structure is never merged; it is appended.** Importing a cartridge a
second time does not update the modules already in the course. It adds
another copy of the whole tree. That is why the pages are wrapped in one
module by default: a re-import then leaves one module to remove rather
than one per chapter, and in Brightspace modules are deleted one at a
time.

**There is one file per path, shared by everything that points at it.**
Two modules showing the same page are two references to one file, not two
copies. Brightspace offers two ways to delete a module, and the difference
matters:

- **Remove from Content** detaches the module and leaves the files.
- **Permanently delete** removes the files themselves.

So after re-importing a book, removing the older module with *Permanently
delete* empties the newer one too — its structure stays and its pages go
blank, with nothing to indicate why. Use *Remove from Content* for cleanup
after a re-import. *Permanently delete* is right only when removing a book
from the course, and the content prefix is what stops it reaching another
book's files.

**Deleting a module does not reclaim its images.** Measured in
Brightspace: *Permanently delete* removes the file a topic **is** and
never the files a topic **uses**. Images and other referenced files are
retained wherever they sit, directories with them, and nothing afterwards
removes either.

This is not specific to importing. The same happens to a file inserted
through Brightspace's own HTML editor, so it is general behaviour rather
than a gap in Common Cartridge handling — imports just reach it faster,
bringing hundreds of files at a time. It also means *Permanently delete*
does not remove everything its dialog says it does.

Nothing in a cartridge can make an LMS delete files it does not consider
owned, so this is something to know rather than something to fix. It is
also a second argument for the content prefix: the leftovers sit in one
named directory you can find and clear in Manage Files, rather than
scattered among everything else at the course root. Expect to do that by
hand after removing a book, and expect the one-time migration to leave the
old, unprefixed images behind when the old module goes.

### The content prefix

Every file in a package goes inside one directory named after the book,
unless you turn `paths.prefix_content` off. Without it, two books that
each contain `frontmatter.html` contain the same file as far as the LMS is
concerned: the second import overwrites the first, and permanently
deleting either empties the other.

The directory name is a readable portion of the title plus a short digest
of the identifier — the title so the folder means something in a file
manager, the digest because two books can share a title and the identifier
is the thing that must be unique. The version is deliberately not part of
it, so an update overwrites the same paths and pages refresh in place.

Nothing on disk moves. The prefix exists only inside the package.

### Moving an existing course to prefixed paths

Turning this on relocates every file, so an instructor with an earlier
import gets a second copy rather than an update. One time only, and the
order matters:

1. **Import the new cartridge.** Both copies now coexist.
2. **Check the new module renders.**
3. **Then permanently delete the old module.** Safe because the paths no
   longer overlap — and here *Permanently delete* is the right choice,
   since nothing else refers to those files and *Remove from Content*
   would leave them behind for good.

Deleting first would work too, but leaves a window with no content and
nothing to fall back on if the import fails.

After this, updates behave as before: same identifier, same prefix, same
paths, pages update in place, and the stale module goes with *Remove from
Content*. The instruction changes once and then changes back, which is
worth telling people or the careful ones will keep permanently deleting
and empty their own courses.

## Building the cartridge

```bash
python3 build-cartridge.py                 # write imsmanifest.xml
python3 build-cartridge.py --check         # validate, write nothing
python3 build-cartridge.py --zip           # also build the .imscc
python3 build-cartridge.py --init          # write a sample config and stop
python3 build-cartridge.py --toc book.pdf  # order from the PDF's outline
```

### Ordering from the book's own table of contents

`--toc book.pdf` reads the PDF's bookmark outline, which is the table of
contents in the order the book actually uses — better than any filename
heuristic can manage, and it supplies the real chapter titles. Pages are
matched by deriving a filename from each heading ("Key Concepts and
Summary" to `key-concepts-and-summary`), so it works for any book whose
files are named after its headings rather than only for known section
names. Needs `pypdf` (`pip3 install pypdf`).

It supplies the order for pages `contents` does not already place; it does
not replace a curated tree. Anything you listed stays exactly where you put
it, the outline orders the rest into the same destination, and only pages
in neither the config nor the outline reach `Unsorted`. With no `contents`
at all, the outline orders everything. The result goes to
`packaging-sample.yaml` for review, and outline entries matching no page
are reported.

Note that it follows the book faithfully. If the PDF puts per-chapter
answer pages under an "Answer Key" section, that is where they land —
move them if you would rather keep them with their chapters.

| Option | Default | Effect |
|---|---|---|
| `-d`, `--dir` | `.` | Directory holding the pages and media |
| `-c`, `--config` | `<dir>/packaging.yaml` | Packaging configuration |
| `--target` | the only one | Which package to build, when several are defined |
| `--allow-unknown-keys` | off | Report unrecognised settings instead of refusing them |
| `-o`, `--output` | `<dir>/imsmanifest.xml` | Manifest to write |
| `--toc PDF` | — | Order from a PDF's bookmark outline |
| `--includeallhtml` | off | Place pages the config does not list |
| `--zip` | off | Also build the `.imscc` |
| `--check` | off | Validate; write nothing |
| `--init` | off | Write a sample config and stop |

There is also `--emit-conversion-config DIR`, which `convert.sh` uses to
read header, footer and image settings out of the config without parsing
YAML in shell. It writes only into `DIR` and is not otherwise useful.

`build-cartridge.py` is **read-only with respect to page content**. It
never edits an HTML file or anything under a media directory; it writes
only the manifest, the file list, the sample config, and the archive. That
is what makes it safe to run repeatedly, and what lets it work on any tidy
directory of HTML rather than only on output from `convert.sh`.

Which files each page needs is discovered from the `src` and `href`
attributes the page actually uses, so a stray file left in a media
directory is not shipped, and a referenced file missing from disk is an
error that writes nothing. Links to other pages in the cartridge are
skipped — each page is already its own resource.

Pages in the directory that `contents` does not list are reported and left
out. `--includeallhtml` adds them, placing each one as precisely as the
filename allows:

- A page whose chapter already has a group in `contents` joins that group,
  in back-matter order. This is what makes re-running after converting a
  few more files cheap.
- A page naming a chapter with no group yet gets a new chapter group at the
  top level.
- Only a page with no chapter in its name goes under `Unsorted` — set the
  heading with `grouping.unsorted_title`.

New groups are added inside the group named by `grouping.append_to`. Left
unset, a contents tree that is a single group and nothing else is treated
as the book container and appended into; any other shape appends at the top
level. Naming a group that does not exist is a warning, not an error.

On a 420-page book that leaves 34 chapter groups and 8 entries in
`Unsorted` (appendices, preface, index, references) rather than everything
in one pile. Move those where they belong in the sample config it writes,
and the group disappears on the next run.

Without `--zip` the script prints the equivalent `zip` command. The archive
puts `imsmanifest.xml` at the root with media directories beneath, which is
what the LMS expects.

## Running the Pandoc filter on its own

`figures-and-tables.lua` is an ordinary Pandoc filter and works outside
`convert.sh`. Everything configurable is read from the environment, which
is how `convert.sh` passes settings from `conversion.yaml`:

| Variable | Default | Effect |
|---|---|---|
| `TABLE_CAPTIONS` | `table-captions.csv` | Sidecar of table descriptions to read |
| `IMAGE_ALT` | `image-alt.csv` | Sidecar of replacement alt text to read |
| `TABLE_CAPTIONS_MISSING` | unset | Where to append rows for tables needing a description |
| `IMAGE_ALT_MISSING` | unset | Where to append rows for images needing alt text |
| `TABLE_HEADERS_MISSING` | unset | Where to append rows for tables with no header row |
| `SPACER_LOG` | unset | Where to append rows for spacer images handled |
| `SPACER_BELOW` | `0` (off) | Width under which an image is a spacer |
| `STRIP_SPACER` | `false` | Remove spacers rather than marking them decorative |
| `ALT_MAX_CHARS` | `120` | Alt text longer than this is reported |
| `TABLE_LABEL_PREFIXES` | `Table` | Comma-separated words that introduce a table caption |
| `FIGURE_LABEL_PREFIXES` | `Figure` | The same for figures |

The `*_MISSING` and `SPACER_LOG` files are appended to, not truncated, and
carry no header row — `convert.sh` collects them across a whole run, sorts
and deduplicates, then writes the header. Point them at a temporary file if
you are running the filter yourself.

```bash
TABLE_CAPTIONS_MISSING=/tmp/rows.csv SPACER_BELOW=0.3in \
  pandoc -f json -t html5 page.json \
    --lua-filter=figures-and-tables.lua -o page.html
```

There are also two toggles near the top of the filter that are not exposed
through the config, because no book has yet needed them to differ:
`RESPONSIVE_IMAGES` (strip fixed heights so images reflow) and
`NORMALISE_MATH_ALT` (rejoin MathSpeak identifiers).

## Migrating a v0.1 configuration

`imsmanifest.yaml` is no longer read. Both halves stop with directions
rather than ignoring it, because a config that looks live and is not is
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

## Validating the manifest

`build-cartridge.py` checks the manifest it writes against the Common
Cartridge 1.1 schemas before building an archive from it. A manifest that
does not conform is still written, so you can look at it, but no `.imscc`
is built:

```
ERROR: imsmanifest.xml did not validate:
  line 22: Element 'version': This element is not expected.
           Expected is ( contribute ).

The manifest was written so you can inspect it, but no archive was built
from it.
  Re-run with --no-validate to build one anyway.
```

This is worth having for a reason with a measured cost: **every cartridge
this project produced before v0.2 was invalid.** The manifest carried a
`version` element in a place the CC 1.1 profile does not allow one. Every
LMS accepted it, so nothing ever surfaced it, and it was found by
validating against the schema and by nothing else.

Full validation uses `lxml`, which is not otherwise required here. Without
it, the check falls back to what the standard library can do:

- the document is well formed
- every identifier is a valid XML name — the rule that catches a pasted
  UUID
- every `identifierref` resolves to a resource that exists
- there is at least one resource

The run says which level it used, so a clean result never leaves you
wondering whether anything was checked. To get the full version:

```bash
sudo apt install python3-lxml
```

You can also run it directly, which is useful for a cartridge this project
did not write:

```bash
python3 bin/validate-manifest.py path/to/imsmanifest.xml
```

## Testing

```bash
bash tests/run-all.sh
```

Four suites, each independent, all runnable without network access or a
corpus of real documents. `run-all.sh` runs every one even if an earlier
one failed, and exits non-zero if any did.

| Suite | What it pins down |
|---|---|
| `run-config-tests.py` | Twenty-two fixtures over the configuration cascade: what a `false` override means, what an explicit `null` means, whether lists append, which identifiers are valid XML names, what happens when a setting is written twice. |
| `run-roundtrip-test.py` | That writing a configuration and reading it back changes nothing. |
| `run-unit-tests.py` | The small functions that decide filenames and directory names, and the places where one fact is written down twice and could drift apart. |
| `run-portability-test.py` | That every Python file parses on Python 3.9, the oldest version supported. Uses an older interpreter if one is installed and scans the source otherwise. |
| `run-filter-tests.py` | The accessibility work the Lua filters do, against six small `.docx` fixtures. Needs Pandoc 3.9; skipped with a message otherwise. |

### Why these and not others

Every filter bug fixed in v0.2 was silent. Alt text applied to the wrong
image; two `<h1>` elements on a page; a caption that stopped being found; a
ten-row table reduced to one empty cell. Nothing raised an error and
nothing in the reports showed it.

They were found by converting a whole book with two versions of the
pipeline and comparing — which works only while the previous version is
still installed and a corpus is on hand. The fixtures assert the same
things against six documents of about 37 KB each, so the check outlives
the version it was written for.

Some cases pin behaviour that is about to change rather than behaviour
that is right -- a merged title row becoming a spanning header, a table
with no header signal having its first row promoted anyway. Both are
things roadmap item 1 will alter, and a change is only checkable if the
starting point was written down.

The configuration fixtures serve a second purpose: they are the
conformance contract for the merge rules. If those rules are ever
reimplemented — in JavaScript for a web front end, or in a separate
repository — the fixtures say whether the new implementation agrees with
this one.

### Why a portability suite

One line of `lib/oerconfig.py` was valid Python 3.12 and a syntax error on
everything older, because PEP 701 lifted the rule that an f-string
replacement field cannot span lines. It compiled on the machine it was
written on and broke three of the four suites on the machine that ran
them.

Nothing caught it, and nothing could: a syntax error is invisible to an
interpreter new enough to accept the syntax. `py_compile` passes, every
test passes, and the file is unusable elsewhere. So that suite checks the
source rather than the interpreter, and runs first — a file that does not
parse makes every other result meaningless on someone else's machine.

It compiles with an older interpreter when one is installed, which is the
authority, and scans for the known-newer constructs otherwise.

### Extending them

The `.docx` fixtures under `tests/fixtures/` are committed, so the tests
need only Pandoc. `tests/make-filter-fixtures.py` rebuilds them and is the
only thing that needs `python-docx`.

Two things about Word are worth knowing before adding a fixture, because
both cost time to discover:

- Pandoc takes the document title and author from paragraphs styled
  **Title** and **Author**, consuming them out of the body. Not from
  `docProps/core.xml`, which it does not read — a natural assumption, and
  wrong.
- Word declares most embedded images as `application/octet-stream` rather
  than by type. `python-docx` sets the content type from the file
  extension, so producing the real-world case means rewriting
  `[Content_Types].xml` after saving.

A new assertion should be checked by breaking the thing it protects. Every
check in both suites was verified that way, and doing so found two
assertions of mine that passed whether the code was right or not. One was
simply badly written. The other looked fine and was worse: it claimed to
check that two documents with identically named images get distinct
sidecar keys, but in the two-step pipeline Pandoc has already qualified
those paths, so the keys were distinct for a reason that had nothing to do
with the code being tested. Only a single-pass conversion reaches the code
in question, which is why there is now a case for it.

For comparing two whole conversion runs — which is still the right tool
for a pipeline change — see `util/compare-output.py`.

## Migrating an existing manifest## Migrating an existing manifest

```bash
python3 util/manifest-to-yaml.py imsmanifest.xml -d .
```

Keeps the part that took work — the order, the grouping, the metadata — and
drops the `<file>` entries, which are now rediscovered on every run. Titles
matching what the page already carries are omitted, so the config holds
only real overrides. Run it once per book, check the result, and retire the
old XML.

## Repairing tracked deletions in the source

Some authors use Word's tracked-deletion mark as *content* — a
before-and-after table showing which words to cut from a sentence. That is
revision history carrying meaning, and anything that resolves revisions
destroys it: Word's own "Accept All Changes", most converters, and Pandoc,
which accepts changes by default. A before-and-after example then shows two
identical sentences.

```bash
# Scan a directory. --check writes nothing, so -o is not needed.
for f in *.docx; do python3 untrack-deletions.py "$f" --check; done

# Repair one file.
python3 untrack-deletions.py BC-14.docx -o BC-14-fixed.docx
```

Each `<w:del>` becomes ordinary runs with `<w:strike/>`, so the appearance
is unchanged in Word but the meaning no longer depends on a revision being
left unresolved. Only `word/document.xml` is touched; every other part of
the package is copied through byte for byte. Strikethrough reaches the HTML
as `<del>`.

`--track-changes=all` on the Pandoc call is the non-destructive
alternative, but it only fixes this pipeline, leaves the document fragile
for every other consumer, and emits `<span class="deletion">` needing CSS.

## Files that are not documents

A glob of `*.docx` picks up things that are not documents, and both
`convert.sh` and `untrack-deletions.py` skip them by name with a message
rather than failing:

| What | Why it appears |
|---|---|
| `~$Name.docx` | Word's owner file, written while a document is open. Not a zip. |
| Empty file | On a cloud-synced drive, usually a placeholder not yet downloaded. |
| No `PK` signature | An older `.doc` renamed to `.docx`. Open it in Word and use Save As. |

Skipping is per file, so one bad file no longer takes the whole run down.

## Converting on a cloud-synced drive

Both the rename and the reference rewrite in step 2 are checked after the
fact rather than trusted. `mv` and `sed` report success as soon as the
kernel accepts the write, which on a network or cloud-synced mount is not
the same as the change being visible to the next command. Each is retried
once, and the run reports how often that was needed:

```
Note: 3 media write(s) had to be retried before the change
  was visible. That is a filesystem symptom, not a conversion one.
```

Any count above zero means the working directory is not giving a
consistent view of its own writes. A Google Drive, OneDrive or Dropbox
folder mounted into WSL (`/mnt/h/...`) is the usual cause, and the
symptoms are erratic: a run fails, the next run fails differently, the
third succeeds. **Convert on the Linux filesystem** (`~/work`, not
`/mnt/...`) and copy the finished `.imscc` back.

If a write is lost twice, the run stops naming the exact file and
operation rather than letting it surface later as a missing image.

## Troubleshooting

**`set: Illegal option -o pipefail`** — the script is running under dash.
Use `bash convert.sh` or `./convert.sh`, not `sh convert.sh`. It re-execs
itself under bash, so this should only appear with a very old copy.

**`\r: not found`, then syntax errors** — CRLF line endings from a Windows
editor. `sed -i 's/\r$//' convert.sh`, and set
`git config --global core.autocrlf input`.

**`couldn't unpack docx container`** — a file that is not a DOCX. Word lock
files (`~$Name.docx`), empty cloud placeholders and renamed `.doc` files
are skipped by name, size and signature; anything else reaching Pandoc is
genuinely malformed.

**`Stopping: N media reference(s) could not be resolved`** — see
`media-unresolved.csv`. Usually EMF/WMF.

**A page appears in no report but looks wrong** — check
`packaging-sample.yaml`. If a run worked out an ordering, the sample
holds what it decided.

**Keys like `page#table-3` do not match what you see** — the number counts
data tables only, in reading order; image-only tables become figures and
are not counted. The `Excerpt` column identifies the row.

**Reports keep listing things you fixed** — check the sidecar key. Table
descriptions key on the label (`Table 2.1`) or a positional key; image alt
keys on the media path ignoring its extension.

## Known limits

- **Header row text cannot be invented.** A table with no header row is
  reported, not fixed. Add the header in Word, where it benefits every
  downstream format.
- **Equation images stay images.** Rejoining MathSpeak identifiers is a
  mitigation. The real fix is authoring them as Word equations, which
  convert to MathML.
- **Identical files in different media directories are separate files.**
  Each page gets its own copy from Word. Content-level deduplication would
  require rewriting page markup, which would break the read-only guarantee.
- **Cross-page links are not rewritten** for the LMS's internal link
  format, so links between sections may not resolve after import.
- **Strikethrough conveys meaning visually.** `<del>` is not announced by
  most screen readers by default, so a before-and-after table should say so
  in its column heading or caption.
- **Complex tables are reported, not fixed.** A table with stacked column
  headers, or with a header row and a header column, needs `headers`/`id`
  associations that no current setting can express. See the roadmap.
- **One conversion target, one package.** The configuration is shaped for
  several of each, and the tools resolve them correctly, but only `html`
  and `common-cartridge` are implemented.
- **`cartridge-files.txt` cannot build a prefixed package.** `zip -@`
  names each member after the path it read, so it cannot place files under
  a directory. Use `--zip`; the file list says so in its header when a
  prefix is in effect.
- **`compare-output.py` matches tables by position**, so inserting one
  table reports every later table on that page as changed. It also flags a
  `.docx` and its `.json` intermediate as a duplicated filename, which is
  noise rather than a finding.
