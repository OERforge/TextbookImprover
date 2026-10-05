# LaTeX sources

A LaTeX book is read through its master file, the one with `\documentclass` and `\begin{document}`, and every target makes its output from it as from any other source. Tested on the suite's own book, on Joseph Fields's [*A Gentle Introduction to the Art of Mathematics*](https://github.com/osj1961/giam) (GIAM), a book of nine chapters that is the test case for this work, and on a set of calculus note templates in one file, already tagged by its author, which has to keep converting cleanly as the rest grows. The book's own PDF, made by LaTeX with tagging on, is not built yet; the `pdf` target makes one through Pandoc, as for any source.

## How a book is read

The master is the `.tex` file in the book's directory that is a whole document. When there's more than one, as when one set of chapters makes a textbook, a workbook, and a solutions manual, `latex.main` names the book's (GIAM's is `GIAM.tex`), and the run stops and says so until it does.

A document that `\include`s nothing is one page, named after its file; its sections can be split into pages of their own ([Splitting pages](splitting.md)).

Pandoc reads the whole book through the master, following `\include` and `\input` from the book's directory, so the preamble's macros apply everywhere, a `\ref` gets the number LaTeX would give it, and a reference into another chapter resolves. The result is cut into pages where each `\include`-d file begins, each page named after its file (`\include{intro/intro}` is `intro`), as every other source's pages are. What the master holds itself before its first `\include` (a copyright page, acknowledgments) is a page named after the master. A `\ref` whose label is on another page links to that page.

With no `contents` declared, the run writes `contents-sample.yaml`: the pages in the master's order, each with the role `\frontmatter`, `\appendix`, or `\backmatter` before it gives it, and the title, authors, and language the preamble declares (babel's or polyglossia's main language, or `\DocumentMetadata`'s `lang`). Copy it into `project.yaml` to use it.

A `README.md` beside the master is the repository's, not a page.

## What is put right before reading

Pandoc's LaTeX reader (3.12) can't take some of what plain LaTeX books do, so the book is copied and the copy put right; the author's files are never written. Each of these was read in Pandoc's source and measured, and is described in `PANDOC-NOTES.md` in the repository, "The LaTeX reader":

