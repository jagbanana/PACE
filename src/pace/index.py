"""SQLite + FTS5 index over the vault's markdown files.

Schema is documented in PRD §7.1. This module owns DB access; callers
upsert and delete files by path, and search returns ranked snippets.

Reference tracking (the ``refs`` table and ``mark_referenced``) lands in
Phase 2 alongside project loads and wikilink parsing. The schema is
created up front so later phases don't require migrations.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# Allowed values for the ``files.kind`` column.
KINDS: frozenset[str] = frozenset(
    {"working", "long_term", "project_summary", "project_note", "archived"}
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    kind TEXT NOT NULL,
    project TEXT,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    aliases TEXT,
    date_created TEXT NOT NULL,
    date_modified TEXT NOT NULL,
    tags TEXT
);

CREATE INDEX IF NOT EXISTS idx_files_kind ON files(kind);
CREATE INDEX IF NOT EXISTS idx_files_project ON files(project);

CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    title, body, tags, aliases,
    content='files', content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS refs (
    id INTEGER PRIMARY KEY,
    source_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
    target_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    ref_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_refs_target_time ON refs(target_id, occurred_at);

CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class SearchHit:
    """A single FTS5 result row, ready to display or hand back over MCP."""

    path: str
    title: str
    kind: str
    project: str | None
    snippet: str
    rank: float


@dataclass(frozen=True)
class FileRecord:
    """Mirror of one ``files`` row, used when reading the index."""

    id: int
    path: str
    kind: str
    project: str | None
    title: str
    body: str
    aliases: list[str]
    tags: list[str]
    date_created: str
    date_modified: str


class Index:
    """Thin wrapper around a SQLite connection holding the vault index."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # ``check_same_thread=False`` lets the MCP server (which may dispatch
        # tools on a worker thread) share the connection. We serialize writes
        # via portalocker at the file-write layer.
        self._conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        self._conn.row_factory = sqlite3.Row
        self._configure()
        self._apply_schema()

    # ---- Setup ---------------------------------------------------------

    def _configure(self) -> None:
        cur = self._conn.cursor()
        cur.execute("PRAGMA journal_mode = WAL;")
        cur.execute("PRAGMA synchronous = NORMAL;")
        cur.execute("PRAGMA foreign_keys = ON;")
        cur.close()

    def _apply_schema(self) -> None:
        with self._conn:
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Context manager wrapping a write transaction."""
        with self._conn:
            yield self._conn

    # ---- File upserts --------------------------------------------------

    def upsert_file(
        self,
        *,
        path: str,
        kind: str,
        title: str,
        body: str,
        date_created: str,
        date_modified: str,
        project: str | None = None,
        aliases: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> int:
        """Insert or update a file row. Returns the row id."""
        if kind not in KINDS:
            raise ValueError(f"Unknown kind {kind!r}; expected one of {sorted(KINDS)}.")
        aliases_json = json.dumps(aliases or [], ensure_ascii=False)
        tags_json = json.dumps(tags or [], ensure_ascii=False)

        with self._conn:
            cur = self._conn.execute(
                "SELECT id FROM files WHERE path = ?",
                (path,),
            )
            existing = cur.fetchone()
            if existing is None:
                cur = self._conn.execute(
                    """
                    INSERT INTO files
                        (path, kind, project, title, body, aliases,
                         date_created, date_modified, tags)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        path,
                        kind,
                        project,
                        title,
                        body,
                        aliases_json,
                        date_created,
                        date_modified,
                        tags_json,
                    ),
                )
                file_id = cur.lastrowid
                assert file_id is not None
                self._fts_insert(file_id, title, body, tags_json, aliases_json)
            else:
                file_id = existing["id"]
                # External-content FTS5 needs an explicit delete before insert
                # to avoid duplicate rows. ``UPDATE`` on an external-content
                # FTS table requires the same rowid trick, so we rebuild.
                self._fts_delete(file_id)
                self._conn.execute(
                    """
                    UPDATE files SET
                        kind = ?, project = ?, title = ?, body = ?,
                        aliases = ?, date_modified = ?, tags = ?
                    WHERE id = ?
                    """,
                    (
                        kind,
                        project,
                        title,
                        body,
                        aliases_json,
                        date_modified,
                        tags_json,
                        file_id,
                    ),
                )
                self._fts_insert(file_id, title, body, tags_json, aliases_json)

        return file_id

    def _fts_insert(
        self, rowid: int, title: str, body: str, tags_json: str, aliases_json: str
    ) -> None:
        self._conn.execute(
            "INSERT INTO files_fts(rowid, title, body, tags, aliases) "
            "VALUES (?, ?, ?, ?, ?)",
            (rowid, title, body, tags_json, aliases_json),
        )

    def _fts_delete(self, rowid: int) -> None:
        # External-content FTS5 deletion uses the special 'delete' command.
        row = self._conn.execute(
            "SELECT title, body, tags, aliases FROM files WHERE id = ?",
            (rowid,),
        ).fetchone()
        if row is None:
            return
        self._conn.execute(
            "INSERT INTO files_fts(files_fts, rowid, title, body, tags, aliases) "
            "VALUES ('delete', ?, ?, ?, ?, ?)",
            (rowid, row["title"], row["body"], row["tags"], row["aliases"]),
        )

    def delete_file(self, path: str) -> bool:
        """Delete the row for ``path``. Returns True if a row was removed."""
        with self._conn:
            cur = self._conn.execute("SELECT id FROM files WHERE path = ?", (path,))
            row = cur.fetchone()
            if row is None:
                return False
            self._fts_delete(row["id"])
            self._conn.execute("DELETE FROM files WHERE id = ?", (row["id"],))
        return True

    def clear_files(self) -> None:
        """Drop every file row. Used by ``pace reindex --rebuild``."""
        with self._conn:
            self._conn.execute(
                "INSERT INTO files_fts(files_fts) VALUES ('delete-all')"
            )
            self._conn.execute("DELETE FROM files")

    # ---- Reads ---------------------------------------------------------

    def get_by_path(self, path: str) -> FileRecord | None:
        row = self._conn.execute(
            "SELECT * FROM files WHERE path = ?",
            (path,),
        ).fetchone()
        return _row_to_record(row) if row else None

    def all_paths(self) -> list[str]:
        rows = self._conn.execute("SELECT path FROM files ORDER BY path").fetchall()
        return [r["path"] for r in rows]

    def all_paths_with_ids(self) -> dict[str, int]:
        """Path → file id, useful for bulk wikilink resolution."""
        rows = self._conn.execute("SELECT id, path FROM files").fetchall()
        return {row["path"]: row["id"] for row in rows}

    def get_id(self, path: str) -> int | None:
        row = self._conn.execute("SELECT id FROM files WHERE path = ?", (path,)).fetchone()
        return row["id"] if row else None

    def count_by_kind(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT kind, COUNT(*) AS n FROM files GROUP BY kind"
        ).fetchall()
        return {row["kind"]: row["n"] for row in rows}

    def list_projects(self) -> list[dict[str, object]]:
        """Return one row per project, with its summary's metadata.

        ``date_modified`` is taken from the summary file — the canonical
        "when did this project last move" timestamp.
        """
        rows = self._conn.execute(
            """
            SELECT project, title, aliases, date_created, date_modified, path
            FROM files
            WHERE kind = 'project_summary'
            ORDER BY project
            """
        ).fetchall()
        return [
            {
                "project": row["project"],
                "title": row["title"],
                "aliases": json.loads(row["aliases"] or "[]"),
                "date_created": row["date_created"],
                "date_modified": row["date_modified"],
                "summary_path": row["path"],
            }
            for row in rows
        ]

    # ---- Refs (wikilinks + project loads) -----------------------------

    def record_ref(
        self,
        *,
        target_id: int,
        ref_type: str,
        source_id: int | None = None,
        occurred_at: str | None = None,
    ) -> None:
        """Insert one row into ``refs``.

        ``ref_type`` is ``'wikilink'`` (source file cites the target) or
        ``'project_load'`` (an MCP/CLI call loaded the target — no source).
        """
        if ref_type not in {"wikilink", "project_load"}:
            raise ValueError(f"Unknown ref_type {ref_type!r}.")
        with self._conn:
            self._conn.execute(
                "INSERT INTO refs(source_id, target_id, ref_type, occurred_at) "
                "VALUES (?, ?, ?, ?)",
                (source_id, target_id, ref_type, occurred_at or now_iso()),
            )

    def clear_wikilink_refs_from(self, source_id: int) -> int:
        """Drop all wikilink rows originating at ``source_id``. Returns count."""
        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM refs WHERE source_id = ? AND ref_type = 'wikilink'",
                (source_id,),
            )
            return cur.rowcount

    def reference_count(self, target_id: int, *, since_days: int = 60) -> int:
        """Count refs to ``target_id`` within the last ``since_days``."""
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM refs "
            "WHERE target_id = ? AND occurred_at > date('now', ?)",
            (target_id, f"-{since_days} days"),
        ).fetchone()
        return int(row["n"]) if row else 0

    def refs_to(self, target_id: int) -> list[dict[str, object]]:
        """All refs targeting ``target_id``, newest first. Used by tests."""
        rows = self._conn.execute(
            "SELECT source_id, ref_type, occurred_at FROM refs "
            "WHERE target_id = ? ORDER BY occurred_at DESC",
            (target_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- Search --------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        scope: str | None = None,
        project: str | None = None,
        limit: int = 10,
    ) -> list[SearchHit]:
        """FTS5 search returning ranked hits with snippets.

        ``scope`` filters by ``kind`` family: ``"memory"`` selects
        ``working`` + ``long_term``; ``"projects"`` selects
        ``project_summary`` + ``project_note``; ``None`` searches all
        non-archived kinds.
        """
        kind_filter = _scope_to_kinds(scope)
        sql = [
            "SELECT files.path, files.title, files.kind, files.project,",
            "       snippet(files_fts, 1, '«', '»', '…', 16) AS snippet,",
            "       bm25(files_fts) AS rank",
            "FROM files_fts",
            "JOIN files ON files.id = files_fts.rowid",
            "WHERE files_fts MATCH ?",
        ]
        params: list[object] = [query]
        if kind_filter is not None:
            placeholders = ",".join("?" for _ in kind_filter)
            sql.append(f"  AND files.kind IN ({placeholders})")
            params.extend(kind_filter)
        if project is not None:
            sql.append("  AND files.project = ?")
            params.append(project)
        sql.append("ORDER BY rank LIMIT ?")
        params.append(limit)

        rows = self._conn.execute("\n".join(sql), params).fetchall()
        return [
            SearchHit(
                path=row["path"],
                title=row["title"],
                kind=row["kind"],
                project=row["project"],
                snippet=row["snippet"],
                rank=row["rank"],
            )
            for row in rows
        ]

    # ---- Config --------------------------------------------------------

    def get_config(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM config WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set_config(self, key: str, value: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO config(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )


def now_iso() -> str:
    """Naive ISO-8601 timestamp without timezone — vault is single-machine."""
    return datetime.now().replace(microsecond=0).isoformat()


def _scope_to_kinds(scope: str | None) -> tuple[str, ...] | None:
    if scope is None:
        return ("working", "long_term", "project_summary", "project_note")
    if scope == "memory":
        return ("working", "long_term")
    if scope == "projects":
        return ("project_summary", "project_note")
    if scope == "all":
        # "all" includes archived; useful for forensic searches.
        return None
    raise ValueError(
        f"Unknown scope {scope!r}; expected one of memory, projects, all, or None."
    )


def _row_to_record(row: sqlite3.Row) -> FileRecord:
    return FileRecord(
        id=row["id"],
        path=row["path"],
        kind=row["kind"],
        project=row["project"],
        title=row["title"],
        body=row["body"],
        aliases=json.loads(row["aliases"] or "[]"),
        tags=json.loads(row["tags"] or "[]"),
        date_created=row["date_created"],
        date_modified=row["date_modified"],
    )
