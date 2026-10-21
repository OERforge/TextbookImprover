#!/usr/bin/env python3
"""
run-cnx-tests.py -- check unpack-cnx.py: a book written in CNXML read,
assembled, baked as OpenStax bakes it, and cut into pages.

    python3 tests/run-cnx-tests.py

The books are built here, small and made up, in the layout of
OpenStax's osbooks-* repositories and of the Connexions archive's
cnx-user-books ones: a repository of two books whose style one recipe
bakes ("economics"), its preface, chapter, sections, end-of-chapter
pages, answer key, appendix, and index; a book of the archive's, which
no recipe knows; a book whose knowledge checks are exercises from
OpenStax's exercise bank ("marketing"), read from a cache written here,
one of them missing; a book whose problems from the bank are "Problem
1-1" ("organic-chemistry"); a book whose end-of-chapter pages are a
group of their own ("bca"); and a book whose worked examples set their
steps out in tables ("dev-math"), beside the same page baked as
"precalculus". Then baking's steps one at a time, and, with
CNX_COOKBOOK naming a clone of openstax/cookbook, every ported recipe on
cookbook's own sample books. Nothing is fetched; the last case converts
a book and needs Pandoc 3.9 or later.

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

import base64
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from html import unescape

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin")
# The cosmos design's face as an OpenStax book's pdf-layout.yaml names it,
# by its files, and with its math font.
PLEX_SERIF = {"mainfont": "IBMPlexSerif",
              "mainfontoptions": ["Extension=.otf", "UprightFont=*-Regular", "BoldFont=*-Bold",
                                  "ItalicFont=*-Italic", "BoldItalicFont=*-BoldItalic"],
              "mathfont": "IBMPlexMath-Regular.otf"}
PLEX_FILES = ",".join(PLEX_SERIF["mainfontoptions"])
sys.path.insert(0, os.path.join(ROOT, "lib"))

ONE_PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYGAAAAAEAAH2"
    "FzhVAAAAAElFTkSuQmCC")

MODULE = """<?xml version="1.0" encoding="UTF-8"?>
<document xmlns="http://cnx.rice.edu/cnxml"
 xmlns:m="http://www.w3.org/1998/Math/MathML" class="{cls}">
<title>{title}</title>
<metadata xmlns:md="http://cnx.rice.edu/mdml">
<md:uuid>{uuid}</md:uuid>
</metadata>
<content>
{content}
</content>
{glossary}
</document>
"""

COLLECTION = """<?xml version="1.0" encoding="UTF-8"?>
<col:collection xmlns:col="http://cnx.rice.edu/collxml"
 xmlns:md="http://cnx.rice.edu/mdml" xmlns="http://cnx.rice.edu/collxml">
<col:metadata>
<md:title>{title}</md:title>
<md:slug>{slug}</md:slug>
<md:language>en</md:language>
<md:uuid>{uuid}</md:uuid>
<md:license url="http://creativecommons.org/licenses/by/4.0/">Creative
Commons Attribution License</md:license>
</col:metadata>
<col:content>
{content}
</col:content>
</col:collection>
"""


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def module(repo, mid, title, content, cls="", glossary=""):
    uuid = f"00000000-0000-4000-8000-{int(mid[1:]):012d}"
    write(os.path.join(repo, "modules", mid, "index.cnxml"),
          MODULE.format(cls=cls, title=title, uuid=uuid, content=content,
                        glossary=glossary))


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


def unpack(repo, out, *extra):
    return subprocess.run(["python3", os.path.join(BIN, "unpack-cnx.py"),
                           repo, "-o", out, "--offline", *extra],
                          capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)


def report_of(out):
    with open(os.path.join(out, "unpack-report.csv"), encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def flat(html):
    """A page's words, its tags taken out and its spaces evened out."""
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


# A repository of two books, one of them baked as "economics" ------------

def build_trade(repo):
    write(os.path.join(repo, "META-INF", "books.xml"), """<container
 xmlns="https://openstax.org/namespaces/book-container" version="1">
<book slug="tiny-trade" style="economics"
 href="../collections/tiny-trade.collection.xml"/>
<book slug="other-trade" style="economics"
 href="../collections/other-trade.collection.xml"/>
</container>""")
    write(os.path.join(repo, "collections", "tiny-trade.collection.xml"),
          COLLECTION.format(title="Tiny Trade", slug="tiny-trade",
                            uuid="11111111-2222-4333-8444-555555555555",
                            content="""
<col:module document="m10001"/>
<col:subcollection><md:title>Trade and Its Gains</md:title><col:content>
<col:module document="m10002"/>
<col:module document="m10003"/>
<col:module document="m10004"/>
</col:content></col:subcollection>
<col:module document="m10005"/>"""))
    write(os.path.join(repo, "collections", "other-trade.collection.xml"),
          COLLECTION.format(title="Other Trade", slug="other-trade",
                            uuid="11111111-2222-4333-8444-666666666666",
                            content='<col:module document="m10009"/>'))
    os.makedirs(os.path.join(repo, "media"), exist_ok=True)
    with open(os.path.join(repo, "media", "dot.png"), "wb") as fh:
        fh.write(ONE_PIXEL)
    # A file beside the repository, which a module names by a path that
    # climbs out of it, and a link in its media to the same file.
    outside = os.path.join(os.path.dirname(os.path.abspath(repo)), "outside.png")
    with open(outside, "wb") as fh:
        fh.write(ONE_PIXEL)
    try:
        os.symlink(outside, os.path.join(repo, "media", "linked.png"))
    except (OSError, NotImplementedError):
        pass                    # no links here (Windows without the right)
    module(repo, "m10001", "Preface", """
<para id="p1">This small book is for checking an unpacker.</para>""",
           cls="preface")
    module(repo, "m10002", "Introduction to Trade", """
<figure id="splash" class="splash"><media alt="A market stall">
<image mime-type="image/png" src="../../media/dot.png"/></media>
<caption>A market.</caption></figure>
<para id="p1">People trade when both gain.</para>""", cls="introduction")
    module(repo, "m10003", "Why Trade Happens", """
<section id="s1"><title>Comparative Advantage</title>
<para id="p1">A <term id="t1">comparative advantage</term> is a lower
opportunity cost.<footnote id="fn1">An old idea.</footnote></para>
<figure id="fig1"><media alt="A curve rising">
<image mime-type="image/png" src="../../media/dot.png"/></media>
<caption>Gains rise with trade.</caption></figure>
<table id="tab1" summary="Output of two goods by two people">
<title>Output per Hour</title><tgroup cols="2"><thead><row>
<entry>Person</entry><entry>Output</entry></row></thead><tfoot><row>
<entry>Source: a survey</entry><entry/></row></tfoot><tbody>
<row><entry>Ann</entry><entry>4</entry></row></tbody></tgroup></table>
<para id="p7">As one study found.<note id="n2" class="reference"
display="inline">Smith, J. (2020). <emphasis effect="italics">A
Book</emphasis>.</note></para>
<table id="tab2" summary="Hours worked by each person">
<tgroup cols="2"><thead><row><entry>Person</entry><entry>Hours</entry>
</row></thead><tbody><row><entry>Bo</entry><entry>8</entry></row>
</tbody></tgroup></table>
<note id="n1" class="linkup"><title>Trading <term id="t3">Posts</term></title>
<para id="p2">Read more at
<link url="https://example.org/trade">a site</link>, Zoë's.</para>
<note id="n7" class="linkup"><title>Inner Posts</title>
<para id="p12">A note inside a note.</para></note></note>
<note id="n3" class="linkup"><title>Link It <term id="t4">Up</term></title>
<para id="p8">A title that only repeats the note's kind.</para></note>
<note id="n4" class="linkup"><title>Link It Up: Markets Meet</title>
<para id="p9">A title that opens with the note's kind.</para></note>
<note id="n5" class="linkup"><title>Link it up: Prices Meet</title>
<para id="p10">A title that opens with the note's kind in other case.</para></note>
<note id="n6" class="linkup"><title>Link It Ups and Downs</title>
<para id="p11">A title that opens with the kind's words in a longer one.</para></note>
<para id="p13">Since \uF061 is small, the change is \uF02D2\uF0BEa loss, if a
small one.</para>
<equation id="eq1"><m:math><m:mi>x</m:mi><m:mo>=</m:mo><m:mn>2</m:mn>
</m:math></equation>
</section>
<section id="sum1" class="summary"><title>Summary</title>
<para id="p3">Trade follows advantage.</para></section>
<section id="sc1" class="self-check-questions"><title>Self-Check</title>
<exercise id="e1"><problem id="pr1"><para id="p4">What is an
advantage?</para></problem><solution id="so1"><para id="p5">A lower
cost.</para>
<table id="tab4" class="unnumbered" summary="A dot, laid out">
<tgroup cols="1"><tbody><row><entry><media alt="A dot"><image
mime-type="image/png" src="../../media/dot.png"/></media></entry></row>
</tbody></tgroup></table>
<table id="tab3" class="unnumbered" summary="The cost of each choice\uF0BEtrade or not">
<tgroup cols="2"><tbody><row><entry>Choice</entry><entry>Cost</entry>
</row><row><entry>Trade</entry><entry>2</entry></row></tbody></tgroup>
</table></solution></exercise></section>
<section id="rq1" class="review-questions"><title>Review</title>
<exercise id="e2"><problem id="pr2"><para id="p6">Why trade?</para>
</problem></exercise></section>""", glossary="""
<glossary><definition id="d1"><term>zero-sum game</term><meaning
id="m1">a game no side gains from</meaning></definition>
<definition id="d2"><term>
comparative advantage</term><meaning id="m2">the lower opportunity
cost</meaning></definition>
<definition id="d3"><term>barter</term><meaning id="m3">trade without
money</meaning></definition></glossary>""")
    module(repo, "m10004", "Gains from Trade", """
<para id="p1">As <link document="m10003" target-id="fig1"/> shows, and
<link document="m10003" target-id="tab1"/> lists, both gain; see
<link document="m10003"/>, and <link document="m10009"/>, in another
book. A <term id="t1">barter</term> needs no
money. Missing: <media alt="gone"><image mime-type="image/png"
src="../../media/missing.png"/></media> Outside: <media alt="out"><image
mime-type="image/png" src="../../../outside.png"/></media> Linked: <media
alt="linked"><image mime-type="image/png" src="../../media/linked.png"/></media></para>
<para id="p2">The items: <list id="l1" list-type="enumerated"
number-style="lower-alpha" display="inline"><item>apples</item>
<item>pears</item></list>.</para>
<list id="l2"><title id="lt2">Steps</title><item>Trade.</item></list>
<para id="p6">Follow <link target-id="lt2">the steps</link>.</para>
<para id="p3">A talk: <media id="v1" alt="A talk on trade"><iframe
src="https://www.youtube.com/embed/abc123" width="660"
height="370.5"/></media></para>
<para id="p4">More at www.example.org/trade, not at
https://doi.org:10.1016/x.1.</para>
<para id="p5">To add them up: <code class="python">a = 1<newline/>
b = 2</code></para>
<code id="c1" class="python line-numbering">
    total = 0
    for gain in gains:
        total += gain
    </code>
<code id="c2" display="block">first<newline/>
second</code>
<code id="c3" class="python inline-code">sum()</code>
<code id="c4">
    Name? <emphasis effect="bold">Ann</emphasis>
      Hi, Ann
    </code>""", glossary="""
<glossary><definition id="d4"><term>barter</term><meaning id="m4">swapping
goods for goods</meaning></definition></glossary>""")
    module(repo, "m10005", "Some Math", """
<para id="p1">Algebra, briefly: <m:math><m:apply><m:eq/><m:ci>y</m:ci>
<m:apply><m:times/><m:apply><m:plus/><m:ci>a</m:ci><m:cn>1</m:cn>
</m:apply><m:ci>x</m:ci></m:apply></m:apply></m:math>, and
<m:math><m:apply><m:int/><m:ci>x</m:ci></m:apply></m:math>.</para>
<equation id="eq2"><m:math><m:mstyle><m:mi>v</m:mi><m:mo>=</m:mo>
<m:mfrac><m:mi>b</m:mi><m:mi>p</m:mi></m:mfrac><m:mspace linebreak="newline"/>
<m:mo>(</m:mo><m:mi>w</m:mi><m:mo>)</m:mo></m:mstyle></m:math></equation>
<para id="p5">Steps: <m:math><m:mrow><m:mi>x</m:mi><m:mo>=</m:mo><m:mn>1</m:mn>
<m:mspace linebreak="newline" indentalign="id"/><m:mi>y</m:mi><m:mo>=</m:mo>
<m:mn>2</m:mn><m:mspace linebreak="newline"/></m:mrow></m:math>.</para>
<para id="p6">Scripts of the wrong number of parts: <m:math><m:mn>0,006</m:mn>
<m:msup><m:mi mathvariant="normal">°</m:mi><m:mi mathvariant="normal">C</m:mi>
<m:mrow><m:mo>−</m:mo><m:mn>1</m:mn></m:mrow></m:msup></m:math>, <m:math>
<m:mfrac><m:msup><m:mn>2,00</m:mn><m:mi>t</m:mi><m:mn>2</m:mn></m:msup>
<m:mn>3</m:mn></m:mfrac></m:math>, <m:math><m:msub><m:mi>R</m:mi><m:mn>0</m:mn>
<m:mspace width="0.2em"/></m:msub><m:mi>Ω</m:mi></m:math>, and <m:math><m:mrow>
<m:msup><m:mi>N</m:mi></m:msup></m:mrow></m:math>.</para>
<section id="s2"><title/><para id="p2">Untitled.</para>
<section id="s3"><title>Inside</title><para id="p4">Within.</para></section>
</section>
<note id="n9" class="linkup"><title/><para id="p3">A bare note.</para></note>""",
           cls="appendix")
    module(repo, "m10009", "Elsewhere", """
<para id="p1">Another book.</para>""")


