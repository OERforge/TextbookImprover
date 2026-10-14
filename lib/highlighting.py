"""
highlighting.py -- the colors highlighted code is drawn in, in every format.

Pandoc highlights code in the pygments style unless told otherwise, and
some of its colors are too light for WCAG's 4.5:1 against a page
(SC 1.4.3): a comment's #60a0b0 is 2.89:1 on #fdfdfd, Pandoc's page
background, and numbers, attributes, preprocessor lines, special
strings, and errors fall short too, in a page, an EPUB, a PDF, a Word
file, a PowerPoint file, and a reveal.js presentation alike. So every
writer that highlights code is given bin/highlighting.theme (ARGS):
pygments, each of those colors darkened to 4.6:1 or more on #fdfdfd,
its hue and chroma kept (its lightness moved in OKLCH), and the rest
pygments' own. A line number's #aaaaaa, 2.28:1, is #737373.

The dark modes Pandoc 3.12's stylesheets follow, a page's on #1a1a1a
and an EPUB's on #232629, need lighter colors than any one theme can
give, and page.css, which both carry, gives each token's pair with
light-dark(): this theme's color, then one lightened the same way to
4.6:1 on #232629, the lighter of the two. The unit suite holds the two
to each other and both to 4.5:1, and the convert suite holds them to
the backgrounds the stylesheets Pandoc writes give.

Pandoc writes the CSS that lays out highlighted code and colors it only
on a page that holds code when it writes it, so a page given code
afterwards, a note notes.py moved there, gets it from with_page_css.

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

import os
import re
import subprocess

THEME = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      os.pardir, "bin", "highlighting.theme"))

# Pandoc 3.8's option, which the oldest Pandoc the run takes (3.9) has.
ARGS = ["--syntax-highlighting=" + THEME]

# What Pandoc writes before the CSS for highlighted code, in the style
# element of a page or an EPUB's chapter file.
CSS_MARK = "/* CSS for syntax highlighting */"
_PAGE_CSS = []


def page_css():
    """The CSS Pandoc's HTML and EPUB writers put in a page that holds
    highlighted code, in this theme's colors: how a line of code and a
    line's number are laid out, and each token's color. A page with none
    gets none, so a page whose code arrives after Pandoc has written it
    (a note notes.placement moved there) is given it (with_page_css).
    Asked of Pandoc once, from a page of one line of code; "" if it
    can't be."""
    if not _PAGE_CSS:
        try:
            done = subprocess.run(["pandoc", "-f", "markdown", "-t", "html5", "--standalone",
                                   "--metadata", "title=code"] + ARGS,
                                  input="```python\nx = 1\n```\n", capture_output=True,
                                  text=True)
            found = re.search(re.escape(CSS_MARK) + r"\n(.*?)\s*</style>", done.stdout, re.S)
            _PAGE_CSS.append(found.group(1) if found else "")
        except OSError:
            _PAGE_CSS.append("")
    return _PAGE_CSS[0]


def with_page_css(text):
    """A page, or an EPUB's chapter file, with page_css() at the end of
    its first style element, where Pandoc writes it on a page holding
    code, when it holds highlighted code and hasn't the CSS; else as it
    is. A page with no style element is given one."""
    if 'class="sourceCode' not in text or CSS_MARK in text:
        return text
    css = page_css()
    head = text.find("</head>")
    if not css or head < 0:
        return text
    block = "\n    " + CSS_MARK + "\n" + css
    end = text.find("</style>", 0, head)
    if end < 0:
        return text[:head] + "  <style>" + block + "\n  </style>\n" + text[head:]
    start = end
    while start and text[start - 1] in " \t\r\n":
        start -= 1
    return text[:start] + block + text[start:]
