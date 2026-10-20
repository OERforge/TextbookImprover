# A CNXML book as the source

OpenStax writes its books in CNXML, an XML format of its own, and keeps each book's source on GitHub in a repository named `osbooks-…`: the [economics books](https://github.com/openstax/osbooks-principles-economics-bundle), the [statistics books](https://github.com/openstax/osbooks-introductory-statistics-bundle), and the rest. The books of the old Connexions archive are in the same format, in the [cnx-user-books](https://github.com/cnx-user-books) repositories. Unpack one and convert what comes out:

```bash
git clone https://github.com/openstax/osbooks-principles-economics-bundle
python3 $T/bin/unpack-cnx.py osbooks-principles-economics-bundle --list
python3 $T/bin/unpack-cnx.py osbooks-principles-economics-bundle \
    --book principles-economics-3e -o ~/books/econ
cd ~/books/econ
python3 $T/bin/convert.py
```

A repository can hold several books (a "bundle"); `--list` names them, and `--book` picks one. `unpack-cnx.py` reads the repository and never writes to it. It needs lxml (`sudo apt install python3-lxml`, or `pip install lxml`) and nothing else: not Ruby, not Docker, not OpenStax's own tools. Converting what it writes needs Pandoc 3.9 or later, as every conversion does.

## What's written

