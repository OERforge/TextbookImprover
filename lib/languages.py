"""
languages.py -- the language each page of a book is in, worked out once
and given to every target.

A page's language is, in order:

1. Its row in languages.csv (sidecars.languages), keyed by its source, as
   page-names.csv is: the page's name, its file's name without the
   extension made safe for a link, or the file's name itself.
2. The language its own file declares:
   - A Word file, which Pandoc's reader reads no language from: the custom
     property language, when the custom property company is a producer
     known to write it there (TRUSTED_PRODUCERS); else the language most of
     its letters are in, each letter's as Word resolves it, from the run's
     own properties, its character style's, its paragraph style's, and the
     document's defaults, the East Asian language for a Chinese, Japanese,
     or Korean letter and the complex-script one for a letter of a
     right-to-left or complex script; else core.xml's dc:language.
   - A PowerPoint deck: the producer's property likewise; else the
     language most of its runs say, as pptxparse counts them; else its
     default text style's; else its masters' text styles'.
   - Any other source: the lang Pandoc's reader gives it (a Markdown
     file's YAML, an HTML page's <html> or <body>, the body's winning, as
     the reader has it, an AsciiDoc file's lang attribute), or a LaTeX
     book's preamble's (latexsource.preamble_language).
3. The project's language.

A file's own that differs from the project's only in region, en-GB in a
book in en-US, or es in one in es-MX, doesn't override it: a Word file's
language is often just the one the copy of Word that made it was set to,
whatever the book is in. Nor, where the project declares none, does
en-US override the default, en, which the packages say.

OpenStax's Word files are why the producer's property is trusted: each is
Pandoc's output on OpenStax's own reference document, whose default is
en-US, and nothing in the file overrides it, so a Spanish book's sections
are English throughout to Word. OpenStax gives Pandoc the language as
language, a custom property to the Word writer, which reads lang. A
producer is added to TRUSTED_PRODUCERS when its files are known to carry
the right language there.

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

import collections
import csv
import os
import re
import zipfile
from xml.etree import ElementTree as ET

import sidecars

# The producers whose language property is a file's language, matched
# against the custom property company without regard to case.
TRUSTED_PRODUCERS = ("OpenStax",)

# oerconfig.LANGUAGE_RE, a primary subtag and any number of subtags,
# loosely, with a primary subtag of two or three letters, as ISO 639's
# are, so a word ("English", "Spanish") isn't one: tests/run-unit-tests.py
# holds every tag this takes to oerconfig's.
LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$")
# BCP 47's codes for no language, undetermined, several, and none coded,
# none of them a page's language; Office's x-none, the same, fails the
# pattern already.
NOT_A_LANGUAGE = {"zxx", "und", "mul", "mis"}

SIDECAR_COLUMNS = ["source", "language", "found", "drafted-by", "reviewed"]
# Where the sidecar keeps its value, and its drafted-by and reviewed
# columns, by position, as convert.py's REVIEW_COLUMNS reads them.
REVIEW = ((1,), 3, 4)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
CUSTOM = "{http://schemas.openxmlformats.org/officeDocument/2006/custom-properties}"
VT = "{http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes}"
DC = "{http://purl.org/dc/elements/1.1/}"
SLOTS = ("val", "eastAsia", "bidi")


# --------------------------------------------------------------------------
# tags
# --------------------------------------------------------------------------

def tag(value):
    """A language tag as a page carries it, in BCP 47's usual case (es-MX,
    zh-Hant-TW), or None when value isn't one: blank, a word ("English"),
    or a code for no language. Word's sort suffix goes (es-ES_tradnl, its
    Spanish with the traditional sort, is es-ES), and an underscore
    otherwise is a hyphen (en_US)."""
    value = str(value or "").strip()
    if "_" in value:
        head = value.split("_", 1)[0]
        value = head if "-" in head else value.replace("_", "-")
    if not LANGUAGE_RE.match(value) or value.lower() in NOT_A_LANGUAGE:
        return None
    parts = value.split("-")
    out, singleton = [parts[0].lower()], False
    for part in parts[1:]:
        if singleton or len(part) == 1:
            # An extension or private use, after its singleton: lowercase.
            singleton = True
            out.append(part.lower())
        elif len(part) == 2 and part.isalpha():
            out.append(part.upper())        # a region
        elif len(part) == 4 and part.isalpha():
            out.append(part.title())        # a script
        else:
            out.append(part.lower())
    return "-".join(out)


def language_of(value):
    """What a tag says the language is, with its script, the region and
    the rest aside: (primary and extended subtags, script or None)."""
    value = tag(value)
    if not value:
        return None
    parts = value.split("-")
    language, script = [parts[0]], None
    for part in parts[1:]:
        if len(part) == 3 and part.isalpha() and script is None and len(language) < 4:
            language.append(part)           # an extended language subtag
            continue
        if len(part) == 4 and part.isalpha():
            script = part
        break
    return "-".join(language), script


def same_language(a, b):
    """Whether two tags name one language, in one script, whatever their
    regions: en-GB and en-US, es and es-MX; not sr-Latn and sr-Cyrl."""
    one, other = language_of(a), language_of(b)
    return one is not None and one == other


def same_tag(a, b):
    return tag(a) is not None and tag(a) == tag(b)


# --------------------------------------------------------------------------
# what a file says
# --------------------------------------------------------------------------

Own = collections.namedtuple("Own", "language source found marks")
Own.__doc__ = """A file's own language: language, its producer's property's
when trusted, else its marks'; source, "producer" or "file"; found, where it
was found, for a person to judge it by; marks, the language the file's own
marks give (a Word file's text, a deck's runs), which a copy given another
language rewrites, or None."""


def custom_properties(archive):
    """{name lowercased: text} of an Office file's custom properties."""
    try:
        data = archive.read("docProps/custom.xml")
    except KeyError:
        return {}
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return {}
    out = {}
    for prop in root.iter(CUSTOM + "property"):
        name = (prop.get("name") or "").strip().lower()
        text = "".join(child.text or "" for child in prop
                       if child.tag.startswith(VT))
        if name:
            out.setdefault(name, text.strip())
    return out


