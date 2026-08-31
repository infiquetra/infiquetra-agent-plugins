# Post-activation readback — portable mission-control package 2.15.2

The `mission-control` package in this repository, `plugins/mission-control/`, is a
portable derived copy of an upstream Claude Code plugin synchronized from
`infiquetra/infiquetra-claude-plugins` at pinned commit
`3b2b7083fdda8e39e213b5f4acf9f8301d60dd52` (version 2.15.2). Following runbook
Phase 3, this document captures the post-activation readback and verification
bound to the frozen candidate commit (`55a651174b8b474c281661658bde3bfd7637855b`),
on 30 August 2026.

## Context and Purpose

A readback proves what client-installed copies actually hold on disk from
cold-start installations, rather than inferring behavior from source tree files
alone:

- An installed-version and digest readback across client-owned installed copies;
- Credential-free and offline entrypoint verification under the declared Python
  3.12 floor;
- Verification of the cycle-16 mutation proof by digest re-check.

Held identical throughout: **credential-free** (no client authenticated, every
`GH_` and `GITHUB_` variable stripped), **read-only and offline** (no GitHub API
call or network request; entrypoints ran `--help` only), **isolated** (each
client ran in an isolated scratch home with empty configuration), and **on the
floor** (every command executed on CPython 3.12.13 in a throwaway virtual
environment holding pytest, pyyaml, requests, and urllib3).

## The Custody Chain

Upstream stays the single writable source; this package is a derived artifact.
The readback binds this document to the shipped bytes: the release block
records the package fingerprint, each of the seven skill units its own
fingerprint, and every readback entry the bytes recomputed from the
client-installed copy.

## Machine-readable record

```json
{
  "schema_version": "1",
  "captured_on": "2026-08-30",
  "release": {
    "name": "mission-control",
    "version": "2.15.2",
    "file_count": 71,
    "tree_sha256": "1f49322e8412ac6b2ae0b1fbebf4a022ac2e53489be71aae674506a7613531f9",
    "upstream_commit": "3b2b7083fdda8e39e213b5f4acf9f8301d60dd52",
    "units": {
      "board": {
        "file_count": 3,
        "tree_sha256": "6e6f9109e3c6a2b9abe4dd184eb9ee678d514be9d88d30f72d5b444d90400e9b"
      },
      "flow": {
        "file_count": 1,
        "tree_sha256": "62221391538fcb23568a4233549889938aef8da92bb5d1996b0e4ee6d4bedc86"
      },
      "issues": {
        "file_count": 3,
        "tree_sha256": "8b2553a38cb654d66d813970cfcc6c3152bd5d80ce73853ca39ad9ccb5c53aab"
      },
      "labels": {
        "file_count": 2,
        "tree_sha256": "deeb29d013af01c0db93a48f789603edbea772f4e5a99a8bd7c6f7ed05ba02ef"
      },
      "metrics": {
        "file_count": 2,
        "tree_sha256": "7e02183cb2ffce6245502d2a5421b607b9a9e8b3290b35dc7ac822948ea3f032"
      },
      "milestones": {
        "file_count": 2,
        "tree_sha256": "73ae762b238773f4f7fcdb7c672714bc7eda15b0518eed38cc3e7385bfd87574"
      },
      "rollout": {
        "file_count": 2,
        "tree_sha256": "0ff96a5380bac2fcba3c344043092e5c0468fe2870a9e00a04ece787856b85a6"
      }
    }
  },
  "method": {
    "credentials": "No client authenticated; every GH_ and GITHUB_ variable removed from the environment before every command.",
    "network": "No GitHub API call, no marketplace refresh, no network request. The upstream release was verified against a local read-only checkout pinned at the recorded commit.",
    "isolation": "Each readback ran against the client-owned installed copies under their empty scratch homes, with no real configuration read or written."
  },
  "readbacks": [
    {
      "client": "Agy",
      "client_version": "1.1.22",
      "install_unit": "package-root",
      "reported_version": null,
      "reported_digest": null,
      "recomputed_file_count": 71,
      "recomputed_tree_sha256": "1f49322e8412ac6b2ae0b1fbebf4a022ac2e53489be71aae674506a7613531f9",
      "matches_release": true,
      "entrypoints_exit_zero": true
    },
    {
      "client": "Grok",
      "client_version": "1.0.13",
      "install_unit": "package-root",
      "reported_version": "2.15.2",
      "reported_digest": null,
      "recomputed_file_count": 71,
      "recomputed_tree_sha256": "1f49322e8412ac6b2ae0b1fbebf4a022ac2e53489be71aae674506a7613531f9",
      "matches_release": true,
      "entrypoints_exit_zero": true
    },
    {
      "client": "Muse",
      "client_version": "1.0.1",
      "install_unit": "skill-directory",
      "reported_version": null,
      "reported_digest": {
        "algorithm": "per-skill-unit tree sha256, recomputed from the installed bytes",
        "board": "6e6f9109e3c6a2b9abe4dd184eb9ee678d514be9d88d30f72d5b444d90400e9b",
        "flow": "62221391538fcb23568a4233549889938aef8da92bb5d1996b0e4ee6d4bedc86",
        "issues": "8b2553a38cb654d66d813970cfcc6c3152bd5d80ce73853ca39ad9ccb5c53aab",
        "labels": "deeb29d013af01c0db93a48f789603edbea772f4e5a99a8bd7c6f7ed05ba02ef",
        "metrics": "7e02183cb2ffce6245502d2a5421b607b9a9e8b3290b35dc7ac822948ea3f032",
        "milestones": "73ae762b238773f4f7fcdb7c672714bc7eda15b0518eed38cc3e7385bfd87574",
        "rollout": "0ff96a5380bac2fcba3c344043092e5c0468fe2870a9e00a04ece787856b85a6"
      },
      "recomputed_file_count": 15,
      "recomputed_tree_sha256": null,
      "matches_release": true,
      "entrypoints_exit_zero": true
    }
  ],
  "cycle_16_verification": {
    "disposition": "verified_by_digest_recheck",
    "proof_document": "docs/evidence/2026-08-25-cycle16-mutation-proof-portable-copies.txt",
    "frozen_candidate_commit": "55a651174b8b474c281661658bde3bfd7637855b",
    "graded_file_digests": {
      "plugins/unifi/scripts/site_profile.py": "31c9695fbc2ebdbe3401c7a06b9d40b284991ece5f380f1b0c4413d3427e5b09",
      "scripts/assess_clients.py": "2f8fafe988f791e53403d619ed61e4749930838435d001993e8cf581ca1ad9d8",
      "scripts/check_compatibility_matrix.py": "1b03201cad5f94ed7c717738020dd1e9c5975e527f94eb46211ca5b96bfa4834",
      "scripts/check_repo.py": "6cf74eb943e790a4a335984bb8fc294aa0d4f2905bb99cbecba8d74a3106f90a",
      "scripts/port_config.py": "bfaeb49285558435195382050ed6bde4d7736e8f42be3665b569cdfd849c927b"
    },
    "all_digests_match_cycle_16_footer": true,
    "mutation_proof_binding_test_passed": true
  }
}
```
