from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.cache import SemanticAnswerCache
from app.core.config import settings
from app.core.llm import ABSTENTION, get_llm_client
from app.core.logging import logger
from app.core.permissions import allowed_access_levels, restricted_document_requested
from app.core.security import get_current_user_from_credentials
from app.core.telemetry import (
    ABSTENTION_COUNT,
    CACHE_HITS,
    CACHE_MISSES,
    CHAT_QUERY_COUNT,
    GENERATION_LATENCY,
    LLM_COST_USD,
    LLM_INPUT_TOKENS,
    LLM_OUTPUT_TOKENS,
    RETRIEVAL_LATENCY,
    RETRIEVED_CHUNKS,
    TRACER,
)
from app.db.database import get_db
from app.db.models import DocumentChunk
from app.schemas.schemas import ChatRequest, ChatResponse, SearchRequest
from app.services.retrieval import RetrievalService

router = APIRouter(tags=["chat"])
retrieval_service = RetrievalService()
answer_cache = SemanticAnswerCache(ttl_seconds=settings.cache_ttl_seconds)


def _retrieve(db: Session, query: str, role: str, top_k: int):
    started = time.perf_counter()
    results = retrieval_service.search(db, query, role=role, top_k=top_k)
    RETRIEVAL_LATENCY.observe(time.perf_counter() - started)
    return results


def _corpus_revision(db: Session, role: str) -> str:
    allowed = allowed_access_levels(role)
    count, maximum_id, latest_chunk = (
        db.query(
            func.count(DocumentChunk.id),
            func.max(DocumentChunk.id),
            func.max(DocumentChunk.created_at),
        )
        .filter(DocumentChunk.access_level.in_(allowed))
        .one()
    )
    latest = latest_chunk.isoformat() if latest_chunk else ""
    return f"{count}:{maximum_id}:{latest}"


@router.post("/search")
def search(
    req: SearchRequest,
    current_user: dict = Depends(get_current_user_from_credentials),
    db: Session = Depends(get_db),
) -> dict:
    role = current_user.get("role", "")
    hits = _retrieve(db, req.query, role, req.top_k)
    return {"results": [result.to_dict() for result in hits], "count": len(hits)}


