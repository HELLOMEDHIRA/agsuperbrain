"""
audio_extractor.py — faster-whisper transcription + segment extraction.

Fix:
  - First try with VAD enabled
  - If zero usable segments are returned, retry with vad_filter=False
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from faster_whisper import WhisperModel

from agsuperbrain.preprocessing.audio_fetcher import AudioFetchResult


def _nid(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


@dataclass
class AudioSourceNode:
    node_id: str
    title: str
    source_url: str
    source_type: str
    wav_path: str
    duration_s: float


@dataclass
class TranscriptSegment:
    node_id: str
    text: str
    start_sec: float
    end_sec: float
    source_id: str
    seq_index: int
    chunk_id: str
    source_path: str
    source_type: str = "audio"


@dataclass
class AudioExtractionResult:
    source: AudioSourceNode
    segments: list[TranscriptSegment] = field(default_factory=list)


class AudioExtractor:
    def __init__(self, model_size: str = "base") -> None:
        self._model_size = model_size
        self._model: WhisperModel | None = None

    def _get_model(self) -> WhisperModel:
        if self._model is None:
            self._model = WhisperModel(
                self._model_size,
                device="cpu",
                compute_type="int8",
            )
        return self._model

    def _transcribe_once(self, wav_path: Path, use_vad: bool):
        model = self._get_model()
        segments_iter, info = model.transcribe(
            str(wav_path),
            beam_size=5,
            word_timestamps=False,
            vad_filter=use_vad,
            vad_parameters={"min_silence_duration_ms": 500} if use_vad else None,
        )
        return list(segments_iter), info

    def extract(self, af: AudioFetchResult) -> AudioExtractionResult:
        wav_stem = _nid(Path(af.wav_path).stem)
        source_id = f"audio__{wav_stem}"

        raw_segments, info = self._transcribe_once(af.wav_path, use_vad=True)

        usable = [s for s in raw_segments if getattr(s, "text", "").strip()]
        if not usable:
            raw_segments, info = self._transcribe_once(af.wav_path, use_vad=False)
            usable = [s for s in raw_segments if getattr(s, "text", "").strip()]

        duration = getattr(info, "duration", af.duration_s) or af.duration_s
        source = AudioSourceNode(
            node_id=source_id,
            title=af.title,
            source_url=af.source_url,
            source_type=af.source_type,
            wav_path=str(af.wav_path),
            duration_s=duration,
        )

        segments: list[TranscriptSegment] = []
        for idx, seg in enumerate(usable):
            text = seg.text.strip()
            seg_id = f"{source_id}__seg_{idx:04d}"
            chunk_id = f"{wav_stem}::seg_{idx:04d}"

            segments.append(
                TranscriptSegment(
                    node_id=seg_id,
                    text=text,
                    start_sec=round(seg.start, 3),
                    end_sec=round(seg.end, 3),
                    source_id=source_id,
                    seq_index=idx,
                    chunk_id=chunk_id,
                    source_path=af.source_url,
                    source_type="audio",
                )
            )

        return AudioExtractionResult(source=source, segments=segments)
