from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pypdf import PdfReader

from app.config import Settings
from app.services.embeddings import MistralEmbeddingClient
from app.services.storage import JsonStore


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[\.\!\?])\s+")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class IngestedDocument:
    doc_id: str
    filename: str
    pages: int
    chunks: list[dict[str, Any]]


def _normalize_text(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def _sentences(text: str) -> list[str]:
    raw = _SENTENCE_SPLIT_RE.split(text)
    return [s.strip() for s in raw if s.strip()]


def chunk_pages(page_texts: list[tuple[int, str]], settings: Settings) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    current_text = ""
    current_pages: list[int] = []
    chunk_idx = 0

    for page_num, page_text in page_texts:
        text = _normalize_text(page_text)
        if not text:
            continue
        for sentence in _sentences(text):
            add_text = sentence if not current_text else f"{current_text} {sentence}"
            if len(add_text) <= settings.max_chunk_chars:
                current_text = add_text
                current_pages.append(page_num)
                continue

            if len(current_text) >= settings.min_chunk_chars:
                chunks.append(
                    {
                        "chunk_idx": chunk_idx,
                        "text": current_text,
                        "page_start": min(current_pages),
                        "page_end": max(current_pages),
                    }
                )
                chunk_idx += 1
                overlap = current_text[-settings.chunk_overlap_chars :] if settings.chunk_overlap_chars > 0 else ""
                current_text = (overlap + " " + sentence).strip() if overlap else sentence
                current_pages = [page_num]
            else:
                current_text = add_text
                current_pages.append(page_num)

    if current_text:
        chunks.append(
            {
                "chunk_idx": chunk_idx,
                "text": current_text,
                "page_start": min(current_pages) if current_pages else 1,
                "page_end": max(current_pages) if current_pages else 1,
            }
        )
    return chunks


class IngestionService:
    def __init__(self, settings: Settings, store: JsonStore, embedder: MistralEmbeddingClient) -> None:
        self.settings = settings
        self.store = store
        self.embedder = embedder

    async def ingest_pdf(self, filename: str, content: bytes) -> IngestedDocument:
        reader = PdfReader(io.BytesIO(content))
        page_texts: list[tuple[int, str]] = []
        for idx, page in enumerate(reader.pages, start=1):
            page_texts.append((idx, page.extract_text() or ""))

        raw_chunks = chunk_pages(page_texts, self.settings)
        embeddings = await self.embedder.embed_texts([c["text"] for c in raw_chunks])
        now = datetime.now(timezone.utc).isoformat()
        doc_id = f"doc_{int(datetime.now(timezone.utc).timestamp() * 1000)}"
        self.store.save_pdf(filename, content)

        chunks: list[dict[str, Any]] = []
        for raw, emb in zip(raw_chunks, embeddings):
            chunk_id = f"{doc_id}_chunk_{raw['chunk_idx']}"
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "doc_id": doc_id,
                    "filename": filename,
                    "chunk_idx": raw["chunk_idx"],
                    "text": raw["text"],
                    "page_start": raw["page_start"],
                    "page_end": raw["page_end"],
                    "embedding": emb,
                    "created_at": now,
                }
            )

        document = {
            "doc_id": doc_id,
            "filename": filename,
            "pages": len(page_texts),
            "created_at": now,
        }
        self.store.upsert_document(document, chunks)
        return IngestedDocument(doc_id=doc_id, filename=filename, pages=len(page_texts), chunks=chunks)

