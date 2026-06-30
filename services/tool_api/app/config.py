from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    database_url: str = "postgresql+asyncpg://omni:omnipass@localhost:5432/omnisupport"
    otel_service_name: str = "tool_api"
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"
    release_id: str = "dev-local"
    metric_registry_path: str = "/workspace/analytics/metric_registry_v1.yml"
    skill_registry_path: str = "/workspace/skills"
    tool_contracts_path: str = "/workspace/contracts/tools/tools"
    tool_contract_schema_path: str = "/workspace/contracts/tools/tool_contract_schema.json"

    # HITL 配置
    hitl_webhook_url: str = ""   # Week10 接入
    hitl_timeout_sec: int = 300


settings = Settings()
