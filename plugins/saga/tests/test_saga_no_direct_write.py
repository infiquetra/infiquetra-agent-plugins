"""W-D1 (#927 U1): no plugin composes or executes a board-field write; Mission Control alone does.

**The discriminator changed on 2026-08-30, and this docstring is the record of why.** The W7 guard
(SDLC issue #88) asked a lexical question — *does this file name the ``set-field-status``
operation?* — and answered "any mention is an offense". The operator superseded that reading:
deciding and submitting a lifecycle-field move is not writing one. Plan and Work now MUST submit
their moves, so the old assertion would forbid the very thing the contract requires.

The question this guard asks instead is **does this path reach GitHub without passing through
Mission Control's executor?**

* **Legal — a submission.** A fenced ``reconcile_controller.py reconcile --op set-field-status``
  block in a skill, or a Python call into ``board_progression.authorize_and_write`` /
  ``default_board_writer``. Every one of those hops stops at Mission Control's ``flow set-field
  --correction``, which owns the certificate gate, the idempotency ledger and the GitHub call.
* **Illegal anywhere under ``plugins/`` except ``plugins/mission-control/``.** The projectV2
  item-field mutation, ``gh project item-edit``, a hand-built single-select option payload, or a
  ``gh api graphql`` invocation aimed at a projectV2 field mutation. Those reach GitHub directly.
* **Illegal — an unrouted op.** Naming the lifecycle-field op kind (literal *or* through the
  certificate constant) in a module that carries no submission seam at all. That is a module
  composing a board write it has no door for.

Three structural properties carry over from the W7 guard unchanged, because each one exists to stop
a specific false result that was reproduced against the real tree:

1. **The scan resolves the op-kind CONSTANT, not only its literal value** (false-green guard).
   ``/outcome`` once composed its op through ``cert.OpKind.SET_FIELD_STATUS`` rather than the
   ``"set-field-status"`` string, so a literal grep returned zero matches while the write was fully
   intact. :data:`_PY_CONSTANT_COMPOSE_RE` flags the constant symbol too.
2. **Nested run artifacts are out of scope** (false-red guard). A vendored checkout under
   ``.claude/agy/runs/**`` carries its own copy of these files; reporting it would keep the gate
   permanently red on code that does not ship.
3. **The submission core is allowlisted.** ``board_progression``, ``op_allowlist`` and
   ``reconcile_controller`` ARE the submission mechanism, and ``outcome_reconcile`` reads historical
   op kinds out of the ledger. Listed explicitly so the exemption is a decision, not an accident.

The scan root widened with the aim: from ``plugins/saga/`` to the whole of ``plugins/``, minus
``plugins/mission-control/``. W7's guard scanned one plugin, which is why Orchestrate's leftover
writer never failed it (#927: "Orchestrate was missed, not exempted"). Within each plugin the walk
is the whole directory and a broad set of suffixes, because a mutation body does not have to live
in a ``.py`` file under one of six conventional directory names to be loaded and driven by one.

**What this guard does not claim.** It is a text scan, so a mutation name assembled at runtime —
``"update" + "ProjectV2ItemFieldValue"`` — evades it, and no lexical form can fix that. What it
does is make an accidental reintroduction impossible to land and a deliberate evasion impossible
to write innocently: the evading form has no reason to exist, so it reads as what it is in review.
The seam patterns are invocations rather than mentions for the same reason — a file must not be
able to excuse itself with a comment.

Offline: pure filesystem + source scanning plus the REAL certificate/controller/board_progression
modules loaded by path (the single-writer-guard's house pattern). No git, no GitHub, no gh.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
PLUGINS_ROOT = ROOT / "plugins"
SAGA_ROOT = PLUGINS_ROOT / "saga"
SCRIPTS = SAGA_ROOT / "scripts"

# Mission Control is the executor. The direct-write vocabulary is its job description, not an
# offense, so its plugin directory is the one exclusion from the fleet-wide scan.
EXECUTOR_PLUGIN_DIR = "mission-control"

# Guard modules that must quote the forbidden tokens. Excluded from the scan
# they implement. See ``_iter_plugin_sources``.
_DENYLIST_SOURCES = frozenset(
    {
        Path(__file__).resolve(),
        (Path(__file__).resolve().parent / "test_saga_single_writer_guard.py").resolve(),
    }
)

# The op-kind vocabulary is ALLOWED without further proof only in the submission/gating core: the
# certificate (definition + field gating), the one legal writer (board_progression), and the
# reconcile controller. Every other file must show a submission seam to name the op at all.
OP_KIND_CORE_FILES = frozenset(
    {
        (SCRIPTS / "board_progression.py").resolve(),
        (SCRIPTS / "op_allowlist.py").resolve(),
        (SCRIPTS / "reconcile_controller.py").resolve(),
    }
)

# /outcome's resume-time detector reads HISTORICAL status keys out of the board-sync ledger; its
# family constant is a read-side vocabulary for ledger records, not an initiation.
OP_KIND_READ_SIDE_FILES = frozenset(
    {
        (SCRIPTS / "outcome_reconcile.py").resolve(),
    }
)

# Reaching GitHub's project fields without Mission Control. Each pattern names a mechanism that
# lands a value on a card by itself — no certificate, no ledger, no replay key.
DIRECT_WRITE_SIGNATURES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?:update|clear)ProjectV2ItemFieldValue", re.IGNORECASE),
        "composes the projectV2 item-field mutation directly",
    ),
    (
        re.compile(r"\bgh\s+project\s+item-edit\b"),
        "executes `gh project item-edit` directly",
    ),
    (
        re.compile(r"singleSelectOptionId|[\"']optionId[\"']\s*:"),
        "hand-builds a project single-select option payload",
    ),
    (
        re.compile(r"gh\s+api\s+graphql[\s\S]{0,600}?projectV2[A-Za-z]*Field", re.IGNORECASE),
        "drives `gh api graphql` at a projectV2 field mutation",
    ),
)

# The submission seams: a file that USES one of these routes its move through Mission Control's
# executor rather than composing its own write. ``reconcile_controller`` is the door orchestrate
# drives as a subprocess; ``authorize_and_write`` / ``default_board_writer`` are the in-process
# equivalents that /outcome and /work use.
#
# Every alternative below is an INVOCATION or an IMPORT, never a bare mention. A pattern that
# matched the name anywhere in the text would let a module exempt itself with a comment — a line
# reading "see reconcile_controller.py for the provenance of this" would satisfy it while the file
# went on to compose its own write. Naming a door is not walking through it.
SUBMISSION_SEAM_RE = re.compile(
    r"authorize_and_write\s*\("
    r"|default_board_writer\s*\("
    r"|_reconcile_call\s*\("
    r"|reconcile_controller_path\s*\("
    r"|\bimport\s+(?:board_progression|reconcile_controller)\b"
    r"|\bfrom\s+(?:board_progression|reconcile_controller)\s+import\b"
)

# The fenced submission a skill is REQUIRED to carry at a lifecycle boundary. Two spellings, one
# contract: the controller call that names an op kind, and the boundary call that names a lifecycle
# boundary and lets the allowed-submission table choose the pair (issue 1028). A `--dry-run` block
# is an inspection, not a submission, and is excluded — otherwise every boundary would appear to
# submit twice.
FENCED_SUBMISSION_RE = re.compile(
    r"reconcile_controller\.py\s+reconcile\b(?:(?!```).)*--op\s+set-field-status",
    re.DOTALL,
)
FENCED_BOUNDARY_RE = re.compile(
    r"board_progression\.py\b(?:(?!```).)*--boundary\s+(?P<boundary>[a-z-]+)",
    re.DOTALL,
)
DRY_RUN_RE = re.compile(r"--dry-run")

# The lifecycle boundaries /work submits, in the order the skill reaches them. `review-accepted` is
# absent on purpose: the lifecycle repository's allowed list carries no row for it, so the skill
# prints the absence and submits nothing there.
WORK_BOUNDARIES = ["build-start", "merge-and-deploy", "close"]

# Constant-resolution false-green guard: the op kind composed through the certificate CONSTANT —
# the exact shape ``outcome_board_sync.py`` had at the W7 planning base — rather than the literal.
_PY_CONSTANT_COMPOSE_RE = re.compile(
    r"str\s*\(\s*cert\.OpKind\.SET_FIELD_STATUS|OpKind\.SET_FIELD_STATUS\s*[,)\]]"
)

_MARKER = "set-field-status"


def _load(name: str) -> ModuleType:
    # Reuse an existing module instance when one is loaded: these share the singleton module
    # identity other saga tests assert on (e.g. outcome_reconcile's re-export identity probe).
    if name in sys.modules:
        return sys.modules[name]
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


RC = _load("reconcile_controller")
CERT = _load("op_allowlist")

# Shipped sources only: any path under a nested checkout or run artifact is out of scope.
_EXCLUDED_SEGMENTS = frozenset({".claude", "agy", "runs", "worktree", "__pycache__"})

# Every suffix a write could hide in. Markdown is included because skills are executable prose;
# shell, JSON, GraphQL and plain text are included because a mutation body or a hand-built option
# payload does not have to live in a ``.py`` file to be loaded and driven by one.
_SOURCE_SUFFIXES = frozenset(
    {".py", ".md", ".sh", ".bash", ".json", ".graphql", ".gql", ".txt", ".yaml", ".yml", ".toml"}
)


def _iter_plugin_sources(plugin_dir: Path) -> list[Path]:
    """Every shipped source file in ONE plugin, vendored/nested artifacts excluded.

    The walk is the WHOLE plugin directory, not a list of blessed subdirectory names. An earlier
    form walked only ``scripts``/``skills``/``commands``/``agents``/``hooks``/``references``, which
    quietly hid real shipped code: ``plugins/redis-channel/server/`` alone carries eleven production
    modules, and every plugin's ``tests/``, ``docs/`` and ``config/`` were invisible too. A guard
    that calls itself fleet-wide and then skips a directory because of its name is a guard with a
    hole shaped exactly like the next plugin's layout.
    """
    files: list[Path] = []
    if not plugin_dir.is_dir():
        return files
    for path in plugin_dir.rglob("*"):
        if not path.is_file() or path.suffix not in _SOURCE_SUFFIXES:
            continue
        if _EXCLUDED_SEGMENTS & set(path.relative_to(plugin_dir).parts):
            continue
        # The guard tests name the forbidden tokens in order to search for them.
        # They used to live outside ``plugins/``, so the scan never read its own
        # denylist. They now live in the package, and reading the denylist back
        # as an offense would make the guard fail on itself.
        if path.resolve() in _DENYLIST_SOURCES:
            continue
        files.append(path)
    return sorted(files)


def _iter_fleet_sources(plugins_root: Path = PLUGINS_ROOT) -> list[Path]:
    """Every shipped source file across the fleet, Mission Control's own plugin excluded."""
    files: list[Path] = []
    if not plugins_root.is_dir():
        return files
    for plugin_dir in sorted(p for p in plugins_root.iterdir() if p.is_dir()):
        if plugin_dir.name == EXECUTOR_PLUGIN_DIR:
            continue
        files.extend(_iter_plugin_sources(plugin_dir))
    return files


