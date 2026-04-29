"""Unit tests for the MCP tool functions, called directly as Python.

The protocol-level wiring is exercised by ``test_mcp_protocol.py``;
this file proves the per-tool *logic* without spinning up a subprocess.

Each test sets ``PACE_ROOT`` via monkeypatch so the tool's vault-resolution
path is the only thing under test, not Click or Cowork.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pace import vault as vault_ops
from pace.mcp_server import (
    pace_capture,
    pace_create_project,
    pace_init,
    pace_list_projects,
    pace_load_project,
    pace_search,
    pace_status,
)


@pytest.fixture
def mcp_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Initialize a vault and point the MCP tools at it via PACE_ROOT."""
    vault_ops.init(tmp_path)
    monkeypatch.setenv("PACE_ROOT", str(tmp_path))
    return tmp_path


# ---- Status ------------------------------------------------------------


def test_status_uninitialized_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PACE_ROOT", str(tmp_path / "uninit"))
    result = pace_status()
    assert result["initialized"] is False
    assert result["root"] is None
    assert result["files"] == {}


def test_status_initialized_returns_working_memory_and_counts(mcp_vault: Path) -> None:
    pace_capture(kind="working", content="A note about Q3 pricing.", tags=["business"])
    result = pace_status()
    assert result["initialized"] is True
    assert result["root"] == str(mcp_vault)
    assert result["files"].get("working") == 1
    assert "Q3 pricing" in result["working_memory"]
    assert result["warnings"] == []


def test_status_surfaces_conflicted_copy_warnings(mcp_vault: Path) -> None:
    # Fabricate a OneDrive-style conflicted-copy file. The model is
    # supposed to raise this with the user before doing other work.
    conflict = mcp_vault / "memories" / "long_term" / "people (Conflicted Copy 2026-04-01).md"
    conflict.parent.mkdir(parents=True, exist_ok=True)
    conflict.write_text("Conflicted version.\n", encoding="utf-8")
    result = pace_status()
    assert result["warnings"]
    assert any("Conflicted" in w for w in result["warnings"])


# ---- Capture -----------------------------------------------------------


def test_capture_working_returns_path(mcp_vault: Path) -> None:
    result = pace_capture(
        kind="working",
        content="The user prefers brevity in writing.",
        tags=["#preference", "#user"],
    )
    assert result["path"] == "memories/working_memory.md"
    assert result["kind"] == "working"


def test_capture_long_term_requires_topic(mcp_vault: Path) -> None:
    result = pace_capture(kind="long_term", content="A fact.")
    assert "error" in result
    assert "topic" in result["error"].lower()


def test_capture_project_summary_requires_existing_project(mcp_vault: Path) -> None:
    result = pace_capture(
        kind="project_summary", content="Kickoff Monday.", project="Ghost"
    )
    assert "error" in result
    assert "project" in result["error"].lower()


def test_capture_uninitialized_returns_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PACE_ROOT", str(tmp_path / "uninit"))
    result = pace_capture(kind="working", content="x")
    assert result == {
        "error": "Vault not initialized. Call pace_init first.",
        "initialized": False,
    }


# ---- Search ------------------------------------------------------------


def test_search_returns_ranked_hits(mcp_vault: Path) -> None:
    pace_capture(kind="working", content="Q3 pricing review on Thursday.")
    result = pace_search(query="Q3 pricing")
    hits = result["hits"]
    assert len(hits) == 1
    assert hits[0]["path"] == "memories/working_memory.md"
    assert "pricing" in hits[0]["snippet"].lower()


def test_search_scope_filter(mcp_vault: Path) -> None:
    pace_create_project(name="Alpha")
    pace_capture(kind="project_summary", project="Alpha", content="Kickoff Monday.")
    pace_capture(kind="working", content="Random working note about kickoff.")

    only_projects = pace_search(query="kickoff", scope="projects")
    only_memory = pace_search(query="kickoff", scope="memory")
    assert all(h["kind"] == "project_summary" for h in only_projects["hits"])
    assert all(h["kind"] == "working" for h in only_memory["hits"])


# ---- Project lifecycle -------------------------------------------------


def test_create_then_list_projects(mcp_vault: Path) -> None:
    created = pace_create_project(name="Alpha", aliases=["alpha-effort"], title="Project Alpha")
    assert created["name"] == "Alpha"
    assert created["aliases"] == ["alpha-effort"]
    assert created["summary_path"] == "projects/Alpha/summary.md"

    listed = pace_list_projects()
    assert len(listed["projects"]) == 1
    assert listed["projects"][0]["title"] == "Project Alpha"


def test_create_project_invalid_name(mcp_vault: Path) -> None:
    result = pace_create_project(name="has spaces")
    assert "error" in result


def test_create_project_collision(mcp_vault: Path) -> None:
    pace_create_project(name="Alpha")
    result = pace_create_project(name="Alpha")
    assert "error" in result


# ---- Load --------------------------------------------------------------


def test_load_project_resolves_by_alias(mcp_vault: Path) -> None:
    pace_create_project(name="Alpha", aliases=["the-effort"])
    pace_capture(kind="project_summary", project="Alpha", content="Initial notes.")
    result = pace_load_project(name="the-effort")
    assert "error" not in result
    assert result["project"]["name"] == "Alpha"
    assert "Initial notes." in result["summary"]


def test_load_project_unknown_returns_error(mcp_vault: Path) -> None:
    result = pace_load_project(name="Ghost")
    assert "error" in result


# ---- Init --------------------------------------------------------------


def test_init_bootstraps_empty_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "fresh"
    monkeypatch.setenv("PACE_ROOT", str(target))
    result = pace_init()
    assert result["root"] == str(target.resolve())
    assert ".mcp.json" in result["created_files"]
    assert (target / ".mcp.json").is_file()
    assert (target / "system" / "pace_index.db").is_file()


def test_init_is_idempotent(mcp_vault: Path) -> None:
    second = pace_init()
    # Already initialized: nothing new should be created.
    assert second["already_initialized"] is True
    assert second["created_dirs"] == []
    assert second["created_files"] == []
