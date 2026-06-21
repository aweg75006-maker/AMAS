from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.core.exceptions import ConfigurationError


BACKEND_DIR = Path(__file__).resolve().parents[2]
APP_DIR = BACKEND_DIR / "app"


class Settings(BaseSettings):
    """Centralized runtime settings for the backend service."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Literal["local", "dev", "staging", "prod"] = "local"
    app_name: str = "IRIS Agent API"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_reload: bool = True

    cors_allow_origins: str = "*"

    openai_api_base: Optional[str] = None
    openai_api_key: Optional[SecretStr] = None
    llm_fast_model: str = "qwen3-max"
    llm_smart_model: str = "deepseek-r1"
    llm_fast_temperature: float = 0.7
    llm_smart_temperature: float = 0.0

    tavily_api_key: Optional[SecretStr] = None
    tavily_search_depth: str = "basic"
    tavily_max_results: int = 3

    dashscope_api_key: Optional[SecretStr] = None

    redis_url: str = "redis://localhost:6379/0"
    redis_enabled: bool = True
    redis_session_ttl: int = 604_800
    redis_turn_full_ttl: int = 259_200
    redis_checkpoint_ttl: int = 604_800

    knowledge_metadata_backend: Literal["redis", "postgres"] = "redis"
    postgres_dsn: Optional[SecretStr] = None
    postgres_auto_migrate: bool = True

    seed_default_user_enabled: bool = False
    seed_default_tenant_name: str = "默认租户"
    seed_default_username: Optional[str] = None
    seed_default_password: Optional[SecretStr] = None

    jwt_secret_key: Optional[SecretStr] = None
    jwt_access_token_ttl_seconds: int = 86_400

    rate_limit_enabled: bool = True
    rate_limit_login_capacity: int = 5
    rate_limit_login_refill_per_second: float = 1 / 60
    rate_limit_chat_capacity: int = 20
    rate_limit_chat_refill_per_second: float = 1 / 15
    rate_limit_upload_capacity: int = 10
    rate_limit_upload_refill_per_second: float = 1 / 60
    rate_limit_default_capacity: int = 60
    rate_limit_default_refill_per_second: float = 1

    total_token_budget: int = 128_000

    rag_chroma_db_path: Path = Field(default=APP_DIR / "rag" / "chroma_db")
    rag_upload_dir: Path = Field(default=APP_DIR / "rag" / "uploads")
    rag_embedding_model: str = "text-embedding-v4"
    rag_reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    rag_chunk_size: int = 500
    rag_chunk_overlap: int = 50
    rag_top_k: int = 5
    rag_fetch_k: int = 20

    upload_max_files: int = 5
    upload_max_file_size_bytes: int = 20 * 1024 * 1024
    upload_allowed_extensions: str = ".pdf"
    upload_allowed_content_types: str = "application/pdf"

    def secret_value(self, value: Optional[SecretStr]) -> Optional[str]:
        return value.get_secret_value() if value else None

    def require_openai_api_key(self) -> str:
        value = self.secret_value(self.openai_api_key)
        if not value:
            raise ConfigurationError("缺少 OPENAI_API_KEY，请在 backend/.env 或环境变量中配置。")
        return value

    def require_tavily_api_key(self) -> str:
        value = self.secret_value(self.tavily_api_key)
        if not value:
            raise ConfigurationError("缺少 TAVILY_API_KEY，请在 backend/.env 或环境变量中配置。")
        return value

    def require_dashscope_api_key(self) -> str:
        value = self.secret_value(self.dashscope_api_key)
        if not value:
            raise ConfigurationError("缺少 DASHSCOPE_API_KEY，请在 backend/.env 或环境变量中配置。")
        return value

    def cors_origins(self) -> list[str]:
        if self.cors_allow_origins.strip() == "*":
            return ["*"]
        return [
            origin.strip()
            for origin in self.cors_allow_origins.split(",")
            if origin.strip()
        ]

    def safe_summary(self) -> dict[str, object]:
        return {
            "environment": self.environment,
            "app_name": self.app_name,
            "app_host": self.app_host,
            "app_port": self.app_port,
            "redis_enabled": self.redis_enabled,
            "redis_url": self.redis_url,
            "knowledge_metadata_backend": self.knowledge_metadata_backend,
            "postgres_configured": bool(self.postgres_dsn),
            "postgres_auto_migrate": self.postgres_auto_migrate,
            "seed_default_user_enabled": self.seed_default_user_enabled,
            "seed_default_username_configured": bool(self.seed_default_username),
            "seed_default_password_configured": bool(self.seed_default_password),
            "jwt_secret_configured": bool(self.jwt_secret_key),
            "jwt_access_token_ttl_seconds": self.jwt_access_token_ttl_seconds,
            "rate_limit_enabled": self.rate_limit_enabled,
            "rate_limit_login_capacity": self.rate_limit_login_capacity,
            "rate_limit_chat_capacity": self.rate_limit_chat_capacity,
            "rate_limit_upload_capacity": self.rate_limit_upload_capacity,
            "llm_fast_model": self.llm_fast_model,
            "llm_smart_model": self.llm_smart_model,
            "dashscope_configured": bool(self.dashscope_api_key),
            "tavily_configured": bool(self.tavily_api_key),
            "total_token_budget": self.total_token_budget,
            "rag_chroma_db_path": str(self.rag_chroma_db_path),
            "rag_upload_dir": str(self.rag_upload_dir),
            "upload_max_files": self.upload_max_files,
            "upload_max_file_size_bytes": self.upload_max_file_size_bytes,
            "upload_allowed_extensions": self.upload_allowed_extensions,
        }

    def jwt_secret(self) -> str:
        value = self.secret_value(self.jwt_secret_key)
        if value:
            return value
        if self.environment == "prod":
            raise ConfigurationError("生产环境必须配置 JWT_SECRET_KEY。")
        return "local-dev-insecure-jwt-secret"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
