#!/usr/bin/env python3
"""
Infiquetra SDLC Manager — Unified CLI for Infiquetra SDLC automation.

Reads configuration dynamically from the infiquetra-sdlc repository checkout
(INFIQUETRA_SDLC_PATH env var, default: ~/workspace/infiquetra/infiquetra-sdlc).

All GitHub operations use the `gh` CLI for zero-token-management auth.

Active boards: Operations, Asgard, CAMPPS. Board/metrics commands require an
explicit --project (KTD17); there is no default board.

Usage:
    sdlc_manager.py board view --project operations
    sdlc_manager.py board add --project asgard --repo athena-service --number 42
    sdlc_manager.py board move --project asgard --repo athena-service --number 42 --status "Active"
    sdlc_manager.py board archive --project asgard [--dry-run]
    sdlc_manager.py board wip --project asgard
    sdlc_manager.py board standup --project operations
    sdlc_manager.py board discover-fields --project operations

    sdlc_manager.py issue create --repo athena-service --type capability
    sdlc_manager.py issue prepare --repo athena-service --type capability --team asgard \
      --project asgard --from docs/plans/example.md
    sdlc_manager.py issue create-prepared docs/sdlc-issue-drafts/<draft>.md
    sdlc_manager.py issue intent-envelope --run-mode unattended --merge auto

    sdlc_manager.py labels sync-fields --repo athena-service --number 42
    sdlc_manager.py labels audit --repo athena-service
    sdlc_manager.py labels deploy --repo athena-service
    sdlc_manager.py labels auto-label --repo athena-service --number 42
    sdlc_manager.py fields create-option --project asgard --field initiative --option "new-initiative"
    sdlc_manager.py fields discover --project asgard

    sdlc_manager.py metrics cycle-time --project asgard [--days 30] [--type capability]
    sdlc_manager.py metrics throughput --project asgard [--weeks 4]
    sdlc_manager.py metrics wip-age --project asgard
    sdlc_manager.py metrics column-time --project asgard --number 42

    sdlc_manager.py milestones create --repo athena-service --title "Pilot: Auth MVP" --due-date 2026-04-15
    sdlc_manager.py milestones list --repo athena-service [--state open]
    sdlc_manager.py milestones progress --repo athena-service --milestone 1
    sdlc_manager.py milestones link --repo athena-service --issue 42 --milestone 1

    sdlc_manager.py rollout status [--team asgard]
    sdlc_manager.py rollout gap-analysis --repo athena-service
    sdlc_manager.py rollout deploy-labels --repo athena-service
    sdlc_manager.py rollout deploy-templates --repo athena-service
    sdlc_manager.py rollout deploy-all --repo athena-service
    sdlc_manager.py rollout update --repo athena-service --field labels --status complete

    sdlc_manager.py flow set-field --project asgard --repo R --number N --field Initiative --option <name>
    sdlc_manager.py flow field-options --project asgard --field Objective
    sdlc_manager.py flow discover-project --repo athena-service
    sdlc_manager.py flow link-sub-issue --parent-repo R --parent-number P --child-repo R2 --child-number C
    sdlc_manager.py flow unlink-sub-issue --parent-repo R --parent-number P --child-repo R2 --child-number C
    sdlc_manager.py flow verify-label --repo athena-service --name high-priority [--color D93F0B] [--description "..."]
    sdlc_manager.py flow validate-card --repo athena-service --number 42

    sdlc_manager.py config show

Environment Variables:
    INFIQUETRA_SDLC_PATH: Path to infiquetra-sdlc repo (default: ~/workspace/infiquetra/infiquetra-sdlc)
"""

import argparse
import base64
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

import yaml

# ===========================
# CONFIGURATION
# ===========================

ORG = "infiquetra"
MAX_GITHUB_LABEL_DESCRIPTION_LENGTH = 100
MIMIR_COVERAGE_REPO = "team-mimir"
MIMIR_COVERAGE_PATH = "deploy/repository_coverage.yml"
MIMIR_INTAKE_LABEL = "intake:mimir"
MIMIR_AUTHORIZED_ROLES = frozenset({"triage", "write", "maintain", "admin"})


def _normalize_repo_arg(value: str) -> str:
    """Normalize a CLI repo argument to the script's internal bare-name contract."""
    repo = value.strip()
    if not repo:
        raise argparse.ArgumentTypeError("repo cannot be empty")
    if "/" not in repo:
        return repo
    owner, name = repo.split("/", 1)
    if not owner or not name or "/" in name:
        raise argparse.ArgumentTypeError("repo must be a bare repository name or infiquetra/<repo>")
    if owner.lower() != ORG.lower():
        raise argparse.ArgumentTypeError(
            f"unsupported repo owner {owner!r}; pass a bare Infiquetra repo name or {ORG}/<repo>"
        )
    return name


def _parse_numbers_arg(value: str) -> list[int]:
    """Parse a comma-separated issue-number list for CLI batch commands."""
    numbers: list[int] = []
    for part in value.split(","):
        raw = part.strip()
        if not raw:
            raise argparse.ArgumentTypeError("numbers must be comma-separated issue numbers")
        try:
            number = int(raw)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"invalid issue number {raw!r}") from exc
        if number <= 0:
            raise argparse.ArgumentTypeError("issue numbers must be positive integers")
        numbers.append(number)
    if not numbers:
        raise argparse.ArgumentTypeError("numbers cannot be empty")
    return numbers


def get_sdlc_path() -> Path:
    """Get path to infiquetra-sdlc checkout."""
    env_path = os.environ.get("INFIQUETRA_SDLC_PATH")
    if env_path:
        return Path(env_path).expanduser()
    return Path.home() / "workspace" / "infiquetra" / "infiquetra-sdlc"


# ===========================
# PER-USER DEFAULTS
# ===========================
# Sticky defaults persisted at ~/.claude/sdlc-defaults.json. The first-run
# wizard (`config init-defaults`) seeds the file. Subsequent commands read
# defaults from here and present them as prompt-default values; operators
# override per-card by typing a different value at the prompt.

_USER_DEFAULTS_PATH = Path.home() / ".claude" / "sdlc-defaults.json"

# Schema (all keys optional; missing keys = no default for that prompt).
# Listed here so callers and the wizard agree on the set:
_USER_DEFAULTS_KEYS = (
    "assignee",  # gh login (NOT OS $USER) — fetched via `gh api user --jq .login`
    "default_project",  # e.g., "operations"
    "default_status",  # e.g., "Backlog"
    "default_priority",  # e.g., "medium-priority"
    "default_initiative",  # option name on Olympus board (None until field is created)
    "default_objective",  # option name on Olympus board (None until field is created)
    "preferred_repos",  # list[str] of repos the operator works with most
)


def load_user_defaults() -> dict[str, Any]:
    """Read ~/.claude/sdlc-defaults.json. Returns {} on:
      - file missing (first run)
      - malformed JSON (warn + return {})
      - non-object root (warn + return {})
      - unreadable file / encoding errors (warn + return {})

    The CLI must remain usable even if the defaults file is corrupt —
    the operator can always re-run `config init-defaults` to reseed it."""
    if not _USER_DEFAULTS_PATH.exists():
        return {}
    try:
        with open(_USER_DEFAULTS_PATH) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            _warn(f"User defaults at {_USER_DEFAULTS_PATH} is not a JSON object; ignoring.")
            return {}
        return data
    except json.JSONDecodeError as e:
        _warn(f"User defaults at {_USER_DEFAULTS_PATH} is malformed JSON ({e}); ignoring.")
        return {}
    except (OSError, UnicodeDecodeError) as e:
        # Permissions, broken symlink, non-UTF-8 encoding, etc. The defaults
        # file is operator-owned and not load-bearing; warn + degrade.
        _warn(
            f"User defaults at {_USER_DEFAULTS_PATH} could not be read "
            f"({type(e).__name__}: {e}); ignoring."
        )
        return {}


def save_user_defaults(data: dict[str, Any]) -> None:
    """Atomically write ~/.claude/sdlc-defaults.json. Creates parent dir
    if missing. Atomic via tempfile + rename so a crash mid-write doesn't
    corrupt the file."""
    _USER_DEFAULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _USER_DEFAULTS_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    tmp_path.replace(_USER_DEFAULTS_PATH)


def get_default(key: str) -> Any:
    """Convenience: read a single default. Returns None if not set."""
    return load_user_defaults().get(key)


def _fetch_gh_login() -> str | None:
    """Get the operator's gh login via `gh api user --jq .login`. Returns
    None if gh is unauthenticated or the call fails — caller decides what
    to do. Importantly, NOT $USER (which can differ from the gh login)."""
    try:
        return _gh(["api", "user", "--jq", ".login"]) or None
    except (GhApiError, RuntimeError):
        return None


def load_config() -> dict[str, Any]:
    """Load SDLC config, preferring live canonical sources when freshness matters."""
    sdlc_path = get_sdlc_path()
    config: dict[str, Any] = {}

    # `legacy_rollout_config` reads `beads-config.json` for back-compat.
    # That file was removed from infiquetra-sdlc on 2026-04-26 (Beads removal);
    # this key now degrades gracefully to {} on missing-file. Several functions
    # below (board_wip, rollout_status, rollout_update, config_show) read this
    # config; they treat empty as "no rollout state tracked" and behave
    # sensibly. When a replacement file ships (e.g., rollout-status.json),
    # rename the key + path here.
    #
    # `project_mappings` resolution order (Phase C foundation):
    #   1. External override:  $INFIQUETRA_SDLC_PATH/config/project-mappings.json
    #   2. Vendored canonical: <plugin>/config/project-mappings.json
    #   3. Remote `gh api` fallback (reads infiquetra-sdlc raw from GitHub)
    # The plugin works without an external infiquetra-sdlc checkout because
    # the vendored copy ships canonical state for the org's projects.
    # Project node IDs captured in the vendored file are best-effort; field
    # and option IDs are NEVER cached (rotate on rename) and are fetched
    # live each call.
    config_files = {
        "labels": sdlc_path / "config" / "labels.json",
        "legacy_rollout_config": sdlc_path / "config" / "beads-config.json",
    }

    for key, path in config_files.items():
        if path.exists():
            with open(path) as f:
                config[key] = json.load(f)
        else:
            # Remote fallback via gh api
            try:
                result = _gh(
                    [
                        "api",
                        f"repos/{ORG}/infiquetra-sdlc/contents/config/{path.name}",
                        "--jq",
                        ".content",
                    ]
                )
                if result:
                    import base64

                    content = base64.b64decode(result.strip()).decode()
                    config[key] = json.loads(content)
            except Exception:
                config[key] = {}

    # Project mappings and SDLC schema each have their own resolution policy.
    # Mappings allow local override for operator workflow testing; schema prefers
    # GitHub main first because a local infiquetra-sdlc checkout may be stale.
    config["project_mappings"] = _resolve_project_mappings(sdlc_path)
    config["sdlc_schema"] = _resolve_sdlc_schema(sdlc_path)

    config["sdlc_path"] = str(sdlc_path)
    return config


# Vendored project-mappings path. Module-level constant so tests can
# `monkeypatch.setattr` it without renaming the real file (which is racy
# under pytest-xdist + leaves a `.bak-test` orphan if the test crashes
# between rename and `finally`). Resolves to `<plugin-dir>/config/project-mappings.json`
# via `scripts/sdlc_manager.py → ../config/...`.
_VENDORED_PROJECT_MAPPINGS_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "project-mappings.json"
)
_VENDORED_SDLC_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "config" / "sdlc-schema.json"
# Active boards only (KTD17): Operations, Asgard, CAMPPS. Mount Olympus
# (former project #1) is retired historical context and is NOT an active board
# choice; legacy Olympus card reads are still handled by the status/WIP helpers
# below for any external override that points at the old project.
PROJECT_CHOICES = ("operations", "asgard", "campps")
LIVE_LEGACY_STATUS_ALIASES = {
    "In Progress": "Assigned",
    "In Development": "Assigned",
    "E2E Testing": "In Review",
    "Deployment Ready": "Deploy State",
    "Deployed": "Done",
}


def _resolve_project_mappings(sdlc_path: Path) -> dict[str, Any]:
    """Resolve project-mappings.json via the documented order:
    external override → vendored → remote fallback. Returns {} if all fail."""
    # 1. External override at INFIQUETRA_SDLC_PATH/config/project-mappings.json
    override = sdlc_path / "config" / "project-mappings.json"
    if override.exists():
        with open(override) as f:
            return cast(dict[str, Any], json.load(f))

    # 2. Vendored canonical at <plugin-dir>/config/project-mappings.json
    if _VENDORED_PROJECT_MAPPINGS_PATH.exists():
        with open(_VENDORED_PROJECT_MAPPINGS_PATH) as f:
            return cast(dict[str, Any], json.load(f))

    # 3. Remote fallback via gh api (reads infiquetra-sdlc directly)
    try:
        result = _gh(
            [
                "api",
                f"repos/{ORG}/infiquetra-sdlc/contents/config/project-mappings.json",
                "--jq",
                ".content",
            ]
        )
        if result:
            import base64

            content = base64.b64decode(result.strip()).decode()
            return cast(dict[str, Any], json.loads(content))
    except (GhApiError, RuntimeError):
        pass

    return {}


def _resolve_sdlc_schema(sdlc_path: Path) -> dict[str, Any]:
    """Resolve sdlc-schema.json via GitHub main → vendored → local fallback."""
    try:
        result = _gh(
            [
                "api",
                f"repos/{ORG}/infiquetra-sdlc/contents/config/sdlc-schema.json?ref=main",
                "--jq",
                ".content",
            ]
        )
        if result:
            import base64

            content = base64.b64decode(result.strip()).decode()
            return cast(dict[str, Any], json.loads(content))
    except (GhApiError, RuntimeError):
        pass

    if _VENDORED_SDLC_SCHEMA_PATH.exists():
        with open(_VENDORED_SDLC_SCHEMA_PATH) as f:
            return cast(dict[str, Any], json.load(f))

    local_fallback = sdlc_path / "config" / "sdlc-schema.json"
    if local_fallback.exists():
        with open(local_fallback) as f:
            return cast(dict[str, Any], json.load(f))

    return {}


def get_project_config(config: dict, project_name: str) -> dict:
    """Get config for a specific project."""
    projects = config.get("project_mappings", {}).get("projects", {})
    if project_name not in projects:
        _error(f"Unknown project: {project_name}. Known projects: {', '.join(projects.keys())}")
        sys.exit(1)
    return cast(dict, projects[project_name])


def _project_board_key(project_name: str, proj: dict) -> str:
    """Return the SDLC schema board key for a project mapping."""
    if proj.get("board_key"):
        return cast(str, proj["board_key"])
    if project_name == "mount-olympus":
        return "olympus"
    return project_name.replace("-", "_")


def _project_workflow_name(schema: dict, project_name: str, proj: dict) -> str:
    """Return the workflow name for a project mapping."""
    if proj.get("workflow"):
        return cast(str, proj["workflow"])
    board_key = _project_board_key(project_name, proj)
    board = schema.get("boards", {}).get(board_key, {})
    workflow = board.get("workflow")
    if workflow:
        return cast(str, workflow)
    return "olympus_execution" if project_name == "mount-olympus" else "intent_flow"


def _project_workflow(config: dict, project_name: str, proj: dict) -> dict:
    """Return the workflow config for a project, or an empty fallback."""
    schema = config.get("sdlc_schema", {})
    workflow_name = _project_workflow_name(schema, project_name, proj)
    return cast(dict, schema.get("workflows", {}).get(workflow_name, {}))


def _status_order(
    config: dict, project_name: str, proj: dict, columns: dict | None = None
) -> list[str]:
    """Return schema-backed display order with live/legacy statuses appended."""
    workflow = _project_workflow(config, project_name, proj)
    ordered = list(workflow.get("statuses", []))

    if project_name == "mount-olympus" and "In Progress" not in ordered:
        # Live Olympus still exposes this option. Keep it visible without
        # making it canonical in the SDLC schema.
        insert_at = ordered.index("In Review") if "In Review" in ordered else len(ordered)
        ordered.insert(insert_at, "In Progress")

    for status in workflow.get("pause_states", []):
        if status not in ordered:
            ordered.append(status)

    if columns:
        for status in columns:
            if status not in ordered:
                ordered.append(status)

    if "No Status" not in ordered:
        ordered.append("No Status")
    return ordered


def _wip_limits(config: dict, project_name: str, proj: dict) -> dict[str, Any]:
    """Return schema-backed WIP limits for the project."""
    schema = config.get("sdlc_schema", {})
    board_key = _project_board_key(project_name, proj)
    limits = schema.get("wip_limits", {}).get(board_key, {})
    if limits:
        return cast(dict[str, Any], limits)

    legacy_limits = config.get("legacy_rollout_config", {}).get("wip_limits", {})
    if project_name == "mount-olympus" and isinstance(legacy_limits, dict) and legacy_limits:
        return {
            "Ready": legacy_limits.get("ready", 10),
            "In Development": legacy_limits.get("in_development", 10),
            "E2E Testing": legacy_limits.get("e2e_testing", 3),
            "Deployment Ready": legacy_limits.get("deployment_ready", 5),
        }

    return {"Ready": 10, "In Progress": 10 if project_name == "mount-olympus" else 5}


def _terminal_statuses(config: dict, project_name: str, proj: dict) -> list[str]:
    workflow = _project_workflow(config, project_name, proj)
    statuses = list(workflow.get("terminal_statuses", []))
    if project_name == "mount-olympus" and "Deployed" not in statuses:
        statuses.append("Deployed")
    return statuses or ["Done"]


def _cycle_start_statuses(project_name: str) -> list[str]:
    if project_name == "mount-olympus":
        return ["Assigned", "In Progress", "In Development"]
    return ["Active"]


def _active_age_thresholds(config: dict, project_name: str, proj: dict) -> dict[str, int]:
    workflow = _project_workflow(config, project_name, proj)
    statuses = list(workflow.get("statuses", []))
    if project_name == "mount-olympus":
        return {
            "Ready": 2,
            "Planning": 2,
            "Assigned": 5,
            "In Progress": 5,
            "In Review": 2,
        }
    terminal_statuses = _terminal_statuses(config, project_name, proj)
    return {status: 3 for status in statuses if status not in terminal_statuses}


def _legacy_status_hint(status: str, available: list[str]) -> str | None:
    """Return a migration hint when an old status name is requested."""
    alias = LIVE_LEGACY_STATUS_ALIASES.get(status)
    if not alias:
        return None
    if alias in available:
        return f"'{status}' is legacy; use '{alias}' on this board."
    return f"'{status}' is legacy; usually maps to '{alias}', which is not available here."


def get_projects_for_repo(config: dict, repo_name: str) -> list[dict]:
    """Return list of project configs that this repo belongs to."""
    mappings = config.get("project_mappings", {})
    excluded = mappings.get("excluded_repositories", [])
    if repo_name in excluded:
        return []

    special = mappings.get("special_mappings", {})
    projects = mappings.get("projects", {})
    result = []

    if repo_name in special:
        project_nums = special[repo_name]["projects"]
        for proj in projects.values():
            if proj["number"] in project_nums:
                result.append(proj)
        return result

    for proj in projects.values():
        if repo_name in proj.get("repositories", []):
            result.append(proj)

    return result


# ===========================
# GH CLI WRAPPER + TYPED EXCEPTIONS
# ===========================
# `_gh` is the single subprocess shim; `_classify_gh_error` parses both
# its stderr AND stdout streams to raise the appropriate typed subclass
# (ApiNotFoundError, ApiAlreadyExistsError, ApiAuthError, etc.).
# Replaces fragile `"422" in str(e)` substring matching across the
# flow_* helpers. Downstream handlers catch by type.


