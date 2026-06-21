import importlib.util

from app.db.migrations import build_alembic_config, to_asyncpg_url


def test_to_asyncpg_url_converts_plain_postgres_dsn():
    assert (
        to_asyncpg_url("postgresql://user:pass@localhost:5432/postgres")
        == "postgresql+asyncpg://user:pass@localhost:5432/postgres"
    )


def test_to_asyncpg_url_keeps_existing_asyncpg_dsn():
    dsn = "postgresql+asyncpg://user:pass@localhost:5432/postgres"
    assert to_asyncpg_url(dsn) == dsn


def test_build_alembic_config_uses_backend_migrations_dir():
    config = build_alembic_config("postgresql://user:pass@localhost:5432/postgres")

    assert config.get_main_option("script_location").endswith("/backend/migrations")
    assert config.get_main_option("sqlalchemy.url").startswith("postgresql+asyncpg://")


def test_initial_migration_revision_exists():
    spec = importlib.util.find_spec(
        "migrations.versions.20260621_0001_create_knowledge_metadata"
    )
    assert spec is not None


def test_account_identity_migration_revision_exists():
    spec = importlib.util.find_spec(
        "migrations.versions.20260621_0002_create_account_identity"
    )
    assert spec is not None


def test_username_migration_revision_exists():
    spec = importlib.util.find_spec(
        "migrations.versions.20260621_0003_add_username_to_users"
    )
    assert spec is not None
