from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=20)


class Citation(BaseModel):
    chunk_id: str
    document: str
    page_start: int
    page_end: int
    score: float
    text_preview: str


class QueryResponse(BaseModel):
    answer: str
    status: Literal["ok", "insufficient_evidence", "refused"]
    intent: str
    used_knowledge_base: bool
    rewritten_query: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    retrieval_debug: dict[str, Any] = Field(default_factory=dict)


class FileIngestResult(BaseModel):
    filename: str
    status: Literal["ingested", "rejected", "error"]
    reason: str | None = None
    pages: int = 0
    chunks: int = 0


class IngestResponse(BaseModel):
    files: list[FileIngestResult]
    total_documents: int
    total_chunks: int


class MemoryFile(BaseModel):
    doc_id: str
    filename: str
    pages: int
    created_at: str | None = None


class MemoryFilesResponse(BaseModel):
    files: list[MemoryFile]
    total_documents: int
    total_chunks: int

