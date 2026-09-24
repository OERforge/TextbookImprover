"""Formulas as MathJax drew them in a saved page, made math again.

A page saved from a browser after MathJax ran holds each formula as
MathJax's rendering, not its source. Pandoc's HTML reader reads MathJax
2's HTML-CSS rendering as spans nested ten deep, drops its CommonHTML
rendering outright, and has nothing to read in an SVG one; an .mhtml
save keeps no scripts, so the TeX is gone. Each rendering is replaced
before Pandoc reads the page, by the first of these that it has:

1. Nothing, when MathJax's <script type="math/tex"> follows it: Pandoc
   reads the TeX, so the formula isn't there twice.
2. The MathML MathJax hides in it for screen readers (MathJax 2's
   MJX_Assistive_MathML, 3's and 4's mjx-assistive-mml), or MathJax 2's
   data-mathml attribute: exact.
3. The TeX it carries: MathJax 4 writes it in data-latex, and an SVG
   rendering may have it as its <title>. Handed to Pandoc as a script.
4. MathML rebuilt from the rendering's structure, which names each
   element: MathJax 2's HTML-CSS in its span classes, with ids numbered in
   the formula's order; its CommonHTML in mjx-* classes; 3's and 4's
   CommonHTML in mjx-* element names, and their SVG in data-mml-node. A
   part's role (superscript, lower limit, root index) comes from the
   wrapper that names it, or in SVG from where it sits and its size,
   since no version draws them in MathML's order.
5. Otherwise a marker, "[formula]", which the output check reports: MathJax
   2's SVG keeps only positioned glyphs, and nothing else can be read.

Tested on renderings MathJax 2.7, 3.2, and 4.1 produced of the same
formulas, and on DCIC, a real book of MathJax 2 HTML-CSS; no real page
of the other kinds has been read yet.
"""
import re

import htmlparse as hp

TOKENS = ("mi", "mo", "mn", "mtext", "ms")
CONTAINERS = ("math", "mrow", "texatom", "mfrac", "msup", "msub", "msubsup",
              "msqrt", "mroot", "munder", "mover", "munderover", "mstyle",
              "mpadded", "mphantom", "menclose", "merror", "mtable", "mtr",
              "mtd", "mlabeledtr", "mspace")
KINDS = TOKENS + CONTAINERS
MATHML = "http://www.w3.org/1998/Math/MathML"


def _classes(element):
    return (element.get("class") or "").split()


def _kind(element):
    for name in _classes(element):
        if name in KINDS:
            return name
    return None


def _number(element):
    found = re.match(r"MathJax-Span-(\d+)$", element.get("id") or "")
    return int(found.group(1)) if found else float("inf")


def _math_children(element):
    """The nearest descendants that name a MathML element, in the
    formula's order: through the spans that only position things."""
    out = []
    for child in element:
        if not isinstance(child.tag, str):
            continue
        if _kind(child):
            out.append(child)
        else:
            out.extend(_math_children(child))
    return sorted(out, key=_number)


# How many children each kind takes; a count that doesn't fit is an mrow.
ARITY = {"mfrac": 2, "mroot": 2, "msup": 2, "msub": 2, "munder": 2,
         "mover": 2, "msubsup": 3, "munderover": 3}


def _top(element, within):
    """The em offset of the nearest positioned span from element up to
    within: how high MathJax placed it."""
    parent_of = {c: p for p in within.iter() for c in p}
    node = element
    while node is not None and node is not within:
        found = re.search(r"(?:^|;)\s*top:\s*(-?[\d.]+)em", node.get("style") or "")
        if found:
            return float(found.group(1))
        node = parent_of.get(node)
    return None


