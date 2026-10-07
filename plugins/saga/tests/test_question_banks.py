"""Policy questions and question banks for the four lenses (issue 157)."""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"
REFERENCES = REPO_ROOT / "plugins" / "saga" / "references"
BANKS_DIR = REFERENCES / "question-banks"
JEV = REPO_ROOT / "plugins" / "fleet-core" / "scripts" / "jev.py"
JEV_SWEEP_SOURCE = (
    REPO_ROOT / "plugins" / "fleet-core" / "scripts" / "fleet_commons" / "jev_sweep.py"
)


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


QB = _load("question_banks")

#: Names that must never appear in committed bank or policy text. Only names
#: already public in the card and issue may be listed here; anything private
#: is checked at the sittings instead, never committed.
DENY_NAMES: tuple[str, ...] = ("infiquetra-sdlc",)

#: Forbidden stem to the lens-table row whose tool or check answers it. Every
#: stem pins its row, so a stem with no row fails review instead of widening.
TOOL_STEMS: dict[str, str] = {
    "coverage": "testing.uncovered-branch",
    "uncovered": "testing.uncovered-branch",
    "mutat": "testing.surviving-mutant",
    "pass-before": "testing.passes-before-change",
    "passes-before": "testing.passes-before-change",
    "before its fix": "testing.passes-before-change",
    "two-run": "testing.passes-before-change",
    "two test run": "testing.passes-before-change",
    "ci-skip": "testing.ci-skipped",
    "ci skip": "testing.ci-skipped",
    "never collected": "testing.ci-skipped",
    "uncollected": "testing.ci-skipped",
    "not collected": "testing.ci-skipped",
    "random order": "testing.flaky-order-or-network",
    "random-order": "testing.flaky-order-or-network",
    "execution order": "testing.flaky-order-or-network",
    "order-depend": "testing.flaky-order-or-network",
    "network-block": "testing.flaky-order-or-network",
    "network blocked": "testing.flaky-order-or-network",
    "without network": "testing.flaky-order-or-network",
    "no-network": "testing.flaky-order-or-network",
    "socket": "testing.flaky-order-or-network",
    "semgrep": "security.scanner",
    "bandit": "security.scanner",
    "scanner finding": "security.scanner",
    "scanner-finding": "security.scanner",
    "scan result": "security.scanner",
    "secret in the diff": "security.secret-in-diff",
    "secret-in-diff": "security.secret-in-diff",
    "gitleaks": "security.secret-in-diff",
    "hardcoded secret": "security.secret-in-diff",
    "hard-coded secret": "security.secret-in-diff",
    "hardcoded-secret": "security.secret-in-diff",
    "dependenc": "security.dependency",
    "vulnerab": "security.dependency",
    "osv": "security.dependency",
    "cve": "security.dependency",
    "pip-audit": "security.dependency",
    "npm audit": "security.dependency",
    "advisory": "security.dependency",
    "workflow": "security.workflow-infra",
    "actionlint": "security.workflow-infra",
    "zizmor": "security.workflow-infra",
    "checkov": "security.workflow-infra",
    "cdk-nag": "security.workflow-infra",
    "unpinned": "security.workflow-infra",
    "iam polic": "security.workflow-infra",
    "iam-": "security.workflow-infra",
    "wildcard polic": "security.workflow-infra",
    "public storage": "security.workflow-infra",
    "public bucket": "security.workflow-infra",
    "declaration": "security.missing-required-test",
    "proving test": "security.missing-required-test",
    "proving-test": "security.missing-required-test",
    "test exists": "security.missing-required-test",
    "missing test": "security.missing-required-test",
    "required test": "security.missing-required-test",
    "functional-check": "correctness.missing-check",
    "no check asserting": "correctness.missing-check",
    "unmapped": "correctness.missing-check",
    "type error": "correctness.type-error",
    "type-error": "correctness.type-error",
    "typecheck": "correctness.type-error",
    "type-check": "correctness.type-error",
    "mypy": "correctness.type-error",
    "tsc": "correctness.type-error",
    "strict concurrency": "correctness.type-error",
    "cleanup block": "correctness.pattern",
    "cleanup-block": "correctness.pattern",
    "shared cleanup": "correctness.pattern",
    "swallow": "correctness.pattern",
    "silent skip": "correctness.pattern",
    "silent-skip": "correctness.pattern",
    "skipped silently": "correctness.pattern",
    "shared update path": "correctness.pattern",
    "shared-update-path": "correctness.pattern",
    "naive time": "correctness.pattern",
    "naive-time": "correctness.pattern",
    "time comparison": "correctness.pattern",
    "floating-point": "correctness.pattern",
    "floating point": "correctness.pattern",
    "float money": "correctness.pattern",
    "money as float": "correctness.pattern",
    "money-float": "correctness.pattern",
    "changed-name": "correctness.stale-reader",
    "changed name": "correctness.stale-reader",
    "stale": "correctness.stale-reader",
    "unaffected": "correctness.stale-reader",
    "reader left": "correctness.stale-reader",
    "left behind": "correctness.stale-reader",
    "no-exit": "correctness.workflow-no-exit",
    "no exit": "correctness.workflow-no-exit",
    "no way out": "correctness.workflow-no-exit",
    "dead-end state": "correctness.workflow-no-exit",
    "dead end state": "correctness.workflow-no-exit",
    "state graph": "correctness.workflow-no-exit",
    "graph check": "correctness.workflow-no-exit",
    "workflow state": "correctness.workflow-no-exit",
    "ci matrix": "correctness.ci-matrix",
    "ci-matrix": "correctness.ci-matrix",
    "version matrix": "correctness.ci-matrix",
    "matrix build": "correctness.ci-matrix",
    "supported build": "correctness.ci-matrix",
    "build matrix": "correctness.ci-matrix",
    "structural check": "architecture-maintainability.structural-check-fails",
    "check_repo": "architecture-maintainability.structural-check-fails",
    "packaging test": "architecture-maintainability.structural-check-fails",
    "import-linter": "architecture-maintainability.structural-check-fails",
    "import rule": "architecture-maintainability.structural-check-fails",
    "import-rule": "architecture-maintainability.structural-check-fails",
    "relocat": "architecture-maintainability.relocated-run-fails",
    "working director": "architecture-maintainability.relocated-run-fails",
    "home director": "architecture-maintainability.relocated-run-fails",
    "machine-specific": "architecture-maintainability.machine-values",
    "machine specific": "architecture-maintainability.machine-values",
    "absolute path": "architecture-maintainability.machine-values",
    "hardcoded path": "architecture-maintainability.machine-values",
    "hard-coded path": "architecture-maintainability.machine-values",
    "hostname": "architecture-maintainability.machine-values",
    "account id": "architecture-maintainability.machine-values",
    "account-id": "architecture-maintainability.machine-values",
    "duplicat": "architecture-maintainability.duplicate",
    "copy-paste": "architecture-maintainability.duplicate",
    "copy and paste": "architecture-maintainability.duplicate",
    "second copy": "architecture-maintainability.duplicate",
    "jscpd": "architecture-maintainability.duplicate",
    "code clone": "architecture-maintainability.duplicate",
    "complexity": "architecture-maintainability.complexity-dead-code-naming",
    "cyclomatic": "architecture-maintainability.complexity-dead-code-naming",
    "dead code": "architecture-maintainability.complexity-dead-code-naming",
    "dead-code": "architecture-maintainability.complexity-dead-code-naming",
    "unused": "architecture-maintainability.complexity-dead-code-naming",
    "vulture": "architecture-maintainability.complexity-dead-code-naming",
    "naming": "architecture-maintainability.complexity-dead-code-naming",
    "lizard": "architecture-maintainability.complexity-dead-code-naming",
    "knip": "architecture-maintainability.complexity-dead-code-naming",
    "formatter": "build-loop.format",
    "ruff format": "build-loop.format",
    "ruff-format": "build-loop.format",
    "shfmt": "build-loop.format",
    "prettier": "build-loop.format",
    "gofmt": "build-loop.format",
    "shellcheck": "tool.lint",
    "eslint": "tool.lint",
    "clippy": "tool.lint",
    "swiftlint": "tool.lint",
    "dart analyze": "tool.lint",
    "markdownlint": "tool.lint",
    "lint": "tool.lint",
    "spell": "tool.spelling",
    "typo": "tool.spelling",
    "broken link": "tool.links",
    "lychee": "tool.links",
}

