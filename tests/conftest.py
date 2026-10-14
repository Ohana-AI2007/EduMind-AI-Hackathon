import math
import os
import re
import tempfile
import zlib
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="edumind_test_"))
os.environ.update({
    "OPENAI_API_KEY": "",
    "DATABASE_URL": f"sqlite:///{_TMP.as_posix()}/test.db",
    "CHROMA_PATH": str(_TMP / "chroma"),
    "UPLOAD_DIR": str(_TMP / "uploads"),
    "ENABLE_IMAGE_DESCRIPTIONS": "false",
    "QUIZ_VERIFY_WITH_LLM": "true",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

_STOP = {"the", "is", "a", "an", "of", "in", "to", "and", "how", "do", "does", "what", "why", "which", "for", "on",
         "it", "this", "that", "with", "as", "by", "at", "be", "or", "from", "into", "are", "was", "were"}


def fake_embed(texts):
    """Deterministic hashed bag-of-words vectors (stopwords ignored): related texts get high cosine similarity."""
    out = []
    for t in texts:
        v = [0.0] * 512
        for w in re.findall(r"[a-z0-9]+", t.lower()):
            if w not in _STOP:
                v[zlib.crc32(w.encode()) % 512] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / n for x in v])
    return out


@pytest.fixture(scope="session")
def client():
    from backend.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def ai_on(monkeypatch):
    """Pretend an API key exists, mock embeddings, and forbid chat calls unless a test installs its own."""
    from backend import llm
    from backend.config import settings
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "min_relevance_score", 0.2)
    monkeypatch.setattr(llm, "embed", fake_embed)

    def no_chat(*a, **k):
        raise AssertionError("chat_json must not be called in this test")

    monkeypatch.setattr(llm, "chat_json", no_chat)
    return monkeypatch