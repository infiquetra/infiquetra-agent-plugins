<!-- matrix-status: readback -->

# Post-activation readback — portable agent-launcher package

This readback was taken from the frozen portable package in
`plugins/agent-launcher/` after the ten-client compatibility matrix
(`docs/evidence/2026-08-27-agent-launcher-compatibility-matrix.md`) and before
closeout. Its content binding is the package tree digest, recomputed at
readback time; the commit named below is where the package bytes were frozen,
not the binding itself.

## The frozen candidate

- **Package tree.** `plugins/agent-launcher/`, 11 files, tree digest
  `65beaf769dfeb8fdb5c80f26e1b4dc6ce21527044f082c5e7d1ec21c9280fb65`,
  recomputed with
  `python3 scripts/check_compatibility_matrix.py --print-fingerprint agent-launcher`
  and equal to the fingerprint recorded in the matrix before and after the run.
- **Frozen at commit `29a29758894c05e1a16c5e3f943dee62d1ba02ab`.** The evidence
  documents committed after it do not touch the package tree; any later commit
  that moved `plugins/agent-launcher/` would retire this readback and the
  matrix, and the re-run obligation in the plan's KTD10 would apply.
- **Upstream pin.** `infiquetra-claude-plugins` commit
  `8269f84b01065ac96d162431ce00ebd42003dd5f` (plugin version 1.0.0), recorded
  in `plugins/agent-launcher/PROVENANCE.json` and re-verified by
  `scripts/sync_vendor_source.py --check` at readback time.
- **Python 3.12 floor.** The staged entrypoint blob was extracted from the index
  (`git show :plugins/agent-launcher/skills/agent-launcher/scripts/launcher.py`)
  and answered `--help` on CPython 3.12.13 (`/opt/homebrew/bin/python3.12`) in
  a throwaway virtual environment holding no third-party dependencies, because
  the entrypoint is standard library only. The floor is verified from staged
  bytes, not from the source tree.

## The custody chain

| Link | What identifies it | How it was checked |
|---|---|---|
| Pinned upstream release | commit `8269f84b01065ac96d162431ce00ebd42003dd5f`, manifest version `1.0.0` | read from the upstream checkout; suite green at the pin from a disposable scratch clone (36 passed) |
| Synchronization pin | `plugins/agent-launcher/PROVENANCE.json` records that same commit and version | verified by `scripts/sync_vendor_source.py --check` |
| Portable package tree | 11 files, tree digest `65beaf76…725` | recomputed with `--print-fingerprint agent-launcher` |

## Installed-version and digest readback

Copies installed into empty scratch homes during the ten-client assessment,
recomputed at readback time from the run workspace:

| Client | Install unit | Client-reported version | Client-reported digest | Recomputed from installed bytes |
|---|---|---|---|---|
| Claude Code | package root (session-scoped) | not reported (session-scoped listing says version unknown) | none reported | 11 files, digest equal to the source package |
| Grok | package root (installed-plugin id) | not reported | none reported | 11 files, digest equal to the source package |
| Agy | package root (re-validated installed copy) | not reported | none reported | 11 files, digest equal to the source package |
| Qwen | copied extension | package version `1.0.0` with manifest description | none reported | the 11 package files equal to the source, plus one client bookkeeping file the installer adds of its own |
| OpenCode | skill directory | not reported | none reported | 2 files, digest equal to the source skill unit |
| Gemini CLI | linked skill | not reported | none reported | 2 files, digest equal to the source skill unit |
| Muse | skill directory (user scope) | not reported | content digest reported by the forced JSON install | 2 files, digest equal to the source skill unit |
| Hermes | skill directory (profile) | not reported | none reported | 2 files, digest equal to the source skill unit |

Cursor Agent was assessed against the real home with session-scoped read-only
probes (no installed copy to recompute); OpenAI Codex placed nothing (it names
a marketplace manifest this package does not ship), so there is no installed
copy for either. The single package entrypoint answered `--help` with exit 0
from every client-resolved copy the matrix reached, under CPython 3.12.13.

