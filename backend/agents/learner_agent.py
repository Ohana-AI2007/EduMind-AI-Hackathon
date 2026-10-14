"""Learner-modeling agent: learner context for personalization and mastery updates."""
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.models import (ActivityLog, LearnerProfile, QuestionResponse, QuizAttempt, QuizQuestion, TopicMastery)
from backend.services import assessment_service, mastery_service


class LearnerAgent:
    def get_profile(self, db: Session, user_id: str) -> LearnerProfile:
        p = db.get(LearnerProfile, user_id)
        if p is None:
            p = LearnerProfile(user_id=user_id)
            db.add(p)
            db.flush()
        return p

    def update_profile(self, db: Session, user_id: str, level, goal, language) -> LearnerProfile:
        p = self.get_profile(db, user_id)
        if level:
            p.level = level
        if goal is not None:
            p.goal = goal.strip() or None
        if language:
            p.preferred_language = language
        db.commit()
        return p

    def context_for(self, db: Session, user_id: str, topics: list) -> dict:
        any_history = db.scalar(select(func.count()).select_from(TopicMastery).where(TopicMastery.user_id == user_id)) or 0
        tm = mastery_service.mastery_map(db, user_id, topics) if topics else {}
        if not any_history:
            summary = "New student with no learning history; assume beginner level and build up from first principles."
        elif not tm:
            summary = "Returning student with no recorded mastery on these topics yet; start at an intermediate-beginner level."
        else:
            summary = "Estimated mastery on related topics: " + "; ".join(
                f"{t}: {p:.0%} ({mastery_service.status_for(p)})" for t, p in tm.items())
        return {"is_new": not any_history, "topic_mastery": tm, "summary": summary}

    def observe_quiz(self, db: Session, user_id: str, results: list) -> list:
        updates: dict = {}
        for r in results:
            if not r["answered"]:
                continue  # skipped questions give no evidence
            q = r["question"]
            before, after = mastery_service.record_observation(db, user_id, q.topic, r["is_correct"], q.qtype)
            u = updates.setdefault(q.topic, {"topic": q.topic, "before": before, "after": after})
            u["after"] = after
        return [{"topic": u["topic"], "before": round(u["before"], 3), "after": round(u["after"], 3)} for u in updates.values()]

    def observe_tutoring(self, db: Session, user_id: str, topics: list) -> None:
        mastery_service.record_tutor_exposure(db, user_id, topics)

    def refresh_level(self, db: Session, user_id: str, force: bool = False) -> None:
        p = self.get_profile(db, user_id)
        vals = list(mastery_service.mastery_map(db, user_id).values())
        if vals and (force or p.level == "unknown"):
            avg = sum(vals) / len(vals)
            p.level = "beginner" if avg < 0.4 else "intermediate" if avg < 0.7 else "advanced"

    def profile_view(self, db: Session, user_id: str) -> dict:
        p = self.get_profile(db, user_id)
        db.commit()
        rows = db.scalars(select(TopicMastery).where(TopicMastery.user_id == user_id)).all()
        resp = db.execute(
            select(QuestionResponse, QuizQuestion).join(QuizQuestion, QuizQuestion.id == QuestionResponse.question_id)
            .join(QuizAttempt, QuizAttempt.id == QuestionResponse.attempt_id)
            .where(QuizAttempt.user_id == user_id, QuestionResponse.answered.is_(True))
            .order_by(QuestionResponse.id.desc()).limit(300)).all()
        by_type: dict = {}
        for r, q in resp:
            n = by_type.setdefault(q.qtype, [0, 0])
            n[0] += 1
            n[1] += int(r.is_correct)
        mistakes = [{"question_id": q.id, "topic": q.topic, "question": q.text, "your_answer": r.user_answer,
                     "correct_answer": assessment_service.correct_answer_display(q)}
                    for r, q in resp if not r.is_correct][:10]
        quizzes = db.scalar(select(func.count()).select_from(QuizAttempt).where(QuizAttempt.user_id == user_id)) or 0
        last = db.scalar(select(func.max(ActivityLog.created_at)).where(ActivityLog.user_id == user_id))
        is_new = not rows and not quizzes
        return {
            "user_id": user_id, "level": p.level, "goal": p.goal, "preferred_language": p.preferred_language,
            "diagnostic_completed": p.diagnostic_completed, "is_new_student": is_new, "topics_tracked": len(rows),
            "overall_mastery": round(sum(m.p_known for m in rows) / len(rows), 3) if rows else None,
            "quizzes_taken": quizzes, "accuracy_by_question_type": {k: round(v[1] / v[0], 3) for k, v in by_type.items()},
            "recent_mistakes": mistakes, "last_active": last,
            "note": ("New student: upload material, then take a diagnostic quiz (POST /api/quizzes/diagnostic)."
                     if is_new else "Mastery uses a BKT-style estimate with fixed parameters; see README.")}