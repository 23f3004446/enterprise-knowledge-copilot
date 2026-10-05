from __future__ import annotations

import json
import math
import statistics
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.core.llm import ExtractiveClient
from app.core.permissions import can_access, restricted_document_requested
from app.db.database import SessionLocal, init_db
from app.services.retrieval import RetrievalService


def expected_source_recall(expected_sources: set[str], retrieved_sources: list[str]) -> float:
    expected = {source.lower() for source in expected_sources}
    if not expected:
        return 0.0
    retrieved = [source.lower() for source in retrieved_sources]
    found = sum(any(expected_name in source for source in retrieved) for expected_name in expected)
    return found / len(expected)


def reciprocal_rank(expected_sources: set[str], retrieved_sources: list[str]) -> float:
    expected = {source.lower() for source in expected_sources}
    for position, source in enumerate(retrieved_sources, start=1):
        if any(name in source.lower() for name in expected):
            return 1 / position
    return 0.0


def run_evaluation() -> dict:
    question_path = Path(settings.evaluation_questions_path)
    cases = json.loads(question_path.read_text(encoding="utf-8"))
    init_db()
    retrieval = RetrievalService()
    answerable = []
    latencies = []
    retrieved_count = 0
    unauthorized_count = 0
    unanswerable_retrievals = 0
    extractive_grounding_checks = []

    with SessionLocal() as db:
        warmup_started = time.perf_counter()
        retrieval.embed_query("evaluation model warm-up")
        warmup_case = next((case for case in cases if case["answerable"]), None)
        if warmup_case is not None:
            retrieval.search(
                db,
                warmup_case["query"],
                role=warmup_case["role"],
                top_k=5,
                rerank=True,
            )
        model_warmup_latency_ms = (time.perf_counter() - warmup_started) * 1000
        for case in cases:
            started = time.perf_counter()
            if restricted_document_requested(db, case["query"], case["role"]):
                results = []
            else:
                results = retrieval.search(db, case["query"], role=case["role"], top_k=5, rerank=True)
            latencies.append((time.perf_counter() - started) * 1000)
            retrieved_count += len(results)
            unauthorized_count += sum(not can_access(case["role"], result.role) for result in results)
            if case["answerable"]:
                expected = {name.lower() for name in case["expected_sources"]}
                retrieved_sources = [result.source for result in results]
                expected_recall = expected_source_recall(expected, retrieved_sources)
                answerable.append(
                    {
                        "hit": expected_recall > 0,
                        "recall": expected_recall,
                        "reciprocal_rank": reciprocal_rank(expected, retrieved_sources),
                    }
                )
                if expected_recall > 0:
                    evidence = [
                        {
                            "text": result.text,
                            "document_name": result.source,
                            "page": result.page,
                            "chunk_id": result.chunk_id,
                        }
                        for result in results
                    ]
                    answer = ExtractiveClient().answer(case["query"], evidence).answer
                    extractive_grounding_checks.append(
                        all(result.text in answer for result in results)
                    )
            elif results:
                unanswerable_retrievals += 1

    count = len(answerable)
    result = {
        "questions_total": len(cases),
        "answerable_questions": count,
        "hit_at_5": sum(item["hit"] for item in answerable) / count if count else 0.0,
        "recall_at_5": sum(item["recall"] for item in answerable) / count if count else 0.0,
        "mrr": sum(item["reciprocal_rank"] for item in answerable) / count if count else 0.0,
        "unanswerable_questions": len(cases) - count,
        "unanswerable_false_positive_rate": (
            unanswerable_retrievals / (len(cases) - count) if len(cases) > count else 0.0
        ),
        "p50_latency_ms": statistics.median(latencies) if latencies else 0.0,
        "p95_latency_ms": (
            sorted(latencies)[max(0, math.ceil(0.95 * len(latencies)) - 1)]
            if latencies
            else 0.0
        ),
        "model_warmup_latency_ms": model_warmup_latency_ms,
        "retrieved_chunks_total": retrieved_count,
        "unauthorized_chunks_total": unauthorized_count,
        "unauthorized_retrieval_rate": unauthorized_count / retrieved_count if retrieved_count else 0.0,
        "unanswerable_cases_with_retrieval": unanswerable_retrievals,
        "extractive_grounding_check": {
            "method": "exact evidence text inclusion in extractive answer (not an independent semantic judge)",
            "questions_checked": len(extractive_grounding_checks),
            "evidence_coverage_rate": (
                sum(extractive_grounding_checks) / len(extractive_grounding_checks)
                if extractive_grounding_checks
                else None
            ),
        },
        "faithfulness_judge_score": None,
        "cost": "not measured; extractive local mode or provider pricing is not configured",
        "model": settings.embedding_model,
    }
    output_path = question_path.parent / "results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(run_evaluation(), indent=2))
