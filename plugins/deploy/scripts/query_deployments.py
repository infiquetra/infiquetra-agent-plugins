#!/usr/bin/env python3
"""Query Infiquetra deployment status and report version drift."""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404
import sys
from collections.abc import Mapping, Sequence
from typing import Any

ENVIRONMENTS = ("nonprod", "staging", "production")
TAG_PREFIXES = (
    "rollback-production-v",
    "rollback-staging-v",
    "rollback-nonprod-v",
    "production-v",
    "staging-v",
    "nonprod-v",
    "v",
)


def run(cmd: list[str], *, check: bool = True) -> str:
    result = subprocess.run(  # nosec B603
        cmd,
        check=False,
        text=True,
        capture_output=True,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() if result.stderr else "command failed"
        raise SystemExit(f"ERROR: {detail}")
    return result.stdout.strip()


def strip_prefix(tag: str) -> str:
    """Strip Infiquetra deployment tag prefixes for drift comparison."""

    value = tag.strip()
    for prefix in TAG_PREFIXES:
        if value.startswith(prefix):
            return value.removeprefix(prefix)
    return value


def _remote_to_repo(remote_url: str) -> str:
    remote = remote_url.strip().removesuffix(".git")
    if "github.com:" in remote:
        path = remote.split("github.com:", 1)[1]
    elif "github.com/" in remote:
        path = remote.split("github.com/", 1)[1]
    else:
        raise SystemExit(f"ERROR: expected github.com/infiquetra/* remote, got {remote_url!r}")

    parts = path.strip("/").split("/")
    if len(parts) < 2:
        raise SystemExit(f"ERROR: expected github.com/infiquetra/* remote, got {remote_url!r}")
    return f"{parts[0]}/{parts[1]}"


def resolve_repo(repo: str | None) -> str:
    if repo:
        resolved = repo if "/" in repo else f"infiquetra/{repo}"
    else:
        resolved = _remote_to_repo(run(["git", "remote", "get-url", "origin"]))

    owner, _, name = resolved.partition("/")
    if owner.lower() != "infiquetra" or not name:
        raise SystemExit(f"ERROR: expected github.com/infiquetra/* repository, got {resolved!r}")
    return f"infiquetra/{name}"


def detect_drift(tags_by_env: Mapping[str, str | None]) -> list[str]:
    versions = {
        env: strip_prefix(tag)
        for env, tag in tags_by_env.items()
        if tag is not None and tag.strip()
    }
    if len(set(versions.values())) <= 1:
        return []
    return [f"{env}: {version}" for env, version in versions.items()]


def is_tag_ref(ref: str | None) -> bool:
    """True when ``ref`` is an Infiquetra deployment tag, not a branch/SHA ref.

    GitHub Actions ``environment:`` job keys auto-create Deployment records whose ref is a
    branch name or SHA (e.g. ``main``). Only records whose ref matches a known tag prefix
    followed by a version digit are real tag-promotion deployments.
    """

    if not ref:
        return False
    for prefix in TAG_PREFIXES:
        if ref.startswith(prefix):
            remainder = ref[len(prefix) :]
            return bool(remainder) and remainder[0].isdigit()
    return False


def latest_deployment(repo: str, env: str) -> dict[str, Any] | None:
    payload = run(
        [
            "gh",
            "api",
            "--method",
            "GET",
            f"repos/{repo}/deployments",
            "-f",
            f"environment={env}",
            "-f",
            "per_page=20",
        ]
    )
    data: list[dict[str, Any]] = json.loads(payload or "[]")
    for record in data:  # GitHub returns deployment records newest-first
        if is_tag_ref(str(record.get("ref") or "")):
            return record
    return None


def render_status(repo: str, deployments: Mapping[str, dict[str, Any] | None]) -> str:
    lines = [f"deployment status: {repo}"]
    tags_by_env: dict[str, str | None] = {}
    for env in ENVIRONMENTS:
        deployment = deployments.get(env)
        if not deployment:
            lines.append(f"- {env}: no deployment found")
            tags_by_env[env] = None
            continue

        ref = str(deployment.get("ref") or deployment.get("sha") or "unknown")
        tags_by_env[env] = ref
        lines.append(f"- {env}: {ref} (version {strip_prefix(ref)})")

    drift = detect_drift(tags_by_env)
    if drift:
        lines.append("drift:")
        lines.extend(f"- {item}" for item in drift)
    else:
        lines.append("drift: none detected")
    lines.append(f"workflow: https://github.com/{repo}/actions")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", help="Repository as name or owner/name")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repo = resolve_repo(args.repo)
    deployments = {env: latest_deployment(repo, env) for env in ENVIRONMENTS}
    print(render_status(repo, deployments))
    return 0


if __name__ == "__main__":
    sys.exit(main())
