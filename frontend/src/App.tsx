import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ApiError,
  closeSession,
  mutateSession,
  readSnapshot,
} from './api';
import type { Action, Snapshot } from './api';

interface Notice {
  title: string;
  message: string;
}

function describeError(error: unknown): Notice {
  if (error instanceof ApiError) {
    return { title: error.title, message: error.message };
  }
  return {
    title: 'Conexiune indisponibilă',
    message: 'Nu se poate confirma starea serviciului local. Verifică serviciul FastAPI. Transcrierea afișată a fost păstrată.',
  };
}

export default function App() {
  const [sessionId] = useState(() => crypto.randomUUID());
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [names, setNames] = useState('');
  const [speakerId, setSpeakerId] = useState('');
  const [newName, setNewName] = useState('');
  const [pending, setPending] = useState(false);
  const [connected, setConnected] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [connectionNotice, setConnectionNotice] = useState<Notice | null>(null);
  const latestSnapshot = useRef<Snapshot | null>(null);
  const busy = useRef(false);
  const generation = useRef(0);
  const pollController = useRef<AbortController | null>(null);
  const transcriptEnd = useRef<HTMLDivElement | null>(null);

  const acceptSnapshot = useCallback((next: Snapshot) => {
    const previous = latestSnapshot.current;
    if (previous && next.revision <= previous.revision) return;
    latestSnapshot.current = next;
    setSnapshot(next);
  }, []);

  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function poll() {
      if (disposed) return;
      if (!busy.current) {
        const requestGeneration = generation.current;
        const controller = new AbortController();
        pollController.current = controller;
        const timeout = setTimeout(() => controller.abort(), 10000);
        try {
          const next = await readSnapshot(sessionId, controller.signal);
          if (!disposed && requestGeneration === generation.current) {
            acceptSnapshot(next);
            setConnected(true);
            setConnectionNotice(null);
          }
        } catch (error) {
          if (!disposed && requestGeneration === generation.current) {
            setConnected(false);
            setConnectionNotice(describeError(error));
          }
        } finally {
          clearTimeout(timeout);
          if (pollController.current === controller) {
            pollController.current = null;
          }
        }
      }
      if (!disposed) {
        const delay = latestSnapshot.current?.phase === 'recording' ? 100 : 1000;
        timer = setTimeout(() => void poll(), delay);
      }
    }

    void poll();
    return () => {
      disposed = true;
      clearTimeout(timer);
      pollController.current?.abort();
    };
  }, [acceptSnapshot, sessionId]);

  useEffect(() => {
    function warnBeforeLeaving(event: BeforeUnloadEvent) {
      const phase = latestSnapshot.current?.phase;
      if (busy.current || phase === 'recording' || phase === 'unsaved') {
        event.preventDefault();
        event.returnValue = '';
      }
    }
    function stopOnPageHide() {
      closeSession(sessionId);
    }
    window.addEventListener('beforeunload', warnBeforeLeaving);
    window.addEventListener('pagehide', stopOnPageHide);
    return () => {
      window.removeEventListener('beforeunload', warnBeforeLeaving);
      window.removeEventListener('pagehide', stopOnPageHide);
    };
  }, [sessionId]);

  useEffect(() => {
    const speakers = snapshot?.speakers ?? [];
    setSpeakerId((current) =>
      speakers.some((speaker) => speaker.id === current)
        ? current
        : (speakers[0]?.id ?? ''),
    );
  }, [snapshot?.speakers]);

  // Only transcript changes scroll the view; heartbeat/status updates do not.
  const transcriptContent = JSON.stringify([snapshot?.entries, snapshot?.partial]);
  useEffect(() => {
    transcriptEnd.current?.scrollIntoView({ block: 'nearest' });
  }, [transcriptContent]);

  async function perform(
    action: Action,
    body: Record<string, unknown>,
  ): Promise<boolean> {
    if (busy.current) return false;
    busy.current = true;
    generation.current += 1;
    pollController.current?.abort();
    setPending(true);
    setNotice(null);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 30000);
    try {
      const next = await mutateSession(sessionId, action, body, controller.signal);
      acceptSnapshot(next);
      setConnected(true);
      setConnectionNotice(null);
      return true;
    } catch (error) {
      if (error instanceof ApiError && error.snapshot) {
        acceptSnapshot(error.snapshot);
      }
      // Even a timed-out mutation may have completed. Poll before another start.
      setConnected(false);
      setNotice(describeError(error));
      return false;
    } finally {
      clearTimeout(timeout);
      busy.current = false;
      setPending(false);
    }
  }

  async function renameSpeaker() {
    const trimmed = newName.trim();
    if (!trimmed || !snapshot?.speakers.some((speaker) => speaker.id === speakerId)) {
      return;
    }
    if (await perform('rename', { speaker_id: speakerId, new_name: trimmed })) {
      setNewName('');
    }
  }

  const sessionOpen = snapshot?.phase === 'recording' || snapshot?.phase === 'unsaved';
  const namesLocked = sessionOpen || pending || !snapshot;
  const entries = snapshot?.entries ?? [];
  const partial = snapshot?.partial;
  const lastEntry = entries[entries.length - 1];

  return (
    <main className="app">
      <header>
        <p className="eyebrow">Azure AI Foundry Speech</p>
        <h1>Transcriere întâlniri în timp real</h1>
        <p className="intro">
          Aplicație locală · se folosește microfonul calculatorului pe care rulează serviciul Python.
        </p>
      </header>

      <section className="panel controls" aria-label="Controlul sesiunii">
        <label htmlFor="participants">
          Participanți (separați prin virgulă, în ordinea în care vor vorbi):
        </label>
        <input
          id="participants"
          value={names}
          onChange={(event) => setNames(event.target.value)}
          disabled={namesLocked}
          autoComplete="off"
          spellCheck={false}
        />
        <div className="actions">
          <button
            type="button"
            className="primary"
            disabled={namesLocked || !connected}
            onClick={() => void perform('start', { participant_names: names.split(',') })}
          >
            <span aria-hidden="true">▶ </span>Pornește
          </button>
          <button
            type="button"
            disabled={pending || !sessionOpen}
            onClick={() => void perform('stop', {})}
          >
            <span aria-hidden="true">■ </span>Oprește și salvează
          </button>
          <p className="session-status" role="status">
            {pending ? 'Se procesează cererea...' : (snapshot?.status ?? 'Se verifică serviciul local...')}
          </p>
        </div>
        {snapshot?.phase === 'unsaved' && (
          <p className="warning">
            Înregistrarea este oprită, dar salvarea nu este confirmată. Apasă „Oprește și salvează” pentru a reîncerca.
          </p>
        )}
      </section>

      {connectionNotice && (
        <section className="notice" role="status">
          <h2>{connectionNotice.title}</h2>
          <p>{connectionNotice.message}</p>
          <p>Reconectarea este automată. O întrerupere a conexiunii nu confirmă oprirea microfonului.</p>
        </section>
      )}
      {notice && (
        <section className="notice" role="alert">
          <h2>{notice.title}</h2>
          <p>{notice.message}</p>
          <button type="button" onClick={() => setNotice(null)}>Închide mesajul</button>
        </section>
      )}

      <section className="panel transcript-panel" aria-labelledby="transcript-heading">
        <h2 id="transcript-heading">Transcriere live</h2>
        <div
          className="transcript"
          role="region"
          aria-label="Transcriere; text doar pentru citire"
          tabIndex={0}
        >
          {entries.length === 0 && !partial && (
            <p className="placeholder">Transcrierea va apărea aici după pornirea sesiunii.</p>
          )}
          {entries.map((entry, index) => (
            <p className="transcript-line" key={`${index}:${entry.speaker_id}`}>
              <span className="timestamp">[{entry.time}] </span>
              <strong>{entry.speaker}: </strong>
              {entry.text}
            </p>
          ))}
          {partial && (
            <p className="transcript-line partial" aria-label="Transcriere provizorie">
              {partial.speaker}: {partial.text}
            </p>
          )}
          <div ref={transcriptEnd} />
        </div>
        <p className="sr-only" aria-live="polite" aria-atomic="true">
          {lastEntry ? `[${lastEntry.time}] ${lastEntry.speaker}: ${lastEntry.text}` : ''}
        </p>
      </section>

      <form
        className="panel rename"
        aria-label="Redenumește vorbitor"
        onSubmit={(event) => {
          event.preventDefault();
          void renameSpeaker();
        }}
      >
        <div className="field">
          <label htmlFor="speaker">Redenumește vorbitor:</label>
          <select
            id="speaker"
            value={speakerId}
            disabled={pending || !snapshot?.speakers.length}
            onChange={(event) => setSpeakerId(event.target.value)}
          >
            {!snapshot?.speakers.length && <option value="">Niciun vorbitor detectat</option>}
            {snapshot?.speakers.map((speaker) => (
              <option key={speaker.id} value={speaker.id}>
                {speaker.id} ({speaker.name})
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="new-name">Nume nou</label>
          <input
            id="new-name"
            value={newName}
            disabled={pending}
            onChange={(event) => setNewName(event.target.value)}
            autoComplete="off"
          />
        </div>
        <button type="submit" disabled={pending}>Redenumește</button>
      </form>

      {snapshot?.saved && (
        <section className="panel saved" aria-label="Fișiere salvate">
          <h2>Fișiere salvate pe calculatorul serviciului</h2>
          <p>Text: <code>{snapshot.saved.txt_path}</code></p>
          <p>JSON: <code>{snapshot.saved.json_path}</code></p>
          <p className="intro">Redenumirile ulterioare nu modifică fișierele deja salvate.</p>
        </section>
      )}
    </main>
  );
}
