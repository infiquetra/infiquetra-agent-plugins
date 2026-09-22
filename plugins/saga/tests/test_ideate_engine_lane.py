"""Contract tests for the /ideate external-engine generator lane (#454)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
IDEATE_SKILL = ROOT / "plugins" / "saga" / "skills" / "ideate" / "SKILL.md"
CONVERGENCE = (
    ROOT
    / "plugins"
    / "saga"
    / "skills"
    / "ideate"
    / "references"
    / "convergence-and-partnership.md"
)
ARTIFACT = ROOT / "plugins" / "saga" / "skills" / "ideate" / "references" / "ideation-artifact.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _between(text: str, start: str, end: str) -> str:
    start_index = text.index(start)
    end_index = text.index(end, start_index)
    return text[start_index:end_index]


def _compact(text: str) -> str:
    return " ".join(text.split())


def test_dispatch_contract_adds_one_external_lane_with_identical_prompt_inputs() -> None:
    text = _read(IDEATE_SKILL)
    lane = _between(
        text,
        "**External-engine generator lane (additive, blind, best-effort).**",
        "**After all available generator lanes return:**",
    )
    compact_lane = _compact(lane)

    assert "In addition to the N Claude frame agents" in compact_lane
    assert "one chaperoned external-engine generator lane" in compact_lane
    assert "`offload`" in lane
    assert "`sonnet/medium`" in lane
    assert "same substituted frame-agent prompt above" in compact_lane
    for prompt_input in (
        "frame",
        "grounding summary",
        "focus",
        "topic axes",
        "per-agent target",
        "captured user seeds",
        "tactical-scope flag",
    ):
        assert prompt_input in compact_lane
    assert "Do not add an external-engine-only prompt variant" in compact_lane


def test_blind_isolation_holds_until_merge_boundary() -> None:
    text = _read(IDEATE_SKILL)
    lane_start = text.index("**External-engine generator lane")
    merge_start = text.index("**After all available generator lanes return:**")
    lane = text[lane_start:merge_start]
    compact_lane = _compact(lane)

    assert lane_start < merge_start
    assert "do not include any raw candidates or merged candidate pool" in compact_lane
    assert "blind by construction" in compact_lane
    assert "first meets the Claude frame-agent output at the merge boundary" in compact_lane


def test_tag_application_records_engine_generated_provenance_only() -> None:
    skill_text = _read(IDEATE_SKILL)
    merge = _between(skill_text, "**After all available generator lanes return:**", "**Checkpoint")
    artifact = _read(ARTIFACT)

    assert "tag the candidate provenance `engine-generated`" in merge
    assert "Do not apply `engine-generated` to Claude" in merge
    assert "| source |" in artifact
    assert "`engine-generated`; provenance only, not a scoring rule" in artifact
    assert "engine-generated | Phase 2" in artifact


def test_no_gate_exemption_applies_identical_convergence_treatment() -> None:
    text = _read(CONVERGENCE)
    note = _between(text, "**Provenance is not a gate criterion.**", "### Survivor scoring rubric")
    compact_note = _compact(note)

    assert "`engine-generated`" in note
    assert "same rejection criteria" in compact_note
    assert "same survivor scoring rubric" in compact_note
    assert "does not relax basis strength" in compact_note
    assert "create a separate review path" in compact_note

    allowed_occurrence_markers = (
        "candidate tagged `engine-generated`",
        "source** — provenance only",
        "`engine-generated`. Omit only",
    )
    for line in text.splitlines():
        if "`engine-generated`" not in line:
            continue
        assert any(marker in line for marker in allowed_occurrence_markers), line


def test_graceful_degrade_keeps_ideate_claude_only_when_lane_unavailable() -> None:
    text = _read(IDEATE_SKILL)
    lane = _between(
        text,
        "**External-engine generator lane (additive, blind, best-effort).**",
        "**After all available generator lanes return:**",
    )
    compact_lane = _compact(lane)

    assert "If the external-engine dispatch is unavailable" in compact_lane
    assert "record a non-blocking note" in compact_lane
    assert "continue with the Claude-only frame-agent set" in compact_lane
    assert "Do not halt `/ideate`" in compact_lane
    assert "do not create a partial-failure state" in compact_lane
