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
picture (the page's title, or a stock site's caption); alt text that is
only a credit (who made the picture, its license, where it's from); and
alt text over images.alt_max_chars. And, among a document's pictures,
one alt text on different pictures (shared).

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

import hashlib
import re

ALT_MAX_CHARS = 120
# A web page's title is short. The patterns that read the end of alt text
# as a title's end (PAGE_TITLE) read alt text no longer than this, since a
# long description's last sentence can end as a title does: a quotation,
# a dash, and its author.
TITLE_MAX_CHARS = 120
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
# stock site's caption. A stock or clip-art site's name anywhere, or its
# words: "royalty-free" and the like anywhere, and "stock photo" and its
# kin at the end or before a dash or a pipe, where a stock site puts them,
# not as a word processor's Stock Images button is named in a description
# of a screenshot. Or, at the end of alt text no longer than
# TITLE_MAX_CHARS: a site's name after a pipe, a domain after a dash, or a
# one-word name after a dash and a title of three words or more, a title
# cut off with an ellipsis, or a search engine's title's "- What Is It";
# or a numbered section's title followed by its book's. Words a
# description uses too are left out (a vector image, a flat design,
# high-quality images, a figure isolated on a white background).
# OpenStax's alt text, 45,427 in 49 of its book repositories, matches none
# of these, nor does a corpus of Word books' 2,462.
STOCK_SITES = re.compile(
    r"\b(?:freepik|vectorstock|shutterstock|istock(?:photo)?|getty ?images|dreamstime|"
    r"depositphotos|123rf|alamy|adobe ?stock|vecteezy|pixabay|pexels|unsplash|flaticon|icons8|"
    r"iconfinder|noun ?project|rawpixel|storyblocks|pond5|bigstock(?:photo)?|can ?stock ?photo|"
    r"fotolia|stocksy|picfair|png(?:tree|wing|egg|item|img)|(?:kind|stick|seek|fav|clean|nice)png|"
    r"hiclipart|clipart(?:max| ?library))\b", re.I)
STOCK_WORDS = re.compile(
    r"\broyalty[- ]free\b|"
    r"\bstock (?:photo|image|vector|illustration|footage|picture)s?(?=\s*(?:$|[-\u2013\u2014|]))|"
    r"\bfree (?:download|vectors?|png|svg|clip ?art|icons?)\b|\bdownload free\b|"
    r"\bhigh[- ]quality (?:vectors?|png)\b|\bpremium vector\b|"
    r"\b(?:png|svg) (?:images?|files?|icons?|clip ?art|graphics?|download|transparent)\b|"
    r"\btransparent (?:png|background)\b|\bvector (?:illustration|concept|art)s?\b|"
    r"\bflat (?:concept|vector)s?\b|\bflat (?:design |style )?icons?\b|\bconcept icon\b", re.I)
PAGE_TITLE = (
    # "Marketing Mix Explained | Quizlet", "Woman with a tablet | Premium Vector":
    # a name, capitalized, with no bracket in it, not a matrix's row
    # ([1 2 | 3]) or a set's condition ({x | x > 2}).
    re.compile(r"\s\|\s+[A-Z][^|(){}\[\]]{0,39}$"),
    # "Why Do Supply Chains Fail? - Examplepedia": a one-word name after a
    # title of three words or more. A word or two and a name after a dash
    # is as often a label: Creative Commons' "Attribution - By" and
    # "ShareAlike - SA", or "Knowledge Check - Memo" (7 of the 2,462
    # descriptions in a corpus of Word books, and none a page's title).
    re.compile(r"^(?:\S+\s+){3,}[-\u2013\u2014]\s*[A-Z][\w&']*$"),
    # "Ten Tips for Better Slides - example.com"
    re.compile(r"\s[-\u2013\u2014]\s*[\w-]+\.(?:com|org|net|edu|gov|io|co)$"),
    # "Robot Shaking Hands With A Person ...", not a sequence going on
    # (3, 6, 9, ...), whose ellipsis follows a comma or a number.
    re.compile(r"(?<![\d,])\s(?:\.\.\.|\u2026)$"),
    # "Opportunity Cost - What Is It and Why It Matters"
    re.compile(r"[-\u2013\u2014:|]\s*what (?:is|are) (?:it|they)\b", re.I),
    # "4.3 Demand and Supply Together - Introductory Economics"
    re.compile(r"^\d+(?:\.\d+)+\s+\S.*\s[-\u2013\u2014|]\s"),
)
# Alt text that is only a credit: who made the picture, under what
# license, or where it's from, and nothing of what it shows, as a
# caption's credit line or Wikimedia Commons' attribution copied in. Each
# of its sentences opens with a credit's label ("Source:", "Credit:",
# "Courtesy of", "Copyright 2021", a copyright sign, "Photographer:"), or
# is a list of bylines ("By" and a name, "Photo by" one, "From" a work
# "by" its author), licenses, "Own work", and addresses, a byline or an
# address among them. A license alone isn't one: it's what a license's
# badge is called. Nor is a byline that goes on to say what the picture
# shows ("Painting by Claude Monet of water lilies"), or a sentence that
# opens with "By" and a capital and isn't one ("By World War I, women had
# entered the workforce"). None of OpenStax's 45,427 alt texts is only a
# credit, though many end with one; two of the Word books' 2,462 are, one
# credit on two pictures.
URL = re.compile(r"\bhttps?://\S+|\bwww\.\S+", re.I)
MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
KINDS = (r"(?i:(?:photo(?:graph)?|image|picture|illustration|graphic|drawing|painting|map|"
         r"art(?:work)?|figure|screenshot|video)s?\s+)")
CREDIT_LABEL = re.compile(
    KINDS + r"?(?:(?i:credits?)\s*[:\-\u2013\u2014]|(?i:courtesy)\s+(?:(?i:of)\b|[A-Z])|"
    r"(?i:sources?)\s*:|(?i:copyright)\s*(?:\u00a9|\((?i:c)\)|:|\d{4}|(?i:by)\b)|\u00a9|"
    r"\((?i:c)\)\s*\d|(?i:photographer)\s*:)")
# A name: capitalized words, and the small words a name has between them.
NAME = (r"[A-Z\u00c0-\u024f][^\s,;]*(?:\s+(?:[A-Z\u00c0-\u024f&][^\s,;]*|"
        r"(?:and|of|the|de|van|von|der|da|di|du|la|le|y)\b))*")
BYLINE = re.compile(
    KINDS + r"?(?:(?i:from)\s+.+?\s+)?(?i:by)\s+(?!(?:the|a|an)\b)" + NAME
    + r"(?:\s+(?i:on|via|for|at|from)\s+" + NAME + r")?")
LICENSE = re.compile(
    r"(?:licen[cs]ed\s+(?:under\s+)?(?:(?:an?|the)\s+)?)?"
    r"(?:cc[\s-]?(?:by|0|zero)(?:[\s-](?:sa|nc|nd))*(?:[\s-]?\d(?:\.\d)?)?"
    r"(?:\s+(?:international|unported|generic))?(?:\s+licen[cs]e)?|"
    r"creative commons(?:\s+[\w.-]+){0,6}?|public domain|gfdl|"
    r"gnu free documentation licen[cs]e|all rights reserved)", re.I)
OWN_WORK = re.compile(r"own work", re.I)


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
                or len(text) <= TITLE_MAX_CHARS and any(p.search(text) for p in PAGE_TITLE))


