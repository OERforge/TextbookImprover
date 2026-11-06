"""
axecheck.py -- --wcag on HTML pages, reveal.js presentations, and an
EPUB's content documents: axe-core's rules for WCAG's criteria, run in
Playwright's Chromium, locked down (lockedbrowser.py).

check() is what check-output.py and audit.py call. It starts this file
as a worker in a process of its own (--worker), with the interpreter
running it, hands it the job as JSON, and reads its results back as
JSON lines, one for the run and one for each page; it never touches the
browser, and it stops a worker that runs past its time. The worker takes
itself off the network, starts Chromium, checks a probe page of its own
(and a probe presentation, when there are presentations to check) to
see that axe-core works and the lockdown holds, then checks the pages a
few at a time, each in a context of its own. Each step that could stall
has a time of its own and each page a budget(), so a page that holds a
step up is named as not checked and the rest go on, and the worker ends
when the run that started it does (watch_parent).

Which rules run: those whose WCAG criteria, from their tags (wcag143 is
1.4.3), are in the version and level --wcag-version and --wcag-level
choose, WCAG 2.1 AA by default (wcag.within), and axe-core's best
practices with --best-practice. Its experimental and deprecated rules
never run. The unit suite holds the criteria to axe-core's own level
tags (wcag2aa, wcag21aa), so a release that retags a rule is noticed.

A rule a page fails is a note, axe:<rule>, and what axe-core can't
decide is one too, axe-review:<rule>, never an error, as veraPDF's
findings are: --wcag is information, and what's installed doesn't decide
a run's verdict. Each names the criteria, the elements by axe-core's
selectors (each its own note with --verbose, with its markup), and
axe-core's page on the rule. A page whose computed color-scheme includes
dark, or that has a stylesheet for it, has its colors checked again in
dark mode.

A presentation TextbookImprover wrote is checked with its own scripts,
and no others: reveal.js and its plugins, byte for byte the repository's
(vendor/reveal.js, and REVEALJS_DIR's in a local run), oer-reveal.js as
the repository has it once each line's indent is set aside, which
Pandoc's template adds, and a start of reveal.js that's settings and
nothing else (revealtarget.start_settings). Each slide is shown with
all its steps, at its own size up to MOST_PIXELS and with motion
reduced, and checked in turn, the first 500 (LIMITS); reveal.js makes
the slides not shown inert, so each is checked once. A presentation
whose scripts aren't those isn't checked, and a note says why: without
its scripts reveal.js shows nothing.

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

import asyncio
import base64
import hashlib
import importlib.util
import json
import math
import os
import re
import signal
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lockedbrowser  # noqa: E402
import outputcheck  # noqa: E402
import revealtarget  # noqa: E402
import wcag  # noqa: E402
from findings import Finding  # noqa: E402

ROOT = os.path.dirname(HERE)
# The repository's axe-core, which a local run can trade for another
# with AXE_CORE_DIR, and a service can't (vendor/axe-core/README.md).
VENDORED = os.path.join(ROOT, "vendor", "axe-core")
AXE_VERSION = "4.14.0"
AXE_SHA256 = "20c09fe157a8a34a30e241aaa1fcdade657734f08ab379ecfbeb7d45cc46e878"
AXE_VARIABLE = "AXE_CORE_DIR"
INSTALL = "docs/installation.md, Optional: Playwright and its Chromium"
INSTALL_CHROMIUM = "python3 -m playwright install --with-deps --only-shell chromium"
NOT_RUN = "axe's WCAG checks not run"
NOT_RUN_QUICK = f"{NOT_RUN} (--quick)."
NOT_RUN_NO_PAGE = f"{NOT_RUN}: no page to check."
CAVEAT = "what it finds is a note, never a failure"
VERBOSE = ("Each rule's elements are counted, not listed: run again with --verbose for "
           "each one, with its markup.")
BEST_PRACTICE = "axe-core best practice"

# What of a page's text isn't written out as it is: control characters,
# which a terminal may act on, and the characters that reorder text
# around them; a line's end and a tab stay.
UNPRINTED = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069]")
# A criterion's tag, wcag143 for 1.4.3 and wcag1410 for 1.4.10.
CRITERION_TAG = re.compile(r"wcag(\d)(\d)(\d+)$")
# axe-core's rules a check of the output check's own covers too, and the
# check: both are reported, since their disagreeing is worth seeing, and
# the fix is the built-in check's.
OVERLAPS = {"image-alt": "image-without-alt", "document-title": "no-title",
            "html-has-lang": "no-lang", "label-content-name-mismatch": "link-label-without-text",
            "th-has-data-cells": "table-without-data-cells"}
# The rules whose result turns on a page's colors, run again in dark mode.
DARK_RULES = ("color-contrast", "color-contrast-enhanced", "link-in-text-block")
# How long a page has to load, and axe-core to finish with it (the
# largest page tried, 242 KB with 60 tables and 120 formulas, took 3.2
# seconds), in seconds; and the most slides of a presentation checked.
LIMITS = {"load": 30, "axe": 60, "slides": 500}
# What a rule's elements are listed to: the first few for the summary,
# and with --verbose, or a presentation's, whose slides share elements
# (its controls) that are reported once, more.
SHOWN, LISTED = 3, 200
# The most frames of a page checked; and the most pixels across or down
# a presentation's window, which its slides' own size sets: Chromium
# stalled, or crashed, opening a page 104,000 pixels square.
MOST_FRAMES, MOST_PIXELS = 50, 4096


# --------------------------------------------------------------------------
# which rules
# --------------------------------------------------------------------------

def criteria(tags):
    """A rule's WCAG criteria, from its tags, ["2.4.4", "4.1.2"]."""
    out = []
    for tag in tags:
        found = CRITERION_TAG.match(tag)
        if found:
            out.append(".".join(found.groups()))
    return out


def select(rules, version=wcag.DEFAULT_VERSION, level=wcag.DEFAULT_LEVEL,
           best_practice=False):
    """The rules to run, of axe-core's (dicts with id and tags): those with
    a criterion within the version and level, and with best_practice its
    best practices; never an experimental or deprecated one."""
    chosen = []
    for rule in rules:
        tags = rule.get("tags") or []
        if "experimental" in tags or "deprecated" in tags:
            continue
        if any(wcag.within(c, version, level) for c in criteria(tags)) \
                or (best_practice and "best-practice" in tags):
            chosen.append(rule)
    return chosen


def described(version, level, best_practice, count=None):
    """What ran, as the summary says it: "its 63 rules for WCAG 2.1 AA"."""
    rules = f"its {count} rules" if count is not None else "its rules"
    return (f"{rules} for {wcag.conformance(version, level)}"
            + (" and its best practices" if best_practice else ""))


# --------------------------------------------------------------------------
# the parent: check()
# --------------------------------------------------------------------------

