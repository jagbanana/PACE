"""Build ``pace-memory.plugin`` (a zip) from ``plugin/``.

Usage:

    python scripts/build_plugin.py [--out dist/pace-memory.plugin]

Cross-platform replacement for ``zip -r`` so Windows users without the
zip CLI can produce releases. Excludes OS / editor cruft and zero-byte
``__pycache__`` directories. Sanity-checks that the manifest's
``version`` matches ``pace.__version__`` so a forgotten bump in one
file fails loudly.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = REPO_ROOT / "plugin"
DEFAULT_OUT = REPO_ROOT / "dist" / "pace-memory.plugin"

# Patterns of files/dirs we never want in a plugin zip.
EXCLUDED_NAMES: frozenset[str] = frozenset({
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
})


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
    """Zip ``plugin/`` into ``out_path``. Returns the resolved output path."""
    if not PLUGIN_DIR.is_dir():
        raise SystemExit(f"plugin/ directory not found at {PLUGIN_DIR}")

    _check_version_alignment()

    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    files = _iter_plugin_files()
    if not files:
        raise SystemExit("plugin/ is empty — nothing to package.")

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            arcname = path.relative_to(PLUGIN_DIR).as_posix()
            zf.write(path, arcname)

    return out_path


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