def case_trade(work):
    repo = os.path.join(work, "osbooks-trade")
    build_trade(repo)
    listed = subprocess.run(["python3", os.path.join(BIN, "unpack-cnx.py"),
                             repo, "--list"], capture_output=True, text=True)
    no_book = unpack(repo, os.path.join(work, "none"))
    out = os.path.join(work, "trade")
    result = unpack(repo, out, "--book", "tiny-trade")
    again = unpack(repo, out, "--book", "tiny-trade")
    import yaml
    project = yaml.safe_load(read(out, "project.yaml"))["project"]
    conversion = yaml.safe_load(read(out, "conversion.yaml"))
    layout = yaml.safe_load(read(out, "pdf-layout.yaml")) \
        if os.path.exists(os.path.join(out, "pdf-layout.yaml")) else {}
    names = sorted(n[:-5] for n in os.listdir(out) if n.endswith(".html"))
    section = read(out, "1-1-why-trade-happens.html")
    gains = read(out, "1-2-gains-from-trade.html")
    intro = read(out, "1-introduction-to-trade.html")
    glossary = read(out, "1-key-terms.html")
    selfcheck = read(out, "1-self-check-questions.html")
    key = read(out, "chapter-1.html")
    index = read(out, "index.html")
    report = report_of(out)
    with open(os.path.join(out, "table-captions.csv"), encoding="utf-8") as fh:
        captions = list(csv.DictReader(fh))
    return [
        ("--list names the repository's books and their styles; a "
         "repository of two needs --book",
         lambda: "tiny-trade  (style: economics)" in listed.stdout
         and no_book.returncode != 0 and "name one" in no_book.stderr),
        ("every page OpenStax makes, named as OpenStax names it",
         lambda: result.returncode == 0 and names == [
             "1-1-why-trade-happens", "1-2-gains-from-trade",
             "1-introduction-to-trade", "1-key-concepts-and-summary",
             "1-key-terms", "1-review-questions", "1-self-check-questions",
             "a-some-math", "chapter-1", "index", "preface", "references"]),
        ("each page's title is its one h1, first, numbered as baked",
         lambda: section.count("<h1") == 1
         and "<h1>1.1 Why Trade Happens</h1>" in section
         and re.search(r"<body><h1>Introduction to Trade</h1>", intro)),
        ("a figure and a table are numbered in their chapter (the opening "
         "picture is its Figure 1.1), the table's label and title its caption",
         lambda: '<span class="os-label">Figure 1.2</span>' in section
         and "<caption><span class=\"os-label\">Table 1.1</span>" in section
         and "Output per Hour" in section),
        ("a link baking names shows the name, and goes to the page its "
         "target is on",
         lambda: '<a href="1-1-why-trade-happens.html#fig1"' in gains
         and ">Figure 1.2</a>" in gains and ">Table 1.1</a>" in gains
         and ">1.1 Why Trade Happens</a>" in gains),
        ("a link to a module of another book of the repository goes to "
         "its page at openstax.org, named as OpenStax names it",
         lambda: '<a href="https://openstax.org/books/other-trade/pages/'
         'elsewhere">Elsewhere</a>' in gains),
        ("a note is a box, headed a level down by its kind, which its class "
         "names, and its own title, in one heading, the kind in a span of its "
         "own; and a heading baking wrote in spans keeps what it holds: a "
         "term in the note's title keeps its id, which the index links to",
         lambda: re.search(r'<div class="os-note linkup box"[^>]*><h3><span '
                           r'class="os-note-label">Link It Up</span>: Trading '
                           r'<strong><span class="os-term" id="t3">Posts'
                           r'</span></strong></h3>', section)
         and 'href="1-1-why-trade-happens.html#t3"' in index),
        ("a note whose title only repeats its kind is headed by its kind alone, "
         "an id the title held kept as an anchor",
         lambda: '<div class="os-note linkup box" id="n3"><h3>Link It Up<span '
         'id="t4"></span></h3>' in section),
        ("and one whose title opens with its kind by its title alone, in any "
         "case, but not one whose title opens with a longer word",
         lambda: '<div class="os-note linkup box" id="n4"><h3>Link It Up: Markets '
         'Meet</h3>' in section
         and '<div class="os-note linkup box" id="n5"><h3>Link it up: Prices '
         'Meet</h3>' in section
         and '<div class="os-note linkup box" id="n6"><h3><span class="os-note-label">'
         'Link It Up</span>: Link It Ups and Downs</h3>' in section),
        ("the title is in the heading alone, not in the note again, and no "
         "id is on the page twice",
         lambda: section.count("Trading") == 1 and section.count('id="t3"') == 1
         and len(re.findall(r' id="([^"]+)"', section))
         == len(set(re.findall(r' id="([^"]+)"', section)))),
        ("what a note holds is a level under its one heading, a note inside it "
         "too",
         lambda: re.search(r'<h3><span class="os-note-label">Link It Up</span>: '
                           r'Trading .*?</h3>\s*<p id="p2">.*?</p>\s*<div '
                           r'class="os-note linkup box" id="n7"><h4><span '
                           r'class="os-note-label">Link It Up</span>: Inner '
                           r'Posts</h4>', section, re.S)),
        ("the unpacker says how many notes are boxes, and how many baking "
         "headed by two headings are headed by one, which way",
         lambda: "7 note(s) made boxes" in result.stdout
         and "6 note(s) that baking headed by their kind and, under it, their "
         "own title are headed by one heading: 3 by both" in " ".join(
             result.stdout.split())
         and "1 by their kind alone" in result.stdout
         and "2 by their title alone" in result.stdout),
        ("a character of the Symbol font, which Word writes in the private use area, is "
         "the character the font draws, its horizontal line an em dash, and each is "
         "reported as taken for the Symbol font's, a table's summary's too",
         lambda: "Since α is small, the change is −2—a loss, if a" in section
         and not re.search("[\uF000-\uF0FF]", section)
         and sorted(r["Detail"] for r in report if r["Check"] == "symbol-font-character")
         == ["U+F02D (1), taken as the Symbol font's, made − (U+2212, minus sign)",
             "U+F061 (1), taken as the Symbol font's, made α (U+03B1, greek small "
             "letter alpha)",
             "U+F0BE (1) in the summary of chapter-1#table-1, taken as the Symbol "
             "font's, made — (U+2014, em dash)",
             "U+F0BE (1), taken as the Symbol font's, made — (U+2014, em dash)"]),
        ("a reference written as a note, which a references page lists, isn't a box",
         lambda: '<div class="os-note reference" id="n2">' in section),
        ("the words are composed (NFC), as HTML wants them",
         lambda: "Zoë's" in section and "̈" not in section),
        ("a footnote is a note as Pandoc writes one",
         lambda: 'role="doc-noteref" href="#fn1"' in section
         and '<section role="doc-endnotes" class="footnotes"><ol><li '
         'id="fn1">' in section),
        ("an equation is numbered, its MathML unprefixed",
         lambda: "<math" in section and "m:math" not in section
         and "1.1" in flat(section.split("<math")[-1])),
        ("a table's foot, which CNXML writes before its body, comes "
         "after it, as HTML has it",
         lambda: re.search(r"</tbody><tfoot><tr><td>Source: a survey",
                           section)),
        ("a note that opens with text keeps it",
         lambda: "Smith, J. (2020). <em>A Book</em>." in
         re.sub(r"\s+", " ", section)),
        ("an inline enumerated list is lettered and separated",
         lambda: "a. apples; b. pears" in flat(gains)),
        ("a list's title keeps its id, which a link names",
         lambda: '<p class="os-list-title" id="lt2"><strong>Steps</strong>'
         in gains and 'href="#lt2"' in gains
         and not any(r["Check"] == "link-to-nothing" for r in report)),
        ("code standing apart is a block, without the indentation of the "
         "source's markup, its lines numbered if OpenStax numbers them; "
         "a newline element and the line break after it are one",
         lambda: '<pre class="python line-numbering numberLines" id="c1">'
         '<code class="python line-numbering">total = 0\nfor gain in gains:'
         '\n    total += gain</code></pre>' in gains
         and '<pre id="c2"><code>first\nsecond</code></pre>' in gains),
        ("code in a line of text, or of class inline-code, is inline",
         lambda: '<code class="python">a = 1<br/>' in gains
         and '<code class="python inline-code" id="c3">sum()</code>'
         in gains and "<pre" not in gains.split('id="c2"')[1]),
        ("a block of code holding bold (a program's example input) is a "
         "paragraph of code, line by line, its indentation kept",
         lambda: '<p id="c4"><code>Name? <strong>Ann</strong><br/>\u00a0\u00a0'
         'Hi, Ann</code></p>' in gains),
        ("an address written as text is a link, as OpenStax's baking "
         "makes one, unless a typo has made it no address (a port that "
         "isn't a number)",
         lambda: '<a href="https://www.example.org/trade">'
         'www.example.org/trade</a>, not' in gains
         and "https://doi.org:10.1016/x.1." in gains
         and 'href="https://doi.org:' not in gains),
        ("a formula in content MathML is made presentation MathML, "
         "parentheses where they're needed; one that can't be is "
         "reported",
         lambda: "<mi>y</mi><mo>=</mo><mrow><mrow><mo>(</mo><mrow><mi>a"
         "</mi><mo>+</mo><mn>1</mn></mrow><mo>)</mo></mrow><mo>\u00d7"
         "</mo><mi>x</mi></mrow>" in read(out, "a-some-math.html")
         and [r["Check"] for r in report].count("content-mathml") == 1),
        ("a script of the wrong number of parts, which texmath rejects, is "
         "a base and its script, what's before them set before them and a "
         "space after them after, in a row where it stood for an argument; "
         "one of one part is its base alone; each is reported",
         lambda: all(part in re.sub(r">\s+<", "><", read(out, "a-some-math.html"))
                     for part in (
             '<mn>0,006</mn><mi mathvariant="normal">°</mi><msup><mi '
             'mathvariant="normal">C</mi><mrow><mo>−</mo><mn>1</mn></mrow>'
             '</msup></math>',
             '<mfrac><mrow><mn>2,00</mn><msup><mi>t</mi><mn>2</mn></msup>'
             '</mrow><mn>3</mn></mfrac>',
             '<msub><mi>R</mi><mn>0</mn></msub><mspace width="0.2em"/>'
             '<mi>Ω</mi>',
             '<mrow><mi>N</mi></mrow></math>'))
         and [r["Check"] for r in report].count("script-repaired") == 4),
        ("and Pandoc reads each as a formula, where it kept their text",
         lambda: re.search(r"parts: \\\(0,006\S*C\^\{- ?1\}\\\), \\\(\\frac\{"
                           r"2,00t\^\{2\}\}\{3\}\\\), \\\(R_\{0\}\S* \\Omega\\\), "
                           r"and \\\(N\\\)\.", " ".join(subprocess.run(
                               ["pandoc", "-f", "html", "-t", "latex",
                                os.path.join(out, "a-some-math.html")],
                               capture_output=True, text=True).stdout.split()))
         if shutil.which("pandoc") else True),
        ("a formula's forced line breaks make its lines the rows of a "
         "table of one column, centered in an equation and set at the left "
         "in a paragraph, a break at the end no row",
         lambda: '<mtable columnalign="center"><mtr><mtd><mrow><mi>v</mi>'
         '<mo>=</mo><mfrac><mi>b</mi><mi>p</mi></mfrac></mrow></mtd></mtr>'
         '<mtr><mtd><mrow><mo>(</mo><mi>w</mi><mo>)</mo></mrow></mtd></mtr>'
         '</mtable>' in read(out, "a-some-math.html")
         and '<mtable columnalign="left"><mtr><mtd><mrow><mi>x</mi><mo>=</mo>'
         '<mn>1</mn></mrow></mtd></mtr><mtr><mtd><mrow><mi>y</mi><mo>=</mo>'
         '<mn>2</mn></mrow></mtd></mtr></mtable>' in read(out, "a-some-math.html")
         and "linebreak" not in read(out, "a-some-math.html")),
        ("and Pandoc reads each line as a row, where it dropped the breaks",
         lambda: (lambda tex: re.search(r"v = \\frac\{b\}\{p\}\}?\s*\\\\\s*\(w\)", tex)
                  and re.search(r"x = 1\}?\s*\\\\\s*\{?y = 2", tex))(subprocess.run(
                      ["pandoc", "-f", "html", "-t", "latex",
                       os.path.join(out, "a-some-math.html")],
                      capture_output=True, text=True).stdout)
         if shutil.which("pandoc") else True),
        ("an empty title is no heading, its id kept on an anchor, and its "
         "section no level of the outline",
         lambda: '<div id="s2"></div>' in read(out, "a-some-math.html")
         and not re.search(r"<h[1-6][^>]*>\s*</h[1-6]>",
                           read(out, "a-some-math.html"))
         and '<h2 id="s3">Inside</h2>' in read(out, "a-some-math.html")),
        ("a frame's size is whole pixels, a half rounded up, as "
         "html-raw.lua rounds it",
         lambda: [('width="660"' in tag, 'height="371"' in tag)
                  for tag in re.findall(r"<iframe[^>]*>", gains)]
         == [(True, True)]),
        ("the key terms are sorted as CLDR sorts them, a term that opens "
         "with a line break first",
         lambda: [flat(t) for t in re.findall(r"<dt>(.*?)</dt>", glossary,
                                               re.S)]
         == ["comparative advantage", "barter", "zero-sum game"]),
        ("a term two sections define is one term with both meanings, the "
         "second's id kept at its meaning's head",
         lambda: re.search(r'barter</dt>\s*<dd[^>]*>swapping goods for goods'
                           r'</dd>\s*<dd[^>]*><span id="d3"></span>trade '
                           r'without money</dd>',
                           re.sub(r"\s+", " ", glossary))),
        ("an exercise is numbered, linking to its solution in the answer "
         "key, which links back",
         lambda: '<a href="chapter-1.html#e1-solution" class="os-number">1'
         '</a>. What is' in re.sub(r"\s+", " ", selfcheck)
         and '<a href="1-self-check-questions.html#e1" class="os-number">1'
         '</a>. A lower cost.' in re.sub(r"\s+", " ", key)),
        ("the index lists each term under its letter, linking to where "
         "it's defined",
         lambda: "<h2>B</h2>" in index and "<h2>C</h2>" in index
         and 'href="1-1-why-trade-happens.html#t1"' in index),
        ("a module's ids lose their prefix on their page",
         lambda: 'id="fig1"' in section and "m10003__" not in section),
        ("project.yaml: the collection's title, an identifier from its "
         "UUID, OpenStax as publisher, the outline as contents",
         lambda: project["title"] == "Tiny Trade"
         and project["identifier"]
         == "book-11111111-2222-4333-8444-555555555555"
         and project["publisher"] == "OpenStax"
         and project["contents"][1]["title"]
         == "Chapter 1 Trade and Its Gains"),
        ("an OpenStax book's pages carry the attribution OpenStax asks for, in its "
         "words, not a link",
         lambda: conversion["defaults"]["footer"] == "Access for free at openstax.org."),
        ("its PDF has the PDF target's default page, OpenStax's paper and margins with "
         "12pt type, copied into the book's folder to be changed there, every setting "
         "the default's but the face, under a comment saying where it came from",
         lambda: conversion["defaults"]["pdf"] == {"metadata": "pdf-layout.yaml"}
         and layout == dict(yaml.safe_load(read(BIN, "pdf-layout.yaml")), **PLEX_SERIF)
         and layout["fontsize"] == "12pt" and layout["ragged-right"] is True
         and read(out, "pdf-layout.yaml").startswith("# Written by unpack-cnx.py from ")
         and "# copied here to be changed for this book" in read(out, "pdf-layout.yaml")),
        ("its text is in OpenStax's face for its design, cosmos's IBM Plex Serif, named by "
         "its files, and its formulas in IBM Plex Math, whose letters are Plex Serif's, "
         "the file says",
         lambda: "# The text in IBM Plex Serif, as OpenStax sets this book in its cosmos\n"
         in read(out, "pdf-layout.yaml")
         and "# by its files, so the build stops if one isn't installed. Formulas in IBM\n"
         "# Plex Math, whose letters are Plex Serif's.\nmainfont: IBMPlexSerif\n"
         "mainfontoptions:\n  - Extension=.otf\n  - UprightFont=*-Regular\n"
         in read(out, "pdf-layout.yaml")),
        ("its notes are numbered through each chapter, as OpenStax numbers "
         "them, and its captions' words are TextbookImprover's own",
         lambda: "  notes:\n    numbering: group\n" in read(out, "conversion.yaml")
         and "captions:" not in read(out, "conversion.yaml")),
        ("a table whose caption is its label alone is described from its "
         "summary, and one with no caption is too, under its place on its "
         "page, a table of pictures not counted",
         lambda: [c["Label"] for c in captions]
         == ["Table 1.2", "chapter-1#table-1"]
         and [c["Description"] for c in captions]
         == ["Hours worked by each person", "The cost of each choice—trade or not"]
         and captions[1]["Excerpt"] == "Choice"),
        ("media are copied; one the module names that isn't there is "
         "reported, its description in its place",
         lambda: os.path.exists(os.path.join(out, "media", "dot.png"))
         and any(r["Check"] == "media-missing" for r in report)
         and "[gone: missing]" in gains and "missing.png" not in gains),
        ("a file outside the repository, named by a path that climbs out of "
         "it or by a link in it, isn't copied, and is reported as missing",
         lambda: not any(name in ("outside.png", "linked.png")
                         for _, _, names in os.walk(out) for name in names)
         and any(r["Check"] == "media-missing"
                 and r["Detail"].startswith("media/m10004/outside.png") for r in report)
         and (not os.path.islink(os.path.join(repo, "media", "linked.png"))
              or any(r["Check"] == "media-missing"
                     and r["Detail"].startswith("media/linked.png") for r in report))
         and "[out:" in gains),
        ("a directory that already holds a book is refused",
         lambda: again.returncode != 0 and "not empty" in again.stderr),
    ]


# A book of the Connexions archive's, which no recipe knows ---------------

