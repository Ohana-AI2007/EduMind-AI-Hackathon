"""Embeddings + ChromaDB vector store. SQLite remains the source of truth for chunk metadata."""
import threading
from typing import Optional

from backend import llm
from backend.config import settings
from backend.errors import AIServiceError

COLLECTION_NAME = "edumind_chunks"
_lock = threading.Lock()
_state: dict = {"collection": None, "path": None}


def get_collection():
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    path = str(settings.chroma_path)
    with _lock:
        if _state["collection"] is None or _state["path"] != path:
            settings.chroma_path.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=path, settings=ChromaSettings(anonymized_telemetry=False))
            _state["collection"] = client.get_or_create_collection(COLLECTION_NAME, metadata={"hnsw:space": "cosine"})
            _state["path"] = path
        return _state["collection"]


def embed_texts(texts: list, batch_size: int = 64) -> list:
    out: list = []
    clean = [(t or " ")[:8000] for t in texts]
    for i in range(0, len(clean), batch_size):
        out.extend(llm.embed(clean[i:i + batch_size]))
    return out


def build_metadata(chunk, document_name: str) -> dict:
    """Chroma accepts only scalar values; None is encoded as -1."""
    return {
        "chunk_id": chunk.id, "document_id": chunk.document_id, "user_id": chunk.user_id,
        "document_name": document_name, "content_type": chunk.content_type, "topic": chunk.topic,
        "page": chunk.page if chunk.page is not None else -1,
        "slide": chunk.slide if chunk.slide is not None else -1,
        "start_sec": float(chunk.start_sec) if chunk.start_sec is not None else -1.0,
        "end_sec": float(chunk.end_sec) if chunk.end_sec is not None else -1.0,
    }


def index_chunks(items: list) -> None:
    """items: list of (chunk_id, text, metadata)."""
    if not items:
        return
    col = get_collection()
    vectors = embed_texts([t for _, t, _ in items])
    if len(vectors) != len(items):
        raise AIServiceError("Embedding count mismatch.")
    for i in range(0, len(items), 100):
        part = items[i:i + 100]
        col.upsert(ids=[p[0] for p in part], embeddings=vectors[i:i + 100],
                   documents=[p[1] for p in part], metadatas=[p[2] for p in part])


def query(vector: list, user_id: str, n_results: int, document_ids: Optional[list] = None) -> list:
    """Returns [(chunk_id, cosine_distance)] restricted to the user (and optionally documents)."""
    col = get_collection()
    total = col.count()
    if total == 0:
        return []
    if document_ids:
        where = {"$and": [{"user_id": user_id}, {"document_id": {"$in": list(document_ids)}}]}
    else:
        where = {"user_id": user_id}
    res = col.query(query_embeddings=[vector], n_results=min(n_results, total), where=where, include=["distances"])
    return list(zip(res["ids"][0], res["distances"][0]))


def delete_document(document_id: str) -> None:
    get_collection().delete(where={"document_id": document_id})


def count_for_document(document_id: str) -> int:
    return len(get_collection().get(where={"document_id": document_id}, include=[])["ids"])