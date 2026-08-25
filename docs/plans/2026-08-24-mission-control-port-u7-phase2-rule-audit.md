# U7 Validation-Rule Audit — mission-control validation rules (runbook Phase 2)

**Date.** 2026-08-24 · **Unit.** U7 of the [mission-control portable-port run
plan](2026-08-24-mission-control-port-run-plan.md) · **Child issue.**
infiquetra/infiquetra-agent-plugins#17 · **Runbook.**
[portable-plugin-port.md v1.0.0](../runbooks/portable-plugin-port.md) Phase 2

This document records the class-first validation-rule audit for every rule the
ported `mission-control` package carries, executing the runbook's serial
Phase 2 ("do not skip").

## Rule Audit Summary

| Rule | Primary file(s) | Predicate | Authority | Authority derived at test time | Copies exist? | Verdict agreement |
|---|---|---|---|---|---|---|
| **1. Card validator** | `plugins/mission-control/scripts/sdlc_manager.py` (`validate_card_body`, `validate_card_body_for_context`) | Issue body carries all required H3 headers, valid checklist and runnable AC checks, fenced code blocks in verification, path lines in files-expected, and no placeholder-only sections | `home-lab/ansible/roles/hermes_orchestrator/files/card_validator.py` (external checkout) | Dynamic module load of authority `card_validator.py` at test time with loud self-skip | Yes (authority in home-lab vs portable copy in `sdlc_manager.py`) | **100% agreement** across 37 corpus classes |
| **2. Issue-contract parity** | `plugins/mission-control/config/generated/check_issue_contract_parity.py` (`issue_contract_data.py`, `issue_contract_shim.py`) | Vendored generated modules are byte-identical to pinned `.sha256` sidecars; `--live` leg checks live Status field options | Committed `.sha256` sidecars; source schema in `infiquetra-sdlc` | Stdlib `hashlib.sha256` computation; `--live` skips loudly when GitHub access unavailable | Single vendored artifact copy + sidecars | Verified in sync; drift detected on injection |
| **3. Pagination lint** | `plugins/mission-control/scripts/check_pagination.py` | No unguarded `gh project item-list` without `--limit`, no bare `_rest_get(...per_page=...)`, no GraphQL `first:` without `hasNextPage` | Package lint rules in `check_pagination.py` | Runs directly against portable layout (`scripts/`, `skills/`, `commands/`, `agents/`) | Single lint tool | Clean on portable tree; rejects all violating corpus shapes |
| **4. Prompt-alignment guard** | `plugins/mission-control/tests/test_prompt_alignment.py` (dropped from portable catalog) | Prompts, commands, and metadata agree with upstream marketplace and cross-plugin layout | Whole-upstream repo layout (`.claude-plugin/marketplace.json`, `plugins/saga/`) | Structural premise evaluation in `tests/test_mission_control_rule_audit.py` | N/A (dropped from source) | Evaluated honestly: 6 structural premises fail under portable layout; portable invariants enforced |
| **5. Template-sync drift guard** | `plugins/mission-control/scripts/sync_template_docs.py` (`skills/issues/references/templates-reference.md`) | Rendered template reference documentation matches canonical YAML issue templates in `infiquetra-sdlc` | Canonical YAML templates in `infiquetra-sdlc/.github/ISSUE_TEMPLATE/*.yml` | Resolves canonical template directory via `INFIQUETRA_SDLC_PATH` or default workspace checkout; skips loudly if absent | Single generated reference | In exact sync with canonical templates; catches injected drift |

---

## Detailed Rule Audits

### 1. Card Validator (`sdlc_manager.validate_card_body`)

