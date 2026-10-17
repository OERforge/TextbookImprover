"""
cnx.bake.injected -- the baking of exercises from OpenStax's exercise
bank (see ../exercises.py), and of the answer key their solutions go to:
ports of the openstax/cookbook directions of the same names and
versions.

An injected exercise's questions are numbered among a section's
exercises, each opening with its number and holding its stem and its
answer choices; a question's solution says which choice is right ("c.")
before the worked answer, and goes, in a book that has one, to the
answer key, under the title of the section it came from ("1.1 Knowledge
Check"), each number linking to the other.

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
import string

from ..cnxml import E
from .core import (EXERCISE, add_class, class_test, detach, has_class,
                   move_children, prepend, span, trash, wrap_children)
from . import directions as d

QUESTION = "div[@data-type='exercise-question']"
QUESTION_SOLUTION = "div[@data-type='question-solution']"
# Cookbook's solution selector: an exercise's or an injected question's.
ANY_SOLUTION = ("div[@data-type='solution' or "
                "@data-type='question-solution']")


def _first(element, xpath):
    found = element.xpath(xpath)
    return found[0] if found else None


def question_id(question):
    """Cookbook's InjectedQuestionElement#id: the question's id, given it
    first if it has none, "auto_{page}_{question}", as exercises.py
    writes it. OpenStax's own assembly leaves the question's number in
    data-id alone."""
    if not question.get("id"):
        page = next((a for a in question.iterancestors("div")
                     if a.get("data-type") == "page"), None)
        page_id = (page.get("id") or "") if page is not None else ""
        if page_id.startswith("page_"):
            page_id = page_id[len("page_"):]
        question.set("id", f"auto_{page_id}_{question.get('data-id')}")
    return question.get("id")


def add_injected_exercise_id(book):
    """Port of AddInjectedExerciseId.v1: every injected question in a
    page given its id."""
    for question in book.body.xpath(
            f".//div[@data-type='page']/descendant::{QUESTION}"):
        question_id(question)


def bake_all_numbered_exercise_types(book, within, exercise_options=None,
                                     question_options=None):
    """Port of BakeAllNumberedExerciseTypes.v1: the exercises and
    injected questions in the given elements, numbered together from 1
    in the order they stand, an unnumbered one skipped."""
    exercise_options = exercise_options or {}
    question_options = question_options or {}
    counter = 1
    # The set holds the elements, so lxml hands back the same objects
    # when a section inside another one is searched again.
    seen = set()
    for holder in within:
        for item in holder.xpath(f".//{EXERCISE} | .//{QUESTION}"):
            if item in seen:
                continue
            seen.add(item)
            if has_class(item, "unnumbered"):
                continue
            if item.get("data-type") == "exercise":
                d.bake_numbered_exercise(book, item, counter,
                                         **exercise_options)
            else:
                bake_injected_exercise_question(book, item, counter,
                                                **question_options)
            counter += 1


def _solutions(question, solution_type=None):
    test = f"[@data-solution-type='{solution_type}']" if solution_type \
        else ""
    return question.xpath(f".//div[@data-type='solution']{test} | "
                          f".//div[@data-type='question-solution']{test}")


def _suppress(question, suppress_summary=False, suppress_detailed=False,
              prioritize_solution=None):
    """The solutions an option drops: a summary, or a detailed one, or
    the other kind when one is preferred and there are two."""
    count = len(_solutions(question))
    if suppress_summary or (prioritize_solution == "detailed"
                            and count > 1):
        for solution in _solutions(question, "summary"):
            trash(solution)
    if suppress_detailed or (prioritize_solution == "summary"
                             and count > 1):
        for solution in _solutions(question, "detailed"):
            trash(solution)


def bake_injected_exercise(book, exercise, alphabetical_multiparts=False,
                           list_type=None, add_brackets=False,
                           suppress_summary=False, suppress_detailed=False,
                           prioritize_solution=None):
    """Port of BakeInjectedExercise.v1: the count of its questions
    recorded, and its context ("Refer to Figure 3.2") moved into its
    question when it has one. With alphabetical_multiparts, an exercise
    with a stimulus and several questions is one question whose parts
    are lettered (a., b.), their solutions gathered into one."""
    questions = exercise.xpath(f".//{QUESTION}")
    count = len(questions)
    stimulus = _first(exercise, ".//div[@data-type='exercise-stimulus']")
    if alphabetical_multiparts and stimulus is not None and questions:
        count = 1
        letters = (string.ascii_uppercase if list_type == "upper-alpha"
                   else string.ascii_lowercase)
        wrapper_id = f"{question_id(questions[0])}-wrapper"
        parts, gathered = [], []
        for index, question in enumerate(questions):
            qid = question_id(question)
            question.set("data-type", "alphabetical-question-multipart")
            letter = (f"({letters[index]})" if add_brackets
                      else f"{letters[index]}.")
            container = E("div", {"class": "os-problem-container"})
            if _solutions(question):
                mark = E("a", {"class": "problem-letter",
                               "href": f"#{qid}-solution"}, letter)
            else:
                mark = span("problem-letter", letter)
            container.append(mark)
            container.append(span("os-divider", " "))
            for part in (".//div[@data-type='question-stimulus']",
                         ".//div[@data-type='question-stem']"):
                found = _first(question, part)
                if found is not None:
                    container.append(detach(found))
            prepend(question, container)
            parts.append(detach(question))
            gathered.extend(bake_injected_exercise_solution(
                book, question, qid, letter, letter_part=True,
                suppress_summary=suppress_summary,
                suppress_detailed=suppress_detailed,
                prioritize_solution=prioritize_solution))
        stimulus.set("data-type", "question-stimulus")
        wrapper = E("div", {"data-type": "exercise-question",
                            "id": wrapper_id})
        wrapper.append(detach(stimulus))
        for part in parts:
            wrapper.append(part)
        if gathered:
            block = E("div", {"data-type": "question-solution",
                              "id": f"{wrapper_id}-solution"})
            for solution in gathered:
                block.append(solution)
            wrapper.append(block)
        prepend(exercise, wrapper)
    exercise.set("data-question-count", str(count))
    exercise.set("data-is-multipart", "True" if count > 1 else "False")
    context = _first(exercise, ".//div[@data-type='exercise-context']")
    if context is None:
        return
    link = _first(context, ".//a")
    for child in list(context):
        context.remove(child)
    context.text = book.t("context_lead_text")
    if link is not None:
        link.tail = None
        context.append(link)
    if count == 1:
        question = _first(exercise, f".//{QUESTION}")
        if question is not None:
            prepend(question, detach(context))


def _prefixed_number(book, number, href=None):
    """The number with "Problem" before it, "Problem 1-1" (cookbook's
    problem_with_prefix), a link when there's somewhere to go."""
    holder = E("a", {"class": "os-prefix", "href": href}) if href \
        else E("div", {"class": "os-prefix"})
    label = span("os-label", book.t("problem"))
    # The line break between the two in cookbook's template.
    label.tail = " "
    holder.append(label)
    holder.append(span("os-number", str(number)))
    return holder


