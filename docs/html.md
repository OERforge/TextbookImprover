# HTML sources

Every `.html` file beside the sources is a source: read into the same intermediate a `.docx` gets, filtered, split, and rendered by every target. Three kinds are left alone because a run put them there: a page named after another source (the page an older layout wrote beside it), a piece the split named with `--`, and a target's copy of a pass-through page.

A page someone finished by hand goes in the **pass-through directory**, `_pt/` unless `passthrough` in `project.yaml` names another. An `.html` there is copied into every HTML target as it stands and read only so the EPUB can carry it; an `.md` there is converted alongside the sources. Either way its files are treated as though they sat beside the sources: a reference in `_pt/about.html` to `images/logo.png` names the book's `images/logo.png`, and that's what is copied with it. A variant of a pass-through page (`_pt/about.print.html`) is that target's copy.

```
book/
  chapter-1.html        a source
  chapter-2.html        a source
  images/
  _pt/
    about.html          copied as it stands; its images/… are the book's
    errata.md           converted with the sources
```

A book with `.docx` or `.md` sources and `.html` beside them says so on every run, since before v0.7 an `.html` beside the sources was a finished page.

## What is read, and what isn't

Pandoc's HTML reader does the reading, with two things set for it.

**`raw_html` is on.** Without it the reader fetches every `<iframe>` over the network to read its contents into the page; with it nothing is fetched. The same now holds for a finished page read for the EPUB. The price is that every tag the reader has no element for arrives as a fragment of raw markup, and `html-source.lua` deals with those (below). `epub_html_exts` is on too, so an EPUB page's `epub:type="noteref"` finds its footnote the way the `role="doc-noteref"` Pandoc writes always does; a page with neither reads the same either way.

**The page is read from a repaired copy.** Pandoc's reader keeps an id only on an element its document model can hang one on: a div, a section, a span, a heading, a link, an image, a figure, a table, code. A paragraph, a list item, a definition, a table cell, a caption, a block quote, and every inline mark are built from their contents alone, so `<p id="fs-id1167">` comes back nameless and every link to it is dead. `lib/htmlrepair.py` moves such an id onto an empty `<span>` opening the element (an empty `<div>` before a list), which the reader keeps and the link finds. One id stays put: the one a note reference names, because the reader matches a footnote to its reference by the id of the element holding the note, and moving it empties the note. The source is never touched.

**`html-source.lua` runs first**, and turns what the page says about itself into declarations:

- A table with a header row (a `<thead>`, or a first row of nothing but `<th>`) and a `<th>` opening every body row is declared `both`; with one and not the other, `first-row` or `first-column`. That is the same declaration a `::: matrix` div makes for a Markdown table, and it outranks the guess. A table with no `<th>` goes to the header pre-pass like a Word table does: guessed from its text and its bold, listed in `table-headers-new.csv`, and corrected in `table-headers.csv`, which outranks the page's own `<th>` as well (see [Sidecars](sidecars.md)).
- A header row written inside `<tbody>`, which is where Pressbooks and most editors put one, is moved to the table's head. Pandoc's reader keeps it as a head row of the body and would write it back inside the body.
- A `<section>` or `<header>` is opened up, its contents standing where it stood. Every generator wraps a heading and what follows in a `<section>`, and the split cuts only at headings that aren't inside something. The reader moves a heading's id onto its section when the two agree; it goes back on the heading, and any other id a section had is kept as an empty anchor.
- Raw HTML goes, its contents kept: `<footer>`, `<nav>`, `<cite>`, and the stray `</code>` an author never opened, which passed through to an EPUB that was then not well-formed. What was dropped is counted on stderr, by tag. An `<iframe>` becomes a link to what it framed, named by its `title`, which is what an EPUB can hold and what a reader who can't use the embed needs.
- An `aria-describedby` or `aria-labelledby` naming an id the page no longer has is dropped, the rest of its list kept. WordPress points every figure at its own caption that way, and the reader keeps no id of a `<figcaption>`.
- What an earlier run of this pipeline derived is taken out so it can be derived again: Pandoc's title block (its subtitle and date are kept as metadata) and the scroll wrapper around a table.

The reader itself decides one more thing: when a page has exactly one `<main>` (or `role="main"`), only what's inside it is the page. Site navigation outside `<main>` is gone; a menu inside it is content as far as anyone can tell, since the reader keeps no trace of `<nav>`.

Images are files the page names by path, checked at the media gate and copied with the page, as for Markdown.

## Converting this pipeline's own pages changes nothing

That is the test this rests on, and it takes both halves: convert a book, convert the pages that produced, and the two runs agree under `compare-output.py`; convert those pages again and the third write equals the second byte for byte. Measured on *Introductory Business Statistics 2e* (169 pages, 228 tables, one difference: a caption the DOCX export wrote as a one-item list, which the second reading takes for the table's) and on a 34-page Markdown textbook (no difference). The byte check alone isn't enough: a footnote's text once went missing between the first write and the second, and the second and third agreed perfectly; the comparison of the first two is what sees a loss. The first write from a Word source isn't the fixed point, for the reason it isn't for Markdown: Word's residue, a trailing space in a heading, is normalized on the way through.

## What this doesn't do yet

An EPUB is unpacked into pages by [`unpack-epub.py`](epub-input.md). Pages saved from a website arrive with their navigation, their scripts' leftovers, links that point at the live site, and no order in their file names; reading the order from the pages' own menus, stripping what isn't the book, and unpacking an `.mhtml` set are the rest of the roadmap's first item. 
