"""Tkinter GUI: live diarized transcript, participant naming, and session save."""

import queue
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, scrolledtext

from .config import load_settings
from .session_store import SessionStore
from .speaker_mapping import SpeakerMapper
from .transcriber import ConversationTranscriberService


class TranscriptApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Transcriere întâlniri în timp real (Azure AI Foundry Speech)")
        self.root.geometry("820x620")

        self.service: ConversationTranscriberService | None = None
        self.mapper = SpeakerMapper()
        self.entries: list[dict] = []
        self.session_store = SessionStore()
        self._has_partial = False

        self._build_widgets()
        self._poll_events()

    def _build_widgets(self) -> None:
        top_frame = tk.Frame(self.root)
        top_frame.pack(fill=tk.X, padx=10, pady=8)

        tk.Label(top_frame, text="Participanți (separați prin virgulă, în ordinea în care vor vorbi):").pack(anchor=tk.W)
        self.names_var = tk.StringVar()
        self.names_entry = tk.Entry(top_frame, textvariable=self.names_var)
        self.names_entry.pack(fill=tk.X, pady=(4, 0))

        button_frame = tk.Frame(self.root)
        button_frame.pack(fill=tk.X, padx=10, pady=(0, 8))

        self.start_button = tk.Button(button_frame, text="▶ Pornește", command=self.start_session)
        self.start_button.pack(side=tk.LEFT)

        self.stop_button = tk.Button(
            button_frame, text="■ Oprește și salvează", command=self.stop_session, state=tk.DISABLED
        )
        self.stop_button.pack(side=tk.LEFT, padx=8)

        self.status_var = tk.StringVar(value="Pregătit.")
        tk.Label(button_frame, textvariable=self.status_var, fg="gray").pack(side=tk.LEFT, padx=12)

        self.transcript_text = scrolledtext.ScrolledText(self.root, wrap=tk.WORD, state=tk.DISABLED)
        self.transcript_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))
        self.transcript_text.tag_configure("partial", foreground="gray")
        self.transcript_text.tag_configure("speaker", font=("TkDefaultFont", 10, "bold"))

        rename_frame = tk.Frame(self.root)
        rename_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        tk.Label(rename_frame, text="Redenumește vorbitor:").pack(side=tk.LEFT)
        self.speaker_id_var = tk.StringVar()
        self.speaker_id_menu = tk.OptionMenu(rename_frame, self.speaker_id_var, "")
        self.speaker_id_menu.pack(side=tk.LEFT, padx=6)
        self.new_name_var = tk.StringVar()
        tk.Entry(rename_frame, textvariable=self.new_name_var, width=20).pack(side=tk.LEFT, padx=6)
        tk.Button(rename_frame, text="Redenumește", command=self._rename_speaker).pack(side=tk.LEFT)

    def start_session(self) -> None:
        try:
            settings = load_settings()
        except RuntimeError as exc:
            messagebox.showerror("Configurare lipsă", str(exc))
            return

        names = self.names_var.get().split(",")
        self.mapper = SpeakerMapper(names)
        self.entries = []
        self._has_partial = False
        self._set_text_state(tk.NORMAL)
        self.transcript_text.delete("1.0", tk.END)
        self._set_text_state(tk.DISABLED)
        self._refresh_speaker_menu()

        self.service = ConversationTranscriberService(settings)
        try:
            self.service.start()
        except Exception as exc:
            messagebox.showerror("Eroare la pornire", str(exc))
            self.service = None
            return

        self.names_entry.config(state=tk.DISABLED)
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.status_var.set("Se înregistrează... vorbește în microfon.")

    def stop_session(self) -> None:
        if self.service:
            self.service.stop()
            self.service = None

        self.names_entry.config(state=tk.NORMAL)
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)

        if self.entries:
            _, txt_path = self.session_store.save(self.entries, self.mapper.mapping())
            self.status_var.set(f"Salvat: {txt_path}")
        else:
            self.status_var.set("Sesiune oprită (nimic de salvat).")

    def _poll_events(self) -> None:
        if self.service:
            try:
                while True:
                    event = self.service.events.get_nowait()
                    self._handle_event(event)
            except queue.Empty:
                pass
        self.root.after(100, self._poll_events)

    def _handle_event(self, event: tuple) -> None:
        kind = event[0]
        if kind == "status":
            self.status_var.set(event[1])
        elif kind == "error":
            self.status_var.set(f"Eroare: {event[1]}")
        elif kind == "partial":
            _, speaker_id, text = event
            self._show_partial(speaker_id, text)
        elif kind == "final":
            _, speaker_id, text = event
            self._add_final(speaker_id, text)

    def _show_partial(self, speaker_id: str, text: str) -> None:
        speaker = self.mapper.resolve(speaker_id)
        self._refresh_speaker_menu()
        self._set_text_state(tk.NORMAL)
        if self._has_partial:
            # Stop right before the widget's protected trailing newline, never past it.
            self.transcript_text.delete("partial_start", "end-1c")
        else:
            self.transcript_text.mark_set("partial_start", "end-1c")
            # Left gravity keeps the mark fixed while the partial text grows after it.
            self.transcript_text.mark_gravity("partial_start", tk.LEFT)
            self._has_partial = True
        self.transcript_text.insert(tk.END, f"{speaker}: {text}", ("partial",))
        self.transcript_text.see(tk.END)
        self._set_text_state(tk.DISABLED)

    def _add_final(self, speaker_id: str, text: str) -> None:
        speaker = self.mapper.resolve(speaker_id)
        self._refresh_speaker_menu()
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.entries.append({"time": timestamp, "speaker_id": speaker_id, "speaker": speaker, "text": text})

        self._set_text_state(tk.NORMAL)
        if self._has_partial:
            self.transcript_text.delete("partial_start", "end-1c")
            self._has_partial = False
        self.transcript_text.insert(tk.END, f"[{timestamp}] ")
        self.transcript_text.insert(tk.END, f"{speaker}: ", ("speaker",))
        self.transcript_text.insert(tk.END, f"{text}\n")
        self.transcript_text.see(tk.END)
        self._set_text_state(tk.DISABLED)

    def _set_text_state(self, state: str) -> None:
        self.transcript_text.config(state=state)

    def _refresh_speaker_menu(self) -> None:
        ids = self.mapper.known_speaker_ids()
        mapping = self.mapper.mapping()
        menu = self.speaker_id_menu["menu"]
        menu.delete(0, tk.END)
        for speaker_id in ids:
            menu.add_command(
                label=f"{speaker_id} ({mapping[speaker_id]})",
                command=lambda s=speaker_id: self.speaker_id_var.set(s),
            )
        if ids and not self.speaker_id_var.get():
            self.speaker_id_var.set(ids[0])

    def _rename_speaker(self) -> None:
        speaker_id = self.speaker_id_var.get()
        new_name = self.new_name_var.get().strip()
        if not speaker_id or not new_name:
            return
        self.mapper.rename(speaker_id, new_name)
        for entry in self.entries:
            if entry["speaker_id"] == speaker_id:
                entry["speaker"] = new_name
        self._redraw_transcript()
        self._refresh_speaker_menu()
        self.new_name_var.set("")

    def _redraw_transcript(self) -> None:
        self._set_text_state(tk.NORMAL)
        self.transcript_text.delete("1.0", tk.END)
        for entry in self.entries:
            self.transcript_text.insert(tk.END, f"[{entry['time']}] ")
            self.transcript_text.insert(tk.END, f"{entry['speaker']}: ", ("speaker",))
            self.transcript_text.insert(tk.END, f"{entry['text']}\n")
        self._has_partial = False
        self.transcript_text.see(tk.END)
        self._set_text_state(tk.DISABLED)

    def on_close(self) -> None:
        if self.service:
            self.service.stop()
        self.root.destroy()


def run() -> None:
    root = tk.Tk()
    app = TranscriptApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
