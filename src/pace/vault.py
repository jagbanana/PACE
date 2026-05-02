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


def _detect_plugin_root(start: Path | None = None) -> Path | None:
    """Walk up from ``start`` looking for ``.claude-plugin/plugin.json``.

    When ``pace init`` is invoked via ``uvx --from <plugin>/server pace``
    (i.e. the bootstrap path that runs from a Claude Code plugin
    install), ``pace.__file__`` lives inside the plugin directory tree
    and walking up four levels finds the plugin root. When ``pace
    init`` is run from a developer venv or a regular pip install,
    nothing on the way up has ``.claude-plugin/plugin.json`` directly
    under it, so this returns ``None`` and the caller falls back to
    embedding ``sys.executable`` in the project ``.mcp.json``.

    Note: the dev *source* repo has the manifest at
    ``plugin/.claude-plugin/plugin.json`` (one extra level), so a dev
    invocation does **not** false-positive — we only match when the
    manifest sits *directly* under a candidate dir.
    """
    if start is None:
        start = Path(__file__).resolve()
    cur = start.parent if start.is_file() else start
    for _ in range(10):
        if (cur / ".claude-plugin" / "plugin.json").is_file():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def _discover_plugin_root(home: Path | None = None) -> Path | None:
    """Best-effort search for the pace-memory plugin install directory.

    Looks under ``~/.claude/plugins/marketplaces/*/pace-memory/`` for a
    subdirectory containing both ``.claude-plugin/plugin.json`` and
    ``server/``. Returns the first match. Used by ``pace bootstrap`` so
    technical users don't have to type the full plugin path.

    Pass ``home`` for testing; defaults to ``Path.home()``.
    """
    base = (home or Path.home()) / ".claude" / "plugins" / "marketplaces"
    if not base.is_dir():
        return None

    for marketplace in sorted(base.iterdir()):
        if not marketplace.is_dir():
            continue
        candidate = marketplace / "pace-memory"
        if (
            (candidate / ".claude-plugin" / "plugin.json").is_file()
            and (candidate / "server").is_dir()
        ):
            return candidate.resolve()
    return None


def install_pace_persistently(plugin_root: Path) -> None:
    """Run ``uv tool install --force <plugin>/server``.

    Used by ``pace bootstrap`` (where pace itself isn't currently
    running, so file-lock errors that bit v0.3.4 don't apply). Raises
    a :class:`subprocess.CalledProcessError` on failure so the CLI
    surfaces it cleanly.
    """
    server_dir = plugin_root / "server"
    if not (server_dir / "pyproject.toml").is_file():
        raise FileNotFoundError(
            f"Plugin server source not found at {server_dir}; "
            "verify --plugin-root or that the plugin install is intact."
        )
    subprocess.run(
        ["uv", "tool", "install", "--force", str(server_dir)],
        check=True,
    )