## Mutation-proof verification

The mutation-proof obligation is discharged by
`docs/evidence/2026-08-27-agent-launcher-mutation-proof-portable-docs.txt`
(eight mutation classes, zero survivors). At readback the two graded files were
verified by SHA-256 digest re-check against the proof footer:

| Graded file | Proof footer digest | Recomputed at readback | Match |
|---|---|---|---|
| `plugins/agent-launcher/skills/agent-launcher/SKILL.md` | `b66b0ab42bab808900814d84f035029cf9980fb9222f82e45a0b61eb2d296dc0` | `b66b0ab42bab808900814d84f035029cf9980fb9222f82e45a0b61eb2d296dc0` | YES |
| `plugins/agent-launcher/README.md` | `fb0f08d28880f4e85ea39cf50089ab74f67c4efc57d9c2d8bf481cb73efaceeb` | `fb0f08d28880f4e85ea39cf50089ab74f67c4efc57d9c2d8bf481cb73efaceeb` | YES |

`MutationProofBindingTest` in `tests/test_agent_launcher_rule_audit.py` passed
during the hermetic suite run at the frozen candidate.

## What this proves, and what it does not

**Proved.** A client installing `agent-launcher` from a cold start holds
exactly the bytes synchronized from upstream `infiquetra-claude-plugins` at
`8269f84b`; the package entrypoint runs credential-free on Python 3.12.13 from
every client-resolved copy; the one skill unit parses and loads cleanly across
the skill-scoped clients; and the mutation-proof binding matches the frozen
candidate bytes.

**Not proved, and not claimed.** No live agent session was launched and no
Herdr mutation was made: the assessment invokes the entrypoint as `--help` and
the safety rule blocks the `launch` and `close` verbs in advance. Launching a
real session remains the operator's act under the contract.

## The machine-readable record

