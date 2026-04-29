# Contributing to PACE

Thanks for considering a contribution. PACE is small enough that almost any
help — bug reports, design feedback, doc fixes, Mac dogfooding — is useful.

## Reporting bugs

Open an issue with:

- The OS and Claude client (Cowork or Claude Code) you're using.
- `pace doctor` output (or `pace --version` if `doctor` is the failing
  command).
- The smallest reproduction you can get.
- Whether your vault is on OneDrive / iCloud / Dropbox — sync engines are
  PACE's most common source of weird bugs.

If the issue involves the plugin install, please also include the contents
of `%APPDATA%\Claude\local-agent-mode-sessions\<session>\<session>\cowork_plugins\installed_plugins.json`
(redact anything personal first).

## Setting up a dev environment

```bash
git clone https://github.com/jagbanana/PACE.git
cd PACE
python -m venv .venv
.venv\Scripts\activate          # macOS / Linux: source .venv/bin/activate
pip install -e ".[dev]"
```

Verify:

```bash
pytest        # full test suite (160+ tests)
ruff check    # lint
```

The repo is structured so that the source folder doubles as a runnable
vault. After install, `pace init` in the repo root scaffolds a working
vault you can experiment against. The vault directories (`memories/`,
`projects/`, `system/`) are gitignored.

## Coding conventions

- **Python 3.11+.** Use modern syntax (`X | None`, PEP 604 unions,
  structural pattern matching where it helps).
- **Paths are `pathlib.Path`,** never raw strings. Mac compatibility is on
  the roadmap and string concatenation breaks it.
- **All file writes go through `pace.io.atomic_write_text`.** Don't write
  with `Path.write_text` directly. Atomicity is what keeps the vault safe
  on OneDrive.
- **The CLI in `pace.cli` is the only writer to the vault.** The MCP server
  in `pace.mcp_server` delegates to the same Python functions — there's no
  duplicated logic.
- **Lint with `ruff`.** Settings live in `pyproject.toml`. Run `ruff check`
  before pushing; fix everything or explain why it can't be fixed.
- **Test with `pytest`.** Add tests for any new branch. The suite uses
  `tmp_path` fixtures heavily — follow the patterns in `tests/conftest.py`.

## Pull request checklist

- [ ] `pytest` passes locally on at least one OS.
- [ ] `ruff check` is clean.
- [ ] New behavior has tests.
- [ ] If you bumped `pace.__version__`, also bump
  `plugin/.claude-plugin/plugin.json`'s `version` and `pyproject.toml`'s
  `version`. The build script enforces these match.
- [ ] If you changed the MCP tool surface, update `plugin/skills/pace-memory/SKILL.md`
  and `plugin/skills/pace-memory/references/onboarding.md` so the model's
  instructions still match reality.
- [ ] Docs in the README reflect any user-visible change.

## Code of conduct

Be kind. Disagree honestly. PACE is a one-maintainer project with a slow
review cadence — patience appreciated.

## License

By contributing you agree that your contributions are licensed under the
[MIT License](LICENSE).
