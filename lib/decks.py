"""
decks.py -- decks written in Markdown, as a slides run reads and writes
them.

A deck in Markdown is Pandoc's slide Markdown: a slide begins at each
heading of the slide level, and the slides' notes are ::: notes divs.
Nothing in the file says it's a deck; the folder does (project.kind:
slides). It's read and filtered as a page is, and what it needs beyond a
page is here:

- Its slide level, recorded in the intermediate when it's read
  (deck-slide-level), which is also what marks the intermediate as a
  deck's. Pandoc works the level out for itself (the shallowest heading
  that something other than a heading follows: getSlideLevel in
  Slides.hs) unless it's told, and the deck can tell it with its own
  slide-level. The page's filter reads the recorded level, and the PDF's
  writer is given it, so a filter can't change which headings are
  slides.
- One-item lists where Pandoc wants a value: a title given as a YAML list
  is lost by Pandoc's PowerPoint, HTML, and beamer writers alike, and
  half of the decks this was built on give one.
- The slides with no title: one a horizontal rule begins, and what comes
  before the first slide, which Pandoc's slide writers make a slide of
  its own (prepSlides).
- Its PDF, through ltx-talk, a presentation class built for LaTeX's
  tagging: its headings renumbered so its sections are LaTeX's (renumber),
  Pandoc's beamer writer with a template of ours, its LaTeX put right
  where ltx-talk differs from beamer (talkify), LuaLaTeX run until the
  cross-references settle, and the tagged result repaired as a book's PDF
  is (pdfretag, pdfparagraphs).

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
from urllib.parse import unquote

import latexbuild

# The intermediate's record of the slide level, which also says the page
# is a deck. target-blocks.lua takes it out of everything a target
# writes; the PDF's writer is given it as --slide-level.
LEVEL_KEY = "deck-slide-level"

# Where Pandoc wants one value and a deck's YAML may give a list of one
# ("title:\n- Macroeconomics: 30. Money"): Pandoc's writers take the list
# for something else, and lose it (docTitle gives nothing for a list).
SINGLE_VALUES = ("title", "subtitle", "date", "lang", "title-meta", "subtitle-meta")

# A beamer deck's aspectratio, as beamer's class option codes it, as
# ltx-talk's aspect-ratio takes it (width:height, any numbers).
BEAMER_RATIOS = {"43": "4:3", "169": "16:9", "1610": "16:10", "149": "14:9",
                 "141": "1.41:1", "54": "5:4", "32": "3:2", "11": "1:1"}
# What a deck that says nothing about its shape gets: PowerPoint's
# default, and ltx-talk's.
DEFAULT_RATIO = "16:9"
# Variables beamer reads and Pandoc's other slide writers don't: a deck
# naming one was written for beamer, whose slides are 4:3 unless it says
# otherwise, so that's what its author saw. reveal.js reads theme too, so
# a theme that's one of reveal.js's own doesn't count.
BEAMER_ONLY = ("theme", "colortheme", "fonttheme", "innertheme", "outertheme",
               "themeoptions", "navigation", "beamerarticle", "titlegraphic",
               "section-titles")
REVEAL_THEMES = ("beige", "black", "black-contrast", "blood", "dracula", "league",
                 "moon", "night", "serif", "simple", "sky", "solarized", "white",
                 "white-contrast")
BEAMER_RATIO = "4:3"
RATIO = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\s*$")


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------

def slide_level(blocks, notes=True):
    """The slide level Pandoc works out for a deck: the shallowest heading
    level some heading followed directly by something other than a heading
    or a horizontal rule has (getSlideLevel, Slides.hs, 3.12.1), looking
    inside divs, the ::: notes divs too unless notes is off; 6 when
    there's none."""
    def go(least, blocks):
        i = 0
        while i < len(blocks):
            block = blocks[i]
            if block.get("t") == "Div" and not notes and is_notes(block):
                i += 1
                continue
            if block.get("t") == "Div":
                return min(go(least, block["c"][1]), go(least, blocks[i + 1:]))
            if (block.get("t") == "Header" and i + 1 < len(blocks)
                    and block["c"][0] < least
                    and blocks[i + 1].get("t") not in ("Header", "HorizontalRule")):
                least = block["c"][0]
                i += 2
                continue
            i += 1
        return least
    return go(6, blocks)


