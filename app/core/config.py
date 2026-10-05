import warnings

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    jwt_secret_key: str = "dev-only-enterprise-knowledge-copilot-key-change-before-production"
    database_url: str = "sqlite:///./data/app.db"
    api_title: str = "Enterprise Knowledge Copilot"
    api_version: str = "0.1.0"
    llm_provider: str = "mock"
    llm_api_key: str = ""
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    vector_top_k: int = 5
    bm25_top_k: int = 5
    rerank_top_k: int = 5
    chunk_size: int = 800
    chunk_overlap: int = 120
    vector_weight: float = 0.6
    bm25_weight: float = 0.4
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str = ""
    llm_input_cost_per_1m: float | None = Field(default=None, ge=0)
    llm_output_cost_per_1m: float | None = Field(default=None, ge=0)
    index_dir: str = "data/index"
    raw_documents_dir: str = "data/raw"
    uploaded_documents_dir: str = "data/uploads"
    evaluation_questions_path: str = "data/evaluation/questions.json"
    cache_enabled: bool = True
    cache_ttl_seconds: int = 300
    evidence_min_score: float = 0.15
    rerank_min_score: float = -8.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    @model_validator(mode="after")
    def validate_jwt_secret(self):
        if (
            self.app_env.lower() != "development"
            and self.jwt_secret_key.lower().startswith("replace_with_a_random_secret")
        ):
            raise ValueError("Replace the JWT_SECRET_KEY example placeholder with a unique production secret.")
        if len(self.jwt_secret_key.encode("utf-8")) < 32:
            if self.app_env.lower() != "development":
                raise ValueError("JWT_SECRET_KEY must be at least 32 bytes outside development.")
            warnings.warn(
                "JWT_SECRET_KEY is too short; using a development-only fallback. Set a random 32+ byte key before deployment.",
                RuntimeWarning,
                stacklevel=2,
            )
            self.jwt_secret_key = "dev-only-enterprise-knowledge-copilot-key-change-before-production"
        return self


settings = Settings()
