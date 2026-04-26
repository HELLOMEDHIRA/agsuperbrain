"""Allow `python -m agsuperbrain <command>` invocation.

This exists so MCP server configs (and any other tooling that needs a
path-independent way to reach the CLI) can invoke Super-Brain as:

    <python> -m agsuperbrain <command>

rather than relying on the `agsuperbrain` entry-point script being on
the shell PATH — which isn't always the case in IDE-spawned shells.
"""

from agsuperbrain.cli import app

if __name__ == "__main__":
    app()
