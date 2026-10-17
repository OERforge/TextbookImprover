"""
cnx.bake.directions -- the baking steps the recipes are made of, each a
port of the openstax/cookbook direction of the same name and version.

What's ported is what changes the book's text, structure, and order: a
number and its label, a title, where an end-of-chapter section goes, the
text of a link. What only styles OpenStax's own renderings is left out
(the wrappers for their web reader, running heads, class markers for
their stylesheet), and so is anything TextbookImprover does itself: a
table of contents, a scope on header cells, opening external links in a
new window. Each function says which direction it ports, and the version.

Two choices differ from cookbook's on purpose. A link baking names gets
the name as its text and no aria-label, since a link's accessible name
is its visible text (WCAG 2.5.3) and TextbookImprover writes any
description as a title. And footnotes are written as Pandoc writes them,
so its reader takes them for notes and TextbookImprover's notes settings
decide where they go.

Copyright 2026 Robert Szarka. Ported from openstax/cookbook, Copyright
(c) 2020 Rice University, under the MIT License, whose text is in
lib/cnx/LICENSE-cookbook.txt.

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

import copy
import re
import string
import unicodedata
from urllib.parse import urlsplit

from ..cnxml import E, append_text
from .core import (EXERCISE, SOLUTION, TERM, add_class, class_test, classes,
                   detach, extra_attribute, figure_to_number, has_class,
                   insert_after, insert_before,
                   move_children, note_title, prepend, remove_class,
                   replace, span, text_of, title_span, trash,
                   unnumbered_figure_to_bake, wrap, wrap_children)


# Titles ----------------------------------------------------------------

def numbered_title(title, number, label=None):
    """A title's content as "<label> <number> <title>", in the spans
    cookbook uses: os-part-text, os-number, os-divider, os-text."""
    text = title_span(title)
    for child in list(title):
        title.remove(child)
    title.text = None
    if label:
        title.append(span("os-part-text", label + " "))
    title.append(span("os-number", number))
    title.append(span("os-divider", " "))
    title.append(text)


def move_title_children_into_span(title):
    """Port of MoveTitleChildrenIntoSpan.v1."""
    text = title_span(title)
    for child in list(title):
        title.remove(child)
    title.text = None
    title.append(text)


# Figures ---------------------------------------------------------------

def _figure_caption(figure, number=None, label=None):
    title = figure.xpath("./div[@data-type='title']")
    caption = figure.xpath("./figcaption")
    title = detach(title[0]) if title else None
    caption = detach(caption[0]) if caption else None
    container = E("figcaption", {"class": "os-caption-container"})
    if number is not None:
        container.append(span("os-title-label", label + " "))
        container.append(span("os-number", number))
        if title is not None:
            container.append(span("os-divider", " "))
    if title is not None:
        out = span("os-title", data_type="title")
        move_children(title, out)
        container.append(out)
    if caption is not None:
        if number is not None or title is not None:
            container.append(span("os-divider", " "))
        out = span("os-caption")
        move_children(caption, out)
        container.append(out)
    return container, title is not None or caption is not None


def bake_unnumbered_figure(book):
    """Port of BakeUnnumberedFigure.v1."""
    for figure in book.figures():
        if not unnumbered_figure_to_bake(figure):
            continue
        container, any_caption = _figure_caption(figure)
        if any_caption:
            figure.append(container)


def bake_figure(book, figure, number, label_class=None, cases=False):
    """Port of BakeFigure.v1. A reaction's mechanism (class
    mechanism-figure) has its caption first, as cookbook sets it above
    the figure; here it stays the figure's caption. With cases, a link
    to it names it in its sentence's case (a Polish book's)."""
    label = book.t("figure")
    if cases:
        book.target_label_cases(figure, "figure", number, label_class)
    else:
        book.target_label(figure, f"{label} {number}", label_class)
    container, _ = _figure_caption(figure, number, label)
    if has_class(figure, "mechanism-figure"):
        prepend(figure, container)
    else:
        figure.append(container)


# Notes -----------------------------------------------------------------

def _note_body(note):
    return wrap_children(note, E("div", {"class": "os-note-body"}))


def autogenerated_title(book, note):
    """NoteElement#autogenerated_title: the locale's string for the one
    class of the note's that names one."""
    notes = book.strings.get("notes", {})
    keys = [c for c in (note.get("class") or "").split() if c in notes]
    if len(keys) > 1:
        raise ValueError("too many title keys for a note: " + ", ".join(keys))
    if not keys:
        return None
    return notes[keys[0]]


def bake_note_subtitle(book, note, cases=False):
    """Port of BakeNoteSubtitle.v1: the note's own title becomes a
    subtitle (h4) inside its body, and what links to the note show,
    with cases after the locale's word for a note, in each case
    ("Ramki …")."""
    title = note_title(note)
    if title is None:
        return
    detach(title)
    if cases:
        book.target_label_cases(note, "note", text_of(title))
    else:
        book.target_label(note, text_of(title))
    subtitle = E("h4", {"data-type": "title", "class": "os-subtitle"})
    inner = span("os-subtitle-label")
    move_children(title, inner)
    subtitle.append(inner)
    body = note.xpath("./div[@class='os-note-body']")[0]
    prepend(body, subtitle)


def bake_autotitled_notes(book, classes, bake_subtitle=True, within=None,
                          except_ids=(), bake_exercises=False, cases=False):
    """Port of BakeAutotitledNotes.v1; with bake_exercises, a note's
    exercises numbered in it ("Exercise 1"), as BakeNoteExercise.v2
    numbers them."""
    for note in book.notes(within):
        if not set(classes) & set((note.get("class") or "").split()):
            continue
        if note.get("id") in except_ids:
            continue
        if note.get("data-baked"):
            continue
        note.set("data-baked", "autotitled")
        _note_body(note)
        if bake_subtitle:
            bake_note_subtitle(book, note, cases)
        else:
            title = note_title(note)
            if title is not None:
                trash(title)
        heading = E("h3", {"class": "os-title", "data-type": "title"})
        heading.append(span("os-title-label", autogenerated_title(book, note)
                            or ""))
        prepend(note, heading)
        if bake_exercises:
            from .injected import bake_note_exercise_v2
            bake_note_exercise_v2(book, note)


def bake_unclassified_notes(book, bake_exercises=False):
    """Port of BakeUnclassifiedNotes.v1: a note with no class keeps its
    own title, as an h3; with bake_exercises, a titled note's exercises
    are numbered in it, as BakeNoteExercise.v2 numbers them."""
    for note in book.notes():
        if (note.get("class") or "").split():
            continue
        if note.get("data-baked"):
            continue
        note.set("data-baked", "unclassified")
        _note_body(note)
        title = note_title(note)
        if title is None:
            continue
        detach(title)
        heading = E("h3", {"class": "os-title", "data-type": "title"})
        inner = span("os-title-label", data_type="")
        if title.get("id"):
            inner.set("id", title.get("id"))
        move_children(title, inner)
        heading.append(inner)
        prepend(note, heading)
        if bake_exercises:
            from .injected import bake_note_exercise_v2
            bake_note_exercise_v2(book, note)


def _has_classes(element, dotted):
    """A cookbook class selector's test: "statistics.lab" is both."""
    return all(has_class(element, c) for c in dotted.split("."))


def _numbered_note_heading(book, note, number):
    """The heading BakeNumberedNotes puts first in a note: its label
    ("Try It ") and its number. Cookbook's h3 has no data-type; it has
    one here, so emit.py finds it as it finds any note's title. A label
    the locale writes with no space after it gets one, which cookbook's
    template gives it as the line break between the two."""
    heading = E("h3", {"class": "os-title", "data-type": "title"})
    label = autogenerated_title(book, note) or ""
    if label and number and not label[-1].isspace():
        label += " "
    heading.append(span("os-title-label", label))
    heading.append(span("os-number", number))
    return heading


def bake_numbered_notes_v3(book, classes, suppress_solution=True):
    """Port of BakeNumberedNotes.v3: a note numbered as the example
    before it is ("Try It 2.3" after Example 2.3), its own title gone,
    its exercises baked as a note's are, their solutions dropped."""
    for klass in classes:
        for chapter in book.chapters():
            for page in book.pages(chapter):
                for note in book.notes(page):
                    if not _has_classes(note, klass):
                        continue
                    _note_body(note)
                    previous = note.getprevious()
                    while previous is not None and (
                            not isinstance(previous.tag, str)
                            or previous.get("data-type") != "example"):
                        previous = previous.getprevious()
                    number = ""
                    if previous is not None:
                        found = previous.xpath(
                            f".//*[{class_test('os-number')}]")
                        number = text_of(found[0]) if found else ""
                    prepend(note, _numbered_note_heading(book, note, number))
                    title = note_title(note)
                    if title is not None:
                        trash(title)
                    book.target_label(
                        note, f"{autogenerated_title(book, note)} {number}")
                    for exercise in note.xpath(f".//{EXERCISE}"):
                        bake_note_exercise(book, note, exercise, divider=". ",
                                           suppress_solution=suppress_solution)
                    if suppress_solution:
                        for solution in note.xpath(f".//{SOLUTION}"):
                            trash(solution)


def bake_numbered_notes_v1(book, classes, bake_exercises=True,
                           cases=False):
    """Port of BakeNumberedNotes.v1: a note of the class numbered in its
    chapter ("CFA Institute 3.2"), or in its appendix ("A1"), its label
    and number before its body; its exercises baked as a note's are,
    and a question of its from the exercise bank unnumbered, its
    solution taking the note's number."""
    from . import injected as inj

    def bake_note(note, number):
        _note_body(note)
        heading = _numbered_note_heading(book, note, number)
        heading.append(span("os-divider", " "))
        prepend(note, heading)
        if note.get("use-subtitle"):
            bake_note_subtitle(book, note, cases)
        if not bake_exercises:
            return
        for exercise in note.xpath(f".//{EXERCISE}"):
            bake_note_exercise(book, note, exercise)
        for exercise in note.xpath(".//div[@data-type='injected-exercise']"):
            inj.bake_injected_exercise(book, exercise)
        for question in note.xpath(".//div[@data-type='exercise-question']"):
            add_class(question, "unnumbered")
            inj.bake_injected_exercise_question(
                book, question, number.replace("#", ""),
                only_number_solution=True)

    for klass in classes:
        for chapter in book.chapters():
            n = book.chapter_number(chapter)
            notes = [note for page in book.pages(chapter)
                     for note in book.notes(page) if has_class(note, klass)]
            for i, note in enumerate(notes, 1):
                bake_note(note, f"{n}.{i}")
        for index, page in enumerate(book.pages(cls="appendix")):
            letter = string.ascii_uppercase[index]
            notes = [note for note in book.notes(page)
                     if has_class(note, klass)]
            for j, note in enumerate(notes, 1):
                bake_note(note, f"{letter}{j}")


def bake_numbered_notes_v2(book, classes):
    """Port of BakeNumberedNotes.v2: a note of the class numbered in its
    page ("Try It #1"), its exercises baked as a note's are, their
    solutions taking the note's number."""
    for klass in classes:
        for chapter in book.chapters():
            for page in book.pages(chapter):
                notes = [note for note in book.notes(page)
                         if has_class(note, klass)]
                for i, note in enumerate(notes, 1):
                    _note_body(note)
                    prepend(note, _numbered_note_heading(book, note, f"#{i}"))
                    for exercise in note.xpath(f".//{EXERCISE}"):
                        bake_note_exercise(book, note, exercise, divider=". ")


