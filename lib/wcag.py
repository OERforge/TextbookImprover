"""
wcag.py -- WCAG 2.2's success criteria: each one's name, level, the
version it came in, and its Understanding document.

veraPDF's WCAG profiles name a rule by its criterion's number alone
(2.4.9-1), which says nothing to a reader who doesn't know the number;
these are what a finding says about it. They're W3C's own, from WCAG
2.2's source (github.com/w3c/wcag at 457cece, 2026-10-19): the number
is the criterion's place in guidelines/index.html, its principle,
guideline, and order; its handle and level are its file's
(guidelines/sc/<version>/<slug>.html), and the folder that file is in
is the version that brought it, 20, 21, or 22. The slug names its
Understanding document: every one is in the working group's build of
the site (understanding/<slug>.html on the repository's gh-pages
branch), and the published pages of the six criteria veraPDF's machine
profiles test were read at UNDERSTANDING + slug + ".html" (2026-10-22).
4.1.1 is here with no level, as WCAG 2.2 keeps it: obsolete and
removed.

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

UNDERSTANDING = "https://www.w3.org/WAI/WCAG22/Understanding/"
RECOMMENDATION = "https://www.w3.org/TR/WCAG22/"

# number: (handle, level, the version it came in, its Understanding slug)
CRITERIA = {
    "1.1.1": ("Non-text Content", "A", "2.0", "non-text-content"),
    "1.2.1": ("Audio-only and Video-only (Prerecorded)", "A", "2.0",
              "audio-only-and-video-only-prerecorded"),
    "1.2.2": ("Captions (Prerecorded)", "A", "2.0", "captions-prerecorded"),
    "1.2.3": ("Audio Description or Media Alternative (Prerecorded)", "A", "2.0",
              "audio-description-or-media-alternative-prerecorded"),
    "1.2.4": ("Captions (Live)", "AA", "2.0", "captions-live"),
    "1.2.5": ("Audio Description (Prerecorded)", "AA", "2.0", "audio-description-prerecorded"),
    "1.2.6": ("Sign Language (Prerecorded)", "AAA", "2.0", "sign-language-prerecorded"),
    "1.2.7": ("Extended Audio Description (Prerecorded)", "AAA", "2.0",
              "extended-audio-description-prerecorded"),
    "1.2.8": ("Media Alternative (Prerecorded)", "AAA", "2.0", "media-alternative-prerecorded"),
    "1.2.9": ("Audio-only (Live)", "AAA", "2.0", "audio-only-live"),
    "1.3.1": ("Info and Relationships", "A", "2.0", "info-and-relationships"),
    "1.3.2": ("Meaningful Sequence", "A", "2.0", "meaningful-sequence"),
    "1.3.3": ("Sensory Characteristics", "A", "2.0", "sensory-characteristics"),
    "1.3.4": ("Orientation", "AA", "2.1", "orientation"),
    "1.3.5": ("Identify Input Purpose", "AA", "2.1", "identify-input-purpose"),
    "1.3.6": ("Identify Purpose", "AAA", "2.1", "identify-purpose"),
    "1.4.1": ("Use of Color", "A", "2.0", "use-of-color"),
    "1.4.2": ("Audio Control", "A", "2.0", "audio-control"),
    "1.4.3": ("Contrast (Minimum)", "AA", "2.0", "contrast-minimum"),
    "1.4.4": ("Resize Text", "AA", "2.0", "resize-text"),
    "1.4.5": ("Images of Text", "AA", "2.0", "images-of-text"),
    "1.4.6": ("Contrast (Enhanced)", "AAA", "2.0", "contrast-enhanced"),
    "1.4.7": ("Low or No Background Audio", "AAA", "2.0", "low-or-no-background-audio"),
    "1.4.8": ("Visual Presentation", "AAA", "2.0", "visual-presentation"),
    "1.4.9": ("Images of Text (No Exception)", "AAA", "2.0", "images-of-text-no-exception"),
    "1.4.10": ("Reflow", "AA", "2.1", "reflow"),
    "1.4.11": ("Non-text Contrast", "AA", "2.1", "non-text-contrast"),
    "1.4.12": ("Text Spacing", "AA", "2.1", "text-spacing"),
    "1.4.13": ("Content on Hover or Focus", "AA", "2.1", "content-on-hover-or-focus"),
    "2.1.1": ("Keyboard", "A", "2.0", "keyboard"),
    "2.1.2": ("No Keyboard Trap", "A", "2.0", "no-keyboard-trap"),
    "2.1.3": ("Keyboard (No Exception)", "AAA", "2.0", "keyboard-no-exception"),
    "2.1.4": ("Character Key Shortcuts", "A", "2.1", "character-key-shortcuts"),
    "2.2.1": ("Timing Adjustable", "A", "2.0", "timing-adjustable"),
    "2.2.2": ("Pause, Stop, Hide", "A", "2.0", "pause-stop-hide"),
    "2.2.3": ("No Timing", "AAA", "2.0", "no-timing"),
    "2.2.4": ("Interruptions", "AAA", "2.0", "interruptions"),
    "2.2.5": ("Re-authenticating", "AAA", "2.0", "re-authenticating"),
    "2.2.6": ("Timeouts", "AAA", "2.1", "timeouts"),
    "2.3.1": ("Three Flashes or Below Threshold", "A", "2.0", "three-flashes-or-below-threshold"),
    "2.3.2": ("Three Flashes", "AAA", "2.0", "three-flashes"),
    "2.3.3": ("Animation from Interactions", "AAA", "2.1", "animation-from-interactions"),
    "2.4.1": ("Bypass Blocks", "A", "2.0", "bypass-blocks"),
    "2.4.2": ("Page Titled", "A", "2.0", "page-titled"),
    "2.4.3": ("Focus Order", "A", "2.0", "focus-order"),
    "2.4.4": ("Link Purpose (In Context)", "A", "2.0", "link-purpose-in-context"),
    "2.4.5": ("Multiple Ways", "AA", "2.0", "multiple-ways"),
    "2.4.6": ("Headings and Labels", "AA", "2.0", "headings-and-labels"),
    "2.4.7": ("Focus Visible", "AA", "2.0", "focus-visible"),
    "2.4.8": ("Location", "AAA", "2.0", "location"),
    "2.4.9": ("Link Purpose (Link Only)", "AAA", "2.0", "link-purpose-link-only"),
    "2.4.10": ("Section Headings", "AAA", "2.0", "section-headings"),
    "2.4.11": ("Focus Not Obscured (Minimum)", "AA", "2.2", "focus-not-obscured-minimum"),
    "2.4.12": ("Focus Not Obscured (Enhanced)", "AAA", "2.2", "focus-not-obscured-enhanced"),
    "2.4.13": ("Focus Appearance", "AAA", "2.2", "focus-appearance"),
    "2.5.1": ("Pointer Gestures", "A", "2.1", "pointer-gestures"),
    "2.5.2": ("Pointer Cancellation", "A", "2.1", "pointer-cancellation"),
    "2.5.3": ("Label in Name", "A", "2.1", "label-in-name"),
    "2.5.4": ("Motion Actuation", "A", "2.1", "motion-actuation"),
    "2.5.5": ("Target Size (Enhanced)", "AAA", "2.1", "target-size-enhanced"),
    "2.5.6": ("Concurrent Input Mechanisms", "AAA", "2.1", "concurrent-input-mechanisms"),
    "2.5.7": ("Dragging Movements", "AA", "2.2", "dragging-movements"),
    "2.5.8": ("Target Size (Minimum)", "AA", "2.2", "target-size-minimum"),
    "3.1.1": ("Language of Page", "A", "2.0", "language-of-page"),
    "3.1.2": ("Language of Parts", "AA", "2.0", "language-of-parts"),
    "3.1.3": ("Unusual Words", "AAA", "2.0", "unusual-words"),
    "3.1.4": ("Abbreviations", "AAA", "2.0", "abbreviations"),
    "3.1.5": ("Reading Level", "AAA", "2.0", "reading-level"),
    "3.1.6": ("Pronunciation", "AAA", "2.0", "pronunciation"),
    "3.2.1": ("On Focus", "A", "2.0", "on-focus"),
    "3.2.2": ("On Input", "A", "2.0", "on-input"),
    "3.2.3": ("Consistent Navigation", "AA", "2.0", "consistent-navigation"),
    "3.2.4": ("Consistent Identification", "AA", "2.0", "consistent-identification"),
    "3.2.5": ("Change on Request", "AAA", "2.0", "change-on-request"),
    "3.2.6": ("Consistent Help", "A", "2.2", "consistent-help"),
    "3.3.1": ("Error Identification", "A", "2.0", "error-identification"),
    "3.3.2": ("Labels or Instructions", "A", "2.0", "labels-or-instructions"),
    "3.3.3": ("Error Suggestion", "AA", "2.0", "error-suggestion"),
    "3.3.4": ("Error Prevention (Legal, Financial, Data)", "AA", "2.0",
              "error-prevention-legal-financial-data"),
    "3.3.5": ("Help", "AAA", "2.0", "help"),
    "3.3.6": ("Error Prevention (All)", "AAA", "2.0", "error-prevention-all"),
    "3.3.7": ("Redundant Entry", "A", "2.2", "redundant-entry"),
    "3.3.8": ("Accessible Authentication (Minimum)", "AA", "2.2",
              "accessible-authentication-minimum"),
    "3.3.9": ("Accessible Authentication (Enhanced)", "AAA", "2.2",
              "accessible-authentication-enhanced"),
    "4.1.1": ("Parsing (Obsolete and removed)", "", "2.0", "parsing"),
    "4.1.2": ("Name, Role, Value", "A", "2.0", "name-role-value"),
    "4.1.3": ("Status Messages", "AA", "2.1", "status-messages"),
}


def criterion(number):
    """(handle, level, version, Understanding URL) for a success
    criterion's number, or None for a number WCAG 2.2 doesn't have."""
    entry = CRITERIA.get(str(number))
    if entry is None:
        return None
    handle, level, version, slug = entry
    return handle, level, version, UNDERSTANDING + slug + ".html"


def standard(number):
    """The findings format's name for a criterion: the version it came
    in, its number, and its level, "WCAG 2.0 SC 1.3.1 (A)", as the
    output check's own findings name theirs (findings.py). A number
    WCAG 2.2 doesn't have is named as 2.2's."""
    entry = CRITERIA.get(str(number))
    if entry is None:
        return f"WCAG 2.2 SC {number}"
    return f"WCAG {entry[2]} SC {number}" + (f" ({entry[1]})" if entry[1] else "")


def named(number):
    """A criterion as a reader meets it: its number, handle, and level,
    "2.4.9 Link Purpose (Link Only) (AAA)", and for one WCAG 2.0
    didn't have, the version that brought it, "1.4.10 Reflow (AA,
    WCAG 2.1)"."""
    entry = CRITERIA.get(str(number))
    if entry is None:
        return f"{number}"
    handle, level, version, _ = entry
    marks = [m for m in (level, "" if version == "2.0" else f"WCAG {version}") if m]
    return f"{number} {handle}" + (f" ({', '.join(marks)})" if marks else "")


def url(number):
    """The criterion's Understanding document, or WCAG 2.2 itself for a
    number it doesn't have."""
    found = criterion(number)
    return found[3] if found else RECOMMENDATION
