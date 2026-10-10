"""Shell, workflow, and Markdown adapters, plus the guide and the pins (issue 152)."""

from __future__ import annotations

import importlib.util
import json
import re
import socket
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"
REFERENCES = REPO_ROOT / "plugins" / "saga" / "references"
_FOUR = ("findings.json", "measurements.json", "degraded.json", "outcomes.json")
_TOKEN = "EXAMPLE_NOT_A_SECRET"
_VERSION = re.compile(r"\d+\.\d+(?:\.\d+)?")
_PIN = re.compile(r"\d+\.\d+(?:\.\d+)?")
_PINS = {
    "bandit": "1.9.4",
    "pip-audit": "2.10.1",
    "mypy": "2.1.0",
    "ruff-lint": "0.15.18",
    "ruff-format": "0.15.18",
    "vulture": "2.16",
    "import-linter": "2.15",
    "coverage": "7.16.2",
    "cosmic-ray": "8.7.0",
    "pytest-randomly": "5.0.0",
    "pytest-socket": "0.8.1",
    "cdk-nag": "3.0.2",
    "checkov-cdk": "3.3.25",
    "checkov-cfn": "3.3.25",
    "cfn-lint": "1.57.2",
    "shellcheck": "0.11.0",
    "shfmt": "3.14.1",
    "zizmor": "1.30.1",
    "actionlint": "1.7.12",
    "markdownlint-cli2": "0.23.3",
    "lychee": "0.24.2",
    "cspell": "10.3.6",
}
_CURATED = (
    "CKV_AWS_62", "CKV_AWS_63", "CKV_AWS_356", "CKV_AWS_20", "CKV_AWS_53",
    "CKV_AWS_54", "CKV_AWS_55", "CKV_AWS_56", "CKV_AWS_57", "CKV_AWS_70",
)
_WORKFLOW = "name: ci\non: push\njobs: {}\n"
_WORKFLOW_HEAD = "name: ci\non: pull_request\njobs: {}\n"


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


T = _load("review_tools")
P = _load("review_adapters_python")
S = _load("review_adapters_shell")
W = _load("review_adapters_workflows")
M = _load("review_adapters_markdown")
R = _load("review_records")
_ADAPTERS = (*P.ADAPTERS, *S.ADAPTERS, *W.ADAPTERS, *M.ADAPTERS)
_VERSIONS = {item.tool: item.default_version for item in _ADAPTERS}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("review adapter tests must make no network call")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return proc.stdout.strip()


def _init(repo: Path) -> None:
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "review-tools@example.com")
    _git(repo, "config", "user.name", "review-tools")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _repo(
    tmp: Path, base_files: dict[str, str], head_files: dict[str, str]
) -> tuple[Path, str, str]:
    repo = tmp / "repo"
    _init(repo)
    for name, text in base_files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    base = _commit(repo, "base")
    for name, text in head_files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    head = _commit(repo, "head")
    return repo, base, head


def _adapter(tool_id: str) -> Any:
    return next(item for item in _ADAPTERS if item.id == tool_id)


def _profile(path: Path) -> Path:
    path.write_text(json.dumps({"review_tools": {"pins": {}}}), encoding="utf-8")
    return path


def _version_text(argv: list[str]) -> str | None:
    if "--version" in argv or "-version" in argv:
        return _VERSIONS.get(argv[0], "0.0.0")
    return None


class _Calls:
    def __init__(
        self,
        base: str,
        payload: str,
        *,
        choose: Any = None,
        exit_code: int = 0,
        base_payload: str | None = None,
    ) -> None:
        self.base = base
        self.payload = payload
        self.choose = choose
        self.exit_code = exit_code
        self.base_payload = base_payload
        self.calls: list[list[str]] = []
        self.envs: list[dict[str, str]] = []

    def __call__(
        self, argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool
    ) -> Any:
        assert shell is False
        self.calls.append(list(argv))
        self.envs.append(dict(env))
        version = _version_text(argv)
        if version is not None:
            return T.ProcessResult(0, version + "\n")
        if self.choose is not None:
            chosen = self.choose(argv, Path(cwd))
            if chosen is not None:
                return chosen
        body = self.payload
        if self.base_payload is not None:
            try:
                head = _git(Path(cwd), "rev-parse", "HEAD")
            except subprocess.CalledProcessError:
                head = ""
            body = self.base_payload if head == self.base else self.payload
        return T.ProcessResult(self.exit_code, body)


