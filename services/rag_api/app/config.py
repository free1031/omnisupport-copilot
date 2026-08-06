"""应用配置 — 通过环境变量注入，支持 .env 文件"""

from typing import List, Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── 数据库 ──────────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://omni:omnipass@localhost:5432/omnisupport"

    # ── MinIO ───────────────────────────────────────────────────────────────
    minio_endpoint: str = "http://localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket_indexes: str = "omni-indexes"

    # ── LLM ─────────────────────────────────────────────────────────────────
    llm_provider: str = "auto"
    llm_base_url: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    deepseek_api_key: str = ""
    dashscope_api_key: str = ""
    kimi_api_key: str = ""
    moonshot_api_key: str = ""
    llm_model: str = ""
    llm_max_tokens: int = 2048
    llm_context_tokens: int = Field(default=8192, ge=2048, le=131072)
    llm_temperature: float = 0.0
    llm_timeout_seconds: float = 90.0
    llm_max_retries: int = 1

    # ── 检索 ─────────────────────────────────────────────────────────────────
    retrieval_top_k: int = 5
    retrieval_min_score: float = 0.6
    rerank_enabled: bool = True
    graph_classifier_threshold: float = 0.70
    graph_max_hops: int = 3
    graph_default_visibility_scope: str = "internal"

    # ── Query Rewrite ────────────────────────────────────────────────────────
    # auto: configured LLM with deterministic validation/fallback; otherwise
    # deterministic. `disabled` is the emergency rollback switch.
    query_rewrite_enabled: bool = True
    query_rewrite_strategy: Literal["auto", "llm", "deterministic", "disabled"] = "auto"
    query_rewrite_provider: str = ""
    query_rewrite_model: str = ""
    query_rewrite_base_url: str = ""
    query_rewrite_prompt_release_id: str = "query-rewrite-v1"
    query_rewrite_timeout_seconds: float = Field(default=6.0, gt=0.0, le=30.0)
    query_rewrite_max_attempts: int = Field(default=2, ge=1, le=3)
    query_rewrite_max_output_chars: int = Field(default=1024, ge=128, le=4096)
    query_rewrite_max_tokens: int = Field(default=256, ge=64, le=1024)
    query_rewrite_context_tokens: int = Field(default=2048, ge=1024, le=16384)
    query_rewrite_temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    query_rewrite_hyde_enabled: bool = False
    query_rewrite_redact_pii: bool = True
    query_rewrite_cache_ttl_seconds: float = Field(default=300.0, ge=0.0, le=86400.0)
    query_rewrite_cache_max_entries: int = Field(default=2048, ge=0, le=100000)
    query_rewrite_circuit_failure_threshold: int = Field(default=5, ge=1, le=100)
    query_rewrite_circuit_recovery_seconds: float = Field(default=30.0, gt=0.0, le=3600.0)

    # ── 版本与发布 ────────────────────────────────────────────────────────────
    release_id: str = "dev-local"
    data_release_id: str = "data-v0.0.1"
    index_release_id: str = "index-v0.0.1"
    prompt_release_id: str = "prompt-v0.0.1"
    graph_release_id: str = "graph-week13-dev-v1"

    # ── OTel ────────────────────────────────────────────────────────────────
    otel_service_name: str = "rag_api"
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"
    otel_enabled: bool = True
    otel_project_name: str = "omnisupport-copilot"
    otel_environment: str = "dev"
    otel_sample_ratio: float = 1.0
    otel_capture_content: bool = False

    # ── CORS ─────────────────────────────────────────────────────────────────
    cors_origins: List[str] = ["http://localhost:8010", "http://127.0.0.1:8010"]

    # ── 安全 ─────────────────────────────────────────────────────────────────
    api_secret_key: str = "dev-secret-change-in-prod"
    internal_service_token: str = "dev-internal-token-change-in-prod"
    require_internal_auth: bool = False


settings = Settings()
