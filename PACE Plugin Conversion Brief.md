# PACE → Cowork Plugin Conversion Brief

A brief for the Claude Code session that will convert the PACE source repo
into a Cowork plugin. **Run this from a clean clone/copy of the PACE repo
in a separate development folder — do not modify Justin's live vault.**

---

## 1. Background — read before starting

PACE ("Persistent AI Context Engine") is a local Markdown memory system
for Claude. It currently consists of:

- A Python package `pace` (in `src/pace/`) with three entry points: a
  CLI (`pace`), a stdio MCP server (`pace-mcp` → `pace.mcp_server:main`),
  and an internal API used by both.
- A vault directory layout (`memories/`, `projects/`, `system/`,
  `.git/`, `.mcp.json`) that `pace init` scaffolds at the user's chosen
  root.
- A `CLAUDE.md` file at the vault root that instructs the model how to
  call the `pace_*` MCP tools (capture, search, project switching,
  first-run onboarding).
- Scheduled-task prompts in `system/prompts/compact.md` and
  `system/prompts/review.md` that handle daily compaction and weekly
  review when registered with Cowork's scheduled-tasks tool.

It is fully implemented and tested — the issue we are solving is purely
**deployment**, not function.

## 2. The problem we're solving

We discovered (and verified via Anthropic's docs) that **Cowork does not
read project-scoped `.mcp.json` files**. That mechanism is exclusive to
Claude Code (the CLI). The PACE README and PRD were written assuming
Cowork would honor `.mcp.json` like Claude Code does. It does not, and
there is no Trust prompt to retrigger because the loader never engages
on project `.mcp.json` in Cowork.

Cowork loads MCP servers from exactly two sources: remote connectors
(HTTP/SSE) and **plugin-bundled MCPs**. Therefore, to make PACE usable
inside Cowork, PACE must be packaged as a Cowork plugin.

## 3. Goal of this work

Produce a Cowork plugin named `pace-memory` (a `.plugin` zip file) that,
when installed, gives any Cowork user the full PACE experience:

- The `pace_*` MCP tools available in every Cowork session.
- A bundled skill containing the model-side instructions (first-run
  onboarding, capture rules, project switching, "don't expose plumbing"
  guidance) that currently live in the vault's `CLAUDE.md`.
- Scheduled-task prompt templates packaged with the plugin so daily
  compaction and weekly review can be registered without copy-pasting
  Markdown.
- Documentation for installing the plugin and configuring the vault root.

The existing `pace` CLI remains useful for power users and for Claude
Code users — keep it intact. The vault layout (`memories/`, `projects/`,
etc.) is unchanged. Only the *integration surface* with Cowork changes.

## 4. Plugin architecture (per Anthropic's plugin spec)

Target this directory layout in the dev folder:

```
pace-memory/
├── .claude-plugin/
│   └── plugin.json              # required manifest
├── .mcp.json                    # local stdio MCP server config
├── skills/
│   └── pace-memory/
│       ├── SKILL.md             # model-side instructions (from CLAUDE.md)
│       └── references/
│           └── onboarding.md    # full first-run flow detail
├── system-prompts/
│   ├── compact.md               # daily compaction prompt
│   └── review.md                # weekly review prompt
├── server/                      # the Python MCP server payload
│   └── (pace package source or installer)
├── README.md
└── LICENSE
```

### `plugin.json`

```json
{
  "name": "pace-memory",
  "version": "0.1.0",
  "description": "Persistent AI Context Engine — local Markdown memory for Claude. Remembers people, decisions, and project context across sessions in a human-readable vault.",
  "author": { "name": "Justin Gesso" },
  "homepage": "https://github.com/justingesso/pace",
  "license": "MIT",
  "keywords": ["memory", "vault", "obsidian", "markdown", "context"]
}
```

### `.mcp.json` — the hard architectural decision

The plugin is installed once globally; the vault lives in a per-user
folder. The MCP server needs to know **which folder is the user's
vault** at startup. There is no single right answer — pick one of these
strategies (in order of preference):

**Option A (preferred): per-user config file.** First-run onboarding
captures the vault path and writes it to
`%APPDATA%\pace\config.json` (Windows) or `~/.config/pace/config.json`
(macOS/Linux). The MCP server reads this on startup. If absent, the
server returns `initialized: false` from `pace_status` and the
onboarding skill walks the user through `pace_init(root=...)`. Clean,
survives Cowork restarts, no env-var fragility.

**Option B (fallback): `PACE_ROOT` env var.** Documented in the README
as a setup step. Brittle on Windows because env vars set in a shell
don't always propagate into Cowork's spawned subprocesses, but it's a
reasonable secondary mechanism.

**Option C (investigate first): Cowork-provided folder var.** Check
whether Cowork passes the user's currently-selected folder to plugin
MCP servers via an env var (try names like `COWORK_SELECTED_FOLDER`,
`CLAUDE_WORKSPACE`, `WORKSPACE_PATH`). If yes, prefer that as the
default vault root — it makes the metaphor "selected folder = vault"
work automatically.

**Recommendation:** implement Option A as the source of truth, accept
Option C as an override if Cowork provides such a var, and document
Option B as a manual escape hatch.

The Python runtime is a second decision. The current vault assumes a
local `.venv`. For a plugin, you have three viable paths:

1. **`uvx pace-memory` in the MCP command field.** Requires `uv`
   installed on the user's system. Zero plugin bloat, always pulls
   latest from PyPI. Cleanest if `uv` is acceptable as a prereq.
2. **`pipx run pace-memory`.** Same idea, different tool. `pipx` is
   more commonly preinstalled on dev machines.
3. **Bundle a venv inside the plugin.** Largest install, but
   self-contained. Use `${CLAUDE_PLUGIN_ROOT}/server/.venv/Scripts/python.exe`
   on Windows. Requires a one-time install script; Cowork plugins do
   not currently run install hooks, so the user would need to run the
   script manually after installing the plugin.

**Recommendation:** Option 1 (`uvx`). Publish `pace-memory` to PyPI as
part of this work; it's already structured correctly in `pyproject.toml`.
Document `uv` as a prerequisite in the README. Provide Option 3 as a
fallback for users who can't install `uv`.

Sample `.mcp.json` for the `uvx` approach:

```json
{
  "mcpServers": {
    "pace": {
      "command": "uvx",
      "args": ["--from", "pace-memory", "pace-mcp"],
      "env": {}
    }
  }
}
```

### `skills/pace-memory/SKILL.md`

Move the contents of the current vault `CLAUDE.md` into a SKILL.md with
proper plugin-skill frontmatter. The body becomes the model's PACE
playbook. Triggers should fire whenever the model would benefit from
PACE — capture-worthy facts, project context switches, sessions in a
PACE-initialized folder. Frontmatter description must be third-person
with explicit trigger phrases ("This skill should be used when ...
'capture', 'remember this', 'load project', the user mentions a
project name, the user states a durable preference or fact, ...").

Keep SKILL.md under ~3000 words. Push the full first-run onboarding
beats and edge cases into `references/onboarding.md` so they load only
when needed.

### `system-prompts/compact.md` and `review.md`

Copy verbatim from `system/prompts/` in the source repo. The
scheduled-task setup instructions in the SKILL/onboarding flow should
reference these via `${CLAUDE_PLUGIN_ROOT}/system-prompts/compact.md`
and `${CLAUDE_PLUGIN_ROOT}/system-prompts/review.md` rather than vault-
relative paths.

### `README.md`

Cover: what the plugin does, prerequisites (`uv` if going with Option
1), installation, vault location strategy (point at the config file
location and how to override), how to verify it works (`pace_status`
returns `initialized: false` on first call → run onboarding), and
troubleshooting.

## 5. What changes in the source repo

This conversion is **additive** to the source repo, not destructive.

- Keep `src/pace/`, the CLI, all tests, and the existing
  `pace.mcp_server` module exactly as they are. Both Cowork (via the
  plugin) and Claude Code (via the legacy project `.mcp.json`) will
  invoke the same Python module.
- Add a top-level `plugin/` directory that contains the plugin layout
  described above. A build script (`scripts/build-plugin.sh` or
  `Makefile` target) zips `plugin/` into `pace-memory.plugin` for
  release.
- Add a `pace.config` module that handles the per-user vault path
  resolution (Option A above) — read/write
  `%APPDATA%\pace\config.json` on Windows, `~/.config/pace/config.json`
  elsewhere. Wire `pace.mcp_server` to call it on startup.
- Update `pace_init` in the CLI to *also* write the per-user config
  file when run, so that `uvx pace-memory pace init <path>` from a
  plugin context registers the vault for future MCP server starts.
- Update README and PRD: remove the wrong claim that Cowork reads
  `.mcp.json`. Add a Cowork-specific section pointing users at the
  plugin install path.

## 6. Acceptance criteria

The work is done when all of the following are true on a Windows
machine with Cowork installed:

1. `cd plugin && zip -r /tmp/pace-memory.plugin . -x "*.DS_Store"`
   produces a clean zip.
2. Installing the resulting `.plugin` file in Cowork makes the
   `mcp__plugin_pace_memory__pace_*` tools (or whatever namespace
   Cowork assigns) appear in a fresh session's tool list — verify by
   asking the model "what tools do you have for memory?" and seeing
   them enumerated.
3. In a fresh folder with no vault, calling `pace_status` returns
   `initialized: false` and the model offers first-run onboarding per
   the SKILL.
4. After onboarding, the per-user config file exists at the documented
   location and contains the chosen vault root.
5. In subsequent sessions in the *same* folder (or any folder, given
   per-user config), `pace_status` returns `initialized: true` and
   `working_memory` is populated.
6. Daily and weekly scheduled tasks can be registered using
   `${CLAUDE_PLUGIN_ROOT}/system-prompts/...` paths and execute
   correctly.
7. `pytest` and `ruff check` still pass on the source repo.
8. Existing Claude Code users with the legacy vault `.mcp.json` are
   unaffected — the same `pace.mcp_server` module still works.

## 7. Out of scope (don't do these)

- Don't rebuild the indexer, capture, or compaction logic. Those work.
- Don't move the vault layout. Users' existing `memories/`,
  `projects/`, `system/` directories must keep working unchanged.
- Don't touch Justin's live vault folder. All work happens in a clean
  development copy.
- Don't add OAuth, remote MCP, or any cloud component. PACE stays
  local-first per the PRD's design tenets.

## 8. First step before coding

Confirm with Justin (the user driving the dev session) which Python
runtime strategy from §4 to use (`uvx`, `pipx`, or bundled venv), and
whether to investigate a Cowork-provided folder env var as the default
vault path. Those two choices change the `.mcp.json` and the README.

Then proceed: scaffold `plugin/`, port `CLAUDE.md` → `SKILL.md`, write
`pace.config`, build, and validate against §6.
