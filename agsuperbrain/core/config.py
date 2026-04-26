"""Load `.agsuperbrain/config.yaml` (optional)."""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from agsuperbrain.terminal import TEXT_ENCODING

DEFAULT_EXCLUDE = frozenset(
    {
        ".venv",
        "venv",
        "env",
        ".env",
        "ENV",
        "node_modules",
        ".npm",
        ".yarn",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".eggs",
        "*.egg-info",
        ".git",
        ".svn",
        ".hg",
        ".idea",
        ".vscode",
        "*.swp",
        "*.swo",
        "*~",
        ".tox",
        ".nox",
        ".cache",
    }
)

SUPERBRAIN_DIR = ".agsuperbrain"

DEFAULT_CONFIG = {
    "exclude": [],
    "languages": ["python", "javascript", "typescript"],
    "watcher": {"debounce_ms": 400, "max_wait_ms": 2000},
    "graph": {"db_path": "./.agsuperbrain/graph"},
    "vector": {"db_path": "./.agsuperbrain/qdrant"},
}


@dataclass
class SuperbrainConfig:
    exclude: frozenset[str] = field(default_factory=lambda: DEFAULT_EXCLUDE)
    languages: list[str] = field(default_factory=list)
    watcher_debounce_ms: int = 400
    watcher_max_wait_ms: int = 2000
    graph_db_path: str = "./.agsuperbrain/graph"
    vector_db_path: str = "./.agsuperbrain/qdrant"

    @classmethod
    def load(cls, path: Path | None = None) -> SuperbrainConfig:
        """Load config from .agsuperbrain/config.yaml or use defaults."""
        if path is None:
            path = Path.cwd() / SUPERBRAIN_DIR / "config.yaml"

        if not path.exists():
            return cls()

        try:
            data = yaml.safe_load(path.read_text(encoding=TEXT_ENCODING)) or {}
        except yaml.YAMLError as exc:
            warnings.warn(
                f"Could not parse {path}: {exc}. Using defaults.",
                stacklevel=2,
            )
            return cls()
        except OSError as exc:
            warnings.warn(
                f"Could not read {path}: {exc}. Using defaults.",
                stacklevel=2,
            )
            return cls()

        exclude = set(DEFAULT_EXCLUDE)
        if "exclude" in data:
            exclude.update(data["exclude"])

        languages = data.get("languages", ["python", "javascript", "typescript"])

        watcher_debounce_ms = 400
        watcher_max_wait_ms = 2000
        if "watcher" in data:
            raw = data["watcher"].get("debounce_ms", 400)
            try:
                watcher_debounce_ms = int(float(raw))
            except (TypeError, ValueError):
                watcher_debounce_ms = 400
            raw2 = data["watcher"].get("max_wait_ms", 2000)
            try:
                watcher_max_wait_ms = int(float(raw2))
            except (TypeError, ValueError):
                watcher_max_wait_ms = 2000

        graph_db_path = data.get("graph", {}).get("db_path", "./.agsuperbrain/graph")
        vector_db_path = data.get("vector", {}).get("db_path", "./.agsuperbrain/qdrant")

        return cls(
            exclude=frozenset(exclude),
            languages=languages,
            watcher_debounce_ms=watcher_debounce_ms,
            watcher_max_wait_ms=watcher_max_wait_ms,
            graph_db_path=graph_db_path,
            vector_db_path=vector_db_path,
        )


def get_config(project_path: Path | None = None) -> SuperbrainConfig:
    """Get config from .agsuperbrain/config.yaml in project directory."""
    if project_path is None:
        project_path = Path.cwd()
    config_path = project_path / SUPERBRAIN_DIR / "config.yaml"
    return SuperbrainConfig.load(config_path)
