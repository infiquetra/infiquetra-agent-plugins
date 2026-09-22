"""Contract tests for the saga plugin package."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = ROOT / "plugins" / "saga"
ADAPTER = PLUGIN_ROOT / "com.infiquetra.claude"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_module(script_name: str):
    path = PLUGIN_ROOT / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(script_name.removesuffix(".py"), path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _frontmatter_name(path: Path) -> str:
    lines = _read(path).splitlines()
    assert lines[0] == "---"
    for line in lines[1:]:
        if line.startswith("name: "):
            return line.removeprefix("name: ").strip()
    raise AssertionError(f"{path} has no frontmatter name")


def test_infiquetra_lifecycle_metadata_and_marketplace_entry_match() -> None:
    plugin_json = json.loads(_read(PLUGIN_ROOT / ".claude-plugin" / "plugin.json"))
    marketplace = json.loads(_read(ROOT / ".claude-plugin" / "marketplace.json"))
    entry = next(p for p in marketplace["plugins"] if p["name"] == "saga")

    assert plugin_json["name"] == "saga"
    # 1.2.2 carries three upstream tests the 1.2.1 import had omitted --
    # test_work_gate_integrity.py, test_work_prose_contracts.py and
    # test_capability_degrade.py from infiquetra-claude-plugins@acc99fe7 -- all targeting files
    # this package ships (saga.py, lifecycle_state.py, issue_progress.py, skills/work/SKILL.md).
    # No production behavior changed; the bump exists because this suite pins the manifest and
    # marketplace version literally, and every content change to the package re-reads it here.
    #
    # 1.2.1 is the authored-here cut: same upstream behavior, patch bumped so the
    # catalog's version is not the upstream pin.
    assert plugin_json["version"] == "1.2.2"  # 1.2.0: the three advisory review
    # judgments of issue #1034 — the conditional-lens proposal at declaration time
    # (review_roster.py --propose, additive only), finding dedupe groups and the severity
    # flag over results (review_result.py, grouped and attached, never applied). Bumped over
    # 1.1.0, the saga version on main at d899c6a0 (issue #1033's batched tier suggestions at
    # admission, merged the same day; both cards were cut from parent/1018 at 994443ea and both
    # chose 1.1.0, so the second to land re-bumped at merge time).
    #
    # Predecessor 1.1.0 was issue #1033: admission's opt-in --suggest flag runs the staffing
    # component's tier consult once per run and records each suggestion beside its default.
    #
    # Predecessor 1.0.0 was the removals of issue
    # #1030 — eleven commands and nine skills gone, four hooks deregistered and deleted, both saga
    # agents gone, and the sandbox-spawn project instruction replaced. Bumped over 0.172.0, the saga
    # version on origin/parent/1018 at b264f154, re-read at that merge turn. 0.172.0 was chosen from
    # the same base by issue #1039, which is why that card skipped it rather than colliding: two
    # cards writing an identical version string never conflict, and the collision merges silently.
    #
    # NOT 1.0.0, which the card names. 1.0.0 is that card's name for the complete release, and this
    # is not it: the script families are still here, blocked on the cc-workflows finding recorded in
    # docs/work-sessions/2026-09-20-issue-1030-removals-and-release.md. A version says what shipped,
    # and taking 1.0.0 now would leave the complete release with no number to be.
    #
    # Predecessor 0.172.0 was issue #1039: /qa becomes the lifecycle's functional test — ten
    # prescribed strategies as data, a per-repository profile, a widen-only advisory judgment,
    # three-status drivers, one evidence envelope each in the run record, and a counted verdict.
    # The health score and its test are removed; the release step no longer reports a blocked
    # scenario as a pass.
    #
    # Predecessor 0.171.0 was issue #1028: the merge turn, the release step, the
    # lifecycle-boundary board interface and the allowed-submission enforcement. That card and issue
    # #1027 BOTH took 0.170.0 against 23959a80, and the collision merged silently: two cards
    # writing an identical version string never conflict, so the manifest and the marketplace entry
    # came through clean and the only signal was two bodies under one changelog heading.
    # Predecessor 0.170.0 was issue #1027: /work becomes the build loop — the exit criterion is
    # written in the run record at admission and read rather than judged, and build_loop.py runs it
    # and records every result under the unit row's `build_loop` key. The five ship-ceremony
    # modules are removed with their tests, the hook entry and their importers.
    # Predecessor 0.169.0 was issue #1029: every lifecycle skill ends by doing the next step in the
    # same turn, a SessionStart hook announces the run record's next_step for a live run and
    # nothing for a done step, a closed run, or no record, and a local-only UserPromptSubmit hook
    # names the command an operator's text is about.
    # Predecessor 0.168.0: the run record reference documents the
    # `units` rows as an extension point and names the three keys the orchestrate plugin adds to a
    # unit row (issue #1025).
    # Predecessor 0.167.0: Work no longer offers an in-process external-engine second opinion; the
    # offer's prose and routing leave the work skill and its continuation reference, and
    # plugins/saga/scripts/second_opinion.py is deleted with no live consumer, while the
    # external-content trust boundary survives with its guard narrowed to the one remaining call
    # site (issue #938).
    # Predecessor 0.166.0: /plan ends by dispatching the plan
    # review to the Plan Reviewer and looping on repair until no P0 or P1 remains, the /work floor
    # gate stays blocking on the operator's one-word override alone, the Workflow-backend and
    # team-execution prose moves to references/workflow-backend.md, and team_emitter.py and
    # spec_table.py are removed (issue #1026). Bumped from 0.165.0, the saga version on
    # origin/parent/1018 at 542e9810: issue #1001 took 0.165.0 while this card's suite ran, so this
    # card renumbered above it rather than shipping a colliding version.
    # Predecessor 0.165.0: code review becomes a policy-free
    # executor -- it reads the lens declaration from the run record, resolves review_roster.v1 with
    # the lifecycle repository's own generator, computes the verdict from that catalogue's
    # strictness ladder, writes review_result.v2 into the run record, and publishes exactly one
    # pull-request comment and never an approving review. The plugin's private fourteen-lens
    # roster is deleted (issue #1001). Bumped from 0.164.0, the saga version on
    # origin/parent/1018 at 4e951f0e.
    # Predecessor 0.164.0: /work and /code-review stand role and
    # lens-reviewer sessions up through agent-launcher's roster helper, which closes only the panes
    # the run record says it created (issue #1024).
    # Predecessor 0.163.0: one JSON run record per issue,
    # outside every worktree and addressed by an absolute path, plus the admission questionnaire
    # asked once at the front of /plan issue (issue #1023). Bumped from 0.161.0, the saga version
    # on origin/parent/1018 at 550ae6ce; the fold of main into that branch then renumbered the
    # tier-overlay release to 0.162.0, which 0.163.0 still clears.
    # Predecessor 0.162.0: the per-repository tier overlay
    # reads through one implementation in fleet-core (issue #1021); renumbered from 0.161.0
    # when main was folded into parent/1018.
    # Predecessor 0.161.0: shaping_judgments.py asks the eleven advisory typed judgments inside
    # /ideate, /brainstorm and /office-hours through the fleet-core TypeSafe client (issue #1037).
    # Predecessor 0.160.0: parse_issue.py gains --flags and
    # --issue, which widen the five keyword flags with a model judgment (widen-only: a keyword
    # flag stays set whatever the model answers) and report the seven approval boundaries
    # advisorily; the journal-nudge hook asks the same way when the feat/fix prefix did not
    # already nudge, stays silent on any failure, and never blocks (issue #1036).
    # Predecessor 0.159.3: plan_save_proof.py carries a
    # command-line entrypoint that names the proof and the command that runs it, serves it at
    # exit 0 for --help, and refuses every other direct invocation at exit 2 with an empty
    # stdout; PyYAML moved to its point of use so that --help works without it (issue #998).
    # Predecessor 0.159.2: plan_save_contract.py imports
    # PyYAML at first use instead of at module scope, so an interpreter without it gets the
    # documented refusal rather than a traceback at the drift exit code, and --help still
    # works (issue #997). Predecessor 0.159.1: a BaseException raised by the
    # checkout that plan_save_contract.py executes stays inside the JSON envelope, at both
    # seams where that code runs (issue #996). Predecessor 0.159.0: accepted-result consistency
    # and lifecycle-namespaced fix identifiers (issue #908 children #894, #899).
    # Predecessor 0.158.0: shared Saga readiness owner with
    # Mission Control delegation (issue #942). Predecessor — issue #926 (unit P5, issue #918
    # Wave Two):
    # Plan's documentation corrections -- the derived-state sentence, the board-move trigger
    # clause, the effort-emission comment's native-vs-proxy description, and the saga-spec
    # /plan consumer row -- plus the two drift checks that keep them from relapsing.
    # Successor to the cycle-2 repair of the integrated review's
    # WK2-WK4 findings: the /qa preamble and certificate comment issue #930 named, the halt/allowlist
    # attribution, a CLI for the build-unit tier resolver, validation of an explicit plan tier, and
    # three guard tests that could not fail. Successor to issue #930's maintenance sweep at 0.154.0
    # — teardown as fifth ceremony call, first-time move, gated/allowlist separation,
    # and the full artifact_pointer path.
    # Successor to issue #929's build-unit tier resolution at 0.153.0
    # Successor to issue 912's handoff envelope schema 1.1 at 0.156.0, which took that
    # version on origin/main while this branch was in review; the bump is re-derived
    # from the current origin/main tip.
    assert entry["version"] == plugin_json["version"]
    assert entry["source"] == "./plugins/saga"
    assert "lifecycle" in plugin_json["description"]
    # "handoff" and "optimize" were in the manifest's keywords until issue 1030 removed both
    # commands. The keywords are a search surface, so they must not advertise a command that is
    # gone; this set names five that survive.
    assert {"lifecycle", "strategy", "plan", "doc-review", "code-review"} <= set(
        plugin_json["keywords"]
    )


def test_fleet_lease_runtime_adapters_are_retired_from_the_package() -> None:
    # #677/U5: the saga broker wrapper and the lease lifecycle hook are deleted outright, and
    # the plugin loads with no lease hook registered. No mutation hook either, since #671: its
    # write fence was a no-op for every spawn without a declared worktree, and concurrent-writer
    # collisions are prevented at emit by wave_file_conflicts().
    assert not (PLUGIN_ROOT / "scripts" / "lease_broker.py").exists()
    assert not (ADAPTER / "hooks" / "lease_lifecycle_hook.py").exists()
    assert not (ADAPTER / "hooks" / "lease_mutation_hook.py").exists()
    hooks_json = json.loads(_read(ADAPTER / "hooks" / "hooks.json"))
    commands = [
        hook["command"]
        for entries in hooks_json["hooks"].values()
        for group in entries
        for hook in group["hooks"]
    ]
    assert not any("lease" in command for command in commands)


def test_office_hours_two_mode_and_hard_gate_contract() -> None:
    """Structural contract for the rebuilt two-mode frame-finding office-hours engine.

    Tokens are chosen from the actual authored SKILL.md / frame-diagnostic.md so the
    assertions track the contract, not fragile prose. See E1-authored office-hours skill.
    """
    skill_doc = _read(PLUGIN_ROOT / "skills" / "office-hours" / "SKILL.md")
    diagnostic_doc = _read(
        PLUGIN_ROOT / "skills" / "office-hours" / "references" / "frame-diagnostic.md"
    )
    combined = skill_doc + "\n" + diagnostic_doc

    # Both modes are present as named modes in the SKILL or its reference.
    assert "Startup mode" in combined
    assert "Builder mode" in combined

    # HARD GATE intent: office-hours diagnoses and routes; it never implements/plans/
    # scaffolds/files an SDLC issue. Both the stable token and the no-implementation
    # phrasing the author used must be present.
    assert "HARD GATE" in skill_doc
    assert "never file an SDLC issue" in skill_doc

    # Office-hours must NOT name "SDLC issue" as one of ITS outputs (the old 23-line stub
    # did: "End with the next useful artifact: ... SDLC issue"). The rebuild must not carry
    # that artifact-list phrasing.
    assert "next useful artifact" not in skill_doc

    # Routing targets are present (these are not the only exits, but all must appear).
    for route in ("/ideate", "/brainstorm", "/plan", "/strategy"):
        assert route in skill_doc

    # Frame-note home is its own directory.
    assert "docs/office-hours/" in skill_doc


def test_work_engine_merge_contract() -> None:
    """Mechanism-floor contract for the rebuilt engine-merge /work engine (0.10.0).

    These are MECHANISM floors, not noun-lists (DA-M10): a vibes reskin of the prior
    39-line facilitator stub MUST fail. Each floor pins a runnable wiring the rebuild
    exists to land — a literal saga write with the work-phase + round flags, the runnable
    backend-recommendation CLI, the total PR-state read, the computed staleness command,
    the extended issue-progress CLI call, and the saga-identity handoff into /code-review.
    Presence-of-phrase checks are demoted to a secondary block at the end.

    Tokens are taken from the actual E1-authored SKILL.md + its 3 references on disk.
    """
    work = PLUGIN_ROOT / "skills" / "work"
    skill_doc = _read(work / "SKILL.md")
    exec_doc = _read(work / "references" / "execution-strategy.md")
    gates_doc = _read(work / "references" / "test-and-gates.md")
    loop_doc = _read(work / "references" / "pr-continuation-loop.md")
    # The runnable backend CLI line lives in the execution-strategy ref; the SKILL points
    # at it. Mechanism floors are asserted against whichever surface actually carries them.
    corpus = "\n".join((skill_doc, exec_doc, gates_doc, loop_doc))

    # --- MECHANISM FLOOR 1: a literal runnable saga write minting the work-thread saga ---
    # /work is the saga's primary writer; the minted thread must carry the work lifecycle
    # phase AND the round axis (--rounds-seen, never the derived next_round). A stub names
    # neither. Pin a single literal `saga.py save` invocation that contains both flags so a
    # bare "writes a saga" mention cannot satisfy the floor.
    save_blocks = re.findall(r"saga\.py save.*?(?=\n#|\n```|\Z)", skill_doc, flags=re.DOTALL)
    assert any(
        "--lifecycle-phase work" in block and "--rounds-seen" in block for block in save_blocks
    ), (
        "SKILL must contain a runnable `saga.py save` carrying --lifecycle-phase work AND --rounds-seen"
    )

    # --- MECHANISM FLOOR 2: a literal recommend-backend CLI invocation with >= 1 flag ---
    # The deferred helper lands here; the engine must EMIT a runnable CLI call, not just name
    # the function. Require the subcommand followed (same or continued line) by >= 1 --flag.
    assert re.search(
        r"recommend-backend(?:[^\n]*\\\n[^\n]*|[^\n]*)--\w",
        corpus,
    ), "engine must emit a runnable `recommend-backend` CLI invocation with at least one flag"

    # --- MECHANISM FLOOR 3: the total PR --json read (state + reviewDecision + check status) ---
    # The round-N loop is driven by a TOTAL read of live PR state. A `gh pr view --json` that
    # omits reviewDecision or the check-status field cannot drive the transition table.
    pr_json_lines = [
        line for line in corpus.splitlines() if "gh pr view" in line and "--json" in line
    ]
    assert pr_json_lines, "engine must read live PR state via `gh pr view --json`"
    assert any("state" in line for line in pr_json_lines)
    assert any("reviewDecision" in line for line in pr_json_lines)
    assert any(
        ("mergeStateStatus" in line or "statusCheckRollup" in line) for line in pr_json_lines
    ), (
        "the PR --json read must include a check-status field (mergeStateStatus or statusCheckRollup)"
    )

    # --- MECHANISM FLOOR 4: the computed staleness check (git rev-list ...HEAD) ---
    # Staleness is computed, not stored (DA-H6): commits since the reviewed SHA via
    # `git rev-list <sha>..HEAD`. A stub has no such computation.
    assert re.search(r"git rev-list\s+\S*\.\.HEAD", corpus), (
        "engine must compute review staleness via `git rev-list <reviewed_sha>..HEAD`"
    )

    # --- MECHANISM FLOOR 5: the EXTENDED issue_progress.py CLI call (--commit-sha + --checks-run) ---
    # DA-C1: the Phase-4 comment must invoke the now-extended CLI with the real evidence flags.
    progress_blocks = re.findall(r"issue_progress\.py.*?(?=\n#|\n```|\Z)", corpus, flags=re.DOTALL)
    assert any("--commit-sha" in block and "--checks-run" in block for block in progress_blocks), (
        "engine must call the extended issue_progress.py CLI with --commit-sha AND --checks-run"
    )

    # --- MECHANISM FLOOR 6: the forward-coupling write + the in-loop gate ---
    # The corrected coupling (DA-C3, hardened after the build review): /work mints a FINDABLE saga
    # (sets --issue-ref, the saga-spec §11 issue_ref-adoption write + a code-review match key) that a
    # standalone /code-review can append to; for its OWN gate /work runs /code-review programmatically and
    # reads the envelope directly, capturing the reviewed SHA itself (git rev-parse HEAD) — no dependency
    # on code-review writing an artifact (it writes none in programmatic mode).
    assert any("--issue-ref" in block for block in save_blocks), (
        "the mint must set --issue-ref (the saga-spec §11 issue_ref-adoption write + code-review match key)"
    )
    assert "/code-review" in skill_doc
    assert "programmatic" in skill_doc, (
        "the /code-review call must be the programmatic/report-only mode"
    )
    assert "git rev-parse HEAD" in corpus, (
        "/work must capture the reviewed SHA itself (git rev-parse HEAD) for the staleness gate"
    )

    # --- MECHANISM FLOOR 7: each of the 3 reference files carries real content (>= 60 lines) ---
    # Blunt thin-port tripwire — a vibes reskin would leave the refs as stubs.
    for ref in ("execution-strategy.md", "test-and-gates.md", "pr-continuation-loop.md"):
        ref_path = work / "references" / ref
        assert ref_path.exists()
        assert len(_read(ref_path).splitlines()) >= 60

    # --- SECONDARY (presence-of-phrase, demoted): boundary + adapted-source markers ---
    # Hard boundary negatives: merge under confirmation, no deploy/canary ownership, no
    # lifecycle advance past work. These are intent markers, not mechanism floors.
    assert "deploy" in corpus  # deploy mutation is delegated, not owned
    assert "mission-control" in corpus  # issue comments routed out, not filed by /work
    assert "Parallel Safety Check" in corpus  # CE execution mechanics carried
    # The canonical change-kind gate was the floor here until issue #1027 removed it. What
    # replaced it is the written exit criterion, so the floor moves with it: naming the runner and
    # its record block is the same class of check -- a mechanism a vibes reskin could not satisfy --
    # about the thing that now decides when the work is done.
    assert "build_loop.py" in corpus  # the runner that executes the written criterion
    assert "exit criterion" in corpus.lower()  # the criterion itself, read rather than judged
    assert "requires_hard_test_gate" not in corpus  # the removed gate must not creep back
    assert "merge-base" in corpus.lower()  # gstack merge-base-before-tests carried
    # qa/resume routing is advisory and lifecycle does not advance past work.
    assert "advisor" in corpus.lower()  # advisory qa/resume routing
    assert "lifecycle_phase" in corpus  # the phase the engine deliberately does not advance


def test_document_review_second_opinion_contract_is_intact() -> None:
    """Issue #394 gave each review surface its own advisory block, never a shared schema.

    Issue #1001's rewrite removed Code Review's half along with the prose it pinned -- none of
    its seven tokens survives the rewrite -- so only Document Review's half is asserted here.
    The negative at the end is issue #1026's card-931 repair: the reference that used to be
    asserted as a *path string* pointed at a file defining neither name it cited.
    """
    doc_skill = _read(PLUGIN_ROOT / "skills" / "doc-review" / "SKILL.md")

    for token in (
        "stable `D1..Dn`",
        "`D<N>`",
        "external_opinion.state=recommended",
        "Never auto-dispatch",
        "late-result ingestion",
        "Claude-owned final priority/status",
    ):
        assert token in doc_skill
    assert "../code-review/references/findings-schema.md" not in doc_skill, (
        "the dangling cross-reference came back; see card 931"
    )


def test_qa_functional_test_step_contract() -> None:
    """Mechanism FLOORS for the /qa functional-test step: the prescribed strategy catalogue (#1039).

    RETARGETED, not deleted. This guard used to pin the nine-way risk router, the ship verdicts,
    the model-assigned severity bands and the runnable `qa_health_score.py` scorer. Issue 1039
    removed every one of those, so a guard that still asserted them would have blocked the change
    it was meant to protect. It now pins what replaced them, at the same strength: the catalogue as
    data, the profile, the three result values, the counted verdict, the routing split between a
    failure and a block, and the absence of any score.

    HONEST SCOPE: presence proves the contract was AUTHORED, not that a given run respects it.
    "Never fix / never commit / never deploy" is enforced by Claude reading the prose at runtime;
    what these floors prove is that the documents EMIT the runnable lines the step stands on, that
    the boundary prose is present with mutation verbs only inside negation windows, and that the
    removed model — score, severity, ship verdicts, nine-way router — is gone from the corpus
    rather than merely unused.

    Tokens are taken from the actual SKILL.md + its 2 references on disk.
    """
    qa = PLUGIN_ROOT / "skills" / "qa"
    skill_doc = _read(qa / "SKILL.md")
    catalogue_doc = _read(qa / "references" / "qa-catalogue-reference.md")
    evidence_doc = _read(qa / "references" / "qa-evidence-and-verdict.md")
    corpus = "\n".join((skill_doc, catalogue_doc, evidence_doc))

    # --- MECHANISM FLOOR 1: one runnable command, not a procedure to reproduce by hand. ---
    assert "qa_strategies.py" in skill_doc, (
        "the SKILL must emit the runnable strategy runner `qa_strategies.py`"
    )
    run_blocks = re.findall(r"qa_strategies\.py.*?(?=\n#|\n```\s|\Z)", corpus, flags=re.DOTALL)
    assert any("--issue" in block for block in run_blocks), (
        "the runner invocation must carry --issue (the run whose record it reads and writes)"
    )
    assert any("--boundary" in block for block in run_blocks), (
        "the SKILL must show the --boundary flag: one runner serves the build loop's narrower "
        "proof boundary as well as the functional test's"
    )
    for subcommand in ("select", "run", "verdict"):
        assert re.search(rf"qa_strategies\.py {subcommand}\b", corpus), (
            f"the {subcommand!r} subcommand must be shown"
        )

    # --- MECHANISM FLOOR 2: the catalogue is DATA, and all ten rows are named. ---
    assert "qa-catalogue.yaml" in corpus, "the catalogue file must be cited by path"
    ten = (
        "api-workflow",
        "contract-check",
        "app-ui",
        "hosted-surface",
        "cli-smoke",
        "deploy-boundary",
        "data-check",
        "infrastructure-read-back",
        "installed-surface",
        "manual-runbook",
    )
    for strategy in ten:
        assert strategy in corpus, f"strategy {strategy!r} must be named in the corpus"
    # The data file itself carries exactly those ten and no eleventh.
    catalogue = yaml.safe_load(
        (PLUGIN_ROOT / "references" / "qa-catalogue.yaml").read_text(encoding="utf-8")
    )
    assert {row["id"] for row in catalogue["strategies"]} == set(ten)
    assert len(catalogue["strategies"]) == 10

    # --- MECHANISM FLOOR 3: three result values, and the corpus says there is no fourth. ---
    for result in ("passed", "failed", "blocked"):
        assert result in corpus, f"the result value {result!r} must be named"
    assert re.search(r"no fourth value|there is no fourth", corpus, re.IGNORECASE), (
        "the corpus must state that the three result values are the whole set"
    )

    # --- MECHANISM FLOOR 4: the counted verdict, in the post-deploy vocabulary. ---
    for verdict in ("pass-with-proof-debt", "fail"):
        assert verdict in corpus, f"the verdict {verdict!r} must be named"
    assert re.search(r"`pass`", corpus), "the verdict 'pass' must be named"
    # The ship-shaped words describe a decision this step no longer makes. They may appear only
    # where the corpus explains what was REPLACED, never as this step's own verdict.
    flat_corpus = re.sub(r"\s+", " ", corpus)
    for gone in ("ship-with-deferred", "no-ship"):
        for match in re.finditer(re.escape(gone), flat_corpus):
            window = flat_corpus[max(0, match.start() - 1400) : match.start()]
            assert re.search(
                r"What replaced what|replaced|used to|no longer", window, re.IGNORECASE
            ), f"the retired verdict {gone!r} may appear only in the what-replaced-what window"

    # --- MECHANISM FLOOR 5: the score, the severity model and the nine-way router are GONE. ---
    assert "qa_health_score" not in corpus, "the deterministic scorer is removed, not renamed"
    assert "Health Score Rubric" not in corpus
    for match in re.finditer(r"(?i)health score", flat_corpus):
        window = flat_corpus[max(0, match.start() - 1400) : match.start()]
        assert re.search(
            r"What replaced what|replaced|used to|no longer|gone", window, re.IGNORECASE
        ), "the health score may be named only where the corpus records that it was removed"
    assert "9-way risk router" not in corpus, "the nine-way risk router is removed, not renamed"
    assert "risk-taxonomy.md" not in corpus, (
        "the risk taxonomy reference was renamed into the catalogue reference; no path may still "
        "cite the old name"
    )
    assert re.search(r"no severity|nothing assigns a severity", corpus, re.IGNORECASE), (
        "the corpus must state that nothing assigns a severity"
    )
    assert re.search(r"Nothing is scored|no score", corpus, re.IGNORECASE), (
        "the corpus must state that nothing is scored"
    )

    # --- MECHANISM FLOOR 6: the widen-only rule, in both directions. ---
    assert re.search(r"may only widen|only widen|never narrow", corpus, re.IGNORECASE), (
        "the advisory judgment's widen-only rule must be stated"
    )
    assert re.search(r"never remove|may never remove", corpus, re.IGNORECASE), (
        "the corpus must say the judgment may never remove a declared strategy"
    )
    assert re.search(r"act band", corpus, re.IGNORECASE), (
        "the act band must be named as a declared number, not a literal in code"
    )

    # --- MECHANISM FLOOR 7: the two profile refusals — never an empty selection that passes. ---
    assert ".saga-profile.json" in corpus, "the profile must be cited by path"
    assert re.search(r"all optional", corpus, re.IGNORECASE), (
        "a profile whose strategies are all optional must be documented as blocked"
    )
    assert re.search(r"never an empty selection", corpus, re.IGNORECASE), (
        "the corpus must say a missing profile is blocked rather than an empty selection"
    )

    # --- MECHANISM FLOOR 8: the ROUTING SPLIT — a failure and a block go to different places. ---
    assert "build loop" in corpus, "a failure must route to the build loop"
    assert re.search(
        r"required[^\n.]*block(?:ed)?[^\n.]*operator|operator[^\n.]*required[^\n.]*block",
        flat_corpus,
        re.IGNORECASE,
    ), "a required blocked strategy must route to the operator"
    assert re.search(
        r"(?:no|never|cannot|which no)[^.]*build loop[^.]*repair|build loop[^.]*(?:cannot|never|no)[^.]*repair",
        flat_corpus,
        re.IGNORECASE,
    ), "the corpus must say WHY a block does not go to the build loop"
    # The exit codes are the routing decision in numeric form, and 4 and 5 are distinct.
    assert re.search(r"\| 4 \|", skill_doc) and re.search(r"\| 5 \|", skill_doc), (
        "the SKILL must document distinct exit codes for a failure and a required block"
    )

    # --- MECHANISM FLOOR 9: evidence is an ENVELOPE in the run record, and the ledger is gone. ---
    assert "evidence_ledger" not in corpus, (
        "the evidence-custody ledger call must be gone from the qa corpus"
    )
    assert "qa-envelope.schema.json" in corpus, "the envelope schema must be cited by path"
    assert re.search(r"run record", corpus, re.IGNORECASE), (
        "the envelopes' home — the run record — must be named"
    )
    assert re.search(r"before the envelope exists", corpus, re.IGNORECASE), (
        "redaction must be documented as happening INSIDE the driver, before the envelope exists"
    )

    # --- MECHANISM FLOOR 10: the published comment, which is what makes the run legible. ---
    assert "gh issue comment" in skill_doc, (
        "the SKILL must emit the runnable line that publishes the per-strategy statuses"
    )

    # --- MECHANISM FLOOR 11: reports-never-repairs, via POSITIVE-BOUNDARY-PROSE + NEGATION-WINDOW.
    for negative in (
        "does **NOT** fix",
        "does **NOT** commit",
        "does **NOT** push",
        "does **NOT** deploy",
    ):
        assert negative in skill_doc, f"boundary prose {negative!r} must be present"
    assert "merge a PR" in skill_doc and "does **NOT**" in skill_doc

    # Negation-window: "push" is the unambiguous mutation verb in this corpus, so every occurrence
    # must sit inside a negation window (the /resume + /founder-review pattern). "commit" is
    # excluded because it doubles as the benign noun "merge commit"; its boundary is pinned by the
    # positive prose above plus the no-runnable-mutation asserts below.
    flat_skill = re.sub(r"\s+", " ", skill_doc)
    for match in re.finditer(r"\bpushe?[sd]?\b", flat_skill, flags=re.IGNORECASE):
        window = flat_skill[max(0, match.start() - 70) : match.start()]
        assert re.search(r"\b(not|never|without|no)\b", window, flags=re.IGNORECASE), (
            f"mutation verb 'push' must only appear inside a negation window, "
            f"found positive use near: {flat_skill[match.start() - 50 : match.start() + 30]!r}"
        )

    # No runnable mutation command anywhere.
    assert not re.search(r"(?<!Never )(?<!never )`?git commit", skill_doc)
    assert "git push" not in skill_doc
    assert "gh pr merge" not in skill_doc and "gh pr create" not in skill_doc
    # Every `git add` occurrence is a "Never git add" negation (the run record is git-ignored).
    for match in re.finditer(r"git add", flat_corpus):
        window = flat_corpus[max(0, match.start() - 30) : match.start()]
        assert re.search(r"\bNever\b", window), (
            "any `git add` mention must be inside a 'Never git add' negation"
        )

    # --- MECHANISM FLOOR 12: outbound routing is DEFERRED, never restated. ---
    # Until issue 1030 this floor required the skill to cite
    # `loop/references/dispatch-table.md` by path. That table left with `/loop`, and the floor
    # outlived it pinned to a path that no longer resolves: a guard that requires a dangling
    # reference is why the rewritten skill kept pointing at a deleted file. The floor's real
    # subject is that `/qa` does not carry its own copy of the routing map, so that is what is
    # checked now, plus the positive half — the skill still says where the next step comes from.
    assert "loop/references/dispatch-table.md" not in corpus, (
        "the dispatch table left with /loop; a reference to it no longer resolves"
    )
    assert "# Dispatch Table" not in corpus, (
        "the dispatch-table H1 title must not be restated in /qa"
    )
    assert "The designed routing map for `/loop`" not in corpus
    assert "run record" in skill_doc.lower(), (
        "outbound routing must name where the next step is read from"
    )

    # --- MECHANISM FLOOR 13: the two strategies declared WITHOUT a driver say so, with the
    # condition that reopens each. A narrowing declared openly is not the same as a silent gap. ---
    for narrowed in ("app-ui", "hosted-surface"):
        row = next(r for r in catalogue["strategies"] if r["id"] == narrowed)
        assert row["driver"] is None
        assert row["no_driver_reason"].strip()
        assert row["revisit_when"].strip()
    assert re.search(r"ships no driver|declared without a driver", corpus, re.IGNORECASE), (
        "the corpus must say out loud which strategies ship no driver"
    )

    # --- ref-floor: both reference files exist and carry real content (>= 60 lines). ---
    for ref in ("qa-catalogue-reference.md", "qa-evidence-and-verdict.md"):
        ref_path = qa / "references" / ref
        assert ref_path.exists()
        assert len(_read(ref_path).splitlines()) >= 60


def test_strategy_engine_merge_contract() -> None:
    """Mechanism FLOORS for the rebuilt engine-merge /strategy direction anchor (0.14.0).

    HONEST SCOPE: presence proves the contract was AUTHORED, not that runtime is mutation-free.
    /strategy's identity is that it RECORDS direction (the records member of the
    record-vs-challenge-vs-readiness trio) — so the engine-identity verbs "record"/"anchor" are
    NEVER negation-windowed; the whole positive point of the engine is that it records direction.
    The records-not-implements boundary is enforced only by Claude reading the prose at runtime —
    the SKILL emits no runnable mutation command, but token presence cannot prove a given run
    respects the boundary. These floors prove the SKILL/refs EMIT the prose the engine stands on
    (Phase-0 file-state routing, the locked-template constraints, the pushback discipline, the
    Infiquetra agent-as-customer / tracks-are-not-actors deltas, the downstream routing), that the
    boundary prose is present (with mutation verbs only inside negation windows, like /qa,
    /resume, and /founder-review), that the ce-* downstream names appear ONLY inside a faithful
    attribution window, and that the dispatch table is referenced not restated. A thin port that
    transcribes weak answers (no pushback, no anti-patterns, no locked constraints) fails these.

    Tokens are taken from the actual E1-authored SKILL.md + its 2 references on disk.
    """
    strategy = PLUGIN_ROOT / "skills" / "strategy"
    skill_doc = _read(strategy / "SKILL.md")
    interview_doc = _read(strategy / "references" / "interview.md")
    template_doc = _read(strategy / "references" / "strategy-template.md")
    corpus = "\n".join((skill_doc, interview_doc, template_doc))

    # --- MECHANISM FLOOR 1: Phase-0 file-state routing — the 3 distinct paths. The engine
    # branches on the root STRATEGY.md's existence (first-run / targeted-section / ask-which),
    # not a single linear interview. A stub has no routing. ---
    assert "Phase 0" in skill_doc, "the engine must route by file state in a Phase 0"
    assert re.search(r"(?:does not exist|not found|first run)", skill_doc, re.IGNORECASE), (
        "Phase 0 must route the file-absent path (first run)"
    )
    assert re.search(r"File exists.*?argument", skill_doc, re.DOTALL), (
        "Phase 0 must route the file-exists + named-section path (targeted update)"
    )
    assert re.search(r"File exists.*?no argument", skill_doc, re.DOTALL), (
        "Phase 0 must route the file-exists + no-argument path (ask which section to revisit)"
    )

    # --- MECHANISM FLOOR 2: the 8 section names live in the interview / template corpus (the
    # locked document structure), NOT in a generated STRATEGY.md (the engine writes that at
    # runtime; the contract is over the AUTHORED skill, not its output). ---
    sections = (
        "Target problem",
        "Our approach",
        "Who it's for",
        "Key metrics",
        "Tracks",
        "Milestones",
        "Not working on",
        "Marketing",
    )
    for section in sections:
        assert section in interview_doc or section in template_doc, (
            f"section {section!r} must be present in the interview/template corpus"
        )

    # --- MECHANISM FLOOR 3: the pushback discipline — the 2-round rule, >= 3 named anti-patterns,
    # and the core-of-the-skill / do-not-skip enforcement. A passive transcription has none of it. ---
    assert re.search(r"two rounds?|two-round", corpus, re.IGNORECASE), (
        "the interview must cap pushback at two rounds per section"
    )
    # >= 3 named anti-patterns (one per family the interview names: vanity / feature-list /
    # goal-as-problem). These are the canonical bad-strategy shapes Rumelt flags.
    for anti_pattern in ("vanity", "feature-list", "goal-as-problem"):
        assert anti_pattern in interview_doc, (
            f"the interview must name the {anti_pattern!r} anti-pattern"
        )
    # The two-round pushback is explicitly framed as the core of the skill that must not be skipped.
    assert "core of the skill" in interview_doc, (
        "the interview must frame the pushback as the core of the skill"
    )
    assert re.search(r"do not skip|don't skip|never .*skip", interview_doc, re.IGNORECASE), (
        "the interview must forbid skipping the pushback / a question"
    )

    # --- MECHANISM FLOOR 4: the locked-template constraints — 3-5 metrics AND 2-4 tracks. The
    # template is constrained on purpose (short is a feature); a vibes port drops the ceilings. ---
    assert "3-5 metrics" in corpus or re.search(r"3-5\b[^\n]*metric", corpus), (
        "the locked template must constrain metrics to 3-5"
    )
    assert "2-4 tracks" in corpus or re.search(r"2-4\b[^\n]*track", corpus), (
        "the locked template must constrain tracks to 2-4"
    )

    # --- MECHANISM FLOOR 5: the artifact is the ROOT STRATEGY.md, and `docs/STRATEGY.md` must
    # NOT appear as a write target (the file is a repo-root well-known peer of README.md, not a
    # docs/ artifact — getting the path wrong breaks every downstream grounding read). ---
    assert "root `STRATEGY.md`" in skill_doc or "repository root `STRATEGY.md`" in skill_doc, (
        "the durable artifact must be the repository-root STRATEGY.md"
    )
    assert "docs/STRATEGY.md" not in corpus, (
        "STRATEGY.md is a repo-root well-known file, never a docs/ artifact"
    )

    # --- MECHANISM FLOOR 6: the Infiquetra deltas — the agent-as-customer persona adaptation AND
    # tracks-are-investment-areas (no actor-naming). These are the two adaptations the port adds
    # on top of the ported ce-strategy rulebook; a faithful port carries both. ---
    assert "agent-as-customer" in corpus, (
        "the persona section must carry the agent-as-customer adaptation"
    )
    assert re.search(r"AI-agent consumer", corpus), (
        "the persona adaptation must allow an AI-agent consumer as the primary persona"
    )
    # Tracks are investment areas / domains of work, NOT the actor (agent) that does the work.
    assert re.search(r"investment area", corpus), (
        "tracks must be framed as investment areas / domains of work"
    )
    assert re.search(r"not\b[^.\n]*actor|NOT actors|not an actor", corpus, re.IGNORECASE), (
        "tracks must be explicitly distinguished from actors (no actor-naming in tracks)"
    )

    # --- MECHANISM FLOOR 7: positive Infiquetra downstream routing — /ideate, /brainstorm, /plan
    # pick STRATEGY.md up as grounding. This is the POSITIVE downstream edge (distinct from the
    # ce-* attribution window below). ---
    for route in ("/ideate", "/brainstorm", "/plan"):
        assert route in skill_doc, (
            f"the downstream handoff must name the Infiquetra route {route!r}"
        )

    # --- MECHANISM FLOOR 8: CE-NAMES attribution window. E1's faithful attribution names the CE
    # downstream commands inside a single attribution sentence (the canonical engine-merge graft),
    # so a flat `ce-ideate not in corpus` assertion would fail a FAITHFUL port (the /resume
    # named-agent + /founder-review no-saga-write pattern). Pin the mechanism: every ce-*
    # downstream-name occurrence sits inside an attribution/negation window (within ~80 chars of an
    # attribution keyword — "Ported"/"CE"/"map to"); the SINGLE hard-absence is that the
    # commands/ce-strategy.md file does NOT exist (mirror resume's ce-doc-review.md non-existence). ---
    flat = re.sub(r"\s+", " ", corpus)
    for name in ("ce-ideate", "ce-brainstorm", "ce-plan"):
        for match in re.finditer(re.escape(name), flat):
            window = flat[max(0, match.start() - 80) : match.start()]
            assert re.search(
                r"\b(Ported|ported|CE|map to|maps? to|Compound-Engineering)\b", window
            ), (
                f"CE downstream name {name!r} must only appear inside an attribution window, "
                f"found near: {flat[max(0, match.start() - 60) : match.start() + 40]!r}"
            )
    # ce-strategy is the porting-attribution name (not a downstream command); it too must only
    # appear inside a "ported from Compound-Engineering" attribution window.
    for match in re.finditer(r"ce-strategy", flat):
        window = flat[max(0, match.start() - 80) : match.start()]
        assert re.search(r"\b(Ported|ported|Compound-Engineering)\b", window), (
            f"ce-strategy must only appear inside a porting-attribution window, "
            f"found near: {flat[max(0, match.start() - 60) : match.start() + 40]!r}"
        )
    # The SINGLE hard-absence: no ce-strategy command shim was created in this plugin.
    assert not (ADAPTER / "commands" / "ce-strategy.md").exists(), (
        "no ce-strategy.md command shim must exist (the port is /strategy, not a ce-* alias)"
    )

    # --- MECHANISM FLOOR 9: BOUNDARY NEGATIVES via POSITIVE-BOUNDARY-PROSE + NEGATION-WINDOW.
    # The positive boundary prose (E1 bolds the NOT): /strategy records, it does not implement,
    # file SDLC issues, prioritize, or compute metric values. ---
    for negative in (
        "does **NOT** implement",
        "does **NOT** prioritize",
        "does **NOT** compute metric values",
        "does **NOT** file SDLC issues",
    ):
        assert negative in skill_doc, f"boundary prose {negative!r} must be present"

    # Negation-window ONLY for the unambiguous mutation verb "deploy" — it appears exactly once
    # in this corpus (inside the gate negation) and never as a benign noun, so every occurrence
    # must sit inside a negation window. "push" is DELIBERATELY EXCLUDED from this window check
    # (the /qa pattern for a token that doubles as an innocent word — "commit" -> "merge commit"):
    # here "push"/"pushes" is the engine's CORE verb ("pushes back on weak answers", "push back",
    # "pushback", Rumelt's "push past bad strategy"), so the push boundary is pinned instead by the
    # positive prose above + the no-runnable-`git push` assert below. The engine IDENTITY verbs
    # "record" and "anchor" are NEVER windowed — the engine's whole positive identity is that it
    # records direction. ---
    flat_skill = re.sub(r"\s+", " ", skill_doc)
    for match in re.finditer(r"\bdeploys?\b|\bdeployed\b", flat_skill, flags=re.IGNORECASE):
        window = flat_skill[max(0, match.start() - 70) : match.start()]
        assert re.search(r"\b(not|never|without|no)\b", window, flags=re.IGNORECASE), (
            f"mutation verb 'deploy' must only appear inside a negation window, found positive use "
            f"near: {flat_skill[max(0, match.start() - 50) : match.start() + 30]!r}"
        )

    # No runnable mutation command anywhere: no git commit, no git push, no gh-PR merge/create.
    assert "git commit" not in skill_doc, "/strategy must emit no runnable `git commit`"
    assert "git push" not in skill_doc, "/strategy must emit no runnable `git push`"
    assert not re.search(r"gh pr\s+\w+", skill_doc), (
        "/strategy must emit no runnable `gh pr ...` command (no merge/create)"
    )

    # --- MECHANISM FLOOR 10: NO-SAGA-WRITE. /strategy runs upstream of the work thread and is
    # advisory — it never writes the saga. E1 mentions the saga tokens only inside explicit
    # negations ("never writes the saga ... no `saga.py` invocation, no `--review-paths`"), so a
    # flat `saga.py not in corpus` would fail a FAITHFUL engine (the /founder-review pattern). Pin
    # the mechanism: no `saga.py save` string AND no runnable `python saga.py` invocation. ---
    assert "saga.py save" not in corpus, "/strategy must never emit a `saga.py save` write"
    assert not re.search(r"python3?\s+\S*saga\.py", corpus), (
        "/strategy must emit no runnable `python saga.py` invocation (it never writes the saga)"
    )

    # --- MECHANISM FLOOR 11: dispatch-table is REFERENCED but NOT restated (one source of truth,
    # no /strategy<->/loop duplication). The path is cited; the table's own unique H1 title + lead
    # sentence (which live ONLY in loop/references/dispatch-table.md) must NOT appear here. ---
    # The cited file went with the /loop skill in issue 1030; the surviving half of this floor is
    # the no-restatement rule below, which is the half that was load-bearing.
    assert "# Dispatch Table" not in corpus, (
        "the dispatch-table H1 title must not be restated in /strategy"
    )
    assert "The designed routing map for" not in corpus, (
        "the dispatch-table lead sentence must not be restated in /strategy"
    )

    # --- MECHANISM FLOOR 12: the interaction model — AskUserQuestion for routing, free-form for
    # substance, and the channel-inline fallback when redis-channel is active. ---
    assert "AskUserQuestion" in skill_doc, "routing decisions must use AskUserQuestion"
    assert re.search(r"routing", skill_doc), "AskUserQuestion is reserved for routing decisions"
    assert "free-form" in skill_doc, "substantive sections must use free-form responses"
    assert "redis-channel" in skill_doc and "inline" in skill_doc, (
        "the channel-inline fallback must be named for redis-channel sessions"
    )

    # --- ref-floor: both reference files exist and carry real content (>= 60 lines). A vibes
    # reskin would leave the refs as stubs. ---
    for ref in ("interview.md", "strategy-template.md"):
        ref_path = strategy / "references" / ref
        assert ref_path.exists()
        assert len(_read(ref_path).splitlines()) >= 60


def test_spec_engine_merge_contract() -> None:
    """Mechanism FLOORS for the gstack `spec` WHAT-interrogation port /spec (0.17.0).

    HONEST SCOPE: presence proves the contract was AUTHORED, not that a given run is mutation-free.
    /spec's whole identity is to INTERROGATE / SPECIFY / SCOPE / SHARPEN / QUANTIFY / CLARIFY the
    WHAT — so those engine-identity verbs are NEVER negation-windowed; the engine's positive point
    is that it interrogates a vague ask into a sharp spec. The off-chain saga-UNTOUCHED contract is
    enforced only by Claude reading the prose at runtime — the SKILL emits no runnable mutation and
    no runnable `python saga.py`, but token presence cannot prove a given run respects the boundary.
    These floors prove the SKILL/refs EMIT the prose the engine stands on (the HARD GATE, the
    five-Why with anti-hand-waving bars, the scope-lock five, read-code-first with the non-code
    escape, quantify-everything, the principal-engineer persona), that the durable artifact is a
    docs/specs/ spec, that the boundary prose is present (mutation verbs only inside negation
    windows, like /strategy / /qa / /founder-review), that gstack is the SINGLE honestly-attributed
    source (NO fabricated ce-spec, NO /ideate or /brainstorm porting graft), and that the dispatch
    table is referenced not restated. A thin transcribe-the-scaffold port fails these.

    This is the OFF-CHAIN twin of test_strategy (saga UNTOUCHED), NOT test_investigate
    (saga READ-ONLY) — so there is no `saga.py restore` present-assert here.

    Tokens are taken from the actual E1-authored SKILL.md + its 2 references on disk.
    """
    spec = PLUGIN_ROOT / "skills" / "spec"
    skill_doc = _read(spec / "SKILL.md")
    interrogation_doc = _read(spec / "references" / "interrogation.md")
    template_doc = _read(spec / "references" / "spec-template.md")
    corpus = "\n".join((skill_doc, interrogation_doc, template_doc))
    flat = re.sub(r"\s+", " ", corpus)
    flat_skill = re.sub(r"\s+", " ", skill_doc)

    # --- MECHANISM FLOOR 1: the HARD GATE — no spec artifact after the first message. A thin port
    # that drafts on message 1 has no gate. E1 phrases it "Do NOT produce a spec artifact after
    # message 1"; pin the do-not-produce-after-the-first-message mechanism, not a bare token. ---
    assert re.search(r"[Dd]o NOT produce.{0,60}after message 1", flat_skill), (
        "the HARD GATE must forbid producing the spec artifact after the first message"
    )
    assert re.search(r"[Ii]nterrogate first", flat), (
        "the HARD GATE must require interrogating before drafting"
    )

    # --- MECHANISM FLOOR 2: the five-Why (Phase 1) — all five questions present. A vibes port
    # collapses these into one "tell me more". The WHAT/WHY lock is the spine. ---
    assert re.search(r"\*\*Who\*\* is affected|Who is affected", corpus), (
        "five-Why: who is affected"
    )
    assert "current behavior" in corpus, "five-Why: what is the current behavior"
    assert re.search(r"should the behavior be|target state", corpus), (
        "five-Why: what should the behavior be (target)"
    )
    assert "Why now" in corpus, "five-Why: why now (the forcing function)"
    assert re.search(r"How will we know|done-signal|it's done", corpus), (
        "five-Why: how will we know it's done"
    )
    # The anti-hand-waving bar — the interrogation refuses vague answers and pushes twice. A thin
    # transcription has no bar; it just records whatever weak answer it's handed.
    assert re.search(r"anti-hand-waving|hand-waving|hand-wav", interrogation_doc, re.IGNORECASE), (
        "the five-Why must carry an anti-hand-waving bar per question"
    )

    # --- MECHANISM FLOOR 3: the scope-lock five (Phase 2). Locking the boundary early is the
    # highest-leverage anti-creep move; a stub drops it. ---
    assert "out of scope" in corpus, "scope-lock: what is explicitly out of scope"
    assert re.search(r"existing systems does this touch|systems does this touch", corpus), (
        "scope-lock: what existing systems does this touch"
    )
    assert re.search(r"[Oo]rdering constraints", corpus), "scope-lock: ordering constraints"
    assert re.search(r"MVP|smallest version", corpus), "scope-lock: the MVP / smallest-version cut"
    assert re.search(r"[Ff]ailure mode", corpus) and re.search(r"[Rr]ollback", corpus), (
        "scope-lock: failure modes + rollback (the native gstack register)"
    )

    # --- MECHANISM FLOOR 4: read-code-first (Phase 3, HARD) — the magical-moment grounding rule.
    # Evidence before ANY Phase-3 question, cite `path:line`, the six categories, the non-code
    # escape. A port that asks "what file should I look at?" first fails this. ---
    assert re.search(
        r"before .{0,40}any .{0,40}question|before asking ANY", corpus, re.IGNORECASE
    ), "read-code-first must require reading evidence BEFORE any Phase-3 question"
    assert re.search(r"\bread\b", corpus, re.IGNORECASE), "read-code-first must require reading"
    assert re.search(r"path:line|cite", corpus), "read-code-first must require citing `path:line`"
    for category in (
        "data model",
        "API",
        "background",
        "UI",
        "infrastructure",
        "testing",
    ):
        assert category in corpus, f"read-code-first must name the {category!r} category"
    # The non-code / greenfield escape — without it the HARD gate would deadlock a greenfield ask.
    assert re.search(r"no code surface", corpus) and re.search(r"greenfield", corpus), (
        "read-code-first must carry the non-code / greenfield escape"
    )

    # --- MECHANISM FLOOR 5: quantify-everything. The "Several files" anti-example + metric/target.
    # A weak port accepts vague magnitudes; this engine demands exact counts and numeric targets. ---
    assert "exact count" in corpus or "Several files" in corpus, (
        "quantify-everything must reject vague magnitudes (exact count / 'Several files')"
    )
    assert "metric" in corpus and re.search(r"\btarget\b", corpus), (
        "quantify-everything must demand a metric and a target"
    )

    # --- MECHANISM FLOOR 6: the persona — a principal engineer for whom ambiguity is a bug. A thin
    # reskin has a neutral note-taker; this engine refuses ambiguity. ---
    assert "principal engineer" in corpus, "the persona must be a principal engineer"
    assert re.search(r"[Aa]mbiguity is a bug", corpus) or re.search(
        r"refuses to let an ambiguous", corpus
    ), "the persona must treat ambiguity as a bug / refuse ambiguous WHATs"

    # --- MECHANISM FLOOR 7: the durable artifact is a docs/specs/ spec with the locked template
    # sections + frontmatter `origin`. The artifact is the only durable output; getting its path or
    # shape wrong breaks the /handoff -> mission-control source mapping. ---
    assert "docs/specs/" in corpus, "the durable artifact must live under docs/specs/"
    for section in (
        "## Acceptance Criteria",
        "## Scope Boundaries",
        "## Failure Modes & Rollback",
    ):
        assert section in template_doc, f"the spec template must carry the {section!r} section"
    assert re.search(r"^origin:", template_doc, re.MULTILINE), (
        "the spec template frontmatter must carry an `origin` field"
    )

    # --- MECHANISM FLOOR 8: SAGA UNTOUCHED — /spec runs off-chain and never writes the work thread.
    # This MIRRORS test_strategy (the off-chain twin), NOT test_investigate (saga READ-ONLY): there
    # is NO `saga.py restore` present-assert. E1 names the saga tokens ONLY inside negations ("it is
    # saga-untouched: no `saga.py`", "does **NOT** write or advance the saga (no `saga.py`, no
    # `--lifecycle-phase`)"), so a flat `saga.py not in corpus` would fail a FAITHFUL off-chain
    # engine. Pin the mechanism: no `saga.py save` string AND no runnable `python saga.py`. The
    # `--lifecycle-phase` token (which the task brief asked to flat-absence) is, on the real E1
    # file, present ONLY inside the boundary negation `no `--lifecycle-phase``; a flat
    # absence-assert contradicts the shipped SKILL, so it is pinned by a negation-window instead
    # (#spec-adaptation-is-a-hypothesis — the brief's flat-absence was written from the label, the
    # file writes it in the off-chain negation exactly like /strategy writes `saga.py`). ---
    assert "saga.py save" not in corpus, "/spec must never emit a `saga.py save` write"
    assert not re.search(r"python3?\s+\S*saga\.py", corpus), (
        "/spec must emit no runnable `python saga.py` invocation (it never writes the saga)"
    )
    for match in re.finditer(r"--lifecycle-phase", flat):
        window = flat[max(0, match.start() - 70) : match.start()]
        assert re.search(r"\b(not|never|without|no)\b", window, flags=re.IGNORECASE), (
            "`--lifecycle-phase` must only appear inside a negation window (off-chain, no saga "
            f"write), found positive use near: {flat[max(0, match.start() - 50) : match.start() + 30]!r}"
        )
    # The bare `saga.py` token also appears only inside off-chain negations ("saga-untouched: no
    # `saga.py`"); window it the same way (the /strategy off-chain pattern).
    for match in re.finditer(r"\bsaga\.py\b", flat, flags=re.IGNORECASE):
        window = flat[max(0, match.start() - 70) : match.start()]
        assert re.search(r"\b(not|never|without|no|untouched)\b", window, flags=re.IGNORECASE), (
            "`saga.py` must only appear inside an off-chain negation window, found positive use "
            f"near: {flat[max(0, match.start() - 50) : match.start() + 30]!r}"
        )

    # --- MECHANISM FLOOR 9: ZERO new Python. /spec is a skills-only port (gstack spec is a SKILL;
    # there is no scorer to port). A stray .py under skills/spec means scope crept into code. ---
    assert not list((PLUGIN_ROOT / "skills" / "spec").glob("**/*.py")), (
        "/spec must add no new Python under skills/spec (it is a skills-only port)"
    )

    # --- MECHANISM FLOOR 10: BOUNDARY NEGATIVES via POSITIVE-BOUNDARY-PROSE + NEGATION-WINDOW.
    # The positive boundary prose (E1 bolds the NOT): /spec interrogates the WHAT and reads the repo
    # read-only; it does not file an SDLC issue, write the saga, offer operator-choice, or do
    # /plan's HOW job. ---
    assert "does **NOT**" in skill_doc, "boundary prose must bold what /spec does NOT do"
    assert "read-only" in skill_doc, "/spec must declare it reads the repo read-only"

    # Negation-window ONLY for the unambiguous mutation verb "deploy" (it appears once, inside the
    # gate negation "It never commits, pushes, ... or deploys"). "push" is DELIBERATELY EXCLUDED
    # from this window check — the persona "pushes back" / "pushback" is the engine's CORE verb (the
    # /strategy pattern), so the push boundary is pinned by the positive prose above + the
    # no-runnable-`git push` assert below. The identity verbs interrogate/spec/specify/scope/
    # sharpen/quantify/clarify are NEVER windowed — they are the engine's positive identity. ---
    for match in re.finditer(r"\bdeploys?\b|\bdeployed\b", flat_skill, flags=re.IGNORECASE):
        window = flat_skill[max(0, match.start() - 70) : match.start()]
        assert re.search(r"\b(not|never|without|no)\b", window, flags=re.IGNORECASE), (
            "mutation verb 'deploy' must only appear inside a negation window, found positive use "
            f"near: {flat_skill[max(0, match.start() - 50) : match.start() + 30]!r}"
        )

    # No runnable mutation command anywhere in the SKILL: no git commit, no git push, no gh-PR
    # create/merge. (Pinned as substring/regex absence on skill_doc, per the /strategy model.)
    assert "git commit" not in skill_doc, "/spec must emit no runnable `git commit`"
    assert "git push" not in skill_doc, "/spec must emit no runnable `git push`"
    assert not re.search(r"gh pr\s+\w+", skill_doc), (
        "/spec must emit no runnable `gh pr ...` command (no merge/create)"
    )
    # THE HIGHEST-VALUE BOUNDARY: /spec never files an issue — mission-control owns issue creation.
    assert "gh issue create" not in corpus, (
        "/spec must never file an SDLC issue (`gh issue create`); mission-control owns issue creation"
    )

    # --- MECHANISM FLOOR 11: routing — /handoff, /plan, /doc-review are the named onward routes,
    # and the dispatch table is REFERENCED by path, NOT restated (one source of truth, no
    # /spec<->/loop duplication). operator-choice is NOT asserted (decision (c) — /spec never offers
    # it). ---
    # /handoff was in this list until issue 1030 removed the command; the run record's next_step
    # replaced it, so the onward routing names the two commands that still exist.
    for route in ("/plan", "/doc-review"):
        assert route in skill_doc, f"the onward routing must name {route!r}"
    # The cited file went with the /loop skill in issue 1030; the surviving half of this floor is
    # the no-restatement rule below, which is the half that was load-bearing.
    assert "# Dispatch Table" not in corpus, (
        "the dispatch-table H1 title must not be restated in /spec"
    )

    # --- MECHANISM FLOOR 12: HONEST ATTRIBUTION / ANTI-FABRICATION. gstack is the SINGLE source,
    # named near a port/source token. E1 wrote the explicit honesty line ruling out a CE engine.
    # The single hard-absence: no ce-spec command shim and no gstack-spec command shim exists (the
    # port is /spec, not a ce-* or gstack-* alias). Anti-graft: /ideate and /brainstorm are NOT
    # required as porting sources (the assumption-challenge + failure-mode register is NATIVE to
    # gstack's persona, not an /ideate+/brainstorm graft). ---
    assert re.search(r"gstack", corpus, re.IGNORECASE), "attribution must name gstack"
    assert re.search(r"(?:Ported|ported) from gstack|from gstack `spec`|gstack `spec`", corpus), (
        "gstack must be named near a port/source token (the single-source attribution)"
    )
    assert "No CE spec engine exists" in corpus, (
        "the honesty line must explicitly state no CE spec engine exists (anti-fabrication)"
    )
    assert not (ADAPTER / "commands" / "ce-spec.md").exists(), (
        "no ce-spec.md command shim must exist (the port is /spec, not a ce-* alias)"
    )
    assert not (ADAPTER / "commands" / "gstack-spec.md").exists(), (
        "no gstack-spec.md command shim must exist (the port is /spec, not a gstack-* alias)"
    )

    # --- MECHANISM FLOOR 13: AskUserQuestion routing + the channel-inline fallback. AskUserQuestion
    # is reserved for ROUTING; substance is free-form; in a redis-channel session the choices are
    # inlined (citing brainstorm/SKILL.md for the canonical convention, not duplicating it). ---
    assert "AskUserQuestion" in skill_doc, "routing decisions must use AskUserQuestion"
    assert re.search(r"routing", skill_doc), "AskUserQuestion is reserved for routing decisions"
    assert "free-form" in skill_doc, "substantive interrogation must use free-form responses"
    assert "redis-channel" in skill_doc and "inline" in skill_doc, (
        "the channel-inline fallback must be named for redis-channel sessions"
    )
    assert "brainstorm/SKILL.md" in skill_doc, (
        "the channel-inline convention must cite brainstorm/SKILL.md (not duplicate it)"
    )

    # --- ref-floor: both reference files exist and carry real content (>= 60 lines). A vibes
    # reskin would leave the refs as stubs. ---
    for ref in ("interrogation.md", "spec-template.md"):
        ref_path = spec / "references" / ref
        assert ref_path.exists()
        assert len(_read(ref_path).splitlines()) >= 60

    # --- /spec is packaged as a command (the new routable WHAT-interrogation lens). ---
    assert (ADAPTER / "commands" / "spec.md").exists(), "/spec must be packaged"


def test_destination_selector_and_escalation_helpers() -> None:
    lifecycle = _load_module("lifecycle_state.py")

    assert lifecycle.normalize_destination("plan") == "plan-only"
    assert lifecycle.normalize_destination("nonprod deploy") == "nonprod-deploy"
    assert lifecycle.destination_includes_deploy("nonprod-deploy")
    assert not lifecycle.destination_includes_deploy("pr")

    assert (
        lifecycle.should_offer_team_execution(
            file_count=2,
            phase_count=2,
            has_security=False,
            has_infra=False,
            cross_repo=False,
            deployment_sensitive=False,
        )
        is False
    )
    assert (
        lifecycle.should_offer_team_execution(
            file_count=1,
            phase_count=1,
            has_security=True,
            has_infra=False,
            cross_repo=False,
            deployment_sensitive=False,
        )
        is True
    )


def test_recommend_backend_release_surface_subtraction() -> None:
    """KTD1 (R1): release-bookkeeping files do not count toward the team-execution size trigger.

    The #526 shape (3 functional + 6 bookkeeping files) misfired to team-execution because the
    raw file_count >= 8 boundary counted plugin.json / marketplace.json / CHANGELOGs / drift pins.
    The subtractive release_surface_file_count fixes it: the size trigger compares
    file_count - release_surface_file_count >= 8, so genuinely-functional 8+ still trips.
    """
    lifecycle = _load_module("lifecycle_state.py")
    rec = lifecycle.recommend_execution_backend

    # #526-shape regression: 9 touched files, 6 of them release bookkeeping -> 3 functional -> inline.
    assert rec(file_count=9, release_surface_file_count=6)["recommended"] == "inline"
    # Without the subtraction the SAME raw count still trips team-execution (boundary preserved).
    assert rec(file_count=9, release_surface_file_count=0)["recommended"] == "inline"
    # 8 genuinely-functional files still trips even with bookkeeping on top.
    assert rec(file_count=14, release_surface_file_count=6)["recommended"] == "inline"
    # Exactly-at-boundary functional count (8) trips; one below (7) does not.
    assert rec(file_count=10, release_surface_file_count=2)["recommended"] == "inline"
    assert rec(file_count=9, release_surface_file_count=2)["recommended"] == "inline"
    # should_offer_team_execution carries the same subtraction directly.
    assert (
        lifecycle.should_offer_team_execution(
            file_count=9,
            phase_count=1,
            has_security=False,
            has_infra=False,
            cross_repo=False,
            deployment_sensitive=False,
            release_surface_file_count=6,
        )
        is False
    )
    # A negative count would INFLATE the functional total and silently over-escalate ->
    # fail loud instead (garbage-in guard), through both the direct and recommender paths.
    with pytest.raises(ValueError, match="release_surface_file_count"):
        lifecycle.should_offer_team_execution(
            file_count=3,
            phase_count=1,
            has_security=False,
            has_infra=False,
            cross_repo=False,
            deployment_sensitive=False,
            release_surface_file_count=-10,
        )
    with pytest.raises(ValueError, match="release_surface_file_count"):
        rec(file_count=3, release_surface_file_count=-10)


def test_recommend_backend_survives_an_unavailable_workflow_tool() -> None:
    """A host without the Workflow tool gets a recommendation, not a ValueError.

    Issue 1030 narrowed the reachable-backend list to ``["inline"]`` and left behind the line
    that removed ``cc-workflows-ultracode`` from it when the tool was absent. ``list.remove``
    raises on a value that is not there, so every call passing ``workflow_available=False`` --
    which is every call from a host that actually probed -- died with
    ``ValueError: list.remove(x): x not in list``. The full suite stayed green because no case
    passed the flag.

    Both provenance values are exercised, because the crash was in the branch the flag selects
    and not in the note the source chooses.
    """

    lifecycle = _load_module("lifecycle_state.py")
    for source in ("probed", "asserted"):
        result = lifecycle.recommend_execution_backend(
            workflow_available=False,
            workflow_availability_source=source,
        )
        assert result["recommended"] == "inline"
        assert result["alternatives"] == []
        assert [entry["backend"] for entry in result["backends"]] == ["inline"]
        assert [entry["status"] for entry in result["backends"]] == ["recommended"]


def test_issue_progress_comments_include_required_evidence() -> None:
    issue_progress = _load_module("issue_progress.py")

    start = issue_progress.render_issue_comment(
        event="start",
        issue_ref="infiquetra/campps-service#42",
        destination="nonprod-deploy",
        plan_path="docs/plans/2026-05-29-campps-service.md",
        summary="Add deployment status endpoint.",
    )
    assert "selected destination: nonprod-deploy" in start
    assert "docs/plans/2026-05-29-campps-service.md" in start

    phase = issue_progress.render_issue_comment(
        event="phase",
        issue_ref="infiquetra/campps-service#42",
        destination="nonprod-deploy",
        work_session_path="docs/work-sessions/2026-05-29-phase-1.md",
        commit_sha="abc1234",
        checks_run=["uv run pytest tests/test_service.py -q"],
        blockers="None",
    )
    assert "docs/work-sessions/2026-05-29-phase-1.md" in phase
    assert "abc1234" in phase
    assert "uv run pytest tests/test_service.py -q" in phase

    review = issue_progress.render_issue_comment(
        event="phase",
        issue_ref="infiquetra/campps-service#42",
        destination="pr",
        handoff_maturity="plan-ready",
        handoff_source="docs/plans/example.md",
        next_action="/work <issue>",
        doc_review_artifact="docs/reviews/2026-05-29-doc-review.md",
        doc_review_blocked=True,
        doc_review_fixes=["Added missing gate."],
        doc_review_findings=["P1 Missing rollback evidence."],
        doc_review_override="Proceeding after owner accepted risk.",
    )
    assert "doc review artifact: docs/reviews/2026-05-29-doc-review.md" in review
    assert "handoff maturity: plan-ready" in review
    assert "handoff source: docs/plans/example.md" in review
    assert "next action: /work <issue>" in review
    assert "doc review blocked: yes" in review
    assert "doc review override: Proceeding after owner accepted risk." in review
    assert "doc review fixes:" in review
    assert "Added missing gate." in review
    assert "doc review findings:" in review
    assert "P1 Missing rollback evidence." in review


def test_issue_progress_cli_renders_extended_work_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """DA-C1: the CLI must expose the fields /work's Phase-4 comment passes.

    render_issue_comment() already accepted these fields, but the argparse surface only
    exposed 8 — so /work's markdown call was uninvokable. The rebuild extends parse_args/main
    to forward the function's full field set. Drive main() with a faked argv (the helper's
    main() takes argv directly) and assert each new flag's value lands in the rendered output.
    """
    issue_progress = _load_module("issue_progress.py")

    rc = issue_progress.main(
        [
            "--event",
            "phase",
            "--issue-ref",
            "infiquetra/campps-service#42",
            "--destination",
            "pr",
            "--work-session-path",
            "docs/work-sessions/2026-06-03-phase-2.md",
            "--commit-sha",
            "deadbeef",
            "--checks-run",
            "pytest|ruff",
            "--blockers",
            "None",
            "--pr-url",
            "https://github.com/infiquetra/campps-service/pull/7",
            "--review-status",
            "APPROVED",
            "--doc-review-artifact",
            "docs/reviews/2026-06-03-doc-review.md",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0

    # Each new CLI flag's value renders into the comment.
    assert "docs/work-sessions/2026-06-03-phase-2.md" in out
    assert "deadbeef" in out
    # --checks-run is pipe-split; each check renders on its own indented bullet.
    assert "`pytest`" in out
    assert "`ruff`" in out
    assert "blockers: None" in out
    assert "https://github.com/infiquetra/campps-service/pull/7" in out
    assert "review status: APPROVED" in out
    assert "doc review artifact: docs/reviews/2026-06-03-doc-review.md" in out


def test_issue_parser_extracts_infiquetra_context_and_risk_flags() -> None:
    parse_issue = _load_module("parse_issue.py")

    extracted = parse_issue.extract("ADR-0004 Round 2\n\nAC-1 Add OpenAPI endpoint with IAM auth.")

    assert extracted["adr_refs"] == ["ADR-0004"]
    assert extracted["ac_refs"] == ["AC-1"]
    assert extracted["round_refs"] == [2]
    assert extracted["flags"]["has_api"] is True
    assert extracted["flags"]["has_security"] is True
    assert extracted["handoff"]["maturity"] == ""


def test_issue_parser_extracts_handoff_maturity_and_source_context() -> None:
    parse_issue = _load_module("parse_issue.py")

    body = """### Objective
