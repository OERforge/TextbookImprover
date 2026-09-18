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

Pandoc 3.9 is a hard requirement, checked before any work starts. Earlier
versions accept most of the command line and quietly do something else:
3.6 and older write tables without cell spans, so a table with merged
cells loses them with no warning at all.

Pandoc versions still differ in ways that show up here — newer releases
read Word caption paragraphs into table captions, older ones don't — so
the same document can produce different reports on different machines.
Neither is wrong; the sidecar files absorb the difference.
