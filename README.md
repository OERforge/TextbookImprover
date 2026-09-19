# TextbookImprover

Converts a directory of Word documents into more-accessible HTML pages, packages them as an IMS Common Cartridge for import into Brightspace or another LMS, and can assemble them into an EPUB.

Licensed GPL 3.0. See `LICENSE` for more info.

The initial release of these scripts was created by Robert Szarka and supported by a grant from the West Virginia Higher Education Policy Commission.

## What it does

Two halves, which share a configuration and the book's table of contents, and nothing else.

**Conversion** turns each `.docx` into an HTML page through Pandoc and a Lua filter, and makes the page more accessible on the way: figures get real captions tied to their images, data tables get captions, header cells, and a focusable scroll region, images get their alt text checked and their layout spacers marked, and equations stay equations. Where the source doesn't say something a screen reader needs -- which column heads a table, what a picture shows -- the run guesses from the file, writes its guess into a sidecar CSV you can correct, and reports what still needs a person.

**Packaging** turns a directory of pages into a Common Cartridge, with the book's table of contents as the module tree, and validates the manifest against the IMS schemas.

Everything a run decides is written down: reports name what to fix, sidecar files hold what you decided, and the configuration file lists every setting with a sentence explaining it.

## Quick start

You need Pandoc 3.9 or later, Python 3.9 or later, and PyYAML; see [Installation](docs/installation.md) for the rest.

```bash
T=/path/to/tools                       # where you cloned this
cd /path/to/your/docx/files

bash $T/bin/convert.sh                 # 1. convert: one .html per .docx, plus reports
```

The first run converts everything, then stops and writes `packaging-sample.yaml`, because a manifest needs two things only you can supply. Set `identifier` and `title` near the top of that file and rename it:

```bash
mv packaging-sample.yaml packaging.yaml
bash $T/bin/convert.sh                 # 2. builds imsmanifest.xml
bash $T/bin/convert.sh --zip           # 3. ... and the .imscc archive
```

If you have the book's PDF, run `bash $T/bin/convert.sh --toc book.pdf` *before* renaming the sample: it orders the pages from the PDF's own table of contents, with the real chapter titles. [A first run](docs/first-run.md) walks through all of this, including the reports and sidecars you will work through afterwards.

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
| [Brightspace](docs/brightspace.md) | What importing and deleting actually do there, confirmed by D2L |
| [Testing](docs/testing.md) | The test suites and what each is load-bearing for |
| [Utilities](docs/utilities.md) | The tools in `util/`: surveying a corpus, checking a source, comparing runs |
| [Troubleshooting and known limits](docs/troubleshooting.md) | Cloud drives, common failures, validator defects, what isn't fixed |

[CHANGELOG.md](CHANGELOG.md) records what changed in each version; [ROADMAP.md](ROADMAP.md) records what is planned and why.
