#!/usr/bin/env python3
"""
restyle-headings.py -- report or rewrite the heading styles of a .docx.

    python3 util/restyle-headings.py book.docx                 # report
    python3 util/restyle-headings.py book.docx --from-toc      # what the TOC says
    python3 util/restyle-headings.py book.docx --from-toc -o book-restyled.docx
    python3 util/restyle-headings.py book.docx --promote Title -o out.docx
    python3 util/restyle-headings.py book.docx --map Title=Heading1,Heading1=Heading2 -o out.docx
    python3 util/restyle-headings.py book.docx --demote --title "Intro to Java" -o out.docx

WHY

Pandoc's DOCX reader reads Heading 1 through Heading 9 as headings and
nothing else. A book whose top level is styled Title loses it on the way
in: the first Title paragraph becomes the document's metadata title and
every later one becomes a plain paragraph. Everything downstream --
the page split, the contents guess, the EPUB's table of contents -- then
sees sections with no chapters over them. One book in this project's
corpus is exactly that: Title for its modules, Heading 1 for their
sections, and its own table-of-contents field declaring the order,
    TOC \\h \\z \\t "Heading 1,2,Heading 2,3,...,Title,1"
which is the mapping this tool applies with --from-toc.

The fix belongs in the source, and Word's Styles pane can do it in a
minute. This does the same thing mechanically, so that a book can be
re-exported and re-run without redoing it by hand.

WHAT IT DOES

Rewrites the w:pStyle of every paragraph in word/document.xml (and the
headers, footers, footnotes, and endnotes) according to a map, all at
once, so Heading1=Heading2,Heading2=Heading3 does not chain. --demote is
the map that moves every heading in use down one; --promote STYLE is
that plus STYLE=Heading1. --title TEXT then puts a Heading 1 paragraph
holding TEXT at the top of the body and records TEXT as the document's
dc:title property, for a book that has several Heading 1 sections and
no heading over them: the pipeline's promote_h1_to_title makes a lone
H1 the page's metadata title as well, so one paragraph serves as both. Paragraphs
whose style is remapped and whose text is empty are dropped, because an
empty Title paragraph would become an empty heading -- and Word leaves
plenty of those. Every target style has to exist in word/styles.xml;
Word defines Heading 3 and up only once they are used, so a shift that
needs one the document has never used is refused rather than producing
a paragraph Word cannot style. Every other part is copied byte for byte.

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

import argparse
import os
import collections
import re
import sys
import zipfile

PARTS = re.compile(r"^word/(document|header\d*|footer\d*|footnotes|endnotes)"
                   r"\.xml$")
PARA = re.compile(r"<w:p\b[^>]*>.*?</w:p>|<w:p\b[^>]*/>", re.S)
PSTYLE = re.compile(r'(<w:pStyle\s+w:val=")([^"]*)(")')
TEXT = re.compile(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>")
TOC_SWITCH = re.compile(r'<w:instrText[^>]*>\s*TOC\b[^<]*?\\t\s*"([^"]*)"',
                        re.I)
# Attributes come in any order: Word writes w:type before w:styleId,
# Pandoc the reverse.
STYLE_OPEN = re.compile(r"<w:style\b([^>]*)>(.*?)</w:style>", re.S)
STYLE_ATTR = re.compile(r'\bw:(styleId|type)="([^"]*)"')
STYLE_NAME = re.compile(r'<w:name\s+w:val="([^"]*)"')
HEADING_ID = re.compile(r"^Heading(\d)$")


def read(path):
    with zipfile.ZipFile(path) as archive:
        return {info.filename: archive.read(info.filename)
                for info in archive.infolist()}, \
            [info for info in archive.infolist()]


def paragraph_styles(document):
    """Style ids of paragraphs in w:styleId form; empty for none."""
    names = {}
    styles = {}
    for match in STYLE_OPEN.finditer(document.get("word/styles.xml", b"")
                                     .decode("utf-8", "replace")):
        attrs = dict(STYLE_ATTR.findall(match.group(1)))
        if attrs.get("type") != "paragraph" or "styleId" not in attrs:
            continue
        name = STYLE_NAME.search(match.group(2))
        styles[attrs["styleId"]] = name.group(1) if name else ""
        if name:
            names[name.group(1).lower()] = attrs["styleId"]
    return styles, names


def count_styles(xml):
    found = collections.Counter()
    empty = collections.Counter()
    for match in PARA.finditer(xml):
        para = match.group(0)
        style = PSTYLE.search(para)
        style_id = style.group(2) if style else ""
        found[style_id] += 1
        if not "".join(TEXT.findall(para)).strip():
            empty[style_id] += 1
    return found, empty


def toc_mapping(xml, names):
    """The style-to-level map a TOC field's \\t switch declares."""
    match = TOC_SWITCH.search(xml)
    if not match:
        return None
    fields = [f.strip() for f in match.group(1).split(",")]
    levels = {}
    for name, level in zip(fields[::2], fields[1::2]):
        style_id = names.get(name.lower())
        if style_id and level.isdigit():
            levels[style_id] = int(level)
    return levels


