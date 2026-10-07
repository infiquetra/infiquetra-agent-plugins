#!/usr/bin/env python3
"""Cut a diff into the pieces ``jev sweep`` classifies (issue 156).

The changed lines come from ``review_diff``. The bytes come from ``git show`` of
the head blob, never from the worktree, because the change under review is
untrusted. Python spans come from ``ast``. The other languages on the Ctags row
come from Universal Ctags, or from the 20-line window when that parser is absent.
"""

from __future__ import annotations

import ast
import json
import stat
import subprocess  # nosec B404
import tempfile
from pathlib import Path
from typing import Any, Callable

import review_diff
import review_tools

SWEEP_COMPONENTS = (
    "plugins/fleet-core/scripts/fleet_commons/jev_sweep.py",
    "plugins/saga/scripts/sweep_pieces.py",
    "plugins/saga/references/model-prices.yaml",
)
CALIBRATION_SCHEMA = "review_calibration.v1"
BANK_SCHEMA = "question_bank.v1"
PIECE_KINDS = ("function", "block", "file")
ROW_KEYS = {"question", "threshold", "piece_size"}
CTAGS_LANGUAGES = {
    "typescript": "TypeScript",
    "dart": "Dart",
    "rust": "Rust",
    "swift": "Swift",
    "shell": "Sh",
}
_TAG_KINDS = {"function", "method", "member"}
DEFAULT_CALIBRATION = (
    Path(__file__).resolve().parent.parent / "references" / "review-calibration.json"
)

Runner = Callable[..., Any]


class SweepPiecesError(ValueError):
    """The bank or the calibration file is not the shape this cutter accepts."""


def pieces(
    repo: Path | str,
    base: str,
    head: str,
    bank: Any,
    *,
    calibration: Path | str | None = None,
    parser: Callable[..., Any] | None = None,
    block_context_lines: int | None = None,
    small_file_max_lines: int | None = None,
    ctags_runner: Runner | None = None,
) -> dict[str, Any]:
    """One piece per changed function, plus a block or a file when the bank asks."""
    if block_context_lines is None or small_file_max_lines is None:
        bundled_context, bundled_file = _bundled_limits()
        if block_context_lines is None:
            block_context_lines = bundled_context
        if small_file_max_lines is None:
            small_file_max_lines = bundled_file
    questions = _bank_questions(bank)
    thresholds, sizes = _calibration(calibration, {item["id"] for item in questions})
    change = review_diff.read(repo, base, head)
    built: list[dict[str, Any]] = []
    degraded: list[dict[str, Any]] = []
    for item in change.files:
        if not item.lines:
            continue
        text = _head_text(repo, head, item.path)
        if text is None:
            continue
        language = review_tools.language_for(item.path)
        file_lines = text.splitlines()
        spans = _spans(text, item.path, language, parser=parser, runner=ctags_runner)
        built.extend(
            _file_pieces(
                item.path, language, file_lines, item.lines, spans, questions, sizes,
                block_context_lines, small_file_max_lines, degraded,
            )
        )
    return {"pieces": built, "degraded": degraded, "thresholds": thresholds}


def ctags_is_universal(version_text: str) -> bool:
    """Exuberant Ctags does not qualify. The text has to name Universal Ctags."""
    return "Universal Ctags" in version_text


def read_ctags_spans(
    text: str,
    path: str,
    language: str,
    runner: Runner | None = None,
) -> list[dict[str, Any]] | None:
    """Spans from Universal Ctags, or ``None`` when the parse cannot be trusted.

    The head blob is a ``0o600`` file inside a ``0o700`` directory. The directory
    is removed when this function returns, including when ctags fails. The file
    keeps the source suffix so ``--language-force`` and the suffix agree.
    """
    forced = CTAGS_LANGUAGES.get(language)
    if forced is None:
        return None
    run = runner or _default_runner
    suffix = Path(path).suffix
    with tempfile.TemporaryDirectory(prefix="sweep-") as directory:
        blob = Path(directory) / f"source{suffix}"
        blob.write_text(text, encoding="utf-8")
        blob.chmod(stat.S_IRUSR | stat.S_IWUSR)
        version = _run(run, ["ctags", "--options=NONE", "--version"], directory)
        if version is None or version.returncode != 0:
            return None
        if not ctags_is_universal(version.stdout or ""):
            return None
        proc = _run(
            run,
            [
                "ctags",
                "--options=NONE",
                "--output-format=json",
                "--fields=+ne",
                f"--language-force={forced}",
                "-o",
                "-",
                "--",
                str(blob),
            ],
            directory,
        )
        if proc is None or proc.returncode != 0:
            return None
        return _parse_tags(proc.stdout or "")


