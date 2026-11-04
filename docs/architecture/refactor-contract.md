# Behavior-preserving refactor contract

## Decision and ownership

The application remains one local Python process launched with `python main.py`. Tkinter owns the GUI; Azure Speech SDK callbacks supply events through a thread-safe queue. There is no HTTP server, browser application, database or deployment change.

Frontend ownership covers GUI structure and rendering. Backend ownership covers configuration, transcription, speaker mapping and persistence. These are module responsibilities inside one project, not independently deployed projects. Shared architecture and dependency policy belong to platform. The Testing Agent owns `tests/modernization-acceptance.json` and additive harnesses under `tests/modernization/`; this document defines expectations only.

Prefer small extractions and adapters. Preserve existing import paths, callable signatures, event tuple shapes, Romanian messages and file formats. This decision does not approve behavior exceptions or implement the later agents' changes.

## Runtime and dependencies

Retain the README's Python 3.11+ requirement and existing pip installation from `requirements.txt`:

- `azure-cognitiveservices-speech==1.42.0`
- `python-dotenv==1.0.1`

The supplied snapshot has no lockfile and specifies no exact pip version. Do not invent a version, switch to Poetry/uv/Pipenv, introduce npm tooling or generate a lockfile. No peer-dependency system applies to this Python project. Native Speech SDK support, Tk availability, display access and microphone access are runtime compatibility risks, not verified successes. No dependency upgrade or audit result is asserted.

## Internal contracts

### Configuration

`load_settings() -> Settings` returns `speech_key: str`, `speech_region: str | None`, `speech_endpoint: str | None` and `language: str`. Importing the configuration module calls `dotenv.load_dotenv()` with its existing defaults; existing process environment values therefore retain precedence over dotenv values.

The environment names remain `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`, `AZURE_SPEECH_ENDPOINT` and `AZURE_SPEECH_LANGUAGE`. Missing language defaults to `ro-RO`; an explicitly empty language remains empty. A missing or empty key raises the existing Romanian `RuntimeError`. Missing or empty region and endpoint together raise the other existing Romanian `RuntimeError`. Do not trim, normalize or add validation as part of this refactor. A truthy endpoint takes precedence over region when constructing SpeechConfig. The key remains the SDK subscription credential.

### Transcription and event consumption

`ConversationTranscriberService(settings)` exposes `events`, a `queue.Queue` of tuples, plus `start()` and `stop()`.

- `('partial', speaker_id, text)` is queued only for nonempty interim text.
- `('final', speaker_id, text)` is queued only for nonempty text with `ResultReason.RecognizedSpeech`.
- `('status', 'Sesiune pornită')` and `('status', 'Sesiune oprită')` represent SDK session notifications.
- `('error', message)` uses `f'{details.reason}: {details.error_details}'` for cancellation details.

Speaker IDs and text pass through without normalization. AudioConfig continues to use the default microphone. Start invokes `start_transcribing_async()` without waiting on its result. Stop waits with `stop_transcribing_async().get()` and clears the SDK transcriber reference only after that wait succeeds. SDK callbacks must not mutate Tk widgets. The GUI continues polling its current service queue every 100 ms.

Do not silently repair lifecycle semantics during extraction: GUI stop clears its service reference before saving current entries, and window close stops the service and destroys the root without saving. Neither path explicitly drains pending events. Changing these semantics requires a separately reviewed behavior change, not this refactor.

### Speaker naming

`SpeakerMapper(participant_names=None)` strips names and drops blank names. `resolve(speaker_id)` assigns the next remaining participant name on first observation, then falls back to the unchanged speaker ID. Repeated resolution is stable. Partial events can establish speaker order before final events arrive.

`rename(speaker_id, new_name)` strips the name, ignores blank names and otherwise assigns it even for a previously unknown ID. `known_speaker_ids()` returns insertion order. `mapping()` returns a defensive dictionary copy. GUI rename updates matching stored entry speaker names and redraws confirmed entries; that redraw clears the current partial display.

### GUI and persistence handoff

Confirmed GUI entries have string fields `time`, `speaker_id`, `speaker` and `text`. Time is local `%H:%M:%S`. Interim text is display-only and must not become a saved entry. Preserve the partial mark's left gravity and deletion endpoint `end-1c` so repeated previews do not remove confirmed lines.

`SessionStore(output_dir='transcripts').save(entries, speaker_mapping)` returns `(json_path, txt_path)` as strings. It creates the output directory and writes UTF-8 files named `transcript_YYYYMMDD_HHMMSS.json` and `.txt` using local time. JSON contains `speakers` and `entries`, uses `ensure_ascii=False` and indentation of two spaces. Entries are serialized as supplied; no schema filtering is introduced. Text consists of `[time] speaker: text\n` for each entry in order.

Preserve current overwrite behavior for identical second-resolution filenames and current exception propagation. There is no transactional-write guarantee. The GUI saves only when its entries list is nonempty; direct store calls can save empty entries. Do not add autosave, remote storage or retention changes.

## Security and licensing

Keep `.env` and `transcripts/` excluded by `.gitignore`. Do not copy real credentials or conversations into documentation, fixtures or logs. Preserve the MIT license and existing consent/privacy guidance. Audio still goes to the configured Azure Speech resource; local execution is not offline transcription. No new authentication scheme is introduced.

## Required verification and handoff

The Testing Agent must add executable standard-library unittest characterization tests, run the same applicable assertions on baseline and candidate, and report failures, skips and environmental blockers honestly. The intended discovery command is `python -m unittest discover -s tests/modernization -p 'test_*.py' -v` after that agent creates the harness. Zero tests or skipped coverage is not acceptance.

Required assertions:

1. Isolate dotenv and process environment in subprocesses or controlled imports; assert exact Settings values, default versus empty language, environment precedence and both exact configuration errors.
2. Use an SDK fake with recorded calls to assert endpoint precedence, subscription and language propagation, default microphone selection, callback registrations, event filtering and exact tuples. Assert start does not wait, stop does wait, and repeated stop is inert after successful cleanup.
3. Assert ordered naming, whitespace handling, fallback IDs, partial-first assignment, unknown-ID rename, blank rename and defensive mapping copies.
4. With a real Tk root on an available display, drive repeated partials, a final event and retroactive rename. Assert confirmed lines survive preview replacement, partials are not stored, timestamps and entries match, widget states transition correctly and redraw removes the partial. Missing display access must be reported as blocked, not passed.
5. Freeze module clocks and use temporary directories to assert exact UTF-8 JSON/text content, returned paths, empty direct saves, GUI empty-session no-save, same-second overwrite and filesystem exception propagation. Assert close does not save and preserve the current pending-event handling.
6. Assert the entry point still invokes GUI run when executed as main, and check that credentials/transcript ignore rules and LICENSE remain intact.

In the existing requirements-managed environment, run `python -m pip check` and validate imports of `tkinter` and `azure.cognitiveservices.speech`. These checks do not replace the characterization suite or prove microphone/cloud operation. A separately authorized live smoke check requires consent, a supported audio device and configured Azure credentials; never embed those credentials in test artifacts. No verification in this document has been executed.
