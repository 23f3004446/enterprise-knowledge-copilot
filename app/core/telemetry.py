from __future__ import annotations

import os
from contextlib import contextmanager
from time import perf_counter
from typing import Iterator

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from fastapi import Response
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

REQUEST_COUNT = Counter("request_count", "Total HTTP requests")
ERROR_COUNT = Counter("error_count", "Total HTTP errors")
REQUEST_LATENCY = Histogram("request_latency_seconds", "Request latency in seconds")
RETRIEVAL_LATENCY = Histogram("retrieval_latency_seconds", "Retrieval latency in seconds")
CACHE_HITS = Counter("cache_hits_total", "Number of cache hits")
CACHE_MISSES = Counter("cache_misses_total", "Number of cache misses")
CHAT_QUERY_COUNT = Counter("chat_queries_total", "Number of chat questions processed")
ABSTENTION_COUNT = Counter("rag_abstentions_total", "Number of questions without supporting evidence")
GENERATION_LATENCY = Histogram("llm_generation_latency_seconds", "LLM or extractive answer generation latency")
RETRIEVED_CHUNKS = Histogram("retrieved_chunks_per_query", "Retrieved evidence chunks per question")
LLM_INPUT_TOKENS = Counter("llm_input_tokens_total", "Provider-reported LLM input tokens")
LLM_OUTPUT_TOKENS = Counter("llm_output_tokens_total", "Provider-reported LLM output tokens")
LLM_COST_USD = Counter("llm_cost_usd_total", "Estimated LLM cost from explicitly configured token prices")
TRACER = trace.get_tracer("enterprise_knowledge_copilot")


def instrument_fastapi(app) -> None:
    provider = TracerProvider(
        resource=Resource.create({SERVICE_NAME: "enterprise-knowledge-copilot"})
    )
    if os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)


@contextmanager
def measure_latency(histogram: Histogram) -> Iterator[None]:
    start = perf_counter()
    try:
        yield
    finally:
        histogram.observe(perf_counter() - start)


def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
