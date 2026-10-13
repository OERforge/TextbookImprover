# Installation

How to get the tools, what they need, and how to check the result. There's no initial configuration step for the tools themselves: `convert.py` finds its filters, schemas, and the shared library by path relative to itself, so they work from wherever you put them.

This version is developed and tested on Ubuntu 24.04 with Pandoc 3.12.1 and 3.12: on Windows under WSL 2, which is what the maintainer runs, and in an Ubuntu container, which is where the test suites run before a release, both with the Python packages Ubuntu 24.04 ships (Python 3.12, pypdf 4.0.2, pikepdf 8.7.1) and with newer ones (pypdf 5.9, pikepdf 10.13). Its suites pass too with Ubuntu 22.04's Python (3.10) and the versions of its packages that 22.04 ships, pypdf aside ([Which Ubuntu you have](#which-ubuntu-you-have)). Nothing here is Windows-specific or WSL-specific, and the same commands work on a Linux machine or on macOS with Homebrew in place of `apt`.

## On Windows: WSL first

The tools are Linux command-line programs. On Windows they run under the Windows Subsystem for Linux, which gives you Ubuntu inside Windows with your Windows drives visible under `/mnt/c`. Microsoft's [Set up a WSL development environment](https://learn.microsoft.com/en-us/windows/wsl/setup/environment) covers installing it and opening a terminal; its default distribution, Ubuntu, is the one these instructions assume.

Once you have an Ubuntu terminal, bring it up to date before installing anything:

```bash
sudo apt update && sudo apt upgrade
```

A book kept on the Windows side works (`cd /mnt/c/Users/you/Documents/book`), but a conversion of a large book is noticeably faster with the sources under your Linux home directory. With a terminal open, carry on below.

## Which Ubuntu you have

These instructions are for Ubuntu 24.04 or later. To see which you have, run this in the Ubuntu terminal:

```bash
grep PRETTY_NAME /etc/os-release
```

If it says 24.04 or later, go on to [Getting the tools](#getting-the-tools). If it says 22.04, the tools work there too, but there's a choice to make first. The three ways, best first:

**1. Upgrade it to 24.04.** Everything you have comes along: your files, your settings, and what you've installed. It can take an hour or more, most of it downloading. Under WSL, make a backup first that you can go back to. Open PowerShell from the Windows Start menu (it's a Windows program, not the Ubuntu terminal) and run:

```powershell
wsl --list --verbose
wsl --export Ubuntu-22.04 "$HOME\ubuntu-22.04-backup.tar"
```

