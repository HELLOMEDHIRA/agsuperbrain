"""yt-dlp → temp file → ffmpeg to 16 kHz mono WAV. Download uses an explicit stem then glob (yt-dlp output quirk)."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

from agsuperbrain.terminal import TEXT_ENCODING


@dataclass
class AudioFetchResult:
    wav_path: Path
    source_url: str
    source_type: str
    title: str
    duration_s: float = 0.0


class AudioFetcher:
    """Local path or URL → 16 kHz mono WAV. Needs `yt-dlp` and `ffmpeg` on PATH for URLs."""

    def __init__(self, cache_dir: Path = Path("./.agsuperbrain/audio")) -> None:
        self._cache = cache_dir
        self._cache.mkdir(parents=True, exist_ok=True)

    def fetch(self, source: str | Path) -> AudioFetchResult:
        if isinstance(source, Path) or (isinstance(source, str) and not source.startswith(("http://", "https://"))):
            return self._from_local(Path(source))
        return self._from_url(str(source))

    # ── Local file ────────────────────────────────────────────────────────

    def _from_local(self, path: Path) -> AudioFetchResult:
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {path}")
        wav = self._to_wav(path, stem=path.stem)
        return AudioFetchResult(
            wav_path=wav,
            source_url=str(path.resolve()),
            source_type="local",
            title=path.stem,
        )

    # ── Remote URL ────────────────────────────────────────────────────────

    def _from_url(self, url: str) -> AudioFetchResult:
        url_hash = hashlib.sha1(url.encode()).hexdigest()[:12]
        wav_path = self._cache / f"{url_hash}.wav"

        # Cache hit
        if wav_path.exists():
            return AudioFetchResult(
                wav_path=wav_path,
                source_url=url,
                source_type="url",
                title=url_hash,
            )

        # ── Step 1: get title without downloading ─────────────────────────
        title = url_hash
        title_result = subprocess.run(
            ["yt-dlp", "--no-playlist", "--print", "title", url],
            capture_output=True,
            text=True,
            encoding=TEXT_ENCODING,
            errors="replace",
        )
        if title_result.returncode == 0 and title_result.stdout.strip():
            lines = title_result.stdout.strip().splitlines()
            title = lines[0] if lines else url_hash

        # ── Step 2: download best audio as-is (no conversion yet) ─────────
        # Use hash as output stem so we know exactly what file to expect.
        raw_template = str(self._cache / f"{url_hash}.%(ext)s")
        dl_result = subprocess.run(
            [
                "yt-dlp",
                "--no-playlist",
                "--extract-audio",
                "--audio-quality",
                "0",
                "--output",
                raw_template,
                url,
            ],
            capture_output=True,
            text=True,
            encoding=TEXT_ENCODING,
            errors="replace",
        )
        if dl_result.returncode != 0:
            raise RuntimeError(f"yt-dlp download failed:\n{dl_result.stderr[-1000:]}")

        # ── Step 3: find downloaded file (any extension) ──────────────────
        candidates = [
            f
            for f in self._cache.glob(f"{url_hash}.*")
            if f.suffix.lower() != ".wav"  # skip any partial .wav
        ]
        if not candidates:
            # Maybe yt-dlp already wrote a .wav
            candidates = list(self._cache.glob(f"{url_hash}.*"))
        if not candidates:
            raise RuntimeError(
                f"yt-dlp produced no output file.\nstdout: {dl_result.stdout[-500:]}\nstderr: {dl_result.stderr[-500:]}"
            )

        raw = max(candidates, key=lambda f: f.stat().st_size)

        # ── Step 4: convert to 16kHz mono WAV ─────────────────────────────
        if raw.suffix.lower() == ".wav":
            wav_path = self._to_wav(raw, stem=url_hash)
        else:
            wav_path = self._to_wav(raw, stem=url_hash)
            raw.unlink(missing_ok=True)

        return AudioFetchResult(
            wav_path=wav_path,
            source_url=url,
            source_type="url",
            title=title,
        )

    # ── WAV conversion ────────────────────────────────────────────────────

    def _to_wav(self, src: Path, stem: str) -> Path:
        """Convert any audio/video → 16kHz mono PCM WAV."""
        out = self._cache / f"{stem}.wav"
        if out.exists():
            return out
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(out),
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding=TEXT_ENCODING,
            errors="replace",
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed for {src}:\n{result.stderr[-800:]}")
        return out
