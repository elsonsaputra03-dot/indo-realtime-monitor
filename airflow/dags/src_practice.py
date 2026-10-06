"""Situs latihan scraping (dibuat khusus untuk dipraktikkan): books.toscrape.com dan quotes.toscrape.com.

books : indeks kategori -> setiap kategori dengan pagination ("next") -> judul, harga, rating, stok -> snapshot harian
        (skema riwayat harga; catatan: harga di situs latihan ini statis, yang ditunjukkan adalah tekniknya)
quotes: versi /js/ merender kutipan dengan JavaScript dari data yang tertanam di <script>; data diambil langsung dari
        script itu (lebih ringan dan stabil daripada menjalankan browser headless untuk halaman seperti ini)
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scrape_lib import Polite

BOOKS = "https://books.toscrape.com/"
QUOTES_JS = "https://quotes.toscrape.com/js/"
RATING = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}
BOOK_REQUIRED = ["title", "price_gbp", "rating", "url"]


def parse_categories(html: str, base: str = BOOKS) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    return [(a.get_text(strip=True), urljoin(base, a["href"])) for a in soup.select("div.side_categories ul li ul li a")]


def parse_listing(html: str, page_url: str, category: str) -> tuple[list[dict], str | None]:
    soup = BeautifulSoup(html, "lxml")
    books = []
    for pod in soup.select("article.product_pod"):
        a = pod.select_one("h3 a")
        price = pod.select_one("p.price_color")
        rating = pod.select_one("p.star-rating")
        stock = pod.select_one("p.instock.availability")
        books.append({
            "title": (a.get("title") or a.get_text(strip=True)) if a else "",
            "url": urljoin(page_url, a["href"]) if a and a.get("href") else "",
            "category": category,
            "price_gbp": float(re.sub(r"[^0-9.]", "", price.get_text())) if price and re.search(r"\d", price.get_text()) else None,
            "rating": next((RATING[c] for c in (rating.get("class", []) if rating else []) if c in RATING), None),
            "in_stock": bool(stock and "In stock" in stock.get_text()),
        })
    nxt = soup.select_one("li.next a")
    return books, (urljoin(page_url, nxt["href"]) if nxt else None)


def parse_quotes_js(html: str) -> list[dict]:
    m = re.search(r"var\s+data\s*=\s*(\[.*?\]);", html, re.S)
    if not m:
        return []
    out = []
    for q in json.loads(m.group(1)):
        out.append({"text": q.get("text", "").strip("“”\""), "author": (q.get("author") or {}).get("name", ""),
                    "tags": q.get("tags", [])})
    return out


def fetch_books(c: Polite | None = None, max_pages: int = 200) -> dict:
    c = c or Polite(min_gap=1.0, respect_robots=True)
    rows, errors, pages, t0 = [], [], 0, datetime.now()
    try:
        cats = parse_categories(c.get(BOOKS).text)
        pages += 1
        if not cats:
            errors.append("no categories found (layout changed?)")
        for name, url in cats:
            while url and pages < max_pages:
                books, url = parse_listing(c.get(url).text, url, name)
                pages += 1
                rows += books
    except Exception as e:  # noqa: BLE001
        errors.append(str(e)[:200])
    return {"rows": rows, "errors": errors, "pages": pages, "ms": int((datetime.now() - t0).total_seconds() * 1000), "stats": c.stats}


def fetch_quotes(c: Polite | None = None, max_pages: int = 20) -> dict:
    c = c or Polite(min_gap=1.0, respect_robots=True)
    rows, errors, url, page = [], [], QUOTES_JS, 0
    try:
        while url and page < max_pages:
            html = c.get(url).text
            page += 1
            got = parse_quotes_js(html)
            for q in got:
                q["page"] = page
            rows += got
            nxt = BeautifulSoup(html, "lxml").select_one("li.next a")
            url = urljoin(url, nxt["href"]) if nxt and got else None
    except Exception as e:  # noqa: BLE001
        errors.append(str(e)[:200])
    return {"rows": rows, "errors": errors, "pages": page, "stats": c.stats}
