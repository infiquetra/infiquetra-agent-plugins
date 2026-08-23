#!/usr/bin/env python3
"""Run the ten-client compatibility assessment as a script instead of a method.

The UniFi pilot ran this assessment nine times. Every run was driven by hand
from a written method, and each one re-learned the same quirks the hard way: an
installer that waits on standard input and lists-and-exits when nothing answers;
a launcher whose real binary cannot be found under an isolated home; a client
that must run against the operator's *authenticated* home or it measures an
unauthenticated first-run client and reports a false failure. The method was
preserved in prose. This file is that method as a program.

What it does, per client, in order:

1. **placement** -- put the package where the client can see it;
2. **discovery** -- ask the client whether it sees it;
3. **load** -- ask the client what components it resolved, which is what
   separates "a directory is listed" from "the unit parsed";
4. **invocation** -- run the package's own entrypoint from the path the client
   resolved, credential-free.

What it refuses to do:

* **Run without saying so.** Nothing executes unless `--execute` is passed. The
  default prints the plan, including the exact argv of every stage.
* **Carry a credential.** Every environment variable matching the package's
  declared credential prefixes is removed from every subprocess environment. A
  client that needs credentials before it will report state gets a **blocked**
  stage naming the requirement, never a satisfied one.
* **Mutate anything live.** Each client runs under its own scratch home. The two
  clients whose quirks require otherwise are handled explicitly and narrowly:
  one may use the real home but may not run a stage that writes client state,
  and one is isolated-only and is refused a real home outright.
* **Invoke a write.** Every stage's argv goes through the same safety predicate
  the matrix validator applies to a recorded command --
  `check_compatibility_matrix.command_safety_problems` -- before it runs. One
  authority, checked before the fact here and after the fact there.
* **Report a package it did not assess.** The package tree is fingerprinted
  before and after the run. If it moved, no record is emitted: something wrote
  into the tree under assessment, and every result is suspect.
* **Invent a verdict.** The overall status per client is proposed from the stage
  results, and the human-readable reason is left empty on purpose. An empty
  reason fails `check_compatibility_matrix.py`, so a record no one finished
  cannot be committed as evidence.

Usage::

    python3 scripts/assess_clients.py --package unifi                  # print the plan
    python3 scripts/assess_clients.py --package unifi --execute \\
        --python /opt/homebrew/bin/python3.12 --out docs/evidence/<date>-matrix.md

Standard library only, matching the rest of this repository's tooling.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_compatibility_matrix as ccm  # noqa: E402
import port_config  # noqa: E402
from port_config import PortConfig, PortConfigError  # noqa: E402


#: Placeholders a stage's argv may carry. They are substituted immediately
#: before the process starts, and substituted *back* before anything is written
#: into the record, which is what keeps a real home directory path out of a
#: public evidence document.
PACKAGE = "<package>"
SKILL = "<skill>"
CLIENT_HOME = "<client-home>"
PYTHON = "<python>"
PLUGIN_ID = "<plugin-id>"
PLUGIN_NAME = "<plugin-name>"

#: Every stage gets a deadline. Two clients prompt for confirmation on standard
#: input and one of them hangs rather than declining when stdin is closed, so a
#: run without deadlines does not fail -- it stops, forever, with no record.
DEFAULT_TIMEOUT = 120.0

#: An isolated home is the default. `real` exists for exactly one client whose
#: authentication lives in the operator's home and whose isolated-home result is
#: therefore a measurement of a different client.
ISOLATED_HOME = "isolated"
REAL_HOME = "real"

EXECUTED = "executed"
BLOCKED = "blocked"
NOT_APPLICABLE = "not-applicable"


class AssessmentError(RuntimeError):
    """The run cannot proceed, or its result cannot be trusted."""


class StageSpec:
    """One stage of one client: what to run, how, and under what deadline."""

    __slots__ = (
        "stage",
        "argv",
        "per_skill",
        "stdin",
        "timeout",
        "writes_client_state",
        "capture",
        "blocked_reason",
        "evidence",
        "from_package",
    )

    def __init__(
        self,
        stage: str,
        argv: tuple[str, ...] = (),
        *,
        per_skill: bool = False,
        stdin: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        writes_client_state: bool = False,
        capture: tuple[str, str] | None = None,
        blocked_reason: str | None = None,
        evidence: str = "",
        from_package: bool = False,
    ) -> None:
        if stage not in ccm.STAGES:
            raise AssessmentError(f"{stage!r} is not one of {', '.join(ccm.STAGES)}")
        #: The invocation stage's argv is the package's own entrypoints, which
        #: only the descriptor knows, so it is filled in at run time. Saying so
        #: explicitly keeps the "a stage runs something or says why not" guard
        #: able to catch a stage that is genuinely empty by mistake.
        self.from_package = from_package
        if blocked_reason is None and not argv and not from_package:
            raise AssessmentError(f"{stage}: a stage either runs a command or names why it cannot")
        self.stage = stage
        self.argv = argv
        self.per_skill = per_skill
        self.stdin = stdin
        self.timeout = timeout
        self.writes_client_state = writes_client_state
        #: ``(placeholder, pattern)``: a value this stage reads out of its own
        #: output for a later stage to use. Grok's install id is generated by
        #: the client, so no plan can know it in advance.
        self.capture = capture
        #: Set when the stage is known in advance not to be runnable -- not
        #: because the tool is missing, but because the client's own design
        #: leaves nothing to do. Codex places nothing, so it loads nothing.
        self.blocked_reason = blocked_reason
        self.evidence = evidence


class ClientPlan:
    """One client, its quirk, and its four stages."""

    __slots__ = (
        "name",
        "binary",
        "home",
        "environment",
        "stages",
        "quirk",
        "skill_scoped",
        "invocation_root",
    )

    def __init__(
        self,
        name: str,
        *,
        binary: str,
        stages: tuple[StageSpec, ...],
        home: str = ISOLATED_HOME,
        environment: dict[str, str] | None = None,
        quirk: str = "",
        skill_scoped: bool = False,
        invocation_root: str = PACKAGE,
    ) -> None:
        self.name = name
        self.binary = binary
        self.home = home
        #: Where *this* client put the package. The invocation stage runs the
        #: entrypoint from here rather than from the source tree, because a
        #: stage that ran out of the source proves the operator's disk works,
        #: not that the client resolved anything. Clients that place
        #: session-scoped leave it at the package root they were handed; clients
        #: that copy or link name their own directory.
        self.invocation_root = invocation_root
        #: Extra variables this client needs. Values may carry placeholders.
        self.environment = environment or {}
        self.stages = stages
        #: Recorded in the plan output so the operator sees why a client is
        #: handled differently before deciding to run it.
        self.quirk = quirk
        #: True when the client consumes individual skill units rather than the
        #: package root. Its placement runs once per unit.
        self.skill_scoped = skill_scoped
        found = tuple(spec.stage for spec in stages)
        if sorted(found) != sorted(ccm.STAGES):
            raise AssessmentError(
                f"{name}: covers {found}, but a row must carry all four stages; a row that "
                "stops at its first failure proves nothing about whether the package loaded"
            )

    def stage(self, name: str) -> StageSpec:
        for spec in self.stages:
            if spec.stage == name:
                return spec
        raise AssessmentError(f"{self.name}: no {name} stage")  # pragma: no cover - guarded above


#: The probe handed to the one client that reports its loaded state through a
#: model turn rather than through a subcommand. It is bounded to session context
#: and forbids every tool that could read the disk or reach the network, so what
#: comes back describes what the client loaded rather than what is on disk.
CURSOR_DISCOVERY_PROBE = (
    "Report the locally loaded plugin and component names available from session context. "
    "Do not use filesystem, shell, network, or UniFi tools."
)
CURSOR_LOAD_PROBE = (
    "From session context only, for the plugin loaded from the session-scoped local plugin "
    "directory (not any marketplace-installed plugin of the same name): report its plugin name, "
    "its version if session context carries one, and the exact component names it contributes. "
    "Do not use filesystem, shell, network, or UniFi tools."
)


def _client_plans() -> tuple[ClientPlan, ...]:
    """The ten plans, one per canonical client.

    Every quirk recorded here was learned across nine assessment runs and is
    carried so the next port does not re-learn it. The membership of this tuple
    is asserted against `check_compatibility_matrix.CANONICAL_CLIENTS` rather
    than restated, so a client added to the roster fails here until it has a
    plan.
    """
    return (
        ClientPlan(
            "Claude Code",
            binary="claude",
            quirk=(
                "User-scope installation needs a marketplace file the portable root does not "
                "carry. Placement is session-scoped through the local-plugin flag, which is "
                "re-supplied on every later stage."
            ),
            stages=(
                StageSpec("placement", ("claude", "--plugin-dir", PACKAGE, "plugin", "list")),
                StageSpec("discovery", ("claude", "--plugin-dir", PACKAGE, "plugin", "list")),
                StageSpec(
                    "load",
                    ("claude", "--plugin-dir", PACKAGE, "plugin", "details", PLUGIN_NAME),
                ),
                StageSpec("invocation", from_package=True),
            ),
        ),
        ClientPlan(
            "OpenAI Codex",
            binary="codex",
            quirk=(
                "Refuses the package root with an actionable message naming the manifest it "
                "wants. The marketplace is its only placement path, so load and invocation "
                "stay blocked on the absent adapter rather than on any package defect."
            ),
            stages=(
                StageSpec(
                    "placement",
                    ("codex", "plugin", "marketplace", "add", PACKAGE),
                    writes_client_state=True,
                ),
                StageSpec("discovery", ("codex", "plugin", "list")),
                StageSpec(
                    "load",
                    blocked_reason=(
                        "Nothing was placed, so there is nothing to load. Blocked on the absent "
                        "adapter rather than on any package defect."
                    ),
                ),
                StageSpec(
                    "invocation",
                    blocked_reason=(
                        "No client-resolved path exists, because placement produced none. A "
                        "stage that did not run through the client is recorded blocked rather "
                        "than borrowed from another client's result."
                    ),
                ),
            ),
        ),
        ClientPlan(
            "Cursor Agent",
            binary="cursor-agent",
            home=REAL_HOME,
            quirk=(
                "Must run against the real authenticated home. An isolated home strips "
                "authentication and measures an unauthenticated first-run client, which a "
                "superseded matrix published as a package failure. Placement is session-scoped "
                "through the local-plugin flag, so no stage writes client state."
            ),
            stages=(
                StageSpec(
                    "placement",
                    (
                        "cursor-agent", "--plugin-dir", PACKAGE, "--mode", "ask", "--trust",
                        "-p", "--output-format", "text", CURSOR_DISCOVERY_PROBE,
                    ),
                ),
                StageSpec(
                    "discovery",
                    (
                        "cursor-agent", "--plugin-dir", PACKAGE, "--mode", "ask", "--trust",
                        "-p", "--output-format", "text", CURSOR_DISCOVERY_PROBE,
                    ),
                ),
                StageSpec(
                    "load",
                    (
                        "cursor-agent", "--plugin-dir", PACKAGE, "--mode", "ask", "--trust",
                        "-p", "--output-format", "text", CURSOR_LOAD_PROBE,
                    ),
                ),
                StageSpec("invocation", from_package=True),
            ),
        ),
        ClientPlan(
            "Qwen",
            binary="qwen",
            invocation_root=f"{CLIENT_HOME}/.qwen/extensions/{PLUGIN_NAME}",
            quirk=(
                "The installer asks for confirmation on standard input; with no answer it "
                "lists the skills and exits without installing. It copies rather than links, "
                "and adds one bookkeeping file of its own to the extension directory."
            ),
            stages=(
                StageSpec(
                    "placement",
                    ("qwen", "extensions", "install", PACKAGE),
                    stdin="y\n",
                    writes_client_state=True,
                ),
                StageSpec("discovery", ("qwen", "extensions", "list")),
                StageSpec("load", ("qwen", "extensions", "list")),
                StageSpec("invocation", from_package=True),
            ),
        ),
        ClientPlan(
            "Grok",
            binary="grok",
            invocation_root=f"{CLIENT_HOME}/.grok/installed-plugins/{PLUGIN_ID}",
            environment={"GROK_AUTO_TRUST_REAL_BIN": ""},
            quirk=(
                "The launcher on PATH is an auto-trust wrapper that resolves its real binary "
                "through the client home, which an isolated home does not contain; without "
                "GROK_AUTO_TRUST_REAL_BIN, the wrapper's own documented override, it "
                "exits before reaching the client. "
                "'plugin details' takes the plugin name, not the generated install id."
            ),
            stages=(
                StageSpec(
                    "placement",
                    ("grok", "plugin", "install", PACKAGE, "--trust"),
                    writes_client_state=True,
                    capture=(PLUGIN_ID, r"\b([A-Za-z0-9_.-]+-[0-9a-f]{8})\b"),
                ),
                StageSpec("discovery", ("grok", "plugin", "list")),
                StageSpec("load", ("grok", "plugin", "details", PLUGIN_NAME)),
                StageSpec("invocation", from_package=True),
            ),
        ),
        ClientPlan(
            "OpenCode",
            binary="opencode",
            invocation_root=f"{CLIENT_HOME}/.agents/skills",
            skill_scoped=True,
            quirk=(
                "Its own configuration documents an auto-loaded external skill directory and "
                "offers no install command for it, so placement is a copy into that directory. "
                "'debug skill' returns each skill's full parsed body, which is load proven "
                "rather than inferred."
            ),
            stages=(
                StageSpec(
                    "placement",
                    ("cp", "-R", SKILL, f"{CLIENT_HOME}/.agents/skills/"),
                    per_skill=True,
                    writes_client_state=True,
                ),
                StageSpec("discovery", ("opencode", "debug", "skill")),
                StageSpec("load", ("opencode", "debug", "skill")),
                StageSpec("invocation", from_package=True),
            ),
        ),
        ClientPlan(
            "Gemini CLI",
            binary="gemini",
            invocation_root=f"{CLIENT_HOME}/.gemini/skills",
            skill_scoped=True,
            quirk=(
                "'skills link' prompts on standard input and hangs rather than declining when "
                "stdin is closed, so the confirmation is supplied explicitly and the stage "
                "carries a deadline. Session injection is not observable without credentials, "
                "so what load confirms is definition load."
            ),
            stages=(
                StageSpec(
                    "placement",
                    ("gemini", "skills", "link", SKILL),
                    per_skill=True,
                    stdin="y\n",
                    writes_client_state=True,
                ),
                StageSpec("discovery", ("gemini", "skills", "list", "--all")),
                StageSpec("load", ("gemini", "skills", "list", "--all")),
                StageSpec("invocation", from_package=True),
            ),
        ),
        ClientPlan(
            "Muse",
            binary="muse",
            invocation_root=f"{CLIENT_HOME}/.config/muse/skills",
            skill_scoped=True,
            quirk=(
                "Refuses the package root as an installable unit, so the skill units install "
                "individually. '--force' is required on the JSON install for it to report a "
                "content digest once placement has already installed the unit."
            ),
            stages=(
                StageSpec(
                    "placement",
                    ("muse", "skills", "install", SKILL, "--scope", "user"),
                    per_skill=True,
                    writes_client_state=True,
                ),
                StageSpec("discovery", ("muse", "skills", "list", "--source", "user")),
                StageSpec(
                    "load",
                    ("muse", "skills", "install", SKILL, "--scope", "user", "--force", "--json"),
                    per_skill=True,
                    writes_client_state=True,
                ),
                StageSpec("invocation", from_package=True),
            ),
        ),
        ClientPlan(
            "Agy",
            binary="agy",
            invocation_root=f"{CLIENT_HOME}/.gemini/config/plugins/{PLUGIN_NAME}",
            environment={"AGY_AUTO_TRUST_REAL_BIN": ""},
            quirk=(
                "Same auto-trust wrapper arrangement as Grok, and the same override, "
                "AGY_AUTO_TRUST_REAL_BIN, for the same reason. It re-validates its own "
                "installed copy, which is what makes its "
                "load stage independent of its placement stage."
            ),
            stages=(
                StageSpec(
                    "placement",
                    ("agy", "plugin", "install", PACKAGE),
                    writes_client_state=True,
                ),
                StageSpec("discovery", ("agy", "plugin", "list")),
                StageSpec(
                    "load",
                    (
                        "agy", "plugin", "validate",
                        f"{CLIENT_HOME}/.gemini/config/plugins/{PLUGIN_NAME}",
                    ),
                ),
                StageSpec("invocation", from_package=True),
            ),
        ),
        ClientPlan(
            "Hermes",
            binary="hermes",
            invocation_root=f"{CLIENT_HOME}/.hermes/skills",
            skill_scoped=True,
            quirk=(
                "Isolated home only, and the live skills directory is counted before and after "
                "to prove it was not written to. Its install subcommand takes a remote "
                "identifier or an HTTP URL rather than a local path, so placement is a copy "
                "into the profile skills directory. 'prompt-size --json' resolves the skills "
                "into a composed prompt offline, which proves load without credentials."
            ),
            stages=(
                StageSpec(
                    "placement",
                    ("cp", "-R", SKILL, f"{CLIENT_HOME}/.hermes/skills/"),
                    per_skill=True,
                    writes_client_state=True,
                ),
                StageSpec("discovery", ("hermes", "skills", "list")),
                StageSpec("load", ("hermes", "prompt-size", "--json")),
                StageSpec("invocation", from_package=True),
            ),
        ),
    )


CLIENT_PLANS = _client_plans()

#: Clients that may never run against the operator's own home, whatever the
#: command line says. Hermes composes prompts from the live profile, so a run
#: against the real home is both a false measurement and a live mutation.
ISOLATED_ONLY = frozenset({"Hermes"})


def plan_for(name: str) -> ClientPlan:
    for plan in CLIENT_PLANS:
        if plan.name == name:
            return plan
    raise AssessmentError(f"{name!r} is not one of the assessed clients")


# --- environment --------------------------------------------------------------


def credential_variables(environ: dict[str, str], config: PortConfig) -> list[str]:
    """Every variable in `environ` the package's own credential prefixes claim."""
    prefixes = config.assessment.credential_prefixes
    if not prefixes:
        return []
    return sorted(name for name in environ if name.startswith(tuple(prefixes)))


