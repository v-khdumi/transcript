# React transcript interface

This is an additive React 19 + TypeScript interface. The FastAPI browser adapter is implemented in `backend/ui_api.py`; the original desktop remains available. This frontend does not contain a mock transcriber, browser speech recognition, Azure keys, or a replacement persistence implementation.

## Verified Integration and Limits

Run the backend from the repository root with `uvicorn backend.api:app --host 127.0.0.1 --port 8000 --workers 1` after installing `backend/requirements.txt`. Set `TRANSCRIPT_API_TOKEN` to a locally generated secret of at least 32 characters in both the backend and Vite server environments. Do not use a `VITE_` variable: the server proxy injects the bearer header and the browser bundle must never contain the token. Configure Azure Speech credentials only in the backend environment.

Only one browser page owns the recorder at a time. A 120-second lease expires without polling, stops capture without saving, and returns 410 to the expired page. The original `/api/session` endpoints cannot take over an active browser owner. Browser close and service shutdown stop browser-owned capture without saving. Explicit Stop saves; storage failures retain entries for retry. Request IDs prevent replay of successful mutations. Real microphone and Azure Speech acceptance is separate from tests with an injected SDK source.

The user approved preserving both files on same-second filename collisions on 2026-09-07; see `tests/approved-behavior.md`. Production hosting and a remotely accessible multi-user application are not provided by this local development proxy.

## Local frontend workflow

Use Node.js 22.12 or newer. From this directory:

```sh
npm ci --ignore-scripts
npm test -- --run
npm run typecheck
npm run build
npm run dev
```

These are instructions, not commands verified by this change. Do not commit dependency directories or generated build output. The development UI listens at `http://127.0.0.1:5173`; its frontend-local proxy forwards `/api` to `http://127.0.0.1:8000`. Vite preview checks static rendering only and does not supply an API proxy. Production serving and infrastructure are outside this frontend change.

Without the backend adapter, the interface displays a connection error and disables starting. It never presents simulated recording as real recording.

## Backend Agent handoff: session API

All paths below are relative to `/api/ui/sessions/{session_id}`. The frontend generates one random UUID for the lifetime of the mounted page. The UUID is a correlation identifier, not authentication or authorization. No transcript or session identifier is stored in browser persistent storage.

Every successful GET or start/stop/rename response must return the complete snapshot below with `Content-Type: application/json` and `Cache-Control: no-store`:

```json
{
  "revision": 0,
  "phase": "idle",
  "status": "Pregătit.",
  "speakers": [],
  "entries": [],
  "partial": null,
  "saved": null
}
```

Snapshot fields:

- `revision`: nonnegative integer, strictly increasing for each observable state change across every recording run for this page session. Never reset it on start. Unchanged snapshots may reuse the revision. If session state is lost on backend restart, return an explicit expiry error rather than silently reusing lower revisions.
- `phase`: `idle`, `recording`, `unsaved`, or `stopped`. `unsaved` means capture has stopped but persistence failed; it locks starting a new run and enables another stop/save attempt.
- `status`: Romanian user-facing status, including existing Azure status and cancellation/error messages. Error events must not silently discard the session.
- `speakers`: ordered array of `{ "id": "Guest-1", "name": "Ana" }`, in first-seen order, including IDs first observed in partial results.
- `entries`: ordered array of `{ "time": "14:03:07", "speaker_id": "Guest-1", "speaker": "Ana", "text": "Bună ziua." }`. The server supplies local timestamps using the existing `%H:%M:%S` convention.
- `partial`: null or `{ "speaker_id": "Guest-1", "speaker": "Ana", "text": "Bună" }`. It is a single provisional line, not an appended history.
- `saved`: null or `{ "json_path": "transcripts/transcript_20260907_140307.json", "txt_path": "transcripts/transcript_20260907_140307.txt" }`. Return actual paths only after both files are saved. They are displayed as text, not browser filesystem links.

### Endpoints

| Method / suffix | Request | Required behavior |
| --- | --- | --- |
| GET / | No body | Return the current full snapshot. For a previously unused page UUID, return the idle snapshot without starting capture. Polls must not drain data required by another reader. |
| POST /start | `{ "participant_names": ["Ana", " Mihai", ""] }` | Validate existing server settings first, then reset the transcript and mapper and start the existing server-machine microphone transcriber. Trim/filter participant names through `SpeakerMapper`, not a different naming algorithm. Return the resulting snapshot. Reject another start while recording or unsaved without resetting entries. |
| POST /stop | `{}` | Stop capture and serialize the existing finalized entries and speaker mapping through `SessionStore`. Return `Salvat: <txt_path>` and actual saved paths, or `Sesiune oprită (nimic de salvat).` for an empty session. Do not save partial text. Repeated stop on an already successfully stopped session must not create another pair of files. |
| POST /rename | `{ "speaker_id": "Guest-1", "new_name": "Ana Popescu" }` | Trim the name; an empty name is a no-op. Rename the known speaker and all its existing finalized entries, clear the partial line as desktop redraw does, and preserve speaker ordering. Allow rename after stop, but do not rewrite files already saved. |
| POST /close | `{}` | Idempotently stop capture without saving, matching desktop window close. Return 204 or a snapshot. Preserve the in-memory transcript for a page restored from browser back/forward cache. |

All mutations carry `Content-Type: application/json`, `X-Transcript-Client: browser`, and a unique `X-Request-ID`. Honor request IDs for idempotency and serialize mutations, snapshots, and SDK event processing per page session. Only one microphone owner may exist on the local machine; reject conflicting sessions with a clear error instead of hijacking capture.

