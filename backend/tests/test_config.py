import pytest

from app.core.exceptions import ConfigurationError


def test_safe_summary_masks_secrets():
    from app.core.config import settings

    summary = settings.safe_summary()

    assert "openai_api_key" not in summary
    assert "tavily_api_key" not in summary
    assert "dashscope_api_key" not in summary
    assert "123456" not in str(summary)
    assert "environment" in summary
    assert "total_token_budget" in summary
    assert "postgres_configured" in summary
    assert "postgres_auto_migrate" in summary
    assert "postgres_dsn" not in summary
    assert "seed_default_password" not in summary
    assert "jwt_secret_key" not in summary
    assert "jwt_secret_configured" in summary
    assert "rate_limit_enabled" in summary
    assert "rate_limit_login_capacity" in summary
    assert "workflow_node_timeout_seconds" in summary
    assert "workflow_node_max_retries" in summary


def test_missing_required_secrets_raise_configuration_error():
    from app.core.config import Settings

    settings = Settings(
        openai_api_key=None,
        tavily_api_key=None,
        dashscope_api_key=None,
    )

    with pytest.raises(ConfigurationError):
        settings.require_openai_api_key()
    with pytest.raises(ConfigurationError):
        settings.require_tavily_api_key()
    with pytest.raises(ConfigurationError):
        settings.require_dashscope_api_key()


def test_cors_origins_parses_comma_separated_values():
    from app.core.config import Settings

    settings = Settings(cors_allow_origins="http://localhost:5173, https://example.com")

    assert settings.cors_origins() == [
        "http://localhost:5173",
        "https://example.com",
    ]
