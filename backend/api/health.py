import importlib.util
import shutil

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend import llm
from backend.config import settings
from backend.dependencies import get_db
from backend.services import embedding_service

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    """Never calls OpenAI, so it costs no credits."""
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except Exception:
        database = "error"
    try:
        embedding_service.get_collection().count()
        vector = "ok"
    except Exception:
        vector = "error"
    has = lambda m: importlib.util.find_spec(m) is not None  # noqa: E731
    return {
        "status": "ok" if database == "ok" and vector == "ok" else "degraded",
        "ai_configured": llm.is_configured(), "database": database, "vector_store": vector,
        "models": {"chat": settings.openai_model, "embedding": settings.openai_embedding_model},
        "features": {"pdf": has("fitz"), "pptx": has("pptx"), "ffmpeg": shutil.which("ffmpeg") is not None,
                     "ocr": has("pytesseract") and has("cv2") and shutil.which("tesseract") is not None,
                     "image_descriptions": settings.enable_image_descriptions and llm.is_configured()},
        "auth": "none: demo prototype, X-User-Id only partitions data and is not authentication"}