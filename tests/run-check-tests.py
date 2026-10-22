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
                                "--math-method=mathml", "-o", out], cwd=work, check=True)
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
    them."""
    tool = os.path.join(ROOT, "bin", "check-output.py")
    fake = fakeverapdf.install(os.path.join(work, "fake"))
    loads = fakeverapdf.modules(os.path.join(work, "loads"))
    unloaded = fakeverapdf.modules(os.path.join(work, "unloaded"), loads=False)
    log = os.path.join(work, "fake.log")
    pdf = os.path.join(work, "book.pdf")
    with open(pdf, "wb") as fh:
        fh.write(pdfcheck.wcag_probe().replace(b"%PDF-1.7", b"%PDF-2.0", 1))

    def run(*flags, folder=None, verapdf=fake, **more):
        env = dict(os.environ, VERAPDF=verapdf, FAKE_VERAPDF_LOG=log, **more)
        env.pop("VERAPDF_WCAG", None)
        if folder:
            env["VERAPDF_WCAG"] = folder
        return subprocess.run([sys.executable, tool, *flags], capture_output=True, text=True,
                              env=env, cwd=work, stdin=subprocess.DEVNULL).stderr

    def calls_since(count):
        with open(log, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh][count:]

    report = os.path.join(work, "wcag.csv")
    ran = run("--wcag", "--pdf", pdf, "--report", report, folder=loads)
    with open(report, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    with open(log, encoding="utf-8") as fh:
        calls = [json.loads(line) for line in fh]
    profiled = [call for call in calls if "-p" in call["args"]]
    others = sum(1 for row in rows if not row["Check"].startswith("verapdf-wcag:"))
    setup = run("--wcag", folder=loads)
    missed = run("--wcag", "--pdf", pdf, folder=unloaded)
    absent = run("--wcag", "--pdf", pdf)
    quick = run("--wcag", "--quick", "--pdf", pdf, folder=loads)
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
        ("--wcag reports the profile's own rules, not PDF/UA's, each failed check a note at "
         "its page, with the criterion as the standard",
         lambda: [(r["Where"], r["Check"], r["Severity"], r["Standard"]) for r in rows
                  if r["Check"].startswith("verapdf")] == [
             ("book.pdf#page=653", "verapdf-wcag:1.3.1-1", "note", "WCAG 2.0 SC 1.3.1 (A)"),
             ("book.pdf#page=3", "verapdf-wcag:2.4.9-1", "note", "WCAG 2.0 SC 2.4.9 (AAA)")]
         or fail("got: " + " | ".join(r["Where"] + " " + r["Check"] for r in rows))),
        ("and the detail says what veraPDF found, the criterion, its Understanding "
         "document, and that the check may be wrong",
         lambda: [r["Detail"] for r in rows if r["Check"] == "verapdf-wcag:2.4.9-1"] == [
             "Links shall contain an alternate description via their Contents or Alt keys or "
             "in the text value: A link annotation does not include an alternate description "
             "in the Contents or Alt Keys or in the text value. 2.4.9 Link Purpose (Link Only) "
             f"(AAA): {url}. veraPDF's WCAG checks are experimental and may be wrong."]),
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
         "the probe and the PDF, and the folder's jars first on its classpath",
         lambda: len(profiled) == 1 and profiled[0]["args"][:6] == [
             "--loglevel", "0", "--nonpdfext", "-p",
             os.path.join(loads, "WCAG-2-2-Machine-PDF20.xml"), "--format"]
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
    ]
    # A PDF the output check finds nothing in of its own: the probe with a
    # title it displays, XMP metadata, and a bookmark.
    try:
        import pikepdf
    except ImportError:
        pikepdf = None
    if pikepdf is not None:
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
        with open(tidy_report, newline="", encoding="utf-8") as fh:
            tidy_rows = list(csv.DictReader(fh))
        cases.append(("veraPDF's WCAG notes alone: nothing found, their lines after, and the "
                      "report written with them",
                      lambda: "Output check: 0 page(s) and 1 PDF(s), nothing found." in alone
                      and f"Written to {tidy_report}." in alone
                      and [r["Check"] for r in tidy_rows] == ["verapdf-wcag:1.3.1-1",
                                                               "verapdf-wcag:2.4.9-1"]
                      or fail("got: " + alone)))
    else:
        print("  skip  no pikepdf to make a PDF the output check finds nothing in")
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


if __name__ == "__main__":
    sys.exit(main())