def map_from_levels(levels):
    """style id -> Heading<level>, leaving a style already at its level."""
    return {style: f"Heading{level}" for style, level in levels.items()
            if style != f"Heading{level}"}


def promote_map(style, styles):
    """style becomes Heading1 and every heading used moves down one."""
    out = {style: "Heading1"} if style else {}
    for style_id in styles:
        m = HEADING_ID.match(style_id)
        if m:
            out[style_id] = f"Heading{int(m.group(1)) + 1}"
    return out


def parse_map(text):
    out = {}
    for pair in text.split(","):
        if "=" not in pair:
            sys.exit(f"--map: {pair!r} is not FROM=TO.")
        a, b = (s.strip() for s in pair.split("=", 1))
        out[a] = b
    return out


def restyle(xml, mapping, keep_empty):
    """Apply the map to every paragraph at once; drop remapped empties."""
    changed = collections.Counter()
    dropped = collections.Counter()

    def one(match):
        para = match.group(0)
        style = PSTYLE.search(para)
        if not style or style.group(2) not in mapping:
            return para
        if not keep_empty and not "".join(TEXT.findall(para)).strip():
            dropped[style.group(2)] += 1
            return ""
        changed[style.group(2)] += 1
        return PSTYLE.sub(lambda m: m.group(1) + mapping[style.group(2)]
                          + m.group(3), para, count=1)

    return PARA.sub(one, xml), changed, dropped


