from __future__ import annotations

import audioop
import math
import threading
import wave
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

CaptureMode = Literal["microphone", "system", "both"]


@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str
    channels: int
    sample_rate: int
    loopback: bool = False

    @property
    def label(self) -> str:
        return self.name


@dataclass
class _Track:
    kind: str
    device: AudioDevice
    path: Path
    stream: object
    writer: wave.Wave_write


def _unique_devices(devices: list[AudioDevice]) -> list[AudioDevice]:
    seen: set[tuple[str, int]] = set()
    result: list[AudioDevice] = []
    for device in devices:
        key = (device.name.casefold(), device.sample_rate)
        if key not in seen:
            result.append(device)
            seen.add(key)
    return result


class AudioRecorder:
    """Capture one or two WASAPI streams and produce a transcription-ready WAV."""

    target_rate = 16_000
    chunk_size = 1024

    def __init__(
        self, output_dir: Path, level_callback: Callable[[str, float], None] | None = None
    ):
        self.output_dir = output_dir
        self.level_callback = level_callback
        self._pa = None
        self._tracks: list[_Track] = []
        self._lock = threading.Lock()
        self._error: Exception | None = None
        self._live_buffers: dict[str, bytearray] = {}
        self.is_recording = False

    @staticmethod
    def _pyaudio():
        try:
            import pyaudiowpatch as pyaudio
        except ImportError as exc:
            raise RuntimeError("PyAudioWPatch n'est pas installé. Lancez .\\lancer.ps1.") from exc
        return pyaudio

    def list_devices(self) -> tuple[list[AudioDevice], list[AudioDevice]]:
        pyaudio = self._pyaudio()
        microphones: list[AudioDevice] = []
        systems: list[AudioDevice] = []
        with pyaudio.PyAudio() as pa:
            default_input = None
            try:
                default_input = int(pa.get_default_input_device_info()["index"])
            except OSError:
                pass

            for index in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(index)
                if int(info.get("maxInputChannels", 0)) < 1 or info.get("isLoopbackDevice", False):
                    continue
                microphones.append(
                    AudioDevice(
                        index=index,
                        name=str(info["name"]),
                        channels=1,
                        sample_rate=int(info["defaultSampleRate"]),
                    )
                )
            microphones.sort(key=lambda d: d.index != default_input)

            for info in pa.get_loopback_device_info_generator():
                systems.append(
                    AudioDevice(
                        index=int(info["index"]),
                        name=str(info["name"]).replace(" [Loopback]", ""),
                        channels=max(1, int(info["maxInputChannels"])),
                        sample_rate=int(info["defaultSampleRate"]),
                        loopback=True,
                    )
                )
        return _unique_devices(microphones), _unique_devices(systems)

    def start(
        self, mode: CaptureMode, microphone: AudioDevice | None, system: AudioDevice | None
    ) -> None:
        if self.is_recording:
            raise RuntimeError("Un enregistrement est déjà en cours.")
        selected: list[tuple[str, AudioDevice]] = []
        if mode in ("microphone", "both"):
            if microphone is None:
                raise RuntimeError("Aucun microphone disponible ou sélectionné.")
            selected.append(("microphone", microphone))
        if mode in ("system", "both"):
            if system is None:
                raise RuntimeError("Aucune sortie Windows compatible WASAPI n'est disponible.")
            selected.append(("system", system))

        self.output_dir.mkdir(parents=True, exist_ok=True)
        pyaudio = self._pyaudio()
        self._pa = pyaudio.PyAudio()
        self._tracks = []
        self._live_buffers = {kind: bytearray() for kind, _ in selected}
        self._error = None
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        try:
            for kind, device in selected:
                path = self.output_dir / f".{stamp}-{kind}.wav"
                writer = wave.open(str(path), "wb")
                writer.setnchannels(device.channels)
                writer.setsampwidth(2)
                writer.setframerate(device.sample_rate)

                def callback(data, frame_count, time_info, status, *, source=kind, wav=writer):
                    try:
                        with self._lock:
                            wav.writeframesraw(data)
                            self._live_buffers[source].extend(data)
                        if self.level_callback:
                            rms = audioop.rms(data, 2) / 32768.0 if data else 0.0
                            self.level_callback(source, min(1.0, math.sqrt(rms)))
                    except Exception as exc:  # PortAudio callbacks cannot re-raise safely.
                        self._error = exc
                        return (None, pyaudio.paAbort)
                    return (None, pyaudio.paContinue)

                stream = self._pa.open(
                    format=pyaudio.paInt16,
                    channels=device.channels,
                    rate=device.sample_rate,
                    input=True,
                    input_device_index=device.index,
                    frames_per_buffer=self.chunk_size,
                    stream_callback=callback,
                )
                self._tracks.append(_Track(kind, device, path, stream, writer))
            self.is_recording = True
        except Exception:
            self._close_tracks()
            for track in self._tracks:
                track.path.unlink(missing_ok=True)
            self._tracks = []
            self._live_buffers = {}
            raise

    def drain_live_tracks(self, stem: Path, overlap_seconds: float = 0.8) -> dict[str, Path]:
        """Build one temporary WAV per source received since the last drain.

        A short raw tail remains in each source buffer so words crossing a
        chunk boundary can be recognized again in the following chunk.
        """
        if not self.is_recording or not self._tracks:
            return {}
        snapshots: list[tuple[_Track, bytes]] = []
        with self._lock:
            for track in self._tracks:
                buffer = self._live_buffers.get(track.kind, bytearray())
                data = bytes(buffer)
                bytes_per_second = track.device.sample_rate * track.device.channels * 2
                keep = min(len(buffer), int(overlap_seconds * bytes_per_second))
                self._live_buffers[track.kind] = bytearray(buffer[-keep:]) if keep else bytearray()
                snapshots.append((track, data))
        if not snapshots or not any(data for _, data in snapshots):
            return {}

        raw_paths: list[Path] = []
        results: dict[str, Path] = {}
        stem.parent.mkdir(parents=True, exist_ok=True)
        try:
            for index, (track, data) in enumerate(snapshots):
                if not data:
                    continue
                raw_path = stem.parent / f".{stem.name}-raw-{index}.wav"
                raw_paths.append(raw_path)
                with wave.open(str(raw_path), "wb") as output:
                    output.setnchannels(track.device.channels)
                    output.setsampwidth(2)
                    output.setframerate(track.device.sample_rate)
                    output.writeframes(data)
                destination = stem.parent / f".{stem.name}-{track.kind}.wav"
                normalize_and_mix([raw_path], destination, self.target_rate)
                results[track.kind] = destination
        finally:
            for raw_path in raw_paths:
                raw_path.unlink(missing_ok=True)
        return results

    def stop(self, tail_only: bool = False) -> dict[str, Path]:
        """Stop capture and return temporary normalized tracks.

        With ``tail_only``, only audio accumulated since the latest live
        chunk (plus its short overlap) is returned. This avoids decoding the
        complete recording a second time when live transcription was active.
        """
        if not self.is_recording:
            raise RuntimeError("Aucun enregistrement en cours.")
        self.is_recording = False
        self._close_tracks()
        if self._error:
            error = self._error
            for track in self._tracks:
                track.path.unlink(missing_ok=True)
            self._tracks = []
            self._live_buffers = {}
            raise RuntimeError(f"La capture audio a échoué : {error}")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        results: dict[str, Path] = {}
        raw_tails: list[Path] = []
        try:
            for track in self._tracks:
                destination = self.output_dir / f".{stamp}-{track.kind}-final.wav"
                source = track.path
                if tail_only:
                    data = bytes(self._live_buffers.get(track.kind, b""))
                    if not data:
                        continue
                    source = self.output_dir / f".{stamp}-{track.kind}-tail.wav"
                    raw_tails.append(source)
                    with wave.open(str(source), "wb") as output:
                        output.setnchannels(track.device.channels)
                        output.setsampwidth(2)
                        output.setframerate(track.device.sample_rate)
                        output.writeframes(data)
                normalize_and_mix([source], destination, self.target_rate)
                results[track.kind] = destination
        finally:
            for raw_tail in raw_tails:
                raw_tail.unlink(missing_ok=True)
            for track in self._tracks:
                track.path.unlink(missing_ok=True)
            self._tracks = []
            self._live_buffers = {}
        return results

    def _close_tracks(self) -> None:
        for track in self._tracks:
            try:
                track.stream.stop_stream()
                track.stream.close()
            except Exception:
                pass
            try:
                with self._lock:
                    track.writer.close()
            except Exception:
                pass
        if self._pa is not None:
            self._pa.terminate()
            self._pa = None

    def close(self) -> None:
        if self.is_recording:
            self.is_recording = False
            self._close_tracks()
            for track in self._tracks:
                track.path.unlink(missing_ok=True)
            self._tracks = []
            self._live_buffers = {}


