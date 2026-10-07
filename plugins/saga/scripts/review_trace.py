#!/usr/bin/env python3
"""Review traces in Langfuse: the trace layout, the visibility rule and the local queue.

Issue 166, card C15. One review run becomes one trace in the "Saga Reviews" project, with an
entry per tool, one for the Jev sweep, one per LLM step, one for the formula and one per
finding. Merge outcomes and plan-review answers attach later as scores on a finding's entry.
Every ID is derived from the records (C1's review run has no run ID), so a later post needs no
lookup and a resend replaces rather than adds.

A post that cannot go waits in ``<home>/.saga/langfuse-queue/``, owner-only, with its reason,
and is sent oldest first once the reason clears. It is never dropped, and nothing here raises
into a review: ``post`` returns a summary, and every caller wraps it besides.

Subcommands: ``post`` (one review run), ``drain``, ``status``, ``probe`` (the project answers)
and ``rounds`` (how often round 2 or 3 found anything new). ``plugins/fleet-core/references/
langfuse.md`` holds the rule; ``references/review-command.md`` describes the posting step.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import bundled_fleet  # noqa: E402
import review_records  # noqa: E402
import review_tools  # noqa: E402

lf = bundled_fleet.load("langfuse_client")

QUEUE_DIRNAME = "langfuse-queue"
CLAIM_STALE_SECONDS = 600
POST_BUDGET_SECONDS = 30.0
EXCERPT_CONTEXT = 5
EXCERPT_MAX_LINES = 60
SECRET_WITHHELD = "[secret line withheld]"
MAX_BODY_BYTES = 2_000_000
SCOPE_NAME = "saga-review"
PROJECT_NAME = "Saga Reviews"
ROUND_VIEW_SCORES = ("round-2-found-new", "round-3-found-new")
METRICS_FROM = "2026-01-01T00:00:00.000Z"

_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_.-]+$")
_REMOTE = re.compile(r"[:/]([A-Za-z0-9][A-Za-z0-9_.-]*)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_STOP = frozenset({lf.UNREACHABLE, lf.TIMEOUT})

Runner = Callable[..., review_tools.ProcessResult]
Item = tuple[str, Any, str | None]


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hex(text: str, size: int) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:size]


def trace_id(identity: Mapping[str, Any]) -> str:
    """32 hex characters of SHA-256 over the canonical identity: an OpenTelemetry trace ID."""
    return _hex(_canonical(dict(identity)), 32)


def review_trace_id(run: Mapping[str, Any], slug: str) -> str:
    return trace_id({
        "subject": "code",
        "repo": slug,
        "base": run.get("base"),
        "head": run.get("head"),
        "card": run.get("card"),
        "round": run.get("round"),
    })


def plan_trace_id(slug: str, card: Any, plan_sha256: str) -> str:
    return trace_id({"subject": "plan", "repo": slug, "card": card, "plan_sha256": plan_sha256})


def span_id(trace: str, key: str) -> str:
    """16 hex characters of SHA-256 over ``<trace>:<key>``: an OpenTelemetry span ID."""
    return _hex(f"{trace}:{key}", 16)


def score_id(trace: str, key: str, name: str) -> str:
    return _hex(f"{trace}:{key}:{name}", 32)


def finding_key(finding_id: str) -> str:
    return f"finding:{finding_id}"


# ---------------------------------------------------------------------------
# Repository facts: slug, visibility and excerpts (read-only git)
# ---------------------------------------------------------------------------


def _git_env() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("GIT_", "SAGA_LANGFUSE_", "LANGFUSE_", "TYPESAFE_"))
    }


def _git(runner: Runner, repo: Path, args: Sequence[str]) -> review_tools.ProcessResult | None:
    try:
        return runner(
            ["git", "-C", str(repo), *args], cwd=repo, env=_git_env(), timeout=30, shell=False,
        )
    except (OSError, ValueError, RuntimeError):
        return None
    except Exception:  # noqa: BLE001 - a timeout or anything else reads as "unknown"
        return None


def _blob(runner: Runner, repo: Path, ref: str, path: str) -> str | None:
    if not _REF.match(ref) or path.startswith("-") or ".." in Path(path).parts:
        return None
    result = _git(runner, repo, ["cat-file", "blob", f"{ref}:{path}"])
    if result is None or result.code != 0:
        return None
    return result.stdout


def repository_slug(repo: Path | None, *, recorded: Any = None, runner: Runner | None = None) -> str:
    """``owner/name``: the run record's value, else the ``origin`` remote's, else ``unknown``.

    Never a local path: C1's ``repo`` field holds the path ``finish`` was given.
    """
    if isinstance(recorded, str) and _SLUG.match(recorded):
        return recorded
    if repo is not None:
        result = _git(runner or review_tools.subprocess_runner, repo, ["remote", "get-url", "origin"])
        if result is not None and result.code == 0:
            match = _REMOTE.search(result.stdout.strip())
            if match:
                return f"{match.group(1)}/{match.group(2)}"
    return "unknown"


def visibility(repo: Path | None, ref: str, *, runner: Runner | None = None) -> str | None:
    """The profile's ``visibility`` at ``ref``: ``public``, ``private``, or ``None`` (private).

    Read at the base commit, never the head or the working tree: the change under review is
    untrusted and could otherwise mark its own repository public.
    """
    if repo is None or not ref:
        return None
    text = _blob(runner or review_tools.subprocess_runner, repo, ref, ".saga-profile.json")
    if text is None:
        return None
    try:
        profile = json.loads(text)
    except json.JSONDecodeError:
        return None
    value = profile.get("visibility") if isinstance(profile, Mapping) else None
    return value if value in lf.VISIBILITIES else None


def plan_visibility(repo: Path, *, runner: Runner | None = None) -> str | None:
    """Visibility at the merge base of ``HEAD`` and the default branch, never at ``HEAD``."""
    process = runner or review_tools.subprocess_runner
    default = "main"
    result = _git(process, repo, ["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"])
    if result is not None and result.code == 0 and result.stdout.strip().startswith("refs/remotes/"):
        default = result.stdout.strip()[len("refs/remotes/"):]
    if not _REF.match(default):
        return None
    base = _git(process, repo, ["merge-base", "HEAD", default])
    if base is None or base.code != 0 or not base.stdout.strip():
        return None
    return visibility(repo, base.stdout.strip(), runner=process)


def secret_ranges(findings: Iterable[Any]) -> dict[str, list[tuple[int, int]]]:
    """Each secret-scanner finding's line range, by file."""
    ranges: dict[str, list[tuple[int, int]]] = {}
    for finding in findings:
        if not isinstance(finding, Mapping) or _row(finding) != review_records.SECRET_ROW:
            continue
        location = finding.get("location") or {}
        lines = location.get("lines") if isinstance(location, Mapping) else None
        if isinstance(lines, Mapping) and isinstance(location.get("file"), str):
            start, end = _int(lines.get("start")), _int(lines.get("end"))
            if start and end:
                ranges.setdefault(location["file"], []).append((start, max(start, end)))
    return ranges


