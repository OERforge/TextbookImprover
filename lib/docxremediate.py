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
              headings="keep", deletions="accept"):
    """Write destination, a copy of source with the decisions applied.
    tables: the pre-pass's resolved list for this file; alts: {relationship
    id: alt or None}; titles: {address: title}. Returns a dict of counts."""
    counts = {"compat": 0, "links": 0}
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