```json
{
  "schema_version": "1",
  "captured_on": "2026-08-27",
  "release": {
    "name": "agent-launcher",
    "version": "1.0.0",
    "file_count": 11,
    "tree_sha256": "65beaf769dfeb8fdb5c80f26e1b4dc6ce21527044f082c5e7d1ec21c9280fb65",
    "upstream_commit": "8269f84b01065ac96d162431ce00ebd42003dd5f",
    "units": {
      "agent-launcher": {
        "file_count": 2,
        "tree_sha256": "3f5225c1efa83051398396f6d9cde3506e18ebabee077c8a1ee2e1ddb7f6f75e"
      }
    }
  },
  "method": {
    "credentials": "No client authenticated; the package declares no credential prefixes and none were supplied.",
    "network": "No remote API call at any stage; the entrypoint was invoked credential-free as --help. The upstream release was verified against a disposable scratch clone pinned at the activated commit.",
    "isolation": "Each client ran under an empty scratch home with empty configuration, except Cursor Agent against the real home with read-only session-scoped probes. No real configuration was read or written."
  },
  "readbacks": [
    {
      "client": "Claude Code",
      "client_version": "2.1.247",
      "install_unit": "package-root",
      "reported_version": null,
      "reported_digest": null,
      "recomputed_file_count": 11,
      "recomputed_tree_sha256": "3eb0aeb5b4634ebf51d0ccac195b9ad81877116514c2347891d4608ce92520df",
      "matches_release": true,
      "entrypoints_exit_zero": true
    },
    {
      "client": "OpenAI Codex",
      "client_version": "0.150.1",
      "install_unit": null,
      "reported_version": null,
      "reported_digest": null,
      "recomputed_file_count": null,
      "recomputed_tree_sha256": null,
      "matches_release": null,
      "entrypoints_exit_zero": null
    },
    {
      "client": "Cursor Agent",
      "client_version": "2026.08.25-3e8eec8",
      "install_unit": "session-scoped-probe",
      "reported_version": null,
      "reported_digest": null,
      "recomputed_file_count": null,
      "recomputed_tree_sha256": null,
      "matches_release": null,
      "entrypoints_exit_zero": true
    },
    {
      "client": "Qwen",
      "client_version": "0.22.2",
      "install_unit": "copied-extension",
      "reported_version": "1.0.0",
      "reported_digest": null,
      "recomputed_file_count": 12,
      "recomputed_tree_sha256": "384291bf53723eeb6c0ace493e31a4745d4d8bae0705cd788bf5614ec8a48d46",
      "matches_release": true,
      "entrypoints_exit_zero": true
    },
    {
      "client": "Grok",
      "client_version": "1.0.5",
      "install_unit": "package-root",
      "reported_version": null,
      "reported_digest": null,
      "recomputed_file_count": 11,
      "recomputed_tree_sha256": "3eb0aeb5b4634ebf51d0ccac195b9ad81877116514c2347891d4608ce92520df",
      "matches_release": true,
      "entrypoints_exit_zero": null
    },
    {
      "client": "OpenCode",
      "client_version": "1.18.18",
      "install_unit": "skill-directory",
      "reported_version": null,
      "reported_digest": null,
      "recomputed_file_count": 2,
      "recomputed_tree_sha256": "3f5225c1efa83051398396f6d9cde3506e18ebabee077c8a1ee2e1ddb7f6f75e",
      "matches_release": true,
      "entrypoints_exit_zero": true
    },
    {
      "client": "Gemini CLI",
      "client_version": "0.44.1",
      "install_unit": "skill-directory",
      "reported_version": null,
      "reported_digest": null,
      "recomputed_file_count": 2,
      "recomputed_tree_sha256": "3f5225c1efa83051398396f6d9cde3506e18ebabee077c8a1ee2e1ddb7f6f75e",
      "matches_release": true,
      "entrypoints_exit_zero": true
    },
    {
      "client": "Muse",
      "client_version": "0.2.1",
      "install_unit": "skill-directory",
      "reported_version": null,
      "reported_digest": {"algorithm": "client-defined content digest"},
      "recomputed_file_count": 2,
      "recomputed_tree_sha256": "3f5225c1efa83051398396f6d9cde3506e18ebabee077c8a1ee2e1ddb7f6f75e",
      "matches_release": true,
      "entrypoints_exit_zero": true
    },
    {
      "client": "Agy",
      "client_version": "1.1.22",
      "install_unit": "package-root",
      "reported_version": null,
      "reported_digest": null,
      "recomputed_file_count": 11,
      "recomputed_tree_sha256": "3eb0aeb5b4634ebf51d0ccac195b9ad81877116514c2347891d4608ce92520df",
      "matches_release": true,
      "entrypoints_exit_zero": true
    },
    {
      "client": "Hermes",
      "client_version": "0.20.5",
      "install_unit": "skill-directory",
      "reported_version": null,
      "reported_digest": null,
      "recomputed_file_count": 2,
      "recomputed_tree_sha256": "3f5225c1efa83051398396f6d9cde3506e18ebabee077c8a1ee2e1ddb7f6f75e",
      "matches_release": true,
      "entrypoints_exit_zero": true
    }
  ],
  "mutation_proof_verification": {
    "disposition": "verified_by_digest_recheck",
    "proof_document": "docs/evidence/2026-08-27-agent-launcher-mutation-proof-portable-docs.txt",
    "frozen_candidate_commit": "29a29758894c05e1a16c5e3f943dee62d1ba02ab",
    "graded_file_digests": {
      "plugins/agent-launcher/skills/agent-launcher/SKILL.md": "b66b0ab42bab808900814d84f035029cf9980fb9222f82e45a0b61eb2d296dc0",
      "plugins/agent-launcher/README.md": "fb0f08d28880f4e85ea39cf50089ab74f67c4efc57d9c2d8bf481cb73efaceeb"
    },
    "all_digests_match_proof_footer": true,
    "mutation_proof_binding_test_passed": true
  }
}
```
