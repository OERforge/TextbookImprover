#!/usr/bin/env python3
"""
run-site-tests.py -- check unpack-site.py and the libraries under it.

    python3 tests/run-site-tests.py

The saves are built here, by hand, in the shapes the real ones take: a
browser's "complete" save (a comment naming the URL, a _files directory
per page, the same image saved by two pages, links absolute to the live
site) for a just-the-docs book whose pages also carry an index that
reaches every page in alphabetical order; and an .mhtml set shaped like
Racket's Scribble (no generator meta, a numbered contents page with a
part in roman numerals, a link icon on every heading, <a name> anchors).
Needs an HTML parser (html5lib, or lxml) and nothing else.

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
import io
import os
import shutil
import subprocess
import sys
import tempfile
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin")
sys.path.insert(0, os.path.join(ROOT, "lib"))

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYGAAAAAEAAH2"
    "FzhVAAAAAElFTkSuQmCC")
SITE = "https://book.example.org/"
PAGES = [("index", "Home", None), ("ch1/index", "Chapter One", None),
         ("ch1/alpha", "Alpha", "ch1/index"), ("ch1/beta", "Beta", "ch1/index"),
         ("ch2/gamma", "Gamma", None), ("colophon", "Colophon", None),
         ("glossary", "Glossary", None)]
IN_MENU = [p for p in PAGES if p[0] not in ("colophon", "glossary")]


def menu():
    items = []
    for path, title, parent in IN_MENU:
        if parent:
            continue
        kids = "".join(f'<li><a href="{SITE}{p}.html">{t}</a></li>'
                       for p, t, par in IN_MENU if par == path)
        items.append(f'<li><a href="{SITE}{path}.html">{title}</a>'
                     + (f"<ul>{kids}</ul>" if kids else "") + "</li>")
    return f'<nav id="site-nav"><ul>{"".join(items)}</ul></nav>'


def index_block():
    # Every page, scattered: the shape of a back-of-book index. It reaches
    # two pages the menu doesn't. Every page also links itself (its
    # heading's anchor), so a page outside the menu reaches the menu's
    # pages plus one: only the index reaches everything, and only its
    # shape can lose it the vote.
    terms = []
    for path, title, _ in sorted(PAGES, key=lambda p: p[1]) * 2:
        terms.append(f'<li><a href="{SITE}{path}.html#t">{title}</a>, '
                     f'<a href="{SITE}{PAGES[0][0]}.html#x">see home</a></li>')
    return f'<div class="book-index"><ul>{"".join(terms)}</ul></div>'


def saved_page(directory, path, title):
    name = title.replace(" ", "_")
    files = name + "_files"
    os.makedirs(os.path.join(directory, files), exist_ok=True)
    with open(os.path.join(directory, files, "figure.png"), "wb") as fh:
        fh.write(PNG)
    with open(os.path.join(directory, files, "just-the-docs-default.css"),
              "w") as fh:
        fh.write("body{}")
    extra = index_block() if path == "ch2/gamma" else ""
    html = f"""<!DOCTYPE html>
<!-- saved from url=(0040){SITE}{path}.html -->
<html lang="en-US"><head><meta name="generator" content="Jekyll v3.10.0">
<title>{title} | The Test Book</title>
<link rel="stylesheet" href="./{files}/just-the-docs-default.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/x/1/x.js"></script>
</head><body><div class="side-bar">{menu()}</div>
<main><nav class="js-toc"><ul><li><a href="#s">Section</a></li></ul></nav>
<h1 id="s"><a href="{SITE}{path}.html#s" class="anchor-heading">#</a>{title}</h1>
<p>Text with <a href="{SITE}ch1/alpha.html#deep">a link</a> and
<a href="{SITE}unsaved.html">a page nobody saved</a> and
<a href="https://elsewhere.example.com/">another site</a>.</p>
<p><img src="./{files}/figure.png" alt="A figure"> <img src="{SITE}missing.png" alt="Gone"></p>
<p><span href="http://purl.org/dc/dcmitype/Text" rel="dct:type">license</span>
<code>&lt;img src="/logo.png"&gt;</code></p>{extra}
<script>var tocbot = 1;</script>
</main><footer>Site footer</footer></body></html>"""
    with open(os.path.join(directory, name + ".html"), "w",
              encoding="utf-8") as fh:
        fh.write(html)


SCRIBBLE = "https://dcic.example.org/2025/"


def mhtml(directory, stem, title, body):
    message = MIMEMultipart("related", type="text/html")
    message["Snapshot-Content-Location"] = SCRIBBLE + stem + ".html"
    message["Subject"] = title
    page = MIMEText(f"""<html><head><title>{title}</title></head><body>
