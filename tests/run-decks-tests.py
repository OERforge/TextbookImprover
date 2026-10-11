#!/usr/bin/env python3
"""
run-decks-tests.py -- check decks written in Markdown: a folder of them
as slides, each deck's page, its Markdown and source copies, and its PDF
through ltx-talk.

    python3 tests/run-decks-tests.py

Needs Pandoc 3.9 or later. The PDF's cases need LuaLaTeX with LaTeX
2026-06-01 or later and the ltx-talk, lua-unicode-math, and
newcomputermodern packages, and pikepdf and pypdf to read what was built,
and skip, saying why, without them; veraPDF, found as the output check
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
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))
import parallel  # noqa: E402
import decks  # noqa: E402

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

[^i]: In a description, which LaTeX leaves out.
[^h]: The head's note.
[^c]: The caption's note.
[^p]: The title's note.
[^q]: The body's note.
[^w]: The wrapped slide's note.
[^z]: The last note.
[^y]: The inner table's note.
"""

# What beamer and LaTeX's other classes read and ltx-talk didn't: a
# footnote in a caption, a table, and a slide's title, struck text, a
# passage in another language, code that shows a frame, a frame option
# ltx-talk has no key for, beamer's own command in header-includes, and
# a color named as xcolor's dvipsnames name it.
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

# Code

```
\\begin{frame}{Hello}
\\begin{columns}[T]
\\end{frame}
```

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
    """(level, text) of each heading on a page, the title block's too."""
    found = []
    for level, text in re.findall(r"<h([1-6])[^>]*>(.*?)</h\1>", page, re.S):
        found.append((int(level), " ".join(html.unescape(re.sub(r"<[^>]+>", "", text)).split())))
    return found


def rows_of(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.reader(fh))[1:]


# --------------------------------------------------------------------------
# the pieces
# --------------------------------------------------------------------------

def header(level, text="Title"):
    return {"t": "Header", "c": [level, ["", [], []], [{"t": "Str", "c": text}]]}


