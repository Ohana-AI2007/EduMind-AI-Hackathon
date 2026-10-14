"""Learner mastery: BKT-style update with fixed, hand-set parameters (no parameter fitting).

Per topic we track P(known). After each observed answer:
  correct:   P' = P(1-s) / (P(1-s) + (1-P)g)
  incorrect: P' = P s / (P s + (1-P)(1-g))
  then learning transition: P_next = P' + (1-P') * learn
s = slip, g = guess (depends on question type), learn = P(T).
Tutoring gives no observation, only a tiny learning transition (exposure).
"""
from datetime import timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import ActivityLog, MasteryEvent, QuizAttempt, TopicMastery, utcnow
from backend.services import assessment_service

P_INIT, P_LEARN, P_SLIP, P_LEARN_TUTOR = 0.30, 0.15, 0.10, 0.02
GUESS = {"mcq": 0.25, "short_answer": 0.05, "numerical": 0.02}


def bkt_update(p_known: float, correct: bool, guess: float, slip: float = P_SLIP, learn: float = P_LEARN) -> float:
    p = min(max(p_known, 1e-6), 1 - 1e-6)
    if correct:
        post = p * (1 - slip) / (p * (1 - slip) + (1 - p) * guess)
    else:
        post = p * slip / (p * slip + (1 - p) * (1 - guess))
    return min(max(post + (1 - post) * learn, 0.01), 0.99)


def status_for(p: float) -> str:
    return "weak" if p < 0.4 else "developing" if p < 0.7 else "strong"


def _get_or_create(db: Session, user_id: str, topic: str) -> TopicMastery:
    topic = topic.strip()[:200] or "General"
    m = db.scalar(select(TopicMastery).where(TopicMastery.user_id == user_id, TopicMastery.topic == topic))
    if m is None:
        m = TopicMastery(user_id=user_id, topic=topic, p_known=P_INIT, attempts=0, correct=0, last_updated=utcnow())
        db.add(m)
        db.flush()
    return m


def record_observation(db: Session, user_id: str, topic: str, correct: bool, qtype: str) -> tuple:
    m = _get_or_create(db, user_id, topic)
    before = m.p_known
    m.p_known = bkt_update(before, correct, GUESS.get(qtype, 0.25))
    m.attempts += 1
    m.correct += int(correct)
    m.last_practiced = m.last_updated = utcnow()
    db.add(MasteryEvent(user_id=user_id, topic=m.topic, p_before=before, p_after=m.p_known, source="quiz", correct=correct))
    return before, m.p_known


def record_tutor_exposure(db: Session, user_id: str, topics: list) -> None:
    for t in list(dict.fromkeys(topics))[:3]:
        m = _get_or_create(db, user_id, t)
        before = m.p_known
        m.p_known = min(0.99, before + (1 - before) * P_LEARN_TUTOR)
        m.last_practiced = m.last_updated = utcnow()
        db.add(MasteryEvent(user_id=user_id, topic=m.topic, p_before=before, p_after=m.p_known, source="tutor", correct=None))


def mastery_map(db: Session, user_id: str, topics: Optional[list] = None) -> dict:
    q = select(TopicMastery).where(TopicMastery.user_id == user_id)
    if topics:
        q = q.where(TopicMastery.topic.in_(topics))
    return {m.topic: m.p_known for m in db.scalars(q).all()}


def progress_summary(db: Session, user_id: str) -> dict:
    rows = db.scalars(select(TopicMastery).where(TopicMastery.user_id == user_id)).all()
    topics = sorted(({
        "topic": m.topic, "mastery": round(m.p_known, 3), "status": status_for(m.p_known), "attempts": m.attempts,
        "correct": m.correct, "accuracy": round(m.correct / m.attempts, 3) if m.attempts else None,
        "last_practiced": m.last_practiced} for m in rows), key=lambda t: t["mastery"])
    history = assessment_service.quiz_history(db, user_id, limit=50, offset=0)
    attempts = db.scalars(select(QuizAttempt).where(QuizAttempt.user_id == user_id)).all()
    total_att = sum(m.attempts for m in rows)
    events = db.scalars(select(MasteryEvent).where(MasteryEvent.user_id == user_id).order_by(MasteryEvent.id)).all()
    cur, by_day = {}, {}
    for e in events:
        cur[e.topic] = e.p_after
        by_day[e.created_at.date().isoformat()] = round(sum(cur.values()) / len(cur), 3)
    acts = db.scalars(select(ActivityLog).where(ActivityLog.user_id == user_id).order_by(ActivityLog.id.desc()).limit(15)).all()
    return {
        "overall_mastery": round(sum(m.p_known for m in rows) / len(rows), 3) if rows else None,
        "topics_tracked": len(rows), "quizzes_taken": len(attempts),
        "average_score": round(sum(a.percent for a in attempts) / len(attempts), 1) if attempts else None,
        "accuracy": round(sum(m.correct for m in rows) / total_att, 3) if total_att else None,
        "topics": topics,
        "strong_topics": [t["topic"] for t in reversed(topics) if t["status"] == "strong"],
        "weak_topics": [t["topic"] for t in topics if t["status"] == "weak"],
        "recent_activity": [{"kind": a.kind, "detail": a.detail or {}, "created_at": a.created_at} for a in acts],
        "mastery_timeline": [{"date": d, "overall_mastery": v} for d, v in list(by_day.items())[-60:]],
        "quiz_scores": history,
    }