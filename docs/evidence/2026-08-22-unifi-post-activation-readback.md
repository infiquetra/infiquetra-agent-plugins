# Post-activation readback — portable UniFi package 2.0.1

The UniFi package in this repository, `plugins/unifi/`, is a derived copy of an
upstream Claude Code plugin that was released as version 2.0.1 and activated
upstream. The portability pilot plan requires two things after any activation,
and neither had been captured:

- **R40** — activation "is preceded by a staged load and followed by an
  installed-version and digest readback".
- **R41** — "a fresh client session proves all three profile states after
  activation: profile present, profile absent, and profile unreadable.
  Source-tree evidence alone does not satisfy this, because an active client can
  remain cached."

Both were recorded as outstanding. A code review found the gap independently and
raised it as a release-blocking item: nothing proved which version and which
bytes an installed client actually holds. This document is that proof, captured
on 22 August 2026.

## This readback was re-captured, and why

This is the third capture. The first described the package at tree digest
`6e6b57c1…`; the second, at `da46ca77…`, followed the re-synchronization of the
portable Fleet Core slice to release 0.25.1.

This capture follows the re-synchronization of the package itself from UniFi
release `2.0.1`, at upstream commit `0d81dd9a`. That release repairs the caller
half of the `Retry-After` defect: both clients used to convert the raw header
with `int()` before raising, so the shared backoff primitive never received a
header it could read. Both client entrypoints therefore changed, along with the
upstream changelog byte copy, and the manifest version moved `2.0.0 → 2.0.1`.
Every fingerprint in the second capture stopped identifying the shipped bytes,
and the synchronization pin it named stopped matching the manifest.

Every install, every recomputation, and all three profile states below were
captured again against the package as it now ships. No number here was carried
forward from an earlier capture. Editing the digests in place would have been
the exact failure the compatibility matrix binding exists to catch, so the
readback was re-run instead. One thing is stronger than before: every command
below ran on `python3.12`, the catalog's declared minimum interpreter, rather
than on whatever interpreter happened to be default.

## What "readback" has to mean here

Reading the version out of the manifest in this repository proves nothing about
an install. The interesting question is the one an operator asks after an
activation: *the client on my machine — what does it actually hold?* So every
number below was read back out of a client-owned installed copy, in a home
directory that was empty when the run started, and then independently
recomputed from the installed bytes.

Held identical throughout:

- **Credential-free.** No client was authenticated. Every `UNIFI_` variable was
  removed from the environment before every command.
- **Read-only and offline.** No controller call, no marketplace refresh, no
  network request of any kind. The upstream release was verified against a local
  clone already pinned at the activated commit, not fetched.
- **Isolated.** Each client ran under its own empty home directory in a scratch
  area, with `XDG_CONFIG_HOME` pointed at an empty scratch directory. The
  operator's deployed site profile and its configuration file were neither read
  nor written; the profile used below is an inert example holding no real site.

## The custody chain

Four links, each verified rather than assumed:

| Link | What identifies it | How it was checked |
|---|---|---|
| Activated upstream release | commit `0d81dd9a48ce4321645fd857d23d749cc23520d1`, manifest version `2.0.1` | read from a local clone at that commit, read-only |
| Synchronization pin | `plugins/unifi/PROVENANCE.json` records that same commit and version | read from this repository |
| Portable package tree | 23 files, tree digest `cafe8836…91d1` | recomputed from `plugins/unifi/` |
| Installed copies | same file count, same tree digest | recomputed from each client-owned installed tree |

Read read-only from the same local clone, the upstream manifest at that commit
declares `unifi` version `2.0.1` and `fleet-core` version `0.25.1`.

**The two portable slices now pin two different revisions, and that is
deliberate.** `plugins/fleet-core/PROVENANCE.json` still pins `ed72f439`, and
`plugins/unifi/PROVENANCE.json` now pins `0d81dd9a`. The Fleet Core pin names
the revision at which the upstream `plugins/fleet-core` subtree last changed,
which is the rule that slice was created under; `0d81dd9a` is a descendant of it
on the same default branch, and the upstream `plugins/fleet-core` subtree is
byte-identical between the two revisions, which was verified rather than
assumed. So the two pins still name one consistent upstream state — they are the
same state read at two points on one line of history, not two competing
answers.

