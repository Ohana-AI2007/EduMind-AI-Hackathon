from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.dependencies import get_db, get_user_id, require_ai_user
from backend.models import ConversationMessage
from backend.orchestrator import orchestrator
from backend.schemas import HistoryMessage, OrchestrateRequest, OrchestrateResponse, TutorChatRequest, TutorResponse

router = APIRouter(prefix="/api", tags=["tutor"])


@router.post("/tutor/chat", response_model=TutorResponse)
def chat(req: TutorChatRequest, db: Session = Depends(get_db), user_id: str = Depends(require_ai_user)):
    return orchestrator.tutor_chat(db, user_id, req)


@router.post("/orchestrate", response_model=OrchestrateResponse)
def orchestrate(req: OrchestrateRequest, db: Session = Depends(get_db), user_id: str = Depends(require_ai_user)):
    return orchestrator.handle(db, user_id, req)


@router.get("/tutor/history", response_model=list[HistoryMessage])
def history(session_id: str = Query("default", pattern=r"^[A-Za-z0-9_\-]{1,64}$"), limit: int = Query(50, ge=1, le=200),
            db: Session = Depends(get_db), user_id: str = Depends(get_user_id)):
    rows = db.scalars(select(ConversationMessage).where(ConversationMessage.user_id == user_id,
                                                        ConversationMessage.session_id == session_id)
                      .order_by(ConversationMessage.id.desc()).limit(limit)).all()
    return [HistoryMessage(role=r.role, content=r.content, created_at=r.created_at, meta=r.meta or {}) for r in reversed(rows)]