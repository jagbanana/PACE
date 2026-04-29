"""Wikilink extraction, resolution, and rewriting."""

from __future__ import annotations

from pace import wikilinks


def test_extract_handles_bare_pipe_and_section() -> None:
    body = "See [[Alpha]] and [[Beta|the beta]] and [[Gamma#deadlines]]."
    matches = wikilinks.extract(body)
    targets = [m.target for m in matches]
    assert targets == ["Alpha", "Beta", "Gamma"]
    assert matches[1].display == "|the beta"
    assert matches[2].section == "#deadlines"


def test_extract_ignores_empty_brackets() -> None:
    assert wikilinks.extract("Some [[]] empty.") == []


def test_extract_keeps_multiple_links_on_one_line_distinct() -> None:
    body = "[[A]] [[B]] [[C]]"
    matches = wikilinks.extract(body)
    assert [m.target for m in matches] == ["A", "B", "C"]


def test_resolve_exact_path_match() -> None:
    paths = {"memories/long_term/people.md": 1, "memories/working_memory.md": 2}
    assert wikilinks.resolve("memories/long_term/people.md", paths) == 1


def test_resolve_topic_shorthand() -> None:
    paths = {"memories/long_term/people.md": 7}
    # [[People]] should resolve to long_term/people.md via the topic candidate.
    assert wikilinks.resolve("People", paths) == 7


def test_resolve_project_summary_shorthand() -> None:
    paths = {"projects/Alpha/summary.md": 12}
    assert wikilinks.resolve("Alpha", paths) == 12


def test_resolve_falls_back_to_stem_match() -> None:
    paths = {"projects/Alpha/notes/launch-plan.md": 4}
    # User wrote [[launch-plan]] without the path; stem fallback wins.
    assert wikilinks.resolve("launch-plan", paths) == 4


def test_resolve_returns_none_when_unknown() -> None:
    assert wikilinks.resolve("Unknown", {"memories/working_memory.md": 1}) is None


def test_rewrite_swaps_exact_target() -> None:
    body = "Working on [[Alpha]] this week, see [[Alpha|details]]."
    new, count = wikilinks.rewrite(body, {"Alpha": "Beta"})
    assert count == 2
    assert "[[Beta]]" in new
    assert "[[Beta|details]]" in new
    assert "[[Alpha]]" not in new


def test_rewrite_swaps_path_prefix() -> None:
    body = "See [[projects/Alpha/notes/launch]]."
    new, count = wikilinks.rewrite(
        body, {"projects/Alpha/": "projects/Beta/"}
    )
    assert count == 1
    assert "[[projects/Beta/notes/launch]]" in new


def test_rewrite_preserves_unrelated_links() -> None:
    body = "[[Alpha]] and [[OtherProject]]"
    new, count = wikilinks.rewrite(body, {"Alpha": "Beta"})
    assert count == 1
    assert "[[OtherProject]]" in new
