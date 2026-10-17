"""
cnx.bake.recipes -- a book's baking, one function per OpenStax style,
each a port of that style's recipe in openstax/cookbook
(lib/recipes/<style>/recipe.rb), step for step, so the two can be read
side by side and a change to theirs found in ours.

A style with no recipe here, which is every book of the Connexions
archive, gets generic(): what any book needs to read well and nothing
that rearranges it. Its figures, tables, and numbered equations are
numbered in their page, as Connexions numbered them, and its notes keep
their own titles.

Each recipe records the cookbook commit its port was read from, so a
later change to theirs can be found by comparing.

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

import string

from . import directions as d
from . import injected as inj
from ..cnxml import E
from .core import (Book, add_class, class_test, figure_to_number, has_class,
                   prepend, remove_class, span, text_of, wrap_children)
from .strings import for_style

# openstax/cookbook as read for these ports.
COOKBOOK_COMMIT = "f5b488f0ad2d48bb1b49b990dd249e9869d0b256"


def _numbered_in_chapter(book, chapter):
    """Tables and figures of a chapter, numbered in document order after
    the end-of-chapter pages have been made, as the recipes do it."""
    n = book.chapter_number(chapter)
    tables = [t for t in book.tables(chapter)
              if not has_class(t, "unnumbered")]
    for i, table in enumerate(tables, 1):
        d.bake_numbered_table(book, table, f"{n}.{i}")
    figures = [f for f in book.figures(chapter) if figure_to_number(f)]
    for i, figure in enumerate(figures, 1):
        d.bake_figure(book, figure, f"{n}.{i}")


def _appendices(book):
    """The recipes' loop over book.pages('$.appendix'): a letter each,
    and its figures, tables, and exercises numbered A1, A2."""
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        d.bake_appendix(book, page, letter)
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
        exercises = page.xpath(
            ".//section/descendant::div[@data-type='exercise']")
        for j, exercise in enumerate(exercises, 1):
            d.bake_numbered_exercise(book, exercise, f"{letter}{j}")


def economics(book):
    """lib/recipes/economics/recipe.rb."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_unnumbered_figure(book)
    d.bake_preface(book, title_element="h1")
    d.bake_chapter_introductions(book)
    d.bake_chapter_title(book)
    d.bake_unclassified_notes(book)
    # BakeIframes: left to TextbookImprover, which keeps an iframe in HTML
    # and makes it a link in an EPUB.
    d.bake_autotitled_notes(book, ["linkup", "bringhome", "clearup",
                                   "workout"])
    answer_key = d.book_answer_key_container(book)

    eoc = ["summary", "self-check-questions", "review-questions",
           "critical-thinking", "problems"]
    for chapter in book.chapters():
        d.bake_learning_objectives(book, chapter)
        d.bake_chapter_glossary(book, chapter)
        d.bake_chapter_summary(book, chapter)
        # Numbered in the order the sections are searched for: every
        # summary section, then every self-check section, and so on,
        # which is the order they'll stand in at the chapter's end.
        number = 0
        for klass in eoc:
            for section in chapter.xpath(f".//section[{class_test(klass)}]"):
                for exercise in section.xpath(".//div[@data-type='exercise']"):
                    number += 1
                    d.bake_numbered_exercise(book, exercise, number)
        for klass in eoc:
            d.move_exercises_to_eoc(book, chapter, klass)
        inner = d.answer_key_inner_container(book, chapter, answer_key)
        d.default_strategy_for_answer_key_solutions(
            book, chapter, ["self-check-questions", "problems",
                            "ap-test-prep"], inner)
        _numbered_in_chapter(book, chapter)
        d.bake_non_introduction_pages(book, chapter)
    _appendices(book)
    d.bake_unnumbered_tables(book)
    d.bake_references_v2(book)
    d.bake_equations(book)
    d.bake_index(book)
    d.bake_footnotes(book)
    d.bake_link_placeholders(book)


def statistics(book):
    """lib/recipes/statistics/recipe.rb, whose selectors take a reference
    to be any element of class references (bake_chapter_references
    reads them so)."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_unnumbered_figure(book)
    d.bake_preface(book, title_element="h1")
    # BakeInlineLists: cnxml.py separates every inline list's items as it
    # writes them, "; " unless the list says otherwise.
    d.bake_unclassified_notes(book)
    d.bake_chapter_title(book)
    d.bake_chapter_introductions(book)

    exercise_classes = ["practice", "bring-together-exercises",
                        "free-response", "bring-together-homework"]
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_learning_objectives(book, chapter)
        d.bake_chapter_glossary(book, chapter)
        d.bake_chapter_summary(book, chapter)
        d.move_custom_section_to_eoc(book, chapter, "formula-review",
                                     "formula-review",
                                     each=d.titled_from_page(book))
        d.move_custom_section_to_eoc(book, chapter, "practice", "practice",
                                     each=d.titled_from_page(book, "h3"))
        d.move_custom_section_to_eoc(book, chapter,
                                     "bring-together-exercises",
                                     "bring-together-exercises",
                                     each=d.remove_section_title)
        d.bake_free_response(book, chapter)
        d.move_custom_section_to_eoc(book, chapter,
                                     "bring-together-homework",
                                     "bring-together-homework",
                                     each=d.remove_section_title)
        d.bake_chapter_references(book, chapter)
        # Numbered across the four kinds of section in the order they
        # now stand in at the chapter's end, which is the order cookbook's
        # search returns them in.
        selector = " or ".join(class_test(c) for c in exercise_classes)
        number = 0
        for section in chapter.xpath(f".//section[{selector}]"):
            for exercise in section.xpath(".//div[@data-type='exercise']"):
                number += 1
                d.bake_numbered_exercise(book, exercise, number)
        d.bake_chapter_solutions(book, chapter, exercise_classes)
        examples = chapter.xpath(".//div[@data-type='example']")
        for i, example in enumerate(examples, 1):
            d.bake_example(book, example, f"{n}.{i}", title_tag="h3",
                           add_problem_title=True)
    d.bake_numbered_notes_v3(book, ["try"], suppress_solution=True)
    stats_labs = d.bake_numbered_notes_v4(book, ["statistics.lab"],
                                          within="stats-labs")
    d.bake_autotitled_notes(book, ["lab", "calculator"],
                            except_ids=stats_labs)
    d.bake_autotitled_notes(book, ["collab"], bake_subtitle=False)
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
        d.move_custom_section_to_eoc(book, chapter, "stats-labs",
                                     "stats-labs")
        d.move_custom_section_to_eoc(book, chapter, "excel-labs",
                                     "excel-labs")
        d.bake_non_introduction_pages(book, chapter)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
        d.bake_appendix(book, page, letter)
    # BakeFirstElements and BakeMathInParagraph: classes for OpenStax's
    # stylesheet.
    d.bake_unnumbered_tables(book)
    d.bake_equations(book)
    d.bake_index(book)
    # BakeCompositePages: ids for OpenStax's reader.
    d.bake_footnotes(book)
    d.bake_link_placeholders(book)


def microbiology(book):
    """lib/recipes/microbiology/recipe.rb. A chapter's questions are in a
    Review Questions group at its end, by kind, numbered through the
    chapter, their answers in the answer key."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_unnumbered_figure(book)
    d.bake_preface(book, title_element="h1")
    # BakeChapterIntroductions.v1 (its outline first).
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    d.bake_chapter_title(book)
    d.bake_autotitled_notes(book, ["clinical-focus",
                                   "check-your-understanding",
                                   "micro-connection", "link-to-learning",
                                   "eye-on-ethics", "case-in-point",
                                   "disease-profile"])
    answer_key = d.book_answer_key_container(book, solutions_plural=False)
    eoc = ["multiple-choice", "true-false", "matching", "fill-in-the-blank",
           "short-answer", "critical-thinking"]
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_learning_objectives(book, chapter)
        d.bake_non_introduction_pages(book, chapter)
        d.bake_chapter_summary(book, chapter)
        wrapper = d.chapter_review_container(book, chapter,
                                             "review-questions")
        for key in eoc:
            d.move_exercises_to_eoc(book, chapter, key, append_to=wrapper)
        exercises = chapter.xpath(
            ".//section[" + " or ".join(class_test(k) for k in eoc) + "]"
            "/descendant::div[@data-type='exercise']")
        for i, exercise in enumerate(exercises, 1):
            d.bake_numbered_exercise(book, exercise, i)
        inner = d.answer_key_inner_container(book, chapter, answer_key,
                                             solutions_plural=False)
        d.default_strategy_for_answer_key_solutions(book, chapter, eoc,
                                                    inner)
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
        d.bake_appendix(book, page, letter)
    d.bake_unnumbered_tables(book)
    d.bake_equations(book)
    d.bake_index(book)
    d.bake_footnotes(book)
    d.bake_link_placeholders(book)


def marketing(book):
    """lib/recipes/marketing/recipe.rb, whose selectors take a reference
    to be a section of class references. Its knowledge checks are
    exercises from OpenStax's exercise bank (see ../exercises.py)."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_preface(book)
    for page in book.pages(cls="preface"):
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, str(i))
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True,
                                 introduction_order="v3")
    d.bake_chapter_title(book)
    d.bake_unnumbered_figure(book)
    d.bake_unclassified_notes(book)
    inj.add_injected_exercise_id(book)
    answer_key = d.book_answer_key_container(book, solutions_plural=False)
    eoc = ["marketing-discussion", "critical-thinking", "building-brand",
           "marketers-do", "marketing-plan", "company-case"]
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_non_introduction_pages(book, chapter)
        d.bake_learning_objectives_v2(book, chapter, add_title=False,
                                      li_numbering="count_only_li")
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
        for page in book.pages(chapter):
            inj.bake_all_numbered_exercise_types(
                book, page.xpath(f".//section[{class_test('knowledge-check')}]"),
                question_options={"add_dot": True})
        d.move_custom_section_to_eoc(book, chapter, "chapter-summary",
                                     "chapter-summary",
                                     each=d.remove_section_title)
        d.bake_chapter_glossary(book, chapter)
        for key in eoc:
            sections = []
            for page in book.pages(chapter):
                sections.extend(page.xpath(f".//section[{class_test(key)}]"))
            inj.bake_all_numbered_exercise_types(book, sections)
            d.move_custom_section_to_eoc(
                book, chapter, key, key,
                each=lambda section: d.remove_section_title(section, "h3"))
        d.bake_chapter_references_v2(book, chapter)
        inner = d.answer_key_inner_container(book, chapter, answer_key,
                                             solutions_plural=False)
        for i, page in enumerate(book.non_introduction_pages(chapter), 1):
            inj.move_solutions_from_exercise_section(
                book, page, inner, "knowledge-check", title_number=f"{n}.{i}")
    d.bake_autotitled_notes(book, ["marketing-practice",
                                   "companies-conscience",
                                   "link-to-learning", "careers-marketing"])
    d.bake_autotitled_notes(book, ["marketing-dashboard"])
    for note in book.notes(cls="marketing-dashboard"):
        inj.bake_note_exercise_v2(book, note)
    d.bake_custom_titled_notes(book, ["unit-opener", "word-document"])
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        d.bake_appendix(book, page, letter)
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
        d.bake_learning_objectives_v2(book, page, add_title=False,
                                      li_numbering="count_only_li_in_appendix")
        for selector in ("references", "chapter-summary", "knowledge-check"):
            for section in page.xpath(f".//section[{class_test(selector)}]"):
                d.bake_appendix_feature_titles(book, section, selector)
        checks = page.xpath(f".//section[{class_test('knowledge-check')}]")
        for check in checks:
            for exercise in check.xpath(
                    ".//div[@data-type='injected-exercise']"):
                inj.bake_injected_exercise(book, exercise)
        questions = [q for check in checks for q in check.xpath(
            ".//div[@data-type='exercise-question']")]
        for j, question in enumerate(questions, 1):
            inj.bake_injected_exercise_question(book, question,
                                                f"{letter}{j}")
        inner = d.answer_key_inner_container(book, page, answer_key,
                                             solutions_plural=False,
                                             in_appendix=True)
        inj.move_solutions_from_exercise_section(
            book, page, inner, "knowledge-check", in_appendix=True)
    d.bake_equations(book)
    # BakeIframes: left to TextbookImprover, which keeps an iframe in HTML
    # and makes it a link in an EPUB.
    d.bake_footnotes(book)
    d.bake_index(book)
    # BakeCompositePages and BakeCompositeChapters: ids for OpenStax's
    # reader.
    d.bake_unit_title(book)
    d.bake_unit_page_title(book)
    d.bake_link_placeholders(book)


def sociology(book):
    """lib/recipes/sociology/recipe.rb, whose selectors take a page's
    summary to be its section of class section-summary and a reference a
    section of class references. An edition "3e" gets the answer key."""
    third = book.title_text().endswith("3e")
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_unnumbered_figure(book)
    d.bake_preface(book)
    for page in book.pages(cls="preface"):
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, str(i))
    d.bake_chapter_title(book)
    # BakeChapterIntroductions.v1: the chapter's outline first.
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    for chapter in book.chapters():
        d.bake_chapter_glossary(book, chapter)
        d.bake_chapter_summary(book, chapter, klass="section-summary")
        for klass in ("section-quiz", "short-answer"):
            # MoveExercisesToEOC.v3
            d.move_custom_section_to_eoc(book, chapter, klass, klass,
                                         each=d.titled_from_page(book))
        # BakeFurtherResearch.v1
        d.move_custom_section_to_eoc(book, chapter, "further-research",
                                     "further-research",
                                     each=d.titled_from_page(book))
        for composite in chapter.xpath(
                "./div[@data-type='composite-page']"):
            exercises = composite.xpath(
                f".//section[{class_test('short-answer')} or "
                f"{class_test('section-quiz')}]/descendant::div[@data-type='exercise']")
            for i, exercise in enumerate(exercises, 1):
                d.bake_numbered_exercise(book, exercise, i,
                                         suppress_solution="even",
                                         note_suppressed_solutions=True)
        d.bake_chapter_references(book, chapter, section_only=True)
    if third:
        answer_key = d.book_answer_key_container(book,
                                                 solutions_plural=False)
        for chapter in book.chapters():
            inner = d.answer_key_inner_container(book, chapter, answer_key,
                                                 solutions_plural=False)
            d.default_strategy_for_answer_key_solutions(
                book, chapter, ["section-quiz"], inner)
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_learning_objectives(book, chapter)
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
        d.bake_non_introduction_pages(book, chapter)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
    d.bake_autotitled_notes(book, ["sociological-research",
                                   "sociology-real-world",
                                   "sociology-big-picture",
                                   "sociology-policy-debate"])
    d.bake_stepwise(book)
    d.bake_unnumbered_tables(book)
    d.bake_index(book)
    d.bake_footnotes(book)
    d.bake_link_placeholders(book)


def american_government(book):
    """lib/recipes/american-government/recipe.rb. A chapter's review and
    critical thinking questions are numbered through it together, the
    review questions' answers in the answer key; its suggested readings
    end it, "Suggestions for Further Study"."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_preface(book)
    d.bake_unit_title(book)
    d.bake_chapter_title(book)
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True,
                                 introduction_order="v2")
    d.bake_unclassified_notes(book)
    d.bake_unnumbered_figure(book)
    answer_key = d.book_answer_key_container(book)
    eoc = ["review-questions", "critical-thinking"]
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_chapter_glossary(book, chapter)
        d.bake_chapter_summary(book, chapter)
        d.bake_non_introduction_pages(book, chapter)
        exercises = chapter.xpath(
            f".//section[{class_test(eoc[0])} or {class_test(eoc[1])}]"
            "/descendant::div[@data-type='exercise']")
        for i, exercise in enumerate(exercises, 1):
            d.bake_numbered_exercise(book, exercise, i)
        for key in eoc:
            d.move_exercises_to_eoc(book, chapter, key)
        inner = d.answer_key_inner_container(book, chapter, answer_key)
        d.default_strategy_for_answer_key_solutions(
            book, chapter, ["review-questions"], inner)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
        for j, example in enumerate(page.xpath(
                ".//div[@data-type='example']"), 1):
            d.bake_example(book, example, f"{letter}{j}", title_tag="div")
        d.bake_appendix(book, page, letter)
    d.bake_autotitled_notes(book, ["link-to-learning", "middle-ground",
                                   "milestone", "get-connected",
                                   "insider-perspective"])
    # BakeScreenreaderSpans: words for screen readers alone, not written.
    d.bake_suggested_reading(book)
    d.bake_references_v1(book)
    d.bake_index(book)
    d.bake_link_placeholders(book)


