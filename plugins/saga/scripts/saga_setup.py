#!/usr/bin/env python3
"""Check the machine and the repository for /saga:setup (issue 150).

``survey`` is read-only apart from the machine record under the home directory.
``write`` updates ``.saga-profile.json``. ``install`` and ``step`` run only the
command the operator named. A run calls the library and does not install, write,
or start the live sandbox probe.

The runner is injected. Tests pass it, the environment, and ``--home``. Nothing
in this module prints an environment value.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess  # nosec B404
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import functional_environment  # noqa: E402
import qa_strategies  # noqa: E402
import review_formula  # noqa: E402
import review_tools  # noqa: E402

SURVEY_SCHEMA = "setup_survey.v1"
MACHINE_SCHEMA = "machine_record.v1"
EXTENSIONS_SCHEMA = "setup_extensions.v1"
PROFILE_SCHEMA = "repository_profile.v1"
QA_PROFILE_SCHEMA = "qa_profile.v1"
NOT_RECORDED = "not-recorded"
SUGGESTION = "Run /saga:setup to check the tools on this machine and the repository."

REFERENCES = Path(__file__).resolve().parent.parent / "references"
EXTENSIONS_PATH = REFERENCES / "setup-extensions.yaml"
LAUNCH_PATH = REFERENCES / "targeted-reviewer-launch.json"
QA_SCHEMA_PATH = REFERENCES / "qa-profile.schema.json"
PROFILE_NAME = functional_environment.PROFILE_FILENAME

CREDENTIAL_NAMES = (
    "TYPESAFE_API_KEY",
    "SAGA_LANGFUSE_PUBLIC_KEY",
    "SAGA_LANGFUSE_SECRET_KEY",
    "SAGA_LANGFUSE_HOST",
)
SKIP_DIRS = frozenset(
    {".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__", ".saga"}
)
RESERVED_PROFILE_KEYS = frozenset(
    {
        "schema",
        "repo",
        "concurrency_allocation",
        "nonproduction_destination",
        "main_consumed_directly",
        "mechanical_tool_baseline",
        "preflight_checks",
        "languages",
        "visibility",
        "review_tools",
        "qa",
        "functional_test_environment",
        "functional_test_waiver",
        "branch_preview",
        "branch_preview_command",
    }
)
_SHEBANG = re.compile(r"^#!.*\b(?:sh|bash|zsh)\b")
_VERSION = review_tools._VERSION
Runner = Callable[..., Any]


class SetupError(Exception):
    """A refusal before any install or profile write. The command exits 2."""


def production_runner(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    """One subprocess, ``shell`` false. The child receives ``env`` and nothing is copied out."""
    return subprocess.run(  # nosec B603 — argument vector, shell false
        [str(part) for part in argv],
        cwd=None if cwd is None else str(cwd),
        env=None if env is None else dict(env),
        timeout=timeout,
        capture_output=True,
        text=True,
        check=False,
        shell=False,
    )


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _real_version(value: Any) -> str | None:
    if isinstance(value, str) and value and value != NOT_RECORDED:
        return value
    return None


def _at_least(found: str, minimum: str) -> bool:
    left = [int(part) for part in found.split(".")]
    right = [int(part) for part in minimum.split(".")]
    width = max(len(left), len(right))
    left.extend([0] * (width - len(left)))
    right.extend([0] * (width - len(right)))
    return tuple(left) >= tuple(right)


def _shebang_shell(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            line = handle.readline(200)
    except OSError:
        return False
    text = line.decode("utf-8", errors="ignore")
    return _SHEBANG.search(text) is not None


def detect_languages(root: Path) -> list[str]:
    """Formula languages present in *root*, in ``review_formula.LANGUAGES`` order.

    ``cloudformation`` is not detected. ``cdk.json`` does not add Python.
    """
    found: set[str] = set()
    base = Path(root)
    for directory, dirnames, filenames in os.walk(base, followlinks=False):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        for name in filenames:
            path = Path(directory) / name
            relative = path.relative_to(base).as_posix()
            suffix = path.suffix.lower()
            if name == "Cargo.toml":
                found.add("rust")
            if suffix == ".py":
                found.add("python")
            elif suffix in {".ts", ".tsx", ".js", ".jsx"}:
                found.add("typescript")
            elif suffix == ".dart":
                found.add("dart")
            elif suffix == ".rs":
                found.add("rust")
            elif suffix == ".swift":
                found.add("swift")
            elif suffix == ".md":
                found.add("markdown")
            elif suffix == ".sh":
                found.add("shell")
            elif suffix == "" and _shebang_shell(path):
                found.add("shell")
            if suffix in {".yml", ".yaml"} and (
                relative.startswith(".github/workflows/")
                or "/.github/workflows/" in f"/{relative}"
            ):
                found.add("github-workflows")
    return [language for language in review_formula.LANGUAGES if language in found]


def load_extensions(path: Path | None = None) -> dict[str, Any]:
    """The step and question registry. A reserved ``profile_key`` is refused here."""
    target = Path(path) if path is not None else EXTENSIONS_PATH
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SetupError(f"could not read {target}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != EXTENSIONS_SCHEMA:
        raise SetupError(f"{target}: schema must be {EXTENSIONS_SCHEMA}")
    steps = data.get("steps") if data.get("steps") is not None else []
    questions = data.get("questions") if data.get("questions") is not None else []
    if not isinstance(steps, list) or not isinstance(questions, list):
        raise SetupError(f"{target}: steps and questions must be lists")
    for question in questions:
        if not isinstance(question, dict):
            raise SetupError(f"{target}: a question must be an object")
        profile_key = question.get("profile_key")
        if profile_key in RESERVED_PROFILE_KEYS:
            raise SetupError(f"reserved profile key {profile_key}")
    return {"steps": steps, "questions": questions}


def machine_path(home: Path) -> Path:
    """The machine record's path under *home*."""
    return Path(home) / ".saga" / "machine.json"


