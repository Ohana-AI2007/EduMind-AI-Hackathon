"""Question validation, grading, report building, source selection and history."""
import hashlib
import random
import re
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.models import Chunk, Document, Quiz, QuizAttempt, QuizQuestion
from backend.services import retrieval_service

MIN_CHUNK_CHARS = 100
STOP = {"the", "is", "a", "an", "of", "in", "to", "and", "who", "what", "how", "why", "did", "does", "do", "are",
        "was", "were", "which", "for", "on", "it", "this", "that", "with", "as", "by", "at", "be", "or", "from"}
_DIFF_HINT = {"beginner": "recall of key definitions and facts",
              "intermediate": "understanding and applying relationships between ideas",
              "advanced": "multi-step reasoning, analysis and subtle distractors"}


def normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", (s or "").lower())).strip()


def content_tokens(s: str) -> set:
    return {t for t in normalize_text(s).split() if t not in STOP and len(t) > 1}


def question_hash(text: str) -> str:
    return hashlib.sha1(normalize_text(text).encode()).hexdigest()


def is_repeat(text: str, recent_norms: list, threshold: float = 0.8) -> bool:
    n = normalize_text(text)
    toks = set(n.split())
    for r in recent_norms:
        if r == n:
            return True
        rt = set(r.split())
        if toks and rt and len(toks & rt) / len(toks | rt) >= threshold:
            return True
    return False


def quote_in_source(quote: str, source: str) -> bool:
    q = normalize_text(quote)
    return len(q) >= 15 and q in normalize_text(source)


