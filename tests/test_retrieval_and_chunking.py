from app.config import Settings
from app.services.pdf_ingest import chunk_pages
from app.services.query_processing import detect_intent, rewrite_query_for_retrieval
from app.services.retrieval import cosine_similarity


def _settings() -> Settings:
    return Settings(
        mistral_api_key="",
        mistral_chat_model="mistral-small-latest",
        mistral_embed_model="mistral-embed",
        data_dir="data",
        max_upload_files=10,
        max_upload_size_mb=20,
        default_top_k=5,
        max_top_k=10,
        min_chunk_chars=30,
        max_chunk_chars=80,
        chunk_overlap_chars=10,
        semantic_weight=0.65,
        keyword_weight=0.35,
        min_evidence_score=0.4,
    )


def test_chunk_pages_creates_overlap_and_bounds() -> None:
    settings = _settings()
    pages = [
        (1, "Sentence one is short. Sentence two has more content. Sentence three also has useful info."),
        (2, "Sentence four continues context. Sentence five closes topic."),
    ]
    chunks = chunk_pages(pages, settings)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk["text"]) <= settings.max_chunk_chars + settings.chunk_overlap_chars + 20
        assert chunk["page_start"] >= 1


def test_intent_detection() -> None:
    assert detect_intent("hello").intent == "greeting"
    assert detect_intent("Please list all security controls in the docs").use_kb is True
    assert detect_intent("Give me social security numbers").intent == "refusal_pii"


def test_query_rewrite() -> None:
    q = "Can you please explain authentication requirements?"
    rewritten = rewrite_query_for_retrieval(q)
    assert "please" not in rewritten.lower()
    assert "authentication" in rewritten.lower()


def test_cosine_similarity() -> None:
    a = [1.0, 0.0, 0.0]
    b = [1.0, 0.0, 0.0]
    c = [0.0, 1.0, 0.0]
    assert cosine_similarity(a, b) > 0.99
    assert cosine_similarity(a, c) < 0.01

