"""
pptxorder.py -- a slide's reading order, and how it can change without
changing how the slide looks.

A slide's shape tree is its reading order and its stacking order at once:
a screen reader reads the shapes in the tree's order, and PowerPoint draws
them in that order, each over the ones before it. Microsoft says as much of
its own Reading Order pane: "Changing the order of objects can affect how
the slide looks when there are overlapping objects"
(https://support.microsoft.com/powerpoint/make-slides-easier-to-read-by-using-the-reading-order-pane).
So an order is written only if every two shapes whose boxes overlap keep
their order, which keeps what's drawn over what; shapes that don't overlap
can be read in any order without the slide looking any different.

Only the shapes at the top of the tree move: a group moves with everything
in it, as the Reading Order pane lists a group as one item, and a shape in
mc:AlternateContent moves with its Fallback. An order names the shapes it
moves by the ids PowerPoint gave them. They take the places in the tree
those shapes had, in the order given, and every other shape stays where it
was.

Overlap is judged by the boxes shapes are drawn in, a rotated shape's box
turned with it, each widened on every side by four points, or by the reach
of its outline when that's more (its width, three times it for a line with
an arrowhead), since an outline, an arrowhead, and the smoothing of edges
reach past the box: two widened boxes that share any area overlap. A shape
whose box can't be known counts as overlapping everything, and one that
draws nothing (a hidden shape, an empty placeholder) as overlapping
nothing. Text that runs further past its box, and a shadow or a glow,
aren't counted. Measured with LibreOffice on real decks: every slide put in
order was drawn pixel for pixel as before; with boxes widened by one point
or two, a few weren't.

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

import bisect
import heapq
import math
import re
from collections import Counter

import pptxparse

# A start tag's attributes, quoted values allowed to hold ">".
ATTRS = r"((?:\s+[\w:.-]+\s*=\s*(?:\"[^\"]*\"|'[^']*'))*)\s*"
# What XML text is made of, for walking it without parsing it: a comment,
# a processing instruction, CDATA, or a tag (its end slash, name,
# attributes, and self-closing slash).
TOKEN = re.compile(r"<!--.*?-->|<\?.*?\?>|<!\[CDATA\[.*?\]\]>"
                   r"|<(/?)([\w.-]+(?::[\w.-]+)?)" + ATTRS + r"(/?)>", re.S)
TREE = re.compile(r"<p:spTree" + ATTRS + r"(/?)>")
CNVPR = re.compile(r"<p:cNvPr" + ATTRS + r"/?>")
ID = re.compile(r"""\sid\s*=\s*(?:"([^"]*)"|'([^']*)')""")
SHAPES = ("p:sp", "p:pic", "p:graphicFrame", "p:grpSp", "p:cxnSp", "p:contentPart")
ALTERNATE = "mc:AlternateContent"
# How many shapes a draft puts in order at most: past that, a slide is a
# drawing in loose pieces more than a page to read, and its order is the
# author's to set.
DRAFT_LIMIT = 200
# How far past its box a shape counts as drawn, at least, in EMU: four
# points, for an outline, an arrowhead, and the smoothing of edges, which
# reach past the box; a wider outline counts at its own width. Measured: at
# one point or two, LibreOffice drew a few reordered slides of real decks a
# few pixels differently; at four, none.
MARGIN = 50800


class Child:
    """One child element of a slide's shape tree, where its text is."""

    __slots__ = ("start", "end", "name", "ids", "shape")

    def __init__(self, start, end, name, ids):
        self.start, self.end, self.name, self.ids = start, end, name, ids
        self.shape = None           # the parsed shape, when its one id names one

    @property
    def movable(self):
        """Whether it's a shape (or a shape in mc:AlternateContent)."""
        return self.name in SHAPES or self.name == ALTERNATE

    @property
    def id(self):
        return self.ids[0] if len(self.ids) == 1 else None


def children(xml, start, end):
    """(start, end, name) of each element directly inside the text from
    start to end, in order."""
    out, depth, begin, name = [], 0, None, None
    for match in TOKEN.finditer(xml, start, end):
        tag = match.group(2)
        if tag is None:
            continue
        if match.group(1):
            depth -= 1
            if depth == 0:
                out.append((begin, match.end(), name))
        elif match.group(4):
            if depth == 0:
                out.append((match.start(), match.end(), tag))
        else:
            if depth == 0:
                begin, name = match.start(), tag
            depth += 1
    return out


def _inside(xml, start, end):
    """Where an element's content is: after its start tag and before its
    end tag; an empty span for a self-closing one."""
    first = TOKEN.match(xml, start)
    if first is None or first.group(4):
        return start, start
    return first.end(), xml.rfind("</", start, end)