def bake_numbered_notes_v4(book, classes, within, scope="chapter"):
    """Port of BakeNumberedNotes.v4: the notes in the named sections
    ("Stats Lab 1"), numbered in their chapter. Returns their ids, which
    the recipe keeps BakeAutotitledNotes from baking again."""
    baked = set()
    for klass in classes:
        for chapter in book.chapters():
            count = 0
            for page in book.pages(chapter):
                for holder in page.xpath(f".//*[{class_test(within)}]"):
                    for note in book.notes(holder):
                        if not _has_classes(note, klass):
                            continue
                        if not note.get("id"):
                            raise ValueError("a numbered note has no id")
                        if note.get("id") in baked:
                            continue
                        count += 1
                        _note_body(note)
                        prepend(note, _numbered_note_heading(book, note,
                                                             str(count)))
                        for exercise in note.xpath(f".//{EXERCISE}"):
                            bake_note_exercise(book, note, exercise,
                                               divider=". ")
                        baked.add(note.get("id"))
    return baked


def bake_stepwise(book):
    """Port of BakeStepwise.v1: each item of a list of class stepwise
    opens with "Step 1. "."""
    for ol in book.body.xpath(f".//ol[{class_test('stepwise')}]"):
        remove_class(ol, "stepwise")
        add_class(ol, "os-stepwise")
        for n, li in enumerate(ol.xpath("./li"), 1):
            blockish = any(isinstance(c.tag, str) and c.tag in BLOCKISH
                           for c in li.iterdescendants())
            content = E("div" if blockish else "span",
                        {"class": "os-stepwise-content"})
            wrap_children(li, content)
            prepend(li, span("os-stepwise-token",
                             f"{book.t('stepwise_step_label')} {n}. "))


# The elements cookbook's contains_blockish? looks for.
BLOCKISH = {"address", "article", "aside", "blockquote", "details", "dialog",
            "dd", "div", "dl", "dt", "fieldset", "figcaption", "figure",
            "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header",
            "hgroup", "hr", "li", "main", "nav", "ol", "p", "pre", "section",
            "table", "ul"}


# Examples --------------------------------------------------------------

def bake_example(book, example, number, title_tag="h3",
                 add_problem_title=False, cases=False):
    """Port of BakeExample.v1: "Example 2.3" above the example; its
    exercises' problems and solutions under "Problem" and "Solution".
    Cookbook renames the titles in it h4, which changes nothing here,
    where emit.py sets every heading's level by where it stands; renamed,
    a figure's title would be missed by BakeFigure, which looks for a
    div, and stand above the figure as a heading in OpenStax's book."""
    wrap_children(example, E("div", {"class": "body"}))
    heading = E(title_tag, {"class": "os-title", "data-type": "title"})
    heading.append(span("os-title-label", book.t("example") + " "))
    heading.append(span("os-number", number))
    heading.append(span("os-divider", " "))
    prepend(example, heading)
    if cases:
        book.target_label_cases(example, "example", number)
    else:
        book.target_label(example, f"{book.t('example')} {number}")
    for exercise in example.xpath(f".//{EXERCISE}"):
        if exercise.xpath(f".//div[{class_test('os-problem-container')}]"):
            continue
        problems = exercise.xpath("./div[@data-type='problem']")
        if problems:
            problem = problems[0]
            wrap_children(problem, E("div", {"class": "os-problem-container"}))
            if add_problem_title:
                title = E("h4", {"data-type": "problem-title"})
                title.append(span("os-title-label", book.t("problem")))
                prepend(problem, title)
        for solution in exercise.xpath(f".//{SOLUTION}"):
            wrap_children(solution,
                          E("div", {"class": "os-solution-container"}))
            title = E("h4", {"data-type": "solution-title"})
            title.append(span("os-title-label", book.t("solution")))
            prepend(solution, title)
        add_class(exercise, "unnumbered")
        commentary = exercise.xpath("./div[@data-type='commentary']")
        if commentary:
            titles = commentary[0].xpath(".//*[@data-type='title']")
            if titles and titles[0].getparent().get("data-type") != "list":
                titles[0].tag = "h4"
                titles[0].set("data-type", "commentary-title")
                wrap_children(titles[0], span("os-title-label"))


def bake_custom_titled_notes(book, classes_):
    """Port of BakeCustomTitledNotes.v1: a note of the classes keeps its
    own title, as its heading."""
    for note in book.notes():
        if not set(classes_) & set(classes(note)):
            continue
        _note_body(note)
        title = note_title(note)
        if title is None:
            continue
        detach(title)
        heading = E("h3", {"class": "os-title", "data-type": "title"})
        label = span("os-title-label")
        move_children(title, label)
        heading.append(label)
        prepend(note, heading)


# Pages and chapters ----------------------------------------------------

def bake_preface(book, title_element="h1", cases=False):
    """Port of BakePreface.v1."""
    for page in book.pages(cls="preface"):
        for old in page.xpath(".//div[@data-type='description'] | "
                              ".//div[@data-type='abstract']"):
            trash(old)
        title = book.page_title(page)
        if title is not None:
            move_title_children_into_span(title)
            title.tag = title_element
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for n, figure in enumerate(figures, 1):
            bake_figure(book, figure, str(n), cases=cases)


def bake_chapter_title(book, chapters=None, number_of=None):
    """Port of BakeChapterTitle.v1: "Chapter 3 Demand and Supply"; and
    of v2, given the chapters and their numbers ("Lesson 1.2")."""
    for chapter in chapters if chapters is not None else book.chapters():
        n = book.chapter_number(chapter)
        heading = book.page_title(chapter)
        heading.set("id", f"chapTitle{n}")
        numbered_title(heading, number_of(chapter) if number_of else str(n),
                       book.t("chapter"))


def bake_learning_objectives(book, chapter):
    """Port of BakeLearningObjectives.v1."""
    for abstract in chapter.xpath(".//div[@data-type='abstract']"):
        heading = E("h3", {"data-type": "title"}, book.t("learning_objectives"))
        prepend(abstract, heading)


def bake_learning_objectives_v2(book, chapter, add_title=True,
                                li_numbering="in_chapter"):
    """Port of BakeLearningObjectives.v2: each objective numbered, by its
    place alone (li_numbering "count_only_li", which Principles of
    Marketing's recipe asks for: "1 Define and describe marketing.") or
    after the section's number ("in_chapter": 1.1.1). Objectives are the
    chapter's abstracts, or its sections of class learning-objectives;
    an appendix's ("count_only_li_in_appendix"), the sections."""
    if li_numbering in ("in_appendix", "count_only_li_in_appendix"):
        found = chapter.xpath(
            f".//section[{class_test('learning-objectives')}]")
    else:
        found = chapter.xpath(".//div[@data-type='abstract']") or \
            chapter.xpath(f".//section[{class_test('learning-objectives')}]")
    for abstract in found:
        if add_title:
            prepend(abstract, E("h3", {"data-type": "title"},
                                book.t("learning_objectives")))
        uls = abstract.xpath(".//ul")
        if not uls:
            continue
        ul = uls[0]
        add_class(ul, "os-abstract")
        page = book.page_of(abstract)
        for index, li in enumerate(ul.xpath(".//li"), 1):
            if li_numbering in ("count_only_li", "count_only_li_in_appendix"):
                token = str(index)
            elif li_numbering == "in_appendix":
                pages = book.pages()
                token = f"{pages.index(page) + 1}.1.{index}"
            else:
                token = f"{book.page_number(page)}.{index}"
            content = span("os-abstract-content")
            move_children(li, content)
            shown = span("os-abstract-token", token)
            # The space cookbook's template leaves between the two.
            shown.tail = " "
            li.append(shown)
            li.append(content)


def bake_chapter_introductions(book, strategy="default",
                               bake_chapter_outline=False,
                               introduction_order="v1",
                               block_target_label=False, cases=False,
                               authors=False):
    """Port of BakeChapterIntroductions.v2: the introduction's title
    inside its text, after what the options put first. The strategy
    "default" puts the chapter's objectives note first; "add_objectives"
    a list of the chapter's sections, each linking to it, which
    bake_chapter_outline titles "Chapter Outline". The orders put a unit
    opener's note (v3) or the authors' (v4) where cookbook's do. A link
    to the introduction shows "Chapter 3" and the chapter's title, in a
    Polish book's case with cases, or nothing baking names with
    block_target_label; with authors, the paragraph naming the
    chapter's authors goes before its opening picture."""
    for n, chapter in enumerate(book.chapters(), 1):
        intro = book.introduction_page(chapter)
        if intro is None:
            continue
        chapter_title = book.page_title(chapter)
        texts = chapter_title.xpath(".//*[@class='os-text']")
        title_label = text_of(texts[0] if texts else chapter_title)
        if cases and not block_target_label:
            book.target_label_cases(intro, "chapter", f"{n} {title_label}")
        elif not block_target_label:
            book.target_label(intro, f"{book.t('chapter')} {n} {title_label}")
        # bake_title: the page's title, an h2 now, inside the intro text.
        for old in intro.xpath(".//div[@data-type='description'] | "
                               ".//div[@data-type='abstract']"):
            trash(old)
        title = detach(book.page_title(intro))
        title.tag = "h2"
        title.set("id", f"{intro.get('id')}_titlecreatedbycookbook")
        move_title_children_into_span(title)
        first = []
        if strategy == "default":
            note = book.notes(chapter, "chapter-objectives")
            if note:
                note = note[0]
                old_title = note_title(note)
                if old_title is not None:
                    trash(old_title)
                bake_autotitled_notes(book, ["chapter-objectives"],
                                      bake_subtitle=False, within=chapter)
                first.append(detach(note))
        elif strategy == "add_objectives":
            first.append(_chapter_objectives(book, chapter, n))
        if bake_chapter_outline:
            outline = E("div", {"class": "os-chapter-outline"})
            heading = E("h3", {"class": "os-title", "data-type": "title"},
                        book.t("chapter_outline"))
            outline.append(heading)
            for part in first:
                outline.append(part)
            first = [outline]
        if introduction_order == "v2" and not first:
            notes = book.notes(intro, "chapter-objectives")
            if notes:
                first = [detach(notes[0])]
        leading = []
        skip = {"splash", "has-splash"}
        if introduction_order == "v3":
            skip.add("unit-opener")
            leading = [detach(note) for note in book.notes(intro,
                                                           "unit-opener")]
        trailing = []
        if introduction_order == "v4":
            skip.add("meet-author")
            trailing = [detach(note) for note in book.notes(intro,
                                                            "meet-author")]
        rest = [c for c in intro if isinstance(c.tag, str)
                and c.get("data-type") != "metadata"
                and not skip & set(classes(c))]
        body = E("div", {"class": "intro-body"})
        for part in leading + first + trailing:
            body.append(part)
        text = E("div", {"class": "intro-text"})
        text.append(title)
        for child in rest:
            text.append(detach(child))
        body.append(text)
        intro.append(body)
        intro.set("data-title-moved", "true")
        if authors:
            # bake_authors: the first splash's sibling.
            splashes = intro.xpath(f".//*[{class_test('splash')}]")
            named = intro.xpath(f".//p[{class_test('author')}]")
            if splashes:
                for paragraph in named:
                    insert_before(splashes[0], detach(paragraph))


def _chapter_objectives(book, chapter, n):
    """BakeChapterObjectives#add_chapter_objectives: the chapter's
    sections, numbered, each a link to its page."""
    ul = E("ul", {"class": "os-chapter-objectives"})
    for i, page in enumerate(book.non_introduction_pages(chapter), 1):
        title = book.page_title(page)
        texts = title.xpath(".//*[@class='os-text']") if title is not None \
            else []
        source = texts[0] if texts else title
        li = E("li", {"class": "os-chapter-objective"})
        link = E("a", {"class": "os-chapter-objective",
                       "href": f"#{page.get('id')}"})
        link.append(span("os-number", f"{n}.{i}"))
        link.append(span("os-divider", " "))
        link.append(title_span(source) if source is not None
                    else span("os-text"))
        li.append(link)
        ul.append(li)
    return ul