def _fenced_blocks(text: str) -> list[str]:
    """Every fenced block's body, whatever its info string.

    The language tag is matched permissively on purpose. A pattern that only recognises
    ``bash``/``sh``/``shell`` does not simply *skip* a ```` ```json ```` block — it fails to see the
    opening fence, then pairs that block's CLOSING fence with the next opening one, so the blocks
    after it are mis-paired and their contents silently drop out of the scan. Both skill files carry
    non-shell fences, so the permissive form is what makes this scan complete.
    """
    return re.findall(r"```[A-Za-z0-9_+.-]*\n(.*?)```", text, re.DOTALL)


def scan_direct_writes(plugins_root: Path = PLUGINS_ROOT) -> list[tuple[str, str]]:
    """Return (relative-path, reason) for every path that reaches GitHub's project fields directly.

    Two offense classes, per W-D1:

    * **Composes or executes a direct write** — any :data:`DIRECT_WRITE_SIGNATURES` match, in a
      fenced block of a skill or anywhere in a Python source. Mission Control alone may do this,
      and its plugin is out of scope.
    * **Names the lifecycle-field op with no submission seam** — a module that carries the op-kind
      vocabulary (literal or constant-resolved) while naming none of Mission Control's doors is
      composing a board write it cannot legally deliver.

    A submission is NOT an offense and is not returned here; :func:`scan_submissions` reports those.
    """
    offenses: list[tuple[str, str]] = []
    for path in _iter_fleet_sources(plugins_root):
        rel = str(path.relative_to(plugins_root))
        text = path.read_text(encoding="utf-8")
        haystacks = _fenced_blocks(text) if path.suffix == ".md" else [text]
        for pattern, reason in DIRECT_WRITE_SIGNATURES:
            if any(pattern.search(chunk) for chunk in haystacks):
                offenses.append((rel, reason))
                break
        if path.suffix != ".py":
            continue
        # Package tests quote the op-kind vocabulary while asserting the
        # contract. That mention is not a writer. A direct GitHub mutation in
        # a test is still an offense, and was already recorded above.
        if "tests" in path.relative_to(plugins_root).parts:
            continue
        resolved = path.resolve()
        if resolved in OP_KIND_CORE_FILES or resolved in OP_KIND_READ_SIDE_FILES:
            continue
        if SUBMISSION_SEAM_RE.search(text):
            continue
        if _PY_CONSTANT_COMPOSE_RE.search(text):
            offenses.append((rel, "composes a set-field-status op with no submission seam"))
        elif _MARKER in text:
            offenses.append((rel, "names set-field-status with no submission seam"))
    return sorted(offenses)


