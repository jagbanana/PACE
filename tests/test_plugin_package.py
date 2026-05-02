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


def test_mcp_json_uses_uvx_against_bundled_source() -> None:
    """The plugin spawns the MCP server via ``uvx --from`` pointed at
    the bundled source under ``${CLAUDE_PLUGIN_ROOT}/server``. This is
    the bundled-source-no-PyPI-publish path — changing it (e.g. back to
    a PyPI package name) is a deliberate decision that needs to be
    matched by the build script and the README."""
    payload = json.loads((PLUGIN_ROOT / ".mcp.json").read_text(encoding="utf-8"))
    server = payload["mcpServers"]["pace"]
    assert server["command"] == "uvx"
    assert server["args"] == [
        "--from",
        "${CLAUDE_PLUGIN_ROOT}/server",
        "pace-mcp",
    ]


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


def test_skill_description_under_marketplace_char_limit() -> None:
    """Anthropic's marketplace validator caps `description` at 1024
    characters; uploads exceeding that are rejected with
    `Plugin validation failed. Skill 'skills/pace-memory': field
    'description' in SKILL.md must be at most 1024 characters`. The
    field is broad enough that we keep brushing against it — this
    guard makes overruns fail in CI instead of at upload time."""
    text = _skill_text()
    for line in text.splitlines():
        if line.startswith("description:"):
            # Strip the YAML key but count everything after, including
            # the value. The validator counts the description value, so
            # use the raw line minus the key prefix as a safe overestimate.
            value = line[len("description:"):].strip()
            assert len(value) <= 1024, (
                f"SKILL.md description is {len(value)} chars (>{1024} limit). "
                "Trim before any marketplace upload — see CHANGELOG/v0.3.5."
            )
            return
    raise AssertionError("description: line not found in SKILL.md")


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


def test_skill_carries_address_and_sign_rule() -> None:
    """The plugin SKILL must teach the same personality rule the in-vault
    CLAUDE.md does. Cowork users only see SKILL.md until pace_init runs."""
    text = _skill_text()
    assert "Address the user and sign every reply" in text
    assert "Sign at the bottom" in text
    assert "Vary the opener" in text or "vary the" in text.lower()


def test_skill_contains_inline_first_vault_bootstrap_recipe() -> None:
    """The skill must carry a self-contained bootstrap recipe so that
    a brand-new folder where the plugin's MCP server isn't yet loaded
    can still be initialized via Bash + uv. We can't rely on the
    `/pace-memory:pace-setup` slash command pipeline alone — slash
    commands from user-uploaded plugins are fragile in current Claude
    Code, and the skill route is the proven primary path.

    Critical details encoded by these asserts:

    1. Plugin-path discovery uses a glob over ``~/.claude/plugins/
       marketplaces/*/pace-memory``, not a literal
       ``${CLAUDE_PLUGIN_ROOT}`` (which Claude Code does NOT substitute
       inside Bash invocations).
    2. ``uv tool install --force "$PLUGIN_ROOT/server"`` runs *before*
       ``pace init``, in its own subprocess. This is what makes MCP
       launches sub-100ms; running install from inside a pace init
       process triggers Windows file-lock errors.
    3. ``pace init --plugin-root "$PLUGIN_ROOT"`` produces a durable
       project ``.mcp.json``.
    """
    text = _skill_text()
    # Must NOT use the literal ${CLAUDE_PLUGIN_ROOT} in shell — bug-guard.
    assert "${CLAUDE_PLUGIN_ROOT}/server" not in text
    # Must show the model how to discover the plugin path.
    assert "ls -d ~/.claude/plugins/marketplaces/*/pace-memory" in text
    # Persistent install step must appear BEFORE pace init in the body.
    install_idx = text.find('uv tool install --force "$PLUGIN_ROOT/server"')
    init_idx = text.find('pace init --plugin-root "$PLUGIN_ROOT"')
    assert install_idx > 0, "must include `uv tool install` step"
    assert init_idx > 0, "must include `pace init --plugin-root` step"
    assert install_idx < init_idx, "install must appear before pace init"
    # Captures use the same uvx pattern.
    assert 'uvx --from "$PLUGIN_ROOT/server" pace capture' in text
    # Must collect identity (3 questions) and tell the user to restart.
    assert "What should I call you?" in text
    assert "restart" in text.lower()