def bake_injected_exercise_question(book, question, number,
                                    only_number_solution=False,
                                    add_dot=False, problem_with_prefix=False,
                                    suppress_summary=False,
                                    suppress_detailed=False,
                                    answer_letter_upper=False,
                                    answer_letter_only=False,
                                    prioritize_solution=None):
    """Port of BakeInjectedExerciseQuestion.v1: the number first ("1.",
    or "Problem 1-1" with problem_with_prefix), linking to the solution
    if there is one, then the question's context, stimulus, stem (or
    lettered parts), and choices; the letters of the right choices
    (capitals with answer_letter_upper) put before the solution; the
    choices' feedback dropped."""
    qid = question_id(question)
    page = book.page_of(question)
    in_appendix = page is not None and has_class(page, "appendix")
    in_preface = page is not None and has_class(page, "preface")
    multipart = bool(question.xpath(
        ".//div[@data-type='alphabetical-question-multipart']"))
    if not only_number_solution:
        if in_appendix or in_preface:
            pages = book.pages()
            prefix = pages.index(page) + 1 if page in pages else ""
        else:
            chapter = book.chapter_of(question)
            prefix = book.chapter_number(chapter) if chapter is not None \
                else ""
        book.target_label(question, f"{book.t('exercise')} {prefix}.{number}")
    answers = _first(question, ".//ol[@data-type='question-answers']")
    letters = []
    if answers is not None:
        if answers.get("type") != "a":
            raise ValueError("unsupported list type for multiple-choice "
                             "answers: " + str(answers.get("type")))
        choices = answers.xpath(".//li[@data-type='question-answer']")
        alphabet = (string.ascii_uppercase if answer_letter_upper
                    else string.ascii_lowercase)
        letters = [alphabet[i] for i, li in enumerate(choices)
                   if li.get("data-correctness") == "1.0"]
    if suppress_summary or (letters and answer_letter_only):
        for solution in _solutions(question, "summary"):
            trash(solution)
    if suppress_detailed or (letters and answer_letter_only):
        for solution in _solutions(question, "detailed"):
            trash(solution)
    if letters:
        shown = span("answer-letters",
                     ", ".join(letters) + ("." if add_dot else ""))
        solution = _first(question, f".//{QUESTION_SOLUTION}")
        if solution is None:
            solution = E("div", {"data-type": "question-solution"})
            solution.append(shown)
            question.append(solution)
        else:
            prepend(solution, shown)
    solution = _first(question, f".//{QUESTION_SOLUTION}")
    context = _first(question, ".//div[@data-type='exercise-context']")
    container = E("div", {"class": "os-problem-container"})
    if context is not None:
        container.append(detach(context))
        container.append(span("os-divider", ". "))
    found = _first(question, "./div[@data-type='question-stimulus'] | "
                             ".//div[@data-type='question-stimulus']")
    if found is not None:
        container.append(detach(found))
    if multipart:
        for part in question.xpath(
                ".//div[@data-type='alphabetical-question-multipart']"):
            container.append(detach(part))
    else:
        found = _first(question, ".//div[@data-type='question-stem']")
        if found is not None:
            container.append(detach(found))
    answers = _first(question, ".//ol[@data-type='question-answers']")
    if answers is not None:
        container.append(detach(answers))
    prepend(question, container)
    if not only_number_solution and problem_with_prefix:
        prepend(question, _prefixed_number(
            book, number, f"#{qid}-solution" if solution is not None
            else None))
    elif not only_number_solution:
        if solution is not None:
            number_el = E("a", {"class": "os-number",
                                "href": f"#{qid}-solution"}, str(number))
        else:
            number_el = span("os-number", str(number))
        divider = span("os-divider", ". ")
        prepend(question, divider)
        prepend(question, number_el)
    bake_injected_exercise_solution(book, question, qid, number,
                                    problem_with_prefix=problem_with_prefix,
                                    suppress_summary=suppress_summary,
                                    suppress_detailed=suppress_detailed,
                                    prioritize_solution=prioritize_solution)
    for feedback in question.xpath(".//div[@data-type='answer-feedback']"):
        trash(feedback)