def locate_axe(policy="local"):
    """(path, problem, note) for the axe-core to run: AXE_CORE_DIR's
    axe.min.js in a local run when it's set, else the repository's,
    which must be the file vendor/axe-core/README.md names, byte for
    byte. problem stops the check; note says a local run used a copy
    other than the repository's."""
    given = os.environ.get(AXE_VARIABLE, "").strip() if policy == "local" else ""
    folder = os.path.abspath(os.path.expanduser(given)) if given else VENDORED
    path = os.path.join(folder, "axe.min.js")
    if not os.path.isfile(path):
        if given:
            return None, (f"{AXE_VARIABLE} is {folder}, which has no axe.min.js (the "
                          "folder axe-core's package unpacks to, or npm's "
                          f"node_modules/axe-core); unset, the repository's own is used "
                          f"({INSTALL})."), ""
        return None, ("the repository's copy of axe-core, vendor/axe-core/axe.min.js, isn't "
                      f"there: a checkout of TextbookImprover has axe-core {AXE_VERSION} "
                      f"there, and {AXE_VARIABLE} can name the folder of another copy."), ""
    version = axe_version(path)
    if given:
        if not version.startswith("4."):
            return None, (f"{AXE_VARIABLE}'s axe.min.js is axe-core "
                          f"{version or 'of no version its header gives'}, where --wcag is "
                          f"written for axe-core 4; unset, the repository's own {AXE_VERSION} "
                          "is used."), ""
        if version != AXE_VERSION:
            return path, "", (f"axe-core {version}, from {AXE_VARIABLE}, where the "
                              f"repository's is {AXE_VERSION}, which the suites test.")
        return path, "", ""
    with open(path, "rb") as fh:
        found = hashlib.sha256(fh.read()).hexdigest()
    if found != AXE_SHA256:
        return None, ("vendor/axe-core/axe.min.js isn't the file the repository has (its "
                      f"SHA-256 is {found[:16]}…, where axe-core {AXE_VERSION}'s is "
                      f"{AXE_SHA256[:16]}…): check out the repository's copy again "
                      "(vendor/axe-core/README.md), or name another with "
                      f"{AXE_VARIABLE}."), ""
    return path, "", ""


def axe_version(path):
    """The version axe.min.js's header gives, /*! axe v4.14.0."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            head = fh.read(200)
    except OSError:
        return ""
    found = re.match(r"/\*! axe v(\d+\.\d+\.\d+\S*)", head)
    return found.group(1) if found else ""


def is_presentation(path):
    """Whether a page is a reveal.js presentation, to be checked as one:
    its markup has reveal.js's frame and something that starts it."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read(4 << 20)
    except OSError:
        return False
    return bool(re.search(r"""<div\s[^>]*class=["'][^"']*\breveal\b""", text)) \
        and "Reveal.initialize" in text


def budget(limits, presentation):
    """The seconds a page has to be checked in, all told: twice its load's
    (a presentation is opened twice) and twice axe-core's (a page's
    colors may be checked again in dark mode), or for a presentation,
    whose every slide is checked, ten times axe-core's."""
    return limits["load"] * 2 + limits["axe"] * (10 if presentation else 2)


def check(pages=(), epubs=(), *, version=wcag.DEFAULT_VERSION, level=wcag.DEFAULT_LEVEL,
          best_practice=False, verbose=False, policy="local", root=None, timeout=None,
          by_epub=False, limits=None):
    """(findings, lines) for axe-core's rules on the pages and on each
    EPUB's content documents: a note for each rule a page fails, or that
    axe-core couldn't decide, and the lines for the run's summary or a
    report, the first saying what ran and where, then what wasn't
    checked and why, then one for each rule. With nothing to check, the
    probes alone, which check the setup. root: the folder the pages are
    served from, by default the one they're all in. A content document's
    finding is filed under the document's name, as the output check's
    own are, or with by_epub under the EPUB's, as an audit's are.
    limits: LIMITS's, in seconds for a page's load and for axe-core, and
    the most slides of a presentation; and timeout the whole worker's,
    past which it's stopped, by default a budget() for each page shared
    among those checked at once, and three minutes."""
    limits = dict(LIMITS, **(limits or {}))
    if importlib.util.find_spec("playwright") is None:
        return [], [f"{NOT_RUN} on the pages: Playwright isn't installed ({INSTALL})."]
    axe, problem, note = locate_axe(policy)
    if problem:
        return [], [f"WARNING: {NOT_RUN} on the pages: {problem}"]
    pages = [os.path.abspath(p) for p in pages]
    if root is None and pages:
        root = os.path.commonpath([os.path.dirname(os.path.realpath(p)) for p in pages])
    items = []
    for path in pages:
        items.append({"id": len(items), "where": outputcheck.page_name(path),
                      "file": os.path.basename(path), "kind": "html",
                      "presentation": is_presentation(path), "folder": root,
                      "path": os.path.relpath(os.path.realpath(path), root).replace(os.sep, "/")})
    for epub in epubs:
        for name in outputcheck.epub_documents(epub):
            items.append({"id": len(items), "where": name,
                          "file": os.path.basename(epub) if by_epub else name.split("/")[-1],
                          "kind": "epub", "presentation": False,
                          "archive": os.path.abspath(epub), "path": name,
                          "epub": os.path.basename(epub)})
    revealjs = revealtarget.revealjs_folder()
    job = {"policy": policy, "axe": axe, "version": version, "level": level,
           "best_practice": bool(best_practice), "verbose": bool(verbose),
           "limits": limits, "width": max(1, min(4, os.cpu_count() or 1, len(items) or 1)),
           "revealjs": revealjs if policy == "local" and revealjs != revealtarget.VENDORED
           else None, "probe_presentation": any(i["presentation"] for i in items) or not items,
           "pages": [{k: v for k, v in item.items() if k in ("id", "kind", "presentation",
                                                              "folder", "archive", "path")}
                     for item in items]}
    if timeout is None:
        each = sum(budget(limits, i["presentation"]) for i in items)
        timeout = 180 + each / job["width"]
    events, stopped, said = run_worker(job, timeout)
    return report(items, events, stopped, said, job, note)


def run_worker(job, timeout):
    """(events, stopped, said): what the worker wrote, each line of its
    stdout a JSON object; whether it was stopped for running past
    timeout seconds; and the last line of its stderr."""
    command = [sys.executable, os.path.abspath(__file__), "--worker"]
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
    except OSError as exc:
        return [], False, f"the worker couldn't be started: {exc}"
    stopped = False
    try:
        out, err = process.communicate(json.dumps(job).encode("utf-8"), timeout=timeout)
    except subprocess.TimeoutExpired:
        stopped = True
        stop(process)
        out, err = process.communicate()
    except BaseException:
        # Interrupted: Ctrl-C reaches this process and not the worker, in a
        # session of its own, so it's stopped here.
        stop(process)
        raise
    events = []
    for line in out.decode("utf-8", "replace").splitlines():
        try:
            event = scrubbed(json.loads(line))
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    lines = [line.strip() for line in err.decode("utf-8", "replace").splitlines()
             if line.strip()]
    return events, stopped, lines[-1][:300] if lines else ""


