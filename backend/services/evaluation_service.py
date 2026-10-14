"""Lightweight, honest RAG evaluation. Run: python -m backend.services.evaluation_service --dataset FILE --user-id ID

Metrics are computed only when the needed data exists; otherwise they are reported as null.
RAGAS is NOT bundled (it needs LangChain wrappers and extra model setup); equivalents here are labelled as proxies."""
import argparse
import json
import math
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import llm
from backend.schemas import EvaluationDataset, QuizGenerateRequest
from backend.models import Chunk, Document, QuizQuestion
from backend.services import assessment_service as A
from backend.services import embedding_service

EXAMPLE_DATASET = {
    "name": "biology-demo",
    "options": {"generate_answers": False, "top_k": 5},
    "retrieval_cases": [{"id": "r1", "question": "How do plants convert light energy?",
                         "expected_sources": [{"document_name": "bio.txt"}],
                         "reference_answer": "Plants convert light energy into chemical energy stored in glucose."}],
    "unsupported_cases": [{"id": "u1", "question": "Who won the football world cup in 1998?"}],
    "quiz_cases": [{"id": "q1", "document_names": ["bio.txt"], "num_questions": 3}]}


def _mean(vals: list) -> Optional[float]:
    v = [x for x in vals if x is not None]
    return round(sum(v) / len(v), 4) if v else None


def _match(chunk, exp) -> bool:
    if chunk.document_name.lower() != exp.document_name.lower():
        return False
    if exp.page is not None and chunk.page != exp.page:
        return False
    if exp.slide is not None and chunk.slide != exp.slide:
        return False
    if exp.start_sec is not None:
        if chunk.start_sec is None:
            return False
        end = exp.end_sec if exp.end_sec is not None else exp.start_sec
        c_end = chunk.end_sec if chunk.end_sec is not None else chunk.start_sec
        if chunk.start_sec > end or c_end < exp.start_sec:
            return False
    return True


def lexical_faithfulness(answer: str, contexts: list) -> Optional[float]:
    """Proxy: share of answer sentences whose content words are >=60% present in the retrieved contexts."""
    ctx = set()
    for c in contexts:
        ctx |= A.content_tokens(c)
    sents = [s for s in re.split(r"(?<=[.!?])\s+", re.sub(r"\[S\d+\]", "", answer)) if len(A.content_tokens(s)) >= 3]
    if not sents:
        return None
    ok = sum(1 for s in sents if len(A.content_tokens(s) & ctx) / len(A.content_tokens(s)) >= 0.6)
    return round(ok / len(sents), 4)


def token_f1(a: str, b: str) -> Optional[float]:
    ta, tb = A.content_tokens(a), A.content_tokens(b)
    if not ta or not tb:
        return None
    inter = len(ta & tb)
    if inter == 0:
        return 0.0
    p, r = inter / len(ta), inter / len(tb)
    return round(2 * p * r / (p + r), 4)


def _cos(a: list, b: list) -> float:
    d = sum(x * y for x, y in zip(a, b))
    n = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return d / n if n else 0.0


def repeated_question_rate(db: Session, user_id: str, cap: int = 500) -> Optional[float]:
    from backend.models import Quiz
    norms = [q.norm_text for q in db.scalars(select(QuizQuestion).join(Quiz, Quiz.id == QuizQuestion.quiz_id)
                                             .where(Quiz.user_id == user_id).order_by(Quiz.created_at, QuizQuestion.position)
                                             .limit(cap)).all()]
    if not norms:
        return None
    rep = sum(1 for i, n in enumerate(norms) if A.is_repeat(n, norms[:i]))
    return round(rep / len(norms), 4)