#: Outcome row-id prefixes that must never appear in bank or policy text. A
#: sitting-ordered mapping change belongs in its own file, never in content.
ROW_PREFIXES: tuple[str, ...] = (
    "security.scanner",
    "security.secret",
    "security.dependency",
    "security.workflow",
    "security.tool-",
    "correctness.pattern",
    "correctness.type-error",
    "correctness.tool-",
    "testing.uncovered",
    "testing.surviving",
    "testing.flaky",
    "testing.two-",
    "architecture-maintainability.relocated",
    "architecture-maintainability.duplicate",
    "architecture-maintainability.complexity",
    "architecture-maintainability.structural",
    "architecture-maintainability.tool-",
)

#: Folded optional lens to the banks that ask its questions, pinned twice:
#: here and on the loader.
EXPECTED_FOLDED: dict[str, tuple[str, ...]] = {
    "reliability": ("correctness",),
    "api-contract": ("correctness",),
    "performance": ("correctness",),
    "adversarial": ("security",),
    "privacy": ("security",),
    "deployment-infrastructure": ("security", "architecture-maintainability"),
    "documentation-clarity": ("architecture-maintainability",),
    "agent-usability": ("architecture-maintainability",),
}

CORRECTNESS_GROUPS = frozenset(
    {
        "what was asked",
        "shared state and timing",
        "data crossing boundaries",
        "failures and resources",
        "callers and readers",
    }
)
SECURITY_GROUPS = frozenset(
    {
        "who may act on what",
        "outside text treated as instructions",
        "file permissions",
        "secrets",
        "data leaving",
        "what the change brings in",
        "permissions granted",
    }
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("question bank tests must make no network call")

    monkeypatch.setattr(socket, "socket", refuse)


def _tiny_question(lens: str, source: str | None = None) -> dict[str, Any]:
    qid = f"{lens}.{source}.tiny-ask" if source else f"{lens}.tiny-ask"
    question: dict[str, Any] = {
        "id": qid,
        "lens": lens,
        "kind": "yes-no",
        "options": [
            {"id": "yes", "definition": "the tiny condition holds"},
            {"id": "no", "definition": "the tiny condition does not hold"},
        ],
        "examples": ["a tiny example of the condition"],
        "not_for": ["anything else"],
        "piece": "function",
    }
    if source:
        question["when"] = {"languages": ["python"]}
    return question


def _tiny_bank(lens: str, source: str | None = None) -> dict[str, Any]:
    return {
        "schema": QB.BANK_SCHEMA,
        "lens": lens,
        "policy": [],
        "questions": [_tiny_question(lens, source)],
    }


def _tiny_policy() -> dict[str, Any]:
    return {
        "schema": QB.POLICY_SCHEMA,
        "questions": [
            {
                "id": f"{lens}-01",
                "lens": lens,
                "group": "tiny group",
                "question": "the tiny policy question?",
                "fails": "it fails.",
                "clears": "it clears.",
                "proving_test": "the tiny test.",
                "not_for": ["nothing"],
            }
            for lens in QB.LENSES
        ],
    }


def _write_tree(root: Path, banks: dict[str, dict[str, Any]], policy: dict[str, Any]) -> Path:
    target = root / "plugins" / "saga" / "references" / "question-banks"
    target.mkdir(parents=True)
    (target / "policy-questions.json").write_text(
        json.dumps(policy, indent=2), encoding="utf-8"
    )
    for lens, bank in banks.items():
        (target / f"{lens}.json").write_text(json.dumps(bank, indent=2), encoding="utf-8")
    return target


def _read_bank(root: Path, lens: str) -> dict[str, Any]:
    base = root / "plugins" / "saga" / "references" / "question-banks"
    return json.loads((base / f"{lens}.json").read_text(encoding="utf-8"))


def _read_policy(root: Path) -> dict[str, Any]:
    base = root / "plugins" / "saga" / "references" / "question-banks"
    return json.loads((base / "policy-questions.json").read_text(encoding="utf-8"))


def _question_texts(question: Mapping[str, Any]) -> list[str]:
    texts = [str(question["id"])]
    texts += [str(option["id"]) for option in question["options"]]
    texts += [str(option["definition"]) for option in question["options"]]
    texts += [str(item) for item in question.get("examples", [])]
    texts += [str(item) for item in question.get("not_for", [])]
    return texts


def _violations(question: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for text in _question_texts(question):
        lowered = text.lower()
        for stem, row in TOOL_STEMS.items():
            if stem in lowered:
                found.append((stem, row, text))
    return found


def _clean_env(home: Path | None = None) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("TYPESAFE_", "GH_", "GITHUB_", "INFIQUETRA_"))
    }
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if home is not None:
        env["HOME"] = str(home)
        env["INFIQUETRA_TYPESAFE_LOG_DIR"] = str(home)
    return env


