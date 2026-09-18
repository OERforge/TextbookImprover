# A first run

From a directory of Word files to a cartridge, in the order the steps have to happen. The short version is in the [README](../README.md); this is the long one, with what each step writes and why the order matters.

## Where the page order comes from

A cartridge needs the pages in the book's order, grouped into modules. Three sources, in order of how much you should trust them:

1. **The book's PDF**, with `--toc book.pdf`: the PDF's bookmark outline is the table of contents in the order the book uses, with its real chapter titles. Needs `pypdf`. Run it *before* adopting the sample, since the sample already places every page and `--toc` orders only pages the config does not.
2. **The filenames**, with `--includeallhtml`: a page named `3-2-something` is placed under chapter 3 without guessing. Pages with no chapter in their name are left for you to sort.
3. **A guess**, which is what a bare first run does and says so in the sample.

Whichever you use, the result goes to `packaging-sample.yaml` for review, and anything you then list under `contents` stays where you put it. [Building the cartridge](packaging.md#ordering-from-the-books-own-table-of-contents) has the detail.

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
[Converting on a cloud-synced drive](troubleshooting.md#converting-on-a-cloud-synced-drive).

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

# 5. Adopt the order it worked out. Do this AFTER step 4: the sample
#    already carries a guessed order for every page, and --toc orders
#    only pages the config does not place, so a config adopted first
#    leaves the outline nothing to do. (If that happens, delete the
#    contents block from packaging.yaml and run step 4 again.)
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
not by care — see [Testing](testing.md).

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
