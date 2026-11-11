# LMS notes

What a learning management system does with a package: IMS Common Cartridge as a format, and what Brightspace does on import, with what Canvas's and Moodle's importers do as read from their code. The user's side is in [`docs/brightspace.md`](../docs/brightspace.md); what a checker inside an LMS reports is in [ACCESSIBILITY-NOTES.md](ACCESSIBILITY-NOTES.md). The file is short because little has been tested yet: results from other systems, and from Brightspace beyond what's here, are what it most needs. Each entry says how its fact is known and when, as [README.md](README.md) describes.

## Common Cartridge

**A cartridge is a container of HTML, and the manifest is the only thing in it to trust.** Read in two exports, one from Brightspace and one from Canvas (as of 0.8, 2026-10-03). Brightspace's content folder is named with a Cyrillic "с" that looks like a Latin "c", its pages have no `<title>`, and its file names end in dots ("… week..html"); Canvas writes links as `$IMS-CC-FILEBASE$/…` with its own query after them, and puts text headers in modules as entries with nothing beneath them. So the unpacker finds everything through the manifest's references, and a page's title comes from the outline when the page has none (`docs/cartridge-input.md`).

**The Common Cartridge 1.1 profile's manifest metadata takes contributors with roles, identifiers, coverage, rights, relations, an educational category, and classifications.** A test manifest carrying them all validated against the profile (measured 2026-11-07, and not measured again since). `validate-manifest.py` doesn't check a resource's metadata (2026-11-07; the script hasn't changed since, as of 2026-11-11).

**The profile's guide prohibits a role in the cartridge's own metadata, though its schema takes one** (read 2026-11-07).

**Canvas's and Moodle's importers read only a resource's first role.** Canvas hides a resource whose first role is Instructor, and Moodle one whose first role is Instructor or Mentor (2026-11-07, from the importers' code; neither was tried with an import).

## Brightspace

**An import appends structure and never merges it, a path holds one file shared by every module that points at it, and `Permanently delete` removes the file a topic _is_ and never the files a topic _uses_.** Verified by Rob in Brightspace, for both natively authored and imported content, in both content experiences. The tests aren't dated; the behavior has been in the repository's documentation since 0.2 (2026-09-12), and is in `docs/brightspace.md` now.

**D2L's support confirmed the deletion behavior as intended**, in answer to Rob's report with a test package. The reply isn't dated; it has been in `docs/brightspace.md` since 2026-09-18 (f071274). It made two points. The option worded "Permanently delete both the topic from Content and the associated file or activity from the course" means the file the topic _is_, the HTML, PDF, or PowerPoint the topic points at, and not the images, CSS, or other resources that file references, because the topic is associated with its primary file and doesn't track what that file pulls in. And where two topics point at the same file, deleting either one with that option deletes the file: the other topic survives with a broken link, Brightspace gives no warning, and it doesn't keep the file on account of the other reference. D2L passed the wording and the missing warning to its product team with no ticket and no commitment, so the behavior should be assumed permanent.

**A stable content prefix means one file is shared by every topic that points at it.** The cartridge's content prefix is deliberately stable, so that an update overwrites the same paths, and so a user who deletes one topic with `Permanently delete` can silently break the others. Nothing in the cartridge can prevent it; the most TextbookImprover can do is not multiply the shared paths unnecessarily and say so in the documentation (`docs/brightspace.md`).

**Brightspace hides a page whose resource's roles include Instructor or Mentor, but a learner can still open its file from a link.** Importing a test cartridge of pages whose resources carry the roles, Brightspace hid every page whose roles include Instructor or Mentor but let a learner open each one's file from a link, as D2L's file-security variables, all off by default, allow (measured by Rob, 2026-11-07).
