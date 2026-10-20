"""
pagefooter.py -- the footer setting, for the targets that aren't pages.

The footer setting is Markdown placed at the bottom of every page, or the
name of a file holding it. An HTML page takes it as a <footer> after its
content, rendered once by convert.py and put in by the template, its
pictures and all. What "every page" is differs by format, and so does
what the footer can hold; outside an HTML page, a picture is its
alternative text and a link to one of the book's own files its words,
since a target carries neither file, a heading is a paragraph, and an id
is left out (_ast):

    epub3     every content document but the cover and the navigation
              document, its last child a <footer> (xhtml), as a page's is
    pdf       every page, below what the page style puts in the foot,
    latex     centered in small type (latex): LaTeX's tagging marks the
              foot an artifact, so a link there would be an annotation
              outside the structure tree, and a link is its words
    docx      every page of every file, in the file's own footer part
              (paragraphs): its words, a paragraph each
    markdown  the end of every file's text, its notes after it in
    asciidoc  Markdown, in a div of class oer-footer (document), which
              target-blocks.lua adds before the target's filters run, so
              it's written as the page is: in AsciiDoc, an open block
              with that role (markdown-source.lua). Reading a file back
              as a source takes a div of that class at its end out
              again, whoever wrote it, since the target's own setting
              puts it back (figures-and-tables.lua).

A source target's copy, the author's own file, gets none: it writes only
what a person decided. OpenStax asks that a copy of one of its books say
"Access for free at openstax.org." on every page, physical or digital,
and unpack-cnx.py sets the footer for every target to say it.

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

import json
import os
import re
import subprocess

# A link's target with a scheme, which a page that isn't the book's own
# HTML can follow: a relative one names a file the target doesn't carry.
ABSOLUTE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")

# The elements whose first field is their attributes, whose ids the
# footer's copies on every page mustn't repeat; a table's parts have
# theirs too (table_parts).
ATTRIBUTED = ("Div", "Span", "Code", "CodeBlock", "Link", "Table", "Figure")

# The white space a Word footer's line runs together: not a no-break
# space, nor any other the plain writer keeps as a character.
SPACES = re.compile(r"[ \t\r\f\v]+")


def named_file(text, base):
    """The file a header or footer setting names, when it's one line that
    is a file's path relative to the book's folder; otherwise None, and
    the setting is Markdown."""
    text = str(text or "").strip()
    if not text or "\n" in text:
        return None
    candidate = os.path.join(base, text)
    return os.path.abspath(candidate) if os.path.isfile(candidate) else None


def markdown(value, base):
    """The setting's Markdown, from the file it names when it names one;
    None when there's nothing to say."""
    text = str(value or "")
    path = named_file(text, base)
    if path:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    return text if text.strip() else None


def _pandoc(arguments, text):
    result = subprocess.run(["pandoc"] + arguments, input=text,
                            capture_output=True, text=True, check=True)
    return result.stdout


def html(value, base):
    """The footer rendered from its Markdown, raw HTML and all; None when
    there's nothing to say."""
    text = markdown(value, base)
    if text is None:
        return None
    out = _pandoc(["-f", "markdown-implicit_figures", "-t", "html5"], text).strip()
    return out or None


def _ast(value, base, links=True):
    """The footer's AST as its rendered HTML reads, which makes raw HTML
    Pandoc's own elements, so what's written from it is well-formed (a
    <footer> the setting is already is read as what it holds): each
    picture its alternative text, and each link to a file of the book's
    its words, since an EPUB carries only the files its chapters name and
    a target's folder only those its pages do; each note left out; each
    heading a paragraph, which no outline or contents takes in; no id
    repeated on every page; and, without links, every link its words.
    None when nothing's left."""
    rendered = html(value, base)
    if rendered is None:
        return None
    doc = json.loads(_pandoc(["-f", "html", "-t", "json"], rendered))

    def walk(node):
        if isinstance(node, list):
            out = []
            for item in node:
                kind = item.get("t") if isinstance(item, dict) else None
                if kind == "Image" or (kind == "Link" and not (
                        links and ABSOLUTE.match(item["c"][2][0]))):
                    out.extend(walk(item["c"][1]))
                elif kind == "Note":
                    continue
                elif kind == "Header":
                    out.append({"t": "Para", "c": walk(item["c"][2])})
                else:
                    out.append(walk(item))
            return out
        if isinstance(node, dict):
            node = {k: walk(v) for k, v in node.items()}
            if node.get("t") in ATTRIBUTED:
                node["c"][0][0] = ""
            if node.get("t") == "Table":
                for attributes in table_parts(node["c"]):
                    attributes[0] = ""
            return node
        return node

    doc["blocks"] = walk(doc["blocks"])
    plain = _pandoc(["-f", "json", "-t", "plain"], json.dumps(doc))
    return doc if plain.strip() else None


