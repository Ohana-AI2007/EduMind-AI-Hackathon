from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.dependencies import get_db, require_ai_user
from backend.schemas import EvaluationRequest
from backend.services import evaluation_service

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


@router.get("/example")
def example_dataset():
    """Dataset format accepted by POST /api/evaluation/run (no API credits used)."""
    return {"dataset": evaluation_service.EXAMPLE_DATASET}


@router.post("/run")
def run(req: EvaluationRequest, db: Session = Depends(get_db), user_id: str = Depends(require_ai_user)):
    """Evaluates against the caller's own indexed documents. Uses embeddings; chat credits only if generate_answers
    is true or quiz_cases are given."""
    return evaluation_service.run_evaluation(db, user_id, req.dataset)