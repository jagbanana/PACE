"""Vault lifecycle operations: ``init`` (scaffold) and ``reindex`` (rebuild).

This module owns the rules for how a freshly-initialized vault looks on
disk, and how to rebuild the SQLite index from disk content for the case
where the user edited markdown files directly in Obsidian.

Phase 3 added ``.mcp.json`` generation. Phase 4 layers the in-vault
``CLAUDE.md``, scheduled-task prompt files, and best-effort ``git init``
on top so a fresh ``pace init`` produces a fully-bootstrapped vault.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from pace import config as pace_config
from pace import frontmatter, wikilinks
from pace import settings as pace_settings
from pace.index import Index, now_iso
from pace.io import atomic_write_text
from pace.onboarding import (
    CLAUDE_MD_TEMPLATE,
    COMPACT_PROMPT,
    HEARTBEAT_PROMPT,
    REVIEW_PROMPT,
)
from pace.paths import (
    ARCHIVED_DIR,
    FOLLOWUPS_DIR,
    FOLLOWUPS_DONE_DIR,
    INDEX_DB,
    LOGS_DIR,
    LONG_TERM_DIR,
    MEMORIES_DIR,
    PROJECTS_DIR,
    SYSTEM_DIR,
    WORKING_MEMORY,
    is_initialized,
)

# Where the scheduled-task prompts live in a vault. Kept in sync with the
# instruction in CLAUDE.md ("read system/prompts/compact.md verbatim").
PROMPTS_DIR = "system/prompts"
COMPACT_PROMPT_PATH = f"{PROMPTS_DIR}/compact.md"
REVIEW_PROMPT_PATH = f"{PROMPTS_DIR}/review.md"
HEARTBEAT_PROMPT_PATH = f"{PROMPTS_DIR}/heartbeat.md"
CLAUDE_MD_PATH = "CLAUDE.md"

VAULT_DIRS: tuple[str, ...] = (
    MEMORIES_DIR,
    LONG_TERM_DIR,
    ARCHIVED_DIR,
    PROJECTS_DIR,
    FOLLOWUPS_DIR,
    FOLLOWUPS_DONE_DIR,
    SYSTEM_DIR,
    LOGS_DIR,
    PROMPTS_DIR,
)

VAULT_GITIGNORE = """\
# PACE runtime artifacts (per CLAUDE.md / PRD §5.1)
system/pace_index.db
system/pace_index.db-wal
system/pace_index.db-shm
system/.pace.lock
system/logs/

# .mcp.json embeds the local Python path; machine-specific.
.mcp.json