def test_load_returns_the_sweep_shape_for_an_approved_bank(tmp_path: Path) -> None:
    bank = _tiny_bank("correctness")
    _write_tree(tmp_path, {"correctness": bank}, _tiny_policy())
    QB.approve("correctness", tmp_path, "2026-10-08")
    loaded = QB.load_bank("correctness", tmp_path)
    assert set(loaded) == {"schema", "questions"}
    assert loaded["schema"] == QB.BANK_SCHEMA
    assert loaded["questions"] == bank["questions"]


def test_approve_then_load_round_trips_on_temporary_copies(tmp_path: Path) -> None:
    _write_tree(tmp_path, {"security": _tiny_bank("security")}, _tiny_policy())
    fingerprint = QB.approve("security", tmp_path, "2026-10-08")
    stored = _read_bank(tmp_path, "security")
    assert stored["approval"] == {"date": "2026-10-08", "fingerprint": fingerprint}
    assert QB.load_bank("security", tmp_path)["questions"] == stored["questions"]


def test_approve_is_stable_byte_for_byte(tmp_path: Path) -> None:
    target = _write_tree(tmp_path, {"testing": _tiny_bank("testing")}, _tiny_policy())
    QB.approve("testing", tmp_path, "2026-10-08")
    first = (target / "testing.json").read_bytes()
    QB.approve("testing", tmp_path, "2026-10-08")
    assert (target / "testing.json").read_bytes() == first