The first command lists your Linux installations by name; if yours isn't called `Ubuntu-22.04` (it may be just `Ubuntu`), use the name it shows in the second. The backup is one file in your Windows home folder (`C:\Users\you`), as large as everything in the installation, often several gigabytes. If the upgrade goes wrong, `wsl --import` makes a working installation from it again ([Microsoft's list of WSL commands](https://learn.microsoft.com/en-us/windows/wsl/basic-commands) has both).

Canonical's [instructions for upgrading Ubuntu on WSL](https://ubuntu.com/wsl/docs/stable/howto/upgrade-ubuntu/) say the upgrade needs systemd, the program that starts Linux's services. To check, in the Ubuntu terminal:

```bash
ps -p 1 -o comm=
```

If that prints `systemd`, go on. If it prints anything else, open WSL's settings file with `sudo nano /etc/wsl.conf`, add these two lines at the end, and save (Ctrl+O, then Enter, then Ctrl+X to leave):

```ini
[boot]
systemd=true
```

Then close the Ubuntu terminal, run `wsl --shutdown` in PowerShell, and open Ubuntu again; `ps -p 1 -o comm=` should now print `systemd` ([Microsoft's page on systemd in WSL](https://learn.microsoft.com/en-us/windows/wsl/systemd)).

Now the upgrade itself, in the Ubuntu terminal:

```bash
sudo apt update && sudo apt full-upgrade -y
sudo do-release-upgrade
```

It asks a few questions as it goes. Answer `y` to start the upgrade and to remove packages it no longer needs; where it asks whether to replace a settings file you changed, press Enter for the default, which keeps yours. When it asks at the end whether to restart, answer `N`: under WSL, close the terminal, run `wsl --shutdown` in PowerShell, and open Ubuntu again instead. `grep PRETTY_NAME /etc/os-release` should then say 24.04. Run `do-release-upgrade` just the once: from 24.04 it may offer the next release, which these tools haven't been tested on. The installation keeps its old name, `Ubuntu-22.04` say, which does no harm: it's the same installation, so it stays your default and nothing else needs changing. On a Linux machine that isn't WSL, it's the same two commands, with your usual backup first and a real restart at the end.

**2. Install 24.04 beside it** (WSL only). WSL can hold more than one Ubuntu. A new one starts empty, so you'd install the tools there from the top of this page, while the old one carries on as it was. In PowerShell:

```powershell
wsl --list --online
wsl --install -d Ubuntu-24.04
```

The first command lists what can be installed; if 24.04's name there isn't `Ubuntu-24.04`, use the one it shows. The new Ubuntu asks you to choose a user name and password the first time it starts, as the first one did; after that it's in the Start menu.

Then make the new one your default. Until you do, typing `wsl`, and anything else that opens "your" Ubuntu without naming one, still opens the old 22.04, and it's easy to go on working there without noticing. In PowerShell:

```powershell
wsl --set-default Ubuntu-24.04
wsl --list --verbose
```

In the list, the default has a `*` before its name; it should now be `Ubuntu-24.04`. Windows Terminal keeps a separate setting: each Ubuntu has its own profile there, and the one a new tab opens is chosen under Settings, Startup, Default profile. Whichever terminal you use, `grep PRETTY_NAME /etc/os-release` says which Ubuntu you're in.

The old installation's files stay where they were; Windows File Explorer reaches them at `\\wsl$\` followed by its name (`\\wsl$\Ubuntu-22.04`, say), so you can copy a book across.

**3. Stay on 22.04.** Everything on this page works there with one change. Ubuntu 22.04 has no `python3-pypdf` package, so `sudo apt install python3-pypdf` stops with `Unable to locate package`; install pypdf with Python's own installer instead:

```bash
sudo apt install python3-pip
pip3 install --user pypdf
```

On 22.04 that's the right way: unlike 24.04, it lets pip install into your home folder (the `--user`), leaving Ubuntu's own Python alone. Every other package on this page comes from `apt` as written.

## Getting the tools

Two ways, and nothing to build either way. A release is a fixed set of files you can point a book at; a clone is the same files plus the history, and `git pull` updates them.

**The latest release.** Download and unpack it anywhere:

```bash
mkdir -p ~/tools && cd ~/tools
curl -L -o TextbookImprover-0.9.tar.gz \
  https://github.com/OERforge/TextbookImprover/archive/refs/tags/v0.9.tar.gz
tar xzf TextbookImprover-0.9.tar.gz        # gives ~/tools/TextbookImprover-0.9
```

The [releases page](https://github.com/OERforge/TextbookImprover/releases) lists every version with its changelog; replace `v0.9` and `0.9` above to take a different one. A `.zip` of the same files is there too, for unpacking on the Windows side.

**Or a clone**, if you'd rather follow the project or send a patch:

```bash
sudo apt install git
git clone https://github.com/OERforge/TextbookImprover.git ~/tools/TextbookImprover
```

Either way, the directory you now have is what the rest of the documentation calls `$T`, and setting that in your shell makes every command here copy-and-pasteable:

```bash
export T=~/tools/TextbookImprover-0.9      # or ~/tools/TextbookImprover for a clone
python3 $T/bin/convert.py --help
```

Put that `export` line in `~/.bashrc` (see [below](#optional-the-full-validators) for what that file is and how to edit it) and it's set in every terminal. The scripts in `bin/`, `util/`, and `tests/` are executable in both the release archives and a clone, so `$T/bin/convert.py` works as well as `python3 $T/bin/convert.py`; the `python3` form is what these pages use, because it works no matter how the files arrived.

## Requirements

| Tool | Needed for | Install |
|---|---|---|
| `pandoc` | Everything but PowerPoint decks ([Slides](slides.md)). **Version 3.9 or later**; see below, because Ubuntu's own package is older. | from Pandoc's release page |
| `python3` | Required, 3.9 or later. Runs the driver and every script. | present on Ubuntu |
| PyYAML | Reading configuration | `sudo apt install python3-yaml` |
| `file` | Detecting real image types | present on Ubuntu |
| `html5lib` | Recommended. Parsing pages saved from the web (`unpack-site.py`), the way a browser does; without it `lxml` is used, and without either `unpack-site.py` stops | `sudo apt install python3-html5lib` |
| `lxml` | Optional. Full schema validation of the manifest; without it a smaller set of checks runs. | `sudo apt install python3-lxml` |
| `pypdf` | `--toc` with a PDF, and checking a PDF the run builds or the audit reads; an EPUB needs nothing | `sudo apt install python3-pypdf`; on Ubuntu 22.04, `pip3 install --user pypdf` ([above](#which-ubuntu-you-have)) |
| LuaLaTeX | A `pdf` target only; see [below](#for-a-pdf-target-lualatex) | TeX Live 2026 |
| The `ltx-talk`, `lua-unicode-math`, and `newcomputermodern` packages | A `pdf` target for decks written in Markdown ([Slides](slides.md#the-pdf)), which also needs LaTeX 2026-06-01 or later; without them, the run says what to install | `tlmgr install ltx-talk lua-unicode-math newcomputermodern` |
| pdfLaTeX or LuaLaTeX, LaTeX's `preview` package, and `pdftocairo` | A LaTeX source with drawings or PDF images, which become SVG ([LaTeX sources](latex.md)); without them they're left out of the pages | TeX Live (`tlmgr install preview` where it's missing); `sudo apt install poppler-utils` |
| TeX's `latex-tagging-status` package | A LaTeX source's copy made for tagging, whose class and packages are checked against the tagging project's status list ([LaTeX sources](latex.md#the-source-target)); without it, the run says how to install it and checks nothing | `tlmgr install latex-tagging-status`; MiKTeX installs it on demand |
| reveal.js 6 | A `revealjs` target for decks written in Markdown ([Slides](slides.md#the-revealjs-presentation)), which also needs Pandoc 3.12 or later; without it, the run says how to get it | its package, unpacked, and `REVEALJS_DIR` set to its folder; see [below](#for-a-revealjs-target-revealjs) |
| Python's Playwright and its Chromium | Optional, and for the test suites only: twelve of the decks suite's checks try a reveal.js presentation in a browser with them, and skip without them | in a virtual environment; see [below](#optional-for-the-suites-playwright-and-its-chromium) |
| `zip` | Only if you package with the printed command instead of `--zip` | `sudo apt install zip` |

**Pandoc has to come from Pandoc.** `sudo apt install pandoc` on Ubuntu 24.04 gives 3.1.3, which this project refuses to run with: Pandoc 3.6 and older write tables without cell spans, so a table with merged cells loses them silently, and several things the filter relies on arrived later. Install the `.deb` from [Pandoc's releases](https://github.com/jgm/pandoc/releases) instead:

```bash
curl -L -O https://github.com/jgm/pandoc/releases/download/3.12.1/pandoc-3.12.1-1-amd64.deb
sudo apt install ./pandoc-3.12.1-1-amd64.deb
pandoc --version | head -1
```

Pandoc 3.9 is a hard requirement for a book, checked before the book is read; a folder of PowerPoint decks needs no Pandoc, a deck's PowerPoint file (a `pptx` target) needs 3.10.1, whose PowerPoint writer keeps a table and the text around it on one slide, and a deck's reveal.js presentation (a `revealjs` target) needs 3.12, whose template loads reveal.js 6's plugins. Versions above it still differ in ways that show up here — newer releases read Word caption paragraphs into table captions, older ones don't — so the same document can produce different reports on different machines. Neither is wrong; the sidecar files absorb the difference.

**Python packages come from `apt`, not `pip`.** Ubuntu 24.04 manages its Python installation, so `pip3 install pypdf` stops with `error: externally-managed-environment` (and on a fresh WSL install `pip3` isn't there to begin with). The `python3-*` packages in the table are the ones to use. Ubuntu 22.04 doesn't stop pip, and its one gap, pypdf, comes from pip there, as [above](#which-ubuntu-you-have). If you need a version newer than Ubuntu ships, or a package it doesn't ship at all, make a virtual environment that sees Ubuntu's packages as well (`python3 -m venv --system-site-packages ~/venv && ~/venv/bin/pip install pypdf`) and run the tools with that interpreter. The one package anything here takes from pip is Playwright, which only the test suites use, and they don't need it ([below](#optional-for-the-suites-playwright-and-its-chromium)).

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

A `pdf` target writes the book through Pandoc's LaTeX writer and LuaLaTeX, with LaTeX's tagging switched on, so it needs a TeX distribution recent enough to tag. The LaTeX Project's [tagging project](https://latex3.github.io/tagging-project/) describes tagging as usable in production since the LaTeX release of 2025-11-01, for documents that keep to packages that support it. A build here needs 2026-06-01 or later, which TeX Live 2026 has had since its June update: with 2025-11-01, a PDF/UA-1 book and a LaTeX book using enumitem's settings stop, and some formulas, figures, and lists are tagged wrong. What's verified here is LaTeX 2026-06-01, with tagpdf 1.0g and latex-lab 2026-06-01a (TinyTeX, updated) and with tagpdf 1.0c (Debian's TeX Live 2026 of July 2026). A LaTeX source needs TeX too, for its drawings and its own PDF. Nothing else in the project does, and a book without a `pdf` target or LaTeX in it never looks for it.

**What you have now.** In the Ubuntu terminal:

```bash
which lualatex
lualatex --version | head -1
```

- Nothing found: there's no TeX yet. Install one of the two below.
- A path under your home folder, `~/.TinyTeX/bin/...`, and TeX Live 2026: TinyTeX, as below. Go on to [`tlmgr` and `sudo`](#tlmgr-and-sudo).
- A path under `/usr/local/texlive/`, and TeX Live 2026: a TeX Live from its own installer. Go on to [`tlmgr` and `sudo`](#tlmgr-and-sudo), which says what to do if it was installed with `sudo`. TeX Live 2025 there is too old: its LaTeX stopped at 2025-11-01, so install 2026 as below.
- `/usr/bin/lualatex` and "TeX Live 2023/Debian" (2021 on Ubuntu 22.04): Ubuntu's own `texlive` packages, too old to tag a book. A build stops on anything older than LaTeX 2026-06-01, saying which release it found. Install one of the two below; you can leave Ubuntu's in place, since whichever comes first on your path is the one used, and the installation steps put the new one first. The `tlmgr` that comes with Ubuntu's packages can't add to them: it runs in a user mode that isn't set up, and installs nothing.

**Installing one.** Two ways, both TeX Live 2026:

- **TinyTeX**, which is what's tested here: a small TeX Live in your home folder, which you add packages to as you need them, without `sudo`. Use this bundle, the one the command below downloads: TinyTeX's own install script installs a smaller one, TinyTeX-1, which lacks much a book is likely to load.

  ```bash
  curl -L -o /tmp/TinyTeX.tar.xz https://github.com/rstudio/tinytex-releases/releases/download/v2026.09/TinyTeX-linux-x86_64-v2026.09.tar.xz
  tar xJf /tmp/TinyTeX.tar.xz -C ~          # gives ~/.TinyTeX
  export PATH="$HOME/.TinyTeX/bin/x86_64-linux:$PATH"    # and add this line to ~/.bashrc
  tlmgr update --self --all
  lualatex --version | head -1
  ```

- **TeX Live 2026 from its own installer**, [as the TeX Live project describes it](https://tug.org/texlive/quickinstall.html): everything in TeX Live, several gigabytes, so it needs none of the packages below. It goes in `/usr/local/texlive`, which the second line makes yours first, so that you install it as yourself, as the TeX Live project recommends, and its `tlmgr` needs no `sudo`, as TinyTeX's doesn't. The download and installation can take an hour or more.

  ```bash
  cd /tmp
  sudo mkdir -p /usr/local/texlive && sudo chown -R "$USER" /usr/local/texlive
  curl -L -o install-tl-unx.tar.gz https://mirror.ctan.org/systems/texlive/tlnet/install-tl-unx.tar.gz
  zcat < install-tl-unx.tar.gz | tar xf -
  cd install-tl-*
  perl ./install-tl --no-interaction
  export PATH="/usr/local/texlive/2026/bin/x86_64-linux:$PATH"    # and add this line to ~/.bashrc
  lualatex --version | head -1
  ```

Either way, `which lualatex` should now name the one you installed, and `lualatex --version` say TeX Live 2026. A TeX Live 2026 installed before June 2026 has LaTeX 2025-11-01 until `tlmgr update --self --all` brings it up to date; the run checks the release itself and says which it found.

### `tlmgr` and `sudo`

`tlmgr` is TeX Live's package manager, which installs the packages below. TinyTeX, in your home folder, and a TeX Live installed as above are yours, so their `tlmgr` needs no `sudo`, and this page writes the commands that way.

A TeX Live installed with `sudo` (`sudo perl ./install-tl`) belongs to root, so its `tlmgr` can't change it without `sudo`. And `sudo tlmgr` fails too: `sudo` looks for programs in a list of folders of its own (Ubuntu's `secure_path`), which TeX Live's isn't in, so it answers `sudo: tlmgr: command not found`, or runs Ubuntu's own `tlmgr` where Ubuntu's `texlive` packages are installed as well. Either of these works:

- Make it yours, once, and every command on this page works as written:

  ```bash
  sudo chown -R "$USER" /usr/local/texlive
  ```

- Or keep it root's, and give `sudo` the path to `tlmgr` each time: `sudo "$(which tlmgr)" update --self --all` where this page says `tlmgr update --self --all`. That's all it needs, since `tlmgr` puts its own folder first on the path for the programs it runs; `sudo env "PATH=$PATH" tlmgr update --self --all` works as well. The commands the run itself suggests are written this way, with the path, where your TeX needs `sudo`.

Before installing anything, bring `tlmgr` itself up to date, since it refuses to install once TeX Live has released a newer version of it:

```bash
tlmgr update --self
```

`tlmgr` downloads from a CTAN mirror chosen for you. On a network that only allows named hosts, set a fixed one first, since the chooser redirects: `tlmgr option repository https://ctan.math.illinois.edu/systems/texlive/tlnet` is the one used here.

### Everything at once

This installs every TeX package and program anything in the project uses, the test suites' books included, so nothing below has to be installed piece by piece. A full TeX Live, from its own installer, has every one of the TeX packages already, so it needs only the last line; TinyTeX needs them all.

```bash
tlmgr install latex-lab tagpdf luamml luatexbase selnolig luacolor lua-ul footnotehyper xurl multirow placeins
tlmgr install luatex85 preview latex-tagging-status
tlmgr install ltx-talk lua-unicode-math newcomputermodern
tlmgr install amsfonts amsmath babel-english caption fancyhdr framed geometry grfext mdframed
tlmgr install pgf soul tabto-ltx tex-gyre titlesec tools ulem wasysym wrapfig
sudo apt install librsvg2-bin poppler-utils ghostscript fonts-dejavu-core python3-pikepdf
```

The rest of this section says what each is for.

### What each is for

The first five TeX packages are the tagging code and what Pandoc's template loads for every book; `luacolor` and `lua-ul` are for underlined or struck-out text (the statistics book has some), and `xurl` lets a long address break anywhere, which the template uses when it's installed. Pandoc 3.11's template also loads `footnotehyper` when it's there; 3.12's writes notes in tables itself and doesn't. `multirow` is for a table with a cell spanning rows, which Pandoc's template loads only when a book has one; the PDF suite's book does. `pdf.figures: section` needs `placeins`.

A book with SVG images needs `rsvg-convert` for its PDF (`librsvg2-bin`); the build stops and says so if it's missing. DejaVu Sans, which most Linux desktops have already (`fonts-dejavu-core`), supplies characters Latin Modern lacks, such as the circled digits of an AsciiDoc book's code callouts, and `newcomputermodern`, installed for decks, the circled letters of OpenStax's math books. For the PDF's table captions and empty paragraph elements, `pikepdf` (`python3-pikepdf`); without it the run says so and leaves both as LaTeX tags them, and the PDF suite skips.

A LaTeX book's PDF is built from the book's own LaTeX ([LaTeX sources](latex.md#the-pdf-target)), by `latexmk`, which TinyTeX and TeX Live include, and with the packages the book itself loads. The copy loads `unicode-math` for its formulas' MathML, which TinyTeX has, and, for a book that uses pdfTeX's own commands or tests for pdfTeX by `\pdfoutput`, `luatex85`. A LaTeX book's drawings are each made a page of LaTeX's `preview` package, and its PDF images and drawings become SVG through `pdftocairo` (`poppler-utils`). Its PDF figures that don't embed their fonts, as R's plots don't, are rewritten in the copy with them embedded, which PDF/UA requires: by Ghostscript where it's installed, and otherwise by `pdftocairo`. `latex-tagging-status` lets the run check a book's packages against the tagging project's list of what tagging supports.

`ltx-talk`, `lua-unicode-math`, and `newcomputermodern` are for a deck's PDF: ltx-talk is the presentation class a deck written in Markdown is built with, and it loads the other two, the math and the fonts it sets a deck in, which TinyTeX doesn't install with it. It needs LaTeX 2026-06-01 or later, TeX Live 2026 ([Slides](slides.md#the-pdf)).

The TeX packages in the last two `tlmgr` lines are what the LaTeX suite's small books load (`tests/run-latex-tests.py`), with `luatex85` and `preview`. Its first checks name a LaTeX too old for the PDF target and any of them that are missing, with the line that installs them, and `rsvg-convert` too. It has one check of Ghostscript's way of embedding fonts, which skips without Ghostscript.

Two more kinds of package, depending on the book. A book with passages in another language needs that language's `babel-` and `hyphen-` packages (`tlmgr install babel-german hyphen-german` for German), or LuaLaTeX stops with babel's `Unknown option`. And whatever a `pdf.metadata` file's `header-includes` loads, and whatever else a book of your own loads, has to be installed too (`hanging`, say). When LuaLaTeX stops on `File 'something.sty' not found`, `tlmgr search --global --file /something.sty` names the package to install, and the run says so.

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

## For a revealjs target: reveal.js

A deck's reveal.js presentation loads reveal.js from a copy beside it, which the run takes from the folder `REVEALJS_DIR` names: reveal.js 6, which Pandoc 3.12's template is written for. reveal.js is a set of files ready to use, with nothing to build, and getting it needs no Node.js: its package on the npm registry, unpacked, is the folder.

```bash
mkdir -p ~/tools && cd ~/tools
curl -L -o reveal.js-6.0.2.tgz https://registry.npmjs.org/reveal.js/-/reveal.js-6.0.2.tgz
mkdir -p reveal.js-6.0.2
tar xzf reveal.js-6.0.2.tgz -C reveal.js-6.0.2 --strip-components=1    # gives ~/tools/reveal.js-6.0.2
```

Then tell the run where it is, with this line in `~/.bashrc`, as for the validators ([above](#optional-the-full-validators)):

```bash
export REVEALJS_DIR="$HOME/tools/reveal.js-6.0.2"
```

Open a new terminal (or run `source ~/.bashrc`) and check that it names reveal.js:

```bash
ls "$REVEALJS_DIR/dist/reveal.js" && grep -m1 '"version"' "$REVEALJS_DIR/package.json"
```

If you have Node.js's `npm` already, `npm install reveal.js@6` in a folder of your own does the same, and `REVEALJS_DIR` is then that folder's `node_modules/reveal.js`. A later 6.x works as well: the run checks the major version, and the files it copies. reveal.js is MIT-licensed, and its license goes with each copy.

### Optional, for the suites: Playwright and its Chromium

Nothing here needs these but twelve of the decks suite's checks. With `REVEALJS_DIR` set, the suite builds presentations and checks what was written; the twelve then open them in a browser, to see what the presentation does there (focus moving to a slide's title, slides fitted, a narrow window's page), through Python's Playwright and the Chromium it installs. Without them, those twelve skip, saying so, and everything else runs. They're worth installing to work on the presentations themselves, and can otherwise be left out: together they take about 570 MB.

Ubuntu doesn't package Playwright, and Ubuntu 24.04's Python won't take a package from pip ([above](#requirements)), so it goes in a virtual environment that sees Ubuntu's own packages too (`--system-site-packages`), and the suites run with that environment's Python:

```bash
sudo apt install python3-venv
python3 -m venv --system-site-packages ~/venv
~/venv/bin/pip install playwright
~/venv/bin/python -m playwright install --with-deps --only-shell chromium
```

`--only-shell` installs only the Chromium that runs without a window, which is all the suites use: about 320 MB, in `~/.cache/ms-playwright`, where Chromium in full would add 600 MB. `--with-deps` installs the libraries and fonts it needs with `apt`, which asks for your password, about 110 MB of them where none is installed yet; Playwright itself is about 130 MB (sizes measured with Playwright 1.56 and its Chromium 141). To check that it starts:

```bash
~/venv/bin/python -c "from playwright.sync_api import sync_playwright as p; s = p().start(); print(s.chromium.launch().version); s.stop()"
```

which prints Chromium's version. Then run the suites with the environment active:

```bash
source ~/venv/bin/activate
bash tests/run-all.sh
```

Activating it lasts for that terminal (`deactivate` ends it early). Add `source ~/venv/bin/activate` to `~/.bashrc` to have it in every terminal; the tools run the same in it, since the environment's Python is Ubuntu's, with Playwright added. Playwright supports Ubuntu 22.04 and 24.04 and WSL ([its system requirements](https://playwright.dev/python/docs/intro#system-requirements)); on Ubuntu 22.04, `pip3 install --user playwright` and then `python3 -m playwright install --with-deps --only-shell chromium` work as well, without the environment, as pypdf does there.

When reveal.js or these are missing, the decks suite says what and how to install it, and `run-all.sh` counts what was skipped and lists why at its end: without `REVEALJS_DIR`, both reveal.js cases skip; without Playwright, or with a Chromium that doesn't start, the twelve checks in a browser do, in one line saying how many it stands for.

## Checking the whole setup

From the directory you cloned into:

```bash
bash tests/run-all.sh
```

Twenty suites run, and a check that the settings pages are current. A check that needs something not installed prints `skip` with the reason and what to install, a validator whose jar isn't set or the decks suite's reveal.js cases without reveal.js or the optional Playwright, and `run-all.sh` lists every skip at its end, so a pass without Java means the pipeline is sound and the validators are simply absent.