def case_archive(work):
    repo = os.path.join(work, "cnx-user-book")
    write(os.path.join(repo, "collections", "a-course.collection.xml"),
          COLLECTION.format(title="A Course", slug="", uuid="", content="""
<col:subcollection><md:title>Week One</md:title><col:content>
<col:module document="m20001"/></col:content></col:subcollection>"""))
    os.makedirs(os.path.join(repo, "media"), exist_ok=True)
    module(repo, "m20001", "Getting Started", """
<figure id="f1"><media alt="A dot"><image mime-type="image/png"
src="dot.png"/></media><caption>A dot.</caption></figure>
<note id="n1"><title>Watch Out</title><para id="p1">Careful.</para></note>
<para id="p2">See <link url="www.example.org">the site</link>.</para>
<para id="p3"><media alt="A photograph"><image mime-type="image/png"
src="../../media/photo.png"/></media> <media alt="A scan"><image
mime-type="image/jpeg" src="../../media/scan.jpg"/></media></para>
<table id="t1" summary=""><tgroup cols="2"><colspec colname="c1"/>
<colspec colname="c2"/><tbody><row><entry namest="c1" nameend="c2">A
source</entry></row><row><entry namest="c1"
nameend="c2">Another</entry></row></tbody></tgroup></table>
""", glossary="""<glossary><definition id="g1"><term>dot</term><meaning
id="gm1">a point</meaning></definition><definition id="g2"><term>dot</term>
<meaning id="gm2">a small spot</meaning></definition></glossary>""")
    with open(os.path.join(repo, "modules", "m20001", "dot.png"), "wb") as fh:
        fh.write(ONE_PIXEL)
    # A JPEG named .png, and a JPEG's bytes each written as two, as text
    # read in Latin-1 and written in UTF-8 (two files in the biology
    # bundle's media, which no page names).
    with open(os.path.join(repo, "media", "photo.png"), "wb") as fh:
        fh.write(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + bytes(20))
    with open(os.path.join(repo, "media", "scan.jpg"), "wb") as fh:
        fh.write("\xff\xd8\xff\xe0\x00\x10JFIF".encode("utf-8"))
    out = os.path.join(work, "course")
    result = unpack(repo, out)
    import yaml
    project = yaml.safe_load(read(out, "project.yaml"))["project"]
    page = read(out, "getting-started.html")
    return [
        ("a repository with no list of books is its collection's book",
         lambda: result.returncode == 0
         and project["title"] == "A Course"),
        ("with no recipe, a figure is numbered in its page, and nothing "
         "moves",
         lambda: '<span class="os-label">Figure 1</span>' in page
         and not os.path.exists(os.path.join(out, "1-key-terms.html"))),
        ("a note keeps its own title, as a heading",
         lambda: "<h2>Watch Out</h2>" in page),
        ("its glossary stays on its page, a term defined twice one term "
         "with both meanings",
         lambda: re.search(r'<dt><span id="g1"></span>dot</dt><dd[^>]*>a '
                           r'point</dd><dd[^>]*><span id="g2"></span>a small '
                           r'spot</dd>', re.sub(r"\s+", " ", page))),
        ("a file kept beside its module is copied under media/, in a "
         "directory named for the module",
         lambda: 'src="media/m20001/dot.png"' in page
         and os.path.exists(os.path.join(out, "media", "m20001", "dot.png"))),
        ("no footer and no layout for a book that isn't OpenStax's",
         lambda: not os.path.exists(os.path.join(out, "conversion.yaml"))
         and not os.path.exists(os.path.join(out, "pdf-layout.yaml"))),
        ("a web address written without its scheme is linked with it, "
         "and reported",
         lambda: '<a href="https://www.example.org">the site</a>' in page
         and any(r["Check"] == "link-without-scheme"
                 for r in report_of(out))),
        # A reading system goes by the extension, and epubcheck rejected
        # the file (OPF-029: Precalculus 2e's two JPEGs named .png).
        ("a picture in another format than its name says is named for its "
         "bytes, and one whose bytes are no picture is reported",
         lambda: 'src="media/photo.jpg"' in page
         and os.path.exists(os.path.join(out, "media", "photo.jpg"))
         and not os.path.exists(os.path.join(out, "media", "photo.png"))
         and [(r["Check"], r["Detail"].split(":")[0])
              for r in report_of(out) if "image" in r["Check"]
              or "extension" in r["Check"]]
         == [("extension-corrected", "media/photo.png"),
             ("image-is-not-an-image", "media/scan.jpg")]),
        ("a table's column no cell begins in is closed up: two columns "
         "each row spans both are one",
         lambda: "<td>A source</td>" in re.sub(r"\s+", " ", page)
         and "colspan" not in page),
    ]


# Exercises from OpenStax's exercise bank ----------------------------------

def bank_item(nickname, stem, choices, right, solution):
    return {"total_count": 1, "items": [{
        "nickname": nickname, "version": 1, "uid": "1@1",
        "solutions_are_public": True, "tags": [], "stimulus_html": "",
        "questions": [{
            "id": 501, "formats": ["multiple-choice"],
            "is_answer_order_important": False, "stimulus_html": "",
            "stem_html": stem,
            "answers": [{"id": 600 + i, "content_html": text,
                         "correctness": "1.0" if i == right else "0.0",
                         "feedback_html": "Why: " + text}
                        for i, text in enumerate(choices)],
            "collaborator_solutions": [{"solution_type": "detailed",
                                        "content_html": solution}]}]}]}


def case_bank(work):
    repo = os.path.join(work, "osbooks-selling")
    write(os.path.join(repo, "META-INF", "books.xml"), """<container
 xmlns="https://openstax.org/namespaces/book-container" version="1">
<book slug="tiny-selling" style="marketing"
 href="../collections/tiny-selling.collection.xml"/></container>""")
    write(os.path.join(repo, "collections", "tiny-selling.collection.xml"),
          COLLECTION.format(title="Tiny Selling", slug="tiny-selling",
                            uuid="22222222-2222-4333-8444-555555555555",
                            content="""
<col:subcollection><md:title>Getting Going</md:title><col:content>
<col:module document="m30001"/>
<col:subcollection><md:title>Selling Basics</md:title><col:content>
<col:module document="m30002"/><col:module document="m30003"/>
</col:content></col:subcollection></col:content></col:subcollection>"""))
    module(repo, "m30001", "Unit Opener", """
<para id="p1">Here we go.</para>""", cls="unit-opener")
    module(repo, "m30002", "In Focus", """
<para id="p1">A shop opens.</para>""", cls="introduction")
    module(repo, "m30003", "What Selling Is", """
<section id="lo" class="learning-objectives"><title>Learning
Outcomes</title><list id="l1"><item>Define selling.</item>
<item>Name a seller.</item></list></section>
<para id="p1">Selling is offering.<cite id="c1" target-id="r1"><note
class="delete-me" display="inline" id="dm"/></cite></para>
<section id="kc" class="knowledge-check"><title>Knowledge Check</title>
<exercise id="x1"><problem id="pr1"><para id="pp1"><link class="os-embed"
url="#exercise/TEST_KC1"/></para></problem></exercise>
<exercise id="x2"><problem id="pr2"><para id="pp2"><link class="os-embed"
url="#exercise/TEST_KC2"/></para></problem></exercise></section>
<section id="refs" class="references"><title>Endnotes</title>
<note id="r1"><link target-id="c1"><span>9.</span></link><span>A
source, 2020.</span></note></section>""")
    cache = os.path.join(work, "cache")
    write(os.path.join(cache, "public", "nickname", "TEST_KC1.json"),
          json.dumps(bank_item("TEST_KC1", "What does a seller offer?",
                               ["Nothing", "Goods", "Silence"], 1,
                               'A seller offers goods: <span data-math='
                               '"x^{2}"></span>.')))
    out = os.path.join(work, "selling")
    result = unpack(repo, out, "--exercises-cache", cache)
    names = sorted(n[:-5] for n in os.listdir(out) if n.endswith(".html"))
    section = read(out, "1-1-what-selling-is.html")
    key = read(out, "chapter-1.html")
    refs = read(out, "1-references.html")
    report = report_of(out)
    return [
        ("a unit's own page is named for the unit's number; the answer key "
         "has a page per chapter",
         lambda: result.returncode == 0 and names == [
             "1-1-what-selling-is", "1-in-focus", "1-references",
             "1-unit-opener", "chapter-1"]),
        ("the unit is a part in contents, so its chapters number their "
         "notes apart",
         lambda: re.search(r'- title: "Unit 1 Getting Going"\n +type: part\n',
                           read(out, "project.yaml"))
         and not re.search(r'Selling Basics"\n +type: part',
                           read(out, "project.yaml"))),
        ("the chapter's introduction opens with its outline, each section "
         "a link",
         lambda: "<h2>Chapter Outline</h2>" in read(out, "1-in-focus.html")
         and '<a class="os-chapter-objective" href="1-1-what-selling-is.html">'
         in read(out, "1-in-focus.html")
         and "1.1 What Selling Is" in flat(read(out, "1-in-focus.html"))),
        ("learning outcomes numbered by place are a numbered list, the "
         "numbers its own, where baking wrote each as a word in a bulleted "
         "item",
         lambda: re.search(r'<ol id="l1" class="os-abstract"><li>Define selling\.'
                           r'</li><li>Name a seller\.</li></ol>', section)
         and "os-abstract-token" not in section),
        ("an exercise from the bank is put in, numbered, its choices "
         "lettered, its feedback gone",
         lambda: '<a href="chapter-1.html#auto_m30003_501-solution" '
         'class="os-number">1</a>. What does a seller offer?' in section
         and '<ol type="a" class="os-choices"><li>Nothing</li><li>Goods'
         '</li>' in section and "Why:" not in section),
        ("its solution goes to the answer key under the section's number, "
         "the right letter first",
         lambda: "<h2>1.1 Knowledge Check</h2>" in key
         and 'class="os-number">1</a>. <span class="answer-letters">b.</span>'
         ' A seller offers goods:' in key),
        ("its formula, TeX in the bank, is MathML (with Pandoc to read it), "
         "or is left as TeX and reported",
         lambda: ("<msup><mi>x</mi><mn>2</mn></msup>" in key)
         if shutil.which("pandoc") else
         ("x^{2}" in key and any(r["Check"] == "exercise-tex"
                                  for r in report))),
        ("one the cache doesn't have says so where it would stand, and is "
         "reported",
         lambda: "TEST_KC2" in section and "couldn't be put in" in section
         and any(r["Check"] == "exercise-missing" for r in report)),
        ("a citation is numbered through the chapter, its endnote moved "
         "to the chapter's references and numbered to match",
         lambda: '<sup class="os-end-note-number">1</sup>' in section
         and "1. A source, 2020." in flat(refs)),
    ]


# Organic Chemistry's problems and pages ------------------------------------

def case_organic(work):
    repo = os.path.join(work, "osbooks-orgo")
    write(os.path.join(repo, "META-INF", "books.xml"), """<container
 xmlns="https://openstax.org/namespaces/book-container" version="1">
<book slug="tiny-orgo" style="organic-chemistry"
 href="../collections/tiny-orgo.collection.xml"/></container>""")
    write(os.path.join(repo, "collections", "tiny-orgo.collection.xml"),
          COLLECTION.format(title="Tiny Orgo", slug="tiny-orgo",
                            uuid="33333333-3333-4333-8444-555555555555",
                            content="""
<col:subcollection><md:title>Structure and Bonding</md:title><col:content>
<col:module document="m40001"/><col:module document="m40002"/>
</col:content></col:subcollection>"""))
    module(repo, "m40001", "Why This Chapter?", """
<para id="p1">Atoms first.</para>""", cls="introduction")
    module(repo, "m40002", "Atomic Structure", """
<para id="p1">Electrons move.</para>
<figure id="f1" class="mechanism-figure"><title>MECHANISM</title>
<media alt="Two steps"><image mime-type="image/png"
src="../../media/one.png"/></media>
<caption>Mechanism of a reaction.</caption></figure>
<table id="t1" summary=""><title>Some Acids</title><tgroup cols="2">
<colspec colnum="col1" colname="col1"/><colspec colnum="col2"
colname="col2"/><tbody><row><entry>HCl</entry><entry>strong</entry></row>
<row><entry namest="col1" nameend="col2">and more</entry></row></tbody>
</tgroup></table>
<section id="pr" class="section-exercises"><title>Problems</title>
<exercise id="x1"><problem id="pr1"><para id="pp1"><link class="os-embed"
url="#exercise/TEST_OC1"/></para></problem></exercise></section>
<section id="cm" class="chemistry-matters"><title>Alkaloids: From Cocaine
to Dental Anesthetics</title><para id="p2">Coca leaves.</para></section>
<note id="n1" class="why-chapter"><title/><note id="n2"><title>Strategy</title>
<para id="p3">Plan.</para></note></note>
<note id="n3" class="why-chapter"><title id="n3t">Bonds Hold</title>
<para id="p4">Electrons pair.</para></note>""")
    os.makedirs(os.path.join(repo, "media"), exist_ok=True)
    with open(os.path.join(repo, "media", "one.png"), "wb") as fh:
        fh.write(ONE_PIXEL)
    cache = os.path.join(work, "cache")
    write(os.path.join(cache, "public", "nickname", "TEST_OC1.json"),
          json.dumps(bank_item("TEST_OC1", "Which atom is smallest?",
                               ["Carbon", "Hydrogen", "Oxygen"], 1,
                               "Hydrogen has one proton.")))
    out = os.path.join(work, "orgo")
    result = unpack(repo, out, "--exercises-cache", cache)
    plain_out = os.path.join(work, "orgo-plain")
    plain = unpack(repo, plain_out, "--exercises-cache", cache, "--no-boxes")
    section = read(out, "1-1-atomic-structure.html")
    key = read(out, "chapter-1.html")
    return [
        ("the book unpacks, a table whose columns are numbered \"col1\" "
         "among it, its span kept",
         lambda: result.returncode == 0
         and '<td colspan="2">and more</td>' in section),
        ("a problem opens with \"Problem\" and its number, chapter and "
         "place, a link to its solution",
         lambda: '<a href="chapter-1.html#auto_m40002_501-solution" '
         'class="os-number">Problem 1-1</a> Which atom is smallest?'
         in section),
        ("its solution, in the answer key, opens the same way, linking "
         "back",
         lambda: '<a href="1-1-atomic-structure.html#auto_m40002_501" '
         'class="os-number">Problem 1-1</a> <span class="answer-letters">'
         'b</span>' in key and "Hydrogen has one proton." in key),
        ("the Chemistry Matters page is named for its section, the dash "
         "closed up",
         lambda: "<h1>Chemistry Matters\u2014Alkaloids: From Cocaine to "
         "Dental Anesthetics</h1>" in read(out, "1-chemistry-matters.html")),
        ("a note whose title is empty has no heading for it, and what it "
         "holds no level lower for it",
         lambda: re.search(r"<h2>Why This Chapter\?</h2>\s*<div class=\"os-note box\"[^>]*>"
                           r"\s*<h3>Strategy</h3>", section)),
        ("a note's kind that ends in a question mark is followed by its "
         "title with no colon",
         lambda: '<div class="os-note why-chapter box" id="n3"><h2><span '
         'class="os-note-label">Why This Chapter?</span> Bonds Hold</h2>'
         in section),
        ("--no-boxes leaves every note no box, each still headed by its kind "
         "and its title in one heading",
         lambda: plain.returncode == 0
         and '<div class="os-note why-chapter" id="n3"><h2><span '
         'class="os-note-label">Why This Chapter?</span> Bonds Hold</h2>'
         in read(plain_out, "1-1-atomic-structure.html")
         and not any("box" in c.split() for c in re.findall(
             r'<div class="(os-note[^"]*)"', read(plain_out, "1-1-atomic-structure.html")))
         and "made boxes" not in plain.stdout and "made boxes" in result.stdout),
        ("a mechanism's caption is its figure's, as any figure's",
         lambda: '<figcaption><span class="os-label">Figure 1.1</span> '
         '<span class="os-title">MECHANISM</span> <span class="os-caption">'
         'Mechanism of a reaction.</span></figcaption>' in section),
    ]


# A book in Polish ---------------------------------------------------------