def biology(book):
    """lib/recipes/biology/recipe.rb (*Biology 2e*, *Concepts of
    Biology*). A chapter's questions follow its summary, by kind, numbered
    through the chapter, without solutions."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_unnumbered_figure(book)
    d.bake_preface(book)
    d.bake_unit_title(book)
    # BakeChapterIntroductions.v1 (its outline first).
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    d.bake_chapter_title(book)
    d.bake_autotitled_notes(book, ["visual-connection", "interactive",
                                   "evolution", "career", "scientific",
                                   "everyday"])
    eoc = ["visual-exercise", "multiple-choice", "critical-thinking"]
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_learning_objectives(book, chapter)
        d.bake_non_introduction_pages(book, chapter)
        d.bake_chapter_glossary(book, chapter)
        d.bake_chapter_summary(book, chapter)
        for key in eoc:
            d.move_exercises_to_eoc(book, chapter, key)
        exercises = chapter.xpath(
            ".//section[" + " or ".join(class_test(k) for k in eoc) + "]"
            "/descendant::div[@data-type='exercise']")
        for i, exercise in enumerate(exercises, 1):
            d.bake_numbered_exercise(book, exercise, i,
                                     suppress_solution=True)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
    d.bake_unnumbered_tables(book)
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        d.bake_appendix(book, page, letter)
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
    # BakeScreenreaderSpans: words for screen readers alone, not written.
    d.bake_equations(book)
    d.bake_index(book)
    d.bake_footnotes(book)
    d.bake_link_placeholders(book)


def _wrap_problem_children(problem):
    """Kitchen's wrap_children(class: 'os-problem-container') on a
    problem: everything in it in one div."""
    wrap_children(problem, E("div", {"class": "os-problem-container"}))


def _unnumbered_exercises_contained(book):
    """An unnumbered exercise's problem in its container, as numbered
    ones get theirs (Kitchen's book.exercises('$.unnumbered'))."""
    for exercise in book.body.xpath(".//div[@data-type='exercise']"):
        if has_class(exercise, "unnumbered"):
            problems = exercise.xpath(".//div[@data-type='problem']")
            if problems:
                _wrap_problem_children(problems[0])


def _note_questions_contained(book):
    """A bank question in a note treated as an unnumbered question: its
    content in a container, its required context taken out (Kitchen's
    book.notes.injected_questions)."""
    for note in book.notes():
        for question in note.xpath(
                ".//div[@data-type='exercise-question']"):
            _wrap_problem_children(question)
            for context in question.xpath(
                    ".//div[@data-type='exercise-context']"):
                d.detach(context)


def ap_biology(book):
    """lib/recipes/ap-biology/recipe.rb (*Biology for AP Courses*). A
    chapter's questions follow its summary, by kind, the exercises and the
    bank's questions numbered together, without solutions; a bank question
    in a note is unnumbered."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_unnumbered_figure(book)
    inj.add_injected_exercise_id(book)
    for exercise in book.body.xpath(".//div[@data-type='injected-exercise']"):
        inj.bake_injected_exercise(book, exercise)
    d.bake_preface(book)
    d.bake_unit_title(book)
    d.bake_chapter_title(book)
    # BakeChapterIntroductions.v1 (its outline first).
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    d.bake_autotitled_notes(book, ["visual-connection",
                                   "ost-sciprac-scithink"],
                            bake_subtitle=False)
    d.bake_autotitled_notes(book, ["interactive", "ost-sciprac-activity",
                                   "ap-science-practices", "os-teacher",
                                   "evolution", "ap-everyday", "career",
                                   "everyday", "experiment", "scientific"])
    d.bake_unclassified_notes(book)
    _unnumbered_exercises_contained(book)
    _note_questions_contained(book)
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        for abstract in chapter.xpath(".//div[@data-type='abstract']"):
            d.trash(abstract)
        d.bake_non_introduction_pages(book, chapter)
        d.bake_chapter_glossary(book, chapter)
        d.bake_chapter_summary(book, chapter)
        for key in ("review", "critical-thinking", "ap-test-prep",
                    "science-practice"):
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         each=d.remove_section_title)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
        inj.bake_all_numbered_exercise_types(
            book, chapter.xpath(f".//div[{class_test('os-eoc')}]"),
            exercise_options={"suppress_solution": True})
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        d.bake_appendix(book, page, letter)
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
    d.bake_unnumbered_tables(book)
    d.bake_footnotes(book)
    d.bake_index(book)
    d.bake_link_placeholders(book)


def ap_physics(book):
    """lib/recipes/ap-physics/recipe.rb (*College Physics for AP Courses
    2e*, whose style is ap-physics-2e, the same recipe). A chapter's
    review is its summaries, questions, problems, and test prep, each
    page's under the page's title, each kind numbered through the chapter;
    the problems' and test prep's solutions are in the answer key."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_unnumbered_figure(book)
    d.bake_preface(book)
    d.bake_chapter_title(book)
    # BakeChapterIntroductions.v1 (its outline first).
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    d.bake_unclassified_notes(book)
    d.bake_autotitled_notes(book, ["interactive"])
    answer_key = d.book_answer_key_container(book)
    for exercise in book.body.xpath(
            ".//div[@data-type='exercise']"
            "[@data-element-type='check-understanding']"):
        d.bake_autotitled_exercise_v3(book, exercise,
                                      book.t("check-understanding"))
    eoc = ("section-summary", "conceptual-questions", "problems-exercises",
           "ap-test-prep")
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_non_introduction_pages(book, chapter)
        d.bake_chapter_glossary(book, chapter)
        for key in eoc:
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         each=d.titled_from_page(book))
        for key in eoc[1:]:
            for i, exercise in enumerate(chapter.xpath(
                    f".//section[{class_test(key)}]"
                    "/descendant::div[@data-type='exercise']"), 1):
                d.bake_numbered_exercise(book, exercise, i)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
        for i, example in enumerate(chapter.xpath(
                ".//div[@data-type='example']"), 1):
            d.bake_example(book, example, f"{n}.{i}", title_tag="h3")
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
        for j, example in enumerate(page.xpath(
                ".//div[@data-type='example']"), 1):
            d.bake_example(book, example, f"{letter}{j}", title_tag="div")
        d.bake_appendix(book, page, letter)
    for chapter in book.chapters():
        inner = d.answer_key_inner_container(book, chapter, answer_key)
        for key in ("problems-exercises", "ap-test-prep"):
            inj.move_solutions_from_exercise_section(book, chapter, inner,
                                                     key)
    # BakeFirstElements: classes for OpenStax's stylesheet.
    for equation in book.body.xpath(
            ".//div[@data-type='composite-page']"
            "/descendant::div[@data-type='equation']"):
        add_class(equation, "unnumbered")
    d.bake_footnotes(book)
    d.bake_equations(book)
    d.bake_index(book)
    d.bake_link_placeholders(book)


def hs_physics(book):
    """lib/recipes/hs-physics/recipe.rb (*Physics*, for high school). A
    section's own questions stay at its end, numbered through the chapter
    with their solutions in place; the chapter's key equations, review,
    and test prep follow it, each page's under the page's title, the
    review and test prep numbered through the chapter together without
    solutions."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_unnumbered_figure(book)
    d.bake_preface(book)
    d.bake_chapter_title(book)
    # BakeChapterIntroductions.v1 (its outline first).
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    inj.add_injected_exercise_id(book)
    d.bake_autotitled_notes(book, [
        "os-teacher", "boundless-physics", "worked-example",
        "virtual-physics", "snap-lab", "links-to-physics",
        "tips-for-success", "teacher-demonstration", "watch-physics",
        "work-in-physics", "fun-in-physics", "misconception"])
    d.bake_autotitled_notes(book, ["learning-objectives"],
                            bake_subtitle=False)
    exercises = ".//div[@data-type='exercise']"
    for exercise in book.body.xpath(
            f"{exercises}[{class_test('grasp-check')}]"):
        d.bake_autotitled_exercise_v2(book, exercise, book.t("grasp-check"))
    d.bake_unclassified_notes(book)
    for note in book.notes(cls="worked-example"):
        for exercise in note.xpath(exercises):
            add_class(exercise, "unnumbered")
    for exercise in book.body.xpath(
            f"{exercises}[{class_test('unnumbered')}]"):
        if not has_class(exercise, "grasp-check"):
            d.bake_unnumbered_exercise(exercise)
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_non_introduction_pages(book, chapter)
        inj.bake_all_numbered_exercise_types(
            book, chapter.xpath(
                f".//section[{class_test('check-understanding')}"
                f" or {class_test('practice-problems')}]"),
            exercise_options={"solution_stays_put": True})
        d.bake_chapter_glossary(book, chapter)
        d.bake_chapter_summary(book, chapter)
        d.move_custom_section_to_eoc(book, chapter, "key-equations",
                                     "key-equations",
                                     each=d.titled_from_page(book))
        for container, keys in (
                ("chapter-review", ("concept", "critical-thinking",
                                    "problems", "performance")),
                ("test-prep", ("multiple-choice", "short-answer",
                               "extended-response"))):
            group = d.chapter_review_container(book, chapter, container)
            for key in keys:
                d.move_custom_section_to_eoc(
                    book, chapter, key, key, append_to=group,
                    each=d.titled_from_page(book, title_tag="h4"),
                    wrap_section=True, wrap_content=True)
        inj.bake_all_numbered_exercise_types(
            book, chapter.xpath(".//div[@data-type='composite-chapter']"),
            exercise_options={"suppress_solution": True})
        # BakeFirstElements: classes for OpenStax's stylesheet.
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        d.bake_appendix(book, page, letter)
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
    d.bake_unnumbered_tables(book)
    d.bake_equations(book)
    # BakeMathInParagraph: a class for OpenStax's stylesheet.
    d.bake_footnotes(book)
    # BakeIframes: left to TextbookImprover.
    d.bake_index(book)
    # BakeCompositePages and BakeCompositeChapters: ids for OpenStax's
    # reader.
    d.bake_link_placeholders(book)


def u_physics(book):
    """lib/recipes/u-physics/recipe.rb (*University Physics*, Volumes 1,
    2, and 3). A chapter's review is a group at its end; its problems are
    numbered through the chapter, the conceptual questions and problems
    each page's under the page's title; the answers to its Check Your
    Understanding notes and odd problems are in the answer key."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_unnumbered_figure(book)
    d.bake_preface(book)
    # BakeChapterIntroductions.v1 (its outline first).
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    d.bake_chapter_title(book)
    for chapter in book.chapters():
        d.bake_learning_objectives(book, chapter)
        d.bake_non_introduction_pages(book, chapter)
    d.bake_autotitled_notes(book, ["media-2", "problem-solving"])
    d.bake_unclassified_notes(book)
    d.bake_numbered_notes_v1(book, ["check-understanding"])
    answer_key = d.book_answer_key_container(book)
    eoc = ["review-conceptual-questions", "review-problems",
           "review-additional-problems", "review-challenge"]
    for chapter in book.chapters():
        review = d.chapter_review_container(book, chapter)
        d.bake_chapter_glossary(book, chapter, append_to=review)
        d.bake_chapter_key_equations(book, chapter, append_to=review)
        d.bake_chapter_key_concepts(book, chapter, append_to=review)
        # MoveExercisesToEOC.v2, then .v1.
        for key in eoc[:2]:
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         append_to=review,
                                         each=d.titled_from_page(book),
                                         wrap_section=True,
                                         wrap_content=True)
        for key in eoc[2:]:
            d.move_exercises_to_eoc(book, chapter, key, append_to=review)
        exercises = chapter.xpath(
            ".//section[" + " or ".join(class_test(k) for k in eoc) + "]"
            "/descendant::div[@data-type='exercise']")
        for i, exercise in enumerate(exercises, 1):
            d.bake_numbered_exercise(book, exercise, i)
        inner = d.answer_key_inner_container(book, chapter, answer_key)
        inj.move_solutions_from_numbered_note(book, chapter, inner,
                                              "check-understanding")
        for key in eoc:
            inj.move_solutions_from_exercise_section(book, chapter, inner,
                                                     key)
    # BakeFirstElements: classes for OpenStax's stylesheet.
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
        for i, example in enumerate(chapter.xpath(
                ".//div[@data-type='example']"), 1):
            d.bake_example(book, example, f"{n}.{i}", title_tag="h3")
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        d.bake_appendix(book, page, letter)
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
    d.bake_unnumbered_tables(book)
    d.bake_equations(book)
    d.bake_index(book)
    d.bake_footnotes(book)
    d.bake_link_placeholders(book)
    d.bake_unit_title(book)


def _college_success_shared(book):
    """lib/recipes/college-success/shared.rb, which bakes both editions of
    *College Success* after the edition's own recipe."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_unnumbered_figure(book)
    d.bake_preface(book)
    d.bake_chapter_title(book)
    # BakeChapterIntroductions.v1 (its outline first).
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    d.bake_autotitled_notes(book, ["student-profile", "activity",
                                   "analysis-question", "what-students-say",
                                   "application", "get-connected"])
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_non_introduction_pages(book, chapter)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        d.bake_appendix(book, page, letter)
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
    # Section titles at depth 3 renamed h5: emit.py sets the levels.
    d.bake_unnumbered_tables(book)
    d.bake_footnotes(book)
    d.bake_index(book)
    d.bake_link_placeholders(book)


def college_success(book):
    """lib/recipes/college-success/recipe.rb, then its shared recipe. The
    notes and sections the high school edition adds are taken out, as the
    recipe takes them out of the college edition's assembly."""
    for xpath in (f".//div[{class_test('real-deal')}]",
                  f".//div[{class_test('student-story')}]",
                  f".//section[{class_test('family-friends')}]",
                  f".//section[{class_test('checking-in')}]"):
        for element in book.body.xpath(xpath):
            d.trash(element)
    for chapter in book.chapters():
        for key in ("summary", "career-connection", "rethinking",
                    "where-go"):
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         each=d.remove_section_title)
    _college_success_shared(book)


def hs_college_success(book):
    """lib/recipes/hs-college-success/recipe.rb (*College Success
    Concise*'s high school edition), then the shared recipe."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_autotitled_notes(book, ["real-deal", "student-story"])
    for chapter in book.chapters():
        for key in ("family-friends", "summary", "checking-in"):
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         each=d.remove_section_title)
    _college_success_shared(book)


def english_composition(book):
    """lib/recipes/english-composition/recipe.rb (*Writing Guide with
    Handbook*). The handbook's sections are numbered H1, H2; a section's
    questions from OpenStax's exercise bank are numbered in it; and last,
    a page or section of a kind the book repeats is titled by its kind
    ("Trailblazer", "Quick Launch: ...")."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_unnumbered_figure(book)
    d.bake_preface(book)
    d.bake_handbook(book)
    d.bake_chapter_title(book)
    # BakeChapterIntroductions.v1 (its outline first).
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    d.bake_unit_title(book)
    d.bake_unit_page_title(book)
    # BakeAnnotationClasses: an annotation's icons, drawn by OpenStax's
    # stylesheet and named for screen readers alone, aren't written.
    for key in ("further-reading", "works-cited", "works-consulted"):
        for chapter in book.chapters():
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         each=d.remove_section_title)
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        seen = set()
        for page in book.pages(chapter):
            for section in page.xpath(".//section"):
                questions = section.xpath(
                    ".//div[@data-type='exercise-question']")
                for i, question in enumerate(questions, 1):
                    # A question in a nested section is the outer one's
                    # first, as cookbook's search meets it.
                    if question in seen:
                        continue
                    seen.add(question)
                    inj.bake_injected_exercise_question(book, question, i)
        d.bake_learning_objectives(book, chapter)
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
        d.bake_non_introduction_pages(book, chapter)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
    for page in book.pages(cls="handbook"):
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"H{i}")
    # BakeScreenreaderSpans: words for screen readers alone, not written.
    d.bake_stepwise(book)
    d.bake_unnumbered_tables(book)
    d.bake_index(book)
    d.bake_footnotes(book)
    d.bake_link_placeholders(book)
    for chapter in book.chapters():
        d.bake_custom_sections(book, chapter, [
            ("narrative-trailblazer", "title"), ("living-words", "subtitle"),
            ("quick-launch", "title_prefix"), ("drafting", "title_prefix"),
            ("peer-review", "title_prefix"), ("revising", "title_prefix")])