def _run(
    repo: Path, base: str, head: str, profile: Path, output: Path, home: Path,
    adapters: list[Any], runner: Any,
) -> int:
    home.mkdir(parents=True, exist_ok=True)
    return T.run(
        repo, base, head, profile, output, home=home, adapters=adapters,
        runner=runner, framework=False,
    )


def _read(output: Path, name: str) -> Any:
    return json.loads((output / name).read_text(encoding="utf-8"))


def _valid(output: Path) -> None:
    for name in ("findings.json", "measurements.json"):
        for record in _read(output, name):
            assert R.validate(record) == []


def _severity(output: Path, ref: str) -> str:
    for finding in _read(output, "outcomes.json")["findings"]:
        if finding["rule"]["ref"] == ref:
            return str(finding["severity"])
    raise AssertionError(ref)


def _row(output: Path, ref: str) -> str:
    for finding in _read(output, "findings.json"):
        if finding["rule"]["ref"] == ref:
            return str(finding["rule"]["row"])
    raise AssertionError(ref)


def _reasons(output: Path) -> list[str]:
    return [item["reason"] for item in _read(output, "degraded.json")]


def _refs(output: Path) -> set[str]:
    return {item["rule"]["ref"] for item in _read(output, "findings.json")}


def _probed(argv: list[str]) -> str | None:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = _VERSION.search((proc.stdout or "") + (proc.stderr or ""))
    return match.group(0) if match else None


def _shell(level: str, code: int, line: int) -> dict[str, Any]:
    return {
        "file": "run.sh",
        "line": line,
        "endLine": line,
        "level": level,
        "code": code,
        "message": f"example {level}",
    }


def test_shellcheck_levels_and_an_unchanged_line_is_absent(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path,
        {"run.sh": "#!/bin/sh\necho ok\n"},
        {
            "run.sh": "#!/bin/sh\necho $1 # shellcheck disable=SC2086\n",
            ".shellcheckrc": "disable=SC2086\n",
        },
    )
    payload = json.dumps([
        _shell("error", 2086, 2),
        _shell("warning", 2034, 2),
        _shell("info", 2148, 2),
        _shell("style", 2001, 2),
        _shell("error", 1000, 1),
    ])

    def choose(argv: list[str], _cwd: Path) -> Any:
        source = argv[2] if len(argv) > 2 and argv[0] == "python3" else ""
        if "--norc" in source and "shellcheck disable" in source:
            return None
        return T.ProcessResult(0, "[]")

    runner = _Calls(base, payload, choose=choose)
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("shellcheck")], runner,
    )
    assert code == 0
    assert _row(output, "SC2086") == "correctness.tool-error"
    assert _severity(output, "SC2086") == "blocks"
    assert _severity(output, "SC2034") == "fix-later"
    assert _severity(output, "SC2148") == "note"
    assert _severity(output, "SC2001") == "note"
    assert "SC1000" not in _refs(output)
    assert "shellcheck-disable" in _reasons(output)
    _valid(output)


def test_a_missing_shellcheck_binary_is_reason_missing(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path, {"run.sh": "#!/bin/sh\necho ok\n"}, {"run.sh": "#!/bin/sh\necho hi\n"}
    )

    def explode(
        argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool
    ) -> Any:
        raise FileNotFoundError(argv[0])

    output = tmp_path / "out"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("shellcheck")], explode,
    )
    assert code == 0
    assert "missing" in _reasons(output)


def _action(kind: str, line: int) -> dict[str, Any]:
    return {
        "message": kind,
        "filepath": ".github/workflows/ci.yml",
        "line": line,
        "column": 1,
        "kind": kind,
        "snippet": _TOKEN,
    }


