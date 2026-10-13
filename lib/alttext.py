"""
alttext.py -- alt text that says nothing about its image, by the same
rules for a deck's pictures (pptxcheck.py) and a book's images
(convert.py, the output check).

What needs a person: alt text holding a file name or extension, which
PowerPoint's Accessibility Checker counts as missing; alt text that says
nothing (punctuation, a word such as "image", a clip-art id, a camera's
name for a file, a shape's default name, or a pattern a project lists in
images.alt_placeholders); a description Office generated, which Office
asks a person to review; alt text copied from a web page with its
picture (the page's title, or a stock site's caption); and alt text over
images.alt_max_chars.

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

import re

ALT_MAX_CHARS = 120
IMAGE_EXTENSIONS = r"png|jpe?g|jpe|jfif|gif|bmp|tiff?|svgz?|emf|wmf|webp|heic|heif|avif|ico|eps|pdf"
# A file name or extension anywhere in the alt text, which PowerPoint's
# checker counts as missing alt text: its rule is that "the alt text doesn't
# contain image names or file extensions" (Microsoft, Rules for the
# Accessibility Checker). Not a name's label before another (www.jpeg.org).
FILE_NAME = re.compile(r"\.(%s)(?!\w|\.\w)" % IMAGE_EXTENSIONS, re.I)
# What says nothing about an image, matched against the whole alt text
# with its case, surrounding space, and closing punctuation ignored.
GENERIC_WORDS = {
    "image", "images", "picture", "pic", "img", "photo", "photograph", "graphic",
    "graphics", "figure", "chart", "diagram", "icon", "logo", "illustration",
    "drawing", "clip art", "clipart", "screenshot", "screen shot", "placeholder",
    "alt", "alt text", "alternative text", "alt tag", "description", "untitled",
    "insert alt text", "add alt text", "null", "none", "n/a", "na", "tbd", "todo",
    "object", "shape", "group",
}
GENERIC_PATTERNS = [
    ("a clip-art id", re.compile(r"[a-z]{1,3}\d{5,}_?", re.I)),     # j0309720, bd20069_
    ("a camera's or tool's name for a file",
     re.compile(r"(img|dsc|dscn|dcim|pict?|image|photo|screenshot|screen ?shot)[ _-]?\d+[\w-]*",
                re.I)),
    ("a default shape name",
     re.compile(r"(picture|content placeholder|graphic|image|chart|diagram|object|group|"
                r"text ?box|rectangle|oval|freeform|straight connector|line|google shape)"
                r"[\s;]*[\d;p]*", re.I)),
]
# Office's generated descriptions: "Description automatically generated"
# after the description, and "A picture containing" before it, in older
# versions; "AI-generated content may be incorrect." after it, in newer ones.
AUTO_GENERATED = re.compile(r"description automatically generated|^a picture containing\b|"
                            r"ai-generated content may be incorrect", re.I)
# Alt text copied from a web page with its picture: the page's title, or a
# stock site's caption. A stock or clip-art site's name, or its words,
# anywhere; or, at the end, a site's name after a pipe, a domain after a
# dash, or a one-word name after a dash and a title of three words or
# more, a title cut off with an ellipsis, or a search engine's title's
# "- What Is It"; or a numbered section's title followed by its book's.
# Words a description uses too are left out (a vector image, a flat
# design, high-quality images). OpenStax's alt text, 2,478 descriptions in
# eight of its book repositories, matches none of these, nor does a corpus
# of Word books' 2,462.
STOCK_SITES = re.compile(
    r"\b(?:freepik|vectorstock|shutterstock|istock(?:photo)?|getty ?images|dreamstime|"
    r"depositphotos|123rf|alamy|adobe ?stock|vecteezy|pixabay|pexels|unsplash|flaticon|icons8|"
    r"iconfinder|noun ?project|rawpixel|storyblocks|pond5|bigstock(?:photo)?|can ?stock ?photo|"
    r"fotolia|stocksy|picfair|png(?:tree|wing|egg|item|img)|(?:kind|stick|seek|fav|clean|nice)png|"
    r"hiclipart|clipart(?:max| ?library))\b", re.I)
STOCK_WORDS = re.compile(
    r"\broyalty[- ]free\b|\bstock (?:photo|image|vector|illustration|footage|picture)s?\b|"
    r"\bfree (?:download|vectors?|png|svg|clip ?art|icons?)\b|\bdownload free\b|"
    r"\bhigh[- ]quality (?:vectors?|png)\b|\bpremium vector\b|"
    r"\b(?:png|svg) (?:images?|files?|icons?|clip ?art|graphics?|download|transparent)\b|"
    r"\btransparent (?:png|background)\b|\bvector (?:illustration|concept|art)s?\b|"
    r"\bflat (?:concept|vector)s?\b|\bflat (?:design |style )?icons?\b|\bconcept icon\b|"
    r"\bisolated on (?:a )?white\b", re.I)
PAGE_TITLE = (
    # "Marketing Mix Explained | Quizlet", "Woman with a tablet | Premium Vector"
    re.compile(r"\s\|\s+[^|()]{1,40}$"),
    # "Why Do Supply Chains Fail? - Examplepedia": a one-word name after a
    # title of three words or more. A word or two and a name after a dash
    # is as often a label: Creative Commons' "Attribution - By" and
    # "ShareAlike - SA", or "Knowledge Check - Memo" (7 of the 2,462
    # descriptions in a corpus of Word books, and none a page's title).
    re.compile(r"^(?:\S+\s+){3,}[-\u2013\u2014]\s*[A-Z][\w&']*$"),
    # "Ten Tips for Better Slides - example.com"
    re.compile(r"\s[-\u2013\u2014]\s*[\w-]+\.(?:com|org|net|edu|gov|io|co)$"),
    # "Robot Shaking Hands With A Person ..."
    re.compile(r"\s(?:\.\.\.|\u2026)$"),
    # "Opportunity Cost - What Is It and Why It Matters"
    re.compile(r"[-\u2013\u2014:|]\s*what (?:is|are) (?:it|they)\b", re.I),
    # "4.3 Demand and Supply Together - Introductory Economics"
    re.compile(r"^\d+(?:\.\d+)+\s+\S.*\s[-\u2013\u2014|]\s"),
)


def clean(text):
    """Text as two are compared: its spacing, its closing punctuation,
    and its case aside."""
    return re.sub(r"[\s.!?;:,]+$", "", " ".join((text or "").split())).lower()


def placeholder_rules(extra=()):
    """The project's own patterns from images.alt_placeholders: plain
    text matched as a whole, case aside; "re:" for a regular expression."""
    words, patterns = set(), []
    for item in extra or ():
        item = str(item)
        if item.startswith("re:"):
            patterns.append(re.compile(item[3:], re.I))
        elif item.strip():
            words.add(clean(item))
    return words, patterns


def page_title(text):
    """Whether alt text looks copied from a web page with its picture: the
    page's title, or a stock site's caption (STOCK_SITES, STOCK_WORDS,
    PAGE_TITLE)."""
    return bool(STOCK_SITES.search(text) or STOCK_WORDS.search(text)
                or any(p.search(text) for p in PAGE_TITLE))


def problem(alt, rules=None, limit=ALT_MAX_CHARS):
    """(kind, rule) for alt text that needs a person, or None: kind is
    is-file-name, placeholder, auto-generated, page-title, or too-long
    (over limit characters; none, for no limit), and rule which of its
    rules it broke, in words. rules: placeholder_rules() of the project's
    own patterns."""
    text = " ".join((alt or "").split())
    if not text:
        return None
    words, patterns = rules or (set(), [])
    cleaned = clean(text)
    if FILE_NAME.search(text):
        return ("is-file-name", "a file name or extension")
    if not re.search(r"\w", text):
        return ("placeholder", "punctuation only")
    if cleaned in GENERIC_WORDS or cleaned in words \
            or any(p.fullmatch(text) or p.fullmatch(cleaned) for p in patterns):
        return ("placeholder", "says nothing")
    for name, pattern in GENERIC_PATTERNS:
        if pattern.fullmatch(cleaned):
            return ("placeholder", name)
    if AUTO_GENERATED.search(text):
        return ("auto-generated", "generated by Office")
    if page_title(text):
        return ("page-title", "a web page's title")
    if limit and len(text) > limit:
        return ("too-long", "%d characters (limit %d)" % (len(text), limit))
    return None


def reason(kind, rule):
    """The Reason column of image-alt-missing.csv for a problem(), a
    book's and a deck's alike: "says nothing (a clip-art id)", "too long
    (227 characters)"."""
    if kind == "placeholder":
        return rule if rule == "says nothing" else "says nothing (%s)" % rule
    if kind == "too-long":
        return "too long (%s)" % rule.split(" (")[0]
    return rule
