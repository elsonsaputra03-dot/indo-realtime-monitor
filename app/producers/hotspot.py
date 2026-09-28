"""
NASA FIRMS hotspot (titik panas / potensi kebakaran) untuk bbox Indonesia.
API: https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{SOURCE}/{W,S,E,N}/{DAY_RANGE}
Butuh FIRMS_MAP_KEY (gratis). Data NRT, latensi satelit ~3 jam.
"""
import csv
import hashlib
import io
import os
from datetime import datetime, timezone

import httpx

from producers.base import run_source

MAP_KEY = os.getenv("FIRMS_MAP_KEY", "").strip()
SENSORS = os.getenv("FIRMS_SOURCES", "VIIRS_SNPP_NRT,VIIRS_NOAA20_NRT").split(",")
BBOX = "94.5,-11.5,141.5,6.5"   # west,south,east,north
POLL_SECONDS = int(os.getenv("FIRMS_POLL_SECONDS", "900"))
DAY_RANGE = int(os.getenv("FIRMS_DAY_RANGE", "2"))
BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def normalize(row: dict, sensor: str) -> dict | None:
    try:
        t = str(row["acq_time"]).zfill(4)
        acq = datetime.strptime(f"{row['acq_date']} {t}", "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc)
        lat, lon = float(row["latitude"]), float(row["longitude"])
    except (KeyError, ValueError):
        return None
    sat = row.get("satellite", "")
    raw_id = f"{sensor}|{acq.isoformat()}|{lat:.4f}|{lon:.4f}"
    return {
        "event_id": "firms-" + hashlib.sha1(raw_id.encode()).hexdigest()[:16],
        "sensor": sensor,
        "satellite": sat,
        "acq_time": acq.isoformat(),
        "lat": lat,
        "lon": lon,
        "confidence": str(row.get("confidence", "")),
        "frp": _f(row.get("frp")),
        "brightness": _f(row.get("bright_ti4") or row.get("brightness")),
        "daynight": row.get("daynight", ""),
    }


def fetch(client: httpx.Client) -> list[dict]:
    if not MAP_KEY:
        raise RuntimeError("FIRMS_MAP_KEY belum diisi di .env")
    out = []
    for sensor in SENSORS:
        r = client.get(f"{BASE}/{MAP_KEY}/{sensor.strip()}/{BBOX}/{DAY_RANGE}")
        r.raise_for_status()
        text = r.text.strip()
        if not text or text.lower().startswith("invalid"):
            raise RuntimeError(f"FIRMS response tidak valid untuk {sensor}: {text[:120]}")
        out += [e for e in (normalize(row, sensor.strip()) for row in csv.DictReader(io.StringIO(text))) if e]
    return out


if __name__ == "__main__":
    run_source("firms", "raw.hotspot", fetch, key=lambda e: e["event_id"], poll_seconds=POLL_SECONDS,
               seed_sql="SELECT DISTINCT event_id FROM hotspots WHERE acq_time >= now() - INTERVAL 3 DAY")
