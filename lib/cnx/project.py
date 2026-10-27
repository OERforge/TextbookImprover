"""
cnx.project -- what unpack-cnx.py writes beside the pages: project.yaml
with the book's metadata and its outline as contents, the media the
pages use, the sidecars the source can fill, and the report.

The outline is the book's own: a chapter is a group titled as the book
titles it ("Chapter 3 Demand and Supply") holding its introduction, its
sections, and its end-of-chapter pages; a unit is a group of chapters;
the answer key a group of its chapters' pages; the preface, appendices,
references, and index stand at the top, typed so an EPUB marks them.
The pages' own titles carry their numbers, so the book's numbering
setting stays off.

A table's summary, which OpenStax writes for every table in some books
and which their Word files lose, goes to table-captions.csv for each
table TextbookImprover asks a description for: one whose caption is its
label alone, under the label, and one with no caption at all (OpenStax
leaves a table in an answer unnumbered), under the key TextbookImprover
gives it, its place on its page ("chapter-12#table-5"). Every summary is
in cnx-table-summaries.csv besides, for anyone who wants them where a
table has a title.

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

import csv
import os
import re
import shutil
import textwrap
import unicodedata

import alttext
import sidecars

from .emit import TEXT_FIXES, symbol_counts, symbol_report
from .pages import Group

BARE_LABEL = re.compile(r"^(Table)\s+[A-Z]?\d+(\.\d+)*$")


def yaml_string(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def identifier(collection, slug):
    """An identifier no other book uses: the collection's UUID, which
    OpenStax keeps across a book's versions, as an XML name."""
    if collection.uuid:
        return "book-" + collection.uuid
    return "book-" + re.sub(r"[^A-Za-z0-9._-]+", "-", slug).strip("-")


def contents_lines(items, indent):
    pad = " " * indent
    lines = []
    for item in items:
        if isinstance(item, Group):
            lines.append(f"{pad}- title: {yaml_string(item.title)}")
            if item.kind == "answer-key":
                lines.append(f"{pad}  role: back")
            if item.kind == "unit":
                # A unit is a part: its chapters are groups of their own,
                # each numbering its notes apart (notes.numbering).
                lines.append(f"{pad}  type: part")
            lines.append(f"{pad}  items:")
            lines.extend(contents_lines(item.items, indent + 4))
        else:
            extra = []
            if item.role and item.group is None:
                extra.append(("role", item.role))
            if item.type:
                extra.append(("type", item.type))
            if extra:
                lines.append(f"{pad}- page: {item.name}")
                for key, value in extra:
                    lines.append(f"{pad}  {key}: {value}")
            else:
                lines.append(f"{pad}- {item.name}")
    return lines


def project_yaml(source, collection, slug, outline, publisher=None,
                 authors=None):
    lines = [f"# Written by {source}; yours to edit.", "project:",
             f"  identifier: {identifier(collection, slug)}",
             f"  title: {yaml_string(collection.title or slug)}",
             f"  language: {yaml_string(collection.language or 'en')}"]
    if publisher:
        lines.append(f"  publisher: {yaml_string(publisher)}")
    if collection.license_text or collection.license_url:
        license_text = collection.license_text or collection.license_url
        if collection.license_url and collection.license_url not in \
                license_text:
            license_text += f" ({collection.license_url})"
        lines.append(f"  description: {yaml_string('Licensed ' + license_text)}")
    if authors:
        lines.append("  authors:")
        lines.extend(f"    - {yaml_string(a)}" for a in authors)
    lines.append("  contents:")
    lines.extend(contents_lines(outline, 4))
    return "\n".join(lines) + "\n"


# The metadata file conversion.yaml names for an OpenStax book's PDF and
# LaTeX targets (pdf.metadata), a copy of the PDF target's default page,
# to be changed there, and the styles whose page is A4. Every design in
# OpenStax's ce-styles sets its pages' margins at 1in at the sides and
# 0.8in at the top and bottom, which the default page has, and only the
# carnival design's Polish pages set a size, A4 (pl-nursing's and
# pl-u-physics'); the rest are Prince's default, US Letter, the default
# page's.
PDF_LAYOUT = "pdf-layout.yaml"
DEFAULT_PDF_LAYOUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir,
                                  os.pardir, "bin", "pdf-layout.yaml")