def _build(element, maker):
    kind = _kind(element)
    if kind in TOKENS:
        node = maker(kind, {})
        node.text = hp.text_of(element).replace("\u200b", "").strip()
        return node, 1
    name = "mrow" if kind == "texatom" else kind
    kids = [] if kind == "mspace" else _math_children(element)
    # MathJax 2 draws msup and msub with its msubsup, and munder and mover
    # with its munderover, so one script means one of the two-child kinds:
    # a superscript (over) when the layout raised it above its base, which
    # is also the likelier when the layout doesn't say.
    if name in ("msubsup", "munderover") and len(kids) == 2:
        base, script = _top(kids[0], element), _top(kids[1], element)
        raised = base is None or script is None or script < base
        name = {"msubsup": ("msup", "msub"),
                "munderover": ("mover", "munder")}[name][0 if raised else 1]
    if name in ARITY and len(kids) != ARITY[name]:
        name = "mrow"
    node = maker(name, {})
    tokens = 0
    # MathJax 2 lays a table out by columns and draws no span for a row,
    # so its cells arrive without their mtr. In the formula's order they're
    # row by row, and a row's cells sit at one height: a new height starts
    # a new row. Without heights, one row, which is at least MathML.
    if name == "mtable" and kids and all(_kind(k) == "mtd" for k in kids):
        rows = []
        for child in kids:
            top = _top(child, element)
            if rows and rows[-1][0] == top:
                rows[-1][1].append(child)
            else:
                rows.append((top, [child]))
        if any(top is None for top, _ in rows):
            rows = [(None, kids)]
        for _, cells in rows:
            row = maker("mtr", {})
            for child in cells:
                built, count = _build(child, maker)
                row.append(built)
                tokens += count
            node.append(row)
        return node, tokens
    for child in kids:
        built, count = _build(child, maker)
        node.append(built)
        tokens += count
    return node, tokens


# ---------------------------------------------------------------------------
# CommonHTML and SVG, every version: one builder, told how a family names
# an element, a role, and a token's characters.
# ---------------------------------------------------------------------------

import unicodedata

MATH_KINDS = set(TOKENS) | set(CONTAINERS) | {"mstyle", "semantics"}
ROLE_WORDS = {"base": "base", "sup": "sup", "sub": "sub", "over": "over",
              "under": "under", "root": "root", "num": "num",
              "numerator": "num", "den": "den", "denominator": "den",
              "surd": "surd", "script": "script"}


def _plain(text, kind):
    """A mathematical italic letter is a plain one in <mi>, where italic is
    the default: MathJax 3 and 4 write x as U+1D465."""
    if kind != "mi":
        return text
    out = []
    for ch in text:
        name = unicodedata.name(ch, "")
        found = re.match(r"MATHEMATICAL ITALIC (SMALL|CAPITAL) ([A-Z])$", name)
        if found:
            ch = found.group(2).lower() if found.group(1) == "SMALL" else found.group(2)
        elif ch == "\u210e":
            ch = "h"
        out.append(ch)
    return "".join(out)


def _hex_chars(codes):
    out = []
    for code in codes:
        try:
            out.append(chr(int(code, 16)))
        except ValueError:
            pass
    return "".join(out)


class _Family:
    svg = False

    def kind(self, element):
        return None

    def role(self, element):
        return None

    def chars(self, element):
        return hp.text_of(element)


class _CommonHTML2(_Family):
    """MathJax 2's CommonHTML: spans classed mjx-<element>, parts in
    wrappers classed mjx-sup, mjx-numerator, and so on."""
    def kind(self, element):
        for name in _classes(element):
            if name.startswith("mjx-") and name[4:] in MATH_KINDS:
                return name[4:]
        return None

    def role(self, element):
        for name in _classes(element):
            if name.startswith("mjx-") and name[4:] in ROLE_WORDS:
                return ROLE_WORDS[name[4:]]
        return None

    def chars(self, element):
        pieces = [hp.text_of(e) for e in element.iter()
                  if isinstance(e.tag, str) and "mjx-char" in _classes(e)]
        return "".join(pieces) if pieces else hp.text_of(element)


class _CommonHTML3(_Family):
    """MathJax 3's and 4's CommonHTML: elements named mjx-<element>, a
    character in <mjx-c class="mjx-c1D465">, as text too in 4; a stretched
    delimiter's character on its mjx-stretchy element."""
    def kind(self, element):
        name = hp.local(element.tag)
        return name[4:] if name.startswith("mjx-") and name[4:] in MATH_KINDS else None

    def role(self, element):
        name = hp.local(element.tag)
        return ROLE_WORDS.get(name[4:]) if name.startswith("mjx-") else None

    def chars(self, element):
        for e in element.iter():
            if isinstance(e.tag, str) and hp.local(e.tag).startswith("mjx-stretchy"):
                return _hex_chars(re.findall(r"mjx-c([0-9A-F]+)", e.get("class") or ""))
        out = []
        for e in element.iter():
            if isinstance(e.tag, str) and hp.local(e.tag) == "mjx-c":
                text = (e.text or "").strip()
                out.append(text or _hex_chars(re.findall(r"mjx-c([0-9A-F]+)",
                                                         e.get("class") or "")))
        return "".join(out)


