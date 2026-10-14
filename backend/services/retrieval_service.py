"""Retrieval over the vector store, resolved against SQLite; also builds citations."""
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models import Chunk, Document
from backend.schemas import CitationOut
from backend.services import embedding_service


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    document_name: str
    text: str
    score: Optional[float]
    page: Optional[int]
    slide: Optional[int]
    start_sec: Optional[float]
    end_sec: Optional[float]
    topic: str
    content_type: str


def format_timestamp(sec: float) -> str:
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def location_label(name, page, slide, start, end, content_type) -> str:
    parts = [name]
    if page is not None:
        parts.append(f"p. {page}")
    if slide is not None:
        parts.append(f"slide {slide}")
    if start is not None:
        parts.append(f"{format_timestamp(start)}-{format_timestamp(end)}" if end else format_timestamp(start))
    if content_type == "image_description":
        parts.append("(AI-described image)")
    elif content_type == "ocr_text":
        parts.append("(OCR text)")
    return ", ".join(parts)


def to_retrieved(chunk: Chunk, doc_name: str, score: Optional[float]) -> RetrievedChunk:
    return RetrievedChunk(chunk.id, chunk.document_id, doc_name, chunk.text, score, chunk.page, chunk.slide,
                          chunk.start_sec, chunk.end_sec, chunk.topic, chunk.content_type)


def to_citation(c: RetrievedChunk, marker: Optional[str] = None, include_excerpt: bool = True,
                excerpt_chars: int = 300) -> CitationOut:
    return CitationOut(
        marker=marker, chunk_id=c.chunk_id, document_id=c.document_id, document_name=c.document_name,
        content_type=c.content_type, topic=c.topic, page=c.page, slide=c.slide, start_sec=c.start_sec,
        end_sec=c.end_sec, label=location_label(c.document_name, c.page, c.slide, c.start_sec, c.end_sec, c.content_type),
        excerpt=c.text[:excerpt_chars] if include_excerpt else None, score=c.score)


def snapshot_to_citation(src: dict, available: bool = True, include_quote: bool = False) -> CitationOut:
    """Citation from the snapshot stored on a quiz question (survives document deletion)."""
    return CitationOut(
        chunk_id=src.get("chunk_id", ""), document_id=src.get("document_id", ""),
        document_name=src.get("document_name", ""), content_type=src.get("content_type", "text"),
        topic=src.get("topic", ""), page=src.get("page"), slide=src.get("slide"),
        start_sec=src.get("start_sec"), end_sec=src.get("end_sec"),
        label=location_label(src.get("document_name", ""), src.get("page"), src.get("slide"),
                             src.get("start_sec"), src.get("end_sec"), src.get("content_type", "text")),
        excerpt=src.get("quote") if include_quote else None, source_available=available)


def retrieve(db: Session, user_id: str, query: str, top_k: Optional[int] = None,
             document_ids: Optional[list] = None, min_score: Optional[float] = None) -> list:
    top_k = top_k or settings.top_k
    threshold = settings.min_relevance_score if min_score is None else min_score
    vector = embedding_service.embed_texts([query])[0]
    hits = embedding_service.query(vector, user_id, top_k, document_ids)
    if not hits:
        return []
    ids = [h[0] for h in hits]
    rows = db.execute(
        select(Chunk, Document.filename).join(Document, Document.id == Chunk.document_id)
        .where(Chunk.id.in_(ids), Document.user_id == user_id, Document.status == "ready")).all()
    by_id = {c.id: (c, name) for c, name in rows}
    out = []
    for cid, dist in hits:
        if cid not in by_id:  # orphan vector: ignored
            continue
        score = round(1.0 - float(dist), 4)
        if score >= threshold:
            out.append(to_retrieved(by_id[cid][0], by_id[cid][1], score))
    return out