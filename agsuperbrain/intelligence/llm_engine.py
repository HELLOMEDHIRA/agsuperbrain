"""
llm_engine.py — llama-cpp-python wrapper for Llama-3.2-1B-Instruct GGUF.

Uses create_chat_completion (OpenAI-compatible) so llama-cpp handles the
special-token formatting internally. This prevents the duplicate BOS token
warning that appears when building raw prompt strings manually.

Model is auto-downloaded from HuggingFace Hub on first use (same as
sentence-transformers), then served from ~/.cache/huggingface/hub/.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from huggingface_hub import hf_hub_download
from llama_cpp import Llama

from agsuperbrain.terminal import console

_llm_engine_cache: LlamaEngine | None = None


def get_llm_engine() -> LlamaEngine | None:
    global _llm_engine_cache
    if _llm_engine_cache is None:
        _llm_engine_cache = LlamaEngine()
    return _llm_engine_cache


_DEFAULT_REPO = "bartowski/Llama-3.2-1B-Instruct-GGUF"
_DEFAULT_FILENAME = "Llama-3.2-1B-Instruct-Q4_K_M.gguf"

_SYSTEM_PROMPT = """You are Super-Brain, a local code intelligence assistant.
You answer questions about codebases using ONLY the provided context.

Rules:
- Answer using ONLY the context below. Never hallucinate.
- If context is insufficient, say "Insufficient context to answer."
- Be specific: mention function names, parameters, return values when visible.
- Be concise: 2-3 sentences max.
- Respond ONLY with valid JSON in this exact shape:
  {"answer": "<your answer>", "confidence": <0.0-1.0>}
- confidence: 0.9 if context directly answers, 0.6 if partial, 0.3 if weak.
- No markdown, no code fences, no extra keys. Raw JSON only."""


@dataclass
class LLMResponse:
    answer: str
    confidence: float
    raw: str
    used_llm: bool = True


def _parse_json(raw: str) -> tuple[str, float]:
    """Extract answer + confidence from raw LLM output with layered fallbacks."""
    text = raw.strip()
    # Strip accidental markdown fences
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)

    # Attempt 1: direct parse
    try:
        obj = json.loads(text)
        return str(obj.get("answer", "")).strip(), float(obj.get("confidence", 0.5))
    except (json.JSONDecodeError, ValueError):
        pass

    # Attempt 2: first {...} block
    m = re.search(r"\{[^{}]+\}", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group())
            return str(obj.get("answer", "")).strip(), float(obj.get("confidence", 0.5))
        except (json.JSONDecodeError, ValueError):
            pass

    # Attempt 3: regex field extraction
    a = re.search(r'"answer"\s*:\s*"([^"]+)"', text)
    c = re.search(r'"confidence"\s*:\s*([\d.]+)', text)
    if a:
        return a.group(1).strip(), float(c.group(1)) if c else 0.4

    return text[:300] if text else "No answer generated.", 0.2


def _auto_download(repo_id: str = _DEFAULT_REPO, filename: str = _DEFAULT_FILENAME) -> str:
    """
    Download GGUF from HuggingFace Hub if not cached, return local path.
    Identical mechanism to sentence-transformers auto-download.
    Cache: ~/.cache/huggingface/hub/
    """
    console.print(f"[dim]Checking model cache: [cyan]{repo_id}/{filename}[/cyan][/dim]")
    # hf_hub_download always resumes — resume_download kwarg removed (deprecated)
    local_path = hf_hub_download(repo_id=repo_id, filename=filename)
    return local_path


class LlamaEngine:
    """
    CPU-only LLM engine wrapping llama-cpp-python.

    Key design decision: uses create_chat_completion (OpenAI-compatible API)
    instead of raw prompt strings. This lets llama-cpp handle BOS/EOS token
    injection internally, preventing the duplicate-BOS warning.

    Usage:
        engine = LlamaEngine()                        # auto-download default
        engine = LlamaEngine(repo_id=..., filename=..)  # custom model
        resp   = engine.answer(context_text, query)
    """

    def __init__(
        self,
        repo_id: str = _DEFAULT_REPO,
        filename: str = _DEFAULT_FILENAME,
        model_path: Path | None = None,
        n_ctx: int = 2048,
        max_tokens: int = 256,
        temperature: float = 0.0,
        n_threads: int = 4,
    ) -> None:
        if model_path is not None and Path(model_path).exists():
            resolved = str(model_path)
            console.print(f"[dim]Using local model: {resolved}[/dim]")
        else:
            resolved = _auto_download(repo_id, filename)

        console.print(f"[dim]Loading LLM weights… (CPU, {n_threads} threads)[/dim]")
        self._llm = Llama(
            model_path=resolved,
            n_ctx=n_ctx,
            n_gpu_layers=0,  # CPU-only — mandatory
            n_threads=n_threads,
            verbose=False,
            # Enable chat format so create_chat_completion works correctly
            chat_format="llama-3",
        )
        self.max_tokens = max_tokens
        self.temperature = temperature
        console.print("[green]✓[/green] LLM ready")

    def answer(
        self,
        context: str,
        query: str,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """
        Generate a JSON answer from context + query.
        Uses chat completion API — no manual BOS token required.
        """
        mt = max_tokens or self.max_tokens
        try:
            result = self._llm.create_chat_completion(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {query}"},
                ],
                max_tokens=mt,
                temperature=self.temperature,
                response_format={"type": "json_object"},  # enforce JSON output
            )
            choices = result.get("choices") or []
            if not choices:
                raise ValueError("LLM returned no choices")
            raw = choices[0]["message"]["content"].strip()
            answer, conf = _parse_json(raw)
            return LLMResponse(answer=answer, confidence=conf, raw=raw)

        except Exception as exc:
            console.print(f"[yellow]LLM error (degraded): {exc}[/yellow]")
            return LLMResponse(
                answer=f"LLM generation failed: {exc}",
                confidence=0.0,
                raw="",
                used_llm=False,
            )
