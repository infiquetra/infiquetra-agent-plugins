# Importing agent-launcher and authoring it here

Date: 2026-09-22

Related: [custody move plan](../../plans/2026-09-22-custody-move-and-claude-plugins-retirement-plan.md).

## What changed

`plugins/agent-launcher` was a derived port of upstream 1.0.0. It is now the
package from `infiquetra-claude-plugins` commit `acc99fe71e25ad8a898eace7033051a7f1c3079e`
(upstream 1.7.0), authored here at 1.7.1. `PROVENANCE.json` is gone.
`ports/agent-launcher.json` keeps the assessment block and drops `source` and
`custody`. The new tree adds `roster.py`, `composer.py`, and `roles/`. There
is no Fleet Core bundle: nothing in the package loads a Fleet Core module.

## What was non-obvious

### The cache ladder is not the same path as `CLAUDE_PLUGIN_ROOT`

**Evidence.** Upstream `SKILL.md` and `README.md` set
`S="$CLAUDE_PLUGIN_ROOT/skills/agent-launcher/scripts/launcher.py"` and, if
that file is missing, take the highest version under
`~/.claude/plugins/cache/*/agent-launcher/`. The contract tests require the
`$S` launch lines. They do not require the cache fallback.

**Mechanism.** Skills stay at the package root, so `$CLAUDE_PLUGIN_ROOT`
still names this package after install. The cache fallback names a different
install. The fallback was removed. The skill also says to resolve
`skills/agent-launcher/scripts/launcher.py` from the package root, which is
how a harness that does not set `CLAUDE_PLUGIN_ROOT` runs the script.

**Generalizable rule.** A `${CLAUDE_PLUGIN_ROOT}` path into `skills/` or
`scripts/` is still this package. A path into the Claude plugin cache is a
different tree and does not belong in the portable skill.

### Orchestrate is not in this checkout, and the launcher tests were written against it

**Evidence.** Upstream `plugins/agent-launcher/tests/test_launcher_contract.py`
and `tests/test_agent_launcher_plugin.py` load
`plugins/orchestrate/scripts` and the upstream marketplace. This catalog does
not contain Orchestrate yet. `parents[3]` from
`plugins/agent-launcher/tests/` is still this repository root, so the path
arithmetic did not need a rewrite. The files those tests open are simply absent.

**Mechanism.** Tests whose subject is Orchestrate, the upstream journal, or
the upstream marketplace were dropped and named in `CHANGELOG.md`. The
launcher-only half of the pane-write net stayed. `test_roster.py` is carried;
a test that needs `plugins/saga/scripts/run_record.py` or Fleet Core's
`staffing.json` skips when that file is absent, because those packages are
imported on other branches. `test_roles_library.py` checks the prompts
against the vendored lifecycle snapshot. Its parity check found the sibling
`infiquetra-sdlc` checkout at `5efc869f`, which is the pin, and passed.

**Generalizable rule.** A test that opens a sibling plugin is that sibling's
premise. Skip it when the sibling is not in the checkout. Drop it when the
sibling is a different repository's layout and will not become a sibling here
under the same path.

### The version-bound matrix cannot be both superseded and still the file the root README cites

**Evidence.** `tests/test_check_compatibility_matrix.py` fails a current
matrix whose recorded version is not the package version, and it fails a
markdown link to a superseded evidence file unless the link text says the
citation is historical. The root `README.md` links
`2026-08-27-agent-launcher-compatibility-matrix.md` and the post-activation
readback in the present tense. This unit was told not to edit that README.

**Mechanism.** The 1.0.0 matrix body moved to
`2026-08-27-agent-launcher-compatibility-matrix-pre-authored-import.md` with
the superseded banner, pointing back at the original filename. That filename
is now a short current notice: 1.7.1 has no ten-client run. The notice carries
a fenced JSON object that is neither a matrix nor a readback, because the
discovery test calls `extract_record` on every evidence markdown file and
raises when a file has no JSON fence. The readback filename stays
non-superseded. Its release `file_count` and `tree_sha256` were rebound to
the imported tree (33 files, `115944ac13a4b3300ee44ae5b7ea9db05ce8dee855c90af547eb74c75ce99157`).
The recorded version stays 1.0.0, and the document says the client rows were
not re-run.

**Generalizable rule.** Supersede a matrix by moving the record, not by
changing the status of a filename other documents already cite, unless those
citations are updated in the same commit. A notice that replaces a matrix has
to contain some fenced JSON object or the evidence walk raises before it can
decide the file is not a readback.

### Deleting the provenance manifest breaks one journal link

**Evidence.** `scripts/check_repo.py` reports a markdown link whose target
does not exist. `docs/engineering-journal/DECISIONS.md` linked
`plugins/agent-launcher/PROVENANCE.json`. The mutation-proof binding on
`scripts/check_repo.py` is why that script was not edited to ignore the link.

**Mechanism.** The link now targets `plugins/agent-launcher/CHANGELOG.md`,
which is where the import commit is recorded. The decision prose around the
link is historical and was left as it was.

**Generalizable rule.** When a provenance manifest is deleted, retarget the
journal link at the changelog. Do not edit the link checker to make the
dangling link legal.

## Design calls

- The two repository tests `tests/test_agent_launcher_packaging.py` and
  `tests/test_agent_launcher_rule_audit.py` were updated. They pin this
  package, the gate runs them, and no other import branch should touch them.
  Custody assertions skip now that the descriptor is authored. The doc-guard
  predicates were updated for the 1.7.0 skill wording, and the mutation-proof
  digests were recomputed.
- `roster.py` and `launcher.py` are both assessment entrypoints. `up` and
  `down` joined `launch` and `close` as mutating operations. `roster.py --help`
  exits before it looks for saga.
- The changelog cites the full upstream commit. The roles-library test treats
  a bare 8-hex token in the current changelog entry as a second lifecycle pin,
  and `acc99fe7` is 8 hex digits. The full id
  `acc99fe71e25ad8a898eace7033051a7f1c3079e` is the same commit. The entry also
  names the roles pin `5efc869f`.
- The personal keychain service name and the home-lab Ansible sentence were
  removed from the skill. The slug and statusline examples in `launcher.py`
  use `example` and `operator`. Account-label behaviour is unchanged.
- The package `.gitignore` (`__pycache__/`, `*.pyc`, `*.pyo`) was not in the
  upstream tree and was not put back. The repository root `.gitignore` already
  ignores `__pycache__/`.
- Local mission-control template-sync failures against the sibling
  `infiquetra-sdlc` checkout (a `Risk` field the committed reference does not
  list) were left alone. They are not caused by this import. Continuous
  integration skips them when that checkout is absent.