def bake_injected_exercise_solution(book, question, qid, number,
                                    letter_part=False,
                                    problem_with_prefix=False,
                                    suppress_summary=False,
                                    suppress_detailed=False,
                                    prioritize_solution=None):
    """Port of BakeInjectedExerciseSolution.v1: the solution (or the
    solutions, joined) numbered, linking back to the question. For a
    lettered part (cookbook's solutions_clipboard), it's lettered and
    taken out, to be gathered with its siblings'; returned in a list."""
    _suppress(question, suppress_summary, suppress_detailed,
              prioritize_solution)
    solutions = _solutions(question)
    if not solutions:
        return []
    if not letter_part:
        add_class(question, "os-hasSolution")

    def numbered(holder):
        if problem_with_prefix:
            holder.append(_prefixed_number(book, number, f"#{qid}"))
        elif letter_part:
            holder.append(E("a", {"class": "problem-letter",
                                  "href": f"#{qid}"}, str(number)))
            holder.append(span("os-divider", " "))
        else:
            holder.append(E("a", {"class": "os-number", "href": f"#{qid}"},
                            str(number)))
            holder.append(span("os-divider", ". "))

    if len(solutions) == 1:
        solution = solutions[0]
        solution.set("id", f"{qid}-solution")
        container = E("div", {"class": "os-solution-container"})
        move_children(solution, container)
        numbered(solution)
        solution.append(container)
    else:
        container = E("div", {"class": "os-solution-container"})
        for part in solutions:
            partial = E("div", {"class": "os-partial-solution"})
            move_children(part, partial)
            container.append(partial)
            trash(part)
        solution = E("div", {"data-type": "question-solution",
                             "id": f"{qid}-solution"})
        numbered(solution)
        solution.append(container)
        question.append(solution)
    if letter_part:
        solution.set("data-type", "solution-part")
        return [detach(solution)]
    return [solution]


def move_solutions_from_exercise_section(book, within, append_to,
                                         section_class, title_number=None,
                                         add_title=True, in_appendix=False):
    """Port of MoveSolutionsFromExerciseSection.v1: the solutions in the
    page's sections of the class, to the answer key's page, under a
    title naming the section ("1.1 Knowledge Check")."""
    if within.tag == "section":
        sections = [within]
    else:
        sections = within.xpath(f".//section[{class_test(section_class)}]")
    solutions = []
    for section in sections:
        solutions.extend(section.xpath(f".//{ANY_SOLUTION}"))
    if not solutions:
        return None
    moved = [detach(s) for s in solutions]
    if not add_title:
        for solution in moved:
            append_to.append(solution)
        return append_to
    if title_number:
        title_text = book.t(f"eoc.{section_class}", number=title_number)
    elif in_appendix:
        title_text = book.t(f"appendix_sections.{section_class}")
    else:
        title_text = book.t(f"eoc.{section_class}")
    area = E("div", {"class": "os-solution-area"})
    title = E("h3", {"data-type": "title"})
    title.append(span("os-title-label", title_text))
    area.append(title)
    for solution in moved:
        area.append(solution)
    append_to.append(area)
    return area


