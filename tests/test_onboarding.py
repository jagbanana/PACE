"""Phase 4 onboarding artifacts: CLAUDE.md, scheduled-task prompts, git init.

The actual onboarding *conversation* runs in Cowork at runtime — these
tests verify only the on-disk deliverables that ``pace init`` produces
to make that conversation possible.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from pace import vault as vault_ops
from pace.onboarding import CLAUDE_MD_TEMPLATE, COMPACT_PROMPT, REVIEW_PROMPT

# ---- CLAUDE.md ---------------------------------------------------------


def test_init_writes_claude_md_from_template(tmp_path: Path) -> None:
    result = vault_ops.init(tmp_path)
    claude = tmp_path / "CLAUDE.md"
    assert claude.is_file()
    assert "CLAUDE.md" in result.created_files
    assert claude.read_text(encoding="utf-8") == CLAUDE_MD_TEMPLATE


def test_init_does_not_overwrite_existing_claude_md(tmp_path: Path) -> None:
    custom = "# Custom CLAUDE.md the user already wrote.\n"
    (tmp_path / "CLAUDE.md").write_text(custom, encoding="utf-8")

    result = vault_ops.init(tmp_path)

    assert "CLAUDE.md" not in result.created_files
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == custom


def test_claude_md_template_lists_every_pace_tool() -> None:
    """The model uses CLAUDE.md to know which tools exist; missing one
    means the model won't reach for it."""
    expected_tools = {
        "pace_status",
        "pace_capture",
        "pace_search",
        "pace_load_project",
        "pace_list_projects",
        "pace_init",
    }
    for tool in expected_tools:
        assert tool in CLAUDE_MD_TEMPLATE, f"{tool} missing from CLAUDE.md template"


def test_claude_md_template_warns_off_maintenance_tools() -> None:
    """Phase 5 ops must NOT be invoked from a conversation."""
    for forbidden in ("pace_compact", "pace_review", "pace_archive", "pace_reindex"):
        # Mentioned only in the "tools NOT to call" section.
        assert forbidden in CLAUDE_MD_TEMPLATE
    # Section header that frames them.
    assert "NOT to call" in CLAUDE_MD_TEMPLATE


def test_claude_md_template_references_scheduled_tasks_mcp() -> None:
    """Onboarding beat 2 instructs the model to register scheduled tasks
    via Cowork's mcp__scheduled-tasks tool. Without that pointer the
    daily/weekly maintenance loop never starts."""
    assert "mcp__scheduled-tasks" in CLAUDE_MD_TEMPLATE


def test_claude_md_template_includes_three_beat_onboarding() -> None:
    for beat in ("Beat 1", "Beat 2", "Beat 3"):
        assert beat in CLAUDE_MD_TEMPLATE


def test_claude_md_template_carries_address_and_sign_rule() -> None:
    """Personality bookends are part of the always-loaded CLAUDE.md, so
    every reply in a PACE vault gets the user's name at the top and the
    assistant nickname/emoji at the bottom."""
    # Section heading is the structural anchor.
    assert "Address the user and sign every reply" in CLAUDE_MD_TEMPLATE
    # Both halves of the rule must be there.
    assert "Vary the opener" in CLAUDE_MD_TEMPLATE or "vary the" in CLAUDE_MD_TEMPLATE.lower()
    assert "Sign at the bottom" in CLAUDE_MD_TEMPLATE
    # The opt-out path must also be documented or the model will drop
    # the rule entirely when nickname is missing.
    assert "skip the sign-off" in CLAUDE_MD_TEMPLATE


def test_claude_md_template_onboarding_asks_for_emoji() -> None:
    """The onboarding script must explicitly ask for an emoji so the
    sign-off has something to render."""
    assert "emoji" in CLAUDE_MD_TEMPLATE.lower()
    # And tell the model to pick one if the user defers.
    assert "you pick" in CLAUDE_MD_TEMPLATE.lower() or "pick an emoji" in CLAUDE_MD_TEMPLATE.lower()


def test_claude_md_template_includes_identity_pin_capture() -> None:
    """The 4th capture is the working-memory identity pin that survives
    force-promotion. Without it, personality info isn't returned by
    pace_status on subsequent sessions."""
    assert "Identity bookends" in CLAUDE_MD_TEMPLATE
    # Tag set on the pin must include #user and #high-signal so the
    # force-promotion exemption applies.
    assert '"#user", "#high-signal"' in CLAUDE_MD_TEMPLATE


# ---- Scheduled-task prompts -------------------------------------------


def test_init_writes_scheduled_task_prompts(tmp_path: Path) -> None:
    vault_ops.init(tmp_path)

    compact = tmp_path / "system" / "prompts" / "compact.md"
    review = tmp_path / "system" / "prompts" / "review.md"

    assert compact.is_file()
    assert review.is_file()
    assert compact.read_text(encoding="utf-8") == COMPACT_PROMPT
    assert review.read_text(encoding="utf-8") == REVIEW_PROMPT


def test_compact_prompt_references_pace_compact_cli() -> None:
    """The prompt has to instruct Claude to invoke ``pace compact`` —
    Phase 5 lands the CLI, but the prompt forward-references it now."""
    assert "pace compact" in COMPACT_PROMPT


def test_review_prompt_references_pace_review_cli() -> None:
    assert "pace review" in REVIEW_PROMPT


def test_prompts_carry_retention_exemptions() -> None:
    """`#high-signal`, `#decision`, `#user` must never auto-archive
    (PRD §6.10 retention exemptions). Both prompts have to know."""
    for prompt in (COMPACT_PROMPT, REVIEW_PROMPT):
        for exempt_tag in ("#high-signal", "#decision", "#user"):
            assert exempt_tag in prompt, f"{exempt_tag} missing"


# ---- Git init ----------------------------------------------------------


@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
def test_init_runs_git_init_on_empty_dir(tmp_path: Path) -> None:
    result = vault_ops.init(tmp_path)
    assert result.git_initialized is True
    assert (tmp_path / ".git").is_dir()

    # Branch is `main`, not the legacy default. ``rev-parse`` fails on a
    # repo with no commits (HEAD doesn't point anywhere yet), so
    # ``symbolic-ref`` is the right query for a freshly-initialized repo.
    branch = subprocess.run(
        ["git", "-C", str(tmp_path), "symbolic-ref", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert branch == "main"


@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
def test_init_skips_git_when_already_a_repo(tmp_path: Path) -> None:
    # Pre-existing repo on a different branch.
    subprocess.run(
        ["git", "init", "-b", "trunk", str(tmp_path)],
        check=True,
        capture_output=True,
    )

    result = vault_ops.init(tmp_path)
    assert result.git_initialized is False

    branch = subprocess.run(
        ["git", "-C", str(tmp_path), "symbolic-ref", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert branch == "trunk"  # Untouched.


def test_init_succeeds_when_git_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If git isn't on PATH, init still completes — it just reports
    git_initialized=False."""
    # Point PATH at an empty dir so subprocess can't find git.
    empty = tmp_path / "empty_path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))

    result = vault_ops.init(tmp_path / "vault")
    assert result.git_initialized is False
    assert (tmp_path / "vault" / "system" / "pace_index.db").is_file()
