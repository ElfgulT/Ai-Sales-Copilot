"""ApolloEnrichmentService unit testleri."""

from __future__ import annotations

import pytest

from app.infrastructure.enrichment.apollo_service import ApolloEnrichmentService


@pytest.mark.asyncio
async def test_apollo_service_fallback_when_no_api_key() -> None:
    service = ApolloEnrichmentService(api_key=None)
    data = await service.enrich_company("https://example.com/about")
    assert data["domain"] == "example.com"
    assert data["enrichment_source"] == "default_fallback"
