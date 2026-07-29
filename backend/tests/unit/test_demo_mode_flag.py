"""Demo modunun analiz sonucunda işaretlenmesi.

Demo sağlayıcı gerçek model çağrısı yapmaz; önceden yazılmış metinler döndürür.
Bu çıktının gerçek analiz sanılması, üründe olabilecek en kötü yanlış anlaşılmadır
(sunum/jüri açısından da kritik). Bu yüzden bayrak API yanıtına kadar taşınmalı.
"""

from __future__ import annotations

import pytest

from app.application.llm_analysis_service import LLMAnalysisService
from app.application.rule_based_scoring_engine import RuleBasedScoringEngine
from tests.factories import (
    FakeAnalyzer,
    FakeOutreachWriter,
    FakeScraper,
    make_scraped_content,
)


def _service(*, is_demo: bool) -> LLMAnalysisService:
    return LLMAnalysisService(
        FakeScraper(make_scraped_content()),
        FakeAnalyzer(),
        RuleBasedScoringEngine(),
        FakeOutreachWriter(),
        is_demo=is_demo,
    )


@pytest.mark.asyncio
async def test_demo_modunda_bayrak_isaretlenir() -> None:
    result = await _service(is_demo=True).analyze("https://ornek.com")
    assert result.meta.is_demo is True


@pytest.mark.asyncio
async def test_gercek_saglayicida_bayrak_kapali() -> None:
    result = await _service(is_demo=False).analyze("https://ornek.com")
    assert result.meta.is_demo is False


@pytest.mark.asyncio
async def test_bayrak_api_yanitina_kadar_tasinir() -> None:
    """Eklenti uyarıyı `meta.is_demo` alanından okuyor; sözleşme korunmalı."""
    from app.api.schemas import AnalyzeResponse, EmailResponse

    result = await _service(is_demo=True).analyze("https://ornek.com")

    assert AnalyzeResponse.from_domain(result).model_dump()["meta"]["is_demo"] is True
    # "↻ Yeniden üret" de demo çıktısı döndürür; orada da işaretlenmeli.
    assert EmailResponse.from_domain(result).model_dump()["is_demo"] is True