- **One `.html` per page of the book as OpenStax publishes it**: each section, each chapter's introduction, the pages OpenStax builds at a chapter's end ("Key Terms", "Review Questions"), the answer key, the references, and the index. Each is named as OpenStax names it in its web addresses and Word files (`3-1-demand-supply-and-equilibrium-in-markets-for-goods-and-services`, `3-key-terms`, `chapter-3` for the chapter's answers), so a link to openstax.org, or a sidecar written for the Word files, carries over.
- **The pictures and other files the pages use**, under `media/`. A file a page names that the repository doesn't have is reported, and its description stands where it would have been, since a page naming a missing file stops `convert.py`.
- **`project.yaml`**, with the book's title, language, license, an identifier from the book's UUID, and the outline as `contents`: a group per unit and chapter, a unit of `type: part`, the answer key a group of the back matter. It's yours to edit.
- **`conversion.yaml`**, for an OpenStax book: the footer "Access for free at openstax.org." that the book's license page asks every copy to carry, on every page of every target, in its words, the address not a link, as OpenStax's own PDFs print it (a link whose text is an address, on every page, is what some checkers report as a bare URL); footnotes numbered through each chapter, as OpenStax numbers them (`notes.numbering: group`, a unit's chapters each on their own, a unit being a part); the PDF's page, from `pdf-layout.yaml` (`pdf.metadata`); and, where the book's captions open with another word than `Figure` or `Table` (*Principles of Management*'s and *Introduction to Business*'s "Exhibit", a Polish book's "Ilustracja" and "Tabela"), that word in `captions.figure_prefixes` or `captions.table_prefixes`, so a PDF sets each caption with its own label and no second number of LaTeX's.
- **`pdf-layout.yaml`**, for an OpenStax book: the page its `pdf` and `latex` targets get. The paper and margins are OpenStax's, which the book's tables and formulas were made for: US Letter, or A4 for the two Polish books OpenStax prints on it (styles `pl-u-physics` and `pl-nursing`), with 1 inch at the sides and 0.8 inch at the top and bottom, as OpenStax's stylesheets set them. The type isn't OpenStax's: theirs is 9 point (8.25 in the math books), about 110 characters to a line, and this is TextbookImprover's own at 12 point, about 89, counting spaces. As in OpenStax's PDFs, the lines are 1.5 times the type's size apart and the text is set ragged right, without breaking words; the page number and the footer sit in the bottom margin (`footskip`). It's yours to edit, as any `pdf.metadata` file is ([Formats](formats.md#pdf)).
- **`table-captions.csv`**, a description for each table that `convert.py` would ask one for, taken from the summary the book's author wrote for the table and marked as drafted by OpenStax for a person to review: a table whose caption is only its label ("Table 3.8"), under its label, and a table with no caption at all (OpenStax leaves a table in an answer unnumbered), under its place on its page (`chapter-12#table-5`), the key `convert.py` reports such a table by. A summary that says nothing isn't drafted from: OpenStax's stand-ins ("No Summary", "Assessment data", "Assessment information", "summary", "no alt text", "table", "key equations table", and the like), a note that says why a cell is empty and not what the table holds ("Some cells are left blank for visual design purposes."), and what alt text's checks call a placeholder (".", "---"). Of OpenStax's 6,214 summaries, 1,604 are such. A summary that reads its table out, a row or a cell at a time ("Two rows and five columns. The first row is labeled, “x”, and the second is labeled, “g(x)”. The values of x are 2, 4, 6, and 8…", "Top left cell reads: Essential Knowledge"), is drafted as any other is, the sidecar's row there to rewrite, and is a `table-summary-reads-out` row of the report: drafted as a caption, it's read before the table it repeats, where a caption that says what the table shows would serve. Of the 4,610 summaries that say something, 1,941 read their tables out, 1,283 of them on a table with no title, whose summary is drafted; the rule that finds them knows the ways OpenStax's summaries read a table (its shape and then its values, a row's or a cell's words, ordered pairs, a function's values), in English and Polish, and finds one that repeats its table's cells in words of its own ("Washington 67, J. Adams 90, Jefferson 83…"), six of them, or five that are half its cells, from two columns or more; it leaves out one that only names the columns, or lists one column's cells. A layout table (below) asks for no description, and its summary isn't drafted. And **`cnx-table-summaries.csv`**, every table's summary, and whether it reads its table out.
- **`unpack-report.csv`**, for what the unpacking noticed and didn't decide (see the table below).

## Baked as OpenStax bakes it

A book's source isn't the book a reader sees. OpenStax "bakes" it: numbers its figures, tables, exercises, and equations; titles its notes ("Link It Up"); gathers each chapter's key terms, summaries, and exercises into pages at the chapter's end; moves solutions to an answer key; fills in the text of a link ("Figure 3.2"); makes a link of a web or email address written as text; and builds the index. The recipe differs by book, and its style names it. `unpack-cnx.py` does the baking itself, from a Python port of the recipes in [openstax/cookbook](https://github.com/openstax/cookbook) (MIT License), for these styles:

| Style | Books |
| --- | --- |
| `accounting` | *Principles of Accounting, Volume 1: Financial Accounting* and *Volume 2: Managerial Accounting* |
| `additive-manufacturing` | *Additive Manufacturing Essentials* |
| `algebra-1` | *Algebra 1* |
| `american-government` | *American Government* |
| `anatomy` | *Anatomy and Physiology* |
| `anthropology` | *Introduction to Anthropology* |
| `ap-biology` | *Biology for AP® Courses* |
| `ap-history` | *Life, Liberty, and the Pursuit of Happiness* |
| `ap-physics`, `ap-physics-2e` | *College Physics for AP® Courses* |
| `astronomy` | *Astronomy* |
| `bca` | *Workplace Software and Skills* |
| `biology` | *Biology*, *Concepts of Biology* |
| `business-ethics` | *Business Ethics*, *Business Law I Essentials*, *Introduction to Intellectual Property* |
| `calculus` | *Calculus*, Volumes 1, 2, and 3 |
| `chemistry` | *Chemistry*, *Chemistry: Atoms First* |
| `college-physics`, `college-physics-2e` | *College Physics* |
| `college-success`, `hs-college-success` | *College Success*, *College Success Concise*, *Preparing for College Success* |
| `computer-science` | *Introduction to Computer Science* |
| `contemporary-math` | *Contemporary Mathematics* |
| `data-science` | *Principles of Data Science* |
| `dev-math` | *Prealgebra*, *Elementary Algebra*, *Intermediate Algebra* |
| `economics` | *Principles of Economics*, *Microeconomics*, *Macroeconomics*, and the AP editions |
| `english-composition` | *Writing Guide with Handbook* |
| `entrepreneurship` | *Entrepreneurship* |
| `finance` | *Principles of Finance* |
| `history` | *U.S. History* |
| `hs-physics` | *Physics* (for high school) |
| `information-systems` | *Foundations of Information Systems* |
| `intro-business` | *Introduction to Business* |
| `lifespan-development` | *Lifespan Development* |
| `marketing` | *Principles of Marketing* |
| `microbiology` | *Microbiology* |
| `neuroscience` | *Introduction to Behavioral Neuroscience* |
| `nursing-external` | *Pharmacology for Nurses*, *Nutrition for Nurses*, *Population Health for Nurses* |
| `nursing-internal` | *Clinical Nursing Skills*, whose source isn't public (checked on cookbook's sample alone) |
| `organic-chemistry` | *Organic Chemistry* |
| `philosophy` | *Introduction to Philosophy* |
| `pl-economics` | *Mikroekonomia – Podstawy*, *Makroekonomia - Podstawy* (in Polish) |
| `pl-marketing` | *Marketing - Podstawy* (in Polish), whose source isn't public (checked on cookbook's sample alone) |
| `pl-nursing` | A nursing book in Polish, whose source isn't public (checked on cookbook's sample alone) |
| `pl-psychology` | *Psychologia* (in Polish) |
| `pl-u-physics` | *Fizyka dla szkół wyższych*, Volumes 1, 2, and 3 (in Polish) |
| `political-science` | *Introduction to Political Science* |
| `precalculus` | *College Algebra*, *Algebra and Trigonometry*, *Precalculus* |
| `precalculus-coreq` | *College Algebra with Corequisite Support* |
| `principles-management` | *Principles of Management*, *Organizational Behavior* |
| `psychology` | *Psychology* |
| `python` | *Introduction to Python Programming* |
| `sociology` | *Introduction to Sociology* |
| `statistics` | *Introductory Statistics*, *Introductory Business Statistics*, *Statistics* |
| `u-physics` | *University Physics*, Volumes 1, 2, and 3 |
| `world-history` | *World History*, Volumes 1 and 2 |

