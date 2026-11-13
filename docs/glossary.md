# Terms these pages use

These pages lean on a small vocabulary of TextbookImprover's own, on the names of other programs and standards, and on short names for the books it's tested on. This page says what each one means and where it's described in full. Nothing here is needed for [a first run](first-run.md); it's for when another page uses a word as though you knew it.

## TextbookImprover's own words

**The book's directory.** The directory `convert.py` is run in, also called the book's folder or the content directory. It holds the sources, the configuration files, the sidecars, the reports, and the intermediates. Each target writes its output into a subdirectory of its own.

**Source.** A file the book is converted from: a Word file (`.docx`), a Markdown file (`.md`), an AsciiDoc file (`.adoc`), an HTML page (`.html`), or a LaTeX book's files, read through its master file. A book that arrives another way (an EPUB, a saved website, a course cartridge, an OpenStax repository) is unpacked into sources first.

**Run.** One go of `convert.py` in a book's directory, from reading the sources to checking what it wrote. "The run says" and "the run warns" mean a line it prints on the terminal. A slides run is a run on a folder of decks.

**`$T`.** The directory the tools themselves are in, wherever you unpacked or cloned them, so `python3 $T/bin/convert.py` runs the converter from any book's directory ([Installation](installation.md#getting-the-tools)).

**Page.** The unit a book is made of. A page starts out as one source file and is named after it, without the extension and made safe for a link: `01 BigPicture.md` is the page `01-BigPicture`. Each HTML target writes one file per page, and an EPUB, a PDF, and a cartridge are assembled from the same pages. A page's name is sometimes called its stem.

**Piece.** A page cut from a longer source at its headings, when `pages.split_level` is set. A piece is named after its source and its heading, with `--` between them: `chapter-7--economies-of-scale` ([Splitting pages](splitting.md)).

**Contents, group.** `contents`, in `project.yaml`, is the book's structure: its pages in order, gathered into groups. A group is a container with a title, whatever the book calls it (a chapter, a unit, a part). The same structure becomes a cartridge's modules, an EPUB's table of contents, and the generated contents page ([Contents](configuration.md#contents)).