def bake_non_introduction_pages(book, chapter, custom_target_label=False,
                                number_of=None, block_target_label=False,
                                cases=False):
    """Port of BakeNonIntroductionPages.v1: "3.1 Demand, Supply, ...".
    With custom_target_label, a link can show the number alone too
    (bake_lo_link_labels); number_of numbers the pages as a recipe's
    numbering options do ("1.2.0"). With block_target_label baking names
    a page nothing a link shows; with cases, a link shows the locale's
    word for a section first, in its sentence's case ("Podrozdziale
    1.2 …")."""
    for page in book.non_introduction_pages(chapter):
        number = number_of(page) if number_of else book.page_number(page)
        for old in page.xpath(".//div[@data-type='description']"):
            trash(old)
        add_class(page, "chapter-content-module")
        title = book.page_title(page)
        if cases and not block_target_label:
            book.target_label_cases(page, "module",
                                    f"{number} {text_of(title)}")
        elif not block_target_label:
            book.target_label(page, f"{number} {text_of(title)}")
        if custom_target_label and page.get("id"):
            book.label_numbers[page.get("id")] = number
        title.tag = "h2"
        title.set("id", f"{page.get('id')}_titlecreatedbycookbook")
        numbered_title(title, number)


def bake_appendix(book, page, number, add_title_label=True,
                  block_target_label=False, cases=False):
    """Port of BakeAppendix.v1: "Appendix A The Use of Mathematics in
    Principles of Economics"; its sections' headings a level down. A link
    to it shows "Appendix A" and the title, or without add_title_label
    the letter alone; with block_target_label, baking names it nothing."""
    title = book.page_title(page)
    title.tag = "h1"
    content = f"{number} {text_of(title)}" if add_title_label else number
    if cases and not block_target_label:
        book.target_label_cases(page, "appendix", content)
    elif not block_target_label:
        book.target_label(page, f"{book.t('appendix')} {content}")
    numbered_title(title, number, book.t("appendix"))
    for section in page.xpath(".//section[not("
                              + class_test("learning-objectives") + ")]"):
        heads = section.xpath("./*[@data-type='title']")
        if heads:
            heads[0].tag = f"h{int(section.get('data-depth', '1')) + 1}"


def bake_appendix_feature_titles(book, section, selector):
    """Port of BakeAppendixFeatureTitles.v1: a section of an appendix
    titled by its kind ("Summary", "Knowledge Check")."""
    old = section.xpath(".//*[@data-type='title']")
    if old:
        trash(old[0])
    heading = E("h2", {"data-type": "title"})
    heading.append(span("os-text", book.t(f"appendix_sections.{selector}")))
    prepend(section, heading)


def bake_unit_title(book, number_of=None):
    """Port of BakeUnitTitle.v1: "Unit 1 Setting the Stage"; number_of
    numbers the units otherwise than by their place."""
    for n, unit in enumerate(book.units(), 1):
        heading = book.page_title(unit)
        if heading is None:
            continue
        text = text_of(heading)
        for child in list(heading):
            heading.remove(child)
        heading.text = None
        heading.append(span("os-part-text", book.t("unit") + " "))
        heading.append(span("os-number",
                            number_of(unit) if number_of else str(n)))
        heading.append(span("os-divider", " "))
        heading.append(span("os-text", text))


def bake_unit_page_title(book):
    """Port of BakeUnitPageTitle.v1: a unit's own page titled with the
    unit's number, "Unit 1 Unit Introduction"."""
    for n, unit in enumerate(book.units(), 1):
        for page in unit:
            if not isinstance(page.tag, str) or \
                    page.get("data-type") != "page":
                continue
            title = book.page_title(page)
            if title is None:
                continue
            text = text_of(title)
            title.tag = "h2"
            for child in list(title):
                title.remove(child)
            title.text = None
            title.append(span("os-part-text", book.t("unit") + " "))
            title.append(span("os-number", str(n)))
            title.append(span("os-divider", " "))
            title.append(span("os-text", text))


def bake_autotitled_exercise(book, exercise):
    """Port of BakeAutotitledExercise.v1, unnumbered: the exercise's
    problem titled by its kind, the locale's name for the class it has
    ("Your Turn"), and its solution "Solution", each in place."""
    add_class(exercise, "unnumbered")
    names = book.strings.get("exercises", {})
    kinds = [c for c in classes(exercise) if c in names]
    title = names[kinds[0]] if kinds \
        else f"unknown title for exercise with classes {' '.join(classes(exercise))}"
    problems = exercise.xpath(".//div[@data-type='problem']")
    if problems:
        problem = problems[0]
        wrap_children(problem, E("div", {"class": "os-problem-container"}))
        prepend(problem, E("h4", {"class": "exercise-title",
                                  "data-type": "title"}, title))
    solutions = exercise.xpath(f".//{SOLUTION}")
    if solutions:
        solution = solutions[0]
        wrap_children(solution, E("div", {"class": "os-solution-container"}))
        heading = E("h4", {"class": "solution-title", "data-type": "title"})
        heading.append(span("os-text", book.t("exercises.solution")))
        prepend(solution, heading)


def bake_autotitled_exercise_v2(book, exercise, title):
    """Port of BakeAutotitledExercise.v2: the exercise unnumbered, its own
    title replaced by the one given ("Check Your Understanding") above
    its problem, and its solution titled "Solution"."""
    add_class(exercise, "unnumbered")
    titles = exercise.xpath(".//*[@data-type='title']")
    if titles:
        trash(titles[0])
    heading = E("h3", {"class": "os-title", "data-type": "title"})
    heading.append(span("os-title-label", title))
    prepend(exercise, heading)
    problems = exercise.xpath(".//div[@data-type='problem']")
    if problems:
        wrap_children(problems[0], E("div", {"class": "os-problem-container"}))
    solutions = exercise.xpath(f".//{SOLUTION}")
    if solutions:
        solution = solutions[0]
        wrap_children(solution, E("div", {"class": "os-solution-container"}))
        sol_title = E("h4", {"class": "solution-title", "data-type": "title"})
        sol_title.append(span("os-text", book.t("solution")))
        prepend(solution, sol_title)


def bake_autotitled_exercise_v3(book, exercise, title):
    """Port of BakeAutotitledExercise.v3, as v2 and, for an exercise with
    a solution, the solution's id made from the exercise's, which the
    answer key links to."""
    bake_autotitled_exercise_v2(book, exercise, title)
    solutions = exercise.xpath(f".//{SOLUTION}")
    if solutions and exercise.get("id"):
        add_class(exercise, "os-hasSolution")
        solutions[0].set("id", f"{exercise.get('id')}-solution")


def bake_unnumbered_exercise(exercise):
    """Port of BakeUnnumberedExercise.v1: the problem's content in its
    container, and each solution's in its own, all of it in place."""
    problems = exercise.xpath(".//div[@data-type='problem']")
    if problems:
        wrap_children(problems[0], E("div", {"class": "os-problem-container"}))
    for solution in exercise.xpath(f".//{SOLUTION}"):
        wrap_children(solution, E("div", {"class": "os-solution-container"}))


def bake_learning_objectives_v3(book, chapter):
    """Port of BakeLearningObjectives.v3 (*College Physics*): each section's
    objectives, its abstract (or its section of class learning-objectives),
    moved to the section's line of the chapter's outline on its
    introduction."""
    found = chapter.xpath(".//div[@data-type='abstract']") or \
        chapter.xpath(f".//section[{class_test('learning-objectives')}]")
    wrapped = [wrap(element, E("div", {"class": "learning-objective"}))
               for element in found]
    intro = book.introduction_page(chapter)
    items = intro.xpath(f".//li[{class_test('os-chapter-objective')}]") \
        if intro is not None else []
    for item, wrapper in zip(items, wrapped):
        item.append(detach(wrapper))


def bake_embedded_exercise_questions(book, chapter, klass):
    """Port of the computer science recipe's loop with
    BakeEmbeddedExerciseQuestion.v1: each item of a numbered list right in
    a section of the class (a lab's steps) an exercise of its own,
    numbered through the chapter. Cookbook makes the list and its items
    spans; here they're divs, since they hold blocks."""
    number = 1
    for section in chapter.xpath(f".//section[{class_test(klass)}]"):
        for listing in section.xpath("./ol"):
            items = listing.xpath("./li")
            for item in items:
                item.tag = "div"
                exercise = E("div", {"data-type": "exercise"})
                problem = E("div", {"data-type": "problem"})
                problem.append(span("os-number", str(number)))
                problem.append(span("os-divider", ". "))
                container = E("div", {"class": "os-problem-container"})
                container.append(detach(item))
                problem.append(container)
                exercise.append(problem)
                listing.append(exercise)
                number += 1
            listing.tag = "div"
            for name in ("type", "start", "number-style"):
                listing.attrib.pop(name, None)


def bake_handbook(book):
    """Port of BakeHandbook.v1 (*Writing Guide with Handbook*): a handbook
    page's top-level sections numbered H1, H2 ("H1. Grammar Essentials"),
    and an Outline after the page's title linking to each."""
    for page in book.pages(cls="handbook"):
        title = book.page_title(page)
        if title is None:
            continue
        text = text_of(title)
        for child in list(title):
            title.remove(child)
        title.text = None
        title.append(span("os-text", text))
        outline = E("div", {"class": "os-handbook-outline"})
        # A title, as the chapter outline's is, so emit.py gives it the
        # level under the page's.
        outline.append(E("h3", {"class": "os-title", "data-type": "title"},
                         book.t("handbook_outline_title")))
        insert_after(title, outline)
        sections = [c for c in page if isinstance(c.tag, str)
                    and c.tag == "section"]
        for n, section in enumerate(sections, 1):
            titles = section.xpath(".//*[@data-type='title']")
            if not titles:
                continue
            first = titles[0]
            words = text_of(first)
            for child in list(first):
                first.remove(child)
            first.text = None
            parts = [span("os-part-text", "H"), span("os-number", str(n)),
                     span("os-divider", ". "), span("os-text", words)]
            for part in parts:
                first.append(part)
            item = E("div", {"class": "os-handbook-objective"})
            link = E("a", {"class": "os-handbook-objective",
                           "href": f"#{section.get('id')}"})
            for part in parts:
                link.append(copy.deepcopy(part))
            item.append(link)
            outline.append(item)


def bake_custom_sections(book, chapter, properties):
    """Port of BakeCustomSections.v1, which the composition recipe runs
    last: for each (class, inject) in properties, the locale's name for
    the class ("Trailblazer") is the title of each such page ("title"),
    the page's own title its subtitle; a heading above each such
    section's title ("subtitle"); or a prefix to it ("title_prefix",
    "Quick Launch: Mapping the Rhetorical Situation"). A page so retitled
    keeps its own title for its name (data-toc-title), as OpenStax's
    contents, made before this step, have it. The subtitle and the heading
    above a section, h3s in cookbook, are paragraphs here, the heading
    above the section just before it, so a page's outline of headings
    doesn't skip a level or put the section's heading after its own."""
    for cls, inject in properties:
        name = book.t(f"custom-sections.{cls}")
        for custom in chapter.xpath(f".//*[{class_test(cls)}]"):
            if inject == "title":
                headings = custom.xpath(".//h2")
                texts = headings[0].xpath(f".//*[{class_test('os-text')}]") \
                    if headings else []
                if not texts:
                    continue
                heading, os_text = headings[0], texts[0]
                # The empty div OpenStax's assembly leaves after a page's
                # title (h2 + div); a div with something in it stays.
                after = heading.getnext()
                if after is not None and after.tag == "div" and not len(after) \
                        and not (after.text or "").strip():
                    trash(after)
                own = text_of(os_text)
                insert_after(heading, E("p", {"class": "os-subtitle"}, own))
                custom.set("data-toc-title", own)
                for child in list(os_text):
                    os_text.remove(child)
                os_text.text = name
            elif inject == "subtitle":
                if custom.xpath(".//*[@data-type='title']"):
                    insert_before(custom, E("p", {"class": "os-title"}, name))
            elif inject == "title_prefix":
                titles = custom.xpath(".//*[@data-type='title']")
                if titles:
                    title = titles[0]
                    words = "".join(title.itertext())
                    for child in list(title):
                        title.remove(child)
                    title.text = f"{name}: {words}"