A book in Polish is baked with cookbook's Polish words ("Ilustracja 1.2"), and as its Polish recipes bake it: a link names its target in the grammatical case its sentence wants, as the source marks it ("na Ilustracji 1.2"), or in the nominative; its terms are in three indexes, of subjects, names, and words in other languages, each term listed by the form the source gives for the index ("wrażenia zmysłowe" for "wrażeń zmysłowych"); and its glossaries and indexes are sorted as Polish sorts (Ł after L, each a group of its own).

A book in another style, and every book of the Connexions archive, is baked plainly: its figures, tables, and equations numbered within each page, as the archive numbered them, its notes keeping their own titles, and nothing moved. The report says so for an OpenStax style with no recipe here.

What's left out is what only styles OpenStax's own web reader and print: its wrappers, its running heads, the classes its stylesheet reads. What TextbookImprover does itself is left to it: the table of contents, a scope on a header cell, opening a link in a new window, and an embedded video (kept in a web page, a link in an EPUB).

A few things are done differently on purpose:

- **A page's title comes first.** OpenStax puts a chapter introduction's title after the chapter's opening picture and its outline; a page's heading opens it here.
- **A table's caption is a `<caption>`**, at the table's top, where a screen reader announces it; OpenStax sets it below.
- **A footnote is a note as Pandoc writes one**, so the notes settings decide where it goes.
- **A link's text is what baking named its target**, with no `aria-label` that says something else (WCAG 2.5.3).
- **A table that only lays things out is a layout table** (`role="presentation"`), as OpenStax's own HTML marks a table with no head, no caption or title, and no label of OpenStax's. Here it's a table with no head, for what it holds or for where it stands. For what it holds, in any book, of any class, and with any caption: a table of one cell, as *Life, Liberty, and the Pursuit of Happiness* sets its bylines, the *College Success* books the time a section takes, and *Writing Guide with Handbook* its templates; a form of blank lines to fill in and nothing else, as *Statistics* sets a lab's recording sheet; pictures in rows, each with a label at most, as *Algebra 1* sets graphs to compare; and a matching exercise, two lists side by side whose items open with marks of two different series (a blank to fill in, numbers, capitals, small letters, roman numerals), as *Microbiology* and the accounting books set theirs, where a row is no record and neither column heads the other. For where it stands, with no caption but its number: a worked example's steps, each step's words beside its result, in the dev-math books, *Prealgebra 2e*, *Elementary Algebra 2e*, and *Intermediate Algebra 2e* (a table classed `unstyled`, or of another class with no label of OpenStax's, as some of their steps are written), and in *College Algebra with Corequisite Support 2e*'s worked examples and corequisite skills (classed `unstyled`); a section's key terms in a grid, in *Physics* (classed `unstyled`); and a chapter's Key Equations, a formula's name beside the formula, in any book and of any class, as OpenStax's own HTML has them. On the inquiry organizer that opens each chapter of *Life, Liberty, and the Pursuit of Happiness*, the key to the emoji its page titles carry has its first column declared as row headers, each emoji heading the row that explains it, and the organizer itself, the chapter's question and objectives and its supporting questions beside their resources, is a layout table. One of these for where it stands that TextbookImprover's header guess reads a header row in is left a data table, and reported: in the dev-math books, 9 of 2,648, 5 of them tables of data ("Binomial Squares | Product of Conjugates") and 4 of steps or properties. A row of `table-headers.csv` decides otherwise for any of them. The guess is made as `convert.py` makes it, of the cells as Pandoc gives them to it, a formula its TeX; for each of the 3,011 tables in the dev-math books, it's the one `convert.py` makes. Other tables stay data tables: *Principles of Accounting*'s exercises and journal entries, whose debit and credit columns a layout table would lose, the dev-math books' tables of other classes that OpenStax labels, tables of values and of data most of them, and the like.
- **OpenStax's label for a table (`aria-label`) isn't written**, but listed in the report. The labels, written in 2023 from the tables' summaries, describe a table as a picture ("The top row of this table, which is a header row, contains…"), 125 words at the median, nearly all of them (1,683 of 1,685) in the dev-math books; a screen reader reads one on entering its table, before the caption, and a browser ignores a layout table's role when it has one. A table's description is its caption, which every format carries.
- **An address written as text that a typo has made no address** (`https://doi.org:10.1016/…`, a colon for a slash) stays text, and so does one with no host's name (the *Writing Guide*'s advice to give an address without “http://.”). OpenStax's baking links it anyway, and an EPUB holding such a link fails epubcheck. **A closing quotation mark after an address** (“https://docs.google.com.”) is text after its link, with the period before it, where OpenStax's baking makes them part of the address, a host that isn't one.
- **An inline list's items are separated and, if enumerated, lettered** ("a. stratified; b. systematic"), as the archive showed them; OpenStax's Word files run the items together.
- **A term the source writes twice, once with a doubled space, is one index entry**, where OpenStax lists it twice.
- **A term two sections of a chapter define is one term with both meanings** in its Key Terms (*Concepts of Biology*'s "pancreas"), where OpenStax lists it twice, each a list of its own: here the Key Terms are one list, which shouldn't name a term twice.
- **Links to learning objectives stand apart** (*Principles of Accounting*'s "LO 8.2 LO 8.4 Visit a favorite eatery…"), and **a labeled item's label is text** (a checklist's "____"): OpenStax's stylesheet spaces the one and shows the other, and a converted book has no stylesheet of theirs.
- **A list whose items are lettered ⓐ, ⓑ is bulleted.** OpenStax's stylesheet hides such a list's numbers; numbered, an item would read "1. ⓐ".
- **Learning objectives numbered by their place are a numbered list** (*Principles of Marketing*'s "1. Define and describe marketing."). OpenStax's baking writes each number as text in a bulleted list, whose bullets its stylesheet hides, so a converted book showed both. Objectives numbered by section ("1.1.1", as in *Principles of Data Science*) stay a bulleted list with their numbers, which a numbered list can't show.
- **A formula's forced line breaks make its lines the rows of a table of one column** (`<mtable>`), centered in an equation and set at the left elsewhere: *Principles of Marketing*'s "Value = Benefits/Price" over "(V = B/P)", and *Algebra 1*'s steps of a solution. Pandoc's reader drops a break the source writes as `<mspace linebreak="newline"/>`, which put the lines side by side, and MathML Core, which browsers implement, has no such break.
- **A superscript or subscript of the wrong number of parts is a base and its script**: texmath, which Pandoc's reader converts a formula with, reads a script of two parts and no other, so Pandoc kept a formula holding one of any other number as its text. *Fizyka dla szkół wyższych* writes the degree sign, the C, and the power of "°C⁻¹" as three parts of one superscript. A script sits on the symbol just before it, so of three parts or more the last is the script and the one before it its base, what's before them set before them; one of one part is that part alone. Each is reported (`script-repaired`), since the source may have lost a script: *Fizyka*'s unit of angular momentum is "kg⋅m/s", the English edition's kg·m²/s.
- **What cookbook writes for screen readers alone isn't written** ("underline … end underline" around each underlined letter of *SohCahToa*): OpenStax's stylesheet hides it from sight, and a converted book would show it. The underline itself is kept.
- **An unnumbered table keeps its title and caption** in *Astronomy* and *College Physics*, whose recipes number every table, counting the unnumbered ones as OpenStax's books do, and in doing so cut such a table's caption and put nothing back (*Astronomy*'s "Table A").
- **The *Writing Guide*'s retitled pages and sections keep a heading outline**: a Trailblazer page's own title follows its title as a paragraph, not a heading a level down, and "Living by Their Own Words" is a paragraph just before its section's heading. Such a page is named by its own title (`1-2-social-media-trailblazer-selena-gomez`), as OpenStax's table of contents, made before the retitling, names it. The icons beside its annotations, which OpenStax's stylesheet draws and names for screen readers alone, aren't written.
- **A Windows character the source holds as a control code is that character**: text pasted from Word and read as Latin-1 along the way leaves the code U+0096 where an en dash was meant (*Statistics* has hundreds), which an EPUB, a PDF, or a Word file would show as nothing or a box.
- **A reaction's mechanism is captioned as any figure is** (*Organic Chemistry*'s "Figure 11.22 MECHANISM Mechanism of the E1 reaction…"): OpenStax sets that caption above the mechanism, in two blocks beside it, for print.
- **A Chemistry Matters page's title closes up its dash** ("Chemistry Matters—Organic Foods: Risk versus Benefit"), as the book's text writes its dashes; OpenStax's page shows a space either side, where the templates its baking writes with break their lines.
- **A meaning in a Polish book's glossary keeps its formatting**: the source writes each as a paragraph, and OpenStax's baking keeps the first paragraph's text alone, its italics and formulas lost.
- **A note whose kind the Polish words don't name** (the nursing sample's special considerations and safety alerts) has no label, where OpenStax's baking writes "unknown title for note with classes …".
- **A chapter of *Marketing - Podstawy* with no references has no references page**, where OpenStax's baking makes one with nothing on it.
- **A unit of *Algebra 1* is numbered as OpenStax's table of contents numbers it** ("Unit 1 Linear Equations"). The heading their baking gives it counts the unnumbered units before it too ("Unit 3"), and their reader shows the contents, never the heading.
- **A frame of the repository's own** (the code runners of *Introduction to Python Programming*, whose code isn't under the book's license) becomes a link to the page of the online book, where it runs.
- **A program keeps its lines but not its source's indentation.** Code standing apart is a code block, as OpenStax's assembly makes it, its lines numbered where OpenStax numbers them, since the text cites them ("Line 6 shows…"); the indentation the source's markup gives every line is taken off, and a line break written after a newline element is that one line break, not a second. A program's run whose example input is in bold is a paragraph of code, line by line, since a code block can't hold bold.

A link to a module of another book in the same repository (a bundle's microeconomics book to a chapter only the full economics book has) goes to that book's page at openstax.org, named as OpenStax names it.

## Exercises from OpenStax's exercise bank

Many of OpenStax's newer books keep exercises outside the repository, in OpenStax's exercise bank: *Principles of Marketing*'s knowledge checks and end-of-chapter questions, *Foundations of Information Systems*'s review questions, nearly all of *Contemporary Mathematics*'s questions, *Algebra 1*'s practice pages. The page holds a link to the exercise, which `unpack-cnx.py` replaces with the exercise, fetched from the bank's public API (`exercises.openstax.org`), and bakes as the recipe says: numbered, its choices lettered, its solution in the answer key with the right letter first.

The first unpacking of such a book fetches every exercise, several at a time, and keeps each in a cache, `~/.cache/textbookimprover/cnx-exercises` by default (`--exercises-cache` names another), so later runs need no network and the cache can be copied to a machine that has none. `--offline` uses the cache alone. An exercise that can't be had is a sentence saying so where it would stand, and a row in the report.

The bank makes some books' answers public and not others': *Principles of Marketing*'s are, all but two of its 662 questions', *Foundations of Information Systems*'s aren't, so its questions come without their answers and its answer key is empty. OpenStax's own Word files have them, because OpenStax builds with a token the bank's owners issue; one set in the environment variable `OPENSTAX_EXERCISES_TOKEN` is used, and the cache keeps what it brings apart from the public copies.

An exercise's formulas are TeX in the bank; Pandoc's TeX reader makes them MathML, as it does a page's. One it can't read, or every one where Pandoc isn't installed, is left as TeX and reported.

## The report

| Check | What it means |
| --- | --- |
| `style-not-baked` | The book's OpenStax style has no recipe here; it's baked plainly. |
| `media-missing` | A file the module names isn't in the repository; its description stands in its place. One outside it, named by a path that climbs out of it or by a link in it, isn't copied either, since it would go wherever the book is posted. |
| `extension-corrected` | A picture in another format than its name says (a JPEG named `.png`), which an EPUB's reading system and epubcheck go by; it's written under the name its format has, and the pages name that. |
| `image-is-not-an-image` | A picture whose bytes aren't a picture's (a JPEG's bytes each written as two, as text read in one encoding and written in another); it's copied as it is, and nothing shows it. |
| `exercise-missing` | An embedded exercise isn't in the cache and couldn't be fetched (or `--offline`). |
| `exercise-solutions-not-public` | The bank gave the question but not its answer. |
| `exercise-tex`, `exercise-image-missing` | A formula of an exercise's left as TeX, which Pandoc couldn't read; a picture an exercise shows that couldn't be fetched. |
| `link-to-other-book` | A link to a module of another book of the repository, and where it now goes. |
| `link-outside-repository` | A link to a module that isn't in the repository at all; it goes to the Connexions archive's address for it. |
| `link-without-scheme` | A link to a web address written without `https://` (`www.quillproject.net`), which a browser takes for a file of the book's; it's linked with `https://`. |
| `link-to-nothing`, `link-without-text` | A link whose target isn't in the book; a link nothing gave text, which shows its target's title or address. |
| `local-interactive` | A frame of the repository's own, a link to the online book now. |
| `obsolete-media` | Flash, a Java applet, or another kind of media nothing plays now; a link to the file. |
| `unknown-element` | CNXML this doesn't know, kept as a `div` or `span` with a class naming it. |
| `table-kept-as-data` | A table that would be a layout table (a worked example's steps, a Key Equations table, a grid of key terms) that the header guess reads a header row in, left a data table; a row of `layout` in `table-headers.csv` makes it a layout table. |
| `table-summary-reads-out` | A table's description in `table-captions.csv`, drafted from OpenStax's summary, that reads the table out, a row or a cell at a time; a screen reader hears it before the table itself, so what the table shows would serve better in its place. |
| `table-label-left-out` | OpenStax's label for a table, which isn't written, and whether the table is a layout table. |
| `content-mathml` | A formula written in content MathML that isn't one of the simple forms made presentation MathML (names, numbers, relations, arithmetic, powers, roots, a function applied): an integral, say. Pandoc would keep its text and lose the formula. |
| `script-repaired` | A formula's superscript or subscript of other than two parts, which Pandoc would keep as text, made a base and its script, or of one part, that part alone (above). |

## Compared with OpenStax's Word files

OpenStax's Word files are their baked book cut into pages, the nearest thing to an answer key for what baking should produce. `util/cnx-compare-word.py` compares the pages with them word for word, page by page, leaving formulas out (Word has them as Office Math or pictures) and reading a table's caption after the table, where Word has it. Every page's name matches its Word file's. Where the words differ, it's for one of these reasons: the source has been corrected since the Word files were made (OpenStax's errata); a deliberate difference above; Word runs together words a table's cells or a code listing keep apart; or Word lost something (a sentence after a formula, an embedded video's description).

| Book | Pages | Below 98% alike |
| --- | --- | --- |
| *Principles of Economics 3e* | 419 | 10 |
| *Introductory Business Statistics 2e* | 169 | 13 |
| *Introduction to Sociology 3e* | 243 | 31 |
| *Principles of Marketing*, with its 662 exercises from the bank | 311 | 2 |
| *Foundations of Information Systems*, *Principles of Data Science* | 132, 105 | the pages with exercises from the bank, which couldn't be fetched where this was measured; the others as above |

## Compared with cookbook's own baking

[openstax/cookbook](https://github.com/openstax/cookbook) tests each recipe on a sample book: a few chapters of the real one as OpenStax's assembly writes them, and the same chapters as the recipe bakes them. `util/cnx-compare-cookbook.py` bakes each sample with the port here and compares the two, page by page, word for word, leaving out what's done differently on purpose (the link for print beside an embedded video, a footnote's number, an inline list's separators, which `unpack-cnx.py` writes as it reads the source, the words for screen readers alone, the running heads for print, and cookbook's "unknown title" for a note). For every style here, every page of all 62 samples matches (2,129 pages). Most of the samples come with exercises from the exercise bank already in them, so their baking is checked against cookbook's even where the bank can't be reached.

```bash
git clone https://github.com/openstax/cookbook
python3 $T/util/cnx-compare-cookbook.py cookbook
```

`util/cnx-compare-assembly.py` checks the other half, the reading: given a book as OpenStax's own assembly writes it (`neb assemble`, from [openstax/nebuchadnezzar](https://github.com/openstax/nebuchadnezzar), which isn't part of TextbookImprover), it bakes that and `unpack-cnx.py`'s reading of the same repository with the same port and compares them page by page. *Principles of Economics 3e*, *Introduction to Sociology 3e*, *Principles of Management*, *Organizational Behavior*, *Introduction to Business*, both volumes of *Principles of Accounting*, *Business Law I Essentials*, and *Entrepreneurship* read alike on every page; the statistics books differ only where an inline list's separators and letters, or a labeled item's label, are written here as text and shown there by OpenStax's stylesheet, and in the order of two key terms that are formulas (*R* and *R*², chapter 13 of *Introductory Business Statistics*): sorting, OpenStax reads a formula's text as their assembly leaves it, twice over (it adds a copy of each formula in content MathML) and with the indentation of its source, so the *R*² term sorts first.
