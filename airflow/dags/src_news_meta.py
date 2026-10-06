"""Metadata artikel berita dari halaman HTML-nya: judul, waktu terbit, rubrik, penulis, kata kunci.

Sengaja HANYA metadata: isi artikel adalah konten berhak cipta dan tidak disimpan. Sumber metadata, berurutan:
1. JSON-LD schema.org (NewsArticle/Article/ReportageNewsArticle), termasuk di dalam @graph
2. Open Graph / meta article:* sebagai cadangan
Tautan artikel diambil dari feed RSS yang sudah dipakai IRM. robots.txt dicek untuk setiap URL artikel, jeda 2 detik
per host, dan hanya beberapa artikel terbaru per feed per run.
"""
from __future__ import annotations

import json
from datetime import datetime
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from scrape_lib import Polite, RobotsDisallowed

ARTICLE_TYPES = {"NewsArticle", "Article", "ReportageNewsArticle", "AnalysisNewsArticle", "BlogPosting"}
REQUIRED = ["headline", "published_at"]


def _as_list(v):
    return v if isinstance(v, list) else [] if v is None else [v]


def _names(v) -> list[str]:
    out = []
    for a in _as_list(v):
        n = a.get("name") if isinstance(a, dict) else a
        if isinstance(n, str) and n.strip():
            out.append(n.strip())
    return out


def _jsonld_article(soup) -> dict | None:
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for node in _as_list(data):
            for item in [node, *_as_list(node.get("@graph") if isinstance(node, dict) else None)]:
                if isinstance(item, dict) and set(_as_list(item.get("@type"))) & ARTICLE_TYPES:
                    return item
    return None


def extract(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    meta = lambda **kv: (soup.find("meta", attrs=kv) or {}).get("content", "")   # noqa: E731
    a = _jsonld_article(soup)
    if a:
        kw = a.get("keywords", [])
        kws = [k.strip() for k in (kw.split(",") if isinstance(kw, str) else _as_list(kw)) if isinstance(k, str) and k.strip()]
        sec = a.get("articleSection", "")
        return {"url": url, "site": urlparse(url).netloc, "headline": (a.get("headline") or "").strip()[:500],
                "published_at": a.get("datePublished", ""), "modified_at": a.get("dateModified", ""),
                "section": (sec[0] if isinstance(sec, list) and sec else sec or "")[:120],
                "authors": _names(a.get("author"))[:10], "keywords": kws[:30], "method": "json-ld"}
    title = meta(property="og:title") or (soup.title.get_text(strip=True) if soup.title else "")
    kws = [k.strip() for k in meta(name="keywords").split(",") if k.strip()]
    return {"url": url, "site": urlparse(url).netloc, "headline": title[:500],
            "published_at": meta(property="article:published_time"), "modified_at": meta(property="article:modified_time"),
            "section": meta(property="article:section")[:120], "authors": [x for x in [meta(name="author")] if x],
            "keywords": kws[:30], "method": "opengraph" if title else "none"}


REFUSED = {401, 403, 451}


def fetch(article_urls: list[str], c: Polite | None = None) -> dict:
    """Situs yang menolak bot (401/403/451) dihormati: sisa URL dari host itu dilewati dalam run yang sama dan dicatat
    sebagai penolakan, bukan error kode. Ditemukan saat run pertama: tempo.co mengizinkan di robots.txt tetapi
    membalas 403 untuk User-Agent scraper."""
    import httpx
    c = c or Polite(min_gap=2.0, respect_robots=True)
    rows, errors, blocked, refused, t0 = [], [], 0, {}, datetime.now()
    for url in article_urls:
        host = urlparse(url).netloc
        if host in refused:
            refused[host] += 1
            continue
        try:
            rows.append(extract(c.get(url).text, url))
        except RobotsDisallowed:
            blocked += 1
        except httpx.HTTPStatusError as e:
            if e.response.status_code in REFUSED:
                refused[host] = 1
            else:
                errors.append(f"{url}: HTTP {e.response.status_code}"[:200])
        except Exception as e:  # noqa: BLE001
            errors.append(f"{url}: {type(e).__name__}"[:200])
    return {"rows": rows, "errors": errors, "robots_blocked": blocked, "refused": refused,
            "ms": int((datetime.now() - t0).total_seconds() * 1000), "stats": c.stats}