def test_sitting_output_pairs_each_question_with_its_purpose(tmp_path: Path) -> None:
    bank = _tiny_bank("correctness", "reliability")
    bank["questions"].append(_tiny_question("correctness"))
    bank["policy"] = [{"bank": "correctness.tiny-ask", "policy": "correctness-01"}]
    _write_tree(tmp_path, {"correctness": bank}, _tiny_policy())
    document = QB.render_sitting("correctness", tmp_path)
    assert "correctness.reliability.tiny-ask" in document
    assert "folded from reliability" in document
    assert "correctness.tiny-ask" in document
    assert "operationalizes correctness-01" in document


def test_policy_loads_only_when_all_four_banks_approve(tmp_path: Path) -> None:
    banks = {lens: _tiny_bank(lens) for lens in QB.LENSES}
    policy = _tiny_policy()
    target = _write_tree(tmp_path, banks, policy)
    for lens in QB.LENSES:
        QB.approve(lens, tmp_path, "2026-10-08")
    assert QB.load_policy(tmp_path)["questions"] == policy["questions"]
    security = _read_bank(tmp_path, "security")
    del security["approval"]
    (target / "security.json").write_text(json.dumps(security, indent=2), encoding="utf-8")
    with pytest.raises(QB.BankRefusal):
        QB.load_policy(tmp_path)
    QB.approve("security", tmp_path, "2026-10-08")
    assert QB.load_policy(tmp_path)["questions"] == policy["questions"]
    changed = _read_policy(tmp_path)
    changed["questions"][0]["fails"] = "it fails differently."
    (target / "policy-questions.json").write_text(
        json.dumps(changed, indent=2), encoding="utf-8"
    )
    with pytest.raises(QB.BankRefusal):
        QB.load_policy(tmp_path)


def test_loader_folded_fallback_names_the_six_code_languages() -> None:
    assert QB.FOLDED_FALLBACK_LANGUAGES == (
        "python",
        "typescript",
        "dart",
        "rust",
        "swift",
        "shell",
    )


def test_loader_constants_match_c6_and_the_formula() -> None:
    import review_formula

    tree = ast.parse(JEV_SWEEP_SOURCE.read_text(encoding="utf-8"))
    sweep: dict[str, Any] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in {
                "BANK_SCHEMA",
                "QUESTION_KEYS",
                "LENSES",
                "LANGUAGES",
                "PIECE_KINDS",
            }:
                sweep[target.id] = ast.literal_eval(node.value)
    assert QB.BANK_SCHEMA == sweep["BANK_SCHEMA"]
    assert set(QB.QUESTION_KEYS) == set(sweep["QUESTION_KEYS"])
    assert QB.PIECE_KINDS == tuple(sweep["PIECE_KINDS"])
    assert QB.LENSES == tuple(sweep["LENSES"]) == tuple(review_formula.LENSES)
    assert QB.LANGUAGES == tuple(sweep["LANGUAGES"]) == tuple(review_formula.LANGUAGES)