A4_STYLES = ("pl-nursing", "pl-u-physics")

# OpenStax's four designs, each with the face it sets its books' text in
# (ce-styles' styles/design-settings/<design>/_typography.scss, baseFont)
# and the styles that use it (each style's book.scss, or the one it
# imports). A book's PDF takes its design's face for the text, and for
# the headings the face's bold, where OpenStax sets them in faces of their
# own, three of which draw a capital I and a small l alike. A style with
# no design in ce-styles (ap-history, otto-book) keeps the default's face.
DESIGNS = {
    "cosmos": ("IBM Plex Serif", (
        "american-government", "economics", "english-composition", "history",
        "lifespan-development", "philosophy", "pl-economics", "pl-psychology",
        "political-science", "psychology", "sociology", "world-history")),
    "carnival": ("IBM Plex Sans", (
        "anatomy", "anthropology", "ap-biology", "ap-physics", "ap-physics-2e", "biology",
        "chemistry", "college-physics", "college-physics-2e", "hs-physics", "microbiology",
        "neuroscience", "nursing-external", "nursing-internal", "organic-chemistry",
        "pl-nursing", "pl-u-physics", "u-physics")),
    "cardboard": ("Noto Sans", (
        "accounting", "astronomy", "bca", "business-ethics", "college-success",
        "computer-science", "data-science", "entrepreneurship", "finance",
        "hs-college-success", "information-systems", "intro-business", "marketing",
        "pl-marketing", "principles-management", "python")),
    "corn": ("Noto Sans", (
        "additive-manufacturing", "algebra-1", "calculus", "contemporary-math", "dev-math",
        "precalculus", "precalculus-coreq", "statistics")),
}
# Organic Chemistry is set in its design's second face (baseOption2Font).
OWN_FACES = {"organic-chemistry": "IBM Plex Serif"}

# What pdf-layout.yaml says of each face, which it names by its files: a
# file that isn't installed stops LaTeX, which the run names, where a
# face named by its family can be matched by another of its weights,
# without a word, as Debian's and Ubuntu's TeX Live has Noto Sans Medium
# and not its Regular, which fonts-noto-core has. IBM Plex Math's letters
# are Plex Serif's, and TeX Live's plex has both. IBM Plex has no math
# font with Plex Sans's letters. Noto Sans Math, which has Noto Sans's,
# has the MATH table a formula is set by only from version 3.000:
# Debian's and Ubuntu's fonts-noto-core have 2.001, and unicode-math,
# given it, sets formulas in Latin Modern Math (2026-10-20).


def face_files(stem, extension):
    """The lines that name a face by its four files, stem-Regular and the
    rest, for fontspec."""
    return [f"mainfont: {stem}", "mainfontoptions:", f"  - Extension={extension}",
            "  - UprightFont=*-Regular", "  - BoldFont=*-Bold", "  - ItalicFont=*-Italic",
            "  - BoldItalicFont=*-BoldItalic"]


FACES = {
    "IBM Plex Serif": ("Formulas in IBM Plex Math, whose letters are Plex Serif's.",
                       face_files("IBMPlexSerif", ".otf")
                       + ["mathfont: IBMPlexMath-Regular.otf"]),
    "IBM Plex Sans": ("Formulas stay in Latin Modern Math, since IBM Plex has no math "
                      "font with Plex Sans's letters.", face_files("IBMPlexSans", ".otf")),
    "Noto Sans": ("Formulas stay in Latin Modern Math: Noto Sans Math, whose letters are "
                  "Noto Sans's, has the table LaTeX sets a formula by from version 3.000 "
                  "(github.com/notofonts/math), and Debian's and Ubuntu's "
                  "fonts-noto-core have 2.001. With 3.000 or later installed, take the "
                  "# off the line below.",
                  face_files("NotoSans", ".ttf") + ["# mathfont: NotoSansMath-Regular.ttf"]),
}