# Composite pages -------------------------------------------------------

def composite_page(book, container_key, content, append_to, title=None,
                   section=None, uuid_key=None):
    """Port of CompositePageContainer.v1: a page built from parts of
    others, titled from the locale's eoc (end of chapter) or eob (end of
    book) strings."""
    in_chapter = append_to.get("data-type") == "chapter"
    in_composite_chapter = append_to.get("data-type") == "composite-chapter"
    if section is None:
        section = "eoc" if (in_chapter or in_composite_chapter) else "eob"
    if title is None:
        title = book.t(f"{section}.{container_key}")
    page = E("div", {"class": f"os-{section} os-{container_key}-container",
                     "data-type": "composite-page",
                     "data-uuid-key": uuid_key or f".{container_key}"})
    tag = "h3" if in_composite_chapter else "h2" if in_chapter else "h1"
    heading = E(tag, {"data-type": "title" if in_composite_chapter
                      else "document-title"})
    heading.append(span("os-text", title))
    page.append(heading)
    for item in content:
        if isinstance(item, str):
            append_text(page, item)
        else:
            page.append(item)
    append_to.append(page)
    return page


def chapter_review_container(book, chapter, klass="chapter-review"):
    """Port of ChapterReviewContainer.v1: a group at the chapter's end,
    titled from the locale ("Chapter Review"), for its end-of-chapter
    pages to go in."""
    group = E("div", {"class": f"os-eoc os-{klass}-container",
                      "data-type": "composite-chapter",
                      "data-uuid-key": f".{klass}"})
    heading = E("h2", {"data-type": "document-title"})
    heading.append(span("os-text", book.t(f"eoc.{klass}")))
    group.append(heading)
    chapter.append(group)
    return group


def eoc_section_title_link(book, page, title_tag="h3", wrapper="link"):
    """Port of EocSectionTitleLinkSnippet.v1: a section's numbered title,
    linking to the section (wrapper "link"), in a div ("div"), or bare
    (None)."""
    heading = E(title_tag, {"data-type": "document-title"})
    if not book.is_introduction(page):
        heading.append(span("os-number", book.page_number(page)))
        heading.append(span("os-divider", " "))
    title = book.page_title(page)
    texts = title.xpath("./span[@class='os-text']") if title is not None \
        else []
    heading.append(title_span(texts[0] if texts else title))
    if wrapper is None:
        return heading
    if wrapper == "div":
        holder = E("div")
        holder.append(heading)
        return holder
    link = E("a", {"href": f"#{page.get('id')}_titlecreatedbycookbook",
                   "data-type": "section-link"})
    link.append(heading)
    return link


def _unwrap_lone_paragraph(holder):
    """The content of a lone paragraph a list item or a meaning holds,
    in the holder itself, markup and all, the paragraph's id kept (on
    the holder, or an anchor where the paragraph began)."""
    kids = [c for c in holder if isinstance(c.tag, str)]
    if len(kids) != 1 or kids[0].tag != "p":
        return
    para = kids[0]
    if (holder.text or "").strip() or (para.tail or "").strip():
        return
    anchor = None
    if para.get("id"):
        if holder.get("id"):
            anchor = E("span", {"id": para.get("id")}, "")
        else:
            holder.set("id", para.get("id"))
    holder.text = None
    if anchor is not None:
        para.addprevious(anchor)
        anchor.tail = para.text
    else:
        holder.text = para.text
    for kid in list(para):
        para.addprevious(kid)
    holder.remove(para)


def bake_lists_with_para(book):
    """Port of BakeListsWithPara.v1: a list item that is one paragraph
    (the Polish books, made in Adaptarr, put each item in one) holds the
    paragraph's content itself."""
    for item in book.body.iter("li"):
        _unwrap_lone_paragraph(item)


def bake_chapter_glossary(book, chapter, sort=True, append_to=None,
                          has_para=False):
    """Port of BakeChapterGlossary.v1: the chapter's definitions, sorted
    by term and then meaning, on a page of their own. With has_para (the
    Polish books, whose meanings are paragraphs), a meaning that is one
    paragraph holds its content itself. Cookbook keeps the first
    paragraph's text alone, its italics and formulas lost; here they're
    kept."""
    if has_para:
        for dd in chapter.xpath(".//div[@data-type='glossary']//dd"):
            _unwrap_lone_paragraph(dd)
    entries = []
    for dl in chapter.xpath(".//div[@data-type='glossary']/dl"):
        dt = dl.xpath("./dt")
        dd = dl.xpath("./dd")
        # The text as it stands, spaces and all, as cookbook sorts it: a
        # term written with a line break first sorts first.
        key = (collation_key("".join(dt[0].itertext()).lower(),
                             book.language) if dt else (),
               collation_key("".join(dd[0].itertext()).lower(),
                             book.language) if dd else ())
        entries.append((key, detach(dl)))
    for glossary in chapter.xpath(".//div[@data-type='glossary']"):
        trash(glossary)
    if not entries:
        return None
    if sort:
        entries.sort(key=lambda pair: pair[0])
    content = E("div", {"class": "os-glossary-list"})
    for _, dl in entries:
        item = E("div", {"class": "os-glossary-list-item"})
        item.append(dl)
        content.append(item)
    return composite_page(book, "glossary", [content],
                          append_to if append_to is not None else chapter)


def bake_chapter_glossary_v2(book, chapter):
    """Port of BakeChapterGlossary.v2: a chapter's key terms written as
    an inline list ("STL, Binder Jetting"), a comma after each term but
    the last, where the list's own separator stood. The recipe moves the
    section to the chapter's end after."""
    for terms in chapter.xpath(f".//*[{class_test('key-terms')}]"
                               "/descendant::*[@data-type='list']"):
        for item in terms.xpath(".//*[@data-type='item']"):
            if item.getnext() is None:
                continue
            rest = re.sub(r"^\s*[;,]?\s*", "", item.tail or "")
            item.tail = ", " + rest


def bake_chapter_key_equations(book, chapter, append_to=None):
    """Port of BakeChapterKeyEquations.v1: the chapter's key equations
    on a page of their own, their titles gone."""
    return move_custom_section_to_eoc(book, chapter, "key-equations",
                                      "key-equations", append_to=append_to,
                                      each=remove_section_title)


def bake_chapter_key_concepts(book, chapter, append_to=None):
    """Port of BakeChapterKeyConcepts.v1: the chapter's key concepts on a
    page of their own, each under a link to its section's title."""
    return move_custom_section_to_eoc(book, chapter, "key-concepts",
                                      "key-concepts", append_to=append_to,
                                      wrap_section=True, wrap_content=True,
                                      each=titled_from_page(book))


def bake_chapter_section_exercises(book, chapter, trash_title=False,
                                   create_title=True):
    """Port of BakeChapterSectionExercises.v1: a section's exercises,
    their own title gone with trash_title, in a container at the
    section's end headed "1.2 Section Exercises"."""
    for page in book.non_introduction_pages(chapter):
        for section in page.xpath(
                f".//section[{class_test('section-exercises')}]"):
            if trash_title:
                old = section.xpath(".//h3[@data-type='title']")
                if old:
                    trash(old[0])
            container = E("div", {
                "class": "os-eos os-section-exercises-container",
                "data-uuid-key": ".section-exercises"})
            wrap(section, container)
            if not create_title:
                continue
            heading = E("h3", {"data-type": "document-title"})
            heading.append(span("os-text", book.t(
                "section_exercises", number=book.page_number(page))))
            insert_before(section, heading)


def bake_chapter_summary(book, chapter, klass="summary"):
    """Port of BakeChapterSummary.v1."""
    gathered = []
    for page in book.pages(chapter):
        found = page.xpath(f".//section[{class_test(klass)}]")
        if not found:
            continue
        summary = found[0]
        remove_section_title(summary)
        prepend(summary, eoc_section_title_link(book, page))
        gathered.append(detach(summary))
    if not gathered:
        return None
    return composite_page(book, klass, gathered, chapter)


def remove_section_title(section, selector="*"):
    """Port of RemoveSectionTitle.v1: the first title in the section,
    its own or, when it has none, the first one in it, as cookbook's
    search finds it; with a selector ("h3"), the first such title."""
    old = section.xpath(f".//{selector}[@data-type='title']")
    if old:
        trash(old[0])


def move_custom_section_to_eoc(book, chapter, container_key, section_class,
                               append_to=None, title=None, each=None,
                               wrap_section=False, wrap_content=False):
    """Port of MoveCustomSectionToEocContainer.v1: the chapter's sections
    of the class on a page of their own, each in a div of its own with
    wrap_section, all of them in one with wrap_content."""
    sections = []
    for page in book.pages(chapter):
        sections.extend(page.xpath(f".//section[{class_test(section_class)}]"))
    if each is not None:
        for section in sections:
            each(section)
    if not sections:
        return None
    moved = []
    for section in sections:
        if wrap_section:
            area = E("div", {"class": "os-section-area"})
            wrap(section, area)
            section = area
        moved.append(detach(section))
    if wrap_content:
        holder = E("div", {"class": f"os-{container_key}"})
        for section in moved:
            holder.append(section)
        moved = [holder]
    return composite_page(book, container_key, moved,
                          append_to if append_to is not None else chapter,
                          title=title)


def move_exercises_to_eoc(book, chapter, klass, append_to=None):
    """Port of MoveExercisesToEOC.v1."""
    return move_custom_section_to_eoc(book, chapter, klass, klass,
                                      append_to=append_to,
                                      each=remove_section_title)


def use_section_title(book, chapter, page_class, section_class):
    """Port of UseSectionTitle.v1: an end-of-chapter page named for the
    section it holds, "Chemistry Matters—Organic Foods: Risk versus
    Benefit", the section's own title gone. The dash is closed up, as the
    book's text writes one; OpenStax's page shows a space either side,
    where cookbook's templates break their lines."""
    pages = chapter.xpath(f".//*[{class_test(page_class)}]")
    if not pages:
        return
    sections = pages[0].xpath(f".//section[{class_test(section_class)}]")
    titles = sections[0].xpath(".//*[@data-type='title']") if sections \
        else []
    heading = pages[0].xpath(".//*[@data-type='document-title']")
    if not titles or not heading:
        return
    heading[0].append(span("os-divider", "\u2014"))
    heading[0].append(span("os-subtitle", text_of(titles[0])))
    trash(titles[0])


def titled_from_page(book, selector="", title_tag="h3"):
    """The block the statistics recipe passes MoveCustomSectionToEoc-
    Container for a section that keeps its page's name: its own title
    out, a link to its page's numbered title in, an h3 or title_tag."""
    def each(section):
        remove_section_title(section, selector or "*")
        prepend(section, eoc_section_title_link(book, book.page_of(section),
                                                title_tag=title_tag))
    return each


def bake_free_response(book, chapter, append_to=None):
    """Port of BakeFreeResponse.v1: each page's free-response sections
    under a link to the page's title, on a page "Homework". Only the
    first h3 of a page's sections goes, as cookbook's search finds it."""
    gathered = []
    for page in book.pages(chapter):
        sections = page.xpath(f".//section[{class_test('free-response')}]")
        if not sections:
            continue
        for section in sections:
            first = section.xpath(".//h3")
            if first:
                trash(first[0])
                break
        for section in sections:
            prepend(section, eoc_section_title_link(book, page))
            gathered.append(detach(section))
    if not gathered:
        return None
    holder = append_to if append_to is not None else chapter
    page = composite_page(book, "free-response", gathered, holder,
                          title=book.t("eoc_free_response"))
    if append_to is not None:
        page[0].tag = "h3"
    return page


