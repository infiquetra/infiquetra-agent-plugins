---
name: review-setup
description: Survey the pinned review tools on this machine and record the Semgrep rule-pack digest. Use when someone asks to set up review tools, check scanner pins, or install the tools a review needs. Suggest code-review for a diff or pull request, security-review for a repository security audit, and doc-review for a plan, spec, or issue.
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

Read the table. It names each tool, its lens, its status, and its pinned version. Ask before installing anything the survey marks missing. After the operator installs a named tool, run the survey again.

Suggest `code-review` for a diff or pull request, `security-review` for a repository security audit, and `doc-review` for a plan, spec, or issue.