class _SVG3(_Family):
    """MathJax 3's and 4's SVG: groups with data-mml-node, each character's
    code point in data-c. No wrapper names a part: where it sits and its
    size do."""
    svg = True

    def kind(self, element):
        name = (element.get("data-mml-node") or "").lower()   # "TeXAtom"
        return name if name in MATH_KINDS else None

    def chars(self, element):
        own = element.get("data-c")
        if own:
            return _hex_chars(own.split())
        codes = [e.get("data-c") for e in element.iter()
                 if isinstance(e.tag, str) and e.get("data-c")]
        # A stretched delimiter is drawn in repeated parts; the digits of 11
        # are two of one character too, so only an operator is one.
        if self.kind(element) == "mo" and len(set(codes)) == 1 and len(codes) > 1:
            codes = codes[:1]
        return _hex_chars(codes)


def _placement(element):
    """(scaled, height) from an SVG group's transform: a script is drawn
    smaller, and a superscript or upper limit higher (y up, as MathJax's
    SVG is flipped)."""
    transform = element.get("transform") or ""
    found = re.search(r"translate\(\s*[-\d.]+\s*,\s*([-\d.]+)", transform)
    scale = re.search(r"scale\(\s*([\d.]+)", transform)
    return (bool(scale) and float(scale.group(1)) < 1,
            float(found.group(1)) if found else 0.0)


def _parts(element, family):
    """[(child, role, position in a script wrapper)] for the nearest
    descendants that name an element, skipping a root's surd."""
    out = []
    outer = family.kind(element)

    def walk(node, role, slot):
        for child in node:
            if not isinstance(child.tag, str):
                continue
            here = family.role(child)
            if here == "surd":
                continue
            # MathJax 3 lays out an munderover's base and lower limit in an
            # mjx-munder of its own, named like the MathML element but a
            # wrapper here.
            if (outer == "munderover" and isinstance(family, _CommonHTML3)
                    and family.kind(child) in ("munder", "mover")):
                walk(child, role, slot)
                continue
            if family.kind(child):
                out.append((child, role, slot[0] if role == "script" else None))
                if role == "script":
                    slot[0] += 1
            else:
                walk(child, here or role, [0] if here == "script" else slot)
    walk(element, None, [0])
    return out


def _ordered(kind, parts, family):
    """The children in MathML's order, and the kind they make: a lone
    script in a two-script element makes the one-script kind."""
    kids = [p[0] for p in parts]
    if kind in ("msubsup", "munderover", "msup", "msub", "mover", "munder",
                "mroot") and len(parts) >= 2:
        if family.svg:
            placed = [(child, *_placement(child)) for child, _, _ in parts]
            base = next((c for c, scaled, _ in placed if not scaled), placed[0][0])
            rest = [(c, y) for c, scaled, y in placed if c is not base]
            if kind == "mroot":
                return "mroot", [base, rest[0][0]]
            rest.sort(key=lambda item: item[1])        # lowest first
            if len(rest) == 2:
                return kind if kind in ("msubsup", "munderover") else \
                    ("msubsup" if kind in ("msup", "msub") else "munderover"), \
                    [base, rest[0][0], rest[1][0]]
            upper = rest[0][1] > 0
            one = {"msubsup": ("msup", "msub"), "munderover": ("mover", "munder")}
            return (one[kind][0 if upper else 1] if kind in one else kind), \
                [base, rest[0][0]]
        roles = {}
        scripts = sum(1 for p in parts if p[1] == "script")
        for child, role, slot in parts:
            if role == "script":
                # MathJax 3 and 4 put a superscript before its subscript in
                # one script wrapper; alone, a script is the element's own.
                if scripts == 2:
                    role = "sup" if slot == 0 else "sub"
                else:
                    role = "sub" if kind in ("msub", "munder") else "sup"
            roles.setdefault(role, child)
        base = roles.get("base") or roles.get(None) or kids[0]
        if kind == "mroot":
            index = roles.get("root") or next(c for c in kids if c is not base)
            return "mroot", [base, index]
        low = roles.get("sub") or roles.get("under")
        high = roles.get("sup") or roles.get("over")
        if kind in ("msub", "munder") and low is None:
            low = next((c for c in kids if c is not base), None)
        if kind in ("msup", "mover") and high is None:
            high = next((c for c in kids if c is not base), None)
        if low is not None and high is not None:
            return ("munderover" if kind in ("munderover", "mover", "munder")
                    else "msubsup"), [base, low, high]
        script = high if high is not None else low
        over = kind in ("munderover", "mover", "munder")
        if script is None:
            return "mrow", kids
        return (("mover" if over else "msup") if high is not None else
                ("munder" if over else "msub")), [base, script]
    if kind == "mfrac" and len(parts) == 2:
        roles = {role: child for child, role, _ in parts}
        if "num" in roles and "den" in roles:
            return "mfrac", [roles["num"], roles["den"]]
    return kind, kids


