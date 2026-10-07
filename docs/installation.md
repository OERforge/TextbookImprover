# Installation

How to get the tools, what they need, and how to check the result. There's no initial configuration step for the tools themselves: `convert.py` finds its filters, schemas, and the shared library by path relative to itself, so they work from wherever you put them.

v0.5 is developed and tested on Ubuntu 24.04 with Pandoc 3.12 (and 3.11 still passes every suite): on Windows under WSL 2, which is what the maintainer runs, and in an Ubuntu container, which is where the test suites run before a release. Nothing here is Windows-specific or WSL-specific, and the same commands work on a Linux machine or on macOS with Homebrew in place of `apt`.

## On Windows: WSL first

The tools are Linux command-line programs. On Windows they run under the Windows Subsystem for Linux, which gives you Ubuntu inside Windows with your Windows drives visible under `/mnt/c`. Microsoft's [Set up a WSL development environment](https://learn.microsoft.com/en-us/windows/wsl/setup/environment) covers installing it and opening a terminal; the default distribution, Ubuntu, is the one these instructions assume.

Once you have an Ubuntu terminal, bring it up to date before installing anything:

```bash
sudo apt update && sudo apt upgrade
```

A book kept on the Windows side works (`cd /mnt/c/Users/you/Documents/book`), but a conversion of a large book is noticeably faster with the sources under your Linux home directory. With a terminal open, carry on below.

## Getting the tools

Two ways, and nothing to build either way. A release is a fixed set of files you can point a book at; a clone is the same files plus the history, and `git pull` updates them.

**The latest release.** Download and unpack it anywhere:

```bash
mkdir -p ~/tools && cd ~/tools
curl -L -o TextbookImprover-0.5.tar.gz \
  https://github.com/OERforge/TextbookImprover/archive/refs/tags/v0.5.tar.gz
tar xzf TextbookImprover-0.5.tar.gz        # gives ~/tools/TextbookImprover-0.5
```