def _college_physics_shared(book):
    """lib/recipes/college-physics/shared.rb. Its tables are numbered
    counting every one, as astronomy's are, an unnumbered table keeping
    its title and caption here (see astronomy)."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_unnumbered_figure(book)
    d.bake_preface(book)
    d.bake_chapter_title(book)
    # BakeChapterIntroductions.v1 (its outline first).
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    d.bake_unclassified_notes(book)
    d.bake_autotitled_notes(book, ["interactive"])
    for exercise in book.body.xpath(
            ".//div[@data-type='exercise']"
            "[@data-element-type='check-understanding']"):
        d.bake_autotitled_exercise_v2(book, exercise,
                                      book.t("check-understanding"))
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_non_introduction_pages(book, chapter)
        d.bake_chapter_glossary(book, chapter)
        for key in ("section-summary", "conceptual-questions",
                    "problems-exercises"):
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         each=d.titled_from_page(book))
        for i, exercise in enumerate(chapter.xpath(
                f".//section[{class_test('conceptual-questions')}]"
                "/descendant::div[@data-type='exercise']"), 1):
            d.bake_numbered_exercise(book, exercise, i,
                                     suppress_solution=True)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        for i, example in enumerate(chapter.xpath(
                ".//div[@data-type='example']"), 1):
            d.bake_example(book, example, f"{n}.{i}", title_tag="h3")
        for i, table in enumerate(book.tables(chapter), 1):
            if not has_class(table, "unnumbered"):
                d.bake_numbered_table(book, table, f"{n}.{i}")
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        d.bake_appendix(book, page, letter)
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
    for equation in book.body.xpath(
            ".//div[@data-type='composite-page']"
            "/descendant::div[@data-type='equation']"):
        add_class(equation, "unnumbered")
    d.bake_unnumbered_tables(book)
    d.bake_equations(book)
    d.bake_footnotes(book)
    d.bake_index(book)
    d.bake_link_placeholders(book)


def college_physics(book):
    """The college-physics bake: its shared recipe, then
    lib/recipes/college-physics/recipe.rb (*College Physics*, the first
    edition), which numbers each chapter's problems and moves each
    section's objectives into the chapter's outline."""
    _college_physics_shared(book)
    for chapter in book.chapters():
        for i, exercise in enumerate(chapter.xpath(
                f".//section[{class_test('problems-exercises')}]"
                "/descendant::div[@data-type='exercise']"), 1):
            d.bake_numbered_exercise(book, exercise, i,
                                     suppress_solution=True)
        d.bake_learning_objectives_v3(book, chapter)


def college_physics_2e(book):
    """The college-physics-2e bake: lib/recipes/college-physics-2e/
    recipe.rb (*College Physics 2e*), which takes out the AP test prep,
    numbers each chapter's problems, their answers in the answer key, and
    each authentic assessment's in it; then the shared recipe."""
    for section in book.body.xpath(f".//section[{class_test('ap-test-prep')}]"):
        d.trash(section)
    answer_key = d.book_answer_key_container(book)
    for chapter in book.chapters():
        for section in chapter.xpath(
                f".//section[{class_test('authentic-assessment')}]"):
            prepend(section, E("h3", {"data-type": "title"},
                               book.t("exercises.authentic-assessment")))
            for i, exercise in enumerate(section.xpath(
                    ".//div[@data-type='exercise']"), 1):
                d.bake_numbered_exercise(book, exercise, i)
        for i, exercise in enumerate(chapter.xpath(
                f".//section[{class_test('problems-exercises')}]"
                "/descendant::div[@data-type='exercise']"), 1):
            d.bake_numbered_exercise(book, exercise, i)
        inner = d.answer_key_inner_container(book, chapter, answer_key)
        inj.move_solutions_from_exercise_section(book, chapter, inner,
                                                 "problems-exercises")
    d.bake_link_placeholders(book)
    _college_physics_shared(book)


def computer_science(book):
    """lib/recipes/computer-science/recipe.rb (*Introduction to Computer
    Science*), whose selectors take a page's summary to be its section of
    class section-summary. Its units are Parts; a lab's steps are numbered
    as exercises through the chapter; its questions from OpenStax's
    exercise bank are numbered on each page of the chapter's review."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_unnumbered_figure(book)
    d.bake_preface(book, title_element="h1")
    # BakeChapterIntroductions.v1 (its outline first).
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    inj.add_injected_exercise_id(book)
    for exercise in book.body.xpath(".//div[@data-type='injected-exercise']"):
        inj.bake_injected_exercise(book, exercise)
    d.bake_chapter_title(book)
    d.bake_unit_title(book)
    d.bake_unit_page_title(book)
    d.bake_autotitled_notes(book, ["concepts-practice", "tech-everyday",
                                   "global-tech", "link-to-learning",
                                   "industry-spotlight"])
    d.bake_autotitled_notes(book, ["think-through"], bake_exercises=True)
    d.bake_unclassified_notes(book)
    eoc = ["review-questions", "conceptual-questions", "practice-exercises",
           "problem-set-a", "problem-set-b", "thought-provokers",
           "labs-assessments"]
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_non_introduction_pages(book, chapter)
        review = d.chapter_review_container(book, chapter)
        d.bake_chapter_glossary(book, chapter, append_to=review)
        d.move_custom_section_to_eoc(book, chapter, "section-summary",
                                     "section-summary", append_to=review,
                                     each=d.titled_from_page(book))
        d.bake_embedded_exercise_questions(book, chapter, "labs-assessments")
        for key in eoc:
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         append_to=review,
                                         each=d.remove_section_title)
            for composite in chapter.xpath(
                    ".//div[@data-type='composite-page']"):
                questions = composite.xpath(
                    f".//section[{class_test(key)}]"
                    "/descendant::div[@data-type='exercise-question']")
                for i, question in enumerate(questions, 1):
                    inj.bake_injected_exercise_question(book, question, i)
        for exercise in chapter.xpath(
                f".//div[@data-type='exercise'][{class_test('your-turn')}]"):
            d.bake_autotitled_exercise(book, exercise)
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
        d.bake_appendix(book, page, letter)
    d.bake_stepwise(book)
    d.bake_unnumbered_tables(book)
    d.bake_index(book)
    d.bake_footnotes(book)
    d.bake_link_placeholders(book)


def chemistry(book):
    """lib/recipes/chemistry/recipe.rb (*Chemistry 2e* and its *Atoms
    First*). A chapter's exercises follow its summary, each page's under
    the page's title, numbered through the chapter, their answers in the
    answer key; its examples are numbered in it."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_unnumbered_figure(book)
    d.bake_preface(book)
    answer_key = d.book_answer_key_container(book, solutions_plural=False)
    for chapter in book.chapters():
        d.bake_chapter_glossary(book, chapter)
        d.bake_chapter_key_equations(book, chapter)
        d.bake_chapter_summary(book, chapter)
        # MoveExercisesToEOC.v3
        d.move_custom_section_to_eoc(book, chapter, "exercises", "exercises",
                                     each=d.titled_from_page(book))
        exercises = chapter.xpath(
            f".//section[{class_test('exercises')}]"
            "/descendant::div[@data-type='exercise']")
        for i, exercise in enumerate(exercises, 1):
            d.bake_numbered_exercise(book, exercise, i)
        inner = d.answer_key_inner_container(book, chapter, answer_key,
                                             solutions_plural=False)
        d.default_strategy_for_answer_key_solutions(book, chapter,
                                                    ["exercises"], inner)
    # BakeChapterIntroductions.v1 (its outline first).
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    d.bake_chapter_title(book)
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_learning_objectives(book, chapter)
        d.bake_non_introduction_pages(book, chapter)
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
        for i, example in enumerate(chapter.xpath(
                ".//div[@data-type='example']"), 1):
            d.bake_example(book, example, f"{n}.{i}", title_tag="h3")
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
        for j, example in enumerate(page.xpath(
                ".//div[@data-type='example']"), 1):
            d.bake_example(book, example, f"{letter}{j}", title_tag="div")
        d.bake_appendix(book, page, letter)
    d.bake_unnumbered_tables(book)
    # BakeFirstElements: classes for OpenStax's stylesheet.
    d.bake_autotitled_notes(book, ["link-to-learning", "everyday-life",
                                   "chemist-portrait",
                                   "sciences-interconnect"])
    d.bake_unclassified_notes(book)
    d.bake_stepwise(book)
    d.bake_equations(book)
    d.bake_index(book)
    d.bake_footnotes(book)
    d.bake_link_placeholders(book)


def anatomy(book):
    """lib/recipes/anatomy/recipe.rb (*Anatomy and Physiology 2e*), whose
    selectors take a reference to be a section of class references. The
    chapter's objectives open its introduction; its questions follow its
    review, by kind, numbered through the chapter, without solutions; the
    references are gathered at the end of the book."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_unnumbered_figure(book)
    d.bake_preface(book, title_element="h1")
    d.bake_unit_title(book)
    inj.add_injected_exercise_id(book)
    d.bake_chapter_introductions(book, introduction_order="v2")
    d.bake_chapter_title(book)
    for note in book.notes(cls="homeostatic"):
        note.set("use-subtitle", "true")
    d.bake_autotitled_notes(book, ["interactive", "everyday", "homeostatic",
                                   "disorders", "career", "aging",
                                   "diseases"])
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_learning_objectives(book, chapter)
        d.bake_non_introduction_pages(book, chapter)
        d.bake_chapter_glossary(book, chapter)
        d.bake_chapter_summary(book, chapter)
        for key in ("interactive-exercise", "multiple-choice",
                    "free-response"):
            d.move_exercises_to_eoc(book, chapter, key)
        inj.bake_all_numbered_exercise_types(
            book, chapter.xpath(f".//div[{class_test('os-eoc')}]"),
            exercise_options={"suppress_solution": True})
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
        d.bake_appendix(book, page, letter)
    d.bake_references_v3(book)
    d.bake_equations(book)
    d.bake_index(book)
    d.bake_link_placeholders(book)


def anthropology(book):
    """lib/recipes/anthropology/recipe.rb. Its critical thinking questions
    are from OpenStax's exercise bank, numbered through the chapter."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_unnumbered_figure(book)
    d.bake_preface(book)
    # BakeChapterIntroductions.v1 (its outline first), before the
    # chapters' titles are baked.
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    d.bake_chapter_title(book)
    d.bake_autotitled_notes(book, ["ethnographic-sketches",
                                   "fieldwork-activity",
                                   "profiles-anthropology", "media-podcast",
                                   "media-video"])
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_learning_objectives(book, chapter)
        d.bake_non_introduction_pages(book, chapter)
        d.bake_chapter_glossary(book, chapter)
        d.move_custom_section_to_eoc(book, chapter, "section-summary",
                                     "section-summary",
                                     each=d.remove_section_title)
        questions = []
        for page in book.pages(chapter):
            questions.extend(page.xpath(
                f".//section[{class_test('critical-thinking')}]"
                "/descendant::div[@data-type='exercise-question']"))
        for i, question in enumerate(questions, 1):
            inj.bake_injected_exercise_question(book, question, i)
        d.move_exercises_to_eoc(book, chapter, "critical-thinking")
        d.move_custom_section_to_eoc(book, chapter, "references",
                                     "references",
                                     each=d.remove_section_title)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
    d.bake_index(book)
    d.bake_link_placeholders(book)


def astronomy(book):
    """lib/recipes/astronomy/recipe.rb. A chapter's questions are in an
    Exercises group at its end, by kind, numbered through the chapter.
    Its tables are numbered counting every one, as the recipe counts
    them, so one after an unnumbered table skips a number, as OpenStax's
    book does. The recipe also gives an unnumbered table to
    BakeNumberedTable, which cuts its title and caption and puts nothing
    back; here it keeps them, baked as BakeUnnumberedTables bakes one
    (*Astronomy 2e*'s "Table A")."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_unnumbered_figure(book)
    d.bake_preface(book)
    d.bake_chapter_title(book)
    # BakeChapterIntroductions.v1 (its outline first).
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    d.bake_autotitled_notes(book, ["link-to-learning", "astronomy-basics",
                                   "making-connections",
                                   "seeing-for-yourself",
                                   "voyagers-in-astronomy"])
    d.bake_unclassified_notes(book)
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_non_introduction_pages(book, chapter)
        d.bake_chapter_glossary(book, chapter)
        d.bake_chapter_summary(book, chapter)
        for key in ("further-exploration", "group-activities"):
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         each=d.remove_section_title)
        group = d.chapter_review_container(book, chapter, "exercises")
        for key in ("review-questions", "thought-questions",
                    "figuring-for-yourself"):
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         append_to=group,
                                         each=d.remove_section_title)
        for i, exercise in enumerate(group.xpath(
                ".//div[@data-type='exercise']"), 1):
            d.bake_numbered_exercise(book, exercise, i)
        if not group.xpath(".//section"):
            d.trash(group)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        for i, example in enumerate(chapter.xpath(
                ".//div[@data-type='example']"), 1):
            d.bake_example(book, example, f"{n}.{i}", title_tag="h3")
        for i, table in enumerate(book.tables(chapter), 1):
            if not has_class(table, "unnumbered"):
                d.bake_numbered_table(book, table, f"{n}.{i}")
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        d.bake_appendix(book, page, letter)
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
    d.bake_unnumbered_tables(book)
    # BakeScreenreaderSpans: words for screen readers alone, not written.
    d.bake_footnotes(book)
    d.bake_equations(book)
    d.bake_index(book)
    d.bake_link_placeholders(book)


def _polish_appendices(book, exercises=False):
    """The Polish recipes' loop over book.pages('$.appendix'): a letter
    each, named in a link's case; its figures and tables numbered A1,
    A2, and with exercises, a section's exercises too."""
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        d.bake_appendix(book, page, letter, cases=True)
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}", cases=True)
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}", cases=True)
        if exercises:
            found = page.xpath(".//section/descendant::div"
                               "[@data-type='exercise']")
            for j, exercise in enumerate(found, 1):
                d.bake_numbered_exercise(book, exercise, f"{letter}{j}",
                                         cases=True)


def pl_economics(book):
    """lib/recipes/pl-economics/recipe.rb, for *Mikroekonomia* and
    *Makroekonomia*, in Polish, whose selectors take a reference to be a
    section of class references. A chapter's questions follow it, by
    kind, numbered through the chapter, the answers to its self-check
    questions and problems in the answer key; a link names its target
    in the case its sentence wants."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_lists_with_para(book)
    d.bake_preface(book, title_element="h1")
    d.bake_unnumbered_figure(book)
    d.bake_chapter_introductions(book, cases=True)
    d.bake_chapter_title(book)
    d.bake_unclassified_notes(book)
    # BakeIframes: left to TextbookImprover.
    d.bake_autotitled_notes(book, ["linkup", "bringhome", "clearup",
                                   "workout", "learning-objectives"],
                            cases=True)
    answer_key = d.book_answer_key_container(book)
    kinds = ("summary", "self-check-questions", "review-questions",
             "critical-thinking", "problems")
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_chapter_glossary(book, chapter, has_para=True)
        d.bake_chapter_summary(book, chapter)
        # Kitchen's search of several selectors: each kind's sections in
        # turn, the exercises numbered through them all.
        exercises = [e for kind in kinds
                     for section in chapter.xpath(
                         f".//section[{class_test(kind)}]")
                     for e in section.xpath(".//div[@data-type='exercise']")]
        for i, exercise in enumerate(exercises, 1):
            d.bake_numbered_exercise(book, exercise, i, cases=True)
        for kind in kinds:
            d.move_exercises_to_eoc(book, chapter, kind)
        inner = d.answer_key_inner_container(book, chapter, answer_key)
        d.default_strategy_for_answer_key_solutions(
            book, chapter, ["self-check-questions", "problems",
                            "ap-test-prep"], inner)
        # The recipe's "temporary fix for top-captioned tables": one
        # with no caption loses its classes.
        for table in book.tables(chapter):
            if has_class(table, "top-captioned") \
                    and not table.xpath(".//caption"):
                del table.attrib["class"]
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}", cases=True)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}", cases=True)
        # BakeFirstElements: classes for OpenStax's stylesheet.
        d.bake_non_introduction_pages(book, chapter, cases=True)
    _polish_appendices(book, exercises=True)
    d.bake_unnumbered_tables(book)
    d.bake_references_v2(book)
    d.bake_equations(book)
    d.bake_index(book, types=("name", "term", "foreign"))
    d.bake_footnotes(book)
    # BakeCompositePages and BakeCompositeChapters: ids for OpenStax's
    # reader.
    d.bake_link_placeholders(book, cases=True)


def pl_psychology(book):
    """lib/recipes/pl-psychology/recipe.rb, for *Psychologia*, whose
    selectors take a reference to be a section of class references. A
    chapter's summaries follow it, each page's under the page's title,
    then its questions, numbered through the chapter without solutions;
    a link names its target in the case its sentence wants."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_lists_with_para(book)
    d.bake_preface(book)
    d.bake_unnumbered_figure(book)
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True,
                                 block_target_label=True, cases=True)
    d.bake_chapter_title(book)
    kinds = ("review-questions", "critical-thinking", "personal-application")
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_learning_objectives(book, chapter)
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table_v2(book, table, f"{n}.{i}", cases=True)
        for i, example in enumerate(chapter.xpath(
                ".//div[@data-type='example']"), 1):
            d.bake_example(book, example, f"{n}.{i}", title_tag="h3",
                           cases=True)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}", cases=True)
        d.bake_non_introduction_pages(book, chapter, block_target_label=True)
        d.bake_chapter_glossary(book, chapter, has_para=True)
        d.move_custom_section_to_eoc(book, chapter, "summary", "summary",
                                     each=d.titled_from_page(book))
        for kind in kinds:
            d.move_custom_section_to_eoc(book, chapter, kind, kind,
                                         each=d.remove_section_title)
        exercises = chapter.xpath(
            ".//section[" + " or ".join(class_test(k) for k in kinds)
            + "]/descendant::div[@data-type='exercise']")
        for i, exercise in enumerate(exercises, 1):
            d.bake_numbered_exercise(book, exercise, i,
                                     suppress_solution=True, cases=True)
    d.bake_autotitled_notes(book, ["link-to-learning", "dig-deeper",
                                   "everyday-connection", "what-do-you-think",
                                   "connect-the-concepts"], cases=True)
    d.bake_references_v2(book)
    d.bake_index(book, types=("name", "term", "foreign"))
    # BakeCompositePages: ids for OpenStax's reader.
    d.bake_footnotes(book)
    d.bake_link_placeholders(book, cases=True)


