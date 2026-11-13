"""Application settings, loaded from the repo-root .env file.

Precedence: real environment variables > .env file > defaults.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> parents[3] == repo root
REPO_ROOT = Path(__file__).resolve().parents[3]

#: Values shipped in .env.example. Acceptable locally, fatal in production.
WEAK_SECRETS = frozenset(
    {
        "",
        "fig_local_dev",
        "fig_local_dev_pwd",
        "change_me_in_local_env",
        "changeme",
        "postgres",
        "neo4j",
    }
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- runtime ----
    app_name: str = "Financial Intelligence Graph"
    app_env: str = "development"
    app_log_level: str = "INFO"
    app_timezone: str = "Asia/Shanghai"

    # ---- api ----
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_base_path: str = "/api/v1"
    api_cors_origins: str = "http://localhost:5173"

    # ---- postgres ----
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "fig"
    postgres_user: str = "fig"
    postgres_password: str = "fig_local_dev"
    postgres_password_file: str | None = None
    database_url: str = ""

    # ---- neo4j ----
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "fig_local_dev"
    neo4j_password_file: str | None = None
    neo4j_database: str = "neo4j"

    # ---- graph expansion (overridable via app_setting table later) ----
    expansion_default_depth: int = 3
    expansion_max_depth: int = 5
    expansion_max_nodes: int = 300
    confidence_isolation_threshold: float = 0.5
    evidence_min_grade_for_verified: str = "C"

    # ---- scheduler ----
    scheduler_enabled: bool = False
    projection_interval_seconds: int = 300

    # ---- alembic locations (overridable so the container layout works) ----
    alembic_ini_path: str = str(REPO_ROOT / "backend" / "alembic.ini")
    migrations_path: str = str(REPO_ROOT / "database" / "migrations")

    # ---- llm ----
    llm_default_provider: str = "openai_compatible"
    llm_default_model: str = ""
    llm_request_timeout_seconds: int = 60
    llm_max_retries: int = 2

    @property
    def sqlalchemy_url(self) -> str:
        """Async SQLAlchemy DSN. Explicit DATABASE_URL wins if provided."""
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

    @model_validator(mode="after")
    def _load_secret_files(self) -> Settings:
        """Support Docker secrets: POSTGRES_PASSWORD_FILE / NEO4J_PASSWORD_FILE.

        Keeps plaintext passwords out of compose files and out of `docker inspect`.
        """
        for field, file_env in (
            ("postgres_password", "postgres_password_file"),
            ("neo4j_password", "neo4j_password_file"),
        ):
            path = getattr(self, file_env, None)
            if not path:
                continue
            candidate = Path(path)
            if candidate.is_file():
                object.__setattr__(self, field, candidate.read_text(encoding="utf-8").strip())
        return self

    @model_validator(mode="after")
    def _refuse_weak_secrets_in_production(self) -> Settings:
        """Fail fast instead of shipping a database with the example password."""
        if not self.is_production:
            return self
        offenders = [
            name
            for name, value in (
                ("POSTGRES_PASSWORD", self.postgres_password),
                ("NEO4J_PASSWORD", self.neo4j_password),
            )
            if value in WEAK_SECRETS
        ]
        if offenders:
            raise ValueError(
                f"Refusing to start in production with default secrets: {', '.join(offenders)}"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()

__all__ = ["Settings", "get_settings", "settings", "REPO_ROOT", "Field"]
