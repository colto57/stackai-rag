from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


@dataclass
class StorageStats:
    total_documents: int
    total_chunks: int


class JsonStore:
    def __init__(self, data_dir: str) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.data_dir / "index.json"
        self.docs_dir = self.data_dir / "docs"
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        if not self.index_path.exists():
            self._write_index({"documents": [], "chunks": []})

    def _read_index(self) -> dict[str, Any]:
        with self.index_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _write_index(self, payload: dict[str, Any]) -> None:
        tmp_path = self.index_path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=True, indent=2)
        os.replace(tmp_path, self.index_path)

    def save_pdf(self, filename: str, content: bytes) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        safe_name = "".join(c for c in filename if c.isalnum() or c in {"-", "_", "."}) or "file.pdf"
        doc_id = f"doc_{timestamp}"
        save_path = self.docs_dir / f"{doc_id}_{safe_name}"
        with save_path.open("wb") as f:
            f.write(content)
        return str(save_path)

    def upsert_document(self, document: dict[str, Any], chunks: list[dict[str, Any]]) -> None:
        with self._lock:
            index = self._read_index()
            index["documents"] = [d for d in index["documents"] if d["doc_id"] != document["doc_id"]]
            index["chunks"] = [c for c in index["chunks"] if c["doc_id"] != document["doc_id"]]
            index["documents"].append(document)
            index["chunks"].extend(chunks)
            self._write_index(index)

    def all_chunks(self) -> list[dict[str, Any]]:
        return self._read_index().get("chunks", [])

    def list_documents(self) -> list[dict[str, Any]]:
        index = self._read_index()
        docs = index.get("documents", [])
        docs.sort(key=lambda d: d.get("created_at", ""), reverse=True)
        return docs

    def has_file_hash(self, file_hash: str) -> bool:
        if not file_hash:
            return False
        docs = self._read_index().get("documents", [])
        return any(d.get("file_hash") == file_hash for d in docs)

    def clear_all(self) -> None:
        with self._lock:
            self._write_index({"documents": [], "chunks": []})
            for path in self.docs_dir.glob("*"):
                if path.is_file():
                    path.unlink(missing_ok=True)

    def stats(self) -> StorageStats:
        index = self._read_index()
        return StorageStats(
            total_documents=len(index.get("documents", [])),
            total_chunks=len(index.get("chunks", [])),
        )