def pl_u_physics(book):
    """lib/recipes/pl-u-physics/recipe.rb, for *Fizyka dla szkół
    wyższych*, Volumes 1, 2, and 3, in Polish. A chapter's review is a
    group at its end; its questions and problems are numbered through
    the chapter, the answers to them and to its Check Your Understanding
    notes in the answer key; a link names its target in the case its
    sentence wants."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    # The recipe takes the bold out of every Check Your Understanding.
    for bold in book.body.xpath(
            f".//*[{class_test('check-understanding')}]//strong"):
        d.trash(bold)
    d.bake_preface(book)
    d.bake_chapter_title(book)
    d.bake_unit_title(book)
    d.bake_unnumbered_figure(book)
    d.bake_unnumbered_tables(book)
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True,
                                 block_target_label=True, cases=True)
    d.bake_autotitled_notes(book, ["media-2", "problem-solving"],
                            cases=True)
    d.bake_unclassified_notes(book)
    d.bake_numbered_notes_v1(book, ["check-understanding"], cases=True)
    answer_key = d.book_answer_key_container(book)
    linked = ("key-concepts", "review-conceptual-questions",
              "review-problems")
    unlinked = ("review-additional-problems", "review-challenge")
    for chapter in book.chapters():
        d.bake_non_introduction_pages(book, chapter, cases=True)
        d.bake_learning_objectives(book, chapter)
        review = d.chapter_review_container(book, chapter)
        d.bake_chapter_glossary(book, chapter, append_to=review)
        d.move_custom_section_to_eoc(book, chapter, "key-equations",
                                     "key-equations", append_to=review,
                                     each=d.remove_section_title)
        for key in linked:
            d.move_custom_section_to_eoc(
                book, chapter, key, key, append_to=review,
                each=d.titled_from_page(book, title_tag="h4"),
                wrap_section=True, wrap_content=True)
        for key in unlinked:
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         append_to=review,
                                         each=d.remove_section_title)
        kinds = linked[1:] + unlinked
        exercises = chapter.xpath(
            ".//section[" + " or ".join(class_test(k) for k in kinds)
            + "]/descendant::div[@data-type='exercise']")
        for i, exercise in enumerate(exercises, 1):
            d.bake_numbered_exercise(book, exercise, i, cases=True)
        inner = d.answer_key_inner_container(book, chapter, answer_key)
        inj.move_solutions_from_numbered_note(book, chapter, inner,
                                              "check-understanding")
        for key in kinds:
            inj.move_solutions_from_exercise_section(book, chapter, inner,
                                                     key)
    # BakeFirstElements: classes for OpenStax's stylesheet.
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}", cases=True)
        for i, example in enumerate(chapter.xpath(
                ".//div[@data-type='example']"), 1):
            d.bake_example(book, example, f"{n}.{i}", title_tag="h3",
                           cases=True)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}", cases=True)
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        d.bake_appendix(book, page, letter, block_target_label=True,
                        cases=True)
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}", cases=True)
    # BakeIframes: left to TextbookImprover.
    d.bake_equations(book, cases=True)
    # BakeMathInParagraph: a class for OpenStax's stylesheet.
    d.bake_index(book, types=("name", "term", "foreign"))
    # BakeCompositePages and BakeCompositeChapters: ids for OpenStax's
    # reader.
    d.bake_footnotes(book)
    d.bake_link_placeholders(book, cases=True)


def pl_marketing(book):
    """lib/recipes/pl-marketing/recipe.rb, for *Marketing - Podstawy*,
    whose references are footnotes of class reference. A section's
    knowledge check is numbered in it, its answers in the answer key
    under the section's number; a chapter's summary, key terms, and
    questions follow it, then its references, numbered through the
    chapter; a link names its target in the case its sentence wants."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_lists_with_para(book)
    d.bake_preface(book, cases=True)
    for page in book.pages(cls="preface"):
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, str(i), cases=True)
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True,
                                 introduction_order="v3", cases=True)
    d.bake_chapter_title(book)
    d.bake_unnumbered_figure(book)
    d.bake_unclassified_notes(book)
    answer_key = d.book_answer_key_container(book, solutions_plural=False)
    eoc = ("marketing-discussion", "critical-thinking", "marketing-plan",
           "company-case")
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_non_introduction_pages(book, chapter, cases=True)
        d.bake_learning_objectives_v2(book, chapter, add_title=False,
                                      li_numbering="count_only_li")
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}", cases=True)
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}", cases=True)
        for page in book.pages(chapter):
            inj.bake_all_numbered_exercise_types(
                book, page.xpath(f".//section[{class_test('knowledge-check')}]"),
                exercise_options={"cases": True},
                question_options={"add_dot": True})
        d.move_custom_section_to_eoc(book, chapter, "chapter-summary",
                                     "chapter-summary",
                                     each=d.remove_section_title)
        d.bake_chapter_glossary(book, chapter, has_para=True)
        for key in eoc:
            sections = [s for page in book.pages(chapter)
                        for s in page.xpath(f".//section[{class_test(key)}]")]
            inj.bake_all_numbered_exercise_types(
                book, sections, exercise_options={"cases": True})
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         each=d.remove_section_title)
        inner = d.answer_key_inner_container(book, chapter, answer_key,
                                             solutions_plural=False)
        for i, page in enumerate(book.non_introduction_pages(chapter), 1):
            inj.move_solutions_from_exercise_section(
                book, page, inner, "knowledge-check", title_number=f"{n}.{i}")
    # BakeFootnotes.v1 for the references, then BakeChapterReferences.v4.
    d.bake_reference_footnotes(book)
    for chapter in book.chapters():
        d.bake_chapter_references_v4(book, chapter)
    d.bake_autotitled_notes(book, ["marketing-practice",
                                   "companies-conscience",
                                   "link-to-learning"], cases=True)
    d.bake_autotitled_notes(book, ["marketing-dashboard"],
                            bake_exercises=True, cases=True)
    d.bake_equations(book)
    # BakeIframes: left to TextbookImprover.
    # BakeFootnotes.v1 for the other footnotes, numbered in Roman there
    # and as the notes settings say here.
    d.bake_footnotes(book)
    d.bake_index(book, types=("name", "term", "foreign"))
    # BakeCompositePages and BakeCompositeChapters: ids for OpenStax's
    # reader.
    d.bake_unit_title(book)
    d.bake_unit_page_title(book)
    d.bake_link_placeholders(book, cases=True)


def pl_nursing(book):
    """lib/recipes/pl-nursing/recipe.rb, whose selectors take a reference
    to be a section of class references. A chapter's summary, further
    reading, key terms, and review questions follow it; the questions,
    and those in its case studies, are numbered through the chapter,
    their answers in the answer key; a link names its target in the case
    its sentence wants."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_lists_with_para(book)
    d.bake_unnumbered_figure(book)
    d.bake_preface(book, cases=True)
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True,
                                 introduction_order="v3", cases=True,
                                 authors=True)
    d.bake_chapter_title(book)
    answer_key = d.book_answer_key_container(book)
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_non_introduction_pages(book, chapter, cases=True)
        d.bake_learning_objectives_v2(book, chapter, add_title=False)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}", cases=True)
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}", cases=True)
        d.move_custom_section_to_eoc(book, chapter, "chapter-summary",
                                     "chapter-summary",
                                     each=d.remove_section_title)
        d.bake_sortable_section(book, chapter, "suggested-reading")
        d.bake_chapter_glossary(book, chapter, has_para=True)
        d.move_custom_section_to_eoc(book, chapter, "review-questions",
                                     "review-questions",
                                     each=d.remove_section_title)
        inj.bake_all_numbered_exercise_types(
            book, chapter.xpath(
                f".//section[{class_test('review-questions')}]"),
            exercise_options={"cases": True})
        inj.bake_all_numbered_exercise_types(
            book, [note for page in book.pages(chapter)
                   for note in book.notes(page, "unfolding-casestudy")],
            exercise_options={"cases": True})
        inner = d.answer_key_inner_container(book, chapter, answer_key)
        inj.move_solutions_from_numbered_note(book, chapter, inner,
                                              "unfolding-casestudy")
        inj.move_solutions_from_exercise_section(book, chapter, inner,
                                                 "review-questions")
        # BakeFirstElements: classes for OpenStax's stylesheet.
    d.bake_autotitled_notes(book, ["special-considerations", "clinical-tip",
                                   "safety-alert", "unfolding-casestudy",
                                   "trending-today"], cases=True)
    d.bake_custom_titled_notes(book, ["media-feature"])
    d.bake_unclassified_notes(book)
    d.bake_unnumbered_tables(book)
    # BakeTableColumns: column widths for OpenStax's stylesheet.
    # BakeIframes: left to TextbookImprover.
    d.bake_unit_title(book)
    d.bake_references_v4(book)
    d.bake_index(book, types=("name", "term", "foreign"))
    # BakeCompositePages and BakeCompositeChapters: ids for OpenStax's
    # reader.
    d.bake_link_placeholders(book, cases=True)


def political_science(book):
    """lib/recipes/political-science/recipe.rb. Its review questions are
    from OpenStax's exercise bank, numbered through the chapter."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_unnumbered_figure(book)
    d.bake_preface(book)
    # BakeChapterIntroductions.v1 (its outline first).
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    d.bake_chapter_title(book)
    d.bake_unit_title(book)
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_learning_objectives(book, chapter)
        d.bake_non_introduction_pages(book, chapter)
        d.move_custom_section_to_eoc(book, chapter, "summary", "summary",
                                     each=d.titled_from_page(book))
        d.bake_chapter_glossary(book, chapter)
        questions = []
        for page in book.pages(chapter):
            questions.extend(page.xpath(
                f".//section[{class_test('review-questions')}]"
                "/descendant::div[@data-type='exercise-question']"))
        for i, question in enumerate(questions, 1):
            inj.bake_injected_exercise_question(book, question, i)
        for key in ("review-questions", "suggested-readings"):
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         each=d.remove_section_title)
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
    d.bake_autotitled_notes(book, ["show-data", "connecting-courses",
                                   "meet-professional", "changing-political",
                                   "what-do", "where-engage", "media-video",
                                   "media-podcast"])
    d.bake_footnotes(book)
    d.bake_references_v1(book, numbered_title=True)
    d.bake_index(book)
    d.bake_link_placeholders(book)


def lifespan_development(book):
    """lib/recipes/lifespan-development/recipe.rb. Its end-of-chapter
    questions are exercises from OpenStax's exercise bank, their answers
    in the book's answer key."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_preface(book)
    d.bake_unnumbered_figure(book)
    d.bake_unnumbered_tables(book)
    inj.add_injected_exercise_id(book)
    for exercise in book.body.xpath(".//div[@data-type='injected-exercise']"):
        inj.bake_injected_exercise(book, exercise)
    d.bake_chapter_title(book)
    # BakeChapterIntroductions.v1 (its outline first).
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    answer_key = d.book_answer_key_container(book)
    eoc = ["review-questions", "check-understanding", "personal-application",
           "essay-questions"]
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_non_introduction_pages(book, chapter)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
        d.bake_chapter_glossary(book, chapter)
        d.move_custom_section_to_eoc(book, chapter, "summary", "summary",
                                     each=d.titled_from_page(book))
        for key in eoc:
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         each=d.remove_section_title)
        inj.bake_all_numbered_exercise_types(
            book, chapter.xpath(".//div[@data-type='composite-page']"))
        inner = d.answer_key_inner_container(book, chapter, answer_key)
        for key in eoc:
            inj.move_solutions_from_exercise_section(book, chapter, inner,
                                                     key, add_title=False)
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
        d.bake_appendix(book, page, letter)
    d.bake_autotitled_notes(book, ["link-to-learning", "it-depends",
                                   "intersections-contexts", "life-hacks"])
    d.bake_index(book)
    d.bake_footnotes(book)
    d.bake_link_placeholders(book)


def philosophy(book):
    """lib/recipes/philosophy/recipe.rb. A chapter's references are its
    pages' paragraphs of references, sorted; its review questions are
    from OpenStax's exercise bank, numbered through the chapter."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_preface(book)
    d.bake_chapter_title(book)
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    d.bake_unnumbered_figure(book)
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_non_introduction_pages(book, chapter)
        d.move_custom_section_to_eoc(book, chapter, "summary", "summary",
                                     each=d.titled_from_page(book))
        d.bake_chapter_glossary(book, chapter)
        # BakeChapterReferences.v3
        d.bake_sortable_section(book, chapter, "references")
        questions = []
        for page in book.pages(chapter):
            questions.extend(page.xpath(
                f".//section[{class_test('review-questions')}]"
                "/descendant::div[@data-type='exercise-question']"))
        for i, question in enumerate(questions, 1):
            inj.bake_injected_exercise_question(book, question, i)
        d.move_custom_section_to_eoc(book, chapter, "review-questions",
                                     "review-questions",
                                     each=d.titled_from_page(book),
                                     wrap_section=True, wrap_content=True)
        d.move_custom_section_to_eoc(book, chapter, "further-reading",
                                     "further-reading",
                                     each=d.remove_section_title)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
    d.bake_autotitled_notes(book, ["read-philosopher", "think-philosopher",
                                   "write-philosopher", "philo-connections",
                                   "time-line", "media-video",
                                   "media-podcast"])
    d.bake_index(book)
    d.bake_link_placeholders(book)


def ap_history(book):
    """lib/recipes/ap-history/recipe.rb (*Life, Liberty, and the Pursuit
    of Happiness*). Nothing moves: in each subsection of a page, its
    exercises are numbered from 1 where they are, and so, on their own,
    are its questions from OpenStax's exercise bank."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_unnumbered_figure(book)
    d.bake_preface(book)
    d.bake_unit_title(book)
    d.bake_chapter_title(book)
    d.bake_autotitled_notes(book, ["os-teacher"])
    d.bake_unclassified_notes(book)
    # BakeIframes: left to TextbookImprover.
    # BakeAccessibilityFixes (a lower-alpha list's type a): the unpacker
    # gives every numbered list its type as it reads the source.
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_non_introduction_pages(book, chapter)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
        for page in book.pages(chapter):
            for section in page.xpath(".//section[@data-depth='2']"):
                exercises = section.xpath(".//div[@data-type='exercise']")
                for i, exercise in enumerate(exercises, 1):
                    d.bake_numbered_exercise(book, exercise, i)
                questions = section.xpath(
                    ".//div[@data-type='exercise-question']")
                for i, question in enumerate(questions, 1):
                    inj.bake_injected_exercise_question(book, question, i)
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        d.bake_appendix(book, page, letter)
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
    d.bake_unnumbered_tables(book)
    d.bake_link_placeholders(book)


def history(book):
    """lib/recipes/history/recipe.rb (*U.S. History*). A chapter's review
    questions and critical thinking questions are numbered through the
    chapter together; the odd review questions' answers are in the answer
    key."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_preface(book, title_element="h1")
    # BakeChapterIntroductions.v1 (its outline first).
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    d.bake_chapter_title(book)
    d.bake_autotitled_notes(book, ["click-and-explore", "my-story",
                                   "americana", "defining-american"])
    answer_key = d.book_answer_key_container(book, solutions_plural=False)
    eoc = ["review-questions", "critical-thinking"]
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_learning_objectives(book, chapter)
        d.bake_non_introduction_pages(book, chapter)
        d.bake_chapter_glossary(book, chapter)
        d.bake_chapter_summary(book, chapter)
        exercises = chapter.xpath(
            f".//section[{class_test(eoc[0])} or {class_test(eoc[1])}]"
            "/descendant::div[@data-type='exercise']")
        for i, exercise in enumerate(exercises, 1):
            if has_class(exercise.getparent(), "review-questions"):
                d.bake_numbered_exercise(book, exercise, i,
                                         suppress_solution="even",
                                         note_suppressed_solutions=True)
            else:
                d.bake_numbered_exercise(book, exercise, i)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
        inner = d.answer_key_inner_container(book, chapter, answer_key,
                                             solutions_plural=False)
        d.default_strategy_for_answer_key_solutions(
            book, chapter, ["review-questions"], inner)
        for key in eoc:
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         each=d.remove_section_title)
    d.bake_unnumbered_figure(book)
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
        d.bake_appendix(book, page, letter)
    d.bake_index(book)
    d.bake_footnotes(book)
    d.bake_link_placeholders(book)


