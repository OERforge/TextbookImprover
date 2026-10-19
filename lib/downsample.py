"""
downsample.py -- images wider in pixels than they're shown, and copies of
them scaled down (images.downsample).

A web page often holds an image far larger than it shows it: LibreTexts
serves a photograph 2,150 pixels wide and shows it 180 wide, leaving the
browser to scale it. Every output carries the file whole, so an EPUB, a
PDF, a Word file, or a cartridge of such a book weighs what all its
originals do. This module measures each image a target's pages show
against the width they show it at, and makes copies scaled down to a set
number of times that width, which the targets read in the originals'
place: an html or revealjs target copies them beside its pages, and
Pandoc, writing an EPUB, a Word file, a PDF, or a deck, finds them first
on its resource path (--resource-path), since each is at the original's
path below a folder of its own.

The width an image is shown at is the one its page gives it, in CSS
pixels: its width (or, failing that, its height and the image's own
proportions), in pixels or any unit CSS converts to pixels, a percentage
of the column; else the image's own width. Either way it's no wider than
the column the pages set their text in, Pandoc's stylesheet's 36em,
576 pixels at a browser's default text size: an image is shown no wider
than that, whatever it says. Only a raster image a page shows as an
Image is measured (PNG, JPEG, GIF, WebP, BMP, TIFF): an SVG has no pixels
to spare, an animated GIF or PNG is left whole, and an image a page holds
in raw HTML isn't seen.

A copy of a drawing gets a palette. An original of few colors, a
drawing's or a chart's flat ones, compresses well as a PNG, but a copy
resampled from it holds thousands of colors along its smoothed edges,
which compress worse: at 2, 77 of Instrumental Analysis's copies came
out larger than their originals, every one such a drawing, and a larger
multiple only made a copy larger still. So a PNG copy whose original is in
RGB or RGBA, with DRAWING_COLORS colors or fewer, is quantized to an
adaptive palette of PALETTE_COLORS (median cut, or fast octree for a copy
with transparency, an alpha channel or a transparent color, which median
cut can't keep). A photograph's copy keeps its colors, since a palette
speckles a photograph's smooth shades, and so does a copy of an image in
shades of gray.

Measuring needs nothing but the files' headers; scaling needs Pillow.

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

import json
import os
import re
import struct
from urllib.parse import unquote

try:
    from PIL import Image
except ImportError:          # measuring works without it; scaling doesn't
    Image = None
# Pillow 9.1 put its filters in enums; Ubuntu 22.04's 9.0 has only the
# names on Image, which every later release keeps too.
LANCZOS = getattr(getattr(Image, "Resampling", Image), "LANCZOS", None)
FASTOCTREE = getattr(getattr(Image, "Quantize", Image), "FASTOCTREE", None)
MEDIANCUT = getattr(getattr(Image, "Quantize", Image), "MEDIANCUT", None)

# A drawing, as against a photograph: an original in RGB or RGBA of this
# many colors or fewer, whose PNG copy gets a palette of PALETTE_COLORS.
# Measured on Instrumental Analysis's PNGs: its drawings and charts have 49
# to 6,705 colors, most under 500, and its photographs more than 65,536.
DRAWING_COLORS = 4096
PALETTE_COLORS = 256

# The widest the pages show anything: Pandoc's stylesheet sets the body
# in a column 36em wide (templates/styles.html, max-width), and a
# browser's default text size is 16 pixels.
COLUMN = 36 * 16

# CSS's absolute units in pixels (CSS Values and Units 4, 6.2), and em at
# the default text size.
UNITS = {"px": 1.0, "": 1.0, "in": 96.0, "cm": 96 / 2.54, "mm": 96 / 25.4,
         "q": 96 / 101.6, "pt": 96 / 72, "pc": 16.0, "em": 16.0, "rem": 16.0}

RASTER = (".png", ".jpg", ".jpeg", ".jpe", ".gif", ".webp", ".bmp", ".tif",
          ".tiff")

LENGTH = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*([a-z%]*)\s*$", re.I)

# What the setting's folder of copies holds, besides them: the limit
# they were made for, so a build that's handed one made for another
# limit knows to make its own.
LIMIT_FILE = ".downsample-limit"

INSTALL = ("images.downsample needs Python's Pillow to scale images: sudo apt "
           "install python3-pil (see docs/installation.md).")


def length(value, natural=None):
    """A CSS length in pixels (a percentage of the column), or None."""
    if value is None:
        return None
    m = LENGTH.match(str(value))
    if not m:
        return None
    number, unit = float(m.group(1)), m.group(2).lower()
    if unit == "%":
        return number / 100 * COLUMN
    if unit in UNITS:
        return number * UNITS[unit]
    return None


def style_length(style, name):
    """A width or height a style attribute gives, in pixels."""
    m = re.search(r"(?:^|;)\s*" + name + r"\s*:\s*([^;]+)", style or "", re.I)
    return length(m.group(1)) if m else None


def pixel_size(path):
    """(width, height) of a raster image as shown, from Pillow when it's
    installed, which turns a JPEG's EXIF orientation into the shape a
    browser shows; else from the file's header. None when neither knows
    the file."""
    if Image is not None:
        try:
            with Image.open(path) as im:
                width, height = im.size
                try:
                    orientation = im.getexif().get(0x0112, 1)
                except Exception:
                    orientation = 1
                if orientation in (5, 6, 7, 8):
                    width, height = height, width
                return width, height
        except Exception:
            return None
    return header_size(path)


def header_size(path):
    """(width, height) from a PNG's, GIF's, JPEG's, WebP's, or BMP's
    header, or None."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(64 * 1024)
    except OSError:
        return None
    if head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
        return struct.unpack(">II", head[16:24])
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return struct.unpack("<HH", head[6:10])
    if head[:2] == b"BM" and len(head) >= 26:
        width, height = struct.unpack("<ii", head[18:26])
        return abs(width), abs(height)
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        kind = head[12:16]
        if kind == b"VP8 " and len(head) >= 30:
            width, height = struct.unpack("<HH", head[26:30])
            return width & 0x3FFF, height & 0x3FFF
        if kind == b"VP8L" and len(head) >= 25:
            bits = int.from_bytes(head[21:25], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if kind == b"VP8X" and len(head) >= 30:
            return (int.from_bytes(head[24:27], "little") + 1,
                    int.from_bytes(head[27:30], "little") + 1)
        return None
    if head[:2] == b"\xff\xd8":
        with open(path, "rb") as fh:
            data = fh.read()
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            size = struct.unpack(">H", data[i + 2:i + 4])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height, width = struct.unpack(">HH", data[i + 5:i + 9])
                return width, height
            i += 2 + size
    return None


def _images(node, found):
    """Every Image in a Pandoc document's JSON: (src, attributes)."""
    if isinstance(node, dict):
        if node.get("t") == "Image":
            attr, _caption, target = node["c"]
            found.append((target[0], dict(attr[2])))
        for value in node.values():
            if isinstance(value, (dict, list)):
                _images(value, found)
    elif isinstance(node, list):
        for value in node:
            _images(value, found)
    return found


def local(src):
    """A src naming a file of the book's, as a relative path, or None."""
    if not src or re.match(r"^[a-z][a-z0-9+.-]*:", src, re.I) or src.startswith(("/", "#")):
        return None
    return unquote(src.split("#", 1)[0].split("?", 1)[0])


def shown_width(attributes, natural):
    """The width an image is shown at, in CSS pixels, no wider than the
    column; None when there's nothing to go by."""
    width = length(attributes.get("width")) or style_length(attributes.get("style"), "width")
    if width is None:
        height = length(attributes.get("height")) or style_length(attributes.get("style"),
                                                                     "height")
        if height is not None and natural and natural[1]:
            width = height * natural[0] / natural[1]
    if width is None and natural:
        width = natural[0]
    if width is None or width <= 0:
        return None
    return min(width, COLUMN)


class Measured:
    """An image, the widest it's shown, and its pixels' ratio to that."""

    def __init__(self, src, path, pixels, shown):
        self.src, self.path, self.pixels, self.shown = src, path, pixels, shown
        self.ratio = pixels[0] / shown if shown else 0
        try:
            self.bytes = os.path.getsize(path)
        except OSError:
            self.bytes = 0


def measure(base, documents):
    """Each local raster image the documents show (filtered intermediates,
    Pandoc's JSON, as paths or as read), measured: the widest any of them
    shows it, against its own width in pixels. Sorted by ratio, largest
    first."""
    shown, sizes = {}, {}
    for page in documents:
        if isinstance(page, dict):
            doc = page
        else:
            try:
                with open(page, encoding="utf-8") as fh:
                    doc = json.load(fh)
            except (OSError, ValueError):
                continue
        for src, attributes in _images(doc.get("blocks", []), []):
            rel = local(src)
            if rel is None or not rel.lower().endswith(RASTER):
                continue
            if os.path.normpath(rel).split(os.sep)[0] == os.pardir:
                continue          # outside the book's folder, as its copy would be
            path = os.path.normpath(os.path.join(base, rel))
            if rel not in sizes:
                sizes[rel] = pixel_size(path) if os.path.isfile(path) else None
            pixels = sizes[rel]
            if not pixels or not pixels[0]:
                continue
            width = shown_width(attributes, pixels)
            if width is not None:
                shown[rel] = max(shown.get(rel, 0), width)
    out = [Measured(rel, os.path.normpath(os.path.join(base, rel)), sizes[rel], width)
           for rel, width in shown.items()]
    return sorted(out, key=lambda m: (-m.ratio, m.src))


def megabytes(n):
    return f"{n / 1e6:.1f} MB" if n >= 1e5 else f"{n / 1e3:.0f} kB"


def warning(measured, targets=()):
    """What the run says when no target scales its images: how many are
    wider than shown, and by how much the widest for its size. None when
    every image is shown at its width or wider."""
    wider = [m for m in measured if m.ratio > 1.0005]
    if not wider:
        return None
    top = wider[0]
    which = f" ({', '.join(targets)})" if targets else ""
    twice = sum(1 for m in wider if m.ratio > 2)
    return (f"WARNING: {len(wider)} image(s) are wider in pixels than the pages show them, "
            f"{twice} of them more than twice as wide, up to {top.ratio:.1f} times "
            f"({top.src}, {top.pixels[0]} pixels shown {round(top.shown)} wide); the "
            f"outputs{which} carry them whole, {megabytes(sum(m.bytes for m in wider))} "
            "in all. images.downsample scales an image down to a set number of times "
            "the width it's shown at (docs/configuration.md#images-larger-than-theyre-shown).")


def _flat(im):
    """An image in a mode Pillow resamples smoothly, and whether it had a
    palette, to have one again."""
    if im.mode == "P":
        has_alpha = "transparency" in im.info
        return im.convert("RGBA" if has_alpha else "RGB"), True
    if im.mode == "1":
        return im.convert("L"), False
    if im.mode in ("I;16", "I;16B", "I;16L"):
        return im.convert("I"), False
    return im, False


def drawing(im):
    """Whether an image in RGB or RGBA has DRAWING_COLORS colors or fewer,
    as a drawing does and a photograph doesn't."""
    return im.mode in ("RGB", "RGBA") and im.getcolors(DRAWING_COLORS) is not None


def scale_one(path, out, factor):
    """A copy of the image at path, its pixels scaled by factor (under 1),
    written to out in the original's format: its color profile, a JPEG's
    EXIF, and the size it prints at kept (its resolution scaled with it).
    A PNG or GIF that had a palette has one again, and a PNG copy of a
    drawing in color gets one. Returns the copy's size in bytes, or None
    when Pillow can't write it or it's animated, and whether it's a drawing
    given a palette."""
    with Image.open(path) as original:
        if getattr(original, "n_frames", 1) > 1:
            return None, False
        fmt = original.format
        info = dict(original.info)
        exif = original.info.get("exif")
        progressive = bool(original.info.get("progressive") or original.info.get("progression"))
        im, palette = _flat(original)
        drawn = fmt == "PNG" and not palette and drawing(im)
        width = max(1, round(original.size[0] * factor))
        height = max(1, round(original.size[1] * factor))
        scaled = im.resize((width, height), LANCZOS)
    options = {}
    if info.get("icc_profile"):
        options["icc_profile"] = info["icc_profile"]
    dpi = info.get("dpi")
    if dpi and all(isinstance(d, (int, float)) and d > 0 for d in dpi):
        options["dpi"] = tuple(d * factor for d in dpi)
    if fmt == "JPEG":
        if scaled.mode not in ("RGB", "L", "CMYK"):
            scaled = scaled.convert("RGB")
        options.update(quality=90, optimize=True, progressive=progressive)
        if exif:
            options["exif"] = exif
    elif fmt == "PNG":
        if palette:
            scaled = scaled.quantize(colors=256, method=FASTOCTREE)
        elif drawn:
            # An RGB original's transparent color (its tRNS chunk) would
            # stay on the palette copy as a color, which a palette PNG can't
            # hold and Pillow's writer fails on, so it's transparency first.
            if "transparency" in scaled.info:
                scaled = scaled.convert("RGBA")
            scaled = scaled.quantize(colors=PALETTE_COLORS,
                                     method=FASTOCTREE if scaled.mode == "RGBA" else MEDIANCUT)
        options["optimize"] = True
    elif fmt == "GIF":
        scaled = scaled.quantize(colors=256, method=FASTOCTREE)
    elif fmt == "WEBP":
        options.update(quality=90)
    elif fmt not in ("BMP", "TIFF"):
        return None, False
    os.makedirs(os.path.dirname(out), exist_ok=True)
    try:
        scaled.save(out, format=fmt, **options)
    except (OSError, ValueError, KeyError):
        return None, False
    return os.path.getsize(out), drawn


def scale(measured, limit, folder):
    """Copies, under folder at each image's path, of the images wider than
    limit times their shown width, scaled to that width; one whose copy
    would be larger than the original is left as it is. Returns counts:
    scaled, bytes before and after, drawings among them given a palette,
    kept (larger scaled), skipped (Pillow couldn't), and the total bytes of
    every image measured."""
    if Image is None:
        raise RuntimeError(INSTALL)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, LIMIT_FILE), "w") as fh:
        fh.write(str(limit))
    counts = {"scaled": 0, "before": 0, "after": 0, "palette": 0, "kept": 0, "skipped": 0,
              "images": len(measured), "total": sum(m.bytes for m in measured)}
    for m in measured:
        if m.ratio <= limit:
            continue
        out = os.path.join(folder, m.src)
        target = limit * m.shown
        size, drawn = scale_one(m.path, out, target / m.pixels[0])
        if size is None:
            counts["skipped"] += 1
            continue
        if size >= m.bytes:
            os.remove(out)
            counts["kept"] += 1
            continue
        counts["scaled"] += 1
        counts["before"] += m.bytes
        counts["after"] += size
        counts["palette"] += drawn
    return counts


