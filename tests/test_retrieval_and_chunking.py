from app.config import Settings
from app.services.pdf_ingest import chunk_pages
from app.services.query_processing import detect_intent, rewrite_query_for_retrieval
from app.services.retrieval import acronym_tokens, cosine_similarity
from app.services.storage import JsonStore


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
    assert detect_intent("what files do you have access to").intent == "file_inventory"


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


def test_storage_keeps_distinct_documents_for_same_millisecond_ids(tmp_path) -> None:
    # Regression guard for prior timestamp-based doc_id collisions.
    store = JsonStore(str(tmp_path))
    doc1 = {"doc_id": "doc_a", "filename": "a.pdf", "pages": 1, "created_at": "t1"}
    doc2 = {"doc_id": "doc_b", "filename": "b.pdf", "pages": 1, "created_at": "t2"}
    store.upsert_document(doc1, [{"chunk_id": "a1", "doc_id": "doc_a", "text": "x"}])
    store.upsert_document(doc2, [{"chunk_id": "b1", "doc_id": "doc_b", "text": "y"}])
    docs = store.list_documents()
    names = {d["filename"] for d in docs}
    assert names == {"a.pdf", "b.pdf"}


def test_acronym_token_extraction() -> None:
    assert acronym_tokens("What is README in this PDF?") == ["readme"]


def test_chunk_pages_handles_long_technical_blocks() -> None:
    settings = _settings()
    long_block = (
        "README framework uses symbolic regression with Bayesian Optimization and Grey Wolf Optimizer. "
        "This section includes mathematical constraints, objective functions, and reproducibility checklist. "
        "Hyperparameters and random seeds are reported for each experiment to ensure comparability. "
        "Additional ablation studies describe why latent diffusion improves the equation search objective."
    )
    chunks = chunk_pages([(1, long_block)], settings)
    assert len(chunks) >= 2
    assert all(chunk["text"].strip() for chunk in chunks)