def world_history(book):
    """lib/recipes/world-history/recipe.rb. A chapter's question pages are
    in an Assessments group; on each, its exercises are numbered first and
    then the questions from OpenStax's exercise bank, as cookbook's search
    of the two kinds finds them."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    inj.add_injected_exercise_id(book)
    for exercise in book.body.xpath(".//div[@data-type='injected-exercise']"):
        inj.bake_injected_exercise(book, exercise)
    d.bake_preface(book)
    d.bake_unnumbered_figure(book)
    d.bake_chapter_title(book)
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    d.bake_unit_title(book)
    eoc = ["review-questions", "check-understanding", "reflection-questions",
           "visual-questions", "making-connections", "thought-provokers",
           "source-questions"]
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_chapter_glossary(book, chapter)
        d.move_custom_section_to_eoc(book, chapter, "section-summary",
                                     "section-summary",
                                     each=d.titled_from_page(book))
        wrapper = d.chapter_review_container(book, chapter, "assessments")
        for key in eoc:
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         append_to=wrapper,
                                         each=d.remove_section_title)
        for composite in chapter.xpath(
                ".//div[@data-type='composite-page']"):
            exercises = composite.xpath(".//div[@data-type='exercise']")
            questions = composite.xpath(
                ".//div[@data-type='exercise-question']")
            for i, exercise in enumerate(exercises, 1):
                d.bake_numbered_exercise(book, exercise, i,
                                         suppress_solution=True)
            for i, question in enumerate(questions, len(exercises) + 1):
                inj.bake_injected_exercise_question(book, question, i)
        d.bake_learning_objectives(book, chapter)
        d.bake_non_introduction_pages(book, chapter)
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
    d.bake_autotitled_notes(book, ["own-words", "dueling-voices",
                                   "beyond-book", "past-present"])
    d.bake_autotitled_notes(book, ["link-to-learning"], bake_subtitle=False)
    d.bake_stepwise(book)
    d.bake_unnumbered_tables(book)
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        d.bake_appendix(book, page, letter)
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
    d.bake_index(book)
    d.bake_footnotes(book)
    d.bake_link_placeholders(book)


def psychology(book):
    """lib/recipes/psychology/recipe.rb, whose selectors take a reference
    to be a section of class references. A chapter's questions follow its
    summary, by kind, numbered from 1 on each page, without solutions."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_preface(book)
    d.bake_unnumbered_figure(book)
    d.bake_chapter_title(book)
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_learning_objectives(book, chapter)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
        d.bake_non_introduction_pages(book, chapter)
        d.bake_chapter_glossary(book, chapter)
        d.move_custom_section_to_eoc(book, chapter, "summary", "summary",
                                     each=d.titled_from_page(book))
        for key in ("review-questions", "critical-thinking",
                    "personal-application"):
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         each=d.remove_section_title)
        inj.bake_all_numbered_exercise_types(
            book, chapter.xpath(".//div[@data-type='composite-page']"),
            exercise_options={"suppress_solution": True})
    d.bake_autotitled_notes(book, ["link-to-learning", "dig-deeper",
                                   "everyday-connection", "what-do-you-think",
                                   "connect-the-concepts"])
    d.bake_references_v2(book)
    d.bake_index(book)
    d.bake_link_placeholders(book)


def information_systems(book):
    """lib/recipes/information-systems/recipe.rb. Its end-of-chapter
    questions are exercises from OpenStax's exercise bank."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_preface(book)
    d.bake_unnumbered_figure(book)
    d.bake_unnumbered_tables(book)
    inj.add_injected_exercise_id(book)
    for exercise in book.body.xpath(".//div[@data-type='injected-exercise']"):
        inj.bake_injected_exercise(book, exercise)
    d.bake_unit_title(book)
    d.bake_chapter_title(book)
    # BakeChapterIntroductions.v1: the chapter's outline first.
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    d.bake_autotitled_notes(book, ["future-tech", "global-connect",
                                   "is-ethics", "is-careers",
                                   "link-to-learning"])
    answer_key = d.book_answer_key_container(book)
    eoc = ["review-questions", "check-understanding",
           "application-questions"]
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_non_introduction_pages(book, chapter)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
        d.bake_chapter_glossary(book, chapter)
        d.move_custom_section_to_eoc(book, chapter, "summary", "summary",
                                     each=d.titled_from_page(book))
        for key in eoc:
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         each=d.remove_section_title)
            for composite in chapter.xpath(
                    "./div[@data-type='composite-page']"):
                questions = composite.xpath(
                    f".//section[{class_test(key)}]"
                    "/descendant::div[@data-type='exercise-question']")
                for i, question in enumerate(questions, 1):
                    inj.bake_injected_exercise_question(book, question, i)
            # BakeFirstElements: classes for OpenStax's stylesheet.
        inner = d.answer_key_inner_container(book, chapter, answer_key)
        for key in eoc:
            inj.move_solutions_from_exercise_section(book, chapter, inner,
                                                     key)
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
        d.bake_appendix(book, page, letter)
    # BakeTableColumns: column widths for OpenStax's stylesheet.
    d.bake_footnotes(book)
    d.bake_index(book)
    d.bake_link_placeholders(book)


def data_science(book):
    """lib/recipes/data-science/recipe.rb, whose selectors take a
    reference to be a section of class references. Its end-of-chapter
    questions are exercises from OpenStax's exercise bank, a question in
    parts lettered."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_preface(book)
    d.bake_unnumbered_figure(book)
    d.bake_unnumbered_tables(book)
    inj.add_injected_exercise_id(book)
    for exercise in book.body.xpath(".//div[@data-type='injected-exercise']"):
        inj.bake_injected_exercise(book, exercise,
                                   alphabetical_multiparts=True,
                                   list_type="lower-alpha",
                                   suppress_summary=True)
    d.bake_chapter_title(book)
    # BakeChapterIntroductions.v1: the chapter's outline first.
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    answer_key = d.book_answer_key_container(book)
    eoc = ["chapter-review", "critical-thinking", "quantitative-problems"]
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_non_introduction_pages(book, chapter)
        d.bake_learning_objectives_v2(book, chapter, add_title=False)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            # BakeNumberedTable.v2: the same words as v1, in this order.
            d.bake_numbered_table(book, table, f"{n}.{i}")
        examples = chapter.xpath(".//div[@data-type='example']")
        for i, example in enumerate(examples, 1):
            d.bake_example(book, example, f"{n}.{i}", title_tag="h3",
                           add_problem_title=True)
        d.bake_chapter_glossary(book, chapter)
        d.move_custom_section_to_eoc(book, chapter, "group-project",
                                     "group-project")
        for key in eoc:
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         each=d.remove_section_title)
        for key in eoc:
            questions = chapter.xpath(f".//section[{class_test(key)}]"
                                      "/descendant::div[@data-type='exercise-question']")
            for i, question in enumerate(questions, 1):
                inj.bake_injected_exercise_question(
                    book, question, i, suppress_summary=True, add_dot=True)
        # BakeChapterReferences.v3
        d.bake_sortable_section(book, chapter, "references")
        inner = d.answer_key_inner_container(book, chapter, answer_key)
        for key in eoc:
            inj.move_solutions_from_exercise_section(book, chapter, inner,
                                                     key)
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
        d.bake_appendix(book, page, letter)
    d.answer_key_cleaner(book)
    d.bake_equations(book)
    d.bake_index(book)
    d.bake_footnotes(book)
    d.bake_link_placeholders(book)
    d.bake_autotitled_notes(book, ["exploring-further", "python-feature"])
    d.bake_custom_titled_notes(book, ["boxed-feature", "download-file"])


def principles_management(book):
    """lib/recipes/principles-management/recipe.rb, for Principles of
    Management and Organizational Behavior, whose selectors take a
    page's summary to be its section of class section-summary. A figure
    is an "Exhibit"; a reference is a note inside its citation, gathered
    on one page at the book's end."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_preface(book, title_element="h1")
    d.bake_chapter_introductions(book)
    d.bake_chapter_title(book)
    d.bake_autotitled_notes(book, [
        "exploring-manager-careers", "concept-check",
        "sustainability-responsible", "managerial-leadership",
        "ethics-in-practice", "managing-change", "catching-spirit",
        "expanding-around-globe", "customer-satisfaction"])
    d.bake_references_v1(book)
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_learning_objectives(book, chapter)
        d.bake_non_introduction_pages(book, chapter)
        d.bake_chapter_glossary(book, chapter)
        d.bake_chapter_summary(book, chapter, klass="section-summary")
        d.bake_chapter_references(book, chapter, selector="reference")
        for key in ("section-summary", "chapter-review", "manage-skills",
                    "manage-exercises", "critical-thinking"):
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         each=d.remove_section_title)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            # BakeNumberedTable.v2: the same words as v1.
            d.bake_numbered_table(book, table, f"{n}.{i}")
    d.bake_unnumbered_figure(book)
    d.bake_unnumbered_tables(book)
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
        d.bake_appendix(book, page, letter)
    # BakeMathInParagraph: a wrapper for the stylesheet only.
    d.bake_index(book)
    d.bake_footnotes(book)
    d.bake_link_placeholders(book)


def intro_business(book):
    """lib/recipes/intro-business/recipe.rb, for Introduction to
    Business. A figure is an "Exhibit"; a reference is a note inside its
    citation, gathered on one page at the book's end."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_preface(book)
    d.bake_unnumbered_figure(book)
    d.bake_chapter_title(book)
    d.bake_chapter_introductions(book)
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            # BakeNumberedTable.v2: the same words as v1.
            d.bake_numbered_table(book, table, f"{n}.{i}")
        d.bake_non_introduction_pages(book, chapter)
        d.bake_chapter_glossary(book, chapter)
        d.move_custom_section_to_eoc(book, chapter, "section-summary",
                                     "section-summary",
                                     each=d.titled_from_page(book))
        for key in ("prep-workplace", "ethics-activity", "working-net",
                    "critical-thinking", "hot-links"):
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         each=d.remove_section_title)
    d.bake_autotitled_notes(book, [
        "exploring-business-careers", "catching-spirit", "concept-check",
        "managing-change", "customer-satisfaction", "ethics-in-practice",
        "expanding-around-globe"])
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        d.bake_appendix(book, page, letter)
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
    d.bake_unnumbered_tables(book)
    d.bake_footnotes(book)
    d.bake_index(book)
    d.bake_references_v1(book)
    d.bake_link_placeholders(book)


def entrepreneurship(book):
    """lib/recipes/entrepreneurship/recipe.rb."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_unnumbered_figure(book)
    d.bake_preface(book)
    d.bake_chapter_title(book)
    # BakeChapterIntroductions.v1: the chapter's outline first.
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    d.bake_autotitled_notes(book, [
        "are-you-ready", "what-can-do", "link-to-learning",
        "entrepreneur-in-action", "work-it-out"])
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_non_introduction_pages(book, chapter)
        d.bake_chapter_glossary(book, chapter)
        d.move_custom_section_to_eoc(book, chapter, "section-summary",
                                     "section-summary",
                                     each=d.titled_from_page(book))
        for key in ("review-questions", "discussion-questions",
                    "case-questions"):
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         each=d.remove_section_title)
            exercises = chapter.xpath(
                f".//section[{class_test(key)}]/descendant::div[@data-type='exercise']")
            for i, exercise in enumerate(exercises, 1):
                d.bake_numbered_exercise(book, exercise, i)
        d.move_custom_section_to_eoc(book, chapter, "suggested-resources",
                                     "suggested-resources",
                                     each=d.titled_from_page(book))
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            # BakeNumberedTable.v2: the same words as v1.
            d.bake_numbered_table(book, table, f"{n}.{i}")
    for i, page in enumerate(book.pages(cls="appendix")):
        d.bake_appendix(book, page, string.ascii_uppercase[i])
    d.bake_footnotes(book)
    d.bake_index(book)
    d.bake_link_placeholders(book)


def business_ethics(book):
    """lib/recipes/business-ethics/recipe.rb, for Business Ethics,
    Business Law I Essentials, and Introduction to Intellectual
    Property, whose selectors take a reference to be a section of class
    references. Its footnotes are numbered in roman numerals there;
    here they're Pandoc's notes, which TextbookImprover numbers."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_preface(book)
    d.bake_unnumbered_figure(book)
    d.bake_unclassified_notes(book)
    # BakeIframes: left to TextbookImprover.
    d.bake_chapter_title(book)
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    inj.add_injected_exercise_id(book)
    for exercise in book.body.xpath(".//div[@data-type='injected-exercise']"):
        inj.bake_injected_exercise(book, exercise)
    answer_key = d.book_answer_key_container(book, solutions_plural=False)
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_non_introduction_pages(book, chapter)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
        d.bake_chapter_glossary(book, chapter)
        d.move_custom_section_to_eoc(book, chapter, "section-summary",
                                     "section-summary",
                                     each=d.titled_from_page(book))
        d.move_custom_section_to_eoc(book, chapter, "assessment-questions",
                                     "assessment-questions",
                                     each=d.remove_section_title)
        d.bake_chapter_references_v2(book, chapter)
        within = chapter.xpath(".//div[@data-type='composite-page'] | "
                               ".//div[@data-type='page']")
        inj.bake_all_numbered_exercise_types(
            book, within, question_options={
                "answer_letter_upper": True,
                "prioritize_solution": "detailed",
                "answer_letter_only": True})
        inner = d.answer_key_inner_container(book, chapter, answer_key,
                                             solutions_plural=False)
        d.default_strategy_for_answer_key_solutions(
            book, chapter, ["assessment-questions"], inner)
        inner = d.answer_key_inner_container(book, chapter, answer_key)
        inj.move_solutions_from_exercise_section(book, chapter, inner,
                                                 "assessment-questions")
    d.bake_autotitled_notes(book, ["link-to-learning", "ethics-across",
                                   "real-world", "what-would"])
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        d.bake_appendix(book, page, letter)
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
    d.answer_key_cleaner(book)
    d.bake_footnotes(book)
    d.bake_index(book)
    d.bake_link_placeholders(book)


