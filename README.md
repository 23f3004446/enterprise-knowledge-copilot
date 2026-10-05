# Enterprise Knowledge Copilot

An interview-demo enterprise knowledge assistant built on an existing FastAPI + Streamlit project. It ingests synthetic policy documents, enforces role permissions in the backend, retrieves authorized evidence using BM25 and sentence-transformer embeddings in FAISS, optionally reranks it with a cross-encoder, and returns evidence with source citations.

## Business problem and solution

Employees lose time searching internal policies. Ordinary RAG can disclose a document to someone who is not permitted to read it. This application applies document access filtering before BM25/vector retrieval and before answer generation. Its local default answer mode is explicitly **extractive** rather than pretending to be a hosted LLM. Configure an OpenAI-compatible provider for generated answers.

## Architecture and data flow

```text
Browser -> Streamlit -> FastAPI/JWT -> role scope -> authorized SQL chunks
                                               |-> BM25 (exact terms)
                                               |-> sentence-transformer -> role-scoped FAISS
                                               -> weighted hybrid fusion -> cross-encoder reranker
                                               -> authorization-scoped semantic cache
                                               -> extractive local answer OR configured LLM
                                               -> citations from chunk metadata
```

Authorization scopes:

| User role | Accessible document levels |
|---|---|
| EMPLOYEE | PUBLIC, EMPLOYEE |
| MANAGER | PUBLIC, EMPLOYEE, MANAGER |
| ADMIN | PUBLIC, EMPLOYEE, MANAGER, ADMIN |

The user's prompt cannot expand this scope. Retrieved context is constructed only from the filtered chunk rows. Cache entries are separated by role, permission-scope hash, authorized-corpus revision, embedding/reranker configuration, retrieval weights and LLM provider/model/base URL. Cache hits do not claim new token usage or estimated cost.

## Technology

- Python 3.11, FastAPI, SQLAlchemy, SQLite, PyJWT
- Streamlit UI
- pypdf parsing with PDF page metadata; TXT and Markdown parsing
- sentence-transformers embeddings, FAISS inner-product indexes, rank-bm25
- sentence-transformers cross-encoder reranking
- Prometheus-compatible `/metrics`, OpenTelemetry FastAPI/request spans and retrieval/generation spans

## Installation and configuration

Use Python 3.11. The first embedding/reranker use may download the configured Hugging Face models and therefore needs internet access. The local extractive mode needs no LLM API key.

```powershell
cd C:\path\to\enterprise-knowledge-copilot
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Set a random `JWT_SECRET_KEY` of at least 32 bytes before deployment. In development only, a too-short placeholder is replaced with a clearly marked development key. Never use that fallback in production. `.env` is ignored by Git and excluded from the Docker build context.

Important settings are documented in `.env.example`: `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL`, `EMBEDDING_MODEL`, `RERANKER_MODEL`, `RERANK_MIN_SCORE`, `CHUNK_SIZE`, `CHUNK_OVERLAP`, `VECTOR_TOP_K`, `BM25_TOP_K`, `RERANK_TOP_K`, `VECTOR_WEIGHT`, `BM25_WEIGHT`, `CACHE_ENABLED`, `CACHE_TTL_SECONDS`, `RAW_DOCUMENTS_DIR`, and `INDEX_DIR`. `RERANK_MIN_SCORE` is a corpus/model-dependent abstention threshold; the demo value is not claimed to generalize.

For OpenAI-compatible generation, set `LLM_PROVIDER=openai`, `LLM_API_KEY`, and optionally `LLM_BASE_URL`; the model uses temperature zero and receives only retrieved authorized context. Provider token counts are returned and exported to Prometheus when available. Set `LLM_INPUT_COST_PER_1M` and `LLM_OUTPUT_COST_PER_1M` to the provider's current USD prices per million tokens to enable per-response and cumulative estimated-cost reporting; otherwise cost remains `null`/unreported. Prices are provider/model-specific and must be configured by the operator.

OpenTelemetry spans are created for HTTP requests, retrieval, and generation. To export traces, set `OTEL_EXPORTER_OTLP_ENDPOINT` to an OTLP/HTTP collector endpoint (for example, an OpenTelemetry Collector); if it is unset, spans are not exported. Sensitive prompt/document contents are not added as span attributes.

## Run locally

In terminal 1:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --reload --port 8000
```

In terminal 2:

```powershell
.\.venv\Scripts\Activate.ps1
$env:API_BASE = "http://127.0.0.1:8000"
python -m streamlit run frontend/streamlit_app.py --server.port 8502
```

Open http://localhost:8502. API docs are at http://localhost:8000/docs and health at `/health`.

Development-only local accounts:

| Email | Password |
|---|---|
| employee@example.com | demo_employee_password |
| manager@example.com | demo_manager_password |
| admin@example.com | demo_admin_password |

These fixed demo credentials are seeded only when `APP_ENV=development`. In other environments, set `INITIAL_EMPLOYEE_PASSWORD`, `INITIAL_MANAGER_PASSWORD`, and `INITIAL_ADMIN_PASSWORD` as deployment secrets to create the corresponding initial accounts. Do not reuse the public development passwords.

## Documents and indexes

