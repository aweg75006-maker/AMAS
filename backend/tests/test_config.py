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
    assert "rate_limit_enabled" in summary
    assert "workflow_node_timeout_seconds" in summary
    assert "workflow_node_max_retries" in summary
    assert "workflow_version" in summary
    assert "prompt_version" in summary
    assert "node_policy_version" in summary
    assert "harness_manifest" in summary
    assert "workflow_engine" in summary


def test_default_workflow_engine_is_langgraph():
    from app.core.config import Settings

    settings = Settings()

    assert settings.workflow_engine == "langgraph"


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