Snapshot polling is non-overlapping, approximately every 100 ms while recording and every second otherwise. GET requests time out after 10 seconds; mutations time out after 30 seconds. An aborted browser request does not prove the server operation was canceled. The frontend reconciles using GET and never automatically retries mutations. The backend must ensure GET reports a coherent state after a mutation whose response was lost, and prevent duplicate starts or duplicate successful saves.

### Existing behavior to retain on the server

Reuse or wrap `load_settings`, `ConversationTranscriberService`, `SpeakerMapper`, and `SessionStore`; do not move Azure credentials into the frontend or replace their existing desktop interfaces. Preserve configured endpoint precedence, region fallback, Romanian language default, Azure error messages subject to credential redaction, UTF-8 JSON/plain-text formats, timestamps, and output-directory behavior.

Replace the current partial on every partial event. A final removes the partial and appends one finalized entry. Resolve names on partial as well as final events. Renaming clears the partial. Stop should retain whatever provisional line the existing desktop workflow would leave visible, but exclude it from persisted entries. Drain/stop behavior and events arriving during stop require an explicit desktop-parity test before finalizing the adapter.

A missing configuration error must preserve the prior transcript because desktop settings validation precedes reset. A subsequent transcriber-start failure should return the reset snapshot if reset already occurred. Only acknowledge recording after the start operation has succeeded sufficiently to permit stop; do not represent an unresolved start as idle while another start could race it.

### Errors and save recovery

Non-2xx responses use:

```json
{
  "title": "Configurare lipsă",
  "message": "Mesaj sigur pentru utilizator, fără secrete.",
  "snapshot": {
    "revision": 0,
    "phase": "idle",
    "status": "Pregătit.",
    "speakers": [],
    "entries": [],
    "partial": null,
    "saved": null
  }
}
```

`snapshot` is optional, but include it when the operation changed state before failing. Preserve `Configurare lipsă` and `Eroare la pornire` distinctions. On persistence failure, retain entries and mapping, return phase `unsaved`, and permit `/stop` to retry persistence without restarting capture. This is an additive recovery safeguard rather than permission to discard data. Keep action errors visible while polling recovers. Do not return raw tracebacks, subscription keys, credential-bearing endpoints, or other secrets.

## Security and lifecycle handoff

- Keep the service local by default and retain any existing authentication/security controls. Same-origin browser calls do not themselves authenticate a user or authorize a session UUID.
- Enforce session ownership and validate Host and Origin on the backend. Reject cross-origin state-changing requests, require the custom client header and JSON content type, and use the application's existing CSRF mechanisms if present. The custom header is not a standalone authentication mechanism.
- For local development, explicitly permit the known frontend origin `http://127.0.0.1:5173` if needed. The Vite proxy preserves Origin. Do not enable wildcard credentialed CORS or expose the development server publicly.
- Never add Azure secrets to Vite variables, browser storage, responses, logs, or source files. Do not log transcript request/response bodies by default.
- The microphone is the default microphone on the Python service machine, exactly as in the desktop app. Browser microphone capture and remote operation are not implemented and must not be implied.
- Page departure warns while recording, saving, or unsaved. A `pagehide` keepalive request asks the backend to stop without saving. Browser termination, crashes, network loss, and mobile suspension can prevent its delivery.
- A backend lease/heartbeat expiry must stop abandoned capture without automatic saving. Choose and document an expiry that accounts for background-tab throttling; GET polling may renew the lease. Serialize close/start races and ensure no recording outlives its lease. Immediate desktop-style close cleanup is not guaranteed in a browser.
- Back/forward-cache restoration resumes polling of the same page session. A normal reload creates a new page UUID. Expired sessions should produce a clear error rather than exposing a different session.
- Platform Agent ownership includes any eventual shared routing, static serving, HTTP security headers, deployment, and infrastructure. None is proposed here.

## Testing Agent handoff

Do not consider behavioral parity verified until automated tests and manual comparison against the unchanged desktop application cover:

1. Missing settings preserve prior text; start failure after reset reports the appropriate title; successful start locks names and enables stop.
2. Whitespace/empty participant names, duplicate display names, first speaker discovered in a partial, and speakers beyond the provided names.
3. Consecutive partial replacements, final-after-partial, final without partial, server timestamps, Unicode Romanian text, and final text containing HTML-like strings rendered literally.
4. Speaker selection, blank rename no-op, Enter submission, historical rename, partial clearing on rename, and rename after save without changing disk files.
5. Stop with no entries, stop with only a partial, nonempty JSON/text save parity, save failure/retry, and preservation of entries on transport errors.
6. Rapid clicks, delayed GET responses arriving after a mutation, monotonic revisions across new runs, invalid snapshots, backend restart/expiry, Azure cancellation, and mutation timeout followed by GET reconciliation.
7. Multiple tabs contending for the microphone, cross-origin mutation rejection, page-close no-save behavior, back/forward-cache restoration, and lease cleanup after browser termination or network loss.
8. Keyboard-only operation, visible focus, labels, screen-reader status/final announcements without provisional-text flooding, text selection/copy, narrow screens, and 200-percent zoom.
9. Frontend type-check and production build, followed by end-to-end local recording with the real FastAPI adapter and existing Azure configuration. Static compilation alone cannot validate transcription or persistence.
