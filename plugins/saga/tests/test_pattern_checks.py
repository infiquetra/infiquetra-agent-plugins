"""Saga's own pattern checks: Semgrep rules for the six recurring defects (issue 154).

Four parts, one per unit that extends this file: the Semgrep pin (U1), the rule
files and their rule tests (U2), the adapter and runner wiring (U3), and the
setup question, docs, and fingerprint (U4).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"
REFERENCES = REPO_ROOT / "plugins" / "saga" / "references"
RULES = REFERENCES / "semgrep"
FIXTURES = REPO_ROOT / "plugins" / "saga" / "tests" / "fixtures" / "review_tools"

sys.path.insert(0, str(SCRIPTS))

import review_adapters_all_languages  # noqa: E402
import review_calibration  # noqa: E402
import review_formula  # noqa: E402
import review_records  # noqa: E402
import review_tools  # noqa: E402
import saga_setup  # noqa: E402

#: The six defects, in the card-table order: file stem, C1 row, harm, languages.
RULE_TABLE: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "release-shares-cleanup-block",
        "correctness.pattern.release-shares-cleanup",
        "two-holders-of-one-exclusive-thing",
        ("python", "typescript"),
    ),
    (
        "swallowed-error",
        "correctness.pattern.swallowed-error",
        "wrong-result-reported-as-success",
        ("python", "typescript"),
    ),
    (
        "silent-skip",
        "correctness.pattern.silent-skip",
        "wrong-result-reported-as-success",
        ("python", "typescript"),
    ),
    (
        "write-skips-shared-update-path",
        "correctness.pattern.write-skips-shared-update",
        "data-lost-or-corrupted",
        ("python", "typescript"),
    ),
    (
        "naive-time-comparison",
        "correctness.pattern.naive-time-comparison",
        "wrong-result-reported-as-success",
        ("python",),
    ),
    (
        "money-as-floating-point",
        "correctness.pattern.money-as-float",
        "money-or-resources-wrongly-moved",
        ("python", "typescript"),
    ),
)
DEFECTS = {
    "release-shares-cleanup-block": "A release sharing a cleanup block",
    "swallowed-error": "A swallowed error",
    "silent-skip": "A silent skip",
    "write-skips-shared-update-path": "A write that skips the shared update path",
    "naive-time-comparison": "A naive time comparison",
    "money-as-floating-point": "Money stored as floating point",
}
OUTCOME = "blocks unless the builder records a reason"
_TARGET_SUFFIX = {"python": "py", "typescript": "ts"}


@pytest.fixture(autouse=True)
def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """No part of this file may touch the network. A call fails the test."""

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise OSError("network blocked")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)

_PIN_RE = re.compile(r"semgrep==([0-9][0-9A-Za-z.]*)")


def _requirements_pin() -> str | None:
    pins = []
    text = (REPO_ROOT / "requirements-plugin-tests.txt").read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _PIN_RE.search(stripped)
        if match:
            pins.append(match.group(1))
    assert len(pins) <= 1, f"semgrep pinned twice in requirements-plugin-tests.txt: {pins}"
    return pins[0] if pins else None


def _workflow_pin() -> str | None:
    text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    pins = _PIN_RE.findall(text)
    assert len(pins) <= 1, f"semgrep pinned twice in ci.yml: {pins}"
    return pins[0] if pins else None


def _tool_list_pin() -> str:
    rows = {row["id"]: row for row in review_tools.load_tool_list()}
    saga = rows["semgrep-saga"]["default_version"]
    security = rows["semgrep-security"]["default_version"]
    assert saga == security, f"the two semgrep rows disagree: saga {saga}, security {security}"
    return str(saga)


def test_semgrep_pin_matches_the_tool_list() -> None:
    """U1: one Semgrep version in the tool list and in exactly one install site."""
    pin = _tool_list_pin()
    assert pin != "not-recorded", "the semgrep rows still carry no pin"
    sites = {
        "requirements-plugin-tests.txt": _requirements_pin(),
        ".github/workflows/ci.yml": _workflow_pin(),
    }
    found = {name: version for name, version in sites.items() if version is not None}
    assert len(found) == 1, f"the semgrep pin must live in exactly one install site: {found}"
    site, installed = next(iter(found.items()))
    assert installed == pin, f"{site} pins semgrep {installed}, the tool list pins {pin}"


def _load_rule(stem: str) -> dict[str, Any]:
    document = yaml.safe_load((RULES / f"{stem}.yaml").read_text(encoding="utf-8"))
    entries = document["rules"]
    assert len(entries) == 1, f"{stem}.yaml must hold exactly one rule"
    return entries[0]


def test_rule_files_carry_identity_message_languages_and_metadata() -> None:
    """U2: every rule file parses and names its id, languages, harm, and outcome."""
    assert sorted(path.name for path in RULES.glob("*.yaml")) == sorted(
        f"{stem}.yaml" for stem, _, _, _ in RULE_TABLE
    )
    for stem, row, harm, languages in RULE_TABLE:
        rule = _load_rule(stem)
        assert rule["id"] == f"saga.{stem}", stem
        assert "\n" not in rule["message"], f"{stem}: the message must be one line"
        assert rule["languages"] == list(languages), stem
        metadata = rule["metadata"]
        assert metadata["lens"] == "correctness", stem
        assert metadata["defect"] == DEFECTS[stem], stem
        assert metadata["harm"] == harm, stem
        assert metadata["outcome"] == OUTCOME, stem
        assert metadata["row"] == row, stem


def test_each_rule_language_has_a_marked_test_file() -> None:
    """U2: every table language has a paired target with ruleid: and ok: lines."""
    for stem, _, _, languages in RULE_TABLE:
        for language in languages:
            target = RULES / f"{stem}.{_TARGET_SUFFIX[language]}"
            assert target.is_file(), f"missing rule-test target: {target.name}"
            text = target.read_text(encoding="utf-8")
            assert re.search(rf"ruleid:\s*saga\.{stem}\b", text), f"{target.name} needs a ruleid: line"
            assert re.search(rf"\bok:\s*saga\.{stem}\b", text), f"{target.name} needs an ok: line"


def test_rule_metadata_stays_in_step_with_the_formula() -> None:
    """U2: each cited row blocks in the formula, excused by a pattern-check reason."""
    for stem, row, _, _ in RULE_TABLE:
        assert _load_rule(stem)["metadata"]["row"] == row
        assert review_formula.ROWS[row].outcome == "blocks", row
        assert review_formula.ROWS[row].excused_by == "pattern-check", row


def _semgrep_or_skip() -> str:
    binary = shutil.which("semgrep")
    if binary is None:
        pytest.skip("semgrep is not installed")
    pin = _tool_list_pin()
    probe = subprocess.run(
        [binary, "--version"], capture_output=True, text=True, timeout=60
    )
    found = review_tools._VERSION.search(f"{probe.stdout}\n{probe.stderr}")
    version = found.group(0) if found else "unknown"
    if version != pin:
        pytest.skip(f"found semgrep {version}, want the pinned {pin}")
    return binary


def test_semgrep_rule_tests_pass_without_network() -> None:
    """U2: semgrep --test passes over the rules folder, proving every rule ran."""
    binary = _semgrep_or_skip()
    env = {**os.environ, "SEMGREP_ENABLE_VERSION_CHECK": "0"}
    proc = subprocess.run(
        [binary, "--test", "--metrics=off", str(RULES)],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
        cwd=REPO_ROOT,
    )
    combined = f"{proc.stdout}\n{proc.stderr}"
    assert proc.returncode == 0, combined
    assert "No unit tests found" not in combined
    match = re.search(r"^(\d+)/(\d+):", combined, re.M)
    assert match is not None, f"no passing count in semgrep --test output:\n{combined}"
    passed, total = match.group(1), match.group(2)
    assert passed == total == str(len(RULE_TABLE)), combined


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return proc.stdout.strip()


def _init(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "pattern-checks@example.com")
    _git(repo, "config", "user.name", "pattern-checks")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _changed_lines_repo(tmp: Path, changed: set[int]) -> tuple[Path, str, str]:
    """A repo whose ``src/app.py`` changed exactly ``changed`` (1-based)."""
    repo = tmp / "repo"
    _init(repo)
    (repo / "src").mkdir()
    base_lines = [f"line{n}\n" for n in range(1, 11)]
    (repo / "src" / "app.py").write_text("".join(base_lines), encoding="utf-8")
    base = _commit(repo, "base")
    head_lines = [
        line.upper() if number in changed else line
        for number, line in enumerate(base_lines, start=1)
    ]
    (repo / "src" / "app.py").write_text("".join(head_lines), encoding="utf-8")
    head = _commit(repo, "head")
    return repo, base, head


class _Calls:
    """A process runner that answers version probes and scans from canned bytes."""

    def __init__(self, version: str, payload: str) -> None:
        self.version = version
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        argv: list[str] | str,
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: int,
        shell: bool,
    ) -> Any:
        assert shell is False
        assert isinstance(argv, list)
        self.calls.append({"argv": list(argv), "cwd": Path(cwd), "env": dict(env)})
        if "--version" in argv:
            return review_tools.ProcessResult(0, self.version)
        return review_tools.ProcessResult(0, self.payload)


def _saga_adapter() -> Any:
    return next(
        item for item in review_adapters_all_languages.ADAPTERS if item.id == "semgrep-saga"
    )


def _run_saga(
    tmp: Path,
    payload: str,
    profile_data: dict[str, Any],
    changed: set[int],
    builder: dict[str, Any] | None = None,
    runner: _Calls | None = None,
) -> tuple[int, Path]:
    repo, base, head = _changed_lines_repo(tmp, changed)
    profile = tmp / "profile.json"
    profile.write_text(json.dumps(profile_data), encoding="utf-8")
    builder_path = None
    if builder is not None:
        builder_path = tmp / "builder.json"
        builder_path.write_text(json.dumps(builder), encoding="utf-8")
    home = tmp / "home"
    home.mkdir(parents=True, exist_ok=True)
    output = tmp / "out"
    if runner is None:
        runner = _Calls(f"semgrep {_tool_list_pin()}\n", payload)
    code = review_tools.run(
        repo,
        base,
        head,
        profile,
        output,
        home=home,
        builder=builder_path,
        adapters=[_saga_adapter()],
        runner=runner,
        framework=False,
    )
    return code, output


def _read(output: Path, name: str) -> Any:
    return json.loads((output / name).read_text(encoding="utf-8"))


def _payload() -> str:
    return (FIXTURES / "semgrep-pattern-checks.json").read_text(encoding="utf-8")


def _profile_with_key() -> dict[str, Any]:
    return {
        "schema": "repository_profile.v1",
        "review": {
            "shared_update_paths": {
                "python": ["example_shared_write"],
                "typescript": ["illustrative_update_path"],
            }
        },
    }


def test_recorded_output_becomes_validated_correctness_findings(tmp_path: Path) -> None:
    """U3: each rule's recorded hit becomes a validated finding that blocks."""
    code, output = _run_saga(tmp_path, _payload(), _profile_with_key(), {4, 5, 6, 7, 8, 9})
    assert code == 0
    findings = _read(output, "findings.json")
    assert len(findings) == len(RULE_TABLE)
    pin = _tool_list_pin()
    for stem, row, harm, _ in RULE_TABLE:
        matching = [item for item in findings if item["rule"]["ref"] == f"saga.{stem}"]
        assert len(matching) == 1, f"saga.{stem} produced {len(matching)} findings"
        finding = matching[0]
        assert finding["lens"] == "correctness"
        assert finding["rule"]["row"] == row
        assert finding["consequence"] == harm
        assert finding["language"] == "python"
        assert finding["source"]["version"] == pin
        assert "severity" not in finding
        assert review_records.validate(finding) == []
    severities = {item["severity"] for item in _read(output, "outcomes.json")["findings"]}
    assert severities == {"blocks"}
    assert _read(output, "degraded.json") == []


