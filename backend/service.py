"""Typed session orchestration; existing desktop classes remain unchanged."""

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from threading import RLock
from typing import Callable, Literal, Protocol
from uuid import uuid4

from transcript_app.session_store import SessionStore
from transcript_app.speaker_mapping import SpeakerMapper


TranscriptionEvent = (
    tuple[Literal["status", "error"], str]
    | tuple[Literal["partial", "final"], str, str]
)


class Transcriber(Protocol):
    events: Queue[TranscriptionEvent]

    def start(self) -> None: ...

    def stop(self) -> None: ...


class SessionConflict(RuntimeError):
    """An active or unsaved session prevents replacement."""


class SessionUnavailable(RuntimeError):
    """A sanitized operational failure suitable for the HTTP boundary."""


@dataclass(frozen=True)
class TranscriptEntry:
    time: str
    speaker_id: str
    speaker: str
    text: str


@dataclass(frozen=True)
class PartialTranscript:
    speaker_id: str
    speaker: str
    text: str


@dataclass(frozen=True)
class SavedFiles:
    json_path: str
    txt_path: str


@dataclass(frozen=True)
class SessionSnapshot:
    session_id: str | None
    running: bool
    status: str
    speakers: dict[str, str]
    entries: list[TranscriptEntry]
    partial: PartialTranscript | None
    saved: SavedFiles | None


def _default_transcriber() -> Transcriber:
    # Azure and environment configuration are needed only on explicit start.
    from transcript_app.config import load_settings
    from transcript_app.transcriber import ConversationTranscriberService

    return ConversationTranscriberService(load_settings())


