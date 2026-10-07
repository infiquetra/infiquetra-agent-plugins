"""CloudFormation and CDK adapters map recorded output onto the lens rows (issue 152)."""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"
_FOUR = ("findings.json", "measurements.json", "degraded.json", "outcomes.json")
_TOKEN = "EXAMPLE_NOT_A_SECRET"
_VERSION = re.compile(r"\d+\.\d+(?:\.\d+)?")


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
I = _load("review_adapters_infrastructure")
R = _load("review_records")
_VERSIONS = {item.tool: item.default_version for item in I.ADAPTERS}


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
    return next(item for item in I.ADAPTERS if item.id == tool_id)


def _profile(path: Path) -> Path:
    path.write_text(json.dumps({"review_tools": {"pins": {}}}), encoding="utf-8")
    return path


def _version_text(argv: list[str]) -> str | None:
    if (
        len(argv) >= 3
        and argv[0] == "python3"
        and argv[1] == "-c"
        and "importlib.metadata" in argv[2]
    ):
        for name, version in _VERSIONS.items():
            if name in argv[2]:
                return version
        return "0.0.0"
    if "--version" in argv or "-version" in argv:
        return _VERSIONS.get(argv[0], "0.0.0")
    return None


class _Calls:
    def __init__(
        self,
        base: str,
        payload: str,
        *,
        base_payload: str = "{}",
        choose: Any = None,
        exit_code: int = 0,
    ) -> None:
        self.base = base
        self.payload = payload
        self.base_payload = base_payload
        self.choose = choose
        self.exit_code = exit_code
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


def _nag(findings: list[dict[str, str]]) -> str:
    return json.dumps({"report_present": True, "findings": findings})


def _nag_hit(rule_id: str, level: str, resource: str) -> dict[str, str]:
    return {
        "rule_id": rule_id,
        "level": level,
        "resource": resource,
        "path": "Stack.template.json",
        "summary": "The bucket is public.",
        "template_body": _TOKEN,
    }


def _check(rule_id: str, line: int, *, secret: bool = False) -> dict[str, Any]:
    item: dict[str, Any] = {
        "check_id": rule_id,
        "check_name": "example check",
        "file_path": "template.yaml",
        "file_line_range": [line, line],
        "resource": "Bucket",
    }
    if secret:
        item["code_block"] = [[line, f"{_TOKEN} = true"]]
    return item


def _checkov(checks: list[dict[str, Any]]) -> str:
    return json.dumps({"results": {"failed_checks": checks}})


def test_cdk_nag_error_blocks_and_a_base_error_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GH_TOKEN", "example")
    repo, base, head = _repo(
        tmp_path, {"cdk.json": "{}\n"}, {"cdk.json": "{}\n", "app.py": "x = 1\n"}
    )
    base_payload = _nag([_nag_hit("AwsSolutions-IAM5", "error", "Bucket")])
    payload = _nag([
        _nag_hit("AwsSolutions-IAM5", "error", "Bucket"),
        _nag_hit("AwsSolutions-S1", "warning", "Logs"),
        _nag_hit("AwsSolutions-IAM4", "error", "Role"),
    ])
    runner = _Calls(base, payload, base_payload=base_payload)
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("cdk-nag")], runner,
    )
    assert code == 0
    assert "AwsSolutions-IAM5" not in _refs(output)
    assert _row(output, "AwsSolutions-IAM4") == "security.workflow-infra-high"
    assert _severity(output, "AwsSolutions-IAM4") == "blocks"
    assert _row(output, "AwsSolutions-S1") == "security.workflow-infra-medium-low"
    assert _severity(output, "AwsSolutions-S1") == "fix-later"
    scan = next(argv for argv in runner.calls if any("synth" in part for part in argv))
    assert "GH_TOKEN" not in runner.envs[runner.calls.index(scan)]
    version = next(
        argv for argv in runner.calls if any("importlib.metadata" in part for part in argv)
    )
    assert "GH_TOKEN" in runner.envs[runner.calls.index(version)]
    for name in _FOUR:
        assert _TOKEN not in (output / name).read_text(encoding="utf-8")
    _valid(output)


