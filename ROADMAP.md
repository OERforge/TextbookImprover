# Roadmap

What's planned, in the order that seems most productive. What has shipped is in [the changelog](CHANGELOG.md); what the tools do now is in [the docs](docs/).

We're attempting to follow two principles: build the tool that can check a change before making the change and, where a decision can't be made by a script, make it declarable by a person once.

Two sections sit after the numbered items. **Refinements to the table headers work** is what v0.3 left undone in the feature it shipped, kept separate because none of it is large enough to be an item and all of it is worth doing before that work is called finished. **Smaller things** is everything that has no dependency on anything else.

## 1. EPUB3 output

One EPUB per book, its table of contents built from the same `contents` the cartridge organization uses. A per-chapter variant follows from the targets mechanism once the first one works.

Nearly free on the table side: EPUB3 uses Pandoc's HTML writer, so `id`, `colspan`, `rowspan`, `scope`, `headers`, and `role` all survive unchanged. The real work is the package document. Pandoc emits accessibility metadata unconditionally and asserts things it can't know: `accessMode: textual` for books that are 820 figures, and `accessibilityFeature: alternativeText` whether or not the images have any. `--epub-metadata` silently drops `schema:` properties, so correcting this means post-processing the OPF inside the archive. An EPUB claiming alt text it doesn't have is worse than one claiming nothing, because catalogs and assistive technology act on that claim.

**Why here.** A second consumer of the table sidecar is the only real test that it describes semantics rather than HTML markup. Defer every output format to the end and HTML assumptions get baked in while nothing pushes back.

## 2. Multiple targets, and `convert.sh` rewritten in Python

The configuration already describes several conversion targets and several packages, each overriding the defaults. Making them real means: building each target into its own output directory, reusing one parsed intermediate across targets that don't override media, and ordering builds from what a package declares it `includes` rather than from the order blocks appear in a file.

`convert.sh` becomes Python at the same time. Adding N targets restructures most of it anyway, and rewriting a script you're about to gut is much cheaper than rewriting one you mean to keep. The argument for Python is mostly the front end in item 10: a web interface shelling out to bash and scraping stderr can't ask what targets exist, can't report progress per document, and can't tell a media failure from a Pandoc failure without parsing prose. Conversion needs to be callable, not just runnable.

The accumulated knowledge in the comments — the Word lock-file check, the zip-signature test for a renamed `.doc`, the cloud-drive write retry, the EMF/WMF guidance — has to carry across verbatim. A rewrite is exactly where that gets dropped. `set -x` tracing needs a deliberate equivalent, too: seeing every Pandoc invocation as it happens has been useful more than once.

`compare-output.py` makes this checkable. The rewrite is done when it says `Runs agree`.

## 3. Markdown as a source format, read and written

Markdown is the one format this project should be able to go both ways in, and the two halves are one piece of work because they define the same vocabulary. Reading has to accept the markers writing emits; writing has to emit markers reading accepts. Ship either half alone and the other is where you find out the first chose badly.

**Tables survive better than this item used to claim.** What Markdown can't carry is the rendered markup: there's no syntax for `scope` on a cell or for a header column. What it can carry is the *declaration*, in a fenced div, and the declaration is what the sidecar holds anyway. Verified on 3.11: `::: matrix` around a table round-trips through the `markdown` and `commonmark_x` writers and readers as `Div ("", ["matrix"], [])`, and a filter reading that class regenerates the whole thing -- `<caption>`, `scope="col"` across the head, `scope="row"` down the first column. So a Markdown source isn't a lesser input carrying more sidecar load; it's a source where the sidecar's content lives in the document. That is how my own textbook is written, with `::: matrix` and `matrix-headers.lua`.

**Captions round-trip in `markdown` and not in `commonmark_x`.** The `markdown` writer emits `: Table 7.1 Costs by technology` beneath the table and reads it back as the table's `Caption`; `commonmark_x` writes it as a following paragraph and reads it back as a paragraph, association gone. That is a second reason for the flavor constraint the link attributes already impose.

