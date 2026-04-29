"""Project-scoped capture: project_summary and project_note kinds."""

from __future__ import annotations

from pathlib import Path

import pytest

from pace import projects
from pace.capture import capture
from pace.index import Index


def test_project_summary_capture_appends_and_indexes(
    vault: Path, index: Index
) -> None:
    projects.create_project(vault, "Alpha", index=index)
    target = capture(
        vault,
        kind="project_summary",
        project="Alpha",
        content="Kickoff scheduled for Monday; Alex owns delivery.",
        tags=["high-signal"],
        index=index,
    )
    assert target == vault / "projects" / "Alpha" / "summary.md"

    hits = index.search("kickoff", scope="projects", project="Alpha")
    assert len(hits) == 1
    assert hits[0].kind == "project_summary"
    assert hits[0].project == "Alpha"


def test_project_note_capture_creates_note_file(vault: Path, index: Index) -> None:
    projects.create_project(vault, "Alpha", index=index)
    target = capture(
        vault,
        kind="project_note",
        project="Alpha",
        note="Interview Jane",
        content="Jane prefers async over meetings; flagged Q3 risk.",
        index=index,
    )
    assert target.name == "interview-jane.md"
    assert target.parent.name == "notes"

    hits = index.search("Jane Q3", scope="projects", project="Alpha")
    assert len(hits) == 1
    assert hits[0].kind == "project_note"


def test_project_capture_requires_existing_project(
    vault: Path, index: Index
) -> None:
    with pytest.raises(FileNotFoundError):
        capture(
            vault,
            kind="project_summary",
            project="Ghost",
            content="No such project.",
            index=index,
        )


def test_search_filtered_by_project(vault: Path, index: Index) -> None:
    projects.create_project(vault, "Alpha", index=index)
    projects.create_project(vault, "Beta", index=index)
    capture(
        vault,
        kind="project_note",
        project="Alpha",
        note="kickoff",
        content="The shared keyword is widget.",
        index=index,
    )
    capture(
        vault,
        kind="project_note",
        project="Beta",
        note="kickoff",
        content="Also a widget here.",
        index=index,
    )

    alpha_hits = index.search("widget", project="Alpha")
    beta_hits = index.search("widget", project="Beta")
    assert len(alpha_hits) == 1
    assert len(beta_hits) == 1
    assert alpha_hits[0].project == "Alpha"
    assert beta_hits[0].project == "Beta"


def test_capture_records_outbound_wikilink_refs(vault: Path, index: Index) -> None:
    projects.create_project(vault, "Alpha", index=index)
    projects.create_project(vault, "Beta", index=index)

    # Capture a note in Alpha that links to Beta — should produce a refs row.
    capture(
        vault,
        kind="project_note",
        project="Alpha",
        note="reference",
        content="See [[Beta]] for adjacent context.",
        index=index,
    )

    beta_id = index.get_id("projects/Beta/summary.md")
    assert beta_id is not None
    refs = index.refs_to(beta_id)
    assert len(refs) == 1
    assert refs[0]["ref_type"] == "wikilink"
    assert refs[0]["source_id"] is not None
