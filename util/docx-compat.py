#!/usr/bin/env python3
"""
docx-compat.py -- read or set the Word compatibility mode of a .docx.

    python3 util/docx-compat.py book/*.docx
    python3 util/docx-compat.py chapter.docx --set 15
    python3 util/docx-compat.py chapter.docx --set 15 -o modern.docx

word/settings.xml carries a compatibilityMode compat setting telling Word
which generation of layout rules to apply: 12 for Word 2007, 14 for 2010,
15 for 2013 and everything since. Below 15, or absent, Word opens the file
in Compatibility Mode and will not run its Accessibility Checker until the
document is converted -- which is an awkward thing to hand somebody at the
end of an accessibility pass.

Pandoc takes settings.xml from its reference document and the bundled one
declares no compat setting at all, so anything Pandoc writes lands in
compatibility mode. That can be fixed by supplying a patched reference
document, but this does it afterwards instead, so it works whatever
reference document the user brought.

Upgrading is not free. Microsoft's guidance is that Compatibility Mode
preserves the document's layout and that converting clears the
compatibility options so the layout appears as it would under the newer
version. Tables and justified text are where that shows. So this does
nothing unless asked, and the pipeline's default is to carry whatever the
source declared.

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

import argparse
import os
import re
import shutil
import sys
import tempfile
import zipfile

SETTINGS_PART = "word/settings.xml"
SETTINGS_TYPE = ("application/vnd.openxmlformats-officedocument."
                 "wordprocessingml.settings+xml")
SETTINGS_REL = ("http://schemas.openxmlformats.org/officeDocument/2006/"
                "relationships/settings")
WORD_URI = "http://schemas.microsoft.com/office/word"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

FIND_MODE = re.compile(r'<w:compatSetting[^>]*?w:name="compatibilityMode"[^>]*?>')
FIND_VAL = re.compile(r'w:val="(\d+)"')

EMPTY_SETTINGS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                  '<w:settings xmlns:w="%s"></w:settings>' % W_NS)


def setting(mode):
    return ('<w:compatSetting w:name="compatibilityMode" w:uri="%s" '
            'w:val="%s"/>' % (WORD_URI, mode))


FIND_COMPAT = re.compile(r"<w:compat>(.*?)</w:compat>", re.S)
FIND_ELEMENT = re.compile(r"<w:([A-Za-z0-9]+)[ />]")


def legacy_options(path):
    """Legacy compat OPTION elements, which are not compatSettings.

    Two different things live inside w:compat. compatSetting elements are
    named key/value pairs, of which compatibilityMode is one. Option
    elements -- doNotExpandShiftReturn, useWord2002TableStyleRules and the
    rest -- are bare flags that pin individual layout behaviors, and
    Word's own Convert clears them.

    Declaring mode 15 while leaving those in place would tell Word to use
    current layout rules and then override some of them, which is a state
    Word would not normally write. None of the 1,027 files in the five
    books here carries one, so this reports rather than acts.
    """
    with zipfile.ZipFile(path) as archive:
        try:
            settings = archive.read(SETTINGS_PART).decode("utf8", "ignore")
        except KeyError:
            return []
    block = FIND_COMPAT.search(settings)
    if not block:
        return []
    return sorted({name for name in FIND_ELEMENT.findall(block.group(1))
                   if name != "compatSetting"})


def read_mode(path):
    """The declared compatibility mode, or None if the file does not say."""
    with zipfile.ZipFile(path) as archive:
        try:
            settings = archive.read(SETTINGS_PART).decode("utf8", "ignore")
        except KeyError:
            return None
    found = FIND_MODE.search(settings)
    if not found:
        return None
    value = FIND_VAL.search(found.group(0))
    return value.group(1) if value else None


def patch_settings(xml, mode):
    """Set compatibilityMode in a settings part, leaving the rest alone.

    Three cases, and the third is the one that matters: a document may
    already carry other compat settings (overrideTableStyleFontSizeAnd-
    Justification, enableOpenTypeFeatures, and so on), and those are
    individual behaviors someone's document may depend on. Only the
    compatibilityMode element is touched.
    """
    found = FIND_MODE.search(xml)
    if found:
        return xml[:found.start()] + setting(mode) + xml[found.end():]
    if "<w:compat>" in xml:
        return xml.replace("<w:compat>", "<w:compat>" + setting(mode), 1)
    if "<w:compat/>" in xml or "<w:compat />" in xml:
        return re.sub(r"<w:compat\s*/>",
                      "<w:compat>" + setting(mode) + "</w:compat>", xml, count=1)
    block = "<w:compat>" + setting(mode) + "</w:compat>"
    if "</w:settings>" in xml:
        return xml.replace("</w:settings>", block + "</w:settings>", 1)
    return re.sub(r"<w:settings([^>]*)/>",
                  lambda m: "<w:settings%s>%s</w:settings>" % (m.group(1), block),
                  xml, count=1)


def add_part(content_types, part, ctype):
    if 'PartName="/%s"' % part in content_types:
        return content_types
    override = '<Override PartName="/%s" ContentType="%s"/>' % (part, ctype)
    return content_types.replace("</Types>", override + "</Types>", 1)


def add_rel(rels, target, rtype, ident):
    if 'Target="%s"' % target in rels:
        return rels
    item = ('<Relationship Id="%s" Type="%s" Target="%s"/>'
            % (ident, rtype, target))
    return rels.replace("</Relationships>", item + "</Relationships>", 1)


def set_mode(path, mode, output=None):
    """Write path (or output) with compatibilityMode set to mode.

    Every other part is copied through untouched, keeping its name, date,
    and compression, because this has no business changing anything it was
    not asked about.
    """
    target = output or path
    handle, temporary = tempfile.mkstemp(suffix=".docx",
                                         dir=os.path.dirname(os.path.abspath(target)))
    os.close(handle)
    try:
        with zipfile.ZipFile(path) as source:
            names = source.namelist()
            with zipfile.ZipFile(temporary, "w") as out:
                for info in source.infolist():
                    data = source.read(info.filename)
                    if info.filename == SETTINGS_PART:
                        data = patch_settings(
                            data.decode("utf8"), mode).encode("utf8")
                    elif info.filename == "[Content_Types].xml" \
                            and SETTINGS_PART not in names:
                        data = add_part(data.decode("utf8"), SETTINGS_PART,
                                        SETTINGS_TYPE).encode("utf8")
                    elif info.filename == "word/_rels/document.xml.rels" \
                            and SETTINGS_PART not in names:
                        data = add_rel(data.decode("utf8"), "settings.xml",
                                       SETTINGS_REL,
                                       "rIdCompat").encode("utf8")
                    out.writestr(info, data)
                if SETTINGS_PART not in names:
                    out.writestr(SETTINGS_PART,
                                 patch_settings(EMPTY_SETTINGS, mode))
        shutil.move(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    return target


def main():
    ap = argparse.ArgumentParser(
        description="Read or set the Word compatibility mode of a .docx.")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--set", dest="mode",
                    help="compatibility mode to declare, e.g. 15")
    ap.add_argument("-o", "--output",
                    help="write here instead of in place (one file only)")
    args = ap.parse_args()

    if args.output and len(args.files) > 1:
        ap.error("-o takes a single input file")
    if args.output and not args.mode:
        ap.error("-o only makes sense with --set")
    if args.mode and not args.mode.isdigit():
        ap.error("--set takes a number, e.g. 15")

    status = 0
    for path in args.files:
        try:
            before = read_mode(path)
        except (zipfile.BadZipFile, OSError) as exc:
            print("%s: %s" % (path, exc), file=sys.stderr)
            status = 1
            continue
        legacy = legacy_options(path)
        if not args.mode:
            note = "" if before == "15" else \
                "  (Word opens this in Compatibility Mode)"
            if legacy:
                note += "  [legacy compat options: %s]" % ", ".join(legacy)
            print("%s: %s%s" % (path, before or "not declared", note))
            continue
        if legacy and args.mode >= "15":
            print("%s: warning: keeps legacy compat option(s) %s, which "
                  "override some of the layout rules mode %s asks for. "
                  "Word's own Convert would clear them."
                  % (path, ", ".join(legacy), args.mode), file=sys.stderr)
        written = set_mode(path, args.mode, args.output)
        after = read_mode(written)
        if after != args.mode:
            print("%s: failed to set mode (still %s)" % (path, after or "unset"),
                  file=sys.stderr)
            status = 1
        else:
            print("%s: %s -> %s" % (written, before or "not declared", after))
    return status


if __name__ == "__main__":
    sys.exit(main())
