"""
Helper untuk DAG news_ingest (bukan DAG).
Etika scraping: User-Agent jelas, cek robots.txt per host, rate limit antar request,
hanya simpan judul + ringkasan pendek + link (bukan artikel penuh).
"""
import hashlib
import html
import json
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlparse
from urllib.robotparser import RobotFileParser

import feedparser
import httpx

USER_AGENT = "indo-realtime-monitor/0.3 (+https://github.com/elsonsaputra03-dot/indo-realtime-monitor)"
SUMMARY_MAX = 280
REQUEST_GAP_SECONDS = 2

# topic -> kata kunci (lowercase). Klasifikasi rule-based; Fase 4 diganti/diperkaya LLM.
TOPICS = {
    "gempa": ["gempa", "tsunami"],
    "banjir_longsor": ["banjir", "longsor", "banjir bandang", "banjir rob"],
    "kebakaran": ["kebakaran hutan", "karhutla", "kebakaran lahan", "titik panas", "hotspot"],
    "gunung_api": ["erupsi", "gunung api", "awan panas", "vulkanik"],
    "cuaca": ["cuaca ekstrem", "hujan lebat", "angin kencang", "puting beliung", "gelombang tinggi",
              "kekeringan", "el nino", "la nina"],
    "kualitas_udara": ["kualitas udara", "polusi udara", "kabut asap", "ispa"],
    "pangan": ["harga beras", "harga cabai", "harga bawang", "harga pangan", "harga telur",
               "harga minyak goreng", "stok beras", "inflasi pangan"],
}

GNEWS = "https://news.google.com/rss/search?q={q}&hl=id&gl=ID&ceid=ID:id"
FEEDS = [
    {"name": "gnews_gempa", "url": GNEWS.format(q=quote("gempa bumi when:1d")), "topic": "gempa"},
    {"name": "gnews_banjir", "url": GNEWS.format(q=quote("banjir OR longsor when:1d")), "topic": "banjir_longsor"},
    {"name": "gnews_karhutla", "url": GNEWS.format(q=quote("karhutla OR \"kebakaran hutan\" when:1d")), "topic": "kebakaran"},
    {"name": "gnews_erupsi", "url": GNEWS.format(q=quote("erupsi gunung when:1d")), "topic": "gunung_api"},
    {"name": "gnews_cuaca", "url": GNEWS.format(q=quote("\"cuaca ekstrem\" BMKG when:1d")), "topic": "cuaca"},
    {"name": "gnews_udara", "url": GNEWS.format(q=quote("\"kualitas udara\" OR \"kabut asap\" when:1d")), "topic": "kualitas_udara"},
    {"name": "gnews_pangan", "url": GNEWS.format(q=quote("\"harga beras\" OR \"harga cabai\" when:1d")), "topic": "pangan"},
    # Portal umum: hanya item yang cocok dengan salah satu topik yang disimpan
    {"name": "antara_terkini", "url": "https://www.antaranews.com/rss/terkini.xml", "topic": None},
    {"name": "cnnindonesia_nasional", "url": "https://www.cnnindonesia.com/nasional/rss", "topic": None},
    {"name": "tempo_nasional", "url": "https://rss.tempo.co/nasional", "topic": None},
]

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_robots_cache: dict[str, RobotFileParser | None] = {}


def clean_text(s: str | None, limit: int | None = None) -> str:
    t = _WS.sub(" ", html.unescape(_TAG.sub(" ", s or ""))).strip()
    if limit and len(t) > limit:
        t = t[: limit - 1].rsplit(" ", 1)[0] + "…"
    return t


def classify(text: str) -> list[str]:
    low = text.lower()
    return [topic for topic, kws in TOPICS.items() if any(k in low for k in kws)]


def robots_allowed(client: httpx.Client, url: str) -> bool:
    host = urlparse(url)
    base = f"{host.scheme}://{host.netloc}"
    if base not in _robots_cache:
        rp = RobotFileParser()
        try:
            r = client.get(base + "/robots.txt", timeout=15)
            if r.status_code in (401, 403):
                rp.disallow_all = True
            elif r.status_code >= 400:
                rp.allow_all = True
            else:
                rp.parse(r.text.splitlines())
            _robots_cache[base] = rp
        except httpx.HTTPError:
            _robots_cache[base] = None      # tidak bisa dicek -> jangan scrape dulu
    rp = _robots_cache[base]
    return bool(rp and rp.can_fetch(USER_AGENT, url))


def parse_feed(feed: dict, content: bytes) -> list[dict]:
    parsed = feedparser.parse(content)
    publisher_default = clean_text(parsed.feed.get("title", feed["name"]))
    items = []
    for e in parsed.entries:
        link = e.get("link", "")
        title = clean_text(e.get("title"))
        if not link or not title:
            continue
        publisher = clean_text((e.get("source") or {}).get("title")) or publisher_default
        if feed["name"].startswith("gnews_") and title.endswith(" - " + publisher):
            title = title[: -len(" - " + publisher)]
        summary = clean_text(e.get("summary"), SUMMARY_MAX)
        if summary.startswith(title):          # Google News: summary = judul + publisher
            summary = ""
        topics = classify(f"{title} {summary}")
        if feed["topic"] and feed["topic"] not in topics:
            topics.append(feed["topic"])
        if not topics:                          # portal umum: buang yang tidak relevan
            continue
        ts = e.get("published_parsed") or e.get("updated_parsed")
        published = (datetime(*ts[:6], tzinfo=timezone.utc) if ts else datetime.now(timezone.utc))
        items.append({
            "news_id": hashlib.sha1(link.encode()).hexdigest()[:20],
            "feed": feed["name"],
            "publisher": publisher[:120],
            "title": title[:300],
            "link": link,
            "summary": summary,
            "published_at": published.isoformat(),
            "topics": sorted(set(topics)),
        })
    return items


def fetch_feed(feed: dict) -> dict:
    """Satu feed -> {'feed','status','items','error'}; tidak pernah raise (dipakai di task mapping)."""
    t0 = time.monotonic()
    out = {"feed": feed["name"], "status": "ok", "items": [], "error": "", "ms": 0}
    try:
        with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True,
                          timeout=httpx.Timeout(20, read=60),
                          transport=httpx.HTTPTransport(retries=2)) as client:
            if not robots_allowed(client, feed["url"]):
                out.update(status="skipped", error="robots.txt tidak mengizinkan / tidak bisa dicek")
            else:
                time.sleep(REQUEST_GAP_SECONDS)
                r = client.get(feed["url"])
                r.raise_for_status()
                out["items"] = parse_feed(feed, r.content)
    except Exception as exc:  # noqa: BLE001
        out.update(status="error", error=f"{type(exc).__name__}: {exc}"[:300])
    out["ms"] = int((time.monotonic() - t0) * 1000)
    return out


def kafka_config() -> dict:
    return {"bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP", "redpanda:9092"),
            "enable.idempotence": True, "compression.type": "zstd", "linger.ms": 50}


def ch_client():
    import clickhouse_connect
    return clickhouse_connect.get_client(
        host=os.getenv("CLICKHOUSE_HOST", "clickhouse"), port=8123,
        username=os.getenv("CLICKHOUSE_USER", "default"),
        password=os.getenv("CLICKHOUSE_PASSWORD", ""),
        database=os.getenv("CLICKHOUSE_DB", "irm"))


def dumps(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)