The tree digest is the one defined in
[the compatibility matrix](2026-08-22-unifi-compatibility-matrix.md#binding-and-what-a-superseded-matrix-may-claim):
SHA-256 over the sorted per-file digests with their relative paths. It is
recomputable from published bytes with:

```console
python3 scripts/check_compatibility_matrix.py --print-fingerprint
```

## Installed-version and digest readback

Three fresh installs, into three homes that were empty when the run began. Each
row separates what the *client itself* reports from what an independent
recomputation of the installed bytes says, because a client's own claim about
what it holds is evidence, not proof.

| Client | Install unit | Client-reported version | Client-reported digest | Recomputed from installed bytes |
|---|---|---|---|---|
| Grok 1.0.5 | package root | `unifi v2.0.1` | none reported | 23 files, `cafe8836…91d1` — equal to the source tree |
| Agy 1.1.18 | package root | not reported; 2 skills processed | none reported | 23 files, `cafe8836…91d1` — equal to the source tree |
| Muse 0.2.1 | each skill directory | not reported; activation on, 0 diagnostics | content digest per unit, 4 files each | `unifi-network` 4 files `39eff353…acc1`; `unifi-protect` 4 files `d12b66b9…e0c9` — equal to the source units |

Two notes on reading that table honestly:

1. **Muse's content digest is Muse's algorithm, not this repository's.** The two
   values it reports —
   `d4452f7badb081504fa5663c72da143b206b3ec7ce1de07944466afffb2ccae3` for
   `unifi-network` and
   `7f820bd1638304efd4b457278f61e448939fe0e09efa240e382199f542363f9f` for
   `unifi-protect` — are recorded because they are the client's own identifier
   for the bytes it installed, and they reproduced identically across two
   independent installs from two differently-named source directories. They are
   not claimed to equal this repository's tree digests for the same units.
2. **Only Grok reports a version at all.** Agy and Muse install and enumerate
   without surfacing one. That is a limitation of those clients, recorded rather
   than worked around; for those two, the digest equality is the whole of the
   identity proof.

Both entrypoints were then run out of each client-owned installed copy, on
`python3.12`, credential-free and with no host argument:
`unifi_network_client.py --help` and `unifi_protect_client.py --help` each exit 0
and print usage — 30 lines and 22 lines of argument-parser text respectively.

## The three profile states, against installed bytes

Run from `scripts/site_profile.py` inside each **installed** package copy, on
`python3.12` — not from this repository's working tree, which is the distinction
R41 draws. The
loader resolves a profile from `UNIFI_SITE_PROFILE` first, then from a
configuration file, then not at all.

| State | How it was produced | Exit | What the installed loader reported |
|---|---|---|---|
| **Absent** | no `UNIFI_SITE_PROFILE`, empty scratch `XDG_CONFIG_HOME` | 0 | mode `discovery-only`, profile path null, source null, subject/policy/constraint counts 0, all four intent fields `unknown`, and five named limits including that operator intent may not be inferred from controller state |
| **Present** | `UNIFI_SITE_PROFILE` naming an inert example profile | 0 | mode `profile`, source `environment`, schema version `1.0`, site identifier `example-site`, 2 subjects, 1 intended policy, 1 operational constraint |
| **Unreadable** | `UNIFI_SITE_PROFILE` naming a file the process cannot read | 1 | `ProfileUnreadableError`, reported as structured JSON on standard output — a loud failure, not a silent fall back to discovery-only |

All three states were proved twice, once from the Grok installed copy and once
from the Agy installed copy, with identical results — compared field by field,
not merely by exit status. The unreadable state is the one that matters most:
falling back to discovery-only there would answer a question about one site
under another site's assumptions, and it does not. The failing output carries
only an error and an error type; it carries no `mode`, so there is no
discovery-only answer for a caller to mistake for success.

## What this proves, and what it does not

**Proved.** A client installing this package from a cold start holds exactly the
bytes this repository ships, which are the bytes synchronized from the activated
upstream 2.0.1 release; the installed copy's entrypoints run credential-free on
the catalog's declared minimum interpreter; and the installed profile loader
distinguishes all three profile states with the documented exit statuses, on that
same interpreter.

**Not proved, and not claimed.** Nothing here exercises a UniFi controller: no
subcommand was run against a live system, so this says nothing about whether any
read operation returns correct data. Nothing here re-fetches the upstream
marketplace, so the chain is verified against a local clone pinned at the
activated commit rather than against the published release surface. The readback
covers the three clients that produce a client-owned installed copy of the
package root or of the skill units; clients that link or symlink to the source
directory hold no separate bytes to read back.

**The floor question the earlier captures deferred is answered here.** Both
earlier captures ran on whatever interpreter was default and said so, which left
the catalog's declared minimum untested by this document. Every command in this
capture ran on `python3.12` — CPython 3.12.13 — which is exactly the floor
`python>=3.12` names, so the installs, the entrypoint runs, and all three profile
states are evidence for the declared minimum rather than evidence gathered above
it. The floor decision is recorded in
[the engineering journal](../engineering-journal/DECISIONS.md#the-portable-catalogs-minimum-supported-python-is-python312)
and enforced by `tests/test_python_floor.py`. What is still not shown is any
interpreter *below* the floor, which is not a case the catalog claims to
support.

## The machine-readable record

```json
{
  "schema_version": "1",
  "captured_on": "2026-08-22",
  "release": {
    "name": "unifi",
    "version": "2.0.1",
    "file_count": 23,
    "tree_sha256": "cafe883671b6ee61fb7ab037a3b31c9e338befd4bf3f18957ab98dc14a6d91d1",
    "upstream_commit": "0d81dd9a48ce4321645fd857d23d749cc23520d1",
    "units": {
      "unifi-network": {
        "file_count": 4,
        "tree_sha256": "39eff353d6cd50323d1ab7606e45d48d3da89e2fc0d98ec9aaba3e3265f1acc1"
      },
      "unifi-protect": {
        "file_count": 4,
        "tree_sha256": "d12b66b98344623c32e1f236b2df7c6f14966b09c52c7697f3fddd8b89a7e0c9"
      }
    }
  },
  "method": {
    "credentials": "No client authenticated; every UNIFI_ variable removed from the environment before every command.",
    "network": "No controller call, no marketplace refresh, no network request. The upstream release was verified against a local clone already pinned at the activated commit.",
    "isolation": "Each client ran under an empty scratch home with XDG_CONFIG_HOME pointed at an empty scratch directory. The deployed site profile and its configuration file were neither read nor written."
  },
  "readbacks": [
    {
      "client": "Grok",
      "client_version": "1.0.5",
      "install_unit": "package-root",
      "reported_version": "2.0.1",
      "reported_digest": null,
      "recomputed_file_count": 23,
      "recomputed_tree_sha256": "cafe883671b6ee61fb7ab037a3b31c9e338befd4bf3f18957ab98dc14a6d91d1",
      "matches_release": true,
      "entrypoints_exit_zero": true
    },
    {
      "client": "Agy",
      "client_version": "1.1.18",
      "install_unit": "package-root",
      "reported_version": null,
      "reported_digest": null,
      "recomputed_file_count": 23,
      "recomputed_tree_sha256": "cafe883671b6ee61fb7ab037a3b31c9e338befd4bf3f18957ab98dc14a6d91d1",
      "matches_release": true,
      "entrypoints_exit_zero": true
    },
    {
      "client": "Muse",
      "client_version": "0.2.1",
      "install_unit": "skill-directory",
      "reported_version": null,
      "reported_digest": {
        "algorithm": "client-defined content digest, not this repository's tree digest",
        "unifi-network": "d4452f7badb081504fa5663c72da143b206b3ec7ce1de07944466afffb2ccae3",
        "unifi-protect": "7f820bd1638304efd4b457278f61e448939fe0e09efa240e382199f542363f9f"
      },
      "recomputed_file_count": 8,
      "recomputed_tree_sha256": null,
      "recomputed_units": {
        "unifi-network": "39eff353d6cd50323d1ab7606e45d48d3da89e2fc0d98ec9aaba3e3265f1acc1",
        "unifi-protect": "d12b66b98344623c32e1f236b2df7c6f14966b09c52c7697f3fddd8b89a7e0c9"
      },
      "matches_release": true,
      "entrypoints_exit_zero": true
    }
  ],
  "profile_states": [
    {
      "state": "absent",
      "proved_from": ["Grok installed copy", "Agy installed copy"],
      "exit_status": 0,
      "mode": "discovery-only",
      "profile_source": null,
      "subject_count": 0,
      "policy_count": 0,
      "constraint_count": 0,
      "intent_fields_unknown": 4,
      "limits_reported": 5
    },
    {
      "state": "present",
      "proved_from": ["Grok installed copy", "Agy installed copy"],
      "exit_status": 0,
      "mode": "profile",
      "profile_source": "environment",
      "profile_schema_version": "1.0",
      "site_identifier": "example-site",
      "subject_count": 2,
      "policy_count": 1,
      "constraint_count": 1
    },
    {
      "state": "unreadable",
      "proved_from": ["Grok installed copy", "Agy installed copy"],
      "exit_status": 1,
      "error_type": "ProfileUnreadableError",
      "fell_back_to_discovery_only": false
    }
  ]
}
```

The release fingerprint in that record is bound by a test: it is recomputed from
`plugins/unifi/` and compared, so this evidence cannot quietly come to describe
a package that no longer exists. That is the same failure the compatibility
matrix had, and it is closed the same way. This re-capture is that test doing
its job: the binding failed when the package changed, and it was cleared by
re-running the readback rather than by editing a digest.