def test_builder_reason_excuses_one_pattern_finding(tmp_path: Path) -> None:
    """U3: a pattern-check reason against the finding's identity drops it to a note."""
    code, output = _run_saga(tmp_path, _payload(), _profile_with_key(), {4, 5, 6, 7, 8, 9})
    assert code == 0
    excused = _read(output, "findings.json")[0]["id"]

    def builder_for(finding_id: str) -> dict[str, Any]:
        return {
            "kind": "builder_record",
            "schema": "review_records.v1",
            "unit": "U3",
            "acceptance_criteria": [],
            "declarations": [],
            "reasons": [
                {
                    "kind": "pattern-check",
                    "finding_id": finding_id,
                    "text": "a false match on this line",
                }
            ],
        }

    code, output = _run_saga(
        tmp_path / "excused", _payload(), _profile_with_key(), {4, 5, 6, 7, 8, 9},
        builder=builder_for(excused),
    )
    assert code == 0
    severities = {
        item["id"]: item["severity"] for item in _read(output, "outcomes.json")["findings"]
    }
    assert severities[excused] == "note"
    assert set(severities.values()) == {"blocks", "note"}

    other = excused[:-1] + ("0" if excused[-1] != "0" else "1")
    code, output = _run_saga(
        tmp_path / "unmatched", _payload(), _profile_with_key(), {4, 5, 6, 7, 8, 9},
        builder=builder_for(other),
    )
    assert code == 0
    severities = {item["severity"] for item in _read(output, "outcomes.json")["findings"]}
    assert severities == {"blocks"}


