#!/usr/bin/env python3
"""
run-pdf-tests.py -- check the pdf target against a small Markdown book.

    python3 tests/run-pdf-tests.py           # run every check
    python3 tests/run-pdf-tests.py --keep    # leave the output in place

Needs Pandoc 3.9 or later, LuaLaTeX with LaTeX's tagging code (TeX Live
2026 or later; see docs/installation.md) and the packages the PDFs load
(PDF_TEX, SUITE_TEX), and pypdf and pikepdf to read the result. Without any of
them, or with a LaTeX too old, it says which and skips, as a machine to
set up; veraPDF, when found through VERAPDF or on the path, is run by the
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
figure, or a footnote tagged where it stands, the default page
(bin/pdf-layout.yaml), which a metadata file changes a field at a time,
its rag reaching footnotes and captions, and a table or a formula too
wide for its line fitted to it as LaTeX measures it. The book is small
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
import glob
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

# Latin Modern's faces, named, as a metadata file keeps them where the
# default's are IBM Plex's (build-pdf.py's FAMILIES): the faces the checks
# of the book, the notes book, the fit book, and the two-column book were
# measured in, where a line's words, a table's widths, and a formula's are
# Latin Modern's, and the untagged book's, whose checks read its text as
# pypdf 4.0.2 gives it (build_untagged). The default book, the footer,
# sized, fancy, preamble, AAA, bars, and languages books are in the
# default's faces.
LATIN_MODERN = ("mainfont: Latin Modern Roman\nsansfont: Latin Modern Sans\n"
                "monofont: Latin Modern Mono\nmathfont: Latin Modern Math\n")

# The book class's own page, where the PDF target's default would have
# its own (bin/pdf-layout.yaml): 10pt type, justified, in the class's
# margins, which the checks of the book and the notes book measure lines
# 345 points long in, in Latin Modern, Pandoc's own face. The footer book
# and the default book, the book again, have the default page, and the
# sized book the default as a metadata file changes it.
CLASS_PAGE = ("fontsize: 10pt\ngeometry: []\nlinestretch: 1\nragged-right: false\n"
              + LATIN_MODERN)

FRONT = r"""---
title: The Test Book
subtitle: A book for checking the PDF target
""" + CLASS_PAGE + r"""---

\frontmatter

# Preface