def scan_submissions(path: Path) -> list[str]:
    """Every fenced Mission Control submission block in one markdown source, in file order.

    Either spelling counts. A `--dry-run` block is excluded: it prints a move and writes nothing.
    """
    return [
        block
        for block in _fenced_blocks(path.read_text(encoding="utf-8"))
        if (FENCED_SUBMISSION_RE.search(block) or FENCED_BOUNDARY_RE.search(block))
        and not DRY_RUN_RE.search(block)
    ]


def scan_boundaries(path: Path) -> list[str]:
    """Every lifecycle boundary this skill SUBMITS, by name, in file order."""
    names: list[str] = []
    for block in _fenced_blocks(path.read_text(encoding="utf-8")):
        if DRY_RUN_RE.search(block):
            continue
        match = FENCED_BOUNDARY_RE.search(block)
        if match:
            names.append(match.group("boundary"))
    return names


def assignments_of(block: str) -> list[tuple[str, str]]:
    """The ``(field, option)`` assignments a fenced submission block carries, in argv order.

    Reads the ``assignments`` array out of the block's ``--payload`` JSON. A block that submits one
    assignment where the boundary owes a pair returns a one-element list, which is exactly the
    half-write the contract tests must be able to see.
    """
    return [
        (m.group(1), m.group(2)) for m in re.finditer(r'\[\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\]', block)
    ]


