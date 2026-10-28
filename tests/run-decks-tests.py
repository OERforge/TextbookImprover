#!/usr/bin/env python3
"""
run-decks-tests.py -- check decks written in Markdown: a folder of them
as slides, each deck's page, its Markdown and source copies, its PDF
through ltx-talk, its PowerPoint file, and its reveal.js presentation.

    python3 tests/run-decks-tests.py

Needs Pandoc 3.9 or later. A deck's PowerPoint file needs 3.10.1, and its
presentation 3.12, as convert.py's pptx and revealjs targets do
(PPTX_PANDOC, REVEALJS_PANDOC): with an older Pandoc, the checks of them
skip, naming the Pandoc found and the one they need, and the rest of
each case runs. The PDF's cases need LuaLaTeX with LaTeX
2026-06-01 or later and the ltx-talk, lua-unicode-math, and
newcomputermodern packages, the packages the decks load (SUITE_TEX), and
pikepdf and pypdf to read what was built, and skip, saying why, without
them; veraPDF, found as the output check
finds it (VERAPDF, or on the path), judges each PDF's claim when it's
there. The decks are written here, small and made up, each holding what
the code has to handle: sections above the slides, an agenda before the
first, sections at ##, notes, pauses, code, a table with a formula in its
head, columns, frame options, footnotes in a table and in titles, a
lettered list, passages in other languages, beamer's commands in
header-includes, a slide with no title.

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
import csv
import html
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import unicodedata
import warnings
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))
import parallel  # noqa: E402
import pdftext  # noqa: E402
import decks  # noqa: E402
import highlighting  # noqa: E402

try:
    import pikepdf
except ImportError:
    pikepdf = None
try:
    import pypdf
except ImportError:
    pypdf = None


def png(path, red, green, blue, size=8):
    """A small PNG of one color."""
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    raw = b"".join(b"\x00" + bytes([red, green, blue]) * size for _ in range(size))
    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


# A deck of slides at level 1, as most decks written for beamer are: its
# title a YAML list of one, notes, a pause, a slide a rule begins, a
# picture named in another case than its file's, and a slide whose title
# has a character New Computer Modern Sans Bold lacks.
FLAT = """\
---
title:
- "Demand: A Short Deck"
author:
- A. Lecturer
date: Fall 2026
language: en-US
theme: Madrid
---

# Value Is Subjective

Value is *subjective*.

::: notes
Ask what the class would pay for water.
:::

# Specialization => Growth

First point.

. . .

Second point, after a pause.

---

Text on a slide with no title.

# A Chart

![A rising line](img/Chart.PNG)

# Market Demand

| Price | $q^d$ |
|------:|------:|
| 1 | 10 |
| 2 | 8 |

: Demand at each price
"""

# A deck of sections above slides at level 2, with code, columns, frame
# options, a footnote, and a link, its shape given as beamer codes it.
SECTIONED = """\
---
title: Sections and Slides
subtitle: A conference talk
author:
- B. Speaker
- C. Speaker
institute: A University
aspectratio: 1610
---

# Part One

## Opening {.t}