def excerpt(
    repo: Path | None,
    head: str,
    finding: Mapping[str, Any],
    secrets: Mapping[str, list[tuple[int, int]]],
    *,
    runner: Runner | None = None,
) -> str | None:
    """The finding's lines plus 5 each side, at most 60, at the head; ``None`` when not sendable.

    A secret-scanner finding has none. Any line a secret finding covers is withheld before
    redaction runs, so a scanner's match cannot ride along on a neighbouring finding.
    """
    if repo is None or _row(finding) == review_records.SECRET_ROW:
        return None
    location = finding.get("location")
    if not isinstance(location, Mapping) or location.get("scope") != "lines":
        return None
    path, lines = location.get("file"), location.get("lines")
    if not isinstance(path, str) or not isinstance(lines, Mapping):
        return None
    start, end = _int(lines.get("start")), _int(lines.get("end"))
    if not start or not end:
        return None
    text = _blob(runner or review_tools.subprocess_runner, repo, head, path)
    if text is None:
        return None
    source = text.splitlines()
    first = max(1, start - EXCERPT_CONTEXT)
    last = min(len(source), max(start, end) + EXCERPT_CONTEXT, first + EXCERPT_MAX_LINES - 1)
    withheld = secrets.get(path, [])
    shown = []
    for number in range(first, last + 1):
        line = source[number - 1]
        if any(low <= number <= high for low, high in withheld):
            line = SECRET_WITHHELD
        shown.append(line)
    return "\n".join(shown)


# ---------------------------------------------------------------------------
# The trace
# ---------------------------------------------------------------------------


def _row(finding: Mapping[str, Any]) -> str:
    rule = finding.get("rule")
    return str(rule.get("row") or "") if isinstance(rule, Mapping) else ""


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return 0.0
    return float(value)


