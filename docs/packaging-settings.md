# Packaging settings

Settings that describe one package of the book, under `packaging:` in `packaging.yaml` and per target under `targets:`. Generated from `bin/schema-packaging.yaml` by `util/settings-reference.py`; edit the schema, not this page.

How converted files are assembled into a distributable package.

**`format`** -- one of `common-cartridge`, `zip`; default `common-cartridge`; *target only*

What this package is. Others -- SCORM in particular -- are expected here later. A common-cartridge is written to the Common Cartridge 1.1 profile. That is deliberate rather than neglect: 1.1 is the only version every major LMS reads, and the floor sets the target. Brightspace and Canvas handle up to 1.3 and Blackboard up to 1.2, but Moodle stops at 1.1, and a 1.1 cartridge imports into all of them while a later one does not. Nothing in 1.2 or 1.3 is needed here: quizzes, question banks, discussion topics, web links and LTI links are all in 1.1 already. Assignments arrive in 1.3 and are the one reason to revisit this.

**`filename`** -- `path`; default `""` (empty); *target only*

The archive to write. Left empty it is worked out afresh on every run from the book's identifier and this package's format, so renaming the book renames the archive. Given without an extension, the one matching the format is added. Set it when a configuration defines two packages of the same format, which would otherwise both want the same name.

**`includes`** -- `list`; default `[]`; *target only*

Conversion targets whose output goes into this package, named as they are named in the conversion config. Order does not matter: anything listed is built first. A package of HTML pages that also ships an EPUB and a print PDF lists all three.

## organization

How the book's structure appears in the importing system.

**`organization.wrap_in_module`** -- `bool`; default `true`

Put every chapter inside one module named after the book, rather than leaving each at the top level. An LMS never merges an imported structure with one already there -- it appends -- so a re-import always adds a second copy. Wrapped, that is one module to remove afterwards; flat, it is one per chapter, and in Brightspace they must be deleted one at a time.

**`organization.module_title`** -- `string`; default `{title} ({version})`

The wrapper module's name, as a template. {title} is the book's title and {version} this package's version. The version is there because after a re-import there are two modules with the same name and nothing else to tell them apart. Write "{title}" alone if you do not bump the version between releases, since a permanent "(1.0)" distinguishes nothing and every student sees it.

## paths

Where files sit inside the package. This affects the package only; nothing on disk moves.

**`paths.prefix_content`** -- `bool`; default `true`

Put every file in the package inside one directory, so two books cannot share a path. Without this, two cartridges that each contain frontmatter.html contain the same file as far as the LMS is concerned: importing the second overwrites the first, and permanently deleting either one empties the other, leaving its pages blank and its structure intact. Turning this on relocates every file, so an instructor with an existing import gets a second copy rather than an update. That is a one-time cost; afterwards updates overwrite in place as before.

**`paths.prefix`** -- `path`; default `""` (empty)

The directory name to use. Left empty it is derived from the book's title and identifier: a readable portion from the title so the folder means something in a file manager, and a short digest of the identifier for uniqueness, which is where the uniqueness has to come from since two books can share a title. The version is deliberately not part of it -- a prefix that changed between releases would make every update a fresh import rather than an update. Set this explicitly if you expect to edit the title, since the title is part of the derivation and changing it relocates everything.

**`source_dir`** -- `path`; default `.`

Directory holding the files to package, for the case where they were not produced by a conversion target listed in includes.

**`version`** -- `string`; default `1.0`

Version recorded in the package metadata. Quote it: unquoted 1.10 is read as the number 1.1.

**`modified`** -- `date`; default `""` (empty)

Date recorded in the package metadata, as YYYY-MM-DD. Empty means the day the package is built, which makes the output differ between runs; set it to keep builds reproducible.

**`keywords`** -- `list`; default `[]`

Subject keywords recorded in the package metadata.

**`common_files`** -- `list`; default `[]`

Files every page depends on -- a stylesheet, a shared image. Listed once as their own resource and referenced by each page rather than repeated.

## grouping

How pages with no explicit place in the book's contents are arranged.

**`grouping.back_matter`** -- `list`; default `[key-terms, chapter-review, key-concepts-and-summary, formula-review, practice, self-check-questions,
  review-questions, critical-thinking-questions, bringing-it-together-practice, homework,
  bringing-it-together-homework, problems, references, solutions]`

The order back matter appears in within a chapter. Books differ: Statistics has chapter-review and homework where Economics has key-concepts-and-summary and problems, so anything unrecognised sorts after this list and is reported rather than silently misplaced.

**`grouping.unsorted_title`** -- `string`; default `Unsorted`

Heading for pages that could not be placed.

**`grouping.append_to`** -- `string`; default `""` (empty)

Put unplaced pages under this existing group rather than in a group of their own.
