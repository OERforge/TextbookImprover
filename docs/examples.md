# Worked examples

Two real books taken from the files their publishers offer to a finished result, one command at a time, with what each command prints. They follow [A first conversion](first-run.md) on real books, so read that first; the settings it explains aren't explained again here. The output below is from running these steps as written. Your numbers may differ if a publisher has changed its files since.

Both examples use `T` for the directory you cloned this repository into:

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
Output check: 169 page(s), 64 finding(s):
     64  link-to-missing-fragment: a link's #fragment matches no id
```

The HTML is already written, one page per Word file, in `html/`. The 1,604 links OpenStax's files make to its own website now point at pages of this book. The run stops at packaging, which needs two things only you can supply:

```
ERROR: packaging.yaml not found.

Wrote packaging-sample.yaml.
Edit it, rename it to packaging.yaml, and run again.
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
Introductory_Business_Statistics_2e_-_DOCX_Customization.zip: not read, since this directory has sources, which are the book once an archive is unpacked.
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

**Alt text.** `image-alt-missing.csv` names each image whose description is missing or too long, with the reason and the description it has now:

```
Image,Alt,Source,Reason,CurrentAlt
1-2-data-sampling-and-variation-in-data-and-sampling/media/rId100.png,,1-2-data-sampling-and-variation-in-data-and-sampling,too long (185 characters),Bar graph consisting of 8 bars with values matching the given data. …
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

**Bare links.** `bare-links-new.csv` lists the 169 addresses the book shows as link text, 165 of them on the chapters' reference pages, each with the citation before it. A screen reader reads each one aloud. They conform as they are, since the citation gives each link its context, so decide what's worth changing: a Title gives the link a tooltip, and text in the Replacement column replaces the address shown, as [Bare links](bare-links.md) explains:

```
URL,Replacement,Title
http://blog.flurry.com,The Flurry Blog,
```

None of this book's addresses is a DOI, so the shortDOI helper has nothing to do here; for a book whose references cite DOIs, it's the quickest way to shorten them.

**The output check.** `output-check.csv` has the 64 links whose `#fragment` names nothing, all from a chapter's solutions page into its practice or homework page. They point at ids OpenStax's export leaves out of its own files, and the `Fix` column says `source` for each: they can be fixed only in the Word files, or by OpenStax.

Run again, and the reports shrink by what the sidecars now answer:

```bash
python3 $T/bin/convert.py
```

```
table-headers: 332 data table(s): 4 blank, 328 declared
Wrote table-captions-missing.csv (261 table(s) needing a description).
Wrote image-alt-missing.csv (207 image(s) needing alt text).
```

The four `blank` tables have a sidecar row with nothing in `headers`: the guess was left blank because the file doesn't say enough to guess. Fill theirs in. This is the loop you'll spend the most time in: add rows, run again, and watch the reports shrink. Nothing requires them to reach zero before you build, but each row left is a table or image a screen-reader user meets without what it needs.

### 7. Build the cartridge

```bash
python3 $T/bin/convert.py --zip
```

```
Wrote org.example.introductory-business-statistics.imscc (18.0 MB, 423 entries).
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
Wrote table-captions-missing.csv (91 table(s) needing a description).
Output check: 80 page(s), 40 finding(s):
     40  heading-skips-level: a heading is more than one level below the last
```

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
```

The EPUB is named for the identifier, and the claims are the accessibility metadata it declares, each checked against what the book holds. The EPUB passes [epubcheck](https://www.w3.org/publishing/epubcheck/) with no message at all, which the run checks for itself when epubcheck is installed ([Installation](installation.md#optional-the-full-validators) says how).

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
