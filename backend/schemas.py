from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

QType = Literal["mcq", "short_answer", "numerical"]
Difficulty = Literal["beginner", "intermediate", "advanced"]
SESSION_PATTERN = r"^[A-Za-z0-9_\-]{1,64}$"


class CitationOut(BaseModel):
    marker: Optional[str] = None
    chunk_id: str
    document_id: str
    document_name: str
    content_type: str
    topic: str
    page: Optional[int] = None
    slide: Optional[int] = None
    start_sec: Optional[float] = None
    end_sec: Optional[float] = None
    label: str
    excerpt: Optional[str] = None
    score: Optional[float] = None
    source_available: bool = True


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    filename: str
    file_type: str
    size_bytes: int
    status: str
    error: Optional[str] = None
    warnings: list[str] = []
    chunk_count: int
    created_at: datetime


class DocumentUploadResponse(BaseModel):
    document: DocumentOut
    message: str


class ChunkDetail(BaseModel):
    chunk_index: int
    citation: CitationOut
    text: str
    previous_text: Optional[str] = None
    next_text: Optional[str] = None


class TraceStep(BaseModel):
    agent: str
    action: str
    status: str = "ok"
    duration_ms: float = 0.0
    detail: Optional[str] = None


# ---------- tutor ----------
class TutorChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(default="default", pattern=SESSION_PATTERN)
    mode: Literal["simple", "detailed", "example"] = "simple"
    language: Literal["en", "hi"] = "en"
    document_ids: Optional[list[str]] = Field(default=None, max_length=50)
    top_k: Optional[int] = Field(default=None, ge=1, le=12)
    allow_outside_knowledge: bool = False

    @field_validator("question")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("question must not be blank")
        return v


class RetrievalInfo(BaseModel):
    query: str
    top_k: int
    returned: int
    threshold: float
    top_score: Optional[float] = None


class TutorResponse(BaseModel):
    answer: str
    evidence_status: Literal["supported", "partial", "insufficient"]
    citations: list[CitationOut] = []
    outside_knowledge_note: Optional[str] = None
    retrieval: RetrievalInfo
    mode: str
    language: str
    session_id: str
    suggestions: list[str] = []


class HistoryMessage(BaseModel):
    role: str
    content: str
    created_at: datetime
    meta: dict[str, Any] = {}


# ---------- quizzes ----------
class QuizGenerateRequest(BaseModel):
    mode: Literal["topic", "document", "mixed"] = "mixed"
    topics: list[str] = Field(default_factory=list, max_length=10)
    document_ids: list[str] = Field(default_factory=list, max_length=50)
    num_questions: int = Field(default=5, ge=1, le=20)
    difficulty: Literal["beginner", "intermediate", "advanced", "adaptive"] = "adaptive"
    question_types: list[QType] = Field(default_factory=lambda: ["mcq"], min_length=1)
    kind: Literal["practice", "mock_exam", "diagnostic"] = "practice"

    @model_validator(mode="after")
    def _check(self):
        if self.mode == "topic" and not [t for t in self.topics if t.strip()]:
            raise ValueError("topics are required when mode is 'topic'")
        if self.mode == "document" and not self.document_ids:
            raise ValueError("document_ids are required when mode is 'document'")
        return self


class QuestionOut(BaseModel):
    id: str
    position: int
    type: str
    text: str
    options: Optional[list[str]] = None
    topic: str
    difficulty: str
    verified: bool
    verification: str
    sources: list[CitationOut]


class QuizOut(BaseModel):
    id: str
    title: str
    kind: str
    mode: str
    difficulty: str
    created_at: datetime
    questions: list[QuestionOut]
    warnings: list[str] = []


class SubmitAnswer(BaseModel):
    question_id: str
    answer: str = Field(default="", max_length=2000)


class QuizSubmitRequest(BaseModel):
    answers: list[SubmitAnswer] = Field(min_length=1, max_length=50)


class QuestionFeedback(BaseModel):
    question_id: str
    position: int
    type: str
    question: str
    topic: str
    user_answer: Optional[str] = None
    answered: bool
    is_correct: bool
    score: float
    correct_answer: str
    explanation: str
    grading_method: str
    feedback: Optional[str] = None
    citations: list[CitationOut]


class TopicScore(BaseModel):
    topic: str
    asked: int
    score: float
    accuracy: float


class Misconception(BaseModel):
    topic: str
    question: str
    your_answer: str
    correct_answer: str
    note: str


class RevisionItem(BaseModel):
    topic: str
    sources: list[str]


class QuizReport(BaseModel):
    weak_topics: list[TopicScore] = []
    strengths: list[TopicScore] = []
    misconceptions: list[Misconception] = []
    suggested_revision: list[RevisionItem] = []
    skipped: int = 0


