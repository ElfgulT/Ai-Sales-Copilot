"""Apollo.io B2B Şirket Veri Zenginleştirme Servisi."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.domain.interfaces import EnrichmentService

logger = logging.getLogger(__name__)


class ApolloEnrichmentService(EnrichmentService):
    """Apollo.io API entegrasyonu ile domain bazlı B2B şirket zenginleştirme servisi.

    API anahtarı bulunmadığında zarif bir biçimde mock/fallback veri döndürür.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    async def enrich_company(self, domain: str) -> dict[str, Any]:
        cleaned_domain = domain.removeprefix("https://").removeprefix("http://").split("/")[0]

        if not self._api_key:
            logger.info("Apollo API anahtarı yok, '%s' için varsayılan zenginleştirme verisi dönülüyor.", cleaned_domain)
            return {
                "domain": cleaned_domain,
                "enrichment_source": "default_fallback",
                "estimated_revenue": "Bilinmiyor",
                "funding_stage": "Bilinmiyor",
                "verified_b2b": True,
            }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.apollo.io/v1/organizations/enrich",
                    params={"domain": cleaned_domain, "api_key": self._api_key},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    org = data.get("organization") or {}
                    return {
                        "domain": cleaned_domain,
                        "enrichment_source": "apollo.io",
                        "estimated_revenue": org.get("estimated_num_employees", "N/A"),
                        "industry": org.get("industry", "Teknoloji"),
                        "technologies": org.get("technology_names", []),
                    }
        except Exception as exc:
            logger.warning("Apollo.io zenginleştirme çağrısı hata verdi: %s", exc)

        return {"domain": cleaned_domain, "enrichment_source": "fallback"}
