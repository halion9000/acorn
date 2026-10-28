"""Leafy answers with the model the tenant set up for the rest of the platform, and with the gateway alias when it set up none."""

from __future__ import annotations

import pytest
from app.api.v1.endpoints.copilot import tenant_llm_override
from app.llm.factory import llm_override, make_chat_model
from app.services.llm_resolver import LlmConfig


def _config(**kw) -> LlmConfig:
    base = {
        "allowed": True,
        "base_url": "https://llm.example.com",
        "model": "gpt-4.1",
        "api_key": "sk-test",
        "source": "tenant",
        "reason": "",
    }
    return LlmConfig(**{**base, **kw})


def test_a_tenants_own_model_key_and_address_are_used_with_the_v1_the_client_wants():
    assert tenant_llm_override(_config()) == {"api_key": "sk-test", "base_url": "https://llm.example.com/v1", "model": "gpt-4.1"}
    assert tenant_llm_override(_config(base_url="https://llm.example.com/v1/", source="mixed"))["base_url"] == "https://llm.example.com/v1"


@pytest.mark.parametrize(
    "config",
    [_config(source="environment"), _config(source="none"), _config(allowed=False), _config(api_key=None)],
)
def test_without_a_tenant_setting_nothing_is_overridden(config):
    assert tenant_llm_override(config) == {}


def test_the_override_reaches_the_model_leafy_is_built_with(monkeypatch):
    monkeypatch.setenv(
        "OPENAI_API_KEY", "sk-from-the-environment"
    )  # the gateway-alias model below has no key of its own; without this the test only passes where the variable happens to be set
    with llm_override(**tenant_llm_override(_config())):
        model = make_chat_model("copilot")
    assert model.model_name == "gpt-4.1"
    assert "llm.example.com" in str(model.openai_api_base)
    assert make_chat_model("copilot").model_name == "aisoc-copilot"
