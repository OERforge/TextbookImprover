# Changelog

All notable changes to this project are documented in this file. The format is based on [Keep a Changelog](https://keepachangelog.com/).

Versions are two-part and pre-1.0: breaking changes may land in any of them until 1.0, and each is marked **Breaking** below. But we intend to keep the configuration schema, the command-line interface of each script, and the format of the sidecar CSV files stable in each version.

## [Unreleased]

Groundwork for the table-headers sidecar (roadmap item 1). Nothing in the conversion pipeline changes yet.

### Added

- `util/table-census.py` reports a `Guess` column beside `Kind`: the value a table-headers sidecar would be prefilled with, for every data table. `Kind` is what the file says, `Guess` is what to declare, and a row where they differ is a row worth looking at. Across seven books (1,271 documents, 2,068 tables, 792 of them data tables) the guess gives 462 `both`, 264 `first-row`, 37 `none`, 28 `first-column`, and 1 `unknown`. The header mechanism it feeds behaves identically on Pandoc 3.1.3, 3.9, and 3.11, so this needs no version bump.
- `util/contrib/fix-empty-paragraphs.py`, contributed from another project and not wired in. It removes content-free paragraph structure elements from a tagged PDF, two sources of which are the longtable caption wrapper and Pandoc's minipage header cells. Needs `pikepdf`. See roadmap item 7.
- `tests/run-census-tests.py` checks that guess against thirteen table shapes built as OOXML directly, so each one carries exactly the formatting signals it means to and no table style decides the answer first. Registered in `tests/run-all.sh`.

- `util/table-samples.py` collects one real example of each table shape into a single Word document, copied out of the sources rather than rebuilt, so the style, table-look flags, merges, repeat-header rows, direct formatting, images, and links all come across. Each example is annotated with its census kind, its guessed value, the evidence read from the file, and which rule produced that value. Deterministic by default; `--random` or `--seed N` samples other examples of the same shapes.
- `util/docx-compat.py` reads, and optionally sets, the `compatibilityMode` compat setting that decides whether Word treats a document as current or opens it in Compatibility Mode, where it refuses to run its Accessibility Checker. Every other part of the package is copied through untouched, and legacy compat option elements are reported rather than cleared.

### Changed

- Cell text now includes equations and respects line structure. A cell's content can be an OMML equation rather than runs of text, and 336 cells across the corpus looked empty to a `w:t`-only reader; paragraphs and line breaks inside a cell are separated rather than run together. Both matter for the guess and more for a key computed from cell text, where three tables in the statistics book hashed identically.
- The guess reads more shapes, each measured against the corpus: a numeric first column must be ordered to count as a key column, a blank corner with labels along both edges is a matrix whatever the body holds, a row of words over rows of numbers is a header row, values with their units written out (`$120 billion`) count as values, the values test is asked per column rather than over the whole body, an unlabeled trailing summary row is set aside, and one-column tables are no longer disqualified by tests written for merged rows.
- `guess()` is now a thin wrapper over `explain()`, which returns the value and the reason together, so the reason cannot drift from the decision.
- A new `unknown` value covers a table whose header band the four values cannot place -- a claim about the guess rather than about the table, kept distinct from `none`.
- The vocabulary for header shapes is `first-row`, `first-column`, `both`, and `none`, naming the line that holds the headers. It previously used `col` for a header *row* and `row` for a header *column*, which is the opposite of how LaTeX's `table/header-rows` and `table/header-columns` read. No sidecar format has shipped with the old names, so there is nothing to migrate.

## [0.2] - 2026-09-12

Two major structural changes to prepare for future work: the conversion pipeline is now routed through JSON instead of Markdown, and the configuration is no longer described in three hand-maintained places. Both were prompted by the same discovery: settings and structure were being lost silently, in ways no report caught and no error announced. Converting *Introductory Business Statistics 2e* with v0.2 produces 169 of 169 pages semantically identical to v0.1, apart from the fixes below, and every one recovers something v0.1 dropped.

Three of the breaking changes need action before a first run with v0.2: split your configuration, rebuild your cartridge, and tell instructors how to re-import it. See [Upgrading](#upgrading-from-01).

### Added

- Pandoc's own document model, as JSON, is now the conversion intermediate. It is lossless where Markdown was not: Markdown has no syntax for a cell attribute or a header column, which are exactly what accessibility remediation produces.
- Every setting is declared in a schema with a type, a default, and a sentence of documentation. The readers, the validator, the sample writer, and the generated files all derive from it, so there is no second list to drift out of step with the first. 42 settings are now declared where 8 were reachable from the configuration file; the rest existed only as environment variables documented in a Lua comment.
- `bin/validate-manifest.py` checks the manifest against the Common Cartridge 1.1 schemas before an archive is built from it. The schemas are bundled in `schemas/cc11/`, unmodified and redistributed under their own terms, so validation needs no network. Full validation uses `lxml`, which is optional: without it the check falls back to well-formedness, identifier syntax, and unresolved references, and says which level ran.
- Chapters are wrapped in one module named after the book. An LMS never merges an imported structure with one already in the course; it appends. A re-import therefore always leaves a second copy, and this makes that one module to remove rather than one per chapter. `organization.wrap_in_module` turns it off, and `organization.module_title` is a template — `"{title} ({version})"` by default, because after a re-import two modules otherwise carry the same name and nothing tells them apart.
- `bin/media-extensions.lua` names extracted images by their real content type while they are still in memory, before anything is written.
- `util/compare-output.py` compares two conversion runs semantically, reporting what carries meaning rather than what changed byte for byte.
- `util/table-census.py` surveys table structure across a corpus of DOCX files.
- `util/migrate-config.py` splits a v0.1 configuration into the three v0.2 files, reporting where every setting lands and refusing to overwrite anything.
- `tests/` holds five suites, run together by `tests/run-all.sh`: a portability check over every Python file; twenty-two configuration conformance fixtures; a round-trip check that writing a configuration and reading it back changes nothing; unit checks over the functions that decide filenames and directory names, plus the places where one fact is written down twice; and filter tests that convert six small committed `.docx` fixtures and assert on the accessibility markup. Every filter bug fixed in this release was silent and was found by comparing two runs of a real book, which only works while the previous version is available; the fixtures make the same checks self-contained.
- `read-conversion-config.py --init` and `build-cartridge.py --init` each write a complete, documented configuration file. Between them there is a way to generate every one, which matters now that there is no example to copy.
- `--allow-unknown-keys` reports settings this version does not recognize instead of refusing them, and keeps them if the configuration is rewritten.
- `build-cartridge.py --target` selects which package to build when a configuration defines more than one, and `--no-validate` builds an archive from a manifest that did not validate.
- `images.responsive` and `tables.wrap` are configurable, having been hardcoded.

### Changed

- **Breaking:** `imsmanifest.yaml` is replaced by three files, split by what a setting describes rather than which script reads it: `project.yaml` for the book, `conversion.yaml` for how it is rendered, `packaging.yaml` for how it is archived. Both halves stop with directions rather than ignoring an old configuration. Run `util/migrate-config.py`.
- **Breaking:** Every file in a package now sits inside one directory named after the book, so two books can't share a path. This relocates every file, so an instructor with an existing import gets a second copy rather than an update and has to remove the old module once — in an order that matters, since doing it backwards leaves a window with no content. `paths.prefix_content: false` restores the old behavior.
- **Breaking:** Pandoc 3.9 or later is required, up from 3, and checked before any work starts. Earlier versions accept most of the command line and quietly do something else: 3.6 and older write tables without cell spans, so a table with merged cells loses them with no warning at all. Upgrading to Pandoc 3.11 (current as of this date) should work best.
- **Breaking:** Python 3 is required rather than optional. It reads the configuration and inspects the conversion intermediates.
- **Breaking:** `build-cartridge.py --emit-conversion-config` is retired. `convert.sh` used to ask the packaging tool to parse its configuration, so a folder of documents could not be converted without it present. Both halves now use the shared library in `lib/` and neither uses the other.
- Reports are written to the book's directory rather than beside the scripts. In v0.1 those were the same place, because the scripts were copied into the content directory. From v0.2 the tools stay where they were cloned, so leaving the reports there would mean two books overwriting each other's.
- Sidecars default to the book's directory too, but that is only a default. They are read rather than written, and they hold the one thing in the pipeline no script can reproduce, so the directory you delete to rebuild is the wrong permanent home for them. `sidecars.table_captions` and `sidecars.image_alt` take a path: absolute, or relative to the book's directory, so corrections can live somewhere version-controlled. See [Sidecar files](README.md#sidecar-files).
- A configuration that can't be read stops the run. It was reported and then ignored, so a book would convert with the defaults while the user believed their settings had applied. A directory with no configuration still converts with the defaults, as before.
- A setting written twice in the same block is refused. PyYAML keeps the last and says nothing, which is a poor bargain when generated configuration files already contain every setting.
- A misplaced setting says where it belongs. `footer` at the top level (where v0.1 put it) now reports that it is a setting and belongs under `defaults:`, rather than reporting only that it was unexpected.
- `project.identifier` is checked as an XML name at load time rather than failing at import time. IMS types it as `xs:ID`, so it must start with a letter and contain no colons, which rules out both obvious ways of writing a globally unique identifier: a bare UUID usually starts with a digit, and `urn:uuid:` has colons.
- Generated configuration files include the settings that belong to a target: `format`, `output_dir`, `filename`, `includes`. They can't go in the defaults block, and were previously written only where a target overrode them, so five settings existed, were read, and were documented nowhere.
- A package's `filename` is derived on every run from the book's identifier and the format's extension rather than written into the file, so renaming the book renames the archive. Two packages of the same format are reported rather than left to overwrite each other.
- The tree is reorganized into `bin/`, `lib/`, `util/`, `tests/`, and `schemas/`, with the documentation at the root.
- Configuration errors print a message rather than a Python traceback.

### Fixed

- An absolute sidecar path in the configuration was silently ignored. `convert.sh` resolved every name as `$PWD/$name`, so `/srv/corrections/table-captions.csv` became `/book//srv/corrections/table-captions.csv`. The book converted, every correction in the file was discarded, the tables reappeared in the missing report as though nobody had written a caption, and the only trace was an instruction to append the work to a path that did not exist. A path that the configuration names but the run cannot read is now an error.
- A line of `lib/oerconfig.py` needed Python 3.12. An f-string replacement field spanned two lines, which PEP 701 permits and every earlier version rejects, so the file was a syntax error on anything older and took three of the four test suites with it. A syntax error is invisible to an interpreter new enough to accept it, so no suite could have caught this: `tests/run-portability-test.py` checks the source against Python 3.9 instead, and runs first.
- Every cartridge this project produced was invalid. The manifest carried a `lomimscc:version` element inside `lifeCycle`, where the CC 1.1 profile permits `contribute` alone and declares no `version` element anywhere. Every LMS accepted it, which is why it went unnoticed until the manifest was validated against the schema.
- Alt text could be applied to the wrong image. Converting a DOCX straight to HTML in one pass, the filter sees the raw mediabag path `media/rId26.so` rather than `1-3-foo/media/rId26.png`, because `--extract-media` rewrites the paths after filters run, so every document in a book collided on the same sidecar keys. Keys are now qualified by the source document. The two-step conversion `convert.sh` performs never had the collision, because step 1 has already rewritten the paths by the time the filter runs in step 2, which is why this needed a single-pass test to cover at all.
- Page language disagreed with package language. `convert.sh` hardcoded `-M lang=en` while the manifest read its own separate setting, so a book in any other language shipped pages contradicting the package describing them, and nothing checked.
- Blank worksheet tables were destroyed. Markdown's writer chose a layout whose empty rows read back as paragraph breaks, reducing a ten-row table to a single empty cell. Three tables across the three OpenStax books.
- Conditional-probability expressions containing `|` were lost, three per page in the statistics book.
- Twelve captions were not being found. Word's list-paragraph style stores a bare label as a one-item list, which Markdown used to flatten.
- Two `<h1>` elements appeared on every page, and titles lost their section number. Pandoc's docx reader turns a paragraph styled `Title` into title metadata, and every OpenStax file has one (saying the same thing as the H1 without its section number). The existing title then blocked the filter's heading promotion.
- A visible "OpenStax" byline appeared under every page title, from an `Author`-styled paragraph read the same way. `author_byline` now keeps the metadata in the page head and suppresses the byline.
- A caption written against a generated position key stopped applying once the table's real label was found. The lookup now tries both, so no sidecar needs rewriting.
- The sample configuration writer dropped three settings (`captions`, `grouping`, and `manifest.modified`) from a file it described as complete and told the user to rename over their own. A round-trip test now asserts that nothing is lost.
- An explicitly empty setting was overruled by its default: `unsorted_title: ""` came out as `Unsorted`, and `back_matter: []` fell back to the built-in order.
- The built-in back-matter order and its documented default disagreed, the latter missing seven entries including `key-concepts-and-summary`.
- A reverse-DNS style identifier produced an archive with no extension. `org.example.book-2e` was read as a filename whose extension was `.book-2e`, so nothing was appended.
- Media that Word declares as `application/octet-stream` produced `.so` files, which Pandoc writes as `<embed>` rather than `<img>`—a page that validates yet shows nothing. Renaming now happens before anything is written, so the file and the reference can't disagree.
- Alt text kept leading whitespace, which a screen reader ignores but which counted against the length limit, so reported character counts disagreed with what a person counts. The trimmed text is now what gets written back as well, so the measured and the emitted value are the same string.
- `python3` was required but unchecked, so a machine without it failed part-way through a run with the intermediates already written.

### Removed

- The Markdown intermediate. Files left behind by v0.1 are named on stderr and otherwise ignored; nothing reads them, and the scripts will not delete files you may want.
- `conf/imsmanifest.example.yaml`. Sample configurations are generated from the schema, complete and documented, so a hand-maintained example is the second list that drifts.
- Roughly 160 lines of media repair in `convert.sh`, which walked the Markdown with `grep` and `sed` because by then it was the only option left. What remains is a check, kept because the failure it guards against is invisible.

### Upgrading from 0.1

```bash
python3 util/migrate-config.py -d . --dry-run   # see where everything goes
python3 util/migrate-config.py -d .
```

Sidecar files need no migration, and can now be moved out of the book's directory: see [Sidecar files](README.md#sidecar-files). If you tried an absolute path before and found it had no effect, that was the bug above rather than your CSV. For the cartridge, see [How Brightspace treats an imported cartridge](README.md#how-brightspace-treats-an-imported-cartridge), in particular the order in which instructors should import the new package and remove the old module, and which of Brightspace's two delete options is safe when. (We haven't tested on other LMS software.)

## [0.1] - 2026-08-30

First release. DOCX to accessible HTML via Markdown, with a Pandoc filter handling figures, tables, alt text, and captions; sidecar CSV files for decisions a script can't make; and an IMS Common Cartridge builder.

[Unreleased]: https://github.com/OERforge/TextbookImprover/compare/v0.2...HEAD
[0.2]: https://github.com/OERforge/TextbookImprover/compare/v0.1...v0.2
[0.1]: https://github.com/OERforge/TextbookImprover/releases/tag/v0.1
