"""Subfolder Node checks use project dependencies and retain stable case identities."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_SPEC = importlib.util.spec_from_file_location("node_check_harness", Path(__file__).with_name("review_check_harness.py"))
assert _SPEC and _SPEC.loader
H = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(H)
P = H.load("review_node_projects")


@pytest.mark.parametrize("command,kind", [
    ("vitest run", "vitest"), ("npx vitest run", "vitest"),
    ("jest", "jest"), ("npx jest", "jest"),
    ("npm test", "vitest"), ("npm run test", "vitest"),
    ("pnpm test", "vitest"), ("yarn test", "vitest"),
])
def test_node_command_forms_resolve_only_a_known_runner(tmp_path: Path, command: str, kind: str) -> None:
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}))
    assert P.test_command(command, tmp_path) == (kind, [], ".")
    assert H.C._classify(command, root=tmp_path)[0] == kind


@pytest.mark.parametrize("script", ["echo vitest", "vitest run && echo x", "npm test", "node script.js", "vitest $FLAGS", "jest; echo x"])
def test_unknown_or_compound_scripts_never_receive_runner_options(tmp_path: Path, script: str) -> None:
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": script}}))
    assert P.test_command("npm test", tmp_path) is None


# A tiny runner executable models structured case reports. It deliberately varies times and
# assertion order between runs; it also checks that production code was not copied to base.
_STUB = '''#!__PYTHON__
import json, pathlib, re, sys, time
cwd = pathlib.Path.cwd()
args = sys.argv[1:]
files = [arg for arg in args if '.test.' in arg and (cwd / arg).is_file()]
pattern = args[args.index('--testNamePattern') + 1] if '--testNamePattern' in args else None
suites = []
for file in files:
    cases = []
    for name in (cwd / file).read_text().splitlines():
        if pattern and not re.search(pattern, name): continue
        status = 'failed' if name == 'fixed' and 'false' in (cwd / 'app.ts').read_text() else 'passed'
        if name == 'skipped': status = 'pending'
        cases.append({'fullName': name, 'status': status, 'duration': time.time()})
    suites.append({'name': str(cwd / file), 'assertionResults': list(reversed(cases)), 'status': 'passed'})
print(json.dumps({'testResults': suites, 'startTime': time.time()}))
'''


def _repo(tmp_path: Path, kind: str) -> tuple[Path, str, str, Path]:
    manifest = json.dumps({"scripts": {"test": kind + (" run" if kind == "vitest" else "")},
                           "devDependencies": {kind: "1.0.0"}})
    common = {"web/package.json": manifest, "web/package-lock.json": '{"lockfileVersion":3,"packages":{}}',
              "web/app.ts": "export const value = false;\n", "web/old.test.ts": "existing\n",
              ".gitignore": "node_modules/\n"}
    repo, base, head = H.make_repo(tmp_path, common,
        {"web/app.ts": "export const value = true;\n",
         "web/new.test.ts": "already\nfixed\nskipped\n"})
    modules = tmp_path / "modules"
    H.executable(modules / ".bin" / kind, _STUB.replace("__PYTHON__", sys.executable))
    return repo, base, head, modules


@pytest.mark.parametrize("kind", ["vitest", "jest"])
def test_two_runs_in_subfolder_reports_only_a_new_case_passing_on_old_code(tmp_path: Path, kind: str) -> None:
    repo, base, _, modules = _repo(tmp_path, kind)
    (repo / "web/node_modules").symlink_to(modules)
    found = H.C.two_runs(repo, base, [("typescript", "cd web && npm test")])
    assert found["gaps"] == []
    assert [(hit["path"], hit["rule_id"]) for hit in found["hits"]] == [
        ("web/new.test.ts", "web/new.test.ts::already")]
    assert H.C.two_runs(repo, base, [("typescript", "cd web && npm test")]) == found


@pytest.mark.parametrize("kind", ["vitest", "jest"])
def test_prepare_command_discovery_and_packet_dependencies_reach_two_runs(tmp_path: Path, kind: str) -> None:
    repo, base, head, modules = _repo(tmp_path, kind)
    profile = H.profile(tmp_path / "profile.json", "echo no-root-project")
    # The script is added from package.json despite the profile having no Node command.
    output = tmp_path / "out"
    (tmp_path / "home").mkdir()
    code = H.T.run(repo, base, head, profile, output, tmp_path / "home",
                   adapters=[H.adapter("two-runs")], framework=False,
                   node_projects=(("web", modules),))
    assert code == 0
    refs = {hit["rule"]["ref"] for hit in H.read(output, "findings.json")}
    assert refs == {"web/new.test.ts::already"}


@pytest.mark.parametrize("kind", ["vitest", "jest"])
def test_modified_node_test_excludes_cases_that_already_existed(tmp_path: Path, kind: str) -> None:
    repo, base, _, modules = _repo(tmp_path, kind)
    H.write(repo, {"web/old.test.ts": "existing\nalso-new\n"})
    H.commit(repo, "edit test")
    (repo / "web/node_modules").symlink_to(modules)
    found = H.C.two_runs(repo, base, [("typescript", f"cd web && {kind}" + (" run" if kind == "vitest" else ""))])
    assert {hit["rule_id"] for hit in found["hits"]} == {"web/new.test.ts::already", "web/old.test.ts::also-new"}


@pytest.mark.skipif(os.environ.get("SAGA_TEST_LIVE_NPM") != "1", reason="opt-in (SAGA_TEST_LIVE_NPM=1): needs npm and network")
@pytest.mark.parametrize("kind,version", [("vitest", "4.1.11"), ("jest", "30.5.2")])
def test_live_node_two_runs_with_locked_subfolder_dependencies(tmp_path: Path, kind: str, version: str) -> None:
    if not shutil.which("npm"):
        pytest.skip("npm is not installed")
    N = H.load("review_dependencies_node")
    D = H.load("review_dependencies")
    manifest = {"name": "example", "private": True, "scripts": {"test": kind + (" run" if kind == "vitest" else "")},
                "devDependencies": {kind: version}}
    common = {"web/package.json": json.dumps(manifest), "web/app.js": "module.exports = (a, b) => a - b;\n"}
    repo, base, _ = H.make_repo(tmp_path, common, {"README.md": "example\n"})
    web = repo / "web"
    proc = subprocess.run(["npm", "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"],
        cwd=web, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    H.commit(repo, "lock")
    base = H.git(repo, "rev-parse", "HEAD")
    imports = "import {test, expect} from 'vitest';\nimport add from './app.js';\n" if kind == "vitest" else "const add = require('./app');\n"
    H.write(repo, {"web/app.js": "module.exports = (a, b) => a + b;\n",
                   "web/new.test.js": imports + "test('already', () => expect(add(0,0)).toBe(0));\n"
                   + "test('fixed', () => expect(add(1,1)).toBe(2));\n"})
    head = H.commit(repo, "fix")
    packet = tmp_path / "packet"
    packet.mkdir()
    def export(dest: Path) -> bool:
        H.write(dest, {name: H.git(repo, "show", f"{head}:{name}") for name in H.git(repo, "ls-tree", "-r", "--name-only", head).splitlines()})
        return True
    def runner(argv: list[str], **kwargs: Any) -> Any:
        proc = subprocess.run(argv, cwd=kwargs["cwd"], env=kwargs.get("env"), capture_output=True, text=True, timeout=kwargs["timeout"])
        return H.T.ProcessResult(proc.returncode, proc.stdout, proc.stderr)
    try:
        record = D.fetch(runner, repo, head, packet, export, base=base)
        (packet / D.FILE).write_text(json.dumps(record))
        assert record["node"]["projects"][0]["state"] == "installed", record
        N.link_projects(repo, N.installed_projects(packet))
        found = H.C.two_runs(repo, base, [("typescript", "cd web && npm test")], diagnostics=tmp_path / "diagnostics")
        assert found["gaps"] == [], found
        assert [hit["rule_id"] for hit in found["hits"]] == ["web/new.test.js::already"]
    finally:
        N.unseal(packet / "dependencies/node")


@pytest.mark.parametrize("kind", ["vitest", "jest"])
@pytest.mark.parametrize("vendored", [False, True])
def test_two_prepares_of_subfolder_commit_produce_identical_complete_packets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, vendored: bool,
) -> None:
    C = H.load("review_command")
    A = H.load("review_adapters_typescript")
    repo, base, head, _ = _repo(tmp_path, kind)
    if vendored:
        # The manager is synthetic here; the separate offline npm test installs a real
        # archive. This fixture exercises verified file inputs through complete prepare.
        import base64
        import hashlib
        data = b"inert vendored archive fixture\n"
        target = repo / "web/vendor/vendored.tgz"
        target.parent.mkdir()
        target.write_bytes(data)
        manifest = json.loads((repo / "web/package.json").read_text())
        manifest["dependencies"] = {"vendored": "file:vendor/vendored.tgz"}
        (repo / "web/package.json").write_text(json.dumps(manifest))
        (repo / "web/package-lock.json").write_text(json.dumps({"lockfileVersion": 3,
            "packages": {"": {}, "node_modules/vendored": {"version": "1.0.0",
                "resolved": "file:vendor/vendored.tgz",
                "integrity": "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode()}}}))
        head = H.commit(repo, "vendored dependency")
    profile = H.profile(tmp_path / "profile.json", "echo no-root-project")
    builder = tmp_path / "builder.json"
    builder.write_text(json.dumps({"kind": "builder_record", "schema": H.R.SCHEMA,
        "unit": "U1", "acceptance_criteria": [{"id": "AC-1", "text": "The value is fixed.", "checks": ["test"]}],
        "declarations": [], "reasons": []}))
    home = tmp_path / "home"
    home.mkdir()
    real_which = shutil.which
    monkeypatch.setattr(shutil, "which", lambda name, *a, **kw:
                        "/inert/npm" if name == "npm" else real_which(name, *a, **kw))
    installs: list[str] = []
    def runner(argv: list[str], **kwargs: Any) -> Any:
        cwd = Path(kwargs["cwd"])
        if "--watch" in argv:
            assert cwd.name == "web"
            installs.append(cwd.name)
            H.executable(cwd / "node_modules/.bin" / kind, _STUB.replace("__PYTHON__", sys.executable))
            H.write(cwd, {f"node_modules/{kind}/package.json": json.dumps({"name": kind, "version": "1.0.0"}),
                          "node_modules/.package-lock.json": str(len(installs))})
            return H.T.ProcessResult(0, "")
        if Path(argv[0]).name == "stryker":
            if "--version" in argv:
                return H.T.ProcessResult(0, "10.0.0\n")
            assert cwd.name == "web" and (cwd / "node_modules/.bin" / kind).is_file()
            report = cwd / "reports/mutation/mutation.json"
            report.parent.mkdir(parents=True)
            report.write_text(json.dumps({"time": len(installs), "files": {"app.ts": {"mutants": [{
                "id": str(len(installs)), "mutatorName": operator, "status": "Survived",
                "location": {"start": {"line": 1}, "end": {"line": 1}}}
                for operator in ("BooleanLiteral", "ConditionalExpression")]}}}))
            return H.T.ProcessResult(0, "")
        proc = subprocess.run(argv, cwd=cwd, env=kwargs.get("env"), capture_output=True, text=True,
                              timeout=kwargs["timeout"])
        return H.T.ProcessResult(proc.returncode, proc.stdout, proc.stderr)
    packets = []
    try:
        for name in ("first", "second"):
            out = tmp_path / name
            code = C.main(["prepare", "--repo", str(repo), "--base", base, "--head", head,
                "--profile", str(profile), "--builder-record", str(builder), "--out", str(out),
                "--home", str(home), "--bank", str(tmp_path / "no-bank.json")],
                adapters=[H.adapter("two-runs"), next(a for a in A.ADAPTERS if a.id == "stryker")],
                runner=runner)
            assert code == 0
            packets.append(out)
        assert len(installs) == 2
        def content(folder: Path) -> dict[str, Any]:
            return {p.relative_to(folder).as_posix():
                    (os.readlink(p) if p.is_symlink() else p.read_bytes())
                    for p in folder.rglob("*") if p.is_file() or p.is_symlink()}
        assert content(packets[0]) == content(packets[1])
        items = json.loads((packets[0] / "where-to-look.json").read_text())
        assert {item["classifier"]["name"] for item in items} >= {"two-runs", "surviving-mutant"}
        assert len([item for item in items if item["classifier"]["name"] == "two-runs"]) == 1
        mutants = [item for item in items if item["classifier"]["name"] == "surviving-mutant"]
        assert {item["location"]["anchor"] for item in mutants} == {
            "surviving-mutant:BooleanLiteral:1", "surviving-mutant:ConditionalExpression:1"}
    finally:
        for packet in packets:
            C.review_dependencies_node.unseal(packet / "dependencies/node")


def test_two_runs_restores_project_base_runner_settings_after_stripping(tmp_path: Path) -> None:
    repo, base, _, _ = _repo(tmp_path, "vitest")
    H.write(repo, {"web/vitest.config.mjs": "export default { test: { globals: true } };\n"})
    base = H.commit(repo, "base settings")
    H.write(repo, {"web/vitest.config.mjs": "export default { test: { exclude: ['**/*'] } };\n"})
    head = H.commit(repo, "disabled settings")
    change = H.C.review_diff.read(repo, base, head)
    (repo / "web/vitest.config.mjs").unlink()
    context = H.T.ScanContext(repo, repo, tmp_path, base=base, change=change)
    H.C._invoke_two_runs(context)
    assert "globals: true" in (repo / "web/vitest.config.mjs").read_text()


@pytest.mark.skipif(os.environ.get("SAGA_TEST_LIVE_NPM") != "1", reason="opt-in (SAGA_TEST_LIVE_NPM=1): needs npm and network")
@pytest.mark.parametrize("kind,version", [("vitest", "4.1.11"), ("jest", "30.5.2")])
def test_live_stryker_in_subfolder_runs_with_packet_packages_and_ten_mutant_budget(
    tmp_path: Path, kind: str, version: str,
) -> None:
    C = H.load("review_command")
    A = H.load("review_adapters_typescript")
    N = C.review_dependencies_node
    manifest = {"name": "example", "private": True, "devDependencies": {kind: version,
        "@stryker-mutator/core": "10.0.0", f"@stryker-mutator/{kind}-runner": "10.0.0"}}
    repo, _, _ = H.make_repo(tmp_path, {"web/package.json": json.dumps(manifest),
        "web/app.js": "module.exports = (a,b) => a-b;\n"}, {"README.md": "example\n"})
    imports = "import {test, expect} from 'vitest';\nimport add from './app.js';\n" if kind == "vitest" else "const add = require('./app');\n"
    test = "test('fixed', () => expect(add(1,1)).toBe(2));\n"
    # The base config is needed by Stryker's runner; head's disabled version must not win.
    config = "vitest.config.ts" if kind == "vitest" else "jest.config.cjs"
    config_text = "export default {test:{globals:true}};\n" if kind == "vitest" else "module.exports = {testEnvironment:'node'};\n"
    H.write(repo, {f"web/{config}": config_text})
    proc = subprocess.run(["npm", "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"],
                          cwd=repo / "web", capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    base = H.commit(repo, "locked base")
    H.write(repo, {"web/app.js": "module.exports = (a,b) => {\n" +
                  "".join(f"const unused{i} = {i} + 1;\n" for i in range(12)) + "return a+b;\n};\n",
                  f"web/new.test.{'ts' if kind == 'vitest' else 'js'}": imports + test,
                  f"web/{config}": "throw Error('head config must not execute');\n"})
    head = H.commit(repo, "fix")
    packet = tmp_path / "packet"
    packet.mkdir()
    def export(dest: Path) -> bool:
        H.write(dest, {name: H.git(repo, "show", f"{head}:{name}") for name in H.git(repo, "ls-tree", "-r", "--name-only", head).splitlines()})
        return True
    home = tmp_path / "home"
    home.mkdir()
    profile = H.profile(tmp_path / "profile.json", "npm test")
    out = tmp_path / "out"
    console: list[str] = []
    statuses: list[dict[str, Any]] = []
    def run(argv: list[str], **kwargs: Any) -> Any:
        result = H.T.subprocess_runner(argv, **kwargs)
        if "run" in argv and Path(argv[0]).name == "stryker":
            console.append(result.stdout + result.stderr)
            report = Path(kwargs["cwd"]) / "reports/mutation/mutation.json"
            if report.is_file():
                statuses.extend(m for file in json.loads(report.read_text())["files"].values()
                                for m in file["mutants"])
        return result
    try:
        record = C.review_dependencies.fetch(H.T.subprocess_runner, repo, head, packet, export, base=base)
        (packet / C.review_dependencies.FILE).write_text(json.dumps(record))
        assert record["node"]["projects"][0]["state"] == "installed", record
        assert H.T.run(repo, base, head, profile, out, home,
                       adapters=[next(a for a in A.ADAPTERS if a.id == "stryker")], framework=False,
                       node_projects=N.installed_projects(packet),
                       diagnostics_directory=tmp_path / "diagnostics", runner=run) == 0
        gaps = H.read(out, "degraded.json")
        if not all(gap["reason"] in {"mutant-budget", "scanner-settings"} for gap in gaps):
            pytest.fail("\n".join(console))
        assert {f["rule"]["ref"] for f in H.read(out, "findings.json")} == {"surviving-mutant"}
        assert len([m for m in statuses if m["status"] != "Ignored"]) <= 10
        assert any(m.get("statusReason") == "saga-mutant-budget" for m in statuses)
    finally:
        N.unseal(packet / "dependencies/node")


def test_copying_node_tests_leaves_production_files_with_test_in_their_name_on_base(tmp_path: Path) -> None:
    repo, base, _, _ = _repo(tmp_path, "vitest")
    H.write(repo, {"web/latest.ts": "fixed\n"})
    head = H.commit(repo, "production name containing test")
    old = tmp_path / "base"
    H.write(old, {"web/latest.ts": "broken\n"})
    H.C._copy_tests(repo, old, H.C.review_diff.read(repo, base, head), "vitest", [])
    assert (old / "web/latest.ts").read_text() == "broken\n"
    assert (old / "web/new.test.ts").is_file()


def test_literal_coverage_script_and_package_separator_resolve_to_the_runner(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run --coverage"}}))
    assert P.test_command("npm test -- --silent", tmp_path) == (
        "vitest", ["--coverage", "--silent"], ".")


@pytest.mark.parametrize("kind", ["vitest", "jest"])
def test_node_case_ids_keep_the_real_test_file_in_shared_path_lookup(kind: str) -> None:
    assert H.C._test_path(kind, "web/new.test.ts::suite new case") == "web/new.test.ts"