def accounting(book):
    """lib/recipes/accounting/recipe.rb, for Principles of Accounting,
    Volume 1: Financial Accounting and Volume 2: Managerial Accounting.
    An exercise in an exercise or problem set opens with its set's
    prefix ("EA1"); a link to a learning objective shows its section's
    number ("LO 3.1")."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_preface(book)
    d.bake_unnumbered_figure(book)
    d.bake_unnumbered_tables(book)
    answer_key = d.book_answer_key_container(book)
    d.bake_chapter_title(book)
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    eoc = ["multiple-choice", "questions", "exercise-set-a",
           "exercise-set-b", "problem-set-a", "problem-set-b",
           "thought-provokers"]
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_non_introduction_pages(book, chapter, custom_target_label=True)
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        d.bake_chapter_glossary(book, chapter)
        d.move_custom_section_to_eoc(book, chapter, "section-summary",
                                     "section-summary",
                                     each=d.titled_from_page(book))
        for key in eoc:
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         each=d.remove_section_title)
            for composite in chapter.xpath(
                    ".//div[@data-type='composite-page']"):
                exercises = composite.xpath(
                    f".//section[{class_test(key)}]"
                    "/descendant::div[@data-type='exercise']")
                for i, exercise in enumerate(exercises, 1):
                    d.bake_numbered_exercise(book, exercise, i)
        d.bake_exercise_prefixes(book, chapter, eoc[2:])
        inner = d.answer_key_inner_container(book, chapter, answer_key)
        for klass in ("multiple-choice", "questions"):
            inj.move_solutions_from_exercise_section(book, chapter, inner,
                                                     klass)
    d.bake_autotitled_notes(book, [
        "your-turn", "think-through", "concepts-practice",
        "continuing-application", "ethical-considerations",
        "ifrs-connection", "link-to-learning"])
    d.bake_stepwise(book)
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        d.bake_appendix(book, page, letter)
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
    d.bake_equations(book)
    d.bake_index(book)
    d.bake_footnotes(book)
    d.bake_link_placeholders(book)
    d.bake_lo_link_labels(book)


def finance(book):
    """lib/recipes/finance/recipe.rb, for Principles of Finance, whose
    selectors take a page's summary to be its section of class
    section-summary. Its questions are from OpenStax's exercise bank,
    their solutions kept with them."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_unnumbered_figure(book)
    d.bake_preface(book, title_element="h1")
    for page in book.pages(cls="preface"):
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, str(i))
    # BakeChapterIntroductions.v1: the chapter's outline first.
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    d.bake_chapter_title(book)
    d.bake_autotitled_notes(book, ["think-through", "link-to-learning",
                                   "concepts-practice"])
    d.bake_numbered_notes_v1(book, ["cfa-institute"])
    d.bake_custom_titled_notes(book, ["excel-spreadsheet"])
    eoc = ["multiple-choice", "review-questions", "problem-set",
           "video-activity"]
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_learning_objectives(book, chapter)
        d.bake_non_introduction_pages(book, chapter)
        d.bake_chapter_summary(book, chapter, klass="section-summary")
        d.bake_chapter_glossary(book, chapter)
        for klass in eoc:
            questions = [question for page in book.pages(chapter)
                         for question in page.xpath(
                             f".//section[{class_test(klass)}]"
                             "/descendant::div[@data-type='exercise-question']")]
            for i, question in enumerate(questions, 1):
                inj.bake_injected_exercise_question(book, question, i)
        d.move_custom_section_to_eoc(book, chapter, "cfa-institute",
                                     "cfa-institute",
                                     each=d.remove_section_title)
        d.move_custom_section_to_eoc(book, chapter, "sources-notes",
                                     "sources-notes",
                                     each=d.titled_from_page(book))
        for key in eoc:
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         each=d.remove_section_title)
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
        d.bake_appendix(book, page, letter)
    # BakeIframes: left to TextbookImprover.
    d.bake_equations(book)
    d.bake_stepwise(book)
    d.bake_unnumbered_tables(book)
    # BakeMathInParagraph: a wrapper for the stylesheet only.
    d.bake_index(book)
    d.bake_footnotes(book)
    d.bake_link_placeholders(book)


def bca(book):
    """lib/recipes/bca/recipe.rb, for Workplace Software and Skills. Its
    end-of-chapter pages are a group of their own in each chapter,
    "Chapter Review"; its questions are from OpenStax's exercise bank,
    one in parts lettered with capitals."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_preface(book)
    d.bake_unnumbered_figure(book)
    d.bake_chapter_title(book)
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    inj.add_injected_exercise_id(book)
    for exercise in book.body.xpath(".//div[@data-type='injected-exercise']"):
        inj.bake_injected_exercise(book, exercise,
                                   alphabetical_multiparts=True,
                                   list_type="upper-alpha")
    eoc = ["review-questions", "conceptual-questions", "you-try",
           "practice-exercises", "written-questions", "case-exercises",
           "extension-exercises"]
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_non_introduction_pages(book, chapter)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
        review = d.chapter_review_container(book, chapter)
        d.bake_chapter_glossary(book, chapter, append_to=review)
        d.move_custom_section_to_eoc(
            book, chapter, "section-summary", "section-summary",
            append_to=review, wrap_section=True, wrap_content=True,
            each=d.titled_from_page(book, title_tag="h4"))
        for key in eoc:
            # The sections' own sections' h4s are h5s there; emit.py sets
            # the levels here.
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         append_to=review,
                                         each=d.remove_section_title)
        questions = review.xpath(
            ".//div[@data-type='composite-page']/descendant::section["
            + " or ".join(class_test(key) for key in eoc)
            + "]/descendant::div[@data-type='exercise-question']")
        for i, question in enumerate(questions, 1):
            inj.bake_injected_exercise_question(book, question, i)
    d.bake_autotitled_notes(book, ["real-application", "spotlight-ethics",
                                   "link-to-learning"])
    d.bake_autotitled_notes(book, ["mac-tip"], bake_exercises=True)
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        d.bake_appendix(book, page, letter)
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
    # BakeIframes: left to TextbookImprover.
    d.bake_footnotes(book)
    d.bake_link_placeholders(book)
    d.bake_index(book)


def nursing_external(book):
    """lib/recipes/nursing-external/recipe.rb, for Pharmacology,
    Nutrition, and Population Health for Nurses, whose selectors take a
    reference to be a section of class references. Its questions are
    from OpenStax's exercise bank; a link to a section shows its number
    alone ("Section 3.1")."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_unnumbered_figure(book)
    d.bake_preface(book)
    inj.add_injected_exercise_id(book)
    for exercise in book.body.xpath(".//div[@data-type='injected-exercise']"):
        inj.bake_injected_exercise(book, exercise)
    answer_key = d.book_answer_key_container(book)
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_learning_objectives_v2(book, chapter, add_title=False)
        d.bake_non_introduction_pages(book, chapter)
        d.move_custom_section_to_eoc(book, chapter, "chapter-summary",
                                     "chapter-summary")
        d.move_custom_section_to_eoc(book, chapter, "section-summary",
                                     "section-summary",
                                     each=d.titled_from_page(book))
        d.bake_chapter_glossary(book, chapter)
        d.move_custom_section_to_eoc(book, chapter, "review-questions",
                                     "review-questions",
                                     each=d.remove_section_title)
        d.bake_sortable_section(book, chapter, "suggested-reading")
        questions = chapter.xpath(
            f".//section[{class_test('review-questions')}]"
            "/descendant::div[@data-type='exercise-question']")
        for i, question in enumerate(questions, 1):
            inj.bake_injected_exercise_question(book, question, i,
                                                add_dot=True)
        for klass in ("unfolding-casestudy", "single-casestudy"):
            questions = [q for page in book.pages(chapter)
                         for note in book.notes(page, klass)
                         for q in note.xpath(
                             ".//div[@data-type='exercise-question']")]
            for i, question in enumerate(questions, 1):
                inj.bake_injected_exercise_question(book, question, i,
                                                    add_dot=True)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
        inner = d.answer_key_inner_container(book, chapter, answer_key)
        for klass in ("unfolding-casestudy", "single-casestudy"):
            inj.move_solutions_from_numbered_note(book, chapter, inner, klass)
        inj.move_solutions_from_exercise_section(book, chapter, inner,
                                                 "review-questions")
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
        d.bake_appendix(book, page, letter)
    d.bake_unnumbered_tables(book)
    # BakeChapterIntroductions.v1: the chapter's outline first.
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    d.bake_chapter_title(book)
    d.bake_references_v4(book)
    # BakeIframes: left to TextbookImprover.
    d.bake_index(book)
    d.bake_link_placeholders(book, replace_section_link_text=True)
    d.bake_unit_title(book)
    d.bake_autotitled_notes(book, [
        "link-to-learning", "safety-alert", "clinical-tip", "health-alert",
        "healthy-people", "trending-today", "culture-conversations",
        "theory-action", "special-considerations", "black-box",
        "client-teaching", "practice-problems", "unfolding-casestudy",
        "single-casestudy", "case-reflection"])
    d.bake_custom_titled_notes(book, ["media-feature", "boxed-feature"])
    d.bake_unclassified_notes(book)
    d.bake_footnotes(book)


def neuroscience(book):
    """lib/recipes/neuroscience/recipe.rb, for Introduction to Behavioral
    Neuroscience. A chapter ends with its summaries, key terms,
    references, and questions, each page's under the page's title; the
    questions are from OpenStax's exercise bank, each kind numbered
    through the chapter, their answers in the answer key."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_unnumbered_figure(book)
    d.bake_preface(book)
    inj.add_injected_exercise_id(book)
    for exercise in book.body.xpath(".//div[@data-type='injected-exercise']"):
        inj.bake_injected_exercise(book, exercise)
    d.bake_unit_title(book)
    d.bake_chapter_title(book)
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True,
                                 introduction_order="v4")
    answer_key = d.book_answer_key_container(book)
    questions = ("multiple-choice", "fillin-blank")
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_non_introduction_pages(book, chapter)
        d.bake_learning_objectives_v2(book, chapter, add_title=False)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
        d.bake_chapter_glossary_v2(book, chapter)
        for key in ("section-summary", "key-terms", "references") + questions:
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         each=d.titled_from_page(book))
        for key in questions:
            # BakeFirstElements: classes for OpenStax's stylesheet.
            for i, question in enumerate(chapter.xpath(
                    f".//section[{class_test(key)}]"
                    "/descendant::div[@data-type='exercise-question']"), 1):
                inj.bake_injected_exercise_question(book, question, i)
        inner = d.answer_key_inner_container(book, chapter, answer_key)
        for key in questions:
            inj.move_solutions_from_exercise_section(book, chapter, inner,
                                                     key)
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
        d.bake_appendix(book, page, letter)
    d.bake_unnumbered_tables(book)
    # BakeTableColumns: column widths for OpenStax's stylesheet.
    # BakeIframes: left to TextbookImprover.
    d.bake_footnotes(book)
    d.bake_index(book)
    # BakeCompositePages and BakeCompositeChapters: ids for OpenStax's
    # reader.
    d.bake_link_placeholders(book)
    for note in book.notes(cls="developmental-perspective"):
        note.set("use-subtitle", "true")
    d.bake_autotitled_notes(book, ["meet-author", "developmental-perspective",
                                   "across-species", "inthe-lab"])
    d.bake_custom_titled_notes(book, ["boxed-feature"])


def nursing_internal(book):
    """lib/recipes/nursing-internal/recipe.rb, whose selectors take a
    reference to be a section of class references. A chapter's summaries
    and key terms follow it, then its assessments, then its references,
    sorted; its questions are from OpenStax's exercise bank, each kind
    numbered through the chapter, their answers in the answer key."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_preface(book)
    d.bake_unnumbered_figure(book)
    d.bake_unnumbered_tables(book)
    inj.add_injected_exercise_id(book)
    for exercise in book.body.xpath(".//div[@data-type='injected-exercise']"):
        inj.bake_injected_exercise(book, exercise)
    answer_key = d.book_answer_key_container(book)
    # BakeChapterIntroductions.v1 (its outline first).
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    d.bake_chapter_title(book)
    assessments = ("review-questions", "check-understanding",
                   "reflection-questions", "critical-thinking",
                   "what-nurses-do", "competency-based")
    notes = ("unfolding-casestudy", "electronic-hr")
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_learning_objectives(book, chapter)
        d.bake_non_introduction_pages(book, chapter)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
        d.move_custom_section_to_eoc(book, chapter, "summary", "summary",
                                     each=d.titled_from_page(book))
        d.bake_chapter_glossary(book, chapter)
        wrapper = d.chapter_review_container(book, chapter)
        for key in assessments:
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         append_to=wrapper,
                                         each=d.remove_section_title)
        # BakeChapterReferences.v3.
        d.bake_sortable_section(book, chapter, "references")
        # BakeFirstElements: classes for OpenStax's stylesheet.
        holders = [f"section[{class_test(key)}]" for key in (
            "review-questions", "check-understanding", "critical-thinking",
            "competency-based", "reflection-questions", "what-nurses-do")]
        holders += [f"div[@data-type='note'][{class_test(klass)}]"
                    for klass in notes]
        for holder in holders:
            for i, question in enumerate(chapter.xpath(
                    f".//{holder}/descendant::div"
                    "[@data-type='exercise-question']"), 1):
                inj.bake_injected_exercise_question(book, question, i)
        inner = d.answer_key_inner_container(book, chapter, answer_key)
        for klass in notes:
            inj.move_solutions_from_numbered_note(book, chapter, inner, klass)
        for key in assessments:
            inj.move_solutions_from_exercise_section(book, chapter, inner,
                                                     key)
    # BakeFirstElements on the questions' solutions: classes for
    # OpenStax's stylesheet.
    d.bake_autotitled_notes(book, [
        "link-to-learning", "unfolding-casestudy", "rn-stories",
        "clinical-safety", "cultural-context", "lifestage-context",
        "patient-conversations", "pharma-connections", "legal-ethical",
        "multi-disciplinary", "clinical-judgment", "electronic-hr",
        "psychosocial-considerations"])
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
        d.bake_appendix(book, page, letter)
    d.answer_key_cleaner(book)
    d.bake_unit_title(book)
    # BakeTableColumns: column widths for OpenStax's stylesheet.
    d.bake_index(book)
    # BakeCompositePages and BakeCompositeChapters: ids for OpenStax's
    # reader.
    d.bake_footnotes(book)
    d.bake_link_placeholders(book)


