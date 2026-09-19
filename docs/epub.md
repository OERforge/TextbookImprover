# Building an EPUB

One EPUB for the whole book, assembled from the same pages the cartridge holds and ordered by the same `project.contents`. Declare an `epub3` target and `convert.py` builds it after the pages, or run `bin/build-epub.py` on its own against a directory that has already been converted.

## Declaring the target

```yaml
# in conversion.yaml
targets:
  html:
    format: html             # writes html/
  epub:
    format: epub3            # writes epub/<identifier>.epub
```

`output_dir` defaults to the target's name and `filename` to the book's identifier with `.epub` added, so the block above writes `epub/org.example.book.epub` and nothing else needs saying. The settings an `epub3` target reads beyond the shared ones are under `epub:` in the [conversion settings](conversion-settings.md): `toc_depth` and `accessibility_summary`.

The book's own details come from `project.yaml`: `title`, `language`, `identifier` (the EPUB's identifier too, so a rebuilt edition is recognized as the same book rather than a new one), `publisher`, `description`, and `authors`, which becomes one creator entry each.

## What goes in, and in what order

The assembler reads the filtered intermediates `convert.py` writes (`<page>.filtered.json`), not the HTML pages. The intermediate is the page after the filter has done its work and before any writer has rendered it, so everything the [remediation](architecture.md#what-conversion-does-to-your-pages) produced (captions, `scope` on header cells, the scroll wrapper, replaced alt text, MathML) arrives in the EPUB as it does in the HTML. Reading the HTML back would lose some of it: Pandoc's HTML reader keeps a cell's `scope` attribute but not the element, so a row header would come back as a `<td>`.

Order and structure come from `project.contents`, exactly as for the cartridge. A group becomes a heading over its pages; a page becomes a heading at its depth; the page's own headings continue below it. So the table of contents shows ranks, not files: with

```yaml
contents:
  - preface
  - title: Unit 1 Foundations
    items:
      - 1-1-what-is-economics
      - 1-2-scarcity
```

the nav lists *Preface* and *Unit 1 Foundations* at the first level and the two sections under the unit, and `toc_depth: 2` (the default, passed straight to Pandoc) is what makes it stop there. A book whose files were split at a different depth reads the same way once its tree says where each page sits. What the tree can't do yet is reach inside a file: a source that arrived as one `.docx` is one page, and its chapters appear as that page's internal headings. Splitting pages at a heading level is [planned](../ROADMAP.md).

Pages on disk that `contents` doesn't place are named on stderr and left out, as the cartridge leaves them out; a page `contents` names that doesn't exist is a warning. With no `contents` at all the order is guessed from the filenames, the same guess the packager makes, and the run says so. A `contents` that is a single page is taken to be the book itself: nothing is added above its headings.

Each page is its own file inside the EPUB, titled by its heading. Every `id` in a page is prefixed with the page's name (`page-1-2-scarcity--table-1`), and links within the page follow, so two pages that both have a *Key Terms* heading don't send a link to the wrong one.

With `numbering: true` on the project, the nav and the headings carry the book's numbers (`1 The Big Picture`, `1.1 …`, `A Math Review`); a `generate: toc` entry in `contents` is a chapter holding the full table of contents; and `notes.placement: book` gathers every footnote on a Notes chapter placed where `contents` lists `notes`, or last. A footnote is numbered where it appears and ends with a labelled link back to its reference.

## What the package document claims

An EPUB carries [accessibility metadata](https://www.w3.org/TR/epub-a11y-11/#sec-disc-package) that catalogs and reading systems act on: which modes the content can be perceived in, which of those are sufficient on their own, which features are present, and a summary for the reader. Pandoc fills these with the same values for every EPUB it writes, including `alternativeText` and the claim that text alone is sufficient, whether or not the images have any.

The assembler computes them from the build instead:

- `accessMode` is `textual`, plus `visual` when the book has images.
- `accessModeSufficient` is `textual` only when every image has alternative text or is marked decorative; otherwise `textual,visual`, meaning a reader needs both.
- `accessibilityFeature` always includes `structuralNavigation`, `tableOfContents`, and `readingOrder`; `alternativeText` is added when the images are all described, and `MathML` when there are equations.
- `accessibilityHazard` is `none`, since nothing that flashes, moves, or sounds comes out of a Word file.
- `accessibilitySummary` is derived from the same counts unless `epub.accessibility_summary` is set, and then that text is used as written.

So the claims change as the sidecars are filled in. A book whose `image-alt-missing.csv` still has rows says so in its summary and withholds `alternativeText`; supply the text through `image-alt.csv`, rebuild, and the EPUB starts claiming it. The run prints what it claimed.

## A cover

```yaml
  epub:
    format: epub3
    epub:
      cover_image: cover.png       # absolute, or relative to the content directory
      cover_alt: Cover of Principles of Marketing, third edition
```

Pandoc makes the cover page, puts it first, and marks the image in the manifest. What it doesn't do is give the cover a text alternative: the page is an SVG holding the image and nothing else, so a screen reader meets the book with a silent page. The assembler names it, as `role="img"` with an `aria-label` and a `<title>` inside the SVG. `cover_alt` is that text; left empty it's "Cover of" and the book's title.

## Checking the result

Every run ends with the [output check](checking.md) over the pages and the EPUB: dead links and fragments, images without alt text, skipped headings, tables without headers, and the EPUB's own container and metadata. [epubcheck](https://github.com/w3c/epubcheck) validates the container and content in full, and DAISY's [Ace](https://daisy.github.io/ace/) reports on the accessibility of the markup as a reading system would see it; both need Java or Node and are worth running on a book before distributing it. The fixture book this project's tests build passes epubcheck 5.2 with no errors or warnings.

One thing to know when reading Ace's report: Pandoc titles each chapter file by its heading here, because the assembler adjusts Pandoc's EPUB template to do so. Without that every file is titled by its own filename, which is a WCAG 2.4.2 failure that Ace reports on every page.
