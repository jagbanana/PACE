"""Project create / load / resolve / alias / rename."""

from __future__ import annotations

from pathlib import Path

import pytest

from pace import projects
from pace.capture import capture
from pace.index import Index
from pace.paths import PROJECTS_DIR

# ---- Create / list -----------------------------------------------------


def test_create_scaffolds_dir_summary_and_notes(vault: Path, index: Index) -> None:
    proj = projects.create_project(vault, "Alpha", index=index)

    assert proj.name == "Alpha"
    assert proj.title == "Alpha"
    assert (vault / PROJECTS_DIR / "Alpha" / "summary.md").is_file()
    assert (vault / PROJECTS_DIR / "Alpha" / "notes").is_dir()

    # Summary is indexed.
    record = index.get_by_path("projects/Alpha/summary.md")
    assert record is not None
    assert record.kind == "project_summary"


def test_create_rejects_invalid_name(vault: Path, index: Index) -> None:
    with pytest.raises(ValueError):
        projects.create_project(vault, "no spaces allowed", index=index)
    with pytest.raises(ValueError):
        projects.create_project(vault, "!leading-symbol", index=index)


def test_create_rejects_existing_project(vault: Path, index: Index) -> None:
    projects.create_project(vault, "Alpha", index=index)
    with pytest.raises(FileExistsError):
        projects.create_project(vault, "Alpha", index=index)


def test_list_projects_returns_disk_state(vault: Path, index: Index) -> None:
    projects.create_project(vault, "Alpha", index=index)
    projects.create_project(vault, "Beta", aliases=["b"], index=index)

    found = projects.list_projects(vault)
    assert [p.name for p in found] == ["Alpha", "Beta"]
    assert found[1].aliases == ["b"]


# ---- Resolve -----------------------------------------------------------


def test_resolve_by_exact_name(vault: Path, index: Index) -> None:
    projects.create_project(vault, "Alpha", index=index)
    proj = projects.resolve(vault, "Alpha", index)
    assert proj is not None and proj.name == "Alpha"


def test_resolve_by_alias_case_insensitive(vault: Path, index: Index) -> None:
    projects.create_project(vault, "Alpha", aliases=["the-alpha-effort"], index=index)
    proj = projects.resolve(vault, "The-Alpha-Effort", index)
    assert proj is not None and proj.name == "Alpha"


def test_resolve_by_title(vault: Path, index: Index) -> None:
    projects.create_project(vault, "Alpha", title="Project Alpha", index=index)
    proj = projects.resolve(vault, "project alpha", index)
    assert proj is not None and proj.name == "Alpha"


def test_resolve_returns_none_for_unknown(vault: Path, index: Index) -> None:
    projects.create_project(vault, "Alpha", index=index)
    assert projects.resolve(vault, "Nonexistent", index) is None


def test_resolve_via_fts_fuzzy_on_summary_content(vault: Path, index: Index) -> None:
    projects.create_project(vault, "Alpha", index=index)
    capture(
        vault,
        kind="project_summary",
        project="Alpha",
        content="This project tracks the redesign of the customer onboarding funnel.",
        index=index,
    )
    # Search by a distinctive token from the summary — FTS5 should find it.
    proj = projects.resolve(vault, "onboarding funnel", index)
    assert proj is not None and proj.name == "Alpha"


# ---- Load --------------------------------------------------------------


def test_load_returns_summary_body(vault: Path, index: Index) -> None:
    projects.create_project(vault, "Alpha", index=index)
    capture(
        vault,
        kind="project_summary",
        project="Alpha",
        content="Status: kickoff complete; next milestone end of month.",
        index=index,
    )
    result = projects.load_project(vault, "Alpha", index=index)
    assert result is not None
    proj, body = result
    assert proj.name == "Alpha"
    assert "kickoff complete" in body


def test_load_records_project_load_ref(vault: Path, index: Index) -> None:
    projects.create_project(vault, "Alpha", index=index)
    target_id = index.get_id("projects/Alpha/summary.md")
    assert target_id is not None

    # Before loading: zero refs.
    assert index.reference_count(target_id) == 0

    projects.load_project(vault, "Alpha", index=index)
    projects.load_project(vault, "Alpha", index=index)

    refs = index.refs_to(target_id)
    assert len(refs) == 2
    assert all(r["ref_type"] == "project_load" for r in refs)
    assert all(r["source_id"] is None for r in refs)
    assert index.reference_count(target_id) == 2


# ---- Aliases -----------------------------------------------------------


def test_add_and_remove_alias(vault: Path, index: Index) -> None:
    projects.create_project(vault, "Alpha", index=index)
    proj = projects.add_alias(vault, "Alpha", "alpha-effort", index=index)
    assert proj.aliases == ["alpha-effort"]
    proj = projects.add_alias(vault, "Alpha", "AE", index=index)
    assert proj.aliases == ["alpha-effort", "AE"]

    proj = projects.remove_alias(vault, "Alpha", "alpha-effort", index=index)
    assert proj.aliases == ["AE"]


def test_add_alias_dedupes_case_insensitive(vault: Path, index: Index) -> None:
    projects.create_project(vault, "Alpha", aliases=["the-effort"], index=index)
    proj = projects.add_alias(vault, "Alpha", "THE-EFFORT", index=index)
    # Same alias, different case: kept as-is once.
    assert len(proj.aliases) == 1
