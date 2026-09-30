"""A remediated copy of an author's Word file: the decisions the pipeline
makes about a Word source, written back into the file itself, so the
author can go on working in Word from an accessible document.

What it changes, all of it decided elsewhere in the pipeline:

- **Tables.** The header declaration a person made for each table in the
  table-headers sidecar, as the header pre-pass resolves it
  (`table-headers.py --resolved`). Never a guess: written into the file,
  a guess would read back as the file's own declaration, and nothing
  would say it was never reviewed. A guess becomes a decision when its
  prefilled row is adopted into the sidecar. A header row is
  written as Word's repeating header row (`w:tblHeader`), with any title
  rows above it, since Word's header rows start at the top; a header
  column as the table style's First Column flag. Both get the bookmark
  Freedom Scientific documents for JAWS (`Title`, `ColumnTitle`,
  `RowTitle`), which the census reads back as the table's declaration. A
  table is found by its position among the file's tables and changed only
  when its row count and first cell are what the pre-pass saw.
- **Images.** Alt text from the image-alt sidecar, as the drawing's
  description, and Word's "Mark as decorative" for `[decorative]`. A
  sidecar row names an image as Pandoc extracts it, `<stem>/media/rIdN`,
  which is its relationship in the file.
- **Captions.** A description from the table-captions sidecar, found as
  the filter recorded it (see htmlremediate): for a table with no label, a
  paragraph in Word's Caption style before it, kept with the table, where
  Word's Insert Caption puts one; for a label paragraph beside the table,
  the description joined to its end.
- **Links.** From the bare-links sidecar, a link's title as its ScreenTip,
  and its replacement address, which replaces the link's address and, for
  a bare link, its text.
- **Language.** The book's language as the document's default, when the
  file has none.
- **Equations.** With math.repair_equations, the characters of Word's own
  equations as math-repair.lua repairs them in the pages: a bar for an
  upper limit that is a macron or an en dash, mu for the micro sign, and
  the rest. Each is written as Pandoc writes the TeX the filter writes, so
  the file reads back as the pages already read. With math.from_text, math
  typed as text made Word's equation where the filter made one in the
  page (remediate_text_math).
- **Compatibility mode 15**, only when asked for.

Everything else is left as it was: the XML is edited as text, never parsed
and written again, and every part not changed is copied byte for byte.
Nothing is tested with Word or a screen reader here; the files are tested
against Word's schema.

Copyright 2026 Robert Szarka
"""

import html
import os
import re
import shutil
import tempfile
import zipfile

import docxtarget

R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
FIRST_ROW = 0x0020
FIRST_COLUMN = 0x0080
TITLE_ID = 870000


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

def table_spans(xml):
    """[(start, end)] of every w:tbl in document order, nested ones
    included, end just past its </w:tbl>: the order the census numbers
    tables in."""
    spans, stack = [], []
    for m in re.finditer(r"<w:tbl>|</w:tbl>", xml):
        if m.group(0) == "<w:tbl>":
            stack.append(len(spans))
            spans.append([m.start(), None])
        elif stack:
            spans[stack.pop()][1] = m.end()
    return [tuple(s) for s in spans if s[1] is not None]


def _own_rows(table):
    """[(start, end)] of the table's own rows, relative to table, not those
    of a table nested in a cell."""
    rows, depth, start = [], 0, None
    for m in re.finditer(r"<w:tbl>|</w:tbl>|<w:tr\b[^>]*>|</w:tr>", table):
        tag = m.group(0)
        if tag == "<w:tbl>":
            depth += 1
        elif tag == "</w:tbl>":
            depth -= 1
        elif depth == 1 and tag.startswith("<w:tr"):
            start = m.start()
        elif depth == 1 and tag == "</w:tr>" and start is not None:
            rows.append((start, m.end()))
            start = None
    return rows