def bake_chapter_references(book, chapter, klass="references",
                            section_only=False, selector=None):
    """Port of BakeChapterReferences.v1: each page's reference sections
    under a link to the page's title, on one page at the chapter's end.
    A reference is any element of class references, as the statistics
    recipe overrides cookbook's selector, or with section_only a section
    of it, as sociology's and marketing's do; selector names another
    class (cookbook's own default is "reference")."""
    gathered = []
    tag = "section" if section_only else "*"
    for page in book.pages(chapter):
        for section in page.xpath(
                f".//{tag}[{class_test(selector or klass)}]"):
            remove_section_title(section)
            prepend(section, eoc_section_title_link(book, page))
            gathered.append(section)
    if not gathered:
        return None
    return composite_page(book, klass, [detach(s) for s in gathered],
                          chapter)


def bake_chapter_references_v2(book, chapter, klass="references"):
    """Port of BakeChapterReferences.v2, endnotes: each citation in the
    chapter opens with its number, counted through the chapter, in a
    superscript; each reference's link back to its citation shows the
    number ("7."); the chapter's reference sections, their titles gone,
    on one page at the chapter's end."""
    for n, link in enumerate(chapter.xpath(".//*[@data-type='cite']"), 1):
        prepend(link, E("sup", {"class": "os-end-note-number"}, str(n)))
        for placeholder in link.xpath(
                f".//*[{class_test('delete-me')}]"):
            trash(placeholder)
    sections = chapter.xpath(f".//section[{class_test(klass)}]")
    count = 0
    for section in sections:
        remove_section_title(section)
        for link in section.xpath(".//a"):
            count += 1
            for child in list(link):
                link.remove(child)
            link.text = None
            link.append(E("span", None, f"{count}."))
    if not sections:
        return None
    return composite_page(book, klass, [detach(s) for s in sections],
                          chapter)


def bake_suggested_reading(book):
    """Port of BakeSuggestedReading.v1: each chapter's sections of class
    suggested-reading on a page of their own at its end, "Suggestions for
    Further Study", which every chapter gets, as cookbook makes it."""
    for chapter in book.chapters():
        sections = [detach(s) for s in chapter.xpath(
            f".//section[{class_test('suggested-reading')}]")]
        composite_page(book, "suggested-reading", sections, chapter,
                       title=book.t("eoc_suggested_reading"))


def bake_sortable_section(book, chapter, klass, append_to=None):
    """Port of BakeSortableSection.v1 (BakeChapterReferences.v3): every
    paragraph of the chapter's sections of the class, sorted by its
    text, on one page at the chapter's end."""
    paragraphs = []
    sections = chapter.xpath(f".//section[{class_test(klass)}]")
    for section in sections:
        for p in section.xpath(".//p"):
            paragraphs.append((collation_key("".join(p.itertext()).lower(),
                                             book.language),
                               detach(p)))
    for section in sections:
        trash(section)
    if not paragraphs:
        return None
    paragraphs.sort(key=lambda pair: pair[0])
    return composite_page(book, klass, [p for _, p in paragraphs],
                          append_to if append_to is not None else chapter)


def bake_chapter_solutions(book, chapter, classes=("free-response",)):
    """Port of BakeChapterSolutions.v1: the solutions of the named
    sections' exercises, by class and then in order, on a page
    "Solutions" at the chapter's end; made even when there are none, as
    cookbook makes it."""
    gathered = []
    for klass in classes:
        for section in chapter.xpath(f".//section[{class_test(klass)}]"):
            for exercise in section.xpath(f".//{EXERCISE}"):
                solution = exercise.xpath(f".//{SOLUTION}")
                if solution:
                    gathered.append(detach(solution[0]))
    return composite_page(book, "solutions", gathered, chapter)


# Exercises and the answer key -------------------------------------------

def bake_numbered_exercise(book, exercise, number, suppress_solution=False,
                           solution_stays_put=False,
                           note_suppressed_solutions=False,
                           suppress_solution_title=False, chapter_number=None,
                           cases=False):
    """Port of BakeNumberedExercise.v1: the problem opens with its
    number, which links to its solution in the answer key; the solution
    opens with the number, linking back. suppress_solution is the option
    suppress_solution_if: true, or "even" or "odd" for the numbers whose
    solutions go (Introduction to Sociology keeps the odd ones').
    chapter_number is the chapter's as the recipe counts it, where that
    isn't its place in the book."""
    if suppress_solution in ("even", "odd"):
        suppress_solution = (int(number) % 2 == 0) == (
            suppress_solution == "even")
    page = book.page_of(exercise)
    in_appendix = page is not None and has_class(page, "appendix")
    chapter = book.chapter_of(exercise)
    if in_appendix or chapter is None:
        label_number = str(number)
        title_label = book.t("exercise")
        divider = ""
    else:
        label_number = f"{chapter_number or book.chapter_number(chapter)}." \
                       f"{number}"
        title_label = None
        divider = ". "
    if cases:
        book.target_label_cases(exercise, "exercise", label_number)
    else:
        book.target_label(exercise, f"{book.t('exercise')} {label_number}")
    problems = exercise.xpath("./div[@data-type='problem']")
    solutions = exercise.xpath("./div[@data-type='solution']")
    problem = problems[0] if problems else None
    solution = solutions[0] if solutions else None
    number_el = span("os-number", str(number))
    if solution is not None:
        if suppress_solution:
            trash(solution)
            if note_suppressed_solutions:
                add_class(exercise, "os-hasSolution-trashed")
        else:
            if not (solution_stays_put or in_appendix):
                number_el = E("a", {"class": "os-number",
                                    "href": f"#{exercise.get('id')}-solution"},
                              str(number))
            _bake_solution(book, exercise, solution, number,
                           solution_stays_put, in_appendix,
                           with_title=not suppress_solution_title)
    if problem is None:
        return
    container = E("div", {"class": "os-problem-container"})
    move_children(problem, container)
    if title_label:
        problem.append(span("os-title-label", title_label))
    problem.append(number_el)
    if divider:
        problem.append(span("os-divider", divider))
    problem.append(container)


def bake_note_exercise(book, note, exercise, divider=" ",
                       suppress_solution=False):
    """Port of BakeNoteExercise.v1: an exercise in a numbered note goes
    unnumbered; its solution, kept, takes the note's number."""
    add_class(exercise, "unnumbered")
    found = note.xpath(f".//*[{class_test('os-number')}]")
    number = text_of(found[0]).replace("#", "") if found else ""
    problems = exercise.xpath(".//div[@data-type='problem']")
    if problems:
        wrap_children(problems[0], E("div", {"class": "os-problem-container"}))
    for commentary in exercise.xpath(".//*[@data-type='commentary']"):
        trash(commentary)
    solutions = exercise.xpath(f".//{SOLUTION}")
    if not solutions:
        return
    if suppress_solution:
        add_class(exercise, "os-hasSolution")
        trash(solutions[0])
    else:
        _bake_solution(book, exercise, solutions[0], number, False, False,
                       divider=divider)


def _bake_solution(book, exercise, solution, number, stays_put, in_appendix,
                   divider=". ", with_title=True):
    if stays_put:
        wrap_children(solution, E("div", {"class": "os-solution-container"}))
        if with_title:
            heading = E("h4", {"class": "solution-title",
                               "data-type": "title"})
            heading.append(span("os-text", book.t("solution")))
            prepend(solution, heading)
        return
    solution.set("id", f"{exercise.get('id')}-solution")
    add_class(exercise, "os-hasSolution")
    if in_appendix:
        wrap_children(solution, E("div", {"class": "os-solution-container"}))
        return
    container = E("div", {"class": "os-solution-container"})
    move_children(solution, container)
    solution.append(E("a", {"class": "os-number",
                            "href": f"#{exercise.get('id')}"}, str(number)))
    solution.append(span("os-divider", divider))
    solution.append(container)


def book_answer_key_container(book, solutions_plural=True):
    """Port of BookAnswerKeyContainer.v1: the composite chapter "Answer
    Key" at the end of the book."""
    which = "solutions" if solutions_plural else "solution"
    chapter = E("div", {"class": f"os-eob os-{which}-container",
                        "data-type": "composite-chapter",
                        "data-uuid-key": which})
    heading = E("h1", {"data-type": "document-title"})
    heading.append(span("os-text", book.t("answer_key_title")))
    chapter.append(heading)
    book.body.append(chapter)
    return chapter


def answer_key_inner_container(book, chapter, append_to,
                               solutions_plural=True, in_appendix=False,
                               in_preface=False):
    """Port of AnswerKeyInnerContainer.v1: the answer key's page for one
    chapter, titled "Chapter 3", or for an appendix ("Appendix A") or the
    preface."""
    which = "solutions" if solutions_plural else "solution"
    if in_appendix:
        letter = string.ascii_uppercase[book.pages(cls="appendix").index(
            chapter)]
        title, key = f"{book.t('appendix')} {letter}", f"appendix{which}"
    elif in_preface:
        title, key = book.t("preface"), f"preface{which}"
    else:
        n = book.chapter_number(chapter)
        title, key = f"{book.t('chapter')} {n}", f"{which}{n}"
    page = E("div", {"class": f"os-eob os-{which}-container",
                     "data-type": "composite-page",
                     "data-uuid-key": f".{key}"})
    heading = E("h2", {"data-type": "document-title"})
    heading.append(span("os-text", title))
    page.append(heading)
    append_to.append(page)
    return page


def default_strategy_for_answer_key_solutions(book, chapter, selectors,
                                              append_to):
    """Port of DefaultStrategyForAnswerKeySolutions.v1: the chapter's
    solutions from the named sections, in order, into its answer key
    page."""
    for cls in selectors:
        for solution in chapter.xpath(
                f".//section[{class_test(cls)}]/descendant::{SOLUTION}"):
            append_to.append(detach(solution))


def answer_key_cleaner(book, remove_empty_container=False):
    """Port of AnswerKeyCleaner.v1: an answer key page with no solution
    on it goes, an exercise's or an injected question's."""
    for container in book.body.xpath(
            f".//div[@data-type='composite-chapter'][{class_test('os-eob')}]"
            f"[{class_test('os-solutions-container')} or "
            f"{class_test('os-solution-container')}]"):
        for page in container.xpath("./div[@data-type='composite-page']"):
            if not page.xpath(".//*[@data-type='solution' or "
                              "@data-type='question-solution']"):
                trash(page)
        if remove_empty_container and not container.xpath(
                "./div[@data-type='composite-page']"):
            trash(container)


# Tables and equations --------------------------------------------------

def _table_caption(table, number=None, label=None):
    """The caption container cookbook puts after a table: "Table 3.1
    Price and Quantity Demanded of Gasoline", then any caption."""
    caption = table.xpath("./caption")
    title = caption[0].xpath("./span[@data-type='title']") if caption else []
    if title:
        detach(title[0])
    # What's left of the caption is the caption, as cookbook takes it:
    # ours in a span of its own, OpenStax's assembly's bare beside the
    # title.
    text = None
    if caption:
        rest = detach(caption[0])
        wrapped = rest.xpath("./span[@data-type='caption']")
        if len(rest) == 1 and wrapped and not (rest.text or "").strip() \
                and not (wrapped[0].tail or "").strip():
            text = wrapped[0]
        else:
            text = rest
    container = E("div", {"class": "os-caption-container"})
    if number is not None:
        container.append(span("os-title-label", label + " "))
        container.append(span("os-number", number))
        container.append(span("os-divider", " "))
    if title:
        out = span("os-title", data_type="title")
        move_children(title[0], out)
        container.append(out)
    shown = text is not None and (len(text) or (text.text or "").strip())
    if shown:
        container.append(span("os-divider", " "))
        out = span("os-caption")
        move_children(text, out)
        container.append(out)
    return container, bool(title) or bool(shown)