def test_actionlint_kinds_map_to_error_warning_and_style(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path,
        {".github/workflows/ci.yml": _WORKFLOW},
        {
            ".github/workflows/ci.yml": _WORKFLOW_HEAD,
            ".github/actionlint.yaml": ":\n",
        },
    )
    payload = json.dumps([
        _action("job-needs", 2),
        _action("permissions", 2),
        _action("deprecated-commands", 2),
        _action("not-a-kind", 2),
        _action("syntax-check", 1),
    ])

    def choose(argv: list[str], cwd: Path) -> Any:
        source = argv[2] if argv[:2] == ["python3", "-c"] else ""
        if (
            "-config-file" not in source
            or "-shellcheck=" not in source
            or "-pyflakes=" not in source
        ):
            return T.ProcessResult(0, "[]")
        config = next(
            (Path(part) for part in argv[3:] if part.endswith("actionlint.yaml")), None
        )
        if config is None or config == cwd or cwd in config.parents:
            return T.ProcessResult(0, "[]")
        return None

    runner = _Calls(base, payload, choose=choose)
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("actionlint")], runner,
    )
    assert code == 0
    assert _row(output, "job-needs") == "correctness.tool-error"
    assert _severity(output, "job-needs") == "blocks"
    assert _severity(output, "permissions") == "fix-later"
    assert _severity(output, "deprecated-commands") == "note"
    assert _severity(output, "not-a-kind") == "fix-later"
    assert "syntax-check" not in _refs(output)
    for name in _FOUR:
        assert _TOKEN not in (output / name).read_text(encoding="utf-8")
    _valid(output)


def _zizmor(ident: str, severity: str, confidence: str) -> dict[str, Any]:
    return {
        "ident": ident,
        "determinations": {"severity": severity, "confidence": confidence},
        "locations": [{
            "concrete": {
                "path": ".github/workflows/ci.yml",
                "start": {"line": 2},
            },
        }],
        "snippet": _TOKEN,
    }


def test_zizmor_high_blocks_and_medium_is_fix_later(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GH_TOKEN", "example")
    repo, base, head = _repo(
        tmp_path,
        {".github/workflows/ci.yml": _WORKFLOW},
        {
            ".github/workflows/ci.yml": _WORKFLOW_HEAD,
            ".github/zizmor.yml": "rules: {}\n",
        },
    )
    payload = json.dumps([
        _zizmor("artipacked", "high", "certain"),
        _zizmor("unpinned", "medium", "medium"),
        _zizmor("impostor", "low", "low"),
        _zizmor("informational-audit", "informational", "low"),
    ])

    def choose(argv: list[str], _cwd: Path) -> Any:
        source = argv[2] if argv[:2] == ["python3", "-c"] else ""
        if "--offline" not in source or "--format=json" not in source:
            return T.ProcessResult(0, "[]")
        if any("gh-token" in part for part in argv):
            return T.ProcessResult(0, "[]")
        return None

    runner = _Calls(base, payload, choose=choose)
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("zizmor")], runner,
    )
    assert code == 0
    assert _row(output, "artipacked") == "security.workflow-infra-high"
    assert _severity(output, "artipacked") == "blocks"
    assert _row(output, "unpinned") == "security.workflow-infra-medium-low"
    assert _severity(output, "unpinned") == "fix-later"
    assert _severity(output, "impostor") == "fix-later"
    assert _row(output, "informational-audit") == "security.tool-style"
    assert _severity(output, "informational-audit") == "note"
    statement = next(
        item["statement"] for item in _read(output, "findings.json")
        if item["rule"]["ref"] == "artipacked"
    )
    assert "certain" in statement
    assert _TOKEN not in statement
    scan = next(
        argv for argv in runner.calls
        if argv[:2] == ["python3", "-c"] and "--offline" in argv[2]
    )
    assert "--offline" not in scan[3:]
    assert "--format=json" not in scan[3:]
    assert "--gh-token" not in scan
    assert "GH_TOKEN" not in runner.envs[runner.calls.index(scan)]
    version = next(argv for argv in runner.calls if "--version" in argv)
    assert "GH_TOKEN" in runner.envs[runner.calls.index(version)]
    for name in _FOUR:
        assert _TOKEN not in (output / name).read_text(encoding="utf-8")
    assert not any(item["reason"] == "known-gap" for item in _read(output, "degraded.json"))
    _valid(output)


# Lines captured from markdownlint-cli2 v0.23.3 (markdownlint v0.41.1) on stderr.
_REAL_MARKDOWNLINT = (
    (
        't.md:2 error MD022/blanks-around-headings Headings should be surrounded by blank '
        'lines [Expected: 1; Actual: 0; Above] [Context: "## b"]'
    ),
    (
        "t.md:5 error MD012/no-multiple-blanks Multiple consecutive blank lines "
        "[Expected: 1; Actual: 2]"
    ),
    "t.md:6:3 error MD004/ul-style Unordered list style [Expected: dash; Actual: asterisk]",
    (
        "t.md:6:3 warning MD030/list-marker-space Spaces after list markers "
        "[Expected: 1; Actual: 2]"
    ),
)


