from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Transcript:
    text: str
    segments: list[TranscriptSegment]


class FasterWhisperTranscriber:
    def __init__(self) -> None:
        self._model = None
        self._model_size = ""

    def load_model(self, model_size: str) -> None:
        if self._model is None or self._model_size != model_size:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                model_size,
                device="cpu",
                compute_type="int8",
                cpu_threads=min(8, os.cpu_count() or 4),
                num_workers=1,
            )
            self._model_size = model_size

    def transcribe(
        self,
        audio_path: Path,
        model_size: str,
        language: str,
        mode: str,
    ) -> Transcript:
        self.load_model(model_size)
        fast_mode = mode == "fast"
        generated, _ = self._model.transcribe(
            str(audio_path),
            language=language,
            beam_size=1 if fast_mode else 5,
            best_of=1 if fast_mode else 5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
            condition_on_previous_text=not fast_mode,
        )
        segments = [
            TranscriptSegment(float(segment.start), float(segment.end), segment.text.strip())
            for segment in generated
            if segment.text.strip()
        ]
        return Transcript(
            text=" ".join(segment.text for segment in segments).strip(),
            segments=segments,
        )
