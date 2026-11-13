# A first run

From a directory of Word files to a cartridge, in the order the steps have to happen. The short version is in the [README](../README.md); this is the long one, with what each step writes and why the order matters.

Four words come up throughout. A **run** is one go of `convert.py` in the book's directory. A **target** is one output a run builds (HTML pages, an EPUB, a PDF), each in a directory of its own; with no configuration there's one, the pages in `html/`. A **report** is a CSV file a run writes, naming what still needs a person. A **sidecar** is a CSV file you keep beside the sources, holding what you decided, which every later run reads. [Terms these pages use](glossary.md) has these and the rest.

## Where the page order comes from

A cartridge needs the pages in the book's order, grouped into modules. Three sources, in order of how much you should trust them:

1. **The book's PDF or EPUB**, with `--toc book.pdf` or `--toc book.epub`: the PDF's bookmark outline or the EPUB's navigation document is the table of contents in the order the book uses, with its real chapter titles. The PDF needs `pypdf`; the EPUB needs nothing. Run it *before* renaming the sample configuration a first run writes (step 2 under [Quick start](#quick-start)), since the sample already places every page and `--toc` orders only pages the configuration doesn't.
2. **The filenames**, with `--include-all-html`: a page named `3-2-something` is placed under chapter 3 without guessing. Pages with no chapter in their name are left for you to sort.
3. **A guess** from the file names, which is what a first run with neither option makes, saying so in the sample.

Whichever you use, the result goes to `project-sample.yaml` for review (to `packaging-sample.yaml` for a book named in `packaging.yaml`'s own `project:` block), and anything you then list under `contents` stays where you put it. [Building the cartridge](packaging.md#ordering-from-the-books-own-table-of-contents) has the detail.

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

You get one page per `.docx`, in `html/`, with their images, and a set of `*-missing.csv` reports naming what still needs a person. The run then stops, because the cartridge's manifest (`imsmanifest.xml`, the file that lists a cartridge's pages and their order) needs two things only you can supply, and writes `project-sample.yaml`.

**2. Fill in the two required settings and rename.** Open
`project-sample.yaml`, set `identifier` and `title` near the top, then:

```bash
mv project-sample.yaml project.yaml
```