# The live (Stage, Status) pair each Saga skill boundary submits (#927 R1). Every pair below is a
# member of ``workflows.stage_flow.stage_statuses`` in mission-control's sdlc-schema.json — the
# board's own authority — and none of them is a retired token.
PLAN_SKILL = SAGA_ROOT / "skills" / "plan" / "SKILL.md"
WORK_SKILL = SAGA_ROOT / "skills" / "work" / "SKILL.md"

BOUNDARY_PAIRS: dict[Path, list[tuple[str, str]]] = {
    PLAN_SKILL: [("Planning", "Designing"), ("Planning", "Ready for Active")],
    WORK_SKILL: [
        ("Active", "Implementing"),
        ("Verify", "Awaiting verification"),
        ("Retro", "Ready to close"),
    ],
}

# Tokens the 0.145.0-era prose still named as Status values. None is an option on either live field,
# so any survivor submits a value Mission Control cannot resolve.
RETIRED_TOKENS = ("Idea", "Ready", "Done")

# The sentence the operator superseded on 2026-08-30. Its return would re-forbid the submission.
SUPERSEDED_PROHIBITION = "Do not run a reconcile tick"


# ---------------------------------------------------------------------------
# U1: the guard asserts the submit-versus-execute contract, fleet-wide
# ---------------------------------------------------------------------------


