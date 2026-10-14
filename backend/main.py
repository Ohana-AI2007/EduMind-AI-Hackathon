import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api import documents, evaluation, health, learner, progress, quizzes, tutor
from backend.config import settings
from backend.database import init_db
from backend.errors import EduMindError

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("edumind")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.chroma_path.mkdir(parents=True, exist_ok=True)
    init_db()
    yield


app = FastAPI(title="EduMind AI", version="1.0.0", lifespan=lifespan,
              description="Personalized tutoring and adaptive learning backend (demo prototype, no authentication).")


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    """Rejects oversized bodies announced via Content-Length (chunked bodies are bounded by the upload reader)."""
    cl = request.headers.get("content-length")
    if cl and cl.isdigit():
        if request.url.path == "/api/documents/upload":
            limit = settings.max_upload_bytes + 1024 * 1024
        else:
            limit = settings.max_request_body_kb * 1024
        if int(cl) > limit:
            return JSONResponse(status_code=413, content={"error": {"code": "payload_too_large",
                                                                    "message": "Request body is too large."}})
    return await call_next(request)


app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(EduMindError)
async def handle_app_error(_: Request, exc: EduMindError):
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.message}})


@app.exception_handler(Exception)
async def handle_unexpected(_: Request, exc: Exception):
    log.exception("Unhandled error: %s", type(exc).__name__)  # details stay in server logs only
    return JSONResponse(status_code=500, content={"error": {"code": "internal_error",
                                                            "message": "An unexpected error occurred."}})


for module in (health, documents, tutor, quizzes, learner, progress, evaluation):
    app.include_router(module.router)