def require_readable_machine(home: Path) -> dict[str, Any] | None:
    """The machine record, or ``None`` when no file exists yet.

    Raises ``SetupError`` when the file exists but cannot be read as a
    machine record: the offer verbs must never mistake a corrupt file for
    setup never offered, and must never replace what they could not read.
    """
    record = load_machine(home)
    if record is None and machine_path(home).is_file():
        raise SetupError(f"{machine_path(home)} exists but cannot be read as a machine record")
    return record


def offer_status(home: Path) -> dict[str, Any]:
    """The machine record's ``ran`` and ``offered``, without writing anything.

    A missing file reads both false; a file that exists but cannot be parsed
    raises ``SetupError`` through :func:`require_readable_machine`.
    """
    record = require_readable_machine(home)
    return {
        "schema": MACHINE_SCHEMA,
        "ran": bool(record.get("ran")) if record else False,
        "offered": bool(record.get("offered")) if record else False,
    }


def load_machine(home: Path) -> dict[str, Any] | None:
    path = machine_path(home)
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded


def write_machine(home: Path, record: dict[str, Any]) -> Path:
    """Write ``<home>/.saga/machine.json``. The directory is mode 0700 and the file 0600."""
    directory = review_tools._saga(Path(home))
    directory.chmod(0o700)
    path = directory / "machine.json"
    text = json.dumps(record, indent=2) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(descriptor, text.encode("utf-8"))
    finally:
        os.close(descriptor)
    path.chmod(0o600)
    directory.chmod(0o700)
    return path


def record_survey(home: Path, survey: Mapping[str, Any]) -> Path:
    """Store *survey* without its questions and set ``ran``. ``offered`` is left as it was."""
    previous = load_machine(home)
    offered = False
    if isinstance(previous, dict) and previous.get("offered") is True:
        offered = True
    stored = {key: value for key, value in survey.items() if key != "questions"}
    record = {
        "schema": MACHINE_SCHEMA,
        "ran": True,
        "offered": offered,
        "survey": stored,
        "updated_at": _now(),
    }
    return write_machine(home, record)


def record_offer(home: Path) -> Path:
    """Set ``offered``. A missing file records ``ran`` false and does not invent a survey."""
    previous = load_machine(home)
    if previous is None:
        record: dict[str, Any] = {
            "schema": MACHINE_SCHEMA,
            "ran": False,
            "offered": True,
            "survey": None,
            "updated_at": _now(),
        }
    else:
        record = dict(previous)
        record["schema"] = MACHINE_SCHEMA
        record["offered"] = True
        record["updated_at"] = _now()
        if "ran" not in record:
            record["ran"] = False
    return write_machine(home, record)


def _tool_rows(path: Path | None) -> list[dict[str, Any]]:
    return review_tools.load_tool_list(path)


def _saga_owned(row: Mapping[str, Any]) -> bool:
    return row.get("catalogue") is False or row.get("lens") == "saga"


def _selected(row: Mapping[str, Any], detected: set[str]) -> bool:
    if _saga_owned(row):
        return True
    languages = row.get("languages") or []
    if not isinstance(languages, list):
        return False
    if "*" in languages:
        return True
    return bool(set(languages) & detected)


