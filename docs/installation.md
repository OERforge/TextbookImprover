# Installation

What the tools need, and how to check it. There's no install step for the tools themselves: `convert.sh` finds its filters, schemas, and the shared library by path relative to itself, so they stay where you cloned them.

## Requirements

| Tool | Needed for | Install |
|---|---|---|
| `pandoc` | Everything. Version 3.9 or later. | `sudo apt install pandoc` |
| `file` | Detecting real image types | usually present |
| `python3` | Required, 3.9 or later. Reads the configuration and inspects conversion intermediates. | usually present |
| PyYAML | Reading configuration | `sudo apt install python3-yaml` |
| `lxml` | Optional. Full schema validation of the manifest; without it a smaller set of checks runs. | `sudo apt install python3-lxml` |
| `pypdf` | `--toc` only | `pip3 install pypdf` |
| `zip` | Only if you package with the printed command instead of `--zip` | `sudo apt install zip` |

## Optional: the full validators

Every run [checks its output](checking.md) with nothing but Python. Two validators know the specifications in full and are used as well when they're present; both are Java. Nothing else in the project needs Java, and a run without them loses only their findings.

On Ubuntu, including WSL:

```bash
sudo apt install default-jre-headless          # Java, about 50 MB

mkdir -p ~/tools
curl -L -o /tmp/epubcheck.zip https://github.com/w3c/epubcheck/releases/download/v5.2.1/epubcheck-5.2.1.zip
unzip -o /tmp/epubcheck.zip -d ~/tools          # gives ~/tools/epubcheck-5.2.1/epubcheck.jar
curl -L -o ~/tools/vnu.jar https://github.com/validator/validator/releases/download/latest/vnu.jar
```

Then tell the run where they are, in `~/.bashrc` so it sticks:

```bash
export EPUBCHECK_JAR="$HOME/tools/epubcheck-5.2.1/epubcheck.jar"
export VNU_JAR="$HOME/tools/vnu.jar"
```

Open a new terminal (or `source ~/.bashrc`) and check:

```bash
java -jar "$EPUBCHECK_JAR" --version
java -jar "$VNU_JAR" --version
```

The next `convert.sh` reports `epubcheck ran on 1 EPUB(s)` and `The Nu HTML checker ran on N page(s)`. Ubuntu also packages `epubcheck` (`sudo apt install epubcheck`), which the run finds on the path without any variable; it's older than the release above, and either works. The `latest` link for `vnu.jar` moves with each release, which is what you want for a validator; the version it prints is the one to note if a finding needs discussing.

Pandoc 3.9 is a hard requirement, checked before any work starts. Earlier
versions accept most of the command line and quietly do something else:
3.6 and older write tables without cell spans, so a table with merged
cells loses them with no warning at all.

Pandoc versions still differ in ways that show up here — newer releases
read Word caption paragraphs into table captions, older ones don't — so
the same document can produce different reports on different machines.
Neither is wrong; the sidecar files absorb the difference.
