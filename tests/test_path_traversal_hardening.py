"""Regression tests: caller-supplied ids/names can't traverse out of the vault.

A PACE vault is driven by an LLM whose tool arguments can be influenced by
untrusted text it has ingested (web pages, emails, documents). These tests pin
the invariant that caller-supplied identifiers (followup ids, project names)
cannot escape the vault root to overwrite or unlink arbitrary files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pace import followups as fu
from pace.capture import capture
from pace.index import Index


def test_resolve_followup_rejects_traversal_id_and_preserves_target(
    vault: Path, index: Index
) -> None:
    # Seed a real memory file the traversal id would resolve to.
    victim = capture(
        vault, kind="long_term", topic="user",
        content="Elliot is the user.", index=index,
    )
    assert victim.is_file()

    # "../memories/long_term/user" joins under followups/ and resolves onto the
    # victim. Pre-hardening this read + unlink()'d it; now it must be refused.
    assert fu.resolve_followup(vault, "../memories/long_term/user") is None
    assert victim.is_file()


def test_update_status_rejects_traversal_id(vault: Path) -> None:
    assert fu.update_status(vault, "../memories/long_term/user", status="ready") is None


def test_resolve_followup_still_works_for_valid_id(vault: Path) -> None:
    created = fu.add_followup(vault, body="ping Alex about pricing", trigger="manual")
    resolved = fu.resolve_followup(vault, created.id, status="done")
    assert resolved is not None
    assert resolved.status == "done"


@pytest.mark.parametrize("bad", ["../evil", "../../evil", "a/b", "..", "foo/../bar", "/abs"])
def test_capture_rejects_traversing_project_name(
    vault: Path, index: Index, bad: str
) -> None:
    with pytest.raises(ValueError):
        capture(
            vault, kind="project_note", project=bad, note="x",
            content="bad", index=index,
        )
    with pytest.raises(ValueError):
        capture(
            vault, kind="project_summary", project=bad,
            content="bad", index=index,
        )
