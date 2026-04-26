"""
embedder.py — CPU-only sentence-transformers wrapper.

Responsibility: text[] -> vector[][]. Nothing else.
Model: all-MiniLM-L6-v2 (384-dim, fast on CPU, excellent quality).
"""

from __future__ import annotations

from dataclasses import dataclass

from sentence_transformers import SentenceTransformer


@dataclass
class EmbedderConfig:
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    batch_size: int = 64
    device: str = "cpu"
    cache_dir: str | None = None


class TextEmbedder:
    """
    Stateful (model cached after first load), stateless per call.

    Usage:
        emb = TextEmbedder()
        vecs = emb.embed(["hello world", "search me"])
        dim  = emb.dimension  # 384
    """

    def __init__(self, config: EmbedderConfig | None = None) -> None:
        self.config = config or EmbedderConfig()
        self._model: SentenceTransformer | None = None

    def _get_model(self) -> SentenceTransformer:
        if self._model is None:
            kwargs: dict = {}
            if self.config.cache_dir:
                kwargs["cache_folder"] = self.config.cache_dir
            self._model = SentenceTransformer(
                self.config.model_name,
                device=self.config.device,
                **kwargs,
            )
        return self._model

    @property
    def dimension(self) -> int:
        return self._get_model().get_embedding_dimension()  # type: ignore[return-value]

    def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a list of texts in batches.
        Returns L2-normalised float vectors (cosine == dot product).
        """
        if not texts:
            return []
        # MCP/JSON and Qdrant payloads can pass non-str values; the encoder expects strings.
        valid: list[str] = []
        for t in texts:
            if t is None:
                valid.append("empty")
            elif isinstance(t, str):
                valid.append(t.strip() or "empty")
            else:
                valid.append(str(t) if str(t).strip() else "empty")
        model = self._get_model()
        vectors = model.encode(
            valid,
            batch_size=self.config.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return [v.tolist() for v in vectors]
