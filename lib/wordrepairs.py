"""Repairs of an author's Word file that change what it means to read it:
its heading styles, and its tracked deletions. Each is decided once, by a
setting (word.headings, word.tracked_deletions), and applied both to the
copy the pipeline reads and, with a source target, to the author's
remediated copy, so the book and the file agree. util/restyle-headings.py
and util/untrack-deletions.py are command lines over the same code.

The XML is edited as text; nothing is parsed and written again.

Copyright 2026 Robert Szarka
"""

import collections
import re

# ---------------------------------------------------------------------------
# Heading styles (from util/restyle-headings.py)
# ---------------------------------------------------------------------------

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
            raise ValueError(f"{pair!r} is not FROM=TO")
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



def heading_map(parts, setting):
    """The style map a word.headings value gives one file, as {from: to},
    keeping only styles the file uses. Returns (map or None, problem or
    None): None for keep, a problem for a file the setting can't apply to,
    which is then left as it is."""
    setting = (setting or "keep").strip()
    if setting == "keep":
        return None, None
    styles, names = paragraph_styles(parts)
    body = parts.get("word/document.xml", b"").decode("utf-8", "replace")
    found, _ = count_styles(body)
    if setting == "from-toc":
        levels = toc_mapping(body, names)
        if not levels:
            return None, "no TOC field declares its heading levels"
        mapping = map_from_levels(levels)
    else:
        try:
            mapping = parse_map(setting)
        except ValueError as problem:
            return None, f"word.headings: {problem}"
    mapping = {a: b for a, b in mapping.items() if a in found and a != b}
    missing = sorted(b for b in set(mapping.values()) if b not in styles)
    if missing:
        return None, ("it doesn't define " + ", ".join(missing) + "; Word defines a "
                      "heading style once it's used, so apply it to one paragraph in "
                      "Word and save")
    return (mapping or None), None


# ---------------------------------------------------------------------------
# Tracked deletions (from util/untrack-deletions.py)
# ---------------------------------------------------------------------------

DEL_RE = re.compile(r"<w:del(?: [^>]*)?>(.*?)</w:del>", re.S)
RUN_RE = re.compile(r"<w:r(?: [^>]*)?>.*?</w:r>", re.S)
RPR_RE = re.compile(r"<w:rPr(?: [^>]*)?>", re.S)


def strike_run(run):
    """Add <w:strike/> to a run and turn its delText back into ordinary text."""
    # <w:delText> is the deleted-text element; only valid inside <w:del>.
    run = run.replace("<w:delText", "<w:t").replace("</w:delText>", "</w:t>")

    if "<w:strike/>" in run or "<w:strike " in run:
        return run

    m = RPR_RE.search(run)
    if m:
        # w:strike belongs in the run properties, where order is loose
        # enough that appending directly after the opening tag is safe.
        return run[:m.end()] + "<w:strike/>" + run[m.end():]

    # No properties yet. They must be the first child of <w:r>.
    open_tag = re.match(r"<w:r(?: [^>]*)?>", run)
    return (run[:open_tag.end()] + "<w:rPr><w:strike/></w:rPr>"
            + run[open_tag.end():])


def strike_deletions(xml):
    """Each tracked deletion holding text made ordinary struck-through runs.
    Returns (xml, counts)."""
    counts = {"deletions": 0, "runs": 0, "words": 0}

    def replace(match):
        inner = match.group(1)
        if "<w:delText" not in inner:
            # A deleted paragraph mark or similar: no text to preserve, so
            # accepting it is the right outcome and it is left alone.
            return match.group(0)

        counts["deletions"] += 1
        for text in re.findall(r"<w:delText[^>]*>(.*?)</w:delText>", inner, re.S):
            counts["words"] += len(text.split())

        def fix(run_match):
            counts["runs"] += 1
            return strike_run(run_match.group(0))

        return RUN_RE.sub(fix, inner)

    return DEL_RE.sub(replace, xml), counts



def count_deletions(xml):
    """How many tracked deletions hold text."""
    return sum(1 for m in DEL_RE.finditer(xml) if "<w:delText" in m.group(1))


# ---------------------------------------------------------------------------
# Both
# ---------------------------------------------------------------------------

def apply(parts, headings="keep", deletions="accept"):
    """The repairs the settings call for, on a file's parts ({name: bytes}),
    in place. Returns (names changed, counts, problem or None)."""
    changed, counts = set(), {"restyled": 0, "dropped": 0, "deletions": 0}
    mapping, problem = heading_map(parts, headings)
    for name in list(parts):
        if mapping and PARTS.match(name):
            text, restyled, dropped = restyle(parts[name].decode("utf-8"), mapping, False)
            if restyled or dropped:
                parts[name] = text.encode("utf-8")
                changed.add(name)
                counts["restyled"] += sum(restyled.values())
                counts["dropped"] += sum(dropped.values())
    if deletions == "strike" and "word/document.xml" in parts:
        text, found = strike_deletions(parts["word/document.xml"].decode("utf-8"))
        if found["deletions"]:
            parts["word/document.xml"] = text.encode("utf-8")
            changed.add("word/document.xml")
            counts["deletions"] = found["deletions"]
    return changed, counts, problem