<div class="tocset">sidebar</div><div class="maincolumn"><div class="main">
<div class="navsettop"><a href="{SCRIBBLE}index.html">up</a></div>
{body}<div class="navsetbottom">bottom</div></div></div></body></html>""",
                    "html", "utf-8")
    page["Content-Location"] = SCRIBBLE + stem + ".html"
    message.attach(page)
    image = MIMEBase("image", "png")
    image.set_payload(base64.b64encode(PNG).decode())
    image["Content-Transfer-Encoding"] = "base64"
    image["Content-Location"] = SCRIBBLE + "pict.png"
    message.attach(image)
    with open(os.path.join(directory, stem + ".mhtml"), "wb") as fh:
        fh.write(message.as_bytes())


SCRIBBLE_TABLES = (
    '<table class="PyretReplInteraction"><tr><td><span class="PyretReplPrompt">'
    '›</span><pre>1 == 1</pre></td><td><pre>true</pre>'
    '<table class="PyretReplInteraction"><tr><td><pre>2 == 2</pre></td>'
    '</tr></table></td></tr></table>'
    '<table class="TwoColumnAsRows"><tr><td>Python</td><td><pre>a = 1</pre>'
    '</td></tr><tr><td>Pyret</td><td><pre>a = 1</pre></td></tr></table>'
    '<table><tr><td><span class="hspace">\u00a0\u00a0</span><span class="stt">'
    'b1 = box(7)</span></td></tr><tr><td><span class="stt">b2 = b1</span></td>'
    '</tr></table>'
    '<table><tr><td><a class="toptoclink" href="#p1">I<span class="hspace">'
    '\u00a0</span>Part</a></td></tr><tr><td><span class="hspace">\u00a0</span>'
    '</td></tr><tr><td><span class="hspace">\u00a0</span><a class="toclink" '
    'href="#c1">1 Chapter</a></td></tr></table>'
    '<table><tr><td>T(k)</td><td>=</td><td>T(k-1) + c</td></tr><tr><td></td>'
    '<td>=</td><td>T(k-2) + 2c</td></tr></table>'
    '<table class="RktBlk"><tr><td>(define x</td></tr><tr><td>\u00a0\u00a01)</td></tr>'
    '</table>'
    '<table><tr><td><a class="toclink" href="#a">2.1 One</a></td></tr>'
    '<tr><td><a class="toclink" href="#b">2.2 Two</a></td></tr></table>'
    '<table class="SVerbatim"><tr><td>line one</td></tr><tr><td>line two'
    '</td></tr></table>'
    '<table class="TwoColumn"><tr><td>Python</td><td>Pyret</td></tr>'
    '<tr><td><pre>x = 1</pre></td><td><pre>x = 1</pre></td></tr></table>')


def heading(number, title, stem):
    return (f'<h3>{number}<a name="(part._{stem})"></a>{title}'
            f'<span class="button-group"><a href="{SCRIBBLE}{stem}.html" '
            f'class="heading-anchor">\U0001F517</a></span></h3>')


def build_mhtml(directory):
    os.makedirs(directory)
    rows = [("I", "Introduction", "intro"), ("1", "Getting Started", "start"),
            ("1.1", "Naming", "naming"), ("II", "Data", "data"),
            ("2", "Tables", "tables")]
    toc = "".join(
        f'<p><a href="{SCRIBBLE}{s}.html" class="toclink">{n} {t}</a>'
        f'<a href="{SCRIBBLE}{s}.html#(part._x)" class="toclink">{n}.x More</a></p>'
        for n, t, s in rows)
    mhtml(directory, "index", "The Scribble Book",
          heading("", "The Scribble Book", "index")
          + '<p class="author">Ann One, Bo Two and Cy Three</p>' + toc)
    for n, t, s in rows:
        mhtml(directory, s, f"{n} {t}", heading(n, t, s)
              + f'<p>See <a href="{SCRIBBLE}naming.html#(part._naming)">naming'
              f'</a>.<img src="{SCRIBBLE}pict.png" alt="p"></p>'
              '<span class="MathJax">x</span>' + SCRIBBLE_TABLES
              if s == "tables" else
              heading(n, t, s) + f'<p><img src="{SCRIBBLE}pict.png" alt="p"></p>')


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


def unpack(inputs, out, *extra):
    return subprocess.run(["python3", os.path.join(BIN, "unpack-site.py")]
                          + inputs + ["-o", out] + list(extra),
                          capture_output=True, text=True)


def report(out):
    with open(os.path.join(out, "unpack-report.csv"), encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def case_browser_save(work):
    saves = os.path.join(work, "saves")
    os.makedirs(saves)
    for path, title, _ in PAGES:
        saved_page(saves, path, title)
    out = os.path.join(work, "book")
    result = unpack([saves], out)
    import yaml
    project = yaml.safe_load(read(out, "project.yaml"))["project"]
    alpha = read(out, "ch1-alpha.html")
    rows = report(out)
    checks = {(r["Check"], r["Detail"].split(" (from")[0]) for r in rows}
    whole = os.path.join(work, "site")
    unpack([saves], whole, "--whole-pages")
    whole_alpha = read(whole, "ch1-alpha.html")
    return [
        ("the run succeeds, a page per save, named by its path",
         lambda: result.returncode == 0 and sorted(
             n for n in os.listdir(out) if n.endswith(".html"))
         == ["ch1-alpha.html", "ch1-beta.html", "ch1-index.html",
             "ch2-gamma.html", "colophon.html", "glossary.html",
             "index.html"]),
        ("the generator is recognized from the pages",
         lambda: any(r["Check"] == "profile" and r["Detail"].startswith(
             "just-the-docs: recognized") for r in rows)),
        ("the menu is the order, not the index that reaches every page too",
         lambda: [c.get("page") or c["items"][0]["page"]
                  for c in project["contents"]][:3]
         == ["index", "ch1-index", "ch2-gamma"]
         and {c.get("page") for c in project["contents"][3:]}
         == {"colophon", "glossary"}
         and [i["page"] for i in project["contents"][1]["items"]]
         == ["ch1-index", "ch1-alpha", "ch1-beta"]),
        ("the book's name is the suffix every title shares, and comes off "
         "each page's",
         lambda: project["title"] == "The Test Book"
         and "<title>Alpha</title>" in alpha),
        ("a link to a page of the book is a link to its file, fragment kept",
         lambda: 'href="ch1-alpha.html#deep"' in alpha),
        ("an image two pages saved is one file, and both point at it",
         lambda: os.listdir(os.path.join(out, "assets")) == ["figure.png"]
         and 'src="assets/figure.png"' in read(out, "ch1-beta.html")),
        ("only the content is kept: menu, footer, a page's own toc, heading "
         "icons, and scripts go",
         lambda: "site-nav" not in alpha and "Site footer" not in alpha
         and "js-toc" not in alpha and "anchor-heading" not in alpha
         and "<script" not in alpha and "stylesheet" not in alpha),
        ("a resource on the site that wasn't saved is reported; a CDN "
         "script, another site, and RDFa aren't",
         lambda: ("resource-not-held", SITE + "missing.png") in checks
         and not any("cdnjs" in d or "purl.org" in d or "elsewhere" in d
                     for _, d in checks)),
        ("a link to a page of the site nobody saved is reported",
         lambda: ("page-not-saved", SITE + "unsaved.html") in checks),
        ("text that shows markup names no file",
         lambda: not any("logo" in d for _, d in checks)),
        ("--whole-pages keeps the menu and the stylesheet, both local",
         lambda: "site-nav" in whole_alpha
         and 'href="assets/just-the-docs-default.css"' in whole_alpha
         and 'href="ch1-beta.html"' in whole_alpha
         and os.path.exists(os.path.join(whole, "assets",
                                         "just-the-docs-default.css"))),
    ]


def case_mhtml(work):
    saves = os.path.join(work, "mhtml")
    build_mhtml(saves)
    out = os.path.join(work, "book")
    result = unpack([saves], out)
    import yaml
    project = yaml.safe_load(read(out, "project.yaml"))["project"]
    tables = read(out, "tables.html") if os.path.exists(
        os.path.join(out, "tables.html")) else ""
    rows = report(out)
    contents = project["contents"]
    return [
        ("the run succeeds and the pages are named without the edition's "
         "directory",
         lambda: result.returncode == 0 and os.path.exists(
             os.path.join(out, "naming.html"))),
        ("Scribble is recognized with no generator to say so",
         lambda: any(r["Check"] == "profile" and r["Detail"].startswith(
             "scribble") for r in rows)),
        ("numbered entries nest, a roman-numbered part above its chapters",
         lambda: contents[1]["title"] == "I Introduction"
         and contents[1]["items"][0]["page"] == "intro"
         and contents[1]["items"][1]["title"] == "1 Getting Started"
         and contents[1]["items"][1]["items"][1]["page"] == "naming"
         and contents[2]["items"][1]["page"] == "tables"),
        ("the authors are read from Scribble's author line",
         lambda: project.get("authors") == ["Ann One", "Bo Two", "Cy Three"]),
        ("neither a heading's icon nor an \"up\" link is a title: the "
         "contents page is named for itself",
         lambda: contents[0]["title"] == "The Scribble Book"),
        ("chrome goes, the heading's anchor becomes an id the reader keeps",
         lambda: "navsettop" not in tables and "heading-anchor" not in tables
         and '<span id="(part._tables)"></span>' in tables),
        ("a resource from the MHTML is a file, and the page points at it",
         lambda: 'src="assets/pict.png"' in tables
         and os.path.exists(os.path.join(out, "assets", "pict.png"))),
        ("a link into another page keeps its fragment",
         lambda: 'href="naming.html#(part._naming)"' in tables),
        ("a REPL interaction isn't a table: its prompt, code, and result "
         "remain",
         lambda: "PyretReplInteraction" not in tables
         and "<pre>1 == 1</pre>" in tables and "<pre>true</pre>" in tables
         and "<pre>2 == 2</pre>" in tables),
        ("code a line a row is one <pre>; the contents, a link a row, a "
         "list; a derivation lined up at its equals signs, a layout table",
         lambda: "<pre>  b1 = box(7)\nb2 = b1</pre>" in tables
         and '<ul class="contents"><li><a class="toptoclink"' in tables
         and tables.count("<li>") == 2 and 'role="presentation"' in tables),
        ("a Racket block laid out a line a row is one <pre>, indentation "
         "kept",
         lambda: "<pre>(define x\n  1)</pre>" in tables),
        ("a section's own table of contents goes, a verbatim table is one "
         "<pre>",
         lambda: "2.1 One" not in tables and "2.2 Two" not in tables
         and "<pre>line one\nline two</pre>" in tables),
        ("a comparison stays a table, its language row the header",
         lambda: '<th scope="col">Python</th>' in tables
         and '<th scope="col">Pyret</th>' in tables
         and '<th scope="row">Python</th>' in tables),
        ("equations present only as MathJax's rendering are reported",
         lambda: any(r["Check"] == "math-lost" and r["Where"] == "tables.html"
                     for r in rows)),
    ]


def case_parsers(work):
    import htmlparse as hp
    markup = "<p>a<wbr>b</p><p>c</p>"
    checks = []
    try:
        import html5lib  # noqa: F401
        hp.require("html5lib")
        tree = hp.parse(markup)
        checks.append(("html5lib: <wbr> is void, the paragraphs are siblings",
                       lambda: [hp.local(e.tag) for e in tree.iter()
                                if hp.local(e.tag) == "p"] == ["p", "p"]
                       and not any(hp.local(c.tag) == "p" for e in tree.iter()
                                   if hp.local(e.tag) == "wbr" for c in e)))
    except ImportError:
        print("  skip  html5lib not installed")
    try:
        import lxml.html  # noqa: F401
        stderr = io.StringIO()
        saved, sys.stderr = sys.stderr, stderr
        try:
            hp._WARNED = False
            hp.require("lxml")
            hp.require("lxml")
        finally:
            sys.stderr = saved
        checks.append(("falling back to lxml says so, once",
                       lambda: stderr.getvalue().count("html5lib isn't "
                                                       "installed") == 1))
    except ImportError:
        print("  skip  lxml not installed")
    finally:
        import importlib
        importlib.reload(hp)
    return checks


def warc_record(url, http, body, chunked=False, gzipped=False):
    import gzip as gz
    headers = "HTTP/1.1 " + http + "\r\n"
    if gzipped:
        body = gz.compress(body)
        headers += "Content-Encoding: gzip\r\n"
    if chunked:
        half = len(body) // 2
        body = b"".join(b"%x\r\n" % len(c) + c + b"\r\n"
                        for c in (body[:half], body[half:])) + b"0\r\n\r\n"
        headers += "Transfer-Encoding: chunked\r\n"
    block = (headers + "\r\n").encode() + body
    record = (f"WARC/1.1\r\nWARC-Type: response\r\nWARC-Target-URI: {url}"
              f"\r\nContent-Length: {len(block)}\r\n\r\n").encode() + block \
        + b"\r\n\r\n"
    return gz.compress(record)


def case_warc(work):
    os.makedirs(work)
    page = """<html><head><title>{t} | Archived</title>
