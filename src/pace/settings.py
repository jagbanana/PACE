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

    heartbeat:
      enabled: false        # Opt-in. Onboarding asks; default off.
      working_hours_start: "09:00"
      working_hours_end:   "17:00"
      working_days:        [mon, tue, wed, thu, fri]
      cadence_minutes:     60          # gap enforced between runs
      stale_age_days:      7           # commitment-shape entries older
                                       # than this are stale candidates
      pattern_min_repeats: 3           # how many similar captures to
                                       # surface as a pattern candidate

If the file is missing, defaults apply silently. If parsing fails (bad
YAML, unexpected types), defaults apply and the error is swallowed —
this is operational state read on every ``pace_status`` call, and we'd
rather degrade to defaults than crash session start.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Default char budgets. Char-counting (not token-counting) is a
# deliberate choice: a 4:1 char-to-token ratio is a fine approximation
# for English prose and avoids pulling in a tokenizer dependency.
DEFAULT_WORKING_MEMORY_SOFT_CHARS = 16_000   # ~4,000 tokens
DEFAULT_WORKING_MEMORY_HARD_CHARS = 32_000   # ~8,000 tokens

# Heartbeat defaults. Off by default — the feature only fires if the
# user opted in during onboarding.
DEFAULT_HEARTBEAT_ENABLED = False
DEFAULT_WORKING_HOURS_START = "09:00"
DEFAULT_WORKING_HOURS_END = "17:00"
DEFAULT_WORKING_DAYS: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri")
DEFAULT_HEARTBEAT_CADENCE_MIN = 60
DEFAULT_STALE_AGE_DAYS = 7
DEFAULT_PATTERN_MIN_REPEATS = 3

# Path of the config file relative to the vault root.
SETTINGS_FILE = "system/pace_config.yaml"


@dataclass(frozen=True)
class Settings:
    """Resolved per-vault settings. Immutable so callers don't mutate
    by accident; a fresh load gives the latest values from disk."""

    working_memory_soft_chars: int = DEFAULT_WORKING_MEMORY_SOFT_CHARS
    working_memory_hard_chars: int = DEFAULT_WORKING_MEMORY_HARD_CHARS

    heartbeat_enabled: bool = DEFAULT_HEARTBEAT_ENABLED
    heartbeat_start: str = DEFAULT_WORKING_HOURS_START
    heartbeat_end: str = DEFAULT_WORKING_HOURS_END
    heartbeat_days: tuple[str, ...] = field(default=DEFAULT_WORKING_DAYS)
    heartbeat_cadence_minutes: int = DEFAULT_HEARTBEAT_CADENCE_MIN
    heartbeat_stale_age_days: int = DEFAULT_STALE_AGE_DAYS
    heartbeat_pattern_min_repeats: int = DEFAULT_PATTERN_MIN_REPEATS


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

    hb = raw.get("heartbeat") or {}
    if not isinstance(hb, dict):
        hb = {}

    return Settings(
        working_memory_soft_chars=_coerce_int(
            wm.get("soft_chars"), DEFAULT_WORKING_MEMORY_SOFT_CHARS
        ),
        working_memory_hard_chars=_coerce_int(
            wm.get("hard_chars"), DEFAULT_WORKING_MEMORY_HARD_CHARS
        ),
        heartbeat_enabled=bool(hb.get("enabled", DEFAULT_HEARTBEAT_ENABLED)),
        heartbeat_start=_coerce_hhmm(
            hb.get("working_hours_start"), DEFAULT_WORKING_HOURS_START
        ),
        heartbeat_end=_coerce_hhmm(
            hb.get("working_hours_end"), DEFAULT_WORKING_HOURS_END
        ),
        heartbeat_days=_coerce_days(
            hb.get("working_days"), DEFAULT_WORKING_DAYS
        ),
        heartbeat_cadence_minutes=_coerce_int(
            hb.get("cadence_minutes"), DEFAULT_HEARTBEAT_CADENCE_MIN
        ),
        heartbeat_stale_age_days=_coerce_int(
            hb.get("stale_age_days"), DEFAULT_STALE_AGE_DAYS
        ),
        heartbeat_pattern_min_repeats=_coerce_int(
            hb.get("pattern_min_repeats"), DEFAULT_PATTERN_MIN_REPEATS
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


_VALID_DAYS: frozenset[str] = frozenset(
    {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
)


def _coerce_days(value: object, default: tuple[str, ...]) -> tuple[str, ...]:
    """Tolerant parser for the ``working_days`` list."""
    if not isinstance(value, list):
        return default
    out = []
    for item in value:
        if not isinstance(item, str):
            continue
        norm = item.strip().lower()[:3]
        if norm in _VALID_DAYS:
            out.append(norm)
    return tuple(out) if out else default


def _coerce_hhmm(value: object, default: str) -> str:
    """Validate an ``HH:MM`` 24-hour string; fall back to default on noise."""
    if not isinstance(value, str):
        return default
    s = value.strip()
    if len(s) != 5 or s[2] != ":":
        return default
    try:
        h = int(s[:2])
        m = int(s[3:])
    except ValueError:
        return default
    if 0 <= h <= 23 and 0 <= m <= 59:
        return s
    return default


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

heartbeat:
  # The proactive heartbeat checks for things to flag during your work
  # hours. Disabled by default; onboarding asks if you want it on. When
  # enabled, a scheduled task fires inside Cowork on the cadence below
  # and writes any findings into followups/ as 'ready' inbox items the
  # next session greets you with.
  enabled: false

  # Working hours (24-hour local time) and days. The heartbeat task
  # bails immediately if it fires outside these — Cowork's cron may
  # tick more often than this, but we don't act on it.
  working_hours_start: "09:00"
  working_hours_end:   "17:00"
  working_days:        [mon, tue, wed, thu, fri]

  # Minimum gap between two heartbeat runs. Even if Cowork's cron
  # fires more often, the orchestrator skips runs inside this window.
  cadence_minutes: 60

  # Heuristic thresholds used when scanning for stale commitments and
  # repeated patterns. See plugin docs for what these mean.
  stale_age_days: 7
  pattern_min_repeats: 3
"""
