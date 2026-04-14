from __future__ import annotations

import re
from dataclasses import dataclass


_GREETING_RE = re.compile(r"^(hi|hello|hey|good morning|good afternoon|good evening)[\!\.\? ]*$", re.IGNORECASE)
_SMALL_TALK_RE = re.compile(r"\b(how are you|who are you|what can you do|thanks|thank you)\b", re.IGNORECASE)
_FILE_LIST_RE = re.compile(
    r"\b(what files|which files|list files|what documents|which documents|files do you have|documents do you have)\b",
    re.IGNORECASE,
)
_PII_RE = re.compile(r"\b(ssn|social security|credit card|passport number|bank account|passwords?)\b", re.IGNORECASE)
_MEDICAL_RE = re.compile(r"\b(diagnose|treatment|medication|prescription|medical advice)\b", re.IGNORECASE)
_LEGAL_RE = re.compile(r"\b(legal advice|lawsuit|sue|contract clause|compliance advice)\b", re.IGNORECASE)

_FLUFF_RE = re.compile(
    r"\b(please|can you|could you|would you|tell me|i want to know|help me|explain)\b",
    re.IGNORECASE,
)


@dataclass
class IntentResult:
    intent: str
    use_kb: bool
    refusal_reason: str | None = None


def detect_intent(query: str) -> IntentResult:
    q = query.strip()
    if _PII_RE.search(q):
        return IntentResult(intent="refusal_pii", use_kb=False, refusal_reason="pii_policy")
    if _MEDICAL_RE.search(q):
        return IntentResult(intent="refusal_medical", use_kb=False, refusal_reason="medical_policy")
    if _LEGAL_RE.search(q):
        return IntentResult(intent="refusal_legal", use_kb=False, refusal_reason="legal_policy")
    if _GREETING_RE.match(q):
        return IntentResult(intent="greeting", use_kb=False)
    if _SMALL_TALK_RE.search(q):
        return IntentResult(intent="small_talk", use_kb=False)
    if _FILE_LIST_RE.search(q):
        return IntentResult(intent="file_inventory", use_kb=False)
    if "list" in q.lower() or "table" in q.lower():
        return IntentResult(intent="structured", use_kb=True)
    return IntentResult(intent="kb_question", use_kb=True)


def rewrite_query_for_retrieval(query: str) -> str:
    no_fluff = _FLUFF_RE.sub(" ", query)
    no_fluff = re.sub(r"\s+", " ", no_fluff).strip()
    return no_fluff or query

