"""LLM çıktısına eklenen kullanıcıya dönük sistem notları.

Sağlayıcılar (Gemini, Claude) arasında ortak tutulur ki kullanıcı hangi modeli
kullanırsa kullansın aynı ifadeyi görsün.
"""

from __future__ import annotations

# Model, çıktı token bütçesi dolduğu için metni yarıda bıraktığında eklenir.
#
# İFADE NEDEN BÖYLE: Bu durum "API anahtarının kotası bitti" DEĞİLDİR — kota
# bitimi ayrı bir hatadır (HTTP 429) ve kendi mesajıyla karşılanır. Burada olan
# şey, tek bir yanıt için ayrılan çıktı uzunluğu sınırının dolmasıdır; sınırı
# biz belirliyoruz, sağlayıcının ücretlendirme planı değil. Bu yüzden kullanıcıya
# "anahtarınızı yükseltin" demek yanlış yönlendirme olur; yapması gereken tek şey
# yeniden üretmeyi denemektir.
TRUNCATED_OUTPUT_NOTICE = (
    "\n\n⚠️ [Bu metin, modelin tek seferde üretebileceği uzunluk sınırına takıldığı "
    "için yarıda kesildi. '↻ Yeniden üret' düğmesiyle tekrar deneyebilirsiniz.]"
)
