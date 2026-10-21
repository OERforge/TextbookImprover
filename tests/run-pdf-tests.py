#!/usr/bin/env python3
"""
run-pdf-tests.py -- check the pdf target against a small Markdown book.

    python3 tests/run-pdf-tests.py           # run every check
    python3 tests/run-pdf-tests.py --keep    # leave the output in place

Needs Pandoc 3.9 or later, LuaLaTeX with LaTeX's tagging code (TeX Live
2026 or later; see docs/installation.md), and pypdf and pikepdf to read
the result. Without LuaLaTeX, pypdf, or pikepdf it says so and skips;
veraPDF, when found through VERAPDF or on the path, is run by the
output check and its findings are checked too.

WHAT IS LOAD-BEARING HERE

Each thing pdf-target.lua, footnote-code.lua, and build-pdf.py add to
what Pandoc's LaTeX writer does has a check that fails without it: a
declared header column tagged as row headers, a decorative image an
artifact rather than a figure, every link's /Contents its visible text
with any description after it and nothing left over for a link LaTeX
makes on its own, the division commands written once each from the
roles, the page the metadata file made given no heading, every
formula's MathML both as structure and as an attached file, a code
block in a footnote set in its note, a passage in another language
tagged with it, a heading inside a list, a quotation, a table's cell, a
figure, or a footnote tagged where it stands, and the default page
(bin/pdf-layout.yaml), which a metadata file changes a field at a time,
its rag reaching footnotes and captions. The book is small
because a LaTeX run is slow; it holds one of each thing, and two of the
things that come in kinds.

Copyright 2026 Robert Szarka

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

import argparse
import concurrent.futures
import contextlib
import csv
import io
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin")

try:
    import pypdf
except ImportError:
    pypdf = None

sys.path.insert(0, os.path.join(ROOT, "lib"))
import highlighting  # noqa: E402
import outputcheck  # noqa: E402
import pdfcheck  # noqa: E402
import pdfparagraphs  # noqa: E402
sys.path.insert(0, HERE)
import parallel  # noqa: E402
import pdftext  # noqa: E402

# The book class's own page, where the PDF target's default would have
# its own (bin/pdf-layout.yaml): 10pt type, justified, in the class's
# margins, which the checks of the book and the notes book measure lines
# 345 points long in. The footer book and the default book, the book
# again, have the default page, and the sized book the default as a
# metadata file changes it.
CLASS_PAGE = "fontsize: 10pt\ngeometry: []\nlinestretch: 1\nragged-right: false\n"

FRONT = r"""---
title: The Test Book
subtitle: A book for checking the PDF target
""" + CLASS_PAGE + r"""---

\frontmatter

# Preface