def _attr(key: str, value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    if isinstance(value, float):
        return {"key": key, "value": {"doubleValue": value}}
    if not isinstance(value, str):
        value = _canonical(value)
    return {"key": key, "value": {"stringValue": value}}


def _span(
    trace: str, span: str, parent: str | None, name: str, start: int, end: int,
    attributes: Mapping[str, Any],
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "traceId": trace,
        "spanId": span,
        "name": name,
        "kind": 1,
        "startTimeUnixNano": str(start),
        "endTimeUnixNano": str(max(start, end)),
        "attributes": [_attr(key, value) for key, value in attributes.items() if value is not None],
    }
    if parent:
        body["parentSpanId"] = parent
    return body


def _otel_bodies(spans: Sequence[dict[str, Any]], version: str) -> list[dict[str, Any]]:
    """One OTLP JSON body, or several of whole spans when one would pass 2 MB."""
    def wrap(chunk: list[dict[str, Any]]) -> dict[str, Any]:
        return {"resourceSpans": [{
            "resource": {"attributes": [_attr("service.name", "saga")]},
            "scopeSpans": [{"scope": {"name": SCOPE_NAME, "version": version}, "spans": chunk}],
        }]}

    bodies: list[dict[str, Any]] = []
    chunk: list[dict[str, Any]] = []
    size = 0
    for span in spans:
        weight = len(_canonical(span))
        if chunk and size + weight > MAX_BODY_BYTES:
            bodies.append(wrap(chunk))
            chunk, size = [], 0
        chunk.append(span)
        size += weight
    if chunk:
        bodies.append(wrap(chunk))
    return bodies


def _score(
    trace: str, key: str, name: str, value: Any, data_type: str, *, observation: str | None = None,
    comment: str | None = None, metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": score_id(trace, key, name),
        "traceId": trace,
        "name": name,
        "value": value,
        "dataType": data_type,
    }
    if observation:
        body["observationId"] = observation
    if comment:
        body["comment"] = comment
    if metadata:
        body["metadata"] = dict(metadata)
    return body


def _usage(result: Mapping[str, Any]) -> tuple[dict[str, int], float, float]:
    usage = result.get("usage") if isinstance(result.get("usage"), Mapping) else {}

    def count(name: str) -> int:
        value = usage.get(name)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    details = {
        "input": count("input_tokens"),
        "output": count("output_tokens"),
        "cache_read": count("cache_read_input_tokens"),
        "cache_write": count("cache_creation_input_tokens"),
    }
    cost = _number(usage.get("cost_usd", result.get("cost_usd")))
    seconds = _number(usage.get("seconds", result.get("seconds")))
    return details, cost, seconds


def _model(result: Mapping[str, Any]) -> str:
    model = result.get("model")
    if isinstance(model, Mapping):
        resolved = model.get("resolved")
        if isinstance(resolved, list) and resolved and isinstance(resolved[0], str):
            return resolved[0]
        model = model.get("requested")
    return model if isinstance(model, str) else "unknown"


def _raw_outputs(run: Mapping[str, Any]) -> tuple[list[dict[str, str]], int]:
    """Each stored raw output as ``{tool, sha256}`` only; the local path never leaves."""
    kept: list[dict[str, str]] = []
    withheld = 0
    for entry in run.get("raw_outputs") or []:
        sha = entry.get("sha256") if isinstance(entry, Mapping) else None
        if isinstance(sha, str) and _SHA256.match(sha):
            kept.append({"tool": str(entry.get("tool") or "tool"), "sha256": sha})
        else:
            withheld += 1
    return kept, withheld


def _tool_of(finding: Mapping[str, Any]) -> str | None:
    source = finding.get("source")
    if isinstance(source, Mapping) and source.get("kind") == "tool":
        return str(source.get("name") or "tool")
    return None


def _sendable_finding(finding: Mapping[str, Any]) -> dict[str, Any]:
    sent = dict(finding)
    if _row(finding) == review_records.SECRET_ROW:
        for name in review_records.SECRET_FIELDS:
            sent.pop(name, None)
        proof = sent.get("proof")
        if isinstance(proof, Mapping):
            sent["proof"] = {key: value for key, value in proof.items() if key != "output"}
    return sent


def round_changes(run: Mapping[str, Any], earlier: Sequence[Mapping[str, Any]]) -> dict[str, int] | None:
    """What this round added over the earlier rounds of the same card, or ``None`` for round 1."""
    current_round = run.get("round")
    previous = [
        entry for entry in earlier
        if entry.get("card") == run.get("card")
        and isinstance(entry.get("round"), int) and isinstance(current_round, int)
        and entry["round"] < current_round
    ]
    if not previous:
        return None
    seen = {f.get("id") for entry in previous for f in entry.get("findings") or [] if isinstance(f, Mapping)}
    latest = max(previous, key=lambda entry: entry["round"])
    last_ids = {f.get("id") for f in latest.get("findings") or [] if isinstance(f, Mapping)}
    findings = [f for f in run.get("findings") or [] if isinstance(f, Mapping)]
    now = {f.get("id") for f in findings}
    new = [f for f in findings if f.get("id") not in seen]
    return {
        "new_findings": len(new),
        "new_blocking": sum(1 for f in new if f.get("severity") == "blocks"),
        "cleared": len(last_ids - now),
    }


def build_review_trace(
    run: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
    *,
    slug: str,
    visibility: str | None,
    earlier_runs: Sequence[Mapping[str, Any]] | None,
    excerpts: Mapping[str, str | None] | None = None,
    now_ns: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The OpenTelemetry bodies and the score bodies for one review run.

    ``earlier_runs`` is ``None`` when there is no run record: the round scores other than
    ``round`` are left out and the trace says ``rounds: "no-store"``.
    """
    end = now_ns if now_ns is not None else time.time_ns()
    trace = review_trace_id(run, slug)
    root = span_id(trace, "review-run")
    usage = run.get("usage") if isinstance(run.get("usage"), Mapping) else {}
    start = end - int(_number(usage.get("seconds")) * 1e9)
    raw, withheld = _raw_outputs(run)
    findings = [f for f in run.get("findings") or [] if isinstance(f, Mapping)]
    tool_versions = dict(run.get("tool_versions") or {})
    saga_version = str(run.get("saga_version") or "not-recorded")
    spans = [_span(trace, root, None, "review-run", start, end, {
        "langfuse.trace.name": "review-run",
        "langfuse.observation.type": "span",
        "langfuse.version": saga_version,
        "langfuse.trace.metadata.repo": slug,
        "langfuse.trace.metadata.base": str(run.get("base") or ""),
        "langfuse.trace.metadata.head": str(run.get("head") or ""),
        "langfuse.trace.metadata.card": run.get("card"),
        "langfuse.trace.metadata.round": run.get("round"),
        "langfuse.trace.metadata.saga_version": saga_version,
        "langfuse.trace.metadata.tool_versions": tool_versions,
        "langfuse.trace.metadata.visibility": visibility or "unrecorded",
        "langfuse.trace.metadata.raw_outputs_withheld": withheld,
        "langfuse.trace.metadata.rounds": "store" if earlier_runs is not None else "no-store",
        "langfuse.trace.metadata.usage": usage,
        "langfuse.trace.output": {
            "lens_grades": run.get("lens_grades") or [],
            "merge": run.get("merge"),
            "degraded_inputs": run.get("degraded_inputs") or [],
        },
    })]
    tools = sorted(set(tool_versions) | {t for f in findings if (t := _tool_of(f))}
                   | {entry["tool"] for entry in raw})
    for tool in tools:
        mine = [f for f in findings if _tool_of(f) == tool]
        prints = sorted({entry["sha256"] for entry in raw if entry["tool"] == tool} | {
            str(f["proof"]["raw_output"]) for f in mine
            if isinstance(f.get("proof"), Mapping)
            and isinstance(f["proof"].get("raw_output"), str) and _SHA256.match(f["proof"]["raw_output"])
        })
        degraded = [
            entry for entry in run.get("degraded_inputs") or []
            if isinstance(entry, Mapping) and entry.get("tool") == tool
        ]
        spans.append(_span(trace, span_id(trace, f"tool:{tool}"), root, f"tool:{tool}", start, end, {
            "langfuse.observation.type": "tool",
            "langfuse.observation.metadata.version": tool_versions.get(tool, "not-recorded"),
            "langfuse.observation.metadata.raw_outputs": prints,
            "langfuse.observation.output": {
                "findings": [f.get("id") for f in mine],
                "degraded": degraded,
            },
        }))
    items = [item for item in run.get("where_to_look") or [] if isinstance(item, Mapping)]
    models = sorted({
        str(item["classifier"].get("model")) for item in items
        if isinstance(item.get("classifier"), Mapping) and item["classifier"].get("model")
    })
    spans.append(_span(trace, span_id(trace, "sweep"), root, "jev-sweep", start, end, {
        "langfuse.observation.type": "evaluator",
        "langfuse.observation.metadata.models": models,
        "langfuse.observation.output": items,
    }))
    reviewers = [r for r in run.get("reviewers") or [] if isinstance(r, Mapping)]
    steps: list[Mapping[str, Any]] = list(results) if results else reviewers
    for index, step in enumerate(steps):
        recorded = reviewers[index] if index < len(reviewers) else {}
        role = str(step.get("role") or recorded.get("role") or "reviewer")
        details, cost, seconds = _usage(step)
        configuration = step.get("configuration")
        fingerprint = (
            configuration.get("fingerprint") if isinstance(configuration, Mapping)
            else step.get("configuration_sha256")
        )
        key = f"llm:{index}:{role}"
        spans.append(_span(trace, span_id(trace, key), root, f"llm:{role}",
                           end - int(seconds * 1e9), end, {
            "langfuse.observation.type": "generation",
            "langfuse.observation.model.name": _model(step),
            "langfuse.observation.usage_details": details,
            "langfuse.observation.cost_details": {"total": cost},
            "langfuse.observation.metadata.vendor": str(step.get("vendor") or "unknown"),
            "langfuse.observation.metadata.role": role,
            "langfuse.observation.metadata.effort": step.get("effort"),
            "langfuse.observation.metadata.configuration_fingerprint": fingerprint,
            "langfuse.observation.metadata.prompt_sha256": step.get("prompt_sha256"),
            "langfuse.observation.metadata.seconds": seconds,
        }))
    spans.append(_span(trace, span_id(trace, "formula"), root, "formula", start, end, {
        "langfuse.observation.type": "chain",
        "langfuse.observation.input": {
            "measurements": run.get("measurements") or [],
            "may_block": run.get("may_block") or {},
            "builder_records": run.get("builder_records") or [],
        },
        "langfuse.observation.output": {
            "lens_grades": run.get("lens_grades") or [],
            "degraded_inputs": run.get("degraded_inputs") or [],
            "merge": run.get("merge"),
        },
    }))
    excerpts = excerpts or {}
    for finding in findings:
        identity = str(finding.get("id") or "")
        attributes: dict[str, Any] = {
            "langfuse.observation.type": "event",
            "langfuse.observation.metadata.finding_id": identity,
            "langfuse.observation.metadata.lens": finding.get("lens"),
            "langfuse.observation.metadata.row": _row(finding),
            "langfuse.observation.metadata.severity": finding.get("severity"),
            "langfuse.observation.input": _sendable_finding(finding),
        }
        text = excerpts.get(identity)
        if text is not None and _row(finding) != review_records.SECRET_ROW:
            attributes["langfuse.observation.output"] = {"excerpt": text}
        spans.append(_span(trace, span_id(trace, finding_key(identity)), root, "finding", end, end,
                           attributes))
    scores = [_score(trace, "review-run", "round", run.get("round"), "NUMERIC")]
    changes = round_changes(run, earlier_runs or []) if earlier_runs is not None else None
    current = run.get("round")
    if changes is not None:
        if current in (2, 3):
            scores.append(_score(trace, "review-run", f"round-{current}-found-new",
                                 1 if changes["new_findings"] else 0, "BOOLEAN"))
        scores.append(_score(trace, "review-run", "round-new-findings", changes["new_findings"], "NUMERIC"))
        scores.append(_score(trace, "review-run", "round-new-blocking", changes["new_blocking"], "NUMERIC"))
        scores.append(_score(trace, "review-run", "round-cleared", changes["cleared"], "NUMERIC"))
    return _otel_bodies(spans, saga_version), scores


def outcome_scores(record: Mapping[str, Any], slug: str) -> tuple[list[tuple[Mapping[str, Any], dict[str, Any]]], int]:
    """Each finding's ``merge-outcome`` score on its entry in the latest run that holds it.

    Returns ``(run, score)`` pairs and the number of findings whose outcome is not recorded.
    """
    runs = [
        entry for entry in record.get("review_cycles") or []
        if isinstance(entry, Mapping) and entry.get("kind") == "review_run"
        and entry.get("loop") == review_records.STORED_LOOP
    ]
    latest: dict[str, tuple[int, int, Mapping[str, Any], Mapping[str, Any]]] = {}
    for position, run in enumerate(runs):
        level = run["round"] if isinstance(run.get("round"), int) else 0
        for finding in run.get("findings") or []:
            if not isinstance(finding, Mapping) or not finding.get("id"):
                continue
            key = (level, position)
            held = latest.get(finding["id"])
            if held is None or key >= held[:2]:
                latest[str(finding["id"])] = (level, position, run, finding)
    pairs: list[tuple[Mapping[str, Any], dict[str, Any]]] = []
    unrecorded = 0
    for identity in sorted(latest):
        _, _, run, finding = latest[identity]
        outcome = finding.get("merge_outcome")
        if not isinstance(outcome, Mapping) or outcome.get("outcome") not in review_records.formula.MERGE_OUTCOMES:
            unrecorded += 1
            continue
        trace = review_trace_id(run, slug)
        value = str(outcome["outcome"])
        comment = None
        metadata = None
        if value == "dismissed":
            comment = str(outcome.get("reason") or "")
        elif value == "filed" and isinstance(outcome.get("issue"), int):
            comment = f"issue #{outcome['issue']}"
            metadata = {"issue": outcome["issue"]}
        pairs.append((run, _score(
            trace, finding_key(identity), "merge-outcome", value, "CATEGORICAL",
            observation=span_id(trace, finding_key(identity)), comment=comment, metadata=metadata,
        )))
    return pairs, unrecorded


def build_plan_trace(
    entry: Mapping[str, Any], *, slug: str, card: Any, visibility: str | None, now_ns: int | None = None,
) -> list[dict[str, Any]]:
    """One plan review: a root ``plan-review`` span and one entry per finding."""
    end = now_ns if now_ns is not None else time.time_ns()
    sha = str(entry.get("plan_sha256") or "")
    trace = plan_trace_id(slug, card, sha)
    root = span_id(trace, "plan-review")
    spans = [_span(trace, root, None, "plan-review", end, end, {
        "langfuse.trace.name": "plan-review",
        "langfuse.observation.type": "span",
        "langfuse.trace.metadata.repo": slug,
        "langfuse.trace.metadata.card": card,
        "langfuse.trace.metadata.plan": Path(str(entry.get("plan_path") or "")).name,
        "langfuse.trace.metadata.plan_sha256": sha,
        "langfuse.trace.metadata.reviewed_revision": str(entry.get("reviewed_revision") or ""),
        "langfuse.trace.metadata.visibility": visibility or "unrecorded",
    })]
    for finding in entry.get("findings") or []:
        if not isinstance(finding, Mapping):
            continue
        identity = str(finding.get("id") or "")
        spans.append(_span(trace, span_id(trace, finding_key(identity)), root, "finding", end, end, {
            "langfuse.observation.type": "event",
            "langfuse.observation.metadata.finding_id": identity,
            "langfuse.observation.metadata.lens": finding.get("lens"),
            "langfuse.observation.input": _sendable_finding(finding),
        }))
    return _otel_bodies(spans, "plan-review")


def plan_answer_scores(record: Mapping[str, Any], finding_id: str, slug: str) -> list[dict[str, Any]]:
    """A ``plan-answer`` score on the finding's entry in every plan review that answers it."""
    scores = []
    for entry in record.get("review_cycles") or []:
        if not isinstance(entry, Mapping) or entry.get("loop") != "plan_review":
            continue
        answer = (entry.get("answers") or {}).get(finding_id)
        if not isinstance(answer, Mapping):
            continue
        trace = plan_trace_id(slug, record.get("issue"), str(entry.get("plan_sha256") or ""))
        comment = answer.get("section") if answer.get("verdict") == "fixed" else answer.get("reason")
        scores.append(_score(
            trace, finding_key(finding_id), "plan-answer", str(answer.get("verdict")), "CATEGORICAL",
            observation=span_id(trace, finding_key(finding_id)), comment=str(comment or "") or None,
        ))
    return scores


# ---------------------------------------------------------------------------
# The queue
# ---------------------------------------------------------------------------


def queue_dir(home: Path) -> Path:
    """``<home>/.saga/langfuse-queue``, created mode 0700, beside C4a's ``review-output``."""
    Path(home).mkdir(mode=0o700, parents=True, exist_ok=True)
    path = review_tools._saga(Path(home)) / QUEUE_DIRNAME
    existed = path.exists()
    path.mkdir(mode=0o700, exist_ok=True)
    if not existed:
        path.chmod(0o700)
    return path


def _write_fd(fd: int, content: str) -> None:
    try:
        os.fchmod(fd, 0o600)
        data = memoryview(content.encode("utf-8"))
        while data:
            written = os.write(fd, data)
            data = data[written:]
    finally:
        os.close(fd)


def _write_0600(path: Path, content: str) -> None:
    _write_fd(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600),
              content)


def _enqueue(home: Path, prepared: Any, visibility: str | None, reason: str) -> Path:
    directory = queue_dir(home)
    text = _canonical(prepared.body)
    stamp = time.time_ns()
    while True:
        target = directory / f"{stamp:020d}-{_hex(text, 16)}.json"
        if not target.exists():
            break
        stamp += 1
    _write_0600(target, json.dumps({
        "kind": prepared.kind,
        "visibility": visibility,
        "reason": reason,
        "attempts": 1,
        "first_queued": datetime.now(UTC).isoformat(timespec="seconds"),
        "body": prepared.body,
    }))
    return target


def _requeue(claimed: Path, path: Path, content: str) -> None:
    """Put a claimed post back under its own name with its new reason and attempt count.

    The update goes to a new owner-only file first, and the claimed copy is removed only once the
    update sits under the original name. A failed write puts the old copy back unchanged; a
    failed put-back leaves the claim, which the next post takes back once it is stale.
    """
    fresh: Path | None = None
    try:
        fd, name = tempfile.mkstemp(dir=path.parent, prefix=f"{path.stem}.", suffix=".rewrite")
        fresh = Path(name)
        _write_fd(fd, content)
        os.replace(fresh, path)
    except OSError:
        try:
            if fresh is not None:
                fresh.unlink(missing_ok=True)
            claimed.rename(path)
        except OSError:
            pass
        return
    claimed.unlink(missing_ok=True)


def _reclaim(directory: Path, now: float) -> None:
    for claimed in directory.glob("*.json.claimed.*"):
        try:
            if now - claimed.stat().st_mtime > CLAIM_STALE_SECONDS:
                claimed.rename(directory / claimed.name.split(".claimed.", 1)[0])
        except OSError:
            continue


def queue_status(home: Path) -> dict[str, Any]:
    """How many posts wait, and how many for each reason. Creates nothing."""
    directory = Path(home) / ".saga" / QUEUE_DIRNAME
    reasons: dict[str, int] = {}
    waiting = 0
    if directory.is_dir():
        for path in sorted(directory.iterdir()):
            if not (path.name.endswith(".json") or ".json.claimed." in path.name):
                continue
            waiting += 1
            try:
                reason = str(json.loads(path.read_text(encoding="utf-8")).get("reason") or "unknown")
            except (OSError, json.JSONDecodeError, AttributeError):
                reason = "unreadable"
            reasons[reason] = reasons.get(reason, 0) + 1
    return {"waiting": waiting, "reasons": dict(sorted(reasons.items()))}


def _send(prepared: Any, visibility: str | None, transport: Mapping[str, Any]) -> Any:
    try:
        return lf.send(prepared, visibility=visibility, **transport)
    except Exception:  # noqa: BLE001 - a client fault queues the post; it never reaches the review
        return lf.SendResult(lf.UNREACHABLE, "client-error")


def post(
    items: Sequence[Item],
    *,
    home: Path,
    getenv: Callable[[str], str | None] = os.environ.get,
    urlopen: Callable[..., Any] | None = None,
    resolve: Callable[..., Any] | None = None,
    clock: Callable[[], float] = time.monotonic,
    budget: float = POST_BUDGET_SECONDS,
) -> dict[str, Any]:
    """Drain the queue oldest first, then send ``items``; queue whatever did not go.

    ``items`` are ``(endpoint kind, body, visibility)``. Never raises for Langfuse's sake.
    """
    transport: dict[str, Any] = {"getenv": getenv, "urlopen": urlopen}
    if resolve is not None:
        transport["resolve"] = resolve
    started = clock()
    summary: dict[str, Any] = {"sent": 0, "queued": 0, "reasons": []}
    stopped: str | None = None
    directory = queue_dir(home)
    _reclaim(directory, time.time())
    for path in sorted(directory.glob("*.json")):
        if clock() - started > budget:
            stopped = stopped or "budget"
            break
        claimed = path.with_name(f"{path.name}.claimed.{os.getpid()}")
        try:
            path.rename(claimed)
            stored = json.loads(claimed.read_text(encoding="utf-8"))
            prepared = lf.prepare_payload(str(stored["kind"]), stored["body"])
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            if claimed.exists():
                claimed.rename(path)
            continue
        result = _send(prepared, stored.get("visibility"), transport)
        if result.outcome == lf.SENT:
            claimed.unlink(missing_ok=True)
            summary["sent"] += 1
            continue
        stored["reason"] = result.reason
        stored["attempts"] = int(stored.get("attempts") or 0) + 1
        _requeue(claimed, path, json.dumps(stored))
        if result.outcome in _STOP:
            stopped = result.reason
            break
    for kind, body, visible in items:
        try:
            prepared = lf.prepare_payload(kind, body)
        except Exception:  # noqa: BLE001 - an unpreparable body is a bug, reported, never raised
            summary["reasons"].append("unprepared")
            continue
        if stopped is None and clock() - started > budget:
            stopped = "budget"
        if stopped is not None:
            _enqueue(home, prepared, visible, stopped)
            summary["queued"] += 1
            summary["reasons"].append(stopped)
            continue
        result = _send(prepared, visible, transport)
        if result.outcome == lf.SENT:
            summary["sent"] += 1
            continue
        _enqueue(home, prepared, visible, result.reason)
        summary["queued"] += 1
        summary["reasons"].append(result.reason)
        if result.outcome in _STOP:
            stopped = result.reason
    summary["waiting"] = queue_status(home)["waiting"]
    return summary


def summary_line(summary: Mapping[str, Any]) -> str:
    """One line for standard error. Never holds a key, the host or a payload."""
    reasons = sorted(set(summary.get("reasons") or []))
    if summary.get("queued"):
        line = f"langfuse: queued ({', '.join(reasons)})"
    elif summary.get("reasons"):
        line = f"langfuse: not sent ({', '.join(reasons)})"
    else:
        line = "langfuse: sent"
    if summary.get("waiting"):
        line += f"; {summary['waiting']} waiting"
    return line


# ---------------------------------------------------------------------------
# Callers: the review command, the release step and plan review
# ---------------------------------------------------------------------------


def stored_runs(record: Mapping[str, Any] | None) -> list[dict[str, Any]] | None:
    if record is None:
        return None
    return [
        dict(entry) for entry in record.get("review_cycles") or []
        if isinstance(entry, Mapping) and entry.get("kind") == "review_run"
        and entry.get("loop") == review_records.STORED_LOOP
    ]


def post_review_run(
    run: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
    *,
    repo: Path | None,
    record: Mapping[str, Any] | None,
    home: Path,
    runner: Runner | None = None,
    **transport: Any,
) -> dict[str, Any]:
    """Build the run's trace and scores and post them. ``record`` is the run record or ``None``."""
    process = runner or review_tools.subprocess_runner
    slug = repository_slug(repo, recorded=(record or {}).get("repo"), runner=process)
    visible = visibility(repo, str(run.get("base") or ""), runner=process)
    findings = [f for f in run.get("findings") or [] if isinstance(f, Mapping)]
    secrets = secret_ranges(findings)
    head = str(run.get("head") or "")
    excerpts = {
        str(f.get("id") or ""): excerpt(repo, head, f, secrets, runner=process) for f in findings
    }
    earlier = stored_runs(record)
    if earlier is not None:
        earlier = [entry for entry in earlier if entry.get("round") != run.get("round")
                   or entry.get("head") != run.get("head")]
    bodies, scores = build_review_trace(
        run, results, slug=slug, visibility=visible, earlier_runs=earlier, excerpts=excerpts,
    )
    items: list[Item] = [("otel-traces", body, visible) for body in bodies]
    items.extend(("scores", score, visible) for score in scores)
    return post(items, home=home, **transport)


def post_outcomes(
    record: Mapping[str, Any],
    *,
    repo: Path | None,
    home: Path,
    runner: Runner | None = None,
    **transport: Any,
) -> dict[str, Any]:
    """Each finding's merge outcome, as a score on its entry. Called once the merge is seen."""
    process = runner or review_tools.subprocess_runner
    slug = repository_slug(repo, recorded=record.get("repo"), runner=process)
    pairs, unrecorded = outcome_scores(record, slug)
    seen: dict[str, str | None] = {}
    items: list[Item] = []
    for run, score in pairs:
        base = str(run.get("base") or "")
        if base not in seen:
            seen[base] = visibility(repo, base, runner=process)
        items.append(("scores", score, seen[base]))
    summary = post(items, home=home, **transport)
    summary["unrecorded"] = unrecorded
    summary["outcomes"] = len(pairs)
    return summary


def post_plan_review(
    entry: Mapping[str, Any],
    *,
    record: Mapping[str, Any],
    repo: Path | None,
    home: Path,
    runner: Runner | None = None,
    **transport: Any,
) -> dict[str, Any]:
    process = runner or review_tools.subprocess_runner
    slug = repository_slug(repo, recorded=record.get("repo"), runner=process)
    visible = plan_visibility(repo, runner=process) if repo is not None else None
    bodies = build_plan_trace(entry, slug=slug, card=record.get("issue"), visibility=visible)
    return post([("otel-traces", body, visible) for body in bodies], home=home, **transport)


def post_plan_answer(
    record: Mapping[str, Any],
    finding_id: str,
    *,
    repo: Path | None,
    home: Path,
    runner: Runner | None = None,
    **transport: Any,
) -> dict[str, Any]:
    process = runner or review_tools.subprocess_runner
    slug = repository_slug(repo, recorded=record.get("repo"), runner=process)
    visible = plan_visibility(repo, runner=process) if repo is not None else None
    scores = plan_answer_scores(record, finding_id, slug)
    return post([("scores", score, visible) for score in scores], home=home, **transport)


# ---------------------------------------------------------------------------
# Reading back: the project probe and the rounds view
# ---------------------------------------------------------------------------


def rounds_query(now: datetime | None = None) -> dict[str, Any]:
    moment = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return {
        "view": "scores-boolean",
        "dimensions": [{"field": "name"}],
        "metrics": [
            {"measure": "value", "aggregation": "avg"},
            {"measure": "count", "aggregation": "count"},
        ],
        "filters": [{
            "column": "name", "operator": "any of", "value": list(ROUND_VIEW_SCORES),
            "type": "stringOptions",
        }],
        "fromTimestamp": METRICS_FROM,
        "toTimestamp": moment,
    }


def _metric(row: Mapping[str, Any], measure: str, aggregation: str) -> float | None:
    for key in (f"{aggregation}_{measure}", f"{measure}_{aggregation}", measure, aggregation):
        value = row.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                continue
    return None


def rounds_lines(body: Any) -> list[str]:
    rows = body.get("data") if isinstance(body, Mapping) else None
    found = {str(row.get("name")): row for row in rows or [] if isinstance(row, Mapping)}
    lines = []
    for name in ROUND_VIEW_SCORES:
        number = name.split("-")[1]
        row = found.get(name)
        share = _metric(row, "value", "avg") if row else None
        count = int(_metric(row, "count", "count") or 0) if row else 0
        if share is None or count == 0:
            lines.append(f"round {number}: no runs yet")
        else:
            lines.append(f"round {number} found something new in {round(share * 100)}% of {count} runs")
    return lines


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="review_trace.py",
        description="Post saga review traces to Langfuse, and read back the queue and the rounds view.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    posting = sub.add_parser("post", help="Post one review run's trace.")
    posting.add_argument("--run", type=Path, required=True, help="The review run JSON.")
    posting.add_argument("--result", type=Path, action="append", default=[],
                         help="A reviewer result JSON, once per LLM step.")
    posting.add_argument("--repo", type=Path, default=None, help="The reviewed repository.")
    posting.add_argument("--record", type=Path, default=None, help="The issue's run record JSON.")
    posting.add_argument("--home", type=Path, default=None)
    for name, text in (("drain", "Send what waits in the queue."), ("status", "Count what waits.")):
        command = sub.add_parser(name, help=text)
        command.add_argument("--home", type=Path, default=None)
    probe = sub.add_parser("probe", help=f"Check that the {PROJECT_NAME!r} project answers.")
    probe.add_argument("--repo", type=Path, default=None)
    rounds = sub.add_parser("rounds", help="How often round 2 or 3 found anything new.")
    rounds.add_argument("--repo", type=Path, default=None)
    return parser


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(
    argv: Sequence[str] | None = None,
    *,
    urlopen: Callable[..., Any] | None = None,
    getenv: Callable[[str], str | None] = os.environ.get,
    resolve: Callable[..., Any] | None = None,
    runner: Runner | None = None,
) -> int:
    """Run one subcommand. The keyword arguments are test seams the CLI does not expose."""
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    transport: dict[str, Any] = {"urlopen": urlopen, "getenv": getenv}
    if resolve is not None:
        transport["resolve"] = resolve
    home = Path(getattr(args, "home", None) or Path.home())
    if args.command == "status":
        status = queue_status(home)
        reasons = ", ".join(f"{name} {count}" for name, count in status["reasons"].items())
        print(f"langfuse: {status['waiting']} waiting" + (f" ({reasons})" if reasons else ""))
        if "plain-http-private" in status["reasons"]:
            print("  " + lf.X3_MESSAGE)
        return 0
    if args.command == "drain":
        print(summary_line(post([], home=home, **transport)), file=sys.stderr)
        return 0
    if args.command == "post":
        try:
            run = _read_json(args.run)
            results = [_read_json(path) for path in args.result]
            record = _read_json(args.record) if args.record else None
        except (OSError, json.JSONDecodeError) as exc:
            print(f"review_trace: {exc.__class__.__name__}: unreadable input", file=sys.stderr)
            return 2
        try:
            summary = post_review_run(run, results, repo=args.repo, record=record, home=home,
                                      runner=runner, **transport)
            print(summary_line(summary), file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 - posting never fails the caller
            print(f"langfuse: not posted ({exc.__class__.__name__})", file=sys.stderr)
        return 0
    repo = args.repo or Path.cwd()
    visible = plan_visibility(repo, runner=runner)
    if args.command == "probe":
        result = lf.get("projects", visibility=visible, **transport)
        if result.outcome != lf.SENT:
            print(f"langfuse: {result.reason}", file=sys.stderr)
            return 1
        names = [
            str(row.get("name")) for row in (result.body or {}).get("data") or []
            if isinstance(row, Mapping)
        ]
        if PROJECT_NAME in names:
            print(f"{PROJECT_NAME} ok")
            return 0
        print(f"langfuse: the keys answer for another project, not {PROJECT_NAME!r}", file=sys.stderr)
        return 1
    result = lf.get("metrics", {"query": rounds_query()}, visibility=visible, **transport)
    if result.outcome != lf.SENT:
        print(f"langfuse: {result.reason}", file=sys.stderr)
        return 1
    for line in rounds_lines(result.body):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
