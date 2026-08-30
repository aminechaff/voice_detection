from __future__ import annotations

import queue
import sys
import tempfile
import threading
import time
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

if __package__ in (None, ""):
    # Permet aussi `python src/voicemaster/app.py` pendant le développement.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from voicemaster.audio import AudioDevice, AudioRecorder, CaptureMode
    from voicemaster.dialogue import Dialogue, append_deduplicated_turns, interleave_transcripts
    from voicemaster.transcription import FasterWhisperTranscriber, Transcript
else:
    from .audio import AudioDevice, AudioRecorder, CaptureMode
    from .dialogue import Dialogue, append_deduplicated_turns, interleave_transcripts
    from .transcription import FasterWhisperTranscriber, Transcript

APP_BG = "#0B1020"
CARD = "#141B2D"
CARD_ALT = "#192238"
TEXT = "#F4F7FF"
MUTED = "#8E9AB5"
ACCENT = "#7C5CFC"
ACCENT_HOVER = "#6B4CE6"
GREEN = "#39D98A"
RED = "#FF5C72"

LANGUAGES = {
    "Français": "fr",
    "English": "en",
    "Deutsch": "de",
    "Español": "es",
    "Italiano": "it",
}
MODES = {"Rapide": "fast", "Précis": "accurate"}
SOURCE_LABELS = {"microphone": "Vous", "system": "PC"}


class VoiceMasterApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title("Voice Master")
        self.geometry("1080x760")
        self.minsize(920, 680)
        self.configure(fg_color=APP_BG)
        for icon_path in (
            Path.cwd() / "assets" / "voice-master.ico",
            Path(__file__).resolve().parents[2] / "assets" / "voice-master.ico",
        ):
            if icon_path.exists():
                self.iconbitmap(icon_path)
                break

        self._temporary_audio = tempfile.TemporaryDirectory(prefix="voice-master-")
        self.temporary_dir = Path(self._temporary_audio.name)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.recorder = AudioRecorder(self.temporary_dir, self._on_audio_level)
        self.transcriber = FasterWhisperTranscriber()
        self.microphones: list[AudioDevice] = []
        self.systems: list[AudioDevice] = []
        self.started_at = 0.0
        self.busy = False
        self.live_stop = threading.Event()
        self.live_thread: threading.Thread | None = None
        self.live_dialogue: Dialogue = []
        self.live_accumulated: dict[str, str] = {}
        self.live_failed = False
        self.display_text = ""
        self.levels = {"microphone": 0.0, "system": 0.0}

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll_events)
        self.after(50, self._animate)
        self.after(150, self.refresh_devices)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self, width=300, corner_radius=0, fg_color="#0E1528")
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            sidebar,
            text="Voice Master",
            justify="left",
            font=ctk.CTkFont(size=27, weight="bold"),
            text_color=TEXT,
        ).grid(row=0, column=0, sticky="w", padx=30, pady=(32, 5))
        ctk.CTkLabel(
            sidebar,
            text="Faster-Whisper · traitement local",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
        ).grid(row=1, column=0, sticky="w", padx=30, pady=(0, 30))

        self._section_label(sidebar, "SOURCE", 2)
        self.capture_mode = ctk.StringVar(value="Micro + PC")
        self.capture_segment = ctk.CTkSegmentedButton(
            sidebar,
            values=["Micro", "PC", "Micro + PC"],
            variable=self.capture_mode,
            command=lambda _: self._sync_source_controls(),
            selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER,
            unselected_color=CARD_ALT,
            unselected_hover_color="#222D48",
        )
        self.capture_segment.grid(row=3, column=0, padx=24, sticky="ew")

        self._section_label(sidebar, "MICROPHONE", 4)
        self.mic_menu = ctk.CTkOptionMenu(
            sidebar,
            values=["Recherche…"],
            fg_color=CARD_ALT,
            button_color="#273250",
            button_hover_color=ACCENT,
            dropdown_fg_color=CARD_ALT,
        )
        self.mic_menu.grid(row=5, column=0, padx=24, sticky="ew")

        self._section_label(sidebar, "SON DU PC (WASAPI)", 6)
        self.system_menu = ctk.CTkOptionMenu(
            sidebar,
            values=["Recherche…"],
            fg_color=CARD_ALT,
            button_color="#273250",
            button_hover_color=ACCENT,
            dropdown_fg_color=CARD_ALT,
        )
        self.system_menu.grid(row=7, column=0, padx=24, sticky="ew")

        self.refresh_button = ctk.CTkButton(
            sidebar,
            text="↻  Actualiser les appareils",
            command=self.refresh_devices,
            fg_color="transparent",
            border_width=1,
            border_color="#34415F",
            hover_color=CARD_ALT,
            text_color=MUTED,
        )
        self.refresh_button.grid(row=8, column=0, padx=24, pady=(14, 0), sticky="ew")

        self._section_label(sidebar, "TRANSCRIPTION", 9)
        options = ctk.CTkFrame(sidebar, fg_color="transparent")
        options.grid(row=10, column=0, padx=24, sticky="ew")
        options.grid_columnconfigure((0, 1), weight=1)
        self.language_menu = ctk.CTkOptionMenu(
            options,
            values=list(LANGUAGES),
            fg_color=CARD_ALT,
            button_color="#273250",
            dropdown_fg_color=CARD_ALT,
            width=118,
        )
        self.language_menu.grid(row=0, column=0, padx=(0, 5), sticky="ew")
        self.transcript_mode_menu = ctk.CTkOptionMenu(
            options,
            values=list(MODES),
            fg_color=CARD_ALT,
            button_color="#273250",
            dropdown_fg_color=CARD_ALT,
            width=118,
            command=lambda _: self._sync_live_control(),
        )
        self.transcript_mode_menu.grid(row=0, column=1, padx=(5, 0), sticky="ew")
        self.model_menu = ctk.CTkOptionMenu(
            sidebar,
            values=["small", "turbo", "medium", "large-v3"],
            fg_color=CARD_ALT,
            button_color="#273250",
            dropdown_fg_color=CARD_ALT,
        )
        self.model_menu.set("small")
        self.model_menu.grid(row=11, column=0, padx=24, pady=(10, 0), sticky="ew")
        self.live_enabled = ctk.IntVar(value=1)
        self.live_switch = ctk.CTkSwitch(
            sidebar,
            text="Texte en direct",
            variable=self.live_enabled,
            progress_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            font=ctk.CTkFont(size=13),
        )
        self.live_switch.grid(row=12, column=0, padx=26, pady=(13, 0), sticky="w")
        ctk.CTkLabel(
            sidebar,
            text="Direct disponible en mode ‘Rapide’.\nSmall est recommandé pour la vitesse.",
            justify="left",
            text_color=MUTED,
            font=ctk.CTkFont(size=11),
        ).grid(row=13, column=0, padx=26, pady=(8, 0), sticky="w")

        main = ctk.CTkFrame(self, corner_radius=0, fg_color=APP_BG)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(3, weight=1)

        header = ctk.CTkFrame(main, fg_color="transparent")
        header.grid(row=0, column=0, padx=38, pady=(28, 18), sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="Transcrire une conversation",
            font=ctk.CTkFont(size=25, weight="bold"),
            text_color=TEXT,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text="Les fichiers audio restent temporaires.",
            text_color=MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=1, column=0, pady=(4, 0), sticky="w")
        self.status_pill = ctk.CTkLabel(
            header,
            text="  PRÊT  ",
            fg_color="#21302E",
            text_color=GREEN,
            corner_radius=10,
            font=ctk.CTkFont(size=11, weight="bold"),
        )
        self.status_pill.grid(row=0, column=1, rowspan=2, sticky="e")

        recorder_card = ctk.CTkFrame(main, fg_color=CARD, corner_radius=18)
        recorder_card.grid(row=1, column=0, padx=38, sticky="ew")
        recorder_card.grid_columnconfigure(0, weight=1)
        self.timer_label = ctk.CTkLabel(
            recorder_card,
            text="00:00:00",
            text_color=TEXT,
            font=ctk.CTkFont(family="Consolas", size=44, weight="bold"),
        )
        self.timer_label.grid(row=0, column=0, pady=(28, 8))

        meters = ctk.CTkFrame(recorder_card, fg_color="transparent")
        meters.grid(row=1, column=0, padx=44, pady=8, sticky="ew")
        meters.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            meters, text="MIC", width=38, text_color=MUTED, font=ctk.CTkFont(size=11)
        ).grid(row=0, column=0)
        self.mic_meter = ctk.CTkProgressBar(
            meters, height=8, progress_color=ACCENT, fg_color="#28324A"
        )
        self.mic_meter.grid(row=0, column=1, padx=(10, 0), sticky="ew")
        self.mic_meter.set(0)
        ctk.CTkLabel(meters, text="PC", width=38, text_color=MUTED, font=ctk.CTkFont(size=11)).grid(
            row=1, column=0, pady=(10, 0)
        )
        self.pc_meter = ctk.CTkProgressBar(
            meters, height=8, progress_color="#38BDF8", fg_color="#28324A"
        )
        self.pc_meter.grid(row=1, column=1, padx=(10, 0), pady=(10, 0), sticky="ew")
        self.pc_meter.set(0)

        self.record_button = ctk.CTkButton(
            recorder_card,
            text="●  Démarrer l'enregistrement",
            command=self.toggle_recording,
            height=54,
            corner_radius=27,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            font=ctk.CTkFont(size=15, weight="bold"),
        )
        self.record_button.grid(row=2, column=0, padx=90, pady=(18, 30), sticky="ew")

        result_header = ctk.CTkFrame(main, fg_color="transparent")
        result_header.grid(row=2, column=0, padx=40, pady=(24, 10), sticky="ew")
        result_header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            result_header,
            text="Transcription",
            text_color=TEXT,
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        self.copy_button = ctk.CTkButton(
            result_header,
            text="Copier",
            width=85,
            fg_color="transparent",
            border_width=1,
            border_color="#34415F",
            hover_color=CARD_ALT,
            command=self._copy_text,
            state="disabled",
        )
        self.copy_button.grid(row=0, column=1, padx=(0, 8))
        self.save_button = ctk.CTkButton(
            result_header,
            text="Enregistrer .txt",
            width=125,
            fg_color="transparent",
            border_width=1,
            border_color="#34415F",
            hover_color=CARD_ALT,
            command=self._save_text,
            state="disabled",
        )
        self.save_button.grid(row=0, column=2)

        self.chat_frame = ctk.CTkScrollableFrame(
            main,
            fg_color=CARD,
            corner_radius=16,
            border_width=0,
            scrollbar_button_color="#34415F",
            scrollbar_button_hover_color=ACCENT,
        )
        self.chat_frame.grid(row=3, column=0, padx=38, pady=(0, 30), sticky="nsew")
        self.chat_frame.grid_columnconfigure(0, weight=1)
        self.chat_placeholder = ctk.CTkLabel(
            self.chat_frame,
            text="La conversation apparaîtra ici.",
            text_color=MUTED,
            font=ctk.CTkFont(size=14),
        )
        self.chat_placeholder.grid(row=0, column=0, padx=24, pady=32)
        self._sync_live_control()

    @staticmethod
    def _section_label(parent, text: str, row: int) -> None:
        ctk.CTkLabel(
            parent, text=text, text_color=MUTED, font=ctk.CTkFont(size=10, weight="bold")
        ).grid(row=row, column=0, padx=26, pady=(18, 7), sticky="w")

    def refresh_devices(self) -> None:
        if self.busy or self.recorder.is_recording:
            return
        self._set_status("APPAREILS…", MUTED, "#222B3F")
        self.refresh_button.configure(state="disabled")

        def work() -> None:
            try:
                self.events.put(("devices", self.recorder.list_devices()))
            except Exception as exc:
                self.events.put(("error", exc))

        threading.Thread(target=work, daemon=True).start()

    def _set_device_values(self, menu: ctk.CTkOptionMenu, devices: list[AudioDevice]) -> None:
        values = [device.label for device in devices] or ["Aucun appareil"]
        menu.configure(values=values)
        menu.set(values[0])

    def _sync_source_controls(self) -> None:
        mode = self._capture_mode()
        self.mic_menu.configure(state="normal" if mode in ("microphone", "both") else "disabled")
        self.system_menu.configure(state="normal" if mode in ("system", "both") else "disabled")

    def _sync_live_control(self) -> None:
        enabled = MODES[self.transcript_mode_menu.get()] == "fast"
        self.live_switch.configure(state="normal" if enabled else "disabled")

    def _capture_mode(self) -> CaptureMode:
        return {"Micro": "microphone", "PC": "system", "Micro + PC": "both"}[
            self.capture_mode.get()
        ]  # type: ignore[return-value]

    @staticmethod
    def _selected_device(menu: ctk.CTkOptionMenu, devices: list[AudioDevice]) -> AudioDevice | None:
        return next((device for device in devices if device.label == menu.get()), None)

    def toggle_recording(self) -> None:
        if self.busy:
            return
        if self.recorder.is_recording:
            self._finish_recording()
        else:
            try:
                self.recorder.start(
                    self._capture_mode(),
                    self._selected_device(self.mic_menu, self.microphones),
                    self._selected_device(self.system_menu, self.systems),
                )
            except Exception as exc:
                self._show_error(exc)
                return
            self.started_at = time.monotonic()
            self.live_dialogue = []
            self.live_accumulated = {}
            self.live_failed = False
            self.display_text = ""
            self._render_dialogue(
                [],
                placeholder="Chargement du direct…"
                if self._live_is_enabled()
                else "Enregistrement en cours…",
            )
            self.record_button.configure(
                text="■  Arrêter et transcrire", fg_color=RED, hover_color="#E4475E"
            )
            self._set_status("ENREGISTREMENT", RED, "#3B202C")
            self._lock_controls(True)
            if self._live_is_enabled():
                self._start_live_transcription()

    def _live_is_enabled(self) -> bool:
        return bool(self.live_enabled.get()) and MODES[self.transcript_mode_menu.get()] == "fast"

    def _start_live_transcription(self) -> None:
        self.live_stop.clear()
        model_size = self.model_menu.get()
        language = LANGUAGES[self.language_menu.get()]

        def work() -> None:
            chunk_number = 0
            try:
                self.transcriber.load_model(model_size)
                self.events.put(("live_ready", None))
                next_chunk = self.started_at + 4.0
                while not self.live_stop.wait(max(0.0, next_chunk - time.monotonic())):
                    if not self.recorder.is_recording:
                        break
                    chunk_number += 1
                    chunk_started = time.monotonic()
                    stem = self.temporary_dir / f"live-{chunk_number}"
                    tracks = self.recorder.drain_live_tracks(stem)
                    chunk_transcripts: dict[str, Transcript] = {}
                    for source, path in tracks.items():
                        try:
                            chunk_transcripts[source] = self.transcriber.transcribe(
                                path, model_size, language, "fast"
                            )
                        finally:
                            path.unlink(missing_ok=True)
                    append_deduplicated_turns(
                        self.live_dialogue,
                        self.live_accumulated,
                        interleave_transcripts(chunk_transcripts),
                    )
                    self.events.put(("live_snapshot", list(self.live_dialogue)))
                    next_chunk = chunk_started + 4.0
            except Exception as exc:
                self.live_failed = True
                self.events.put(("live_error", exc))

        self.live_thread = threading.Thread(target=work, daemon=True)
        self.live_thread.start()

    def _finish_recording(self) -> None:
        self.live_stop.set()
        self.busy = True
        self.record_button.configure(state="disabled", text="Préparation de l’audio…")
        self._set_status("TRAITEMENT", "#FBBF24", "#3A3020")

        def work() -> None:
            tracks: dict[str, Path] = {}
            try:
                use_live_result = self._live_is_enabled() and not self.live_failed
                tracks = self.recorder.stop(tail_only=use_live_result)
                if self.live_thread and self.live_thread.is_alive():
                    self.live_thread.join()
                self.events.put(("audio_ready", None))
                dialogue = (
                    list(self.live_dialogue) if use_live_result and not self.live_failed else []
                )
                accumulated = (
                    dict(self.live_accumulated) if use_live_result and not self.live_failed else {}
                )
                final_transcripts: dict[str, Transcript] = {}
                for source, path in tracks.items():
                    final_transcripts[source] = self.transcriber.transcribe(
                        path,
                        self.model_menu.get(),
                        LANGUAGES[self.language_menu.get()],
                        MODES[self.transcript_mode_menu.get()],
                    )
                final_turns = interleave_transcripts(final_transcripts)
                if use_live_result:
                    append_deduplicated_turns(
                        dialogue,
                        accumulated,
                        final_turns,
                    )
                else:
                    dialogue = final_turns
                self.events.put(("transcript_done", dialogue))
            except Exception as exc:
                self.events.put(("error", exc))
            finally:
                for path in tracks.values():
                    path.unlink(missing_ok=True)

        threading.Thread(target=work, daemon=True).start()

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "devices":
                    self.microphones, self.systems = payload  # type: ignore[misc]
                    self._set_device_values(self.mic_menu, self.microphones)
                    self._set_device_values(self.system_menu, self.systems)
                    self.refresh_button.configure(state="normal")
                    self._sync_source_controls()
                    self._set_status("PRÊT", GREEN, "#21302E")
                elif kind == "audio_ready":
                    self.record_button.configure(text="Finalisation Faster-Whisper…")
                elif kind == "transcript_done":
                    self._finish_transcription(payload)  # type: ignore[arg-type]
                elif kind == "live_ready":
                    self._set_status("DIRECT", GREEN, "#21302E")
                elif kind == "live_snapshot":
                    self._render_dialogue(payload)  # type: ignore[arg-type]
                elif kind == "live_error":
                    self.live_stop.set()
                    self._set_status("ENREGISTREMENT", RED, "#3B202C")
                elif kind == "error":
                    self._show_error(payload)  # type: ignore[arg-type]
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _finish_transcription(self, dialogue: Dialogue) -> None:
        self._render_dialogue(dialogue)
        self.busy = False
        self.record_button.configure(
            state="normal",
            text="●  Démarrer un nouvel enregistrement",
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
        )
        self._lock_controls(False)
        self._set_status("TERMINÉ", GREEN, "#21302E")

    def _render_dialogue(self, dialogue: Dialogue, placeholder: str | None = None) -> None:
        for child in self.chat_frame.winfo_children():
            child.destroy()
        parts: list[str] = []
        for row, (source, text) in enumerate(dialogue):
            label = SOURCE_LABELS[source]
            is_microphone = source == "microphone"
            line = ctk.CTkFrame(self.chat_frame, fg_color="transparent")
            line.grid(row=row, column=0, padx=18, pady=(7, 2), sticky="ew")
            line.grid_columnconfigure((0, 1), weight=1)
            bubble = ctk.CTkFrame(
                line,
                fg_color="#2A2452" if is_microphone else "#182B3C",
                corner_radius=14,
                border_width=1,
                border_color="#463B7B" if is_microphone else "#24455F",
            )
            bubble.grid(
                row=0,
                column=1 if is_microphone else 0,
                padx=(44, 0) if is_microphone else (0, 44),
                sticky="e" if is_microphone else "w",
            )
            ctk.CTkLabel(
                bubble,
                text=label,
                text_color="#B9A8FF" if is_microphone else "#67D4FF",
                font=ctk.CTkFont(size=11, weight="bold"),
            ).pack(anchor="w", padx=16, pady=(11, 2))
            ctk.CTkLabel(
                bubble,
                text=text,
                justify="left",
                anchor="w",
                wraplength=500,
                text_color="#EEF2FF",
                font=ctk.CTkFont(size=14),
            ).pack(anchor="w", padx=16, pady=(0, 12))
            parts.append(f"{label}\n{text}")
        if not parts:
            ctk.CTkLabel(
                self.chat_frame,
                text=placeholder or "Aucune parole détectée.",
                text_color=MUTED,
                font=ctk.CTkFont(size=14),
            ).grid(row=0, column=0, padx=24, pady=32)
        self.display_text = "\n\n".join(parts)
        button_state = "normal" if self.display_text else "disabled"
        self.copy_button.configure(state=button_state)
        self.save_button.configure(state=button_state)
        if parts:
            self.after_idle(self._scroll_chat_to_bottom)

    def _scroll_chat_to_bottom(self) -> None:
        try:
            self.chat_frame._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass

    def _copy_text(self) -> None:
        if not self.display_text:
            return
        self.clipboard_clear()
        self.clipboard_append(self.display_text)
        self._set_status("COPIÉ", GREEN, "#21302E")

    def _save_text(self) -> None:
        if not self.display_text:
            return
        filename = filedialog.asksaveasfilename(
            title="Enregistrer la transcription",
            defaultextension=".txt",
            filetypes=[("Fichier texte", "*.txt")],
            initialfile="transcription.txt",
        )
        if filename:
            Path(filename).write_text(self.display_text + "\n", encoding="utf-8")
            self._set_status("ENREGISTRÉ", GREEN, "#21302E")

    def _show_error(self, error: object) -> None:
        self.busy = False
        self.refresh_button.configure(state="normal")
        self.record_button.configure(
            state="normal",
            text="●  Démarrer l'enregistrement",
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
        )
        self._lock_controls(False)
        self._set_status("ERREUR", RED, "#3B202C")
        messagebox.showerror("Voice Master", str(error))

    def _lock_controls(self, locked: bool) -> None:
        state = "disabled" if locked else "normal"
        self.capture_segment.configure(state=state)
        self.language_menu.configure(state=state)
        self.transcript_mode_menu.configure(state=state)
        self.model_menu.configure(state=state)
        self.live_switch.configure(state=state)
        self.refresh_button.configure(state=state)
        if not locked:
            self._sync_source_controls()
            self._sync_live_control()
        else:
            self.mic_menu.configure(state="disabled")
            self.system_menu.configure(state="disabled")

    def _set_status(self, text: str, color: str, background: str) -> None:
        self.status_pill.configure(text=f"  {text}  ", text_color=color, fg_color=background)

    def _on_audio_level(self, source: str, level: float) -> None:
        self.levels[source] = level

    def _animate(self) -> None:
        if self.recorder.is_recording:
            elapsed = int(time.monotonic() - self.started_at)
            hours, rest = divmod(elapsed, 3600)
            minutes, seconds = divmod(rest, 60)
            self.timer_label.configure(text=f"{hours:02}:{minutes:02}:{seconds:02}")
        self.mic_meter.set(self.levels["microphone"])
        self.pc_meter.set(self.levels["system"])
        self.levels["microphone"] *= 0.82
        self.levels["system"] *= 0.82
        self.after(50, self._animate)

    def _on_close(self) -> None:
        self.live_stop.set()
        if self.recorder.is_recording:
            if not messagebox.askyesno("Voice Master", "Abandonner l’enregistrement en cours ?"):
                return
            self.recorder.close()
        self._temporary_audio.cleanup()
        self.destroy()


def main() -> None:
    app = VoiceMasterApp()
    app.mainloop()


if __name__ == "__main__":
    main()
