"""Custom agent orchestrator: intent routing and cooperation between the five agents."""
import re
import time
from contextlib import contextmanager
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend import llm
from backend.agents.knowledge_agent import KnowledgeAgent
from backend.agents.learner_agent import LearnerAgent
from backend.agents.quiz_agent import QuizAgent, quiz_to_out
from backend.agents.recommendation_agent import RecommendationAgent
from backend.agents.tutor_agent import TutorAgent
from backend.config import settings
from backend.errors import NotFoundError, UnprocessableError
from backend.models import (ActivityLog, ConversationMessage, Document, Quiz, QuestionResponse, QuizAttempt, new_id)
from backend.schemas import (OrchestrateRequest, OrchestrateResponse, ProgressOut, QuizGenerateRequest, QuizOut,
                             QuizResult, QuizSubmitRequest, RecommendationsOut, RetrievalInfo, TraceStep,
                             TutorChatRequest, TutorResponse)
from backend.services import assessment_service, mastery_service
from backend.services.retrieval_service import snapshot_to_citation

knowledge_agent, tutor_agent, quiz_agent = KnowledgeAgent(), TutorAgent(), QuizAgent()
learner_agent, recommendation_agent = LearnerAgent(), RecommendationAgent()

_DIAG = re.compile(r"\b(diagnostic|placement test|assess my level|find my level|where do i stand)\b", re.I)
_QUIZ = re.compile(r"\b(quiz|mock (exam|test)|practice (questions?|test)|test me|examine me|mcqs?|question paper)\b", re.I)
_PROGRESS = re.compile(r"\b(my progress|how am i doing|my (scores?|mastery|results|performance)|progress report|dashboard)\b", re.I)
_RECO = re.compile(r"\b(what should i (study|learn|revise|do|practice)( next)?|recommend\w*|revision (plan|priorit\w*)|study plan|"
                   r"what to (study|revise)|next topics?|weak (topics|areas))\b", re.I)


def _quiz_params(message: str) -> dict:
    p: dict = {}
    low = message.lower()
    m = re.search(r"\b(\d{1,2})\s+(?:\w+\s+)?(?:questions?|mcqs?)\b", message, re.I)
    if m:
        p["num_questions"] = max(1, min(20, int(m.group(1))))
    if re.search(r"\b(beginner|easy|basic)\b", low):
        p["difficulty"] = "beginner"
    elif re.search(r"\b(intermediate|medium)\b", low):
        p["difficulty"] = "intermediate"
    elif re.search(r"\b(advanced|hard|difficult|challenging)\b", low):
        p["difficulty"] = "advanced"
    types = []
    if re.search(r"\b(mcqs?|multiple[- ]choice)\b", low):
        types.append("mcq")
    if re.search(r"\bshort[- ]answers?\b", low):
        types.append("short_answer")
    if re.search(r"\b(numerical|numeric|calculation)s?\b", low):
        types.append("numerical")
    if types:
        p["question_types"] = types
    t = re.search(r"\b(?:on|about|covering|regarding)\s+([A-Za-z0-9][^.?!,\n]{2,80})", message)
    if t:
        topic = re.split(r"\s+(?:with|using|at|in|and give|and make|\d+\s+(?:\w+\s+)?(?:questions?|mcqs?))\b", t.group(1),
                         maxsplit=1, flags=re.I)[0].strip(" .")
        if topic:
            p["topic"] = topic
    return p


def detect_intent(message: str) -> tuple:
    """Deterministic routing. Returns (intent, params)."""
    if _DIAG.search(message):
        return "diagnostic", {}
    if _QUIZ.search(message):
        return "quiz", _quiz_params(message)
    if _PROGRESS.search(message):
        return "progress", {}
    if _RECO.search(message):
        return "recommend", {}
    return "tutor", {}


