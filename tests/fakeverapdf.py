"""
fakeverapdf.py -- a stand-in for veraPDF's launcher, so the suites can
check what the output check and the audit make of its WCAG profile's
report without Java, and wherever they run.

install(folder) writes the stand-in, an executable that VERAPDF can
name, and modules(folder, loads) a folder for VERAPDF_WCAG with the two
modules' jars named as Maven Central names them, empty, and the two
machine profiles, each the one rule the probe fails (PROFILE, a profile
veraPDF itself reads too). The stand-in answers as veraPDF 1.30.3 does, in
its JSON report's shape: a run without a profile (-p) finds nothing; a
run with one, when the folder CLASSPATH_PREFIX names holds the file
LOADS (the modules loaded), fails the probe on rule 1.3.1-1 and any
other PDF on 1.3.1-1 at page 653 and 2.4.9-1 at page 3, as well as a
PDF/UA rule, which the WCAG run doesn't report; without LOADS, a PDF/UA
rule alone, as veraPDF without its modules does. FAKE_VERAPDF_LOG, when
set, names a file each run appends its arguments and CLASSPATH_PREFIX
to, as a line of JSON; FAKE_VERAPDF_SKIP names a file to leave out of
the report, as veraPDF leaves out one it can't open by its name; and
FAKE_VERAPDF_GARBLED, set, has a run with a profile print what isn't
JSON, and a stack trace, as veraPDF does when it can't load one;
FAKE_VERAPDF_STDERR is written to its stderr, as bytes, beside its
report; FAKE_VERAPDF_KILLED, set, has a run with a profile end there,
killed, as the kernel kills a JVM short of memory; and
FAKE_VERAPDF_SLEEP is how many seconds it waits first.

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

import os
import sys

SCRIPT = r'''
import json
import os
import signal
import sys
import time

args = sys.argv[1:]
time.sleep(float(os.environ.get("FAKE_VERAPDF_SLEEP") or 0))
if os.environ.get("FAKE_VERAPDF_STDERR"):
    sys.stderr.buffer.write(os.environ["FAKE_VERAPDF_STDERR"].encode("utf-8", "surrogateescape"))
    sys.stderr.flush()
log = os.environ.get("FAKE_VERAPDF_LOG")
if log:
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"args": args,
                             "prefix": os.environ.get("CLASSPATH_PREFIX", "")}) + "\n")
files = [a for a in args if a.lower().endswith(".pdf")]
profile = args[args.index("-p") + 1] if "-p" in args else None
if profile and os.environ.get("FAKE_VERAPDF_KILLED"):
    os.kill(os.getpid(), signal.SIGKILL)
if profile and os.environ.get("FAKE_VERAPDF_GARBLED"):
    print("Usage: veraPDF [options] FILES")
    print('Exception in thread "main" javax.xml.bind.UnmarshalException: Problem loading '
          'custom profile', file=sys.stderr)
    print("\tat org.verapdf.apps.Main(Main.java:1)", file=sys.stderr)
    print("\t... 11 more", file=sys.stderr)
    sys.exit(2)
skip = os.environ.get("FAKE_VERAPDF_SKIP")
files = [name for name in files if os.path.basename(name) != skip]
first = os.environ.get("CLASSPATH_PREFIX", "").split(os.pathsep)[0]
loads = bool(profile) and first.endswith("*") and os.path.exists(
    os.path.join(os.path.dirname(first), "LOADS"))


def rule(spec, clause, test, kind, description, checks):
    return {"ruleStatus": "FAILED", "specification": spec, "clause": clause,
            "testNumber": test, "status": "failed", "failedChecks": len(checks),
            "object": kind, "description": description, "checks": checks}


ua = rule("ISO 14289-2:2024", "8.2.5.2", 2, "CosDocument", "A PDF/UA rule", [
    {"status": "failed", "context": "root/doc[0]", "errorMessage": "a PDF/UA message"}])
repeated = rule("WCAG2.2", "1.3.1", 1, "SARepeatedCharacters",
                "Text should not contain repeated non space characters", [
                    {"status": "failed", "context": "root/doc[0]/repeatedCharacters[0]",
                     "location": '{"bbox":[{"p":652,"rect":[174.0,295.3,177.1,306.7]}]}',
                     "errorMessage": "Text contains 7 repeated non space characters"}])
link = rule("WCAG2.2", "2.4.9", 1, "SALinkAnnotation", "Links shall contain an alternate "
            "description via their Contents or Alt keys or in the text value", [
                {"status": "failed", "context": "root/doc[0]/pages[2]/annots[0]",
                 "errorMessage": "A link annotation does not include an alternate description "
                                 "in the Contents or Alt Keys or in the text value"}])
jobs = []
for name in files:
    if not profile:
        rules = []
    elif not loads:
        rules = [ua]
    elif os.path.basename(name) == "wcag-probe.pdf":
        rules = [ua, rule("WCAG2.2", "1.3.1", 1, "SARepeatedCharacters",
                          "Text should not contain repeated non space characters",
                          [{"status": "failed", "context": "root/doc[0]",
                            "errorMessage": "Text contains 10 repeated non space characters"}])]
    else:
        rules = [ua, repeated, link]
    jobs.append({"itemDetails": {"name": name, "size": 1}, "validationResult": [{
        "jobEndStatus": "normal",
        "profileName": "WCAG 2.2 machine validation profile" if profile else "PDF/UA-2",
        "compliant": not rules, "details": {"passedRules": 90, "failedRules": len(rules),
                                            "ruleSummaries": rules}}]})
print(json.dumps({"report": {"buildInformation": {"releaseDetails": [
    {"id": "core", "version": "1.30.3"}, {"id": "apps", "version": "1.30.3"}]},
    "jobs": jobs}}))
sys.exit(1 if any(job["validationResult"][0]["details"]["ruleSummaries"]
                  for job in jobs) else 0)
'''

MODULES = ("wcag-validation-1.30.3.jar", "wcag-algorithms-1.30.3.jar")
PROFILES = ("WCAG-2-2-Machine-PDF20.xml", "WCAG-2-2-Machine.xml")

# One rule of veraPDF's WCAG 2.2 machine profiles in a profile of the
# suites' own: five or more of one character in a row, its test as
# veraPDF's profiles have it, on an object only veraPDF's WCAG modules
# make. {kind} is the profile's flavour, for PDF 2.0 or for PDF 1.x.
PROFILE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<profile xmlns="http://www.verapdf.org/ValidationProfile" flavour="{kind}">
    <details creator="TextbookImprover's suites" created="2026-10-22T00:00:00Z">
        <name>A WCAG rule alone</name>
        <description>Five or more of one character in a row</description>
    </details>
    <hash></hash>
    <rules>
        <rule object="SARepeatedCharacters" tags="cosmetic,machine,text">
            <id specification="WCAG_2_2" clause="1.3.1" testNumber="1"/>
            <description>No run of five or more of one character</description>
            <test>isNonSpace == false || numberOfRepeatedCharacters &lt; 5</test>
            <error>
                <message>%1 of one character in a row</message>
                <arguments>
                    <argument>numberOfRepeatedCharacters</argument>
                </arguments>
            </error>
            <references/>
        </rule>
    </rules>
    <variables/>
</profile>
"""
KINDS = {"WCAG-2-2-Machine-PDF20.xml": "WCAG_2_2_PDF_2_0_MACHINE",
         "WCAG-2-2-Machine.xml": "WCAG_2_2_MACHINE"}


def install(folder):
    """The stand-in's path, written into the folder."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "verapdf")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"#!{sys.executable}\n" + SCRIPT)
    os.chmod(path, 0o755)
    return path


def modules(folder, loads=True, profiles=PROFILES):
    """A folder for VERAPDF_WCAG: the modules' jars, empty, the profiles,
    and LOADS when the stand-in is to take them for loaded."""
    os.makedirs(folder, exist_ok=True)
    for name in MODULES + (("LOADS",) if loads else ()):
        open(os.path.join(folder, name), "w").close()
    for name in profiles:
        with open(os.path.join(folder, name), "w", encoding="utf-8") as fh:
            fh.write(PROFILE.format(kind=KINDS.get(name, "WCAG_2_2_MACHINE")))
    return folder