def design_face(style):
    """(OpenStax's design for the style, the face it sets the style's
    text in), or None for a style with no design."""
    for design, (face, styles) in DESIGNS.items():
        if style in styles:
            return design, OWN_FACES.get(style, face)
    return None


def face_lines(style):
    """The lines pdf-layout.yaml gives the style's face, a comment saying
    what they do first; [] for a style with no design."""
    found = design_face(style)
    if not found:
        return []
    design, face = found
    said, settings = FACES[face]
    named = ("It's the default's face too, named here by its files, so the build stops "
             "if one isn't installed, where the default gives way to Latin Modern with a "
             "warning." if face == "IBM Plex Serif" else
             "It's named by its files, so the build stops if one isn't installed, where "
             "the default's face, IBM Plex Serif, gives way to Latin Modern with a warning.")
    words = (f"The text in {face}, as OpenStax sets this book in its {design} design, "
             "and the headings in its bold, where OpenStax sets them in a face of their "
             f"own. {named} " + said)
    return ["# " + line for line in textwrap.wrap(words, 72)] + settings


def openstax_pdf_layout(source, style):
    """pdf-layout.yaml for an OpenStax book of the style: the PDF target's
    default page (bin/pdf-layout.yaml), OpenStax's paper and margins with
    larger type, copied into the book's folder to be changed there, on A4
    for the styles OpenStax prints on it, its text in its design's face
    (face_lines). The default's opening comment, on being the default,
    gives way to one saying where the copy came from; a default someone
    has edited is copied as it is, its comment gone or not, and its paper
    set or not, and a face it names, or a math font, stays."""
    with open(DEFAULT_PDF_LAYOUT, encoding="utf-8") as fh:
        settings = fh.read()
    opening, blank, rest = settings.partition("\n\n")
    if blank and all(line.startswith("#") for line in opening.splitlines()):
        settings = rest
    head = [f"# Written by {source}; yours to edit.",
            "# The PDF's page: the PDF target's default (bin/pdf-layout.yaml),",
            "# copied here to be changed for this book; a field left out keeps",
            "# the default's value."]
    if style in A4_STYLES:
        settings, found = re.subn(r"(?m)^papersize:.*$", "papersize: a4", settings, count=1)
        if not found:
            settings = settings.rstrip("\n") + "\npapersize: a4\n"
        head.append("# On A4, as OpenStax prints this style's books.")
    faces = face_lines(style)
    if faces and not re.search(r"(?m)^(mainfont|mathfont)\s*:", settings):
        settings = settings.rstrip("\n") + "\n\n" + "\n".join(faces) + "\n"
    return "\n".join(head) + "\n\n" + settings


def openstax_conversion(source, figure_word="Figure", table_word="Table",
                        footer="Access for free at openstax.org"):
    """conversion.yaml for an OpenStax book: the footer OpenStax asks
    for, footnotes numbered through each chapter as OpenStax numbers
    them, the PDF's page (PDF_LAYOUT), and the words the book's captions
    open with where they aren't TextbookImprover's own (*Principles of
    Management*'s "Exhibit", a Polish book's "Ilustracja" and "Tabela").

    The footer is the attribution the book's copyright page asks a copy
    to carry on every page, digital or printed, in its words, and as
    OpenStax's PDFs print it: not a link, since an address as a link's
    text, on every page, is what some checkers report as a bare URL. Its
    words are the book's language's, as cookbook prints them on a page of
    OpenStax's PDF (folio.access_for_free), with the period the license
    page's English has after them."""
    lines = [f"# Written by {source}; yours to edit.",
             "# OpenStax asks that every page of a book made from theirs say where it",
             "# can be read for free; this footer does that on every page of every",
             "# target, in OpenStax's words.",
             "defaults:",
             f"  footer: {yaml_string(footer.rstrip('.') + '.')}",
             "  # Footnotes numbered through each chapter, as OpenStax numbers them;",
             "  # each unit is a part in project.yaml, so its chapters number apart.",
             "  notes:",
             "    numbering: group",
             "  # The PDF's page, the PDF target's default copied here to be changed.",
             "  pdf:",
             f"    metadata: {PDF_LAYOUT}"]
    if figure_word != "Figure" or table_word != "Table":
        lines += ["  # The word each caption's own label opens with, as the book has it.",
                  "  captions:"]
        if figure_word != "Figure":
            lines.append(f"    figure_prefixes: [{yaml_string(figure_word)}]")
        if table_word != "Table":
            lines.append(f"    table_prefixes: [{yaml_string(table_word)}]")
    return "\n".join(lines) + "\n"


