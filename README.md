# TextbookImprover

Converts a directory of Word or Markdown documents into more-accessible HTML pages, packages them as an IMS Common Cartridge for import into Brightspace or another LMS, and can assemble them into an EPUB.

Licensed GPL 3.0. See `LICENSE` for more info.

The initial release of these scripts was created by Robert Szarka and supported by a grant from the West Virginia Higher Education Policy Commission.

## What it does

Reads a book's sources, one file per page (Word, Markdown, or a page written by hand as HTML), into one intermediate per page, makes each page more accessible on the way, and writes every output the configuration asks for from the same intermediates: HTML pages, an EPUB, Markdown source, and a Common Cartridge for import into an LMS. The book's structure, declared once as `contents` or guessed from the files and the publisher's PDF, is the cartridge's module tree, the EPUB's table of contents, and the generated contents page alike.

**Conversion** runs each source through Pandoc and a Lua filter that makes the page more accessible: figures get real captions tied to their images, data tables get captions, header cells, and a focusable scroll region, images get their alt text checked and their layout spacers marked, equations stay equations, and cross-references that Word's export left dangling land. Where the source doesn't say something a screen reader needs, the run reports it, and a sidecar file holds what you decide; after a Markdown round trip, the decisions are in the source itself.

**Packaging** turns the pages into a Common Cartridge with the book's structure as the module tree, validated against the IMS schemas, and into an EPUB 3 that validates with epubcheck and says what it can claim about itself.

**Every run checks what it wrote**: dead links and fragments, missing alt text, heading order, invalid ids, tables without headers or caption, and, when the validators are installed, epubcheck and the Nu HTML checker. The same checks, plus what a Word, Markdown, or PDF file says about itself, run on any file without converting it: `audit.py` writes a findings CSV and a report.

Everything a run decides is written down: reports name what to fix, sidecar files hold what you decided, and the configuration file lists every setting with a sentence explaining it.

## Quick start

You need Pandoc 3.9 or later, Python 3.9 or later, and PyYAML; see [Installation](docs/installation.md) for the rest.

```bash
T=/path/to/tools                       # where you cloned this
cd /path/to/your/docx/files

python3 $T/bin/convert.py                 # 1. convert: html/, one page per source, plus reports
```

The first run converts everything, then stops and writes `packaging-sample.yaml`, because a manifest needs two things only you can supply. Set `identifier` and `title` near the top of that file and rename it:

```bash
mv packaging-sample.yaml packaging.yaml
python3 $T/bin/convert.py                 # 2. builds imsmanifest.xml
python3 $T/bin/convert.py --zip           # 3. ... and the .imscc archive
```

If you have the book's PDF or EPUB, run `python3 $T/bin/convert.py --toc book.pdf` (or `--toc book.epub`) *before* renaming the sample: it orders the pages from the book's own table of contents, with chapters as modules. To build more than one output, declare targets in `conversion.yaml`:

```yaml
targets:
  html:
    format: html              # writes html/
  epub:
    format: epub3             # writes epub/<identifier>.epub
  src:
    format: markdown          # writes src/, the book as Markdown source
```

Each target writes into a directory of its own; the content directory keeps the sources, the intermediates, the sidecars, and the reports. See [Configuration](docs/configuration.md) for targets, editions, and the book's structure, and [Markdown sources](docs/markdown.md) for Markdown in and out.

## Documentation

| Page | What it covers |
| --- | --- |
| [Installation](docs/installation.md) | Prerequisites and how to check them |
| [A first run](docs/first-run.md) | Start to finish, what each run writes, exit codes |
| [How it works](docs/architecture.md) | The pieces, what conversion does to a page, running the filter alone |
| [Configuration](docs/configuration.md) | How the configuration files fit together, precedence, contents, migration from v0.1 |
| [Project settings](docs/project-settings.md) | Reference, generated from the schema |
| [Conversion settings](docs/conversion-settings.md) | Reference, generated from the schema |
| [Packaging settings](docs/packaging-settings.md) | Reference, generated from the schema |
| [Sidecars and reports](docs/sidecars.md) | Each report, each sidecar, and what goes in them |
| [Building the cartridge](docs/packaging.md) | The packager, ordering from a PDF, validating the manifest |
| [Building an EPUB](docs/epub.md) | One EPUB per book from the same pages and the same contents, and what it claims about itself |
| [Checking the output](docs/checking.md) | What every run checks about the pages and EPUBs it wrote, and what it doesn't |
| [Auditing](docs/auditing.md) | `audit.py`: what is wrong with a Word, Markdown, HTML, EPUB, or PDF file, without converting it; the findings format every check shares |
| [HTML sources](docs/html.md) | An `.html` that `contents` marks `convert: true` is a source: what is read from it, what isn't, and why converting this pipeline's own pages changes nothing |
| [A book saved from the web](docs/site-input.md) | `unpack-site.py`: browser saves or `.mhtml` into pages whose every reference is local, the generator recognized, the order read from the site's own menus |
| [AsciiDoc sources](docs/asciidoc.md) | `.adoc` chapters as sources, a master file that includes them as the book's order, and what is done on reading that the reader leaves undone |
| [An EPUB as the source](docs/epub-input.md) | `unpack-epub.py`: a publisher's EPUB into pages, media, and a `project.yaml` with its metadata and its navigation as `contents`; a book that is one file |
| [Markdown sources](docs/markdown.md) | A `.md` beside the sources is a page: what it can declare, how its images travel, and a book set up for a Pandoc PDF build |
| [Splitting pages](docs/splitting.md) | One page per heading from a source that arrived as one file per chapter, or one file |
| [Brightspace](docs/brightspace.md) | What importing and deleting actually do there, confirmed by D2L |
| [Testing](docs/testing.md) | The test suites and what each is load-bearing for |
| [Utilities](docs/utilities.md) | The tools in `util/`: surveying a corpus, checking a source, comparing runs |
| [Troubleshooting and known limits](docs/troubleshooting.md) | Cloud drives, common failures, validator defects, what isn't fixed |

[CHANGELOG.md](CHANGELOG.md) records what changed in each version; [ROADMAP.md](ROADMAP.md) records what is planned and why.