@router.post("/chat", response_model=ChatResponse)
def chat(
    req: ChatRequest,
    current_user: dict = Depends(get_current_user_from_credentials),
    db: Session = Depends(get_db),
) -> ChatResponse:
    if not req.question.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Question is required.")
    role = current_user.get("role", "")
    if role not in {"EMPLOYEE", "MANAGER", "ADMIN"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="A recognized role is required.")
    started = time.perf_counter()
    query_id = str(uuid.uuid4())
    CHAT_QUERY_COUNT.inc()
    if restricted_document_requested(db, req.question, role):
        ABSTENTION_COUNT.inc()
        return ChatResponse(
            answer=ABSTENTION,
            sources=[],
            citations=[],
            evidence="requested content is outside the user's document permissions",
            latency_ms=(time.perf_counter() - started) * 1000,
            query_id=query_id,
            model="authorization-filter",
        )
    scope = SemanticAnswerCache.scope_key(allowed_access_levels(role))
    model_key = (
        f"{settings.embedding_model}:{settings.llm_provider}:{settings.llm_model}:"
        f"{settings.llm_base_url}:{settings.reranker_model}:{settings.vector_weight}:"
        f"{settings.bm25_weight}:{settings.vector_top_k}:{settings.bm25_top_k}:"
        f"{settings.rerank_top_k}:{settings.rerank_min_score}:{settings.evidence_min_score}:"
        f"corpus={_corpus_revision(db, role)}"
    )

    try:
        query_vector = retrieval_service.embed_query(req.question)
        if settings.cache_enabled:
            cached = answer_cache.get(query_vector, role, scope, model_key)
            if cached is not None:
                CACHE_HITS.inc()
                result = ChatResponse.model_validate(cached)
                result.cache_hit = True
                result.query_id = query_id
                result.latency_ms = (time.perf_counter() - started) * 1000
                result.input_tokens = None
                result.output_tokens = None
                result.cost_usd = None
                logger.info(
                    "chat completed query_id=%s role=%s cache_hit=true latency_ms=%.2f",
                    query_id,
                    role,
                    result.latency_ms,
                )
                return result
            CACHE_MISSES.inc()

        with TRACER.start_as_current_span("rag.retrieve") as span:
            span.set_attribute("user.role", role)
            hits = _retrieve(db, req.question, role, settings.rerank_top_k)
            span.set_attribute("rag.retrieved_chunks", len(hits))
        RETRIEVED_CHUNKS.observe(len(hits))
        if not hits:
            ABSTENTION_COUNT.inc()
            result = ChatResponse(
                answer=ABSTENTION,
                sources=[],
                citations=[],
                evidence="insufficient evidence",
                latency_ms=(time.perf_counter() - started) * 1000,
                query_id=query_id,
                model=settings.llm_provider,
            )
            if settings.cache_enabled:
                answer_cache.set(query_vector, role, scope, model_key, result.model_dump())
            logger.info(
                "chat abstained query_id=%s role=%s retrieved_chunks=0 latency_ms=%.2f",
                query_id,
                role,
                result.latency_ms,
            )
            return result

        context: list[dict[str, Any]] = [
            {
                "text": hit.text,
                "document_name": hit.source,
                "page": hit.page,
                "chunk_id": hit.chunk_id,
            }
            for hit in hits
        ]
        generation_started = time.perf_counter()
        with TRACER.start_as_current_span("rag.generate") as span:
            span.set_attribute("llm.provider", settings.llm_provider)
            generated = get_llm_client().answer(req.question, context)
            span.set_attribute("llm.model", generated.model)
            if generated.input_tokens is not None:
                span.set_attribute("llm.input_tokens", generated.input_tokens)
            if generated.output_tokens is not None:
                span.set_attribute("llm.output_tokens", generated.output_tokens)
        GENERATION_LATENCY.observe(time.perf_counter() - generation_started)
        if generated.input_tokens is not None:
            LLM_INPUT_TOKENS.inc(generated.input_tokens)
        if generated.output_tokens is not None:
            LLM_OUTPUT_TOKENS.inc(generated.output_tokens)
        cost_usd = None
        if (
            generated.input_tokens is not None
            and generated.output_tokens is not None
            and settings.llm_input_cost_per_1m is not None
            and settings.llm_output_cost_per_1m is not None
        ):
            cost_usd = (
                generated.input_tokens * settings.llm_input_cost_per_1m
                + generated.output_tokens * settings.llm_output_cost_per_1m
            ) / 1_000_000
            LLM_COST_USD.inc(cost_usd)
        citations = [
            f"[{i}] {hit.source}" + (f" — Page {hit.page}" if hit.page is not None else "")
            for i, hit in enumerate(hits, start=1)
        ]
        result = ChatResponse(
            answer=generated.answer,
            sources=[hit.source for hit in hits],
            citations=citations,
            evidence="retrieved authorized evidence",
            latency_ms=(time.perf_counter() - started) * 1000,
            query_id=query_id,
            model=generated.model,
            input_tokens=generated.input_tokens,
            output_tokens=generated.output_tokens,
            cost_usd=cost_usd,
            retrieved_chunks=[hit.to_dict() for hit in hits],
        )
        if settings.cache_enabled:
            answer_cache.set(query_vector, role, scope, model_key, result.model_dump())
        logger.info(
            "chat completed query_id=%s role=%s retrieved_chunks=%s model=%s input_tokens=%s output_tokens=%s latency_ms=%.2f",
            query_id,
            role,
            len(hits),
            generated.model,
            generated.input_tokens,
            generated.output_tokens,
            result.latency_ms,
        )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Retrieval or answer generation is unavailable: {type(exc).__name__}. Check configured model availability.",
        ) from exc
