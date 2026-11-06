"""
revealtarget.py -- a deck written in Markdown made a reveal.js presentation.

Pandoc's reveal.js writer writes it from the deck's intermediate, after
deck-revealjs.lua and target-blocks.lua, with Pandoc's own template
(build); here is what's put right in what it wrote (finish), read in
Writers/HTML.hs and data/templates/default.revealjs at 3.12.1, and the
copy of reveal.js it loads (copy_revealjs, from the repository's own,
vendor/reveal.js, or REVEALJS_DIR's):

- reveal.js is loaded from a copy beside the presentations, reveal.js 6,
  for which Pandoc 3.12's template is written, where the template loads
  it from unpkg.com with ^6 in each address, which the Nu checker calls
  an illegal character, and which an LMS or a reader offline may not
  reach. The copy is the repository's, 6.0.2, the release oer-reveal.js
  was written against (vendor/reveal.js/README.md says why and how to
  update it), or that of the folder REVEALJS_DIR names, for another
  release of reveal.js 6, which the run notes. reveal.js is MIT-licensed,
  and the font its white theme embeds is under the SIL Open Font
  License; both licenses go with the copy;
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
- the script that starts reveal.js holds settings and nothing else
  (start_settings): a deck's YAML gives the template's settings their
  values as text, so a value with a quote in it would end its string and
  go on as code, and a presentation whose start holds more isn't written;
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
import pandocversion

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
# The repository's copy of reveal.js, which the presentations load unless
# REVEALJS_DIR names another (vendor/reveal.js/README.md).
VENDORED = os.path.join(os.path.dirname(HERE), "vendor", "reveal.js")
STYLESHEET = os.path.join(BIN, "oer-reveal.css")
SCRIPT = os.path.join(BIN, "oer-reveal.js")

# The reveal.js major version Pandoc 3.12's template loads (its plugins
# are dist/plugin/notes.js and the rest, where 5's were plugin/notes/).
REVEALJS_MAJOR = 6
# The theme the presentations take, whatever theme a deck's YAML names
# (a beamer theme, as often as not): reveal.js's white, its text #222 on
# white, over which oer-reveal.css sets the rest.
THEME = "white"
# What the template loads of reveal.js, its license, and the license of
# the font the theme embeds, copied beside the presentations under the
# name the template's revealjs-url gives.
REVEALJS_FILES = ("dist/reveal.js", "dist/reveal.css", "dist/reset.css",
                  f"dist/theme/{THEME}.css", "dist/plugin/notes.js",
                  "dist/plugin/search.js", "dist/plugin/zoom.js", "LICENSE",
                  "css/theme/fonts/source-sans-pro/LICENSE")
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

# The template's start of reveal.js, read as settings and nothing else:
# Reveal.initialize({...}); and comments, each setting a name and a value,
# true, false, null, a number, or a string with nothing in it that could
# end it or the script (a quote, a backslash, a line's end, < or >, a
# backtick, a control character), and the plugins a list of the ones the
# template loads. A deck's YAML gives the template's settings their values
# as text, so a value with a quote in it ends its string and goes on as
# code (a transition of none\', controls: (window.pwned = 1), x: \'); what
# isn't a setting is refused (start_settings).
START_TOKEN = re.compile(r"""
    (?P<space>[ \t\r\n]+)
  | (?P<comment>//[^\r\n<>  ]*)
  | (?P<open>Reveal\.initialize\(\{)
  | (?P<close>\}\);)
  | (?P<key>[A-Za-z][A-Za-z0-9]*)[ \t]*:
  | (?P<value>true|false|null
      | -?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?
      | '[^'\\\r\n<>`\x00-\x1f\x7f  ]*'
      | "[^"\\\r\n<>`\x00-\x1f\x7f  ]*")
  | (?P<plugin>RevealNotes|RevealSearch|RevealZoom)
  | (?P<comma>,)
  | (?P<lbracket>\[)
  | (?P<rbracket>\])
""", re.X)
# A script element, its attributes and its text, as the HTML parser ends
# one: at the first </script. (A text with < in it isn't settings, so
# the parser's other ways of ending one don't arise.)
SCRIPT_ELEMENT = re.compile(r"<script(\s[^>]*)?>(.*?)</script[\s/>]", re.S | re.I)
SCRIPT_SOURCE = re.compile(r"\ssrc\s*=", re.I)

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


def revealjs_folder(environ=None):
    """The folder of the reveal.js the presentations load: REVEALJS_DIR's,
    made absolute, when it's set, else the repository's (VENDORED)."""
    given = (environ if environ is not None else os.environ).get("REVEALJS_DIR", "").strip()
    return os.path.abspath(os.path.expanduser(given)) if given else VENDORED


def revealjs_problem(folder):
    """Why folder, the repository's copy of reveal.js or REVEALJS_DIR's,
    isn't one the presentations can load, or None."""
    missing = [name for name in REVEALJS_FILES + ("package.json",)
               if not os.path.isfile(os.path.join(folder, name))]
    if os.path.realpath(folder) == os.path.realpath(VENDORED):
        version = revealjs_version(folder)
        if not missing and version.startswith(f"{REVEALJS_MAJOR}."):
            return None
        return ("The repository's copy of reveal.js, vendor/reveal.js, is "
                + ("missing " + ", ".join(missing[:3]) + (", ..." if len(missing) > 3 else "")
                   if missing else f"reveal.js {version or 'of no version'}")
                + ": a checkout of TextbookImprover has reveal.js "
                f"{REVEALJS_MAJOR} there, and REVEALJS_DIR can name the folder of another copy "
                "(see docs/installation.md).")
    if missing:
        return (f"REVEALJS_DIR is {folder}, which isn't a copy of reveal.js: it has no "
                + ", ".join(missing[:3]) + (", ..." if len(missing) > 3 else "")
                + " (the folder reveal.js's package unpacks to, or npm's "
                "node_modules/reveal.js, holds dist and package.json; see docs/installation.md). "
                "Unset, the repository's own copy is used.")
    version = revealjs_version(folder)
    if not version or not version.startswith(f"{REVEALJS_MAJOR}."):
        return (f"REVEALJS_DIR's reveal.js is {version or 'of no version package.json gives'}, and "
                f"the presentations are written for reveal.js {REVEALJS_MAJOR}, whose plugins "
                f"Pandoc's template loads: unset, the repository's own copy of reveal.js "
                f"{revealjs_version(VENDORED)} is used (see docs/installation.md).")
    return None


def revealjs_note(folder):
    """A note for a copy of reveal.js other than the release the
    repository carries, which oer-reveal.js was written against and the
    suites test, or None."""
    version, vendored = revealjs_version(folder), revealjs_version(VENDORED)
    if os.path.realpath(folder) == os.path.realpath(VENDORED) or version == vendored:
        return None
    return (f"NOTE: the presentations load REVEALJS_DIR's reveal.js {version}, where the "
            f"script that makes them readable with a screen reader (oer-reveal.js) was written "
            f"against {vendored}, the repository's own copy, and is tested with it; unset "
            "REVEALJS_DIR to use that one.")


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


def start_settings(text):
    """(settings, problem) for the text of the script that starts
    reveal.js: {name: value} and None when it's settings and nothing else
    (START_TOKEN), the plugins a list of their names; else None and what
    isn't a setting, named by the setting it follows, "the setting
    transition holds '<p>none', controls: (window.pwned = 1), x: …"."""
    tokens, at = [], 0
    while at < len(text):
        found = START_TOKEN.match(text, at)
        if not found:
            tokens.append(("bad", "", at, at))
            break
        if found.lastgroup not in ("space", "comment"):
            tokens.append((found.lastgroup, found.group(found.lastgroup), found.start(),
                           found.end()))
        at = found.end()
    tokens.append(("end", "", len(text), len(text)))

    def held(start):
        # To the end of its line, as the template writes a setting a line.
        line = text[start:].lstrip().split("\n", 1)[0]
        words = " ".join(line.split()).rstrip(",")
        return words[:100] + ("…" if len(words) > 100 else "") if words else "nothing"

    settings, place, name, start = {}, 0, None, 0

    def kind():
        return tokens[place][0]

    def wrong(lead=None):
        if lead:
            return None, f"{lead} it holds {held(tokens[place][2])}"
        if name is None:
            return None, (f"it holds {held(tokens[place][2])} where Pandoc's template "
                          "calls Reveal.initialize with its settings")
        return None, f"the setting {name} holds {held(start)}"

    if kind() != "open":
        return wrong()
    place += 1
    while kind() != "close":
        if kind() != "key":
            return wrong()
        name, start = tokens[place][1], tokens[place][3]
        place += 1
        if name == "plugins" and kind() == "lbracket":
            place += 1
            plugins = []
            while kind() == "plugin":
                plugins.append(tokens[place][1])
                place += 1
                if kind() != "comma":
                    break
                place += 1
            if kind() != "rbracket":
                return wrong()
            settings[name] = plugins
        elif kind() == "value":
            literal = tokens[place][1]
            settings[name] = (True if literal == "true" else False if literal == "false"
                              else None if literal == "null" else literal[1:-1]
                              if literal[0] in "'\"" else float(literal))
        else:
            return wrong()
        place += 1
        if kind() == "comma":
            place += 1
        elif kind() != "close":
            return wrong()
    place += 1
    if kind() != "end":
        return wrong("after its settings,")
    return settings, None


def start_problem(html):
    """Why a presentation's start of reveal.js isn't settings and nothing
    else (start_settings), or None: what the setting holds, or that the
    presentation has no start, or two."""
    starts = [match.group(2) for match in SCRIPT_ELEMENT.finditer(html)
              if not SCRIPT_SOURCE.search(match.group(1) or "")
              and "Reveal.initialize" in match.group(2)]
    if len(starts) != 1:
        return (f"it has {'no' if not starts else len(starts)} script"
                f"{'' if len(starts) == 1 else 's'} starting reveal.js, where Pandoc's "
                "template writes one")
    return start_settings(starts[0])[1]


def build(intermediate, base, out, *, filters, level, language, shape, notes="collapsed",
          env=None):
    """One deck's presentation, out, from its filtered intermediate: Pandoc's
    reveal.js writer with filters, at the deck's slide level, its slides
    shape, then finish(). notes is slides.notes. Returns a dict: ok; log,
    Pandoc's errors; refused, why a presentation Pandoc wrote was refused
    and removed, its start of reveal.js holding more than settings
    (start_problem), which would run as code; warnings, Pandoc's others;
    slides, how many. filters
    ends with header-includes.lua, which adds the stylesheet to the
    deck's header-includes and the script after its include-after, where
    Pandoc's --include-in-header and --include-after-body would take
    their place."""
    result = {"ok": False, "log": "", "refused": "", "warnings": [], "slides": 0,
              "html": out}
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
                   *pandocversion.mathml(), "--slide-level", str(level),
                   "--reference-location=section",
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
                                       INCLUDE_AFTER_FILE=script,
                                       DECK_NOTES=str(notes), DECK_LEVELS_ONLY="1"))
        if done.returncode:
            result["log"] = done.stderr
            return result
        result["warnings"] = sorted({" ".join(line.split())[:160]
                                     for line in done.stderr.splitlines() if line.strip()})
        with open(out, encoding="utf-8") as fh:
            html = finish(fh.read())
        refused = start_problem(html)
        if refused:
            os.remove(out)
            result["refused"] = refused
            return result
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(html)
        result["slides"] = len(re.findall(r'<section\b[^>]*\bclass="[^"]*\bslide\b', html)) \
            + html.count('<section id="title-slide"')
        result["ok"] = True
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return result
