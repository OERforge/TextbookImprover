# Common Cartridge 1.1 schemas

Used by `bin/validate-manifest.py` to check the manifest
`build-cartridge.py` writes. They are here rather than fetched because
validation should not need a network connection, and because the IMS URLs
these files name in their own imports have been unreliable — at the time
of writing, `ccv1p1_imsccauth_v1p1.xsd` is not served at the address the
content-packaging schema gives for it.

## What each file is

| File | Purpose |
|---|---|
| `ccv1p1_imscp_v1p2_v1p0.xsd` | Content packaging. The root schema; everything else is reached from it. |
| `ccv1p1_imsccauth_v1p1.xsd` | Authorization. Imported by the above for `autz:protected` and `autz:authorizations`, which this project never emits — but the root schema will not load without it. |
| `ccv1p1_lommanifest_v1p0.xsd` | LOM metadata at the manifest level. |
| `ccv1p1_lomresource_v1p0.xsd` | LOM metadata at the resource level. |
| `ccv1p1_imsdt_v1p1.xsd` | Discussion topics. Not yet emitted; here for completeness. |
| `ccv1p1_imswl_v1p1.xsd` | Web links. Not yet emitted. |
| `ccv1p1_qtiasiv1p2p1_v1p0.xsd` | QTI 1.2.1, for assessments and question banks. Not yet emitted. |
| `xml.xsd` | The W3C XML-namespace schema. Every IMS schema imports it and none of them ship it. |

## They are unmodified, and must stay that way

The IMS schemas carry this term:

> Developers of products or services that are not original incorporators
> of this document and have not changed this document, that is, are
> distributing a software product that incorporates this document as is
> from a third-party source other than IMS, are hereby granted permission
> to copy, display and distribute the contents of this document in any
> medium for any purpose without fee or royalty provided that you include
> this IPR, License and Distribution notice in its entirety on ALL copies,
> or portions thereof.

Redistribution is permitted on two conditions: the files are unchanged,
and the notice travels with them. The notice is inside each file, so
keeping them byte-for-byte satisfies both at once.

This has a practical consequence. The schemas import each other by
absolute `https://` URL, so they will not load from a directory without
help. The obvious fix — rewriting those to relative paths — is exactly
the change the license does not allow. `validate-manifest.py` therefore
registers a resolver that serves each import from this directory by
filename, leaving the files untouched. That also means validation never
touches the network.

If you ever need to alter one of these, take it up with IMS rather than
editing it here. A modified copy falls outside the grant above.

`xml.xsd` is W3C rather than IMS, under the W3C Software and Document
Notice and Licence, which likewise permits redistribution with its notice
intact.

## Where they came from

- IMS Global (now 1EdTech), Common Cartridge 1.1 profile, and the IMS
  Content Packaging 1.1.4 binding it profiles.
- W3C, `https://www.w3.org/2001/xml.xsd`.

## Which version, and why 1.1

`build-cartridge.py` writes Common Cartridge 1.1 deliberately. It is the
only version every major LMS reads: Brightspace and Canvas handle up to
1.3 and Blackboard up to 1.2, but Moodle stops at 1.1, and a 1.1 cartridge
imports into all of them while a later one does not. Nothing in 1.2 or 1.3
is needed here — quizzes, question banks, discussion topics, web links and
LTI links are all in 1.1 already. Assignments arrive in 1.3 and are the
one reason to revisit it. See `ROADMAP.md`.