def test_saga_no_direct_write_fleet_composes_or_executes_nothing() -> None:
    """R3/R4: no path under ``plugins/`` composes or executes a board-field write."""
    offenses = scan_direct_writes()
    assert offenses == [], (
        "paths reach GitHub's project fields without Mission Control:\n"
        + "\n".join(f"  {path}: {reason}" for path, reason in offenses)
    )


def test_saga_no_direct_write_scan_covers_the_whole_fleet() -> None:
    """The scan root is the fleet, not one plugin — W7's one-plugin scan is why Orchestrate's
    leftover writer never failed this guard (#927). Proven by the plugins actually walked."""
    walked = {Path(str(p.relative_to(PLUGINS_ROOT))).parts[0] for p in _iter_fleet_sources()}
    present = {
        path.name
        for path in PLUGINS_ROOT.iterdir()
        if path.is_dir() and path.name != EXECUTOR_PLUGIN_DIR
    }
    assert present <= walked, f"the fleet scan missed a plugin: {sorted(present - walked)}"
    assert EXECUTOR_PLUGIN_DIR not in walked, "Mission Control is the executor and is out of scope"


def test_saga_no_direct_write_scan_reaches_beyond_the_conventional_directories() -> None:
    """The walk is the whole plugin directory, not a blessed list of subdirectory names.

    ``plugins/redis-channel/server/`` carries eleven production modules and every plugin's
    ``tests/`` holds real code; an earlier form of this scan walked six directory names and saw
    none of it. Pinned against the real tree so the hole cannot come back by convention.
    """
    walked = _iter_fleet_sources()
    parents = {str(path.relative_to(PLUGINS_ROOT).parent) for path in walked}
    # redis-channel's ``server/`` directory was the original non-conventional
    # example. This checkout may not carry that package yet. The Claude adapter
    # directory is the non-conventional directory saga itself now ships.
    nonconventional = (PLUGINS_ROOT / "redis-channel" / "server").is_dir()
    if nonconventional:
        assert any(part.startswith("redis-channel/server") for part in parents), (
            "the scan skipped a plugin's non-conventional source directory"
        )
    else:
        assert any("com.infiquetra.claude" in part for part in parents), (
            "the scan skipped saga's Claude adapter, a non-conventional source directory"
        )
    assert any("/tests" in part for part in parents), "the scan skipped plugin-local tests"
    assert any(path.suffix not in (".py", ".md") for path in walked), (
        "a mutation body can live in a .sh or .json file the scan must still read"
    )


def test_saga_no_direct_write_a_mere_mention_of_the_seam_does_not_exempt(tmp_path: Path) -> None:
    """Naming a door is not walking through it.

    A seam pattern matching the module name anywhere in the text lets a file exempt itself with a
    comment — "see reconcile_controller.py for the provenance of this" — while going on to compose
    its own write. The seam must be an invocation or an import.
    """
    plugins = tmp_path / "plugins"
    excused = plugins / "orchestrate" / "scripts" / "excused_by_a_comment.py"
    excused.parent.mkdir(parents=True)
    excused.write_text(
        "# See reconcile_controller.py and board_progression.py for the provenance of this\n"
        "# legacy fallback; unrelated in code.\n"
        'OP = "set-field-status"\n',
        encoding="utf-8",
    )
    routed = plugins / "orchestrate" / "scripts" / "genuinely_routed.py"
    routed.write_text(
        "# no mention of the module name at all, just the call\n"
        'record = authorize_and_write("set-field-status", "o/r", 1, "Implementing")\n',
        encoding="utf-8",
    )
    assert scan_direct_writes(plugins) == [
        (
            "orchestrate/scripts/excused_by_a_comment.py",
            "names set-field-status with no submission seam",
        )
    ]


