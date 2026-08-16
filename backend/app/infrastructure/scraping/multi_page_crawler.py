"""Multi-page crawler: ana sayfa + öncelikli alt sayfaları çekip birleştirir.

Tek sayfalık scraping'in kör noktasını kapatır: /about, /services, /team gibi
marka sinyali taşıyan sayfalar artık LLM'e de ulaşır.

Alt sayfa adayları ÖNCE ana sayfanın kendi `<a href>` bağlantılarından seçilir:
aynı host üzerinde olan ve yolunda anlamlı anahtar kelime geçen adresler.
Böylece var olmayan adreslere kör istek atılmaz. Gerçek vaka: sabit yol
listesiyle python.org analizinde 4 adayın 3'ü 404 dönüyordu. Sabit liste
yalnızca sayfada hiç uygun bağlantı bulunamazsa (ör. içerik JS ile gelmiş ve
menü render edilmemişse) yedek olarak devreye girer.

Aynı `WebScraper` arayüzünü uygular ve `HybridScraper`'ı sarmalar (decorator).
Üst katman hiçbir farkı görmez. İç scraper zaten UrlGuard + rate limiter
içerdiğinden burada ayrıca adres doğrulaması yapılmaz; aynı host, aynı kural.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from urllib.parse import unquote, urljoin, urlparse

from app.core.exceptions import ScrapeError
from app.domain.interfaces import WebScraper
from app.domain.models import ScrapedContent

logger = logging.getLogger(__name__)

_PRIORITY_PATHS: list[str] = [
    "/about",
    "/about-us",
    "/who-we-are",
    "/services",
    "/products",
    "/solutions",
    "/team",
    "/our-team",
    "/careers",
    "/jobs",
    "/contact",
    "/contact-us",
]

# Bağlantı yollarında aranan anahtar kelimeler, ÖNCELİK sırasıyla gruplanmış.
# Her gruptan en fazla bir sayfa seçilir; böylece /about, /about/history,
# /about/offices gibi bir küme tüm kotayı yemez, farklı temalar temsil edilir.
_KEYWORD_GROUPS: tuple[tuple[str, ...], ...] = (
    ("about", "hakkimizda", "hakkinda", "who-we-are", "kurumsal"),
    ("services", "hizmet", "solutions", "cozum"),
    ("products", "urun", "product"),
    ("team", "ekip", "kadro"),
    ("careers", "kariyer", "jobs", "career"),
    ("contact", "iletisim"),
)

# Sayfa olmayan (indirilebilir dosya) uzantılar — metin analizi için değersiz.
_SKIPPED_SUFFIXES = (
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".zip",
    ".rar",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".webp",
    ".mp4",
    ".mp3",
)

# Türkçe karakterleri ASCII karşılıklarına indirger: "/hakkımızda" adresi de
# "/hakkimizda" anahtar kelimesiyle eşleşsin diye.
_TR_FOLD = str.maketrans(
    {
        "ı": "i",
        "İ": "i",
        "ş": "s",
        "Ş": "s",
        "ğ": "g",
        "Ğ": "g",
        "ü": "u",
        "Ü": "u",
        "ö": "o",
        "Ö": "o",
        "ç": "c",
        "Ç": "c",
        "â": "a",
        "î": "i",
        "û": "u",
    }
)


def _path_label(url: str) -> str:
    """URL'den okunabilir bölüm etiketi üretir (birleştirilmiş metinde kullanılır)."""
    path = urlparse(url).path.strip("/")
    return path.replace("-", " ").replace("/", " > ").title() or "Home"


def _dedupe_key(url: str) -> str:
    """Aynı sayfanın farklı yazımlarını tek anahtara indirger."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/")
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{host}{path}{query}"


def _host_key(url: str) -> str:
    """Karşılaştırma için host: küçük harf, "www." atılmış, port dahil."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    return f"{host}:{parsed.port}" if parsed.port else host


def _normalized_path(url: str) -> str:
    """Yolu anahtar kelime eşleşmesi için sadeleştirir (unquote + ASCII + küçük harf).

    ASCII indirgeme küçük harfe çevirmeden ÖNCE yapılır: "İ".lower() Python'da
    birleşik nokta içeren iki karakter üretir ve eşleşmeyi bozar.
    """
    return unquote(urlparse(url).path).translate(_TR_FOLD).lower()


def _keyword_group(path: str) -> int | None:
    """Yolun eşleştiği anahtar kelime grubunun sırasını döndürür; yoksa None."""
    for index, keywords in enumerate(_KEYWORD_GROUPS):
        if any(keyword in path for keyword in keywords):
            return index
    return None


