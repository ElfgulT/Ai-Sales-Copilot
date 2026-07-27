"""Kesilen çıktıda yeniden deneme davranışının testi."""
from __future__ import annotations
import pytest
from app.infrastructure.llm.gemini_provider import GeminiLLMProvider


class _FakeResp:
    def __init__(self, text, reason):
        self.text = text
        self.candidates = [type("C", (), {
            "finish_reason": reason,
            "content": type("Ct", (), {"parts": [type("P", (), {"text": text})()]})(),
        })()]


@pytest.mark.asyncio
async def test_kesilen_cikti_daha_buyuk_butceyle_tekrar_denenir(monkeypatch):
    provider = GeminiLLMProvider.__new__(GeminiLLMProvider)
    provider._max_tokens = 4096
    calls = []

    async def fake_raw(*, system, contents, max_tokens, json_mode):
        calls.append(max_tokens)
        if len(calls) == 1:
            return _FakeResp("yarim kalan cumle", "FinishReason.MAX_TOKENS")
        return _FakeResp("tam ve eksiksiz bir cumle olarak biter.", "FinishReason.STOP")

    monkeypatch.setattr(provider, "_generate_raw", fake_raw)
    out = await provider.generate_text(system="s", prompt="p", max_tokens=4096)

    assert calls == [4096, 8192], f"beklenen butce artisi olmadi: {calls}"
    assert out == "tam ve eksiksiz bir cumle olarak biter."


@pytest.mark.asyncio
async def test_kesilme_yoksa_tek_cagri_yapilir(monkeypatch):
    provider = GeminiLLMProvider.__new__(GeminiLLMProvider)
    provider._max_tokens = 4096
    calls = []

    async def fake_raw(*, system, contents, max_tokens, json_mode):
        calls.append(max_tokens)
        return _FakeResp("tamam", "FinishReason.STOP")

    monkeypatch.setattr(provider, "_generate_raw", fake_raw)
    out = await provider.generate_text(system="s", prompt="p", max_tokens=4096)

    assert calls == [4096], "gereksiz ikinci cagri yapildi"
    assert out == "tamam"


@pytest.mark.asyncio
async def test_yeniden_deneme_de_kesilirse_kullaniciya_bildirilir(monkeypatch):
    """Yarım metni sessizce sunmak kabul edilemez; kullanıcı neden yarım olduğunu
    görmeli ve ne yapacağını bilmeli."""
    from app.infrastructure.llm.notices import TRUNCATED_OUTPUT_NOTICE

    provider = GeminiLLMProvider.__new__(GeminiLLMProvider)
    provider._max_tokens = 4096

    async def fake_raw(*, system, contents, max_tokens, json_mode):
        return _FakeResp("cumle yarida kal", "FinishReason.MAX_TOKENS")

    monkeypatch.setattr(provider, "_generate_raw", fake_raw)
    out = await provider.generate_text(system="s", prompt="p", max_tokens=4096)

    assert out.startswith("cumle yarida kal")
    assert TRUNCATED_OUTPUT_NOTICE.strip() in out
    # Yanlış yönlendirme yapmamalı: bu bir kota/fatura sorunu DEĞİL.
    assert "kota" not in out.lower()
    assert "yükselt" not in out.lower()


@pytest.mark.asyncio
async def test_kesilme_yoksa_not_eklenmez(monkeypatch):
    from app.infrastructure.llm.notices import TRUNCATED_OUTPUT_NOTICE

    provider = GeminiLLMProvider.__new__(GeminiLLMProvider)
    provider._max_tokens = 4096

    async def fake_raw(*, system, contents, max_tokens, json_mode):
        return _FakeResp("tam metin.", "FinishReason.STOP")

    monkeypatch.setattr(provider, "_generate_raw", fake_raw)
    out = await provider.generate_text(system="s", prompt="p", max_tokens=4096)

    assert out == "tam metin."
    assert TRUNCATED_OUTPUT_NOTICE.strip() not in out
