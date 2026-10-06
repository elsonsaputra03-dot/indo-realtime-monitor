"""Klien HTTP "sopan" bersama untuk semua scraper web, plus pemeriksaan kesehatan hasil parsing.

Aturan yang ditegakkan di satu tempat:
- User-Agent jelas dengan alamat kontak (sama dengan scraper berita yang sudah ada)
- Jeda minimum antar-permintaan PER HOST (bukan global), supaya satu situs tidak dibanjiri
- robots.txt dicek per host untuk scraping halaman; untuk API resmi yang punya kebijakan sendiri (BMKG, GitHub,
  Wikipedia API) pemeriksaan robots dimatikan dan yang dipatuhi adalah kebijakan API-nya (batas laju, User-Agent)
- Retry dengan backoff untuk 429/5xx, menghormati header Retry-After
- Conditional GET (ETag / Last-Modified) agar halaman yang tidak berubah tidak diunduh ulang dalam satu proses

Kesehatan parsing: scraper HTML bisa "berhasil" mengunduh halaman tetapi menghasilkan data kosong saat situs mengubah
tata letaknya. health() mendeteksi itu (terlalu sedikit baris atau kolom wajib kosong) sehingga run dilaporkan
sebagai layout_changed, bukan ok.
"""
from __future__ import annotations

import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = "indo-realtime-monitor/0.3 (+https://github.com/elsonsaputra03-dot/indo-realtime-monitor)"


class RobotsDisallowed(Exception):
    pass


class Polite:
    def __init__(self, min_gap: float = 1.0, respect_robots: bool = True, timeout: float = 20, retries: int = 3,
                 headers: dict | None = None, transport: httpx.BaseTransport | None = None, sleep=time.sleep, clock=time.monotonic):
        self.client = httpx.Client(headers={"User-Agent": USER_AGENT, **(headers or {})}, timeout=timeout,
                                   follow_redirects=True, transport=transport)
        self.min_gap, self.respect_robots, self.retries = min_gap, respect_robots, retries
        self.sleep, self.clock = sleep, clock
        self.last: dict[str, float] = {}
        self.robots: dict[str, RobotFileParser | None] = {}
        self.cache: dict[str, tuple[str, str, httpx.Response]] = {}
        self.stats = {"requests": 0, "not_modified": 0, "retries": 0, "robots_blocked": 0}

    def _wait(self, host: str) -> None:
        last = self.last.get(host)
        if last is not None:
            gap = self.min_gap - (self.clock() - last)
            if gap > 0:
                self.sleep(gap)
        self.last[host] = self.clock()

    def allowed(self, url: str) -> bool:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self.robots:
            rp = RobotFileParser()
            try:
                self._wait(p.netloc)
                r = self.client.get(base + "/robots.txt")
                self.stats["requests"] += 1
                if r.status_code >= 400:          # tidak ada robots.txt -> tidak ada larangan
                    rp.parse([])
                else:
                    rp.parse(r.text.splitlines())
                self.robots[base] = rp
            except httpx.HTTPError:
                self.robots[base] = None          # tidak bisa dicek -> jangan scrape
        rp = self.robots[base]
        return bool(rp and rp.can_fetch(USER_AGENT, url))

    def get(self, url: str, params: dict | None = None, headers: dict | None = None) -> httpx.Response:
        if self.respect_robots and not self.allowed(url):
            self.stats["robots_blocked"] += 1
            raise RobotsDisallowed(url)
        host = urlparse(url).netloc
        key = str(httpx.URL(url, params=params))
        h = dict(headers or {})
        if key in self.cache:
            etag, modified, _ = self.cache[key]
            if etag:
                h["If-None-Match"] = etag
            if modified:
                h["If-Modified-Since"] = modified
        for attempt in range(self.retries + 1):
            self._wait(host)
            r = self.client.get(url, params=params, headers=h)
            self.stats["requests"] += 1
            if r.status_code == 304 and key in self.cache:
                self.stats["not_modified"] += 1
                return self.cache[key][2]
            if r.status_code in (429, 500, 502, 503, 504) and attempt < self.retries:
                self.stats["retries"] += 1
                ra = r.headers.get("Retry-After", "")
                self.sleep(float(ra) if ra.isdigit() else 2 ** attempt * 2)
                continue
            r.raise_for_status()
            if r.headers.get("ETag") or r.headers.get("Last-Modified"):
                self.cache[key] = (r.headers.get("ETag", ""), r.headers.get("Last-Modified", ""), r)
            return r
        r.raise_for_status()
        return r

    def close(self) -> None:
        self.client.close()


def health(records: list[dict], required: list[str], min_records: int = 1) -> dict:
    """ok=False bila baris terlalu sedikit atau ada kolom wajib yang kosong di lebih dari 20% baris."""
    missing = {f: sum(1 for r in records if r.get(f) in (None, "", [])) for f in required}
    bad = {f: n for f, n in missing.items() if records and n / len(records) > 0.2}
    ok = len(records) >= min_records and not bad
    reason = "" if ok else (f"only {len(records)} records (expected >= {min_records})" if len(records) < min_records
                            else "missing fields: " + ", ".join(f"{f} ({n}/{len(records)})" for f, n in bad.items()))
    return {"ok": ok, "records": len(records), "missing": missing, "reason": reason}
