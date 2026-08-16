"""MultiPageCrawler testleri — ağ kullanmadan."""

from __future__ import annotations

import pytest

from app.core.exceptions import ScrapeError
from app.domain.interfaces import WebScraper
from app.domain.models import ScrapedContent
from app.infrastructure.scraping.multi_page_crawler import MultiPageCrawler
from tests.factories import make_scraped_content


class MappingScraper(WebScraper):
    """URL'e göre farklı içerik döndüren test yardımcısı."""

    def __init__(
        self,
        mapping: dict[str, ScrapedContent],
        default_error: Exception | None = None,
    ) -> None:
        self._mapping = mapping
        self._default_error = default_error

    async def scrape(self, url: str) -> ScrapedContent:
        key = url.rstrip("/")
        for k, v in self._mapping.items():
            if k.rstrip("/") == key:
                return v
        if self._default_error:
            raise self._default_error
        raise ScrapeError(f"Bilinmeyen URL: {url}")


def _rich(url: str, text: str, links: tuple[str, ...] = ()) -> ScrapedContent:
    words = text.split()
    return make_scraped_content(url=url, text=text, word_count=len(words), links=links)


class LoggingScraper(WebScraper):
    """Çağrılan URL'leri kaydeden, her istekte aynı içeriği dönen scraper."""

    def __init__(self, content: ScrapedContent) -> None:
        self._content = content
        self.calls: list[str] = []

    async def scrape(self, url: str) -> ScrapedContent:
        self.calls.append(url)
        return self._content


async def _visited_subpages(
    main: ScrapedContent, *, entry_url: str = "https://example.com", max_subpages: int = 4
) -> list[str]:
    """Crawler'ı çalıştırıp ana sayfa dışında ziyaret edilen adresleri döndürür."""
    scraper = LoggingScraper(main)
    crawler = MultiPageCrawler(scraper, max_subpages=max_subpages, min_words=50)
    await crawler.scrape(entry_url)
    return [u for u in scraper.calls if u.rstrip("/") != entry_url.rstrip("/")]


@pytest.mark.asyncio
async def test_merges_subpages_into_main_content() -> None:
    main = _rich("https://example.com", "ana sayfa metni " * 30)
    about = _rich("https://example.com/about", "hakkımızda metni " * 30)

    scraper = MappingScraper(
        {"https://example.com": main, "https://example.com/about": about},
        default_error=ScrapeError("404"),
    )
    crawler = MultiPageCrawler(scraper, max_subpages=1, min_words=50)
    result = await crawler.scrape("https://example.com")

    assert "ana sayfa metni" in result.text
    assert "hakkımızda metni" in result.text
    assert result.url == "https://example.com"


@pytest.mark.asyncio
async def test_returns_main_when_all_subpages_fail() -> None:
    main = _rich("https://example.com", "ana sayfa " * 20)
    scraper = MappingScraper(
        {"https://example.com": main},
        default_error=ScrapeError("404"),
    )
    crawler = MultiPageCrawler(scraper, max_subpages=4, min_words=50)
    result = await crawler.scrape("https://example.com")

    assert result.text == main.text
    assert result.word_count == main.word_count


@pytest.mark.asyncio
async def test_skips_thin_subpages() -> None:
    main = _rich("https://example.com", "ana sayfa metni " * 20)
    thin = make_scraped_content(
        url="https://example.com/about", text="az", word_count=1
    )
    scraper = MappingScraper(
        {"https://example.com": main, "https://example.com/about": thin},
        default_error=ScrapeError("404"),
    )
    crawler = MultiPageCrawler(scraper, max_subpages=1, min_words=50)
    result = await crawler.scrape("https://example.com")

    assert result.text == main.text


@pytest.mark.asyncio
async def test_respects_max_subpages() -> None:
    call_log: list[str] = []
    rich_content = _rich("https://example.com", "içerik " * 30)

    class LoggingScraper(WebScraper):
        async def scrape(self, url: str) -> ScrapedContent:
            call_log.append(url)
            return rich_content

    crawler = MultiPageCrawler(LoggingScraper(), max_subpages=2, min_words=50)
    await crawler.scrape("https://example.com")

    assert len(call_log) == 3  # 1 ana + 2 alt sayfa


@pytest.mark.asyncio
async def test_skips_failed_subpages_gracefully() -> None:
    main = _rich("https://example.com", "ana sayfa " * 30)
    about = _rich("https://example.com/about", "hakkımızda " * 60)

    class PartialScraper(WebScraper):
        async def scrape(self, url: str) -> ScrapedContent:
            if url.rstrip("/") == "https://example.com":
                return main
            if "/about" in url:
                return about
            raise ScrapeError("bulunamadı")

    crawler = MultiPageCrawler(PartialScraper(), max_subpages=4, min_words=50)
    result = await crawler.scrape("https://example.com")

    assert "ana sayfa" in result.text
    assert "hakkımızda" in result.text