The [releases page](https://github.com/OERforge/TextbookImprover/releases) lists every version with its changelog; replace `v0.5` and `0.5` above to take a different one. A `.zip` of the same files is there too, for unpacking on the Windows side.

**Or a clone**, if you'd rather follow the project or send a patch:

```bash
sudo apt install git
git clone https://github.com/OERforge/TextbookImprover.git ~/tools/TextbookImprover
```

Either way, the directory you now have is what the rest of the documentation calls `$T`, and setting that in your shell makes every command here copy-and-pasteable:

```bash
export T=~/tools/TextbookImprover-0.5      # or ~/tools/TextbookImprover for a clone
python3 $T/bin/convert.py --help
```

Put that `export` line in `~/.bashrc` (see [below](#optional-the-full-validators) for what that file is and how to edit it) and it's set in every terminal. The scripts in `bin/`, `util/`, and `tests/` are executable in both the release archives and a clone, so `$T/bin/convert.py` works as well as `python3 $T/bin/convert.py`; the `python3` form is what these pages use, because it works no matter how the files arrived.

## Requirements

| Tool | Needed for | Install |
|---|---|---|
| `pandoc` | Everything. **Version 3.9 or later**; see below, because Ubuntu's own package is older. | from Pandoc's release page |
| `python3` | Required, 3.9 or later. Runs the driver and every script. | present on Ubuntu |
| PyYAML | Reading configuration | `sudo apt install python3-yaml` |
| `file` | Detecting real image types | present on Ubuntu |
| `html5lib` | Recommended. Parsing pages saved from the web (`unpack-site.py`), the way a browser does; without it `lxml` is used, and without either `unpack-site.py` stops | `sudo apt install python3-html5lib` |
| `lxml` | Optional. Full schema validation of the manifest; without it a smaller set of checks runs. | `sudo apt install python3-lxml` |
| `pypdf` | `--toc` with a PDF, and checking a PDF the run builds or the audit reads; an EPUB needs nothing | `sudo apt install python3-pypdf` |
| LuaLaTeX | A `pdf` target only; see [below](#for-a-pdf-target-lualatex) | TeX Live 2026 |
| pdfLaTeX or LuaLaTeX, and `pdftocairo` | A LaTeX source with drawings or PDF images, which become SVG ([LaTeX sources](latex.md)); without them they're left out of the pages | TeX Live; `sudo apt install poppler-utils` |
| TeX's `latex-tagging-status` package | A LaTeX source's copy made for tagging, whose class and packages are checked against the tagging project's status list ([LaTeX sources](latex.md#the-source-target)); without it, the run says how to install it and checks nothing | `tlmgr install latex-tagging-status`; MiKTeX installs it on demand |
| `zip` | Only if you package with the printed command instead of `--zip` | `sudo apt install zip` |

**Pandoc has to come from Pandoc.** `sudo apt install pandoc` on Ubuntu 24.04 gives 3.1.3, which this project refuses to run with: Pandoc 3.6 and older write tables without cell spans, so a table with merged cells loses them silently, and several things the filter relies on arrived later. Install the `.deb` from [Pandoc's releases](https://github.com/jgm/pandoc/releases) instead:

```bash
curl -L -O https://github.com/jgm/pandoc/releases/download/3.12/pandoc-3.12-1-amd64.deb
sudo apt install ./pandoc-3.12-1-amd64.deb
pandoc --version | head -1
```

Pandoc 3.9 is a hard requirement, checked before any work starts. Versions above it still differ in ways that show up here — newer releases read Word caption paragraphs into table captions, older ones don't — so the same document can produce different reports on different machines. Neither is wrong; the sidecar files absorb the difference.

**Python packages come from `apt`, not `pip`.** Ubuntu 24.04 manages its Python installation, so `pip3 install pypdf` stops with `error: externally-managed-environment` (and on a fresh WSL install `pip3` isn't there to begin with). The `python3-*` packages in the table are the ones to use. If you need a version newer than Ubuntu ships, make a virtual environment for it (`python3 -m venv ~/venv && ~/venv/bin/pip install pypdf`) and run the tools with that interpreter.

## Optional: the full validators

Every run [checks its output](checking.md) with nothing but Python. Two validators know the specifications in full and are used as well when they're present; both are Java, and the Nu checker needs **Java 17 or later** (its own classes are built for 11, but it bundles a Jetty library built for 17, and Java 11 fails on that with `UnsupportedClassVersionError`). epubcheck is happy on 11. Nothing else in the project needs Java, and a run without the validators loses only their findings.

```bash
sudo apt install openjdk-17-jre-headless       # Java 17, about 50 MB

mkdir -p ~/tools
curl -L -o /tmp/epubcheck.zip https://github.com/w3c/epubcheck/releases/download/v5.4.0/epubcheck-5.4.0.zip
unzip -o /tmp/epubcheck.zip -d ~/tools          # gives ~/tools/epubcheck-5.4.0/epubcheck.jar
curl -L -o ~/tools/vnu.jar https://github.com/validator/validator/releases/download/latest/vnu.jar
```

Then tell the run where they are. The two lines below go in `~/.bashrc`, the file bash reads every time you open a terminal, so you don't have to set them again. Open it with a text editor — `nano ~/.bashrc` is the easiest if you don't already have a preference; `vi` and `vim` are there too — scroll to the end, add the lines, and save (in `nano`, Ctrl+O then Enter to write, Ctrl+X to leave):

```bash
export EPUBCHECK_JAR="$HOME/tools/epubcheck-5.4.0/epubcheck.jar"
export VNU_JAR="$HOME/tools/vnu.jar"
```

Open a new terminal (or run `source ~/.bashrc` in this one) and check:

```bash
java -jar "$EPUBCHECK_JAR" --version
java -jar "$VNU_JAR" --version
```

The next `convert.py` reports `epubcheck ran on 1 EPUB(s)` and `The Nu HTML checker ran on N page(s)`. If `java -version` still reports 11 after installing 17 (Ubuntu keeps both), `sudo update-alternatives --config java` picks the one the run sees. A `vnu:failed` finding carries the checker's own exception, which names the cause.

Two notes on versions. Ubuntu packages `epubcheck` as well (`sudo apt install epubcheck`), which the run finds on the path with no variable set; it's 4.2.6 on 24.04, several years behind, and it checks EPUB 3 well enough that either works. And the `latest` link for `vnu.jar` moves with each release, which is what you want for a validator; the version it prints is the one to note if a finding needs discussing.

## For a PDF target: LuaLaTeX

A `pdf` target writes the book through Pandoc's LaTeX writer and LuaLaTeX, with LaTeX's tagging switched on, so it needs a TeX distribution recent enough to tag. The LaTeX Project's [tagging project](https://latex3.github.io/tagging-project/) describes tagging as usable in production since the LaTeX release of 2025-11-01, for documents that keep to packages that support it, and TeX Live 2026 ships that; what's verified here is LaTeX 2026-06-01, tagpdf 1.0g, and latex-lab 2026-06-01a. **Ubuntu's `texlive` packages are TeX Live 2023 on 24.04, too old to tag a book properly**, so install TeX Live from the TeX Live project instead. A build checks the release first (`\fmtversion`, which LuaLaTeX reports) and stops on anything older than 2025-11-01, saying which release it found; without that check, Ubuntu 24.04's LaTeX (2023-11-01) stops on a missing `pdfmanagement-testphase.sty`, which older releases load for `\DocumentMetadata` and current ones have replaced. The `tlmgr` that comes with Debian's and Ubuntu's texlive packages can't add it: it runs in a user mode that isn't set up, and installs nothing into the system's TeX Live. When a TeX Live from Ubuntu and one from the TeX Live project are both installed, the one earlier on the path is the one used: `which lualatex` says which. Nothing else in the project needs TeX, and a book without a `pdf` target never looks for it.

Verified here: [TinyTeX](https://github.com/rstudio/tinytex-releases), a small TeX Live 2026, brought up to date and given the packages the tagging code and Pandoc's template load that it lacks.

```bash
curl -L -o /tmp/TinyTeX.tar.xz https://github.com/rstudio/tinytex-releases/releases/download/v2026.09/TinyTeX-linux-x86_64-v2026.09.tar.xz
tar xJf /tmp/TinyTeX.tar.xz -C ~          # gives ~/.TinyTeX
export PATH="$HOME/.TinyTeX/bin/x86_64-linux:$PATH"    # and add this line to ~/.bashrc
tlmgr update --self --all
tlmgr install latex-lab tagpdf luamml luatexbase selnolig luacolor lua-ul footnotehyper xurl multirow
lualatex --version | head -1
```

Pandoc's template loads the first five for every book; `luacolor` and `lua-ul` when the book has underlined or struck-out text (the statistics book does), and `xurl` when it's installed, which is better than not (it lets a long address break anywhere). Pandoc 3.11's template also loads `footnotehyper` when it's there; 3.12's writes notes in tables itself and doesn't.

A book with SVG images needs `rsvg-convert` for its PDF (`sudo apt install librsvg2-bin`); the build stops and says so if it's missing. DejaVu Sans, which most Linux desktops have already (`sudo apt install fonts-dejavu-core` if not), supplies characters Latin Modern lacks, such as the circled digits of an AsciiDoc book's code callouts.

For the PDF's table captions and empty paragraph elements, `pikepdf` too (`pip install pikepdf`, or `sudo apt install python3-pikepdf`); without it the run says so and leaves both as LaTeX tags them, and the PDF suite skips. `pdf.figures: section` needs `placeins` (`tlmgr install placeins`). `multirow` is for a table with a cell spanning rows, which Pandoc's template loads only when a book has one; the PDF suite's book does.

A LaTeX book's PDF is built from the book's own LaTeX ([LaTeX sources](latex.md#the-pdf-target)), by `latexmk`, which TinyTeX and TeX Live include, and with the packages the book itself loads, which `tlmgr` installs as below. The copy loads `unicode-math` for its formulas' MathML, which TinyTeX has, and, for a book that uses pdfTeX's own commands or tests for pdfTeX by `\pdfoutput`, `luatex85`, which TinyTeX lacks (`tlmgr install luatex85`).

Two more kinds of package, depending on the book. A book with passages in another language needs that language's `babel-` and `hyphen-` packages (`tlmgr install babel-german hyphen-german` for German), or LuaLaTeX stops with babel's `Unknown option`. And whatever a `pdf.metadata` file's `header-includes` loads has to be installed too (`hanging`, say). When LuaLaTeX stops on `File 'something.sty' not found`, `tlmgr search --global --file /something.sty` names the package to install.

`tlmgr` downloads from a CTAN mirror chosen for you. On a network that only allows named hosts, set a fixed one first, since the chooser redirects: `tlmgr option repository https://ctan.math.illinois.edu/systems/texlive/tlnet` is the one used here.

A full TeX Live 2026 from the [TeX Live installer](https://tug.org/texlive/quickinstall.html) has everything above already, at several gigabytes. It hasn't been tried here.

## Optional: veraPDF

[veraPDF](https://verapdf.org) checks a PDF against PDF/UA and PDF/A. When it's installed, the output check runs it on every PDF a run builds, and the [audit](auditing.md) on every PDF it's given. It's Java, like the other validators, and installs from its own site without its graphical parts:

```bash
curl -L -o /tmp/verapdf.zip https://software.verapdf.org/releases/verapdf-installer.zip
unzip -o /tmp/verapdf.zip -d /tmp/verapdf
java -DINSTALL_PATH="$HOME/tools/verapdf" -jar /tmp/verapdf/verapdf-greenfield-*/verapdf-izpack-installer-*.jar -options-system
export VERAPDF="$HOME/tools/verapdf/verapdf"    # and add this line to ~/.bashrc
"$VERAPDF" --version
```

The run finds it through `VERAPDF` or as `verapdf` on the path. veraPDF chooses its profiles from what the file claims: for a PDF claiming PDF/UA-2 and PDF/A-4f, veraPDF 1.30 applies PDF/UA-2 with Tagged PDF, PDF/A-4f, and both WTPDF 1.0 profiles.

## Checking the whole setup

From the directory you cloned into:

```bash
bash tests/run-all.sh
```

Twelve suites run; the ones needing a validator print `skip` with the reason when its jar isn't set, so a pass without Java means the pipeline is sound and the validators are simply absent.
