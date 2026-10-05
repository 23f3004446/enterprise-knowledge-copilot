from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import faiss
import numpy as np
from rank_bm25 import BM25Okapi
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.permissions import allowed_access_levels
from app.db.models import DocumentChunk

os.environ.setdefault("USE_TF", "0")
_model_lock = threading.Lock()


@dataclass(frozen=True)
class RetrievalResult:
    chunk_id: str
    document_id: str
    text: str
    source: str
    page: int | None
    role: str
    department: str
    source_type: str
    score: float
    vector_score: float = 0.0
    bm25_score: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class RetrievalService:
    def __init__(self) -> None:
        self._embedder: Any = None
        self._reranker: Any = None

    def _get_embedder(self):
        if self._embedder is None:
            with _model_lock:
                if self._embedder is None:
                    from sentence_transformers import SentenceTransformer

                    self._embedder = SentenceTransformer(settings.embedding_model)
        return self._embedder

    def _get_reranker(self):
        if self._reranker is None:
            with _model_lock:
                if self._reranker is None:
                    from sentence_transformers import CrossEncoder

                    self._reranker = CrossEncoder(settings.reranker_model)
        return self._reranker

    def embed_query(self, query: str) -> np.ndarray:
        vector = self._get_embedder().encode(
            [query], convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False
        )
        return np.asarray(vector[0], dtype="float32")

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [token.lower().strip(".,!?;:()[]{}\"'") for token in text.split() if token.strip()]

    @staticmethod
    def _allowed_chunks(db: Session, role: str) -> list[DocumentChunk]:
        access = allowed_access_levels(role)
        if not access:
            return []
        return (
            db.query(DocumentChunk)
            .filter(DocumentChunk.access_level.in_(access))
            .order_by(DocumentChunk.document_id, DocumentChunk.page, DocumentChunk.id)
            .all()
        )

    def _vector_hits(
        self, chunks: list[DocumentChunk], query: str, top_k: int, role: str
    ) -> list[tuple[DocumentChunk, float]]:
        if not chunks:
            return []
        index_root = Path(settings.index_dir).resolve()
        index_root.mkdir(parents=True, exist_ok=True)
        role_name = role.lower()
        index_path = index_root / f"{role_name}.faiss"
        mapping_path = index_root / f"{role_name}.json"
        signature = hashlib.sha256(
            "\n".join(f"{c.chunk_id}:{c.content}" for c in chunks).encode("utf-8")
        ).hexdigest()
        mapping: dict = {}
        index = None
        if index_path.exists() and mapping_path.exists():
            try:
                mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
                if mapping.get("signature") == signature:
                    loaded = faiss.read_index(str(index_path))
                    if loaded.ntotal == len(mapping.get("chunk_ids", [])):
                        index = loaded
            except (OSError, ValueError, RuntimeError):
                index = None

        if index is None:
            texts = [chunk.content for chunk in chunks]
            vectors = self._get_embedder().encode(
                texts, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False
            )
            vectors = np.asarray(vectors, dtype="float32")
            index = faiss.IndexFlatIP(vectors.shape[1])
            index.add(vectors)
            mapping = {"signature": signature, "chunk_ids": [chunk.chunk_id for chunk in chunks]}
            faiss.write_index(index, str(index_path))
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")

        query_vector = self.embed_query(query)[None, :]
        scores, indices = index.search(np.asarray(query_vector, dtype="float32"), min(top_k, len(chunks)))
        by_id = {chunk.chunk_id: chunk for chunk in chunks}
        results = []
        for score, position in zip(scores[0], indices[0]):
            if position < 0:
                continue
            chunk_id = mapping["chunk_ids"][position]
            chunk = by_id.get(chunk_id)
            if chunk is not None:
                results.append((chunk, float(score)))
        return results

    def search(
        self,
        db: Session,
        query: str,
        role: str,
        top_k: int | None = None,
        rerank: bool = True,
    ) -> list[RetrievalResult]:
        if not query.strip():
            return []
        k = top_k or settings.rerank_top_k
        # Permission filtering happens before either BM25 or vector retrieval.
        chunks = self._allowed_chunks(db, role)
        if not chunks:
            return []

        tokenized = [self._tokenize(chunk.content) for chunk in chunks]
        bm25 = BM25Okapi(tokenized)
        bm25_scores = bm25.get_scores(self._tokenize(query))
        query_tokens = set(self._tokenize(query))
        lexical_positions = [
            i for i, tokens in enumerate(tokenized) if query_tokens.intersection(tokens)
        ]
        if lexical_positions:
            minimum = min(float(bm25_scores[position]) for position in lexical_positions)
            normalized_lexical = {
                position: float(bm25_scores[position]) - minimum + 1e-6
                for position in lexical_positions
            }
            bm25_order = sorted(
                lexical_positions,
                key=lambda position: normalized_lexical[position],
                reverse=True,
            )[: settings.bm25_top_k]
        else:
            normalized_lexical = {}
            bm25_order = []
        bm25_by_id = {
            chunks[int(position)].chunk_id: normalized_lexical[int(position)]
            for position in bm25_order
        }

        vector_by_id = dict(
            (chunk.chunk_id, (chunk, score))
            for chunk, score in self._vector_hits(chunks, query, settings.vector_top_k, role)
        )
        max_bm25 = max(bm25_by_id.values(), default=0.0)
        candidates: dict[str, tuple[DocumentChunk, float, float]] = {}
        for position, (chunk, score) in enumerate(vector_by_id.values()):
            candidates[chunk.chunk_id] = (chunk, score * settings.vector_weight, 0.0)
        by_id = {chunk.chunk_id: chunk for chunk in chunks}
        for chunk_id, raw_score in bm25_by_id.items():
            chunk = by_id[chunk_id]
            old = candidates.get(chunk_id, (chunk, 0.0, 0.0))
            normalized = raw_score / max_bm25 if max_bm25 else 0.0
            candidates[chunk_id] = (
                chunk,
                old[1],
                normalized * settings.bm25_weight,
            )

        fused = [
            RetrievalResult(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                text=chunk.content,
                source=chunk.document_name,
                page=chunk.page,
                role=chunk.access_level,
                department=chunk.department,
                source_type=chunk.source_type,
                score=vector_score + bm25_score,
                vector_score=vector_score,
                bm25_score=bm25_score,
            )
            for chunk, vector_score, bm25_score in candidates.values()
        ]
        fused.sort(key=lambda item: item.score, reverse=True)
        fused = [item for item in fused if item.score >= settings.evidence_min_score]
        candidate_limit = max(k, settings.vector_top_k, settings.bm25_top_k)
        fused = fused[:candidate_limit]

        if rerank and fused:
            scores = self._get_reranker().predict(
                [(query, result.text) for result in fused], show_progress_bar=False
            )
            fused = [
                RetrievalResult(**{**result.to_dict(), "score": float(score)})
                for result, score in zip(fused, scores)
            ]
            fused.sort(key=lambda item: item.score, reverse=True)
            fused = [item for item in fused if item.score >= settings.rerank_min_score]
        return fused[:k]

    def build_indexes(self, db: Session) -> dict[str, int]:
        counts = {}
        for role in ("EMPLOYEE", "MANAGER", "ADMIN"):
            allowed = self._allowed_chunks(db, role)
            self._vector_hits(allowed, "index build", 1, role)
            counts[role] = len(allowed)
        return counts
