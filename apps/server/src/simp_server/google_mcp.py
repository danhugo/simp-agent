"""Run the Google apps' MCP servers ourselves: one workspace-mcp (github.com/taylorwilsdon/google_workspace_mcp, MIT)
per app, on 127.0.0.1. Google's own hosted MCP servers (gmailmcp.googleapis.com...) are a Developer Preview that only
works for enrolled Cloud projects; workspace-mcp calls the normal Gmail/Drive/Calendar APIs instead.

Each request carries the user's Google access token (Simp sends it, as for any app): workspace-mcp runs with an
external OAuth provider, so it checks the token with Google and keeps no login of its own.
`uv run python -m simp_server.google_mcp` (or `make google-mcp`) starts them; Ctrl-C stops them."""

from __future__ import annotations

import os
import signal
import subprocess
import sys

from .server import load_settings, take_keys

PORTS = {"gmail": 8101, "drive": 8102, "calendar": 8103}  # the default app urls in connections.APPS use these


def env_for(port: int, keys: dict) -> dict:
    """Only the Google OAuth client goes to workspace-mcp; model and storage keys stay out (take_keys pops them)."""
    return {**os.environ, "GOOGLE_OAUTH_CLIENT_ID": keys.get("GOOGLE_CLIENT_ID", ""),
            "GOOGLE_OAUTH_CLIENT_SECRET": keys.get("GOOGLE_CLIENT_SECRET", ""),
            "MCP_ENABLE_OAUTH21": "true", "EXTERNAL_OAUTH21_PROVIDER": "true",
            "WORKSPACE_MCP_HOST": "127.0.0.1", "WORKSPACE_MCP_PORT": str(port)}


def main() -> None:
    keys = take_keys(load_settings())
    procs = [subprocess.Popen(["uvx", "workspace-mcp", "--transport", "streamable-http", "--tools", app], env=env_for(port, keys))
             for app, port in PORTS.items()]
    print("google mcp: " + ", ".join(f"{a} http://127.0.0.1:{p}/mcp" for a, p in PORTS.items()), file=sys.stderr)
    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.send_signal(signal.SIGTERM)


if __name__ == "__main__":
    main()
