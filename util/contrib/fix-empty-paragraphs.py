#!/usr/bin/env python3
# NOT YET WIRED IN. Kept here because it repairs a defect the PDF half of
# this project will produce as soon as it has a PDF half: LaTeX's tagging
# code opens paragraph structure elements that never receive content, and
# a PDF/UA checker reports each one as an empty paragraph. Two of the four
# places it happens are ours -- the longtable caption wrapper and Pandoc's
# minipage header cells -- so this is not a defect we can avoid by writing
# better Markdown.
#
# Written in another session against a hand-built textbook, so it has not
# been run against anything this pipeline produced. It needs pikepdf, which
# nothing else here does. Roadmap item 6 is where it gets picked up, along
# with the two other post-processing candidates named there.
#
"""
fix_empty_paragraphs.py -- remove content-free paragraph structure elements
from a tagged PDF produced by LaTeX (tagpdf / latex-lab) via Pandoc.

Background
----------
LaTeX's tagging code opens a paragraph structure element at points where no
paragraph content ever materialises:

  * around the parbox/multicolumn wrapper that longtable uses for \\caption
  * around Pandoc's \\begin{minipage}...\\end{minipage} header cells
  * inside the \\endhead repeated-header block, which longtable discards
  * around \\pandocbounded's \\resizebox when an image is scaled down

The resulting `P` elements contain either nothing at all or a marked-content
sequence holding only graphics-state operators. WCAG/PDF-UA checkers report
these as "empty paragraph" errors.

What this does
--------------
1. Walks the structure tree and finds every element whose role resolves to
   /P and whose subtree renders nothing -- no glyphs, no image, no path
   painting.
2. Deletes those elements, then prunes any purely-grouping ancestor left
   childless (Part, Div, Span, Sect, NonStruct, Quote, Art). Table cells,
   list items, notes, figures and captions are never pruned, even if empty.
3. Rewrites the affected pages' content streams, turning each orphaned
   marked-content sequence into an artifact (`/Artifact BMC ... EMC`) and
   renumbering the surviving MCIDs so no gaps remain.
4. Rebuilds those pages' /ParentTree arrays to match the new numbering, and
   removes the deleted elements' /ID entries from the /IDTree.

Paragraphs that hold a `\\rule` (Markdown's `---` thematic break) or an
inline Figure are NOT removed -- they draw something, and deleting them
would orphan real page content. Pass --list to see what is being touched
without writing anything.

Usage
-----
    python3 fix_empty_paragraphs.py in.pdf out.pdf
    python3 fix_empty_paragraphs.py in.pdf --list

Requires pikepdf (tested with 10.5).
"""

import argparse
import sys
from collections import defaultdict

import pikepdf
from pikepdf import Name, Dictionary, Array

# Operators that put something on the page. Anything else (graphics state,
# text positioning, colour) is invisible on its own.
RENDERING_OPS = {
    "Tj", "TJ", "'", '"',        # text showing
    "Do",                        # XObject (image or form)
    "sh",                        # shading
    "EI",                        # inline image
    "S", "s", "f", "F", "f*",    # path painting
    "B", "B*", "b", "b*",
}

# Roles that exist only to group other content -- safe to drop once empty.
PRUNABLE_ROLES = {"/Part", "/Div", "/Span", "/Sect", "/NonStruct", "/Art",
                  "/Quote", "/P"}


# --------------------------------------------------------------------------
# structure-tree helpers
# --------------------------------------------------------------------------

def make_role_resolver(struct_root):
    """Return a function mapping a raw /S value to its standard-namespace role."""
    rolemap = {}
    rm = struct_root.get("/RoleMap")
    if rm is not None:
        rolemap.update({str(k): str(v) for k, v in rm.items()})
    for ns in struct_root.get("/Namespaces", []) or []:
        rmns = ns.get("/RoleMapNS")
        if rmns is not None:
            for k, v in rmns.items():
                # /RoleMapNS values may be [role, namespace]; take the role.
                target = v[0] if isinstance(v, Array) else v
                rolemap.setdefault(str(k), str(target))

    def resolve(tag):
        seen = set()
        while tag in rolemap and tag not in seen:
            seen.add(tag)
            tag = rolemap[tag]
        return tag

    return resolve


