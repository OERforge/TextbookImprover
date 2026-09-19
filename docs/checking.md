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
| `image-empty-alt-not-decorative` | `alt=""` without `role="presentation"`: the image was neither described nor declared decorative. |
| `heading-skips-level` | A heading is more than one level below the one before it. |
| `empty-heading` | A heading with no text. |
| `duplicate-id` | An `id` used more than once in one document, so links to it are ambiguous. |
| `table-without-headers-or-caption` | A table with no `th` and no `caption`, and not marked `role="presentation"`. A data grid with no relationships to encode conforms with a caption alone; without one it's unidentifiable. |
| `no-lang`, `no-title` | The `html` element declares no language, or the page has no title. |
| `not-well-formed` | An EPUB content document that isn't XML. |

For an EPUB it also checks the container: `mimetype` first and uncompressed, a package document the container points at, every manifest item present in the archive and every file in the archive present in the manifest, spine entries that exist, a navigation document, the `dc:title`, `dc:identifier`, and `dc:language` every EPUB needs, and the accessibility metadata this project writes.

Each finding says where (the page or archive member), which check, and what (the link, the image path, the heading text), so `output-check.csv` sorts and filters into work lists: every image without alt text goes to `image-alt.csv`, every table without headers to the table sidecars.

## What it isn't

It isn't a validator. [epubcheck](https://github.com/w3c/epubcheck) and the [Nu HTML checker](https://validator.github.io/validator/) know their specifications in full, and DAISY's [Ace](https://daisy.github.io/ace/) applies the accessibility rules to an EPUB the way a reading system would. All three are worth running on a book before distributing it, and all three need Java or Node with a bundled browser, which is why they aren't part of the run. The check here is what can be done every run, on every machine that can run the pipeline, with nothing installed. Where it and epubcheck have both been run on the same book they have agreed; a link the check reports as dead is one epubcheck reports as `RSC-012`.
