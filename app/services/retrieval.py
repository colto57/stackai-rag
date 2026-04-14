from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Any

from app.config import Settings
from app.services.embeddings import MistralEmbeddingClient
from app.services.storage import JsonStore


_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")
_ACRONYM_RE = re.compile(r"\b[A-Z]{3,}\b")
_IGNORED_ACRONYMS = {"pdf", "api", "llm", "rag"}


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def acronym_tokens(query: str) -> list[str]:
    tokens = [m.group(0).lower() for m in _ACRONYM_RE.finditer(query or "")]
    return [t for t in tokens if t not in _IGNORED_ACRONYMS]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    size = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(size))
    norm_a = math.sqrt(sum(v * v for v in a[:size]))
    norm_b = math.sqrt(sum(v * v for v in b[:size]))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class RetrievalService:
    def __init__(self, settings: Settings, store: JsonStore, embedder: MistralEmbeddingClient) -> None:
        self.settings = settings
        self.store = store
        self.embedder = embedder

    async def retrieve(self, query: str, top_k: int) -> dict[str, Any]:
        chunks = self.store.all_chunks()
        if not chunks:
            return {"results": [], "debug": {"reason": "empty_index"}}

        semantic_scores = await self._semantic_scores(query, chunks)
        keyword_scores = self._keyword_scores(query, chunks)
        fused = self._hybrid_fuse(chunks, semantic_scores, keyword_scores)
        reranked = self._rerank(fused)
        acronyms = acronym_tokens(query)
        acronym_filtered_count = 0
        if acronyms:
            filtered = [
                item
                for item in reranked
                if any(acr in item.get("text", "").lower() for acr in acronyms)
            ]
            if filtered:
                acronym_filtered_count = len(filtered)
                reranked = filtered
        results = reranked[:top_k]
        return {
            "results": results,
            "debug": {
                "semantic_weight": self.settings.semantic_weight,
                "keyword_weight": self.settings.keyword_weight,
                "candidate_count": len(chunks),
                "acronym_tokens": acronyms,
                "acronym_filtered_count": acronym_filtered_count,
            },
        }

    async def _semantic_scores(self, query: str, chunks: list[dict[str, Any]]) -> dict[str, float]:
        q_vec = await self.embedder.embed_text(query)
        return {
            c["chunk_id"]: max(0.0, cosine_similarity(q_vec, c.get("embedding", [])))
            for c in chunks
        }

    def _keyword_scores(self, query: str, chunks: list[dict[str, Any]]) -> dict[str, float]:
        query_tokens = _tokens(query)
        if not query_tokens:
            return {}
        tf_by_chunk: dict[str, Counter[str]] = {}
        doc_freq: defaultdict[str, int] = defaultdict(int)
        lengths: dict[str, int] = {}
        for c in chunks:
            toks = _tokens(c["text"])
            lengths[c["chunk_id"]] = len(toks) or 1
            tf = Counter(toks)
            tf_by_chunk[c["chunk_id"]] = tf
            for token in set(toks):
                doc_freq[token] += 1

        avg_len = sum(lengths.values()) / max(1, len(lengths))
        k1 = 1.5
        b = 0.75
        n_docs = len(chunks)
        scores: dict[str, float] = {}

        for c in chunks:
            chunk_id = c["chunk_id"]
            score = 0.0
            for token in query_tokens:
                tf = tf_by_chunk[chunk_id][token]
                if tf == 0:
                    continue
                df = doc_freq[token]
                idf = math.log((n_docs - df + 0.5) / (df + 0.5) + 1.0)
                denom = tf + k1 * (1 - b + b * lengths[chunk_id] / avg_len)
                score += idf * (tf * (k1 + 1.0)) / denom
            scores[chunk_id] = max(0.0, score)
        return scores

    def _hybrid_fuse(
        self,
        chunks: list[dict[str, Any]],
        semantic: dict[str, float],
        keyword: dict[str, float],
    ) -> list[dict[str, Any]]:
        max_sem = max(semantic.values()) if semantic else 1.0
        max_key = max(keyword.values()) if keyword else 1.0
        sem_rank = {cid: i for i, cid in enumerate(sorted(semantic, key=semantic.get, reverse=True), start=1)}
        key_rank = {cid: i for i, cid in enumerate(sorted(keyword, key=keyword.get, reverse=True), start=1)}

        fused: list[dict[str, Any]] = []
        for c in chunks:
            cid = c["chunk_id"]
            sem_norm = (semantic.get(cid, 0.0) / max_sem) if max_sem > 0 else 0.0
            key_norm = (keyword.get(cid, 0.0) / max_key) if max_key > 0 else 0.0
            weighted = self.settings.semantic_weight * sem_norm + self.settings.keyword_weight * key_norm
            rrf = 1.0 / (60 + sem_rank.get(cid, 1000)) + 1.0 / (60 + key_rank.get(cid, 1000))
            total = 0.85 * weighted + 0.15 * rrf
            fused.append(
                {
                    **c,
                    "semantic_score": semantic.get(cid, 0.0),
                    "keyword_score": keyword.get(cid, 0.0),
                    "score": total,
                }
            )
        fused.sort(key=lambda x: x["score"], reverse=True)
        return fused

    def _rerank(self, ranked: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen_signatures: set[str] = set()
        doc_counts: defaultdict[str, int] = defaultdict(int)
        reranked: list[dict[str, Any]] = []
        for c in ranked:
            signature = " ".join(_tokens(c["text"])[:20])
            if signature in seen_signatures:
                continue
            if doc_counts[c["doc_id"]] >= 3:
                continue
            seen_signatures.add(signature)
            doc_counts[c["doc_id"]] += 1
            reranked.append(c)
        return reranked