def test_markdownlint_parses_real_lines_with_severity_and_optional_column() -> None:
    hits = M._parse_markdownlint("\n".join(_REAL_MARKDOWNLINT)).hits
    assert [(h.rule_id, h.path, h.start) for h in hits] == [
        ("MD022", "t.md", 2), ("MD012", "t.md", 5), ("MD004", "t.md", 6), ("MD030", "t.md", 6),
    ]
    assert hits[0].statement.startswith("MD022 Headings should be surrounded by blank lines")
    assert hits[3].statement.startswith("MD030 Spaces after list markers")


def test_markdownlint_still_parses_the_older_column_shape_and_skips_banners() -> None:
    text = (
        "markdownlint-cli2 v0.23.3 (markdownlint v0.41.1)\n"
        "Finding: t.md\nLinting: 1 file\n"
        "notes.md:2:1 MD013/line-length too long\n"
        "Summary: 1 issues in 1 file\n"
    )
    hits = M._parse_markdownlint(text).hits
    assert [(h.rule_id, h.path, h.start) for h in hits] == [("MD013", "notes.md", 2)]


def test_markdownlint_reads_stderr_and_no_other_markdown_tool_does() -> None:
    assert _adapter("markdownlint-cli2").stream == "stderr"
    assert _adapter("lychee").stream == "stdout"
    assert _adapter("cspell").stream == "stdout"


def test_markdownlint_findings_on_stderr_reach_the_review(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path, {"README.md": "base\n"}, {"README.md": "base\n", "t.md": "# a\n## b\n"}
    )
    stderr = "\n".join(_REAL_MARKDOWNLINT[:1]) + "\n"

    def on_stderr(argv: list[str], cwd: Path) -> Any:
        if "--config" in argv:
            return T.ProcessResult(1, "Linting: 2 files\n", stderr)
        return None

    output = tmp_path / "out"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("markdownlint-cli2")], _Calls(base, "", choose=on_stderr),
    )
    assert code == 0
    findings = _read(output, "findings.json")
    assert [item["statement"].split()[0] for item in findings] == ["MD022"]
    assert _severity(output, "MD022") == "note"


def test_markdownlint_and_cspell_are_notes_and_lychee_is_fix_later(tmp_path: Path) -> None:
    base_dictionary = '{"version": "0.2", "words": ["alpha"]}\n'
    repo, base, head = _repo(
        tmp_path,
        {
            "notes.md": "# title\nshort\n",
            "same.md": "# same\n",
            "cspell.json": base_dictionary,
        },
        {
            "notes.md": "# title\nthis line changed\n",
            "same.md": "# same changed\n",
            "changed.md": "# changed\n",
            "cspell.json": '{"version": "0.2", "words": ["alpha", "beta"]}\n',
            ".markdownlint.yaml": "MD013: false\n",
        },
    )
    markdown = (
        "notes.md:2:1 MD013/line-length too long\n"
        "notes.md:1:1 MD013/line-length title\n"
    )
    cspell = "notes.md:2:1 - Unknown word (beta)\nnotes.md:1:1 - Unknown word (alpha)\n"
    old_url = "https://example.invalid/same"
    new_url = "https://example.invalid/new-on-an-unchanged-first-line"
    base_lychee = json.dumps({"fail_map": {"same.md": [{"url": old_url}]}})
    lychee = json.dumps({"fail_map": {
        "notes.md": [{"url": new_url}],
        "same.md": [{"url": old_url}],
    }})

    def choose_markdown(argv: list[str], cwd: Path) -> Any:
        if "--config" not in argv:
            return T.ProcessResult(0, "")
        path = Path(argv[argv.index("--config") + 1])
        if cwd == path or cwd in path.parents:
            return T.ProcessResult(0, "")
        return None

    def markdown_on_stderr(argv: list[str], cwd: Path) -> Any:
        # markdownlint-cli2 writes its findings to stderr and a banner to stdout.
        if "--config" in argv:
            return T.ProcessResult(1, "markdownlint-cli2 v0.23.3\nLinting: 1 file\n", markdown)
        return None

    home = tmp_path / "home"
    output = tmp_path / "markdown"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, home,
        [_adapter("markdownlint-cli2")], _Calls(base, "", choose=markdown_on_stderr),
    )
    assert code == 0
    assert _severity(output, "MD013") == "note"
    assert _row(output, "MD013") == "correctness.tool-style"
    statements = [item["statement"] for item in _read(output, "findings.json")]
    assert len(statements) == 1
    assert "title" not in statements[0]

    spell_out = tmp_path / "spell"
    code = _run(
        repo, base, head, _profile(tmp_path / "spell-profile.json"), spell_out,
        tmp_path / "spell-home",
        [_adapter("cspell")], _Calls(base, cspell, choose=choose_markdown),
    )
    assert code == 0
    assert _row(spell_out, "beta") == "architecture-maintainability.tool-style"
    assert _severity(spell_out, "beta") == "note"
    assert "alpha" not in _refs(spell_out)
    written = (tmp_path / "spell-home" / "cspell.json").read_text(encoding="utf-8")
    assert written == base_dictionary

    link_out = tmp_path / "links"
    code = _run(
        repo, base, head, _profile(tmp_path / "link-profile.json"), link_out,
        tmp_path / "link-home",
        [_adapter("lychee")],
        _Calls(base, lychee, exit_code=2, base_payload=base_lychee),
    )
    assert code == 0
    assert _row(link_out, new_url) == "architecture-maintainability.tool-warning"
    assert _severity(link_out, new_url) == "fix-later"
    assert old_url not in _refs(link_out)
    _valid(output)
    _valid(spell_out)
    _valid(link_out)


