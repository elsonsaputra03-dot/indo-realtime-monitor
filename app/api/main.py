"""Public read-only API + static map page."""
import os
import threading
import time

from fastapi import FastAPI, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from common import ch_client

app = FastAPI(title="Indonesia Realtime Monitor API", version="0.1.0")
app.add_middleware(GZipMiddleware, minimum_size=1000)

_local = threading.local()
_cache: dict[tuple, tuple[float, object]] = {}
CACHE_TTL = int(os.getenv("API_CACHE_SECONDS", "30"))


def ch():
    # clickhouse-connect client tidak thread-safe untuk query paralel -> satu client per thread
    if not hasattr(_local, "client"):
        _local.client = ch_client()
    return _local.client


def cached(key: tuple, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    value = fn()
    _cache[key] = (time.time(), value)
    return value


@app.get("/api/health")
def health():
    ch().query("SELECT 1")
    return {"status": "ok"}


@app.get("/api/earthquakes")
def earthquakes(hours: int = Query(72, ge=1, le=720), min_mag: float = Query(0, ge=0, le=10)):
    def q():
        res = ch().query(
            """
            SELECT event_id, source, toString(event_time) AS t, lat, lon,
                   magnitude, depth_km, region, felt
            FROM earthquake_events FINAL
            WHERE event_time >= now64(3) - toIntervalHour({h:UInt32})
              AND magnitude >= {m:Float32}
            ORDER BY event_time DESC
            LIMIT 2000
            """,
            parameters={"h": hours, "m": min_mag},
        )
        features = [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r[4], r[3]]},
            "properties": {"id": r[0], "source": r[1], "time": r[2] + "Z", "magnitude": round(r[5], 1),
                           "depth_km": round(r[6], 1), "region": r[7], "felt": r[8]},
        } for r in res.result_rows]
        return {"type": "FeatureCollection", "features": features}

    return cached(("eq", hours, min_mag), q)


@app.get("/api/dq/latest")
def dq_latest():
    def q():
        res = ch().query(
            """
            SELECT source, check_name,
                   argMax(status, checked_at), argMax(value, checked_at),
                   argMax(detail, checked_at), toString(max(checked_at))
            FROM dq_results
            WHERE checked_at >= now64(3) - INTERVAL 1 HOUR
            GROUP BY source, check_name
            ORDER BY source, check_name
            """
        )
        keys = ["source", "check", "status", "value", "detail", "checked_at"]
        return [dict(zip(keys, r)) for r in res.result_rows]

    return cached(("dq",), q)


@app.get("/api/ingest/stats")
def ingest_stats():
    def q():
        res = ch().query(
            """
            SELECT source, count() AS runs, countIf(status = 'error') AS errors,
                   sum(new_records) AS new_records, round(avg(latency_ms)) AS avg_latency_ms,
                   toString(max(run_at)) AS last_run
            FROM ingest_runs
            WHERE run_at >= now64(3) - INTERVAL 24 HOUR
            GROUP BY source ORDER BY source
            """
        )
        keys = ["source", "runs", "errors", "new_records", "avg_latency_ms", "last_run"]
        return [dict(zip(keys, r)) for r in res.result_rows]

    return cached(("ingest",), q)


@app.get("/api/hotspots")
def hotspots(hours: int = Query(24, ge=1, le=240), confidence: str = Query("n,h")):
    conf = [c.strip() for c in confidence.split(",") if c.strip()] or ["l", "n", "h"]

    def q():
        res = ch().query(
            """
            SELECT lat, lon, toString(acq_time) AS t, frp, confidence, satellite, daynight
            FROM hotspots FINAL
            WHERE acq_time >= now() - toIntervalHour({h:UInt32})
              AND has({conf:Array(String)}, toString(confidence))
            ORDER BY acq_time DESC
            LIMIT 20000
            """,
            parameters={"h": hours, "conf": conf},
        )
        feats = [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r[1], r[0]]},
            "properties": {"time": r[2] + "Z", "frp": round(r[3], 1), "confidence": r[4],
                           "satellite": r[5], "daynight": r[6]},
        } for r in res.result_rows]
        return {"type": "FeatureCollection", "features": feats}

    return cached(("hs", hours, tuple(conf)), q)


@app.get("/api/air-quality/latest")
def air_quality_latest():
    def q():
        res = ch().query(
            """
            SELECT city, province, any(lat), any(lon),
                   toString(max(obs_time)),
                   argMax(pm2_5, obs_time), argMax(pm10, obs_time), argMax(us_aqi, obs_time)
            FROM air_quality FINAL
            WHERE obs_time >= now() - INTERVAL 1 DAY
            GROUP BY city, province
            ORDER BY argMax(us_aqi, obs_time) DESC
            """
        )
        keys = ["city", "province", "lat", "lon", "obs_time", "pm2_5", "pm10", "us_aqi"]
        return [dict(zip(keys, r)) for r in res.result_rows]

    return cached(("aq",), q)


# Static map page (mount terakhir supaya tidak menutupi /api)
if os.path.isdir("/web"):
    app.mount("/", StaticFiles(directory="/web", html=True), name="web")