def credit(text):
    """Whether alt text is only a credit (CREDIT_LABEL, BYLINE, LICENSE):
    who made the picture, its license, and where it's from."""
    marked = bool(URL.search(text))
    plain = URL.sub(" ", MARKDOWN_LINK.sub(r"\1", text))
    for sentence in re.split(r"(?<=[.;])\s+", plain):
        sentence = sentence.strip(" ,;:.-\u2013\u2014")
        # A credit in parentheses, "(credit: ...)", but not "(c) 2021".
        if sentence.startswith("(") and sentence.endswith(")"):
            sentence = sentence[1:-1].strip(" ,;:.-\u2013\u2014")
        if not sentence:
            continue
        if CREDIT_LABEL.match(sentence):
            marked = True
            continue
        for piece in re.split(r",|\s[-\u2013\u2014]\s", sentence):
            piece = piece.strip(" ()")
            if BYLINE.fullmatch(piece) or OWN_WORK.fullmatch(piece):
                marked = True
            elif piece and not LICENSE.fullmatch(piece):
                return False
    return marked


def problem(alt, rules=None, limit=ALT_MAX_CHARS):
    """(kind, rule) for alt text that needs a person, or None: kind is
    is-file-name, placeholder, auto-generated, page-title, credit, or
    too-long (over limit characters; none, for no limit), and rule which
    of its rules it broke, in words. rules: placeholder_rules() of the
    project's own patterns."""
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
    if credit(text):
        return ("credit", "a credit or a source")
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


def shared(items, identity=None):
    """{index: how many other pictures have its alt text} for each of
    items, [(key, alt)], whose alt text another picture of a document
    has too, case, spacing, and closing punctuation aside (clean): a
    description copied to a picture it may not fit, or the same picture
    in two files. A key names an image, and identity(key) is what tells
    two apart, a digest of its bytes (digest), so two files holding one
    image are one picture; it's asked only of keys whose alt text
    another key has. Empty alt text is no picture's."""
    keys = {}
    for key, alt in items:
        text = clean(alt)
        if text:
            keys.setdefault(text, []).append(key)
    others = {}
    for text, named in keys.items():
        named = list(dict.fromkeys(named))
        if len(named) > 1:
            pictures = {identity(key) if identity else key for key in named}
            if len(pictures) > 1:
                others[text] = len(pictures) - 1
    return {index: others[clean(alt)] for index, (_key, alt) in enumerate(items)
            if clean(alt) in others}


def shared_reason(others, noun="image"):
    """The Reason column for alt text shared() finds: "shared with 2 other
    images"."""
    return "shared with %d other %s%s" % (others, noun, "" if others == 1 else "s")


def digest(path, fallback=None):
    """What tells one image from another (shared): a digest of a file's
    bytes, as a deck's pictures are keyed, or fallback for a file that
    can't be read, or a path that names none (a%00.png)."""
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except (OSError, ValueError):
        return fallback