def test_match_outside_the_change_yields_nothing(tmp_path: Path) -> None:
    """U3: recorded hits on unchanged lines are dropped by the changed-line filter."""
    code, output = _run_saga(tmp_path, _payload(), _profile_with_key(), {1})
    assert code == 0
    assert _read(output, "findings.json") == []


def test_missing_key_records_a_degraded_input(tmp_path: Path) -> None:
    """U3: without the key the run degrades and the other rules still report."""
    code, output = _run_saga(
        tmp_path, _payload(), {"schema": "repository_profile.v1"}, {4, 5, 6, 7, 8, 9}
    )
    assert code == 0
    degraded = _read(output, "degraded.json")
    assert {
        "lens": "correctness",
        "language": "none",
        "input": "correctness.pattern.write-skips-shared-update",
        "tool": "semgrep",
        "reason": "missing-shared-update-paths",
    } in degraded
    # The stubbed scan returns canned bytes however the rule rendered; the live
    # test below proves the never-matching render reports nothing for real.
    assert len(_read(output, "findings.json")) == len(RULE_TABLE)


def test_head_key_change_keeps_the_base_value_and_notes_it(tmp_path: Path) -> None:
    """U3: a head-only key is recorded, never applied; the base run degrades."""
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("".join(f"line{n}\n" for n in range(1, 11)))
    (repo / ".saga-profile.json").write_text(json.dumps({"schema": "repository_profile.v1"}))
    base = _commit(repo, "base")
    (repo / "src" / "app.py").write_text("".join(
        line.upper() if number in {4, 5, 6, 7, 8, 9} else line
        for number, line in enumerate(
            "".join(f"line{n}\n" for n in range(1, 11)).splitlines(keepends=True), start=1
        )
    ))
    (repo / ".saga-profile.json").write_text(json.dumps(_profile_with_key()))
    head = _commit(repo, "head")
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    output = tmp_path / "out"
    runner = _Calls(f"semgrep {_tool_list_pin()}\n", _payload())
    code = review_tools.run(
        repo,
        base,
        head,
        repo / ".saga-profile.json",
        output,
        home=home,
        adapters=[_saga_adapter()],
        runner=runner,
        framework=False,
    )
    assert code == 0
    reasons = {(item["input"], item["reason"]) for item in _read(output, "degraded.json")}
    assert ("correctness.pattern.write-skips-shared-update", "missing-shared-update-paths") in reasons
    assert ("head-profile", "head-profile-change") in reasons


