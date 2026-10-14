"""Central configuration. Everything comes from environment variables (.env supported)."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent.parent


def _env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return default if v is None or not v.strip() else v.strip()


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    return _env(name, "true" if default else "false").lower() in {"1", "true", "yes", "on"}


def _path(name: str, default: str) -> Path:
    p = Path(_env(name, default))
    return p if p.is_absolute() else (BASE_DIR / p).resolve()


def _opt_float(name: str) -> Optional[float]:
    v = _env(name)
    try:
        return float(v) if v else None
    except ValueError:
        return None


@dataclass
class Settings:
    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    openai_model: str = field(default_factory=lambda: _env("OPENAI_MODEL", "gpt-4o-mini"))
    openai_embedding_model: str = field(default_factory=lambda: _env("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"))
    openai_vision_model: str = field(default_factory=lambda: _env("OPENAI_VISION_MODEL"))
    openai_transcription_model: str = field(default_factory=lambda: _env("OPENAI_TRANSCRIPTION_MODEL", "whisper-1"))
    openai_temperature: Optional[float] = field(default_factory=lambda: _opt_float("OPENAI_TEMPERATURE"))
    openai_timeout: int = field(default_factory=lambda: _int("OPENAI_TIMEOUT_SECONDS", 60))
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "sqlite:///./data/edumind.db"))
    chroma_path: Path = field(default_factory=lambda: _path("CHROMA_PATH", "./data/chroma"))
    upload_dir: Path = field(default_factory=lambda: _path("UPLOAD_DIR", "./data/uploads"))
    max_upload_size_mb: int = field(default_factory=lambda: _int("MAX_UPLOAD_SIZE_MB", 50))
    max_request_body_kb: int = field(default_factory=lambda: _int("MAX_REQUEST_BODY_KB", 1024))
    cors_origins: list = field(default_factory=lambda: [
        o.strip() for o in _env("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",") if o.strip()])
    chunk_size: int = field(default_factory=lambda: _int("CHUNK_SIZE", 1000))
    chunk_overlap: int = field(default_factory=lambda: _int("CHUNK_OVERLAP", 150))
    top_k: int = field(default_factory=lambda: _int("TOP_K", 5))
    min_relevance_score: float = field(default_factory=lambda: _float("MIN_RELEVANCE_SCORE", 0.25))
    enable_image_descriptions: bool = field(default_factory=lambda: _bool("ENABLE_IMAGE_DESCRIPTIONS", False))
    max_images_per_document: int = field(default_factory=lambda: _int("MAX_IMAGES_PER_DOCUMENT", 10))
    enable_ocr: bool = field(default_factory=lambda: _bool("ENABLE_OCR", True))
    video_segment_seconds: int = field(default_factory=lambda: _int("VIDEO_SEGMENT_SECONDS", 600))
    quiz_verify_with_llm: bool = field(default_factory=lambda: _bool("QUIZ_VERIFY_WITH_LLM", True))
    history_turns: int = field(default_factory=lambda: _int("HISTORY_TURNS", 6))
    rate_limit_per_minute: int = field(default_factory=lambda: _int("RATE_LIMIT_PER_MINUTE", 60))
    default_user_id: str = field(default_factory=lambda: _env("DEFAULT_USER_ID", "demo-user"))

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def effective_overlap(self) -> int:
        return max(0, min(self.chunk_overlap, self.chunk_size // 2))

    @property
    def vision_model(self) -> str:
        return self.openai_vision_model or self.openai_model


settings = Settings()