def calibration_path_lists() -> list[list[str]] | None:
    """Path lists ``review_calibration.py`` exports, or ``None`` when it is absent.

    The list's name belongs to card C2. This looks at the sequences the module
    actually defines rather than guessing a name.
    """
    path = Path(__file__).resolve().parent / "review_calibration.py"
    if not path.is_file():
        return None
    import importlib.util
    import sys

    cache_key = "review_calibration_for_sweep_components"
    spec = importlib.util.spec_from_file_location(cache_key, path)
    if spec is None or spec.loader is None:
        return []
    module = importlib.util.module_from_spec(spec)
    sys.modules[cache_key] = module
    spec.loader.exec_module(module)
    found: list[list[str]] = []
    for name, value in vars(module).items():
        if name.startswith("_") or not isinstance(value, (list, tuple)) or not value:
            continue
        if all(isinstance(item, str) and item.startswith("plugins/") for item in value):
            found.append(list(value))
    return found


def _bundled_limits() -> tuple[int, int]:
    """The two line counts, read from saga's bundle only when a caller omits them."""
    import sys

    scripts = Path(__file__).resolve().parent
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import bundled_fleet

    module = bundled_fleet.load("jev_sweep")
    return int(module.BLOCK_CONTEXT_LINES), int(module.SMALL_FILE_MAX_LINES)


def _bank_questions(bank: Any) -> list[dict[str, Any]]:
    if not isinstance(bank, dict) or bank.get("schema") != BANK_SCHEMA:
        raise SweepPiecesError("bank schema must be question_bank.v1")
    raw = bank.get("questions")
    if not isinstance(raw, list):
        raise SweepPiecesError("bank questions must be a list")
    questions = []
    for index, question in enumerate(raw):
        if not isinstance(question, dict):
            raise SweepPiecesError(f"questions[{index}] is not an object")
        qid = question.get("id")
        kind = question.get("piece")
        if not isinstance(qid, str) or not qid:
            raise SweepPiecesError(f"questions[{index}] needs an id")
        if kind not in PIECE_KINDS:
            raise SweepPiecesError(f"questions[{index}] needs a piece kind")
        questions.append(question)
    return questions


def _calibration(
    path: Path | str | None, question_ids: set[str],
) -> tuple[dict[str, float], dict[str, int]]:
    if path is None:
        target = DEFAULT_CALIBRATION
        if not target.is_file():
            return {}, {}
    else:
        target = Path(path)
        if not target.is_file():
            raise SweepPiecesError(f"no calibration file at {target}")
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SweepPiecesError(f"calibration file is not JSON: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema") != CALIBRATION_SCHEMA:
        raise SweepPiecesError("calibration schema must be review_calibration.v1")
    rows = raw.get("thresholds")
    if not isinstance(rows, list):
        raise SweepPiecesError("calibration thresholds must be a list")
    thresholds: dict[str, float] = {}
    sizes: dict[str, int] = {}
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise SweepPiecesError(f"thresholds[{index}] is not an object")
        extra = set(row) - ROW_KEYS
        if extra:
            names = ", ".join(sorted(extra))
            raise SweepPiecesError(f"thresholds[{index}] has unexpected keys: {names}")
        if "question" not in row or "threshold" not in row:
            raise SweepPiecesError(f"thresholds[{index}] is missing question or threshold")
        qid = row["question"]
        if not isinstance(qid, str) or qid not in question_ids:
            raise SweepPiecesError(f"thresholds[{index}] names an unknown question")
        if qid in seen:
            raise SweepPiecesError(f"thresholds[{index}] repeats {qid}")
        seen.add(qid)
        number = row["threshold"]
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            raise SweepPiecesError(f"threshold for {qid} must be a number")
        if number < 0 or number > 1:
            raise SweepPiecesError(f"threshold for {qid} must be from 0 to 1")
        thresholds[qid] = float(number)
        if "piece_size" in row:
            sizes[qid] = _piece_size(row["piece_size"], qid)
    return thresholds, sizes