This preface points to [the first section](one.html#first) and cites
[https://doi.org/10/b8xx35](https://doi.org/10/b8xx35 "Crandall 2019 via doi.org"),
then [a plain link](https://example.org/).[^n]

An address whose path names its language, <https://example.org/lang--en/q?`x>,
is its own description.

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

![A cell\'s nucleus, its \|bar\|, 1 < 2 > 0, x\~y, a\\b, x\^2, “quoted” and ‘single’ it’s 1–5 a—b, and \-\- as typed](assets/red.png)

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

Markup = price less cost
:   An equals sign in a term, which LaTeX's tagging read as keys.

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

The terms ____ and ________ are often used interchangeably, the words
after each blank still in the paragraph.

And underscores in code, which aren't a blank: `a____b`. And in a bare
address, <https://example.org/fill____in>, and a picture's description:
![A red square over a line to write on, ________](assets/red.png).
"""

# An untagged book, built to no PDF/UA standard, with figures and no
# table, so no caption package: its figures are set by LaTeX's classes.
# And boxes that open a list's item, a quotation, and a definition, whose
# label LaTeX sets untagged from \everypar, which a box's rule had taken
# over.
# A drawing in LaTeX's picture mode, a circle asked for at 80 points,
# which LaTeX's lcircle10 font draws at 40, its largest, and pict2e at 80
# with a path: in the preamble book, drawn with pict2e (picture_paths, on
# by default), and in the untagged book, whose target turns it off.
PICTURE = ("```{=latex}\n\\setlength{\\unitlength}{1pt}\\begin{picture}(90,90)"
           "\\put(45,45){\\circle{80}}\\end{picture}\n```\n")
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

A formula too wide for the paper even in type half its size, which LaTeX
can't break:

$$y_{0}+y_{1}+y_{2}+y_{3}+y_{4}+y_{5}+y_{6}+y_{7}+y_{8}+y_{9}+y_{10}+y_{11}+y_{12}+y_{13}+y_{14}+y_{15}+y_{16}+y_{17}+y_{18}+y_{19}+y_{20}+y_{21}+y_{22}+y_{23}+y_{24}+y_{25}+y_{26}+y_{27}+y_{28}+y_{29}+y_{30}+y_{31}+y_{32}+y_{33}+y_{34}+y_{35}+y_{36}+y_{37}+y_{38}+y_{39}+y_{40}+y_{41}+y_{42}+y_{43}+y_{44}+y_{45}+y_{46}+y_{47}+y_{48}+y_{49}+y_{50}+y_{51}+y_{52}+y_{53}+y_{54}+y_{55}+y_{56}+y_{57}+y_{58}+y_{59}$$

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

A circle in picture mode:

""" + PICTURE

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

![A figure whose caption has [a linked word](https://example.org/caption) and [one within](#captions) in it.](assets/red.png)

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

And a worked example's steps as the CNX unpacker lays them out, columns of formulas beside a column of their reasons, longer than a line together, and steps that fit their line:

<table role="presentation" class="formula-steps"><tr><td style="text-align: right">$1234 + \frac{5678}{9012} + \frac{3456}{7890}$</td><td style="text-align: center">$=$</td><td style="text-align: left">$\frac{15924}{2468} + \frac{1357}{2468} + 1111$</td><td style="text-align: left">Collect the numbers that came before into one sum, carrying the others along as they were.</td></tr><tr><td style="text-align: right"></td><td style="text-align: center">$=$</td><td style="text-align: left">$29738$</td><td style="text-align: left">Add them.</td></tr></table>

<table role="presentation" class="formula-steps"><tr><td style="text-align: right">$\frac{12}{34} + \frac{56}{78}$</td><td style="text-align: center">$=$</td><td style="text-align: left">$\frac{2143}{6587} + \frac{4321}{8765}$</td><td style="text-align: left">Add the fractions together into one.</td></tr><tr><td style="text-align: right"></td><td style="text-align: center">$=$</td><td style="text-align: left">$\frac{9876}{5432}$</td><td style="text-align: left">Simplify it.</td></tr></table>

And four whose longest words, side by side, are wider than a line, or
wider than the columns their widths give them: a column of reactions,
which TeX breaks at their relations and operators; two words the filter
counts as too long for a line together, which fit it; a word too long
for an equal share of a table whose cell of two paragraphs gives it
equal widths; and a table of numbers too wide for a line:

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

```{=latex}
\newcommand{\arc}[1]{\overset{\frown}{#1}}
```

Terms struck out, as a worked example cancels them:
$\frac{\cancel{3}x}{\cancel{3}} = x$, $\bcancel{y}$, and $\xcancel{2z}$; and an
arc, $\arc{AB}$, by a command the book defines, named as one of pict2e's.

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

An address LaTeX links on its own, \url{https://example.org/lang--en/q?`x}.

[^1]: The note, with [a link in it](https://example.org/note).
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
        with open(report, encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
    return os.path.join(work, "pdf", "org.example.ua1.pdf"), converted.stdout + converted.stderr, rows


def build_untagged(work):
    """A book built to no PDF/UA standard, UNTAGGED_PAGE, in Latin Modern
    (LATIN_MODERN), since pypdf 4.0.2, Ubuntu 24.04's, runs the words of
    its text together in IBM Plex, as it does the notes book's untagged
    copy's (build_notes): (the PDF's path, what the run said)."""
    os.makedirs(os.path.join(work, "assets"))
    png(os.path.join(work, "assets", "red.png"), (200, 0, 0))
    noise_png(os.path.join(work, "assets", "wide.png"), 400, 200)
    with open(os.path.join(work, "figures.md"), "w", encoding="utf-8") as fh:
        fh.write(UNTAGGED_PAGE)
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  title: No Standard\n  identifier: org.example.untagged\n"
                 "  language: en-US\n")
    with open(os.path.join(work, "meta.yaml"), "w", encoding="utf-8") as fh:
        fh.write(LATIN_MODERN)
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("defaults:\n  captions:\n    figure_prefixes: [Figure, Exhibit]\n"
                 "  images:\n    downsample: 2\n"
                 "targets:\n  pdf:\n    format: pdf\n    picture_paths: \"off\"\n"
                 "    pdf:\n      standard: []\n      metadata: meta.yaml\n")
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


# A book in en-US with a page in French and a chapter whose opening page is
# in French, its title the chapter's, after which a page in the book's
# language: each page in its own language (build-pdf.py's in_language).
LANGUAGE_PAGES = {
    "un.md": "---\ntitle: Un\nlang: fr\n---\n\nUne phrase en français.\n",
    "two.md": "---\ntitle: Two\n---\n\nA sentence in the book's own language.\n",
    "chapitre.md": "---\ntitle: Le chapitre\nlang: fr\n---\n\nLe début du chapitre.\n",
    "suite.md": "---\ntitle: Suite\n---\n\nMore in the book's own language.\n",
}


def build_languages(work):
    """LANGUAGE_PAGES built: the PDF's path."""
    os.makedirs(work)
    for name, text in LANGUAGE_PAGES.items():
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  title: Languages\n  identifier: org.example.languages\n"
                 "  language: en-US\n  contents:\n    - two\n    - un\n"
                 "    - title: Le chapitre\n      items:\n        - chapitre\n"
                 "        - suite\n")
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  pdf:\n    format: pdf\n")
    subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick"], cwd=work,
                   capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return os.path.join(work, "pdf", "org.example.languages.pdf")


def language_checks(path):
    declared = languages(path) if os.path.exists(path) else []
    with pikepdf_open(path) as pdf:
        catalog = str(pdf.Root.get("/Lang", "")) if pdf is not None else ""
    return [
        ("a page in another language than the book's is in its own, its heading's words and "
         "its text, the book's catalog the book's",
         lambda: catalog == "en-US"
         and any(s == "/Span" and lang == "fr" and text == "Un" for s, lang, text, _ in declared)
         and any(lang == "fr" and text == "Une phrase en français." for _, lang, text, _
                 in declared)),
        ("and so is a chapter's opening page in another language, the chapter's heading its "
         "title, the page after it in the book's",
         lambda: any(s == "/Span" and lang == "fr" and text == "Le chapitre"
                     for s, lang, text, _ in declared)
         and any(lang == "fr" and text == "Le début du chapitre." for _, lang, text, _
                 in declared)
         and [(lang, above) for _, lang, text, above in declared if "own language" in text]
         and all(lang is None and above is None
                 for _, lang, text, above in declared if "own language" in text)),
    ]


def pikepdf_open(path):
    """The PDF at path opened with pikepdf, or a context giving None."""
    import contextlib
    if not os.path.exists(path):
        return contextlib.nullcontext(None)
    return pdftext.pikepdf.open(path)


def build_notes(work):
    """NOTES_CAPTIONS, NOTES_CELLS, and NOTES_HEADINGS, built tagged, to
    PDF/UA-2, with a list of figures, and untagged, on the default page,
    each in Latin Modern (LATIN_MODERN): (the tagged PDF's path, the
    untagged one's, what the run said, the tagged one's LaTeX). pypdf's
    text of an untagged PDF in IBM Plex runs its words together, which
    pdftotext's and MuPDF's don't: such a PDF draws no spaces, and pypdf
    finds them by the gaps."""
    os.makedirs(os.path.join(work, "assets"))
    png(os.path.join(work, "assets", "red.png"), (200, 0, 0))
    for name, text in (("captions.md", NOTES_CAPTIONS), ("cells.md", NOTES_CELLS),
                       ("headings.md", NOTES_HEADINGS),
                       ("meta.md", "---\nlof: true\n" + CLASS_PAGE + "---\n"),
                       ("plain.md", "---\n" + LATIN_MODERN + "---\n")):
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  title: Notes\n  identifier: org.example.notes\n"
                 "  language: en-US\n  contents:\n    - captions\n    - cells\n    - headings\n")
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  pdf:\n    format: pdf\n    pdf:\n      metadata: meta.md\n"
                 "  plain:\n    format: pdf\n    pdf:\n      standard: []\n"
                 "      metadata: plain.md\n")
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
# the book's fontsize, which scrextend sets. And a face of its own, IBM
# Plex Serif, an OpenStax book's, named by its files as the unpacker names
# it, with the fallback fonts the default's have: a character it lacks,
# an arrow, had been left out.
FANCY_FOOTER = "## License\n\nShared under [the license](license.md).\n"
FANCY_ARROW = "\nIf it rains, the ground is wet: rain ⇒ wet.\n"
FANCY_LAYOUT = ("mainfont: IBMPlexSerif\nmainfontoptions:\n  - Extension=.otf\n"
                "  - UprightFont=*-Regular\n  - BoldFont=*-Bold\n  - ItalicFont=*-Italic\n"
                "  - BoldItalicFont=*-BoldItalic\n"
                "classoption: [oneside, 13.5pt, a4paper]\ngeometry: []\n"
                "header-includes:\n  - |\n    ```{=latex}\n"
                "    \\usepackage[twoside]{fancyhdr}\n"
                "    \\pagestyle{fancy}\n    \\fancyhf{}\n    \\fancyfoot[LE,RO]{\\thepage}\n"
                "    \\renewcommand\\headrulewidth{0pt}\n"
                "    \\fancypagestyle{plain}[fancy]{}\n    ```\n")


def build_fancy(work):
    """FOOTER_ONE and FOOTER_TWO with FANCY_ARROW, with FANCY_FOOTER's
    footer, from a file, on FANCY_LAYOUT's pages: (the PDF's path, what
    the run said)."""
    os.makedirs(work)
    for name, text in (("one.md", FOOTER_ONE), ("two.md", FOOTER_TWO + FANCY_ARROW),
                       ("footer.md", FANCY_FOOTER), ("fancy.yaml", FANCY_LAYOUT)):
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  title: Fancy\n  identifier: org.example.fancy\n"
                 "  language: en-US\n  contents:\n    - one\n    - two\n")
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("defaults:\n  footer: footer.md\n"
                 "targets:\n  pdf:\n    format: pdf\n    pdf:\n      metadata: fancy.yaml\n")
    converted = subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick"],
                               cwd=work, capture_output=True, text=True,
                               stdin=subprocess.DEVNULL)
    return os.path.join(work, "pdf", "org.example.fancy.pdf"), \
        converted.stdout + converted.stderr



# A book written for a Pandoc PDF build, its metadata file loading the
# packages for its own margins and line spacing, as Pandoc's own page
# left a book to: the default page's margins and line spacing, which load
# geometry and setspace first, had stopped LaTeX ("Option clash for
# package geometry"), and undone a spacing the file set. And no contents
# page, as such a book may have none: Pandoc's template sets LaTeX's
# tocdepth, which the bookmarks follow, only where it writes the contents,
# so a page's subsections had bookmarks too. And a math font of its own, a
# monospaced face with fallbacks of its own, and no face for the text: the
# template sets each before the default's text face, scaled to Latin
# Modern's small letters, and build-pdf.py sets each again after it, with a
# scale, without which fontspec kept the size it had worked out (formulas
# a sixth smaller than the text).
PREAMBLE_META = ("---\ntoc: false\nmathfont: IBMPlexMath-Regular.otf\n"
                 "monofont: Latin Modern Mono\nmonofontfallback:\n"
                 "  - \"IBMPlexMono-Regular.otf:mode=harf;\"\nheader-includes:\n"
                 "  - |\n    ```{=latex}\n"
                 "    \\usepackage[margin=1.5in]{geometry}\n"
                 "    \\usepackage[doublespacing]{setspace}\n    ```\n---\n")
PREAMBLE_TWO = ("# Two\n\nThe second chapter.\n\n## Its section\n\nThe section, and its "
                "formula, $x + y = z$, and its code, `x = y`.\n\n" + PICTURE + "\n"
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


# Tables and formulas too wide for their lines, on the default page, which
# latexbuild's FIT_MACROS fits as LaTeX measures them, each named by the
# first cell of its row of numbers or the first word of its formula: first
# a paragraph whose lines run on before a display formula in it; then a
# table that narrower spaces between its columns fit; one that needs
# smaller type as well; one whose smaller type is Latin Modern's design for
# 9 points, 5 percent wider for its size than the 12-point design, which
# leaves it 2 percent too wide; one too wide even at three quarters of its
# type, centered on the page; one too wide for the paper at that size, set
# smaller still; one too wide for the paper even at half its type, which
# the build warns of, of more columns than pdf-target.lua's count of a line
# can space, and after it a table of the class float, which the writer
# sets as a tabular in a table float, not a longtable; one whose head is a
# cell across its columns, which longtable measures too wide on the first
# run; one of formulas, whose math in smaller type is set in the forms for
# subscripts, wider, so that its first fit leaves it too wide; one whose
# columns wrap; one whose columns' widths are given, a word too long for
# its column, which the filter counts as fitting it; one whose columns'
# widths are given, a formula TeX can't break too wide for its column,
# opening a line of its cell; one whose formula, too wide for its
# column, opens a line and breaks after an operator; one whose columns'
# widths are more than its line together, a line of words in a cell
# before one a formula opens; a layout table, its
# caption a paragraph before it; one of 45 columns whose widths are given,
# the spaces between them more than its line; and one of 22 columns whose
# longest words are wider than a line together, its corner's words
# wrapping.
# Then display formulas likewise, one wide by its spaces, each three quads
# (54mu), and a numbered one; and a worked example's steps, an array in
# text.
FIT_NUMBERS = ("161.45", "199.50", "215.71", "224.58", "230.16", "233.99", "236.77",
               "238.88", "240.54", "241.88", "242.98", "243.91", "244.69", "245.36",
               "245.95", "246.46")


def fit_table(name, values, head=None):
    """An HTML table of values, its head the column numbers or head, its
    row's first cell name."""
    head = head or ("<tr><th>Degrees</th>"
                    + "".join("<th>%d</th>" % (i + 1) for i in range(len(values))) + "</tr>")
    return ("<table><thead>" + head + "</thead><tbody><tr><td>" + name + "</td>"
            + "".join("<td>%s</td>" % v for v in values) + "</tr></tbody></table>\n\n")


def fit_terms(count):
    """A sum of count terms, a formula TeX breaks nowhere in a display."""
    return " + ".join("a_{%d}x^{%d}" % (i, i) for i in range(1, count + 1))


# Twelve functions' names: formula_width counts each by its letters and
# the space beside it, cell_size's formula_length as a character.
TRIG_TERMS = " ".join(["\\sin x", "\\cos x", "\\tan x", "\\cot x", "\\sec x", "\\csc x"] * 2)


# A row of a matrix of ten columns, amsmath's most, 451 points wide in the
# default page's type; and eighteen numbers, 683 points wide summed.
MATRIX_ROW = ["123456", "234567", "345678", "456789", "567891", "678912", "789123", "891234",
              "912345", "102345"]
FIT_NUMBERS_STEPS = ["1111", "2222", "3333", "4444", "5555", "6666", "7777", "8888", "9999", "1212",
                     "2323", "3434", "4545", "5656", "6767", "7878", "8989", "9191"]


def fit_steps(first, relation, second, reason):
    """A worked example's steps as the CNX unpacker lays them out, a layout
    table of the class formula-steps: first, relation, and second, and the
    step's reason; then the relation and 29738, and a short reason."""
    return ('<table role="presentation" class="formula-steps"><tr>'
            '<td style="text-align: right">$%s$</td><td style="text-align: center">$%s$</td>'
            '<td style="text-align: left">$%s$</td><td style="text-align: left">%s</td></tr>'
            '<tr><td style="text-align: right"></td><td style="text-align: center">$%s$</td>'
            '<td style="text-align: left">$29738$</td><td style="text-align: left">Add them.</td>'
            '</tr></table>\n\n' % (first, relation, second, reason, relation))


FIT_ONE = (
    "# Fitting\n\nLeadpara, a paragraph whose lines run on before a display formula in it too "
    "wide for its line, the lines spaced as the text's are whatever the formula's type, with "
    "words enough to fill three lines or more of the default page's six and a half inches "
    "across, and then a few more to be sure of it, and then more of them:\n"
    "$$\\text{Displaylead} = " + fit_terms(11) + "$$\nand after the display the paragraph "
    "goes on.\n\nA table a little too wide, which spaces narrowed between its columns fit:\n\n"
    + fit_table("Spaced", FIT_NUMBERS[:10])
    + "A table that needs smaller type as well:\n\n" + fit_table("Smaller", FIT_NUMBERS[:12])
    + "A table whose smaller type is a design wider for its size, which leaves it a little "
    "too wide:\n\n" + fit_table("Overstep", FIT_NUMBERS[:14])
    + "A table too wide even in type three quarters its size, centered:\n\n"
    + fit_table("Centered", FIT_NUMBERS)
    + "A table too wide for the paper in that type, set smaller still:\n\n"
    + fit_table("Margins", (FIT_NUMBERS * 2)[:20])
    + "A table too wide for the paper in type half its size:\n\n"
    + fit_table("Overpaper", (FIT_NUMBERS * 3)[:44])
    + "A floating table after it, which the writer sets as a tabular in a table float, "
    "not a longtable:\n\n<table class=\"float\"><tbody><tr><td>Floatcell</td><td>beside it</td>"
    "</tr></tbody></table>\n\n"
    + "A table whose head is a cell across its columns, which fits its line:\n\n"
    + fit_table("Spanned", FIT_NUMBERS[:9],
                head="<tr><th></th><th colspan=\"9\">Degrees of freedom in the numerator</th></tr>")
    + "A table of formulas:\n\n"
    + fit_table("Mathcells", ["$x^{%d}y^{2}z$" % (i + 2) for i in range(14)])
    + "A table whose columns wrap, two words too long for a line together:\n\n"
    "<table><thead><tr><th>Wrapping</th><th>Longer word</th><th>Notes</th></tr></thead>"
    "<tbody><tr><td>Supercalifragilisticexpialidocious</td>"
    "<td>Hippopotomonstrosesquippedaliophobia</td><td><p>From dust.</p><p>Rare.</p></td>"
    "</tr></tbody></table>\n\n"
    "A table whose columns' widths are given, one too narrow for its longest word, which the "
    "filter counts as wide enough:\n\n<table><colgroup>" + "<col style=\"width: 20%\">" * 5
    + "</colgroup><thead><tr><th>Given</th><th>Next</th><th>Third</th><th>Fourth</th>"
    "<th>Fifth</th></tr></thead><tbody><tr><td>WWWWWWWWW</td><td>Wordnext</td><td>c</td>"
    "<td>d</td><td>e</td></tr></tbody></table>\n\n"
    "A table whose columns' widths are given, a formula TeX can't break too wide for its "
    "column, opening a line of its cell:\n\n<table><colgroup>" + "<col style=\"width: 20%\">" * 5
    + "</colgroup><thead><tr><th>Trig</th><th>Then</th><th>Third</th><th>Fourth</th>"
    "<th>Fifth</th></tr></thead><tbody><tr><td>a</td><td>b</td><td>c</td><td>d</td>"
    "<td>Trigcell then $\\sin x \\cos x \\tan x \\cot x$</td></tr></tbody></table>\n\n"
    "A table whose columns' widths are given, a formula too wide for its column opening a "
    "line of its cell and breaking after an operator:\n\n<table><colgroup>"
    + "<col style=\"width: 20%\">" * 5
    + "</colgroup><thead><tr><th>Plus</th><th>Then</th><th>Third</th><th>Fourth</th>"
    "<th>Fifth</th></tr></thead><tbody><tr><td>a</td><td>b</td><td>c</td><td>d</td>"
    "<td>Pluscell then $\\sec x \\csc x \\sin x \\cos x + 1$</td></tr></tbody></table>\n\n"
    "A table whose columns' widths are given, more than its line together, a line of words "
    "in a cell before one a formula opens:\n\n<table><colgroup>"
    + "<col style=\"width: 30%\">" * 5
    + "</colgroup><thead><tr><th>Over</th><th>Then</th><th>Third</th><th>Fourth</th>"
    "<th>Fifth</th></tr></thead><tbody><tr><td>a</td><td>b</td><td>c</td><td>d</td>"
    "<td>Overgiven, words to fill most of a column, then $\\sin x \\cos x \\tan x$</td>"
    "</tr></tbody></table>\n\n"
    "A table whose columns' widths are given, a fill-in blank too long for its column:\n\n"
    "<table><colgroup>" + "<col style=\"width: 20%\">" * 5
    + "</colgroup><thead><tr><th>Blank</th><th>Then</th><th>Third</th><th>Fourth</th>"
    "<th>Fifth</th></tr></thead><tbody><tr><td>a</td><td>b</td><td>c</td><td>d</td>"
    "<td>Blankcell: fill in the " + "_" * 30 + " here.</td></tr></tbody></table>\n\n"
    "A table whose columns' widths are given, more than its line together, a fill-in blank too "
    "long for its column:\n\n<table><colgroup>" + "<col style=\"width: 60%\">" * 2
    + "</colgroup><thead><tr><th>Over</th><th>Blank</th></tr></thead><tbody><tr>"
    "<td>Overblank: some words to fill a column</td><td>fill in the " + "_" * 36 + " here.</td>"
    "</tr></tbody></table>\n\n"
    "A table whose columns' widths are given, half the line each, a word of 26 letters in "
    "one and a fill-in blank in the other, the blank longer than its column:\n\n<table>"
    "<colgroup>" + "<col style=\"width: 50%\">" * 2 + "</colgroup><thead><tr><th>Word</th>"
    "<th>Blank</th></tr></thead><tbody><tr><td>Abcdefghijklmnopqrstuvwxyz</td>"
    "<td>Halfblank: fill in the " + "_" * 64 + " here.</td></tr></tbody></table>\n\n"
    "A table whose columns' widths are given, a word of code in one holding a run of "
    "underscores, which isn't a fill-in blank, longer than its column:\n\n<table><colgroup>"
    "<col style=\"width: 10%\"><col style=\"width: 90%\"></colgroup><tbody><tr>"
    "<td>Codeblank `print(________)`</td><td>words beside it, enough of them to fill the rest "
    "of the line</td></tr></tbody></table>\n\n"
    "A table whose columns' widths are given, a fill-in blank shorter than two thirds of its "
    "column joined to a word, the two longer than the column together:\n\n<table>"
    "<colgroup>" + "<col style=\"width: 50%\">" * 2 + "</colgroup><tbody><tr><td>Joinleft</td>"
    "<td>Joincell " + "_" * 15 + "12345678901234567890</td></tr></tbody></table>"
    "\n\n"
    "A table whose columns' widths are given, a fill-in blank longer than two thirds of its "
    "column with words joined to it, the three a little longer than the column even with "
    "the blank three underscores long, which a count of their characters fits:\n\n<table>"
    "<colgroup>" + "<col style=\"width: 20%\">" * 5
    + "</colgroup><tbody><tr><td>a</td><td>b</td><td>c</td><td>d</td><td>Joinlong WWW"
    + "_" * 15 + "8642</td></tr></tbody></table>\n\n"
    "A table of ten columns whose widths are given, a tenth of the line each, a fill-in blank "
    "longer than two thirds of the last between two words, alone on its line:\n\n<table>"
    "<colgroup>" + "<col style=\"width: 10%\">" * 10 + "</colgroup><tbody><tr>"
    "<td>bbb Edgy</td>" + "<td>b</td>" * 8 + "<td>bb " + "_" * 6 + " bb</td></tr>"
    "</tbody></table>\n\n"
    "A paragraph with a fill-in blank longer than two thirds of the line joined to a formula, "
    "and words after it:\n\n"
    "Mathjoin " + "_" * 40 + "$x = 1$ and more words to follow it on the line.\n\n"
    "A paragraph set flush to both margins, a label and a fill-in blank that fit the line "
    "together, and a second label and blank:\n\n"
    "```{=latex}\n{\\rightskip=0pt\\relax Justname \\OERBlank{" + "\\_" * 46
    + "} Justdate \\OERBlank{" + "\\_" * 10 + "}\\par}\n```\n\n"
    "A paragraph of two lines, the first ending in a fill-in blank and the second opening "
    "with one, each line's space shrunk to fit it:\n\n"
    "```{=latex}\n{\\setbox0=\\hbox{Rightmargin}\\setbox2=\\hbox{\\_\\_\\_\\_\\_}"
    "\\setbox4=\\hbox{Leftmargin}\\noindent Rightmargin\\nobreak\\hskip\\dimexpr\\linewidth"
    "-\\wd0-\\wd2+4pt\\relax minus 10pt\\OERBlank{\\_\\_\\_\\_\\_}\\linebreak\n"
    "\\OERBlank{\\_\\_\\_\\_\\_}\\nobreak\\hskip\\dimexpr\\linewidth-\\wd2-\\wd4+11.26pt\\relax "
    "minus 10pt Leftmargin\\par}\n```\n\n"
    "A paragraph opening with a fill-in blank that fits, a label, and a blank longer than two "
    "thirds of the line:\n\n" + "_" * 5 + " Twoblank " + "_" * 50 + "\n\n"
    + "_" * 37 + " Wholeback, the words after a fill-in blank longer than two thirds of the "
    "line that its line has room for whole.\n\n"
    "A paragraph opening with a fill-in blank, then a label, and a second blank that ends a "
    "point short of the line's end as TeX sets the line, a space after it taking the line two "
    "and a half points further:\n\n"
    "```{=latex}\n{\\setbox2=\\hbox{\\_\\_\\_\\_\\_}\\setbox4=\\hbox{Reachfit}"
    "\\setbox6=\\hbox{" + "\\_" * 10 + "}\\noindent\\OERBlank{\\_\\_\\_\\_\\_}"
    "\\nobreak\\hskip 3pt\\relax\\hbox{Reachfit}\\nobreak\\hskip\\dimexpr\\linewidth-\\wd2"
    "-\\wd4-\\wd6-4pt+1.76pt\\relax\\OERBlank{" + "\\_" * 10 + "}\\nobreak\\hskip 2.5pt"
    "\\relax\\hbox{}\\par}\n```\n\n"
    "A paragraph of one line opening with a fill-in blank longer than two thirds of it, no "
    "break allowed after the blank, then a label and a second blank, which ends a point short "
    "of the line's end with the line's space shrunk two points, as TeX sets the line:\n\n"
    "```{=latex}\n{\\setbox2=\\hbox{\\_\\_\\_\\_\\_}\\setbox4=\\hbox{Shrunk}"
    "\\noindent\\OERBlank{" + "\\_" * 40 + "}\\nobreak\\hskip 4pt\\relax\\hbox{Shrunk}"
    "\\nobreak\\hskip\\dimexpr\\linewidth+2.76pt-\\linewidth*2/3-4pt-\\wd4-\\wd2\\relax "
    "minus 10pt\\relax\\OERBlank{\\_\\_\\_\\_\\_}\\nobreak\\hskip 1pt\\relax\\hbox{}"
    "\\par}\n```\n\n"
    "A paragraph ending in a fill-in blank longer than the line:\n\n"
    "Endlabel " + "_" * 80 + "\n\n"
    + "_" * 76 + " Startafter, the word after a fill-in blank that opens its paragraph.\n\n"
    "A table of one column whose width is given, the line, two labels each with a fill-in "
    "blank longer than the line:\n\n<table><colgroup><col style=\"width: 100%\"></colgroup>"
    "<tbody><tr><td>Namelabel " + "_" * 72 + " and Datelabel " + "_" * 72 + "</td></tr></tbody>"
    "</table>\n\n"
    "A table whose columns have no widths, a fill-in blank in one too long for the line at "
    "its full length, which a count of its characters fits:\n\n<table><thead><tr>"
    "<th>Label</th><th>Blank</th></tr></thead><tbody><tr><td>Rowblank</td><td>"
    + "_" * 52 + "</td></tr></tbody></table>\n\n"
    "A table whose columns have no widths, words in one and a long fill-in blank in the other, "
    "which fit the line together with the blank at its least:\n\n<table><thead><tr>"
    "<th>Item</th><th>Answer</th></tr></thead><tbody><tr><td>Wordcol lorem ipsum dolor sit "
    "amet consectetur</td><td>Signature: " + "_" * 66 + "</td></tr></tbody></table>\n\n"
    "A table whose columns have no widths, two of words and one a long fill-in blank:\n\n"
    "<table><thead><tr><th>Name</th><th>Role</th><th>Notes</th></tr></thead><tbody><tr>"
    "<td>Threecol Alexandra Hamilton</td><td>Project coordinator</td><td>" + "_" * 58
    + "</td></tr></tbody></table>\n\n"
    "A table whose columns have no widths, words that fit the line beside a blank of three "
    "underscores after its label, but not beside one of two thirds of a column three times "
    "as wide as the label:\n\n<table><thead><tr><th>Item</th><th>Answer</th></tr></thead>"
    "<tbody><tr><td>Labelcol lorem ipsum dolor sit amet consectetur adipiscing elit sed</td>"
    "<td>Labelsig: " + "_" * 66 + "</td></tr></tbody></table>\n\n"
    "A table whose columns have no widths, a label and its formula in the first column, "
    "pairs of numbers with fractions in the others, as Precalculus 2e's Table 2 of section "
    "4.4 has them, which the counts give more of the line than the label:\n\n<table><tbody><tr>"
    "<td>Wholerow $g(x) = \\log_{2}(x)$</td>"
    + "".join("<td>$\\left( \\frac{1}{%d},%d \\right)$</td>" % (2 ** i, -i) for i in range(1, 6))
    + "</tr></tbody></table>\n\n"
    "A table whose columns have no widths, a sum too long for the line in one:\n\n"
    "<table><thead><tr><th>Name</th><th>Sum</th></tr></thead><tbody><tr>"
    "<td>Piecerow, a sum too long for its line</td><td>$S = " + fit_terms(22) + "$</td>"
    "</tr></tbody></table>\n\n"
    "A layout table too wide for its line, its caption a paragraph before it:\n\n"
    "<table role=\"presentation\"><caption>Laycap, the caption of a layout table too wide for "
    "its line</caption><tbody><tr><td>Laytable</td>"
    + "".join("<td>%s</td>" % v for v in FIT_NUMBERS[:14]) + "</tr></tbody></table>\n\n"
    "A table of 45 columns whose widths are given, the spaces between them more than its "
    "line, so that the writer gives its columns less than no width:\n\n<table><colgroup>"
    + "<col style=\"width: 2.22%\">" * 45 + "</colgroup><tbody><tr><td>Qz</td>"
    + "".join("<td>%d</td>" % (i + 1) for i in range(44)) + "</tr></tbody></table>\n\n"
    "A table of 22 columns whose longest words are wider than a line together, its "
    "corner's words wrapping:\n\n"
    + fit_table("Twentytwo", (FIT_NUMBERS * 2)[:21],
                head="<tr><th>Degrees of freedom</th>"
                + "".join("<th>%d</th>" % (i + 1) for i in range(21)) + "</tr>")
    + "And one with a cell across two columns in its head:\n\n"
    + fit_table("Twentyspan", (FIT_NUMBERS * 2)[:21],
                head="<tr><th>Corner words wrapping</th><th colspan=\"2\">1 and 2</th>"
                + "".join("<th>%d</th>" % (i + 3) for i in range(19)) + "</tr>")
    + "A display formula whose spaces narrowed fit it:\n\n$$\\text{Displayspaced} = x^{2} "
    "\\mspace{54mu} \\text{as a worked example gives a step its reason, here a long one} "
    "\\mspace{54mu} y$$\n\n"
    "A display formula a little too wide, set smaller:\n\n$$\\text{Displaysmaller} = "
    + fit_terms(10) + "$$\n\nA display formula whose math is set in its subscripts' forms "
    "when smaller:\n\n$$\\text{Displayrefit} = " + fit_terms(13) + "$$\n\n"
    "A display formula too wide even so, centered:\n\n$$\\text{Displaycentered} = "
    + fit_terms(14) + "$$\n\nA numbered display formula a little too wide, set smaller, its "
    "number at its line's end:\n\n$$\\text{Tagwide} = " + fit_terms(11) + " \\tag{1.2}$$\n\n"
    "A worked example's steps whose formulas and reason's longest word the filter counts "
    "wider than a line, which LaTeX finds fit it:\n\n"
    + fit_steps("1111 + \\frac{2222}{3333} + \\frac{4444}{5555}", "=",
                "\\frac{66666}{7777} + \\frac{8888}{9999} + 1212",
                "Antidisestablishmentarianism is the longest word of this reason, which runs on "
                "for words enough to take most of a line and more of the next.")
    + "Steps whose reason's longest word leaves their formulas less of the line than "
    "they're wide:\n\n"
    + fit_steps("1313 + \\frac{2424}{3535} + \\frac{4646}{5757}", "=",
                "\\frac{68686}{7979} + \\frac{8080}{9191} + 1414",
                "Unbreakableformulasreasonlongestword is the longest word of this reason.")
    + "Steps whose relations are TeX's commands, set across the line:\n\n"
    + fit_steps("1515 + \\frac{2626}{3737}", "\\leq", "\\frac{48484}{5959} + 6161",
                "Leqreason: collect the terms, and the inequality holds as it did, in words "
                "enough to wrap in their column.")
    + "Steps whose reason holds a formula wider than the line leaves their words:\n\n"
    + fit_steps("1818 + \\frac{2929}{3131} + \\frac{4242}{5353}", "=",
                "\\frac{63636}{7474} + \\frac{8585}{9696} + 1717",
                "Reasonmath: use $a^{2} + b^{2} + c^{2} + d^{2} + e^{2} = g^{2}$ on it.")
    + "Steps whose reason's formula leaves their formulas less than three quarters of "
    "their counts:\n\n"
    + fit_steps("1919 + \\frac{2828}{3737} + \\frac{4646}{5656}", "=",
                "\\frac{64646}{7575} + \\frac{8686}{9797} + 1919",
                "Reasonshare: use $p^{2} + q^{2} + r^{2} + s^{2} + t^{2} + u^{2} = w^{2}$ on it.")
    + "Steps whose reason's formula leaves their formulas a little more than three quarters "
    "of their counts:\n\n"
    + fit_steps("2121 + \\frac{3232}{4343} + \\frac{5454}{6565}", "=",
                "\\frac{76767}{8787} + \\frac{9898}{2323} + 2121",
                "Reasonfloor: use $a^{2} + b^{2} + c^{2} + d^{2} + e^{2} = 23g^{2}$ on it.")
    + "And a little less:\n\n"
    + fit_steps("3434 + \\frac{4545}{6767} + \\frac{7878}{8989}", "=",
                "\\frac{87878}{9090} + \\frac{2525}{3636} + 3434",
                "Reasonunder: use $a^{2} + b^{2} + c^{2} + d^{2} + e^{2} = 234g^{2}$ on it.")
    + "Steps whose reason holds a formula and a word longer than the formula's share of the "
    "line:\n\n"
    + fit_steps("4747 + \\frac{5858}{6969} + \\frac{7171}{8282}", "=",
                "\\frac{97979}{9393} + \\frac{2727}{3838} + 4747",
                "Holdword: use $p^{2} + q^{2} + r^{2} + s^{2} + t^{2} + u^{2} = w^{2}$ with "
                "Pythagoreanextendedwordyandmore.")
    + "Steps whose reason holds a fraction, longer counted piece by piece, as a cell's words "
    "are, than its words:\n\n"
    + fit_steps("5252 + \\frac{6363}{7070} + \\frac{8181}{9292} + 5252", "=",
                "\\frac{86868}{3030} + \\frac{4141}{5252} + \\frac{6363}{7070} + "
                "\\frac{8181}{9292} + 8181",
                "Fracreason: divide by $\\frac{123456789}{987654321}$ here.")
    + "Steps whose reason's formula alone is longer than a line, as counted:\n\n"
    + fit_steps("x", "=", "y", "Reasonline: use $a^{2} + b^{2} + c^{2} + d^{2} + e^{2} + f^{2} "
                "+ h^{2} + i^{2} + j^{2} + k^{2} + m^{2} = g^{2}$ on it.")
    + "Steps whose reason's formula alone is longer than a line, as counted, though their "
    "cells, a function's name a character, are shorter:\n\n"
    + fit_steps("x", "=", "y", "Trigline: use $" + TRIG_TERMS + "$ on it.")
    + "Steps whose reason's longest word alone is longer than a line, as counted:\n\n"
    + fit_steps("x + 1", "=", "y", "Longestwordofthisreasonlongerthanalineofsixtyonecharacterscounted "
                "is a word.")
    + "Steps the counts set across the line, which fit it at their own width as LaTeX sets "
    "them:\n\n"
    + fit_steps("1111 + 2222", "=", "3333", "Ownwidth: one line of words beside the math, at its width.")
    + "Steps a little too wide at their own width, which narrowed spaces would fit:\n\n"
    + fit_steps("1112 + 2223", "=", "3335",
                "Nearwidth: a line of words beside the math, a little too wide for it.")
    + "Steps too wide at their own width, their reason wrapping beside their formulas:\n\n"
    + fit_steps("1515 + 2626 + 3737", "=", "4848 + 5959 + 6161 + 7272 + 8383",
                "Mathwidth: collect the terms, and the equation holds as it did, in words enough to "
                "wrap in their column beside the math.")
    + "Steps too wide even with their reason as narrow as its longest word:\n\n"
    + fit_steps("1313 + \\frac{2424}{3535} + \\frac{4646}{5757} + \\frac{1212}{3434} + "
                "\\frac{5656}{7878}", "=",
                "\\frac{68686}{7979} + \\frac{8080}{9191} + 1414 + \\frac{2323}{4545} + "
                "\\frac{6767}{8989}",
                "Smallsteps: Unbreakablelongestwordofthsreasonhere is its longest word.")
    + "Steps whose reason's longest word is wider than its count, which narrowed spaces fit:\n\n"
    + fit_steps("1918 + 2827 + 3736 + 4645", "=", "5554",
                "Wordwide: " + "W" * 22 + " is the longest word here.")
    + "Steps whose reason holds a fill-in blank longer than its column:\n\n"
    + fit_steps("1111 + 2222", "=", "3333",
                "Blankreason: fill in the " + "_" * 60 + " here.")
    + "Steps whose reason holds a label and a fill-in blank that fit the line beside their "
    "formulas, the blank longer than two thirds of the column the counts give it:\n\n"
    + fit_steps("x", "=", "y", "Wholereason " + "_" * 32)
    + "Steps whose reason holds a run of underscores underlined, which isn't a blank, so "
    "nothing draws it shorter:\n\n"
    + fit_steps("1111 + 2222", "=", "3333",
                "Underreason: fill in the <u>" + "_" * 45 + "</u> here.")
    + "Steps whose reason's lines are broken where it says, each shorter than the part of the "
    "line the counts give it:\n\n"
    + fit_steps("1111 + 2222", "=", "3333", "Breakreason:<br>a line under it.")
    + "Steps whose reason's formula, whole, is wider than the line beside their formulas:\n\n"
    + fit_steps("x", "=", "y", "Mathpiece: use $" + " + ".join("a_{%d}" % i for i in range(1, 17))
                + "$ on it.")
    + "Steps whose reason holds a matrix wider than the line beside their formulas:\n\n"
    + fit_steps("x", "=", "y", "Matrixreason: use $\\begin{matrix} " + " & ".join(MATRIX_ROW)
                + " \\end{matrix}$ here.")
    + "Steps too wide for the paper even at three quarters of their type:\n\n"
    + fit_steps(" + ".join(FIT_NUMBERS_STEPS), "=", "1111", "Paperwide: add them.")
    + "Steps whose words are in two columns, set as the counts lay them out:\n\n"
    '<table role="presentation" class="formula-steps"><tr><td>$x$</td><td>$=$</td>'
    "<td>Twowords: a column</td><td>of words beside it.</td></tr><tr><td></td><td>$=$</td>"
    "<td>$29738$</td><td>Add them.</td></tr></table>\n\n"
    + "Steps whose formula is spaced with an empty matrix, as OpenStax spaces one:\n\n"
    + fit_steps("x + 1", "=", "2\\begin{matrix} & & & \\end{matrix}",
                "Bracedsteps: take one from each side.")
    + "Steps whose cells in a column differ in width, each column aligned as they align it:\n\n"
    '<table role="presentation" class="formula-steps"><tr>'
    '<td style="text-align: right">$6031 + 7042$</td><td style="text-align: center">$=$</td>'
    '<td style="text-align: left">$13073$</td><td style="text-align: left">Alignone: add.</td>'
    '</tr><tr><td style="text-align: right">$58$</td>'
    '<td style="text-align: center">$\\Longrightarrow$</td>'
    '<td style="text-align: left">$1000000000003$</td>'
    '<td style="text-align: left">Aligntwo: compare.</td></tr></table>\n\n'
    + "Steps whose longtable has a column more than their group says, as an edit of the latex "
    "target's LaTeX can leave them:\n\n"
    "```{=latex}\n"
    "{\\OERFitStepsTable{999}{4}{rcll}{m,m,m,0.3000}\\binoppenalty=10000 \\relpenalty=10000\n"
    "{\\ifdefined\\tagpdfsetup\\tagpdfsetup{table/tagging=div}\\fi\n"
    "{\\def\\LTcaptype{none}\n"
    "\\begin{longtable}[]{@{}rclll@{}}\n"
    "\\toprule\\noalign{}\n\\endhead\n\\bottomrule\\noalign{}\n\\endlastfoot\n"
    "\\(4321\\) & \\(=\\) & \\(1234\\) & Editedspec: a column & and another. \\\\\n"
    "\\end{longtable}\n}\n}\n\\OERFitTableEnd{999}}\n"
    "```\n\n"
    + "A worked example's steps a book sets out in a table of its own, which the CNX unpacker "
    "gives the class steps, as it does the dev-math books':\n\n"
    '<table role="presentation" class="unnumbered unstyled steps"><tr><td>Unruledsteps: '
    "write the sum.</td><td>$7 + 12$</td></tr><tr><td>Simplify.</td><td>$19$</td></tr>"
    "</table>\n\n"
    "And a layout table that isn't steps:\n\n"
    '<table role="presentation" class="unnumbered unstyled"><tr><td>Ruledlayout: write the '
    "sum.</td><td>$7 + 12$</td></tr><tr><td>Simplify.</td><td>$19$</td></tr></table>\n\n"
    "And steps of each kind made a table of data again, as a row of table-headers.csv makes "
    "them, a header row and no role:\n\n"
    '<table class="unnumbered unstyled steps"><thead><tr><th>Ruleddata: the step</th>'
    "<th>Its result</th></tr></thead><tbody><tr><td>Write the sum.</td><td>$7 + 12$</td>"
    "</tr></tbody></table>\n\n"
    + fit_steps("1212 + 3434", "=", "4646", "Ruledformula: add them.").replace(
        '<table role="presentation" class="formula-steps"><tr>',
        '<table class="formula-steps"><thead><tr>').replace(
        "Ruledformula: add them.</td></tr>",
        "Ruledformula: add them.</td></tr></thead><tbody>").replace(
        "Add them.</td></tr></table>", "Add them.</td></tr></tbody></table>")
    + "Steps that float, which the writer sets as a tabular in a table float:\n\n"
    + fit_steps("1111 + 2222", "=", "3333", "Floatsteps: add them.").replace(
        'class="formula-steps"', 'class="formula-steps float"')
    + "A worked example's steps, an array in text:\n\n"
    "1. $\\begin{array}{lll} \\text{Arraysmaller} & = & " + fit_terms(11)
    + " \\\\ & = & b \\end{array}$\n")


def build_fit(work):
    """FIT_ONE on the default page, in Latin Modern (LATIN_MODERN): (the
    PDF's path, what the run said,
    its LaTeX, and LuaLaTeX's log of its LaTeX run as a third run would
    be, the aux saying two had gone before and fitted nothing)."""
    os.makedirs(work)
    with open(os.path.join(work, "one.md"), "w", encoding="utf-8") as fh:
        fh.write(FIT_ONE)
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  title: Fit\n  identifier: org.example.fit\n"
                 "  language: en-US\n  contents:\n    - one\n")
    with open(os.path.join(work, "meta.yaml"), "w", encoding="utf-8") as fh:
        fh.write(LATIN_MODERN)
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  pdf:\n    format: pdf\n    pdf:\n      metadata: meta.yaml\n")
    converted = subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick"],
                               cwd=work, capture_output=True, text=True,
                               stdin=subprocess.DEVNULL)
    run(["python3", os.path.join(BIN, "build-pdf.py"), "--latex-only"], work)
    tex = os.path.join(work, "pdf", "book.tex")
    source = third = ""
    if os.path.exists(tex):
        with open(tex, encoding="utf-8") as fh:
            source = fh.read()
        runs = os.path.join(work, "third")
        os.makedirs(runs)
        with open(os.path.join(runs, "book.aux"), "w", encoding="utf-8") as fh:
            fh.write("\\relax\n\\OERFitRun{2}\n")
        subprocess.run(["lualatex", "-interaction=nonstopmode", "-output-directory", runs, tex],
                       cwd=work, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if os.path.exists(os.path.join(runs, "book.log")):
            with open(os.path.join(runs, "book.log"), encoding="utf-8", errors="replace") as fh:
                third = fh.read()
    return (os.path.join(work, "pdf", "org.example.fit.pdf"),
            converted.stdout + converted.stderr, source, third)


# On the default page in two columns, under the fleqn class option, which
# sets a display a margin from its line's left end: a display formula too
# wide for its column, which FIT_MACROS leaves as fleqn sets it; a worked
# example's steps, an array in text, too wide for their column even at three
# quarters of their type, set smaller still to fit it rather than run into
# the other column; steps too wide for it even at half their type, of
# which the build warns; and a line of code in no language too wide for its
# column even at three quarters of its size, set smaller still to fit it,
# below 8.5 points, where Latin Modern Mono's 8-point design, 3 percent
# wider for its size, leaves it a little too wide, within 4 percent of its
# column, until the second run fits it again. (longtable can't be set in
# two columns.)
FIT_TWO = (
    "# Columns\n\nA display formula too wide for its column:\n\n$$\\text{Columndisplay} = "
    + fit_terms(10) + "$$\n\nA worked example's steps too wide for their column even at "
    "three quarters of their type:\n\n1. $\\begin{array}{lll} \\text{Columnarray} & = & "
    + fit_terms(6) + " \\\\ & = & b \\end{array}$\n\nSteps too wide for it even at half "
    "their type:\n\n1. $\\begin{array}{lll} \\text{Columnwide} & = & " + fit_terms(14)
    + " \\\\ & = & b \\end{array}$\n\nA line of code too wide for its column even at "
    "three quarters of its size:\n\n```\nColumncode = \"" + "c" * 45 + "\"\n```\n")


def build_fit_columns(work):
    """FIT_TWO on the default page in two columns, under fleqn, in Latin
    Modern (LATIN_MODERN): (the PDF's path, what the run said)."""
    os.makedirs(work)
    with open(os.path.join(work, "one.md"), "w", encoding="utf-8") as fh:
        fh.write(FIT_TWO)
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  title: Columns\n  identifier: org.example.columns\n"
                 "  language: en-US\n  contents:\n    - one\n")
    with open(os.path.join(work, "meta.yaml"), "w", encoding="utf-8") as fh:
        fh.write("classoption: [twocolumn, fleqn]\n" + LATIN_MODERN)
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  pdf:\n    format: pdf\n    pdf:\n      metadata: meta.yaml\n")
    converted = subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick"],
                               cwd=work, capture_output=True, text=True,
                               stdin=subprocess.DEVNULL)
    return (os.path.join(work, "pdf", "org.example.columns.pdf"),
            converted.stdout + converted.stderr)


# An evaluation bar's limits as OpenStax writes them, an mtable under the
# bar and one over it, a row of each empty: texmath writes a one-column
# matrix whose last row is empty with an empty line before its end, which
# TeX reads as \par, and LaTeX's tagging stopped at one in a display
# formula (Calculus Volume 2's chapter 3); in a formula in text, where LaTeX
# read on, the row was lost, a \\ before a matrix's end making none, and
# the upper limit sat 9.5 points above the formula's baseline, the lower
# 28.5 below. A page of HTML, as the CNX unpacker writes one: a Markdown
# formula can't hold an empty line.
BAR_LIMITS = ("<msubsup><mo>|</mo><mtable><mtr><mtd></mtd></mtr><mtr><mtd><mn>0</mn></mtd></mtr>"
              "</mtable><mtable><mtr><mtd><mn>5</mn></mtd></mtr><mtr><mtd></mtd></mtr></mtable>"
              "</msubsup>")
BLANK_LINES = ('<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8"><title>Bars</title>'
               '</head><body>\n<h1>Bars</h1>\n<p>Barlimits, an evaluation bar\'s limits in a display '
               'formula:</p>\n<p><math display="block"><mrow><mi>x</mi>' + BAR_LIMITS
               + '<mo>=</mo><mn>5</mn></mrow></math></p>\n<p>And Barinline, in a formula in text, '
               '<math><mrow><mi>y</mi>' + BAR_LIMITS + '</mrow></math>, after it.</p>\n'
               '</body></html>\n')


def build_blank_lines(work):
    """BLANK_LINES as a book's one page, on the default page: (the PDF's
    path, its LaTeX)."""
    os.makedirs(work)
    with open(os.path.join(work, "bars.html"), "w", encoding="utf-8") as fh:
        fh.write(BLANK_LINES)
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  title: Bars\n  identifier: org.example.bars\n"
                 "  language: en-US\n  contents:\n    - bars\n")
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  pdf:\n    format: pdf\n")
    run(["python3", os.path.join(BIN, "convert.py"), "--quick"], work)
    run(["python3", os.path.join(BIN, "build-pdf.py"), "--latex-only"], work)
    tex = os.path.join(work, "pdf", "book.tex")
    source = ""
    if os.path.exists(tex):
        with open(tex, encoding="utf-8") as fh:
            source = fh.read()
    return os.path.join(work, "pdf", "org.example.bars.pdf"), source