def stop(process):
    """Stop the worker and what it started, its whole process group."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (OSError, AttributeError):
        process.kill()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def scrubbed(value):
    """The worker's word with the characters UNPRINTED names a space, in
    every string in it, since a page's text, its selectors and markup and
    addresses, goes to a terminal and a report."""
    if isinstance(value, str):
        return UNPRINTED.sub(" ", value)
    if isinstance(value, list):
        return [scrubbed(item) for item in value]
    if isinstance(value, dict):
        return {scrubbed(key): scrubbed(item) for key, item in value.items()}
    return value


# --------------------------------------------------------------------------
# what the worker found, as findings and lines
# --------------------------------------------------------------------------

def report(items, events, stopped, said, job, note=""):
    """(findings, lines) from the worker's events."""
    ready = next((e for e in events if e.get("event") == "ready"), None)
    failed = next((e for e in events if e.get("event") == "failed"), None)
    if ready is None:
        if failed and failed.get("kind") == "playwright":
            return [], [f"{NOT_RUN} on the pages: Playwright isn't installed ({INSTALL})."]
        if failed and failed.get("kind") == "chromium":
            return [], [f"{NOT_RUN} on the pages: Playwright's Chromium doesn't start "
                        f"({failed.get('why')}); `{INSTALL_CHROMIUM}` installs it ({INSTALL})."]
        why = (failed or {}).get("why") or (
            "it ran past the time it was given, and was stopped" if stopped else
            "it stopped without saying why" + (f" ({said})" if said else ""))
        return [], [f"WARNING: {NOT_RUN} on the pages: the worker that runs them failed: "
                    f"{why}."]
    meta = {rule["id"]: rule for rule in ready.get("rules", [])}
    problems = ready.get("problems") or []
    if problems:
        return [], [f"WARNING: {NOT_RUN} on the pages: " + "; ".join(problems)
                    + ", so nothing axe-core found is reported."]
    results = {e["id"]: e for e in events if e.get("event") == "page" and "id" in e}
    findings, groups = [], {}
    unchecked, scripted, outside, frames, past = [], [], [], [], []
    slides = presentations = documents = plain = 0
    for item in items:
        result = results.get(item["id"])
        if result is None:
            unchecked.append((item, "the worker was stopped before it" if stopped
                              else "the worker stopped before it"))
            continue
        if result.get("status") != "checked":
            unchecked.append((item, result.get("why") or "it couldn't be"))
            continue
        if item["presentation"]:
            presentations += 1
            slides += len(result.get("places") or [])
            if result.get("past"):
                past.append((item, int(result["past"]), len(result.get("places") or [])))
        elif item["kind"] == "epub":
            documents += 1
        else:
            plain += 1
        if result.get("scripts"):
            scripted.append(item)
        if result.get("outside"):
            outside.append((item, result["outside"]))
        if result.get("frames"):
            frames.append((item, result["frames"]))
        for place in result.get("places") or []:
            where = item["where"] + (place.get("route") or "")
            for dark, found in ((False, place.get("light")), (True, place.get("dark"))):
                for kind, prefix in (("violations", "axe"), ("incomplete", "axe-review")):
                    for rule in (found or {}).get(kind, []):
                        about = meta.get(rule.get("id"), {})
                        findings += rule_findings(item, where, prefix, rule, about,
                                                  job["verbose"], dark)
                        group = groups.setdefault((f"{prefix}:{rule.get('id')}", dark), {
                            "elements": 0, "pages": set(), "first": None, "each": [],
                            "keys": {}})
                        group["elements"] += int(rule.get("count") or 0)
                        group["pages"].add(item["where"])
                        for key, (n, message) in (rule.get("keys") or {}).items():
                            pair = group["keys"].setdefault(key, [0, message])
                            pair[0] += n
                        for node in rule.get("nodes") or []:
                            seen = (where, selector(node.get("target")),
                                    summary_text(node.get("summary")))
                            group["first"] = group["first"] or seen
                            group["each"].append(seen)
    lines = [head_line(ready, job, plain, presentations, slides, documents, items)]
    if note:
        lines.append(note)
    sandbox, network = ready.get("sandbox") or [None, ""], ready.get("network") or ""
    if sandbox[0] is False:
        lines.append(f"Chromium's sandbox wasn't on ({sandbox[1]}): a page that broke out of "
                     "Chromium's renderer would be outside it, which matters for a page from "
                     f"someone else ({INSTALL}).")
    elif sandbox[0] is None:
        lines.append(f"Whether Chromium's sandbox was on couldn't be seen ({sandbox[1]}), "
                     "though it was asked for.")
    if network:
        lines.append(f"The check wasn't off the network ({network}): what the browser was "
                     "served, and its resolving no name, kept the pages from reaching it.")
    if failed:
        lines.append(f"WARNING: the worker that runs axe-core failed partway: {failed.get('why')}.")
    lines += unchecked_lines(unchecked)
    if outside:
        lines.append(f"What {len(outside)} page(s) load from elsewhere wasn't loaded, so "
                     "their colors and sizes may differ from what a reader sees: "
                     + listed([f"{item['where']} ({', '.join(what[:2])}"
                               + (f", and {len(what) - 2} more" if len(what) > 2 else "") + ")"
                               for item, what in outside[:5]]
                              + ([f"{len(outside) - 5} more"] if len(outside) > 5 else []))
                     + ".")
    if scripted:
        lines.append(f"{len(scripted)} page(s) have scripts of their own, which didn't run, "
                     "so what they'd show isn't checked: "
                     + listed([item["where"] for item in scripted[:5]]
                              + ([f"{len(scripted) - 5} more"] if len(scripted) > 5 else []))
                     + ".")
    if frames:
        count = sum(len(what) for _, what in frames)
        lines.append(f"{count} frame(s) weren't checked, which aren't served from the folder, "
                     "weren't loaded, or are past the most a page's check takes "
                     f"({MOST_FRAMES}, five deep): "
                     + listed([f"{item['where']} ({', '.join(what[:2])}"
                               + (f", and {len(what) - 2} more" if len(what) > 2 else "") + ")"
                               for item, what in frames[:5]]
                              + ([f"{len(frames) - 5} more"] if len(frames) > 5 else []))
                     + ".")
    if past:
        most = int(dict(LIMITS, **(job.get("limits") or {}))["slides"])
        lines.append(f"{sum(n for _, n, _ in past)} slide(s) weren't checked, after the first "
                     f"{most} of a presentation: "
                     + listed([f"{item['where']} ({n} of {n + done})"
                               for item, n, done in past[:5]]
                              + ([f"{len(past) - 5} more"] if len(past) > 5 else []))
                     + ".")
    lines += rule_lines(groups, meta, job["verbose"])
    return findings, lines


def head_line(ready, job, plain, presentations, slides, documents, items):
    """The summary's first line: what ran, on what, and how."""
    what = described(job["version"], job["level"], job["best_practice"],
                     len(ready.get("rules") or []))
    places = []
    if plain:
        places.append(f"{plain} page(s)")
    if presentations:
        places.append(f"{slides} slide(s) of {presentations} presentation(s)")
    if documents:
        epubs = len({i.get("epub") for i in items if i["kind"] == "epub"})
        places.append(f"{documents} content document(s) of {epubs} EPUB(s)")
    browser = (f"in Playwright {ready.get('playwright', '?')}'s Chromium "
               f"{str(ready.get('chromium', '?')).split('.')[0]}")
    sandboxed = (ready.get("sandbox") or [None])[0]
    how = ("sandboxed" if sandboxed is True else "not sandboxed" if sandboxed is False
           else "its sandbox unseen") \
        + (" and off the network" if not ready.get("network") else " and on the network")
    if not items:
        return (f"axe-core {ready.get('axe', '?')} ran {what} on a probe page of its own"
                + (" and a probe presentation" if ready.get("presentation") else "")
                + f", {browser}, {how}: it found the probe's problems, the probe's script "
                "didn't run, its requests elsewhere were refused, and its refresh canceled, "
                "so pages can be checked" + (", and presentations TextbookImprover wrote too"
                                             if ready.get("presentation") else "") + ".")
    own = ", but in a presentation TextbookImprover's own" if presentations else ""
    return (f"axe-core {ready.get('axe', '?')} ran {what} on {listed(places) or 'nothing'}, "
            f"{browser}, {how}, with each page's own scripts blocked{own}: {CAVEAT}.")


