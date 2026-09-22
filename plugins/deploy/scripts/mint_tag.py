#!/usr/bin/env python3
"""Mint Infiquetra tag-promotion deployment tags."""

from __future__ import annotations

import argparse
import re
import subprocess  # nosec B404
import sys
from collections.abc import Sequence

ENV_TO_PREFIX = {
    "nonprod": "nonprod",
    "staging": "staging",
    "production": "production",
}

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:\.\d+)?$")


def run(cmd: list[str], *, check: bool = True, capture: bool = True) -> str:
    """Run a command and return stdout."""

    result = subprocess.run(  # nosec B603
        cmd,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() if result.stderr else "command failed"
        raise SystemExit(f"ERROR: {detail}")
    return result.stdout.strip() if result.stdout else ""


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
    """Resolve a repository name and reject non-Infiquetra owners."""

    if repo:
        resolved = repo if "/" in repo else f"infiquetra/{repo}"
    else:
        resolved = _remote_to_repo(run(["git", "remote", "get-url", "origin"]))

    owner, _, name = resolved.partition("/")
    if owner.lower() != "infiquetra" or not name:
        raise SystemExit(f"ERROR: expected github.com/infiquetra/* repository, got {resolved!r}")
    return f"infiquetra/{name}"


def build_tag_name(env: str, version: str, *, rollback: bool = False) -> str:
    """Build an Infiquetra deployment tag name."""

    normalized_env = env.strip().lower()
    if normalized_env not in ENV_TO_PREFIX:
        allowed = ", ".join(ENV_TO_PREFIX)
        raise SystemExit(f"ERROR: unknown environment {env!r}; expected one of {allowed}")

    normalized_version = version.strip().removeprefix("v")
    if not VERSION_RE.match(normalized_version):
        raise SystemExit("ERROR: version must look like 1.2.3 or hotfix form 1.2.3.1")

    prefix = ENV_TO_PREFIX[normalized_env]
    if rollback:
        prefix = f"rollback-{prefix}"
    return f"{prefix}-v{normalized_version}"


def strip_prefix(tag: str) -> str:
    """Strip Infiquetra deployment tag prefixes and return the version."""

    for prefix in (
        "rollback-production-v",
        "rollback-staging-v",
        "rollback-nonprod-v",
        "production-v",
        "staging-v",
        "nonprod-v",
        "v",
    ):
        if tag.startswith(prefix):
            return tag.removeprefix(prefix)
    return tag


def current_env_version(repo: str, env: str) -> str | None:
    """Return the currently deployed version for an environment."""

    ref = run(
        [
            "gh",
            "api",
            f"repos/{repo}/deployments?environment={env}&per_page=1",
            "--jq",
            ".[0].ref // empty",
        ],
        check=False,
    )
    return strip_prefix(ref) if ref else None


def tag_exists(tag: str) -> bool:
    """Return whether a tag exists locally or on origin."""

    local = run(["git", "tag", "-l", tag], check=False)
    if local == tag:
        return True
    remote = run(
        ["git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}"],
        check=False,
    )
    return tag in remote


def latest_snapshot_version() -> str | None:
    """Return the latest local or remote snapshot version."""

    latest = run(["git", "tag", "-l", "v[0-9]*", "--sort=-version:refname"], check=False)
    if not latest:
        run(["git", "fetch", "--tags", "origin"], check=False, capture=False)
        latest = run(["git", "tag", "-l", "v[0-9]*", "--sort=-version:refname"], check=False)
    if not latest:
        return None
    return latest.splitlines()[0].removeprefix("v")


def resolve_version(*, env: str, version: str | None, ref: str | None, repo: str) -> str:
    """Resolve explicit or inferred deployment version."""

    if version:
        return version.strip().removeprefix("v")
    if ref and ref != "HEAD":
        raise SystemExit("ERROR: --ref requires --version in hotfix mode.")

    if env == "nonprod":
        latest = latest_snapshot_version()
        if not latest:
            raise SystemExit("ERROR: no snapshot tags found; pass --version explicitly.")
        return latest

    prior_env = {"staging": "nonprod", "production": "staging"}[env]
    current = current_env_version(repo, prior_env)
    if not current:
        raise SystemExit(
            f"ERROR: cannot infer version: no current deployment in {prior_env}; "
            "pass --version explicitly."
        )
    return current


def assert_snapshot_not_unhealthy(
    *,
    tag: str,
    version: str,
    rollback: bool,
    ref: str | None,
    force_unhealthy: bool,
) -> None:
    """Refuse to promote snapshots marked unhealthy unless explicitly overridden."""

    if rollback or (ref and ref != "HEAD"):
        return
    unhealthy_tag = f"unhealthy-v{version}"
    if not tag_exists(unhealthy_tag):
        return
    if force_unhealthy:
        print(f">>> UNHEALTHY-OVERRIDE: minting {tag} despite {unhealthy_tag}")
        return
    raise SystemExit(
        f"ERROR: refusing to promote v{version} to {tag}: {unhealthy_tag} exists on origin. "
        "Fix forward, promote a newer healthy snapshot, or pass --force-unhealthy after "
        "manual verification."
    )


def _print_plan(repo: str, tag: str, ref: str, *, dry_run: bool) -> None:
    mode = "DRY RUN" if dry_run else "MUTATING"
    print(f"{mode}: {repo}")
    print(f"tag: {tag}")
    print(f"ref: {ref}")
    print(f"workflow: https://github.com/{repo}/actions")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", required=True, choices=sorted(ENV_TO_PREFIX))
    parser.add_argument("--version")
    parser.add_argument("--repo", help="Repository as name or owner/name")
    parser.add_argument("--ref", default="HEAD", help="Commit-ish to tag")
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--force-unhealthy",
        action="store_true",
        help="Override the unhealthy-v<version> quarantine marker after manual verification.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repo = resolve_repo(args.repo)
    version = resolve_version(env=args.env, version=args.version, ref=args.ref, repo=repo)
    tag = build_tag_name(args.env, version, rollback=args.rollback)
    source = args.ref if args.ref != "HEAD" else f"v{version}"
    _print_plan(repo, tag, source, dry_run=args.dry_run)

    if not args.rollback and args.ref == "HEAD" and not tag_exists(source):
        raise SystemExit(
            f"ERROR: snapshot {source} not found locally or on origin; cannot mint {tag}."
        )

    assert_snapshot_not_unhealthy(
        tag=tag,
        version=version,
        rollback=args.rollback,
        ref=args.ref,
        force_unhealthy=args.force_unhealthy,
    )

    if tag_exists(tag):
        raise SystemExit(f"ERROR: tag {tag} already exists locally or on origin.")

    if args.dry_run:
        print(f"[dry-run] would: git tag -a {tag} {source}^{{commit}} -m '...'")
        print(f"[dry-run] would: git push origin {tag}")
        return 0

    target_commit = run(["git", "rev-parse", f"{source}^{{commit}}"])
    message = f"Infiquetra {args.env} deployment {tag}"
    if args.rollback:
        message = f"Infiquetra {args.env} rollback {tag}"
    elif args.ref != "HEAD":
        message = f"Infiquetra {args.env} hotfix {tag}"

    run(["git", "fetch", "--tags", "origin"], capture=False)
    run(["git", "tag", "-a", tag, target_commit, "-m", message], capture=False)
    run(["git", "push", "origin", tag], capture=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