# Tables ruled row by row (class row-rules), as the CNX unpacker classes
# those OpenStax's math books draw with a light rule under each row: on a
# page, a worked example's steps, a layout table, its last step opening
# with "(", which booktabs takes a rule's columns to trim it to from; a
# table of data with a caption and a head; and one with a cell spanning
# rows. On another, a table in a ruled table's last cell, after which the
# row's rule is drawn, a table not ruled, and a table ruled in the lighter
# gray of a calculus book's Key Equations (row-rules-faint).
# And on a third, a table of 205 rows, longer than one of the chunks
# longtable sets a table in (\LTchunksize, 200 rows).
def ruled_page(title, body):
    return ('<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8"><title>' + title
            + '</title></head><body>\n<h1>' + title + '</h1>\n' + body + '</body></html>\n')


RULED_TABLES = ruled_page("Ruled", (
    '<p>Stepsbefore, a worked example\'s steps:</p>\n'
    '<table class="steps row-rules" role="presentation"><tbody>\n'
    '<tr><td>Stepone Write the equation.</td><td><math><mi>x</mi><mo>+</mo><mn>3</mn>'
    '<mo>=</mo><mn>7</mn></math></td></tr>\n'
    '<tr><td>Steptwo Take 3 from each side.</td><td><math><mi>x</mi><mo>=</mo><mn>7</mn>'
    '<mo>&#x2212;</mo><mn>3</mn></math></td></tr>\n'
    '<tr><td>(a) Stepthree Simplify.</td><td><math><mi>x</mi><mo>=</mo><mn>4</mn></math>'
    '</td></tr>\n</tbody></table>\n'
    '<p>Databefore, a table of data:</p>\n'
    '<table class="row-rules"><caption>Keyequations</caption>\n'
    '<thead><tr><th>Nameword</th><th>Equation</th></tr></thead><tbody>\n'
    '<tr><td>Slopeword</td><td>rise over run</td></tr>\n'
    '<tr><td>Pointword</td><td>a point and a slope</td></tr>\n'
    '<tr><td>Interceptword</td><td>where it meets an axis</td></tr>\n</tbody></table>\n'
    '<p>Spanbefore, a cell spanning rows:</p>\n'
    '<table class="row-rules"><tbody>\n'
    '<tr><td rowspan="2">Spanstwo</td><td>Spanfirst</td></tr>\n'
    '<tr><td>Spansecond</td></tr>\n'
    '<tr><td>Spanalone</td><td>Spanthird</td></tr>\n</tbody></table>\n'
    '<p>Spanafter, the end.</p>\n'))
RULED_INNER = ruled_page("Inner", (
    '<p>Innerbefore, a table in a cell:</p>\n'
    '<table class="row-rules"><tbody>\n'
    '<tr><td>Besideit</td><td><table><thead><tr><th>Innerhead</th><th>B</th></tr></thead>'
    '<tbody>\n<tr><td>Innerone</td><td>2</td></tr><tr><td>Innertwo</td><td>4</td></tr>'
    '</tbody></table></td></tr>\n'
    '<tr><td>Underit</td><td>Lastone</td></tr>\n</tbody></table>\n'
    '<p>Plainbefore, a table not ruled:</p>\n'
    '<table><thead><tr><th>Plainhead</th><th>Value</th></tr></thead><tbody>\n'
    '<tr><td>Plainone</td><td>1</td></tr><tr><td>Plaintwo</td><td>2</td></tr>\n'
    '</tbody></table>\n<p>Plainafter, the end.</p>\n'
    '<table class="row-rules row-rules-faint"><tbody>\n'
    '<tr><td>Faintone</td><td>1</td></tr><tr><td>Fainttwo</td><td>2</td></tr>\n'
    '</tbody></table>\n<p>Faintafter, the end.</p>\n'))
RULED_LONG = ruled_page("Long", (
    '<p>Longbefore, a long table:</p>\n'
    '<table class="row-rules"><thead><tr><th>Longhead</th><th>Square</th></tr></thead><tbody>\n'
    + "".join(f'<tr><td>Longrow{n}</td><td>{n * n}</td></tr>\n' for n in range(1, 206))
    + '</tbody></table>\n<p>Longafter, the end.</p>\n'))
GRAY = (0.459, 0.455, 0.455)   # OpenStax's Grey3, #757474, as the PDF gives it
FAINT = (0.945, 0.945, 0.945)  # and its Grey1, #F1F1F1


def build_rules(work):
    """RULED_TABLES, RULED_INNER, and RULED_LONG as a book's three pages, on
    the default page: the PDF's path."""
    os.makedirs(work)
    for name, page in (("ruled", RULED_TABLES), ("inner", RULED_INNER),
                       ("long", RULED_LONG)):
        with open(os.path.join(work, name + ".html"), "w", encoding="utf-8") as fh:
            fh.write(page)
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  title: Rules\n  identifier: org.example.rules\n"
                 "  language: en-US\n  contents:\n    - ruled\n    - inner\n    - long\n")
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  pdf:\n    format: pdf\n")
    run(["python3", os.path.join(BIN, "convert.py"), "--quick"], work)
    return os.path.join(work, "pdf", "org.example.rules.pdf")


def rules_between(lines, rules, above, below, color=GRAY):
    """How many level rules of a color (any, for None) a page draws between
    the line holding above and the first line under it holding below, on
    the first page holding both (glyph_lines, pdftext.level_rules); None
    where no page does."""
    for page, rows in sorted(lines.items()):
        tops = [row[0] for row in rows if above in row[3]]
        bottoms = [row[0] for row in rows if below in row[3] and tops and row[0] < tops[0]]
        if tops and bottoms:
            return sum(1 for at, height, _left, _right, drawn, _artifact in rules
                       if at == page and max(bottoms) < height < tops[0]
                       and (color is None or drawn == color))
    return None


def rules_checks(rules_path):
    """The rules book's checks (build_rules)."""
    built = os.path.exists(rules_path)
    lines = glyph_lines(rules_path) if built else {}
    rules = pdftext.level_rules(rules_path) if built else []

    def between(above, below, color=GRAY):
        return rules_between(lines, rules, above, below, color)

    def page_of(word):
        return next((page for page, rows in sorted(lines.items())
                     if any(word in row[3] for row in rows)), None)

    def steps_rules():
        page = page_of("Stepone")
        top, bottom = (next(row[0] for row in lines.get(page, []) if word in row[3])
                       for word in ("Stepone", "Databefore"))
        return [r for r in rules if r[0] == page and bottom < r[1] < top]

    def line_edges():
        """Where the line starts and ends: the widest gray rule on the page
        with the table in a cell, as wide as the line, its column of words
        wrapping."""
        return max(((r[2], r[3]) for r in rules if r[0] == page_of("Underit") and r[4] == GRAY),
                   key=lambda edges: edges[1] - edges[0])
    long_pages = [page for page, rows in lines.items()
                  if any("Longhead" in row[3] for row in rows)]
    items = [
        ("a table ruled row by row (class row-rules) has a rule under each row of its body, "
         "in OpenStax's gray, a worked example's steps, a layout table, and a table of data, "
         "and none under its head, as OpenStax draws none there, nor any of the rules the "
         "writer draws above it, under its head, or below it",
         lambda: built and [(between(*pair), between(*pair, None)) for pair in (
             ("Stepone", "Steptwo"), ("Steptwo", "Stepthree"), ("Stepthree", "Databefore"),
             ("Slopeword", "Pointword"), ("Pointword", "Interceptword"),
             ("Interceptword", "Spanbefore"))] == [(1, 1)] * 6
         and [between(above, below, None) for above, below in (
             ("Stepsbefore", "Stepone"), ("Keyequations", "Nameword"),
             ("Nameword", "Slopeword"))] == [0, 0, 0]),
        ("and a table of a calculus book's Key Equations (row-rules-faint) in OpenStax's "
         "lighter gray",
         lambda: built and [between("Faintone", "Fainttwo", FAINT),
                            between("Fainttwo", "Faintafter", FAINT),
                            between("Faintone", "Faintafter")] == [1, 1, 0]),
        ("each an artifact, across the table's columns as booktabs draws a rule in a long "
         "table, not the line: the steps' start right of where a table as wide as the line "
         "starts its rules and end left of where it ends them",
         lambda: built and rules and all(r[5] for r in rules if r[4] in (GRAY, FAINT))
         and len(steps_rules()) == 3
         and len({(r[2], r[3]) for r in steps_rules()}) == 1
         and steps_rules()[0][2] > line_edges()[0] + 20
         and steps_rules()[0][3] < line_edges()[1] - 20),
        ("a step opening with \"(\" keeps it: the rule before it is no rule's columns to trim "
         "to (booktabs' \\midrule(lr) in a long table)",
         lambda: built and any("(a)Stepthree" in row[3].replace(" ", "")
                               for rows in lines.values() for row in rows)),
        ("a row a cell spanning rows reaches below isn't ruled; the row it ends with is",
         lambda: built and [between("Spanfirst", "Spansecond", None),
                            between("Spansecond", "Spanalone"),
                            between("Spanalone", "Spanafter")] == [0, 1, 1]),
        ("a table in a ruled table's last cell is drawn as before, its head's black rule and "
         "no other, and the rule under the row it's in is under it",
         lambda: built and [between("Innerhead", "Innerone", (0.0, 0.0, 0.0)),
                            between("Innerhead", "Innerone", None),
                            between("Innerone", "Innertwo", None),
                            between("Innertwo", "Underit"),
                            between("Underit", "Plainbefore")] == [1, 1, 0, 1, 1]),
        ("a table not ruled keeps the writer's black rules, above it, under its head, and "
         "below it, and no gray one",
         lambda: built and [between(above, below, (0.0, 0.0, 0.0)) for above, below in (
             ("Plainbefore", "Plainhead"), ("Plainhead", "Plainone"),
             ("Plaintwo", "Plainafter"))] == [1, 1, 1]
         and between("Plainbefore", "Plainafter") == 0),
        ("a table longer than one of longtable's chunks (200 rows) is ruled across the end "
         "of the first, where a rule had stopped LaTeX's tagging: a rule under each of its "
         "205 rows, and none under its head on any page it's on",
         lambda: built and long_pages and sum(
             1 for r in rules if r[0] in long_pages and r[4] == GRAY) == 205
         and between("Longrow200", "Longrow201") in (1, None)
         and between("Longhead", "Longrow1", None) == 0),
        ("and a rule is no row of its table's: each table's rows are its own, the long "
         "table's its head's and its 205",
         lambda: built and [len(spanning_table(rules_path, n)) for n in range(7)]
         == [4, 3, 2, 3, 3, 2, 206]
         and spanning_table(rules_path, 1) == [[2, 1], [1], [1, 1]]),
    ]
    if shutil.which("verapdf") or os.environ.get("VERAPDF"):
        items.append(("veraPDF finds nothing in the rules book's PDF",
                      lambda: built and not pdfcheck.run_verapdf(
                          outputcheck.find_validator("verapdf"), rules_path)))
    return items


# A book of code on the default page, in the default's faces, its code in
# IBM Plex Mono at the text's size (build_code): a block whose lines fit
# theirs, set at that size; a highlighted line too long for its line, and
# one in no language, which the writer sets in LaTeX's verbatim, each set
# smaller to fit it; a line in no language in a list's item that fits the
# text's width but not the item's, measured without the list's margin; a
# line in no language too long for its line even at three quarters of its
# size, set at that size, running on into the margin, which LaTeX reports as
# a line of text too wide and the build names as code; one that would come
# within a quarter inch of the paper's edge at three quarters, set smaller
# to end that far inside it; one that would come that near even at half, but
# for the little more room the fit aims to leave, set at half, not wrapped;
# a block with a line too long for the paper even at half its size, set at
# three quarters, its lines too long for their line wrapped where they reach
# its end, a line of one word broken between its letters, one of a word TeX
# would hyphenate, not hyphenated, a line of words indented with spaces and
# one with no-break spaces, as OpenStax's code is, broken at their spaces,
# and a line after them, and lines in no language so, one of hyphened
# words broken after a hyphen, and one longer than its line by less than
# half a point, not broken, as a highlighted one isn't; a block of a long
# word after an indentation, broken in the word, not after the
# indentation, a line indented deeper than leaves twenty characters to a
# part, its text twenty characters from the line's end, a line of words
# joined by no-break spaces, broken after one, a word after a space that
# fits the next row whole, not broken after a dot, a line that opens with
# a mark, its parts two characters in, and Hebrew with its points, each
# kept with its letter, one line with a point on every letter; and a
# line in no language
# where a page ends, whose parts go on to the next page together, all of
# which the build says it wrapped; and a footnote's, fitted to the
# footnote's line. And what a review found: a line in no language with
# hyphens, which TeX broke after one, ragged right letting it; a quotation's
# line, fitted to the quotation's line and inside the text's, not said to
# run into the margin; a definition that opens with code, whose term the
# writer's ~ keeps on a line of its own; code in a table's cell, in no
# language in one table and highlighted in another, each table fitted by its
# lines; a footnote's code in a table's cell, a table whose columns wrap, so
# that the footnote's code, set after the table in its group, which measures
# highlighted code too, is measured as its own; a footnote's code in no
# language still too wide, which LaTeX reports at a line of the file it's
# read from, named once, as code; and a footnote whose words are too wide
# for its line and whose last block is code, which LaTeX reports at the line
# the footnote's text ends on, named as a line of text. Each line, its text
# as written, opens with a word of its own.
CODE_LONG = "def longline(price, quantity, discount, tax_rate, shipping, handling, region):"
PAPER_WORDS = " ".join("word%02d" % i for i in range(30))
FOOT_WORDS = " ".join("word%02d" % i for i in range(90))
PAPER_HYPHEN = "incomprehensibilities" * 10
PAPER_DASHES = "abcde-" * 40
PAPER_LEAD = " " * 60 + "Paperlead" + "x" * 31 + " = 1"
PAPER_DEEP = " " * 90 + "Paperdeep = \"" + PAPER_WORDS + "\""
PAPER_HEB = "Paperheb = \"" + "\u05e9\u05b8\u05c1\u05dc\u05d5\u05b9\u05dd" * 40 + "\""
PAPER_JOINED = "Paperjoined = \"" + PAPER_WORDS.replace(" ", "\u00a0") + "\""
PAPER_POINTED = "Paperpointed = \"" + "\u05d1\u05bc" * 150 + "\""
PAPER_DOTS = "Paperdots = " + ".".join("part%d" % i for i in range(13))
PAPER_MARK = "\u0301Papermark = \"" + PAPER_WORDS + "\""
PAPER_EXACT = "Paperexact = " + "e" * 74
TALL_WORDS = " ".join("t%03d" % i for i in range(1000))
CODE_CELL = ("Cellplain = [" + ", ".join(str(i) for i in range(10, 19)) + "]",
             "Cellcode = [" + ", ".join(str(i) for i in range(10, 19)) + "]")
FIT_CODE = (
    "# Code\n\nA block whose lines fit theirs:\n\n```python\ndef shortline(p):\n    return p\n"
    "```\n\nA highlighted line too long for its line:\n\n```python\n" + CODE_LONG
    + "\n    return price\n```\n\nCode in no language, LaTeX's own verbatim, too long for its "
    "line:\n\n```\nPlainlong = \"" + "abcdefghijklmnopqrstuvwxyz" * 2 + "abcdefghijkl\"\n```\n\n"
    "1. In a list, a line in no language that fits the text's width but not the item's:\n\n"
    "    ```\n    Listline = [" + ", ".join(str(i) for i in range(1, 16)) + "]\n    ```\n\n"
    "A line in no language too long for its line even at three quarters of its size:\n\n```\n"
    "Marginline = \"" + "x" * 80 + "\"\n```\n\nA line that would come within a quarter inch of "
    "the paper's edge at three quarters of its size:\n\n```python\nRoomline = \"" + "w" * 109
    + "\"\n```\n\nA line that would come that near even at half its size, but for the room "
    "the fit leaves:\n\n```python\nHalfline = \"" + "h" * 130 + "\"\n```\n\n"
    "A line too long for the paper even at half its size, and lines of words, "
    "one indented with no-break spaces, as OpenStax indents code:\n\n```python\nPaperline = \""
    + "y" * 200 + "\"\nPaperhyphen = \"" + PAPER_HYPHEN + "\"\n    Paperwords = \""
    + PAPER_WORDS + "\"\n\u00a0\u00a0Papernbsp = \""
    + PAPER_WORDS + "\"\nPaperafter = 1\n```\n\nA line in no language too long for the paper "
    "even at half its size:\n\n```\nPaperplain = " + PAPER_WORDS + "\nPaperdash = " + PAPER_DASHES
    + "\n" + PAPER_EXACT + "\n```\n\nA line indented deeper than leaves twenty characters to a part, a long word "
    "after an indentation, words joined by no-break spaces, a word that fits the next row "
    "whole, a line that opens with a mark, and Hebrew with its points:\n\n"
    "```python\n" + PAPER_LEAD + "\n" + PAPER_DEEP + "\n" + PAPER_JOINED + "\n" + PAPER_DOTS
    + "\n" + PAPER_MARK + "\n" + PAPER_HEB + "\n" + PAPER_POINTED + "\n```\n\n"
    "A footnote with code.[^code]\n\n"
    "A line in no language with hyphens, too long for its line:\n\n```\nHyphenline = \""
    + "abcd-" * 12 + "abcd\"\n```\n\n> A quotation's code, too long for its line but not the "
    "text's at three quarters of its size:\n>\n> ```\n> Quoteline = \"" + "q" * 64 + "\"\n> ```\n\n"
    "Termone\n\n:   ```python\n    Defline = 1\n    ```\n\nTermtwo\n\n:   ```\n    Plaindef = 2\n"
    "    ```\n\nCode in no language in a table's cell:\n\n+" + "-" * 50 + "+" + "-" * 16
    + "+\n| ```" + " " * 45 + " | Beside" + " " * 9 + "|\n| " + CODE_CELL[0].ljust(48) + " |"
    + " " * 16 + "|\n| ```" + " " * 45 + " |" + " " * 16 + "|\n+" + "-" * 50 + "+" + "-" * 16
    + "+\n\nHighlighted code in a table's cell:\n\n+" + "-" * 50 + "+" + "-" * 16
    + "+\n| ```python" + " " * 39 + " | Besidetwo" + " " * 6 + "|\n| " + CODE_CELL[1].ljust(48)
    + " |" + " " * 16 + "|\n| ```" + " " * 45 + " |" + " " * 16 + "|\n+" + "-" * 50 + "+"
    + "-" * 16 + "+\n\n"
    "A footnote in a table's cell, whose columns wrap:\n\n+" + "-" * 30 + "+" + "-" * 12 + "+\n"
    "| A cell's note.[^cell]" + " " * 8 + "| Here" + " " * 7 + "|\n+" + "-" * 30 + "+"
    + "-" * 12 + "+\n\nA footnote whose code is too long for its line even at three quarters of its "
    "size.[^wide]\n\nA footnote whose words are too wide for its line and whose last block is "
    "code.[^words]\n\n```{=latex}\n\\clearpage\n\\vspace*{\\dimexpr\\textheight-4\\baselineskip"
    "\\relax}\n```\n\n```\nPagefoot = " + FOOT_WORDS + "\n```\n\n"
    "[^code]: Its code:\n\n    ```python\n    Noteline = \"" + "z" * 70
    + "\"\n    ```\n\n[^cell]: Its code:\n\n    ```python\n    Cellnote = \"" + "c" * 87
    + "\"\n    ```\n\n[^wide]: Its code:\n\n    ```\n    Notewide = \"" + "n" * 106
    + "\"\n    ```\n\n[^words]: Its words: `Wideword" + "q" * 100 + "`\n\n    ```python\n"
    "    Footcode = 1\n    ```\n")
# A one-sided page whose right margin is wider than its left (CODE_MARGINS,
# build_code), in the default's faces, a footer of two lines at the foot
# of each page: a line in no language that would come within a quarter inch
# of the paper's edge at three quarters of its size if its margin were the
# left one, set at three quarters, as the right one has room for, and a
# numbered display likewise, which runs into the right margin too; a
# list's item's line in no language that fits the text's width but not
# the item's, fitted to the item's line, in a tagged PDF, where latex-lab's
# verbatim indents it by a paragraph shape, and in an untagged one (the
# target untagged), where LaTeX's own verbatim indents it by its left skip,
# which isn't the line's to measure; a list's item holding a block of
# code in no language that runs across a page's break, its lines short, at
# the text's size, not set smaller by the footer's lines, which the output
# routine sets while the block's group is open and which are wider than the
# item's line; and a quotation's lines too long for the paper even at half
# their size, highlighted and in no language, wrapped at the quotation's
# line's end, tagged and untagged.
CODE_MARGINS = ("geometry:\n  - left=0.75in\n  - right=1.5in\n  - top=0.8in\n"
                "  - bottom=0.8in\n  - footskip=0.3in\nclassoption: [oneside]\n")
FIT_CODE_MARGINS = (
    "# Margins\n\nA line that would come within a quarter inch of the paper's edge at three "
    "quarters of its size if its margin were the left one:\n\n```\nRightline = \"" + "r" * 84
    + "\"\n```\n\nA numbered display, likewise:\n\n$$x = "
    + " + ".join("abcdefghijklmnopqrstuvwxyz"[k % 26] for k in range(30)) + " \\tag{1}$$\n\n"
    "1. A list's item whose line in no language fits the text's width but not the item's:\n\n"
    "    ```\n    Itemline = [" + ", ".join(str(i) for i in range(1, 16)) + "]\n    ```\n\n"
    "2. A list's item whose code runs across a page's break:\n\n    ```\n"
    + "".join("    Footline_%02d = %d\n" % (i, i) for i in range(1, 81)) + "    ```\n\n"
    "> A quotation's lines too long for the paper even at half their size:\n>\n> ```python\n"
    "> Quotewrap = \"" + PAPER_WORDS + "\"\n> ```\n>\n> ```\n> Quoteplain = " + PAPER_WORDS
    + "\n> ```\n")
