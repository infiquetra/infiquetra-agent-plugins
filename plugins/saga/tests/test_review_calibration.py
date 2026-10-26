"""The calibration file: marks, verdicts, and the may-block answer (issue 149).

Sockets are refused for the whole module. A network call fails the test.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import socket
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPTS = REPO / "plugins" / "saga" / "scripts"
REFERENCES = REPO / "plugins" / "saga" / "references"
COMMITTED = REFERENCES / "review-calibration.json"
PLAN = REPO / "docs" / "brainstorms" / "2026-10-05-saga-review-redesign" / "plan.md"
PROMPT = "plugins/saga/references/targeted-reviewer-prompt.md"

sys.path.insert(0, str(SCRIPTS))

import review_calibration as calibration  # noqa: E402
import review_formula  # noqa: E402

COUNTS = (
    "held_out_blocked",
    "held_out_defects",
    "held_out_false_blocks",
    "held_out_clean",
    "repeat_flips",
    "repeat_cases",
)
NULL_FIELDS = (
    "corpus_version",
    "jev_model_version",
    "cost_usd",
    "langfuse_run_id",
    "reviewer_configuration",
)


@pytest.fixture(autouse=True)
def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """U1 and U3 share this file. Both refuse the network."""

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise OSError("network blocked")

    if hasattr(socket.socket, "connect"):
        # The suite-wide guard in conftest replaces socket.socket outright,
        # which refuses creation before connect is reached. Patch the method
        # only when the class is still the real one.
        monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _committed() -> dict[str, Any]:
    return json.loads(COMMITTED.read_text(encoding="utf-8"))


def _overall(**overrides: object) -> dict[str, object]:
    counts: dict[str, object] = {name: 0 for name in COUNTS}
    counts.update(
        held_out_defects=10,
        held_out_clean=10,
        repeat_cases=10,
    )
    counts.update(overrides)
    return counts


def _language(verdict: str, **overrides: object) -> dict[str, object]:
    return {"verdict": verdict, **_overall(**overrides)}


def _write(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _problems(data: dict[str, Any], tmp_path: Path) -> list[str]:
    path = _write(tmp_path / "review-calibration.json", data)
    return calibration.problems_in(path)


def _copy_components(root: Path) -> None:
    for relative in calibration.COMPONENTS:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((REPO / relative).read_bytes())


def _fingerprint(root: Path) -> dict[str, str]:
    return calibration.fingerprint(root)


def _recorded(
    root: Path,
    *,
    drift: str = "as-recorded",
    languages: dict[str, dict[str, object]] | None = None,
    numbers: dict[str, object] | None = None,
) -> Path:
    """A recorded document whose fingerprint matches the components under ``root``."""
    _copy_components(root)
    counts = numbers if numbers is not None else _overall(held_out_blocked=1)
    per_language = languages
    if per_language is None:
        per_language = {"python": _language("cleared", **counts)}
    data = _committed()
    data["corpus_run"] = "recorded"
    data["fingerprint"] = _fingerprint(root)
    for lens in data["lenses"].values():
        lens["drift"] = drift
        lens["overall"] = dict(counts)
        lens["languages"] = {name: dict(value) for name, value in per_language.items()}
    return _write(root / calibration.CALIBRATION_RELATIVE, data)


def _invoke(
    root: Path,
    lens: str = "security",
    language: str = "python",
    *,
    file: Path | None = None,
) -> tuple[int, str, str]:
    argv = ["may-block", "--lens", lens, "--language", language, "--root", str(root)]
    if file is not None:
        argv.extend(["--file", str(file)])
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = calibration.main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


def _answer(root: Path, lens: str = "security", language: str = "python") -> str:
    return calibration.may_block(
        lens,
        language,
        root=root,
        calibration=root / calibration.CALIBRATION_RELATIVE,
    )


def test_committed_file_is_no_run() -> None:
    data = _committed()
    assert data["schema"] == "review_calibration.v1"
    assert data["corpus_run"] == "no-run"
    assert data["fingerprint"] == {}
    assert data["thresholds"] == []
    for name in NULL_FIELDS:
        assert data[name] is None
    assert set(data["lenses"]) == set(review_formula.LENSES)
    for lens in review_formula.LENSES:
        assert data["lenses"][lens] == {"drift": "report-only", "languages": {}}
    assert calibration.document_problems(data) == []


def test_thresholds_read_back(tmp_path: Path) -> None:
    assert calibration.thresholds() == []
    data = _committed()
    data["thresholds"] = [
        {"question": "security.secret-in-diff", "threshold": 0.8, "piece_size": 40}
    ]
    path = _write(tmp_path / "review-calibration.json", data)
    assert calibration.thresholds(path) == [
        {"question": "security.secret-in-diff", "threshold": 0.8, "piece_size": 40}
    ]


def _fraction(cell: str) -> dict[str, int]:
    match = re.search(r"(\d+) in (\d+)", cell)
    assert match is not None, cell
    return {"numerator": int(match.group(1)), "denominator": int(match.group(2))}


def _plan_marks(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    header = next(index for index, line in enumerate(lines) if "Must block, of known blocking defects" in line)
    lenses: dict[str, dict[str, dict[str, int]]] = {}
    for line in lines[header + 1:]:
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells or set(cells[0]) <= set("-: "):
            continue
        name = cells[0]
        lens = "architecture-maintainability" if name == "Architecture and maintainability" else name.lower()
        lenses[lens] = {"must_block": _fraction(cells[1]), "may_block_clean": _fraction(cells[2])}
    guard_line = next(
        line for line in lines if "fewer than 7 of 10" in line and "more than 2 of 10" in line
    )
    fewer = re.search(r"fewer than (\d+) of (\d+)", guard_line)
    more = re.search(r"more than (\d+) of (\d+)", guard_line)
    assert fewer is not None and more is not None
    repeat = text.split("**Repeat runs**", 1)[1].split("**The calibration file**", 1)[0]
    flip = re.search(r"more than (\d+) in (\d+)", repeat)
    assert flip is not None
    how = text.split("### How we'll know it works", 1)[1].split("### Where the plan stands", 1)[0]
    assert "the same grade every time" in how
    return {
        "lenses": lenses,
        "language_guard": {
            "must_catch": {"numerator": int(fewer.group(1)), "denominator": int(fewer.group(2))},
            "may_block_clean": {"numerator": int(more.group(1)), "denominator": int(more.group(2))},
        },
        "repeat_run": {
            "may_flip": {"numerator": int(flip.group(1)), "denominator": int(flip.group(2))}
        },
        "deterministic": "identical",
    }


def test_stored_marks_equal_plan() -> None:
    parsed = _plan_marks(PLAN.read_text(encoding="utf-8"))
    # The plan's table predates the 2026-10-25 operator decision (option A): architecture
    # plants are flagged, not blocked. Same fraction, so only the key changes.
    architecture = parsed["lenses"]["architecture-maintainability"]
    architecture["must_flag"] = architecture.pop("must_block")
    assert calibration.MARKS == parsed
    assert _committed()["marks"] == parsed


def test_architecture_mark_is_flagged_not_blocked() -> None:
    lenses = calibration.MARKS["lenses"]
    architecture = lenses["architecture-maintainability"]
    assert "must_block" not in architecture
    assert architecture["must_flag"] == {"numerator": 6, "denominator": 10}
    assert architecture["may_block_clean"] == {"numerator": 1, "denominator": 20}
    for lens in ("correctness", "security", "testing"):
        assert "must_block" in lenses[lens]
        assert "must_flag" not in lenses[lens]


def test_marks_with_architecture_must_block_are_refused() -> None:
    data = _committed()
    architecture = data["marks"]["lenses"]["architecture-maintainability"]
    architecture["must_block"] = architecture.pop("must_flag")
    assert "not an identifier: marks" in calibration.document_problems(data)


def test_lens_mark_refuses_an_unknown_catch_kind() -> None:
    with pytest.raises(ValueError, match="unknown catch kind: must_note"):
        calibration._lens_mark((6, 10), (1, 20), "must_note")


def test_format_refuses_an_unknown_key_and_free_text(tmp_path: Path) -> None:
    extra = _committed()
    extra["comment"] = "hello"
    assert any("comment" in item for item in _problems(extra, tmp_path))

    spaced = _committed()
    spaced["langfuse_run_id"] = "a sentence with spaces"
    assert any("langfuse_run_id" in item for item in _problems(spaced, tmp_path / "id"))

    maybe = _committed()
    maybe["corpus_run"] = "maybe"
    assert _problems(maybe, tmp_path / "run")

    recorded = _committed()
    recorded["corpus_run"] = "recorded"
    for row in recorded["lenses"].values():
        row["drift"] = "as-recorded"
        row["overall"] = _overall()
        row["languages"] = {"python": _language("looks good")}
    assert _problems(recorded, tmp_path / "verdict")

    unknown = _committed()
    unknown["lenses"]["taste"] = {"drift": "report-only", "languages": {}}
    assert _problems(unknown, tmp_path / "lens")

    counted = _committed()
    counted["corpus_run"] = "recorded"
    for row in counted["lenses"].values():
        row["drift"] = "as-recorded"
        row["overall"] = _overall(held_out_blocked="9")
        row["languages"] = {}
    assert _problems(counted, tmp_path / "count")


def test_a_recorded_lens_may_omit_a_language(tmp_path: Path) -> None:
    data = _committed()
    data["corpus_run"] = "recorded"
    for row in data["lenses"].values():
        row["drift"] = "as-recorded"
        row["overall"] = _overall()
        row["languages"] = {"typescript": _language("cleared")}
    assert _problems(data, tmp_path) == []


def test_components_match_the_landed_cards() -> None:
    import question_banks
    import review_tools
    import sweep_pieces

    assert calibration.COMPONENTS == (
        "plugins/saga/scripts/review_formula.py",
        "plugins/saga/references/review-records.schema.json",
        *review_tools.FINGERPRINT_COMPONENTS,
        "plugins/saga/references/targeted-reviewer-prompt.md",
        "plugins/saga/references/targeted-reviewer-answer.schema.json",
        "plugins/saga/references/targeted-reviewer-launch.json",
        *sweep_pieces.SWEEP_COMPONENTS,
        "plugins/saga/references/semgrep/release-shares-cleanup-block.yaml",
        "plugins/saga/references/semgrep/swallowed-error.yaml",
        "plugins/saga/references/semgrep/silent-skip.yaml",
        "plugins/saga/references/semgrep/write-skips-shared-update-path.yaml",
        "plugins/saga/references/semgrep/naive-time-comparison.yaml",
        "plugins/saga/references/semgrep/money-as-floating-point.yaml",
        "plugins/saga/scripts/review_command.py",
        "plugins/saga/scripts/review_dependencies.py",
        *question_banks.QUESTION_BANK_COMPONENTS,
        "plugins/saga/scripts/review_checks.py",
    )


def test_no_run_answers_every_lens() -> None:
    for lens in review_formula.LENSES:
        assert calibration.may_block(lens, "python", root=REPO) == "report-only no-run"
        assert calibration.may_block(lens, "none", root=REPO) == "report-only no-run"
    code, stdout, stderr = _invoke(REPO)
    assert code == 0
    assert stderr == ""
    assert stdout == "report-only no-run\n"


def test_no_run_command_loads_no_yaml(tmp_path: Path) -> None:
    pinned = tmp_path / "pinned"
    _write(pinned / calibration.CALIBRATION_RELATIVE, _committed())
    _write(
        pinned / ".saga-profile.json",
        {"review_tools": {"pins": {"semgrep": {"version": "9.9.9"}}}},
    )
    script = """