def unchecked_lines(unchecked):
    """A line for the pages axe-core didn't check, and one for the
    presentations it didn't, each with why."""
    lines = []
    shows = [(item, why) for item, why in unchecked if item["presentation"]]
    pages = [(item, why) for item, why in unchecked if not item["presentation"]]
    if pages:
        lines.append(f"axe-core didn't check {len(pages)} page(s): "
                     + listed([f"{item['where']} ({why})" for item, why in pages[:5]]
                              + ([f"{len(pages) - 5} more"] if len(pages) > 5 else [])) + ".")
    if shows:
        lines.append(f"axe-core didn't check {len(shows)} presentation(s), whose scripts "
                     "it runs only when they're TextbookImprover's own: "
                     + listed([f"{item['where']} ({why})" for item, why in shows[:5]]
                              + ([f"{len(shows) - 5} more"] if len(shows) > 5 else [])) + ".")
    return lines


def rule_findings(item, where, prefix, rule, meta, verbose, dark=False):
    """The findings for one rule a page, a slide, or a content document
    failed or left undecided: one, counting its elements, or with
    verbose one for each element axe-core listed, and one for those it
    didn't."""
    check = f"{prefix}:{rule.get('id', '?')}"
    found = criteria(meta.get("tags") or [])
    standard = "; ".join(wcag.standard(c) for c in found) or BEST_PRACTICE
    fix = "manual"
    if rule.get("id") in OVERLAPS:
        import findings as findings_lib
        fix = findings_lib.CHECKS.get(OVERLAPS[rule["id"]], ("", "", "", "manual"))[3]
    about = criteria_text(found)
    page = axe_page(meta)
    lead = ("In dark mode: " if dark else "") + str(meta.get("help") or rule.get("id"))
    if rule.get("impact"):
        lead += f" ({rule['impact']})"
    if prefix == "axe-review":
        lead += ", which axe-core couldn't decide, for a person to judge"
    nodes, count = rule.get("nodes") or [], int(rule.get("count") or 0)

    def note(detail):
        return Finding(where, check, detail, file=item["file"], kind=item["kind"],
                       severity="note", standard=standard, tool="axe", fix=fix)

    if not verbose:
        named = [selector(n.get("target")) for n in nodes[:SHOWN]]
        at = listed(named + ([f"{count - len(named)} more"] if count > len(named) else []))
        why = reasons(rule) if prefix == "axe-review" else ""
        return [note(f"{lead}: {count} element(s), at {at}{why}; --verbose lists each, "
                     f"with its markup. {about}. {page}")]
    out = []
    for node in nodes:
        summary = summary_text(node.get("summary"))
        markup = " ".join(str(node.get("html") or "").split())
        markup = markup[:120] + ("…" if len(markup) > 120 else "")
        out.append(note(f"{lead}, at {selector(node.get('target'))}: "
                        + (f"{summary}; " if summary else "")
                        + f"its markup, {markup}. {about}. {page}"))
    if count > len(nodes):
        out.append(note(f"{lead}: {count - len(nodes)} more element(s), which axe-core "
                        f"found and the check doesn't list. {about}. {page}"))
    return out


def summary_text(text):
    """axe-core's summary of what an element failed, on one line: "Fix
    any of the following: A; B"."""
    out = ""
    for part in (line.strip() for line in str(text or "").splitlines()):
        if part:
            out = part if not out else out + (" " if out.endswith(":") else "; ") + part
    return out


def criteria_text(found):
    """The criteria as a finding names them, each with its number,
    handle, and level, and the first's Understanding document."""
    if not found:
        return "A best practice of axe-core's, beyond WCAG's criteria"
    return " and ".join(wcag.named(c) for c in found) + f": {wcag.url(found[0])}"


def axe_page(meta):
    """axe-core's page on a rule, its address without the query that
    names the tool that asked."""
    address = str(meta.get("url") or "").split("?", 1)[0]
    return f"axe-core's rule: {address}." if address else ""


def reasons(rule):
    """Why axe-core couldn't decide, by its reason (a check's messageKey):
    "; 15 because Element content contains only non-text characters"."""
    parts = sorted((pair for pair in (rule.get("keys") or {}).values() if pair[1]),
                   key=lambda pair: -pair[0])
    if not parts:
        return ""
    return "; " + ", ".join(f"{n} because {short(message)}" for n, message in parts[:4])


def short(message, most=100):
    """One of axe-core's messages, without its full stop, cut to most."""
    text = " ".join(str(message).split()).rstrip(".")
    return text[:most] + ("…" if len(text) > most else "")


def selector(target):
    """An element as axe-core names it: its CSS selector, and in a frame,
    the frame's after it; a selector into a shadow tree is a list."""
    if not isinstance(target, list) or not target:
        return str(target or "?")

    def one(part):
        return " >>> ".join(map(str, part)) if isinstance(part, list) else str(part)
    text = one(target[-1])
    for frame in reversed(target[:-1]):
        text += f", in the frame at {one(frame)}"
    return text


def rule_lines(groups, meta, verbose):
    """A line for each rule in the summary: its check and criteria, how
    many elements on how many pages, the first, and what it means; and
    with verbose a line under it for each element, the first twenty."""
    lines = []
    for check, dark in sorted(groups, key=lambda key: (key[0].startswith("axe-review:"),
                                                       key[0].split(":", 1)[1], key[1])):
        group = groups[(check, dark)]
        rule = check.split(":", 1)[1]
        about = meta.get(rule, {})
        found = criteria(about.get("tags") or [])
        named = " and ".join(wcag.named(c) for c in found) or "a best practice"
        overlap = f", as {OVERLAPS[rule]} checks too" if rule in OVERLAPS else ""
        first = group["first"]
        review = check.startswith("axe-review:")
        lines.append(f"{check}{' in dark mode' if dark else ''}, {named}{overlap}: "
                     f"{group['elements']} element(s) on {len(group['pages'])} page(s)"
                     + (" axe-core couldn't decide, for a person to judge" if review else "")
                     + (f", the first in {first[0]} at {first[1]}" if first else "")
                     + (reasons({"keys": group["keys"]}) if review else "")
                     + f": {about.get('help') or rule}. "
                     + (wcag.url(found[0]) if found else
                        str(about.get("url") or "").split("?", 1)[0]))
        if verbose:
            for where, at, said in group["each"][:20]:
                lines.append(f"  {where} at {at}" + (f": {said}" if said else ""))
            if len(group["each"]) > 20:
                lines.append(f"  and {len(group['each']) - 20} more, in the report")
    if lines and not verbose:
        lines.append(VERBOSE)
    return lines


def listed(names):
    names = [str(n) for n in names]
    if len(names) < 3:
        return " and ".join(names)
    return ", ".join(names[:-1]) + ", and " + names[-1]


# --------------------------------------------------------------------------
# the worker
# --------------------------------------------------------------------------