def parse_number(s: str) -> Optional[float]:
    s = (s or "").replace(",", "").strip()
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*[x×*]\s*10\s*\^?\s*(-?\d+)", s)
    if m:
        return float(m.group(1)) * 10 ** int(m.group(2))
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", s)
    if m and float(m.group(2)) != 0:
        return float(m.group(1)) / float(m.group(2))
    m = re.search(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", s)
    return float(m.group(0)) if m else None


def validate_question(raw, allowed_types: list, chunk_by_marker: dict) -> tuple:
    """Returns (validated_dict | None, rejection_reason)."""
    if not isinstance(raw, dict):
        return None, "not an object"
    qtype = str(raw.get("type", "")).strip().lower().replace(" ", "_").replace("-", "_")
    qtype = {"short": "short_answer", "shortanswer": "short_answer", "numeric": "numerical"}.get(qtype, qtype)
    if qtype not in allowed_types:
        return None, f"type '{qtype}' was not requested"
    text = str(raw.get("question", "")).strip()
    if not 10 <= len(text) <= 600:
        return None, "question text length invalid"
    chunk = chunk_by_marker.get(str(raw.get("source", "")).strip().strip("[]").upper())
    if chunk is None:
        return None, "unknown source excerpt"
    quote = str(raw.get("source_quote", "")).strip()
    if not quote_in_source(quote, chunk.text):
        return None, "source_quote not found verbatim in the cited excerpt"
    out = {"type": qtype, "text": text, "chunk": chunk, "quote": quote[:300], "options": None, "accepted": [],
           "tolerance": None, "explanation": str(raw.get("explanation", "")).strip()[:800]}
    ans = raw.get("answer")
    if qtype == "mcq":
        opts = raw.get("options")
        if not isinstance(opts, list) or len(opts) != 4:
            return None, "mcq needs exactly 4 options"
        cleaned = [re.sub(r"^\s*[A-Da-d][\).:\-]\s+", "", str(o)).strip() for o in opts]
        if any(not o for o in cleaned) or len({normalize_text(o) for o in cleaned}) != 4:
            return None, "mcq options empty or duplicated"
        letter = None
        m = re.match(r"^\s*\(?([A-Da-d])\)?\s*$", str(ans or ""))
        if m:
            letter = m.group(1).upper()
        else:
            for i, o in enumerate(cleaned):
                if normalize_text(o) == normalize_text(str(ans or "")):
                    letter = "ABCD"[i]
        if letter is None:
            return None, "mcq answer is not one of A-D"
        out.update(options=cleaned, answer=letter)
    elif qtype == "short_answer":
        a = str(ans or "").strip()
        if not a or len(a) > 300:
            return None, "short answer key missing or too long"
        acc = raw.get("accepted_answers") or []
        out.update(answer=a, accepted=[str(x).strip() for x in acc if str(x).strip()][:3] if isinstance(acc, list) else [])
    else:
        if parse_number(str(ans or "")) is None:
            return None, "numerical answer is not a number"
        try:
            tol = float(raw.get("tolerance_percent") or 1.0)
        except (TypeError, ValueError):
            tol = 1.0
        out.update(answer=str(ans).strip(), tolerance=min(max(tol, 0.01), 10.0))
    return out, ""


# ---------- grading ----------
def normalize_mcq_answer(user_answer: str, options: list) -> Optional[str]:
    m = re.match(r"^\s*\(?([A-Da-d])\)?[\).:]?\s*$", user_answer or "")
    if m:
        return m.group(1).upper()
    for i, o in enumerate(options or []):
        if normalize_text(o) == normalize_text(user_answer or ""):
            return "ABCD"[i]
    return None


def grade_mcq(user_answer: str, options: list, correct_letter: str) -> float:
    return 1.0 if normalize_mcq_answer(user_answer, options) == correct_letter else 0.0


def grade_numeric(user_answer: str, key: str, tolerance_percent: Optional[float]) -> float:
    a, b = parse_number(user_answer), parse_number(key)
    if a is None or b is None:
        return 0.0
    tol = (tolerance_percent or 1.0) / 100.0
    return 1.0 if abs(a - b) <= max(abs(b) * tol, 1e-6) else 0.0


_ARTICLES = {"the", "a", "an"}


def _strip_articles(s: str) -> str:
    return " ".join(w for w in normalize_text(s).split() if w not in _ARTICLES)


def exact_short_match(user_answer: str, key: str, accepted: list) -> bool:
    u = _strip_articles(user_answer)
    return bool(u) and any(u == _strip_articles(k) for k in [key, *(accepted or [])])

def lexical_short_answer_score(user_answer: str, key: str, accepted: list) -> float:
    if exact_short_match(user_answer, key, accepted):
        return 1.0
    ua, best = content_tokens(user_answer), 0.0
    for k in [key, *(accepted or [])]:
        kt = content_tokens(k)
        if kt:
            best = max(best, len(ua & kt) / len(kt))
    return 1.0 if best >= 0.8 else 0.5 if best >= 0.5 else 0.0


def correct_answer_display(q: QuizQuestion) -> str:
    if q.qtype == "mcq" and q.options:
        return f"{q.correct_answer}. {q.options['ABCD'.index(q.correct_answer)]}"
    return q.correct_answer


# ---------- report ----------
def build_report(items: list) -> dict:
    """items: dicts with question(QuizQuestion), answered, score, is_correct, user_answer."""
    topics: dict = {}
    skipped, miscon = 0, []
    for it in items:
        q = it["question"]
        if not it["answered"]:
            skipped += 1
            continue
        t = topics.setdefault(q.topic, {"asked": 0, "score": 0.0})
        t["asked"] += 1
        t["score"] += it["score"]
        if not it["is_correct"]:
            note = f"Source says: \"{q.source.get('quote', '')}\"" if q.source.get("quote") else "Review the cited source."
            if q.qtype == "mcq" and q.options:
                letter = normalize_mcq_answer(it["user_answer"] or "", q.options)
                if letter:
                    note = f"You chose \"{q.options['ABCD'.index(letter)]}\". " + note
            miscon.append({"topic": q.topic, "question": q.text, "your_answer": it["user_answer"] or "",
                           "correct_answer": correct_answer_display(q), "note": note})
    scored = [{"topic": k, "asked": v["asked"], "score": round(v["score"], 2), "accuracy": round(v["score"] / v["asked"], 3)}
              for k, v in topics.items()]
    weak = sorted([s for s in scored if s["accuracy"] < 0.6], key=lambda s: s["accuracy"])
    strong = sorted([s for s in scored if s["accuracy"] >= 0.8], key=lambda s: -s["accuracy"])
    revision = []
    for w in weak:
        labels = []
        for it in items:
            q = it["question"]
            if q.topic == w["topic"] and it["answered"] and not it["is_correct"]:
                lbl = retrieval_service.snapshot_to_citation(q.source).label
                if lbl and lbl not in labels:
                    labels.append(lbl)
        revision.append({"topic": w["topic"], "sources": labels})
    return {"weak_topics": weak, "strengths": strong, "misconceptions": miscon, "suggested_revision": revision, "skipped": skipped}


# ---------- selection / history ----------
def _weighted_sample(items: list, weights: list, k: int) -> list:
    keyed = sorted(((random.random() ** (1.0 / max(w, 1e-6)), it) for it, w in zip(items, weights)),
                   key=lambda x: x[0], reverse=True)
    return [it for _, it in keyed[:k]]


def resolve_difficulty(req, mastery: dict, topics: list) -> str:
    if req.difficulty != "adaptive":
        return req.difficulty
    if req.kind == "diagnostic":
        return "intermediate"
    vals = [mastery[t] for t in topics if t in mastery]
    if not vals:
        return "beginner"
    avg = sum(vals) / len(vals)
    return "beginner" if avg < 0.4 else "intermediate" if avg < 0.7 else "advanced"


def select_source_chunks(db: Session, user_id: str, req, n: int, mastery: dict, avoid: set) -> list:
    base = (select(Chunk, Document.filename).join(Document, Document.id == Chunk.document_id)
            .where(Document.user_id == user_id, Document.status == "ready", func.length(Chunk.text) >= MIN_CHUNK_CHARS))
    if req.document_ids:
        base = base.where(Chunk.document_id.in_(req.document_ids))
    pool: dict = {}
    if req.mode == "topic":
        for t in [t.strip() for t in req.topics if t.strip()]:
            for c in retrieval_service.retrieve(db, user_id, t, top_k=max(4, n), document_ids=req.document_ids or None):
                pool[c.chunk_id] = c
            for ch, name in db.execute(base.where(Chunk.topic.ilike(f"%{t}%")).limit(50)).all():
                pool.setdefault(ch.id, retrieval_service.to_retrieved(ch, name, None))
    else:
        for ch, name in db.execute(base.limit(2000)).all():
            pool[ch.id] = retrieval_service.to_retrieved(ch, name, None)
    cands = [c for c in pool.values() if len(c.text) >= MIN_CHUNK_CHARS]
    weights = [(1.2 - mastery.get(c.topic, 0.3)) * (0.3 if c.chunk_id in avoid else 1.0) for c in cands]
    return _weighted_sample(cands, weights, min(n, len(cands)))


def quiz_history(db: Session, user_id: str, limit: int = 20, offset: int = 0) -> list:
    rows = db.execute(select(QuizAttempt, Quiz).join(Quiz, Quiz.id == QuizAttempt.quiz_id)
                      .where(QuizAttempt.user_id == user_id).order_by(QuizAttempt.submitted_at.desc())
                      .limit(limit).offset(offset)).all()
    return [{"attempt_id": a.id, "quiz_id": q.id, "title": q.title, "kind": q.kind, "difficulty": q.difficulty,
             "score": a.score, "max_score": a.max_score, "percent": a.percent, "submitted_at": a.submitted_at}
            for a, q in rows]


def difficulty_hint(d: str) -> str:
    return _DIFF_HINT.get(d, "")