def _rendered_rule(target: Path) -> dict[str, Any]:
    document = yaml.safe_load(
        (target / "write-skips-shared-update-path.yaml").read_text(encoding="utf-8")
    )
    assert len(document["rules"]) == 1
    return document["rules"][0]


def _rendered_slot(target: Path) -> str:
    slots = review_tools._shared_update_slots(_rendered_rule(target))
    assert len(slots) == 1
    return str(slots[0]["regex"])


def test_render_fills_profile_names_and_nothing_else(tmp_path: Path) -> None:
    """U3: usable names become one sorted, escaped alternation; siblings copy over."""
    target = tmp_path / "rendered"
    target.mkdir()
    review = {"shared_update_paths": {"python": ["board.write", "a"], "typescript": []}}
    notes = review_tools._render_saga_rules(_saga_adapter(), RULES, review, target)
    assert notes == ()
    assert sorted(path.name for path in target.iterdir()) == sorted(
        f"{stem}.yaml" for stem, _, _, _ in RULE_TABLE
    )
    assert _rendered_slot(target) == r"(?:a|board\.write)"
    for stem, _, _, _ in RULE_TABLE:
        if stem == "write-skips-shared-update-path":
            continue
        assert (target / f"{stem}.yaml").read_bytes() == (RULES / f"{stem}.yaml").read_bytes()