def meta_text(value):
    """A metadata value's text, whatever its form."""
    if not isinstance(value, dict):
        return ""
    kind, content = value.get("t"), value.get("c")
    if kind == "MetaString":
        return str(content)
    if kind == "MetaBool":
        return "true" if content else "false"
    if kind == "MetaList":
        return " ".join(meta_text(v) for v in content)
    return " ".join(inline_text(content).split())


def inline_text(node):
    if isinstance(node, dict):
        kind = node.get("t")
        if kind == "Str":
            return node["c"]
        if kind in ("Space", "SoftBreak", "LineBreak"):
            return " "
        if kind in ("Code", "Math"):
            return node["c"][1]
        if kind in ("RawInline", "Note"):
            return ""
        return inline_text(node.get("c", []))
    if isinstance(node, list):
        return "".join(inline_text(child) for child in node)
    return ""


def declared_level(meta):
    """The slide level the deck gives itself (slide-level in its YAML, as
    Pandoc's --slide-level takes it, 0 to 6), or None."""
    text = meta_text(meta.get("slide-level")).strip()
    return int(text) if re.fullmatch(r"[0-6]", text) else None


def single_values(meta):
    """Each of SINGLE_VALUES the YAML gives as a list of one item, made
    that item. Returns the keys changed."""
    changed = []
    for key in SINGLE_VALUES:
        value = meta.get(key)
        if isinstance(value, dict) and value.get("t") == "MetaList" \
                and len(value.get("c") or []) == 1:
            meta[key] = value["c"][0]
            changed.append(key)
    return changed


def mark(doc):
    """Record the deck's slide level in its intermediate, the one it
    declares or the one Pandoc would work out. Returns it."""
    meta = doc.setdefault("meta", {})
    level = declared_level(meta)
    if level is None:
        level = slide_level(doc.get("blocks", []))
    meta[LEVEL_KEY] = {"t": "MetaString", "c": str(level)}
    return level


def level_of(doc):
    """The slide level an intermediate records, or None for a page that
    isn't a deck's."""
    text = meta_text((doc.get("meta") or {}).get(LEVEL_KEY)).strip()
    return int(text) if text.isdigit() else None


def notes_level(meta, blocks, level):
    """The slide level a deck would have without the headings in its
    ::: notes divs, when they make it shallower and the deck doesn't give
    its own: Pandoc counts them, so a cue written # in the notes made a
    deck's sections slides. None otherwise."""
    if declared_level(meta) is not None:
        return None
    without = slide_level(blocks, notes=False)
    return without if without > level else None


def untitled_slides(blocks, level):
    """How many slides have no title: one a horizontal rule begins without
    a slide's heading after it, and what comes before the first heading of
    the slide level or above, which Pandoc's slide writers make a slide
    with no title (prepSlides, Slides.hs)."""
    count = 0
    if level <= 0:
        return 0
    first = next((b for b in blocks if b.get("t") != "Null"), None)
    if first is not None and not (first.get("t") == "Header" and first["c"][0] <= level) \
            and not (first.get("t") == "Div" and first["c"][1]
                     and first["c"][1][0].get("t") == "Header"
                     and first["c"][1][0]["c"][0] <= level):
        count += 1
    for i, block in enumerate(blocks):
        if block.get("t") == "HorizontalRule":
            after = blocks[i + 1] if i + 1 < len(blocks) else None
            if not (after and after.get("t") == "Header" and after["c"][0] == level):
                count += 1
    return count


def language_key(meta):
    """Whether the deck names its language language:, which Pandoc doesn't
    read (its name is lang)."""
    return "language" in meta and "lang" not in meta


# --------------------------------------------------------------------------
# the PDF
# --------------------------------------------------------------------------

def aspect_ratio(meta, setting):
    """The PDF's slide shape and why: (ratio, reason). setting is
    slides.aspect_ratio: a ratio, or auto for the deck's own, which is its
    aspectratio as beamer reads it, else 4:3 when it names a variable of
    beamer's (BEAMER_ONLY), else 16:9."""
    setting = str(setting or "auto").strip()
    if setting != "auto":
        return setting, "slides.aspect_ratio"
    own = meta_text(meta.get("aspectratio")).strip()
    if own in BEAMER_RATIOS:
        return BEAMER_RATIOS[own], "its aspectratio"
    if RATIO.match(own):
        return own.replace(" ", ""), "its aspectratio"
    named = [key for key in BEAMER_ONLY if key in meta
             and not (key == "theme"
                      and meta_text(meta[key]).strip().lower() in REVEAL_THEMES)]
    if named:
        return BEAMER_RATIO, f"its {named[0]}, which is beamer's"
    return DEFAULT_RATIO, "the default"