def case_polish(work):
    repo = os.path.join(work, "osbooks-psychologia")
    write(os.path.join(repo, "META-INF", "books.xml"), """<container
 xmlns="https://openstax.org/namespaces/book-container" version="1">
<book slug="psychologia" style="pl-psychology"
 href="../collections/psychologia.collection.xml"/></container>""")
    write(os.path.join(repo, "collections", "psychologia.collection.xml"),
          COLLECTION.format(title="Psychologia", slug="psychologia",
                            uuid="44444444-3333-4333-8444-555555555555",
                            content="""
<col:subcollection><md:title>Wprowadzenie do psychologii</md:title>
<col:content><col:module document="m50001"/><col:module document="m50002"/>
</col:content></col:subcollection>""").replace(
              "<md:language>en</md:language>", "<md:language>pl</md:language>"))
    module(repo, "m50001", "Wprowadzenie", """
<para id="p1">Zaczynamy.</para>""", cls="introduction")
    module(repo, "m50002", "Czym jest psychologia?", """
<figure id="f1"><media alt="Mózg"><image mime-type="image/png"
src="../../media/one.png"/></media><caption>Mózg.</caption></figure>
<para id="p1" xmlns:cmlnle="http://katalysteducation.org/cmlnle/1.0"
xmlns:cxlxt="http://katalysteducation.org/cxlxt/1.0">Na <link
target-id="f1" cmlnle:case="locative"/> widać mózg, a <link
target-id="f1"/> go pokazuje. Wiele o <term
cmlnle:reference="psychologia ewolucyjna">psychologii ewolucyjnej</term>,
<term cmlnle:reference="łuk odruchowy">łuku odruchowym</term> i <term
cmlnle:reference="lęk">lęku</term> wiedział <term cxlxt:index="name"
cxlxt:name="Darwin, Karol">Karol Darwin</term>, który pisał o
<foreign xml:lang="en"><term cxlxt:index="foreign">mind</term></foreign>.
</para>
<list id="l1"><item><para id="ip1">Pierwszy punkt.</para></item></list>
""", glossary="""<glossary><definition id="d1"><term>umysł</term><meaning
id="dm1"><para id="dp1">to, co <emphasis
effect="italics">myśli</emphasis></para></meaning></definition>
</glossary>""")
    os.makedirs(os.path.join(repo, "media"), exist_ok=True)
    with open(os.path.join(repo, "media", "one.png"), "wb") as fh:
        fh.write(ONE_PIXEL)
    out = os.path.join(work, "psychologia")
    result = unpack(repo, out)
    from cnx.project import openstax_pdf_layout
    from cnx.bake.recipes import RECIPES
    import cnx.project
    import yaml
    section = read(out, "1-1-czym-jest-psychologia.html")
    # The default as someone might edit it, its opening comment gone and
    # its paper unset.
    edited = os.path.join(work, "edited", "pdf-layout.yaml")
    write(edited, "fontsize: 11pt\n\nlinestretch: 1\n")
    # And one that names a face of its own.
    named = os.path.join(work, "named", "pdf-layout.yaml")
    write(named, "fontsize: 11pt\nmainfont: Libertinus Serif\n")
    saved = cnx.project.DEFAULT_PDF_LAYOUT
    try:
        cnx.project.DEFAULT_PDF_LAYOUT = edited
        copies = [yaml.safe_load(openstax_pdf_layout("a test", style))
                  for style in ("sociology", "pl-nursing")]
        cnx.project.DEFAULT_PDF_LAYOUT = named
        copies += [yaml.safe_load(openstax_pdf_layout("a test", "sociology"))]
    finally:
        cnx.project.DEFAULT_PDF_LAYOUT = saved
    # A style of each design, Organic Chemistry's, set in its design's
    # second face, and one with no design in OpenStax's styles.
    faces = {style: yaml.safe_load(openstax_pdf_layout("a test", style))
             for style in ("psychology", "biology", "organic-chemistry", "marketing",
                           "statistics", "otto-book")}
    noto = openstax_pdf_layout("a test", "statistics")

    def index(name):
        return read(out, f"{name}.html")

    return [
        ("a book in Polish unpacks, its figure an Ilustracja",
         lambda: result.returncode == 0
         and '<span class="os-label">Ilustracja 1.1</span>' in section),
        ("and its captions' own labels are read by the Polish words",
         lambda: '  captions:\n    figure_prefixes: ["Ilustracja"]\n'
         '    table_prefixes: ["Tabela"]\n' in read(out, "conversion.yaml")),
        ("its PDF is on Letter paper, as OpenStax's is for its cosmos design, where "
         "the carnival design's Polish books, nursing and physics, are on A4",
         lambda: "papersize: letter\n" in read(out, "pdf-layout.yaml")
         and all("papersize: a4\n" in openstax_pdf_layout("a test", style)
                 for style in ("pl-nursing", "pl-u-physics"))),
        ("a default someone has edited, its opening comment gone and its paper unset, "
         "is copied whole, put on A4 for those books and given each one's face, and a "
         "face it names stays",
         lambda: copies == [dict({"fontsize": "11pt", "linestretch": 1}, **PLEX_SERIF),
                            {"fontsize": "11pt", "linestretch": 1, "papersize": "a4",
                             "mainfont": "IBMPlexSans",
                             "mainfontoptions": PLEX_SERIF["mainfontoptions"]},
                            {"fontsize": "11pt", "mainfont": "Libertinus Serif"}]),
        ("each book's text is in its design's face, as OpenStax sets it, named by its "
         "four files: cosmos's IBM Plex Serif, with IBM Plex Math for formulas, "
         "carnival's IBM Plex Sans, Organic Chemistry's Plex Serif, and cardboard's and "
         "corn's Noto Sans, Noto Sans Math left for whoever installs a version with a "
         "MATH table; a style with no design keeps the default's face",
         lambda: [(faces[s].get("mainfont"), faces[s].get("mathfont")) for s in
                  ("psychology", "biology", "organic-chemistry", "marketing", "statistics",
                   "otto-book")]
         == [("IBMPlexSerif", "IBMPlexMath-Regular.otf"), ("IBMPlexSans", None),
             ("IBMPlexSerif", "IBMPlexMath-Regular.otf"), ("NotoSans", None),
             ("NotoSans", None), (None, None)]
         and all(faces[s]["mainfontoptions"] == PLEX_SERIF["mainfontoptions"]
                 for s in ("psychology", "biology", "organic-chemistry"))
         and all(faces[s]["mainfontoptions"] == ["Extension=.ttf"]
                 + PLEX_SERIF["mainfontoptions"][1:] for s in ("marketing", "statistics"))
         and noto.endswith("from version 3.000\n# (github.com/notofonts/math), and "
                           "Debian's and Ubuntu's fonts-noto-core\n# have 2.001. With "
                           "3.000 or later installed, take the # off the line\n# below.\n"
                           "mainfont: NotoSans\nmainfontoptions:\n  - Extension=.ttf\n"
                           "  - UprightFont=*-Regular\n  - BoldFont=*-Bold\n"
                           "  - ItalicFont=*-Italic\n  - BoldItalicFont=*-BoldItalic\n"
                           "# mathfont: NotoSansMath-Regular.ttf\n")),
        ("every style a recipe bakes has an OpenStax design, or none in OpenStax's styles",
         lambda: sorted(style for style in RECIPES if not cnx.project.design_face(style))
         == ["ap-history", "otto-book"]),
        ("a link names its target in the case its sentence wants, the "
         "nominative where it names none",
         lambda: 'Na <a href="#f1">Ilustracji 1.1</a> widać mózg, a '
         '<a href="#f1">Ilustracja 1.1</a> go pokazuje' in section),
        ("a list item that is one paragraph is the paragraph's words, "
         "its id kept",
         lambda: '<li id="ip1">Pierwszy punkt.</li>' in section),
        ("a meaning that is one paragraph keeps its italics, and the "
         "paragraph's id",
         lambda: re.search(r'<dd id="dm1"><span id="dp1"></span>to, co '
                           r'<em>myśli</em></dd>',
                           read(out, "1-kluczowe-pojecia.html"))),
        ("terms, names, and foreign words are each in an index of their "
         "own, a term by its form for the index",
         lambda: "psychologia ewolucyjna" in flat(index("skorowidz-rzeczowy"))
         and "Darwin, Karol" in flat(index("skorowidz-nazwisk"))
         and 'lang="en">mind' in index("skorowidz-terminow-obcojezycznych")),
        ("the index is in Polish order, Ł after L, each its own group",
         lambda: re.search(r"<h2>L</h2>.*lęk.*<h2>Ł</h2>.*łuk odruchowy.*"
                           r"<h2>P</h2>.*psychologia ewolucyjna",
                           index("skorowidz-rzeczowy"), re.S)),
    ]


# A book whose end-of-chapter pages are a group of their own ---------------

def case_review(work):
    repo = os.path.join(work, "osbooks-skills")
    write(os.path.join(repo, "META-INF", "books.xml"), """<container
 xmlns="https://openstax.org/namespaces/book-container" version="1">
<book slug="tiny-skills" style="bca"
 href="../collections/tiny-skills.collection.xml"/>
</container>""")
    write(os.path.join(repo, "collections", "tiny-skills.collection.xml"),
          COLLECTION.format(title="Tiny Skills", slug="tiny-skills",
                            uuid="11111111-2222-4333-8444-777777777777",
                            content="""
<col:subcollection><md:title>Using Software</md:title><col:content>
<col:module document="m30001"/>
<col:module document="m30002"/>
</col:content></col:subcollection>"""))
    module(repo, "m30001", "Chapter Scenario", """
<para id="p1">A day at work.</para>""", cls="introduction")
    module(repo, "m30002", "Spreadsheets", """
<para id="p1">A <term id="t1">cell</term> holds a value.</para>
<section id="s1" class="section-summary"><title>Summary</title>
<para id="p2">Cells hold values.</para></section>
<section id="s2" class="review-questions"><title>Review</title>
<exercise id="e1"><problem id="pr1"><para id="p3">What is a
cell?</para></problem></exercise></section>""", glossary="""
<glossary><definition id="d1"><term>cell</term><meaning id="m1">a box of a
sheet</meaning></definition></glossary>""")
    out = os.path.join(work, "skills")
    result = unpack(repo, out)
    import yaml
    contents = yaml.safe_load(read(out, "project.yaml"))["project"]["contents"]
    chapter = contents[0]
    group = [item for item in chapter["items"] if isinstance(item, dict)
             and "title" in item]
    names = [item if isinstance(item, str) else item.get("page")
             for item in (group[0]["items"] if group else [])]
    return [
        ("its end-of-chapter pages are a group in their chapter, \"Chapter "
         "Review\", each named with the chapter's number as OpenStax "
         "names it",
         lambda: result.returncode == 0 and group
         and group[0]["title"] == "Chapter Review"
         and names == ["1-key-terms", "1-summary", "1-review-questions"]),
    ]


# A nursing book's references, gathered by chapter -----------------------

def case_references(work):
    repo = os.path.join(work, "osbooks-nursing")
    write(os.path.join(repo, "META-INF", "books.xml"), """<container
 xmlns="https://openstax.org/namespaces/book-container" version="1">
<book slug="tiny-nursing" style="nursing-external"
 href="../collections/tiny-nursing.collection.xml"/>
</container>""")
    write(os.path.join(repo, "collections", "tiny-nursing.collection.xml"),
          COLLECTION.format(title="Tiny Nursing", slug="tiny-nursing",
                            uuid="11111111-2222-4333-8444-888888888888",
                            content="""
<col:subcollection><md:title>Drugs</md:title><col:content>
<col:module document="m40001"/>
<col:module document="m40002"/>
</col:content></col:subcollection>"""))
    module(repo, "m40001", "Introduction", """
<para id="p1">Drugs help.</para>""", cls="introduction")
    module(repo, "m40002", "Doses", """
<section id="lo" class="learning-objectives"><title>Learning
Outcomes</title><list id="l1"><item>Define a dose.</item>
<item>Name a drug.</item></list></section>
<para id="p1">A dose is an amount.</para>
<section id="r1" class="references"><title>References</title>
<para id="p2">Smith, J. (2020). <emphasis effect="italics">Doses</emphasis>.
</para></section>""")
    out = os.path.join(work, "nursing")
    result = unpack(repo, out)
    references = read(out, "references.html") \
        if os.path.exists(os.path.join(out, "references.html")) else ""
    # Anatomy and Physiology's: each section's under its page's numbered
    # title, a heading of plain words, since a reader's contents (the
    # EPUB's navigation) shows a heading's spans, and an empty one is
    # epubcheck's error.
    anatomy = os.path.join(work, "osbooks-anatomy")
    write(os.path.join(anatomy, "META-INF", "books.xml"), """<container
 xmlns="https://openstax.org/namespaces/book-container" version="1">
<book slug="tiny-anatomy" style="anatomy"
 href="../collections/tiny-anatomy.collection.xml"/>
</container>""")
    write(os.path.join(anatomy, "collections", "tiny-anatomy.collection.xml"),
          COLLECTION.format(title="Tiny Anatomy", slug="tiny-anatomy",
                            uuid="11111111-2222-4333-8444-999999999999",
                            content="""
<col:subcollection><md:title>Cells</md:title><col:content>
<col:module document="m40011"/>
<col:module document="m40012"/>
</col:content></col:subcollection>"""))
    module(anatomy, "m40011", "Introduction", """
<para id="p1">Cells are small.</para>""", cls="introduction")
    module(anatomy, "m40012", "The Cytoplasm", """
<para id="p1">It fills the cell.</para>
<section id="r1" class="references"><title>References</title>
<para id="p2">Jones, K. (2019). <emphasis effect="italics">Cells</emphasis>.
</para></section>""")
    out2 = os.path.join(work, "anatomy")
    result2 = unpack(anatomy, out2)
    gathered = read(out2, "references.html") \
        if os.path.exists(os.path.join(out2, "references.html")) else ""
    return [
        ("each chapter's references on one page at the book's end, under "
         "a heading holding a link to the chapter",
         lambda: result.returncode == 0
         and '<h2><a href="1-introduction.html">Chapter 1 Drugs</a></h2>'
         in references and "Smith, J. (2020)" in references
         and "Smith" not in read(out, "1-1-doses.html")),
        ("learning outcomes numbered with their section's number keep it, "
         "bulleted, as a numbered list can't number so",
         lambda: re.search(r'<ul id="l1" class="os-abstract"><li><span '
                           r'class="os-abstract-token">1\.1\.1</span> <span '
                           r'class="os-abstract-content">Define a dose\.</span>',
                           read(out, "1-1-doses.html"))),
        ("Anatomy and Physiology's references under their page's numbered "
         "title, a heading of plain words keeping the section's id",
         lambda: result2.returncode == 0
         and re.search(r'<h2 id="r1">1\.1 The Cytoplasm\s*</h2>', gathered)
         and "Jones, K. (2019)" in gathered
         and "os-" not in gathered),
    ]


# A math book, baked as College Algebra is ------------------------------

def case_precalculus(work):
    repo = os.path.join(work, "osbooks-algebra")
    write(os.path.join(repo, "META-INF", "books.xml"), """<container
 xmlns="https://openstax.org/namespaces/book-container" version="1">
<book slug="tiny-algebra" style="precalculus"
 href="../collections/tiny-algebra.collection.xml"/>
</container>""")
    write(os.path.join(repo, "collections", "tiny-algebra.collection.xml"),
          COLLECTION.format(title="Tiny Algebra", slug="tiny-algebra",
                            uuid="11111111-2222-4333-8444-999999999999",
                            content="""
<col:subcollection><md:title>Numbers</md:title><col:content>
<col:module document="m50001"/>
<col:module document="m50002"/>
</col:content></col:subcollection>"""))
    module(repo, "m50001", "Introduction to Numbers", """
<para id="p1">Numbers count\x97one, two\x96and they\x92re kept.</para>""",
           cls="introduction")
    module(repo, "m50002", "Real Numbers", """
<section id="s1"><title>Classifying</title>
<para id="p7">Read <m:math><m:mrow><m:mo>“</m:mo><m:mn>5</m:mn>
<m:mo>−</m:mo><m:mn>3</m:mn><m:mo>"</m:mo></m:mrow></m:math> as
five minus three, <m:math><m:mtext mathvariant="bold-italic">x</m:mtext>
</m:math> as a variable, and <m:math><m:munder><m:mrow><m:mi>x</m:mi>
<m:mo>+</m:mo><m:mi>y</m:mi></m:mrow><m:mo>︸</m:mo></m:munder>
</m:math> as a sum.</para>
<example id="ex1"><exercise id="exe1"><problem id="pe1"><para id="p1">Is 2
whole?</para></problem><solution id="se1"><para id="p2">Yes.</para>
</solution></exercise></example>
<note id="n1" class="try"><exercise id="tr1"><problem id="pt1"><para
id="p3">Is 3 whole?</para><list id="l1" list-type="enumerated"
class="circled"><item><span class="token">\u24d0</span> as a word</item>
<item><span class="token">\u24d1</span> as a digit</item></list></problem>
<solution id="st1"><para id="p4">Yes.</para></solution></exercise></note>
</section>
<section id="s2" class="section-exercises"><title>1.1 Section Exercises</title>
<section id="s3"><title>Verbal</title>
<exercise id="e1"><problem id="pr1"><para id="p5">Is 4 whole?</para>
</problem><solution id="so1"><para id="p6">Yes.</para></solution>
</exercise></section></section>""")
    out = os.path.join(work, "algebra")
    result = unpack(repo, out)
    section = read(out, "1-1-real-numbers.html")
    key = read(out, "chapter-1.html")
    intro = read(out, "1-introduction-to-numbers.html")

    def outline(html):
        return [(int(m.group(1)), " ".join(re.sub(r"<[^>]+>", "",
                                                   m.group(2)).split()))
                for m in re.finditer(r"<h([1-6])[^>]*>(.*?)</h\1>", html,
                                     re.S)]
    return [
        ("its examples and Try It notes numbered in their page, its "
         "section's exercises under a heading of their own, their own "
         "sections a level down",
         lambda: result.returncode == 0 and outline(section) == [
             (1, "1.1 Real Numbers"), (2, "Classifying"), (3, "Example 1"),
             (4, "Solution"), (3, "Try It #1"),
             (2, "1.1 Section Exercises"), (3, "Verbal")]),
        ("a circled list is bulleted, its circled letters kept, where "
         "numbered it would read 1. \u24d0",
         lambda: re.search(r'<ul class="circled" id="l1"><li><span '
                           r'class="token">\u24d0</span> as a word</li>',
                           section)),
        ("a quotation mark in a formula is text there, a letter set as bold "
         "italic text a variable, which Pandoc can read back, and an "
         "underbrace written with a brace for vertical text the brace "
         "mathematics has",
         lambda: re.search(r'<mtext>\u201c</mtext><mn>5</mn>\s*<mo>\u2212'
                           r'</mo><mn>3</mn><mtext>"</mtext>', section)
         and '<mi mathvariant="bold-italic">x</mi>' in section
         and "<mo>\u23df</mo>" in section and "\ufe38" not in section),
        ("a Windows character the source holds as a control code is that "
         "character",
         lambda: "Numbers count\u2014one, two\u2013and they\u2019re kept."
         in intro),
        ("the answer key's page holds the Try It solutions under each "
         "page's numbered title, then the section's exercises'",
         lambda: outline(key) == [
             (1, "Chapter 1"), (2, "Try It"), (3, "1.1 Real Numbers"),
             (2, "1.1 Section Exercises")]
         and "Yes." in key and 'href="1-1-real-numbers.html#e1"' in key),
    ]


# A dev-math book's worked examples, their steps laid out in tables ---------

