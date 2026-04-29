"""Vault-internal settings loaded from ``system/pace_config.yaml``.

Distinct from :mod:`pace.config` (which handles the OS-level per-user
config that records the vault's *location*). This module owns the
in-vault tunables — the kind of knobs the user might tweak per vault.

Schema (all optional; defaults baked into :class:`Settings`):

.. code-block:: yaml

    working_memory:
      soft_chars: 16000   # ~4K tokens; compaction force-promotes
                          # oldest entries to stay under this.
      hard_chars: 32000   # ~8K tokens; pace_status truncates the
                          # returned body to fit if it ever exceeds
                          # this between scheduled compactions.

If the file is missing, defaults apply silently. If parsing fails (bad
YAML, unexpected types), defaults apply and the error is swallowed —
this is operational state read on every ``pace_status`` call, and we'd
rather degrade to defaults than crash session start.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

# Default char budgets. Char-counting (not token-counting) is a
# deliberate choice: a 4:1 char-to-token ratio is a fine approximation
# for English prose and avoids pulling in a tokenizer dependency.
DEFAULT_WORKING_MEMORY_SOFT_CHARS = 16_000   # ~4,000 tokens
DEFAULT_WORKING_MEMORY_HARD_CHARS = 32_000   # ~8,000 tokens

# Path of the config file relative to the vault root.
SETTINGS_FILE = "system/pace_config.yaml"


@dataclass(frozen=True)
class Settings:
    """Resolved per-vault settings. Immutable so callers don't mutate
    by accident; a fresh load gives the latest values from disk."""

    working_memory_soft_chars: int = DEFAULT_WORKING_MEMORY_SOFT_CHARS
    working_memory_hard_chars: int = DEFAULT_WORKING_MEMORY_HARD_CHARS


def load(root: Path) -> Settings:
    """Read ``<root>/system/pace_config.yaml`` and return :class:`Settings`.

    Missing file or any parse error → defaults. We never raise here:
    settings are read on every ``pace_status`` call, so a corrupt file
    can't be allowed to crash session start. ``pace doctor`` flags
    drift through other checks if the user has unusual values.
    """
    path = root / SETTINGS_FILE
    if not path.is_file():
        return Settings()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError):
        return Settings()
    if not isinstance(raw, dict):
        return Settings()

    wm = raw.get("working_memory") or {}
    if not isinstance(wm, dict):
        wm = {}

    return Settings(
        working_memory_soft_chars=_coerce_int(
            wm.get("soft_chars"), DEFAULT_WORKING_MEMORY_SOFT_CHARS
        ),
        working_memory_hard_chars=_coerce_int(
            wm.get("hard_chars"), DEFAULT_WORKING_MEMORY_HARD_CHARS
        ),
    )


def write_default_if_missing(root: Path) -> Path | None:
    """Drop a documented default config file if one isn't there yet.

    Called by :func:`pace.vault.init` so a freshly-scaffolded vault has
    a discoverable, commented config file the user can tune. Returns the
    path written, or ``None`` if the file already existed.
    """
    path = root / SETTINGS_FILE
    if path.is_file():
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_DEFAULT_YAML, encoding="utf-8")
    return path


def _coerce_int(value: object, default: int) -> int:
    """Tolerant int parsing for yaml-loaded values."""
    if value is None:
        return default
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    return result if result > 0 else default


_DEFAULT_YAML = """\
# PACE vault settings. All values are optional; PACE falls back to
# documented defaults if a key is missing or unparseable. Edit and save
# — changes take effect on the next `pace_status` call.

working_memory:
  # Compaction keeps memories/working_memory.md below this size. After
  # the LLM applies its decisions, any remaining oldest entries are
  # auto-promoted to memories/long_term/working-overflow.md until the
  # body fits. Default: 16,000 characters (~4,000 tokens).
  soft_chars: 16000

  # Hard ceiling for what pace_status returns at session start. If the
  # body exceeds this, the most recent entries that fit are returned
  # plus a one-line notice that older content was elided. The full
  # working memory file on disk is unchanged — older content remains
  # searchable via pace_search. Default: 32,000 characters
  # (~8,000 tokens).
  hard_chars: 32000
"""