def test_cdk_nag_without_cdk_json_does_not_degrade(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path, {"app.py": "x = 1\n"}, {"app.py": "x = 2  # cdk_nag\n"}
    )
    runner = _Calls(base, _nag([_nag_hit("AwsSolutions-IAM5", "error", "Bucket")]))
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("cdk-nag"), _adapter("checkov-cdk")], runner,
    )
    assert code == 0
    assert _read(output, "findings.json") == []
    assert "known-gap" not in _reasons(output)
    assert "missing" not in _reasons(output)
    assert not any("cdk synth" in " ".join(argv) for argv in runner.calls)
    assert not any("--skip-download" in " ".join(argv) for argv in runner.calls)


def test_cdk_nag_missing_report_is_known_gap(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path,
        {"cdk.json": "{}\n", "app.py": "x = 1\n"},
        {"cdk.json": "{}\n", "app.py": "x = 2  # cdk_nag\n"},
    )
    payload = json.dumps({"report_present": False, "findings": []})
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("cdk-nag")], _Calls(base, payload, base_payload=payload),
    )
    assert code == 0
    assert _reasons(output).count("known-gap") == 1
    assert _read(output, "findings.json") == []


def test_cdk_nag_synth_missing_is_reason_missing(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path, {"cdk.json": "{}\n"}, {"cdk.json": "{}\n", "app.py": "x = 1\n"}
    )
    payload = json.dumps({"report_present": False, "synth_missing": True, "findings": []})
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("cdk-nag")], _Calls(base, payload, base_payload=payload),
    )
    assert code == 0
    assert _reasons(output).count("missing") == 1


def test_checkov_curated_rule_blocks_and_an_uncurated_rule_is_fix_later(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path,
        {"template.yaml": "Resources:\n  Bucket: {}\n"},
        {
            "template.yaml": "Resources:\n  Bucket: {Type: AWS::S3::Bucket}\n",
            ".checkov.yaml": "skip-check: [CKV_AWS_62]\n",
        },
    )
    payload = _checkov([
        _check("CKV_AWS_62", 2, secret=True),
        _check("CKV_AWS_999", 2, secret=True),
        _check("CKV_AWS_20", 1),
    ])

    def choose(argv: list[str], cwd: Path) -> Any:
        if not argv or argv[0] != "python3" or "--skip-download" not in " ".join(argv):
            return T.ProcessResult(0, _checkov([]))
        dest = Path(argv[5])
        if dest == cwd or cwd in dest.parents:
            return T.ProcessResult(0, _checkov([]))
        if "bc-api-key" in " ".join(argv):
            return T.ProcessResult(0, _checkov([]))
        return None

    runner = _Calls(base, payload, choose=choose)
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("checkov-cfn")], runner,
    )
    assert code == 0
    assert _row(output, "CKV_AWS_62") == "security.tool-curated"
    assert _severity(output, "CKV_AWS_62") == "blocks"
    assert _row(output, "CKV_AWS_999") == "security.tool-unscoped"
    assert _severity(output, "CKV_AWS_999") == "fix-later"
    assert "CKV_AWS_20" not in _refs(output)
    assert "--skip-download" in " ".join(runner.calls[-1])
    assert "bc-api-key" not in " ".join(runner.calls[-1])
    for name in _FOUR:
        assert _TOKEN not in (output / name).read_text(encoding="utf-8")
    _valid(output)


def test_checkov_cdk_finding_present_at_base_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GH_TOKEN", "example")
    repo, base, head = _repo(
        tmp_path, {"cdk.json": "{}\n"}, {"cdk.json": "{}\n", "app.py": "x = 1\n"}
    )
    repeated = _checkov([_check("CKV_AWS_62", 1)])
    payload = _checkov([_check("CKV_AWS_62", 1), _check("CKV_AWS_63", 1)])
    runner = _Calls(base, payload, base_payload=repeated)
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("checkov-cdk")], runner,
    )
    assert code == 0
    assert "CKV_AWS_62" not in _refs(output)
    assert _row(output, "CKV_AWS_63") == "security.tool-curated"
    assert _severity(output, "CKV_AWS_63") == "blocks"
    scan = next(argv for argv in runner.calls if "--skip-download" in " ".join(argv))
    assert "GH_TOKEN" not in runner.envs[runner.calls.index(scan)]
    assert "--bc-api-key" not in scan


