"""
cnx.bake.strings -- the words baking writes into a book: "Figure",
"Answer Key", a note's title, an end-of-chapter page's title.

These are openstax/cookbook's English, Polish, and Spanish locale
strings (lib/locales/en.yml, pl.yml, and es.yml, and each recipe's
locales/en.yml, pl.yml, or es.yml), the ones the ported recipes use,
kept as they are there so a book reads as OpenStax's does. Copyright (c) 2020 Rice University, under
the MIT License, whose text is in lib/cnx/LICENSE-cookbook.txt.

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

import copy

# lib/locales/en.yml, the strings the ported directions use.
COMMON = {
    "figure": "Figure",
    "table": "Table",
    "appendix": "Appendix",
    "preface": "Preface",
    "solution": "Solution",
    "problem": "Problem",
    "section": "Section",
    "chapter_outline": "Chapter Outline",
    "example": "Example",
    "exercise": "Exercise",
    "equation": "Equation",
    "chapter": "Chapter",
    "unit": "Unit",
    "learning_objectives": "Learning Objectives",
    "references": "References",
    "answer_key_title": "Answer Key",
    "eoc_solutions_title": "Solutions",
    "eob_index_symbols_group": "Symbols",
    "context_lead_text": "Refer to ",
    "eoc_suggested_reading": "Suggestions for Further Study",
    "handbook_outline_title": "Outline",
    "stepwise_step_label": "Step",
    "lo_label_text": "LO ",
    "section_exercises": "Section %{number} Exercises",
    "eoc": {
        "glossary": "Key Terms",
        "key-equations": "Key Equations",
        "summary": "Summary",
        "further-research": "Further Research",
        "key-concepts": "Key Concepts",
        "references": "References",
        "solutions": "Solutions",
        "section-exercises": "Section %{number} Exercises",
    },
    "eob": {
        "references": "References",
        "reference": "References",
    },
    "index": {
        "main": "Index",
    },
    # The attribution OpenStax asks every page of a copy to carry, its
    # license page's words, which cnx.project makes the footer.
    "folio": {
        "access_for_free": "Access for free at openstax.org",
    },
}

# Each recipe's locales/en.yml.
BY_STYLE = {
    "algebra-1": {
        "chapter": "Lesson",
        "eoc": {
            "chapter-review": "Chapter Review",
            "key-terms": "Key Terms",
        },
        "notes": {
            "chapter-objectives": "Chapter Objectives",
            "general-strategies": "General Strategies",
            "link-to-learning": "Classroom Connection",
            "mini-lesson-question": "Mini Lesson Question",
            "self-check": "Self Check",
            "try": "Try it",
        },
    },
    "contemporary-math": {
        "eoc": {
            "chapter-summary": "Chapter Summary",
            "key-terms": "Key Terms",
            "eoc-videos": "Videos",
            "formula-review": "Formula Review",
            "projects": "Projects",
            "chapter-review": "Chapter Review",
            "chapter-test": "Chapter Test",
            "check-understanding": "Check Your Understanding",
        },
        "notes": {
            "your-turn": "Your Turn ",
            "people-mathematics": "People in Mathematics",
            "who-knew": "Who Knew?",
            "tech-check": "Tech Check",
            "check-point": "Checkpoint",
            "video": "Video",
            "work-out": "WORK IT OUT",
            "definition": "DEFINITION",
            "formula": "FORMULA",
        },
    },
    "dev-math": {
        "notes": {
            "try": "Try It ",
            "manipulative-math": "Manipulative Mathematics",
            "howto": "How To",
            "media-2": "Media",
            "be-prepared": "Be Prepared ",
            "links-to-literacy": "Links To Literacy",
        },
        "eoc": {
            "chapter-review": "Chapter Review",
            "exercises": "Exercises",
            "review-exercises": "Review Exercises",
            "practice-test": "Practice Test",
        },
    },
    "calculus": {
        "eoc": {
            "review-exercises": "Review Exercises",
            "chapter-review": "Chapter Review",
        },
        "media-2": "Media",
        "notes": {
            "media-2": "Media",
            "problem-solving": "Problem-Solving Strategy",
            "project": "Student Project",
            "theorem": "Theorem",
            "checkpoint": "Checkpoint",
        },
    },
    "precalculus": {
        "section_exercises": "%{number} Section Exercises",
        "eoc": {
            "practice-test": "Practice Test",
            "review-exercises": "Review Exercises",
            "section-exercises": "%{number} Section Exercises",
            "exercises": "Exercises",
            "chapter-review": "Chapter Review",
        },
        "notes": {
            "try": "Try It ",
            "how-to-notitle": "How To",
            "qa": "Q&A",
            "media-notitle": "Media",
        },
    },
    "precalculus-coreq": {
        "section_exercises": "%{number} Section Exercises",
        "coreq-skills": "Corequisite Skills",
        "eoc": {
            "practice-test": "Practice Test",
            "review-exercises": "Review Exercises",
            "section-exercises": "%{number} Section Exercises",
            "exercises": "Exercises",
            "chapter-review": "Chapter Review",
        },
        "notes": {
            "try": "Try It ",
            "how-to-notitle": "How To",
            "qa": "Q&A",
            "media-notitle": "Media",
        },
    },
    "additive-manufacturing": {
        "eoc": {
            "review-questions": "Review Questions",
            "practice": "Case Questions",
            "free-response": "Discussion Questions",
            "key-terms": "Key Terms",
        },
        "exercises": {
            "exercise": "Exercise",
        },
    },
    "python": {
        "notes": {
            "guided-slides": "Checkpoint",
            "learning-questions": "Concepts in Practice",
            "practice-program": "Try It",
        },
    },
    "neuroscience": {
        "notes": {
            "meet-author": "Meet the Author",
            "developmental-perspective": "Developmental Perspective",
            "across-species": "Neuroscience Across Species",
            "inthe-lab": "Neuroscience in the Lab",
        },
        "eoc": {
            "section-summary": "Section Summary",
            "key-terms": "Key Terms",
            "references": "References",
            "multiple-choice": "Multiple Choice",
            "fillin-blank": "Fill in the Blank",
        },
    },
    "nursing-internal": {
        "notes": {
            "link-to-learning": "Link to Learning",
            "unfolding-casestudy": "Unfolding Case Study",
            "rn-stories": "Real RN Stories",
            "clinical-safety": "Clinical Safety and Procedures (QSEN)",
            "cultural-context": "Cultural Context",
            "lifestage-context": "Life-Stage Context",
            "patient-conversations": "Patient Conversations",
            "pharma-connections": "Pharmacology Connections",
            "legal-ethical": "Legal and Ethical Issues",
            "multi-disciplinary": "Interdisciplinary Plan of Care",
            "clinical-judgment": "Clinical Judgment Measurement Model",
            "electronic-hr": "Read the Electronic Health Record",
            "psychosocial-considerations": "Psychosocial Considerations",
        },
        "eoc": {
            "chapter-review": "Assessments",
            "summary": "Summary",
            "review-questions": "Review Questions",
            "check-understanding": "Check Your Understanding Questions",
            "critical-thinking":
                "Critical-Thinking Questions about Case Studies",
            "competency-based": "Competency-Based Assessments",
            "reflection-questions": "Reflection Questions",
            "what-nurses-do": "What Should the Nurse Do?",
        },
    },
    "organic-chemistry": {
        "example": "Worked Example",
        "chapter_outline": "Chapter Contents",
        "notes": {
            "why-chapter": "Why This Chapter?",
            "chemistry-matters": "Chemistry Matters",
            "working-problems": "Working Problems",
        },
        "eoc": {
            "chemistry-matters": "Chemistry Matters",
            "key-terms": "Key Terms",
            "summary-reactions": "Summary of Reactions",
            "visualizing-chemistry": "Visualizing Chemistry",
            "additional-problems": "Additional Problems",
            "practice-scientific":
                "Practice Your Scientific Analysis and Reasoning",
            "mechanism-problems": "Mechanism Problems",
            "energy-reaction": "Energy Diagrams and Reaction Mechanisms",
            "general-problems": "General Problems",
            "preview-carbonylchemistry": "Preview of Carbonyl Chemistry",
        },
    },
    "nursing-external": {
        "notes": {
            "link-to-learning": "Link to Learning",
            "safety-alert": "Safety Alert",
            "clinical-tip": "Clinical Tip",
            "health-alert": "The Roots of Health Inequities",
            "healthy-people": "Healthy People 2030",
            "trending-today": "Trending Today",
            "culture-conversations": "Conversations About Culture",
            "theory-action": "Theory in Action",
            "special-considerations": "Special Considerations",
            "black-box": "FDA Black Box Warning",
            "client-teaching": "Client Teaching Guidelines",
            "practice-problems": "Practice Problems",
            "unfolding-casestudy": "Unfolding Case Study",
            "single-casestudy": "Case Study",
            "case-reflection": "Case Reflection",
        },
        "eoc": {
            "chapter-summary": "Chapter Summary",
            "section-summary": "Chapter Summary",
            "review-questions": "Review Questions",
            "suggested-reading": "Suggested Reading",
        },
    },
    "bca": {
        "notes": {
            "real-application": "Real-World Application",
            "spotlight-ethics": "Spotlight on Ethics",
            "mac-tip": "Mac Tip",
            "link-to-learning": "Link to Learning",
        },
        "eoc": {
            "chapter-review": "Chapter Review",
            "section-summary": "Summary",
            "review-questions": "Review Questions",
            "conceptual-questions": "Conceptual Questions",
            "you-try": "Now You Try It",
            "practice-exercises": "Practice Exercises",
            "written-questions": "Written Questions",
            "case-exercises": "Case Exercises",
            "extension-exercises": "Extension Exercises",
        },
        "exercises": {
            "exercise": "Exercise",
            "solution": "Answer",
        },
    },
    "finance": {
        "notes": {
            "think-through": "Think It Through",
            "link-to-learning": "Link to Learning",
            "concepts-practice": "Concepts In Practice",
        },
        "eoc": {
            "cfa-institute": "CFA Institute",
            "multiple-choice": "Multiple Choice",
            "review-questions": "Review Questions",
            "problem-set": "Problems",
            "section-summary": "Summary",
            "sources-notes": "Sources and Notes",
            "video-activity": "Video Activity",
        },
    },
    "accounting": {
        "notes": {
            "your-turn": "Your Turn",
            "concepts-practice": "Concepts In Practice",
            "continuing-application": "Continuing Application",
            "ethical-considerations": "Ethical Considerations",
            "ifrs-connection": "IFRS Connection",
            "link-to-learning": "Link to Learning",
            "think-through": "Think It Through",
        },
        "eoc": {
            "multiple-choice": "Multiple Choice",
            "questions": "Questions",
            "exercise-set-a": "Exercise Set A",
            "exercise-set-b": "Exercise Set B",
            "problem-set-a": "Problem Set A",
            "problem-set-b": "Problem Set B",
            "thought-provokers": "Thought Provokers",
            "section-summary": "Summary",
        },
        "sections_prefixed": {
            "exercise-set-a": "EA",
            "exercise-set-b": "EB",
            "problem-set-a": "PA",
            "problem-set-b": "PB",
            "thought-provokers": "TP",
        },
    },
    "business-ethics": {
        "notes": {
            "link-to-learning": "Link to Learning",
            "ethics-across": "Ethics Across Time and Cultures",
            "real-world": "Cases from the Real World",
            "what-would": "What Would You Do?",
        },
        "eoc": {
            "section-summary": "Summary",
            "assessment-questions": "Assessment Questions",
            "references": "Endnotes",
        },
    },
    "entrepreneurship": {
        "test": "Test",
        "eoc": {
            "section-summary": "Summary",
            "review-questions": "Review Questions",
            "discussion-questions": "Discussion Questions",
            "case-questions": "Case Questions",
            "suggested-resources": "Suggested Resources",
        },
        "notes": {
            "are-you-ready": "Are You Ready?",
            "what-can-do": "What Can You Do?",
            "link-to-learning": "Link to Learning",
            "entrepreneur-in-action": "Entrepreneur In Action",
            "work-it-out": "Work It Out",
        },
    },
    "principles-management": {
        "figure": "Exhibit",
        "notes": {
            "exploring-manager-careers": "Exploring Managerial Careers",
            "concept-check": "Concept Check",
            "sustainability-responsible":
                "Sustainability and Responsible Management",
            "managerial-leadership": "Managerial Leadership",
            "ethics-in-practice": "Ethics in Practice",
            "managing-change": "Managing Change",
            "catching-spirit": "Catching the Entrepreneurial Spirit",
            "expanding-around-globe": "Expanding Around the Globe",
            "customer-satisfaction": "Customer Satisfaction and Quality",
        },
        "eoc": {
            "review-questions": "Review Questions",
            "section-summary": "Summary of Learning Outcomes",
            "manage-skills": "Management Skills Application Exercises",
            "manage-exercises": "Managerial Decision Exercises",
            # The locale names critical-thinking twice; YAML keeps the
            # second.
            "critical-thinking": "Critical Thinking Case",
            "chapter-review": "Chapter Review Questions",
        },
    },
    "intro-business": {
        "figure": "Exhibit",
        "notes": {
            "exploring-business-careers": "Exploring Business Careers",
            "catching-spirit": "Catching the Entrepreneurial Spirit",
            "concept-check": "Concept Check",
            "managing-change": "Managing Change",
            "customer-satisfaction": "Customer Satisfaction and Quality",
            "ethics-in-practice": "Ethics in Practice",
            "expanding-around-globe": "Expanding Around the Globe",
        },
        "eoc": {
            "section-summary": "Summary of Learning Outcomes",
            "prep-workplace": "Preparing for Tomorrow's Workplace Skills",
            "ethics-activity": "Ethics Activity",
            "working-net": "Working the Net",
            "critical-thinking": "Critical Thinking Case",
            "hot-links": "Hot Links Address Book",
        },
    },
    "economics": {
        "notes": {
            "linkup": "Link It Up",
            "bringhome": "Bring It Home",
            "clearup": "Clear It Up",
            "workout": "Work It Out",
            "chapter-objectives": "Chapter Objectives",
        },
        "eoc": {
            "summary": "Key Concepts and Summary",
            "self-check-questions": "Self-Check Questions",
            "review-questions": "Review Questions",
            "critical-thinking": "Critical Thinking Questions",
            "glossary": "Key Terms",
            "problems": "Problems",
        },
    },
    "statistics": {
        "eoc_free_response": "Homework",
        "eoc": {
            "summary": "Chapter Review",
            "formula-review": "Formula Review",
            "practice": "Practice",
            "bring-together-homework": "Bringing It Together: Homework",
            "bring-together-exercises": "Bringing It Together: Practice",
            "free-response": "Homework",
            "stats-labs": "Stats Labs",
            "excel-labs": "Excel Labs",
        },
        "notes": {
            # The space after a label is the locale's, kept: the number
            # follows it.
            "try": "Try It ",
            "lab": "Stats Lab ",
            "collab": "Collaborative Exercise",
            "calculator": "Using the TI-83, 83+, 84, 84+ Calculator",
            "chapter-objectives": "Chapter Objectives",
        },
    },
    "american-government": {
        "notes": {
            "link-to-learning": "Link to Learning",
            "middle-ground": "Finding a Middle Ground",
            "milestone": "Milestone",
            "get-connected": "Get Connected!",
            "insider-perspective": "Insider Perspective",
        },
        "eoc": {
            "review-questions": "Review Questions",
            "critical-thinking": "Critical Thinking Questions",
        },
    },
    "u-physics": {
        "notes": {
            "check-understanding": "Check Your Understanding ",
            "media-2": "Interactive",
            "problem-solving": "Problem-Solving Strategy",
        },
        "eoc": {
            "review-conceptual-questions": "Conceptual Questions",
            "review-problems": "Problems",
            "review-additional-problems": "Additional Problems",
            "review-challenge": "Challenge Problems",
            "chapter-review": "Chapter Review",
            "key-concepts": "Summary",
            "solutions": "Solutions",
        },
        "eoc_key_concepts": "Summary",
    },
    "english-composition": {
        "eoc": {
            "further-reading": "Further Reading",
            "works-consulted": "Works Consulted",
            "works-cited": "Works Cited",
        },
        "custom-sections": {
            "narrative-trailblazer": "Trailblazer",
            "living-words": "Living by Their Own Words",
            "quick-launch": "Quick Launch",
            "drafting": "Drafting",
            "peer-review": "Peer Review",
            "revising": "Revising",
        },
    },
    "computer-science": {
        "unit": "Part",
        "notes": {
            "think-through": "Think It Through",
            "tech-everyday": "Technology in Everyday Life",
            "concepts-practice": "Concepts In Practice",
            "global-tech": "Global Issues in Technology",
            "link-to-learning": "Link to Learning",
            "industry-spotlight": "Industry Spotlight",
        },
        "eoc": {
            "chapter-review": "Chapter Review",
            "review-questions": "Review Questions",
            "conceptual-questions": "Conceptual Questions",
            "practice-exercises": "Practice Exercises",
            "problem-set-a": "Problem Set A",
            "problem-set-b": "Problem Set B",
            "thought-provokers": "Thought Provokers",
            "labs-assessments": "Labs",
            "section-summary": "Summary",
        },
        "exercises": {
            "your-turn": "Your Turn",
            "solution": "Solution",
            "exercise": "Exercise",
        },
    },
    "college-physics": {
        "check-understanding": "Check Your Understanding",
        "eoc": {
            "glossary": "Glossary",
            "section-summary": "Section Summary",
            "conceptual-questions": "Conceptual Questions",
            # "Problems &amp; Exercises", written into HTML there.
            "problems-exercises": "Problems & Exercises",
        },
        "notes": {
            "interactive": "PhET Explorations",
        },
    },
    "college-physics-2e": {
        "check-understanding": "Check Your Understanding",
        "eoc": {
            "glossary": "Glossary",
            "section-summary": "Section Summary",
            "conceptual-questions": "Conceptual Questions",
            "problems-exercises": "Problems & Exercises",
        },
        "notes": {
            "interactive": "PhET Explorations",
        },
        "exercises": {
            "authentic-assessment": "Authentic Assessment",
        },
    },
    "college-success": {
        "notes": {
            "student-profile": "Student Profile",
            "activity": "Activity",
            "analysis-question": "Analysis Question",
            "what-students-say": "What Students Say",
            "application": "Application",
            "get-connected": "Get Connected",
        },
        "eoc": {
            "rethinking": "Rethinking",
            "where-go": "Where do you go from here?",
            "career-connection": "Career Connection",
        },
    },
    "hs-college-success": {
        "notes": {
            "student-profile": "Student Profile",
            "activity": "Activity",
            "analysis-question": "Analysis Question",
            "what-students-say": "What Students Say",
            "application": "Application",
            "get-connected": "Get Connected",
            "real-deal": "The Real Deal",
            "student-story": "Student Story",
        },
        "eoc": {
            "rethinking": "Rethinking",
            "where-go": "Where do you go from here?",
            "career-connection": "Career Connection",
            # "Family &amp; Friends Matter" in the locale, written into
            # HTML there: an ampersand.
            "family-friends": "Family & Friends Matter",
            "checking-in": "Checking In: Your College Readiness Checklist",
        },
    },
    "chemistry": {
        "eoc": {
            "exercises": "Exercises",
        },
        "notes": {
            "link-to-learning": "Link to Learning",
            "everyday-life": "Chemistry in Everyday Life",
            "chemist-portrait": "Portrait of a Chemist",
            "sciences-interconnect": "How Sciences Interconnect",
        },
    },
    "biology": {
        "notes": {
            "visual-connection": "Visual Connection",
            "interactive": "Link to Learning",
            "evolution": "Evolution Connection",
            "career": "Career Connection",
            "scientific": "Scientific Method Connection",
            "everyday": "Everyday Connection",
        },
        "eoc": {
            "summary": "Chapter Summary",
            "visual-exercise": "Visual Connection Questions",
            "multiple-choice": "Review Questions",
            "critical-thinking": "Critical Thinking Questions",
        },
    },
    "ap-biology": {
        "notes": {
            "os-teacher": "Teacher Support",
            "visual-connection": "Visual Connection",
            "interactive": "Link to Learning",
            "evolution": "Evolution Connection",
            "ap-everyday": "Everyday Connection for AP\u00ae\u00a0Courses",
            "career": "Career Connection",
            "ost-sciprac-scithink": "Think About It",
            "ost-sciprac-activity": "Activity",
            "ap-science-practices":
                "Science Practice Connection for AP\u00ae\u00a0Courses",
            "everyday": "Everyday Connection",
            "experiment": "Scientific Method Connection",
            "scientific": "Scientific Method Connection",
        },
        "eoc": {
            "summary": "Chapter Summary",
            "review": "Review Questions",
            "critical-thinking": "Critical Thinking Questions",
            "ap-test-prep": "Test Prep for AP\u00ae\u00a0Courses",
            "science-practice": "Science Practice Challenge Questions",
        },
    },
    "ap-history": {
        "notes": {
            "os-teacher": "Teacher Support",
        },
    },
    "hs-physics": {
        "grasp-check": "Grasp Check",
        "notes": {
            "os-teacher": "Teacher Support",
            "learning-objectives": "Section Learning Objectives",
            "boundless-physics": "Boundless Physics",
            "worked-example": "Worked Example",
            "virtual-physics": "Virtual Physics",
            "snap-lab": "Snap Lab",
            "links-to-physics": "Links To Physics",
            "tips-for-success": "Tips For Success",
            "teacher-demonstration": "Teacher Demonstration",
            "watch-physics": "Watch Physics",
            "work-in-physics": "Work In Physics",
            "fun-in-physics": "Fun In Physics",
            "misconception": "Misconception Alert",
        },
        "eoc": {
            "test-prep": "Test Prep",
            "chapter-review": "Chapter Review",
            "concept": "Concept Items",
            "summary": "Section Summary",
            "critical-thinking": "Critical Thinking Items",
            "problems": "Problems",
            "performance": "Performance Task",
            "multiple-choice": "Multiple Choice",
            "short-answer": "Short Answer",
            "extended-response": "Extended Response",
        },
    },
    "ap-physics": {
        "check-understanding": "Check Your Understanding",
        "eoc": {
            "glossary": "Glossary",
            "section-summary": "Section Summary",
            "conceptual-questions": "Conceptual Questions",
            "problems-exercises": "Problems & Exercises",
            "ap-test-prep": "Test Prep for AP\u00ae Courses",
        },
        "notes": {
            "interactive": "PhET Explorations",
        },
    },
    "anatomy": {
        "notes": {
            "interactive": "Interactive Link",
            "everyday": "Everyday Connection",
            "homeostatic": "Homeostatic Imbalances",
            "disorders": "Disorders of the...",
            "career": "Career Connection",
            "chapter-objectives": "Chapter Objectives",
            "aging": "Aging and the...",
            "diseases": "Diseases of the...",
        },
        "eoc": {
            "interactive-exercise": "Interactive Link Questions",
            "multiple-choice": "Review Questions",
            "free-response": "Critical Thinking Questions",
            "summary": "Chapter Review",
            "disorders": "Disorders of the...",
            "career": "Career Connection",
        },
    },
    "astronomy": {
        "eoc": {
            "further-exploration": "For Further Exploration",
            "group-activities": "Collaborative Group Activities",
            "exercises": "Exercises",
            "review-questions": "Review Questions",
            "thought-questions": "Thought Questions",
            "figuring-for-yourself": "Figuring for Yourself",
        },
        "notes": {
            "link-to-learning": "Link to Learning",
            "astronomy-basics": "Astronomy Basics",
            "making-connections": "Making Connections",
            "seeing-for-yourself": "Seeing for Yourself",
            "voyagers-in-astronomy": "Voyagers in Astronomy",
        },
    },
    "anthropology": {
        "notes": {
            "ethnographic-sketches": "Ethnographic Sketches",
            "fieldwork-activity": "Mini-Fieldwork Activity",
            "profiles-anthropology": "Profiles in Anthropology",
            "media-podcast": "Podcast",
            "media-video": "Video",
        },
        "eoc": {
            "critical-thinking": "Critical Thinking Questions",
            "references": "Bibliography",
            "section-summary": "Summary",
        },
    },
    "world-history": {
        "notes": {
            "link-to-learning": "Link to Learning",
            "own-words": "In Their Own Words",
            "dueling-voices": "Dueling Voices",
            "beyond-book": "Beyond the Book",
            "past-present": "The Past Meets the Present",
        },
        "eoc": {
            "assessments": "Assessments",
            "section-summary": "Section Summary",
            "review-questions": "Review Questions",
            "check-understanding": "Check Your Understanding Questions",
            "reflection-questions": "Application and Reflection Questions",
            "visual-questions": "Visual-Based Questions",
            "making-connections": "Making Connections",
            "thought-provokers": "Thought Provokers",
            "source-questions": "Source Questions",
        },
    },
    "history": {
        "notes": {
            "click-and-explore": "Click and Explore",
            "my-story": "My Story",
            "americana": "Americana",
            "defining-american": "Defining American",
        },
        "eoc": {
            "critical-thinking": "Critical Thinking Questions",
            "review-questions": "Review Questions",
            "section-summary": "Summary",
        },
    },
    "microbiology": {
        "notes": {
            "clinical-focus": "Clinical Focus",
            "check-your-understanding": "Check Your Understanding",
            "micro-connection": "Micro Connections",
            "link-to-learning": "Link to Learning",
            "eye-on-ethics": "Eye on Ethics",
            "case-in-point": "Case in Point",
            "disease-profile": "Disease Profile",
        },
        "eoc": {
            "multiple-choice": "Multiple Choice",
            "fill-in-the-blank": "Fill in the Blank",
            "short-answer": "Short Answer",
            "critical-thinking": "Critical Thinking",
            "review-questions": "Review Questions",
            "true-false": "True/False",
            "matching": "Matching",
        },
        "eoc_key_concepts": "Summary",
        "eoc_exercises_title": "Chapter Review",
        "eoc_composite_metadata_title": "Review Questions",
    },
    "lifespan-development": {
        "eoc": {
            "review-questions": "Review Questions",
            "check-understanding": "Check Your Understanding Questions",
            "personal-application": "Personal Application Questions",
            "essay-questions": "Essay Questions",
        },
        "notes": {
            "link-to-learning": "Link to Learning",
            "it-depends": "It Depends",
            "intersections-contexts": "Intersections and Contexts",
            "life-hacks": "Life Hacks",
        },
    },
    "philosophy": {
        "notes": {
            "read-philosopher": "Read Like a Philosopher",
            "think-philosopher": "Think Like a Philosopher",
            "write-philosopher": "Write Like a Philosopher",
            "philo-connections": "Connections",
            "time-line": "Timeline",
            "media-video": "Video",
            "media-podcast": "Podcast",
        },
        "eoc": {
            "summary": "Summary",
            "review-questions": "Review Questions",
            "further-reading": "Further Reading",
            "references": "References",
            "further-research": "Further Research",
        },
    },
    "political-science": {
        "eoc": {
            "review-questions": "Review Questions",
            "suggested-readings": "Suggested Readings",
        },
        "notes": {
            "show-data": "Show Me the Data",
            "connecting-courses": "Connecting Courses",
            "meet-professional": "Meet a Professional",
            "changing-political": "THE CHANGING POLITICAL LANDSCAPE",
            "what-do": "What Can I Do?",
            "where-engage": "Where Can I Engage?",
            "media-video": "Video",
            "media-podcast": "Podcast",
        },
    },
    "psychology": {
        "notes": {
            "link-to-learning": "Link to Learning",
            "dig-deeper": "Dig Deeper",
            "everyday-connection": "Everyday Connection",
            "what-do-you-think": "What Do You Think?",
            "connect-the-concepts": "Connect the Concepts",
        },
        "eoc": {
            "review-questions": "Review Questions",
            "critical-thinking": "Critical Thinking Questions",
            "personal-application": "Personal Application Questions",
        },
    },
    "sociology": {
        "notes": {
            "sociological-research": "Sociological Research",
            "sociology-real-world": "Sociology in the Real World",
            "sociology-big-picture": "Big Picture",
            "sociology-policy-debate": "Social Policy and Debate",
        },
        "eoc": {
            "section-quiz": "Section Quiz",
            "short-answer": "Short Answer",
            "section-summary": "Section Summary",
        },
    },
    "data-science": {
        "eoc": {
            "group-project": "Group Project",
            "chapter-review": "Chapter Review",
            "critical-thinking": "Critical Thinking",
            "quantitative-problems": "Quantitative Problems",
        },
        "notes": {
            "exploring-further": "Exploring Further",
            "python-feature": "Python Code",
        },
    },
    "information-systems": {
        "eoc": {
            "review-questions": "Review Questions",
            "check-understanding": "Check Your Understanding Questions",
            "application-questions": "Application Questions",
        },
        "notes": {
            "future-tech": "Future Technology",
            "global-connect": "Global Connections",
            "is-ethics": "Ethics in IS",
            "is-careers": "Careers in IS",
            "link-to-learning": "Link to Learning",
        },
    },
    "marketing": {
        "notes": {
            "marketing-dashboard": "Marketing Dashboard",
            "marketing-practice": "Marketing in Practice",
            "companies-conscience": "Companies with a Conscience",
            "link-to-learning": "Link to Learning",
            "careers-marketing": "Careers In Marketing",
        },
        "eoc": {
            "knowledge-check": "%{number} Knowledge Check",
            "chapter-summary": "Chapter Summary",
            "marketing-discussion":
                "Applied Marketing Knowledge: Discussion Questions",
            "critical-thinking": "Critical Thinking Exercises",
            "building-brand": "Building Your Personal Brand",
            "marketers-do": "What Do Marketers Do?",
            "marketing-plan": "Marketing Plan Exercise",
            "company-case": "Closing Company Case",
            "references": "References",
        },
        "exercises": {
            "solution": "Solution",
        },
        "appendix_sections": {
            "references": "References",
            "chapter-summary": "Summary",
            "knowledge-check": "Knowledge Check",
            "learning-objectives": "Learning Outcomes",
        },
    },
}


# lib/locales/pl.yml, for a book in Polish. A word a link may name
# its target with has its seven cases, the nominative the one shown
# elsewhere.
COMMON_PL = {
    "figure": {
        "nominative": "Ilustracja",
        "genitive": "Ilustracji",
        "dative": "Ilustracji",
        "accusative": "Ilustrację",
        "instrumental": "Ilustracją",
        "locative": "Ilustracji",
        "vocative": "Ilustracjo",
    },
    "table": {
        "nominative": "Tabela",
        "genitive": "Tabeli",
        "dative": "Tabeli",
        "accusative": "Tabelę",
        "instrumental": "Tabelą",
        "locative": "Tabeli",
        "vocative": "Tabelo",
    },
    "example": {
        "nominative": "Przykład",
        "genitive": "Przykładu",
        "dative": "Przykładowi",
        "accusative": "Przykład",
        "instrumental": "Przykładem",
        "locative": "Przykładzie",
        "vocative": "Przykładzie",
    },
    "exercise": {
        "nominative": "Ćwiczenie",
        "genitive": "Ćwiczenia",
        "dative": "Ćwiczeniu",
        "accusative": "Ćwiczenie",
        "instrumental": "Ćwiczeniem",
        "locative": "Ćwiczeniu",
        "vocative": "Ćwiczenie",
    },
    "equation": {
        "nominative": "Równanie",
        "genitive": "Równania",
        "dative": "Równaniu",
        "accusative": "Równanie",
        "instrumental": "Równaniem",
        "locative": "Równaniu",
        "vocative": "Równanie",
    },
    "note": {
        "nominative": "Ramka",
        "genitive": "Ramki",
        "dative": "Ramce",
        "accusative": "Ramkę",
        "instrumental": "Ramką",
        "locative": "Ramce",
        "vocative": "Ramko",
    },
    "theorem": "Twierdzenie",
    "solution": "Rozwiązanie",
    "chapter_outline": "Treść rozdziału",
    "unit": "Część",
    "chapter_review": "Podsumowanie rozdziału",
    "learning_objectives": "Cel dydaktyczny",
    "stepwise_step_label": "Krok",
    "answer_key_title": "Rozwiązania zadań",
    "eoc_chapter_review": "Podsumowanie rozdziału",
    "eoc_solutions_title": "Rozwiązania",
    "eob_index_symbols_group": "Symbole",
    "references": "Bibliografia",
    "eoc": {
        "glossary": "Kluczowe pojęcia",
        "key-equations": "Najważniejsze wzory",
        "summary": "Podsumowanie",
        "references": "Bibliografia",
    },
    "eob": {
        "references": "Bibliografia",
        "reference": "Bibliografia",
    },
    "index": {
        "name": "Skorowidz nazwisk",
        "term": "Skorowidz rzeczowy",
        "foreign": "Skorowidz terminów obcojęzycznych",
    },
    "folio": {
        "access_for_free": "Podręcznik dostępny za darmo na openstax.org",
    },
    "appendix": {
        "nominative": "Dodatek",
        "genitive": "Dodatku",
        "dative": "Dodatkowi",
        "accusative": "Dodatek",
        "instrumental": "Dodatkiem",
        "locative": "Dodatku",
        "vocative": "Dodatku",
    },
    "preface": {
        "nominative": "Przedmowa",
    },
    "chapter": {
        "nominative": "Rozdział",
        "genitive": "Rozdziału",
        "dative": "Rozdziałowi",
        "accusative": "Rozdział",
        "instrumental": "Rozdziałem",
        "locative": "Rozdziale",
        "vocative": "Rozdziale",
    },
    "module": {
        "nominative": "Podrozdział",
        "genitive": "Podrozdziału",
        "dative": "Podrozdziałowi",
        "accusative": "Podrozdział",
        "instrumental": "Podrozdziałem",
        "locative": "Podrozdziale",
        "vocative": "Podrozdziale",
    },
}

# Each Polish recipe's locales/pl.yml.
BY_STYLE_PL = {
    "pl-economics": {
        "notes": {
            "linkup": "Sięgnij po więcej",
            "bringhome": "Do przemyślenia",
            "clearup": "Poznaj szczegóły",
            "workout": "Krok po kroku",
            "chapter-objectives": "Cel dydaktyczny rozdziału",
            "learning-objectives": "Cel dydaktyczny",
        },
        "eoc": {
            "self-check-questions": "Pytania sprawdzające",
            "review-questions": "Sprawdź wiedzę",
            "critical-thinking": "Ćwicz myślenie krytyczne",
            "problems": "Problemy",
        },
    },
    "pl-marketing": {
        "notes": {
            "marketing-dashboard": "Analityka marketingowa",
            "marketing-practice": "Z doświadczenia marketera",
            "companies-conscience": "Etyczna firma",
            "link-to-learning": "Sięgnij po więcej",
        },
        "eoc": {
            "knowledge-check": "%{number} Sprawdź wiedzę",
            "chapter-summary": "Podsumowanie rozdziału",
            "marketing-discussion": "Marketing w praktyce — przedyskutuj to",
            "critical-thinking": "Ćwicz myślenie krytyczne",
            "marketing-plan": "Plan marketingowy — ćwiczenia",
            "company-case": "A na koniec — studium przypadku",
        },
    },
    "pl-nursing": {
        "notes": {
            "unfolding-casestudy": "Jak postąpisz w tym przypadku?",
            "clinical-tip": "Z praktyki klinicznej",
        },
        "eoc": {
            "chapter-summary": "Podsumowanie rozdziału",
            "review-questions": "Sprawdź się!",
            "suggested-reading": "Chcesz wiedzieć więcej?",
        },
    },
    "pl-psychology": {
        "notes": {
            "link-to-learning": "Sięgnij po więcej",
            "dig-deeper": "Poznaj szczegóły",
            "everyday-connection": "Wokół nas",
            "what-do-you-think": "Co o tym sądzisz?",
            "connect-the-concepts": "Połącz wątki",
        },
        "eoc": {
            "review-questions": "Sprawdź wiedzę",
            "critical-thinking": "Ćwicz myślenie krytyczne",
            "personal-application": "Rozwijaj się",
        },
    },
    "pl-u-physics": {
        "notes": {
            "media-2": "Materiały pomocnicze",
            "check-understanding": "Sprawdź, czy rozumiesz",
            "problem-solving": "Strategia rozwiązywania zadań",
        },
        "eoc": {
            "chapter-review": "Podsumowanie rozdziału",
            "key-concepts": "Podsumowanie",
            "review-conceptual-questions": "Pytania",
            "review-problems": "Zadania",
            "review-additional-problems": "Zadania dodatkowe",
            "review-challenge": "Zadania trudniejsze",
        },
    },
}


# lib/locales/es.yml, for a book in Spanish: the strings the ported
# directions look up, as cookbook's Spanish locale gives them. It has no
# "problem", which the statistics recipe heads each example's problem
# with, 389 times in OpenStax's two Spanish statistics books, so that
# OpenStax's own *Introducción a la estadística* shows "Translation
# missing: es.problem" there (openstax.org, read 2026-10-27): "Problema"
# here is TextbookImprover's, not cookbook's. Of the strings it lacks,
# that's the only one OpenStax's Spanish books reach (each of the five
# repositories' eleven baked); "section", "preface", and "lo_label_text"
# stay English.
COMMON_ES = {
    "figure": "Figura",
    "table": "Tabla",
    "appendix": "Apéndice",
    "solution": "Solución",
    "problem": "Problema",
    "chapter_outline": "Esquema del capítulo",
    "example": "Ejemplo",
    "exercise": "Ejercicio",
    "equation": "Ecuación",
    "chapter": "Capítulo",
    "unit": "Unidad",
    "learning_objectives": "Objetivos de aprendizaje",
    "stepwise_step_label": "Paso",
    "references": "Referencias",
    "answer_key_title": "Clave de respuestas",
    "eoc_exercises_title": "Ejercicios",
    "eoc_composite_metadata_title": "Revisión del capítulo",
    "eoc_solutions_title": "Soluciones",
    "eoc_suggested_reading": "Sugerencias para estudios adicionales",
    "eob_index_symbols_group": "Símbolos",
    "section_exercises": "Sección %{number} ejercicios",
    "handbook_outline_title": "Esquema",
    "context_lead_text": "Referirse a ",
    "eoc": {
        "glossary": "Términos clave",
        "key-equations": "Ecuaciones clave",
        "summary": "Resumen",
        "further-research": "Investigación adicional",
        "key-concepts": "Conceptos clave",
        "references": "Referencias",
        "solutions": "Soluciones",
        "section-exercises": "Sección %{number} ejercicios",
    },
    "eob": {
        "references": "Referencias",
        "reference": "Referencias",
    },
    "index": {
        "main": "Índice",
    },
    "folio": {
        "access_for_free": "Acceso gratis en openstax.org",
    },
}

# Each recipe's locales/es.yml, the strings its English has: history's
# is finance's, but for two strings.
BY_STYLE_ES = {
    "anatomy": {
        "notes": {
            "interactive": "Enlace Interactivo",
            "everyday": "Conexión Diaria",
            "homeostatic": "Desequilibrios Homeostáticos",
            "disorders": "Trastornos del ...",
            "career": "Conexión Profesional",
            "chapter-objectives": "Objetivos del Capítulo",
            "aging": "El Envejecimiento y el ...",
        },
        "eoc": {
            "interactive-exercise": "Preguntas Sobre Enlaces Interactivos",
            "multiple-choice": "Preguntas de Revisión",
            "free-response": "Preguntas de Pensamiento Crítico",
            "summary": "Revisión del Capítulo",
            "disorders": "Trastornos del ...",
            "career": "Conexión Profesional",
        },
    },
    "calculus": {
        "eoc": {
            "review-exercises": "Ejercicios de repaso",
            "chapter-review": "Revisión del capítulo",
        },
        "media-2": "Medios",
        "notes": {
            "media-2": "Medios",
            "problem-solving": "Estrategia de resolución de problemas",
            "project": "Proyecto de estudiante",
            "theorem": "Teorema",
            "checkpoint": "Punto de control",
        },
    },
    "chemistry": {
        "eoc": {
            "exercises": "Ejercicios",
        },
        "notes": {
            "link-to-learning": "Enlace al aprendizaje",
            "everyday-life": "La química en la vida cotidiana",
            "chemist-portrait": "Retrato de un químico",
            "sciences-interconnect": "Cómo se interconectan las ciencias",
        },
    },
    "computer-science": {
        "unit": "Parte",
        "notes": {
            "think-through": "Piénsalo",
            "tech-everyday": "Tecnología en la Vida Cotidiana",
            "concepts-practice": "Conceptos en Práctica",
            "global-tech": "Problemas Globales de Tecnología",
            "link-to-learning": "Enlace al Aprendizaje",
            "industry-spotlight": "Destacado en la Industria",
        },
        "eoc": {
            "review-questions": "Preguntas de Revisión",
            "conceptual-questions": "Preguntas Conceptuales",
            "practice-exercises": "Ejercicios de Práctica",
            "problem-set-a": "Serie de Problemas A",
            "problem-set-b": "Serie de Problemas B",
            "thought-provokers": "Provocadores del Pensamiento",
            "labs-assessments": "Laboratorios",
            "section-summary": "Resumen",
        },
        "exercises": {
            "your-turn": "Tu Turno",
            "solution": "Solución",
            "exercise": "Ejercicio",
        },
    },
    "finance": {
        "notes": {
            "think-through": "Piénsalo",
            "link-to-learning": "Enlace al Aprendizaje",
            "concepts-practice": "Conceptos en la Práctica",
        },
        "eoc": {
            "cfa-institute": "Instituto CFA",
            "multiple-choice": "Opción Múltiple",
            "review-questions": "Preguntas de Revisión",
            "problem-set": "Problemas",
            "section-summary": "Resumen",
            "sources-notes": "Fuentes y Notas",
            "video-activity": "Video Actividad",
        },
    },
    "history": {
        "eoc": {
            "review-questions": "Preguntas de Revisión",
            "section-summary": "Resumen",
        },
    },
    "microbiology": {
        "notes": {
            "clinical-focus": "Enfoque Clínico",
            "check-your-understanding": "Verifica Tu Comprensión ",
            "micro-connection": "Micro Conexiones",
            "link-to-learning": "Enlace Al Aprendizaje",
            "eye-on-ethics": "Ojo En La Etica",
            "case-in-point": "Caso En Punto",
            "disease-profile": "Perfil De Enfermedad",
        },
        "eoc": {
            "multiple-choice": "Selección Multiple",
            "fill-in-the-blank": "Complete El Espacio En Blanco",
            "short-answer": "Respuesta Corta",
            "critical-thinking": "Pensamiento Crítico",
            "review-questions": "Preguntas De Revisión",
            "true-false": "Verdadero/Falso",
            "matching": "Combinación",
        },
        "eoc_key_concepts": "Resumen",
        "eoc_exercises_title": "Revisión Del Capítulo",
        "eoc_composite_metadata_title": "Preguntas De Revisión",
    },
    "political-science": {
        "eoc": {
            "review-questions": "Preguntas de Revisión",
            "suggested-readings": "Lecturas sugeridas",
        },
        "notes": {
            "show-data": "Muéstrame los Datos",
            "connecting-courses": "Cursos de Conexión",
            "meet-professional": "Conoce a un Profesional",
            "changing-political": "El Cambiante Paisaje Político",
            "what-do": "¿Qué puedo hacer?",
            "where-engage": "¿Dónde puedo participar?",
            "media-video": "Video",
            "media-podcast": "Podcast",
        },
    },
    "precalculus": {
        "section_exercises": "%{number} Ejercicios de sección",
        "eoc": {
            "practice-test": "Examen de práctica",
            "review-exercises": "Ejercicios de repaso",
            "section-exercises": "%{number} Ejercicios de sección",
            "exercises": "Ejercicios",
            "chapter-review": "Revisión del capítulo",
        },
        "notes": {
            "try": "Inténtelo ",
            "how-to-notitle": "Cómo",
            "qa": "Preguntas y respuestas",
            "media-notitle": "Media",
        },
    },
    "precalculus-coreq": {
        "section_exercises": "%{number} Ejercicios de sección",
        "coreq-skills": "Habilidades de correquisito",
        "eoc": {
            "practice-test": "Examen de práctica",
            "review-exercises": "Ejercicios de repaso",
            "section-exercises": "%{number} ejercicios de sección",
            "exercises": "Ejercicios",
            "chapter-review": "Revisión del capítulo",
        },
        "notes": {
            "try": "Inténtelo ",
            "how-to-notitle": "Cómo",
            "qa": "Q&A",
            "media-notitle": "Media",
        },
    },
    "statistics": {
        "eoc_free_response": "Tarea para la casa",
        "eoc": {
            "summary": "Repaso del capítulo",
            "formula-review": "Repaso de fórmulas",
            "practice": "Práctica",
            "bring-together-homework": "Resúmalo todo: tarea para la casa",
            "bring-together-exercises": "Uniéndolo todo: Práctica",
            "free-response": "Tarea para la casa",
            "solutions": "Soluciones",
            "stats-labs": "Laboratorios de estadística",
            "excel-labs": "Laboratorios de Excel",
        },
        "notes": {
            "try": "Inténtelo ",
            "lab": "Laboratorio de estadística ",
            "collab": "Ejercicio colaborativo",
            "calculator": "Uso de las calculadoras TI-83, 83+, 84, 84+",
            "chapter-objectives": "Objetivos del capítulo",
        },
    },
    "u-physics": {
        "notes": {
            "check-understanding": "Compruebe Lo Aprendido ",
            "media-2": "Interactivo",
            "problem-solving": "Estrategia de Resolución De Problemas",
        },
        "eoc": {
            "review-conceptual-questions": "Preguntas Conceptuales",
            "review-problems": "Problemas",
            "review-additional-problems": "Problemas Adicionales",
            "review-challenge": "Problemas De Desafío",
            "chapter-review": "Revisión Del Capítulo",
            "key-concepts": "Resumen",
            "solutions": "Soluciones",
        },
        "eoc_key_concepts": "Resumen",
    },
}


def merged(base, extra):
    out = copy.deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merged(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


# A style baked by another's recipe, as cookbook's bake script maps it.
ALIASES = {"ap-physics-2e": "ap-physics", "otto-book": "chemistry"}


def for_style(style, language="en"):
    """The strings for a book of the style: English, or for a book in
    Polish or Spanish, the language's where cookbook's locale for it has
    a string, the recipe's before the common ones, as cookbook looks
    them up, and English where it hasn't (cookbook would write
    "translation missing")."""
    style = ALIASES.get(style, style)
    strings = merged(COMMON, BY_STYLE.get(style, {}))
    if language == "pl":
        strings = merged(strings, merged(COMMON_PL, BY_STYLE_PL.get(style,
                                                                   {})))
    elif language == "es":
        strings = merged(strings, merged(COMMON_ES, BY_STYLE_ES.get(style,
                                                                   {})))
    return strings