Synthetic, non-confidential demo policies are under `data/raw/{PUBLIC,EMPLOYEE,MANAGER,ADMIN}/`. Application startup imports those documents idempotently. To ingest additional files, place supported PDF/TXT/Markdown files under one of the role folders, then run:

```powershell
python scripts/ingest.py
python scripts/build_index.py
```

The Admin UI can also upload a PDF, TXT or Markdown file, set its access level and department, and index it immediately. The upload limit is 20 MiB. PDF chunks retain extracted page numbers; TXT/Markdown citations correctly omit page numbers.

`scripts/build_index.py` writes one FAISS index and metadata map per role under `data/index/`. Indexes are rebuilt automatically when the authorized chunk set changes. BM25 is calculated from the real authorized chunk corpus at query time. Admin uploads are stored separately under `data/uploads/` (ignored by Git to avoid accidentally committing private documents) and re-ingested at startup.

## API

- `GET /health`
- `POST /auth/login`, `GET /auth/me`
- `GET /documents`, `POST /documents/upload` (multipart, admin only), `POST /documents/ingest` (admin only)
- `POST /search`, `POST /chat`
- `GET /metrics`
- `GET /admin/overview`, `POST /evaluation/run`, `GET /evaluation/results` (admin only)

## Evaluation and tests

The 30-question dataset at `data/evaluation/questions.json` includes factual, exact-term, semantic, permission-sensitive, unanswerable and adversarial prompts. Run the actual retrieval evaluation with:

```powershell
python scripts/evaluate.py
```

It measures Hit@5, expected-source Recall@5, MRR, warmed retrieval p50/p95, model warm-up time, unauthorized-chunk rate and unanswerable false-positive rate from executed retrievals. It also performs a deterministic exact-evidence inclusion check for the extractive answer path; this is not an independent semantic faithfulness score. A separate LLM judge/faithfulness score is not claimed. The generated `data/evaluation/results.json` is not committed; run it to obtain machine-specific results.

Run tests:

```powershell
python -m pytest -q
```

## Docker

After creating `.env` from `.env.example`:

```powershell
docker compose up --build
```

Open http://localhost:8502. SQLite database, raw uploads and indexes are persisted in `./data`. Stop with `Ctrl+C`, then `docker compose down`.
The Dockerfile installs the CPU-only PyTorch wheel before sentence-transformers to avoid bundling unused NVIDIA/CUDA libraries; dependency downloads use an extended timeout for slower connections.

## Free portfolio deployment

The Streamlit UI and FastAPI/RAG API are separate deployments. Streamlit Community Cloud runs `frontend/streamlit_app.py` and installs only the frontend dependencies from `frontend/requirements.txt`; set its `API_BASE` secret to the deployed API's HTTPS origin. The UI uses `API_BASE` from the process environment or Streamlit secrets, falling back to `http://127.0.0.1:8000` only for local development. Streamlit sends API requests server-side, so browser CORS is not needed for this architecture.

`render.yaml` defines a free Render Python web service for `app.main:app`. Create it from the public GitHub repository using Render's Blueprint flow and enter three unique initial passwords when prompted for `INITIAL_EMPLOYEE_PASSWORD`, `INITIAL_MANAGER_PASSWORD`, and `INITIAL_ADMIN_PASSWORD`. Render generates `JWT_SECRET_KEY`. These values remain platform secrets; do not put them in GitHub or Streamlit secrets. The fixed demo passwords are created only in development mode.

The backend runtime installs CPU-only PyTorch separately and uses `requirements-backend.txt`, which excludes frontend and test packages but retains FAISS, sentence-transformers, embeddings, BM25, reranking, authentication, and the API dependencies. Models load on the first retrieval request rather than during process startup. The first query may take several minutes while model files download.

Free hosting is for portfolio/testing use, not production: Render Free provides 512 MB RAM, spins down after inactivity, and has an ephemeral filesystem. The local SQLite database, uploads, indexes, and downloaded models can be lost after a restart or spin-down; bundled sample documents are re-ingested at startup and indexes can be rebuilt. The full embedding and reranker models may exceed the free instance's memory during a real query. If that occurs, a larger paid service or a different host with sufficient free RAM is required; do not silently disable vector retrieval or reranking to fit the free tier.

## Limitations and interview explanation

- Local default mode is evidence extraction, not generative AI. This is explicit and avoids fabricating model capability. A configured compatible LLM enables grounded generation.
- Sentence-transformer and cross-encoder model artifacts must be downloaded on first use unless already cached.
- FAISS indexes are local CPU indexes; SQLite and a single process suit a demo, not a multi-node production deployment.
- A local trace collector is not included; OTLP export requires an operator-provided endpoint. Distributed cache/database, production identity federation, document malware scanning, OCR for scanned PDFs, robust migrations, and independent model-judge faithfulness evaluation remain production follow-ups.
- Retrieval results and evaluation scores depend on this synthetic corpus and are measurements, not claims about an enterprise corpus.

Interview summary: “I built a role-aware document assistant where access control precedes retrieval and generation. It combines exact lexical matching with local semantic vectors, fuses and reranks authorized candidates, cites real source metadata, abstains without evidence, and isolates semantic cache entries by authorization context.”