def test_onboarding_reference_asks_for_emoji_and_pins_identity() -> None:
    """Beat 1 of onboarding must collect the emoji and write the
    identity-pin capture so personality bookends survive force-promotion."""
    ref = (PLUGIN_ROOT / "skills" / "pace-memory" / "references" / "onboarding.md").read_text(
        encoding="utf-8"
    )
    assert "emoji" in ref.lower()
    assert "Identity bookends" in ref
    assert '"#user", "#high-signal"' in ref


def test_onboarding_reference_doc_exists() -> None:
    """The full first-run flow lives in references/onboarding.md so it
    only loads when needed."""
    ref = PLUGIN_ROOT / "skills" / "pace-memory" / "references" / "onboarding.md"
    assert ref.is_file()
    text = ref.read_text(encoding="utf-8")
    # v0.2.1 reduced onboarding to two beats — scheduled-task
    # registration is gone (replaced by in-session lazy maintenance).
    for beat in ("Beat 1", "Beat 2"):
        assert beat in text
    assert "Beat 3" not in text


# ---- commands --------------------------------------------------------


def test_pace_setup_command_present() -> None:
    """`/pace-setup` is the first-vault entry point shipped in v0.3.1.
    Without this command, real-world users can't bootstrap a vault when
    the plugin's MCP server isn't auto-loaded by Claude Code."""
    cmd = PLUGIN_ROOT / "commands" / "pace-setup.md"
    assert cmd.is_file(), "plugin/commands/pace-setup.md must exist"


def test_pace_setup_command_has_frontmatter_and_uses_bundled_cli() -> None:
    """The command must (a) declare a description so it shows up in the
    plugin slash-command picker, (b) authorize Bash so the model can
    actually run the bootstrap (omitting allowed-tools defaults to
    nothing-authorized → silent freeze), and (c) actually invoke the
    bundled CLI via uvx with --plugin-root so the project .mcp.json
    gets a durable uvx-based command (the whole reason this slash
    command exists).

    The shell variable ``$PLUGIN_ROOT`` is set by the command body via
    a glob over ``~/.claude/plugins/marketplaces/*/pace-memory`` —
    that's what's actually portable across user-uploaded and future
    marketplace installs. ``${CLAUDE_PLUGIN_ROOT}`` is NOT used here
    because Claude Code does not expand it inside Bash invocations.
    """
    text = (PLUGIN_ROOT / "commands" / "pace-setup.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "description:" in text
    # Bash must be authorized; omitting the field silently disables tools.
    assert "allowed-tools:" in text
    assert '"Bash"' in text
    # Must NOT use ${CLAUDE_PLUGIN_ROOT} literal in shell — that's the
    # bug we're guarding against.
    assert "${CLAUDE_PLUGIN_ROOT}/server" not in text
    # Must run `uv tool install` BEFORE `pace init` (no in-flight
    # pace process during install → no Windows file-lock errors).
    install_idx = text.find('uv tool install --force "$PLUGIN_ROOT/server"')
    init_idx = text.find(
        'uvx --from "$PLUGIN_ROOT/server" pace init --plugin-root "$PLUGIN_ROOT"'
    )
    assert install_idx > 0, "command must include `uv tool install` step"
    assert init_idx > 0, "command must include `pace init` step"
    assert install_idx < init_idx, "install must come before pace init"
    assert 'uvx --from "$PLUGIN_ROOT/server" pace capture' in text
    # Must show the model how to discover the plugin path.
    assert "ls -d ~/.claude/plugins/marketplaces/*/pace-memory" in text


def test_pace_setup_command_tells_user_to_restart() -> None:
    """The post-bootstrap restart is non-negotiable — without it the
    project-level .mcp.json doesn't load and PACE tools stay missing.
    The command must include this explicitly in its instructions."""
    text = (PLUGIN_ROOT / "commands" / "pace-setup.md").read_text(encoding="utf-8")
    assert "restart" in text.lower()


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