def build_environment(
    config: PortConfig,
    *,
    home: Path | None,
    extra: dict[str, str] | None = None,
    base: dict[str, str] | None = None,
) -> dict[str, str]:
    """The environment one stage runs in.

    Two things happen here and nowhere else. Every variable the package declares
    as credential-shaped is removed, so no stage can be satisfied by a
    credential that happened to be exported in the operator's shell. And when a
    scratch home is supplied, the variables that decide where a client keeps its
    state are pointed into it -- `HOME` alone is not enough, because a client
    reading `XDG_CONFIG_HOME` would otherwise still write to the real one.
    """
    environment = dict(os.environ if base is None else base)
    for name in credential_variables(environment, config):
        environment.pop(name)
    if home is not None:
        environment["HOME"] = str(home)
        environment["XDG_CONFIG_HOME"] = str(home / ".config")
        environment["XDG_DATA_HOME"] = str(home / ".local" / "share")
        environment["XDG_STATE_HOME"] = str(home / ".local" / "state")
        environment["XDG_CACHE_HOME"] = str(home / ".cache")
    for key, value in (extra or {}).items():
        environment[key] = value
    return environment


# --- safety -------------------------------------------------------------------


def refuse_unsafe_argv(argv: tuple[str, ...], config: PortConfig) -> None:
    """Refuse an argv that confirms a write or names a mutating operation.

    The predicate is `check_compatibility_matrix.command_safety_problems`, the
    same one the matrix validator applies to a recorded command. Sharing it is
    the point: a rule enforced before the fact by one copy and after the fact by
    another is a rule that can be satisfied by neither when the two disagree.
    """
    problems = ccm.command_safety_problems(" ".join(argv), config)
    if problems:
        raise AssessmentError(
            "refusing to run a stage whose command is not read-only: " + "; ".join(problems)
        )


