"""Build ``pace-memory.plugin`` (a zip) from ``plugin/`` + bundled source.

Usage:

    python scripts/build_plugin.py [--out dist/pace-memory.plugin]

Two-stage build:

1. **Stage** — copies the Python source needed at runtime (``src/pace/``,
   ``pyproject.toml``, ``LICENSE``, plus a minimal ``README.md``) into a
   temporary staging directory **outside the source tree**. Avoiding the
   source tree (and therefore OneDrive) keeps this fast and reliable —
   OneDrive on Windows holds open handles for several seconds after a
   write, which makes in-tree staging racy.
2. **Zip** — writes ``plugin/`` (verbatim) plus the staged source (under
   the ``server/`` arc-name prefix) into the ``.plugin`` archive.

The plugin's ``.mcp.json`` runs ``uvx --from ${CLAUDE_PLUGIN_ROOT}/server
pace-mcp``; the ``server/`` arc-name prefix is what makes that resolve.

Excludes OS / editor cruft and ``__pycache__`` everywhere. Sanity-checks
that the manifest's ``version`` matches ``pace.__version__`` so a
forgotten bump in one file fails loudly.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = REPO_ROOT / "plugin"
DEFAULT_OUT = REPO_ROOT / "dist" / "pace-memory.plugin"

# Arc-name prefix for the bundled Python source inside the zip. Must
# match the path the plugin's ``.mcp.json`` references via
# ``${CLAUDE_PLUGIN_ROOT}/server``.
SERVER_ARCNAME_PREFIX = "server"

# Patterns of files/dirs we never want in a plugin zip.
EXCLUDED_NAMES: frozenset[str] = frozenset({
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
})

# Minimal README written into the staged server dir. The bundled source
# only needs enough metadata for ``uvx`` to resolve it; we don't want
# to ship the full repo README inside the plugin.
_BUNDLED_README = """\
# pace-memory — bundled source

This is the Python source for the PACE MCP server, shipped inside the
`pace-memory` Cowork plugin. At runtime it's resolved by
`uvx --from ${CLAUDE_PLUGIN_ROOT}/server pace-mcp` — users don't run
this directly.

Full project: <https://github.com/justingesso/pace>.
"""


def _check_version_alignment() -> None:
    """Ensure plugin.json's version matches pace.__version__."""
    sys.path.insert(0, str(REPO_ROOT / "src"))
    try:
        from pace import __version__ as pace_version  # noqa: PLC0415
    except ImportError as exc:
        raise SystemExit(
            f"Could not import pace to check version alignment: {exc}"
        ) from exc

    manifest_path = PLUGIN_DIR / ".claude-plugin" / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    plugin_version = manifest.get("version")

    if plugin_version != pace_version:
        raise SystemExit(
            f"Version mismatch: plugin.json={plugin_version!r}, "
            f"pace.__version__={pace_version!r}. Bump both before building."
        )


def _iter_plugin_files() -> list[Path]:
    """Yield every file in ``plugin/`` we want to include in the zip."""
    out: list[Path] = []
    for path in sorted(PLUGIN_DIR.rglob("*")):
        if path.is_dir():
            continue
        # Skip excluded names anywhere in the relative path.
        if any(part in EXCLUDED_NAMES for part in path.relative_to(PLUGIN_DIR).parts):
            continue
        out.append(path)
    return out


def build(out_path: Path) -> Path:
    """Stage source into a temp dir, then zip ``plugin/`` + staged source to ``out_path``."""
    if not PLUGIN_DIR.is_dir():
        raise SystemExit(f"plugin/ directory not found at {PLUGIN_DIR}")

    _check_version_alignment()

    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    plugin_files = _iter_plugin_files()
    if not plugin_files:
        raise SystemExit("plugin/ is empty — nothing to package.")

    # Stage the bundled source into a system temp dir so we never write
    # under OneDrive — that's what made earlier in-tree staging flaky.
    # The TemporaryDirectory cleans up automatically on exit.
    with tempfile.TemporaryDirectory(prefix="pace-plugin-stage-") as tmp:
        staged = stage_server_source(Path(tmp))

        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # plugin/ verbatim.
            for path in plugin_files:
                arcname = path.relative_to(PLUGIN_DIR).as_posix()
                zf.write(path, arcname)
            # Staged source under the server/ prefix.
            for path in sorted(staged.rglob("*")):
                if not path.is_file():
                    continue
                rel = path.relative_to(staged).as_posix()
                arcname = f"{SERVER_ARCNAME_PREFIX}/{rel}"
                zf.write(path, arcname)

    return out_path


def stage_server_source(target_dir: Path) -> Path:
    """Copy the Python source uvx needs into ``target_dir``.

    Pure copy operation — no destructive cleanup, no in-tree mutation.
    The caller owns ``target_dir`` and its lifecycle (typically a
    ``tempfile.TemporaryDirectory``).

    Bundles:
    - ``src/pace/`` (excluding ``__pycache__``)
    - ``pyproject.toml`` (so uvx can resolve the package metadata and
      run the ``pace-mcp`` entry point)
    - ``LICENSE`` (referenced by pyproject)
    - A minimal ``README.md`` (also referenced by pyproject)
    """
    target_dir.mkdir(parents=True, exist_ok=True)

    # src/pace/ — include only Python sources; skip caches.
    src_pace = REPO_ROOT / "src" / "pace"
    dest_pace = target_dir / "src" / "pace"
    if dest_pace.exists():
        shutil.rmtree(dest_pace)
    shutil.copytree(
        src_pace,
        dest_pace,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )

    # pyproject.toml — uvx reads this to know dependencies + entry points.
    shutil.copy2(REPO_ROOT / "pyproject.toml", target_dir / "pyproject.toml")

    # LICENSE — pyproject's license field references the same MIT terms.
    shutil.copy2(REPO_ROOT / "LICENSE", target_dir / "LICENSE")

    # Minimal README — pyproject declares ``readme = "README.md"`` so the
    # build backend wants this present, but users never see it.
    (target_dir / "README.md").write_text(_BUNDLED_README, encoding="utf-8")

    return target_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Output zip path. Default: {DEFAULT_OUT.relative_to(REPO_ROOT)}",
    )
    args = parser.parse_args()

    out = build(args.out)
    files = _iter_plugin_files()
    size_kb = out.stat().st_size / 1024
    print(f"Built {out.relative_to(REPO_ROOT)} ({len(files)} files, {size_kb:.1f} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