def _text(fragment):
    return " ".join(html.unescape("".join(
        re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", fragment))).split())


def _set_header_row(row):
    """A row with its tblHeader on."""
    if re.search(r"<w:tblHeader\b", row):
        return re.sub(r"<w:tblHeader\b[^>]*/>", "<w:tblHeader/>", row, count=1)
    open_tag = re.match(r"<w:tr\b[^>]*>", row).group(0)
    rest = row[len(open_tag):]
    prex = re.match(r"\s*<w:tblPrEx>.*?</w:tblPrEx>", rest, re.S)
    at = len(open_tag) + (prex.end() if prex else 0)
    if re.match(r"\s*<w:trPr>", row[at:]):
        close = row.index("</w:trPr>", at)
        return row[:close] + "<w:tblHeader/>" + row[close:]
    if re.match(r"\s*<w:trPr\s*/>", row[at:]):
        return re.sub(r"<w:trPr\s*/>", "<w:trPr><w:tblHeader/></w:trPr>", row, count=1)
    return row[:at] + "<w:trPr><w:tblHeader/></w:trPr>" + row[at:]


def _set_look(table, bits):
    """The table's own tblLook with the given flags on."""
    tbl_pr = re.match(r"<w:tbl>\s*<w:tblPr>.*?</w:tblPr>", table, re.S)
    if not tbl_pr:
        return table
    props = tbl_pr.group(0)
    look = re.search(r"<w:tblLook\b[^>]*/>", props)
    if look:
        tag = look.group(0)
        for flag, name in ((FIRST_ROW, "firstRow"), (FIRST_COLUMN, "firstColumn")):
            if bits & flag:
                if re.search(r'w:%s="' % name, tag):
                    tag = re.sub(r'w:%s="[^"]*"' % name, 'w:%s="1"' % name, tag)
                elif 'w:val="' in tag:
                    pass
                else:
                    tag = tag.replace("<w:tblLook", '<w:tblLook w:%s="1"' % name, 1)
        val = re.search(r'w:val="([0-9A-Fa-f]{4})"', tag)
        if val:
            tag = tag.replace(val.group(0), 'w:val="%04X"' % (int(val.group(1), 16) | bits))
        new_props = props.replace(look.group(0), tag, 1)
    else:
        tag = '<w:tblLook w:val="%04X"%s%s/>' % (
            bits, ' w:firstRow="1"' if bits & FIRST_ROW else "",
            ' w:firstColumn="1"' if bits & FIRST_COLUMN else "")
        new_props = props.replace("</w:tblPr>", tag + "</w:tblPr>", 1)
    return new_props + table[len(props):]


def _title_bookmark(table, name, ident):
    """The JAWS bookmark at the start of the table's first cell."""
    if re.search(r'w:name="(?:Column|Row)?Title[^"]*"', table, re.I):
        return table
    cell = table.find("<w:tc>")
    para = re.compile(r"<w:p\b[^>]*>").search(table, cell) if cell >= 0 else None
    if not para:
        return table
    at = para.end()
    props = re.compile(r"\s*<w:pPr>.*?</w:pPr>", re.S).match(table, at)
    if props:
        at = props.end()
    return (table[:at] + '<w:bookmarkStart w:id="%d" w:name="%s"/><w:bookmarkEnd w:id="%d"/>'
            % (ident, name, ident) + table[at:])


def remediate_tables(xml, resolved, guesses=False):
    """Each table's declaration from the sidecar written into it, or with
    guesses, the census's guess too. resolved is the pre-pass's list for
    this file. Returns (xml, counts)."""
    counts = {"header_rows": 0, "header_columns": 0, "titles": 0, "skipped": 0,
              "undecided": 0}
    spans = table_spans(xml)
    edits = []
    for entry in resolved:
        value = entry.get("headers")
        if entry.get("supplier") != "sidecar" and not (guesses and entry.get("supplier") == "guess"):
            counts["undecided"] += entry.get("supplier") == "guess" and value in (
                "first-row", "first-column", "both")
            continue
        if value not in ("first-row", "first-column", "both"):
            continue
        index = entry.get("index")
        if not isinstance(index, int) or index >= len(spans):
            counts["skipped"] += 1
            continue
        start, end = spans[index]
        table = xml[start:end]
        rows = _own_rows(table)
        first_cell = re.search(r"<w:tc>.*?</w:tc>", table[rows[0][0]:rows[0][1]], re.S) if rows else None
        if len(rows) != entry.get("rows") or (entry.get("first") and not (
                first_cell and _text(first_cell.group(0)).startswith(entry["first"][:30]))):
            counts["skipped"] += 1
            continue
        row, col = value in ("first-row", "both"), value in ("first-column", "both")
        new = table
        if row:
            through = len(entry.get("caption_rows") or []) + 1
            for r_start, r_end in reversed(rows[:through]):
                new = new[:r_start] + _set_header_row(new[r_start:r_end]) + new[r_end:]
            counts["header_rows"] += 1
        if col:
            counts["header_columns"] += 1
        new = _set_look(new, (FIRST_ROW if row else 0) | (FIRST_COLUMN if col else 0))
        name = ("Title" if row and col else "ColumnTitle" if row else "RowTitle") + "_%d" % (index + 1)
        titled = _title_bookmark(new, name, TITLE_ID + index)
        counts["titles"] += titled != new
        edits.append((start, end, titled))
    for start, end, new in sorted(edits, reverse=True):
        xml = xml[:start] + new + xml[end:]
    return xml, counts


# ---------------------------------------------------------------------------
# Images and links
# ---------------------------------------------------------------------------

def remediate_images(xml, alts):
    """alts: {relationship id: alt text, or None for decorative}. Each
    drawing whose picture embeds one gets its description. Returns (xml,
    counts)."""
    counts = {"described": 0, "decorative": 0}
    if not alts:
        return xml, counts

    def one(m):
        drawing = m.group(0)
        embed = re.search(r'r:embed="([^"]+)"', drawing)
        if not embed or embed.group(1) not in alts:
            return drawing
        alt = alts[embed.group(1)]
        doc_pr = re.search(r"<wp:docPr\b([^>]*?)(/?)>", drawing)
        if not doc_pr:
            return drawing
        # An author's own title stays with a described image; a decorative
        # one has neither.
        attrs = re.sub(r'\s+descr="[^"]*"' if alt else r'\s+(?:descr|title)="[^"]*"',
                       "", doc_pr.group(1)).rstrip()
        attrs += ' descr="%s"' % html.escape(alt or "", quote=True)
        if alt is None:
            counts["decorative"] += 1
            if "decorative" in drawing:
                tag = "<wp:docPr%s%s>" % (attrs, doc_pr.group(2))
            elif doc_pr.group(2):
                tag = "<wp:docPr%s>%s</wp:docPr>" % (attrs, docxtarget.DECORATIVE)
            else:
                tag = "<wp:docPr%s>%s" % (attrs, docxtarget.DECORATIVE)
        else:
            counts["described"] += 1
            tag = "<wp:docPr%s%s>" % (attrs, doc_pr.group(2))
        return drawing[:doc_pr.start()] + tag + drawing[doc_pr.end():]
    xml = re.sub(r"<w:drawing>.*?</w:drawing>", one, xml, flags=re.S)
    return xml, counts


def alt_rows(path):
    """{stem: {relationship id: alt, or None for decorative}} from an
    image-alt sidecar, whose Image column names <stem>/media/rIdN.ext."""
    import csv
    found = {}
    if not path or not os.path.exists(path):
        return found
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            image, alt = (row.get("Image") or "").strip(), (row.get("Alt") or "").strip()
            parts = image.split("/")
            if len(parts) != 3 or parts[1] != "media" or not alt:
                continue
            found.setdefault(parts[0], {})[os.path.splitext(parts[2])[0]] = \
                None if alt == "[decorative]" else alt
    return found


def link_titles(path):
    """{address: title} from a bare-links sidecar."""
    import csv
    found = {}
    if not path or not os.path.exists(path):
        return found
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if (row.get("URL") or "").strip() and (row.get("Title") or "").strip():
                found[row["URL"].strip()] = row["Title"].strip()
    return found


CAPTION_STYLE = ('<w:style w:type="paragraph" w:styleId="Caption"><w:name w:val="caption"/>'
                 '<w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="35"/>'
                 '<w:unhideWhenUsed/><w:qFormat/><w:pPr><w:spacing w:after="200" w:line="240" '
                 'w:lineRule="auto"/></w:pPr><w:rPr><w:i/><w:iCs/><w:color w:val="44546A" '
                 'w:themeColor="text2"/><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>')


def _run(text):
    return '<w:r><w:t xml:space="preserve">%s</w:t></w:r>' % html.escape(text, quote=False)


SKIPPABLE = (r"(?:\s*(?:<w:bookmark(?:Start|End)\b[^>]*/>|<w:p\b[^>]*/>|"
             r"<w:p\b[^>]*>\s*(?:<w:pPr>(?:(?!</w:pPr>).)*</w:pPr>)?\s*</w:p>))*\s*")


def remediate_captions(xml, applied, resolved):
    """applied: [(position, how, key, description)] the filter recorded
    for the file; resolved: the pre-pass's entries, which give each
    table's shape. Returns (xml, counts)."""
    counts = {"captions": 0, "captions_left": 0, "labels_joined": 0}
    shapes = {e.get("index"): e for e in resolved}
    spans = table_spans(xml)
    edits = []
    for position, how, key, description in applied:
        if position >= len(spans):
            counts["captions_left"] += 1
            continue
        start, end = spans[position]
        if how in ("label-after", "label-before"):
            # Between a table and its label, only what Pandoc's reader
            # doesn't count as content: bookmarks (OpenStax wraps each table
            # in one) and empty paragraphs.
            if how == "label-after":
                para = re.compile(SKIPPABLE + r"(<w:p\b[^>]*>(?:(?!</w:p>).)*)(</w:p>)",
                                  re.S).match(xml, end)
            else:
                paras = list(re.finditer(r"(<w:p\b[^>]*>(?:(?!</w:p>).)*)(</w:p>)" + SKIPPABLE + r"\Z",
                                         xml[:start], re.S))
                para = paras[-1] if paras else None
            if para and _text(para.group(1)) == " ".join(key.split()):
                edits.append((para.start(2), _run(" " + description)))
                counts["labels_joined"] += 1
            else:
                counts["captions_left"] += 1
            continue
        entry = shapes.get(position)
        table = xml[start:end]
        rows = _own_rows(table)
        first = re.search(r"<w:tc>.*?</w:tc>", table[rows[0][0]:rows[0][1]], re.S) if rows else None
        if how != "position" or entry is None or len(rows) != entry.get("rows") or (
                entry.get("first") and not (
                    first and _text(first.group(0)).startswith(entry["first"][:30]))):
            counts["captions_left"] += 1
            continue
        edits.append((start, '<w:p><w:pPr><w:pStyle w:val="Caption"/><w:keepNext/></w:pPr>'
                             + _run(description) + "</w:p>"))
        counts["captions"] += 1
    for at, text in sorted(edits, key=lambda e: e[0], reverse=True):
        xml = xml[:at] + text + xml[at:]
    return xml, counts


# An equation's characters, as math-repair.lua repairs them in the pages
# (math.repair_equations), written into Word's own equations (OMML). Each
# structure below is what the statistics textbook's equations hold; each
# replacement is what Pandoc writes for the TeX the filter writes, so the
# file reads back as the pages already read.
MATH_RUN = re.compile(r"(<m:r>)((?:(?!</m:r>).)*?)(<m:t(?:\s[^>]*)?>)([^<]*)(</m:t>)(</m:r>)", re.S)
# A bar written as an upper limit: the base, and a macron or an en dash as
# the limit. Pandoc writes \bar{x} as an accent with an overline.
BAR = '<m:acc><m:accPr><m:chr m:val="\u203e" /></m:accPr><m:e>%s</m:e></m:acc>'
HAT = '<m:acc><m:accPr><m:chr m:val="\u0302" /></m:accPr><m:e>%s</m:e></m:acc>'
SUB_SLASHED_O = re.compile(r"(<m:sub><m:r>(?:(?!</m:r>).)*?<m:t(?:\s[^>]*)?>)\u00d8(</m:t></m:r></m:sub>)", re.S)
EQUATION_CHARACTERS = {"\u00b5": "\u03bc", "\u2206": "\u0394"}


def _repair_run(m, counts):
    """One m:r: its characters, and y-hat as an accent over y, the run
    split around it with its properties on each part."""
    start, props, t_open, text, t_close, end = m.groups()
    fixed = text
    for old, new in EQUATION_CHARACTERS.items():
        fixed = fixed.replace(old, new)
    # An en dash is a minus, except in normal text (m:nor), which is what
    # \text{} becomes.
    if "<m:nor" not in props:
        fixed = fixed.replace("\u2013", "\u2212")
    counts["equation_characters"] += sum(a != b for a, b in zip(text, fixed))
    if "\u0177" not in fixed and "\u0176" not in fixed:
        return start + props + t_open + fixed + t_close + end
    parts = []
    for piece in re.split("([\u0176\u0177])", fixed):
        if piece in ("\u0176", "\u0177"):
            letter = "y" if piece == "\u0177" else "Y"
            parts.append(HAT % (start + props + t_open + letter + t_close + end))
            counts["equation_characters"] += 1
        elif piece:
            parts.append(start + props + t_open + piece + t_close + end)
    return "".join(parts)


LIMIT_OPEN = re.compile(r"<m:limUpp>")
LIMIT_TAIL = re.compile(r"</m:e><m:lim><m:r>(?:(?!</m:r>).)*?<m:t(?:\s[^>]*)?>[\u00af\u2013]</m:t>"
                        r"</m:r></m:lim></m:limUpp>", re.S)


def _limit_bars(eq):
    """Each upper limit whose limit is a macron or an en dash, as a bar
    over its base, the base found by counting m:e, since it can hold
    structures of its own (X sub 1). Returns (eq, count)."""
    out, pos, count = [], 0, 0
    for m in LIMIT_OPEN.finditer(eq):
        if m.start() < pos:
            continue
        rest = eq[m.end():]
        head = re.match(r"(?:<m:limUppPr>(?:(?!</m:limUppPr>).)*</m:limUppPr>)?<m:e>", rest, re.S)
        if not head:
            continue
        depth, i = 1, head.end()
        for tag in re.finditer(r"<m:e>|</m:e>", rest[i:]):
            depth += 1 if tag.group(0) == "<m:e>" else -1
            if depth == 0:
                base_end = i + tag.start()
                break
        else:
            continue
        tail = LIMIT_TAIL.match(rest, base_end)
        if not tail:
            continue
        out.append(eq[pos:m.start()])
        out.append(BAR % rest[head.end():base_end])
        pos = m.end() + tail.end()
        count += 1
    out.append(eq[pos:])
    return "".join(out), count


def remediate_equations(xml):
    """The characters of each of Word's equations, as math.repair_equations
    repairs them in the pages: mu for the micro sign, Delta for the
    increment sign, a minus for an en dash, a bar for an upper limit that
    is a macron or an en dash, a hat over y for the one-character y-hat,
    and 0 for a subscript's slashed O. Only inside m:oMath; the text around
    an equation is left to math.from_text. Returns (xml, counts)."""
    counts = {"equations_repaired": 0, "equation_characters": 0}

    def one(m):
        eq = m.group(0)
        fixed, bars = _limit_bars(eq)
        counts["equation_characters"] += bars
        fixed, zeros = SUB_SLASHED_O.subn(r"\g<1>0\g<2>", fixed)
        counts["equation_characters"] += zeros
        fixed = MATH_RUN.sub(lambda r: _repair_run(r, counts), fixed)
        if fixed != eq:
            counts["equations_repaired"] += 1
        return fixed
    xml = re.sub(r"<m:oMath>(?:(?!</m:oMath>).)*</m:oMath>", one, xml, flags=re.S)
    return xml, counts


# Math typed as text, made an equation in the Word file where the filter
# made one in the page (math.from_text). The filter records each one's
# place: the paragraph's text, the equation's text, which occurrence of it,
# and its TeX (MATH_PLACES). Here the paragraph whose runs give that text is
# found, the runs the equation's text spans are replaced by Word's equation
# for the TeX, as Pandoc writes it, and a run the span begins or ends inside
# is split, its formatting kept on what stays text. Only what maps exactly
# is written: a paragraph with tracked changes, a field, a text box, or a
# symbol font is left, and so is a span that crosses a link's edge or holds
# a note reference or a picture. Each place not written is counted.
PLACEHOLDER = "\ufffc"
RUN = re.compile(r"<w:r(?:\s[^>]*)?>((?:(?!</w:r>).)*)</w:r>", re.S)
UNIT = re.compile(r"(<m:oMath>(?:(?!</m:oMath>).)*</m:oMath>)|(<w:r(?:\s[^>]*)?>(?:(?!</w:r>).)*</w:r>)"
                  r"|(<w:hyperlink\b[^>]*>)|(</w:hyperlink>)", re.S)
RUN_PARTS = re.compile(r"(<w:rPr>(?:(?!</w:rPr>).)*</w:rPr>)|<w:t(?:\s[^>]*)?>([^<]*)</w:t>|<w:t\s*/>"
                       r"|(<w:tab\s*/>|<w:br\b[^>]*/>|<w:cr\s*/>)|(<w:lastRenderedPageBreak\s*/>)"
                       r"|(<[^>]+>)", re.S)
UNMAPPABLE = ("<w:del ", "<w:del>", "<w:ins ", "<w:ins>", "<w:fldChar", "<w:instrText",
              "<w:fldSimple", "<w:sym ", "<w:txbxContent", "<w:moveFrom", "<w:moveTo")
KEEP_BETWEEN = re.compile(r"<w:bookmark(?:Start|End)\b[^>]*/>")


def math_places(path):
    """{page: [(number, paragraph, span, occurrence, tex)]} from the rows
    the filter wrote, each once, in order."""
    import csv
    out, seen = {}, set()
    if not path or not os.path.exists(path):
        return out
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.reader(fh):
            if len(row) != 6 or tuple(row) in seen:
                continue
            seen.add(tuple(row))
            page, number, paragraph, span, occurrence, tex = row
            out.setdefault(page, []).append((int(number), paragraph, span,
                                             int(occurrence), tex))
    return out


def _normalize(text):
    """The text with each run of whitespace one space, and none at the
    ends, and for each character kept, its index in text."""
    out, index, space = [], [], False
    for i, ch in enumerate(text):
        if ch.isspace():
            space = bool(out)
            continue
        if space:
            out.append(" ")
            index.append(i - 1)
            space = False
        out.append(ch)
        index.append(i)
    return "".join(out), index


def _units(para):
    """A paragraph's runs and equations in order, each (start, end, text,
    kind, container, run parts), and the paragraph's text."""
    units, container, text = [], 0, []
    for m in UNIT.finditer(para):
        if m.group(3):
            container = m.start()
            continue
        if m.group(4):
            container = 0
            continue
        if m.group(1):
            units.append((m.start(), m.end(), PLACEHOLDER, "math", container, None))
            text.append(PLACEHOLDER)
            continue
        inner = RUN.match(m.group(2)).group(1)
        props, pieces, simple = "", [], True
        for part in RUN_PARTS.finditer(inner):
            if part.group(1):
                props = part.group(1)
            elif part.group(3):
                pieces.append(" ")
                simple = False if simple else simple
            elif part.group(4):
                continue
            elif part.group(2) is not None or re.match(r"<w:t\s*/>", part.group(0)):
                pieces.append(html.unescape(part.group(2) or ""))
            else:
                # A note's reference, a picture, anything else: no text
                # the filter saw, and nothing to take into an equation.
                pieces.append("")
                simple = None
        run_text = "".join(pieces)
        units.append((m.start(), m.end(), run_text, "run", container,
                      (m.group(2)[:m.group(2).index(">") + 1], props, simple)))
        text.append(run_text)
    return units, "".join(text)


def _plain_run(open_tag, props, text):
    return '%s%s<w:t xml:space="preserve">%s</w:t></w:r>' % (open_tag, props,
                                                         html.escape(text, quote=False))


def _place_in(para, spans, omml, counts):
    """The paragraph with each (span, occurrence, tex) made an equation
    where it maps exactly; the others counted as left."""
    units, raw = _units(para)
    norm, index = _normalize(raw)
    # Which unit each character of raw belongs to.
    owner = []
    for n, unit in enumerate(units):
        owner.extend([n] * len(unit[2]))
    edits, taken = [], []
    for span, occurrence, tex in spans:
        start, found = -1, 0
        while found < occurrence:
            start = norm.find(span, start + 1)
            if start < 0:
                break
            found += 1
        equation = omml.get(tex)
        if start < 0 or not equation or not span:
            counts["text_equations_left"] += 1
            continue
        first, last = index[start], index[start + len(span) - 1]
        a, b = owner[first], owner[last]
        covered = units[a:b + 1]
        head_offset = first - sum(len(u[2]) for u in units[:a])
        tail_offset = last - sum(len(u[2]) for u in units[:b]) + 1
        ok = len({u[4] for u in covered}) == 1 and covered[0][4] == 0
        for n, u in enumerate(covered):
            if u[3] == "run":
                simple = u[5][2]
                partial = (n == 0 and head_offset > 0) or (n == len(covered) - 1 and tail_offset < len(u[2]))
                if simple is None or (partial and not simple):
                    ok = False
        # Two places over the same text: neither can be trusted.
        if not ok or any(head_start < covered[-1][1] and covered[0][0] < head_end
                         for head_start, head_end in taken):
            counts["text_equations_left"] += 1
            continue
        taken.append((covered[0][0], covered[-1][1]))
        pieces = []
        head, tail = covered[0], covered[-1]
        if head[3] == "run" and head_offset > 0:
            pieces.append(_plain_run(head[5][0], head[5][1], head[2][:head_offset]))
        pieces.append(equation)
        kept = KEEP_BETWEEN.findall(para[head[1]:tail[0]]) if len(covered) > 1 else []
        pieces.extend(kept)
        if tail[3] == "run" and tail_offset < len(tail[2]):
            pieces.append(_plain_run(tail[5][0], tail[5][1], tail[2][tail_offset:]))
        edits.append((head[0], tail[1], "".join(pieces)))
        counts["text_equations"] += 1
    for start, end, new in sorted(edits, reverse=True):
        para = para[:start] + new + para[end:]
    return para


PARAGRAPH = re.compile(r"<w:p(?:\s[^>]*)?>(?:(?!<w:p[\s>]).)*?</w:p>", re.S)


def remediate_text_math(xml, places, omml):
    """places: [(number, paragraph, span, occurrence, tex)] for this file;
    omml: {tex: Word's equation}. Returns (xml, counts, the numbers of the
    places' paragraphs written or accounted for).

    Paragraphs are matched by their text, with an equation already there
    as a placeholder. When several share a text, the filter's paragraph
    numbers are given to them in order, but only when there are as many of
    them here as the filter recorded; otherwise none is written, since
    which equation belongs where can't be told."""
    counts = {"text_equations": 0, "text_equations_left": 0}
    by_text = {}
    for number, paragraph, span, occurrence, tex in places:
        by_text.setdefault(paragraph, {}).setdefault(number, []).append((span, occurrence, tex))
    texts = [_normalize(_units(m.group(0))[1])[0] for m in PARAGRAPH.finditer(xml)]
    present = {}
    for t in texts:
        present[t] = present.get(t, 0) + 1
    seen_here, done = {}, set()
    out, pos = [], 0
    for m, norm in zip(PARAGRAPH.finditer(xml), texts):
        numbers = by_text.get(norm)
        if not numbers:
            continue
        k = seen_here.get(norm, 0)
        seen_here[norm] = k + 1
        ordered = sorted(numbers)
        if present[norm] != len(ordered):
            if k == 0:
                counts["text_equations_left"] += sum(len(v) for v in numbers.values())
                done.update(ordered)
            continue
        number = ordered[k]
        spans = numbers[number]
        done.add(number)
        para = m.group(0)
        if any(marker in para for marker in UNMAPPABLE):
            counts["text_equations_left"] += len(spans)
            continue
        new = _place_in(para, spans, omml, counts)
        out.append(xml[pos:m.start()])
        out.append(new)
        pos = m.end()
    out.append(xml[pos:])
    return "".join(out), counts, done


def equations_for(texs):
    """{tex: Word's equation for it}, as Pandoc writes each, in one run."""
    import subprocess
    texs = [t for t in dict.fromkeys(texs) if t]
    if not texs:
        return {}
    source = "\n\n".join("$%s$" % t for t in texs) + "\n"
    handle, path = tempfile.mkstemp(suffix=".docx")
    os.close(handle)
    try:
        result = subprocess.run(["pandoc", "-f", "markdown", "-t", "docx", "-o", path],
                                input=source, text=True, capture_output=True)
        if result.returncode != 0:
            return {}
        with zipfile.ZipFile(path) as z:
            document = z.read("word/document.xml").decode("utf-8")
    finally:
        os.remove(path)
    body = document[document.index("<w:body>"):]
    paras = re.findall(r"<w:p(?:\s[^>]*)?>(?:(?!</w:p>).)*</w:p>", body, re.S)
    out = {}
    for tex, para in zip(texs, paras):
        found = re.findall(r"<m:oMath>(?:(?!</m:oMath>).)*</m:oMath>", para, re.S)
        if len(found) == 1:
            out[tex] = found[0]
    return out


def replace_links(xml, rels, replacements):
    """replacements: {address: replacement}. Each relationship to one gets
    the replacement; each hyperlink using it whose text is the address
    gets the replacement as its text, in its first run. Returns (xml,
    rels, count)."""
    if not replacements:
        return xml, rels, 0
    changed = {}

    def rel(m):
        target = html.unescape(m.group(2))
        if target in replacements and 'TargetMode="External"' in m.group(0):
            changed[m.group(1)] = (target, replacements[target])
            return m.group(0).replace('Target="%s"' % m.group(2),
                                      'Target="%s"' % html.escape(replacements[target], quote=True))
        return m.group(0)
    rels = re.sub(r'<Relationship\b[^>]*?Id="([^"]+)"[^>]*?Target="([^"]*)"[^>]*/>', rel, rels)
    count = 0

    def link(m):
        nonlocal count
        rid = re.search(r'r:id="([^"]+)"', m.group(1))
        if not rid or rid.group(1) not in changed:
            return m.group(0)
        address, replacement = changed[rid.group(1)]
        body = m.group(2)
        if _text(body) != address:
            return m.group(0)
        seen = []

        def text(t):
            seen.append(1)
            return "%s%s</w:t>" % (t.group(1), html.escape(replacement, quote=False) if len(seen) == 1 else "")
        count += 1
        return m.group(1) + re.sub(r"(<w:t(?:\s[^>]*)?>)[^<]*</w:t>", text, body) + "</w:hyperlink>"
    xml = re.sub(r"(<w:hyperlink\b[^>]*>)(.*?)</w:hyperlink>", link, xml, flags=re.S)
    return xml, rels, count


def remediate_language(styles, language):
    """The document's default language, when styles.xml declares none.
    Returns (styles, 1 or 0)."""
    if not language or "<w:docDefaults>" not in styles:
        return styles, 0
    defaults = re.search(r"<w:docDefaults>.*?</w:docDefaults>", styles, re.S)
    if re.search(r"<w:lang\b", defaults.group(0)):
        return styles, 0
    lang = '<w:lang w:val="%s"/>' % html.escape(language, quote=True)
    block = defaults.group(0)
    if re.search(r"<w:rPrDefault>\s*<w:rPr>", block):
        rpr = re.search(r"<w:rPrDefault>\s*<w:rPr>(.*?)</w:rPr>", block, re.S)
        inner = rpr.group(1)
        # Before the few elements CT_RPr puts after lang.
        after = re.search(r"<w:(?:eastAsianLayout|specVanish|oMath)\b", inner)
        cut = after.start() if after else len(inner)
        new_block = block[:rpr.start(1)] + inner[:cut] + lang + inner[cut:] + block[rpr.end(1):]
    elif "<w:rPrDefault/>" in block or "<w:rPrDefault />" in block:
        new_block = re.sub(r"<w:rPrDefault\s*/>", "<w:rPrDefault><w:rPr>%s</w:rPr></w:rPrDefault>" % lang,
                           block, count=1)
    else:
        new_block = block.replace("<w:docDefaults>",
                                  "<w:docDefaults><w:rPrDefault><w:rPr>%s</w:rPr></w:rPrDefault>" % lang, 1)
    return styles.replace(block, new_block, 1), 1


def remediate_links(xml, rels, titles):
    """titles: {address: title}. Each hyperlink to one gets its ScreenTip.
    Returns (xml, count)."""
    if not titles:
        return xml, 0
    targets = {m.group(1): html.unescape(m.group(2)) for m in re.finditer(
        r'<Relationship\b[^>]*?Id="([^"]+)"[^>]*?Target="([^"]*)"', rels)}
    count = 0

    def one(m):
        nonlocal count
        tag = m.group(0)
        rid = re.search(r'r:id="([^"]+)"', tag)
        title = titles.get(targets.get(rid.group(1), "")) if rid else None
        if not title or "w:tooltip=" in tag:
            return tag
        count += 1
        return tag[:-1] + ' w:tooltip="%s">' % html.escape(title, quote=True)
    return re.sub(r"<w:hyperlink\b[^>]*>", one, xml), count


# ---------------------------------------------------------------------------
# The file
# ---------------------------------------------------------------------------

def remediate(source, destination, tables=None, alts=None, titles=None, compat=False,
              guesses=False, captions=None, replacements=None, language=None,
              headings="keep", deletions="accept", equations=False, places=None):
    """Write destination, a copy of source with the decisions applied.
    tables: the pre-pass's resolved list for this file; alts: {relationship
    id: alt or None}; titles: {address: title}; equations: repair the
    characters of Word's equations (math.repair_equations). Returns a dict
    of counts."""
    counts = {"compat": 0, "links": 0, "equations_repaired": 0,
              "equation_characters": 0, "text_equations": 0,
              "text_equations_left": 0}
    with zipfile.ZipFile(source) as z:
        infos = z.infolist()
        parts = {i.filename: z.read(i.filename) for i in infos}
    text = lambda n: parts[n].decode("utf-8")
    changed = set()
    if "word/document.xml" in parts:
        xml = text("word/document.xml")
        new, found = remediate_tables(xml, tables or [], guesses)
        counts.update(found)
        new, found = remediate_captions(new, captions or [], tables or [])
        counts.update(found)
        new, found = remediate_images(new, alts or {})
        counts.update(found)
        rels_name = "word/_rels/document.xml.rels"
        rels = text(rels_name) if rels_name in parts else ""
        new, counts["links"] = remediate_links(new, rels, titles or {})
        new, new_rels, counts["replaced"] = replace_links(new, rels, replacements or {})
        if new_rels != rels:
            parts[rels_name] = new_rels.encode("utf-8")
            changed.add(rels_name)
        if new != xml:
            parts["word/document.xml"] = new.encode("utf-8")
            changed.add("word/document.xml")
    # Equations are in notes too. Text made equations first: the places
    # were recorded against the text as the source has it.
    omml = equations_for([tex for _, _, _, _, tex in places or []])
    matched = set()
    for name in ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml"):
        if places and name in parts:
            xml = text(name)
            new, found, seen = remediate_text_math(xml, places, omml)
            counts["text_equations"] += found["text_equations"]
            counts["text_equations_left"] += found["text_equations_left"]
            matched |= seen
            if new != xml:
                parts[name] = new.encode("utf-8")
                changed.add(name)
        if equations and name in parts:
            xml = text(name)
            new, found = remediate_equations(xml)
            for key, n in found.items():
                counts[key] += n
            if new != xml:
                parts[name] = new.encode("utf-8")
                changed.add(name)
    # A place no paragraph of any part matched is left too.
    counts["text_equations_left"] += sum(1 for number, _, _, _, _ in places or []
                                         if number not in matched)
    if "word/styles.xml" in parts:
        styles = text("word/styles.xml")
        new_styles, counts["language"] = remediate_language(styles, language)
        if counts.get("captions") and 'w:styleId="Caption"' not in new_styles:
            new_styles = new_styles.replace("</w:styles>", CAPTION_STYLE + "</w:styles>", 1)
        if new_styles != styles:
            parts["word/styles.xml"] = new_styles.encode("utf-8")
            changed.add("word/styles.xml")
    # The book's word.headings and word.tracked_deletions, last: striking
    # a deletion changes a cell's text, and a table is matched by its
    # first cell as the pre-pass read it.
    import wordrepairs
    repaired, found, _ = wordrepairs.apply(parts, headings, deletions)
    changed |= repaired
    counts["restyled"], counts["deletions_struck"] = found["restyled"], found["deletions"]
    if compat and "word/settings.xml" in parts:
        new = docxtarget.compat_mode(text("word/settings.xml"))
        if new != text("word/settings.xml"):
            parts["word/settings.xml"] = new.encode("utf-8")
            changed.add("word/settings.xml")
            counts["compat"] = 1
    handle, temporary = tempfile.mkstemp(suffix=".docx", dir=os.path.dirname(os.path.abspath(destination)))
    os.close(handle)
    with zipfile.ZipFile(temporary, "w") as out:
        for info in infos:
            out.writestr(info, parts[info.filename])
    shutil.move(temporary, destination)
    counts["parts_changed"] = len(changed)
    return counts
