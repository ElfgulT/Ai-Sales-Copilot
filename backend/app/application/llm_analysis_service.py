"""Sprint 3 `AnalysisService`: scraping + LLM içgörü + kural tabanlı skorlama.

Pipeline (düz, sıralı orkestrasyon — rehberin önerdiği gibi LangGraph YOK):
    robots kontrolü -> scrape -> LLM içgörü (özet+pain point+sinyaller) ->
    kural tabanlı skor -> CompanyAnalysis

Artık `is_stub=False`: özet, acı noktaları ve lead skoru GERÇEK. Yalnızca
soğuk e-posta ve pitch placeholder kalır (Sprint 4).

Tüm bağımlılıklar arayüz üzerinden enjekte edilir (DIP) → her parça ayrı ayrı
test edilebilir, LLM mock'lanabilir.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from app import PIPELINE_VERSION
from app.application.company_name import derive_company_name
from app.core.exceptions import RobotsDisallowedError
from app.domain.interfaces import (
    AnalysisService,
    CompanyInsightAnalyzer,
    EnrichmentService,
    OutreachWriter,
    ScoringEngine,
    VectorStore,
    WebScraper,
)
from app.domain.models import AnalysisMeta, CompanyAnalysis
from app.infrastructure.rag.vector_store import SimpleVectorStore
from app.infrastructure.scraping.robots import RobotsChecker

logger = logging.getLogger(__name__)


class LLMAnalysisService(AnalysisService):
    def __init__(
        self,
        scraper: WebScraper,
        analyzer: CompanyInsightAnalyzer,
        scoring_engine: ScoringEngine,
        outreach_writer: OutreachWriter,
        robots_checker: RobotsChecker | None = None,
        vector_store: VectorStore | None = None,
        enrichment_service: EnrichmentService | None = None,
        is_demo: bool = False,
    ):
        self._scraper = scraper
        self._analyzer = analyzer
        self._scoring_engine = scoring_engine
        self._outreach_writer = outreach_writer
        self._robots_checker = robots_checker
        self._vector_store = vector_store
        self._enrichment_service = enrichment_service
        self._is_demo = is_demo

    async def analyze(self, url: str) -> CompanyAnalysis:
        if self._robots_checker is not None and not await self._robots_checker.is_allowed(url):
            raise RobotsDisallowedError()

        content = await self._scraper.scrape(url)
        company_name = derive_company_name(content, url)

        # RAG Vektör İndeksleme & Sorgulama (Retrieval) - Şirket Bazlı Tam İzole İndeks
        rag_context: str | None = None
        # Her analiz çağrısı için sıfır, izole bir Vektör Deposu oluşturulur (şirketler arası veri sızması imkânsızdır).
        vector_store = self._vector_store.__class__() if self._vector_store is not None else SimpleVectorStore()
        if content.text:
            await vector_store.add_documents([content.text], metadatas=[{"url": url, "name": company_name}])
            rag_chunks = await vector_store.query("acı noktaları müşteri zorluk fırsat teknoloji büyüme", top_k=3)
            if rag_chunks:
                rag_context = "\n---\n".join(rag_chunks)
                logger.info("RAG Sorgulaması (%d parça çekildi) tamamlandı.", len(rag_chunks))

        # B2B Şirket Veri Zenginleştirme (Apollo.io)
        enrichment_data: dict | None = None
        if self._enrichment_service is not None:
            enrichment_data = await self._enrichment_service.enrich_company(url)
            logger.info("Apollo zenginleştirme tamam: %s (Sektör: %s)", enrichment_data.get("enrichment_source"), enrichment_data.get("industry", "N/A"))

        insights = await self._analyzer.analyze(content, rag_context=rag_context, enrichment_data=enrichment_data)
        lead_score = self._scoring_engine.score(insights.signals)

        # E-posta ve pitch birbirinden bağımsız → eşzamanlı üret (daha hızlı).
        cold_email, pitch = await asyncio.gather(
            self._outreach_writer.write_cold_email(company_name, insights),
            self._outreach_writer.write_pitch(company_name, insights),
        )

        logger.info(
            "Analiz tamam: %s | skor=%d (%s) | %d acı noktası",
            company_name,
            lead_score.value,
            lead_score.tier.value,
            len(insights.pain_points),
        )

        return CompanyAnalysis(
            url=url,
            company_name=company_name,
            summary=insights.summary,
            pain_points=insights.pain_points,
            lead_score=lead_score,
            cold_email=cold_email,
            pitch=pitch,
            meta=AnalysisMeta(
                generated_at=datetime.now(UTC),
                pipeline_version=PIPELINE_VERSION,
                is_stub=False,
                is_demo=self._is_demo,
            ),
            scraped=content,
            signals=insights.signals,
        )
