# Post-activation readback — portable UniFi package 2.0.0

The UniFi package in this repository, `plugins/unifi/`, is a derived copy of an
upstream Claude Code plugin that was released as version 2.0.0 and activated
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

The first capture of this readback described the package at tree digest
`6e6b57c1…`. Re-synchronizing the portable Fleet Core slice to release 0.25.1,
at upstream commit `ed72f439`, regenerated both
`skills/*/scripts/_bundled/retry_backoff.py` bundles and re-pinned
`plugins/unifi/PROVENANCE.json`. All three files live inside the package, so
every fingerprint in the first capture stopped identifying the shipped bytes,
and the synchronization pin it named stopped matching the manifest.

Every install, every recomputation, and all three profile states below were
captured again against the package as it now ships. No number here was carried
forward from the earlier capture. Editing the digests in place would have been
the exact failure the compatibility matrix binding exists to catch, so the
readback was re-run instead.

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
| Activated upstream release | commit `ed72f439ba01f2e20d94be074e5612c5641c0c8e`, manifest version `2.0.0` | read from a local clone at that commit, read-only |
| Synchronization pin | `plugins/unifi/PROVENANCE.json` records that same commit and version | read from this repository |
| Portable package tree | 23 files, tree digest `da46ca77…08c5` | recomputed from `plugins/unifi/` |
| Installed copies | same file count, same tree digest | recomputed from each client-owned installed tree |

The pinned commit is the one that carries Fleet Core 0.25.1: read read-only from
the same local clone, the upstream manifest at that commit declares `unifi`
version `2.0.0` and `fleet-core` version `0.25.1`. That is what makes the first
two links of the chain one revision rather than two.

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
| Grok 1.0.5 | package root | `unifi v2.0.0` | none reported | 23 files, `da46ca77…08c5` — equal to the source tree |
| Agy 1.1.18 | package root | not reported; 2 skills processed | none reported | 23 files, `da46ca77…08c5` — equal to the source tree |
| Muse 0.2.1 | each skill directory | not reported; activation on, 0 diagnostics | content digest per unit, 4 files each | `unifi-network` 4 files `96fa6e10…81a7`; `unifi-protect` 4 files `e21dd480…d629` — equal to the source units |

Two notes on reading that table honestly:

1. **Muse's content digest is Muse's algorithm, not this repository's.** The two
   values it reports —
   `30dd7da8760990b0a1d854ae2b4c3cc339c72f6ad517d00a7c97718aade8dcd6` for
   `unifi-network` and
   `7156c2545d9fe21487f419f8762c62c53eda19eb7f4299c3bb5d0b34c0b59551` for
   `unifi-protect` — are recorded because they are the client's own identifier
   for the bytes it installed, and they reproduced identically across two
   independent installs from two differently-named source directories. They are
   not claimed to equal this repository's tree digests for the same units.
2. **Only Grok reports a version at all.** Agy and Muse install and enumerate
   without surfacing one. That is a limitation of those clients, recorded rather
   than worked around; for those two, the digest equality is the whole of the
   identity proof.

Both entrypoints were then run out of each client-owned installed copy, credential-free
and with no host argument: `unifi_network_client.py --help` and
`unifi_protect_client.py --help` each exit 0 and print usage.

## The three profile states, against installed bytes

Run from `scripts/site_profile.py` inside each **installed** package copy — not
from this repository's working tree, which is the distinction R41 draws. The
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
upstream 2.0.0 release at the revision that carries Fleet Core 0.25.1; the
installed copy's entrypoints run credential-free; and the installed profile
loader distinguishes all three profile states with the documented exit statuses.

**Not proved, and not claimed.** Nothing here exercises a UniFi controller: no
subcommand was run against a live system, so this says nothing about whether any
read operation returns correct data. Nothing here re-fetches the upstream
marketplace, so the chain is verified against a local clone pinned at the
activated commit rather than against the published release surface. The readback
covers the three clients that produce a client-owned installed copy of the
package root or of the skill units; clients that link or symlink to the source
directory hold no separate bytes to read back. And every command above ran on an
interpreter above the catalog's documented Python floor, so nothing here
addresses the floor question the 0.25.1 re-synchronization raised; that is
tracked in [the engineering journal's queue](../engineering-journal/QUEUED.md).

## The machine-readable record

```json
{
  "schema_version": "1",
  "captured_on": "2026-08-22",
  "release": {
    "name": "unifi",
    "version": "2.0.0",
    "file_count": 23,
    "tree_sha256": "da46ca77d5d5290339586bdae87cbc8cb192f233f4b2f863e623b9e2b57308c5",
    "upstream_commit": "ed72f439ba01f2e20d94be074e5612c5641c0c8e",
    "units": {
      "unifi-network": {
        "file_count": 4,
        "tree_sha256": "96fa6e10bcb7d8927b15428dc7f195ae75480a965aa24d932e5a7cfba59481a7"
      },
      "unifi-protect": {
        "file_count": 4,
        "tree_sha256": "e21dd48013573783c1334edb502037a56cc23b2f6eaedc13a0bca7b66793d629"
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
      "reported_version": "2.0.0",
      "reported_digest": null,
      "recomputed_file_count": 23,
      "recomputed_tree_sha256": "da46ca77d5d5290339586bdae87cbc8cb192f233f4b2f863e623b9e2b57308c5",
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
      "recomputed_tree_sha256": "da46ca77d5d5290339586bdae87cbc8cb192f233f4b2f863e623b9e2b57308c5",
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
        "unifi-network": "30dd7da8760990b0a1d854ae2b4c3cc339c72f6ad517d00a7c97718aade8dcd6",
        "unifi-protect": "7156c2545d9fe21487f419f8762c62c53eda19eb7f4299c3bb5d0b34c0b59551"
      },
      "recomputed_file_count": 8,
      "recomputed_tree_sha256": null,
      "recomputed_units": {
        "unifi-network": "96fa6e10bcb7d8927b15428dc7f195ae75480a965aa24d932e5a7cfba59481a7",
        "unifi-protect": "e21dd48013573783c1334edb502037a56cc23b2f6eaedc13a0bca7b66793d629"
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
