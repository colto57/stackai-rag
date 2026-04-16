from __future__ import annotations

import re
from typing import Any

import httpx

from app.config import Settings


_SENT_SPLIT = re.compile(r"(?<=[\.\!\?])\s+")
_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")
_STOP_TOKENS = {
    "what",
    "which",
    "how",
    "does",
    "about",
    "this",
    "that",
    "with",
    "from",
    "into",
    "your",
    "their",
    "have",
    "has",
    "tell",
    "me",
    "the",
    "and",
    "for",
    "you",
}


class GenerationService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.url = "https://api.mistral.ai/v1/chat/completions"

    async def direct_reply(self, query: str, intent: str) -> str:
        if intent.startswith("refusal_"):
            if intent == "refusal_pii":
                return "I cannot help with sensitive personal data extraction or disclosure requests."
            if intent == "refusal_medical":
                return "I cannot provide medical advice. Please consult a licensed healthcare professional."
            if intent == "refusal_legal":
                return "I cannot provide legal advice. Please consult a qualified legal professional."
        if intent in {"greeting", "small_talk"}:
            return "Hello! I can answer questions from your uploaded PDF knowledge base. Upload files, then ask a question."
        answer = await self._chat_completion(
            system_prompt="You are a concise assistant.",
            user_prompt=query,
        )
        if not answer:
            return "I could not generate a response from the language model right now. Please try again."
        return answer

    async def grounded_answer(
        self,
        query: str,
        rewritten_query: str,
        intent: str,
        results: list[dict[str, Any]],
    ) -> tuple[str, list[str]]:
        if not self._query_has_context_support(query, results):
            citations = [f"[{i}] {r['filename']} p.{r['page_start']}-{r['page_end']}" for i, r in enumerate(results, start=1)]
            return "insufficient evidence", citations

        context_lines = []
        for i, item in enumerate(results, start=1):
            context_lines.append(
                f"[{i}] {item['filename']} p.{item['page_start']}-{item['page_end']}: {item['text']}"
            )
        context = "\n".join(context_lines)

        if intent == "structured":
            style = "If the user asks for a list or table, use markdown bullet points or a simple markdown table."
        else:
            style = "Use concise paragraphs."

        system_prompt = (
            "You are a strict grounded QA assistant. "
            "Use only the provided context and do not use prior knowledge. "
            "Do not invent definitions, expansions, or background details not explicitly present in context. "
            "Every factual claim must include citation markers like [1], [2]. "
            "If evidence is missing or ambiguous, reply exactly: insufficient evidence."
        )
        user_prompt = (
            f"User query: {query}\n"
            f"Retrieval query: {rewritten_query}\n"
            f"Style instruction: {style}\n\n"
            f"Context:\n{context}\n\n"
            "Answer with citations only from this context. "
            "If user asks what a term means in the document, describe only what the document says about it."
        )
        answer = await self._chat_completion(system_prompt=system_prompt, user_prompt=user_prompt)
        if not answer:
            # Fallback to extractive response when chat completion is unavailable.
            fallback = self._extractive_fallback(query, results)
            return fallback, [f"[{i}] {r['filename']} p.{r['page_start']}-{r['page_end']}" for i, r in enumerate(results, start=1)]
        checked = self._evidence_check(answer, results)
        if self._is_insufficiently_supported(checked):
            checked = "insufficient evidence"
        citations = [f"[{i}] {r['filename']} p.{r['page_start']}-{r['page_end']}" for i, r in enumerate(results, start=1)]
        return checked, citations

    async def _chat_completion(self, system_prompt: str, user_prompt: str) -> str:
        if not self.settings.mistral_api_key:
            return ""
        payload: dict[str, Any] = {
            "model": self.settings.mistral_chat_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.mistral_api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                response = await client.post(self.url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception:
            return ""

    def _evidence_check(self, answer: str, results: list[dict[str, Any]]) -> str:
        context_words = set()
        for r in results:
            context_words.update(re.findall(r"[a-zA-Z0-9]+", r["text"].lower()))
        sentences = _SENT_SPLIT.split(answer)
        validated: list[str] = []
        for sentence in sentences:
            words = re.findall(r"[a-zA-Z0-9]+", sentence.lower())
            if not words:
                continue
            overlap = sum(1 for w in words if w in context_words)
            ratio = overlap / max(1, len(words))
            if ratio < 0.2 and "[" not in sentence:
                validated.append("[Unsupported claim removed by evidence filter.]")
            else:
                validated.append(sentence)
        return " ".join(validated)

    def _extractive_fallback(self, query: str, results: list[dict[str, Any]]) -> str:
        snippets: list[str] = []
        for i, item in enumerate(results[:3], start=1):
            snippet = item["text"].strip().replace("\n", " ")
            if len(snippet) > 260:
                snippet = snippet[:260].rstrip() + "..."
            snippets.append(f"[{i}] {snippet}")
        if not snippets:
            return "insufficient evidence"
        return (
            "I could not reach the language model, so here are the most relevant extracted passages:\n"
            + "\n".join(snippets)
            + "\n\nPlease retry once the API key/model access is valid."
        )

    def _is_insufficiently_supported(self, answer: str) -> bool:
        text = (answer or "").strip().lower()
        if not text:
            return True
        if text == "insufficient evidence":
            return True
        if "[unsupported claim removed by evidence filter.]" in text:
            return True
        return False

    def _query_has_context_support(self, query: str, results: list[dict[str, Any]]) -> bool:
        q_terms = {t for t in _TOKEN_RE.findall((query or "").lower()) if len(t) > 2 and t not in _STOP_TOKENS}
        if not q_terms:
            return True
        context = " ".join(r.get("text", "").lower() for r in results)
        if not context:
            return False
        covered = sum(1 for term in q_terms if term in context)
        return covered / len(q_terms) >= 0.35