def test_formatters_write_no_record(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path, {"app.py": "x = 1\n"}, {"app.py": "x=1\n", "run.sh": "echo  1\n"}
    )
    runner = _Calls(base, "should-not-be-parsed")
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("ruff-format"), _adapter("shfmt")], runner,
    )
    assert code == 0
    assert _read(output, "findings.json") == []
    assert runner.calls == []


def test_default_adapters_include_the_issue_table() -> None:
    ids = {item.id for item in T.default_adapters()}
    for tool_id in _PINS:
        assert tool_id in ids


def test_default_versions() -> None:
    document = yaml.safe_load((REFERENCES / "review-tools.yaml").read_text(encoding="utf-8"))
    rows = {row["id"]: row for row in document["tools"]}
    for tool_id, pin in _PINS.items():
        version = str(rows[tool_id]["default_version"])
        assert version == pin
        assert _PIN.fullmatch(version)
        assert version != "not-recorded"
    assert rows["import-linter"]["default_version"] == "2.15"
    assert rows["import-linter"]["default_version"] != "2.15.0"
    source = (REPO_ROOT / "plugins/saga/scripts/review_adapters_python.py").read_text(
        encoding="utf-8"
    )
    for package in ("cosmic-ray", "pytest-randomly", "pytest-socket"):
        assert f"{package}=={rows[package]['default_version']}" in source
    assert rows["ruff-lint"]["default_version"] == rows["ruff-format"]["default_version"]
    assert rows["checkov-cdk"]["default_version"] == rows["checkov-cfn"]["default_version"]
    assert rows["relocated-test"]["default_version"] == "not-recorded"
    assert rows["coverage"]["tool"] == ""


def test_review_tools_md() -> None:
    guide = (REFERENCES / "review-tools.md").read_text(encoding="utf-8")
    for tool_id in _PINS:
        assert tool_id in guide
    for rule_id in _CURATED:
        assert rule_id in guide
    for prefix in ("F", "B", "S", "C4", "UP", "SIM", "RUF", "E", "W", "N", "I"):
        assert prefix in guide
    for word in ("blocks", "fix later", "note"):
        assert word in guide
    for path in (
        "plugins/saga/scripts/review_adapters_python.py",
        "plugins/saga/scripts/review_adapters_infrastructure.py",
        "plugins/saga/scripts/review_adapters_shell.py",
        "plugins/saga/scripts/review_adapters_workflows.py",
        "plugins/saga/scripts/review_adapters_markdown.py",
    ):
        assert path in guide