def bake_numbered_table(book, table, number, move_caption_on_top=False,
                        label_class=None, cases=False):
    """Port of BakeNumberedTable.v1 (and BakeTableBody.V1, as far as it
    changes the text): the caption goes after the table, or before it
    with move_caption_on_top, in a wrapper that holds both."""
    label = book.t("table")
    wrapper = wrap(table, E("div", {"class": "os-table"}))
    if cases:
        book.target_label_cases(table, "table", number, label_class)
    else:
        book.target_label(table, f"{label} {number}", label_class)
    if has_class(table, "top-titled"):
        _top_titled(table, wrapper)
    elif has_class(table, "top-captioned"):
        _top_captioned(table, wrapper)
    container, _ = _table_caption(table, number, label)
    if move_caption_on_top:
        insert_before(table, container)
    else:
        insert_after(table, container)


def bake_numbered_table_v2(book, table, number, label_class=None,
                           cases=False):
    """Port of BakeNumberedTable.v2: as v1, but the caption, title and
    all, is one span after the label and number."""
    label = book.t("table")
    wrapper = wrap(table, E("div", {"class": "os-table"}))
    if cases:
        book.target_label_cases(table, "table", number, label_class)
    else:
        book.target_label(table, f"{label} {number}", label_class)
    if has_class(table, "top-titled"):
        _top_titled(table, wrapper)
    elif has_class(table, "top-captioned"):
        _top_captioned(table, wrapper)
    container = E("div", {"class": "os-caption-container"})
    container.append(span("os-title-label", label + " "))
    container.append(span("os-number", number))
    container.append(span("os-divider", " "))
    caption = table.xpath("./caption")
    if caption:
        # Cookbook renames the caption a span and puts a divider after
        # its first part; the title's words go in it bare here, as a
        # caption's title is shown, and the caption's after them.
        caption = detach(caption[0])
        parts = [("text", caption.text)] if (caption.text or "").strip() \
            else []
        for child in caption:
            parts.append(("element", child))
            if (child.tail or "").strip():
                parts.append(("text", child.tail))
        out = span("os-caption")
        for i, (kind, part) in enumerate(parts):
            if i == 1:
                out.append(span("os-divider", " "))
            if kind == "text":
                append_text(out, part)
            elif part.get("data-type") in ("title", "caption"):
                append_text(out, part.text)
                for kid in list(part):
                    out.append(kid)
            else:
                part.tail = None
                out.append(part)
        container.append(out)
    insert_after(table, container)


def _top_captioned(table, wrapper):
    """BakeTableBody's top-captioned table: the title of its caption set
    above the table, the caption gone."""
    caption = table.xpath("./caption")
    if not caption:
        return
    title = E("div", {"class": "os-top-caption"})
    found = caption[0].xpath("./span[@data-type='title']")
    if found:
        title.text = found[0].text
        for kid in list(found[0]):
            title.append(kid)
    prepend(wrapper, title)
    trash(caption[0])


def _top_titled(table, wrapper):
    """A table whose first head row is its title (class top-titled):
    the row taken out and set above the table."""
    rows = table.xpath("./thead/tr")
    if not rows:
        return
    row = rows[0]
    cells = row.xpath("./th|./td")
    title = E("div", {"class": "os-table-title"})
    if cells:
        move_children(cells[0], title)
    prepend(wrapper, title)
    trash(row)


def bake_unnumbered_tables(book):
    """Port of BakeUnnumberedTables.v1."""
    for table in book.tables():
        if not has_class(table, "unnumbered"):
            continue
        if table.getparent() is not None and has_class(table.getparent(),
                                                       "os-table"):
            continue
        wrapper = wrap(table, E("div", {"class": "os-table"}))
        if has_class(table, "top-titled"):
            _top_titled(table, wrapper)
        container, any_caption = _table_caption(table)
        if any_caption:
            insert_after(table, container)


def bake_equations(book, decorator="none", cases=False):
    """Port of BakeEquations.v1: an equation not marked unnumbered gets
    its chapter's number, 3.1."""
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        count = 0
        for eq in chapter.xpath(".//div[@data-type='equation']"):
            if has_class(eq, "unnumbered"):
                continue
            count += 1
            number = f"{n}.{count}"
            if cases:
                book.target_label_cases(eq, "equation", number)
            else:
                book.target_label(eq, f"{book.t('equation')} {number}")
            shown = f"({number})" if decorator == "parentheses" else number
            holder = E("div", {"class": "os-equation-number"})
            holder.append(span("os-number", shown))
            eq.append(holder)


# References ------------------------------------------------------------

def bake_references_v2(book):
    """Port of BakeReferences.v2: every chapter's references, under the
    chapter's title, on one page at the end of the book."""
    areas = []
    for chapter in book.chapters():
        refs = chapter.xpath(f".//{_page_like()}//section"
                             f"[{class_test('references')}]")
        for section in refs:
            # Cookbook trashes the sections' h3s, which is what their
            # titles are in OpenStax's assembled pages; here a title is
            # marked by its data-type, whatever its tag.
            for heading in section.xpath(".//*[@data-type='title']"):
                trash(heading)
        title = book.page_title(chapter)
        texts = title.xpath(".//span[@class='os-text']")
        area = E("div", {"class": "os-chapter-area"})
        heading = E("h2", {"data-type": "document-title",
                           "data-rex-keep": "true"})
        if texts:
            heading.append(copy.deepcopy(texts[0]))
        else:
            heading.text = text_of(title)
        area.append(heading)
        for section in refs:
            area.append(detach(section))
        areas.append(area)
    return composite_page(book, "references", areas, book.body,
                          section="eob", uuid_key=".references")


def bake_references_v3(book):
    """Port of BakeReferences.v3: each reference section on a chapter's
    pages, its titles gone, under its page's numbered title (an h2, no
    link), all of them on one page at the end of the book."""
    test = f".//section[{class_test('references')}]"
    if not book.body.xpath(test):
        return None
    for chapter in book.chapters():
        for page in book.pages(chapter):
            for section in page.xpath(test):
                for title in section.xpath(".//*[@data-type='title']"):
                    trash(title)
                prepend(section, eoc_section_title_link(
                    book, page, title_tag="h2", wrapper=None))
    sections = [detach(section) for chapter in book.chapters()
                for section in chapter.xpath(test)]
    return composite_page(book, "references", sections, book.body,
                          section="eob", uuid_key=".references")


def bake_references_v4(book, klass="references"):
    """Port of BakeReferences.v4: each chapter's reference sections,
    their titles gone, under a heading naming the chapter ("Chapter 3
    Pharmacokinetics") that links to its introduction, on one page at
    the end of the book."""
    areas = []
    for n, chapter in enumerate(book.chapters(), 1):
        sections = chapter.xpath(f".//{_page_like()}//section"
                                 f"[{class_test(klass)}]")
        for section in sections:
            for heading in section.xpath(".//h3"):
                trash(heading)
        sections = [s for s in sections if book.page_of(s) is not None
                    and book.page_of(s).get("data-type") == "page"]
        if not sections:
            continue
        intro = book.introduction_page(chapter)
        link = E("a", {"href": f"#{intro.get('id')}_titlecreatedbycookbook"
                       if intro is not None else "#"})
        heading = E("h2", {"data-type": "document-title",
                           "data-rex-keep": "true"})
        heading.append(span("os-part-text", book.t("chapter") + " "))
        heading.append(span("os-number", str(n)))
        heading.append(span("os-divider", " "))
        title = book.page_title(chapter)
        texts = title.xpath(".//span[@class='os-text']") \
            if title is not None else []
        if texts:
            heading.append(copy.deepcopy(texts[0]))
        link.append(heading)
        area = E("div", {"class": "os-chapter-area"})
        area.append(link)
        for section in sections:
            area.append(detach(section))
        areas.append(area)
    return composite_page(book, "references", areas, book.body,
                          section="eob", uuid_key=".references")


def bake_references_v1(book, numbered_title=False):
    """Port of BakeReferences.v1, for references written as notes inside
    their citations: each citation numbered in a superscript, counted
    through its chapter, a citation that follows another with nothing
    between parted from it by a comma; each reference numbered to match
    ("3. "); and every chapter's references, under the chapter's title,
    on one page at the end of the book, each citation linking to its
    reference there."""
    areas = []
    for chapter in book.chapters():
        for n, link in enumerate(chapter.xpath(".//*[@data-type='cite']"),
                                 1):
            prepend(link, E("sup", {"class": "os-citation-number"},
                            str(n)))
            previous = link.getprevious()
            between = (previous.tail if previous is not None
                       else link.getparent().text) or ""
            if previous is None or between.strip() or \
                    previous.get("data-type") != "cite":
                continue
            separator = span("os-reference-link-separator")
            separator.append(E("sup", None, ", "))
            insert_before(link, separator)
        references = chapter.xpath(f".//*[{class_test('reference')}]")
        for n, reference in enumerate(references, 1):
            prepend(reference, span("os-reference-number", f"{n}. "))
        gathered = [r for r in references
                    if book.page_of(r) is not None
                    and book.page_of(r).get("data-type") == "page"]
        title = book.page_title(chapter)
        wanted = ("os-number", "os-divider", "os-text") if numbered_title \
            else ("os-text",)
        heading = E("h2", {"data-type": "document-title",
                           "data-rex-keep": "true"})
        if title is not None:
            for part in title.iter("span"):
                if set(classes(part)) & set(wanted):
                    heading.append(copy.deepcopy(part))
        area = E("div", {"class": "os-chapter-area"})
        area.append(heading)
        for reference in gathered:
            area.append(detach(reference))
        areas.append(area)
    return composite_page(book, "reference", areas, book.body,
                          section="eob", uuid_key=".reference")


def _page_like():
    return "div[@data-type='page']"


# Footnotes -------------------------------------------------------------

def bake_footnotes(book):
    """BakeFootnotes.v1 numbers each page's footnotes and puts their
    text at the page's end. Here each footnote becomes a reference and a
    note as Pandoc writes them (role doc-noteref, a doc-endnotes section),
    numbered in the page, so Pandoc's reader makes notes of them and
    TextbookImprover numbers and places them by its notes settings."""
    for page in book.body.xpath(".//div[@data-type='page'] | "
                                ".//div[@data-type='composite-page']"):
        notes = [n for n in page.xpath(".//span[@data-type='footnote']")
                 if book.page_of(n) is page]
        if not notes:
            continue
        section = E("section", {"role": "doc-endnotes",
                                "class": "footnotes"})
        ol = E("ol")
        section.append(ol)
        for n, note in enumerate(notes, 1):
            ident = note.get("id") or f"{page.get('id')}__fn{n}"
            ref = E("a", {"role": "doc-noteref", "href": f"#{ident}",
                          "id": f"{ident}-ref", "class": "footnote-ref"})
            ref.append(E("sup", None, str(n)))
            replace(note, ref)
            li = E("li", {"id": ident})
            p = E("p")
            move_children(note, p)
            li.append(p)
            ol.append(li)
        page.append(section)


