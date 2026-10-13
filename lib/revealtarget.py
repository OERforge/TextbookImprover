"""
revealtarget.py -- a deck written in Markdown made a reveal.js presentation.

Pandoc's reveal.js writer writes it from the deck's intermediate, after
deck-revealjs.lua and target-blocks.lua, with Pandoc's own template
(build); here is what's put right in what it wrote (finish), read in
Writers/HTML.hs and data/templates/default.revealjs at 3.12.1, and the
copy of reveal.js it loads (copy_revealjs, from REVEALJS_DIR):

- reveal.js is loaded from a copy beside the presentations, reveal.js 6,
  for which Pandoc 3.12's template is written, where the template loads
  it from unpkg.com with ^6 in each address, which the Nu checker calls
  an illegal character, and which an LMS or a reader offline may not
  reach. reveal.js is MIT-licensed; its license goes with the copy;
- each image's address is src again, where the writer gives reveal.js's
  data-src, for it to load the image when its slide is near: without the
  script there's no picture, and the Nu checker reports each as missing
  its src. A picture the deck marks loading="lazy" is loaded with the
  page too, since a slide reveal.js hides is never near, and
  oer-reveal.js fits the slides once every picture is in;
- the viewport lets a reader zoom, where the template's says
  maximum-scale=1.0, user-scalable=no, which keeps a reader on a phone or
  a tablet from zooming, against WCAG 1.4.4;
- each heading is at the level the deck's page gives it (deck-html.lua,
  run with DECK_LEVELS_ONLY, giving each its level as an attribute):
  the deck's title the one H1, a section an H2, a slide in no section an
  H2 and one in a section an H3, a block one below its slide, where the
  writer gives each heading the deck's own level, a section's and the
  title slide's both H1, and a block's #### under a slide's ## a skipped
  level, which the output check reports; and a block with no title is no
  heading, as on the page;
- a section's slides follow it in one row with the rest, where the
  writer stacks them in a section of their own with no heading, which
  reveal.js shows as a column under the section's slide, its right
  arrow skipping past them, and in which the Nu checker finds a section
  without a heading;
- reveal.js's own scroll view, which a window 435 pixels wide or less
  turns on, is off: it scales each slide to the window's width, so its
  text shrinks with the window;
- oer-reveal.js, after the script that starts reveal.js, takes away the
  presentation's role="application", silences the live region that read
  each slide's text run together, gives a slide's title focus as the
  slide is shown and a link's place focus as it's followed, fits a slide
  too tall for its frame, and shows a slide as a page in a narrow
  window, and oer-reveal.css sets the look over reveal.js's white theme
  (see each).

What the writer is told: the deck's slide level; MathML for formulas, as
the deck's page has them; footnotes at the foot of each slide
(--reference-location=section), as in the deck's PDF, where the writer
would gather them on a slide at the end; the slides the deck's shape, 720
pixels high (16:9 is 1280 wide), as the deck's PDF and PowerPoint file
take it (slides.aspect_ratio); no bouncing arrow to teach the controls,
and the arrow back as plain as the arrow on, where reveal.js fades it to
three tenths, too faint for a control to be made out (WCAG 1.4.11); the
speaker notes shown under each slide to everyone with slides.notes
visible, kept for reveal.js's speaker view by default, and left out with
omitted; and the deck's language.

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
import shutil
import subprocess
import tempfile

import highlighting

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
STYLESHEET = os.path.join(BIN, "oer-reveal.css")
SCRIPT = os.path.join(BIN, "oer-reveal.js")

# The reveal.js major version Pandoc 3.12's template loads (its plugins
# are dist/plugin/notes.js and the rest, where 5's were plugin/notes/).
REVEALJS_MAJOR = 6
# The theme the presentations take, whatever theme a deck's YAML names
# (a beamer theme, as often as not): reveal.js's white, its text #222 on
# white, over which oer-reveal.css sets the rest.
THEME = "white"
# What the template loads of reveal.js, and its license, copied beside
# the presentations under the name the template's revealjs-url gives.
REVEALJS_FILES = ("dist/reveal.js", "dist/reveal.css", "dist/reset.css",
                  f"dist/theme/{THEME}.css", "dist/plugin/notes.js",
                  "dist/plugin/search.js", "dist/plugin/zoom.js", "LICENSE")
REVEALJS_URL = "reveal.js"
# A slide's height, in reveal.js's pixels; its width follows the deck's
# shape.
HEIGHT = 720
VIEWPORT = re.compile(r'(<meta name="viewport" content=")[^"]*(")')
# The template's start of reveal.js, which a setting is put first in.
INITIALIZE = "Reveal.initialize({"
# reveal.js's own scroll view, which a window 435 pixels wide or less
# turns on, and which scales each slide to the window's width, its text
# smaller as the window narrows: off, for oer-reveal.js's page view. The
# template sets it only with the scroll view asked for.
NO_SCROLL_VIEW = "\n        scrollActivationWidth: null,"

# An address the writer gives reveal.js to load when the slide is near.
LAZY = re.compile(r"(<(?:img|video|audio|source|iframe)\b[^>]*?)\sdata-src=")
# A picture an author has the browser load only once it's near, which a
# slide reveal.js hides never is.
DEFERRED = re.compile(r'(<(?:img|iframe)\b[^>]*?)\sloading="lazy"')
# A slide's section element, opening or closing, as the writer writes one.
SECTION_TAG = re.compile(r"<section\b[^>]*>|</section>")
# A heading at the level the deck's page gives it (deck-html.lua's, as an
# attribute, which the writer puts on the heading and on its slide).
LEVELED = re.compile(r'<h([1-6])(\b[^>]*?)\sdata-oer-level="([1-6])"([^>]*)>(.*?)</h\1>', re.S)
LEVEL_ATTRIBUTE = re.compile(r'\sdata-oer-level="[1-6]"')


def revealjs_problem(folder):
    """Why folder, REVEALJS_DIR, isn't a copy of reveal.js the
    presentations can load, or None."""
    if not folder:
        return ("A revealjs target's presentations load reveal.js from a copy beside them, and "
                f"REVEALJS_DIR, the folder of one, isn't set: unpack reveal.js {REVEALJS_MAJOR}'s "
                f"package from the npm registry, or `npm install reveal.js@{REVEALJS_MAJOR}`, and "
                "set REVEALJS_DIR to its folder (see docs/installation.md, For a revealjs "
                "target).")
    missing = [name for name in REVEALJS_FILES if not os.path.isfile(os.path.join(folder, name))]
    if missing:
        return (f"REVEALJS_DIR is {folder}, which isn't a copy of reveal.js: it has no "
                + ", ".join(missing[:3]) + (", ..." if len(missing) > 3 else "")
                + " (the folder reveal.js's package unpacks to, or npm's "
                "node_modules/reveal.js, holds dist and package.json; see docs/installation.md).")
    version = revealjs_version(folder)
    if not version or not version.startswith(f"{REVEALJS_MAJOR}."):
        return (f"REVEALJS_DIR's reveal.js is {version or 'of no version package.json gives'}, and "
                f"the presentations are written for reveal.js {REVEALJS_MAJOR}, whose plugins "
                f"Pandoc's template loads: docs/installation.md says how to get reveal.js "
                f"{REVEALJS_MAJOR}.")
    return None


def revealjs_version(folder):
    try:
        with open(os.path.join(folder, "package.json"), encoding="utf-8") as fh:
            return str(json.load(fh).get("version") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def copy_revealjs(folder, output_dir):
    """What the presentations load of reveal.js, from folder, beside them in
    output_dir, under the name the template's address gives."""
    for name in REVEALJS_FILES:
        dest = os.path.join(output_dir, REVEALJS_URL, name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(os.path.join(folder, name), dest)


def frame(shape):
    """(width, height) of a slide of shape ("16:9"), in reveal.js's pixels."""
    across, down = (int(n) for n in shape.split(":"))
    return round(HEIGHT * across / down), HEIGHT


def flatten(html):
    """The writer's page with each section of the deck's slides in one row
    with the rest: the writer stacks a section's slides in a section of
    their own, with no attributes and no heading (its first slide has the
    section's title), which reveal.js shows as a column under the
    section, its right arrow skipping past them, and in which the Nu
    checker finds a section without a heading. Its tags go."""
    stack, drop = [], set()
    tags = list(SECTION_TAG.finditer(html))
    for n, tag in enumerate(tags):
        if tag.group(0) == "</section>":
            opening = stack.pop() if stack else None
            if opening is not None and opening in drop:
                drop.add(n)
        else:
            if tag.group(0) == "<section>" and n + 1 < len(tags) \
                    and tags[n + 1].group(0).startswith("<section"):
                drop.add(n)
            stack.append(n)
    out, last = [], 0
    for n, tag in enumerate(tags):
        if n in drop:
            out.append(html[last:tag.start()])
            last = tag.end()
    out.append(html[last:])
    return "".join(out)


def finish(html):
    """The writer's page put right: the viewport, each address src and
    loaded with the page, reveal.js's own scroll view off, and each
    heading at its level."""
    html = VIEWPORT.sub(r"\1width=device-width, initial-scale=1.0\2", html, count=1)
    html = html.replace(INITIALIZE, INITIALIZE + NO_SCROLL_VIEW, 1)
    html = LEVELED.sub(lambda m: f"<h{m[3]}{m[2]}{m[4]}>{m[5]}</h{m[3]}>", html)
    html = LEVEL_ATTRIBUTE.sub("", html)
    html = DEFERRED.sub(r"\1", html)
    return flatten(LAZY.sub(r"\1 src=", html))


def build(intermediate, base, out, *, filters, level, language, shape, notes="collapsed",
          env=None):
    """One deck's presentation, out, from its filtered intermediate: Pandoc's
    reveal.js writer with filters, at the deck's slide level, its slides
    shape, then finish(). notes is slides.notes. Returns a dict: ok; log,
    Pandoc's errors; warnings, its others; slides, how many."""
    result = {"ok": False, "log": "", "warnings": [], "slides": 0, "html": out}
    work = tempfile.mkdtemp(prefix="deck-reveal-")
    try:
        style, script = os.path.join(work, "style.html"), os.path.join(work, "script.html")
        with open(STYLESHEET, encoding="utf-8") as fh:
            css = fh.read()
        with open(style, "w", encoding="utf-8") as fh:
            fh.write("<style>\n" + css + "</style>\n")
        with open(SCRIPT, encoding="utf-8") as fh:
            js = fh.read()
        with open(script, "w", encoding="utf-8") as fh:
            fh.write("<script>\n" + js + "</script>\n")
        width, height = frame(shape)
        command = ["pandoc", "-f", "json", "-t", "revealjs", "-s", intermediate, "-o", out,
                   "--math-method=mathml", "--slide-level", str(level),
                   "--reference-location=section", "--include-after-body", script,
                   "-V", f"revealjs-url={REVEALJS_URL}", "-V", f"theme={THEME}",
                   "-V", f"width={width}", "-V", f"height={height}",
                   "-V", "controlsTutorial=false", "-V", "controlsBackArrows=visible",
                   "-M", f"lang={language}"] + highlighting.ARGS
        if notes == "visible":
            command += ["-V", "showNotes=true"]
        for path in filters:
            command += ["--lua-filter", path]
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        done = subprocess.run(command, cwd=base, capture_output=True, text=True,
                              env=dict(env or os.environ, HEADER_INCLUDES_FILE=style,
                                       DECK_NOTES=str(notes), DECK_LEVELS_ONLY="1"))
        if done.returncode:
            result["log"] = done.stderr
            return result
        result["warnings"] = sorted({" ".join(line.split())[:160]
                                     for line in done.stderr.splitlines() if line.strip()})
        with open(out, encoding="utf-8") as fh:
            html = finish(fh.read())
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(html)
        result["slides"] = len(re.findall(r'<section\b[^>]*\bclass="[^"]*\bslide\b', html)) \
            + html.count('<section id="title-slide"')
        result["ok"] = True
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return result
