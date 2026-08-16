"""Hybrid scraper fallback mantığı testleri (sahte scraper'larla)."""

from __future__ import annotations

import pytest

from app.core.exceptions import PageNotFoundError, ScrapeError
from app.infrastructure.scraping.hybrid_scraper import HybridScraper
from tests.factories import FakeScraper, make_scraped_content


@pytest.mark.asyncio
async def test_uses_static_when_content_is_rich() -> None:
    static = FakeScraper(make_scraped_content(renderer="static", word_count=200))
    dynamic = FakeScraper(make_scraped_content(renderer="dynamic", word_count=500))
    hybrid = HybridScraper(static, dynamic, min_words=120)

    result = await hybrid.scrape("https://example.com")

    assert result.renderer == "static"
    assert dynamic.called is False  # pahalı yol hiç çağrılmadı


@pytest.mark.asyncio
async def test_falls_back_to_dynamic_when_static_is_thin() -> None:
    static = FakeScraper(make_scraped_content(renderer="static", word_count=10))
    dynamic = FakeScraper(make_scraped_content(renderer="dynamic", word_count=300))
    hybrid = HybridScraper(static, dynamic, min_words=120)

    result = await hybrid.scrape("https://example.com")

    assert result.renderer == "dynamic"
    assert dynamic.called is True


@pytest.mark.asyncio
async def test_returns_static_when_dynamic_fails() -> None:
    static = FakeScraper(make_scraped_content(renderer="static", word_count=10))
    dynamic = FakeScraper(error=ScrapeError("Playwright yok"))
    hybrid = HybridScraper(static, dynamic, min_words=120)

    result = await hybrid.scrape("https://example.com")

    assert result.renderer == "static"  # zarif düşüş (graceful degradation)


@pytest.mark.asyncio
async def test_does_not_fall_back_to_dynamic_on_404() -> None:
    """404'te dinamik yedek DENENMEMELİ.

    Denenirse Playwright sitenin 404 sayfasını başarıyla render eder ve hata
    sayfasının metni gerçek şirket içeriği sanılır — python.org analizinde tam
    olarak bu oldu ve "sitede 404 hataları var" şeklinde yanlış bir acı noktası
    üretildi.
    """
    static = FakeScraper(error=PageNotFoundError())
    dynamic = FakeScraper(make_scraped_content(renderer="dynamic", word_count=115))
    hybrid = HybridScraper(static, dynamic, min_words=120)

    with pytest.raises(PageNotFoundError):
        await hybrid.scrape("https://example.com/about-us")

    assert dynamic.called is False


@pytest.mark.asyncio
async def test_still_falls_back_on_other_static_errors() -> None:
    """404 dışındaki hatalarda dinamik yedek çalışmaya devam etmeli."""
    static = FakeScraper(error=ScrapeError("geçici hata"))
    dynamic = FakeScraper(make_scraped_content(renderer="dynamic", word_count=300))
    hybrid = HybridScraper(static, dynamic, min_words=120)

    result = await hybrid.scrape("https://example.com")

    assert result.renderer == "dynamic"


@pytest.mark.asyncio
async def test_keeps_static_when_dynamic_has_less_content() -> None:
    static = FakeScraper(make_scraped_content(renderer="static", word_count=50))
    dynamic = FakeScraper(make_scraped_content(renderer="dynamic", word_count=20))
    hybrid = HybridScraper(static, dynamic, min_words=120)

    result = await hybrid.scrape("https://example.com")

    assert result.renderer == "static"
