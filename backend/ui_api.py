import hashlib
import json
import time
from dataclasses import asdict
from threading import RLock
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from .service import SessionService, SessionConflict, SessionUnavailable


class BrowserSessions:
    def __init__(self, manager: SessionService, clock=time.monotonic):
        self.manager = manager
        self.clock = clock
        self.lock = RLock()
        self.owner = None
        self.expired = set()
        self.deadline = 0.0
        self.revision = 0
        self.fingerprint = None
        self.closed = False
        self.requests = {}

    def expire(self):
        with self.lock:
            if self.owner and self.clock() > self.deadline:
                self.manager.close()
                self.expired.add(self.owner)
                self.owner = None
                self.manager.reset()

    def legacy_access(self):
        with self.lock:
            self.expire()
            if self.owner:
                raise SessionConflict("A browser session owns this recorder.")

    def claim(self, session_id):
        self.expire()
        if session_id in self.expired:
            raise HTTPException(410, "Browser session expired. Reload to create a new session.")
        if self.owner and self.owner != session_id:
            raise SessionConflict("Another browser session owns this recorder.")
        if self.owner is None:
            current = self.manager.snapshot()
            if current.running or current.entries and current.saved is None:
                raise SessionConflict("An active or unsaved session owns this recorder.")
            if len(self.expired) >= 1000:
                raise HTTPException(503, "Session capacity reached. Restart the local service.")
            self.manager.reset()
            self.owner = session_id
            self.requests.clear()
            self.closed = False
        self.deadline = self.clock() + 120

    def snapshot(self):
        current = asdict(self.manager.snapshot())
        phase = 'recording' if current['running'] else 'stopped' if self.closed or current['saved'] else 'unsaved' if current['entries'] else 'idle'
        result = {key: current[key] for key in ['status', 'entries', 'partial', 'saved']}
        result.update(phase=phase, speakers=[{'id': key, 'name': value} for key, value in current['speakers'].items()])
        fingerprint = json.dumps(result, sort_keys=True)
        if fingerprint != self.fingerprint:
            self.revision += 1
            self.fingerprint = fingerprint
        return {'revision': self.revision, **result}

    def dispatch(self, session_id, action, body, request_id=None):
        with self.lock:
            self.claim(session_id)
            signature = hashlib.sha256(json.dumps([action, body], sort_keys=True).encode()).hexdigest()
            if request_id in self.requests:
                if self.requests[request_id] != signature:
                    raise SessionConflict("Request ID reused for a different operation.")
                return self.snapshot()
            if action != 'read' and len(self.requests) >= 1000:
                raise HTTPException(429, "Session mutation limit reached.")
            try:
                if action == 'start':
                    self.manager.start(body['participant_names'])
                    self.closed = False
                elif action == 'rename':
                    self.manager.rename(body['speaker_id'], body['new_name'])
                elif action == 'stop':
                    self.manager.stop()
                elif action == 'close':
                    self.manager.close()
                    self.closed = True
                result = self.snapshot()
            except (SessionConflict, SessionUnavailable) as exc:
                return JSONResponse(status_code=409 if isinstance(exc, SessionConflict) else 503,
                                    content={'title': 'Session operation failed', 'message': str(exc), 'snapshot': self.snapshot()})
            if action != 'read':
                self.requests[request_id] = signature
            return result


def browser_routes(sessions, start_model, rename_model):
    router = APIRouter()

    def browser_request(request, mutation=False):
        if request.headers.get('X-Transcript-Client') != 'browser':
            raise HTTPException(403, "Browser client header required.")
        origin = request.headers.get('origin')
        if origin and origin not in {'http://127.0.0.1:5173', 'http://localhost:5173', 'http://127.0.0.1:8000', 'http://localhost:8000'}:
            raise HTTPException(403, "Origin is not permitted.")
        if mutation:
            if request.headers.get('content-type', '').split(';')[0] != 'application/json':
                raise HTTPException(415, "JSON required.")
            value = request.headers.get('X-Request-ID', '')
            try:
                return str(UUID(value))
            except ValueError:
                raise HTTPException(400, "UUID request ID required.")

    @router.get('/api/ui/sessions/{session_id}')
    def read(session_id: UUID, request: Request):
        browser_request(request)
        return sessions.dispatch(str(session_id), 'read', {})

    @router.post('/api/ui/sessions/{session_id}/{action}')
    async def mutate(session_id: UUID, action: str, request: Request):
        request_id = browser_request(request, True)
        if action not in {'start', 'rename', 'stop', 'close'}:
            raise HTTPException(404, "Unknown operation.")
        try:
            body = await request.json()
            if action == 'start':
                body = start_model.model_validate(body).model_dump()
            elif action == 'rename':
                body = rename_model.model_validate(body).model_dump()
            elif body != {}:
                raise ValueError('Empty request body required')
        except (ValueError, TypeError):
            raise HTTPException(422, "Invalid request payload.")
        import asyncio
        return await asyncio.to_thread(sessions.dispatch, str(session_id), action, body, request_id)

    return router