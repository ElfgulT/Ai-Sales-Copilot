"""`build_scraped_content` / `absolute_links` testleri."""

from __future__ import annotations

from app.infrastructure.scraping.content_builder import absolute_links, build_scraped_content
from app.infrastructure.scraping.html_cleaner import clean_html


def test_relative_links_become_absolute() -> None:
    links = absolute_links(
        "https://example.com/tr/anasayfa",
        ("/hakkimizda", "iletisim", "https://other.com/x"),
    )
    assert links == (
        "https://example.com/hakkimizda",
        "https://example.com/tr/iletisim",
        "https://other.com/x",
    )


def test_drops_non_page_hrefs_and_fragments() -> None:
    links = absolute_links(
        "https://example.com/",
        ("#bolum", "mailto:a@b.com", "tel:+900000", "javascript:void(0)", "/a#ust", "/a"),
    )
    # Fragment atıldığı için "/a#ust" ile "/a" tek adres sayılır.
    assert links == ("https://example.com/a",)


def test_build_scraped_content_fills_absolute_links() -> None:
    doc = clean_html('<html><body><a href="/about">Hakkında</a></body></html>')
    content = build_scraped_content("https://example.com/tr/", doc, renderer="static")
    assert content.links == ("https://example.com/about",)