import sys
from pathlib import Path
live = Path(sys.argv[1])
pinned = Path(sys.argv[2])
sys.path.insert(0, str(live / "plugins" / "saga" / "scripts"))
import review_calibration
pinned_file = pinned / "plugins" / "saga" / "references" / "review-calibration.json"
assert review_calibration.may_block("security", "python", root=live) == "report-only no-run"
assert review_calibration.may_block(
    "security", "python", root=pinned, calibration=pinned_file
) == "report-only no-run"
assert "yaml" not in sys.modules
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(REPO), str(pinned)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_cleared_verdict_answers_yes(tmp_path: Path) -> None:
    root = tmp_path / "cleared"
    _recorded(root, numbers=_overall(held_out_blocked=1, held_out_false_blocks=0))
    assert _answer(root) == "yes cleared"


def test_report_only_verdict_beside_clearing_numbers(tmp_path: Path) -> None:
    root = tmp_path / "report"
    numbers = _overall(held_out_blocked=10, held_out_false_blocks=0)
    _recorded(root, numbers=numbers, languages={"python": _language("report-only", **numbers)})
    assert _answer(root) == "report-only verdict"


def test_drift_report_only_covers_every_language(tmp_path: Path) -> None:
    root = tmp_path / "drift"
    numbers = _overall(held_out_blocked=10, held_out_false_blocks=0)
    _recorded(
        root,
        drift="report-only",
        numbers=numbers,
        languages={
            "python": _language("cleared", **numbers),
            "typescript": _language("cleared", **numbers),
        },
    )
    assert _answer(root, language="python") == "report-only drift"
    assert _answer(root, language="typescript") == "report-only drift"


