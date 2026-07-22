from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    database_url: str = "postgresql://omni:omnipass@localhost:5432/omnisupport"
    rag_api_url: str = "http://localhost:8000"
    tool_api_url: str = "http://localhost:8001"
    internal_service_token: str = "dev-internal-token-change-in-prod"
    auth_signing_key: str = "dev-auth-key-change-in-prod"
    auth_token_ttl_seconds: int = 28800
    demo_tenant_id: str = "northstar-demo"
    demo_agent_email: str = "agent@northstar.demo"
    demo_agent_password: str = "Agent@2026"
    demo_admin_email: str = "admin@northstar.demo"
    demo_admin_password: str = "Admin@2026"
    enable_demo_users: bool = True
    release_id: str = "capstone-dev-local"
    release_environment: str = "dev"
    data_release_id: str = "data-capstone-v1"
    prompt_release_id: str = "prompt-capstone-v1"
    otel_service_name: str = "copilot_api"
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"
    otel_enabled: bool = True
    otel_project_name: str = "omnisupport-copilot"
    otel_environment: str = "dev"
    otel_sample_ratio: float = 1.0


settings = Settings()