STEP_TABLES = """
<section id="s1"><title>Ratios</title>
<example id="ex1"><para id="p2">Write 21 out of 100 as a percent.</para>
<table id="steps1" class="unnumbered unstyled" summary="No Summary"
 aria-label="In this figure we have two columns of steps."><label/>
<tgroup cols="2"><tbody>
<row><entry>The amount we want to convert is <m:math><m:mn>21</m:mn></m:math>
out of <m:math><m:mn>100</m:mn></m:math>.</entry><entry><m:math><m:mn>21</m:mn>
</m:math> out of <m:math><m:mn>100</m:mn></m:math></entry></row>
<row><entry>Write as a ratio.</entry><entry><m:math><m:mfrac><m:mn>21</m:mn><m:mn>100</m:mn></m:mfrac></m:math></entry></row>
<row><entry>Convert the 21 per 100 to percent.</entry><entry><m:math>
<m:mn>21%</m:mn></m:math></entry></row>
</tbody></tgroup></table>
<table id="steps2" class="unstyled" summary="Steps for adding."><label/>
<tgroup cols="2"><tbody>
<row><entry>Write a phrase.</entry><entry>Seven plus twelve.</entry></row>
<row><entry>Translate.</entry><entry><m:math><m:mn>7</m:mn><m:mo>+</m:mo>
<m:mn>12</m:mn></m:math></entry></row>
<row><entry>Simplify.</entry><entry><m:math><m:mn>19</m:mn></m:math></entry></row>
</tbody></tgroup></table>
<table id="steps3" class="unnumbered unstyled" summary="Steps for naming.">
<tgroup cols="2"><tbody>
<row><entry>Read the problem.</entry><entry>Two values.</entry></row>
<row><entry>Name them:</entry></row>
<row><entry><emphasis effect="bold">Name</emphasis></entry><entry><emphasis
effect="bold">Value</emphasis></entry></row>
<row><entry>x</entry><entry>1</entry></row>
<row><entry>y</entry><entry>2</entry></row>
</tbody></tgroup></table>
</example>
<table id="kinds" class="unnumbered unstyled" summary="."
 aria-label="The top row of this table, which is a header row, names the kinds.">
<tgroup cols="3"><tbody>
<row><entry/><entry>Polynomial</entry><entry>Terms</entry></row>
<row><entry>Monomial</entry><entry><m:math><m:mn>14</m:mn></m:math></entry><entry>1</entry></row>
<row><entry>Binomial</entry><entry><m:math><m:mi>y</m:mi><m:mo>+</m:mo><m:mn>3</m:mn>
</m:math></entry><entry>2</entry></row>
</tbody></tgroup></table>
<table id="pictures" class="unnumbered unstyled" summary="Points">
<tgroup cols="3"><tbody>
<row><entry/><entry><media id="i1" alt="x equals zero"><image mime-type="image/png"
 src="../../media/one.png"/></media></entry><entry><media id="i2" alt="y equals zero">
<image mime-type="image/png" src="../../media/one.png"/></media></entry></row>
<row><entry>Substitute.</entry><entry><media id="i3" alt="zero minus four y"><image
 mime-type="image/png" src="../../media/one.png"/></media></entry><entry><media id="i4"
 alt="x minus zero"><image mime-type="image/png" src="../../media/one.png"/></media>
</entry></row>
<row><entry>Solve.</entry><entry><media id="i5" alt="y is minus two"><image
 mime-type="image/png" src="../../media/one.png"/></media></entry><entry><media id="i6"
 alt="x is eight"><image mime-type="image/png" src="../../media/one.png"/></media>
</entry></row>
</tbody></tgroup></table>
<table id="spaced" class="unnumbered unstyled" summary="Two tables of values">
<tgroup cols="5"><tbody>
<row><entry><emphasis effect="bold">x</emphasis></entry><entry><emphasis
effect="bold">y</emphasis></entry><entry morerows="3"/><entry><emphasis
effect="bold">x</emphasis></entry><entry><emphasis effect="bold">y</emphasis></entry></row>
<row><entry>0</entry><entry>0</entry><entry>0</entry><entry>4</entry></row>
<row><entry>1</entry><entry>4</entry><entry>1</entry><entry>4</entry></row>
<row><entry>2</entry><entry>8</entry><entry>2</entry><entry>4</entry></row>
</tbody></tgroup></table>
<table id="data1" summary="Prices of fruit">
<tgroup cols="2"><thead><row><entry>Fruit</entry><entry>Price</entry></row></thead>
<tbody><row><entry>Apple</entry><entry>1</entry></row>
<row><entry>Pear</entry><entry>2</entry></row></tbody></tgroup></table>
<example id="ex2"><para id="p3">Subtract 7 from 12.</para>
<table id="steps4">
<tgroup cols="2"><tbody>
<row><entry/><entry><m:math><m:mn>12</m:mn><m:mo>&#8722;</m:mo><m:mn>7</m:mn></m:math></entry></row>
<row><entry>Subtract.</entry><entry><m:math><m:mn>5</m:mn></m:math></entry></row>
</tbody></tgroup></table>
</example>
<table id="days" summary="A stock's changes"
 aria-label="The table has two columns, the days of the week and the changes.">
<tgroup cols="2"><tbody>
<row><entry>Monday</entry><entry><m:math><m:mn>&#8722;504</m:mn></m:math></entry></row>
<row><entry>Tuesday</entry><entry><m:math><m:mo>+</m:mo><m:mn>142</m:mn></m:math></entry></row>
<row><entry>Wednesday</entry><entry><m:math><m:mn>&#8722;449</m:mn></m:math></entry></row>
</tbody></tgroup></table>
</section>"""


def build_steps(repo):
    write(os.path.join(repo, "META-INF", "books.xml"), """<container
 xmlns="https://openstax.org/namespaces/book-container" version="1">
<book slug="tiny-prealgebra" style="dev-math"
 href="../collections/tiny-prealgebra.collection.xml"/>
<book slug="tiny-precalculus" style="precalculus"
 href="../collections/tiny-precalculus.collection.xml"/>
</container>""")
    for slug, title, uuid, first in (
            ("tiny-prealgebra", "Tiny Prealgebra", "aaaaaaaaaaaa", 60001),
            ("tiny-precalculus", "Tiny Precalculus", "bbbbbbbbbbbb", 60003)):
        write(os.path.join(repo, "collections", f"{slug}.collection.xml"),
              COLLECTION.format(title=title, slug=slug,
                                uuid=f"11111111-2222-4333-8444-{uuid}",
                                content=f"""
<col:subcollection><md:title>Fractions</md:title><col:content>
<col:module document="m{first}"/>
<col:module document="m{first + 1}"/>
</col:content></col:subcollection>"""))
        module(repo, f"m{first}", "Introduction to Fractions", """
<para id="p1">Fractions name parts of a whole.</para>""", cls="introduction")
        module(repo, f"m{first + 1}", "Ratios", STEP_TABLES)
    os.makedirs(os.path.join(repo, "media"), exist_ok=True)
    with open(os.path.join(repo, "media", "one.png"), "wb") as fh:
        fh.write(ONE_PIXEL)


def tables_of(html):
    """Each table's id and the attributes it opens with."""
    return {m.group(1): m.group(0) for m in re.finditer(
        r'<table id="([^"]+)"[^>]*>', html)}


def case_step_tables(work):
    from lxml import etree
    from cnx import mathtex, steptables
    repo = os.path.join(work, "osbooks-steps")
    build_steps(repo)
    out = os.path.join(work, "steps")
    result = unpack(repo, out, "--book", "tiny-prealgebra")
    page = read(out, "1-1-ratios.html")
    tables = tables_of(page)
    report = report_of(out)
    kept = {r["Detail"].split(" ")[0] for r in report
            if r["Check"] == "table-kept-as-data"}
    labels = [r["Detail"] for r in report
              if r["Check"] == "table-label-left-out"]
    with open(os.path.join(out, "table-captions.csv"), encoding="utf-8") as fh:
        drafted = {r["Label"]: r["Description"] for r in csv.DictReader(fh)}
    other = os.path.join(work, "precalculus")
    unpack(repo, other, "--book", "tiny-precalculus")
    other_tables = tables_of(read(other, "1-1-ratios.html"))

    # Converted, where Pandoc 3.9 or later is installed.
    converted, guessed, missing = None, [], []
    version = pandoc_version()
    if version is not None and version >= (3, 9):
        write(os.path.join(out, "conversion.yaml"), read(out, "conversion.yaml")
              + "targets:\n  html:\n    format: html\n")
        run = subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick",
                              "--quiet"], cwd=out, capture_output=True, text=True,
                             stdin=subprocess.DEVNULL)
        page_out = os.path.join(out, "html", "1-1-ratios.html")
        converted = read(page_out) if run.returncode == 0 and os.path.exists(
            page_out) else ""
        with open(os.path.join(out, "table-headers-new.csv"), encoding="utf-8") as fh:
            guessed = sorted((r["preview"], r["headers"]) for r in csv.DictReader(fh))
        if os.path.exists(os.path.join(out, "table-captions-missing.csv")):
            with open(os.path.join(out, "table-captions-missing.csv"),
                      encoding="utf-8") as fh:
                missing = [r["Label"] for r in csv.DictReader(fh)]

    def presentation(name):
        return 'role="presentation"' in tables.get(name, "")

    def tex(markup):
        return mathtex.tex(etree.fromstring(
            '<math xmlns="http://www.w3.org/1998/Math/MathML">%s</math>'
            % markup))
    return [
        ("a worked example's steps, a table OpenStax classes unstyled with "
         "no head and no caption but its number, is a layout table",
         lambda: result.returncode == 0 and presentation("steps1")
         and presentation("steps2") and presentation("steps3")
         and "Table 1.1" in page and not presentation("data1")),
        ("and so are steps OpenStax gives no class, as a dev-math book writes "
         "some, numbered as OpenStax numbers a table of no class",
         lambda: presentation("steps4") and "Table 1.3" in page),
        ("but a table of no class that OpenStax labels is a data table, as "
         "OpenStax's own HTML has it, and isn't reported: such tables are "
         "tables of values and of data, most of them",
         lambda: "days" in tables and not presentation("days")
         and "days" not in kept),
        ("the header guess reads a table as Pandoc gives it to the guess: "
         "a ratio set as a fraction is a formula, not the number 21100 "
         "under a row of words, and a short row is padded, not a band "
         "across the table over a part that has a header row",
         lambda: presentation("steps1") and presentation("steps3")
         and not kept & {"steps1", "steps3"}),
        ("and a table of nothing but pictures has no text of its own, as "
         "convert.py's census reads it, whatever the pictures' descriptions "
         "say: the filter makes it a figure",
         lambda: steptables.header_guess(etree.fromstring(
             "<table><tbody>" + "".join(
                 "<tr>%s</tr>" % "".join('<td><img src="a.png" alt="%s"/></td>' % a
                                         for a in row)
                 for row in (("Price", "Size"), ("1", "2"), ("3", "4"), ("5", "6")))
             + "</tbody></table>")) is None),
        ("one the guess reads a header row in is left a data table and "
         "reported: labels along the top beside a blank corner, pictures "
         "whose descriptions label the top, and a header row over two "
         "tables an empty column keeps apart, the column dropped as "
         "html-source.lua drops it",
         lambda: kept == {"kinds", "pictures", "spaced"}
         and not any(presentation(n) for n in kept)),
        ("OpenStax's label for a table isn't written, a layout table's or "
         "a data table's, and each is in the report",
         lambda: "aria-label" not in page
         and labels == ["steps1, a layout table: In this figure we have "
                        "two columns of steps.",
                        "kinds: The top row of this table, which is a header "
                        "row, names the kinds.",
                        "days: The table has two columns, the days of the "
                        "week and the changes."]),
        ("no description is drafted for a layout table, or from a summary "
         "that says nothing (\"No Summary\", \".\")",
         lambda: set(drafted.values()) == {"Points", "Two tables of values",
                                           "Prices of fruit", "A stock's changes"}
         and "2 table summary(ies) say nothing" in result.stdout
         and "4 table(s) that only lay things out" in result.stdout),
        ("a book of another style keeps such tables data tables, of that "
         "class or of none",
         lambda: other_tables and not any(
             'role="presentation"' in t for t in other_tables.values())),
        ("a formula's TeX is texmath's: an arrow between \\left. and "
         "\\right., a fraction in parentheses between \\left( and \\right), "
         "a space after a command a letter follows, a bar, a prime, limits, "
         "a space of an em, and text in bold",
         lambda: tex("<mi>a</mi><mo>\u2192</mo><mi>b</mi>")
         == "\\left. a\\rightarrow b \\right."
         and tex("<mo>(</mo><mn>2</mn><mo>)</mo><mo>(</mo><mfrac><mn>1</mn>"
                 "<mn>2</mn></mfrac><mo>)</mo>")
         == "(2)\\left( \\frac{1}{2} \\right)"
         and tex("<mn>$40</mn>") == "\\$ 40"
         and tex("<mi>m</mi><mo>\u2220</mo><mi>A</mi>") == "m\\angle A"
         and tex("<mo>\u2212</mo><mo>(</mo><mn>\u22122</mn><mo>)</mo>")
         == "- (-2)"
         and tex("<mover><mi>x</mi><mo>\u00af</mo></mover>") == "\\overline{x}"
         and tex("<msup><mi>f</mi><mo>\u2032</mo></msup>") == "f'"
         and tex("<munderover><mo>\u2211</mo><mrow><mi>i</mi><mo>=</mo>"
                 "<mn>1</mn></mrow><mi>n</mi></munderover><mi>i</mi>")
         == "\\sum\\limits_{i = 1}^{n}i"
         and tex('<mi>x</mi><mspace width="1em"/><mi>y</mi>') == "x\\quad y"
         and tex('<mtext mathvariant="bold">sum</mtext>') == "\\textbf{sum}"),
    ] + ([] if converted is None else [
        ("converted, a layout table has no scrolling wrapper and asks for no "
         "description, its number its caption; and convert.py's header "
         "guess reads a header row in each table the unpacker left a data "
         "table for one, and lists the layout tables as the page marks them",
         lambda: re.search(r'(?<!tabindex="0">\n)<table id="steps1"[^>]*'
                           r'role="presentation"', converted)
         and re.search(r'(?<!tabindex="0">\n)<table id="steps2"[^>]*'
                       r'role="presentation">\n<caption><span class="os-label">'
                       r'Table 1.1</span></caption>', converted)
         and missing == ["1-1-ratios#table-4"]
         and guessed == [(" | 12 - 7", "layout"),
                         (" | Polynomial | Terms", "both"),
                         (" | x equals zero | y equals zero", "both"),
                         ("Fruit | Price", "first-row"),
                         ("Monday | -504", "first-column"),
                         ("Read the problem. | Two values.", "layout"),
                         ("The amount we want to co | 21 out of 100", "layout"),
                         ("Write a phrase. | Seven plus twelve.", "layout"),
                         ("x | y | x", "both")]),
    ])


# Other books' tables that only lay things out -----------------------------

PHYSICS_TABLES = """
<section id="keyterms"><title>Section Key Terms</title>
<table id="terms" summary="The key terms: atom, physics, and theory."
 class="unnumbered unstyled section-key-terms"><label/>
<tgroup cols="3"><tbody>
<row><entry>atom</entry><entry>classical physics</entry><entry>modern physics</entry></row>
<row><entry>physics</entry><entry>quantum mechanics</entry><entry>theory of relativity</entry></row>
</tbody></tgroup></table>
</section>
<section id="s2"><title>Speed</title>
<para id="p3">Speed is distance over time.</para>
</section>
<section id="ke" class="key-equations"><title>Key Equations</title>
<table id="equations" class="unnumbered unstyled" summary="key equations table">
<tgroup cols="2"><tbody>
<row><entry>speed</entry><entry><m:math><m:mi>v</m:mi><m:mo>=</m:mo><m:mfrac>
<m:mi>d</m:mi><m:mi>t</m:mi></m:mfrac></m:math></entry></row>
<row><entry>density</entry><entry><m:math><m:mi>ρ</m:mi><m:mo>=</m:mo><m:mfrac>
<m:mi>m</m:mi><m:mi>V</m:mi></m:mfrac></m:math></entry></row>
</tbody></tgroup></table>
<table id="alone" class="unnumbered unstyled" summary="An equation.">
<tgroup cols="1"><tbody>
<row><entry><m:math><m:mi>F</m:mi><m:mo>=</m:mo><m:mi>m</m:mi><m:mi>a</m:mi>
</m:math></entry></row>
</tbody></tgroup></table>
</section>"""

