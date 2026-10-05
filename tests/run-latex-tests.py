#!/usr/bin/env python3
"""
run-latex-tests.py -- check LaTeX as a source, end to end through convert.py.

    python3 tests/run-latex-tests.py           # run every case
    python3 tests/run-latex-tests.py --keep    # leave the output in place

Needs Pandoc 3.9 or later. The drawing and the PDF image need a LaTeX
engine and pdftocairo; without them those checks are skipped and say so.

WHAT IS LOAD-BEARING HERE

The book is written by this script: a master that \\include-s four
chapters, two of them in folders, with the constructs Pandoc's reader
(3.12) can't take, each put right on a copy before reading
(lib/latexsource.py): an ifthen boolean, \\input without braces, a table
inside \\centerline, a picture environment, an image named without its
extension, a PDF image, an artifact, alt text holding LaTeX, and a
formula with \\mbox{\\tiny ...}. Each check would fail without the repair
it names; the author's files are checked unchanged afterwards, since
everything happens on a copy.

The page cut is checked against the master's \\include-s, the roles
against its division commands, and a \\ref into another chapter against
the page the label is on.

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
import hashlib
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

MASTER = r"""\documentclass{book}
\usepackage[english]{babel}
\usepackage{ifthen}
\usepackage{graphicx}
\usepackage{amssymb}
\usepackage{tikz}
\newboolean{Solutions}
\setboolean{Solutions}{false}
\newcommand{\Znoneg}{{\mathbb Z}^{\mbox{\tiny noneg}}}
\newcommand{\relR}{\mbox{\textsf R}}
\newcommand{\suchthat}{\; \rule[-3pt]{.5pt}{13pt} \;}
\newcommand{\weird}{\mbox{\raisebox{2pt}{$\star$}}}
\title{A Test Book}
\author{A. Author}
\begin{document}
\AddToShipoutPictureBG{\begin{tikzpicture}[remember picture,overlay]
\draw (0,0) -- (1,1);\end{tikzpicture}}
\maketitle
\frontmatter
Copyright 2026 A. Author. This front matter is the master's own.

\include{preface}
\mainmatter
\include{ch1/one}
\include{ch2/two}
\appendix
\include{answers}
\end{document}
"""

PREFACE = r"""\chapter*{Preface}
A preface.
"""

ONE = r"""\chapter{One}
\label{ch:one}
\section{First}
\label{sec:first}
\ifthenelse{\boolean{Solutions}}{SOLUTION TEXT}{EXERCISE TEXT}

\input ch1/table

\begin{figure}
\begin{picture}(40,20)
\put(0,0){\line(1,0){40}}
\put(5,5){$x$}
\end{picture}
\caption{A line}
\label{fig:line}
\end{figure}

Images: \includegraphics[alt={50\% shaded}]{img/square.png}
and \includegraphics{img/square} and
\includegraphics[artifact]{img/rule.png} and
\includegraphics{img/diagram.pdf}.

Sets: $\Znoneg$ and $a \relR b$ and $\{x \suchthat x > 0\}$, and
$a\hspace{10mm}b$, and $a \weird b$.

\begin{enumerate}
\item An item with a formula:
\[ x^2 + 1 \]
and more after it.
\item An item with a table:

\begin{tabular}{cc}
p & q \\
\end{tabular}

and text after it.
\item A blank to fill in:

\hrule

\item Nested:
\begin{enumerate}
\item A nested blank:

\hrule

\item Another nested item, with a blank too:

\hrule

\end{enumerate}
\item A quotation in an item:
\begin{quote}
Let $x$ be odd. Then
\[ x = 2k + 1 \]
for some integer $k$.
\end{quote}
\item The next item.
\end{enumerate}

\begin{figure}
\begin{tabular}{cc}
1 & 2 \\
\end{tabular}
\caption{A table set as a figure}
\end{figure}

\begin{quote}
Proof: a table follows.

\begin{tabular}{ccl}
 & $A \cup B$ & \rule{36pt}{0pt} Given \\
$=$ & $U \cap (A \cup B)$ & Identity law \\
 & \begin{minipage}{2in}A boxed aside.\end{minipage} & \\