# What runs in the page, the frames, and a blank page beside them, as
# axe-core's Playwright integration runs it: runPartial in the page and
# in each frame served from the folder, depth first, then finishRun.
CONTEXT = {"include": [], "exclude": []}
RULES = """() => axe.getRules().map(r => ({id: r.ruleId, tags: r.tags, help: r.help,
    description: r.description, url: r.helpUrl}))"""
FRAME_CONTEXTS = "context => axe.utils.getFrameContexts(context)"
SHADOW_SELECT = "selector => axe.utils.shadowSelect(selector)"
# A frame's partial results go through Python as JSON text, as axe-core's
# own integration passes them: brought back as objects, a check's result
# of undefined, which marks one axe-core couldn't decide, comes back as
# null, and finishRun then gives it the message for a check that failed.
RUN_PARTIAL = "async ([context, options]) => JSON.stringify(await axe.runPartial(context, options))"
# finishRun, and the results brought back short: each rule's count, its
# reasons (messageKey) counted, and its first elements, each's selector,
# the start of its markup, and axe-core's summary of what failed.
FINISH = """async ([partials, options, shown]) => {
  const result = await axe.finishRun(partials.map(p => p === null ? null : JSON.parse(p)),
                                     options);
  const reason = node => {
    const checks = [...(node.any || []), ...(node.all || []), ...(node.none || [])];
    const keyed = checks.find(c => c && c.data && c.data.messageKey);
    const check = keyed || checks[0];
    return check ? [keyed ? String(keyed.data.messageKey) : String(check.id),
                    String(check.message || '').slice(0, 200)] : ['', ''];
  };
  const brief = list => list.map(rule => {
    const keys = {};
    for (const node of rule.nodes) {
      const [key, message] = reason(node);
      if (!keys[key]) keys[key] = [0, message];
      keys[key][0] += 1;
    }
    return {id: rule.id, impact: rule.impact, count: rule.nodes.length, keys,
            nodes: rule.nodes.slice(0, shown).map(node => ({
              target: node.target, html: String(node.html || '').slice(0, 200),
              summary: String(node.failureSummary || '').slice(0, 400),
              key: reason(node)[0]}))};
  });
  return {violations: brief(result.violations), incomplete: brief(result.incomplete)};
}"""
# Whether a page changes in dark mode: a color-scheme with dark in it, or
# a stylesheet, or a rule in one, for prefers-color-scheme.
DARK = """() => {
  if (/\\bdark\\b/.test(getComputedStyle(document.documentElement).colorScheme || '')) return true;
  const asks = text => /prefers-color-scheme/.test(text || '');
  const inside = rules => Array.from(rules || []).some(rule =>
    (rule.media && asks(rule.media.mediaText)) || (rule.cssRules && inside(rule.cssRules)));
  return Array.from(document.styleSheets).some(sheet => {
    try { return (sheet.media && asks(sheet.media.mediaText)) || inside(sheet.cssRules); }
    catch (e) { return false; }
  });
}"""
# An XHTML document that isn't well-formed is shown as far as it parsed,
# with Chromium's account of the error, which isn't the page.
UNPARSED = """() => document.getElementsByTagName('parsererror').length > 0
    || document.documentElement.localName !== 'html'"""
# What's moving brought to its end, then two frames drawn: reveal.js fades
# a slide's background in over 0.8 seconds, which oer-reveal.css's
# reduced motion doesn't stop, and caught partway, a gray slide's
# background is all but white, its white text unreadable on it.
SETTLE = """() => {
  for (const motion of document.getAnimations()) {
    try { motion.finish(); } catch (e) { /* one that never ends */ }
  }
  return new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done)));
}"""
# A presentation's scripts, as its first load, every one blocked, has
# them: [address, or null for an inline script, its text]; a script of a
# type no browser runs isn't one.
SCRIPTS = """() => Array.from(document.scripts).filter(s => {
    const type = (s.type || '').trim().toLowerCase();
    return type === '' || type === 'module'
      || /^(text|application)\\/(x-)?(java|ecma)script$/.test(type);
  }).map(s => s.hasAttribute('src') ? [s.src, ''] : [null, s.text])"""
READY = """() => typeof Reveal !== 'undefined' && typeof Reveal.isReady === 'function'
    && Reveal.isReady()"""
ROLE = """() => { const deck = document.querySelector('.reveal');
    return deck ? deck.getAttribute('role') : null; }"""
SLIDE_COUNT = "() => Reveal.getSlides().length"
# A slide shown with all its steps, and its route: reveal.js's to it,
# #/ and its id, or its place.
STEP = """index => {
  const slide = Reveal.getSlides()[index];
  const at = Reveal.getIndices(slide);
  Reveal.slide(at.h, at.v || 0);
  let steps = 0;
  while (steps < 500 && Reveal.nextFragment()) steps += 1;
  return slide.id ? '#/' + slide.id : '#/' + at.h + (at.v ? '/' + at.v : '');
}"""

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNg"
                       "YGD4DwABBAEAwS2OUAAAAABJRU5ErkJggg==")
PROBE_TITLE = "axe-core's probe"
# The probe page: no language, a picture without alt text, a script that
# would change its title, a picture from elsewhere, one from outside its
# files, and a refresh to elsewhere. axe-core must find the first two,
# the title must stay, the pictures be refused, and the refresh canceled.
PROBE_PAGE = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{PROBE_TITLE}</title>
<meta http-equiv="refresh" content="0; url=https://elsewhere.invalid/">
</head><body><main><h1>A probe</h1>
<p><img src="nameless.png"></p>
<p><img src="https://elsewhere.invalid/picture.png" alt="A picture from elsewhere"></p>
<p><img src="../../../etc/hostname" alt="A file outside the probe's"></p>
<script>document.title = "changed by the probe's script";</script>
</main></body></html>""".encode("utf-8")
PROBE_FILES = {"probe.html": PROBE_PAGE, "nameless.png": PNG}


def probe_presentation_files(shipped_folder=None):
    """The probe presentation's files: two slides, the second with a
    picture without alt text, loading the repository's reveal.js and
    oer-reveal.js as revealtarget writes them."""
    folder = shipped_folder or revealtarget.VENDORED
    files = {"nameless.png": PNG}
    for name in revealtarget.REVEALJS_FILES:
        try:
            with open(os.path.join(folder, name), "rb") as fh:
                files["reveal.js/" + name] = fh.read()
        except OSError:
            pass
    with open(revealtarget.SCRIPT, encoding="utf-8") as fh:
        script = fh.read()
    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>A probe presentation</title>
<link rel="stylesheet" href="reveal.js/dist/reset.css">
<link rel="stylesheet" href="reveal.js/dist/reveal.css">
<link rel="stylesheet" href="reveal.js/dist/theme/white.css">
</head><body><div class="reveal"><div class="slides">
<section id="one" class="slide level2"><h2>One</h2><p>The first slide.</p></section>
<section id="two" class="slide level2"><h2>Two</h2><p><img src="nameless.png"></p></section>
</div></div>
<script src="reveal.js/dist/reveal.js"></script>
<script src="reveal.js/dist/plugin/notes.js"></script>
<script src="reveal.js/dist/plugin/search.js"></script>
<script src="reveal.js/dist/plugin/zoom.js"></script>
<script>
      Reveal.initialize({{
        hash: true,
        width: 1280,
        height: 720,
        plugins: [RevealNotes, RevealSearch, RevealZoom]
      }});
</script>
<script>
{script}</script>
</body></html>"""
    files["probe-presentation.html"] = page.encode("utf-8")
    return files