def _to_mono(data: bytes, channels: int) -> bytes:
    if channels == 2:
        return audioop.tomono(data, 2, 0.5, 0.5)
    if channels > 2:
        # Keep chunks small so unusual surround configurations do not incur
        # unbounded memory use while retaining their front left/right signal.
        frames = memoryview(data).cast("h")
        stereo = bytearray((len(frames) // channels) * 4)
        out = memoryview(stereo).cast("h")
        for frame in range(len(frames) // channels):
            out[frame * 2] = frames[frame * channels]
            out[frame * 2 + 1] = frames[frame * channels + 1]
        return audioop.tomono(stereo, 2, 0.5, 0.5)
    return data


def _normalize_track(path: Path, destination: Path, target_rate: int) -> None:
    with wave.open(str(path), "rb") as source, wave.open(str(destination), "wb") as output:
        channels = source.getnchannels()
        width = source.getsampwidth()
        rate = source.getframerate()
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(target_rate)
        rate_state = None
        while data := source.readframes(8192):
            if width != 2:
                data = audioop.lin2lin(data, width, 2)
            data = _to_mono(data, channels)
            if rate != target_rate:
                data, rate_state = audioop.ratecv(data, 2, 1, rate, target_rate, rate_state)
            output.writeframesraw(data)


def normalize_and_mix(paths: list[Path], destination: Path, target_rate: int = 16_000) -> None:
    if not paths:
        raise ValueError("Au moins une piste est requise.")
    normalized = [
        destination.parent / f".{destination.stem}-track-{index}.wav" for index in range(len(paths))
    ]
    readers: list[wave.Wave_read] = []
    try:
        for source, temporary in zip(paths, normalized, strict=True):
            _normalize_track(source, temporary, target_rate)
        readers = [wave.open(str(path), "rb") for path in normalized]
        gain = 1.0 / len(readers)
        with wave.open(str(destination), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(target_rate)
            while True:
                chunks = [reader.readframes(8192) for reader in readers]
                max_size = max(map(len, chunks))
                if max_size == 0:
                    break
                chunks = [chunk + bytes(max_size - len(chunk)) for chunk in chunks]
                mixed = audioop.mul(chunks[0], 2, gain)
                for chunk in chunks[1:]:
                    mixed = audioop.add(mixed, audioop.mul(chunk, 2, gain), 2)
                output.writeframesraw(mixed)
    finally:
        for reader in readers:
            reader.close()
        for temporary in normalized:
            temporary.unlink(missing_ok=True)