def test_no_verdict_for_a_missing_language(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    _recorded(root, languages={"typescript": _language("cleared")})
    assert _answer(root) == "report-only no-verdict"


def test_stale_fingerprint_names_the_component(tmp_path: Path) -> None:
    root = tmp_path / "stale"
    _recorded(root)
    prompt = root / PROMPT
    prompt.write_bytes(prompt.read_bytes() + b"\n")
    assert _answer(root) == f"report-only stale-fingerprint {PROMPT}"


def test_stale_fingerprint_ignores_claude_md(tmp_path: Path) -> None:
    root = tmp_path / "instructions"
    _recorded(root)
    instructions = root / "CLAUDE.md"
    instructions.write_text("first\n", encoding="utf-8")
    assert calibration.check(root) == []
    instructions.write_text("changed\n", encoding="utf-8")
    assert calibration.check(root) == []
    assert "CLAUDE.md" not in calibration.COMPONENTS


TARGETED_REVIEWER_COMPONENTS = (
    "plugins/saga/references/targeted-reviewer-prompt.md",
    "plugins/saga/references/targeted-reviewer-answer.schema.json",
    "plugins/saga/references/targeted-reviewer-launch.json",
)
INSTRUCTION_FILES = ("CLAUDE.md", "AGENTS.md", "GEMINI.md")
PLUGIN_MANIFESTS = (
    "plugins/saga/plugin.json",
    "plugins/saga/fleet-bundle.json",
    "plugins/saga/.claude-plugin/plugin.json",
    "plugins/saga/.codex-plugin/plugin.json",
    "plugins/saga/com.infiquetra.claude/plugin.json",
)


def test_calibration_fingerprints_targeted_reviewer_components(tmp_path: Path) -> None:
    """Issue 158 U6: the prompt, schema and launch settings are part of the review."""
    for relative in TARGETED_REVIEWER_COMPONENTS:
        assert relative in calibration.COMPONENTS
    root = tmp_path / "targeted"
    _recorded(root)
    assert calibration.check(root) == []
    for relative in TARGETED_REVIEWER_COMPONENTS:
        component = root / relative
        original = component.read_bytes()
        component.write_bytes(original + b" ")
        assert calibration.check(root) == [f"changed component: {relative}"]
        assert _answer(root) == f"report-only stale-fingerprint {relative}"
        component.write_bytes(original)
        assert calibration.check(root) == []


def test_calibration_ignores_instruction_file_changes(tmp_path: Path) -> None:
    """Issue 158 U6: the configuration fingerprint stays off the component list."""
    for relative in calibration.COMPONENTS:
        assert Path(relative).name not in INSTRUCTION_FILES
        assert relative not in PLUGIN_MANIFESTS
        assert not relative.startswith("plugins/agent-launcher/")
    root = tmp_path / "instructions"
    _recorded(root)
    changed = [*INSTRUCTION_FILES[:2], *PLUGIN_MANIFESTS]
    for relative in changed:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        source = REPO / relative
        target.write_bytes(source.read_bytes() if source.is_file() else b"# instructions\n")
    assert calibration.check(root) == []
    assert _answer(root) == "yes cleared"
    for relative in changed:
        target = root / relative
        target.write_bytes(target.read_bytes() + b"\nchanged\n")
    assert calibration.check(root) == []
    assert _answer(root) == "yes cleared"


def _profile(root: Path, pins: dict[str, Any]) -> None:
    _write(root / ".saga-profile.json", {"review_tools": {"pins": pins}})


def _security_rules(root: Path) -> list[dict[str, Any]]:
    import review_tools

    tools = review_tools.load_tool_list(root / calibration.TOOL_LIST_RELATIVE)
    row = next(item for item in tools if item.get("id") == "semgrep-security")
    return [
        {key: value for key, value in rule.items() if key in {"pack", "path", "sha256"}}
        for rule in row["rules"]
    ]


def _semgrep_default(root: Path) -> str:
    import review_tools

    tools = review_tools.load_tool_list(root / calibration.TOOL_LIST_RELATIVE)
    row = next(item for item in tools if item.get("id") == "semgrep-security")
    return str(row["default_version"])


def test_pinned_tool_off_default_reports_only(tmp_path: Path) -> None:
    root = tmp_path / "pins"
    _recorded(root)
    _profile(root, {"semgrep": {"version": "9.9.9"}})
    assert _answer(root, lens="security") == "report-only pinned-tool semgrep"
    assert _answer(root, lens="correctness") == "report-only pinned-tool semgrep"
    assert _answer(root, lens="architecture-maintainability") == "yes cleared"

    equal = tmp_path / "equal"
    _recorded(equal)
    _profile(equal, {"semgrep": {"version": _semgrep_default(equal)}})
    assert _answer(equal, lens="security") == "yes cleared"
    assert _answer(equal, lens="correctness") == "yes cleared"

    copied = tmp_path / "copied"
    _recorded(copied)
    _profile(copied, {"semgrep": {"rules": _security_rules(copied)}})
    assert _answer(copied, lens="security") == "yes cleared"

    changed = tmp_path / "changed"
    _recorded(changed)
    rules = _security_rules(changed)
    rules[0]["sha256"] = "0" * 64
    _profile(changed, {"semgrep": {"rules": rules}})
    assert _answer(changed, lens="security") == "report-only pinned-tool semgrep"


def test_pinned_tool_refuses_a_malformed_profile(tmp_path: Path) -> None:
    profiles = [
        "{",
        "[]",
        json.dumps({"review_tools": []}),
        json.dumps({"review_tools": {"pins": []}}),
        json.dumps({"review_tools": {"pins": {"semgrep": {"version": 1}}}}),
        json.dumps({"review_tools": {"pins": {"not-a-tool": {"version": "1"}}}}),
        json.dumps({"review_tools": {"pins": {"semgrep": {"rules": ["nope"]}}}}),
    ]
    for index, text in enumerate(profiles):
        root = tmp_path / f"bad-{index}"
        _recorded(root)
        (root / ".saga-profile.json").write_text(text, encoding="utf-8")
        code, stdout, stderr = _invoke(root, file=root / calibration.CALIBRATION_RELATIVE)
        assert code == 2, (text, code, stdout, stderr)
        assert stdout == ""
        assert "yes" not in stdout
        assert stderr.strip()


def test_pinned_tool_reads_the_root_tool_list(tmp_path: Path) -> None:
    root = tmp_path / "root-list"
    _recorded(root)
    listing = root / calibration.TOOL_LIST_RELATIVE
    listing.write_text(
        re.sub(
            r'default_version: "[^"]*"',
            'default_version: "from-root"',
            listing.read_text(encoding="utf-8"),
        ),
        encoding="utf-8",
    )
    document = json.loads((root / calibration.CALIBRATION_RELATIVE).read_text(encoding="utf-8"))
    document["fingerprint"] = _fingerprint(root)
    _write(root / calibration.CALIBRATION_RELATIVE, document)
    _profile(root, {"semgrep": {"version": "from-root"}})
    assert _answer(root, lens="security") == "yes cleared"


def test_absent_profile_on_a_cleared_tree_answers_yes(tmp_path: Path) -> None:
    root = tmp_path / "no-profile"
    _recorded(root)
    assert not (root / ".saga-profile.json").exists()
    assert _answer(root) == "yes cleared"


def test_unknown_lens_or_language_exits_2(tmp_path: Path) -> None:
    root = tmp_path / "unknown"
    _recorded(root)
    for argv_lens, argv_language in (("taste", "python"), ("security", "cobol")):
        code, stdout, stderr = _invoke(root, lens=argv_lens, language=argv_language)
        assert code == 2
        assert stdout == ""
        assert "yes" not in stdout
        assert stderr.strip()


_RECORD_INSTALLED = """
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

script = Path(sys.argv[1])
sys.path.insert(0, str(script.parent))
spec = importlib.util.spec_from_file_location("installed_review_calibration", script)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
path = module.default_calibration_path()
data = json.loads(path.read_text(encoding="utf-8"))
data["corpus_run"] = "recorded"
counts = {
    "held_out_blocked": 1,
    "held_out_defects": 10,
    "held_out_false_blocks": 0,
    "held_out_clean": 10,
    "repeat_flips": 0,
    "repeat_cases": 10,
}
for row in data["lenses"].values():
    row["drift"] = "as-recorded"
    row["overall"] = dict(counts)
    row["languages"] = {"python": {"verdict": "cleared", **counts}}
fingerprint = {}
for relative in module.COMPONENTS:
    file = module.locate(module.package_dir(), relative)
    if not file.is_file():
        raise SystemExit(f"missing {relative} at {file}")
    fingerprint[relative] = hashlib.sha256(file.read_bytes()).hexdigest()
data["fingerprint"] = fingerprint
path.write_text(json.dumps(data), encoding="utf-8")
"""


def test_an_installed_copy_answers_from_the_package(tmp_path: Path) -> None:
    """A marketplace copy is the saga directory, not a repository checkout."""
    install = tmp_path / "cache" / "saga" / "1.0.0"
    shutil.copytree(
        REPO / "plugins" / "saga",
        install,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    script = install / "scripts" / "review_calibration.py"
    # The sweep's fleet-core file is not inside the saga package. A checkout
    # keeps it at parents[3] of this script. The fixture puts it there.
    outside = script.resolve().parents[3] / "plugins/fleet-core/scripts/fleet_commons/jev_sweep.py"
    outside.parent.mkdir(parents=True, exist_ok=True)
    source = REPO / "plugins/fleet-core/scripts/fleet_commons/jev_sweep.py"
    outside.write_bytes(source.read_bytes())

    def run(*extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(script),
                "may-block",
                "--lens",
                "security",
                "--language",
                "python",
                *extra,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    no_run = run()
    assert no_run.returncode == 0, no_run.stderr
    assert no_run.stderr == ""
    assert no_run.stdout == "report-only no-run\n"

    recorded = subprocess.run(
        [sys.executable, "-c", _RECORD_INSTALLED, str(script)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert recorded.returncode == 0, recorded.stderr

    cleared = run()
    assert cleared.returncode == 0, cleared.stderr
    assert cleared.stderr == ""
    assert cleared.stdout == "yes cleared\n"

    rooted = run("--root", str(install))
    assert rooted.returncode == 0, rooted.stderr
    assert rooted.stderr == ""
    assert rooted.stdout == "yes cleared\n"


def test_default_calibration_is_the_installed_package(tmp_path: Path) -> None:
    head = tmp_path / "head"
    _recorded(head)
    code, stdout, stderr = _invoke(head)
    assert code == 0
    assert stderr == ""
    assert stdout == "report-only no-run\n"
    default = calibration.default_calibration_path()
    assert default == calibration.package_dir() / "references" / "review-calibration.json"
    assert head not in default.parents
    help_run = subprocess.run(
        [sys.executable, str(SCRIPTS / "review_calibration.py"), "may-block", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert help_run.returncode == 0, help_run.stderr
    for phrase in ("base commit", "installed saga", "reviewed head"):
        assert phrase in help_run.stdout


def test_unreadable_profile_exits_2(tmp_path: Path) -> None:
    root = tmp_path / "locked"
    _recorded(root)
    profile = root / ".saga-profile.json"
    profile.write_text("{}\n", encoding="utf-8")
    profile.chmod(0)
    try:
        code, stdout, stderr = _invoke(root, file=root / calibration.CALIBRATION_RELATIVE)
    finally:
        profile.chmod(0o644)
    assert code == 2
    assert stdout == ""
    assert "yes" not in stdout
    assert stderr.strip()


def _component_list(text: str) -> list[str]:
    start = text.index("## Component paths")
    fence = text.index("```", start)
    body = text.index("\n", fence) + 1
    end = text.index("```", body)
    return [line.strip() for line in text[body:end].splitlines() if line.strip()]


def test_reference_documents_fields_kinds_and_the_add_path_rule() -> None:
    text = (REFERENCES / "review-calibration.md").read_text(encoding="utf-8")
    assert _component_list(text) == list(calibration.COMPONENTS)
    for key in (
        "schema",
        "corpus_run",
        "fingerprint",
        "corpus_version",
        "jev_model_version",
        "cost_usd",
        "langfuse_run_id",
        "reviewer_configuration",
        "marks",
        "lenses",
        "thresholds",
    ):
        assert f"`{key}`" in text
    assert "sha256" in text
    assert "targeted-reviewer-launch.json" in text
    assert "adds its paths in the same change" in text
    assert "Instruction files are recorded in `reviewer_configuration` and are not fingerprinted." in text
    assert "scripts/check_repo.py" in text
    assert "plugins/saga/scripts/check_repo.py" not in text
    assert "A component is a file." in text
    assert "reviewer_answer.py" in text
    for phrase in ("base commit", "installed saga", "reviewed head"):
        assert phrase in text
    section = (REFERENCES / "repository-profile.md").read_text(encoding="utf-8")
    block = section.split("### `review_tools`", 1)[1].split("\n## ", 1)[0]
    assert "may-block" in block
    assert "review_tools.pins" in block


#: The language ids in ``corpus/case.py`` LANGUAGES on saga-review-corpus main.
CORPUS_LANGUAGES = (
    "cdk",
    "cloudformation",
    "dart",
    "github-workflow",
    "markdown",
    "python",
    "rust",
    "shell",
    "swift",
    "typescript",
)


def test_corpus_language_ids_verdicts_validate(tmp_path: Path) -> None:
    data = _committed()
    data["corpus_run"] = "recorded"
    for lens in data["lenses"].values():
        lens["drift"] = "as-recorded"
        lens["overall"] = _overall()
        lens["languages"] = {
            language: _language("cleared")
            for language in ("cdk", "cloudformation", "github-workflow")
        }
    assert _problems(data, tmp_path) == []
    data["lenses"]["security"]["languages"]["github-workflows"] = _language("cleared")
    assert any(
        "languages.github-workflows" in problem for problem in _problems(data, tmp_path)
    )


@pytest.mark.parametrize("language", CORPUS_LANGUAGES)
def test_corpus_language_ids_may_block_answers(tmp_path: Path, language: str) -> None:
    root = tmp_path / "root"
    path = _recorded(root, languages={language: _language("cleared")})
    for lens in review_formula.LENSES:
        assert (
            calibration.may_block(lens, language, root=root, calibration=path)
            == "yes cleared"
        )


def _reviewer(**overrides: object) -> dict[str, object]:
    configuration: dict[str, object] = {
        "vendor": "example-vendor",
        "model": "example-model",
        "effort": "high",
        "prompt_sha256": "b" * 64,
        "configuration_fingerprint": "d" * 64,
        "second": {"vendor": "other-vendor", "model": "other-model", "effort": "low"},
        "cleared_components": ["example-component"],
    }
    configuration.update(overrides)
    return configuration


def _with_reviewer(data: dict[str, Any], configuration: object) -> dict[str, Any]:
    data["reviewer_configuration"] = configuration
    return data


def test_reviewer_configuration_object_validates(tmp_path: Path) -> None:
    assert _problems(_with_reviewer(_committed(), _reviewer()), tmp_path) == []
    assert (
        _problems(
            _with_reviewer(_committed(), _reviewer(second=None, cleared_components=[])),
            tmp_path,
        )
        == []
    )


def _reviewer_mutations() -> list[tuple[str, dict[str, Any], str]]:
    base = _reviewer()
    cases: list[tuple[str, dict[str, Any], str]] = []
    for name in ("vendor", "model", "effort"):
        bad = dict(base)
        bad[name] = "not an identifier!"
        cases.append((name, bad, f"reviewer_configuration.{name}"))
    for name in ("prompt_sha256", "configuration_fingerprint"):
        bad = dict(base)
        bad[name] = "xyz"
        cases.append((name, bad, f"reviewer_configuration.{name}"))
    bad = dict(base)
    bad["second"] = "other-vendor"
    cases.append(("second-string", bad, "reviewer_configuration.second"))
    bad = dict(base)
    bad["second"] = {**base["second"], "extra": "no"}  # type: ignore[dict-item]
    cases.append(("second-extra", bad, "reviewer_configuration.second.extra"))
    bad = dict(base)
    bad["second"] = {"vendor": "other-vendor", "model": "other-model"}
    cases.append(("second-missing", bad, "reviewer_configuration.second.effort"))
    bad = dict(base)
    bad["cleared_components"] = ["ok", 7]
    cases.append(("cleared-mixed", bad, "reviewer_configuration.cleared_components"))
    bad = dict(base)
    bad["cleared_components"] = ["same", "same"]
    cases.append(("cleared-duplicate", bad, "reviewer_configuration.cleared_components"))
    bad = dict(base)
    bad["cleared_components"] = "example-component"
    cases.append(("cleared-string", bad, "reviewer_configuration.cleared_components"))
    bad = dict(base)
    bad["launch"] = {"vendor": "example-vendor"}
    cases.append(("unknown-key", bad, "reviewer_configuration.launch"))
    return cases


@pytest.mark.parametrize("name,configuration,field", _reviewer_mutations())
def test_reviewer_configuration_malformed_field_is_refused_by_name(
    tmp_path: Path, name: str, configuration: dict[str, Any], field: str
) -> None:
    del name
    problems = _problems(_with_reviewer(_committed(), configuration), tmp_path)
    assert any(field in problem for problem in problems), problems


@pytest.mark.parametrize("name", list(calibration.REVIEWER_FIELDS))
def test_reviewer_configuration_missing_key_is_refused_by_name(
    tmp_path: Path, name: str
) -> None:
    configuration = _reviewer()
    del configuration[name]
    problems = _problems(_with_reviewer(_committed(), configuration), tmp_path)
    assert any(f"reviewer_configuration.{name}" in problem for problem in problems)


@pytest.mark.parametrize("name", list(calibration.SECOND_FIELDS))
def test_reviewer_configuration_missing_second_key_is_refused_by_name(
    tmp_path: Path, name: str
) -> None:
    second = {"vendor": "other-vendor", "model": "other-model", "effort": "low"}
    del second[name]
    problems = _problems(_with_reviewer(_committed(), _reviewer(second=second)), tmp_path)
    assert any(f"reviewer_configuration.second.{name}" in problem for problem in problems)


def test_reviewer_configuration_null_validates_and_string_is_refused(
    tmp_path: Path,
) -> None:
    assert _problems(_with_reviewer(_committed(), None), tmp_path) == []
    problems = _problems(_with_reviewer(_committed(), "a" * 64), tmp_path)
    assert problems == ["not an identifier: reviewer_configuration"]


def test_reviewer_configuration_recorded_fixtures_still_validate(tmp_path: Path) -> None:
    root = tmp_path / "root"
    path = _recorded(root)
    assert calibration.problems_in(path) == []
    assert calibration.problems_in(COMMITTED) == []


def test_fingerprint_builder_hashes_every_component_through_locate(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _copy_components(root)
    expected = {
        relative: hashlib.sha256(calibration.locate(root, relative).read_bytes()).hexdigest()
        for relative in calibration.COMPONENTS
    }
    assert calibration.fingerprint(root) == expected
    assert list(calibration.fingerprint(root)) == list(calibration.COMPONENTS)


def test_fingerprint_builder_missing_component_raises_naming_the_path(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    _copy_components(root)
    missing = calibration.COMPONENTS[0]
    (root / missing).unlink()
    with pytest.raises(OSError) as failed:
        calibration.fingerprint(root)
    assert missing in str(failed.value)


def test_fingerprint_builder_helper_calls_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = {"plugins/saga/scripts/review_formula.py": "0" * 64}
    monkeypatch.setattr(calibration, "fingerprint", lambda root: sentinel)
    assert _fingerprint(tmp_path) == sentinel
