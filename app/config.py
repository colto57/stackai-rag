from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Settings:
    mistral_api_key: str
    mistral_chat_model: str
    mistral_embed_model: str
    data_dir: str
    max_upload_files: int
    max_upload_size_mb: int
    default_top_k: int
    max_top_k: int
    min_chunk_chars: int
    max_chunk_chars: int
    chunk_overlap_chars: int
    semantic_weight: float
    keyword_weight: float
    min_evidence_score: float


def load_settings() -> Settings:
    return Settings(
        mistral_api_key=os.getenv("MISTRAL_API_KEY", "").strip(),
        mistral_chat_model=os.getenv("MISTRAL_CHAT_MODEL", "mistral-small-latest").strip(),
        mistral_embed_model=os.getenv("MISTRAL_EMBED_MODEL", "mistral-embed").strip(),
        data_dir=os.getenv("DATA_DIR", "data").strip(),
        max_upload_files=int(os.getenv("MAX_UPLOAD_FILES", "10")),
        max_upload_size_mb=int(os.getenv("MAX_UPLOAD_SIZE_MB", "20")),
        default_top_k=int(os.getenv("DEFAULT_TOP_K", "5")),
        max_top_k=int(os.getenv("MAX_TOP_K", "10")),
        min_chunk_chars=int(os.getenv("MIN_CHUNK_CHARS", "350")),
        max_chunk_chars=int(os.getenv("MAX_CHUNK_CHARS", "900")),
        chunk_overlap_chars=int(os.getenv("CHUNK_OVERLAP_CHARS", "120")),
        semantic_weight=float(os.getenv("SEMANTIC_WEIGHT", "0.65")),
        keyword_weight=float(os.getenv("KEYWORD_WEIGHT", "0.35")),
        min_evidence_score=float(os.getenv("MIN_EVIDENCE_SCORE", "0.4")),
    )