class Trace:
    def __init__(self):
        self.steps: list = []

    @contextmanager
    def step(self, agent: str, action: str):
        rec = {"agent": agent, "action": action, "status": "ok", "detail": None}
        t0 = time.perf_counter()
        try:
            yield rec
        except Exception:
            rec["status"] = "error"
            raise
        finally:
            rec["duration_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            self.steps.append(rec)


def _ready_docs(db: Session, user_id: str, document_ids: Optional[list]) -> int:
    q = select(func.count()).select_from(Document).where(Document.user_id == user_id, Document.status == "ready")
    if document_ids:
        q = q.where(Document.id.in_(document_ids))
    return db.scalar(q) or 0


def _validate_documents(db: Session, user_id: str, ids: Optional[list]) -> None:
    if not ids:
        return
    found = set(db.scalars(select(Document.id).where(Document.user_id == user_id, Document.id.in_(ids))).all())
    missing = [i for i in ids if i not in found]
    if missing:
        raise NotFoundError(f"Document(s) not found: {', '.join(missing[:5])}")


def get_history(db: Session, user_id: str, session_id: str, limit: int) -> list:
    rows = db.scalars(select(ConversationMessage).where(ConversationMessage.user_id == user_id,
                                                        ConversationMessage.session_id == session_id)
                      .order_by(ConversationMessage.id.desc()).limit(limit * 2)).all()
    return [{"role": r.role, "content": r.content} for r in reversed(rows)]


def full_progress(db: Session, user_id: str) -> ProgressOut:
    s = mastery_service.progress_summary(db, user_id)
    return ProgressOut(**s, recommendations=RecommendationsOut(**recommendation_agent.recommend(db, user_id)))


class Orchestrator:
    # ---------- tutoring pipeline: knowledge -> learner -> tutor -> learner(update) -> recommendation ----------
    def tutor_chat(self, db: Session, user_id: str, req: TutorChatRequest, trace: Optional[Trace] = None) -> TutorResponse:
        trace = trace or Trace()
        llm.require_configured()
        _validate_documents(db, user_id, req.document_ids)
        k = req.top_k or settings.top_k
        info = RetrievalInfo(query=req.question, top_k=k, returned=0, threshold=settings.min_relevance_score)
        if _ready_docs(db, user_id, req.document_ids) == 0:
            msg = "No indexed study material is available yet. Upload documents and wait until their status is 'ready'."
            return TutorResponse(answer=msg, evidence_status="insufficient", retrieval=info, mode=req.mode,
                                 language=req.language, session_id=req.session_id,
                                 suggestions=["Upload a PDF, PPTX, TXT/MD file or lecture video."])
        history = get_history(db, user_id, req.session_id, settings.history_turns)
        with trace.step("knowledge", "retrieve") as s:
            pack = knowledge_agent.gather(db, user_id, req.question, history, req.document_ids, req.top_k)
            s["detail"] = f"{len(pack.chunks)} chunk(s) above threshold {pack.threshold}"
        with trace.step("learner", "context") as s:
            ctx = learner_agent.context_for(db, user_id, pack.topics)
            s["detail"] = "new student" if ctx["is_new"] else "history found"
        with trace.step("tutor", "answer") as s:
            if not pack.sufficient and not req.allow_outside_knowledge:
                result = tutor_agent.insufficient(req.language)
                s["detail"] = "no evidence; LLM not called"
            else:
                result = tutor_agent.answer(req.question, pack, ctx, req.mode, req.language, history,
                                            req.allow_outside_knowledge)
                s["detail"] = result.evidence_status
        db.add(ConversationMessage(user_id=user_id, session_id=req.session_id, role="user", content=req.question))
        db.add(ConversationMessage(user_id=user_id, session_id=req.session_id, role="assistant", content=result.answer,
                                   meta={"evidence_status": result.evidence_status,
                                         "citations": [c.chunk_id for c in result.citations]}))
        db.add(ActivityLog(user_id=user_id, kind="tutor_question",
                           detail={"question": req.question[:120], "evidence_status": result.evidence_status}))
        with trace.step("learner", "observe_tutoring"):
            if result.evidence_status in {"supported", "partial"} and result.citations:
                learner_agent.observe_tutoring(db, user_id, [c.topic for c in result.citations])
        suggestions = list(result.suggestions)
        with trace.step("recommendation", "followups"):
            rec = recommendation_agent.recommend(db, user_id, limit=3)
            if rec["revision_priorities"] and rec["revision_priorities"][0]["mastery"] < 0.7:
                suggestions.append(f"Consider revising '{rec['revision_priorities'][0]['topic']}' next.")
        db.commit()
        info.returned, info.top_score = len(pack.chunks), pack.top_score
        info.query = pack.query
        return TutorResponse(answer=result.answer, evidence_status=result.evidence_status, citations=result.citations,
                             outside_knowledge_note=result.outside_note, retrieval=info, mode=req.mode,
                             language=req.language, session_id=req.session_id, suggestions=suggestions[:4])

    # ---------- quizzes ----------
    def generate_quiz(self, db: Session, user_id: str, req: QuizGenerateRequest) -> QuizOut:
        _validate_documents(db, user_id, req.document_ids)
        quiz = quiz_agent.generate(db, user_id, req, mastery_service.mastery_map(db, user_id))
        db.add(ActivityLog(user_id=user_id, kind="quiz_generated", detail={"quiz_id": quiz.id, "kind": quiz.kind}))
        db.commit()
        return quiz_to_out(quiz)

    def submit_quiz(self, db: Session, user_id: str, quiz_id: str, req: QuizSubmitRequest) -> QuizResult:
        quiz = db.get(Quiz, quiz_id)
        if quiz is None or quiz.user_id != user_id:
            raise NotFoundError("Quiz not found.")
        valid_ids = {q.id for q in quiz.questions}
        answers = {}
        for a in req.answers:
            if a.question_id not in valid_ids:
                raise UnprocessableError(f"Question {a.question_id} does not belong to this quiz.")
            answers[a.question_id] = a.answer
        results = quiz_agent.grade(db, quiz, answers)
        updates = learner_agent.observe_quiz(db, user_id, results)
        report = assessment_service.build_report(results)
        existing = set(db.scalars(select(Document.id).where(Document.user_id == user_id)).all())
        feedback = []
        for r in results:
            q = r["question"]
            feedback.append({
                "question_id": q.id, "position": q.position, "type": q.qtype, "question": q.text, "topic": q.topic,
                "user_answer": r["user_answer"], "answered": r["answered"], "is_correct": r["is_correct"],
                "score": r["score"], "correct_answer": assessment_service.correct_answer_display(q),
                "explanation": q.explanation, "grading_method": r["method"], "feedback": r["feedback"],
                "citations": [snapshot_to_citation(q.source, q.source.get("document_id") in existing, True)]})
        score = round(sum(r["score"] for r in results), 2)
        total = len(results)
        attempt = QuizAttempt(id=new_id(), quiz_id=quiz.id, user_id=user_id, score=score, max_score=float(total),
                              percent=round(100.0 * score / total, 1) if total else 0.0)
        db.add(attempt)
        db.flush()
        for r in results:
            db.add(QuestionResponse(attempt_id=attempt.id, question_id=r["question"].id, user_answer=r["user_answer"],
                                    answered=r["answered"], score=r["score"], is_correct=r["is_correct"],
                                    grading_method=r["method"]))
        profile = learner_agent.get_profile(db, user_id)
        if quiz.kind == "diagnostic":
            profile.diagnostic_completed = True
        learner_agent.refresh_level(db, user_id, force=quiz.kind == "diagnostic")
        db.add(ActivityLog(user_id=user_id, kind="quiz_submitted",
                           detail={"quiz_id": quiz.id, "percent": attempt.percent}))
        result = QuizResult(attempt_id=attempt.id, quiz_id=quiz.id, score=score, max_score=float(total),
                            percent=attempt.percent, answered=sum(1 for r in results if r["answered"]), total=total,
                            feedback=feedback, report=report, mastery_updates=updates)
        attempt.report = result.model_dump(mode="json")
        db.commit()
        return result

    # ---------- generic entry point ----------
    def handle(self, db: Session, user_id: str, req: OrchestrateRequest) -> OrchestrateResponse:
        trace = Trace()
        with trace.step("orchestrator", "detect_intent") as s:
            detected, params = detect_intent(req.message)
            intent = req.intent or detected
            s["detail"] = f"{intent} ({'override' if req.intent else 'rules'})"
        if intent in {"tutor", "quiz", "diagnostic"}:
            llm.require_configured()
            _validate_documents(db, user_id, req.document_ids)
            if _ready_docs(db, user_id, req.document_ids) == 0:
                return OrchestrateResponse(intent=intent, status="needs_documents", trace=self._t(trace),
                                           message="No indexed study material yet. Upload documents and wait for status 'ready'.")
        if intent == "tutor":
            tr = self.tutor_chat(db, user_id, TutorChatRequest(
                question=req.message, session_id=req.session_id, mode=req.mode, language=req.language,
                document_ids=req.document_ids, allow_outside_knowledge=req.allow_outside_knowledge), trace)
            return OrchestrateResponse(intent=intent, tutor=tr, trace=self._t(trace), message=tr.answer,
                                       status="ok" if tr.evidence_status != "insufficient" else "insufficient_evidence")
        if intent in {"quiz", "diagnostic"}:
            topic = params.get("topic")
            qreq = QuizGenerateRequest(
                mode="topic" if topic else ("document" if req.document_ids else "mixed"),
                topics=[topic] if topic else [], document_ids=req.document_ids or [],
                num_questions=params.get("num_questions", 8 if intent == "diagnostic" else 5),
                difficulty=params.get("difficulty", "adaptive"), question_types=params.get("question_types", ["mcq"]),
                kind="diagnostic" if intent == "diagnostic" else "practice")
            with trace.step("quiz", "generate") as s:
                quiz = self.generate_quiz(db, user_id, qreq)
                s["detail"] = f"{len(quiz.questions)} verified question(s), difficulty {quiz.difficulty}"
            return OrchestrateResponse(intent=intent, status="ok", quiz=quiz, trace=self._t(trace),
                                       message=f"Generated '{quiz.title}'. Submit answers to /api/quizzes/{quiz.id}/submit.")
        if intent == "progress":
            with trace.step("learner", "progress"):
                prog = full_progress(db, user_id)
            return OrchestrateResponse(intent=intent, status="ok", progress=prog, trace=self._t(trace),
                                       message="Here is your progress." if prog.topics_tracked else
                                       "No learning history yet. Take a diagnostic quiz to begin.")
        with trace.step("recommendation", "recommend"):
            rec = RecommendationsOut(**recommendation_agent.recommend(db, user_id))
        return OrchestrateResponse(intent="recommend", status="ok", recommendations=rec, trace=self._t(trace),
                                   message=rec.suggestions[0] if rec.suggestions else "Keep practicing.")

    @staticmethod
    def _t(trace: Trace) -> list:
        return [TraceStep(**s) for s in trace.steps]


orchestrator = Orchestrator()