"""Opt-in local HTTP adapter using the server's default microphone.

Requires TRANSCRIPT_API_TOKEN in the process environment (at least 32
characters). Azure settings continue to use transcript_app.config unchanged.
Use a single worker bound to 127.0.0.1; never run the desktop and HTTP recorder
against the same microphone simultaneously. No browser audio transport or
cross-origin access is enabled. A frontend must use an appropriate same-origin
integration and must not bundle the token into public assets.
"""

import asyncio
import os
from contextlib import asynccontextmanager, suppress
from secrets import compare_digest
from typing import Annotated, AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .service import (
    SessionConflict,
    SessionService,
    SessionSnapshot,
    SessionUnavailable,
)
from .ui_api import BrowserSessions, browser_routes


class StartSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    participant_names: list[Annotated[str, Field(max_length=200)]] = Field(
        default_factory=list, max_length=100
    )


class RenameSpeakerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker_id: str = Field(max_length=200)
    new_name: str = Field(max_length=200)


_bearer = HTTPBearer(auto_error=False)


def create_app(
    service: SessionService | None = None,
    token: str | None = None,
) -> FastAPI:
    """Create an isolated adapter; injectable dependencies avoid live Azure tests."""
    manager = service if service is not None else SessionService()
    browser = BrowserSessions(manager)

    async def consume_events() -> None:
        while True:
            await asyncio.to_thread(browser.expire)
            await asyncio.to_thread(manager.poll)
            await asyncio.sleep(0.1)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configured_token = token if token is not None else os.getenv("TRANSCRIPT_API_TOKEN", "")
        if len(configured_token) < 32 or configured_token != configured_token.strip():
            raise RuntimeError(
                "Set TRANSCRIPT_API_TOKEN to a backend-only token of at least 32 characters "
                "without leading or trailing whitespace."
            )
        application.state.api_token = configured_token.encode("utf-8")
        consumer = asyncio.create_task(consume_events())
        try:
            yield
        finally:
            consumer.cancel()
            try:
                with suppress(asyncio.CancelledError):
                    await consumer
            finally:
                try:
                    # Preserve accumulated finals on graceful server shutdown.
                    await asyncio.to_thread(manager.close if browser.owner else manager.stop)
                finally:
                    application.state.api_token = b""

    async def authorize(
        request: Request,
        credentials: Annotated[
            HTTPAuthorizationCredentials | None, Depends(_bearer)
        ],
    ) -> None:
        expected = getattr(request.app.state, "api_token", b"")
        supplied = credentials.credentials.encode("utf-8") if credentials else b""
        if not expected or not compare_digest(supplied, expected):
            raise HTTPException(
                status_code=401,
                detail="Authentication required.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    application = FastAPI(
        title="Local transcript backend",
        version="1.0.0",
        lifespan=lifespan,
        dependencies=[Depends(authorize)],
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost"],
        www_redirect=False,
    )

    @application.middleware("http")
    async def prevent_transcript_caching(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(SessionConflict)
    async def conflict_handler(request: Request, exc: SessionConflict) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @application.exception_handler(SessionUnavailable)
    async def unavailable_handler(request: Request, exc: SessionUnavailable) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @application.get("/api/session", response_model=SessionSnapshot)
    def get_session() -> SessionSnapshot:
        with browser.lock:
            browser.legacy_access()
            return manager.snapshot()

    @application.post("/api/session/start", response_model=SessionSnapshot)
    def start_session(body: StartSessionRequest) -> SessionSnapshot:
        with browser.lock:
            browser.legacy_access()
            return manager.start(body.participant_names)

    @application.patch("/api/session/speaker", response_model=SessionSnapshot)
    def rename_speaker(body: RenameSpeakerRequest) -> SessionSnapshot:
        with browser.lock:
            browser.legacy_access()
            return manager.rename(body.speaker_id, body.new_name)

    @application.post("/api/session/stop", response_model=SessionSnapshot)
    def stop_session() -> SessionSnapshot:
        with browser.lock:
            browser.legacy_access()
            return manager.stop()

    application.include_router(browser_routes(browser, StartSessionRequest, RenameSpeakerRequest))
    return application


app = create_app()
