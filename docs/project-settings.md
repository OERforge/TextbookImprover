# Project settings

Settings that describe the book rather than any one rendering or package of it, at the top level of `packaging.yaml`. Both halves of the pipeline read them. Generated from `lib/schema-project.yaml` by `util/settings-reference.py`; edit the schema, not this page.

Facts about the book itself, true of every rendering of it.

**`identifier`**—`ncname`; default `book`

A name for this book that no other book anywhere will use. It is what an LMS matches on to recognize a re-import as the same course, it's what the content folder inside a package is named after, and two books sharing one are two books the LMS will treat as one. The IMS schema only requires it to be unique within the package; uniqueness beyond that's your responsibility and nothing will warn you. It also has to be a valid XML name, because IMS types it as xs:ID: start with a letter, then letters, digits, and . - _ only. No colons, and it may not start with a digit—which rules out both obvious ways of generating a unique one, since a bare UUID usually starts with a digit and urn:uuid: has colons. Reverse-DNS is the least error-prone form and reads well as a folder name: org.example.dept.course-code. A UUID works with a letter in front, which you can generate with python3 -c "import uuid; print('i' + uuid.uuid4().hex)". Whichever you choose, keep it for the life of the book. Changing it makes every future import a new course rather than an update.

**`title`**—`string`; default `Untitled`

The book's title, as it should appear to a reader.

**`language`**—`language`; default `en`

BCP 47 language tag for the book's text. Sets the lang attribute on every page (WCAG 3.1.1) and the language declared in any package built from those pages. Quote it: unquoted no, yes, and on are read as booleans by YAML.

**`description`**—`text`; default `""` (empty)

A sentence or two about the book, used wherever a package format asks for one.

**`publisher`**—`string`; default `""` (empty)

Who published the book. Written as document metadata, and available to package formats that record it.

**`numbering`**—`bool`; default `false`

Number the book's structure the way a printed book does: groups and top-level pages with the main role 1, 2, 3 and their pages 1.1, 1.2; appendices A, B and A.1, A.2; front and back matter unnumbered. The numbers appear in the EPUB's table of contents and headings, the cartridge organization, the generated contents page, and the pages' titles.

**`authors`**—`list`; default `[]`

Who wrote the book, one entry each, as a reader should see them. An EPUB records each as a creator; the cartridge has nowhere to put one. For an OpenStax book the publisher is usually the right entry.

**`passthrough`**—`path`; default `_pt`

A directory, inside the book's, for pages that aren't converted from the book's sources: an .html here is a page someone finished and is copied into every HTML target as it stands (and read for the EPUB), and an .md here is converted alongside the sources. Its files are treated as though they sat beside the sources, so a reference in _pt/about.html to images/logo.png names the book's images/logo.png. Every .html beside the sources is a source.

**`contents`**—`opaque`; default `[]`

The book's structure as a nested list of pages and groups. This describes the book, not any one package, so a cartridge organization and an EPUB table of contents are both built from it. A group or page may carry a role, front, main, appendix, or back, which says how it counts when numbering is on and where it belongs in the book; the default is main. An entry "generate: toc" is a page the run writes, a full table of contents with links, named toc unless "name" says otherwise and titled Contents unless "title" does. Left empty, tools that need an order guess one and say so.