def run_evaluation(db: Session, user_id: str, ds: EvaluationDataset) -> dict:
    from backend.agents.knowledge_agent import KnowledgeAgent
    from backend.agents.quiz_agent import QuizAgent
    from backend.agents.tutor_agent import TutorAgent
    from backend.services import mastery_service
    knowledge, tutor, quiz_agent = KnowledgeAgent(), TutorAgent(), QuizAgent()
    llm.require_configured()
    gen = ds.options.generate_answers
    notes = ["Faithfulness/answer-relevancy are lightweight proxies, not RAGAS scores."]
    if not gen:
        notes.append("generate_answers=false: faithfulness and answer relevancy were not computed.")
    report: dict = {"dataset": ds.name, "user_id": user_id, "generated_at": datetime.now(timezone.utc).isoformat(), "notes": notes}

    cases = []
    for c in ds.retrieval_cases:
        pack = knowledge.gather(db, user_id, c.question, [], None, ds.options.top_k)
        row: dict = {"id": c.id, "returned": len(pack.chunks), "top_score": pack.top_score}
        exp = c.expected_sources
        if exp:
            flags = [any(_match(ch, e) for e in exp) for ch in pack.chunks]
            first = next((i for i, f in enumerate(flags) if f), None)
            row.update(hit=first is not None, reciprocal_rank=round(1 / (first + 1), 4) if first is not None else 0.0,
                       context_precision=round(sum(flags) / len(flags), 4) if flags else 0.0,
                       context_recall=round(sum(1 for e in exp if any(_match(ch, e) for ch in pack.chunks)) / len(exp), 4))
        if gen and pack.chunks:
            res = tutor.answer(c.question, pack, {"summary": "Evaluation run; no learner context."}, "simple", "en", [], False)
            row["evidence_status"] = res.evidence_status
            if res.evidence_status != "insufficient":
                row["faithfulness_proxy"] = lexical_faithfulness(res.answer, [ch.text for ch in pack.chunks])
                qa = embedding_service.embed_texts([c.question, res.answer])
                row["answer_relevancy_proxy"] = round(_cos(qa[0], qa[1]), 4)
                if c.reference_answer:
                    row["answer_token_f1_vs_reference"] = token_f1(res.answer, c.reference_answer)
        cases.append(row)
    report["retrieval"] = {
        "cases": cases, "hit_rate": _mean([float(r["hit"]) for r in cases if "hit" in r]),
        "mrr": _mean([r.get("reciprocal_rank") for r in cases]), "context_precision": _mean([r.get("context_precision") for r in cases]),
        "context_recall": _mean([r.get("context_recall") for r in cases]),
        "faithfulness_proxy": _mean([r.get("faithfulness_proxy") for r in cases]),
        "answer_relevancy_proxy": _mean([r.get("answer_relevancy_proxy") for r in cases]),
        "answer_token_f1_vs_reference": _mean([r.get("answer_token_f1_vs_reference") for r in cases])}

    un = []
    for c in ds.unsupported_cases:
        pack = knowledge.gather(db, user_id, c.question, [], None, ds.options.top_k)
        handled, mode = not pack.sufficient, "retrieval_only"
        if pack.sufficient and gen:
            res = tutor.answer(c.question, pack, {"summary": "Evaluation run."}, "simple", "en", [], False)
            handled, mode = res.evidence_status == "insufficient", "end_to_end"
        un.append({"id": c.id, "handled_correctly": handled, "mode": mode, "chunks_above_threshold": len(pack.chunks)})
    report["unsupported_queries"] = {"cases": un, "correct_refusal_rate": _mean([float(u["handled_correctly"]) for u in un])}

    qrows = []
    for c in ds.quiz_cases:
        ids = db.scalars(select(Document.id).where(Document.user_id == user_id, Document.status == "ready",
                                                   Document.filename.in_(c.document_names))).all()
        if not ids:
            qrows.append({"id": c.id, "error": "no matching ready documents"})
            continue
        try:
            quiz = quiz_agent.generate(db, user_id, QuizGenerateRequest(mode="document", document_ids=list(ids),
                                       num_questions=c.num_questions), mastery_service.mastery_map(db, user_id))
            db.commit()
        except Exception as exc:  # report, do not crash the run
            db.rollback()
            qrows.append({"id": c.id, "error": getattr(exc, "message", "quiz generation failed")})
            continue
        ok = 0
        for q in quiz.questions:
            ch = db.get(Chunk, q.source.get("chunk_id", ""))
            ok += int(bool(ch and A.quote_in_source(q.source.get("quote", ""), ch.text)))
        n = len(quiz.questions)
        qrows.append({"id": c.id, "questions": n, "verified_rate": round(sum(q.verified for q in quiz.questions) / n, 4),
                      "source_quote_correct_rate": round(ok / n, 4)})
    report["quiz_source_correctness"] = {"cases": qrows, "source_quote_correct_rate": _mean([r.get("source_quote_correct_rate") for r in qrows]),
                                         "verified_rate": _mean([r.get("verified_rate") for r in qrows])}
    report["repeated_question_rate"] = repeated_question_rate(db, user_id)
    return report


def main() -> None:
    from backend.database import SessionLocal, init_db
    ap = argparse.ArgumentParser(description="Run EduMind RAG evaluation (uses OpenAI embeddings; may use chat credits).")
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--user-id", default="demo-user")
    args = ap.parse_args()
    with open(args.dataset, encoding="utf-8") as fh:
        ds = EvaluationDataset.model_validate(json.load(fh))
    init_db()
    db = SessionLocal()
    try:
        print(json.dumps(run_evaluation(db, args.user_id, ds), indent=2, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()