def is_notes(node):
    """Whether a block is a ::: notes div, which the PDF leaves out."""
    return node.get("t") == "Div" and "notes" in node["c"][0][1]


def visit(node, function):
    """function on each element of a deck in reading order, a ::: notes
    div's aside."""
    if isinstance(node, dict):
        if is_notes(node):
            return
        function(node)
        for value in node.values():
            if isinstance(value, (dict, list)):
                visit(value, function)
    elif isinstance(node, list):
        for value in node:
            visit(value, function)


def section_levels(blocks, level):
    """The levels of the headings above the slide level, the sections',
    shallowest first: headings as Pandoc finds slides, in the deck's own
    blocks and its divs."""
    found = set()

    def walk(blocks):
        for block in blocks:
            if block.get("t") == "Header" and block["c"][0] < level:
                found.add(block["c"][0])
            elif block.get("t") == "Div" and not is_notes(block):
                walk(block["c"][1])
    walk(blocks)
    return sorted(found)


def renumber(blocks, level):
    """The headings renumbered as ltx-talk numbers sections: the levels of
    the sections above the slide level 1, 2, 3 in order, the slides one
    below the deepest, and what's in a slide moved with it. Pandoc's beamer
    writer makes a level-1 heading \\section and a level-2 \\subsection
    whatever the slide level, and ltx-talk tags and bookmarks each at its
    own depth, so a deck whose sections are ## had \\subsections tagged H2
    under no H1, and one that skips a level a heading tagged two below the
    last. Returns the slide level now; a slide level of 0, no slides at
    headings, is left as it is."""
    if level <= 0:
        return level
    levels = section_levels(blocks, level)
    order = {old: new for new, old in enumerate(levels, 1)}
    shift = len(levels) + 1 - level

    def one(node):
        if node.get("t") == "Header":
            old = node["c"][0]
            node["c"][0] = order[old] if old in order else max(1, min(6, old + shift))
    visit(blocks, one)
    return len(levels) + 1


def frame_tag(blocks, level):
    """The heading a slide's title is tagged as when the template can't
    tag each at its own level (ltx-talk's code for a slide's title isn't
    the code it knows): H1 when nothing is above the slide level, one
    more for each level of sections above it."""
    return "H%d" % min(6, len(section_levels(blocks, level)) + 1)


def captioned_tables(blocks):
    """For each table the PDF shows, in order, whether it has a caption:
    a table in a ::: notes div isn't in the PDF."""
    found = []
    visit(blocks, lambda n: found.append(bool(n["c"][1][1]))
          if n.get("t") == "Table" else None)
    return found


# What ltx-talk reads differently from beamer, in the LaTeX Pandoc's beamer
# writer gives (Writers/LaTeX.hs, 3.12.1).
#
# A code block's or code's text, set aside while the rest is rewritten,
# so code on a slide that shows LaTeX is shown as written and its
# \end{frame} doesn't end the frame: a code block without highlighting
# is verbatim (or Verbatim, with attributes), one with it Highlighting.
VERBATIM_TEXT = re.compile(
    r"\\begin\{(verbatim|Verbatim|lstlisting|Highlighting)\}.*?\\end\{\1\}", re.S)
# Where a piece of code stood while it's set aside.
HELD = "\x00%d\x00"
HELD_MARK = re.compile("\x00(\\d+)\x00")
# What makes a frame need ltx-talk's frame*, which reads its body
# verbatim: a code block, set aside above, highlighted (in Shaded) or not,
# and inline code the writer highlights (fancyvrb's \VERB).
VERBATIM = re.compile(r"\x00\d+\x00|\\begin\{Shaded\}|\\VERB\b")
# A frame as the writer opens one: its options, and whether a title
# follows (a slide a horizontal rule begins has none).
FRAME = re.compile(r"\\begin\{frame\}")
# beamer's frame options ltx-talk has a key for.
FRAME_KEYS = {"allowframebreaks": "auto-break=true",
              "t": "vertical-alignment=top", "c": "vertical-alignment=center",
              "b": "vertical-alignment=bottom"}
