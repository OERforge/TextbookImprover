# Testing

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
| `run-convert-tests.py` | `convert.py` on the fixtures: a bare directory converts into `html/`, several targets each in their own directory sharing or splitting intermediates, media copied, arguments passed through, a Markdown source, a hand-written page, two editions from one directory, footnote numbering and placement, roles and numbering with a contents page, and the Markdown round trip (read back, the HTML is the same; the second write is the fixed point). |
| `run-filter-tests.py` | The accessibility work the Lua filters do, against six small `.docx` fixtures. Needs Pandoc 3.9; skipped with a message otherwise. |
| `run-check-tests.py` | The output checker: a page that breaks every check and one that breaks none, and an EPUB with a link broken inside the archive by hand. |
| `run-split-tests.py` | `split-pages.py` on a chapter-shaped document Pandoc builds from Markdown: what a piece is, the names sidecar, links between pieces, and that the packager and the EPUB assembler group the pieces under their source from the provenance each carries. Same Pandoc requirement. |
| `run-unpack-tests.py` | `unpack-epub.py` on an EPUB built by hand in the shape of three publishers' (the package in a directory of its own, a page that isn't well-formed XML, an "image" that is an error page, a navigation entry inside a page, a spine page the navigation never names); a declared page that was split standing for its pieces; and, with Pandoc, the unpacked book converted, its links landing. |
| `run-epub-tests.py` | `build-epub.py` against the same fixtures: the nav mirrors `contents`, each page is its own file titled by its heading, a declared row header survives assembly, ids stay distinct across pages, and the package document claims `alternativeText` only once every image has it. Same Pandoc requirement. |

`run-all.sh` ends with `All suites passed.` or with the names of the suites that failed and their `FAIL` and `ERROR` lines repeated, so the reason is at the bottom rather than somewhere in ten suites of output. A check that runs one of the full validators says what the validator returned when it fails, since the usual cause is the tool, not the page.

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

Some cases pin behavior that's about to change rather than behavior
that's right — a merged title row becoming a spanning header, a table
with no header signal having its first row promoted anyway. Those are
what the filter does with no declaration in reach, which is how those
cases run; what a declaration does instead is pinned separately, in the
cases that run the pre-pass the way `convert.py` does.

The configuration fixtures serve a second purpose: they're the
conformance contract for the merge rules. If those rules are ever
reimplemented — in JavaScript for a web front end, or in a separate
repository — the fixtures say whether the new implementation agrees with
this one.

### Why a portability suite

One line of `lib/oerconfig.py` was valid Python 3.12 and a syntax error on
everything older, because PEP 701 lifted the rule that an f-string
replacement field can't span lines. It compiled on the machine it was
written on and broke three of the four suites on the machine that ran
them.

Nothing caught it, and nothing could: a syntax error is invisible to an
interpreter new enough to accept the syntax. `py_compile` passes, every
test passes, and the file is unusable elsewhere. So that suite checks the
source rather than the interpreter, and runs first — a file that doesn't
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
  `docProps/core.xml`, which it doesn't read — a natural assumption, and
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
in question, which is why there's now a case for it.

For comparing two whole conversion runs — which is still the right tool
for a pipeline change — see `util/compare-output.py`.

## House style

Reminder for Claude: Prose in this repository—these pages, the README, the changelog, the roadmap, code comments, docstrings, and the descriptions in the schemas—is US English and uses contractions: *can't*, *doesn't*, *isn't*, *it's*. The expanded forms are for the rare place where the emphasis is the point, as in the roadmap's heading "What the PDF half can and cannot do".

Two things are not prose and are left alone: anything inside a code span or a fenced block, and any string the programs print. A message a user reads on their terminal is part of the interface, and restyling one is a change to the interface rather than to the documentation.

The three settings pages under `docs/` are generated from the schemas by `util/settings-reference.py`, so their wording is fixed in the schema's `description:` and regenerated, never edited in place. `tests/run-all.sh` fails when they drift.
