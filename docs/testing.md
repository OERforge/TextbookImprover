# Testing

```bash
bash tests/run-all.sh          # cases side by side, on half the processors
bash tests/run-all.sh -j 1     # one at a time
```

Nineteen suites and a check that the settings pages are current, each
independent, all runnable without network access or a corpus of real
documents. `run-all.sh` runs every one even if an earlier
one failed, and exits non-zero if any did.

The convert, LaTeX, and EPUB suites run their cases side by side, each case a process of its own, as many at once as `-j` says (to `run-all.sh` or to the suite): by default half the processors the run may use, which leaves the rest of the machine room. A case's lines are printed whole, in the suite's order, so the output reads as it does one at a time, and `-j 1` runs them one after another in the suite's own process. The PDF suite builds its two books at once with `-j 2` or more. A LaTeX case's TeX runs can take a few hundred megabytes each, so on a machine short of memory a smaller `-j` is the way to go.

The suites' runs of `convert.py` pass `--quick`, so the output check's validators start only where a check reads what they say: epubcheck and the Nu checker in the check suite, epubcheck on the EPUB suite's books and a few of the convert suite's, and veraPDF in the PDF and LaTeX suites. They had started, a Java process each, in every run, which was most of the convert suite's time.

| Suite | What it pins down |
|---|---|
| `run-spelling-tests.py` | US spelling in every tracked text file, prose and names alike, naming file and line, the changelog's released sections included. Needs git. |
| `run-config-tests.py` | Twenty-seven fixtures over the configuration cascade: what a `false` override means, what an explicit `null` means, whether lists append, which identifiers are valid XML names, what happens when a setting is written twice, a sidecar or report setting inside a target, and what a retired setting or another block's says. |
| `run-roundtrip-test.py` | That writing a configuration and reading it back changes nothing. |
| `run-unit-tests.py` | The small functions that decide filenames and directory names, and the places where one fact is written down twice and could drift apart. |
| `run-headers-tests.py` | The table-headers pre-pass end to end, on `.docx` files built as OOXML: keys, the sidecar's values and aliases, the new-rows file, the report, and a key that matches nothing set aside, the run going on. |
| `run-census-tests.py` | The sidecar guess in `lib/tablecensus.py`, against tables built as OOXML so each carries exactly the formatting signals it means to. |
| `run-portability-test.py` | That every Python file parses on Python 3.9, the oldest version supported. Compiles with `python3.9` if one is installed and scans the source otherwise; looks for an annotation 3.9 can't evaluate either way. |
| `run-convert-tests.py` | `convert.py` on the fixtures: a bare directory converts into `html/`, several targets each in their own directory sharing or splitting intermediates, media copied, arguments passed through, a Markdown source, a hand-written page, a pdf target stopped by a missing LuaLaTeX, an old LaTeX, an SVG with no converter, or a build that outgrows TeX's tables (a stand-in LuaLaTeX writing LuaTeX's own log), two editions from one directory, footnote numbering and placement (in the EPUB too, where two chapter files can each have an `fn1` and each note's link goes to its own and back), roles and numbering with a contents page, and the Markdown round trip (read back, the HTML is the same; the second write is the fixed point). |
| `run-filter-tests.py` | The accessibility work the Lua filters do, against six small `.docx` fixtures. Needs Pandoc 3.9; skipped with a message otherwise. |
| `run-check-tests.py` | The output checker: a page that breaks every check and one that breaks none, and an EPUB with a link broken inside the archive by hand. |
| `run-split-tests.py` | `split-pages.py` on a chapter-shaped document Pandoc builds from Markdown: what a piece is, the names sidecar, links between pieces, and that the packager and the EPUB assembler group the pieces under their source from the provenance each carries. Same Pandoc requirement. |
| `run-site-tests.py` | `unpack-site.py` on saves built by hand: a browser's saves of a just-the-docs book whose pages also carry an index reaching every page, and an `.mhtml` set shaped like Scribble's. That the index loses to the menu, that images two pages saved are one file, what is reported missing and what isn't, the numbering-based nesting, and that falling back to lxml says so. Needs html5lib or lxml, and skips without either. |
| `run-mathjax-tests.py` | Formulas a saved page holds only as MathJax 2.7, 3.2, or 4.1 drew them, read back as math and checked against Pandoc's reading of MathJax's own MathML. Needs html5lib or lxml, and Pandoc. |
| `run-unpack-tests.py` | `unpack-epub.py` on an EPUB built by hand in the shape of three publishers' (the package in a directory of its own, a page that isn't well-formed XML, an "image" that is an error page, a navigation entry inside a page, a spine page the navigation never names); a declared page that was split standing for its pieces; and, with Pandoc, the unpacked book converted, its links landing. |
| `run-slides-tests.py` | PowerPoint decks, built as PresentationML so each shape is there on purpose: a deck read (a placeholder placed by its layout, a group's child through the group, one picture in two parts as one image, AlternateContent read from its Choice, notes, sections, a hidden slide); each of the checks found once in a messy deck and nothing in a clean one; and each decision written into a copy and read back: alt text by an image's content and by a slide's shape, escaped, in AlternateContent's Choice and Fallback alike; the decorative mark beside a shape's other extensions; a picture on the master marked once; header rows; a title above a slide, in its empty placeholder or first in its tree; the language in the default text style when a deck has none; the core title; a shape whose id repeats skipped; every other part byte for byte. What PowerPoint made of three decks Pandoc wrote: an empty shape and an undeclared `a14` named on their slides and put right in a copy, and a file name anywhere in alt text an error. With Pandoc, `convert.py` on folders of decks: the implied target, the reports and their keys, the copies after every decision, a stale sidecar row, decks beside a book's pages, `project.kind`, decks in a zip and a tgz, `archive`, `audit.py`, and `remediate.py`. |
| `run-latex-tests.py` | LaTeX as a source, end to end through `convert.py`, on a small book the script writes: a master `\include`-ing four chapters as the pages, the roles and the contents in the project's sample, each repair on the copy Pandoc reads (an ifthen boolean, `\input` without braces, a table in `\centerline`, `\cline`, a tagging header declaration, an image without its extension, a PDF image, alt text holding LaTeX, an artifact, `\mbox` and millimeters in formulas, `latex-conversion-macros.tex`), a drawing rendered and another LaTeX can't make costing only itself, a page overlay left alone, references between chapters with LaTeX's numbers, the EPUB's links to a chapter, `latex.main`, a one-file document, a book of documents each built on its own (the binder that only gathers their PDFs, `latex.main` as a list and a pattern, a title set as large type, a box, a `\newcolumntype`, a `\ref` to a quiz item, a file reached from the document's own folder, and each document's tagged copy and PDF), the `source` target's copy (alt text at a macro's calls, each written so the call does what it did, and those it can't write named; a book's other masters, with `luatex85` for a test for pdfTeX; its own `\DocumentMetadata` completed; fonts set in a style file of the book's own; `bm`'s bold), the PDF target's copy of the book (a `.latexmkrc` and a link outside the book), a book made its own way, as OpenIntro Statistics is (chapters `\include`-d by its own macro, images behind macros whose file holds `\chapterfolder`, environments called as commands, titlesec's settings, a color of its own, `\nameref`, `\subfigure`, a label with a space and a reference to it through a macro, groups and numbers after commands the reader takes whole, boxes it drops whole, exercises and solutions linked by keys made of counters and counters shown, an image named in another case, formulas as OpenIntro writes them, the EPUB's link to a figure in another chapter's file and its navigation document's MathML, the PDF's heading labels, the suggestion to pass on an image macro's alt-text argument and the copy that carries it, a brace never closed named, the PDF from the pages at the type size and margins its preamble gives, and an alt-text argument of paragraphs run on in the copy), a book set with packages LaTeX's tagging can't take (titlesec with its page styles, mdframed, framed, soul, ulem with a style of its own, tabto, wrapfig in a minipage too, the enumerate package's label patterns, from a macro's argument and a style file of the book's own as well, wasysym's symbols, amssymb's squares beside a symbol of the book's own, and PDF figures that don't embed their fonts, one in a folder the book links to: the copy loads none of the packages and says what that changes, for the `source` target and the PDF target alike, and its PDF builds tagged with every word, the figures' fonts embedded and the book's own figures untouched, and passes veraPDF), a figure's lossless raster kept lossless, and the author's files unchanged. Needs Pandoc; the drawing checks need a LaTeX engine and `pdftocairo` and skip without them. Where there's a TeX, the first check is that it has what these books load, and `rsvg-convert`, naming what's missing and what installs it ([Installation](installation.md#for-a-pdf-target-lualatex)). |
| `run-pdf-tests.py` | The PDF target, end to end, on a small Markdown book: a declared header column tagged as row headers, a decorative image as no figure and an undescribed one reported, each link's `/Contents`, Greek written as text present in the PDF's text and a character no font has reported once, MathML as structure and as a file, the division commands once each from the roles, the contents where `contents` puts them, the preamble page without a heading, a section's title too long for its running head scaled to fit beside the page number, amssymb's squares as the characters they are, and no page label twice; veraPDF's verdict when it's installed (only the `.notdef` of that one character). Needs LuaLaTeX with LaTeX 2025-11-01 or later, and pypdf, and skips without them, saying which is missing or too old. |
| `run-audit-tests.py` | The audit on one file of each kind, the shared findings format, the cache, and that the source check and the filter agree about what an image without alt text is. Needs Pandoc. |
| `run-epub-tests.py` | `build-epub.py` against the same fixtures: the nav mirrors `contents`, each page is its own file titled by its heading, a declared row header survives assembly, ids stay distinct across pages, and the package document claims `alternativeText` only once every image has it. Same Pandoc requirement. |

`run-latex-tests.py` and `run-convert-tests.py` take `--case LABEL`, repeatable, to run only the cases with those labels, as the scripts' `CASES` lists name them (the LaTeX suite takes any part of a label).

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

It compiles with Python 3.9 when one is installed, which is the
authority, and scans for the known-newer constructs otherwise; any
interpreter newer than 3.9 accepts some of them, so only 3.9 itself will
do. Either way it reads each file's syntax tree for an annotation written
`X | Y`, which 3.9 compiles and then fails on when the definition runs.

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

A new assertion should be checked by breaking the thing it protects. The
configuration and filter suites' checks were each verified that way, and doing so found two
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

Reminder for Claude: Prose in this repository—these pages, the README, the changelog, the roadmap, code comments, docstrings, and the descriptions in the schemas—is US English and uses contractions: *can't*, *doesn't*, *isn't*, *it's*. The expanded forms are for the rare place where the emphasis is the point, as in the roadmap's heading "What the PDF half can and cannot do". `tests/run-spelling-tests.py` holds the spelling mechanically, in prose and in the names of our own functions and settings, and says which file and line; a changelog entry naming an old spelling to say what became of it, a name that isn't ours (ARIA's `aria-labelledby`), and an old name kept working until 1.0 are left alone.

Two things are not prose and are left alone: anything inside a code span or a fenced block, and any string the programs print. A message a user reads on their terminal is part of the interface, and restyling one is a change to the interface rather than to the documentation.

The three settings pages under `docs/` are generated from the schemas by `util/settings-reference.py`, so their wording is fixed in the schema's `description:` and regenerated, never edited in place. `tests/run-all.sh` fails when they drift.