COREQ_TABLES = """
<section id="cs" class="coreq-skills"><title>Exponents</title>
<example id="ex1"><exercise id="e1"><problem id="pr1"><para id="p4">Solve
<m:math><m:mn>2</m:mn><m:mi>x</m:mi><m:mo>=</m:mo><m:mn>8</m:mn></m:math>.</para>
</problem><solution id="so1">
<table id="worked" class="unnumbered unstyled" summary="Steps to solve."><label/>
<tgroup cols="2"><tbody>
<row><entry>Divide each side by 2.</entry><entry><m:math><m:mi>x</m:mi><m:mo>=</m:mo>
<m:mn>4</m:mn></m:math></entry></row>
<row><entry>Check.</entry><entry><m:math><m:mn>2</m:mn><m:mo>·</m:mo><m:mn>4</m:mn>
<m:mo>=</m:mo><m:mn>8</m:mn></m:math></entry></row>
</tbody></tgroup></table>
</solution></exercise></example>
<table id="hours" class="unnumbered unstyled" summary="Hours of study."><label/>
<tgroup cols="2"><tbody>
<row><entry><emphasis effect="bold">Credit hours</emphasis></entry><entry><emphasis
effect="bold">Study time</emphasis></entry></row>
<row><entry>9</entry><entry>18</entry></row>
<row><entry>12</entry><entry>24</entry></row>
</tbody></tgroup></table>
</section>
<section id="ke2" class="key-equations"><title>Key Equations</title>
<table id="rules" class="unnumbered unstyled" summary="The rules.">
<tgroup cols="2"><tbody>
<row><entry>Product rule</entry><entry><m:math><m:msup><m:mi>a</m:mi><m:mi>m</m:mi>
</m:msup><m:mo>·</m:mo><m:msup><m:mi>a</m:mi><m:mi>n</m:mi></m:msup></m:math></entry></row>
<row><entry>Quotient rule</entry><entry><m:math><m:mfrac><m:msup><m:mi>a</m:mi>
<m:mi>m</m:mi></m:msup><m:msup><m:mi>a</m:mi><m:mi>n</m:mi></m:msup></m:mfrac>
</m:math></entry></row>
</tbody></tgroup></table>
</section>"""

PLAIN_TABLES = """
<section id="s3"><title>Before the War</title>
<table id="byline" class="unnumbered unstyled" summary="Who wrote it.">
<tgroup cols="1"><tbody>
<row><entry>Written by: A. Historian, A College</entry></row>
</tbody></tgroup></table>
<para id="p5">The colonies had grown.</para>
<table id="claims" class="unnumbered unstyled" summary="A worksheet.">
<tgroup cols="2"><tbody>
<row><entry>The claim:</entry><entry>The argument against it:</entry></row>
<row><entry>A.</entry><entry/></row>
<row><entry>B.</entry><entry/></row>
</tbody></tgroup></table>
<table id="sizes" class="unnumbered" summary="Two rows and three columns. The first row is
 labeled, &#8220;size&#8221;, and the second row is labeled, &#8220;price&#8221;. Reading the
 columns as ordered pairs, we have: (small, 2), and (large, 4).">
<tgroup cols="3"><tbody>
<row><entry>size</entry><entry>small</entry><entry>large</entry></row>
<row><entry>price</entry><entry>2</entry><entry>4</entry></row>
</tbody></tgroup></table>
<table id="tolls" class="unnumbered" summary="The tolls each colony charged on goods from
 England.">
<tgroup cols="2"><tbody>
<row><entry>Virginia</entry><entry>2 shillings</entry></row>
<row><entry>Maryland</entry><entry>3 shillings</entry></row>
</tbody></tgroup></table>
<table id="crops" class="unnumbered" summary="Virginia grew tobacco and charged 2 shillings,
 Maryland grew corn and charged 3 shillings, and Georgia grew rice.">
<tgroup cols="3"><tbody>
<row><entry>Virginia</entry><entry>tobacco</entry><entry>2 shillings</entry></row>
<row><entry>Maryland</entry><entry>corn</entry><entry>3 shillings</entry></row>
<row><entry>Georgia</entry><entry>rice</entry><entry>4 shillings</entry></row>
</tbody></tgroup></table>
<table id="time">
<tgroup cols="1"><tbody>
<row><entry>Estimated completion time: 20 minutes</entry></row>
</tbody></tgroup></table>
<table id="tally">
<title>Survey Results</title>
<tgroup cols="3"><tbody>
<row><entry>__________</entry><entry>__________</entry><entry>__________</entry></row>
<row><entry>__________</entry><entry>__________</entry><entry/></row>
</tbody></tgroup></table>
<table id="signed">
<tgroup cols="2"><tbody>
<row><entry>Name: __________</entry><entry>Date: __________</entry></row>
</tbody></tgroup></table>
<table id="maps" class="unnumbered">
<tgroup cols="2"><tbody>
<row><entry><media id="m1" alt="A map of Virginia."><image mime-type="image/png"
 src="../../media/one.png"/></media><para id="p6">Map A</para></entry><entry><media id="m2"
 alt="A map of Maryland."><image mime-type="image/png" src="../../media/one.png"/></media>
<para id="p7">Map B</para></entry></row>
</tbody></tgroup></table>
<table id="ports" class="unnumbered">
<tgroup cols="2"><tbody>
<row><entry><media id="m3" alt="A wharf."><image mime-type="image/png"
 src="../../media/one.png"/></media> Ships took tobacco from the rivers of Virginia.</entry>
<entry><media id="m4" alt="A harbor."><image mime-type="image/png"
 src="../../media/one.png"/></media> Ships took rice from the harbor of Charleston.</entry></row>
</tbody></tgroup></table>
<table id="match1" class="unnumbered unstyled">
<tgroup cols="2"><tbody>
<row><entry>___Virginia</entry><entry>A. rice</entry></row>
<row><entry>___Maryland</entry><entry>B. tobacco</entry></row>
<row><entry>___Georgia</entry><entry>C. corn</entry></row>
</tbody></tgroup></table>
<table id="match2" class="unnumbered unstyled">
<tgroup cols="2"><tbody>
<row><entry>A. Virginia</entry><entry>i. corn</entry></row>
<row><entry>B. Maryland</entry><entry>ii. rice</entry></row>
<row><entry>C. Georgia</entry><entry>iii. tobacco</entry></row>
<row><entry/><entry>iv. indigo</entry></row>
</tbody></tgroup></table>
<table id="listed" class="unnumbered unstyled">
<tgroup cols="2"><tbody>
<row><entry>1. Virginia</entry><entry>4. Delaware</entry></row>
<row><entry>2. Maryland</entry><entry>5. New York</entry></row>
<row><entry>3. Georgia</entry><entry>6. Carolina</entry></row>
</tbody></tgroup></table>
</section>
<section id="ke3" class="key-equations"><title>Key Equations</title>
<table id="growth" class="unnumbered unstyled" summary="This table has two columns and two
 rows. The first row reads &#8220;Growth&#8221; and &#8220;P equals P zero e to the r t&#8221;.">
<tgroup cols="2"><tbody>
<row><entry>Growth</entry><entry><m:math><m:mi>P</m:mi><m:mo>=</m:mo><m:msub><m:mi>P</m:mi>
<m:mn>0</m:mn></m:msub><m:msup><m:mi>e</m:mi><m:mrow><m:mi>r</m:mi><m:mi>t</m:mi></m:mrow>
</m:msup></m:math></entry></row>
<row><entry>Decay</entry><entry><m:math><m:mi>P</m:mi><m:mo>=</m:mo><m:msub><m:mi>P</m:mi>
<m:mn>0</m:mn></m:msub><m:msup><m:mi>e</m:mi><m:mrow><m:mo>&#8722;</m:mo><m:mi>r</m:mi>
<m:mi>t</m:mi></m:mrow></m:msup></m:math></entry></row>
</tbody></tgroup></table>
<table id="halving" class="unnumbered">
<tgroup cols="2"><tbody>
<row><entry>Half-life</entry><entry><m:math><m:mi>t</m:mi><m:mo>=</m:mo><m:mfrac><m:mn>0.69</m:mn>
<m:mi>r</m:mi></m:mfrac></m:math></entry></row>
<row><entry>Doubling time</entry><entry><m:math><m:mi>t</m:mi><m:mo>=</m:mo><m:mfrac>
<m:mn>0.69</m:mn><m:mi>r</m:mi></m:mfrac></m:math></entry></row>
</tbody></tgroup></table>
</section>"""


def build_layout_books(repo):
    """Three books of the styles whose layout tables aren't steps, each of
    an introduction and a section: Physics (hs-physics), College Algebra
    with Corequisite Support (precalculus-coreq), and a book of a style
    that lays nothing out in tables (precalculus)."""
    books = (("tiny-physics", "hs-physics", "Tiny Physics", "cccccccccccc", 61001,
              "Motion", PHYSICS_TABLES),
             ("tiny-coreq", "precalculus-coreq", "Tiny Corequisite", "dddddddddddd", 61003,
              "Exponents", COREQ_TABLES),
             ("tiny-history", "precalculus", "Tiny History", "eeeeeeeeeeee", 61005,
              "The Colonies", PLAIN_TABLES))
    write(os.path.join(repo, "META-INF", "books.xml"), """<container
 xmlns="https://openstax.org/namespaces/book-container" version="1">
""" + "".join(f"""<book slug="{slug}" style="{style}"
 href="../collections/{slug}.collection.xml"/>
""" for slug, style, *_ in books) + "</container>")
    for slug, _style, title, uuid, first, chapter, content in books:
        write(os.path.join(repo, "collections", f"{slug}.collection.xml"),
              COLLECTION.format(title=title, slug=slug,
                                uuid=f"11111111-2222-4333-8444-{uuid}",
                                content=f"""
<col:subcollection><md:title>{chapter}</md:title><col:content>
<col:module document="m{first}"/>
<col:module document="m{first + 1}"/>
</col:content></col:subcollection>"""))
        module(repo, f"m{first}", f"Introduction to {chapter}", """
<para id="p1">This chapter opens.</para>""", cls="introduction")
        module(repo, f"m{first + 1}", chapter, content)
    os.makedirs(os.path.join(repo, "media"), exist_ok=True)
    with open(os.path.join(repo, "media", "one.png"), "wb") as fh:
        fh.write(ONE_PIXEL)


def case_layout_kinds(work):
    repo = os.path.join(work, "osbooks-layout")
    build_layout_books(repo)
    found, said, reports, drafted, summaries = {}, {}, {}, {}, {}
    for slug in ("tiny-physics", "tiny-coreq", "tiny-history"):
        out = os.path.join(work, slug)
        result = unpack(repo, out, "--book", slug)
        said[slug] = result.stdout + result.stderr
        captions = os.path.join(out, "table-captions.csv")
        drafted[slug] = read(captions) if os.path.exists(captions) else ""
        listed = os.path.join(out, "cnx-table-summaries.csv")
        summaries[slug] = []
        if os.path.exists(listed):
            with open(listed, encoding="utf-8", newline="") as fh:
                summaries[slug] = list(csv.DictReader(fh))
        found[slug] = {}
        for name in sorted(os.listdir(out)) if result.returncode == 0 else []:
            if name.endswith(".html"):
                found[slug].update(tables_of(read(out, name)))
        reports[slug] = report_of(out) if result.returncode == 0 else []

    def presentation(slug, name):
        return 'role="presentation"' in found[slug].get(name, "")

    def known(slug, *names):
        return all(name in found[slug] for name in names)
    return [
        ("a grid of a section's key terms in Physics is a layout table, and so is "
         "its Key Equations table, a formula's name beside the formula",
         lambda: known("tiny-physics", "terms", "equations")
         and presentation("tiny-physics", "terms")
         and presentation("tiny-physics", "equations")),
        ("a table of one cell is a layout table in a book of any style, of any "
         "class: a formula alone in Key Equations, and a byline and an estimate "
         "of the time a section takes where the book's tables of more cells are "
         "data tables",
         lambda: known("tiny-physics", "alone")
         and known("tiny-history", "byline", "time", "claims")
         and presentation("tiny-physics", "alone")
         and presentation("tiny-history", "byline")
         and presentation("tiny-history", "time")
         and not presentation("tiny-history", "claims")),
        ("so is a Key Equations table in a book of any style, of any class",
         lambda: known("tiny-history", "growth", "halving")
         and presentation("tiny-history", "growth")
         and presentation("tiny-history", "halving")),
        ("so is a form of lines to fill in and nothing else, in a book of any "
         "style, of any class, with a title of its own or none; one with labels "
         "beside its lines isn't",
         lambda: known("tiny-history", "tally", "signed")
         and presentation("tiny-history", "tally")
         and not presentation("tiny-history", "signed")),
        ("so are pictures in rows, each with a label at most; pictures each with "
         "a sentence aren't",
         lambda: known("tiny-history", "maps", "ports")
         and presentation("tiny-history", "maps")
         and not presentation("tiny-history", "ports")),
        ("so is a matching exercise, two lists side by side, each item opening "
         "with a mark of its list's series, a blank or a letter beside a letter "
         "or a roman numeral; a list numbered alike in two columns isn't",
         lambda: known("tiny-history", "match1", "match2", "listed")
         and presentation("tiny-history", "match1")
         and presentation("tiny-history", "match2")
         and not presentation("tiny-history", "listed")),
        ("College Algebra with Corequisite Support's worked steps are a layout "
         "table, and its Key Equations, and its table the header guess reads a "
         "header row in a data table, reported",
         lambda: known("tiny-coreq", "worked", "hours", "rules")
         and presentation("tiny-coreq", "worked")
         and not presentation("tiny-coreq", "hours")
         and presentation("tiny-coreq", "rules")
         and [r["Detail"].split(" ")[0] for r in reports["tiny-coreq"]
              if r["Check"] == "table-kept-as-data"] == ["hours"]),
        ("and the run counts them",
         lambda: "3 table(s) that only lay things out" in said["tiny-physics"]
         and "2 table(s) that only lay things out" in said["tiny-coreq"]
         and "8 table(s) that only lay things out" in said["tiny-history"]),
        ("a layout table's summary isn't drafted as a description, a Key Equations "
         "table's among them, which stays in cnx-table-summaries.csv",
         lambda: "The rules." not in drafted["tiny-coreq"]
         and "Growth" not in drafted["tiny-history"]
         and "key equations table" not in drafted["tiny-physics"]
         and any(r["Summary"] == "The rules." for r in summaries["tiny-coreq"])
         and "1 table summary(ies) say nothing" in said["tiny-physics"]),
        # A summary that reads its table out, drafted as a caption, is read
        # before the table it repeats; it's drafted still, so a person can
        # rewrite it where it stands, and named, so they can find it.
        ("a summary that reads its table out is drafted as any other is, and "
         "named in the report and in cnx-table-summaries.csv, where one that says "
         "what its table shows isn't; one that repeats its table's cells in words "
         "of its own reads it out",
         lambda: "Reading the columns as ordered pairs" in drafted["tiny-history"]
         and "The tolls each colony" in drafted["tiny-history"]
         and "Virginia grew tobacco" in drafted["tiny-history"]
         and [r["Detail"].split(":")[0] for r in reports["tiny-history"]
              if r["Check"] == "table-summary-reads-out"]
         == ["1-1-the-colonies#table-3", "1-1-the-colonies#table-5"]
         and {r["Summary"].split(".")[0]: r["Reads out"] for r in summaries["tiny-history"]}
         == {"Who wrote it": "", "A worksheet": "", "Two rows and three columns": "yes",
             "The tolls each colony charged on goods from England": "",
             "Virginia grew tobacco and charged 2 shillings, Maryland grew corn and "
             "charged 3 shillings, and Georgia grew rice": "yes",
             "This table has two columns and two rows": "yes"}
         and "2 of them read the table out" in said["tiny-history"]),
    ]


# An inquiry organizer: a key to the emoji, and the chapter's plan --------

ORGANIZER_KEY = """<tgroup cols="3"><tbody>
<row><entry>\U0001F4CE </entry><entry>Inquiry Organizer</entry><entry>Summary of chapter
objectives and resources</entry></row>
<row><entry>\U0001F50E </entry><entry>Narratives</entry><entry>Shorter essays on a dramatic
story or individual</entry></row>
<row><entry>✒️ </entry><entry>Primary Sources</entry><entry>Firsthand accounts
from the time period</entry></row>
</tbody></tgroup></table>"""

ORGANIZER_PAGE = """
<para id="p2">What this chapter asks.</para>
<table id="key" class="unnumbered" summary="No Summary">
""" + ORGANIZER_KEY + """
<table id="plan" class="unnumbered" summary="No Summary">
<tgroup cols="2"><colspec colnum="1" colname="c1"/><colspec colnum="2" colname="c2"/>
<tbody>
<row><entry namest="c1" nameend="c2"><emphasis effect="bold">Chapter 1
(1763&#8211;1789)</emphasis></entry></row>
<row><entry namest="c1" nameend="c2"><emphasis effect="bold">Compelling Question: Why
did the colonies declare their independence?</emphasis></entry></row>
<row><entry><emphasis effect="bold">Supporting Question 1:</emphasis> What did the
colonists object to?</entry><entry><emphasis effect="bold">Resources:</emphasis> The
Stamp Act, a narrative</entry></row>
<row><entry><emphasis effect="bold">Supporting Question 2:</emphasis> Who led
them?</entry><entry><emphasis effect="bold">Resources:</emphasis> Samuel Adams, a
primary source</entry></row>
</tbody></tgroup></table>"""

