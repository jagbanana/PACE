"""MCP server entry point.

Phase 3 fleshes this out per PACE Dev Plan.md. For now this is a placeholder
so `python -m pace.mcp_server` is callable and `.mcp.json` references resolve
during early development.
"""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "pace.mcp_server is not implemented yet — Phase 3 of PACE Dev Plan.md.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