def test_saga_no_direct_write_a_seeded_direct_write_outside_mission_control_is_reported(
    tmp_path: Path,
) -> None:
    """A module composing the projectV2 field mutation under ``plugins/orchestrate/`` IS reported —
    and the identical composition under ``plugins/mission-control/`` is NOT."""
    plugins = tmp_path / "plugins"
    offender = plugins / "orchestrate" / "scripts" / "evil_direct_writer.py"
    offender.parent.mkdir(parents=True)
    offender.write_text(
        'MUTATION = "mutation { updateProjectV2ItemFieldValue(input: $i) { clientMutationId } }"\n',
        encoding="utf-8",
    )
    executor = plugins / EXECUTOR_PLUGIN_DIR / "scripts" / "sdlc_manager.py"
    executor.parent.mkdir(parents=True)
    executor.write_text(offender.read_text(encoding="utf-8"), encoding="utf-8")

    assert scan_direct_writes(plugins) == [
        (
            "orchestrate/scripts/evil_direct_writer.py",
            "composes the projectV2 item-field mutation directly",
        )
    ]


def test_saga_no_direct_write_a_fenced_submission_is_legal_not_an_offense(tmp_path: Path) -> None:
    """The sanctioned submission — the thing W7's guard forbade — is reported as a submission."""
    plugins = tmp_path / "plugins"
    skill = plugins / "saga" / "skills" / "plan" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "```bash\n"
        "python3 plugins/saga/scripts/reconcile_controller.py reconcile \\\n"
        "  --op set-field-status --repo owner/repo --number 1 \\\n"
        '  --target-state Designing --payload \'{"assignments": '
        '[["Stage", "Planning"], ["Status", "Designing"]]}\'\n'
        "```\n",
        encoding="utf-8",
    )
    assert scan_direct_writes(plugins) == []
    blocks = scan_submissions(skill)
    assert len(blocks) == 1
    assert assignments_of(blocks[0]) == [("Stage", "Planning"), ("Status", "Designing")]


def test_saga_no_direct_write_excludes_nested_run_artifacts(tmp_path: Path) -> None:
    """False-red guard: a vendored checkout under ``.claude/agy/runs/**`` — carrying its own
    direct-write text — is NOT reported, while the genuine shipped offense still is."""
    plugins = tmp_path / "plugins"
    nested = (
        plugins
        / "saga"
        / "scripts"
        / ".claude"
        / "agy"
        / "runs"
        / "agy-0-6-1-proof"
        / "worktree"
        / "plugins"
        / "saga"
        / "scripts"
    )
    nested.mkdir(parents=True)
    (nested / "vendored_writer.py").write_text(
        'MUTATION = "updateProjectV2ItemFieldValue"\n', encoding="utf-8"
    )
    shipped_violation = plugins / "saga" / "skills" / "evil" / "SKILL.md"
    shipped_violation.parent.mkdir(parents=True)
    shipped_violation.write_text(
        "```bash\ngh project item-edit --id X --field-id Y --single-select-option-id Z\n```\n",
        encoding="utf-8",
    )
    hits = dict(scan_direct_writes(plugins))
    assert hits == {"saga/skills/evil/SKILL.md": "executes `gh project item-edit` directly"}, (
        f"nested run artifacts leaked into the scan (or the genuine hit vanished): {hits}"
    )


def test_saga_submits_at_every_plan_boundary() -> None:
    """R1: /plan submits its two lifecycle moves through Mission Control."""
    blocks = scan_submissions(PLAN_SKILL)
    assert len(blocks) == 2, f"skills/plan/SKILL.md must submit at 0.6 and 5.0; found {len(blocks)}"


def test_saga_submits_at_every_work_boundary() -> None:
    """R1: /work submits one move at each of its three lifecycle boundaries, and no more."""
    blocks = scan_submissions(WORK_SKILL)
    assert len(blocks) == 3, (
        "skills/work/SKILL.md must submit at build start, merge plus deploy and close; found "
        f"{len(blocks)}"
    )


