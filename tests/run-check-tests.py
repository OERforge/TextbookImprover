#!/usr/bin/env python3
"""
run-check-tests.py -- check the output checker.

    python3 tests/run-check-tests.py

Each check is exercised by a page that breaks it and, where it matters,
one that does not: the checker's job is to find what is wrong, and a
finding on a correct page is as bad as silence on a wrong one. The EPUB
half builds a small book with Pandoc and breaks a link inside the
archive by hand, since the assembler would not write one.

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

import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, HERE)
import fakeverapdf  # noqa: E402
import outputcheck  # noqa: E402
import pandocversion  # noqa: E402
import pdfcheck  # noqa: E402

GOOD = """<!DOCTYPE html><html lang="en"><head><title>A page</title></head>
<body><h1 id="top">Top</h1><h2>Second</h2>
<h2><img src="z.png" alt="A described figure"></h2>
<img src="x.png" alt="A thing"><img src="y.png" alt="" aria-hidden="true">
<div class="table-wrapper" tabindex="0" role="region" aria-label="Data">
<table><caption>Data</caption><tr><th scope="col">H</th></tr><tr><td>1</td></tr></table></div>
<div class="table-wrapper" tabindex="0" role="region" aria-label="Revenue">
<table><caption>Revenue</caption><tr><th scope="col">Revenue, <math><semantics><mi>p</mi><annotation encoding="application/x-tex">p</annotation></semantics></math></th>
<th scope="col"><img src="h.png" alt="Height"> <math><mi>h</mi></math></th><th scope="col"><math><mi>q</mi></math> per day</th></tr>
<tr><td>1</td><td>2</td><td>3</td></tr></table></div>
<table role="presentation"><tr><th><math><mi>z</mi></math></th><td>layout</td></tr></table>
<a href="#top">up</a><a href="other.html#there">over</a>
<a href="https://example.org/#x">out</a><p>A formula <math><mi>x</mi></math>, and one in MathJax's form <span class="math inline">\\(y\\)</span>, as Sphinx writes one <span class="math notranslate nohighlight">\\(z\\)</span>.</p><p><a href="other.html" aria-label="Read more about cats">Read more</a> <a href="other.html" aria-label="Chart of sales, larger"><img src="c.png" alt="Chart of sales"></a> <a href="other.html">no label</a> <a href="other.html" class="footnote-back" aria-label="Back to reference 1">&#x21A9;&#xFE0E;</a></p>
</body></html>"""

OTHER = """<!DOCTYPE html><html lang="en"><head><title>Other</title></head>
<body><h1 id="there">There</h1></body></html>"""

BAD = """<!DOCTYPE html><html><head><title></title></head>
<body><h1 id="a">A</h1><h3 id="a">Skipped</h3><h2 id="two words"></h2>
<img src="p.png"><img src="q.png" alt=""><img src="media/db-locked.png" alt="db locked">
<img src="r.png" alt="IMG_2041"><img src="s.png" alt="A dog on a lawn Description automatically generated">
<img src="t.png" alt="Marketing Mix Explained | Quizlet"><img src="u.png" alt="Figure 2 (fig2.png)">
<img src="v.png" alt="By Jane Roe - Own work, CC BY-SA 4.0, https://commons.wikimedia.org/w/index.php?curid=1">
<table><tr><td>1</td></tr></table>
<div class="table-wrapper" tabindex="0" role="region" aria-label="Demand">
<table><caption>Demand</caption><tr><th scope="col"><math display="inline"><semantics><msub><mi>q</mi><mi>d</mi></msub><annotation encoding="application/x-tex">q_d</annotation></semantics></math></th>
<th scope="col"> <math><mi>p</mi></math> </th><th scope="col">Price</th></tr>
<tr><th scope="row"><math><mi>r</mi></math><th scope="row">Rate</th></tr></table></div>
<a href="#nowhere">x</a><a href="gone.html">y</a><a href="other.html#no">z</a>
<a href="other.html" aria-label="DOI for Klein and Stern 2005">https://doi.org/10/b8xx35</a>
<a href="other.html" aria-label="Note two">2</a>
<p><span class="math inline">$x_{2}\\text{\\cdot}x_{n}$</span></p>
<p><span class="math" data-display="block">x
  2</span></p>
