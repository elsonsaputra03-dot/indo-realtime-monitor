"""
Producer gempa: BMKG (gempaterkini + gempadirasakan) dan USGS (bbox Indonesia).
- Normalisasi ke satu skema -> topic raw.earthquake
- Hanya kirim event baru (seen-cache), dedup final di ClickHouse ReplacingMergeTree
- Setiap run kirim heartbeat ke ops.ingest_run (untuk monitoring & DQ)
"""
import hashlib
import logging
import os
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

import httpx

from common import kafka_producer, send, utcnow_iso

log = logging.getLogger("producer.earthquake")

TOPIC = "raw.earthquake"
RUN_TOPIC = "ops.ingest_run"
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "60"))
USER_AGENT = "indo-realtime-monitor/0.1 (portfolio project)"

BMKG_URLS = [
    "https://data.bmkg.go.id/DataMKG/TEWS/gempaterkini.json",   # 15 gempa M5+ terbaru
    "https://data.bmkg.go.id/DataMKG/TEWS/gempadirasakan.json",  # 15 gempa dirasakan terbaru
]
USGS_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
INDONESIA_BBOX = dict(minlatitude=-11.5, maxlatitude=6.5, minlongitude=94.5, maxlongitude=141.5)


class SeenCache:
    """LRU sederhana supaya event yang sama tidak dikirim ulang tiap polling."""

    def __init__(self, maxsize: int = 5000):
        self._d: OrderedDict[str, None] = OrderedDict()
        self.maxsize = maxsize

    def add_if_new(self, key: str) -> bool:
        if key in self._d:
            self._d.move_to_end(key)
            return False
        self._d[key] = None
        if len(self._d) > self.maxsize:
            self._d.popitem(last=False)
        return True


def _to_float(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        return float(str(text).replace(",", ".").split()[0])
    except (ValueError, IndexError):
        return None


def normalize_bmkg(g: dict) -> dict | None:
    """Contoh field BMKG: DateTime, Coordinates '-2.39,120.93', Magnitude, Kedalaman '10 km', Wilayah."""
    coords = (g.get("Coordinates") or "").split(",")
    if len(coords) != 2 or not g.get("DateTime"):
        return None
    lat, lon = _to_float(coords[0]), _to_float(coords[1])
    mag = _to_float(g.get("Magnitude"))
    if lat is None or lon is None or mag is None:
        return None
    raw_id = f"{g['DateTime']}|{lat:.2f}|{lon:.2f}|{mag:.1f}"
    return {
        "event_id": "bmkg-" + hashlib.sha1(raw_id.encode()).hexdigest()[:16],
        "source": "bmkg",
        "event_time": g["DateTime"],
        "lat": lat,
        "lon": lon,
        "magnitude": mag,
        "depth_km": _to_float(g.get("Kedalaman")) or 0.0,
        "region": g.get("Wilayah", ""),
        "felt": g.get("Dirasakan", "") or "",
    }


def normalize_usgs(f: dict) -> dict | None:
    p, geom = f.get("properties", {}), f.get("geometry", {})
    c = geom.get("coordinates") or []
    if len(c) < 2 or p.get("time") is None or p.get("mag") is None:
        return None
    return {
        "event_id": "usgs-" + f["id"],
        "source": "usgs",
        "event_time": datetime.fromtimestamp(p["time"] / 1000, tz=timezone.utc).isoformat(),
        "lat": float(c[1]),
        "lon": float(c[0]),
        "magnitude": float(p["mag"]),
        "depth_km": float(c[2]) if len(c) > 2 and c[2] is not None else 0.0,
        "region": p.get("place") or "",
        "felt": str(p.get("felt") or ""),
    }


def fetch_bmkg(client: httpx.Client) -> list[dict]:
    events = []
    for url in BMKG_URLS:
        r = client.get(url)
        r.raise_for_status()
        gempa = r.json().get("Infogempa", {}).get("gempa", [])
        if isinstance(gempa, dict):
            gempa = [gempa]
        events += [e for e in (normalize_bmkg(g) for g in gempa) if e]
    return events


def fetch_usgs(client: httpx.Client) -> list[dict]:
    start = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S")
    r = client.get(USGS_URL, params={"format": "geojson", "starttime": start, **INDONESIA_BBOX})
    r.raise_for_status()
    return [e for e in (normalize_usgs(f) for f in r.json().get("features", [])) if e]


SOURCES = {"bmkg": fetch_bmkg, "usgs": fetch_usgs}


def run_forever() -> None:
    producer = kafka_producer()
    seen = SeenCache()
    with httpx.Client(transport=httpx.HTTPTransport(retries=3), timeout=20, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        while True:
            for name, fetch in SOURCES.items():
                t0 = time.monotonic()
                run = {"source": name, "run_at": utcnow_iso(), "status": "ok",
                       "fetched": 0, "new_records": 0, "latency_ms": 0, "error": ""}
                try:
                    events = fetch(client)
                    run["fetched"] = len(events)
                    ingested_at = utcnow_iso()
                    for ev in events:
                        if seen.add_if_new(ev["event_id"]):
                            send(producer, TOPIC, ev["event_id"], {**ev, "ingested_at": ingested_at})
                            run["new_records"] += 1
                except Exception as exc:  # noqa: BLE001 - catat semua error ke run log
                    run["status"] = "error"
                    run["error"] = f"{type(exc).__name__}: {exc}"[:500]
                    log.exception("fetch %s gagal", name)
                run["latency_ms"] = int((time.monotonic() - t0) * 1000)
                send(producer, RUN_TOPIC, name, run)
                log.info("%s status=%s fetched=%d new=%d %dms", name, run["status"],
                         run["fetched"], run["new_records"], run["latency_ms"])
            producer.flush(10)
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run_forever()
