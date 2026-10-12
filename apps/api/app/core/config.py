from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL, make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", case_sensitive=False, hide_input_in_errors=True
    )

    app_name: str = "nexusflow-api"
    app_env: Literal["development", "test", "production"] = "development"
    app_version: str = "0.1.0"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = "nexusflow"
    postgres_user: str = "nexusflow"
    postgres_password: SecretStr | None = None
    database_url: SecretStr | None = None
    redis_host: str = "localhost"
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_url: SecretStr | None = None
    cors_origins: list[str] = ["http://localhost:3000"]
    frontend_url: str = "http://localhost:3000"
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "api", "testserver"]

    approval_expire_hours: int = Field(default=24, ge=1, le=168)
    jwt_secret_key: SecretStr
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_issuer: str = "nexusflow-api"
    jwt_audience: str = "nexusflow-web"
    access_token_expire_minutes: int = Field(default=15, ge=1, le=60)
    refresh_token_expire_days: int = Field(default=30, ge=1, le=90)
    auth_cookie_name: str = Field(default="nexusflow_refresh", pattern=r"^[A-Za-z0-9_-]+$")
    auth_cookie_secure: bool = False
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    # Only the offline deterministic provider exists in M3; live providers are a later milestone.
    llm_provider: Literal["deterministic"] = "deterministic"
    # MCP servers are reachable only at explicitly allowlisted host:port pairs (e.g. the Compose
    # demo service). Public HTTPS hosts additionally require MCP_ALLOW_PUBLIC_HOSTS=true.
    mcp_allowed_hosts: list[str] = []
    mcp_allow_public_hosts: bool = False
    mcp_connect_timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    mcp_request_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    # Background execution (M7). "queue" sends run IDs through Redis to the worker service;
    # "inline" runs the same job executor inside the request and exists for tests only.
    execution_mode: Literal["queue", "inline"] = "queue"
    queue_name: str = Field(default="nexusflow-runs", pattern=r"^[a-z0-9-]+$")
    worker_heartbeat_seconds: float = Field(default=10.0, gt=0, le=60)
    job_stale_after_seconds: float = Field(default=60.0, gt=0, le=3600)
    job_max_attempts: int = Field(default=3, ge=1, le=10)
    job_retry_base_seconds: float = Field(default=5.0, ge=0, le=300)
    job_recovery_seconds: float = Field(default=15.0, gt=0, le=600)
    # A queued job whose message is older than this is re-sent (lost Redis messages).
    job_redeliver_after_seconds: float = Field(default=60.0, gt=0, le=3600)
    # Agent memory (M8). Budget for what one run may receive, summary trigger, and the default
    # lifetime of memories written automatically from runs (0 = no expiry).
    memory_max_entries: int = Field(default=20, ge=1, le=200)
    memory_max_chars: int = Field(default=4000, ge=200, le=50000)
    memory_summary_threshold: int = Field(default=8, ge=2, le=500)
    memory_default_ttl_days: int = Field(default=180, ge=0, le=3650)
    # Knowledge / RAG (M9). deterministic_local is offline and reproducible (tests, demo);
    # openai needs OPENAI_API_KEY and is never used by the test suite. The vector column is
    # vector(384): changing the dimension requires a migration, so only 384 is accepted.
    knowledge_embedding_provider: Literal["deterministic_local", "openai"] = "deterministic_local"
    knowledge_embedding_model: str = Field(default="nexusflow-hash-v1", max_length=80)
    knowledge_embedding_dimension: int = Field(default=384, ge=384, le=384)
    openai_api_key: SecretStr | None = None
    knowledge_embedding_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    knowledge_chunk_size: int = Field(default=1200, ge=200, le=8000)
    knowledge_chunk_overlap: int = Field(default=200, ge=0, le=2000)
    knowledge_top_k: int = Field(default=5, ge=1, le=20)
    knowledge_semantic_weight: float = Field(default=0.7, ge=0, le=1)
    knowledge_lexical_weight: float = Field(default=0.3, ge=0, le=1)
    knowledge_min_score: float = Field(default=0.2, ge=0, le=1)
    knowledge_max_context_chars: int = Field(default=4000, ge=500, le=50000)
    knowledge_max_file_mb: int = Field(default=10, ge=1, le=100)
    knowledge_upload_dir: str = "/data/knowledge"

    @model_validator(mode="after")
    def validate_configuration(self):
        if len(self.jwt_secret_key.get_secret_value().encode()) < 32:
            raise ValueError("JWT_SECRET_KEY must contain at least 32 bytes")
        if self.app_env == "production" and not self.auth_cookie_secure:
            raise ValueError("AUTH_COOKIE_SECURE must be true in production")
        if self.auth_cookie_samesite == "none" and not self.auth_cookie_secure:
            raise ValueError("SameSite=None requires a Secure cookie")
        if self.auth_cookie_name.startswith("__Host-") and not self.auth_cookie_secure:
            raise ValueError("__Host- cookies require Secure")
        if not self.api_v1_prefix.startswith("/") or self.api_v1_prefix.endswith("/"):
            raise ValueError("API_V1_PREFIX must begin with / and have no trailing slash")
        if "*" in self.cors_origins:
            raise ValueError("CORS_ORIGINS must contain explicit origins")
        if self.app_env == "production" and self.debug:
            raise ValueError("DEBUG must be false in production")
        if self.database_url:
            url = make_url(self.database_url.get_secret_value())
            if url.drivername != "postgresql+psycopg":
                raise ValueError("DATABASE_URL must use postgresql+psycopg")
        elif not self.postgres_password or not self.postgres_password.get_secret_value():
            raise ValueError("POSTGRES_PASSWORD or DATABASE_URL is required")
        for entry in self.mcp_allowed_hosts:
            host, _, port = entry.rpartition(":")
            if not host or not port.isdigit() or entry != entry.strip().lower():
                raise ValueError("MCP_ALLOWED_HOSTS entries must be lowercase host:port pairs")
        if self.app_env == "production" and self.execution_mode != "queue":
            raise ValueError("EXECUTION_MODE must be queue in production")
        if self.job_stale_after_seconds < 2 * self.worker_heartbeat_seconds:
            raise ValueError("JOB_STALE_AFTER_SECONDS must be at least twice the heartbeat")
        if self.knowledge_chunk_overlap >= self.knowledge_chunk_size // 2:
            raise ValueError("KNOWLEDGE_CHUNK_OVERLAP must be less than half the chunk size")
        if abs(self.knowledge_semantic_weight + self.knowledge_lexical_weight - 1) > 1e-6:
            raise ValueError("KNOWLEDGE_SEMANTIC_WEIGHT + KNOWLEDGE_LEXICAL_WEIGHT must equal 1")
        if self.knowledge_embedding_provider == "openai" and not self.openai_api_key:
            raise ValueError("KNOWLEDGE_EMBEDDING_PROVIDER=openai requires OPENAI_API_KEY")
        if self.knowledge_embedding_provider == "openai" and not (
            self.knowledge_embedding_model.startswith("text-embedding-3-")
        ):
            raise ValueError("OpenAI embeddings need KNOWLEDGE_EMBEDDING_MODEL=text-embedding-3-*")
        if self.redis_url and not self.redis_url.get_secret_value().startswith(
            ("redis://", "rediss://")
        ):
            raise ValueError("REDIS_URL must use redis:// or rediss://")
        if self.app_env == "production":
            secret = self.jwt_secret_key.get_secret_value()
            if (
                len(secret.encode()) < 48
                or len(set(secret)) < 12
                or any(
                    word in secret.lower()
                    for word in ("test-only", "change-me", "changeme", "example")
                )
            ):
                raise ValueError("Production JWT_SECRET_KEY must be a generated secret (48+ bytes)")
            required = {
                "cors_origins",
                "frontend_url",
                "allowed_hosts",
                "redis_url",
                "mcp_allowed_hosts",
                "knowledge_upload_dir",
            }
            if not required.issubset(self.model_fields_set):
                raise ValueError(
                    "Production requires explicit origins, hosts, Redis, MCP "
                    "and upload configuration"
                )
            for origin in [self.frontend_url, *self.cors_origins]:
                parsed = urlsplit(origin)
                if (
                    parsed.scheme != "https"
                    or not parsed.hostname
                    or parsed.username
                    or parsed.password
                    or parsed.path not in ("", "/")
                    or parsed.query
                    or parsed.fragment
                    or "*" in origin
                ):
                    raise ValueError(
                        "Production frontend and CORS origins must be explicit HTTPS origins"
                    )
            if not self.cors_origins or self.frontend_url.rstrip("/") not in {
                origin.rstrip("/") for origin in self.cors_origins
            }:
                raise ValueError("Production CORS_ORIGINS must include FRONTEND_URL")
            if not self.allowed_hosts or any(
                not host or "*" in host or "/" in host or ":" in host for host in self.allowed_hosts
            ):
                raise ValueError("Production ALLOWED_HOSTS must be explicit hostnames")
            database = self.sqlalchemy_url
            if not database.host or not database.username or len(database.password or "") < 16:
                raise ValueError(
                    "Production database requires a host, user and 16+ character password"
                )
            internal_hosts = {"postgres", "redis", "localhost", "127.0.0.1", "::1"}
            if database.host not in internal_hosts and database.query.get("sslmode") not in {
                "require",
                "verify-ca",
                "verify-full",
            }:
                raise ValueError("Remote production DATABASE_URL requires TLS sslmode")
            if not self.redis_url:
                raise ValueError("Production REDIS_URL must be explicit")
            redis = urlsplit(self.redis_url.get_secret_value())
            if not redis.hostname or (
                redis.hostname not in internal_hosts
                and (redis.scheme != "rediss" or not redis.password)
            ):
                raise ValueError("Remote production Redis requires TLS and authentication")
            upload = Path(self.knowledge_upload_dir)
            if not upload.is_absolute() or upload == Path("/") or ".." in upload.parts:
                raise ValueError(
                    "Production KNOWLEDGE_UPLOAD_DIR must be an absolute dedicated path"
                )
        return self

    @property
    def sqlalchemy_url(self) -> URL:
        if self.database_url:
            return make_url(self.database_url.get_secret_value())
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

    @property
    def redis_connection_url(self) -> str:
        if self.redis_url:
            return self.redis_url.get_secret_value()
        return f"redis://{self.redis_host}:{self.redis_port}/0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