</body></html>"""

# An EPUB document whose table holds another in a cell: the outer
# header has words, the inner one only a formula.
NESTED = """<html xmlns="http://www.w3.org/1999/xhtml" lang="en"><head><title>N</title></head>
<body><table><tr><th>Words, <math xmlns="http://www.w3.org/1998/Math/MathML"><mi>w</mi></math></th>
<th><math xmlns="http://www.w3.org/1998/Math/MathML"><mi>v</mi></math> per day</th>
<th><img src="i.png" alt="Income"/><math xmlns="http://www.w3.org/1998/Math/MathML"><mi>i</mi></math></th></tr>
<tr><td><table><tr><th><math
xmlns="http://www.w3.org/1998/Math/MathML"><semantics><mi>y</mi><annotation
encoding="application/x-tex">y</annotation></semantics></math></th></tr></table></td></tr></table>
<table role="presentation"><tr><th><math xmlns="http://www.w3.org/1998/Math/MathML"><mi>z</mi></math></th></tr></table>
</body></html>"""

# A link in an EPUB document whose words are a picture's and the text
# after it, some in an element inside another.
LABELED = """<html xmlns="http://www.w3.org/1999/xhtml" lang="en"><head><title>L</title></head>
<body><p><a href="x.xhtml" aria-label="Sales"><img src="c.png" alt="Chart"/> of <span><em>sales</em></span></a></p>
</body></html>"""

# Two layout tables marked role="none", ARIA's other name for
# presentation: one with no header cell or caption, one whose header cell
# is a formula, neither in a scroll region.
LAYOUT_NONE = OTHER.replace("</h1>", '</h1><table role="none"><tr><td>Subtract 3.</td>'
                            '<td>x = 4</td></tr></table><table role="none"><tr><th><math>'
                            '<mi>z</mi></math></th><td>layout</td></tr></table>')

# The formula Pandoc couldn't convert, and one it couldn't read, on a page
# whose script may render them.
SCRIPTED = OTHER.replace("</h1>", "</h1><p><span class=\"math inline\">$x_{2}\\text{\\cdot}$"
                         "</span> <span class=\"math\">x2</span></p>"
                         "<script src=\"mathjax.js\"></script>")

# Formulas texmath can't read, a script of one part and a fraction of one,
# which Pandoc's HTML reader keeps as their text, and one it can read.
KEPT = """<!DOCTYPE html><html lang="en"><head><title>Kept</title></head>
<body><h1>Kept</h1><p>Read <math><msup><mi>x</mi></msup></math>, then
<math display="block"><mfrac><mn>1</mn></mfrac></math> and <math><mi>y</mi></math>.</p>
</body></html>"""


def checks(findings):
    return sorted(f.check for f in findings)


def fail(message):
    raise AssertionError(message)


def expect(condition, findings):
    """A failed expectation shows what the checker actually returned."""
    if not condition:
        raise AssertionError("got: " + "; ".join(
            f"{f.where} {f.check} {f.detail[:300]}" for f in findings)
            if findings else "got no findings")
    return True


def main():
    work = tempfile.mkdtemp(prefix="check-tests-")
    failed = 0
    try:
        for name, markup in (("good.html", GOOD), ("other.html", OTHER),
                             ("bad.html", BAD)):
            with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
                fh.write(markup)
        good = outputcheck.check_html_files(
            [os.path.join(work, "good.html"), os.path.join(work, "other.html")])
        # Pages titled with their files' names, and one whose title is its
        # name as a word, which is no file's name.
        named = {"ch_intro_to_data.html": "ch_intro_to_data", "tTable.html": "tTable",
                 "preface.html": "preface", "Intro.html": "Intro",
                 "Self-Assessment.html": "Self-Assessment"}
        for name, title in named.items():
            markup = OTHER.replace("<title>Other</title>", f"<title>{title}</title>") \
                .replace('id="there"', 'id="t-%s"' % name[:2])
            if name == "Self-Assessment.html":
                markup = markup.replace(">There</h1>", ">Self-Assessment</h1>")
            with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
                fh.write(markup)
        titled = outputcheck.check_html_files([os.path.join(work, n) for n in named])
        bad = outputcheck.check_html_files(
            [os.path.join(work, "bad.html"), os.path.join(work, "other.html")])
        with open(os.path.join(work, "none.html"), "w", encoding="utf-8") as fh:
            fh.write(LAYOUT_NONE)
        none = outputcheck.check_html_files([os.path.join(work, "none.html")])
        with open(os.path.join(work, "scripted.html"), "w", encoding="utf-8") as fh:
            fh.write(SCRIPTED)
        scripted = outputcheck.check_html_files([os.path.join(work, "scripted.html")])
        # A reveal.js presentation's links within it are reveal.js's routes,
        # #/ and an id, or a slide's place, which a page's aren't.
        routes = ('<a href="#/one">1</a> <a href="#/one/2">2</a> <a href="#/3/1">3</a> '
                  '<a href="#/gone">4</a>')
        with open(os.path.join(work, "presented.html"), "w", encoding="utf-8") as fh:
            fh.write(OTHER.replace('<h1 id="there">', '<div class="reveal"><section id="one">'
                                   '<h1 id="there">').replace("</body>", routes
                                                              + "</section></div></body>"))
        with open(os.path.join(work, "routed.html"), "w", encoding="utf-8") as fh:
            fh.write(OTHER.replace("</body>", '<a href="#/there">1</a></body>'))
        presented = outputcheck.check_html_files([os.path.join(work, "presented.html")])
        routed = outputcheck.check_html_files([os.path.join(work, "routed.html")])
        # One alt text on three images, two of them one picture in two
        # files, and on a picture another check names; a picture and its
        # copy with one alt text; a decorative image; an image elsewhere.
        os.makedirs(os.path.join(work, "pics", "m"))
        for name, data in (("a.png", b"one"), ("m/b.png", b"two"), ("c.png", b"one"),
                           ("d.png", b"three"), ("e.png", b"three")):
            with open(os.path.join(work, "pics", name), "wb") as fh:
                fh.write(data)
        for name, body in (
                ("one.html", '<img src="a.png" alt="A rising line"><img src="m/b.png" '
                             'alt="a rising line."><img src="d.png" alt="Two dots">'
                             '<img src="r.png" alt="IMG_2041"><img src="f.png" alt="IMG_2041">'),
                ("two.html", '<img src="c.png" alt="A rising line"><img src="e.png" '
                             'alt="Two dots"><img src="g.png" alt="A rising line" '
                             'aria-hidden="true"><img src="https://example.org/h.png" '
                             'alt="Two dots">')):
            with open(os.path.join(work, "pics", name), "w", encoding="utf-8") as fh:
                fh.write(OTHER.replace("</h1>", "</h1>" + body).replace(
                    'id="there"', 'id="t-%s"' % name[:3]))
        alike = outputcheck.check_html_files([os.path.join(work, "pics", n)
                                              for n in ("one.html", "two.html")])
        # A name no file system takes, which can't be read to be compared.
        with open(os.path.join(work, "pics", "nul.html"), "w", encoding="utf-8") as fh:
            fh.write(OTHER.replace("</h1>", '</h1><img src="a%00.png" alt="A falling line">'
                                   '<img src="b.png" alt="A falling line">'))
        unnamed = outputcheck.check_html_files([os.path.join(work, "pics", "nul.html")])
        cases = [
            ("a correct pair of pages produces no finding",
             lambda: checks(good) == []),
            ("every check fires on the page that breaks it",
             lambda: checks(bad) == sorted([
                 "no-lang", "no-title", "duplicate-id", "invalid-id",
                 "heading-skips-level",
                 "empty-heading", "image-without-alt",
                 "image-empty-alt-not-decorative",
                 "image-alt-is-file-name", "image-alt-is-file-name",
                 "image-alt-placeholder", "image-alt-auto-generated", "image-alt-page-title",
                 "image-alt-credit",
                 "link-label-without-text", "link-label-without-text",
                 "table-without-headers-or-caption",
                 "table-not-in-scroll-region", "table-without-data-cells",
                 "link-to-missing-fragment", "link-to-missing-file",
                 "link-to-missing-fragment", "formula-shown-as-tex",
                 "formula-kept-as-text",
                 "table-header-is-formula", "table-header-is-formula",
                 "table-header-is-formula"])),
            # By the rules a deck's pictures are judged by (alttext.py).
            ("alt text that says nothing is named with why, and so is one holding a file's name",
             lambda: [f.detail for f in bad if f.check == "image-alt-placeholder"]
             == ["r.png: 'IMG_2041' (a camera's or tool's name for a file)"]
             and [f.detail for f in bad if f.check == "image-alt-is-file-name"]
             == ["media/db-locked.png: 'db locked'", "u.png: 'Figure 2 (fig2.png)'"]),
            ("alt text that is only a credit is named",
             lambda: [f.detail.split(":")[0] for f in bad if f.check == "image-alt-credit"]
             == ["v.png"]),
            ("one alt text on different pictures is named on each page it's on, case and "
             "closing punctuation aside, with how many others have it; not on copies of one "
             "picture, a decorative image, or alt text another check names",
             lambda: expect(sorted((os.path.basename(f.where), f.detail) for f in alike
                                   if f.check == "image-alt-shared") == [
                 ("one.html", "a.png: 'A rising line' (shared with 1 other image)"),
                 ("one.html", "d.png: 'Two dots' (shared with 1 other image)"),
                 ("one.html", "m/b.png: 'a rising line.' (shared with 1 other image)"),
                 ("two.html", "c.png: 'A rising line' (shared with 1 other image)"),
                 ("two.html", "e.png: 'Two dots' (shared with 1 other image)"),
                 ("two.html", "https://example.org/h.png: 'Two dots' "
                              "(shared with 1 other image)")], alike)),
            ("and on one no file system can name, by its name",
             lambda: [f.detail.split(":")[0] for f in unnamed if f.check == "image-alt-shared"]
             == ["a%00.png", "b.png"]),
            ("a table whose every cell is a header is named by its place on the page, "
             "and one with a data cell isn't",
             lambda: [f.detail for f in bad if f.check == "table-without-data-cells"]
             == ["table 2"]),
            ("a header cell holding only a formula is named by its table and TeX, "
             "and one with no TeX by its table",
             lambda: sorted(f.detail for f in bad if f.check == "table-header-is-formula")
             == ["table 2", "table 2", "table 2: q_d"]),
            # An EPUB's documents are read as XML: a nested table's header is
            # its own table's, not the table around it.
            ("in XHTML too, each header its own table's",
             lambda: outputcheck.read_xhtml("n.xhtml", NESTED).formula_headers
             == [(2, "y")]),
            ("a layout table marked role none, as one marked presentation, is checked for "
             "neither headers, a scroll region, nor a formula as its header, in HTML and XHTML",
             lambda: expect(checks(none) == [], none)
             and outputcheck.read_xhtml("n.xhtml", NESTED.replace(
                 'role="presentation"', 'role="none"')).formula_headers == [(2, "y")]),
            ("and a link's text is read as it's shown, a picture's alt text in its place",
             lambda: outputcheck.read_xhtml("l.xhtml", LABELED).labeled_links
             == [("Sales", "Chart of sales")]),
            # WCAG 2.5.3, where W3C's Understanding document says text used
            # as a symbol isn't a visible label: the good page's note has a
            # way back, a symbol named "Back to reference 1".
            ("a link whose label leaves out its text is named, when the text is words or a "
             "number, not a symbol",
             lambda: [f.detail for f in bad if f.check == "link-label-without-text"]
             == ["'https://doi.org/10/b8xx35' named 'DOI for Klein and Stern 2005'",
                 "'2' named 'Note two'"]),
            ("a formula shown as TeX is named by its TeX",
             lambda: any(f.check == "formula-shown-as-tex"
                         and f.detail == "$x_{2}\\text{\\cdot}x_{n}$" for f in bad)),
            ("a formula Pandoc kept as its text is named by its text, its spaces evened out",
             lambda: [f.detail for f in bad if f.check == "formula-kept-as-text"]
             == ["x 2"]),
            ("and neither is found on a page with a script, which may render them",
             lambda: checks(scripted) == []),
            ("a page titled with its file's name is found, one whose name is a word isn't, "
             "nor one named for its H1",
             lambda: sorted((os.path.basename(f.where), f.check) for f in titled) == [
                 ("ch_intro_to_data.html", "title-is-file-name"),
                 ("tTable.html", "title-is-file-name")]),
            ("in a reveal.js presentation, a route to an id or a slide's place is a link "
             "within it, one to no id a missing fragment, and on a page any route is",
             lambda: [(f.check, f.detail) for f in presented]
             == [("link-to-missing-fragment", "#/gone")]
             and [(f.check, f.detail) for f in routed]
             == [("link-to-missing-fragment", "#/there")]),
                        ("a finding says where and what",
             lambda: any(f.where == "bad.html" and f.detail == "gone.html"
                         for f in bad)),
        ]
        if shutil.which("pandoc"):
            with open(os.path.join(work, "b.md"), "w", encoding="utf-8") as fh:
                fh.write("---\ntitle: B\nlang: en\n---\n\n# One\n\n"
                         "See [two](#two).\n\n# Two {#two}\n\ntext\n")
            epub = os.path.join(work, "b.epub")
            subprocess.run(["pandoc", "b.md", "-t", "epub3", "-o", epub],
                           cwd=work, check=True)
            clean = outputcheck.check_epub(epub)
            # Break the link inside the archive.
            broken = os.path.join(work, "broken.epub")
            with zipfile.ZipFile(epub) as src, \
                    zipfile.ZipFile(broken, "w") as dst:
                for info in src.infolist():
                    data = src.read(info.filename)
                    if info.filename.endswith("ch001.xhtml"):
                        data = data.replace(b"#two", b"#gone").replace(
                            b"See ", b'See <span class="math display">$$\\text{\\cdot}$$</span> ')
                        data = data.replace(b"</h1>", b'</h1><table><tr><th><math '
                                            b'xmlns="http://www.w3.org/1998/Math/MathML">'
                                            b'<mi>x</mi></math></th></tr></table>', 1)
                        data = data.replace(b"</body>", b'<p><a href="ch002.xhtml" aria-label='
                                            b'"Chapter two">2</a> <a href="ch002.xhtml" '
                                            b'aria-label="Back to reference 1">&#x21A9;&#xFE0E;'
                                            b'</a></p></body>')
                        # One picture in two files, with one alt text, and a
                        # picture with another's.
                        data = data.replace(b"</body>", b'<p><img src="../media/one.png" alt='
                                            b'"A falling line"/><img src="../media/same.png" '
                                            b'alt="A falling line"/><img src="../media/three.png" '
                                            b'alt="Two dots."/></p></body>')
                    if info.filename.endswith("ch002.xhtml"):
                        data = data.replace(b"</body>", b'<p><img src="../media/two.png" alt='
                                            b'"Two dots"/></p></body>')
                    if info.filename.endswith("content.opf"):
                        data = data.replace(b"</manifest>", b"".join(
                            b'<item id="%s" href="media/%s.png" media-type="image/png"/>'
                            % (n, n) for n in (b"one", b"same", b"two", b"three"))
                            + b"</manifest>")
                    dst.writestr(info, data)
                for name, picture in (("one", b"1"), ("same", b"1"), ("two", b"2"),
                                      ("three", b"3")):
                    dst.writestr("EPUB/media/%s.png" % name, picture)
            damaged = outputcheck.check_epub(broken)
            # Pandoc's own page and EPUB from a page whose formulas it
            # can't all read: the span it keeps one in is found in each.
            with open(os.path.join(work, "kept.html"), "w", encoding="utf-8") as fh:
                fh.write(KEPT)
            for out in ("kept-out.html", "kept.epub"):
                subprocess.run(["pandoc", "kept.html", "--standalone",
                                *pandocversion.mathml(), "-o", out], cwd=work, check=True)
            kept_page = outputcheck.check_html_files([os.path.join(work, "kept-out.html")])
            kept_book = outputcheck.check_epub(os.path.join(work, "kept.epub"))
            cases += [
                ("a formula Pandoc couldn't read from its MathML is found where it kept it, "
                 "on its page and in its EPUB, and the one it read isn't",
                 lambda: expect([f.detail for f in kept_page
                                 if f.check == "formula-kept-as-text"] == ["x", "1"]
                                and [f.detail for f in kept_book
                                     if f.check == "formula-kept-as-text"] == ["x", "1"],
                                kept_page + kept_book)),
                ("a Pandoc EPUB passes apart from its known omissions",
                 lambda: set(checks(clean)) <= {"no-accessibility-metadata"}
                 or checks(clean) == []),
                ("a fragment broken inside the archive is found",
                 lambda: "link-to-missing-fragment" in checks(damaged)),
                ("and a formula shown as TeX in it",
                 lambda: "formula-shown-as-tex" in checks(damaged)),
                ("and a header cell holding only a formula",
                 lambda: [f.detail for f in damaged if f.check == "table-header-is-formula"]
                 == ["table 1"]),
                ("and a table whose every cell is a header, not one with a data cell",
                 lambda: expect([f.detail for f in damaged
                                 if f.check == "table-without-data-cells"] == ["table 1"],
                                damaged)),
                ("and a link whose label leaves out its text, not one whose text is a symbol",
                 lambda: [f.detail for f in damaged if f.check == "link-label-without-text"]
                 == ["'2' named 'Chapter two'"]),
                ("and one alt text on different pictures, told apart by the archive's files, "
                 "not on one picture in two of them",
                 lambda: expect(sorted((f.where.split("/")[-1], f.detail.split(":")[0])
                                       for f in damaged if f.check == "image-alt-shared") == [
                     ("ch001.xhtml", "../media/three.png"), ("ch002.xhtml", "../media/two.png")],
                     damaged)),
                ("the EPUB's own structure is read: manifest, spine, nav",
                 lambda: not any(c.startswith(("manifest", "spine", "no-nav",
                                               "file-not", "mimetype"))
                                 for c in checks(damaged))),
            ]
        # The full validators, when they are here. A machine without
        # them skips these with a note rather than failing.
        have = {n: outputcheck.find_validator(n) for n in ("epubcheck", "vnu")}
        if shutil.which("pandoc") and have["epubcheck"]:
            ec_clean = outputcheck.run_epubcheck(have["epubcheck"], epub)
            ec_broken = outputcheck.run_epubcheck(have["epubcheck"], broken)
            cases += [
                ("epubcheck passes Pandoc's own EPUB",
                 lambda: expect(ec_clean == [], ec_clean)),
                ("and reports the broken fragment as RSC-012, with the file",
                 lambda: expect(any(f.check == "epubcheck:RSC-012"
                                    and f.where.endswith("ch001.xhtml")
                                    for f in ec_broken), ec_broken)),
            ]
        else:
            print("  skip  epubcheck not installed (EPUBCHECK_JAR)")
        if have["vnu"]:
            # One run for both pages, its findings told apart by page.
            both, _ = outputcheck.run_vnu(have["vnu"], [os.path.join(work, "good.html"),
                                                        os.path.join(work, "bad.html")])
            v_good = [f for f in both if f.where == "good.html"]
            v_bad = [f for f in both if f.where == "bad.html"]
            cases += [
                ("the Nu checker passes the correct page",
                 lambda: expect(not [f for f in v_good
                                     if f.check != "vnu:warning"], v_good)),
                ("and reports the image without alt, naming the page",
                 lambda: expect(any(f.check == "vnu:error"
                                    and "alt" in f.detail
                                    and f.where == "bad.html"
                                    for f in v_bad), v_bad)),
            ]
        else:
            print("  skip  the Nu HTML checker not installed (VNU_JAR)")
        # Either validator is found by its environment variable or by its
        # own name on the path, so a note about a missing one says both.
        # Both are hidden here, each variable naming a file that isn't
        # there, so the notes are checked wherever the suite runs, and
        # neither validator starts.
        hidden = {"EPUBCHECK_JAR": os.path.join(work, "none"),
                  "VNU_JAR": os.path.join(work, "none")}
        saved = {name: os.environ.get(name) for name in hidden}
        os.environ.update(hidden)
        try:
            _, notes = outputcheck.run_validators(
                [os.path.join(work, "good.html")], [os.path.join(work, "b.epub")])
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        cases += [
            ("a note about a validator that isn't here names the variable "
             "and the path",
             # expect() formats findings; a note is a plain line.
             lambda: all(any(variable in note and "on the path" in note
                             for note in notes)
                         for variable in hidden)
             or fail("got: " + " | ".join(notes))),
        ]
        cases += wcag_cases(work)
        cases += ace_cases(work)
        cases += axe_cases(work)
        for label, predicate in cases:
            try:
                ok = predicate()
            except Exception as exc:
                ok, label = False, f"{label}  ({exc})"
            print(("  ok    " if ok else "  FAIL  ") + label)
            failed += not ok
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"\n{failed} check(s) failed" if failed else "\nall output checks passed")
    return 1 if failed else 0


def wcag_cases(work):
    """--wcag: veraPDF's WCAG 2.2 profile run on a PDF, its own rules
    reported apart and as notes, and a probe in the same run saying
    whether its modules loaded. With a stand-in for veraPDF wherever the
    suite runs; and with veraPDF itself where it's installed, which,
    with jars that hold no modules, passes the profile's rule unchecked,
    as the probe shows, and with the modules VERAPDF_WCAG names, loads
    them. Each run is at AAA, which reports the stand-in's rule for 2.4.9,
    but those that say what WCAG 2.1 AA, the default, leaves out."""
    tool = os.path.join(ROOT, "bin", "check-output.py")
    fake = fakeverapdf.install(os.path.join(work, "fake"))
    loads = fakeverapdf.modules(os.path.join(work, "loads"))
    unloaded = fakeverapdf.modules(os.path.join(work, "unloaded"), loads=False)
    log = os.path.join(work, "fake.log")
    pdf = os.path.join(work, "book.pdf")
    with open(pdf, "wb") as fh:
        fh.write(pdfcheck.wcag_probe().replace(b"%PDF-1.7", b"%PDF-2.0", 1))

    def run(*flags, folder=None, verapdf=fake, level="AAA", **more):
        env = dict(os.environ, VERAPDF=verapdf, FAKE_VERAPDF_LOG=log, **more)
        env.pop("VERAPDF_WCAG", None)
        if folder:
            env["VERAPDF_WCAG"] = folder
        flags = list(flags) + (["--wcag-level", level] if level and "--wcag" in flags else [])
        return subprocess.run([sys.executable, tool, *flags], capture_output=True, text=True,
                              env=env, cwd=work, stdin=subprocess.DEVNULL).stderr

    def calls_since(count):
        with open(log, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh][count:]

    report = os.path.join(work, "wcag.csv")
    ran = run("--wcag", "--pdf", pdf, "--report", report, folder=loads)
    with open(report, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    with open(log, encoding="utf-8") as fh:
        calls = [json.loads(line) for line in fh]
    profiled = [call for call in calls if "-p" in call["args"]]
    others = sum(1 for row in rows if not row["Check"].startswith("verapdf-wcag:"))
    # With --verbose: each failed check a row, and a line after its rule's.
    loud_report = os.path.join(work, "wcag-verbose.csv")
    loud = run("--wcag", "--verbose", "--pdf", pdf, "--report", loud_report, folder=loads)
    unasked = run("--verbose", "--pdf", pdf, folder=loads)
    with open(loud_report, newline="", encoding="utf-8-sig") as fh:
        loud_rows = list(csv.DictReader(fh))
    setup = run("--wcag", folder=loads)
    missed = run("--wcag", "--pdf", pdf, folder=unloaded)
    absent = run("--wcag", "--pdf", pdf)
    quick = run("--wcag", "--quick", "--pdf", pdf, folder=loads)
    # At WCAG 2.1 AA, the default, and at 2.0: the rule for 2.4.9 (AAA), and
    # for 1.4.10 (AA, WCAG 2.1), left out and counted.
    default_report = os.path.join(work, "wcag-default.csv")
    default = run("--wcag", "--pdf", pdf, "--report", default_report, folder=loads, level=None)
    with open(default_report, newline="", encoding="utf-8-sig") as fh:
        default_rows = list(csv.DictReader(fh))
    older_aa = run("--wcag", "--wcag-version", "2.0", "--pdf", pdf, folder=loads, level=None,
                   FAKE_VERAPDF_REFLOW="1")
    # A PDF 1.x beside a PDF 2.0, each against its own profile, a
    # CLASSPATH_PREFIX already set kept after the modules', and a folder
    # without the 1.x profile.
    older = os.path.join(work, "older.pdf")
    with open(older, "wb") as fh:
        fh.write(pdfcheck.wcag_probe())
    count = len(calls_since(0))
    both = run("--wcag", "--pdf", pdf, "--pdf", older, folder=loads,
               CLASSPATH_PREFIX="/somewhere/else.jar")
    both_calls = [call for call in calls_since(count) if "-p" in call["args"]]
    lacking = fakeverapdf.modules(os.path.join(work, "lacking"),
                                  profiles=("WCAG-2-2-Machine-PDF20.xml",))
    count = len(calls_since(0))
    halfway = run("--wcag", "--pdf", pdf, "--pdf", older, folder=lacking)
    halfway_calls = [call for call in calls_since(count) if "-p" in call["args"]]
    # Two PDF 2.0 files, and a folder with only the 1.x profile.
    second = os.path.join(work, "book2.pdf")
    shutil.copy(pdf, second)
    only_older = fakeverapdf.modules(os.path.join(work, "only-older"),
                                     profiles=("WCAG-2-2-Machine.xml",))
    count = len(calls_since(0))
    newer_unfit = run("--wcag", "--pdf", pdf, "--pdf", second, folder=only_older)
    newer_unfit_calls = [call for call in calls_since(count) if "-p" in call["args"]]
    count = len(calls_since(0))
    pages_only = run("--wcag", os.path.join(work, "good.html"), folder=loads)
    pages_calls = calls_since(count)
    garbled = run("--wcag", "--pdf", pdf, folder=loads, FAKE_VERAPDF_GARBLED="1")
    skipped = run("--wcag", "--pdf", pdf, folder=loads, FAKE_VERAPDF_SKIP="book.pdf")
    # Modules that don't load, with two profiles to run: one run, one warning.
    count = len(calls_since(0))
    missed_both = run("--wcag", "--pdf", pdf, "--pdf", older, folder=unloaded)
    missed_calls = [call for call in calls_since(count) if "-p" in call["args"]]
    # What veraPDF writes to stderr beside its report: an exception, the
    # JVM's note of options that mention an error, and bytes that aren't UTF-8.
    erred = run("--wcag", "--pdf", pdf, folder=loads,
                FAKE_VERAPDF_STDERR="java.io.IOException: Couldn't render page 3\n"
                                    "\tat org.apache.pdfbox.rendering.PDFRenderer.x(X.java:1)\n")
    # The notes and the log lines are as veraPDF 1.30.3 writes them here.
    noted = run("--wcag", "--pdf", pdf, folder=loads,
                FAKE_VERAPDF_STDERR="NOTE: Picked up JDK_JAVA_OPTIONS: "
                                    "-XX:+HeapDumpOnOutOfMemoryError\n"
                                    "Picked up JAVA_TOOL_OPTIONS: -Dhttps.proxyPort=46607\n"
                                    "Oct 22, 2026 10:14:27 AM org.verapdf.gf.model.factory."
                                    "chunks.ChunkParser getMCID\n"
                                    "SEVERE: Undefined property /Artifact in a content "
                                    "stream\n")
    undecoded = run("--wcag", "--pdf", pdf, folder=loads, FAKE_VERAPDF_STDERR="\udcff\udcfe\n")
    # veraPDF killed before it reported, as the kernel kills a JVM short of
    # memory, with only the JVM's note on stderr.
    killed = run("--wcag", "--pdf", pdf, folder=loads, FAKE_VERAPDF_KILLED="1",
                 FAKE_VERAPDF_STDERR="NOTE: Picked up JDK_JAVA_OPTIONS: "
                                     "-XX:+HeapDumpOnOutOfMemoryError\n")
    # A PDF or an EPUB named that isn't there: no PDF to check, not the setup.
    count = len(calls_since(0))
    typos = [run("--wcag", flag, os.path.join(work, "no-such" + ext), folder=loads)
             for flag, ext in (("--pdf", ".pdf"), ("--epub", ".epub"))]
    typo_calls = [call for call in calls_since(count) if "-p" in call["args"]]
    # A profile without the rule the probe fails, by the name of veraPDF's.
    foreign = fakeverapdf.modules(os.path.join(work, "foreign"))
    for name, kind in fakeverapdf.KINDS.items():
        with open(os.path.join(foreign, name), "w", encoding="utf-8") as fh:
            fh.write(fakeverapdf.PROFILE.format(kind=kind).replace('testNumber="1"',
                                                                   'testNumber="2"'))
    count = len(calls_since(0))
    unfit = run("--wcag", "--pdf", pdf, folder=foreign)
    unfit_calls = [call for call in calls_since(count) if "-p" in call["args"]]
    # Nothing found and no --wcag: the report removed, and not said to be written.
    bare_report = os.path.join(work, "nothing.csv")
    with open(bare_report, "w") as fh:
        fh.write("Where,Check,Detail\n")
    nothing = run(os.path.join(work, "other.html"), "--report", bare_report)
    url = "https://www.w3.org/WAI/WCAG22/Understanding/link-purpose-link-only.html"
    cases = [
        ("--wcag reports the profile's own rules, not PDF/UA's, each a note counting its "
         "failed checks, with the criterion as the standard",
         lambda: [(r["Where"], r["Check"], r["Severity"], r["Standard"]) for r in rows
                  if r["Check"].startswith("verapdf")] == [
             ("book.pdf", "verapdf-wcag:1.3.1-1", "note", "WCAG 2.0 SC 1.3.1 (A)"),
             ("book.pdf", "verapdf-wcag:2.4.9-1", "note", "WCAG 2.0 SC 2.4.9 (AAA)")]
         or fail("got: " + " | ".join(r["Where"] + " " + r["Check"] for r in rows))),
        ("and the detail says how many, on which pages, that --verbose lists each, the "
         "criterion, its Understanding document, and that the check may be wrong",
         lambda: [r["Detail"] for r in rows if r["Check"] == "verapdf-wcag:2.4.9-1"] == [
             "Links shall contain an alternate description via their Contents or Alt keys or "
             "in the text value: 1 failed check(s), page 3; --verbose lists each, with what the "
             f"PDF has there. 2.4.9 Link Purpose (Link Only) (AAA): {url}. veraPDF's WCAG "
             "checks are experimental and may be wrong."]),
        ("and the summary says, last, that --verbose lists each failed check",
         lambda: ran.rstrip().splitlines()[-2:] == [
             "  " + pdfcheck.WCAG_VERBOSE, f"Written to {report}."] or fail("got: " + ran)),
        ("with --verbose, each failed check a note at its page, saying what veraPDF found",
         lambda: [(r["Where"], r["Check"], r["Severity"]) for r in loud_rows
                  if r["Check"].startswith("verapdf")] == [
             ("book.pdf#page=653", "verapdf-wcag:1.3.1-1", "note"),
             ("book.pdf#page=3", "verapdf-wcag:2.4.9-1", "note")]
         and [r["Detail"] for r in loud_rows if r["Check"] == "verapdf-wcag:2.4.9-1"] == [
             "Links shall contain an alternate description via their Contents or Alt keys or "
             "in the text value: A link annotation does not include an alternate description "
             "in the Contents or Alt Keys or in the text value. 2.4.9 Link Purpose (Link Only) "
             f"(AAA): {url}. veraPDF's WCAG checks are experimental and may be wrong."]
         or fail("got: " + " | ".join(r["Where"] + " " + r["Detail"] for r in loud_rows))),
        ("and a line for each after its rule's, and nothing said of --verbose",
         lambda: loud.index("  book.pdf: verapdf-wcag:1.3.1-1")
         < loud.index("    book.pdf#page=653: Text contains 7 repeated non space characters\n")
         < loud.index("  book.pdf: verapdf-wcag:2.4.9-1")
         < loud.index("    book.pdf#page=3: A link annotation does not include")
         and "--verbose" not in loud or fail("got: " + loud)),
        ("--verbose without --wcag says it changes nothing, and runs no profile",
         lambda: "  " + pdfcheck.WCAG_ALONE in unasked and "verapdf-wcag" not in unasked
         or fail("got: " + unasked)),
        ("the summary's verdict doesn't count them, and their lines come after it, "
         "under one saying they're experimental",
         lambda: re.search(rf"Output check: 0 page\(s\) and 1 PDF\(s\), {others} finding\(s\)",
                           ran)
         and ran.index("Output check:") < ran.index("WCAG 2.2 machine checks ran on 1 PDF(s)")
         < ran.index("experimental and may be wrong")
         < ran.index("book.pdf: verapdf-wcag:1.3.1-1") or fail("got: " + ran)),
        ("a line for each rule, naming the criterion, the pages, and its Understanding document",
         lambda: f"book.pdf: verapdf-wcag:2.4.9-1, 2.4.9 Link Purpose (Link Only) (AAA): 1 "
                 f"failed check(s), page 3: Links shall contain" in ran and url in ran),
        ("veraPDF gets the folder's profile for PDF 2.0, its log off, a file of any name, "
         "a rule's every failed check listed, the probe and the PDF, and the folder's jars "
         "first on its classpath",
         lambda: len(profiled) == 1 and profiled[0]["args"][:6] == [
             "--loglevel", "0", "--nonpdfext", "-p",
             os.path.join(loads, "WCAG-2-2-Machine-PDF20.xml"), "--format"]
         and profiled[0]["args"][profiled[0]["args"].index("--maxfailuresdisplayed") + 1]
         == "10000"
         and os.path.basename(profiled[0]["args"][-2]) == "wcag-probe.pdf"
         and profiled[0]["args"][-1] == pdf
         and profiled[0]["prefix"].split(os.pathsep)[0] == os.path.join(loads, "*")
         or fail(f"got: {profiled}")),
        ("and veraPDF's usual run gets a file of any name too",
         lambda: [call for call in calls if "-p" not in call["args"]]
         and all("--nonpdfext" in call["args"] for call in calls if "-p" not in call["args"])
         or fail(f"got: {calls}")),
        ("with nothing to check, the probe alone says the modules loaded",
         lambda: "veraPDF 1.30.3 loaded its WCAG modules from " + loads in setup
         and "run on PDF 2.0 and PDF 1.x files alike" in setup
         or fail("got: " + setup)),
        ("modules veraPDF didn't load are a warning that it skips their checks silently, "
         "and nothing is reported, nor said to have run",
         lambda: "WARNING: veraPDF 1.30.3 didn't load its WCAG modules" in missed
         and "silently" in missed and "verapdf-wcag:" not in missed
         and "ran on" not in missed or fail("got: " + missed)),
        ("a PDF 1.x and a PDF 2.0 each get their own profile, and a CLASSPATH_PREFIX "
         "already set comes after the modules'",
         lambda: sorted(os.path.basename(call["args"][call["args"].index("-p") + 1])
                        for call in both_calls)
         == ["WCAG-2-2-Machine-PDF20.xml", "WCAG-2-2-Machine.xml"]
         and all(call["prefix"] == os.pathsep.join([os.path.join(loads, "*"),
                                                    "/somewhere/else.jar"])
                 for call in both_calls)
         and "ran on 2 PDF(s)" in both and "older.pdf: verapdf-wcag:2.4.9-1" in both
         or fail(f"got: {both_calls} | {both}")),
        ("a folder without a profile a PDF needs is a warning for that PDF, the other "
         "checked", lambda: len(halfway_calls) == 1
         and "has no WCAG-2-2-Machine.xml, so the WCAG checks didn't run on 1 PDF 1.x "
             "file(s): older.pdf (docs/installation.md" in halfway
         and "book.pdf: verapdf-wcag:1.3.1-1" in halfway
         and "older.pdf: verapdf-wcag" not in halfway or fail("got: " + halfway)),
        ("and one without the PDF 2.0 profile names the PDF 2.0 files it didn't check",
         lambda: not newer_unfit_calls
         and "has no WCAG-2-2-Machine-PDF20.xml, so the WCAG checks didn't run on 2 PDF 2.0 "
             "file(s): book.pdf and book2.pdf (docs/installation.md" in newer_unfit
         or fail("got: " + newer_unfit)),
        ("pages and no PDF: the profile isn't run, and the summary says why",
         lambda: "veraPDF's WCAG checks not run: no PDF to check." in pages_only
         and not [call for call in pages_calls if "-p" in call["args"]]),
        ("what veraPDF prints when it can't load a profile is a warning with its exception, "
         "not a stopped run",
         lambda: "WARNING: --wcag: veraPDF didn't report on WCAG-2-2-Machine-PDF20.xml: "
                 'Exception in thread "main" javax.xml.bind.UnmarshalException' in garbled
         and "Traceback" not in garbled or fail("got: " + garbled)),
        ("a PDF veraPDF left out of its report, saying nothing, is a warning",
         lambda: "WARNING: --wcag: veraPDF didn't check book.pdf, and said nothing of it"
         in skipped or fail("got: " + skipped)),
        ("modules that don't load with one profile aren't tried with the other: one run, "
         "one warning", lambda: len(missed_calls) == 1
         and missed_both.count("didn't load its WCAG modules") == 1
         or fail(f"got: {missed_calls} | {missed_both}")),
        ("an exception veraPDF printed as it checked is a warning that checks may be undone",
         lambda: "WARNING: --wcag: veraPDF wrote an error as it checked, which may have left "
                 "some checks undone: java.io.IOException: Couldn't render page 3" in erred
         and "book.pdf: verapdf-wcag:1.3.1-1" in erred or fail("got: " + erred)),
        ("the JVM's notes of its options, one naming an error, and veraPDF's log aren't one",
         lambda: "wrote an error" not in noted and "ran on 1 PDF(s)" in noted
         or fail("got: " + noted)),
        ("nor do bytes that aren't UTF-8 stop the run, or veraPDF's usual one",
         lambda: "Traceback" not in undecoded and "ran on 1 PDF(s)" in undecoded
         and "verapdf:failed" not in undecoded or fail("got: " + undecoded)),
        ("veraPDF killed before it reported is a warning saying so, not naming the JVM's note",
         lambda: "WARNING: --wcag: veraPDF didn't report on WCAG-2-2-Machine-PDF20.xml: "
                 "stopped by signal 9" in killed and "Picked up" not in killed
         or fail("got: " + killed)),
        ("a PDF or an EPUB named that isn't there: no PDF to check, and the setup not checked",
         lambda: all("veraPDF's WCAG checks not run: no PDF to check." in typo
                     and "loaded its WCAG modules" not in typo for typo in typos)
         and not typo_calls or fail(f"got: {typos} | {typo_calls}")),
        ("a profile without the probe's rule is a warning, and isn't run, since the probe "
         "can't tell with it", lambda: not unfit_calls
         and "lacks the rule veraPDF's 1.30 machine profiles have on repeated characters, "
             "1.3.1-1" in unfit
         and "didn't load" not in unfit or fail("got: " + unfit)),
        ("nothing found: the report removed, and not said to be written",
         lambda: "nothing found" in nothing and "Written to" not in nothing
         and not os.path.exists(bare_report) or fail("got: " + nothing)),
        ("no folder of them is a warning naming VERAPDF_WCAG",
         lambda: "WARNING: veraPDF's WCAG modules aren't installed (VERAPDF_WCAG" in absent
         or fail("got: " + absent)),
        ("--quick leaves the profile out, saying so",
         lambda: "veraPDF's WCAG checks not run (--quick)." in quick),
        ("at WCAG 2.1 AA, the default, a rule for a criterion beyond it is no finding, and a "
         "line counts what it found",
         lambda: [r["Check"] for r in default_rows if r["Check"].startswith("verapdf-wcag")]
         == ["verapdf-wcag:1.3.1-1"]
         and "WCAG 2.2 machine checks ran on 1 PDF(s) for WCAG 2.1 AA, with its WCAG" in default
         and "  Left out at WCAG 2.1 AA, which --wcag-version and --wcag-level choose: "
             "verapdf-wcag:2.4.9-1, 2.4.9 Link Purpose (Link Only) (AAA), 1 failed check(s) "
             "in book.pdf.\n" in default or fail("got: " + default)),
        ("and at 2.0 AA, a rule for one 2.1 brought, left out with it",
         lambda: "Left out at WCAG 2.0 AA, which --wcag-version and --wcag-level choose: "
                 "verapdf-wcag:1.4.10-1, 1.4.10 Reflow (AA, WCAG 2.1), 1 failed check(s) in "
                 "book.pdf; verapdf-wcag:2.4.9-1" in older_aa
         and "book.pdf: verapdf-wcag:1.3.1-1" in older_aa or fail("got: " + older_aa)),
    ]
    # A PDF the output check finds nothing in of its own: the probe with a
    # title it displays, XMP metadata, and a bookmark.
    try:
        import pikepdf
    except ImportError:
        pikepdf = None
    if pikepdf is not None and pdfcheck.pypdf is not None:
        tidy, tidy_report = os.path.join(work, "tidy.pdf"), os.path.join(work, "tidy.csv")
        with pikepdf.open(io.BytesIO(pdfcheck.wcag_probe())) as made:
            made.docinfo["/Title"] = "A Book"
            made.Root.ViewerPreferences = pikepdf.Dictionary(DisplayDocTitle=True)
            with made.open_metadata() as meta:
                meta["dc:title"] = "A Book"
            with made.open_outline() as outline:
                outline.root.append(pikepdf.OutlineItem("A Book", 0))
            made.save(tidy)
        alone = run("--wcag", "--pdf", tidy, "--report", tidy_report, folder=loads)
        with open(tidy_report, newline="", encoding="utf-8-sig") as fh:
            tidy_rows = list(csv.DictReader(fh))
        cases.append(("veraPDF's WCAG notes alone: nothing found, their lines after, and the "
                      "report written with them",
                      lambda: "Output check: 0 page(s) and 1 PDF(s), nothing found." in alone
                      and f"Written to {tidy_report}." in alone
                      and [r["Check"] for r in tidy_rows] == ["verapdf-wcag:1.3.1-1",
                                                               "verapdf-wcag:2.4.9-1"]
                      or fail("got: " + alone)))
    elif pikepdf is None:
        print("  skip  no pikepdf to make a PDF the output check finds nothing in")
    else:
        print("  skip  no pypdf for the output check to read a PDF it finds nothing in")
    real = outputcheck.find_validator("verapdf")
    if not real:
        print("  skip  veraPDF not installed (VERAPDF); its WCAG profile isn't run itself")
        return cases
    if len(real) > 1:
        print("  skip  VERAPDF names veraPDF's jar, which java -jar runs without "
              "CLASSPATH_PREFIX; its WCAG profile isn't run itself")
        return cases
    bare = os.path.join(work, "bare")
    os.makedirs(bare)
    for name in fakeverapdf.MODULES:
        zipfile.ZipFile(os.path.join(bare, name), "w").close()
    for name, kind in fakeverapdf.KINDS.items():
        with open(os.path.join(bare, name), "w", encoding="utf-8") as fh:
            fh.write(fakeverapdf.PROFILE.format(kind=kind))
    silent = run("--wcag", folder=bare, verapdf=real[0])
    cases.append(("veraPDF itself, given jars that hold no modules, passes the probe, which "
                  "the warning says", lambda: "didn't load its WCAG modules" in silent
                  or fail("got: " + silent)))
    installed = os.environ.get("VERAPDF_WCAG", "").strip()
    if installed:
        loaded = run("--wcag", folder=installed, verapdf=real[0])
        cases.append(("and given the modules VERAPDF_WCAG names, it loads them",
                      lambda: "loaded its WCAG modules" in loaded or fail("got: " + loaded)))
    else:
        print("  skip  veraPDF's WCAG modules not installed (VERAPDF_WCAG)")
    return cases


def browser_problem():
    """Why a page can't be checked in a browser here, or None: Python's
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
        return (f"Playwright's Chromium doesn't start ({lines[0][:200] if lines else exc}); "
                "`python3 -m playwright install --with-deps --only-shell chromium` installs "
                "it (see docs/installation.md)")
    return None