def test_render_degrades_without_a_usable_key(tmp_path: Path) -> None:
    """U3: a missing, empty, or hostile key renders the never-match plus one note."""
    expected = {
        "lens": "correctness",
        "language": "none",
        "input": "correctness.pattern.write-skips-shared-update",
        "tool": "semgrep",
        "reason": "missing-shared-update-paths",
    }
    unusable = [
        None,
        {},
        {"shared_update_paths": None},
        {"shared_update_paths": []},
        {"shared_update_paths": {}},
        {"shared_update_paths": {"python": []}},
        {"shared_update_paths": {"python": "board.write"}},
        {"shared_update_paths": {"python": [None]}},
        {"shared_update_paths": {"python": [""]}},
        {"shared_update_paths": {"python": ["has space"]}},
        {"shared_update_paths": {"python": ["line\nbreak"]}},
        {"shared_update_paths": {"python": ['quote"break']}},
        {"shared_update_paths": {"python": ["dash-name"]}},
        {"shared_update_paths": {"python": ["ok_name", "bad name"]}},
        "not-a-mapping",
    ]
    for index, review in enumerate(unusable):
        target = tmp_path / f"rendered-{index}"
        target.mkdir()
        notes = review_tools._render_saga_rules(_saga_adapter(), RULES, review, target)
        assert tuple(notes) == (expected,), review
        assert _rendered_rule(target)["patterns"] == [{"pattern-regex": "(?!)"}], review
        assert sorted(path.name for path in target.iterdir()) == sorted(
            f"{stem}.yaml" for stem, _, _, _ in RULE_TABLE
        )


def test_render_without_the_shared_update_file_degrades(tmp_path: Path) -> None:
    """U3: a plugin copy without the template still scans the rest, degraded."""
    shipped = tmp_path / "shipped"
    shipped.mkdir()
    (shipped / "rule.yml").write_text("rules: []\n", encoding="utf-8")
    target = tmp_path / "rendered"
    target.mkdir()
    notes = review_tools._render_saga_rules(_saga_adapter(), shipped, None, target)
    assert [note["reason"] for note in notes] == ["missing-shared-update-paths"]
    assert (target / "rule.yml").read_text(encoding="utf-8") == "rules: []\n"


def test_render_refuses_a_corrupt_shared_update_rule(tmp_path: Path) -> None:
    """U3: a template with the wrong row or no name slot refuses the run."""
    shipped = tmp_path / "shipped"
    shipped.mkdir()
    (shipped / "write-skips-shared-update-path.yaml").write_text(
        yaml.safe_dump({"rules": [{"metadata": {"row": "correctness.type-error"}}]}),
        encoding="utf-8",
    )
    target = tmp_path / "rendered"
    target.mkdir()
    with pytest.raises(review_tools.RunnerFailure) as caught:
        review_tools._render_saga_rules(_saga_adapter(), shipped, None, target)
    assert caught.value.code == 2
    (shipped / "write-skips-shared-update-path.yaml").write_text(
        yaml.safe_dump({
            "rules": [{
                "metadata": {"row": "correctness.pattern.write-skips-shared-update"},
                "patterns": [{"pattern-regex": "x"}],
            }]
        }),
        encoding="utf-8",
    )
    with pytest.raises(review_tools.RunnerFailure) as caught:
        review_tools._render_saga_rules(_saga_adapter(), shipped, None, target)
    assert caught.value.code == 2


def test_render_constants_stay_in_step_with_the_shipped_rule() -> None:
    """U3: the runner's file, row, and slot agree with the template on disk."""
    assert (RULES / review_tools._SHARED_UPDATE_FILE).is_file()
    document = yaml.safe_load(
        (RULES / review_tools._SHARED_UPDATE_FILE).read_text(encoding="utf-8")
    )
    assert document["rules"][0]["metadata"]["row"] == review_tools._SHARED_UPDATE_ROW
    assert review_tools._SHARED_UPDATE_ROW in review_formula.ROWS


