"""Vault-internal settings: defaults, yaml overrides, fault tolerance."""

from __future__ import annotations

from pathlib import Path

from pace import settings as pace_settings


def test_defaults_apply_when_no_yaml(tmp_path: Path) -> None:
    s = pace_settings.load(tmp_path)
    assert s.working_memory_soft_chars == pace_settings.DEFAULT_WORKING_MEMORY_SOFT_CHARS
    assert s.working_memory_hard_chars == pace_settings.DEFAULT_WORKING_MEMORY_HARD_CHARS


def test_yaml_overrides_apply(tmp_path: Path) -> None:
    cfg = tmp_path / "system" / "pace_config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        "working_memory:\n  soft_chars: 1000\n  hard_chars: 2000\n",
        encoding="utf-8",
    )
    s = pace_settings.load(tmp_path)
    assert s.working_memory_soft_chars == 1000
    assert s.working_memory_hard_chars == 2000


def test_partial_yaml_keeps_defaults_for_missing_keys(tmp_path: Path) -> None:
    cfg = tmp_path / "system" / "pace_config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        "working_memory:\n  soft_chars: 5000\n",  # hard_chars missing
        encoding="utf-8",
    )
    s = pace_settings.load(tmp_path)
    assert s.working_memory_soft_chars == 5000
    assert s.working_memory_hard_chars == pace_settings.DEFAULT_WORKING_MEMORY_HARD_CHARS


def test_corrupt_yaml_falls_back_to_defaults(tmp_path: Path) -> None:
    cfg = tmp_path / "system" / "pace_config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("this is not: valid: yaml: at: all", encoding="utf-8")
    s = pace_settings.load(tmp_path)
    # No exception, just defaults.
    assert s.working_memory_soft_chars == pace_settings.DEFAULT_WORKING_MEMORY_SOFT_CHARS


def test_negative_or_zero_values_fall_back_to_defaults(tmp_path: Path) -> None:
    """Pathological values shouldn't crash compaction; treat as 'use default'."""
    cfg = tmp_path / "system" / "pace_config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        "working_memory:\n  soft_chars: 0\n  hard_chars: -1\n",
        encoding="utf-8",
    )
    s = pace_settings.load(tmp_path)
    assert s.working_memory_soft_chars == pace_settings.DEFAULT_WORKING_MEMORY_SOFT_CHARS
    assert s.working_memory_hard_chars == pace_settings.DEFAULT_WORKING_MEMORY_HARD_CHARS


def test_write_default_creates_file_when_missing(tmp_path: Path) -> None:
    written = pace_settings.write_default_if_missing(tmp_path)
    assert written is not None
    assert written.is_file()
    text = written.read_text(encoding="utf-8")
    # Spot-check the documented schema is in there.
    assert "soft_chars" in text
    assert "hard_chars" in text


def test_write_default_is_a_noop_when_file_exists(tmp_path: Path) -> None:
    cfg = tmp_path / "system" / "pace_config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("working_memory:\n  soft_chars: 100\n", encoding="utf-8")

    result = pace_settings.write_default_if_missing(tmp_path)
    assert result is None
    # Not overwritten — user's customization survives.
    assert "soft_chars: 100" in cfg.read_text(encoding="utf-8")


def test_init_writes_default_pace_config(tmp_path: Path) -> None:
    """``pace init`` ships a documented config file so the user can see
    the tunables without reading source."""
    from pace import vault as vault_ops

    vault_ops.init(tmp_path)
    cfg = tmp_path / "system" / "pace_config.yaml"
    assert cfg.is_file()
    assert "working_memory" in cfg.read_text(encoding="utf-8")
