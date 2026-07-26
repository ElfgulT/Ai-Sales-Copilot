"""DemoLLMProvider testleri."""

from __future__ import annotations

import pytest

from app.infrastructure.llm.demo_provider import DemoLLMProvider


@pytest.mark.asyncio
async def test_demo_provider_extract_structured() -> None:
    provider = DemoLLMProvider()
    result = await provider.extract_structured(
        system="system prompt",
        prompt="otokar otobüs üreticisidir",
        schema={},
        tool_name="extract_insights",
        tool_description="test",
    )
    assert "summary" in result
    assert "pain_points" in result
    assert "signals" in result


@pytest.mark.asyncio
async def test_demo_provider_generate_text() -> None:
    provider = DemoLLMProvider()
    email = await provider.generate_text(
        system="system prompt",
        prompt="otokar email prompt",
        max_tokens=500,
    )
    pitch = await provider.generate_text(
        system="system prompt",
        prompt="otokar pitch prompt",
        max_tokens=500,
    )
    assert len(email) > 10
    assert len(pitch) > 10