def organic_chemistry(book):
    """lib/recipes/organic-chemistry/recipe.rb, for Organic Chemistry. A
    chapter ends with its Chemistry Matters section, named for its title,
    then its key terms, key equations, summaries, and problems. The
    problems are from OpenStax's exercise bank, numbered through the
    chapter as "Problem 1-1", their parts lettered "(a)"; the answers to
    a section's problems, the Visualizing Chemistry and additional
    problems, and the preview of carbonyl chemistry are in the answer
    key."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_unnumbered_figure(book)
    d.bake_preface(book)
    inj.add_injected_exercise_id(book)
    for exercise in book.body.xpath(".//div[@data-type='injected-exercise']"):
        inj.bake_injected_exercise(book, exercise,
                                   alphabetical_multiparts=True,
                                   list_type="lower-alpha", add_brackets=True)
    answer_key = d.book_answer_key_container(book)
    problems = ("visualizing-chemistry", "mechanism-problems",
                "energy-reaction", "additional-problems", "general-problems")
    numbered = ("section-exercises",) + problems + (
        "preview-carbonylchemistry",)
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.move_custom_section_to_eoc(book, chapter, "chemistry-matters",
                                     "chemistry-matters")
        d.use_section_title(book, chapter, "os-chemistry-matters-container",
                            "chemistry-matters")
        d.move_custom_section_to_eoc(book, chapter, "key-terms", "key-terms")
        d.bake_chapter_key_equations(book, chapter)
        for key in ("summary", "summary-reactions"):
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         each=d.remove_section_title)
        for key in problems:
            d.move_exercises_to_eoc(book, chapter, key)
        d.bake_chapter_section_exercises(book, chapter, trash_title=True,
                                         create_title=False)
        d.move_custom_section_to_eoc(book, chapter, "practice-scientific",
                                     "practice-scientific",
                                     each=d.titled_from_page(book))
        d.move_custom_section_to_eoc(book, chapter,
                                     "preview-carbonylchemistry",
                                     "preview-carbonylchemistry",
                                     each=d.remove_section_title)
        # BakeFirstElements: classes for OpenStax's stylesheet.
        for i, question in enumerate(chapter.xpath(
                ".//section[" + " or ".join(class_test(k) for k in numbered)
                + "]/descendant::div[@data-type='exercise-question']"), 1):
            inj.bake_injected_exercise_question(book, question, f"{n}-{i}",
                                                problem_with_prefix=True)
        inner = d.answer_key_inner_container(book, chapter, answer_key)
        for page in book.non_introduction_pages(chapter):
            for wrapper in page.xpath(
                    f".//div[{class_test('os-eos')} and "
                    f"{class_test('os-section-exercises-container')}]"):
                inj.move_solutions_from_exercise_section(
                    book, wrapper, inner, "section-exercises",
                    add_title=False)
        for key in ("visualizing-chemistry", "additional-problems",
                    "preview-carbonylchemistry"):
            inj.move_solutions_from_exercise_section(book, chapter, inner,
                                                     key, add_title=False)
    # BakeChapterIntroductions.v1 (its outline first).
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    d.bake_chapter_title(book)
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_learning_objectives(book, chapter)
        d.bake_non_introduction_pages(book, chapter)
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}",
                                  move_caption_on_top=True,
                                  label_class="table-target-label")
        for i, example in enumerate(chapter.xpath(
                ".//div[@data-type='example']"), 1):
            d.bake_example(book, example, f"{n}.{i}", title_tag="h3")
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}",
                          label_class="figure-target-label")
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}",
                          label_class="figure-target-label")
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}",
                                  move_caption_on_top=True,
                                  label_class="table-target-label")
        for j, example in enumerate(page.xpath(
                ".//div[@data-type='example']"), 1):
            d.bake_example(book, example, f"{letter}{j}", title_tag="div")
        d.bake_appendix(book, page, letter, add_title_label=False)
    d.bake_unnumbered_tables(book)
    # BakeFirstElements on the questions' solutions: classes for
    # OpenStax's stylesheet.
    d.bake_autotitled_notes(book, ["why-chapter", "chemistry-matters"])
    d.bake_custom_titled_notes(book, ["dedication-page"])
    d.bake_unclassified_notes(book)
    d.bake_stepwise(book)
    # BakeMathInParagraph: a class for OpenStax's stylesheet.
    d.bake_index(book)
    d.bake_footnotes(book)
    # BakeCompositePages, BakeCompositeChapters, and BakeToc, with the
    # recipe's change to Chemistry Matters' line in the contents: ids
    # and contents for OpenStax's reader.
    d.bake_link_placeholders(book, replace_section_link_text=True)


def python(book):
    """lib/recipes/python/recipe.rb, for Introduction to Python
    Programming. Its code runners, files of the repository's whose code
    isn't under the book's license, are links to the online book (see
    cnxml.py's frame()). Its code isn't highlighted here
    (BakeHighlightedCode): that's markup for OpenStax's stylesheet."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_preface(book)
    d.bake_unnumbered_figure(book)
    d.bake_unclassified_notes(book)
    # BakeIframes: left to TextbookImprover.
    d.bake_unnumbered_tables(book)
    inj.add_injected_exercise_id(book)
    for exercise in book.body.xpath(".//div[@data-type='injected-exercise']"):
        inj.bake_injected_exercise(book, exercise)
    d.bake_autotitled_notes(book, ["guided-slides", "learning-questions",
                                   "practice-program"])
    answer_key = d.book_answer_key_container(book)
    d.bake_chapter_title(book)
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_non_introduction_pages(book, chapter)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
        examples = chapter.xpath(".//div[@data-type='example']")
        for i, example in enumerate(examples, 1):
            d.bake_example(book, example, f"{n}.{i}", title_tag="h3")
        for page in book.pages(chapter):
            questions = [q for note in book.notes(page, "learning-questions")
                         for q in note.xpath(
                             ".//div[@data-type='exercise-question']")]
            for i, question in enumerate(questions, 1):
                inj.bake_injected_exercise_question(book, question, i,
                                                    add_dot=True)
        inner = d.answer_key_inner_container(book, chapter, answer_key)
        for page in book.non_introduction_pages(chapter):
            inj.move_solutions_from_autotitled_note(
                book, page, inner, "learning-questions",
                title=book.page_title(page))
    d.bake_footnotes(book)
    d.bake_index(book)
    d.bake_link_placeholders(book)


def additive_manufacturing(book):
    """lib/recipes/additive-manufacturing/recipe.rb, for Additive
    Manufacturing Essentials. Its key terms are an inline list, given
    commas; its questions are from OpenStax's exercise bank, numbered
    through each chapter's end-of-chapter pages, their answers left with
    them, as the recipe builds no answer key."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_unnumbered_figure(book)
    d.bake_preface(book)
    d.bake_chapter_title(book)
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    d.bake_unclassified_notes(book, bake_exercises=True)
    inj.add_injected_exercise_id(book)
    eoc = ["summary", "review-questions", "free-response", "practice"]
    asked = ["review-questions", "practice", "free-response"]
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_non_introduction_pages(book, chapter)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
        d.bake_chapter_glossary_v2(book, chapter)
        for key in eoc:
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         each=d.remove_section_title)
        d.move_custom_section_to_eoc(book, chapter, "key-terms", "key-terms",
                                     each=d.titled_from_page(book))
        questions = chapter.xpath(
            ".//div[@data-type='composite-page']/descendant::section["
            + " or ".join(class_test(key) for key in asked)
            + "]/descendant::div[@data-type='exercise-question']")
        for i, question in enumerate(questions, 1):
            inj.bake_injected_exercise_question(book, question, i)
    d.bake_footnotes(book)
    d.bake_index(book)
    d.bake_link_placeholders(book)


def _precalculus_shared(book):
    """lib/recipes/precalculus/shared.rb, which bakes College Algebra,
    Algebra and Trigonometry, Precalculus, and (followed by the coreq
    recipe) College Algebra with Corequisite Support. Its figures,
    tables, and examples are numbered in their page ("Example 3"), its
    exercises too, and in its chapter at its end; its Try It notes are
    numbered in their page, their solutions in the answer key. Its
    screen reader spans aren't made (text that would show here), nor
    its inline lists' separators (written as the source is read)."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    for section in book.body.xpath(
            f".//section[{class_test('coreq-skills')}]"):
        for el in (book.tables(section) + book.figures(section)
                   + section.xpath(".//div[@data-type='example']")):
            add_class(el, "os-coreq-element")
    d.bake_preface(book)
    # BakeChapterIntroductions.v1: the chapter's outline first.
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    d.bake_chapter_title(book)
    for chapter in book.chapters():
        d.bake_learning_objectives(book, chapter)
        d.bake_non_introduction_pages(book, chapter)
    d.bake_autotitled_notes(book, ["how-to-notitle", "qa", "media-notitle"])
    d.bake_unclassified_notes(book)
    d.bake_numbered_notes_v2(book, ["try"])
    for chapter in book.chapters():
        review = d.chapter_review_container(book, chapter)
        d.bake_chapter_glossary(book, chapter, append_to=review)
        d.bake_chapter_key_equations(book, chapter, append_to=review)
        d.bake_chapter_key_concepts(book, chapter, append_to=review)
        exercises = d.chapter_review_container(book, chapter,
                                               klass="exercises")
        for klass in ("review-exercises", "practice-test"):
            # The sections' own sections' h4s are h5s there; emit.py sets
            # the levels here.
            d.move_custom_section_to_eoc(book, chapter, klass, klass,
                                         append_to=exercises,
                                         each=d.remove_section_title)
        d.bake_chapter_section_exercises(book, chapter, trash_title=True)
        for klass in ("review-exercises", "practice-test"):
            found = chapter.xpath(f".//section[{class_test(klass)}]"
                                  "/descendant::div[@data-type='exercise']")
            for i, exercise in enumerate(found, 1):
                d.bake_numbered_exercise(book, exercise, i)
        for page in book.pages(chapter):
            found = page.xpath(
                f".//section[{class_test('section-exercises')}]"
                "/descendant::div[@data-type='exercise']")
            for i, exercise in enumerate(found, 1):
                d.bake_numbered_exercise(book, exercise, i)
    # A table in a Try It's solution or a section's or review's exercises'
    # goes unnumbered. (Walked, not found by one XPath: libxml2 merges the
    # node sets of a//b//c in quadratic time, minutes for a book.)
    for table in book.body.iter("table"):
        in_solution = False
        for ancestor in table.iterancestors():
            if ancestor.get("data-type") == "solution":
                in_solution = True
            elif in_solution and (
                    (ancestor.get("data-type") == "note"
                     and has_class(ancestor, "try"))
                    or (ancestor.tag == "section"
                        and (has_class(ancestor, "section-exercises")
                             or has_class(ancestor, "review-exercises")))):
                add_class(table, "unnumbered")
                break
    for page in book.pages():
        if has_class(page, "appendix"):
            continue
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")
                  and not has_class(t, "os-coreq-element")]
        for i, table in enumerate(tables, 1):
            # BakeNumberedTable.v2, which keeps a caption's title in the
            # caption's span: the same words in the same order.
            d.bake_numbered_table(book, table, str(i))
        figures = [f for f in book.figures(page)
                   if not has_class(f, "os-coreq-element")
                   and figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, str(i))
        examples = [e for e in page.xpath(".//div[@data-type='example']")
                    if not has_class(e, "os-coreq-element")]
        for i, example in enumerate(examples, 1):
            d.bake_example(book, example, str(i), title_tag="h3")
    d.bake_unnumbered_figure(book)
    for page in book.body.xpath(".//div[@data-type='composite-page']"):
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, str(i))
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, str(i))
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        d.bake_appendix(book, page, letter)
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
    d.bake_unnumbered_tables(book)
    answer_key = d.book_answer_key_container(book, solutions_plural=False)
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        inner = d.answer_key_inner_container(book, chapter, answer_key,
                                             solutions_plural=False)
        inj.move_solutions_from_autotitled_note_v2(book, chapter, inner,
                                                   "try")
        for p, page in enumerate(book.non_introduction_pages(chapter), 1):
            inj.move_solutions_from_exercise_section(
                book, page, inner, "section-exercises",
                title_number=f"{n}.{p}")
        for klass in ("review-exercises", "practice-test"):
            inj.move_solutions_from_exercise_section(book, chapter, inner,
                                                     klass)
    d.bake_equations(book)
    d.bake_index(book)
    d.bake_footnotes(book)
    d.bake_stepwise(book)
    d.bake_link_placeholders(book)


def precalculus(book):
    """lib/recipes/precalculus/recipe.rb and then shared.rb: the
    corequisite book's sections taken out first."""
    for section in book.body.xpath(
            f".//section[{class_test('practice-perfect')} or "
            f"{class_test('coreq-skills')}]"):
        d.trash(section)
    _precalculus_shared(book)


def precalculus_coreq(book):
    """shared.rb and then lib/recipes/precalculus-coreq/recipe.rb, for
    College Algebra with Corequisite Support: its Practice Makes Perfect
    exercises numbered in their page, their solutions kept there, and
    its Corequisite Skills sections titled, their tables, figures, and
    examples numbered in their page apart from the rest."""
    _precalculus_shared(book)
    for chapter in book.chapters():
        for page in book.pages(chapter):
            found = page.xpath(
                f".//section[{class_test('practice-perfect')}]"
                "/descendant::div[@data-type='exercise']")
            for i, exercise in enumerate(found, 1):
                remove_class(exercise, "material-set-2")
                add_class(exercise, "os-coreq-exercises")
                d.bake_numbered_exercise(book, exercise, i)
                for table in exercise.xpath(".//table"):
                    add_class(table, "os-coreq-element")
    for page in book.pages():
        sections = page.xpath(f".//section[{class_test('coreq-skills')}]")
        tables, figures, examples = [], [], []
        for section in sections:
            heading = E("h3", {"class": "os-title"})
            heading.append(span("os-title-label", book.t("coreq-skills")))
            prepend(section, heading)
            tables += [t for t in book.tables(section)
                       if not has_class(t, "unnumbered")]
            figures += [f for f in book.figures(section)
                        if figure_to_number(f)]
            examples += section.xpath(".//div[@data-type='example']")
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, str(i))
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, str(i))
        for i, example in enumerate(examples, 1):
            d.bake_example(book, example, str(i), title_tag="h3")


def calculus(book):
    """lib/recipes/calculus/recipe.rb, for Calculus Volumes 1, 2, and 3.
    A chapter's exercises are numbered through it, the review's after
    the sections'; its figures, tables, examples, and equations in it,
    an equation's number in parentheses; its theorems and checkpoints
    numbered in it, the checkpoints' solutions in the answer key."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_unnumbered_figure(book)
    d.bake_preface(book)
    d.bake_unclassified_notes(book)
    for note in book.notes(cls="theorem"):
        note.set("use-subtitle", "true")
    d.bake_autotitled_notes(book, ["media-2", "problem-solving", "project"])
    d.bake_numbered_notes_v1(book, ["theorem", "checkpoint"])
    for chapter in book.chapters():
        review = d.chapter_review_container(book, chapter)
        d.bake_chapter_glossary(book, chapter, append_to=review)
        d.bake_chapter_key_equations(book, chapter, append_to=review)
        d.bake_chapter_key_concepts(book, chapter, append_to=review)
        d.move_exercises_to_eoc(book, chapter, "review-exercises",
                                append_to=review)
        d.bake_chapter_section_exercises(book, chapter)
        found = chapter.xpath(
            f".//section[{class_test('section-exercises')} or "
            f"{class_test('review-exercises')}]/descendant::div[@data-type='exercise']")
        for i, exercise in enumerate(found, 1):
            d.bake_numbered_exercise(book, exercise, i)
    # BakeChapterIntroductions.v1: the chapter's outline first.
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    d.bake_chapter_title(book)
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
        for i, example in enumerate(
                chapter.xpath(".//div[@data-type='example']"), 1):
            d.bake_example(book, example, f"{n}.{i}", title_tag="h3")
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        d.bake_non_introduction_pages(book, chapter)
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
        for j, example in enumerate(
                page.xpath(".//div[@data-type='example']"), 1):
            d.bake_example(book, example, f"{letter}{j}", title_tag="div")
        d.bake_appendix(book, page, letter)
    answer_key = d.book_answer_key_container(book)
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        inner = d.answer_key_inner_container(book, chapter, answer_key)
        inj.move_solutions_from_autotitled_note(
            book, chapter, inner, "checkpoint",
            title=book.t("notes.checkpoint"))
        sections = chapter.xpath(
            f".//section[{class_test('section-exercises')}]")
        for k, section in enumerate(sections, 1):
            inj.move_solutions_from_exercise_section(
                book, section, inner, "section-exercises",
                title_number=f"{n}.{k}")
        inj.move_solutions_from_exercise_section(book, chapter, inner,
                                                 "review-exercises")
    d.bake_stepwise(book)
    d.bake_unnumbered_tables(book)
    d.bake_index(book)
    d.bake_footnotes(book)
    d.bake_equations(book, decorator="parentheses")
    for chapter in book.chapters():
        d.bake_learning_objectives_v2(book, chapter)
    d.bake_link_placeholders(book)


def _first_example_solution_title(example):
    """The title dev-math's recipe takes out of an example's first
    solution: the first one there that BakeExample renamed h4, which is
    any not in a caption, a note, or an exercise as its child."""
    containers = example.xpath(
        f".//div[{class_test('os-solution-container')}]")
    if not containers:
        return None
    for el in containers[0].iterdescendants():
        if not isinstance(el.tag, str) or el.get("data-type") != "title":
            continue
        parent = el.getparent()
        if parent.tag == "caption" or has_class(parent, "os-caption") or \
                has_class(parent, "os-caption-container") or \
                parent.get("data-type") in ("note", "exercise"):
            continue
        return el
    return None


def dev_math(book):
    """lib/recipes/dev-math/recipe.rb, for Prealgebra, Elementary
    Algebra, and Intermediate Algebra. A chapter's exercises are
    numbered through it, sections', review's, and practice test's;
    its figures, tables, and examples in it; its Be Prepared and Try It
    notes in it too, their solutions in the answer key."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_unnumbered_figure(book)
    d.bake_preface(book)
    d.bake_chapter_title(book)
    # BakeChapterIntroductions.v1: the chapter's outline first.
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    d.bake_unclassified_notes(book)
    d.bake_numbered_notes_v1(book, ["try", "be-prepared"])
    d.bake_autotitled_notes(book, ["manipulative-math", "howto", "media-2",
                                   "links-to-literacy"])
    answer_key = d.book_answer_key_container(book)
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_learning_objectives(book, chapter)
        d.bake_non_introduction_pages(book, chapter)
        review = d.chapter_review_container(book, chapter)
        exercises = d.chapter_review_container(book, chapter,
                                               klass="exercises")
        d.bake_chapter_glossary(book, chapter, append_to=review)
        d.move_custom_section_to_eoc(
            book, chapter, "key-concepts", "key-concepts", append_to=review,
            wrap_section=True, wrap_content=True,
            each=d.titled_from_page(book, title_tag="h4"))
        # ChangeSubsectionTitleTag: heading levels, which emit.py sets.
        d.move_custom_section_to_eoc(book, chapter, "review-exercises",
                                     "review-exercises", append_to=exercises,
                                     each=d.remove_section_title)
        d.move_exercises_to_eoc(book, chapter, "practice-test",
                                append_to=exercises)
        found = chapter.xpath(
            f".//section[{class_test('section-exercises')} or "
            f"{class_test('review-exercises')} or "
            f"{class_test('practice-test')}]/descendant::div[@data-type='exercise']")
        for i, exercise in enumerate(found, 1):
            d.bake_numbered_exercise(book, exercise, i)
        d.bake_chapter_section_exercises(book, chapter)
        for section in chapter.xpath(
                f".//section[{class_test('section-exercises')}]"):
            titles = section.xpath("./h3[@data-type='title']")
            if titles:
                d.trash(titles[0])
        inner = d.answer_key_inner_container(book, chapter, answer_key)
        inj.move_solutions_from_numbered_note(book, chapter, inner,
                                              "be-prepared")
        inj.move_solutions_from_numbered_note(book, chapter, inner, "try")
        for p, page in enumerate(book.non_introduction_pages(chapter), 1):
            inj.move_solutions_from_exercise_section(
                book, page, inner, "section-exercises",
                title_number=f"{n}.{p}")
        for klass in ("review-exercises", "practice-test"):
            inj.move_solutions_from_exercise_section(book, chapter, inner,
                                                     klass)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        for i, example in enumerate(
                chapter.xpath(".//div[@data-type='example']"), 1):
            d.bake_example(book, example, f"{n}.{i}", title_tag="h3")
            title = _first_example_solution_title(example)
            if title is not None:
                d.trash(title)
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        d.bake_appendix(book, page, letter)
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
    d.bake_unnumbered_tables(book)
    d.bake_stepwise(book)
    d.bake_equations(book)
    d.bake_index(book)
    d.bake_link_placeholders(book)


