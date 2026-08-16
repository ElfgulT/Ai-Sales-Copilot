"""CachingAnalysisService unit testleri."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.application.caching_analysis_service import CachingAnalysisService
from app.domain.models import (
    AnalysisMeta,
    CompanyAnalysis,
    LeadScore,
    LeadTier,
    ScrapedContent,
)


@pytest.mark.asyncio
async def test_caching_analysis_service_caches_results() -> None:
    fake_scraped = ScrapedContent(
        url="https://example.com",
        title="Example",
        site_name="Example",
        meta_description=None,
        text="Test text",
        headings=("H1",),
        word_count=2,
        renderer="static",
        fetched_at=datetime.now(UTC),
    )
    fake_analysis = CompanyAnalysis(
        url="https://example.com",
        company_name="Example",
        summary="Özet",
        pain_points=("Nokta 1",),
        lead_score=LeadScore(value=80, tier=LeadTier.HOT),
        cold_email="Mail",
        pitch="Pitch",
        meta=AnalysisMeta(
            generated_at=datetime.now(UTC),
            pipeline_version="0.5.1",
            is_stub=True,
        ),
        scraped=fake_scraped,
    )
    inner_service = AsyncMock()
    inner_service.analyze.return_value = fake_analysis

    caching_service = CachingAnalysisService(inner_service, maxsize=10, ttl=60)

    # 1. Çağrı: Servisi çağırır
    res1 = await caching_service.analyze("https://example.com")
    assert res1 == fake_analysis
    assert inner_service.analyze.call_count == 1

    # 2. Çağrı: Önbellekten gelir (inner_service tekrar çağrılmaz)
    res2 = await caching_service.analyze("https://example.com")
    assert res2 == fake_analysis
    assert inner_service.analyze.call_count == 1
