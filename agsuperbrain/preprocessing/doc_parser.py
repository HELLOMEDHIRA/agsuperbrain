"""
doc_parser.py — MarkItDown document parser.

Responsibility: any file → DocParseResult (markdown text + metadata).
Nothing more. Extraction is downstream.

Supports: PDF, DOCX, PPTX, XLSX, HTML, CSV, Markdown, plain text.
Uses MarkItDown — DO NOT use LlamaParse or send raw docs to LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from markitdown import MarkItDown

# ── Supported extensions ──────────────────────────────────────────────────────

_SUPPORTED_EXTENSIONS: set[str] = {
    ".pdf",
    ".docx",
    ".doc",
    ".pptx",
    ".ppt",
    ".xlsx",
    ".xls",
    ".csv",
    ".html",
    ".htm",
    ".md",
    ".markdown",
    ".txt",
    ".rst",
}


def is_document(path: Path) -> bool:
    """Return True if this path is a supported document type."""
    return path.suffix.lower() in _SUPPORTED_EXTENSIONS


# ── DocParseResult ────────────────────────────────────────────────────────────


@dataclass
class DocParseResult:
    """
    Output of DocParser.parse().

    Attributes:
        markdown:    Full markdown text produced by MarkItDown.
        source_path: Absolute resolved path.
        source_type: File extension without dot (e.g. "pdf", "docx").
        title:       Best-effort document title (first H1 or filename stem).
        metadata:    Any extra key-value pairs from MarkItDown.
    """

    markdown: str
    source_path: Path
    source_type: str
    title: str
    metadata: dict = field(default_factory=dict)


# ── DocParser ─────────────────────────────────────────────────────────────────


class DocParser:
    """
    Stateless document parser backed by MarkItDown.

    Usage:
        parser = DocParser()
        result = parser.parse(Path("report.pdf"))
        print(result.markdown)
    """

    def __init__(self) -> None:
        self._md = MarkItDown()

    def parse(self, path: Path) -> DocParseResult:
        """
        Convert any supported document → DocParseResult.

        Raises:
            FileNotFoundError: File does not exist.
            ValueError:        File type is not supported.
        """
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        ext = path.suffix.lower()
        if ext not in _SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported document type: {ext!r}. Supported: {sorted(_SUPPORTED_EXTENSIONS)}")

        result = self._md.convert(str(path))
        markdown = result.text_content or ""
        title = self._extract_title(markdown, path)

        return DocParseResult(
            markdown=markdown,
            source_path=path.resolve(),
            source_type=ext.lstrip("."),
            title=title,
            metadata={},
        )

    def parse_string(
        self,
        text: str,
        source_type: str = "md",
        fake_path: Path | None = None,
    ) -> DocParseResult:
        """Parse raw markdown/text string — useful for tests."""
        fp = fake_path or Path(f"<string>.{source_type}")
        title = self._extract_title(text, fp)
        return DocParseResult(
            markdown=text,
            source_path=fp,
            source_type=source_type,
            title=title,
        )

    @staticmethod
    def _extract_title(markdown: str, path: Path) -> str:
        """Return first H1 heading, or fall back to filename stem."""
        for line in markdown.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped[2:].strip()
        return path.stem