def _shape_id(xml, start, end):
    """A shape element's own id: its first cNvPr's, which its non-visual
    properties hold before anything else."""
    match = CNVPR.search(xml, start, end)
    if match is None:
        return None
    found = ID.search(match.group(1))
    return (found.group(1) if found.group(1) is not None else found.group(2)) if found else None


def _ids(xml, start, end, name):
    """The ids of the shapes an element puts at the top of the tree: its
    own, or, for mc:AlternateContent, those of the shapes in its first
    Choice (in its Fallback when it has none), which PowerPoint shows."""
    if name in SHAPES:
        found = _shape_id(xml, start, end)
        return [found] if found is not None else []
    if name != ALTERNATE:
        return []
    branches = children(xml, *_inside(xml, start, end))
    branch = next((b for b in branches if b[2] == "mc:Choice"), None) or next(
        (b for b in branches if b[2] == "mc:Fallback"), None)
    if branch is None:
        return []
    out = []
    for s, e, kind in children(xml, *_inside(xml, branch[0], branch[1])):
        if kind in SHAPES:
            found = _shape_id(xml, s, e)
            if found is not None:
                out.append(found)
    return out


def tree(xml, slide=None):
    """The children of a slide's shape tree, in order, as Child objects,
    each shape matched to the parsed slide's shape with its id when the id
    names one shape on the slide; None when the slide has no tree."""
    match = TREE.search(xml)
    if match is None:
        return None
    if match.group(2):
        return []
    close = xml.find("</p:spTree>", match.end())
    if close < 0:
        return None
    kids = [Child(s, e, name, _ids(xml, s, e, name))
            for s, e, name in children(xml, match.end(), close)]
    if slide is not None:
        counts = Counter(s.id for s in slide.all_shapes() if s.id is not None)
        by_id = {s.id: s for s in slide.shapes if s.id is not None and counts[s.id] == 1}
        for kid in kids:
            if kid.id is not None:
                kid.shape = by_id.get(kid.id)
    return kids


def envelope(shape):
    """The box a shape is drawn in, turned with it (a rotated box's own
    box on the slide), and widened on every side by MARGIN or its
    outline's reach, whichever is more."""
    box = shape.box
    if box is None:
        return None
    width, height = box.cx, box.cy
    if shape.rotation % 180:
        theta = math.radians(shape.rotation)
        cos, sin = abs(math.cos(theta)), abs(math.sin(theta))
        width, height = box.cx * cos + box.cy * sin, box.cx * sin + box.cy * cos
    middle_x, middle_y = box.x + box.cx / 2, box.y + box.cy / 2
    pad = max(MARGIN, shape.stroke)
    return pptxparse.Box(int(middle_x - width / 2 - pad), int(middle_y - height / 2 - pad),
                         int(round(width + 2 * pad)), int(round(height + 2 * pad)))


def draws(shape):
    """Whether a shape puts anything on the slide: not when it's hidden,
    or a placeholder with nothing in it, which shows only while editing.
    A shape that isn't known is taken to."""
    if shape is None:
        return True
    if shape.hidden:
        return False
    return not (shape.placeholder and shape.kind == "sp" and not shape.text.strip()
                and not shape.image)


def overlap(a, b):
    """Whether two of the tree's shapes are drawn one over the other, or
    may be: a shape whose box isn't known overlaps everything."""
    if not draws(a.shape) or not draws(b.shape):
        return False
    first = envelope(a.shape) if a.shape is not None else None
    second = envelope(b.shape) if b.shape is not None else None
    if first is None or second is None:
        return True
    return first.overlaps(second)


def before(a, b):
    """Whether parsed shape a comes before b as they're laid out, when
    the two don't overlap: wholly above it, or beside it and wholly to its
    left; None when neither comes before the other. A line has no height,
    so two lines side by side are each "above" the other by their edges
    alone; one starts above the other only if it starts higher too."""
    if a.box.overlaps(b.box):
        return None
    if a.box.y + a.box.cy <= b.box.y and a.box.y < b.box.y:
        return True
    if b.box.y + b.box.cy <= a.box.y and b.box.y < a.box.y:
        return False
    if a.box.x + a.box.cx <= b.box.x and a.box.x < b.box.x:
        return True
    if b.box.x + b.box.cx <= a.box.x and b.box.x < a.box.x:
        return False
    return None


def _ahead(shapes):
    """For each of shapes, how many of the others come before it (before()),
    and which come after it: (counts, lists), by position."""
    counts, after = [0] * len(shapes), [[] for _ in shapes]
    for i, a in enumerate(shapes):
        for j, b in enumerate(shapes):
            if i != j and before(a, b):
                counts[j] += 1
                after[i].append(j)
    return counts, after


