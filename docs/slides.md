# Slides

A folder of PowerPoint decks is slides. Each deck is checked as PowerPoint's own Accessibility Checker checks it, and for more besides; what needs a person's decision goes into the reports, as a book's does, keyed so one decision covers every place it applies; and a `source` target writes the decisions made so far into a copy of each deck, changing nothing else. The run never guesses into a deck: a copy holds only what a person decided in the sidecars, apart from two things it takes from the project and the deck, and two repairs of XML PowerPoint can't read, below.

That's the first part of slides support. Converting a deck to HTML, to a tagged PDF, or to Markdown, decks written in Markdown, and decks packaged beside a book come later ([ROADMAP.md](../ROADMAP.md#3-slides-and-test-banks)).

## A first run

Put the decks in a folder of their own and run `convert.py` there:

```bash
cd stats-slides
python3 $T/bin/convert.py
```

A slides run needs Python and PyYAML from the [requirements](installation.md#requirements), and not Pandoc, which a book's run reads its sources with.

On OpenStax's 13 decks for _Introductory Business Statistics 2e_, the run begins:

```
Slides: 13 PowerPoint deck(s), each checked and remediated on its own, since they're all this folder holds.
Checked 13 deck(s): 165 finding(s): 21 errors, 144 warnings.
  - `pptx-alt-too-long` ×144: alt text longer than images.alt_max_chars
  - `pptx-alt-placeholder` ×21: alt text that says nothing about the image: punctuation, a word such as "image", a default name, a clip-art id, or a pattern from images.alt_placeholders
Written to slides-check.csv.
Wrote image-alt-missing.csv (165 picture(s) and object(s) needing alt text).
Fill in the second column, then append the rows to image-alt.csv.
```

It then writes a copy of each deck to `remediated/` and checks the copies (`output-check.csv`). On the first run, nothing has been decided yet, so the copies match their originals. The 21 placeholders are `...` and `..`, 12 of them on the regression deck's scatter plots.

A folder holding `.pptx` files and nothing a book is read from (a `README.md` aside) is slides without being told. In a folder with other files, `project.kind: slides` in `project.yaml` says so; the other files are then left out, and the run names them. A deck in a book's folder is left out of the book, and the run says so too. Decks can come in a zip or a tar (`.tar.gz`, `.tgz`, `.tar`), which the first run unpacks as it unpacks a book's archive: a folder that wraps everything is dropped, and what macOS adds (`__MACOSX`, `._` files) is left out. An entry that would land outside the folder, or a link, is refused and listed in `unpack-report.csv`. With no target in `conversion.yaml`, the run implies one, `remediated`, with format `source`. A deck that can't be read, such as one saved with a password, is named with the reason, and the rest go on.

## What's checked

The findings go to `slides-check.csv`, in the format every check here shares ([Auditing](auditing.md#the-findings-format)). `audit.py` writes the same findings as a report to read. They start with what PowerPoint's Accessibility Checker reports, as [WebAIM's guide to it](https://webaim.org/resources/evaloffice/2019) lists them:

- **Errors**: a slide with no title (`pptx-slide-no-title`); a picture, chart, SmartArt graphic, embedded object, or video with no alt text that isn't marked decorative (`pptx-object-no-alt`), or whose alt text holds a file name or extension, which PowerPoint counts as missing (`pptx-alt-is-file-name`: its rule is that alt text "doesn't contain image names or file extensions," [Microsoft says](https://support.microsoft.com/office/rules-for-the-accessibility-checker-651e08f2-0fc3-4e10-aaca-74b4a67101c1)); a table with no header row (`pptx-table-no-header`); and a section that still has PowerPoint's default name (`pptx-section-default-name`).
- **Warnings**: a table with merged cells (`pptx-merged-cells`); a slide whose shapes are read in a different order from how they're laid out, top to bottom and left to right, its title not first, or two shapes that don't overlap read in the opposite order (`pptx-reading-order`); and audio or video, which needs captions (`pptx-media-no-captions`).
- **Notes**: slides with the same title (`pptx-duplicate-title`) and sections with the same name (`pptx-duplicate-section`).

What the pipeline checks elsewhere, and what older decks are made of, is checked as well:

- Alt text that says nothing: punctuation alone, a word such as "image" or "picture," a clip-art id (`j0309720`), a camera's file name (`IMG_2041`), a shape's default name (`Picture 9`), or a pattern the project lists in `images.alt_placeholders` (`pptx-alt-placeholder`, an error). Alt text that Office generated (`pptx-alt-auto-generated`, PowerPoint's "Review Auto-Generated Description"), or that's longer than `images.alt_max_chars` (`pptx-alt-too-long`).
- A group, or a shape with no text, with no alt text (`pptx-shape-no-alt`, a warning). PowerPoint asks for alt text on these too. A group's pieces without text are the group's to describe, so only the group is named, but a picture inside a group still needs alt text of its own.
- A decorative shape that still has alt text (`pptx-decorative-with-alt`), which a converter may read.
- A picture on a layout or master with no alt text (`pptx-master-image-no-alt`, a note). PowerPoint's checker doesn't look there, but every slide using the layout shows the picture.
- A deck that declares no language (`pptx-no-language`), and a deck whose properties have no title (`pptx-no-core-title`), which a PDF exported from it takes as its own.
- A hidden slide (`pptx-hidden-slide`), and a link whose text is its own address (`pptx-link-bare-url`).
- A diagram drawn from eight or more loose shapes, lines, and one- or two-word labels (`pptx-drawn-diagram`). A screen reader reads each piece on its own. Group it and describe the group, or replace it with a picture that has alt text.
- Columns of text laid out with tabs (`pptx-tab-table`), which a screen reader reads as a run of words, not as a table.
- XML that PowerPoint can't read as written (`pptx-malformed`, an error): a shape with nothing in it, which stops PowerPoint opening the deck ("Sorry, PowerPoint can't read" it), and a prefix used without its namespace declared, which PowerPoint repairs by removing content. Pandoc's PowerPoint writer writes both: an empty shape for a date when the reference document's title layout has no date placeholder, and `a14` undeclared in a table holding a formula. A copy has both put right ([The copy](#the-copy)).

`images.alt_placeholders` is the project's own list, for junk alt text a corpus turns out to have: each entry is matched against the whole alt text, ignoring case, surrounding spaces, and closing punctuation. An entry starting `re:` is a regular expression that the whole alt text must match:

```yaml
defaults:
  images:
    alt_placeholders: ["slide image", "re:fig\\. ?\\d+"]
```

It's read for decks for now. Each check's meaning, severity, and standard are listed in `lib/findings.py`.

## The reports and the sidecars

Each report is written only when it has rows, and a stale one is removed. A report being there means there's something to decide. A row is adopted the way a book's is: fill in the second column and append the row to the sidecar. A header row pasted in again, anywhere, is skipped. The sidecars are read by position, key first and value second, so a sidecar written by hand needs no header row ([Sidecars and reports](sidecars.md)). An `Alt` left blank means what it means for a book's image: checked, and fine as it is. The picture keeps what it has, and the row isn't reported again, which is how a long description someone means to keep stops coming back.

**`image-alt-missing.csv`**, for `image-alt.csv`, has a row for each picture or object whose alt text is missing or says nothing. A picture is keyed on its image's content: `media/` and the first 16 characters of the image's SHA-256, with its extension. The run writes the image at that path in the folder, so the file the row names can be opened. A row covers every copy of the image, on every slide of every deck, and on the layouts and masters too. A logo or a flourish pasted onto 50 slides in 12 decks is one row, marked `[decorative]` once. Since the decision is every copy's, a picture's row names every copy in `Source`, including any whose own alt text was fine, and `CurrentAlt` gives what the copies have now: their alt text, `(none)`, or `(decorative)`. `Reason` says why the row is there: `missing (picture)`, `says nothing (a clip-art id)`, or `too long (227 characters)`. An object with no image of its own (a chart, a SmartArt graphic, a group, a shape) is keyed on `deck/slide-N/shape-M`, where `deck` is the deck's file name without `.pptx`, `N` is the id PowerPoint gave the slide, and `M` the shape's. Those ids last until the slide or the shape is deleted, so moving a slide doesn't break its rows. `deck/media/...` applies a picture's row to one deck's copies alone. The most particular row wins: a shape's own, then its image's in its deck, then its image's anywhere. Two decks whose names are one key (`Deck.pptx` and `Deck.PPTX`) stop the run, since their rows would be applied to both.

**`table-headers-new.csv`**, for `table-headers.csv`, has a row for each table with no header row. The row has the same columns as a book's table, and the table is keyed on its content the same way ([the header pre-pass](sidecars.md)). The `headers` value is the table census's guess, marked `TI` in `drafted-by`, or empty when the census can't say. A value states the table's headers whole, so each one sets both of PowerPoint's checkboxes, Header Row and First Column. `first-row` checks Header Row and clears First Column, and `none` clears both, which also changes how a table styled with First Column looks. A row left blank, or `manual`, leaves the table as it is. Like any row, it takes the table off the report. `split-at` and `caption-rows` aren't read for a deck, since PowerPoint can't split a table or caption it. Its header row is the first row, whatever that holds.

**`slide-titles-new.csv`**, for `slide-titles.csv`, has a row for each slide with no title, and for each slide whose title an earlier slide in its deck has (`pptx-duplicate-title`), keyed on `deck/slide-N`, with `Slide`, `Title`, `Source`, `Drafted by`, and `Reviewed` columns. A repeated title's row is drafted, marked `TI`: the title with its number among the slides that share it, `Market Demand (2)` for the second, and `Source` names the slide whose title it repeats. A title for a slide that has one takes the old one's place on the slide, where it's seen, so slides titled alike are told apart on the screen and in a screen reader's list of slides alike. A title given as it is keeps it.

**`reading-order-new.csv`**, for `reading-order.csv`, has a row for each slide whose shapes are read in another order than they're laid out (`pptx-reading-order`), keyed on `deck/slide-N`. `Order` is a draft, marked `TI`: the ids of the shapes a screen reader reads, the title first and then top to bottom and left to right, or as near to that as the slide can come without looking any different. A slide's shape tree is its reading order and its stacking order at once. A screen reader reads the shapes in the tree's order, and PowerPoint draws them in that order, each over the ones before it, so "changing the order of objects can affect how the slide looks when there are overlapping objects," as [Microsoft says of PowerPoint's own Reading Order pane](https://support.microsoft.com/powerpoint/make-slides-easier-to-read-by-using-the-reading-order-pane). Two shapes whose boxes overlap therefore keep their order, and `Note` says which pairs kept the draft from the layout's order. `Shapes` says what each id is, in the order the shapes are read now: the id, the shape's name, and its text or alt text. A slide where nothing can move without changing what's drawn over what gets no draft, and `Note` says so. Often that's a picture behind the text, read before the title: marked decorative, it isn't read at all, and the slide is in order.

An `Order` is ids separated by spaces or commas. Only the shapes it names move, each into a place one of them had in the tree, so a shape it leaves out stays where it was. A blank `Order` leaves the slide as it is, and, like any row, takes it off the report.

**`bare-links-new.csv`**, for `bare-links.csv`, has a row for each address a deck's link shows as its text (`pptx-link-bare-url`), in the columns a book's report has ([Bare links](bare-links.md)): `Source` names the slides, `Context` is the text before the link in its paragraph, and `Title` the ScreenTip it has now. A `Replacement` that's an address replaces the link's address and its text, any other `Replacement` its text alone, and a `Title` becomes its ScreenTip. A row left blank keeps the link as it is.

**`output-check.csv`** has the copies' findings, written once a `source` target has written them, with `Kind` `pptx`. A table that the sidecar says has no headers (`none`) isn't counted against a copy, nor is a slide whose shapes are in the order the reading-order sidecar gives, whatever order a person chose, nor a bare link the bare-links sidecar decided, bare or not.

A sidecar row whose key matches nothing in the decks is named in a note. A deck that changed since the row was written will have its new row in this run's report.

## The copy

A `source` target writes a copy of each deck to its folder, under the deck's own name, and the originals are never touched:

- **Alt text**: each decision goes into the picture's or object's description. For `[decorative]`, PowerPoint's decorative mark is added and the description removed. A shape that was marked decorative and is given alt text loses the mark.
- **Table headers**: each table gets the header row and first column the sidecar decides.
- **Slide titles**: a slide with no title gets its title above the slide, where a screen reader reads it and the slide doesn't show it, as PowerPoint's Add Hidden Slide Title does ([Microsoft](https://support.microsoft.com/en-us/powerpoint/title-a-slide)). An empty title placeholder takes the text and moves above the slide. Otherwise, a title placeholder is added first in the slide's shapes, so it's read first. A slide with a title gets the new one in its place: what the new title adds to the old, as ` (2)` does, goes after the old title's last run, in that run's formatting, and a new title that doesn't begin with the old one takes the place of all its text, in the formatting of its first run and paragraph.
- **Reading order**: the shapes an order names are put in its order, in the places they had in the slide's tree. A group moves with everything in it, as the Reading Order pane lists a group as one item, and a shape in `mc:AlternateContent` moves with its Fallback. An order isn't written if it would draw two overlapping shapes the other way round, or if it names a shape that isn't at the top of the slide's tree (one in a group moves with the group, by the group's id), an id two shapes share, or one id twice; the run says which order and why. Overlap is judged by the boxes the shapes are drawn in, a rotated shape's box turned with it, each widened on every side by four points, or by the reach of its outline when that's more (its width, or three times it for a line with an arrowhead), since outlines, arrowheads, and the smoothing of edges reach past a box. A shape whose box can't be known counts as overlapping everything, and a hidden shape or an empty placeholder, which draws nothing, as overlapping nothing. Text that runs further past its box, and a shadow or a glow, aren't counted. Measured with LibreOffice on real decks, every slide put in order was drawn pixel for pixel as it had been; with boxes widened by one point or two, a few weren't.
- **Bare links**: a link the bare-links sidecar decides gets its `Title` as its ScreenTip, and its `Replacement` as its text, and as its address too when the replacement is an address (in the slide's relationships, so every link on the slide to that address goes to the new one). A link whose text PowerPoint split over several runs is one link: the replacement goes in the first run, in its formatting, and the others go.
- **Equations**, with `math.repair_equations` (on by default), get the characters they mean, as a Word file's do ([Math](configuration.md#math)): PowerPoint's equations are the same Office math. On OpenStax's decks, 12 of the 73 equations change, each a bar written as a macron or an en dash over a letter (x̄ for the sample mean). `math-keep.csv` isn't read for decks yet; a deck whose repairs aren't wanted needs the setting off.
- **The language**, when the project declares one (`project.language`): it goes where PowerPoint declares a deck's language, in the default text style and the masters' text styles, which every run that names no language of its own inherits. It's written only into a deck with no default language, and a run that names a language keeps it.
- **The title in the file's properties**, when they have none, is the first slide's title (the sidecar's, if that slide has none of its own), since a PDF exported from the deck takes the properties' title as its own.
- **What PowerPoint can't read as written** (`pptx-malformed`), where putting it right loses nothing: an empty shape is taken out, and a prefix used without its namespace declared is declared on the part's root. A deck Pandoc wrote with each, which PowerPoint wouldn't open or repaired by removing content, opened in PowerPoint with only that repair made. A part with something else wrong is left as it is, and its copy's check names it.

The language and the title come from the project and the deck, and the repairs from the file itself, not from a sidecar. Everything else in a copy is what a person decided.

Each part of the deck is copied byte for byte unless a decision changes it, and the XML of the parts that change is edited as text, never parsed and written again. A shape in `mc:AlternateContent` is edited in both its Choice and its Fallback, which carry the same id. A decision about a shape whose id its slide repeats, which PowerPoint repairs when it opens the file, is skipped, and the run says how many were.

On the OpenStax decks, with every row of `image-alt-missing.csv` decided (155 described and 10 marked decorative), the copies' check finds nothing. Their changed parts are well-formed XML, the rest is byte for byte, and LibreOffice opens them and exports them to PDF.

A target's `archive` setting packs its folder into one file once the folder is written: `zip` or `tar.gz`, beside the folder and named after it (`remediated.zip`), holding the folder. Nothing is archived in a run where a deck couldn't be read or a copy couldn't be read back, so an archive is never part of the set. Later runs don't read the archive as a source to unpack:

```yaml
targets:
  remediated:
    format: source
    archive: zip
```

## What a person still does

Some findings ask for work in PowerPoint itself, and the copy doesn't change them:

- **Reading order on a slide where nothing can move** without changing how it looks, which the report's row says. A picture behind the text that carries no meaning can be marked decorative, which takes it out of what's read, or made the slide's background in PowerPoint, where it isn't a shape at all. Otherwise it's the author's to lay out again, or to put in order with PowerPoint's Reading Order pane and accept the change in how it looks.
- **Drawn diagrams and tab tables** are the author's to rebuild: a group with alt text or a picture for the one, a table for the other.
- **Media captions** can't be confirmed from the file yet, so every video and audio clip is reported.
- **An old Equation Editor object** (`Equation.3`) is a picture of a formula to a screen reader. It needs alt text now, and retyping in PowerPoint's own equation editor later.

## Tools

`audit.py` reads decks too, and writes their findings with everything else it's given, using the default length limit and placeholders (`python3 $T/bin/audit.py *.pptx -o audit`). `util/remediate.py` writes a deck's copy outside a run, from the sidecars named:

```bash
python3 $T/util/remediate.py *.pptx --alt image-alt.csv --table-headers table-headers.csv \
    --slide-titles slide-titles.csv --reading-order reading-order.csv \
    --links bare-links.csv --repair-equations --language en-US --out remediated
```