**Role, type.** Two things a `contents` entry can say about itself. Its role is the part of the book it's in (`front`, `main`, `appendix`, or `back`), which decides how it's numbered. Its type is what it is (`preface`, `glossary`, `index`, and so on), which an EPUB marks for a reading system ([Contents](configuration.md#contents)).

**Target.** One output a run builds, declared under `targets:` in `conversion.yaml` with a name and a `format`: `html`, `epub3`, `pdf`, `latex`, `docx`, `pptx`, `revealjs`, `markdown`, `asciidoc`, or `source`. A run with no configuration has one target, named `html`. Every target is built from the same sources on every run ([Targets](configuration.md#targets)).

**Remediate, a `source` target, the copy.** To remediate a file is to fix what keeps a reader with a disability from using it: alt text that's missing, a table whose header cells aren't marked, a link that reads as its address. A target with `format: source` writes a remediated copy of the author's own files: the decisions recorded in the sidecars written into a copy of each Word, Markdown, HTML, LaTeX, or PowerPoint file, and the rest of the file left as the author wrote it. Where a page says "the copy" without saying more, it means that copy. A LaTeX book's tagged copy is one also changed so that it builds with LaTeX's own tagging ([Source](formats.md#source)).

**Intermediate.** A page as Pandoc read it, kept as a `.json` file in Pandoc's own document format beside the sources, and the same page after the filter has run, as `.filtered.json`. Every target is written from the filtered intermediates. They can be deleted; the next run makes them again ([What a run creates](first-run.md#what-a-run-creates)).

**The filter.** `bin/figures-and-tables.lua`, a program Pandoc runs on each page between reading it and writing it, which does most of the accessibility work: figures, table captions and headers, alt text, and the rest ([What conversion does to your pages](architecture.md#what-conversion-does-to-your-pages)). A few smaller filters run with it or after it.

**Filter stage, render stage.** The two main points at which a conversion setting acts. A setting at the filter stage changes the filtered intermediate, and so every output made from it. A setting at the render stage changes only how one target writes that intermediate out. Two targets that agree on every filter-stage setting share one filtered intermediate, and one that differs gets its own ([Targets](configuration.md#targets)). `bin/schema-conversion.yaml` gives each setting's stage.

**The pre-pass**, or the header pre-pass. `bin/table-headers.py`, which looks at a book's tables before the filter runs. It reads what `table-headers.csv` declares, guesses where every other data table's headers are, and writes the table-header reports ([Sidecar files](sidecars.md#sidecar-files)).

**The census**, or the table census. The reading of a table's shape that the pre-pass and `util/table-census.py` share (`lib/tablecensus.py`): what kind of table each one is, and the guess at which of its cells are headers ([Utilities](utilities.md)).

**The gate.** The point early in a run where it stops, before writing any page, if an image a page shows isn't on disk or can't be identified. It writes `media-unresolved.csv` naming each one.

**Report.** A CSV file a run writes beside the sources, naming what still needs a person: images with no alt text, tables with no description, links to shorten. Reports are written again on every run, and most exist only while there's something in them ([Reports](sidecars.md#reports)).

**Sidecar.** A CSV file you keep beside the sources that holds what you decided about the book and the sources themselves can't say: `image-alt.csv` for alt text, `table-captions.csv` for a table's description, `table-headers.csv` for which cells head a table, and others. Every run reads them, and they outlast a new copy of the sources. You usually make one by filling in a report's rows and appending them to the sidecar ([Sidecars and reports](sidecars.md)).

**Drafted, reviewed, `TI`.** The last two columns of a sidecar record where a value came from and whether a person has checked it. `TI` in the first means TextbookImprover guessed the value ([Who drafted a value](sidecars.md#who-drafted-a-value-and-whether-its-been-reviewed)).

**Decorative.** An image that tells a reader nothing the text doesn't, such as a rule or an ornament. A screen reader should pass over it, and `[decorative]` in place of an image's alt text in `image-alt.csv` marks it so.

**Spacer.** A tiny, usually transparent image a document uses to push things into place or as a bullet ([Spacer images](configuration.md#spacer-images)).

**Data table, layout table.** A data table relates its cells to headers, and needs those headers marked. A layout table only lines things up: a picture in a one-cell box, two columns of text. The conversion turns a one-cell table that only holds a picture into a figure, and a table declared `layout` in `table-headers.csv` is written so that a screen reader doesn't announce it as a table (`role="presentation"` on a page) ([Sidecar files](sidecars.md#sidecar-files)).

**Header declaration.** What `table-headers.csv`, or the guess, says about one table: `first-row`, `first-column`, `both`, `none`, or `layout`. The guess can also answer `unknown`, for a table it can't decide.

**Band.** A merged row partway down a table that labels the rows under it ("Year 2", "Higher Income Countries"). By default, an HTML, EPUB, or PDF target gets a table with bands as one table per band, each captioned with its band, and a Markdown, AsciiDoc, or Word target keeps it as one table; `tables.bands` chooses ([What conversion does to your pages](architecture.md#what-conversion-does-to-your-pages)).

**Sample.** A complete configuration file a tool writes for you to rename: `project-sample.yaml`, `conversion-sample.yaml`, `packaging-sample.yaml`. It lists every setting with its description, at your value where you've set one and the default otherwise. Adopting a sample means renaming it to the real name (`project.yaml`) ([Samples](configuration.md#samples)).

**The two halves.** Conversion (`convert.py`, sources into pages and books) and packaging (`build-cartridge.py`, pages into a cartridge). Each has its own configuration file, and either works without the other. `project.yaml` describes the book for both.

**The packager, a package, a cartridge.** The packager is `bin/build-cartridge.py`. A cartridge is an IMS Common Cartridge, a zip file with the extension `.imscc` that a learning management system imports as a course's modules and pages. A package is one such archive as `packaging.yaml` describes it ([Building the cartridge](packaging.md)).

**Pass-through directory.** `_pt/` in the book's directory, unless `project.yaml` names another: the place for a page someone finished by hand. An `.html` file there is copied into each HTML target as it stands, where an `.html` file beside the sources is converted like any other source ([HTML sources](html.md)).

**Variant, edition.** A variant is a file named `<page>.<target>.<extension>` (`about.print.md`), which takes the place of that page for the one target named. Editions of a book are targets that differ this way, or in passages marked for some targets only ([Editions](configuration.md#editions)).

**Master file.** The file of a LaTeX or AsciiDoc book that pulls in the others, with `\include` or `include::`, and so gives the book's order.

**Unpack.** To turn a book that arrived as one archive or one repository into a book's directory of sources. Each `unpack-…` tool in `bin/` does it for one kind: an EPUB, a saved website, a course cartridge, an OpenStax repository ([Formats](formats.md)).

**Round trip.** Converting a book to a format and then reading the result back as a source, to see what the format kept. `util/compare-output.py` compares the pages from the two readings.

**The output check.** What every run does last: `bin/check-output.py` reads each page, EPUB, and PDF the run wrote and lists what it finds in `output-check.csv` ([Checking the output](checking.md)).

**Finding.** One thing a check found, as one row of a CSV: where, which check, and the detail, then the file, a severity (`error`, `warning`, or `note`), the standard it bears on, the tool that said so, and where the fix belongs ([The findings format](auditing.md#the-findings-format)).

**The audit.** `bin/audit.py`, which checks files without converting them ([Auditing](auditing.md)).

**Deck, slides.** A deck is one presentation: a PowerPoint file, or a Markdown file written as slides. A folder of decks is slides, as opposed to a book ([Slides](slides.md)).

**Bake.** OpenStax's word for turning a book's CNXML source into the book a reader sees: numbering its figures and exercises, gathering each chapter's end-of-chapter pages, and filling in its cross-references. OpenStax's cookbook holds the recipes; `unpack-cnx.py` does the same from a port of them ([Baked as OpenStax bakes it](cnx-input.md#baked-as-openstax-bakes-it)).

**Suite.** One of the test programs in `tests/`. "The PDF suite's book" and the like are small books kept there for the tests, not books anyone reads ([Testing](testing.md)).

**"Here."** In "verified here", "measured here", and "not tried here", the project's own testing, on the setups the [installation page](installation.md) names. "Not tried here" means nobody working on the project has tested it, so a report from someone who has is welcome.

**TESTED, NEEDS MORE TESTING, NOT TESTED.** How far each path from a source format to an output has been tested ([How the paths are rated](formats.md#how-the-paths-are-rated)).

## Other software, formats, and standards

**[Pandoc](https://pandoc.org/).** The document converter everything here is built on. It reads each source into one document format and writes that out as HTML, EPUB, LaTeX, Word, and the rest. A Lua filter is a small program Pandoc runs on a document in between.

**LaTeX, LuaLaTeX, TeX Live, TinyTeX, `tlmgr`.** LaTeX is the typesetting system a PDF is built with, and LuaLaTeX the program that runs it here. TeX Live is the distribution that supplies both, TinyTeX a small TeX Live, and `tlmgr` the program that installs TeX Live's packages ([Installation](installation.md#for-a-pdf-target-lualatex)).

**Tagged PDF, the tagging project, `latex-lab`, `tagpdf`.** A tagged PDF carries its structure (headings, lists, tables, the order to read them in) for a screen reader. The LaTeX Project's [tagging project](https://latex3.github.io/tagging-project/) is making LaTeX write those tags itself; `latex-lab` and `tagpdf` are the packages that hold its code.

**PDF/UA-1, PDF/UA-2, WTPDF, PDF/A.** Standards a PDF can claim to meet. PDF/UA (ISO 14289) is the accessibility standard: part 1 for PDF 1.7, part 2 for PDF 2.0. [Well-Tagged PDF](https://pdfa.org/resource/well-tagged-pdf/) (WTPDF) is the PDF Association's specification for PDF 2.0 files that are accessible and reusable. PDF/A (ISO 19005) is the archiving standard.

**[veraPDF](https://verapdf.org), [PDF4WCAG](https://pdf4wcag.com/), [PAC](https://pac.pdf-accessibility.org).** Programs that check a PDF. veraPDF checks one against PDF/UA, WTPDF, and PDF/A, and a run uses it when it's installed. PDF4WCAG runs veraPDF's WCAG checks. PAC, the PDF Accessibility Checker, is a free Windows program from axes4 that checks against PDF/UA-1.

**EPUB 3, [epubcheck](https://github.com/w3c/epubcheck), [Ace](https://daisy.github.io/ace/).** EPUB 3 is the ebook format: a zip of XHTML pages with a package document that describes them. epubcheck is W3C's validator for it, and Ace is the DAISY Consortium's accessibility checker for it.

**[The Nu HTML checker](https://validator.github.io/validator/).** The validator for HTML that W3C's own checking service runs, also called vnu.

**[WCAG](https://www.w3.org/TR/WCAG22/).** W3C's Web Content Accessibility Guidelines. Each requirement is a numbered success criterion (1.3.1, 1.4.3) at one of three levels: A, AA, or AAA, the strictest. A technique (G141, C20) is a documented way of meeting one.

**[axe-core](https://github.com/dequelabs/axe-core), Playwright.** axe-core is Deque's library of accessibility checks, which run on a page inside a browser. Playwright is the Python package that runs the browser, a Chromium with no window.

**MathML, TeX math, MathJax, texmath.** MathML is the web's format for a formula, which a screen reader can read term by term. TeX math is a formula as LaTeX writes it (`\frac{1}{2}`). MathJax is a script that draws math on a web page. texmath is the library Pandoc converts formulas with.

**MathSpeak.** A set of rules for speaking a formula in words. Alt text written that way spells a name out a letter at a time ("upper C u s t o m e r").

**NVDA, JAWS, Narrator, VoiceOver.** Screen readers. NVDA is the free one for Windows that most of the testing here was done with; JAWS is Freedom Scientific's, also for Windows; Narrator is built into Windows, and VoiceOver into Apple's systems.

**LMS, Common Cartridge, Brightspace.** A learning management system (LMS) is the website a course runs in. Common Cartridge is the IMS format for moving course content between them. Brightspace is D2L's LMS, the only one imports have been tested in ([Brightspace](brightspace.md)).

**WARC, WACZ, MHTML.** Ways a website is saved. A WARC is a web archive, a file holding each address a crawler fetched with what the server sent. A WACZ is a zip of WARCs with an index. MHTML (`.mhtml`) is a browser's save of one page and its images as a single file ([Making a WARC](making-warcs.md)).

**OpenStax, CNXML, Connexions, cookbook.** [OpenStax](https://openstax.org) publishes openly licensed textbooks, the books most of the testing here was done on. CNXML is the XML format it writes them in, which the books of the older Connexions archive are in too. cookbook is OpenStax's own program for baking a book ([A CNXML book as the source](cnx-input.md)).

**[reveal.js](https://revealjs.com), beamer, [ltx-talk](https://ctan.org/pkg/ltx-talk).** reveal.js shows slides as a web page. beamer is LaTeX's long-standing class for slides, and ltx-talk a newer one built for LaTeX's tagging, which a deck's PDF is made with.

**DOI, [shortDOI](https://shortdoi.org/).** A DOI is a permanent identifier for an article (`10.1017/S1751731114000202`), and a shortDOI a short alias for one (`10/abcde`) ([Bare links](bare-links.md)).

**Byte-order mark.** Three bytes at the start of a UTF-8 file that tell Excel the file is UTF-8. These pages sometimes call it "the mark" ([Sidecar files](sidecars.md#sidecar-files)).

**BCP 47.** The standard for language tags: `en`, `es-MX`, `zh-Hant`.

**WSL.** The Windows Subsystem for Linux, which runs Ubuntu inside Windows ([Installation](installation.md#on-windows-wsl-first)).

## The books these pages measure on

Most numbers in these pages come from converting real, openly licensed books, and the pages often name a book by a short form. `notes/CORPUS-NOTES.md` has each one's source, license, and measurements.

- **The statistics book** or **statistics textbook**: OpenStax's *Introductory Business Statistics 2e*, from its Word files unless a page says otherwise.
- **The economics book** or **economics textbook**: a draft economics textbook written in Markdown, a file per chapter. OpenStax's *Principles of Economics 3e* is a different book, and is named in full.
- **DCIC**: *A Data-Centric Introduction to Computing*, a book published as a website.
- **CS168**: the online textbook for Berkeley's CS 168 course, a website whose Markdown source is public (`berkeley-cs168/textbook` on GitHub).
- **The security textbook**: a book written in AsciiDoc (`rxt1077/it230` on GitHub).
- ***Instrumental Analysis***: David Harvey's book on LibreTexts, read from a web archive.
- **GIAM**: Joseph Fields's *A Gentle Introduction to the Art of Mathematics*, a LaTeX book ([osj1961/giam](https://github.com/osj1961/giam)).
- **The calculus notes**: a set of calculus note templates in one LaTeX file, already tagged by their author.
- **FINC 308**: the notes for a financial planning course, 18 LaTeX documents.
- ***OpenIntro Statistics***: a LaTeX book with a style of its own ([OpenIntroStat/openintro-statistics](https://github.com/OpenIntroStat/openintro-statistics)).
- **The corpus**, or **the Word corpus**: nine books' Word files, 1,782 files in all, that the table census was measured on.