def kids_of(elem):
    k = elem.get("/K")
    if k is None:
        return []
    return list(k) if isinstance(k, Array) else [k]


def is_struct_elem(obj):
    return isinstance(obj, Dictionary) and "/S" in obj


# --------------------------------------------------------------------------
# content-stream scanning
# --------------------------------------------------------------------------

def scan_page_ops(page):
    """Map MCID -> set of operators appearing inside that marked-content
    sequence (attributed to the innermost enclosing MCID)."""
    ops = defaultdict(set)
    stack = []
    try:
        instructions = pikepdf.parse_content_stream(page)
    except Exception as exc:                      # damaged or unusual stream
        print(f"  ! could not parse a content stream: {exc}", file=sys.stderr)
        return ops
    for operands, operator in instructions:
        op = str(operator)
        if op == "BDC":
            mcid = None
            if len(operands) > 1 and isinstance(operands[1], Dictionary):
                if "/MCID" in operands[1]:
                    mcid = int(operands[1]["/MCID"])
            stack.append(mcid)
            if mcid is not None:
                ops[mcid]  # touch, so empty sequences are recorded
        elif op == "BMC":
            stack.append(None)
        elif op == "EMC":
            if stack:
                stack.pop()
        else:
            current = next((m for m in reversed(stack) if m is not None), None)
            if current is not None:
                ops[current].add(op)
    return ops


# --------------------------------------------------------------------------
# main pass
# --------------------------------------------------------------------------