def copy_media(asm, out, notes):
    copied = 0
    for rel, source in sorted(asm.media.items()):
        dest = os.path.join(out, *rel.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(source, dest)
        copied += 1
    for rel, module in sorted(asm.missing_media.items()):
        notes.append((module, "media-missing",
                      f"{rel}: named by the module, not in the repository; "
                      "its description stands in its place"))
    return copied


# What OpenStax writes for a table's summary when it has none to give. Of
# the 6,214 summaries in 41 of its book repositories (June 2026), 1,604 say
# nothing: 671 that alt text's rules catch (".", "---", and the like), and
# 933 these words: "No Summary" 575, "Assessment data" 124, "Some cells are
# left blank for visual design purposes." 75 (Principles of Finance, which
# says why a cell is empty and not what the table holds), "key equations
# table" 51 (the chemistry books'), "Assessment information" 34, "Table" and
# the like 26, "summary" 21, "no alt text" 13, "table x.x" 5, "No-Summary"
# 5, and a Polish template's "The table is called...Opis tabeli" 4.
EMPTY_SUMMARIES = alttext.placeholder_rules(
    ("No Summary", "No-Summary", "Assessment data", "Assessment information",
     "summary", "no alt text", "table", "table x.x", "key equations table",
     "Some cells are left blank for visual design purposes",
     "The table is called...Opis tabeli"))


def says_nothing(summary):
    """Whether a table's summary says nothing about it: a placeholder by
    the rules alt text is judged by (lib/alttext.py), or one of OpenStax's
    own (EMPTY_SUMMARIES)."""
    found = alttext.problem(summary, EMPTY_SUMMARIES, limit=None)
    return bool(found) and found[0] == "placeholder"


# A summary that reads its table out, a row or a cell at a time, rather
# than saying what the table shows: "Two rows and five columns. The first
# row is labeled, “x”, and the second is labeled, “g(x)”. The values of x
# are 2, 4, 6, and 8", "Top left cell reads: Essential Knowledge", "Reading
# the columns as ordered pairs, we have: (1, 31), (2, 28)…", "Row 2 has
# “Big Bang” and 10 to the 68", "f(1)=6, f(2)=8, f(3)=3, and f(4)=1", or
# the table's cells in words of its own ("Washington 67, J. Adams 90,
# Jefferson 83…", repeats). Drafted as a caption, it's read before the
# table it repeats. Of the 4,610 summaries that say something in 41 of
# OpenStax's repositories (June 2026), these rules name 1,941, 1,283 of
# them on a table with no title, whose summary is drafted: 1,609 by their
# words, and 332 more by the cells they repeat. Read: 99 of the first (the
# 29 a numbered row or column, a header's numbers, or a function's values
# names, and 70 others), and every one reads its table out; 50 of the
# second, and 49 do, the other a stem-and-leaf plot's stems. They leave
# out one that names the columns and not their cells ("This table
# presents the year in the first column and percent of workers paid
# hourly rates in the second column"), or one column's cells, its rows'
# names; and miss some that read a table out in words they don't know,
# with its numbers written as its cells don't have them ("10 to the power
# minus 3", "eight"), or in English beside a table in Polish.
_NUMBER = (r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
           r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|\d+)")
_NUMBER_PL = (r"(?:jedn\w*|dw\w+|trzy|trzech|czter\w+|pię\w+|sześ\w+|siedem\w*|"
              r"osiem\w*|dziewię\w+|dziesię\w+|\d+)")
_ORDINAL = (r"(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
            r"next|last|top|bottom|header|data|final|1st|2nd|3rd|\d+th)")
_SHAPE = re.compile(_NUMBER + r"[\s-]+(?:rows?|columns?)\b|"
                    + _NUMBER_PL + r"\s+(?:kolumn\w*|wiersz\w*|rzęd\w*)", re.I)
_PAIRS = re.compile(r"\bordered (?:pairs|triples)\b"
                    r"|(?:\([^()]{1,40},[^()]{1,40}\)\s*[,;]?\s*(?:and\s+)?){3,}", re.I)
_A_ROW_READ = re.compile(
    r"\b" + _ORDINAL + r"(?:\s+data)?\s+row\b[^.]{0,40}?\b(?:contains?|has|reads?|"
    r"is labell?ed|lists?|shows?|includes?|states?)\b"
    r"|\b" + _ORDINAL + r"\s+row\s*:"
    r"|\brows?\s+(?:\d+|one|two|three)\s*[:,]"
    r"|\b" + _ORDINAL + r"\s+column,?\s+" + _ORDINAL + r"\s+row\b"
    r"|\bentries\s+in\s+the\s+" + _ORDINAL + r"\s+row\b"
    r"|\bcells?\s+reads?\b|\bcells\s+contain\b"
    r"|\bfrom (?:left to right|top to bottom|bottom to top)\b"
    r"|\bunder (?:the|it|this)\b[^.]{0,60}?\b(?:are|is|reads?|lists?)\b"
    r"|\b(?:wiersz\w*|komórk\w*)\b[^.]{0,40}?\bzawiera\b|\bkolejno\b"
    r"|\bnagłówek\b[^.]{0,80}\bwpis\w*"
    r"|\b(?:rows?|columns?)\s+" + _NUMBER + r"(?:\s*(?:-|–|through|to|and)\s*" + _NUMBER
    + r")?\s+(?:has|have|had|reads?|contains?|shows?|lists?|gives?|describes?|is|are)\s+"
    r"(?:for\s+\w+\s+)?(?:the\s+(?:following|values|entries)\b|[“\"'‘]|minus\b|-?\$?\d)"
    r"|\bare the (?:numbers|values)\s*:", re.I)
_A_COLUMN_NAMED = re.compile(r"\bcolumn\s+(?:\d+|one|two|three)\s+(?:lists?|shows?|"
                             r"is labell?ed|contains?|has)\b", re.I)
_VALUES = re.compile(
    r"-?\$?\d[\d,]*(?:\.\d+)?%?(?:\s*[,;]\s*(?:and\s+|i\s+)?-?\$?\d[\d,]*(?:\.\d+)?%?){3,}"
    r"|(?:[“\"'‘][^”\"'’]{1,60}[”\"'’]\s*[,;]?\s*(?:and\s+|i\s+)?){3,}", re.I)
_EQUATIONS = re.compile(
    r"(?:(?:\w+\([^()]{0,20}\)|[\w)])\s*=\s*-?\$?\d+(?:\.\d+)?[^.;]*?[.;,]\s*(?:and\s+)?){3,}")
_HYPHENS = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2212"), "-")
_QUOTES = dict.fromkeys(map(ord, "\u201c\u201d\u201e\u201f\"\u2018\u2019\u201a\u201b'"), None)


def _comparable(text):
    """Text as a summary and its table's cells are compared: in its
    compatibility forms, a dash a hyphen, without quotation marks, in
    lowercase, its spaces one."""
    text = unicodedata.normalize("NFKC", text).translate(_HYPHENS).translate(_QUOTES)
    return " ".join(text.lower().split())


def repeats(summary, rows):
    """Whether a summary repeats its table: the words of six or more of
    the cells in its body's rows, or five if they're half of them, from
    two or more columns. The same words in two cells are counted once; a
    letter alone isn't counted, a digit is."""
    said = _comparable(summary)
    cells = {}       # a cell's words: the columns they're in
    for row in rows:
        for column, cell in enumerate(row):
            words = _comparable(cell).strip(" .,;:")
            if len(words) > 1 or words.isdigit():
                cells.setdefault(words, set()).add(column)
    found = [where for words, where in cells.items()
             if re.search(r"(?<![\w.])" + re.escape(words) + r"(?!\w|\.\d)", said)]
    return (len(found) >= 6 or len(found) == 5 and len(cells) <= 10) \
        and len(set().union(*found)) >= 2


def reads_out(summary, rows=()):
    """Whether a table's summary reads the table out, a row or a cell at a
    time: its rows or columns as ordered pairs, a row's or a cell's words,
    its shape or a column's name and then its values, a function's values,
    or, given the words of its body's cells by row, the table (repeats)."""
    if _PAIRS.search(summary) or _A_ROW_READ.search(summary) \
            or _EQUATIONS.search(summary):
        return True
    if (_SHAPE.search(summary) or _A_COLUMN_NAMED.search(summary)) \
            and _VALUES.search(summary):
        return True
    return repeats(summary, rows)


def write_captions(out, tables, report=None):
    """table-captions.csv, prefilled where a table's caption is its label
    alone, or it has none, and the source has a summary that says
    something; not for a layout table, which needs none. A summary that
    reads its table out (reads_out) is drafted as any other is, and named
    in the report, for a person to put what the table shows in its place.
    cnx-table-summaries.csv, every summary, and which read their tables
    out. `tables` is the emitter's: (page, label, caption text, summary,
    layout, the words of its body's cells by row, place, excerpt). Returns
    (prefilled, summaries, summaries that say nothing, drafted summaries
    that read their tables out)."""
    prefilled = empty = read_out = 0
    rows = []
    summaries = []
    for page, label, caption, summary, layout, cells, place, excerpt in tables:
        if not summary:
            continue
        # A summary isn't on the page, whose characters the emitter
        # reported, but it's drafted from, and listed.
        if report:
            table = label or (f"{page}#table-{place}" if place else "a table")
            for words in symbol_report(symbol_counts(summary), f" in the summary of {table}"):
                report(page, "symbol-font-character", words)
        caption, summary, excerpt = (
            (text or "").translate(TEXT_FIXES)
            for text in (caption, summary, excerpt))
        reading = reads_out(summary, [[cell.translate(TEXT_FIXES) for cell in row]
                                      for row in cells])
        summaries.append((page, label or "", caption, summary, "yes" if reading else ""))
        if says_nothing(summary):
            empty += 1
            continue
        if layout:
            continue
        if label and BARE_LABEL.match(caption.strip()):
            key = label
            rows.append((label, summary, page, "", "OpenStax", ""))
        elif not caption.strip() and place:
            key = f"{page}#table-{place}"
            rows.append((key, summary, page, excerpt, "OpenStax", ""))
        else:
            continue
        prefilled += 1
        if reading:
            read_out += 1
            if report:
                words = summary.split()
                report(page, "table-summary-reads-out",
                       f"{key}: its description in table-captions.csv, OpenStax's "
                       "summary, reads the table out, which a screen reader hears "
                       "before the table itself: “" + " ".join(words[:12])
                       + ("…" if len(words) > 12 else "") + "”")
    if rows:
        with open(os.path.join(out, "table-captions.csv"), "w", newline="",
                  encoding=sidecars.CSV_ENCODING) as fh:
            writer = csv.writer(fh)
            writer.writerow(["Label", "Description", "Source", "Excerpt",
                             "Drafted by", "Reviewed"])
            writer.writerows(rows)
    if summaries:
        with open(os.path.join(out, "cnx-table-summaries.csv"), "w",
                  newline="", encoding=sidecars.CSV_ENCODING) as fh:
            writer = csv.writer(fh)
            writer.writerow(["Page", "Label", "Caption", "Summary", "Reads out"])
            writer.writerows(summaries)
    return prefilled, len(summaries), empty, read_out
