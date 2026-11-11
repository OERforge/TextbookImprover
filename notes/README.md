# Notes

Reference notes behind TextbookImprover: what the software it's built on does, what the standards say, what testing found, and why the project is built as it is. They're for anyone working on the code, a person or an AI assistant, who needs a fact that would otherwise take an hour of reading source or an experiment to find again. Using TextbookImprover needs none of this: that's what [the documentation](../docs/) is for.

## The files

- [PANDOC-NOTES.md](PANDOC-NOTES.md): what Pandoc does, by reader and writer, with its templates, its Lua filter environment, texmath, building it from source, and what's been reported upstream.
- [LATEX-NOTES.md](LATEX-NOTES.md): what LaTeX's tagging code, its packages, LuaTeX, and the fonts do, the TeX distributions, and the other programs in a PDF's build (latexmk, Ghostscript, poppler, pypdf, pikepdf).
- [OFFICE-NOTES.md](OFFICE-NOTES.md): what Word, PowerPoint, Excel, LibreOffice, and Keynote do, and what their file formats hold.
- [WEB-NOTES.md](WEB-NOTES.md): browsers and Chromium under Playwright, MathJax, reveal.js, web archives and saved pages, and publishers' sites.
- [LMS-NOTES.md](LMS-NOTES.md): Common Cartridge, and what a learning management system does with a package on import.
- [ACCESSIBILITY-NOTES.md](ACCESSIBILITY-NOTES.md): what WCAG, PDF/UA, and WTPDF say, what screen readers say of the output, and what the checkers report and miss.
- [CNX-NOTES.md](CNX-NOTES.md): OpenStax's CNXML sources and how the unpacker reads them.
- [CORPUS-NOTES.md](CORPUS-NOTES.md): the books and decks the project is tested on, and what converting each one measured.
- [DESIGN-NOTES.md](DESIGN-NOTES.md): decisions about TextbookImprover itself whose reasons aren't obvious from the code.

## What goes where

A fact goes in the file of the thing it's a fact about, not the feature that needed it.

- What a program does goes in that program's file, in the section for the part that does it: what Pandoc's DOCX writer writes is in PANDOC-NOTES, and what Word then does with it is in OFFICE-NOTES.
- What a screen reader said, or a checker reported, goes in ACCESSIBILITY-NOTES, under the screen reader and the program it was reading, or under the checker.
- What a standard requires goes in ACCESSIBILITY-NOTES. How LaTeX's code meets a PDF standard is in LATEX-NOTES.
- A measurement of a book or a deck goes in CORPUS-NOTES. A measurement of a program, made on a book, goes in the program's file and names the book.
- What TextbookImprover does about a fact is named in a sentence at the end of the fact's entry, with the file or function that does it. Why it does that, when the reason is a choice among alternatives, goes in DESIGN-NOTES.
- When a fact belongs in two files, it's written once, in the file of the program whose behavior it is, and the other file points there by the file's name and section.

These don't go in the notes: how to use TextbookImprover ([`docs/`](../docs/)); what changed and when ([`CHANGELOG.md`](../CHANGELOG.md)); what's planned or open ([`ROADMAP.md`](../ROADMAP.md)); the history of how something was worked out, beyond what was tried and dropped; and anything true only of one person's machine.

## How an entry is written

- **One fact per paragraph, with a bold lead that states it.** The lead is a sentence someone can act on without reading further. The rest of the paragraph gives the particulars.
- **Say how it's known.** "Read" means read from the source or the specification, with the file, function, or clause. "Measured" means run, with what it was run on. A fact taken from documentation and not checked says so. A guess says it's a guess.
- **Say which version and when.** A fact is true of the release it was read or measured at, so the entry names the release and the date. When a later release changes it, the entry is corrected in place, with the date of the correction and what was true before if anyone might still have the older release.
- **Name the tester for a test result.** What a person heard from a screen reader, or saw in Word, PowerPoint, Acrobat, or an LMS, is recorded with their name, the date, and the versions if known: "(Rob, 2026-10-09)". Say what was heard or seen, word for word where that matters, not what was expected. Rob is Rob Szarka, the project's maintainer, who made nearly all the tests recorded so far. Nobody is named for anything else: a decision is stated with its reason, not with who made it.
- **Refer by name and date, not by number.** Entries aren't numbered. Refer to another entry by its file and section ("LATEX-NOTES, Fonts"), and to a measurement by its date.
- **Say whether a defect has been reported.** A fault found in another project is written up where the fact is, with either the issue's or pull request's number or "not reported upstream as of" and the date. If it's fixed upstream, say in which release.
- **Name only public samples.** A book or a deck that's openly licensed and public is named, with its license in CORPUS-NOTES. A sample lent for testing is described ("a set of course decks written for beamer") and not named, and nothing of its content is given beyond counts and what it exercises.
- **Write for someone who wasn't there.** Full sentences, each term defined or pointed to, no reference to a conversation or to an unpublished file.

The house style is the documentation's: US spelling, the Oxford comma, contractions, one paragraph per line, and no hard wrapping.

## Adding to the notes

Add an entry when you've learned something that took effort and that the next person would otherwise have to learn again: a behavior read from source, a test result, a dead end. Put it in the section it belongs to, in the form above, and correct any entry it contradicts. Test results from other screen readers, browsers, Office versions, and learning management systems are especially welcome, since most of what's here comes from one tester's setup. A pull request that changes only these files is fine.
