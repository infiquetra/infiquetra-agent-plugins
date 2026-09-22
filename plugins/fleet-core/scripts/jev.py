#!/usr/bin/env python3
"""``jev`` -- the command-line front door to the TypeSafe client (plan U5).

Any harness that can run a shell command can use this without the plugin being
visible to it.  Output is JSON on standard output; failures exit non-zero with a
reason on standard error.

    jev ask --state '{"x":"hello"}' --noul 'Is `x` a greeting?'
    jev ask --state-file state.json --noul '...' --dry-run
    jev tier --state '{"task":"rename a variable across 12 files"}'
    jev eval --cached docs/analysis/2026-09-18-typesafe-jev-research-inputs/

``--dry-run`` prints the request body and makes no call.  The body never carries
the credential -- it lives only in the ``Authorization`` header -- so the dry run
is safe to print and to paste into an issue.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path


def _load_sibling(name: str):
    """Load ``fleet_commons/<name>.py`` beside this script.

    Portable stand-in for ``fleet_commons_shim.load``. See the same helper in
    the fleet_commons modules: resolution is the directory that holds the
    modules, never the Claude Code plugin ladder.
    """
    import importlib.util
    import sys

    sibling_dir = Path(__file__).resolve().parent / "fleet_commons"
    cache_key = f"_fleet_commons_{name}@{sibling_dir}"
    cached = sys.modules.get(cache_key)
    if cached is not None:
        return cached
    module_path = sibling_dir / f"{name}.py"
    if not module_path.is_file():
        raise RuntimeError(f"fleet-commons: module {name!r} not found at {module_path}")
    spec = importlib.util.spec_from_file_location(cache_key, module_path)
    if spec is None or spec.loader is None:  # pragma: no cover - importlib internal failure
        raise RuntimeError(f"fleet-commons: importlib could not load {module_path}")
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[cache_key] = loaded
    try:
        spec.loader.exec_module(loaded)
    except BaseException:
        sys.modules.pop(cache_key, None)
        raise
    return loaded

typesafe_client = _load_sibling("typesafe_client")
jev_eval = _load_sibling("jev_eval")
jev_log = _load_sibling("jev_log")
jev_verbs = _load_sibling("jev_verbs")


def _fail(message: str) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return 1


def _load_state(args: argparse.Namespace) -> object:
    if args.state is not None and args.state_file is not None:
        raise ValueError("pass either --state or --state-file, not both")
    if args.state_file is not None:
        path = Path(args.state_file)
        if not path.is_file():
            raise ValueError(f"no such state file: {path}")
        raw = path.read_text(encoding="utf-8")
    elif args.state is not None:
        raw = args.state
    else:
        raise ValueError("a state is required; pass --state or --state-file")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        source = "--state-file" if args.state_file else "--state"
        raise ValueError(f"{source} is not valid JSON: {exc}") from None


def _questions_from_flags(args: argparse.Namespace) -> dict[str, object]:
    questions: dict[str, object] = {}
    for index, instructions in enumerate(args.noul or []):
        questions[f"noul_{index + 1}" if index else "noul"] = {
            "type": "noul",
            "instructions": instructions,
        }
    for index, spec in enumerate(args.choice or []):
        instructions, _, options = spec.partition("::")
        if not options:
            raise ValueError(
                "--choice takes 'question::option1,option2'; no '::' separator was found"
            )
        criteria = {opt.strip(): "" for opt in options.split(",") if opt.strip()}
        if len(criteria) < 2:
            raise ValueError("--choice needs at least two comma-separated options")
        questions[f"choice_{index + 1}" if index else "choice"] = {
            "type": "choice",
            "instructions": instructions,
            "criteria": criteria,
        }
    for index, spec in enumerate(args.score or []):
        instructions, _, levels = spec.partition("::")
        if not levels:
            raise ValueError("--score takes 'question::low,medium,high'; no '::' separator found")
        ordered = [level.strip() for level in levels.split(",") if level.strip()]
        if len(ordered) < 2:
            raise ValueError("--score needs at least two ordered levels")
        questions[f"score_{index + 1}" if index else "score"] = {
            "type": "score",
            "instructions": instructions,
            "criteria": ordered,
        }
    if not questions:
        raise ValueError("at least one of --noul, --choice or --score is required")
    return questions


def _emit(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def _run_ask(args: argparse.Namespace, questions: dict[str, object]) -> int:
    try:
        state = _load_state(args)
    except ValueError as exc:
        return _fail(str(exc))

    if args.dry_run:
        try:
            prepared = typesafe_client.prepare_state(state, questions)
            body = typesafe_client.build_body(prepared, args.model)
        except typesafe_client.TypeSafeClientError as exc:
            return _fail(str(exc))
        _emit({"dry_run": True, "request": body, "truncation": list(prepared.truncation)})
        return 0

    result = typesafe_client.ask(state, questions, model=args.model, transport=args.transport)
    payload = result.to_dict()

    if result.status != typesafe_client.STATUS_OK:
        _emit(payload)
        return _fail(result.note or f"the request failed with status {result.status}")

    if args.log:
        for key, answer in result.answers.items():
            jev_log.record_verdict(
                decision_id=f"{args.decision_id or args.verb}:{key}",
                state=state,
                questions=questions,
                answer=answer,
                confidence=typesafe_client.answer_confidence(answer),
                threshold=args.confidence_floor,
                resolved_model=result.model,
            )

    _emit(payload)
    return 0


def _run_eval(args: argparse.Namespace) -> int:
    try:
        report = jev_eval.evaluate_path(Path(args.cached), question_key=args.question_key)
    except jev_eval.EvalInputError as exc:
        return _fail(str(exc))
    if args.json:
        _emit(report.to_dict())
    else:
        print(report.render())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jev", description="Typed judgments from the TypeSafe System One endpoint."
    )
    sub = parser.add_subparsers(dest="verb", required=True)

    def _add_common(target: argparse.ArgumentParser) -> None:
        target.add_argument("--state", help="the state as an inline JSON document")
        target.add_argument("--state-file", help="a file holding the state as JSON")
        target.add_argument("--model", default=typesafe_client.DEFAULT_MODEL)
        target.add_argument("--transport", choices=list(typesafe_client.TRANSPORTS))
        target.add_argument(
            "--dry-run",
            action="store_true",
            help="print the request body and make no call",
        )
        target.add_argument("--log", action="store_true", help="append to the verdict log")
        target.add_argument("--decision-id", help="identifier recorded in the verdict log")

    ask = sub.add_parser("ask", help="ask an ad-hoc question set")
    _add_common(ask)
    ask.add_argument("--noul", action="append", help="a yes/no question")
    ask.add_argument("--choice", action="append", help="'question::option1,option2'")
    ask.add_argument("--score", action="append", help="'question::low,medium,high'")
    ask.set_defaults(confidence_floor=None)

    for name in jev_verbs.verb_names():
        verb = jev_verbs.VERBS[name]
        target = sub.add_parser(name, help=f"{verb.summary} ({verb.state_help})")
        _add_common(target)
        target.set_defaults(confidence_floor=verb.confidence_floor)

    evaluate = sub.add_parser("eval", help="score recorded answers against labels")
    evaluate.add_argument(
        "--cached", required=True, help="a recorded-answers file or a directory holding one"
    )
    evaluate.add_argument(
        "--question-key", help="score one question out of each record's answer map"
    )
    evaluate.add_argument("--json", action="store_true", help="emit JSON rather than text")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.verb == "eval":
        return _run_eval(args)

    if args.verb == "ask":
        try:
            questions = _questions_from_flags(args)
        except ValueError as exc:
            return _fail(str(exc))
    else:
        questions = jev_verbs.VERBS[args.verb].question_set()

    return _run_ask(args, questions)


if __name__ == "__main__":
    sys.exit(main())
