"""
Data quality checks per source, hasil ditulis ke irm.dq_results.

Check per source:
- freshness_min          : menit sejak run sukses terakhir (ingest_runs)
- run_error_rate_pct     : % run error dalam 1 jam terakhir (+ pesan error terakhir)
- volume_24h             : jumlah baris baru 24 jam (0 = warn, bisa normal)
- validity_invalid_pct   : % baris yang melanggar aturan validitas source
- duplicate_ratio_pct    : % duplikat key sebelum merge ReplacingMergeTree
- event_lag_median_min   : median menit event_time -> ingested_at, HANYA untuk event
                           di dalam lag window (backfill data lama tidak dihitung)

Tambah source baru = tambah entry di SOURCES.
"""
import logging
import os
import time
from datetime import datetime, timezone

from common import ch_client

log = logging.getLogger("dq")
INTERVAL = int(os.getenv("DQ_INTERVAL_SECONDS", "60"))

INDONESIA = "lat NOT BETWEEN -15 AND 10 OR lon NOT BETWEEN 90 AND 145"
SOURCES = {
    "bmkg": {
        "table": "earthquake_events", "filter": "source = 'bmkg'", "key": "event_id", "time_col": "event_time",
        "validity": f"{INDONESIA} OR magnitude NOT BETWEEN 0 AND 10 OR depth_km < 0",
        "freshness_min": (5, 15), "lag_window_h": 6, "event_lag_min": (30, 120),
    },
    "usgs": {
        "table": "earthquake_events", "filter": "source = 'usgs'", "key": "event_id", "time_col": "event_time",
        "validity": f"{INDONESIA} OR magnitude NOT BETWEEN 0 AND 10 OR depth_km < 0",
        "freshness_min": (5, 15), "lag_window_h": 6, "event_lag_min": (60, 240),
    },
    "firms": {
        "table": "hotspots", "filter": "1", "key": "event_id", "time_col": "acq_time",
        "validity": f"{INDONESIA} OR frp < 0",
        "freshness_min": (30, 60), "lag_window_h": 24, "event_lag_min": (240, 480),
    },
    "news": {
        "table": "news", "filter": "1", "key": "news_id", "time_col": "published_at",
        "validity": "title = '' OR NOT startsWith(link, 'http') OR length(topics) = 0",
        "freshness_min": (30, 60), "lag_window_h": 6, "event_lag_min": (120, 360),
    },
    "openmeteo_aq": {
        "table": "air_quality", "filter": "1", "key": "concat(city, toString(obs_time))", "time_col": "obs_time",
        "validity": "pm2_5 < 0 OR pm10 < 0 OR us_aqi < 0 OR us_aqi > 500",
        "freshness_min": (30, 60), "lag_window_h": 6, "event_lag_min": (90, 180),
    },
}
ERROR_RATE = (10.0, 50.0)
VALIDITY = (1.0, 5.0)
DUP_RATIO = (20.0, 60.0)


def is_num(v) -> bool:
    return v is not None and v == v   # bukan None dan bukan NaN


def grade(value, warn: float, fail: float) -> str:
    if not is_num(value):
        return "fail"
    return "fail" if value >= fail else "warn" if value >= warn else "pass"


def check_source(ch, src: str, c: dict, now: datetime) -> list[list]:
    rows = []

    def add(name, value, warn=0.0, fail=0.0, detail="", status=None):
        rows.append([now, src, name, status or grade(value, warn, fail),
                     float(value) if is_num(value) else -1.0, float(fail), detail])

    p = {"src": src}
    fresh = ch.query(
        "SELECT dateDiff('second', max(run_at), now64(3)) / 60.0 "
        "FROM ingest_runs WHERE source = {src:String} AND status = 'ok'", parameters=p
    ).result_rows[0][0]
    fresh = None if fresh is None or fresh > 60 * 24 * 365 else fresh
    add("freshness_min", fresh, *c["freshness_min"], detail="" if fresh is not None else "belum pernah sukses")

    total, errors, last_err = ch.query(
        "SELECT count(), countIf(status = 'error'), argMaxIf(error, run_at, status = 'error') "
        "FROM ingest_runs WHERE source = {src:String} AND run_at >= now64(3) - INTERVAL 1 HOUR",
        parameters=p,
    ).result_rows[0]
    add("run_error_rate_pct", (errors / total * 100) if total else None, *ERROR_RATE,
        detail=f"{errors}/{total} runs" + (f"; last: {last_err[:150]}" if errors else ""))

    tc = c["time_col"]
    n, invalid, uniq, lag = ch.query(
        f"""
        SELECT count(),
               countIf({c['validity']}),
               uniqExact({c['key']}),
               quantileExactIf(0.5)(dateDiff('second', {tc}, ingested_at) / 60.0,
                                    {tc} >= now() - INTERVAL {int(c['lag_window_h'])} HOUR AND ingested_at >= now64(3) - INTERVAL 3 HOUR)
        FROM {c['table']}
        WHERE {c['filter']} AND ingested_at >= now64(3) - INTERVAL 24 HOUR
        """
    ).result_rows[0]
    add("volume_24h", float(n), status="pass" if n else "warn",
        detail="" if n else "tidak ada record baru 24 jam")
    if n:
        add("validity_invalid_pct", invalid / n * 100, *VALIDITY, detail=f"{invalid}/{n} rows")
        add("duplicate_ratio_pct", (n - uniq) / n * 100, *DUP_RATIO, detail=f"{n - uniq} dup")
        if is_num(lag):
            add("event_lag_median_min", lag, *c["event_lag_min"])
        else:
            add("event_lag_median_min", None, status="pass",
                detail=f"tidak ada event dalam {c['lag_window_h']} jam terakhir")
    return rows


def main() -> None:
    ch = ch_client()
    cols = ["checked_at", "source", "check_name", "status", "value", "threshold", "detail"]
    while True:
        now = datetime.now(timezone.utc)
        rows: list[list] = []
        for src, cfg in SOURCES.items():
            try:
                rows += check_source(ch, src, cfg, now)
                rows.append([now, src, "dq_execution", "pass", 0.0, 0.0, ""])
            except Exception as exc:  # noqa: BLE001 - satu source gagal tidak menghentikan yang lain
                log.warning("dq %s gagal: %s", src, exc)
                rows.append([now, src, "dq_execution", "fail", -1.0, 0.0, str(exc)[:300]])
        try:
            ch.insert("dq_results", rows, column_names=cols)
            summary: dict[str, int] = {}
            for r in rows:
                summary[r[3]] = summary.get(r[3], 0) + 1
            log.info("dq run: %s", summary)
        except Exception:  # noqa: BLE001
            log.exception("insert dq_results gagal")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
