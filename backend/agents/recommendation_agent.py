"""Recommendation agent: revision priorities, next topics and practice questions from stored data."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.models import (Chunk, Document, Quiz, QuestionResponse, QuizAttempt, QuizQuestion, TopicMastery, utcnow)


class RecommendationAgent:
    def recommend(self, db: Session, user_id: str, limit: int = 5) -> dict:
        now = utcnow()
        rows = db.scalars(select(TopicMastery).where(TopicMastery.user_id == user_id)).all()
        pri = []
        for m in rows:
            last = m.last_practiced or m.last_updated
            days = (now - last).days if last else None
            stale = min((days or 0) / 14.0, 1.0)
            reasons = []
            if m.p_known < 0.4:
                reasons.append(f"low mastery ({m.p_known:.0%})")
            elif m.p_known < 0.7:
                reasons.append(f"still developing ({m.p_known:.0%})")
            if days is not None and days >= 7:
                reasons.append(f"not practiced for {days} days")
            pri.append({"topic": m.topic, "mastery": round(m.p_known, 3),
                        "priority": round(0.7 * (1 - m.p_known) + 0.3 * stale, 3), "days_since_practice": days,
                        "reason": "; ".join(reasons) or "maintain with light review"})
        pri.sort(key=lambda p: -p["priority"])
        pri = pri[:limit]
        tracked = {m.topic for m in rows}
        doc_topics = db.scalars(
            select(Chunk.topic).join(Document, Document.id == Chunk.document_id)
            .where(Document.user_id == user_id, Document.status == "ready")
            .group_by(Chunk.topic).order_by(func.min(Chunk.id))).all()
        untouched = [t for t in doc_topics if t and t not in tracked][:limit]
        weak = [p["topic"] for p in pri if p["mastery"] < 0.7][:3]
        next_topics = list(dict.fromkeys(weak + untouched))[:limit]
        practice = []
        if weak:
            solved = select(QuestionResponse.question_id).join(QuizAttempt, QuizAttempt.id == QuestionResponse.attempt_id) \
                .where(QuizAttempt.user_id == user_id, QuestionResponse.is_correct.is_(True))
            qs = db.scalars(
                select(QuizQuestion).join(Quiz, Quiz.id == QuizQuestion.quiz_id)
                .where(Quiz.user_id == user_id, QuizQuestion.verified.is_(True), QuizQuestion.topic.in_(weak),
                       QuizQuestion.id.not_in(solved)).order_by(Quiz.created_at.desc()).limit(5)).all()
            practice = [{"question_id": q.id, "quiz_id": q.quiz_id, "topic": q.topic, "type": q.qtype, "text": q.text,
                         "options": q.options} for q in qs]
        suggestions = []
        if not db.scalar(select(func.count()).select_from(Document).where(Document.user_id == user_id, Document.status == "ready")):
            suggestions.append("Upload study material (POST /api/documents/upload) to get started.")
        if not rows:
            suggestions.append("Take a diagnostic quiz (POST /api/quizzes/diagnostic) to initialise your learner model.")
        else:
            if pri and pri[0]["mastery"] < 0.7:
                suggestions.append(f"Revise '{pri[0]['topic']}' first: {pri[0]['reason']}.")
            if untouched:
                suggestions.append(f"You haven't practiced '{untouched[0]}' yet; try a short quiz on it.")
        return {"has_history": bool(rows), "next_topics": next_topics, "revision_priorities": pri,
                "practice_questions": practice, "suggestions": suggestions}