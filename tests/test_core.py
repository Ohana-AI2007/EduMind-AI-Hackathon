from types import SimpleNamespace

import pytest

from backend import llm
from backend.orchestrator import detect_intent
from backend.services import assessment_service as A
from backend.services import embedding_service, mastery_service
from backend.services.document_service import chunk_text, safe_filename
from backend.services.retrieval_service import format_timestamp, location_label

DOC = ("Photosynthesis is the process by which plants convert light energy into chemical energy stored in glucose. "
       "It takes place in the chloroplasts, which contain chlorophyll that absorbs sunlight.")


def hdr(user):
    return {"X-User-Id": user}


def upload(client, user, name="bio.txt", data=DOC.encode()):
    return client.post("/api/documents/upload", files={"file": (name, data, "text/plain")}, headers=hdr(user))


# ---------- health / credentials / validation ----------
def test_health_works_without_api_key(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ai_configured"] is False and body["database"] == "ok" and body["vector_store"] == "ok"


def test_ai_endpoints_return_clear_error_without_key(client):
    r = client.post("/api/tutor/chat", json={"question": "What is mitosis?"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "ai_not_configured"
    r = client.post("/api/quizzes/generate", json={"mode": "mixed"})
    assert r.status_code == 503
    assert client.get("/api/progress", headers=hdr("nokey")).status_code == 200  # non-AI endpoint still works
    assert client.post("/api/quizzes/nope/submit", json={"answers": [{"question_id": "x", "answer": "A"}]},
                       headers=hdr("nokey")).status_code == 404


def test_request_validation(client, ai_on):
    assert client.post("/api/tutor/chat", json={"question": ""}).status_code == 422
    assert client.post("/api/tutor/chat", json={"question": "hi", "session_id": "bad id!"}).status_code == 422
    assert client.post("/api/quizzes/generate", json={"mode": "topic", "topics": []}).status_code == 422
    assert client.post("/api/quizzes/generate", json={"num_questions": 99}).status_code == 422
    assert client.get("/api/documents", headers=hdr("bad id!")).status_code == 400


# ---------- documents, metadata, citations ----------
def test_safe_filename_blocks_traversal():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("..\\..\\evil.pdf") == "evil.pdf"
    assert "/" not in safe_filename("a/b/c.txt")


def test_chunking_respects_size_and_overlap():
    text = ("Sentence number one is here. " * 100).strip()
    chunks = chunk_text(text, 300, 50)
    assert len(chunks) > 1 and all(len(c) <= 300 for c in chunks)
    assert chunk_text("short", 300, 50) == ["short"]


def test_location_label_and_timestamps():
    assert format_timestamp(125) == "2:05" and format_timestamp(3725) == "1:02:05"
    assert location_label("a.pdf", 3, None, None, None, "text") == "a.pdf, p. 3"
    assert location_label("v.mp4", None, None, 65, 130, "transcript") == "v.mp4, 1:05-2:10"
    assert "slide 4" in location_label("d.pptx", None, 4, None, None, "slide")


def test_chroma_metadata_is_scalar():
    ch = SimpleNamespace(id="d-00001", document_id="d", user_id="u", content_type="transcript", topic="T",
                         page=None, slide=None, start_sec=12.5, end_sec=None)
    meta = embedding_service.build_metadata(ch, "lecture.mp4")
    assert all(isinstance(v, (str, int, float, bool)) for v in meta.values())
    assert meta["page"] == -1 and meta["start_sec"] == 12.5


def test_upload_citation_lookup_and_delete(client, ai_on):
    r = upload(client, "u-docs")
    assert r.status_code == 202
    doc = r.json()["document"]
    got = client.get(f"/api/documents/{doc['id']}", headers=hdr("u-docs")).json()
    assert got["status"] == "ready" and got["chunk_count"] >= 1
    chunks = client.get(f"/api/documents/{doc['id']}/chunks", headers=hdr("u-docs")).json()
    detail = client.get(f"/api/documents/chunks/{chunks[0]['chunk_id']}", headers=hdr("u-docs")).json()
    assert "Photosynthesis" in detail["text"] and detail["citation"]["document_name"] == "bio.txt"
    assert client.get(f"/api/documents/{doc['id']}", headers=hdr("someone-else")).status_code == 404
    assert embedding_service.count_for_document(doc["id"]) >= 1
    assert client.delete(f"/api/documents/{doc['id']}", headers=hdr("u-docs")).status_code == 204
    assert embedding_service.count_for_document(doc["id"]) == 0
    assert client.get(f"/api/documents/{doc['id']}", headers=hdr("u-docs")).status_code == 404


def test_upload_rejects_bad_types_and_content(client):
    assert upload(client, "u-bad", "evil.exe", b"MZ").status_code == 400
    assert upload(client, "u-bad", "fake.pdf", b"not a pdf").status_code == 400
    assert upload(client, "u-bad", "empty.txt", b"").status_code == 400


def test_upload_without_key_is_extracted_but_awaits_index(client):
    doc = upload(client, "u-nokey").json()["document"]
    got = client.get(f"/api/documents/{doc['id']}", headers=hdr("u-nokey")).json()
    assert got["status"] == "awaiting_index" and got["chunk_count"] >= 1 and "OPENAI_API_KEY" in got["error"]


# ---------- tutor: grounded answers and unsupported questions ----------
def test_tutor_supported_answer_has_real_citations(client, ai_on):
    user = "u-tutor"
    upload(client, user)

    def fake_chat(system, user_msg, history=None):
        return {"answer": "Plants convert light energy into chemical energy [S1]. See also [S9].",
                "evidence_status": "supported", "used_sources": ["S1", "S9"], "follow_up_suggestions": ["Ask about chlorophyll"]}

    ai_on.setattr(llm, "chat_json", fake_chat)
    r = client.post("/api/tutor/chat", json={"question": "How do plants convert light energy into chemical energy?",
                                             "session_id": "s1"}, headers=hdr(user))
    assert r.status_code == 200
    body = r.json()
    assert body["evidence_status"] == "supported"
    assert [c["document_name"] for c in body["citations"]] == ["bio.txt"]
    assert "[S9]" not in body["answer"]  # fabricated marker removed
    hist = client.get("/api/tutor/history?session_id=s1", headers=hdr(user)).json()
    assert [m["role"] for m in hist] == ["user", "assistant"]


def test_tutor_unsupported_question_does_not_call_llm(client, ai_on):
    user = "u-unsup"
    upload(client, user)
    r = client.post("/api/tutor/chat", json={"question": "Explain gluon confinement in quantum chromodynamics"},
                    headers=hdr(user))
    assert r.status_code == 200
    body = r.json()
    assert body["evidence_status"] == "insufficient" and body["citations"] == []
    assert "won't guess" in body["answer"]


def test_tutor_without_documents_is_explicit(client, ai_on):
    r = client.post("/api/tutor/chat", json={"question": "What is osmosis?"}, headers=hdr("u-empty"))
    assert r.status_code == 200 and r.json()["evidence_status"] == "insufficient"


# ---------- quizzes: full workflow ----------
def test_quiz_generate_submit_progress_and_repeat_filter(client, ai_on):
    user = "u-quiz"
    upload(client, user)

    def fake_chat(system, user_msg, history=None):
        if "assessment author" in system:
            return {"questions": [{
                "type": "mcq", "question": "Into what kind of energy do plants convert light energy?",
                "options": ["Heat", "Chemical energy", "Sound", "Pressure"], "answer": "B",
                "explanation": "The excerpt says plants convert light into chemical energy.",
                "source": "S1", "source_quote": "plants convert light energy into chemical energy"}]}
        if "answer-key verifier" in system:
            return {"results": [{"id": "Q1", "supported": True, "reason": "ok"}]}
        raise AssertionError("unexpected prompt")

    ai_on.setattr(llm, "chat_json", fake_chat)
    r = client.post("/api/quizzes/generate", json={"mode": "mixed", "num_questions": 1, "difficulty": "beginner",
                                                   "question_types": ["mcq"]}, headers=hdr(user))
    assert r.status_code == 201
    quiz = r.json()
    q = quiz["questions"][0]
    assert q["verified"] and q["sources"][0]["document_name"] == "bio.txt"
    assert "correct_answer" not in q and "explanation" not in q  # answer keys are not leaked

    res = client.post(f"/api/quizzes/{quiz['id']}/submit", json={"answers": [{"question_id": q["id"], "answer": "B"}]},
                      headers=hdr(user))
    assert res.status_code == 200
    out = res.json()
    assert out["percent"] == 100.0 and out["feedback"][0]["is_correct"] is True
    assert out["feedback"][0]["citations"][0]["excerpt"]
    upd = out["mastery_updates"][0]
    assert upd["after"] > upd["before"]

    prog = client.get("/api/progress", headers=hdr(user)).json()
    assert prog["topics_tracked"] == 1 and prog["quizzes_taken"] == 1 and prog["average_score"] == 100.0
    hist = client.get("/api/quizzes/history", headers=hdr(user)).json()
    assert len(hist) == 1 and hist[0]["quiz_id"] == quiz["id"]
    assert client.get("/api/learner/profile", headers=hdr(user)).json()["quizzes_taken"] == 1

    # the same question again must be rejected as a repeat -> nothing verified -> 422
    again = client.post("/api/quizzes/generate", json={"mode": "mixed", "num_questions": 1, "difficulty": "beginner"},
                        headers=hdr(user))
    assert again.status_code == 422


def test_new_student_profile_and_recommendations(client):
    prof = client.get("/api/learner/profile", headers=hdr("u-brandnew")).json()
    assert prof["is_new_student"] is True and prof["overall_mastery"] is None
    rec = client.get("/api/recommendations", headers=hdr("u-brandnew")).json()
    assert rec["has_history"] is False and rec["suggestions"]


# ---------- assessment unit tests ----------
RAW = {"type": "mcq", "question": "Into what kind of energy do plants convert light?",
       "options": ["A) Heat", "B) Chemical energy", "C) Sound", "D) Pressure"], "answer": "B",
       "source": "S1", "source_quote": "plants convert light energy into chemical energy"}


def test_validate_question_accepts_good_and_rejects_bad():
    chunks = {"S1": SimpleNamespace(text=DOC)}
    q, why = A.validate_question(RAW, ["mcq"], chunks)
    assert q is not None and q["answer"] == "B" and q["options"][0] == "Heat"
    assert A.validate_question({**RAW, "source_quote": "plants turn sunlight into gold bars"}, ["mcq"], chunks)[0] is None
    assert A.validate_question({**RAW, "options": ["a", "a", "b", "c"]}, ["mcq"], chunks)[0] is None
    assert A.validate_question({**RAW, "answer": "Z"}, ["mcq"], chunks)[0] is None
    assert A.validate_question({**RAW, "source": "S7"}, ["mcq"], chunks)[0] is None
    assert A.validate_question(RAW, ["short_answer"], chunks)[0] is None


def test_grading_functions():
    opts = ["Heat", "Chemical energy", "Sound", "Pressure"]
    assert A.grade_mcq("b", opts, "B") == 1.0 and A.grade_mcq("Chemical energy", opts, "B") == 1.0
    assert A.grade_mcq("A", opts, "B") == 0.0
    assert A.grade_numeric("9.81 m/s", "9.8", 1.0) == 1.0 and A.grade_numeric("12", "9.8", 1.0) == 0.0
    assert A.parse_number("3 x 10^8") == pytest.approx(3e8)
    assert A.exact_short_match("The Chloroplast!", "chloroplast", [])
    assert A.lexical_short_answer_score("chlorophyll absorbs sunlight", "chlorophyll absorbs sunlight energy", []) >= 0.5


def test_repeat_detection():
    assert A.is_repeat("What is the powerhouse of the cell?", [A.normalize_text("what is the powerhouse of the cell")])
    assert not A.is_repeat("Define osmosis in plants", [A.normalize_text("What is the powerhouse of the cell?")])


# ---------- mastery ----------
def test_bkt_update_properties():
    p = 0.3
    up, down = mastery_service.bkt_update(p, True, 0.25), mastery_service.bkt_update(p, False, 0.25)
    assert up > p > down
    assert mastery_service.bkt_update(p, True, 0.02) > up  # harder-to-guess question types give more evidence
    for x in (0.0, 1.0, 0.5):
        assert 0.01 <= mastery_service.bkt_update(x, True, 0.25) <= 0.99
    assert mastery_service.status_for(0.2) == "weak" and mastery_service.status_for(0.9) == "strong"


# ---------- intent routing ----------
@pytest.mark.parametrize("msg,intent", [
    ("Explain photosynthesis simply", "tutor"),
    ("Give me 5 MCQs on photosynthesis", "quiz"),
    ("Run a diagnostic test for me", "diagnostic"),
    ("Show my progress", "progress"),
    ("What should I study next?", "recommend"),
])
def test_intent_routing(msg, intent):
    assert detect_intent(msg)[0] == intent


def test_quiz_parameter_extraction():
    intent, p = detect_intent("Give me 5 hard MCQs on photosynthesis")
    assert intent == "quiz" and p["num_questions"] == 5 and p["difficulty"] == "advanced"
    assert p["question_types"] == ["mcq"] and p["topic"] == "photosynthesis"