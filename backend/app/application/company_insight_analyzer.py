"""Çekilen içerikten şirket içgörüsü (özet + acı noktaları + sinyaller) üretir.

Tek bir yapılandırılmış LLM çağrısıyla üç çıktıyı birlikte alır — ayrı ayrı üç
çağrı yapmaya göre daha ucuz ve tutarlı. LLM yalnızca dil anlama/çıkarım yapar;
puanlama bu sınıfın işi DEĞİLDİR (o, kural motorunun işi).

Prompt mühendisliği ilkeleri:
- Türkçe, doğal ve spesifik çıktı iste.
- "Yalnızca verilen içeriğe dayan, uydurma" (halüsinasyonu azalt).
- Bilinmeyen alanlar için null/boş bırak.
"""

from __future__ import annotations

import logging

from app.domain.interfaces import CompanyInsightAnalyzer, LLMProvider
from app.domain.models import CompanyInsights, CompanySignals, ScrapedContent

logger = logging.getLogger(__name__)

_TOOL_NAME = "save_company_insights"
_TOOL_DESCRIPTION = (
    "Bir şirketin web sitesi içeriğinden çıkarılan satış içgörülerini kaydeder."
)

# Geçerli çalışan sayısı bantları (kural motoru bunlara göre puanlar).
_EMPLOYEE_BANDS = ["1-10", "11-50", "51-200", "201-500", "501-1000", "1000+"]

_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "Şirketin ne yaptığına dair 3-4 cümlelik, Türkçe, akıcı özet.",
        },
        "pain_points": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Şirketin muhtemel 2-4 acı noktası (Türkçe, spesifik). "
                "Örn: 'Hızlı büyüyorlar ama destek ekibi küçük görünüyor.'"
            ),
        },
        "signals": {
            "type": "object",
            "properties": {
                "sector": {
                    "type": ["string", "null"],
                    "description": "Sektör, örn. 'SaaS', 'e-ticaret', 'fintech'. Bilinmiyorsa null.",
                },
                "employee_band": {
                    "type": ["string", "null"],
                    "enum": [*_EMPLOYEE_BANDS, None],
                    "description": "Tahmini çalışan sayısı bandı. Net değilse null.",
                },
                "is_hiring": {
                    "type": "boolean",
                    "description": "Sitede açık iş ilanı / kariyer sinyali var mı.",
                },
                "hiring_roles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Açık pozisyon türleri, örn. ['DevOps', 'Satış'].",
                },
                "growth_signals": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Büyüme işaretleri: yeni yatırım, yeni pazar, yeni ürün vb.",
                },
                "technologies": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tespit edilen teknolojiler/araçlar.",
                },
            },
            "required": ["sector", "employee_band", "is_hiring", "hiring_roles",
                         "growth_signals", "technologies"],
        },
    },
    "required": ["summary", "pain_points", "signals"],
}

_SYSTEM_PROMPT = (
    "Sen deneyimli bir B2B satış araştırma asistanısın. Sana bir şirketin web "
    "sitesinden çekilmiş metin verilir. Görevin: satış temsilcisinin bu şirketi "
    "hızlıca anlamasını sağlayacak özet, olası acı noktaları ve yapılandırılmış "
    "sinyaller çıkarmak. KURALLAR: Yalnızca verilen içeriğe dayan, bilgi "
    "uydurma. Emin olmadığın alanları boş/null bırak. Tüm metinsel çıktılar "
    "Türkçe ve doğal olsun."
)


class LLMCompanyInsightAnalyzer(CompanyInsightAnalyzer):
    def __init__(self, provider: LLMProvider, *, max_input_chars: int = 6000):
        self._provider = provider
        self._max_input_chars = max_input_chars

    async def analyze(
        self,
        content: ScrapedContent,
        rag_context: str | None = None,
        enrichment_data: dict | None = None,
    ) -> CompanyInsights:
        prompt = self._build_prompt(content, rag_context=rag_context, enrichment_data=enrichment_data)
        data = await self._provider.extract_structured(
            system=_SYSTEM_PROMPT,
            prompt=prompt,
            schema=_SCHEMA,
            tool_name=_TOOL_NAME,
            tool_description=_TOOL_DESCRIPTION,
        )
        return self._to_insights(data, enrichment_data=enrichment_data)

    def _build_prompt(
        self,
        content: ScrapedContent,
        rag_context: str | None = None,
        enrichment_data: dict | None = None,
    ) -> str:
        text = content.text[: self._max_input_chars]
        headings = " | ".join(content.headings[:15])

        prompt_parts = [
            f"ŞİRKET URL: {content.url}",
            f"BAŞLIK: {content.title or '-'}",
            f"META AÇIKLAMA: {content.meta_description or '-'}",
            f"BÖLÜM BAŞLIKLARI: {headings or '-'}",
        ]

        if rag_context:
            prompt_parts.append(f"\n--- RAG ODAKLI ÇEKİLEN İÇERİK PARÇALARI ---\n{rag_context}")

        if enrichment_data:
            # `domain` ve `enrichment_source` yalnızca iç kayıt tutma alanlarıdır;
            # modele gönderilirse gürültü yaratır. Yalnızca gerçek şirket verisi
            # kalırsa bloğu ekle — aksi halde hiç ekleme.
            facts = {
                k: v
                for k, v in enrichment_data.items()
                if v and k not in ("domain", "enrichment_source")
            }
            if facts:
                enrich_summary = ", ".join(f"{k}: {v}" for k, v in facts.items())
                prompt_parts.append(
                    f"\n--- APOLLO.IO B2B ŞİRKET ZENGİNLEŞTİRME VERİSİ ---\n{enrich_summary}"
                )

        prompt_parts.append(f"\nSAYFA METNİ:\n{text}")
        return "\n".join(prompt_parts)

    @staticmethod
    def _to_insights(data: dict, enrichment_data: dict | None = None) -> CompanyInsights:
        """LLM sözlüğünü güvenli biçimde domain modeline çevirir (eksik alanlara dayanıklı)."""
        raw_signals = data.get("signals") or {}

        # Apollo.io zenginleştirme verisini sinyallere entegre et
        sector = _clean_str(raw_signals.get("sector"))
        if not sector and enrichment_data and enrichment_data.get("industry"):
            sector = str(enrichment_data["industry"])

        techs = _clean_list(raw_signals.get("technologies"))
        if enrichment_data and enrichment_data.get("technologies"):
            # Sırayı KORUYARAK tekilleştir. `set()` kullanılırsa sıra çalıştırmadan
            # çalıştırmaya değişir; aynı sayfa iki kez analiz edildiğinde çıktı
            # farklı görünür ve testler kararsızlaşır.
            merged = list(techs) + [str(t) for t in enrichment_data["technologies"]]
            techs = tuple(dict.fromkeys(t for t in merged if t))

        signals = CompanySignals(
            sector=sector,
            employee_band=_clean_str(raw_signals.get("employee_band")),
            is_hiring=bool(raw_signals.get("is_hiring", False)),
            hiring_roles=_clean_list(raw_signals.get("hiring_roles")),
            growth_signals=_clean_list(raw_signals.get("growth_signals")),
            technologies=techs,
        )
        return CompanyInsights(
            summary=(data.get("summary") or "").strip(),
            pain_points=_clean_list(data.get("pain_points")),
            signals=signals,
        )


def _clean_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _clean_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())
