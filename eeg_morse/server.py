"""Local HTTP API for drag-and-drop decoding of recorded EEG files.

    uv run eeg-morse serve            # http://127.0.0.1:8770

GET  /api/health             -> models available
POST /api/recordings/decode  -> multipart `files` (+ optional `model`, `expected`, `sfreq`)

Every response uses one envelope: {"success": bool, "data": ..., "error": str | null}.
Binds to localhost by default; it is a single-user tool, so decodes are capped
at MAX_CONCURRENT and further requests get HTTP 429 instead of queueing.
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
import threading
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .service import DecodeRequest, available_models, decode_file
from .uploads import MAX_TOTAL_BYTES, Incoming, UploadError, read_notes, safe_name, stage

log = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8770
CORS_ENV = "DECODER_CORS_ORIGINS"
DEFAULT_ORIGINS = [f"http://{h}:{p}" for h in ("localhost", "127.0.0.1") for p in (3000, 3088, 3089)]
MAX_CONCURRENT = 2
MAX_SFREQ = 100_000.0

_slots = threading.BoundedSemaphore(MAX_CONCURRENT)


LOOPBACK_HOSTS = ["127.0.0.1", "localhost", "[::1]", "::1"]
HOSTS_ENV = "DECODER_ALLOWED_HOSTS"  # extra hostnames when hosted, e.g. a custom domain
# Set by Vercel at runtime; the deployment's own hostnames are trusted automatically.
VERCEL_HOST_VARS = ("VERCEL_URL", "VERCEL_BRANCH_URL", "VERCEL_PROJECT_PRODUCTION_URL")
UPLOAD_MB_ENV = "DECODER_MAX_UPLOAD_MB"
VERCEL_MAX_UPLOAD_MB = 4  # Vercel functions accept at most 4.5 MB per request
# The whole multipart body is parsed before the handler runs, so the size cap
# has to be enforced on Content-Length first (browsers always send it for FormData).
MAX_BODY_BYTES = MAX_TOTAL_BYTES + 1024 * 1024
MAX_ERROR_CHARS = 200
_ORIGIN_RE = re.compile(r"^https?://[A-Za-z0-9.\-\[\]:]+$")


def envelope(data=None, error: str | None = None, status: int = 200) -> JSONResponse:
    return JSONResponse({"success": error is None, "data": data, "error": error}, status_code=status)


def _hosted_hosts() -> list[str]:
    """Hostnames this deployment answers on (Vercel's own URLs + DECODER_ALLOWED_HOSTS)."""
    names = [os.environ.get(v, "") for v in VERCEL_HOST_VARS]
    names += os.environ.get(HOSTS_ENV, "").split(",")
    return sorted({n.strip().removeprefix("https://").rstrip("/") for n in names if n.strip()})


def _origins() -> list[str]:
    raw = os.environ.get(CORS_ENV, "")
    extra = [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]
    bad = [o for o in extra if not _ORIGIN_RE.match(o)]
    if bad:
        raise ValueError(f"{CORS_ENV} must list origins like http://localhost:3088 (no '*'): {bad}")
    return (extra or DEFAULT_ORIGINS) + [f"https://{h}" for h in _hosted_hosts()]


def _max_body_bytes() -> int:
    """Upload cap: DECODER_MAX_UPLOAD_MB, else Vercel's request limit when hosted there."""
    raw = os.environ.get(UPLOAD_MB_ENV)
    if raw:
        return int(float(raw) * 1024 * 1024)
    if os.environ.get("VERCEL"):
        return VERCEL_MAX_UPLOAD_MB * 1024 * 1024
    return MAX_BODY_BYTES


def _guard(origins: list[str], max_body: int):
    """Reject cross-site POSTs (blind CSRF from any open web page) and oversized bodies early."""
    allowed = set(origins)

    async def middleware(request: Request, call_next):
        if request.method == "POST":
            origin = request.headers.get("origin")
            if origin is not None and origin.rstrip("/") not in allowed:
                return envelope(error="This origin may not use the decoder.", status=403)
            length = request.headers.get("content-length")
            if length is None or not length.isdigit():
                return envelope(error="Uploads need a Content-Length header.", status=411)
            if int(length) > max_body:
                return envelope(error=f"Upload is larger than {max_body // (1024 * 1024)} MB.",
                                status=413)
        return await call_next(request)

    return middleware


def _public_error(exc: Exception, tmp: str) -> str:
    """User-actionable message without temp paths or long internals."""
    text = str(exc).replace(tmp, "<upload>").split("; streams found")[0]
    return text[:MAX_ERROR_CHARS]


def _parse_sfreq(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        sfreq = float(value)
    except ValueError as e:
        raise UploadError("sfreq must be a number (Hz).") from e
    if not 0 < sfreq <= MAX_SFREQ:
        raise UploadError(f"sfreq must be between 0 and {MAX_SFREQ:g} Hz.")
    return sfreq


NOTES_DIR_ENV = "EEG_MORSE_NOTES_DIR"


def _notes_dir(explicit: Path | None) -> Path | None:
    raw = explicit or (Path(os.environ[NOTES_DIR_ENV]) if os.environ.get(NOTES_DIR_ENV) else None)
    return raw.expanduser() if raw else None


def create_app(notes_dir: Path | None = None) -> FastAPI:
    notes = _notes_dir(notes_dir)
    app = FastAPI(title="eeg_morse decoder", version="0.1.0")
    origins = _origins()
    app.middleware("http")(_guard(origins, min(MAX_BODY_BYTES, _max_body_bytes())))
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"],
                       allow_headers=["*"])
    # DNS rebinding: a hostile page's domain resolving to 127.0.0.1 sends its own Host.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=LOOPBACK_HOSTS + _hosted_hosts())

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return envelope(error=str(exc.detail), status=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = ", ".join(".".join(str(p) for p in e.get("loc", [])[1:]) or "body" for e in exc.errors())
        return envelope(error=f"Invalid request ({fields}). Send files as multipart field 'files'.",
                        status=422)

    @app.get("/api/health")
    def health() -> JSONResponse:
        return envelope({"status": "ok", "models": available_models()})

    @app.post("/api/recordings/decode")
    def decode_recording(files: list[UploadFile] = File(...), model: str | None = Form(None),
                         expected: str | None = Form(None), sfreq: str | None = Form(None)) -> JSONResponse:
        if not _slots.acquire(blocking=False):
            return envelope(error="The decoder is busy with other files. Try again shortly.", status=429)
        try:
            return _decode(files, model, expected, sfreq, notes)
        finally:
            _slots.release()

    return app


def _decode(files: list[UploadFile], model: str | None, expected: str | None,
            sfreq: str | None, notes_dir: Path | None = None) -> JSONResponse:
    tmp = ""
    try:
        rate = _parse_sfreq(sfreq)
        with tempfile.TemporaryDirectory(prefix="eeg_upload_") as tmp:
            path = stage([Incoming(f.filename or "", f.file) for f in files], Path(tmp))
            req = DecodeRequest(path, safe_name(path.name), model, expected, rate,
                                tuple(read_notes(path, notes_dir)))
            return envelope(decode_file(req))
    except UploadError as e:
        return envelope(error=str(e), status=e.status)
    except (ValueError, KeyError) as e:
        # Bad/unsupported content (wrong format, too short, unknown channels, unknown model):
        # the user can act on these; temp paths are scrubbed from the message.
        log.warning("decode rejected: %s", e)
        return envelope(error=f"Could not decode this recording: {_public_error(e, tmp or '//')}",
                        status=422)
    except Exception:  # noqa: BLE001 - never leak a traceback to the client
        log.exception("decode failed")
        return envelope(error="Decoding failed unexpectedly. Check the decoder's terminal log.", status=500)


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, notes_dir: Path | None = None) -> None:
    import uvicorn

    if host not in LOOPBACK_HOSTS:
        # The API has no authentication and handles participant recordings.
        raise ValueError(f"refusing to bind {host!r}: the decoder API is for this laptop only "
                         "(use 127.0.0.1)")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if notes_dir is not None and not notes_dir.expanduser().is_dir():
        raise ValueError(f"--notes-dir {notes_dir} is not a folder")
    uvicorn.run(create_app(notes_dir), host=host, port=port, log_level="info", timeout_keep_alive=5)
