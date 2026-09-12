# Roadmap

What's planned, in the order that seems most productive.

We are attempting to follow two principles: build the tool that can check a change before making the change and, where a decision can't be made by a script, make it declarable by a person once.

## 1. Table headers sidecar

A CSV declaring, per table, where its headers are: first row, first column, both, or neither. The conversion applies it, so the same declaration drives every output format.

A census of three OpenStax books found 592 data tables among 1,412. Formatting alone classifies most of them, but the interesting distinction can't be read from the file at all: a contingency table's category column and a frequency table's interval column are byte-for-byte identical in the DOCX, and only one of them wants `scope="row"`. That's what the sidecar is for.

The generated report will carry a best guess. A first column whose values uniquely key their rows, over a body of values, is treated as headers; that gives roughly 53% `matrix`, 37% `col`, 9% `grid`, and 1% `row` across the three books. The guess is a starting point to correct, not an answer.

Also here: promote a merged full-width first row to `<caption>` rather than treating it as a header row, which folds five tables in the statistics book into the existing caption machinery.

**Why now.** It is the largest accessibility gap remaining, it is independent of everything else, and the schema is in place so it arrives as a declared setting rather than another environment variable.

## 2. Link text sidecar, for bare URLs

A reference list reads like this:

    Seidel, G. E. 2014. "Update on Sexed Semen Technology in Cattle." _Animal_ 8 (January):160--64. [https://doi.org/10.1017/S1751731114000202](https://doi.org/10.1017/S1751731114000202).

The link's visible text is the address. A screen reader announces all 57 characters of it, and the longest in *Introductory Business Statistics 2e* runs to 135 with `%20` and `+` escapes in the middle. There are 176 of them across 17 files in that book alone, 169 of them distinct, so the URL itself works as a sidecar key at almost exactly one row per link.

A sidecar maps each URL to a short description, which the filter attaches to the `Link` element as an `aria-label` attribute. That single annotation covers every output on this list:

- **HTML and EPUB3** need nothing further. Pandoc's writer emits the attribute as it stands, verified in both.
- **PDF** needs the attribute turned into the `/Contents` entry of the link annotation, which is what PDF/UA requires as a link's alternate description and what Acrobat announces. A filter for this already exists from another project and reads exactly the attribute above, so the two halves meet without either knowing about the other. What this gets us: in testing, Acrobat announces `/Contents`, browser PDF viewers ignore it. Every other mechanism — `/Alt` or `/ActualText` on a marked-content span, `/Alt` on the `Link` structure element — was tested against Acrobat and NVDA and announced nothing, and Edge announced nothing for any of them including `/Contents`. So the PDF half reaches Acrobat users and no one else, which is an argument for sequencing it after the HTML and EPUB halves rather than alongside them.
- **Markdown**, once it is an output format (item 5), carries the annotation as the `{aria-label="..."}` attribute syntax it was authored in. This is the same markup my textbook project writes by hand, so a sidecar-generated description and an author-written one are indistinguishable downstream. The flavor matters: `markdown` and `commonmark_x` round-trip the attribute, while `gfm`, `commonmark`, and `markdown_strict` rewrite the whole link as a raw `<a>` element. That is not a silent loss (it survives in the HTML) but reading such a file back gives a `RawInline` holding the opening tag, a bare `Link` stripped of its attributes, and a `RawInline` holding the closing tag. So a filter reading `Link.attributes` finds nothing, and the PDF half of this breaks. Any Markdown target needs `link_attributes` asserted rather than assumed. Item 5 has the detail.

### What has to be worked out

**Why a sidecar and not the source.** A Word hyperlink can hold a ScreenTip in `w:tooltip`, which would be the obvious place for a description and would let a remediated `.docx` carry its own. Pandoc's DOCX reader discards it: a tooltip injected by hand into `word/document.xml` comes back as `['', [], []]` on the `Link`, with the title slot empty too. So for DOCX input there is nowhere in the file for this to live, and a sidecar is not a convenience but the only option short of pre-processing the OOXML. Relevant to the DOCX-output question in item 7, which would otherwise be the natural home for writing descriptions back into a corrected source.

**Detection.** Pandoc marks a bare URL with `class="uri"` when it comes from Markdown autolink syntax, but not when it comes from a `.docx`, so that signal is not free. The rule that works: the link's text, normalized, equals its href. That found all 176 without hand-tuning.

**The guess.** The description is usually already sitting next to the URL, because a citation names its source before giving the address. Taking the text preceding the link within the same paragraph and trimming trailing punctuation produces a usable description for **77%** of them — *The Data and Story Library*, *Gallup-Healthways Well-Being Index*. The other 23% produce something visibly wrong, like *Data from*, which a person fixes in a few seconds. As with the table-headers sidecar, that is a starting point to correct rather than an answer.

Note that 144 of the 176 are in `-references.html` files and 32 are elsewhere, so the guess can't assume a citation is present.

**`aria-label` replaces the accessible name.** The URL stays visible while a screen reader hears the description instead, and WCAG 2.5.3 (Label in Name) asks that a control's accessible name contain its visible label. Strictly, this fails it. Practically, the risk is close to nil, since 2.5.3 exists so speech-input users can say what they see, and nobody dictates a 135-character URL.

Still worth deciding deliberately rather than by default. The alternative is to shorten the visible text to something readable, keep the full address in the `href`, and restore it for print with `@media print { a[href]::after { content: " (" attr(href) ")" } }`. That satisfies both criteria and changes what a reader sees on the page, which is a bigger decision than adding an attribute.

**The LaTeX side needs a preamble.** The existing filter emits `\LinkAlt{...}` and `\LinkAltReset{}` around each link, and those macros live in a `link-alt-preamble.tex` that has to come along with it. It is also a no-op without `\DocumentMetadata` tagging enabled, so the PDF half of this arrives with item 7 rather than before it. The HTML and EPUB halves have no such dependency.

### Why second

It is smaller than anything else on this list and shares all its plumbing with item 1: report what needs a human, read a CSV, apply it, report what is still outstanding. Building that machinery once with two users tests whether it is actually general, which is cheaper to find out now than after a third sidecar is bolted onto it.

## 3. EPUB3 output

One EPUB per book, its table of contents built from the same `contents` the cartridge organization uses. A per-chapter variant follows from the targets mechanism once the first one works.

Nearly free on the table side: EPUB3 uses Pandoc's HTML writer, so `id`, `colspan`, `rowspan`, `scope`, `headers`, and `role` all survive unchanged. The real work is the package document. Pandoc emits accessibility metadata unconditionally and asserts things it can't know: `accessMode: textual` for books that are 820 figures, and `accessibilityFeature: alternativeText` whether or not the images have any. `--epub-metadata` silently drops `schema:` properties, so correcting this means post-processing the OPF inside the archive. An EPUB claiming alt text it does not have is worse than one claiming nothing, because catalogs and assistive technology act on that claim.

**Why second.** A second consumer of the table sidecar is the only real test that it describes semantics rather than HTML markup. Defer every output format to the end and HTML assumptions get baked in while nothing pushes back.

## 4. Multiple targets, and `convert.sh` rewritten in Python

The configuration already describes several conversion targets and several packages, each overriding the defaults. Making them real means: building each target into its own output directory, reusing one parsed intermediate across targets that do not override media, and ordering builds from what a package declares it `includes` rather than from the order blocks appear in a file.

`convert.sh` becomes Python at the same time. Adding N targets restructures most of it anyway, and rewriting a script you are about to gut is much cheaper than rewriting one you mean to keep. The argument for Python is mostly the front end in item 9: a web interface shelling out to bash and scraping stderr can't ask what targets exist, can't report progress per document, and can't tell a media failure from a Pandoc failure without parsing prose. Conversion needs to be callable, not just runnable.

The accumulated knowledge in the comments — the Word lock-file check, the zip-signature test for a renamed `.doc`, the cloud-drive write retry, the EMF/WMF guidance — has to carry across verbatim. A rewrite is exactly where that gets dropped. `set -x` tracing needs a deliberate equivalent, too: seeing every Pandoc invocation as it happens has been useful more than once.

`compare-output.py` makes this checkable. The rewrite is done when it says `Runs agree`.

## 5. Markdown output

Pandoc writes Markdown already, so the work is small: a target with a format, and two decisions.

**The flavor is not free.** It has to be `markdown` or `commonmark_x`. Those round-trip a link's `{aria-label="..."}` attribute; `gfm`, `commonmark`, and `markdown_strict` rewrite the whole link as a raw `<a>` element instead, and reading such a file back gives a `RawInline` holding the tag, a `Link` stripped of its attributes, and another `RawInline`. So the description survives visually and stops being reachable by any filter that looks at `Link.attributes`. `link_attributes` has to be asserted on the target rather than assumed.

**Tables do not survive.** Markdown has no syntax for a header column, a cell attribute, or a `scope`, which is most of what item 1 produces. A Markdown target therefore can't be an accessible deliverable: it is a source format. That is a reasonable thing to want: converting an OER `.docx` into editable Pandoc Markdown is how a book gets maintained rather than merely republished, and it's the form my textbook project authors in. But the report files remain the record of the accessibility work, and regenerating HTML from the Markdown would need the sidecars applied again.

Links are the exception: a Markdown source can carry its own `aria-label`, so a book maintained as Markdown needs no link sidecar. See items 2 and 6, which is the reading half of the same point.

**Why here.** Its only dependency is the targets mechanism above. It's the cheapest output on this list, it's not blocked on anything external the way PDF is, and it's the one that turns this project from a one-way converter into something a book can be maintained in.

## 6. More input formats

Markdown and HTML alongside DOCX. This mostly follows from the JSON architecture: a reader is a reader.

HTML in particular opens same-format remediation, reading an HTML file and writing it back improved. Pandoc's HTML reader preserves `scope`, `headers`, `id`, and `role`, so this round-trips, which gives a testable invariant worth having: **running the pipeline on its own output should change nothing.** That is a stronger regression test than golden files, because it catches any filter that applies twice or acts non-deterministically. Note the fixed point is reached after one pass, not zero: the reader normalizes irregular tables on the way in.

Markdown is the weakest input for tables: it can't express a header column or a cell attribute, so the sidecar carries proportionally more of the load. Links are the exception. Markdown can carry an `aria-label` on a link directly, in the same `{aria-label="..."}` syntax the writer emits, so for item 2 a Markdown source needs no sidecar at all: the annotation is authorable in the file. Subject to the flavor caveat noted there: `link_attributes` has to be on, or the reader sees a raw `<a>` element rather than a `Link`.

## 7. PDF, and DOCX output

**PDF** is gated on something outside this project. Pandoc 3.9 can drive LaTeX's tagging via `-V pdfstandard=ua-2`, but `latex-lab-table` states plainly that only simple header rows and columns are supported; that complex headers with subheaders need syntax changes not yet made; and that a cell `Headers` array (the mechanism the hard cases need) is an open item. Until that lands, a tagged PDF from this pipeline can carry simple tables correctly and can't carry the complex ones. Worth revisiting each LaTeX release rather than working around.

**DOCX output** is the riskier one, and deserves scoping care. The writer does preserve `w:tblHeader`, so in principle `table-headers-missing.csv` could stop being a report and start being an input that produces a corrected source document. But a Pandoc round trip discards everything Pandoc does not model: converting a file and back turned a layout table's `FigureTable` style into plain `Table`, and that style is the cleanest signal available for identifying layout tables. Section properties, content controls, comments, field codes, and tracked changes have the same exposure. If this is built, it should annotate the OOXML directly rather than rebuild the document. It's more code, but the difference between annotating and rebuilding.

## 8. Common Cartridge 1.3, for assignments

The 1.1 profile already carries everything this project emits today. Quizzes and question banks (`imsqti_xmlv1p2`), discussion topics, web links, LTI links, and the authorization attributes are all in 1.1. The only thing worth moving for is **assignments**, which arrive in 1.3.

The cost is reach. Brightspace and Canvas read up to 1.3, Blackboard up to 1.2, Moodle only to 1.1, so a 1.1 cartridge imports everywhere while a 1.3 one does not. So this is not a migration but an option: a `cc_version` setting on the packaging target, defaulting to 1.1. The manifest differences are the namespace, the schemaversion, and the schema location, all already template substitutions, so the mechanism is small. But it requires a second set of schemas to validate against and a second set of resource types to emit correctly.

Worth doing when there is an assignment to ship, not before.

## 9. A web front end

Here's why the configuration is schema-driven and why conversion becomes a library: a front end needs to render a form from the settings that exist, write a complete config back without losing anything, and report progress and failures structurally.

Two pieces are already in place for it: the schema carries a description per setting, which is what a form's help text should say, and the writer is proven lossless by test. The third piece (resolving a config in JavaScript) is what the conformance fixtures in `tests/config/` exist to make safe.

## 10. Splitting into separate repositories

Eventually the two halves may be separate projects with a small shared library between them. Both standalone cases are already close: packaging is read-only with respect to page content and runs against any directory of HTML, and conversion has no packaging logic. v0.2 removed the last coupling, which was the config.

When that time comes, we'll need the library versioned and released on its own, and the conformance fixtures promoted from tests to a compatibility contract, ensuring that a conversion repo pinned to one version still resolves configs the same way as a packaging repo on another.

Not a goal in itself. Worth doing when one half has users the other does not.

## Smaller things

- **Retired key names.** Writing `manifest.cartridge` into a v0.2 config fails with "unknown setting" and no suggestion, because nothing is similarly named. A small table of retired names would let the error say where it went instead.
- **`compare-output.py` matches tables by position**, so one inserted table reports every later one on that page as changed. Matching on caption could help, but not every table has one.
- **A media inventory for the comparator.** It reports files and references; comparing image dimensions or bytes-per-page would catch a class of regression it currently can't see.
- **Cross-page links are not rewritten** for an LMS's internal link format, so links between sections may not resolve after import.
- **Deduplicating identical media.** Each page of a DOCX gets its own copy from Word. Sharing them would shrink a cartridge substantially but requires rewriting page markup. Worth more than it looks: an LMS that does not reclaim images when a module is deleted (looking at you, Brightspace!) accumulates every copy, so the duplication is paid for repeatedly rather than once.
- **One media directory per book** rather than per page. Pandoc's `--extract-media` produces `<page>/media/`, which inside a prefixed package means a directory per page. Flattening to `<prefix>/media/` would make the leftovers after a deletion one folder to remove instead of dozens. Cosmetic, but the cleanup is manual.

