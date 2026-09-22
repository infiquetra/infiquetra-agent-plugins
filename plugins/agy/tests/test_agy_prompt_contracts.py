"""Static prompt-contract tests for packaged agy surfaces."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = ROOT
WRAPPER_PATH = "plugins/agy/scripts/agy_delegate.py"


def _read(relative_path: str) -> str:
    return (PLUGIN_ROOT / relative_path).read_text(encoding="utf-8")


def _frontmatter(relative_path: str) -> dict[str, str]:
    lines = _read(relative_path).splitlines()
    assert lines[0] == "---"

    data: dict[str, str] = {}
    for line in lines[1:]:
        if line == "---":
            return data
        if ": " in line:
            key, value = line.split(": ", 1)
            data[key] = value.strip()

    raise AssertionError(f"{relative_path} has no closing frontmatter marker")


def _assert_all_present(text: str, required: tuple[str, ...]) -> None:
    missing = [needle for needle in required if needle not in text]
    assert missing == []


def test_bridge_agents_are_bash_only_and_single_wrapper_run() -> None:
    required = (
        "tools: Bash",
        WRAPPER_PATH,
        "exactly once per delegated turn",
        "Direct Read/Edit/Write solving",
        "contract breach",
        "Do not invoke raw `agy`",
        "Do not use background, detached",
        "Do not commit, push, force-push, rewrite history",
        "change remote state",
        "locally as a fallback",
    )

    for agent in ("agy-coder", "agy-reviewer"):
        relative_path = f"com.infiquetra.claude/agents/{agent}.md"
        text = _read(relative_path)

        assert _frontmatter(relative_path)["tools"] == "Bash"
        _assert_all_present(text, required)


def test_coder_prompt_requires_strong_packet_and_write_gate() -> None:
    text = _read("com.infiquetra.claude/agents/agy-coder.md")

    _assert_all_present(
        text,
        (
            "expert software engineer",
            "read-broad/write-narrow",
            "exact write-set",
            "PLAN_GAP:",
            "TEST_CONFLICT:",
            "PATH_MISSING:",
            "Verification commands",
            "run report",
            "Use `mode=patch-only`",
            "never writes the live tree",
        ),
    )


def test_reviewer_prompt_defaults_and_lenses_are_single_agent_contract() -> None:
    text = _read("com.infiquetra.claude/agents/agy-reviewer.md")

    _assert_all_present(
        text,
        (
            "Default to `role=reviewer`, `mode=no-write`, and `review_lens=adversarial`",
            "`adversarial`",
            "`quality`",
            "`scope-gap`",
            "`security-ops`",
            "do not create additional reviewer agents",
        ),
    )


def test_delegate_command_documents_wrapper_syntax_not_raw_agy() -> None:
    text = _read("com.infiquetra.claude/commands/delegate.md")

    _assert_all_present(
        text,
        (
            "role=<coder|reviewer>",
            "mode=<no-write|patch-only>",
            "evidence=<minimal|summary|full>",
            "write-set=<repo-relative-path>",
            "verification=<command>",
            "review_lens=<adversarial|quality|scope-gap|security-ops>",
            "--write-set",
            "--verification-command",
            "--verification-required",
            WRAPPER_PATH,
            "Do not invoke raw `agy` directly",
        ),
    )
    assert "```bash\nagy " not in text


def test_skill_and_reference_share_evidence_and_write_gate_contract() -> None:
    skill = _read("skills/agy-delegate/SKILL.md")
    reference = _read("skills/agy-delegate/references/delegation-contract.md")

    for text in (skill, reference):
        _assert_all_present(
            text,
            (
                "The wrapper is the only supported execution path",
                "Direct Read/Edit/Write",
                "solving",
                "contract breach",
                "mode=patch-only",
                "role=reviewer",
                "mode=no-write",
                "review_lens=adversarial",
                "adversarial",
                "quality",
                "scope-gap",
                "security-ops",
                "evidence",
                WRAPPER_PATH,
            ),
        )


def test_prompts_do_not_offer_the_retired_live_apply_mode() -> None:
    """`auto-if-clean` was retired in 0.6.0 (#671).

    Naming it is allowed — the contract reference and README explain the retirement — but no
    surface may present it as a mode a caller can select.
    """

    surfaces = (
        "com.infiquetra.claude/agents/agy-coder.md",
        "com.infiquetra.claude/agents/agy-reviewer.md",
        "com.infiquetra.claude/commands/delegate.md",
        "skills/agy-delegate/SKILL.md",
        "skills/agy-delegate/references/delegation-contract.md",
    )
    banned = (
        "mode=<no-write|patch-only|auto-if-clean>",
        "use `mode=auto-if-clean`",
        "`no-write`, `patch-only`, or `auto-if-clean`",
        "apply_policy=apply-if-clean",
        "--lease-resource-key-file",
    )

    for relative_path in surfaces:
        lowered = _read(relative_path).lower()
        for fragment in banned:
            assert fragment.lower() not in lowered, f"{relative_path} offers {fragment!r}"


def test_prompts_do_not_advertise_local_solving_affordances() -> None:
    surfaces = {
        "com.infiquetra.claude/agents/agy-coder.md": _read(
            "com.infiquetra.claude/agents/agy-coder.md"
        ),
        "com.infiquetra.claude/agents/agy-reviewer.md": _read(
            "com.infiquetra.claude/agents/agy-reviewer.md"
        ),
        "com.infiquetra.claude/commands/delegate.md": _read(
            "com.infiquetra.claude/commands/delegate.md"
        ),
        "skills/agy-delegate/SKILL.md": _read("skills/agy-delegate/SKILL.md"),
        "skills/agy-delegate/references/delegation-contract.md": _read(
            "skills/agy-delegate/references/delegation-contract.md"
        ),
    }
    banned_fragments = (
        "use Read",
        "use Edit",
        "use Write",
        "use MultiEdit",
        "solve locally",
        "local fallback is allowed",
        "may call raw `agy`",
        "invoke raw `agy` directly when",
        "run `agy` directly",
        "nohup python3 plugins/agy/scripts/agy_delegate.py",
        "&\n",
    )

    for path, text in surfaces.items():
        lowered = text.lower()
        for fragment in banned_fragments:
            assert fragment.lower() not in lowered, f"{path} advertises {fragment!r}"