def shipped_scripts(extra=None):
    """{SHA-256: name} of the script files a presentation may load:
    reveal.js and the plugins Pandoc's template loads, the repository's
    and, given, another copy's (REVEALJS_DIR's)."""
    found = {}
    for folder in [revealtarget.VENDORED] + ([extra] if extra else []):
        for name in revealtarget.REVEALJS_FILES:
            if not name.endswith(".js"):
                continue
            try:
                with open(os.path.join(folder, name), "rb") as fh:
                    found.setdefault(hashlib.sha256(fh.read()).hexdigest(), name)
            except OSError:
                continue
    return found


def script_lines(text):
    """A script's lines with each line's indent and trailing spaces set
    aside, as it's compared with oer-reveal.js."""
    return [line.strip() for line in text.strip().splitlines()]


def policy_hash(text):
    """A Content Security Policy's source for an inline script's text."""
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()
                                         ).decode("ascii") + "'"


def judge_scripts(scripts, source, shipped, oer_lines):
    """What a presentation's scripts are, from its first load: {"hashes":
    the policy sources of its start of reveal.js and of oer-reveal.js,
    "settings": its start's, "own": how many scripts of its own it has,
    which stay blocked, "problem": why it's not TextbookImprover's, and
    so isn't checked, or ""}."""
    files, own, start, oer, other_oer = [], 0, [], None, False
    for address, text in scripts:
        if address is not None:
            path = lockedbrowser.path_of(address)
            data = source.read(path) if path is not None else None
            name = shipped.get(hashlib.sha256(data).hexdigest()) \
                if isinstance(data, bytes) else None
            if name:
                files.append(name)
            else:
                own += 1
        elif script_lines(text) == oer_lines:
            oer = text
        elif "Reveal.initialize" in text:
            start.append(text)
        else:
            own += 1
            other_oer = other_oer or "oer-reveal.js --" in text
    verdict = {"hashes": [], "settings": {}, "own": own, "problem": ""}
    if "dist/reveal.js" not in files:
        verdict["problem"] = "it doesn't load the repository's copy of reveal.js"
    elif len(start) != 1:
        verdict["problem"] = (f"it has {'no' if not start else len(start)} start"
                              f"{'' if len(start) == 1 else 's'} of reveal.js, where "
                              "Pandoc's template writes one")
    elif oer is None:
        verdict["problem"] = ("its oer-reveal.js isn't this version of TextbookImprover's"
                              if other_oer else "it has no oer-reveal.js")
    else:
        settings, problem = revealtarget.start_settings(start[0])
        if problem:
            verdict["problem"] = f"its start of reveal.js holds more than settings: {problem}"
        else:
            verdict["settings"] = settings
            verdict["hashes"] = [policy_hash(start[0]), policy_hash(oer)]
    return verdict


def slide_viewport(settings):
    """The window a presentation's slides are checked in: the slide's
    size with reveal.js's margin around it, so it's shown at its own
    size, and wider than 1000 pixels, past which oer-reveal.js shows the
    slides as a page; but no more than MOST_PIXELS across or down, in
    which reveal.js shows a larger slide smaller, as a reader's window
    would."""
    def number(name, default):
        value = settings.get(name)
        return value if isinstance(value, float) and value > 0 else default
    width, height = number("width", 960.0), number("height", 700.0)
    margin = settings.get("margin")
    margin = margin if isinstance(margin, float) and 0 <= margin < 1 else 0.04
    across, down = width * (1 + margin), height * (1 + margin)
    if across <= 1000:
        down, across = down * 1001 / across, 1001
    across, down = min(across, MOST_PIXELS), min(down, MOST_PIXELS)
    # Rounded first, so 720 × 1.1 is 792, not 793 from its last bit.
    return int(math.ceil(round(across, 6))), int(math.ceil(round(down, 6)))


def worker_main():
    """The worker: a job as JSON on stdin, results as JSON lines on
    stdout. Anything else written to stdout goes to stderr."""
    parent = os.getppid()
    out = os.fdopen(os.dup(1), "w", encoding="utf-8")
    os.dup2(2, 1)

    def emit(event):
        out.write(json.dumps(event) + "\n")
        out.flush()
    try:
        job = json.load(sys.stdin)
    except ValueError as exc:
        emit({"event": "failed", "why": f"its job couldn't be read ({exc})"})
        return 0
    network = lockedbrowser.leave_network()
    if network and job.get("policy") == "service":
        emit({"event": "failed", "why": f"it couldn't leave the network ({network})"})
        return 0
    # Only now: a process with a second thread can't leave the network,
    # since unshare refuses it a user namespace.
    watch_parent(parent)
    try:
        asyncio.run(work(job, network, emit))
    except lockedbrowser.Refused as exc:
        emit({"event": "failed", "why": str(exc)})
    except Exception as exc:            # anything else: said, and the run goes on
        emit({"event": "failed", "why": first_line(exc)})
    return 0


def watch_parent(parent):
    """End the worker once the run that started it, parent, is gone. It's
    in a session of its own, so as to be stopped whole when it runs too
    long, and so isn't stopped with that run otherwise; when it ends,
    Playwright's driver, and Chromium, end with it."""
    def watch():
        while os.getppid() == parent:
            time.sleep(1)
        os._exit(1)
    threading.Thread(target=watch, name="parent", daemon=True).start()


def first_line(exc):
    lines = [line.strip() for line in str(exc).splitlines() if line.strip()]
    return (lines[0] if lines else type(exc).__name__)[:300]


async def work(job, network, emit):
    try:
        from playwright.async_api import async_playwright
        from importlib import metadata
    except ImportError:
        emit({"event": "failed", "kind": "playwright", "why": "Playwright isn't installed"})
        return
    if job["policy"] not in lockedbrowser.POLICIES:
        emit({"event": "failed", "why": f"no policy {job['policy']}"})
        return
    path = job["axe"] if job["policy"] == "local" else os.path.join(VENDORED, "axe.min.js")
    with open(path, encoding="utf-8") as fh:
        axe = fh.read()
    shipped = shipped_scripts(job.get("revealjs") if job["policy"] == "local" else None)
    with open(revealtarget.SCRIPT, encoding="utf-8") as fh:
        oer_lines = script_lines(fh.read())
    limits = dict(LIMITS, **(job.get("limits") or {}))
    async with async_playwright() as play:
        try:
            browser, sandbox_why = await lockedbrowser.launch(play, job["policy"])
        except lockedbrowser.Refused:
            raise
        except Exception as exc:        # Chromium not installed, or not starting
            emit({"event": "failed", "kind": "chromium",
                  "why": lockedbrowser.launch_reason(exc)})
            return
        checker = Checker(browser, axe, shipped, oer_lines, limits, job)
        try:
            ready = await checker.probe()
            # Launched without its sandbox, Chromium says why; with it, /proc
            # says whether its renderers are in it.
            if sandbox_why:
                ready["sandbox"] = [False, sandbox_why]
            if job["policy"] == "service" and ready["sandbox"][0] is not True:
                raise lockedbrowser.Refused(
                    f"Chromium's sandbox isn't on: {ready['sandbox'][1]}")
            try:
                version = metadata.version("playwright")
            except Exception:           # installed in a way metadata can't see
                version = "?"
            ready.update({"event": "ready", "playwright": version,
                          "chromium": browser.version, "network": network})
            emit(ready)
            if ready["problems"]:
                return
            gate = asyncio.Semaphore(max(1, int(job.get("width") or 1)))

            async def one(item):
                async with gate:
                    result = await checker.check_item(item)
                emit(dict(result, event="page", id=item["id"]))
            await asyncio.gather(*(one(item) for item in job["pages"]))
            emit({"event": "done"})
        finally:
            checker.close()
            if checker.blank_context is not None:
                await lockedbrowser.close_quietly(checker.blank_context)
            await lockedbrowser.close_quietly(browser)


