"""SimpleVectorStore RAG unit testleri."""

from __future__ import annotations

import pytest

from app.infrastructure.rag.vector_store import SimpleVectorStore


@pytest.mark.asyncio
async def test_vector_store_add_and_query() -> None:
    store = SimpleVectorStore(chunk_size=100)
    docs = [
        "Otokar savunma sanayinde lider otobüs ve zırhlı araç üreticisidir.",
        "GitHub yazılımcılar için kod barındırma ve CI/CD platformudur.",
    ]
    await store.add_documents(docs)

    results = await store.query("otobüs savunma araç")
    assert len(results) > 0
    assert "Otokar" in results[0] or "savunma" in results[0]


@pytest.mark.asyncio
async def test_vector_store_empty_documents() -> None:
    store = SimpleVectorStore()
    results = await store.query("test")
    assert results == []
