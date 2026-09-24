#!/usr/bin/env python3
"""Formulas as MathJax drew them, read back: lib/mathjax.py.

The renderings in tests/fixtures/mathjax/renderings.json are what MathJax
2.7, 3.2, and 4.1 themselves produced for three formulas (a sub- and
superscript and a fraction; a square root and a two-case table; a sum with
limits and a cube root), in CommonHTML and SVG, with the MathML they hide
for screen readers and without it. Each is read back and handed to
Pandoc, and the TeX Pandoc gets must match what it gets from MathJax's own
MathML for the formula (or the formula's source, where the TeX itself was
recovered). No real page of these kinds has been read yet, so the path is
rated as needing more testing in docs/formats.md.

Needs html5lib or lxml, and Pandoc.
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))


def pandoc_tex(html):
    run = subprocess.run(["pandoc", "-f", "html", "-t", "json"],
                         input="<html><body>" + html + "</body></html>",
                         capture_output=True, text=True)
    found = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("t") == "Math":
                found.append(node["c"][1])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(json.loads(run.stdout)["blocks"])
    return found


def same(a, b):
    def norm(tex):
        tex = re.sub(r"\\(left|right|operatorname|limits)", "", tex)
        return re.sub(r"[\s{}.]", "", tex)
    return [norm(x) for x in a] == [norm(x) for x in b]


def variants(samples):
    """{name: (expected route, [three renderings])}."""
    out = {}
    for key, htmls in samples.items():
        if not key.startswith(("mj3", "mj4")):
            continue
        version, jax, hidden = key.split("-")
        if hidden == "mml":
            route = "hidden-mathml"
        elif version == "mj4":
            route = "tex"                  # MathJax 4 writes data-latex
        else:
            route = "rebuilt"
        out[key] = (route, htmls)
        if version == "mj4" and hidden == "bare":
            out[key + "-nolatex"] = ("rebuilt", [
                re.sub(r'\sdata-latex="[^"]*"', "", h) for h in htmls])
    chtml, svg, mml = samples["mj2-chtml"], samples["mj2-svg"], samples["mj2-mml"]
    out["mj2-chtml-bare"] = ("rebuilt", chtml)
    out["mj2-chtml-mml"] = ("hidden-mathml", [
        '<span class="mjx-chtml MathJax_CHTML"><span class="mjx-math" '
        'aria-hidden="true">%s</span><span class="MJX_Assistive_MathML">%s'
        '</span></span>' % (re.sub(r"^<span class=.mjx-chtml[^>]*>|</span>$",
                                   "", h), m) for h, m in zip(chtml, mml)])
    out["mj2-svg-title"] = ("tex", ['<span class="MathJax_SVG">%s</span>' % h
                                    for h in svg])
    out["mj2-svg-bare"] = ("lost", [
        '<span class="MathJax_SVG">%s</span>'
        % re.sub(r"<title[^>]*>.*?</title>", "", h, flags=re.S) for h in svg])
    return out


LABELS = {"mj2": "MathJax 2", "mj3": "MathJax 3", "mj4": "MathJax 4",
          "chtml": "CommonHTML", "svg": "SVG", "mml": "with its hidden MathML",
          "bare": "without hidden MathML", "nolatex": "without data-latex",
          "title": "with a TeX title"}


def rendering_checks(mathjax, samples):
    refs = [pandoc_tex(m) for m in samples["mj2-mml"]]
    sources = samples["_sources"]
    for name, (route, htmls) in sorted(variants(samples).items()):
        label = " ".join(LABELS.get(part, part) for part in name.split("-"))
        problems = []
        for i, html in enumerate(htmls):
            page, counts = mathjax.rebuilt(
                "<!DOCTYPE html><html><body><p>%s</p></body></html>" % html)
            taken = [k for k, n in counts.items() if n]
            if taken != [route]:
                problems.append("formula %d went %s" % (i + 1, taken))
                continue
            if route == "lost":
                if "[formula]" not in page:
                    problems.append("formula %d has no marker" % (i + 1))
                continue
            body = re.sub(r"^.*?<body>|</body>.*$", "", page, flags=re.S)
            got = pandoc_tex(body)
            if not same(got, [sources[i]] if route == "tex" else refs[i]):
                problems.append("formula %d read as %s" % (i + 1, got))
        yield ("%s: %s" % (label, route.replace("-", " ")), not problems,
               "; ".join(problems))


def pipeline_checks(samples):
    """A saved page with one formula that can be read back and one that
    can't, converted: MathML in the page, and the lost one reported."""
    work = tempfile.mkdtemp()
    try:
        svg = re.sub(r"<title[^>]*>.*?</title>", "", samples["mj2-svg"][0],
                     flags=re.S)
        with open(os.path.join(work, "saved.html"), "w", encoding="utf-8") as fh:
            fh.write('<!DOCTYPE html><html lang="en"><head><title>Saved</title>'
                     '</head><body><h1>Saved</h1><p>First %s, then '
                     '<span class="MathJax_SVG">%s</span>.</p></body></html>'
                     % (samples["mj3-chtml-bare"][0], svg))
        with open(os.path.join(work, "conversion.yaml"), "w") as fh:
            fh.write("targets:\n  html:\n    format: html\n")
        run = subprocess.run([sys.executable, os.path.join(ROOT, "bin",
                                                           "convert.py"),
                              "--quiet"], cwd=work, capture_output=True,
                             text=True, stdin=subprocess.DEVNULL)
        page = ""
        path = os.path.join(work, "html", "saved.html")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                page = fh.read()
        report = ""
        path = os.path.join(work, "output-check.csv")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                report = fh.read()
        yield ("converted, a formula that can be read back is MathML",
               page.count("<math") == 1 and "<msubsup>" in page,
               run.stderr[-300:])
        yield ("and one that can't is marked, said on the way, and reported",
               "[formula]" in page and "lost, marked [formula]" in run.stderr
               and "formula-lost" in report, run.stderr[-300:])
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    if not (importlib.util.find_spec("html5lib") or importlib.util.find_spec("lxml")):
        print("skip  no HTML parser (install html5lib, or lxml)")
        return 0
    if not shutil.which("pandoc"):
        print("skip  Pandoc is not on the path")
        return 0
    import mathjax
    with open(os.path.join(HERE, "fixtures", "mathjax", "renderings.json"),
              encoding="utf-8") as fh:
        samples = json.load(fh)
    failures = total = 0
    for name, ok, detail in list(rendering_checks(mathjax, samples)) + list(
            pipeline_checks(samples)):
        total += 1
        if ok:
            print("  ok    %s" % name)
        else:
            failures += 1
            print("  FAIL  %s" % name)
            if detail:
                print("          %s" % detail)
    if failures:
        print("%d of %d MathJax checks failed." % (failures, total))
        return 1
    print("all %d MathJax checks passed" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