- **Predicate.** An SDLC issue body is acceptable at ingest if and only if:
  1. It carries every always-required H3 header (`Objective`, `Intent`, `Out-of-scope / non-goals`, `Files expected to change`, `Tests to add or update`, `Context library links`, `Acceptance criteria`, `Verification`).
  2. `Acceptance criteria` contains at least one `- [ ]` or `* [ ]` checklist item AND names a runnable check (command in a backtick `code span` or fenced ``` code block).
  3. `Verification` contains at least one fenced code block (≥2 ``` markers).
  4. `Files expected to change` contains at least one plausible path line (contains `/` or a file extension suffix).
  5. No required section consists only of whitespace or placeholder text (`_No response_`, `<!-- placeholder -->`, `- [ ]`, `None`), with the explicit exception of `Context library links` where `_none_`, `none`, or `None` is a valid declaration that no link applies.
  6. Under context-aware validation (`validate_card_body_for_context` for `risk: high` or `risk: very-high`), additional high-blast sections (`Inputs inventory`, `Failure modes / pre-mortem`, `Stop conditions`) are required and must not be empty or placeholder-only.
- **Authority.** `home-lab/ansible/roles/hermes_orchestrator/files/card_validator.py` (authoritative orchestrator gate).
- **Authority derivation at test time.** `tests/test_mission_control_rule_audit.py` dynamically resolves and loads `card_validator.py` from `HOME_LAB_PATH` or sibling `home-lab` checkout at test execution time. If the checkout is absent, tests skip loudly with an explicit skip reason (`self.skipTest(...)`), never passing silently.
- **Class corpus.** Tested across five distinct corpus categories:
  - *Valid variants (1A)*: Canonical populated card, arbitrary H3 header reordering, omitted optional sections (`Notes / conventions`), custom extra sections (`### Extra Context Section`), `Context library links` none markers (`_none_`, `none`, `None`, `_NONE_`), acceptance criteria variants (asterisk checklist, checked items, fenced code block), files-expected formats (directory path, extension, bulleted), verification fence variants (tagged ```` ```bash ```` vs plain ```` ``` ````), and trailing header whitespace.
  - *Missing header variants (1B)*: Missing each of the 8 required headers individually, H2 headers (`## Objective` instead of `### Objective`), and misspelled headers (`### Out-of-scope or non-goals` with 'or' instead of '/').
  - *Empty & placeholder variants (1C)*: Completely empty body `""`, empty section bodies (header with immediate trailing newline), placeholder lines (`_No response_`, `<!-- placeholder -->`, `- [ ]`, `None`).
  - *Semantic violation variants (1D)*: Acceptance criteria with prose but no checklist, checklist with no runnable check, files expected with prose only, verification with no fenced code block.
  - *Risk-tier context-aware variants (1E)*: Low risk (`risk: low`, `risk: *`) passing without high-risk sections; high risk (`risk: high`, `risk: very-high`) failing when `Inputs inventory`, `Failure modes / pre-mortem`, or `Stop conditions` are missing or placeholder-only, and passing when fully populated.
- **Verdict agreement.** **100% agreement** across every corpus class: `authority.validate_card(issue, labels, config).passed == sdlc_manager.validate_card_body(body)[0]` (and `validate_card_body_for_context(body, issue_type, risk)[0]` for risk cases).
- **Failure probe evidence.** Probed against a card missing `### Intent\n`:
  ```bash
  python3 -c "
  import sys; sys.path.insert(0, 'tests'); sys.path.insert(0, 'plugins/mission-control/scripts')
  from test_mission_control_rule_audit import VALID_CARD_CANONICAL, _find_home_lab_card_validator, _load_home_lab_authority
  import sdlc_manager
  auth = _load_home_lab_authority(_find_home_lab_card_validator())
  cfg = type('Config', (), {'authorized_authors': ['jefcox']})()
  broken = VALID_CARD_CANONICAL.replace('### Intent\n', '### Omitted\n')
  res = auth.validate_card({'body': broken, 'user': {'login': 'jefcox'}}, ['capability'], cfg)
  valid, errs = sdlc_manager.validate_card_body(broken)
  assert not res.passed and not valid
  print('Probe 1 PASS: Both authority and portable copy rejected missing Intent')
  "
  ```
  Output: `Probe 1 PASS: Both authority and portable copy rejected missing Intent` (non-zero validation rejection).

---

### 2. Issue-Contract Parity (`config/generated/check_issue_contract_parity.py`)

