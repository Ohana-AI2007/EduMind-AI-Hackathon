from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.agents.quiz_agent import quiz_to_out
from backend.dependencies import get_db, get_user_id, require_ai_user
from backend.errors import NotFoundError
from backend.models import Quiz, QuizAttempt
from backend.orchestrator import orchestrator
from backend.schemas import QuizGenerateRequest, QuizHistoryItem, QuizOut, QuizResult, QuizSubmitRequest
from backend.services import assessment_service

router = APIRouter(prefix="/api/quizzes", tags=["quizzes"])


@router.post("/generate", response_model=QuizOut, status_code=201)
def generate(req: QuizGenerateRequest, db: Session = Depends(get_db), user_id: str = Depends(require_ai_user)):
    return orchestrator.generate_quiz(db, user_id, req)


@router.post("/diagnostic", response_model=QuizOut, status_code=201)
def diagnostic(num_questions: int = Query(8, ge=3, le=15), db: Session = Depends(get_db),
               user_id: str = Depends(require_ai_user)):
    """Placement quiz for new students: mixed topics, intermediate difficulty."""
    req = QuizGenerateRequest(mode="mixed", num_questions=num_questions, difficulty="adaptive",
                              question_types=["mcq"], kind="diagnostic")
    return orchestrator.generate_quiz(db, user_id, req)


@router.get("/history", response_model=list[QuizHistoryItem])
def history(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db),
            user_id: str = Depends(get_user_id)):
    return assessment_service.quiz_history(db, user_id, limit, offset)


@router.get("/attempts/{attempt_id}", response_model=QuizResult)
def get_attempt(attempt_id: str, db: Session = Depends(get_db), user_id: str = Depends(get_user_id)):
    """Re-open the stored result/report of a past attempt."""
    attempt = db.get(QuizAttempt, attempt_id)
    if attempt is None or attempt.user_id != user_id:
        raise NotFoundError("Attempt not found.")
    return QuizResult.model_validate(attempt.report)


@router.get("/{quiz_id}", response_model=QuizOut)
def get_quiz(quiz_id: str, db: Session = Depends(get_db), user_id: str = Depends(get_user_id)):
    quiz = db.get(Quiz, quiz_id)
    if quiz is None or quiz.user_id != user_id:
        raise NotFoundError("Quiz not found.")
    return quiz_to_out(quiz)


@router.post("/{quiz_id}/submit", response_model=QuizResult)
def submit(quiz_id: str, req: QuizSubmitRequest, db: Session = Depends(get_db),
           user_id: str = Depends(get_user_id)):
    """Works without an API key (MCQ/numerical are graded locally; short answers fall back to lexical grading)."""
    return orchestrator.submit_quiz(db, user_id, quiz_id, req)