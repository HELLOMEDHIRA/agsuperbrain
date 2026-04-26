"""
Runnable pattern for project text files: always pass `encoding=` explicitly.

From repo root (no install): ``python scripts/text_io_snippet.py``
With an editable install, the import works from any cwd.
"""

from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agsuperbrain.terminal import TEXT_ENCODING


def main() -> None:
    with TemporaryDirectory() as d:
        p = Path(d) / "sample.txt"
        text = "héllo π 测试"
        p.write_text(text, encoding=TEXT_ENCODING)
        assert p.read_text(encoding=TEXT_ENCODING) == text, "round-trip failed"
    print("ok — TEXT_ENCODING round-trip")


if __name__ == "__main__":
    main()
