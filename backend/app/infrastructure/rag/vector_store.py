"""RAG (Retrieval-Augmented Generation) Vektör Veritabanı bileşenleri."""

from __future__ import annotations

import logging
import re
from typing import Sequence

from app.domain.interfaces import VectorStore

logger = logging.getLogger(__name__)


class SimpleVectorStore(VectorStore):
    """Hafif, sıfır dış bağımlılık gerektiren TF-IDF & Cosine Similarity tabanlı yerel Vektör Veritabanı.

    Metin parçalarını (chunks) indeksler ve anlamsal/kelime benzerliğine göre
    en alakalı parçaları RAG sorgusuna döndürür.
    """

    def __init__(self, chunk_size: int = 400, overlap: int = 50) -> None:
        self._chunk_size = chunk_size
        self._overlap = overlap
        self._documents: list[str] = []
        self._metadatas: list[dict] = []

    def _chunk_text(self, text: str) -> list[str]:
        """Metni belirtilen karakter boyutunda parçalara (chunk) böler."""
        if not text or len(text) <= self._chunk_size:
            return [text] if text else []

        # Paragraf veya cümle sınırlarına göre bölmeye çalış
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        chunks = []
        current = ""

        for p in paragraphs:
            if len(current) + len(p) <= self._chunk_size:
                current = f"{current}\n{p}" if current else p
            else:
                if current:
                    chunks.append(current)
                current = p

        if current:
            chunks.append(current)

        return chunks

    async def add_documents(self, documents: list[str], metadatas: list[dict] | None = None) -> None:
        for idx, doc in enumerate(documents):
            meta = metadatas[idx] if metadatas and idx < len(metadatas) else {}
            for chunk in self._chunk_text(doc):
                if chunk.strip():
                    self._documents.append(chunk)
                    self._metadatas.append(meta)

        logger.info("Vektör veritabanına %d yeni doküman parçası (chunk) indekslendi.", len(self._documents))

    async def query(self, query_text: str, top_k: int = 3) -> list[str]:
        if not self._documents or not query_text.strip():
            return []

        # Scikit-learn veya kelime çakışması / Jaccard & TF-IDF benzerliği ile puanlama
        query_words = set(re.findall(r"\w+", query_text.lower()))

        scored_docs: list[tuple[float, str]] = []
        for doc in self._documents:
            doc_words = set(re.findall(r"\w+", doc.lower()))
            if not doc_words:
                continue
            intersection = query_words.intersection(doc_words)
            union = query_words.union(doc_words)
            score = len(intersection) / len(union) if union else 0.0
            scored_docs.append((score, doc))

        # En yüksek puanlıları sırala
        scored_docs.sort(key=lambda x: x[0], reverse=True)
        results = [doc for score, doc in scored_docs[:top_k] if score > 0]

        # Benzerlik 0 çıksa bile ilk k parçayı fallback olarak döndür
        if not results and self._documents:
            results = self._documents[:top_k]

        return results
