"""Knowledge/Retrieval agent: query formulation, retrieval, evidence-sufficiency decision."""
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from backend.config import settings
from backend.services import retrieval_service


@dataclass
class EvidencePack:
    query: str
    chunks: list = field(default_factory=list)
    sufficient: bool = False
    top_score: Optional[float] = None
    topics: list = field(default_factory=list)
    threshold: float = 0.0
    top_k: int = 0


class KnowledgeAgent:
    def build_query(self, question: str, history: list) -> str:
        """Short follow-ups ('why?') borrow the previous user question for retrieval (no LLM call)."""
        if len(question.split()) < 6:
            prev = [m["content"] for m in history if m["role"] == "user"]
            if prev:
                return f"{prev[-1]} {question}"[:1000]
        return question

    def gather(self, db: Session, user_id: str, question: str, history: list,
               document_ids: Optional[list] = None, top_k: Optional[int] = None) -> EvidencePack:
        k = top_k or settings.top_k
        query = self.build_query(question, history)
        chunks = retrieval_service.retrieve(db, user_id, query, top_k=k, document_ids=document_ids)
        return EvidencePack(query=query, chunks=chunks, sufficient=bool(chunks),
                            top_score=chunks[0].score if chunks else None,
                            topics=list(dict.fromkeys(c.topic for c in chunks)),
                            threshold=settings.min_relevance_score, top_k=k)