# A page that tries everything a page shouldn't get to do when it's
# checked: its scripts, inline, in a handler, and in a frame's srcdoc,
# each of which would add a picture without alt text, named pwned, if it
# ran; a refresh elsewhere; a stylesheet, a font, and a picture from
# elsewhere; a file of the machine's, in a picture and a frame; a frame of
# its own folder's, with a picture without alt text, and one from
# elsewhere; and a WebSocket.
PWNED = "document.body.insertAdjacentHTML('beforeend', '<img src=\"pwned-{}.png\">');"
HOSTILE = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>A hostile page</title>
<meta http-equiv="refresh" content="0; url=https://refresh.example.com/">
<link rel="stylesheet" href="https://example.com/remote.css">
<style>@font-face {{ font-family: Far; src: url("https://fonts.example.org/far.woff2"); }}
p {{ font-family: Far, serif; }}</style>
</head><body onload="{PWNED.format('onload').replace('"', '&quot;')}">
<main><h1>A hostile page</h1>
<p><img src="https://tracker.example.com/pixel.gif" alt=""></p>
<p><img src="file:///etc/hostname" alt="A file of the machine's"></p>
<iframe src="file:///etc/passwd" title="A file of the machine's"></iframe>
<iframe src="frame.html" title="A frame of the folder's"></iframe>
<iframe src="https://www.youtube.com/embed/abc" title="A frame from elsewhere"></iframe>
<iframe srcdoc="<p>srcdoc</p><script>parent.{PWNED.format('srcdoc').replace('"', '&quot;')}</script>" title="srcdoc"></iframe>
<script src="https://cdn.example.com/lib.js"></script>
<script>{PWNED.format('inline')} new WebSocket('wss://ws.example.com/');</script>
</main></body></html>"""
FRAME = """<!DOCTYPE html><html lang="en"><head><title>A frame</title></head>
<body><main><p>A frame of the folder's.</p><img src="in-frame.png"></main></body></html>"""
# A page whose text is fine in light mode and too faint in dark.
DARK = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Dark</title>
<style>:root { color-scheme: light dark; }
body { background: light-dark(#ffffff, #111111); color: light-dark(#222222, #eeeeee); }
p.faint { color: light-dark(#222222, #333333); }</style></head>
<body><main><h1>Dark</h1><p class="faint">Readable in light mode only.</p></main></body></html>"""
# A formula in the text's colors, whose minus sign axe-core doesn't
# measure, and text over a picture, whose background it can't tell, in
# light mode and dark; and a formula with a color of its own.
FORMULAS = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Formulas</title>
<style>:root { color-scheme: light dark; }
body { background: light-dark(#ffffff, #111111); color: light-dark(#222222, #eeeeee); }</style>
</head><body><main><h1>Formulas</h1>
<p>A difference, <math><mi>x</mi><mo>−</mo><mn>2</mn></math>, in the text's colors.</p>
<p style="background-image: url(data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAf
FcSJAAAADUlEQVR4nGNgYGD4DwABBAEAwS2OUAAAAABJRU5ErkJggg==)">Text over a picture.</p>
</main></body></html>""".replace("AAAAf\nFcSJ", "AAAAfFcSJ")
COLORED = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Colored</title>
</head><body><main><h1>Colored</h1>
<p>A difference in a color of its own,
<math><mi>x</mi><mo mathcolor="#999999">−</mo><mn>2</mn></math>.</p></main></body></html>"""
# What only axe-core's experimental rules and its best practices find: a
# paragraph styled as a heading, a large table without headers, a caption
# written in a table's first cell, and a paragraph outside the landmarks.
TRYING = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Trying</title>
<style>body { margin: 1em; }</style></head><body><main><h1>Trying</h1>
<p><b><i>Results</i></b></p>
<p>The scores for the first three weeks, and the totals after them.</p>
<table border="1"><caption>Scores</caption>
<tr><td>Week</td><td>Ana</td><td>Ben</td><td>Cy</td></tr>
<tr><td>1</td><td>9</td><td>8</td><td>7</td></tr>
<tr><td>2</td><td>8</td><td>7</td><td>6</td></tr>
<tr><td>3</td><td>7</td><td>6</td><td>5</td></tr></table>
<table border="1"><tr><td colspan="3">Table 2: Totals</td></tr>
<tr><th>Name</th><th>Total</th><th>Rank</th></tr>
<tr><td>Ana</td><td>24</td><td>1</td></tr>
<tr><td>Ben</td><td>21</td><td>2</td></tr></table></main>
<p>Outside the main content.</p></body></html>"""


def presentation(folder, slides=None, start=None, before="", reveal_tail=b"", oer_tail=""):
    """A presentation as revealtarget writes one, in folder, from the
    probe's own files: TextbookImprover's scripts, and slides, the second
    with a picture without alt text, one in a step, and one whose
    background only reveal.js paints. start, before, reveal_tail, and
    oer_tail change it: the start of reveal.js, markup before the
    scripts, and what's added to reveal.js and to oer-reveal.js."""
    import axecheck
    files = axecheck.probe_presentation_files()
    page = files.pop("probe-presentation.html").decode("utf-8")
    page = page.replace(
        '<section id="two" class="slide level2"><h2>Two</h2><p><img src="nameless.png">'
        "</p></section>", slides or (
            '<section id="two" class="slide level2"><h2>Two</h2><p><img src="nameless.png">'
            '</p></section><section id="steps" class="slide level2"><h2>Steps</h2>'
            '<p>First.</p><p class="fragment"><img src="step.png"></p></section>'
            '<section id="gray" class="slide level2" data-background-color="#777777">'
            '<h2>Gray</h2><p style="font-size: 16px">Small text on gray, which reveal.js '
            "paints, and makes white: 4.48 to 1.</p></section>"))
    if start:
        page = re.sub(r"Reveal\.initialize\(\{.*?\}\);", lambda m: start, page, count=1,
                      flags=re.S)
    if before:
        page = page.replace('<script src="reveal.js/dist/reveal.js">',
                            before + '<script src="reveal.js/dist/reveal.js">', 1)
    if oer_tail:
        page = page.replace("</script>\n</body>", oer_tail + "\n</script>\n</body>")
    files["reveal.js/dist/reveal.js"] += reveal_tail
    files["deck.html"] = page.encode("utf-8")
    files["step.png"] = files["nameless.png"]
    for name, data in files.items():
        os.makedirs(os.path.dirname(os.path.join(folder, name)), exist_ok=True)
        with open(os.path.join(folder, name), "wb") as fh:
            fh.write(data)
    return os.path.join(folder, "deck.html")


def epub(path, documents):
    """An EPUB of the given content documents, {name: XHTML}."""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", (
            '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:'
            'opendocument:xmlns:container"><rootfiles><rootfile full-path="EPUB/p.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>'))
        items = "".join(f'<item id="d{n}" href="{name}" media-type="application/xhtml+xml"/>'
                        for n, name in enumerate(documents))
        refs = "".join(f'<itemref idref="d{n}"/>' for n in range(len(documents)))
        archive.writestr("EPUB/p.opf", (
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
            f"<manifest>{items}</manifest><spine>{refs}</spine></package>"))
        for name, text in documents.items():
            archive.writestr("EPUB/" + name, text)
    return path


def ace_cases(work):
    """--wcag on an EPUB with a stand-in for DAISY's Ace (tests/fakeace.py):
    its own findings notes, after the verdict and not in its count, the
    package's under the package document and a content document's under
    it, its axe-core results left out and counted; with nothing named,
    its probe; and the lines for no EPUB, --quick, a run that fails, an
    ACE that names nothing, and no Ace at all; without --wcag, not run."""
    sys.path.insert(0, HERE)
    import fakeace
    import acecheck
    folder = os.path.join(work, "ace")
    os.makedirs(folder)
    fake = fakeace.install(os.path.join(folder, "bin"))
    log = os.path.join(folder, "runs.jsonl")
    document = ('<?xml version="1.0" encoding="UTF-8"?><html xmlns="http://www.w3.org/1999/xhtml" '
                'xmlns:epub="http://www.idpf.org/2007/ops" lang="en" xml:lang="en"><head><title>'
                'One</title></head><body><section epub:type="chapter"><h1>One</h1><p><img '
                'src="a.png"/></p></section></body></html>')
    nav = ('<?xml version="1.0" encoding="UTF-8"?><html xmlns="http://www.w3.org/1999/xhtml" '
           'xmlns:epub="http://www.idpf.org/2007/ops" lang="en" xml:lang="en"><head><title>Nav'
           '</title></head><body><nav epub:type="toc"><ol><li><a href="one.xhtml">One</a></li>'
           '</ol></nav></body></html>')
    book = epub(os.path.join(folder, "book.epub"), {"one.xhtml": document, "nav.xhtml": nav})
    # The navigation document, which Ace names from the EPUB's root.
    with zipfile.ZipFile(book) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    parts["EPUB/p.opf"] = parts["EPUB/p.opf"].replace(
        b'href="nav.xhtml" media-type="application/xhtml+xml"',
        b'href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"')
    with zipfile.ZipFile(book, "w") as archive:
        for name, data in parts.items():
            archive.writestr(name, data, zipfile.ZIP_STORED if name == "mimetype"
                             else zipfile.ZIP_DEFLATED)
    tool = os.path.join(ROOT, "bin", "check-output.py")
    empty = os.path.join(folder, "empty-path")
    os.makedirs(empty)

    def run(*flags, **env):
        environ = dict(os.environ, ACE=fake, FAKE_ACE_LOG=log)
        environ.pop("VERAPDF", None)
        environ.update(env)
        for name, value in env.items():
            if value is None:
                environ.pop(name, None)
        return subprocess.run([sys.executable, tool, *flags], capture_output=True, text=True,
                              env=environ, cwd=folder, stdin=subprocess.DEVNULL).stderr

    def runs():
        if not os.path.exists(log):
            return 0
        with open(log, encoding="utf-8") as fh:
            return sum(1 for line in fh if '"-o"' in line)
    report = os.path.join(folder, "ace.csv")
    quick = run("--wcag", "--quick", "--epub", book)
    quick_runs = runs()
    ran = run("--wcag", "--epub", book, "--report", report)
    with open(report, newline="", encoding="utf-8-sig") as fh:
        rows = [r for r in csv.DictReader(fh) if r["Tool"] == "ace"]
    probe = run("--wcag")
    blind = run("--wcag", FAKE_ACE_BLIND="1")
    pages = run("--wcag", os.path.join(work, "good.html"))
    before_plain = runs()
    plain = run("--epub", book)
    plain_runs = runs() - before_plain
    failed = run("--wcag", "--epub", book, FAKE_ACE_FAIL="1")
    nothing = run("--wcag", "--epub", book, ACE=os.path.join(folder, "no-such-ace"))
    absent = run("--wcag", "--epub", book, ACE=None, PATH=empty)
    return [
        ("Ace's own findings are notes, the package's under the package document and a content "
         "document's under it, by the tool ace",
         lambda: sorted((r["Where"], r["Check"], r["Severity"], r["Standard"]) for r in rows) == [
             ("EPUB/nav.xhtml", "ace:epub-type-has-matching-role", "note", "Ace best practice"),
             ("EPUB/one.xhtml", "ace:epub-type-has-matching-role", "note", "Ace best practice"),
             ("EPUB/p.opf", "ace:metadata-accessmode", "note", "EPUB Accessibility 1.1")]
         or fail("got: " + json.dumps(rows))),
        ("its axe-core results are left out and counted, after the verdict and not in its count",
         lambda: "Ace by DAISY 1.4.6 checked 1 EPUB(s): 3 finding(s) of its own, a note each, "
                 "as axe-core's are; its axe-core results, 1 element(s) failing 1 rule(s) "
                 "(image-alt), are left out, since --wcag runs axe-core's rules itself." in ran
         and "ace:image-alt" not in ran and not [r for r in rows if r["Check"] == "ace:image-alt"]
         and ran.index("Output check:") < ran.index("Ace by DAISY")
         and "ace:metadata-accessmode, EPUB Accessibility 1.1: 1 finding(s), the first in "
             "EPUB/p.opf: Publications must declare the 'schema:accessMode' metadata (serious)"
             in ran or fail("got: " + ran)),
        ("with nothing named, its probe, which checks the setup",
         lambda: "Ace by DAISY 1.4.6 checked a probe EPUB of its own and found what it lacks "
                 f"({acecheck.PROBE_RULE}), so EPUBs can be checked" in probe
         or fail("got: " + probe)),
        ("and a warning when it doesn't find what the probe lacks",
         lambda: "WARNING: Ace by DAISY 1.4.6 checked a probe EPUB of its own, and didn't find "
                 f"what it lacks ({acecheck.PROBE_RULE}): it found nothing." in blind
         or fail("got: " + blind)),
        ("its lines come between axe-core's and veraPDF's",
         lambda: probe.index("axe") < probe.index("Ace by DAISY") < probe.index("veraPDF")
         or fail("got: " + probe)),
        ("pages and no EPUB, and --quick, say it didn't run, and it doesn't",
         lambda: acecheck.NOT_RUN_NO_EPUB in pages and acecheck.NOT_RUN_QUICK in quick
         and quick_runs == 0 or fail("got: " + pages + quick)),
        ("without --wcag it doesn't run",
         lambda: plain_runs == 0 and "Ace" not in plain or fail("got: " + plain)),
        ("a run that fails is a warning saying why, in Ace's words",
         lambda: "WARNING: Ace didn't check book.epub: Could not find Chrome (ver. 148.0.7778.97). "
                 "This can occur if either." in failed or fail("got: " + failed)),
        ("an ACE that names nothing, and no Ace on the path, say so",
         lambda: f"Ace's checks not run: ACE is {os.path.join(folder, 'no-such-ace')}, which "
                 "isn't there." in nothing and acecheck.NOT_FOUND in absent
         or fail("got: " + nothing + absent)),
    ]


def axe_cases(work):
    """--wcag on pages: axe-core's rules in Playwright's Chromium, locked
    down. Without Playwright, and with a Chromium that doesn't start, a
    line says so and the other findings are what they'd be without
    --wcag, and with a Playwright older than 1.48 a line naming it; --quick,
    and nothing but a PDF, leave axe-core out, saying so.
    With them: the probes as the setup; the built-in checks and axe-core's
    rules that overlap them agreeing on the suite's pages; a hostile
    page's scripts not run, its requests elsewhere refused and its
    stylesheet and font named, its refresh canceled, the machine's files
    not read, a frame of its folder's checked and one from elsewhere
    named; a page's colors checked again in dark mode, what axe-core
    couldn't decide in light mode not said again; a symbol in a formula
    in the text's colors left out and counted, one in a color of its own
    kept; an EPUB's content
    documents, one not well-formed named; TextbookImprover's presentation
    checked slide by slide with its own scripts, a step's picture and a
    slide only its background fails found, and each tampered copy caught;
    each element a note with --verbose; a page past its time, and a
    worker past its, named; a presentation whose slides are too large for
    a window checked in a smaller one, and slides past the most counted;
    off the network wherever a process can leave it; another axe-core
    noted; the policy service
    refusing what it lacks; in the suite's own process, the route taking
    a WebSocket and canceling a navigation that scripts make; and a
    worker whose run is killed partway ending too."""
    import axecheck
    tool = os.path.join(ROOT, "bin", "check-output.py")
    pages = [os.path.join(work, name) for name in ("good.html", "other.html", "bad.html")]

    def run(*flags, **env):
        environ = dict(os.environ, **env)
        environ.pop("VERAPDF", None)
        return subprocess.run([sys.executable, tool, *flags], capture_output=True, text=True,
                              env=environ, cwd=work, stdin=subprocess.DEVNULL).stderr

    def rows_of(path):
        with open(path, newline="", encoding="utf-8-sig") as fh:
            return list(csv.DictReader(fh))
    # Playwright hidden by a package of the same name that can't be imported.
    hidden = os.path.join(work, "hidden")
    os.makedirs(os.path.join(hidden, "playwright"))
    with open(os.path.join(hidden, "playwright", "__init__.py"), "w") as fh:
        fh.write('raise ImportError("hidden by the check suite")\n')
    plain_report = os.path.join(work, "plain.csv")
    hidden_report = os.path.join(work, "hidden.csv")
    run(*pages, "--quick", "--report", plain_report)
    without = run("--wcag", *pages, "--quick", "--report", hidden_report,
                  PYTHONPATH=hidden)
    unhidden = run("--wcag", *pages, PYTHONPATH=hidden)
    # A Playwright older than 1.48: one whose BrowserContext has no
    # route_web_socket, by a package of the same name.
    old = os.path.join(work, "old")
    os.makedirs(os.path.join(old, "playwright"))
    with open(os.path.join(old, "playwright", "__init__.py"), "w") as fh:
        fh.write("")
    with open(os.path.join(old, "playwright", "async_api.py"), "w") as fh:
        fh.write("class BrowserContext:\n    pass\n\n\n"
                 "def async_playwright():\n    raise RuntimeError('never reached')\n")
    aged = run("--wcag", pages[0], PYTHONPATH=old)
    quick = run("--wcag", "--quick", *pages)
    no_page = run("--wcag", "--pdf", os.path.join(work, "no-such.pdf"))
    cases = [
        ("--quick leaves axe-core out, saying so",
         lambda: "  " + axecheck.NOT_RUN_QUICK in quick or fail("got: " + quick)),
        ("and nothing named but a PDF, or one that isn't there, does too",
         lambda: "  " + axecheck.NOT_RUN_NO_PAGE in no_page or fail("got: " + no_page)),
        ("without Playwright, a line says so, and the findings are those without --wcag",
         lambda: "axe's WCAG checks not run on the pages: Playwright isn't installed "
                 "(docs/installation.md, Optional: Playwright and its Chromium)." in unhidden
         and rows_of(plain_report) == rows_of(hidden_report) or fail("got: " + unhidden)),
        ("one older than 1.48, without route_web_socket, named, and how to update it",
         lambda: "is older than 1.48, the first that lets the check take a page's "
                 "WebSockets; update it, and its Chromium (docs/installation.md, Optional: "
                 "Playwright and its Chromium)." in aged or fail("got: " + aged)),
    ]
    problem = browser_problem()
    if problem:
        print(f"  skip  {problem}: axe-core's checks in a browser aren't tried")
        return cases
    # Chromium that doesn't start: a folder of browsers with none in it.
    empty = os.path.join(work, "no-browsers")
    os.makedirs(empty)
    absent = run("--wcag", pages[0], PLAYWRIGHT_BROWSERS_PATH=empty)
    setup = run("--wcag")
    # Everything else in one run: the suite's pages, the hostile page, the
    # dark one, an EPUB, and the presentation with its tampered copies.
    for name, markup in (("hostile.html", HOSTILE), ("frame.html", FRAME),
                         ("dark.html", DARK), ("formulas.html", FORMULAS),
                         ("colored.html", COLORED)):
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(markup)
    xhtml = ('<?xml version="1.0" encoding="UTF-8"?><html xmlns="http://www.w3.org/1999/xhtml" '
             'lang="en" xml:lang="en"><head><title>{0}</title></head><body><main><h1>{0}</h1>'
             '{1}</main></body></html>')
    book = epub(os.path.join(work, "axe.epub"), {
        "text/ch01.xhtml": xhtml.format("One", '<p><img src="one.png"/></p>'),
        "text/ch02.xhtml": xhtml.format("Two", "<p>Unclosed").replace("</main>", "", 1)})
    decks = os.path.join(work, "decks")
    shows = {"ours": presentation(os.path.join(decks, "ours"))}
    shows["inline"] = presentation(os.path.join(decks, "inline"),
                                   before=f"<script>{PWNED.format('extra')}</script>")
    shows["handler"] = presentation(
        os.path.join(decks, "handler"),
        before=f'<img src="missing.png" alt="" onerror="{PWNED.format("handler")}">'.replace(
            "'<img", "&apos;<img").replace(".png\">');", '.png&quot;>&apos;);'))
    shows["setting"] = presentation(
        os.path.join(decks, "setting"),
        start="Reveal.initialize({hash: (function () { " + PWNED.format("setting")
              + " return true; })(), plugins: [RevealNotes, RevealSearch, RevealZoom]});")
    shows["revealjs"] = presentation(os.path.join(decks, "revealjs"),
                                     reveal_tail=b"\n;" + PWNED.format("revealjs").encode())
    shows["oer"] = presentation(os.path.join(decks, "oer"), oer_tail=PWNED.format("oer"))
    with open(os.path.join(decks, "file.js"), "w") as fh:
        fh.write(PWNED.format("file"))
    shows["file"] = presentation(os.path.join(decks, "file"),
                                 before='<script src="../file.js"></script>')
    with open(os.path.join(decks, "notes.txt"), "w") as fh:
        fh.write(PWNED.format("text"))
    shows["text"] = presentation(os.path.join(decks, "text"),
                                 before='<script src="../notes.txt"></script>')
    report = os.path.join(work, "axe.csv")
    checked = [os.path.join(work, n) for n in ("good.html", "bad.html", "hostile.html",
                                               "dark.html", "formulas.html", "colored.html")] \
        + list(shows.values())
    ran = run("--wcag", *checked, "--epub", book, "--report", report)
    trying = os.path.join(work, "trying.html")
    with open(trying, "w", encoding="utf-8") as fh:
        fh.write(TRYING)
    tried_report = os.path.join(work, "trying.csv")
    tried = run("--wcag", "--experimental", "--best-practice", trying, "--report", tried_report)
    tried_rows = [r for r in rows_of(tried_report) if r["Tool"] == "axe"] \
        if os.path.exists(tried_report) else []
    untried = run("--wcag", trying)
    rows = [r for r in rows_of(report) if r["Tool"] == "axe"] if os.path.exists(report) else []
    loud_report = os.path.join(work, "axe-verbose.csv")
    other_axe = os.path.join(work, "other-axe")
    os.makedirs(other_axe)
    with open(os.path.join(axecheck.VENDORED, "axe.min.js"), "rb") as fh:
        data = fh.read().replace(b"axe v4.14.0", b"axe v4.13.9", 1)
    with open(os.path.join(other_axe, "axe.min.js"), "wb") as fh:
        fh.write(data)
    loud = run("--wcag", "--verbose", pages[2], "--report", loud_report, AXE_CORE_DIR=other_axe)
    loud_rows = [r for r in rows_of(loud_report) if r["Tool"] == "axe"]
    past = axecheck.check([os.path.join(work, "good.html")], limits={"axe": 0.001})[1]
    stopped = axecheck.check([os.path.join(work, "good.html")], timeout=0.5)[1]
    service = axecheck.check([os.path.join(work, "good.html")], policy="service")[1]
    # Slides its settings make 100,000 pixels square, a window Chromium
    # stalled or crashed opening, checked in a smaller one, in the time a
    # stall would run past; and a presentation's slides past the most.
    start = re.search(r"Reveal\.initialize\(\{.*?\}\);", axecheck.probe_presentation_files()[
        "probe-presentation.html"].decode("utf-8"), re.S).group(0)
    giant = presentation(os.path.join(decks, "giant"), start=start.replace(
        "width: 1280,", "width: 100000,").replace("height: 720,", "height: 100000,"))
    huge = axecheck.check([giant], timeout=150)[1]
    few = axecheck.check([shows["ours"]], limits={"slides": 2})[1]
    # Whether a process of its own can leave the network here, as the
    # worker should.
    can_leave = subprocess.run(
        [sys.executable, "-c", "import lockedbrowser as l; print(repr(l.leave_network()))"],
        capture_output=True, text=True,
        env=dict(os.environ, PYTHONPATH=os.path.join(ROOT, "lib"))).stdout.strip() == "''"
    lockdown = route_cases(work)
    orphans = orphan_cases(presentation(os.path.join(decks, "long"), slides="".join(
        f'<section id="s{n}" class="slide level2"><h2>Slide {n}</h2><p>Text {n}.</p>'
        "</section>" for n in range(300))))

    def at(where, check, text=None):
        return [r for r in rows if r["Where"].replace(os.sep, "/").endswith(where)
                and r["Check"] == check and (text is None or text in r["Detail"])]
    overlaps = {"image-without-alt": "axe:image-alt", "no-lang": "axe:html-has-lang",
                "no-title": "axe:document-title"}
    built_in = [r for r in rows_of(report)] if os.path.exists(report) else []
    experimental = {"axe:td-has-header", "axe:table-fake-caption", "axe:p-as-heading"}
    cases += [
        ("--experimental and --best-practice: the summary names the rules, axe-core's "
         "experimental ones among them, and its best practices",
         lambda: "ran its 96 rules, its experimental ones among them, for WCAG 2.1 AA and its "
                 "best practices on 1 page(s)" in tried or fail("got: " + tried)),
        ("each experimental rule's finding says it's a rule axe-core is still trying, and its "
         "line in the summary that it's experimental: a large table's missing headers, a "
         "caption in a table's cell, a paragraph styled as a heading",
         lambda: {r["Check"] for r in tried_rows} >= experimental
         and all("by a rule axe-core is still trying" in r["Detail"]
                 for r in tried_rows if r["Check"] in experimental)
         and not any("still trying" in r["Detail"]
                     for r in tried_rows if r["Check"] not in experimental)
         and "axe:td-has-header, 1.3.1 Info and Relationships (A), an experimental rule: "
             in tried or fail("got: " + tried)),
        ("a best practice runs too: content outside the landmarks",
         lambda: "axe:region" in {r["Check"] for r in tried_rows} or fail("got: " + tried)),
        ("without them, none of those runs",
         lambda: "ran its 63 rules for WCAG 2.1 AA on 1 page(s)" in untried
         and not any(check in untried for check in experimental | {"axe:region"})
         or fail("got: " + untried)),
        ("a Chromium that doesn't start: a line saying why, and how to install it",
         lambda: "axe's WCAG checks not run on the pages: Playwright's Chromium doesn't start ("
                 in absent and "playwright install --with-deps --only-shell chromium" in absent
         or fail("got: " + absent)),
        ("with nothing to check, the probes alone: a page, and a presentation of "
         "TextbookImprover's",
         lambda: re.search(r"axe-core 4\.14\.0 ran its 63 rules for WCAG 2\.1 AA on a probe "
                           r"page of its own and a probe presentation, in Playwright [\d.]+'s "
                           r"Chromium \d+, (not )?sandboxed and (off|on) the network: it found "
                           r"the probe's problems", setup) or fail("got: " + setup)),
        ("the sandbox and the network as they are, and a line for each that isn't",
         lambda: (re.search(r"axe-core 4\.14\.0 ran [^\n]*, sandboxed and", ran)
                  or "Chromium's sandbox wasn't on (" in ran)
         and (re.search(r"axe-core 4\.14\.0 ran [^\n]* off the network", ran)
              or "The check wasn't off the network (" in ran) or fail("got: " + ran)),
        ("off the network wherever a process of its own can leave it, as one can here",
         lambda: not can_leave
         or re.search(r"axe-core 4\.14\.0 ran [^\n]* off the network", ran)
         or fail("got: " + ran)),
        ("axe-core's rules a built-in check overlaps agree with it on the suite's pages",
         lambda: all(bool([r for r in built_in if r["Check"] == mine
                           and r["Where"].endswith(page)])
                     == bool(at(page, theirs)) for mine, theirs in overlaps.items()
                     for page in ("good.html", "bad.html"))
         and at("bad.html", "axe:image-alt") and at("bad.html", "axe:html-has-lang")
         and not at("good.html", "axe:image-alt") or fail("got: " + " | ".join(
             r["Where"] + " " + r["Check"] for r in built_in))),
        ("each a note, by axe, its criterion the standard and the built-in check's fix",
         lambda: {(r["Severity"], r["Tool"]) for r in rows} == {("note", "axe")}
         and at("bad.html", "axe:image-alt")[0]["Standard"] == "WCAG 2.0 SC 1.1.1 (A)"
         and at("bad.html", "axe:image-alt")[0]["Fix"] == "sidecar"),
        ("the verdict doesn't count them, and their lines come after it",
         lambda: ran.index("Output check:") < ran.index("axe-core 4.14.0 ran its 63 rules")
         and "axe:" not in ran.split("Output check:")[1].split("axe-core 4.14.0 ran")[0]),
        ("a hostile page's scripts don't run: inline, in a handler, or in a frame's srcdoc",
         lambda: not [r for r in rows if "pwned-onload" in r["Detail"]
                      or "pwned-inline" in r["Detail"] or "pwned-srcdoc" in r["Detail"]]
         and "have scripts of their own, which didn't run, so what they'd show isn't "
             "checked: hostile.html" in ran or fail("got: " + ran)),
        ("its refresh elsewhere canceled, so axe-core checks it, not Chromium's error page",
         lambda: at("hostile.html", "axe:image-alt")
         and not at("hostile.html", "axe:document-title")
         and not at("hostile.html", "axe:html-has-lang")),
        ("its stylesheet and font from elsewhere named, as what may change its look",
         lambda: re.search(r"What \d+ page\(s\) load from elsewhere wasn't loaded, so their "
                           r"colors and sizes may differ from what a reader sees: hostile\.html "
                           r"\(the stylesheet https://example\.com/remote\.css, the font "
                           r"https://fonts\.example\.org/far\.woff2\)", ran)
         or fail("got: " + ran)),
        ("a frame of its folder's checked, and one from elsewhere and the machine's file named "
         "as not checked", lambda: at("hostile.html", "axe:image-alt", "in the frame at")
         and re.search(r"\d frame\(s\) weren't checked, which aren't served from the folder, "
                       r"weren't loaded, or are past the most a page's check takes \(50, five "
                       r"deep\): hostile\.html \(file:///etc/passwd, "
                       r"https://www\.youtube\.com/embed/abc", ran) or fail("got: " + ran)),
        ("nothing of the machine's files read",
         lambda: "root:" not in ran and not [r for r in rows if "root:" in r["Detail"]]),
        ("a page's colors checked again in dark mode, its text there too faint",
         lambda: at("dark.html", "axe:color-contrast", "In dark mode: ")
         and not [r for r in at("dark.html", "axe:color-contrast")
                  if not r["Detail"].startswith("In dark mode: ")]
         and "axe:color-contrast in dark mode, 1.4.3" in ran),
        ("a symbol in a formula in the text's colors, whose contrast axe-core doesn't "
         "measure, left out and counted; text over a picture, which it can't decide, a "
         "person's to judge",
         lambda: re.search(r"\d+ symbol\(s\) in formulas on \d+ page\(s\), whose contrast "
                           r"axe-core doesn't measure since they aren't text, are left out: "
                           r"each takes the colors of the text around its formula\.", ran)
         and [r["Detail"][:70] for r in at("formulas.html", "axe-review:color-contrast")] == [
             "Elements must meet minimum color contrast ratio thresholds (serious), "]
         and "1 element(s), at p:nth-child(3)" in at(
             "formulas.html", "axe-review:color-contrast")[0]["Detail"]
         or fail("got: " + " | ".join(r["Detail"][:150] for r in at(
             "formulas.html", "axe-review:color-contrast")))),
        ("and in dark mode, what it couldn't decide in light mode isn't said again",
         lambda: not [r for r in at("formulas.html", "axe-review:color-contrast")
                      if r["Detail"].startswith("In dark mode")]),
        ("a symbol in a formula with a color of its own a person's to judge",
         lambda: at("colored.html", "axe-review:color-contrast", "1 element(s), at mo")
         or fail("got: " + " | ".join(r["Detail"][:150] for r in at(
             "colored.html", "axe-review:color-contrast")))),
        ("an EPUB's content documents checked, as its own entries, and one not well-formed "
         "named", lambda: [r["Kind"] for r in at("EPUB/text/ch01.xhtml", "axe:image-alt")]
         == ["epub"] and "EPUB/text/ch02.xhtml (it isn't well-formed XHTML, which the EPUB's "
                         "checks report)" in ran or fail("got: " + ran)),
        ("TextbookImprover's presentation checked slide by slide: a picture on its slide, "
         "one in a step, and small text only the slide's background fails, its large title, "
         "which passes once the background has faded in, not",
         lambda: at("ours/deck.html#/two", "axe:image-alt")
         and at("ours/deck.html#/steps", "axe:image-alt")
         and at("ours/deck.html#/gray", "axe:color-contrast")
         and not at("ours/deck.html#/gray", "axe:color-contrast", "h2")
         and not at("ours/deck.html#/one", "axe:image-alt")
         and "20 slide(s) of 5 presentation(s)" in ran or fail("got: " + " | ".join(
             r["Where"] + " " + r["Check"] for r in rows))),
        ("a presentation's script of its own, inline, a handler, a file, or a text file, "
         "doesn't run, and the rest is checked",
         lambda: not [r for r in rows if "pwned" in r["Detail"]]
         and all(at(f"{name}/deck.html#/two", "axe:image-alt")
                 for name in ("inline", "handler", "file", "text"))),
        ("one whose start of reveal.js holds code, or whose reveal.js or oer-reveal.js "
         "isn't the repository's, isn't checked, and says why",
         lambda: "decks/setting/deck.html (its start of reveal.js holds more than settings: "
                 "the setting hash holds (function () {" in ran
         and "decks/revealjs/deck.html (it doesn't load the repository's copy of reveal.js)"
             in ran
         and "decks/oer/deck.html (its oer-reveal.js isn't this version of "
             "TextbookImprover's)" in ran
         and not at("setting/deck.html#/two", "axe:image-alt") or fail("got: " + ran)),
        ("with --verbose, each element a note with its markup, listed under its rule",
         lambda: len([r for r in loud_rows if r["Check"] == "axe:image-alt"]) == 1
         and "its markup, <img src=\"p.png\">" in [r for r in loud_rows
                                                   if r["Check"] == "axe:image-alt"][0]["Detail"]
         and re.search(r"\n    bad\.html at img\[src=\"p\.png\"\]: Fix any of the "
                       r"following: Element does not have an alt attribute", loud)
         or fail("got: " + loud)),
        ("another axe-core, from AXE_CORE_DIR, named in a note",
         lambda: "axe-core 4.13.9, from AXE_CORE_DIR, where the repository's is 4.14.0" in loud),
        ("a page past its time named, and the rest go on",
         lambda: any("good.html (axe-core hadn't finished after 0.001 seconds)" in line
                     for line in past) or fail(" | ".join(past))),
        ("a presentation whose settings make its slides 100,000 pixels square checked in a "
         "smaller window, in its time",
         lambda: re.search(r"axe-core 4\.14\.0 ran [^\n]* on 4 slide\(s\) of 1 "
                           r"presentation\(s\)", huge[0])
         and not any("didn't check" in line or "stopped" in line for line in huge)
         or fail(" | ".join(huge))),
        ("a presentation's slides past the most checked, counted",
         lambda: re.search(r"axe-core 4\.14\.0 ran [^\n]* on 2 slide\(s\) of 1 "
                           r"presentation\(s\)", few[0])
         and any(re.fullmatch(r"2 slide\(s\) weren't checked, after the first 2 of a "
                              r"presentation: \S*deck\.html \(2 of 4\)\.", line)
                 for line in few) or fail(" | ".join(few))),
        ("and a worker past its, stopped, with a warning",
         lambda: stopped == ["WARNING: axe's WCAG checks not run on the pages: the worker that "
                             "runs them failed: it ran past the time it was given, and was "
                             "stopped."] or fail(" | ".join(stopped))),
        ("the policy service refuses to go on without Chromium's sandbox or the network's "
         "namespace, which root can't have",
         lambda: (any("the worker that runs them failed: Chromium's sandbox didn't start: it "
                      "can't start for root" in line for line in service)
                  if os.geteuid() == 0 else
                  service[0].startswith("axe-core 4.14.0 ran") or "failed: " in service[0])
         or fail(" | ".join(service))),
    ] + lockdown + orphans
    return cases


def orphan_cases(deck):
    """The worker ends once the run that started it is gone: a run of a
    presentation of many slides, killed partway, leaves no worker behind
    (axecheck.watch_parent), where without it the worker went on to the
    end. Read from /proc, so Linux's alone."""
    import signal
    import time
    if not os.path.isdir("/proc/self"):
        print("  skip  no /proc: whether the worker outlives its run isn't tried")
        return []
    run = subprocess.Popen([sys.executable, "-c", "import sys, axecheck; "
                            "axecheck.check(sys.argv[1:])", deck],
                           env=dict(os.environ, PYTHONPATH=os.path.join(ROOT, "lib")),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def workers():
        """{pid: its parent's} for each worker running, a zombie aside."""
        found = {}
        for name in os.listdir("/proc"):
            try:
                with open(f"/proc/{name}/cmdline", "rb") as fh:
                    command = fh.read().split(b"\0")
                with open(f"/proc/{name}/stat") as fh:
                    state, parent = fh.read().rsplit(")", 1)[1].split()[:2]
            except (OSError, ValueError):
                continue
            if state != "Z" and b"--worker" in command \
                    and any(part.endswith(b"axecheck.py") for part in command):
                found[int(name)] = int(parent)
        return found
    worker, deadline = None, time.monotonic() + 60
    while worker is None and time.monotonic() < deadline and run.poll() is None:
        worker = next((pid for pid, parent in workers().items() if parent == run.pid), None)
        time.sleep(0.2)
    time.sleep(3)                       # into the slides
    run.kill()
    run.wait()
    gone, deadline = False, time.monotonic() + 15
    while worker and not gone and time.monotonic() < deadline:
        gone = worker not in workers()
        time.sleep(0.25)
    if worker and not gone:
        os.killpg(worker, signal.SIGKILL)
    return [
        ("a worker whose run is killed partway ends too",
         lambda: worker is not None and gone or fail(f"worker {worker}, gone: {gone}")),
    ]


def route_cases(work):
    """The route itself, in this process, with the page's scripts allowed,
    which no check allows: what they try is still kept in, and a link in
    the folder to a file outside it isn't followed. And the worker's way
    off the network, in a process of its own: a loopback and nothing
    else, or the reason it couldn't."""
    import asyncio
    import lockedbrowser
    from playwright.async_api import async_playwright
    served = os.path.join(work, "served")
    os.makedirs(served)
    with open(os.path.join(served, "scripted-out.html"), "w", encoding="utf-8") as fh:
        fh.write('<!DOCTYPE html><html lang="en"><head><title>Out</title></head><body>'
                 '<p id="said">waiting</p><img src="linked-out.png" alt="A link out">'
                 '<script>new WebSocket("wss://ws.example.com/");'
                 'fetch("https://example.com/").catch(() => {});'
                 'const img = document.createElement("img"); img.src = "../../../etc/hostname";'
                 'document.body.append(img); setTimeout(() => location.href = '
                 '"https://elsewhere.example.com/", 50);</script></body></html>')
    outside = os.path.join(work, "outside.png")
    with open(outside, "wb") as fh:
        fh.write(b"outside the folder")
    os.symlink(outside, os.path.join(served, "linked-out.png"))
    left = subprocess.run([sys.executable, "-c", "import lockedbrowser as l; "
                           "print(repr(l.leave_network())); print(l.interfaces())"],
                          capture_output=True, text=True, env=dict(
                              os.environ, PYTHONPATH=os.path.join(ROOT, "lib")))
    seen = {}

    async def go():
        async with async_playwright() as play:
            browser = await play.chromium.launch(args=lockedbrowser.ARGUMENTS)
            context, page, visit = await lockedbrowser.open_page(
                browser, lockedbrowser.Folder(served), "scripted-out.html",
                scripts="'unsafe-inline'")
            await page.wait_for_timeout(600)
            seen.update(url=page.url, refused=list(visit.refused), served=dict(visit.served),
                        canceled=list(visit.canceled),
                        blocked=await lockedbrowser.blocked(page.main_frame))
            await context.close()
            await browser.close()
    asyncio.run(go())
    return [
        ("with the page's scripts allowed, a WebSocket is taken and never connected",
         lambda: ("websocket", "wss://ws.example.com/", "elsewhere") in seen["refused"]
         or fail(f"got: {seen}")),
        ("a fetch elsewhere blocked, and a file outside the folder refused",
         lambda: any(directive == "connect-src" for directive, _ in seen["blocked"])
         and any(why == "not there" for _, _, why in seen["refused"])),
        ("a link in the folder to a file outside it isn't followed",
         lambda: "linked-out.png" not in seen["served"]
         and any(url.endswith("/linked-out.png") and why == "not there"
                 for _, url, why in seen["refused"]) or fail(f"got: {seen}")),
        ("the worker's way off the network leaves a loopback and nothing else, or says why "
         "it couldn't",
         lambda: left.stdout.splitlines() == ["''", "['lo']"]
         or (left.stdout.splitlines()[:1] != ["''"] and left.returncode == 0)
         or fail("got: " + left.stdout + left.stderr)),
        ("and a navigation a script makes canceled, the page where it was",
         lambda: seen["canceled"] == ["https://elsewhere.example.com/"]
         and seen["url"].endswith("/scripted-out.html") or fail(f"got: {seen}")),
    ]


if __name__ == "__main__":
    sys.exit(main())
