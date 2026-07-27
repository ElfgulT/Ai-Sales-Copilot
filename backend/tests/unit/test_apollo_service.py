"""ApolloEnrichmentService unit testleri.

Odak: servis ASLA veri uydurmamalı. Apollo bir alanı döndürmediğinde o alan
sonuçta hiç bulunmamalı; varsayılan bir değerle doldurulmamalıdır — çünkü bu
veri lead skorunu ve soğuk e-postayı doğrudan besliyor.
"""

from __future__ import annotations

import httpx
import pytest

from app.infrastructure.enrichment.apollo_service import ApolloEnrichmentService


@pytest.mark.asyncio
async def test_anahtar_yoksa_servis_devre_disi() -> None:
    service = ApolloEnrichmentService(api_key=None)

    assert service.is_enabled is False

    data = await service.enrich_company("https://example.com/about")

    assert data["domain"] == "example.com"
    assert data["enrichment_source"] == "disabled"
    # Uydurulmuş hiçbir şirket verisi dönmemeli.
    assert "industry" not in data
    assert "annual_revenue" not in data
    assert "technologies" not in data


@pytest.mark.asyncio
async def test_apollo_alan_dondurmezse_alan_uydurulmaz(monkeypatch) -> None:
    """Apollo 200 döner ama `industry` yoksa → sonuçta `industry` HİÇ olmamalı.

    Eski davranış burada "Teknoloji" uyduruyordu; o değer sinyallere ve oradan
    lead skoruna geçtiği için kullanıcıya kanıtsız bilgi sunuluyordu.
    """

    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, json={"organization": {"name": "Örnek A.Ş."}})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    service = ApolloEnrichmentService(api_key="test-key")
    data = await service.enrich_company("ornek.com")

    assert data["enrichment_source"] == "apollo.io"
    assert "industry" not in data
    assert "employee_count" not in data


@pytest.mark.asyncio
async def test_apollo_alanlari_dogru_isimlerle_eslenir(monkeypatch) -> None:
    """Çalışan sayısı `employee_count`'a gider — eskiden yanlışlıkla
    `estimated_revenue` (yıllık gelir) olarak etiketleniyordu."""

    async def fake_get(self, url, **kwargs):
        return httpx.Response(
            200,
            json={
                "organization": {
                    "industry": "software",
                    "estimated_num_employees": 250,
                    "annual_revenue": 5_000_000,
                    "technology_names": ["AWS", "React"],
                }
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    service = ApolloEnrichmentService(api_key="test-key")
    data = await service.enrich_company("https://ornek.com/urunler")

    assert data["domain"] == "ornek.com"
    assert data["industry"] == "software"
    assert data["employee_count"] == 250
    assert data["annual_revenue"] == 5_000_000
    assert data["technologies"] == ["AWS", "React"]


@pytest.mark.asyncio
async def test_api_hata_dondurunce_cokmeden_devam_eder(monkeypatch) -> None:
    async def fake_get(self, url, **kwargs):
        return httpx.Response(401, json={"error": "unauthorized"})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    service = ApolloEnrichmentService(api_key="gecersiz")
    data = await service.enrich_company("ornek.com")

    assert data == {"domain": "ornek.com", "enrichment_source": "unavailable"}


@pytest.mark.asyncio
async def test_ag_hatasinda_cokmez(monkeypatch) -> None:
    async def fake_get(self, url, **kwargs):
        raise httpx.ConnectError("baglanti yok")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    service = ApolloEnrichmentService(api_key="test-key")
    data = await service.enrich_company("ornek.com")

    assert data["enrichment_source"] == "unavailable"
