# A book saved from the web

When a book exists only as a website, save its pages and unpack them:

```bash
python3 $T/bin/unpack-site.py "saved pages/" -o ~/books/cs168
cd ~/books/cs168
python3 $T/bin/convert.py
```

Look for the book's source first. Two of the three web books this was built against have public repositories (Markdown for one, AsciiDoc for another), and a source beats the best save.

`unpack-site.py` takes a directory of a browser's "complete" saves (an `.html` per page, each with a `_files` directory beside it), a directory of `.mhtml` files, or WARC and WACZ files. It fetches nothing.

**A WARC is the best of the three** ([Making a WARC](making-warcs.md) says how). Every archiving crawler writes one: `wget --mirror --page-requisites --no-parent --warc-file=book https://…` does, as do the ArchiveWeb.page browser extension, Browsertrix Crawler, and the Internet Archive's Heritrix. It holds each URL's bytes as the server sent them, before any script ran, so nothing a browser's save loses (a MathJax page's TeX, the original links) is lost. Redirects the crawl recorded are followed; gzipped and chunked responses are decoded. A WACZ is WARCs in a zip and is read the same way. A wget WARC of a copy of CS168 unpacked to pages byte-identical to the unpacked browser save, with the same contents and the same images. What it writes:

- **One `.html` per page**, named from the page's URL below the directory the book's pages share (`end-to-end/dhcp.html` becomes `end-to-end-dhcp.html`). By default a page is its content and nothing around it; with `--whole-pages` it's the whole page, an offline copy of the site.
- **`assets/`**, holding each image (and, for `--whole-pages`, each stylesheet and script) once, however many pages saved a copy. One save held 766 images as 763 files.
- **`project.yaml`**, with the book's title (the suffix every page's `<title>` shares, "CS 168 Textbook"), its language, and, as `contents`, the order its own menus give.
- **`unpack-report.csv`**, for what it recognized, guessed, and couldn't find.

## Every reference points at what is here

A link to a page of the book becomes a link to its file, fragment kept; an image or stylesheet becomes a reference to its copy under `assets/`. Anything not held keeps the URL it had, and the report says so when that matters. A **link** to another site is only a link and isn't reported, but a link to a page of the book's own site that nobody saved is (`page-not-saved`). A **resource** (anything a page fetches to show itself: an image, a stylesheet, a script, a frame) that isn't held is reported (`resource-not-held`), wherever it lives, unless its host serves other people's frameworks and fonts. A short list of those is built in (cdnjs, jsDelivr, unpkg, Google Fonts, and a few more); `--third-party HOST` adds one.

Fragments and ids are brought to one form on both sides. Racket's Scribble writes `<a name="(part._my-len)">` and links to `#%28part._my-len%29`, and names some anchors `section 5.2`. A browser decodes a fragment before looking for it; epubcheck and our own check don't, and no id may hold a space. Decoded, with whitespace made underscores, both ends agree.

## The generator, recognized

What surrounds the content depends on what built the site, and a profile says where the content is and what inside it is chrome. The profile is chosen from what the pages say about themselves, never by asking; `--profile` overrides it.

| Profile | Recognized by | Content | Chrome removed from the content |
| --- | --- | --- | --- |
| `just-the-docs` | a Jekyll generator meta and the theme's name | `<main>` | the page's own table of contents, the link icon on every heading, breadcrumbs, the footer |
| `scribble` | its `navsettop` bar (Scribble names itself nowhere) | `div.main` | the prev/up/next bars, the 🔗 on every heading, the sidebar |
| `asciidoctor` | its generator meta | `#content` | the table of contents, the footer, heading anchors |
| `wordpress` | its generator meta | `<main>`, `#content`, or `<article>` | navigation, footers, sharing buttons |
| `generic` | anything else | `<main>`, `role="main"`, `<article>`, or the body | navigation and footers |

A profile may also say what its generator lays out as a table that isn't one. Scribble does that four ways, and of DCIC's 335 tables 210 were these: a REPL interaction (prompt, code, result) becomes its contents; a section's own table of contents, nothing but `toclink` links, goes, like just-the-docs' per-page contents; a verbatim block with a line per row becomes one `<pre>`; and a Python/Pyret comparison, the one kind that is data, keeps its table and gets its row of language names as header cells. The report counts each kind.

A book's pages keep no `<script>` except math (`type="math/tex"`, which Pandoc reads), no stylesheets, and no `<style>`. An `<a name>` with no link becomes an empty `<span>` holding the id, since Pandoc's reader drops the name.

## The order, from the pages' own menus

Every element on every page that links to at least three pages is a candidate, and the one reaching most pages wins, a tie going to the smaller element. That alone would crown a back-of-book index, which links every page too. What separates a table of contents from an index isn't how often it links a page: a detailed contents links a chapter and then each of its sections. It's that a contents keeps a page's links together and an index scatters them through the alphabet. So a candidate's links, read in order with repeats of one page collapsed, must come to not much more than one run per page.

Nesting comes from the menu's lists. A menu that is one flat list, like Scribble's, is nested by its numbering (`5.2 Processing Lists` under `5 Lists`), with a part numbered in roman numerals above the chapters that follow it. A link whose text is an icon or a word like "up" isn't a title; the page's own is used. Pages no menu names are listed at the end and reported (`not-in-menu`).

## What the save itself decides

A browser saves the page as it stood after its scripts ran. Where the site renders math with MathJax, a "complete" save keeps the `<script type="math/tex">` source and Pandoc reads it. An `.mhtml` save keeps no scripts, so the TeX is gone and only MathJax's rendering is left, which isn't math to anyone reading the output. The report names each such page (`math-lost`). That's a property of the save, and a different way of saving the book would do better.

## Parsers

Saved pages are parsed with html5lib, which builds the tree a browser builds; install it with `sudo apt install python3-html5lib`. Without it `lxml` is used, and the run says so once: libxml2's HTML parser doesn't know `<wbr>` is empty and nests what follows inside it, which changed the tree of 42 of one book's 80 pages. With neither, the run stops and says what to install.
