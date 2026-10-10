# Checking the output

Every run ends by checking what it wrote: each page of the run, and each EPUB and PDF built from them. The findings go to `output-check.csv` beside the other reports, in the [findings format](auditing.md#the-findings-format) every check in this project shares (`Where, Check, Detail` first, then the file, its kind, a severity, the standard, the tool, and where the fix lives), and a summary goes to the terminal. The check never stops the run: the output exists, and the report is the list to work through. For the same checks on files that didn't come from a run, and for Word, Markdown, and PDF as well, see [Auditing](auditing.md).

```bash
python3 bin/check-output.py *.html --epub epub/book.epub --report output-check.csv
```

runs the same check by hand, on whatever you point it at.

## What it looks for

The checks are the class of defect that has reached this project's output before: structure that's well-formed and wrong, which nobody notices by looking at a page.

| Check | What it means |
|---|---|
| `link-to-missing-file` | A link names a page or file that isn't in the set being checked. |
| `link-to-missing-fragment` | A link's `#fragment` matches no `id` in the page it points at. |
| `image-without-alt` | An `img` has no `alt` attribute, so a screen reader announces the file name. |
| `image-empty-alt-not-decorative` | `alt=""` without `aria-hidden="true"`: the image was neither described nor declared decorative. In an EPUB this is the usual form of a missing description, since Pandoc's writer gives every image an `alt`. |
| `heading-skips-level` | A heading is more than one level below the one before it. |
| `formula-shown-as-tex` | A formula Pandoc couldn't convert to MathML, so the page shows its TeX (`$r_{s} = \left( …$`) and a screen reader reads that out. Pandoc says so only in a warning among the run's output; the detail is the formula, to find it in the source. A page with a script is skipped, since a script there may be what renders the TeX. |
| `empty-heading` | A heading with no text. |
| `invalid-id` | An `id` containing whitespace, which no `id` may. |
| `duplicate-id` | An `id` used more than once in one document, so links to it are ambiguous. |
| `vnu:error`, `vnu:warning`, `epubcheck:<ID>` | What the full validators reported, when installed; see below. |
| `table-not-in-scroll-region` | A data table on an HTML page outside the focusable wrapper the filter puts around every data table (WCAG 1.4.10). The filter's own invariant, checked on the output. |
| `table-without-headers-or-caption` | A table with no `th` and no `caption`, and not marked `role="presentation"`. A data grid with no relationships to encode conforms with a caption alone; without one it's unidentifiable. |
| `table-header-is-formula` | A note: a header cell (`th`) holding only a formula. The table is right as it stands, but NVDA reads the formula in the header row and announces no header on moving into its column, since it takes a header from the cell's text in its buffer, where a formula is a single space ([its browser support](https://github.com/nvaccess/nvda/blob/release-2026.2/nvdaHelper/vbufBackends/gecko_ia2/gecko_ia2.cpp#L849-L856), [the header's text](https://github.com/nvaccess/nvda/blob/release-2026.2/source/virtualBuffers/__init__.py#L416-L437)). Words beside the formula it announces ("Quantity demanded, q_d" is announced as its words). Heard so with NVDA in Chrome or Firefox and in Acrobat. The detail is the table's number on the page and the formula's TeX. |
| `no-lang`, `no-title` | The `html` element declares no language, or the page has no title. |
| `title-is-file-name` | The page's title is its file's name (`ch_intro_to_data`), as a page with no heading of its own gets: a name with an underscore, a hyphen, a dot, or a capital inside a word. |
| `not-well-formed` | An EPUB content document that isn't XML. |

For an EPUB it also checks the container: `mimetype` first and uncompressed, a package document the container points at, every manifest item present in the archive and every file in the archive present in the manifest, spine entries that exist, a navigation document, the `dc:title`, `dc:identifier`, and `dc:language` every EPUB needs, and the accessibility metadata this project writes.

Each finding says where (the page or archive member), which check, and what (the link, the image path, the heading text), so `output-check.csv` sorts and filters into work lists: every image without alt text goes to `image-alt.csv`, every table without headers to the table sidecars.

## Contrast

No checker here measures color contrast on the rendered page; Ace, axe, and Panorama do. What the pipeline controls is its own stylesheet, and that is checked where it's decided: a unit test computes the ratio of every text color `page.css` sets against Pandoc's page background and against white, and fails below 4.5:1 (the caption color is held to 7:1).

## The full validators

The checks above are what the standard library can do. [epubcheck](https://github.com/w3c/epubcheck) and the [Nu HTML checker](https://validator.github.io/validator/) know their specifications in full, and when they're installed the run uses them too: epubcheck on each EPUB, the Nu checker on every page. Their findings land in the same report in the same shape, with the tool's own message as the check (`epubcheck:RSC-012`, `vnu:error`, `vnu:warning`), and the run says which ran. The Nu checker's informational messages (Pandoc's trailing slashes on void elements, mostly) are counted and not listed, since they change nothing for a reader.

A PDF gets what the [audit](auditing.md) reports about one: what the file claims, whether it's tagged, and, from its structure tree, each figure whose alternative text is a file name (`pdf-figure-alt-is-file-name`), which is what LaTeX writes for an image with none and a validator accepts, and each whose alternative text is the placeholder LaTeX writes for a drawing with none, `picture environment` or `Alternative text missing!` (`pdf-figure-alt-is-placeholder`); and, as a note, each header cell holding only a formula (`pdf-table-header-is-formula`), which NVDA in Acrobat doesn't announce as a column's header, as on a page ([its Acrobat support](https://github.com/nvaccess/nvda/blob/release-2026.2/nvdaHelper/vbufBackends/adobeAcrobat/adobeAcrobat.cpp#L456-L460)), whatever alternative text the formula has. The detail is the cell's page, its table's number, and its own among the table's header cells, in the structure tree's order. Content beside a formula counts if it shows anything at all, a space glyph included. When [veraPDF](https://verapdf.org) is installed, each rule it finds failed is a finding (`verapdf:<clause>-<test>`, with the standard's clause in the Standard column), and once it has run and found nothing, the note that the file's claims are unverified is dropped.

All three are Java, which is why they're optional. [Installation](installation.md#optional-the-full-validators) says how to set up the first two, and [veraPDF](installation.md#optional-verapdf) the third; the run finds them through `EPUBCHECK_JAR`, `VNU_JAR`, and `VERAPDF`, or as `epubcheck`, `vnu`, and `verapdf` commands on the path. When a fast turn is wanted, `convert.py --quick` checks the run's output without them, as `check-output.py --quick` does on its own; the checks above still run, and the summary says the validators didn't.

The first thing the Nu checker found in this project's own output was a rule the built-in check couldn't know: an `img` with `alt=""` already has the presentation role and may not carry a `role` attribute, which the filter had been adding to every decorative image. It now uses `aria-hidden="true"`, which the checker accepts and which does the same job. That's the argument for running the real thing.

A PDF/UA-2 file this pipeline makes also claims the PDF Association's [Well-Tagged PDF](https://pdfa.org/resource/well-tagged-pdf/), at both its levels (accessibility and reuse; LaTeX writes the declarations), and veraPDF validates what a file claims: its WTPDF 1.0 profiles run on every such PDF, beside PDF/UA-2 and Tagged PDF, and a finding names the profile. A PDF/UA-1 file, PDF 1.7, is outside WTPDF, which is PDF 2.0. A PDF's validators and readers have their own limits. When a screen reader says something a tagged PDF doesn't, the viewer may be at fault rather than the file: the PDF Association's technical notes say that a viewer which announces a figure for an image tagged with the text it shows ([TN-PDFUA1-001](https://pdfa.org/resource/tn-pdfua1-001)), or announces "link" twice for a contents entry, whose `Reference` encloses a `Link` as it should ([TN-PDFUA1-002](https://pdfa.org/resource/tn-pdfua1-002)), has a defect to report to the viewer's publisher. Few checkers know PDF 2.0, and one that applies PDF 1.7's rules to a PDF/UA-2 file reports problems a valid file doesn't have; the LaTeX tagging project keeps a [list of such false reports](https://github.com/latex3/tagging-project/discussions/categories/issues-with-accessibility-checkers-and-other-at-software) to check a finding against. [PDFix](https://pdfix.net/) runs veraPDF's checks but shows where in the page each problem is, which veraPDF's paths into the structure tree don't. veraPDF's [other profiles](https://github.com/veraPDF/veraPDF-validation-profiles), WCAG 2.2 among them, can be run on the same file. Blackboard Ally, in many learning management systems, checks against PDF 1.7: it wants alt text on every formula, which a PDF/UA-1 build has and a PDF/UA-2 build doesn't (`pdf.standard`), and headings in anything over two pages. For hearing a tagged PDF 2.0 file, Acrobat, Foxit, and Firefox expose its tags, to NVDA or JAWS on Windows and Orca on Linux.

DAISY's [Ace](https://daisy.github.io/ace/) applies the accessibility rules to an EPUB the way a reading system would; it needs Node with a bundled browser and isn't wired in. Worth running on a book before distributing it.