def move_solutions_from_numbered_note(book, chapter, append_to, note_class):
    """Port of MoveSolutionsFromNumberedNote.v1: the solutions in the
    chapter's notes of the class ("Unfolding Case Study"), to the answer
    key's page, under the notes' title."""
    solutions = [s for note in book.notes(chapter, note_class)
                 for s in note.xpath(f".//{ANY_SOLUTION}")]
    if not solutions:
        return None
    area = E("div", {"class": "os-solution-area"})
    title = E("h3", {"data-type": "title"})
    title.append(span("os-title-label", book.t(f"notes.{note_class}")))
    area.append(title)
    for solution in solutions:
        area.append(detach(solution))
    append_to.append(area)
    return area


def move_solutions_from_numbered_note_v2(book, chapter, append_to,
                                         note_class):
    """Port of MoveSolutionsFromNumberedNote.v2: when any of the
    chapter's notes of the class has a solution, a title for the class
    ("Your Turn") and then, note by note, an area under the note's
    number in its chapter ("1.3") holding its solutions, if any."""
    notes = book.notes(chapter, note_class)
    if not any(note.xpath(f".//{ANY_SOLUTION}") for note in notes):
        return None
    title = E("h3", {"data-type": "title"})
    title.append(span("os-title-label", book.t(f"notes.{note_class}")))
    append_to.append(title)
    n = book.chapter_number(chapter)
    for i, note in enumerate(notes, 1):
        area = E("div", {"class": "os-solution-area"})
        area.append(span("os-note-number", f"{n}.{i}"))
        for solution in note.xpath(f".//{ANY_SOLUTION}"):
            area.append(detach(solution))
        append_to.append(area)
    return append_to


def move_solutions_from_autotitled_note(book, page, append_to, note_class,
                                        title=None):
    """Port of MoveSolutionsFromAutotitledNote.v1: the solutions in the
    page's (or chapter's) notes of the class, to the answer key's page,
    under the title given, the words of an element (the page's numbered
    title) or a string ("Checkpoint"), or bare."""
    solutions = [s for note in book.notes(page, note_class)
                 for s in note.xpath(f".//{ANY_SOLUTION}")]
    if not solutions:
        return None
    moved = [detach(s) for s in solutions]
    if title is None:
        for solution in moved:
            append_to.append(solution)
        return append_to
    area = E("div", {"class": "os-solution-area"})
    heading = E("h3", {"data-type": "title"})
    label = span("os-title-label")
    if isinstance(title, str):
        label.text = title
    else:
        move_children(copy.deepcopy(title), label)
    heading.append(label)
    area.append(heading)
    for solution in moved:
        area.append(solution)
    append_to.append(area)
    return area


def move_solutions_from_autotitled_note_v2(book, chapter, append_to,
                                           note_class):
    """Port of MoveSolutionsFromAutotitledNote.v2: an area of the answer
    key's page titled for the class ("Try It"), even when it holds
    nothing, and in it, page by page, the solutions of the exercises in
    the page's notes of the class, under the page's numbered title."""
    area = E("div", {"class": "os-module-reset-solution-area "
                              f"os-{note_class}-solution-area"})
    title = E("h3", {"data-type": "title"})
    title.append(span("os-title-label", book.t(f"notes.{note_class}")))
    area.append(title)
    append_to.append(area)
    for page in book.pages(chapter):
        solutions = [s for note in book.notes(page, note_class)
                     for exercise in note.xpath(f".//{EXERCISE}")
                     for s in exercise.xpath(f".//{ANY_SOLUTION}")]
        if not solutions:
            continue
        moved = [detach(s) for s in solutions]
        solutions_area = E("div", {"class": "os-solution-area"})
        solutions_area.append(d.eoc_section_title_link(book, page,
                                                       wrapper="div"))
        for solution in moved:
            solutions_area.append(solution)
        area.append(solutions_area)
    return area


def bake_note_exercise_v2(book, note):
    """Port of BakeNoteExercise.v2: a note's exercises, each numbered in
    the note unless it's unnumbered, and each solution labeled."""
    count = 0
    for exercise in note.xpath(f".//{EXERCISE}"):
        problem = _first(exercise, "./div[@data-type='problem']")
        if problem is not None:
            wrap_children(problem, E("div", {"class": "os-problem-container"}))
            if not has_class(exercise, "unnumbered"):
                count += 1
                prepend(problem, span("os-number", str(count)))
                prepend(problem, span("os-title-label",
                                      book.t("exercises.exercise") + " "))
        solution = _first(exercise, "./div[@data-type='solution']")
        if solution is not None:
            wrap_children(solution,
                          E("div", {"class": "os-solution-container"}))
            prepend(solution, span("os-title-label",
                                   book.t("exercises.solution")))
