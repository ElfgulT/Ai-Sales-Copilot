"""Yapılandırma (Settings) testleri."""

from __future__ import annotations

import pytest

from app.core.config import Settings


def test_defaults() -> None:
    settings = Settings()
    assert settings.app_name == "AI Sales Copilot"
    assert settings.environment == "development"
    assert settings.is_production is False


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COPILOT_ENVIRONMENT", "production")
    monkeypatch.setenv("COPILOT_LOG_LEVEL", "DEBUG")
    # Üretim ortamı kendi JWT sırrını zorunlu kılar (bkz. aşağıdaki testler);
    # burada asıl ölçtüğümüz şey ortam değişkenlerinin okunması olduğu için
    # geçerli bir sır veriyoruz.
    monkeypatch.setenv("COPILOT_JWT_SECRET", "test-ortamina-ozel-bir-sir-degeri")

    settings = Settings()

    assert settings.environment == "production"
    assert settings.is_production is True
    assert settings.log_level == "DEBUG"


def test_provider_env_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    # Standart env adları (prefix'siz) da çalışmalı.
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "g-123")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-123")
    settings = Settings()
    assert settings.llm_provider == "gemini"
    assert settings.gemini_api_key == "g-123"
    assert settings.anthropic_api_key == "sk-123"


def _isolated(**overrides) -> Settings:
    """Geliştiricinin yerel `.env` dosyasından ve ortam değişkenlerinden bağımsız
    bir `Settings` üretir — aksi halde testin sonucu, testi çalıştıran kişinin
    makinesindeki `.env` içeriğine göre değişir."""
    return Settings(_env_file=None, **overrides)


def test_uretimde_varsayilan_jwt_sirri_reddedilir(monkeypatch: pytest.MonkeyPatch) -> None:
    """`docker-compose.yml` ortamı production yapıyor ve `.env`'i opsiyonel tutuyor.

    Bu koruma olmadan `.env` unutulduğunda uygulama herkesin bildiği bir sırla
    ayağa kalkar ve isteyen kendine geçerli oturum token'ı üretebilir.
    """
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("COPILOT_JWT_SECRET", raising=False)

    with pytest.raises(ValueError, match="JWT"):
        _isolated(environment="production")


def test_uretimde_kendi_sirriyla_acilir() -> None:
    settings = _isolated(
        environment="production", jwt_secret="yeterince-uzun-ve-ozel-bir-sir-degeri"
    )
    assert settings.is_production is True


def test_gelistirmede_varsayilan_sir_serbest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Yerel geliştirmede kurulum sürtünmesi yaratmamalı."""
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("COPILOT_JWT_SECRET", raising=False)

    settings = _isolated(environment="development")
    assert settings.is_production is False


def test_apollo_anahtari_varsayilan_olarak_yok() -> None:
    assert _isolated().apollo_api_key is None


def test_apollo_anahtari_env_ile_okunur(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APOLLO_API_KEY", "apollo-123")
    assert Settings().apollo_api_key == "apollo-123"
