"""应用配置 — 通过环境变量注入，支持 .env 文件"""

from typing import List

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
    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-4-6"
    llm_max_tokens: int = 2048
    llm_temperature: float = 0.0

    # ── 检索 ─────────────────────────────────────────────────────────────────
    retrieval_top_k: int = 5
    retrieval_min_score: float = 0.6
    rerank_enabled: bool = True

    # ── 版本与发布 ────────────────────────────────────────────────────────────
    release_id: str = "dev-local"
    data_release_id: str = "data-v0.0.1"
    index_release_id: str = "index-v0.0.1"
    prompt_release_id: str = "prompt-v0.0.1"

    # ── OTel ────────────────────────────────────────────────────────────────
    otel_service_name: str = "rag_api"
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"
    otel_enabled: bool = True
    otel_project_name: str = "omnisupport-copilot"
    otel_environment: str = "dev"
    otel_sample_ratio: float = 1.0
    otel_capture_content: bool = False

    # ── CORS ─────────────────────────────────────────────────────────────────
    cors_origins: List[str] = ["*"]

    # ── 安全 ─────────────────────────────────────────────────────────────────
    api_secret_key: str = "dev-secret-change-in-prod"


settings = Settings()