def visual(shapes):
    """Shapes, in the tree's order, in the order they're laid out: the
    title first, then in turn a shape none of those left comes before
    (wholly above it, or beside it and wholly to its left), the earliest
    in the tree among them; where every shape left has one before it, as
    a layout can go round in a circle, the one with the fewest."""
    counts, after = _ahead(shapes)
    left, out = set(range(len(shapes))), []
    while left:
        pick = min(left, key=lambda i: (not shapes[i].is_title, counts[i], i))
        left.discard(pick)
        out.append(shapes[pick])
        for j in after[pick]:
            counts[j] -= 1
    return out


def label(shape):
    """A shape as a person finds it on a slide: its id, its name, and what
    it says or shows."""
    head = "%s %s" % (shape.id, shape.name or "")
    text = " ".join(shape.text.split())
    if text:
        return '%s "%s"' % (head.strip(), text[:40] + ("..." if len(text) > 40 else ""))
    descr = " ".join((shape.descr or "").split())
    if descr:
        return "%s (alt text: %s)" % (head.strip(), descr[:40] + ("..." if len(descr) > 40 else ""))
    return head.strip()


def named(kid):
    """A child of the tree as a message names it: by its id, or by its
    shape's name when it has no id of its own."""
    if kid.id is not None:
        return kid.id
    return kid.shape.name if kid.shape is not None and kid.shape.name else "a shape with no id"


def parse_order(text):
    """The ids an order names, in order: numbers, separated by spaces,
    commas, or semicolons. ValueError names the first that isn't one."""
    tokens = [t for t in re.split(r"[\s,;]+", text.strip()) if t]
    for token in tokens:
        if not re.fullmatch(r"\d+", token, re.ASCII):
            raise ValueError(token)
    return tokens


def violations(kids, arrangement):
    """Pairs (a, b) of the tree's shapes that overlap, a drawn before b
    now and after it in arrangement: a list of child indices, the tree's
    new order."""
    place = {child: n for n, child in enumerate(arrangement)}
    movable = [i for i, kid in enumerate(kids) if kid.movable]
    out = []
    for x in range(len(movable)):
        for y in range(x + 1, len(movable)):
            a, b = movable[x], movable[y]
            if place[a] > place[b] and overlap(kids[a], kids[b]):
                out.append((kids[a], kids[b]))
    return out


def arrange(kids, ids):
    """The tree's new order, as a list of child indices, for an order
    naming shapes by id: each named shape takes, in turn, the places the
    named shapes had. (arrangement, None), or (None, why it can't be)."""
    count = Counter(kid.id for kid in kids if kid.id is not None)
    where = {kid.id: i for i, kid in enumerate(kids) if kid.movable and kid.id is not None}
    seen, chosen = set(), []
    for shape_id in ids:
        if shape_id in seen:
            return None, "it names %s twice" % shape_id
        seen.add(shape_id)
        if shape_id not in where:
            return None, ("it names %s, which isn't a shape at the top of the slide's tree (one in "
                          "a group moves with the group, by the group's id)" % shape_id)
        if count[shape_id] > 1 or kids[where[shape_id]].shape is None:
            return None, ("it names %s, an id more than one shape on the slide has; PowerPoint "
                          "gives each its own when it opens and saves the deck" % shape_id)
        chosen.append(where[shape_id])
    arrangement = list(range(len(kids)))
    for slot, child in zip(sorted(chosen), chosen):
        arrangement[slot] = child
    clashes = violations(kids, arrangement)
    if clashes:
        return None, "; ".join(
            "%s and %s overlap, and it would draw %s over %s instead of under it"
            % (named(a), named(b), named(a), named(b)) for a, b in clashes[:3])
    return arrangement, None


def rewrite(xml, kids, arrangement):
    """xml with the tree's children in arrangement's order, the text
    between them left where it was."""
    if arrangement == list(range(len(kids))):
        return xml
    out = [xml[:kids[0].start]]
    for slot, child in enumerate(arrangement):
        out.append(xml[kids[child].start:kids[child].end])
        out.append(xml[kids[slot].end:kids[slot + 1].start] if slot + 1 < len(kids) else "")
    out.append(xml[kids[-1].end:])
    return "".join(out)


def order_of(kids, ids):
    """The order the shapes an order names are in, in the tree as it is."""
    wanted = set(ids)
    return [kid.id for kid in kids if kid.movable and kid.id in wanted]


