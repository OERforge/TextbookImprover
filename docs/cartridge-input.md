# A course cartridge as the source

A Common Cartridge (`.imscc`) is how a course leaves an LMS: Brightspace, Canvas, Blackboard, and Moodle all export one, and publishers distribute course shells as cartridges. It's a zip whose manifest lists every resource and arranges them in an outline of modules. `unpack-cartridge.py` turns one into a book directory: each HTML page a source page, each Word document a source, every other file kept where the cartridge had it, and a `project.yaml` with the outline as `contents`.

## Converting one

Put the cartridge in a directory of its own and run `convert.py` there. Finding a cartridge and no sources, it unpacks it into the directory, then converts the pages:

```bash
mkdir ~/books/soc && cp introduction-to-sociology-3e-export.imscc ~/books/soc/
cd ~/books/soc
python3 $T/bin/convert.py
```

As with a web archive, the pages are the book from then on: correct them, not the cartridge, which later runs don't read again. A `project.yaml` already in the directory is kept, with the unpacker's beside it as `project-unpacked.yaml`. To unpack by hand, into a directory of its own:

```bash
python3 $T/bin/unpack-cartridge.py course.imscc -o ~/books/course
```

A cartridge is recognized by its manifest, whatever the file is called, and versions 1.0 through 1.3 read the same way.

## What becomes what

A module is a group in `contents`, and an entry in it that names a page is that page. Canvas puts text headers in a module, entries with nothing beneath them that head the entries after them; each becomes a group of those entries. A resource the outline names twice (Brightspace lists a week's discussion in two modules) is in the book once, where it first appears. A page the outline doesn't list is added at the end, unless Canvas marks it unpublished, in which case it's left out.

A page is named after its file, made safe for a link, and a second file with the same name takes a number. A page with no `<title>` of its own, as Brightspace writes them, takes the outline's title for it. Canvas's link placeholders are resolved: `$IMS-CC-FILEBASE$` is the course's files, `$WIKI_REFERENCE$/pages/…` another page, and the query Canvas adds to a local link (`?canvas_=1&canvas_qs_wrap=1`) is dropped. When every file the pages use sits in one directory, as in a cartridge this project built, that directory drops out of the book's paths.

A Word document the outline names is a source, and becomes a page like any other. A local file a page only links to, like a PDF or a Word checklist, is copied into each target beside the page, as an image is. An EPUB can't hold one, so there the link's text stays without the link, and the output check lists each file as `link-to-file-dropped`: OpenStax's cartridge has five, its setup checklists and a caption guide.

## Linked documents as pages

A document a page links to stays a file unless you ask otherwise, since it may be a handout meant to be downloaded as it is. With `--linked-documents`, each linked file the pipeline can convert (Word, Markdown, AsciiDoc, HTML) becomes a page of the book instead: beneath the first page that links to it, titled by that link's text, with the link now leading to the page. As a page it's in every target, the EPUB included. PDFs and slides stay files either way.

```bash
python3 $T/bin/convert.py --linked-documents          # the run that unpacks the cartridge
python3 $T/bin/unpack-cartridge.py course.imscc -o book/ --linked-documents
```

The switch acts when a cartridge is unpacked; given on a later run, `convert.py` says it has nothing to do. Without it, the report lists each convertible document it kept as a file (`linked-document-kept`). OpenStax's sociology cartridge has four, its setup checklists and an accessibility guide; with the switch, they're pages, and the EPUB's only dropped link is a PDF. A converted document brings its own defects with it, which the output check reports as for any source: two of those four link to bookmarks they don't contain.

## What unpack-report.csv lists

What a course holds that a book doesn't: discussions, assignments, web links, quizzes and test banks, and links to external tools (LTI), each with where the outline put it; and, as `unlisted-…`, how many of each the outline never names. A course's test banks usually sit outside its modules. Files the outline names that aren't pages (slides, PDFs) are kept and listed as `file-in-outline`. A page that is little more than links to one other site is `links-out`: a reading list pointing at the reading, which the cartridge doesn't hold.

## The two cartridges it was built on

A Brightspace export (Common Cartridge 1.3) of a course with eight modules: 21 HTML pages and 3 Word documents became the book, and its 11 discussions, 2 assignments, and 2 web links are in the report. Its pages had no titles, and its content folder is named with a Cyrillic "с" that looks like a Latin "c", which is why nothing here trusts a folder's name over the manifest.

OpenStax's course cartridge for *Introduction to Sociology 3e*, exported from Canvas (Common Cartridge 1.1): 32 pages, 22 of them reading lists that link to openstax.org, with 24 slide decks and PDFs in the outline and 42 test banks outside it. Its pages link to Word checklists and banner images through `$IMS-CC-FILEBASE$`.

A book this project packaged as a cartridge converts back to the same pages and files, which the test suite checks.