def test_load_refuses_a_bank_whose_question_changed(tmp_path: Path) -> None:
    target = _write_tree(tmp_path, {"correctness": _tiny_bank("correctness")}, _tiny_policy())
    QB.approve("correctness", tmp_path, "2026-10-08")
    bank = _read_bank(tmp_path, "correctness")
    bank["questions"][0]["options"][0]["definition"] = "the tiny condition changed"
    (target / "correctness.json").write_text(json.dumps(bank, indent=2), encoding="utf-8")
    with pytest.raises(QB.BankRefusal):
        QB.load_bank("correctness", tmp_path)
    completed = subprocess.run(
        [sys.executable, str(SCRIPTS / "question_banks.py"), "load", "--lens", "correctness",
         "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        env=_clean_env(),
        timeout=60,
        cwd=REPO_ROOT,
    )
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "refused" in completed.stderr


def test_load_refuses_a_bank_with_no_approval(tmp_path: Path) -> None:
    _write_tree(tmp_path, {"security": _tiny_bank("security")}, _tiny_policy())
    with pytest.raises(QB.BankRefusal, match="no approval"):
        QB.load_bank("security", tmp_path)


def test_load_refuses_a_changed_policy_entry(tmp_path: Path) -> None:
    target = _write_tree(tmp_path, {"testing": _tiny_bank("testing")}, _tiny_policy())
    QB.approve("testing", tmp_path, "2026-10-08")
    policy = _read_policy(tmp_path)
    entry = next(item for item in policy["questions"] if item["lens"] == "testing")
    entry["fails"] = "it fails differently."
    (target / "policy-questions.json").write_text(
        json.dumps(policy, indent=2), encoding="utf-8"
    )
    with pytest.raises(QB.BankRefusal, match="differs from approval"):
        QB.load_bank("testing", tmp_path)


def test_load_refuses_a_question_with_an_unexpected_key(tmp_path: Path) -> None:
    bank = _tiny_bank("correctness")
    bank["questions"][0]["ninth"] = "the sweep would reject this key"
    problems = QB.validate_bank(bank, "correctness", _tiny_policy())
    assert any("unexpected keys" in problem for problem in problems)
    _write_tree(tmp_path, {"correctness": bank}, _tiny_policy())
    with pytest.raises(QB.BankRefusal):
        QB.load_bank("correctness", tmp_path)


def test_load_refuses_a_folded_id_with_an_unknown_source(tmp_path: Path) -> None:
    bank = _tiny_bank("correctness")
    bank["questions"][0]["id"] = "correctness.bogus-lens.tiny-ask"
    assert QB.validate_bank(bank, "correctness", _tiny_policy())
    other = _tiny_bank("testing")
    other["questions"][0]["id"] = "testing.reliability.tiny-ask"
    other["questions"][0]["lens"] = "testing"
    assert QB.validate_bank(other, "testing", _tiny_policy())
    _write_tree(tmp_path, {"correctness": bank}, _tiny_policy())
    with pytest.raises(QB.BankRefusal):
        QB.load_bank("correctness", tmp_path)


def test_load_refuses_a_policy_link_to_an_unknown_id(tmp_path: Path) -> None:
    bank = _tiny_bank("security")
    bank["policy"] = [{"bank": "security.tiny-ask", "policy": "security-99"}]
    assert QB.validate_bank(bank, "security", _tiny_policy())
    bank["policy"] = [{"bank": "security.tiny-ask", "policy": "correctness-01"}]
    assert QB.validate_bank(bank, "security", _tiny_policy())
    _write_tree(tmp_path, {"security": bank}, _tiny_policy())
    with pytest.raises(QB.BankRefusal):
        QB.load_bank("security", tmp_path)


def test_load_refuses_an_empty_condition_list(tmp_path: Path) -> None:
    plain = _tiny_bank("correctness")
    plain["questions"][0]["when"] = {"languages": []}
    assert QB.validate_bank(plain, "correctness", _tiny_policy())
    folded = _tiny_bank("security", "privacy")
    folded["questions"][0]["when"] = {"paths": []}
    assert QB.validate_bank(folded, "security", _tiny_policy())
    _write_tree(tmp_path, {"correctness": plain}, _tiny_policy())
    with pytest.raises(QB.BankRefusal):
        QB.load_bank("correctness", tmp_path)


def test_loader_help_exits_zero_without_credentials() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPTS / "question_banks.py"), "--help"],
        capture_output=True,
        text=True,
        env=_clean_env(),
        timeout=60,
        cwd=SCRIPTS.parent,
    )
    assert completed.returncode == 0
    assert "usage:" in (completed.stdout + completed.stderr).lower()
    assert "ModuleNotFoundError" not in completed.stderr
    assert "Traceback" not in completed.stderr


def test_loader_entrypoint_discovery_covers_the_new_script() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "plugins/saga/tests/test_entrypoints.py",
         "-q", "--import-mode=importlib", "-k", "question_banks", "-p", "no:cacheprovider"],
        capture_output=True,
        text=True,
        env=_clean_env(),
        timeout=300,
        cwd=REPO_ROOT,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_policy_list_holds_thirty_questions() -> None:
    entries = _read_policy(REPO_ROOT)["questions"]
    assert len(entries) == 30
    by_lens = [entry["lens"] for entry in entries]
    assert by_lens.count("correctness") == 15
    assert by_lens.count("security") == 7
    assert by_lens.count("testing") + by_lens.count("architecture-maintainability") == 8
    assert by_lens.count("testing") >= 1
    assert by_lens.count("architecture-maintainability") >= 1