def report(counts, limit):
    """One line for what scale did."""
    if not counts["scaled"] and not counts["kept"] and not counts["skipped"]:
        return (f"images.downsample {limit:g}: no image is wider than {limit:g} times "
                "the width it's shown at.")
    line = (f"images.downsample {limit:g}: {counts['scaled']} of {counts['images']} image(s) "
            f"scaled down to {limit:g} times the width they're shown at, "
            f"{megabytes(counts['before'])} to {megabytes(counts['after'])}")
    if counts.get("palette"):
        line += (f", {counts['palette']} of them drawings given a palette of "
                 f"{PALETTE_COLORS} colors")
    if counts["kept"]:
        line += (f"; {counts['kept']} kept as they were, since a copy at that size was "
                 "larger")
    if counts["skipped"]:
        line += f"; {counts['skipped']} left whole, animated or in a format not rewritten"
    return line + "."


def folder_for(folder, limit):
    """folder if it holds copies made for limit, else None."""
    try:
        with open(os.path.join(folder, LIMIT_FILE)) as fh:
            return folder if float(fh.read().strip()) == float(limit) else None
    except (OSError, ValueError, TypeError):
        return None


def folder_for_build(limit, base, documents, work, announce=None):
    """For a build run on its own (build-epub.py, build-pdf.py): the
    copies the run made, which it names in DOWNSAMPLED when they were made
    for limit, or else copies made here, in a folder of work's. None when
    limit is 0. Raises RuntimeError, saying what to install, without
    Pillow."""
    if not limit:
        return None
    given = os.environ.get("DOWNSAMPLED")
    if given and folder_for(given, limit):
        return given
    if Image is None:
        raise RuntimeError(INSTALL)
    made = os.path.join(work, "downsample")
    counts = scale(measure(base, documents), limit, made)
    if announce:
        announce(report(counts, limit))
    return made


def resource_args(folder):
    """Pandoc's options to find the copies in folder before the originals,
    which it looks for in the folder it runs in."""
    return ["--resource-path", folder + os.pathsep + "."] if folder else []


def limit_of(value):
    """images.downsample as a number: 0, or the largest ratio kept."""
    try:
        limit = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return limit if limit > 0 else 0.0