Build the thing.

### Handoff maturity
plan-ready

### Suggested next action
Use `/work <issue>` to execute from the plan-grade context.

### Source context
- Source: docs/plans/example.md
- Source type: plan
- Source title: Example Plan
"""

    extracted = parse_issue.extract(body)

    assert extracted["handoff"] == {
        "maturity": "plan-ready",
        "suggested_next_action": "Use `/work <issue>` to execute from the plan-grade context.",
        "source": "docs/plans/example.md",
        "source_type": "plan",
        "source_title": "Example Plan",
        "can_plan": False,
        "can_work": True,
        "requires_clarification": False,
    }


def test_handoff_envelope_routes_to_sdlc_manager_without_issue_body_ownership(tmp_path) -> None:
    handoff = _load_module("handoff_envelope.py")
    plan = tmp_path / "docs" / "plans" / "example.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Example Plan\n")

    envelope = handoff.build_handoff_envelope(
        "docs/plans/example.md",
        target_team="Asgard",
        target_repo="infiquetra-claude-plugins",
        issue_type="capability",
        reason="another team should pick this up",
        root=tmp_path,
    )

    assert envelope["source"] == "docs/plans/example.md"
    assert envelope["lifecycle_phase"] == "plan"
    assert envelope["handoff_maturity"] == "plan-ready"
    assert envelope["lifecycle_owner"] == "saga"
    assert envelope["issue_artifact_owner"] == "mission-control"
    assert envelope["body_template_owner"] == "mission-control"
    assert envelope["suggested_command"].startswith("/issue --prepare")
    assert "--from docs/plans/example.md" in envelope["suggested_command"]
    assert "--maturity plan-ready" in envelope["suggested_command"]
    assert "/loop" not in envelope["suggested_command"]

    # A /spec artifact under docs/specs/ is a sharp WHAT (requirements-ready) and OFF-CHAIN:
    # it carries no lifecycle phase (the saga-untouched /spec produces a backlog source, not a
    # work-thread tick). These pin the docs/specs/ handoff inference E1 wired for the /spec port.
    assert handoff.infer_maturity("docs/specs/x-spec.md") == "requirements-ready"
    assert handoff.infer_lifecycle_phase("docs/specs/x-spec.md") == "unknown"


def test_handoff_envelope_discovers_active_plan_from_loop_state(tmp_path) -> None:
    handoff = _load_module("handoff_envelope.py")
    state = tmp_path / ".claude" / "saga" / "state.json"
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps({"current_work": {"plan_path": "docs/plans/active.md"}}),
        encoding="utf-8",
    )

    envelope = handoff.build_handoff_envelope(root=tmp_path)

    assert envelope["source"] == "docs/plans/active.md"
    assert envelope["handoff_maturity"] == "plan-ready"


def _load_saga_module():
    """Load saga.py REGISTERED in sys.modules.

    saga.py defines a frozen @dataclass; on Python 3.12+ the dataclass build
    looks the class's __module__ up in sys.modules, so an unregistered import
    raises during exec. (The module-level ``_load_module`` here does not
    register, so it cannot load saga.py.)
    """
    path = PLUGIN_ROOT / "scripts" / "saga.py"
    spec = importlib.util.spec_from_file_location("saga", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["saga"] = module
    spec.loader.exec_module(module)
    return module


def _stub_saga_git_seam(saga, monkeypatch: pytest.MonkeyPatch) -> None:
    """Offline save: stub the git seam exactly like test_scan_exposes_picker_fields does."""
    no_git = lambda *_a, **_k: SimpleNamespace(returncode=1, stdout="", stderr="")  # noqa: E731
    monkeypatch.setattr(saga.subprocess, "run", no_git)
    for fn_name in ("save", "current_git_state"):
        fn = getattr(saga, fn_name)
        new_kwdefaults = dict(fn.__kwdefaults__ or {})
        new_kwdefaults["runner"] = no_git
        monkeypatch.setattr(fn, "__kwdefaults__", new_kwdefaults)


def test_spec_check_ok_and_file_missing_verdicts(tmp_path, monkeypatch) -> None:
    """#693: a real spec path verifies ok; a path whose file is gone is file-missing."""
    saga_mod = _load_saga_module()
    _stub_saga_git_seam(saga_mod, monkeypatch)

    spec_path = tmp_path / "docs" / "plans" / "2026-08-04-ok-spec.json"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text("{}", encoding="utf-8")

    ok_id = saga_mod.derive_saga_id("issue", "693")
    saga_mod.save(
        tmp_path,
        saga_mod.Saga(
            saga_id=ok_id,
            kind="issue",
            id="693",
            orchestration_ref="docs/plans/2026-08-04-ok-spec.json",
        ),
        now=datetime(2026, 8, 4, 9, 0, 0, tzinfo=UTC),
    )
    restored = saga_mod.restore(tmp_path, ok_id)
    assert saga_mod.spec_ref_verdict(restored, tmp_path) == (
        "ok",
        "docs/plans/2026-08-04-ok-spec.json",
    )

    gone_id = saga_mod.derive_saga_id("issue", "694")
    saga_mod.save(
        tmp_path,
        saga_mod.Saga(
            saga_id=gone_id, kind="issue", id="694", orchestration_ref="docs/plans/gone-spec.json"
        ),
        now=datetime(2026, 8, 4, 9, 5, 0, tzinfo=UTC),
    )
    verdict, _ = saga_mod.spec_ref_verdict(saga_mod.restore(tmp_path, gone_id), tmp_path)
    assert verdict == "file-missing"

    monkeypatch.chdir(tmp_path)
    assert saga_mod.main(["spec-check", "--saga-id", ok_id]) == 0
    assert saga_mod.main(["spec-check", "--saga-id", gone_id]) == 2