def xml_escape(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


def insert_title(xml, text):
    """A Heading 1 paragraph as the first thing in the body. Inserted
    after the restyle, so it is not demoted with the rest."""
    para = ('<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r>'
            f'<w:t xml:space="preserve">{xml_escape(text)}</w:t></w:r></w:p>')
    return re.sub(r"(<w:body\b[^>]*>)", lambda m: m.group(1) + para, xml,
                  count=1)


def set_core_title(xml, text):
    """dc:title in docProps/core.xml. Pandoc does not read it, but Word
    shows it and other readers may."""
    if re.search(r"<dc:title\b", xml):
        return re.sub(r"<dc:title\b[^>]*>.*?</dc:title>|<dc:title\b[^>]*/>",
                      f"<dc:title>{xml_escape(text)}</dc:title>", xml,
                      count=1, flags=re.S)
    return xml.replace("</cp:coreProperties>",
                       f"<dc:title>{xml_escape(text)}</dc:title>"
                       "</cp:coreProperties>", 1)


def main():
    parser = argparse.ArgumentParser(
        description="Report or rewrite the heading styles of a .docx.")
    parser.add_argument("file")
    parser.add_argument("-o", "--output",
                        help="write the restyled document here")
    parser.add_argument("--in-place", action="store_true",
                        help="overwrite the input (keep a copy yourself)")
    how = parser.add_mutually_exclusive_group()
    how.add_argument("--from-toc", action="store_true",
                     help="use the levels the document's own TOC field "
                          "declares")
    how.add_argument("--promote", metavar="STYLE",
                     help="make STYLE the level-1 heading and move every "
                          "heading in use down one")
    how.add_argument("--demote", action="store_true",
                     help="move every heading in use down one")
    how.add_argument("--map", metavar="FROM=TO,...",
                     help="explicit style-id map, applied all at once")
    parser.add_argument("--title", metavar="TEXT",
                        help="insert a Heading 1 paragraph holding TEXT at "
                             "the top of the body, and set dc:title to it")
    parser.add_argument("--keep-empty", action="store_true",
                        help="keep empty paragraphs of a remapped style "
                             "instead of dropping them")
    args = parser.parse_args()
    if args.output and args.in_place:
        parser.error("give -o or --in-place, not both")

    document, infos = read(args.file)
    styles, names = paragraph_styles(document)
    body = document["word/document.xml"].decode("utf-8")
    found, empty = count_styles(body)

    if args.from_toc:
        levels = toc_mapping(body, names)
        if not levels:
            sys.exit(f"{args.file}: no TOC field with a \\t switch, so the "
                     "document does not say which styles are headings. "
                     "Use --promote or --map.")
        mapping = map_from_levels(levels)
    elif args.promote:
        if args.promote not in styles:
            sys.exit(f"{args.file}: no paragraph style {args.promote!r}. "
                     "Styles here: " + ", ".join(sorted(styles)))
        mapping = promote_map(args.promote, {s for s in found if s})
    elif args.demote:
        mapping = promote_map(None, {s for s in found if s})
    elif args.map:
        mapping = parse_map(args.map)
    else:
        mapping = {} if args.title else None

    print(f"{args.file}: paragraph styles in use")
    for style_id, count in found.most_common():
        label = style_id or "(none)"
        name = styles.get(style_id, "")
        note = f"  {empty[style_id]} empty" if empty[style_id] else ""
        print(f"  {count:6}  {label:24} {name}{note}")
    levels = toc_mapping(body, names)
    if levels:
        print("  The TOC field declares: " + ", ".join(
            f"{s} at level {n}" for s, n in sorted(levels.items(),
                                                   key=lambda kv: kv[1])))
    else:
        print("  No TOC field declares heading levels.")

    if mapping is None:
        print("Nothing changed. Give --from-toc, --promote STYLE, --demote, "
              "--map, or --title.")
        return 0

    mapping = {a: b for a, b in mapping.items() if a in found and a != b}
    needed = set(mapping.values()) | ({"Heading1"} if args.title else set())
    missing = sorted(b for b in needed if b not in styles)
    if missing:
        sys.exit("Cannot restyle: the document does not define "
                 + ", ".join(missing) + ". Word defines a heading style "
                 "once it is used, so apply that style to one paragraph "
                 "in Word, save, and run this again.")
    if mapping:
        print("Will apply: " + ", ".join(f"{a} -> {b}"
                                         for a, b in sorted(mapping.items())))
    if args.title:
        print(f"Will insert a Heading1 paragraph: {args.title!r}")
    if not (args.output or args.in_place):
        print("Give -o FILE or --in-place to write it.")
        return 0

    out_path = args.file if args.in_place else args.output
    with zipfile.ZipFile(out_path + ".tmp", "w") as archive:
        for info in infos:
            data = document[info.filename]
            if PARTS.match(info.filename):
                text, changed, dropped = restyle(data.decode("utf-8"),
                                                 mapping, args.keep_empty)
                if args.title and info.filename == "word/document.xml":
                    text = insert_title(text, args.title)
                data = text.encode("utf-8")
                for style_id, n in changed.items():
                    print(f"  {info.filename}: {n} {style_id} -> "
                          f"{mapping[style_id]}")
                for style_id, n in dropped.items():
                    print(f"  {info.filename}: {n} empty {style_id} "
                          "paragraph(s) dropped")
            elif args.title and info.filename == "docProps/core.xml":
                data = set_core_title(data.decode("utf-8"),
                                      args.title).encode("utf-8")
                print(f"  {info.filename}: dc:title set")
            archive.writestr(info, data)
    os.replace(out_path + ".tmp", out_path)
    print(f"Wrote {out_path}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