<script src="https://cdn.example.org/mathjax/MathJax.js"></script></head><body>
<nav><ul><li><a href="/book/one.html">Home</a></li><li><a href="/book/two.html">
Two</a></li><li><a href="/book/three.html">Three</a></li></ul></nav>
<main><h1>{t}</h1><p><a href="/book/old.html#here">moved</a>
<img src="/book/pic.png" alt="p"></p>
<p>Suppose \\(k^2\\) nodes, so \\[E = mc^2\\] holds.</p>
<pre>print("\\(not math\\)")</pre>
</main></body></html>"""
    records = [
        warc_record(SITE + "book/one.html", "200 OK\r\nContent-Type: text/html",
                    page.format(t="One").encode()),
        warc_record(SITE + "book/two.html", "200 OK\r\nContent-Type: text/html; "
                    "charset=utf-8", page.format(t="Two").encode(),
                    chunked=True, gzipped=True),
        warc_record(SITE + "book/three.html", "200 OK\r\nContent-Type: text/html",
                    page.format(t="Three").encode(), gzipped=True),
        warc_record(SITE + "book/old.html", "301 Moved\r\nLocation: /book/three.html",
                    b""),
        warc_record(SITE + "book/pic.png", "200 OK\r\nContent-Type: image/png",
                    PNG, chunked=True),
    ]
    warc = os.path.join(work, "crawl.warc.gz")
    with open(warc, "wb") as fh:
        fh.write(b"".join(records))
    wacz = os.path.join(work, "crawl.wacz")
    import zipfile
    with zipfile.ZipFile(wacz, "w") as z:
        z.write(warc, "archive/data.warc.gz")
        z.writestr("datapackage.json", "{}")
    out, out2 = os.path.join(work, "book"), os.path.join(work, "book2")
    out3 = os.path.join(work, "book3")
    result = unpack([warc], out)
    unpack([wacz], out2)
    odd = os.path.join(work, "crawl_warc.gz")          # as an upload renames it
    shutil.copy(warc, odd)
    renamed = unpack([odd], out3)
    two = read(out, "two.html") if os.path.exists(os.path.join(out, "two.html")) \
        else ""
    return [
        ("a WARC's HTML responses are the pages, gzipped per record, "
         "chunked, and content-encoded",
         lambda: result.returncode == 0 and sorted(
             n for n in os.listdir(out) if n.endswith(".html"))
         == ["one.html", "three.html", "two.html"] and "<h1>Two</h1>" in two),
        ("a link to a URL that redirected goes where the redirect went",
         lambda: 'href="three.html#here"' in two),
        ("a resource is its response's body",
         lambda: open(os.path.join(out, "assets", "pic.png"), "rb").read()
         == PNG),
        ("the menu gives the order, and \"Home\" is a title like any other",
         lambda: "page: one" in read(out, "project.yaml")
         and read(out, "project.yaml").index("page: two")
         < read(out, "project.yaml").index("page: three")
         and 'title: "Home"' in read(out, "project.yaml")),
        ("MathJax's delimiters become math the run reads, display and "
         "inline, and code keeps its backslashes",
         lambda: '<script type="math/tex">k^2</script>' in two
         and '<script type="math/tex; mode=display">E = mc^2</script>' in two
         and '\\(not math\\)' in two
         and any(r["Check"] == "mathjax-tex" for r in report(out))),
        ("a WARC named anything is still a WARC",
         lambda: renamed.returncode == 0 and os.path.exists(
             os.path.join(out3, "one.html"))),
        ("a WACZ holding the same WARC gives the same pages",
         lambda: all(read(out, n) == read(out2, n)
                     for n in ("one.html", "two.html", "three.html"))),
    ]


def warc_revisit(url, http, refers=None):
    import gzip as gz
    block = ("HTTP/1.1 " + http + "\r\n\r\n").encode()
    record = (f"WARC/1.1\r\nWARC-Type: revisit\r\nWARC-Target-URI: {url}\r\n"
              + (f"WARC-Refers-To-Target-URI: {refers}\r\n" if refers else "")
              + f"Content-Length: {len(block)}\r\n\r\n").encode() + block \
        + b"\r\n\r\n"
    return gz.compress(record)


LESSON = "https://oer.example.org/courseware/lesson/7/student/70"


def case_browser_archive(work):
    """A browser's archive of a lesson whose sections are fetched as JSON,
    in the shape ArchiveWeb.page recorded OER Commons."""
    import json
    import zipfile
    os.makedirs(work)
    menu = ('<ul class="task-slide-dropdown-ct">'
            + "".join(f'<li><a href="?section={n}">{t}</a></li>' for n, t in
                      ((0, "Title"), (1, "1 - Speaking"), (2, "2 - Writing"),
                       (3, "View all as one page"))) + "</ul>")
    controls = f'<div class="lesson-task-slides-controls">{menu}</div>'
    base = f"""<html><head><title>Talk | Example Commons</title>