def test_ae10_status_card_single_emitter_routing() -> None:
    """AE10: each of the five saga surfaces routes its operator-facing status-summary
    through the shared status_card renderer (R14 — retire per-surface prose emissions).

    Tokens chosen from the actual authored SKILL.md prose — these are load-bearing
    contract assertions, not fragile grep guards. KTD5 evidence detail is kept as
    drill-down body below the card; per-finding tables and verdict values remain.
    """
    work_doc = _read(PLUGIN_ROOT / "skills" / "work" / "SKILL.md")
    cr_doc = _read(PLUGIN_ROOT / "skills" / "code-review" / "SKILL.md")
    qa_doc = _read(PLUGIN_ROOT / "skills" / "qa" / "SKILL.md")

    # --- /work ---
    # PRESENT: card renderer and per-surface function name.
    assert "status_card" in work_doc
    assert "project_work" in work_doc
    # PRESENT: U2 producer flag — gate_verdicts written by /work Phase-3 tick.
    assert "--gate-verdict" in work_doc
    # PRESENT: the producer example uses a CANONICAL gate state — a passing gate is `tests:done:<ref>`.
    assert "tests:done:<ref>" in work_doc
    # ABSENT: the non-canonical `pass|fail|skip` vocab would parse to *unknown* and silently drop the
    # verdict (the Tests card cell would render not-reached) — guard against that regression.
    assert "tests:<pass|fail|skip>" not in work_doc
    # PRESENT (substantive): the card render is the LEAD status step of §5.4 — proving the card is
    # the operator status HEADER, not an afterthought — and a fourth step still follows it, which
    # proves a real reorder rather than a keyword sprinkle. THREE cards have now changed this
    # section's wording: issue #1029 made the step continue the run rather than present routing,
    # issue #1027 removed the ship ceremony it used to continue into, and issue #1028 replaced the
    # hand-over with the merge turn, release, functional test and close it hands over TO. That is
    # the argument for holding the POSITION and the property, not the prose.
    assert "1. **Render the operator status header**" in work_doc
    assert re.search(r"^4\. \*\*[^*]+\*\*", work_doc, flags=re.MULTILINE), (
        "section 5.4 must still carry a fourth step after the status-card render"
    )
    section = work_doc[work_doc.index("### 5.4 ") :]
    body = section[section.index("\n") :]  # past the heading, which names the steps too
    assert body.index("**Render the operator status header**") < body.index(
        "Take the merge turn"
    ), "the status card must lead §5.4, not trail the steps it heads"
    assert "Run `/qa` in this turn" in work_doc, (
        "issue 1029's continuation contract: the functional test is run, not recommended"
    )
    # STILL PRESENT (KTD5): detailed work-session evidence reference.
    assert "work-session" in work_doc

    # --- /code-review ---
    # PRESENT: card renderer and per-surface function name.
    assert "status_card" in cr_doc
    assert "project_code_review" in cr_doc
    # ABSENT: old standalone "blockquote verdict" status-summary phrasing (retired by card).
    assert "blockquote verdict" not in cr_doc
    # STILL PRESENT (KTD5): per-finding evidence table header (drill-down body kept).
    assert "# | File | Issue | Reviewer | Confidence | Route" in cr_doc

    # --- /qa ---
    # PRESENT: card renderer and per-surface function name.
    assert "status_card" in qa_doc
    assert "project_qa" in qa_doc
    # ABSENT: old bold "**health-score block**" as standalone operator-facing presentation element.
    assert "**health-score block**" not in qa_doc
    # STILL PRESENT (KTD5): verdict values are the card's data source; remain in artifact spec.
    assert "ship-with-deferred" in qa_doc
    assert "no-ship" in qa_doc

    # The /outcome and /resume blocks lived here. Issue 1030 removed both skills with the
    # commands, so the five surfaces this case guards are now three: /work, /code-review
    # and /qa. The renderer contract itself is unchanged.