def _piece_size(value: Any, qid: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SweepPiecesError(f"piece_size for {qid} must be a positive integer")
    return value


def _head_text(repo: Path | str, head: str, path: str) -> str | None:
    proc = subprocess.run(  # nosec B603
        ["git", "show", f"{head}:{path}"],
        cwd=repo,
        check=False,
        capture_output=True,
    )
    if proc.returncode != 0:
        return None
    try:
        return proc.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _spans(
    text: str,
    path: str,
    language: str,
    *,
    parser: Callable[..., Any] | None,
    runner: Runner | None,
) -> list[dict[str, Any]] | None:
    """Spans, or ``None`` when the parser did not run.

    ``None`` is the degraded window. An empty list means the parser ran and
    found no function. For Python that is a module-level window and is not
    degraded. For Ctags an empty list, or a list that covers no changed line,
    is the same degraded window as a missing parser.
    """
    if language == "python":
        return _python_spans(text)
    if language not in CTAGS_LANGUAGES:
        return None
    if parser is not None:
        try:
            parsed = parser(text, path, language)
        except FileNotFoundError:
            return None
        if parsed is None:
            return None
        return list(parsed)
    return read_ctags_spans(text, path, language, runner=runner)


def _python_spans(text: str) -> list[dict[str, Any]] | None:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    source = text.splitlines()
    spans = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.end_lineno is None:
            continue
        start = node.lineno
        if node.decorator_list:
            start = min(item.lineno for item in node.decorator_list)
        anchor = source[node.lineno - 1].strip() if node.lineno <= len(source) else node.name
        spans.append({
            "name": node.name,
            "start": start,
            "end": node.end_lineno,
            "anchor": anchor,
        })
    return spans


def _file_pieces(
    path: str,
    language: str,
    file_lines: list[str],
    changed: frozenset[int],
    spans: list[dict[str, Any]] | None,
    questions: list[dict[str, Any]],
    sizes: dict[str, int],
    context: int,
    small_max: int,
    degraded: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    owned = _assign(spans, changed) if spans else {}
    covered = set(owned)
    # Python outside a function is a real window. Ctags with nothing covering
    # the change, and a parser that did not run, are the degraded window.
    missed = not covered
    window_degraded = missed and not (language == "python" and spans is not None)
    built: list[dict[str, Any]] = []
    if covered:
        seen: list[tuple[int, int, str | None]] = []
        for line in sorted(covered):
            span = owned[line]
            key = (span["start"], span["end"], span.get("name"))
            if key in seen:
                continue
            seen.append(key)
            origin = _piece(
                path, language, "function", file_lines, span["start"], span["end"],
                span.get("name"), False, span.get("anchor") or "",
            )
            built.append(origin)
            built.extend(_clips(origin, file_lines, changed, questions, sizes, "function"))
        outside = changed - covered
        if outside:
            built.extend(
                _window_pieces(
                    path, language, file_lines, outside, context, "function", False,
                    questions, sizes,
                )
            )
    else:
        built.extend(
            _window_pieces(
                path, language, file_lines, changed, context, "function", window_degraded,
                questions, sizes,
            )
        )
    if any(question["piece"] == "block" for question in questions):
        built.extend(
            _window_pieces(
                path, language, file_lines, changed, context, "block", window_degraded,
                questions, sizes,
            )
        )
    _file_kind(
        path, language, file_lines, changed, questions, sizes, small_max, built, degraded,
    )
    return built


def _assign(
    spans: list[dict[str, Any]], changed: frozenset[int],
) -> dict[int, dict[str, Any]]:
    owned: dict[int, dict[str, Any]] = {}
    for line in changed:
        covers = [span for span in spans if span["start"] <= line <= span["end"]]
        if not covers:
            continue
        covers.sort(key=lambda span: (span["end"] - span["start"], -span["start"]))
        owned[line] = covers[0]
    return owned


def _window_pieces(
    path: str,
    language: str,
    file_lines: list[str],
    changed: frozenset[int],
    context: int,
    kind: str,
    degraded: bool,
    questions: list[dict[str, Any]] | None,
    sizes: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    built = []
    for start, end in _windows(len(file_lines), changed, context):
        origin = _piece(path, language, kind, file_lines, start, end, None, degraded, "")
        built.append(origin)
        if questions is not None and sizes is not None:
            built.extend(_clips(origin, file_lines, changed, questions, sizes, kind))
    return built


def _windows(line_count: int, changed: frozenset[int], context: int) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for line in sorted(changed):
        start = max(1, line - context)
        end = min(line_count, line + context)
        if ranges and start <= ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], end))
        else:
            ranges.append((start, end))
    return ranges


