"""A LaTeX book's class and packages, checked against the LaTeX tagging
project's status list, before the book is built with LaTeX's own tagging.

The list comes from the TeX distribution itself: the package
latex-tagging-status (TeX Live's collection-latexextra; MiKTeX installs it
on demand) holds latex-tagging-status.ltx, which LaTeX reads for the
check-tagging-status key of \\DocumentMetadata. The run looks for it with
kpsewhich, from the book's own folder first, and says how to install it
when it's missing; the distribution's own updater keeps it current, and
the run says when it's older than the LaTeX it checks.

The check only advises. A document can build to a PDF that passes PDF/UA-2
with a class and a package the list calls currently incompatible (the
calculus notes, with extarticle and selectp), and a package that uses the
tagging interfaces itself can still be rated incompatible (the KOMA-Script
classes), so neither the list nor a package's own source is taken as the
last word, and nothing stops a run.
"""

import os
import re
import shutil
import subprocess

import latexsource

DATA = "latex-tagging-status.ltx"
PAGE = "https://latex3.github.io/tagging-project/tagging-status/"
ENTRY = re.compile(r"\\@kernel@tagging@status\{([^}]*)\}\{([^}]*)\}\{(\d+)\}")
DATE = re.compile(r"\\ProvidesFile\{latex-tagging-status\.ltx\}\[(\d{4}-\d{2}-\d{2})")
KERNEL_DATE = re.compile(r"\\edef\\fmtversion\s*\{(\d{4}-\d{2}-\d{2})\}")
# The codes the data file uses (its own header): 100 is a package another
# one includes, listed under it, so it says nothing of its own.
STATUS = {4: "compatible", 3: "partially compatible", 2: "currently incompatible",
          1: "never to be supported", 0: "unchecked"}
PACKAGE = re.compile(r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")
CLASS = re.compile(r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")
INPUT = re.compile(r"\\(?:input|include)\s*\{([^}]*)\}")


def kpsewhich(name, cwd):
    """The path kpsewhich finds for name, looking from cwd, or None."""
    if not shutil.which("kpsewhich"):
        return None
    found = subprocess.run(["kpsewhich", name], cwd=cwd, capture_output=True,
                           text=True).stdout.strip()
    if not found:
        return None
    return found if os.path.isabs(found) else os.path.join(cwd, found)


def load(path):
    """(date, {(name, ext): code}) from the data file."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    date = DATE.search(text)
    return (date.group(1) if date else ""), {
        (m.group(1), m.group(2)): int(m.group(3)) for m in ENTRY.finditer(text)}


def kernel_date(cwd):
    path = kpsewhich("latex.ltx", cwd)
    if not path:
        return ""
    with open(path, encoding="utf-8", errors="replace") as fh:
        found = KERNEL_DATE.search(fh.read())
    return found.group(1) if found else ""


def preamble_code(base, master):
    """The master's preamble, in code, with each file it \\input-s there."""
    text = latexsource.read_text(os.path.join(base, master))
    preamble = latexsource.split_master(text)[0]
    pieces = [preamble]
    spans = latexsource.skip_spans(preamble)
    for m in INPUT.finditer(preamble):
        if latexsource.in_spans(m.start(), spans):
            continue
        name = m.group(1).strip()
        for candidate in (name, name + ".tex"):
            path = os.path.join(base, candidate)
            if os.path.isfile(path):
                pieces.append(latexsource.read_text(path))
                break
    return pieces


def used(base, master):
    """[(name, ext)] the book loads: its class, then its packages, in order."""
    found = []
    for text in preamble_code(base, master):
        spans = latexsource.skip_spans(text)
        for m in CLASS.finditer(text):
            if not latexsource.in_spans(m.start(), spans):
                found.append((m.group(1).strip(), "cls"))
        for m in PACKAGE.finditer(text):
            if latexsource.in_spans(m.start(), spans):
                continue
            for name in m.group(1).split(","):
                name = name.strip()
                if name and (name, "sty") not in found:
                    found.append((name, "sty"))
    return found


def check(base, master, say):
    """Say what the status list has to say about the book's class and
    packages, when any of them isn't rated compatible. Returns the counts,
    or None when the data file isn't installed."""
    path = kpsewhich(DATA, base)
    if not path:
        say("The tagging status check needs TeX's latex-tagging-status package, "
            "which isn't installed: `tlmgr install latex-tagging-status` on TeX "
            "Live or TinyTeX, or MiKTeX's package manager. It says which of the "
            "book's packages LaTeX's tagging can't take yet; without it, nothing "
            "is checked.")
        return None
    date, statuses = load(path)
    kernel = kernel_date(base)
    if date and kernel and date < kernel:
        say(f"The tagging status list is dated {date}, older than the LaTeX it "
            f"checks ({kernel}): `tlmgr update latex-tagging-status` brings it up "
            "to date.")
    groups, counts = {}, {}
    for name, ext in used(base, master):
        code = statuses.get((name, ext))
        if code == 100 or code == 4:
            counts["compatible"] = counts.get("compatible", 0) + 1
            continue
        label = STATUS.get(code, "not in the list")
        groups.setdefault(label, []).append(name + ("" if ext == "sty" else " (class)"))
        counts[label] = counts.get(label, 0) + 1
    if groups:
        order = ["never to be supported", "currently incompatible",
                 "partially compatible", "unchecked", "not in the list"]
        say("Tagging status of the book's class and packages (" + (date or "undated")
            + "): " + "; ".join(f"{label}: {', '.join(groups[label])}"
                                for label in order if label in groups)
            + f". The list only advises; {PAGE} says why, and what to use "
            "instead where there's a replacement.")
    return counts
