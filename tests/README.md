# Preserved-behavior test suite

## Running

From the repository root, with Python 3.10+ and the existing requirements installed:

```sh
python -B -m unittest discover -s tests -p 'test_*.py' -v
```

The suite uses standard-library unittest; no additional Python test dependencies are proposed. Tkinter must be available to import the existing GUI. On systems where Tkinter is packaged separately, its installation is an environment-owner responsibility.

The real-widget tests skip when Tk cannot open a display. A full GUI regression run requires a working display or an existing virtual-display environment. Treat skipped widget tests as unverified coverage, not a successful GUI verification.

These commands have not been executed as part of this proposal.

## Safety and isolation

- Azure Speech SDK constructors are mocked before transcription starts. Tests do not contact Azure or open a microphone.
- Credentials and endpoints in fixtures are synthetic.
- Configuration imports suppress automatic dotenv loading in the test process; settings tests replace the environment explicitly.
- A separate import-contract subprocess verifies the dotenv call without reading a real .env file.
- Persistence tests write only inside temporary directories and remove their files afterward.
- The suite does not modify application code, requirements, deployment configuration, credentials, or existing tests.

## Coverage

- Configuration: dotenv import hook, Romanian validation messages, key/location requirements, defaults, endpoint/region coexistence, and unchanged empty language values.
- Speaker mapping: first-seen assignment, trimming, fallback names, repeated IDs, duplicate names, rename behavior, insertion order, and defensive snapshots.
- Persistence: filenames, JSON shape, Unicode, plain-text formatting, empty sessions, input immutability, same-second collisions, and error propagation.
- Azure adapter: endpoint precedence, language and microphone configuration, callback subscriptions, asynchronous start, synchronous stop wait, filtering, tuple shapes, status/error messages, and worker-thread queue delivery.
- GUI controller: reset/start/stop, errors, polling, naming menus, rename propagation, partial/final routing, close behavior, and entry-point wiring.
- Integration: mocked SDK callbacks flow through the real queue, GUI controller, speaker mapper, and temporary session store.
- Real Tk regression: protected trailing newline, left-gravity partial mark, replacement of consecutive partials, finalization, rename redraw, and widget states.

Headless GUI tests verify controller calls, not Tk rendering. Only the real-widget tests exercise Text indices and marks.

## Characterized limitations and handoff

These tests describe the supplied implementation, not a proposed HTTP API:

- Saving twice within one second in the same directory reuses filenames and overwrites the earlier contents.
- The GUI saves only finalized entries. Closing the window stops transcription but does not save entries.
- stop_session does not drain events queued during the SDK stop wait before dropping its service reference.
- SDK start is initiated without waiting on the returned future; immediate exceptions are handled by the GUI, but delayed failures depend on callbacks.
- Save and stop exceptions currently propagate. A service-constructor exception also occurs outside the GUI's start-error handler.
- Renaming redraws finalized entries and removes any partial preview.

Changing these behaviors requires an explicit product decision and owner implementation rather than silently changing expectations during modernization. The collision and shutdown cases warrant review before claiming durability guarantees.

Backend and frontend owners must define FastAPI routes, request/response and streaming schemas, authentication, browser microphone behavior, and React components before HTTP contract tests or browser end-to-end tests can be implemented without inventing interfaces. Preserve the characterized event tuples, participant assignment, Unicode output, and session data shape at the adapter boundary unless an approved versioned contract supersedes them.

Live Azure recognition accuracy, native audio capture, actual credentials, operating-system permissions, and browser behavior remain outside this offline suite and require separately authorized verification.