class GhApiError(RuntimeError):
    """Base for typed gh-API errors. Carries the parsed HTTP status_code
    when one could be extracted; otherwise None. Also retains both stderr
    AND stdout from the failed call — gh CLI prints the response body
    (often containing the actual error code in JSON) to STDOUT for 4xx/5xx
    failures, while stderr only carries a short summary like
    `gh: Validation Failed (HTTP 422)`. Both are needed for accurate
    classification (verified 2026-05-04 via direct `gh api` reproduction
    of 404 + 422-duplicate-label cases)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        stderr: str | None = None,
        stdout: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.stderr = stderr
        self.stdout = stdout


# N818 — exception class names end in `Error`
class ApiNotFoundError(GhApiError):
    """HTTP 404 from gh api. Used to detect 'label/issue/repo doesn't exist'
    cases without parsing English error strings."""


class ApiAlreadyExistsError(GhApiError):
    """HTTP 422 from gh api when the conflict is a duplicate-resource case
    (sub-issue already linked, label already exists, etc.). Used by the
    flow helpers to honor idempotency contracts.

    Note: 422 is also used by GitHub for general validation failures.
    This class is raised only when the response body matches a duplicate-
    resource pattern. The pattern check inspects BOTH stdout (where gh
    puts the JSON body — `{"errors":[{"code":"already_exists",...}]}` for
    label-already-exists; or English text for sub-issue link duplicates)
    AND stderr (which carries only the short status summary). Verified
    2026-05-04 against real GitHub responses."""


class ApiRateLimitedError(GhApiError):
    """HTTP 403 with rate-limit signals, or 429."""


class ApiAuthError(GhApiError):
    """HTTP 401 or 403 (non-rate-limit)."""


# Status-code parser. gh CLI prints stderr like:
#   "gh: Not Found (HTTP 404)"
#   "gh: Validation Failed (HTTP 422)"
# AND prints the JSON response body to stdout, e.g.:
#   {"message":"Not Found","status":"404"}
#   {"message":"Validation Failed","errors":[{"resource":"Label",
#    "code":"already_exists","field":"name"}],"status":"422"}
# Both streams are inspected. Verified 2026-05-04 by reproducing each
# error type against the real GitHub API.
_HTTP_STATUS_RE = re.compile(r"HTTP\s+(\d{3})\b", re.IGNORECASE)
# The structured indicator: GitHub's JSON error body uses these `code:`
# values for resource-already-exists. This is the canonical signal.
_DUPLICATE_RESOURCE_CODES = (
    '"code":"already_exists"',  # label-already-exists, etc. (no whitespace)
    '"code": "already_exists"',  # same with whitespace variant
)
# English-text fallback hints for cases where gh emits the message but
# not the structured code (e.g., sub-issue link duplicate where the
# response body uses different wording).
_DUPLICATE_RESOURCE_HINTS = (
    "already exists",
    "already a child",
    "already linked",
    "name has already been taken",
)


def _classify_gh_error(
    stderr: str,
    returncode: int,
    stdout: str = "",
) -> RuntimeError:
    """Inspect gh CLI stderr + stdout, return the appropriate exception
    type. Public for tests; called from `_gh` on non-zero exit.

    `stdout` defaults to "" for back-compat with tests written before
    the dual-stream classifier — passing only stderr still works for
    tests that synthesize stderr containing both status + body."""
    msg = stderr.strip() if stderr else "Unknown error"
    full = f"gh command failed: {msg}"

    # Status extraction — check stderr first (where gh puts the summary
    # `(HTTP NNN)` line), fall back to stdout JSON's `"status":"NNN"`.
    match = _HTTP_STATUS_RE.search(stderr)
    if not match:
        match = re.search(r'"status"\s*:\s*"?(\d{3})"?', stdout)
    status = int(match.group(1)) if match else None

    # Combined haystack for substring searches (both streams)
    combined_lower = (stderr + "\n" + stdout).lower()

    if status == 404:
        return ApiNotFoundError(full, status_code=404, stderr=stderr, stdout=stdout)
    if status in (401, 403):
        # Distinguish rate-limit from auth (rate-limit signals appear
        # in both streams)
        if "rate limit" in combined_lower or "x-ratelimit" in combined_lower:
            return ApiRateLimitedError(full, status_code=status, stderr=stderr, stdout=stdout)
        return ApiAuthError(full, status_code=status, stderr=stderr, stdout=stdout)
    if status == 429:
        return ApiRateLimitedError(full, status_code=429, stderr=stderr, stdout=stdout)
    if status == 422:
        # Duplicate-resource detection: structured `"code":"already_exists"`
        # in stdout JSON is the canonical signal; English-text hints in
        # stderr are the fallback.
        body_combined = stderr + stdout  # both streams, case-preserving for code match
        if any(code in body_combined for code in _DUPLICATE_RESOURCE_CODES):
            return ApiAlreadyExistsError(full, status_code=422, stderr=stderr, stdout=stdout)
        if any(hint in combined_lower for hint in _DUPLICATE_RESOURCE_HINTS):
            return ApiAlreadyExistsError(full, status_code=422, stderr=stderr, stdout=stdout)
        # Other 422s (validation failures) fall through to generic GhApiError
        return GhApiError(full, status_code=422, stderr=stderr, stdout=stdout)

    # Any other status / no parseable status
    return GhApiError(full, status_code=status, stderr=stderr, stdout=stdout)


# Backward-compat aliases for callers using the original names. Removable
# once a deprecation cycle has elapsed; kept here so any in-flight branches
# can still merge cleanly.
ApiNotFound = ApiNotFoundError
ApiAlreadyExists = ApiAlreadyExistsError
ApiRateLimited = ApiRateLimitedError


def _gh(args: list[str], input_data: str | None = None, capture: bool = True) -> str:
    """Run gh CLI command. Raises a typed GhApiError subclass on non-zero
    exit (ApiNotFoundError for 404, ApiAlreadyExistsError for duplicate-
    resource 422, ApiRateLimitedError / ApiAuthError as appropriate,
    GhApiError otherwise).
    Callers can catch the base GhApiError or RuntimeError."""
    cmd = ["gh"] + args
    try:
        result = subprocess.run(
            cmd,
            input=input_data,
            capture_output=capture,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            # Pass BOTH streams to the classifier — gh prints the JSON
            # error body to stdout for 4xx/5xx responses; stderr only
            # carries the short summary line.
            raise _classify_gh_error(
                result.stderr or "",
                result.returncode,
                stdout=result.stdout or "",
            )
        return result.stdout.strip() if capture else ""
    except subprocess.TimeoutExpired:
        raise GhApiError("gh command timed out after 60s") from None
    except FileNotFoundError:
        _error("gh CLI not found. Install from: https://cli.github.com/")
        sys.exit(1)


def _graphql(query: str, variables: dict | None = None) -> dict:
    """Execute a GraphQL query via gh CLI."""
    payload: dict[str, Any] = {"query": query}
    if variables:
        payload["variables"] = variables

    args = ["api", "graphql", "--input", "-"]
    result = _gh(args, input_data=json.dumps(payload))
    data = json.loads(result)

    if "errors" in data:
        raise RuntimeError(f"GraphQL errors: {data['errors']}")
    return cast(dict, data.get("data", {}))


def _issue_or_pull_request_node(repo_data: dict[str, Any]) -> dict[str, Any] | None:
    """Return the resolved Issue/PullRequest union node, if present."""
    node = repo_data.get("issueOrPullRequest")
    if isinstance(node, dict):
        return cast(dict[str, Any], node)
    return None


def _rest_get(path: str) -> Any:
    """Execute a REST GET via gh CLI."""
    result = _gh(["api", path])
    return json.loads(result)


# ===========================
# PAGINATION EXHAUSTION (#424)
# ===========================
# A truncated list read silently treated as "the whole list" is the fleet
# defect pattern named in docs/plans/2026-07-03-plugin-fleet-grounding-brief.md
# §7 pattern 3 (item-list pagination silently truncating at 200 of 375
# items). `paginate_or_raise` is the single shared loop every list-fetch call
# site (GraphQL cursor-based or REST page-number-based) should route through:
# it keeps fetching pages until the caller's `fetch_page` reports a real
# terminal signal (`next_token is None`), and raises `PaginationExhaustedError`
# — rather than silently returning whatever partial list it has accumulated —
# if `max_pages` is exhausted first. A misbehaving/runaway upstream is a
# defect to surface, never a partial result to swallow.


class PaginationExhaustedError(RuntimeError):
    """Raised when a paginated fetch does not reach a terminal page within
    the safety cap — a truncated read is a defect, not a valid partial list."""


def paginate_or_raise(
    fetch_page: Callable[[Any], tuple[list[Any], Any | None]],
    *,
    max_pages: int = 200,
) -> list[Any]:
    """Fetch every page via `fetch_page` until it signals termination.

    `fetch_page(token)` returns `(items, next_token)`. `token` starts as
    `None` on the first call. `next_token is None` is the ONLY accepted
    "no more pages" signal; any other value causes another call with that
    token. If `max_pages` calls happen without a `None` next_token, raises
    `PaginationExhaustedError` instead of returning the partial list — a
    silent 200-of-375-item truncation must fail loud, not slip through.
    """
    all_items: list[Any] = []
    token: Any = None
    for _ in range(max_pages):
        items, next_token = fetch_page(token)
        all_items.extend(items)
        if next_token is None:
            return all_items
        token = next_token
    raise PaginationExhaustedError(
        f"pagination did not terminate within {max_pages} pages "
        f"({len(all_items)} items fetched so far); refusing to silently truncate"
    )


def _rest_list_paginated(path: str, *, per_page: int = 100, max_pages: int = 50) -> list[Any]:
    """Fully paginate a REST GET that returns a JSON array (e.g. labels,
    milestones), via `paginate_or_raise`. Uses the standard `page`/`per_page`
    REST pagination params; a returned page shorter than `per_page` is the
    terminal signal (GitHub REST never pads a final page)."""
    sep = "&" if "?" in path else "?"

    def _fetch_page(page: int | None) -> tuple[list[Any], int | None]:
        page_num = page or 1
        batch = _rest_get(  # pagination-lint: allow (this IS the paginated fetch)
            f"{path}{sep}per_page={per_page}&page={page_num}"
        )
        if not isinstance(batch, list):
            raise RuntimeError(f"expected a JSON array from {path!r}, got {type(batch).__name__}")
        next_page = page_num + 1 if len(batch) == per_page else None
        return batch, next_page

    return paginate_or_raise(_fetch_page, max_pages=max_pages)


def _rest_post(path: str, body: dict) -> Any:
    """Execute a REST POST via gh CLI."""
    result = _gh(["api", "--method", "POST", path, "--input", "-"], input_data=json.dumps(body))
    return json.loads(result)


def _rest_patch(path: str, body: dict) -> Any:
    """Execute a REST PATCH via gh CLI."""
    result = _gh(["api", "--method", "PATCH", path, "--input", "-"], input_data=json.dumps(body))
    return json.loads(result)


def _rest_put(path: str, body: dict) -> Any:
    """Execute a REST PUT via gh CLI."""
    result = _gh(["api", "--method", "PUT", path, "--input", "-"], input_data=json.dumps(body))
    return json.loads(result)


def _rest_delete(path: str, body: dict | None = None) -> Any:
    """Execute a REST DELETE via gh CLI. May return empty body (e.g. 204 No Content)."""
    args = ["api", "--method", "DELETE", path]
    input_data = None
    if body is not None:
        args.extend(["--input", "-"])
        input_data = json.dumps(body)
    result = _gh(args, input_data=input_data)
    return json.loads(result) if result else ""


# ===========================
# OUTPUT HELPERS
# ===========================


def _out(data: Any, fmt: str = "text") -> None:
    """Output data in the requested format."""
    if fmt == "json":
        print(json.dumps(data, indent=2, default=str))
    else:
        print(data if isinstance(data, str) else json.dumps(data, indent=2, default=str))


def _error(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)


def _warn(msg: str) -> None:
    print(f"WARNING: {msg}", file=sys.stderr)


# ===========================
# GRAPHQL QUERIES
# ===========================

QUERY_GET_ITEM_NODE_ID = """
query($org: String!, $repo: String!, $number: Int!) {
  repository(owner: $org, name: $repo) {
    issueOrPullRequest(number: $number) {
      __typename
      ... on Issue { id number title }
      ... on PullRequest { id number title }
    }
  }
}
"""

QUERY_ADD_ITEM_TO_PROJECT = """
mutation($projectId: ID!, $contentId: ID!) {
  addProjectV2ItemById(input: {projectId: $projectId, contentId: $contentId}) {
    item { id }
  }
}
"""

QUERY_ARCHIVE_ITEM = """
mutation($projectId: ID!, $itemId: ID!) {
  archiveProjectV2Item(input: {projectId: $projectId, itemId: $itemId}) {
    item { id }
  }
}
"""

QUERY_SET_FIELD_VALUE = """
mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
  updateProjectV2ItemFieldValue(input: {
    projectId: $projectId
    itemId: $itemId
    fieldId: $fieldId
    value: { singleSelectOptionId: $optionId }
  }) { projectV2Item { id } }
}
"""

QUERY_GET_PROJECT_ITEMS = """
query($org: String!, $number: Int!, $cursor: String) {
  organization(login: $org) {
    projectV2(number: $number) {
      id
      title
      items(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          createdAt
          updatedAt
          content {
            ... on Issue {
              number title url state
              labels(first: 20) { nodes { name } }
              repository { name }
              milestone { title dueOn }
            }
            ... on PullRequest {
              number title url state
              labels(first: 20) { nodes { name } }
              repository { name }
            }
          }
          fieldValues(first: 20) {
            nodes {
              ... on ProjectV2ItemFieldSingleSelectValue {
                name
                field { ... on ProjectV2SingleSelectField { name id } }
              }
              ... on ProjectV2ItemFieldDateValue {
                date
                field { ... on ProjectV2Field { name id } }
              }
              ... on ProjectV2ItemFieldTextValue {
                text
                field { ... on ProjectV2Field { name id } }
              }
            }
          }
        }
      }
    }
  }
}
"""

QUERY_GET_PROJECT_FIELDS = """
query($org: String!, $number: Int!, $cursor: String) {
  organization(login: $org) {
    projectV2(number: $number) {
      id
      title
      fields(first: 30, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          ... on ProjectV2Field {
            id name dataType
          }
          ... on ProjectV2SingleSelectField {
            id name
            options { id name }
          }
          ... on ProjectV2IterationField {
            id name
          }
        }
      }
    }
  }
}
"""

QUERY_GET_ITEM_LABELS = """
# pagination-lint: allow (a single issue/PR never carries >30 labels; a cursor
# loop here would cost a round trip per read for a bound that cannot be reached)
query($org: String!, $repo: String!, $number: Int!) {
  repository(owner: $org, name: $repo) {
    issueOrPullRequest(number: $number) {
      __typename
      ... on Issue { labels(first: 30) { nodes { name } } }
      ... on PullRequest { labels(first: 30) { nodes { name } } }
    }
  }
}
"""

QUERY_GET_MIMIR_OBJECTIVE_FIELDS = """
# pagination-lint: allow (a single issue sits on a handful of projects, never
# >100, and each carries far fewer than 100 field values)
query($org: String!, $repo: String!, $number: Int!) {
  repository(owner: $org, name: $repo) {
    issue(number: $number) {
      projectItems(first: 100) {
        nodes {
          project { title number }
          fieldValues(first: 100) {
            nodes {
              ... on ProjectV2ItemFieldSingleSelectValue {
                name
                field { ... on ProjectV2SingleSelectField { name } }
              }
            }
          }
        }
      }
    }
  }
}
"""

QUERY_GET_ISSUE_TIMELINE = """
query($org: String!, $repo: String!, $number: Int!, $cursor: String) {
  repository(owner: $org, name: $repo) {
    issue(number: $number) {
      title
      createdAt
      closedAt
      timelineItems(first: 100, after: $cursor,
        itemTypes: [PROJECT_V2_ITEM_FIELD_VALUE_EVENT]) {
        pageInfo { hasNextPage endCursor }
        nodes {
          ... on ProjectV2ItemFieldValueEvent {
            createdAt
            previousProjectV2ItemFieldValue {
              ... on ProjectV2ItemFieldSingleSelectValue { name }
            }
            projectV2ItemFieldValue {
              ... on ProjectV2ItemFieldSingleSelectValue { name }
            }
          }
        }
      }
    }
  }
}
"""


# ===========================
# BOARD OPERATIONS
# ===========================


def get_project_items(project_number: int) -> tuple[str, list[dict]]:
    """Fetch all items from a project, returning (project_id, items).

    Routes through `paginate_or_raise` (#424) so a runaway/misbehaving
    upstream response raises `PaginationExhaustedError` instead of this
    function silently returning a partial item list."""
    project_id_box: dict[str, str] = {"id": ""}

    def _fetch_page(cursor: str | None) -> tuple[list[dict], str | None]:
        data = _graphql(
            QUERY_GET_PROJECT_ITEMS,
            {
                "org": ORG,
                "number": project_number,
                "cursor": cursor,
            },
        )
        proj = data.get("organization", {}).get("projectV2", {})
        if not project_id_box["id"]:
            project_id_box["id"] = proj.get("id", "")

        items_data = proj.get("items", {})
        page_info = items_data.get("pageInfo", {})
        next_cursor = page_info.get("endCursor") if page_info.get("hasNextPage") else None
        return items_data.get("nodes", []), next_cursor

    all_items = paginate_or_raise(_fetch_page)
    return project_id_box["id"], all_items


def get_project_fields(
    project_number: int,
    *,
    max_pages: int = 200,
) -> tuple[str, list[dict[str, Any]]]:
    """Fetch all fields from a project, returning (project_id, fields).

    Routes through `paginate_or_raise` (#424, #584) so a runaway/misbehaving
    upstream response raises `PaginationExhaustedError` instead of this
    function silently returning a partial field list."""
    project_id_box: dict[str, str] = {"id": ""}

    def _fetch_page(cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
        data = _graphql(
            QUERY_GET_PROJECT_FIELDS,
            {
                "org": ORG,
                "number": project_number,
                "cursor": cursor,
            },
        )
        proj = data.get("organization", {}).get("projectV2") or {}
        if not project_id_box["id"]:
            project_id_box["id"] = proj.get("id", "")

        fields_data = proj.get("fields", {})
        page_info = fields_data.get("pageInfo", {})
        next_cursor = page_info.get("endCursor") if page_info.get("hasNextPage") else None
        return fields_data.get("nodes", []), next_cursor

    all_fields = paginate_or_raise(_fetch_page, max_pages=max_pages)
    return project_id_box["id"], all_fields


def get_item_status(item: dict) -> str:
    """Extract Status field value from a project item."""
    for fv in item.get("fieldValues", {}).get("nodes", []):
        field_name = fv.get("field", {}).get("name", "")
        if field_name == "Status":
            return cast(str, fv.get("name", ""))
    return ""


def get_item_field_value(item: dict, field_name: str) -> str:
    """Extract any single-select or text field value."""
    for fv in item.get("fieldValues", {}).get("nodes", []):
        fn = fv.get("field", {}).get("name", "")
        if fn == field_name:
            return cast(str, fv.get("name", "") or fv.get("text", "") or fv.get("date", ""))
    return ""


def get_item_age_days(item: dict) -> float:
    """Get age of item in days (from createdAt)."""
    created = item.get("createdAt", "")
    if not created:
        return 0
    dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
    return (datetime.now(UTC) - dt).total_seconds() / 86400


def board_view(project_name: str, status_filter: str | None, fmt: str) -> None:
    """View project board items grouped by column."""
    config = load_config()
    proj = get_project_config(config, project_name)
    project_id, items = get_project_items(proj["number"])

    # Group by status
    columns: dict[str, list[dict]] = {}
    for item in items:
        status = get_item_status(item)
        if not status:
            status = "No Status"
        if status_filter and status != status_filter:
            continue
        columns.setdefault(status, []).append(item)

    wip_limits = _wip_limits(config, project_name, proj)
    column_order = _status_order(config, project_name, proj, columns)

    if fmt == "json":
        _out({"project": project_name, "columns": columns}, fmt)
        return

    print(f"\n{'=' * 60}")
    print(f"  {proj['name']} (Project #{proj['number']})")
    print(f"{'=' * 60}\n")

    for col in column_order:
        col_items = columns.get(col, [])
        if not col_items and col not in wip_limits:
            continue

        limit = wip_limits.get(col)
        if isinstance(limit, int):
            limit_str = f" [WIP: {len(col_items)}/{limit}]"
            over_limit = len(col_items) > limit
        elif isinstance(limit, str):
            limit_str = f" [WIP: {len(col_items)}; limit {limit}]"
            over_limit = False
        else:
            limit_str = f" [{len(col_items)} items]"
            over_limit = False
        marker = " OVER LIMIT" if over_limit else ""

        print(f"### {col}{limit_str}{marker}")
        for item in col_items:
            content = item.get("content", {})
            repo = content.get("repository", {}).get("name", "unknown")
            number = content.get("number", "?")
            title = content.get("title", "")[:60]
            age = get_item_age_days(item)
            labels = [la["name"] for la in content.get("labels", {}).get("nodes", [])]
            type_label = next(
                (
                    la
                    for la in labels
                    if la in ["capability", "enhancement", "defect", "exploration"]
                ),
                "",
            )
            print(f"  - [{type_label or 'unknown'}] {repo}#{number}: {title} (age: {age:.0f}d)")
        print()


def board_add(
    repo: str,
    number: int,
    fmt: str,
    config: dict | None = None,
    project_name: str | None = None,
    project_names: list[str] | None = None,
    strict: bool = False,
) -> None:
    """Add issue/PR to correct project(s).

    Native Projects-v2 multi-membership: one item node id is added to each
    resolved project as an INDEPENDENT membership (not a clone — see KTD10).
    Each project keeps its own per-board Status.

    Project resolution precedence (first non-empty wins):
      1. ``project_names`` — explicit list of named projects (repeatable
         ``--project`` on the CLI). Order-preserving de-dup; add to exactly
         those boards.
      2. ``project_name`` — a single explicit named project (back-compat).
      3. neither given — fall back to ``get_projects_for_repo`` (the repo →
         project mapping), unchanged.

    Per-project fault isolation: one project's add failing is captured in the
    results and does not abort adds to the remaining projects.
    """
    if not config:
        config = load_config()

    if project_names:
        # Explicit multi-membership: resolve each named project, order-
        # preserving de-dup so a repeated --project doesn't add twice.
        seen: set[str] = set()
        ordered: list[str] = []
        for name in project_names:
            if name in seen:
                continue
            seen.add(name)
            ordered.append(name)
        projects = [get_project_config(config, n) for n in ordered]
    elif project_name:
        projects = [get_project_config(config, project_name)]
    else:
        projects = get_projects_for_repo(config, repo)
    if not projects:
        mappings = config.get("project_mappings", {})
        excluded = mappings.get("excluded_repositories", [])
        if repo in excluded:
            print(f"Repo '{repo}' is excluded from project automation.")
        else:
            print(f"Repo '{repo}' is not mapped to any project. Add manually if needed.")
        return

    # Get item node ID
    data = _graphql(QUERY_GET_ITEM_NODE_ID, {"org": ORG, "repo": repo, "number": number})
    repo_data = data.get("repository") or {}
    item_data = _issue_or_pull_request_node(repo_data)
    if not item_data:
        _error(f"Could not find issue/PR #{number} in {ORG}/{repo}")
        sys.exit(1)
    item_id = item_data["id"]

    results = []
    for proj in projects:
        try:
            _graphql(
                QUERY_ADD_ITEM_TO_PROJECT,
                {
                    "projectId": proj["id"],
                    "contentId": item_id,
                },
            )
            results.append(f"Added {repo}#{number} to '{proj['name']}' (#{proj['number']})")

            # Sync label fields if project has label_fields config
            if "label_fields" in proj:
                sync_results = _sync_label_fields_for_item(repo, number, proj, item_id)
                results.extend(sync_results)
        except Exception as e:
            if strict:
                raise RuntimeError(f"Failed to add to '{proj['name']}': {e}") from e
            results.append(f"Failed to add to '{proj['name']}': {e}")

    _out("\n".join(results), fmt)


def board_move(
    repo: str, number: int, status: str, fmt: str, project_name: str | None = None
) -> bool:
    """Move item to a different board column."""
    config = load_config()
    projects = (
        [get_project_config(config, project_name)]
        if project_name
        else get_projects_for_repo(config, repo)
    )
    if not projects:
        _error(f"Repo '{repo}' not mapped to any project")
        sys.exit(1)

    results = []
    failed = False
    for proj in projects:
        project_id, items = get_project_items(proj["number"])

        # Find item
        target_item = None
        for item in items:
            content = item.get("content", {})
            if (
                content.get("number") == number
                and content.get("repository", {}).get("name") == repo
            ):
                target_item = item
                break

        if not target_item:
            results.append(f"Item {repo}#{number} not found in '{proj['name']}'")
            failed = True
            continue

        # Find Status field ID and option ID via field discovery
        _, proj_fields = get_project_fields(proj["number"])

        status_field = None
        status_option_id = None
        for field in proj_fields:
            if field.get("name") == "Status":
                status_field = field
                for opt in field.get("options", []):
                    if opt["name"] == status:
                        status_option_id = opt["id"]
                        break
                break

        if not status_field:
            results.append(f"No Status field found in '{proj['name']}'")
            failed = True
            continue
        if not status_option_id:
            available = [o["name"] for o in status_field.get("options", [])]
            hint = _legacy_status_hint(status, available)
            message = f"Status '{status}' not found. Available: {', '.join(available)}"
            if hint:
                message = f"{message}. {hint}"
            results.append(message)
            failed = True
            continue

        try:
            _graphql(
                QUERY_SET_FIELD_VALUE,
                {
                    "projectId": project_id,
                    "itemId": target_item["id"],
                    "fieldId": status_field["id"],
                    "optionId": status_option_id,
                },
            )
            results.append(f"Moved {repo}#{number} to '{status}' in '{proj['name']}'")
        except Exception as e:
            results.append(f"Failed to move: {e}")
            failed = True

    _out("\n".join(results), fmt)
    return not failed


def board_archive(project_name: str, dry_run: bool, fmt: str) -> None:
    """Archive items in terminal workflow statuses."""
    config = load_config()
    proj = get_project_config(config, project_name)
    project_id, items = get_project_items(proj["number"])

    terminal_statuses = set(_terminal_statuses(config, project_name, proj))
    terminal_items = [i for i in items if get_item_status(i) in terminal_statuses]

    if dry_run:
        print(
            f"DRY RUN: Would archive {len(terminal_items)} terminal items "
            f"from '{proj['name']}' ({', '.join(sorted(terminal_statuses))}):"
        )
        for item in terminal_items:
            content = item.get("content", {})
            print(
                f"  - {content.get('repository', {}).get('name', '?')}#{content.get('number', '?')}: {content.get('title', '')[:50]}"
            )
        return

    results = []
    for item in terminal_items:
        content = item.get("content", {})
        label = f"{content.get('repository', {}).get('name', '?')}#{content.get('number', '?')}"
        try:
            _graphql(
                QUERY_ARCHIVE_ITEM,
                {
                    "projectId": project_id,
                    "itemId": item["id"],
                },
            )
            results.append(f"Archived {label}")
        except Exception as e:
            results.append(f"Failed to archive {label}: {e}")

    ok = sum(1 for r in results if r.startswith("Archived"))
    _out(f"Archived {ok} items.\n" + "\n".join(results), fmt)


def board_wip(project_name: str, fmt: str) -> None:
    """Show WIP counts vs limits."""
    config = load_config()
    proj = get_project_config(config, project_name)
    _, items = get_project_items(proj["number"])

    wip_limits = _wip_limits(config, project_name, proj)

    counts: dict[str, int] = {}
    for item in items:
        status = get_item_status(item)
        if status:
            counts[status] = counts.get(status, 0) + 1

    print(f"\nWIP Status — {proj['name']}")
    print("=" * 50)
    violations = []
    for col, limit in wip_limits.items():
        if col == "pause_states" or limit is None:
            continue
        count = counts.get(col, 0)
        if isinstance(limit, int):
            over = count > limit
            if over:
                violations.append(col)
            bar = "X" * count + "." * max(0, limit - count)
            marker = " OVER LIMIT" if over else ""
            print(f"  {col:20} {count:2}/{limit:<2} [{bar}]{marker}")
        else:
            print(f"  {col:20} {count:2} (limit: {limit})")

    if violations:
        print(f"\nWIP VIOLATIONS: {', '.join(violations)}")
        print("Stop pulling new work until WIP returns to limit.")
    else:
        print("\nAll WIP limits respected.")


def board_standup(project_name: str, fmt: str) -> None:
    """Right-to-left board review for standup."""
    config = load_config()
    proj = get_project_config(config, project_name)
    _, items = get_project_items(proj["number"])

    # Group and sort
    columns: dict[str, list[dict]] = {}
    for item in items:
        status = get_item_status(item) or "No Status"
        columns.setdefault(status, []).append(item)

    right_to_left = list(reversed(_status_order(config, project_name, proj, columns)))
    right_to_left = [c for c in right_to_left if c != "No Status"]

    print(f"\n{'=' * 60}")
    print(f"  STANDUP PREP — {proj['name']}")
    print(f"  {datetime.now().strftime('%Y-%m-%d')}")
    print(f"{'=' * 60}\n")

    for col in right_to_left:
        col_items = columns.get(col, [])
        if not col_items:
            print(f"### {col}: (empty)")
            print()
            continue

        print(f"### {col} ({len(col_items)} items)")
        for item in col_items:
            content = item.get("content", {})
            repo = content.get("repository", {}).get("name", "?")
            number = content.get("number", "?")
            title = content.get("title", "")[:55]
            age = get_item_age_days(item)
            labels = [la["name"] for la in content.get("labels", {}).get("nodes", [])]
            blocked = "blocked" in labels
            marker = " BLOCKED" if blocked else ""
            aged = " AGING" if age > 3 else ""
            print(f"  - {repo}#{number}: {title}{marker}{aged} ({age:.0f}d)")
        print()

    # Summary
    terminal = set(_terminal_statuses(config, project_name, proj))
    active_columns = [c for c in right_to_left if c not in terminal and c != "No Status"]
    total_active = sum(len(columns.get(c, [])) for c in active_columns)
    print(f"Summary: {total_active} active items, {len(columns.get('Ready', []))} in Ready")


def board_discover_fields(project_name: str, fmt: str) -> None:
    """Discover all fields and options on a project."""
    config = load_config()
    proj = get_project_config(config, project_name)
    _, fields = get_project_fields(proj["number"])

    if fmt == "json":
        _out({"project": project_name, "fields": fields}, fmt)
        return

    print(f"\nFields for '{proj['name']}' (#{proj['number']})")
    print("=" * 50)
    for field in fields:
        name = field.get("name", "")
        fid = field.get("id", "")
        dtype = field.get("dataType", "")
        options = field.get("options", [])
        print(f"\n  {name} (type: {dtype or 'unknown'})")
        print(f"    ID: {fid}")
        if options:
            for opt in options:
                print(f"    Option: {opt['name']:30} ID: {opt['id']}")


# ===========================
# LABEL OPERATIONS
# ===========================


def _get_item_labels(repo: str, number: int) -> list[str]:
    """Get label names for an issue."""
    data = _graphql(QUERY_GET_ITEM_LABELS, {"org": ORG, "repo": repo, "number": number})
    repo_data = data.get("repository") or {}
    item_data = _issue_or_pull_request_node(repo_data)
    if not item_data:
        return []
    return [n["name"] for n in item_data.get("labels", {}).get("nodes", [])]


def _sync_label_fields_for_item(repo: str, number: int, proj: dict, item_id: str) -> list[str]:
    """Sync initiative/objective labels to project fields. Returns result messages."""
    label_fields = proj.get("label_fields", {})
    if not label_fields:
        return []

    labels = _get_item_labels(repo, number)
    results = []
    project_id = proj["id"]

    for label_prefix, field_config in label_fields.items():
        field_id = field_config.get("field_id", "")
        options = field_config.get("options", {})
        prefix = f"{label_prefix}:"

        matching = [lbl[len(prefix) :] for lbl in labels if lbl.startswith(prefix)]
        if not matching:
            continue

        value = matching[0]
        option_id = options.get(value)

        if not option_id:
            results.append(
                f"No option ID for {label_prefix}:{value} — consider running 'fields create-option'"
            )
            continue

        try:
            _graphql(
                QUERY_SET_FIELD_VALUE,
                {
                    "projectId": project_id,
                    "itemId": item_id,
                    "fieldId": field_id,
                    "optionId": option_id,
                },
            )
            results.append(f"Set {label_prefix}={value}")
        except Exception as e:
            results.append(f"Failed to set {label_prefix}={value}: {e}")

    return results


def labels_sync_fields(repo: str, number: int, fmt: str) -> None:
    """Sync initiative/objective labels to project single-select fields."""
    config = load_config()
    projects = get_projects_for_repo(config, repo)
    if not projects:
        _error(f"Repo '{repo}' not mapped to any project")
        sys.exit(1)

    all_results = []
    for proj in projects:
        if "label_fields" not in proj:
            continue

        # Find the project item ID
        project_id, items = get_project_items(proj["number"])
        target_item = next(
            (
                i
                for i in items
                if i.get("content", {}).get("number") == number
                and i.get("content", {}).get("repository", {}).get("name") == repo
            ),
            None,
        )
        if not target_item:
            all_results.append(f"Item {repo}#{number} not found in '{proj['name']}'")
            continue

        results = _sync_label_fields_for_item(repo, number, proj, target_item["id"])
        all_results.extend(results)

    _out("\n".join(all_results) if all_results else "No label fields to sync.", fmt)


def labels_audit(repo: str, fmt: str) -> None:
    """Check if repo has all required SDLC labels."""
    config = load_config()
    required_labels = [la["name"] for la in config.get("labels", {}).get("labels", [])]

    # Get existing labels
    try:
        existing_raw = _rest_list_paginated(f"/repos/{ORG}/{repo}/labels")
        existing = {la["name"] for la in existing_raw}
    except Exception as e:
        _error(f"Could not fetch labels from {repo}: {e}")
        sys.exit(1)

    missing = [la for la in required_labels if la not in existing]
    extra = [la for la in existing if la not in required_labels]

    if fmt == "json":
        _out(
            {
                "repo": repo,
                "missing": missing,
                "extra": list(extra),
                "required_count": len(required_labels),
                "existing_count": len(existing),
            },
            fmt,
        )
        return

    print(f"\nLabel Audit: {ORG}/{repo}")
    print(f"Required: {len(required_labels)} | Existing: {len(existing)}")
    if missing:
        print(f"\nMissing ({len(missing)}):")
        for la in missing:
            print(f"  - {la}")
    else:
        print("\nAll required labels present")
    if extra:
        print(f"\nExtra labels ({len(extra)}):")
        for la in list(extra)[:10]:
            print(f"  - {la}")


def labels_deploy(repo: str, fmt: str) -> None:
    """Create/update all SDLC labels in target repo."""
    config = load_config()
    label_defs = config.get("labels", {}).get("labels", [])
    _validate_label_taxonomy(label_defs)

    results = []
    for label in label_defs:
        name = label["name"]
        color = label["color"]
        description = label.get("description", "")

        try:
            _gh(
                [
                    "label",
                    "create",
                    name,
                    "--color",
                    color,
                    "--description",
                    description,
                    "--repo",
                    f"{ORG}/{repo}",
                    "--force",
                ]
            )
            results.append(f"OK: {name}")
        except Exception as e:
            results.append(f"FAIL: {name}: {e}")

    ok = sum(1 for r in results if r.startswith("OK"))
    fail = len(results) - ok
    print(f"\nDeployed labels to {ORG}/{repo}: {ok} ok, {fail} failed")
    if fail:
        for r in results:
            if r.startswith("FAIL"):
                print(f"  {r}")


def _required_issue_taxonomy_labels() -> set[str]:
    required: set[str] = set()
    for labels in _ISSUE_TYPE_LABELS.values():
        required.update(labels)
    return required


def _validate_label_taxonomy(label_defs: list[dict[str, Any]]) -> None:
    """Validate loaded SDLC label definitions before any GitHub label mutation."""
    errors: list[str] = []
    if not label_defs:
        errors.append("label taxonomy has no labels")

    seen: set[str] = set()
    names: set[str] = set()
    for index, label in enumerate(label_defs):
        raw_name = label.get("name", "")
        name = raw_name.strip() if isinstance(raw_name, str) else ""
        if not name:
            errors.append(f"label at index {index} is missing a name")
            continue
        if name in seen:
            errors.append(f"{name}: duplicate label name")
        seen.add(name)
        names.add(name)

        raw_color = label.get("color", "")
        color = raw_color.strip() if isinstance(raw_color, str) else ""
        if not color:
            errors.append(f"{name}: missing color")

        description = label.get("description", "") or ""
        if len(description) > MAX_GITHUB_LABEL_DESCRIPTION_LENGTH:
            errors.append(
                f"{name}: description is {len(description)} chars; "
                f"GitHub max is {MAX_GITHUB_LABEL_DESCRIPTION_LENGTH}"
            )

    missing_required = sorted(_required_issue_taxonomy_labels() - names)
    if missing_required:
        errors.append("missing required issue taxonomy labels: " + ", ".join(missing_required))

    if errors:
        details = "\n".join(f"- {error}" for error in errors)
        raise RuntimeError(f"Invalid SDLC label taxonomy:\n{details}")


def labels_auto_label(repo: str, number: int, fmt: str) -> None:
    """Apply auto-label rules based on issue title/content."""
    config = load_config()
    rules = config.get("labels", {}).get("auto_label_rules", {})

    # Get issue title
    try:
        issue_data = _rest_get(f"/repos/{ORG}/{repo}/issues/{number}")
        title = issue_data.get("title", "")
        body = issue_data.get("body", "") or ""
    except Exception as e:
        _error(f"Could not fetch issue: {e}")
        sys.exit(1)

    text = f"{title} {body}"
    labels_to_add = []
    for _rule_name, rule in rules.items():
        pattern = rule.get("pattern", "")
        if re.search(pattern, text, re.IGNORECASE):
            labels_to_add.extend(rule.get("add_labels", []))

    labels_to_add = list(set(labels_to_add))
    if not labels_to_add:
        print(f"No auto-label rules matched for {repo}#{number}")
        return

    # Apply labels
    try:
        _rest_post(f"/repos/{ORG}/{repo}/issues/{number}/labels", {"labels": labels_to_add})
        print(f"Applied labels to {repo}#{number}: {', '.join(labels_to_add)}")
    except Exception as e:
        _error(f"Failed to apply labels: {e}")


def fields_create_option(project_name: str, field_name: str, option_name: str, fmt: str) -> None:
    """Create a new single-select option on a project field."""
    config = load_config()
    proj = get_project_config(config, project_name)

    # Discover fields
    _, fields = get_project_fields(proj["number"])

    target_field = None
    for f in fields:
        if f.get("name", "").lower() == field_name.lower():
            target_field = f
            break

    if not target_field:
        _error(f"Field '{field_name}' not found in project '{project_name}'")
        sys.exit(1)

    print(f"Creating option '{option_name}' for field '{field_name}' in '{project_name}'...")
    print(f"Field ID: {target_field['id']}")
    print(f"Existing options: {[o['name'] for o in target_field.get('options', [])]}")
    print("\nNote: Option creation via GraphQL may require specific permissions.")
    print("If this fails, add the option manually in the GitHub Projects UI:")
    print(f"  https://github.com/orgs/{ORG}/projects/{proj['number']}/settings/fields")


def fields_discover(project_name: str, fmt: str) -> None:
    """Alias for board discover-fields."""
    board_discover_fields(project_name, fmt)


# ===========================
# METRICS OPERATIONS
# ===========================


def _get_issue_column_times(org: str, repo: str, number: int) -> list[dict]:
    """Get time spent in each column via timeline events."""

    def _fetch_page(cursor: str | None) -> tuple[list[dict], str | None]:
        data = _graphql(
            QUERY_GET_ISSUE_TIMELINE, {"org": org, "repo": repo, "number": number, "cursor": cursor}
        )
        timeline = data.get("repository", {}).get("issue", {}).get("timelineItems", {})
        page_info = timeline.get("pageInfo", {})
        next_cursor = page_info.get("endCursor") if page_info.get("hasNextPage") else None
        return timeline.get("nodes", []), next_cursor

    all_events = paginate_or_raise(_fetch_page)

    # Calculate time in each column
    transitions = []
    for event in all_events:
        if not event:
            continue
        prev = event.get("previousProjectV2ItemFieldValue", {})
        curr = event.get("projectV2ItemFieldValue", {})
        prev_status = prev.get("name", "") if prev else ""
        curr_status = curr.get("name", "") if curr else ""
        if curr_status:
            transitions.append(
                {
                    "at": event.get("createdAt", ""),
                    "from": prev_status,
                    "to": curr_status,
                }
            )

    return transitions


def metrics_cycle_time(project_name: str, days: int, issue_type: str | None, fmt: str) -> None:
    """Calculate cycle time percentiles using timeline events."""
    config = load_config()
    proj = get_project_config(config, project_name)
    _, items = get_project_items(proj["number"])
    terminal_statuses = set(_terminal_statuses(config, project_name, proj))
    start_statuses = set(_cycle_start_statuses(project_name))

    cycle_times = []

    print(f"Analyzing cycle times for '{proj['name']}' (last {days} days)...")
    print("This may take a moment as we fetch timeline events for each item.\n")

    for item in items:
        status = get_item_status(item)
        if status not in terminal_statuses:
            continue

        content = item.get("content", {})
        labels = [la["name"] for la in content.get("labels", {}).get("nodes", [])]

        if issue_type and issue_type not in labels:
            continue

        repo = content.get("repository", {}).get("name", "")
        number = content.get("number")
        if not repo or not number:
            continue

        try:
            transitions = _get_issue_column_times(ORG, repo, number)
        except Exception:
            continue

        # Find first active-work start and terminal end. Legacy Olympus
        # timeline data may still use In Progress / In Development / Deployed.
        dev_start = None
        done_time = None
        for t in transitions:
            if t["to"] in start_statuses and not dev_start:
                dev_start = datetime.fromisoformat(t["at"].replace("Z", "+00:00"))
            if t["to"] in terminal_statuses:
                done_time = datetime.fromisoformat(t["at"].replace("Z", "+00:00"))

        if dev_start and done_time:
            cycle_days = (done_time - dev_start).total_seconds() / 86400
            cycle_times.append(cycle_days)

    if not cycle_times:
        print("No completed items found in range.")
        return

    cycle_times.sort()
    n = len(cycle_times)
    p50 = cycle_times[int(n * 0.5)]
    p85 = cycle_times[int(n * 0.85)]
    p95 = cycle_times[min(int(n * 0.95), n - 1)]

    targets = {"capability": 5, "enhancement": 2, "defect": 1}
    target = targets.get(issue_type or "")

    if fmt == "json":
        _out({"count": n, "p50": p50, "p85": p85, "p95": p95, "target": target}, fmt)
        return

    print(f"Cycle Time — {proj['name']} ({issue_type or 'all types'})")
    print(f"Sample size: {n} items")
    target_ok = not target or p85 <= target
    print(f"  P50: {p50:.1f} days")
    print(f"  P85: {p85:.1f} days {'OK' if target_ok else 'OVER TARGET'}")
    print(f"  P95: {p95:.1f} days")
    if target:
        print(f"  Target: < {target} days (P85)")


def metrics_throughput(project_name: str, weeks: int, fmt: str) -> None:
    """Show terminal items per week."""
    config = load_config()
    proj = get_project_config(config, project_name)
    _, items = get_project_items(proj["number"])
    terminal_statuses = set(_terminal_statuses(config, project_name, proj))

    from collections import defaultdict

    weekly: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for item in items:
        status = get_item_status(item)
        if status not in terminal_statuses:
            continue

        content = item.get("content", {})
        labels = [la["name"] for la in content.get("labels", {}).get("nodes", [])]
        issue_type = next(
            (la for la in labels if la in ["capability", "enhancement", "defect"]), "other"
        )

        updated = item.get("updatedAt", "")
        if updated:
            dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            week_key = dt.strftime("%Y-W%V")
            weekly[week_key][issue_type] += 1

    # Show last N weeks
    all_weeks = sorted(weekly.keys())[-weeks:]

    if fmt == "json":
        _out(
            {
                "project": project_name,
                "weeks": {w: dict(v) for w, v in weekly.items() if w in all_weeks},
            },
            fmt,
        )
        return

    print(f"\nThroughput — {proj['name']} (last {weeks} weeks)")
    print(f"{'Week':15} {'Capabilities':12} {'Enhancements':12} {'Defects':8} {'Total':6}")
    print("-" * 55)
    for week in all_weeks:
        caps = weekly[week].get("capability", 0)
        enhs = weekly[week].get("enhancement", 0)
        defs = weekly[week].get("defect", 0)
        total = sum(weekly[week].values())
        print(f"  {week:13} {caps:12} {enhs:12} {defs:8} {total:6}")


def metrics_wip_age(project_name: str, fmt: str) -> None:
    """Show age of in-progress items."""
    config = load_config()
    proj = get_project_config(config, project_name)
    _, items = get_project_items(proj["number"])

    aged_thresholds = _active_age_thresholds(config, project_name, proj)
    active_cols = list(aged_thresholds.keys())

    print(f"\nWIP Age — {proj['name']}")
    print("=" * 60)

    for col in active_cols:
        col_items = [(i, get_item_age_days(i)) for i in items if get_item_status(i) == col]
        col_items.sort(key=lambda x: x[1], reverse=True)
        threshold = aged_thresholds.get(col, 3)

        print(f"\n### {col}")
        for item, age in col_items:
            content = item.get("content", {})
            repo = content.get("repository", {}).get("name", "?")
            number = content.get("number", "?")
            title = content.get("title", "")[:45]
            flag = " AGING" if age > threshold else ""
            print(f"  - {repo}#{number}: {title} ({age:.0f}d){flag}")


def metrics_column_time(project_name: str, number: int, fmt: str) -> None:
    """Show time spent in each column for a specific item."""
    config = load_config()
    proj = get_project_config(config, project_name)
    _, items = get_project_items(proj["number"])

    # Find item and its repo
    target_item = None
    for item in items:
        if item.get("content", {}).get("number") == number:
            target_item = item
            break

    if not target_item:
        _error(f"Item #{number} not found in '{project_name}'")
        sys.exit(1)

    repo = target_item.get("content", {}).get("repository", {}).get("name", "")
    transitions = _get_issue_column_times(ORG, repo, number)

    print(f"\nColumn Times — {repo}#{number} in '{proj['name']}'")
    print(f"Title: {target_item.get('content', {}).get('title', '')}")
    print("=" * 50)

    if not transitions:
        print("No column transitions recorded.")
        return

    for _i, t in enumerate(transitions):
        print(f"  {t['at'][:10]}: {t['from'] or 'start':25} -> {t['to']}")

    # Calculate durations between transitions
    print("\nTime in each column:")
    for i in range(len(transitions) - 1):
        t1 = datetime.fromisoformat(transitions[i]["at"].replace("Z", "+00:00"))
        t2 = datetime.fromisoformat(transitions[i + 1]["at"].replace("Z", "+00:00"))
        duration_days = (t2 - t1).total_seconds() / 86400
        col = transitions[i]["to"]
        print(f"  {col:25}: {duration_days:.1f} days")


# ===========================
# MILESTONE OPERATIONS
# ===========================


def milestones_create(repo: str, title: str, due_date: str, description: str, fmt: str) -> None:
    """Create a GitHub milestone for an Objective."""
    body = {"title": title, "due_on": f"{due_date}T00:00:00Z"}
    if description:
        body["description"] = description

    try:
        result = _rest_post(f"/repos/{ORG}/{repo}/milestones", body)
        ms_number = result.get("number")
        url = result.get("html_url", "")
        print(f"Created milestone #{ms_number}: '{title}'")
        print(f"   URL: {url}")
        print(f"   Due: {due_date}")
    except Exception as e:
        _error(f"Failed to create milestone: {e}")


def milestones_list(repo: str, state: str, fmt: str) -> None:
    """List milestones in a repo."""
    try:
        milestones = _rest_list_paginated(f"/repos/{ORG}/{repo}/milestones?state={state}")
    except Exception as e:
        _error(f"Failed to list milestones: {e}")
        sys.exit(1)

    if fmt == "json":
        _out(milestones, fmt)
        return

    print(f"\nMilestones in {ORG}/{repo} ({state})")
    print("=" * 50)
    for ms in milestones:
        number = ms.get("number")
        title = ms.get("title", "")
        due = ms.get("due_on", "")[:10] if ms.get("due_on") else "no due date"
        open_count = ms.get("open_issues", 0)
        closed_count = ms.get("closed_issues", 0)
        total = open_count + closed_count
        pct = int(closed_count / total * 100) if total > 0 else 0
        print(f"  #{number}: {title}")
        print(f"    Due: {due} | Progress: {closed_count}/{total} ({pct}%)")


def milestones_progress(repo: str, milestone_num: int, fmt: str) -> None:
    """Show milestone completion progress."""
    try:
        ms = _rest_get(f"/repos/{ORG}/{repo}/milestones/{milestone_num}")
    except Exception as e:
        _error(f"Failed to get milestone: {e}")
        sys.exit(1)

    title = ms.get("title", "")
    open_count = ms.get("open_issues", 0)
    closed_count = ms.get("closed_issues", 0)
    total = open_count + closed_count
    pct = int(closed_count / total * 100) if total > 0 else 0
    due = ms.get("due_on", "")[:10] if ms.get("due_on") else "no due date"

    if fmt == "json":
        _out(
            {
                "title": title,
                "open": open_count,
                "closed": closed_count,
                "total": total,
                "percent": pct,
                "due": due,
            },
            fmt,
        )
        return

    print(f"\nMilestone Progress: {title}")
    print(f"  Due: {due}")
    bar = "X" * (pct // 5) + "." * (20 - pct // 5)
    print(f"  Progress: [{bar}] {pct}% ({closed_count}/{total} capabilities)")

    # Risk assessment
    if due != "no due date":
        due_dt = datetime.fromisoformat(due)
        days_left = (due_dt - datetime.now()).days
        if days_left < 0:
            print(f"  OVERDUE by {abs(days_left)} days")
        elif days_left < 7 and pct < 80:
            print(f"  AT RISK: {days_left} days left, only {pct}% complete")
        else:
            print(f"  {days_left} days until target date")


def milestones_link(repo: str, issue_num: int, milestone_num: int, fmt: str) -> None:
    """Link an issue to a milestone."""
    try:
        _rest_patch(f"/repos/{ORG}/{repo}/issues/{issue_num}", {"milestone": milestone_num})
        print(f"Linked {repo}#{issue_num} to milestone #{milestone_num}")
    except Exception as e:
        _error(f"Failed to link issue to milestone: {e}")


# ===========================
# ROLLOUT OPERATIONS
# ===========================


def rollout_status(team_filter: str | None, fmt: str) -> None:
    """Show rollout status from config."""
    config = load_config()
    status = config.get("legacy_rollout_config", {})
    repos = status.get("repositories", {})
    summary = status.get("summary", {})

    if team_filter:
        repos = {k: v for k, v in repos.items() if v.get("team", "").lower() == team_filter.lower()}

    if fmt == "json":
        _out(status, fmt)
        return

    print("\nSDLC Rollout Status")
    print(f"Last updated: {status.get('last_updated', 'unknown')}")
    print(
        f"Total: {summary.get('total_repos', 0)} repos | "
        f"Complete: {summary.get('completed', 0)} | "
        f"In progress: {summary.get('in_progress', 0)} | "
        f"Pending: {summary.get('pending', 0)}"
    )
    print()

    # Group by tier
    by_tier: dict[int, list[tuple[str, dict]]] = {}
    for repo_name, repo_data in repos.items():
        tier = repo_data.get("tier", 0)
        by_tier.setdefault(tier, []).append((repo_name, repo_data))

    for tier in sorted(by_tier.keys()):
        tier_repos = by_tier[tier]
        print(f"### Tier {tier}")
        for repo_name, repo_data in tier_repos:
            fields = ["labels", "templates", "claude_md", "project"]
            statuses = {f: repo_data.get(f, "unknown") for f in fields}
            complete = all(v == "complete" for v in statuses.values())
            in_progress = any(v == "complete" for v in statuses.values())
            if complete:
                marker = "DONE"
            elif in_progress:
                marker = "WIP"
            else:
                marker = "PENDING"
            team = repo_data.get("team", "")
            print(f"  [{marker}] {repo_name:40} [{team}]")
            if not complete:
                pending_fields = [f for f, v in statuses.items() if v != "complete"]
                print(f"       Pending: {', '.join(pending_fields)}")
        print()


def rollout_gap_analysis(repo: str, fmt: str) -> None:
    """Check what SDLC setup is missing from a repo."""
    config = load_config()
    required_labels = [la["name"] for la in config.get("labels", {}).get("labels", [])]
    template_names = [
        "capability.yml",
        "context-update.yml",
        "defect.yml",
        "enhancement.yml",
        "exploration.yml",
    ]

    gaps = []

    # Check labels
    try:
        existing_labels_raw = _rest_list_paginated(f"/repos/{ORG}/{repo}/labels")
        existing_labels = {la["name"] for la in existing_labels_raw}
        missing_labels = [la for la in required_labels if la not in existing_labels]
        if missing_labels:
            gaps.append(
                f"Missing {len(missing_labels)} labels (run: sdlc_manager.py rollout deploy-labels --repo {repo})"
            )
        else:
            gaps.append("All labels present")
    except Exception as e:
        gaps.append(f"Could not check labels: {e}")

    # Check templates
    try:
        existing_templates = _rest_get(f"/repos/{ORG}/{repo}/contents/.github/ISSUE_TEMPLATE")
        existing_template_names = {t["name"] for t in existing_templates}
        missing_templates = [t for t in template_names if t not in existing_template_names]
        if missing_templates:
            gaps.append(f"Missing templates: {', '.join(missing_templates)}")
        else:
            gaps.append("All issue templates present")
    except Exception:
        gaps.append(
            f"Missing .github/ISSUE_TEMPLATE/ directory (run: sdlc_manager.py rollout deploy-templates --repo {repo})"
        )

    # Check project mapping
    projects = get_projects_for_repo(config, repo)
    if projects:
        gaps.append(f"Mapped to project(s): {', '.join(p['name'] for p in projects)}")
    else:
        gaps.append("Not mapped to any project")

    _out(f"\nGap Analysis: {ORG}/{repo}\n" + "\n".join(f"  - {g}" for g in gaps), fmt)


def rollout_deploy_labels(repo: str, fmt: str) -> None:
    """Deploy all SDLC labels to a repo."""
    labels_deploy(repo, fmt)


def rollout_deploy_templates(repo: str, fmt: str) -> None:
    """Copy all SDLC issue templates to target repo."""
    sdlc_path = get_sdlc_path()
    template_dir = sdlc_path / ".github" / "ISSUE_TEMPLATE"

    if not template_dir.exists():
        _error(f"Template directory not found: {template_dir}")
        sys.exit(1)

    templates = list(template_dir.glob("*.yml"))
    results = []

    for template_path in templates:
        with open(template_path) as f:
            content = f.read()

        import base64

        content_b64 = base64.b64encode(content.encode()).decode()

        gh_path = f".github/ISSUE_TEMPLATE/{template_path.name}"
        api_path = f"/repos/{ORG}/{repo}/contents/{gh_path}"

        # Check if file exists to get SHA for update
        sha = None
        try:
            existing = _rest_get(api_path)
            sha = existing.get("sha")
        except Exception:
            pass  # File doesn't exist yet

        body: dict[str, Any] = {
            "message": f"chore: deploy SDLC template {template_path.name}",
            "content": content_b64,
        }
        if sha:
            body["sha"] = sha

        try:
            _rest_put(api_path, body)
            results.append(f"OK: {template_path.name}")
        except Exception as e:
            results.append(f"FAIL: {template_path.name}: {e}")

    print(f"\nDeployed templates to {ORG}/{repo}:")
    for r in results:
        print(f"  {r}")


def rollout_deploy_all(repo: str, fmt: str) -> None:
    """Full deployment: labels + templates."""
    print(f"\n=== Deploying SDLC to {ORG}/{repo} ===\n")
    print("Step 1: Labels")
    rollout_deploy_labels(repo, fmt)
    print("\nStep 2: Templates")
    rollout_deploy_templates(repo, fmt)
    print("\nStep 3: Gap analysis")
    rollout_gap_analysis(repo, fmt)


def rollout_update(repo: str, field: str, status: str, fmt: str) -> None:
    """Update beads-config.json for a repo."""
    sdlc_path = get_sdlc_path()
    status_file = sdlc_path / "config" / "beads-config.json"

    config = load_config()
    beads = config.get("legacy_rollout_config", {})
    repos = beads.get("repositories", {})

    if repo not in repos:
        _error(f"Repo '{repo}' not found in beads-config.json")
        sys.exit(1)

    repos[repo][field] = status
    beads["last_updated"] = datetime.now().strftime("%Y-%m-%d")

    # Recalculate summary
    summary = {"total_repos": len(repos), "completed": 0, "in_progress": 0, "pending": 0}
    for repo_data in repos.values():
        fields = ["labels", "templates", "claude_md", "project"]
        statuses_vals = [repo_data.get(f, "pending") for f in fields]
        if all(v == "complete" for v in statuses_vals):
            summary["completed"] += 1
        elif any(v == "complete" for v in statuses_vals):
            summary["in_progress"] += 1
        else:
            summary["pending"] += 1
    beads["summary"] = summary

    with open(status_file, "w") as f:
        json.dump(beads, f, indent=2)
        f.write("\n")

    print(f"Updated {repo}.{field} = {status} in beads-config.json")


# NOTE: The `beads` subcommand group + `_bd` shell helper + `beads_*`
# functions were removed in this PR. Beads/Dolt was decommissioned from
# the Mount Olympus coordination layer on 2026-04-26 (see
# infiquetra-sdlc/docs/engineering-journal/narratives/2026-04-26-beads-dolt-removed.md);
# the agent fleet now coordinates via Redis pub/sub (`olympus:*` channels)
# + GitHub Projects v2 + Discord per-card threads.


# ===========================
# FLOW OPERATIONS (Phase C)
# ===========================
# `flow` is a thin operator-facing surface over the GraphQL + REST APIs the
# plugin already uses elsewhere. Commands here are the minimum viable set
# needed to make the blueprint-to-issue workflow executable end-to-end:
#   - set-field          set a single-select project field on a card
#   - field-options      list current options for a project field
#   - discover-project   resolve which project a repo is mapped to
#   - link-sub-issue     wrap the native sub-issue API
#   - verify-label       self-heal missing labels (404 → create; exists → no-op)
#   - validate-card      run the card_validator schema check on an issue body


def _resolve_project_field(project_name: str, field_name: str) -> dict:
    """Look up a project field by name. Returns the field node (with
    id, name, options if SINGLE_SELECT). Raises RuntimeError if missing."""
    return _resolve_project_fields(project_name, [field_name])[field_name]


def _resolve_project_fields(project_name: str, field_names: list[str]) -> dict[str, dict[str, Any]]:
    """Look up project fields by name with one live discovery query."""
    config = load_config()
    proj = get_project_config(config, project_name)
    project_id, fields = get_project_fields(proj["number"])
    requested = {name.lower(): name for name in field_names}
    resolved: dict[str, dict[str, Any]] = {}
    for field in fields:
        requested_name = requested.get(field.get("name", "").lower())
        if requested_name:
            resolved[requested_name] = {**field, "_project_id": project_id}

    missing = [name for name in field_names if name not in resolved]
    if missing:
        raise RuntimeError(
            f"Field(s) {missing} not found on project '{project_name}'. "
            f"Available fields: {[f.get('name') for f in fields]}. "
            f"If you expected this field to exist (e.g., Initiative or Objective), "
            f"the field-creation runbook is in "
            f"`infiquetra-sdlc/docs/operations/operational-reference.md` "
            f"under 'Initiative/Objective Tracking'."
        )
    return resolved


def flow_field_options(project_name: str, field_name: str, fmt: str) -> None:
    """List the current options for a project single-select field.
    Live discovery — option IDs rotate on rename/recreate; never cache them."""
    field = _resolve_project_field(project_name, field_name)
    options = field.get("options", [])
    if not options:
        _out(
            f"Field '{field_name}' has no options (or is not a SINGLE_SELECT field).",
            fmt,
        )
        return
    if fmt == "json":
        _out([{"id": o["id"], "name": o["name"]} for o in options], fmt)
    else:
        print(f"\nOptions for {project_name}.{field_name}:")
        for o in options:
            print(f"  {o['name']:30s}  (id: {o['id']})")


def flow_set_field(
    project_name: str,
    repo: str,
    number: int,
    field_name: str,
    option_name: str,
    fmt: str,
) -> None:
    """Set a single-select field value on a card. Idempotent: re-running
    with the same option produces the same final state."""
    field = _resolve_project_field(project_name, field_name)
    project_id = field["_project_id"]
    option = _resolve_field_option(project_name, field_name, field, option_name)
    item_by_number = _project_items_by_number(project_name, repo)

    target_item = item_by_number.get(number)
    if not target_item:
        raise RuntimeError(
            f"Issue {repo}#{number} is not on project '{project_name}'. "
            f"Use `sdlc_manager.py board add --repo {repo} --number {number}` first."
        )

    _set_project_field_value(project_id, field, option, target_item)
    _out(f"Set {field_name}='{option_name}' on {repo}#{number} ({project_name})", fmt)


def _resolve_field_option(
    project_name: str,
    field_name: str,
    field: dict[str, Any],
    option_name: str,
) -> dict[str, Any]:
    """Find a single-select option by name with the existing operator hint."""
    options = field.get("options", [])
    option = next(
        (o for o in options if o.get("name", "").lower() == option_name.lower()),
        None,
    )
    if not option:
        raise RuntimeError(
            f"Option '{option_name}' not found on field '{field_name}'. "
            f"Available: {[o['name'] for o in options]}. "
            f"Hint: use `flow field-options --project {project_name} --field {field_name}` "
            f"to see current options."
        )
    return cast(dict[str, Any], option)


def _project_items_by_number(project_name: str, repo: str) -> dict[int, dict[str, Any]]:
    """Index current project items for one repo; callers decide missing-item semantics."""
    config = load_config()
    project_number = get_project_config(config, project_name)["number"]
    _, items = get_project_items(project_number)
    return {
        cast(int, item.get("content", {}).get("number")): cast(dict[str, Any], item)
        for item in items
        if item.get("content", {}).get("repository", {}).get("name") == repo
        and isinstance(item.get("content", {}).get("number"), int)
    }


def _set_project_field_value(
    project_id: str,
    field: dict[str, Any],
    option: dict[str, Any],
    target_item: dict[str, Any],
) -> None:
    _graphql(
        QUERY_SET_FIELD_VALUE,
        {
            "projectId": project_id,
            "itemId": target_item["id"],
            "fieldId": field["id"],
            "optionId": option["id"],
        },
    )


def flow_set_field_bulk(
    project_name: str,
    repo: str,
    numbers: list[int],
    field_name: str,
    option_name: str,
    fmt: str,
) -> None:
    """Set one single-select field value across multiple cards in one discovery pass."""
    flow_set_fields_bulk(project_name, repo, numbers, [(field_name, option_name)], fmt)


def flow_set_fields_bulk(
    project_name: str,
    repo: str,
    numbers: list[int],
    assignments: list[tuple[str, str]],
    fmt: str,
) -> None:
    """Set one or more single-select fields across multiple cards in one discovery pass."""
    if not numbers:
        raise RuntimeError("numbers cannot be empty")
    if not assignments:
        raise RuntimeError("field assignments cannot be empty")

    field_names = [field_name for field_name, _ in assignments]
    fields = _resolve_project_fields(project_name, field_names)
    resolved_assignments = [
        (
            field_name,
            option_name,
            fields[field_name],
            _resolve_field_option(project_name, field_name, fields[field_name], option_name),
        )
        for field_name, option_name in assignments
    ]
    item_by_number = _project_items_by_number(project_name, repo)

    updated: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for number in numbers:
        target_item = item_by_number.get(number)
        if not target_item:
            failed.append(
                {
                    "repo": repo,
                    "number": number,
                    "error": (
                        f"Issue {repo}#{number} is not on project '{project_name}'. "
                        f"Use `sdlc_manager.py board add --repo {repo} --number {number}` first."
                    ),
                }
            )
            continue
        for field_name, option_name, field, option in resolved_assignments:
            try:
                _set_project_field_value(field["_project_id"], field, option, target_item)
            except RuntimeError as exc:
                failed.append(
                    {
                        "repo": repo,
                        "number": number,
                        "field": field_name,
                        "option": option_name,
                        "error": str(exc),
                    }
                )
                continue
            updated.append(
                {
                    "repo": repo,
                    "number": number,
                    "field": field_name,
                    "option": option_name,
                }
            )

    result = {
        "action": "set-field",
        "project": project_name,
        "repo": repo,
        "assignments": [
            {"field": field_name, "option": option_name} for field_name, option_name in assignments
        ],
        "updated": updated,
        "failed": failed,
    }
    _out(result, fmt)
    if failed:
        raise RuntimeError(
            f"flow set-field failed for {len(failed)} of "
            f"{len(numbers) * len(assignments)} field update(s); see results above"
        )


def flow_discover_project(repo: str, fmt: str) -> None:
    """Resolve which project(s) a repo is mapped to via project-mappings.json.
    Returns a list of {name, number} entries; empty list if unmapped."""
    config = load_config()
    projects = get_projects_for_repo(config, repo)
    if not projects:
        mappings = config.get("project_mappings", {})
        excluded = mappings.get("excluded_repositories", [])
        if repo in excluded:
            _out(f"Repo '{repo}' is in excluded_repositories.", fmt)
        else:
            _out(f"Repo '{repo}' is not mapped to any project.", fmt)
        return
    if fmt == "json":
        _out([{"name": p["name"], "number": p["number"]} for p in projects], fmt)
    else:
        print(f"\n{repo} maps to:")
        for p in projects:
            print(f"  - {p['name']} (#{p['number']})")


def _load_live_mimir_coverage(repo: str) -> dict[str, Any]:
    """Read and validate Team Mimir's exact repository admission from GitHub main."""
    encoded = _gh(
        [
            "api",
            f"repos/{ORG}/{MIMIR_COVERAGE_REPO}/contents/{MIMIR_COVERAGE_PATH}?ref=main",
            "--jq",
            ".content",
        ]
    )
    try:
        document = yaml.safe_load(base64.b64decode(encoded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise RuntimeError("Team Mimir coverage is unreadable; no mutation performed") from exc

    if not isinstance(document, dict) or not isinstance(document.get("repository_coverage"), dict):
        raise RuntimeError("Team Mimir coverage has an invalid root; no mutation performed")
    coverage = cast(dict[str, Any], document["repository_coverage"])
    if coverage.get("schema_version") != 1:
        raise RuntimeError("Team Mimir coverage schema is unsupported; no mutation performed")
    if coverage.get("policy_version") != "repository-coverage/v1":
        raise RuntimeError("Team Mimir coverage policy is unsupported; no mutation performed")
    if coverage.get("default_disposition") != "quarantine":
        raise RuntimeError("Team Mimir coverage is not fail-closed; no mutation performed")

    full_repo = f"{ORG}/{repo}"
    entries = coverage.get("repositories")
    if not isinstance(entries, list):
        raise RuntimeError("Team Mimir coverage repository list is invalid; no mutation performed")
    matches = [
        entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("repository") == full_repo
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Repository {full_repo} is not uniquely covered by Team Mimir; no mutation performed"
        )
    entry = cast(dict[str, Any], matches[0])
    events = entry.get("events")
    if entry.get("state") != "active" or not isinstance(events, list) or "issues" not in events:
        raise RuntimeError(
            f"Repository {full_repo} is not active for Team Mimir issue intake; no mutation performed"
        )
    if not isinstance(entry.get("route"), str) or not entry["route"]:
        raise RuntimeError(f"Repository {full_repo} has no Team Mimir route; no mutation performed")
    return {
        "policy_version": coverage.get("policy_version"),
        "repository": full_repo,
        "route": entry["route"],
    }


def _mimir_objective_fields(repo: str, number: int) -> list[dict[str, Any]]:
    """Return live Objective values on every project card carrying the issue."""
    data = _graphql(
        QUERY_GET_MIMIR_OBJECTIVE_FIELDS,
        {"org": ORG, "repo": repo, "number": number},
    )
    issue = data.get("repository", {}).get("issue")
    if not isinstance(issue, dict):
        raise RuntimeError(f"Could not read back {ORG}/{repo}#{number} project state")

    result: list[dict[str, Any]] = []
    for item in issue.get("projectItems", {}).get("nodes", []):
        if not isinstance(item, dict):
            continue
        project = item.get("project", {})
        for field_value in item.get("fieldValues", {}).get("nodes", []):
            if not isinstance(field_value, dict):
                continue
            if field_value.get("field", {}).get("name") != "Objective":
                continue
            value = field_value.get("name")
            if value:
                result.append(
                    {
                        "project": project.get("title"),
                        "project_number": project.get("number"),
                        "value": value,
                    }
                )
    return result


def flow_assign_mimir(repo: str, number: int, fmt: str) -> None:
    """Apply the existing Mimir intake label after live, fail-closed preflight."""
    coverage = _load_live_mimir_coverage(repo)
    issue_path = f"repos/{ORG}/{repo}/issues/{number}"
    issue = _rest_get(issue_path)
    if not isinstance(issue, dict) or issue.get("pull_request"):
        raise RuntimeError(f"{ORG}/{repo}#{number} is not an issue; no mutation performed")
    if issue.get("state") != "open":
        raise RuntimeError(f"{ORG}/{repo}#{number} is not open; no mutation performed")

    actor = _fetch_gh_login()
    if not actor:
        raise RuntimeError("Current GitHub principal could not be verified; no mutation performed")
    try:
        authority = _rest_get(
            f"repos/{ORG}/{repo}/collaborators/{quote(actor, safe='')}/permission"
        )
    except ApiNotFoundError as exc:
        raise RuntimeError(
            f"GitHub principal {actor} has no verified authority on {ORG}/{repo}; "
            "no mutation performed"
        ) from exc
    if not isinstance(authority, dict):
        raise RuntimeError(
            f"GitHub authority for {actor} on {ORG}/{repo} was unreadable; no mutation performed"
        )
    # `role_name` may be an organization-defined custom role. GitHub's
    # standardized `permission` is the effective base role we can compare
    # against the command's closed authorization vocabulary.
    role = authority.get("permission") or authority.get("role_name")
    if role not in MIMIR_AUTHORIZED_ROLES:
        raise RuntimeError(
            f"GitHub principal {actor} has insufficient authority ({role!r}) on {ORG}/{repo}; "
            "no mutation performed"
        )

    try:
        _rest_get(f"repos/{ORG}/{repo}/labels/{quote(MIMIR_INTAKE_LABEL, safe='')}")
    except ApiNotFoundError as exc:
        raise RuntimeError(
            f"Required trigger label {MIMIR_INTAKE_LABEL!r} is missing from {ORG}/{repo}; "
            "no mutation performed"
        ) from exc

    labels = {
        label.get("name")
        for label in issue.get("labels", [])
        if isinstance(label, dict) and isinstance(label.get("name"), str)
    }
    trigger_state = "already-triggered"
    if MIMIR_INTAKE_LABEL not in labels:
        _rest_post(f"{issue_path}/labels", {"labels": [MIMIR_INTAKE_LABEL]})
        trigger_state = "applied"

    readback = _rest_get(issue_path)
    if not isinstance(readback, dict):
        raise RuntimeError(f"Could not read back {ORG}/{repo}#{number}; refusing success")
    readback_labels = {
        label.get("name")
        for label in readback.get("labels", [])
        if isinstance(label, dict) and isinstance(label.get("name"), str)
    }
    if MIMIR_INTAKE_LABEL not in readback_labels:
        raise RuntimeError(
            f"{MIMIR_INTAKE_LABEL!r} was not present in issue readback; refusing success"
        )

    _out(
        {
            "action": "assign-mimir",
            "issue_url": readback.get("html_url"),
            "repository": coverage["repository"],
            "number": number,
            "trigger": {"label": MIMIR_INTAKE_LABEL, "state": trigger_state},
            "coverage": coverage,
            "objective_fields": _mimir_objective_fields(repo, number),
            "expected_team_mimir_route": coverage["route"],
            "actor": actor,
            "authority": role,
        },
        fmt,
    )


# ===========================
# ISSUE WRITE VERBS (U3 — #279)
# ===========================


def issue_close(repo: str, number: int, fmt: str = "text") -> None:
    """Close a GitHub issue. Idempotent: re-closing an already-closed issue succeeds."""
    _rest_patch(f"repos/{ORG}/{repo}/issues/{number}", {"state": "closed"})
    _out({"action": "closed", "repo": repo, "number": number}, fmt)


def issue_reopen(repo: str, number: int, fmt: str = "text") -> None:
    """Reopen a closed GitHub issue. Idempotent: re-opening an open issue succeeds."""
    _rest_patch(f"repos/{ORG}/{repo}/issues/{number}", {"state": "open"})
    _out({"action": "reopened", "repo": repo, "number": number}, fmt)


def issue_comment(repo: str, number: int, body: str, fmt: str = "text") -> None:
    """Post a comment on a GitHub issue. Plain POST — consumer's idempotency ledger
    (KTD4) ensures one comment per meaningful transition; this verb just posts."""
    result = _rest_post(f"repos/{ORG}/{repo}/issues/{number}/comments", {"body": body})
    _out(
        {"action": "commented", "repo": repo, "number": number, "comment_id": result.get("id")}, fmt
    )


def issue_label_add(repo: str, number: int, label: str, fmt: str = "text") -> None:
    """Add a label to a GitHub issue. Idempotent: GitHub no-ops if the label is
    already present (returns 200)."""
    _rest_post(f"repos/{ORG}/{repo}/issues/{number}/labels", {"labels": [label]})
    _out({"action": "label_added", "repo": repo, "number": number, "label": label}, fmt)


def issue_label_remove(repo: str, number: int, label: str, fmt: str = "text") -> None:
    """Remove a label from a GitHub issue. Idempotent: treats 404 (label already
    absent) as success; lets other errors propagate for the U4 retry path.

    The label is URL-encoded into the path — label names routinely contain spaces (``good first
    issue``) or ``/``, which would otherwise yield a malformed/mis-targeted path. Note the 404 catch
    is deliberately broad (a 404 from a wrong issue/repo is also treated as no-op) — a documented
    idempotency tradeoff; distinguishing the causes would need an extra existence probe.
    """
    from urllib.parse import quote

    label_seg = quote(label, safe="")
    try:
        _rest_delete(f"repos/{ORG}/{repo}/issues/{number}/labels/{label_seg}")
    except ApiNotFoundError:
        # Label was already absent — idempotent success.
        _out({"action": "label_remove_noop", "repo": repo, "number": number, "label": label}, fmt)
        return
    _out({"action": "label_removed", "repo": repo, "number": number, "label": label}, fmt)


def flow_link_sub_issue(
    parent_repo: str,
    parent_number: int,
    child_repo: str,
    child_number: int,
    fmt: str,
) -> None:
    """Link child as a native GitHub sub-issue of parent. Uses the REST
    sub-issues API. Cross-repo supported. Idempotent — re-POST returns
    HTTP 422 with 'already exists' which we treat as success."""
    # Look up child's database ID (the sub-issues API uses db_id, not node id)
    try:
        child_data = _rest_get(f"repos/{ORG}/{child_repo}/issues/{child_number}")
    except RuntimeError as e:
        raise RuntimeError(f"Could not fetch child {child_repo}#{child_number}: {e}") from e
    child_db_id = child_data.get("id")
    if not isinstance(child_db_id, int):
        raise RuntimeError(
            f"Child {child_repo}#{child_number} returned no integer 'id'; "
            f"got {child_db_id!r}. Cannot link."
        )

    # Validate parent exists + is an issue (not a PR)
    try:
        parent_data = _rest_get(f"repos/{ORG}/{parent_repo}/issues/{parent_number}")
    except RuntimeError as e:
        raise RuntimeError(f"Could not fetch parent {parent_repo}#{parent_number}: {e}") from e
    if "pull_request" in parent_data:
        raise RuntimeError(
            f"Parent {parent_repo}#{parent_number} is a PR, not an issue. "
            f"Sub-issues require an issue parent."
        )

    # POST the link. Endpoint is /repos/{owner}/{repo}/issues/{N}/sub_issues
    # with body {"sub_issue_id": <child_db_id>}. Idempotent on duplicate.
    try:
        _rest_post(
            f"repos/{ORG}/{parent_repo}/issues/{parent_number}/sub_issues",
            {"sub_issue_id": child_db_id},
        )
        _out(
            f"Linked {child_repo}#{child_number} as sub-issue of {parent_repo}#{parent_number}",
            fmt,
        )
    except ApiAlreadyExistsError:
        # Idempotency: 422 with a duplicate-resource hint = already linked.
        # Treat as success.
        _out(
            f"Already linked: {child_repo}#{child_number} is already a "
            f"sub-issue of {parent_repo}#{parent_number} (idempotent re-run).",
            fmt,
        )


def flow_unlink_sub_issue(
    parent_repo: str,
    parent_number: int,
    child_repo: str,
    child_number: int,
    fmt: str,
) -> None:
    """Remove a native sub-issue relationship without closing either issue.

    Both issues are fetched first so a 404 from DELETE can safely mean the
    relationship is already absent rather than a typo in the repo or number.
    """
    try:
        child_data = _rest_get(f"repos/{ORG}/{child_repo}/issues/{child_number}")
    except RuntimeError as e:
        raise RuntimeError(f"Could not fetch child {child_repo}#{child_number}: {e}") from e
    child_db_id = child_data.get("id")
    if not isinstance(child_db_id, int):
        raise RuntimeError(
            f"Child {child_repo}#{child_number} returned no integer 'id'; "
            f"got {child_db_id!r}. Cannot unlink."
        )

    try:
        parent_data = _rest_get(f"repos/{ORG}/{parent_repo}/issues/{parent_number}")
    except RuntimeError as e:
        raise RuntimeError(f"Could not fetch parent {parent_repo}#{parent_number}: {e}") from e
    if "pull_request" in parent_data:
        raise RuntimeError(
            f"Parent {parent_repo}#{parent_number} is a PR, not an issue. "
            f"Sub-issues require an issue parent."
        )

    try:
        _rest_delete(
            f"repos/{ORG}/{parent_repo}/issues/{parent_number}/sub_issue",
            {"sub_issue_id": child_db_id},
        )
    except ApiNotFoundError:
        _out(
            f"Already unlinked: {child_repo}#{child_number} is not a "
            f"sub-issue of {parent_repo}#{parent_number} (idempotent re-run).",
            fmt,
        )
        return

    _out(
        f"Unlinked {child_repo}#{child_number} from {parent_repo}#{parent_number}",
        fmt,
    )


def flow_verify_label(
    repo: str,
    name: str,
    color: str | None,
    description: str | None,
    fmt: str,
) -> None:
    """Self-healing label create. If the label exists on the repo, no-op.
    If 404, create with given color + description. Auth/rate-limit/server
    errors propagate as their typed exceptions — NOT silently treated as
    missing (which would create labels under the wrong auth context)."""
    # Probe for existence. The try/except/else makes the two-branch nature
    # explicit: success (label exists) vs ApiNotFoundError (need to create).
    # Other typed exceptions (ApiAuthError, ApiRateLimitedError, generic
    # GhApiError) propagate to the caller.
    try:
        _gh(["api", f"repos/{ORG}/{repo}/labels/{name}"])
    except ApiNotFoundError:
        pass  # fall through to create
    else:
        _out(f"Label '{name}' already exists on {ORG}/{repo} (no-op).", fmt)
        return

    # 404 — create the label
    body: dict[str, str] = {"name": name}
    if color:
        body["color"] = color.lstrip("#")  # GH API rejects leading '#'
    if description:
        body["description"] = description
    try:
        _rest_post(f"repos/{ORG}/{repo}/labels", body)
    except ApiAlreadyExistsError:
        # Race: another process created the label between our probe and POST.
        # Idempotency contract — treat as success.
        _out(
            f"Label '{name}' was just created (race detected; treating as no-op).",
            fmt,
        )
        return
    _out(f"Created label '{name}' on {ORG}/{repo}.", fmt)


# ===========================
# CARD VALIDATOR (generated-data-backed pre-flight, mirrors home-lab card_validator.py)
# ===========================
# Pre-flight-checks an issue body before plan-review fires. This is the
# ALGORITHM (control flow) only — its DATA (the 6 required H3 headers, the
# regexes, the placeholder set) is GENERATED in infiquetra-sdlc
# (`tools/docs/gen_issue_contract.py` from the `issue_fields` block of
# `config/sdlc-schema.json`) and VENDORED here as
# `config/generated/issue_contract_shim.py` (carried with a pinned SHA256 + a
# consumer-side parity gate). When the contract changes, the shim DATA is
# re-vendored from sdlc and this algorithm is left untouched (KTD2). The shim is
# shaped as a drop-in: it carries `REQUIRED_H3_HEADERS` / `OPTIONAL_H3_HEADERS`
# and the named regex source strings (`HEADER_RE_PATTERN` / `CHECKLIST_RE_PATTERN`
# / `CODE_BLOCK_RE_PATTERN` / `PATH_LINE_RE_PATTERN`) + a LOWERCASED
# `PLACEHOLDER_LINES` set (the shim compares `ln.lower() in _PLACEHOLDER_LINES`).
#
# Import mechanism: load the vendored shim BY PATH relative to this file
# (`__file__`-relative), so it resolves whether `sdlc_manager` is imported as a
# top-level module in the test suite (tests put `scripts/` on sys.path) OR run
# directly as the CLI. Loading by path means resolution does NOT depend on
# `config/generated/` being on sys.path or being an importable package.
_SHIM_DATA_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "generated" / "issue_contract_shim.py"
)
_CONTRACT_DATA_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "generated" / "issue_contract_data.py"
)
_shim_spec = importlib.util.spec_from_file_location("issue_contract_shim", _SHIM_DATA_PATH)
if _shim_spec is None or _shim_spec.loader is None:  # pragma: no cover - defensive
    raise ImportError(f"vendored issue-contract shim not loadable at {_SHIM_DATA_PATH}")
_shim = importlib.util.module_from_spec(_shim_spec)
_shim_spec.loader.exec_module(_shim)
_contract_spec = importlib.util.spec_from_file_location("issue_contract_data", _CONTRACT_DATA_PATH)
if _contract_spec is None or _contract_spec.loader is None:  # pragma: no cover - defensive
    raise ImportError(f"vendored issue-contract data not loadable at {_CONTRACT_DATA_PATH}")
_contract = importlib.util.module_from_spec(_contract_spec)
_contract_spec.loader.exec_module(_contract)

# DATA imported from the vendored shim (NOT hand-maintained here). A named regex
# group is also positional group 1, so `HEADER_RE_PATTERN`'s `(?P<label>...)` is
# a drop-in for the prior `m.group(1)` extraction in `_split_sections` below.
_REQUIRED_H3_HEADERS = _shim.REQUIRED_H3_HEADERS
_OPTIONAL_H3_HEADERS = _shim.OPTIONAL_H3_HEADERS
_CONTRACT_FIELD_HEADERS = _contract.FIELD_HEADERS
_CONTRACT_REQUIRED_MATRIX = _contract.REQUIRED_MATRIX
_CONTRACT_AUTO_FIELDS = frozenset(_CONTRACT_REQUIRED_MATRIX.get("auto_populated_fields", ()))
_HEADER_RE = re.compile(_shim.HEADER_RE_PATTERN, re.MULTILINE)
_CHECKLIST_RE = re.compile(_shim.CHECKLIST_RE_PATTERN, re.MULTILINE)
_CODE_BLOCK_RE = re.compile(_shim.CODE_BLOCK_RE_PATTERN, re.MULTILINE)
_PATH_LINE_RE = re.compile(_shim.PATH_LINE_RE_PATTERN, re.MULTILINE)
# R2/KTD8 executable-acceptance regex: the acceptance field must name a runnable
# check (a `code span` or a ``` fenced block). DATA from the vendored shim.
_ACCEPTANCE_EXECUTABLE_RE = re.compile(_shim.ACCEPTANCE_EXECUTABLE_RE_PATTERN, re.MULTILINE)
# R4: explicit `_none_` declaration accepted for context-links presence. The
# none-marker is `_none_` / `none` / `None` (case-insensitive); hard-coded here to
# match the vendored CONTEXT_PARSING none-marker the home-lab validator uses.
_NONE_MARKER_RE = re.compile(r"^_?none_?$", re.IGNORECASE)
# Already LOWERCASED in the vendored shim to match the `.lower()` compare below.
_PLACEHOLDER_LINES = frozenset(_shim.PLACEHOLDER_LINES)


def _split_sections(body: str) -> dict[str, str]:
    """Split a card body on `### H3` headers. Returns {header_text: section_text}."""
    matches = list(_HEADER_RE.finditer(body))
    sections: dict[str, str] = {}
    for i, m in enumerate(matches):
        header = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections[header] = body[start:end].strip()
    return sections


def validate_card_body(body: str) -> tuple[bool, list[str]]:
    """Run the card_validator schema check on an issue body.

    Mirrors home-lab card_validator.py's high-leverage checks. When that
    file's contract changes, update this shim in the same PR.

    Returns (is_valid, errors). The checks (mirror the home-lab validator's
    always-required, body-only surface — the shim has no Risk/issue-type input,
    so the risk-conditional matrix R5-R7 is enforced by the authoritative
    home-lab gate, not here):
      1. All required H3 sections present (now incl. Intent and Context library
         links per the U8 context package).
      2. Acceptance criteria has at least one `- [ ]` / `* [ ]` checklist item.
      2b. Acceptance criteria is EXECUTABLE (R2/KTD8): a criterion names a
         runnable check — a `code span` or a ``` fenced block.
      3. Verification has at least one fenced code block (≥2 ``` markers).
      4. Files expected to change has at least one path-like line.
      5. No required section consists of only placeholder lines — EXCEPT the
         Context library links `_none_` declaration (R4), which is a valid
         "no link applies" marker, not leftover placeholder chrome.
    """
    errors: list[str] = []
    sections = _split_sections(body)
    section_names = set(sections.keys())

    # 1. Required headers present
    missing = [h for h in _REQUIRED_H3_HEADERS if h not in section_names]
    if missing:
        errors.append(f"Missing required H3 sections: {missing}")

    # 2 + 2b. Acceptance criteria: a checklist item AND an executable criterion.
    if "Acceptance criteria" in sections:
        ac = sections["Acceptance criteria"]
        if not _CHECKLIST_RE.search(ac):
            errors.append(
                "'Acceptance criteria' has no `- [ ]` checklist item "
                "(card_validator requires at least one)"
            )
        elif not _ACCEPTANCE_EXECUTABLE_RE.search(ac):
            errors.append(
                "'Acceptance criteria' is not executable (card_validator "
                "requires each criterion to name a runnable check -- a `code "
                "span` or a ``` fenced block -- with its expected result)"
            )

    # 3. Verification has ≥1 fenced code block
    if "Verification" in sections:
        v = sections["Verification"]
        # Need at least 2 ``` markers to form one fenced block
        if len(_CODE_BLOCK_RE.findall(v)) < 2:
            errors.append(
                "'Verification' has no fenced code block "
                "(card_validator requires at least one ``` block)"
            )

    # 4. Files expected has ≥1 path-like line
    if "Files expected to change" in sections:
        f = sections["Files expected to change"]
        if not _PATH_LINE_RE.search(f):
            errors.append(
                "'Files expected to change' has no path-like line "
                "(card_validator requires at least one `dir/file` style entry)"
            )

    # 5. No placeholder-only sections (Context library links `_none_` exempt).
    for header in _REQUIRED_H3_HEADERS:
        if header not in sections:
            continue
        text = sections[header].strip()
        # R4: a whole-field `_none_` on Context library links is a valid
        # declaration, not a placeholder-only section.
        if header == "Context library links" and _NONE_MARKER_RE.match(text):
            continue
        if not text:
            errors.append(f"'{header}' is empty")
            continue
        # Strip blank lines + check whether all remaining lines are placeholders
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if lines and all(ln.lower() in _PLACEHOLDER_LINES for ln in lines):
            errors.append(f"'{header}' contains only placeholder text")

    return (len(errors) == 0, errors)


def _rule_matches(rule_value: str, actual: str | None) -> bool:
    return rule_value == "*" or rule_value == (actual or "")


def _required_contract_field_keys(issue_type: str, risk: str | None) -> list[str]:
    required_by_field = {
        field: bool(_CONTRACT_REQUIRED_MATRIX.get("default_required", False))
        for field in _CONTRACT_REQUIRED_MATRIX["axes"]["field"]
    }
    normalized_risk = risk or "*"
    for rule in _CONTRACT_REQUIRED_MATRIX["rules"]:
        if not _rule_matches(rule["issue_type"], issue_type):
            continue
        if not _rule_matches(rule["risk"], normalized_risk):
            continue
        for field in rule["fields"]:
            required_by_field[field] = bool(rule["required"])
    return [
        field
        for field in _CONTRACT_REQUIRED_MATRIX["axes"]["field"]
        if required_by_field.get(field) and field not in _CONTRACT_AUTO_FIELDS
    ]


def validate_card_body_for_context(
    body: str, issue_type: str, risk: str | None
) -> tuple[bool, list[str]]:
    """Validate a prepared issue body when issue type and risk are known.

    `validate_card_body` intentionally remains body-only for compatibility. This
    wrapper layers the generated required matrix on top for prepared drafts.
    """
    valid, errors = validate_card_body(body)
    sections = _split_sections(body)
    required_headers = [
        _CONTRACT_FIELD_HEADERS[field] for field in _required_contract_field_keys(issue_type, risk)
    ]
    missing = [header for header in required_headers if header not in sections]
    if missing:
        errors.append(
            f"Missing required H3 sections for {issue_type}/{risk or 'unknown-risk'}: {missing}"
        )

    for header in required_headers:
        if header not in sections:
            continue
        text = sections[header].strip()
        if header == "Context library links" and _NONE_MARKER_RE.match(text):
            continue
        if not text:
            errors.append(f"'{header}' is empty")
            continue
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if lines and all(ln.lower() in _PLACEHOLDER_LINES for ln in lines):
            errors.append(f"'{header}' contains only placeholder text")

    return (valid and not errors, errors)


class CardValidationError(RuntimeError):
    """Raised when an issue body fails the card_validator schema check.
    `main()` catches RuntimeError and exits non-zero — using a typed
    subclass lets future callers inspect the failure programmatically
    while preserving the standard CLI exit-code path."""

    def __init__(self, issue_ref: str, errors: list[str]):
        self.issue_ref = issue_ref
        self.errors = errors
        super().__init__(
            f"INVALID: {issue_ref} fails card_validator schema check: " + "; ".join(errors)
        )


def flow_validate_card(repo: str, number: int, fmt: str) -> None:
    """Fetch an issue body via gh, run card_validator, report result.

    Consistent with other flow helpers: raises RuntimeError on failure
    (caught by main() → exit 1). Does NOT call sys.exit() directly —
    that would bypass main()'s formatted-error path and break programmatic
    callers who import this function."""
    issue_ref = f"{repo}#{number}"
    try:
        data = _rest_get(f"repos/{ORG}/{repo}/issues/{number}")
    except RuntimeError as e:
        raise RuntimeError(f"Could not fetch issue {issue_ref}: {e}") from e
    body = data.get("body") or ""
    if not body:
        # Empty body fails trivially — report via the standard error path
        raise CardValidationError(issue_ref, ["Issue has empty body"])

    is_valid, errors = validate_card_body(body)
    if is_valid:
        _out(f"VALID: {issue_ref} passes card_validator schema check.", fmt)
        return

    # For JSON callers, emit the structured payload before raising.
    # The CardValidationError still propagates so main() exits 1.
    if fmt == "json":
        _out({"valid": False, "errors": errors, "issue": issue_ref}, fmt)
    else:
        print(f"INVALID: {issue_ref} fails card_validator schema check:")
        for err in errors:
            print(f"   - {err}")
    raise CardValidationError(issue_ref, errors)


# ===========================
# CONFIG OPERATIONS
# ===========================


def config_show(fmt: str) -> None:
    """Display loaded configuration."""
    config = load_config()
    sdlc_path = config.get("sdlc_path", "unknown")

    if fmt == "json":
        _out(config, fmt)
        return

    print("\nInfiquetra SDLC Manager Configuration")
    print(f"SDLC Path: {sdlc_path}")
    print(f"Organization: {ORG}")

    pm = config.get("project_mappings", {})
    projects = pm.get("projects", {})
    print(f"\nProjects: {len(projects)}")
    for name, proj in projects.items():
        print(
            f"  - {name}: #{proj['number']} — {proj.get('name', '')} ({len(proj.get('repositories', []))} repos)"
        )

    labels = config.get("labels", {}).get("labels", [])
    print(f"\nLabels: {len(labels)} defined")

    beads = config.get("legacy_rollout_config", {})
    summary = beads.get("summary", {})
    print(
        f"\nRollout: {summary.get('completed', 0)}/{summary.get('total_repos', 0)} repos complete"
    )

    # Per-user defaults (Phase C)
    defaults = load_user_defaults()
    print(f"\nUser defaults: {_USER_DEFAULTS_PATH}")
    if defaults:
        for key in _USER_DEFAULTS_KEYS:
            if key in defaults:
                print(f"  {key:22s} = {defaults[key]!r}")
    else:
        print("  (none — run `config init-defaults` to seed)")


def config_show_defaults(fmt: str) -> None:
    """Display the current per-user defaults from ~/.claude/sdlc-defaults.json."""
    defaults = load_user_defaults()
    if fmt == "json":
        _out({"path": str(_USER_DEFAULTS_PATH), "defaults": defaults}, fmt)
        return
    print(f"\nUser defaults: {_USER_DEFAULTS_PATH}")
    if not defaults:
        print("  (none set — run `config init-defaults` to seed)")
        return
    for key in _USER_DEFAULTS_KEYS:
        if key in defaults:
            print(f"  {key:22s} = {defaults[key]!r}")
        else:
            print(f"  {key:22s} = (not set)")


def config_init_defaults(non_interactive: bool, fmt: str) -> None:
    """First-run wizard: seed ~/.claude/sdlc-defaults.json.

    Interactive by default — prompts for each key with the existing value
    (or a sensible suggestion) as the default. Type a value to override;
    press Enter to accept the suggestion; type '-' to skip / unset.

    --non-interactive seeds with auto-detected values only (gh login as
    assignee; default_project=<sole-project> ONLY if exactly one project
    mapped in config — no guessing on multi-project orgs). Useful for
    CI / scripted setup.

    **Both modes preserve existing values** — running this command again
    against an already-populated defaults file does NOT clobber it. Keys
    not recognized by the current schema (e.g., from a future plugin
    version) are also preserved. Re-running is safe."""
    existing = load_user_defaults()
    new: dict[str, Any] = dict(existing)  # start from existing; preserve unknown keys

    # Always re-fetch the gh login (in case the operator changed accounts)
    gh_login = _fetch_gh_login()

    # Auto-detect default_project if exactly one project is mapped
    auto_project: str | None = None
    try:
        cfg = load_config()
        projects = cfg.get("project_mappings", {}).get("projects", {})
        if len(projects) == 1:
            auto_project = next(iter(projects.keys()))
    except Exception:
        pass  # config load failed; not fatal for the wizard

    # Field-by-field seeding. For each key, the order is:
    #   suggested = existing[key] OR auto-detected OR a built-in default
    suggestions = {
        "assignee": gh_login or existing.get("assignee"),
        "default_project": existing.get("default_project") or auto_project,
        "default_status": existing.get("default_status") or "Backlog",
        "default_priority": existing.get("default_priority") or "medium-priority",
        "default_initiative": existing.get("default_initiative"),  # no default
        "default_objective": existing.get("default_objective"),  # no default
        "preferred_repos": existing.get("preferred_repos") or [],
    }

    if non_interactive:
        # Seed with suggestions only
        for key in _USER_DEFAULTS_KEYS:
            if suggestions.get(key) not in (None, []):
                new[key] = suggestions[key]
        save_user_defaults(new)
        if fmt == "json":
            _out({"saved_to": str(_USER_DEFAULTS_PATH), "defaults": new}, fmt)
        else:
            print(f"Seeded {_USER_DEFAULTS_PATH} with auto-detected values:")
            for key in _USER_DEFAULTS_KEYS:
                if key in new:
                    print(f"  {key:22s} = {new[key]!r}")
        return

    # Interactive wizard
    print(f"\nFirst-run wizard for {_USER_DEFAULTS_PATH}")
    print("Press Enter to accept the [default]; type a value to override; type '-' to skip.\n")

    for key in _USER_DEFAULTS_KEYS:
        suggestion = suggestions.get(key)
        if key == "preferred_repos":
            current = ", ".join(suggestion) if suggestion else ""
            prompt = f"  preferred_repos (comma-separated) [{current}]: "
            try:
                answer = input(prompt).strip()
            except (EOFError, KeyboardInterrupt):
                print("\nWizard aborted (no changes saved).")
                return
            if answer == "-":
                new.pop(key, None)
            elif answer:
                new[key] = [r.strip() for r in answer.split(",") if r.strip()]
            elif suggestion:
                new[key] = suggestion
            continue

        display = repr(suggestion) if suggestion is not None else "(not set)"
        prompt = f"  {key} [{display}]: "
        try:
            answer = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nWizard aborted (no changes saved).")
            return
        if answer == "-":
            new.pop(key, None)
        elif answer:
            new[key] = answer
        elif suggestion is not None:
            new[key] = suggestion
        # else: leave unset

    save_user_defaults(new)
    print(f"\nSaved to {_USER_DEFAULTS_PATH}")
    config_show_defaults(fmt)


# ===========================
# CLI
# ===========================

_ISSUE_TYPES = (
    "capability",
    "enhancement",
    "defect",
    "exploration",
    "context-update",
)
# Active prepared-issue teams (KTD17): Asgard (shaping/rapid-action profile) and
# CAMPPS (strict actionable dispatch profile on the initiative execution board).
# Mount Olympus is retired historical context and is not an active prepare target.
_TEAM_CHOICES = ("asgard", "campps")
_TEAM_SAFE_STATUSES = {"asgard": "Shaping", "campps": "Idea"}
_DISPATCH_ACTIONABLE_TYPES = frozenset({"capability", "enhancement", "defect"})
_ISSUE_TYPE_LABELS = {
    "capability": ["capability", "needs-plan"],
    "enhancement": ["enhancement", "needs-plan"],
    "defect": ["defect", "needs-plan"],
    "exploration": ["exploration", "research"],
    "context-update": ["context-update", "documentation"],
}
_PREPARED_DRAFT_DIR = Path("docs") / "sdlc-issue-drafts"
_HANDOFF_MATURITY_CHOICES = (
    "idea-ready",
    "requirements-ready",
    "plan-ready",
    "resume-ready",
    "deferred-context",
)
_SOURCE_SEARCH_DIRS = (
    Path(".claude") / "saga",
    Path("docs") / "plans",
    Path("docs") / "brainstorms",
    Path("docs") / "ideation",
    Path("docs") / "reviews",
    Path("docs") / "work-sessions",
    Path("docs") / "sdlc-issue-drafts",
)
_SOURCE_HINT_DIRS = {
    "plan": (Path("docs") / "plans",),
    "brainstorm": (Path("docs") / "brainstorms",),
    "requirements": (Path("docs") / "brainstorms",),
    "idea": (Path("docs") / "ideation",),
    "ideation": (Path("docs") / "ideation",),
    "review": (Path("docs") / "reviews",),
    "work": (Path("docs") / "work-sessions",),
    "resume": (Path("docs") / "work-sessions", Path(".claude") / "saga"),
    "draft": (Path("docs") / "sdlc-issue-drafts",),
}

_CONTRACT_ISSUE_TYPES = frozenset(
    {
        "capability",
        "enhancement",
        "defect",
    }
)
# Issue types where the capability-adaptive fields are relevant (size,
# etc.). The orchestrator's planner reads these to inform sequencing /
# capacity decisions; non-capability cards don't need them.
#
# IMPORTANT — PROJECT FIELD REALITY (verified 2026-05-04):
# As of today, the only single-select field on the Olympus project (#1) is
# `Status`. `Initiative`, `Objective`, `Capability Size`, `Business Value`,
# `Technical Risk`, `Target Quarter` are all "decided, not yet created" per
# Phase A carry-over #2 in `infiquetra-sdlc`. The interactive flow is built
# to handle the post-create world (per-project schema discovery silently
# skips prompts for fields the project doesn't expose), so today operators
# will see ONLY the Status prompt. The skip is intentional, not a bug.
# When the operator runs the field-creation runbook in
# `infiquetra-sdlc/docs/operations/operational-reference.md`, the
# additional prompts light up automatically.
_CAPABILITY_ADAPTIVE_TYPES = frozenset({"capability"})

# ---------------------------------------------------------------------------
# Prepared-issue compile + approve machinery (U11)
# ---------------------------------------------------------------------------
# Two ORTHOGONAL durable axes, kept separate on purpose:
#   - `state`          : the creation-pipeline state (blocked -> ready_to_create
#                        -> mapping_pending -> created). UNCHANGED by U11 so the
#                        existing readiness/create-prepared contract + tests hold.
#   - `approval_state` : the human gate U11 adds. A cleanly-compiled draft lands
#                        in NEEDS_OPERATOR_APPROVAL (recorded durably in BOTH the
#                        sidecar and the draft front-matter) and is NOT
#                        auto-created. Batch approval transitions it to APPROVED.
# A blocked draft has approval_state=None — it never reaches the gate.
_PREPARE_STATE_BLOCKED = "blocked"
_PREPARE_STATE_READY = "ready_to_create"
_APPROVAL_NEEDS_OPERATOR = "needs_operator_approval"
_APPROVAL_APPROVED = "approved"
# approval_state values from which a draft may be batch-approved. Only a draft
# sitting in the gate is approvable; an already-approved draft is SKIPPED (its
# approved_at timestamp is preserved, not rewritten) so approval is a true no-op.
_APPROVABLE_APPROVAL_STATES = frozenset({_APPROVAL_NEEDS_OPERATOR})

# Project FIELDS a prepared card carries, computed offline at prepare time from
# the issue's own metadata and RECORDED in the sidecar for a future create-time
# consumer (consumption is a follow-up unit, not wired here). These are card
# VALUES (not the project's live field schema): "field-schema discovery" against
# a real project stays behind `_resolve_project_field` (live GraphQL), which
# `flow set-field` uses. Lifecycle Origin is the auto-populated field (R10) —
# never author-supplied. Risk maps to the `Technical Risk` single-select named
# in the PROJECT FIELD REALITY note above.
_PREPARED_FIELD_RISK = "Technical Risk"
_PREPARED_FIELD_OBJECTIVE = "Objective"
_PREPARED_FIELD_ISSUE_TYPE = "Issue Type"
_PREPARED_FIELD_LIFECYCLE_ORIGIN = "Lifecycle Origin"


@dataclass
class PreparedReadiness:
    profile: str
    passed: bool
    blocking_gaps: list[str]
    warnings: list[str]


@dataclass
class SourceArtifact:
    ref: str
    kind: str
    title: str
    content: str
    inferred_maturity: str
    path: str | None = None
    url: str | None = None
    branch: str | None = None


@dataclass
class PreparedIssue:
    title: str
    repo: str
    issue_type: str
    team: str
    project: str
    status: str
    labels: list[str]
    risk: str | None
    mode: str | None
    body: str
    handoff_maturity: str | None = None
    source_artifact: dict[str, Any] | None = None
    project_fields: dict[str, str] | None = None
    draft_path: str | None = None
    sidecar_path: str | None = None


def _prepared_project_fields(
    issue: PreparedIssue, source_artifact: SourceArtifact | None
) -> dict[str, str]:
    """Resolve the project-field values a prepared card will carry (U11).

    Pure/offline: derives values from the issue's own metadata + the handoff
    source, so tests run without a live GitHub call. These values are RECORDED
    in the sidecar (`project_fields`) for a LATER create-time consumer to set on
    the live card — that consumption is a FOLLOW-UP unit and is NOT wired here.
    `create` does not yet read `project_fields`, and `_resolve_project_field`
    currently RAISES on a field the live project doesn't expose (per-field
    tolerance for not-yet-created fields is also a follow-up, not implemented
    here). We only record non-empty values so the sidecar reflects what we could
    populate; do not read more into the presence of this key than "recorded".
    """
    fields: dict[str, str] = {_PREPARED_FIELD_ISSUE_TYPE: issue.issue_type}
    if issue.risk:
        fields[_PREPARED_FIELD_RISK] = issue.risk
    # Lifecycle Origin is auto-populated from the handoff maturity that drove
    # this draft (R10) — it is the compile step's record of "where this card
    # came from", never an author-required input.
    if issue.handoff_maturity:
        fields[_PREPARED_FIELD_LIFECYCLE_ORIGIN] = issue.handoff_maturity
    # Objective is carried only when the handoff source names one; we don't
    # invent an Objective the operator didn't supply.
    if source_artifact and source_artifact.ref:
        fields[_PREPARED_FIELD_OBJECTIVE] = source_artifact.ref
    return fields


@dataclass
class MutationStep:
    action: str
    detail: str


@dataclass
class MutationPlan:
    draft_path: str
    repo: str
    issue_type: str
    team: str
    project: str
    status: str
    steps: list[MutationStep]
    mapping_missing: bool = False


def _issue_expected_labels(issue_type: str) -> list[str]:
    return list(_ISSUE_TYPE_LABELS.get(issue_type, [issue_type]))


def _normalize_label_list(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        return [item.strip() for item in raw.split(",") if item.strip()]
    return []


def _source_artifact_payload(artifact: SourceArtifact | None) -> dict[str, Any] | None:
    if not artifact:
        return None
    payload = asdict(artifact)
    content = str(payload.pop("content", "")).strip()
    if content:
        payload["content_excerpt"] = content[:1200]
    return payload


def _markdown_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip() or fallback
    return fallback


def _infer_maturity_from_path(path: Path) -> str:
    normalized = path.as_posix()
    if "docs/ideation/" in normalized:
        return "idea-ready"
    if "docs/brainstorms/" in normalized:
        return "requirements-ready"
    if "docs/plans/" in normalized or "docs/reviews/" in normalized:
        return "plan-ready"
    if "docs/work-sessions/" in normalized or "docs/sdlc-issue-drafts/" in normalized:
        return "resume-ready"
    if ".claude/saga/" in normalized:
        return "resume-ready"
    return "requirements-ready"


def _infer_kind_from_path(path: Path) -> str:
    normalized = path.as_posix()
    if "docs/ideation/" in normalized:
        return "ideation"
    if "docs/brainstorms/" in normalized:
        return "brainstorm"
    if "docs/plans/" in normalized:
        return "plan"
    if "docs/reviews/" in normalized:
        return "review"
    if "docs/work-sessions/" in normalized:
        return "work-session"
    if "docs/sdlc-issue-drafts/" in normalized:
        return "prepared-draft"
    if ".claude/saga/" in normalized:
        return "loop-state"
    return "local-file"


def _source_from_local_path(path: Path, root: Path | None = None) -> SourceArtifact:
    root = root or Path.cwd()
    resolved = path.expanduser()
    if not resolved.is_absolute():
        resolved = root / resolved
    if not resolved.exists() or not resolved.is_file():
        raise RuntimeError(f"Source artifact path does not exist or is not a file: {path}")
    content = resolved.read_text(encoding="utf-8")
    try:
        display_path = resolved.relative_to(root).as_posix()
    except ValueError:
        display_path = resolved.as_posix()
    return SourceArtifact(
        ref=display_path,
        kind=_infer_kind_from_path(Path(display_path)),
        title=_markdown_title(content, resolved.stem),
        content=content,
        inferred_maturity=_infer_maturity_from_path(Path(display_path)),
        path=display_path,
    )


def _source_from_github_url(url: str) -> SourceArtifact:
    match = re.match(
        r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/"
        r"(?P<kind>issues|pull)/(?P<number>\d+)(?:\b|/|$)",
        url.strip(),
    )
    if not match:
        raise RuntimeError(f"Unsupported GitHub source URL: {url}")

    owner = match.group("owner")
    repo = match.group("repo")
    number = match.group("number")
    is_pr = match.group("kind") == "pull"
    resource = "pr" if is_pr else "issue"
    try:
        raw = _gh(
            [
                resource,
                "view",
                number,
                "--repo",
                f"{owner}/{repo}",
                "--json",
                "title,body,url",
            ]
        )
        data = json.loads(raw)
    except Exception as e:
        raise RuntimeError(f"Could not fetch GitHub source artifact {url}: {e}") from e

    title = str(data.get("title") or f"{repo}#{number}").strip()
    body = str(data.get("body") or "").strip()
    content = f"# {title}\n\n{body}".strip()
    return SourceArtifact(
        ref=f"{owner}/{repo}#{number}",
        kind="github-pr" if is_pr else "github-issue",
        title=title,
        content=content,
        inferred_maturity="resume-ready" if is_pr else "requirements-ready",
        url=str(data.get("url") or url),
    )


def _source_from_branch_ref(ref: str, root: Path | None = None) -> SourceArtifact:
    root = root or Path.cwd()
    branch = ref.removeprefix("branch:").strip() or "HEAD"
    if branch in {"current", "current-branch", "current branch"}:
        branch = _run_git_command(["git", "branch", "--show-current"], root) or "HEAD"
    head = _run_git_command(["git", "rev-parse", branch], root)
    try:
        upstream = _run_git_command(
            ["git", "rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}"], root
        )
    except RuntimeError:
        upstream = "none"
    status = _run_git_command(["git", "status", "--short", "--branch"], root)
    content = (
        f"# Branch handoff: {branch}\n\n"
        f"- Branch: {branch}\n"
        f"- HEAD: {head}\n"
        f"- Upstream: {upstream}\n\n"
        "## Working tree\n\n"
        f"```text\n{status}\n```\n"
    )
    return SourceArtifact(
        ref=f"branch:{branch}",
        kind="branch",
        title=f"Branch handoff: {branch}",
        content=content,
        inferred_maturity="resume-ready",
        branch=branch,
    )


def _hint_search_dirs(hint: str) -> tuple[Path, ...]:
    lower = hint.lower()
    dirs: list[Path] = []
    for word, paths in _SOURCE_HINT_DIRS.items():
        if word in lower:
            dirs.extend(paths)
    if dirs:
        return tuple(dict.fromkeys(dirs))
    return _SOURCE_SEARCH_DIRS


def _source_matches_hint(path: Path, text: str, hint: str) -> bool:
    lower = hint.lower()
    ignored_terms = set(_SOURCE_HINT_DIRS) | {
        "from",
        "the",
        "this",
        "that",
        "issue",
        "handoff",
        "hand",
        "off",
        "create",
        "using",
        "use",
        "based",
        "for",
    }
    terms = [
        term for term in re.findall(r"[a-z0-9][a-z0-9-]{2,}", lower) if term not in ignored_terms
    ]
    if not terms:
        return True
    haystack = f"{path.stem}\n{text[:2000]}".lower()
    return all(term in haystack for term in terms[:4])


def find_source_artifacts(hint: str, root: Path | None = None) -> list[SourceArtifact]:
    root = root or Path.cwd()
    matches: list[tuple[float, SourceArtifact]] = []
    for rel_dir in _hint_search_dirs(hint):
        search_dir = root / rel_dir
        if not search_dir.exists():
            continue
        for candidate in search_dir.rglob("*.md"):
            if not candidate.is_file():
                continue
            text = candidate.read_text(encoding="utf-8")
            if _source_matches_hint(candidate, text, hint):
                artifact = _source_from_local_path(candidate, root)
                matches.append((candidate.stat().st_mtime, artifact))
    matches.sort(key=lambda item: item[0], reverse=True)
    return [artifact for _, artifact in matches]


def resolve_source_artifact(ref_or_hint: str, root: Path | None = None) -> SourceArtifact:
    root = root or Path.cwd()
    ref = ref_or_hint.strip()
    if not ref:
        raise RuntimeError("Source artifact reference is empty")

    path = Path(ref).expanduser()
    if path.exists() or (not path.is_absolute() and (root / path).exists()):
        return _source_from_local_path(path, root)
    if ref.startswith("https://github.com/"):
        return _source_from_github_url(ref)
    if ref.startswith("branch:") or ref in {"current-branch", "current branch"}:
        return _source_from_branch_ref(ref, root)

    matches = find_source_artifacts(ref, root)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        searched = ", ".join(str(path) for path in _hint_search_dirs(ref))
        raise RuntimeError(f"No source artifact matched {ref!r}. Searched: {searched}")
    choices = ", ".join(artifact.ref for artifact in matches[:10])
    raise RuntimeError(f"Ambiguous source artifact hint {ref!r}. Matches: {choices}")


def _natural_language_source_hint(text: str) -> str | None:
    lower = text.lower()
    if not any(word in lower for word in _SOURCE_HINT_DIRS):
        return None
    if re.search(r"\b(from|handoff|hand off|using|use|based on)\b", lower):
        return text
    return None


def _resolve_prepare_source(
    source_parts: list[str],
    source_file: str | None,
    from_ref: str | None,
    root: Path | None = None,
) -> tuple[str, SourceArtifact | None]:
    root = root or Path.cwd()
    if from_ref:
        artifact = resolve_source_artifact(from_ref, root)
        return artifact.content, artifact
    if source_file:
        artifact = _source_from_local_path(Path(source_file), root)
        return artifact.content, artifact
    if source_parts:
        source = " ".join(source_parts)
        natural_hint = _natural_language_source_hint(source)
        if natural_hint:
            artifact = resolve_source_artifact(natural_hint, root)
            return artifact.content, artifact
        return source, None
    if not sys.stdin.isatty():
        return sys.stdin.read(), None
    raise RuntimeError("Provide source text as an argument, stdin, --source-file, or --from")


def _parse_draft_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    metadata: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()
    return metadata, text[end + 5 :].lstrip()


def _strip_draft_h1(body: str) -> tuple[str | None, str]:
    lines = body.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("# "):
            title = line[2:].strip()
            remaining = "\n".join(lines[index + 1 :]).lstrip()
            return title, remaining
        if line.strip():
            break
    return None, body


def _strip_frontmatter_and_title(text: str) -> tuple[dict[str, str], str]:
    """Strip all leading YAML front-matter blocks and H1 titles from text."""
    current = text.strip()
    merged_metadata: dict[str, str] = {}
    while current.startswith("---\n"):
        metadata, remaining = _parse_draft_frontmatter(current)
        if not metadata and remaining == current:
            break
        merged_metadata.update(metadata)
        current = remaining.strip()
    while True:
        title, remaining = _strip_draft_h1(current)
        if title is None:
            break
        if "title" not in merged_metadata:
            merged_metadata["title"] = title
        current = remaining.strip()
    if "\n\n## Created Issue\n" in current:
        current = current.split("\n\n## Created Issue\n", 1)[0].rstrip()
    elif current.startswith("## Created Issue\n"):
        current = ""
    return merged_metadata, current.strip()


def _render_draft_markdown(issue: PreparedIssue, approval_state: str | None = None) -> str:
    labels = ", ".join(issue.labels)
    frontmatter = [
        "---",
        f"title: {issue.title}",
        f"repo: {issue.repo}",
        f"type: {issue.issue_type}",
        f"team: {issue.team}",
        f"project: {issue.project}",
        f"status: {issue.status}",
        f"labels: {labels}",
    ]
    if issue.risk:
        frontmatter.append(f"risk: {issue.risk}")
    if issue.mode:
        frontmatter.append(f"mode: {issue.mode}")
    if issue.handoff_maturity:
        frontmatter.append(f"handoff_maturity: {issue.handoff_maturity}")
    # Durably record the approval state in the draft front-matter too (U11), so
    # the human gate survives independent of the sidecar (front-matter is what
    # an operator reads when reviewing the draft markdown directly).
    if approval_state:
        frontmatter.append(f"approval_state: {approval_state}")
    frontmatter.append("---")
    _, clean_body = _strip_frontmatter_and_title(issue.body)
    return "\n".join(frontmatter) + f"\n\n# {issue.title}\n\n{clean_body.rstrip()}\n"


def _suggested_next_action(handoff_maturity: str) -> str:
    return {
        "idea-ready": "Use `/plan <issue>` to shape requirements before implementation.",
        "requirements-ready": "Use `/plan <issue>` to create an implementation plan.",
        "plan-ready": "Use `/work <issue>` to execute from the plan-grade context.",
        "resume-ready": "Use `/work <issue>` to resume from the captured work state.",
        "deferred-context": "Clarify current intent before planning or working this issue.",
    }[handoff_maturity]


def _render_handoff_context(
    handoff_maturity: str | None,
    source_artifact: SourceArtifact | None,
) -> str:
    if not handoff_maturity and not source_artifact:
        return ""
    maturity = handoff_maturity or "requirements-ready"
    lines = [
        "### Handoff maturity",
        maturity,
        "",
        "### Suggested next action",
        _suggested_next_action(maturity),
    ]
    if source_artifact:
        lines.extend(
            [
                "",
                "### Source context",
                f"- Source: {source_artifact.ref}",
                f"- Source type: {source_artifact.kind}",
                f"- Source title: {source_artifact.title}",
            ]
        )
        if source_artifact.url:
            lines.append(f"- Source URL: {source_artifact.url}")
        if source_artifact.branch:
            lines.append(f"- Source branch: {source_artifact.branch}")
    return "\n\n" + "\n".join(lines) + "\n"


def _context_links_from_source(source_artifact: SourceArtifact | None) -> str:
    if not source_artifact:
        return "_none_"
    if source_artifact.url:
        return f"- source_context: {source_artifact.url}"
    if source_artifact.path:
        return f"- source_context: {source_artifact.path}"
    return "_none_"


def _contract_field_placeholder(
    field: str,
    source: str,
    source_artifact: SourceArtifact | None,
) -> str:
    if field == "objective":
        return source
    if field == "context_library_links":
        return _context_links_from_source(source_artifact)
    if field == "acceptance_criteria":
        return "- [ ] _No response_"
    return "_No response_"


def _contract_scaffold_body(
    source: str,
    issue_type: str,
    risk: str | None,
    source_artifact: SourceArtifact | None,
) -> str:
    sections: list[str] = []
    for field in _required_contract_field_keys(issue_type, risk):
        header = _CONTRACT_FIELD_HEADERS[field]
        value = _contract_field_placeholder(field, source, source_artifact)
        sections.append(f"### {header}\n{value}")
    return "\n\n".join(sections)


# Issue-carried recommended tier band (#368 AC5): a coarse issue-time seed for
# /plan's per-unit tier table (saga's tier_defaults.resolve_tier_for_plan reads
# it; precedence there is repo overlay > this band > shared registry). The map
# mirrors tier_policy.json's work-shape bands: judgment→opus/high,
# mechanical→sonnet/medium, read-only-survey→sonnet/low.
_TIER_BAND_HEADER = "Recommended Tier Band"
_ISSUE_TYPE_TIER_BANDS: dict[str, tuple[str, str] | None] = {
    "capability": ("opus", "high"),
    "enhancement": ("sonnet", "medium"),
    "defect": ("opus", "high"),
    "exploration": ("sonnet", "low"),
    "context-update": ("sonnet", "medium"),
}


def derive_tier_band(issue_type: str) -> dict[str, str] | None:
    """Type→band mapping for the stamped `### Recommended Tier Band` field (AC5).

    Returns ``{"model", "effort"}`` or None for an unknown type.
    """
    band = _ISSUE_TYPE_TIER_BANDS.get(issue_type)
    if band is None:
        return None
    return {"model": band[0], "effort": band[1]}


def _has_tier_band_section(body: str) -> bool:
    """True when a real H3 tier-band header exists outside fenced code blocks.

    The idempotence guard must be fence-aware, not a substring test: a prose or
    code-block *mention* of the header text (e.g. a Verification section showing
    example output) must not silently suppress the stamp. Mirrored by saga's
    ``tier_defaults._unfenced_lines`` on the parse side of the format contract.
    """
    header_re = re.compile(rf"###\s+{re.escape(_TIER_BAND_HEADER)}\s*")
    in_fence = False
    for line in body.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if not in_fence and header_re.fullmatch(line):
            return True
    return False


def _open_fence_closer(body: str) -> str | None:
    """The marker that closes a fence still open at end-of-body, or None.

    An unclosed fence runs to end-of-document (CommonMark), so a section
    appended after it would render — and parse — as code text. Returns the
    opening marker's own prefix (``` or ~~~) so the closer matches the flavor.
    """
    open_marker: str | None = None
    for line in body.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            open_marker = None if open_marker else stripped[:3]
    return open_marker


def _append_tier_band(body: str, issue_type: str) -> str:
    """Stamp the derived band as an auto-populated H3 section (idempotent).

    Mirrors the Lifecycle Origin discipline: auto-populated at compile time,
    never author-required. The card validator only checks *required* sections,
    so the extra section is accepted as-is. A fence left open at end-of-body is
    closed first — render-neutral for the author's content (the fence ran to
    end-of-document anyway), and it keeps the stamped band a real section
    instead of code text the saga-side parser can never see.
    """
    band = derive_tier_band(issue_type)
    if band is None or _has_tier_band_section(body):
        return body
    base = body.rstrip()
    closer = _open_fence_closer(base)
    if closer is not None:
        base += f"\n{closer}"
    return base + f"\n\n### {_TIER_BAND_HEADER}\n{band['model']}/{band['effort']}\n"


def _source_to_issue_body(
    source: str,
    issue_type: str,
    team: str,
    repo: str,
    risk: str | None,
    mode: str | None,
    handoff_maturity: str | None = None,
    source_artifact: SourceArtifact | None = None,
) -> str:
    """Assemble the issue body, then stamp the recommended tier band (AC5).

    The stamp lives on this wrapper (not the single current call site) so every
    body the compile path emits carries the band — a future call site cannot
    silently miss it.
    """
    body = _source_to_issue_body_unstamped(
        source, issue_type, team, repo, risk, mode, handoff_maturity, source_artifact
    )
    return _append_tier_band(body, issue_type)


def _source_to_issue_body_unstamped(
    source: str,
    issue_type: str,
    team: str,
    repo: str,
    risk: str | None,
    mode: str | None,
    handoff_maturity: str | None = None,
    source_artifact: SourceArtifact | None = None,
) -> str:
    _, clean_source = _strip_frontmatter_and_title(source)
    stripped = clean_source.strip()
    if "### " in stripped:
        if "### Handoff maturity" in stripped:
            return stripped
        return stripped + _render_handoff_context(handoff_maturity, source_artifact)
    if issue_type in _DISPATCH_ACTIONABLE_TYPES:
        return _contract_scaffold_body(
            stripped, issue_type, risk, source_artifact
        ) + _render_handoff_context(handoff_maturity, source_artifact)
    if team == "asgard":
        return f"""### Intent
{stripped}

### Target repo / surface
{repo}

### Mode
{mode or "TBD"}

### Constraints
TBD

### Risk
TBD

### Transfer notes
- [ ] Record any explicit cross-team transfer target, or leave as none.
""" + _render_handoff_context(handoff_maturity, source_artifact)
    return f"""### Objective
{stripped}

### Acceptance criteria
- [ ] TBD

### Out-of-scope / non-goals
TBD

### Files expected to change
TBD

### Tests to add or update
TBD

### Verification
TBD
""" + _render_handoff_context(handoff_maturity, source_artifact)


def _safe_slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:48].strip("-") or "issue"


def _unique_draft_path(draft_dir: Path, title: str) -> Path:
    date_prefix = datetime.now(UTC).strftime("%Y-%m-%d")
    base = f"{date_prefix}-{_safe_slug(title)}"
    candidate = draft_dir / f"{base}.md"
    index = 2
    while candidate.exists() or candidate.with_suffix(".json").exists():
        candidate = draft_dir / f"{base}-{index}.md"
        index += 1
    return candidate


def _read_prepared_issue(draft_path: Path) -> PreparedIssue:
    text = draft_path.read_text(encoding="utf-8")
    metadata, body_with_title = _parse_draft_frontmatter(text)
    h1_title, body = _strip_draft_h1(body_with_title)
    sidecar_path = draft_path.with_suffix(".json")
    if not sidecar_path.exists():
        raise RuntimeError(f"Missing prepared issue sidecar: {sidecar_path}")
    try:
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Malformed prepared issue sidecar {sidecar_path}: {e}") from e
    if not isinstance(sidecar, dict):
        raise RuntimeError(f"Prepared issue sidecar {sidecar_path} is not a JSON object")

    def field(name: str, sidecar_name: str | None = None) -> str:
        value = metadata.get(name) or sidecar.get(sidecar_name or name)
        return str(value).strip() if value is not None else ""

    issue = PreparedIssue(
        title=field("title") or h1_title or draft_path.stem,
        repo=field("repo"),
        issue_type=field("type", "issue_type"),
        team=field("team"),
        project=field("project"),
        status=field("status"),
        labels=_normalize_label_list(metadata.get("labels") or sidecar.get("labels")),
        risk=field("risk") or None,
        mode=field("mode") or None,
        body=body.strip(),
        handoff_maturity=field("handoff_maturity") or None,
        source_artifact=sidecar.get("source_artifact")
        if isinstance(sidecar.get("source_artifact"), dict)
        else None,
        project_fields=sidecar.get("project_fields")
        if isinstance(sidecar.get("project_fields"), dict)
        else None,
        draft_path=str(draft_path),
        sidecar_path=str(sidecar_path),
    )

    for key, value in {
        "repo": issue.repo,
        "type": issue.issue_type,
        "team": issue.team,
        "project": issue.project,
    }.items():
        sidecar_key = "issue_type" if key == "type" else key
        if metadata.get(key) and sidecar.get(sidecar_key) and metadata[key] != sidecar[sidecar_key]:
            raise RuntimeError(
                f"Draft metadata {key}={metadata[key]!r} conflicts with sidecar "
                f"{sidecar_key}={sidecar[sidecar_key]!r}"
            )
        if not value:
            raise RuntimeError(f"Prepared issue draft is missing required metadata: {key}")
    if issue.issue_type not in _ISSUE_TYPES:
        raise RuntimeError(f"Unknown issue type in prepared draft: {issue.issue_type}")
    if issue.team not in _TEAM_CHOICES:
        raise RuntimeError(f"Unknown team in prepared draft: {issue.team}")
    return issue


def _load_intent_envelope() -> Any:
    """Load the canonical fleet intent-envelope module (#380) through the vendored shim.

    Lazy on purpose: only the issue-capture surfaces that touch an envelope pay the
    fleet-core resolution cost; every other verb imports nothing new.
    """
    scripts_dir = str(Path(__file__).resolve().parent / "_bundled")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    # The build-time Fleet Core bundle replaces the upstream fleet_commons_shim, whose
    # resolution ladder is Claude-specific runtime discovery this package must not
    # retain. scripts/bundle_fleet_module.py writes the bundle, so the module is on
    # disk at install time and Fleet Core is never installed separately.
    import intent_envelope  # noqa: PLC0415

    return intent_envelope


def _intent_envelope_readiness_error(body: str) -> str | None:
    """Schema-validate an issue draft's intent-envelope block at capture time (#380).

    Absent block -> ``None`` (the envelope is optional at capture). A present-but-invalid
    block is a BLOCKING gap — the ship policy an `/outcome start` will trust must be
    schema-valid the moment it is authored, never discovered broken downstream.
    """
    intent_envelope = _load_intent_envelope()
    try:
        intent_envelope.envelope_from_issue_body(body)
    except intent_envelope.IntentEnvelopeError as exc:
        return f"Invalid intent envelope block: {exc}"
    return None


def issue_render_intent_envelope(
    run_mode: str,
    *,
    reviews_required: str | None = None,
    merge: str | None = None,
    deploy_nonprod: str | None = None,
    authored_by: str = "",
) -> str:
    """Render the schema-validated ship-policy envelope block for an issue body (#380).

    This is the CAPTURE-side producer: the autonomy answers are recorded once, on the
    issue, through the fleet's single interview registry (`apply_answers` — typed,
    closed-vocabulary, fail-closed), so `/outcome start` can read them and skip the
    run-start interview instead of re-interrogating the operator (S-22 / H-F2-9).
    """
    intent_envelope = _load_intent_envelope()
    answers: dict[str, str] = {"run_mode": run_mode}
    if reviews_required is not None:
        answers["reviews_required"] = reviews_required
    if merge is not None:
        answers["merge"] = merge
    if deploy_nonprod is not None:
        answers["deploy_nonprod"] = deploy_nonprod
    try:
        envelope = intent_envelope.apply_answers(
            answers,
            source="issue-capture",
            authored_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            authored_by=authored_by,
        )
    except intent_envelope.IntentEnvelopeError as exc:
        raise RuntimeError(f"intent-envelope: {exc}") from exc  # main()'s clean-error path
    block = str(intent_envelope.render_issue_block(envelope))
    print(block, end="")
    return block


def _unfenced_lines(text: str) -> list[str]:
    """Return lines that occur outside of fenced code blocks (``` or ~~~)."""
    in_fence = False
    result: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if not in_fence:
            result.append(line)
    return result


def _extract_unfenced_headers(body: str) -> list[tuple[int, str]]:
    """Extract (level, header_text) for markdown headers outside code fences."""
    in_fence = False
    headers: list[tuple[int, str]] = []
    for line in body.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if not in_fence:
            m3 = re.match(r"^###\s+(.+?)\s*$", line)
            if m3:
                headers.append((3, m3.group(1).strip()))
                continue
            m2 = re.match(r"^##\s+(.+?)\s*$", line)
            if m2:
                headers.append((2, m2.group(1).strip()))
    return headers


def _readiness_for_prepared_issue(issue: PreparedIssue) -> PreparedReadiness:
    blocking: list[str] = []
    warnings: list[str] = []

    if issue.draft_path and Path(issue.draft_path).is_file():
        draft_text = Path(issue.draft_path).read_text(encoding="utf-8")
        unfenced_draft_lines = _unfenced_lines(draft_text)
        fence_count = sum(1 for line in unfenced_draft_lines if line.strip() == "---")
        if fence_count > 2:
            blocking.append(
                f"Prepared draft has multi-fence front matter ({fence_count} '---' fences found; expected 2)"
            )

    unfenced_body_lines = _unfenced_lines(issue.body)
    if any(line.strip() == "---" for line in unfenced_body_lines):
        blocking.append("Prepared issue body contains multi-fence front-matter fences ('---')")

    headers = _extract_unfenced_headers(issue.body)
    h3_headers = [h for level, h in headers if level == 3]
    h3_counts = Counter(h3_headers)
    duplicate_h3 = [h for h, count in h3_counts.items() if count > 1]
    if duplicate_h3:
        blocking.append(f"Duplicate H3 sections found in body: {duplicate_h3}")

    h2_headers = {h for level, h in headers if level == 2}
    duplicated_levels = sorted(h2_headers & set(h3_headers))
    if duplicated_levels:
        blocking.append(f"Duplicated section pairs between H2 and H3 headers: {duplicated_levels}")

    envelope_error = _intent_envelope_readiness_error(issue.body)
    if envelope_error:
        blocking.append(envelope_error)

    expected_status = _TEAM_SAFE_STATUSES.get(issue.team)
    if issue.status == "Ready":
        blocking.append("Prepared issues must not start in Ready")
    elif expected_status and issue.status != expected_status:
        blocking.append(
            f"Prepared {issue.team} issues must start in {expected_status!r}, not {issue.status!r}"
        )

    if issue.project not in PROJECT_CHOICES:
        blocking.append(f"Unknown project {issue.project!r}")

    expected_labels = set(_issue_expected_labels(issue.issue_type))
    missing_labels = sorted(expected_labels - set(issue.labels))
    if missing_labels:
        blocking.append(f"Missing expected labels: {missing_labels}")

    if issue.handoff_maturity and issue.handoff_maturity not in _HANDOFF_MATURITY_CHOICES:
        allowed = ", ".join(_HANDOFF_MATURITY_CHOICES)
        blocking.append(f"Unknown handoff maturity {issue.handoff_maturity!r}; expected {allowed}")
    elif not issue.handoff_maturity:
        warnings.append("Missing handoff maturity metadata")

    sections = _split_sections(issue.body)
    if issue.issue_type in _DISPATCH_ACTIONABLE_TYPES:
        valid_body, body_errors = validate_card_body_for_context(
            issue.body, issue.issue_type, issue.risk
        )
        if not valid_body:
            blocking.extend(body_errors)
        if not issue.project:
            blocking.append("Missing target project")
        if not issue.risk:
            blocking.append("Missing author-visible risk metadata")
    elif issue.team == "campps":
        if issue.issue_type not in _DISPATCH_ACTIONABLE_TYPES:
            blocking.append(
                f"Issue type {issue.issue_type!r} is not a CAMPPS dispatch-ready task type"
            )
    elif issue.team == "asgard":
        required = {
            "Intent": "intent",
            "Target repo / surface": "target repo/surface",
            "Mode": "mode",
            "Constraints": "constraints",
            "Risk": "risk",
            "Transfer notes": "transfer notes",
        }
        for header, label in required.items():
            text = sections.get(header, "").strip()
            if not text or text.upper() == "TBD":
                blocking.append(f"Missing Asgard {label}")
        if not issue.mode:
            blocking.append("Missing Asgard mode metadata")
        if not issue.risk:
            blocking.append("Missing Asgard risk metadata")

    return PreparedReadiness(
        profile=issue.team,
        passed=not blocking,
        blocking_gaps=blocking,
        warnings=warnings,
    )


def _sidecar_payload(
    issue: PreparedIssue,
    readiness: PreparedReadiness,
    state: str,
    approval_state: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "state": state,
        # The U11 human gate (None when blocked — a blocked draft never reaches
        # approval). Distinct from `state` (the creation pipeline) on purpose.
        "approval_state": approval_state,
        "title": issue.title,
        "repo": issue.repo,
        "issue_type": issue.issue_type,
        "team": issue.team,
        "project": issue.project,
        "status": issue.status,
        "labels": issue.labels,
        "risk": issue.risk,
        "mode": issue.mode,
        "handoff_maturity": issue.handoff_maturity,
        "source_artifact": issue.source_artifact,
        "project_fields": issue.project_fields or {},
        "draft_path": issue.draft_path,
        "sidecar_path": issue.sidecar_path,
        "readiness": asdict(readiness),
        "updated_at": datetime.now(UTC).isoformat(),
    }


def issue_prepare(
    repo: str,
    issue_type: str,
    team: str,
    project: str,
    source: str,
    title: str | None,
    status: str | None,
    risk: str | None,
    mode: str | None,
    handoff_maturity: str | None = None,
    source_artifact: SourceArtifact | None = None,
    draft_dir: Path | None = None,
    fmt: str = "text",
) -> Path:
    if not source.strip():
        raise RuntimeError("issue prepare requires non-empty source text")
    if team not in _TEAM_CHOICES:
        raise RuntimeError(f"Unknown team {team!r}; expected one of {', '.join(_TEAM_CHOICES)}")
    if issue_type not in _ISSUE_TYPES:
        raise RuntimeError(f"Unknown issue type {issue_type!r}")
    if project not in PROJECT_CHOICES:
        raise RuntimeError(
            f"Unknown project {project!r}; expected one of {', '.join(PROJECT_CHOICES)}"
        )

    safe_status = status or _TEAM_SAFE_STATUSES[team]
    draft_title = title or f"{issue_type}: {repo} {team} work"
    maturity = handoff_maturity or (
        source_artifact.inferred_maturity if source_artifact else "requirements-ready"
    )
    if maturity not in _HANDOFF_MATURITY_CHOICES:
        allowed = ", ".join(_HANDOFF_MATURITY_CHOICES)
        raise RuntimeError(f"Unknown handoff maturity {maturity!r}; expected {allowed}")
    issue = PreparedIssue(
        title=draft_title,
        repo=repo,
        issue_type=issue_type,
        team=team,
        project=project,
        status=safe_status,
        labels=_issue_expected_labels(issue_type),
        risk=risk,
        mode=mode,
        body=_source_to_issue_body(
            source, issue_type, team, repo, risk, mode, maturity, source_artifact
        ),
        handoff_maturity=maturity,
        source_artifact=_source_artifact_payload(source_artifact),
    )
    # Record the project-field values the card will carry so the later live
    # `create` step can set them (U11). Offline — derived from issue metadata.
    issue.project_fields = _prepared_project_fields(issue, source_artifact)
    # KTD9: the body produced by prepare must PASS the Phase C validator before
    # it can reach approval. The validator runs inside readiness (the olympus
    # profile calls validate_card_body), so a malformed body fails readiness and
    # is forced to `blocked` below — it never reaches `needs_operator_approval`.
    readiness = _readiness_for_prepared_issue(issue)

    target_dir = draft_dir or _PREPARED_DRAFT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    draft_path = _unique_draft_path(target_dir, draft_title)
    sidecar_path = draft_path.with_suffix(".json")
    issue.draft_path = str(draft_path)
    issue.sidecar_path = str(sidecar_path)

    # Creation-pipeline state is unchanged by U11 (ready_to_create / blocked).
    # The U11 human gate is the SEPARATE approval_state: a cleanly-compiled draft
    # lands in `needs_operator_approval` (NOT auto-created); a blocked draft has
    # no approval gate to enter.
    state = _PREPARE_STATE_READY if readiness.passed else _PREPARE_STATE_BLOCKED
    approval_state = _APPROVAL_NEEDS_OPERATOR if readiness.passed else None
    draft_path.write_text(
        _render_draft_markdown(issue, approval_state=approval_state), encoding="utf-8"
    )
    sidecar_path.write_text(
        json.dumps(
            _sidecar_payload(issue, readiness, state, approval_state), indent=2, sort_keys=True
        )
        + "\n",
        encoding="utf-8",
    )

    if fmt == "json":
        _out(
            {
                "draft": str(draft_path),
                "sidecar": str(sidecar_path),
                "readiness": asdict(readiness),
            },
            fmt,
        )
    else:
        print(f"Prepared draft: {draft_path}")
        print(f"Readiness: {'passed' if readiness.passed else 'blocked'}")
        for gap in readiness.blocking_gaps:
            print(f"  - BLOCKING: {gap}")
        for warning in readiness.warnings:
            print(f"  - WARNING: {warning}")
    return draft_path


def _known_template_names() -> list[str]:
    return [f"{issue_type}.yml" for issue_type in _ISSUE_TYPES]


def _repo_missing_labels(repo: str, required_labels: list[str]) -> list[str]:
    existing_raw = _rest_list_paginated(f"/repos/{ORG}/{repo}/labels")
    existing = {label.get("name") for label in existing_raw if isinstance(label, dict)}
    return [label for label in required_labels if label not in existing]


def _repo_missing_templates(repo: str) -> list[str]:
    template_names = _known_template_names()
    try:
        existing_raw = _rest_get(f"/repos/{ORG}/{repo}/contents/.github/ISSUE_TEMPLATE")
    except ApiNotFoundError:
        return template_names
    existing = {template.get("name") for template in existing_raw if isinstance(template, dict)}
    return [template for template in template_names if template not in existing]


def _project_mapping_contains_repo(config: dict[str, Any], repo: str, project_name: str) -> bool:
    projects = config.get("project_mappings", {}).get("projects", {})
    project = projects.get(project_name, {})
    return repo in project.get("repositories", [])


def _mapping_update_target() -> tuple[Path, Path, str, str | None]:
    sdlc_path = get_sdlc_path()
    external = sdlc_path / "config" / "project-mappings.json"
    if external.exists():
        return external, sdlc_path, "infiquetra-sdlc", None
    warning = (
        "No external infiquetra-sdlc project-mappings.json found; updating vendored "
        "mission-control mapping instead."
    )
    repo_root = Path(__file__).resolve().parents[3]
    return _VENDORED_PROJECT_MAPPINGS_PATH, repo_root, "infiquetra-claude-plugins", warning


def _write_mapping_update(mapping_path: Path, repo: str, project_name: str) -> None:
    data = json.loads(mapping_path.read_text(encoding="utf-8"))
    projects = data.setdefault("projects", {})
    if project_name not in projects:
        raise RuntimeError(f"Project {project_name!r} not found in {mapping_path}")
    repositories = projects[project_name].setdefault("repositories", [])
    if repo not in repositories:
        repositories.append(repo)
        projects[project_name]["repositories"] = sorted(repositories)
    mapping_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _run_git_command(args: list[str], cwd: Path) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"{args[0]} failed")
    return result.stdout.strip()


def _open_mapping_pr(repo: str, project_name: str) -> str:
    mapping_path, worktree_root, gh_repo, warning = _mapping_update_target()
    if warning:
        _warn(warning)
    branch = (
        f"sdlc-map-{_safe_slug(repo)}-{_safe_slug(project_name)}-"
        f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    )
    rel_mapping_path = mapping_path.relative_to(worktree_root)
    with tempfile.TemporaryDirectory(prefix="sdlc-mapping-") as tmp_parent:
        temp_worktree = Path(tmp_parent) / "repo"
        _run_git_command(
            ["git", "worktree", "add", "-b", branch, str(temp_worktree), "HEAD"],
            cwd=worktree_root,
        )
        try:
            _write_mapping_update(temp_worktree / rel_mapping_path, repo, project_name)
            _run_git_command(["git", "add", str(rel_mapping_path)], cwd=temp_worktree)
            _run_git_command(
                ["git", "commit", "-m", f"chore(sdlc): map {repo} to {project_name}"],
                cwd=temp_worktree,
            )
            _run_git_command(["git", "push", "-u", "origin", branch], cwd=temp_worktree)
            return _gh(
                [
                    "pr",
                    "create",
                    "--repo",
                    f"{ORG}/{gh_repo}",
                    "--title",
                    f"chore(sdlc): map {repo} to {project_name}",
                    "--body",
                    f"Adds `{repo}` to the `{project_name}` project mapping for mission-control routing.",
                ]
            )
        finally:
            try:
                _run_git_command(
                    ["git", "worktree", "remove", "--force", str(temp_worktree)], cwd=worktree_root
                )
            except RuntimeError as e:
                _warn(f"Could not remove temporary mapping worktree {temp_worktree}: {e}")


def _issue_body_for_github(issue: PreparedIssue) -> str:
    _, clean_body = _strip_frontmatter_and_title(issue.body)
    return clean_body.strip() + "\n"


def _create_github_issue(issue: PreparedIssue) -> tuple[str, int]:
    args = [
        "issue",
        "create",
        "--repo",
        f"{ORG}/{issue.repo}",
        "--title",
        issue.title,
        "--body",
        _issue_body_for_github(issue),
    ]
    if issue.labels:
        args.extend(["--label", ",".join(issue.labels)])
    url = _gh(args).strip()
    match = re.search(r"/issues/(\d+)\b", url)
    if not match:
        raise RuntimeError(f"Could not parse created issue number from gh output: {url!r}")
    return url, int(match.group(1))


def _append_created_issue_to_draft(draft_path: Path, url: str, number: int) -> None:
    text = draft_path.read_text(encoding="utf-8").rstrip()
    created_at = datetime.now(UTC).isoformat()
    marker = "\n\n## Created Issue\n"
    if marker in text:
        text = text.split(marker, 1)[0].rstrip()
    text += f"{marker}\n- URL: {url}\n- Number: {number}\n- Created at: {created_at}\n"
    draft_path.write_text(text + "\n", encoding="utf-8")


def _update_sidecar_state(draft_path: Path, updates: dict[str, Any]) -> None:
    sidecar_path = draft_path.with_suffix(".json")
    payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    payload.update(updates)
    payload["updated_at"] = datetime.now(UTC).isoformat()
    sidecar_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_sidecar_payload(draft_path: Path) -> dict[str, Any]:
    sidecar_path = draft_path.with_suffix(".json")
    payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Prepared issue sidecar {sidecar_path} not JSON object")
    return cast(dict[str, Any], payload)


def _prepared_project_item_exists(
    project_name: str, repo: str, number: int, config: dict[str, Any]
) -> bool:
    project_number = get_project_config(config, project_name)["number"]
    _, items = get_project_items(project_number)
    return any(
        item.get("content", {}).get("number") == number
        and item.get("content", {}).get("repository", {}).get("name") == repo
        for item in items
    )


def _post_create_pending_state(draft_path: Path) -> dict[str, Any] | None:
    payload = _read_sidecar_payload(draft_path)
    if payload.get("state") != "post_create_pending":
        return None
    url = str(payload.get("created_issue_url") or "")
    number = payload.get("created_issue_number")
    if not url or not isinstance(number, int):
        raise RuntimeError("Prepared issue post-create state is missing created issue URL/number")
    remaining = payload.get("remaining_steps")
    if not isinstance(remaining, list) or not all(isinstance(step, str) for step in remaining):
        remaining = ["board-add", "status"]
    return {
        "created_issue_url": url,
        "created_issue_number": number,
        "remaining_steps": remaining,
        "mapping_pr_url": payload.get("mapping_pr_url"),
        "pending_mapping": payload.get("pending_mapping", False),
        "mutation_summary": payload.get("mutation_summary", []),
        "created_at": payload.get("created_at") or datetime.now(UTC).isoformat(),
    }


def _read_sidecar_approval_state(draft_path: Path) -> str | None:
    """Read just the U11 `approval_state` from a draft's sidecar.

    Focused reader (the gate enforcement in issue_create_prepared needs only
    this one field; PreparedIssue deliberately doesn't carry it). Returns None
    when absent — i.e. legacy drafts predating the gate, which proceed unblocked.
    """
    sidecar_path = draft_path.with_suffix(".json")
    payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    value = payload.get("approval_state")
    return str(value) if value is not None else None


def _build_mutation_plan(issue: PreparedIssue, config: dict[str, Any]) -> MutationPlan:
    if not issue.draft_path:
        raise RuntimeError("Prepared issue is missing draft_path")
    steps: list[MutationStep] = []
    missing_labels = _repo_missing_labels(issue.repo, issue.labels)
    missing_templates = _repo_missing_templates(issue.repo)
    mapping_missing = not _project_mapping_contains_repo(config, issue.repo, issue.project)

    if missing_labels:
        steps.append(
            MutationStep("deploy-labels", f"Deploy missing labels: {', '.join(missing_labels)}")
        )
    if missing_templates:
        steps.append(
            MutationStep(
                "deploy-templates", f"Deploy missing templates: {', '.join(missing_templates)}"
            )
        )
    if mapping_missing:
        steps.append(
            MutationStep(
                "mapping-pr",
                f"Open mapping PR for {issue.repo} -> {issue.project}",
            )
        )
    steps.extend(
        [
            MutationStep("issue", f"Create {issue.issue_type} in {ORG}/{issue.repo}"),
            MutationStep("board-add", f"Add issue to {issue.project}"),
            MutationStep("set-status", f"Set Status to {issue.status}"),
            MutationStep("mark-draft", "Record created issue on draft and sidecar"),
        ]
    )
    return MutationPlan(
        draft_path=issue.draft_path,
        repo=issue.repo,
        issue_type=issue.issue_type,
        team=issue.team,
        project=issue.project,
        status=issue.status,
        steps=steps,
        mapping_missing=mapping_missing,
    )


def _print_mutation_plan(plan: MutationPlan) -> None:
    print("\nMutation plan:")
    for step in plan.steps:
        print(f"  - {step.action}: {step.detail}")


def issue_create_prepared(
    draft_path: Path,
    fmt: str,
    auto_confirm: bool = False,
    override_mapping: bool = False,
    skip_approval: bool = False,
) -> dict[str, Any]:
    issue = _read_prepared_issue(draft_path)
    readiness = _readiness_for_prepared_issue(issue)
    if not readiness.passed:
        if fmt == "json":
            _out({"created": False, "readiness": asdict(readiness)}, fmt)
        else:
            print("Prepared issue is blocked:")
            for gap in readiness.blocking_gaps:
                print(f"  - {gap}")
        raise RuntimeError("Prepared issue has blocking readiness gaps")

    # Enforce the U11 human gate (FIX 1): a draft sitting in
    # `needs_operator_approval` is NOT created until an operator approves it (via
    # `issue approve`) or explicitly overrides with --skip-approval. An
    # `approved` draft proceeds; a None approval_state (legacy drafts predating
    # the gate; blocked drafts already failed readiness above) proceeds
    # unchanged — back-compatible, do NOT newly block None.
    approval_state = _read_sidecar_approval_state(draft_path)
    if approval_state == _APPROVAL_NEEDS_OPERATOR and not skip_approval:
        message = (
            f"Prepared draft awaits operator approval; run "
            f"`issue approve {draft_path}` first, or pass --skip-approval."
        )
        if fmt == "json":
            _out({"created": False, "reason": "needs_operator_approval"}, fmt)
        else:
            print(message)
        raise RuntimeError(message)

    config = load_config()
    plan = _build_mutation_plan(issue, config)
    plan_payload = asdict(plan)
    if fmt != "json":
        _print_mutation_plan(plan)

    if not auto_confirm:
        confirm = _safe_input("Apply this mutation plan? (y/N): ")
        if confirm is None or confirm.lower() not in ("y", "yes"):
            result = {"created": False, "reason": "declined"}
            if fmt == "json":
                _out({**result, "mutation_plan": plan_payload}, fmt)
            else:
                print("No mutations applied.")
            return result

    resume_state = _post_create_pending_state(draft_path)
    mapping_pr_url: str | None = None

    if resume_state:
        url = str(resume_state["created_issue_url"])
        number = int(resume_state["created_issue_number"])
        remaining_steps = list(resume_state["remaining_steps"])
        mapping_pr_url = (
            str(resume_state["mapping_pr_url"]) if resume_state.get("mapping_pr_url") else None
        )
        pending_mapping = bool(resume_state.get("pending_mapping"))
        created_at = str(resume_state["created_at"])
        mutation_summary = resume_state.get("mutation_summary") or [
            asdict(step) for step in plan.steps
        ]
    else:
        labels_missing = any(step.action == "deploy-labels" for step in plan.steps)
        templates_missing = any(step.action == "deploy-templates" for step in plan.steps)
        if labels_missing:
            labels_deploy(issue.repo, fmt="text")
        if templates_missing:
            rollout_deploy_templates(issue.repo, fmt="text")

        if plan.mapping_missing:
            mapping_pr_url = _open_mapping_pr(issue.repo, issue.project)
            if not override_mapping:
                _update_sidecar_state(
                    draft_path,
                    {
                        "state": "mapping_pending",
                        "mapping_pr_url": mapping_pr_url,
                        "pending_mapping": {"repo": issue.repo, "project": issue.project},
                    },
                )
                if fmt != "json":
                    print(f"Mapping PR opened; issue creation stopped: {mapping_pr_url}")
                result = {"created": False, "mapping_pr_url": mapping_pr_url}
                if fmt == "json":
                    _out({**result, "mutation_plan": plan_payload}, fmt)
                return result

        url, number = _create_github_issue(issue)
        created_at = datetime.now(UTC).isoformat()
        mutation_summary = [asdict(step) for step in plan.steps]
        pending_mapping = bool(mapping_pr_url and override_mapping)
        remaining_steps = ["board-add", "status"]
        _append_created_issue_to_draft(draft_path, url, number)
        _update_sidecar_state(
            draft_path,
            {
                "state": "post_create_pending",
                "created_issue_url": url,
                "created_issue_number": number,
                "created_at": created_at,
                "remaining_steps": remaining_steps,
                "mutation_summary": mutation_summary,
                "mapping_pr_url": mapping_pr_url,
                "pending_mapping": pending_mapping,
            },
        )

    try:
        if "board-add" in remaining_steps:
            if _prepared_project_item_exists(issue.project, issue.repo, number, config):
                remaining_steps = [step for step in remaining_steps if step != "board-add"]
            else:
                board_add(
                    issue.repo,
                    number,
                    fmt="text",
                    config=config,
                    project_name=issue.project,
                    strict=True,
                )
                remaining_steps = [step for step in remaining_steps if step != "board-add"]
            _update_sidecar_state(draft_path, {"remaining_steps": remaining_steps})

        if "status" in remaining_steps:
            flow_set_field(issue.project, issue.repo, number, "Status", issue.status, fmt="text")
            remaining_steps = [step for step in remaining_steps if step != "status"]
            _update_sidecar_state(draft_path, {"remaining_steps": remaining_steps})
    except Exception as e:
        _update_sidecar_state(
            draft_path,
            {
                "state": "post_create_pending",
                "created_issue_url": url,
                "created_issue_number": number,
                "created_at": created_at,
                "remaining_steps": remaining_steps,
                "mutation_summary": mutation_summary,
                "mapping_pr_url": mapping_pr_url,
                "pending_mapping": pending_mapping,
            },
        )
        remaining = ", ".join(remaining_steps) or "none"
        raise RuntimeError(
            f"Created issue {url}, but post-create steps failed: {e}. Remaining steps: {remaining}."
        ) from e

    _update_sidecar_state(
        draft_path,
        {
            "state": "created",
            "created_issue_url": url,
            "created_issue_number": number,
            "created_at": created_at,
            "remaining_steps": [],
            "mutation_summary": mutation_summary,
            "mapping_pr_url": mapping_pr_url,
            "pending_mapping": pending_mapping,
        },
    )
    result = {"created": True, "url": url, "number": number, "mapping_pr_url": mapping_pr_url}
    if fmt == "json":
        _out({**result, "mutation_plan": plan_payload}, fmt)
    else:
        print(f"Created issue: {url}")
    return result


def _set_draft_approval_state(draft_path: Path, approval_state: str) -> None:
    """Rewrite the `approval_state:` front-matter line on the draft markdown.

    The approval state lives in BOTH the draft front-matter and the sidecar so
    the human gate survives whichever artifact an operator looks at. This keeps
    the front-matter in lockstep when batch approval transitions the sidecar.
    """
    text = draft_path.read_text(encoding="utf-8")
    metadata, _ = _parse_draft_frontmatter(text)
    line = f"approval_state: {approval_state}"
    if "approval_state" in metadata:
        # Replace the existing line in place (front-matter only, before body).
        end = text.find("\n---\n", 4)
        if end == -1:
            # Opening `---` but no closing fence: never split a malformed draft
            # (matches _parse_draft_frontmatter's contract). Safe no-op.
            return
        head, tail = text[:end], text[end:]
        head = re.sub(r"(?m)^approval_state:.*$", line, head)
        draft_path.write_text(head + tail, encoding="utf-8")
        return
    if not text.startswith("---\n"):
        # No front-matter to edit (defensive): nothing durable to rewrite.
        return
    end = text.find("\n---\n", 4)
    if end == -1:
        # Opening `---` but no closing fence: refuse to truncate. Safe no-op.
        return
    draft_path.write_text(text[:end] + f"\n{line}" + text[end:], encoding="utf-8")


def prepared_approve_batch(draft_paths: list[Path], fmt: str = "text") -> dict[str, Any]:
    """Approve multiple prepared drafts at once (U11 batch approval).

    Transitions each draft's `approval_state` from `needs_operator_approval` ->
    `approved` in both the sidecar and the draft front-matter. This is the human
    gate clearing a batch of compiled cards for creation.

    Per-draft fault isolated: a missing/malformed/non-gate draft is reported in
    `skipped` and the rest of the batch still proceeds. Approving an
    already-`approved` draft is a no-op — it is SKIPPED ("already approved") and
    its `approved_at`/`updated_at` are preserved, not rewritten.

    Self-defending: readiness is RECONSTRUCTED from disk (re-run the validator
    on the on-disk body) before approving, so a hand-edited / forged sidecar that
    claims `needs_operator_approval` over a body that fails validation cannot be
    pushed to `approved`.
    """
    approved: list[str] = []
    skipped: list[dict[str, str]] = []
    for draft_path in draft_paths:
        sidecar_path = draft_path.with_suffix(".json")
        if not sidecar_path.exists():
            skipped.append({"draft": str(draft_path), "reason": "missing sidecar"})
            continue
        try:
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            skipped.append({"draft": str(draft_path), "reason": f"malformed sidecar: {e}"})
            continue
        current = sidecar.get("approval_state")
        if current == _APPROVAL_APPROVED:
            skipped.append({"draft": str(draft_path), "reason": "already approved"})
            continue
        if current not in _APPROVABLE_APPROVAL_STATES:
            skipped.append({"draft": str(draft_path), "reason": f"approval_state is {current!r}"})
            continue
        # Re-derive readiness from the on-disk draft so a tampered sidecar can't
        # smuggle an unvalidated body past the gate. _read_prepared_issue raises
        # on a malformed/conflicting draft — treat that as a skip, not an abort.
        try:
            issue = _read_prepared_issue(draft_path)
            readiness = _readiness_for_prepared_issue(issue)
        except RuntimeError as e:
            skipped.append({"draft": str(draft_path), "reason": f"unreadable draft: {e}"})
            continue
        if not readiness.passed:
            skipped.append({"draft": str(draft_path), "reason": "fails validation"})
            continue
        _update_sidecar_state(
            draft_path,
            {
                "approval_state": _APPROVAL_APPROVED,
                "approved_at": datetime.now(UTC).isoformat(),
            },
        )
        _set_draft_approval_state(draft_path, _APPROVAL_APPROVED)
        approved.append(str(draft_path))

    result = {"approved": approved, "skipped": skipped}
    if fmt == "json":
        _out(result, fmt)
    else:
        print(f"Approved {len(approved)} prepared draft(s).")
        for path in approved:
            print(f"  - APPROVED: {path}")
        for entry in skipped:
            print(f"  - SKIPPED ({entry['reason']}): {entry['draft']}")
    return result


def _read_prepare_source(
    source_parts: list[str],
    source_file: str | None,
    from_ref: str | None = None,
) -> str:
    source, _ = _resolve_prepare_source(source_parts, source_file, from_ref)
    return source


def _safe_input(prompt: str) -> str | None:
    """Wrap `input()` to handle EOF (Ctrl+D) and KeyboardInterrupt (Ctrl+C)
    uniformly: return None instead of raising. Saves ~24 lines of repeated
    try/except boilerplate across the prompt helpers + makes the contract
    "what does Ctrl+D do here?" trivially answerable."""
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return None


def _select_issue_type(default: str | None = None) -> str:
    """Decision-tree prompt for the five issue types. Returns the chosen
    type. `default` overrides the built-in 'capability' default if set."""
    print("\nIssue Type Selection")
    print("=" * 40)
    print("Decision tree:")
    print("  1. Broken functionality? -> DEFECT")
    print("  2. New end-to-end deployable functionality? -> CAPABILITY")
    print("  3. Improving existing functionality? -> ENHANCEMENT")
    print("  4. Researching or investigating? -> EXPLORATION")
    print("  5. Updating documentation? -> CONTEXT UPDATE")
    print("  Objective is a project field plus scorecard, not an issue type.")
    print()
    fallback = default if default in _ISSUE_TYPES else "capability"
    answer = _safe_input(f"Select type (or press Enter for '{fallback}'): ")
    if answer is None:
        return fallback
    choice = answer.lower()
    return choice if choice in _ISSUE_TYPES else fallback


_PARENT_REF_RE = re.compile(r"^\s*([\w.-]+)#(\d+)\s*$")


def _prompt_parent_issue() -> tuple[str, int] | None:
    """Prompt for an optional decomposition parent.

    Returns ``(parent_repo, parent_number)`` for a supplied reference or
    ``None`` for a top-level card. Blank input defaults to no parent.
    """
    print("\nParent linkage is optional and only represents real decomposition.")
    print("Paste a parent ref like 'campps-context-library#42', or press Enter for none.")
    raw = _safe_input("Parent issue? (no/yes/<repo#N>) [no]: ")
    if raw is None:
        return None  # Ctrl+D / Ctrl+C → treat as no-parent
    answer = raw.lower()

    if answer in ("", "no", "n", "skip", "-"):
        return None
    if answer in ("yes", "y"):
        # Operator confirmed but didn't paste a ref — re-prompt for the ref
        ref = _safe_input("Parent ref (e.g., campps-context-library#42): ")
        if ref is None:
            return None
        match = _PARENT_REF_RE.match(ref)
    else:
        match = _PARENT_REF_RE.match(raw)

    if not match:
        _warn(
            "Couldn't parse parent ref. Expected '<repo>#<number>'. "
            "Continuing as free-floating (no parent)."
        )
        return None
    return match.group(1), int(match.group(2))


def _project_field_options(project_name: str, field_name: str) -> list[str] | None:
    """Look up the option names for a project single-select field, or
    return None if the field doesn't exist on the project. Used for
    per-project schema discovery — silently skip prompts for fields the
    operator's project doesn't expose."""
    try:
        field = _resolve_project_field(project_name, field_name)
    except RuntimeError:
        return None
    return [o.get("name", "") for o in field.get("options", [])]


def _prompt_choice(
    label: str,
    options: list[str] | None,
    default: str | None = None,
) -> str | None:
    """Generic field-value prompt.

    Two distinct semantics:
      - `options is None`  → the field doesn't exist on this project at all.
                              Skip silently (return None) — caller wanted
                              per-project schema discovery.
      - `options == []`    → the field exists but has no options yet.
                              Skip with a hint — accepting freeform input
                              would create a useless reference; the operator
                              should add options to the field first.
      - `options == [...]` → normal prompt with options listed.

    Operator can press Enter for default (if default is in options),
    type a value matching one of the options, or type '-' to skip.
    """
    if options is None:
        return None
    if not options:  # empty list — field exists but no options
        _warn(
            f"  {label}: field exists on the project but has no options yet. "
            f"Add options via the GH Projects UI or `gh project field-edit` "
            f"before this prompt can offer values. Skipping."
        )
        return None
    options_display = ", ".join(options)
    if default and default in options:
        prompt = f"  {label} [{default}] (options: {options_display}; '-' to skip): "
    else:
        prompt = f"  {label} (options: {options_display}; '-' to skip): "
    answer = _safe_input(prompt)
    if answer is None:
        return None
    if answer == "-" or answer.lower() in ("skip", "no"):
        return None
    if not answer:
        return default if default and default in options else None
    if answer not in options:
        _warn(
            f"'{answer}' not in {label} options ({options_display}); "
            f"skipping. Use `flow field-options --field {label}` to see "
            f"current options. If you need a new option, add it via the "
            f"GH Projects UI or `gh project field-edit` — `flow set-field` "
            f"will fail with the same not-in-options error otherwise."
        )
        return None
    return answer


def _open_gh_issue_create_web(repo: str, issue_type: str) -> None:
    """Open the gh web flow for the operator to fill the body. Returns
    nothing — the operator submits in the browser, then pastes back the
    issue number to the next prompt. We don't try to capture stdout from
    `gh issue create --web` because gh's behavior with --web differs
    across versions + operator may take arbitrary time in the browser."""
    print(f"\nOpening browser to create {issue_type} issue in {ORG}/{repo}.")
    print("Fill the form + submit. We'll capture the issue number after.\n")
    try:
        subprocess.run(
            [
                "gh",
                "issue",
                "create",
                "--repo",
                f"{ORG}/{repo}",
                "--template",
                f"{issue_type}.yml",
                "--web",
            ],
            check=False,  # operator may close the tab without submitting
        )
    except FileNotFoundError:
        _error("gh CLI not found.")
        raise


def _prompt_issue_number(repo: str) -> int | None:
    """After the browser flow, ask for the new issue number. Operator can
    paste a URL ('https://github.com/foo/bar/issues/42') or just the
    number. Return None if the operator skips (e.g., closed the browser
    without submitting). PR URLs are intentionally rejected — sub-issue
    linking and project field assignment work on issues, not PRs."""
    answer = _safe_input(
        f"\nIssue number that was created in {repo} (or paste URL; Enter to skip metadata): "
    )
    if not answer:
        return None
    # Try to extract a trailing /issues/N or a bare integer (#42 / 42).
    # The /issues/ branch matches the URL form; the bare-int branch is
    # anchored (`^#?(\d+)$`) so a pasted /pull/N URL won't accidentally
    # match the bare-int side.
    match = re.search(r"/issues/(\d+)\b|^#?(\d+)$", answer)
    if match:
        return int(match.group(1) or match.group(2))
    _warn(f"Couldn't parse issue number from {answer!r}; skipping metadata.")
    return None


def _gate_created_issue_body(repo: str, issue_number: int, issue_type: str, fmt: str) -> bool:
    """Gate post-create metadata on the card contract. Returns True to proceed.

    `issue create-prepared` has always refused to create a draft with blocking
    readiness gaps (`RuntimeError: Prepared issue has blocking readiness gaps`).
    The interactive path had no equivalent: it opened the browser template, took
    the pasted issue number, and applied labels + board membership with no body
    check at all. A blank or half-filled template therefore landed on the board
    wearing exactly the same labels as a conformant card, which is the single
    most direct generator of board inconsistency.

    Scope: only the contract-bearing types carry the eight-section contract.
    `exploration` and `context-update` ship deliberately different field sets and
    are not validated here — validating them would reject correct cards.

    Failure is a stop, not a veto: the operator is shown the specific gaps and
    must opt in explicitly (default no). Declining leaves the issue without
    labels or board membership, which is recoverable and visible; silently
    carding a malformed issue is neither. A fetch failure is not treated as a
    validation failure — an API hiccup should not strand a good issue.
    """
    if issue_type not in _CONTRACT_ISSUE_TYPES:
        return True

    issue_ref = f"{repo}#{issue_number}"
    try:
        data = _rest_get(f"repos/{ORG}/{repo}/issues/{issue_number}")
    except RuntimeError as e:
        _warn(f"Could not fetch {issue_ref} to validate it ({e}); applying metadata unchecked.")
        return True

    body = data.get("body") or ""
    is_valid, errors = (
        (False, ["Issue has empty body"])
        if not body.strip()
        else validate_card_body_for_context(body, issue_type, None)
    )
    if is_valid:
        return True

    if fmt == "json":
        _out({"valid": False, "errors": errors, "issue": issue_ref, "metadata_applied": False}, fmt)
        return False

    print(f"\nINVALID: {issue_ref} does not satisfy the card contract:")
    for err in errors:
        print(f"   - {err}")
    print(
        f"\nFix the body first:  gh issue edit {issue_number} --repo {ORG}/{repo}\n"
        f"Then card it:        sdlc_manager.py flow validate-card "
        f"--repo {repo} --number {issue_number}"
    )
    answer = _safe_input("\nApply labels and board membership anyway? (y/N): ")
    if (answer or "").strip().lower() in ("y", "yes"):
        _warn(f"Proceeding with a card that fails the contract: {issue_ref}")
        return True
    print("Metadata not applied. The issue exists but is not on a board.")
    return False


def _apply_post_create_metadata(
    repo: str,
    issue_number: int,
    issue_type: str,
    project_name: str | None,
    parent: tuple[str, int] | None,
    field_values: dict[str, str],
    fmt: str,
) -> None:
    """Apply the post-create metadata steps. Each step is logged and
    isolated — failures in one don't abort the others.

    Steps execute IN ORDER (later steps depend on earlier ones):
      1. Apply the canonical type labels
      2. Add the issue to the project board (`board_add`) — required
         before step 3 can target the project item
      3. Set each project field value via `flow_set_field` — depends on
         step 2 having created the project item
      4. Link as a sub-issue under `parent` via `flow_link_sub_issue`

    Steps 2-3 require `project_name` to be set; step 1 always runs;
    step 4 requires `parent`."""
    if issue_type not in _ISSUE_TYPES:
        raise RuntimeError(
            f"Unknown or retired issue type {issue_type!r}; expected one of {', '.join(_ISSUE_TYPES)}"
        )

    issue_ref = f"{repo}#{issue_number}"
    print(f"\nApplying metadata to {issue_ref}...")
    # Cache config once — saves a load_config() round-trip on board_add.
    # (flow_set_field internally re-loads; a global lru_cache on
    # load_config would address that more cleanly, deferred to follow-up.)
    cached_config = load_config()

    # 1. Type labels. The browser template applies these when it prefills, but
    # `gh issue create --template ... --web` does not always prefill, so a card
    # could previously land with no type label at all — this path only ever
    # guaranteed the retired Hermes dispatch marker. Applying the canonical set
    # is idempotent when the template already did it.
    labels = _ISSUE_TYPE_LABELS.get(issue_type, [])
    if labels:
        try:
            _gh(
                [
                    "issue",
                    "edit",
                    str(issue_number),
                    "--repo",
                    f"{ORG}/{repo}",
                    "--add-label",
                    ",".join(labels),
                ]
            )
            print(f"  ✓ Applied labels `{'`, `'.join(labels)}`")
        except GhApiError as e:
            _warn(f"  ✗ Could not apply type labels: {e}")

    # 2. Add to project board
    if project_name:
        try:
            board_add(repo, issue_number, fmt, config=cached_config)
        except RuntimeError as e:
            _warn(f"  ✗ board add failed: {e}")

    # 3. Project field values (Initiative, Objective, Priority, Size, ...)
    for field_name, option in field_values.items():
        if not option or not project_name:
            continue
        try:
            flow_set_field(
                project_name,
                repo,
                issue_number,
                field_name,
                option,
                fmt="text",
            )
        except RuntimeError as e:
            _warn(f"  ✗ set {field_name}={option} failed: {e}")

    # 4. Sub-issue link (parent → child)
    if parent:
        parent_repo, parent_number = parent
        try:
            flow_link_sub_issue(parent_repo, parent_number, repo, issue_number, fmt="text")
        except RuntimeError as e:
            _warn(f"  ✗ sub-issue link failed: {e}")


def _prompt_paired_card(repo: str, issue_number: int) -> str | None:
    """Opt-in paired-card prompt. After a successful card create, ask
    if the operator wants a sibling card on another repo with similar
    scope. Returns the target repo name, or None to skip. Default is no
    — paired cards are useful for cross-service capabilities (e.g., a
    backend change with a paired Flutter app change) but not the common case.

    Phase C v1: only the target repo is captured. The browser flow on the
    sibling card is the right place for the operator to type the
    title/body. Earlier drafts collected `title_delta` / `body_delta`
    here but never applied them — a UX promise we don't keep. Implementing
    them properly requires a `gh issue edit --title --body` post-create
    step + careful handling of the existing template body; deferred to a
    follow-up if the need surfaces."""
    print(f"\nCreated {repo}#{issue_number}.")
    raw = _safe_input("Create a paired card on another repo with similar scope? (y/N): ")
    if raw is None:
        return None
    if raw.lower() not in ("y", "yes"):
        return None
    target_repo = _safe_input("  Target repo (e.g., campps-flutter-app): ")
    if not target_repo:
        return None
    return target_repo


def issue_create(
    repo: str,
    issue_type: str | None,
    fmt: str,
    parent_ref: str | None = None,
    skip_metadata: bool = False,
    _in_paired_card: bool = False,
) -> None:
    """Interactive issue creation with optional parent linkage and per-project schema
    aware, with capability-adaptive fields and paired-card flow.

    **Today's reality (2026-05-04)**: the Olympus project (#1) only exposes
    `Status` as a single-select field. Initiative, Objective, Capability
    Size, Business Value, Technical Risk, Target Quarter are all "decided,
    not yet created" per Phase A carry-over #2. The per-project schema
    discovery silently skips prompts for missing fields, so today operators
    will see only the type, parent, Status, and confirm prompts. When the
    operator runs the field-creation runbook in
    `infiquetra-sdlc/docs/operations/operational-reference.md`, the
    additional prompts light up automatically.

    **`--web` flow caveat**: this calls `gh issue create --template <type>.yml --web`.
    `gh` accepts both flags but the `--template` may not always prefill
    the templated body in the browser tab (gh's `--web` URL generation
    varies). If the browser opens to a blank issue form, manually pick
    the `<type>` template from the GitHub UI's template chooser. This
    has been observed but not catalogued by gh version.

    Flow:
      1. Determine type (decision tree if not provided)
      2. Optional decomposition-parent prompt (default: none)
      3. Discover project the repo maps to (if any)
      4. Per-project schema discovery: which project fields exist?
      5. Prompt for field values, defaults from ~/.claude/sdlc-defaults.json
      6. Capability-adaptive: prompt for Size if type is capability and the project exposes the field
      7. Open `gh issue create --web` in browser; operator fills body
      8. Operator pastes back the issue number
      9. Apply the canonical type labels, project field values, sub-issue link
     10. Paired-card prompt (opt-in) — suppressed when called recursively
         (`_in_paired_card=True`) to prevent unbounded nesting

    Args:
      repo: target repo (without org)
      issue_type: optional pre-selected type; decision-tree prompt if None
      fmt: output format (passed to sub-helpers)
      parent_ref: optional pre-supplied 'repo#N' parent ref; skips the prompt
      skip_metadata: if True, just create the issue + skip post-create
        metadata application (useful for testing or scripted flows)
      _in_paired_card: private flag set when this call is the
        paired-card recursion. Suppresses the paired-card prompt at step 10
        so a chain of yes-yes-yes can't recurse indefinitely. Operators
        never set this directly."""
    defaults = load_user_defaults()

    # Step 1: determine type
    if issue_type is None:
        issue_type = _select_issue_type(default=defaults.get("default_type"))

    # Step 2: optional decomposition-parent prompt
    parent: tuple[str, int] | None = None
    if parent_ref:
        match = _PARENT_REF_RE.match(parent_ref)
        if match:
            parent = (match.group(1), int(match.group(2)))
        else:
            _warn(f"Couldn't parse --parent-ref={parent_ref!r}; treating as no-parent.")
    elif not skip_metadata:
        parent = _prompt_parent_issue()

    # Step 3: discover project for this repo
    config = load_config()
    projects = get_projects_for_repo(config, repo)
    project_name: str | None = None
    if projects:
        # Prefer the user's default_project if it's one of the matches.
        # No board is a hardcoded canonical default (KTD17): work is never
        # silently routed to a board the operator did not name.
        default_project = defaults.get("default_project")
        for p in projects:
            if default_project and p.get("name", "").lower() == default_project.lower():
                project_name = next(
                    (
                        k
                        for k, v in config.get("project_mappings", {}).get("projects", {}).items()
                        if v.get("number") == p.get("number")
                    ),
                    None,
                )
                break
        if not project_name:
            # Just use the first repo-mapped match (no implicit project-#1 default).
            project_name = next(
                iter(config.get("project_mappings", {}).get("projects", {}).keys()),
                None,
            )

    # Step 4 + 5: per-project schema discovery + field prompts
    field_values: dict[str, str] = {}
    if project_name and not skip_metadata:
        print(f"\nProject: {project_name}")
        # Initiative
        opts = _project_field_options(project_name, "Initiative")
        chosen = _prompt_choice("Initiative", opts, default=defaults.get("default_initiative"))
        if chosen:
            field_values["Initiative"] = chosen

        # Objective
        opts = _project_field_options(project_name, "Objective")
        chosen = _prompt_choice("Objective", opts, default=defaults.get("default_objective"))
        if chosen:
            field_values["Objective"] = chosen

        # Status (default Backlog or per-user default)
        opts = _project_field_options(project_name, "Status")
        chosen = _prompt_choice(
            "Status",
            opts,
            default=defaults.get("default_status") or "Backlog",
        )
        if chosen:
            field_values["Status"] = chosen

    # Step 6: capability-adaptive fields (only for capability AND
    # only when the project exposes the field)
    if issue_type in _CAPABILITY_ADAPTIVE_TYPES and project_name and not skip_metadata:
        for adaptive_field in (
            "Capability Size",
            "Business Value",
            "Technical Risk",
            "Target Quarter",
        ):
            opts = _project_field_options(project_name, adaptive_field)
            chosen = _prompt_choice(adaptive_field, opts, default=None)
            if chosen:
                field_values[adaptive_field] = chosen

    # Step 7: open browser
    print(f"\nReady to create {issue_type} in {ORG}/{repo}")
    if parent:
        print(f"  Parent: {parent[0]}#{parent[1]}")
    if field_values:
        for k, v in field_values.items():
            print(f"  {k}: {v}")
    print()

    if not skip_metadata:
        try:
            confirm = input("Open browser? (Y/n): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("Aborted.")
            return
        if confirm in ("n", "no"):
            print(
                f"\nRun manually: gh issue create --repo {ORG}/{repo} "
                f"--template {issue_type}.yml --web"
            )
            return

        _open_gh_issue_create_web(repo, issue_type)

        # Step 8: capture issue number
        issue_number = _prompt_issue_number(repo)
        if issue_number is None:
            print("Skipping post-create metadata.")
            return

        # Step 8b: gate on the card contract before carding it. The prepared
        # path has always blocked here; this path never checked.
        if not _gate_created_issue_body(repo, issue_number, issue_type, fmt):
            return

        # Step 9: apply metadata
        _apply_post_create_metadata(
            repo,
            issue_number,
            issue_type,
            project_name,
            parent,
            field_values,
            fmt,
        )

        # Step 10: paired-card prompt — suppressed in recursive call to
        # prevent unbounded nesting.
        if not _in_paired_card:
            target_repo = _prompt_paired_card(repo, issue_number)
            if target_repo:
                print(f"\nLaunching paired-card flow for {target_repo}...")
                # Recurse with the same type + parent to create a sibling card.
                # The recursive call gets _in_paired_card=True so its own
                # Step 10 is skipped (no chain-recursion).
                # We don't auto-link the two cards — the operator decides
                # whether they should be linked (e.g., as sibling sub-issues
                # of a common parent).
                issue_create(
                    target_repo,
                    issue_type,
                    fmt,
                    parent_ref=f"{parent[0]}#{parent[1]}" if parent else None,
                    _in_paired_card=True,
                )
    else:
        # skip_metadata path: just print the manual command
        print(
            f"Run manually: gh issue create --repo {ORG}/{repo} --template {issue_type}.yml --web"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Infiquetra SDLC Manager — Unified CLI for Infiquetra SDLC automation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--format", choices=["text", "json", "markdown"], default="text", help="Output format"
    )

    subparsers = parser.add_subparsers(dest="resource", required=True)

    # ===========================
    # BOARD
    # ===========================
    board_p = subparsers.add_parser("board", help="Project board operations")
    board_sp = board_p.add_subparsers(dest="action", required=True)

    board_view_p = board_sp.add_parser("view", help="View board items by column")
    board_view_p.add_argument("--project", required=True, choices=PROJECT_CHOICES)
    board_view_p.add_argument("--status", help="Filter by status column")

    board_add_p = board_sp.add_parser("add", help="Add issue/PR to project(s)")
    board_add_p.add_argument(
        "--project",
        action="append",
        choices=PROJECT_CHOICES,
        help=(
            "Target a specific project instead of repo-based default routing. "
            "Repeatable: pass --project more than once to place the item on "
            "multiple boards as independent memberships "
            "(e.g. --project operations --project asgard)."
        ),
    )
    board_add_p.add_argument(
        "--repo",
        required=True,
        type=_normalize_repo_arg,
        help="Repository name (bare or infiquetra/<repo>)",
    )
    board_add_p.add_argument("--number", required=True, type=int, help="Issue or PR number")

    board_move_p = board_sp.add_parser("move", help="Move item to different column")
    board_move_p.add_argument(
        "--project",
        choices=PROJECT_CHOICES,
        help="Target a specific project instead of repo-based default routing",
    )
    board_move_p.add_argument("--repo", required=True, type=_normalize_repo_arg)
    board_move_p.add_argument("--number", required=True, type=int)
    board_move_p.add_argument(
        "--status", required=True, help="Target status (e.g. 'Assigned', 'In Review', 'Active')"
    )

    board_archive_p = board_sp.add_parser("archive", help="Archive terminal workflow items")
    board_archive_p.add_argument("--project", required=True, choices=PROJECT_CHOICES)
    board_archive_p.add_argument("--dry-run", action="store_true")

    board_wip_p = board_sp.add_parser("wip", help="Show WIP counts and limits")
    board_wip_p.add_argument("--project", required=True, choices=PROJECT_CHOICES)

    board_standup_p = board_sp.add_parser(
        "standup", help="Standup prep — right-to-left board review"
    )
    board_standup_p.add_argument("--project", required=True, choices=PROJECT_CHOICES)

    board_fields_p = board_sp.add_parser(
        "discover-fields", help="Discover all project fields and options"
    )
    board_fields_p.add_argument("--project", required=True, choices=PROJECT_CHOICES)

    # ===========================
    # ISSUE
    # ===========================
    issue_p = subparsers.add_parser("issue", help="Issue creation and management")
    issue_sp = issue_p.add_subparsers(dest="action", required=True)

    issue_create_p = issue_sp.add_parser(
        "create",
        help="Interactive issue creation with optional parent linkage and metadata application",
    )
    issue_create_p.add_argument("--repo", required=True, type=_normalize_repo_arg)
    issue_create_p.add_argument(
        "--type",
        choices=_ISSUE_TYPES,
        help="Issue type (uses template). If omitted, decision-tree prompts for it.",
    )
    issue_create_p.add_argument(
        "--parent-ref",
        default=None,
        help="Optional pre-supplied 'repo#N' parent ref; skips the sub-issue prompt.",
    )
    issue_create_p.add_argument(
        "--skip-metadata",
        action="store_true",
        help="Skip post-create metadata (labels, project fields, sub-issue link, "
        "paired-card prompt). Useful for testing or scripted setup.",
    )
    issue_prepare_p = issue_sp.add_parser(
        "prepare",
        help="Prepare a team-aware issue draft and readiness sidecar without GitHub mutation",
    )
    issue_prepare_p.add_argument("--repo", required=True, type=_normalize_repo_arg)
    issue_prepare_p.add_argument(
        "--type",
        required=True,
        choices=_ISSUE_TYPES,
    )
    issue_prepare_p.add_argument("--team", required=True, choices=_TEAM_CHOICES)
    issue_prepare_p.add_argument("--project", required=True, choices=PROJECT_CHOICES)
    issue_prepare_p.add_argument("--title", default=None)
    issue_prepare_p.add_argument("--status", default=None)
    issue_prepare_p.add_argument("--risk", default=None)
    issue_prepare_p.add_argument("--mode", default=None)
    issue_prepare_p.add_argument("--source-file", default=None)
    issue_prepare_p.add_argument(
        "--from",
        dest="from_ref",
        default=None,
        help="Source artifact ref: local path, GitHub issue/PR URL, branch ref, or search hint",
    )
    issue_prepare_p.add_argument(
        "--maturity",
        dest="handoff_maturity",
        default=None,
        choices=_HANDOFF_MATURITY_CHOICES,
        help="Override inferred handoff maturity",
    )
    issue_prepare_p.add_argument("source", nargs="*")

    issue_create_prepared_p = issue_sp.add_parser(
        "create-prepared",
        help="Create a prepared issue draft after readiness checks and final confirmation",
    )
    issue_create_prepared_p.add_argument("draft")
    issue_create_prepared_p.add_argument(
        "--yes",
        action="store_true",
        help="Apply the rendered mutation plan without an interactive prompt",
    )
    issue_create_prepared_p.add_argument(
        "--override-mapping",
        action="store_true",
        help="Create the issue before a missing project-mapping PR merges",
    )
    issue_create_prepared_p.add_argument(
        "--skip-approval",
        action="store_true",
        help="Bypass the Needs Operator Approval gate (operator's direct "
        "prepare->create path); otherwise approve via `issue approve` first",
    )

    issue_approve_p = issue_sp.add_parser(
        "approve",
        help="Batch-approve prepared drafts out of the Needs Operator Approval gate",
    )
    issue_approve_p.add_argument(
        "drafts",
        nargs="+",
        help="One or more prepared draft markdown paths to approve",
    )

    # #380: capture-side producer of the ship-policy intent envelope. Answer values are
    # validated against the fleet interview's closed vocabulary at render time (fail
    # closed), never enumerated here a second time.
    issue_intent_envelope_p = issue_sp.add_parser(
        "intent-envelope",
        help="Render the schema-validated intent-envelope block to embed in an issue body",
    )
    issue_intent_envelope_p.add_argument(
        "--run-mode",
        required=True,
        help="The run_mode answer (typed against the fleet interview's closed options)",
    )
    issue_intent_envelope_p.add_argument(
        "--reviews-required", default=None, help="Ceremony gate: gate|auto (default gate)"
    )
    issue_intent_envelope_p.add_argument(
        "--merge", default=None, help="Ceremony gate: gate|auto (default gate)"
    )
    issue_intent_envelope_p.add_argument(
        "--deploy-nonprod", default=None, help="Ceremony gate: gate|auto (default gate)"
    )
    issue_intent_envelope_p.add_argument("--authored-by", default="")

    # U3 (#279): issue write verbs — close / reopen / comment / label-add / label-remove
    issue_close_p = issue_sp.add_parser("close", help="Close a GitHub issue (idempotent)")
    issue_close_p.add_argument("--repo", required=True, type=_normalize_repo_arg)
    issue_close_p.add_argument("--number", required=True, type=int)

    issue_reopen_p = issue_sp.add_parser("reopen", help="Reopen a closed GitHub issue (idempotent)")
    issue_reopen_p.add_argument("--repo", required=True, type=_normalize_repo_arg)
    issue_reopen_p.add_argument("--number", required=True, type=int)

    issue_comment_p = issue_sp.add_parser("comment", help="Post a comment on a GitHub issue")
    issue_comment_p.add_argument("--repo", required=True, type=_normalize_repo_arg)
    issue_comment_p.add_argument("--number", required=True, type=int)
    issue_comment_p.add_argument("--body", required=True)

    issue_label_add_p = issue_sp.add_parser(
        "label-add", help="Add a label to a GitHub issue (idempotent)"
    )
    issue_label_add_p.add_argument("--repo", required=True, type=_normalize_repo_arg)
    issue_label_add_p.add_argument("--number", required=True, type=int)
    issue_label_add_p.add_argument("--label", required=True)

    issue_label_remove_p = issue_sp.add_parser(
        "label-remove", help="Remove a label from a GitHub issue (idempotent — 404 = success)"
    )
    issue_label_remove_p.add_argument("--repo", required=True, type=_normalize_repo_arg)
    issue_label_remove_p.add_argument("--number", required=True, type=int)
    issue_label_remove_p.add_argument("--label", required=True)

    # ===========================
    # LABELS
    # ===========================
    labels_p = subparsers.add_parser("labels", help="Label management")
    labels_sp = labels_p.add_subparsers(dest="action", required=True)

    labels_sync_p = labels_sp.add_parser(
        "sync-fields", help="Sync initiative/objective labels to project fields"
    )
    labels_sync_p.add_argument("--repo", required=True, type=_normalize_repo_arg)
    labels_sync_p.add_argument("--number", required=True, type=int)

    labels_audit_p = labels_sp.add_parser("audit", help="Check repo has all SDLC labels")
    labels_audit_p.add_argument("--repo", required=True, type=_normalize_repo_arg)

    labels_deploy_p = labels_sp.add_parser("deploy", help="Create/update all labels in repo")
    labels_deploy_p.add_argument("--repo", required=True, type=_normalize_repo_arg)

    labels_auto_p = labels_sp.add_parser("auto-label", help="Apply auto-label rules to issue")
    labels_auto_p.add_argument("--repo", required=True, type=_normalize_repo_arg)
    labels_auto_p.add_argument("--number", required=True, type=int)

    # ===========================
    # FIELDS
    # ===========================
    fields_p = subparsers.add_parser("fields", help="Project field management")
    fields_sp = fields_p.add_subparsers(dest="action", required=True)

    fields_create_p = fields_sp.add_parser("create-option", help="Create new single-select option")
    fields_create_p.add_argument("--project", required=True, choices=PROJECT_CHOICES)
    fields_create_p.add_argument(
        "--field", required=True, help="Field name (e.g. initiative, objective)"
    )
    fields_create_p.add_argument("--option", required=True, help="New option name")

    fields_discover_p = fields_sp.add_parser("discover", help="Discover all fields and options")
    fields_discover_p.add_argument("--project", required=True, choices=PROJECT_CHOICES)

    # ===========================
    # METRICS
    # ===========================
    metrics_p = subparsers.add_parser("metrics", help="Flow metrics and analysis")
    metrics_sp = metrics_p.add_subparsers(dest="action", required=True)

    metrics_ct_p = metrics_sp.add_parser("cycle-time", help="Cycle time percentiles")
    metrics_ct_p.add_argument("--project", required=True, choices=PROJECT_CHOICES)
    metrics_ct_p.add_argument("--days", type=int, default=30)
    metrics_ct_p.add_argument(
        "--type", choices=["capability", "enhancement", "defect", "exploration"]
    )

    metrics_th_p = metrics_sp.add_parser("throughput", help="Items deployed per week")
    metrics_th_p.add_argument("--project", required=True, choices=PROJECT_CHOICES)
    metrics_th_p.add_argument("--weeks", type=int, default=4)

    metrics_age_p = metrics_sp.add_parser("wip-age", help="Age of in-progress items")
    metrics_age_p.add_argument("--project", required=True, choices=PROJECT_CHOICES)

    metrics_col_p = metrics_sp.add_parser(
        "column-time", help="Time in each column for a specific item"
    )
    metrics_col_p.add_argument("--project", required=True, choices=PROJECT_CHOICES)
    metrics_col_p.add_argument("--number", required=True, type=int)

    # ===========================
    # MILESTONES
    # ===========================
    ms_p = subparsers.add_parser("milestones", help="Milestone management for Objectives")
    ms_sp = ms_p.add_subparsers(dest="action", required=True)

    ms_create_p = ms_sp.add_parser("create", help="Create milestone for Objective")
    ms_create_p.add_argument("--repo", required=True, type=_normalize_repo_arg)
    ms_create_p.add_argument(
        "--title", required=True, help="Milestone title (e.g. 'Pilot: Auth MVP')"
    )
    ms_create_p.add_argument("--due-date", required=True, help="Due date (YYYY-MM-DD)")
    ms_create_p.add_argument("--description", default="", help="Milestone description")

    ms_list_p = ms_sp.add_parser("list", help="List milestones")
    ms_list_p.add_argument("--repo", required=True, type=_normalize_repo_arg)
    ms_list_p.add_argument("--state", choices=["open", "closed", "all"], default="open")

    ms_progress_p = ms_sp.add_parser("progress", help="Show milestone completion percent")
    ms_progress_p.add_argument("--repo", required=True, type=_normalize_repo_arg)
    ms_progress_p.add_argument("--milestone", required=True, type=int, help="Milestone number")

    ms_link_p = ms_sp.add_parser("link", help="Link issue to milestone")
    ms_link_p.add_argument("--repo", required=True, type=_normalize_repo_arg)
    ms_link_p.add_argument("--issue", required=True, type=int)
    ms_link_p.add_argument("--milestone", required=True, type=int)

    # ===========================
    # ROLLOUT
    # ===========================
    rollout_p = subparsers.add_parser("rollout", help="Rollout tracking and deployment")
    rollout_sp = rollout_p.add_subparsers(dest="action", required=True)

    rollout_status_p = rollout_sp.add_parser("status", help="Show rollout status")
    rollout_status_p.add_argument("--team", help="Filter by team")

    rollout_gap_p = rollout_sp.add_parser("gap-analysis", help="Check what's missing from a repo")
    rollout_gap_p.add_argument("--repo", required=True, type=_normalize_repo_arg)

    rollout_labels_p = rollout_sp.add_parser("deploy-labels", help="Deploy all SDLC labels to repo")
    rollout_labels_p.add_argument("--repo", required=True, type=_normalize_repo_arg)

    rollout_templates_p = rollout_sp.add_parser(
        "deploy-templates", help="Deploy all SDLC templates to repo"
    )
    rollout_templates_p.add_argument("--repo", required=True, type=_normalize_repo_arg)

    rollout_all_p = rollout_sp.add_parser("deploy-all", help="Full SDLC deployment to repo")
    rollout_all_p.add_argument("--repo", required=True, type=_normalize_repo_arg)

    rollout_update_p = rollout_sp.add_parser("update", help="Update beads-config.json")
    rollout_update_p.add_argument("--repo", required=True, type=_normalize_repo_arg)
    rollout_update_p.add_argument(
        "--field", required=True, choices=["labels", "templates", "claude_md", "project"]
    )
    rollout_update_p.add_argument(
        "--status", required=True, choices=["pending", "in-progress", "complete"]
    )

    # ===========================
    # FLOW (Phase C — operator-facing GraphQL/REST surface)
    # ===========================
    flow_p = subparsers.add_parser("flow", help="Operator-facing GraphQL + REST helpers")
    flow_sp = flow_p.add_subparsers(dest="action", required=True)

    flow_setfield_p = flow_sp.add_parser(
        "set-field",
        help="Set a single-select project field on a card",
    )
    flow_setfield_p.add_argument("--project", required=True, help="Project name (e.g., operations)")
    flow_setfield_p.add_argument("--repo", required=True, type=_normalize_repo_arg)
    flow_setfield_numbers = flow_setfield_p.add_mutually_exclusive_group(required=True)
    flow_setfield_numbers.add_argument("--number", type=int)
    flow_setfield_numbers.add_argument("--numbers", type=_parse_numbers_arg)
    flow_setfield_p.add_argument(
        "--field",
        required=True,
        action="append",
        help="Field name (repeat with --option to set multiple fields)",
    )
    flow_setfield_p.add_argument(
        "--option",
        required=True,
        action="append",
        help="Option name, case-insensitive (repeat with --field)",
    )

    flow_options_p = flow_sp.add_parser(
        "field-options",
        help="List current options for a project field (live discovery)",
    )
    flow_options_p.add_argument("--project", required=True)
    flow_options_p.add_argument("--field", required=True)

    flow_disc_p = flow_sp.add_parser(
        "discover-project",
        help="Resolve which project(s) a repo is mapped to",
    )
    flow_disc_p.add_argument("--repo", required=True, type=_normalize_repo_arg)

    flow_assign_mimir_p = flow_sp.add_parser(
        "assign-mimir",
        help="Apply the covered repository's Team Mimir intake trigger (idempotent)",
    )
    flow_assign_mimir_p.add_argument("--repo", required=True, type=_normalize_repo_arg)
    flow_assign_mimir_p.add_argument("--number", required=True, type=int)

    flow_link_p = flow_sp.add_parser(
        "link-sub-issue",
        help="Link child as native sub-issue of parent (cross-repo supported, idempotent)",
    )
    flow_link_p.add_argument("--parent-repo", required=True, type=_normalize_repo_arg)
    flow_link_p.add_argument("--parent-number", required=True, type=int)
    flow_link_p.add_argument("--child-repo", required=True, type=_normalize_repo_arg)
    flow_link_p.add_argument("--child-number", required=True, type=int)

    flow_unlink_p = flow_sp.add_parser(
        "unlink-sub-issue",
        help="Remove a native parent/child relationship (cross-repo supported, idempotent)",
    )
    flow_unlink_p.add_argument("--parent-repo", required=True, type=_normalize_repo_arg)
    flow_unlink_p.add_argument("--parent-number", required=True, type=int)
    flow_unlink_p.add_argument("--child-repo", required=True, type=_normalize_repo_arg)
    flow_unlink_p.add_argument("--child-number", required=True, type=int)

    flow_label_p = flow_sp.add_parser(
        "verify-label",
        help="Self-healing label create (404 → create; exists → no-op; other errors raise)",
    )
    flow_label_p.add_argument("--repo", required=True, type=_normalize_repo_arg)
    flow_label_p.add_argument("--name", required=True)
    flow_label_p.add_argument("--color", default=None, help="Hex color without leading '#'")
    flow_label_p.add_argument("--description", default=None)

    flow_validate_p = flow_sp.add_parser(
        "validate-card",
        help="Run card_validator schema check on an existing issue body",
    )
    flow_validate_p.add_argument("--repo", required=True, type=_normalize_repo_arg)
    flow_validate_p.add_argument("--number", required=True, type=int)

    # ===========================
    # CONFIG
    # ===========================
    config_p = subparsers.add_parser("config", help="Configuration operations")
    config_sp = config_p.add_subparsers(dest="action", required=True)
    config_sp.add_parser("show", help="Show loaded configuration")
    config_sp.add_parser(
        "show-defaults", help="Show per-user defaults from ~/.claude/sdlc-defaults.json"
    )
    config_init_p = config_sp.add_parser(
        "init-defaults",
        help="First-run wizard to seed per-user defaults",
    )
    config_init_p.add_argument(
        "--non-interactive",
        action="store_true",
        help="Seed with auto-detected values only (gh login as assignee, etc.); no prompts",
    )

    # ===========================
    # PARSE AND ROUTE
    # ===========================
    args = parser.parse_args()
    fmt = args.format

    try:
        if args.resource == "board":
            if args.action == "view":
                board_view(args.project, args.status, fmt)
            elif args.action == "add":
                # `--project` is repeatable (action="append"): args.project is
                # None (repo-mapping default) or a list of named projects.
                board_add(args.repo, args.number, fmt, project_names=args.project)
            elif args.action == "move":
                if not board_move(
                    args.repo,
                    args.number,
                    args.status,
                    fmt,
                    project_name=args.project,
                ):
                    raise SystemExit(1)
            elif args.action == "archive":
                board_archive(args.project, args.dry_run, fmt)
            elif args.action == "wip":
                board_wip(args.project, fmt)
            elif args.action == "standup":
                board_standup(args.project, fmt)
            elif args.action == "discover-fields":
                board_discover_fields(args.project, fmt)

        elif args.resource == "issue":
            if args.action == "create":
                issue_create(
                    args.repo,
                    args.type,
                    fmt,
                    parent_ref=args.parent_ref,
                    skip_metadata=args.skip_metadata,
                )
            elif args.action == "prepare":
                source, source_artifact = _resolve_prepare_source(
                    args.source,
                    args.source_file,
                    args.from_ref,
                )
                issue_prepare(
                    repo=args.repo,
                    issue_type=args.type,
                    team=args.team,
                    project=args.project,
                    source=source,
                    title=args.title,
                    status=args.status,
                    risk=args.risk,
                    mode=args.mode,
                    handoff_maturity=args.handoff_maturity,
                    source_artifact=source_artifact,
                    fmt=fmt,
                )
            elif args.action == "create-prepared":
                issue_create_prepared(
                    Path(args.draft),
                    fmt=fmt,
                    auto_confirm=args.yes,
                    override_mapping=args.override_mapping,
                    skip_approval=args.skip_approval,
                )
            elif args.action == "approve":
                prepared_approve_batch([Path(d) for d in args.drafts], fmt=fmt)
            elif args.action == "intent-envelope":
                issue_render_intent_envelope(
                    args.run_mode,
                    reviews_required=args.reviews_required,
                    merge=args.merge,
                    deploy_nonprod=args.deploy_nonprod,
                    authored_by=args.authored_by,
                )
            # U3 (#279): issue write verbs
            elif args.action == "close":
                issue_close(args.repo, args.number, fmt)
            elif args.action == "reopen":
                issue_reopen(args.repo, args.number, fmt)
            elif args.action == "comment":
                issue_comment(args.repo, args.number, args.body, fmt)
            elif args.action == "label-add":
                issue_label_add(args.repo, args.number, args.label, fmt)
            elif args.action == "label-remove":
                issue_label_remove(args.repo, args.number, args.label, fmt)

        elif args.resource == "labels":
            if args.action == "sync-fields":
                labels_sync_fields(args.repo, args.number, fmt)
            elif args.action == "audit":
                labels_audit(args.repo, fmt)
            elif args.action == "deploy":
                labels_deploy(args.repo, fmt)
            elif args.action == "auto-label":
                labels_auto_label(args.repo, args.number, fmt)

        elif args.resource == "fields":
            if args.action == "create-option":
                fields_create_option(args.project, args.field, args.option, fmt)
            elif args.action == "discover":
                fields_discover(args.project, fmt)

        elif args.resource == "metrics":
            if args.action == "cycle-time":
                metrics_cycle_time(args.project, args.days, args.type, fmt)
            elif args.action == "throughput":
                metrics_throughput(args.project, args.weeks, fmt)
            elif args.action == "wip-age":
                metrics_wip_age(args.project, fmt)
            elif args.action == "column-time":
                metrics_column_time(args.project, args.number, fmt)

        elif args.resource == "milestones":
            if args.action == "create":
                milestones_create(args.repo, args.title, args.due_date, args.description, fmt)
            elif args.action == "list":
                milestones_list(args.repo, args.state, fmt)
            elif args.action == "progress":
                milestones_progress(args.repo, args.milestone, fmt)
            elif args.action == "link":
                milestones_link(args.repo, args.issue, args.milestone, fmt)

        elif args.resource == "rollout":
            if args.action == "status":
                rollout_status(args.team, fmt)
            elif args.action == "gap-analysis":
                rollout_gap_analysis(args.repo, fmt)
            elif args.action == "deploy-labels":
                rollout_deploy_labels(args.repo, fmt)
            elif args.action == "deploy-templates":
                rollout_deploy_templates(args.repo, fmt)
            elif args.action == "deploy-all":
                rollout_deploy_all(args.repo, fmt)
            elif args.action == "update":
                rollout_update(args.repo, args.field, args.status, fmt)

        elif args.resource == "flow":
            if args.action == "set-field":
                if len(args.field) != len(args.option):
                    raise RuntimeError(
                        "flow set-field requires the same number of --field and --option values"
                    )
                if args.numbers is not None or len(args.field) > 1:
                    flow_set_fields_bulk(
                        args.project,
                        args.repo,
                        args.numbers if args.numbers is not None else [args.number],
                        list(zip(args.field, args.option, strict=True)),
                        fmt,
                    )
                else:
                    flow_set_field(
                        args.project, args.repo, args.number, args.field[0], args.option[0], fmt
                    )
            elif args.action == "field-options":
                flow_field_options(args.project, args.field, fmt)
            elif args.action == "discover-project":
                flow_discover_project(args.repo, fmt)
            elif args.action == "assign-mimir":
                flow_assign_mimir(args.repo, args.number, fmt)
            elif args.action == "link-sub-issue":
                flow_link_sub_issue(
                    args.parent_repo, args.parent_number, args.child_repo, args.child_number, fmt
                )
            elif args.action == "unlink-sub-issue":
                flow_unlink_sub_issue(
                    args.parent_repo, args.parent_number, args.child_repo, args.child_number, fmt
                )
            elif args.action == "verify-label":
                flow_verify_label(args.repo, args.name, args.color, args.description, fmt)
            elif args.action == "validate-card":
                flow_validate_card(args.repo, args.number, fmt)

        elif args.resource == "config":
            if args.action == "show":
                config_show(fmt)
            elif args.action == "show-defaults":
                config_show_defaults(fmt)
            elif args.action == "init-defaults":
                config_init_defaults(args.non_interactive, fmt)

    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        _error(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
