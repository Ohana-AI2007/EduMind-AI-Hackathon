# EduMind AI — Backend (Track D: Personalized Tutoring & Adaptive Learning)

FastAPI + OpenAI + ChromaDB + SQLite. **Prototype for a controlled demo: there is no authentication.**
The `X-User-Id` header only partitions data between demo users and is NOT a security boundary.

## Prerequisites
- Python 3.11+, PowerShell
- Optional: FFmpeg on PATH (lecture videos), Tesseract + `opencv-python-headless` + `pytesseract` (OCR)
- An OpenAI API key is needed only for AI features (see "What needs API credits")

## Setup (Windows PowerShell, from the `edumind-ai` folder)
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1      # if blocked: Set-ExecutionPolicy -Scope Process Bypass
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env                       # set OPENAI_API_KEY (optional for a degraded-mode run)
New-Item -ItemType Directory -Force data\uploads, data\chroma | Out-Null
uvicorn backend.main:app --reload --port 8000
```
Swagger UI: http://localhost:8000/docs. Always launch from the `edumind-ai` folder.

## Run without spending credits
```powershell
pytest -q                                    # all OpenAI calls are mocked
Invoke-RestMethod http://localhost:8000/api/health
```
With no key: health, document listing/status, citation lookup, progress, recommendations, profile and quiz
submission work. Uploads are extracted and stored with status `awaiting_index`. AI endpoints return `503 ai_not_configured`.

**Needs API credits:** indexing (embeddings), tutor chat, quiz generation/verification, LLM short-answer grading,
image descriptions, video transcription, `/api/evaluation/run`.

## Workflow and example requests
Use `curl.exe` (not the `curl` alias) in PowerShell.
```powershell
# 1. upload (returns 202; processing is a background task)
curl.exe -X POST http://localhost:8000/api/documents/upload -H "X-User-Id: alice" -F "file=@C:\path\notes.pdf"
# 2. poll until status = ready
Invoke-RestMethod http://localhost:8000/api/documents -Headers @{"X-User-Id"="alice"}
# 3. ask the tutor
$b = '{"question":"Explain osmosis simply","mode":"simple","language":"en","session_id":"s1"}'
Invoke-RestMethod http://localhost:8000/api/tutor/chat -Method Post -Body $b -ContentType "application/json" -Headers @{"X-User-Id"="alice"}
# 4. natural-language entry point (routes to tutor/quiz/progress/recommendations)
$b = '{"message":"Give me 5 MCQs on osmosis"}'
Invoke-RestMethod http://localhost:8000/api/orchestrate -Method Post -Body $b -ContentType "application/json" -Headers @{"X-User-Id"="alice"}
# 5. diagnostic quiz for a new student, then submit
Invoke-RestMethod http://localhost:8000/api/quizzes/diagnostic -Method Post -Headers @{"X-User-Id"="alice"}
$b = '{"answers":[{"question_id":"<id>","answer":"B"}]}'
Invoke-RestMethod http://localhost:8000/api/quizzes/<quiz_id>/submit -Method Post -Body $b -ContentType "application/json" -Headers @{"X-User-Id"="alice"}
# 6. dashboard
Invoke-RestMethod http://localhost:8000/api/progress -Headers @{"X-User-Id"="alice"}
```
Other endpoints: `GET /api/documents/{id}/status`, `/chunks`, `POST /api/documents/{id}/reprocess` (after setting the key or
fixing FFmpeg), `GET /api/documents/chunks/{chunk_id}` (citation → original passage and neighbours),
`GET /api/tutor/history`, `GET /api/quizzes/{id}`, `GET /api/quizzes/attempts/{id}`, `PUT /api/learner/profile`.

## How it works
**Ingestion:** PDF (PyMuPDF; page numbers), PPTX (slide numbers, tables, speaker notes), TXT/MD (heading-based topics), video/audio
(FFmpeg → fixed-length audio parts → OpenAI transcription → timestamped chunks). Each chunk stores document, page/slide/timestamps, topic and
content type (`text`, `slide`, `ocr_text`, `image_description`, `transcript`). Embeddings go to ChromaDB; SQLite is the source of truth.
Failures are reported in `status`/`error`/`warnings` (missing FFmpeg, empty pages, password-protected PDFs, etc.). Nothing is faked.
Image descriptions are off by default (`ENABLE_IMAGE_DESCRIPTIONS=true`, needs a vision-capable model) and are labelled "AI-described image".

**Agents** (`backend/orchestrator.py`, deterministic regex routing, no LLM call to pick an intent):
1. Knowledge agent: builds the query, retrieves, applies the relevance threshold and decides whether evidence exists.
2. Learner agent: supplies mastery context (new vs. returning student) and applies mastery updates.
3. Tutor agent: the only place that writes grounded answers; validates citation markers against retrieved chunks.
4. Quiz agent: generates, validates and grades questions.
5. Recommendation agent: ranks revision priorities, next topics and practice questions from stored data.
Tutor flow: knowledge → learner → tutor → learner (small exposure update) → recommendation. If nothing passes the threshold the LLM is not called.

**Citations:** the tutor sees numbered excerpts `[S1]…`; only markers matching real retrieved chunks survive, and each becomes a citation
with document name and page/slide/timestamp. If the model claims support without a valid marker, the answer is replaced by "insufficient evidence".
Outside knowledge appears only in `outside_knowledge_note` and only when `allow_outside_knowledge=true`.

**Quizzes:** questions are generated from sampled chunks (weighted to weaker topics). Each must cite an excerpt and include a quote that
exists verbatim in it (checked in code), plus an optional second LLM check of the answer key (`QUIZ_VERIFY_WITH_LLM`). Failures are rejected,
not shown. Near-duplicates of recent questions are filtered. Answer keys are only returned after submission.

**Mastery:** BKT-style update per topic with fixed hand-set parameters (initial 0.30, learn 0.15, slip 0.10, guess 0.25/0.05/0.02 for
MCQ/short/numerical); equations are in `services/mastery_service.py`. Parameters are not fitted to data, so treat values as estimates.
Skipped questions give no evidence; partial credit counts as incorrect for mastery. Tutoring adds a tiny exposure bump only.
Mastery below 0.4 is "weak", 0.4-0.7 "developing", above 0.7 "strong". Re-submitting a quiz counts as a new attempt.

## Evaluation
```powershell
# via CLI (uses your uploaded docs for the given user)
python -m backend.services.evaluation_service --dataset data\eval_example.json --user-id alice
# via API
Invoke-RestMethod http://localhost:8000/api/evaluation/example
```
Reports retrieval hit rate/MRR, context precision/recall against expected source locations, unsupported-query refusal rate,
quiz source-quote correctness, and repeated-question rate. With `generate_answers=true` it adds **proxy** faithfulness and answer-relevancy
scores (lexical overlap and embedding similarity). They are not RAGAS scores. RAGAS is not bundled; use it separately if you need it.
Metrics with no data are `null`.

## Troubleshooting
- `ModuleNotFoundError: backend`: run commands from the `edumind-ai` folder.
- `503 ai_not_configured`: set `OPENAI_API_KEY` in `.env` and restart.
- Document stuck at `awaiting_index`: fix the cause shown in `error`, then `POST /api/documents/{id}/reprocess`.
- Video `failed` with FFmpeg message: install FFmpeg and add it to PATH.
- Model errors (e.g. temperature or vision unsupported): change `OPENAI_MODEL` / `OPENAI_VISION_MODEL` / leave `OPENAI_TEMPERATURE` empty.
- Chroma errors after changing the embedding model: delete `data\chroma` and call reprocess on each document.
- Scanned PDFs yield no text: install OCR dependencies (see requirements.txt).