This preface points to [the first section](one.html#first) and cites
[https://doi.org/10/b8xx35](https://doi.org/10/b8xx35 "Crandall 2019 via doi.org"),
then [a plain link](https://example.org/).[^n]

[^n]: A note, whose mark is a link LaTeX makes on its own.

# Acknowledgements

Two headings, so neither is promoted to the page's title: the page is
titled by its metadata, which is the book's title, as a preamble is.
"""

ONE = r"""# One

## First {#first}

Greek and symbols as text, and not math, which the math repair would make
of a Greek letter alone: the letters αβγ as one word, and ≤ and ≈ named on
their own. And 漢, which no Latin Modern font has, and ⓐ, a circled
letter, which of the fonts the build falls back to only New Computer
Modern's math font has.

Inline math $x^2 + y^2 = z^2$, and a display:

$$\frac{a}{b}$$

And an eqnarray*, which the writer would wrap in display math:

$$\begin{eqnarray*}
a &=& b + c
\end{eqnarray*}$$

And a poor man's bold, as a LaTeX book writes one: $\pmb{\hat{p}_1 - b}$.

And amssymb's squares, which unicode-math has no names for: $\square \blacksquare$.

::: matrix
|      | Left | Right |
|------|------|-------|
| Up   | 1    | 3     |
| Down | 2    | 4     |
:::

| Year | Output |
|------|--------|
| 2020 | 5      |
| 2021 | $\begin{matrix} 5 & + & 1 \end{matrix}$ |

![A small red square](assets/red.png){width=800px}

A rule between paragraphs: ![](assets/rule.png){.decorative width=900px height=2px}

![](assets/blank.png)

![IMG_2041](assets/photo.png)

| Year | Price |
|------|-------|
| 2020 | 10    |
| 2021 | 12    |

Table: Price by year, $\begin{matrix} p & q \end{matrix}$

+----------------------+
| Both columns         |
+-----------+----------+
| Left      | Right    |
+===========+==========+
| 1         | 2        |
+-----------+----------+

+-------------------+-------------------+
| Racket            | Pyret             |
+===================+===================+
| > (define x 1)    | x = 1             |
+-------------------+-------------------+

+-------+-------+
| Group | Value |
+=======+=======+
| Alpha | 1     |
+       +-------+
|       | 2     |
+-------+-------+
| Beta  | 3     |
+-------+-------+

| After | Spans |
|-------|-------|
| a     | b     |
| c     | d     |
| e     | f     |

| $q_d$ | Revenue, $p \cdot q_d$ |
|-------|------------------------|
| 10    | 10                     |

| Year | Cost |
|------|------|
| 2020 | 3    |

Table: Cost by year {.unnumbered}

Elasticity[^term]
:   How much quantity responds to price.

[^term]: A term's footnote, which LaTeX's tagging stopped on.

Highlighted code, whose spaces were lost beside a colored word:

```python
def demand(p):
    return 12 - 2 * p > 0
```

And code in a footnote, which LaTeX reads as the footnote's text.[^code]

[^code]: Highlighted:

    ```python
    def supply(p):
        return 2 * p  # 100%
    ```

    And not, which is LaTeX's own verbatim:

    ```
    q   = 10
    ```

#### Deep

##### Run-in one

###### Run-in two

## After the run-in headings

A heading below a subsection is run in to the text after it, and two of
them followed by a section had left LaTeX's paragraph tagging one short.

Some [tea and biscuits]{lang=en-GB} as in Britain, and a
[link in it](https://example.org/tea){lang=en-GB}.

::: {lang=en-GB}
A paragraph in British English, about the lift and the flat.

### Holiday

- A list in it, of the post and the queue.

::: {lang=en-AU}
### Mate

A passage inside it in a language of its own.
:::

And a paragraph after the heading, and a table with row headers.

::: matrix
|        | Shade |
|--------|-------|
| Plain  | grey  |
:::
:::

Back in the book's own language.

An editor's marks with nothing in them but the space typed after them
set nothing: water is H~2~O, S<sub> </sub>= 0, S~\ ~= 0, and *\ *so on.

| z   | 0.00    | 0.01   | 0.02   | 0.03   |
|-----|---------|--------|--------|--------|
| 3.0 | 0.00135 | &nbsp; | &nbsp; | &nbsp; |

Table: Values whose row ends in empty cells, each holding a no-break space

## A section whose title runs longer than the line a running head has beside the page number, as a topic's can

Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is.

Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is.

Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is.

Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is.

Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is.

Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is.

Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is.

Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is.

Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is.

Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is.

Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is.

Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is. Words that fill the pages under a long title, so that its running head is set on a page of its own, beside the page's number, where the book class would set it in one line however long it is.
"""

APPENDIX = r"""\appendix

# Tables of Values

Figures and a table whose captions carry their own labels, as a book
whose captions number themselves has them, the second figure's too long
for one line.

![Figure 7.3 A red square the book labels itself](assets/red.png)

![Figure 7.5 A red square again, whose caption the book labels itself, long enough to run past the width of its line and be set as a paragraph of its own](assets/red.png)

And a figure it doesn't number, as OpenStax doesn't a chapter's opening picture.

![A red square the book leaves unnumbered](assets/red.png){.unnumbered}

| Year | Rate |
|------|------|
| 2020 | 4    |

Table: Table 7.4 Rates the book labels itself

And a figure set in a table's cell beside words, its caption carrying
its own label, as a LibreTexts page sets two figures side by side.

+--------------------------------------------------------+--------------------------------------------------------+
| ![Figure 7.6 A red square in a cell](assets/red.png)   | Words beside the figure, in the table's other cell.    |
+--------------------------------------------------------+--------------------------------------------------------+

And two pictures side by side in one figure, each a figure of its own in
a row, as a LibreTexts page sets them.

<figure><div class="row"><figure><img src="assets/red.png" alt="A left red square"></figure><figure><img src="assets/photo.png" alt="A right green square"></figure></div><figcaption>Figure 7.7 Two squares side by side</figcaption></figure>

::: box
A passage set off in a box, as a LibreTexts page's Example is and a
LaTeX book's framed passage.
:::

And text after the box.

## Fill in the ________

Two questions that end in a fill-in blank, as Sociology's quiz asks
them, the first too long for what's left of its line, which TeX can't
break:

The Rating of Perceived Exertion (RPE) is an example of ________________

Core nations are also known as __________________

And underscores in code, which aren't a blank: `a____b`. And in a bare
address, <https://example.org/fill____in>, and a picture's description:
![A red square over a line to write on, ________](assets/red.png).
"""

# An untagged book, built to no PDF/UA standard, with figures and no
# table, so no caption package: its figures are set by LaTeX's classes.
# And boxes that open a list's item, a quotation, and a definition, whose
# label LaTeX sets untagged from \everypar, which a box's rule had taken
# over.
UNTAGGED_PAGE = r"""# Figures

Three figures whose captions carry their own labels, the second too
long for one line and the third labeled by a word the book's settings
name, and one whose caption doesn't. Two captions too long for a line
hold a footnote, as this paragraph does.[^u1]

![Figure 7.3 A red square the book labels itself](assets/red.png)

![A red square with no label of its own](assets/red.png)

![Figure 7.4 A caption the book labels itself, long enough to run past the width of its line and be set as a paragraph of its own.[^u2]](assets/red.png)

![Exhibit 2.1 A red square labeled as an exhibit](assets/red.png)

![A red square whose caption, long enough to run past the width of its line and be set as a paragraph of its own, holds a note.[^u3]](assets/red.png)

A band of noise four times as wide in pixels as it's shown, in a line of
text, which images.downsample scales to twice: ![A wide band of
noise](assets/wide.png){width=100px}.

A formula too wide for its line, which LaTeX can't break:

$$y_{0}+y_{1}+y_{2}+y_{3}+y_{4}+y_{5}+y_{6}+y_{7}+y_{8}+y_{9}+y_{10}+y_{11}+y_{12}+y_{13}+y_{14}+y_{15}+y_{16}+y_{17}+y_{18}+y_{19}+y_{20}+y_{21}+y_{22}+y_{23}+y_{24}+y_{25}+y_{26}+y_{27}+y_{28}+y_{29}$$

Boxes that open a list's items, a quotation, and a definition, the
second item's holding a figure alone:

1.  ::: box
    Boxed words at the first item's start.
    :::

    More of the first item.

2.  ::: box
    ![A black square alone in a box](assets/red.png){height=0.5in}
    :::

    The second item's words after its box.

> ::: box
> Boxed words at a quotation's start.
> :::

A term
:   ::: box
    Boxed words at a definition's start.
    :::

[^u1]: The first note, in the text.
[^u2]: The second note, in a labeled caption.
[^u3]: The third note, in a caption.
"""

# Footnotes where LaTeX numbered them wrong, in a book built tagged and
# untagged, its notes numbered through its two chapters: in a figure's
# caption, whose mark took a number each time LaTeX set the caption, and
# in a table inside a table's cell, which was a minipage's; with a table
# with a header column, and the table in the cell with a head, whose
# \tagpdfsetup stopped LaTeX untagged.
NOTES_CAPTIONS = r"""# Captions

Text with a note.[^a]

![A figure whose caption has a note.[^b]](assets/red.png)

![A figure whose caption, long enough to run past the width of its line and be set as a paragraph of its own, has a note.[^c]](assets/red.png)

[^a]: Note a, in the text.
[^b]: Note b, in a caption.
[^c]: Note c, in a long caption.
"""

# The longer cell of each of two tables NOTES_CELLS has whose cells, side
# by side, are longer than a line.
WIDE_CELLS = ("The temperature warmed up twelve degrees from seven degrees below zero by noon today.",
              "The snow fell for eleven days without stopping, and the rivers froze from bank to bank.")

NOTES_CELLS = r"""# Cells

::: matrix
|      | Left | Right |
|------|------|-------|
| Up   | 1    | 3     |
| Down | 2    | 4     |
:::

+--------------------------+--------------------------+
| Outer                    | Right                    |
+==========================+==========================+
| Above it, a note.[^d]    | A plain cell.            |
+--------------------------+--------------------------+
| +-------+-------+        | Beside it, a note.[^g]   |
| | In    | Out   |        |                          |
| +=======+=======+        |                          |
| | x[^e] | y[^f] |        |                          |
| +-------+-------+        |                          |
+--------------------------+--------------------------+

After the tables, a note.[^h]

Two layout tables, the second holding a data table:

<table id="solve" role="presentation"><tr><td>Subtract 3 from each side.</td><td>x = 4</td></tr><tr><td>Divide each side by 2.</td><td>x = 2</td></tr></table>

<table role="presentation"><tr><td>Read the price off the table.</td><td><table><tr><th>Year</th><th>Price</th></tr><tr><td>2020</td><td>10</td></tr></table></td></tr></table>

And one with a caption:

<table id="steps" role="presentation"><caption>Steps to solve</caption><tr><td>Add 1 to each side.</td><td>x = 5</td></tr><tr><td>Halve each side.</td><td>x = 2.5</td></tr></table>

And one whose first row is in its head, as Pandoc's Word reader puts a row Word repeats as a header:

<table role="presentation"><thead><tr><th>Diploma in game design</th><th>Sept. 2015 to Apr. 2018</th></tr></thead><tbody><tr><td>Certificate in illustration</td><td>Sept. 2014 to Apr. 2015</td></tr></tbody></table>

As [the first steps](#solve) and [the second](#steps) show.

Two data tables with an id and no caption, the second of a class the book doesn't number:

<table id="rates"><thead><tr><th>Rate</th><th>Term</th></tr></thead><tbody><tr><td>Four percent</td><td>Ten years</td></tr></tbody></table>

<table id="fees" class="unnumbered"><thead><tr><th>Fee</th><th>When</th></tr></thead><tbody><tr><td>Five dollars</td><td>Monthly</td></tr></tbody></table>

As [the rates](#rates) and [the fees](#fees) show.

And two whose cells, side by side, are longer than a line:

<table role="presentation"><tr><td>Write a phrase for the temperature.</td><td>The temperature warmed up twelve degrees from seven degrees below zero by noon today.</td></tr></table>

<table><thead><tr><th>Season</th><th>What the weather did</th></tr></thead><tbody><tr><td>Winter</td><td>The snow fell for eleven days without stopping, and the rivers froze from bank to bank.</td></tr></tbody></table>

And four whose longest words, side by side, are wider than a line, or
wider than the columns their widths give them: a column of reactions,
which TeX breaks at their relations and operators; two words too long
for a line together; a word too long for an equal share of a table whose
cell of two paragraphs gives it equal widths; and a table of numbers
too wide for a line in any type:

<table><thead><tr><th>Mediator</th><th>Reagent</th><th>Representative reaction</th></tr></thead><tbody><tr><td>Silver</td><td><script type="math/tex">\mathrm{Ag}^{+}\rightleftharpoons\mathrm{Ag}^{2+}+e^{-}</script></td><td><script type="math/tex">\mathrm{H_2C_2O_4}(aq)+2\mathrm{Ag}^{2+}(aq)+2\mathrm{H_2O}(l)\rightleftharpoons 2\mathrm{CO_2}(g)+2\mathrm{Ag}^{+}(aq)+2\mathrm{H_3O}^{+}(aq)</script></td></tr></tbody></table>

<table><thead><tr><th>Long word</th><th>Longer word</th></tr></thead><tbody><tr><td>Supercalifragilisticexpialidocious</td><td>Hippopotomonstrosesquippedaliophobia</td></tr></tbody></table>

<table><thead><tr><th>Organ</th><th>Disease</th><th>Notes</th></tr></thead><tbody><tr><td>Lung</td><td>Pneumonoultramicroscopicsilicovolcanoconiosis</td><td><p>From dust.</p><p>Rare.</p></td></tr></tbody></table>

<table><thead><tr><th>Degrees</th><th>1</th><th>2</th><th>3</th><th>4</th><th>5</th><th>6</th><th>7</th><th>8</th><th>9</th><th>10</th><th>11</th></tr></thead><tbody><tr><td>Critical</td><td>161.45</td><td>199.50</td><td>215.71</td><td>224.58</td><td>230.16</td><td>233.99</td><td>236.77</td><td>238.88</td><td>240.54</td><td>241.88</td><td>242.98</td></tr></tbody></table>

[^d]: Note d, above the inner table.
[^e]: Note e, in the inner table.
[^f]: Note f, in the inner table too.
[^g]: Note g, beside the inner table.
[^h]: Note h, after the tables.
"""

# Headings where the writer's sectioning command opened a section LaTeX's
# tagging couldn't close, so that every section after a list's was tagged
# inside the list: in a list's item (OpenStax puts a note with a title in
# one), a numbered item, a definition, a quotation, a table's cell, a
# figure, and a footnote; with a link to one, and a section after them.
# The headings are a level below a section's, so none skips a level,
# which heading_levels would lift.
NOTES_HEADINGS = r"""# Headings

## In a list, a quotation, a table, a figure, and a note

- An item before it.

  ### Heading in an item {#in-an-item}

  A note's words, as OpenStax puts a note with a title in a list's item.

- The item after it.

1. A numbered item.

   ### Heading in a numbered item

   Its words.

Term
:   A definition.

    ### Heading in a definition

    Its words.

> A quotation.
>
> ### Heading in a quotation
>
> Its words.

+-----------------------------+-------------+
| Kind                        | Words       |
+=============================+=============+
| ### Heading in a cell       | Its words.  |
|                             |             |
| More of the cell.           |             |
+-----------------------------+-------------+

<figure><h3>Heading in a figure</h3><p>A figure's words.</p><figcaption>A figure with a heading.</figcaption></figure>

Text with a note.[^i] As [the heading in the item](#in-an-item) says.

[^i]: Note i, with a heading.

    ### Heading in a note

    More of note i.

## A section after them

Its words.

Two fill-in blanks joined to a number too long for any line by a space
that doesn't break: the first doesn't reach the line's end, so it's left
as it is, and the second reaches past it with too little of it before the
margin to be drawn whole, so it's drawn no shorter than three
underscores.

________\ 31415926535897932384626433832795028841971693993751058209749445923078164062862089986280

2718281828459045235360287471352662497757247093699959574966967627724\ ____

And blanks underlined, struck out, and highlighted, whose line or
highlight lua-ul draws before a blank could be drawn shorter, left as
they are: [________________]{.underline}, ~~________________~~, and
[________________]{.mark}.

## Sixty-four places of π, 3141592653589793238462643383279502884197169399375105820974944592

A heading too long for a line of the contents, which is narrower than
the text, and a caption too long for a line of the list of figures:

![Sixty-four places of π, 3141592653589793238462643383279502884197169399375105820974944592](assets/red.png)
"""

PROJECT = """project:
  identifier: org.example.pdf
  title: The Test Book
  language: en
  contents:
    - page: front
      role: front
    - generate: toc
    - one
    - page: appendix
      role: appendix
"""

CONVERSION = """targets:
  html:
    format: html
  pdf:
    format: pdf
    pdf:
      metadata: front.md
"""


def png(path, rgb):
    """A 4x4 PNG of one color, written without an imaging library."""
    raw = b"".join(b"\x00" + bytes(rgb) * 4 for _ in range(4))

    def chunk(kind, data):
        body = kind + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xffffffff))
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n"
                 + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0))
                 + chunk(b"IDAT", zlib.compress(raw))
                 + chunk(b"IEND", b""))


def noise_png(path, width, height):
    """A PNG of noise, which scaling makes smaller, written without an
    imaging library."""
    import random
    rows = random.Random(7)
    raw = b"".join(b"\x00" + rows.randbytes(width * 3) for _ in range(height))

    def chunk(kind, data):
        body = kind + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xffffffff))
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n"
                 + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                 + chunk(b"IDAT", zlib.compress(raw))
                 + chunk(b"IEND", b""))


def image_pixels(path):
    """The width and height in pixels of each image a PDF's pages draw."""
    sizes = []
    for page in pypdf.PdfReader(path).pages:
        resources = resolve(page.get("/Resources")) or {}
        for image in (resolve(resources.get("/XObject")) or {}).values():
            image = image.get_object()
            if image.get("/Subtype") == "/Image":
                sizes.append((int(image["/Width"]), int(image["/Height"])))
    return sizes


def write_book(work):
    os.makedirs(os.path.join(work, "assets"))
    for name, text in (("front.md", FRONT), ("one.md", ONE),
                       ("appendix.md", APPENDIX), ("project.yaml", PROJECT),
                       ("conversion.yaml", CONVERSION)):
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    png(os.path.join(work, "assets", "red.png"), (200, 0, 0))
    png(os.path.join(work, "assets", "rule.png"), (0, 0, 0))
    png(os.path.join(work, "assets", "blank.png"), (255, 255, 255))
    png(os.path.join(work, "assets", "photo.png"), (0, 120, 0))


# --------------------------------------------------------------------------
# reading the PDF
# --------------------------------------------------------------------------

def resolve(obj):
    return obj.get_object() if hasattr(obj, "get_object") else obj


def elements(node, found=None):
    """Every structure element under node, in order."""
    found = [] if found is None else found
    node = resolve(node)
    if not isinstance(node, dict):
        return found
    if "/S" in node:
        found.append(node)
    kids = node.get("/K")
    if kids is None:
        return found
    kids = resolve(kids)
    for kid in (kids if isinstance(kids, list) else [kids]):
        if not isinstance(kid, int):
            elements(kid, found)
    return found


def kind(element):
    return str(element.get("/S", ""))


def classes(element):
    value = resolve(element.get("/C")) if "/C" in element else None
    if value is None:
        return []
    return [str(v) for v in value] if isinstance(value, list) else [str(value)]


UA1_PAGE = r"""# Old Standard

## A section

A [described link](https://example.org/ "Example, a test site") and a
formula, $a^2 + b^2 = c^2$, with a note.[^1] Its [flat]{lang=en-GB} too.

[^1]: The note.
"""


def build_ua1(work):
    """A one-chapter book claiming PDF/UA-1, its math as Office writes it,
    which is the default: (the PDF's path, what the run said, the output
    check's rows)."""
    os.makedirs(work)
    with open(os.path.join(work, "old.md"), "w", encoding="utf-8") as fh:
        fh.write(UA1_PAGE)
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  title: Old Standard\n  identifier: org.example.ua1\n"
                 "  language: en-US\n")
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  pdf:\n    format: pdf\n    pdf:\n      standard: [ua-1]\n")
    converted = subprocess.run(["python3", os.path.join(BIN, "convert.py")], cwd=work,
                               capture_output=True, text=True, stdin=subprocess.DEVNULL)
    report = os.path.join(work, "output-check.csv")
    rows = []
    if os.path.exists(report):
        with open(report, encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
    return os.path.join(work, "pdf", "org.example.ua1.pdf"), converted.stdout + converted.stderr, rows


def build_untagged(work):
    """A book built to no PDF/UA standard, UNTAGGED_PAGE: (the PDF's path,
    what the run said)."""
    os.makedirs(os.path.join(work, "assets"))
    png(os.path.join(work, "assets", "red.png"), (200, 0, 0))
    noise_png(os.path.join(work, "assets", "wide.png"), 400, 200)
    with open(os.path.join(work, "figures.md"), "w", encoding="utf-8") as fh:
        fh.write(UNTAGGED_PAGE)
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  title: No Standard\n  identifier: org.example.untagged\n"
                 "  language: en-US\n")
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("defaults:\n  captions:\n    figure_prefixes: [Figure, Exhibit]\n"
                 "  images:\n    downsample: 2\n"
                 "targets:\n  pdf:\n    format: pdf\n    pdf:\n      standard: []\n")
    converted = subprocess.run(["python3", os.path.join(BIN, "convert.py")], cwd=work,
                               capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return (os.path.join(work, "pdf", "org.example.untagged.pdf"),
            converted.stdout + converted.stderr)


def languages(path):
    """(tag, /Lang, its text and its children's, the /Lang of the element
    holding it) for each structure element that declares a language, and
    for each whose text holds a phrase of the book's own language."""
    pikepdf = pdftext.pikepdf
    texts = pdftext.marked_text(path)
    out = []
    with pikepdf.open(path) as pdf:
        pages = {page.objgen: n for n, page in enumerate(pdf.pages)}

        def kids(element):
            found = element.get("/K")
            return list(found) if isinstance(found, pikepdf.Array) else [found]

        def whole(element):
            text = pdftext.own_text(element, texts, pages)
            for kid in kids(element):
                if isinstance(kid, pikepdf.Dictionary) and "/S" in kid:
                    text += whole(kid)
            return text

        def walk(element, above):
            if not isinstance(element, pikepdf.Dictionary) or "/S" not in element:
                return
            lang = str(element.Lang) if "/Lang" in element else None
            text = whole(element)
            if lang or "own language" in text:
                out.append((str(element.S), lang, " ".join(text.split()), above))
            for kid in kids(element):
                walk(kid, lang or above)

        for kid in kids(pdf.Root.StructTreeRoot):
            walk(kid, None)
    return out


def build_notes(work):
    """NOTES_CAPTIONS, NOTES_CELLS, and NOTES_HEADINGS, built tagged, to
    PDF/UA-2, with a list of figures, and untagged: (the tagged PDF's path,
    the untagged one's, what the run said, the tagged one's LaTeX)."""
    os.makedirs(os.path.join(work, "assets"))
    png(os.path.join(work, "assets", "red.png"), (200, 0, 0))
    for name, text in (("captions.md", NOTES_CAPTIONS), ("cells.md", NOTES_CELLS),
                       ("headings.md", NOTES_HEADINGS),
                       ("meta.md", "---\nlof: true\n" + CLASS_PAGE + "---\n")):
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  title: Notes\n  identifier: org.example.notes\n"
                 "  language: en-US\n  contents:\n    - captions\n    - cells\n    - headings\n")
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  pdf:\n    format: pdf\n    pdf:\n      metadata: meta.md\n"
                 "  plain:\n    format: pdf\n    pdf:\n      standard: []\n")
    converted = subprocess.run(["python3", os.path.join(BIN, "convert.py")], cwd=work,
                               capture_output=True, text=True, stdin=subprocess.DEVNULL)
    run(["python3", os.path.join(BIN, "build-pdf.py"), "--latex-only", "--target", "pdf"],
        work)
    tex = os.path.join(work, "pdf", "book.tex")
    source = ""
    if os.path.exists(tex):
        with open(tex, encoding="utf-8") as fh:
            source = fh.read()
    return (os.path.join(work, "pdf", "org.example.notes.pdf"),
            os.path.join(work, "plain", "org.example.notes.pdf"),
            converted.stdout + converted.stderr, source)


# Words long enough that a justified line, or ragged2e's, would break one,
# and a footnote's and a caption's of their own, each ending in a word of
# its own, to find their lines by.
FOOTER_WORDS = ("Each sentence of this chapter runs on about internationalization, "
                "characteristically interdisciplinary counterrevolutionaries, and "
                "institutionalization, so that its lines are long. ")
FOOTER_NOTE = ("Each sentence of this note runs on about decentralization, "
               "compartmentalization, and electroencephalography, so that its "
               "lines are long. ")
FOOTER_CAPTION = ("Each sentence of this caption runs on about photosynthesis, "
                  "chlorofluorocarbons, and thermoregulation, so that its lines "
                  "are long. ")
FOOTER_ONE = ("# One\n\nThe first chapter opens with a note.[^1]\n\n"
              "[^1]: The note. " + FOOTER_NOTE * 3 + "Thereafter.\n\n"
              + "".join(FOOTER_WORDS * 4 + "\n\n" for _ in range(14)))
FOOTER_TWO = "# Two\n\nThe second chapter.\n"


# Two lines of a paragraph, and of a caption, with a break between them.
FOOTER_VERSE = "\nA line of a verse,\\\nand its next line, one paragraph.\n"
FOOTER_BREAK = "\\\nAnd a line of its own."


def build_footer(work):
    """A book of two chapters with a footer, a link and a picture in it,
    on the PDF target's default page (bin/pdf-layout.yaml), which no
    metadata file changes, a line break and a figure with a long caption
    in its second chapter: the PDF's path."""
    os.makedirs(work)
    for name, text in (("one.md", FOOTER_ONE),
                       ("two.md", FOOTER_TWO + FOOTER_VERSE + "\n![" + FOOTER_CAPTION * 3
                        + "Henceforth." + FOOTER_BREAK + "](cc.png)\n")):
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  title: Footed\n  identifier: org.example.footer\n"
                 "  language: en-US\n  contents:\n    - one\n    - two\n")
    png(os.path.join(work, "cc.png"), (0, 0, 0))
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write('defaults:\n  footer: "Read *this book* free at '
                 '[example.net](https://example.net). ![CC BY](cc.png)"\n'
                 "targets:\n  pdf:\n    format: pdf\n")
    subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick"], cwd=work,
                   capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return os.path.join(work, "pdf", "org.example.footer.pdf")


# The default page changed a field at a time: a type size the book class
# hasn't, which KOMA-Script's scrextend sets, and justified text, the
# default's paper, margins, and line spacing kept; one-sided, so a page's
# paragraphs aren't spread to fill it. The second chapter is on page
# 1,000 or after, for a page number of four digits in the contents: its
# section's, since the class sets a chapter's in a box that gives way,
# which LaTeX doesn't report as too wide.
SIZED_LAYOUT = "fontsize: 13.5pt\nragged-right: false\nclassoption: [oneside]\n"
THOUSANDTH = "```{=latex}\n\\setcounter{page}{1000}\n```\n\n"
SIZED_SECTION = "\n## Its section\n\nThe section's words.\n"
# A box that opens with a heading, as a box's legend does, too tall for
# what's left of its page, 60 points, room for its rule and its heading:
# on a one-sided page, which can end anywhere, a heading's place to break
# a page (a penalty the class gives it) had left the rule above the box at
# the page's foot. A figure alone after the legend, which begins no
# paragraph, and a heading after the box, which had lost its space above,
# where one after a box of a paragraph alone keeps it.
SIZED_BOX = ("".join("\n" + FOOTER_WORDS * 4 + "\n" for _ in range(2))
             + "\n```{=latex}\n\\par\\vspace{\\dimexpr\\pagegoal-\\pagetotal-60pt\\relax}\n```\n"
             "\n::: {#legend .box}\n## The box's legend\n\n"
             "![A tall black square in a box](cc.png){height=4in}\n:::\n"
             "\n## After the figure's box\n\nThe words after it.\n"
             "\n::: box\nA paragraph alone in a box.\n:::\n"
             "\n## After the paragraph's box\n\nThe words after that.\n")
# A list after a paragraph, at that size, its items spaced and indented as
# at the class's own: a loose list, its items paragraphs, which parskip
# sets as far apart as the paragraphs around them.
SIZED_LIST = ("\nThe paragraph before a list.\n\n- The list's first item.\n\n"
              "- The list's second item.\n\nThe paragraph after the list.\n")


def build_sized(work):
    """FOOTER_ONE and FOOTER_TWO on the default page as SIZED_LAYOUT's
    metadata file changes it: (the PDF's path, what the run said)."""
    os.makedirs(work)
    for name, text in (("one.md", FOOTER_ONE),
                       ("two.md", THOUSANDTH + FOOTER_TWO + SIZED_LIST + SIZED_SECTION
                        + SIZED_BOX),
                       ("sized.yaml", SIZED_LAYOUT)):
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  title: Sized\n  identifier: org.example.sized\n"
                 "  language: en-US\n  contents:\n    - one\n    - two\n")
    png(os.path.join(work, "cc.png"), (0, 0, 0))
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  pdf:\n    format: pdf\n    pdf:\n      metadata: sized.yaml\n")
    converted = subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick"],
                               cwd=work, capture_output=True, text=True,
                               stdin=subprocess.DEVNULL)
    return os.path.join(work, "pdf", "org.example.sized.pdf"), converted.stdout + converted.stderr


# A footer from a file of its own, with a heading, on pages in
# fancyhdr's styles, its plain style made from its fancy one: selecting
# plain, as a chapter's first page does, selects fancy as well, and each
# wraps the foot (lib/pagefooter.py). fancyhdr is twoside and the book
# isn't, so its odd foot, which the class sets on every page, gives its
# even one on an even page. And a type size and a paper given as class
# options, in the class's own margins, which the book class had set at
# the default page's 12pt and Letter, taking its options in the order it
# declares them; the size one the class hasn't, which it ignores, so it's
# the book's fontsize, which scrextend sets.
FANCY_FOOTER = "## License\n\nShared under [the license](license.md).\n"
FANCY_LAYOUT = ("classoption: [oneside, 13.5pt, a4paper]\ngeometry: []\n"
                "header-includes:\n  - |\n    ```{=latex}\n"
                "    \\usepackage[twoside]{fancyhdr}\n"
                "    \\pagestyle{fancy}\n    \\fancyhf{}\n    \\fancyfoot[LE,RO]{\\thepage}\n"
                "    \\renewcommand\\headrulewidth{0pt}\n"
                "    \\fancypagestyle{plain}[fancy]{}\n    ```\n")


def build_fancy(work):
    """FOOTER_ONE and FOOTER_TWO with FANCY_FOOTER's footer, from a file,
    on FANCY_LAYOUT's pages: the PDF's path."""
    os.makedirs(work)
    for name, text in (("one.md", FOOTER_ONE), ("two.md", FOOTER_TWO),
                       ("footer.md", FANCY_FOOTER), ("fancy.yaml", FANCY_LAYOUT)):
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  title: Fancy\n  identifier: org.example.fancy\n"
                 "  language: en-US\n  contents:\n    - one\n    - two\n")
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("defaults:\n  footer: footer.md\n"
                 "targets:\n  pdf:\n    format: pdf\n    pdf:\n      metadata: fancy.yaml\n")
    subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick"], cwd=work,
                   capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return os.path.join(work, "pdf", "org.example.fancy.pdf")



# A book written for a Pandoc PDF build, its metadata file loading the
# packages for its own margins and line spacing, as Pandoc's own page
# left a book to: the default page's margins and line spacing, which load
# geometry and setspace first, had stopped LaTeX ("Option clash for
# package geometry"), and undone a spacing the file set. And no contents
# page, as such a book may have none: Pandoc's template sets LaTeX's
# tocdepth, which the bookmarks follow, only where it writes the contents,
# so a page's subsections had bookmarks too.
PREAMBLE_META = ("---\ntoc: false\nheader-includes:\n  - |\n    ```{=latex}\n"
                 "    \\usepackage[margin=1.5in]{geometry}\n"
                 "    \\usepackage[doublespacing]{setspace}\n    ```\n---\n")
PREAMBLE_TWO = ("# Two\n\nThe second chapter.\n\n## Its section\n\nThe section.\n\n"
                "### Its subsection\n\nThe subsection.\n")


def build_preamble(work):
    """A chapter of long paragraphs and one with a section and a
    subsection, whose metadata file is PREAMBLE_META: (the PDF's path,
    build-pdf.py's LaTeX run on its own from the folder above, with -d
    the book's folder as a relative path, and what it said)."""
    os.makedirs(work)
    for name, text in (("one.md", "# One\n\n" + "".join(FOOTER_WORDS * 4 + "\n\n"
                                                         for _ in range(6))),
                       ("two.md", PREAMBLE_TWO), ("_preamble.md", PREAMBLE_META)):
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  title: Preamble\n  identifier: org.example.preamble\n"
                 "  language: en-US\n  contents:\n    - one\n    - two\n")
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  pdf:\n    format: pdf\n    pdf:\n      metadata: _preamble.md\n")
    subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick"], cwd=work,
                   capture_output=True, text=True, stdin=subprocess.DEVNULL)
    # The metadata file had been looked for in the book's folder twice
    # over (Pandoc ran there, given a path relative to where the build
    # did), and the build stopped.
    hand = subprocess.run(["python3", os.path.join(BIN, "build-pdf.py"), "-d",
                           os.path.basename(work), "--latex-only"],
                          cwd=os.path.dirname(work), capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)
    tex = os.path.join(work, "pdf", "book.tex")
    source = ""
    if os.path.exists(tex):
        with open(tex, encoding="utf-8") as fh:
            source = fh.read()
    return os.path.join(work, "pdf", "org.example.preamble.pdf"), source, \
        hand.stdout + hand.stderr

