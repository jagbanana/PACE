"""Static checks against the bundled Cowork plugin layout.

The plugin directory is hand-curated source — no Python loads it at
runtime — so these tests serve as a tripwire: if someone bumps the
package version without bumping ``plugin/.claude-plugin/plugin.json``,
or removes the SKILL.md, or breaks the manifest's JSON, CI catches it
before a release.

These are pure-Python tests with no Cowork in the loop. End-to-end
"plugin actually works in Cowork" verification is out of scope for an
automated suite — it requires a live Cowork install.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import pace

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = REPO_ROOT / "plugin"


@pytest.fixture(autouse=True)
def _no_user_config_isolation_needed() -> None:
    """These tests don't touch the user config path; the autouse fixture
    in conftest.py is harmless but not required."""
    return


def test_plugin_root_exists() -> None:
    assert PLUGIN_ROOT.is_dir(), "plugin/ should be present in the repo"


# ---- plugin.json -----------------------------------------------------


def _manifest() -> dict:
    return json.loads(
        (PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )


def test_manifest_is_valid_json() -> None:
    _manifest()  # raises if invalid


def test_manifest_required_fields() -> None:
    m = _manifest()
    # `name` is the only strictly required field per the plugin spec, but
    # we expect description/version/author too for a published plugin.
    for required in ("name", "version", "description"):
        assert m.get(required), f"manifest missing {required!r}"


def test_manifest_name_matches_skill_dir() -> None:
    """Cowork namespaces skills by plugin name; the SKILL.md folder name
    must match so the model finds the skill."""
    name = _manifest()["name"]
    assert (PLUGIN_ROOT / "skills" / name / "SKILL.md").is_file()


def test_manifest_version_matches_package() -> None:
    """plugin.json version must match pace.__version__ — the build script
    enforces this too, but a unit test makes the failure mode obvious."""
    assert _manifest()["version"] == pace.__version__


def test_manifest_declares_user_config_for_vault_root() -> None:
    """Cowork prompts for userConfig at install; the optional vault path
    must be exposed there so install-time-set users skip onboarding."""
    user_config = _manifest().get("userConfig", {})
    assert "vaultRoot" in user_config
    field = user_config["vaultRoot"]
    # An ``envVar`` key tells Cowork what env var to surface to the
    # plugin's MCP server. Our resolution chain reads
    # CLAUDE_PLUGIN_OPTION_VAULT_ROOT.
    assert field.get("envVar") == "VAULT_ROOT"


# ---- .mcp.json -------------------------------------------------------


def test_mcp_json_present_at_plugin_root() -> None:
    """Per Anthropic plugin spec, .mcp.json lives at the plugin root, not
    inside .claude-plugin/."""
    assert (PLUGIN_ROOT / ".mcp.json").is_file()


def test_mcp_json_uses_uvx() -> None:
    """The plugin spawns the MCP server via uvx so users don't need to
    manage Python themselves. Changing this is a deliberate decision."""
    payload = json.loads((PLUGIN_ROOT / ".mcp.json").read_text(encoding="utf-8"))
    server = payload["mcpServers"]["pace"]
    assert server["command"] == "uvx"
    assert server["args"] == ["--from", "pace-memory", "pace-mcp"]


# ---- SKILL.md --------------------------------------------------------


def _skill_text() -> str:
    return (PLUGIN_ROOT / "skills" / "pace-memory" / "SKILL.md").read_text(
        encoding="utf-8"
    )


def test_skill_has_yaml_frontmatter_with_required_fields() -> None:
    """Plugin skills require frontmatter with name + description so the
    model knows when to load them."""
    text = _skill_text()
    assert text.startswith("---\n"), "SKILL.md must open with YAML frontmatter"
    assert "name: pace-memory" in text
    assert "description:" in text


def test_skill_lists_every_pace_mcp_tool() -> None:
    """The model uses SKILL.md to know which tools exist; missing one
    means the model won't reach for it."""
    text = _skill_text()
    for tool in (
        "pace_status",
        "pace_capture",
        "pace_search",
        "pace_load_project",
        "pace_list_projects",
        "pace_init",
    ):
        assert tool in text, f"{tool} missing from SKILL.md"


def test_skill_warns_off_maintenance_tools() -> None:
    text = _skill_text()
    for forbidden in ("pace_compact", "pace_review", "pace_archive", "pace_reindex"):
        assert forbidden in text, f"SKILL.md should explicitly forbid {forbidden}"


def test_onboarding_reference_doc_exists() -> None:
    """The full first-run flow lives in references/onboarding.md so it
    only loads when needed."""
    ref = PLUGIN_ROOT / "skills" / "pace-memory" / "references" / "onboarding.md"
    assert ref.is_file()
    text = ref.read_text(encoding="utf-8")
    # Spot-check the three beats are documented.
    for beat in ("Beat 1", "Beat 2", "Beat 3"):
        assert beat in text


# ---- system-prompts --------------------------------------------------


def test_scheduled_task_prompts_present_in_plugin() -> None:
    """Bundled scheduled-task prompts let the SKILL register them via
    ${CLAUDE_PLUGIN_ROOT}/system-prompts/... without copy-pasting from
    the source repo."""
    assert (PLUGIN_ROOT / "system-prompts" / "compact.md").is_file()
    assert (PLUGIN_ROOT / "system-prompts" / "review.md").is_file()


def test_scheduled_task_prompts_match_canonical_constants() -> None:
    """The plugin's prompt files should be byte-identical to the
    constants in pace.onboarding so the build is reproducible. The
    build script regenerates them, so drift means a stale build."""
    from pace.onboarding import COMPACT_PROMPT, REVIEW_PROMPT

    compact = (PLUGIN_ROOT / "system-prompts" / "compact.md").read_text(
        encoding="utf-8"
    )
    review = (PLUGIN_ROOT / "system-prompts" / "review.md").read_text(
        encoding="utf-8"
    )
    assert compact == COMPACT_PROMPT
    assert review == REVIEW_PROMPT


# ---- LICENSE + README ------------------------------------------------


def test_license_present() -> None:
    assert (PLUGIN_ROOT / "LICENSE").is_file()


def test_readme_present_and_mentions_uvx() -> None:
    """Users need to know `uv` is a prerequisite."""
    readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
    assert "uvx" in readme or "uv " in readme
    assert "vaultRoot" in readme or "vault root" in readme.lower()