def test_intake_exit_saga_creates_no_issue() -> None:
    """W10 / sdlc#91 AE32: the two Intake commands are boundary-bounded —
    office-hours and ideate produce durable source material and carry NO runnable
    GitHub issue-creating instruction. Mission Control owns issue creation (its
    `issue create-prepared` path), reached through `/handoff`.

    A flat absence assert would also pass an emptied corpus, so the test pins
    three mechanisms: (1) no `issue create-prepared` invocation and no runnable
    `gh issue create`, with every `gh issue create` mention inside a negation
    window; (2) POSITIVE identity — the corpora still carry their producing
    verbs and durable artifact paths; (3) a seeded violation — a bare runnable
    `gh issue create` appended to a copy FAILS the check, proving teeth.
    """
    office_doc = _read(PLUGIN_ROOT / "skills" / "office-hours" / "SKILL.md")
    ideate = PLUGIN_ROOT / "skills" / "ideate"
    ideate_doc = _read(ideate / "SKILL.md")
    convergence_doc = _read(ideate / "references" / "convergence-and-partnership.md")
    corpora = {"office-hours": office_doc, "ideate": ideate_doc + "\n" + convergence_doc}

    def _boundary_check(corpus: str, surface: str) -> None:
        assert "issue create-prepared" not in corpus, (
            f"{surface} must not invoke Mission Control's issue creation directly"
        )
        for match in re.finditer(r"gh issue create", corpus):
            window = corpus[max(0, match.start() - 60) : match.start()]
            assert re.search(r"\b(not|never|no)\b", window, re.IGNORECASE), (
                f"every `gh issue create` mention must sit inside a negation window "
                f"({surface}), found near: "
                f"{corpus[max(0, match.start() - 50) : match.end() + 30]!r}"
            )

    for surface, corpus in corpora.items():
        _boundary_check(corpus, surface)

    # --- (R6) the boundary is STATED in each command's own skill text — deleting
    # the boundary prose from either SKILL.md fails this test. ---
    assert "durable source material only" in office_doc, (
        "office-hours must state that it produces durable source material only"
    )
    assert "Mission Control owns issue creation" in office_doc, (
        "office-hours must name Mission Control as the issue-creation owner"
    )
    assert "durable source material" in ideate_doc, (
        "ideate must state that it produces durable source material"
    )
    assert "never runs `gh issue create`" in ideate_doc, (
        "ideate must carry the never-runs-gh-issue-create boundary in its own text"
    )

    # --- POSITIVE IDENTITY: withdrawing issue-creation authority removed nothing
    # the commands produce. Each corpus still carries its producing verbs + paths. ---
    assert "diagnos" in office_doc.lower(), "office-hours must keep its diagnostic identity"
    assert "frame" in office_doc.lower(), "office-hours must keep its frame-finding identity"
    # ``/handoff`` was the fourth route until issue 1030 removed the command. Its
    # destination did not move -- Mission Control still owns the issue -- so the
    # boundary assertion above carries that half, and this loop pins only routes that
    # still resolve. A guard that required a removed command's name would have made
    # the dangling route impossible to fix.
    for route in ("/ideate", "/brainstorm", "/plan"):
        assert route in office_doc, f"office-hours routing must still name {route}"
    assert "Mission Control" in office_doc, "office-hours must still name where an issue comes from"
    for verb in ("generate", "critique", "reject"):
        assert verb in ideate_doc.lower(), f"ideate must keep its {verb} identity"
    assert "docs/ideation/" in ideate_doc, "ideate's durable artifact path must survive"
    assert "`mission-control`" in convergence_doc, (
        "/ideate must still route to Mission Control for the issue; the `/handoff` command\n"
        "that fronted that route was removed by issue 1030, and the destination was not"
    )

    # --- SEEDED VIOLATION: the same check FAILS on a bare runnable `gh issue create`.
    # The seed keeps its token >60 chars away from any negation the doc happens to carry. ---
    seeded = office_doc + (
        "\nAs a later step in this flow you would then: "
        "gh issue create --repo infiquetra/infiquetra-sdlc\n"
    )
    failed = False
    try:
        _boundary_check(seeded, "seeded-violation")
    except AssertionError:
        failed = True
    assert failed, "the seeded bare `gh issue create` must FAIL the boundary check"