class Checker:
    """What the worker checks pages with: the browser, axe-core, the
    rules, and the scripts a presentation may run."""

    def __init__(self, browser, axe, shipped, oer_lines, limits, job):
        self.browser, self.axe, self.shipped, self.oer_lines = browser, axe, shipped, oer_lines
        self.limits, self.job = limits, job
        self.options = self.dark_options = None
        self.archives, self.folders = {}, {}
        # One blank page finishes every run, one at a time, since axe-core
        # runs once at a time in a page.
        self.blank, self.blank_context, self.finishing = None, None, asyncio.Lock()

    def close(self):
        for archive in self.archives.values():
            archive.close()

    async def finish(self, partials, options, shown):
        async with self.finishing:
            if self.blank is None:
                self.blank_context, self.blank = await lockedbrowser.blank_page(self.browser)
                await self.blank.evaluate(self.axe)
            try:
                return await self.blank.evaluate(FINISH, [partials, options, shown])
            except BaseException:
                # Stopped partway (a page past its time), the page may still be
                # running it: the next run gets a page of its own.
                context, self.blank, self.blank_context = self.blank_context, None, None
                await lockedbrowser.close_quietly(context)
                raise

    def source(self, item):
        if item.get("archive"):
            if item["archive"] not in self.archives:
                self.archives[item["archive"]] = lockedbrowser.Archive(item["archive"])
            return self.archives[item["archive"]]
        if item["folder"] not in self.folders:
            self.folders[item["folder"]] = lockedbrowser.Folder(item["folder"])
        return self.folders[item["folder"]]

    async def probe(self):
        """The probe page checked, and the presentation's when asked for:
        {"axe": its version, "rules": the rules chosen, "sandbox": [on,
        why], "presentation": whether the probe presentation was checked,
        "problems": what didn't hold}."""
        problems = []
        # The probes' own limits are never less than the usual, whatever a
        # job asks of its pages.
        limits = {name: max(value, LIMITS[name]) for name, value in self.limits.items()}
        source = lockedbrowser.Memory(PROBE_FILES)
        context, page, visit = await lockedbrowser.open_page(
            self.browser, source, "probe.html", load=limits["load"])
        try:
            for _ in range(30):
                if visit.canceled:
                    break
                await asyncio.sleep(0.1)
            await page.evaluate(self.axe)
            version = await page.evaluate("() => axe.version")
            rules = await page.evaluate(RULES)
            chosen = select(rules, self.job["version"], self.job["level"],
                            self.job["best_practice"])
            self.options = axe_options([rule["id"] for rule in chosen])
            dark = [rule["id"] for rule in chosen if rule["id"] in DARK_RULES]
            self.dark_options = axe_options(dark) if dark else None
            sandbox = list(lockedbrowser.sandbox_state())
            found = await self.timed(page, self.options, SHOWN, visit, [], limits["axe"])
            failed = {rule["id"] for rule in found["violations"]}
            if not {"html-has-lang", "image-alt"} <= failed:
                problems.append("the probe page didn't fail axe-core's html-has-lang and "
                                "image-alt, as it "
                                "should (it failed " + (", ".join(sorted(failed)) or "nothing")
                                + ")")
            # The document's own title: Playwright 1.64's page.title() gives
            # "Loading https://elsewhere.invalid/" once the refresh there is
            # canceled, where 1.63's gave the document's.
            if await page.evaluate("() => document.title") != PROBE_TITLE:
                problems.append("the probe page's script ran")
            blocked = await lockedbrowser.blocked(page.main_frame)
            if not any(uri.startswith("https://elsewhere.invalid/") for _, uri in blocked) \
                    and not any(url.startswith("https://elsewhere.invalid/")
                                for _, url, _ in visit.refused):
                problems.append("the probe page loaded a picture from elsewhere")
            if not any(why == "not there" for _, _, why in visit.refused):
                problems.append("the probe page wasn't refused a file outside its own")
            if not visit.canceled or page.url != visit.url:
                problems.append("the probe page left for elsewhere, its refresh not canceled")
        finally:
            await lockedbrowser.close_quietly(context)
        ready = {"axe": version, "rules": chosen, "sandbox": sandbox, "problems": problems,
                 "presentation": False}
        if not problems and self.job.get("probe_presentation"):
            source = lockedbrowser.Memory(probe_presentation_files())
            kept, self.limits = self.limits, limits
            try:
                result = await self.check_presentation(source, "probe-presentation.html")
            finally:
                self.limits = kept
            places = {place["route"]: place for place in result.get("places") or []}
            if result.get("status") != "checked":
                problems.append(f"the probe presentation wasn't checked: {result.get('why')}")
            elif not any(rule["id"] == "image-alt" for rule in
                         places.get("#/two", {}).get("light", {}).get("violations", [])) \
                    or any(rule["id"] == "image-alt" for rule in
                           places.get("#/one", {}).get("light", {}).get("violations", [])):
                problems.append("the probe presentation's picture without alt text wasn't "
                                "found on its "
                                "second slide alone")
            ready["presentation"] = not problems
        return ready

    async def run(self, page, options, shown, visit, unchecked):
        """axe-core's results for a page and its frames, as FINISH brings
        them back."""
        partials = await self.partials(page.main_frame, CONTEXT, options, visit, unchecked, [0])
        return await self.finish(partials, options, shown)

    async def timed(self, page, options, shown, visit, unchecked, seconds):
        """run's results, or Slow when axe-core hasn't finished after
        seconds."""
        return await lockedbrowser.within(
            self.run(page, options, shown, visit, unchecked), seconds,
            f"axe-core hadn't finished after {seconds} seconds")

    async def partials(self, frame, context, options, visit, unchecked, counted, depth=0):
        """runPartial's results in a frame and the frames in it, depth first,
        None for a frame not checked: one not served from the folder (a
        refused frame shows Chromium's error page), or past MOST_FRAMES."""
        contexts = await frame.evaluate(FRAME_CONTEXTS, context)
        out = [await frame.evaluate(RUN_PARTIAL, [context, options])]
        for entry in contexts:
            below = None
            try:
                handle = await frame.evaluate_handle(SHADOW_SELECT, entry["frameSelector"])
                element = handle.as_element()
                child = await element.content_frame() if element else None
                url = child.url.split("#", 1)[0] if child else ""
                if child is None or depth >= 5 or counted[0] >= MOST_FRAMES or not (
                        url in visit.documents or url in ("about:blank", "about:srcdoc")):
                    # Named by its src: a refused frame's address is its error page's.
                    named = (await element.get_attribute("src") if element else "") or url
                    if len(unchecked) < 20:
                        unchecked.append(" ".join(str(named or "a frame").split())[:80])
                else:
                    counted[0] += 1
                    if not await child.evaluate("() => typeof axe !== 'undefined'"):
                        await child.evaluate(self.axe)
                    below = await self.partials(child, entry["frameContext"], options, visit,
                                                unchecked, counted, depth + 1)
            except Exception:           # a frame gone, or one axe-core can't run in
                below = None
            out += below if below else [None]
        return out

    async def check_item(self, item):
        """A page's results: {"status": "checked" or "not checked", "why",
        "places": [{"route", "light", "dark"}], "scripts": whether it has
        scripts of its own, which didn't run, "outside": what it loads from
        elsewhere that would change its look, "frames": the frames not
        checked, "past": a presentation's slides past the most checked}.
        Each step that could stall has a time of its own, and the whole a
        budget, so no page holds up the others for long."""
        presentation = bool(item.get("presentation"))
        seconds = budget(self.limits, presentation)
        try:
            source = self.source(item)
            check = self.check_presentation if presentation else self.check_page
            return await lockedbrowser.within(
                check(source, item["path"]), seconds,
                f"it wasn't checked in the {seconds} seconds it was given")
        except lockedbrowser.Slow as exc:
            return {"status": "not checked", "why": str(exc)}
        except Exception as exc:        # Playwright's, the page's, or the source's
            text = first_line(exc)
            if "Timeout" in text and "exceeded" in text:
                text = f"it hadn't loaded after {self.limits['load']} seconds"
            return {"status": "not checked", "why": text}

    async def check_page(self, source, path):
        context, page, visit = await lockedbrowser.open_page(
            self.browser, source, path, load=self.limits["load"])
        try:
            if await page.evaluate(UNPARSED):
                return {"status": "not checked",
                        "why": "it isn't well-formed XHTML, which the EPUB's checks report"}
            await page.evaluate(self.axe)
            await page.evaluate(SETTLE)
            unchecked = []
            shown = LISTED if self.job["verbose"] else SHOWN
            light = await self.timed(page, self.options, shown, visit, unchecked,
                                     self.limits["axe"])
            dark = None
            if self.dark_options and await page.evaluate(DARK):
                await page.emulate_media(color_scheme="dark")
                await page.evaluate(SETTLE)
                dark = await self.timed(page, self.dark_options, shown, visit, [],
                                        self.limits["axe"])
            return dict(await self.about(page, visit), status="checked", frames=unchecked,
                        places=[{"route": "", "light": light, "dark": dark}])
        finally:
            await lockedbrowser.close_quietly(context)

    async def about(self, page, visit):
        """What a page did that the check didn't follow: its own scripts,
        blocked, and what it loads from elsewhere that would change its
        look, a stylesheet or a font, refused."""
        blocked = await lockedbrowser.blocked(page.main_frame)
        scripts = any(directive.startswith("script-src") for directive, _ in blocked)
        outside = []
        for directive, uri in blocked:
            kind = {"style-src-elem": "the stylesheet", "style-src": "the stylesheet",
                    "font-src": "the font"}.get(directive)
            if kind and f"{kind} {uri}" not in outside:
                outside.append(f"{kind} {uri}")
        for kind, url, why in visit.refused:
            name = {"stylesheet": "the stylesheet", "font": "the font"}.get(kind)
            if name and f"{name} {url}" not in outside:
                outside.append(f"{name} {url}")
        return {"scripts": scripts, "outside": outside[:10]}

    async def check_presentation(self, source, path):
        """A presentation checked slide by slide with its own scripts, when
        they're TextbookImprover's (judge_scripts)."""
        context, page, visit = await lockedbrowser.open_page(
            self.browser, source, path, load=self.limits["load"])
        try:
            scripts = await page.evaluate(SCRIPTS)
        finally:
            await lockedbrowser.close_quietly(context)
        verdict = judge_scripts(scripts, source, self.shipped, self.oer_lines)
        if verdict["problem"]:
            return {"status": "not checked", "why": verdict["problem"]}
        width, height = slide_viewport(verdict["settings"])
        context, page, visit = await lockedbrowser.open_page(
            self.browser, source, path, scripts="'self' " + " ".join(verdict["hashes"]),
            allowed=self.shipped, viewport=(width, height), load=self.limits["load"])
        try:
            try:
                await page.wait_for_function(READY, timeout=self.limits["load"] * 1000)
            except Exception:
                return {"status": "not checked", "why": "reveal.js didn't start"}
            if await page.evaluate(ROLE) == "application":
                return {"status": "not checked", "why": "its oer-reveal.js didn't run"}
            await page.evaluate("document.fonts.ready.then(() => true)")
            await page.evaluate(self.axe)
            dark = self.dark_options and await page.evaluate(DARK)
            places, seen, unchecked = [], set(), []
            total = int(await page.evaluate(SLIDE_COUNT) or 0)
            count = min(total, int(self.limits["slides"]))
            for index in range(count):
                route = await page.evaluate(STEP, index)
                await page.evaluate(SETTLE)
                light = await self.timed(page, self.options, LISTED, visit, unchecked,
                                         self.limits["axe"])
                places.append({"route": route, "light": unseen(light, seen), "dark": None})
            if dark:
                await page.emulate_media(color_scheme="dark")
                for index, place in enumerate(places):
                    await page.evaluate(STEP, index)
                    await page.evaluate(SETTLE)
                    found = await self.timed(page, self.dark_options, LISTED, visit, [],
                                             self.limits["axe"])
                    place["dark"] = unseen(found, seen, "dark")
            about = await self.about(page, visit)
            about["scripts"] = verdict["own"] > 0 or about["scripts"]
            return dict(about, status="checked", frames=unchecked, places=places,
                        past=total - count)
        finally:
            await lockedbrowser.close_quietly(context)