# A page 4 inches tall (CODE_TALL_PAGE, build_code), the default's
# otherwise: a highlighted line too long for a page even wrapped, said to
# run off its foot, wider at the text's size than TeX's largest dimension,
# which stopped LaTeX where the fit measured it, and than a box's width
# TeX can hold; and a line in no language taller than half the page
# wrapped, which breaks across pages.
CODE_TALL_PAGE = ("geometry:\n  - left=1in\n  - right=1in\n  - top=0.8in\n  - bottom=0.8in\n"
                  "  - footskip=0.3in\n  - paperheight=4in\n")
FIT_CODE_TALL = (
    "# Tall\n\nA highlighted line too long for a page even wrapped:\n\n```python\nTallcode = \""
    + TALL_WORDS + "\"\n```\n\nA line in no language taller than half the page wrapped:\n\n"
    "```\nTallplain = " + TALL_WORDS + "\n```\n")
CODE_FOOTER = ("This footer runs to two lines, the first wider than a list's item's line, "
               "which a block of code in an item the output routine interrupts was measured by.")


def build_code(work):
    """FIT_CODE on the default page, in the default's faces, and again in
    Latin Modern (LATIN_MODERN), whose smallest designs of Latin Modern
    Mono are wider for their size, each a target of its own; and
    FIT_CODE_MARGINS on CODE_MARGINS' page, with CODE_FOOTER, in the folder
    beside it ending -margins, and untagged, without it, in its folder
    untagged; and FIT_CODE_TALL on CODE_TALL_PAGE's page, in the folder
    beside it ending -tall: (the PDF's path, Latin Modern's, what the run
    said, the margins book's PDF's path, what its run said, the tall book's
    PDF's path, what its run said)."""
    os.makedirs(work)
    with open(os.path.join(work, "code.md"), "w", encoding="utf-8") as fh:
        fh.write(FIT_CODE)
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  title: Code\n  identifier: org.example.code\n"
                 "  language: en-US\n  contents:\n    - code\n")
    with open(os.path.join(work, "meta.yaml"), "w", encoding="utf-8") as fh:
        fh.write(LATIN_MODERN)
    with open(os.path.join(work, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  pdf:\n    format: pdf\n  latin:\n    format: pdf\n"
                 "    pdf:\n      metadata: meta.yaml\n")
    converted = run(["python3", os.path.join(BIN, "convert.py"), "--quick"], work)
    margins = work + "-margins"
    os.makedirs(margins)
    with open(os.path.join(margins, "margins.md"), "w", encoding="utf-8") as fh:
        fh.write(FIT_CODE_MARGINS)
    with open(os.path.join(margins, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  title: Margins\n  identifier: org.example.margins\n"
                 "  language: en-US\n  contents:\n    - margins\n")
    with open(os.path.join(margins, "page.yaml"), "w", encoding="utf-8") as fh:
        fh.write(CODE_MARGINS)
    with open(os.path.join(margins, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  pdf:\n    format: pdf\n    footer: \"" + CODE_FOOTER + "\"\n"
                 "    pdf:\n      metadata: page.yaml\n"
                 "  untagged:\n    format: pdf\n    pdf:\n      standard: []\n"
                 "      metadata: page.yaml\n")
    margined = run(["python3", os.path.join(BIN, "convert.py"), "--quick"], margins)
    tall = work + "-tall"
    os.makedirs(tall)
    with open(os.path.join(tall, "tall.md"), "w", encoding="utf-8") as fh:
        fh.write(FIT_CODE_TALL)
    with open(os.path.join(tall, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  title: Tall\n  identifier: org.example.tall\n"
                 "  language: en-US\n  contents:\n    - tall\n")
    with open(os.path.join(tall, "page.yaml"), "w", encoding="utf-8") as fh:
        fh.write(CODE_TALL_PAGE)
    with open(os.path.join(tall, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  pdf:\n    format: pdf\n    pdf:\n      metadata: page.yaml\n")
    talled = run(["python3", os.path.join(BIN, "convert.py"), "--quick"], tall)
    return (os.path.join(work, "pdf", "org.example.code.pdf"),
            os.path.join(work, "latin", "org.example.code.pdf"),
            converted.stdout + converted.stderr,
            os.path.join(margins, "pdf", "org.example.margins.pdf"),
            margined.stdout + margined.stderr,
            os.path.join(tall, "pdf", "org.example.tall.pdf"),
            talled.stdout + talled.stderr)


def code_line(path, word):
    """(left, right, how wide each glyph is, on average) of the line of
    code that opens with word, or None: where its first and last glyphs
    are, its glyphs as glyph_lines groups them."""
    if not os.path.exists(path):
        return None
    lines = {}
    for page, baseline, left, right, char in pdftext.glyph_boxes(path):
        lines.setdefault((page, baseline), []).append((left, right, char))
    for glyphs in lines.values():
        if "".join(g[2] for g in glyphs).startswith(word):
            return (glyphs[0][0], glyphs[-1][1], (glyphs[-1][1] - glyphs[0][0]) / len(glyphs))
    return None


def code_checks(code_path, latin_path, said, margins_path, margins_said, tall_path, tall_said):
    """The code book's checks (build_code), and its margins book's. The
    default page is US Letter with an inch at the sides: its text runs from
    72 points to 540, 468 points, and a quarter inch inside the paper's
    edge is 594. At 12 points, a character of Plex Mono is 0.6 of the
    type's size wide, and of Latin Modern Mono 0.515, 11.955 PDF points (12
    TeX points) each; a list's item's line is 30 TeX points shorter, a
    quotation's 60, and a footnote's type 10 points. The margins book's
    text runs from 54 points to 504, its right margin room to 594."""
    plex, latin = 0.6 * 11.955, 0.515 * 11.955

    def line(path, word):
        return code_line(path, word) or (0, 0, 0)

    def fitted(path, word, full, low=520):
        """The line ends within the text's width, near its end, in smaller
        type."""
        left, right, advance = line(path, word)
        return low < right <= 540.5 and 0 < advance < full - 0.05

    def glyph_rows(path):
        """[(page, baseline, [(left, right, char)])], top to bottom."""
        if not os.path.exists(path):
            return []
        rows = {}
        for page, baseline, left, right, char in pdftext.glyph_boxes(path):
            rows.setdefault((page, baseline), []).append((left, right, char))
        return [(page, baseline, rows[(page, baseline)])
                for page, baseline in sorted(rows, key=lambda k: (k[0], -k[1]))]

    def beside(word, other):
        """(where the line of code that opens with word ends, where the
        word other beside it in the next column begins), on their baseline;
        (0, 0) where there's none."""
        for _page, _baseline, glyphs in glyph_rows(code_path):
            text = "".join(g[2] for g in glyphs)
            if text.startswith(word) and other in text:
                at = text.index(other, len(word))
                return glyphs[at - 1][1], glyphs[at][0]
        return 0, 0

    def term_above(term, word):
        """The term is a line of its own, the definition's line of code that
        opens with word the line under it."""
        rows = ["".join(g[2] for g in glyphs) for _p, _b, glyphs in glyph_rows(code_path)]
        return any(rows[i] == term and rows[i + 1].startswith(word)
                   for i in range(len(rows) - 1))

    def page_of(path, word):
        for page, _baseline, glyphs in glyph_rows(path):
            if "".join(g[2] for g in glyphs).startswith(word):
                return page
        return None

    def advance_of(glyphs):
        return (glyphs[-1][1] - glyphs[0][0]) / len(glyphs)

    def parts(path, word, indent, step=None):
        """[(page, baseline, glyphs)] of the line of code that opens with
        word, wrapped: its first row, and each after it on its page, a
        wrapped line's parts kept together, that begins the line's
        indentation (indent characters) and two characters further in, a
        character as wide as the first row's, or step where that's given,
        as for an untagged PDF, whose spaces aren't characters."""
        rows = glyph_rows(path)
        for i, (page, _baseline, glyphs) in enumerate(rows):
            if "".join(g[2] for g in glyphs).startswith(word):
                found, step = [rows[i]], step or advance_of(glyphs)
                for later in rows[i + 1:]:
                    if later[0] != page or abs(later[2][0][0] - glyphs[0][0]
                                               - (indent + 2) * step) > 0.5:
                        break
                    found.append(later)
                return found
        return []

    def wrapped(path, whole, indent, piece, advance, full, edge=540, spaces=True):
        """The line whole, indented indent characters, is wrapped (parts),
        its parts holding it all, its spaces among them (where they're
        characters: not in an untagged PDF), each part's characters as wide
        as each other's, advance wide where that's given, smaller than full
        where it isn't, ending inside its line's end (edge, the text's
        unless given), and each but the last filled: less room left at its
        end than the next part's first piece TeX may break after needs,
        piece characters at most, a word, or a letter of a word longer than
        the line."""
        found = parts(path, whole[:indent + 6], indent, None if spaces else advance)
        steps = [advance_of(glyphs) if spaces else advance for _page, _baseline, glyphs in found]
        text = whole if spaces else whole.replace(" ", "")
        return len(found) >= 2 and all(glyphs[-1][1] <= edge + 0.5 for _p, _b, glyphs in found) \
            and "".join(g[2] for _p, _b, glyphs in found for g in glyphs) == text \
            and max(steps) - min(steps) < 0.01 \
            and all(glyphs[-1][1] > edge - (piece + 1) * steps[0] for _p, _b, glyphs in found[:-1]) \
            and (abs(steps[0] - advance) < 0.05 if advance else steps[0] < full - 0.05)

    def deep(path):
        """The line indented deeper than leaves twenty characters to a part
        (PAPER_DEEP): its indentation, and on its row as much of its text
        as fits there whole, a word, or none, its first word in Plex Mono,
        whose character is wider than Latin Modern Mono's, its next rows
        twenty characters from the text's edge, inside it, on one page."""
        rows = glyph_rows(path)
        for i, (page, _baseline, glyphs) in enumerate(rows):
            text = "".join(g[2] for g in glyphs)
            if "Paperdeep" in text and text.strip().startswith("Paperdeep"):
                found = [rows[i - 1]] if text.startswith("Paperdeep") and i > 0 else []
                found.append(rows[i])
                step = advance_of(glyphs[-10:])
                for later in rows[i + 1:]:
                    if later[0] != page or abs(later[2][0][0] - (540 - 20 * step)) > 0.5:
                        break
                    found.append(later)
                return len(found) >= 3 and found[0][0] == page \
                    and all(g[1] <= 540.5 for _p, _b, glyphs in found for g in glyphs
                            if g[2] != " ") \
                    and "".join(g[2] for _p, _b, glyphs in found for g in glyphs) == PAPER_DEEP
        return False

    def joined(path):
        """The line of words joined by no-break spaces (PAPER_JOINED) breaks
        after one, each part after the first opening with a word."""
        found = parts(path, "Paperjoined", 0)
        return len(found) >= 2 and all("".join(g[2] for g in glyphs).startswith("word")
                                       for _p, _b, glyphs in found[1:])

    def pointed(path):
        """Each part of the lines of Hebrew with their points (PAPER_HEB,
        PAPER_POINTED) holds its letters' points, which a fallback font
        HarfBuzz shapes sets before its letters: as many holams as vavs,
        qamatses and shin dots as shins, and daggeshes as bets, where a
        review found a holam on the line before its vav, and a second found
        a line whose every letter had a point unbroken. True where no font
        has Hebrew."""
        found = ["".join(g[2] for g in glyphs) for _p, _b, glyphs in glyph_rows(path)
                 if any("\u05d0" <= g[2] <= "\u05ea" for g in glyphs)]
        return not found or len(found) >= 4 and all(
            text.count("\u05d5") == text.count("\u05b9")
            and text.count("\u05e9") == text.count("\u05b8") == text.count("\u05c1")
            and text.count("\u05d1") == text.count("\u05bc")
            and all(g[1] <= 540.5 for _p, _b, glyphs in glyph_rows(path)
                    for g in glyphs if "\u05d0" <= g[2] <= "\u05ea")
            for text in found)

    def whole_word(path):
        """The word of the line that wraps before it (PAPER_DOTS), which
        fits the next row whole, is on one row, not broken after a dot; and
        the line just long enough for its line by less than half a point
        (PAPER_EXACT) is on one row too, as a highlighted line is."""
        texts = ["".join(g[2] for g in glyphs) for _p, _b, glyphs in glyph_rows(path)]
        word = PAPER_DOTS.split(" = ")[1]
        return any(word in text for text in texts) and PAPER_EXACT in texts

    def marked(path):
        """The line that opens with a mark (PAPER_MARK), which has no width,
        has its parts after the first two characters in, as wide as its
        letters."""
        found = parts(path, PAPER_MARK[:6], 0, None)
        return len(found) >= 2

    def tall_rows(path):
        """[(page, baseline, glyphs)] of the tall book's line in no
        language, wrapped (Tallplain): its first row and each after it at
        the line's indentation and two characters further in, on any page,
        past the running head over a page's first, to the row that ends
        it."""
        rows = glyph_rows(path)
        for i, (_page, _baseline, glyphs) in enumerate(rows):
            if "".join(g[2] for g in glyphs).startswith("Tallplain"):
                step, found = advance_of(glyphs), [rows[i]]
                for later in rows[i + 1:]:
                    if TALL_WORDS.split()[-1] in "".join(g[2] for g in found[-1][2]):
                        break
                    if abs(later[2][0][0] - glyphs[0][0] - 2 * step) < 0.5:
                        found.append(later)
                return found
        return []

    def dashed(path):
        """Each part of the line of hyphened words in no language but its
        last ends after a hyphen, where TeX may break in LaTeX's verbatim
        once its discretionaries are taken out, its exhyphenpenalty 10000."""
        found = parts(path, "Paperdash", 0)
        return len(found) >= 2 and all("".join(g[2] for g in glyphs).endswith("-")
                                       for _p, _b, glyphs in found[:-1])

    def codeline_kids(path):
        """The tags of the structure elements a /codeline element holds,
        none where each line's text is its own marked content."""
        if not os.path.exists(path):
            return {"no PDF"}
        found = set()
        with pdftext.pikepdf.open(path) as pdf:
            def walk(element, inside):
                if isinstance(element, pdftext.pikepdf.Array):
                    for kid in element:
                        walk(kid, inside)
                elif isinstance(element, pdftext.pikepdf.Dictionary) and "/S" in element:
                    if inside:
                        found.add(str(element.S))
                    if element.get("/K") is not None:
                        walk(element.K, inside or element.S == "/codeline")
            walk(pdf.Root.StructTreeRoot.K, False)
        return found

    def spaced(path, pairs):
        """For each (line_, after) of pairs, the line that opens with after,
        line_ (word, indent) wrapped above it: where it's on the page the
        wrapped line ends on, under its last part by as much as each of its
        parts is under the one before; and so for two at least, a page's
        break aside."""
        measured = 0
        for line_, after in pairs:
            found = parts(path, line_[0], line_[1])
            below = next(((page, baseline) for page, baseline, glyphs in glyph_rows(path)
                          if "".join(g[2] for g in glyphs).startswith(after)), None)
            if len(found) < 2 or below is None:
                return False
            step = found[0][1] - found[1][1]
            if step <= 0 or any(abs(a[1] - b[1] - step) > 0.05 for a, b in zip(found, found[1:])):
                return False
            if below[0] == found[-1][0]:
                if abs(found[-1][1] - below[1] - step) > 0.05:
                    return False
                measured += 1
        return measured >= 2

    def overfull(text):
        """[how many points too wide the line of text each target's build
        names is], where each names one line of text alone; [] otherwise."""
        found = re.findall(r"WARNING: 1 line\(s\) of the PDF are more than 3 points wider "
                           r"than the text or table column they're set in, [^\n]*: 1 line\(s\) "
                           r"of text; the widest is a line of text on code, (\d+) points too wide",
                           text)
        return ([int(points) for points in found]
                if len(found) == text.count("line(s) of the PDF") else [])
    items = [
        ("a block of code whose lines fit theirs is set at the text's size, in Plex Mono as "
         "in Latin Modern Mono",
         lambda: abs(line(code_path, "def shortline")[2] - plex) < 0.05
         and abs(line(latin_path, "def shortline")[2] - latin) < 0.05),
        ("a highlighted line too long for its line, and one in no language, which the "
         "writer sets in LaTeX's verbatim, are set smaller to fit it, the block's other "
         "lines with them",
         lambda: fitted(code_path, "def longline", plex)
         and fitted(code_path, "Plainlong", plex)
         and fitted(latin_path, "def longline", latin)
         and abs(line(code_path, "def longline")[2] - line(code_path, "    return price")[2])
         < 0.05),
        ("a line in a list's item that fits the text's width but not the item's is fitted "
         "to the item's",
         lambda: line(code_path, "Listline")[0] > 90 and fitted(code_path, "Listline", plex)
         and 62 * plex < 468),
        ("a line in no language too long for its line even at three quarters of its size is "
         "set at three quarters, running on into the margin, and the build names it as code, "
         "with a line that would come within a quarter inch of the paper's edge, one that "
         "would at half its size, and a footnote's line still too wide, and not a "
         "quotation's line, which runs past the quotation's line but not the text's",
         lambda: abs(line(code_path, "Marginline")[2] - 0.75 * plex) < 0.05
         and 540.5 < line(code_path, "Marginline")[1] <= 594
         and re.search(r"4 block\(s\) of code, still wider than the text in smaller type, the "
                       r"smallest at \d+% of its size, run into the margin on its right, the "
                       r"widest \d+ points wider: on code\.", said)),
        ("one that would come within a quarter inch of the paper's edge at three quarters "
         "of its size is set smaller, to end that far inside it, in Plex Mono and in Latin "
         "Modern Mono, whose smallest design is wider for its size",
         lambda: all(560 < line(path, "Roomline")[1] <= 594
                     and 0 < line(path, "Roomline")[2] < 0.75 * full - 0.05
                     for path, full in ((code_path, plex), (latin_path, latin)))),
        # Set smaller to end a little further in than a quarter inch, as
        # the fit aims, it would need less than half its size; at half it
        # still ends inside, and isn't wrapped.
        ("one that would come within a quarter inch of the paper's edge even at half its "
         "size, but for the little more room the fit aims to leave, is set at half, inside "
         "that edge, its line whole",
         lambda: abs(line(code_path, "Halfline")[2] - 0.5 * plex) < 0.05
         and 560 < line(code_path, "Halfline")[1] <= 594
         and len(parts(code_path, "Halfline", 0)) == 1),
        ("a line too long for the paper even at half its size, highlighted or in no "
         "language, is set at three quarters of its size, wrapped where it reaches its "
         "line's end, every part of it inside the text's width, each after the first after "
         "the line's indentation and two characters more, each but the last filled, a line "
         "of one word broken between its letters, not hyphenated, and a line of words at its "
         "spaces, a line of words joined by no-break spaces after one, a word that fits the "
         "next row whole moved there, a line of hyphened words in no language after a "
         "hyphen, a line longer than its line by less than half a point not broken, a line "
         "that opens with a mark two characters in, a long word after "
         "an indentation broken in the word, not after the indentation, a line indented "
         "deeper than leaves twenty characters to a part broken after its indentation, "
         "twenty characters from the line's end, and Hebrew with each letter's points, a "
         "line with a point on every letter among them, its "
         "parts on one page, one where a page ends going on to the next whole, its text one "
         "line of code in the PDF's structure, no paragraph of its own, in Plex Mono and in "
         "Latin Modern Mono, and the build says so, warning of nothing too wide for the "
         "paper",
         lambda: all(wrapped(path, whole, indent, piece, advance, full)
                     for path, advance, full in ((code_path, 0.75 * plex, plex),
                                                 (latin_path, None, latin))
                     for whole, indent, piece in (
                         ("Paperline = \"" + "y" * 200 + "\"", 0, 1),
                         ("Paperhyphen = \"" + PAPER_HYPHEN + "\"", 0, 1),
                         ("    Paperwords = \"" + PAPER_WORDS + "\"", 4, 7),
                         ("\u00a0\u00a0Papernbsp = \"" + PAPER_WORDS + "\"", 2, 7),
                         ("Paperplain = " + PAPER_WORDS, 0, 7),
                         ("Paperdash = " + PAPER_DASHES, 0, 6),
                         (PAPER_LEAD, 60, 1),
                         (PAPER_JOINED, 0, 7),
                         ("Pagefoot = " + FOOT_WORDS, 0, 7)))
         and codeline_kids(code_path) == set()
         and all(dashed(path) and deep(path) and pointed(path) and joined(path)
                 and whole_word(path) and marked(path)
                 for path in (code_path, latin_path))
         and "Fitted 17 table(s), formula(s), and block(s) of code too wide for their lines "
         "to them: 17 in smaller type" in said
         and said.count("4 block(s) of code with a line too long for the paper even at half "
                        "their size are set at 75% of their size, each line too long for its "
                        "line wrapped where it reaches the line's end: on code.") == 2
         and "too wide for the paper" not in said),
        ("a line after a wrapped one, wrapped or not, is set at the block's spacing under the "
         "wrapped line's last part, as its parts are under each other, where no page's break "
         "parts them",
         lambda: all(spaced(path, ((("Paperline", 0), "Paperhyphen"),
                                   (("Paperhyphen", 0), "    Paperwords"),
                                   (("    Paperwords", 4), "\u00a0\u00a0Papernbsp"),
                                   (("\u00a0\u00a0Papernbsp", 2), "Paperafter"),
                                   (("Paperplain", 0), "Paperdash")))
                     for path in (code_path, latin_path))),
        ("a footnote's code is fitted to the footnote's line, a footnote's in a table's cell "
         "too, whose text is set after the table",
         lambda: fitted(code_path, "Noteline", 0.6 * 9.963, low=500)
         and fitted(code_path, "Cellnote", 0.6 * 9.963, low=500)),
        ("a line in no language with hyphens, too long for its line, is set smaller to fit "
         "it, whole, not broken after a hyphen, as ragged right let TeX break it",
         lambda: fitted(code_path, "Hyphenline", plex)),
        ("a quotation's line, too long for the quotation's line, is fitted to it, at three "
         "quarters of its size, inside the text's",
         lambda: abs(line(code_path, "Quoteline")[2] - 0.75 * plex) < 0.05
         and 500 < line(code_path, "Quoteline")[1] <= 540.5),
        ("a definition that opens with code has its term on a line of its own above the "
         "code, highlighted or in no language",
         lambda: term_above("Termone", "Defline") and term_above("Termtwo", "Plaindef")
         and abs(line(code_path, "Defline")[2] - plex) < 0.05),
        ("code in a table's cell, in no language or highlighted, each in a table of its own, "
         "too wide for its column, fits it once its table is fitted, ending before the next "
         "column's words",
         lambda: all(0 < end < start - 1 for end, start in
                     (beside("Cellplain", "Beside"), beside("Cellcode", "Besidetwo")))
         and 0 < line(code_path, "Cellplain")[2] < plex - 0.05
         and 0 < line(code_path, "Cellcode")[2] < plex - 0.05),
        ("a footnote's code in no language still too wide for its line runs into the margin, "
         "named as code, not again as a line of text, which LaTeX reports it as, at a line of "
         "the file it's read from; and a footnote's words too wide for its line, whose last "
         "block is code, are named as a line of text, which LaTeX reports at the line the "
         "footnote's text ends on",
         lambda: 540.5 < line(code_path, "Notewide")[1] <= 594
         and len(overfull(said)) == 2 and min(overfull(said)) > 50),
        ("each line's text is as written, its spaces kept, fitted or not, a line of Hebrew "
         "with its points holding its characters",
         lambda: os.path.exists(code_path)
         and [line_ for line_ in pdftext.code_lines(code_path)
              if not line_.startswith(("Paperheb", "Paperpointed"))]
         == ["def shortline(p):", "    return p", CODE_LONG, "    return price",
             "Plainlong = \"" + "abcdefghijklmnopqrstuvwxyz" * 2 + "abcdefghijkl\"",
             "Listline = [" + ", ".join(str(i) for i in range(1, 16)) + "]",
             "Marginline = \"" + "x" * 80 + "\"", "Roomline = \"" + "w" * 109 + "\"",
             "Halfline = \"" + "h" * 130 + "\"",
             "Paperline = \"" + "y" * 200 + "\"", "Paperhyphen = \"" + PAPER_HYPHEN + "\"",
             "    Paperwords = \"" + PAPER_WORDS + "\"",
             "\u00a0\u00a0Papernbsp = \"" + PAPER_WORDS + "\"", "Paperafter = 1",
             "Paperplain = " + PAPER_WORDS, "Paperdash = " + PAPER_DASHES,
             PAPER_EXACT, PAPER_LEAD, PAPER_DEEP, PAPER_JOINED, PAPER_DOTS, PAPER_MARK,
             "Noteline = \"" + "z" * 70 + "\"",
             "Hyphenline = \"" + "abcd-" * 12 + "abcd\"", "Quoteline = \"" + "q" * 64 + "\"",
             "Defline = 1", "Plaindef = 2", CODE_CELL[0], CODE_CELL[1],
             "Cellnote = \"" + "c" * 87 + "\"", "Notewide = \"" + "n" * 106 + "\"",
             "Footcode = 1", "Pagefoot = " + FOOT_WORDS]
         and [sorted(line_) for line_ in pdftext.code_lines(code_path)
              if line_.startswith(("Paperheb", "Paperpointed"))]
         == [sorted(PAPER_HEB), sorted(PAPER_POINTED)]),
        ("on a one-sided page whose right margin is wider than its left, a line too long "
         "even at three quarters of its size runs into the right margin at three quarters, "
         "as far as a quarter inch from the paper's edge, the left margin's width aside, and "
         "a numbered display too",
         lambda: abs(line(margins_path, "Rightline")[2] - 0.75 * plex) < 0.05
         and 560 < line(margins_path, "Rightline")[1] <= 594
         and "Fitted 5 table(s), formula(s), and block(s) of code too wide for their lines "
         "to them: 5 in smaller type, the smallest at 75% of its size." in margins_said),
        # The quotation's lines end 30 points (29.9 PDF points) inside the
        # text's edge, at 504; fancyvrb's line is as wide as the text less
        # the quotation's left margin, and latex-lab's verbatim sets a
        # paragraph shape 30 points shorter than the quotation's line, and
        # LaTeX's own verbatim, untagged, a left skip alone.
        ("a quotation's lines too long for the paper even at half their size wrap at the "
         "quotation's line's end, highlighted or in no language, in a tagged PDF and in an "
         "untagged one",
         lambda: all(wrapped(path, whole, 0, 7, 0.75 * plex, plex, edge=474.1, spaces=spaces)
                     for path, spaces in ((margins_path, True), (os.path.join(
                         os.path.dirname(os.path.dirname(margins_path)), "untagged",
                         os.path.basename(margins_path)), False))
                     for whole in ("Quotewrap = \"" + PAPER_WORDS + "\"",
                                   "Quoteplain = " + PAPER_WORDS))),
        ("a highlighted line too long for a page even wrapped is said to run off its foot, "
         "and one wider than TeX's largest dimension at the text's size doesn't stop LaTeX "
         "where it's measured; a line in no language taller than half the page wrapped "
         "breaks across pages, each part inside the page's text",
         lambda: "WARNING: 1 block(s) of code in a language has a line too long for a page "
         "even wrapped, which runs off its page's foot: on tall." in tall_said
         and os.path.exists(tall_path)
         and pdftext.code_lines(tall_path) == ["Tallcode = \"" + TALL_WORDS + "\"",
                                              "Tallplain = " + TALL_WORDS]
         and len(tall_rows(tall_path)) > 20
         and "".join(g[2] for _p, _b, glyphs in tall_rows(tall_path) for g in glyphs)
         == "Tallplain = " + TALL_WORDS
         and len({page for page, _b, _g in tall_rows(tall_path)}) >= 2
         and all(57 < baseline < 230 and glyphs[-1][1] <= 540.5
                 for _p, baseline, glyphs in tall_rows(tall_path))),
        # An untagged PDF's spaces in code aren't characters, so its line's
        # glyphs are fewer than its characters: its end is the measure.
        ("a list's item's line in no language that fits the text's width but not the item's "
         "is fitted to the item's, in a tagged PDF and in an untagged one, whose LaTeX's own "
         "verbatim indents it by its left skip, which isn't measured as the line's",
         lambda: 485 < line(margins_path, "Itemline")[1] <= 504.5
         and 0 < line(margins_path, "Itemline")[2] < plex - 0.05 and 62 * plex < 450
         and abs(line(os.path.join(os.path.dirname(os.path.dirname(margins_path)), "untagged",
                                   os.path.basename(margins_path)), "Itemline")[1]
                 - line(margins_path, "Itemline")[1]) < 0.5),
        ("a list's item's code that runs across pages, a footer wider than the item's line "
         "under each, is set at its size: the footer's lines, which the output routine sets "
         "while the code's group is open, aren't measured as the code's",
         lambda: all(abs(line(margins_path, "Footline_%02d" % i)[2] - plex) < 0.05
                     for i in (1, 80))
         and page_of(margins_path, "Footline_01") is not None
         and (page_of(margins_path, "Footline_80") or 0) > page_of(margins_path, "Footline_01")),
    ]
    if shutil.which("verapdf") or os.environ.get("VERAPDF"):
        items.append(("veraPDF finds nothing in the code book's PDF, nor its margins book's",
                      lambda: all(os.path.exists(path) and not pdfcheck.run_verapdf(
                          outputcheck.find_validator("verapdf"), path)
                          for path in (code_path, margins_path))))
    return items


# build-pdf.py as a module, its name for IBM Plex Math's file one no TeX
# has, run on a copy of the default book: the book as LaTeX sets it where
# TeX lacks a file of Plex's (build-pdf.py's default_faces).
LACKING_PLEX = ("import importlib.util, sys\n"
                "spec = importlib.util.spec_from_file_location('build_pdf', sys.argv[1])\n"
                "build_pdf = importlib.util.module_from_spec(spec)\n"
                "spec.loader.exec_module(build_pdf)\n"
                "build_pdf.PLEX_MATH = 'NoSuchMath-Regular.otf'\n"
                "sys.argv = sys.argv[1:]\n"
                "sys.exit(build_pdf.main())\n")


def build_default(work):
    """The book (write_book) on the PDF target's default page, in its
    faces, where its checks measure it on the class's (CLASS_PAGE), in
    Latin Modern: every kind of thing it holds, ragged right, in 12pt type
    on the default's margins, in IBM Plex. And a copy of it, its PDF built
    again where TeX lacks a file of Plex's (LACKING_PLEX), in the folder
    beside it ending -lacking. (The PDF's path, what the run said, the
    copy's PDF's path, and what its build said.)"""
    write_book(work)
    with open(os.path.join(work, "front.md"), "w", encoding="utf-8") as fh:
        fh.write(FRONT.replace(CLASS_PAGE, ""))
    converted = run(["python3", os.path.join(BIN, "convert.py"), "--quick"], work)
    lacking = work + "-lacking"
    shutil.copytree(work, lacking)
    lacking_path = os.path.join(lacking, "pdf", "org.example.pdf.pdf")
    if os.path.exists(lacking_path):
        os.remove(lacking_path)
    rebuilt = run(["python3", "-c", LACKING_PLEX, os.path.join(BIN, "build-pdf.py"), "-d",
                   lacking, "--target", "pdf", "--intermediates", lacking], lacking)
    return (os.path.join(work, "pdf", "org.example.pdf.pdf"),
            converted.stdout + converted.stderr, lacking_path, rebuilt.stdout + rebuilt.stderr)


def bar_limits(path):
    """[(how far the upper limit's baseline is above the formula's, how far
    the lower limit's is below it)] for each evaluation bar on the bars
    page (BLANK_LINES), the display's and the one in text: a line between
    one holding the upper limit, 5, alone and one holding the lower, 0."""
    rows = [row for page, lines in sorted(glyph_lines(path).items()) for row in lines]
    return [(rows[i - 1][0] - rows[i][0], rows[i][0] - rows[i + 1][0])
            for i in range(1, len(rows) - 1)
            if rows[i - 1][3] == "5" and rows[i + 1][3] == "0"]


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


def font_sizes(reader, page, face):
    """The sizes a page draws text in a font whose name holds face at, as
    sizes_by_page reads them."""
    import math
    found = set()

    def visit(text, cm, tm, font, size):
        if font is not None and face in str(font.get("/BaseFont", "")) and text.strip():
            found.add(round(size * math.hypot(tm[0], tm[1]) * math.hypot(cm[0], cm[1]), 2))
    reader.pages[page].extract_text(visitor_text=visit)
    return found


def code_advance(path, words):
    """How wide each glyph of the line holding words is, on average: the
    line's width over its glyphs, None for no such line."""
    lines = {}
    for page, baseline, left, right, char in pdftext.glyph_boxes(path):
        lines.setdefault((page, baseline), []).append((left, right, char))
    for glyphs in lines.values():
        if words in "".join(g[2] for g in glyphs):
            return (glyphs[-1][1] - glyphs[0][0]) / len(glyphs)
    return None


def head_of(source, words):
    """The LaTeX of the longtable holding words, from its column
    specification through its first head ("" if none holds them)."""
    for chunk in source.split("\\begin{longtable}")[1:]:
        table = chunk.split("\\end{longtable}")[0]
        if words in table:
            return table.split("\\endhead")[0]
    return ""


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


def text_order(path, words):
    """For each of words, where the innermost structure element holding
    them comes in the tree, in order, or None where none does."""
    found = [" ".join(text.split()) for _, _, text, _ in deep_texts(path)]
    return [max((i for i, text in enumerate(found) if w in text), default=None) for w in words]


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


def blank_runs(path):
    """For each line holding a run of underscores, in order: how many it
    has, whether any overlaps the one before it, and where its last
    ends."""
    lines = {}
    for page, baseline, left, right, char in pdftext.glyph_boxes(path):
        lines.setdefault((page, baseline), []).append((left, right, char))
    found = []
    for glyphs in lines.values():
        run = [g for g in glyphs if g[2] == "_"]
        if run:
            found.append((len(run), any(b[0] < a[1] - 0.01 for a, b in zip(run, run[1:])),
                          run[-1][1]))
    return found


def blank_at(path, words):
    """For the line whose text holds words and a run of underscores: how
    many underscores the run has, whether any overlaps the one before it,
    and where its first starts and its last ends; None for no such line."""
    lines = {}
    for page, baseline, left, right, char in pdftext.glyph_boxes(path):
        lines.setdefault((page, baseline), []).append((left, right, char))
    for glyphs in lines.values():
        if words in "".join(g[2] for g in glyphs):
            run = [g for g in glyphs if g[2] == "_"]
            if run:
                return (len(run), any(b[0] < a[1] - 0.01 for a, b in zip(run, run[1:])),
                        run[0][0], run[-1][1])
    return None


def blank_spans(path):
    """For each line holding a run of underscores, in order: how many it
    has, whether any overlaps the one before it, and where its first
    starts and its last ends."""
    lines = {}
    for page, baseline, left, right, char in pdftext.glyph_boxes(path):
        lines.setdefault((page, baseline), []).append((left, right, char))
    found = []
    for glyphs in lines.values():
        run = [g for g in glyphs if g[2] == "_"]
        if run:
            found.append((len(run), any(b[0] < a[1] - 0.01 for a, b in zip(run, run[1:])),
                          run[0][0], run[-1][1]))
    return found


def blanks_on_line(path, words):
    """For the line whose text holds words: each run of underscores on it,
    in order, as (how many it has, whether any overlaps the one before it,
    where its first starts, where its last ends); None for no such line."""
    lines = {}
    for page, baseline, left, right, char in pdftext.glyph_boxes(path):
        lines.setdefault((page, baseline), []).append((left, right, char))
    for glyphs in lines.values():
        if words in "".join(g[2] for g in glyphs):
            found, run = [], []
            for glyph in glyphs + [(0, 0, "")]:
                if glyph[2] == "_":
                    run.append(glyph)
                elif run:
                    found.append((len(run),
                                  any(b[0] < a[1] - 0.01 for a, b in zip(run, run[1:])),
                                  run[0][0], run[-1][1]))
                    run = []
            return found
    return None


def blank_box(path, words):
    """(page index, box) for the run of underscores on the line whose text
    holds words, the box as veraPDF gives a check's location, [left,
    bottom, right, top] in points; None for no such line."""
    lines = {}
    for page, baseline, left, right, char in pdftext.glyph_boxes(path):
        lines.setdefault((page, baseline), []).append((left, right, char))
    for (page, baseline), glyphs in lines.items():
        if words in "".join(g[2] for g in glyphs):
            run = [g for g in glyphs if g[2] == "_"]
            if run:
                return page, [run[0][0], baseline - 3, run[-1][1], baseline + 9]
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
# page's geometry and setspace, scrextend for the sized book's 13.5pt,
# multirow for the book's table with a cell spanning rows, the fancy
# book's Plex Serif, and for the notes book cancel and pict2e, for its
# terms struck out of its formulas, which neither TinyTeX nor TeX Live's
# medium scheme has, and luacolor and lua-ul, not in TinyTeX, for its
# blanks struck out, underlined, and marked (docs/installation.md).
SUITE_TEX = [("geometry", "geometry.sty"), ("setspace", "setspace.sty"),
             ("koma-script", "scrextend.sty"), ("multirow", "multirow.sty"),
             ("plex", "IBMPlexSerif-Regular.otf"), ("cancel", "cancel.sty"),
             ("pict2e", "pict2e.sty"), ("luacolor", "luacolor.sty"),
             ("lua-ul", "lua-ul.sty")]
# And what any tagged PDF loads, which TinyTeX lacks too (docs/
# installation.md's first tlmgr line): LaTeX's tagging code, latex-lab's,
# which \DocumentMetadata reads, and tagpdf; luamml, for the formulas'
# MathML; and selnolig, which Pandoc's template loads under LuaLaTeX for a
# book with a language, and luatexbase, which selnolig loads.
PDF_TEX = [("latex-lab", "documentmetadata-support.ltx"), ("tagpdf", "tagpdf.sty"),
           ("luamml", "luamml.sty"), ("luatexbase", "luatexbase.sty"),
           ("selnolig", "selnolig.sty")]


def tex_missing():
    """The packages of SUITE_TEX and PDF_TEX TeX can't find, none where
    there's no kpsewhich to ask."""
    if not shutil.which("kpsewhich"):
        return []
    return [package for package, name in PDF_TEX + SUITE_TEX
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
        with open(report, encoding="utf-8-sig", newline="") as fh:
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


def default_checks(default_path, default_said, lacking_path, lacking_said):
    """The default book's checks (build_default): the book on the page a
    book gets when nothing changes it, in the faces it gets, and as it's
    set where TeX lacks them."""
    fonts = font_names(pypdf.PdfReader(default_path)) if os.path.exists(default_path) \
        else set()
    lacking = font_names(pypdf.PdfReader(lacking_path)) if os.path.exists(lacking_path) \
        else set()
    spec = importlib.util.spec_from_file_location("build_pdf", os.path.join(BIN, "build-pdf.py"))
    build_pdf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_pdf)

    def named(fields, value="A Face"):
        """Metadata naming a face for each field, as Pandoc gives it."""
        return {field: {"t": "MetaString", "c": value} for field in fields}

    def files(meta, value="A Face"):
        """The files of the default's faces LaTeX looks for, given the
        metadata's fields, and whether it sets the formulas' face."""
        latex = build_pdf.default_faces(named(meta, value))
        return (re.findall(r"\\IfFontExistsTF\{([^}]*)\}", latex),
                "\\setmathfont{IBMPlexMath-Regular.otf}" in latex)
    shapes = ("Regular", "Bold", "Italic", "BoldItalic")
    # The book's one character no font has, Latin Modern's fallbacks
    # filling in for the rest as they do for Plex.
    unfilled = ("WARNING: 3 character(s) the fonts don't have are missing from the PDF: "
                "\u6f22 (U+6F22) x3.")
    plex = ["IBMPlex%s-%s.otf" % (face, shape) for face in ("Serif", "Sans", "Mono")
            for shape in shapes]
    items = [("the book on the PDF target's default page builds, LaTeX stopping on "
              "nothing in it", lambda: os.path.exists(default_path)),
             ("and it's in the default's faces, IBM Plex: its text in Plex Serif, its code "
              "in Plex Mono, and its formulas in IBM Plex Math, whose letters are Plex "
              "Serif's, with the fallback fonts for a character they lack, the run saying "
              "nothing of the faces",
              lambda: all(any(face in name for name in fonts) for face in
                          ("IBMPlexSerif-Regular", "IBMPlexMono", "IBMPlexMath-Regular"))
              and not any("LMRoman" in name or "LatinModern" in name for name in fonts)
              and "default faces" not in default_said and unfilled in default_said),
             ("where TeX lacks a file of Plex's, its math font's here, the book is set in "
              "Latin Modern, as it was before Plex was the default, with the fallback "
              "fonts, and the run warns, naming the file, the package that has them, and "
              "how to keep Latin Modern without the warning",
              lambda: any("LMRoman" in name for name in lacking)
              and any("LatinModernMath" in name for name in lacking)
              and not any("IBMPlex" in name for name in lacking)
              and unfilled in lacking_said
              and re.search(r"WARNING: TeX lacks the PDF's default faces, IBM Plex and IBM Plex "
                            r"Math, so the book is set in Latin Modern: LaTeX found no "
                            r"NoSuchMath-Regular\.otf\. TeX Live's plex package has them: for "
                            r"TinyTeX or TeX Live from tug\.org, (?:sudo (?:\S*/)?)?tlmgr "
                            r"install plex, and for Debian's or Ubuntu's texlive packages, sudo "
                            r"apt install texlive-fonts-extra\. To keep Latin Modern without "
                            r"this warning, name Latin Modern's faces in the pdf\.metadata file "
                            r"\(docs/configuration\.md, \"The faces\"\)\.", lacking_said)),
             ("LaTeX looks for every file of the default's faces it would set, those of "
              "each family the metadata file doesn't name, and IBM Plex Math's where it "
              "names neither a face for the text nor one for formulas, which only then "
              "are in Plex Math",
              lambda: files([]) == (plex + ["IBMPlexMath-Regular.otf"], True)
              and files(["mainfont"]) == (plex[4:], False)
              and files(["mathfont"]) == (plex, False)
              and files(["mainfont", "monofont"]) == (plex[4:8], False)
              and files(["mainfont"], "") == (plex + ["IBMPlexMath-Regular.otf"], True)
              and build_pdf.default_faces(named(["mainfont", "sansfont", "monofont"])) == ""),
             ("and the warning says what's set in Latin Modern: the book, where every family "
              "and the formulas are the default's, and otherwise each the file doesn't name",
              lambda: "so its sans-serif type and monospaced type are set in Latin Modern: "
              "LaTeX found no IBMPlexSans-Regular.otf, nor 7 more of their files." in
              build_pdf.face_warning(plex[4:], named(["mainfont"]))
              and "TeX lacks the PDF's default faces, IBM Plex, so its monospaced type is set "
              "in Latin Modern: LaTeX found no IBMPlexMono-Regular.otf." in
              build_pdf.face_warning(plex[8:9], named(["mainfont", "sansfont", "mathfont"]))
              and "IBM Plex, so its text, sans-serif type, and monospaced type are set in "
              "Latin Modern" in build_pdf.face_warning(plex, named(["mathfont"]))
              and "IBM Plex and IBM Plex Math, so the book is set in Latin Modern" in
              build_pdf.face_warning(plex, {})),
             ("a face the file names, set again after the default's text face, is given a "
              "scale, so that fontspec works its size out again: the last its options "
              "give, or the template's own",
              lambda: build_pdf.rescaled([]) == ["Scale=MatchLowercase"]
              and build_pdf.rescaled(["Scale = 0.9", "Ligatures=TeX"])
              == ["Scale = 0.9", "Ligatures=TeX", "Scale = 0.9"]),
             ("code is set in Plex Mono at the text's size, its small letters as tall as Plex "
              "Serif's, each character 0.6 of the size wide, and formulas at the text's size",
              lambda: (lambda advance, page: advance is not None
                       and abs(advance - 0.6 * 11.955) < 0.05 and page is not None
                       and max(font_sizes(pypdf.PdfReader(default_path), page, "IBMPlexMath")
                               or {0}) == 11.96)(
                  code_advance(default_path, "def demand(p):"),
                  page_holding(default_path, "Inline math"))),
             ]
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
        ("a picture in a page's LaTeX, a circle asked for at 80 points, is drawn with a "
         "path by pict2e, four curves, no glyph of LaTeX's lcircle10 font, which maps to no "
         "character",
         lambda: reader is not None and "LCIRCLE10" not in pdftext.base_fonts(preamble_path)
         and not {"LINE10", "LINEW10"} & pdftext.base_fonts(preamble_path)
         and sorted(pdftext.curves(preamble_path).values()) == [4]),
        ("a math font, and a monospaced face with fallbacks of its own, that the file "
         "names, and no face for the text, are scaled to the default's text face: "
         "formulas at the text's size, not a sixth smaller, and Latin Modern Mono, its "
         "small letters a sixth smaller than IBM Plex Serif's, a fifth larger than the text",
         lambda: (lambda page: page is not None
                  and max(font_sizes(reader, page, "IBMPlexMath") or {0}) == 11.96
                  and abs(max(font_sizes(reader, page, "LMMono") or {0}) - 14.31) < 0.05
                  and sizes_by_page(reader, "The section")[page][:1] == [11.96])(
             page_holding(preamble_path, "The section"))),
    ]

def gap_after(path, words):
    """The space, in points, between the end of words and the next glyph
    that isn't a space on its line, or None."""
    rows = {}
    for page, baseline, left, right, char in pdftext.glyph_boxes(path):
        rows.setdefault((page, baseline), []).append((left, right, char))
    for glyphs in rows.values():
        glyphs.sort()
        text = "".join(g[2] for g in glyphs)
        at = text.find(words)
        if at >= 0:
            after = next((g for g in glyphs[at + len(words):] if g[2].strip()), None)
            return after[0] - glyphs[at + len(words) - 1][1] if after else None
    return None


# A wrapping table's fit on the second run, as Introductory Business
# Statistics 2e's Table A7 of F's critical values was measured on it: set
# at 61.3 percent of its size, its columns at 0.3573 of their widths, on
# the first run, where longtable's widths under a head across its columns
# had it hundreds of points too wide, its longest piece, "denominator",
# 0.9801 of its column, the shares of the line its 13 columns, half an em
# apart, have 1.7347 together, in 12-point type on a line of 469.755
# points with 578.16 of room. Fitted with its spaces counted at the size
# it had, it was set at 98.8 percent, "denominator" 3.4 points too wide.
WRAP_REFIT = {"factor": 0.613, "columns": 0.3573, "tight": 0.9801, "shares": 1.7347,
              "count": 13, "size": 12, "line": 469.755, "room": 578.16}


def wrap_refit(case):
    """(ratio, factor, columns) for FIT_MACROS' fit of a wrapping table
    (WRAP_REFIT), its Lua run by texlua: the size and columns it sets, and
    its longest piece against its column at them, the spaces between its
    columns half an em at that size; None without texlua."""
    import latexbuild
    texlua = shutil.which("texlua")
    if texlua is None:
        return None
    macros = latexbuild.FIT_MACROS
    opening = macros.index("\\directlua{") + len("\\directlua{")
    depth, end = 1, opening
    while depth:
        depth += {"{": 1, "}": -1}.get(macros[end], 0)
        end += 1
    stubs = ("luatexbase = { attributes = { OERFitAttribute = 1 }, add_to_callback = function() end }\n"
             "node = { id = function() return 0 end, subtypes = function() return {} end }\n"
             "tex = { getattribute = function() return 0 end, sprint = function() end }\n"
             "texio = { write_nl = function() end }\n")
    run = """
local sp, c = 65536, {case}
local k = c.count
oerfit.size[1], oerfit.columns[1] = c.size * sp, k
oerfit.sep[1] = 0.25 * c.size * c.factor * sp
local s = {{ narrow = 1, factor = c.factor, columns = c.columns, center = 1 }}
local line, room = c.line * sp, c.room * sp
local pad = 2 * (k - 1) * oerfit.sep[1]
local w = pad + c.shares * s.columns * (line - pad)
local new = oerfit.next("p", 1, s, w, line, room, c.tight)
local spaces = 2 * (k - 1) * 0.25 * c.size * sp * new.factor
print(c.tight * new.factor / s.factor * s.columns * (line - pad) / (new.columns * (line - spaces)),
      new.factor, new.columns)
""".format(case="{ " + ", ".join("%s = %r" % item for item in case.items()) + " }")
    with tempfile.TemporaryDirectory() as work:
        script = os.path.join(work, "refit.lua")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(stubs + macros[opening:end - 1] + run)
        done = subprocess.run([texlua, script], cwd=work, capture_output=True, text=True)
    return tuple(float(x) for x in done.stdout.split()) if done.returncode == 0 else ()


def paragraph_measures(texts):
    """FIT_MACROS' measure of each text as a paragraph (oerfit.paragraph),
    its Lua run by texlua on nodes a character wide: (its least, its width
    as one line). A letter is a glyph, a space glue, an underscore a fill-in
    blank's, ~ a no-break space (a penalty of 10000 and glue), and $ opens
    and closes a formula. [] without texlua or where it fails."""
    import latexbuild
    texlua = shutil.which("texlua")
    if texlua is None:
        return []
    macros = latexbuild.FIT_MACROS
    opening = macros.index("\\directlua{") + len("\\directlua{")
    depth, end = 1, opening
    while depth:
        depth += {"{": 1, "}": -1}.get(macros[end], 0)
        end += 1
    stubs = """
ids = { hlist = 1, vlist = 2, glue = 3, penalty = 4, math = 5, dir = 6, glyph = 7, kern = 8 }
luatexbase = { attributes = { OERFitAttribute = 1, OERFitStepsAttribute = 2, OERBlankAttribute = 99 },
               add_to_callback = function() end }
node = { id = function(name) return ids[name] or 0 end,
         subtypes = function() return {} end,
         traverse = function(head) local i = 0 return function() i = i + 1 return head[i] end end,
         dimensions = function(n) return n.width or 0 end,
         has_attribute = function(n, a, v)
           local x = n.attr and n.attr[a]
           if v then return (x == v) and x or nil end
           return x
         end }
tex = { getattribute = function() return 0 end, sprint = function() end, hsize = 1000000 }
texio = { write_nl = function() end }
"""
    run = """
local function build(s)
  local list, inmath = {}, false
  for c in s:gmatch(".") do
    if c == "$" then
      inmath = not inmath
      list[#list + 1] = { id = ids.math, subtype = inmath and 0 or 1, width = 0 }
    elseif c == " " then
      list[#list + 1] = { id = ids.glue, width = 1 }
    elseif c == "~" then
      list[#list + 1] = { id = ids.penalty, penalty = 10000, width = 0 }
      list[#list + 1] = { id = ids.glue, width = 1 }
    elseif c == "_" then
      list[#list + 1] = { id = ids.glyph, char = 95, width = 1, attr = { [99] = 1 } }
    else
      list[#list + 1] = { id = ids.glyph, char = c:byte(), width = 1 }
    end
  end
  return list
end
for _, s in ipairs({%s}) do
  local line, low = oerfit.paragraph(build(s))
  print(low, line)
end
""" % ", ".join("[==[%s]==]" % text for text in texts)
    with tempfile.TemporaryDirectory() as work:
        script = os.path.join(work, "paragraph.lua")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(stubs + macros[opening:end - 1] + run)
        done = subprocess.run([texlua, script], cwd=work, capture_output=True, text=True)
    if done.returncode != 0:
        print(done.stderr[-500:])
        return []
    numbers = [int(float(x)) for x in done.stdout.split()]
    return list(zip(numbers[0::2], numbers[1::2]))


def formula_widths(texs, count="formula_width(tex)"):
    """pdf-target.lua's formula_width of each TeX in texs, or another of its
    counts of it (a Lua expression of tex), its Lua run by `pandoc lua`, the
    filter read up to the filters it returns; [] where that fails."""
    with open(os.path.join(BIN, "pdf-target.lua"), encoding="utf-8") as fh:
        source = fh.read()
    cut = source.rfind("\nreturn {")
    if cut < 0:
        return []
    script = (source[:cut] + "\nfor _, tex in ipairs({"
              + ", ".join("[==[%s]==]" % tex for tex in texs)
              + "}) do print(" + count + ") end\n")
    with tempfile.TemporaryDirectory() as work:
        path = os.path.join(work, "widths.lua")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(script)
        done = subprocess.run(["pandoc", "lua", path], cwd=work, capture_output=True,
                              text=True, stdin=subprocess.DEVNULL)
    return [int(x) for x in done.stdout.split()] if done.returncode == 0 else []


def fit_checks(fit_path, fit_said, fit_source, fit_third):
    """The fit book's checks (build_fit): what latexbuild's FIT_MACROS did
    with each table and formula too wide for its line. The default page's
    text runs from 72 to 540 points across a paper 612 wide, its type 12
    points, 11.96 of the PDF's; a quarter inch is 18 points."""
    reader = pypdf.PdfReader(fit_path) if os.path.exists(fit_path) else None
    lines = glyph_lines(fit_path) if reader else {}

    def size(words):
        """The size the words are drawn at, or 0."""
        found = [s for sizes in sizes_by_page(reader, words) for s in sizes] if reader else []
        return found[0] if found else 0

    def ends(words):
        """(left, right) of the line holding the words, or (0, 0)."""
        return next(((left, right) for rows in lines.values()
                     for _baseline, left, right, text in rows if words in text), (0, 0))

    def line_of(words):
        """The text of the line holding the words, or ""."""
        return next((text for rows in lines.values()
                     for _baseline, _left, _right, text in rows if words in text), "")

    def leading_before(words, display):
        """The distances between the lines of text from the one holding
        words to the last before the display holding display, on one page,
        leaving out a line of its superscripts."""
        for rows in lines.values():
            texts = [row[3] for row in rows]
            start = next((i for i, text in enumerate(texts) if words in text), None)
            stop = next((i for i, text in enumerate(texts) if display in text), None)
            if start is not None and stop is not None and start < stop:
                kept = [row[0] for row in rows[start:stop] if len(squeezed(row[3])) > 20]
                return [a - b for a, b in zip(kept, kept[1:])]
        return []

    def within(words):
        left, right = ends(words)
        return left >= 71.5 and 0 < right <= 540.5

    def at_edge(count, words=None):
        """Whether a run of count underscores, drawn shorter, ends within
        half a point of the text's right edge: the run on the line holding
        words, or any run of that many."""
        if words:
            found = blank_at(fit_path, words)
            runs = [(found[0], found[1], found[3])] if found else []
        else:
            runs = blank_runs(fit_path)
        return any(n == count and over and 539.5 <= right <= 540.5 for n, over, right in runs)

    def rows_until(first, stop):
        """The lines from the one holding first to the last before the one
        holding stop, on first's page: (baseline, left, right, text)."""
        for rows in lines.values():
            texts = [row[3] for row in rows]
            start = next((i for i, text in enumerate(texts) if first in text), None)
            if start is not None:
                end = next((i for i, text in enumerate(texts) if stop in text and i > start),
                           len(rows))
                return rows[start:end]
        return []

    glyphs = {}
    for page, baseline, left, right, char in (pdftext.glyph_boxes(fit_path) if reader else []):
        if char.strip():
            glyphs.setdefault((page, baseline), []).append((left, right, char))

    def span(words, part):
        """(left, right) of the glyphs of part, its first on the line holding
        words, spaces aside, or None."""
        for boxes in glyphs.values():
            boxes = sorted(boxes)
            text, starts = "", []
            for box in boxes:
                starts.append(len(text))
                text += box[2]
            if words in text and part in text:
                i = text.index(part)
                first = max(k for k, start in enumerate(starts) if start <= i)
                last = max(k for k, start in enumerate(starts) if start <= i + len(part) - 1)
                return boxes[first][0], boxes[last][1]
        return None

    def whole(first, second):
        """Whether a line holds both, two fractions' numerators in one
        formula, unbroken."""
        return any(first in text and second in text
                   for rows in lines.values() for *_, text in rows)

    def centered(words):
        """Run into both margins alike, a quarter inch inside the paper's
        edges."""
        left, right = ends(words)
        return 18 <= left < 69 and 543 < right <= 594 and abs((72 - left) - (right - 540)) < 1

    body = size("which spaces narrowed")
    refit = wrap_refit(WRAP_REFIT)

    def at(words, part):
        """Whether the words are drawn at part of the text's size."""
        return body > 11 and abs(size(words) - part * body) < 0.03

    rules = artifact_rules(fit_path) if reader else {}

    def rules_by(words, rows):
        """How many rules are drawn as artifacts from 20 points above the
        line holding the words to 20 below the line rows - 1 lines after
        it, as a table's are above its first row, under its head, and
        below its last; None for no such line."""
        for page, found in lines.items():
            for i, (baseline, _left, _right, text) in enumerate(found):
                if words in text:
                    last = found[min(i + rows - 1, len(found) - 1)][0]
                    return sum(1 for y in rules.get(page, []) if last - 20 < y < baseline + 20)
        return None
    return [
        ("a table a little too wide for its line fits it with narrower spaces between its "
         "columns, in the text's type",
         lambda: at("Spaced", 1) and within("Spaced")),
        ("a table that needs smaller type as well fits its line in it",
         lambda: 0.75 * body < size("Smaller") < body - 0.1 and within("Smaller")),
        ("a table left a little too wide by its smaller type's design is centered on the "
         "page, and not fitted again for a fit within 4 percent of its line",
         lambda: 0.75 * body + 0.3 < size("Overstep") < 0.8 * body and centered("Overstep")),
        ("a table too wide for its line even at three quarters of its type is centered on "
         "the page, into both margins",
         lambda: at("Centered", 0.75) and centered("Centered")),
        ("and one that would come within a quarter inch of the paper's edge at that size is "
         "set smaller still, a quarter inch inside it",
         lambda: 0.5 * body < size("Margins") < 0.75 * body - 0.1 and centered("Margins")),
        ("a table too wide for the paper even at half its type is set at half, its columns "
         "as the writer sets them, and the build warns of it",
         lambda: at("Overpaper", 0.5)
         and "p{(" not in head_of(fit_source, "Overpaper")
         and re.search(r"WARNING: 1 table\(s\), formula\(s\), or block\(s\) of code are too "
                       r"wide for the paper even in smaller type, the smallest at 50% of its "
                       r"size,[^\n]*: on one\.", fit_said)),
        ("a table of the class float after it, a tabular, isn't fitted by the widths the "
         "longtable before it recorded: in the text's type, its columns 12 points apart",
         lambda: at("Floatcell", 1) and 11.5 < (gap_after(fit_path, "Floatcell") or 0) < 12.5),
        ("and though it floats, its tags are where the text has it, between the paragraphs "
         "before and after it, not after everything else",
         lambda: (lambda order: None not in order and order == sorted(order))(text_order(
             fit_path, ("A floating table after it", "Floatcell",
                        "A table whose head is a cell across")))),
        ("a table whose head is a cell across its columns, which longtable measures too "
         "wide on the first run, is fitted again on the second, in the text's type, its "
         "columns 12 points apart",
         lambda: at("Spanned", 1) and within("Spanned")
         and 11.5 < (gap_after(fit_path, "Spanned") or 0) < 12.5),
        ("a table of formulas, whose math in smaller type is set in wider forms, is fitted "
         "again on the second run",
         lambda: at("Mathcells", 0.75)),
        ("a table whose columns wrap, its longest words together a little too wide for a "
         "line, fits it with narrower spaces, in the text's type, each word whole in its "
         "column",
         lambda: at("Supercalifragilisticexpialidocious", 1)
         and within("SupercalifragilisticexpialidociousHippopotomonstrosesquippedaliophobia")),
        ("a table whose columns wrap, set larger on the second run than on the first, as "
         "a head across its columns can make longtable's first widths ask, is fitted with "
         "its spaces at its new size, its longest piece 98 percent of its column",
         lambda: refit is not None and len(refit) == 3 and 0.97 < refit[0] <= 0.981
         and abs(refit[1] - 0.935) < 0.0005),
        ("a table whose columns' widths are given, a word too long for its column that "
         "LaTeX measures running into the next, is set smaller to fit it",
         lambda: 0.75 * body < size("WWWWWWWWW") < body - 0.1
         and (gap_after(fit_path, "WWWWWWWWW") or 0) > 1),
        # latexbuild.FIT_MACROS: a line that opens in a formula, TeX having
        # dropped the node that opens it at the break, was measured by the
        # pieces between the formula's spaces, as if they were words, so a
        # formula too wide for its column that TeX can't break wasn't
        # fitted, and ran 20 points past it, into the margin; fitted, it
        # ends within the 4 percent of its column a fit may leave it over
        # (3.6 points).
        ("and one whose formula TeX can't break, too wide for its column, opening a line "
         "of its cell, is set smaller to fit it",
         lambda: 0.75 * body < size("Trigcell") < body - 0.1 and 0 < ends("cos")[1] < 544.1),
        # A line of a formula that holds neither its start nor its end, as
        # the first of two does where TeX dropped the start at the break,
        # was measured by the pieces between the formula's spaces, so a
        # formula that opens a line and breaks after an operator, its first
        # line too wide for its column, wasn't fitted, and ran 27 points
        # past it.
        ("and one whose formula, too wide for its column, opens a line of its cell and "
         "breaks after an operator, is set smaller to fit it",
         lambda: 0.75 * body < size("Pluscell") < body - 0.1 and 0 < ends("csc")[1] < 544.1),
        # A line of words that ends at a space before a formula that opens
        # the next line is measured by its words. Taken as the formula's, as
        # a line that ends at a penalty before one is, it would be measured
        # whole, and this table, which narrowing its columns fits, would be
        # set in type three quarters its size.
        ("and one whose columns' widths are more than its line together, a line of words "
         "in a cell before a formula that opens the next, keeps its type, its columns "
         "narrowed to fit it",
         lambda: at("Overgiven", 1) and within("Overgiven")),
        # FIT_MACROS measures a cell's lines before oer.blanks draws a
        # blank shorter to fit its line, and took this one at its full
        # length for a piece TeX can't break, setting the table at 87
        # percent of its size; a blank is three underscores at most to it
        # now.
        ("and one whose columns' widths are given, a fill-in blank too long for its column, "
         "keeps its type, the blank drawn shorter to its column",
         lambda: at("Blankcell", 1) and within("Blankcell") and at_edge(30)),
        # Narrowed, a table is set smaller as its cells' longest pieces ask:
        # taken whole, as on main, this blank set the table at 75 percent of
        # its size, and drawn shorter first, as the blank's macros run first
        # where they come after the fit's, to end where its column does, it
        # would be as wide as its column to the fit, the table at 83.
        ("and one whose columns' widths are more than its line together, a fill-in blank too "
         "long for its column, keeps its type, its columns narrowed, the blank drawn shorter",
         lambda: at("Overblank", 1) and within("Overblank") and at_edge(36)),
        # pdf-target.lua's widths for the columns counted the blank as a word
        # of 64 characters, and gave its column the line, the word of 26
        # letters too, which set the table at 86 percent of its size.
        ("and one whose columns' widths are given, half the line each, a blank longer than "
         "its column beside a word of 26 letters, keeps its type, the word whole",
         lambda: at("Abcdefghijklmnopqrstuvwxyz", 1) and within("Abcdefghijklmnopqrstuvwxyz")
         and at_edge(64)),
        # pdf-target.lua's widths counted the code's run of underscores as
        # a blank, three to a word, and gave its column 10 characters for
        # its 15; LaTeX draws code's underscores whole, and the table was
        # set at 75 percent of its size.
        ("and one whose columns' widths are given, a word of code holding a run of "
         "underscores, which isn't a blank, too long for its column, keeps its type, its "
         "column widened to the code, the underscores drawn whole",
         lambda: at("Codeblank", 1) and within("Codeblank")
         and (lambda found: found is not None and found[0] == 8 and not found[1])(
             blank_at(fit_path, "print("))),
        # oer.blanks drew a blank shorter only where its own underscores ran
        # past its line's end, which these end within; the word joined to
        # them ran 8.8 points past the line.
        ("and one whose cell holds a blank joined to a number, the two longer than its "
         "column, has the blank drawn shorter, the number ending within its line",
         lambda: at("Joincell", 1) and within("12345678901234567890")
         and (lambda found: found is not None and found[1] == 15 and found[2])(
             blank_on_line(fit_path, "12345678901234567890"))),
        # Drawn at two thirds of its column while TeX breaks the cell's
        # lines, the blank's underscores overlap by kerns the fit's measure
        # meets before they're drawn again: counted, they took the blank for
        # less than its three underscores, the table kept its spaces, and the
        # words ran 1.2 points past the column; and counted with every
        # underscore, as a word's letters are, they set the table at 75
        # percent of its size.
        ("and one whose cell holds a blank longer than two thirds of its column with words "
         "joined to it, the three a little longer than the column with the blank at its "
         "shortest, keeps its type, its spaces narrowed, the words within its column, the "
         "blank measured as three underscores",
         lambda: at("Joinlong", 1) and within("8642")),
        # The margin's first fix put the blank's kerns back, as far as the
        # blank, drawn at its shortest while TeX broke the cell's lines,
        # couldn't give them up, before drawing it to fill its line, and it
        # hung 1.8 points past each edge of its column; main, which widens
        # its column for the blank counted whole, began it 1.8 points before
        # its column and ended it 0.6 past. A cell's only line hangs
        # nothing, opening and ending with the array package's struts.
        ("and a blank alone on a middle line of a column too narrow for it, drawn at its "
         "shortest while TeX breaks the cell's lines and then to fill its line, begins and "
         "ends where the column does, hung into neither margin",
         lambda: (lambda found: found is not None and found[0] == 6 and found[1]
                  and 503.5 <= found[2] <= 504.5 and 539.5 <= found[3] <= 540.5)(
             blank_at(fit_path, "Edgy"))),
        # The penalty after the blank, drawn at two thirds of its line, went
        # before the first glue after it, the formula's own, where TeX ended
        # the line: x on the blank's line, and = 1 on the next.
        ("a blank longer than two thirds of its line joined to a formula has the line end "
         "after the formula, which isn't broken",
         lambda: "\U0001d465=1" in line_of("Mathjoin") and "and" not in line_of("Mathjoin")
         and within("Mathjoin")),
        # Drawn at two thirds of its line while TeX broke the paragraph, the
        # blank left a line too loose to end after it, so the next label and
        # its blank shared it, the two blanks drawn shorter, 415 points of
        # their 491.
        ("in a paragraph set flush to both margins, a label and a blank that fit the line "
         "share it, the blank whole, and the next label starts the next line",
         lambda: "Justdate" not in line_of("Justname")
         and (lambda found: found is not None and found[0] == 46 and not found[1])(
             blank_at(fit_path, "Justname"))),
        # With the margin's kern set to nothing and the line's spaces set
        # again at their width, the blank was drawn shorter by the space TeX
        # had taken from them as well as by its hang, 39.9 points of its
        # 43.9; it's left as TeX set it now, as a blank that fits is.
        ("a blank that fits at the end of a line whose spaces TeX shrank to fit it is left "
         "as TeX set it, whole, hung into the margin as microtype hangs it and no further",
         lambda: (lambda found: found is not None and found[0] == 5 and not found[1]
                  and 540.5 < found[3] <= 542)(blank_at(fit_path, "Rightmargin"))),
        # With the kern before its blank set to nothing and the line's spaces
        # set again, the line, whose spaces TeX had shrunk all but all they
        # could, ran 1.3 points past the margin; it's left as TeX set it now,
        # the blank hung into the left margin as microtype hangs it.
        ("and one that opens such a line, its spaces shrunk all but all they could, is left "
         "as TeX set it too, the line ending at the text's edge, not past it, the blank whole",
         lambda: 539.5 <= ends("Leftmargin")[1] <= 540.5
         and (lambda found: found is not None and found[0] == 5 and not found[1])(
             blank_at(fit_path, "Leftmargin"))),
        # With every hang on a line set to nothing where one of its blanks
        # was drawn, the blank that opens the line began at the margin.
        ("a blank that fits keeps its hang beside one drawn on its line, which ends where "
         "the line does",
         lambda: (lambda runs: runs is not None and len(runs) == 2
                  and runs[0][0] == 5 and not runs[0][1] and runs[0][2] < 71.5
                  and runs[1][0] == 50 and runs[1][1] and 539.5 <= runs[1][3] <= 540.5)(
             blanks_on_line(fit_path, "Twoblank"))),
        # Drawn at two thirds of its line while TeX broke the paragraph, and
        # then whole, it began at the margin, its hang set to nothing.
        ("and so does a blank drawn at two thirds of its line that its line has room for "
         "whole",
         lambda: any(n == 37 and not over and left < 71.5
                     for n, over, left, right in blank_spans(fit_path))
         and line_of("Wholeback") != "" and "_" not in line_of("Wholeback")),
        # Measured with the hang of the blank before it set to nothing, the
        # second blank reached past the line's end, and was drawn shorter by
        # 3.2 points.
        ("and a blank that ends short of its line's end as TeX set the line is left whole "
         "where what follows it runs past, the hang of the blank before it counted",
         lambda: (lambda runs: runs is not None and len(runs) == 2
                  and runs[0][0] == 5 and not runs[0][1] and runs[0][2] < 71.5
                  and runs[1][0] == 10 and not runs[1][1] and 538.5 <= runs[1][3] <= 539.5)(
             blanks_on_line(fit_path, "Reachfit"))),
        # Measured at the line's natural spacing, as the blank drawn at two
        # thirds has the line set again, the second blank reached past the
        # line's end, and was drawn shorter, 40.1 points of its 43.9.
        ("and so is one on a line TeX shrank to fit, beside a blank drawn at two thirds, which "
         "gets back its hang, the line having no room without it",
         lambda: (lambda runs: runs is not None and len(runs) == 2
                  and runs[0][0] == 40 and runs[0][1] and runs[0][2] < 71.5
                  and runs[1][0] == 5 and not runs[1][1] and 538.5 <= runs[1][3] <= 539.5)(
             blanks_on_line(fit_path, "Shrunk"))),
        # TeX broke the line before a blank too long for it, which was drawn
        # shorter on a line of its own, the label alone on the line before.
        ("a blank longer than its line shares it with the label before it, drawn shorter to "
         "end where the line does",
         lambda: at_edge(72, "Namelabel") and within("Namelabel")),
        # Without the penalty after the blank, the next label and the word
        # before it shared the first blank's line, their blank on the next.
        ("and the line ends after it, the next label starting the next line, with its own "
         "blank",
         lambda: "Datelabel" not in line_of("Namelabel")
         and at_edge(72, "Datelabel") and within("Datelabel")),
        # A table whose columns don't wrap, as the writer sets one that fits
        # its line by the count, has no lines in a cell to draw a blank
        # shorter on: fitted, it was set at 89 percent of its size, the
        # blank whole.
        ("a table whose columns have no widths, a blank too long for its line, keeps its "
         "type, its columns wrapping, the blank drawn shorter to end within its column",
         lambda: at("Rowblank", 1) and within("Rowblank") and at_edge(52)),
        # Counted whole, as by the counts and by LaTeX's measure, a long
        # blank took the line from the words beside it, which wrapped where
        # they had room: Wordcol's seven words on two lines, and Threecol's
        # name and role each on two.
        ("a table whose columns have no widths, words beside a long blank, gives the words "
         "their line and the blank what's left of it, the blank drawn shorter to end within "
         "its column",
         lambda: at("Wordcol", 1) and "Wordcolloremipsumdolorsitametconsectetur"
         in squeezed(line_of("Wordcol")) and at_edge(66, "Wordcol") and within("Wordcol")),
        ("and two columns of words beside a blank, each on one line",
         lambda: at("Threecol", 1)
         and "ThreecolAlexandraHamiltonProjectcoordinator" in squeezed(line_of("Threecol"))
         and at_edge(58, "Threecol") and within("Threecol")),
        # Given the rest of the line beside the words on one line, Labelsig
        # had less than three times its width, and its blank, drawn at two
        # thirds of the column while TeX broke the cell into lines, went to
        # the line after it.
        ("but a blank after a label keeps its label's line, its least two thirds of its "
         "column, the words wrapping where they don't fit beside that",
         lambda: at("Labelsig", 1) and blank_at(fit_path, "Labelsig") is not None
         and at_edge(66, "Labelsig") and within("Labelsig")
         and "Labelcol" in line_of("Labelcol") and "sed" not in line_of("Labelcol")),
        # FIT_MACROS' measure of a paragraph's least, run by texlua on nodes
        # a character wide: a blank three underscores, or three times the
        # words that share its line, before it and joined to it as far as a
        # space TeX may break at, a formula and a no-break space among
        # them; the line whole where that's less, the words after the last
        # blank whole, and a paragraph with no blank as wide as its line.
        ("LaTeX's measure of a paragraph's least: a blank three underscores, or two thirds of "
         "its line beside the words that share it, joined to it as far as a space TeX may "
         "break at, a formula's and a no-break space's not among them",
         lambda: paragraph_measures(
             ["Signature: " + "_" * 66, "____%", "Name ____ Date: " + "_" * 32,
              "Label: " + "_" * 30 + "~cm and more", "Label: " + "_" * 30 + "$x = y$",
              "Wordcol lorem ipsum", "a. ____", "____/____"])
         == [(33, 77), (4, 5), (18, 48), (30, 49), (36, 42), (19, 19), (7, 7), (8, 9)]),
        # The counts gave the pairs' columns, their fractions counted a part
        # after the other, more of the line than the label's, whose formula
        # broke after its relation, the label and the formula on three lines.
        ("a table whose columns have no widths is laid out as LaTeX measures it, a "
         "label's formula on the label's line, beside pairs with fractions",
         lambda: "log" in line_of("Wholerow") and within("Wholerow")),
        # Taken whole, as a worked example's step is, the sum set the table at
        # half its size, and it still ran past the paper's edges.
        ("and one with a formula too long for the line keeps its type, the formula "
         "breaking within its column, as TeX breaks a formula in text",
         lambda: at("Piecerow", 1)
         and (lambda rows: len(rows) > 1
              and all(left >= 71.5 and 0 < right <= 540.5 for _, left, right, _ in rows))(
             rows_until("Piecerow", "A layout table too wide"))),
        # microtype hangs an underscore into the margin, a fifth of its
        # width in Latin Modern, 1.8 points at 12; LuaTeX puts the margin's
        # kern after the penalty a paragraph ends with, and before the node
        # that opens its first line, not beside the underscore.
        ("a blank that ends a paragraph, drawn shorter to end where its line does, isn't "
         "hung into the margin, nor one that opens a paragraph",
         lambda: within("Endlabel") and within("Startafter") and at_edge(80, "Endlabel")
         and any(n == 76 and over and 71.5 <= left <= 72.5 and 539.5 <= right <= 540.5
                 for n, over, left, right in blank_spans(fit_path))),
        ("a layout table set smaller keeps its caption, a paragraph before it, in the text's "
         "type",
         lambda: at("Laycap", 1) and 0 < size("Laytable") < body - 0.1),
        ("a table of 45 columns whose widths are given, the spaces between them more than "
         "its line, has them narrowed on the first run and is fitted on the second, a quarter "
         "inch inside the paper's edges, its first column clear of the next",
         lambda: 0.5 * body - 0.03 < size("Qz") < body - 0.1
         and 18 <= ends("Qz")[0] and 0 < ends("Qz")[1] <= 594
         and (gap_after(fit_path, "Qz") or 0) > 0.5),
        # Laid out as LaTeX measures it, set smaller after the second run, at
        # 7.3 points (at 6.05 where the counts laid it out), in the type's
        # design for 7 points, wider for its size than the 12-point it was
        # measured in, which leaves its first column's longest word,
        # "Twentytwo", a little wider than its column, short of the next.
        ("a table of 22 columns whose longest words are wider than a line together, its "
         "corner's words wrapping, is set smaller still to keep it a quarter inch inside the "
         "paper's edges, each word whole and clear of the next column",
         lambda: 0.5 * body - 0.03 < size("Twentytwo") < 0.75 * body - 0.1
         and 18 <= ends("Twentytwo")[0] and ends("Twentytwo")[1] <= 594
         and (gap_after(fit_path, "Twentytwo") or 0) > 0.5),
        # In the columns the writer sets, each as wide as its widest cell, the
        # corner's words on one line, the table was set at 53 percent of its
        # size and ran to within 5.2 points of the paper's edges.
        ("and one with a cell across two columns in its head, which the counts lay out "
         "instead, its longest words their columns' widths, likewise, its corner's words "
         "wrapping",
         lambda: 0.5 * body - 0.03 < size("Twentyspan") < 0.75 * body - 0.1
         and 18 <= ends("Twentyspan")[0] and ends("Twentyspan")[1] <= 594
         and (gap_after(fit_path, "Twentyspan") or 0) > 0.5
         and line_of("Corner") != "" and line_of("Corner words wrapping") == ""),
        # The default page's lines are 18.06 points apart, setspace's 1.25
        # times the class's 14.5.
        ("a display formula set smaller in a paragraph leaves the paragraph's lines before "
         "it as far apart as the text's",
         lambda: size("Displaylead") < body - 0.1
         and (lambda gaps: len(gaps) > 1 and all(abs(g - 18.06) < 0.05 for g in gaps))(
             leading_before("Leadpara", "Displaylead"))),
        ("a display formula too wide for its line by its spaces fits it with them narrowed, "
         "in the text's type",
         lambda: at("Displayspaced", 1) and ends("Displayspaced")[0] >= 71.5),
        ("a display formula a little too wide for its line is set smaller to fit it",
         lambda: 0.75 * body < size("Displaysmaller") < body - 0.1
         and ends("Displaysmaller")[0] >= 71.5),
        ("and one whose math in smaller type is set in wider forms is fitted again on the "
         "second run",
         lambda: at("Displayrefit", 0.75)),
        ("and one too wide even at three quarters of its type is centered on the page",
         lambda: at("Displaycentered", 0.75)
         and 18 <= ends("Displaycentered")[0] < 69),
        # microtype sets a closing parenthesis at the line's end up to 1.4
        # points into the margin.
        ("a numbered display formula a little too wide for its line is set smaller to fit "
         "it, its number at the line's end and not in the margin",
         lambda: 0.75 * body < size("Tagwide") < body - 0.1
         and "(1.2)" in line_of("Tagwide") and ends("Tagwide")[0] >= 71.5
         and ends("Tagwide")[1] <= 541.5),
        # pdf-target.lua's steps_widths, the counts, read from the LaTeX:
        # each column's share of the line as its \real{}, which a TeX
        # without Lua sets, and LuaTeX's first run gives the words theirs
        # of (the PDF's steps are laid out by LaTeX's measure, below).
        # Steps whose formulas and longest word it counted wider than a
        # line had been set as any other table, their columns of math
        # narrower than their formulas; a relation TeX names, as \leq,
        # counted as a symbol is, as wide as an x, would leave its column
        # narrower than it; a formula in a reason, which doesn't break
        # either, counted by its longest piece, would leave the reason's
        # column narrower than it, and counted without the tenth more a
        # column of math is given (MATH_ROOM), narrower than a face larger
        # than Latin Modern sets it; and steps whose longest word alone
        # fills the line, shared as the rest are, would be given columns of
        # less than no width. A reason's longest a word, not a formula, the
        # line is shared as above whatever the formulas are left: the
        # word's column as wide as the word, the formulas sharing what's
        # left by their counts, their part found again once the word's
        # column is held at it.
        ("in the LaTeX, the counts give a worked example's steps whose reason's longest word leaves their formulas "
         "less of the line than they're wide a column of words as wide as the word, the "
         "formulas sharing what's left by their counts",
         lambda: (lambda reals, w: len(reals) == 4 and len(w) == 3 and all(
             abs(reals[j] - w[j] * (61 - 36) / sum(w) / 61) < 0.0001 for j in range(3))
             and abs(reals[3] - 36 / 61) < 0.0001)(
             [float(r) for r in re.findall(r"\\real\{([\d.]+)\}",
                                           head_of(fit_source, "Unbreakableformulas"))],
             formula_widths(["1313 + \\frac{2424}{3535} + \\frac{4646}{5757}", "=",
                             "\\frac{68686}{7979} + \\frac{8080}{9191} + 1414"]))),
        # Its relation counted as an equals sign is, an operator's or a
        # relation's width, where a symbol's would leave its column too
        # narrow.
        ("and steps whose relations are TeX's commands, set across the line, each column of "
         "formulas its count and a tenth more, a relation TeX names as wide as an equals sign, "
         "the words what's left",
         lambda: (lambda reals, w: len(reals) == 4 and len(w) == 3 and all(
             abs(reals[j] - 1.1 * w[j] / 61) < 0.0001 for j in range(3))
             and abs(reals[3] - (61 - 1.1 * sum(w)) / 61) < 0.0001)(
             [float(r) for r in re.findall(r"\\real\{([\d.]+)\}",
                                           head_of(fit_source, "Leqreason"))],
             formula_widths(["1515 + \\frac{2626}{3737}", "=", "\\frac{48484}{5959} + 6161"]))),
        ("and steps whose reason holds a formula wider than the line leaves their words a "
         "column for the reason a tenth wider than its formula as counted, as a column of math "
         "is, the formulas sharing what's left by their counts",
         lambda: (lambda reals, w: len(reals) == 4 and len(w) == 4 and all(
             abs(reals[j] - share / 61) < 0.0001 for j, share in enumerate(
                 [1.1 * w[k] * (61 - 1.1 * w[3]) / (1.1 * sum(w[:3])) for k in range(3)]
                 + [1.1 * w[3]])))(
             [float(r) for r in re.findall(r"\\real\{([\d.]+)\}",
                                           head_of(fit_source, "Reasonmath"))],
             formula_widths(["1818 + \\frac{2929}{3131} + \\frac{4242}{5353}", "=",
                             "\\frac{63636}{7474} + \\frac{8585}{9696} + 1717",
                             "a^{2} + b^{2} + c^{2} + d^{2} + e^{2} = g^{2}"]))),
        # Shared as the rest are, the formulas of steps whose reason's
        # formula leaves them less than FIT_FLOOR of their counts would be
        # given less than the fit to the line sets a table in, as
        # Precalculus 2e's Example 7 in 12.2 would have run past the paper's
        # edge.
        ("and steps whose reason's formula leaves their formulas less than three quarters of "
         "their counts share the line in proportion, each formula, the reason's too, the same "
         "part of its count",
         lambda: (lambda reals, w: len(reals) == 4 and len(w) == 4 and all(
             abs(reals[j] - w[j] / sum(w)) < 0.0001 for j in range(4)))(
             [float(r) for r in re.findall(r"\\real\{([\d.]+)\}",
                                           head_of(fit_source, "Reasonshare"))],
             formula_widths(["1919 + \\frac{2828}{3737} + \\frac{4646}{5656}", "=",
                             "\\frac{64646}{7575} + \\frac{8686}{9797} + 1919",
                             "p^{2} + q^{2} + r^{2} + s^{2} + t^{2} + u^{2} = w^{2}"]))),
        # Where the formulas would get FIT_FLOOR of their counts or more, a
        # fit to the line makes up the rest, and shared alike, as they would
        # be were their part of their counts given the tenth more (MATH_ROOM)
        # taken for their part of their counts, one of Precalculus 2e's
        # tables of steps in 12.4 would have been set smaller than it was,
        # when the counts laid out the PDF.
        ("and steps whose reason's formula leaves their formulas a little more than three "
         "quarters of their counts give it room, a tenth more than its count, the formulas "
         "sharing what's left by their counts",
         lambda: (lambda reals, w: len(reals) == 4 and len(w) == 4 and all(
             abs(reals[j] - share / 61) < 0.0001 for j, share in enumerate(
                 [1.1 * w[k] * (61 - 1.1 * w[3]) / (1.1 * sum(w[:3])) for k in range(3)]
                 + [1.1 * w[3]])))(
             [float(r) for r in re.findall(r"\\real\{([\d.]+)\}",
                                           head_of(fit_source, "Reasonfloor"))],
             formula_widths(["2121 + \\frac{3232}{4343} + \\frac{5454}{6565}", "=",
                             "\\frac{76767}{8787} + \\frac{9898}{2323} + 2121",
                             "a^{2} + b^{2} + c^{2} + d^{2} + e^{2} = 23g^{2}"]))),
        ("and a little less, share it in proportion",
         lambda: (lambda reals, w: len(reals) == 4 and len(w) == 4 and all(
             abs(reals[j] - w[j] / sum(w)) < 0.0001 for j in range(4)))(
             [float(r) for r in re.findall(r"\\real\{([\d.]+)\}",
                                           head_of(fit_source, "Reasonunder"))],
             formula_widths(["3434 + \\frac{4545}{6767} + \\frac{7878}{8989}", "=",
                             "\\frac{87878}{9090} + \\frac{2525}{3636} + 3434",
                             "a^{2} + b^{2} + c^{2} + d^{2} + e^{2} = 234g^{2}"]))),
        # So shared, a reason's column is held at its longest word where its
        # formula's share is narrower, the part found again, as above, so
        # that the word isn't broken at a hyphen.
        ("and steps whose reason holds a formula and a word longer than the formula's share "
         "of the line give it the word's room, the formulas sharing what's left in proportion",
         lambda: (lambda reals, w, word: len(reals) == 4 and len(w) == 3 and all(
             abs(reals[j] - w[j] * (61 - word) / sum(w) / 61) < 0.0001 for j in range(3))
             and abs(reals[3] - word / 61) < 0.0001)(
             [float(r) for r in re.findall(r"\\real\{([\d.]+)\}",
                                           head_of(fit_source, "Holdword"))],
             formula_widths(["4747 + \\frac{5858}{6969} + \\frac{7171}{8282}", "=",
                             "\\frac{97979}{9393} + \\frac{2727}{3838} + 4747"]),
             len("Pythagoreanextendedwordyandmore."))),
        # And held at its longest word as cell_size counts a cell's words,
        # a formula's pieces between the places TeX could break it among
        # them, though a formula in steps doesn't break: held at its words
        # alone, Calculus Volume 2's steps in 3.3 would have been 108 points
        # wider than the text, where they were 36, when the counts laid out
        # the PDF (pdf-target.lua's steps_widths).
        ("and steps whose reason holds a fraction, longer counted piece by piece than its "
         "words, hold its column at that count",
         lambda: (lambda reals, w, piece: len(reals) == 4 and len(w) == 3 and len(piece) == 1
                  and piece[0] > len("Fracreason:") and all(
             abs(reals[j] - w[j] * (61 - piece[0]) / sum(w) / 61) < 0.0001 for j in range(3))
             and abs(reals[3] - piece[0] / 61) < 0.0001)(
             [float(r) for r in re.findall(r"\\real\{([\d.]+)\}",
                                           head_of(fit_source, "Fracreason"))],
             formula_widths(["5252 + \\frac{6363}{7070} + \\frac{8181}{9292} + 5252", "=",
                             "\\frac{86868}{3030} + \\frac{4141}{5252} + \\frac{6363}{7070} + "
                             "\\frac{8181}{9292} + 8181"]),
             formula_widths(["\\frac{123456789}{987654321}"],
                            "(function() local m = 0 for _, p in ipairs(formula_pieces(tex)) do "
                            "m = math.max(m, formula_length(p)) end return m end)()"))),
        # Only steps whose longest words alone fill the line are set as any
        # other table: steps whose reason's formula alone does are shared
        # alike, where so set their formulas would be given a part of the
        # line by their cells' length as formula_length counts it.
        ("and steps whose reason's formula alone is longer than a line, as counted, share it "
         "in proportion",
         lambda: (lambda reals, w: len(reals) == 4 and len(w) == 4 and all(
             abs(reals[j] - w[j] / sum(w)) < 0.0001 for j in range(4)))(
             [float(r) for r in re.findall(r"\\real\{([\d.]+)\}",
                                           head_of(fit_source, "Reasonline"))],
             formula_widths(["x", "=", "29738",
                             "a^{2} + b^{2} + c^{2} + d^{2} + e^{2} + f^{2} + h^{2} + i^{2} "
                             "+ j^{2} + k^{2} + m^{2} = g^{2}"]))),
        # By formula_width's count, given MATH_ROOM, which counts a function's
        # name by its letters and the space beside it: their cells' length
        # as cell_size counts it, a function's name a character, would set
        # them at their own width.
        ("and steps whose reason's formula alone is longer than a line, as counted, though "
         "their cells, a function's name a character, are shorter, share it in proportion",
         lambda: (lambda reals, w: len(reals) == 4 and len(w) == 4 and all(
             abs(reals[j] - w[j] / sum(w)) < 0.0001 for j in range(4)))(
             [float(r) for r in re.findall(r"\\real\{([\d.]+)\}",
                                           head_of(fit_source, "Trigline"))],
             formula_widths(["x", "=", "29738", TRIG_TERMS]))),
        ("and steps whose reason's longest word alone is longer than a line, as counted, "
         "are set as any other table, no column of less than no width",
         lambda: (lambda reals: len(reals) == 4 and min(reals) > 0)(
             [float(r) for r in re.findall(r"\\real\{(-?[\d.]+)\}",
                                           head_of(fit_source, "Longestwordofthis"))])),
        # latexbuild.FIT_MACROS' \OERFitStepsTable: steps whose counts set
        # them across the line, their words wrapped, are set at their own
        # width where LaTeX finds them narrower than it, their spaces as they
        # were, and where it doesn't, across it, each column of formulas as
        # wide as its widest, the words in what's left, no narrower than
        # their longest piece TeX can't break, then with their spaces
        # narrowed, then in smaller type, three quarters of it the least to
        # fit the line and half to keep a quarter inch inside the paper's
        # edges, measured again where the second run finds them still too
        # wide. Each paragraph of words is measured, the writer's minipage
        # around a cell's lines broken where it says, as wide as its column,
        # not counted, though a matrix is; a formula is one piece, and a
        # fill-in blank three underscores, as it's drawn shorter to fit its
        # line. Steps with two columns of words, and steps the writer
        # floats, not a longtable, keep the counts' columns.
        ("a worked example's steps whose formulas and reason's longest word the filter counts "
         "wider than a line, which LaTeX finds fit it, are set in the text's type, each formula "
         "whole",
         lambda: whole("2222", "4444") and whole("66666", "8888")
         and at("Antidisestablishmentarianism", 1)),
        ("and steps whose reason's longest word the counts leave their formulas less of the "
         "line than they're wide, which LaTeX finds fit it, are set in the text's type, their "
         "formulas whole, within the line",
         lambda: whole("2424", "4646") and whole("68686", "8080")
         and at("Unbreakableformulasreasonlongestword", 1)
         and within("Unbreakableformulasreasonlongestword")),
        ("and steps whose reason holds a formula wider than the line the counts leave their "
         "words, and steps whose reason's formula leaves their formulas less than three "
         "quarters of their counts, are set in the text's type, their formulas whole",
         lambda: at("Reasonmath", 1) and whole("2929", "4242")
         and at("Reasonshare", 1) and whole("2828", "4646") and whole("64646", "8686")),
        ("and steps the counts set across the line, which fit it at their own width as LaTeX "
         "sets them, are set so, centered, their reason on one line",
         lambda: "at its width." in line_of("Ownwidth") and ends("Ownwidth")[0] > 80
         and abs((ends("Ownwidth")[0] - 72) - (540 - ends("Ownwidth")[1])) < 1),
        # Pandoc's writer draws a rule above and below every table; OpenStax
        # sets a worked example's steps, a formula, with none.
        ("and steps are drawn without the rules above and below them a table of data has",
         lambda: rules_by("Ownwidth", 2) == 0 and rules_by("Spaced", 1) == 2),
        ("and so are a worked example's steps a book sets out in a table of its own (class "
         "steps), where a layout table that isn't steps has its rules",
         lambda: rules_by("Unruledsteps", 2) == 0 and rules_by("Ruledlayout", 2) == 2),
        ("but steps of either kind made a table of data again keep a table of data's rules, "
         "above its head, under it, and below its last row",
         lambda: rules_by("Ruleddata", 2) == 3 and rules_by("Ruledformula", 2) == 3),
        ("and steps a little too wide at their own width, which narrowed spaces would fit, "
         "are set across the line, their spaces as they were, their reason wrapping",
         lambda: at("Nearwidth", 1) and within("Nearwidth") and ends("Nearwidth")[0] < 72.5
         and "for it." not in line_of("Nearwidth")
         and 11.5 < (gap_after(fit_path, "1112+2223") or 0) < 12.5),
        ("and steps too wide at their own width are set across the line, each column of "
         "formulas as wide as its widest, their reason wrapping in what's left",
         lambda: at("Mathwidth", 1) and within("Mathwidth") and ends("Mathwidth")[0] < 72.5
         and "beside the math." not in line_of("Mathwidth")
         and 11.5 < (gap_after(fit_path, "8383") or 0) < 12.5),
        ("and steps whose reason's longest word is wider than its count fit the line with "
         "their spaces narrowed, in the text's type, the word whole",
         lambda: at("Wordwide", 1) and whole("W" * 22, "W" * 22) and within("W" * 22)
         and 5.5 < (gap_after(fit_path, "3736+4645") or 0) < 6.5),
        # Fitted at 0.801 of their size on the first run, their math set in
        # its forms for subscripts there 12 percent wider for its size, on
        # the second at three quarters (FIT_FLOOR), where 0.741 would fit;
        # their word, in a smaller design wider for its size than the one
        # the second run measured, a little wider than its column, which TeX
        # had broken (Unbreakablelongestword-).
        ("and steps too wide even with their reason as narrow as its longest word are set "
         "smaller, measured again on the second run, at three quarters of their size, within "
         "the line, the word whole",
         lambda: at("Smallsteps", 0.75) and within("Smallsteps")
         and whole("Unbreakablelongestwordofthsreasonhere",
                   "Unbreakablelongestwordofthsreasonhere")
         and within("Unbreakablelongestwordofthsreasonhere")),
        # microtype hung a blank at the end of a line 1.8 points into the
        # margin, a fifth of an underscore's width.
        ("and steps whose reason holds a fill-in blank longer than its column keep the text's "
         "type, the blank drawn shorter to fit its line, ending where it does",
         lambda: at("Blankreason", 1) and within("Blankreason") and at_edge(60)),
        # Drawn at two thirds of the reason's column on the first run before
        # the measure took the paragraph's width, the blank was measured with
        # its overlapping underscores, and drawn 207.8 points of its 280.8.
        ("and steps whose reason holds a label and a fill-in blank that fit beside their "
         "formulas are set so, the blank whole on the label's line",
         lambda: at("Wholereason", 1) and within("Wholereason")
         and (lambda found: found is not None and found[1] == 32 and not found[2])(
             blank_on_line(fit_path, "Wholereason"))),
        # A run of underscores underlined isn't marked as a blank, and
        # nothing draws it shorter, so the measure takes it whole: taken for
        # a blank, the steps would be set across the line in the text's
        # type, the run 62.8 points past it.
        ("and steps whose reason holds a run of underscores underlined, which isn't a blank, "
         "are measured with the run whole, set smaller to fit it within the line",
         lambda: size("Underreason") < body - 0.1
         and any(count == 45 and not over and 0 < right < 542
                 for count, over, right in blank_runs(fit_path))),
        ("and steps whose reason's lines are broken where it says are as wide as their longest "
         "line, centered",
         lambda: "a line under it." not in line_of("Breakreason")
         and ends("Breakreason")[0] > 80
         and abs((ends("Breakreason")[0] - 72) - (540 - ends("a line under it.")[1])) < 1),
        ("and steps whose reason's formula, whole, is wider than the line beside their "
         "formulas are set smaller to fit it, the formula whole",
         lambda: size("Mathpiece") < body - 0.1 and within("+".join(["\U0001d44e"] * 16))),
        ("and steps whose reason holds a matrix wider than the line beside their formulas "
         "are set smaller to fit it",
         lambda: size("Matrixreason") < body - 0.1 and within("912345102345")),
        ("and steps too wide for the paper even at three quarters of their type are set "
         "smaller still, a quarter inch inside its edges",
         lambda: 0.5 * body < size("Paperwide") < 0.75 * body - 0.1 and centered("Paperwide")),
        # pdf-target.lua's lone_formula: a formula with an alignment in it,
        # in braces in a table's cell (braced_math), was taken for words, its
        # column for one of words, so the steps had two and kept the counts'
        # columns (20 of College Algebra 2e's 160 tables of steps).
        ("and steps whose formula is spaced with an empty matrix's &, in braces in a table's "
         "cell, are laid out by LaTeX's measure too, at their own width",
         lambda: "Bracedsteps" in fit_source and re.findall(
             r"\{\\OERFit(?:Steps)?Table\{", fit_source[:fit_source.find("Bracedsteps")])[-1:]
         == ["{\\OERFitStepsTable{"] and "each side." in line_of("Bracedsteps")),
        ("and steps whose words are in two columns keep the counts' columns",
         lambda: "Twowords" in fit_source and re.findall(
             r"\{\\OERFit(?:Steps)?Table\{", fit_source[:fit_source.find("Twowords")])[-1:]
         == ["{\\OERFitTable{"]),
        ("and steps the writer floats, not a longtable, keep the counts' columns, in the "
         "text's type",
         lambda: at("Floatsteps", 1) and (lambda start, end: start >= 0
             and fit_source.startswith("{\\OERFitStepsTable{", start)
             and "\\begin{tabular}{@{}rcll@{}}" in fit_source[start:end]
             and "\\begin{longtable}" not in fit_source[start:end])(
             fit_source.rfind("{\\OERFit", 0, fit_source.find("Floatsteps")),
             fit_source.find("Floatsteps"))),
        # pdf-target.lua's steps_spec gives each column's letter as the
        # steps align it, which oerfit.lt_array sets: cells of a column
        # differ in width, so that a column set another way would show.
        ("and each of their columns is aligned as the steps align it: the formulas before the "
         "relation at its right, the relations centered on each other, and the formulas "
         "after it at its left",
         lambda: (lambda a, b, c, d, e, f: None not in (a, b, c, d, e, f)
                  and abs(a[1] - b[1]) < 0.5 and abs(a[0] - b[0]) > 5
                  and abs((c[0] + c[1]) - (d[0] + d[1])) < 1 and abs(c[0] - d[0]) > 2
                  and abs(e[0] - f[0]) < 0.5 and abs(e[1] - f[1]) > 5)(
             span("Alignone", "6031+7042"), span("Aligntwo", "58"),
             span("Alignone", "="), span("Aligntwo", "\u27f9"),
             span("Alignone", "13073"), span("Aligntwo", "1000000000003"))),
        # An edit of the latex target's LaTeX can give a table of steps'
        # longtable another number of columns than its \OERFitStepsTable
        # says, which LaTeX stopped on, the measure setting the group's
        # ("Extra alignment tab has been changed to \cr").
        ("and steps whose longtable has a column more than their group says, as an edit of the "
         "latex target's LaTeX can leave them, are set by their own columns, in the text's type",
         lambda: at("Editedspec", 1) and "4321" in line_of("Editedspec")
         and "another." in line_of("Editedspec")),
        ("a worked example's steps, an array in text, are set smaller to fit their line, "
         "and fitted again on the second run",
         lambda: 0.75 * body < size("Arraysmaller") < 0.8 * body),
        # Fitted on the third run, a formula's smaller type moves the page
        # breaks the fourth run reads its labels from the third with, the
        # contents' page numbers among them.
        ("nothing is fitted after the second run, so the last run's pages are the run's "
         "before",
         lambda: "TextbookImprover fit: run 3," in fit_third
         and "Package TextbookImprover Warning" not in fit_third),
        ("the build says what it fitted, and what's still wider than the text, centered, "
         "and names no line as too wide",
         lambda: "Fitted 31 table(s), formula(s), and block(s) of code too wide for their "
         "lines to them: 7 by narrowing their spaces; 24 in smaller type, the smallest at "
         "50% of its size." in fit_said
         and re.search(r"11 of them, still wider than the text, are centered on the page "
                       r"\(9 table\(s\), 2 display formula\(s\)\), the widest \d+ points "
                       r"wider: on one\.", fit_said)
         and "points wider than the text or table column" not in fit_said),
    ]


def columns_checks(columns_path, columns_said):
    """The two-column book's checks (build_fit_columns): its columns 229
    points wide, the left from 72 to 301 and the right from 311 to 540, in
    12-point type, 11.96 of the PDF's."""
    reader = pypdf.PdfReader(columns_path) if os.path.exists(columns_path) else None
    lines = glyph_lines(columns_path) if reader else {}

    def size(words):
        """The size the words are drawn at, or 0."""
        found = [s for sizes in sizes_by_page(reader, words) for s in sizes] if reader else []
        return found[0] if found else 0

    def ends(words):
        """(left, right) of the line holding the words, or (0, 0)."""
        return next(((left, right) for rows in lines.values()
                     for _baseline, left, right, text in rows if words in text), (0, 0))
    return [
        ("under the fleqn class option, a display formula too wide for its column is left as "
         "fleqn sets it, in the text's type, and named among the lines too wide",
         lambda: abs(size("Columndisplay") - 11.96) < 0.03
         and re.search(r"WARNING: [^\n]*: 1 display formula\(s\)", columns_said)),
        # Its smaller type's forms are wider for their size, so that it's
        # still a few points too wide.
        ("on a page of two columns, a worked example's steps too wide for their column even "
         "at three quarters of their type are set smaller still for it, a few points past "
         "it, and not let run a margin's width into the other column",
         lambda: 0 < size("Columnarray") < 0.75 * 11.96 - 0.1
         and 71.5 <= ends("Columnarray")[0] and 0 < ends("Columnarray")[1] <= 307),
        ("a line of code too wide for its column even at three quarters of its size is set "
         "smaller still, to fit it, and fitted again on the second run, where Latin Modern "
         "Mono's design for its smaller size leaves it a little too wide",
         lambda: 0 < size("Columncode") < 0.75 * 11.96 - 0.1
         and (lambda left, right: (71.5 <= left and right <= 301.5)
              or (310.5 <= left and right <= 540.5))(*ends("Columncode"))),
        ("and the build warns of what's too wide for its column even in smaller type, as "
         "too wide for the column, not for the paper",
         lambda: re.search(r"WARNING: 2 table\(s\), formula\(s\), or block\(s\) of code on "
                           r"pages of two columns are too wide for their column even in "
                           r"smaller type, the smallest "
                           r"at 50% of its size, and run past it, the widest \d+ points wider "
                           r"than the column: on one\.", columns_said)
         and "too wide for the paper" not in columns_said),
    ]


def aaa_checks(aaa_path):
    """The AAA book's checks (build_aaa): the page for WCAG 1.4.8 (AAA),
    bin/pdf-layout-wcag-aaa.yaml. 12.5pt is 12.45 of the PDF's points,
    and a footnote's type, 10.42pt, is 10.38."""
    reader = pypdf.PdfReader(aaa_path) if os.path.exists(aaa_path) else None
    lines = glyph_lines(aaa_path) if reader else {}
    opening = page_holding(aaa_path, "The first chapter opens")
    body = text_lines(lines, opening + 1) if opening is not None else []
    sizes = sizes_by_page(reader, "sentence")[opening + 1] \
        if opening is not None and opening + 1 < len(reader.pages) else []
    leading = commonest_leading(body) or 0
    # The space between paragraphs on every page of text, the least of
    # them as the page sets it: a full page's, two-sided, is stretched to
    # fill it (\flushbottom), a chapter's last page's not. The text's lines
    # alone: in IBM Plex, the default's face, a footnote's first line is as
    # far under the text's last as a paragraph's is under the one before.
    breaks = []
    for page in range(opening, len(reader.pages)) if opening is not None else []:
        found = text_lines(lines, page)
        found = found[:next((i for i, line in enumerate(found)
                             if squeezed("The note.") in squeezed(line[3])), len(found))]
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
        ("on the page for WCAG 1.4.8 (AAA), the text is 12.5pt type on lines "
         "space-and-a-half apart, 1.5 times the type's size, as W3C's technique C21 "
         "measures it",
         lambda: len(body) > 10 and set(sizes) == {12.45}
         and abs(leading - 1.5 * 12.45) < 0.15),
        ("its paragraphs 2.5 times the type's size apart, from the top of one's last "
         "line to the top of the next one's first",
         lambda: len(breaks) >= 2 and abs(min(breaks) - 2.5 * 12.45) < 0.5),
        ("and a footnote's lines and a caption's, in a book with a table, which loads "
         "the caption package, are as far apart for their type as the text's, where the "
         "default page sets them single-spaced",
         lambda: len(note) > 2 and len(caption) > 2
         and abs(commonest_leading(note) - 1.5 * 10.38) < 0.15
         and abs(commonest_leading(caption) - 1.5 * 12.45) < 0.15),
    ]


def fancy_checks(fancy_path, fancy_said):
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
        ("a face the metadata file names is the text's, with the fallback fonts for a "
         "character it lacks",
         lambda: reader is not None
         and any("IBMPlexSerif-Regular" in name for name in font_names(reader))
         and "rain ⇒ wet" in "".join(page.extract_text() or "" for page in reader.pages)
         and "missing from the PDF" not in fancy_said),
    ]


# The folders the books are built in, each the main book's (work) with its
# suffix: the PDF/UA-1, untagged, notes, footer, sized, fancy, default,
# preamble, AAA, fit, two-column, evaluation bar's, languages, rules,
# code, code margins, and code tall books are built beside it (build_ua1 to
# build_code), and the default book's copy, built again where TeX lacks a
# file of IBM Plex's (build_default). The cleanup removes them and --keep names them, from
# this one list, and a check sees that no build leaves another: the
# languages book's folder was left in the temporary directory by every
# run, when the cleanup and the message each had a list of their own.
BOOK_FOLDERS = ("", "-ua1", "-untagged", "-notes", "-footer", "-sized", "-fancy",
                "-default", "-default-lacking", "-preamble", "-aaa", "-fit", "-columns",
                "-bars", "-languages", "-rules", "-code", "-code-margins", "-code-tall")


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
            fitted = pool.submit(build_fit, work + "-fit")
            columned = pool.submit(build_fit_columns, work + "-columns")
            barred = pool.submit(build_blank_lines, work + "-bars")
            spoken = pool.submit(build_languages, work + "-languages")
            ruled = pool.submit(build_rules, work + "-rules")
            coded = pool.submit(build_code, work + "-code")
            reader, source, rows, log, placements = book.result()
            ua1_path, ua1_said, ua1_rows = ua1.result()
            untagged_path, untagged_said = plain.result()
            notes_path, notes_plain, notes_said, notes_source = noted.result()
            footer_path = footed.result()
            sized_path, sized_said = sized.result()
            fancy_path, fancy_said = fancied.result()
            default_path, default_said, lacking_path, lacking_said = defaulted.result()
            preamble_path, preamble_source, preamble_said = prefaced.result()
            aaa_path = aaa.result()
            fit_path, fit_said, fit_source, fit_third = fitted.result()
            columns_path, columns_said = columned.result()
            bars_path, bars_source = barred.result()
            languages_path = spoken.result()
            rules_path = ruled.result()
            (code_path, latin_code_path, code_said, margins_path, margins_said, tall_path,
         tall_said) = coded.result()
    else:
        reader, source, rows, log, placements = build(work)
        ua1_path, ua1_said, ua1_rows = build_ua1(work + "-ua1")
        untagged_path, untagged_said = build_untagged(work + "-untagged")
        notes_path, notes_plain, notes_said, notes_source = build_notes(work + "-notes")
        footer_path = build_footer(work + "-footer")
        sized_path, sized_said = build_sized(work + "-sized")
        fancy_path, fancy_said = build_fancy(work + "-fancy")
        default_path, default_said, lacking_path, lacking_said = build_default(
            work + "-default")
        preamble_path, preamble_source, preamble_said = build_preamble(work + "-preamble")
        aaa_path = build_aaa(work + "-aaa")
        fit_path, fit_said, fit_source, fit_third = build_fit(work + "-fit")
        columns_path, columns_said = build_fit_columns(work + "-columns")
        bars_path, bars_source = build_blank_lines(work + "-bars")
        languages_path = build_languages(work + "-languages")
        rules_path = build_rules(work + "-rules")
        (code_path, latin_code_path, code_said, margins_path, margins_said, tall_path,
         tall_said) = build_code(work + "-code")

    def page_text(path):
        return "".join(page.extract_text() or "" for page in pypdf.PdfReader(path).pages) \
            if os.path.exists(path) else ""
    notes_text, notes_plain_text = page_text(notes_path), page_text(notes_plain)

    def notes_marks():
        return footnote_marks(notes_path) if os.path.exists(notes_path) else []
    notes_reader = pypdf.PdfReader(notes_path) if os.path.exists(notes_path) else None

    def notes_size(words):
        """The size the notes book first draws words at, or 0."""
        found = [s for sizes in sizes_by_page(notes_reader, words) for s in sizes] \
            if notes_reader else []
        return found[0] if found else 0
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
        # Pandoc's writer before 3.13 leaves a term with an = in it bare in
        # \item's optional argument, where LaTeX's tagging reads it as keys
        # and stops; pdf-target.lua braces it, as 3.13's writer does. Any
        # run of spaces between words, as pypdf 4.0.2 reads a justified
        # line's wider ones.
        ("a definition list's term with an equals sign is set",
         lambda: re.search(r"Markup\s*=\s*price\s+less\s+cost\s*An\s+equals\s+sign\s+in\s+a\s+term",
                           text) is not None),
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
        ("and one LaTeX makes on its own is its address, its hyphens and backtick as "
         "written",
         lambda: os.path.exists(ua1_path) and [
             contents for s, uri, contents in links(pypdf.PdfReader(ua1_path))
             if "lang" in uri] == ["https://example.org/lang--en/q?`x"]),
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
         == [["/Lbl", "/text"], ["/Lbl", "/text"], ["/Lbl", "/text"], ["/text"], ["/text"],
             ["/text"], ["/text"]]),
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
        ("with picture_paths off, a picture in a page's LaTeX is drawn with LaTeX's own "
         "lcircle10 glyphs, as before pict2e drew picture mode in every PDF",
         lambda: os.path.exists(untagged_path)
         and "LCIRCLE10" in pdftext.base_fonts(untagged_path)),
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
        # underscore is drawn still, each blank a Span whose ActualText,
        # "blank", is what a screen reader says. A blank that fits is left
        # as it is.
        ("a fill-in blank that runs past its line ends where the line does, its spaces "
         "their natural width, and the build doesn't name the line",
         lambda: (lambda found: found is not None and abs(found[0] - 345) < 1
                  and found[1] == 16 and found[2] and found[5] is not None
                  and found[5] > 3.2)(blank_on_line(pdf_path, "Exertion"))
         and not re.search(r"more than 3 points wider[^\n]*appendix", log)),
        ("and each blank is a Span whose ActualText is \"blank\", for a screen reader, its "
         "underscores drawn, the question's words the paragraph's",
         lambda: [(said, text) for said, text in pdftext.actual_texts(pdf_path, "/Span")
                  if said == "blank"] == [("blank", "_" * 16), ("blank", "_" * 18),
                                          ("blank", "_" * 4), ("blank", "_" * 8)]
         and "The Rating of Perceived Exertion (RPE) is an example of"
         in [" ".join(t.split()) for t in pdftext.element_texts(pdf_path, "/text")]),
        # A blank in the middle of a paragraph: the words after it are the
        # paragraph's still, not an artifact, and its Span holds nothing
        # but the underscores, the next paragraph after the Span's, not in it.
        ("a blank in a paragraph's middle leaves the words after it the paragraph's, its Span "
         "the paragraph's child and holding no other",
         lambda: "The terms and are often used interchangeably, the words after each blank "
                 "still in the paragraph."
         in [" ".join(t.split()) for t in pdftext.element_texts(pdf_path, "/text")]
         and [(tag, has) for tag, _, has in pdftext.span_parents(pdf_path, "blank")]
         == [("/text", False)] * 4
         and [" ".join(text.split()) for _, text, _ in pdftext.span_parents(pdf_path, "blank")][2:]
         == ["The terms and are often used interchangeably, the words after each blank still "
             "in the paragraph."] * 2),
        # What --wcag --verbose says of a blank veraPDF fails: the line it's
        # on, read with pypdf, which gives some runs around a tagged PDF's
        # marked content no place.
        ("and --wcag --verbose names the line a blank is on, its words in order",
         lambda: (lambda found: found is not None and pdfcheck._WcagContext(pdf_path).line(
             *found).endswith("is an example of " + "_" * 16))(
             blank_box(pdf_path, "Exertion"))),
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
        # its JSON log of the run: a formula too wide for the paper even in
        # type half its size, which FIT_MACROS sets at half.
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
        # LaTeX titles an entry's structure element with its text made
        # plain, which had kept a link's description and an \\href's address.
        ("an entry in the list of figures is titled by its caption's words, a link in it "
         "by its text alone",
         lambda: os.path.exists(notes_path)
         and "A figure whose caption has a linked word and one within in it."
         in [str(e.get("/T")) for e in elements(
             pypdf.PdfReader(notes_path).trailer["/Root"]["/StructTreeRoot"])
             if kind(e) == "/TOCI"]),
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
        # pdf-target.lua's steps_widths: a column of formulas had been as
        # narrow as the longest piece of its longest, each column given its
        # share of the line by its length as formula_length counts it, a
        # fraction's two parts one after the other, so a formula broke
        # over its column's lines; and steps that fit their line were set
        # across it, their reasons wrapped.
        ("a worked example's steps longer than a line keep each formula whole, two "
         "fractions' numerators on one line, and their reasons wrap in their column",
         lambda: (lambda lines: all(any(first in text and second in text for text in lines)
                                    for first, second in (("5678", "3456"), ("15924", "1357")))
                  and not any("Collect" in text and "were." in text for text in lines)
                  and says(re.sub(r"-\n", "", notes_text), "Collect the numbers that came "
                           "before into one sum, carrying the others along as they were."))(
             [text for rows in glyph_lines(notes_path).values() for *_, text in rows])),
        ("and in the LaTeX, the counts' columns, steps that fit their line are set at their "
         "own width, in columns that don't wrap",
         lambda: head_of(notes_source, "\\frac{9876}{5432}")
         and "p{(" not in head_of(notes_source, "\\frac{9876}{5432}")),
        # pdf-target.lua's formula_width, which an escaped symbol (\{) and a
        # text's spaces would add nothing to, and which would count a
        # function's name (\sin) as one character, though TeX sets it as
        # its letters, upright, with a space beside it that it sets beside
        # no text, nor before a parenthesis, but does before \left(, which
        # makes a group of what it holds; a space in \mathrm, where TeX
        # sets none, as a text's; limits set under something, as \underset
        # and \limits set them, beside it; and a relation set under or over
        # something, as \overset{?}{=}, as a symbol; and MATH_ROOM, a tenth
        # more for a face whose small letters are taller than Latin
        # Modern's, to which Pandoc's template scales a formula's.
        ("a formula's width counts an escaped brace as a symbol, a text's spaces but not "
         "\\mathrm's, a function's name by its letters and the space beside it, none before "
         "a parenthesis but one before \\left, limits set under something as wide as the "
         "wider of the two, and a relation set so as a relation",
         lambda: (lambda w: len(w) == 32 and all(w[k] > w[k + 1] for k in (0, 2, 4))
                  and all(w[k] == w[k + 1] for k in range(6, 32, 2)))(
             formula_widths(["\\text{if and only if}", "\\text{ifandonlyif}", "\\sin x",
                             "\\text{sin} x", "\\log\\left( x \\right)", "\\log(x)",
                             "\\{ x \\}", "( x )", "\\mathrm{a b}", "\\mathrm{ab}",
                             "\\ln(x)", "\\text{ln}(x)", "\\ln[x]", "\\text{ln}[x]",
                             "\\sup\\{x\\}", "\\text{sup}\\{x\\}",
                             "\\sin\\lbrack x \\rbrack", "\\text{sin}\\lbrack x \\rbrack",
                             "\\log_{2}(x)", "\\text{log}_{2}(x)", "\\sin\\nolimits(x)",
                             "\\text{sin}(x)", "\\lim\\limits_{n}(x)", "\\lim(x)",
                             "\\underset{x}{\\text{lim}}", "\\text{lim}",
                             "x\\overset{?}{=}5", "x = 5", "x\\underset{a}{\\leq}5", "x \\leq 5",
                             "x\\stackrel{a}{b}y", "x = y"]))),
        ("and in the LaTeX, steps set across the line give each column of math a tenth more "
         "than its widest formula, so counted",
         lambda: (lambda reals, w: len(reals) == 4 and len(w) == 3 and all(
             abs(reals[j] - 1.1 * w[j] / 61) < 0.0001 for j in range(3)))(
             [float(r) for r in re.findall(r"\\real\{([\d.]+)\}",
                                           head_of(notes_source, "\\frac{5678}{9012}"))],
             formula_widths(["1234 + \\frac{5678}{9012} + \\frac{3456}{7890}", "=",
                             "\\frac{15924}{2468} + \\frac{1357}{2468} + 1111"]))),
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
        # word too wide for a line, wraps; a table with widths gives a
        # column narrower than its longest word the room it needs. A table
        # whose longest words the filter counts too wide for a line had
        # been set in \small, which one whose words LaTeX finds fit didn't
        # need; and a table of numbers is set smaller as LaTeX measures it
        # (FIT_MACROS), in 10-point Latin Modern at 86 percent, 8.57
        # points, 1.2 points too wide for its line in the 9-point design,
        # and so centered, where fitting it again would have set it in the
        # 8-point design at 84 percent, 2.7 points too wide.
        ("a table of reactions is set in columns that wrap, its formula a word a piece",
         lambda: "p{(\\linewidth" in head_of(notes_source, "Representative reaction")),
        ("a table whose longest words the filter counts too wide for a line, which LaTeX "
         "finds fit it, is set in the text's type",
         lambda: notes_size("Two layout") > 9
         and notes_size("Hippopotomonstrosesquippedaliophobia") == notes_size("Two layout")),
        ("a table's equal widths give a word too long for its share the room it needs",
         lambda: (lambda reals: len(reals) == 3 and reals[1] > 0.5 and reals[1] == max(reals))(
             [float(r) for r in re.findall(r"\\real\{([\d.]+)\}", head_of(
                 notes_source, "Pneumonoultramicroscopicsilicovolcanoconiosis"))])),
        ("a table of numbers too wide for its line keeps its columns and is set smaller "
         "to fit it, and not fitted again for a fit within 4 percent of its line",
         lambda: head_of(notes_source, "242.98") and "p{(" not in head_of(notes_source, "242.98")
         and 0.85 * notes_size("Two layout") < notes_size("242.98") < 0.86 * notes_size("Two layout")
         and "Fitted 1 table(s), formula(s), and block(s) of code" in notes_said),
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
        # The cancel package draws its strokes with picture mode's \line,
        # glyphs of LaTeX's line10 font, which have no map to Unicode;
        # with pict2e (latexbuild's PICTURE_PATHS) they're paths.
        ("a formula's term struck out is drawn as a line, one for each stroke, and none "
         "of LaTeX's line10 font's glyphs, which have no map to Unicode, is in the PDF, "
         "tagged or not",
         lambda: [stroke[0] for stroke in pdftext.diagonal_strokes(notes_path)]
         == [page_holding(notes_path, "Terms struck out")] * 5
         and not {"LINE10", "LINEW10"} & (pdftext.base_fonts(notes_path)
                                          | pdftext.base_fonts(notes_plain))),
        # pict2e defines an \arc of its own, which a \newcommand of the
        # book's in its text stopped on ("already defined"); PICTURE_PATHS
        # takes it away again at \begin{document}.
        ("pict2e, loaded for a term struck out, leaves the book its own command of a "
         "name pict2e has, \\arc, defined in its text, tagged or not",
         lambda: says(notes_text, "\u2322") and says(notes_plain_text, "\u2322")),
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
        ("pdf.figures section lets figures float within their section",
         lambda: "\\usepackage[section]{placeins}" in placements["section"]
         and "floatplacement" not in placements["section"]),
        ("pdf.figures float leaves LaTeX's placement alone",
         lambda: not any(word in placements["float"] for word in
                         ("floatplacement", "placeins", "float/flush"))),
        ("and the default keeps figures in place",
         lambda: "\\floatplacement{figure}{H}" in source),
        # LaTeX's tagging gathers the tags of what floats at the end of the
        # document; under section, flushed, they had followed the section.
        ("under each placement, a float's tags are where the text has it",
         lambda: all("{\\tagpdfsetup{float/here}}" in text
                     for text in (source, placements["section"], placements["float"]))),
        ("each figure's tags sit where the text has it",
         lambda: figures and not inside(tree, "/figures", "/Figure")),
        ("the described image is a figure with its alt text",
         lambda: any(str(f.get("/Alt")) == "A small red square"
                     for f in figures)),
        # Pandoc's writer writes a straight quote, a bar, <, >, ~, and \ in
        # the alt key as commands, ^ as \^{}, and curly quotes and dashes as
        # TeX's ligatures, which /Alt had as they're written.
        ("a figure's alt text is its characters, those the writer writes as commands and "
         "the quotes and dashes it writes as TeX's ligatures among them",
         lambda: any(str(f.get("/Alt")) == "A cell's nucleus, its |bar|, 1 < 2 > 0, x~y, a\\b, "
                     "x^2, \u201cquoted\u201d and \u2018single\u2019 it\u2019s 1\u20135 "
                     "a\u2014b, and -- as typed" for f in figures)),
        ("the decorative image is no figure",
         lambda: len(figures) == 11),
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
        # hyperref's \pdfstringdef, which writes it, would make -- an en
        # dash, as the ilo.org addresses in Sociology's references were,
        # and ?` an inverted question mark.
        ("and an address's hyphens and backtick are kept in it as they're written",
         lambda: by_uri.get("https://example.org/lang--en/q?%60x")
         == "https://example.org/lang--en/q?`x"),
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
    items += fancy_checks(fancy_path, fancy_said)
    items += default_checks(default_path, default_said, lacking_path, lacking_said)
    items += preamble_checks(preamble_path, preamble_source, preamble_said)
    items += aaa_checks(aaa_path)
    items += fit_checks(fit_path, fit_said, fit_source, fit_third)
    items += columns_checks(columns_path, columns_said)
    # pdf-target.lua's Math: an empty line in a formula, as texmath writes a
    # one-column matrix whose last row is empty, is that row, an empty group.
    matrices = re.findall(r"\\begin\{matrix\}.*?\\end\{matrix\}", bars_source, re.S)
    items += [
        ("a display formula holding an empty line, as texmath writes an evaluation bar's "
         "limits, builds, the empty line an empty row, and so does a formula in text "
         "holding one",
         lambda: os.path.exists(bars_path) and len(matrices) == 4
         and not any(re.search(r"\n[ \t]*\n", m) for m in matrices)
         and "Barinline" in "".join(page.extract_text() or "" for page in
                                    pypdf.PdfReader(bars_path).pages)),
        ("and each bar's upper limit is as far above the formula's line as its lower "
         "limit is below it, in the display and in text, the empty row kept",
         lambda: os.path.exists(bars_path)
         and [abs(up - down) < 3 for up, down in bar_limits(bars_path)] == [True, True]),
    ]
    items += language_checks(languages_path)
    items += rules_checks(rules_path)
    items += code_checks(code_path, latin_code_path, code_said, margins_path, margins_said,
                         tall_path, tall_said)
    items.append(("every folder a book is built in is one the suite removes once it's done, "
                  "or names when told to keep them (BOOK_FOLDERS)",
                  lambda: {os.path.basename(path) for path in glob.glob(glob.escape(work) + "*")}
                  <= {os.path.basename(work) + suffix for suffix in BOOK_FOLDERS}))
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
    # and this suite says why it can't run. So is a TeX without a package
    # the books load, on which LaTeX stops.
    spec = importlib.util.spec_from_file_location(
        "build_pdf", os.path.join(BIN, "build-pdf.py"))
    build_pdf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_pdf)
    problem = build_pdf.latex_problem()
    missing = tex_missing()
    if missing and not problem:
        import latexbuild
        problem = ("TeX lacks " + ", ".join(missing) + ", which the suite's PDFs load ("
                   + latexbuild.tlmgr_command("install " + " ".join(missing))
                   + "); the pdf target is not checked")
    if problem:
        print(f"  skip  {problem}")
        print("\nall PDF checks skipped")
        return 0

    work = tempfile.mkdtemp(prefix="pdf-tests-")
    failed = 0
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
        # Each book's folder (BOOK_FOLDERS).
        folders = [work + suffix for suffix in BOOK_FOLDERS]
        if arguments.keep:
            print(f"\nOutput left in {', '.join(folders[:-1])}, and {folders[-1]}")
        else:
            for folder in folders:
                shutil.rmtree(folder, ignore_errors=True)
    print(f"\n{failed} check(s) failed" if failed
          else "\nall PDF checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