def producer_language(props):
    """(language, producer) when a trusted producer's company property
    and a language property say the file's language, else (None, None)."""
    company = (props.get("company") or "").strip()
    if company.lower() not in {p.lower() for p in TRUSTED_PRODUCERS}:
        return None, None
    language = tag(props.get("language"))
    return (language, company) if language else (None, None)


def producer_found(name, producer):
    return "%s: its custom property language, which %s's files carry" % (name, producer)


# Letters Word gives the East Asian language: Han, kana, Hangul, and
# their compatibility and extension blocks.
EAST_ASIAN = ((0x1100, 0x11FF), (0x2E80, 0x2FDF), (0x3040, 0x30FF), (0x3100, 0x31FF),
              (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xA960, 0xA97F), (0xAC00, 0xD7FF),
              (0xF900, 0xFAFF), (0xFF66, 0xFFDC), (0x20000, 0x3134F))
# Letters it gives the complex-script language: right-to-left scripts,
# and those of South and Southeast Asia that Word lays out as complex.
COMPLEX = ((0x0590, 0x08FF), (0x0900, 0x0DFF), (0x0E00, 0x0EFF), (0x1000, 0x109F),
           (0x1780, 0x17FF), (0xFB1D, 0xFDFF), (0xFE70, 0xFEFF))


def _within(ranges, code):
    return any(low <= code <= high for low, high in ranges)


def slot(letter, complex_run=False):
    """Which of w:lang's three a letter takes its language from."""
    code = ord(letter)
    if _within(EAST_ASIAN, code):
        return "eastAsia"
    if complex_run or _within(COMPLEX, code):
        return "bidi"
    return "val"