def test_saga_work_submits_the_named_boundaries_and_not_review_acceptance() -> None:
    """Issue 1028: the boundary is what a caller names, and review acceptance has no move."""
    submitted = scan_boundaries(WORK_SKILL)
    assert "review-accepted" not in submitted, (
        "review acceptance has no row in the lifecycle repository's allowed submissions; the skill "
        "must print the absence, not submit a move"
    )
    for boundary in submitted:
        assert boundary in WORK_BOUNDARIES, f"/work submits an unknown boundary: {boundary}"
    assert "merge-and-deploy" in submitted and "close" in submitted, (
        f"/work must submit the merge-plus-deploy and close boundaries; found {submitted}"
    )


def test_saga_every_submission_carries_the_live_pair() -> None:
    """R1/Decision A: each fenced block carries BOTH assignments, and the pair is the live one.

    A single-assignment block is the false green this test exists for: ``Ready for Active`` is a
    legal ``Status`` on its own, so a Status-only submission looks like success while ``Stage``
    stays where it was.
    """
    for skill, expected in BOUNDARY_PAIRS.items():
        found = [
            assignments_of(block)
            for block in scan_submissions(skill)
            if FENCED_SUBMISSION_RE.search(block)
        ]
        for assignments in found:
            assert len(assignments) == 2, (
                f"{skill.name}: a submission carries {len(assignments)} assignment(s), not the pair: "
                f"{assignments}"
            )
            assert [f for f, _ in assignments] == ["Stage", "Status"], (
                f"{skill.name}: a submission names the wrong fields: {assignments}"
            )
        pairs = [(a[0][1], a[1][1]) for a in found]
        assert pairs == [pair for pair in expected if pair in pairs] and set(pairs) <= set(
            expected
        ), f"{skill.name}: submitted pairs {pairs} are not a prefix of R1's {expected}"


def test_saga_every_submitted_pair_is_live_on_the_board() -> None:
    """R1: every submitted pair is a member of the schema's own ``stage_statuses``."""
    schema = json.loads(
        (PLUGINS_ROOT / EXECUTOR_PLUGIN_DIR / "config" / "sdlc-schema.json").read_text(
            encoding="utf-8"
        )
    )
    stage_statuses = schema["workflows"]["stage_flow"]["stage_statuses"]
    live = {(stage, status) for stage, options in stage_statuses.items() for status in options}
    for skill, expected in BOUNDARY_PAIRS.items():
        for pair in expected:
            assert pair in live, f"{skill.name}: {pair} is not an option combination on the board"


def test_saga_no_boundary_reintroduces_the_superseded_prohibition() -> None:
    """W-D1: the sentence the operator superseded must not come back in either skill."""
    for skill in (PLAN_SKILL, WORK_SKILL):
        text = skill.read_text(encoding="utf-8")
        assert SUPERSEDED_PROHIBITION not in text, (
            f"{skill.name} still carries the superseded prohibition sentence"
        )


def test_saga_no_boundary_names_a_retired_token() -> None:
    """R1: no ``Status -> <retired token>`` prose survives in either skill's board-move sections."""
    arrow = re.compile(
        r"`?Status`?\s*(?:->|→)\s*`?(" + "|".join(RETIRED_TOKENS + ("Active", "Verify")) + r")`?"
    )
    for skill in (PLAN_SKILL, WORK_SKILL):
        hits = arrow.findall(skill.read_text(encoding="utf-8"))
        assert hits == [], f"{skill.name} still names retired Status tokens: {hits}"


def test_saga_the_non_field_operations_survive() -> None:
    """R30 governed Stage/Status only: /work's two non-field ops must be untouched."""
    work = WORK_SKILL.read_text(encoding="utf-8")
    assert "--op issue-progress-comment" in work, (
        "the non-field progress-comment op must survive (R30 governs fields only)"
    )
    assert "--op sub-issue-close" in work, (
        "the non-field sub-issue-close op must survive (an issue-state write, not a field write)"
    )


# ---------------------------------------------------------------------------
# Unchanged since W7: /loop stays correction-only and /outcome keeps no field authority
# ---------------------------------------------------------------------------