class MasteryUpdate(BaseModel):
    topic: str
    before: float
    after: float


class QuizResult(BaseModel):
    attempt_id: str
    quiz_id: str
    score: float
    max_score: float
    percent: float
    answered: int
    total: int
    feedback: list[QuestionFeedback]
    report: QuizReport
    mastery_updates: list[MasteryUpdate]


class QuizHistoryItem(BaseModel):
    attempt_id: str
    quiz_id: str
    title: str
    kind: str
    difficulty: str
    score: float
    max_score: float
    percent: float
    submitted_at: datetime


# ---------- learner / progress ----------
class LearnerProfileUpdate(BaseModel):
    level: Optional[Difficulty] = None
    goal: Optional[str] = Field(default=None, max_length=300)
    preferred_language: Optional[Literal["en", "hi"]] = None


class RecentMistake(BaseModel):
    question_id: str
    topic: str
    question: str
    your_answer: Optional[str]
    correct_answer: str


class LearnerProfileOut(BaseModel):
    user_id: str
    level: str
    goal: Optional[str]
    preferred_language: str
    diagnostic_completed: bool
    is_new_student: bool
    topics_tracked: int
    overall_mastery: Optional[float]
    quizzes_taken: int
    accuracy_by_question_type: dict[str, float]
    recent_mistakes: list[RecentMistake]
    last_active: Optional[datetime]
    note: str


class TopicMasteryOut(BaseModel):
    topic: str
    mastery: float
    status: Literal["weak", "developing", "strong"]
    attempts: int
    correct: int
    accuracy: Optional[float]
    last_practiced: Optional[datetime]


class ActivityOut(BaseModel):
    kind: str
    detail: dict[str, Any]
    created_at: datetime


class TimelinePoint(BaseModel):
    date: str
    overall_mastery: float


class RevisionPriority(BaseModel):
    topic: str
    mastery: float
    priority: float
    days_since_practice: Optional[int]
    reason: str


class PracticeQuestion(BaseModel):
    question_id: str
    quiz_id: str
    topic: str
    type: str
    text: str
    options: Optional[list[str]] = None


class RecommendationsOut(BaseModel):
    has_history: bool
    next_topics: list[str]
    revision_priorities: list[RevisionPriority]
    practice_questions: list[PracticeQuestion]
    suggestions: list[str]


class ProgressOut(BaseModel):
    overall_mastery: Optional[float]
    topics_tracked: int
    quizzes_taken: int
    average_score: Optional[float]
    accuracy: Optional[float]
    topics: list[TopicMasteryOut]
    strong_topics: list[str]
    weak_topics: list[str]
    recent_activity: list[ActivityOut]
    mastery_timeline: list[TimelinePoint]
    quiz_scores: list[QuizHistoryItem]
    recommendations: RecommendationsOut


# ---------- orchestrator ----------
class OrchestrateRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(default="default", pattern=SESSION_PATTERN)
    document_ids: Optional[list[str]] = Field(default=None, max_length=50)
    intent: Optional[Literal["tutor", "quiz", "progress", "recommend", "diagnostic"]] = None
    mode: Literal["simple", "detailed", "example"] = "simple"
    language: Literal["en", "hi"] = "en"
    allow_outside_knowledge: bool = False

    @field_validator("message")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message must not be blank")
        return v


class OrchestrateResponse(BaseModel):
    intent: str
    status: Literal["ok", "insufficient_evidence", "needs_documents"]
    message: str
    tutor: Optional[TutorResponse] = None
    quiz: Optional[QuizOut] = None
    progress: Optional[ProgressOut] = None
    recommendations: Optional[RecommendationsOut] = None
    trace: list[TraceStep] = []


# ---------- evaluation ----------
class ExpectedSource(BaseModel):
    document_name: str
    page: Optional[int] = None
    slide: Optional[int] = None
    start_sec: Optional[float] = None
    end_sec: Optional[float] = None


class RetrievalCase(BaseModel):
    id: str
    question: str
    expected_sources: list[ExpectedSource] = []
    reference_answer: Optional[str] = None


class UnsupportedCase(BaseModel):
    id: str
    question: str


class QuizCase(BaseModel):
    id: str
    document_names: list[str]
    num_questions: int = Field(default=3, ge=1, le=10)


class EvalOptions(BaseModel):
    generate_answers: bool = False  # costs API credits: runs the tutor on each case
    top_k: Optional[int] = Field(default=None, ge=1, le=12)


class EvaluationDataset(BaseModel):
    name: str = "dataset"
    options: EvalOptions = EvalOptions()
    retrieval_cases: list[RetrievalCase] = []
    unsupported_cases: list[UnsupportedCase] = []
    quiz_cases: list[QuizCase] = []


class EvaluationRequest(BaseModel):
    dataset: EvaluationDataset