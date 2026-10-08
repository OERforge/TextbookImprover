# Installation

How to get the tools, what they need, and how to check the result. There's no initial configuration step for the tools themselves: `convert.py` finds its filters, schemas, and the shared library by path relative to itself, so they work from wherever you put them.

This version is developed and tested on Ubuntu 24.04 with Pandoc 3.12.1 and 3.12: on Windows under WSL 2, which is what the maintainer runs, and in an Ubuntu container, which is where the test suites run before a release. Its suites pass too with Ubuntu 22.04's Python (3.10) and the versions of its packages that 22.04 ships, pypdf aside ([Which Ubuntu you have](#which-ubuntu-you-have)). Nothing here is Windows-specific or WSL-specific, and the same commands work on a Linux machine or on macOS with Homebrew in place of `apt`.

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
| `pandoc` | Everything. **Version 3.9 or later**; see below, because Ubuntu's own package is older. | from Pandoc's release page |
| `python3` | Required, 3.9 or later. Runs the driver and every script. | present on Ubuntu |
| PyYAML | Reading configuration | `sudo apt install python3-yaml` |
| `file` | Detecting real image types | present on Ubuntu |
| `html5lib` | Recommended. Parsing pages saved from the web (`unpack-site.py`), the way a browser does; without it `lxml` is used, and without either `unpack-site.py` stops | `sudo apt install python3-html5lib` |
| `lxml` | Optional. Full schema validation of the manifest; without it a smaller set of checks runs. | `sudo apt install python3-lxml` |
| `pypdf` | `--toc` with a PDF, and checking a PDF the run builds or the audit reads; an EPUB needs nothing | `sudo apt install python3-pypdf`; on Ubuntu 22.04, `pip3 install --user pypdf` ([above](#which-ubuntu-you-have)) |
| LuaLaTeX | A `pdf` target only; see [below](#for-a-pdf-target-lualatex) | TeX Live 2026 |
| pdfLaTeX or LuaLaTeX, LaTeX's `preview` package, and `pdftocairo` | A LaTeX source with drawings or PDF images, which become SVG ([LaTeX sources](latex.md)); without them they're left out of the pages | TeX Live (`tlmgr install preview` where it's missing); `sudo apt install poppler-utils` |
| TeX's `latex-tagging-status` package | A LaTeX source's copy made for tagging, whose class and packages are checked against the tagging project's status list ([LaTeX sources](latex.md#the-source-target)); without it, the run says how to install it and checks nothing | `tlmgr install latex-tagging-status`; MiKTeX installs it on demand |
| `zip` | Only if you package with the printed command instead of `--zip` | `sudo apt install zip` |

**Pandoc has to come from Pandoc.** `sudo apt install pandoc` on Ubuntu 24.04 gives 3.1.3, which this project refuses to run with: Pandoc 3.6 and older write tables without cell spans, so a table with merged cells loses them silently, and several things the filter relies on arrived later. Install the `.deb` from [Pandoc's releases](https://github.com/jgm/pandoc/releases) instead:

```bash
curl -L -O https://github.com/jgm/pandoc/releases/download/3.12.1/pandoc-3.12.1-1-amd64.deb
sudo apt install ./pandoc-3.12.1-1-amd64.deb
pandoc --version | head -1
```

Pandoc 3.9 is a hard requirement, checked before any work starts. Versions above it still differ in ways that show up here — newer releases read Word caption paragraphs into table captions, older ones don't — so the same document can produce different reports on different machines. Neither is wrong; the sidecar files absorb the difference.

**Python packages come from `apt`, not `pip`.** Ubuntu 24.04 manages its Python installation, so `pip3 install pypdf` stops with `error: externally-managed-environment` (and on a fresh WSL install `pip3` isn't there to begin with). The `python3-*` packages in the table are the ones to use. Ubuntu 22.04 doesn't stop pip, and its one gap, pypdf, comes from pip there, as [above](#which-ubuntu-you-have). If you need a version newer than Ubuntu ships, make a virtual environment for it (`python3 -m venv ~/venv && ~/venv/bin/pip install pypdf`) and run the tools with that interpreter.

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

**`tlmgr` and `sudo`.** TinyTeX lives in your home folder, so its `tlmgr` needs no `sudo`, as in the commands above. A TeX Live from its own installer is usually installed for the whole system, under `/usr/local/texlive`, and there every `tlmgr install` and `tlmgr update` needs `sudo` before it: `sudo tlmgr install preview`, where this page says `tlmgr install preview`. If `sudo` then answers `tlmgr: command not found`, which happens because `sudo` uses a shorter list of folders to find programs in than you do, `sudo "$(which tlmgr)" install preview` works. The commands the run itself suggests have `sudo` in them where your TeX needs it. And when `tlmgr` says it has to be updated itself before it will install anything, as it does once TeX Live has released a new version of it, `tlmgr update --self` (again with `sudo` for a whole-system TeX Live) does that; then run the install again.

A book with SVG images needs `rsvg-convert` for its PDF (`sudo apt install librsvg2-bin`); the build stops and says so if it's missing. DejaVu Sans, which most Linux desktops have already (`sudo apt install fonts-dejavu-core` if not), supplies characters Latin Modern lacks, such as the circled digits of an AsciiDoc book's code callouts.

For the PDF's table captions and empty paragraph elements, `pikepdf` too (`sudo apt install python3-pikepdf`); without it the run says so and leaves both as LaTeX tags them, and the PDF suite skips. `pdf.figures: section` needs `placeins` (`tlmgr install placeins`). `multirow` is for a table with a cell spanning rows, which Pandoc's template loads only when a book has one; the PDF suite's book does.

A LaTeX book's PDF is built from the book's own LaTeX ([LaTeX sources](latex.md#the-pdf-target)), by `latexmk`, which TinyTeX and TeX Live include, and with the packages the book itself loads, which `tlmgr` installs as below. The copy loads `unicode-math` for its formulas' MathML, which TinyTeX has, and, for a book that uses pdfTeX's own commands or tests for pdfTeX by `\pdfoutput`, `luatex85`, which TinyTeX lacks (`tlmgr install luatex85`).

A LaTeX book's drawings are each made a page of LaTeX's `preview` package, which the TinyTeX above has. TinyTeX-1, the smaller bundle TinyTeX's own install script installs, doesn't, and lacks much else a book is likely to load: a run without `preview` says to install it, and a build that stops names the file it couldn't find, as above.

A LaTeX book's PDF figures that don't embed their fonts, as R's plots don't, are rewritten in the copy with them embedded, which PDF/UA requires: by Ghostscript where it's installed (`sudo apt install ghostscript`), and otherwise by `pdftocairo`. The LaTeX suite has one check of Ghostscript's way, which skips without it.

The LaTeX suite (`tests/run-latex-tests.py`) builds small books that load more than the PDF target needs, and its first check names whatever of it is missing, with the line that installs it. On the TinyTeX above, that's `tlmgr install luatex85 wasysym`; on TinyTeX-1, `tlmgr install babel-english caption fancyhdr grfext luatex85 mdframed pgf preview soul tabto-ltx tex-gyre titlesec ulem wasysym wrapfig`; and on either, `rsvg-convert` for its SVG (`sudo apt install librsvg2-bin`).

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