def contemporary_math(book):
    """lib/recipes/contemporary-math/recipe.rb, for Contemporary
    Mathematics, whose questions are from OpenStax's exercise bank:
    numbered in a chapter's Check Your Understanding, its review, and
    its test, in a page's exercises, and in a Your Turn note; their
    solutions in the answer key."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_preface(book)
    # BakeChapterIntroductions.v1: the chapter's outline first.
    d.bake_chapter_introductions(book, strategy="add_objectives",
                                 bake_chapter_outline=True)
    d.bake_chapter_title(book)
    inj.add_injected_exercise_id(book)
    d.bake_unclassified_notes(book)
    d.bake_autotitled_notes(book, [
        "people-mathematics", "who-knew", "tech-check", "check-point",
        "video", "work-out", "definition", "formula"])
    d.bake_numbered_notes_v1(book, ["your-turn"], bake_exercises=False)
    holders = book.body.xpath(
        f".//div[@data-type='note'][{class_test('your-turn')}]"
        f" | .//section[{class_test('section-exercises')} or "
        f"{class_test('chapter-review')} or {class_test('chapter-test')}]")
    seen = set()
    for holder in holders:
        for solution in holder.xpath(
                ".//div[@data-type='solution' or "
                "@data-type='question-solution']"):
            if solution in seen:
                continue
            seen.add(solution)
            for el in book.tables(solution) + book.figures(solution):
                add_class(el, "unnumbered")
    d.bake_unnumbered_figure(book)
    d.bake_unnumbered_tables(book)
    for exercise in book.body.xpath(".//div[@data-type='injected-exercise']"):
        inj.bake_injected_exercise(book, exercise)
    answer_key = d.book_answer_key_container(book)
    question = "/descendant::div[@data-type='exercise-question']"
    for chapter in book.chapters():
        n = book.chapter_number(chapter)
        d.bake_learning_objectives(book, chapter)
        d.bake_non_introduction_pages(book, chapter)
        d.bake_chapter_section_exercises(book, chapter, trash_title=True)
        for klass in ("check-understanding",):
            found = chapter.xpath(f".//section[{class_test(klass)}]"
                                  + question)
            for i, q in enumerate(found, 1):
                inj.bake_injected_exercise_question(book, q, i)
        for page in book.pages(chapter):
            found = page.xpath(
                f".//section[{class_test('section-exercises')}]" + question)
            for i, q in enumerate(found, 1):
                inj.bake_injected_exercise_question(book, q, i)
        for klass in ("chapter-review", "chapter-test"):
            found = chapter.xpath(f".//section[{class_test(klass)}]"
                                  + question)
            for i, q in enumerate(found, 1):
                inj.bake_injected_exercise_question(book, q, i)
        for note in book.notes(chapter, "your-turn"):
            found = note.xpath("." + question)
            for i, q in enumerate(found, 1):
                inj.bake_injected_exercise_question(book, q, i)
        summary = d.chapter_review_container(book, chapter,
                                             klass="chapter-summary")
        for key in ("key-terms", "key-concepts", "eoc-videos",
                    "formula-review"):
            d.move_custom_section_to_eoc(
                book, chapter, key, key, append_to=summary,
                wrap_section=True, wrap_content=True,
                each=d.titled_from_page(book))
        d.move_custom_section_to_eoc(book, chapter, "projects", "projects",
                                     append_to=summary,
                                     each=d.remove_section_title)
        # ChangeSubsectionTitleTag: heading levels, which emit.py sets.
        for key in ("chapter-review", "chapter-test"):
            d.move_custom_section_to_eoc(book, chapter, key, key,
                                         append_to=summary,
                                         each=d.remove_section_title)
        figures = [f for f in book.figures(chapter) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{n}.{i}")
        tables = [t for t in book.tables(chapter)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{n}.{i}")
        for i, example in enumerate(
                chapter.xpath(".//div[@data-type='example']"), 1):
            d.bake_example(book, example, f"{n}.{i}", title_tag="h3")
        inner = d.answer_key_inner_container(book, chapter, answer_key)
        inj.move_solutions_from_numbered_note_v2(book, chapter, inner,
                                                 "your-turn")
        for p, page in enumerate(book.non_introduction_pages(chapter), 1):
            inj.move_solutions_from_exercise_section(
                book, page, inner, "section-exercises",
                title_number=f"{n}.{p}")
        for klass in ("chapter-review", "chapter-test",
                      "check-understanding"):
            inj.move_solutions_from_exercise_section(book, chapter, inner,
                                                     klass)
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
        for j, example in enumerate(
                page.xpath(".//div[@data-type='example']"), 1):
            d.bake_example(book, example, f"{letter}{j}", title_tag="h3")
        d.bake_appendix(book, page, letter)
    # BakeIframes: left to TextbookImprover.
    d.bake_equations(book)
    d.bake_index(book)
    d.bake_link_placeholders(book)


def _title_text(title):
    """Cookbook's title_text: a title's text, or its os-text's once
    baking has numbered it."""
    kids = [k for k in title if isinstance(k.tag, str)]
    if not kids:
        return text_of(title)
    texts = title.xpath(f".//*[{class_test('os-text')}]")
    return text_of(texts[0]) if texts else text_of(title)


def algebra_1(book):
    """lib/recipes/algebra-1/recipe.rb, for Algebra 1: units of lessons
    (chapters, "Lesson 1.2"), a lesson's pages numbered from its
    overview, 1.2.0. The units that open and close the book (Getting
    Started, Supporting All Learners, Research in Practice) and a unit's
    first lesson, its overview, and its projects go unnumbered, and the
    lessons after them are numbered as if they weren't there.

    Kitchen counts an element among those the search that found it
    found, so a lesson's number counts the numbered units and lessons
    only, and the units and lessons that go unnumbered are counted among
    themselves; that's done here with the lists the recipe searches."""
    unnumbered_units, unnumbered_chapters = set(), set()
    units = book.units()

    def chapters_of(unit):
        return unit.xpath(".//div[@data-type='chapter']")

    for unit in units:
        title = text_of(book.page_title(unit))
        if any(words in title for words in (
                "Getting Started", "Supporting All Learners",
                "Research in Practice")):
            unnumbered_units.add(unit)
            unnumbered_chapters.update(chapters_of(unit))
        else:
            for i, chapter in enumerate(chapters_of(unit)):
                title = text_of(book.page_title(chapter))
                if i == 0 or "Overview and Readiness" in title \
                        or "Project" in title:
                    unnumbered_chapters.add(chapter)
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_unnumbered_figure(book)
    d.bake_unclassified_notes(book)
    # BakeIframes: left to TextbookImprover.
    inj.add_injected_exercise_id(book)
    for exercise in book.body.xpath(".//div[@data-type='injected-exercise']"):
        inj.bake_injected_exercise(book, exercise)
    d.bake_autotitled_notes(book, [
        "chapter-objectives", "general-strategies", "link-to-learning",
        "mini-lesson-question", "self-check", "try"], bake_subtitle=True)
    d.bake_custom_titled_notes(book, ["document"])
    skipped_units = len(unnumbered_units) - 1
    unit_place = {unit: i for i, unit in enumerate(units, 1)}
    for unit in units:
        chapters = chapters_of(unit)
        skipped = len([c for c in chapters if c in unnumbered_chapters]) - 1
        place = {chapter: i for i, chapter in enumerate(chapters, 1)}
        d.bake_chapter_title(
            book, chapters,
            lambda chapter, u=unit_place[unit], p=place, s=skipped:
                f"{u - skipped_units}.{p[chapter] - s}")
    # The chapters of each kind, as the recipe searches them; a numbered
    # one's number counts the numbered units and lessons alone, an
    # unnumbered one's the unnumbered lessons alone.
    numbered = []
    for u, unit in enumerate(
            [u for u in units if u not in unnumbered_units], 1):
        lessons = [c for c in chapters_of(unit)
                   if c not in unnumbered_chapters]
        numbered.extend((chapter, f"{u}.{c}")
                        for c, chapter in enumerate(lessons, 1))
    unnumbered = [(chapter, str(c)) for c, chapter in enumerate(
        [c for c in book.chapters() if c in unnumbered_chapters], 1)]
    for chapter, _ in numbered:
        d.move_custom_section_to_eoc(book, chapter, "key-terms", "key-terms")
    for kind in (unnumbered, numbered):
        for place, (chapter, prefix) in enumerate(kind, 1):

            # page_offset: -1, which numbers whatever the chapter holds
            # from 0, its first page an overview.
            def number(i, prefix=prefix):
                return f"{prefix}.{i - 1}"

            tables = [t for t in book.tables(chapter)
                      if not has_class(t, "unnumbered")]
            for i, table in enumerate(tables, 1):
                d.bake_numbered_table(book, table, number(i))
            examples = chapter.xpath(".//div[@data-type='example']")
            for i, example in enumerate(examples, 1):
                d.bake_example(book, example, number(i), title_tag="h3")
            figures = [f for f in book.figures(chapter)
                       if figure_to_number(f)]
            for i, figure in enumerate(figures, 1):
                d.bake_figure(book, figure, number(i))
            pages = book.pages(chapter)
            for test in (f"section[{class_test('practice')}]",
                         f"div[@data-type='note'][{class_test('mini-lesson-question')}]",
                         f"div[@data-type='note'][{class_test('mini-lesson-review')}]",
                         f"div[@data-type='note'][{class_test('self-check')}]"):
                for page in pages:
                    for holder in page.xpath(".//" + test):
                        questions = holder.xpath(
                            ".//div[@data-type='exercise-question']")
                        for i, question in enumerate(questions, 1):
                            inj.bake_injected_exercise_question(
                                book, question, i, only_number_solution=True)
                            # BakeFirstElements: classes for OpenStax's
                            # stylesheet.
            for page in pages:
                sections = page.xpath(
                    f".//section[{class_test('numbered-exercises')}]")
                for section in reversed(sections):
                    exercises = [e for e in section.xpath(
                        ".//div[@data-type='exercise']")
                        if not has_class(e, "unnumbered")]
                    for i, exercise in enumerate(exercises, 1):
                        if exercise.xpath(
                                f".//div[{class_test('os-problem-container')}]"):
                            continue
                        d.bake_numbered_exercise(
                            book, exercise, i, solution_stays_put=True,
                            suppress_solution_title=True,
                            chapter_number=place)
            numbers = {page: number(i) for i, page in
                       enumerate(book.non_introduction_pages(chapter), 1)}
            d.bake_non_introduction_pages(book, chapter,
                                          number_of=numbers.get)
    for i, page in enumerate(book.pages(cls="appendix")):
        letter = string.ascii_uppercase[i]
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for j, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, f"{letter}{j}")
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for j, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, f"{letter}{j}")
        for j, example in enumerate(
                page.xpath(".//div[@data-type='example']"), 1):
            d.bake_example(book, example, f"{letter}{j}", title_tag="div")
        d.bake_appendix(book, page, letter)
    d.bake_stepwise(book)
    d.bake_unnumbered_tables(book)
    # BakeFirstElements and BakeMathInParagraph: classes and wrappers for
    # OpenStax's stylesheet.
    d.bake_index(book)
    # BakeCompositePages and BakeCompositeChapters: ids for OpenStax's
    # reader.
    d.bake_footnotes(book)
    # A unit is numbered as OpenStax's table of contents numbers it
    # (BakeToc, "Unit 1"), where BakeUnitTitle counts the unnumbered
    # units before it too ("Unit 3"); the contents are what a reader of
    # OpenStax's book sees.
    d.bake_unit_title(book, number_of=lambda unit: str(
        unit_place[unit] - skipped_units))
    d.bake_unit_page_title(book)
    # Titles without numbers: the unnumbered units and their pages, the
    # unnumbered lessons and their pages, and a unit's closing page.
    plain = [book.page_title(u) for u in units if u in unnumbered_units]
    plain += [book.page_title(p) for u in units if u in unnumbered_units
              for p in book.pages(u) if not book.is_introduction(p)]
    plain += [book.page_title(c) for c in book.chapters()
              if c in unnumbered_chapters]
    plain += [book.page_title(p) for c in book.chapters()
              if c in unnumbered_chapters for p in book.pages(c)]
    plain += [book.page_title(p) for p in book.pages(cls="unit-closer")]
    done = set()
    for title in plain:
        if title is None or title in done:
            continue
        done.add(title)
        text = _title_text(title)
        for child in list(title):
            title.remove(child)
        title.text = None
        title.append(span("os-text", text))
    # BakeToc: TextbookImprover's.
    d.bake_equations(book, decorator="parentheses")
    # BakeFolio: running heads for print.
    for chapter in book.chapters():
        d.bake_learning_objectives_v2(book, chapter)
    # BakeRexWrappers and BakeLinks: attributes for OpenStax's reader.
    d.bake_link_placeholders(book)


def generic(book):
    """For a book no recipe here knows: numbers within each page, as the
    Connexions archive's books had them, and nothing moved."""
    for pi in book.body.xpath(".//cnx-pi"):
        d.trash(pi)
    d.bake_unnumbered_figure(book)
    d.bake_unclassified_notes(book)
    for page in book.pages():
        figures = [f for f in book.figures(page) if figure_to_number(f)]
        for i, figure in enumerate(figures, 1):
            d.bake_figure(book, figure, str(i))
        tables = [t for t in book.tables(page)
                  if not has_class(t, "unnumbered")]
        for i, table in enumerate(tables, 1):
            d.bake_numbered_table(book, table, str(i))
    d.bake_unnumbered_tables(book)
    d.bake_footnotes(book)
    d.bake_link_placeholders(book)


RECIPES = {
    "additive-manufacturing": additive_manufacturing,
    "accounting": accounting,
    "algebra-1": algebra_1,
    "american-government": american_government,
    "anatomy": anatomy,
    "anthropology": anthropology,
    "ap-biology": ap_biology,
    "ap-history": ap_history,
    "ap-physics": ap_physics,
    "ap-physics-2e": ap_physics,
    "astronomy": astronomy,
    "bca": bca,
    "biology": biology,
    "calculus": calculus,
    "chemistry": chemistry,
    "college-physics": college_physics,
    "college-physics-2e": college_physics_2e,
    "college-success": college_success,
    "computer-science": computer_science,
    "business-ethics": business_ethics,
    "contemporary-math": contemporary_math,
    "data-science": data_science,
    "dev-math": dev_math,
    "economics": economics,
    "english-composition": english_composition,
    "entrepreneurship": entrepreneurship,
    "finance": finance,
    "history": history,
    "hs-physics": hs_physics,
    "hs-college-success": hs_college_success,
    "information-systems": information_systems,
    "intro-business": intro_business,
    "lifespan-development": lifespan_development,
    "marketing": marketing,
    "microbiology": microbiology,
    "neuroscience": neuroscience,
    "nursing-external": nursing_external,
    "nursing-internal": nursing_internal,
    "organic-chemistry": organic_chemistry,
    "otto-book": chemistry,
    "philosophy": philosophy,
    "pl-economics": pl_economics,
    "pl-marketing": pl_marketing,
    "pl-nursing": pl_nursing,
    "pl-psychology": pl_psychology,
    "pl-u-physics": pl_u_physics,
    "political-science": political_science,
    "precalculus": precalculus,
    "precalculus-coreq": precalculus_coreq,
    "principles-management": principles_management,
    "psychology": psychology,
    "python": python,
    "sociology": sociology,
    "statistics": statistics,
    "u-physics": u_physics,
    "world-history": world_history,
}


def bake(body, style, language="en"):
    """Bake the assembled book in place, its strings in its language
    (English, or Polish where cookbook has Polish ones). Returns the
    Book, whose labels pages.py uses for links baking didn't name."""
    recipe = RECIPES.get(style)
    book = Book(body, for_style(style if recipe else "", language), style,
                language)
    (recipe or generic)(book)
    if recipe:
        # Cookbook's post_bake, which follows every recipe.
        d.convert_textual_links(book.body)
    return book
