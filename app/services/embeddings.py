from __future__ import annotations

from typing import Any

import httpx


class MistralEmbeddingClient:
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model
        self.url = "https://api.mistral.ai/v1/embeddings"

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.api_key:
            return [self._deterministic_fallback(text) for text in texts]

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "input": texts,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(self.url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        return [item["embedding"] for item in data["data"]]

    async def embed_text(self, text: str) -> list[float]:
        vectors = await self.embed_texts([text])
        return vectors[0]

    @staticmethod
    def _deterministic_fallback(text: str, dim: int = 128) -> list[float]:
        vector = [0.0] * dim
        for token in text.lower().split():
            idx = hash(token) % dim
            vector[idx] += 1.0
        norm = sum(v * v for v in vector) ** 0.5
        if norm == 0:
            return vector
        return [v / norm for v in vector]