def para(text="Text."):
    return {"t": "Para", "c": [{"t": "Str", "c": text}]}


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
    doc = {"meta": {}, "blocks": [header(1), para(), header(1), para()]}
    declared = {"meta": {"slide-level": {"t": "MetaString", "c": "2"}},
                "blocks": [header(1), para()]}
    return [
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


def case_split(work):
    work = folder(work, SPLIT, decks_given={"sectioned.md": SECTIONED})
    result = convert(work, "--quick")
    split = os.path.join(work, "split")
    piece = read(os.path.join(split, "sectioned--a-footnote.html")) \
        if os.path.exists(os.path.join(split, "sectioned--a-footnote.html")) else ""
    bare = read(os.path.join(work, "bare", "sectioned.html"))
    return [
        ("pages.split_level cuts a deck into a page per slide, its sections groups",
         lambda: result.returncode == 0 and sorted(
             n for n in os.listdir(split) if n.endswith(".html")) == [
             "sectioned--a-footnote.html", "sectioned--opening.html",
             "sectioned--some-code.html"]),
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


def colors(path, page):
    """The fill colors a page's content sets."""
    with pikepdf.open(path) as pdf:
        content = pdf.pages[page].Contents
        data = b"".join(c.read_bytes() for c in (
            content if isinstance(content, pikepdf.Array) else [content]))
    return set(re.findall(rb"([\d.]+ [\d.]+ [\d.]+) rg", data))


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
    """Why the PDF's cases can't run here, or None."""
    problem = decks.ltx_talk_problem()
    if problem:
        return problem
    if pikepdf is None or pypdf is None:
        return "pikepdf and pypdf are needed to read the PDFs built"
    return None


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


def shape_of(path):
    box = pypdf.PdfReader(path).pages[0].mediabox
    return float(box.width) / float(box.height)


def heading_elements(path):
    """Each heading element in the structure, in reading order: its level
    (through the role maps), whether it holds content of its own, its
    ActualText, and the text of the page its content is on."""
    found = []
    with pikepdf.open(path) as pdf:
        root = pdf.Root.StructTreeRoot
        maps = [root.get("/RoleMap") or {}] + [ns.get("/RoleMapNS") or {}
                                               for ns in root.get("/Namespaces") or []]
        pages = {page.objgen: n for n, page in enumerate(pdf.pages)}
        texts = [page.extract_text() or "" for page in pypdf.PdfReader(path).pages]

        def standard(name):
            for _ in range(4):
                for mapping in maps:
                    mapped = mapping.get(name)
                    if mapped is not None:
                        name = mapped[0] if isinstance(mapped, pikepdf.Array) else mapped
                        break
                else:
                    break
            return str(name)

        def walk(element):
            if isinstance(element, pikepdf.Array):
                for kid in element:
                    walk(kid)
                return
            if not isinstance(element, pikepdf.Dictionary) or "/S" not in element:
                return
            kind = standard(element.S)
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
        maps = [root.get("/RoleMap") or {}] + [ns.get("/RoleMapNS") or {}
                                               for ns in root.get("/Namespaces") or []]

        def standard(name):
            for _ in range(4):
                for mapping in maps:
                    mapped = mapping.get(name)
                    if mapped is not None:
                        name = mapped[0] if isinstance(mapped, pikepdf.Array) else mapped
                        break
                else:
                    break
            return str(name)

        def walk(element, inside):
            nonlocal found
            if isinstance(element, pikepdf.Array):
                for kid in element:
                    walk(kid, inside)
                return
            if not isinstance(element, pikepdf.Dictionary) or "/S" not in element:
                return
            kind = standard(element.S)
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


def case_pdf(work):
    problem = pdf_ready()
    if problem:
        print(f"  skip  {problem}; a deck's PDF isn't checked")
        return []
    svg = shutil.which("rsvg-convert")
    work = folder(work, PDF, decks_given={
        "Flat Deck.md": FLAT, "untitled.md": UNTITLED, "agenda.md": AGENDA, "odd.md": ODD,
        "nested.md": NESTED, "more.md": MORE, "subsections.md": SUBSECTIONS,
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
    check = rows_of(os.path.join(work, "output-check.csv"))
    ran = verapdf()
    if not ran:
        print("  skip  veraPDF not found (set VERAPDF); the PDFs' claims aren't judged")
    flat_text, sectioned_text = text_of(flat), text_of(sectioned)
    agenda_text, odd_text, more_text = text_of(agenda), text_of(odd), text_of(more)
    levels = lambda path: [h[0] for h in heading_elements(path)]  # noqa: E731
    checks = [
        ("a PDF of each deck, the whole deck however its pages are cut",
         lambda: result.returncode == 0 and sorted(os.listdir(os.path.join(work, "pdf"))) == [
             "Flat-Deck.pdf", "agenda.pdf", "more.pdf", "nested.pdf", "odd.pdf",
             "sectioned.pdf", "subsections.pdf", "untitled.pdf"]
         and "Wrote 8 PDF(s)" in out),
        ("a slide's title is an H1, or an H2 in a section, and a section's an H1",
         lambda: levels(flat) == [1, 1, 1, 1] and levels(sectioned) == [1, 2, 2, 1, 2]),
        ("a slide before the first section is an H1, as a section is, and bookmarked"
         " beside the sections, one in another language by its words",
         lambda: levels(agenda) == [1, 1, 2, 1, 2] and outline(agenda) == [
             ("Agenda", []), ("Supply", [("The Curve", [])]),
             ("Profit: MR = MC", [("The Rule", [])])]),
        ("sections at ## are LaTeX's sections, their slides H2s under H1s",
         lambda: levels(subsections) == [1, 2, 1, 2] and outline(subsections) == [
             ("Part A", [("Slide One", [])]), ("Part B", [("Slide Two", [])])]),
        ("two levels of sections nest, in the headings and the bookmarks",
         lambda: levels(nested) == [1, 2, 3, 2, 3, 1, 2] and outline(nested) == [
             ("Part One", [("Chapter A", [("Slide A1", [])]), ("Chapter B", [("Slide B1", [])])]),
             ("Part Two", [("Slide C1", [])])]),
        ("a slide's bookmark leaves out its title's footnote",
         lambda: ("A Claim", []) in outline(odd)),
        ("a slide in a div is a slide: bookmarked, its title's footnote set",
         lambda: ("Wrapped Slide", []) in outline(more) and "Wrapped Slide5" in more_text
         and "5The wrapped" in more_text),
        ("a heading in a quotation is bold text in its slide, which stays an H1 among H1s",
         lambda: levels(more) == [1] * 9 and "Quoted heading" in more_text
         and "Quoted big heading" in more_text),
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
         lambda: "Temporary page" not in flat_text + sectioned_text + agenda_text),
        ("each slide with a title is bookmarked, under its section, once though it pauses",
         lambda: outline(flat) == [("Value Is Subjective", []), ("Specialization => Growth", []),
                                   ("A Chart", []), ("Market Demand", [])]
         and outline(sectioned) == [("Part One", [("Opening", []), ("Some Code", [])]),
                                    ("Part Two", [("A Footnote", [])])]),
        ("the title slide has the deck's title, subtitle, authors, and institute",
         lambda: all(words in sectioned_text for words in (
             "Sections and Slides", "A conference talk", "B. Speaker", "A University"))),
        ("speaker notes aren't in the PDF",
         lambda: "Ask what the class would pay" not in flat_text
         and "Notes for part two" not in sectioned_text),
        ("a title with > keeps it: the bold face lacks it, and another face supplies it",
         lambda: "Specialization => Growth" in flat_text and "Missing character" not in out
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
    ]
    if ran:
        checks.insert(1, ("veraPDF finds nothing to fail in any of them",
                          lambda: not [r for r in check if r[1].startswith("verapdf")]))
    return checks


def case_pdf_settings(work):
    problem = pdf_ready()
    if problem:
        print(f"  skip  {problem}; a deck's PDF settings aren't checked")
        return []
    work = folder(work, "targets:\n  pdf:\n    format: pdf\n    pdf:\n      standard: [ua-1]\n"
                  "    slides:\n      aspect_ratio: \"5:4\"\n",
                  decks_given={"sectioned.md": SECTIONED, "agenda.md": AGENDA})
    result = convert(work)
    built = os.path.join(work, "pdf", "sectioned.pdf")
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
    ]
    if ran:
        checks.insert(1, ("veraPDF passes them as PDF/UA-1: the footnote's mark no link, "
                          "the agenda's heading an H1",
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
    run needs before LaTeX, and nothing else."""
    tools = os.path.join(work, "bin")
    os.makedirs(tools)
    for program in keep:
        found = shutil.which(program)
        if found:
            os.symlink(found, os.path.join(tools, program))
    os.symlink(sys.executable, os.path.join(tools, "python3"))
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


CASES = [("the pieces", case_pieces),
         ("a folder of decks", case_folder),
         ("the headings' levels on a page", case_levels),
         ("the implied target, and a book's Markdown", case_implied),
         ("pages per slide, and the notes", case_split),
         ("a deck's PDF", case_pdf),
         ("the PDF's settings", case_pdf_settings),
         ("an SVG the PDF can't show", case_svg),
         ("LaTeX that doesn't finish", case_timeout),
         ("no LuaLaTeX", case_no_latex)]
SLOW = ("a deck's PDF", "the PDF's settings")


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
