# Transcript application architecture

## Scope and status

This document describes the supplied source snapshot and defines boundaries for an additive modernization. It does not introduce a backend, frontend, network listener, or executable contract. The current application remains launched through `main.py`.

The requested future stack is Python with FastAPI and React 19 with TypeScript. Cloud deployment, additional AI capabilities, and replacement of the desktop application are outside this slice. Existing Azure Speech use remains part of the application; local operation does not mean offline transcription.

See [ADR 0001](adr/0001-additive-local-web-boundaries.md) for the migration decision and gates.

## Current module map

| Module | Current responsibility | Boundary to preserve |
| --- | --- | --- |
| `main.py` | Launches `transcript_app.gui.run` | Desktop composition entry point |
| `transcript_app/gui.py` | Tkinter widgets, session orchestration, in-memory entries, queue polling, rename and save actions | Existing presentation and orchestration adapter; not yet separated |
| `transcript_app/config.py` | Loads dotenv at import and constructs settings from environment variables | Process-local configuration and credential boundary |
| `transcript_app/transcriber.py` | Configures Azure Speech, captures the default host microphone, emits callback events | Speech infrastructure adapter |
| `transcript_app/speaker_mapping.py` | Assigns participant names and supports renaming | SDK- and UI-independent naming logic |
| `transcript_app/session_store.py` | Writes JSON and text files | Filesystem persistence adapter |
| `requirements.txt` | Pins the current desktop runtime dependencies | Existing manifest remains unchanged |

Current dependency direction:

```text
main -> gui -> config
            -> speaker_mapping
            -> session_store
            -> transcriber -> config + Azure Speech SDK
```

Azure callbacks enqueue tuples from background threads. Tkinter polls the queue every 100 milliseconds and handles events on its UI thread. No HTTP service, browser client, authentication layer, or browser audio ingestion exists in the supplied files.

## Compatibility baseline

### Configuration and capture

- `AZURE_SPEECH_KEY` is required. At least one of `AZURE_SPEECH_REGION` and `AZURE_SPEECH_ENDPOINT` is required.
- A configured endpoint takes precedence over region when constructing the SDK configuration.
- `AZURE_SPEECH_LANGUAGE` defaults to `ro-RO` when absent. Existing environment and dotenv loading semantics and Romanian configuration errors are compatibility requirements.
- Audio comes from `AudioConfig(use_default_microphone=True)` on the Python process host.
- `start()` requests asynchronous SDK startup without waiting on its future. Its return does not establish that recognition is active.
- `stop()` waits for the SDK stop future when a transcriber exists, then clears that SDK reference.

### Internal event contract

These are existing in-process tuples, not a public network schema:

| Tuple | Handling |
| --- | --- |
| `('status', message)` | Updates the UI status |
| `('error', message)` | Displays an error-prefixed status; does not itself stop or save |
| `('partial', speaker_id, text)` | Resolves the speaker and replaces the current preview |
| `('final', speaker_id, text)` | Resolves the speaker, appends an entry, and replaces the preview with committed text |

The transcriber emits partials only for nonempty text and finals only for nonempty recognized speech. Cancellation details become an error message. There is no sequence number, session identifier, acknowledgment, or replay contract today.

### Speaker naming and display

Participant names are comma-separated in the UI, then trimmed with empty names discarded by `SpeakerMapper`. Names are assigned on first resolution of each speaker ID; a partial can therefore consume the next participant name before a final arrives. After supplied names are exhausted, the speaker ID is the display name. Known speaker IDs retain insertion order, and `mapping()` returns a copy.

Final entries contain `time`, `speaker_id`, `speaker`, and `text`. The time is local wall-clock time formatted as `HH:MM:SS` when the GUI handles the final event, not the recognition offset. Renaming updates the mapping and matching existing entries. Redrawing after rename removes any visible partial preview. Partial replacement uses a left-gravity mark and stops before Tkinter's protected trailing newline; preserve this regression-sensitive behavior.

### Persistence and lifecycle