# ltx-talk 0.6.9's frame keys: a key=value option naming one of them stays.
TALK_FRAME_KEYS = ("action-spec", "auto-break", "auto-break-coverage", "label", "name",
                   "supplementary-frame", "tag-slides", "vertical-alignment")
# Columns as the writer opens them (wrapDiv in Writers/LaTeX/Util.hs):
# columns with an alignment, beamer's T by default, and perhaps
# totalwidth and onlytextwidth; a column with an alignment if it has one.
COLUMNS = re.compile(r"\\begin\{(columns|column)\}\[([^\]]*)\]")
# beamer's alignments as ltx-talk's keys, which have no baseline variant.
COLUMN_KEYS = {"T": "t", "t": "t", "c": "c", "b": "b"}
# A footnote as the writer writes one for beamer (inlineToLaTeX's Note,
# Writers/LaTeX.hs): from the current overlay on, and on the frame rather
# than a column. ltx-talk takes the overlay for an action and stops on
# beamer's counter, and takes [frame] for the footnote's number.
BEAMER_FOOTNOTE = re.compile(r"\\footnote(?:<\\value\{beamerpauses\}->|<\.->)\[frame\]")
# A numbered list's style as the writer gives beamer one, beamer's own
# template on the line after \begin{enumerate} ([a.], [(i)], [1)]), which
# ltx-talk, whose optional argument is an action, sets as text before the
# first \item. LaTeX's \labelenumi does it, as the writer has it for any
# other class.
LIST_STYLE = re.compile(
    r"(\\begin\{enumerate\}(?:\[<\+->\])?)\n([ \t]*)\[(\()?([1aAiI])([.)])\]\n")
LIST_COUNTERS = {"1": "arabic", "a": "alph", "A": "Alph", "i": "roman", "I": "Roman"}
# A section as the writer writes one. ltx-talk reads a section's optional
# argument as keys when it holds an = and as its short title otherwise,
# and with none given takes the title for it: a title with an = in it
# ("Profit: MR = MC") stopped LaTeX. A short title given as the key
# shorttitle is read as written.
SECTION = re.compile(r"\\(section|subsection|subsubsection)(\*?)(?=[\[{])")
SECTION_KEYS = ("bookmark", "label", "nameref", "numbered", "unnumbered", "quote",
                "running", "shorttitle", "subtitle", "toc")
# beamer's modes as ltx-talk names them (header-includes'
# \mode<presentation>{...}): ltx-talk has projector, handout, and article,
# one at a time, and took presentation, or beamer|handout, for an overlay
# and set it as text. The PDF is ltx-talk's projector mode, so a mode
# beamer would show there is projector, and any other article, which
# isn't shown. \mode*, which ltx-talk took for \mode with * to show, goes.
MODES = re.compile(r"\\mode\s*<([^<>]*)>")
SHOWN_MODES = ("presentation", "beamer", "projector", "all")


def group_end(tex, at, opening="{", closing="}"):
    """The index just past the group that opens at tex[at], braces inside
    it counted and escaped characters skipped, or -1 if it doesn't
    close. For [ ], what's in braces inside is skipped too."""
    depth, braces, i = 0, 0, at
    while i < len(tex):
        char = tex[i]
        if char == "\\":
            i += 2
            continue
        if opening != "{" and char in "{}":
            braces += 1 if char == "{" else -1
        elif braces == 0 and char == opening:
            depth += 1
        elif braces == 0 and char == closing:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def top_level_split(text):
    """Options split at the commas outside braces."""
    parts, depth, current = [], 0, []
    for char in text:
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return [part.strip() for part in parts]


def frame_options(options, counts):
    """beamer's frame options as ltx-talk's keys, the rest named in
    counts."""
    keys = []
    for option in top_level_split(options):
        key, _, value = option.partition("=")
        key = key.strip()
        if not option or option in ("fragile", "containsverbatim"):
            continue
        if option in FRAME_KEYS:
            keys.append(FRAME_KEYS[option])
        elif key == "allowframebreaks" and value.strip():
            # beamer's fraction of the slide filled before a break.
            keys += ["auto-break=true", "auto-break-coverage=" + value.strip()]
        elif value and key in TALK_FRAME_KEYS:
            keys.append(option)
        elif option not in counts["dropped"]:
            counts["dropped"].append(option)
    return keys


