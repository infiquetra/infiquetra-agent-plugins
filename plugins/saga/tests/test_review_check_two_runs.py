"""A new test that passes on the code before the change (issue 155)."""

from __future__ import annotations

import importlib.util
import socket
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest


def _harness() -> Any:
    path = Path(__file__).resolve().parent / "review_check_harness.py"
    spec = importlib.util.spec_from_file_location("review_check_harness", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


H = _harness()

INI = "[pytest]\n"
KEEP = "def test_keep():\n    assert True\n"
APP_BASE = "def add(a, b):\n    return a - b\n"
APP_HEAD = "def add(a, b):\n    return a + b\n"
SAMPLE = (
    "import sys\n"
    "from pathlib import Path\n"
    "\n"
    "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
    "from app import add\n"
    "\n"
    "\n"
    "def test_fixed():\n"
    "    assert add(1, 1) == 2\n"
    "\n"
    "\n"
    "def test_already():\n"
    "    assert add(0, 0) == 0\n"
)
CONFTEST = "import pytest\n\n\n@pytest.fixture\ndef sample():\n    return 0\n"
SAMPLE_FIXTURE = (
    "import sys\n"
    "from pathlib import Path\n"
    "\n"
    "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
    "from app import add\n"
    "\n"
    "\n"
    "def test_fixed():\n"
    "    assert add(1, 1) == 2\n"
    "\n"
    "\n"
    "def test_already(sample):\n"
    "    assert add(sample, sample) == 0\n"
)
ALREADY = "tests/test_sample.py::test_already"
FIXED = "tests/test_sample.py::test_fixed"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sockets stay refused. The check's own processes are separate programs."""

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("scripted check tests must make no network call")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _base() -> dict[str, str]:
    return {"pytest.ini": INI, "app.py": APP_BASE, "tests/test_keep.py": KEEP}


def _head(sample: str, *, conftest: bool = False) -> dict[str, str]:
    files = {
        "pytest.ini": INI,
        "app.py": APP_HEAD,
        "tests/test_keep.py": KEEP,
        "tests/test_sample.py": sample,
    }
    if conftest:
        files["tests/conftest.py"] = CONFTEST
    return files


def _refs(output: Path) -> set[str]:
    return {str(item["rule"]["ref"]) for item in H.read(output, "findings.json")}


def _review_gaps(output: Path) -> list[dict[str, str]]:
    return [item for item in H.gaps(output) if item.get("tool") == "review-checks"]


def test_a_new_test_that_passes_before_the_change_is_a_lead_that_fixes_later(
    tmp_path: Path,
) -> None:
    """Not a block on its own: a new test that passes before the change may pin behaviour the
    change keeps. The reviewer escalates one that should check the change."""
    code, output, *_rest = H.one(tmp_path, _base(), _head(SAMPLE), "two-runs", H.PYTEST)
    assert code == 0
    H.valid(output)
    refs = _refs(output)
    assert ALREADY in refs
    assert FIXED not in refs
    found = H.outcomes_for(output, ALREADY)
    assert len(found) == 1
    assert found[0]["severity"] == "fix-later"
    assert found[0]["rule"]["row"] == "testing.test-passes-before-change"


def test_a_fixture_in_conftest_is_copied(tmp_path: Path) -> None:
    code, output, *_rest = H.one(
        tmp_path, _base(), _head(SAMPLE_FIXTURE, conftest=True), "two-runs", H.PYTEST,
    )
    assert code == 0
    H.valid(output)
    refs = _refs(output)
    assert ALREADY in refs
    assert FIXED not in refs


def test_a_builder_reason_turns_the_block_into_a_note(tmp_path: Path) -> None:
    code, first, *_rest = H.one(tmp_path, _base(), _head(SAMPLE), "two-runs", H.PYTEST)
    assert code == 0
    finding = next(
        item for item in H.read(first, "findings.json") if item["rule"]["ref"] == ALREADY
    )
    repo, base, head = H.make_repo(tmp_path / "again", _base(), _head(SAMPLE))
    record = H.builder(finding["id"], "test-passes-before-change", tmp_path / "builder.json")
    second = tmp_path / "second"
    code = H.run(
        repo, base, head, H.profile(tmp_path / "profile-again.json", H.PYTEST),
        second, tmp_path / "home-again", [H.adapter("two-runs")], builder=record,
    )
    assert code == 0
    found = H.outcomes_for(second, ALREADY)
    assert len(found) == 1
    assert found[0]["severity"] == "note"
    assert "excused" in found[0]["severity_basis"]["modifiers"]


def test_a_command_that_is_not_a_lister_is_no_test_list(tmp_path: Path) -> None:
    code, output, *_rest = H.one(
        tmp_path, {"notes.txt": "one\n"}, {"notes.txt": "two\n"}, "two-runs", "echo ok",
    )
    assert code == 0
    assert H.read(output, "findings.json") == []
    assert any(item["reason"] == "no-test-list" for item in _review_gaps(output))


def _pytest_stub(directory: Path, text: str, monkeypatch: pytest.MonkeyPatch) -> None:
    H.executable(directory / "pytest", text)
    H.prepend(monkeypatch, directory)


def test_pytest_that_exits_nonzero_is_no_test_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pytest_stub(tmp_path / "bin", "#!/bin/sh\nexit 1\n", monkeypatch)
    code, output, *_rest = H.one(
        tmp_path, {"notes.txt": "one\n"}, {"notes.txt": "two\n"}, "two-runs", "pytest -q",
    )
    assert code == 0
    assert H.read(output, "findings.json") == []
    assert any(item["reason"] == "no-test-list-default-collection" for item in _review_gaps(output))


def test_pytest_that_prints_no_node_id_is_no_test_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pytest_stub(tmp_path / "bin", "#!/bin/sh\necho 'no ids here'\nexit 0\n", monkeypatch)
    code, output, *_rest = H.one(
        tmp_path, {"notes.txt": "one\n"}, {"notes.txt": "two\n"}, "two-runs", "pytest -q",
    )
    assert code == 0
    assert H.read(output, "findings.json") == []
    assert any(item["reason"] == "no-test-list-default-collection" for item in _review_gaps(output))


def test_a_listing_timeout_is_reason_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pytest_stub(tmp_path / "bin", "#!/bin/sh\nsleep 2\nexit 0\n", monkeypatch)
    repo, base, _head = H.make_repo(tmp_path, {"notes.txt": "one\n"}, {"notes.txt": "two\n"})
    payload = H.C.two_runs(repo, base, [("none", "pytest -q")], command_timeout=0.2)
    assert payload["hits"] == []
    assert payload["gaps"] == [{
        "reason": "timeout", "row": "testing.test-passes-before-change",
    }]


def test_a_missing_pytest_is_reason_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", str(H.git_bin(tmp_path / "bin")))
    repo, base, _head = H.make_repo(tmp_path, {"notes.txt": "one\n"}, {"notes.txt": "two\n"})
    payload = H.C.two_runs(repo, base, [("none", "pytest -q")])
    assert payload["hits"] == []
    assert payload["gaps"][0]["reason"] == "missing"


def test_the_run_subcommand_records_the_check_without_a_run_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    H.install_stubs(tmp_path / "stubs")
    H.prepend(monkeypatch, tmp_path / "stubs")
    repo, base, head = H.make_repo(tmp_path, _base(), _head(SAMPLE))
    profile = H.profile(tmp_path / "profile.json", H.PYTEST)
    output = tmp_path / "cli"
    home = tmp_path / "cli-home"
    home.mkdir()
    argv = [
        sys.executable, str(H.SCRIPTS / "review_tools.py"), "run",
        "--repo", str(repo), "--base", base, "--head", head,
        "--profile", str(profile), "--output", str(output), "--home", str(home),
    ]
    assert "--builder" not in argv
    assert not any("run-record" in item for item in argv)
    proc = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stderr
    assert not (output / "review_run.json").exists()
    for name in (
        "findings.json", "measurements.json", "degraded.json",
        "outcomes.json", "where-to-look.json",
    ):
        assert (output / name).is_file()
    H.valid(output)
    assert ALREADY in _refs(output)


# A Python project whose tests import a dependency the operator's interpreter does not have.
DEP_APP_BASE = "import extdep\n\n\ndef add(a, b):\n    return a - b + extdep.ZERO\n"
DEP_APP_HEAD = "import extdep\n\n\ndef add(a, b):\n    return a + b + extdep.ZERO\n"


def _dep_files(app: str, sample: str | None = None) -> dict[str, str]:
    files = {"pytest.ini": INI, "app.py": app, "tests/test_keep.py": KEEP}
    if sample is not None:
        files["tests/test_sample.py"] = sample
    return files


def _python_env(tmp: Path) -> Path:
    """A saga-written environment over a ``site-packages`` that holds ``extdep``.

    The packet's real folder holds pytest too; here a ``.pth`` line adds this interpreter's own
    ``site-packages`` for pytest, while ``extdep`` exists only in the environment.
    """
    deps = H.load("review_dependencies")
    site = tmp / "packet-site"
    (site / "extdep").mkdir(parents=True)
    (site / "extdep" / "__init__.py").write_text("ZERO = 0\n", encoding="utf-8")
    (site / "pytest-home.pth").write_text(
        str(Path(pytest.__file__).resolve().parents[1]) + "\n", encoding="utf-8",
    )
    version = deps.interpreter_version(sys.executable)
    assert version is not None
    shim = deps.write_python_shim(
        tmp / "env", deps.PythonDependencies(site=site, version=version), sys.executable,
    )
    assert shim is not None
    return shim


@pytest.mark.parametrize("command", [
    "pytest -q",
    "py.test",
    "/usr/local/bin/pytest -q",
    "python -m pytest -q",
    "python3 -m pytest -q",
    "python3.12 -m pytest -q",
    f"{sys.executable} -m pytest -q",
    "uv run pytest -q",
    "uv run --no-sync pytest -q",
    "uv run --no-sync --with pytest-cov --group test python -m pytest -q",
    "uv run -- pytest -q",
    "bash -c 'python -m pytest -q'",
    "bash -lc 'uv run --no-sync pytest -q tests'",
    "sh -c \"python3 -m pytest -k 'a or b'\"",
    "/bin/bash -e -c 'pytest -q'",
    ".venv/bin/python -m pytest -q",
    "PYTHONPATH=tests python -m pytest -q",
    "bash -c 'FOO=1 python -m pytest'",
    "bash -c 'PYTHONPATH=tests .venv/bin/python -m pytest -q \"$@\"' bash",
    "bash -c 'pytest -q $@' runner",
])
def test_pytest_commands_are_recognised_behind_their_launchers(command: str) -> None:
    classified = H.C._classify(command)
    assert classified is not None
    kind, tokens, _assigned = classified
    assert kind == "pytest"
    assert Path(tokens[0]).name not in {"bash", "sh"}
    assert {"pytest", "py.test"} & {Path(token).name for token in tokens}


@pytest.mark.parametrize("command", [
    "echo ok",
    "make test",
    "tox -e pytest",
    "uv run tox -e pytest",
    "uv run mystery pytest",
    "python -c pytest",
    "bash -c 'cd tests && python -m pytest'",
    "bash -c 'python -m pytest $ARGS'",
    "bash -c 'python -m pytest tests/*'",
    "bash -c 'PATH=/tmp python -m pytest'",
    "bash -c 'PYTHONPATH=$HOME python -m pytest'",
    "PYTHONPATH=~/x pytest",
    "bash -c 'python -m pytest' name extra",
    "bash -c 'make test'",
    "bash --norc -c 'pytest'",
    "zsh -c 'pytest'",
    "pytest 'unclosed",
])
def test_commands_that_cannot_be_read_safely_stay_refused(command: str) -> None:
    assert H.C._classify(command) is None


def test_a_shell_wrapper_runs_its_inner_command_with_the_listing_options() -> None:
    classified = H.C._classify("bash -c 'uv run --no-sync python -m pytest -q tests'")
    assert classified == ("pytest", [
        "uv", "run", "--no-sync", "python", "-m", "pytest", "-q", "tests",
    ], {})
    kind, tokens, _assigned = classified
    assert H.C._list_argv(kind, tokens)[-1] == "--collect-only"


def test_with_a_python_environment_pytest_runs_with_its_interpreter(tmp_path: Path) -> None:
    env = tmp_path / "env"
    classified = H.C._classify("bash -c 'uv run --no-sync pytest -q tests'", env)
    assert classified == (
        "pytest", [str(env / "bin" / "python3"), "-m", "pytest", "-q", "tests"], {},
    )
    assert H.C._classify("cargo test", env) == ("cargo", ["cargo", "test"], {})


def test_a_shell_command_s_assignments_and_passed_words_are_kept(tmp_path: Path) -> None:
    """``"$@"`` with a ``$0`` name passes the words after it; a project ``.venv`` interpreter is
    replaced by the packet environment's, since the review's checkout has no ``.venv``."""
    env = tmp_path / "env"
    command = (
        "bash -c 'PYTHONPATH=tests .venv/bin/python -m pytest -q --import-mode=importlib "
        "\"$@\"' bash -x"
    )
    assert H.C._classify(command) == (
        "pytest", [".venv/bin/python", "-m", "pytest", "-q", "--import-mode=importlib", "-x"],
        {"PYTHONPATH": "tests"},
    )
    assert H.C._classify(command, env) == (
        "pytest",
        [str(env / "bin" / "python3"), "-m", "pytest", "-q", "--import-mode=importlib", "-x"],
        {"PYTHONPATH": "tests"},
    )


def test_tests_that_import_a_locked_dependency_need_the_python_environment(
    tmp_path: Path,
) -> None:
    repo, base, _head = H.make_repo(
        tmp_path, _dep_files(DEP_APP_BASE), _dep_files(DEP_APP_HEAD, SAMPLE),
    )
    # The command a uv project's profile names. Without the packet's environment the tests
    # cannot import ``extdep``, so nothing can be listed.
    command = "uv run --no-sync pytest -q"
    without = H.C.two_runs(repo, base, [("python", command)])
    assert without["hits"] == []
    assert without["gaps"] and without["gaps"][0]["row"] == "testing.test-passes-before-change"
    shim = _python_env(tmp_path)
    payload = H.C.two_runs(repo, base, [("python", command)], python_env=shim)
    assert payload["gaps"] == []
    assert [hit["anchor"] for hit in payload["hits"]] == [ALREADY]


def test_the_runner_hands_two_runs_the_python_environment(tmp_path: Path) -> None:
    repo, base, head = H.make_repo(
        tmp_path, _dep_files(DEP_APP_BASE), _dep_files(DEP_APP_HEAD, SAMPLE),
    )
    shim = _python_env(tmp_path)
    output = tmp_path / "out"
    home = tmp_path / "home"
    home.mkdir()
    code = H.T.run(
        repo, base, head, H.profile(tmp_path / "profile.json", "uv run --no-sync pytest -q"),
        output, home=home, adapters=[H.adapter("two-runs")], framework=False, python_env=shim,
    )
    assert code == 0
    assert _review_gaps(output) == []
    assert ALREADY in _refs(output)


def test_a_failed_old_version_checkout_is_a_gap_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, base, _sha = H.make_repo(tmp_path, _base(), _head(SAMPLE))

    @contextmanager
    def refuse(_repo: Path, _revision: str) -> Iterator[Path]:
        raise RuntimeError("git worktree add failed")
        yield _repo  # pragma: no cover - never reached

    monkeypatch.setattr(H.C, "_detached", refuse)
    payload = H.C.two_runs(repo, base, [("python", H.PYTEST)])
    assert payload == {"hits": [], "where_to_look": [], "gaps": [{
        "reason": "no-test-list", "row": "testing.test-passes-before-change",
    }]}


HELPER = "ZERO = 0\n"
SAMPLE_HELPER = (
    "import helpers\n"
    "from app import add\n"
    "\n"
    "\n"
    "def test_fixed():\n"
    "    assert add(1, 1) == 2\n"
    "\n"
    "\n"
    "def test_already():\n"
    "    assert add(helpers.ZERO, helpers.ZERO) == 0\n"
)


def test_a_project_venv_command_with_a_pythonpath_runs_in_the_python_environment(
    tmp_path: Path,
) -> None:
    """A profile that names the project's own ``.venv`` interpreter and sets ``PYTHONPATH`` in a
    ``bash -c`` wrapper. The review's checkout has no ``.venv``; the packet's environment stands
    in for it, and the assignment still reaches the tests."""
    base_files = {**_dep_files(DEP_APP_BASE), "tests/helpers.py": HELPER}
    head_files = {**_dep_files(DEP_APP_HEAD, SAMPLE_HELPER), "tests/helpers.py": HELPER}
    repo, base, _sha = H.make_repo(tmp_path, base_files, head_files)
    command = (
        "bash -c 'PYTHONPATH=tests .venv/bin/python -m pytest -q --import-mode=importlib "
        "\"$@\"' bash"
    )
    shim = _python_env(tmp_path)
    payload = H.C.two_runs(repo, base, [("python", command)], python_env=shim)
    assert payload["gaps"] == []
    assert [hit["anchor"] for hit in payload["hits"]] == [ALREADY]


def test_a_failed_listing_keeps_its_output_s_end_in_the_diagnostics_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    lines = "".join(f"echo line-{number} >&2\n" for number in range(60))
    _pytest_stub(tmp_path / "bin", f"#!/bin/sh\necho out-line\n{lines}exit 2\n", monkeypatch)
    repo, base, _sha = H.make_repo(tmp_path, {"notes.txt": "one\n"}, {"notes.txt": "two\n"})
    diagnostics = tmp_path / "diagnostics"
    payload = H.C.two_runs(repo, base, [("none", "pytest -q")], diagnostics=diagnostics)
    # The change touched no test file, so the default collection ran, and the reason says so.
    assert payload["gaps"][0]["reason"] == "no-test-list-default-collection"
    [tail] = list(diagnostics.glob("two-runs-head-listing-*/tail.txt"))
    text = tail.read_text(encoding="utf-8")
    assert "exit code: 2" in text and "out-line" in text
    assert "line-59" in text and "line-20" in text and "line-19\n" not in text
    assert oct(tail.stat().st_mode & 0o777) == "0o600"


def test_a_profile_glob_the_shell_never_expanded_does_not_stop_the_check(tmp_path: Path) -> None:
    """A committed profile command such as ``python3 -m pytest plugins/*/tests`` runs without a
    shell, so pytest would get the glob literally. Two-runs names the change's own test files
    instead, keeping the command's options."""
    repo, base, _sha = H.make_repo(tmp_path, _base(), _head(SAMPLE))
    command = f"{sys.executable} -m pytest nowhere/*/tests -q -p no:cacheprovider"
    payload = H.C.two_runs(repo, base, [("python", command)])
    assert payload["gaps"] == []
    assert [hit["anchor"] for hit in payload["hits"]] == [ALREADY]


def test_an_edited_test_file_is_listed_on_both_versions(tmp_path: Path) -> None:
    base_files = {**_base(), "tests/test_sample.py": SAMPLE.split("def test_already")[0]}
    repo, base, _sha = H.make_repo(tmp_path, base_files, _head(SAMPLE))
    payload = H.C.two_runs(repo, base, [("python", H.PYTEST)])
    assert payload["gaps"] == []
    assert [hit["anchor"] for hit in payload["hits"]] == [ALREADY]


def test_pytest_options_keep_values_and_drop_paths() -> None:
    options = H.T.pytest_options([
        "plugins/*/tests", "-q", "-k", "not slow", "--import-mode=importlib", "-p",
        "no:randomly", "tests/test_x.py::test_y", "-x", "--", "after",
    ])
    assert options == [
        "-q", "-k", "not slow", "--import-mode=importlib", "-p", "no:randomly", "-x",
    ]


def test_globs_expand_relative_to_the_project_as_a_shell_would(tmp_path: Path) -> None:
    for name in ("b", "a"):
        (tmp_path / "plugins" / name / "tests").mkdir(parents=True)
    assert H.T.expand_globs(["-q", "plugins/*/tests", "none/*/x", "plain"], tmp_path) == [
        "-q", "plugins/a/tests", "plugins/b/tests", "none/*/x", "plain",
    ]


def test_a_copied_test_file_that_cannot_load_on_the_old_version_does_not_stop_the_others(
    tmp_path: Path,
) -> None:
    """On the old version a copied test file may import a module only the change adds. pytest
    then cannot collect it; its tests do not pass there, and the other files still run."""
    needs_new = "from newmod import VALUE\n\n\ndef test_new():\n    assert VALUE == 1\n"
    head_files = {**_head(SAMPLE), "newmod.py": "VALUE = 1\n", "tests/test_new.py": needs_new}
    repo, base, _sha = H.make_repo(tmp_path, _base(), head_files)
    payload = H.C.two_runs(repo, base, [("python", H.PYTEST)])
    assert payload["gaps"] == []
    assert [hit["anchor"] for hit in payload["hits"]] == [ALREADY]
