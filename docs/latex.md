# LaTeX sources

A LaTeX book is read through its master file, the one with `\documentclass` and `\begin{document}`, and every target makes its output from it as from any other source. Tested on the suite's own book and on Joseph Fields's [*A Gentle Introduction to the Art of Mathematics*](https://github.com/osj1961/giam) (GIAM), which is the test case for this work. The book's own PDF, made by LaTeX with tagging on, is not built yet; the `pdf` target makes one through Pandoc, as for any source.

## How a book is read

The master is the `.tex` file in the book's directory that is a whole document. When there's more than one, as when one set of chapters makes a textbook, a workbook, and a solutions manual, `latex.main` names the book's (GIAM's is `GIAM.tex`), and the run stops and says so until it does.

Pandoc reads the whole book through the master, following `\include` and `\input` from the book's directory, so the preamble's macros apply everywhere, a `\ref` gets the number LaTeX would give it, and a reference into another chapter resolves. The result is cut into pages where each `\include`-d file begins, each page named after its file (`\include{intro/intro}` is `intro`), as every other source's pages are. What the master holds itself before its first `\include` (a copyright page, acknowledgments) is a page named after the master. A `\ref` whose label is on another page links to that page.

With no `contents` declared, the run writes `contents-sample.yaml`: the pages in the master's order, each with the role `\frontmatter`, `\appendix`, or `\backmatter` before it gives it, and the title, authors, and language the preamble declares (babel's or polyglossia's main language, or `\DocumentMetadata`'s `lang`). Copy it into `project.yaml` to use it.

A `README.md` beside the master is the repository's, not a page.

## What is put right before reading

Pandoc's LaTeX reader (3.12) can't take some of what plain LaTeX books do, so the book is copied and the copy put right; the author's files are never written. Each of these was read in Pandoc's source and measured, and is described in `PANDOC-NOTES.md` in the repository, "The LaTeX reader":

- **ifthen's booleans** (`\newboolean`, `\setboolean`, `\ifthenelse{\boolean{...}}`) become etoolbox's toggles, which the reader evaluates. It drops `\ifthenelse`, both branches with it ([jgm/pandoc#11008](https://github.com/jgm/pandoc/issues/11008)). An `\ifthenelse` with any other condition is still dropped, and the run counts them.
- **`\input file`**, TeX's own form without braces, is braced. The reader stops on it.
- **`\centerline`** is read as a center environment. The reader takes its argument as inline text and stops on a table inside it.
- **An image named without its extension** is resolved the way graphicx resolves it (`.pdf`, then `.png`, `.jpg`, and the rest, then `.eps`), in the book's directory and `\graphicspath`. The reader looks in the copy, where it isn't.
- **A PDF or EPS image**, which no browser shows, is made an SVG of its first page with `pdftocairo` (EPS through `epstopdf` first).
- **A drawing**, a `picture`, `tikzpicture`, or `pspicture` environment, which the reader drops whole, is rendered by LaTeX with the book's own preamble and made an SVG; the copy includes the SVG in its place, so a figure keeps its caption and label. A run of drawings with nothing between them but comments and a `\setlength{\unitlength}`, which is what fig2dev's `pstex_t` output is, makes one image. The engine is pdfLaTeX unless the preamble needs LuaLaTeX (fontspec, unicode-math, polyglossia, `\DocumentMetadata`).
- **The `artifact` key** on `\includegraphics` makes the image decorative, as latex-lab does; the reader ignores the key.
- **Alt text** in an `alt` key is read as LaTeX (`50\%` is "50%"); the reader keeps it as typed. An image without one is reported in `image-alt-missing.csv` like any other; the reader would describe it as "image".
- **Formulas** texmath can't read, which then appear as their TeX: a size command in text inside math (`\mbox{\tiny noneg}`), a text command inside `\mbox` (`\mbox{\textsf R}`, `\mbox{{\bf c}}`), and a rule with no width (a strut) or no height (a space) are written as texmath reads them. A rule that shows is left, since it draws something only a person can name; see the next section.

The rendered images go in `rendered/` in the book's directory, at the path of the file they came from (`figures/Venn.tex` is `rendered/figures/Venn.svg`; a drawing in a chapter is `rendered/sets/sets-3.svg`). `rendered/.rendered.json` records what each was made from, so an unchanged drawing isn't made again. An image's alt text comes from `image-alt.csv` by that path, like any image's.

Drawings and PDF images need a LaTeX engine and `pdftocairo` (`sudo apt install poppler-utils`). Without them the run says so, and they're left out of the pages. A figure the book's own build makes (xfig through fig2dev, say) has to be made first; the run names any file the master reaches that isn't there.

## Definitions for reading: `latex-macros.tex`

Some macros draw what they mean. GIAM's "such that" is a bar drawn with `\rule`, and so is its restriction of a function to a set, and its blank to fill in is three rules. Read as written, each is a formula texmath can't read, or one a screen reader reads as nothing. Only a person can say what each means, once, in `latex-macros.tex` beside the master: LaTeX definitions read after the book's own preamble, for reading only. The book's own PDF never sees them. GIAM's:

```latex
% "Such that", drawn as a bar with \rule.
\renewcommand{\suchthat}{\mid}
% A function restricted to a set, drawn as a bar with \rule.
\renewcommand{\restrict}[2]{#1|_{#2}}
% A blank to fill in, drawn as three rules.
\renewcommand{\blnk}{\underline{\quad}}
```

The file's name is the `latex.macros` setting.

## What is lost

- **Index entries.** `\index` is dropped; the pages have no index.
- **A bibliography.** `\bibliography` names the `.bib` file, but no references list is made, and a `\cite` stays a citation key.
- **Macros defined in a package file beside the book.** The copy holds the `.tex` files the master reaches and no `.sty`, since Pandoc reading a drawing package's definitions (DraTex's) stopped it; a macro the book's own package defines is unknown to the reader, and its text is skipped.
- **Manual formatting**, `\raisebox` and visible rules in formulas, `\vspace` and `\newpage`, is dropped or left as TeX. On GIAM, 6 formulas of about 4,500.

## Measured on GIAM

From the repository at 167696e (2026-08-03), with its figures made by its own Makefile: 10 pages (the master's front matter and 9 chapters), read in about 15 seconds with its 93 drawings rendered, 19 references between chapters resolved, 21 `\ifthenelse`s and 10 PDF images put right. Of its formulas, texmath could read all but 313 as read; with the repairs above, all but 13, and with the three definitions above, all but 6. The HTML and the EPUB pass epubcheck and the Nu checker but for what the book itself lacks: alt text on its 104 images and descriptions for its tables.