def list_styles(tex):
    """beamer's numbered-list templates as LaTeX's \\labelenumi, ii, ...,
    by how deep the list is."""
    def one(m):
        before = tex[:m.start()]
        depth = before.count("\\begin{enumerate}") - before.count("\\end{enumerate}") + 1
        if not 1 <= depth <= 4:
            return m.group(1) + "\n"
        counter = "enum" + ("i", "ii", "iii", "iv")[depth - 1]
        number = "\\%s{%s}" % (LIST_COUNTERS[m.group(4)], counter)
        label = "(%s)" % number if m.group(3) else number + m.group(5)
        return "%s\n%s\\def\\label%s{%s}\n" % (m.group(1), m.group(2), counter, label)
    return LIST_STYLE.sub(one, tex)


def section_titles(tex):
    """Each section's short title given as ltx-talk's shorttitle key."""
    out, pos = [], 0
    while True:
        m = SECTION.search(tex, pos)
        if not m:
            out.append(tex[pos:])
            return "".join(out)
        i, short = m.end(), None
        if tex[i] == "[":
            j = group_end(tex, i, "[", "]")
            if j < 0:
                out.append(tex[pos:i])
                pos = i
                continue
            short, i = tex[i + 1:j - 1], j
        k = group_end(tex, i) if i < len(tex) and tex[i] == "{" else -1
        if k < 0:
            out.append(tex[pos:i])
            pos = i
            continue
        title = tex[i + 1:k - 1]
        if short is not None and short.split("=", 1)[0].strip() in SECTION_KEYS \
                and "=" in short:
            keys = short
        else:
            keys = "shorttitle={%s}" % (title if short is None else short)
        out.append(tex[pos:m.start()] + "\\%s%s[%s]{%s}" % (m.group(1), m.group(2), keys, title))
        pos = k


def talkify(tex):
    """Pandoc's beamer LaTeX as ltx-talk with frame-title-arg builds it.
    ltx-talk reads a frame's options as keys only when they hold an =, and
    otherwise as an overlay specification; it can't take a verbatim body in
    a frame, only in frame*; and a frame without a title takes the first
    token of its body as one. So: a frame holding code becomes frame*,
    beamer's fragile and containsverbatim go, allowframebreaks and t, c,
    and b become ltx-talk's keys, a key=value option naming one of
    ltx-talk's keys stays, any other is dropped, and a frame with no title
    gets an empty one, which ltx-talk neither shows nor tags. Frames don't
    nest, so each \\begin{frame} is closed by the next \\end{frame} that
    isn't code. Columns' alignments become ltx-talk's t, c, and b, and
    their totalwidth its width; a footnote loses beamer's overlay and
    [frame]; a numbered list's style is LaTeX's \\labelenumi; a
    section's short title is given as a key; and beamer's modes are
    ltx-talk's. Code is set aside first, so none of this touches it.
    Returns the LaTeX and counts: verbatim frames, untitled frames, and
    the options dropped."""
    counts = {"verbatim": 0, "untitled": 0, "dropped": []}
    held = []

    def hold(m):
        held.append(m.group(0))
        return HELD % (len(held) - 1)
    tex = VERBATIM_TEXT.sub(hold, tex)

    def columns(m):
        keys = []
        for option in m.group(2).split(","):
            option = option.strip()
            if option in COLUMN_KEYS:
                keys.append(COLUMN_KEYS[option])
            elif option.startswith("totalwidth=") and m.group(1) == "columns":
                keys.append("width=" + option.split("=", 1)[1])
            elif option and option != "onlytextwidth" and option not in counts["dropped"]:
                counts["dropped"].append(option)
        return "\\begin{%s}%s" % (m.group(1), "[%s]" % ",".join(keys) if keys else "")
    tex = COLUMNS.sub(columns, tex)
    tex = BEAMER_FOOTNOTE.sub(lambda m: "\\footnote", tex)
    tex = list_styles(tex)
    tex = section_titles(tex)
    tex = MODES.sub(lambda m: "\\mode<%s>" % (
        "projector" if any(mode.strip() in SHOWN_MODES for mode in m.group(1).split("|"))
        else "article"), tex)
    tex = re.sub(r"\\mode\*", "", tex)
    out, pos = [], 0
    while True:
        m = FRAME.search(tex, pos)
        if not m:
            out.append(tex[pos:])
            break
        out.append(tex[pos:m.start()])
        i, options = m.end(), ""
        if tex.startswith("[", i):
            j = group_end(tex, i, "[", "]")
            if j > 0:
                options, i = tex[i + 1:j - 1], j
        titled = tex.startswith("{", i)
        if titled:
            i += 1
        end = tex.find("\\end{frame}", i)
        if end < 0:
            out.append(tex[m.start():])
            break
        body = tex[i:end]
        keys = frame_options(options, counts)
        star = bool(VERBATIM.search(body))
        counts["verbatim"] += star
        if not titled:
            counts["untitled"] += 1
        environment = "frame*" if star else "frame"
        out.append("\\begin{%s}%s%s%s\\end{%s}" % (
            environment, "[%s]" % ",".join(keys) if keys else "",
            "{" if titled else "{}", body, environment))
        pos = end + len("\\end{frame}")
    tex = "".join(out)
    return HELD_MARK.sub(lambda m: held[int(m.group(1))], tex), counts