def _build_named(element, family, maker):
    kind = family.kind(element)
    if kind in TOKENS:
        node = maker(kind, {})
        node.text = _plain(family.chars(element).replace("\u200b", "").strip(), kind)
        return node, 1
    name = "mrow" if kind in ("texatom", "semantics") else kind
    parts = [] if kind == "mspace" else _parts(element, family)
    if name in ("msqrt", "mroot") and family.svg:
        parts = [p for p in parts if not (family.kind(p[0]) == "mo"
                                          and family.chars(p[0]).strip() == "\u221a")]
    name, kids = _ordered(name, parts, family)
    if name in ARITY and len(kids) != ARITY[name]:
        name = "mrow"
    node = maker(name, {})
    tokens = 0
    for child in kids:
        built, count = _build_named(child, family, maker)
        node.append(built)
        tokens += count
    return node, tokens


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

RENDERING_CLASSES = {"MathJax", "MathJax_Display", "mjx-chtml", "MathJax_CHTML",
                     "MJXc-display", "MathJax_SVG", "MathJax_SVG_Display"}
DISPLAY_CLASSES = {"MathJax_Display", "MJXc-display", "MathJax_SVG_Display"}


def _is_rendering(element):
    if not isinstance(element.tag, str):
        return False
    if hp.local(element.tag) == "mjx-container":
        return True
    return bool(RENDERING_CLASSES & set(_classes(element)))


def _find(element, test):
    return next((e for e in element.iter() if isinstance(e.tag, str) and test(e)), None)


def _hidden_mathml(rendering):
    """The <math> MathJax hid in its rendering for screen readers."""
    for holder in rendering.iter():
        if isinstance(holder.tag, str) and (
                "MJX_Assistive_MathML" in _classes(holder)
                or hp.local(holder.tag) == "mjx-assistive-mml"):
            for child in holder:
                if isinstance(child.tag, str) and hp.local(child.tag) == "math":
                    return holder, child
    return None, None


def _tex(rendering):
    """TeX the rendering carries: MathJax 4's data-latex on the formula,
    or an SVG rendering's <title>."""
    latex = _find(rendering, lambda e: hp.local(e.tag) == "mjx-math"
                  and e.get("data-latex"))
    if latex is None:
        latex = _find(rendering, lambda e: e.get("data-mml-node") == "math"
                      and e.get("data-latex"))
    if latex is not None:
        return latex.get("data-latex")
    svg = _find(rendering, lambda e: hp.local(e.tag) == "svg")
    if svg is not None:
        title = next((c for c in svg if isinstance(c.tag, str)
                      and hp.local(c.tag) == "title"), None)
        if title is not None and (title.text or "").strip():
            return title.text.strip()
    return None