# The page for WCAG 1.4.8 (AAA), bin/pdf-layout-wcag-aaa.yaml, copied into
# a book as its metadata file: FOOTER_ONE's footnote, and a chapter with a
# table, which loads the caption package, a figure with a long caption, and
# paragraphs. The text's lines are spaced by the type's size, and so are a
# footnote's and a caption's, which setspace and the caption package set
# single-spaced on the default page.
AAA_TABLE = ("\n| Name | What it holds |\n|---|---|\n| One | A cell. |\n\n"
             ": A table, which loads the caption package.\n")


def build_aaa(work):
    """FOOTER_ONE, and FOOTER_TWO with AAA_TABLE, a figure with a long
    caption, and paragraphs, on the AAA page: the PDF's path."""
    os.makedirs(work)
    two = (FOOTER_TWO + AAA_TABLE + "\n![" + FOOTER_CAPTION * 3 + "Henceforth.](cc.png)\n"
           + "".join("\n" + FOOTER_WORDS * 4 + "\n" for _ in range(4)))
    for name, text in (("one.md", FOOTER_ONE), ("two.md", two)):
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    shutil.copy(os.path.join(BIN, "pdf-layout-wcag-aaa.yaml"), work)
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  title: AAA\n  identifier: org.example.aaa\n"
                 "  language: en-US\n  contents:\n    - one\n    - two\n")
    png(os.path.join(work, "cc.png"), (0, 0, 0))
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  pdf:\n    format: pdf\n    pdf:\n"
                 "      metadata: pdf-layout-wcag-aaa.yaml\n")
    subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick"], cwd=work,
                   capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return os.path.join(work, "pdf", "org.example.aaa.pdf")


def build_default(work):
    """The book (write_book) on the PDF target's default page, which its
    checks measure on the class's (CLASS_PAGE): every kind of thing it
    holds, ragged right, in 12pt type on the default's margins. The PDF's
    path."""
    write_book(work)
    with open(os.path.join(work, "front.md"), "w", encoding="utf-8") as fh:
        fh.write(FRONT.replace(CLASS_PAGE, ""))
    subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick"], cwd=work,
                   capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return os.path.join(work, "pdf", "org.example.pdf.pdf")


def glyph_lines(path):
    """{page index: [(baseline, left, right, text)]}, each page's lines,
    its glyphs grouped by their baseline, from the top of the page down
    (pdftext.glyph_boxes): a line begins and ends where its first and last
    glyphs that aren't a space do, a space after its last word left out."""
    rows = {}
    for page, baseline, left, right, char in pdftext.glyph_boxes(path):
        rows.setdefault(page, {}).setdefault(baseline, []).append((left, right, char))
    return {page: sorted(((baseline, min(g[0] for g in shown), max(g[1] for g in shown),
                           "".join(g[2] for g in glyphs))
                          for baseline, glyphs in lines.items()
                          for shown in [[g for g in glyphs if g[2].strip()] or glyphs]),
                         reverse=True)
            for page, lines in rows.items()}


def sizes_by_page(reader, words):
    """[the sizes text holding words is drawn at] for each page, its font's
    size as the page scales it, as head_sizes reads them."""
    import math
    found = []
    for page in reader.pages:
        sizes = []

        def visit(text, cm, tm, font, size):
            if words in text:
                sizes.append(round(size * math.hypot(tm[0], tm[1])
                                   * math.hypot(cm[0], cm[1]), 2))
        page.extract_text(visitor_text=visit)
        found.append(sizes)
    return found


def head_of(source, words):
    """The LaTeX of the longtable holding words, from its column
    specification through its first head ("" if none holds them)."""
    for chunk in source.split("\\begin{longtable}")[1:]:
        table = chunk.split("\\end{longtable}")[0]
        if words in table:
            return table.split("\\endhead")[0]
    return ""


def table_size(source, words):
    """The type size the longtable holding words is set in, the group
    pdf-target.lua opens before it ("small", "footnotesize"), "" for the
    text's own, and None if no table holds them."""
    parts = source.split("\\begin{longtable}")
    for i in range(1, len(parts)):
        if words in parts[i].split("\\end{longtable}")[0]:
            before = parts[i - 1].split("\\end{longtable}")[-1]
            found = re.findall(r"\{\\(small|footnotesize)\b", before)
            return found[-1] if found else ""
    return None


def footnote_marks(path):
    """Each footnote mark of a tagged PDF, in order: its text, and the text
    of each note its /Ref links it to."""
    texts = pdftext.marked_text(path)
    pdf = pdfparagraphs.pikepdf.open(path)
    pages = {page.objgen: n for n, page in enumerate(pdf.pages)}

    def text_of(element):
        text = pdftext.own_text(element, texts, pages)
        for kid in pdfparagraphs.kids_of(element):
            if pdfparagraphs.is_struct_elem(kid):
                text += text_of(kid)
        return text
    found = []

    def walk(element):
        if not pdfparagraphs.is_struct_elem(element):
            return
        if str(element["/S"]) == "/footnotemark":
            found.append((text_of(element), [text_of(note) for note in element.get("/Ref") or []]))
        for kid in pdfparagraphs.kids_of(element):
            walk(kid)
    for kid in pdfparagraphs.kids_of(pdf.Root.StructTreeRoot):
        walk(kid)
    return found


# Where each chapter of the notes book has its notes' marks, in order.
CAPTION_MARKS = [r"with\s+a\s+note\.\s*1", r"caption\s+has\s+a\s+note\.\s*2",
                 r"own,\s+has\s+a\s+note\.\s*3"]
CELL_MARKS = [r"Above\s+it,\s+a\s+note\.\s*4", r"x\s*5\s*y\s*6",
              r"Beside\s+it,\s+a\s+note\.\s*7", r"tables,\s+a\s+note\.\s*8"]


def numbered_notes(text, letters, first, marks):
    """Whether the PDF's text has the notes lettered letters (NOTES_CAPTIONS,
    NOTES_CELLS) numbered from first, in order, and each mark beside its
    words."""
    return all(re.search(r"(?<![\d.])%d\s*Note\s+%s," % (n, letter), text)
               for n, letter in enumerate(letters, first)) \
        and all(re.search(mark, text) for mark in marks)


def linked_notes(marks, letters, first):
    """Whether footnote_marks's marks are numbered from first, in order,
    each linked to the note of its number, lettered letters in order."""
    return [(mark, [re.sub(r"^(\d+)\s*Note (\w),.*", r"\1\2", note) for note in notes])
            for mark, notes in marks] \
        == [(str(n), ["%d%s" % (n, letter)]) for n, letter in enumerate(letters, first)]


def text_paths(path, words):
    """For each structure element whose own text holds words, the kinds
    of the elements from the root down to it."""
    if not os.path.exists(path):
        return []
    texts = pdftext.marked_text(path)
    pdf = pdfparagraphs.pikepdf.open(path)
    pages = {page.objgen: n for n, page in enumerate(pdf.pages)}
    found = []

    def walk(element, above):
        if not pdfparagraphs.is_struct_elem(element):
            return
        here = above + [str(element["/S"])]
        if words in " ".join(pdftext.own_text(element, texts, pages).split()):
            found.append(here)
        for kid in pdfparagraphs.kids_of(element):
            walk(kid, here)
    for kid in pdfparagraphs.kids_of(pdf.Root.StructTreeRoot):
        walk(kid, [])
    return found


def deep_texts(path):
    """Each structure element's kind, classes, and text, its own and its
    descendants', in order, with its children's kinds and texts."""
    if not os.path.exists(path):
        return []
    texts = pdftext.marked_text(path)
    pdf = pdfparagraphs.pikepdf.open(path)
    pages = {page.objgen: n for n, page in enumerate(pdf.pages)}
    found = []

    def walk(element):
        if not pdfparagraphs.is_struct_elem(element):
            return None
        at = len(found)
        found.append(None)
        text, kids = pdftext.own_text(element, texts, pages), []
        for kid in pdfparagraphs.kids_of(element):
            got = walk(kid)
            if got is not None:
                kids.append(got)
                text += got[1]
        value = element.get("/C")
        named = [str(v) for v in value] if isinstance(value, pdfparagraphs.pikepdf.Array) \
            else ([str(value)] if value is not None else [])
        found[at] = (str(element["/S"]), named, text, kids)
        return str(element["/S"]), text
    for kid in pdfparagraphs.kids_of(pdf.Root.StructTreeRoot):
        walk(kid)
    return found


def row_cells(path, words):
    """The text of each cell of each table row whose text holds words."""
    return [[text for kind_, text in kids if kind_ in ("/TD", "/TH")]
            for kind_, _, text, kids in deep_texts(path) if kind_ == "/TR" and words in text]


