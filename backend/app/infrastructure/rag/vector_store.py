"""RAG (Retrieval-Augmented Generation) Vektör Veritabanı bileşenleri."""

from __future__ import annotations

import logging
from typing import Sequence

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.domain.interfaces import VectorStore

logger = logging.getLogger(__name__)


class SimpleVectorStore(VectorStore):
    """TF-IDF & Cosine Similarity tabanlı yerel Vektör Veritabanı.

    Metin parçalarını (chunks) indeksler ve anlamsal/kelime TF-IDF benzerliğine göre
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

        logger.info("Vektör veritabanına %d doküman parçası (chunk) TF-IDF ile indekslendi.", len(self._documents))

    async def query(self, query_text: str, top_k: int = 3) -> list[str]:
        if not self._documents or not query_text.strip():
            return []

        try:
            vectorizer = TfidfVectorizer().fit(self._documents + [query_text])
            doc_vectors = vectorizer.transform(self._documents)
            query_vector = vectorizer.transform([query_text])

            similarities = cosine_similarity(query_vector, doc_vectors).flatten()

            # Skorlara göre sırala
            indexed_scores = list(enumerate(similarities))
            indexed_scores.sort(key=lambda x: x[1], reverse=True)

            results = [self._documents[idx] for idx, score in indexed_scores[:top_k] if score > 0.0]
            if not results and self._documents:
                results = self._documents[:top_k]

            return results
        except Exception as exc:
            logger.warning("Vektör aramada hata: %s, fallback uygulanıyor.", exc)
            return self._documents[:top_k]
