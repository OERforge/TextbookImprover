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

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))
import outputcheck  # noqa: E402

GOOD = """<!DOCTYPE html><html lang="en"><head><title>A page</title></head>
<body><h1 id="top">Top</h1><h2>Second</h2>
<h2><img src="z.png" alt="A described figure"></h2>
<img src="x.png" alt="A thing"><img src="y.png" alt="" aria-hidden="true">
<div class="table-wrapper" tabindex="0" role="region" aria-label="Data">
<table><caption>Data</caption><tr><th scope="col">H</th></tr></table></div>
<div class="table-wrapper" tabindex="0" role="region" aria-label="Revenue">
<table><caption>Revenue</caption><tr><th scope="col">Revenue, <math><semantics><mi>p</mi><annotation encoding="application/x-tex">p</annotation></semantics></math></th>
<th scope="col"><img src="h.png" alt="Height"> <math><mi>h</mi></math></th><th scope="col"><math><mi>q</mi></math> per day</th></tr></table></div>
<table role="presentation"><tr><th><math><mi>z</mi></math></th><td>layout</td></tr></table>
<a href="#top">up</a><a href="other.html#there">over</a>
<a href="https://example.org/#x">out</a><p>A formula <math><mi>x</mi></math>, and one in MathJax's form <span class="math inline">\\(y\\)</span>.</p><p><a href="other.html" aria-label="Read more about cats">Read more</a> <a href="other.html" aria-label="Chart of sales, larger"><img src="c.png" alt="Chart of sales"></a> <a href="other.html">no label</a></p>
</body></html>"""

OTHER = """<!DOCTYPE html><html lang="en"><head><title>Other</title></head>
<body><h1 id="there">There</h1></body></html>"""

BAD = """<!DOCTYPE html><html><head><title></title></head>
<body><h1 id="a">A</h1><h3 id="a">Skipped</h3><h2 id="two words"></h2>
<img src="p.png"><img src="q.png" alt=""><img src="media/db-locked.png" alt="db locked">
<table><tr><td>1</td></tr></table>
<div class="table-wrapper" tabindex="0" role="region" aria-label="Demand">
<table><caption>Demand</caption><tr><th scope="col"><math display="inline"><semantics><msub><mi>q</mi><mi>d</mi></msub><annotation encoding="application/x-tex">q_d</annotation></semantics></math></th>
<th scope="col"> <math><mi>p</mi></math> </th><th scope="col">Price</th></tr>
<tr><th scope="row"><math><mi>r</mi></math><th scope="row">Rate</th></tr></table></div>
<a href="#nowhere">x</a><a href="gone.html">y</a><a href="other.html#no">z</a>
<a href="other.html" aria-label="DOI for Klein and Stern 2005">https://doi.org/10/b8xx35</a>
<p><span class="math inline">$x_{2}\\text{\\cdot}x_{n}$</span></p>
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

# The formula Pandoc couldn't convert, on a page whose script may render it.
SCRIPTED = OTHER.replace("</h1>", "</h1><p><span class=\"math inline\">$x_{2}\\text{\\cdot}$"
                         "</span></p><script src=\"mathjax.js\"></script>")


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
        with open(os.path.join(work, "scripted.html"), "w", encoding="utf-8") as fh:
            fh.write(SCRIPTED)
        scripted = outputcheck.check_html_files([os.path.join(work, "scripted.html")])
        cases = [
            ("a correct pair of pages produces no finding",
             lambda: checks(good) == []),
            ("every check fires on the page that breaks it",
             lambda: checks(bad) == sorted([
                 "no-lang", "no-title", "duplicate-id", "invalid-id",
                 "heading-skips-level",
                 "empty-heading", "image-without-alt",
                 "image-empty-alt-not-decorative",
                 "image-alt-is-file-name",
                 "link-label-without-text",
                 "table-without-headers-or-caption",
                 "table-not-in-scroll-region",
                 "link-to-missing-fragment", "link-to-missing-file",
                 "link-to-missing-fragment", "formula-shown-as-tex",
                 "table-header-is-formula", "table-header-is-formula",
                 "table-header-is-formula"])),
            ("a header cell holding only a formula is named by its table and TeX, "
             "and one with no TeX by its table",
             lambda: sorted(f.detail for f in bad if f.check == "table-header-is-formula")
             == ["table 2", "table 2", "table 2: q_d"]),
            # An EPUB's documents are read as XML: a nested table's header is
            # its own table's, not the table around it.
            ("in XHTML too, each header its own table's",
             lambda: outputcheck.read_xhtml("n.xhtml", NESTED).formula_headers
             == [(2, "y")]),
            ("a formula shown as TeX is named by its TeX",
             lambda: any(f.check == "formula-shown-as-tex"
                         and f.detail == "$x_{2}\\text{\\cdot}x_{n}$" for f in bad)),
            ("and isn't found on a page with a script, which may render it",
             lambda: checks(scripted) == []),
            ("a page titled with its file's name is found, one whose name is a word isn't, "
             "nor one named for its H1",
             lambda: sorted((os.path.basename(f.where), f.check) for f in titled) == [
                 ("ch_intro_to_data.html", "title-is-file-name"),
                 ("tTable.html", "title-is-file-name")]),
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
                    dst.writestr(info, data)
            damaged = outputcheck.check_epub(broken)
            cases += [
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


if __name__ == "__main__":
    sys.exit(main())