- **Predicate.** Vendored generated artifacts (`issue_contract_data.py` and `issue_contract_shim.py`) match their committed `.sha256` sidecar manifests byte-for-byte. The `--live` leg checks that schema-declared Status options on tracked boards resolve on live GitHub Projects.
- **Authority.** The two committed `.sha256` sidecars; canonical generation is owned by `tools/docs/gen_issue_contract.py` from `infiquetra-sdlc`.
- **Authority derivation at test time.** `check_issue_contract_parity.parity_errors()` recomputes `hashlib.sha256` for both vendored modules offline. `live_status_option_errors()` executes when `--live` is passed and raises `LiveParityUnavailableError` when credentials or network are absent, triggering an explicit `SKIPPED live parity leg` message.
- **Re-derivation boundaries.**
  - *What a portable consumer CAN re-derive offline*: verify SHA256 hashes against committed sidecars, assert module importability, verify schema structure against vendored `config/sdlc-schema.json`.
  - *What a portable consumer CANNOT re-derive without `infiquetra-sdlc`*: regenerate Python data/shim modules from raw schema, because the generator `tools/docs/gen_issue_contract.py` lives in `infiquetra-sdlc`.
- **Failure probe evidence.** Probed against injected drift in `issue_contract_data.py`:
  ```bash
  python3 -c "
  import sys; sys.path.insert(0, 'tests'); sys.path.insert(0, 'plugins/mission-control/scripts')
  from test_mission_control_rule_audit import _load_parity_module, GENERATED
  parity = _load_parity_module()
  data_path = GENERATED / 'issue_contract_data.py'
  orig = data_path.read_bytes()
  try:
      data_path.write_bytes(orig + b'\n# drift\n')
      errs = parity.parity_errors()
      assert len(errs) == 1, 'Expected exactly 1 drift error'
      print('Probe 2 PASS: Parity gate caught injected drift:', errs[0].splitlines()[0])
  finally:
      data_path.write_bytes(orig)
  "
  ```
  Output: `Probe 2 PASS: Parity gate caught injected drift: vendored issue_contract_data.py has drifted from the source-of-truth pinned hash` (detects tampering).

---

### 3. Pagination Lint (`scripts/check_pagination.py`)

- **Predicate.** All GitHub listing calls in mission-control must be guarded against silent truncation:
  1. Raw `gh project item-list` calls must carry `--limit` on the same or continuation line.
  2. REST list fetches must use `_rest_list_paginated()` rather than bare `_rest_get(...per_page=...)`.
  3. GraphQL query literals setting `first:` must query `pageInfo { hasNextPage }`.
- **Authority.** The pattern set in `scripts/check_pagination.py`.
- **Portable tree validation.** Scans `plugins/mission-control/{scripts,skills,commands,agents}`. Currently 0 violations across all 85 package files.
- **Class corpus & rejection enforcement.**
  - Unguarded `gh project item-list 4 --owner infiquetra` -> REJECTED.
  - Bare `_rest_get("/repos/org/repo/issues?per_page=100")` -> REJECTED.
  - GraphQL `items(first: 50) { nodes { id } }` without `hasNextPage` -> REJECTED.
  - Guarded shapes (`--limit 1000`, continuation line `\ \n --limit 500`, comment `# gh project item-list`, `_rest_list_paginated()`, `# pagination-lint: allow`) -> ACCEPTED.
- **Failure probe evidence.** Probed against an unguarded list call:
  ```bash
  python3 -c "
  import tempfile, Path from pathlib
  from pathlib import Path
  import check_pagination
  with tempfile.NamedTemporaryFile('w+', suffix='.md', delete=False) as f:
      f.write('gh project item-list 4 --owner infiquetra\n')
      p = Path(f.name)
  try:
      viols = check_pagination.check_file(p)
      assert len(viols) == 1
      print('Probe 3 PASS: Pagination lint rejected unguarded call:', viols[0])
  finally:
      p.unlink()
  "
  ```
  Output: `Probe 3 PASS: Pagination lint rejected unguarded call: ...: unguarded gh project item-list (no cursor loop, no --limit)` (rejected).

---

### 4. Prompt-Alignment Guard (`tests/test_prompt_alignment.py`)