def _profile_object(repo: Path) -> dict[str, Any]:
    path = Path(repo) / PROFILE_NAME
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SetupError(f"{path} is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise SetupError(f"could not read {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise SetupError(f"{path} does not hold a JSON object")
    return loaded


def _pins_block(profile: Mapping[str, Any]) -> dict[str, Any]:
    block = profile.get("review_tools")
    if not isinstance(block, dict):
        return {}
    pins = block.get("pins")
    if not isinstance(pins, dict):
        return {}
    return pins


def _recorded_pin(profile: Mapping[str, Any], tool: str) -> str | None:
    entry = _pins_block(profile).get(tool)
    if isinstance(entry, str):
        return _real_version(entry)
    if isinstance(entry, dict):
        return _real_version(entry.get("version"))
    return None


def _display_pin(row: Mapping[str, Any], profile: Mapping[str, Any]) -> str:
    tool = str(row.get("tool") or "")
    if tool:
        recorded = _recorded_pin(profile, tool)
        if recorded:
            return recorded
    if row.get("version_mode") == "minimum" and row.get("minimum_version"):
        return str(row["minimum_version"])
    return str(row.get("default_version") or NOT_RECORDED)


def _comparison_pin(row: Mapping[str, Any], profile: Mapping[str, Any]) -> str | None:
    tool = str(row.get("tool") or "")
    if tool:
        recorded = _recorded_pin(profile, tool)
        if recorded:
            return recorded
    return _real_version(row.get("default_version"))


def _classify(row: Mapping[str, Any], version: str | None, profile: Mapping[str, Any]) -> str:
    if version is None:
        return "missing"
    mode = row.get("version_mode") or "exact"
    if mode == "any":
        return "installed"
    if mode == "minimum":
        floor = str(row.get("minimum_version") or "0")
        return "installed" if _at_least(version, floor) else "wrong-version"
    pin = _comparison_pin(row, profile)
    if pin is None:
        return "installed"
    return "installed" if version == pin else "wrong-version"


def _call(
    runner: Runner,
    argv: Sequence[str],
    *,
    cwd: Path | None,
    env: Mapping[str, str] | None,
    timeout: int,
) -> Any:
    return runner(list(argv), cwd=cwd, env=env, timeout=timeout)


def _probe_row(
    row: Mapping[str, Any],
    *,
    runner: Runner,
    env: Mapping[str, str] | None,
    cwd: Path,
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    identity = str(row.get("id") or "")
    tool = str(row.get("tool") or "")
    base = {
        "id": identity,
        "tool": tool,
        "lens": row.get("lens"),
        "pinned_version": _display_pin(row, profile),
        "status": "installed",
        "version": None,
        "auth": "not-applicable",
        # The setup pane's checkbox reads these (issue 165): whether the row
        # has an install command, and the sentence shown when it has not.
        "has_install": bool(row.get("install_argv")),
        "install": row.get("install"),
    }
    if not tool:
        return base
    argv = [tool, *[str(part) for part in (row.get("version_args") or ["--version"])]]
    timeout = int(row.get("timeout_seconds") or 30)
    try:
        result = _call(runner, argv, cwd=cwd, env=env, timeout=timeout)
    except FileNotFoundError:
        base["status"] = "missing"
        return base
    except subprocess.TimeoutExpired:
        base["status"] = "missing"
        return base
    text = f"{getattr(result, 'stdout', '') or ''}\n{getattr(result, 'stderr', '') or ''}"
    found = _VERSION.search(text)
    if found is None:
        base["status"] = "missing"
        return base
    version = found.group(0)
    status = _classify(row, version, profile)
    base["version"] = version
    base["status"] = status
    if tool == "gh" and status == "installed":
        try:
            auth = _call(
                runner, ["gh", "auth", "status"], cwd=cwd, env=env, timeout=timeout
            )
            signed_in = int(getattr(auth, "returncode", 1)) == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            signed_in = False
        if signed_in:
            base["auth"] = "signed-in"
        else:
            base["status"] = "needs-sign-in"
            base["auth"] = "needs-sign-in"
    return base


def _credentials(env: Mapping[str, str] | None) -> list[dict[str, str]]:
    rows = []
    for name in CREDENTIAL_NAMES:
        value = None if env is None else env.get(name)
        state = "present" if isinstance(value, str) and value != "" else "absent"
        rows.append({"name": name, "state": state})
    return rows


def _visibility(
    repo: Path, runner: Runner, env: Mapping[str, str] | None
) -> str | None:
    try:
        result = _call(
            runner,
            ["gh", "repo", "view", "--json", "visibility"],
            cwd=repo,
            env=env,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if int(getattr(result, "returncode", 1)) != 0:
        return None
    try:
        payload = json.loads(getattr(result, "stdout", "") or "")
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("visibility")
    if value == "PUBLIC":
        return "public"
    if value in {"PRIVATE", "INTERNAL"}:
        return "private"
    return None


def _claude_resolves(runner: Runner, env: Mapping[str, str] | None) -> bool:
    try:
        _call(runner, ["claude", "--version"], cwd=None, env=env, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return True


def _stored_sandbox(home: Path | None) -> dict[str, Any] | None:
    if home is None:
        return None
    record = load_machine(home)
    if not isinstance(record, dict):
        return None
    survey = record.get("survey")
    if not isinstance(survey, dict):
        return None
    sandbox = survey.get("sandbox")
    if not isinstance(sandbox, dict) or "reproduction" not in sandbox:
        return None
    return sandbox


def _unavailable(reason: str) -> dict[str, Any]:
    return {"available": False, "reproduction": "unavailable", "reason": reason}


def _launch(model_override: str | None) -> tuple[str, str | None] | None:
    try:
        data = json.loads(LAUNCH_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("vendor") != "claude":
        return None
    model = model_override or data.get("model")
    if not isinstance(model, str) or not model:
        return None
    effort = data.get("effort")
    if not isinstance(effort, str):
        effort = None
    return model, effort


def _live_probe(model: str, effort: str | None) -> int:
    scripts = (
        Path(__file__).resolve().parents[2]
        / "agent-launcher"
        / "skills"
        / "agent-launcher"
        / "scripts"
    )
    if not (scripts / "launcher.py").is_file():
        raise ImportError(str(scripts))
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import launcher  # noqa: E402

    _verdicts, code = launcher.reviewer_probe("claude", model, effort)
    return int(code)


def probe_reproduction_sandbox(session: Any, model: str, effort: str | None) -> dict[str, Any]:
    """Run C8's probe. A missing launch file or a failed probe is unavailable, not a crash."""
    try:
        if session is not None:
            _verdicts, code = session("claude", model, effort)
        else:
            code = _live_probe(model, effort)
    except Exception:  # noqa: BLE001 — a failed probe is a survey fact, not an abort
        return _unavailable("probe-unavailable")
    if int(code) != 0:
        return _unavailable("probe-unavailable")
    return {"available": True, "reproduction": "available", "reason": None}


def _sandbox(
    *,
    probe_live: bool,
    session: Any,
    model_override: str | None,
    runner: Runner,
    env: Mapping[str, str] | None,
    home: Path | None,
) -> dict[str, Any]:
    if probe_live:
        launched = _launch(model_override)
        if launched is None:
            return _unavailable("probe-unavailable")
        model, effort = launched
        return probe_reproduction_sandbox(session, model, effort)
    stored = _stored_sandbox(home)
    if stored is None:
        return _unavailable("not-probed")
    if not _claude_resolves(runner, env):
        if stored.get("available") is True or stored.get("reproduction") == "available":
            return _unavailable("probe-unavailable")
        return _unavailable(str(stored.get("reason") or "not-probed"))
    return {
        "available": bool(stored.get("available")),
        "reproduction": stored.get("reproduction"),
        "reason": stored.get("reason"),
    }


def _step_status(
    step: Mapping[str, Any],
    runner: Runner,
    env: Mapping[str, str] | None,
    cwd: Path,
) -> dict[str, Any]:
    argv = step.get("done")
    done = False
    if isinstance(argv, list) and argv:
        try:
            result = _call(runner, argv, cwd=cwd, env=env, timeout=30)
            done = int(getattr(result, "returncode", 1)) == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            done = False
    return {"name": step.get("name"), "summary": step.get("summary"), "done": done}


def _functional_settled(profile: Mapping[str, Any]) -> bool:
    try:
        resolved = functional_environment.resolve(dict(profile))
    except functional_environment.DeclarationError:
        return False
    if not isinstance(resolved, dict):
        return False
    return resolved.get("mode") in functional_environment.ANSWERED_MODES


def _qa_schema() -> dict[str, Any]:
    loaded = json.loads(QA_SCHEMA_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise SetupError(f"{QA_SCHEMA_PATH} is not an object")
    return loaded


def hand_check_qa(block: Any) -> None:
    """Refuse a ``qa`` block the schema's required shapes reject. Does not import jsonschema."""
    schema = _qa_schema()
    if not isinstance(block, dict):
        raise SetupError("qa must be an object")
    allowed = set(schema.get("properties") or {})
    unknown = sorted(set(block) - allowed)
    if unknown:
        raise SetupError(f"qa has unknown keys: {', '.join(unknown)}")
    if block.get("schema") != QA_PROFILE_SCHEMA:
        raise SetupError(f"qa schema must be {QA_PROFILE_SCHEMA}")
    ceiling_schema = (schema.get("properties") or {}).get("ceiling") or {}
    ceiling = block.get("ceiling")
    if not isinstance(ceiling, dict):
        raise SetupError("qa ceiling must be an object")
    ceiling_keys = set((ceiling_schema.get("properties") or {}))
    required = set(ceiling_schema.get("required") or [])
    missing_ceiling = sorted(required - set(ceiling))
    extra_ceiling = sorted(set(ceiling) - ceiling_keys)
    if missing_ceiling or extra_ceiling:
        detail = ", ".join(missing_ceiling or extra_ceiling)
        raise SetupError(f"qa ceiling must have both numbers and no other key ({detail})")
    duration = ceiling.get("max_duration_seconds")
    cost = ceiling.get("max_direct_cost")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration <= 0:
        raise SetupError("qa ceiling max_duration_seconds must be greater than 0")
    if isinstance(cost, bool) or not isinstance(cost, (int, float)) or cost < 0:
        raise SetupError("qa ceiling max_direct_cost must be at least 0")
    strategies = block.get("strategies")
    if not isinstance(strategies, dict) or not strategies:
        raise SetupError("qa strategies must be a non-empty object")
    strategy_schema = (schema.get("properties") or {}).get("strategies") or {}
    entry_schema = strategy_schema.get("additionalProperties") or {}
    entry_keys = set((entry_schema.get("properties") or {}))
    any_required = False
    for name, entry in strategies.items():
        if not isinstance(entry, dict):
            raise SetupError(f"qa strategy {name} must be an object")
        extra = sorted(set(entry) - entry_keys)
        if extra:
            raise SetupError(f"qa strategy {name} has unknown keys: {', '.join(extra)}")
        required_flag = entry.get("required")
        if not isinstance(required_flag, bool):
            raise SetupError(f"qa strategy {name} required must be a boolean")
        any_required = any_required or required_flag
    if not any_required:
        raise SetupError("qa needs at least one required strategy")
    environment = block.get("environment")
    if environment is not None:
        env_schema = (schema.get("properties") or {}).get("environment") or {}
        env_keys = set((env_schema.get("properties") or {}))
        if not isinstance(environment, dict) or set(environment) - env_keys:
            raise SetupError("qa environment has an unknown key")
    with tempfile.TemporaryDirectory(prefix="saga-qa-") as directory:
        root = Path(directory)
        (root / PROFILE_NAME).write_text(
            json.dumps({"schema": PROFILE_SCHEMA, "qa": block}) + "\n",
            encoding="utf-8",
        )
        try:
            qa_strategies.load_profile(root)
        except qa_strategies.ProfileRefusalError as exc:
            raise SetupError(str(exc)) from exc


def _qa_settled(profile: Mapping[str, Any]) -> bool:
    block = profile.get("qa")
    if not isinstance(block, dict):
        return False
    try:
        hand_check_qa(block)
    except SetupError:
        return False
    return True


def _has_value(profile: Mapping[str, Any], key: Any) -> bool:
    if not isinstance(key, str) or key not in profile:
        return False
    value = profile.get(key)
    return value is not None and value != ""


def questions_for(
    survey: Mapping[str, Any],
    profile: Mapping[str, Any],
    extensions: Mapping[str, Any],
) -> list[dict[str, str]]:
    """What ``write`` still needs. Languages are detected and are not a question."""
    questions: list[dict[str, str]] = []
    if not _functional_settled(profile):
        questions.append(
            {
                "key": functional_environment.PROFILE_KEY,
                "prompt": (
                    "How is this repository functionally tested before review? "
                    "Answer with a functional_test_environment object, or a "
                    "functional_test_waiver object."
                ),
            }
        )
    if not _qa_settled(profile):
        questions.append(
            {
                "key": "qa",
                "prompt": (
                    "What qa block should this repository record? Include schema "
                    "qa_profile.v1, strategies, and a ceiling with both numbers."
                ),
            }
        )
    known = survey.get("visibility") in {"public", "private"}
    recorded = profile.get("visibility") in {"public", "private"}
    if not known and not recorded:
        questions.append(
            {"key": "visibility", "prompt": "Is this repository public or private?"}
        )
    for question in extensions.get("questions") or []:
        if not isinstance(question, dict):
            continue
        if _has_value(profile, question.get("profile_key")):
            continue
        questions.append(
            {"key": str(question.get("key")), "prompt": str(question.get("prompt") or "")}
        )
    return questions


def collect(
    repo: Path,
    *,
    runner: Runner,
    env: Mapping[str, str] | None,
    home: Path | None = None,
    tools_path: Path | None = None,
    extensions_path: Path | None = None,
    probe_live: bool = False,
    session: Any = None,
    model_override: str | None = None,
    persist: bool = False,
) -> dict[str, Any]:
    """Build one ``setup_survey.v1`` document. ``persist`` writes the machine record."""
    extensions = load_extensions(extensions_path)
    root = Path(repo)
    languages = detect_languages(root)
    detected = set(languages)
    profile = _profile_object(root)
    tools = [
        _probe_row(row, runner=runner, env=env, cwd=root, profile=profile)
        for row in _tool_rows(tools_path)
        if _selected(row, detected)
    ]
    document = {
        "schema": SURVEY_SCHEMA,
        "tools": tools,
        "credentials": _credentials(env),
        "sandbox": _sandbox(
            probe_live=probe_live,
            session=session,
            model_override=model_override,
            runner=runner,
            env=env,
            home=home,
        ),
        "steps": [
            _step_status(step, runner, env, root)
            for step in extensions["steps"]
            if isinstance(step, dict)
        ],
        "languages": languages,
        "visibility": _visibility(root, runner, env),
        "langfuse_queue": langfuse_queue(home),
        "questions": [],
    }
    document["questions"] = questions_for(document, profile, extensions)
    if persist:
        if home is None:
            raise SetupError("survey needs a home directory to record")
        record_survey(home, document)
    return document


def langfuse_queue(home: Path | None) -> dict[str, Any]:
    """How many Langfuse posts wait in ``<home>/.saga/langfuse-queue``, by reason (issue 166)."""
    if home is None:
        return {"waiting": 0, "reasons": {}}
    try:
        import review_trace  # noqa: PLC0415 - only setup's survey needs it

        return review_trace.queue_status(Path(home))
    except Exception:  # noqa: BLE001 - an unreadable queue is reported, never fatal to setup
        return {"waiting": 0, "reasons": {"unreadable": 1}}


def notice_for(survey: Mapping[str, Any]) -> dict[str, Any]:
    """The one admission notice. Every status other than ``installed`` is named."""
    missing = [
        str(tool["id"])
        for tool in survey.get("tools") or []
        if isinstance(tool, dict) and tool.get("status") != "installed"
    ]
    sandbox = survey.get("sandbox") if isinstance(survey.get("sandbox"), dict) else {}
    unavailable = sandbox.get("reproduction") != "available"
    if missing and unavailable:
        text = f"Missing {', '.join(missing)} and sandbox. Run /saga:setup."
    elif missing:
        text = f"Missing {', '.join(missing)}. Run /saga:setup."
    elif unavailable:
        text = "Missing sandbox. Run /saga:setup."
    else:
        text = ""
    queue = survey.get("langfuse_queue") if isinstance(survey.get("langfuse_queue"), dict) else {}
    waiting = queue.get("waiting") if isinstance(queue.get("waiting"), int) else 0
    if waiting:
        text = (text + " " if text else "") + f"Langfuse posts waiting: {waiting}."
    return {
        "text": text,
        "missing_tools": missing,
        "sandbox_unavailable": unavailable,
        "langfuse_waiting": waiting,
    }


def render_text(document: Mapping[str, Any]) -> str:
    """The same facts as the JSON document, then the questions numbered from 1."""
    lines = ["Tools", ""]
    header = f"{'id':<24} {'lens':<28} {'status':<16} {'version':<16} pin"
    lines.append(header)
    for tool in document.get("tools") or []:
        version = "-" if tool.get("version") is None else str(tool.get("version"))
        lines.append(
            f"{str(tool.get('id')):<24} {str(tool.get('lens')):<28} "
            f"{str(tool.get('status')):<16} {version:<16} {tool.get('pinned_version')}"
        )
    lines.extend(["", "Credentials"])
    for item in document.get("credentials") or []:
        lines.append(f"  {item.get('name')}: {item.get('state')}")
    sandbox = document.get("sandbox") or {}
    reason = sandbox.get("reason")
    suffix = f" ({reason})" if reason else ""
    lines.extend(
        [
            "",
            f"Sandbox: reproduction {sandbox.get('reproduction')}{suffix}",
            "Languages: " + ", ".join(document.get("languages") or []),
            "Visibility: " + (document.get("visibility") or "unknown"),
            _queue_line(document.get("langfuse_queue")),
            "Steps",
        ]
    )
    steps = list(document.get("steps") or [])
    if not steps:
        lines.append("  none")
    for step in steps:
        state = "done" if step.get("done") else "not done"
        lines.append(f"  {step.get('name')}: {state} — {step.get('summary')}")
    questions = list(document.get("questions") or [])
    if questions:
        lines.extend(["", "Questions"])
        for index, question in enumerate(questions, start=1):
            lines.append(f"  {index}. {question.get('key')}: {question.get('prompt')}")
    return "\n".join(lines) + "\n"


def _queue_line(queue: Any) -> str:
    queue = queue if isinstance(queue, dict) else {}
    waiting = queue.get("waiting") if isinstance(queue.get("waiting"), int) else 0
    reasons = queue.get("reasons") if isinstance(queue.get("reasons"), dict) else {}
    detail = ", ".join(f"{name} {count}" for name, count in sorted(reasons.items()))
    return f"Langfuse posts waiting: {waiting}" + (f" ({detail})" if detail else "")


def _keep_pin(entry: Any) -> dict[str, Any] | None:
    if isinstance(entry, dict) and _real_version(entry.get("version")):
        return dict(entry)
    if isinstance(entry, str) and _real_version(entry):
        return {"version": entry}
    return None


def pins_for(
    rows: Sequence[Mapping[str, Any]],
    probed: Mapping[str, str],
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    """Version-only pins. An existing recorded version is copied, rules included."""
    existing = _pins_block(profile)
    pins: dict[str, Any] = {}
    seen: set[str] = set()
    for row in rows:
        if _saga_owned(row):
            continue
        tool = str(row.get("tool") or "")
        if not tool or tool in seen:
            continue
        seen.add(tool)
        kept = _keep_pin(existing.get(tool))
        if kept is not None:
            pins[tool] = kept
            continue
        default = _real_version(row.get("default_version"))
        version = default or probed.get(tool)
        if version:
            pins[tool] = {"version": version}
    return pins


def _apply_pins(profile: dict[str, Any], pins: Mapping[str, Any]) -> None:
    if not pins:
        return
    block = profile.get("review_tools")
    if not isinstance(block, dict):
        profile["review_tools"] = {"pins": dict(pins)}
        return
    current = block.get("pins")
    if not isinstance(current, dict):
        block["pins"] = dict(pins)
        return
    for tool, pin in pins.items():
        current[tool] = pin


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".saga-profile.", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _require_answers(questions: Sequence[Mapping[str, str]], answers: Mapping[str, Any]) -> None:
    allowed: set[str] = set()
    missing: list[str] = []
    waiver = functional_environment.WAIVER_KEY
    functional = functional_environment.PROFILE_KEY
    for question in questions:
        key = str(question.get("key"))
        allowed.add(key)
        if key == functional:
            if functional not in answers and waiver not in answers:
                missing.append(key)
            else:
                allowed.add(waiver)
        elif key not in answers:
            missing.append(key)
    extra = set(answers) - allowed
    reserved = sorted(extra & RESERVED_PROFILE_KEYS)
    if reserved:
        raise SetupError(f"reserved answer key {reserved[0]}")
    unknown = sorted(extra)
    if unknown:
        raise SetupError(f"unknown answer key {unknown[0]}")
    if missing:
        raise SetupError(f"unanswered question {missing[0]}")


def _profile_for_write(repo: Path) -> dict[str, Any]:
    path = Path(repo) / PROFILE_NAME
    if not path.is_file():
        return {"schema": PROFILE_SCHEMA}
    loaded = _profile_object(repo)
    return loaded


def write_profile(
    repo: Path,
    answers: Mapping[str, Any],
    *,
    runner: Runner,
    env: Mapping[str, str] | None,
    tools_path: Path | None = None,
    extensions_path: Path | None = None,
    declaration_writer: Callable[..., Any] | None = None,
) -> Path:
    """Update the profile atomically, then hand a functional-test answer to its writer.

    A refusal happens before the temporary file is created. Survey does not call this.
    """
    if not isinstance(answers, dict):
        raise SetupError("the answers must be one JSON object")
    root = Path(repo)
    document = collect(
        root,
        runner=runner,
        env=env,
        tools_path=tools_path,
        extensions_path=extensions_path,
        persist=False,
        probe_live=False,
    )
    profile = _profile_for_write(root)
    _require_answers(document["questions"], answers)
    resolved = None
    if not _functional_settled(profile):
        try:
            resolved = functional_environment.from_answers(dict(answers))
        except functional_environment.DeclarationError as exc:
            raise SetupError(str(exc)) from exc
        if not isinstance(resolved, dict) or resolved.get("mode") not in (
            functional_environment.ANSWERED_MODES
        ):
            raise SetupError("the functional-test answer is incomplete")
    if "qa" in answers:
        hand_check_qa(answers["qa"])
    if "visibility" in answers and answers["visibility"] not in {"public", "private"}:
        raise SetupError("visibility must be public or private")
    rows = [row for row in _tool_rows(tools_path) if _selected(row, set(document["languages"]))]
    probed: dict[str, str] = {}
    for tool in document["tools"]:
        version = tool.get("version")
        name = str(tool.get("tool") or "")
        if name and isinstance(version, str) and name not in probed:
            probed[name] = version
    profile["languages"] = list(document["languages"])
    if document.get("visibility") in {"public", "private"}:
        profile["visibility"] = document["visibility"]
    elif answers.get("visibility") in {"public", "private"}:
        profile["visibility"] = answers["visibility"]
    _apply_pins(profile, pins_for(rows, probed, profile))
    if "qa" in answers:
        profile["qa"] = answers["qa"]
    extensions = load_extensions(extensions_path)
    for question in extensions["questions"]:
        key = question.get("key")
        if key in answers:
            profile[str(question.get("profile_key"))] = answers[key]
    path = root / PROFILE_NAME
    _atomic_write(path, json.dumps(profile, indent=2) + "\n")
    if resolved is not None:
        writer = declaration_writer or functional_environment.write_declaration
        try:
            writer(root, resolved)
        except (OSError, functional_environment.DeclarationError) as exc:
            raise SetupError(f"could not write the functional-test declaration: {exc}") from exc
    return path


def _stream(prefix: str, text: str | None, stream: Any) -> None:
    for line in (text or "").splitlines():
        print(f"{prefix}: {line}", file=stream)


def install_named(
    ids: Sequence[str],
    *,
    runner: Runner,
    env: Mapping[str, str] | None,
    cwd: Path,
    tools_path: Path | None = None,
) -> int:
    """Run the named install vectors, in order. Resolve every id before the first vector."""
    rows = _tool_rows(tools_path)
    chosen: list[dict[str, Any]] = []
    for identity in ids:
        row = next((item for item in rows if item.get("id") == identity), None)
        if row is None:
            raise SetupError(f"unknown tool {identity}")
        argv = row.get("install_argv")
        if not isinstance(argv, list) or not argv:
            print(str(row.get("install") or f"{identity} is not installed by setup"))
            raise SetupError(f"{identity} has no install command")
        chosen.append(row)
    for row in chosen:
        result = _call(
            runner,
            row["install_argv"],
            cwd=cwd,
            env=env,
            timeout=int(row.get("timeout_seconds") or 30),
        )
        identity = str(row.get("id"))
        _stream(identity, getattr(result, "stdout", ""), sys.stdout)
        _stream(identity, getattr(result, "stderr", ""), sys.stderr)
        if int(getattr(result, "returncode", 1)) != 0:
            return 1
    return 0


def run_named_step(
    name: str,
    *,
    runner: Runner,
    env: Mapping[str, str] | None,
    cwd: Path,
    extensions_path: Path | None = None,
) -> int:
    extensions = load_extensions(extensions_path)
    step = next(
        (
            item
            for item in extensions["steps"]
            if isinstance(item, dict) and item.get("name") == name
        ),
        None,
    )
    if step is None:
        raise SetupError(f"unknown step {name}")
    argv = step.get("run")
    if not isinstance(argv, list) or not argv:
        raise SetupError(f"{name} has no run command")
    result = _call(runner, argv, cwd=cwd, env=env, timeout=30)
    _stream(name, getattr(result, "stdout", ""), sys.stdout)
    _stream(name, getattr(result, "stderr", ""), sys.stderr)
    return 0 if int(getattr(result, "returncode", 1)) == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="saga_setup.py",
        description="Check the tools on this machine and the repository.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    survey = subcommands.add_parser("survey", help="Report tools, languages, and questions.")
    survey.add_argument(
        "--repo",
        default=None,
        help="Repository to read. Defaults to the working directory.",
    )
    survey.add_argument("--home", default=None, help="Home directory for the machine record.")
    survey.add_argument("--format", choices=("text", "json"), default="text")
    survey.add_argument("--probe-sandbox", choices=("live",), default=None)
    survey.add_argument("--probe-sandbox-model", default=None)
    survey.add_argument("--extensions", default=None)
    survey.add_argument(
        "--tools",
        default=None,
        help="Tool-list path. Defaults to the shipped list.",
    )

    write = subcommands.add_parser("write", help="Record answers in the repository profile.")
    write.add_argument("--repo", default=None)
    write.add_argument("--answers", required=True)
    write.add_argument("--extensions", default=None)
    write.add_argument("--tools", default=None)

    install = subcommands.add_parser("install", help="Run install commands for the named ids.")
    install.add_argument("--tools", required=True, help="Comma-separated tool ids.")
    install.add_argument("--repo", default=None)
    install.add_argument("--tool-list", default=None)

    step = subcommands.add_parser("step", help="Run one named optional step.")
    step.add_argument("--name", required=True)
    step.add_argument("--repo", default=None)
    step.add_argument("--extensions", default=None)

    offer_status_parser = subcommands.add_parser(
        "offer-status", help="Print whether setup ran and was offered, without writing."
    )
    offer_status_parser.add_argument("--home", default=None, help="Home directory for the machine record.")

    record_offer_parser = subcommands.add_parser(
        "record-offer", help="Record that the setup offer was shown, without marking setup run."
    )
    record_offer_parser.add_argument("--home", default=None, help="Home directory for the machine record.")
    return parser


def _repo(value: str | None) -> Path:
    return Path(value).resolve() if value else Path.cwd()


def _read_answers(source: str) -> dict[str, Any]:
    try:
        text = Path(source).read_text(encoding="utf-8")
    except OSError as exc:
        raise SetupError(f"could not read the answers from {source}: {exc}") from exc
    try:
        answers = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SetupError(f"the answers in {source} are not JSON: {exc}") from exc
    if not isinstance(answers, dict):
        raise SetupError("the answers must be one JSON object")
    return answers


def main(
    argv: list[str] | None = None,
    *,
    runner: Runner | None = None,
    env: Mapping[str, str] | None = None,
    session: Any = None,
    declaration_writer: Callable[..., Any] | None = None,
) -> int:
    """Run one subcommand. ``runner`` and ``env`` default to the process only when omitted."""
    parser = build_parser()
    args = parser.parse_args(argv)
    active = production_runner if runner is None else runner
    environment = os.environ if env is None else env
    try:
        if args.command == "survey":
            home = Path(args.home) if args.home else Path.home()
            document = collect(
                _repo(args.repo),
                runner=active,
                env=environment,
                home=home,
                tools_path=Path(args.tools) if args.tools else None,
                extensions_path=Path(args.extensions) if args.extensions else None,
                probe_live=args.probe_sandbox == "live",
                session=session,
                model_override=args.probe_sandbox_model,
                persist=True,
            )
            if args.format == "json":
                print(json.dumps(document, indent=2))
            else:
                print(render_text(document), end="")
            return 0
        if args.command == "write":
            write_profile(
                _repo(args.repo),
                _read_answers(args.answers),
                runner=active,
                env=environment,
                tools_path=Path(args.tools) if args.tools else None,
                extensions_path=Path(args.extensions) if args.extensions else None,
                declaration_writer=declaration_writer,
            )
            return 0
        if args.command == "install":
            ids = [part.strip() for part in str(args.tools).split(",") if part.strip()]
            if not ids:
                raise SetupError("name at least one tool id")
            return install_named(
                ids,
                runner=active,
                env=environment,
                cwd=_repo(args.repo),
                tools_path=Path(args.tool_list) if args.tool_list else None,
            )
        if args.command == "step":
            return run_named_step(
                args.name,
                runner=active,
                env=environment,
                cwd=_repo(args.repo),
                extensions_path=Path(args.extensions) if args.extensions else None,
            )
        if args.command == "offer-status":
            print(json.dumps(offer_status(Path(args.home) if args.home else Path.home()), indent=2))
            return 0
        if args.command == "record-offer":
            home = Path(args.home) if args.home else Path.home()
            require_readable_machine(home)
            print(record_offer(home))
            return 0
        raise SetupError(f"unknown command {args.command}")
    except SetupError as exc:
        print(f"saga_setup: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
