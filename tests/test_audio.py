import math
import wave
from pathlib import Path

from voicemaster.audio import AudioDevice, AudioRecorder, _Track, normalize_and_mix
from voicemaster.dialogue import interleave_transcripts, merge_live_text
from voicemaster.transcription import Transcript, TranscriptSegment


def _write_tone(path: Path, rate: int, channels: int, frequency: float = 440.0) -> None:
    frames = bytearray()
    for index in range(rate // 10):
        value = int(math.sin(2 * math.pi * frequency * index / rate) * 8000)
        frame = value.to_bytes(2, "little", signed=True) * channels
        frames.extend(frame)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(frames)


def test_normalize_and_mix_creates_mono_16k(tmp_path: Path) -> None:
    mic = tmp_path / "mic.wav"
    pc = tmp_path / "pc.wav"
    result = tmp_path / "result.wav"
    _write_tone(mic, 44_100, 1)
    _write_tone(pc, 48_000, 2, 880.0)

    normalize_and_mix([mic, pc], result)

    with wave.open(str(result), "rb") as output:
        assert output.getnchannels() == 1
        assert output.getsampwidth() == 2
        assert output.getframerate() == 16_000
        assert 1_590 <= output.getnframes() <= 1_610


def test_live_text_removes_overlapped_words() -> None:
    current = "Bonjour tout le monde ceci est un test"
    incoming = "ceci est un test de transcription en direct"
    assert merge_live_text(current, incoming) == (
        "Bonjour tout le monde ceci est un test de transcription en direct"
    )


def test_sources_are_interleaved_as_a_dialogue() -> None:
    transcripts = {
        "system": Transcript(
            "Salut. Très bien.",
            [
                TranscriptSegment(0.0, 0.8, "Salut."),
                TranscriptSegment(2.0, 2.8, "Très bien."),
            ],
        ),
        "microphone": Transcript(
            "Bonjour.",
            [
                TranscriptSegment(1.0, 1.7, "Bonjour."),
            ],
        ),
    }
    assert interleave_transcripts(transcripts) == [
        ("system", "Salut."),
        ("microphone", "Bonjour."),
        ("system", "Très bien."),
    ]


def test_stop_can_return_only_untranscribed_tail(tmp_path: Path) -> None:
    class DummyStream:
        def stop_stream(self):
            pass

        def close(self):
            pass

    raw = tmp_path / ".raw.wav"
    device = AudioDevice(0, "test", 1, 16_000)
    writer = wave.open(str(raw), "wb")
    writer.setnchannels(1)
    writer.setsampwidth(2)
    writer.setframerate(16_000)
    full_audio = bytes(16_000 * 2 * 2)  # deux secondes
    writer.writeframesraw(full_audio)

    recorder = AudioRecorder(tmp_path)
    recorder.is_recording = True
    recorder._tracks = [_Track("microphone", device, raw, DummyStream(), writer)]
    recorder._live_buffers = {"microphone": bytearray(bytes(16_000))}  # 0,5 s

    results = recorder.stop(tail_only=True)

    with wave.open(str(results["microphone"]), "rb") as output:
        assert output.getnframes() == 8_000