**The flavor isn't free.** It has to be `markdown` or `commonmark_x`. Those round-trip a link's `{aria-label="..."}` attribute; `gfm`, `commonmark`, and `markdown_strict` rewrite the whole link as a raw `<a>` element instead, and reading such a file back gives a `RawInline` holding the tag, a `Link` stripped of its attributes, and another `RawInline`. So the description survives visually and stops being reachable by any filter that looks at `Link.attributes`. `gfm` does the same to a fenced div. The extension has to be asserted on the target rather than assumed, and it isn't spelled the same way in both: `link_attributes` for `markdown`, `attributes` for `commonmark_x`.

**Marker names are configurable.** `::: matrix` is what one author chose; another will have chosen otherwise, and a book may mark nothing at all. So `tables.markers` maps each declaration to the div classes that mean it, defaulting to what my textbook uses, and an unmarked table is the unmarked case: guessed, reported, and distinguishable in the report from one that was marked. The same applies to links, where a Markdown source can carry its own `aria-label` and needs no sidecar at all.

**The acceptance test exists only when both halves do.** Convert a `.docx` to Markdown, convert that Markdown to HTML, and compare against converting the `.docx` straight to HTML. If the pages differ, a declaration didn't survive. `util/compare-output.py` already performs that comparison, so the gate is free once the second half lands.

**Read first, write second.** There are Markdown books to test the reading half against today, and no Markdown output yet to produce any. Reading also settles the marker vocabulary against a real document rather than against a guess.

**Why here.** Its only dependency is the targets mechanism above. It's the cheapest format on this list, it isn't blocked on anything external the way PDF is, and it's the one that turns this project from a one-way converter into something a book can be maintained in.

## 4. HTML and EPUB as input formats

With Markdown handled above, what remains is HTML and EPUB, and they're close relatives: an EPUB is zipped XHTML, and Pandoc reads it with the same reader.

**HTML opens same-format remediation** -- reading an HTML file and writing it back improved. Pandoc's HTML reader preserves `scope`, `headers`, `id`, and `role`, so this round-trips, which gives a testable invariant worth having: **running the pipeline on its own output should change nothing.** That is a stronger regression test than golden files, because it catches any filter that applies twice or acts non-deterministically. Note the fixed point is reached after one pass, not zero: the reader normalizes irregular tables on the way in.

One thing to know before relying on it: the reader keeps the attribute but not the element. `<th scope="row">` comes back as a `Cell` carrying `("scope","row")` and is written as `<td scope="row">`, because a `Cell` has no is-a-header flag and only `row_head_columns` makes a body cell a `th`. So `scope="row"` on the first column is a source marker meaning `first-column` or `both`, and the filter sets `row_head_columns` to make it true again. Verified on 3.11 for both readers.

**EPUB earns its place twice over.** Its `nav.xhtml` is the book's table of contents in machine-readable form, which is the packager's module tree without needing the PDF's bookmark outline (see Smaller things). And it's built from the same source as the DOCX but keeps the ids the DOCX export drops, which is where the anchors for item 7 would have to come from.

## 5. Validating each output the way the manifest is validated

The cartridge is the one output the pipeline checks after building it: `validate-manifest.py` runs the manifest against the IMS schemas and reports what doesn't conform. Every other output is trusted. That is worth changing as outputs multiply, because each format has a validator that finds the same class of mistake -- structure that's well-formed and wrong -- and none of them is the kind of thing a person notices by looking at a page.

- **HTML**: the Nu HTML checker (`vnu.jar`, needs Java) for conformance; `pa11y` or `axe-core` for the accessibility rules that markup alone can be checked against, which is most of what the tables and links work produces.
- **EPUB**: `epubcheck` (Java) for the container and content, and DAISY's `Ace` for accessibility, which reports on exactly the table and image markup this project cares about.
- **PDF**: `veraPDF` for PDF/UA conformance, scriptable and cross-platform. PAC is Windows-only and interactive, and its two known defects (item 8) mean its output needs reading with that in mind.
- **DOCX**: Word's Accessibility Checker can't be driven from a script. `util/docx-compat.py`'s checks are what can be automated, and they're about the package, not the content.