def test_policy_entries_name_lens_fails_clears_and_proving_test() -> None:
    for entry in _read_policy(REPO_ROOT)["questions"]:
        assert set(entry) == set(QB.POLICY_KEYS), entry.get("id")
        for field in ("id", "lens", "group", "question", "fails", "clears", "proving_test"):
            assert isinstance(entry[field], str) and entry[field].strip(), (entry["id"], field)
        assert isinstance(entry["not_for"], list) and entry["not_for"]
        assert all(isinstance(line, str) and line.strip() for line in entry["not_for"])


def test_policy_ids_are_unique_and_lens_prefixed() -> None:
    ids = [entry["id"] for entry in _read_policy(REPO_ROOT)["questions"]]
    assert len(set(ids)) == len(ids)
    for entry in _read_policy(REPO_ROOT)["questions"]:
        assert entry["id"].startswith(f"{entry['lens']}-"), entry["id"]


def test_policy_questions_validate_through_the_loader() -> None:
    assert QB.validate_policy(_read_policy(REPO_ROOT)) == []


def test_policy_text_has_no_denied_name() -> None:
    blob = json.dumps(_read_policy(REPO_ROOT), ensure_ascii=False).lower()
    for name in DENY_NAMES:
        assert name.lower() not in blob, name


def test_policy_groups_match_the_design_plans_named_sets() -> None:
    entries = _read_policy(REPO_ROOT)["questions"]
    assert {e["group"] for e in entries if e["lens"] == "correctness"} == CORRECTNESS_GROUPS
    assert {e["group"] for e in entries if e["lens"] == "security"} == SECURITY_GROUPS


def test_bank_counts_hold_ten_to_twenty_per_lens() -> None:
    for lens in QB.LENSES:
        count = len(_read_bank(REPO_ROOT, lens)["questions"])
        assert 10 <= count <= 20, (lens, count)


def test_bank_ids_are_unique_across_all_four_banks() -> None:
    ids = [
        question["id"]
        for lens in QB.LENSES
        for question in _read_bank(REPO_ROOT, lens)["questions"]
    ]
    assert len(set(ids)) == len(ids)


def test_bank_questions_carry_options_examples_and_not_for() -> None:
    for lens in QB.LENSES:
        for question in _read_bank(REPO_ROOT, lens)["questions"]:
            options = question["options"]
            assert isinstance(options, list) and options, question["id"]
            assert all(
                isinstance(option["id"], str) and option["id"].strip()
                and isinstance(option["definition"], str) and option["definition"].strip()
                for option in options
            ), question["id"]
            assert len({option["id"] for option in options}) == len(options), question["id"]
            if question["kind"] == "yes-no":
                assert [option["id"] for option in options][:2] == ["yes", "no"], question["id"]
            else:
                assert question["kind"] == "choice"
                assert len(options) >= 2, question["id"]
            assert isinstance(question["examples"], list) and question["examples"], question["id"]
            assert all(isinstance(item, str) and item.strip() for item in question["examples"])
            assert isinstance(question["not_for"], list) and question["not_for"], question["id"]
            assert all(isinstance(item, str) and item.strip() for item in question["not_for"])


def test_bank_firing_option_definition_states_the_condition() -> None:
    for lens in QB.LENSES:
        for question in _read_bank(REPO_ROOT, lens)["questions"]:
            definitions = [option["definition"] for option in question["options"]]
            assert definitions[0].strip(), question["id"]
            assert all(other != definitions[0] for other in definitions[1:]), question["id"]


def test_folded_questions_name_source_and_condition() -> None:
    assert set(QB.FOLDED_SOURCES) == set(EXPECTED_FOLDED)
    for source, lenses in EXPECTED_FOLDED.items():
        assert tuple(QB.FOLDED_SOURCES[source]) == tuple(lenses)
    seen: dict[str, set[str]] = {lens: set() for lens in QB.LENSES}
    for lens in QB.LENSES:
        for question in _read_bank(REPO_ROOT, lens)["questions"]:
            qid = question["id"]
            rest = qid[len(lens) + 1 :].split(".")
            if len(rest) != 2:
                continue
            source = rest[0]
            assert source in EXPECTED_FOLDED, qid
            assert lens in EXPECTED_FOLDED[source], qid
            when = question.get("when") or {}
            assert when, qid
            if "languages" in when:
                assert when["languages"], qid
            if "paths" in when:
                assert when["paths"], qid
            seen[lens].add(source)
    for source, lenses in EXPECTED_FOLDED.items():
        for lens in lenses:
            assert source in seen[lens], (source, lens)