def bake_reference_footnotes(book, klass="reference"):
    """Port of BakeFootnotes.v1 with a selector (.reference), for the
    Polish *Marketing*, whose references are footnotes of that class:
    numbered through each chapter, and each page outside one, each a
    superscript number where it stood that links to the reference, and
    the reference a paragraph opening with the number, which links back
    ("1."), at the end of its page, for BakeChapterReferences.v4 to
    gather at the chapter's end."""
    holders = [child for child in book.body if isinstance(child.tag, str)
               and child.get("data-type") in ("page", "composite-page",
                                              "composite-chapter")]
    for holder in holders + book.chapters():
        # OpenStax's assembly's shape, which cookbook's samples are in: a
        # link to an aside, numbered as cookbook numbers them.
        asides = {}
        for n, ref in enumerate(holder.xpath(
                f".//a[@role='doc-noteref'][{class_test(klass)}]"), 1):
            for child in list(ref):
                ref.remove(child)
            ref.text = str(n)
            target = (ref.get("href") or "")[1:]
            asides[target] = str(n)
            ref.set("id", f"{target}-a")
        for aside in holder.xpath(f".//aside[{class_test(klass)}]"):
            wrap_children(aside, E("span"))
            prepend(aside, E("a", {"href": f"#{aside.get('id')}-a",
                                   "data-type": "footnote-number"},
                             f"{asides.get(aside.get('id'), '')}."))
        notes = holder.xpath(f".//span[@data-type='footnote']"
                             f"[{class_test(klass)}]")
        for n, note in enumerate(notes, 1):
            page = book.page_of(note)
            ident = note.get("id") or \
                f"{page.get('id') if page is not None else 'book'}__ref{n}"
            ref = E("a", {"href": f"#{ident}", "id": f"{ident}-a",
                          "data-type": "reference-ref"})
            ref.append(E("sup", None, str(n)))
            replace(note, ref)
            entry = E("p", {"class": f"os-{klass}", "id": ident})
            back = E("a", {"href": f"#{ident}-a"}, f"{n}.")
            back.tail = " "
            entry.append(back)
            out = span(None)
            move_children(note, out)
            entry.append(out)
            (page if page is not None else holder).append(entry)


def bake_chapter_references_v4(book, chapter, klass="references",
                               reference="reference"):
    """Port of BakeChapterReferences.v4: the chapter's references (here,
    the paragraphs bake_reference_footnotes made of them) on one page at
    its end."""
    found = chapter.xpath(f".//p[{class_test('os-' + reference)}] | "
                          f".//aside[{class_test(reference)}]")
    if not found:
        # Cookbook makes the page with nothing on it.
        return None
    return composite_page(book, klass, [detach(p) for p in found], chapter)


# Index -----------------------------------------------------------------

# CLDR's root order of the spaces, punctuation, and symbols books use, as
# twitter_cldr, the collator cookbook sorts with, gives it: each sorts
# before every digit and letter, in this order; characters that share a
# place (a hyphen and a non-breaking one) are in one string.
PUNCTUATION_ORDER = [
    "\t", "\n", "\r", " ", "_", "-", "\u2010\u2011", "\u2012", "\u2013",
    "\u2014", "\u2015", ",", ";", ":", "!", "\u00a1", "?", "\u00bf", ".",
    "\u00b7", "'", "\u2018", "\u2019", "\u2039", "\u203a", '"',
    "\u201c", "\u201d", "\u00ab", "\u00bb", "(", ")", "[", "]", "{", "}",
    "\u00a7", "\u00b6", "@", "*", "/", "\\", "&", "#", "%", "\u2020",
    "\u2021", "\u2022", "\u2032", "`", "^", "\u00b0", "\u00a9", "\u00ae",
    "\u2190", "\u2192", "+", "\u00b1", "\u00f7", "\u00d7", "<",
    "=\u2260", ">", "|", "~", "\u2212", "\u221e", "\u2264", "\u2265",
    "\u00a2", "$", "\u00a3", "\u00a5", "\u20ac",
]
PUNCTUATION_RANK = {c: rank for rank, chars in enumerate(PUNCTUATION_ORDER)
                    for c in chars}
# Characters CLDR sorts as others: an ellipsis as three periods.
EXPANSIONS = {"\u2026": "...", "\u2033": "\u2032\u2032", "\u2122": "TM"}


# CLDR's Polish collation: these letters are letters of their own, each
# after the one it's made from (&A<ą, &C<ć, &E<ę, &L<ł, &N<ń, &O<ó,
# &S<ś, &Z<ź<ż), where the root collation takes ą for an a with an
# accent.
POLISH_LETTERS = {"ą": ("a", 1), "ć": ("c", 1), "ę": ("e", 1),
                  "ł": ("l", 1), "ń": ("n", 1), "ó": ("o", 1),
                  "ś": ("s", 1), "ź": ("z", 1), "ż": ("z", 2)}


def collation_key(text, language="en"):
    """CLDR's root collation, which cookbook sorts with, as far as books'
    words need: letters compared without case or accents first; spaces,
    punctuation, and symbols before digits, in CLDR's order, digits
    before letters; then accents, then lowercase before uppercase. It
    orders the 12,934 terms of eight of OpenStax's repositories as
    twitter_cldr does. For a book in Polish, CLDR's Polish collation,
    which twitter_cldr gives cookbook for one: ą after a, ł after l, and
    the like, ż after ź."""
    primary, secondary, tertiary = [], [], []
    # A Polish letter written as a letter and an accent is one letter.
    source = unicodedata.normalize("NFC", text) if language == "pl" \
        else text
    for ch in "".join(EXPANSIONS.get(c, c) for c in source):
        own = POLISH_LETTERS.get(ch.lower()) if language == "pl" else None
        if own is not None:
            primary.append((2,) + own)
            secondary.append("")
            tertiary.append(0 if ch.islower() else 1)
            continue
        base = unicodedata.normalize("NFKD", ch)
        letters = "".join(c for c in base if not unicodedata.combining(c))
        accents = "".join(c for c in base if unicodedata.combining(c))
        for c in letters or ch:
            if c.isalpha():
                primary.append((2, c.casefold(), 0))
            elif c.isdigit():
                primary.append((1, c))
            elif c in PUNCTUATION_RANK:
                primary.append((0, PUNCTUATION_RANK[c]))
            else:
                primary.append((0, len(PUNCTUATION_ORDER) + ord(c)))
        secondary.append(accents)
        tertiary.append(0 if ch.islower() or not ch.isalpha() else 1)
    return (tuple(primary), tuple(secondary), tuple(tertiary))


def _uncapitalize(text):
    """Kitchen's String#uncapitalize: a first letter A to Z lowercase."""
    return text[:1].lower() + text[1:] if "A" <= text[:1] <= "Z" else text


def _capitalize(text):
    """Ruby's String#capitalize: the first letter up, the rest down."""
    return text[:1].upper() + text[1:].lower()


# The Latin letters Ruby's I18n.transliterate spells in others, which
# NFKD doesn't take apart (its default approximations).
TRANSLITERATED = {"Æ": "AE", "æ": "ae", "Ð": "D", "ð": "d", "Ø": "O",
                  "ø": "o", "Þ": "Th", "þ": "th", "ß": "ss", "Đ": "D",
                  "đ": "d", "Ħ": "H", "ħ": "h", "ı": "i", "Ĳ": "IJ",
                  "ĳ": "ij", "ĸ": "q", "Ŀ": "L", "ŀ": "l", "Ł": "L",
                  "ł": "l", "Ŋ": "NG", "ŋ": "ng", "Œ": "OE", "œ": "oe",
                  "Ŧ": "T", "ŧ": "t"}


def _group_of(text, language="en"):
    """The group a term is listed under, as cookbook's BakeIndex finds it:
    its first character as I18n.transliterate spells it in ASCII, an
    accent taken off, capitalized; None for the symbols' group, where a
    character with no ASCII spelling goes, as I18n writes it "?": a
    digit, a sign, and a letter of another script, Greek's α among them
    (*Biology 2e*'s "α-helix" is under Symbols). A Polish book's is the
    character as it stands (I18n.character_to_group), "Ł" its own
    group, and only a character that isn't a letter goes to Symbols."""
    first = text.strip()[:1]
    if not first:
        return None
    if language == "pl":
        return _capitalize(first) if first.isalpha() else None
    spelled = TRANSLITERATED.get(first)
    if spelled is None:
        base = unicodedata.normalize("NFKD", first)
        spelled = "".join(c for c in base if not unicodedata.combining(c))
    if not re.match(r"[A-Za-z]", spelled):
        return None
    return spelled[:1].upper() + spelled[1:].lower()


def _index_kind(term):
    """Which of a Polish book's indexes a term goes in: a person's name
    (cxlxt:index="name"), a word of another language ("foreign"), or the
    terms' own ("term")."""
    kind = extra_attribute(term, "index")
    return kind if kind in ("name", "foreign") else "term"


def bake_index(book, types=("main",)):
    """Port of BakeIndex.v1: every term in the book's pages, grouped by
    first letter, each listed with links to the pages that use it,
    titled as the pages are. With types (a Polish book's name, term, and
    foreign), each kind of term is in an index of its own, as its index
    attribute says, and listed by the form the index gives it where it
    has one: its cmlnle:reference ("wrażenia zmysłowe" for "wrażeń
    zmysłowych"), or a person's cxlxt:name ("Darwin, Karol"), grouped by
    that form's first character as it stands."""
    symbols_group = book.t("eob_index_symbols_group")
    found = {("term" if kind == "main" else kind): [] for kind in types}

    def page_title_text(page):
        if page.get("data-type") == "composite-page":
            # CompositePageElement#title: an h3 title as well, a page's
            # in a group of pages (a chapter's review).
            found = [t for t in page.xpath(
                ".//h3[@data-type='title'] | "
                ".//h2[@data-type='document-title'] | "
                ".//h1[@data-type='document-title']")
                if t.getparent().get("data-type") != "metadata"]
            return text_of(found[0]) if found else ""
        title = book.page_title(page)
        return text_of(title) if title is not None else ""

    def add(term, page_title):
        reference = extra_attribute(term, "reference")
        name = extra_attribute(term, "name")
        if reference is not None or name is not None:
            text = reference if reference is not None else name
            text, shown = text.strip(), None
            group = text[:1] or None
        else:
            text, shown = text_of(term), term
            group = _group_of(text, book.language)
        if not text:
            return
        if group is not None and not re.match(r"[^\W\d_]", group):
            group = None
        if not term.get("id"):
            count = sum(len(entries) for entries in found.values())
            term.set("id", f"auto_{count + 1}_term")
        # A kind the recipe has no index for goes in the terms' own.
        kind = _index_kind(term)
        if kind not in found:
            kind = "term"
        lang = None
        parent = term.getparent()
        if parent is not None and parent.get("data-type") == "foreign":
            lang = parent.get("lang") or parent.get(
                "{http://www.w3.org/XML/1998/namespace}lang")
        found[kind].append((text, shown, term, page_title, group, lang))

    pages = book.body.xpath(".//div[@data-type='page'] | "
                            ".//div[@data-type='composite-page']")
    front = [p for p in pages if has_class(p, "preface")
             or has_class(p, "unit-opener")]
    back = [p for p in pages if has_class(p, "appendix")
            or has_class(p, "handbook")]
    middle = []
    for chapter in book.chapters():
        middle.extend(chapter.xpath(".//div[@data-type='page'] | "
                                    ".//div[@data-type='composite-page']"))
    for page in front + middle + back:
        title = page_title_text(page)
        if page.get("data-type") == "composite-page":
            chapter = book.chapter_of(page)
            if chapter is not None:
                title = f"{book.chapter_number(chapter)} {title}".strip()
        for term in page.xpath(f".//{TERM}"):
            if book.page_of(term) is not page:
                continue
            add(term, title)
    made = None
    for kind in types:
        name = "term" if kind == "main" else kind
        if found[name]:
            made = _index_page(book, kind, found[name], symbols_group)
    return made