def table_parts(content):
    """The attributes of a table's head, bodies, foot, rows, and cells,
    from its content: [attr, caption, colspecs, head, bodies, foot]."""
    _, _, _, head, bodies, foot = content
    found = [head[0], foot[0]] + [body[0] for body in bodies]
    rows = head[1] + foot[1] + [row for body in bodies for row in body[2] + body[3]]
    for row in rows:
        found.append(row[0])
        found.extend(cell[0] for cell in row[1])
    return found


def document(value, base):
    """The footer as a Pandoc document in JSON, its links links, for a
    Markdown or AsciiDoc target's files to end with (target-blocks.lua);
    None when there's nothing to say."""
    doc = _ast(value, base)
    return json.dumps(doc) if doc is not None else None


def xhtml(value, base):
    """The footer as an EPUB's content document holds it: well-formed, its
    links links, in a <footer>; None when there's nothing to say."""
    doc = _ast(value, base)
    if doc is None:
        return None
    out = _pandoc(["-f", "json", "-t", "html5"], json.dumps(doc)).strip()
    return "<footer>\n%s\n</footer>" % out


def latex(value, base):
    """The footer as LaTeX for a page's foot, its paragraphs apart, each
    link its words; None when there's nothing to say."""
    doc = _ast(value, base, links=False)
    if doc is None:
        return None
    out = _pandoc(["-f", "json", "-t", "latex", "--wrap=none"], json.dumps(doc)).strip()
    return out or None


def paragraphs(value, base):
    """The footer's paragraphs as plain text, for a Word file's footer,
    each link its words, a line break in one a newline (with --wrap=none
    the plain writer breaks a line nowhere else), a no-break space kept."""
    doc = _ast(value, base, links=False)
    if doc is None:
        return []
    out = _pandoc(["-f", "json", "-t", "plain", "--wrap=none"], json.dumps(doc))
    found = []
    for paragraph in re.split(r"\n[ \t\r\f\v]*\n", out):
        lines = [SPACES.sub(" ", line).strip(" ") for line in paragraph.split("\n")]
        lines = [line for line in lines if line]
        if lines:
            found.append("\n".join(lines))
    return found


# The page style patch a PDF and a LaTeX target's master carry: each of
# LaTeX's page styles (empty, plain, headings, myheadings, and fancyhdr's
# when a metadata file loads it) wraps its foot in a box of two lines,
# what the style puts there and the footer under it, centered in small
# type, so the title page, a chapter's opening page, and a blank page get
# it too. The footer is a small line's space under the foot's line, empty
# or not, set single-spaced whatever a metadata file's linestretch makes
# the text, so it stays the same height on every page, and in the bottom
# margin a layout gives it. Its size is the class's \footnotesize, which
# the title page's \maketitle makes \small for its own notes. The class's
# current style is wrapped at once; selecting a style again wraps its own
# foot, once. A foot that's wrapped already isn't wrapped again, as
# fancyhdr's \fancypagestyle{plain}[fancy] would have it, plain's own
# wrapping after fancy's, which would make the foot its own content until
# TeX ran out of memory; and a foot inside a wrapped one, as fancyhdr's
# odd foot gives its even one on an even page when fancyhdr is twoside
# and the class isn't, is set as it is. LaTeX's tagging marks the foot an
# artifact, as it does a page number.
LATEX_FOOT = r"""\makeatletter
\newcommand\OERFooterText{%s}
\NewCommandCopy\OER@footnotesize\footnotesize
\newif\ifOER@infoot
\newcommand\OER@footline[1]{%%
  \ifOER@infoot #1\else
  \vtop{\OER@infoottrue\hsize\textwidth
    \hb@xt@\textwidth{#1}%%
    \def\baselinestretch{1}\OER@footnotesize
    \hb@xt@\textwidth{\hfil\parbox[t]{\textwidth}{\centering
      \OERFooterText}\hfil}}\fi}
\def\OER@wrappedodd{\OER@footline\OER@oddfoot}
\def\OER@wrappedeven{\OER@footline\OER@evenfoot}
\newcommand\OER@addfooter{%%
  \ifx\@oddfoot\OER@wrappedodd\else
    \let\OER@oddfoot\@oddfoot \let\@oddfoot\OER@wrappedodd\fi
  \ifx\@evenfoot\OER@wrappedeven\else
    \let\OER@evenfoot\@evenfoot \let\@evenfoot\OER@wrappedeven\fi}
\@for\OER@style:={empty,plain,headings,myheadings,fancy,fancyplain}\do{%%
  \@ifundefined{ps@\OER@style}{}{%%
    \expandafter\g@addto@macro\csname ps@\OER@style\endcsname\OER@addfooter}}
\OER@addfooter
\makeatother
"""


def latex_preamble(value, base):
    """What a PDF's preamble takes to put the footer on every page, or
    an empty string."""
    text = latex(value, base)
    return LATEX_FOOT % text if text else ""
