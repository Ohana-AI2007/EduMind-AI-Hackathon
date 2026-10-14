from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.dependencies import get_db, get_user_id
from backend.orchestrator import learner_agent
from backend.schemas import LearnerProfileOut, LearnerProfileUpdate

router = APIRouter(prefix="/api/learner", tags=["learner"])


@router.get("/profile", response_model=LearnerProfileOut)
def get_profile(db: Session = Depends(get_db), user_id: str = Depends(get_user_id)):
    return learner_agent.profile_view(db, user_id)


@router.put("/profile", response_model=LearnerProfileOut)
def update_profile(body: LearnerProfileUpdate, db: Session = Depends(get_db), user_id: str = Depends(get_user_id)):
    learner_agent.update_profile(db, user_id, body.level, body.goal, body.preferred_language)
    return learner_agent.profile_view(db, user_id)