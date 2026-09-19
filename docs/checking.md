# Checking the output

Every run ends by checking what it wrote: each page of the run, and each EPUB built from them. The findings go to `output-check.csv` beside the other reports, and the run isn't stopped by them. The output exists; the report is the list to work through. When there's nothing to report the file is removed, so its existing at all is the signal.

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
| `empty-heading` | A heading with no text. |
| `duplicate-id` | An `id` used more than once in one document, so links to it are ambiguous. |
| `vnu:error`, `vnu:warning`, `epubcheck:<ID>` | What the full validators reported, when installed; see below. |
| `table-not-in-scroll-region` | A data table on an HTML page outside the focusable wrapper the filter puts around every data table (WCAG 1.4.10). The filter's own invariant, checked on the output. |
| `table-without-headers-or-caption` | A table with no `th` and no `caption`, and not marked `role="presentation"`. A data grid with no relationships to encode conforms with a caption alone; without one it's unidentifiable. |
| `no-lang`, `no-title` | The `html` element declares no language, or the page has no title. |
| `not-well-formed` | An EPUB content document that isn't XML. |

For an EPUB it also checks the container: `mimetype` first and uncompressed, a package document the container points at, every manifest item present in the archive and every file in the archive present in the manifest, spine entries that exist, a navigation document, the `dc:title`, `dc:identifier`, and `dc:language` every EPUB needs, and the accessibility metadata this project writes.

Each finding says where (the page or archive member), which check, and what (the link, the image path, the heading text), so `output-check.csv` sorts and filters into work lists: every image without alt text goes to `image-alt.csv`, every table without headers to the table sidecars.

## Contrast

No checker here measures color contrast on the rendered page; Ace, axe, and Panorama do. What the pipeline controls is its own stylesheet, and that is checked where it's decided: a unit test computes the ratio of every text color `page.css` sets against Pandoc's page background and against white, and fails below 4.5:1 (the caption color is held to 7:1).

## The full validators

The checks above are what the standard library can do. [epubcheck](https://github.com/w3c/epubcheck) and the [Nu HTML checker](https://validator.github.io/validator/) know their specifications in full, and when they're installed the run uses them too: epubcheck on each EPUB, the Nu checker on every page. Their findings land in the same report in the same shape, with the tool's own message as the check (`epubcheck:RSC-012`, `vnu:error`, `vnu:warning`), and the run says which ran. The Nu checker's informational messages (Pandoc's trailing slashes on void elements, mostly) are counted and not listed, since they change nothing for a reader.

Both are Java, which is why they're optional. [Installation](installation.md#optional-the-full-validators) says how to set them up; the run finds them through `EPUBCHECK_JAR` and `VNU_JAR`, or as `epubcheck` and `vnu` commands on the path. `check-output.py --quick` skips them when a fast turn is wanted.

The first thing the Nu checker found in this project's own output was a rule the built-in check couldn't know: an `img` with `alt=""` already has the presentation role and may not carry a `role` attribute, which the filter had been adding to every decorative image. It now uses `aria-hidden="true"`, which the checker accepts and which does the same job. That's the argument for running the real thing.

DAISY's [Ace](https://daisy.github.io/ace/) applies the accessibility rules to an EPUB the way a reading system would; it needs Node with a bundled browser and isn't wired in. Worth running on a book before distributing it.