def axe_options(rules):
    return {"runOnly": {"type": "rule", "values": list(rules)},
            "resultTypes": ["violations", "incomplete"], "selectors": True,
            "ancestry": False, "xpath": False, "elementRef": False}


def unseen(result, seen, mode="light"):
    """A slide's results without what an earlier slide's had, by rule and
    selector: the presentation's controls, which every slide's check
    sees, are reported once."""
    out = {}
    for kind in ("violations", "incomplete"):
        rules = []
        for rule in result.get(kind, []):
            fresh = []
            for node in rule.get("nodes") or []:
                key = (mode, kind, rule["id"], json.dumps(node.get("target")))
                if key not in seen:
                    seen.add(key)
                    fresh.append(node)
            listed_all = len(rule.get("nodes") or []) >= rule.get("count", 0)
            if not fresh and listed_all:
                continue
            keys = rule.get("keys") or {}
            if listed_all:
                messages = {key: pair[1] for key, pair in keys.items()}
                keys = {}
                for node in fresh:
                    pair = keys.setdefault(node.get("key", ""),
                                           [0, messages.get(node.get("key", ""), "")])
                    pair[0] += 1
            rules.append(dict(rule, nodes=fresh, keys=keys,
                              count=len(fresh) if listed_all else rule.get("count", 0)))
        out[kind] = rules
    return out


if __name__ == "__main__":
    if sys.argv[1:] == ["--worker"]:
        sys.exit(worker_main())
    sys.exit("axecheck.py is run by check-output.py and audit.py; --worker is theirs.")