class SessionService:
    """Own one local microphone session, with injectable I/O for verification.

    UUID directories prevent the legacy second-resolution filenames from
    overwriting a different API session. JSON and text contents still come
    exclusively from the existing SessionStore implementation.
    """

    def __init__(
        self,
        transcriber_factory: Callable[[], Transcriber] = _default_transcriber,
        output_dir: str = "transcripts",
        clock: Callable[[], datetime] = datetime.now,
        store_factory: Callable[[str], SessionStore] | None = None,
    ) -> None:
        self._lock = RLock()
        self._transcriber_factory = transcriber_factory
        self._clock = clock
        self._store_factory = store_factory or (
            lambda session_id: SessionStore(str(Path(output_dir) / session_id))
        )
        self._source: Transcriber | None = None
        self._store: SessionStore | None = None
        self._session_id: str | None = None
        self._mapper = SpeakerMapper()
        self._entries: list[TranscriptEntry] = []
        self._partial: PartialTranscript | None = None
        self._saved: SavedFiles | None = None
        self._status = "Pregătit."

    def start(self, participant_names: list[str]) -> SessionSnapshot:
        with self._lock:
            if self._source is not None:
                raise SessionConflict("O sesiune este deja activă; opriți-o mai întâi.")
            if self._entries and self._saved is None:
                raise SessionConflict("Salvați sesiunea curentă prin oprire înainte de a începe alta.")

            session_id = uuid4().hex
            try:
                store = self._store_factory(session_id)
                source = self._transcriber_factory()
            except Exception as exc:
                raise SessionUnavailable("Serviciul de transcriere nu poate fi inițializat.") from exc

            self._session_id = session_id
            self._store = store
            self._source = source
            self._mapper = SpeakerMapper(participant_names)
            self._entries = []
            self._partial = None
            self._saved = None
            self._status = "Se înregistrează... vorbește în microfon."
            try:
                source.start()
            except Exception as exc:
                self._status = "Eroare la pornire."
                try:
                    source.stop()
                except Exception:
                    # Retain ownership if cleanup fails; stop can be retried.
                    self._status = "Eroare la pornire. Reîncercați oprirea sesiunii."
                else:
                    self._source = None
                raise SessionUnavailable(self._status) from exc

            self._drain(source)
            return self._snapshot()

    def poll(self) -> None:
        """Consume queued SDK callbacks without copying the whole transcript."""
        with self._lock:
            if self._source is not None:
                self._drain(self._source)

    def close(self) -> SessionSnapshot:
        with self._lock:
            if self._source is not None:
                try:
                    self._source.stop()
                except Exception as exc:
                    raise SessionUnavailable("Unable to stop capture; retry close.") from exc
                self._source = None
            self._status = "Session closed without saving."
            return self._snapshot()

    def reset(self) -> None:
        with self._lock:
            if self._source is not None:
                raise SessionConflict("Capture is still active.")
            self._session_id = None
            self._entries = []
            self._mapper = SpeakerMapper()
            self._partial = None
            self._saved = None
            self._store = None
            self._status = "Ready."

    def snapshot(self) -> SessionSnapshot:
        with self._lock:
            if self._source is not None:
                self._drain(self._source)
            return self._snapshot()

    def rename(self, speaker_id: str, new_name: str) -> SessionSnapshot:
        with self._lock:
            if self._source is not None:
                self._drain(self._source)
            name = new_name.strip()
            if not speaker_id or not name:
                return self._snapshot()
            self._mapper.rename(speaker_id, name)
            self._entries = [
                replace(entry, speaker=name) if entry.speaker_id == speaker_id else entry
                for entry in self._entries
            ]
            # The desktop redraw also removes its current partial preview.
            self._partial = None
            self._saved = None
            return self._snapshot()

    def stop(self) -> SessionSnapshot:
        """Stop first, drain final callbacks, then save; repeated calls are safe."""
        with self._lock:
            if self._source is not None:
                source = self._source
                try:
                    source.stop()
                except Exception as exc:
                    self._status = "Oprirea a eșuat. Reîncercați oprirea sesiunii."
                    raise SessionUnavailable(self._status) from exc
                self._source = None
                self._drain(source)

            if self._entries and self._saved is None:
                if self._store is None:
                    raise SessionUnavailable("Stocarea sesiunii nu este disponibilă.")
                try:
                    json_path, txt_path = self._store.save(
                        [asdict(entry) for entry in self._entries],
                        self._mapper.mapping(),
                    )
                except OSError as exc:
                    self._status = "Salvarea a eșuat. Reîncercați oprirea pentru a salva."
                    raise SessionUnavailable(self._status) from exc
                self._saved = SavedFiles(json_path=json_path, txt_path=txt_path)

            if self._saved is not None:
                self._status = f"Salvat: {self._saved.txt_path}"
            elif self._session_id is not None:
                self._status = "Sesiune oprită (nimic de salvat)."
            return self._snapshot()

    def _drain(self, source: Transcriber) -> None:
        # A finite batch prevents continuously arriving callbacks from starving
        # stop/rename requests. The lifespan poller consumes subsequent batches.
        for _ in range(source.events.qsize()):
            try:
                event = source.events.get_nowait()
            except Empty:
                break
            if event[0] == "status":
                self._status = event[1]
            elif event[0] == "error":
                # SDK error details can contain resource information. They are
                # not exposed over HTTP; the legacy desktop path is untouched.
                self._status = "Eroare: transcrierea a fost anulată. Opriți sesiunea."
            elif event[0] == "partial":
                _, speaker_id, text = event
                self._partial = PartialTranscript(
                    speaker_id=speaker_id,
                    speaker=self._mapper.resolve(speaker_id),
                    text=text,
                )
            elif event[0] == "final":
                _, speaker_id, text = event
                self._entries.append(
                    TranscriptEntry(
                        time=self._clock().strftime("%H:%M:%S"),
                        speaker_id=speaker_id,
                        speaker=self._mapper.resolve(speaker_id),
                        text=text,
                    )
                )
                self._partial = None
                self._saved = None

    def _snapshot(self) -> SessionSnapshot:
        return SessionSnapshot(
            session_id=self._session_id,
            running=self._source is not None,
            status=self._status,
            speakers=self._mapper.mapping(),
            entries=list(self._entries),
            partial=self._partial,
            saved=self._saved,
        )