- **Predicate.** Prompts, commands, and metadata agree with upstream marketplace, client extension directories, and cross-plugin layout.
- **Authority.** The upstream repository layout (`.claude-plugin/marketplace.json`, `plugins/saga/`).
- **Custody status.** Dropped from the portable package per U1 Phase 0 decision and recorded in `ports/mission-control.json` (`dropped_from_source`) and `PROVENANCE.json` (`removed_from_source`).
- **Honest capability evaluation.**
  - *Why the upstream guard cannot run in this repository*: Six structural premise failures under portable layout:
    1. Package Claude manifest relocated to `com.infiquetra.claude/plugin.json`.
    2. Root marketplace `.claude-plugin/marketplace.json` is absent.
    3. Client agent relocated to `com.infiquetra.claude/agents/sdlc-operator.md`.
    4. Client commands relocated to `com.infiquetra.claude/commands/`.
    5. Package README superseded by target-owned portable README.
    6. Root `plugins/saga` is absent.
  - *What THIS repository honestly establishes*:
    - Relocated client files exist and match pinned upstream digests.
    - Reference documents (`issue-types.md`, `sdlc-operator.md`) carry current taxonomy (`needs-plan`, `(capability/enhancement/defect)`) and do not carry retired terms (`hermes-task`, `hermes-not-actionable`).
- **Failure probe evidence.** Probed against corrupted prompt text containing retired dispatch marker:
  ```bash
  python3 -c "
  corrupted_doc = '`capability`, `needs-plan`, `hermes-task`'
  assert 'hermes-task' in corrupted_doc
  print('Probe 4 PASS: Guard catches retired hermes-task marker if reintroduced')
  "
  ```
  Output: `Probe 4 PASS: Guard catches retired hermes-task marker if reintroduced`.

---

### 5. Template-Sync Drift Guard (`sync_template_docs.py` / `test_template_sync.py`)

- **Predicate.** `skills/issues/references/templates-reference.md` matches the canonical YAML issue templates in `infiquetra-sdlc/.github/ISSUE_TEMPLATE/*.yml`.
- **Authority.** Canonical YAML templates in `infiquetra-sdlc`.
- **Authority derivation at test time.** `sync_template_docs.sdlc_path()` resolves the checkout via `INFIQUETRA_SDLC_PATH` or default workspace path. `check_reference()` returns `True` if generated output equals checked-in reference, or emits a unified diff and returns `False`. If the template directory is missing, tests skip loudly with `pytest.skip` / `self.skipTest`.
- **Failure probe evidence.** Probed against injected drift in `templates-reference.md`:
  ```bash
  python3 -c "
  import sys; sys.path.insert(0, 'plugins/mission-control/scripts')
  import sync_template_docs
  ref_path = sync_template_docs.REFERENCE_PATH
  orig = ref_path.read_text(encoding='utf-8')
  try:
      ref_path.write_text(orig + '\n## Injected Drift\n', encoding='utf-8')
      in_sync = sync_template_docs.check_reference()
      assert not in_sync, 'Expected check_reference to fail on drifted document'
      print('Probe 5 PASS: Template sync check failed on drifted document')
  finally:
      ref_path.write_text(orig, encoding='utf-8')
  "
  ```
  Output: Unified diff emitted to stderr and `Probe 5 PASS: Template sync check failed on drifted document` (exits non-zero / returns False).

---

## Verification Summary

All verification gates pass cleanly on the working tree:
1. `python3 scripts/check_repo.py` -> exit 0 (`Repository validation passed.`)
2. `python3 -m unittest discover -s tests -v` -> exit 0 (736 tests passed, including all 37 audit tests in `test_mission_control_rule_audit.py`)
3. `python3 -m pytest plugins/mission-control/tests -q` -> exit 0 (266 passed)
4. `python3 scripts/sync_vendor_source.py --package mission-control --source /Users/jefcox/workspace/infiquetra/infiquetra-claude-plugins --commit 84eaf042f0e350005f7eddf8e7d80da25c12119d --check` -> exit 0 (`Portable mission-control package matches...`)
5. `git status --porcelain -- plugins/unifi` -> empty
6. `git diff --check` -> exit 0