def is_svg(src):
    """Whether an image's address is a local SVG file."""
    return src.lower().split("?")[0].endswith(".svg") and "://" not in src


def svg_images(doc):
    """The local SVG images the deck's PDF would show."""
    found = []
    visit(doc.get("blocks", []), lambda n: found.append(n["c"][2][0])
          if n.get("t") == "Image" and is_svg(n["c"][2][0]) else None)
    return found


def svgs_to_pdf(doc, base, out_dir):
    """Each local SVG image made a PDF in out_dir with rsvg-convert, and
    the image pointed at it by its absolute path: Pandoc's LaTeX writer
    gives an SVG \\includesvg, which needs Inkscape and takes no alt text,
    and the template doesn't load it. Returns the SVGs that couldn't be
    made PDFs, each with why."""
    failed, made = [], {}

    def one(node):
        if node.get("t") != "Image" or not is_svg(node["c"][2][0]):
            return
        target = node["c"][2]
        src = target[0]
        if src not in made:
            out = os.path.join(out_dir, "svg-%d.pdf" % len(made))
            # The address as Markdown gives it, a space as %20.
            source = os.path.join(base, unquote(src))
            why = None
            if not os.path.isfile(source):
                why = "there's no such file"
            elif shutil.which("rsvg-convert") is None:
                why = "rsvg-convert isn't installed"
            else:
                done = subprocess.run(["rsvg-convert", "-f", "pdf", "-o", out, source],
                                      capture_output=True, text=True, errors="replace",
                                      stdin=subprocess.DEVNULL)
                if done.returncode:
                    why = "rsvg-convert: " + (" ".join(done.stderr.split())[:120]
                                              or "exit %d" % done.returncode)
            made[src] = None if why else out
            if why:
                failed.append((src, why))
        if made[src]:
            target[0] = made[src]
    visit(doc.get("blocks", []), one)
    return failed


RERUN = re.compile(r"Warning:.*Rerun", re.I)
# ltx-talk 0.6.9 stops on an older LaTeX, and loads the font and the math
# package below, which TinyTeX doesn't install with it.
LTX_TALK_LATEX = "2026-06-01"
LTX_TALK_FILES = (("ltx-talk.cls", "ltx-talk"),
                  ("lua-unicode-math.sty", "lua-unicode-math"),
                  ("NewCMSans10-Regular.otf", "newcomputermodern"))


