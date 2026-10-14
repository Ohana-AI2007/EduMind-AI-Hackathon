from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.dependencies import get_db, get_user_id
from backend.orchestrator import full_progress, recommendation_agent
from backend.schemas import ProgressOut, RecommendationsOut

router = APIRouter(prefix="/api", tags=["progress"])


@router.get("/progress", response_model=ProgressOut)
def progress(db: Session = Depends(get_db), user_id: str = Depends(get_user_id)):
    """Everything is computed from stored attempts, mastery rows and activity; nothing is hardcoded."""
    return full_progress(db, user_id)


@router.get("/recommendations", response_model=RecommendationsOut)
def recommendations(db: Session = Depends(get_db), user_id: str = Depends(get_user_id)):
    return RecommendationsOut(**recommendation_agent.recommend(db, user_id))