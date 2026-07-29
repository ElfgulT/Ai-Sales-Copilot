"""Hedef sektör eşleştirmesinin Türkçe karakterlere dayanıklılığı.

Gerçek hata: Python'un `str.lower()` metodu Türkçe'ye göre çalışmaz.
    "YAZILIM".lower()   -> "yazilim"    ("ı" yerine noktalı "i")
    "E-TİCARET".lower() -> "e-ti̇caret"  (birleşik nokta karakteri kalır)
Bu yüzden sektörü BÜYÜK harfle yazılan şirketler hedef listesiyle eşleşemiyor ve
25 puanı sessizce kaybediyordu. Aynı şirket, sektörü küçük harfle yazıldığında
25 puan alıyordu — yani skor, modelin yazım tercihine göre zıplıyordu.
"""

from __future__ import annotations

import pytest

from app.application.rule_based_scoring_engine import RuleBasedScoringEngine
from app.domain.models import CompanySignals


def _score_for(sector: str) -> int:
    """Yalnızca sektör kuralını izole eder; diğer tüm sinyaller boş bırakılır."""
    engine = RuleBasedScoringEngine()
    signals = CompanySignals(
        sector=sector,
        employee_band=None,
        is_hiring=False,
        hiring_roles=(),
        growth_signals=(),
        technologies=(),
    )
    return engine.score(signals).value


@pytest.mark.parametrize(
    "sector",
    [
        "yazılım",
        "Yazılım",
        "YAZILIM",          # regresyon: "ı" -> "i" dönüşümü yüzünden kaçırılıyordu
        "Yazilim",          # Türkçe karaktersiz yazım
        "e-ticaret",
        "E-Ticaret",
        "E-TİCARET",        # regresyon: birleşik nokta yüzünden kaçırılıyordu
        "teknoloji",
        "TEKNOLOJİ",
        "Teknoloji ve Yazılım",
        "SaaS",
        "FINTECH",
    ],
)
def test_hedef_sektor_yazimdan_bagimsiz_eslesir(sector: str) -> None:
    assert _score_for(sector) == 25, f"'{sector}' hedef sektör olarak tanınmalıydı"


@pytest.mark.parametrize("sector", ["Cilt Bakımı", "Gıda", "İnşaat", "Tekstil"])
def test_hedef_disi_sektor_puan_almaz(sector: str) -> None:
    assert _score_for(sector) == 0


def test_ayni_sektorun_farkli_yazimlari_ayni_puani_verir() -> None:
    """Skorun yazım biçimine göre zıplamaması gerekir."""
    varyantlar = ["yazılım", "Yazılım", "YAZILIM", "YAZILIM ve DANIŞMANLIK"]
    puanlar = {_score_for(s) for s in varyantlar}
    assert puanlar == {25}, f"Aynı sektör farklı puanlar aldı: {puanlar}"