def ltx_talk_problem():
    """Why a deck's PDF can't be built here, or None: LuaLaTeX missing,
    ltx-talk or what it loads not installed, or a LaTeX older than it
    takes."""
    if shutil.which(latexbuild.ENGINE) is None:
        return (f"{latexbuild.ENGINE} is not on the path, and a deck's PDF is built "
                "with it (see docs/installation.md).")
    if shutil.which("kpsewhich"):
        missing = []
        for name, package in LTX_TALK_FILES:
            found = subprocess.run(["kpsewhich", name], capture_output=True, text=True,
                                   stdin=subprocess.DEVNULL).stdout.strip()
            if not found:
                missing.append(package)
        if missing:
            return ("A deck's PDF is built with the ltx-talk class, and TeX doesn't have "
                    + ", ".join(missing) + ": `" + latexbuild.tlmgr_command(
                        "install " + " ".join(missing)) + "` installs "
                    + ("it" if len(missing) == 1 else "them")
                    + " (see docs/installation.md).")
    release = latexbuild.latex_release()
    if release and release < LTX_TALK_LATEX:
        return (f"{latexbuild.ENGINE} runs the LaTeX release of {release}, and the "
                f"ltx-talk class a deck's PDF is built with needs {LTX_TALK_LATEX} or "
                "later (TeX Live 2026); docs/installation.md says how to update.")
    return None


# How long one LuaLaTeX run may take: a long deck takes seconds, and
# LaTeX caught in a loop, as ltx-talk 0.6.9 is by a \footnotetext the
# template hadn't fixed, never finishes.
LATEX_TIMEOUT = 300
# beamer's commands a deck's header-includes may give, which ltx-talk
# hasn't: the template makes them do nothing, and the run names them.
BEAMER_COMMANDS = re.compile(
    r"\\(setbeamertemplate|setbeamercolor|setbeamerfont|setbeamersize|setbeamercovered"
    r"|setbeameroption|addtobeamertemplate|defbeamertemplate|usebeamercolor"
    r"|usebeamerfont|usebeamertemplate|usetheme|usecolortheme|usefonttheme"
    r"|useinnertheme|useoutertheme|beamertemplate[a-z]+|logo|titlegraphic"
    r"|AtBeginSection|AtBeginSubsection|AtBeginPart)(?![A-Za-z@])")
# What the template writes to the log when ltx-talk's code for a slide's
# title isn't the code it knows, and every slide's title is tagged at one
# level.
ONE_LEVEL = "oer: every frame title tagged at one level"