Starting a session resets the mapper, entries, and transcript display after configuration loads successfully. A successful start disables participant editing and the start button and enables stop.

Explicit stop stops the service and clears the GUI's reference before saving nonempty entries. Empty sessions are not saved. Closing the window stops an existing service and destroys the window without saving.

`SessionStore` defaults to `transcripts` relative to the working directory. It writes `transcript_YYYYMMDD_HHMMSS.json` and a matching `.txt` file using UTF-8. JSON has top-level `speakers` and `entries`, uses two-space indentation, and preserves non-ASCII characters. Text contains one `[time] speaker: text` line per entry. `save()` returns the JSON path followed by the text path.

Observed limitations are not authorization to change behavior: queued events are not explicitly drained after stop; SDK cancellation does not reset the GUI controls; second-resolution filenames can collide; the two writes are not atomic. Characterize these cases before proposing separately reviewed fixes.

## Target logical boundaries

The following boundaries are design constraints for future implementation, not modules added by this change:

1. **Presentation adapters:** retain Tkinter; add React as an optional client. React handles rendering and user intent, not Azure credentials, filesystem paths, or the authoritative speaker map.
2. **Application session coordinator:** serialize start, stop, rename, and recognition-event handling; own the mapper and committed entries. Define explicit ownership of the shared host microphone and an explicit lifecycle before implementation. Do not import Tkinter, FastAPI, or React concepts into this boundary.
3. **Naming logic:** reuse the existing `SpeakerMapper` behavior without adding framework dependencies.
4. **Speech boundary:** adapt the current service behind start, stop, and event-consumption operations. Keep SDK objects and credential-bearing settings inside Python infrastructure.
5. **Persistence boundary:** delegate desktop-compatible output to `SessionStore`. Do not permit a browser to choose arbitrary server filesystem paths.
6. **Transport adapter:** FastAPI translates validated requests and streamed events to and from the coordinator. Its wire schemas must be distinct from SDK objects and the internal tuple representation.
7. **Composition and configuration:** each optional entry point wires its adapters explicitly. Desktop startup must not import optional web dependencies or open network ports.

Desired dependency direction is presentation/transport -> application -> naming logic and adapter interfaces. Infrastructure implements those interfaces. Avoid speculative extraction or a shared Python/TypeScript package before the first adapter demonstrates a need.

## Required handoffs and verification

- **Backend Agent:** propose the coordinator and optional FastAPI adapter, including microphone ownership, cancellation semantics, callback handoff, stop ordering, error redaction, and explicit startup acknowledgment. Do not wrap blocking SDK stop or disk writes directly in the asynchronous request loop. Preserve the desktop entry point and current dependencies.
- **Frontend Agent:** implement an optional React 19/TypeScript client only after the audio and wire contracts are approved. Preserve Romanian presentation, preview replacement, participant order, rename effects, empty-session behavior, and export semantics. Do not claim browser microphone support when capture occurs on the Python host.
- **Platform follow-up:** review optional entry points and dependency placement only when implementation requires them. No cloud resources, deployment actions, generated outputs, or secrets are needed here.
- **Testing Agent:** own characterization and future integration tests. Cover missing configuration, endpoint precedence, language defaults, naming on partials, mapping copies, event filtering and order, preview replacement, rename/redraw, session reset, empty versus nonempty stop, close without save, UTF-8 output, and exact export shape. Use isolated environment variables, fake SDK callbacks, controlled clocks, and temporary output directories. Exercise Tkinter rendering in a suitable display environment.
- **Future web gates:** test concurrent commands, microphone contention, final events racing stop, disconnect/reconnect, bounded event delivery, unauthorized and cross-origin access, and absence of credentials or raw SDK diagnostics in client responses. Any changed lifecycle semantics require an explicit compatibility decision rather than a silent fix.
- **Manual smoke test:** with an authorized Azure resource and microphone, verify start, partial/final diarization, rename, stop/save, and close. This is opt-in and may transmit audio to Azure and incur service charges; it is not required to review these documentation additions.

No verification commands or tests were executed for this proposal.