<meta property="og:title" content="Talk">
<meta property="og:site_name" content="Example Commons"></head><body>
<nav>site menu</nav><div class="js-courseware-ct">{controls}
<div class="text-center"><img src="/cover.png" alt="Talk"></div>{controls}
</div></body></html>"""

    def section(n, title, extra=""):
        return json.dumps({"status": "success", "template": (
            f'<div class="js-courseware-ct">{controls}<article '
            f'class="lesson-task-slide"><h2 class="lesson-task-title">{title}'
            f'</h2><p>Section {n}. {extra}</p></article>{controls}</div>')})
    records = [
        warc_record("https://accounts.example.com/relay", "200 OK\r\n"
                    "Content-Type: text/html", b"<html><body>relay</body></html>"),
        warc_record(LESSON, "200 OK\r\nContent-Type: text/html", base.encode()),
        warc_record(LESSON + "?section=1", "200 OK\r\nContent-Type: "
                    "application/json", section(1, "Speaking",
                    '<img src="https://oer.example.org/editor/images/9" alt="A '
                    'podium">').encode()),
        warc_record(LESSON + "?section=2", "200 OK\r\nContent-Type: "
                    "application/json", section(2, "Writing",
                    '<iframe src="https://video.example.com/embed/abc" '
                    'title="A talk"></iframe><h3>&nbsp;</h3>').encode()),
        warc_record("https://video.example.com/embed/abc", "200 OK\r\n"
                    "Content-Type: text/html", b"<html><body>player</body></html>"),
        warc_record("https://oer.example.org/oembed/client?url=x", "200 OK\r\n"
                    "Content-Type: application/json",
                    json.dumps({"html": "<iframe src='x'></iframe>"}).encode()),
        warc_revisit("https://oer.example.org/editor/images/9",
                     "302 Found\r\nLocation: https://img.example.org/podium.png"),
        warc_record("https://img.example.org/podium.png", "200 OK\r\n"
                    "Content-Type: image/png", PNG),
    ]
    wacz = os.path.join(work, "session.wacz")
    with zipfile.ZipFile(wacz, "w") as z:
        z.writestr("archive/data.warc.gz", b"".join(records))
        z.writestr("pages/pages.jsonl", '{"format": "json-pages-1.0"}\n'
                   + json.dumps({"url": LESSON, "title": "Talk"}) + "\n")
        z.writestr("datapackage.json", "{}")
    out = os.path.join(work, "book")
    result = unpack([wacz], out)
    import yaml
    project = yaml.safe_load(read(out, "project.yaml"))["project"] \
        if os.path.exists(os.path.join(out, "project.yaml")) else {}
    one = read(out, "section-1.html") if os.path.exists(
        os.path.join(out, "section-1.html")) else ""
    rows = report(out) if os.path.exists(
        os.path.join(out, "unpack-report.csv")) else []
    return [
        ("the book is the site the archive says was recorded, not the first "
         "HTML fetched",
         lambda: result.returncode == 0 and sorted(
             n for n in os.listdir(out) if n.endswith(".html"))
         == ["section-0.html", "section-1.html", "section-2.html"]),
        ("sections fetched as JSON are pages; an oEmbed answer isn't",
         lambda: "Section 1." in one and not any(
             "oembed" in n for n in os.listdir(out))),
        ("the lesson's own menu gives the order, and names the lesson page "
         "section-0",
         lambda: [c["page"] for c in project["contents"]]
         == ["section-0", "section-1", "section-2"]),
        ("OER Commons is recognized: the chapter is the content, its heading "
         "the page's h1, the controls gone",
         lambda: any(r["Check"] == "profile" and r["Detail"].startswith(
             "oercommons") for r in rows)
         and "<h1" in one and "task-slide-dropdown" not in one),
        ("an image reached through a redirect stored as a revisit is held",
         lambda: 'src="assets/podium.png"' in one),
        ("a frame keeps pointing at what it shows, though the archive holds "
         "a copy",
         lambda: 'src="https://video.example.com/embed/abc"'
         in read(out, "section-2.html") and not any(
             "video.example.com" in r["Detail"] for r in rows)),
        ("the book's title is og:title, and the site's name leaves a page's",
         lambda: project.get("title") == "Talk"
         and "<title>Talk</title>" in read(out, "section-0.html")),
    ]


def case_edtech_books(work):
    """An EdTech Books capture: a shell page and JSON records, from which
    the book is made."""
    import json
    import zipfile
    os.makedirs(work)
    host = "https://open.example.edu"
    png = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                        "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")

    def record(kind, n, entity):
        entity = dict(entity, settings=entity.get("settings", {}))
        return warc_record(f"{host}/{kind}/{n}/view", "200 OK\r\nContent-Type: application/json",
                           json.dumps({"status": "success", "entity": entity}).encode())
    links = [
        {"id": 1, "title": "Intro ", "short_name": "intro", "chapter_level": 0, "children": []},
        {"id": 2, "title": "Section", "short_name": "section", "chapter_level": 0, "children": [3]},
        {"id": 3, "title": "Inside", "short_name": "inside", "chapter_level": 1, "children": []},
        {"id": 4, "title": "Deeper", "short_name": "deeper", "chapter_level": 3, "children": []},
    ]
    intro = ('<div class="story-header"><h6>Story</h6><h3>A story</h3></div>'
             '<p>Intro text.</p><div data-template="youtube" contenteditable="false" '
             'placeholder="YouTube Video" data-youtube-id="abc123"></div>'
             '<img src="/images/content_images/bk/Exec summary 1.png" alt="A chart">'
             '<h6></h6><h4>Sub</h4><p>More.</p>')
    records = [
        warc_record(f"{host}/bk", "200 OK\r\nContent-Type: text/html",
                    b"<html><head><title>EdTech Books</title></head><body>"
                    b"<a href='#main'>Skip to main content</a></body></html>"),
        warc_record(f"{host}/ui/default/chapter.html", "200 OK\r\nContent-Type: text/html",
                    b"<div>{{chapter.title}}</div>"),
        warc_record(f"{host}/book/bk/view", "200 OK\r\nContent-Type: application/json",
                    json.dumps({"status": "success", "entity": {
                        "settings": {}, "short_name": "bk", "title": "A Test Book",
                        "subtitle": "For testing", "authorships": [{"name": "Ann Author"}],
                        "abstract": "An abstract.", "chapter_links": links}}).encode()),
        record("chapter", 1, {"id": 1, "title": "Intro", "settings": {"text": intro}}),
        record("chapter", 2, {"id": 2, "title": "Section", "settings": {"text": " "}}),
        record("chapter", 3, {"id": 3, "title": "Inside", "settings": {"text": "<p>Inside text.</p>"}}),
        record("chapter", 4, {"id": 4, "title": "Deeper", "settings": {"text": "<p>Deeper text.</p>"}}),
        warc_record(f"{host}/images/content_images/bk/Exec%20summary%201.png",
                    "200 OK\r\nContent-Type: image/png", png),
    ]
    wacz = os.path.join(work, "session.wacz")
    with zipfile.ZipFile(wacz, "w") as z:
        z.writestr("pages/pages.jsonl", '{"format": "json-pages-1.0"}\n'
                   + json.dumps({"url": f"{host}/bk"}) + "\n")
        z.writestr("archive/data.warc.gz", b"".join(records))
    out = os.path.join(work, "out")
    unpack([wacz], out)
    project = read(out, "project.yaml") if os.path.exists(os.path.join(out, "project.yaml")) else ""
    page = read(out, "intro.html") if os.path.exists(os.path.join(out, "intro.html")) else ""
    pages = sorted(f for f in os.listdir(out) if f.endswith(".html")) if os.path.isdir(out) else []
    notes = report(out) if os.path.exists(os.path.join(out, "unpack-report.csv")) else ""
    return [
        ("the book is made from its records: a cover and a page per chapter, "
         "and neither the shell nor a template", lambda: pages == [
            "deeper.html", "index.html", "inside.html", "intro.html", "section.html"]),
        ("the title and author come from the book record, the cover first",
         lambda: 'title: "A Test Book"' in project and '"Ann Author"' in project
         and project.index("page: index") < project.index("page: intro")),
        ("chapters nest by their levels, deeper than children says",
         lambda: project.index("page: section") < project.index("page: inside")
         < project.index("page: deeper") and "      items:" in project),
        ("a video placeholder is the player's frame",
         lambda: 'src="https://www.youtube.com/embed/abc123"' in page),
        ("an h6 is a label, an empty one goes, and headings start at h2",
         lambda: '<p class="label">Story</p>' in page and "<h6" not in page
         and "<h2>A story</h2>" in page and "<h3>Sub</h3>" in page),
        ("an image named with spaces is found under its encoded address, and "
         "saved under its own name", lambda: "resource-not-held" not in notes
         and any("Exec" in f and "20" not in f for f in os.listdir(os.path.join(out, "assets")))),
        ("a section with no text lists what's in it",
         lambda: 'href="inside.html"' in read(out, "section.html")),
    ]


CASES = [
    ("a browser's saves", case_browser_save),
    ("an MHTML set", case_mhtml),
    ("a WARC and a WACZ", case_warc),
    ("a browser's archive of a lesson", case_browser_archive),
    ("the parsers", case_parsers),
    ("EdTech Books", case_edtech_books),
]


def main():
    import htmlparse
    if htmlparse.BACKEND is None:
        print("skip: no HTML parser (install html5lib, or lxml)")
        return 0
    work = tempfile.mkdtemp(prefix="site-tests-")
    failed = 0
    try:
        for label, case in CASES:
            print(f"\n{label}")
            try:
                checks = case(os.path.join(work, label.replace(" ", "-")
                                           .replace("'", "")))
            except Exception as exc:
                print(f"  ERROR {label}: {exc!r}")
                failed += 1
                continue
            for name, predicate in checks:
                try:
                    ok = predicate()
                except Exception as exc:
                    ok, name = False, f"{name}  ({exc!r})"
                print(("  ok    " if ok else "  FAIL  ") + name)
                failed += not ok
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"\n{failed} check(s) failed" if failed
          else "\nall site checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