def _languages(rpr):
    """{slot: value} of a run properties element's w:lang."""
    if rpr is None:
        return {}
    lang = rpr.find(W + "lang")
    if lang is None:
        return {}
    return {s: lang.get(W + s) for s in SLOTS if lang.get(W + s)}


def _complex(rpr):
    """Whether run properties mark the run right-to-left or complex."""
    if rpr is None:
        return False
    for name in ("rtl", "cs"):
        flag = rpr.find(W + name)
        if flag is not None and (flag.get(W + "val") or "true").lower() not in (
                "0", "false", "off"):
            return True
    return False


class _Styles:
    """What styles.xml says of the language: the document's defaults, and
    each style's own, by the style it's based on."""

    def __init__(self, data):
        self.defaults, self.styles, self.default, self.cache = {}, {}, {}, {}
        try:
            root = ET.fromstring(data) if data else None
        except ET.ParseError:
            root = None
        if root is None:
            return
        defaults = root.find(W + "docDefaults/" + W + "rPrDefault/" + W + "rPr")
        self.defaults = _languages(defaults)
        for style in root.iter(W + "style"):
            ident, kind = style.get(W + "styleId"), style.get(W + "type")
            based = style.find(W + "basedOn")
            rpr = style.find(W + "rPr")
            self.styles[ident] = (based.get(W + "val") if based is not None else None,
                                  _languages(rpr), _complex(rpr))
            if (style.get(W + "default") or "").lower() in ("1", "true", "on"):
                self.default.setdefault(kind, ident)

    def chain(self, ident, kind):
        """({slot: value}, complex) a style gives, with what the styles
        it's based on give beneath its own: the kind's default style when
        none is named."""
        ident = ident or self.default.get(kind)
        key = (ident, kind)
        if key not in self.cache:
            seen, order = set(), []
            while ident and ident not in seen and ident in self.styles:
                seen.add(ident)
                order.append(self.styles[ident])
                ident = self.styles[ident][0]
            merged, flag = {}, False
            for _based, languages, own_flag in reversed(order):
                merged.update(languages)
                flag = flag or own_flag
            self.cache[key] = (merged, flag)
        return self.cache[key]


def docx_own(path, name=None):
    """A Word file's own language (Own), or None when it says none."""
    name = name or os.path.basename(path)
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile):
        return None
    with archive:
        parts = set(archive.namelist())
        props = custom_properties(archive)
        styles = _Styles(archive.read("word/styles.xml") if "word/styles.xml" in parts else None)
        try:
            body = ET.fromstring(archive.read("word/document.xml")) \
                if "word/document.xml" in parts else None
        except ET.ParseError:
            body = None
        core = None
        if "docProps/core.xml" in parts:
            try:
                found = ET.fromstring(archive.read("docProps/core.xml")).find(DC + "language")
                core = tag(found.text) if found is not None else None
            except ET.ParseError:
                pass
    letters, marked = collections.Counter(), collections.Counter()

    def count(text, paragraph_style, run_style, rpr):
        langs, flag = {}, False
        sources = {}
        for slot_name, value in styles.defaults.items():
            langs[slot_name], sources[slot_name] = value, "default"
        for languages, own_flag in (styles.chain(paragraph_style, "paragraph"),
                                    styles.chain(run_style, "character")):
            for slot_name, value in languages.items():
                langs[slot_name], sources[slot_name] = value, "style"
            flag = flag or own_flag
        for slot_name, value in _languages(rpr).items():
            langs[slot_name], sources[slot_name] = value, "run"
        flag = flag or _complex(rpr)
        for letter in text:
            if not letter.isalpha():
                continue
            where = slot(letter, flag)
            language = tag(langs.get(where))
            if language:
                letters[language] += 1
                if sources[where] != "default":
                    marked[language] += 1

    def walk(element, paragraph_style):
        for child in element:
            if child.tag == W + "p":
                style = child.find(W + "pPr/" + W + "pStyle")
                walk(child, style.get(W + "val") if style is not None else None)
            elif child.tag == W + "r":
                rpr = child.find(W + "rPr")
                style = rpr.find(W + "rStyle") if rpr is not None else None
                text = "".join(t.text or "" for t in child.findall(W + "t"))
                if text:
                    count(text, paragraph_style, style.get(W + "val") if style is not None
                          else None, rpr)
                walk(child, paragraph_style)    # a text box's paragraphs
            else:
                walk(child, paragraph_style)

    if body is not None:
        walk(body, None)
    language, producer = producer_language(props)
    marks, how = None, None
    if letters:
        marks = letters.most_common(1)[0][0]
        how = "most of its text" if marked[marks] * 2 > letters[marks] \
            else "its default, which most of its text has"
    elif tag(styles.defaults.get("val")):
        marks, how = tag(styles.defaults.get("val")), "its default"
    elif core:
        marks, how = core, "its core properties' language"
    if language:
        return Own(language, "producer", producer_found(name, producer), marks)
    if marks:
        return Own(marks, "file", "%s: %s" % (name, how), marks)
    return None


