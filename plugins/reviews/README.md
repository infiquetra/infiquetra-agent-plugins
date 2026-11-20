# reviews

Standalone review package for a git range, a committed-tree security audit, SDLC document rubrics, and review-tool setup.

| Skill | When to use it |
|---|---|
| [code-review](skills/code-review/SKILL.md) | A diff or pull request. `--base` and `--head` select the range. `--issue` is optional. The packet is `.reviews/` or `--out`. |
| [security-review](skills/security-review/SKILL.md) | A committed repository tree. Scanner results and reasoned findings stay in separate sections. |
| [doc-review](skills/doc-review/SKILL.md) | A plan, spec, or issue. Rubrics cover `idea`, `spec`, and `issue`. |
| [review-setup](skills/review-setup/SKILL.md) | Tool pins and the Semgrep rule-pack digest on this machine. |

Packets and grades are produced by `scripts/review_command.py`. The grade calculation is `scripts/review_formula.py`. Security scans go through `scripts/security_scan.py`. Document rubrics go through `scripts/lifecycle_review.py`. `scripts/builder_record.py check` judges one builder-record file against this package's policy list and the proving tests named in it. It does not open an issue file. `write` merges that file onto one unit of `issue-<N>.json` in the directory given by `--store-root`.

The machine record is `~/.config/infiquetra/reviews/machine.json`. When that file is absent, reads fall back to `~/.saga/machine.json` and do not rewrite it.

```bash
python3 plugins/reviews/scripts/review_command.py --help
python3 plugins/reviews/scripts/security_scan.py --help
python3 plugins/reviews/scripts/lifecycle_review.py --help
python3 plugins/reviews/scripts/review_setup.py --help
python3 plugins/reviews/scripts/builder_record.py --help
```
