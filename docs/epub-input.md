# An EPUB as the source

When the cleanest copy of a book is its publisher's EPUB, unpack it and convert what comes out:

```bash
python3 $T/bin/unpack-epub.py book.epub -o ~/books/infosys
cd ~/books/infosys
python3 $T/bin/convert.py
```

`unpack-epub.py` reads the EPUB and never writes to it. The directory it makes holds:

- **One `.html` per content document**, named for the file it was and made safe for a link. The text is the publisher's, byte for byte, except that its references point at where things now are: a link to another file of the book is a link to that page, fragment kept; an image is at the path it had beside the package document. The navigation document isn't a page.
- **The book's other files**, images and stylesheets, where they sat.
- **`project.yaml`**, with what the package said about the book (title, language, authors, publisher, description, an identifier made into an XML name) and, as `contents`, what its navigation said about the order. A navigation entry with entries beneath it is a group, opened by its own page when it has one. Every top-level entry carries `convert: true`, so the pages are sources (see [HTML sources](html.md)); there's no group around the whole book, which would push every page a level down in the cartridge and the EPUB's table of contents. The file is yours to edit.
- **`unpack-report.csv`**, for what the unpacking noticed and didn't decide.

| Check | What it means |
| --- | --- |
| `not-in-navigation` | A file in the spine that no navigation entry names. It's listed at the end of `contents`. |
| `looks-like-contents` | A page that links to most of the book, which is usually the book's own table of contents. `generate: toc` in `contents` writes one from the book as it now is; the entry carries a comment saying so. |
| `image-is-not-an-image` | A file the pages show as an image whose bytes aren't one. One exporter packaged a web server's `403 Forbidden` page under each of 120 image names and declared them `text/html`; the pictures aren't in that EPUB at all and have to come from the book's site. Converting such a book stops at the media gate, which names each one in `media-unresolved.csv` as an HTML page where an image should be. |
| `entries-inside-pages` | Navigation entries that point inside a page already named. A book that arrives as one long file has nothing else. Set `pages.split_level` and the page is cut at its headings. |
| `not-linear`, `missing-from-archive` | The spine marks the file as outside the reading order; the manifest names a file the archive doesn't have. |

## A book that is one file

Two of the three EPUBs this was built against hold the whole book in one content document. `contents` then names one page, and that's right: set `pages.split_level` in `conversion.yaml` and the declared page stands for its pieces, grouped under it in reading order exactly as the guess would arrange them. (That holds for any declared page the split cuts, not only one from an EPUB; `contents` that already names the pieces is left as declared.) Links into the file from the book's other pages, its own contents page included, follow their targets to the pieces they moved to.

## Why not Pandoc's EPUB reader

Read from `Readers/EPUB.hs` at 3.11, and in [the Pandoc notes](../PANDOC-NOTES.md): it concatenates the spine into one document, rewrites every id to `<file>_<id>` on some kinds of element and every internal link to match, so a link to a figure or a table dies; it drops each file's own title and language; and it doesn't read the navigation document. Unpacked, each page goes through Pandoc's HTML reader with its ids as the publisher wrote them.

The unpacker parses no content document. One of the three EPUBs isn't well-formed XML (an unclosed `<br>`, which epubcheck calls fatal and reading systems shrug at), so references are rewritten in the text, attribute by attribute.

## What came out, measured

| Book | Their EPUB, epubcheck | Ours from it |
| --- | --- | --- |
| *Information Systems for Business and Beyond* (Pressbooks, 168 files) | 8 errors | 168 pages; 5 errors, each the publisher's own: four malformed URLs and a footnote link to nothing |
| *Computer Systems Security* (Asciidoctor, one file) | 69 errors and a fatal | 16 pages at `split_level: 1`; no errors |

Neither conversion needed a sidecar to get that far. What the run reports is the list to work through next: tables with no header cells, images with no alt text, headings that skip a level.