def test_bank_lens_matches_every_question_lens() -> None:
    for lens in QB.LENSES:
        bank = _read_bank(REPO_ROOT, lens)
        assert bank["lens"] == lens
        for question in bank["questions"]:
            assert question["lens"] == lens, question["id"]


def test_bank_policy_links_resolve_to_the_same_lens() -> None:
    policy_ids = {
        entry["id"] for entry in _read_policy(REPO_ROOT)["questions"]
    }
    lens_ids = {
        lens: {
            entry["id"]
            for entry in _read_policy(REPO_ROOT)["questions"]
            if entry["lens"] == lens
        }
        for lens in QB.LENSES
    }
    for lens in QB.LENSES:
        bank = _read_bank(REPO_ROOT, lens)
        ids = {question["id"] for question in bank["questions"]}
        assert isinstance(bank.get("policy", []), list), lens
        for link in bank.get("policy", []):
            assert link["bank"] in ids, link
            assert link["policy"] in policy_ids, link
            assert link["policy"] in lens_ids[lens], link


def test_sweep_parser_accepts_each_bank(tmp_path: Path) -> None:
    rate = {
        "uncached_input": 0,
        "cache_read": 0,
        "cache_write_5m": 0,
        "cache_write_1h": 0,
        "output": 0,
    }
    pieces = tmp_path / "pieces.json"
    pieces.write_text("[]", encoding="utf-8")
    thresholds = tmp_path / "thresholds.json"
    thresholds.write_text("{}", encoding="utf-8")
    rate_path = tmp_path / "rate.json"
    rate_path.write_text(json.dumps(rate), encoding="utf-8")
    for lens in QB.LENSES:
        completed = subprocess.run(
            [sys.executable, str(JEV), "sweep",
             "--bank", str(BANKS_DIR / f"{lens}.json"),
             "--pieces", str(pieces), "--thresholds", str(thresholds),
             "--rate", str(rate_path)],
            capture_output=True,
            text=True,
            env=_clean_env(tmp_path),
            timeout=120,
            cwd=REPO_ROOT,
        )
        assert completed.returncode == 0, (lens, completed.stdout, completed.stderr)
        document = json.loads(completed.stdout)
        assert document["failed"] is False, lens
        assert document["items"] == [], lens
        assert document["degraded"] == [], lens


def test_tool_answered_inputs_are_never_asked() -> None:
    assert all(row for row in TOOL_STEMS.values())
    for lens in QB.LENSES:
        for question in _read_bank(REPO_ROOT, lens)["questions"]:
            hits = _violations(question)
            assert not hits, (question["id"], [(stem, row) for stem, row, _ in hits])


def test_tool_answered_stems_catch_planted_violations() -> None:
    planted: dict[str, Any] = {
        "id": "testing.coverage-trap",
        "lens": "testing",
        "kind": "yes-no",
        "options": [
            {"id": "mutat-trap", "definition": "the scanner finding trap"},
            {"id": "no", "definition": "no trap here"},
        ],
        "examples": ["a stale trap"],
        "not_for": ["the duplicated trap"],
        "piece": "function",
    }
    stems = {stem for stem, _, _ in _violations(planted)}
    assert {"coverage", "mutat", "scanner finding", "stale", "duplicat"} <= stems
    clean = copy.deepcopy(planted)
    clean["id"] = "testing.clean-ask"
    clean["options"] = [
        {"id": "yes", "definition": "the tiny condition holds"},
        {"id": "no", "definition": "the tiny condition does not hold"},
    ]
    clean["examples"] = ["a tiny example"]
    clean["not_for"] = ["anything else"]
    assert _violations(clean) == []


def test_bank_text_has_no_denied_name() -> None:
    for lens in QB.LENSES:
        blob = json.dumps(_read_bank(REPO_ROOT, lens), ensure_ascii=False).lower()
        for name in DENY_NAMES:
            assert name.lower() not in blob, (lens, name)


def test_folded_deployment_infrastructure_sits_in_two_banks() -> None:
    for lens in ("security", "architecture-maintainability"):
        folded = [
            question
            for question in _read_bank(REPO_ROOT, lens)["questions"]
            if question["id"].split(".")[1:-1] == ["deployment-infrastructure"]
        ]
        assert folded, lens
        assert any(
            any(
                keyword in pattern
                for pattern in question.get("when", {}).get("paths", [])
                for keyword in ("workflows", "Dockerfile", "docker-compose", ".tf", "cdk", "migrat")
            )
            for question in folded
        ), lens