def untagged_repairs(work):
    """build-pdf.py's repairs after LaTeX on a PDF with no structure tree,
    as one built to no PDF/UA standard has none: (whether it's taken for
    tagged, what the repairs said, what they raised)."""
    path = os.path.join(work, "untagged.pdf")
    pdf = pdfparagraphs.pikepdf.new()
    pdf.add_blank_page()
    pdf.save(path)
    spec = importlib.util.spec_from_file_location("build_pdf", os.path.join(BIN, "build-pdf.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    said, raised = io.StringIO(), None
    try:
        with contextlib.redirect_stderr(said):
            module.repair(path, {"pdf.repair_captions": True,
                                 "pdf.remove_empty_paragraphs": True}, [])
    except Exception as exc:
        raised = repr(exc)
    return module.pdfretag.tagged(path), said.getvalue(), raised


def ua1_formulas(path):
    """Each Formula's alt text, its attribute owners, and its kids' kinds."""
    pdf = pdfparagraphs.pikepdf.open(path)
    found = []

    def walk(element):
        if not pdfparagraphs.is_struct_elem(element):
            return
        if str(element["/S"]) == "/Formula":
            attributes = element.get("/A")
            attributes = attributes if isinstance(attributes, pdfparagraphs.pikepdf.Array) \
                else ([attributes] if attributes is not None else [])
            found.append((str(element.get("/Alt", "")),
                          [str(a.get("/O")) for a in attributes
                           if isinstance(a, pdfparagraphs.pikepdf.Dictionary)],
                          [str(k["/S"]) for k in pdfparagraphs.kids_of(element)
                           if pdfparagraphs.is_struct_elem(k)]))
        for kid in pdfparagraphs.kids_of(element):
            walk(kid)
    for kid in pdfparagraphs.kids_of(pdf.Root.StructTreeRoot):
        walk(kid)
    links = ["/Contents" in annot for page in pdf.pages for annot in page.get("/Annots") or []
             if str(annot.get("/Subtype")) == "/Link"]
    role = pdfparagraphs.make_role_resolver(pdf.Root.StructTreeRoot)
    kinds = []

    def roles(element):
        if pdfparagraphs.is_struct_elem(element):
            kinds.append(role(str(element["/S"])))
            for kid in pdfparagraphs.kids_of(element):
                roles(kid)
    for kid in pdfparagraphs.kids_of(pdf.Root.StructTreeRoot):
        roles(kid)
    found.append(("roles", kinds))
    return found, pdf.pdf_version, links


def page_label_styles(path):
    """The numbering style of each run of pages, in order: /D for 1, 2,
    3; /r for i, ii, iii."""
    pdf = pdfparagraphs.pikepdf.open(path)
    labels = pdf.Root.get("/PageLabels")
    if labels is None:
        return []
    nums = list(labels.get("/Nums") or [])
    return [str(nums[i + 1].get("/S")) for i in range(0, len(nums), 2)]


def spanning_table(path, index):
    """The index-th table's rows, each as a list of its cells' RowSpan (1
    when the cell has none), from the class map and the cells' own
    attributes."""
    import pdfretag
    pdf = pdfparagraphs.pikepdf.open(path)
    classes = pdf.Root.StructTreeRoot.get("/ClassMap") or {}
    found = pdfretag.tables(pdf.Root.StructTreeRoot)
    if len(found) <= index:
        return []

    def span(cell):
        names = cell.get("/C")
        names = list(names) if isinstance(names, pdfparagraphs.pikepdf.Array) else ([names] if names is not None else [])
        owned = [classes.get(str(n)) for n in names] + [cell.get("/A")]
        for attributes in owned:
            for one in (attributes if isinstance(attributes, pdfparagraphs.pikepdf.Array) else [attributes]):
                if isinstance(one, pdfparagraphs.pikepdf.Dictionary) and "/RowSpan" in one:
                    return int(one["/RowSpan"])
        return 1
    rows = []
    for row in pdfretag._kids(found[index]):
        if pdfretag._kind(row) == "/TR":
            rows.append([span(c) for c in pdfretag._cells(row)])
    return rows


def quoted_cells(path):
    """BlockQuote elements under a table cell, by their standard role."""
    pdf = pdfparagraphs.pikepdf.open(path)
    role = pdfparagraphs.make_role_resolver(pdf.Root.StructTreeRoot)
    found = []

    def walk(element, in_cell):
        if not pdfparagraphs.is_struct_elem(element):
            return
        kind_here = role(str(element["/S"]))
        if in_cell and kind_here == "/BlockQuote":
            found.append(element)
        for kid in pdfparagraphs.kids_of(element):
            walk(kid, in_cell or kind_here in ("/TD", "/TH"))
    for kid in pdfparagraphs.kids_of(pdf.Root.StructTreeRoot):
        walk(kid, False)
    return found


def says(text, words):
    """Whether the PDF's text holds the words, any space between them."""
    return re.search(r"\s+".join(map(re.escape, words.split())), text) is not None


def blank_on_line(path, words):
    """For the line whose text holds words and a run of underscores: how
    far the run's last underscore ends from where the line's first glyph
    starts, how many underscores it has, whether any overlaps the one
    before it, how wide the run is drawn, how wide one underscore is, and
    how far apart the closest two words are, from where the space between
    them starts (a tagged PDF's text has its spaces); None for no such
    line."""
    lines = {}
    for page, baseline, left, right, char in pdftext.glyph_boxes(path):
        lines.setdefault((page, baseline), []).append((left, right, char))
    for glyphs in lines.values():
        if words in "".join(g[2] for g in glyphs):
            run = [g for g in glyphs if g[2] == "_"]
            if run:
                return (run[-1][1] - glyphs[0][0], len(run),
                        any(b[0] < a[1] - 0.01 for a, b in zip(run, run[1:])),
                        run[-1][1] - run[0][0], run[0][1] - run[0][0],
                        min((b[0] - a[0] for a, b in zip(glyphs, glyphs[1:]) if a[2] == " "),
                            default=None))
    return None


def children(element):
    """An element's own structure elements, in order."""
    kids = resolve(element.get("/K"))
    kids = kids if isinstance(kids, list) else [kids]
    return [resolve(k) for k in kids if isinstance(resolve(k), dict) and "/S" in resolve(k)]


def inside(everything, outer, inner):
    """The inner elements that sit anywhere under an outer one."""
    found = []
    for element in everything:
        if kind(element) == outer:
            found += [e for e in elements(element) if kind(e) == inner]
    return found


def tables(everything):
    """Each /Table's elements, the table's own and not a nested one's."""
    out = []
    for element in everything:
        if kind(element) == "/Table":
            out.append(elements(element))
    return out


def links(reader):
    out = []
    for page in reader.pages:
        for annot in resolve(page.get("/Annots")) or []:
            annot = resolve(annot)
            if annot.get("/Subtype") != "/Link":
                continue
            action = resolve(annot.get("/A")) if "/A" in annot else {}
            out.append((str(action.get("/S", "/Dest")),
                        str(action.get("/URI", "")),
                        str(annot["/Contents"]) if "/Contents" in annot
                        else None))
    return out


def goes_to(path, contents):
    """The page each internal link described as contents goes to, in
    order: None where the PDF doesn't define its destination."""
    if not os.path.exists(path):
        return []
    reader = pypdf.PdfReader(path)
    named = reader.named_destinations
    out = []
    for page in reader.pages:
        for annot in resolve(page.get("/Annots")) or []:
            annot = resolve(annot)
            action = resolve(annot.get("/A")) if "/A" in annot else {}
            if annot.get("/Subtype") == "/Link" and action.get("/S") == "/GoTo" \
                    and str(annot.get("/Contents")) == contents:
                dest = named.get(str(action.get("/D")))
                out.append(reader.get_destination_page_number(dest) if dest else None)
    return out


def page_holding(path, words):
    """The first page whose text holds the words, or None."""
    if not os.path.exists(path):
        return None
    for n, page in enumerate(pypdf.PdfReader(path).pages):
        if says(page.extract_text() or "", words):
            return n
    return None


def artifact_rules(path):
    """{page index: [the height of each straight line the page strokes as
    an artifact]}, in points from the page's foot, as the current matrix
    places it."""
    pikepdf = pdfparagraphs.pikepdf
    found = {}
    if not os.path.exists(path):
        return found
    with pikepdf.open(path) as pdf:
        for n, page in enumerate(pdf.pages):
            ctm, saved, marked, heights = [1, 0, 0, 1, 0, 0], [], [], []
            for operands, op in pikepdf.parse_content_stream(page):
                op = str(op)
                if op == "q":
                    saved.append(ctm)
                elif op == "Q" and saved:
                    ctm = saved.pop()
                elif op == "cm" and len(operands) == 6:
                    ctm = pdftext._times([float(x) for x in operands], ctm)
                elif op in ("BMC", "BDC"):
                    marked.append(str(operands[0]))
                elif op == "EMC" and marked:
                    marked.pop()
                elif op in ("m", "l") and len(operands) == 2:
                    x, y = (float(v) for v in operands)
                    heights.append(ctm[1] * x + ctm[3] * y + ctm[5])
                elif op == "S":
                    if len(heights) == 2 and "/Artifact" in marked:
                        found.setdefault(n, []).append(round(heights[0], 2))
                    heights = []
    return found


def artifact_strokes(path, words):
    """The lengths of the straight lines, in points, that the first page
    holding words strokes as artifacts."""
    pikepdf = pdfparagraphs.pikepdf
    at = page_holding(path, words)
    if at is None:
        return []
    found, marked, path_ = [], [], []
    with pikepdf.open(path) as pdf:
        for operands, op in pikepdf.parse_content_stream(pdf.pages[at]):
            op = str(op)
            if op in ("BMC", "BDC"):
                marked.append(str(operands[0]))
            elif op == "EMC" and marked:
                marked.pop()
            elif op in ("m", "l"):
                path_.append([float(x) for x in operands])
            elif op == "S":
                if len(path_) == 2 and "/Artifact" in marked:
                    found.append(round(abs(path_[1][0] - path_[0][0])))
                path_ = []
    return found


def font_names(reader):
    """The base font names the PDF's pages draw with, form XObjects too."""
    names = set()

    def walk(resources):
        if resources is None:
            return
        resources = resources.get_object()
        for ref in (resolve(resources.get("/Font")) or {}).values():
            names.add(str(ref.get_object().get("/BaseFont", "")))
        for ref in (resolve(resources.get("/XObject")) or {}).values():
            xobject = ref.get_object()
            if xobject.get("/Subtype") == "/Form":
                walk(xobject.get("/Resources"))
    for page in reader.pages:
        walk(page.get("/Resources"))
    return names


def fill_colors(reader):
    """The fill colors the pages' content sets, as LaTeX writes them."""
    found = set()
    for page in reader.pages:
        content = page.get_contents()
        if content is not None:
            found |= set(re.findall(rb"([\d.]+ [\d.]+ [\d.]+) rg", content.get_data()))
    return {color.decode() for color in found}


def latex_color(color):
    """A #rrggbb color as Pandoc's highlighting macros give it LaTeX,
    and LaTeX the PDF."""
    return " ".join("%.2f" % (int(color[i:i + 2], 16) / 255) for i in (1, 3, 5))


# The TeX packages the suite's books load that a tagged build of any book
# may not, which a smaller TeX can lack, by a file each holds: the default
# page's geometry and setspace, scrextend for the sized book's 13.5pt, and
# multirow for the book's table with a cell spanning rows
# (docs/installation.md).
SUITE_TEX = [("geometry", "geometry.sty"), ("setspace", "setspace.sty"),
             ("koma-script", "scrextend.sty"), ("multirow", "multirow.sty")]


def tex_missing():
    """The packages of SUITE_TEX TeX can't find, none where there's no
    kpsewhich to ask."""
    if not shutil.which("kpsewhich"):
        return []
    return [package for package, name in SUITE_TEX
            if not subprocess.run(["kpsewhich", name], capture_output=True, text=True,
                                  stdin=subprocess.DEVNULL).stdout.strip()]


def font_installed(name):
    """Whether TeX finds the font file."""
    if not shutil.which("kpsewhich"):
        return False
    found = subprocess.run(["kpsewhich", name], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)
    return bool(found.stdout.strip())


def image_widths(reader):
    """The width, in points, each image a page draws is drawn at: its
    matrix's, as the page's q, Q, and cm operators leave it."""
    import math
    widths = []
    for page in reader.pages:
        resources = resolve(page.get("/Resources")) or {}
        images = resolve(resources.get("/XObject")) or {}
        content = page.get_contents()
        if content is None:
            continue
        matrix, saved = (1, 0, 0, 1, 0, 0), []
        for operands, operator in content.operations:
            if operator == b"q":
                saved.append(matrix)
            elif operator == b"Q" and saved:
                matrix = saved.pop()
            elif operator == b"cm":
                a, b, c, d, e, f = (float(x) for x in operands)
                A, B, C, D, E, F = matrix
                matrix = (a * A + b * C, a * B + b * D, c * A + d * C,
                          c * B + d * D, e * A + f * C + E, e * B + f * D + F)
            elif operator == b"Do" and operands:
                image = images.get(operands[0])
                if image is not None and image.get_object().get("/Subtype") == "/Image":
                    widths.append(math.hypot(matrix[0], matrix[1]))
    return widths


def image_boxes(reader, words):
    """(x, y, width) in points of each image drawn on the first page whose
    text holds words, as the page's q, Q, and cm operators place it."""
    import math
    for page in reader.pages:
        if not says(page.extract_text() or "", words):
            continue
        resources = resolve(page.get("/Resources")) or {}
        images = resolve(resources.get("/XObject")) or {}
        content = page.get_contents()
        boxes = []
        matrix, saved = (1, 0, 0, 1, 0, 0), []
        for operands, operator in (content.operations if content is not None else []):
            if operator == b"q":
                saved.append(matrix)
            elif operator == b"Q" and saved:
                matrix = saved.pop()
            elif operator == b"cm":
                a, b, c, d, e, f = (float(x) for x in operands)
                A, B, C, D, E, F = matrix
                matrix = (a * A + b * C, a * B + b * D, c * A + d * C,
                          c * B + d * D, e * A + f * C + E, e * B + f * D + F)
            elif operator == b"Do" and operands:
                image = images.get(operands[0])
                if image is not None and image.get_object().get("/Subtype") == "/Image":
                    boxes.append((round(matrix[4], 1), round(matrix[5], 1),
                                  round(math.hypot(matrix[0], matrix[1]), 1)))
        return boxes
    return []


def head_sizes(reader, words):
    """The size each page's running head holding words is drawn at, its
    font's size as the page scales it."""
    import math
    sizes = []
    for page in reader.pages:
        def visit(text, cm, tm, font, size):
            if words in text:
                sizes.append(size * math.hypot(tm[0], tm[1]) * math.hypot(cm[0], cm[1]))
        page.extract_text(visitor_text=visit)
    return sizes


def outline_titles(reader):
    titles = []

    def walk(items):
        for item in items:
            if isinstance(item, list):
                walk(item)
            else:
                titles.append(item.title)
    walk(reader.outline)
    return titles


# --------------------------------------------------------------------------

def run(arguments, cwd, environment=None):
    return subprocess.run(arguments, cwd=cwd, env=environment,
                          capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)


def build(work):
    """The book converted by convert.py, then its LaTeX written again on
    its own so the division commands can be counted."""
    write_book(work)
    converted = run(["python3", os.path.join(BIN, "convert.py")], work)
    pdf = os.path.join(work, "pdf", "org.example.pdf.pdf")
    if not os.path.exists(pdf):
        raise RuntimeError("no PDF was written:\n" + converted.stderr[-3000:])
    latex = run(["python3", os.path.join(BIN, "build-pdf.py"),
                 "--latex-only"], work)
    tex = os.path.join(work, "pdf", "book.tex")
    if not os.path.exists(tex):
        raise RuntimeError("no LaTeX was written:\n" + latex.stderr[-3000:])
    with open(tex, encoding="utf-8") as fh:
        source = fh.read()
    # The other two figure placements, as LaTeX gets them: written only,
    # since LaTeX takes a while and the in_place default is built above.
    placements = {}
    for choice in ("section", "float"):
        with open(os.path.join(work, "conversion.yaml"), "w") as fh:
            fh.write(CONVERSION + "      figures: %s\n" % choice)
        run(["python3", os.path.join(BIN, "build-pdf.py"), "--latex-only"], work)
        with open(tex, encoding="utf-8") as fh:
            placements[choice] = fh.read()
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write(CONVERSION)
    report = os.path.join(work, "output-check.csv")
    rows = []
    if os.path.exists(report):
        with open(report, encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
    return pypdf.PdfReader(pdf), source, rows, converted.stderr, placements


def squeezed(words):
    """Words without their spaces, which a PDF's text gives as it likes."""
    return re.sub(r"\s+", "", words)


def text_lines(lines, page):
    """The lines of a page of text alone, between the default page's head
    and foot, more than 20 characters each: [(baseline, left, right,
    text)], from the top (glyph_lines)."""
    return [line for line in lines.get(page, []) if 57.6 < line[0] < 734.4
            and len(squeezed(line[3])) > 20] if page is not None else []


def commonest_leading(lines):
    """The distance between lines that most of them keep."""
    gaps = [round(a[0] - b[0], 1) for a, b in zip(lines, lines[1:])]
    return max(set(gaps), key=gaps.count) if gaps else None


def ragged(lines, margin=540):
    """Whether lines are set ragged right: those before the last don't
    end together, fewer than half of them reaching the margin, as all but
    a paragraph's last line of justified text do, and none ends in a
    broken word. The default page's margin is an inch in from the right
    of a Letter page."""
    ends = [line[2] for line in lines[:-1]]
    return len(ends) > 2 and max(ends) - min(ends) > 3 \
        and sum(1 for end in ends if end > margin - 0.5) < len(ends) / 2 \
        and not any(line[3].rstrip().endswith("-") for line in lines)


def footer_checks(footer_path):
    """The footer book's checks (build_footer): the footer setting at the
    foot of every page (lib/pagefooter.py), on the PDF target's default
    page (bin/pdf-layout.yaml)."""
    footer_reader = pypdf.PdfReader(footer_path) if os.path.exists(footer_path) else None
    footer_lines = glyph_lines(footer_path) if footer_reader else {}
    footer_texts = pdftext.marked_text(footer_path) if footer_reader else {}
    opening = page_holding(footer_path, "The first chapter opens")
    captioned = page_holding(footer_path, "The second chapter")

    def footer_baselines():
        """Each page's footer's baseline, None on a page without one."""
        return [next((b for b, _, _, t in footer_lines.get(n, [])
                      if "freeatexample.net" in squeezed(t)), None)
                for n in range(len(footer_reader.pages))] if footer_reader else []

    def opening_gap():
        """How far the footer's baseline is under the page number's on the
        first chapter's opening page, whose foot has its number: the line
        of digits alone nearest above the footer."""
        lines = footer_lines.get(opening, [])
        foot = [b for b, _, _, t in lines if "freeatexample.net" in squeezed(t)]
        number = [b for b, _, _, t in lines if squeezed(t).isdigit()
                  and foot and b > foot[0]]
        return min(number) - foot[0] if number and foot else None

    def body_lines():
        """The lines of the page after the first chapter's opening page, a
        page of its text alone."""
        return text_lines(footer_lines, opening + 1) if opening is not None else []

    def run_of(page, first, last):
        """The lines of a page from the first holding first to the next
        holding last, spaces aside."""
        lines = footer_lines.get(page, []) if page is not None else []
        start = next((i for i, line in enumerate(lines) if first in squeezed(line[3])), None)
        if start is None:
            return []
        end = next((i for i, line in enumerate(lines[start:], start)
                    if last in squeezed(line[3])), None)
        return lines[start:end + 1] if end is not None else []
    items = [
        ("a footer is at the foot of every page, the title page's among them, as an "
         "artifact, a link in it its words and a picture its alternative text, with no "
         "link and no image",
         lambda: footer_reader is not None and len(footer_reader.pages) >= 5
         and all("Readthisbookfreeatexample.net.CCBY" in squeezed(footer_texts.get((n, None), ""))
                 for n in range(len(footer_reader.pages)))
         and not any("freeat" in squeezed(t) for (n, mcid), t in footer_texts.items()
                     if mcid is not None)
         and not [uri for _, uri, _ in links(footer_reader) if "example.net" in uri]
         and not any(page.images for n, page in enumerate(footer_reader.pages)
                     if n != captioned)),
        ("it's set in the same size and place on every page, the title page's too",
         lambda: footer_baselines() and None not in footer_baselines()
         and max(footer_baselines()) - min(footer_baselines()) < 0.01
         and len({s for sizes in sizes_by_page(footer_reader, "example") for s in sizes}) == 1),
        ("a small line's space under the page number, where the foot has one, whatever "
         "the text's line spacing",
         lambda: opening_gap() is not None and 11 < opening_gap() < 13),
        ("on the PDF target's default page, the footer is in the bottom margin, a "
         "quarter inch or more from the paper's edge",
         lambda: footer_baselines() and None not in footer_baselines()
         and all(18 <= b < 57.6 - 18 for b in footer_baselines())),
        ("and the page is OpenStax's: Letter paper, the text 6.5 inches wide from an "
         "inch in, in 12pt type on lines 1.5 times its size apart",
         lambda: footer_reader is not None
         and (float(footer_reader.pages[0].mediabox.width),
              float(footer_reader.pages[0].mediabox.height)) == (612, 792)
         and len(body_lines()) > 30
         and {round(line[1]) for line in body_lines()} == {72}
         and 530 < max(line[2] for line in body_lines()) < 546
         and 18 <= commonest_leading(body_lines()) <= 18.3
         and set(sizes_by_page(footer_reader, "sentence")[opening + 1]) == {11.96}),
        ("its text is set ragged right, its lines not ending together at the margin, "
         "and no word broken at a line's end",
         lambda: ragged(body_lines())),
        ("and so are a footnote and a caption, which LaTeX sets justified again",
         lambda: ragged(run_of(opening, "Thenote.", "Thereafter."))
         and ragged(run_of(captioned, "Eachsentenceofthiscaption", "Henceforth."))),
        # microtype's font expansion, which justifies a line by drawing its
        # letters up to 2% narrower or wider, had fitted more on a ragged
        # line: a caption's 11.75 points of 11.96, a footnote's 9.77 of 9.96.
        ("no ragged line's letters are drawn narrower or wider to fit more on it: the text, "
         "a footnote, and a caption are in their type's own sizes, 12pt and 10pt",
         lambda: footer_reader is not None and captioned is not None
         and set(s for sizes in sizes_by_page(footer_reader, "sentence") for s in sizes)
         == {11.96, 9.96}
         and set(sizes_by_page(footer_reader, "regulation")[captioned]) == {11.96}),
        # LaTeX's \raggedright makes \\ end the paragraph, which its tagging
        # made two, and a caption's \\, in the box LaTeX sets it in first,
        # stopped LaTeX.
        ("a line break leaves its paragraph one, and a caption's is a line of its caption",
         lambda: any(squeezed(t) == "Alineofaverse,anditsnextline,oneparagraph."
                     for t in pdftext.element_texts(footer_path, "/text"))
         and "Henceforth.Andalineofitsown." in squeezed(
             footer_reader.pages[captioned].extract_text() or "")),
    ]
    if shutil.which("verapdf") or os.environ.get("VERAPDF"):
        items.append(("veraPDF finds nothing in the footer book's PDF",
                      lambda: os.path.exists(footer_path) and not pdfcheck.run_verapdf(
                          outputcheck.find_validator("verapdf"), footer_path)))
    return items


def sized_checks(sized_path, sized_said):
    """The sized book's checks (build_sized): the default page as a
    metadata file changes it, a field at a time."""
    reader = pypdf.PdfReader(sized_path) if os.path.exists(sized_path) else None
    listing = page_holding(sized_path, "Contents")
    contents = reader.pages[listing].extract_text() if listing is not None else ""
    lines = glyph_lines(sized_path) if reader else {}
    opening = page_holding(sized_path, "The first chapter opens")
    body = text_lines(lines, opening + 1) if opening is not None else []
    listed = page_holding(sized_path, "The paragraph before a list")
    boxed = page_holding(sized_path, "A tall black square in a box")
    rules = artifact_rules(sized_path) if reader else {}

    def baseline(page, pattern):
        """The baseline of the page's first line whose text, spaces aside,
        the pattern finds."""
        return next((line[0] for line in lines.get(page, [])
                     if re.search(pattern, squeezed(line[3]))), None)

    def list_gaps():
        """The distances between the baselines of the paragraph before the
        list, its two items, and the paragraph after it."""
        marks = [baseline(listed, p) for p in ("paragraphbeforealist", "firstitem",
                                               "seconditem", "paragraphafterthelist")]
        return [a - b for a, b in zip(marks, marks[1:])] if None not in marks else []

    def item_indent():
        """How far in from the margin the list's first item's words begin,
        its bullet aside."""
        at = baseline(listed, "firstitem")
        shown = sorted(g[2] for g in pdftext.glyph_boxes(sized_path)
                       if g[0] == listed and g[1] == at and g[4].strip())
        return shown[1] - 72 if len(shown) > 1 else None

    def rule_over(pattern):
        """How far the nearest rule above a line of the box's page is above
        its baseline, the line the pattern finds."""
        under = baseline(boxed, pattern)
        above = [y - under for y in rules.get(boxed, []) if under is not None and y > under]
        return min(above) if above else None
    return [
        ("a metadata file changes the default page a field at a time: 13.5pt type, a "
         "size the book class hasn't, on the default's Letter paper an inch in from its "
         "edge, on lines 1.5 times its size apart",
         lambda: reader is not None
         and (float(reader.pages[0].mediabox.width),
              float(reader.pages[0].mediabox.height)) == (612, 792)
         and len(body) > 20 and {round(line[1]) for line in body} == {72}
         # microtype's font expansion draws a justified line's glyphs as
         # much as 2% larger or smaller.
         and sizes_by_page(reader, "sentence")[opening + 1]
         and all(abs(size / 13.45 - 1) < 0.03
                 for size in sizes_by_page(reader, "sentence")[opening + 1])
         and 1.45 * 13.45 < commonest_leading(body) < 1.55 * 13.45),
        ("and ragged-right: false justifies the text, most of its lines reaching the margin",
         lambda: len(body) > 20
         and sum(1 for line in body[:-1] if line[2] >= 539) > len(body) / 2),
        # 20.18 points of line and 8.07 of parskip's half a line at 13.5pt
        # (16.2 points), where the class's 10pt had left it 6 points.
        ("its paragraphs half a line apart at that size, as at the class's own",
         lambda: (lambda gaps: len(gaps) > 2 and all(27.75 < g < 28.75 for g in gaps))(
             [a[0] - b[0] for a, b in zip(body, body[1:]) if a[0] - b[0] > 22])),
        # scrextend sets the size, and its own spacing for lists, where
        # parskip's had none above a list or between its items but the
        # space between paragraphs; a list's indents, in ems, and the space
        # above a page's first line, its type's size, were the class's, at
        # 10pt.
        ("a list at that size is spaced as its paragraphs are, its items' words 2.5em in, "
         "and a page's first line is a line of that type below the top margin",
         lambda: len(list_gaps()) == 3 and all(27.75 < g < 28.75 for g in list_gaps())
         and item_indent() is not None and abs(item_indent() - 2.5 * 13.45) < 0.2
         and len(body) > 20 and abs(body[0][0] - (734.4 - 13.45)) < 0.2),
        ("a page number of four digits fits its line of the contents",
         lambda: re.search(r"Its section\W*100\d", contents)
         and "in the contents" not in sized_said),
        ("a box that opens with a heading takes the rule above it to the next page with it",
         lambda: rule_over(r"Thebox.slegend") is not None and rule_over(r"Thebox.slegend") < 60),
        # A figure alone begins no paragraph, which had left the heading
        # after its box without its space above, as one at a box's top is.
        ("a heading after a box is as far below it whatever the box ends with, a figure "
         "or a paragraph",
         lambda: rule_over("Afterthefigure") is not None
         and rule_over("Aftertheparagraph") is not None
         and abs(rule_over("Afterthefigure") - rule_over("Aftertheparagraph")) < 0.5),
    ]


def default_checks(default_path):
    """The default book's checks (build_default): the book on the page a
    book gets when nothing changes it."""
    items = [("the book on the PDF target's default page builds, LaTeX stopping on "
              "nothing in it", lambda: os.path.exists(default_path))]
    if shutil.which("verapdf") or os.environ.get("VERAPDF"):
        items.append(("and veraPDF finds only the character no font has, as on the class's "
                      "page",
                      lambda: os.path.exists(default_path) and {
                          f.check for f in pdfcheck.run_verapdf(
                              outputcheck.find_validator("verapdf"), default_path)}
                      == {"verapdf:8.4.5.9-1"}))
    return items



def preamble_checks(preamble_path, preamble_source, preamble_said):
    """The preamble book's checks (build_preamble)."""
    reader = pypdf.PdfReader(preamble_path) if os.path.exists(preamble_path) else None
    lines = glyph_lines(preamble_path) if reader else {}
    opening = page_holding(preamble_path, "Each sentence of this chapter")
    body = text_lines(lines, opening)
    # setspace's double spacing at 12pt is 1.655 of the class's 14.5
    # points, 23.91 of the PDF's; the default page's is 18.06.
    return [
        ("a metadata file that loads geometry and setspace itself, as a book written for "
         "Pandoc's page may, has its own margins and line spacing, where the default page "
         "has its own",
         lambda: len(body) > 10 and {round(line[1]) for line in body} == {108}
         and 23.5 < commonest_leading(body) < 24.3),
        ("without a contents page, the bookmarks go as deep as pdf.toc_depth says, a "
         "page's sections and not their subsections",
         lambda: reader is not None
         and not any("Contents" in (page.extract_text() or "") for page in reader.pages)
         and outline_titles(reader) == ["One", "Two", "Its section"]),
        ("build-pdf.py run on its own, given the book's folder as a relative path, finds "
         "the metadata file",
         lambda: "\\usepackage[margin=1.5in]{geometry}" in preamble_source
         and "Could not find" not in preamble_said and "does not exist" not in preamble_said),
    ]

def aaa_checks(aaa_path):
    """The AAA book's checks (build_aaa): the page for WCAG 1.4.8 (AAA),
    bin/pdf-layout-wcag-aaa.yaml. 13.5pt is 13.45 of the PDF's points,
    and a footnote's type, 11.25pt, is 11.21."""
    reader = pypdf.PdfReader(aaa_path) if os.path.exists(aaa_path) else None
    lines = glyph_lines(aaa_path) if reader else {}
    opening = page_holding(aaa_path, "The first chapter opens")
    body = text_lines(lines, opening + 1) if opening is not None else []
    sizes = sizes_by_page(reader, "sentence")[opening + 1] \
        if opening is not None and opening + 1 < len(reader.pages) else []
    leading = commonest_leading(body) or 0
    # The space between paragraphs on every page of text, the least of
    # them as the page sets it: a full page's, two-sided, is stretched to
    # fill it (\flushbottom), a chapter's last page's not.
    breaks = []
    for page in range(opening, len(reader.pages)) if opening is not None else []:
        found = text_lines(lines, page)
        breaks += [a[0] - b[0] for a, b in zip(found, found[1:])
                   if 1.5 * leading < a[0] - b[0] < 2 * leading]

    def lines_from(page, first, last=None):
        """A page's lines from the one holding first to the one holding
        last, or to the page's text's end."""
        found = text_lines(lines, page)
        start = next((i for i, line in enumerate(found) if squeezed(first) in
                      squeezed(line[3])), None)
        if start is None:
            return []
        end = next((i for i, line in enumerate(found) if i >= start and last
                    and squeezed(last) in squeezed(line[3])), len(found) - 1)
        return found[start:end + 1]
    note = lines_from(opening, "The note.") if opening is not None else []
    figure = page_holding(aaa_path, "Each sentence of this caption")
    caption = lines_from(figure, "Each sentence of this caption", "Henceforth") \
        if figure is not None else []
    return [
        ("on the page for WCAG 1.4.8 (AAA), the text is 13.5pt type on lines "
         "space-and-a-half apart, 1.5 times the type's size, as W3C's technique C21 "
         "measures it",
         lambda: len(body) > 10 and set(sizes) == {13.45}
         and abs(leading - 1.5 * 13.45) < 0.15),
        ("its paragraphs 2.5 times the type's size apart, from the top of one's last "
         "line to the top of the next one's first",
         lambda: len(breaks) >= 2 and abs(min(breaks) - 2.5 * 13.45) < 0.5),
        ("and a footnote's lines and a caption's, in a book with a table, which loads "
         "the caption package, are as far apart for their type as the text's, where the "
         "default page sets them single-spaced",
         lambda: len(note) > 2 and len(caption) > 2
         and abs(commonest_leading(note) - 1.5 * 11.21) < 0.15
         and abs(commonest_leading(caption) - 1.5 * 13.45) < 0.15),
    ]


def fancy_checks(fancy_path):
    """The fancy book's checks (build_fancy)."""
    reader = pypdf.PdfReader(fancy_path) if os.path.exists(fancy_path) else None
    texts = pdftext.marked_text(fancy_path) if reader else {}
    opening = page_holding(fancy_path, "The first chapter opens")
    body = sizes_by_page(reader, "sentence")[opening + 1] \
        if opening is not None and opening + 1 < len(reader.pages) else []

    def footers(n):
        return re.sub(r"\s+", "", texts.get((n, None), "")).count("LicenseSharedunderthelicense.")
    return [
        ("in fancyhdr's page styles, a chapter's first page's made from the others', and "
         "an even page's foot given by the odd one's, the footer is at the foot of every "
         "page once",
         lambda: reader is not None and len(reader.pages) >= 4
         and all(footers(n) == 1 for n in range(len(reader.pages)))),
        ("a heading in the footer is a paragraph there, not in the PDF's bookmarks",
         lambda: reader is not None and footers(0) == 1
         and outline_titles(reader) == ["One", "Two"]),
        # 13.5pt is 13.45 of the PDF's points.
        ("a type size and a paper a metadata file gives as class options stand, where the "
         "default page has its own: 13.5pt type, a size the book class hasn't, on A4",
         lambda: reader is not None
         and (round(float(reader.pages[0].mediabox.width)),
              round(float(reader.pages[0].mediabox.height))) == (595, 842)
         and body and set(body) == {13.45}),
    ]


def checks(work, jobs=1):
    # The two books, at once when there's room: each is a LaTeX build of
    # its own, in a directory of its own.
    if jobs > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            book = pool.submit(build, work)
            ua1 = pool.submit(build_ua1, work + "-ua1")
            plain = pool.submit(build_untagged, work + "-untagged")
            noted = pool.submit(build_notes, work + "-notes")
            footed = pool.submit(build_footer, work + "-footer")
            sized = pool.submit(build_sized, work + "-sized")
            fancied = pool.submit(build_fancy, work + "-fancy")
            defaulted = pool.submit(build_default, work + "-default")
            prefaced = pool.submit(build_preamble, work + "-preamble")
            aaa = pool.submit(build_aaa, work + "-aaa")
            reader, source, rows, log, placements = book.result()
            ua1_path, ua1_said, ua1_rows = ua1.result()
            untagged_path, untagged_said = plain.result()
            notes_path, notes_plain, notes_said, notes_source = noted.result()
            footer_path = footed.result()
            sized_path, sized_said = sized.result()
            fancy_path = fancied.result()
            default_path = defaulted.result()
            preamble_path, preamble_source, preamble_said = prefaced.result()
            aaa_path = aaa.result()
    else:
        reader, source, rows, log, placements = build(work)
        ua1_path, ua1_said, ua1_rows = build_ua1(work + "-ua1")
        untagged_path, untagged_said = build_untagged(work + "-untagged")
        notes_path, notes_plain, notes_said, notes_source = build_notes(work + "-notes")
        footer_path = build_footer(work + "-footer")
        sized_path, sized_said = build_sized(work + "-sized")
        fancy_path = build_fancy(work + "-fancy")
        default_path = build_default(work + "-default")
        preamble_path, preamble_source, preamble_said = build_preamble(work + "-preamble")
        aaa_path = build_aaa(work + "-aaa")

    def page_text(path):
        return "".join(page.extract_text() or "" for page in pypdf.PdfReader(path).pages) \
            if os.path.exists(path) else ""
    notes_text, notes_plain_text = page_text(notes_path), page_text(notes_plain)

    def notes_marks():
        return footnote_marks(notes_path) if os.path.exists(notes_path) else []
    untagged_text = "".join(page.extract_text() or "" for page in
                            pypdf.PdfReader(untagged_path).pages) \
        if os.path.exists(untagged_path) else ""
    ua1_math, ua1_version, ua1_links = ua1_formulas(ua1_path) if os.path.exists(ua1_path) \
        else ([], "", [])
    ua1_roles = dict(f for f in ua1_math if f[0] == "roles").get("roles", [])
    ua1_languages = languages(ua1_path) if os.path.exists(ua1_path) else []
    ua1_math = [f for f in ua1_math if f[0] != "roles"]
    pdf_path = os.path.join(work, "pdf", "org.example.pdf.pdf")
    declared = languages(pdf_path)
    untagged = untagged_repairs(work)
    root = reader.trailer["/Root"]
    tree = elements(root["/StructTreeRoot"])
    kinds = [kind(e) for e in tree]
    figures = [e for e in tree if kind(e) == "/Figure"]
    formulas = [e for e in tree if kind(e) == "/Formula"]
    found = links(reader)
    by_uri = {uri: contents for s, uri, contents in found if s == "/URI"}
    goto = [contents for s, uri, contents in found if s != "/URI"]
    tabled = tables(tree)
    table_elements = [e for e in tree if kind(e) == "/Table"]

    def shape(table):
        """A table's own children, and for each row its cells' count."""
        return [kind(k) if kind(k) != "/TR" else len(children(k)) for k in children(table)]
    pdf_rows = [r for r in rows if r.get("Kind") == "pdf"]
    verapdf_ran = shutil.which("verapdf") or os.environ.get("VERAPDF")
    body = source.split("\\begin{document}", 1)[-1]
    text = "".join(page.extract_text() or "" for page in reader.pages)
    contents_page = next((t for t in (page.extract_text() or "" for page in reader.pages)
                          if says(t, "Contents") and says(t, "One")), "")

    def division(command):
        return len(re.findall(re.escape(command) + r"(?![a-zA-Z])", source))

    def row_headers(table):
        return sum(1 for e in table if kind(e) == "/TH"
                   and any("TH-row" in c for c in classes(e)))

    items = [
        ("the PDF is tagged, with a structure tree and a language",
         lambda: "/StructTreeRoot" in root
         and bool(resolve(root["/MarkInfo"])["/Marked"])
         and str(root["/Lang"]) == "en"),
        ("a section's title too long for the running head beside the page number is "
         "scaled to fit there, not run past the margin",
         lambda: head_sizes(reader, "SECTION WHOSE TITLE RUNS")
         and all(size < 9.5 for size in head_sizes(reader, "SECTION WHOSE TITLE RUNS"))),
        # babel's commands set a passage's hyphenation and tag nothing;
        # pdf-target.lua's \\oerlang and oerlanguage give it its /Lang.
        ("a span in another language is a Span with its /Lang, and so is a link in one",
         lambda: ("/Span", "en-GB", "tea and biscuits", None) in declared
         and any(s == "/Span" and lang == "en-GB" and text == "link in it"
                 for s, lang, text, _ in declared)),
        ("a passage's paragraphs and list take its /Lang, and a heading in it is its words "
         "in a Span, the heading and its section declaring nothing",
         lambda: any(lang == "en-GB" and text == "A paragraph in British English, about the "
                     "lift and the flat." and s != "/Span" for s, lang, text, _ in declared)
         and any(lang == "en-GB" and text.endswith("A list in it, of the post and the queue.")
                 for s, lang, text, _ in declared)
         and any(lang == "en-GB" and text == "And a paragraph after the heading, and a table "
                 "with row headers." for s, lang, text, _ in declared)
         and any(s == "/Table" and lang == "en-GB" for s, lang, text, _ in declared)
         and ("/Span", "en-GB", "Holiday", None) in declared),
        ("a passage inside it in a language of its own, with a heading, is its own language's",
         lambda: ("/Span", "en-AU", "Mate", None) in declared
         and any(lang == "en-AU" and above is None and text == "A passage inside it in a "
                 "language of its own." for s, lang, text, above in declared)),
        ("the text after the passage, in the section its heading began, is in the book's "
         "language: nothing around it declares another",
         lambda: any(text.startswith("Back in the book") and text.endswith("own language.")
                     for _, _, text, _ in declared)
         and all(lang is None and above is None for _, lang, text, above in declared
                 if "own language" in text)),
        ("and a PDF/UA-1 file's span too",
         lambda: ("/Span", "en-GB", "flat", None) in ua1_languages),
        # The retagging stopped the run on an untagged PDF, which LaTeX
        # makes for a pdf.standard with no PDF/UA in it.
        ("a PDF with no structure tree, as one built to no PDF/UA standard is, is left as "
         "LaTeX made it, the repairs saying nothing",
         lambda: untagged == (False, "", None)),
        ("it claims PDF/UA-2 in its metadata",
         lambda: re.search(r"pdfuaid:part[^0-9]{1,5}2",
                           resolve(root["/Metadata"]).get_data().decode(
                               "utf-8", "replace")) is not None),
        # The matrix marker declares a header column; latex-lab tags the
        # first cell of each body row TH-row only if pdf-target.lua set
        # table/header-columns around it.
        ("the matrix table's first column is row headers",
         lambda: len(tabled) == 13 and row_headers(tabled[0]) == 2),
        ("and so is a table's in a passage in another language that holds a heading",
         lambda: len(tabled) == 13 and row_headers(tabled[9]) == 1),
        ("the plain table has header cells and no row headers",
         lambda: len(tabled) == 13 and row_headers(tabled[1]) == 0
         and any(kind(e) == "/TH" for e in tabled[1])),
        # LaTeX writes a longtable's caption as a first row of one header
        # cell, and leaves the empty copy of the head it repeats inside the
        # table; pdfretag.py makes the one a Caption and takes the other out.
        # The caption's wrapper also holds paragraph elements that stay
        # empty, which pdfparagraphs.py removes.
        ("headings below a subsection, followed by a section, don't stop "
         "LaTeX's tagging", lambda: "automatic begin" not in log
         and "xxxSubParagraphNoStar" in source),
        # Pandoc sets a cell spanning rows with \\multirow, which LaTeX's
        # tagging doesn't follow; pdf-target.lua says table/multirow in it.
        ("a cell spanning two rows is tagged so, and the row it covers has "
         "no cell of its own there",
         lambda: spanning_table(pdf_path, 5) == [[1, 1], [2, 1], [1], [1, 1]]),
        # LaTeX's record of the cells a span covers outlived its table, and
        # the next table lost the cells at the same places (build-pdf.py).
        ("and the table after it keeps every cell",
         lambda: spanning_table(pdf_path, 6) == [[1, 1]] * 4),
        ("a quotation in a table cell is unwrapped, since a cell can't hold one",
         lambda: not quoted_cells(pdf_path)),
        # The writer gives a term's footnote as a mark in the term and its
        # text after the list, a pair LaTeX's tagging stops on in a list's
        # label; pdf-target.lua puts it at the head of the definition.
        ("a footnote in a definition list's term is set, at the head of its definition",
         lambda: re.search(r"Elasticity\s*\d+How much", text) is not None
         and "A term" in text),
        # PDF/UA-1 is PDF 1.7: no MathML structure elements, a TeX alt text
        # on each formula, Office's MathML attribute unless pdf.ua1_math is
        # alt, and a /Contents on every link, LaTeX's own included.
        ("a PDF/UA-1 book is PDF 1.7, and veraPDF finds nothing in it",
         lambda: ua1_version == "1.7" and os.path.exists(ua1_path)
         and (not shutil.which("verapdf") and not os.environ.get("VERAPDF") or not ua1_rows)),
        ("its formula has alt text and Office's MathML attribute, and no "
         "MathML structure elements",
         lambda: len(ua1_math) == 1 and ua1_math[0][0] and "/MSFT_Office" in ua1_math[0][1]
         and not ua1_math[0][2]),
        ("every link in it has a /Contents",
         lambda: ua1_links and all(ua1_links)),
        # A one-page book whose heading is its title: no title page, and the
        # heading is its first, at level 1 (title_page: auto).
        ("a one-page book has no title page, and its title is its level-1 heading",
         lambda: "/Title" not in ua1_roles and "/H1" in ua1_roles),
        # The divisions are written between entries, so its one page never
        # reached the main matter: numbered i, its chapter unnumbered.
        ("and its page is in the main matter, numbered 1, 2, 3",
         lambda: os.path.exists(ua1_path) and page_label_styles(ua1_path)[-1:] == ["/D"]),
        ("the run warns that its equations are tagged as PDF/UA-1 allows, "
         "Office's attribute among them",
         lambda: "PDF/UA-1 has no standard way to tag MathML" in ua1_said
         and "Microsoft Office's attribute, which NVDA reads" in ua1_said),
        ("no paragraph element is left empty",
         lambda: not pdfparagraphs.find(pdfparagraphs.pikepdf.open(pdf_path)).doomed),
        ("a captioned table's caption is its Caption, before its rows",
         lambda: shape(table_elements[2]) == ["/Caption", 2, 2, 2]),
        # Pandoc writes an unnumbered table's caption with \LTcaptype set
        # to none, which the caption package stopped on (latexbuild.py).
        ("a table marked unnumbered keeps its caption, with no number",
         lambda: "Cost by year" in text
         and not re.search(r"Table\s*\d+\s*:\s*Cost by year", text)
         and shape(table_elements[8])[:1] == ["/Caption"]),
        # A caption that carries its own label, or an unnumbered figure's:
        # pdf-target.lua sets its figure or table with \OERNoCaptionLabel, and
        # LaTeX gives it no label of its own.
        # Words matched with any space between, pypdf before 5.1 giving a
        # justified line's spaces as two.
        ("a figure's and a long table's caption that carry their own label "
         "aren't numbered again, a figure's too long for one line too",
         lambda: says(text, "Figure 7.3 A red square the book labels itself")
         and says(text, "Table 7.4 Rates the book labels itself")
         and says(text, "Figure 7.5 A red square again")
         and says(text, "Figure 7.7 Two squares side by side")
         and not re.search(r":\s*(Figure\s*7\.[357]|Table\s*7\.4)", text)
         and body.count("{\\OERNoCaptionLabel") == 5),
        # In a table's cell a figure is no float, so LaTeX numbers no caption
        # there, and \OERNoCaptionLabel stopped LaTeX in a longtable's cell
        # ("Misplaced \noalign"); the count of five above leaves them out.
        ("a figure in a table's cell whose caption carries its own label is "
         "left as it is",
         lambda: says(text, "Figure 7.6 A red square in a cell")
         and says(text, "Words beside the figure")
         and not re.search(r":\s*Figure\s*7\.6", text)),
        ("and a figure marked unnumbered gets no number",
         lambda: says(text, "A red square the book leaves unnumbered")
         and not re.search(r"Figure\s*\d+\s*:\s*A\s+red\s+square\s+the\s+book\s+leaves", text)),
        ("and captions that don't carry one keep LaTeX's",
         lambda: re.search(r"Figure\s*1\s*:\s*A small red square", text)
         and re.search(r"Table\s*1\s*:\s*Price by year", text)),
        # LaTeX's caption/label socket gives the label nothing, and the two
        # around it switch paragraph tagging off and on with no Lbl between.
        ("such a figure's Caption holds its words and no Lbl, where the others "
         "hold a Lbl and their words",
         lambda: sorted([kind(k) for k in children(e)] for e in tree
                        if kind(e) == "/Caption"
                        and [kind(k) for k in children(e)][:1] != ["/Div"])
         == [["/Lbl", "/text"], ["/Lbl", "/text"], ["/text"], ["/text"], ["/text"],
             ["/text"]]),
        # Untagged and with no table, so no caption package: LaTeX's classes
        # set its figures, a caption too long for a line as a paragraph.
        ("so in an untagged book with no table, a short caption and a long one, "
         "and one labeled by a word captions.figure_prefixes names",
         lambda: says(untagged_text, "Figure 7.3 A red square the book labels itself")
         and says(untagged_text, "Figure 7.4 A caption the book labels itself")
         and says(untagged_text, "Exhibit 2.1 A red square labeled as an exhibit")
         and not re.search(r":\s*(Figure\s*7\.[34]|Exhibit)", untagged_text)
         and re.search(r"Figure\s*2\s*:\s*A red square with no label", untagged_text)
         and "/StructTreeRoot" not in pypdf.PdfReader(untagged_path).trailer["/Root"]),
        # A box's rule above it leaves LaTeX as a heading does, which took
        # over the \everypar that sets an item's label untagged, and the
        # rule below ends it: a box that opened an item had stopped LaTeX
        # ("perhaps a missing \item").
        ("untagged, a box that opens a list's item, a quotation, or a definition is set, "
         "the item's number beside its first paragraph",
         lambda: re.search(r"1\.\s*Boxed\s+words\s+at\s+the\s+first\s+item", untagged_text)
         and re.search(r"2\.\s*The\s+second\s+item", untagged_text)
         and says(untagged_text, "Boxed words at a quotation")
         and says(untagged_text, "Boxed words at a definition")),
        # Pandoc reads the PDF's images through its resource path, where
        # the run puts its scaled copies first.
        ("images.downsample: the PDF carries an image scaled down to twice the width it's "
         "shown at, and the run says so",
         lambda: (200, 100) in image_pixels(untagged_path)
         and (400, 200) not in image_pixels(untagged_path)
         and "images.downsample 2: 1 of 2 image(s) scaled down" in untagged_said),
        # figures-and-tables.lua's white space with nothing to show: an
        # editor's mark holding nothing but white space, which LaTeX's
        # tagging made an empty Span, and a cell holding a no-break space, a
        # space character in the PDF's text, a row of them a run of spaces
        # (veraPDF's WCAG 2.2 profile, 4.1.2-17 and 1.3.1-2).
        ("a mark holding nothing but white space sets nothing, where it was an empty Span, "
         "and a subscript with something in it is still a Span",
         lambda: (lambda spans: bool(spans) and all(t.strip() for _, t in spans)
                  and (["/sub"], "2") in spans)(
             [(c, t) for k, c, t, _ in deep_texts(pdf_path) if k == "/Span"])),
        ("a cell holding only a no-break space is empty, not a space character, so its row "
         "holds no run of spaces",
         lambda: row_cells(pdf_path, "0.00135") == [["3.0", "0.00135", "", "", ""]]),
        # pdf-target.lua: a figure's pictures in a row, which the pages set
        # side by side (page.css), are one line of pictures in the PDF too,
        # each its share of the line, where they had stood one under another.
        ("two pictures in a figure's row are set side by side, each its share of the line",
         lambda: (lambda shared: len(shared) == 2 and shared[0][1] == shared[1][1]
                  and abs(shared[0][0] - shared[1][0]) > 160)(
             [b for b in image_boxes(reader, "Two squares side by side")
              if abs(b[2] - 0.48 * 345) < 3])),
        # A box, which the pages draw with a border: a rule above it and one
        # below, across the line, each an artifact.
        ("a box is set off by a rule above and one below, across the line, artifacts",
         lambda: "\\OERBoxRule{above}" in source and "\\OERBoxRule{below}" in source
         and source.index("\\OERBoxRule{above}") < source.index("A passage set off in a box")
         < source.index("\\OERBoxRule{below}")
         and artifact_strokes(pdf_path, "A passage set off in a box") == [344, 344]),
        # pdf-target.lua's \OERBlank and latexbuild's PDF_MACROS: a fill-in
        # blank that runs past the end of its line, which TeX can't break,
        # is drawn shorter, its underscores overlapping, to end where the
        # line of 345 points does, its spaces their natural width (3.32
        # points, where TeX had shrunk them to 2.21), and the build doesn't
        # name the line, which LaTeX had reported as too wide; every
        # underscore is in the text still. A blank that fits is left as it
        # is.
        ("a fill-in blank that runs past its line ends where the line does, its spaces "
         "their natural width, and the build doesn't name the line",
         lambda: (lambda found: found is not None and abs(found[0] - 345) < 1
                  and found[1] == 16 and found[2] and found[5] is not None
                  and found[5] > 3.2)(blank_on_line(pdf_path, "Exertion"))
         and not re.search(r"more than 3 points wider[^\n]*appendix", log)),
        ("and every underscore of it is in the text, for a screen reader",
         lambda: "The Rating of Perceived Exertion (RPE) is an example of " + "_" * 16
         in [" ".join(t.split()) for t in pdftext.element_texts(pdf_path, "/text")]),
        ("a blank that fits its line is left as it is",
         lambda: (lambda found: found is not None and found[1] == 18 and not found[2])(
             blank_on_line(pdf_path, "Core nations"))
         and "\\OERBlank{" + "\\_" * 18 + "}" in source),
        ("and underscores in code, a bare address, a picture's description, or a "
         "heading aren't a blank, its bookmark keeping them",
         lambda: "\\texttt{a\\_\\_\\_\\_b}" in source
         and "\\url{https://example.org/fill____in}" in source
         and any(str(f.get("/Alt")) == "A red square over a line to write on, ________"
                 for f in figures)
         and "Fill in the ________" in outline_titles(reader)),
        # LaTeX says so in its log, which Pandoc keeps to itself but for
        # its JSON log of the run.
        ("a line wider than the text is named, a display formula, on its page",
         lambda: re.search(r"WARNING: 1 line\(s\) of the PDF are more than 3 points wider "
                           r"than the text or table column they're set in.*: 1 display "
                           r"formula\(s\); the widest is a display "
                           r"formula on figures, \d+ points too wide", untagged_said)),
        # LaTeX's classes set a caption too long for its line twice, and
        # TextbookImprover's own for a caption without its label, and a
        # footnote's mark in it took a number each time.
        ("and a footnote in a caption too long for its line is numbered once, there and in "
         "one without its label",
         lambda: re.search(r"as\s+this\s+paragraph\s+does\.\s*1", untagged_text)
         and re.search(r"of\s+its\s+own\.\s*2", untagged_text)
         and re.search(r"holds\s+a\s+note\.\s*3", untagged_text)
         and all(re.search(r"(?<!\d)%d\s*The\s+%s\s+note" % (n, word), untagged_text)
                 for n, word in ((1, "first"), (2, "second"), (3, "third")))),
        # A tagged PDF's figure caption is set twice, and an untagged one
        # too long for its line where there's no caption package (latexbuild's
        # \\OERCaptionNotes).
        ("a footnote in a figure's caption is numbered once, a long caption's too, "
         "tagged and untagged: each mark beside its words, numbered in order as its note is",
         lambda: numbered_notes(notes_text, "abc", 1, CAPTION_MARKS)
         and numbered_notes(notes_plain_text, "abc", 1, CAPTION_MARKS)),
        ("and its mark is linked to its note",
         lambda: linked_notes(notes_marks()[:3], "abc", 1)),
        # The list of figures' caption is given, as the writer would make
        # it of the caption without its notes, so it doesn't hold the
        # command, which would set the counter back there.
        ("the list of figures' caption doesn't hold the command, the caption does",
         lambda: re.search(r"\\caption\[[^\]]*OERCaptionNotes", notes_source) is None
         and len(re.findall(r"\\caption\[[^\]]*\]\{\\OERCaptionNotes\{[12]\}",
                            notes_source)) == 2),
        # Written with the cell's text, a minipage's note, lettered, its
        # text taking a number another note had (pdf-target.lua).
        ("a footnote in a table inside a table's cell is numbered among the outer "
         "table's, in order, tagged and untagged, its text after the outer table",
         lambda: numbered_notes(notes_text, "defgh", 4, CELL_MARKS)
         and numbered_notes(notes_plain_text, "defgh", 4, CELL_MARKS)),
        ("and its mark is linked to its note",
         lambda: linked_notes(notes_marks()[3:8], "defgh", 4)),
        ("an untagged PDF of a book with a table with a header column, and one in a "
         "table's cell with a head, is built, as LaTeX stopped on \\tagpdfsetup",
         lambda: os.path.exists(notes_plain) and "Undefined control sequence" not in notes_said),
        # pdf-target.lua: a layout table (role="presentation") tagged
        # table/tagging=div, in a group, only where tagging is; a data table
        # inside one set back to a table, its plugs a table's again.
        ("a layout table is a division of paragraphs, not a table, a data table "
         "inside one a table with its header cells, a caption a paragraph before "
         "it, no table's and unnumbered, the PDF's captions still lined up with "
         "the book's tables, and an untagged book has its words",
         lambda: (lambda steps, year: steps and year
                  and all("/Div" in p and "/Table" not in p and "/TD" not in p for p in steps)
                  and all("/Div" in p and "/TH" in p for p in year))(
             text_paths(notes_path, "Subtract 3 from each side."),
             text_paths(notes_path, "Year"))
         and (lambda caption, steps: caption and steps
              and all(p[-1] in ("/P", "/text") and "/TH" not in p and "/Table" not in p
                      and "/Caption" not in p and "/Div" not in p for p in caption)
              and all("/Div" in p and "/Table" not in p for p in steps))(
             text_paths(notes_path, "Steps to solve"),
             text_paths(notes_path, "Add 1 to each side."))
         and says(notes_plain_text, "Steps to solve")
         and not re.search(r"Table\s+\d+:\s*Steps to solve", notes_text + notes_plain_text)
         and "{\\ifdefined\\tagpdfsetup\\tagpdfsetup{table/tagging=div}\\fi" in notes_source
         and "\\tagpdfsetup{table/tagging=on,table/header-rows={1}}"
             "\\AssignTaggingSocketPlug{tbl/hmode/begin}{Table}" in notes_source
         and "don't line up" not in notes_said
         and says(notes_plain_text, "Subtract 3 from each side.")
         and says(notes_plain_text, "Read the price off the table.")),
        # On the table, the writer gave a layout table's id an empty caption
        # to hold its \label, which LaTeX numbered ("Table 1") in the
        # longtable's head, tagged a header cell with no row.
        ("and its id is an anchor before it, which a link goes to, not an empty "
         "caption LaTeX numbers, tagged or untagged",
         lambda: not re.search(r"Table\s*\d", notes_text + notes_plain_text)
         and (lambda first, second: first is not None and second is not None
              and goes_to(notes_path, "the first steps") == [first]
              and goes_to(notes_path, "the second") == [second])(
             page_holding(notes_path, "Subtract 3 from each side."),
             page_holding(notes_path, "Steps to solve"))),
        # The writer held a data table's id in an empty caption too, which
        # LaTeX numbered, and gave one of class unnumbered no \label at all,
        # so a link to it went nowhere; both ids are anchors before them.
        ("a data table with an id and no caption is numbered by nothing, and "
         "its id is an anchor a link goes to, one the book doesn't number too",
         lambda: not re.search(r"Table\s*\d", notes_text + notes_plain_text)
         and (lambda rates, fees: rates is not None and fees is not None
              and goes_to(notes_path, "the rates") == [rates]
              and goes_to(notes_path, "the fees") == [fees])(
             page_holding(notes_path, "Four percent"),
             page_holding(notes_path, "Five dollars"))),
        # pdf-target.lua: a table whose columns have no widths and whose
        # cells are each a paragraph the writer set in l columns, which
        # don't wrap, and its longer cell ran past the page's edge.
        ("a table whose cells, side by side, are longer than a line wraps "
         "them, a layout table and a data table alike, tagged or untagged",
         lambda: all(says(re.sub(r"-\n", "", text), words)
                     and not any(words in line for line in text.splitlines())
                     for text in (notes_text, notes_plain_text)
                     for words in (WIDE_CELLS[0], WIDE_CELLS[1]))
         and all(any(marker in chunk and "p{(\\linewidth" in chunk.split("\\endhead")[0]
                     for chunk in notes_source.split("\\begin{longtable}"))
                 for marker in ("twelve", "eleven"))),
        # pdf-target.lua: a heading where the writer's sectioning command
        # opened a section LaTeX's tagging couldn't close, every section
        # after a list's tagged inside the list.
        ("a heading inside a list's item, a numbered item, a definition, a "
         "quotation, a table's cell, or a figure is tagged as the heading it is, "
         "where it stands, and one in a footnote, which holds no heading, as a "
         "paragraph",
         lambda: all((lambda paths: len(paths) == 1 and paths[0][-1] == "/H3"
                      and holder in paths[0])(text_paths(notes_path, words))
                     for words, holder in (("Heading in an item", "/itembody"),
                                           ("Heading in a numbered item", "/itembody"),
                                           ("Heading in a definition", "/itembody"),
                                           ("Heading in a quotation", "/quote"),
                                           ("Heading in a cell", "/TD"),
                                           ("Heading in a figure", "/float")))
         and (lambda paths: len(paths) == 1 and paths[0][-1] == "/text"
              and "/footnote" in paths[0])(text_paths(notes_path, "Heading in a note"))),
        ("and the section after them is the chapter's, not inside one of them",
         lambda: (lambda paths: len(paths) == 1 and paths[0][-1] == "/section"
                  and not {"/itemize", "/enumerate", "/description", "/quote",
                           "/Table", "/float", "/footnote"} & set(paths[0]))(
             [p for p in text_paths(notes_path, "A section after them") if "/TOC" not in p])),
        ("a link to the heading inside the list's item goes to it, and an untagged "
         "book has the heading's words",
         lambda: (lambda page: page is not None
                  and goes_to(notes_path, "the heading in the item") == [page])(
             page_holding(notes_path, "Heading in an item"))
         and says(notes_plain_text, "Heading in an item")),
        # pdf-target.lua: a formula's longest word is its longest piece TeX
        # can't break, so a column of reactions, which had counted as one
        # word too wide for a line, wraps; a table whose longest words
        # don't fit a line is set smaller; a table with widths gives a
        # column narrower than its longest word the room it needs; and one
        # too wide in any type keeps its columns, and the build names it.
        ("a table of reactions is set in columns that wrap, its formula a word a piece",
         lambda: "p{(\\linewidth" in head_of(notes_source, "Representative reaction")
         and table_size(notes_source, "Representative reaction") == ""),
        ("a table whose longest words don't fit a line is set in \\small",
         lambda: table_size(notes_source, "Hippopotomonstrosesquippedaliophobia") == "small"),
        ("a table's equal widths give a word too long for its share the room it needs",
         lambda: (lambda reals: len(reals) == 3 and reals[1] > 0.5 and reals[1] == max(reals))(
             [float(r) for r in re.findall(r"\\real\{([\d.]+)\}", head_of(
                 notes_source, "Pneumonoultramicroscopicsilicovolcanoconiosis"))])),
        ("a table too wide in any type keeps its columns, in \\footnotesize, and the "
         "build names it",
         lambda: table_size(notes_source, "242.98") == "footnotesize"
         and "\\begin{longtable}" in notes_source and "p{(" not in head_of(notes_source, "242.98")
         and re.search(r"WARNING: \d+ line\(s\) of the PDF are more than 3 points wider[^\n]* "
                       r"in table\(s\)", notes_said)),
        # A line too wide in the contents or the list of figures is reported
        # by TeX at a line of the list's own file; the build names it as the
        # list's (PDF_MACROS marks where each list is set).
        ("a line too wide in the contents or the list of figures is named as the list's",
         lambda: re.search(r"WARNING: [^\n]* 1 in the contents\b", notes_said)
         and re.search(r"WARNING: [^\n]* 1 in a list of figures or tables\b", notes_said)),
        # A blank on a line too wide that doesn't reach the line's end is
        # left as it is, and one that reaches past it with too little of it
        # before the margin is drawn three underscores wide, no shorter.
        ("a blank on a line too wide that doesn't reach the line's end is left as it is",
         lambda: (lambda found: found is not None and found[1] == 8 and not found[2])(
             blank_on_line(notes_path, "3141592653589793238462643383279502884197169399"))),
        ("and one with too little room before the margin is drawn no shorter than "
         "three underscores",
         lambda: (lambda found: found is not None and found[1] == 4 and found[2]
                  and abs(found[3] - 3 * found[4]) < 0.05)(
             blank_on_line(notes_path, "2718281828459045235360287471352662497757247093"))),
        ("and a blank underlined, struck out, or highlighted isn't marked, lua-ul drawing "
         "its line first",
         lambda: all("\\%s{%s}" % (command, "\\_" * 16) in notes_source
                     for command in ("ul", "st", "hl"))),
        # figures-and-tables.lua: a layout table's head rows are body rows,
        # since LaTeX's tagging made a longtable's head header cells even
        # tagged as a division, a TH outside any TR, which PDF/UA-2 rejects
        # (ISO 32005, Sect-TH), as a Word table's repeating header row read.
        ("a layout table's head is rows like the others, no header cells",
         lambda: (lambda head, body: head and body
                  and all("/Div" in p and "/TH" not in p and "/Table" not in p
                          for p in head + body))(
             text_paths(notes_path, "Diploma in game design"),
             text_paths(notes_path, "Certificate in illustration"))),
        ("a table whose first header row is one spanning cell, with no "
         "caption, keeps that row",
         lambda: shape(table_elements[3])[:2] == [1, 2]
         and "/Caption" not in shape(table_elements[3])),
        ("no table holds an empty artifact",
         lambda: not any(kind(k) == "/Artifact" for t in table_elements for k in children(t))),
        # pdf.figures in_place: H, so the tags stay where the text has them,
        # not gathered in a container at the end of the document.
        ("pdf.figures section flushes each section's figure tags, and lets "
         "figures float within it",
         lambda: "float/flush=section" in placements["section"]
         and "\\usepackage[section]{placeins}" in placements["section"]
         and "floatplacement" not in placements["section"]),
        ("pdf.figures float leaves LaTeX's placement alone",
         lambda: not any(word in placements["float"] for word in
                         ("floatplacement", "placeins", "float/flush"))),
        ("and the default keeps figures in place",
         lambda: "\\floatplacement{figure}{H}" in source),
        ("each figure's tags sit where the text has it",
         lambda: figures and not inside(tree, "/figures", "/Figure")),
        ("the described image is a figure with its alt text",
         lambda: any(str(f.get("/Alt")) == "A small red square"
                     for f in figures)),
        ("the decorative image is no figure",
         lambda: len(figures) == 10),
        # Each inner figure's empty \caption{} was the float's too, three
        # Captions in one Aside, which veraPDF rejects (ISO 14289-2,
        # 8.2.5.27).
        # Set side by side, the two pictures are one line, a paragraph of
        # the float's.
        ("two pictures side by side in a figure, each a figure in a row, are one figure "
         "with one caption, its first or last element",
         lambda: (lambda floats: len(floats) == 1
                  and [kind(e) for e in elements(floats[0])].count("/Figure") == 2
                  and [kind(k) for k in children(floats[0])].count("/Caption") == 1
                  and [kind(k) for k in children(floats[0])].index("/Caption")
                  in (0, len(children(floats[0])) - 1))(
             [e for e in tree if kind(e) in ("/Aside", "/float")
              and any(str(k.get("/Alt")) == "A left red square" for k in elements(e))])),
        ("and the two are in one paragraph, a line of the float's",
         lambda: any(kind(e) in ("/P", "/text-unit")
                     and [str(k.get("/Alt")) for k in elements(e) if kind(k) == "/Figure"]
                     == ["A left red square", "A right green square"] for e in tree)),
        # Its width, 800 pixels, is 600 points at the writer's 96 an inch,
        # and the decorative rule's 675: no wider than the line now.
        ("an image whose width is wider than the line is scaled to fit it, "
         "a decorative one too",
         lambda: len(re.findall(r"\\protect\\pandocbounded\{\\includegraphics\[width=[\d.]+in,",
                                source)) == 2
         and 0 < max(image_widths(reader))
         <= 0.75 * float(reader.pages[0].mediabox.width)),
        ("an image with no alt text is reported by the output check",
         lambda: [r["Check"] for r in pdf_rows].count(
             "pdf-figure-alt-is-file-name") == 1),
        # By the rules a deck's pictures are judged by (alttext.py).
        ("and one whose alt text says nothing, a camera's name for a file",
         lambda: [(r["Check"], r["Detail"]) for r in pdf_rows
                  if r["Check"] == "pdf-figure-alt-is-placeholder"]
         == [("pdf-figure-alt-is-placeholder", "IMG_2041")]),
        # NVDA announces no column header for a cell holding only a
        # formula, and announces the words beside one (round 5).
        ("a header cell holding only a formula is reported, in the PDF and on its "
         "page, and one with words beside its formula isn't",
         lambda: [r["Check"] for r in pdf_rows].count("pdf-table-header-is-formula") == 1
         and [r["Check"] for r in rows if r.get("Kind") == "html"].count(
             "table-header-is-formula") == 1),
        ("a link with a description reads its text, then the description",
         lambda: by_uri.get("https://doi.org/10/b8xx35")
         == "https://doi.org/10/b8xx35 (Crandall 2019 via doi.org)"),
        ("a link without one reads its text",
         lambda: by_uri.get("https://example.org/") == "a plain link"),
        ("a link within the book reads its text",
         lambda: "the first section" in goto),
        # The footnote mark, and the contents lines, are links LaTeX
        # makes itself; the reset keeps the last description off them.
        ("a link LaTeX makes on its own gets no /Contents",
         lambda: goto.count(None) >= 1
         and all(c in (None, "the first section") for c in goto)),
        # Latin Modern has no Greek; without the fallback font these are
        # drawn blank.
        ("Greek and symbols written as text are in the PDF's text",
         lambda: all(c in text for c in "αβγ≤≈")),
        # pypdf reads the squares from TeX's AMS font by its glyph names; the
        # font's ToUnicode, which a screen reader and pdftotext go by, maps
        # them to control characters once the formula's MathML is made. So
        # the check is that no square is drawn from that font at all.
        ("amssymb's squares, which unicode-math has no names for, are the characters "
         "they are, from the OpenType math font, not TeX's AMS font",
         lambda: "□" in text and "■" in text and not any(
             "MSAM" in name or "MSBM" in name for name in font_names(reader))),
        # The one character no fallback has is reported once, in a line
        # of its own, rather than as one warning per occurrence.
        ("a character no font has is reported in one line, with its code",
         lambda: [line for line in log.splitlines()
                  if "missing from the PDF" in line]
         == [line for line in log.splitlines() if "U+6F22" in line]
         and log.count("missing from the PDF") == 1
         and "Missing character" not in log),
        # An eqnarray* among them, which the writer wrapped in \[ \] and
        # LaTeX stopped on, before pdf-target.lua wrote it as it is; and a
        # \pmb, on which LuaTeX's tagging of the formula stopped.
        ("every formula, an eqnarray* and a \\pmb among them, has MathML structure "
         "elements and a MathML file",
         lambda: len(formulas) == 9
         and all("/AF" in f for f in formulas)
         and "/math" in kinds),
        # LaTeX stopped on a matrix's & in a cell or a caption, which TeX
        # took for the table's while the tagging read the formula whole.
        ("a formula with an alignment in a table's cell, and in its caption, "
         "is a Formula there",
         lambda: len(inside(tree, "/TD", "/Formula")) == 1
         and len(inside(tree, "/Caption", "/Formula")) == 1),
        # Once each in the whole file: the template's own are switched
        # off, the book opens in the front matter from the preamble, and
        # the source's \frontmatter and \appendix are dropped.
        ("each division command is written once, from the roles",
         lambda: [division(c) for c in ("\\frontmatter", "\\mainmatter",
                                        "\\appendix", "\\backmatter")]
         == [1, 1, 1, 0]),
        # The class decides whether level 1 is a chapter, and the writer
        # reads the class from the metadata by its text.
        ("a page at the top of contents is a chapter",
         lambda: "\\chapter{One}" in body
         and "\\chapter{Tables of Values}" in body),
        ("the contents sit in the front matter, where contents puts them",
         lambda: body.index("Preface") < body.index("\\tableofcontents")
         < body.index("\\mainmatter") < body.index("{One}")),
        ("the page the metadata file made has no heading of its own",
         lambda: "The Test Book" not in outline_titles(reader)
         and {"Preface", "Acknowledgements"} <= set(outline_titles(reader))),
        # pdf.toc_depth counts as the EPUB's contents do, LaTeX's tocdepth
        # a chapter as 0: at 2, a page's subsections had come in too.
        ("the contents and the bookmarks go as deep as pdf.toc_depth says, "
         "a page and its sections and not their subsections",
         lambda: {"One", "First", "After the run-in headings"} <= set(outline_titles(reader))
         and "Deep" not in outline_titles(reader)
         and says(contents_page, "First") and not says(contents_page, "Deep")),
        # A roman i on the title page and again on the preface was what
        # the template's \mainmatter before a front page produced.
        ("no page label is used twice",
         lambda: len(reader.page_labels) == len(set(reader.page_labels))),
    ]

    items += footer_checks(footer_path)
    items += sized_checks(sized_path, sized_said)
    items += fancy_checks(fancy_path)
    items += default_checks(default_path)
    items += preamble_checks(preamble_path, preamble_source, preamble_said)
    items += aaa_checks(aaa_path)
    if verapdf_ran:
        # The one character no font has is drawn as .notdef, which
        # veraPDF reports, and that's the only rule it finds failed.
        items.append(("veraPDF finds only the character no font has",
                      lambda: {r["Check"] for r in pdf_rows
                               if r["Tool"] == "verapdf"}
                      == {"verapdf:8.4.5.9-1"}))
        items.append(("and so the claims aren't reported as unverified",
                      lambda: not [r for r in pdf_rows if r["Check"]
                                   == "pdf-claims-unverified"]))
        items.append(("veraPDF finds nothing in the notes book's tagged PDF",
                      lambda: os.path.exists(notes_path) and not pdfcheck.run_verapdf(
                          outputcheck.find_validator("verapdf"), notes_path)))
    else:
        print("  skip  veraPDF not found (set VERAPDF); its verdict is "
              "not checked")
    # The fallbacks' last, when it's installed (build-pdf.py).
    if font_installed("NewCMMath-Book.otf"):
        items.append(("a circled letter, which of the fallbacks only New Computer "
                      "Modern's math font has, is in the PDF's text",
                      lambda: "\u24d0" in text))
    else:
        print("  skip  New Computer Modern isn't installed; the circled letter "
              "it would supply isn't checked")
    # Pandoc's highlighted code, its tokens colored: a space beside a
    # color's change was no character, and an indentation one
    # (latexbuild.CODE_SPACES).
    items.append(("a highlighted code block's spaces are characters, its "
                  "indentation kept",
                  lambda: pdftext.code_lines(pdf_path)[-5:-3]
                  == ["def demand(p):", "    return 12 - 2 * p > 0"]))
    # LaTeX's tagged footnote takes its text as an argument, where a code
    # block's verbatim can't be read; footnote-code.lua writes each to a
    # file of its own, read where it stood.
    items.append(("a code block in a footnote is set in its note, highlighted or not, "
                  "its lines and spaces kept",
                  lambda: pdftext.code_lines(pdf_path)[-3:]
                  == ["def supply(p):", "    return 2 * p  # 100%", "q   = 10"]
                  and len(inside(tree, "/footnote", "/codeline")) == 3))
    # In the theme every writer is given (lib/highlighting.py), whose
    # colors clear 4.5:1 where pygments' didn't: a number in the text's
    # code, a comment in a footnote's.
    with open(highlighting.THEME, encoding="utf-8") as fh:
        theme = json.load(fh)["text-styles"]
    items.append(("highlighted code is drawn in the theme's colors, a number in the text's "
                  "code and a comment in a footnote's",
                  lambda: {latex_color(theme["DecVal"]["text-color"]),
                           latex_color(theme["Comment"]["text-color"])} <= fill_colors(reader)))
    return items


def main():
    parser = argparse.ArgumentParser(
        description="Check the pdf target against a small Markdown book.")
    parser.add_argument("--keep", action="store_true",
                        help="leave the built output in place")
    parser.add_argument("-j", "--jobs", type=int, default=parallel.default_jobs(),
                        metavar="N", help="with 2 or more, build the two books at "
                        "once (default: half the processors, "
                        f"{parallel.default_jobs()} here)")
    arguments = parser.parse_args()

    if shutil.which("pandoc") is None:
        sys.exit("pandoc is not on the path.")
    version = subprocess.run(["pandoc", "--version"], capture_output=True,
                             text=True).stdout.split()[1]
    if tuple(int(p) for p in re.findall(r"\d+", version)[:3]) < (3, 9):
        sys.exit(f"Pandoc {version} is too old; these tests need 3.9 or "
                 "later, as convert.py does.")
    if shutil.which("lualatex") is None or pypdf is None or pdfparagraphs.pikepdf is None:
        print("  skip  " + ("lualatex is not on the path"
                            if shutil.which("lualatex") is None
                            else "pypdf is not installed" if pypdf is None
                            else "pikepdf is not installed, and the PDF's repairs need it")
              + "; the pdf target is not checked")
        print("\nall PDF checks skipped")
        return 0

    # A LaTeX too old to tag is a machine to set up, not a failure of the
    # target: build-pdf.py refuses it (run-convert-tests.py checks that),
    # and this suite says why it can't run.
    spec = importlib.util.spec_from_file_location(
        "build_pdf", os.path.join(BIN, "build-pdf.py"))
    build_pdf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_pdf)
    problem = build_pdf.latex_problem()
    if problem:
        print(f"  skip  {problem}")
        print("\nall PDF checks skipped")
        return 0

    work = tempfile.mkdtemp(prefix="pdf-tests-")
    failed = 0
    missing = tex_missing()
    if missing:
        import latexbuild
        print("  FAIL  TeX has the packages the suite's books load, or the checks that build "
              "them fail: missing " + ", ".join(missing) + " ("
              + latexbuild.tlmgr_command("install " + " ".join(missing)) + ")")
        failed += 1
    try:
        try:
            items = checks(work, arguments.jobs)
        except Exception as exc:
            print(f"  ERROR building the book: {exc}")
            return 1
        for name, predicate in items:
            try:
                passed = predicate()
            except Exception as exc:
                passed, name = False, f"{name}  ({exc})"
            print(("  ok    " if passed else "  FAIL  ") + name)
            failed += not passed
    finally:
        # The PDF/UA-1, untagged, notes, footer, sized, fancy, default,
        # preamble, and AAA books are built beside the book (build_ua1,
        # build_untagged, build_notes, build_footer, build_sized,
        # build_fancy, build_default, build_preamble, build_aaa).
        if arguments.keep:
            print(f"\nOutput left in {work}, {work}-ua1, {work}-untagged, {work}-notes, "
                  f"{work}-footer, {work}-sized, {work}-fancy, {work}-default, "
                  f"{work}-preamble, and {work}-aaa")
        else:
            shutil.rmtree(work, ignore_errors=True)
            shutil.rmtree(work + "-ua1", ignore_errors=True)
            shutil.rmtree(work + "-untagged", ignore_errors=True)
            shutil.rmtree(work + "-notes", ignore_errors=True)
            shutil.rmtree(work + "-footer", ignore_errors=True)
            shutil.rmtree(work + "-sized", ignore_errors=True)
            shutil.rmtree(work + "-fancy", ignore_errors=True)
            shutil.rmtree(work + "-default", ignore_errors=True)
            shutil.rmtree(work + "-preamble", ignore_errors=True)
            shutil.rmtree(work + "-aaa", ignore_errors=True)
    print(f"\n{failed} check(s) failed" if failed
          else "\nall PDF checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
