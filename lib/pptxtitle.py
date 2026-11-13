"""
pptxtitle.py -- a heading a slide already shows, made the slide's title in
place, as PowerPoint's Set as Slide Title makes it.

A slide's title, to PowerPoint, a screen reader, and a conversion, is what
its title placeholder holds. A deck whose layouts have no title
placeholder puts each slide's heading in a body placeholder or a text box,
which looks like a title and isn't one; a hidden title above such a slide
would have the heading read twice. PowerPoint's Accessibility pane offers
Set as Slide Title for it, which "makes the selected object your slide
title" (https://support.microsoft.com/en-us/powerpoint/title-a-slide).

What it writes, measured on five slides of a deck it was used on, three
headings in body placeholders and two in text boxes: the shape keeps its
id, name, position, text, and place in the tree; its placeholder becomes
<p:ph type="title" idx="4294967295"/> (a text box's added, with its lock
noGrp="1"); and everything its text inherited is written onto it, since a
title inherits the master's title style instead, which can align and size
it otherwise. PowerPoint writes it out on every paragraph and run; this
writes it into the shape's own list style, which every paragraph and run
inherits before anything else, and which keeps their own formatting as it
was. On those five slides, every paragraph's and run's properties came out
as PowerPoint's did, and as the heading's had been, and so did the text
body's and the shape's.

What the shape inherits is read from its chain: a placeholder's from the
layout's placeholder it matches (by idx, else by type), the master's of
its type, and the master's body style (the title style for a title, the
other style for a date, footer, or slide number), on the presentation's
default text style; a text box's from the presentation's default text
style, which in every deck measured was the master's other style too.
Every property that chain sets is written, and every property the title's
chain sets that it doesn't, as its default. One neither sets is left out,
where PowerPoint writes it too: it's the default either way, and a program
with defaults of its own keeps them. LibreOffice's insets for a text body
that gives none are 0.25 cm and 0.125 cm, where PowerPoint's are 0.254 cm
and 0.127 cm; written out, they moved a heading's glyphs there by a
fraction of a pixel. Left out, the slides of the decks measured rendered
in LibreOffice as they had, pixel for pixel, but for those whose title had
a number added, and a text box LibreOffice now reads as a frame and not a
shape.

A shape PowerPoint draws takes its fill, outline, effects, fonts, and
text color from the theme's styles (p:style), which a title placeholder's
inherited fill and outline, and the master's title style, would come
before. Made a title by PowerPoint, such a shape kept its p:style and had
the theme's entries it refers to written out as its own fill, outline, and
effects, and its fonts and color on every run (theme_style()); this writes
them so too, the fonts and color into its list style. On the slide
PowerPoint converted, the shape's fill, outline, and effects came out as
PowerPoint wrote them, element for element, every run as PowerPoint's,
and in LibreOffice the slide rendered as PowerPoint's did, pixel for
pixel. A deck whose master has no theme, or a style the theme hasn't the
entries for, leaves the shape as it is.

The XML is edited as text, never parsed and written again: the elements
copied from a layout, a master, the presentation, or the theme are copied
as they're written there.

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
from collections import Counter, OrderedDict

# A start tag's attributes, quoted values allowed to hold ">".
ATTRS = r"((?:\s+[\w:.-]+\s*=\s*(?:\"[^\"]*\"|'[^']*'))*)\s*"
TAG = re.compile(r"<(/?)([\w.-]+(?::[\w.-]+)?)%s(/?)>" % ATTRS)
ATTR = re.compile(r"""([\w:.-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
TITLE_PH = '<p:ph type="title" idx="4294967295"/>'
# The placeholder types a master's body style formats, and those its other
# style does; a title's is its title style.
OTHER_TYPES = ("dt", "ftr", "sldNum", "hdr")
TITLE_TYPES = ("title", "ctrTitle")


# --------------------------------------------------------------------------
# Elements in text

def element_end(xml, start):
    """The index just past the element whose start tag begins at start."""
    depth = 0
    for tag in TAG.finditer(xml, start):
        if tag.group(1):
            depth -= 1
        elif not tag.group(4):
            depth += 1
        if depth == 0:
            return tag.end()
    raise ValueError("an element with no end")


def children(xml, start=0, end=None):
    """[(name, start, end)] of the direct children of the element whose
    start tag begins at start, or of the top level of xml[start:end] when
    end is given."""
    out = []
    if end is None:
        first = TAG.match(xml, start)
        if first is None or first.group(4):
            return out
        end = element_end(xml, start) - len("</%s>" % first.group(2))
        pos = first.end()
    else:
        pos = start
    while True:
        tag = TAG.search(xml, pos, end)
        if tag is None or tag.group(1):
            return out
        stop = tag.end() if tag.group(4) else element_end(xml, tag.start())
        out.append((tag.group(2), tag.start(), stop))
        pos = stop


def child(xml, start, name):
    """(start, end) of the first direct child named name, or None."""
    for found, s, e in children(xml, start):
        if found == name:
            return s, e
    return None


def attributes(start_tag):
    """OrderedDict of a start tag's attributes."""
    match = TAG.match(start_tag)
    return OrderedDict((m.group(1), m.group(2) if m.group(2) is not None else m.group(3))
                       for m in ATTR.finditer(match.group(3) if match else ""))


def _start(name, attrs, empty=False, order=()):
    """A start tag; attrs' values as they were read from the XML, escaped
    already but for a double quote a single-quoted value can hold; those
    in order first, in that order."""
    names = [k for k in order if k in attrs] + [k for k in attrs if k not in order]
    return "<%s%s%s>" % (name, "".join(' %s="%s"' % (k, attrs[k].replace('"', "&quot;"))
                                       for k in names), "/" if empty else "")


# --------------------------------------------------------------------------
# Properties, by the groups the schema allows one of

# A paragraph's (or a list-style level's) child elements, and a run's, by
# group: one of each group is in force, the nearest one in the chain.
P_GROUPS = OrderedDict([
    ("a:lnSpc", "lnSpc"), ("a:spcBef", "spcBef"), ("a:spcAft", "spcAft"),
    ("a:buClrTx", "buClr"), ("a:buClr", "buClr"),
    ("a:buSzTx", "buSz"), ("a:buSzPct", "buSz"), ("a:buSzPts", "buSz"),
    ("a:buFontTx", "buFont"), ("a:buFont", "buFont"),
    ("a:buNone", "bu"), ("a:buAutoNum", "bu"), ("a:buChar", "bu"), ("a:buBlip", "bu"),
    ("a:tabLst", "tabLst"), ("a:extLst", "extLst")])
P_ORDER = ["lnSpc", "spcBef", "spcAft", "buClr", "buSz", "buFont", "bu", "tabLst", "defRPr",
           "extLst"]
R_GROUPS = OrderedDict([
    ("a:ln", "ln"), ("a:noFill", "fill"), ("a:solidFill", "fill"), ("a:gradFill", "fill"),
    ("a:blipFill", "fill"), ("a:pattFill", "fill"), ("a:grpFill", "fill"),
    ("a:effectLst", "effect"), ("a:effectDag", "effect"), ("a:highlight", "highlight"),
    ("a:uLnTx", "uLn"), ("a:uLn", "uLn"), ("a:uFillTx", "uFill"), ("a:uFill", "uFill"),
    ("a:latin", "latin"), ("a:ea", "ea"), ("a:cs", "cs"), ("a:sym", "sym"),
    ("a:hlinkClick", "hlinkClick"), ("a:hlinkMouseOver", "hlinkMouseOver"), ("a:rtl", "rtl"),
    ("a:extLst", "extLst")])
R_ORDER = ["ln", "fill", "effect", "highlight", "uLn", "uFill", "latin", "ea", "cs", "sym",
           "hlinkClick", "hlinkMouseOver", "rtl", "extLst"]
B_GROUPS = OrderedDict([
    ("a:prstTxWarp", "prstTxWarp"), ("a:noAutofit", "autofit"), ("a:normAutofit", "autofit"),
    ("a:spAutoFit", "autofit"), ("a:scene3d", "scene3d"), ("a:sp3d", "sp3d"),
    ("a:flatTx", "flatTx"), ("a:extLst", "extLst")])
B_ORDER = ["prstTxWarp", "autofit", "scene3d", "sp3d", "flatTx", "extLst"]
S_GROUPS = OrderedDict([
    ("a:xfrm", "xfrm"), ("a:custGeom", "geom"), ("a:prstGeom", "geom"),
    ("a:noFill", "fill"), ("a:solidFill", "fill"), ("a:gradFill", "fill"), ("a:blipFill", "fill"),
    ("a:pattFill", "fill"), ("a:grpFill", "fill"), ("a:ln", "ln"), ("a:effectLst", "effect"),
    ("a:effectDag", "effect"), ("a:scene3d", "scene3d"), ("a:sp3d", "sp3d"),
    ("a:extLst", "extLst")])
S_ORDER = ["xfrm", "geom", "fill", "ln", "effect", "scene3d", "sp3d", "extLst"]

# Attributes in the schema's order, as PowerPoint writes them.
P_ATTRS = ("marL", "marR", "lvl", "indent", "algn", "defTabSz", "rtl", "eaLnBrk", "fontAlgn",
           "latinLnBrk", "hangingPunct")
R_ATTRS = ("kumimoji", "lang", "altLang", "sz", "b", "i", "u", "strike", "kern", "cap", "spc",
           "normalizeH", "baseline", "noProof", "dirty", "err", "smtClean", "smtId", "bmk")
B_ATTRS = ("rot", "spcFirstLastPara", "vertOverflow", "horzOverflow", "vert", "wrap", "lIns",
           "tIns", "rIns", "bIns", "numCol", "spcCol", "rtlCol", "fromWordArt", "anchor",
           "anchorCtr", "forceAA", "upright", "compatLnSpc")

# What a property is when nothing in a chain sets it, written where the
# title's chain sets one that the shape's own doesn't: the values
# PowerPoint wrote for such properties.
P_ATTR_DEFAULTS = OrderedDict([
    ("marL", "0"), ("marR", "0"), ("indent", "0"), ("algn", "l"), ("defTabSz", "914400"),
    ("rtl", "0"), ("eaLnBrk", "1"), ("fontAlgn", "auto"), ("latinLnBrk", "0"),
    ("hangingPunct", "1")])
P_GROUP_DEFAULTS = {
    "lnSpc": '<a:lnSpc><a:spcPct val="100000"/></a:lnSpc>',
    "spcBef": '<a:spcBef><a:spcPts val="0"/></a:spcBef>',
    "spcAft": '<a:spcAft><a:spcPts val="0"/></a:spcAft>',
    "buClr": "<a:buClrTx/>", "buSz": "<a:buSzTx/>", "buFont": "<a:buFontTx/>",
    "bu": "<a:buNone/>", "tabLst": "<a:tabLst/>"}
R_ATTR_DEFAULTS = OrderedDict([
    ("kumimoji", "0"), ("sz", "1800"), ("b", "0"), ("i", "0"), ("u", "none"),
    ("strike", "noStrike"), ("kern", "0"), ("cap", "none"), ("spc", "0"), ("normalizeH", "0"),
    ("baseline", "0"), ("noProof", "0")])
R_GROUP_DEFAULTS = {
    "ln": "<a:ln><a:noFill/></a:ln>", "fill": '<a:solidFill><a:schemeClr val="tx1"/></a:solidFill>',
    "effect": "<a:effectLst/>", "uLn": "<a:uLnTx/>", "uFill": "<a:uFillTx/>",
    "latin": '<a:latin typeface="+mn-lt"/>', "ea": '<a:ea typeface="+mn-ea"/>',
    "cs": '<a:cs typeface="+mn-cs"/>'}
B_ATTR_DEFAULTS = OrderedDict([
    ("rot", "0"), ("spcFirstLastPara", "0"), ("vertOverflow", "overflow"),
    ("horzOverflow", "overflow"), ("vert", "horz"), ("wrap", "square"), ("lIns", "91440"),
    ("tIns", "45720"), ("rIns", "91440"), ("bIns", "45720"), ("numCol", "1"), ("spcCol", "0"),
    ("rtlCol", "0"), ("fromWordArt", "0"), ("anchor", "t"), ("anchorCtr", "0"), ("forceAA", "0"),
    ("upright", "0"), ("compatLnSpc", "1")])
B_GROUP_DEFAULTS = {"prstTxWarp": '<a:prstTxWarp prst="textNoShape"><a:avLst/></a:prstTxWarp>',
                    "autofit": "<a:noAutofit/>"}
S_DEFAULTS = {"geom": '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>', "fill": "<a:noFill/>",
              "ln": "<a:ln><a:noFill/><a:prstDash/></a:ln>", "effect": "<a:effectLst/>"}


class Props:
    """An element's properties: its attributes, and its children by group,
    each child as it's written; a list-style level also its run defaults,
    another Props."""

    __slots__ = ("attrs", "groups", "run")

    def __init__(self):
        self.attrs, self.groups, self.run = OrderedDict(), OrderedDict(), None

    @classmethod
    def read(cls, xml, start, groups, run_tag=None, run_groups=None):
        """The properties of the element whose start tag begins at start."""
        props = cls()
        props.attrs = attributes(TAG.match(xml, start).group(0))
        for name, s, e in children(xml, start):
            if run_tag and name == run_tag:
                props.run = cls.read(xml, s, run_groups)
            elif name in groups:
                props.groups[groups[name]] = xml[s:e]
        return props

    def over(self, lower):
        """These properties laid over lower's: each attribute and group
        this one sets wins, and lower's others stay."""
        merged = Props()
        merged.attrs = OrderedDict(lower.attrs)
        merged.attrs.update(self.attrs)
        merged.groups = OrderedDict(lower.groups)
        merged.groups.update(self.groups)
        if self.run is not None or lower.run is not None:
            merged.run = (self.run or Props()).over(lower.run or Props())
        return merged

    def fill_in(self, other, attr_defaults, group_defaults, run_attr_defaults=None,
                run_group_defaults=None):
        """Each attribute and group other sets that this doesn't, given its
        default here, so that other's can't come through."""
        for name in other.attrs:
            if name not in self.attrs and name in attr_defaults:
                self.attrs[name] = attr_defaults[name]
        for name in other.groups:
            if name not in self.groups and name in group_defaults:
                self.groups[name] = group_defaults[name]
        if other.run is not None and run_attr_defaults is not None:
            if self.run is None:
                self.run = Props()
            self.run.fill_in(other.run, run_attr_defaults, run_group_defaults)
        return self

    def empty(self):
        return not self.attrs and not self.groups and (self.run is None or self.run.empty())

    def write(self, name, order, run_tag=None, run_order=None, attr_order=(),
              run_attr_order=()):
        """The element, its attributes in the schema's order where they have
        one, and its children in the schema's order."""
        body = []
        for group in order:
            if group == "defRPr" and run_tag:
                if self.run is not None and not self.run.empty():
                    body.append(self.run.write(run_tag, run_order, attr_order=run_attr_order))
            elif group in self.groups:
                body.append(self.groups[group])
        if not body:
            return _start(name, self.attrs, empty=True, order=attr_order)
        return _start(name, self.attrs, order=attr_order) + "".join(body) + "</%s>" % name


def _level(xml, start):
    return Props.read(xml, start, P_GROUPS, "a:defRPr", R_GROUPS)


def list_levels(xml, start):
    """{1..9: Props} of a list style (an a:lstStyle, or a master's or the
    presentation's text style) whose start tag begins at start; a:defPPr,
    which every level inherits, laid under each."""
    levels, default = {}, None
    for name, s, _e in children(xml, start):
        found = re.match(r"a:lvl(\d)pPr$", name)
        if found:
            levels[int(found.group(1))] = _level(xml, s)
        elif name == "a:defPPr":
            default = _level(xml, s)
    if default is not None:
        for n in range(1, 10):
            levels[n] = levels[n].over(default) if n in levels else default
    return levels


def chain(lists):
    """{level: Props} of list styles laid one over another, the first
    lowest."""
    out = {}
    for levels in lists:
        for n, props in levels.items():
            out[n] = props.over(out[n]) if n in out else props
    return out


# --------------------------------------------------------------------------
# Where a shape's text gets what it inherits

def _shape_tree(xml):
    match = re.search(r"<p:spTree\b", xml)
    return match.start() if match else None


def placeholders(xml):
    """[(type, idx, start)] of the placeholder shapes at the top of a
    layout's or a master's shape tree; type obj when it names none."""
    tree = _shape_tree(xml)
    out = []
    if tree is None:
        return out
    for name, s, _e in children(xml, tree):
        if name != "p:sp":
            continue
        ph = re.search(r"<p:ph\b%s/?>" % ATTRS, xml[s:element_end(xml, s)])
        if ph is None:
            continue
        attrs = attributes(ph.group(0))
        out.append((attrs.get("type", "obj"), attrs.get("idx"), s))
    return out


def matching(xml, ph_type, idx):
    """The start of a layout's or master's placeholder a slide's matches:
    by idx when it has one that's found, else by type; a title, a body,
    or another placeholder of the kind its type falls in."""
    found = placeholders(xml) if xml else []
    if idx is not None and ph_type not in TITLE_TYPES:
        for t, i, s in found:
            if i == idx:
                return s
    kind = _kind(ph_type)
    for t, _i, s in found:
        if t == ph_type:
            return s
    for t, _i, s in found:
        if _kind(t) == kind and kind != "other":
            return s
    return None


def _kind(ph_type):
    if ph_type in TITLE_TYPES:
        return "title"
    if ph_type in OTHER_TYPES:
        return "other"
    return "body"


def _sub(xml, start, path):
    """(start, end) of the element reached from start through the named
    children in turn, or None."""
    span = (start, element_end(xml, start))
    for name in path:
        span = child(xml, span[0], name) if span else None
        if span is None:
            return None
    return span


def _lst(xml, start):
    """{level: Props} of a placeholder shape's own list style."""
    if xml is None or start is None:
        return {}
    span = _sub(xml, start, ["p:txBody", "a:lstStyle"])
    return list_levels(xml, span[0]) if span else {}


def _body(xml, start):
    if xml is None or start is None:
        return Props()
    span = _sub(xml, start, ["p:txBody", "a:bodyPr"])
    return Props.read(xml, span[0], B_GROUPS) if span else Props()


def _sppr(xml, start):
    if xml is None or start is None:
        return Props()
    span = _sub(xml, start, ["p:spPr"])
    return Props.read(xml, span[0], S_GROUPS) if span else Props()


# --------------------------------------------------------------------------
# A shape's look from the theme's styles (p:style)
#
# A shape PowerPoint draws refers to the theme's formatting scheme for its
# fill, outline, and effects, each by its place in the scheme's list and a
# color to put for the list entry's placeholder color (phClr), and to its
# major or minor fonts and a color for its text (ECMA-376 Part 1,
# 20.1.4.2.10 to 20.1.4.2.13 and 20.1.4.1.17, fmtScheme). Made a title in
# PowerPoint (Set as Slide Title, 2026-11-13), such a shape kept its
# p:style and had what it refers to written out on it: the third fill
# style, the first line style, and the second effect style's effect list,
# each with its phClr made the reference's color and phClr's own tint,
# shade, and saturation kept, as the shape's own fill, outline, and
# effects; and the minor fonts and the font reference's color on each run.
# A title placeholder's inherited fill and outline, and the master's title
# style, would otherwise come before them.

PH_COLOR = re.compile(r'<a:schemeClr val="phClr"\s*(?:/>|>(.*?)</a:schemeClr>)', re.S)
# A reference's place, as fmtScheme numbers it: 0 none, 1 to 999 the
# fill, line, or effect list's, 1001 on the background fills'.
STYLE_LISTS = {"fill": ("a:fillStyleLst", "a:bgFillStyleLst"),
               "ln": ("a:lnStyleLst", None), "effect": ("a:effectStyleLst", None)}
STYLE_NONE = {"fill": "<a:noFill/>", "ln": "<a:ln><a:noFill/></a:ln>",
              "effect": "<a:effectLst/>"}
FONT_REFS = {"major": "mj", "minor": "mn"}


def _color(xml, start):
    """(name, attributes' text, children's text) of a reference's color,
    its one child, or None."""
    for name, s, e in children(xml, start):
        tag = TAG.match(xml, s)
        inner = "" if tag.group(4) else xml[tag.end():e - len("</%s>" % name)]
        return name, tag.group(3), inner
    return None


def _placed(entry, color):
    """A style list's entry with each phClr made the color: the color's
    own children first, then phClr's."""
    if color is None:
        return entry
    name, attrs, inner = color

    def put(match):
        mods = inner + (match.group(1) or "")
        return "<%s%s/>" % (name, attrs) if not mods else "<%s%s>%s</%s>" % (name, attrs, mods,
                                                                              name)
    return PH_COLOR.sub(put, entry)


def theme_style(sp, theme):
    """(shape Props, run Props) of what a shape's p:style refers to in the
    theme's formatting scheme: fill, outline, and effects (with an effect
    style's 3-D scene and shape), and fonts and color for its text; None
    when it has no p:style, or one the theme doesn't have the entries for."""
    style = _sub(sp, 0, ["p:style"])
    if style is None:
        return None
    scheme = re.search(r"<a:fmtScheme\b", theme or "")
    if scheme is None:
        return None
    shape, run = Props(), Props()
    for ref, group in (("a:fillRef", "fill"), ("a:lnRef", "ln"), ("a:effectRef", "effect")):
        span = child(sp, style[0], ref)
        if span is None:
            return None
        idx = attributes(TAG.match(sp, span[0]).group(0)).get("idx", "")
        if not idx.isdigit():
            return None
        n = int(idx)
        if n == 0:
            shape.groups[group] = STYLE_NONE[group]
            continue
        listed, background = STYLE_LISTS[group]
        if n > 1000:
            listed, n = background, n - 1000
        lst = child(theme, scheme.start(), listed) if listed else None
        entries = children(theme, lst[0]) if lst else []
        if n > len(entries):
            return None
        _name, s, e = entries[n - 1]
        entry = _placed(theme[s:e], _color(sp, span[0]))
        if group != "effect":
            shape.groups[group] = entry
            continue
        for name, es, ee in children(entry, 0):
            if name in S_GROUPS and S_GROUPS[name] in ("effect", "scene3d", "sp3d"):
                shape.groups[S_GROUPS[name]] = entry[es:ee]
    span = child(sp, style[0], "a:fontRef")
    if span is not None:
        which = FONT_REFS.get(attributes(TAG.match(sp, span[0]).group(0)).get("idx"))
        if which:
            for script in ("latin", "ea", "cs"):
                run.groups[script] = '<a:%s typeface="+%s-%s"/>' % (
                    script, which, {"latin": "lt"}.get(script, script))
        color = _color(sp, span[0])
        if color is not None:
            name, attrs, inner = color
            run.groups["fill"] = "<a:solidFill>%s</a:solidFill>" % (
                "<%s%s/>" % (name, attrs) if not inner else "<%s%s>%s</%s>" % (name, attrs, inner,
                                                                             name))
    return shape, run


def _style(xml, name):
    """{level: Props} of a master's text style, or the presentation's."""
    if not xml:
        return {}
    match = re.search(r"<%s\b" % re.escape(name), xml)
    return list_levels(xml, match.start()) if match else {}


class Chains:
    """What a shape's text inherits, and what a title's would: list styles,
    text body properties, and shape properties, from the shape's layout,
    master, and presentation."""

    def __init__(self, ph_type, idx, layout, master, presentation, styled=None):
        defaults = _style(presentation, "p:defaultTextStyle")
        # What the theme's styles give a shape (theme_style()): its text's
        # fonts and color over the text styles, under any list style a
        # placeholder has, and its fill, outline, and effects under any it
        # inherits. Measured for a text box; a placeholder styled by the
        # theme hasn't been seen.
        style_shape, style_run = styled or (Props(), Props())
        style_text = {n: Props() for n in range(1, 10)} if not style_run.empty() else {}
        for props in style_text.values():
            props.run = style_run
        if ph_type is None:
            self.lists = [defaults, style_text]
            self.body = Props()
            self.shape = style_shape
        else:
            style = {"title": "p:titleStyle", "body": "p:bodyStyle",
                     "other": "p:otherStyle"}[_kind(ph_type)]
            on_layout = matching(layout, ph_type, idx)
            on_master = matching(master, ph_type, None)
            self.lists = [defaults, _style(master, style), style_text, _lst(master, on_master),
                          _lst(layout, on_layout)]
            self.body = _body(layout, on_layout).over(_body(master, on_master))
            self.shape = _sppr(layout, on_layout).over(_sppr(master, on_master)).over(
                style_shape)
        on_layout = matching(layout, "title", None)
        on_master = matching(master, "title", None)
        self.title_lists = [defaults, _style(master, "p:titleStyle"), _lst(master, on_master),
                            _lst(layout, on_layout)]
        self.title_body = _body(layout, on_layout).over(_body(master, on_master))
        self.title_shape = _sppr(layout, on_layout).over(_sppr(master, on_master))


# --------------------------------------------------------------------------
# Which shape is a slide's heading

# The most a heading's text is drafted from: a slide whose topmost text is
# longer, or in more paragraphs, starts with something else.
HEADING_CHARS = 150
HEADING_PARAGRAPHS = 3
# A number added to a title, as a slide-titles draft numbers a title an
# earlier slide has.
NUMBERED = re.compile(r" \(\d+\)$")


def collapsed(text):
    return " ".join((text or "").split())


def _texts(slide):
    """The shapes on a parsed slide (pptxparse.Slide) that show it words,
    topmost first: a shape, not a picture, a frame, a group, or a
    connector, at the top of its tree, shown and placed, holding words and
    no equation, with an id no other shape on the slide has; not the date,
    footer, slide number, or header. None when the slide has a title
    placeholder, even an empty one, which is where its title goes."""
    shapes = list(slide.all_shapes())
    if any(s.is_title for s in shapes):
        return []
    count = Counter(s.id for s in shapes if s.id)
    found = [s for s in slide.shapes
             if s.kind == "sp" and s.id and count[s.id] == 1 and not s.furniture
             and not s.hidden and not s.decorative and not s.malformed and not s.math
             and s.box is not None and collapsed(s.text)]
    return sorted(found, key=lambda s: (s.box.y, s.box.x))


def heading_shapes(slide):
    """The shapes that could be a slide's title in place, topmost first:
    those that show it words, a shape that takes its look from the theme's
    styles among them (set_as_title() writes what they refer to out)."""
    return _texts(slide)


def heading(slide):
    """The shape a slide's title is drafted from: the topmost of those at
    the top of its tree that show words, a group's or an equation's among
    them, when it could be the slide's title in place and its text is
    short enough to be one; else None."""
    shapes = heading_shapes(slide)
    shown = [s for s in slide.shapes if s.box is not None and not s.hidden and not s.furniture
             and any(collapsed(part.text) for part in s.walk())]
    if not shapes or not shown:
        return None
    top = min(shown, key=lambda s: (s.box.y, s.box.x))
    if top is not shapes[0] or len(collapsed(top.text)) > HEADING_CHARS \
            or len([p for p in top.paragraphs if p.strip()]) > HEADING_PARAGRAPHS:
        return None
    return top


def heading_for(slide, title):
    """(shape, added): the shape that could be a slide's title whose text
    is title, or is title but for a number added, as " (2)" is, which is
    added; (None, "") when none is."""
    shapes = heading_shapes(slide)
    for shape in shapes:
        if collapsed(shape.text) == title:
            return shape, ""
    number = NUMBERED.search(title)
    if number:
        for shape in shapes:
            if collapsed(shape.text) == title[:number.start()]:
                return shape, title[number.start():]
    return None, ""


# --------------------------------------------------------------------------
# Set as Slide Title

def _sp_spans(xml, shape_id):
    """[(start, end)] of each p:sp whose cNvPr has the id, AlternateContent's
    Choice and Fallback alike."""
    out = []
    for cnvpr in re.finditer(r"<p:cNvPr\b%s/?>" % ATTRS, xml):
        if attributes(cnvpr.group(0)).get("id") != str(shape_id):
            continue
        starts = [m for m in re.finditer(r"<p:sp\b%s>" % ATTRS, xml[:cnvpr.start()])]
        if not starts:
            continue
        start = starts[-1].start()
        end = element_end(xml, start)
        if end > cnvpr.start():
            out.append((start, end))
    return out


def _in_group(xml, start):
    """Whether the element at start sits in a group rather than at the top
    of the slide's tree."""
    tree = _shape_tree(xml)
    if tree is None:
        return True
    for name, s, e in children(xml, tree):
        if s <= start < e:
            if s == start:
                return False
            if name == "mc:AlternateContent":
                return re.search(r"<p:grpSp\b", xml[s:start]) is not None
            return True
    return True


def set_as_title(xml, shape_id, layout=None, master=None, presentation=None, theme=None):
    """(xml, count): a slide's XML with the shape whose id is shape_id, a
    p:sp at the top of its tree holding text, made the slide's title in
    place, its look kept, in AlternateContent's Choice and Fallback alike;
    count 0 when there's no such shape (_convert()). layout, master, and
    presentation: the XML of the slide's layout, its master, and the
    presentation part, what the shape inherits from; theme, the master's
    theme, what a shape styled by the theme refers to."""
    spans = [(s, e) for s, e in _sp_spans(xml, shape_id) if not _in_group(xml, s)]
    if not spans:
        return xml, 0
    out = xml
    for start, end in sorted(spans, reverse=True):
        new = _convert(xml[start:end], layout, master, presentation, theme)
        if new is None:
            return xml, 0
        out = out[:start] + new + out[end:]
    return out, 1


def _convert(sp, layout, master, presentation, theme=None):
    """A p:sp's XML made a title, or None when it holds no text body, is a
    title already, or takes its look from the theme's styles and the
    theme hasn't what they refer to (theme_style())."""
    nv = _sub(sp, 0, ["p:nvSpPr"])
    body = _sub(sp, 0, ["p:txBody"])
    if nv is None or body is None:
        return None
    styled = None
    if _sub(sp, 0, ["p:style"]):
        styled = theme_style(sp, theme)
        if styled is None:
            return None
    ph = _sub(sp, 0, ["p:nvSpPr", "p:nvPr", "p:ph"])
    if ph:
        attrs = attributes(TAG.match(sp, ph[0]).group(0))
        ph_type, idx = attrs.get("type", "obj"), attrs.get("idx")
        if ph_type in TITLE_TYPES:
            return None
    else:
        ph_type = idx = None
    chains = Chains(ph_type, idx, layout, master, presentation, styled)
    edits = []          # (start, end, text), applied from the end

    # The list style: everything the shape's chain sets, its own over it,
    # and the defaults of what the title's sets that it doesn't.
    lst = child(sp, body[0], "a:lstStyle")
    own = list_levels(sp, lst[0]) if lst else {}
    current = chain(chains.lists + [own])
    title = chain(chains.title_lists)
    levels = []
    for n in range(1, 10):
        props = current.get(n, Props())
        if n in title:
            props.fill_in(title[n], P_ATTR_DEFAULTS, P_GROUP_DEFAULTS, R_ATTR_DEFAULTS,
                          R_GROUP_DEFAULTS)
        if not props.empty():
            levels.append(props.write("a:lvl%dpPr" % n, P_ORDER, "a:defRPr", R_ORDER, P_ATTRS,
                                      R_ATTRS))
    written = "<a:lstStyle>%s</a:lstStyle>" % "".join(levels) if levels else "<a:lstStyle/>"
    if lst:
        edits.append((lst[0], lst[1], written))
    else:
        bodypr = child(sp, body[0], "a:bodyPr")
        at = bodypr[1] if bodypr else TAG.match(sp, body[0]).end()
        edits.append((at, at, written))

    # The text body's properties, as the list style.
    bodypr = child(sp, body[0], "a:bodyPr")
    own_body = Props.read(sp, bodypr[0], B_GROUPS) if bodypr else Props()
    props = own_body.over(chains.body).fill_in(chains.title_body, B_ATTR_DEFAULTS,
                                               B_GROUP_DEFAULTS)
    text = props.write("a:bodyPr", B_ORDER, attr_order=B_ATTRS)
    if bodypr:
        edits.append((bodypr[0], bodypr[1], text))
    else:
        at = TAG.match(sp, body[0]).end()
        edits.append((at, at, text))

    # The shape's own properties, as the list style: its position, which a
    # placeholder takes from the one it matches, and its geometry, fill,
    # outline, and effects.
    sppr = _sub(sp, 0, ["p:spPr"])
    own_shape = Props.read(sp, sppr[0], S_GROUPS) if sppr else Props()
    props = own_shape.over(chains.shape).fill_in(chains.title_shape, {}, S_DEFAULTS)
    text = props.write("p:spPr", S_ORDER)
    if sppr:
        edits.append((sppr[0], sppr[1], text))
    else:
        at = nv[1]
        edits.append((at, at, text))

    # The placeholder: a title's, matched to no placeholder on the layout,
    # as PowerPoint writes it; a text box's lock on grouping set.
    nvpr = _sub(sp, 0, ["p:nvSpPr", "p:nvPr"])
    if ph:
        edits.append((ph[0], ph[1], TITLE_PH))
    elif nvpr:
        tag = TAG.match(sp, nvpr[0])
        if tag.group(4):
            edits.append((nvpr[0], nvpr[1], _start("p:nvPr", attributes(tag.group(0)))
                          + TITLE_PH + "</p:nvPr>"))
        else:
            edits.append((tag.end(), tag.end(), TITLE_PH))
    cnvsppr = _sub(sp, 0, ["p:nvSpPr", "p:cNvSpPr"])
    if not ph and cnvsppr:
        locks = child(sp, cnvsppr[0], "a:spLocks")
        tag = TAG.match(sp, cnvsppr[0])
        if locks:
            lock_attrs = attributes(TAG.match(sp, locks[0]).group(0))
            lock_attrs["noGrp"] = "1"
            lock_tag = TAG.match(sp, locks[0])
            edits.append((locks[0], lock_tag.end(), _start("a:spLocks", lock_attrs,
                                                         empty=bool(lock_tag.group(4)))))
        elif tag.group(4):
            edits.append((cnvsppr[0], cnvsppr[1], _start("p:cNvSpPr", attributes(tag.group(0)))
                          + '<a:spLocks noGrp="1"/></p:cNvSpPr>'))
        else:
            edits.append((tag.end(), tag.end(), '<a:spLocks noGrp="1"/>'))
    for start, end, text in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        sp = sp[:start] + text + sp[end:]
    return sp


# --------------------------------------------------------------------------
# What a paragraph and a run end up with, for checking

def effective(xml, shape_id, layout=None, master=None, presentation=None, theme=None):
    """[(paragraph Props, [run Props])] of a slide shape's text, each
    paragraph's and run's properties as they come out of its chain: its
    own over its shape's list style over what the shape inherits, the
    theme's styles' fonts and color among it when theme is given."""
    spans = _sp_spans(xml, shape_id)
    if not spans:
        return []
    sp = xml[spans[0][0]:spans[0][1]]
    ph = _sub(sp, 0, ["p:nvSpPr", "p:nvPr", "p:ph"])
    if ph:
        attrs = attributes(TAG.match(sp, ph[0]).group(0))
        ph_type, idx = attrs.get("type", "obj"), attrs.get("idx")
    else:
        ph_type = idx = None
    styled = theme_style(sp, theme) if theme else None
    chains = Chains(ph_type, idx, layout, master, presentation, styled)
    body = _sub(sp, 0, ["p:txBody"])
    lst = child(sp, body[0], "a:lstStyle")
    levels = chain(chains.lists + [list_levels(sp, lst[0]) if lst else {}])
    out = []
    for name, s, _e in children(sp, body[0]):
        if name != "a:p":
            continue
        ppr = child(sp, s, "a:pPr")
        own = Props.read(sp, ppr[0], P_GROUPS, "a:defRPr", R_GROUPS) if ppr else Props()
        level = int(own.attrs.get("lvl", "0")) + 1
        para = own.over(levels.get(level, Props()))
        runs = []
        for kind, rs, _re in children(sp, s):
            if kind in ("a:r", "a:fld", "a:br"):
                rpr = child(sp, rs, "a:rPr")
                run = Props.read(sp, rpr[0], R_GROUPS) if rpr else Props()
                runs.append(run.over(para.run or Props()))
        out.append((para, runs))
    return out