def _resolve_persistent_pace_mcp() -> str | None:
    """Return the absolute path of a persistently-installed pace-mcp
    binary, or None if no such install exists.

    This **only looks up** an existing install — it never attempts
    to install. Why: ``pace init`` runs *as* the bundled pace
    package, frequently via ``uvx --from <plugin>/server`` which
    will reuse an existing ``uv tool install`` if one is present.
    Trying to ``uv tool install --force`` from inside that running
    pace process triggers Windows file-lock errors as uv tries to
    delete files the running interpreter has open. The bootstrap
    flow puts the install step in a separate subprocess (see SKILL
    Step "Install pace persistently") *before* invoking pace init,
    so by the time we land here the install is already done.

    Asks ``uv tool dir --bin`` for the install bin directory rather
    than relying on PATH (which has the ephemeral uvx env in front
    when pace init was launched via uvx).

    Returns the path as a string for direct embedding in
    ``.mcp.json``; returns None if uv isn't installed, isn't on
    PATH, or there's no pace-mcp binary at the expected location.
    Callers fall back to the uvx-based ``.mcp.json`` shape in that
    case (slower first launch, but still functional once a manual
    install completes later).
    """
    try:
        result = subprocess.run(
            ["uv", "tool", "dir", "--bin"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    bin_dir = Path(result.stdout.strip())
    bin_name = "pace-mcp.exe" if sys.platform == "win32" else "pace-mcp"
    bin_path = bin_dir / bin_name
    return str(bin_path) if bin_path.is_file() else None


def _build_mcp_config(
    root: Path,
    *,
    plugin_root: Path | None = None,
    pace_mcp_bin: str | None = None,
) -> dict:
    """Construct the ``.mcp.json`` payload for this vault.

    Three shapes, in priority order:

    1. **Persistent install** (``pace_mcp_bin`` provided). Best path:
       absolute path to ``pace-mcp.exe`` from ``uv tool install``.
       Sub-100ms launches, durable across restarts and ``uv cache
       clean``.
    2. **uvx fallback** (``plugin_root`` provided, install failed).
       Spawns ``uvx --from <plugin>/server pace-mcp`` on every
       session start. Works but slow on cold cache; can trip Claude
       Code's MCP startup timeout.
    3. **Dev/CLI invocation** (neither provided). Embeds
       ``sys.executable`` directly — correct only when ``pace init``
       was run from a stable venv or pip install.

    ``PACE_ROOT`` is set in every shape so the server resolves the
    right vault even when launched from a different cwd.
    """
    if plugin_root is None:
        plugin_root = _detect_plugin_root()

    if pace_mcp_bin is not None:
        return {
            "mcpServers": {
                "pace": {
                    "command": pace_mcp_bin,
                    "args": [],
                    "env": {"PACE_ROOT": str(root)},
                }
            }
        }

    if plugin_root is not None:
        return {
            "mcpServers": {
                "pace": {
                    "command": "uvx",
                    "args": [
                        "--from",
                        str(plugin_root / "server"),
                        "pace-mcp",
                    ],
                    "env": {"PACE_ROOT": str(root)},
                }
            }
        }

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


def init(root: Path, *, plugin_root: Path | None = None) -> InitResult:
    """Scaffold ``root`` as a PACE vault. Idempotent.

    Args:
        root: vault directory.
        plugin_root: when set, ``.mcp.json`` is written with a
            ``uvx --from <plugin_root>/server pace-mcp`` command. This
            is what the SKILL/slash-command bootstrap passes when
            invoking ``pace init`` via uvx from a plugin install — the
            ``sys.executable`` form would otherwise embed an ephemeral
            uvx-cache path. When ``None``, the function still tries
            :func:`_detect_plugin_root` as a heuristic fallback (works
            only for unusual layouts; the uvx-cache case can't be
            detected from ``pace.__file__`` alone), and falls through
            to ``sys.executable`` if even that fails.
    """
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
    # When invoked from a plugin context, look up the persistently-
    # installed pace-mcp binary so MCP launches don't trip Claude Code's
    # startup timeout. Caller (the SKILL bootstrap, or a power user)
    # is responsible for having run `uv tool install <plugin>/server`
    # *before* calling pace init — we deliberately don't attempt the
    # install ourselves because pace init may be running *as* the very
    # tool install we'd be updating (Windows file-lock territory).
    # If no persistent install exists yet, fall back to the slower
    # `uvx --from` shape; that still works (just rebuilds on every
    # session) and the user can promote to a fast install later by
    # running `uv tool install` and re-running pace init.
    pace_mcp_bin: str | None = None
    if plugin_root is not None:
        pace_mcp_bin = _resolve_persistent_pace_mcp()
        if pace_mcp_bin is None:
            print(
                "warning: no persistent pace-mcp install found; "
                ".mcp.json will use `uvx --from` (slow first launch).",
                file=sys.stderr,
            )
            print(
                "         to upgrade, run "
                "`uv tool install --force <plugin>/server` then "
                "re-run pace init.",
                file=sys.stderr,
            )

    mcp_config_path = root / ".mcp.json"
    if not mcp_config_path.exists():
        payload = json.dumps(
            _build_mcp_config(
                root,
                plugin_root=plugin_root,
                pace_mcp_bin=pace_mcp_bin,
            ),
            indent=2,
        ) + "\n"
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
    # Record this vault as the CLI's default *only* if no default is
    # already set. PACE supports multiple vaults on the same machine —
    # initializing a second vault must not silently overwrite the
    # first vault's slot in %APPDATA%\pace\config.json (that file is
    # only used by the CLI as a fallback when invoked from a folder
    # that isn't part of any vault; the MCP server doesn't consult it).
    user_config_path, _ = pace_config.set_vault_root_if_unset(root)

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