def _family(rendering):
    """(family, [the elements holding the formula]) for a rendering this
    can rebuild; (None, None) for one it can't. MathJax 4 breaks a long
    formula's SVG into one <svg> per line, each with its own math group,
    so an SVG formula is every one of them, in order."""
    tops = [e for e in rendering.iter() if isinstance(e.tag, str)
            and e.get("data-mml-node") == "math"]
    if tops:
        return _SVG3(), tops
    top = _find(rendering, lambda e: hp.local(e.tag) == "mjx-math")
    if top is not None:
        return _CommonHTML3(), [top]
    top = _find(rendering, lambda e: "mjx-math" in _classes(e))
    if top is not None:
        return _CommonHTML2(), [top]
    top = _find(rendering, lambda e: "math" in _classes(e)
                and re.match(r"MathJax-Span-\d+$", e.get("id") or ""))
    if top is not None:
        return "html-css", [top]
    return None, None


def _replace(parent, old, new):
    index = list(parent).index(old)
    new.tail = old.tail
    parent.remove(old)
    parent.insert(index, new)


def rebuilt(markup):
    """(markup, counts): the page with every MathJax rendering replaced,
    and how many went each way -- tex-follows, hidden-mathml, tex,
    rebuilt, lost. A page that mentions no MathJax is returned untouched."""
    counts = {"tex-follows": 0, "hidden-mathml": 0, "tex": 0, "rebuilt": 0,
              "lost": 0}
    if "MathJax" not in markup and "mjx-" not in markup:
        return markup, counts
    root = hp.parse(markup)
    parent_of = hp.parents(root)

    def inside_another(element):
        parent = parent_of.get(element)
        while parent is not None:
            if _is_rendering(parent):
                return True
            parent = parent_of.get(parent)
        return False
    renderings = [e for e in root.iter() if _is_rendering(e)
                  and "MathJax_Preview" not in _classes(e) and not inside_another(e)]
    for rendering in renderings:
        parent = parent_of.get(rendering)
        if parent is None:
            continue
        maker = rendering.makeelement
        display = (rendering.get("display") == "true"
                   or bool(DISPLAY_CLASSES & set(_classes(rendering))))
        siblings = [s for s in parent if isinstance(s.tag, str)]
        at = siblings.index(rendering)
        following = siblings[at + 1] if at + 1 < len(siblings) else None
        if following is not None and hp.local(following.tag) == "script" \
                and (following.get("type") or "").startswith("math/"):
            hp.drop(rendering, parent_of)
            counts["tex-follows"] += 1
            continue
        holder, hidden = _hidden_mathml(rendering)
        if hidden is None:
            framed = _find(rendering, lambda e: e.get("data-mathml"))
            if framed is not None:
                found = _find(hp.parse("<body>" + framed.get("data-mathml") + "</body>"),
                              lambda e: hp.local(e.tag) == "math")
                if found is not None:
                    holder, hidden = None, found
        if hidden is not None:
            if holder is not None:
                holder.remove(hidden)
            if display:
                hidden.set("display", "block")
            _replace(parent, rendering, hidden)
            counts["hidden-mathml"] += 1
            continue
        tex = _tex(rendering)
        if tex:
            script = maker("script", {"type": "math/tex; mode=display" if display
                                      else "math/tex"})
            script.text = tex
            _replace(parent, rendering, script)
            counts["tex"] += 1
            continue
        family, tops = _family(rendering)
        formula, tokens = None, 0
        if family is not None:
            attrs = {"xmlns": MATHML}
            if display:
                attrs["display"] = "block"
            formula = maker("math", attrs)
            if family == "html-css":
                children = [c for top in tops for c in _math_children(top)]
                build = lambda child: _build(child, maker)
            else:
                children = [p[0] for top in tops for p in _parts(top, family)]
                build = lambda child: _build_named(child, family, maker)
            for child in children:
                built, count = build(child)
                formula.append(built)
                tokens += count
        if formula is not None and tokens:
            _replace(parent, rendering, formula)
            counts["rebuilt"] += 1
            continue
        lost = maker("span", {"class": "math-lost"})
        lost.text = "[formula]"
        _replace(parent, rendering, lost)
        counts["lost"] += 1
    if not any(counts.values()):
        return markup, counts
    doctype = "<!DOCTYPE html>\n" if markup.lstrip()[:9].lower() == "<!doctype" else ""
    return doctype + hp.serialize(root), counts
