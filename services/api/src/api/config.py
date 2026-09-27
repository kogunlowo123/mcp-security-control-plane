"""
Application configuration via pydantic-settings.
All values can be overridden by environment variables.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "MCP Security Control Plane API"
    app_version: str = "0.1.0"
    debug: bool = False

    # JWT
    jwt_secret: str = "change-me-in-production-32-char-min"
    jwt_algorithm: str = "HS256"
    jwt_audience: str = "mcp-security-control-plane"

    # OPA
    opa_url: str = "http://opa:8181"
    opa_timeout_seconds: float = 2.0

    # PostgreSQL
    postgres_dsn: str = "postgresql://postgres:postgres@postgres:5432/mcp_security"

    # OpenTelemetry
    otlp_endpoint: str = "http://otel-collector:4317"
    otlp_insecure: bool = True
    tracing_enabled: bool = True

    # Rate limiting
    rate_limit_requests: int = 100
    rate_limit_window_seconds: int = 60

    # CORS
    cors_origins: list[str] = ["*"]
    cors_allow_credentials: bool = True
    cors_allow_methods: list[str] = ["*"]
    cors_allow_headers: list[str] = ["*"]


# Module-level singleton; import this throughout the application.
settings = Settings()