class Fixer:
    def __init__(self, pdf):
        self.pdf = pdf
        self.root = pdf.Root.StructTreeRoot
        self.role = make_role_resolver(self.root)
        self.page_by_objgen = {p.obj.objgen: p for p in pdf.pages}
        self.pageno = {p.obj.objgen: i + 1 for i, p in enumerate(pdf.pages)}
        self.ops = {p.obj.objgen: scan_page_ops(p) for p in pdf.pages}
        # (page objgen, mcid) -> owning structure element, filled during walk
        self.mc_owner = {}
        self.doomed = []          # (elem, parent, pagenum, reason)
        self.doomed_ids = set()

    # -- collection ---------------------------------------------------------

    def mcrefs(self, elem, inherited_pg=None):
        """Yield (page objgen, mcid) for every marked-content reference in the
        subtree rooted at elem."""
        pg = elem.get("/Pg")
        pg = pg.objgen if pg is not None else inherited_pg
        for kid in kids_of(elem):
            if is_struct_elem(kid):
                yield from self.mcrefs(kid, pg)
            elif isinstance(kid, Dictionary):
                if str(kid.get("/Type")) == "/MCR":
                    kpg = kid.get("/Pg")
                    yield ((kpg.objgen if kpg is not None else pg),
                           int(kid["/MCID"]))
                # /OBJR references an annotation: real content, leave alone
                elif str(kid.get("/Type")) == "/OBJR":
                    yield ("OBJR", None)
            else:
                yield (pg, int(kid))

    def renders_nothing(self, elem, inherited_pg=None):
        for pg, mcid in self.mcrefs(elem, inherited_pg):
            if pg == "OBJR":
                return False
            if RENDERING_OPS & self.ops.get(pg, {}).get(mcid, set()):
                return False
        return True

    def collect(self):
        def walk(elem, parent, inherited_pg):
            pg = elem.get("/Pg")
            pg = pg.objgen if pg is not None else inherited_pg
            tag = str(elem["/S"])

            for kid in kids_of(elem):
                if is_struct_elem(kid):
                    walk(kid, elem, pg)
                elif isinstance(kid, Dictionary):
                    if str(kid.get("/Type")) == "/MCR":
                        kpg = kid.get("/Pg")
                        key = ((kpg.objgen if kpg is not None else pg),
                               int(kid["/MCID"]))
                        self.mc_owner[key] = elem
                else:
                    self.mc_owner[(pg, int(kid))] = elem

            if self.role(tag) == "/P" and self.renders_nothing(elem, inherited_pg):
                refs = [r for r in self.mcrefs(elem, inherited_pg)]
                pgnum = self.pageno.get(refs[0][0]) if refs else None
                if pgnum is None:
                    pgnum = self.pageno.get(pg)
                if pgnum is None and parent is not None:
                    # caption / discarded-header cases carry no content of
                    # their own; borrow a page number from the nearest
                    # ancestor that does
                    anc = parent
                    while pgnum is None and is_struct_elem(anc):
                        for apg, _amc in self.mcrefs(anc):
                            if apg != "OBJR":
                                pgnum = self.pageno.get(apg)
                                break
                        anc = anc.get("/P")
                self.doomed.append((elem, parent, pgnum, len(refs)))

        for kid in kids_of(self.root):
            if is_struct_elem(kid):
                walk(kid, None, None)

    # -- removal ------------------------------------------------------------

    def detach(self, elem, parent):
        """Remove elem from parent's /K. Returns True if it was found."""
        container = self.root if parent is None else parent
        k = container.get("/K")
        if k is None:
            return False
        if isinstance(k, Array):
            for i, kid in enumerate(k):
                if isinstance(kid, Dictionary) and kid.objgen == elem.objgen:
                    del k[i]
                    if len(k) == 0:
                        del container["/K"]
                    return True
            return False
        if isinstance(k, Dictionary) and k.objgen == elem.objgen:
            del container["/K"]
            return True
        return False

    def note_id(self, elem, recurse=False):
        if "/ID" in elem:
            self.doomed_ids.add(bytes(elem["/ID"]))
        if recurse:
            for kid in kids_of(elem):
                if is_struct_elem(kid):
                    self.note_id(kid, recurse=True)

    def prune_upwards(self, elem):
        """Delete now-childless grouping ancestors."""
        while elem is not None and is_struct_elem(elem):
            if kids_of(elem):
                return
            if self.role(str(elem["/S"])) not in PRUNABLE_ROLES:
                return
            parent = elem.get("/P")
            parent = parent if is_struct_elem(parent) else None
            if not self.detach(elem, parent):
                return
            self.note_id(elem)
            elem = parent

    def remove_all(self):
        removed_mcids = defaultdict(set)     # page objgen -> {mcid}
        for elem, parent, _pgnum, _n in self.doomed:
            for pg, mcid in self.mcrefs(elem):
                if pg != "OBJR":
                    removed_mcids[pg].add(mcid)
            self.detach(elem, parent)
            self.note_id(elem, recurse=True)
            self.prune_upwards(parent)
        return removed_mcids

    # -- content streams ----------------------------------------------------

    def rewrite_page(self, page_objgen, removed):
        """Artifact-ise removed sequences, renumber the rest.
        Returns {old mcid: new mcid} for survivors."""
        page = self.page_by_objgen[page_objgen]
        instructions = pikepdf.parse_content_stream(page)
        out = []
        stack = []          # True when inside a removed sequence
        remap = {}
        next_id = 0
        for operands, operator in instructions:
            op = str(operator)
            if op == "BDC":
                mcid = None
                props = operands[1] if len(operands) > 1 else None
                if isinstance(props, Dictionary) and "/MCID" in props:
                    mcid = int(props["/MCID"])
                elif isinstance(props, Name) and mcid is None:
                    # property list held in the page's /Properties resource
                    pass
                if mcid is not None and mcid in removed:
                    if any(stack):
                        raise RuntimeError(
                            f"nested MCID {mcid} inside a removed sequence")
                    stack.append(True)
                    out.append(([Name("/Artifact")], pikepdf.Operator("BMC")))
                    continue
                stack.append(False)
                if mcid is not None:
                    remap[mcid] = next_id
                    newprops = Dictionary(props)
                    newprops["/MCID"] = next_id
                    next_id += 1
                    out.append(([operands[0], newprops], operator))
                    continue
            elif op == "BMC":
                stack.append(False)
            elif op == "EMC":
                if stack:
                    stack.pop()
            out.append((operands, operator))

        page.Contents = self.pdf.make_stream(
            pikepdf.unparse_content_stream(out))
        return remap

    def apply_remap(self, page_objgen, remap):
        """Point every surviving MCR / integer kid at its new MCID."""
        for (pg, old), owner in list(self.mc_owner.items()):
            if pg != page_objgen or old not in remap:
                continue
            new = remap[old]
            if new == old:
                continue
            k = owner.get("/K")
            items = k if isinstance(k, Array) else ([k] if k is not None else [])
            for i, kid in enumerate(items):
                if isinstance(kid, Dictionary) and str(kid.get("/Type")) == "/MCR":
                    kpg = kid.get("/Pg")
                    kpg = kpg.objgen if kpg is not None else \
                        (owner.get("/Pg").objgen if owner.get("/Pg") is not None else None)
                    if kpg == pg and int(kid["/MCID"]) == old:
                        kid["/MCID"] = new
                elif not isinstance(kid, Dictionary) and int(kid) == old:
                    if isinstance(k, Array):
                        k[i] = new
                    else:
                        owner["/K"] = new

    def rebuild_parent_tree(self, page_objgen, remap):
        page = self.page_by_objgen[page_objgen]
        sp = page.obj.get("/StructParents")
        if sp is None:
            return
        key = int(sp)
        nums = self.root.ParentTree.Nums
        for i in range(0, len(nums), 2):
            if int(nums[i]) == key:
                old = nums[i + 1]
                size = max(remap.values()) + 1 if remap else 0
                new = Array([None] * size)
                for o, n in remap.items():
                    if o < len(old):
                        new[n] = old[o]
                nums[i + 1] = self.pdf.make_indirect(new)
                return

    def clean_id_tree(self):
        if not self.doomed_ids:
            return
        idtree = self.root.get("/IDTree")
        if idtree is None:
            return

        def clean(node):
            names = node.get("/Names")
            if names is not None:
                kept = []
                for i in range(0, len(names), 2):
                    if bytes(names[i]) not in self.doomed_ids:
                        kept.extend([names[i], names[i + 1]])
                node["/Names"] = Array(kept)
                if kept:
                    node["/Limits"] = Array([kept[0], kept[-2]])
                elif "/Limits" in node:
                    del node["/Limits"]
                return bool(kept)
            kids = node.get("/Kids")
            if kids is not None:
                survivors = [k for k in kids if clean(k)]
                node["/Kids"] = Array(survivors)
                if survivors:
                    node["/Limits"] = Array([survivors[0]["/Limits"][0],
                                             survivors[-1]["/Limits"][1]])
                return bool(survivors)
            return False

        clean(idtree)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("output", nargs="?")
    ap.add_argument("--list", action="store_true",
                    help="report what would be removed and exit")
    args = ap.parse_args()
    if not args.list and not args.output:
        ap.error("give an output path, or use --list")

    pdf = pikepdf.open(args.input)
    if "/StructTreeRoot" not in pdf.Root:
        sys.exit("no structure tree -- is this a tagged PDF?")

    fixer = Fixer(pdf)
    fixer.collect()

    counts = defaultdict(int)
    for _elem, _parent, pgnum, _n in fixer.doomed:
        counts[pgnum] += 1
    print(f"content-free paragraph elements: {len(fixer.doomed)}")
    for pgnum in sorted(counts, key=lambda x: (x is None, x)):
        print(f"  page {pgnum}: {counts[pgnum]}")
    if args.list or not fixer.doomed:
        return

    removed = fixer.remove_all()
    for page_objgen, mcids in removed.items():
        remap = fixer.rewrite_page(page_objgen, mcids)
        fixer.apply_remap(page_objgen, remap)
        fixer.rebuild_parent_tree(page_objgen, remap)
    fixer.clean_id_tree()

    pdf.save(args.output)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