def test_saga_parser_recovers_bare_rule_ids() -> None:
    """U3: prefixed check ids reduce to saga.<stem>; bare ids pass through."""
    adapter = _saga_adapter()
    parsed = adapter.parse(json.dumps({"results": [
        {
            "check_id": "saga-rules-xyz.saga.swallowed-error",
            "path": "src/app.py",
            "start": {"line": 4},
            "end": {"line": 4},
            "extra": {
                "message": "An error is swallowed instead of handled.",
                "metadata": {
                    "row": "correctness.pattern.swallowed-error",
                    "harm": "wrong-result-reported-as-success",
                },
            },
        },
        {
            "check_id": "saga.silent-skip",
            "path": "src/app.py",
            "start": {"line": 5},
            "end": {"line": 5},
            "extra": {
                "message": "An item is skipped without a trace.",
                "metadata": {
                    "row": "correctness.pattern.silent-skip",
                    "harm": "wrong-result-reported-as-success",
                },
            },
        },
    ]}))
    assert [(hit.rule_id, hit.anchor) for hit in parsed.hits] == [
        ("saga.swallowed-error", "saga.swallowed-error"),
        ("saga.silent-skip", "saga.silent-skip"),
    ]
    security = next(
        item for item in review_adapters_all_languages.ADAPTERS if item.id == "semgrep-security"
    )
    parsed = security.parse(json.dumps({"results": [
        {
            "check_id": "cache Pack.python.flask.security.xss",
            "path": "src/app.py",
            "start": {"line": 4},
            "end": {"line": 4},
            "extra": {
                "severity": "ERROR",
                "message": "A finding.",
                "metadata": {},
            },
        },
    ]}))
    assert parsed.hits[0].rule_id == "cache Pack.python.flask.security.xss"
    assert parsed.hits[0].consequence is None


def test_profile_rule_override_passes_through_unrendered(tmp_path: Path) -> None:
    """U3: a profile that replaces the saga rules gets no render and no notes."""
    custom = tmp_path / "custom"
    custom.mkdir()
    (custom / "custom.yml").write_text("rules: []\n", encoding="utf-8")
    adapter = _saga_adapter()
    rules = (review_tools.RulePin(pack=None, sha256=None, path=str(custom)),)
    with review_tools._rule_config(
        adapter, rules, tmp_path, tmp_path / "home", "0" * 40, None
    ) as (configs, problem, notes):
        assert configs == (custom,)
        assert problem is None
        assert notes == ()


def test_saga_scan_stays_off_the_network(tmp_path: Path, monkeypatch: Any) -> None:
    """The saga scan disables the version check by flag and by environment."""
    monkeypatch.setenv("SEMGREP_ENABLE_VERSION_CHECK", "1")
    runner = _Calls(f"semgrep {_tool_list_pin()}\n", _payload())
    code, _output = _run_saga(
        tmp_path, _payload(), _profile_with_key(), {4, 5, 6, 7, 8, 9}, runner=runner
    )
    assert code == 0
    scans = [call for call in runner.calls if "scan" in call["argv"]]
    assert len(scans) == 1
    assert "--disable-version-check" in scans[0]["argv"]
    assert scans[0]["env"]["SEMGREP_ENABLE_VERSION_CHECK"] == "0"


def test_rendered_config_scans_cleanly_live(tmp_path: Path) -> None:
    """U3: the rendered config scans for real, excluding only the named paths."""
    binary = _semgrep_or_skip()
    sample = tmp_path / "sample.py"
    sample.write_text(
        'direct = "updateProjectV2ItemFieldValue"\n'
        'sample_shared_write("updateProjectV2ItemFieldValue")\n'
        "try:\n"
        "    work()\n"
        "except ValueError:\n"
        "    pass\n",
        encoding="utf-8",
    )
    adapter = _saga_adapter()

    def scan(review: object) -> Any:
        target = tmp_path / f"rendered-{len(list(tmp_path.glob('rendered-*')))}"
        target.mkdir()
        notes = review_tools._render_saga_rules(adapter, RULES, review, target)
        env = {**os.environ, "SEMGREP_ENABLE_VERSION_CHECK": "0"}
        proc = subprocess.run(
            [binary, "scan", "--metrics=off", "--disable-nosem", "--disable-version-check",
             "--json", "--config", str(target), str(sample)],
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
            cwd=tmp_path,
        )
        assert proc.returncode == 0, proc.stderr
        return notes, adapter.parse(proc.stdout)

    notes, parsed = scan({"shared_update_paths": {"python": ["sample_shared_write"]}})
    assert notes == ()
    assert parsed.problems == ()
    assert sorted((hit.rule_id, hit.start) for hit in parsed.hits) == [
        ("saga.swallowed-error", 5),
        ("saga.write-skips-shared-update-path", 1),
    ]
    notes, parsed = scan(None)
    assert [note["reason"] for note in notes] == ["missing-shared-update-paths"]
    assert parsed.problems == ()
    assert [(hit.rule_id, hit.start) for hit in parsed.hits] == [
        ("saga.swallowed-error", 5),
    ]