def deck_own(deck, props, name):
    """A PowerPoint deck's own language (Own), from its parsed deck
    (pptxparse.Deck) and its custom properties, or None."""
    marks, how = None, None
    runs = collections.Counter()
    for value, n in deck.languages.items():
        if tag(value):
            runs[tag(value)] += n
    masters = collections.Counter()
    for value, n in deck.master_languages.items():
        if tag(value):
            masters[tag(value)] += n
    if runs:
        marks, how = runs.most_common(1)[0][0], "most of its text"
    elif tag(deck.default_language):
        marks, how = tag(deck.default_language), "its default"
    elif masters:
        marks, how = masters.most_common(1)[0][0], "its masters' text styles"
    language, producer = producer_language(props)
    if language:
        return Own(language, "producer", producer_found(name, producer), marks)
    if marks:
        return Own(marks, "file", "%s: %s" % (name, how), marks)
    return None


def pptx_own(path, name=None):
    """A deck's own language, read from its file (deck_own)."""
    import pptxparse
    name = name or os.path.basename(path)
    try:
        deck = pptxparse.read(path)
        with zipfile.ZipFile(path) as archive:
            props = custom_properties(archive)
    except Exception:                   # its checks say why it can't be read
        return None
    return deck_own(deck, props, name)


def declared_own(value, found):
    """The own language of a source whose reader gives one (Own), or None."""
    language = tag(value)
    return Own(language, "file", found, language) if language else None