# OneDrive sync residue
*.tmp
~$*
* (Conflicted Copy *).md
"""


def _build_mcp_config(root: Path) -> dict:
    """Construct the ``.mcp.json`` payload for this vault.

    Uses the *current* Python interpreter so the registered server is
    guaranteed to have ``pace`` importable. Sets ``PACE_ROOT`` so the
    server resolves the right vault even when Cowork launches it from
    a different cwd.
    """
    return {
        "mcpServers": {
            "pace": {
                "command": sys.executable,
                "args": ["-m", "pace.mcp_server"],
                "env": {"PACE_ROOT": str(root)},
            }
        }
    }


@dataclass(frozen=True)
class InitResult:
    """Outcome of ``pace init`` — used by the CLI for human-readable output."""

    root: Path
    created_dirs: list[str]
    created_files: list[str]
    already_initialized: bool
    git_initialized: bool = False
    user_config_path: Path | None = None


@dataclass(frozen=True)
class ReindexResult:
    """Counts returned from ``reindex``; surfaced by the CLI."""

    indexed: int
    removed: int
    skipped: int


def init(root: Path) -> InitResult:
    """Scaffold ``root`` as a PACE vault. Idempotent."""
    root = root.resolve()
    already = is_initialized(root)

    created_dirs: list[str] = []
    for rel in VAULT_DIRS:
        d = root / rel
        if not d.exists():
            d.mkdir(parents=True)
            created_dirs.append(rel)

    created_files: list[str] = []

    # working_memory.md ------------------------------------------------
    wm = root / WORKING_MEMORY
    if not wm.exists():
        fm = {
            "title": "Working Memory",
            "kind": "working",
            "date_created": now_iso(),
            "date_modified": now_iso(),
            "tags": [],
        }
        atomic_write_text(wm, frontmatter.dump(fm, ""))
        created_files.append(WORKING_MEMORY)

    # SQLite index ------------------------------------------------------
    db_path = root / INDEX_DB
    db_existed = db_path.is_file()
    idx = Index(db_path)
    try:
        if not db_existed:
            # Stamp vault creation time so doctor can suppress
            # "scheduled tasks never ran" warnings on day-1 vaults.
            idx.set_config("vault_created_at", now_iso())
            created_files.append(INDEX_DB)
    finally:
        idx.close()

    # Vault .gitignore --------------------------------------------------
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        atomic_write_text(gitignore, VAULT_GITIGNORE)
        created_files.append(".gitignore")

    # .mcp.json ---------------------------------------------------------
    mcp_config_path = root / ".mcp.json"
    if not mcp_config_path.exists():
        payload = json.dumps(_build_mcp_config(root), indent=2) + "\n"
        atomic_write_text(mcp_config_path, payload)
        created_files.append(".mcp.json")

    # CLAUDE.md ---------------------------------------------------------
    # Idempotent: if the user (or this source repo) already has a
    # CLAUDE.md, leave it alone. The user may have customized it.
    claude_md_path = root / CLAUDE_MD_PATH
    if not claude_md_path.exists():
        atomic_write_text(claude_md_path, CLAUDE_MD_TEMPLATE)
        created_files.append(CLAUDE_MD_PATH)

    # Scheduled-task prompts -------------------------------------------
    # Written verbatim into the vault so the user can inspect or tweak
    # them, and so the model can hand them to mcp__scheduled-tasks
    # without out-of-band coordination during onboarding beat 2.
    for rel, content in (
        (COMPACT_PROMPT_PATH, COMPACT_PROMPT),
        (REVIEW_PROMPT_PATH, REVIEW_PROMPT),
        (HEARTBEAT_PROMPT_PATH, HEARTBEAT_PROMPT),
    ):
        prompt_path = root / rel
        if not prompt_path.exists():
            atomic_write_text(prompt_path, content)
            created_files.append(rel)

    # pace_config.yaml -------------------------------------------------
    # Documented defaults for working-memory budgets and other vault
    # tunables. Idempotent; never overwrites a customized file.
    cfg_path = pace_settings.write_default_if_missing(root)
    if cfg_path is not None:
        created_files.append(pace_settings.SETTINGS_FILE)

    # Git --------------------------------------------------------------
    git_initialized = _maybe_git_init(root)

    # Per-user config --------------------------------------------------
    # Record the vault location so the plugin-launched MCP server can
    # find this folder on subsequent starts without an env var. Same
    # write happens whether init was called from the CLI or the
    # pace_init MCP tool.
    user_config_path = pace_config.set_vault_root(root)

    # If we just created the working_memory file, register it in the
    # freshly-built index so the first ``pace status`` reflects reality.
    if WORKING_MEMORY in created_files:
        idx = Index(db_path)
        try:
            text = wm.read_text(encoding="utf-8")
            fm, body = frontmatter.parse(text)
            idx.upsert_file(
                path=WORKING_MEMORY,
                kind="working",
                title=str(fm.get("title", "Working Memory")),
                body=body,
                date_created=str(fm.get("date_created", now_iso())),
                date_modified=str(fm.get("date_modified", now_iso())),
                tags=list(fm.get("tags") or []),
            )
        finally:
            idx.close()

    return InitResult(
        root=root,
        created_dirs=created_dirs,
        created_files=created_files,
        already_initialized=already,
        git_initialized=git_initialized,
        user_config_path=user_config_path,
    )


def _maybe_git_init(root: Path) -> bool:
    """Run ``git init -b main`` in ``root`` if it isn't already a repo.

    Best-effort. Skips silently if git is missing from PATH, returns
    False if the dir is already a repo. The model can suggest a first
    commit at the end of onboarding (PRD §6.1 step 5); we don't auto-
    commit because the user hasn't reviewed the contents yet.
    """
    if (root / ".git").exists():
        return False
    try:
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=root,
            check=True,
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False
    return True


def reindex(root: Path, index: Index) -> ReindexResult:
    """Rebuild the file index and wikilink refs from disk.

    Files no longer present are removed. After every file is upserted we
    refresh outbound wikilink refs so reference counts (used by pruning)
    stay aligned with reality even when the user edited markdown directly
    in Obsidian.
    """
    root = root.resolve()
    seen: set[str] = set()
    indexed = 0
    skipped = 0

    # First pass: file rows. Wikilink resolution needs the full path→id map,
    # so we record bodies for the second pass instead of re-reading.
    bodies: dict[int, str] = {}

    for md in _walk_markdown(root):
        rel = md.relative_to(root).as_posix()
        kind = _kind_from_path(rel)
        if kind is None:
            skipped += 1
            continue

        text = md.read_text(encoding="utf-8")
        fm, body = frontmatter.parse(text)

        title = str(fm.get("title") or _default_title_for(rel))
        date_created = str(fm.get("date_created") or now_iso())
        date_modified = str(fm.get("date_modified") or now_iso())
        tags = list(fm.get("tags") or [])
        aliases = list(fm.get("aliases") or [])
        project = _project_from_path(rel)

        fid = index.upsert_file(
            path=rel,
            kind=kind,
            project=project,
            title=title,
            body=body,
            aliases=aliases,
            tags=tags,
            date_created=date_created,
            date_modified=date_modified,
        )
        bodies[fid] = body
        seen.add(rel)
        indexed += 1

    # Second pass: wikilink refs. Now every file is in the index, so target
    # resolution can find every plausible link.
    paths_to_ids = index.all_paths_with_ids()
    for fid, body in bodies.items():
        index.clear_wikilink_refs_from(fid)
        for link in wikilinks.extract(body):
            target_id = wikilinks.resolve(link.target, paths_to_ids)
            if target_id is None or target_id == fid:
                continue
            index.record_ref(
                source_id=fid,
                target_id=target_id,
                ref_type="wikilink",
            )

    # Remove rows whose files were deleted on disk.
    removed = 0
    for known_path in index.all_paths():
        if known_path not in seen:
            if index.delete_file(known_path):
                removed += 1

    return ReindexResult(indexed=indexed, removed=removed, skipped=skipped)


# ---- Helpers -----------------------------------------------------------


def _walk_markdown(root: Path):
    """Yield every ``*.md`` file under ``memories/`` and ``projects/``.

    The system directory is excluded — anything in there is operational
    state, not memory content.
    """
    for sub in (MEMORIES_DIR, PROJECTS_DIR):
        base = root / sub
        if not base.is_dir():
            continue
        for path in base.rglob("*.md"):
            if path.is_file():
                yield path


def _kind_from_path(rel: str) -> str | None:
    parts = rel.split("/")
    if rel == WORKING_MEMORY:
        return "working"
    if parts[:2] == ["memories", "long_term"]:
        return "long_term"
    if parts[:2] == ["memories", "archived"]:
        return "archived"
    if len(parts) >= 3 and parts[0] == "projects":
        if parts[-1] == "summary.md" and len(parts) == 3:
            return "project_summary"
        if "notes" in parts:
            return "project_note"
    return None


def _project_from_path(rel: str) -> str | None:
    parts = rel.split("/")
    if len(parts) >= 3 and parts[0] == "projects":
        return parts[1]
    return None


def _default_title_for(rel: str) -> str:
    stem = Path(rel).stem
    return stem.replace("-", " ").replace("_", " ").title()


__all__ = [
    "InitResult",
    "ReindexResult",
    "VAULT_DIRS",
    "VAULT_GITIGNORE",
    "init",
    "reindex",
]
