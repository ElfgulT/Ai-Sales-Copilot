"""Gemini (Google AI Studio) tabanlı `LLMProvider` implementasyonu.

`ClaudeLLMProvider` ile AYNI arayüzü (`LLMProvider`) uygular; uygulamanın geri
kalanı hangi sağlayıcının kullanıldığını bilmez (Liskov / DIP). Ücretsiz Google
AI Studio API anahtarıyla çalışır.

ÜRETİM NOTLARI (Gemini 2.5 Flash uyumluluğu):
- Gemini 2.5 Flash bir "düşünen" (thinking) modeldir; düşünme token'ları
  `max_output_tokens` bütçesinden harcanır. İçerik zenginleştiğinde çıktı yarıda
  kesilebilir (MAX_TOKENS).
  `google-genai` 1.2.0'da `ThinkingConfig`'in tek alanı `include_thoughts` kaldı;
  `thinking_budget` KALDIRILDI. DİKKAT: `include_thoughts=False` düşünmeyi
  kapatmaz — yalnızca düşünceleri yanıttan gizler. Model yine düşünür ve token
  bütçesini yine tüketir. Bu yüzden kesilmeye karşı tek korumamız token
  limitlerini yeterince yüksek tutmaktır (bkz. `config.py`: llm_max_tokens,
  llm_email_max_tokens, llm_pitch_max_tokens).
- Yanıt metni birden çok yoldan güvenle çıkarılır: candidates -> content.parts
  -> part.text; olmazsa `response.text`.
- JSON ayrıştırma toleranslıdır: düz JSON, ```json``` çitli, önünde/arkasında
  fazladan metin olan çıktılar desteklenir.
- Ayrıştırma başarısızsa TAM yanıt ve `finish_reason` loglanır.

`google.genai` import'u tembeldir: paket/anahtar yoksa modül import'u uygulamayı
çökertmez.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator

from app.core.exceptions import LLMError
from app.domain.interfaces import LLMProvider
from app.infrastructure.llm.notices import TRUNCATED_OUTPUT_NOTICE

logger = logging.getLogger(__name__)


class GeminiLLMProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        *,
        model: str = "gemini-2.5-flash",
        max_tokens: int = 4096,
    ):
        import google.genai as genai

        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    async def _generate_raw(self, *, system: str, contents: str, max_tokens: int, json_mode: bool):
        """generate_content'i sarıp Gemini hatalarını `LLMError`'a çevirir ve ham
        yanıt nesnesini döndürür (metin çıkarımı ayrı yapılır)."""
        from google.genai import errors, types

        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            response_mime_type="application/json" if json_mode else "text/plain",
            # Düşünceleri yanıttan gizler. Düşünmeyi KAPATMAZ (SDK 1.2.0'da böyle
            # bir seçenek yok) — token bütçesi yine düşünmeyle paylaşılır.
            thinking_config=types.ThinkingConfig(include_thoughts=False),
        )
        try:
            return await self._client.aio.models.generate_content(
                model=self._model, contents=contents, config=config
            )
        except errors.ClientError as exc:
            code = getattr(exc, "code", None)
            if code in (401, 403) or "API key" in str(exc) or "API_KEY" in str(exc):
                logger.error("Gemini kimlik doğrulama hatası: %s", exc)
                raise LLMError("Analiz servisi yapılandırması hatalı (API anahtarı).") from exc
            if code == 429:
                raise LLMError(
                    "Analiz servisi şu an yoğun (kota). Lütfen birazdan tekrar deneyin."
                ) from exc
            logger.error("Gemini istemci hatası: %s", exc)
            raise LLMError() from exc
        except errors.ServerError as exc:
            raise LLMError("Analiz servisine ulaşılamadı. Lütfen tekrar deneyin.") from exc
        except errors.APIError as exc:
            logger.error("Gemini API hatası: %s", exc)
            raise LLMError() from exc

    async def extract_structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: dict,
        tool_name: str,
        tool_description: str,
    ) -> dict:
        contents = (
            f"{prompt}\n\n"
            "YALNIZCA aşağıdaki JSON şemasına uygun, geçerli bir JSON nesnesi döndür. "
            "Açıklama, markdown veya ek metin ekleme:\n"
            f"{json.dumps(schema, ensure_ascii=False)}"
        )
        response = await self._generate_raw(
            system=system, contents=contents, max_tokens=self._max_tokens, json_mode=True
        )
        text, finish_reason = self._extract_text(response)
        return self._parse_json(text, finish_reason)

    # Kesilme durumunda bütçe bu katsayıyla bir kez büyütülüp yeniden denenir.
    _RETRY_TOKEN_MULTIPLIER = 2
    _MAX_TOKEN_CEILING = 16384

    async def generate_text(self, *, system: str, prompt: str, max_tokens: int) -> str:
        """Serbest metin üretir; çıktı kesilirse bütçeyi büyütüp BİR KEZ yeniden dener.

        NEDEN: Gemini 2.5 Flash'ın düşünme token'ları `max_output_tokens`
        bütçesinden harcanır ve harcanan miktar çağrıdan çağrıya değişir. Sabit bir
        limit bu yüzden güvenilir değil — 4096 token ile bile e-posta/pitch cümle
        ortasında kesilebiliyor. Kesilmeyi `finish_reason` üzerinden tespit edip
        daha geniş bir bütçeyle tekrar denemek, limiti sürekli yükseltmekten hem
        daha güvenilir hem de daha ucuz (yalnızca gerektiğinde ödeme yapılır).
        """
        text, finish_reason = await self._generate_once(
            system=system, prompt=prompt, max_tokens=max_tokens
        )

        if self._is_truncated(finish_reason):
            retry_tokens = min(
                max_tokens * self._RETRY_TOKEN_MULTIPLIER, self._MAX_TOKEN_CEILING
            )
            if retry_tokens > max_tokens:
                logger.warning(
                    "Çıktı kesildi (MAX_TOKENS). Bütçe %d -> %d yapılıp yeniden deneniyor.",
                    max_tokens,
                    retry_tokens,
                )
                retry_text, retry_reason = await self._generate_once(
                    system=system, prompt=prompt, max_tokens=retry_tokens
                )
                # Yeniden deneme de kesilebilir; yine de daha uzun olanı tercih et.
                if retry_text and len(retry_text) >= len(text):
                    text, finish_reason = retry_text, retry_reason

        if not text:
            logger.error("Gemini boş metin döndürdü (finish_reason=%s).", finish_reason)
            raise LLMError("Analiz servisi boş yanıt döndürdü.")

        if self._is_truncated(finish_reason):
            # Yeniden deneme de yetmedi: yarım metni sessizce sunmak yerine
            # kesildiğini kullanıcıya söylüyoruz.
            logger.warning("Çıktı yeniden denemeden sonra da kesik kaldı.")
            return text.strip() + TRUNCATED_OUTPUT_NOTICE

        return text.strip()

    async def _generate_once(
        self, *, system: str, prompt: str, max_tokens: int
    ) -> tuple[str, object | None]:
        response = await self._generate_raw(
            system=system, contents=prompt, max_tokens=max_tokens, json_mode=False
        )
        return self._extract_text(response)

    @staticmethod
    def _is_truncated(finish_reason: object | None) -> bool:
        return finish_reason is not None and str(finish_reason).endswith("MAX_TOKENS")

    # --- Yanıt çıkarımı ve ayrıştırma ---

    @staticmethod
    def _extract_text(response) -> tuple[str, object | None]:
        """Yanıttan metni ve finish_reason'ı sağlam biçimde çıkarır.

        Öncelik: candidates[].content.parts[].text (en güvenilir). Boşsa
        `response.text` kısayoluna düşülür.
        """
        candidates = getattr(response, "candidates", None) or []
        finish_reason = getattr(candidates[0], "finish_reason", None) if candidates else None

        chunks: list[str] = []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            for part in (getattr(content, "parts", None) or []):
                part_text = getattr(part, "text", None)
                if part_text:
                    chunks.append(part_text)
        text = "".join(chunks)

        if not text:
            try:
                text = response.text or ""
            except Exception:  # response.text bazı durumlarda hata fırlatabilir
                text = ""

        if finish_reason is not None and str(finish_reason).endswith("MAX_TOKENS"):
            logger.warning(
                "Gemini yanıtı token limitine takıldı (MAX_TOKENS); çıktı kesilmiş olabilir."
            )
        return text, finish_reason

    @classmethod
    def _parse_json(cls, text: str, finish_reason: object | None = None) -> dict:
        for candidate in cls._json_candidates(text):
            try:
                data = json.loads(candidate)
            except (ValueError, TypeError):
                continue
            if isinstance(data, dict):
                return data

        # Başarısız: TAM yanıtı ve finish_reason'ı logla (teşhis için).
        logger.error(
            "Gemini geçerli JSON döndürmedi (finish_reason=%s). Tam yanıt:\n%s",
            finish_reason,
            text,
        )
        if finish_reason is not None and str(finish_reason).endswith("MAX_TOKENS"):
            raise LLMError(
                "Analiz çıktısı token limitine takıldı. Lütfen tekrar deneyin."
            )
        raise LLMError("Analiz modeli beklenen yapılandırılmış çıktıyı döndürmedi.")

    @staticmethod
    def _json_candidates(text: str) -> Iterator[str]:
        """Metinden olası JSON gövdelerini üretir (düz, çitli, gömülü)."""
        stripped = (text or "").strip()
        if not stripped:
            return

        # 1) Doğrudan
        yield stripped

        # 2) Markdown kod çitini kaldır: ```json ... ``` veya ``` ... ```
        if stripped.startswith("```"):
            body = stripped[3:]
            if body[:4].lower() == "json":
                body = body[4:]
            end = body.rfind("```")
            if end != -1:
                body = body[:end]
            yield body.strip()

        # 3) İlk '{' ile son '}' arası (önde/arkada fazladan metin varsa)
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start != -1 and end > start:
            yield stripped[start : end + 1]