def raw_text(value):
    """The LaTeX in a metadata value: raw blocks and inlines, and text."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("t") in ("RawBlock", "RawInline"):
                found.append(node["c"][1])
            elif node.get("t") in ("Str", "MetaString"):
                found.append(node["c"])
            else:
                walk(node.get("c"))
        elif isinstance(node, list):
            for child in node:
                walk(child)
    walk(value)
    return " ".join(found)


def build_pdf(intermediate, base, out_pdf, *, template, filters, language,
              standards=("ua-2",), ua1_math="office", ratio="auto", title=None,
              repair_captions=True, remove_empty_paragraphs=True, env=None,
              keep=None, trace=None):
    """One deck's tagged PDF, through ltx-talk: the deck's filtered
    intermediate, its headings renumbered (renumber), written by Pandoc's
    beamer writer with template and filters, talkified, and built by
    LuaLaTeX in a folder of its own, at least twice (ltx-talk's first run
    leaves a placeholder page) and again while the log asks for it, up to
    four times, each run stopped after LATEX_TIMEOUT seconds; then the
    tables' captions retagged and the empty paragraph elements taken out,
    as for a book's PDF. title names the PDF when the deck has none. keep:
    a folder the LaTeX is copied to. An SVG that can't be made a PDF stops
    it before LaTeX, which can't show one. Returns a dict: ok, pages, log
    (the last run's), timeout (LaTeX stopped), ratio and why, level, frame
    tag, whether each slide's title was tagged at its own level, talkify's
    counts, the SVGs that couldn't be converted and why, the beamer
    commands header-includes gives, and the repairs' counts."""
    with open(intermediate, encoding="utf-8") as fh:
        doc = json.load(fh)
    meta = doc.get("meta") or {}
    level = level_of(doc)
    if level is None:
        level = slide_level(doc.get("blocks", []))
    shape, why = aspect_ratio(meta, ratio)
    result = {"ok": False, "pages": 0, "log": "", "timeout": False, "ratio": shape,
              "ratio_why": why, "level": level, "tag": None, "own_levels": True,
              "talkify": None, "svg_failed": [], "retag": None, "paragraphs": None,
              "beamer_commands": sorted(set(BEAMER_COMMANDS.findall(
                  raw_text(meta.get("header-includes"))))),
              "pdf": out_pdf}
    level = renumber(doc.get("blocks", []), level)
    result["tag"] = tag = frame_tag(doc.get("blocks", []), level)
    work = tempfile.mkdtemp(prefix="deck-pdf-")
    try:
        result["svg_failed"] = svgs_to_pdf(doc, base, work)
        if result["svg_failed"]:
            result["log"] = "".join(
                f"! An SVG image couldn't be made a PDF, which LaTeX can't show: {src}: "
                f"{reason}.\n" for src, reason in result["svg_failed"])
            return result
        source = os.path.join(work, "deck.json")
        with open(source, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        tex = os.path.join(work, "deck.tex")
        standards = [str(s).strip() for s in standards if str(s).strip()] or ["ua-2"]
        macros = latexbuild.PDF_MACROS
        ua1 = latexbuild.is_ua1(standards)
        if ua1:
            macros += latexbuild.UA1_LINKS
        macros += "\\ifdefined\\directlua\n" + latexbuild.UM_ALIASES + "\\fi\n"
        command = ["pandoc", "-f", "json", "-t", "beamer", "-s", source, "-o", tex,
                   "--template", template, "--slide-level", str(level),
                   "--extract-media", os.path.join(work, "media"),
                   "-M", f"lang={language}",
                   "-V", f"aspect-ratio={shape}", "-V", f"frametitle-tag={tag}",
                   "-V", "math-setup=" + latexbuild.math_setup(standards, ua1_math),
                   "-V", "oer-macros=" + macros]
        for standard in standards:
            command += ["-M", f"pdfstandard={standard}"]
        if ua1:
            # PDF/UA-1 wants a /Contents on every link, and a footnote's
            # mark, which LaTeX makes a link, gets none; ltx-talk loads
            # hyperref itself, so the option goes before the class.
            command += ["-V", "hyperfootnotes-off=true"]
        if title and not meta.get("title") and not meta.get("title-meta"):
            command += ["-M", f"title-meta={title}"]
        for path in filters:
            command += ["--lua-filter", path]
        if trace:
            trace(command)
        done = subprocess.run(command, cwd=base, capture_output=True, text=True,
                              env=dict(env or os.environ, DECK_SLIDE_LEVEL=str(level)))
        if done.returncode:
            result["log"] = done.stderr
            return result
        with open(tex, encoding="utf-8") as fh:
            text, result["talkify"] = talkify(fh.read())
        with open(tex, "w", encoding="utf-8") as fh:
            fh.write(text)
        if keep:
            os.makedirs(keep, exist_ok=True)
            shutil.copy(tex, os.path.join(keep, os.path.splitext(
                os.path.basename(out_pdf))[0] + ".tex"))
        log_path = os.path.join(work, "deck.log")
        for run in range(1, 5):
            try:
                done = subprocess.run(
                    [latexbuild.ENGINE, "-interaction=nonstopmode", "-halt-on-error",
                     "-file-line-error", "deck.tex"],
                    cwd=work, capture_output=True, text=True, errors="replace",
                    stdin=subprocess.DEVNULL, env=env, timeout=LATEX_TIMEOUT)
            except subprocess.TimeoutExpired:
                done = None
            log = ""
            if os.path.exists(log_path):
                with open(log_path, encoding="utf-8", errors="replace") as fh:
                    log = fh.read()
            if done is None:
                result["timeout"] = True
                result["log"] = log
                return result
            result["log"] = log or done.stdout
            if done.returncode or not os.path.exists(os.path.join(work, "deck.pdf")):
                return result
            if run >= 2 and not RERUN.search(log):
                break
        result["own_levels"] = ONE_LEVEL not in result["log"]
        os.makedirs(os.path.dirname(os.path.abspath(out_pdf)), exist_ok=True)
        shutil.copyfile(os.path.join(work, "deck.pdf"), out_pdf)
        found = re.search(r"Output written on .*?\((\d+) pages?", result["log"])
        result["pages"] = int(found.group(1)) if found else 0
        result["ok"] = True
    finally:
        shutil.rmtree(work, ignore_errors=True)
    import pdfretag
    import pdfparagraphs
    if pdfretag.pikepdf is not None:
        captioned = captioned_tables(doc.get("blocks", []))
        if repair_captions and captioned:
            result["retag"] = pdfretag.retag(out_pdf, captioned)
        if remove_empty_paragraphs:
            result["paragraphs"] = pdfparagraphs.remove_from(out_pdf)
    return result
