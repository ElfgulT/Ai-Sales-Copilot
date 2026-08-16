"""`CleanedDocument` -> `ScrapedContent` dönüşümü (tek yerde, DRY).

Hem statik hem dinamik scraper aynı kurala göre `ScrapedContent` üretir.
"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

from app.domain.models import ScrapedContent
from app.infrastructure.scraping.html_cleaner import CleanedDocument

_HTTP_SCHEMES = {"http", "https"}
# Bağlantı olmayan href şemaları (mail/telefon/JS) ve sayfa içi çapa.
_NON_PAGE_PREFIXES = ("#", "mailto:", "tel:", "sms:", "javascript:", "data:")


def build_scraped_content(url: str, doc: CleanedDocument, renderer: str) -> ScrapedContent:
    return ScrapedContent(
        url=url,
        title=doc.title,
        site_name=doc.site_name,
        meta_description=doc.meta_description,
        text=doc.text,
        headings=doc.headings,
        word_count=len(doc.text.split()),
        renderer=renderer,
        fetched_at=datetime.now(UTC),
        detected_name=doc.company_name,
        links=absolute_links(url, doc.links),
    )


def absolute_links(base_url: str, hrefs: tuple[str, ...]) -> tuple[str, ...]:
    """Ham href'leri mutlak http(s) adreslerine çevirip tekilleştirir.

    Fragment (#bolum) atılır; aynı sayfanın farklı çapaları tek adres sayılır.
    Sayfadaki sıra korunur — gezinme menüsündeki bağlantılar önce gelir.
    """
    seen: set[str] = set()
    links: list[str] = []

    for href in hrefs:
        if href.lower().startswith(_NON_PAGE_PREFIXES):
            continue
        parsed = urlsplit(urljoin(base_url, href))
        if parsed.scheme not in _HTTP_SCHEMES or not parsed.netloc:
            continue
        absolute = urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.query, "")
        )
        if absolute in seen:
            continue
        seen.add(absolute)
        links.append(absolute)

    return tuple(links)
