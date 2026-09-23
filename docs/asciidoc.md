# AsciiDoc sources

An `.adoc` file beside the sources is a page of the book, read with Pandoc's AsciiDoc reader into the same intermediate a `.docx` gets. Three things are done on reading that Asciidoctor would have done and the reader (Pandoc 3.11's, which is the `asciidoc` library's) doesn't:

- **`imagesdir` is applied.** `image::hats.png[]` under `:imagesdir: images` names `images/hats.png`. A chapter that sets none takes its master file's.
- **A chapter's `=` line is its title** and its `==` sections become `h2`, so a page has one `h1`. Asciidoctor's own settings (`:toc:`, `:icons:`, `:stylesheet:`, `:sectnums:`) are dropped from the metadata, where Pandoc's template would read `toc` as a switch.
- **Cross-references land.** `<<Unix File Permissions>>` names a section by its title and `<<Malware>>` a chapter by its title; Asciidoctor resolves both, the reader leaves the title as the fragment. After reading, each goes to the heading, or the page, that holds it, on whichever chapter that is, when exactly one does. On the security textbook this resolved 22 references, plus the references to whole chapters.
- **Links are repaired.** `mailto:someone@example.org[Name]` gets back the `mailto:` the reader drops, and a code span holding a URL scheme (`` `ftp://` ``), which the reader wraps in a link, is just code again.

## A master file

A book is usually one file that `include::`s its chapters. Read through that file, the reader loses each chapter's `=` title (it is neither a heading nor the document's metadata there) and ignores `:leveloffset:`. So a file that includes others isn't read: it's the book's order, each file it includes is a source in its own right, and the run says so. With no `contents` declared, the run writes `contents-sample.yaml` in the shape `project.yaml` takes: the order the master includes its chapters in, and what its header says about the book (its `=` title, the author line beneath it, and `:lang:`). Nothing else carries those, since the master isn't read as a page, so without them the book's EPUB is called "Untitled". Copy the sample into `project.yaml`. Anything else the master holds besides its includes, such as a cover shown only to HTML (`ifdef::backend-html5[]`), isn't part of the book.

## Measured against the book's EPUB

The security textbook is published as an Asciidoctor EPUB and its source is public. The two routes give the same 14 chapters and the same text. What they disagree about is instructive: the EPUB's images have alt text and the source's don't. 49 of the EPUB's 51 alt texts are the image's file name ("db locked" for `db-locked.png`), which is what Asciidoctor writes when the author gave none. The output check now reports that (`image-alt-is-file-name`), so both routes say the same thing: 22 figures need describing.
