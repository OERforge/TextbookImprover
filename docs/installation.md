# Installation

How to get the tools, what they need, and how to check the result. There's no initial configuration step for the tools themselves: `convert.py` finds its filters, schemas, and the shared library by path relative to itself, so they work from wherever you put them.

v0.5 is developed and tested on Ubuntu 24.04 with Pandoc 3.11: on Windows under WSL 2, which is what the maintainer runs, and in an Ubuntu container, which is where the test suites run before a release. Nothing here is Windows-specific or WSL-specific, and the same commands work on a Linux machine or on macOS with Homebrew in place of `apt`.

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
| `pypdf` | `--toc` with a PDF only; an EPUB needs nothing | `sudo apt install python3-pypdf` |
| `zip` | Only if you package with the printed command instead of `--zip` | `sudo apt install zip` |

**Pandoc has to come from Pandoc.** `sudo apt install pandoc` on Ubuntu 24.04 gives 3.1.3, which this project refuses to run with: Pandoc 3.6 and older write tables without cell spans, so a table with merged cells loses them silently, and several things the filter relies on arrived later. Install the `.deb` from [Pandoc's releases](https://github.com/jgm/pandoc/releases) instead:

```bash
curl -L -O https://github.com/jgm/pandoc/releases/download/3.11/pandoc-3.11-1-amd64.deb
sudo apt install ./pandoc-3.11-1-amd64.deb
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

## Checking the whole setup

From the directory you cloned into:

```bash
bash tests/run-all.sh
```

Twelve suites run; the ones needing a validator print `skip` with the reason when its jar isn't set, so a pass without Java means the pipeline is sound and the validators are simply absent.
