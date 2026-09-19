# Building the cartridge

`build-cartridge.py` turns a directory of pages into an IMS Common Cartridge: the manifest, the file list, and optionally the archive. `convert.py` calls it for you and passes its options through.

## Building the cartridge

```bash
python3 build-cartridge.py                 # write imsmanifest.xml
python3 build-cartridge.py --check         # validate, write nothing
python3 build-cartridge.py --zip           # also build the .imscc
python3 build-cartridge.py --init          # write a sample config and stop
python3 build-cartridge.py --toc book.pdf  # order from the PDF's outline, or book.epub
```

### Ordering from the book's own table of contents

`--toc book.pdf` reads the PDF's bookmark outline, and `--toc book.epub`
the EPUB's navigation document (or `toc.ncx` in an EPUB 2), which is the table of
contents in the order the book actually uses — better than any filename
heuristic can manage, and it supplies the real chapter titles. Pages are
matched by deriving a filename from each heading ("Key Concepts and
Summary" to `key-concepts-and-summary`), so it works for any book whose
files are named after its headings rather than only for known section
names. Needs `pypdf` (`pip3 install pypdf`).

It supplies the order for pages `contents` doesn't already place; it does
not replace a curated tree. Anything you listed stays exactly where you put
it, the outline orders the rest into the same destination, and only pages
in neither the config nor the outline reach `Unsorted`. With no `contents`
at all, the outline orders everything.

That last case is the one you want on a first pass, and it's easy to miss
by doing things in the wrong order: the sample a first run writes already
places every page in a guessed order, so a `packaging.yaml` adopted from it
leaves the outline nothing to do, and `--toc` says so and changes nothing.

An entry is matched to a page two ways: by the filename its heading
derives (`Key Concepts and Summary` finds `1-key-concepts-and-summary`,
which is how OpenStax names files), and failing that by the page's own
title, so files named `BC-01` or pages cut from a chapter by
`pages.split_level` are found too. A title two pages share is settled by
provenance, preferring the page from the source the rest of the group
came from, then by reading order. Entries the outline has but no page
carries are reported; pages the outline never names are appended after
it, grouped under their source's title when they came from a split.
Publishers' navigation documents are not always clean: blank entries are
skipped, and an entry holding a page's worth of text (one in the corpus
does) is skipped with a warning rather than matched.
Run `--toc` before adopting the sample, or delete the `contents` block and
run it again. The result goes to
`packaging-sample.yaml` for review, and outline entries matching no page
are reported.

Note that it follows the book faithfully. If the PDF puts per-chapter
answer pages under an "Answer Key" section, that's where they land —
move them if you would rather keep them with their chapters.

| Option | Default | Effect |
|---|---|---|
| `-d`, `--dir` | `.` | Directory holding the pages and media |
| `-c`, `--config` | `<dir>/packaging.yaml` | Packaging configuration |
| `--target` | the only one | Which package to build, when several are defined |
| `--allow-unknown-keys` | off | Report unrecognized settings instead of refusing them |
| `-o`, `--output` | `<dir>/imsmanifest.xml` | Manifest to write |
| `--toc PDF-OR-EPUB` | — | Order from a PDF's bookmark outline or an EPUB's table of contents |
| `--includeallhtml` | off | Place pages the config doesn't list |
| `--zip` | off | Also build the `.imscc` |
| `--check` | off | Validate; write nothing |
| `--init` | off | Write a sample config and stop |

There's also `--emit-conversion-config DIR`, which `convert.py` uses to
read header, footer and image settings out of the config without parsing
YAML in shell. It writes only into `DIR` and isn't otherwise useful.

`build-cartridge.py` is **read-only with respect to page content**. It
never edits an HTML file or anything under a media directory; it writes
only the manifest, the file list, the sample config, and the archive. That
is what makes it safe to run repeatedly, and what lets it work on any tidy
directory of HTML rather than only on output from `convert.py`.

Which files each page needs is discovered from the `src` and `href`
attributes the page actually uses, so a stray file left in a media
directory isn't shipped, and a referenced file missing from disk is an
error that writes nothing. Links to other pages in the cartridge are
skipped — each page is already its own resource.

Pages in the directory that `contents` doesn't list are reported and left
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
unset, a contents tree that's a single group and nothing else is treated
as the book container and appended into; any other shape appends at the top
level. Naming a group that doesn't exist is a warning, not an error.

On a 420-page book that leaves 34 chapter groups and 8 entries in
`Unsorted` (appendices, preface, index, references) rather than everything
in one pile. Move those where they belong in the sample config it writes,
and the group disappears on the next run.

Without `--zip` the script prints the equivalent `zip` command. The archive
puts `imsmanifest.xml` at the root with media directories beneath, which is
what the LMS expects.

## Validating the manifest

`build-cartridge.py` checks the manifest it writes against the Common
Cartridge 1.1 schemas before building an archive from it. A manifest that
doesn't conform is still written, so you can look at it, but no `.imscc`
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
`version` element in a place the CC 1.1 profile doesn't allow one. Every
LMS accepted it, so nothing ever surfaced it, and it was found by
validating against the schema and by nothing else.

Full validation uses `lxml`, which isn't otherwise required here. Without
it, the check falls back to what the standard library can do:

- the document is well formed
- every identifier is a valid XML name — the rule that catches a pasted
  UUID
- every `identifierref` resolves to a resource that exists
- there's at least one resource

The run says which level it used, so a clean result never leaves you
wondering whether anything was checked. To get the full version:

```bash
sudo apt install python3-lxml
```

You can also run it directly, which is useful for a cartridge this project
didn't write:

```bash
python3 bin/validate-manifest.py path/to/imsmanifest.xml
```

## Migrating an existing manifest

```bash
python3 util/manifest-to-yaml.py imsmanifest.xml -d .
```

Keeps the part that took work — the order, the grouping, the metadata — and
drops the `<file>` entries, which are now rediscovered on every run. Titles
matching what the page already carries are omitted, so the config holds
only real overrides. Run it once per book, check the result, and retire the
old XML.