\end{tabular}

Q.E.D.
\end{quote}

\tagpdfsetup{table/header-rows={1}}
\begin{tabular}{cc}
Head one & Head two \\
x & y \\
\end{tabular}
% \input{ch1/never}
\begin{verbatim}
\input ch1/never
\end{verbatim}
"""

TABLE = r"""\centerline{\begin{tabular}{cc}
alpha & beta \\ \cline{2-2}
gamma & delta \\
\end{tabular}}
"""

TWO = r"""\chapter{Two}
\begin{picture}(10,10)\undefinedcommandhere\end{picture}

See Section~\ref{sec:first} and Figure~\ref{fig:line}, in
Chapter~\ref{ch:one}.
"""

ANSWERS = r"""\chapter{Answers}
Answers.
"""

MACROS = r"""% For reading only: "such that" is drawn with \rule.
\renewcommand{\suchthat}{\mid}
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


def pdf(path):
    """A one-page PDF holding a blue rectangle, written by hand."""
    stream = b"0 0 1 rg 5 5 30 10 re f\n"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 40 20] "
               b"/Contents 4 0 R >>",
               b"<< /Length %d >>\nstream\n" % len(stream) + stream
               + b"endstream"]
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, xref)
    with open(path, "wb") as fh:
        fh.write(out)


def write_book(work, macros=False, second_master=False, readme=True,
               epub=False):
    os.makedirs(os.path.join(work, "ch1"))
    os.makedirs(os.path.join(work, "ch2"))
    os.makedirs(os.path.join(work, "img"))
    files = {"book.tex": MASTER, "preface.tex": PREFACE, "ch1/one.tex": ONE,
             "ch1/table.tex": TABLE, "ch2/two.tex": TWO,
             "answers.tex": ANSWERS}
    if macros:
        files["latex-conversion-macros.tex"] = MACROS
    if second_master:
        files["workbook.tex"] = MASTER.replace("{false}", "{true}")
    if readme:
        files["README.md"] = "# The repository\n\nNot a page.\n"
    for name, text in files.items():
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    png(os.path.join(work, "img", "square.png"), (90, 90, 90))
    png(os.path.join(work, "img", "rule.png"), (0, 0, 0))
    pdf(os.path.join(work, "img", "diagram.pdf"))
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n"
                 + ("  epub:\n    format: epub3\n  word:\n    format: docx\n"
                    if epub else ""))


def fingerprint(work):
    """The author's files, by content: everything but what a run writes."""
    found = {}
    for top, _, names in os.walk(work):
        for name in names:
            path = os.path.join(top, name)
            if name.endswith((".tex", ".png", ".pdf", ".md")) and \
                    not name.endswith("-sample.tex") and \
                    "rendered" not in path and "html" not in path \
                    and os.sep + "back" + os.sep not in path:
                with open(path, "rb") as fh:
                    found[os.path.relpath(path, work)] = \
                        hashlib.sha256(fh.read()).hexdigest()
    return found


def convert(work):
    return subprocess.run(
        ["python3", os.path.join(BIN, "convert.py"), "--quiet"], cwd=work,
        capture_output=True, text=True, stdin=subprocess.DEVNULL)


def read(work, *parts):
    with open(os.path.join(work, *parts), encoding="utf-8") as fh:
        return fh.read()


def epub_links_resolve(work):
    """Every #fragment link in the EPUB names an id one of its files has."""
    import zipfile
    with zipfile.ZipFile(os.path.join(work, "epub", "book.epub")) as z:
        texts = [z.read(n).decode("utf-8") for n in z.namelist()
                 if n.endswith(".xhtml")]
    ids = set()
    for text in texts:
        ids.update(re.findall(r'\sid="([^"]+)"', text))
    targets = set()
    for text in texts:
        targets.update(re.findall(r'href="[^"#]*#([^"]+)"', text))
    return "page-one" in ids and targets and targets <= ids