NARRATIVE_PAGE = """
<para id="p3">The colonists objected to the tax.</para>
<table id="marks" class="unnumbered" summary="No Summary">
""" + ORGANIZER_KEY


def build_organizers(repo):
    """Two books with a page titled as *Life, Liberty, and the Pursuit of
    Happiness* titles its inquiry organizers, each with a key to the emoji
    and the chapter's plan, and a narrative page holding the same key: one
    of that book's style (ap-history), and one of a style that sets its
    tables as that one does, in the containers baking makes (precalculus;
    *U.S. History*'s doesn't)."""
    books = (("tiny-liberty", "ap-history", "Tiny Liberty", "ffffffffffff", 61007),
             ("tiny-other", "precalculus", "Tiny Other", "abababababab", 61011))
    write(os.path.join(repo, "META-INF", "books.xml"), """<container
 xmlns="https://openstax.org/namespaces/book-container" version="1">
""" + "".join(f"""<book slug="{slug}" style="{style}"
 href="../collections/{slug}.collection.xml"/>
""" for slug, style, *_ in books) + "</container>")
    for slug, _style, title, uuid, first in books:
        write(os.path.join(repo, "collections", f"{slug}.collection.xml"),
              COLLECTION.format(title=title, slug=slug,
                                uuid=f"11111111-2222-4333-8444-{uuid}",
                                content=f"""
<col:subcollection><md:title>1763&#8211;1789</md:title><col:content>
<col:module document="m{first}"/>
<col:module document="m{first + 1}"/>
<col:module document="m{first + 2}"/>
</col:content></col:subcollection>"""))
        module(repo, f"m{first}", "Introduction", """
<para id="p1">This chapter opens.</para>""", cls="introduction")
        module(repo, f"m{first + 1}", "\U0001F4CE Inquiry Organizer", ORGANIZER_PAGE)
        module(repo, f"m{first + 2}", "\U0001F50E The Stamp Act", NARRATIVE_PAGE)


def case_organizers(work):
    from lxml import etree
    from cnx import steptables
    repo = os.path.join(work, "osbooks-organizers")
    build_organizers(repo)
    pages, said = {}, {}
    for slug in ("tiny-liberty", "tiny-other"):
        out = os.path.join(work, slug)
        result = unpack(repo, out, "--book", slug)
        said[slug] = result.stdout + result.stderr
        pages[slug] = [read(out, name) for name in sorted(os.listdir(out))
                       if name.endswith(".html")] if result.returncode == 0 else []

    def table(slug, name):
        for page in pages[slug]:
            found = re.search(r'<table\b[^>]*\bid="%s".*?</table>' % name, page, re.S)
            if found:
                return found.group(0)
        return ""

    def key(rows):
        return steptables.symbol_key(etree.fromstring(
            "<table><tbody>%s</tbody></table>" % rows))

    def untouched(slug, name):
        markup = table(slug, name)
        return bool(markup) and "<th" not in markup and "role=" not in markup
    return [
        ("on an inquiry organizer, the key to the emoji the book's page titles "
         "carry is a data table whose rows its emoji head, and the chapter's "
         "plan, its questions and their resources, is a layout table",
         lambda: table("tiny-liberty", "key").count('<th scope="row">') == 3
         and table("tiny-liberty", "key").count("<td") == 6
         and "role=" not in table("tiny-liberty", "key")
         and 'role="presentation"' in table("tiny-liberty", "plan")
         and "1 table(s) that only lay things out" in said["tiny-liberty"]),
        ("the same key on another page of the book is left as it is",
         lambda: untouched("tiny-liberty", "marks")),
        ("a key opens every row with a symbol alone, words beside it: a "
         "first column of words, or a symbol with nothing beside it, is none",
         lambda: key("<tr><td>\U0001F4CE </td><td>Inquiry Organizer</td></tr>"
                     "<tr><td>\u270f\ufe0f</td><td>Unit Essay Activity</td></tr>")
         and not key("<tr><td>Narratives</td><td>Shorter essays</td></tr>"
                     "<tr><td>Lessons</td><td>Handouts</td></tr>")
         and not key("<tr><td>\U0001F4CE</td><td></td></tr>"
                     "<tr><td>\U0001F50E</td><td> </td></tr>")),
        ("and so are an organizer's tables in a book of another style",
         lambda: untouched("tiny-other", "key") and untouched("tiny-other", "plan")),
    ]


# A table baking leaves where it stands ----------------------------------

UNWRAPPED_PAGE = """
<para id="p2">The colonies had grown.</para>
<table id="byline" class="unnumbered" summary="Who wrote it.">
<tgroup cols="1"><tbody>
<row><entry>Written by: A. Historian, A College</entry></row>
</tbody></tgroup></table>
<table id="people" class="unnumbered" summary="The colonies' people in 1750."
 aria-label="A table of two columns, the colony and its people.">
<tgroup cols="2"><thead><row><entry>Colony</entry><entry>People</entry></row></thead>
<tbody><row><entry>Virginia</entry><entry>231,000</entry></row>
<row><entry>Maryland</entry><entry>141,000</entry></row></tbody></tgroup></table>"""


def build_unwrapped(repo):
    """A book of *U.S. History*'s style (history), whose recipe leaves an
    unnumbered table where it stands, outside the container it bakes a
    numbered one in."""
    write(os.path.join(repo, "META-INF", "books.xml"), """<container
 xmlns="https://openstax.org/namespaces/book-container" version="1">
<book slug="tiny-usa" style="history"
 href="../collections/tiny-usa.collection.xml"/>
</container>""")
    write(os.path.join(repo, "collections", "tiny-usa.collection.xml"),
          COLLECTION.format(title="Tiny USA", slug="tiny-usa",
                            uuid="11111111-2222-4333-8444-acacacacacac",
                            content="""
<col:subcollection><md:title>The Colonies</md:title><col:content>
<col:module document="m61015"/>
<col:module document="m61016"/>
</col:content></col:subcollection>"""))
    module(repo, "m61015", "Introduction", """
<para id="p1">This chapter opens.</para>""", cls="introduction")
    module(repo, "m61016", "The Colonies", UNWRAPPED_PAGE)


def case_unwrapped(work):
    repo = os.path.join(work, "osbooks-unwrapped")
    build_unwrapped(repo)
    out = os.path.join(work, "tiny-usa")
    result = unpack(repo, out, "--book", "tiny-usa")
    page = read(out, "1-1-the-colonies.html") if result.returncode == 0 else ""
    report = report_of(out) if result.returncode == 0 else []
    captions = os.path.join(out, "table-captions.csv")
    drafted = read(captions) if os.path.exists(captions) else ""

    def table(name):
        found = re.search(r'<table\b[^>]*\bid="%s"[^>]*>' % name, page)
        return found.group(0) if found else ""
    return [
        ("a table baking leaves outside its container, as U.S. History's style "
         "leaves an unnumbered one, is decided as any other: one of one cell is "
         "a layout table, and the run counts it",
         lambda: 'role="presentation"' in table("byline")
         and "class=\"os-table\"" not in page
         and "1 table(s) that only lay things out" in result.stdout),
        ("and its summary is drafted as its description, and OpenStax's label "
         "for it left out and reported",
         lambda: table("people") and 'role="presentation"' not in table("people")
         and "The colonies' people in 1750." in drafted
         and "aria-label" not in page
         and [r["Detail"] for r in report if r["Check"] == "table-label-left-out"]
         == ["people: A table of two columns, the colony and its people."]),
    ]


# Which summaries read their tables out ------------------------------------

def case_read_out(work):
    from cnx.project import reads_out
    colonies = [["Virginia", "tobacco"], ["Maryland", "corn"], ["Georgia", "rice"],
                ["Carolina", "indigo"], ["New York", "furs"], ["Delaware", "wheat"]]
    digits = [["1", "2"], ["3", "4"], ["5", "6"]]
    # Each of six cells the summary has only as the comparison has it: in
    # capitals and without its period, a hyphen for its dash, a straight
    # apostrophe for its curly one, "fi" for its ligature, a hyphen for its
    # minus sign, one space for its two; six more it hasn't.
    unlike = [["Virginia.", "1\u20132 shillings"], ["Newton\u2019s law", "\ufb01ne print"],
              ["\u22123", "two  words"], ["alpha", "beta"], ["gamma", "delta"],
              ["epsilon", "zeta"]]
    return [
        ("a summary that reads a numbered row's or column's cells reads its table "
         "out, where one that names a column, or rows, by number doesn't",
         lambda: reads_out("The first row is a header row. Row 2 has “Big Bang” and 10 "
                           "to the 68.")
         and reads_out("Column 1 has the values: 0 to 0.1, 0.1 to 1, and 2.")
         and reads_out("Rows two through five contain “theta subscript f equals theta”.")
         and reads_out("Row one is for grades 49.5-59.5 and the frequency is 2.")
         and not reads_out("Column 1 lists types of measurements. Column two contains "
                           "their units.")
         and not reads_out("Rows 4 and 5 show the options for Firm A.")),
        ("so does one that lists a header's numbers",
         lambda: reads_out("To the right of the header, “Rate,” are the numbers: 0.10, "
                           "0.20, and 0.30.")),
        ("and one that gives a function's values, whole numbers or not",
         lambda: reads_out("The values of f(x) are: f(1)=3, f(2)=2, and f(5)=5.")
         and reads_out("When x=3, g(3)=2, f(g(3))=8, f(3)=3, and g(f(3))=2.")
         and reads_out("Its values: f(1)=1.5, f(2)=2.5, and f(3)=3.5.")),
        ("and one that repeats six of its table's cells, from two columns, in words "
         "of its own",
         lambda: reads_out("Virginia grew tobacco, Maryland corn, and Georgia rice.",
                           colonies)),
        ("or five, where they're half of its cells, but not five of twelve",
         lambda: reads_out("Virginia grew tobacco, Maryland corn, and Georgia much else.",
                           colonies[:5])
         and not reads_out("Virginia grew tobacco, Maryland corn, and Georgia much else.",
                           colonies)),
        ("but not one that names one column's cells, its rows' names",
         lambda: not reads_out("The crops of Virginia, Maryland, Georgia, Carolina, New "
                               "York, and Delaware.", colonies)),
        ("a cell of a letter alone isn't counted, one of a digit is",
         lambda: not reads_out("Graphs a, b, c, d, e, and f, each a scatter plot.",
                               [["A", "B"], ["C", "D"], ["E", "F"]])
         and reads_out("x is 1, 3, and 5, and y is 2, 4, and 6.", digits)),
        ("a number inside another isn't a cell's: 1 in 0.1, 11, or 1.5",
         lambda: not reads_out("Near 0.1, 0.2, 0.3, 0.4, 0.5, and 0.6; 11, 22, 33, 44, 55, "
                               "and 66; 1.5, 2.5, 3.5, 4.5, 5.5, and 6.5.", digits)),
        ("a cell is found whatever its case, its dashes, its quotation marks, its "
         "ligatures, its spacing, or a period after it",
         lambda: reads_out("VIRGINIA charged 1-2 shillings under Newton's law, in the "
                           "fine print, at -3, in two words.", unlike)),
    ]


# The collation glossaries and indexes are sorted by -----------------------

def case_collation(work):
    from cnx.bake.directions import _group_of, collation_key
    words = ["zebra", "#hashtag", "\napple", "Apple", "apple", "a-b",
             "a_b", "a b", "a,b", "(a)", "2nd", "éclair", "eclair",
             "Ecole", "“quoted”", "a/b", "a&b"]
    ordered = sorted(words, key=collation_key)
    return [
        ("space and punctuation sort before digits, digits before letters, "
         "in CLDR's order",
         lambda: ordered.index("\napple") == 0
         and ordered.index("“quoted”") < ordered.index("(a)")
         < ordered.index("#hashtag") < ordered.index("2nd")
         < ordered.index("a b")),
        ("within a word: _ - , then / & then letters",
         lambda: ordered.index("a b") < ordered.index("a_b")
         < ordered.index("a-b") < ordered.index("a,b") < ordered.index("a/b")
         < ordered.index("a&b") < ordered.index("apple")),
        ("case and accents count only when nothing else differs, "
         "lowercase first",
         lambda: ordered.index("apple") < ordered.index("Apple")
         and ordered.index("eclair") < ordered.index("éclair")
         < ordered.index("Ecole") < ordered.index("zebra")),
        ("an index entry's group is its first letter as Ruby's I18n spells "
         "it in ASCII: an accent off, Æ as Ae, and Greek or a digit under "
         "Symbols, as Biology 2e's α-helix is",
         lambda: [_group_of(w) for w in ("α-helix", "éclair", "Æther", "2nd",
                                         "zebra", "łódź")]
         == [None, "E", "Ae", None, "Z", "L"]),
    ]


# A note's heading, from baking's markup -------------------------------------

def case_note_headings(work):
    """The emitter on notes as baking writes them: a label that ends in its
    divider's space, as Calculus' theorems do, and ids on the label and on
    the title, as OpenStax's own assembly writes them."""
    from lxml import etree
    from cnx.cnxml import E
    from cnx.emit import Emitter

    def emitted(markup):
        out = E("div")
        Emitter(None, [], "en", []).dt_note(etree.fromstring(markup), out, 2,
                                            None)
        return etree.tostring(out, encoding="unicode")

    theorem = emitted(
        '<div data-type="note" class="theorem" id="n1"><h3 data-type="title" '
        'class="os-title"><span class="os-title-label">Theorem</span> <span '
        'class="os-number">2.1</span><span class="os-divider"> </span></h3>'
        '<div class="os-note-body"><h4 data-type="title" class="os-subtitle" '
        'id="sub1"><span class="os-subtitle-label">Two Important Limits</span>'
        '</h4><p id="p1">Let a be a real number.</p></div></div>')
    try_it = emitted(
        '<div data-type="note" class="try" id="n2"><h3 data-type="title" '
        'class="os-title"><span class="os-title-label">Try it</span><span '
        'id="lab2"></span></h3><div class="os-note-body"><h4 data-type="title" '
        'class="os-subtitle" id="sub2"><span class="os-subtitle-label">Try It: '
        'The Terms</span></h4><p id="p2">Find them.</p></div></div>')
    return [
        ("a label that ends in a space, its divider's, has none before the "
         "colon",
         lambda: '<h3><span class="os-note-label">Theorem 2.1</span>: Two '
         'Important Limits' in theorem),
        ("the title's own id stays, an anchor in the heading, when it joins "
         "its label",
         lambda: re.search(r'Two Important Limits<span id="sub1"/></h3>',
                           theorem)),
        ("and when it stands alone, an id the label held kept as well",
         lambda: re.search(r'<h3>(<span id="lab2"/>)?Try It: The Terms'
                           r'(<span id="sub2"/>)?</h3>', try_it)
         and 'id="lab2"' in try_it and 'id="sub2"' in try_it
         and "Try it" not in try_it),
    ]


# The Symbol font's characters, in an attribute too ---------------------------

def case_symbol_font(work):
    """What the emitter's finishing makes of a character of the Symbol
    font in an attribute, as the statistics books' alt text has one, and
    in a formula."""
    from lxml import etree
    from cnx.emit import finish
    page = etree.fromstring(
        '<div><p><img alt="Line 6. a = \uF02D173.5" src="x.png"/> '
        '<math xmlns="http://www.w3.org/1998/Math/MathML"><mi>\uF061</mi></math>'
        '</p></div>')
    counts = finish(page)
    return [
        ("a character of the Symbol font in an attribute or a formula is the "
         "character the font draws, and is counted",
         lambda: page.find(".//img").get("alt") == "Line 6. a = \u2212173.5"
         and "<mi>\u03b1</mi>" in etree.tostring(page, encoding="unicode")
         and counts == {"\uF02D": 1, "\uF061": 1}),
    ]


# Baking's steps, one at a time ---------------------------------------------

