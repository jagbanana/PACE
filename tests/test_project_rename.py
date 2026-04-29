"""Project rename preserves wikilinks across the vault and re-indexes correctly."""

from __future__ import annotations

from pathlib import Path

from pace import projects, wikilinks
from pace.capture import capture
from pace.index import Index


def test_rename_moves_directory_and_updates_index(vault: Path, index: Index) -> None:
    projects.create_project(vault, "Alpha", index=index)
    capture(
        vault,
        kind="project_summary",
        project="Alpha",
        content="Original summary content.",
        index=index,
    )

    projects.rename_project(vault, "Alpha", "Beta", index=index)

    assert not (vault / "projects" / "Alpha").exists()
    assert (vault / "projects" / "Beta" / "summary.md").is_file()

    # Index reflects the new path; old path is gone.
    assert index.get_by_path("projects/Alpha/summary.md") is None
    new_record = index.get_by_path("projects/Beta/summary.md")
    assert new_record is not None
    assert new_record.project == "Beta"


def test_rename_rewrites_wikilinks_in_other_files(
    vault: Path, index: Index
) -> None:
    projects.create_project(vault, "Alpha", index=index)
    projects.create_project(vault, "Other", index=index)

    # Note in Other links to Alpha by name and by full path.
    capture(
        vault,
        kind="project_note",
        project="Other",
        note="cross-refs",
        content=(
            "We rely on [[Alpha]] for delivery. "
            "Specifically [[projects/Alpha/notes/launch]] is the source of truth."
        ),
        index=index,
    )

    projects.rename_project(vault, "Alpha", "Beta", index=index)

    note_path = vault / "projects" / "Other" / "notes" / "cross-refs.md"
    body = note_path.read_text(encoding="utf-8")
    extracted = [m.target for m in wikilinks.extract(body)]

    # Both wikilink shapes were rewritten.
    assert "Beta" in extracted
    assert "projects/Beta/notes/launch" in extracted
    assert "Alpha" not in extracted
    assert "projects/Alpha/notes/launch" not in extracted


def test_rename_rejects_collision(vault: Path, index: Index) -> None:
    projects.create_project(vault, "Alpha", index=index)
    projects.create_project(vault, "Beta", index=index)
    import pytest

    with pytest.raises(FileExistsError):
        projects.rename_project(vault, "Alpha", "Beta", index=index)
