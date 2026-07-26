"""LLM analiz servisi (pipeline orkestrasyonu) testleri."""

from __future__ import annotations

import pytest

from app.application.llm_analysis_service import LLMAnalysisService
from app.application.rule_based_scoring_engine import RuleBasedScoringEngine
from app.core.exceptions import RobotsDisallowedError
from app.domain.models import CompanyInsights
from tests.factories import (
    FakeAnalyzer,
    FakeOutreachWriter,
    FakeScraper,
    make_scraped_content,
    make_signals,
)


def _service(analyzer=None, robots=None, writer=None) -> LLMAnalysisService:
    return LLMAnalysisService(
        FakeScraper(make_scraped_content()),
        analyzer or FakeAnalyzer(),
        RuleBasedScoringEngine(),
        writer or FakeOutreachWriter(),
        robots_checker=robots,
    )


@pytest.mark.asyncio
async def test_produces_real_analysis_not_stub() -> None:
    result = await _service().analyze("https://example.com")

    assert result.meta.is_stub is False
    assert result.summary == "Örnek şirket özeti."
    assert result.pain_points == ("Acı noktası 1", "Acı noktası 2")
    assert result.scraped is not None
    assert result.signals is not None
    # Sprint 4: e-posta ve pitch artık placeholder değil
    assert result.cold_email == "Sahte soğuk e-posta"
    assert result.pitch == "Sahte pitch"


@pytest.mark.asyncio
async def test_score_is_computed_from_signals() -> None:
    # Hot sinyaller -> yüksek skor (SaaS 25 + 51-200 30 + hiring 15 + growth 10 + tech 10 = 90)
    insights = CompanyInsights(
        summary="s", pain_points=("p",), signals=make_signals()
    )
    result = await _service(analyzer=FakeAnalyzer(insights)).analyze("https://example.com")

    assert result.lead_score.value == 90
    assert result.lead_score.tier.value == "hot"
    assert result.lead_score.reasons


@pytest.mark.asyncio
async def test_robots_disallowed_raises_before_work() -> None:
    class _Robots:
        async def is_allowed(self, url: str) -> bool:
            return False

    analyzer = FakeAnalyzer()
    service = _service(analyzer=analyzer, robots=_Robots())

    with pytest.raises(RobotsDisallowedError):
        await service.analyze("https://example.com")

    assert analyzer.called is False  # robots reddedince LLM çağrılmaz


@pytest.mark.asyncio
async def test_vector_store_per_company_isolation() -> None:
    """Ardışık şirket analizlerinde RAG bağlamlarının sızmadığını (izole olduğunu) doğrular."""
    from app.infrastructure.rag.vector_store import SimpleVectorStore

    class _CaptureAnalyzer(FakeAnalyzer):
        def __init__(self):
            super().__init__()
            self.last_rag_context: str | None = None

        async def analyze(self, content, rag_context=None, enrichment_data=None):
            self.last_rag_context = rag_context
            return self._insights

    analyzer = _CaptureAnalyzer()
    shared_store = SimpleVectorStore()
    service = LLMAnalysisService(
        FakeScraper(make_scraped_content(text="ABC Şirketi Özel Gizli Metni")),
        analyzer,
        RuleBasedScoringEngine(),
        FakeOutreachWriter(),
        vector_store=shared_store,
    )

    # 1. Şirket analizi
    await service.analyze("https://companyA.com")
    assert analyzer.last_rag_context is not None
    assert "ABC Şirketi" in analyzer.last_rag_context

    # 2. Şirket analizi (farklı metin)
    service._scraper = FakeScraper(make_scraped_content(text="XYZ Şirketi Tekstil İçeriği"))
    await service.analyze("https://companyB.com")
    assert analyzer.last_rag_context is not None
    assert "XYZ Şirketi" in analyzer.last_rag_context
    assert "ABC Şirketi" not in analyzer.last_rag_context  # ABC Şirketi verisi XYZ'ye sızmamalı!