def case_steps(work):
    from lxml import etree
    from cnx.cnxml import E
    from cnx.bake import directions as d, injected as inj
    from cnx.bake.core import Book
    from cnx.bake.strings import for_style

    def book_of(markup):
        root = etree.fromstring(markup)
        body = root if root.tag == "body" else root.find("body")
        return Book(body, for_style("economics"), "economics")

    key = book_of("""<body><div data-type="composite-chapter"
 class="os-eob os-solutions-container"><h1>Answer Key</h1>
<div data-type="composite-page" class="os-eob"><h2>Chapter 1</h2>
<div data-type="question-solution">a.</div></div>
<div data-type="composite-page" class="os-eob"><h2>Chapter 2</h2>
<p>Nothing.</p></div></div></body>""")
    d.answer_key_cleaner(key)
    kept = [p.findtext("h2") for p in key.body.iter("div")
            if p.get("data-type") == "composite-page"]

    links = etree.fromstring(
        "<p>Read http://example.org/a.pdf. Or www.example.org, or write "
        "to a.b@example.org; <a href='#x'>www.kept.org</a> "
        "<code>http://code.org</code> e.g. 3.5, "
        "https://example.org/p?i=1#{%22page%22:0} and https://example.org/q#:~:text=In%"
        " \u201cwww.example.net\u201d, \u201chttp://.\u201d, https://example..org/a and "
        "www.example.com/lec.pdf\u200e</p>")
    d.convert_textual_links(links)
    made = [(a.get("href"), a.text) for a in links.iter("a")]
    hashed = etree.fromstring(
        "<p>Filed 1994, https://example.org/f?year=1994##doc-2.</p>")
    d.convert_textual_links(hashed)
    numbered = etree.fromstring(
        "<p>See https://doi.10.1111/bcp.13499 and http://192.0.2.1/x.</p>")
    d.convert_textual_links(numbered)

    neb = book_of("""<html><head><title>A Book 3e</title></head><body>
<div data-type="page" id="page_abc"><div data-type="injected-exercise">
<div data-type="exercise-question" data-id="42"><div
 data-type="question-stem">Why?</div></div></div>
<table id="t1"><caption><span data-type="title">Prices</span>(Source:
 a survey)</caption><tbody><tr><td>1</td></tr></tbody></table>
<p><a href="#t1" class="autogenerated-content">[link]</a></p>
</div></body></html>""")
    inj.add_injected_exercise_id(neb)
    question = [q for q in neb.body.iter("div")
                if q.get("data-type") == "exercise-question"][0]
    table = neb.body.find(".//table")
    d.bake_numbered_table(neb, table, "1.1")
    d.bake_link_placeholders(neb)
    caption = " ".join("".join(neb.body.xpath(
        ".//div[@class='os-caption-container']")[0].itertext()).split())

    # Accounting's learning objective links and exercise prefixes, and
    # Principles of Finance's numbered notes.
    def styled(markup, style):
        return Book(etree.fromstring(markup), for_style(style), style)

    acc = styled("""<body><div data-type="chapter"><h1
 data-type="document-title">Accounting</h1>
<div data-type="page" class="introduction" id="page_i"><h1
 data-type="document-title">Introduction</h1></div>
<div data-type="page" id="page_a"><h1 data-type="document-title">Costs</h1>
<p><a class="lo-reference autogenerated-content" href="#page_a"/> Costs?</p>
<section class="exercise-set-a"><div data-type="exercise" id="e1"><div
 data-type="problem"><p>Add.</p></div></div></section></div></div></body>""",
                 "accounting")
    chapter = acc.chapters()[0]
    d.bake_non_introduction_pages(acc, chapter, custom_target_label=True)
    d.move_custom_section_to_eoc(acc, chapter, "exercise-set-a",
                                 "exercise-set-a", each=d.remove_section_title)
    d.bake_numbered_exercise(acc, acc.body.xpath(
        ".//div[@data-type='exercise']")[0], 1)
    d.bake_exercise_prefixes(acc, chapter, ["exercise-set-a"])
    d.bake_link_placeholders(acc)
    d.bake_lo_link_labels(acc)
    lo = " ".join("".join(acc.body.xpath(".//a")[0].itertext()).split())
    problem = " ".join("".join(acc.body.xpath(
        ".//div[@data-type='problem']")[0].itertext()).split())

    fin = styled("""<body><div data-type="chapter"><h1
 data-type="document-title">Finance</h1>
<div data-type="page" id="page_f"><h1 data-type="document-title">Bonds</h1>
<div data-type="note" class="think-through" id="n1"><p>One.</p></div>
<div data-type="note" class="think-through" id="n2"><p>Two.</p></div>
</div></div></body>""", "finance")
    d.bake_numbered_notes_v1(fin, ["think-through"])
    notes = [" ".join("".join(h.itertext()).split())
             for h in fin.body.xpath(".//h3")]

    # The nursing books' links to a section, and their case studies'
    # solutions; the Python book's solutions under their page's title.
    nur = styled("""<body><div data-type="chapter"><h1
 data-type="document-title">Drugs</h1>
<div data-type="page" class="introduction" id="page_i"><h1
 data-type="document-title">Introduction</h1></div>
<div data-type="page" id="page_d"><h1 data-type="document-title">Doses</h1>
<p><a class="autogenerated-content" href="#page_d"/> says so.</p>
<div data-type="note" class="single-casestudy"><div
 data-type="question-solution">b.</div></div>
<div data-type="note" class="learning-questions"><div
 data-type="solution">a.</div></div></div></div></body>""",
                 "nursing-external")
    chapter = nur.chapters()[0]
    d.bake_non_introduction_pages(nur, chapter)
    d.bake_link_placeholders(nur, replace_section_link_text=True)
    section_link = nur.body.findtext(".//p/a")
    holder = E("div")
    inj.move_solutions_from_numbered_note(nur, chapter, holder,
                                          "single-casestudy")
    inj.move_solutions_from_autotitled_note(
        nur, nur.pages(chapter)[1], holder, "learning-questions",
        title=nur.page_title(nur.pages(chapter)[1]))
    areas = [" ".join(" ".join(a.itertext()).split()) for a in holder]

    # The Writing Guide's handbook, and its pages and sections retitled.
    guide = Book(etree.fromstring("""<body><div data-type="page" id="hb"
 class="handbook"><div data-type="document-title">Handbook</div>
<section id="s1"><h3 data-type="title">Grammar Essentials</h3><p>Nouns.</p>
</section><section id="s2"><h3 data-type="title">Verbs</h3></section></div>
<div data-type="chapter"><h1 data-type="document-title">Reading</h1>
<div data-type="page" id="tb" class="narrative-trailblazer"><h2
 data-type="document-title"><span class="os-number">1.2</span><span
 class="os-divider"> </span><span class="os-text">Social Media Trailblazer:
 Selena Gomez</span></h2><div id="empty"></div><p>Text.</p></div>
<div data-type="page" id="lw"><h2 data-type="document-title">Sample</h2>
<section id="s3" class="living-words"><h3 data-type="title">Thread</h3>
</section><section id="s4" class="quick-launch"><h3 data-type="title">Mapping
 <em>it</em></h3></section></div></div></body>"""),
        for_style("english-composition"), "english-composition")
    d.bake_handbook(guide)
    d.bake_custom_sections(guide, guide.chapters()[0], [
        ("narrative-trailblazer", "title"), ("living-words", "subtitle"),
        ("quick-launch", "title_prefix")])
    handbook = guide.body.find("div")
    trailblazer = guide.body.xpath(".//div[@id='tb']")[0]
    from cnx.pages import collect
    named = {p.element.get("id"): p.name for p in collect(guide)[1]}
    return [
        ("the Writing Guide's handbook: its sections H1, H2, an Outline "
         "after its title linking to each",
         lambda: [" ".join(" ".join(t.itertext()).split())
                  for t in handbook.xpath("./section/*[@data-type='title']")]
         == ["H 1 . Grammar Essentials", "H 2 . Verbs"]
         and [a.get("href") for a in handbook.iter("a")] == ["#s1", "#s2"]
         and handbook[1].get("class") == "os-handbook-outline"),
        ("a Trailblazer page is titled by its kind, its own title a paragraph "
         "after it and its name, the empty div after its title gone; a "
         "section's kind a paragraph before it, or its title's prefix",
         lambda: "".join(trailblazer[0].itertext()).endswith("Trailblazer")
         and trailblazer[1].tag == "p"
         and " ".join(trailblazer[1].text.split())
         == "Social Media Trailblazer: Selena Gomez"
         and not trailblazer.xpath(".//div[@id='empty']")
         and named["tb"] == "1-2-social-media-trailblazer-selena-gomez"
         and guide.body.xpath(".//section[@id='s3']")[0].getprevious().text
         == "Living by Their Own Words"
         and " ".join("".join(guide.body.xpath(".//section[@id='s4']/h3")[0]
                                .itertext()).split()) == "Quick Launch: Mapping it"),
        ("an answer key's page goes when it has no solution on it, and "
         "stays when its one solution is an exercise's from the bank",
         lambda: kept == ["Chapter 1"]),
        ("an address or an email address written as text is a link to "
         "itself, but not in a link or code, nor a number; what a link's "
         "address can't hold, a lone % or a brace, is escaped in it; a "
         "closing quotation mark or an invisible mark after it is text "
         "after the link, and an address with no host's name no link",
         lambda: made == [("http://example.org/a.pdf",
                           "http://example.org/a.pdf"),
                          ("https://www.example.org", "www.example.org"),
                          ("mailto:a.b@example.org", "a.b@example.org"),
                          ("#x", "www.kept.org"),
                          ("https://example.org/p?i=1#%7B%22page%22:0",
                           "https://example.org/p?i=1#{%22page%22:0"),
                          ("https://example.org/q#:~:text=In%25",
                           "https://example.org/q#:~:text=In%"),
                          ("https://www.example.net", "www.example.net"),
                          ("https://www.example.com/lec.pdf",
                           "www.example.com/lec.pdf")]),
        # A second #, which a link's fragment can't hold, as the first: the
        # Nu checker's error and epubcheck's (Marketing's references).
        ("and so is a # after the one that opens the fragment",
         lambda: [(a.get("href"), a.text) for a in hashed.iter("a")]
         == [("https://example.org/f?year=1994#%23doc-2",
              "https://example.org/f?year=1994##doc-2")]),
        # A period for "org/" makes a host ending in a number, which the
        # URL Standard reads as an IPv4 address and rejects (the nursing
        # books' references, eight times).
        ("an address whose host ends in a number that isn't an IPv4 "
         "address stays text, and an IPv4 address is linked",
         lambda: [(a.get("href"), a.text) for a in numbered.iter("a")]
         == [("http://192.0.2.1/x", "http://192.0.2.1/x")]),
        ("in OpenStax's own assembly's shape: a question from the bank "
         "is given its id, a caption's text beside its title kept, a "
         "link's [link] named, and the edition read from the head's title",
         lambda: question.get("id") == "auto_abc_42"
         and caption == "Table 1.1 Prices (Source: a survey)"
         and neb.body.findtext(".//p/a") == "Table 1.1"
         and neb.title_text() == "A Book 3e"),
        ("a link to a learning objective shows its section's number "
         "(\"LO 1.1\"), and an exercise in an exercise set opens with "
         "the set's prefix (\"EA1\")",
         lambda: lo == "LO 1.1" and problem.startswith("EA1. Add.")),
        ("a numbered note is numbered in its chapter",
         lambda: notes == ["Think It Through 1.1", "Think It Through 1.2"]),
        ("a link to a section can show its number alone (\"Section "
         "1.1\"); a case study's solutions go to the answer key under "
         "its title, a note's under its page's numbered title",
         lambda: section_link == "Section 1.1"
         and areas == ["Case Study b.", "1.1 Doses a."]),
    ]


def case_cookbook(work):
    """With CNX_COOKBOOK naming a clone of openstax/cookbook, each
    ported recipe bakes cookbook's sample book as cookbook does."""
    cookbook = os.environ.get("CNX_COOKBOOK")
    if not cookbook:
        print("  skip  set CNX_COOKBOOK to a clone of openstax/cookbook to "
              "compare with its sample books")
        return []
    run = subprocess.run(
        ["python3", os.path.join(ROOT, "util", "cnx-compare-cookbook.py"),
         cookbook], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    lines = [line for line in run.stdout.splitlines()
             if not line.startswith(" ")]
    return [(f"{line.split(':')[0]}: every page as cookbook bakes it",
             lambda line=line: line.endswith("none differ"))
            for line in lines] + [
        ("the comparison ran", lambda: run.returncode == 0 and lines)]


# What convert.py makes of an unpacked book -------------------------------

def pandoc_version():
    pandoc = shutil.which("pandoc")
    if pandoc is None:
        return None
    out = subprocess.run([pandoc, "--version"], capture_output=True,
                         text=True).stdout
    m = re.match(r"pandoc\S*\s+(\d+)\.(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else None


def case_convert(work):
    version = pandoc_version()
    if version is None or version < (3, 9):
        print("  skip  converting needs Pandoc 3.9 or later")
        return []
    repo = os.path.join(work, "osbooks-trade")
    build_trade(repo)
    out = os.path.join(work, "trade")
    unpack(repo, out, "--book", "tiny-trade")
    write(os.path.join(out, "conversion.yaml"),
          read(out, "conversion.yaml") + "targets:\n  html:\n    format: html\n"
          "  tex:\n    format: latex\n")
    run = subprocess.run(["python3", os.path.join(BIN, "convert.py"),
                          "--quick", "--quiet"], cwd=out, capture_output=True,
                         text=True, stdin=subprocess.DEVNULL)
    page = os.path.join(out, "html", "1-1-why-trade-happens.html")
    html = read(page) if os.path.exists(page) else ""
    master = os.path.join(out, "tex", "book-11111111-2222-4333-8444-555555555555.tex")
    latex = read(master) if os.path.exists(master) else ""
    page = os.path.join(out, "html", "chapter-1.html")
    key = read(page) if os.path.exists(page) else ""
    unplaced = os.path.join(out, "table-captions-missing.csv")
    return [
        ("the book converts",
         lambda: run.returncode == 0 and html != ""),
        ("each page ends with OpenStax's attribution, its address not a link",
         lambda: re.search(r"</main>\s*<footer>\s*<p>Access for free at openstax\.org\.</p>"
                           r"\s*</footer>\s*</body>", html)),
        ("and the LaTeX has OpenStax's paper and margins with 12pt type on lines 1.5 "
         "times its size apart, ragged right, the attribution at every page's foot",
         lambda: re.search(r"\\documentclass\[[^]]*\b12pt,\s*letterpaper,", latex)
         and "\\usepackage[left=1in,right=1in,top=0.8in,bottom=0.8in,footskip=0.3in]"
             "{geometry}" in latex
         and "\\setstretch{1.25}" in latex
         and "\\AtBeginDocument{\\@rightskip\\@flushglue\\rightskip\\@rightskip}" in latex
         and "\\newcommand\\OERFooterText{Access for free at openstax.org.}" in latex),
        ("and its text is in IBM Plex Serif, named by its files, babel's face for its "
         "language as well, with the fallback fonts for a character it lacks, and its "
         "formulas in IBM Plex Math",
         lambda: "\\setmainfont{IBMPlexSerif}[" + PLEX_FILES
         + ",RawFeature={fallback=oerfallback}]" in latex
         and "\\babelfont{rm}[" + PLEX_FILES + ",RawFeature={fallback=oerfallback}]"
         "{IBMPlexSerif}" in latex
         and "\\setmathfont[]{IBMPlexMath-Regular.otf}" in latex),
        ("its footnote is a note again, nothing left of the markup",
         lambda: "footnote" in html and "doc-endnotes" in html
         and "Reference not found" not in run.stderr),
        ("its table keeps its caption, and the summary's description is "
         "joined to the bare one's",
         lambda: "Output per Hour" in html
         and "Hours worked by each person" in html),
        ("a table with no caption is given its summary under the key "
         "TextbookImprover reports it by, its place on its page",
         lambda: unescape(flat(re.search(r'id="tab3".*?</caption>', key, re.S)
                               .group(0))).endswith("The cost of each choice—trade or not")
         and not os.path.exists(unplaced)),
    ]


CASES = [
    ("a repository of OpenStax's, baked as economics", case_trade),
    ("a book of the Connexions archive's", case_archive),
    ("exercises from OpenStax's exercise bank", case_bank),
    ("Organic Chemistry's problems and pages", case_organic),
    ("a book in Polish", case_polish),
    ("a chapter's review, a group of its own", case_review),
    ("a nursing book's references, gathered by chapter", case_references),
    ("a math book, baked as College Algebra is", case_precalculus),
    ("a worked example's steps in a table, a layout table", case_step_tables),
    ("a grid of key terms, a corequisite book's steps, Key Equations, a box of "
     "one cell, a form, pictures, and a matching exercise, layout tables, and "
     "summaries that read a table out", case_layout_kinds),
    ("an inquiry organizer's key and plan", case_organizers),
    ("a table baking leaves outside its container", case_unwrapped),
    ("which summaries read their tables out", case_read_out),
    ("the collation", case_collation),
    ("baking's steps, one at a time", case_steps),
    ("a note's heading, from baking's markup", case_note_headings),
    ("the Symbol font's characters, in an attribute too", case_symbol_font),
    ("cookbook's own sample books", case_cookbook),
    ("converting an unpacked book", case_convert),
]


def main():
    try:
        import lxml  # noqa: F401
    except ImportError:
        print("skip  unpack-cnx.py needs lxml")
        return 0
    work = tempfile.mkdtemp(prefix="cnx-tests-")
    failed = 0
    try:
        for label, case in CASES:
            print(f"\n{label}")
            try:
                checks = case(os.path.join(work, label.replace(" ", "-")))
            except Exception as exc:
                print(f"  ERROR {label}: {exc}")
                failed += 1
                continue
            for name, predicate in checks:
                try:
                    ok = predicate()
                except Exception as exc:
                    ok, name = False, f"{name}  ({exc})"
                print(("  ok    " if ok else "  FAIL  ") + name)
                failed += not ok
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"\n{failed} check(s) failed" if failed
          else "\nall CNX checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