Every project setting is in that file at its current value with a sentence explaining it, so this is also how you find out what can be configured. Edit the line that's already there rather than adding another: the file is complete, so a second line for a setting would contradict the first, and the tools refuse a file that sets one twice rather than choose. Delete any line you're happy to leave at its default; a setting the file leaves out takes its default, and the next sample lists it again. A sample is written from your own file's values, so renaming one over a `project.yaml` you already have never loses anything you had set; that's asserted by a test, not by care. The run also prints the commands that write the other two samples, [below](#changing-how-conversion-or-packaging-works).

`identifier` is worth a moment's thought. Brightspace matches on it when
re-importing, so changing it later duplicates a course rather than
updating it.

**3. Run again.**

```bash
python3 $T/bin/convert.py            # builds imsmanifest.xml
python3 $T/bin/convert.py --zip      # ... and the .imscc archive
```

### Changing how conversion or packaging works

Everything above uses the conversion and packaging defaults. To change
any of them (the page language, an attribution footer, caption label
words, the alt text length limit, the cartridge's version), generate the
file's sample:

```bash
python3 $T/bin/read-conversion-config.py -d . --init   # conversion-sample.yaml
python3 $T/bin/build-cartridge.py -d . --init          # packaging-sample.yaml
```

Each holds every setting with a line of documentation above it, at the
value your file already gives it or else the default. Rename it to
`conversion.yaml` or `packaging.yaml` and edit it.

### Where settings live

| File | Holds | Generate with |
|---|---|---|
| `project.yaml` | The book itself: identifier, title, language, contents. | first `convert.py` run (`project-sample.yaml`) |
| `conversion.yaml` | How documents become pages. | `read-conversion-config.py -d . --init` (`conversion-sample.yaml`) |
| `packaging.yaml` | How pages become an archive. | `build-cartridge.py -d . --init` (`packaging-sample.yaml`) |

`conversion.yaml` and `packaging.yaml` are optional: every setting in them has a default. `project.yaml` names the book for both halves of the work, conversion (the pages, and an EPUB or a PDF) and packaging (the cartridge). A `project:` block in `packaging.yaml` or `conversion.yaml` names the book for that file's half alone, which is enough for a book that uses one half; files that describe the book differently stop the run. [Configuration](configuration.md#where-the-book-is-named) has the detail.

### Notes

`convert.py` finds its filters, schemas, and the shared library by path relative to itself, so the tools can stay where you unpacked or cloned them. There's no install step.

Run the scripts with `python3`, as these pages do. Everything in `bin/` and `util/` is Python; the one shell script is `tests/run-all.sh`, which runs the test suites. Running a Python script with `bash` produces a confusing pile of `import: command not found`. The scripts carry a first line that names their interpreter and are marked executable in a release archive and in a clone, so `$T/bin/convert.py` works there too, but the mark doesn't survive every way of copying files (a commit made through GitHub's web interface drops it), so the `python3` form is what these pages use throughout.

`convert.py` passes any option it doesn't take itself on to `build-cartridge.py`, the packager, so `--zip`, `--check`, `--toc`, and `--include-all-html` all work on `convert.py`.

Under WSL, keep the book on the Linux filesystem, in your home directory, not on a Windows or cloud-synced drive under `/mnt/c` or `/mnt/h`. See [Converting on a cloud-synced drive](troubleshooting.md#converting-on-a-cloud-synced-drive).

## A book that arrives as an archive

A book often comes packed: a `.zip` of its Word or Markdown files, a course exported from an LMS as a cartridge, a website captured as a WARC. Put the archive in a directory of its own and run `convert.py` there. Finding an archive and no sources, it unpacks it into the directory first, then converts what it unpacked:

- **A `.zip`** is extracted, and if it holds pages a browser saved, they're unpacked as `unpack-site.py` unpacks a browser's save. The folders that wrap everything are dropped, however many there are (an OpenStax DOCX download has two: `Book_-_DOCX_Customization/book/…`), so the sources land at the top, where `convert.py` looks for them; macOS's `__MACOSX` and `.DS_Store` are left out; and an entry that would land outside the directory is refused, and listed in `unpack-report.csv`. A zip is known by its name, since a Word file, a slide deck, and an EPUB are zips too, and one with no sources at its top stops the run with a list of what it holds.
- **A Common Cartridge** is unpacked as [A course cartridge as the source](cartridge-input.md) describes.
- **A WARC or WACZ**, a website as a crawler recorded it, is unpacked as [A book saved from the web](site-input.md) describes; [Making a WARC](making-warcs.md) says how to record one.

From then on the unpacked files are the book: correct them, not the archive, which later runs don't read again. A `project.yaml` or `conversion.yaml` already in the directory is kept, and the archive's is written beside it (`project-unpacked.yaml`, `conversion-unpacked.yaml`). One archive makes one book, so two in a directory stop the run, except several WARCs of one site, which are read together.

## A first conversion, start to finish

```bash
T=/path/to/tools

# 1. Check the source before converting anything.
for f in *.docx; do python3 $T/util/untrack-deletions.py "$f" --check; done \
  | grep -v ': 0 '

# 2. First run. There is no project.yaml yet, so it stops with a sample.
#    With the book's PDF or EPUB, order the pages from it on this run:
python3 $T/bin/convert.py --toc book.pdf
#    Without one, the sample's order is guessed from the file names:
python3 $T/bin/convert.py

# 3. Fill in identifier and title, correct the order, then rename. Do
#    step 2's --toc first: --toc orders only pages the contents don't
#    place, and the sample places every page, so once it's adopted the
#    outline has nothing to do. (If that happens, delete contents from
#    project.yaml and run step 2 again.)
mv project-sample.yaml project.yaml

# 4. Work through the reports: fill in a report's rows and append them
#    to its sidecar file (image-alt-missing.csv to image-alt.csv, say).
#    Re-run after each pass; the reports shrink.
python3 $T/bin/convert.py

# 5. When the reports you care about are gone, build the cartridge.
python3 $T/bin/convert.py --zip
```

Steps 4 and 5 are the loop you will spend the most time in, and [Sidecars and reports](sidecars.md) says what each report wants and which sidecar its rows go in. Everything else is done once per book. A page left out of `contents` later on is placed in the chapter its name gives with `--include-all-html`.

The sample written in step 2 is complete: every project setting appears at
its current value with a comment explaining it, so renaming it over your
own `project.yaml` never loses anything you had set. That is asserted by a test,
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
project-sample.yaml                   written when the script worked something out
*-missing.csv                         what still needs a human
course.imscc                          only with --zip
epub/course.epub                      only with an epub3 target declared
output-check.csv                      what the output check found, if anything
src/1-3-levels-of-measurement.md      only with a markdown target declared
html/toc.html                         only with a `generate: toc` entry in contents
html/notes.html                       only with notes.placement set to book
```

In the listing, `html/` is the directory of the `html` target, the one a run has when no configuration declares any, and each other target declared writes into a directory of its own (`epub/`, `src/`). The `.json` files are the intermediates: each page as Pandoc read it, and again after the filter, the program that does the accessibility work on a page, has run.

The sources can be Word (`.docx`), Markdown (`.md`), AsciiDoc (`.adoc`), or HTML (`.html`) files, one page each, in any mix, or a LaTeX book ([Formats](formats.md)). An `.html` file beside the sources is a source like the others. A page you finished by hand and want left as it is goes in the pass-through directory, `_pt/`: it's copied into `html/` as it stands, with the files it links, and appears in the EPUB and the cartridge like any other page ([HTML sources](html.md)). A file named `<page>.<target>.md` (or `.docx`, `.html`) replaces that page for that target alone; see [Editions](configuration.md#editions).

A page's name is its source's name made safe for a link: `01 BigPicture.md`
is the page `01-BigPicture`. The names of pages cut from a source are the
source's name and the heading's; `page-names.csv` renames them.

The intermediates are in Pandoc's own document format, as JSON, which keeps everything Pandoc read (version 0.1 kept a page as Markdown between its steps, which lost some of it). The first is the source as Pandoc read it; the second is what the filter made of it, and it's what every output format is written from, so a table that looks wrong on the page can be checked there before suspecting the step that writes the page. Neither is meant to be read directly, but neither is opaque:

```bash
pandoc -f json -t markdown 1-3-levels-of-measurement.filtered.json | less
```

Deleting the `.json` files costs nothing; the next run regenerates them.

An `.md` file with the same name as a `.docx` is what version 0.1 left behind; the run names it and otherwise ignores it. So are pages a version before 0.5 wrote beside the sources, which now go to `html/`. The run won't delete files you may want.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Everything ran. Reports may still list outstanding work. |
| 1 | The run stopped: no source present, unresolved media, a missing required config value, or a referenced file not on disk. Or a target that writes a book, an EPUB, a PDF, or a LaTeX master, wasn't written for want of the book's title, which the run says, while the other targets were. |

A non-zero exit on a first run is normal — nothing names the book yet, so
the manifest step writes `project-sample.yaml` and stops. The HTML is
already written by that point.

## Next

[Worked examples](examples.md) takes three real books through these steps from start to finish: an OpenStax book from its Word files to a course cartridge, a book website from a WARC to an EPUB, and a LaTeX book from its repository to a tagged PDF.