def _index_page(book, kind, terms, symbols_group):
    # IndexSection#item_for: one entry for a term written with and
    # without a capital, as cookbook finds the two. A term matches an
    # entry whose text is its own with the first letter lowercase (A-Z
    # only), or else its own as Ruby's capitalize makes it, first letter
    # up and the rest down, so "Gross domestic product (GDP)", met after
    # "gross domestic product (GDP)", joins it, and met first, doesn't.
    # The one difference: a term's spaces are evened out first, so one
    # typed with two spaces joins the same words typed with one, where
    # cookbook lists the two apart and they read alike.
    language = book.language
    groups = {}
    for text, shown, term, title, group, lang in terms:
        group = _capitalize(group) if group else symbols_group
        items, by_text = groups.setdefault(group, ([], {}))
        item = by_text.get(text)
        if item is None:
            item = by_text.get(_uncapitalize(text))
            if item is not None:
                item[0] = _uncapitalize(item[0])
            else:
                item = by_text.get(_capitalize(text))
                if item is not None:
                    item[0] = _capitalize(item[0])
            if item is None:
                item = [text, []]
                items.append(item)
            by_text[text] = item
        item[1].append((shown, term, title, lang))
    suffix = "" if kind == "main" else f"-{kind}"
    page = E("div", {"class": f"os-eob os-index{suffix}-container",
                     "data-type": "composite-page",
                     "data-uuid-key": f"index{suffix}"})
    heading = E("h1", {"data-type": "document-title"})
    heading.append(span("os-text", book.t(f"index.{kind}")))
    page.append(heading)
    order = sorted(groups, key=lambda g: (g != symbols_group,
                                          collation_key(g, language)))
    for group in order:
        holder = E("div", {"class": "group-by"})
        holder.append(span("group-label", group))
        for text, found in sorted(
                groups[group][0],
                key=lambda entry: collation_key(entry[0], language)):
            item = E("div", {"class": "os-index-item"})
            for i, (shown, term, title, lang) in enumerate(found):
                if i == 0:
                    out = span("os-term")
                    if shown is None:
                        out.text = text
                    else:
                        out.text, kids = shown.text, [copy.deepcopy(k)
                                                      for k in shown]
                        for kid in kids:
                            out.append(kid)
                    if kind == "foreign" and lang:
                        out.set("lang", lang)
                    # The space cookbook's template leaves between the
                    # term and its first link.
                    out.tail = " "
                    item.append(out)
                else:
                    item.append(span("os-index-link-separator", ", "))
                link = E("a", {"class": "os-term-section-link",
                               "href": f"#{term.get('id')}"})
                link.append(span("os-term-section", title))
                item.append(link)
            holder.append(item)
        page.append(holder)
    book.body.append(page)
    return page


# Links -----------------------------------------------------------------

def bake_link_placeholders(book, replace_section_link_text=False,
                           cases=False):
    """Port of BakeLinkPlaceholders.v1, without the aria-label: a link
    with no text of its own shows what baking named its target, "Figure
    3.2" or "3.1 Demand, Supply, and Equilibrium in Markets for Goods and
    Services". One whose target baking named nothing is left for
    pages.py to name or report. OpenStax's assembly gives such a link
    the text "[link]", which is what cookbook looks for; ours leaves it
    empty. With replace_section_link_text, a link to a chapter's page
    shows its number alone ("Section 3.1"). With cases (a Polish book),
    a link shows its target's name in the case its sentence wants
    (cmlnle:case in the source), or in the nominative if it names
    none."""
    sections = set()
    if replace_section_link_text:
        sections = {page.get("id") for chapter in book.chapters()
                    for page in book.pages(chapter) if page.get("id")}
    for link in book.body.xpath(".//a[" + class_test("autogenerated-content")
                                + " or normalize-space(.)='[link]']"):
        href = link.get("href") or ""
        if not href.startswith("#") or len(link) or \
                (link.text or "").strip() not in ("", "[link]"):
            continue
        target = href[1:]
        if cases:
            case = extra_attribute(link, "case") or "nominative"
            text = book.case_labels.get(target, {}).get(case)
        else:
            text = book.labels.get(target)
        if text and target in sections:
            # Cookbook's own test: the first "n.n" in the label.
            number = re.search(r"([1-9][0-9]|[0-9]).([0-9][0-9]|[0-9])",
                               text)
            if number:
                text = f"{book.t('section')} {number.group(0)}"
        if text:
            link.text = text
            remove_class(link, "autogenerated-content")
            link.set("data-label-from", "baking")
            kind = book.link_types.get(target)
            if kind:
                add_class(link, kind)



def bake_lo_link_labels(book):
    """Port of BakeLOLinkLabels.v1: a link to a learning objective's
    section shows "LO " and the section's number ("LO 3.1"), its title
    left out. The links stand side by side in OpenStax's markup, before
    the exercise's words, their stylesheet setting them apart; here a
    space after each does."""
    for link in book.body.xpath(f".//a[{class_test('lo-reference')}]"):
        target = (link.get("href") or "")[1:]
        number = book.label_numbers.get(target)
        if number is not None and link.get("data-label-from") == "baking":
            for child in list(link):
                link.remove(child)
            link.text = number
        prepend(link, span("label-text", book.t("lo_label_text")))
        if not (link.tail or "")[:1].isspace():
            link.tail = " " + (link.tail or "")


def bake_exercise_prefixes(book, chapter, sections):
    """Port of BakeExercisePrefixes.v1: an exercise in an end-of-chapter
    section the locale names a prefix for opens with it, before its
    number ("EA1")."""
    for key in sections:
        for composite in chapter.xpath(".//div[@data-type='composite-page']"):
            for exercise in composite.xpath(
                    f".//section[{class_test(key)}]/descendant::{EXERCISE}"):
                problems = exercise.xpath("./div[@data-type='problem']")
                if problems:
                    prepend(problems[0], span(
                        "os-text", book.t(f"sections_prefixed.{key}")))

# After every recipe ---------------------------------------------------------
#
# Cookbook's post_bake recipe (lib/recipes/post_bake/recipe.rb), which
# every book OpenStax bakes goes through: an address or an email address
# written as text becomes a link to itself, as it is on openstax.org and
# in OpenStax's Word files (303 such links in Economics 3e's references).
# Its other steps are left out: heading levels (emit.py sets them), and
# the aria-label and data-bare-link it gives every link.

URL_PATTERN = (r"(?:https?://[^\s<>\"]+[^\s<>\".,;:!?)\]}]"
               r"|www\.[^\s<>\"]+[^\s<>\".,;:!?)\]}])")
EMAIL_PATTERN = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
LINK_PATTERN = re.compile(f"({EMAIL_PATTERN}|{URL_PATTERN})", re.I)
EMAIL_RE = re.compile(EMAIL_PATTERN)
URL_RE = re.compile(URL_PATTERN, re.I)
# Cookbook's fast check, \p{L} as Python spells a letter or digit.
QUICK_CHECK = re.compile(r"://|www|@|[^\W_]\.[^\W_]")
# What an address written as text can hold that a link's address can't
# (the URL Standard's code points, as the Nu checker and epubcheck read
# them): a % that starts no escape, as an address a line break cuts in
# two leaves one ("…#:~:text=In%", Lifespan Development), and {, }, |,
# ^, `, [ and ] (Accounting's "#{%22issue_id%22:390208…"), and a # after
# the one that opens the fragment (Marketing's "…year=1994##document…").
# Each is its escape in the link, where cookbook writes it as it is; the
# text shows it as written.
URL_UNSAFE = re.compile(r"%(?![0-9A-Fa-f]{2})|[{}|^`\[\]]")


def _escaped(href):
    """href with what a link's address can't hold escaped (URL_UNSAFE)."""
    head, mark, fragment = href.partition("#")
    href = head + mark + fragment.replace("#", "%23")
    return URL_UNSAFE.sub(lambda m: "%%%02X" % ord(m.group()), href)
# Whose text is left alone, inside and out: a link's, a glossary's
# terms and definitions, code. MathML too, which can't hold a link.
LINK_IGNORE = {"a", "dt", "dd", "code"}


# What ends an address written as text that cookbook's pattern takes in:
# a closing quotation mark (*Astronomy 2e*'s observatories, each
# "“www.tmt.org”," in a table), the punctuation before it, and a mark
# that shows nothing (a left-to-right mark after a statistics lecture's
# address). Cookbook links them with the address, to a host that isn't
# one; they're the text after the link here.
TRAILING = set("\u201d\u2019\u00bb\u203a.,;:!?)]}"
               "\u200b\u200c\u200d\u200e\u200f\u2060\ufeff")


def _linked(text):
    """text cut into pieces, a link made of each address: [text, a,
    text, a, text], or None if it holds none."""
    if not text or not QUICK_CHECK.search(text):
        return None
    parts = LINK_PATTERN.split(text)
    if len(parts) == 1:
        return None
    pieces = [parts[0]]
    for i in range(1, len(parts), 2):
        part, after = parts[i], parts[i + 1]
        address = part
        while address and address[-1] in TRAILING:
            address = address[:-1]
        if EMAIL_RE.search(part):
            pieces += [E("a", {"href": f"mailto:{part}"}, part), after]
        elif URL_RE.fullmatch(address) and _valid_url(address):
            href = address if re.match(r"https?://", address, re.I) \
                else f"https://{address}"
            href = _escaped(href)
            pieces += [E("a", {"href": href}, address),
                       part[len(address):] + after]
        else:
            pieces[-1] += part + after
    return pieces if len(pieces) > 1 else None


# A host's last label that makes it an IPv4 address to the URL Standard:
# a number, decimal or hexadecimal.
IPV4_PART = re.compile(r"\d+|0[xX][0-9A-Fa-f]*")


def _valid_url(address):
    """Whether an address written as text is one a link can go to. A
    typo can make one that isn't ("https://doi.org:10.1016/...", a colon
    for a slash, read as a port; a backslash; no host, or one with an
    empty or impossible name, as "“http://.”" leaves "."; a host ending
    in a number that isn't an IPv4 address, "https://doi.10.1111/…", a
    period for "org/", as the nursing books have it eight times), which
    cookbook links anyway: an EPUB holding it fails epubcheck, and it
    goes nowhere. Such an address stays text here."""
    if "\\" in address:
        return False
    href = address if re.match(r"https?://", address, re.I) \
        else f"https://{address}"
    try:
        parts = urlsplit(href)
        parts.port
    except ValueError:
        return False
    host = parts.hostname or ""
    if host.startswith("["):
        return True
    labels = host.split(".")
    if len(labels) > 1 and labels[-1] == "":
        labels = labels[:-1]          # a name's final dot, "example.org."
    if IPV4_PART.fullmatch(labels[-1]):
        return len(labels) <= 4 and all(IPV4_PART.fullmatch(label)
                                        for label in labels)
    return bool(host) and all(re.fullmatch(r"[\w-]+", label)
                              and re.search(r"[^\W_]", label)
                              for label in labels)


def _put_links(parent, at, pieces):
    """pieces after the first, a link and the text after it in turn, into
    parent from position at."""
    last = None
    for piece in pieces[1:]:
        if isinstance(piece, str):
            last.tail = (last.tail or "") + piece
        else:
            parent.insert(at, piece)
            last = piece
            at += 1


def convert_textual_links(element):
    """Port of post_bake's convert_textual_links: each text in the
    element made links of its addresses, the element's own and its
    children's tails, and each child's in turn."""
    if not isinstance(element.tag, str) or element.tag in LINK_IGNORE \
            or element.tag.startswith("{"):
        return
    pieces = _linked(element.text)
    if pieces:
        element.text = pieces[0]
        _put_links(element, 0, pieces)
    for child in list(element):
        convert_textual_links(child)
        pieces = _linked(child.tail)
        if pieces:
            child.tail = pieces[0]
            _put_links(element, element.index(child) + 1, pieces)