- **ifthen's booleans** (`\newboolean`, `\setboolean`, `\ifthenelse{\boolean{...}}`) become etoolbox's toggles, which the reader evaluates. It drops `\ifthenelse`, both branches with it ([jgm/pandoc#11008](https://github.com/jgm/pandoc/issues/11008)). An `\ifthenelse` with any other condition is still dropped, and the run counts them.
- **`\input file`**, TeX's own form without braces, is braced. The reader stops on it.
- **`\centerline`** is read as a center environment. The reader takes its argument as inline text and stops on a table inside it.
- **`\cline{2-3}` and `\cmidrule{2-3}`** become whole rules. The reader leaves their column range in the next cell as text.
- **A table's header declaration for LaTeX's tagging**, `\tagpdfsetup{table/header-rows={1}}` or `table/header-columns={1}` (or both) just before the table, is the table's declaration here too, as a `table-headers.csv` row or a Markdown marker would be; the reader drops `\tagpdfsetup`. A declaration naming more than the first row or column is counted and left for `table-headers.csv`.
- **An image named without its extension** is resolved the way graphicx resolves it (`.pdf`, then `.png`, `.jpg`, and the rest, then `.eps`), in the book's directory and `\graphicspath`. The reader looks in the copy, where it isn't.
- **A PDF or EPS image**, which no browser shows, is made an SVG of its first page with `pdftocairo` (EPS through `epstopdf` first).
- **A drawing**, a `picture`, `tikzpicture`, or `pspicture` environment, which the reader drops whole, is rendered by LaTeX with the book's own preamble and made an SVG; the copy includes the SVG in its place, so a figure keeps its caption and label. A run of drawings with nothing between them but comments and a `\setlength{\unitlength}`, which is what fig2dev's `pstex_t` output is, makes one image. The engine is pdfLaTeX unless the preamble needs LuaLaTeX (fontspec, unicode-math, polyglossia, `\DocumentMetadata`). A `tikzpicture` drawn as an `overlay`, a rule down every page from `\AddToShipoutPictureBG` say, belongs to the page and not the text, and is left alone.
- **The `artifact` key** on `\includegraphics` makes the image decorative, as latex-lab does; the reader ignores the key.
- **Alt text** in an `alt` key is read as LaTeX (`50\%` is "50%"); the reader keeps it as typed. An image without one is reported in `image-alt-missing.csv` like any other; the reader would describe it as "image".
- **Formulas** texmath can't read, which then appear as their TeX: a size command in text inside math (`\mbox{\tiny noneg}`), a text command inside `\mbox` (`\mbox{\textsf R}`, `\mbox{{\bf c}}`), a length in millimeters (`\hspace{40mm}`; texmath knows em, pt, in, and cm), a length set inside a formula (`\setlength\tabcolsep` in an `array`), and a rule with no width (a strut) or no height (a space) are written as texmath reads them. A rule that shows is left, since it draws something only a person can name; see the next section.

The rendered images go in `rendered/` in the book's directory, at the path of the file they came from (`figures/Venn.tex` is `rendered/figures/Venn.svg`; a drawing in a chapter is `rendered/sets/sets-3.svg`). `rendered/.rendered.json` records what each was made from, so an unchanged drawing isn't made again. An image's alt text comes from `image-alt.csv` by that path, like any image's.

Drawings and PDF images need a LaTeX engine and `pdftocairo` (`sudo apt install poppler-utils`). Without them the run says so, and they're left out of the pages. When LaTeX can't make one drawing, the others are made one at a time, so it costs only itself.

## A book with a build of its own

Some books make part of their LaTeX with another program first: GIAM draws its figures in xfig, and its Makefile has fig2dev write each as a `.tex` file and a PDF. The conversion reads LaTeX, so that build runs first, and what it makes is the conversion's input. When the master reaches a file that isn't there, the run stops before converting anything, names the files, and points at any `Makefile` beside the master or the missing files.

## Definitions for reading: `latex-conversion-macros.tex`

The book's own definitions are always read, and this file never replaces them in the book: it is read after them, by the conversion only, and changes what a macro means only for the pages the conversion writes. Some macros draw what they mean. GIAM's "such that" is a bar drawn with `\rule`, and so is its restriction of a function to a set, and its blank to fill in is three rules. Read as written, each is a formula texmath can't read, or one a screen reader reads as nothing. Only a person can say what each means, once, in `latex-conversion-macros.tex` beside the master: LaTeX definitions read after the book's own preamble, for reading only. The book's own PDF never sees them. GIAM's:

```latex
% "Such that", drawn as a bar with \rule.
\renewcommand{\suchthat}{\mid}
% A function restricted to a set, drawn as a bar with \rule.
\renewcommand{\restrict}[2]{#1|_{#2}}
% A blank to fill in, drawn as three rules.
\renewcommand{\blnk}{\underline{\quad}}
```

The file's name is the `latex.macros` setting.

**The run writes a starting point**, `latex-conversion-macros-sample.tex`, whenever any of the book's macros (defined with `\newcommand` and its kin, and used in a formula) still gives a formula texmath can't make MathML of, once the repairs above and the definitions file are applied. Each is listed with how often formulas use it and the book's own definition. Where its drawing has one reading, the sample suggests a definition, kept only if texmath then reads it: a thin tall rule is a vertical bar (`\mid` when only spacing surrounds it, so GIAM's `\suchthat`), and flat rules with nothing but ticks and spacing beside them are a blank to fill in (`\underline{\quad}`). The rest are left as a commented-out `\renewcommand` for a person to fill in, as GIAM's `\nrelR`, an R struck through with a raised `\not`, is. Check the sample, then save it as `latex-conversion-macros.tex` or merge it into yours; it's never read as it stands. With nothing left to list, a stale sample is removed.

## The source target

`format: source` writes the book's own `.tex` files back, every one the master reaches, at the same paths under the target's folder, so the folder can be laid over the author's tree. What it writes into them is only what a person decided in the sidecars, at the element each decision was made about, and the rest is as the author wrote it, comments and all. So far that's alt text: each image and drawing in the image-alt sidecar gets the `alt` key LaTeX's tagging reads, or `artifact` for `[decorative]`, beside the author's own keys (`\includegraphics[alt={A gray square},width=1cm]{sq}`, `\begin{picture}[alt={Two boxes}](40,20)`, `\begin{tikzpicture}[alt={...},scale=2]`). A drawing is found as the conversion named it (its file, and its place among the file's drawings), an image by the file graphicx would include; anything in a comment or verbatim text is left alone. fig2dev's pair of picture environments is one drawing: the first gets the alt text, and the second, which holds its labels, is marked `artifact` so it isn't a figure of its own. A `pspicture` has no such key; it's counted and left alone.

The keys don't change an untagged build. With TeX Live 2026, `pdflatex` builds a document using all three with no error or warning, and with `\DocumentMetadata{tagging=on}` and LuaLaTeX each becomes its figure's `/Alt` in the PDF's structure and the artifact image isn't a figure at all (checked in the structure tree). On GIAM, with a placeholder description for each of its 102 images and drawings, 99 of its 154 files change, and the copy laid over the author's tree builds with the book's own `pdflatex GIAM` to the same 424 pages as the original.

**A file the book's build makes** can be written into, but building again writes over it: 93 of GIAM's drawings are in files fig2dev makes from xfig sources. A file beside a same-named `.fig` is counted as one, and the run says how many of its changes are in such files. Until the book's own build carries the alt text (an xfig comment it passes through, say), the copy is a version whose build is this one.

Still to come: the book's language and `\DocumentMetadata`, which needs the book to build with LuaLaTeX (GIAM has three pdfTeX-only lines); table headers from the table-headers sidecar, as `\tagpdfsetup{table/header-rows=...}`; and definitions from `latex-conversion-macros.tex`, as changes to the author's own.

## What is lost

- **Index entries.** `\index` is dropped; the pages have no index.
- **A bibliography.** `\bibliography` names the `.bib` file, but no references list is made, and a `\cite` stays a citation key.
- **Macros defined in a package file beside the book.** The copy holds the `.tex` files the master reaches and no `.sty`, since Pandoc reading a drawing package's definitions (DraTex's) stopped it; a macro the book's own package defines is unknown to the reader, and its text is skipped.
- **Manual formatting**, `\raisebox` and visible rules in formulas, `\vspace` and `\newpage`, is dropped or left as TeX. On GIAM, 6 formulas of about 4,500.

## Measured

**GIAM**, from the repository at 167696e (2026-08-03), with its figures made by its own Makefile (which needs fig2dev; the run doesn't make them, and names any it can't find): 10 pages (the master's front matter and 9 chapters), read in about 15 seconds with its 93 drawings rendered, 19 references between chapters resolved, 21 `\ifthenelse`s and 10 PDF images put right. Of about 4,500 formulas, texmath couldn't read 313 as read, and 6 with the repairs above and the three definitions in `latex-conversion-macros.tex`. The HTML and the EPUB pass epubcheck, and the Nu checker finds what the book itself lacks (alt text on its 104 images) and a footnotes section with no heading (Pandoc's own) on each page that has notes. The PDF, through Pandoc, takes about ten minutes for 281 pages; veraPDF finds 4 rules failed in a few places (a figure's two captions, one paragraph inside another, content directly in a section) besides the images' missing alt text.

**The calculus notes** (870 lines, one file, `extarticle`, already tagged by their author and passing PDF/UA-2): one page, about 430 formulas, all made MathML; the author's header declaration on its one table carried through; HTML and EPUB with nothing found by the output check, epubcheck, or the Nu checker; the PDF through Pandoc passing veraPDF; and the Word file, read back, with the same headings, lists, table, formulas, and links.