def test_parse_issue_pending_confirmation_distinguishable(tmp_path: Path) -> None:
    """fix-41f71b5ccacd: pending-confirmation is not blanked and is distinguishable from no handoff."""
    mod = _load_module("parse_issue.py")
    # Real path: parse an issue body carrying pending-confirmation
    body_pending = "### Handoff maturity\npending-confirmation\n\n### Source context\n- Source: docs/brainstorms/2026-08-30-x-requirements.md\n"
    parsed_pending = mod.extract(body_pending)
    assert parsed_pending["handoff"]["maturity"] == "pending-confirmation"
    # Must not be can_plan/can_work, and blank must be different
    body_blank = "### Objective\nNo handoff here\n"
    parsed_blank = mod.extract(body_blank)
    assert parsed_blank["handoff"]["maturity"] == ""
    assert parsed_pending["handoff"]["maturity"] != parsed_blank["handoff"]["maturity"]
    # pending-confirmation is not a planning/working maturity, but is distinct from blank
    assert parsed_pending["handoff"]["can_plan"] is False
    assert parsed_pending["handoff"]["can_work"] is False
    # If HANDOFF_MATURITY_VALUES lacked pending-confirmation, this would have returned "" and failed


def test_parse_issue_collapses_unrecognized_to_empty() -> None:
    """fix-6d7c2083c11c TEST-19: issue parser collapses unrecognized Handoff maturity to empty."""
    mod = _load_module("parse_issue.py")
    body = "### Handoff maturity\nnot-a-real-maturity\n\n### Source context\n- Source: docs/brainstorms/x.md\n"
    parsed = mod.extract(body)
    assert parsed["handoff"]["maturity"] == "", (
        "unrecognized Handoff maturity must collapse to empty string, not a sentinel"
    )
    assert parsed["handoff"]["can_plan"] is False
    assert parsed["handoff"]["can_work"] is False
    # Also verify empty vs unrecognized are indistinguishable (both collapse to empty)
    body_blank = "### Objective\nNo handoff here\n"
    parsed_blank = mod.extract(body_blank)
    assert parsed_blank["handoff"]["maturity"] == ""
    assert parsed["handoff"]["maturity"] == parsed_blank["handoff"]["maturity"]