HTML_ROOT = re.compile(r"<html\b([^>]*)>", re.I)
HTML_BODY = re.compile(r"<body\b([^>]*)>", re.I)
LANG_ATTRIBUTE = re.compile(r"""\s(lang|xml:lang)\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.I)


def html_language(text):
    """The language Pandoc's HTML reader gives a page: its <body>'s lang,
    or xml:lang, else its <html>'s (pHtml and pBody, Readers/HTML.hs)."""
    found = None
    for pattern in (HTML_ROOT, HTML_BODY):
        element = pattern.search(text)
        if not element:
            continue
        attributes = {m.group(1).lower(): m.group(2) if m.group(2) is not None else m.group(3)
                      for m in LANG_ATTRIBUTE.finditer(element.group(1))}
        value = attributes.get("lang") or attributes.get("xml:lang")
        if value:
            found = value
    return found


# --------------------------------------------------------------------------
# the sidecar, and what's decided
# --------------------------------------------------------------------------

def read_rows(path):
    """(rows, problems) of a languages sidecar: rows {source: language},
    in the file's order, a source given twice at its later row; problems,
    a sentence for each row whose language isn't a tag, which isn't used.
    A blank language is a row not filled in. Read by position, as every
    sidecar is: source, language, and anything after, the report's found,
    drafted-by, and reviewed."""
    rows, problems = collections.OrderedDict(), []
    if not path or not os.path.exists(path):
        return rows, problems
    with open(path, encoding=sidecars.CSV_ENCODING, newline="") as fh:
        for row in csv.reader(sidecars.csv_lines(fh)):
            if not row or not row[0].strip() or row[0].strip().lower() == "source":
                continue
            source = row[0].strip()
            value = row[1].strip() if len(row) > 1 else ""
            if not value:
                continue
            if not tag(value):
                problems.append("the row for %s gives %r, which isn't a language tag such as "
                                "en, en-US, or es-MX; it isn't used" % (source, value))
                continue
            rows.pop(source, None)
            rows[source] = tag(value)
    return rows, problems


def keys_of(source):
    """The names a row's source may give a page by: as written, without a
    file's extension, and each made safe for a link, as a page's name is."""
    from names import safe_stem
    names = [source]
    root, extension = os.path.splitext(source)
    if extension.lower() in (".docx", ".md", ".html", ".adoc", ".asciidoc", ".pptx", ".tex"):
        names.append(root)
    out = []
    for name in names:
        for key in (name, safe_stem(os.path.basename(name))):
            if key not in out:
                out.append(key)
    return out


def match_rows(rows, pages):
    """({page: language}, [unmatched source]): each row matched to the
    page whose name or other name (pages, {page: [names]}) it gives, the
    later of two rows for one page used, as a row appended to correct one
    is meant to be."""
    names = {}
    for page, others in pages.items():
        for name in [page] + list(others or ()):
            names.setdefault(name, page)
    found, unmatched = {}, []
    for source, language in rows.items():
        page = next((names[k] for k in keys_of(source) if k in names), None)
        if page is None:
            unmatched.append(source)
        else:
            found[page] = language
    return found, unmatched


Decision = collections.namedtuple("Decision", "language source own")
Decision.__doc__ = """A page's language: language, the tag; source,
"sidecar", "producer", "file", or "project"; own, the file's Own or None."""


def decide(row, own, project):
    """A page's Decision: its sidecar row's language, else its file's own
    (own, an Own), unless it differs from the project's only in region,
    else the project's."""
    if row:
        return Decision(tag(row), "sidecar", own)
    if own and own.language:
        if same_language(own.language, project):
            return Decision(tag(project) or project, "project", own)
        return Decision(own.language, own.source, own)
    return Decision(tag(project) or project, "project", own)


def other_than(decision, project):
    """Whether a page is in another language than the project's, not only
    another region's."""
    return not same_language(decision.language, project)


def for_copy(decision, declared):
    """(language, replacing) for a source's copy: language, what it says
    where the file says none, or None for nothing (the project's when the
    project doesn't declare it, which is nobody's decision); replacing,
    when the file's own marks are to be rewritten as language, what they
    say ("" for none), else None. A row rewrites a file's language, and a
    producer's property or the project's rewrites marks in another
    language, as an OpenStax file's English is in a Spanish book; a
    file's own region is kept."""
    marks = decision.own.marks if decision.own else None
    if decision.source == "sidecar":
        if same_tag(marks, decision.language):
            return decision.language, None
        return decision.language, marks or ""
    if decision.source in ("producer", "project") and marks \
            and not same_language(marks, decision.language):
        return decision.language, marks
    if decision.source == "project" and not declared:
        return None, None
    return decision.language, None


def for_source_targets(decision, reader):
    """What a Markdown or AsciiDoc target says a page's language is, its
    lang, as what the author decided: the reader's (reader, as written),
    which differs from the page's at most in region, unless a row decides;
    nothing where the reader gave none and the page's is the project's,
    since read back it is; else the page's. None for no lang."""
    if decision.source != "sidecar" and tag(reader) and same_language(reader, decision.language):
        return reader
    if not tag(reader) and decision.source == "project":
        return None
    return decision.language


def report_row(source, decision):
    """A languages-new.csv row: the sidecar's columns, the language drafted
    from the file."""
    return [source, decision.language, decision.own.found if decision.own else "", "TI", ""]
