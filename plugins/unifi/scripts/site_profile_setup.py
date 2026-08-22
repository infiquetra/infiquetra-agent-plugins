#!/usr/bin/env python3
"""First-setup entrypoint for the UniFi operator site profile.

A contract that nothing presents is not reachable by a user, so presenting the
first-setup choice is a named module rather than an implied behavior. On first
setup with no configured profile available, exactly three safe paths exist:

1. Supply an existing profile path.
2. Run credential-safe read-only discovery and generate a proposed profile for
   operator review.
3. Continue in discovery-only mode, with the limits of unknown operator intent
   stated explicitly.

There is no fourth path, and the count is asserted by test so one cannot be
added silently. The chosen path is written to the portable configuration file
so setup is not asked again on every use.

Output is JSON on standard output, matching the output discipline the UniFi
clients already use, so the entrypoint is equally usable by an operator, by a
skill, and by a test.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import site_profile
from site_profile import (
    DISCOVERY_ONLY_LIMITS,
    DISCOVERY_ONLY_MODE,
    ENVIRONMENT_VARIABLE,
    PROFILE_MODE,
    SiteProfileError,
    config_file_path,
    default_profile_path,
    load_profile_document,
    read_config,
    write_config,
)


EXISTING_PROFILE = "existing-profile"
DISCOVERY_PROPOSAL = "discovery-proposal"
DISCOVERY_ONLY = "discovery-only"


@dataclass(frozen=True)
class SetupPath:
    """One of the three safe first-setup choices."""

    key: str
    title: str
    description: str
    requires_profile_path: bool
    next_step: str

    def describe(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "description": self.description,
            "requires_profile_path": self.requires_profile_path,
            "next_step": self.next_step,
        }


#: Exactly three paths. A fourth would be a change to the contract, not a
#: convenience, so the count is part of what the tests hold.
SETUP_PATHS: tuple[SetupPath, ...] = (
    SetupPath(
        key=EXISTING_PROFILE,
        title="Use an existing site profile",
        description=(
            "Point the package at a profile file you already maintain. The file is "
            "validated against the site-profile contract before the choice is "
            "remembered, so a malformed profile is rejected now rather than on first "
            "use."
        ),
        requires_profile_path=True,
        next_step="site_profile_setup.py --choose existing-profile --profile-path PATH",
    ),
    SetupPath(
        key=DISCOVERY_PROPOSAL,
        title="Generate a proposed profile from read-only discovery",
        description=(
            "Run credential-safe, read-only discovery and write a proposed profile for "
            "your review. The proposal records what the controller reports and marks "
            "every intent field unknown, because observing a host cannot establish who "
            "owns it or how much it matters. Nothing is applied: review the proposal, "
            "fill in intent yourself, then return here and choose "
            f"{EXISTING_PROFILE!r}."
        ),
        requires_profile_path=False,
        next_step="discover.py --propose-profile --output PATH",
    ),
    SetupPath(
        key=DISCOVERY_ONLY,
        title="Continue without a profile",
        description=(
            "Fully supported. The package reports actual controller state and infers no "
            "trust role, criticality, ownership, or intended policy. Every such query "
            "answers with an explicit unknown."
        ),
        requires_profile_path=False,
        next_step="site_profile_setup.py --choose discovery-only",
    ),
)

SETUP_PATH_KEYS: tuple[str, ...] = tuple(path.key for path in SETUP_PATHS)


def setup_path(key: str) -> SetupPath:
    for candidate in SETUP_PATHS:
        if candidate.key == key:
            return candidate
    raise SiteProfileError(
        f"unknown setup path {key!r}; the three paths are {', '.join(SETUP_PATH_KEYS)}"
    )


def present_paths(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """The three paths, with the environment override stated alongside them."""
    return {
        "configured": False,
        "path_count": len(SETUP_PATHS),
        "paths": [path.describe() for path in SETUP_PATHS],
        "config_file": str(config_file_path(environ)),
        "default_profile_path": str(default_profile_path(environ)),
        "environment_override": ENVIRONMENT_VARIABLE,
        "discovery_only_limits": list(DISCOVERY_ONLY_LIMITS),
    }


def choose(
    key: str,
    profile_path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Record the operator's choice so setup is not asked again."""
    chosen = setup_path(key)

    resolved: Path | None = None
    if chosen.requires_profile_path:
        if profile_path is None or not str(profile_path).strip():
            raise SiteProfileError(
                f"setup path {chosen.key!r} requires a profile path"
            )
        resolved = Path(str(profile_path)).expanduser()
        # Validate before remembering. A choice that is remembered but unusable
        # is worse than a choice that fails now, because the failure surfaces
        # later against whatever the operator was actually trying to do.
        load_profile_document(resolved)
    elif profile_path is not None and str(profile_path).strip():
        raise SiteProfileError(
            f"setup path {chosen.key!r} takes no profile path"
        )

    config = {
        "config_version": site_profile.CONFIG_VERSION,
        "setup_path": chosen.key,
        "site_profile_path": str(resolved) if resolved is not None else None,
    }
    written = write_config(config, environ=environ, config_path=config_path)
    return {
        "configured": True,
        "setup_path": chosen.key,
        "mode": PROFILE_MODE if resolved is not None else DISCOVERY_ONLY_MODE,
        "site_profile_path": str(resolved) if resolved is not None else None,
        "config_file": str(written),
        "next_step": chosen.next_step,
    }


def status(
    environ: Mapping[str, str] | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Report the remembered choice, or present the three paths on first setup.

    A configuration file that names a profile which no longer exists is
    reported as exactly that. It never degrades quietly to discovery-only,
    because the operator said a profile was there and the honest answer is that
    it has gone.
    """
    config = read_config(environ=environ, config_path=config_path)
    if not config:
        return present_paths(environ)

    resolved_config = (
        Path(config_path) if config_path is not None else config_file_path(environ)
    )
    report: dict[str, Any] = {
        "configured": True,
        "setup_path": config.get("setup_path"),
        "site_profile_path": config.get("site_profile_path"),
        "config_file": str(resolved_config),
    }
    try:
        context = site_profile.load_site_context(environ=environ, config_path=config_path)
    except SiteProfileError as exc:
        report["error"] = str(exc)
        report["error_type"] = type(exc).__name__
        return report
    report["mode"] = context.mode
    report["profile_source"] = context.source
    report["context"] = context.describe()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Present the three first-setup paths for the UniFi operator site profile, "
            "and remember the chosen one."
        )
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print the three setup paths without reading the remembered choice.",
    )
    parser.add_argument(
        "--choose",
        choices=SETUP_PATH_KEYS,
        default=None,
        help="Record one of the three setup paths.",
    )
    parser.add_argument(
        "--profile-path",
        default=None,
        help=f"Profile file to remember; required by --choose {EXISTING_PROFILE}.",
    )
    parser.add_argument(
        "--config-path",
        default=None,
        help="Configuration file to read and write instead of the XDG default.",
    )
    arguments = parser.parse_args(argv)
    config_path = Path(arguments.config_path) if arguments.config_path else None

    try:
        if arguments.list:
            report = present_paths()
        elif arguments.choose:
            report = choose(
                arguments.choose,
                profile_path=arguments.profile_path,
                config_path=config_path,
            )
        else:
            report = status(config_path=config_path)
    except SiteProfileError as exc:
        print(json.dumps({"error": str(exc), "error_type": type(exc).__name__}, indent=2))
        return 1

    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
