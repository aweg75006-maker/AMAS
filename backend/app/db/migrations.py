from pathlib import Path

from alembic import command
from alembic.config import Config

from app.core.config import BACKEND_DIR
from app.core.exceptions import ConfigurationError


def to_asyncpg_url(dsn: str) -> str:
    if dsn.startswith("postgresql+asyncpg://"):
        return dsn
    if dsn.startswith("postgresql://"):
        return dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    return dsn


def build_alembic_config(dsn: str) -> Config:
    alembic_ini = BACKEND_DIR / "alembic.ini"
    migrations_dir = BACKEND_DIR / "migrations"
    if not alembic_ini.exists() or not migrations_dir.exists():
        raise ConfigurationError("Alembic 迁移配置不存在，请检查 backend/alembic.ini 和 backend/migrations。")

    config = Config(str(alembic_ini))
    config.set_main_option("script_location", str(migrations_dir))
    config.set_main_option("sqlalchemy.url", to_asyncpg_url(dsn))
    return config


def run_postgres_migrations(dsn: str, revision: str = "head") -> None:
    config = build_alembic_config(dsn)
    command.upgrade(config, revision)
