---
name: review-setup
description: Survey the pinned review tools on this machine, record the Semgrep rule-pack digest, and build the offline pip-audit and npm-audit advisory snapshots from local OSV databases. Use when someone asks to set up review tools, check scanner pins, build advisory snapshots, or install the tools a review needs. Suggest code-review for a diff or pull request, security-review for a repository security audit, and doc-review for a plan, spec, or issue.
---

# Review Setup

Survey this machine's review tools and record what is installed. Install a tool only when the operator names that tool.

The script is `scripts/review_setup.py` at the package root, two directories above this skill. Run that file by its path. Do not resolve the script from the repository checkout you are editing: a standalone install is not that repository's working directory.

```bash
# SKILL_DIR is the directory that contains this SKILL.md.
# CLAUDE_PLUGIN_ROOT is the package root when the package is installed.
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  S="$CLAUDE_PLUGIN_ROOT/scripts/review_setup.py"
else
  S="$SKILL_DIR/../../scripts/review_setup.py"
fi
python3 "$S" survey --repo <repository> --home <home>
```

The machine record is written to `~/.config/infiquetra/reviews/machine.json` (or `<home>/.config/infiquetra/reviews/machine.json`). When that file is absent, reads fall back to `~/.saga/machine.json` and do not rewrite it. The survey records the digest of a local Semgrep rule-pack cache when one is present. It does not download a pack and it does not install a tool.

## Advisory snapshots

The pip-audit and npm-audit rows read local advisory snapshots and never ask the network. Build them from the OSV databases osv-scanner already downloaded:

```bash
python3 "$S" advisories --home <home>
```

It reads `<home>/.config/infiquetra/reviews/advisories/osv-scanner/osv-scalibr/<PyPI|npm>/all.zip` (or the legacy `~/.saga/advisories/` copy) and writes `advisories.json` and `metadata.json` under `advisories/pip-audit/` and `advisories/npm-audit/`. It prints each file's size and its advisory, package and entry counts, and the records it could not express offline. It exits non-zero and names the missing path when a database is absent. Download one only when the operator asks:

```bash
env OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY=<home>/.config/infiquetra/reviews/advisories/osv-scanner \
  osv-scanner scan source --offline-vulnerabilities --download-offline-databases --lockfile <a lock file>
```

Run `advisories` again after a download, then run the survey so the machine record lists the new snapshot versions. The entry format and the matching rules are in `references/review-tools.md` under "Offline advisory snapshots".

Read the table. It names each tool, its lens, its status, and its pinned version. Ask before installing anything the survey marks missing. After the operator installs a named tool, run the survey again.

Suggest `code-review` for a diff or pull request, `security-review` for a repository security audit, and `doc-review` for a plan, spec, or issue.