def test_unrecognized_maturity_fails_closed_and_vocabularies_synced(tmp_path: Path) -> None:
    """fix-13e628f20af7: unrecognized maturity fails closed with no signal, vocabularies in sync."""
    handoff = _load_module("handoff_envelope.py")
    parse_mod = _load_module("parse_issue.py")
    # Real path: frontmatter with unknown maturity under docs/brainstorms must not emit a route
    brainstorms = tmp_path / "docs" / "brainstorms"
    brainstorms.mkdir(parents=True)
    target = brainstorms / "2026-08-30-x-requirements.md"
    target.write_text("---\nmaturity: not-a-real-maturity\n---\n\nBody\n", encoding="utf-8")
    envelope = handoff.build_handoff_envelope(
        "docs/brainstorms/2026-08-30-x-requirements.md", root=tmp_path
    )
    assert "/issue --prepare" not in envelope["suggested_command"], (
        "unrecognized maturity must not emit a route"
    )
    assert envelope["handoff_maturity"].startswith("unknown:")
    # Uniformly indented frontmatter IS top-level YAML — declares and fails closed (not ignored)
    target.write_text("---\n  maturity: pending-confirmation\n---\n\nBody\n", encoding="utf-8")
    assert (
        handoff.infer_maturity("docs/brainstorms/2026-08-30-x-requirements.md", root=tmp_path)
        == "pending-confirmation"
    )
    # Genuinely nested key does not declare, fails closed as carrier
    target.write_text(
        "---\nmeta:\n  maturity: pending-confirmation\n---\n\nBody\n", encoding="utf-8"
    )
    assert handoff.infer_maturity(
        "docs/brainstorms/2026-08-30-x-requirements.md", root=tmp_path
    ).startswith("unknown:carrier:")
    # Vocabulary drift guard: every code-level maturity vocab is superset of HANDOFF_MATURITIES
    handoff_mats = set(handoff.HANDOFF_MATURITIES)
    assert set(parse_mod.HANDOFF_MATURITY_VALUES) == handoff_mats
    spec_text = _read(ROOT / "plugins/saga/references/saga-spec.md")
    for val in handoff_mats:
        assert val in spec_text