_SETTLED_PROFILE = {
    "schema": "repository_profile.v1",
    "functional_test_environment": {
        "kind": "local",
        "test_command": "python3 -m pytest tests -q",
        "scope": "private",
    },
    "qa": {
        "schema": "qa_profile.v1",
        "strategies": {"example": {"required": True}},
        "ceiling": {"max_duration_seconds": 60, "max_direct_cost": 0},
    },
    "visibility": "private",
    "other_key": "kept",
}
_REVIEW_PROMPT = (
    "Which functions, methods, or module paths are this repository's shared "
    'update paths, per language? Answer with an object like {"shared_update_paths": '
    '{"python": [...]}}; omit languages with none.'
)


def test_shared_update_question_is_registered() -> None:
    """U4: the setup registry asks for the shared update paths under review."""
    extensions = saga_setup.load_extensions()
    questions = [item for item in extensions["questions"] if item.get("key") == "review"]
    assert len(questions) == 1
    assert questions[0]["profile_key"] == "review"
    assert questions[0]["prompt"] == _REVIEW_PROMPT


def test_setup_asks_and_stores_the_shared_update_paths(tmp_path: Path) -> None:
    """U4: setup asks without the key, stays quiet with it, and keeps other keys."""
    extensions = saga_setup.load_extensions()
    asked = saga_setup.questions_for({}, dict(_SETTLED_PROFILE), extensions)
    assert [item for item in asked if item["key"] == "review"] == [
        {"key": "review", "prompt": _REVIEW_PROMPT}
    ]
    settled = dict(_SETTLED_PROFILE)
    settled["review"] = {"shared_update_paths": {"python": ["board.write"]}}
    assert all(item["key"] != "review" for item in saga_setup.questions_for({}, settled, extensions))

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("value = 1\n", encoding="utf-8")
    (repo / ".saga-profile.json").write_text(json.dumps(_SETTLED_PROFILE), encoding="utf-8")

    def runner(argv: object, **kwargs: object) -> Any:
        del argv, kwargs
        raise FileNotFoundError("no tools in this fixture")

    answer = {"shared_update_paths": {"python": ["board.write"], "typescript": []}}
    saga_setup.write_profile(repo, {"review": answer}, runner=runner, env={})
    profile = json.loads((repo / ".saga-profile.json").read_text(encoding="utf-8"))
    assert profile["review"] == answer
    assert profile["other_key"] == "kept"


def _rules_fence() -> list[dict[str, Any]]:
    guide = (REFERENCES / "review-tools.md").read_text(encoding="utf-8")
    fences = [chunk.split("```", 1)[0] for chunk in guide.split("```yaml")[1:]]
    matching = [yaml.safe_load(fence) for fence in fences if "saga_pattern_rules" in fence]
    assert len(matching) == 1
    return matching[0]["saga_pattern_rules"]


def test_review_tools_lists_the_six_rules() -> None:
    """U4: the doc's rule fence matches every rule file's harm, outcome, languages."""
    entries = {entry["file"]: entry for entry in _rules_fence()}
    assert sorted(entries) == sorted(f"{stem}.yaml" for stem, _, _, _ in RULE_TABLE)
    for stem, _, harm, languages in RULE_TABLE:
        rule = _load_rule(stem)
        entry = entries[f"{stem}.yaml"]
        assert entry["harm"] == rule["metadata"]["harm"] == harm
        assert entry["outcome"] == rule["metadata"]["outcome"] == OUTCOME
        assert entry["languages"] == rule["languages"] == list(languages)


def test_repository_profile_documents_the_key() -> None:
    """U4: the profile doc names the shared-update-path key and its shape."""
    profile = (REFERENCES / "repository-profile.md").read_text(encoding="utf-8")
    assert "shared_update_paths" in profile
    assert "identifier-shaped" in profile


def test_rule_files_join_the_fingerprint() -> None:
    """U4: all six rule files are fingerprinted calibration components."""
    for stem, _, _, _ in RULE_TABLE:
        assert f"plugins/saga/references/semgrep/{stem}.yaml" in review_calibration.COMPONENTS