class MultiPageCrawler(WebScraper):
    """Inner scraper'ı sarmalayan çok sayfalı tarayıcı.

    `scrape(url)`:
    1. Ana URL'yi inner scraper ile çeker.
    2. Ana sayfanın bağlantılarından alt sayfa adayları seçer (yoksa sabit
       yol listesine düşer).
    3. Adayları eş zamanlı çeker; başarısızlar sessizce atlanır.
    4. Tüm sonuçları tek bir zenginleştirilmiş `ScrapedContent`'te birleştirir.
    """

    def __init__(
        self,
        inner: WebScraper,
        *,
        max_subpages: int = 4,
        min_words: int = 50,
    ) -> None:
        self._inner = inner
        self._max_subpages = max_subpages
        self._min_words = min_words

    async def scrape(self, url: str) -> ScrapedContent:
        main = await self._inner.scrape(url)

        candidates = self._candidate_urls(url, main.links)
        if not candidates:
            return main

        tasks = [self._safe_scrape(c) for c in candidates]
        results: list[ScrapedContent | None] = await asyncio.gather(*tasks)

        extras = [
            r for r in results
            if r is not None and r.word_count >= self._min_words
        ]

        if not extras:
            return main

        merged = self._merge(main, extras)
        logger.info(
            "Çok sayfalı çekim tamamlandı: %d alt sayfa birleştirildi, "
            "toplam %d kelime (%s)",
            len(extras),
            merged.word_count,
            url,
        )
        return merged

    async def _safe_scrape(self, url: str) -> ScrapedContent | None:
        try:
            return await self._inner.scrape(url)
        except ScrapeError as exc:
            logger.debug("Alt sayfa atlandı (%s): %s", exc, url)
            return None

    def _candidate_urls(self, entry_url: str, links: Sequence[str]) -> list[str]:
        """Önce sayfadaki gerçek bağlantılar; hiçbiri uymazsa sabit yol listesi."""
        discovered = self._discovered_candidates(entry_url, links)
        if discovered:
            logger.debug(
                "Alt sayfa adayları bağlantılardan seçildi (%d): %s",
                len(discovered),
                discovered,
            )
            return discovered
        return self._fallback_candidates(entry_url)

    def _discovered_candidates(self, entry_url: str, links: Sequence[str]) -> list[str]:
        """Aynı host üzerindeki, anahtar kelime taşıyan bağlantıları seçer.

        Her anahtar kelime grubundan önce birer sayfa alınır (öncelik sırasıyla),
        kota artarsa kalan eşleşmelerle doldurulur.
        """
        entry_host = _host_key(entry_url)
        seen: set[str] = {_dedupe_key(entry_url)}
        best_per_group: dict[int, str] = {}
        leftovers: list[str] = []

        for link in links:
            key = _dedupe_key(link)
            if key in seen or _host_key(link) != entry_host:
                continue

            path = _normalized_path(link)
            if not path.strip("/") or path.endswith(_SKIPPED_SUFFIXES):
                continue

            group = _keyword_group(path)
            if group is None:
                continue

            seen.add(key)
            if group in best_per_group:
                leftovers.append(link)
            else:
                best_per_group[group] = link

        ordered = [best_per_group[g] for g in sorted(best_per_group)] + leftovers
        return ordered[: self._max_subpages]

    def _fallback_candidates(self, entry_url: str) -> list[str]:
        """Sayfada uygun bağlantı yoksa kullanılan sabit yol tahminleri."""
        parsed = urlparse(entry_url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        seen: set[str] = {_dedupe_key(entry_url)}
        candidates: list[str] = []

        for path in _PRIORITY_PATHS:
            candidate = urljoin(base, path)
            key = _dedupe_key(candidate)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)
            if len(candidates) >= self._max_subpages:
                break

        return candidates

    def _merge(self, main: ScrapedContent, extras: list[ScrapedContent]) -> ScrapedContent:
        parts = [main.text]
        for extra in extras:
            label = _path_label(extra.url)
            parts.append(f"\n\n[{label}]\n{extra.text}")

        merged_text = "".join(parts)

        seen_headings: set[str] = set(main.headings)
        extra_headings: list[str] = []
        for extra in extras:
            for h in extra.headings:
                if h not in seen_headings:
                    seen_headings.add(h)
                    extra_headings.append(h)

        all_headings = tuple(list(main.headings) + extra_headings)[:30]

        return ScrapedContent(
            url=main.url,
            title=main.title,
            site_name=main.site_name,
            meta_description=main.meta_description,
            text=merged_text,
            headings=all_headings,
            word_count=len(merged_text.split()),
            renderer=main.renderer,
            fetched_at=main.fetched_at,
            detected_name=main.detected_name,
            links=main.links,
        )
