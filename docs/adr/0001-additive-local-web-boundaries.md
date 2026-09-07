# ADR 0001: Add a local web adapter without replacing the desktop application

- Status: Proposed; runtime implementation requires review and characterization tests.
- Scope: Architectural boundaries for Python/FastAPI and React 19/TypeScript.
- Baseline: [Application architecture](../architecture.md).

## Context

The application is a local Tkinter program using Azure Speech for live diarization. The GUI currently owns session state and consumes a thread-safe queue from an SDK adapter. Speaker naming and filesystem persistence already reside in separate modules.

The modernization request specifies FastAPI and React 19 with TypeScript while requiring existing behavior to remain available. No cloud deployment or additional AI functionality is requested. Moving microphone capture into a browser is not equivalent to the current SDK default-microphone implementation.

## Decision

Use an additive adapter architecture. Keep `main.py`, the desktop application, existing configuration, dependency pins, speech adapter, and export format intact in this documentation slice. Do not add runtime scaffolding or dependency manifests merely to represent the target stack.

A later implementation may introduce an application session coordinator and an optional FastAPI entry point with a React client. First characterize current behavior; then introduce the coordinator through adapters rather than rewriting the GUI. Migrating the desktop to shared orchestration is a separate gated step, not a prerequisite for documenting the boundaries.

The Python application owns authoritative session state, naming, credentials, speech integration, and saving. React owns display and interaction. FastAPI is a transport adapter, not the home of naming or persistence rules.

### Initial audio and operating scope

Assume the first optional web client controls the microphone attached to the Python host on the same machine. Label that source clearly. Do not request browser microphone permission or imply that client-device audio is captured. Browser capture would require a separate ADR covering consent, audio framing, encoding, buffering, SDK audio input, and disconnect handling.

Keep the optional service local-only and explicitly started. The current desktop startup must not open a listener. Remote access, multi-user use, cloud hosting, and simultaneous use of the host microphone by desktop and web are not supported by this initial design. Define a contention guard before enabling capture; unsupported concurrent use must not silently mix sessions.

### Transport and security gates

No endpoint paths, schemas, or streaming protocol are established by this ADR. Before implementation, the Backend and Frontend Agents must agree on:

- Session identity, command validation, lifecycle transitions, and whether start has been requested or actually acknowledged by the SDK.
- An ordered event envelope for status, errors, previews, committed entries, and rename updates, without leaking SDK objects.
- Snapshot/reconnection behavior, terminal-event handling, and queue limits. Do not silently discard finals or rename updates under load.
- Stop/save completion semantics and explicit treatment of finals arriving during shutdown. Current queue loss is an observed limitation, not a new reliability guarantee.
- A streaming choice based on actual interaction needs rather than treating the in-process queue as a public API.

Loopback binding alone is not sufficient protection against untrusted browser pages. Before exposing microphone controls, require a reviewed local-access mechanism, Host validation, explicit Origin validation for applicable HTTP and streaming traffic, and protection against cross-site state-changing requests. Do not use wildcard CORS as a shortcut. Remote exposure requires a separate authentication, authorization, TLS, and privacy review.

Azure keys remain in the Python process through the existing configuration mechanism. Never place them in frontend bundles, client-visible configuration, URLs, or logs. Network-facing errors must not expose raw SDK diagnostics, secrets, or unrestricted local paths; translating errors for the new adapter must not silently rewrite existing desktop messages. Treat participant names and transcripts as sensitive data. Do not introduce telemetry, raw audio persistence, transcript logging, or automatic uploads beyond the existing Azure speech flow.

### Persistence compatibility

Reuse existing JSON and text output semantics for the initial adapter. Keep output directory selection under trusted application configuration, not arbitrary client input. If file download is added, authorize access to the owning session's exports rather than exposing the output directory. Storage format changes, filename collision fixes, atomic writes, and close-time autosave require separate review because they change observable behavior.

## Alternatives considered

- **Replace Tkinter immediately:** rejected because it removes the only working interface and obscures behavior regressions.
- **Embed HTTP handlers directly in the GUI:** rejected because it couples two event loops and makes session ownership and threading harder to reason about.
- **Call Azure directly from React:** rejected because it changes the credential and audio boundaries without an approved design.
- **Introduce microservices or cloud infrastructure:** rejected as unnecessary for the local single-host workflow and outside the requested scope.
- **Extract every module before delivering an adapter:** rejected because speculative abstraction increases migration risk without demonstrating parity.

## Consequences

The desktop remains usable independently of web dependencies. Small adapters allow gradual verification and retain rollback through the unchanged entry point. The cost is temporary parallel presentation code and an explicit compatibility contract.

The first web option is deliberately not a remote meeting service. Host microphone ownership, SDK callback concurrency, and persistence completion require application-level coordination. React cannot serve as the authoritative source of speaker names or transcript history.

Known desktop limitations must be documented and tested rather than opportunistically repaired. Improved web semantics may be proposed, but differences from desktop behavior need explicit approval and corresponding tests.

## Acceptance and follow-up

1. Review this ADR and the baseline against the source snapshot.
2. Testing Agent supplies characterization tests for configuration, events, naming, rendering, lifecycle, and export compatibility.
3. Backend and Frontend Agents approve the wire contract and host-microphone UX before adding executable adapters.
4. Review local-access security and failure handling before enabling a network listener.
5. Verify desktop startup remains independent, then verify web parity with fake recognition events. Use an authorized live Azure smoke test only as an opt-in integration check.
6. Keep the desktop as the default until an explicit release decision approves otherwise. This ADR does not authorize deleting it.

This proposal adds no executable service, frontend, test files, deployment configuration, or generated artifacts. No commands or tests were executed.
