from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import load_settings
from app.models import Citation, FileIngestResult, IngestResponse, MemoryFile, MemoryFilesResponse, QueryRequest, QueryResponse
from app.services.embeddings import MistralEmbeddingClient
from app.services.generation import GenerationService
from app.services.pdf_ingest import IngestionService
from app.services.query_processing import detect_intent, rewrite_query_for_retrieval
from app.services.retrieval import RetrievalService
from app.services.storage import JsonStore


settings = load_settings()
embedder = MistralEmbeddingClient(settings.mistral_api_key, settings.mistral_embed_model)
generation = GenerationService(settings)
stores_by_session: dict[str, JsonStore] = {}

app = FastAPI(title="StackAI RAG Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


def _store_for_session(session_id: str) -> JsonStore:
    if session_id not in stores_by_session:
        session_data_dir = str(Path(settings.data_dir) / "sessions" / session_id)
        stores_by_session[session_id] = JsonStore(session_data_dir)
    return stores_by_session[session_id]


@app.middleware("http")
async def session_middleware(request: Request, call_next):
    session_id = request.cookies.get("session_id")
    if not session_id:
        session_id = uuid4().hex
    request.state.session_id = session_id
    response = await call_next(request)
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=7 * 24 * 60 * 60,
    )
    return response


@app.get("/")
async def home() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.post("/ingest", response_model=IngestResponse)
async def ingest(request: Request, files: list[UploadFile] = File(...)) -> IngestResponse:
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")
    if settings.max_upload_files > 0 and len(files) > settings.max_upload_files:
        raise HTTPException(status_code=400, detail=f"Max {settings.max_upload_files} files allowed per request.")

    store = _store_for_session(request.state.session_id)
    ingestion = IngestionService(settings, store, embedder)
    results: list[FileIngestResult] = []
    for upload in files:
        filename = upload.filename or "file.pdf"
        if not filename.lower().endswith(".pdf"):
            results.append(FileIngestResult(filename=filename, status="rejected", reason="Only PDF files are supported."))
            continue

        content = await upload.read()
        if len(content) > settings.max_upload_size_mb * 1024 * 1024:
            results.append(
                FileIngestResult(
                    filename=filename,
                    status="rejected",
                    reason=f"File exceeds max size ({settings.max_upload_size_mb} MB).",
                )
            )
            continue

        try:
            doc = await ingestion.ingest_pdf(filename=filename, content=content)
            results.append(
                FileIngestResult(
                    filename=filename,
                    status="ingested",
                    pages=doc.pages,
                    chunks=len(doc.chunks),
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(FileIngestResult(filename=filename, status="error", reason=str(exc)))

    stats = store.stats()
    return IngestResponse(files=results, total_documents=stats.total_documents, total_chunks=stats.total_chunks)


@app.get("/memory/files", response_model=MemoryFilesResponse)
async def list_memory_files(request: Request) -> MemoryFilesResponse:
    store = _store_for_session(request.state.session_id)
    docs = store.list_documents()
    stats = store.stats()
    return MemoryFilesResponse(
        files=[
            MemoryFile(
                doc_id=doc["doc_id"],
                filename=doc["filename"],
                pages=doc["pages"],
                created_at=doc.get("created_at"),
                file_size_bytes=doc.get("file_size_bytes"),
                file_hash=doc.get("file_hash"),
            )
            for doc in docs
        ],
        total_documents=stats.total_documents,
        total_chunks=stats.total_chunks,
    )


@app.delete("/memory/files", response_model=MemoryFilesResponse)
async def clear_memory_files(request: Request) -> MemoryFilesResponse:
    store = _store_for_session(request.state.session_id)
    store.clear_all()
    stats = store.stats()
    return MemoryFilesResponse(files=[], total_documents=stats.total_documents, total_chunks=stats.total_chunks)


@app.post("/query", response_model=QueryResponse)
async def query(request: Request, req: QueryRequest) -> QueryResponse:
    intent_result = detect_intent(req.query)
    top_k = min(req.top_k or settings.default_top_k, settings.max_top_k)
    store = _store_for_session(request.state.session_id)
    retrieval = RetrievalService(settings, store, embedder)

    if not intent_result.use_kb:
        answer = await generation.direct_reply(req.query, intent_result.intent)
        return QueryResponse(
            answer=answer,
            status="refused" if intent_result.intent.startswith("refusal_") else "ok",
            intent=intent_result.intent,
            used_knowledge_base=False,
        )

    rewritten = rewrite_query_for_retrieval(req.query)
    found = await retrieval.retrieve(rewritten, top_k)
    results = found["results"]
    if not results:
        return QueryResponse(
            answer="insufficient evidence",
            status="insufficient_evidence",
            intent=intent_result.intent,
            used_knowledge_base=True,
            rewritten_query=rewritten,
            retrieval_debug=found["debug"],
        )

    if results[0]["score"] < settings.min_evidence_score:
        return QueryResponse(
            answer="insufficient evidence",
            status="insufficient_evidence",
            intent=intent_result.intent,
            used_knowledge_base=True,
            rewritten_query=rewritten,
            retrieval_debug={**found["debug"], "top_score": results[0]["score"]},
        )

    selected = results[:top_k]
    answer, _ = await generation.grounded_answer(req.query, rewritten, intent_result.intent, selected)
    citations = [
        Citation(
            chunk_id=item["chunk_id"],
            document=item["filename"],
            page_start=item["page_start"],
            page_end=item["page_end"],
            score=item["score"],
            text_preview=item["text"][:220],
        )
        for item in selected
    ]
    return QueryResponse(
        answer=answer,
        status="ok",
        intent=intent_result.intent,
        used_knowledge_base=True,
        rewritten_query=rewritten,
        citations=citations,
        retrieval_debug={**found["debug"], "top_score": selected[0]["score"]},
    )