def _file_kind(
    path: str,
    language: str,
    file_lines: list[str],
    changed: frozenset[int],
    questions: list[dict[str, Any]],
    sizes: dict[str, int],
    small_max: int,
    built: list[dict[str, Any]],
    degraded: list[dict[str, Any]],
) -> None:
    file_questions = [question for question in questions if question["piece"] == "file"]
    if not file_questions:
        return
    count = len(file_lines)
    unsized = [question for question in file_questions if question["id"] not in sizes]
    if count <= small_max and unsized:
        origin = _piece(path, language, "file", file_lines, 1, count, None, False, "")
        built.append(origin)
    elif count > small_max:
        for question in unsized:
            degraded.append({
                "reason": "file-too-large",
                "question": question["id"],
                "piece": path,
            })
    for question in file_questions:
        size = sizes.get(question["id"])
        if size is None:
            continue
        start, end = _clip(1, count, changed, size)
        built.append(
            _piece(
                path, language, "file", file_lines, start, end, None, False, "",
                only_question=question["id"],
            )
        )


def _clips(
    origin: dict[str, Any],
    file_lines: list[str],
    changed: frozenset[int],
    questions: list[dict[str, Any]],
    sizes: dict[str, int],
    kind: str,
) -> list[dict[str, Any]]:
    start = origin["location"]["lines"]["start"]
    end = origin["location"]["lines"]["end"]
    inside = {line for line in changed if start <= line <= end} or {start}
    clips = []
    for question in questions:
        if question["piece"] != kind or question["id"] not in sizes:
            continue
        clip_start, clip_end = _clip(start, end, inside, sizes[question["id"]])
        clips.append(
            _piece(
                origin["path"], origin["language"], kind, file_lines, clip_start, clip_end,
                origin["location"]["function"], False, origin["location"]["anchor"],
                only_question=question["id"],
            )
        )
    return clips


def _clip(origin_start: int, origin_end: int, changed: set[int], size: int) -> tuple[int, int]:
    width = origin_end - origin_start + 1
    if size >= width:
        return origin_start, origin_end
    center = (min(changed) + max(changed)) // 2
    half = size // 2
    start = center - half
    end = start + size - 1
    if start < origin_start:
        end += origin_start - start
        start = origin_start
    if end > origin_end:
        start -= end - origin_end
        end = origin_end
    return max(start, origin_start), min(end, origin_end)


def _piece(
    path: str,
    language: str,
    kind: str,
    file_lines: list[str],
    start: int,
    end: int,
    function: str | None,
    degraded: bool,
    anchor: str,
    only_question: str | None = None,
) -> dict[str, Any]:
    selected = file_lines[start - 1:end]
    if not anchor:
        anchor = next((line.strip() for line in selected if line.strip()), path)
    identity = f"{path}:{start}-{end}"
    if only_question:
        identity = f"{identity}:{only_question}"
    piece: dict[str, Any] = {
        "id": identity,
        "path": path,
        "language": language,
        "kind": kind,
        "text": "\n".join(selected) + "\n",
        "degraded": degraded,
        "location": {
            "scope": "lines",
            "file": path,
            "lines": {"start": start, "end": end},
            "function": function,
            "anchor": anchor,
        },
    }
    if only_question:
        piece["only_question"] = only_question
    return piece


def _parse_tags(stdout: str) -> list[dict[str, Any]] | None:
    spans = []
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", "")).lower()
        if kind not in _TAG_KINDS:
            continue
        end = item.get("end")
        start = item.get("line", item.get("start"))
        if isinstance(end, bool) or not isinstance(end, int):
            continue
        if isinstance(start, bool) or not isinstance(start, int) or end < start:
            continue
        name = item.get("name")
        spans.append({
            "name": name if isinstance(name, str) else None,
            "start": start,
            "end": end,
            "anchor": "",
        })
    return spans


def _run(runner: Runner, argv: list[str], cwd: str) -> Any:
    try:
        return runner(argv, cwd)
    except FileNotFoundError:
        return None


def _default_runner(argv: list[str], cwd: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(  # nosec B603
            argv, cwd=cwd, check=False, capture_output=True, text=True,
        )
    except FileNotFoundError:
        return None
