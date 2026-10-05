from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    email: str
    username: str
    role: str


class DocumentMetadata(BaseModel):
    chunk_id: str
    document_id: str
    document_name: str
    page: Optional[int] = None
    role: str
    department: Optional[str] = None
    access_level: Optional[str] = None
    source_type: str


class ChatMessage(BaseModel):
    role: str = "user"
    content: str


class ChatRequest(BaseModel):
    question: str
    history: list[ChatMessage] = Field(default_factory=list)


class RetrievalChunk(BaseModel):
    chunk_id: str
    document_id: str
    document_name: str
    content: str
    role: str
    page: Optional[int] = None
    score: float = 0.0
    source_type: str = "text"


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]
    citations: list[str]
    evidence: str
    latency_ms: float
    query_id: str = ""
    model: str = ""
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    cache_hit: bool = False
    retrieved_chunks: list[dict] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=25)


class EvaluationResult(BaseModel):
    recall_at_5: Optional[float] = None
    mrr: Optional[float] = None
    unauthorized_retrieval_rate: Optional[float] = None
    p50_latency_ms: Optional[float] = None
    p95_latency_ms: Optional[float] = None
    cost_per_request: Optional[float] = None
    findings: list[str] = Field(default_factory=list)


class DocumentUploadRequest(BaseModel):
    filename: str
    content: str
    role: str = "EMPLOYEE"
    department: str = "General"

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"PUBLIC", "EMPLOYEE", "MANAGER", "ADMIN"}:
            raise ValueError("role must be PUBLIC, EMPLOYEE, MANAGER, or ADMIN")
        return normalized


class DocumentIngestRequest(BaseModel):
    relative_path: str
    access_level: str = "EMPLOYEE"
    department: str = "General"