@pytest.mark.asyncio
async def test_metadata_comes_from_main_page() -> None:
    main = make_scraped_content(
        url="https://example.com",
        title="Ana Başlık",
        site_name="ExampleCo",
        text="ana metni " * 20,
        word_count=200,
        detected_name="Example Company",
    )
    about = make_scraped_content(
        url="https://example.com/about",
        title="Hakkımızda",
        site_name="Farklı İsim",
        text="alt sayfa metni " * 20,
        word_count=80,
    )
    scraper = MappingScraper(
        {"https://example.com": main, "https://example.com/about": about},
        default_error=ScrapeError("404"),
    )
    crawler = MultiPageCrawler(scraper, max_subpages=1, min_words=50)
    result = await crawler.scrape("https://example.com")

    assert result.title == "Ana Başlık"
    assert result.site_name == "ExampleCo"
    assert result.detected_name == "Example Company"
    assert result.url == "https://example.com"


@pytest.mark.asyncio
async def test_entry_url_not_duplicated_as_candidate() -> None:
    """Ana URL zaten /about ise, /about tekrar çekilmemeli."""
    call_log: list[str] = []
    content = _rich("https://example.com/about", "içerik " * 30)

    class LoggingScraper(WebScraper):
        async def scrape(self, url: str) -> ScrapedContent:
            call_log.append(url)
            return content

    crawler = MultiPageCrawler(LoggingScraper(), max_subpages=4, min_words=50)
    await crawler.scrape("https://example.com/about")

    called_paths = [url for url in call_log if url.rstrip("/") == "https://example.com/about"]
    assert len(called_paths) == 1  # yalnızca bir kez çekildi


@pytest.mark.asyncio
async def test_candidates_come_from_page_links_not_guesses() -> None:
    """Sayfada gerçek bağlantı varsa sabit yol listesi hiç denenmez."""
    main = _rich(
        "https://example.com",
        "içerik " * 30,
        links=(
            "https://example.com/kurumsal/hakkimizda",
            "https://example.com/blog/yeni-yazi",
            "https://example.com/cozumlerimiz",
        ),
    )

    visited = await _visited_subpages(main)

    assert visited == [
        "https://example.com/kurumsal/hakkimizda",
        "https://example.com/cozumlerimiz",
    ]


@pytest.mark.asyncio
async def test_ignores_links_from_other_hosts() -> None:
    main = _rich(
        "https://example.com",
        "içerik " * 30,
        links=(
            "https://twitter.com/example/about",
            "https://cdn.other.com/services",
            "https://www.example.com/about-us",
        ),
    )

    visited = await _visited_subpages(main)

    # "www." aynı site sayılır; farklı hostlar elenir.
    assert visited == ["https://www.example.com/about-us"]


@pytest.mark.asyncio
async def test_matches_turkish_and_encoded_paths() -> None:
    main = _rich(
        "https://example.com",
        "içerik " * 30,
        links=(
            "https://example.com/hakk%C4%B1m%C4%B1zda",
            "https://example.com/İletişim",
        ),
    )

    visited = await _visited_subpages(main)

    assert visited == [
        "https://example.com/hakk%C4%B1m%C4%B1zda",
        "https://example.com/İletişim",
    ]


@pytest.mark.asyncio
async def test_one_page_per_keyword_group_before_extras() -> None:
    """Tek bir tema (ör. /about/*) tüm kotayı yemez; önce farklı temalar gelir."""
    main = _rich(
        "https://example.com",
        "içerik " * 30,
        links=(
            "https://example.com/about",
            "https://example.com/about/history",
            "https://example.com/about/offices",
            "https://example.com/careers",
        ),
    )

    visited = await _visited_subpages(main, max_subpages=3)

    assert visited[:2] == ["https://example.com/about", "https://example.com/careers"]
    assert visited[2] == "https://example.com/about/history"


@pytest.mark.asyncio
async def test_skips_non_page_links_and_entry_url() -> None:
    main = _rich(
        "https://example.com",
        "içerik " * 30,
        links=(
            "https://example.com/",
            "https://example.com/docs/about-us.pdf",
            "https://example.com/team",
        ),
    )

    visited = await _visited_subpages(main)

    assert visited == ["https://example.com/team"]


@pytest.mark.asyncio
async def test_falls_back_to_static_paths_when_no_link_matches() -> None:
    """Sayfada uygun bağlantı yoksa (ör. JS menü) sabit liste yedeğe girer."""
    main = _rich(
        "https://example.com",
        "içerik " * 30,
        links=("https://example.com/blog", "https://linkedin.com/company/example"),
    )

    visited = await _visited_subpages(main, max_subpages=2)

    assert visited == ["https://example.com/about", "https://example.com/about-us"]
