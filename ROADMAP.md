# Roadmap

What's planned, in the order that seems most productive.

We are attempting to follow two principles: build the tool that can check a change before making the change and, where a decision can't be made by a script, make it declarable by a person once.

## 1. Table headers sidecar

A CSV declaring, per table, which lines hold its headers: `first-row`, `first-column`, `both`, or `none`. The conversion applies it, so the same declaration drives every output format.

**Status: built, on the `table-headers` branch.** The sidecar, the key, the pre-pass, and the report exist; the filter applies the value in effect (`first-row`, `first-column`, `both`, `none`; a blank, `manual`, and `list` leave the table as Pandoc gave it); `caption-rows` folds named rows into the caption, with `caption-rows=1` inferred for a merged title row; and `split-at` makes one table per band, inferred for merged rows below row 1. What remains is the merge to `main` and a release.

The values are named for the line that holds the headers, which is how [`latex-lab-table`](https://ctan.org/pkg/latex-lab) names `table/header-rows` and `table/header-columns` and how Pandoc names `row_head_columns`. Earlier drafts of this file used `col`, `row`, `matrix`, and `grid`, where `col` meant a header *row*: that reads as the opposite of the LaTeX keys and is gone. `matrix` and `grid` stay acceptable as aliases for `both` and `none`, because `matrix` is what my textbook's fenced divs already say.

A census of four OpenStax books found 687 data tables among 1,716. Formatting alone classifies most of them, but the interesting distinction can't be read from the file at all: a contingency table's category column and a frequency table's interval column are byte-for-byte identical in the DOCX, and only one of them wants `scope="row"`. That's what the sidecar is for.

### The guess

The generated report carries a best guess, produced by `util/table-census.py` and checked by `tests/run-census-tests.py`. Across the four books it gives 332 `both` (48%), 289 `first-row` (42%), 60 `none` (9%), and 6 `first-column` (1%). The proportions differ by book rather than being a property of OpenStax: *Introductory Business Statistics 2e* is 61% `both`, *Principles of Data Science* is 60% `first-row`, and *Principles of Marketing* has 22 data tables in 250.

The rule that produces it: a first column that keys its rows, over a body of values, is headers. Keying means every cell filled and no value repeated. Two conditions stop that from over-firing. The body has to be mostly numeric, so a table of descriptions stays `first-row`: a prose body reads as a list rather than a matrix. And a *numeric* first column only counts if it is ordered. 110 tables turn on that last one and they split 78/32. The ordered side is lookup axes (Year, Price Level, `z`, a frequency table's Data column), the unordered side is homogeneous measurements where row 1 names three groups and there is no label column at all. Formatting that already proves a header column wins over the rule where they disagree, which is 8 tables.

Where the guess is soft rather than wrong: 89 of the tables it calls `both` have two columns, and there `both` and `first-row` are both defensible. A screen reader on the value cell of `Labor | Wage` announces the row label as well, which helps someone who arrowed into the middle of the table and is verbose for someone reading it top to bottom. W3C's [one-header page](https://www.w3.org/WAI/tutorials/tables/one-header/) makes the case for the lighter markup on small tables where the data is unambiguous on its own. It stays `both` because the errors are not symmetric -- a spurious `scope="row"` costs verbosity, a missing one loses the association -- and because carving out two-column tables would reverse the decision that `Data | Frequency` and `x | P(x)` are matrix tables. Worth sampling there first.

Residual error is small but real. Of the tables guessed `both`, five have parallel column headers (`Team 1 | Team 2 | Team 3`), and two of those five are genuinely a first data column that happens to ascend. The guess is a starting point to correct, not an answer.

Two shapes to read past before any of this applies: a merged full-width first row, which becomes a `<caption>`, and a wholly empty first row, which three tables in the data science book use above their real header row. Reading either as the header row calls an ordinary table headerless. In a one-column table every row spans the width trivially, so the first test has to be off there or it consumes the table.

**A trailing summary row keeps its empty header cell, for now.** A frequency table often ends with a row whose label cell is blank and whose other cells read `Total = 600`. The guess sets that row aside when deciding whether the first column keys its rows, because it summarizes the rows rather than being one of them, and five tables in five books land on `both` because of it. But `row_head_columns` covers every row of a `TableBody`, so the summary row's empty cell still becomes an empty `<th scope="row">`. Nothing fails, and a screen reader arriving at the total announces a blank row header first. The decision for now is to leave it and report it as possibly needing a hand, since `explain()` already names the condition. Worth revisiting whether to automate: the options are putting the summary row in its own `TableBody` so it falls outside the setting, or moving it to `TableFoot`, which is arguably what it is and which the HTML writer renders as `<tfoot>`. The same question returns with the grouping-band splits, so it is worth settling once for both.

Also here: promote a merged full-width first row to `<caption>` rather than treating it as a header row, which folds five tables in the statistics book into the existing caption machinery. The guess already reads past such a row, so the value describes the table as it will be after the promotion.

### Shapes a header declaration cannot describe

Two kinds of table have nothing wrong with their headers and something wrong with being tables at all. Both convert as tables for now; both are worth revisiting once the sidecar is in place, and they are not equally urgent.

**Two declarations are reserved now and do nothing yet.** Readers should accept both and ignore them, so that adding the behavior later is a change to one filter rather than a change to the sidecar format every book already carries.

`list` declares that the table is a list snaked into columns; what that means is below.

`caption-rows=N,M` declares that those rows are not part of the table and their content belongs in the caption, in the same syntax as `split-at`. A merged full-width first row is the inferred case, `caption-rows=1`. It is not `split-at` under another name: that divides a table into parts, this removes a row and moves what it held. `11-5-race-and-ethnicity-in-the-united-states.docx` is the case -- it opens with `Population estimates, July 1, 2019 | 328,239,523`, a fact about the whole table sitting above the real header row, which is why that table is the corpus's only `unknown`. Folded into the caption it reads as one sentence and leaves an ordinary `both` table underneath. Two things to settle when it is built: how the cells of the removed row are joined into caption text (a colon between the two here, but that is one example), and what happens when the table already has a caption, since a book that labels its tables will have one.

**A list snaked into columns.** Four tables in the programming book are glossaries laid out three columns wide, running alphabetically down column one and then down column two. Read across the rows, which is what HTML and a screen reader do, the order becomes `Class, JavaDoc, private` and the alphabetical sequence is gone. `none` is the right value and says nothing about the problem. This one is a real defect: the content reaches the reader in an order the author did not write. `util/table-samples.py` recognizes the shape well enough to show examples (two or more columns individually sorted, short text cells, no numbers, row-major order not sorted), but two genuine data tables elsewhere have sorted columns by coincidence, so it is a prompt to look rather than something to act on. That is also why it has to be a declared value rather than something the conversion decides: turning a real data table into a list would destroy structure that is doing work.

Rebuilding the cells in column order as a `BulletList` is a few lines in a Lua filter and produces the right order, verified on 3.11. The caption is what makes it more than that, and all three routes were tested:

- A `Figure` wrapping the list gives correct HTML (`<figure><ul>…</ul><figcaption>`) and wrong LaTeX: the content becomes a float and is numbered as a figure, so a caption reading "Table 12.1" renders as "Figure 3: Table 12.1" and every cross-reference to it breaks.
- Emitting the caption as a paragraph avoids both problems and leaves the caption unassociated with the list, which is what a caption is for.
- Transposing the table instead, so row-major reading follows the original columns, keeps `<caption>`, numbering, and cross-references untouched and is much the smallest change. It fails on width: the real glossary is 9x3, and 3x9 runs off the page in PDF.

So the work is format-specific caption handling -- `figure`/`figcaption` for HTML, something like `capt-of`'s `\captionof{table}` for LaTeX, which keeps the table counter without floating -- rather than the list construction. Worth doing deliberately, after the value vocabulary is settled.

**Parallel lists in a grid.** `BC-11.docx` Table 35.1 is a Do and Don't table: two columns of advice, marked up with a header row. Whether the rows mean anything is the question, and here they do -- each row is one piece of advice stated both ways -- so `first-row` describes it correctly and reading across a row is coherent. The test is whether either column could be shuffled independently without changing the meaning. Where it could, the row structure is spurious and the content is two lists; where it could not, the table is doing real work.

The distinction between the two matters more than either case. A table whose reading order is wrong is an accessibility defect. A table heavier than its content needs is a style judgment about someone else's book, and we should be slow to act on those.

### Splitting grouping-band tables

Twelve tables across the five books have a merged full-width row partway down, labeling the rows beneath it, 34 such rows in total. They are all genuine merges and the census sees all of them; an earlier draft of this section claimed one book wrote its bands as repeated text instead, which was wrong. The largest is `d-appendix-d-review-of-python-functions.docx`, 85 rows with seven bands. `<th colspan="N" scope="rowgroup">` is the canonical HTML answer, but `scope="rowgroup"` has thin screen reader support, PDF's `Scope` has no rowgroup value, and a cell `Headers` array is an open item in `latex-lab-table`. So the sidecar takes `split-at=1,6,11` instead and each band starts a new table with the band text as its caption. That works identically in HTML and LaTeX, and for `7-5-costs-in-the-long-run.docx` it is a truer reading of the source, which really is three tables Word glued together.

Two things the build settled that the plan had wrong. First, that table's bands each sit over their own header row -- "Example A", then `| Labor Cost | Machine Cost | Total Cost`, then the data, then "Example B" and another header row -- so "every part gets a copy of the original header row" is right only where the table had one marked in Word; otherwise each part's own first row is promoted by the header declaration, applied per part. Second, row 1 there is a band, not a title, and the pre-pass tells the two apart by whether there are bands below: a merged row 1 alone is `caption-rows=1`, a merged row 1 with bands beneath joins `split-at`. The guess for a banded table is taken part by part with any shared header rows in place, and the parts vote; read whole, the bands break every rule and such a table guessed `none`.

Third, a band need not be a merged row. Table 7.2 of the sociology book repeats its bold header row three times with a different group name in the corner -- Functionalism, Conflict Theory, Symbolic Interactionism -- over `| Associated Theorist | Deviance arises from:`. Of the eighteen tables in seven books with header-looking rows below row 1, three have exactly this shape and nothing else does, so it is inferred. The filter tells the two kinds of split row apart from the row itself: one merged cell across the table is a caption, several cells cannot be, so the row heads its part and only its corner cell goes into the caption.

### Keys

A key has to survive the source being reissued, and it has to survive us splitting a table. Position survives neither. Content hashing survives both, and the collision worry turns out to be backwards: if two tables have identical content they want identical headers, so a collision is a feature.

Measured on the three books, a hash over the whole normalized cell text plus the table's shape gives 15 duplicate groups covering 31 tables, and **no group whose members the guess treats differently**. A narrower hash over just the header row, first column, and shape gives 36 groups covering 76 tables, of which 4 disagree. So the narrow hash buys robustness against an edit in a data cell at the cost of merging tables that want different declarations, and the full hash is the better trade on this corpus.

The split case falls out of this: we are the ones splitting, so we can compute each sub-table's hash before writing anything and record it against the parent's row. Nothing has to be rediscovered on a later pass.

A DOCX-to-DOCX round trip is the one case this does not reach, since the output's tables are new tables. That is also the one case where we are already rewriting the publisher's file, so a bookmark per table written at that point is affordable there and nowhere else.

### Where the declaration comes from

The CSV is one supplier and not the only one, but it is always available and it wins.

- **DOCX** has nowhere to put a declaration, so the CSV is all there is.
- **Markdown** can carry it in a fenced div, which is what my textbook does with `::: matrix :::`. The marker names have to be configurable, since another author will have chosen differently, and an unmarked table has to stay distinguishable from one marked and declared, so that a fresh batch from that author is still reportable.
- **HTML** may carry `scope` and `headers` already, which we preserve, and may carry nothing, which is the unmarked case again.

The default for an unmarked table is a declared setting rather than a constant. `first-row` is right for a book whose tables all have header rows and wrong for a corpus with 60 genuine data grids in it.

### Which Pandoc this needs

Not a newer one. Setting `row_head_columns` from a Lua filter, and setting `scope` on a cell's attributes, produce identical HTML on 3.1.3, 3.9, and 3.11, and survive to EPUB3 unchanged on 3.9 and 3.11. So item 1 adds no version pressure and the project's existing floor of 3.9 stands.

Two version facts that bear on it anyway. Pandoc's DOCX reader treated `<w:tblHeader w:val="0"/>` as marking a header row until 3.10, so on an earlier version a deliberately disabled header row reads as a header. None of the 1,011 files in the four books carries one (590 `tblHeader` elements, none disabled), so the census figures are unaffected, but the next corpus may differ. And spanning cells only round-trip through the Markdown writer from 3.7, which matters for the complex tables item 1 does not cover.

### What the PDF half can and cannot do

`table/header-columns={1}` is the mechanism, and it is what my `matrix-headers.lua` already emits. Three things about it are worth writing down before anyone builds on it.

The setting is ambient, not per-table. [The documentation](https://ctan.org/pkg/latex-lab) says it applies to all tables until changed or emptied, so the pattern is set-before and reset-after around each table, which is self-contained and works for a filter that knows nothing about the surrounding document. There is no per-table argument to pass.

`table/header-rows` is ignored whenever `\endhead` or `\endfirsthead` is present, which for Pandoc is always, because Pandoc emits `longtable` for everything. The documentation is explicit: in a longtable the code uses the `\endhead` or `\endfirsthead` rows as the header and in that case ignores `table/header-rows`. So the header row is tagged `TH` either way, and setting the key changes nothing; the column key is the only one whose value alters the output. If we ever emitted `tabular` inside a float instead, that would reverse: there is no `\endhead` to read, and `table/header-rows={1}` would become the only thing marking the header row. A cell falling under both settings gets `TH-both`, so a matrix table's blank corner gets `Scope=Both` for free.

A longtable `\caption` is typeset as a multicolumn inside `\endfirsthead` and is tagged `TH` rather than `Caption`. So the caption promotion above produces correct markup in HTML and EPUB and an incorrectly tagged header row in PDF, through no fault of ours. Either post-process the PDF to retag it (see item 9) or accept it until `latex-lab` handles longtable captions.

### Two PAC errors that are not ours

Both are described, with citations, in [Troubleshooting and known limits](docs/troubleshooting.md#known-limits): the `/ClassMap` attribute class PAC does not resolve, and the `Artifact` under `Table` it rejects though ISO 32000-2 permits it. Item 1's output will trip both, and neither is a defect to chase.

**Why now.** It is the largest accessibility gap remaining, it is independent of everything else, and the schema is in place so it arrives as a declared setting rather than another environment variable.

## 2. Link text sidecar, for bare URLs

A reference list reads like this:

    Seidel, G. E. 2014. "Update on Sexed Semen Technology in Cattle." _Animal_ 8 (January):160--64. [https://doi.org/10.1017/S1751731114000202](https://doi.org/10.1017/S1751731114000202).

The link's visible text is the address. A screen reader announces all 57 characters of it, and the longest in *Introductory Business Statistics 2e* runs to 135 with `%20` and `+` escapes in the middle. There are 176 of them across 17 files in that book alone, 169 of them distinct, so the URL itself works as a sidecar key at almost exactly one row per link.

A sidecar maps each URL to a short description, which the filter attaches to the `Link` element as an `aria-label` attribute. That single annotation covers every output on this list:

- **HTML and EPUB3** need nothing further. Pandoc's writer emits the attribute as it stands, verified in both.
- **PDF** needs the attribute turned into the `/Contents` entry of the link annotation, which is what PDF/UA requires as a link's alternate description and what Acrobat announces. A filter for this already exists from another project and reads exactly the attribute above, so the two halves meet without either knowing about the other. What this gets us: in testing, Acrobat announces `/Contents`, browser PDF viewers ignore it. Every other mechanism — `/Alt` or `/ActualText` on a marked-content span, `/Alt` on the `Link` structure element — was tested against Acrobat and NVDA and announced nothing, and Edge announced nothing for any of them including `/Contents`. So the PDF half reaches Acrobat users and no one else, which is an argument for sequencing it after the HTML and EPUB halves rather than alongside them.
- **Markdown**, once it is an output format (item 5), carries the annotation as the `{aria-label="..."}` attribute syntax it was authored in. This is the same markup my textbook project writes by hand, so a sidecar-generated description and an author-written one are indistinguishable downstream. The flavor matters: `markdown` and `commonmark_x` round-trip the attribute, while `gfm`, `commonmark`, and `markdown_strict` rewrite the whole link as a raw `<a>` element. The extension is spelled `link_attributes` for `markdown` and `attributes` for `commonmark_x`, verified on 3.11. That is not a silent loss (it survives in the HTML) but reading such a file back gives a `RawInline` holding the opening tag, a bare `Link` stripped of its attributes, and a `RawInline` holding the closing tag. So a filter reading `Link.attributes` finds nothing, and the PDF half of this breaks. Any Markdown target needs the extension asserted rather than assumed. Item 5 has the detail.

### What has to be worked out

**Why a sidecar and not the source.** A Word hyperlink can hold a ScreenTip in `w:tooltip`, which would be the obvious place for a description and would let a remediated `.docx` carry its own. Pandoc's DOCX reader discards it: a tooltip injected by hand into `word/document.xml` comes back as `['', [], []]` on the `Link`, with the title slot empty too. So for DOCX input there is nowhere in the file for this to live, and a sidecar is not a convenience but the only option short of pre-processing the OOXML. Relevant to the DOCX-output question in item 9, which would otherwise be the natural home for writing descriptions back into a corrected source.

**Detection.** Pandoc marks a bare URL with `class="uri"` when it comes from Markdown autolink syntax, but not when it comes from a `.docx`, so that signal is not free. The rule that works: the link's text, normalized, equals its href. That found all 176 without hand-tuning.

**The guess.** The description is usually already sitting next to the URL, because a citation names its source before giving the address. Taking the text preceding the link within the same paragraph and trimming trailing punctuation produces a usable description for **77%** of them — *The Data and Story Library*, *Gallup-Healthways Well-Being Index*. The other 23% produce something visibly wrong, like *Data from*, which a person fixes in a few seconds. As with the table-headers sidecar, that is a starting point to correct rather than an answer.

Note that 144 of the 176 are in `-references.html` files and 32 are elsewhere, so the guess can't assume a citation is present.

**`aria-label` replaces the accessible name.** The URL stays visible while a screen reader hears the description instead, and WCAG 2.5.3 (Label in Name) asks that a control's accessible name contain its visible label. Strictly, this fails it. Practically, the risk is close to nil, since 2.5.3 exists so speech-input users can say what they see, and nobody dictates a 135-character URL.

Still worth deciding deliberately rather than by default, and the PDF testing argues for the alternative more strongly than it first appeared. Of seven mechanisms tested against NVDA, only the annotation `/Contents` announced anything, and only in Acrobat; `/ActualText` works but replaces what a reader copies, which for a DOI is a real loss. Descriptive visible text was the only option that worked in every viewer and needed nothing from the reader's stack. So: shorten the visible text to something readable, keep the full address in the `href`, and restore it for print with `@media print { a[href]::after { content: " (" attr(href) ")" } }`. That satisfies both WCAG criteria and asks nothing of tagged-PDF support. It changes what a reader sees on the page, which is a bigger decision than adding an attribute, but it is the one that reaches everybody.

**The LaTeX side needs a preamble.** The existing filter emits `\LinkAlt{...}` and `\LinkAltReset{}` around each link, and those macros live in a `link-alt-preamble.tex` that has to come along with it. It is also a no-op without `\DocumentMetadata` tagging enabled, so the PDF half of this arrives with item 9 rather than before it. The HTML and EPUB halves have no such dependency.

### Why second

It is smaller than anything else on this list and shares all its plumbing with item 1: report what needs a human, read a CSV, apply it, report what is still outstanding. Building that machinery once with two users tests whether it is actually general, which is cheaper to find out now than after a third sidecar is bolted onto it.

## 3. EPUB3 output

One EPUB per book, its table of contents built from the same `contents` the cartridge organization uses. A per-chapter variant follows from the targets mechanism once the first one works.

Nearly free on the table side: EPUB3 uses Pandoc's HTML writer, so `id`, `colspan`, `rowspan`, `scope`, `headers`, and `role` all survive unchanged. The real work is the package document. Pandoc emits accessibility metadata unconditionally and asserts things it can't know: `accessMode: textual` for books that are 820 figures, and `accessibilityFeature: alternativeText` whether or not the images have any. `--epub-metadata` silently drops `schema:` properties, so correcting this means post-processing the OPF inside the archive. An EPUB claiming alt text it does not have is worse than one claiming nothing, because catalogs and assistive technology act on that claim.

**Why second.** A second consumer of the table sidecar is the only real test that it describes semantics rather than HTML markup. Defer every output format to the end and HTML assumptions get baked in while nothing pushes back.

## 4. Multiple targets, and `convert.sh` rewritten in Python

The configuration already describes several conversion targets and several packages, each overriding the defaults. Making them real means: building each target into its own output directory, reusing one parsed intermediate across targets that do not override media, and ordering builds from what a package declares it `includes` rather than from the order blocks appear in a file.

`convert.sh` becomes Python at the same time. Adding N targets restructures most of it anyway, and rewriting a script you are about to gut is much cheaper than rewriting one you mean to keep. The argument for Python is mostly the front end in item 11: a web interface shelling out to bash and scraping stderr can't ask what targets exist, can't report progress per document, and can't tell a media failure from a Pandoc failure without parsing prose. Conversion needs to be callable, not just runnable.

The accumulated knowledge in the comments — the Word lock-file check, the zip-signature test for a renamed `.doc`, the cloud-drive write retry, the EMF/WMF guidance — has to carry across verbatim. A rewrite is exactly where that gets dropped. `set -x` tracing needs a deliberate equivalent, too: seeing every Pandoc invocation as it happens has been useful more than once.

`compare-output.py` makes this checkable. The rewrite is done when it says `Runs agree`.

## 5. Markdown output

Pandoc writes Markdown already, so the work is small: a target with a format, and two decisions.

**The flavor is not free.** It has to be `markdown` or `commonmark_x`. Those round-trip a link's `{aria-label="..."}` attribute; `gfm`, `commonmark`, and `markdown_strict` rewrite the whole link as a raw `<a>` element instead, and reading such a file back gives a `RawInline` holding the tag, a `Link` stripped of its attributes, and another `RawInline`. So the description survives visually and stops being reachable by any filter that looks at `Link.attributes`. The extension has to be asserted on the target rather than assumed, and it is not spelled the same way in both: `link_attributes` for `markdown`, `attributes` for `commonmark_x`.

**Tables do not survive.** Markdown has no syntax for a header column, a cell attribute, or a `scope`, which is most of what item 1 produces. A Markdown target therefore can't be an accessible deliverable: it is a source format. That is a reasonable thing to want: converting an OER `.docx` into editable Pandoc Markdown is how a book gets maintained rather than merely republished, and it's the form my textbook project authors in. But the report files remain the record of the accessibility work, and regenerating HTML from the Markdown would need the sidecars applied again.

Links are the exception: a Markdown source can carry its own `aria-label`, so a book maintained as Markdown needs no link sidecar. See items 2 and 6, which is the reading half of the same point.

**Why here.** Its only dependency is the targets mechanism above. It's the cheapest output on this list, it's not blocked on anything external the way PDF is, and it's the one that turns this project from a one-way converter into something a book can be maintained in.

## 6. More input formats

Markdown and HTML alongside DOCX. This mostly follows from the JSON architecture: a reader is a reader.

HTML in particular opens same-format remediation, reading an HTML file and writing it back improved. Pandoc's HTML reader preserves `scope`, `headers`, `id`, and `role`, so this round-trips, which gives a testable invariant worth having: **running the pipeline on its own output should change nothing.** That is a stronger regression test than golden files, because it catches any filter that applies twice or acts non-deterministically. Note the fixed point is reached after one pass, not zero: the reader normalizes irregular tables on the way in.

Markdown is the weakest input for tables: it can't express a header column or a cell attribute, so the sidecar carries proportionally more of the load. Links are the exception. Markdown can carry an `aria-label` on a link directly, in the same `{aria-label="..."}` syntax the writer emits, so for item 2 a Markdown source needs no sidecar at all: the annotation is authorable in the file. Subject to the flavor caveat noted there: `link_attributes` has to be on, or the reader sees a raw `<a>` element rather than a `Link`.

## 7. Rewriting links that point back at the publisher

**Held until the consequences for license compliance are understood.** Rewriting a link changes what a page says about where its content came from, and OpenStax's license terms are worth reading against that before anything is built. The measurements are done, so the work waits on that reading rather than on more investigation.

OpenStax's DOCX exports link within the book by absolute URL: a section quiz's answer link is `https://openstax.org/books/introduction-sociology-3e/pages/chapter-8#fs-id2627631-solution`, so a reader of the converted book is sent to the publisher's site instead of the page a few clicks away. Measured across five books, 11,306 such links, 9,911 of them with an anchor; in *Introduction to Sociology 3e* alone, 1,001 survive into the HTML and every one names a page that exists locally. The page half is a rewrite: `pages/<slug>` to `<slug>.html`, or whatever the target's page naming is. The anchor half is harder, and measured: none of the 927 anchors resolves, because the DOCX export carries no bookmarks (zero `w:bookmarkStart` in 243 files), so the `fs-id…` targets exist nowhere in the source. Two ways forward, not exclusive: rewrite to the page and drop the anchor, which is still a local link; or take anchors from the EPUB, which is built from the same source and should carry the ids -- one more argument for EPUB as an input. The `-solution` suffix is worth checking against the EPUB first, since it may be the web site's own convention rather than an id in the content. Belongs with the link work in item 2, which is already reading every link.

## 8. Validating each output the way the manifest is validated

The cartridge is the one output the pipeline checks after building it: `validate-manifest.py` runs the manifest against the IMS schemas and reports what does not conform. Every other output is trusted. That is worth changing as outputs multiply, because each format has a validator that finds the same class of mistake -- structure that is well-formed and wrong -- and none of them is the kind of thing a person notices by looking at a page.

- **HTML**: the Nu HTML checker (`vnu.jar`, needs Java) for conformance; `pa11y` or `axe-core` for the accessibility rules that markup alone can be checked against, which is most of what the tables and links work produces.
- **EPUB**: `epubcheck` (Java) for the container and content, and DAISY's `Ace` for accessibility, which reports on exactly the table and image markup this project cares about.
- **PDF**: `veraPDF` for PDF/UA conformance, scriptable and cross-platform. PAC is Windows-only and interactive, and its two known defects (item 9) mean its output needs reading with that in mind.
- **DOCX**: Word's Accessibility Checker cannot be driven from a script. `util/docx-compat.py`'s checks are what can be automated, and they are about the package, not the content.

The shape would be a `--check` per target, as the packager has today, run by `convert.sh` after the build and reported alongside the other reports rather than failing the run: a validator's findings are things to work through, and the run producing them is the point. Each tool wants installing separately, which is the argument for making every one optional and saying which ran.

## 9. PDF, and DOCX output

**PDF** is gated on something outside this project. Pandoc 3.9 can drive LaTeX's tagging via `-V pdfstandard=ua-2`, but `latex-lab-table` states plainly that only simple header rows and columns are supported; that complex headers with subheaders need syntax changes not yet made; and that a cell `Headers` array (the mechanism the hard cases need) is an open item. Until that lands, a tagged PDF from this pipeline can carry simple tables correctly and can't carry the complex ones. Worth revisiting each LaTeX release rather than working around.

Three defects in the meantime are candidates for a post-processing pass with `pikepdf`, which is how they were diagnosed in the first place. [`util/contrib/fix-empty-paragraphs.py`](util/contrib/fix-empty-paragraphs.py) already handles one of them: LaTeX's tagging code opens paragraph structure elements that never receive content, around the longtable caption wrapper and around Pandoc's minipage header cells among others, and a checker reports each as an empty paragraph. It is not wired in and has not been run against anything this pipeline produced. A longtable caption arrives tagged `TH` inside the repeated-header structure rather than as a `Caption` element, and retagging it means changing the element type, moving it out of the `TR`, and reparenting it under the `Table`: mechanical, and the structure tree is explicit enough to do it reliably. The `/ClassMap` case is easier still, since flattening a `/C` reference into an inline `/A` dictionary is a local rewrite. All three work around other people's open items, so each wants a check against the current `latex-lab` before being carried forward.

**Compatibility mode has to be carried, not silently upgraded.** `word/settings.xml` holds a `compatibilityMode` compat setting that tells Word which generation of layout rules to apply, and Word refuses to run its Accessibility Checker on anything below 15 until the file is converted. All 1,011 files in the four OpenStax books declare 12; the non-OpenStax book declares 15; Pandoc's bundled `reference.docx` declares nothing, so Pandoc output lands in compatibility mode too. Converting is not free: Microsoft's [guidance](https://support.microsoft.com/en-us/word/converting-documents-to-a-newer-format) says Compatibility Mode preserves the document's layout and that Convert clears the compatibility options so the layout appears as it would under the newer version. Two OpenStax chapters converted by hand showed no visible change, which is reassuring for this corpus and not a general result. So: match the source by default, report the mode when it is below 15 or absent so the user knows the option exists, and make upgrading a declared setting rather than something the run decides. Upgrading needs no reference document: [`util/docx-compat.py`](util/docx-compat.py) reads the mode from any `.docx` and sets it afterwards, copying every other part through byte for byte and leaving any other compat settings (`overrideTableStyleFontSizeAndJustification` and friends) in place. Doing it after the fact rather than through a patched reference document means it works whatever reference document the user brought, and it applies to files we did not write.

**DOCX output** is the riskier one, and deserves scoping care. The writer does preserve `w:tblHeader`, so in principle `table-headers-missing.csv` could stop being a report and start being an input that produces a corrected source document. But a Pandoc round trip discards everything Pandoc does not model: converting a file and back turned a layout table's `FigureTable` style into plain `Table`, and that style is the cleanest signal available for identifying layout tables. Section properties, content controls, comments, field codes, and tracked changes have the same exposure. If this is built, it should annotate the OOXML directly rather than rebuild the document. It's more code, but the difference between annotating and rebuilding.

## 10. Common Cartridge 1.3, for assignments

The 1.1 profile already carries everything this project emits today. Quizzes and question banks (`imsqti_xmlv1p2`), discussion topics, web links, LTI links, and the authorization attributes are all in 1.1. The only thing worth moving for is **assignments**, which arrive in 1.3.

The cost is reach. Brightspace and Canvas read up to 1.3, Blackboard up to 1.2, Moodle only to 1.1, so a 1.1 cartridge imports everywhere while a 1.3 one does not. So this is not a migration but an option: a `cc_version` setting on the packaging target, defaulting to 1.1. The manifest differences are the namespace, the schemaversion, and the schema location, all already template substitutions, so the mechanism is small. But it requires a second set of schemas to validate against and a second set of resource types to emit correctly.

Worth doing when there is an assignment to ship, not before.

## 11. A web front end

Here's why the configuration is schema-driven and why conversion becomes a library: a front end needs to render a form from the settings that exist, write a complete config back without losing anything, and report progress and failures structurally.

Two pieces are already in place for it: the schema carries a description per setting, which is what a form's help text should say, and the writer is proven lossless by test. The third piece (resolving a config in JavaScript) is what the conformance fixtures in `tests/config/` exist to make safe.

## 12. Splitting into separate repositories

Eventually the two halves may be separate projects with a small shared library between them. Both standalone cases are already close: packaging is read-only with respect to page content and runs against any directory of HTML, and conversion has no packaging logic. v0.2 removed the last coupling, which was the config.

When that time comes, we'll need the library versioned and released on its own, and the conformance fixtures promoted from tests to a compatibility contract, ensuring that a conversion repo pinned to one version still resolves configs the same way as a packaging repo on another.

Not a goal in itself. Worth doing when one half has users the other does not.

## Smaller things

- **Read the contents tree from an EPUB as well as a PDF.** `build-cartridge.py` builds the module tree from a PDF's bookmark outline, which is the book's table of contents in the order the book actually uses. An EPUB carries the same thing in machine-readable form -- `nav.xhtml` with `epub:type="toc"` in EPUB 3, `toc.ncx` in EPUB 2 -- so the same walk produces the same `(depth, title)` list without needing `pypdf`, and OpenStax publishes EPUBs. The matching of titles to page filenames is unchanged; only the source of the entries differs.
- **Watch [pandoc#3034](https://github.com/jgm/pandoc/issues/3034).** The DOCX and ODT readers ignore `docProps/core.xml`, so a Word file whose title is set through File → Info → Properties converts with no metadata at all: the standalone HTML `<title>` falls back to the filename and the EPUB OPF gets no `dc:title`. If the reader ever picks those up, `promote_h1_to_title` and the duplicate-H1 guard both need rechecking, since the condition they turn on is `doc.meta.title == nil`.
- **Retired key names.** Writing `manifest.cartridge` into a v0.2 config fails with "unknown setting" and no suggestion, because nothing is similarly named. A small table of retired names would let the error say where it went instead.
- **`compare-output.py` matches tables by position**, so one inserted table reports every later one on that page as changed. Matching on caption could help, but not every table has one.
- **A media inventory for the comparator.** It reports files and references; comparing image dimensions or bytes-per-page would catch a class of regression it currently can't see.
- **Cross-page links are not rewritten** for an LMS's internal link format, so links between sections may not resolve after import.
- **Deduplicating identical media.** Each page of a DOCX gets its own copy from Word. Sharing them would shrink a cartridge substantially but requires rewriting page markup. Worth more than it looks: an LMS that does not reclaim images when a module is deleted (looking at you, Brightspace!) accumulates every copy, so the duplication is paid for repeatedly rather than once.
- **One media directory per book** rather than per page. Pandoc's `--extract-media` produces `<page>/media/`, which inside a prefixed package means a directory per page. Flattening to `<prefix>/media/` would make the leftovers after a deletion one folder to remove instead of dozens. Cosmetic, but the cleanup is manual.

