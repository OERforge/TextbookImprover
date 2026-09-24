# A first run

From a directory of Word files to a cartridge, in the order the steps have to happen. The short version is in the [README](../README.md); this is the long one, with what each step writes and why the order matters.

## Where the page order comes from

A cartridge needs the pages in the book's order, grouped into modules. Three sources, in order of how much you should trust them:

1. **The book's PDF or EPUB**, with `--toc book.pdf` or `--toc book.epub`: the PDF's bookmark outline or the EPUB's navigation document is the table of contents in the order the book uses, with its real chapter titles. The PDF needs `pypdf`; the EPUB needs nothing. Run it *before* adopting the sample, since the sample already places every page and `--toc` orders only pages the config doesn't.
2. **The filenames**, with `--includeallhtml`: a page named `3-2-something` is placed under chapter 3 without guessing. Pages with no chapter in their name are left for you to sort.
3. **A guess**, which is what a bare first run does and says so in the sample.

Whichever you use, the result goes to `packaging-sample.yaml` for review, and anything you then list under `contents` stays where you put it. [Building the cartridge](packaging.md#ordering-from-the-books-own-table-of-contents) has the detail.

## Quick start

There's no example configuration to copy. The schema is the only
description of the settings, so the file you start from is generated from
it and can't fall out of date.

```bash
T=/path/to/tools                       # where you cloned this
cd /path/to/your/docx/files
```

**1. Convert.** No configuration is needed for a first run: every setting
has a documented default.

```bash
python3 $T/bin/convert.py
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
Edit the line that's already there rather than adding another — the file
is complete, so a second copy of a key would discard the first. (The tools
refuse that rather than let it happen.) Delete any line you're happy to
leave at its default; they fill it back in. Renaming it never loses anything you had already set — that's
asserted by a test, not by care.

`identifier` is worth a moment's thought. Brightspace matches on it when
re-importing, so changing it later duplicates a course rather than
updating it.

**3. Run again.**

```bash
python3 $T/bin/convert.py            # builds imsmanifest.xml
python3 $T/bin/convert.py --zip      # ... and the .imscc archive
```

### Changing how conversion works

Everything above uses the conversion defaults. To change any of them —
the page language, an attribution footer, caption label words, the alt
text length limit — generate a conversion config the same way:

```bash
python3 $T/bin/read-conversion-config.py -d . --init
```

That writes `conversion.yaml` with every setting at its default and a line
of documentation above each. Edit it in place; there's nothing to rename.

### Where settings live

| File | Holds | Generate with |
|---|---|---|
| `packaging.yaml` | How pages become an archive. | first `convert.py` run, or `build-cartridge.py --init` |
| `conversion.yaml` | How documents become pages. | `read-conversion-config.py --init` |
| `project.yaml` | The book itself: language, identifier, title, structure. | optional — see below |

`project.yaml` is optional. The generated `packaging.yaml` carries the
book's details in a `project:` block at the top, which is enough for most
uses. Split them out only if you want conversion and packaging to read the
same declaration from one place, and if you do, remove the inline block so
there's only one copy. The tools warn when two disagree.

### Notes

`convert.py` finds its filters, schemas, and the shared library by path
relative to itself, so the tools can stay where you cloned them. There's
no install step.

Run each script with the interpreter that matches it: `bash` for
`convert.py`, `python3` for anything ending in `.py`. Running a Python
script with `bash` produces a confusing pile of `import: command not
found`. The scripts do carry shebangs, so if the executable bit survived
however you obtained them, `./bin/convert.py` works too — but it doesn't
survive a commit made through GitHub's web interface, so the explicit form
is what this document uses throughout.

`convert.py` passes any arguments straight through to `build-cartridge.py`,
so `--zip`, `--check`, `--toc` and `--includeallhtml` all work on the front
script.

Work on the Linux filesystem, not under `/mnt/c` or `/mnt/h`. See
[Converting on a cloud-synced drive](troubleshooting.md#converting-on-a-cloud-synced-drive).

## A book that arrives as an archive

A book often comes packed: a `.zip` of its Word or Markdown files, a course exported from an LMS as a cartridge, a website captured as a WARC. Put the archive in a directory of its own and run `convert.py` there. Finding an archive and no sources, it unpacks it into the directory first, then converts what it unpacked:

- **A `.zip`** is extracted, and if it holds pages a browser saved, they're unpacked as `unpack-site.py` unpacks a browser's save. The folders that wrap everything are dropped, however many there are (an OpenStax DOCX download has two: `Book_-_DOCX_Customization/book/…`), so the sources land at the top, where `convert.py` looks for them; macOS's `__MACOSX` and `.DS_Store` are left out; and an entry that would land outside the directory is refused, and listed in `unpack-report.csv`. A zip is known by its name, since a Word file, a slide deck, and an EPUB are zips too, and one with no sources at its top stops the run with a list of what it holds.
- **A Common Cartridge** is unpacked as [A course cartridge as the source](cartridge-input.md) describes.
- **A WARC or WACZ** is unpacked as [Making WARCs](making-warcs.md) describes.

From then on the unpacked files are the book: correct them, not the archive, which later runs don't read again. A `project.yaml` or `conversion.yaml` already in the directory is kept, and the archive's is written beside it (`project-unpacked.yaml`, `conversion-unpacked.yaml`). One archive makes one book, so two in a directory stop the run, except several WARCs of one site, which are read together.

## A first conversion, start to finish

```bash
T=/path/to/tools

# 1. Check the source before converting anything.
for f in *.docx; do python3 $T/util/untrack-deletions.py "$f" --check; done \
  | grep -v ': 0 '

# 2. First run. There is no config yet, so it stops with a sample.
python3 $T/bin/convert.py

# 3. Fill in identifier and title, then rename.
mv packaging-sample.yaml packaging.yaml

# 4. Order the pages. With the book's PDF:
python3 $T/bin/convert.py --toc book.pdf
#    Without one, let it guess and correct the sample:
python3 $T/bin/convert.py --includeallhtml

# 5. Adopt the order it worked out. Do this AFTER step 4: the sample
#    already carries a guessed order for every page, and --toc orders
#    only pages the config does not place, so a config adopted first
#    leaves the outline nothing to do. (If that happens, delete the
#    contents block from packaging.yaml and run step 4 again.)
mv packaging-sample.yaml packaging.yaml

# 6. Work through the reports, appending rows to the sidecar files.
#    Re-run after each pass; the reports shrink.
python3 $T/bin/convert.py

# 7. When the reports you care about are gone, build the cartridge.
python3 $T/bin/convert.py --zip
```

Steps 6 and 7 are the loop you will spend the most time in. Everything else
is done once per book.

The sample written in steps 2 and 4 is complete: every setting appears at
its current value with a comment explaining it, so renaming it over your
own config never loses anything you had set. That is asserted by a test,
not by care — see [Testing](testing.md).

## What a run creates

```
1-3-levels-of-measurement.json        intermediate, as Pandoc read the source
1-3-levels-of-measurement.filtered.json   the same page after the filter has run
1-3-levels-of-measurement/media/      its images, named by real content type
html/1-3-levels-of-measurement.html   the page, in the html target's directory
html/chapter-7--economies-of-scale.html   a page cut from chapter-7, with pages.split_level on
html/1-3-levels-of-measurement/media/ the images again, beside the page that uses them
imsmanifest.xml                       the manifest
cartridge-files.txt                   every file the archive must contain
packaging-sample.yaml                 written when the script worked something out
*-missing.csv                         what still needs a human
course.imscc                          only with --zip
epub/course.epub                      only with an epub3 target declared
output-check.csv                      what the output check found, if anything
src/1-3-levels-of-measurement.md      only with a markdown target declared
html/toc.html                         only with a `generate: toc` entry in contents
html/notes.html                       only with notes.placement set to book
```

The source can be `.docx` or `.md`, one page each, in any mix. A page you
wrote yourself, an `.html` beside the sources with no source of its own,
is copied into `html/` as it stands, with the files it links, and appears
in the EPUB and the cartridge like any other page. A file named
`<stem>.<target>.md` (or `.docx`, `.html`) replaces `<stem>` for that
target alone; see [Editions](configuration.md#editions).

A page's name is its source's name made safe for a link: `01 BigPicture.md`
is the page `01-BigPicture`. The names of pages cut from a source are the
source's name and the heading's; `page-names.csv` renames them.

The intermediates are Pandoc's own document model as JSON, which is
lossless where Markdown wasn't. The first is the source as Pandoc read it;
the second is what the filter made of it, and it's what every output
format is rendered from, so a table that looks wrong on the page can be
checked there before suspecting the writer. Neither is meant to be read
directly, but neither is opaque:

```bash
pandoc -f json -t markdown 1-3-levels-of-measurement.filtered.json | less
```

Deleting the `.json` files costs nothing; the next run regenerates them.

An `.md` file with the same name as a `.docx` is what v0.1 left behind;
it's named on stderr and otherwise ignored. So are pages an earlier
version wrote beside the sources, which now go to `html/`. This script
won't delete files you may want.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Everything ran. Reports may still list outstanding work. |
| 1 | The run stopped: no source present, unresolved media, a missing required config value, or a referenced file not on disk. |

A non-zero exit on a first run is normal — there's no config yet, so the
manifest step writes a sample and stops. The HTML is already written by
that point.