def refuse_unsafe_home(plan: ClientPlan, spec: StageSpec, home_kind: str) -> None:
    """Refuse a stage that would write client state into the operator's own home."""
    if home_kind != REAL_HOME:
        return
    if plan.name in ISOLATED_ONLY:
        raise AssessmentError(
            f"{plan.name}: is assessed under an isolated home only; running it against the "
            "operator's home would both mis-measure it and write to live configuration"
        )
    if spec.writes_client_state:
        raise AssessmentError(
            f"{plan.name}/{spec.stage}: writes client state and would do so in the operator's "
            "own home. A stage that installs, links, or copies runs under a scratch home or "
            "not at all"
        )


# --- running a stage ----------------------------------------------------------


class StageOutcome:
    """What one stage did, in the vocabulary the matrix record uses."""

    __slots__ = ("stage", "result", "command", "evidence", "reason", "returncode", "captured")

    def __init__(
        self,
        stage: str,
        result: str,
        *,
        command: str = "",
        evidence: str = "",
        reason: str = "",
        returncode: int | None = None,
        captured: dict[str, str] | None = None,
    ) -> None:
        self.stage = stage
        self.result = result
        self.command = command
        self.evidence = evidence
        self.reason = reason
        self.returncode = returncode
        self.captured = captured or {}

    def record(self) -> dict[str, Any]:
        entry: dict[str, Any] = {"result": self.result}
        if self.command:
            entry["command"] = self.command
        if self.result == EXECUTED:
            entry["evidence"] = self.evidence
        else:
            entry["reason"] = self.reason
        return entry