The shape would be a `--check` per target, as the packager has today, run by `convert.sh` after the build and reported alongside the other reports rather than failing the run: a validator's findings are things to work through, and the run producing them is the point. Each tool wants installing separately, which is the argument for making every one optional and saying which ran.

## 6. Link text sidecar, for bare URLs

**Held, with item 7, until the WCAG question is settled.** Both items change what a link says or where it goes, and the question is the same for each: whether the result still meets the letter and the spirit of the guidelines. Here it's whether supplying an accessible name the visible text doesn't show -- so that a sighted reader and a screen reader user are given different link text -- is the right reading of 2.4.4, or whether the honest fix is to change the visible text so everyone sees it. The research below stands; what waits is the decision it feeds.

A reference list reads like this:

    Seidel, G. E. 2014. "Update on Sexed Semen Technology in Cattle." _Animal_ 8 (January):160--64. [https://doi.org/10.1017/S1751731114000202](https://doi.org/10.1017/S1751731114000202).

The link's visible text is the address. A screen reader announces all 57 characters of it, and the longest in *Introductory Business Statistics 2e* runs to 135 with `%20` and `+` escapes in the middle. There are 176 of them across 17 files in that book alone, 169 of them distinct, so the URL itself works as a sidecar key at almost exactly one row per link.

A sidecar maps each URL to a short description, which the filter attaches to the `Link` element as an `aria-label` attribute. That single annotation covers every output on this list:

- **HTML and EPUB3** need nothing further. Pandoc's writer emits the attribute as it stands, verified in both.
- **PDF** needs the attribute turned into the `/Contents` entry of the link annotation, which is what PDF/UA requires as a link's alternate description and what Acrobat announces. A filter for this already exists from another project and reads exactly the attribute above, so the two halves meet without either knowing about the other. What this gets us: in testing, Acrobat announces `/Contents`, browser PDF viewers ignore it. Every other mechanism — `/Alt` or `/ActualText` on a marked-content span, `/Alt` on the `Link` structure element — was tested against Acrobat and NVDA and announced nothing, and Edge announced nothing for any of them including `/Contents`. So the PDF half reaches Acrobat users and no one else, which is an argument for sequencing it after the HTML and EPUB halves rather than alongside them.
- **Markdown**, once item 3 lands, carries the annotation as the `{aria-label="..."}` attribute syntax it was authored in. This is the same markup my textbook project writes by hand, so a sidecar-generated description and an author-written one are indistinguishable downstream. The flavor matters: `markdown` and `commonmark_x` round-trip the attribute, while `gfm`, `commonmark`, and `markdown_strict` rewrite the whole link as a raw `<a>` element. The extension is spelled `link_attributes` for `markdown` and `attributes` for `commonmark_x`, verified on 3.11. That isn't a silent loss (it survives in the HTML) but reading such a file back gives a `RawInline` holding the opening tag, a bare `Link` stripped of its attributes, and a `RawInline` holding the closing tag. So a filter reading `Link.attributes` finds nothing, and the PDF half of this breaks. Any Markdown target needs the extension asserted rather than assumed. Item 5 has the detail.

### What has to be worked out

**Why a sidecar and not the source.** A Word hyperlink can hold a ScreenTip in `w:tooltip`, which would be the obvious place for a description and would let a remediated `.docx` carry its own. Pandoc's DOCX reader discards it: a tooltip injected by hand into `word/document.xml` comes back as `['', [], []]` on the `Link`, with the title slot empty too. So for DOCX input there's nowhere in the file for this to live, and a sidecar isn't a convenience but the only option short of pre-processing the OOXML. Relevant to the DOCX-output question in item 8, which would otherwise be the natural home for writing descriptions back into a corrected source.

**Detection.** Pandoc marks a bare URL with `class="uri"` when it comes from Markdown autolink syntax, but not when it comes from a `.docx`, so that signal isn't free. The rule that works: the link's text, normalized, equals its href. That found all 176 without hand-tuning.

**The guess.** The description is usually already sitting next to the URL, because a citation names its source before giving the address. Taking the text preceding the link within the same paragraph and trimming trailing punctuation produces a usable description for **77%** of them — *The Data and Story Library*, *Gallup-Healthways Well-Being Index*. The other 23% produce something visibly wrong, like *Data from*, which a person fixes in a few seconds. As with the table-headers sidecar, that's a starting point to correct rather than an answer.

Note that 144 of the 176 are in `-references.html` files and 32 are elsewhere, so the guess can't assume a citation is present.

**`aria-label` replaces the accessible name.** The URL stays visible while a screen reader hears the description instead, and WCAG 2.5.3 (Label in Name) asks that a control's accessible name contain its visible label. Strictly, this fails it. Practically, the risk is close to nil, since 2.5.3 exists so speech-input users can say what they see, and nobody dictates a 135-character URL.

Still worth deciding deliberately rather than by default, and the PDF testing argues for the alternative more strongly than it first appeared. Of seven mechanisms tested against NVDA, only the annotation `/Contents` announced anything, and only in Acrobat; `/ActualText` works but replaces what a reader copies, which for a DOI is a real loss. Descriptive visible text was the only option that worked in every viewer and needed nothing from the reader's stack. So: shorten the visible text to something readable, keep the full address in the `href`, and restore it for print with `@media print { a[href]::after { content: " (" attr(href) ")" } }`. That satisfies both WCAG criteria and asks nothing of tagged-PDF support. It changes what a reader sees on the page, which is a bigger decision than adding an attribute, but it's the one that reaches everybody.

**The LaTeX side needs a preamble.** The existing filter emits `\LinkAlt{...}` and `\LinkAltReset{}` around each link, and those macros live in a `link-alt-preamble.tex` that has to come along with it. It's also a no-op without `\DocumentMetadata` tagging enabled, so the PDF half of this arrives with item 8 rather than before it. The HTML and EPUB halves have no such dependency.

### Why it isn't harder than it looks

It's smaller than most of what is on this list and shares all its plumbing with the table headers sidecar that shipped in v0.3: report what needs a human, read a CSV, apply it, report what is still outstanding. That machinery is built and has one user, so this is the second, which is what tests whether it's actually general -- cheaper to find out with two than after a third sidecar is bolted on. What holds the item is the question above, not the work.

## 7. Rewriting links that point back at the publisher

**Held, with item 6, until the WCAG question is settled.** Rewriting a link changes where it goes, and the question is whether the result still meets the letter and the spirit of the guidelines: a link whose text and surrounding prose describe one destination (the publisher's page, with its anchor) would then lead somewhere else (a local page, possibly without the anchor), and that bears on how link purpose is judged. The measurements are done, so the work waits on that reading rather than on more investigation.

OpenStax's DOCX exports link within the book by absolute URL: a section quiz's answer link is `https://openstax.org/books/introduction-sociology-3e/pages/chapter-8#fs-id2627631-solution`, so a reader of the converted book is sent to the publisher's site instead of the page a few clicks away. Measured across five books, 11,306 such links, 9,911 of them with an anchor; in *Introduction to Sociology 3e* alone, 1,001 survive into the HTML and every one names a page that exists locally. The page half is a rewrite: `pages/<slug>` to `<slug>.html`, or whatever the target's page naming is. The anchor half is harder, and measured: none of the 927 anchors resolves, because the DOCX export carries no bookmarks (zero `w:bookmarkStart` in 243 files), so the `fs-id…` targets exist nowhere in the source. Two ways forward, not exclusive: rewrite to the page and drop the anchor, which is still a local link; or take anchors from the EPUB, which is built from the same source and should carry the ids -- one more argument for EPUB as an input. The `-solution` suffix is worth checking against the EPUB first, since it may be the web site's own convention rather than an id in the content. Belongs with the link work in item 6, which is already reading every link.

## 8. PDF, and DOCX output

**PDF** is gated on something outside this project. Pandoc 3.9 can drive LaTeX's tagging via `-V pdfstandard=ua-2`, but `latex-lab-table` states plainly that only simple header rows and columns are supported; that complex headers with subheaders need syntax changes not yet made; and that a cell `Headers` array (the mechanism the hard cases need) is an open item. Until that lands, a tagged PDF from this pipeline can carry simple tables correctly and can't carry the complex ones. Worth revisiting each LaTeX release rather than working around.

Three defects in the meantime are candidates for a post-processing pass with `pikepdf`, which is how they were diagnosed in the first place. [`util/contrib/fix-empty-paragraphs.py`](util/contrib/fix-empty-paragraphs.py) already handles one of them: LaTeX's tagging code opens paragraph structure elements that never receive content, around the longtable caption wrapper and around Pandoc's minipage header cells among others, and a checker reports each as an empty paragraph. It isn't wired in and hasn't been run against anything this pipeline produced. A longtable caption arrives tagged `TH` inside the repeated-header structure rather than as a `Caption` element, and retagging it means changing the element type, moving it out of the `TR`, and reparenting it under the `Table`: mechanical, and the structure tree is explicit enough to do it reliably. The `/ClassMap` case is easier still, since flattening a `/C` reference into an inline `/A` dictionary is a local rewrite. All three work around other people's open items, so each wants a check against the current `latex-lab` before being carried forward.

**Compatibility mode has to be carried, not silently upgraded.** `word/settings.xml` holds a `compatibilityMode` compat setting that tells Word which generation of layout rules to apply, and Word refuses to run its Accessibility Checker on anything below 15 until the file is converted. All 1,011 files in the four OpenStax books declare 12; the non-OpenStax book declares 15; Pandoc's bundled `reference.docx` declares nothing, so Pandoc output lands in compatibility mode too. Converting isn't free: Microsoft's [guidance](https://support.microsoft.com/en-us/word/converting-documents-to-a-newer-format) says Compatibility Mode preserves the document's layout and that Convert clears the compatibility options so the layout appears as it would under the newer version. Two OpenStax chapters converted by hand showed no visible change, which is reassuring for this corpus and not a general result. So: match the source by default, report the mode when it's below 15 or absent so the user knows the option exists, and make upgrading a declared setting rather than something the run decides. Upgrading needs no reference document: [`util/docx-compat.py`](util/docx-compat.py) reads the mode from any `.docx` and sets it afterwards, copying every other part through byte for byte and leaving any other compat settings (`overrideTableStyleFontSizeAndJustification` and friends) in place. Doing it after the fact rather than through a patched reference document means it works whatever reference document the user brought, and it applies to files we didn't write.

**DOCX output** is the riskier one, and deserves scoping care. The writer does preserve `w:tblHeader`, so in principle `table-headers-missing.csv` could stop being a report and start being an input that produces a corrected source document. But a Pandoc round trip discards everything Pandoc doesn't model: converting a file and back turned a layout table's `FigureTable` style into plain `Table`, and that style is the cleanest signal available for identifying layout tables. Section properties, content controls, comments, field codes, and tracked changes have the same exposure. If this is built, it should annotate the OOXML directly rather than rebuild the document. It's more code, but the difference between annotating and rebuilding.

## 9. Common Cartridge 1.3, for assignments

The 1.1 profile already carries everything this project emits today. Quizzes and question banks (`imsqti_xmlv1p2`), discussion topics, web links, LTI links, and the authorization attributes are all in 1.1. The only thing worth moving for is **assignments**, which arrive in 1.3.

The cost is reach. Brightspace and Canvas read up to 1.3, Blackboard up to 1.2, Moodle only to 1.1, so a 1.1 cartridge imports everywhere while a 1.3 one doesn't. So this isn't a migration but an option: a `cc_version` setting on the packaging target, defaulting to 1.1. The manifest differences are the namespace, the schemaversion, and the schema location, all already template substitutions, so the mechanism is small. But it requires a second set of schemas to validate against and a second set of resource types to emit correctly.

Worth doing when there's an assignment to ship, not before.

## 10. A web front end

Here's why the configuration is schema-driven and why conversion becomes a library: a front end needs to render a form from the settings that exist, write a complete config back without losing anything, and report progress and failures structurally.

Two pieces are already in place for it: the schema carries a description per setting, which is what a form's help text should say, and the writer is proven lossless by test. The third piece (resolving a config in JavaScript) is what the conformance fixtures in `tests/config/` exist to make safe.

## 11. Splitting into separate repositories

Eventually the two halves may be separate projects with a small shared library between them. Both standalone cases are already close: packaging is read-only with respect to page content and runs against any directory of HTML, and conversion has no packaging logic. v0.2 removed the last coupling, which was the config.

When that time comes, we'll need the library versioned and released on its own, and the conformance fixtures promoted from tests to a compatibility contract, ensuring that a conversion repo pinned to one version still resolves configs the same way as a packaging repo on another.

Not a goal in itself. Worth doing when one half has users the other doesn't.

## Refinements to the table headers work

The table headers sidecar shipped in v0.3 and is no longer a numbered item: the sidecar, the key, the pre-pass, the report, and the filter applying `first-row`, `first-column`, `both`, `none`, `caption-rows`, and `split-at`. What the conversion does with each is described in [the docs](docs/sidecars.md); why each rule reads the way it does is in `lib/tablecensus.py`. What follows is what that work left undone.

**A trailing summary row keeps its empty header cell.** A frequency table often ends with a row whose label cell is blank and whose other cells read `Total = 600`. The guess sets that row aside when deciding whether the first column keys its rows, because it summarizes the rows rather than being one of them, and five tables in five books land on `both` because of it. But `row_head_columns` covers every row of a `TableBody`, so the summary row's empty cell still becomes an empty `<th scope="row">`. Nothing fails, and a screen reader arriving at the total announces a blank row header first. The decision for now is to leave it and report it as possibly needing a hand, since `explain()` already names the condition. Worth revisiting whether to automate: the options are putting the summary row in its own `TableBody` so it falls outside the setting, or moving it to `TableFoot`, which is arguably what it's and which the HTML writer renders as `<tfoot>`. The same question returns with the grouping-band splits, so it's worth settling once for both.

**Two declarations are reserved and do nothing yet.** `list` says a table is a list snaked into columns; `caption-rows` is built, but `list` is not. Readers accept the value and treat it as blank, so a book can carry it before anything acts on it. Rebuilding the cells in column order as a `BulletList` is a few lines in a Lua filter and produces the right order, verified on 3.11. The caption is what makes it more than that, and all three routes were tested: a `Figure` wrapping the list gives correct HTML and a LaTeX float that renumbers as a figure, so a caption reading "Table 12.1" renders as "Figure 3: Table 12.1" and cross-references break; emitting the caption as a paragraph avoids that and leaves the caption unassociated with the list; transposing the table instead keeps `<caption>`, numbering, and cross-references and fails on width, since the real glossary is 9x3 and 3x9 runs off the page in PDF. So the work is format-specific caption handling -- `figure`/`figcaption` for HTML, something like `capt-of`'s `\captionof{table}` for LaTeX, which keeps the table counter without floating -- rather than the list construction.

**Where to sample the guess first.** 89 of the tables it calls `both` have two columns, and there `both` and `first-row` are both defensible. A screen reader on the value cell of `Labor | Wage` announces the row label as well, which helps someone who arrowed into the middle of the table and is verbose for someone reading it top to bottom. W3C's [one-header page](https://www.w3.org/WAI/tutorials/tables/one-header/) makes the case for the lighter markup on small tables where the data is unambiguous on its own. It stays `both` because the errors aren't symmetric -- a spurious `scope="row"` costs verbosity, a missing one loses the association -- and because carving out two-column tables would reverse the decision that `Data | Frequency` and `x | P(x)` are matrix tables. Worth sampling there first.

**Nothing records that a person looked.** Adopting `table-headers-new.csv` as the sidecar turns every guess into a declaration, including the ones nobody read: converting *Principles of Data Science* and renaming the file without editing a value gives 95 tables all reported `declared`, supplier `sidecar`. That is the design working -- a value is a value whoever supplied it -- but the report then can't separate a value someone confirmed from one adopted in bulk, which is exactly what a second pass over a book would want to know.

The report already carries both `declared` and `guess`, so a row where they differ is one somebody certainly changed. That is a proxy and not the thing: a reviewer who reads a table and agrees with the guess leaves no trace at all.

Recording the act needs a column of its own -- `reviewed`, holding initials and a date, or empty. Adding one is safe whenever it is wanted, and does not have to be decided now: the reader maps columns by name and ignores what it doesn't recognise, verified by appending a `reviewed` column to a real sidecar and running the pre-pass, which read it unchanged. So the question is whether the workflow wants it, not whether the format allows it, and the honest answer is that nobody has yet worked through a whole book twice.

**`mostly_numeric` uses `int(0.6 * n)`**, so a four-cell column that is half numeric counts as mostly numeric. It decides whether a bin column (`1`, `2`, `3-4`, `5+`) reaches the ordering test at all. Left alone rather than changed inside another change; worth tightening deliberately and re-measuring.

**`is_full_width_band` is true for every row of a one-column table**, which has caused three separate defects in the census. It wants a `wide` parameter or a name that says what it assumes.

### Shapes a header declaration can't describe

Two kinds of table have nothing wrong with their headers and something wrong with being tables at all. Both convert as tables for now; both are worth revisiting once the sidecar is in place, and they aren't equally urgent.

**Two declarations are reserved now and do nothing yet.** Readers should accept both and ignore them, so that adding the behavior later is a change to one filter rather than a change to the sidecar format every book already carries.

`list` declares that the table is a list snaked into columns; what that means is below.

`caption-rows=N,M` declares that those rows aren't part of the table and their content belongs in the caption, in the same syntax as `split-at`. A merged full-width first row is the inferred case, `caption-rows=1`. It isn't `split-at` under another name: that divides a table into parts, this removes a row and moves what it held. `11-5-race-and-ethnicity-in-the-united-states.docx` is the case -- it opens with `Population estimates, July 1, 2019 | 328,239,523`, a fact about the whole table sitting above the real header row, which is why that table is the corpus's only `unknown`. Folded into the caption it reads as one sentence and leaves an ordinary `both` table underneath. Two things to settle when it's built: how the cells of the removed row are joined into caption text (a colon between the two here, but that's one example), and what happens when the table already has a caption, since a book that labels its tables will have one.

**A list snaked into columns.** Four tables in the programming book in our test corpus are glossaries laid out three columns wide, running alphabetically down column one and then down column two. Read across the rows, which is what HTML and a screen reader do, the order becomes `Class, JavaDoc, private` and the alphabetical sequence is gone. `none` is the right value and says nothing about the problem. This one is a real defect: the content reaches the reader in an order the author didn't write. `util/table-samples.py` recognizes the shape well enough to show examples (two or more columns individually sorted, short text cells, no numbers, row-major order not sorted), but two genuine data tables elsewhere have sorted columns by coincidence, so it's a prompt to look rather than something to act on. That is also why it has to be a declared value rather than something the conversion decides: turning a real data table into a list would destroy structure that's doing work.

Rebuilding the cells in column order as a `BulletList` is a few lines in a Lua filter and produces the right order, verified on 3.11. The caption is what makes it more than that, and all three routes were tested:

- A `Figure` wrapping the list gives correct HTML (`<figure><ul>…</ul><figcaption>`) and wrong LaTeX: the content becomes a float and is numbered as a figure, so a caption reading "Table 12.1" renders as "Figure 3: Table 12.1" and every cross-reference to it breaks.
- Emitting the caption as a paragraph avoids both problems and leaves the caption unassociated with the list, which is what a caption is for.
- Transposing the table instead, so row-major reading follows the original columns, keeps `<caption>`, numbering, and cross-references untouched and is much the smallest change. It fails on width: the real glossary is 9x3, and 3x9 runs off the page in PDF.

So the work is format-specific caption handling -- `figure`/`figcaption` for HTML, something like `capt-of`'s `\captionof{table}` for LaTeX, which keeps the table counter without floating -- rather than the list construction. Worth doing deliberately, after the value vocabulary is settled.

**Parallel lists in a grid.** `BC-11.docx` Table 35.1 is a Do and Don't table: two columns of advice, marked up with a header row. Whether the rows mean anything is the question, and here they do -- each row is one piece of advice stated both ways -- so `first-row` describes it correctly and reading across a row is coherent. The test is whether either column could be shuffled independently without changing the meaning. Where it could, the row structure is spurious and the content is two lists; where it couldn't, the table is doing real work.

The distinction between the two matters more than either case. A table whose reading order is wrong is an accessibility defect. A table heavier than its content needs is a style judgment about someone else's book, and we should be slow to act on those.

## Smaller things

- **Read the contents tree from an EPUB as well as a PDF.** `build-cartridge.py` builds the module tree from a PDF's bookmark outline, which is the book's table of contents in the order the book actually uses. An EPUB carries the same thing in machine-readable form -- `nav.xhtml` with `epub:type="toc"` in EPUB 3, `toc.ncx` in EPUB 2 -- so the same walk produces the same `(depth, title)` list without needing `pypdf`, and OpenStax publishes EPUBs. The matching of titles to page filenames is unchanged; only the source of the entries differs.
- **Watch [pandoc#3034](https://github.com/jgm/pandoc/issues/3034).** The DOCX and ODT readers ignore `docProps/core.xml`, so a Word file whose title is set through File → Info → Properties converts with no metadata at all: the standalone HTML `<title>` falls back to the filename and the EPUB OPF gets no `dc:title`. If the reader ever picks those up, `promote_h1_to_title` and the duplicate-H1 guard both need rechecking, since the condition they turn on is `doc.meta.title == nil`.
- **Retired key names.** Writing `manifest.cartridge` into a v0.2 config fails with "unknown setting" and no suggestion, because nothing is similarly named. A small table of retired names would let the error say where it went instead.
- **`compare-output.py` matches tables by position**, so one inserted table reports every later one on that page as changed. Matching on caption could help, but not every table has one.
- **A media inventory for the comparator.** It reports files and references; comparing image dimensions or bytes-per-page would catch a class of regression it currently can't see.
- **Cross-page links aren't rewritten** for an LMS's internal link format, so links between sections may not resolve after import.
- **Deduplicating identical media.** Each page of a DOCX gets its own copy from Word. Sharing them would shrink a cartridge substantially but requires rewriting page markup. Worth more than it looks: an LMS that doesn't reclaim images when a module is deleted (looking at you, Brightspace!) accumulates every copy, so the duplication is paid for repeatedly rather than once.
- **One media directory per book** rather than per page. Pandoc's `--extract-media` produces `<page>/media/`, which inside a prefixed package means a directory per page. Flattening to `<prefix>/media/` would make the leftovers after a deletion one folder to remove instead of dozens. Cosmetic, but the cleanup is manual.