def test_bank_files_validate_through_the_loader() -> None:
    policy = _read_policy(REPO_ROOT)
    for lens in QB.LENSES:
        assert QB.validate_bank(_read_bank(REPO_ROOT, lens), lens, policy) == [], lens


def test_shipped_banks_obey_the_approval_rule() -> None:
    policy = _read_policy(REPO_ROOT)
    for lens in QB.LENSES:
        bank = _read_bank(REPO_ROOT, lens)
        try:
            loaded = QB.load_bank(lens, REPO_ROOT)
        except QB.BankRefusal:
            assert "approval" not in bank, f"{lens}: refused yet carries an approval"
        else:
            assert loaded["questions"] == bank["questions"], lens
            stamp = bank["approval"]["date"]
            assert re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", stamp), lens
            date.fromisoformat(stamp)
    try:
        loaded_policy = QB.load_policy(REPO_ROOT)
    except QB.BankRefusal:
        for lens in QB.LENSES:
            bank = _read_bank(REPO_ROOT, lens)
            if "approval" in bank:
                entries = [e for e in policy["questions"] if e["lens"] == lens]
                content = {k: v for k, v in bank.items() if k != "approval"}
                assert bank["approval"]["fingerprint"] == QB.fingerprint_of(content, entries), (
                    f"{lens}: approval drifted"
                )
    else:
        assert loaded_policy["questions"] == policy["questions"]


def test_post_approval_edit_refuses_that_lens(tmp_path: Path) -> None:
    target = tmp_path / "plugins" / "saga" / "references"
    shutil.copytree(REFERENCES, target, dirs_exist_ok=True)
    for lens in QB.LENSES:
        QB.approve(lens, tmp_path, "2026-10-08")
    assert QB.load_bank("security", tmp_path)["questions"]
    bank = _read_bank(tmp_path, "correctness")
    bank["questions"][0]["examples"] = ["a changed example"]
    (target / "question-banks" / "correctness.json").write_text(
        json.dumps(bank, indent=2), encoding="utf-8"
    )
    with pytest.raises(QB.BankRefusal, match="differs from approval"):
        QB.load_bank("correctness", tmp_path)
    assert QB.load_bank("security", tmp_path)["questions"]


def test_rendered_material_covers_every_question() -> None:
    policy = _read_policy(REPO_ROOT)
    for lens in QB.LENSES:
        document = QB.render_sitting(lens, REPO_ROOT)
        for question in _read_bank(REPO_ROOT, lens)["questions"]:
            assert document.count(f"### {question['id']}\n") == 1, question["id"]
        for entry in policy["questions"]:
            if entry["lens"] == lens:
                assert document.count(f"### {entry['id']}") == 1, entry["id"]


def test_sitting_driven_mapping_edits_stay_in_their_own_files() -> None:
    blob = json.dumps(_read_policy(REPO_ROOT), ensure_ascii=False)
    for lens in QB.LENSES:
        blob += json.dumps(_read_bank(REPO_ROOT, lens), ensure_ascii=False)
    for prefix in ROW_PREFIXES:
        assert prefix not in blob, prefix


def test_question_bank_components_name_the_six_paths() -> None:
    assert QB.QUESTION_BANK_COMPONENTS == (
        "plugins/saga/scripts/question_banks.py",
        "plugins/saga/references/question-banks/policy-questions.json",
        "plugins/saga/references/question-banks/architecture-maintainability.json",
        "plugins/saga/references/question-banks/correctness.json",
        "plugins/saga/references/question-banks/security.json",
        "plugins/saga/references/question-banks/testing.json",
    )
    for relative in QB.QUESTION_BANK_COMPONENTS:
        assert (REPO_ROOT / relative).is_file(), relative


def test_earlier_fingerprint_tuples_are_unchanged() -> None:
    tools = _load("review_tools")
    assert tools.FINGERPRINT_COMPONENTS[:5] == (
        "plugins/saga/scripts/review_tools.py",
        "plugins/saga/scripts/review_diff.py",
        "plugins/saga/scripts/coverage_lines.py",
        "plugins/saga/scripts/review_adapters_all_languages.py",
        "plugins/saga/references/review-tools.yaml",
    )
    pieces = _load("sweep_pieces")
    assert pieces.SWEEP_COMPONENTS == (
        "plugins/fleet-core/scripts/fleet_commons/jev_sweep.py",
        "plugins/saga/scripts/sweep_pieces.py",
        "plugins/saga/references/model-prices.yaml",
    )