@pytest.mark.skipif(
    _probed(["shellcheck", "--version"]) != "0.11.0",
    reason="shellcheck pin is not installed",
)
def test_shellcheck_live_reports_an_unquoted_expansion(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path,
        {"README.md": "base\n"},
        {
            "run.sh": "#!/bin/sh\necho $1 # shellcheck disable=SC2086\n",
            ".shellcheckrc": "disable=SC2086\n",
        },
    )
    output = tmp_path / "out"
    home = tmp_path / "home"
    home.mkdir()
    code = T.run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        home=home, adapters=[_adapter("shellcheck")], framework=False,
    )
    assert code == 0
    assert "SC2086" in _refs(output)


@pytest.mark.skipif(
    _probed(["actionlint", "-version"]) != "1.7.12",
    reason="actionlint pin is not installed",
)
def test_actionlint_live_reports_a_missing_need(tmp_path: Path) -> None:
    workflow = (
        "name: ci\non: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n"
        "    needs: [missing]\n    steps:\n      - run: echo ok\n"
    )
    repo, base, head = _repo(
        tmp_path,
        {"README.md": "base\n"},
        {".github/workflows/ci.yml": workflow, ".github/actionlint.yaml": ":\n"},
    )
    output = tmp_path / "out"
    home = tmp_path / "home"
    home.mkdir()
    code = T.run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        home=home, adapters=[_adapter("actionlint")], framework=False,
    )
    assert code == 0
    assert "job-needs" in _refs(output)


@pytest.mark.skipif(
    _probed(["zizmor", "--version"]) != "1.30.1",
    reason="zizmor pin is not installed",
)
def test_zizmor_live_stays_offline(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path,
        {"README.md": "base\n"},
        {".github/workflows/ci.yml": _WORKFLOW_HEAD},
    )
    output = tmp_path / "out"
    home = tmp_path / "home"
    home.mkdir()
    code = T.run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        home=home, adapters=[_adapter("zizmor")], framework=False,
    )
    assert code == 0


@pytest.mark.skipif(
    _probed(["markdownlint-cli2", "--version"]) != "0.23.3",
    reason="markdownlint-cli2 pin is not installed",
)
def test_markdownlint_live_is_a_note_when_the_pin_matches(tmp_path: Path) -> None:
    repo, base, head = _repo(tmp_path, {"README.md": "base\n"}, {"notes.md": "# title\n\n\n"})
    output = tmp_path / "out"
    home = tmp_path / "home"
    home.mkdir()
    code = T.run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        home=home, adapters=[_adapter("markdownlint-cli2")], framework=False,
    )
    assert code == 0


@pytest.mark.skipif(
    _probed(["cspell", "--version"]) != "10.3.6",
    reason="cspell pin is not installed",
)
def test_cspell_live_is_a_note_when_the_pin_matches(tmp_path: Path) -> None:
    repo, base, head = _repo(tmp_path, {"README.md": "base\n"}, {"notes.md": "# title\n"})
    output = tmp_path / "out"
    home = tmp_path / "home"
    home.mkdir()
    code = T.run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        home=home, adapters=[_adapter("cspell")], framework=False,
    )
    assert code == 0


@pytest.mark.skipif(
    _probed(["shfmt", "--version"]) != "3.14.1",
    reason="shfmt pin is not installed",
)
def test_shfmt_live_writes_no_record(tmp_path: Path) -> None:
    repo, base, head = _repo(tmp_path, {"run.sh": "echo ok\n"}, {"run.sh": "echo  ok\n"})
    output = tmp_path / "out"
    home = tmp_path / "home"
    home.mkdir()
    code = T.run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        home=home, adapters=[_adapter("shfmt")], framework=False,
    )
    assert code == 0
    assert _read(output, "findings.json") == []


@pytest.mark.skipif(_probed(["ruff", "--version"]) != "0.15.18", reason="ruff pin is not installed")
def test_ruff_format_live_writes_no_record(tmp_path: Path) -> None:
    repo, base, head = _repo(tmp_path, {"app.py": "x = 1\n"}, {"app.py": "x=1\n"})
    output = tmp_path / "out"
    home = tmp_path / "home"
    home.mkdir()
    code = T.run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        home=home, adapters=[_adapter("ruff-format")], framework=False,
    )
    assert code == 0
    assert _read(output, "findings.json") == []