def _fits(rest, start, end, lo, hi, first, then):
    """Whether the shapes in rest, the tree's places of shapes to read,
    can take the slots from start to end, one each: each in a slot from
    lo to hi, and after every overlapping shape before it in the tree
    (first, then: those before it and after it). Release times and
    deadlines are tightened along the overlaps, and the earliest deadline
    is taken first, which finds a way whenever there's one for slots of
    equal length."""
    order = sorted(rest)            # an overlap is always kept in the tree's order
    release, due = {}, {}
    for c in order:
        release[c] = max([lo[c], start] + [release[a] + 1 for a in first[c] if a in rest])
    for c in reversed(order):
        due[c] = min([hi[c]] + [due[b] - 1 for b in then[c] if b in rest])
        if due[c] < release[c]:
            return False
    waiting, ready, i = sorted(order, key=release.get), [], 0
    for slot in range(start, end):
        while i < len(waiting) and release[waiting[i]] <= slot:
            heapq.heappush(ready, (due[waiting[i]], waiting[i]))
            i += 1
        if not ready or heapq.heappop(ready)[0] < slot:
            return False
    return True


def draft(kids, read):
    """An order for a person to review: the shapes a screen reader reads
    (read, parsed shapes) in the order they're laid out (visual()), as
    near to it as the tree can come with every overlapping pair kept in
    its order. Slot by slot, the shape the layout puts first among those
    that can go there, with the rest still able to go somewhere. (ids,
    note), or (None, note) when no order nearer the layout keeps what's
    drawn over what, or ids can't name the shapes."""
    index = {id(kid.shape): i for i, kid in enumerate(kids) if kid.shape is not None}
    unnamed = [s for s in read if id(s) not in index]
    if unnamed:
        return None, ("%s can't be named: %s; PowerPoint gives each shape its own id when it "
                      "opens and saves the deck" % (
                          ", ".join(s.name or "a shape" for s in unnamed[:3]),
                          "two shapes share the id" if any(s.id for s in unnamed)
                          else "it has no id"))
    if len(read) > DRAFT_LIMIT:
        return None, ("With %d shapes to read, no order is drafted; that's for the author, in "
                      "PowerPoint's Reading Order pane." % len(read))
    reading = sorted(index[id(s)] for s in read)        # the slots, in the tree
    shape_at = {index[id(s)]: s for s in read}
    count = len(reading)
    movable = [i for i, kid in enumerate(kids) if kid.movable]
    boxes = {}
    for i in movable:
        shape = kids[i].shape
        boxes[i] = (envelope(shape) if shape is not None else None) if draws(shape) else False

    def over(a, b):         # overlap(), each box worked out once
        if boxes[a] is False or boxes[b] is False:
            return False
        return boxes[a] is None or boxes[b] is None or boxes[a].overlaps(boxes[b])
    # A shape that isn't read stays where it is, so one it overlaps keeps
    # to its side of it: the slots it can take run from lo to hi.
    lo, hi = {c: 0 for c in reading}, {c: count - 1 for c in reading}
    for f in movable:
        if f in shape_at:
            continue
        cut = bisect.bisect_left(reading, f)
        for c in reading:
            if over(c, f):
                if c < f:
                    hi[c] = min(hi[c], cut - 1)
                else:
                    lo[c] = max(lo[c], cut)
    first, then = {c: [] for c in reading}, {c: [] for c in reading}
    for x, a in enumerate(reading):
        for b in reading[x + 1:]:
            if over(a, b):
                first[b].append(a)
                then[a].append(b)
    # Which overlapping pairs the layout's order would draw the other way
    # round: what keeps the draft from being it.
    ideal = list(range(len(kids)))
    for slot, shape in zip(reading, visual([shape_at[c] for c in reading])):
        ideal[slot] = index[id(shape)]
    kept = violations(kids, ideal)
    counts, after = _ahead([shape_at[c] for c in reading])
    ahead = {c: counts[n] for n, c in enumerate(reading)}
    behind = {c: [reading[j] for j in after[n]] for n, c in enumerate(reading)}
    left, found = set(reading), []
    for slot in range(count):
        ready = [c for c in left if lo[c] <= slot <= hi[c] and not any(a in left for a in first[c])]
        # The tree's own order always fits, so some shape always can.
        pick = next(c for c in sorted(ready, key=lambda c: (not shape_at[c].is_title, ahead[c], c))
                    if _fits(left - {c}, slot + 1, count, lo, hi, first, then))
        left.discard(pick)
        found.append(pick)
        for b in behind[pick]:
            ahead[b] -= 1
    note = ""
    if kept:
        note = "kept in the tree's order, since they overlap: " + "; ".join(
            "%s before %s" % (named(a), named(b)) for a, b in kept[:4]) + "."
        pictures = [a for a, b in kept if a.shape is not None and a.shape.image
                    and b.shape is not None and b.shape.text.strip()]
        if pictures:
            note += (" A picture under text is usually decorative, or belongs in the slide's "
                     "background.")
    if found == reading:
        return None, (note + (" No order nearer the layout keeps what's drawn over what"
                              if kept else " No order reads every shape after those above it "
                              "and to its left, as these are laid out") +
                      "; that's for the author, in PowerPoint.").strip()
    return [kids[i].id for i in found], note
