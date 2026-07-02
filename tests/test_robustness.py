"""Robustness batch regression tests.

Covers three hardening fixes:

* Malformed FTS5 queries surface as a catchable ``SearchQueryError``
  (a ``ValueError``) instead of an unhandled ``sqlite3.OperationalError``.
* The SQLite connection sets a ``busy_timeout`` so concurrent writers
  wait rather than failing immediately with "database is locked".
* ``pace init`` writes ``system/pace_config.yaml`` atomically (no
  leftover ``.tmp`` sibling; content intact).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pace import settings as pace_settings
from pace import vault as vault_ops
from pace.capture import capture
from pace.index import Index, SearchQueryError
from pace.mcp_server import pace_search
from pace.paths import INDEX_DB

# ---- #1 Malformed FTS5 query handling ---------------------------------


@pytest.mark.parametrize(
    "bad_query",
    ['"unbalanced', "foo AND", "NEAR(", "* ", "(unclosed"],
)
def test_search_malformed_query_raises_search_query_error(
    vault: Path, index: Index, bad_query: str
) -> None:
    capture(vault, kind="working", content="Some indexed content.", index=index)
    with pytest.raises(SearchQueryError):
        index.search(bad_query)


def test_search_query_error_is_value_error(vault: Path, index: Index) -> None:
    """Subclassing ValueError is what lets existing `except ValueError`
    guards (MCP pace_search, CLI search) catch it."""
    with pytest.raises(ValueError):
        index.search('"still open')


def test_mcp_search_returns_error_on_bad_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_ops.init(tmp_path)
    monkeypatch.setenv("PACE_ROOT", str(tmp_path))
    result = pace_search(query='"unbalanced')
    assert "error" in result
    assert "hits" not in result


def test_valid_query_still_works_after_hardening(vault: Path, index: Index) -> None:
    capture(vault, kind="working", content="Quarterly gross margin review.", index=index)
    hits = index.search("gross margin")
    assert len(hits) == 1


# ---- #4 busy_timeout --------------------------------------------------


def test_index_sets_busy_timeout(vault: Path, index: Index) -> None:
    row = index._conn.execute("PRAGMA busy_timeout;").fetchone()  # noqa: SLF001
    assert int(row[0]) >= 5000


def test_second_connection_can_write_while_first_open(vault: Path) -> None:
    """Two Index handles on one vault (the multi-window case) should both
    be able to write; the busy_timeout keeps the second from failing
    outright on contention."""
    a = Index(vault / INDEX_DB)
    b = Index(vault / INDEX_DB)
    try:
        capture(vault, kind="working", content="From handle A.", index=a)
        capture(vault, kind="long_term", topic="misc", content="From handle B.", index=b)
        assert b.search("handle A")  # a's write is visible to b
        assert a.search("handle B")  # b's write is visible to a
    finally:
        a.close()
        b.close()


# ---- #5 atomic settings write -----------------------------------------


def test_write_default_config_is_atomic_no_tmp_left(tmp_path: Path) -> None:
    written = pace_settings.write_default_if_missing(tmp_path)
    assert written is not None
    assert written.is_file()
    # The atomic write renames <path>.tmp over the target; no stray temp.
    assert not written.with_name(written.name + ".tmp").exists()
    text = written.read_text(encoding="utf-8")
    assert "soft_chars" in text and "heartbeat" in text
    # LF-normalized like every other atomic vault write.
    assert "\r\n" not in text