def substitute(argv: tuple[str, ...], values: dict[str, str]) -> tuple[str, ...]:
    resolved = []
    for item in argv:
        for placeholder, value in values.items():
            item = item.replace(placeholder, value)
        resolved.append(item)
    return tuple(resolved)


def redact(text: str, values: dict[str, str]) -> str:
    """Put the placeholders back, longest concrete value first.

    Longest first matters: a scratch home is a prefix of the package copy inside
    it, and replacing the shorter one first would leave half a real path in a
    public document.
    """
    for placeholder, value in sorted(values.items(), key=lambda item: -len(item[1])):
        if value:
            text = text.replace(value, placeholder)
    return text


def stage_argvs(
    config: PortConfig,
    plan: ClientPlan,
    spec: StageSpec,
    values: dict[str, str],
) -> tuple[tuple[str, ...], ...]:
    """Every process one stage runs, in order.

    Most stages are one command. Two shapes are not, and both are shapes where
    running only the first would produce a green result from half an
    observation:

    * a **per-skill** stage runs once per skill unit, because a client that
      installs units rather than packages has not been assessed until every unit
      it was given went in;
    * the **invocation** stage runs once per entrypoint, because the pilot
      shipped a package whose two clients both failed at import and checking one
      of them would have called that package working.
    """
    if spec.from_package:
        return invocation_argv(config, plan, values[PYTHON])
    if spec.per_skill:
        return tuple(
            substitute(spec.argv, {**values, SKILL: f"{values[PACKAGE]}/{unit}"})
            for unit in config.assessment.skill_units
        )
    return (substitute(spec.argv, values),)