def word_list_reads_back(work):
    """one.docx, read back as a source, gives the list whole: the table
    and the rule inside their items, and every item in one list."""
    back = os.path.join(work, "back")
    os.makedirs(back, exist_ok=True)
    shutil.copy(os.path.join(work, "word", "one.docx"), back)
    with open(os.path.join(back, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    convert(back)
    page = read(back, "html", "one.html")
    lists = re.findall(r"<ol[^>]*>(.*?)</ol>", page, re.S)
    whole = [l for l in lists if "An item with a formula" in l]
    outer = page[page.find("An item with a formula"):]
    outer = outer[:outer.find("The next item") + 1]
    return whole and "The next item" in page and "<table" in outer \
        and outer.count("<hr") >= 3 and "and text after it" in outer \
        and "Another nested item" in outer and "for some integer" in outer \
        and len(re.findall(r"<ol", page[page.find("An item with a formula"):
                                       page.find("The next item")])) == 1


def word_quote_reads_back(work):
    """The quotation holding a table, read back from one.docx (which
    word_list_reads_back converted), is one quotation with the table in it,
    and no cell is a quotation."""
    page = read(work, "back", "html", "one.html")
    quotes = re.findall(r"<blockquote>(.*?)</blockquote>", page, re.S)
    proof = [q for q in quotes if "Proof: a table follows" in q]
    return proof and "<table" in proof[0] and "Q.E.D." in proof[0] \
        and not any(("Given" in q or "boxed aside" in q) and "<table" not in q
                    for q in quotes)


def word_math_in_list(work):
    """The Word file's display formula in a list item is numbered as the
    item's other paragraphs are, so reading it keeps the item whole."""
    import zipfile
    with zipfile.ZipFile(os.path.join(work, "word", "one.docx")) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    paragraphs = re.findall(r"<w:p>.*?</w:p>", xml, re.S)
    formula = [p for p in paragraphs if "oMathPara" in p and "x" in p]
    return formula and all('<w:numId w:val="1000"' in p for p in formula) \
        and "tiqMath" not in xml


def can_draw():
    return bool((shutil.which("pdflatex") or shutil.which("lualatex"))
                and shutil.which("pdftocairo"))


SKIPPED = []


def skip(reason):
    """A check that can't run here: reported, and passing."""
    if reason not in SKIPPED:
        SKIPPED.append(reason)
        print(f"  skip  {reason}")
    return True


def case_book(work):
    """The whole book: pages, roles, repairs, references."""
    write_book(work, macros=True, epub=True)
    before = fingerprint(work)
    result = convert(work)
    log = result.stdout + result.stderr
    one = read(work, "html", "one.html") \
        if os.path.exists(os.path.join(work, "html", "one.html")) else ""
    two = read(work, "html", "two.html") \
        if os.path.exists(os.path.join(work, "html", "two.html")) else ""
    import yaml
    sample = yaml.safe_load(read(work, "contents-sample.yaml")) \
        if os.path.exists(os.path.join(work, "contents-sample.yaml")) else {}
    project = (sample or {}).get("project", {})
    sample_text = read(work, "latex-conversion-macros-sample.tex") \
        if os.path.exists(os.path.join(work,
                                       "latex-conversion-macros-sample.tex")) else ""
    missing_alt = read(work, "image-alt-missing.csv") \
        if os.path.exists(os.path.join(work, "image-alt-missing.csv")) else ""
    return [
        ("the master's \\include-s are the pages, the master's own text one more",
         lambda: all(os.path.exists(os.path.join(work, "html", n + ".html"))
                     for n in ("book", "preface", "one", "two", "answers"))),
        ("a README beside the master is the repository's, not a page",
         lambda: not os.path.exists(os.path.join(work, "html", "README.html"))),
        ("the contents sample follows the master, roles from its divisions",
         lambda: project.get("contents") == [
             {"page": "book", "role": "front"},
             {"page": "preface", "role": "front"}, "one", "two",
             {"page": "answers", "role": "appendix"}]),
        ("and takes the title, author, and babel's language from the preamble",
         lambda: project.get("title") == "A Test Book"
         and project.get("authors") == ["A. Author"]
         and project.get("language") == "en"),
        ("an ifthen boolean is evaluated: one branch, not both or neither",
         lambda: "EXERCISE TEXT" in one and "SOLUTION TEXT" not in one),
        ("\\input without braces is read, and a table inside \\centerline",
         lambda: "<table" in one and "delta" in one),
        ("\\cline's column range is a rule, not a cell's text",
         lambda: "delta" in one and "2-2" not in one),
        ("a rule with no height is a space, not a line across the page",
         lambda: "<hr" not in re.sub(r"(?s)A blank to fill in.*?The next item", "", one)),
        ("an \\input in a comment or verbatim is left alone",
         lambda: "\\input ch1/never" in one
         and "reaches ch1/never" not in log),
        ("alt text holding LaTeX is read as LaTeX",
         lambda: 'alt="50% shaded"' in one),
        ("an image named without its extension is found",
         lambda: 'src="img/square.png"' in one),
        ("and, with no alt key, is reported rather than described as \"image\"",
         lambda: "img/square.png" in missing_alt and 'alt="image"' not in one),
        ("an artifact is decorative",
         lambda: re.search(r'<img src="img/rule\.png"[^>]*alt=""', one)
         and 'aria-hidden="true"' in one),
        ("a drawing LaTeX can't make costs only itself",
         lambda: "1 of the book's 2 drawing(s)" in log
         and os.path.exists(os.path.join(work, "rendered", "ch1", "one-1.svg"))
         if can_draw() else skip("no LaTeX or pdftocairo: drawings not rendered")),
        ("a drawing is rendered whole and keeps its figure's caption",
         lambda: re.search(r'<figure[^>]*>\s*<img src="rendered/ch1/one-1\.svg"',
                           one) and "A line" in one
         if can_draw() else skip("no LaTeX or pdftocairo: drawings not rendered")),
        ("a PDF image is made an SVG",
         lambda: 'src="rendered/img/diagram.svg"' in one
         if can_draw() else skip("no LaTeX or pdftocairo: drawings not rendered")),
        ("\\mbox{\\tiny ...} and \\mbox{\\textsf R} reach MathML",
         lambda: all("raisebox" in line for line in log.splitlines()
                     if "Could not convert TeX math" in line)
         and "noneg" in one and "<math" in one),
        ("the definitions sample lists what's left for a person, not what's defined",
         lambda: "\\weird" in sample_text and "\\renewcommand{\\suchthat}"
         not in sample_text),
        ("a length in mm inside a formula reaches MathML",
         lambda: "10mm" not in one),
        ("the author's tagging header declaration is the table's",
         lambda: re.search(r'<th[^>]*scope="col"[^>]*>Head one', one)),
        ("an overlay drawn on every page isn't a drawing of the text",
         lambda: not os.path.exists(os.path.join(work, "rendered", "book.svg"))
         and not os.path.exists(os.path.join(work, "rendered", "book-1.svg"))),
        ("latex-conversion-macros.tex is read after the preamble: \\suchthat as \\mid",
         lambda: "∣" in one or "&#x2223;" in one or "|</mo>" in one),
        ("a \\ref into another chapter goes to the page the label is on",
         lambda: 'href="one.html#sec:first"' in two
         and 'href="one.html#fig:line"' in two),
        ("with the numbers LaTeX would give",
         lambda: re.search(r'href="one.html#sec:first"[^>]*>1\.1<', two)),
        ("in the EPUB, a \\ref to a chapter's own \\label goes to the chapter",
         lambda: epub_links_resolve(work)),
        ("in Word, a formula inside a list item stays in the item",
         lambda: word_math_in_list(work)),
        ("read back from Word, a list with a formula, a table, and a rule in its items is whole",
         lambda: word_list_reads_back(work)),
        ("read back from Word, a quotation holding a table is whole, its cells not quotations",
         lambda: word_quote_reads_back(work)),
        ("a figure holding a table is reported as a Word loss",
         lambda: "figure-table" in (read(work, "fidelity.csv")
                                    if os.path.exists(os.path.join(work, "fidelity.csv")) else "")),
        ("the author's files are untouched",
         lambda: fingerprint(work) == before),
    ]


def case_masters(work):
    """Two masters: latex.main decides, and without it the run stops."""
    write_book(work, second_master=True, readme=False)
    stopped = convert(work)
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("defaults:\n  latex:\n    main: workbook.tex\n"
                 "targets:\n  html:\n    format: html\n")
    chosen = convert(work)
    sample = read(work, "latex-conversion-macros-sample.tex") \
        if os.path.exists(os.path.join(work,
                                       "latex-conversion-macros-sample.tex")) else ""
    one = read(work, "html", "one.html") \
        if os.path.exists(os.path.join(work, "html", "one.html")) else ""
    return [
        ("two masters and no latex.main stop the run, naming both",
         lambda: stopped.returncode != 0
         and "book.tex" in stopped.stderr + stopped.stdout
         and "workbook.tex" in stopped.stderr + stopped.stdout
         and "latex.main" in stopped.stderr + stopped.stdout),
        ("with no definitions file, a drawn bar is suggested as \\mid",
         lambda: "\\renewcommand{\\suchthat}{\\mid}" in sample
         and "% \\renewcommand{\\weird}{}" in sample),
        ("latex.main picks the master, and its boolean holds",
         lambda: "SOLUTION TEXT" in one and "EXERCISE TEXT" not in one),
    ]


def case_single(work):
    """A document that \\include-s nothing is one page."""
    os.makedirs(work)
    with open(os.path.join(work, "notes.tex"), "w", encoding="utf-8") as fh:
        fh.write("\\documentclass{article}\n\\begin{document}\n"
                 "\\section*{1.0 Review}\nText.\n\\section*{1.1 Parts}\n"
                 "More.\n\\end{document}\n")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    result = convert(work)
    page = os.path.join(work, "html", "notes.html")
    return [
        ("a document that includes nothing is one page, its sections in it",
         lambda: os.path.exists(page) and "1.1 Parts" in read(work, "html",
                                                               "notes.html")
         and "one page" in result.stdout + result.stderr),
    ]


def case_unbuilt(work):
    """A file the book's own build makes, not made yet: the run stops."""
    os.makedirs(os.path.join(work, "figures"))
    with open(os.path.join(work, "notes.tex"), "w", encoding="utf-8") as fh:
        fh.write("\\documentclass{article}\n\\begin{document}\nText.\n"
                 "\\input{figures/venn.tex}\n\\end{document}\n")
    with open(os.path.join(work, "figures", "Makefile"), "w") as fh:
        fh.write("all:\n\tfig2dev -L pstex_t venn.fig > venn.tex\n")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    result = convert(work)
    said = result.stdout + result.stderr
    return [
        ("a file the book's own build makes, missing, stops the run",
         lambda: result.returncode != 0 and "figures/venn.tex" in said
         and "figures/Makefile" in said and "Nothing was converted" in said
         and not os.path.exists(os.path.join(work, "html"))),
    ]


CASES = [("a LaTeX book", case_book), ("two masters", case_masters),
         ("one file", case_single), ("an unbuilt book", case_unbuilt)]


def main():
    parser = argparse.ArgumentParser(
        description="Check LaTeX as a source, end to end.")
    parser.add_argument("--keep", action="store_true",
                        help="leave the built output in place")
    arguments = parser.parse_args()
    if shutil.which("pandoc") is None:
        sys.exit("pandoc is not on the path.")
    work = tempfile.mkdtemp(prefix="latex-tests-")
    failed = 0
    try:
        for label, case in CASES:
            directory = os.path.join(work, re.sub(r"[^\w-]+", "-", label))
            try:
                checks = case(directory)
            except Exception as exc:
                print(f"  ERROR {label}: {exc}")
                failed += 1
                continue
            for name, predicate in checks:
                try:
                    passed = bool(predicate())
                except Exception as exc:
                    passed, name = False, f"{name}  ({exc})"
                print(("  ok    " if passed else "  FAIL  ") + name)
                failed += not passed
    finally:
        if arguments.keep:
            print(f"\nOutput left in {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
    print(f"\n{failed} check(s) failed across {len(CASES)} case(s)"
          if failed else "\nall LaTeX checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
