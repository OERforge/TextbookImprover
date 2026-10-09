# Worked examples

Three real books taken from the files their publishers offer to a finished result, one command at a time, with what each command prints. They follow [A first conversion](first-run.md) on real books, so read that first; the settings it explains aren't explained again here. The output below is from running these steps as written. Your numbers may differ if a publisher has changed its files since.

The examples use `T` for the directory you cloned this repository into:

```bash
T=/path/to/TextbookImprover
```

## An OpenStax book, from Word files to a course cartridge

*Introductory Business Statistics 2e*, from the Word files OpenStax gives instructors to a Common Cartridge an LMS can import.

### Getting the files

OpenStax offers the Word files for its books as an instructor resource. Create a free instructor account at [openstax.org](https://openstax.org), then open the [instructor resources for *Introductory Business Statistics 2e*](https://openstax.org/details/books/introductory-business-statistics-2e?Instructor%20resources) and download the Word files. They arrive as one zip, `Introductory_Business_Statistics_2e_-_DOCX_Customization.zip`. OpenStax puts them behind the instructor account on purpose, so when you point someone else to them, point to the resources page rather than to the file.

The book's PDF is free for anyone: download [*Introductory Business Statistics 2e* as a PDF](https://assets.openstax.org/oscms-prodcms/media/documents/introductory-business-statistics-2e_-_WEB.pdf) too. Its bookmarks are the book's table of contents, which step 2 uses for the order of the pages and the chapters' titles.

### 1. A directory of its own, and a first run

Put the zip alone in a new directory and convert:

```bash
mkdir -p ~/books/ibs && cd ~/books/ibs
mv ~/Downloads/Introductory_Business_Statistics_2e_-_DOCX_Customization.zip .
python3 $T/bin/convert.py
```

`convert.py` finds the zip alone in the directory and extracts it, dropping the two folders OpenStax wraps around the files:

```
Unpacked Introductory_Business_Statistics_2e_-_DOCX_Customization.zip: 169 source(s), which are the book from now on. Correct them, not the archive: later runs don't read it again.
```

The 169 Word files are the book from now on. If one needs correcting, correct it; the zip isn't read again. A line per file follows, saying how many bookmarks were moved into the paragraphs they precede, which is a repair the conversion needs and nothing you have to act on. Then come the reports, the part of the output that asks for a person:

```
table-headers: 332 data table(s): 11 needs-source, 321 new
table-headers: 319 table(s) have no sidecar row; prefilled rows are in table-headers-new.csv -- paste them into table-headers.csv
1604 publisher link(s) now point at pages of this book.
Wrote table-captions-missing.csv (262 table(s) needing a description).
Wrote image-alt-missing.csv (208 image(s) needing alt text).
Wrote bare-links-new.csv (169 bare link(s) with no row in bare-links.csv).
61 page(s) keep their declared title without the number their heading puts before it ("1.1 Definitions of Statistics, Probability, and Key Terms" is titled "Definitions of Statistics, Probability, and Key Terms"), in <title> and in the names a cartridge gives its pages; promote_h1_to_title: always titles them with the number.
Wrote math-repaired.csv (1632 math repair(s)).
Output check: 169 page(s), nothing found.
```

The HTML is already written, one page per Word file, in `html/`. The 1,604 links OpenStax's files make to its own website now point at pages of this book. The 1,632 math repairs are equations given the characters they mean, such as the micro sign `µ` where the Greek `μ` was meant, and math typed as text made an equation; `math-repaired.csv` lists each, in case one shouldn't have changed ([Math](configuration.md#math)). The 61 pages are the numbered sections, whose Word files are titled without the number. The output check finds nothing to report.

The run stops at packaging, which needs two things only you can supply:

```
WARNING: contents not specified; using guessed order.
ERROR: packaging.yaml not found.

Wrote packaging-sample.yaml.
Edit it, rename it to packaging.yaml, and run again.
Every setting is in there with its description, so nothing you had set is lost by renaming it.
```

### 2. Order the pages from the book's PDF

Put the PDF beside the Word files and run again with `--toc`, which reads its bookmarks:

```bash
mv ~/Downloads/introductory-business-statistics-2e_-_WEB.pdf .
python3 $T/bin/convert.py --toc introductory-business-statistics-2e_-_WEB.pdf
```

```
Read introductory-business-statistics-2e_-_WEB.pdf: 169 of 169 unplaced page(s) ordered from the outline.
```

The order is in `packaging-sample.yaml` under `contents` now, with the book's own chapter titles:

```yaml
  contents:
  - preface
  - title: Chapter 1 Sampling and Data
    items:
    - 1-introduction
    - 1-1-definitions-of-statistics-probability-and-key-terms
    - 1-2-data-sampling-and-variation-in-data-and-sampling
    - 1-3-levels-of-measurement
    - 1-4-experimental-design-and-ethics
    - 1-key-terms
    - 1-chapter-review
    - 1-homework
    - 1-references
    - 1-solutions
  - title: Chapter 2 Descriptive Statistics
```

Do this before the next step. `--toc` orders only the pages the contents don't place already, and the sample a first run writes places every page, by guessing. So once that sample is adopted as `packaging.yaml`, the PDF has nothing left to order, and `--toc` says so and changes nothing. (If that happens, delete the `contents` block from `packaging.yaml` and run it again.) Without a PDF, step 5 is the way to fix the order by hand.

The run still stops at packaging, as the first one did: the book needs a name.

### 3. Name the book

Open `packaging-sample.yaml`, and near the top set the book's identifier and title:

```yaml
  identifier: org.example.introductory-business-statistics
  title: Introductory Business Statistics 2e
```

The identifier is how an LMS recognizes a later import as the same course, so choose one you'll keep; [A first conversion](first-run.md) says more. Then rename the file and run again:

```bash
mv packaging-sample.yaml packaging.yaml
python3 $T/bin/convert.py
```

This time the run goes through to the end and writes the cartridge's manifest. It also says, as every run from now on will, that the zip beside the Word files isn't read:

```
Introductory_Business_Statistics_2e_-_DOCX_Customization.zip: not read, since this directory has sources, which are the book once an archive is unpacked. To unpack it afresh, extract it into a new directory.
```

### 4. Credit OpenStax on every page

OpenStax asks that every page of a book built from its files carry the line "Access for free at openstax.org." A footer does that. It's Markdown, placed at the bottom of every page, and it goes in `conversion.yaml`, which until now the book hasn't needed:

```bash
cat > conversion.yaml <<'EOF'
defaults:
  footer: "Access for free at [openstax.org](https://openstax.org)."
EOF
python3 $T/bin/convert.py
```

In `defaults`, it applies to every target the book has: to the HTML in the cartridge now, and to an EPUB if you add one later. A footer isn't read by the filters the way a page is, so it isn't checked or changed; write it as it should appear.

### 5. Without the PDF: the guessed order

Without step 2, the pages are in an order guessed from their file names. The guesser knows OpenStax's naming, so each chapter's introduction comes first and its end-of-chapter pages last, as in the PDF's order:

```yaml
  contents:
  - page: preface
    role: front
  - title: Chapter 1
    items:
    - 1-introduction
    - 1-1-definitions-of-statistics-probability-and-key-terms
    - 1-2-data-sampling-and-variation-in-data-and-sampling
    - 1-3-levels-of-measurement
    - 1-4-experimental-design-and-ethics
    - 1-key-terms
    - 1-chapter-review
    - 1-homework
    - 1-references
    - 1-solutions
```

What it can't know is what the chapters are called. Give each its title from the book's contents, which then shows in the LMS's outline:

```yaml
  - title: Chapter 1 Sampling and Data
```

### 6. Work through the reports

Each report is a CSV file listing what needs a person, and each decision goes into a sidecar file beside it, which later runs read. [Sidecar files](sidecars.md) describes them all; this is how the first pass goes.

**Table headers.** `table-headers-new.csv` has a row for each table with a guess in its `headers` column (`first-row`, `first-column`, `both`, or `none`) and the start of the table in `preview`. A table that appears more than once, identical, has one row, which is why there are 319 rows for 332 tables. Read the guesses, correct any that are wrong, and make the file the sidecar:

```bash
cp table-headers-new.csv table-headers.csv
```

Each guess says `TI` in its `drafted-by` column, since TextbookImprover made it. It's used as it stands, and once you've checked a row, your initials in its `reviewed` column say so ([Who drafted a value](sidecars.md#who-drafted-a-value-and-whether-its-been-reviewed)).

**Alt text.** `image-alt-missing.csv` names each image whose description is missing or too long, with the reason and the description it has now:

```
Image,Alt,Source,Reason,CurrentAlt,Drafted by,Reviewed
1-2-data-sampling-and-variation-in-data-and-sampling/media/rId100.png,,1-2-data-sampling-and-variation-in-data-and-sampling,too long (185 characters),Bar graph consisting of 8 bars with values matching the given data. …,,
```

Write a shorter description in the `Alt` column and put the row in `image-alt.csv`. An image that carries no meaning gets `[decorative]` instead:

```
Image,Alt
1-2-data-sampling-and-variation-in-data-and-sampling/media/rId100.png,"Bar graph of the number of students at each level of the survey question, one bar per response."
```

**Table descriptions.** `table-captions-missing.csv` names each table without a description, with its label and the start of its text. Descriptions go in `table-captions.csv` the same way:

```
Label,Description
Table 1.1,"Speeds at which cars crashed, by the location of the driver."
```

**Bare links.** `bare-links-new.csv` lists the 169 addresses the book shows as link text, 164 of them on the chapters' reference pages, each with the citation before it. A screen reader reads each one aloud. They conform as they are, since the citation gives each link its context, so decide what's worth changing: a Title gives the link a tooltip, and text in the Replacement column replaces the address shown, as [Bare links](bare-links.md) explains:

```
URL,Replacement,Title
http://blog.flurry.com,The Flurry Blog,
```

None of this book's addresses is a DOI, so the shortDOI helper has nothing to do here; for a book whose references cite DOIs, it's the quickest way to shorten them.

Run again, and the reports shrink by what the sidecars now answer:

```bash
python3 $T/bin/convert.py
```

```
table-headers: 332 data table(s): 4 blank, 328 declared
Wrote table-captions-missing.csv (261 table(s) needing a description).
Wrote image-alt-missing.csv (207 image(s) needing alt text).
Wrote bare-links-new.csv (168 bare link(s) with no row in bare-links.csv).
315 value(s) in the sidecars were drafted by TextbookImprover or a model and not yet reviewed (table-headers.csv 315); they're used as they stand. Put a name or initials in a row's Reviewed column once a person has checked it.
```

The four `blank` tables have a sidecar row with nothing in `headers`: the guess was left blank because the file doesn't say enough to guess. Fill theirs in. The 315 drafted values are the rest of the guesses you copied, and the count falls as you fill in `reviewed`. This is the loop you'll spend the most time in: add rows, run again, and watch the reports shrink. Nothing requires them to reach zero before you build, but each row left is a table or image a screen-reader user meets without what it needs.

### 7. Build the cartridge

```bash
python3 $T/bin/convert.py --zip
```

```
Wrote org.example.introductory-business-statistics.imscc (18.1 MB, 423 entries).
```

Now you have a Common Cartridge file that you can import into your LMS of choice.

## A book website, from a WARC to an EPUB

*A Data-Centric Introduction to Computing* (DCIC) is published as a website, generated by Scribble, with no EPUB or Word files to download. This example captures the site in a WARC, turns it into an EPUB, and then converts the HTML it wrote a second time, to show the pages read back as the same book.

### Getting the files

A WARC is a web archive: every page and file a crawler fetched, stored as it was served. [Making a WARC](making-warcs.md) explains the options; this is the command used for this example, starting at the contents page of the edition dated 2025-08-27:

```bash
mkdir -p ~/warcs/dcic && cd ~/warcs/dcic
wget --recursive --level=inf --no-parent --page-requisites \
     --wait=0.5 --random-wait --no-verbose \
     --warc-file=dcic \
     https://dcic-world.org/2025-08-27/index.html
```

`--wait=0.5 --random-wait` spaces the requests out, which is the courteous way to crawl someone else's site. It writes `dcic.warc.gz`, about 12 MB, beside a copy of the site that can be deleted afterward.

### 1. A directory of its own, and a first run

```bash
mkdir -p ~/books/dcic && cd ~/books/dcic
mv ~/warcs/dcic/dcic.warc.gz .
python3 $T/bin/convert.py
```

```
Unpacked dcic.warc.gz: 80 source(s), which are the book from now on. Correct them, not the archive: later runs don't read it again. unpack-report.csv says what the unpacking found.
table-headers: 85 data table(s): 85 new
table-headers: 50 table(s) have no sidecar row; prefilled rows are in table-headers-new.csv -- paste them into table-headers.csv
Wrote table-captions-missing.csv (91 table(s) needing a description).
Wrote bare-links-new.csv (2 bare link(s) with no row in bare-links.csv).
Output check: 80 page(s), 40 finding(s):
     40  heading-skips-level: a heading is more than one level below the last
```

Before the reports, most pages get a line naming the tags the reader dropped, keeping what they held: nearly all are Scribble's `<wbr>`, a hint where a long name may break. A few pages get a line saying an id was moved onto an anchor, so that links to it still land. Neither asks anything of you.

The unpacking recognized Scribble, took its navigation off each page, and made a page of each of the book's 80 pages. Unlike the Word files, the website says what the book is, so the unpacking also wrote `project.yaml` from it: the title, the authors, an identifier made from the address, and the order of the pages, taken from the site's own menus.

```yaml
project:
  identifier: dcic-world.org-2025-08-27
  title: "A Data-Centric Introduction to Computing"
  language: "en"
  authors:
    - "Kathi Fisler"
    - "Shriram Krishnamurthi"
    - "Benjamin S. Lerner"
    - "Joe Gibbs Politz"
  contents:
    - page: index
      title: "A Data-Centric Introduction to Computing"
    - page: booklet_intro
      title: "I Introduction"
    - title: "II Introduction to Programming"
      items:
        - page: booklet_intro-to-programming
          title: "II Introduction to Programming"
```

It's yours to edit. Because it names the book, this first run doesn't stop at packaging. The 40 headings that skip a level are how DCIC's pages are built (a page's title, then its sections at the third level), which the check reports and leaves as they are. The reports are worked through as in the first example.

### 2. An EPUB

A run with no `conversion.yaml` writes HTML only. To have an EPUB too, name both targets:

```bash
cat > conversion.yaml <<'EOF'
targets:
  html:
    format: html
  epub:
    format: epub3
EOF
python3 $T/bin/convert.py
```

```
Wrote epub/dcic-world.org-2025-08-27.epub: 80 page(s), 42 image(s), 0 without alternative text.
  Claims: accessMode textual, visual; sufficient textual; features structuralNavigation, tableOfContents, readingOrder, alternativeText, MathML.
  epubcheck ran on 1 EPUB(s).
Output check: 80 page(s) and 1 EPUB(s), 80 finding(s):
     80  heading-skips-level: a heading is more than one level below the last
```

The EPUB is named for the identifier, and the claims are the accessibility metadata it declares, each checked against what the book holds. The EPUB passes [epubcheck](https://www.w3.org/publishing/epubcheck/) with no message at all, which the run checks for itself when epubcheck is installed ([Installation](installation.md#optional-the-full-validators) says how). With an EPUB target, the output check reads the EPUB's pages as well as the HTML, so the 40 headings are counted twice, once in each.

### 3. The round trip

The HTML this pipeline writes is also a source: converting it again should give the same book. Copy the pages and `project.yaml` to a new directory and convert them:

```bash
mkdir ../dcic-check && cp -r html/. project.yaml ../dcic-check/
cd ../dcic-check
python3 $T/bin/convert.py
```

Then compare the two runs page by page:

```bash
python3 $T/util/compare-output.py ../dcic/html html
```

```
Pages: 80 in baseline, 80 in candidate, 80 in both
  80 identical, 0 differing
  …
    page links:        228, all resolve
  …
Runs agree.
```

All 80 pages are identical, and all 228 links between them resolve. So the pages you publish from this conversion are also a source you can keep the book in, edit as HTML, and convert again.

## A LaTeX book, from its repository to a tagged PDF

Joseph E. Fields's [*A Gentle Introduction to the Art of Mathematics*](https://github.com/osj1961/giam) (GIAM) is an open textbook kept as LaTeX on GitHub under the GFDL: nine chapters, each a file the master `\include`-s, with figures drawn in xfig that the book's own Makefile turns into LaTeX. This example converts it to HTML and an EPUB, then writes a copy of its LaTeX that builds a tagged PDF, and has the run make that PDF itself. Besides LaTeX itself, it needs `pdftocairo` for the drawings ([Installation](installation.md)) and, for the book's own build, `fig2dev` (`sudo apt install fig2dev`). The output below is from commit 167696e, with paths shortened to the file's name.

### Getting the files

```bash
mkdir -p ~/books && cd ~/books
git clone https://github.com/osj1961/giam
cd giam
```

The clone is the book's directory: the conversion reads it in place, never writes the author's files, and puts what it makes beside them.

### 1. Which file is the book

```bash
python3 $T/bin/convert.py
```

```
3 files here are each a whole LaTeX document: GIAM-hw.tex, GIAM-solutions_manual.tex, GIAM.tex. Set latex.main to the one that is the book, or list them all when each is a part of it.
```

One set of chapters makes the textbook, a workbook, and a solutions manual, each with a master file of its own. Name the textbook's:

```bash
cat > conversion.yaml <<'END'
defaults:
  latex:
    main: GIAM.tex
END
```

### 2. The book's own build

```bash
python3 $T/bin/convert.py
```

```
GIAM.tex reaches 93 file(s) that aren't here: figures/Eratosthenes.tex, figures/if-then_flowchart.tex, figures/div_alg_flowchart.tex, figures/Euc_alg_flowchart.tex, figures/betweenness_example.tex, figures/transistor.tex, figures/series.tex, figures/parallel.tex, .... A book's own build often makes files like these (figures drawn by another program, say), and it has to run before the book is converted, since what it makes is what the conversion reads. Makefiles are here, Makefile, figures/Makefile: run make in the one that makes them. Nothing was converted.
```

The chapters `\input` figures that fig2dev writes from the xfig drawings, and the repository holds only the drawings. The conversion reads LaTeX, so the book's own build comes first:

```bash
(cd figures && make)
```

### 3. A first run

```bash
python3 $T/bin/convert.py
```

```
GIAM.tex is the book: 11 page(s), one for each file it \include-s, and 2 for what it holds itself, each part or chapter it sets between them a page of its own.
93 of 93 drawing(s) made images by LaTeX, in rendered/.
Read from a copy of the LaTeX: 21 \ifthenelse on a boolean read as a toggle; 1 \cline or \cmidrule read as a whole rule; 50 line break in a minipage read as \newline; 1 space between words a command sets (\hspace, \quad, \hfill) kept as a space, which the reader dropped, running the words together; 10 PDF or EPS image made SVG; 8 \ref to an enumerated item written as the item's number; 847 group or number after a command the reader takes whole kept apart from it, so it's read; 755 box (\fbox, \makebox, \resizebox, and the like) read as what it holds, which the reader dropped with it; 17 bibliography entry written out from BibTeX's .bbl, in the book's style, where the bibliography is; 16 citation written as the label LaTeX prints, linked to its entry; 65 reference or counter given the value LaTeX gives it.
Wrote latex-conversion-macros-sample.tex: 3 macro(s) whose formulas texmath can't make MathML of, with a definition suggested for 2 and 1 for a person to define. Check it, then save it as latex-conversion-macros.tex.
37 LaTeX cross-reference(s) resolved to the section or id they name.
No contents declared: contents-sample.yaml holds the order the master file gives, and its title and authors. Copy it into project.yaml to use it.
table-headers: 102 data table(s): 4 needs-source, 98 new
Wrote table-captions-missing.csv (99 table(s) needing a description).
Wrote image-alt-missing.csv (102 image(s) needing alt text).
Wrote bare-links-new.csv (10 bare link(s) with no row in bare-links.csv).
Output check: 11 page(s), 141 finding(s):
    104  image-without-alt: an img element has no alt attribute
     37  table-without-headers-or-caption: a data table with no th and no caption
...
ERROR: packaging.yaml not found.
```

LaTeX drew each of the 93 drawings as an SVG, and the pages are in `html/`: one for each chapter, one for what the master holds before them (the copyright page and acknowledgments), and one for the bibliography BibTeX made, which comes after them, with the book's 16 citations linked to it. The run stops at packaging, as [the first example's](#1-a-directory-of-its-own-and-a-first-run) did, until step 5 names the book. The book was read from a copy put right for Pandoc's reader: GIAM's `\ifthenelse` chooses between the textbook and the workbook, which the reader would drop, so each is read as a toggle set as the master sets it. [LaTeX sources](latex.md) lists what is put right and why. Among these lines Pandoc warns 57 times that it couldn't make MathML of a formula and left it as TeX, as in:

```
[WARNING] Could not convert TeX math \; \rule[-3pt]{.5pt}{13pt} \;, rendering as TeX:
```

### 4. Definitions for the formulas

Those formulas use three of the book's own macros, and `latex-conversion-macros-sample.tex` says which:

```latex
% \nrelR is used in 3 formula(s). The book has:
%   \newcommand{\nrelR}{\mbox{\raisebox{1pt}{$\not$}\rule{1pt}{0pt}{\textsf R}}}
% Only a person can say what this draws:
% \renewcommand{\nrelR}{}

% \restrict is used in 8 formula(s). The book has:
%   \newcommand{\restrict}[2]{#1 \,\rule[-4pt]{.25pt}{14pt}_{\,#2}}
% Suggested: it draws what this says; check that it means it.
\renewcommand{\restrict}[2]{#1 |_{ #2}}

% \suchthat is used in 49 formula(s). The book has:
%   \newcommand{\suchthat}{\; \rule[-3pt]{.5pt}{13pt} \;}
% Suggested: it draws what this says; check that it means it.
\renewcommand{\suchthat}{\mid}
```

GIAM draws "such that" and a function's restriction as bars made of rules, which say nothing to a screen reader; the suggestions say what they mean. `\nrelR`, "is not related to," is an R with a raised slash, and the sample leaves it to a person. Save the sample as `latex-conversion-macros.tex` with that line filled in:

```latex
\renewcommand{\nrelR}{\mathrel{\not R}}
```

The file is read after the book's preamble, so its definitions win over the book's. The book's own files are never changed; a `source` target, in step 6, writes them into its copy.

### 5. Name the book, and an EPUB

`contents-sample.yaml` holds what the master says about the book, its last entry the bibliography's page, named for the master and numbered (`GIAM-1`), with `type: bibliography`, which puts it in the back matter and marks it as a bibliography in the EPUB. Its title reads "A Gentle Introduction to the Art of Mathematics Version 3.2 N", since GIAM's `\title` sets the version below the title, so correct it as you copy the rest into `project.yaml`, and give the book an identifier:

```yaml
project:
  identifier: giam-3.2
  title: A Gentle Introduction to the Art of Mathematics
  authors:
  - Joe Fields
  language: en
  contents:
  - GIAM
  - intro
  - logic
  - proof1
  - sets
  - proof2
  - rel
  - proof3
  - card
  - proof4
  - page: GIAM-1
    type: bibliography
```

Then name an EPUB target beside the HTML:

```bash
cat > conversion.yaml <<'END'
defaults:
  latex:
    main: GIAM.tex
targets:
  html:
    format: html
  epub:
    format: epub3
END
python3 $T/bin/convert.py
```

```
Read from a copy of the LaTeX: 21 \ifthenelse on a boolean read as a toggle; ...; 65 reference or counter given the value LaTeX gives it; the definitions in latex-conversion-macros.tex read after the preamble.
...
Wrote epub/giam-3.2.epub: 11 page(s), 104 image(s), 104 without alternative text.
  Claims: accessMode textual, visual; sufficient textual,visual; features structuralNavigation, tableOfContents, readingOrder, MathML.
  epubcheck ran on 1 EPUB(s).
Output check: 11 page(s) and 1 EPUB(s), 284 finding(s):
    104  image-empty-alt-not-decorative: alt is empty but the image is not marked aria-hidden="true"
    104  image-without-alt: an img element has no alt attribute
     76  table-without-headers-or-caption: a data table with no th and no caption
```

No formula is left as TeX now: Pandoc warns about none, and every one in the book is MathML. The EPUB passes epubcheck. What's left is the reports: alt text for the 102 images and drawings, and headers and descriptions for the tables, worked through as in [the first example](#6-work-through-the-reports). Until then the EPUB doesn't claim `alternativeText`, and the check finds each image twice, once in the HTML and once in the EPUB.

### 6. A copy of the LaTeX that builds a tagged PDF

The book's PDF is LaTeX's to make. A `source` target writes the book's own files back with what the reports decided, and `tagging: "on"` makes them build with LaTeX's tagging, for a PDF a screen reader can follow. Add one:

```bash
cat >> conversion.yaml <<'END'
  tagged:
    format: source
    tagging: "on"
END
python3 $T/bin/convert.py
```

```
tagged: 154 LaTeX file(s) written, 3 of them changed: 0 image(s) and drawing(s) given alt text and 0 marked artifact, as keys LaTeX's tagging reads. 3 definition(s) from latex-conversion-macros.tex written after the preamble, as the conversion reads them. Made to build with LaTeX's tagging, with LuaLaTeX: \DocumentMetadata added, 2 pdftex option(s) and 1 pdfTeX setting(s) taken out, luatex85 loaded for LuaLaTeX, so a test for pdfTeX (\ifx\pdfoutput\undefined) takes it for pdfTeX and pdfTeX's commands work, 2 starred theorem(s) defined only when tagging hasn't, \centerline on a line of its own made a centered paragraph, unicode-math loaded, so each formula carries its MathML, with the OpenType Latin Modern fonts (TeX's own design) and a fallback for characters they lack, the PostScript font families the book names (ptm) set in TeX Gyre's OpenType clones, where installed, which the OpenType fonts' encoding has, 51 figure(s) and table(s) tagged where the text has them, not gathered at the end of the document, and 1 display formula(s) opening a paragraph in a center environment given \leavevmode.
tagged: the book's other master(s) written too, GIAM-hw.tex with 9 file(s) only it reaches, 0 image(s) and drawing(s) given alt text and 0 marked artifact; GIAM-solutions_manual.tex, which reaches no file the others don't, 0 image(s) and drawing(s) given alt text and 0 marked artifact, each made to build with LaTeX's tagging as the book's is; luatex85 loaded for LuaLaTeX in GIAM-hw.tex, GIAM-solutions_manual.tex, for a test for pdfTeX (\ifx\pdfoutput\undefined) and pdfTeX's commands.
```

The run also checks GIAM's class and packages against the LaTeX tagging project's status list, from TeX's `latex-tagging-status` package. TinyTeX doesn't install it, and then the run says how (`tlmgr install latex-tagging-status`); with it, the run says:

```
Tagging status of the book's class and packages (2026-09-27): partially compatible: hyperref, amssymb, amsmath, amsthm; unchecked: babel. The list only advises; https://latex3.github.io/tagging-project/tagging-status/ says why, and what to use instead where there's a replacement.
```

None of GIAM's is rated incompatible, and the copy builds clean below.

`tagged/` holds every file the master reaches, at the same paths, and the book's two other masters, the workbook and the solutions manual, with the exercise files only the workbook reaches. Both choose their class options with an old test for pdfTeX that LuaLaTeX fails, since LuaTeX has no `\pdfoutput`, and so would take LaTeX with dvips; the copy loads `luatex85` for LuaLaTeX, which gives it pdfTeX's commands, so the test takes LuaLaTeX for pdfTeX, as it does where one of the chapters uses it to choose `.pdf` figures over `.eps`. Lay it over a clean copy of the repository and build it with LuaLaTeX in place of the Makefile's pdfLaTeX, which runs out of memory on a tagged book this size. `latexmk`, which comes with TeX Live, runs BibTeX, makeindex, and as many LuaLaTeX passes as the book needs:

```bash
git clone . ../giam-tagged
cp -r tagged/. ../giam-tagged/
cd ../giam-tagged
(cd figures && make)
latexmk -lualatex GIAM
```

That's four LuaLaTeX passes, as many as GIAM's own Makefile makes with pdfLaTeX, in about eight minutes; without the MathML it takes four. Tagging's references settle over them too: a link to a figure or a table points at the number tagging gave its structure on the pass before, and until the numbers settle the log warns that some links' destinations have no structure. Settled, the PDF has 434 pages and no error, and its only tagging warnings are one for each of its 195 figures, for the alt text the book doesn't have yet. Each of its 4,521 formulas carries its MathML, both as structure a screen reader can walk and as an attached file, made from unicode-math's fonts, which have GIAM's look. Each figure's tags are where the text has the figure, so a screen reader meets it there, not at the end of the book. The definitions are in it too: `\suchthat` is the relation `\mid`, not a bar drawn with a rule. [veraPDF](https://verapdf.org/) passes it as PDF/UA-2:

```bash
verapdf --flavour ua2 --format text GIAM.pdf
```

```
PASS GIAM.pdf ua2
```

The workbook and the solutions manual build the same way after it, `latexmk -lualatex GIAM-hw` and `latexmk -lualatex GIAM-solutions_manual`, since they take their references to the textbook from its `.aux` (the `xr` package). They have 197 and 160 pages, as many as with pdfLaTeX, and both pass too.

That pass says less than it seems. With nothing in `image-alt.csv`, LaTeX gives each figure a placeholder for its alt text, `picture environment` or the image's file name, and veraPDF can't tell a placeholder from a description. Once the image-alt sidecar has the book's descriptions, the next run writes each into the copy, as `\begin{picture}[alt={...}]` or `\includegraphics[alt={...}]`, and the PDF built from it carries them. 93 of the drawings are in the files fig2dev writes, so their descriptions go into the copy's versions of those files, and running `make` in the copy again would write over them; the run says so. [LaTeX sources](latex.md#the-source-target) says what the copy changes and why.

### 7. The PDF, made by the run

A `pdf` target makes the same PDF in the run, from a copy of the book's folder that the run makes itself, and the output check runs on it with the pages:

```bash
cat >> conversion.yaml <<'END'
  pdf:
    format: pdf
END
python3 $T/bin/convert.py
```

```
Wrote pdf/giam-3.2.pdf: 434 page(s), built by LaTeX from the book's own files, made to build with LaTeX's tagging as a source target would make them: 0 image(s) and drawing(s) with alt text and 0 marked artifact, 57 table(s) with a header row and 13 with a header column declared, a person's or the census's, each formula with its MathML, its figures and tables tagged where the text has them, and 195 figure(s) LaTeX gave a placeholder for alt text, which image-alt.csv can describe.
...
Output check: 11 page(s), 1 EPUB(s), and 1 PDF(s), 479 finding(s):
    104  image-empty-alt-not-decorative: alt is empty but the image is not marked aria-hidden="true"
    104  image-without-alt: an img element has no alt attribute
     76  table-without-headers-or-caption: a data table with no th and no caption
  giam-3.2.pdf: 186 pdf-figure-alt-is-placeholder: a figure's alternative text in the PDF is the placeholder LaTeX writes for a drawing that has none
  giam-3.2.pdf: 9 pdf-figure-alt-is-file-name: a figure's alternative text in the PDF is a file name, which is what LaTeX writes when an image has none
```

It differs from the `tagged` copy in one way: every table's headers are declared as the pages have them, the census's guesses included, where the copy, which goes back to the author, declares only what a person decided. The run with the other targets takes about nine minutes. The output check finds what veraPDF can't, the placeholders LaTeX gave the 195 figures, so the PDF is done when `image-alt.csv` is. With `pdf.from: pages` the PDF is made from the pages through Pandoc instead, as for a book from any other source: 324 pages, also passing PDF/UA-2, with the bibliography but without the index ([LaTeX sources](latex.md#the-pdf-target)).
