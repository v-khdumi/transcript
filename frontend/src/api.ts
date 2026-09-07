import { z } from 'zod';

const speakerSchema = z.object({
  id: z.string().min(1),
  name: z.string(),
});

const entrySchema = z.object({
  time: z.string(),
  speaker_id: z.string().min(1),
  speaker: z.string(),
  text: z.string(),
});

export const snapshotSchema = z.object({
  revision: z.number().int().nonnegative(),
  phase: z.enum(['idle', 'recording', 'unsaved', 'stopped']),
  status: z.string(),
  speakers: z.array(speakerSchema),
  entries: z.array(entrySchema),
  partial: z.object({
    speaker_id: z.string().min(1),
    speaker: z.string(),
    text: z.string(),
  }).nullable(),
  saved: z.object({
    json_path: z.string(),
    txt_path: z.string(),
  }).nullable(),
});

export type Snapshot = z.infer<typeof snapshotSchema>;
export type Action = 'start' | 'stop' | 'rename';

const errorSchema = z.object({
  title: z.string(),
  message: z.string(),
  snapshot: snapshotSchema.optional(),
});

export class ApiError extends Error {
  constructor(
    readonly title: string,
    message: string,
    readonly snapshot?: Snapshot,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

function sessionUrl(sessionId: string): string {
  return `/api/ui/sessions/${encodeURIComponent(sessionId)}`;
}

async function requestSnapshot(
  url: string,
  init: RequestInit,
): Promise<Snapshot> {
  const response = await fetch(url, {
    ...init,
    credentials: 'same-origin',
    cache: 'no-store',
    redirect: 'error',
    headers: {
      Accept: 'application/json',
      'X-Transcript-Client': 'browser',
      ...init.headers,
    },
  });

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new ApiError(
      'Răspuns API invalid',
      `Serviciul nu a returnat JSON valid (HTTP ${response.status}).`,
    );
  }

  if (!response.ok) {
    const parsed = errorSchema.safeParse(payload);
    if (parsed.success) {
      throw new ApiError(
        parsed.data.title,
        parsed.data.message,
        parsed.data.snapshot,
      );
    }
    throw new ApiError(
      'Eroare de serviciu',
      `Cererea nu a putut fi finalizată (HTTP ${response.status}).`,
    );
  }

  const parsed = snapshotSchema.safeParse(payload);
  if (!parsed.success) {
    throw new ApiError(
      'Răspuns API incompatibil',
      'Starea sesiunii nu respectă contractul interfeței. Transcrierea afișată a fost păstrată.',
    );
  }
  return parsed.data;
}

export function readSnapshot(
  sessionId: string,
  signal: AbortSignal,
): Promise<Snapshot> {
  return requestSnapshot(sessionUrl(sessionId), { signal });
}

export function mutateSession(
  sessionId: string,
  action: Action,
  body: Record<string, unknown>,
  signal: AbortSignal,
): Promise<Snapshot> {
  return requestSnapshot(`${sessionUrl(sessionId)}/${action}`, {
    method: 'POST',
    signal,
    headers: {
      'Content-Type': 'application/json',
      'X-Request-ID': crypto.randomUUID(),
    },
    body: JSON.stringify(body),
  });
}

// Best effort only: the backend lease must also stop abandoned recordings.
// This endpoint stops capture without saving, matching desktop window close.
export function closeSession(sessionId: string): void {
  void fetch(`${sessionUrl(sessionId)}/close`, {
    method: 'POST',
    credentials: 'same-origin',
    redirect: 'error',
    keepalive: true,
    headers: {
      'Content-Type': 'application/json',
      'X-Transcript-Client': 'browser',
      'X-Request-ID': crypto.randomUUID(),
    },
    body: '{}',
  }).catch(() => {
    // Browsers cannot guarantee delivery during page termination.
  });
}
