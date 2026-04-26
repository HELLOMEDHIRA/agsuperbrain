"""UTF-8 stdio on Windows, shared Rich `Console`, and `TEXT_ENCODING` for file I/O.

Imported from `agsuperbrain.__init__` so it runs before other package code.
"""

from __future__ import annotations

import io
import sys

from rich.console import Console

TEXT_ENCODING: str = "utf-8"  # prefer over locale default for Path I/O


def _reconfigure_text_stream(stream: object) -> None:
    if stream is None or not hasattr(stream, "reconfigure"):
        return
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (OSError, ValueError, AttributeError, io.UnsupportedOperation):
        return


if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        _reconfigure_text_stream(_s)


def make_console() -> Console:
    """A Rich Console suitable for the current OS (Unicode on modern Windows)."""
    if sys.platform == "win32":
        return Console(legacy_windows=False)
    return Console()


console: Console = make_console()