def test_checkov_non_object_is_unparseable(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path, {"template.yaml": "Resources: {}\n"}, {"template.yaml": "Resources:\n  A: {}\n"}
    )
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("checkov-cfn")],
        _Calls(base, "null", choose=lambda _argv, _cwd: T.ProcessResult(0, "null")),
    )
    assert code == 0
    assert "unparseable" in _reasons(output)


def _cfn(rule_id: str, line: int, message: str) -> dict[str, Any]:
    return {
        "Rule": {"Id": rule_id},
        "Level": "Error",
        "Filename": "template.yaml",
        "Location": {"Start": {"LineNumber": line}, "End": {"LineNumber": line}},
        "Message": message,
    }


def test_cfn_lint_levels_follow_the_rule_prefix(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path,
        {"template.yaml": "Resources:\n  Bucket: {}\n"},
        {"template.yaml": "Resources:\n  Bucket: {Type: AWS::S3::Bucket}\n"},
    )
    payload = json.dumps([
        _cfn("E3012", 2, "bad type"),
        _cfn("W2001", 2, "unused"),
        _cfn("I1001", 2, "info"),
        _cfn("E3001", 1, "unchanged"),
    ])
    output = tmp_path / "out"
    code = _run(
        repo, base, head, _profile(tmp_path / "profile.json"), output, tmp_path / "home",
        [_adapter("cfn-lint")], _Calls(base, payload),
    )
    assert code == 0
    assert _row(output, "E3012") == "correctness.tool-error"
    assert _severity(output, "E3012") == "blocks"
    assert _row(output, "W2001") == "correctness.tool-warning"
    assert _severity(output, "W2001") == "fix-later"
    assert _row(output, "I1001") == "correctness.tool-style"
    assert _severity(output, "I1001") == "note"
    assert "E3001" not in _refs(output)
    _valid(output)


def _distribution(name: str) -> str | None:
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:  # pragma: no cover
        return None
    try:
        return version(name)
    except PackageNotFoundError:
        return None


@pytest.mark.skipif(
    shutil.which("cdk") is None or _distribution("cdk-nag") != "3.0.2",
    reason="cdk-nag pin is not installed",
)
def test_cdk_nag_live_synth_does_not_install(tmp_path: Path) -> None:
    repo, base, head = _repo(
        tmp_path, {"README.md": "base\n"}, {"cdk.json": '{"app": "python3 app.py"}\n'}
    )
    output = tmp_path / "out"
    home = tmp_path / "home"
    home.mkdir()
    code = T.run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        home=home, adapters=[_adapter("cdk-nag")], framework=False,
    )
    assert code == 0
    reasons = _reasons(output)
    assert _refs(output) or "known-gap" in reasons or "missing" in reasons


@pytest.mark.skipif(
    _probed(["checkov", "--version"]) != "3.3.25",
    reason="checkov pin is not installed",
)
def test_checkov_live_scans_one_resource_template(tmp_path: Path) -> None:
    template = "Resources:\n  Bucket:\n    Type: AWS::S3::Bucket\n"
    repo, base, head = _repo(tmp_path, {"README.md": "base\n"}, {"template.yaml": template})
    output = tmp_path / "out"
    home = tmp_path / "home"
    home.mkdir()
    code = T.run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        home=home, adapters=[_adapter("checkov-cfn")], framework=False,
    )
    assert code == 0


@pytest.mark.skipif(
    _probed(["cfn-lint", "--version"]) != "1.57.2", reason="cfn-lint pin is not installed"
)
def test_cfn_lint_live_scans_one_resource_template(tmp_path: Path) -> None:
    template = "Resources:\n  Bucket:\n    Type: AWS::S3::Bucket\n"
    repo, base, head = _repo(tmp_path, {"README.md": "base\n"}, {"template.yaml": template})
    output = tmp_path / "out"
    home = tmp_path / "home"
    home.mkdir()
    code = T.run(
        repo, base, head, _profile(tmp_path / "profile.json"), output,
        home=home, adapters=[_adapter("cfn-lint")], framework=False,
    )
    assert code == 0
