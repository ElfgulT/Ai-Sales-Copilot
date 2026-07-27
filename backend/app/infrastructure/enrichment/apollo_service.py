"""Apollo.io B2B Şirket Veri Zenginleştirme Servisi."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.domain.interfaces import EnrichmentService

logger = logging.getLogger(__name__)


class ApolloEnrichmentService(EnrichmentService):
    """Apollo.io API entegrasyonu ile domain bazlı B2B şirket zenginleştirme servisi.

    TEMEL İLKE — ASLA VERİ UYDURMA: Zenginleştirme verisi lead skorunu ve soğuk
    e-postayı doğrudan besler. Bu yüzden Apollo bir alanı döndürmediğinde o alan
    sözlüğe HİÇ eklenmez; varsayılan ("Teknoloji", "Bilinmiyor" gibi) bir değerle
    doldurulmaz. Aksi halde sistem, kanıtı olmayan bir bilgiyi kullanıcıya
    doğrulanmış gibi sunar — projenin halüsinasyon karşıtı ilkesine aykırıdır.

    API anahtarı yoksa servis sessizce devre dışı kalır (boş sonuç döner);
    uygulama zenginleştirmesiz çalışmaya devam eder.
    """

    _ENDPOINT = "https://api.apollo.io/v1/organizations/enrich"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    @property
    def is_enabled(self) -> bool:
        return bool(self._api_key)

    @staticmethod
    def _clean_domain(domain: str) -> str:
        return domain.removeprefix("https://").removeprefix("http://").split("/")[0]

    async def enrich_company(self, domain: str) -> dict[str, Any]:
        cleaned_domain = self._clean_domain(domain)

        if not self._api_key:
            logger.info(
                "Apollo API anahtarı tanımlı değil — '%s' zenginleştirilmeden devam ediliyor.",
                cleaned_domain,
            )
            return {"domain": cleaned_domain, "enrichment_source": "disabled"}

        try:
            # Güvenlik: API anahtarı URL sorgusu yerine HTTP başlığında iletilir
            # (URL'ler log'lara, proxy kayıtlarına ve Referer başlıklarına sızabilir).
            headers = {"Cache-Control": "no-cache", "x-api-key": self._api_key}
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    self._ENDPOINT,
                    params={"domain": cleaned_domain},
                    headers=headers,
                )

            if resp.status_code != 200:
                logger.warning(
                    "Apollo.io beklenmeyen yanıt verdi (HTTP %s) — zenginleştirme atlanıyor.",
                    resp.status_code,
                )
                return {"domain": cleaned_domain, "enrichment_source": "unavailable"}

            org = (resp.json() or {}).get("organization") or {}
            result: dict[str, Any] = {
                "domain": cleaned_domain,
                "enrichment_source": "apollo.io",
            }
            # Yalnızca Apollo'nun GERÇEKTEN döndürdüğü alanları ekle.
            if org.get("industry"):
                result["industry"] = org["industry"]
            if org.get("estimated_num_employees"):
                result["employee_count"] = org["estimated_num_employees"]
            if org.get("annual_revenue"):
                result["annual_revenue"] = org["annual_revenue"]
            if org.get("technology_names"):
                result["technologies"] = list(org["technology_names"])
            return result

        except Exception as exc:
            logger.warning("Apollo.io zenginleştirme çağrısı hata verdi: %s", exc)
            return {"domain": cleaned_domain, "enrichment_source": "unavailable"}