def run_stage(
    plan: ClientPlan,
    spec: StageSpec,
    config: PortConfig,
    values: dict[str, str],
    environment: dict[str, str],
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> StageOutcome:
    """Execute one stage and classify the result honestly.

    The three-way classification is the whole point, so it is spelled out:

    * **blocked** -- the stage did not run to completion, and the reason is
      named. The client is not installed; the stage is blocked in advance by the
      client's own design; the deadline expired. A blocked stage is never
      dressed up as a satisfied one.
    * **executed** -- every process in the stage ran to completion. *Any* exit
      status counts, including a refusal: a client that declines the package
      with a specific, actionable message has told us something true about its
      compatibility, and recording that as "blocked" would lose the finding. The
      exit statuses are recorded either way.
    * **not-applicable** -- reserved for a stage that cannot apply to a client at
      all. No current plan uses it; it exists because the schema admits it and a
      future client may need it.

    A stage of several processes is blocked if *any* of them is, because a stage
    that half ran did not run.
    """
    if spec.blocked_reason is not None:
        return StageOutcome(spec.stage, BLOCKED, reason=spec.blocked_reason)

    argvs = stage_argvs(config, plan, spec, values)
    for argv in argvs:
        refuse_unsafe_argv(argv, config)

    recorded = redact(" ".join(argvs[0]), values)
    statuses: list[int] = []
    captured: dict[str, str] = {}

    for argv in argvs:
        if shutil.which(argv[0], path=environment.get("PATH")) is None:
            return StageOutcome(
                spec.stage,
                BLOCKED,
                command=recorded,
                reason=(
                    f"{argv[0]!r} is not on PATH for this run, so the client could not be "
                    "asked. An absent client is recorded as uncovered, never as a package "
                    "failure."
                ),
            )
        # Either the stage's own confirmation, or nothing at all -- never the
        # operator's terminal. Several of these clients prompt on standard
        # input; a stage that inherited the parent's stdin would sit waiting for
        # a human to type, and would behave differently in a terminal than under
        # a scheduler. Closing it makes an unanswered prompt reach its deadline
        # the same way everywhere.
        streams: dict[str, Any] = (
            {"input": spec.stdin} if spec.stdin is not None else {"stdin": subprocess.DEVNULL}
        )
        try:
            completed = runner(
                list(argv),
                capture_output=True,
                text=True,
                env=environment,
                timeout=spec.timeout,
                **streams,
            )
        except subprocess.TimeoutExpired:
            return StageOutcome(
                spec.stage,
                BLOCKED,
                command=recorded,
                reason=(
                    f"No result within the {spec.timeout:g}s deadline. At least one client "
                    "prompts on standard input and hangs rather than declining when it gets no "
                    "answer, so a stage that does not finish is recorded blocked rather than "
                    "left running."
                ),
            )
        statuses.append(completed.returncode)
        if spec.capture is not None and not captured:
            placeholder, pattern = spec.capture
            match = re.search(pattern, f"{completed.stdout or ''}{completed.stderr or ''}")
            if match is not None:
                captured[placeholder] = match.group(1)

    summary = ", ".join(str(status) for status in statuses)
    return StageOutcome(
        spec.stage,
        EXECUTED,
        command=recorded,
        evidence=(
            spec.evidence
            or f"Ran {len(argvs)} command(s); exit status {summary}. "
            "Replace this line with the observation."
        ),
        returncode=statuses[0],
        captured=captured,
    )


# --- the overall status -------------------------------------------------------


def propose_status(outcomes: dict[str, StageOutcome]) -> str:
    """A proposal, never a verdict.

    Derived only from what the stages did, so it cannot claim more than was
    observed. Three distinctions, in the order they are decided:

    * **failed** -- the package's own entrypoint ran through this client and did
      not succeed. `executed` says a process completed, not that it worked, so
      the exit status is what separates a client that consumed the package from
      one that consumed it and then broke. This is the pilot's own shipped
      defect: both entrypoints raised `ModuleNotFoundError` before parsing an
      argument, and every stage still "executed".
    * **works-through-an-adapter** -- the client could not consume the package
      *and named what it wanted*. An adapter exists; someone has to build it.
    * **unsupported** -- nothing ran at all.

    The accompanying reason is left empty for the operator, and an empty reason
    fails the matrix validator, so no proposal here reaches evidence unread.
    """
    results = {stage: outcome.result for stage, outcome in outcomes.items()}
    invocation = outcomes.get("invocation")
    if (
        invocation is not None
        and invocation.result == EXECUTED
        and invocation.returncode not in (None, 0)
    ):
        return "failed"
    if all(result == EXECUTED for result in results.values()):
        return "works-directly"
    if any(result == EXECUTED for result in results.values()):
        return "works-through-an-adapter"
    return "unsupported"


# --- the run ------------------------------------------------------------------


def stage_home(base: Path, plan: ClientPlan) -> Path:
    home = base / plan.name.replace(" ", "-").lower()
    (home / ".config").mkdir(parents=True, exist_ok=True)
    for relative in (".agents/skills", ".hermes/skills", ".gemini/skills"):
        (home / relative).mkdir(parents=True, exist_ok=True)
    return home


def entrypoint_paths(config: PortConfig, plan: ClientPlan) -> tuple[str, ...]:
    """Where each of the package's entrypoints lands for this client.

    A package-scoped client keeps the package's own layout, so an entrypoint's
    path under the client's root is its path in the package. A skill-scoped
    client installs each *skill unit* rather than the package, so the unit
    directory becomes the top level and everything above it disappears:
    ``skills/unifi-network/scripts/client.py`` resolves at
    ``unifi-network/scripts/client.py`` under that client's skills directory.

    Both forms are derived from the descriptor's own `skill_units`, so a package
    that names its units differently is handled without editing this file.
    """
    entrypoints = config.custody.entrypoint_transforms
    if not entrypoints:
        raise AssessmentError(
            f"{config.name}: declares no entrypoint_transforms, so there is nothing to invoke; "
            "a package with no executable entrypoint needs its invocation stage described "
            "in the descriptor rather than assumed here"
        )
    if not plan.skill_scoped:
        return tuple(f"{plan.invocation_root}/{relative}" for relative in entrypoints)

    resolved: list[str] = []
    for relative in entrypoints:
        for unit in config.assessment.skill_units:
            prefix = f"{unit}/"
            if relative.startswith(prefix):
                name = Path(unit).name
                resolved.append(f"{plan.invocation_root}/{name}/{relative[len(prefix):]}")
                break
        else:
            raise AssessmentError(
                f"{config.name}: entrypoint {relative!r} sits under no declared skill unit, so "
                f"{plan.name}, which installs skill units rather than the package, has no path "
                "to run it from. Name the unit in the descriptor's assessment.skill_units"
            )
    return tuple(resolved)


def invocation_argv(config: PortConfig, plan: ClientPlan, python: str) -> tuple[tuple[str, ...], ...]:
    """One argv per entrypoint, each with the credential-free help action.

    `--help` is answered by the argument parser and exits before any client
    object is constructed, so no host is contacted and no credential is read.
    Every entrypoint is run, not just the first: the pilot shipped a package
    whose two clients both raised `ModuleNotFoundError` at import, and a stage
    that checks one of them would have reported that package as working.
    """
    return tuple((python, path, "--help") for path in entrypoint_paths(config, plan))


def assess(
    config: PortConfig,
    *,
    python: str,
    execute: bool,
    only: tuple[str, ...] = (),
    workspace: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[str, Any]:
    """Run the assessment and return the record, or raise rather than emit a lie."""
    package_root = config.package_directory
    before = ccm.package_fingerprint(package_root)
    name, version = ccm.package_identity(package_root, config.package_manifest)

    base = Path(workspace) if workspace is not None else Path(tempfile.mkdtemp())
    scratch = base / "package"
    if not scratch.exists():
        shutil.copytree(package_root, scratch)

    plans = [plan for plan in CLIENT_PLANS if not only or plan.name in only]
    clients: list[dict[str, Any]] = []

    for plan in plans:
        home = stage_home(base, plan) if plan.home == ISOLATED_HOME else None
        values = {
            PACKAGE: str(scratch),
            PYTHON: python,
            CLIENT_HOME: str(home) if home is not None else str(Path.home()),
            PLUGIN_NAME: config.name,
            PLUGIN_ID: config.name,
        }
        environment = build_environment(
            config,
            home=home,
            extra={
                key: (value or shutil.which(plan.binary) or plan.binary)
                for key, value in plan.environment.items()
            },
        )

        outcomes: dict[str, StageOutcome] = {}
        for spec in sorted(plan.stages, key=lambda item: ccm.STAGES.index(item.stage)):
            # Checked before anything runs, and for every stage rather than only
            # the ones that write: a client's home policy is a property of the
            # run, and discovering it mid-way would already have installed
            # something.
            refuse_unsafe_home(plan, spec, plan.home)
            if not execute:
                if spec.blocked_reason is not None:
                    command = ""
                else:
                    command = redact(" ".join(stage_argvs(config, plan, spec, values)[0]), values)
                outcomes[spec.stage] = StageOutcome(
                    spec.stage,
                    BLOCKED,
                    command=command,
                    reason=(
                        spec.blocked_reason
                        or "Planned only. This run was not started with --execute."
                    ),
                )
                continue
            outcome = run_stage(plan, spec, config, values, environment, runner=runner)
            values.update(outcome.captured)
            outcomes[spec.stage] = outcome

        clients.append(
            {
                "name": plan.name,
                "version": "",
                "stages": {stage: outcomes[stage].record() for stage in ccm.STAGES},
                "status": propose_status(outcomes),
                # Left empty on purpose. The validator refuses a client row with
                # no concrete reason, so a record no one finished reading cannot
                # be committed as evidence.
                "reason": "",
            }
        )

    after = ccm.package_fingerprint(package_root)
    if after != before:
        raise AssessmentError(
            f"the assessed tree moved during the run: {before} -> {after}. Something wrote into "
            f"{config.package_root} while it was being assessed, so every result here describes "
            "a package that no longer exists and none of it may be published"
        )

    return {
        "$schema": "../../schemas/compatibility-matrix.schema.json",
        "schema_version": "1",
        "assessed_on": "",
        "package": {
            "name": name,
            "version": version,
            "file_count": before[0],
            "tree_sha256": before[1],
        },
        "method": {
            "stages": list(ccm.STAGES),
            "isolation": "",
            "credentials": "",
            "network": "",
        },
        "clients": clients,
    }


def describe_plan(config: PortConfig) -> str:
    """The plan, as text, with every stage's argv shown before anything runs."""
    lines = [
        f"Assessment plan for {config.name} ({config.package_root})",
        f"Clients: {len(CLIENT_PLANS)}   Stages per client: {len(ccm.STAGES)}",
        "",
        "Nothing below has run. Pass --execute to run it.",
        "",
    ]
    values = {PACKAGE: PACKAGE, PYTHON: PYTHON, CLIENT_HOME: CLIENT_HOME}
    for plan in CLIENT_PLANS:
        lines.append(f"## {plan.name}  [home: {plan.home}]")
        if plan.quirk:
            lines.append(f"   quirk: {plan.quirk}")
        for stage in ccm.STAGES:
            spec = plan.stage(stage)
            if spec.blocked_reason is not None:
                lines.append(f"   {stage:<11} blocked in advance: {spec.blocked_reason}")
                continue
            argvs = stage_argvs(config, plan, spec, values)
            suffix = []
            if len(argvs) > 1:
                suffix.append(f"{len(argvs)} commands")
            if spec.stdin:
                suffix.append("confirmation on stdin")
            suffix.append(f"deadline {spec.timeout:g}s")
            lines.append(f"   {stage:<11} {' '.join(argvs[0])}   ({', '.join(suffix)})")
            for argv in argvs[1:]:
                lines.append(f"   {'':<11} {' '.join(argv)}")
        lines.append("")
    return "\n".join(lines)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the ten-client compatibility assessment for a portable package."
    )
    parser.add_argument("--package", required=True, help="the package to assess")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="actually run the clients; without it the plan is printed and nothing runs",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="the interpreter the invocation stage uses; name the floor explicitly by path",
    )
    parser.add_argument("--client", action="append", default=[], help="restrict to one client")
    parser.add_argument("--out", help="write the record as JSON to this path")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_argument_parser().parse_args(argv)
    try:
        config = port_config.load(arguments.package)
    except PortConfigError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    if not arguments.execute:
        print(describe_plan(config))
        return 0

    try:
        record = assess(
            config,
            python=arguments.python,
            execute=True,
            only=tuple(arguments.client),
        )
    except (AssessmentError, ccm.MatrixError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    leaks = ccm.check_public_evidence_rules(record)
    if leaks:
        print("ERROR: the record would leak site-identifying values:", file=sys.stderr)
        for leak in leaks:
            print(f"  {leak}", file=sys.stderr)
        return 1

    payload = json.dumps(record, indent=2, ensure_ascii=False) + "\n"
    if arguments.out:
        Path(arguments.out).write_text(payload, encoding="utf-8")
        print(f"wrote {arguments.out}")
    else:
        print(payload)
    print(
        "\nThe record is deliberately incomplete: assessed_on, each client's version and "
        "reason, and the method prose are empty, and check_compatibility_matrix.py refuses "
        "a record whose reasons are blank. Fill them from what you observed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