:::: columns
::: column
Left, with a [link](https://example.org/).
:::
::: column
Right.
:::
::::

## Some Code {.allowframebreaks .plain}

```python
def demand(p):
    return 12 - 2 * p > 0
```

# Part Two

## A Footnote

A claim.[^1]

::: notes
Notes for part two.
:::

[^1]: Its source.
"""

# A deck with no title, and a README beside the decks, which isn't one.
UNTITLED = """\
# Only Slide

Nothing else.
"""

# An agenda before the first section, sections whose titles have an = and
# a footnote, a lettered list, and a heading in a slide that skips a level.
AGENDA = """\
---
title: Lecture Five
---

## Agenda

1. Supply
2. Profit

# [Supply]{lang=en-GB}

## The Curve

a. Upward sloping
b. Steeper in the short run

#### A Block

Its text.

# Profit: MR = MC[^p]

## The Rule

Produce where they meet.

[^p]: Marginal revenue and marginal cost.

    Each is [per unit](https://example.org/unit).
"""

# Sections at ##, slides at ###, as a deck cut from a longer document has.
SUBSECTIONS = """\
---
title: Subsections
---

## Part A

### Slide One

Text one.

## Part B

### Slide Two

Text two.
"""

# A cue in the notes written as a level-1 heading, which Pandoc counts,
# making every heading a slide's.
CUE = """\
---
title: Cue
---

# Part

## Slide

Text.

::: notes
# A Cue

Say this.
:::
"""

# Two levels of sections, and a slide in a part with no chapter.
NESTED = """\
---
title: Nested
---

# Part One

## Chapter A

### Slide A1

Text.

## Chapter B

### Slide B1

Text.

::: notes
Say this.

# A Cue
:::

# Part Two

### Slide C1

Text.

> # Quoted big heading

#### A Block After

More text.
"""

# More of what had gone wrong: a passage in another language that begins
# a paragraph or a list item, a link in one, a slide in one, and a slide's
# title with one; footnotes in a table's caption and head, in an image's
# description, which LaTeX leaves out, on a slide shown in steps, and in
# a slide inside a div; headings in a quotation; and beamer's commands
# with a star, and one more.
MORE = """\
---
title: More Cases
header-includes:
- \\setbeamercolor*{structure}{fg=blue}
- \\setbeameroption{hide notes}
---

# Words

[Bonjour]{lang=fr}, she said.

- [Hola]{lang=es} to all
- and [un sito](https://example.org/){lang=it}

::: {lang=de}
# Eine Folie

Ein Absatz.
:::

# Le [titre]{lang=fr} anglais

Text.

# A Table

A tiny ![square[^i]](img/chart.png) in a line.

| Price[^h] | Quantity |
|------:|------:|
| 1 | 10 |

: Prices[^c]

# Paused[^p]

First.

. . .

Second.[^q]

> ### Quoted heading
>
> # Quoted big heading

::: {.highlight}
# Wrapped Slide[^w]

Wrapped text.
:::

# Last

Done.[^z] `\\subsection{Raw in a frame}`{=latex}

# Blocks

::: {lang=de}
### Ein Block

Ein Text im Block.
:::

:::: columns
::: {.column lang=fr}
### Pour

- rapide
:::
::: column
### Against

- slow
:::
::::

# Nested Table

+-----------------------+-------------------+
| Head                  | Other             |
+=======================+===================+
| a                     | +-----+-------+   |
|                       | | x   | y[^y] |   |
|                       | +-----+-------+   |
+-----------------------+-------------------+

# Long {.allowframebreaks}

1. Item 1
2. Item 2
3. Item 3
4. Item 4
5. Item 5
6. Item 6
7. Item 7
8. Item 8
9. Item 9
10. Item 10
11. Item 11
12. Item 12
13. Item 13
14. Item 14
15. Item 15
16. Item 16
17. Item 17
18. Item 18
19. Item 19
20. Item 20
21. Item 21
22. Item 22
23. Item 23
24. Item 24
25. Item 25

[^i]: In a description, which LaTeX leaves out.
[^h]: The head's note.
[^c]: The caption's note.
[^p]: The title's note.
[^q]: The body's note.
[^w]: The wrapped slide's note.
[^z]: The last note.
[^y]: The inner table's note.
"""

# Headings in a slide: in a list's item and a table's cell, where
# Pandoc's slide writers find no slide, a block in a block, quotations in
# it with headings the deck puts under its title and beside it, a block
# with no title, blocks in two columns, the second's deeper, with a
# quotation in it, and headings in a quotation, one under another, each at
# the level the deck's page gives it; and footnotes in a block's title,
# one in a column too, and a heading in an item and a quotation. And an
# empty heading in a quotation, and a block whose title is an anchor, which
# are no headings, and links to the anchor and a heading in a quotation.
HEADINGS = """---
title: Headings
---

# A List

- ### In an item[^i]

  Its text, and links to [a heading in a quotation](#quoted-beside-inner), [the
  anchor block](#anchor-only), and [the columns slide](#columns).

- Plain item

# A Table

+---------------------+---------+
| Head                | Other   |
+=====================+=========+
| ### In a cell       | b       |
|                     |         |
| Cell text.          |         |
+---------------------+---------+

# Blocks

## Outer[^o]

Outer text.

### Inner

Inner text.

> #### Quoted under Inner
>
> Its text.

> ### Quoted beside Inner
>
> Its text.

## {.example}

An untitled block's text.

## []{#anchor-only}

An anchor's block's text.

# Columns

:::: columns
::: column
## Left[^l]

Left text.
:::
::: column
### Right

> #### Quoted right
>
> Its text.
:::
::::

# Quoted

> ### Quoted[^q]
>
> #### Under it
>
> Its text.
>
> ####

[^i]: The item's note.
[^o]: The block's note.
[^l]: The column's note.
[^q]: The quotation's note.
"""

# Footnotes in headings in another language: a section's, a slide's, a
# block's (of two paragraphs), and a quotation's heading's, in a div in
# German, and one in a passage in French in a slide's title; each note in
# its language. And a block with no title in the div, and a quotation's
# heading in one, which has no heading for it to be under.
LANGS = """---
title: Sprachen
---

# Teil Eins

## Eine Folie

Text.

::: {lang=de}
# Teil Zwei[^t]

## Zweite Folie[^f]

### Ein Block[^b]

Ein Text.

> ### Ein Zitat[^z]
>
> Zitiert.

### {.example}

Ein Text ohne Titel.
:::

## A [Mot[^m]]{lang=fr} Slide

Text.

## Ohne Titel

### {.example}

> #### Im Block ohne Titel
>
> Text.

[^t]: Die Fußnote des Teils.
[^f]: Die Fußnote der Folie.
[^b]: Die Fußnote des Blocks.

    Ihr zweiter Absatz.
[^z]: Die Fußnote des Zitats.
[^m]: La note du mot.
"""

# Code in footnotes, which LaTeX's footnote reads as an argument, where a
# code block's verbatim can't be read: a section's footnote with the
# deck's only highlighted code, inline, and a code block of LaTeX's own
# verbatim in it, in a slide's, and in a block's title's; and the deck's
# own header-includes, which the code's files join.
CODE_NOTES = r"""---
title: Code in Notes
header-includes: \hypersetup{pdfsubject={Code in notes}}
---

# Costs[^s]

## Marginal Cost

Where it turns up.[^m]

#### A Block[^b]

Its text.

[^s]: Computed by `mc(2)`{.python}, and tabled:

    ```
    q   mc
    ```
[^m]: As a rule:

    ```
    mc  = 2 * q
    ```
[^b]: And its total:

    ```
    tc  = q * q  % of all
    ```
"""

# Highlighted code blocks in a section's footnote and a slide's, and
# header-includes as a list.
SHADED_NOTES = r"""---
title: Highlighted Notes
header-includes:
- \hypersetup{pdfkeywords={notes, code}}
---

# Revenue[^r]

## Marginal Revenue

Where it falls.[^f]

[^r]: The function:

    ```python
    def mr(q):
        return 12 - 2 * q  # 100%
    ```
[^f]: Its slope:

    ```python
    slope = -2
    ```
"""

# A list whose first item opens with highlighted code, whose number
# LaTeX's tagging had set over the next item's (latexbuild.PDF_MACROS).
ITEM_CODE = r"""---
title: Item Code
---

# A List

1. ```python
   Deckopens = 1
   ```

2. The item after the code.
"""

# What beamer and LaTeX's other classes read and ltx-talk didn't: a
# footnote in a caption, a table, and a slide's title, struck text, a
# passage in another language, code that shows a frame, a frame option
# ltx-talk has no key for, beamer's own command in header-includes, and
# a color named as xcolor's dvipsnames name it. And a formula's term
# struck out, which the cancel package draws.
ODD = """\
---
title: Odd Cases
urlcolor: NavyBlue
header-includes:
- \\setbeamertemplate{navigation symbols}{}
---

# Before

A first note.[^a]

![A blue square, with a note[^c]](img/chart.png)

# A Claim[^t]

| Price | Note |
|------:|------|
| 1 | low[^n] |

: Prices

# Words {shrink=10}

~~struck~~ and [bonjour]{lang=fr}, and [a site](https://example.org/).

::: {lang=de}
Ein ganzer Absatz.
:::

# Struck out

$\\frac{\\cancel{3}x}{\\cancel{3}} = x$ and $\\xcancel{2z}$.

# Code

```
\\begin{frame}{Hello}
\\begin{columns}[T]
\\end{frame}
```

# Pages 10\\-\\-20

Two hyphens in a title, escaped so as to stay two.

[^a]: The first note.
[^c]: The caption's note.
[^t]: The title's note.
[^n]: The table's note.
"""


def write(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def folder(work, config, project=True, decks_given=None):
    """A folder of decks: the three above unless decks_given names others,
    a README, a picture, and the configuration given."""
    os.makedirs(work, exist_ok=True)
    for name, text in (decks_given or {"Flat Deck.md": FLAT, "sectioned.md": SECTIONED,
                                       "untitled.md": UNTITLED}).items():
        write(os.path.join(work, name), text)
    write(os.path.join(work, "README.md"), "# About these slides\n\nNot a deck.\n")
    png(os.path.join(work, "img", "chart.png"), 40, 90, 200)
    if project:
        write(os.path.join(work, "project.yaml"),
              "project:\n  identifier: org.example.decks\n  title: The Decks\n"
              "  language: en-US\n  kind: slides\n")
    if config is not None:
        write(os.path.join(work, "conversion.yaml"), config)
    return work


def convert(work, *flags, env=None):
    return subprocess.run([sys.executable, os.path.join(BIN, "convert.py"), "--quiet", *flags],
                          cwd=work, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                          env=env)


def headings(page):
    """(level, text) of each heading on a page, the title block's too, but
    the one over its notes, which the run gives a page's notes, not the
    deck."""
    found = []
    page = re.sub(r'<h2 class="footnotes-title">.*?</h2>', "", page, flags=re.S)
    for level, text in re.findall(r"<h([1-6])[^>]*>(.*?)</h\1>", page, re.S):
        found.append((int(level), " ".join(html.unescape(re.sub(r"<[^>]+>", "", text)).split())))
    return found


def rows_of(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.reader(fh))[1:]


# --------------------------------------------------------------------------
# the pieces
# --------------------------------------------------------------------------

def header(level, text="Title"):
    return {"t": "Header", "c": [level, ["", [], []], [{"t": "Str", "c": text}]]}


def para(text="Text."):
    return {"t": "Para", "c": [{"t": "Str", "c": text}]}


def tidy_fixture(path, ghost=True):
    """A PDF in the shapes LaTeX leaves in a deck's, for decks.tidy: a link
    tagged in the tree; a link bin, an Artifact holding a Link holding the
    annotation of a link made while tagging was suspended; an Artifact with
    content of its own, as a table's repeated head is, holding a footnote's
    mark, its link and its marked content; a note whose /Ref names its own
    mark, that one, and (ghost) a mark the tree doesn't hold; a mark with no
    note; and an Artifact holding a form field's annotation, which is no
    link, the field in the document's form, as hyperref puts one: pikepdf
    warns on saving a widget no form reaches."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    name = pikepdf.Name

    def link(n):
        return pdf.make_indirect(pikepdf.Dictionary(
            Type=name.Annot, Subtype=name.Link, Rect=[0, 0, 10, 10], StructParent=n,
            A=pikepdf.Dictionary(S=name.URI, URI=pikepdf.String(f"https://example.org/{n}"))))

    def element(kind, kids, **keys):
        return pdf.make_indirect(pikepdf.Dictionary(Type=name.StructElem, S=name(kind),
                                                    K=pikepdf.Array(kids), **keys))

    tagged, binned, repeated = link(0), link(1), link(3)
    widget = pdf.make_indirect(pikepdf.Dictionary(Type=name.Annot, Subtype=name.Widget,
                                                  Rect=[0, 20, 10, 30], StructParent=2,
                                                  FT=name.Tx, T=pikepdf.String("field")))
    pdf.pages[0].obj.Annots = pikepdf.Array([tagged, binned, widget, repeated])
    pdf.Root.AcroForm = pdf.make_indirect(pikepdf.Dictionary(Fields=pikepdf.Array([widget])))
    repeated_link = element("/Link", [pikepdf.Dictionary(Type=name.OBJR, Obj=repeated)])
    own, untied, lost = (element("/footnotemark", [n]) for n in (0, 3, 2))
    kept = element("/footnotemark", [pikepdf.Dictionary(Type=name.MCR, MCID=1,
                                                        Pg=pdf.pages[0].obj),
                                     repeated_link])
    marks = [own, kept, lost] if ghost else [own, kept]
    note = element("/footnote", [4], Ref=pikepdf.Array(marks))
    for mark in marks:
        mark.Ref = pikepdf.Array([note])
    tagged_link = element("/Link", [pikepdf.Dictionary(Type=name.OBJR, Obj=tagged)])
    binned_link = element("/Link", [pikepdf.Dictionary(Type=name.OBJR, Obj=binned)])
    bin_ = element("/Artifact", [binned_link], T=pikepdf.String("Ignored link annotations"))
    field = element("/Form", [pikepdf.Dictionary(Type=name.OBJR, Obj=widget)])
    document = element("/Document", [element("/P", [own, tagged_link]),
                                     element("/Artifact", [element("/TD", [kept])]),
                                     element("/P", [untied]), note, bin_,
                                     element("/Artifact", [field])])
    parents, ids = pikepdf.NumberTree.new(pdf), pikepdf.NameTree.new(pdf)
    parents[0], parents[1], parents[2], parents[3] = tagged_link, binned_link, field, repeated_link
    ids["bin"], ids["binned"], ids["note"] = bin_, binned_link, note
    pdf.Root.StructTreeRoot = pdf.make_indirect(pikepdf.Dictionary(
        Type=name.StructTreeRoot, K=pikepdf.Array([document]), ParentTree=parents.obj,
        IDTree=ids.obj))
    pdf.save(path)


def tidied(path):
    """What tidy_fixture's PDF holds: the document's elements, the MCIDs of
    the marks its note names, the page's links, and the parent tree's keys
    and the ID tree's."""
    with pikepdf.open(path) as pdf:
        root = pdf.Root.StructTreeRoot
        kids = list(root.K[0].K)
        note = next(k for k in kids if k.S == "/footnote")
        return ([str(k.S) for k in kids],
                [int(r.K[0].MCID if isinstance(r.K[0], pikepdf.Dictionary) else r.K[0])
                 for r in note.Ref],
                [str(a.A.URI) if "/A" in a else str(a.Subtype) for a in pdf.pages[0].obj.Annots],
                sorted(int(k) for k, _ in pikepdf.NumberTree(root.ParentTree).items()),
                sorted(str(k) for k, _ in pikepdf.NameTree(root.IDTree).items()))


def case_pieces(work):
    rule = {"t": "HorizontalRule"}
    div = {"t": "Div", "c": [["", ["notes"], []], [para()]]}
    tex = ("\\begin{frame}[fragile]{Code}\n\\begin{Shaded}\nx\n\\end{Shaded}\n\\end{frame}\n"
           "\\begin{frame}[fragile]{Inline}\n\\texttt{x}\n\\end{frame}\n"
           "\\begin{frame}{Verb}\n\\VERB|\\NormalTok{x}|\n\\end{frame}\n"
           "\\begin{frame}\nNo title.\n\\end{frame}\n"
           "\\begin{frame}[allowframebreaks,t,plain,label=one,shrink=10]{Options}\nText.\n"
           "\\end{frame}\n"
           "\\begin{frame}[allowframebreaks=0.8,squeeze,label={a,b}]{More}\nText.\n\\end{frame}\n"
           "\\begin{columns}[T,totalwidth=0.9\\textwidth,onlytextwidth]\n"
           "\\begin{column}[b]{0.48\\linewidth}\nA\\footnote<\\value{beamerpauses}->[frame]{N.}"
           "\\footnote<.->[frame]{M.}\n\\end{column}\n\\end{columns}\n")
    out, counts = decks.talkify(tex)
    # Code that shows LaTeX: its \\end{frame} doesn't end the frame, and
    # nothing in it is rewritten.
    code = ("\\begin{verbatim}\n\\begin{frame}{Hello}\n\\begin{columns}[T]\n"
            "\\footnote<.->[frame]{x}\n\\section{A = B}\n\\end{frame}\n\\end{verbatim}\n")
    shown = decks.talkify("\\begin{frame}{Teaching}\n" + code + "\\end{frame}\n")[0]
    lists = decks.talkify(
        "\\begin{enumerate}\n[a.]\n\\item A\n  \\begin{enumerate}\n  [(i)]\n  \\item B\n"
        "  \\end{enumerate}\n\\end{enumerate}\n\\begin{enumerate}[<+->]\n[1)]\n"
        "\\setcounter{enumi}{2}\n\\item C\n\\end{enumerate}\n")[0]
    sections = decks.talkify("\\section{Profit: MR = MC}\\label{p}\n"
                             "\\subsection*[Short]{Long\\footnote{n}}\n"
                             "\\subsubsection[toc={X}]{Y}\n"
                             "\\section[{A ]}]{B}\n")[0]
    modes = decks.talkify("\\mode<presentation>{\\usetheme{Madrid}}\\mode<trans>{x}"
                          "\\mode<article>{y}\\mode <beamer|handout>{z}\\mode*")[0]
    gapped = [header(2, "A"), header(4, "S"), para(), header(5, "B"), para(), header(2, "C"),
              header(4, "T"), para()]
    gapped_level = decks.renumber(gapped, 4)
    skipped = [header(1, "A"), header(3, "B"), header(4, "S"), para()]
    skipped_level = decks.renumber(skipped, 4)
    noted_levels = decks.section_levels(
        [header(2), {"t": "Div", "c": [["", ["notes"], []], [header(1), para()]]},
         header(3), para()], 3)
    table = {"t": "Table", "c": [["", [], []], [None, [para("Caption.")]], [], [], [], []]}
    bare = {"t": "Table", "c": [["", [], []], [None, []], [], [], [], []]}
    noted = [table, {"t": "Div", "c": [["", ["notes"], []], [bare]]}, bare]
    meta_list = {"title": {"t": "MetaList", "c": [{"t": "MetaInlines", "c": [{"t": "Str", "c": "T"}]}]},
                 "author": {"t": "MetaList", "c": [{"t": "MetaString", "c": "A"}]},
                 "date": {"t": "MetaList", "c": [{"t": "MetaString", "c": "1"},
                                                 {"t": "MetaString", "c": "2"}]}}
    changed = decks.single_values(meta_list)
    linked = decks.talkify("\\begin{frame}{A}\n\\protect\\phantomsection\\label{a-b.c}\n"
                           "See \\hyperlink{a-b.c}{this} and \\hyperlink{t}{that}."
                           "\\hypertarget{t}{}\\label{both}\\hypertarget{both}{}"
                           "\\hyperlink{both}{too}\n\\begin{verbatim}\n\\hyperlink{a-b.c}{x}\n"
                           "\\end{verbatim}\n\\end{frame}\n")[0]
    doc = {"meta": {}, "blocks": [header(1), para(), header(1), para()]}
    declared = {"meta": {"slide-level": {"t": "MetaString", "c": "2"}},
                "blocks": [header(1), para()]}
    extra = []
    if pikepdf is None:
        print("  skip  pikepdf not found; what tidy does to a deck's PDF isn't checked")
    else:
        bins, only = os.path.join(work, "bins.pdf"), os.path.join(work, "only-bins.pdf")
        os.makedirs(work, exist_ok=True)
        # Nothing of pikepdf's on the terminal: its warning on saving a
        # widget no form reaches came out in the middle of the suite's own.
        with warnings.catch_warnings(record=True) as warned:
            warnings.simplefilter("always")
            tidy_fixture(bins)
            tidy_fixture(only, ghost=False)
            tidy_counts, only_counts = decks.tidy(bins), decks.tidy(only)
        left = (["/P", "/Artifact", "/P", "/footnote", "/Artifact"], [0, 1],
                ["https://example.org/0", "/Widget", "https://example.org/3"], [0, 2, 3], ["note"])
        extra.append((
            "tidy takes out a link bin, its link, and their entries in the parent tree and the"
            " ID tree, leaves an artifact with content of its own, a link in it too, or a form"
            " field, drops a /Ref to an element the tree doesn't hold, and counts a mark tied"
            " to no note; a bin alone to take out is taken out too, and nothing is warned of",
            lambda: tidy_counts == {"step_links": 1, "ghost_refs": 1, "untied_marks": 1}
            and not warned
            and tidied(bins) == left
            and only_counts == {"step_links": 1, "ghost_refs": 0, "untied_marks": 1}
            and tidied(only) == left))
    return extra + [
        ("the slide level is the shallowest heading something else follows",
         lambda: decks.slide_level([header(1), para(), header(2), para()]) == 1
         and decks.slide_level([header(1), header(2), para(), header(1), header(2), para()]) == 2),
        ("a heading followed by a heading or a rule doesn't count, and a div is looked into",
         lambda: decks.slide_level([header(1), rule, header(2), para()]) == 2
         and decks.slide_level([{"t": "Div", "c": [["", [], []], [header(3), para()]]}]) == 3
         and decks.slide_level([para()]) == 6),
        ("a deck's own slide-level wins, and marks the intermediate a deck's",
         lambda: decks.mark(declared) == 2 and decks.level_of(declared) == 2
         and decks.mark(doc) == 1 and decks.level_of({"meta": {}}) is None),
        ("a slide-level Pandoc wouldn't take isn't one",
         lambda: decks.declared_level({"slide-level": {"t": "MetaString", "c": "9"}}) is None
         and decks.declared_level({"slide-level": {"t": "MetaString", "c": "0"}}) == 0),
        ("language: is named only where lang isn't given",
         lambda: decks.language_key({"language": {}}) and not decks.language_key(
             {"language": {}, "lang": {}})),
        ("a title or a date given as a list of one is its value, authors stay a list",
         lambda: changed == ["title"] and meta_list["title"]["t"] == "MetaInlines"
         and meta_list["author"]["t"] == "MetaList" and meta_list["date"]["t"] == "MetaList"),
        ("slides with no title: a rule with no heading after it, and text before the first",
         lambda: decks.untitled_slides([para(), header(1), para(), rule, para(),
                                        rule, header(1), para()], 1) == 2
         and decks.untitled_slides([header(1), para()], 1) == 0
         and decks.untitled_slides([div, header(1)], 1) == 1),
        ("the shape: a setting, the deck's aspectratio, 4:3 for beamer's variables, else 16:9",
         lambda: decks.aspect_ratio({}, "4:3") == ("4:3", "slides.aspect_ratio")
         and decks.aspect_ratio({"aspectratio": {"t": "MetaString", "c": "169"}}, "auto")[0] == "16:9"
         and decks.aspect_ratio({"aspectratio": {"t": "MetaString", "c": "3:2"}}, "auto")[0] == "3:2"
         and decks.aspect_ratio({"theme": {"t": "MetaString", "c": "Madrid"}}, "auto")[0] == "4:3"
         and decks.aspect_ratio({"theme": {"t": "MetaString", "c": "white"}}, "auto")[0] == "16:9"
         and decks.aspect_ratio({"urlcolor": {"t": "MetaString", "c": "blue"}}, "auto")[0] == "16:9"),
        ("a slide's title is H1, one deeper for each level of sections",
         lambda: decks.frame_tag([header(1), para()], 1) == "H1"
         and decks.frame_tag([header(1), header(2), para()], 2) == "H2"
         and decks.frame_tag([header(2), para()], 2) == "H1"
         and decks.frame_tag([header(1), header(2), header(3), para()], 3) == "H3"),
        ("a frame with a code block, or highlighted inline code, is frame*, and only those",
         lambda: counts["verbatim"] == 2 and "\\begin{frame*}{Code}" in out
         and "\\begin{frame}{Inline}" in out and "\\begin{frame*}{Verb}" in out
         and "\\end{frame*}" in out and "fragile" not in out),
        ("a frame with no title gets an empty one",
         lambda: counts["untitled"] == 1 and "\\begin{frame}{}\nNo title." in out),
        ("beamer's options become ltx-talk's keys, a key of ltx-talk's stays, the rest are named",
         lambda: "\\begin{frame}[auto-break=true,vertical-alignment=top,label=one]{Options}" in out
         and "\\begin{frame}[auto-break=true,auto-break-coverage=0.8,label={a,b}]{More}" in out
         and counts["dropped"] == ["plain", "shrink=10", "squeeze"]),
        ("code is left as it is, and a frame it shows doesn't end the frame",
         lambda: shown == "\\begin{frame*}{Teaching}\n" + code + "\\end{frame*}\n"),
        ("a numbered list's style is LaTeX's label, at its depth, incremental too",
         lambda: "\\begin{enumerate}\n\\def\\labelenumi{\\alph{enumi}.}\n\\item A" in lists
         and "  \\begin{enumerate}\n  \\def\\labelenumii{(\\roman{enumii})}\n" in lists
         and "\\begin{enumerate}[<+->]\n\\def\\labelenumi{\\arabic{enumi})}\n"
             "\\setcounter{enumi}{2}" in lists and "[a.]" not in lists),
        ("a section's short title is a key, so an = in its title is text",
         lambda: "\\section[shorttitle={Profit: MR = MC}]{Profit: MR = MC}\\label{p}" in sections
         and "\\subsection*[shorttitle={Short}]{Long\\footnote{n}}" in sections
         and "\\subsubsection[toc={X}]{Y}" in sections
         and "\\section[shorttitle={{A ]}}]{B}" in sections),
        ("beamer's modes are ltx-talk's",
         lambda: modes == "\\mode<projector>{\\usetheme{Madrid}}\\mode<article>{x}"
                          "\\mode<article>{y}\\mode<projector>{z}"),
        ("sections renumbered 1, 2, 3 in order, the slides below the deepest",
         lambda: gapped_level == 2 and [h["c"][0] for h in gapped if h["t"] == "Header"]
         == [1, 2, 3, 1, 2]
         and skipped_level == 3 and [h["c"][0] for h in skipped if h["t"] == "Header"]
         == [1, 2, 3]
         and decks.renumber([header(1), para()], 0) == 0
         and noted_levels == [2]),
        ("a table in the notes isn't the PDF's, for the captions' repair",
         lambda: decks.captioned_tables(noted) == [True, False]),
        ("columns' alignment and width become ltx-talk's, and a footnote loses the overlay",
         lambda: "\\begin{columns}[t,width=0.9\\textwidth]" in out
         and "\\begin{column}[b]{0.48\\linewidth}" in out
         and "\\footnote{N.}\\footnote{M.}" in out and "beamerpauses" not in out),
        ("a frame with no end is left as it is", lambda: decks.talkify(
            "\\begin{frame}{A}\ntext")[0] == "\\begin{frame}{A}\ntext"),
        ("a link to a label goes to it, one to a hypertarget stays, a label's too, and code"
         " is left alone",
         lambda: "See \\hyperref[a-b.c]{this} and \\hyperlink{t}{that}" in linked
         and "\\hyperlink{both}{too}" in linked and "\\hyperlink{a-b.c}{x}" in linked),
    ]


# --------------------------------------------------------------------------
# a folder of decks
# --------------------------------------------------------------------------

PAGES = """\
targets:
  pages:
    format: html
  md:
    format: markdown
  copy:
    format: source
  book:
    format: epub3
"""


def case_folder(work):
    work = folder(work, PAGES)
    shutil.copy(os.path.join(work, "README.md"), os.path.join(work, "notes.adoc"))
    write(os.path.join(work, "image-alt.csv"), "Image,Alt\nimg/chart,A line rising to the right\n")
    result = convert(work, "--quick")
    out = result.stderr
    page = lambda name: read(os.path.join(work, "pages", name))  # noqa: E731
    flat = page("Flat-Deck.html")
    sectioned = page("sectioned.html")
    md = read(os.path.join(work, "md", "Flat-Deck.md"))
    copy = read(os.path.join(work, "copy", "Flat Deck.md"))
    return [
        ("a folder project.kind says is slides makes each Markdown file a deck",
         lambda: result.returncode == 0
         and "Slides: 3 deck(s) written in Markdown (project.kind)" in out),
        ("a README isn't a deck, and a file of another kind is left out and named",
         lambda: not os.path.exists(os.path.join(work, "pages", "README.html"))
         and "left out (notes.adoc)" in out),
        ("an EPUB isn't written for decks, and the run says so",
         lambda: "target book is format epub3, which isn't written for decks" in out
         and not os.path.exists(os.path.join(work, "book"))),
        ("the page's H1 is the deck's title, a list of one in its YAML, and its slides H2s",
         lambda: headings(flat)[:3] == [(1, "Demand: A Short Deck"), (2, "Value Is Subjective"),
                                        (2, "Specialization => Growth")]
         and "<title>Demand: A Short Deck</title>" in flat),
        ("a section is an H2 and its slides H3s, below the title",
         lambda: headings(sectioned) == [(1, "Sections and Slides"), (2, "Part One"),
                                         (3, "Opening"), (3, "Some Code"), (2, "Part Two"),
                                         (3, "A Footnote")]),
        ("a deck with no title: its one heading is a slide's, an H1, not made its title",
         lambda: headings(page("untitled.html")) == [(1, "Only Slide")]
         and "<title>untitled</title>" in page("untitled.html")),
        ("a deck's page heads its notes, as a book's page does",
         lambda: re.search(r'<section id="footnotes"[^>]*>\s*<hr />\s*'
                           r'<h2 class="footnotes-title">Notes</h2>', sectioned) is not None),
        ("the authors are on the page, as on a title slide",
         lambda: '<p class="author">A. Lecturer</p>' in flat
         and '<p class="author">C. Speaker</p>' in sectioned),
        ("a slide's notes are under it, in a closed disclosure labeled Speaker notes",
         lambda: re.search(r'<details class="notes">\s*<summary>Speaker notes</summary>\s*'
                           r'<p>Ask what the class would pay for water\.</p>\s*</details>', flat)
         is not None and "<details class=\"notes\" open" not in flat),
        ("a pause isn't on the page", lambda: ". . ." not in flat
         and "Second point, after a pause." in flat),
        ("a picture named in another case is read as its file, and said to be",
         lambda: 'src="img/chart.png"' in flat
         and "names an image img/Chart.PNG, and the file is img/chart.png" in out),
        ("the alt-text sidecar reaches a deck's picture",
         lambda: 'alt="A line rising to the right"' in flat),
        ("the run names the slide with no title, the language: key, and the untitled deck",
         lambda: "1 slide(s) in 1 deck(s) have no title (Flat Deck.md 1)" in out
         and "1 deck(s) name their language language: (Flat Deck.md)" in out
         and "1 deck(s) have no title (untitled.md)" in out),
        ("the markdown target keeps the notes and the title, and no slide level of ours",
         lambda: "::: notes" in md and 'title: "Demand: A Short Deck"' in md
         and "slide-level" not in md),
        ("the source copy holds the alt text decided",
         lambda: "A line rising to the right" in copy and "::: notes" in copy),
        ("slides aren't packaged", lambda: "Slides aren't packaged yet" in out
         and not os.path.exists(os.path.join(work, "imsmanifest.xml"))),
    ]


def case_shared_alt(work):
    """One alt text on different pictures is looked for within a deck, in
    its report and in the output check alike, its pages and its
    presentation one document; two decks' pictures are each their own."""
    decks_given = {
        "one.md": "---\ntitle: One\n---\n\n# Part A\n\n## First\n\n![A rising line](img/a.png)\n\n"
                  "# Part B\n\n## Second\n\n![A rising line](img/b.png)\n",
        "two.md": "---\ntitle: Two\n---\n\n# First\n\n![Two dots](img/c.png)\n",
        "three.md": "---\ntitle: Three\n---\n\n# First\n\n![Two dots](img/d.png)\n"}
    unready = too_old("REVEALJS_PANDOC", "a deck's reveal.js presentation")
    if unready:
        print(f"  skip  {unready}; the pictures sharing alt text in a presentation aren't "
              "looked for")
    work = folder(work, "targets:\n  pages:\n    format: html\n    pages:\n      split_level: 1\n"
                        + ("" if unready else "  show:\n    format: revealjs\n"),
                  decks_given=decks_given)
    for name, color in (("a", 10), ("b", 20), ("c", 30), ("d", 40)):
        png(os.path.join(work, "img", name + ".png"), color, color, color)
    result = convert(work, "--quick")
    rows = sorted((r[0], r[2], r[3]) for r in rows_of(os.path.join(work, "image-alt-missing.csv")))
    found = sorted((r[0], r[2].split(":")[0]) for r in rows_of(os.path.join(work, "output-check.csv"))
                   if r[1] == "image-alt-shared")
    return [
        ("a deck's pictures sharing alt text each have a row, and two decks' don't",
         lambda: result.returncode == 0 and rows == [
             ("img/a.png", "one", "shared with 1 other image"),
             ("img/b.png", "one", "shared with 1 other image")]),
        ("the output check names them on the deck's pieces" + ("" if unready else
                                                               " and in its presentation")
         + ", and not the other decks'",
         lambda: found == [("pages/one--part-a.html", "img/a.png"),
                           ("pages/one--part-b.html", "img/b.png")]
         + ([] if unready else [("show/one.html", "img/a.png"), ("show/one.html", "img/b.png")])),
    ]


def case_lowercase_names(work):
    """media.lowercase in a deck's presentation and its page alike: the
    picture copied under its name in lowercase, and named so."""
    unready = too_old("REVEALJS_PANDOC", "a deck's reveal.js presentation")
    if unready:
        print(f"  skip  {unready}; a presentation's lowercased names aren't checked")
    problem = None if unready else revealjs_ready()
    if problem:
        return [("a copy of reveal.js to build the presentations with: " + problem,
                 lambda: False)]
    work = folder(work, "defaults:\n  media:\n    lowercase: true\ntargets:\n  pages:\n"
                        "    format: html\n" + ("" if unready else "  show:\n    format: revealjs\n"),
                  decks_given={"one.md": "---\ntitle: One\n---\n\n# First\n\n"
                                         "![A rising line](Img/Rising.PNG)\n"})
    png(os.path.join(work, "Img", "Rising.PNG"), 10, 20, 30)
    result = convert(work, "--quick")
    shown = {name: read(os.path.join(work, name, "one.html"))
             if os.path.exists(os.path.join(work, name, "one.html")) else ""
             for name in ("pages",) + (() if unready else ("show",))}
    return [
        ("each copies the picture under its name in lowercase, and names it so",
         lambda: result.returncode == 0
         and all(os.path.isfile(os.path.join(work, name, "img", "rising.png"))
                 and 'src="img/rising.png"' in shown[name] for name in shown)),
    ]


def case_display_style(work):
    """A formula whose TeX opens with \\displaystyle is in display style in
    a deck's presentation, as on its page and in its PDF: its MathML in an
    mstyle that says so, laid out as a display is, a sum's limits under and
    over it (target-blocks.lua), where another formula's are scripts."""
    unready = too_old("REVEALJS_PANDOC", "a deck's reveal.js presentation")
    if unready:
        print(f"  skip  {unready}; a presentation's formula in display style isn't checked")
    problem = None if unready else revealjs_ready()
    if problem:
        return [("a copy of reveal.js to build the presentations with: " + problem,
                 lambda: False)]
    work = folder(work, "targets:\n  pages:\n    format: html\n"
                  + ("" if unready else "  show:\n    format: revealjs\n"),
                  decks_given={"one.md": "---\ntitle: One\n---\n\n# First\n\nA sum, "
                                         "$\\displaystyle \\sum_{i=1}^{n} i$, and one in "
                                         "a line, $\\sum_{j=1}^{n} j$.\n"})
    result = convert(work, "--quick")
    shown = {name: read(os.path.join(work, name, "one.html"))
             if os.path.exists(os.path.join(work, name, "one.html")) else ""
             for name in ("pages",) + (() if unready else ("show",))}
    return [
        (("on the deck's page" if unready else "in the presentation, as on the deck's page")
         + ", the formula opening with \\displaystyle is in an mstyle that says so, its "
         "sum's limits under and over it, and the other's beside it",
         lambda: result.returncode == 0 and all(
             page.count('<semantics><mstyle displaystyle="true"><mrow><munderover>') == 1
             and len(re.findall(r"<msubsup><mo>(?:&#x2211;|∑)</mo>", page)) == 1
             for page in shown.values())),
    ]


def case_downsample(work):
    """images.downsample in a deck's presentation, its PowerPoint file,
    and its PDF: each carries the picture scaled down to twice the width
    it's shown at, and the deck's own file stays as it is."""
    old_reveal = too_old("REVEALJS_PANDOC", "a deck's reveal.js presentation")
    if old_reveal:
        print(f"  skip  {old_reveal}; a presentation's scaled picture isn't checked")
    old_pptx = too_old("PPTX_PANDOC", "a deck's PowerPoint file")
    if old_pptx:
        print(f"  skip  {old_pptx}; a PowerPoint file's scaled picture isn't checked")
    problem = None if old_reveal else revealjs_ready()
    if problem:
        return [("a copy of reveal.js to build the presentations with: " + problem,
                 lambda: False)]
    unready = pdf_ready()
    if unready:
        print(f"  skip  {unready}; a deck's PDF with a scaled picture isn't checked")
    if old_reveal and old_pptx and unready:
        return []
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        print("  skip  Pillow not installed (python3-pil); a deck's pictures aren't scaled")
        return []
    import random
    import zipfile
    work = folder(work, "defaults:\n  images:\n    downsample: 2\ntargets:\n"
                        + ("" if old_reveal else "  show:\n    format: revealjs\n")
                        + ("" if old_pptx else "  slides:\n    format: pptx\n")
                        + ("" if unready else "  print:\n    format: pdf\n"),
                  decks_given={"one.md": "---\ntitle: One\n---\n\n# First\n\n"
                                         "![A wide band of noise](img/wide.png){width=100px}\n"})
    noise = random.Random(5)

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    raw = b"".join(b"\x00" + noise.randbytes(400 * 3) for _ in range(200))
    original = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 400, 200, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    with open(os.path.join(work, "img", "wide.png"), "wb") as fh:
        fh.write(original)
    result = convert(work, "--quick")

    def size(data):
        return struct.unpack(">II", data[16:24]) if data[:8] == b"\x89PNG\r\n\x1a\n" else None

    def file_size(*parts):
        path = os.path.join(work, *parts)
        if not os.path.exists(path):
            return None
        with open(path, "rb") as fh:
            return size(fh.read(64))

    def pptx_sizes():
        path = os.path.join(work, "slides", "one.pptx")
        if not os.path.exists(path):
            return []
        with zipfile.ZipFile(path) as z:
            return [size(z.read(n)) for n in z.namelist() if n.startswith("ppt/media/")]

    def pdf_sizes():
        import pypdf

        def resolved(entry):
            # A page's resources can be an indirect object, which pypdf 5
            # reads as what it names and pypdf 4, Ubuntu 24.04's, doesn't.
            return entry.get_object() if hasattr(entry, "get_object") else entry
        found = []
        for page in pypdf.PdfReader(os.path.join(work, "print", "one.pdf")).pages:
            resources = resolved(page.get("/Resources")) or {}
            for image in (resolved(resources.get("/XObject")) or {}).values():
                image = image.get_object()
                if image.get("/Subtype") == "/Image":
                    found.append((int(image["/Width"]), int(image["/Height"])))
        return found
    checks = [
        ("the deck converts, and its own picture stays as it is",
         lambda: result.returncode == 0
         and open(os.path.join(work, "img", "wide.png"), "rb").read() == original),
    ]
    if not old_reveal:
        checks.append(("its presentation carries the picture scaled down to twice the width "
                       "it's shown at",
                       lambda: file_size("show", "img", "wide.png") == (200, 100)))
    if not old_pptx:
        checks.append(("its PowerPoint file carries it scaled down likewise",
                       lambda: pptx_sizes() == [(200, 100)]))
    if not unready:
        checks.append(("its PDF carries it scaled down likewise",
                       lambda: pdf_sizes() == [(200, 100)]))
    return checks


def case_implied(work):
    work = folder(work, None, decks_given={"one.md": UNTITLED})
    result = convert(work, "--quick")
    plain = os.path.join(os.path.dirname(work), "plain")
    os.makedirs(plain)
    write(os.path.join(plain, "one.md"), "---\ntitle:\n- One Page\nlinkcolor: blue\n---\n\n"
          "# Body\n\nA [link](https://example.org/).\n")
    write(os.path.join(plain, "project.yaml"),
          "project:\n  identifier: org.example.book\n  title: A Book\n")
    book = convert(plain, "--quick")
    return [
        ("with no target declared, a folder of Markdown decks gets html",
         lambda: result.returncode == 0
         and os.path.exists(os.path.join(work, "html", "one.html"))),
        ("a folder of Markdown that says nothing is a book, its page titled by a list of one",
         lambda: book.returncode == 0 and "Slides:" not in book.stderr
         and "<title>One Page</title>" in read(os.path.join(plain, "html", "one.html"))),
        ("a link color gives dark mode the text's color, which CSS takes, not inherit",
         lambda: "light-dark(blue, currentcolor)" in read(os.path.join(plain, "html", "one.html"))
         and "inherit)" not in read(os.path.join(plain, "html", "one.html"))),
    ]


def case_levels(work):
    work = folder(work, "targets:\n  pages:\n    format: html\n",
                  decks_given={"agenda.md": AGENDA, "subsections.md": SUBSECTIONS,
                               "nested.md": NESTED, "cue.md": CUE})
    result = convert(work, "--quick")
    agenda = read(os.path.join(work, "pages", "agenda.html"))
    subsections = read(os.path.join(work, "pages", "subsections.html"))
    nested = read(os.path.join(work, "pages", "nested.html"))
    check = rows_of(os.path.join(work, "output-check.csv"))
    return [
        ("a slide before the first section is an H2, as a section is, and one in it an H3",
         lambda: result.returncode == 0 and [n for n, _ in headings(agenda)] == [1, 2, 2, 3, 4, 2, 3]
         and headings(agenda)[1] == (2, "Agenda") and headings(agenda)[3] == (3, "The Curve")),
        ("a heading in a slide is one below the slide's, though the deck skips a level",
         lambda: headings(agenda)[4] == (4, "A Block")),
        ("sections at ## and slides at ### are H2s and H3s",
         lambda: headings(subsections) == [(1, "Subsections"), (2, "Part A"), (3, "Slide One"),
                                           (2, "Part B"), (3, "Slide Two")]),
        ("two levels of sections nest, a slide in a part with no chapter one below the part,"
         " and a heading in the notes or a quotation one below its slide, whatever its level",
         lambda: headings(nested) == [(1, "Nested"), (2, "Part One"), (3, "Chapter A"),
                                      (4, "Slide A1"), (3, "Chapter B"), (4, "Slide B1"),
                                      (5, "A Cue"), (2, "Part Two"), (3, "Slide C1"),
                                      (4, "Quoted big heading"), (4, "A Block After")]),
        ("the output check finds no heading that skips a level",
         lambda: not [r for r in check if r[1] == "heading-skips-level"]),
        ("a heading in the notes that sets the slide level is named, with the level"
         " without it",
         lambda: "WARNING: a heading in the speaker notes of 1 deck(s) sets its slide level"
                 " (cue.md 1, 2 without it)" in result.stderr),
    ]


SPLIT = """\
targets:
  split:
    format: html
    pages:
      split_level: 2
    slides:
      notes: visible
      notes_label: Notes for the speaker
  bare:
    format: html
    slides:
      notes: omitted
"""


# A section and its slide in a div in a div, a passage in German with an
# id around an incremental one, with a sentence before the section.
DIVIDED = """---
title: Divided
---

# Part One

## First Slide

Text.

::: {#german lang=de}
Noch ein Satz.

::: incremental
# Teil Zwei

## Zweite Folie

- Ein Punkt
:::
:::
"""


def case_split(work):
    work = folder(work, SPLIT, decks_given={"sectioned.md": SECTIONED, "langs.md": LANGS,
                                            "divided.md": DIVIDED})
    result = convert(work, "--quick")
    split = os.path.join(work, "split")

    def page(name):
        path = os.path.join(split, name + ".html")
        return html.unescape(read(path)) if os.path.exists(path) else ""
    piece = page("sectioned--a-footnote")
    bare = read(os.path.join(work, "bare", "sectioned.html"))
    return [
        ("pages.split_level cuts a deck into a page per slide, its sections groups",
         lambda: result.returncode == 0 and sorted(
             n for n in os.listdir(split) if n.endswith(".html")) == [
             "divided--first-slide.html", "divided--zweite-folie.html",
             "langs--a-mot-slide.html", "langs--eine-folie.html", "langs--ohne-titel.html",
             "langs--teil-zwei.html", "langs--zweite-folie.html",
             "sectioned--a-footnote.html", "sectioned--opening.html",
             "sectioned--some-code.html"]),
        # Pandoc's slide writers find a deck's sections and slides in a div,
        # and the split had found them only outside one.
        ("a slide in a passage in another language is cut there, its title in it",
         lambda: page("langs--zweite-folie").count('<h1><span lang="de">Zweite Folie') == 1),
        ("in a div in a div too, what's around it in copies of both, the id on the first",
         lambda: '<div id="german" lang="de">\n<p>Noch ein Satz.</p>' in page("divided--first-slide")
         and '<h1><span lang="de">Zweite Folie</span></h1>' in page("divided--zweite-folie")
         and re.search(r'<div lang="de">\s*<div class="incremental">\s*<ul[^>]*>\s*<li>Ein Punkt',
                       page("divided--zweite-folie"))
         and 'id="german"' not in page("divided--zweite-folie")),
        ("and its section, a group, is a page of its own for the footnote in its heading,"
         " which no page had shown",
         lambda: '<h1><span lang="de">Teil Zwei' in page("langs--teil-zwei")
         and "Die Fußnote des Teils." in page("langs--teil-zwei")),
        # The split had moved a deck's headings up a level, and deck-html.lua
        # took a block's title for a slide's, a block with no title an
        # empty heading.
        ("a block's title on a slide's page is one below the slide's, and a block with"
         " no title is no heading, as on the whole deck's page",
         lambda: [level for level, _ in headings(page("langs--zweite-folie"))] == [1, 2, 2]
         and [level for level, _ in headings(page("langs--ohne-titel"))] == [1, 2]
         and not re.search(r"<h[1-6][^>]*>\s*</h[1-6]>",
                           "".join(page(n[:-5]) for n in os.listdir(split)))),
        ("a slide's page is headed by its title, as its H1",
         lambda: headings(piece)[:1] == [(1, "A Footnote")]),
        ("notes: visible opens the disclosure, under the label given",
         lambda: '<details class="notes" open>' in piece
         and "<summary>Notes for the speaker</summary>" in piece),
        ("notes: omitted leaves them off", lambda: "Notes for part two" not in bare
         and "<details" not in bare),
        ("the split's report stays, though a target that doesn't split runs after it",
         lambda: os.path.exists(os.path.join(work, "page-names-new.csv"))),
    ]


# --------------------------------------------------------------------------
# the PDF
# --------------------------------------------------------------------------

PDF = """\
defaults:
  pages:
    split_level: 1
targets:
  pdf:
    format: pdf
  pages:
    format: html
"""
SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20"><rect width="40" height="20"/></svg>'


def math_elements(path):
    """How many MathML structure elements the PDF has."""
    count = 0
    with pikepdf.open(path) as pdf:
        def walk(element):
            nonlocal count
            if isinstance(element, pikepdf.Array):
                for kid in element:
                    walk(kid)
            elif isinstance(element, pikepdf.Dictionary):
                if str(element.get("/S")) == "/math":
                    count += 1
                if element.get("/K") is not None:
                    walk(element.K)
        walk(pdf.Root.StructTreeRoot.K)
    return count


def empty_paragraphs(path):
    """How many empty paragraph elements a copy of the PDF would lose."""
    import pdfparagraphs
    copy = path + ".copy.pdf"
    shutil.copy(path, copy)
    try:
        return pdfparagraphs.remove_from(copy)
    finally:
        os.remove(copy)


def colors(path, page=None):
    """The fill colors a page's content sets, or every page's."""
    found = set()
    with pikepdf.open(path) as pdf:
        for number in range(len(pdf.pages)) if page is None else [page]:
            content = pdf.pages[number].Contents
            data = b"".join(c.read_bytes() for c in (
                content if isinstance(content, pikepdf.Array) else [content]))
            found |= set(re.findall(rb"([\d.]+ [\d.]+ [\d.]+) rg", data))
    return found


def highlight_color(token):
    """A token's #rrggbb in the theme every writer is given
    (lib/highlighting.py)."""
    with open(highlighting.THEME, encoding="utf-8") as fh:
        return json.load(fh)["text-styles"][token]["text-color"]


def latex_color(color):
    """A #rrggbb color as Pandoc's highlighting macros give it LaTeX, and
    LaTeX a PDF's content."""
    return " ".join("%.2f" % (int(color[i:i + 2], 16) / 255) for i in (1, 3, 5)).encode()


def figures(path):
    """The alt text of each Figure."""
    found = []
    with pikepdf.open(path) as pdf:
        def walk(element):
            if isinstance(element, pikepdf.Array):
                for kid in element:
                    walk(kid)
            elif isinstance(element, pikepdf.Dictionary):
                if str(element.get("/S")) == "/Figure":
                    found.append(str(element.get("/Alt", "")))
                if element.get("/K") is not None:
                    walk(element.K)
        walk(pdf.Root.StructTreeRoot.K)
    return found


def verapdf():
    return os.environ.get("VERAPDF") or shutil.which("verapdf")


def pdf_ready():
    """Why the PDF's cases can't run here, or None: ltx-talk or what it
    needs missing (decks.ltx_talk_problem), a package the suite's decks
    load (SUITE_TEX), or pikepdf and pypdf to read the PDFs. A machine to
    set up, not the code failing, so the checks skip, saying why."""
    problem = decks.ltx_talk_problem()
    if problem:
        # Said before what isn't checked, after a semicolon.
        return problem.rstrip(".")
    lacking = tex_missing()
    if lacking:
        return ("TeX lacks " + ", ".join(lacking) + ", which the suite's decks load ("
                + decks.latexbuild.tlmgr_command("install " + " ".join(lacking)) + ")")
    if pikepdf is None or pypdf is None:
        return "pikepdf and pypdf are needed to read the PDFs built"
    return None


# The TeX packages the suite's decks load beyond what ltx-talk needs, which
# a smaller TeX can lack, by a file each holds: LaTeX's tagging code, which
# TinyTeX lacks (latex-lab's, which \DocumentMetadata reads, and tagpdf),
# and luamml, for the formulas' MathML; cancel and pict2e for the odd
# deck's terms struck out of its formulas, which neither TinyTeX nor TeX
# Live's medium scheme has; and luacolor and lua-ul, not in TinyTeX, which
# the template loads for its struck text (docs/installation.md).
SUITE_TEX = [("latex-lab", "documentmetadata-support.ltx"), ("tagpdf", "tagpdf.sty"),
             ("luamml", "luamml.sty"), ("cancel", "cancel.sty"), ("pict2e", "pict2e.sty"),
             ("luacolor", "luacolor.sty"), ("lua-ul", "lua-ul.sty")]


def tex_missing():
    """The packages of SUITE_TEX TeX can't find, none where there's no
    kpsewhich to ask."""
    if not shutil.which("kpsewhich"):
        return []
    return [package for package, name in SUITE_TEX
            if not subprocess.run(["kpsewhich", name], capture_output=True, text=True,
                                  stdin=subprocess.DEVNULL).stdout.strip()]


def outline(path):
    with pikepdf.open(path) as pdf:
        with pdf.open_outline() as tree:
            def walk(items):
                return [(item.title, walk(item.children)) for item in items]
            return walk(tree.root)


def role_of(path, name):
    """The standard type a structure type maps to, through the role maps."""
    with pikepdf.open(path) as pdf:
        root = pdf.Root.StructTreeRoot
        for ns in root.get("/Namespaces") or []:
            mapped = (ns.get("/RoleMapNS") or {}).get("/" + name)
            if mapped is not None:
                return str(mapped[0] if isinstance(mapped, pikepdf.Array) else mapped)[1:]
        mapped = (root.get("/RoleMap") or {}).get("/" + name)
        return str(mapped)[1:] if mapped is not None else None


def table_kids(path):
    """The kinds of each Table element's children."""
    found = []
    with pikepdf.open(path) as pdf:
        def walk(element):
            if not isinstance(element, pikepdf.Dictionary):
                if isinstance(element, pikepdf.Array):
                    for kid in element:
                        walk(kid)
                return
            if str(element.get("/S")) == "/Table":
                kids = element.get("/K")
                kids = list(kids) if isinstance(kids, pikepdf.Array) else [kids]
                found.append([str(k.get("/S"))[1:] for k in kids
                              if isinstance(k, pikepdf.Dictionary)])
            if element.get("/K") is not None:
                walk(element.K)
        walk(pdf.Root.StructTreeRoot.K)
    return found


def text_of(path):
    return " ".join(page.extract_text() or "" for page in pypdf.PdfReader(path).pages)


def holds(text, phrase):
    """Whether text extracted from a PDF holds phrase, its spaces aside:
    where the font changes, pypdf before 5.1 infers a space that later
    releases don't, so Ubuntu 24.04's (4.0.2) gives "per unit ." for
    "per unit." and "= >" for a title's "=>", whose ">" another face
    supplies."""
    return re.sub(r"\s+", "", phrase) in re.sub(r"\s+", "", text)


def shape_of(path):
    box = pypdf.PdfReader(path).pages[0].mediabox
    return float(box.width) / float(box.height)


# The namespaces of PDF 2.0's standard structure types and PDF 1.7's.
STANDARD = ("http://iso.org/pdf2/ssn", "http://iso.org/pdf/ssn")


def resolver(root):
    """A function giving a structure element's standard type: through its
    namespace's role map to a type in a standard namespace, PDF 2.0's
    (FENote, Title) or PDF 1.7's, or through the role map where it has no
    namespace, as in PDF/UA-1. The role map of a PDF 2.0 file maps PDF
    2.0's types to PDF 1.7's too (FENote to Note), for older readers."""
    rolemap = root.get("/RoleMap") or {}

    def standard(element):
        name, ns = element.get("/S"), element.get("/NS")
        for _ in range(8):
            if ns is not None:
                if str(ns.get("/NS")) in STANDARD:
                    break
                mapped = (ns.get("/RoleMapNS") or {}).get(name)
                if mapped is None:
                    break
                if isinstance(mapped, pikepdf.Array):
                    name, ns = mapped[0], (mapped[1] if len(mapped) > 1 else None)
                else:
                    name, ns = mapped, None
            else:
                mapped = rolemap.get(name)
                if mapped is None:
                    break
                name = mapped
        return str(name)
    return standard


def heading_elements(path):
    """Each heading element in the structure, in reading order: its level
    (through the role maps), whether it holds content of its own, its
    ActualText, and the text of the page its content is on."""
    found = []
    with pikepdf.open(path) as pdf:
        root = pdf.Root.StructTreeRoot
        standard = resolver(root)
        pages = {page.objgen: n for n, page in enumerate(pdf.pages)}
        texts = [page.extract_text() or "" for page in pypdf.PdfReader(path).pages]

        def walk(element):
            if isinstance(element, pikepdf.Array):
                for kid in element:
                    walk(kid)
                return
            if not isinstance(element, pikepdf.Dictionary) or "/S" not in element:
                return
            kind = standard(element)
            kids = element.get("/K")
            if re.fullmatch(r"/H[1-6]", kind):
                listed = list(kids) if isinstance(kids, pikepdf.Array) else [kids]
                marked = [k for k in listed if isinstance(k, pikepdf.Dictionary) and "/MCID" in k]
                content = bool(marked) or any(isinstance(k, int) for k in listed)
                page = element.get("/Pg") or (marked[0].get("/Pg") if marked else None)
                found.append((int(kind[2]), content, str(element.get("/ActualText", "")),
                              texts[pages[page.objgen]].strip() if page is not None else ""))
            if kids is not None:
                walk(kids)
        walk(root.K)
    return found


def lang_spans_holding_paragraphs(path):
    """How many paragraphs or parts are tagged inside a span marked with a
    language: a passage in another language begins inside its paragraph,
    not the paragraph inside it."""
    found = 0
    with pikepdf.open(path) as pdf:
        root = pdf.Root.StructTreeRoot
        standard = resolver(root)

        def walk(element, inside):
            nonlocal found
            if isinstance(element, pikepdf.Array):
                for kid in element:
                    walk(kid, inside)
                return
            if not isinstance(element, pikepdf.Dictionary) or "/S" not in element:
                return
            kind = standard(element)
            if inside and kind in ("/P", "/Part"):
                found += 1
            if element.get("/K") is not None:
                walk(element.K, inside or (kind == "/Span" and "/Lang" in element))
        walk(root.K, False)
    return found


def titles(path):
    """Every structure element's title (/T)."""
    found = []
    with pikepdf.open(path) as pdf:
        def walk(element):
            if isinstance(element, pikepdf.Array):
                for kid in element:
                    walk(kid)
            elif isinstance(element, pikepdf.Dictionary):
                if "/T" in element and "/S" in element:
                    found.append(str(element.T))
                if element.get("/K") is not None:
                    walk(element.K)
        walk(pdf.Root.StructTreeRoot.K)
    return found


def structure(path):
    """The structure tree in reading order: (element, its standard role,
    its ancestors' roles), with the role maps followed (resolver)."""
    pdf = pikepdf.open(path)
    root = pdf.Root.StructTreeRoot
    standard = resolver(root)
    found = []

    def walk(element, above):
        if isinstance(element, pikepdf.Array):
            for kid in element:
                walk(kid, above)
            return
        if not isinstance(element, pikepdf.Dictionary) or "/S" not in element:
            return
        role = standard(element)
        found.append((element, role, above))
        if element.get("/K") is not None:
            walk(element.K, above + (role,))

    walk(root.K, ())
    return pdf, found


def refs(element):
    """What an element's /Ref names."""
    named = element.get("/Ref")
    if named is None:
        return []
    return list(named) if isinstance(named, pikepdf.Array) else [named]


def document_info(path, key):
    """A value of the PDF's document information dictionary, as text, or
    None; read while the file is open, as pikepdf's objects need."""
    with pikepdf.open(path) as pdf:
        value = pdf.docinfo.get(key)
        return None if value is None else str(value)


def footnote_ties(path, linked=True):
    """(marks, untied, unlinked, notes_before, dangling): the footnote marks
    LaTeX tags, those without a /Ref to a note that refers back, those not
    a link (when linked), the notes that come before a mark of theirs, and
    the /Ref entries of marks and notes naming an element the structure
    tree doesn't hold."""
    pdf, found = structure(path)
    order = {element.objgen: n for n, (element, _, _) in enumerate(found)}
    marks = [e for e, _, _ in found if e.S == "/footnotemark"]
    untied = unlinked = before = dangling = 0
    for mark in marks:
        notes = [r for r in refs(mark) if r.get("/S") == "/footnote"]
        if not notes or not all(mark.objgen in [b.objgen for b in refs(r)] for r in notes):
            untied += 1
        if linked and not any(isinstance(k, pikepdf.Dictionary) and k.get("/S") == "/Link"
                              for k in (mark.K if isinstance(mark.get("/K"), pikepdf.Array)
                                        else [mark.get("/K")])):
            unlinked += 1
    for element, _, _ in found:
        if element.S in ("/footnote", "/footnotemark"):
            dangling += sum(1 for r in refs(element) if r.objgen not in order)
        if element.S == "/footnote":
            for mark in refs(element):
                if order.get(mark.objgen, -1) > order[element.objgen]:
                    before += 1
    return len(marks), untied, unlinked, before, dangling


def within(path, role, container):
    """The roles of the elements of role within one of role container,
    in reading order: each a pattern."""
    _, found = structure(path)
    return [r for _, r, above in found if re.fullmatch(role, r)
            and any(re.fullmatch(container, a) for a in above)]


def heading_texts(path):
    """Each heading's level and its own text, in reading order: the
    characters its own content holds (pdftext), not a footnote's mark."""
    texts = pdftext.marked_text(path)
    pdf, found = structure(path)
    pages = {page.objgen: n for n, page in enumerate(pdf.pages)}
    return [(int(role[2]), pdftext.own_text(element, texts, pages))
            for element, role, _ in found if re.fullmatch(r"/H[1-6]", role)]


def artifacts_in_tables(path):
    """How many Artifact elements a table holds."""
    pdf, found = structure(path)
    with pdf:
        return sum(1 for e, _, above in found if e.S == "/Artifact" and "/Table" in above)


def link_contents(path):
    """{address: /Contents} for each link to an address."""
    found = {}
    with pikepdf.open(path) as pdf:
        for page in pdf.pages:
            for annot in page.obj.get("/Annots") or []:
                action = annot.get("/A")
                if annot.get("/Subtype") == "/Link" and action is not None and "/URI" in action:
                    found[str(action.URI)] = str(annot.get("/Contents", ""))
    return found


def misdirected_marks(path):
    """The footnote marks whose link goes to a page other than their
    note's: the link's destination, resolved, against the first page the
    note's content is on."""
    pdf, found = structure(path)
    with pdf:
        pages = {page.objgen: n for n, page in enumerate(pdf.pages)}
        names = pdf.Root.get("/Names")
        dests = pikepdf.NameTree(names.Dests) if names is not None and "/Dests" in names else {}

        def page_of(element):
            todo = [element]
            while todo:
                node = todo.pop(0)
                if isinstance(node, pikepdf.Dictionary):
                    if "/Pg" in node:
                        return pages.get(node.Pg.objgen)
                    kids = node.get("/K")
                    if kids is not None:
                        todo[0:0] = list(kids) if isinstance(kids, pikepdf.Array) else [kids]
            return None

        def target(annot):
            action = annot.get("/A")
            dest = action.get("/D") if action is not None else annot.get("/Dest")
            if isinstance(dest, (pikepdf.String, pikepdf.Name)):
                dest = dests[str(dest)]
            if isinstance(dest, pikepdf.Dictionary):
                dest = dest.D
            return pages.get(dest[0].objgen)

        wrong = 0
        for mark, _, _ in found:
            if mark.S != "/footnotemark":
                continue
            notes = [r for r in refs(mark) if r.get("/S") == "/footnote"]
            for link in mark.get("/K") if isinstance(mark.get("/K"), pikepdf.Array) else []:
                if not isinstance(link, pikepdf.Dictionary) or link.get("/S") != "/Link":
                    continue
                for kid in (link.K if isinstance(link.get("/K"), pikepdf.Array) else [link.K]):
                    if isinstance(kid, pikepdf.Dictionary) and kid.get("/Type") == "/OBJR":
                        if any(target(kid.Obj) != page_of(note) for note in notes):
                            wrong += 1
        return wrong


def note_languages(path):
    """The languages each footnote's note holds, in reading order: its own
    and its parts' /Lang, joined."""
    pdf, found = structure(path)
    with pdf:
        out = []
        for note, role, _ in found:
            if role != "/FENote":
                continue
            langs, todo = set(), [note]
            while todo:
                node = todo.pop()
                if isinstance(node, pikepdf.Dictionary) and "/S" in node:
                    if "/Lang" in node:
                        langs.add(str(node.Lang))
                    kids = node.get("/K")
                    if kids is not None:
                        todo += list(kids) if isinstance(kids, pikepdf.Array) else [kids]
            out.append(",".join(sorted(langs)))
        return out


def paragraph_languages(path):
    """The languages each footnote's paragraphs are in, in reading order:
    each paragraph's own /Lang or the nearest within the note above it, ""
    for the document's, joined."""
    pdf, found = structure(path)
    with pdf:
        out = []
        for note, role, _ in found:
            if role != "/FENote":
                continue
            langs, standard = set(), resolver(pdf.Root.StructTreeRoot)
            todo = [(note, str(note.Lang) if "/Lang" in note else "")]
            while todo:
                node, lang = todo.pop()
                if not isinstance(node, pikepdf.Dictionary) or "/S" not in node:
                    continue
                lang = str(node.Lang) if "/Lang" in node else lang
                if standard(node) == "/P":
                    langs.add(lang)
                kids = node.get("/K")
                for kid in (list(kids) if isinstance(kids, pikepdf.Array) else [kids]):
                    todo.append((kid, lang))
            out.append(",".join(sorted(langs)))
        return out


def link_pages(path):
    """{a link's /Contents: the index of the page it goes to}, for each link
    within the PDF."""
    with pikepdf.open(path) as pdf:
        pages = {page.objgen: n for n, page in enumerate(pdf.pages)}
        names = pdf.Root.get("/Names")
        dests = pikepdf.NameTree(names.Dests) if names is not None and "/Dests" in names else {}
        found = {}
        for page in pdf.pages:
            for annot in page.obj.get("/Annots") or []:
                action = annot.get("/A")
                if annot.get("/Subtype") != "/Link" or action is None or action.get("/S") != "/GoTo":
                    continue
                dest = action.D
                if not isinstance(dest, pikepdf.Array):
                    dest = dests[str(dest)]
                if isinstance(dest, pikepdf.Dictionary):
                    dest = dest.D
                found[str(annot.get("/Contents", ""))] = pages.get(dest[0].objgen)
        return found


def page_with(path, words):
    """The index of the first page whose text holds words."""
    return next((n for n, page in enumerate(pypdf.PdfReader(path).pages)
                 if words in (page.extract_text() or "")), None)


def piece_levels(pages, stem):
    """The levels of the headings on the pages a split cut a deck into, in
    their order."""
    pieces = []
    for name in os.listdir(pages):
        if name.endswith(".html"):
            page = read(os.path.join(pages, name))
            part = re.search(r'<meta name="page-part" content="(\d+)/', page)
            if f'<meta name="source-page" content="{stem}"' in page and part:
                pieces.append((int(part.group(1)), page))
    return [level for _, page in sorted(pieces) for level, _ in headings(page)]


def step_links(path, title):
    """The links left on a slide's earlier steps: on each page but the
    last whose text starts with the slide's title, and any LaTeX gathered
    as untagged (an Artifact structure element holding them), with any
    entry of the parent tree naming a structure element not in the tree."""
    with pikepdf.open(path) as pdf:
        texts = [page.extract_text() or "" for page in pypdf.PdfReader(path).pages]
        steps = [n for n, text in enumerate(texts) if text.strip().startswith(title)]
        left = sum(len(pdf.pages[n].obj.get("/Annots") or []) for n in steps[:-1])
    pdf, found = structure(path)
    reachable = {e.objgen for e, _, _ in found if e.is_indirect}
    stale = 0
    for _, value in pikepdf.NumberTree(pdf.Root.StructTreeRoot.ParentTree).items():
        for element in (list(value) if isinstance(value, pikepdf.Array) else [value]):
            if isinstance(element, pikepdf.Dictionary) and element.is_indirect \
                    and element.objgen not in reachable:
                stale += 1

    def holds_link(element):
        kids = element.get("/K")
        for kid in (list(kids) if isinstance(kids, pikepdf.Array) else [kids]):
            if isinstance(kid, pikepdf.Dictionary) and (
                    kid.get("/Type") == "/OBJR" or ("/S" in kid and holds_link(kid))):
                return True
        return False

    return len(steps), left + stale + sum(1 for e, _, _ in found
                                          if e.S == "/Artifact" and holds_link(e))


def languages(path):
    """The languages structure elements give, other than the document's."""
    found = set()
    with pikepdf.open(path) as pdf:
        def walk(element):
            if isinstance(element, pikepdf.Array):
                for kid in element:
                    walk(kid)
            elif isinstance(element, pikepdf.Dictionary):
                if "/Lang" in element and "/S" in element:
                    found.add(str(element.Lang))
                if element.get("/K") is not None:
                    walk(element.K)
        walk(pdf.Root.StructTreeRoot.K)
    return found


GERMAN_DECK = """---
title: Auf Deutsch
lang: de
---

## Eine Folie

Ein Satz auf Deutsch.
"""
ENGLISH_DECK = """---
title: In English
---

## A Slide

A sentence in English.
"""


def case_languages(work):
    """A deck in another language than the project's, as its YAML says:
    its page, its presentation, its PowerPoint file, and its PDF in its
    own, each deck's language decided once for every target, a deck with
    none in the project's."""
    ready = pdf_ready()
    old_reveal = too_old("REVEALJS_PANDOC", "a deck's reveal.js presentation")
    if old_reveal:
        print(f"  skip  {old_reveal}; a presentation's language isn't checked")
    old_pptx = too_old("PPTX_PANDOC", "a deck's PowerPoint file")
    if old_pptx:
        print(f"  skip  {old_pptx}; a PowerPoint file's language isn't checked")
    work = folder(work, "targets:\n  pages:\n    format: html\n"
                  + ("" if old_reveal else "  show:\n    format: revealjs\n")
                  + ("" if old_pptx else "  slides:\n    format: pptx\n")
                  + ("" if ready else "  pdf:\n    format: pdf\n"),
                  decks_given={"allemand.md": GERMAN_DECK, "english.md": ENGLISH_DECK})
    result = convert(work, "--quick")

    def root(*parts):
        path = os.path.join(work, *parts)
        found = re.search(r'<html\b[^>]*\slang="([^"]*)"', read(path)) \
            if os.path.isfile(path) else None
        return found.group(1) if found else None

    def runs(name):
        path = os.path.join(work, "slides", name + ".pptx")
        if not os.path.isfile(path):
            return set()
        with zipfile.ZipFile(path) as z:
            return {lang for part in z.namelist() if part.startswith("ppt/slides/slide")
                    for lang in re.findall(r'<a:(?:rPr|endParaRPr)\b[^>]*\slang="([^"]*)"',
                                           z.read(part).decode("utf-8"))}

    def catalog(name):
        path = os.path.join(work, "pdf", name + ".pdf")
        if not os.path.isfile(path):
            return None
        with pikepdf.open(path) as pdf:
            return str(pdf.Root.get("/Lang", ""))
    shown = ("pages",) + (() if old_reveal else ("show",))
    checks = [
        ("each deck converts", lambda: result.returncode == 0),
        ("a deck's page " + ("is" if old_reveal else "and presentation are") + " in its "
         "language, one with none in the project's",
         lambda: [(root(name, "allemand.html"), root(name, "english.html")) for name in shown]
         == [("de", "en-US")] * len(shown)),
    ]
    if not old_pptx:
        checks.append(("and its PowerPoint file's text",
                       lambda: runs("allemand") == {"de"} and runs("english") == {"en-US"}))
    checks += [
        ("the run names the deck in another language and drafts its row",
         lambda: "1 page(s) are in another language than the book's, en-US: allemand de "
         "(its file)" in result.stderr
         and rows_of(os.path.join(work, "languages-new.csv"))[0][:2] == ["allemand", "de"]),
    ]
    if ready:
        print(f"  skip  {ready}; a deck's PDF's language isn't checked")
    else:
        checks.append(("and its PDF", lambda: (catalog("allemand"), catalog("english"))
                       == ("de", "en-US")))
    return checks


def item_rows(path):
    """The lines of ITEM_CODE's PDF holding its list's items, from the top,
    each its glyphs' characters without spaces in the order drawn, and
    where each begins (pdftext.glyph_boxes): ([text], [left])."""
    if not os.path.exists(path):
        return [], []
    rows = {}
    for page, baseline, left, _right, char in pdftext.glyph_boxes(path):
        rows.setdefault((page, -baseline), []).append((left, char))
    found = [(re.sub(r"\s+", "", "".join(c for _l, c in glyphs)),
              round(min((l for l, c in glyphs if c.strip()),
                        default=min(l for l, _c in glyphs)), 1))
             for _key, glyphs in sorted(rows.items())]
    found = [f for f in found if "Deckopens" in f[0] or "Theitemafter" in f[0]]
    return [f[0] for f in found], [f[1] for f in found]


def case_pdf(work):
    problem = pdf_ready()
    if problem:
        print(f"  skip  {problem}; a deck's PDF isn't checked")
        return []
    svg = shutil.which("rsvg-convert")
    work = folder(work, PDF, decks_given={
        "Flat Deck.md": FLAT, "untitled.md": UNTITLED, "agenda.md": AGENDA, "odd.md": ODD,
        "nested.md": NESTED, "more.md": MORE, "subsections.md": SUBSECTIONS,
        "headings.md": HEADINGS, "langs.md": LANGS, "code-notes.md": CODE_NOTES,
        "shaded-notes.md": SHADED_NOTES, "item-code.md": ITEM_CODE,
        "sectioned.md": SECTIONED.replace("Right.", "![A dark bar](<img/a bar.svg>)" if svg
                                          else "Right.")})
    write(os.path.join(work, "img", "a bar.svg"), SVG)
    if not svg:
        print("  skip  rsvg-convert not found; a deck's SVG picture isn't checked")
    result = convert(work)
    out = result.stderr
    flat = os.path.join(work, "pdf", "Flat-Deck.pdf")
    sectioned = os.path.join(work, "pdf", "sectioned.pdf")
    agenda = os.path.join(work, "pdf", "agenda.pdf")
    odd = os.path.join(work, "pdf", "odd.pdf")
    nested = os.path.join(work, "pdf", "nested.pdf")
    more = os.path.join(work, "pdf", "more.pdf")
    subsections = os.path.join(work, "pdf", "subsections.pdf")
    headings = os.path.join(work, "pdf", "headings.pdf")
    langs = os.path.join(work, "pdf", "langs.pdf")
    code_notes = os.path.join(work, "pdf", "code-notes.pdf")
    shaded_notes = os.path.join(work, "pdf", "shaded-notes.pdf")
    item_code = os.path.join(work, "pdf", "item-code.pdf")
    built = lambda: [os.path.join(work, "pdf", name)  # noqa: E731
                     for name in sorted(os.listdir(os.path.join(work, "pdf")))]
    check = rows_of(os.path.join(work, "output-check.csv"))
    ran = verapdf()
    if not ran:
        print("  skip  veraPDF not found (set VERAPDF); the PDFs' claims aren't judged")

    def built_text(path):
        """The deck's text, nothing where its PDF wasn't built, which its
        checks fail on, so that the rest run."""
        return text_of(path) if os.path.exists(path) else ""
    flat_text, sectioned_text = built_text(flat), built_text(sectioned)
    agenda_text, odd_text, more_text = built_text(agenda), built_text(odd), built_text(more)
    levels = lambda path: [h[0] for h in heading_elements(path)]  # noqa: E731
    checks = [
        ("a PDF of each deck, the whole deck however its pages are cut",
         lambda: result.returncode == 0 and sorted(os.listdir(os.path.join(work, "pdf"))) == [
             "Flat-Deck.pdf", "agenda.pdf", "code-notes.pdf", "headings.pdf", "item-code.pdf",
             "langs.pdf", "more.pdf", "nested.pdf", "odd.pdf", "sectioned.pdf",
             "shaded-notes.pdf", "subsections.pdf", "untitled.pdf"]
         and "Wrote 13 PDF(s)" in out and "still changing" not in out),
        ("a slide's title is an H1, or an H2 in a section, and a section's an H1",
         lambda: levels(flat) == [1, 1, 1, 1] and levels(sectioned) == [1, 2, 2, 1, 2]),
        ("a slide before the first section is an H1, as a section is, and bookmarked"
         " beside the sections, one in another language by its words",
         lambda: levels(agenda) == [1, 1, 2, 3, 1, 2] and outline(agenda) == [
             ("Agenda", []), ("Supply", [("The Curve", [])]),
             ("Profit: MR = MC", [("The Rule", [])])]),
        ("sections at ## are LaTeX's sections, their slides H2s under H1s",
         lambda: levels(subsections) == [1, 2, 1, 2] and outline(subsections) == [
             ("Part A", [("Slide One", [])]), ("Part B", [("Slide Two", [])])]),
        ("two levels of sections nest, in the headings and the bookmarks",
         lambda: levels(nested) == [1, 2, 3, 2, 3, 1, 2, 3, 3] and outline(nested) == [
             ("Part One", [("Chapter A", [("Slide A1", [])]), ("Chapter B", [("Slide B1", [])])]),
             ("Part Two", [("Slide C1", [])])]),
        ("a slide's bookmark leaves out its title's footnote",
         lambda: ("A Claim", []) in outline(odd)),
        # hyperref's \\pdfstringdef, which writes it, would make them a dash.
        ("and keeps two hyphens in its title as they're printed",
         lambda: ("Pages 10--20", []) in outline(odd) and "Pages 10--20" in odd_text),
        ("a slide in a div is a slide: bookmarked, its title's footnote set",
         lambda: ("Wrapped Slide", []) in outline(more) and "Wrapped Slide5" in more_text
         and "5The wrapped" in more_text),
        ("a heading in a quotation is a heading one below its slide's, in the quotation,"
         " as a block's title is, whatever level the deck gives it",
         lambda: levels(more)[:14] == [1, 1, 1, 1, 1, 2, 2, 1, 1, 1, 2, 2, 2, 1]
         and levels(more)[14:] == [1, 1]
         and within(more, r"/H[1-6]", "/BlockQuote") == ["/H2", "/H2"]
         and within(nested, r"/H[1-6]", "/BlockQuote") == ["/H3"]
         and "Quoted heading" in more_text and "Quoted big heading" in more_text),
        ("and so is a heading in a list's item or a table's cell, and a block's title, one"
         " below the block's it's in, across columns too; a heading in a quotation in a"
         " block is below that, or beside it, as the deck has it, and one in a quotation"
         " below another there; a block with no title has no heading",
         lambda: levels(headings) == [1, 2, 1, 2, 1, 2, 3, 4, 3, 1, 2, 3, 4, 1, 2, 3]
         and within(headings, r"/H[1-6]", "/LBody") == ["/H2"]
         and within(headings, r"/H[1-6]", "/TD") == ["/H2"]
         and within(headings, r"/H[1-6]", "/BlockQuote") == ["/H4", "/H3", "/H4", "/H2", "/H3"]
         and all(h[1] for h in heading_elements(headings))),
        ("a link to a heading in a quotation, a block's anchor, and a slide lands on its"
         " page, where a \\hyperlink to a label went to the last page, and on the pages,"
         " a block's anchor stays where its heading goes",
         lambda: link_pages(headings).get("a heading in a quotation")
         == page_with(headings, "Quoted beside Inner") is not None
         and link_pages(headings).get("the anchor block") == page_with(headings, "An anchor")
         and link_pages(headings).get("the columns slide") == page_with(headings, "Columns")
         and page_with(headings, "Columns") is not None
         and not [r for r in check if r[1] == "link-to-missing-fragment"]),
        ("the PDF's headings are at the levels the deck's pages give them, split a page a"
         " slide, and no page has a heading for a block with no title, as no PDF has",
         lambda: piece_levels(os.path.join(work, "pages"), "headings") == levels(headings)
         and not [r for r in check if r[1] == "empty-heading"]),
        # The split found a deck's sections and slides only outside a div, and
        # a heading it cut lost its footnote, its title being its words alone.
        ("and a section in a passage in another language is cut there, its pages' levels"
         " the PDF's, and a section's footnote is on its page, as on the whole deck's",
         lambda: piece_levels(os.path.join(work, "pages"), "langs") == levels(langs)
         and os.path.exists(os.path.join(work, "pages", "langs--teil-zwei.html"))
         and "Marginal revenue and marginal cost." in read(
             os.path.join(work, "pages", "agenda--profit-mr-mc.html"))),
        ("a block's title is a heading one below its slide's",
         lambda: heading_elements(agenda)[3][0] == 3),
        ("every footnote's mark is a link to its note, the two tied by a /Ref each way,"
         " naming nothing the tree lacks, and no note comes before its mark: in a slide's"
         " or a section's title, a block's, a heading in an item or a quotation, a"
         " caption, a table, and on a slide shown in steps",
         lambda: footnote_ties(more) == (7, 0, 0, 0, 0) and footnote_ties(odd) == (4, 0, 0, 0, 0)
         and footnote_ties(agenda) == (1, 0, 0, 0, 0)
         and footnote_ties(headings) == (4, 0, 0, 0, 0)
         and "aren't tied to their notes" not in out),
        ("each mark's link goes to its note's page, on a slide shown in steps too, in a deck"
         " with a slide LaTeX breaks over pages",
         lambda: all(misdirected_marks(path) == 0 for path in built())),
        ("a heading's footnote set after it is in the heading's language: a section's, a"
         " slide's, a block's, and a quotation's heading's in a div in German, and one in"
         " a passage in French in a slide's title, every paragraph of a German note"
         " German; and a block with no title in the div has no heading, and a quotation's"
         " heading in one is one below its slide's",
         lambda: note_languages(langs) == ["de", "de", "de", "de", "fr"]
         and paragraph_languages(langs) == ["de", "de", "de", "de", ""]
         and levels(langs) == [1, 2, 1, 2, 3, 3, 2, 2, 3]),
        ("a footnote in a heading of any kind is set after it, never in it, and no note's"
         " text is a heading",
         lambda: all(within(path, "/FENote", r"/H[1-6]") == []
                     and within(path, r"/H[1-6]", "/FENote") == [] for path in built())
         and len(within(agenda, "/FENote", ".*")) == 1
         and len(within(headings, "/FENote", ".*")) == 4),
        ("a section's footnote is set on its slide after its heading, its link with its"
         " text for /Contents, as any link has",
         lambda: holds(agenda_text, "1Marginal revenue") and holds(agenda_text, "Each is per unit.")
         and link_contents(agenda).get("https://example.org/unit") == "per unit"),
        ("a slide's earlier steps have no links, and nothing left untagged holds any, and"
         " the run notes the links taken out, and from which deck",
         lambda: step_links(more, "Paused") == (2, 0)
         and "NOTE: 2 link(s) on the earlier steps of slides shown in steps were taken out of"
         " 1 deck PDF(s) (more)" in out),
        ("a piece the split cut has its headings placed as the page has them, none skipped",
         lambda: not [r for r in check if r[1] == "heading-skips-level"]),
        ("a passage in another language that begins a paragraph or an item is in it,"
         " and a link, a slide, and a slide's title are tagged with theirs",
         lambda: lang_spans_holding_paragraphs(more) == 0
         and languages(more) >= {"fr", "es", "it", "de"}
         and ("Eine Folie", []) in outline(more) and ("Le titre anglais", []) in outline(more)
         and "Le titre anglais" in titles(more)),
        ("footnotes in a table's caption and head, after one LaTeX leaves out, numbered"
         " once, in order, and on a slide shown in steps",
         lambda: "Prices1" in more_text and "Price2" in more_text
         and "1The caption" in more_text and "2The head" in more_text
         and "Paused3" in more_text and "Second.4" in more_text and "Done.6" in more_text
         and "In a description" not in more_text
         and "y7" in more_text and "7The inner" in more_text),
        ("a block and a column in another language are tagged with it, the block's"
         " heading too",
         lambda: "Ein Block" in more_text and "Pour" in more_text
         and languages(more) >= {"fr", "es", "it", "de"}),
        ("beamer's commands with a star, and setbeameroption, do nothing, and are named",
         lambda: re.search(r"NOTE: beamer's [^\n]*\\setbeamercolor[^\n]*\\setbeameroption", out)),
        ("no page has a placeholder LaTeX left on a first run",
         lambda: flat_text and sectioned_text and agenda_text
         and "Temporary page" not in flat_text + sectioned_text + agenda_text),
        ("each slide with a title is bookmarked, under its section, once though it pauses",
         lambda: outline(flat) == [("Value Is Subjective", []), ("Specialization => Growth", []),
                                   ("A Chart", []), ("Market Demand", [])]
         and outline(sectioned) == [("Part One", [("Opening", []), ("Some Code", [])]),
                                    ("Part Two", [("A Footnote", [])])]),
        ("the title slide has the deck's title, subtitle, authors, and institute",
         lambda: all(words in sectioned_text for words in (
             "Sections and Slides", "A conference talk", "B. Speaker", "A University"))),
        ("speaker notes aren't in the PDF",
         lambda: flat_text and sectioned_text and "Ask what the class would pay" not in flat_text
         and "Notes for part two" not in sectioned_text),
        ("a title with > keeps it: the bold face lacks it, and another face supplies it",
         lambda: holds(flat_text, "Specialization => Growth") and "Missing character" not in out
         and "missing from the PDF" not in out),
        ("4:3 for a deck that names a theme, 16:10 for its aspectratio",
         lambda: abs(shape_of(flat) - 4 / 3) < 0.01 and abs(shape_of(sectioned) - 1.6) < 0.01
         and "4:3 (its theme, which is beamer's) for 1" in out),
        ("the code is set, and the options ltx-talk has no key for are named",
         lambda: "def demand(p):" in sectioned_text and re.search(
             r"frame options ltx-talk has no key for were left out of the PDFs: "
             r"(plain, shrink=10|shrink=10, plain)\.", out)),
        ("code that shows a frame is shown as written, its \\end{frame} no end",
         lambda: "\\begin{frame}{Hello}" in odd_text and "\\begin{columns}[T]" in odd_text
         and "\\end{frame}" in odd_text),
        ("a footnote in a caption, a table, and a slide's title, each numbered once, in order",
         lambda: "1The first note." in odd_text and "note2" in odd_text
         and "2The caption" in odd_text and "A Claim3" in odd_text and "low4" in odd_text
         and "3The title" in odd_text and "4The table" in odd_text),
        ("struck text is set, and a passage in another language is tagged with it",
         lambda: "struck" in odd_text and languages(odd) >= {"fr", "de"}),
        # The cancel package's strokes, drawn by pict2e (latexbuild's
        # PDF_MACROS), not with glyphs of the line10 font.
        ("a formula's term struck out is drawn as a line, one for each stroke, and no "
         "glyph of LaTeX's line10 font is in the deck",
         lambda: len(pdftext.diagonal_strokes(odd)) == 4
         and not {"LINE10", "LINEW10"} & pdftext.base_fonts(odd)),
        ("beamer's command in header-includes does nothing, and the run names it",
         lambda: re.search(r"NOTE: beamer's [^\n]*\\setbeamertemplate in the header-includes "
                           r"of more, odd do nothing", out)),
        ("a section titled with an =, and a lettered list, are set",
         lambda: "Profit: MR = MC" in agenda_text and re.search(r"a\.\s*Upward sloping", agenda_text)
         and re.search(r"b\.\s*Steeper", agenda_text)),
        ("a table's caption is its Caption, not a first row",
         lambda: table_kids(flat) and table_kids(flat)[0][0] == "Caption"
         and table_kids(odd) and table_kids(odd)[0][0] == "Caption"
         and "don't line up" not in out),
        ("a section has a slide of its own, its title the slide's heading, and once",
         lambda: len(pypdf.PdfReader(sectioned).pages) == 6
         and [(h[0], h[3]) for h in heading_elements(sectioned) if h[0] == 1]
         == [(1, "Part One"), (1, "Part Two")]
         and all(h[1] and not h[2] for h in heading_elements(sectioned))
         and sectioned_text.count("Part One") == 1),
        ("a deck with no title has no title slide, and its file's name for a title",
         lambda: pikepdf.open(os.path.join(work, "pdf", "untitled.pdf")).open_metadata()
         .get("dc:title") == "untitled"
         and text_of(os.path.join(work, "pdf", "untitled.pdf")).startswith("Only Slide")),
        ("a deck with no date has none on its title slide, not the day it was built",
         lambda: not re.search(r"\d", pypdf.PdfReader(sectioned).pages[0].extract_text())),
        ("a formula's MathML is in the structure", lambda: math_elements(flat) >= 1),
        ("no empty paragraph element is left", lambda: empty_paragraphs(flat) == 0
         and empty_paragraphs(sectioned) == 0),
        ("a link is in the blue told apart from text",
         lambda: any(re.fullmatch(rb"0(?:\.0)? 0\.4 0\.8", c) for c in colors(sectioned, 2))),
        ("an SVG picture named with a space is made a PDF, its alt text kept",
         lambda: not svg or "A dark bar" in figures(sectioned)),
        ("a code block's spaces are characters in the PDF, its indentation kept",
         lambda: pdftext.code_lines(sectioned) == ["def demand(p):",
                                                   "    return 12 - 2 * p > 0"]),
        # LaTeX's footnote takes its text as an argument, where a code
        # block's verbatim can't be read (footnote-code.lua), and a
        # section's footnotes are written apart from the deck, which had
        # no highlighting macros for them (deck-pdf.lua).
        ("a code block in a footnote is set in its note, a section's, a slide's, or a"
         " block title's, highlighted or not, its lines and spaces kept",
         lambda: pdftext.code_lines(code_notes) == ["q   mc", "mc  = 2 * q", "tc  = q * q  % of all"]
         and pdftext.code_lines(shaded_notes) == ["def mr(q):", "    return 12 - 2 * q  # 100%",
                                                  "slope = -2"]
         and within(code_notes, "/Code", "/FENote") == ["/Code"] * 3
         and within(shaded_notes, "/Code", "/FENote") == ["/Code"] * 2),
        ("and highlighted code in a section's footnote, the deck's only, is set, and the"
         " deck's own header-includes, one or a list, kept beside the code's files",
         lambda: holds(text_of(code_notes), "Computed by mc(2), and tabled")
         and footnote_ties(code_notes) == (3, 0, 0, 0, 0)
         and footnote_ties(shaded_notes) == (2, 0, 0, 0, 0)
         and document_info(code_notes, "/Subject") == "Code in notes"
         and document_info(shaded_notes, "/Keywords") == "notes, code"),
        # Under LaTeX's tagging, the label had waited for the next item's
        # first paragraph, and was set there, over that item's ("1.2.").
        ("a list's item that opens with highlighted code has its number beside the code's "
         "first line, and the next item its own",
         lambda: item_rows(item_code)[0] == ["1.Deckopens=1", "2.Theitemafterthecode."]
         and len(set(item_rows(item_code)[1])) == 1),
        # In the theme every writer is given (lib/highlighting.py): in the
        # writer's macros for a slide's code, and in those deck-pdf.lua
        # writes for inline code in a section's footnote, the deck's only.
        ("highlighted code is drawn in the theme's colors, a slide's and a section's "
         "footnote's alike",
         lambda: latex_color(highlight_color("DecVal")) in colors(sectioned)
         and latex_color(highlight_color("DecVal")) in colors(code_notes)),
        ("each heading's words, its footnote's mark not among them",
         lambda: heading_texts(headings) == [
             (1, "A List"), (2, "In an item"), (1, "A Table"), (2, "In a cell"),
             (1, "Blocks"), (2, "Outer"), (3, "Inner"), (4, "Quoted under Inner"),
             (3, "Quoted beside Inner"), (1, "Columns"), (2, "Left"),
             (3, "Right"), (4, "Quoted right"), (1, "Quoted"), (2, "Quoted"),
             (3, "Under it")]
         and heading_texts(agenda)[3] == (3, "A Block")),
    ]
    if ran:
        checks.insert(1, ("veraPDF finds nothing to fail in any of them",
                          lambda: not [r for r in check if r[1].startswith("verapdf")]))
    return checks


# A table whose head LaTeX sets twice, the second an artifact, with a
# footnote in it.
CAPTIONED = """---
title: Captioned
---

# A Table

| Price[^h] | Quantity |
|------:|------:|
| 1 | 10 |

: Prices

[^h]: The head's note.
"""

# A circle in LaTeX's picture mode, asked for at 80 points, which LaTeX's
# lcircle10 font draws at 40, its largest, and pict2e at 80 with a path:
# built with picture_paths off, in LaTeX's own glyphs.
PICTURED = """---
title: Pictured
---

# A Circle

```{=latex}
\\setlength{\\unitlength}{1pt}\\begin{picture}(90,90)\\put(45,45){\\circle{80}}\\end{picture}
```
"""

# Captions that carry their own labels, one by a word the settings name, a
# figure marked unnumbered, and a figure and a table whose captions don't,
# which keep ltx-talk's label, "Figure:" or "Table:".
LABELS = """---
title: Labels
---

# Labeled

![Figure 1.1 A blue square the deck labels itself](img/chart.png)

# Unnumbered

![A blue square the deck leaves unnumbered](img/chart.png){.unnumbered}

# Plain

![A blue square with no label of its own](img/chart.png)

# An Exhibit

![Exhibit 3 A blue square labeled as an exhibit](img/chart.png)

# A Labeled Table

| Year | Rate |
|------|------|
| 2020 | 4    |

: Table 2.1 Rates the deck labels itself

# A Plain Table

| Year | Count |
|------|-------|
| 2021 | 7     |

: Counts by year
"""


def figure_captions(path):
    """The standard roles of each figure's Caption's elements, in order: a
    Lbl for ltx-talk's label, then its paragraph."""
    pdf, found = structure(path)
    standard = resolver(pdf.Root.StructTreeRoot)
    captions = []
    for element, role, above in found:
        if role == "/Caption" and above and above[-1] != "/Table":
            kids = element.get("/K")
            kids = list(kids) if isinstance(kids, pikepdf.Array) else [kids]
            captions.append([standard(k)[1:] for k in kids
                             if isinstance(k, pikepdf.Dictionary) and "/S" in k])
    return captions


def case_pdf_settings(work):
    problem = pdf_ready()
    if problem:
        print(f"  skip  {problem}; a deck's PDF settings aren't checked")
        return []
    plain = folder(os.path.join(work, "plain"), "targets:\n  pdf:\n    format: pdf\n"
                   "    picture_paths: \"off\"\n    pdf:\n      repair_captions: false\n",
                   decks_given={"captioned.md": CAPTIONED, "pictured.md": PICTURED})
    unrepaired = convert(plain)
    captioned = os.path.join(plain, "pdf", "captioned.pdf")
    pictured = os.path.join(plain, "pdf", "pictured.pdf")
    plain_check = rows_of(os.path.join(plain, "output-check.csv"))
    work = folder(os.path.join(work, "ua1"), "defaults:\n  captions:\n"
                  "    figure_prefixes: [Figure, Exhibit]\n"
                  "targets:\n  pdf:\n    format: pdf\n    pdf:\n"
                  "      standard: [ua-1]\n    slides:\n      aspect_ratio: \"5:4\"\n",
                  decks_given={"sectioned.md": SECTIONED, "agenda.md": AGENDA,
                               "labels.md": LABELS})
    result = convert(work)
    built = os.path.join(work, "pdf", "sectioned.pdf")
    agenda = os.path.join(work, "pdf", "agenda.pdf")
    labels = os.path.join(work, "pdf", "labels.pdf")
    # Its words with no spaces, which pypdf before 5.1 infers where the
    # font changes (holds).
    labels_text = re.sub(r"\s+", "", text_of(labels)) if os.path.exists(labels) else ""
    check = rows_of(os.path.join(work, "output-check.csv"))
    ran = verapdf()
    if not ran:
        print("  skip  veraPDF not found (set VERAPDF); the PDFs' claims aren't judged")
    write(os.path.join(work, "conversion.yaml"),
          "targets:\n  pdf:\n    format: pdf\n    slides:\n      aspect_ratio: wide\n")
    wrong = convert(work)
    checks = [
        ("slides.aspect_ratio is every deck's shape, and PDF/UA-1 is built",
         lambda: result.returncode == 0 and abs(shape_of(built) - 1.25) < 0.01
         and pikepdf.open(built).pdf_version == "1.7"),
        ("an aspect ratio that isn't one stops the run, saying what it takes",
         lambda: wrong.returncode != 0 and "slides.aspect_ratio is 'wide'" in wrong.stderr),
        ("in PDF/UA-1 a footnote's mark is tied to its note too, though no link, and a"
         " section's footnote's link has its text for /Contents",
         lambda: footnote_ties(agenda) == (1, 0, 1, 0, 0)
         and link_contents(agenda).get("https://example.org/unit") == "per unit"),
        ("with the captions' repair off, the artifact LaTeX makes of a table's repeated"
         " head stays, and its footnote's mark with it, tied as the other is",
         lambda: unrepaired.returncode == 0
         and artifacts_in_tables(captioned) == 1
         and footnote_ties(captioned)[1:] == (0, 0, 0, 0)),
        ("decks with no slide shown in steps have no note of links taken out",
         lambda: "on the earlier steps" not in result.stderr + unrepaired.stderr),
        ("with picture_paths off, a deck's picture in its LaTeX is drawn with LaTeX's own "
         "lcircle10 glyphs, as before pict2e drew picture mode in every PDF",
         lambda: os.path.exists(pictured) and "LCIRCLE10" in pdftext.base_fonts(pictured)),
        # pdf-target.lua sets them with \OERNoCaptionLabel: a figure's
        # caption through LaTeX's caption sockets, a long table's through
        # an empty \LTcaptype, ltx-talk loading no caption package.
        ("a figure's and a table's caption that carry their own label lose ltx-talk's "
         "label, and so does an unnumbered figure's, where the others keep it",
         lambda: "Figure1.1Abluesquare" in labels_text
         and "Figure:Figure1.1" not in labels_text
         and "Table2.1Rates" in labels_text and "Table:Table2.1" not in labels_text
         and "Abluesquarethedeckleavesunnumbered" in labels_text
         and "Figure:Abluesquarethedeckleaves" not in labels_text
         and "Figure:Abluesquarewithnolabel" in labels_text
         and "Table:Countsbyyear" in labels_text),
        ("and the words are the captions settings', as for a book's PDF",
         lambda: "Exhibit3Abluesquare" in labels_text
         and "Figure:Exhibit3" not in labels_text),
        ("such a figure's Caption holds its paragraph and no Lbl",
         lambda: figure_captions(labels) == [["P"], ["P"], ["Lbl", "P"], ["P"]]),
    ]
    if ran:
        checks.insert(1, ("veraPDF passes them as PDF/UA-1: the footnote's mark no link, "
                          "the agenda's heading an H1",
                          lambda: not [r for r in check if r[1].startswith("verapdf")]))
        checks.append(("and veraPDF passes that PDF as PDF/UA-2",
                       lambda: not [r for r in plain_check if r[1].startswith("verapdf")]))
    return checks


# What a newer ltx-talk or LaTeX would change, as the template's checks of
# their code see it: the copy of ltx-talk's code for a slide's title, and
# for a block, made unlike the class's, and LaTeX's footnote variable the
# template looks for named as one that doesn't exist.
FALLBACKS = [("        tag      = frametitle ,\n", "        tag      = frametitle-changed ,\n"),
             ("\\normalfont \\large \\bfseries", "\\normalfont \\Large \\bfseries"),
             ("{ \\bool_if_exist_p:N \\l__fnote_autodetect_bool }",
              "{ \\bool_if_exist_p:N \\l__fnote_autodetect_changed_bool }")]
# The agenda, with a footnote in a slide's title, which LaTeX can't tie to
# a text set before it, and a heading in a quotation.
FALLBACK = AGENDA.replace("## The Rule\n\nProduce where they meet.\n",
                          "## The Rule[^r]\n\nProduce where they meet.\n\n"
                          "> ### Quoted\n>\n> Its text.\n") + "\n[^r]: The rule's note.\n"


def case_fallbacks(work):
    """A deck's PDF where ltx-talk's code for a slide's title and a block,
    and LaTeX's footnote code, aren't the code the template knows: each
    falls back to what the class and LaTeX do, the PDF still passes, and
    the run says so. A copy of bin and lib, its template changed."""
    problem = pdf_ready()
    if problem:
        print(f"  skip  {problem}; the template's fallbacks aren't checked")
        return []
    copy = os.path.join(work, "copy")
    shutil.copytree(BIN, os.path.join(copy, "bin"))
    shutil.copytree(os.path.join(ROOT, "lib"), os.path.join(copy, "lib"))
    template = os.path.join(copy, "bin", "ltx-talk.latex")
    with open(template, encoding="utf-8") as fh:
        text = fh.read()
    found = [text.count(old) for old, _ in FALLBACKS]
    for old, new in FALLBACKS:
        text = text.replace(old, new)
    write(template, text)
    decks_dir = folder(os.path.join(work, "decks"), "targets:\n  pdf:\n    format: pdf\n",
                       decks_given={"agenda.md": FALLBACK})
    result = subprocess.run([sys.executable, os.path.join(copy, "bin", "convert.py"), "--quiet"],
                            cwd=decks_dir, capture_output=True, text=True,
                            stdin=subprocess.DEVNULL)
    out = result.stderr
    agenda = os.path.join(decks_dir, "pdf", "agenda.pdf")
    check = rows_of(os.path.join(decks_dir, "output-check.csv"))
    ran = verapdf()
    levels = lambda path: [h[0] for h in heading_elements(path)]  # noqa: E731
    checks = [
        ("each of the template's checks found the code it changes",
         lambda: FALLBACK != AGENDA + "\n[^r]: The rule's note.\n" and found == [1, 1, 1]),
        ("the PDF is built, and the run warns of each fallback, and of the mark LaTeX"
         " couldn't tie",
         lambda: result.returncode == 0 and os.path.exists(agenda)
         and "every slide's title is tagged at one level" in out
         and "a block's title is a paragraph, not a heading" in out
         and "has a mark that is a number, not a link to its note" in out
         and "1 footnote mark(s) in 1 deck PDF(s) (agenda) aren't tied" in out),
        ("every slide's title at one level, H2 below the sections, the block's a"
         " paragraph, its level not set in it, and a heading in a quotation one below the"
         " slides'",
         lambda: levels(agenda) == [2, 1, 2, 1, 2, 3]
         and re.search(r"(?<!\d)A Block", text_of(agenda))),
        ("a section's footnote still after its slide's heading, and no mark a link,"
         " though LaTeX ties a mark set before its text, not the slide's title's",
         lambda: within(agenda, "/FENote", r"/H[1-6]") == []
         and footnote_ties(agenda) == (2, 1, 2, 0, 0) and "1Marginal revenue" in text_of(agenda)),
    ]
    if ran:
        checks.append(("veraPDF still finds nothing to fail",
                       lambda: not [r for r in check if r[1].startswith("verapdf")]))
    return checks


def case_no_latex(work):
    """A deck's PDF with no LuaLaTeX on the path: the run stops, saying so."""
    tools = tools_without(work)
    decks_dir = folder(os.path.join(work, "decks"), "targets:\n  pdf:\n    format: pdf\n",
                       decks_given={"one.md": UNTITLED})
    result = convert(decks_dir, "--quick", env=dict(os.environ, PATH=tools))
    return [
        ("without LuaLaTeX, a deck's PDF stops the run, saying what it needs",
         lambda: result.returncode != 0
         and "lualatex is not on the path, and a deck's PDF is built with it" in result.stderr),
    ]


def tools_without(work, keep=("pandoc", "file")):
    """A folder of the programs keep names and Python, for PATH: what a
    run needs before LaTeX, and nothing else. Python is a script that runs
    this one: a venv's python run through a link starts without the venv's
    packages."""
    tools = os.path.join(work, "bin")
    os.makedirs(tools)
    for program in keep:
        found = shutil.which(program)
        if found:
            os.symlink(found, os.path.join(tools, program))
    with open(os.path.join(tools, "python3"), "w") as fh:
        fh.write("#!/bin/sh\nexec %s \"$@\"\n" % shlex.quote(sys.executable))
    os.chmod(os.path.join(tools, "python3"), 0o755)
    return tools


def case_svg(work):
    """An SVG a deck's PDF can't show: without rsvg-convert the run stops
    before LaTeX, and one rsvg-convert can't read stops its deck's PDF."""
    broken = "---\ntitle: Broken\n---\n\n# A Picture\n\n![A bar](img/broken.svg)\n"
    decks_dir = folder(os.path.join(work, "decks"), "targets:\n  pdf:\n    format: pdf\n",
                       decks_given={"broken.md": broken})
    write(os.path.join(decks_dir, "img", "broken.svg"), "<svg xmlns='http://www.w3.org/2000/svg'")
    without = convert(decks_dir, "--quick", env=dict(os.environ, PATH=tools_without(work)))
    checks = [
        ("without rsvg-convert, a deck's SVG stops the run before LaTeX, saying what it needs",
         lambda: without.returncode != 0
         and "1 deck(s) show SVG images (img/broken.svg in broken first)" in without.stderr
         and "librsvg2-bin" in without.stderr),
    ]
    if shutil.which("rsvg-convert") and not pdf_ready():
        broke = convert(decks_dir, "--quick")
        checks.append(
            ("an SVG rsvg-convert can't read stops its deck's PDF, saying which and why",
             lambda: broke.returncode != 0
             and "broken's PDF wasn't built: LaTeX can't show an SVG image, and img/broken.svg "
                 "couldn't be made a PDF (rsvg-convert:" in broke.stderr))
        # Before LaTeX, which would only stop on \includesvg.
        intermediate = os.path.join(decks_dir, "broken.filtered.json")
        direct = decks.build_pdf(
            intermediate, decks_dir, os.path.join(work, "broken.pdf"),
            template=os.path.join(BIN, "ltx-talk.latex"),
            filters=[os.path.join(BIN, name) for name in
                     ("target-blocks.lua", "deck-pdf.lua", "pdf-target.lua")],
            language="en-US") if os.path.exists(intermediate) else None
        checks.append(
            ("and stops it before Pandoc and LaTeX are run",
             lambda: direct is not None and not direct["ok"] and direct["talkify"] is None
             and direct["svg_failed"] and direct["svg_failed"][0][0] == "img/broken.svg"))
    return checks


def case_timeout(work):
    """LaTeX that doesn't finish is stopped: build_pdf with an engine that
    only sleeps, and a limit of a second."""
    os.makedirs(work)
    source, intermediate = os.path.join(work, "deck.md"), os.path.join(work, "deck.json")
    write(source, "# Slide\n\nText.\n")
    subprocess.run(["pandoc", source, "-t", "json", "-o", intermediate], check=True)
    with open(intermediate, encoding="utf-8") as fh:
        doc = json.load(fh)
    doc["meta"][decks.LEVEL_KEY] = {"t": "MetaString", "c": "1"}
    write(intermediate, json.dumps(doc))
    engine = os.path.join(work, "sleeper")
    write(engine, "#!/bin/sh\nexec sleep 30\n")
    os.chmod(engine, 0o755)
    saved = decks.latexbuild.ENGINE, decks.LATEX_TIMEOUT
    decks.latexbuild.ENGINE, decks.LATEX_TIMEOUT = engine, 1
    try:
        result = decks.build_pdf(
            intermediate, work, os.path.join(work, "deck.pdf"),
            template=os.path.join(BIN, "ltx-talk.latex"),
            filters=[os.path.join(BIN, name) for name in
                     ("target-blocks.lua", "pdf-target.lua", "deck-pdf.lua")],
            language="en-US", env=dict(os.environ, TARGET_NAME="pdf", TITLE_BLOCK="True"))
    finally:
        decks.latexbuild.ENGINE, decks.LATEX_TIMEOUT = saved
    return [
        ("LaTeX that doesn't finish is stopped, and the result says so",
         lambda: result["timeout"] and not result["ok"]
         and not os.path.exists(os.path.join(work, "deck.pdf"))),
    ]


def case_unsettled(work):
    """Cross-references that never settle: a deck built through a LuaLaTeX
    that runs the real one and then changes the .aux, as a deck whose
    labels move each run would."""
    real = shutil.which("lualatex")
    if not real or pdf_ready():
        print(f"  skip  {pdf_ready() or 'lualatex not found'}; LaTeX's runs aren't checked")
        return []
    decks_dir = folder(os.path.join(work, "decks"), "targets:\n  pdf:\n    format: pdf\n",
                       decks_given={"moving.md": "---\ntitle: Moving\n---\n\n# Slide\n\nText.\n"})
    tools, runs = os.path.join(work, "tools"), os.path.join(work, "runs.log")
    write(os.path.join(tools, "lualatex"),
          f"#!/bin/sh\n{shlex.quote(real)} \"$@\"\nstatus=$?\n"
          "if [ -f deck.aux ]; then echo \"% run $(date +%s%N)\" >> deck.aux; "
          f"echo run >> {shlex.quote(runs)}; fi\nexit $status\n")
    os.chmod(os.path.join(tools, "lualatex"), 0o755)
    result = convert(decks_dir, "--quick",
                     env=dict(os.environ, PATH=tools + os.pathsep + os.environ["PATH"]))
    return [
        ("LaTeX's cross-references still changing after its last run are warned of, the"
         " deck named, its PDF written",
         lambda: result.returncode == 0 and read(runs).count("run") == 4
         and "WARNING: in 1 deck PDF(s) (moving), LaTeX's cross-references were still "
             "changing after 4 runs of LuaLaTeX" in result.stderr
         and os.path.exists(os.path.join(decks_dir, "pdf", "moving.pdf"))),
    ]


# A slide's table and a slide's formula too wide for it, which LaTeX fits
# to it as it does a book's (latexbuild's FIT_MACROS), and a slide whose
# code is too long for it even at half its size, which wraps.
WIDE_SLIDES = ("---\ntitle: Wide\n---\n\n# A table\n\n"
               + "| " + " | ".join("Column %d" % c for c in range(12)) + " |\n"
               + "|" + "---|" * 12 + "\n"
               + ("| " + " | ".join("%d.%02d" % (c * 37, c) for c in range(12)) + " |\n") * 3
               + "\n# A formula\n\n$$x = "
               + " + ".join("a_{%d} b_{%d} c_{%d}" % (k, k, k) for k in range(16)) + "$$\n"
               + "\n# Code\n\n```python\nCodeslide = \"" + "x" * 100 + "\"\n```\n"
               + "\n# Short code\n\n```python\nShortslide = 1\n```\n"
               + "\n# Long code\n\n```python\nCodewrap = \"" + " ".join(
                   "word%02d" % k for k in range(50)) + "\"\n```\n")

# A section's footnote with code that fits, and a slide with code too wide
# for it, which deck-pdf.lua and pdf-target.lua number apart; and the deck
# again with the slide's code short, where nothing is fitted.
SECTION_CODE = ("---\ntitle: Sections\n---\n\n# A Section[^s]\n\n## Code\n\n```python\n"
                "Slidecode = \"%s\"\n```\n\n[^s]: Its code:\n\n    ```python\n"
                "    Sectionnote = 1\n    ```\n")


def case_wide_slide(work):
    """A table, a formula, and a block of code too wide for their slides,
    fitted to them, and LaTeX's runs settling with them fitted, through a
    LuaLaTeX that notes the folder each run is in: the .aux keeps the fit,
    which had changed it on every run, and a deck with nothing to fit,
    which keeps no count of runs, settles in two runs, as it did before
    fitting. The block of code is too wide for its slide at the text's
    size (a line of 74 characters had fit it, fitted or not), and a slide
    of code that fits it is beside it. And a section's footnote's code
    that fits keeps its size beside a slide's set smaller (SECTION_CODE):
    its fit numbered from 1, as the deck's are, it had the slide's. And a
    slide whose line of code is too long for it even at half its size,
    set at three quarters and wrapped."""
    real = shutil.which("lualatex")
    if not real or pdf_ready():
        print(f"  skip  {pdf_ready() or 'lualatex not found'}; a slide too wide isn't checked")
        return []
    decks_dir = folder(os.path.join(work, "decks"), "targets:\n  pdf:\n    format: pdf\n",
                       decks_given={"wide.md": WIDE_SLIDES,
                                    "plain.md": "---\ntitle: Plain\n---\n\n# Slide\n\nText.\n",
                                    "sections.md": SECTION_CODE % ("x" * 100),
                                    "sectionsshort.md": SECTION_CODE % "x"})
    tools, runs = os.path.join(work, "tools"), os.path.join(work, "runs.log")
    write(os.path.join(tools, "lualatex"),
          f"#!/bin/sh\npwd >> {shlex.quote(runs)}\nexec {shlex.quote(real)} \"$@\"\n")
    os.chmod(os.path.join(tools, "lualatex"), 0o755)
    result = convert(decks_dir, "--quick",
                     env=dict(os.environ, PATH=tools + os.pathsep + os.environ["PATH"]))
    path = os.path.join(decks_dir, "pdf", "wide.pdf")

    def counts():
        """How many runs each deck's LaTeX had, fewest first, not counting
        the run that tries LaTeX first, in a folder of its own."""
        folders = [f for f in (read(runs).splitlines() if os.path.exists(runs) else [])
                   if os.path.basename(f).startswith("deck-pdf")]
        return sorted(folders.count(f) for f in set(folders))

    def inside(slide, least):
        """Each of the slide's glyphs, least of them at the least, is a
        quarter inch inside its edges, its last column's or its last term's
        among them."""
        if not os.path.exists(path):
            return False
        with pikepdf.open(path) as pdf:
            width = float(pdf.pages[slide].MediaBox[2])
        boxes = [b for b in pdftext.glyph_boxes(path) if b[0] == slide]
        return len(boxes) >= least and all(18 <= left and right <= width - 18
                                           for _, _, left, right, _ in boxes)

    def rows(slide):
        """The wide deck's slide's lines of text: its baselines."""
        if not os.path.exists(path):
            return []
        return sorted({round(b[1], 1) for b in pdftext.glyph_boxes(path) if b[0] == slide})

    def advance(deck, word):
        """How wide a glyph of the line of code that opens with word is, on
        average, in the deck's PDF; 0 where there's none."""
        pdf = os.path.join(decks_dir, "pdf", deck + ".pdf")
        if not os.path.exists(pdf):
            return 0
        lines = {}
        for page, baseline, left, right, char in pdftext.glyph_boxes(pdf):
            lines.setdefault((page, baseline), []).append((left, right, char))
        for glyphs in lines.values():
            if "".join(g[2] for g in glyphs).startswith(word):
                return (glyphs[-1][1] - glyphs[0][0]) / len(glyphs)
        return 0
    return [
        ("a slide's table, formula, and block of code too wide for it are set smaller to "
         "fit it, a quarter inch inside its edges, as a book's are, the code smaller than a "
         "slide's code that fits",
         lambda: inside(1, 200) and inside(2, 100) and inside(3, 100)
         and 0 < advance("wide", "Codeslide") < 0.9 * advance("wide", "Shortslide")),
        ("a slide's line of code too long for it even at half its size is set at three "
         "quarters of its size and wrapped, every part a quarter inch inside the slide's "
         "edges",
         lambda: inside(5, 300) and len(rows(5)) >= 3
         and abs(advance("wide", "Codewrap") - 0.75 * advance("wide", "Shortslide")) < 0.05),
        ("a section's footnote's code that fits is set at its size beside a slide's code set "
         "smaller, as wide a character as where the slide's code fits too",
         lambda: 0 < advance("sections", "Slidecode") < 0.9 * advance("sectionsshort", "Slidecode")
         and abs(advance("sections", "Sectionnote") - advance("sectionsshort", "Sectionnote"))
         < 0.05),
        ("and LaTeX's runs settle with them fitted, and in two runs for a deck with "
         "nothing to fit",
         lambda: result.returncode == 0 and "still changing" not in result.stderr
         and len(counts()) == 4 and counts()[0] == 2),
    ]


# --------------------------------------------------------------------------
# a deck's PowerPoint file
# --------------------------------------------------------------------------

PPTX = """\
targets:
  slides:
    format: pptx
"""

# What Pandoc's PowerPoint writer does with a deck, as deck-pptx.lua and
# pptxtarget.py put it right: a picture between text, two pictures, a
# table with a header column and a caption before a picture, columns with
# text around them, a paragraph that opens with a picture and links to a
# figure on another slide, bars over letters in text and in a table's
# cell, a caption that isn't the alt text, a decorative picture, more text
# than a slide holds, a long table, a passage in another language, and an
# institute.
SHAPES = """\
---
title: Shapes
author: A. Lecturer
institute: Shepherd University
date: 2026
notes: |
  Welcome. The plan is at [the site](https://example.org/plan).
---

# Picture and Text

Before the picture.

![A rising line](img/plot.png)

After the picture.

# Two Pictures

![First chart](img/plot.png){#fig-first}

![A second chart](img/plot.png){alt="The second chart, described"}

# Table Then Picture

::: matrix
| Good | Price |
|------|------:|
| Apples | 1 |
| Pears | 2 |

: Prices of fruit
:::

![After the table](img/plot.png)

# Columns

Before the columns.

:::: columns
::: column
Left words.
:::
::: column
Right words.
:::
::::

After the columns.

# Opening Picture

![Inline alt](img/plot.png) and words after it, see [the first chart](#fig-first).

# Bars

$\\bar{x} = \\frac{1}{n}\\sum x_i$ and $\\hat{y}$.

| Statistic | Value |
|-----------|------:|
| $\\bar{x}$ | 3 |

# Decorative

![](img/plot.png){.decorative}

# Dense

""" + "".join("- Item %d says a good deal more than a slide's item should, at length.\n" % n
              for n in range(1, 21)) + """
# Long Table

| Price | Quantity |
|------:|---------:|
""" + "".join("| %d | %d |\n" % (n, 40 - n) for n in range(1, 13)) + """
: A long demand schedule

# Too Long

| Price | Quantity |
|------:|---------:|
""" + "".join("| %d | %d |\n" % (n, 40 - n) for n in range(1, 31)) + """
# Table and Text

Some words before the table.

| Price | Quantity |
|------:|---------:|
""" + "".join("| %d | %d |\n" % (n, 40 - n) for n in range(1, 9)) + """
Words after the table.

# Formatted Table

| **Bold** *italic* | Value |
|-------------------|------:|
| [a link](https://example.org) `code` | 1 |

# Steps

| Step | Done |
|------|-----:|
| One | 1 |

: Steps taken

::: incremental
- First step
- Second step
:::

# More Steps

Before the steps.

| Step | Done |
|------|-----:|
| Two | 2 |

::: incremental
- Third step
- Fourth step
:::

# Figure Pair

::: {#fig-pair .figure}
![Left chart](img/plot.png)

![Right chart](img/plot.png)

::: caption
Two charts side by side.
:::
:::

# Div Target

::: {#box}
Words in a box.
:::

# Boxed Picture

::: {#boxed}
![Boxed chart](img/plot.png) and words after it.
:::

# Div Link

See [the box](#box), [the pair](#fig-pair), and [the boxed chart](#boxed).

# Private Notes

Shown words.

::: {.notes .private}
Only for the speaker.
:::

# Listed Notes

Words shown.

::: notes
Two points:

- First
    - Under it
- Second

1. Numbered
:::

# Notes First

::: notes
Say this first.
:::

:::: columns
::: column
Left.
:::
::: column
Right.
:::
::::

# Display

$$E = mc^2$$

The mean:

$$\\bar{x} = \\frac{1}{n}\\sum x_i$$

and the rest.

In a line
$$y = mx + b$$
and after.

# Display Kept

After a break\\
$$a = b$$

\\vspace{1em}

$$c = d$$

\\medskip

then this.

&nbsp;

$$f = g$$

# Space

First words.

\\bigskip

Second words.

\\vspace{-1em}

Third words \\vspace{1cm}

Fourth words.

\\addvspace{5mm}

\\vfill

Fifth words.

# Space Again

Words before.

\\vspace*{0.5\\baselineskip}

- An item

  \\smallskip

\\vskip 6pt plus 2pt

## A Heading

`\\vspace{3ex}`{=latex} Last words.

# Space Top

\\vspace{2em}

Pushed down.

Not pushed.

\\vspace{1em}

# Languages

[Bonjour]{lang=fr} and more.

::: notes
Say hello in French.
:::

# Display After a List

- A point
  - A smaller point

$$p = q$$

# Display Top

\\vspace{1em}

$$z = 1$$

After it.

# Linked Notes

Words shown.

::: notes
See [the *source*](https://example.org/data "Where the data & more are") and
<https://example.org/two?a=1&b=2>, then [the first](#listed-notes), [this
one](#linked-notes), and [`the code`](https://example.org/data).

- A point at <someone@example.org>
:::

# Listed Beside a Picture

Words before the list.

- A point
    - A smaller point

![A rising line](img/plot.png)

# Titled Links

See [the data](https://example.org/data "Where the data & more are"), [*the* plan](https://example.org/plan "The plan"), [no title](https://example.org/none), and [the list](#listed-beside-a-picture "Back to the list").

# Code Link

See [`the code`](https://example.org/code).

# Notes Math

Words shown.

::: notes
The line $\\hat{y}=a+bx$, the average $\\bar{x}_{n}$, and $\\frac{a}{b}$.
:::
"""


def pptx_parts(path):
    """A PowerPoint file's parts, its XML as text."""
    import zipfile
    with zipfile.ZipFile(path) as z:
        return {name: z.read(name).decode("utf-8", "replace")
                if name.endswith((".xml", ".rels")) else z.read(name) for name in z.namelist()}


def pptx_slides(parts):
    """Each slide's XML, in order."""
    names = [n for n in parts if re.match(r"ppt/slides/slide\d+\.xml$", n)]
    return [parts[n] for n in sorted(names, key=lambda n: int(re.search(r"(\d+)\.xml$", n)[1]))]


def pptx_deck(path):
    import pptxparse
    return pptxparse.read(path)


def pptx_findings(path):
    import pptxcheck
    return [(f.where, f.check) for f in pptxcheck.check(pptx_deck(path), kind="pptx")]


def slide_titled(deck, title):
    return next((s for s in deck.slides if s.title == title), None)


def unique_ids(parts):
    """Whether each slide's shapes' ids are their own, mc:Fallback's copies
    aside, which share their Choice's."""
    for xml in pptx_slides(parts):
        xml = re.sub(r"<mc:Fallback>.*?</mc:Fallback>", "", xml, flags=re.S)
        ids = re.findall(r'<p:cNvPr\b[^>]*?\sid="(\d+)"', xml)
        if len(ids) != len(set(ids)) or "0" in ids:
            return False
    return True


def slide_rels(parts, slide):
    return parts.get(slide.part.replace("slides/", "slides/_rels/") + ".rels", "") \
        if slide else ""


def slide_links(parts, slide):
    """The files of the slides a slide links to."""
    return sorted(re.findall(r'relationships/slide" Target="(slide\d+\.xml)"',
                             slide_rels(parts, slide)))


def file_of(slide):
    return slide.part.rsplit("/", 1)[1] if slide else None


# The children of a run's properties in the order ECMA-376's dml-main.xsd
# gives them (CT_TextCharacterProperties), a group's sharing a place.
SCHEMA_ORDER = {name: n for n, names in enumerate((
    ("ln",), ("noFill", "solidFill", "gradFill", "blipFill", "pattFill", "grpFill"),
    ("effectLst", "effectDag"), ("highlight",), ("uLnTx", "uLn"), ("uFillTx", "uFill"),
    ("latin",), ("ea",), ("cs",), ("sym",), ("hlinkClick",), ("hlinkMouseOver",), ("rtl",),
    ("extLst",))) for name in names}


def properties_in_order(xml):
    """Whether each run's properties in a part hold their children in the
    schema's order."""
    for name, inner in re.findall(r"<a:(rPr|endParaRPr|defRPr)\b[^>]*?(?<!/)>(.*?)</a:\1>",
                                  xml, re.S):
        depth, ranks = 0, []
        for close, tag, end in re.findall(r"<(/?)a:(\w+)\b[^>]*?(/?)>", inner):
            if close:
                depth -= 1
                continue
            if depth == 0:
                ranks.append(SCHEMA_ORDER.get(tag, -1))
            if not end:
                depth += 1
        if ranks != sorted(ranks):
            return False
    return True


def run_tooltips(xml):
    """(text, ScreenTip or None) of each run with a link on a slide."""
    out = []
    for run in re.findall(r"<a:r>.*?</a:r>", xml, re.S):
        click = re.search(r"<a:hlinkClick\b[^>]*>", run)
        if click:
            tip = re.search(r'\stooltip="([^"]*)"', click.group(0))
            out.append(("".join(re.findall(r"<a:t>([^<]*)</a:t>", run)),
                        tip.group(1) if tip else None))
    return out


def paragraph_bullets(xml):
    """(level, bullet, left margin, indent, text) of each paragraph in a
    slide's shapes that aren't its title, the bullet its character or
    None."""
    out = []
    for shape in re.findall(r"<p:sp>.*?</p:sp>", xml, re.S):
        if re.search(r'<p:ph\b[^>]*\stype="(?:title|ctrTitle)"', shape):
            continue
        for paragraph in re.findall(r"<a:p>.*?</a:p>", shape, re.S):
            props = re.search(r"<a:pPr\b([^>]*?)(?:/>|>(.*?)</a:pPr>)", paragraph, re.S)
            attrs, inner = (props.group(1), props.group(2) or "") if props else ("", "")
            char = re.search(r'<a:buChar\b[^>]*?\schar="([^"]*)"', inner)

            def value(name):
                found = re.search(r'\s%s="([^"]*)"' % name, attrs)
                return found.group(1) if found else None
            out.append((value("lvl"), char.group(1) if char else None, value("marL"),
                        value("indent"), "".join(re.findall(r"<a:t>([^<]*)</a:t>", paragraph))))
    return out


def notes_of(parts, slide):
    """The XML of a slide's notes."""
    found = re.search(r'Target="\.\./notesSlides/(notesSlide\d+\.xml)"', slide_rels(parts, slide))
    return parts.get("ppt/notesSlides/" + found.group(1), "") if found else ""


def notes_links(xml):
    """(words, relationship id, ScreenTip) of each run of a notes slide's
    text that is a link."""
    out = []
    for rpr, words in re.findall(r"<a:r>(<a:rPr\b[^>]*?(?:/>|>.*?</a:rPr>))<a:t>([^<]*)</a:t>",
                                 xml, re.S):
        click = re.search(r'<a:hlinkClick r:id="([^"]*)"(?: tooltip="([^"]*)")?', rpr)
        if click:
            out.append((words, click.group(1), click.group(2)))
    return out


def unrecorded_link():
    """pptxtarget's notes slide, a link's marks around words with no link
    recorded for them, its relationships, and the links it counts."""
    import pptxtarget
    counts = {"notes_links": 0}
    xml, rels = pptxtarget.notes_links(
        '<a:p><a:r><a:rPr lang="en"/><a:t>See \ue004\U000f0001the data\ue005.</a:t></a:r></a:p>',
        "<Relationships></Relationships>", [], counts)
    return xml, rels, counts["notes_links"]


# A notes slide as Pandoc's writer writes one from 3.13 on (#11935), its
# color map after its common data.
MAPPED_NOTES = ('<p:notes xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
                '<p:cSld><p:spTree/></p:cSld><p:clrMapOvr><a:masterClrMapping/>'
                '</p:clrMapOvr></p:notes>')
# A notes slide's color map, as pptxtarget writes it, or as the writer
# does, with a space before the empty element's end; and the release
# whose writer writes it.
NOTES_COLOR_MAP = r"<p:clrMapOvr>\s*<a:masterClrMapping\s*/>\s*</p:clrMapOvr>"
WRITER_NOTES_COLORS = (3, 13)


def pandoc_version():
    """The version of the Pandoc on the path, as a tuple of numbers."""
    words = subprocess.run(["pandoc", "--version"], capture_output=True, text=True).stdout.split()
    return tuple(int(p) for p in re.findall(r"\d+", words[1] if len(words) > 1 else "")[:3])


# The Pandoc a deck's PowerPoint file and its presentation need, by the
# name convert.py gives it (PPTX_PANDOC, REVEALJS_PANDOC), read from it
# once, so the two can't drift apart.
NEEDED = {}


def too_old(name, what):
    """Why the Pandoc on the path can't write what, a deck's PowerPoint
    file or its presentation, or None. convert.py stops a pptx target on a
    Pandoc older than PPTX_PANDOC, and a revealjs target on one older than
    REVEALJS_PANDOC; the suite's floor is 3.9. A machine to set up, not the
    code failing, so the checks of what those targets write skip, saying
    so, where they'd fail; the rest of a case runs."""
    if not NEEDED:
        import importlib.util
        spec = importlib.util.spec_from_file_location("convert_needs",
                                                      os.path.join(BIN, "convert.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        NEEDED.update(PPTX_PANDOC=module.PPTX_PANDOC, REVEALJS_PANDOC=module.REVEALJS_PANDOC)
    if pandoc_version() >= NEEDED[name]:
        return None
    found = subprocess.run(["pandoc", "--version"], capture_output=True,
                           text=True).stdout.split()[1]
    return (f"Pandoc {found} is too old for {what}, which needs "
            + ".".join(map(str, NEEDED[name])) + " or later")


def mapped_notes():
    """pptxtarget's notes slide that has a color map already, and the
    notes slides it counts as given one."""
    import pptxtarget
    counts = {"notes_colors": 0}
    return pptxtarget.notes_colors(MAPPED_NOTES, counts), counts["notes_colors"]


def notes_rels(parts, slide):
    """The relationships of a slide's notes slide."""
    found = re.search(r'Target="\.\./notesSlides/(notesSlide\d+\.xml)"', slide_rels(parts, slide))
    return parts.get("ppt/notesSlides/_rels/%s.rels" % found.group(1), "") if found else ""


def rel_target(rels, rid):
    """The target of a part's relationship rid, if it's an external one."""
    found = re.search(r'<Relationship Id="%s"[^>]*?Target="([^"]*)"[^>]*TargetMode="External"'
                      % re.escape(rid), rels)
    return found.group(1) if found else None


def notes_list(xml):
    """(text, level, first line's indent, bullet) of each paragraph of
    a notes slide's text holding text, the bullet its character, "number",
    or "none"."""
    out = []
    for p in re.findall(r"<a:p>(.*?)</a:p>", xml, re.S):
        words = "".join(re.findall(r"<a:t>([^<]*)</a:t>", p))
        props = re.search(r"<a:pPr\b([^>]*?)(?:/>|>(.*?)</a:pPr>)", p, re.S)
        if not words or props is None:
            continue
        inner = props.group(2) or ""
        char = re.search(r'<a:buChar char="([^"]*)"', inner)
        out.append((words, re.search(r'lvl="(\d+)"', props.group(1)).group(1),
                    (re.search(r'indent="(-?\d+)"', props.group(1)) or [None, None])[1]
                    if char or "buAutoNum" in inner else None,
                    char.group(1) if char else "number" if "buAutoNum" in inner else "none"))
    return out


def shape_id(xml, words):
    """The id of the shape on a slide whose text holds words."""
    for piece in re.findall(r"<p:sp>.*?</p:sp>", xml, re.S):
        if words in piece:
            return re.search(r'<p:cNvPr\b[^>]*?\sid="(\d+)"', piece).group(1)
    return None


def animated(xml):
    """The ids of the shapes a slide's animation names, in its steps and in
    its build list."""
    return (sorted(set(re.findall(r'<p:spTgt spid="(\d+)"', xml))),
            sorted(set(re.findall(r'<p:bldP\b[^>]*?\sspid="(\d+)"', xml))))


def table_ends_above(xml, base):
    """Whether a slide's table, set smaller than base, the master's size
    for its text, ends above the shape the writer stacks under it, as
    pptxtarget reckons a table's height."""
    import pptxorder
    import pptxtarget
    tree = pptxorder.TREE.search(xml)
    close = xml.find("</p:spTree>", tree.end())
    pieces = [(xml[a:b], name) for a, b, name in pptxorder.children(xml, tree.end(), close)]
    frame = next((p for p, name in pieces if name == "p:graphicFrame"), None)
    if frame is None:
        return False
    top = pptxtarget._place(frame)[1]
    below = [place[1] for place in (pptxtarget._place(p) for p, name in pieces if name == "p:sp")
             if place and place[1] > top]
    sizes = set(re.findall(r'<a:rPr[^>]*?\ssz="(\d+)"', frame))
    if not below or len(sizes) != 1:
        return False
    size = int(sizes.pop()) / 100
    return size < base and top + pptxtarget.table_height(frame, size) <= min(below)


def master_sizes(parts):
    """The points the master sets a title, a body's first level, and other
    text in."""
    import pptxtarget
    styles = pptxtarget.text_styles(parts["ppt/slideMasters/slideMaster1.xml"])
    return tuple(styles[key][0][0] for key in ("title", "body", "other"))


def display_spaces(xml):
    """For each paragraph of a slide's text but its title's: whether it
    holds a display equation, the space before and after it it's given
    itself (spcPct values, or None), and its words, if it has any. A
    shape's fallback, its equations as text, is left out."""
    out = []
    xml = re.sub(r"<mc:Fallback>.*?</mc:Fallback>", "", xml, flags=re.S)
    for shape in re.findall(r"<p:sp\b[^>]*>(.*?)</p:sp>", xml, re.S):
        if re.search(r'<p:ph\b[^>]*type="(?:title|ctrTitle)"', shape):
            continue
        for body in re.findall(r"<p:txBody>(.*?)</p:txBody>", shape, re.S):
            for paragraph in re.findall(r"<a:p>(.*?)</a:p>", body, re.S):
                spaces = [re.search(r'<a:pPr\b[^>]*>(?:(?!</a:pPr>).)*?<a:%s>'
                                    r'<a:spcPct val="(\d+)"' % element, paragraph, re.S)
                          for element in ("spcBef", "spcAft")]
                words = "".join(re.findall(r"<a:t>([^<]*)</a:t>",
                                           re.sub(r"<a14:m>.*?</a14:m>", "", paragraph,
                                                  flags=re.S)))
                out.append(("<m:oMathPara" in paragraph,)
                           + tuple(s.group(1) if s else None for s in spaces) + (words.strip(),))
    return out


def text_height(*paragraphs, respected=False, top=None):
    """pptxtarget's estimate of a text box's height holding paragraphs
    (what each <a:p> holds), at 24 points with a fifth of a line before
    each, as Pandoc's master has its body text; respected, the box told to
    respect its first paragraph's space before and its last one's after;
    top, its top inset."""
    import pptxtarget
    return pptxtarget.body_height("<p:sp><p:txBody><a:bodyPr%s%s/>%s</p:txBody></p:sp>" % (
        ' spcFirstLastPara="1"' if respected else "", ' tIns="%d"' % top if top else "",
        "".join("<a:p>%s</a:p>" % p for p in paragraphs)), {0: (24, 0, 0.2)}, 8000000)


def inset_of(head, layout, master):
    """pptxtarget's inset a shape takes from its placeholder, head its XML
    before its text body, layout and master the XML of a layout's and a
    master's placeholders."""
    import pptxtarget
    return pptxtarget.inherited_inset(head, pptxtarget.placeholder_insets(layout),
                                      pptxtarget.placeholder_insets(master))


INSET_LAYOUT = ('<p:sp><p:nvSpPr><p:nvPr><p:ph idx="13"/></p:nvPr></p:nvSpPr>'
                '<p:txBody><a:bodyPr tIns="1000"/></p:txBody></p:sp>'
                '<p:sp><p:nvSpPr><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>'
                '<p:txBody><a:bodyPr anchor="b"/></p:txBody></p:sp>')
INSET_MASTER = ('<p:sp><p:nvSpPr><p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr>'
                '<p:txBody><a:bodyPr tIns="2000"/></p:txBody></p:sp>'
                '<p:sp><p:nvSpPr><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>'
                '<p:txBody><a:bodyPr tIns="3000"/></p:txBody></p:sp>')


def spaced_after(paragraph):
    """A paragraph, <a:p>…</a:p> or <a:p/>, given a quarter of a line's
    space after it by pptxtarget."""
    import pptxtarget
    return pptxtarget._whole(paragraph, lambda held: pptxtarget._space_after(held, 25000))


WORDS = '<a:pPr/><a:r><a:rPr lang="en"/><a:t>Words</a:t></a:r>'
SPACED_WORDS = ('<a:pPr><a:spcBef><a:spcPct val="50000"/></a:spcBef></a:pPr>'
                '<a:r><a:rPr lang="en"/><a:t>Words</a:t></a:r>')
WORDS_SPACED = ('<a:pPr><a:spcAft><a:spcPct val="50000"/></a:spcAft></a:pPr>'
                '<a:r><a:rPr lang="en"/><a:t>Words</a:t></a:r>')
FLAT_DISPLAY = ('<a:pPr/><a14:m><m:oMathPara><m:oMath><m:r><m:t>x</m:t></m:r></m:oMath>'
                '</m:oMathPara></a14:m>')
TALL_DISPLAY = ('<a:pPr/><a14:m><m:oMathPara><m:oMath><m:f><m:num><m:r><m:t>1</m:t></m:r></m:num>'
                '<m:den><m:r><m:t>n</m:t></m:r></m:den></m:f></m:oMath></m:oMathPara></a14:m>')


def case_pptx(work):
    unready = too_old("PPTX_PANDOC", "a deck's PowerPoint file")
    if unready:
        print(f"  skip  {unready}; a deck's PowerPoint file isn't checked")
        return []
    work = folder(work, PPTX, decks_given={"Flat Deck.md": FLAT, "sectioned.md": SECTIONED,
                                           "untitled.md": UNTITLED, "shapes.md": SHAPES})
    write(os.path.join(work, "image-alt.csv"), "Image,Alt\nimg/chart,A line rising to the right\n")
    png(os.path.join(work, "img", "plot.png"), 200, 90, 40)
    write(os.path.join(work, "project.yaml"),
          "project:\n  identifier: org.example.decks\n  title: The Decks\n"
          "  language: de-DE\n  kind: slides\n")
    result = convert(work, "--quick")
    out = result.stderr
    where = os.path.join(work, "slides")
    flat, sectioned = os.path.join(where, "Flat-Deck.pptx"), os.path.join(where, "sectioned.pptx")
    shapes, untitled = os.path.join(where, "shapes.pptx"), os.path.join(where, "untitled.pptx")
    if result.returncode or not os.path.exists(shapes):
        return [("the pptx target writes a PowerPoint file of each deck",
                 lambda: False and print(out[-2000:]))]
    fp, sp, hp = pptx_parts(flat), pptx_parts(sectioned), pptx_parts(shapes)
    fd, sd, hd = pptx_deck(flat), pptx_deck(sectioned), pptx_deck(shapes)
    every = "".join(x for p in (fp, sp, hp) for x in p.values() if isinstance(x, str))
    chart = slide_titled(fd, "A Chart")
    market = slide_titled(fd, "Market Demand")
    bars = slide_titled(hd, "Bars")
    bars_xml = hp[bars.part] if bars else ""
    fruit = slide_titled(hd, "Table Then Picture")
    fruit_xml = hp[fruit.part] if fruit else ""
    long_table = slide_titled(hd, "Long Table")
    too_long = slide_titled(hd, "Too Long")
    dense = slide_titled(hd, "Dense")
    opening = slide_titled(hd, "Opening Picture (2)")
    first = slide_titled(hd, "Two Pictures")
    formatted = slide_titled(hd, "Formatted Table")
    formatted_xml = hp[formatted.part] if formatted else ""
    steps = slide_titled(hd, "Steps")
    steps_xml = hp[steps.part] if steps else ""
    more = slide_titled(hd, "More Steps")
    more_xml = hp[more.part] if more else ""
    stacked = slide_titled(hd, "Table and Text")
    pair = slide_titled(hd, "Figure Pair (2)")
    private = slide_titled(hd, "Private Notes")
    listed = slide_titled(hd, "Listed Notes")
    linked_notes = slide_titled(hd, "Linked Notes")
    linked_xml = notes_of(hp, linked_notes) if linked_notes else ""
    linked_rels = notes_rels(hp, linked_notes) if linked_notes else ""
    marks = [n for n, x in hp.items() if isinstance(x, str)
             and re.search("[\ue004\ue005\U000f0000-\U000fffff]", x)]
    notes_first = slide_titled(hd, "Notes First")
    display = slide_titled(hd, "Display")
    kept = slide_titled(hd, "Display Kept")
    space = slide_titled(hd, "Space")
    space_again = slide_titled(hd, "Space Again")
    space_top = slide_titled(hd, "Space Top")
    after_list = slide_titled(hd, "Display After a List")
    top_math = slide_titled(hd, "Display Top")
    beside = slide_titled(hd, "Listed Beside a Picture")
    titled = slide_titled(hd, "Titled Links")
    titled_xml = hp[titled.part] if titled else ""
    titled_rels = slide_rels(hp, titled)
    code_link = slide_titled(hd, "Code Link")
    notes_math = slide_titled(hd, "Notes Math")
    notes_math_text = "".join(re.findall(r"<a:t>([^<]*)</a:t>", notes_of(hp, notes_math))) \
        if notes_math else ""
    every_notes = [x for p in (fp, sp, hp) for n, x in p.items()
                   if re.match(r"ppt/notesSlides/notesSlide\d+\.xml$", n)]
    every_slides = [x for p in (fp, sp, hp) for x in pptx_slides(p)]
    code = slide_titled(sd, "Some Code")

    def number(slide):
        return hd.slides.index(slide) + 1 if slide in hd.slides else None
    overflow = re.search(r"too much for its slide even set small.*?\(shapes slide\(s\) ([\d, ]+)\)",
                         out, re.S)
    checks = [
        ("the pptx target writes a PowerPoint file of each deck, and says how",
         lambda: result.returncode == 0 and "Wrote 4 PowerPoint file(s)" in out
         and "through Pandoc's PowerPoint writer" in out),
        ("the output check reads each, and finds only the slide the deck gives no title",
         lambda: pptx_findings(flat) == [("slide 4", "pptx-slide-no-title")]
         and pptx_findings(shapes) == [] and pptx_findings(sectioned) == []
         and pptx_findings(untitled) == []
         and "pptx-slide-no-title" in read(os.path.join(work, "output-check.csv"))),
        ("a picture's description is its alt text, the sidecar's, not its title and path",
         lambda: chart is not None
         and [s.descr for s in chart.shapes if s.kind == "pic"] == ["A line rising to the right"]
         and "oer-pic" not in every and "img/chart.png" not in every),
        ("a picture's caption is a figure's own, shown and read beside the alt text",
         lambda: any(s.text == "A rising line" and not s.decorative for s in chart.shapes)),
        ("a caption that repeats the alt text is marked decorative, as the page hides it",
         lambda: any(s.text == "A rising line" and s.decorative
                     for s in slide_titled(hd, "Picture and Text").shapes)
         and [s.descr for s in slide_titled(hd, "Picture and Text").shapes
              if s.kind == "pic"] == ["A rising line"]),
        ("a caption that isn't the alt text is shown and read",
         lambda: any(s.kind == "pic" and s.descr == "The second chart, described"
                     for s in slide_titled(hd, "Two Pictures (2)").shapes)
         and any(s.text == "A second chart" and not s.decorative
                 for s in slide_titled(hd, "Two Pictures (2)").shapes)),
        ("an image that isn't a figure shows no caption",
         lambda: [s.kind for s in slide_titled(hd, "Opening Picture").shapes
                  if not s.is_title] == ["pic"]),
        ("a decorative picture has PowerPoint's mark and no description",
         lambda: [(s.kind, s.decorative, s.descr) for s in slide_titled(hd, "Decorative").shapes
                  if not s.is_title] == [("pic", True, None)]),
        ("each shape's id is its own on its slide", lambda: all(map(unique_ids, (fp, sp, hp)))),
        ("a table's marker is taken out, its caption above it and read first",
         lambda: "\ue000" not in every and market is not None
         and [s.kind for s in market.shapes if not s.is_title] == ["sp", "graphicFrame"]
         and market.shapes[1].text == "Demand at each price"
         and market.shapes[1].box.y + market.shapes[1].box.cy <= market.shapes[2].box.y),
        ("a table's header column is PowerPoint's First Column, its header row too",
         lambda: re.search(r'<a:tblPr[^>]*firstRow="1"[^>]*firstCol="1"', fruit_xml)
         and not re.search(r'firstCol="1"', hp[slide_titled(hd, "Long Table").part])),
        ("a slide is cut where the writer would put a picture over other content, or "
         "begin a slide with no title, each part titled with its number",
         lambda: [s.title for s in hd.slides][1:12] == [
             "Picture and Text", "Picture and Text (2)", "Two Pictures", "Two Pictures (2)",
             "Table Then Picture", "Table Then Picture (2)", "Columns", "Columns (2)",
             "Columns (3)", "Opening Picture", "Opening Picture (2)"]
         and "1 deck(s) have slides cut into more in the PowerPoint files, 8 slide(s) added "
         "(shapes 8)" in out),
        ("a picture after text is the writer's own layout, the text beside it",
         lambda: slide_titled(hd, "Picture and Text").layout == "Content with Caption"),
        ("a list beside a picture has the bullets the master gives a slide's list, hanging as "
         "a numbered one does, where the writer's layout for text beside a picture gives none; "
         "its other paragraphs keep none, and a list the master's style gives bullets is the "
         "writer's",
         lambda: beside is not None and beside.layout == "Content with Caption"
         and paragraph_bullets(hp[beside.part])[:3] == [
             ("0", None, "0", "0", "Words before the list."),
             ("0", "•", "457200", "-457200", "A point"),
             ("1", "–", "914400", "-457200", "A smaller point")]
         and after_list is not None and paragraph_bullets(hp[after_list.part])[:2] == [
             ("0", None, None, None, "A point"), ("1", None, None, None, "A smaller point")]
         and "2 paragraph(s) of lists on slides given their bullets" in out),
        ("a link's title is its ScreenTip, on every run of the link, one to a slide's too, "
         "which the writer doesn't write; the marks the filter put around its words are gone, "
         "and each relationship the slide keeps is one it names",
         lambda: run_tooltips(titled_xml) == [
             ("the data", "Where the data &amp; more are"), ("the", "The plan"),
             (" plan", "The plan"), ("no title", None), ("the list", "Back to the list")]
         and not re.search("[]", every)
         and all(re.search(r'\sr:id="%s"' % rid, titled_xml)
                 for rid in re.findall(r'<Relationship\b[^>]*?\sId="(rId\d+)"[^>]*?'
                                       r'relationships/(?:hyperlink|slide)"', titled_rels))
         and "3 link(s) on slides given their titles as their ScreenTips" in out),
        ("a formula in the notes is its text, where the writer writes its TeX there, with a "
         "word's spaces and a script as a deck types one; one texmath can't make text is left "
         "its TeX; and the run says how many of each, the plain writer's warning not passed "
         "on as the PowerPoint writer's",
         lambda: "The line \u0177 = a + bx," in unicodedata.normalize("NFC", notes_math_text)
         and "x\u0304_n" in notes_math_text and "\\frac{a}{b}" in notes_math_text
         and "\\hat" not in notes_math_text
         and "2 formula(s) in the speaker notes of 1 deck(s) are text" in out
         and "1 formula(s) in the speaker notes of 1 deck(s) are their TeX" in out
         and "Could not convert TeX math \\frac{a}{b}" not in out),
        ("a run's properties are in the schema's order, a code font before its link, where "
         "the writer puts the link first; and each notes slide has the color map PowerPoint "
         "gives one, once, after its common data, which the writer leaves out before 3.13, "
         "and one that has it is left as it is",
         lambda: code_link is not None and re.search(
             r'<a:rPr\b[^>]*><a:latin typeface="[^"]*"\s*/><a:hlinkClick r:id="rId\d+"\s*/>'
             r"</a:rPr><a:t>the code</a:t>", hp[code_link.part])
         and all(properties_in_order(x) for x in every_slides + every_notes)
         and every_notes and all(len(re.findall(NOTES_COLOR_MAP, x)) == 1
                                 and re.search("</p:cSld>" + NOTES_COLOR_MAP, x)
                                 for x in every_notes)
         and "1 run(s)' properties put in the schema's order" in out
         and (("given the color map" not in out) if pandoc_version() >= WRITER_NOTES_COLORS
              else "%d notes slide(s) given the color map PowerPoint gives one"
              % len(every_notes) in out)
         and mapped_notes() == (MAPPED_NOTES, 0)),
        ("a link to a figure goes to the slide the figure is on",
         lambda: opening is not None and first is not None and re.search(
             r'Target="%s"' % re.escape(first.part.rsplit("/", 1)[1]),
             hp[opening.part.replace("slides/", "slides/_rels/") + ".rels"])),
        ("a bar over a letter is an accent of the macron, as a Word file's is, a hat an "
         "accent of the circumflex",
         lambda: bars_xml.count('<m:chr m:val="\u00af"') == 2 and "\u203e" not in bars_xml
         and "<m:limUpp>" not in bars_xml and 'm:val="\u0302"' in bars_xml),
        ("an equation in a table's cell is declared, and each shape with one has a fallback",
         lambda: not any(problem for _, problem in hd.malformed)
         and bars_xml.count("<mc:Fallback>") == 2
         and "x\u0304" in re.sub(r"<[^>]+>", "", "".join(
             re.findall(r"<mc:Fallback>.*?</mc:Fallback>", bars_xml, re.S)))),
        ("a long table is set smaller to fit its slide, and text too much for its box shrunk",
         lambda: long_table is not None
         and set(re.findall(r'<a:rPr[^>]*?\ssz="(\d+)"', hp[long_table.part])) in (
             {"1600"}, {"1467"}, {"1333"})
         and overflow is not None and str(number(long_table)) not in overflow.group(1).split(", ")
         and "2 table(s) set smaller to fit their slides" in out
         and dense is not None and re.search(r'<a:normAutofit fontScale="\d+"',
                                             hp[dense.part])),
        ("a table too long for its slide even at three quarters of its size is warned of, "
         "by its slide",
         lambda: too_long is not None and overflow is not None
         and overflow.group(1).split(", ") == [str(number(too_long))]
         and set(re.findall(r'<a:rPr[^>]*?\ssz="(\d+)"', hp[too_long.part])) == {"1333"}),
        ("a table stacked over text is set small enough to end above it",
         lambda: stacked is not None and table_ends_above(hp[stacked.part], 18)),
        ("the tables take PowerPoint's Light Style 1 - Accent 1, its text dark on white and "
         "pale blue, not Pandoc's Medium Style 2 - Accent 1, its header white on blue",
         lambda: '<a:tblStyleLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
         'def="{3B4B98B0-60AC-42C2-AFA5-B58CD77FA1E5}"' in hp["ppt/tableStyles.xml"]
         and set(re.findall(r"<a:tableStyleId>([^<]*)</a:tableStyleId>", "".join(
             pptx_slides(hp)))) == {"{3B4B98B0-60AC-42C2-AFA5-B58CD77FA1E5}"}),
        ("a display equation, and the paragraph after it, are set off by space, but where the "
         "deck gives some the writer keeps or an equation opens its slide's text; the deck's raw "
         "\\vspace or \\medskip is added to it, in lines of its PDF; an equation's goes after "
         "the paragraph above it, in that paragraph's lines, as PowerPoint shows no space "
         "before an equation, whose own is none",
         lambda: display is not None and display_spaces(hp[display.part]) == [
             (True, None, None, ""), (False, "50000", "50000", "The mean:"),
             (True, "0", None, ""), (False, "50000", None, "and the rest."),
             (False, None, "50000", "In a line"), (True, "0", None, ""),
             (False, "50000", None, "and after.")]
         and kept is not None and display_spaces(hp[kept.part]) == [
             (False, None, None, "After a break"), (True, None, "130515", ""),
             (True, "0", None, ""), (False, "94118", None, "then this."),
             (False, None, None, ""), (True, None, None, "")]
         and after_list is not None and display_spaces(hp[after_list.part]) == [
             (False, None, None, "A point"), (False, None, "57143", "A smaller point"),
             (True, "0", None, "")]
         and "\ue002" not in every and "4 display equation(s) set off by space" in out
         and not re.search(r"<m:t(?:\s[^>]*)?(?:/>|></m:t>)", hp[display.part] + hp[kept.part])),
        ("space after a paragraph goes after its line spacing and space before, as the schema "
         "orders them, in place of any it had, an empty paragraph's too",
         lambda: [spaced_after(p) for p in (
             '<a:p><a:pPr lvl="1"><a:lnSpc><a:spcPct val="90000"/></a:lnSpc><a:spcBef><a:spcPts '
             'val="600"/></a:spcBef><a:buNone/></a:pPr><a:r/></a:p>',
             '<a:p><a:pPr><a:spcAft><a:spcPts val="1200"/></a:spcAft></a:pPr><a:r/></a:p>',
             '<a:p><a:pPr/><a:r/></a:p>', '<a:p><a:r/></a:p>', '<a:p/>')] == [
             '<a:p><a:pPr lvl="1"><a:lnSpc><a:spcPct val="90000"/></a:lnSpc><a:spcBef><a:spcPts '
             'val="600"/></a:spcBef><a:spcAft><a:spcPct val="25000"/></a:spcAft><a:buNone/>'
             '</a:pPr><a:r/></a:p>']
         + ['<a:p><a:pPr><a:spcAft><a:spcPct val="25000"/></a:spcAft></a:pPr><a:r/></a:p>'] * 3
         + ['<a:p><a:pPr><a:spcAft><a:spcPct val="25000"/></a:spcAft></a:pPr></a:p>']),
        ("vertical space the deck gives in raw LaTeX is added to the space before the text "
         "after it, in lines of the deck's PDF, its units each its own, and less than none is "
         "none; it can't fill, or come after the text on its slide",
         lambda: space is not None and display_spaces(hp[space.part]) == [
             (False, None, None, "First words."), (False, "108235", None, "Second words."),
             (False, "0", None, "Third words"), (False, "229211", None, "Fourth words."),
             (False, "124606", None, "Fifth words.")]
         and space_again is not None and display_spaces(hp[space_again.part]) == [
             (False, None, None, "Words before."), (False, "70000", None, "An item"),
             (False, "122243", None, "A Heading"), (False, "123897", None, "Last words.")]
         and "\ue003" not in every and not re.search("[\U000F0000-\U000FFFFD]", every)
         and "vfill" not in every and "vspace" not in every
         and "11 vertical space(s) the decks give in raw LaTeX given before the text after "
         "them" in out
         and "Pandoc's PowerPoint writer left out 3 block(s) of 1 deck(s) (shapes 3)" in out),
        ("space the deck gives at the top of a slide's text is given there, and the text body "
         "told to respect it, as PowerPoint otherwise wouldn't",
         lambda: space_top is not None and display_spaces(hp[space_top.part]) == [
             (False, "161029", None, "Pushed down."), (False, None, None, "Not pushed.")]
         and re.search(r'<a:bodyPr\b[^>]*\sspcFirstLastPara="1"', hp[space_top.part])
         and "".join(pptx_slides(hp)).count("spcFirstLastPara") == 1),
        ("above an equation at the top of a slide's text, whose space before PowerPoint "
         "doesn't show however the body is told, the deck's space widens the text body's top "
         "inset, over the master's, in the equation's lines, the text after it set off",
         lambda: top_math is not None and display_spaces(hp[top_math.part]) == [
             (True, "0", None, ""), (False, "50000", None, "After it.")]
         and re.findall(r"<p:txBody><a:bodyPr([^>]*)>", hp[top_math.part])[1:]
         == [' tIns="%d"/' % (60960 + round(10.95 / 13.6 * 1.2 * 32 * 12700))] * 2),
        ("text set to fit counts a paragraph's own space before it and after it, the first "
         "one's before and the last one's after when its box respects them, a display "
         "equation with a fraction a line taller, and the text body's own top inset",
         lambda: text_height(WORDS, SPACED_WORDS) > text_height(WORDS, WORDS)
         and text_height(WORDS_SPACED, WORDS) > text_height(WORDS, WORDS)
         == text_height(WORDS, WORDS_SPACED)
         and text_height(WORDS, WORDS_SPACED, respected=True)
         > text_height(WORDS, WORDS, respected=True)
         and text_height(WORDS, TALL_DISPLAY) > text_height(WORDS, FLAT_DISPLAY)
         and text_height(SPACED_WORDS, respected=True) > text_height(SPACED_WORDS)
         == text_height(WORDS)
         and abs(text_height(WORDS, top=500000) - text_height(WORDS) - (500000 - 45720)) <= 1),
        ("a text body's top inset is its placeholder's in its layout, by index and then by "
         "type, else its master's by type, else a twentieth of an inch",
         lambda: [inset_of('<p:nvSpPr><p:nvPr>%s</p:nvPr></p:nvSpPr>' % ph, INSET_LAYOUT,
                           INSET_MASTER) for ph in (
             '<p:ph idx="13"/>', '<p:ph idx="1"/>', '<p:ph type="title"/>',
             '<p:ph type="subTitle" idx="2"/>', '<p:ph type="dt" idx="10"/>', '')]
         == [1000, 1000, 3000, 2000, 45720, 45720]),
        ("a table's cells keep their words, spaces, and formatting, the marker taken out",
         lambda: formatted is not None
         and [s.text for s in formatted.shapes if s.kind == "graphicFrame"]
         == ["Bold italic\tValue\na link code\t1"]
         and re.search(r'<a:rPr b="1"[^>]*/><a:t>Bold</a:t>', formatted_xml)
         and re.search(r'<a:t> </a:t></a:r><a:r><a:rPr i="1"[^>]*/><a:t>italic</a:t>',
                       formatted_xml)
         and "<a:hlinkClick" in formatted_xml
         and 'Target="https://example.org"' in slide_rels(hp, formatted)),
        ("an incremental list's animation names the shape holding it, after a captioned "
         "table, or after text and a table",
         lambda: steps_xml and shape_id(steps_xml, "First step") is not None
         and animated(steps_xml) == ([shape_id(steps_xml, "First step")],) * 2
         and more_xml and shape_id(more_xml, "Third step") is not None
         and animated(more_xml) == ([shape_id(more_xml, "Third step")],) * 2),
        ("a figure of two pictures shows both, its caption under the last",
         lambda: [(s.kind, s.descr) for s in slide_titled(hd, "Figure Pair").shapes
                  if not s.is_title] == [("pic", "Left chart")]
         and pair is not None and [(s.kind, s.descr, s.text or "", s.decorative)
                                   for s in pair.shapes if not s.is_title] == [
             ("pic", "Right chart", "", False), ("sp", None, "Two charts side by side.", False)]),
        ("a link to a div, or to a figure of two pictures, goes to the slide it's on, and a "
         "div's picture stays one",
         lambda: slide_links(hp, slide_titled(hd, "Div Link")) == sorted(
             [file_of(slide_titled(hd, "Div Target")), file_of(slide_titled(hd, "Figure Pair")),
              file_of(slide_titled(hd, "Boxed Picture"))])
         and [s.descr for s in slide_titled(hd, "Boxed Picture").shapes if s.kind == "pic"]
         == ["Boxed chart"]),
        ("a notes div with another class too is the slide's notes, not shown on it",
         lambda: private is not None and "Only for the speaker." not in hp[private.part]
         and "Only for the speaker." in notes_of(hp, private)),
        ("a list in a slide's notes has the bullets the master gives a slide's list, hanging as "
         "a numbered one does, where the writer gave none, and the run says",
         lambda: listed is not None and notes_list(notes_of(hp, listed)) == [
             ("Two points:", "0", None, "none"), ("First", "0", "-457200", "\u2022"),
             ("Under it", "1", "-457200", "\u2013"), ("Second", "0", "-457200", "\u2022"),
             ("Numbered", "0", "-457200", "number")]
         and "4 paragraph(s) of lists in speaker notes given their bullets" in out),
        ("a link in a slide's notes is a link, which the writer took out: its words linked, a "
         "word formatted inside it too, code too, its ScreenTip its title, each address a "
         "relationship of the notes slide's; one to a place in the deck its words, and the run "
         "says both",
         lambda: [(w, rel_target(linked_rels, r), tip) for w, r, tip in notes_links(linked_xml)]
         == [("the ", "https://example.org/data", "Where the data &amp; more are"),
             ("source", "https://example.org/data", "Where the data &amp; more are"),
             ("https://example.org/two?a=1&amp;b=2", "https://example.org/two?a=1&amp;b=2", None),
             ("the code", "https://example.org/data", None),
             ("someone@example.org", "mailto:someone@example.org", None)]
         and linked_rels.count("relationships/hyperlink") == 3
         and re.search(r'<a:latin typeface="[^"]*" ?/><a:hlinkClick r:id="[^"]*"/></a:rPr>'
                       r'<a:t>the code</a:t>', linked_xml)
         and "the first" in linked_xml and "this one" in linked_xml and not marks
         and "5 link(s) in speaker notes put back" in out
         and "2 link(s) in the speaker notes of 1 deck(s) to a place in the deck aren't links "
             "in the PowerPoint files" in out),
        ("and marks with no link recorded leave their words, unlinked",
         lambda: unrecorded_link() == (
             '<a:p><a:r><a:rPr lang="en"/><a:t>See </a:t></a:r><a:r><a:rPr lang="en"/>'
             '<a:t>the data</a:t></a:r><a:r><a:rPr lang="en"/><a:t>.</a:t></a:r></a:p>',
             "<Relationships></Relationships>", 0)),
        ("and a link in the title slide's notes, which the metadata's notes field holds",
         lambda: [(w, rel_target(notes_rels(hp, hd.slides[0]), r), tip)
                  for w, r, tip in notes_links(notes_of(hp, hd.slides[0]))]
         == [("the site", "https://example.org/plan", None)]),
        ("notes between a slide's heading and its columns stay with the slide",
         lambda: notes_first is not None and notes_first.layout == "Two Content"
         and slide_titled(hd, "Notes First (2)") is None
         and "Say this first." in notes_of(hp, notes_first)),
        ("the deck's language is on its runs and the styles they inherit, not the "
         "reference's",
         lambda: 'lang="en-US"' not in every and 'lang="de-DE"' in hp["ppt/presentation.xml"]
         and 'lang="de-DE"' in hp["ppt/slideMasters/slideMaster1.xml"] and hd.language == "de-DE"),
        ("the file's title is the deck's, a list of one in its YAML, or its file's name",
         lambda: fd.core_title == "Demand: A Short Deck"
         and pptx_deck(untitled).core_title == "untitled"),
        ("an institute is shown under the authors, and the authors alone are the creator",
         lambda: "Shepherd University" in hd.slides[0].shapes[1].text
         and "<dc:creator>A. Lecturer</dc:creator>" in hp["docProps/core.xml"]),
        ("the custom properties hold none of beamer's or the pipeline's fields",
         lambda: "theme" not in fp["docProps/custom.xml"]
         and "aspectratio" not in sp["docProps/custom.xml"]
         and "institute" not in hp["docProps/custom.xml"]),
        ("docProps/app.xml lists the deck's slides' titles, not the reference's",
         lambda: "<vt:lpstr>Picture and Text (2)</vt:lpstr>" in hp["docProps/app.xml"]
         and "Slide Title for Two-Content" not in hp["docProps/app.xml"]
         and "<Slides>%d</Slides>" % len(hd.slides) in hp["docProps/app.xml"]),
        ("the slides are the deck's shape at PowerPoint's size: 4:3 for a beamer theme, "
         "16:10 its aspectratio, 16:9 otherwise, Widescreen",
         lambda: (fd.width, fd.height) == (9144000, 6858000)
         and (sd.width, sd.height) == (9144000, 5715000)
         and (hd.width, hd.height) == (12192000, 6858000)
         and '<p:sldSz cx="9144000" cy="5715000" type="screen16x10"' in sp["ppt/presentation.xml"]
         and '<p:sldSz cx="12192000" cy="6858000" />' in hp["ppt/presentation.xml"]
         and "<PresentationFormat>Widescreen</PresentationFormat>" in hp["docProps/app.xml"]
         and "<PresentationFormat>On-screen Show (4:3)</PresentationFormat>" in fp["docProps/app.xml"]
         and "4:3 (its theme, which is beamer's) for 1" in out
         and "16:9 (the default), Widescreen, for 2" in out),
        ("a 4:3 deck's layouts are Pandoc's, scaled down the slide as PowerPoint's 4:3 has "
         "them, its text Pandoc's size; a Widescreen deck's Pandoc's enlarged a third, text "
         "and all",
         lambda: abs(fd.slides[1].title_shape.box.y - 274638) <= 1
         and fd.slides[1].title_shape.box.cy == 1143000
         and master_sizes(fp) == (33.0, 24.0, 13.5)
         and (slide_titled(hd, "Columns").title_shape.box.x,
              slide_titled(hd, "Columns").title_shape.box.cx,
              slide_titled(hd, "Columns").title_shape.box.cy) == (609600, 10972800, 1143000)
         and master_sizes(hp) == (44.0, 32.0, 18.0)),
        ("speaker notes are the slides' notes, and a pause is gone, the run says",
         lambda: "Ask what the class would pay for water." in "".join(
             x for n, x in fp.items() if n.startswith("ppt/notesSlides/"))
         and ". . ." not in "".join(pptx_slides(fp))
         and "1 pause(s) in 1 deck(s) are left out of the PowerPoint files" in out),
        ("a footnote's text is on the end's Notes slide", lambda: sd.slides[-1].title == "Notes"
         and "Its source." in sd.slides[-1].shapes[1].text),
        ("a passage in another language is named in the run's notes",
         lambda: "1 passage(s) in another language in 1 deck(s)" in out),
        ("a slide's highlighted code is in the theme's colors (lib/highlighting.py)",
         lambda: code is not None and 'srgbClr val="%s"' % highlight_color("DecVal")[1:].upper()
         in sp[code.part]),
    ]
    return checks


def foreign_reference(source, out):
    """A reference document unlike Pandoc's: its Comparison layout named
    otherwise, no size in its master's text styles, and Pandoc's default
    table style, a header row of white on its theme's blue, 4.0:1."""
    import zipfile
    with zipfile.ZipFile(source) as z, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as o:
        for info in z.infolist():
            data = z.read(info.filename)
            if re.match(r"ppt/slideLayouts/slideLayout\d+\.xml$", info.filename):
                data = re.sub(rb'(<p:cSld name=")Comparison(")', rb"\1Side by Side\2", data)
            elif info.filename == "ppt/slideMasters/slideMaster1.xml":
                text = data.decode("utf-8")
                start, end = text.find("<p:txStyles>"), text.find("</p:txStyles>")
                data = (text[:start] + re.sub(r'\ssz="\d+"', "", text[start:end])
                        + text[end:]).encode("utf-8")
            elif info.filename == "ppt/tableStyles.xml":
                data = re.sub(rb'def="[^"]*"', b'def="{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"',
                              data)
            o.writestr(info, data)


def case_pptx_settings(work):
    """slides.notes omitted, slides.reference_doc and slides.aspect_ratio
    and slides.size beside it, a reference document unlike Pandoc's,
    slides.size on-screen-show, a book's pptx target, and a Pandoc too
    old."""
    import pptxtarget
    unready = too_old("PPTX_PANDOC", "a deck's PowerPoint file")
    config = PPTX + "    slides:\n      notes: omitted\n      reference_doc: look.pptx\n" \
        "      aspect_ratio: \"16:9\"\n      size: on-screen-show\n"
    decks_dir = folder(os.path.join(work, "decks"), config,
                       decks_given={"Flat Deck.md": FLAT})
    pptxtarget.reference_doc("1.41:1", os.path.join(decks_dir, "look.pptx"))
    result = convert(decks_dir, "--quick")
    made = os.path.join(decks_dir, "slides", "Flat-Deck.pptx")
    parts = pptx_parts(made) if os.path.exists(made) else {}
    foreign_dir = folder(os.path.join(work, "foreign"), PPTX + "    slides:\n      "
                         "reference_doc: house.pptx\n", decks_given={"Flat Deck.md": FLAT})
    pptxtarget.reference_doc("16:9", os.path.join(work, "pandoc-look.pptx"))
    foreign_reference(os.path.join(work, "pandoc-look.pptx"),
                      os.path.join(foreign_dir, "house.pptx"))
    foreign = convert(foreign_dir, "--quick")
    foreign_made = os.path.join(foreign_dir, "slides", "Flat-Deck.pptx")
    show_dir = folder(os.path.join(work, "show"), PPTX + "    slides:\n      size: on-screen-show\n",
                      decks_given={"one.md": UNTITLED})
    show = convert(show_dir, "--quick")
    shown = os.path.join(show_dir, "slides", "one.pptx")
    show_parts = pptx_parts(shown) if os.path.exists(shown) else {}
    missing = folder(os.path.join(work, "missing"), PPTX + "    slides:\n      reference_doc: "
                     "nowhere.pptx\n", decks_given={"one.md": UNTITLED})
    nowhere = convert(missing, "--quick")
    book = os.path.join(work, "book")
    os.makedirs(book)
    write(os.path.join(book, "one.md"), "# A Page\n\nText.\n")
    write(os.path.join(book, "project.yaml"),
          "project:\n  identifier: org.example.book\n  title: A Book\n")
    write(os.path.join(book, "conversion.yaml"), PPTX + "  pages:\n    format: html\n")
    as_book = convert(book, "--quick")
    old_dir = folder(os.path.join(work, "old"), PPTX, decks_given={"one.md": UNTITLED})
    tools = os.path.join(work, "tools")
    os.makedirs(tools)
    real = shutil.which("pandoc")
    write(os.path.join(tools, "pandoc"), "#!/bin/sh\nif [ \"$1\" = --version ]; then echo "
          "'pandoc 3.10.0'; exit 0; fi\nexec %s \"$@\"\n" % real)
    os.chmod(os.path.join(tools, "pandoc"), 0o755)
    old = convert(old_dir, "--quick", env=dict(os.environ, PATH=tools + os.pathsep
                                               + os.environ["PATH"]))
    built = [
        ("slides.notes omitted leaves the speaker notes out, and the run says so",
         lambda: result.returncode == 0 and parts
         and not any(n.startswith("ppt/notesSlides/") for n in parts)
         and "slides.notes is omitted for target slides" in result.stderr),
        ("slides.reference_doc's slides' size is the file's, slides.aspect_ratio and "
         "slides.size said unread",
         lambda: '<p:sldSz cx="9144000" cy="6485106"' in parts.get("ppt/presentation.xml", "")
         and "slides.aspect_ratio and slides.size aren't read for target slides's PowerPoint "
         "files" in result.stderr),
        ("slides.size on-screen-show makes a 16:9 deck PowerPoint's On-screen Show, Pandoc's "
         "own size and text",
         lambda: show.returncode == 0
         and '<p:sldSz cx="9144000" cy="5143500" type="screen16x9"' in show_parts.get(
             "ppt/presentation.xml", "")
         and "<PresentationFormat>On-screen Show (16:9)</PresentationFormat>"
         in show_parts["docProps/app.xml"]
         and master_sizes(show_parts) == (33.0, 24.0, 13.5)
         and "16:9 (the default), On-screen Show, for 1" in show.stderr),
        ("a reference document whose default table style's header row has too little "
         "contrast is warned of, and ours has enough",
         lambda: "WARNING: the tables in target slides's PowerPoint files take "
         "slides.reference_doc's default table style, Medium Style 2 - Accent 1, whose header "
         "row is #FFFFFF on #4F81BD, a contrast of 4.0:1, under the 4.5:1 PowerPoint's "
         "Accessibility Checker asks for" in foreign.stderr
         and "contrast of" not in result.stderr
         and pptxtarget.table_contrast(os.path.join(decks_dir, "look.pptx"))[1:3]
         == ("000000", "FFFFFF")),
        ("a reference document without a layout Pandoc's writer looks for is warned of, and "
         "one whose master gives no text size is read",
         lambda: foreign.returncode == 0 and os.path.exists(foreign_made)
         and 'WARNING: slides.reference_doc, house.pptx, has no layout named "Comparison", '
         "which Pandoc's PowerPoint writer looks for by name" in foreign.stderr
         and "Traceback" not in foreign.stderr),
        ("a reference document that isn't there stops the run, saying where it looked",
         lambda: nowhere.returncode != 0 and "slides.reference_doc is" in nowhere.stderr
         and "nowhere.pptx" in nowhere.stderr and "doesn't exist" in nowhere.stderr),
    ]
    # Said before a deck's target is built, whatever the Pandoc.
    before = [
        ("a book's pptx target writes nothing, and the run says why",
         lambda: as_book.returncode == 0
         and "target slides is format pptx, which is written for decks written in Markdown"
         in as_book.stderr and not os.path.exists(os.path.join(book, "slides"))),
        ("a Pandoc older than 3.10.1 stops the pptx target, saying why",
         lambda: old.returncode != 0 and "Pandoc 3.10.0 is too old for target slides's "
         "PowerPoint files" in old.stderr),
    ]
    if unready:
        print(f"  skip  {len(built)} checks of the PowerPoint files' settings: {unready}")
        return before
    return built + before


# A column with two pictures, which the writer puts in one place; a third
# column, which it doesn't write; a column with a table after a picture,
# which it leaves out; and an SVG.
EDGES = """\
---
title: Edges
notes: "Said [aloud](https://example.org/aloud)."
---

# Stacked

:::: columns
::: column
![One](img/chart.png)

![Two](img/chart.png)
:::
::: column
Words.
:::
::::

# Three Columns

:::: columns
::: column
A
:::
::: column
B
:::
::: column
C
:::
::::

# Cut Column

:::: columns
::: column
![One](img/chart.png)

| a | b |
|---|---|
| 1 | 2 |
:::
::: column
Words.
:::
::::

# Vector

![A bar](img/bar.svg)

# Column Picture

:::: columns
::: column
![Pic](img/chart.png) and its words.

More words.
:::
::: column
Right.
:::
::::

# Compare

:::: columns
::: column
Left text.

![Left pic](img/chart.png)
:::
::: column
Right text.

![Right pic](img/chart.png)
:::
::::

# Compare Table

:::: columns
::: column
Left text.

![Left pic](img/chart.png)

| a | b |
|---|---|
| 1 | 2 |
:::
::: column
Right text.

![Right pic](img/chart.png)
:::
::::

# Bad Math

The writer can't read $\\begin{nope} x \\end{nope}$.

# Raw LaTeX

Press \\textsc{small} and \\LaTeX{} now.
"""


def case_pptx_edges(work):
    """What the writer can't be brought to do, named; and an SVG, with
    rsvg-convert and without."""
    unready = too_old("PPTX_PANDOC", "a deck's PowerPoint file")
    if unready:
        print(f"  skip  {unready}; what the PowerPoint writer can't do isn't checked")
        return []
    decks_dir = folder(os.path.join(work, "decks"), PPTX, decks_given={"edges.md": EDGES})
    write(os.path.join(decks_dir, "img", "bar.svg"), "<svg xmlns='http://www.w3.org/2000/svg' "
          "width='40' height='20'><rect width='40' height='20' fill='#333'/></svg>")
    without = convert(decks_dir, "--quick", env=dict(os.environ, PATH=tools_without(work)))
    checks = [
        ("without rsvg-convert, a deck's SVG stops the pptx target, saying what it needs",
         lambda: without.returncode != 0 and "a deck's PowerPoint file needs rsvg-convert"
         in without.stderr and "librsvg2-bin" in without.stderr),
    ]
    if not shutil.which("rsvg-convert"):
        return checks
    result = convert(decks_dir, "--quick")
    made = os.path.join(decks_dir, "slides", "edges.pptx")
    parts = pptx_parts(made) if os.path.exists(made) else {}
    deck = pptx_deck(made) if parts else None
    vector = slide_titled(deck, "Vector") if deck else None
    rels = parts.get(vector.part.replace("slides/", "slides/_rels/") + ".rels", "") \
        if vector else ""
    checks += [
        ("shapes the writer puts over one another are named, by slide, and those less than "
         "a point into another not",
         lambda: result.returncode == 0 and "shapes overlap on slides of 1 PowerPoint file(s) "
         "(edges slide(s) 2, 6, 8)" in result.stderr),
        ("a paragraph that opens with a picture keeps its words in a column",
         lambda: "and its words." in parts[slide_titled(deck, "Column Picture").part]
         and "More words." in parts[slide_titled(deck, "Column Picture").part]),
        ("what the writer doesn't write is named: a third column, and raw LaTeX in a line",
         lambda: "Pandoc's PowerPoint writer left out 1 block(s) and 2 piece(s) of raw HTML or "
         "LaTeX in a line of text of 1 deck(s) (edges 3)" in result.stderr),
        ("what the writer leaves out of a column is named, a comparison's columns, shown "
         "whole, not",
         lambda: "1 block(s) in the columns of 1 deck(s) are left out of the PowerPoint files"
         in result.stderr and slide_titled(deck, "Compare Table").layout == "Comparison"
         and [s.kind for s in slide_titled(deck, "Compare Table").shapes
              if s.kind != "sp"] == ["pic", "graphicFrame", "pic"]),
        ("the writer's own warnings are passed on, by deck",
         lambda: "Pandoc's PowerPoint writer warned of 1 thing(s) writing the PowerPoint files:"
         in result.stderr and "  edges: Could not convert TeX math \\begin{nope} x \\end{nope}"
         in result.stderr),
        ("a link in the title slide's notes, a line in the metadata, is a link",
         lambda: deck is not None
         and [(w, rel_target(notes_rels(parts, deck.slides[0]), r), tip)
              for w, r, tip in notes_links(notes_of(parts, deck.slides[0]))]
         == [("aloud", "https://example.org/aloud", None)]),
        ("an SVG is a PNG with the SVG beside it, as PowerPoint inserts one",
         lambda: vector is not None and "asvg:svgBlip" in parts[vector.part]
         and re.search(r'Target="\.\./media/oer-svg1\.svg"', rels)
         and "ppt/media/oer-svg1.svg" in parts
         and 'Extension="svg"' in parts["[Content_Types].xml"]
         and [s.descr for s in vector.shapes if s.kind == "pic"] == ["A bar"]),
    ]
    return checks


# --------------------------------------------------------------------------
# a deck's reveal.js presentation
# --------------------------------------------------------------------------

REVEALJS = """\
targets:
  present:
    format: revealjs
"""

# An agenda before the first section, a section's slides, a block under a
# slide two levels down, a block with no title, a footnote, a link to a
# slide, a formula, notes, a slide in steps, a picture the deck has load
# lazily, a slide too tall for its frame, with a footnote far from its
# mark, and one too tall even at a quarter of its size.
PRESENTED = """---
title: Presented
author: A. Lecturer
---

## Agenda

1. One
2. Two

# Part One

## Opening

Text with a [link](https://example.org/) and $x^2$.[^1] On to [the steps](#steps).

#### A Block

Its text.

### {.example}

Untitled block text.

::: notes
Say hello.
:::

## Steps

- First
- Second

. . .

Later.

## A Picture

![A rising line](img/chart.png){loading=lazy}

## A Big Picture

![A big square](img/big.png)

""" + "".join(f"Paragraph {n} under the picture, with words.\n\n" for n in range(1, 4)) + """
# Part Two

## A Bit Long

""" + "".join(f"- Short item {n}\n" for n in range(1, 13)) + """
## A Long List

- Item number 1, with words enough to wrap its line on a slide[^2]
""" + "".join(f"- Item number {n}, with words enough to wrap its line on a slide\n"
              for n in range(2, 19)) + """
## Too Long

""" + "".join(f"- Line {n}\n" for n in range(1, 160)) + """
[^1]: A note on the opening.

[^2]: A note on the long list.
"""

# A slide too tall for a narrow window's page, a step at its end, and
# after it a slide with no title, as tall: where the step is, and where
# that slide's page starts.
NO_TITLE_SLIDE = """---
title: A Slide With No Title
---

## Long First

""" + "".join(f"- Long line {n}\n" for n in range(1, 40)) + """
. . .

The step at its end.

---

""" + "".join(f"- Line {n} of a slide with no title\n" for n in range(1, 11))


def revealjs_ready():
    """Why a presentation can't be built here, or None: the repository's
    copy of reveal.js, or REVEALJS_DIR's, is what it loads."""
    import revealtarget
    return revealtarget.revealjs_problem(revealtarget.revealjs_folder())


def vendored_problem(missing):
    """What the run says of the repository's copy of reveal.js with the
    file missing taken out of a copy of it."""
    import revealtarget
    copy = tempfile.mkdtemp(prefix="vendored-")
    kept = revealtarget.VENDORED
    try:
        shutil.copytree(kept, os.path.join(copy, "reveal.js"))
        os.remove(os.path.join(copy, "reveal.js", missing))
        revealtarget.VENDORED = os.path.join(copy, "reveal.js")
        return revealtarget.revealjs_problem(revealtarget.revealjs_folder({}))
    finally:
        revealtarget.VENDORED = kept
        shutil.rmtree(copy, ignore_errors=True)


def vendored_version():
    """The version vendor/reveal.js/README.md's title gives, and its
    package.json's."""
    import revealtarget
    title = read(os.path.join(revealtarget.VENDORED, "README.md")).split("\n", 1)[0]
    return title.replace("# reveal.js ", "", 1), revealtarget.revealjs_version(revealtarget.VENDORED)


def browser_problem():
    """Why a presentation can't be tried in a browser here, or None: Python's
    Playwright tries it, in the Chromium Playwright installs."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "Playwright isn't installed (docs/installation.md says how to install both)"
    try:
        with sync_playwright() as play:
            play.chromium.launch().close()
    except Exception as exc:
        lines = str(exc).strip().splitlines()
        reason = lines[0][:200] if lines else type(exc).__name__
        return (f"Playwright's Chromium doesn't start ({reason}); `python3 -m playwright install "
                "--with-deps --only-shell chromium` installs it (see docs/installation.md)")
    return None


# Fonts that come after the page has loaded, as from a slow server: the
# page's document.fonts.ready a tenth of a second after its load event,
# after reveal.js's own layout on that event.
LATE_FONTS = """(() => {
  const ready = document.fonts.ready;
  const late = new Promise(done => addEventListener('load', () => setTimeout(done, 100)));
  Object.defineProperty(document.fonts, 'ready',
                        {get: () => Promise.all([ready, late]).then(() => document.fonts)});
})();"""


def in_browser(path, steps, width=1280, height=720, touch=False, broken=False, late_fonts=False):
    """What steps (a function of a Playwright page) give of the presentation
    at path (and #fragment), opened in Chromium in a window width by
    height, served over HTTP from its folder, its big picture a second
    late, as from a slow server, or never (broken), and its fonts after
    the page has loaded (late_fonts), or {"error": ...} when they fail.
    browser_problem() says first whether Playwright and its Chromium are
    here to try it."""
    from playwright.sync_api import sync_playwright
    import functools
    import http.server
    import threading
    import time
    file, _, fragment = path.partition("#")

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(Quiet, directory=os.path.dirname(file)))
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def late(route):
        time.sleep(1)
        if broken:
            route.abort()
        else:
            route.continue_()
    try:
        with sync_playwright() as play:
            browser = play.chromium.launch()
            try:
                context = browser.new_context(viewport={"width": width, "height": height},
                                              has_touch=touch, is_mobile=touch)
                if late_fonts:
                    context.add_init_script(LATE_FONTS)
                page = context.new_page()
                page.route("**/img/big.png", late)
                page.goto(f"http://127.0.0.1:{server.server_port}/{os.path.basename(file)}"
                          + (f"#{fragment}" if fragment else ""))
                page.wait_for_function("() => window.Reveal && Reveal.isReady()")
                page.wait_for_function("() => document.fonts.status === 'loaded'")
                page.wait_for_function("() => Array.from(document.images).every(i => i.complete)"
                                       if not broken else "() => true")
                if broken:
                    page.wait_for_timeout(1500)
                page.wait_for_timeout(500)
                return steps(page)
            finally:
                browser.close()
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    finally:
        server.shutdown()
        server.server_close()


FOCUSED = "() => { const a = document.activeElement; return [a.tagName, a.textContent.trim()]; }"
OUTLINE = "() => getComputedStyle(document.activeElement).outlineStyle"
LINK = """() => { const a = document.querySelector('#opening a[href^="http"]'); const s = getComputedStyle(a);
  return [s.color, s.textDecorationLine]; }"""
FITTED = """() => Reveal.getSlides().map(s => {
  const shown = s.style.display; s.style.display = 'block';
  const title = s.querySelector('h1,h2,h3');
  const out = [title && title.textContent,
               s.classList.contains('oer-fitted'), s.classList.contains('oer-scrolled'),
               s.style.getPropertyValue('--oer-scale'), s.scrollHeight,
               title && getComputedStyle(title).fontSize, s.style.getPropertyValue('--oer-line'),
               getComputedStyle(s).overflowY, s.clientHeight,
               title && getComputedStyle(title).textTransform];
  s.style.display = shown; return out; })"""


def left_out(page, selector):
    """Whether Chromium leaves the element selector names out of the
    accessibility tree a screen reader reads."""
    cdp = page.context.new_cdp_session(page)
    root = cdp.send("DOM.getDocument")["root"]["nodeId"]
    node = cdp.send("DOM.querySelector", {"nodeId": root, "selector": selector})["nodeId"]
    return cdp.send("Accessibility.getPartialAXTree",
                    {"nodeId": node, "fetchRelatives": False})["nodes"][0].get("ignored", False)


def presentation_steps(page):
    found = {"role": page.evaluate("() => document.querySelector('.reveal').getAttribute('role')"),
             "live": page.evaluate("() => { const s = document.querySelector('.aria-status');"
                                   " return [s.getAttribute('aria-live'), s.getAttribute('aria-hidden')]; }"),
             "progress": left_out(page, ".reveal .progress"),
             "controls": left_out(page, ".reveal .controls"),
             "fitted": page.evaluate(FITTED)}
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(300)
    found["first"] = page.evaluate(FOCUSED)
    found["arrows"] = page.evaluate("() => ['left', 'right'].map(side => getComputedStyle("
                                    "document.querySelector('.reveal .controls .navigate-' + side))"
                                    ".opacity)")
    found["outline"] = page.evaluate(OUTLINE)
    found["link"] = page.evaluate(LINK)
    page.emulate_media(reduced_motion="reduce")
    found["motion"] = page.evaluate("() => getComputedStyle(Reveal.getCurrentSlide())"
                                    ".transitionDuration")
    page.emulate_media(reduced_motion="no-preference")
    page.evaluate("() => Reveal.slide(Reveal.getSlides().findIndex("
                  "s => s.id === 'steps'))")
    page.wait_for_timeout(300)
    found["title"] = page.evaluate(FOCUSED)
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(300)
    found["step"] = page.evaluate(FOCUSED)
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(300)
    found["overview"] = page.evaluate(FOCUSED)
    return found


PLACE = """() => { const a = document.activeElement;
  return [a.tagName, a.id || a.textContent.trim(), a.hasAttribute('tabindex'),
          getComputedStyle(a).outlineStyle, Reveal.getCurrentSlide().id]; }"""


def link_steps(page):
    """Opened at the Opening slide: its footnote's mark followed from the
    keyboard, the note's way back, and the link to the Steps slide."""
    found = {}
    for name, link in (("note", "#opening a.footnote-ref"), ("back", "#opening a.footnote-back"),
                       ("slide", '#opening a[href="#/steps"]')):
        page.focus(link)
        page.keyboard.press("Enter")
        page.wait_for_timeout(300)
        found[name] = page.evaluate(PLACE)
    return found


def scroll_steps(page):
    """Opened at A Long List: on to Too Long, which scrolls, then down, the
    overview opened and closed with space, and left."""
    current = "() => [Reveal.getCurrentSlide().id, Reveal.getCurrentSlide().scrollTop]"
    found = {}
    for name, key in (("right", "ArrowRight"), ("down", "ArrowDown"), ("overview", "Escape"),
                      ("space", "Space"), ("left", "ArrowLeft")):
        page.keyboard.press(key)
        page.wait_for_timeout(300)
        found[name] = page.evaluate(current) + [page.evaluate("() => Reveal.isOverview()")]
    return found


def narrow_steps(page):
    view = ("() => [document.documentElement.classList.contains('oer-page-view'),"
            " Reveal.getCurrentSlide().id, scrollY,"
            " getComputedStyle(Reveal.getCurrentSlide().querySelector('li, p')).fontSize,"
            " document.querySelector('.reveal .slides').style.transform]")
    # The controls shown, top and bottom, and the bottom of the slide's end.
    controls = """() => { const shown = Array.from(document.querySelectorAll('.reveal .controls button'))
      .filter(b => { const s = getComputedStyle(b);
        return s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0'; })
      .map(b => b.getBoundingClientRect());
      return [Math.min(...shown.map(r => r.top)), Math.max(...shown.map(r => r.bottom)),
              Reveal.getCurrentSlide().lastElementChild.getBoundingClientRect().bottom]; }"""
    found = {"opened": page.evaluate(view)}
    # Where the slide is on the page, against the top of the slides' room
    # (nothing before it, nor reveal.js's centering left on it), and
    # whether the page is any wider than the window.
    found["placed"] = page.evaluate("""() => {
      const s = Reveal.getCurrentSlide(), room = document.querySelector('.reveal .slides');
      return [Math.round(s.getBoundingClientRect().top - room.getBoundingClientRect().top
                         - parseFloat(getComputedStyle(room).paddingTop)),
              document.documentElement.scrollWidth <= innerWidth]; }""")
    page.keyboard.press("ArrowDown")
    page.wait_for_timeout(300)
    found["down"] = page.evaluate(view)
    top, bottom, _ = page.evaluate(controls)
    found["controls"] = top >= 0 and bottom <= page.viewport_size["height"]
    page.keyboard.press("End")
    page.wait_for_timeout(300)
    top, _, end = page.evaluate(controls)
    found["end"] = page.evaluate(view)[1:3] + [end <= top]
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(300)
    found["right"] = page.evaluate(view)
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    found["overview"] = page.evaluate("() => Reveal.isOverview()")
    width, height = page.viewport_size["width"], page.viewport_size["height"]
    page.set_viewport_size({"width": 1280, "height": 720})
    page.wait_for_timeout(300)
    found["widened"] = page.evaluate(view)
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    found["widened overview"] = page.evaluate("() => Reveal.isOverview()")
    page.set_viewport_size({"width": width, "height": height})
    page.wait_for_timeout(300)
    found["narrowed"] = page.evaluate(view)[:2] + [page.evaluate("() => Reveal.isOverview()")]
    return found


def top_steps(page):
    """In a narrow window, Long First's step shown, far below its title, then
    on to the slide with no title: whether the step is scrolled into view
    as it takes focus, and where that slide's page starts."""
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(500)
    found = {"step": page.evaluate("""() => { const a = document.activeElement, r = a.getBoundingClientRect();
      return [a.textContent.trim(), Reveal.getCurrentSlide().id, r.top >= 0 && r.bottom <= innerHeight]; }""")}
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(500)
    found["next"] = page.evaluate("() => [scrollY, document.activeElement.tagName, "
                                  "!Reveal.getCurrentSlide().querySelector('h1, h2, h3')]")
    return found


def note_steps(page):
    """In a narrow window, A Long List's footnote mark followed: whether the
    note, far below it, is scrolled into view."""
    page.focus("#a-long-list a.footnote-ref")
    page.keyboard.press("Enter")
    page.wait_for_timeout(300)
    return page.evaluate("""() => { const a = document.activeElement, r = a.getBoundingClientRect();
      return [a.id, r.top >= 0 && r.bottom <= innerHeight]; }""")


def case_revealjs(work):
    unready = too_old("REVEALJS_PANDOC", "a deck's reveal.js presentation")
    if unready:
        print(f"  skip  {unready}; a deck's presentation isn't checked")
        return []
    problem = revealjs_ready()
    if problem:
        return [("a copy of reveal.js to build the presentations with: " + problem,
                 lambda: False)]
    decks_dir = folder(work, REVEALJS, decks_given={"presented.md": PRESENTED,
                                                    "no-title.md": NO_TITLE_SLIDE})
    png(os.path.join(decks_dir, "img", "big.png"), 200, 120, 40, size=600)
    result = convert(decks_dir)
    out = os.path.join(decks_dir, "present")
    path = os.path.join(out, "presented.html")
    page = read(path) if os.path.exists(path) else ""
    check = [r for r in rows_of(os.path.join(decks_dir, "output-check.csv"))
             if r[0].endswith(".html")]
    import outputcheck
    nu = outputcheck.find_validator("vnu")
    if not nu:
        print("  skip  the Nu HTML checker not installed (VNU_JAR); its warning of a slide "
              "with no title isn't checked")
    browser = browser_problem() if page else None
    tried = page and not browser
    browsed = in_browser(path, presentation_steps) if tried else {}
    linked = in_browser(path + "#/opening", link_steps) if tried else {}
    scrolled = in_browser(path + "#/a-long-list", scroll_steps) if tried else {}
    narrow = in_browser(path + "#/a-long-list", narrow_steps, 900, 506) if tried else {}
    noted = in_browser(path + "#/a-long-list", note_steps, 900, 506) if tried else {}
    topped = in_browser(os.path.join(out, "no-title.html#/long-first"), top_steps, 900, 506) \
        if tried else {}
    phone = in_browser(path + "#/a-long-list", narrow_steps, 375, 667, touch=True) if tried else {}
    broken = in_browser(path, lambda p: p.evaluate(FITTED), broken=True) if tried else {}
    centered = in_browser(path + "#/a-long-list", lambda p: (p.wait_for_function(
        "() => Reveal.getCurrentSlide().classList.contains('oer-fitted')"), p.evaluate(
        "() => [Reveal.getCurrentSlide().style.top, Reveal.getCurrentSlide().scrollHeight]"))[1],
        late_fonts=True) if tried else {}
    checks = [
        ("a presentation of each deck, beside a copy of reveal.js, its license and its "
         "theme's font's, and the deck's pictures, nothing loaded from elsewhere",
         lambda: result.returncode == 0 and "Wrote 2 presentation(s)" in result.stderr
         and all(os.path.isfile(os.path.join(out, "reveal.js", name)) for name in (
             "dist/reveal.js", "dist/reveal.css", "dist/reset.css", "dist/theme/white.css",
             "dist/plugin/notes.js", "dist/plugin/search.js", "dist/plugin/zoom.js", "LICENSE",
             "css/theme/fonts/source-sans-pro/LICENSE"))
         and os.path.isfile(os.path.join(out, "img", "chart.png"))
         and "unpkg" not in page and 'href="reveal.js/dist/theme/white.css"' in page),
        ("the deck's language, a viewport a reader can zoom, and every picture's address src, "
         "loaded with the page",
         lambda: '<html lang="en-US">' in page
         and '<meta name="viewport" content="width=device-width, initial-scale=1.0">' in page
         and "user-scalable" not in page and "data-src" not in page
         and '<img src="img/chart.png"' in page and "loading=" not in page),
        ("each heading at the level the deck's page gives it, the title the one H1, and a "
         "block with no title no heading",
         lambda: headings(page) == [
             (1, "Presented"), (2, "Agenda"), (2, "Part One"), (3, "Opening"), (4, "A Block"),
             (3, "Steps"), (3, "A Picture"), (3, "A Big Picture"), (2, "Part Two"),
             (3, "A Bit Long"), (3, "A Long List"), (3, "Too Long")]
         and "oer-level" not in page and "Untitled block text." in page),
        ("a section's slides in one row with the rest, and reveal.js's own scroll view off",
         lambda: not re.search(r"<section>\s*<section", page)
         and "Reveal.initialize({\n        scrollActivationWidth: null," in page),
        ("the slides the deck's shape, no bouncing arrow, a footnote at the foot of its slide, "
         "MathML, and the notes for the speaker's view",
         lambda: "        width: 1280,\n" in page and "        height: 720,\n" in page
         and "        controlsTutorial: false,\n" in page
         and re.search(r'<section id="opening"(?:(?!<section).)*<aside id="footnotes" '
                       r'class="footnotes footnotes-end-of-section"', page, re.S)
         and "<math" in page and '<aside class="notes">' in page
         and "showNotes: false," in page and "speaker notes in reveal.js's speaker view"
         in result.stderr),
        ("the look over reveal.js's white theme and the script after reveal.js starts",
         lambda: "--r-heading-text-transform: none;" in page and "oer-page-view" in page
         and page.index("Reveal.initialize(") < page.index("function pageView")),
        ("the output check finds nothing in the presentations but the slide with no title, a "
         "section with no heading, which the Nu checker warns of",
         lambda: page and [(os.path.basename(r[0]), r[1]) for r in check]
         == [("no-title.html", "vnu:warning")] and "Section lacks heading" in check[0][2])
        if nu else ("the output check finds nothing in the presentations",
                    lambda: page and check == []),
    ]
    in_browser_checks = [
        ("in a browser, reveal.js's role and its live region go, its progress bar, which a "
         "mouse can click and NVDA reads as a space, is left out of what a screen reader reads, "
         "its controls not, and a slide's title takes focus as it's shown, outlined as no "
         "keyboard focus is, a step's content as it appears, and nothing in the overview",
         lambda: browsed.get("role") is None and browsed.get("live") == [None, "true"]
         and browsed.get("progress") is True and browsed.get("controls") is False
         and browsed.get("first") == ["H2", "Agenda"] and browsed.get("outline") == "none"
         and browsed.get("title") == ["H3", "Steps"] and browsed.get("step") == ["DIV", "Later."]
         and browsed.get("overview") == ["DIV", "Later."]),
        ("a link within the presentation takes focus to its place: a footnote's mark to its "
         "note, the note's way back to the mark, still a link with its outline, and a link to a "
         "slide to the slide's title",
         lambda: linked.get("note") == ["LI", "fn1", True, "none", "opening"]
         and linked.get("back") == ["A", "fnref1", False, "solid", "opening"]
         and linked.get("slide") == ["H3", "Steps", True, "none", "steps"]),
        ("links in #0066CC, underlined, the arrow back as plain as the arrow on, and no slide "
         "moving with reduced motion asked for",
         lambda: browsed.get("link") == ["rgb(0, 102, 204)", "underline"]
         and len(set(browsed.get("arrows", []))) == 1 and browsed["arrows"][0] != "0.3"
         and browsed.get("motion") == "0s"),
        ("a slide too tall is set closer and smaller to fit, as PowerPoint shrinks text, once "
         "its pictures are in, its title as it was, and one too tall at a quarter of its size "
         "scrolls",
         lambda: [f[:3] for f in browsed.get("fitted", []) if f[1] or f[2]]
         == [["A Big Picture", True, False], ["A Bit Long", True, False],
             ["A Long List", True, False], ["Too Long", True, True]]
         and all(f[4] <= 720 for f in browsed["fitted"] if not f[2])
         and [f[6] for f in browsed["fitted"] if f[0] == "A Bit Long"] == ["0.9"]
         and [f[3] for f in browsed["fitted"] if f[0] == "A Bit Long"] == ["1"]
         and 0.25 < float(next(f[3] for f in browsed["fitted"] if f[0] == "A Long List")) < 1
         and [f[3] + " " + f[7] + " " + str(f[8]) for f in browsed["fitted"] if f[2]]
         == ["0.25 auto 720"]
         and {f[5] for f in browsed["fitted"] if f[0] in ("A Long List", "Opening")}
         == {"57.75px"}
         and {f[9] for f in browsed["fitted"] if f[9]} == {"none"}),
        ("a slide too tall even then takes the up and down keys and space as a page does, the "
         "left and right keys going from slide to slide, and space still closes the overview",
         lambda: [scrolled.get(k, [None])[0] for k in ("right", "down", "overview", "space", "left")]
         == ["too-long", "too-long", "too-long", "too-long", "a-long-list"]
         and scrolled["down"][1] > 0 and scrolled["overview"][2] is True
         and scrolled["space"][2] is False),
        ("a fitted slide shown first is centered on its fitted height, though its fonts come "
         "after the page has loaded",
         lambda: isinstance(centered, list) and centered[0] == f"{(720 - centered[1]) / 2}px"),
        ("and a picture that never comes doesn't keep the slides from being fitted",
         lambda: isinstance(broken, list)
         and [f[:3] for f in broken if f[0] == "A Long List"] == [["A Long List", True, False]]),
        ("a narrow window shows the slide as a page that scrolls, at the slide's size, at the "
         "top and no wider than the window, its controls kept in view and its end clear of them, "
         "the left and right keys going from slide to slide",
         lambda: narrow.get("opened") == [True, "a-long-list", 0, "42px", ""]
         and narrow["placed"] == [0, True]
         and narrow["down"][1] == "a-long-list" and narrow["down"][2] > 0
         and narrow["controls"] is True and narrow["end"][0] == "a-long-list"
         and narrow["end"][1] > narrow["down"][2] and narrow["end"][2] is True
         and narrow["right"][1] == "too-long" and narrow["right"][2] == 0),
        ("and widened, the slides again",
         lambda: narrow.get("widened", [None])[0] is False
         and narrow["widened"][4].startswith("translate(-50%, -50%) scale(")),
        ("the page has no overview, which showed nothing there, and one open as the window "
         "narrows is closed",
         lambda: narrow.get("overview") is False and narrow.get("widened overview") is True
         and narrow.get("narrowed") == [True, "too-long", False]),
        ("the page scrolls to the place a link takes focus to and to a step as it appears, and "
         "a slide's page starts at its top, one with no title too",
         lambda: noted == ["fn2", True]
         and topped.get("step") == ["The step at its end.", "long-first", True]
         and topped.get("next") == [0, "SECTION", True]),
        ("a phone's page has text a page's size, at the slide its address names, at the top and "
         "no wider than the window, its end clear of the controls",
         lambda: phone.get("opened") == [True, "a-long-list", 0, "20px", ""]
         and phone["placed"] == [0, True] and phone["end"][1] > 0 and phone["end"][2] is True),
    ]
    if browser:
        # One line for them all, which says how many it stands for, as
        # run-all.sh counts it.
        print(f"  skip  {len(in_browser_checks)} checks of the presentations in a browser, which "
              f"need Python's Playwright and its Chromium, both optional: {browser}")
        return checks
    return checks + in_browser_checks


def case_revealjs_settings(work):
    """slides.notes visible and omitted, slides.aspect_ratio, slides.size and
    slides.reference_doc said unread, a book's revealjs target, the
    repository's copy of reveal.js and REVEALJS_DIR's in its place, a
    later release, reveal.js 5, and an empty folder, a Pandoc too old, and
    highlighted code."""
    unready = too_old("REVEALJS_PANDOC", "a deck's reveal.js presentation")
    problem = revealjs_ready()
    if problem:
        return [("a copy of reveal.js to build the presentations with: " + problem,
                 lambda: False)]
    visible_dir = folder(os.path.join(work, "visible"), "defaults:\n  pages:\n    "
                         "split_level: 2\n" + REVEALJS + "    slides:\n      "
                         "notes: visible\n      aspect_ratio: \"4:3\"\n      size: "
                         "on-screen-show\n", decks_given={"presented.md": PRESENTED})
    png(os.path.join(visible_dir, "img", "big.png"), 200, 120, 40, size=400)
    visible = convert(visible_dir, "--quick")
    shown = read(os.path.join(visible_dir, "present", "presented.html")) \
        if visible.returncode == 0 else ""
    # This deck has an include-after of its own, a closing line.
    omitted_dir = folder(os.path.join(work, "omitted"), REVEALJS + "    slides:\n      "
                         "notes: omitted\n", decks_given={"presented.md": PRESENTED.replace(
                             "author: A. Lecturer\n", "author: A. Lecturer\n"
                             "include-after: A closing line of the deck itself.\n")})
    png(os.path.join(omitted_dir, "img", "big.png"), 200, 120, 40, size=400)
    omitted = convert(omitted_dir, "--quick")
    left = read(os.path.join(omitted_dir, "present", "presented.html")) \
        if omitted.returncode == 0 else ""
    coded_dir = folder(os.path.join(work, "coded"), REVEALJS, decks_given={"code.md": SECTIONED})
    coded = convert(coded_dir, "--quick")
    code_page = read(os.path.join(coded_dir, "present", "code.html")) \
        if coded.returncode == 0 else ""
    book = os.path.join(work, "book")
    os.makedirs(book)
    write(os.path.join(book, "one.md"), "# A Page\n\nText.\n")
    write(os.path.join(book, "project.yaml"),
          "project:\n  identifier: org.example.book\n  title: A Book\n")
    write(os.path.join(book, "conversion.yaml"), REVEALJS + "  pages:\n    format: html\n")
    as_book = convert(book, "--quick")
    import revealtarget
    plain = folder(os.path.join(work, "plain"), REVEALJS, decks_given={"one.md": UNTITLED})
    unset = convert(plain, "--quick", env=dict(os.environ, REVEALJS_DIR=""))
    copied = sorted(os.path.relpath(os.path.join(root, name), os.path.join(
        plain, "present", "reveal.js")) for root, _, names in os.walk(
        os.path.join(plain, "present", "reveal.js")) for name in names) \
        if unset.returncode == 0 else []
    later = os.path.join(work, "reveal-later")
    shutil.copytree(revealtarget.VENDORED, later)
    write(os.path.join(later, "package.json"), '{"name": "reveal.js", "version": "6.9.0"}\n')
    shutil.rmtree(os.path.join(plain, "present"), ignore_errors=True)
    newer = convert(plain, "--quick", env=dict(os.environ, REVEALJS_DIR=later))
    five = os.path.join(work, "reveal5")
    shutil.copytree(revealtarget.VENDORED, five)
    write(os.path.join(five, "package.json"), '{"name": "reveal.js", "version": "5.2.1"}\n')
    older = convert(plain, "--quick", env=dict(os.environ, REVEALJS_DIR=five))
    empty = os.path.join(work, "empty")
    os.makedirs(empty)
    nothing = convert(plain, "--quick", env=dict(os.environ, REVEALJS_DIR=empty))
    tools = os.path.join(work, "tools")
    os.makedirs(tools)
    write(os.path.join(tools, "pandoc"), "#!/bin/sh\nif [ \"$1\" = --version ]; then echo "
          "'pandoc 3.11.0'; exit 0; fi\nexec %s \"$@\"\n" % shutil.which("pandoc"))
    os.chmod(os.path.join(tools, "pandoc"), 0o755)
    old = convert(plain, "--quick", env=dict(os.environ, PATH=tools + os.pathsep
                                             + os.environ["PATH"]))
    built = [
        ("slides.notes visible shows the notes under each slide, slides.aspect_ratio sets "
         "the shape, and the presentation is the whole deck, whatever cuts its pages",
         lambda: sorted(os.listdir(os.path.join(visible_dir, "present")))[-1] == "reveal.js"
         and [n for n in os.listdir(os.path.join(visible_dir, "present"))
              if n.endswith(".html")] == ["presented.html"]
         and "showNotes: true," in shown and '<aside class="notes">' in shown
         and "        width: 960,\n" in shown and "4:3 (slides.aspect_ratio) for 1" in visible.stderr
         and "speaker notes shown under each slide" in visible.stderr),
        ("slides.size isn't read for a presentation, and the run says so",
         lambda: "NOTE: slides.size isn't read for target present's presentations"
         in visible.stderr),
        ("slides.notes omitted leaves the notes out, and the run says so",
         lambda: omitted.returncode == 0 and left and '<aside class="notes">' not in left
         and "speaker notes left out" in omitted.stderr),
        ("a deck's own include-after is kept, the script after it, where Pandoc's option "
         "for the script had taken its place",
         lambda: "A closing line of the deck itself." in left
         and left.index("Reveal.initialize(") < left.index("A closing line of the deck itself.")
         < left.index("function pageView")),
        ("without REVEALJS_DIR the repository's copy of reveal.js goes beside the "
         "presentations, its license and its theme's font's with it, and nothing is noted",
         lambda: unset.returncode == 0 and "through Pandoc's reveal.js writer and reveal.js "
         "6.0.2, copied beside them" in unset.stderr and "NOTE: the presentations load"
         not in unset.stderr
         and copied == sorted(revealtarget.REVEALJS_FILES) == sorted(
             os.path.relpath(os.path.join(root, name), revealtarget.VENDORED)
             for root, _, names in os.walk(revealtarget.VENDORED) for name in names
             if name not in ("README.md", "package.json"))),
        ("REVEALJS_DIR's copy takes its place, and a release other than the repository's is "
         "noted, with the one the presentations' script was written against",
         lambda: newer.returncode == 0 and "and reveal.js 6.9.0, copied beside them" in newer.stderr
         and "NOTE: the presentations load REVEALJS_DIR's reveal.js 6.9.0, where the script "
         "that makes them readable with a screen reader (oer-reveal.js) was written against "
         "6.0.2, the repository's own copy" in newer.stderr),
        ("a folder that isn't reveal.js stops the run, what's missing named",
         lambda: nothing.returncode != 0 and f"REVEALJS_DIR is {empty}, which isn't a copy of "
         "reveal.js: it has no dist/reveal.js, dist/reveal.css, dist/reset.css, ..."
         in nothing.stderr and "Unset, the repository's own copy is used." in nothing.stderr),
        ("reveal.js 5 stops it too, its version named",
         lambda: older.returncode != 0 and "REVEALJS_DIR's reveal.js is 5.2.1, and the "
         "presentations are written for reveal.js 6" in older.stderr
         and "unset, the repository's own copy of reveal.js 6.0.2 is used" in older.stderr),
        ("a slide's highlighted code is in the theme's colors (lib/highlighting.py)",
         lambda: "code span.dv { color: %s; }" % highlight_color("DecVal") in code_page),
    ]
    # Said before a deck's presentation is built, whatever the Pandoc, or
    # of the repository's copy of reveal.js itself.
    before = [
        ("a book's revealjs target is refused, the rest written",
         lambda: as_book.returncode == 0 and "target present is format revealjs, which is "
         "written for decks written in Markdown" in as_book.stderr
         and not os.path.exists(os.path.join(book, "present"))),
        ("the repository's copy is reveal.js as its README names it, and one missing a file "
         "stops the run, saying a checkout has it and REVEALJS_DIR can name another",
         lambda: vendored_version() == ("6.0.2", "6.0.2")
         and vendored_problem("dist/plugin/zoom.js") == (
             "The repository's copy of reveal.js, vendor/reveal.js, is missing "
             "dist/plugin/zoom.js: a checkout of TextbookImprover has reveal.js 6 there, and "
             "REVEALJS_DIR can name the folder of another copy (see docs/installation.md).")
         and vendored_problem("package.json").startswith(
             "The repository's copy of reveal.js, vendor/reveal.js, is missing package.json:")),
        ("a Pandoc older than 3.12 is refused, its version named",
         lambda: old.returncode != 0 and "Pandoc 3.11.0 is too old for target present's "
         "presentations; 3.12 or later" in old.stderr),
    ]
    if unready:
        print(f"  skip  {len(built)} checks of the presentations' settings: {unready}")
        return before
    return built + before


CASES = [("the pieces", case_pieces),
         ("a folder of decks", case_folder),
         ("one alt text on a deck's different pictures", case_shared_alt),
         ("file names lowercased", case_lowercase_names),
         ("a formula in display style", case_display_style),
         ("pictures scaled down to a set number of times the width shown", case_downsample),
         ("the headings' levels on a page", case_levels),
         ("the implied target, and a book's Markdown", case_implied),
         ("pages per slide, and the notes", case_split),
         ("a deck's PDF", case_pdf),
         ("the PDF's settings", case_pdf_settings),
         ("an SVG the PDF can't show", case_svg),
         ("LaTeX that doesn't finish", case_timeout),
         ("LaTeX that doesn't settle", case_unsettled),
         ("a slide too wide", case_wide_slide),
         ("the template's fallbacks", case_fallbacks),
         ("no LuaLaTeX", case_no_latex),
         ("a deck's PowerPoint file", case_pptx),
         ("the PowerPoint files' settings", case_pptx_settings),
         ("what the PowerPoint writer can't do", case_pptx_edges),
         ("a deck's reveal.js presentation", case_revealjs),
         ("a deck in another language", case_languages),
         ("the presentations' settings", case_revealjs_settings)]
SLOW = ("a deck's PDF", "the PDF's settings", "the template's fallbacks")


def run_cases(cases):
    """The cases one after another, here: how many checks failed."""
    work = tempfile.mkdtemp(prefix="decks-tests-")
    failed = 0
    try:
        for label, case in cases:
            print(label)
            directory = os.path.join(work, re.sub(r"[^\w-]+", "-", label))
            try:
                checks = case(directory)
            except Exception as exc:
                print(f"  ERROR {label}: {type(exc).__name__}: {exc}")
                failed += 1
                continue
            for name, predicate in checks:
                try:
                    ok = predicate()
                except Exception as exc:
                    ok, name = False, f"{name}  ({type(exc).__name__}: {exc})"
                print(("  ok    " if ok else "  FAIL  ") + name)
                failed += not ok
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return failed


def main():
    parser = argparse.ArgumentParser(description="Check decks written in Markdown.")
    parser.add_argument("--case", action="append", default=[], metavar="LABEL",
                        help="run only the case with this label, as CASES names it; "
                             "may be given again")
    parallel.add_options(parser)
    arguments = parser.parse_args()
    if shutil.which("pandoc") is None:
        sys.exit("pandoc is not on the path.")
    version = subprocess.run(["pandoc", "--version"], capture_output=True,
                             text=True).stdout.split()[1]
    if tuple(int(p) for p in re.findall(r"\d+", version)[:3]) < (3, 9):
        sys.exit(f"Pandoc {version} is too old; these tests need 3.9 or "
                 "later, as convert.py does.")
    if arguments.case_index is not None:
        return min(run_cases([CASES[arguments.case_index]]), parallel.MOST)
    chosen = arguments.case
    cases = [c for c in CASES if not chosen or c[0] in chosen]
    if chosen and len(cases) != len(set(chosen)):
        sys.exit("no case is called " + ", ".join(
            repr(c) for c in chosen if c not in {label for label, _ in CASES}))
    if arguments.jobs > 1 and len(cases) > 1:
        failed = parallel.run(os.path.abspath(__file__), CASES, chosen,
                              arguments.jobs, first=SLOW)
    else:
        failed = run_cases(cases)
    print(f"\n{failed} check(s) failed across {len(cases)} case(s)"
          if failed else "\nall decks checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
