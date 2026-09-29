"""
Snapshot statis untuk GitHub Pages (biaya Rp0): dijalankan GitHub Actions tiap jam.

Mengambil data publik, memakai ulang normalizer dari producer/DAG project ini, lalu menulis
JSON ke site/data/. Tidak butuh Kafka/ClickHouse/Airflow. Setiap sumber berdiri sendiri:
satu sumber gagal tidak menggagalkan yang lain, dan statusnya dicatat di meta.json (DQ-lite).

Jalankan lokal:  PYTHONPATH=app:airflow/dags python scripts/snapshot.py --out site/data
"""
import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

import httpx

sys.path[:0] = ["app", "airflow/dags", "scripts"]
os.environ.setdefault("GAZETTEER_CSV", "reference/wilayah_indonesia.csv")

UA = "indo-realtime-monitor-snapshot/1.0 (+https://github.com/elsonsaputra03-dot/indo-realtime-monitor)"
WIB = timezone(timedelta(hours=7))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def redact(text: str) -> str:
    """Pesan status tampil di situs publik: jangan pernah bocorkan secret / URL ber-key."""
    import re
    for var in ("FIRMS_MAP_KEY",):
        val = os.getenv(var, "").strip()
        if val:
            text = text.replace(val, "***")
    text = re.sub(r"/api/area/csv/[^/\s']+", "/api/area/csv/***", text)
    return re.sub(r"https?://\S+", "[url]", text)


def write(out: str, name: str, obj) -> int:
    path = os.path.join(out, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    return os.path.getsize(path)


def client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": UA}, follow_redirects=True,
                        timeout=httpx.Timeout(20, read=120), transport=httpx.HTTPTransport(retries=2))


# ---------------------------------------------------------------- sumber
def src_earthquakes(c: httpx.Client) -> dict:
    from producers.earthquake import fetch_bmkg, fetch_usgs
    events, errors = [], []
    for name, fn in (("bmkg", fetch_bmkg), ("usgs", fetch_usgs)):
        try:
            events += fn(c)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {type(exc).__name__}")
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    uniq = {e["event_id"]: e for e in events}
    feats = []
    for e in uniq.values():
        t = datetime.fromisoformat(e["event_time"].replace("Z", "+00:00"))
        if t >= cutoff:
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [e["lon"], e["lat"]]},
                          "properties": {"id": e["event_id"], "source": e["source"], "time": t.isoformat(),
                                         "magnitude": round(e["magnitude"], 1), "depth_km": round(e["depth_km"], 1),
                                         "region": e["region"], "felt": e["felt"]}})
    feats.sort(key=lambda f: f["properties"]["time"], reverse=True)
    if errors and not feats:
        raise RuntimeError("; ".join(errors))
    return {"file": ("earthquakes.json", {"type": "FeatureCollection", "features": feats}),
            "count": len(feats), "note": "; ".join(errors)}


def src_hotspots(c: httpx.Client) -> dict:
    import producers.hotspot as hs
    if not hs.MAP_KEY:
        raise RuntimeError("FIRMS_MAP_KEY belum di-set (GitHub secret)")
    rows = hs.fetch(c)
    rows = [r for r in rows if r["confidence"] in ("n", "h")]
    uniq = {r["event_id"]: r for r in rows}
    # format ringkas: [lat, lon, frp, confidence, acq_time] -> file kecil untuk ribuan titik
    pts = [[round(r["lat"], 4), round(r["lon"], 4), round(r["frp"], 1), r["confidence"], r["acq_time"][:16]]
           for r in uniq.values()]
    return {"file": ("hotspots.json", {"fields": ["lat", "lon", "frp", "confidence", "acq_time_utc"], "points": pts}),
            "count": len(pts)}


def src_air_quality(c: httpx.Client) -> dict:
    import producers.air_quality as aq
    rows = aq.fetch(c)
    return {"file": ("air_quality.json", rows), "count": len(rows)}


def src_news(_c: httpx.Client) -> dict:
    from news_lib import FEEDS, fetch_feed
    items, failed = {}, []
    for feed in FEEDS:
        res = fetch_feed(feed)
        if res["status"] != "ok":
            failed.append(f"{feed['name']}({res['status']})")
        for it in res["items"]:
            items[it["news_id"]] = it
    cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    news = sorted((i for i in items.values() if i["published_at"] >= cutoff),
                  key=lambda i: i["published_at"], reverse=True)[:150]
    if failed and len(failed) == len(FEEDS):
        raise RuntimeError("semua feed gagal")
    return {"file": ("news.json", news), "count": len(news), "note": ", ".join(failed)}


def src_food_prices(_c: httpx.Client, out: str) -> dict:
    """PIHPS harian: cukup diambil ulang bila cache > 12 jam (hemat request ke server BI)."""
    from pihps_lib import COMMODITIES, fetch_commodity
    path = os.path.join(out, "food_prices.json")
    if os.path.exists(path):
        cached = json.load(open(path, encoding="utf-8"))
        age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(cached["generated_at"])).total_seconds() / 3600
        if age_h < 12 and cached.get("items"):
            return {"file": None, "count": len(cached["items"]), "note": f"cache {age_h:.0f} jam"}
    today = datetime.now(WIB).date()
    items, failed = [], []
    for cid in COMMODITIES:
        res = fetch_commodity(cid, [today, today - timedelta(days=1)])
        if res["status"] != "ok":
            failed.append(str(cid))
        latest = max((i["price_date"] for i in res["items"]), default=None)
        items += [i for i in res["items"] if i["price_date"] == latest]
    if not items:
        raise RuntimeError("PIHPS tidak mengembalikan data" + (f" (gagal: {', '.join(failed)})" if failed else ""))
    return {"file": ("food_prices.json", {"generated_at": now_iso(), "items": items}), "count": len(items),
            "note": f"komoditas gagal: {', '.join(failed)}" if failed else ""}


# ---------------------------------------------------------------- alert email
SITE_URL = "https://elsonsaputra03-dot.github.io/indo-realtime-monitor/demo.html"
INDONESIA_BBOX = (94.0, -12.0, 142.0, 7.0)     # lon_min, lat_min, lon_max, lat_max


def run_alerts(out: str, meta: dict) -> None:
    """Sumber gagal >=3 run berturut-turut, gempa M>=6 (sekali per event), AQI >=300 (pulih bila <200)."""
    import alerting
    st = alerting.AlertState(os.getenv("ALERT_STATE", ".alert-state/state.json"))
    now = datetime.now(timezone.utc)
    for key, s in meta["sources"].items():
        st.update(f"source:{key}", s["status"] != "ok", f"Sumber data gagal: {s['label']}",
                  s.get("note", ""), open_after=3, now=now)

    def load(name, default):
        p = os.path.join(out, name)
        return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default

    lo0, la0, lo1, la1 = INDONESIA_BBOX
    for f in load("earthquakes.json", {"features": []})["features"]:
        p, (lon, lat) = f["properties"], f["geometry"]["coordinates"]
        age_h = (now - datetime.fromisoformat(p["time"])).total_seconds() / 3600
        if p["magnitude"] >= 6.0 and age_h <= 24 and lo0 <= lon <= lo1 and la0 <= lat <= la1:
            wib = datetime.fromisoformat(p["time"]).astimezone(WIB)
            st.once(f"quake:{p['id']}", f"Gempa M{p['magnitude']} · {p['region']}",
                    f"{wib:%d %b %Y %H:%M} WIB, kedalaman {p['depth_km']:g} km, sumber {p['source'].upper()}", now=now)
    for r in load("air_quality.json", []):
        aqi, key = r.get("us_aqi", -1), f"aqi:{r['city']}"
        failing = aqi >= 300 or (st.is_active(key) and aqi >= 200)      # histeresis: tutup saat < 200
        st.update(key, failing, f"Kualitas udara berbahaya: {r['city']} ({r['province']})",
                  f"US AQI {round(aqi)}, PM2.5 {r.get('pm2_5', 0):.0f} µg/m³", now=now)
    st.prune(now=now)
    n_open = sum(1 for e in st.events if e["type"] != "resolve")
    n_res = len(st.events) - n_open
    sent = st.flush("snapshot", footer=f"Peta: {SITE_URL}")
    st.save()
    print(f"{'alert':15} {'sent' if sent else 'skip':6} baru={n_open} pulih={n_res} "
          f"email={'on' if alerting.email_configured() else 'off'}")


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site/data")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    meta = {"generated_at": now_iso(), "sources": {}}
    jobs = [("gempa", "BMKG & USGS", src_earthquakes), ("titik_panas", "NASA FIRMS", src_hotspots),
            ("kualitas_udara", "Open-Meteo", src_air_quality), ("berita", "8 portal nasional (RSS)", src_news),
            ("harga_pangan", "PIHPS Bank Indonesia", lambda c: src_food_prices(c, a.out))]
    with client() as c:
        for key, label, fn in jobs:
            t0 = time.monotonic()
            info = {"label": label, "status": "ok", "count": 0, "note": "", "ms": 0}
            try:
                res = fn(c)
                if res.get("file"):
                    name, obj = res["file"]
                    info["bytes"] = write(a.out, name, obj)
                info["count"], info["note"] = res["count"], res.get("note", "")
            except Exception as exc:  # noqa: BLE001 - satu sumber gagal tidak menghentikan yang lain
                info.update(status="error", note=redact(f"{type(exc).__name__}: {exc}")[:200])
            info["ms"] = int((time.monotonic() - t0) * 1000)
            meta["sources"][key] = info
            print(f"{key:15} {info['status']:6} n={info['count']:<6} {info['ms']:>6}ms {info['note']}")
    # ---- Fase 5: indeks risiko per kab/kota dari data yang baru ditulis
    t0 = time.monotonic()
    info = {"label": "Indeks risiko kab/kota", "status": "ok", "count": 0, "note": "", "ms": 0}
    try:
        import risk
        res = risk.build_from_dir(a.out, "reference/batas_kabkota.geojson", os.environ["GAZETTEER_CSV"])
        info["bytes"] = write(a.out, "risk.json", res)
        info["count"] = len(res["items"])
        top = res["items"][0]
        info["note"] = f"tertinggi: {top['nama']} ({top['skor']})"
    except Exception as exc:  # noqa: BLE001
        info.update(status="error", note=redact(f"{type(exc).__name__}: {exc}")[:200])
    info["ms"] = int((time.monotonic() - t0) * 1000)
    meta["sources"]["risiko"] = info
    print(f"{'risiko':15} {info['status']:6} n={info['count']:<6} {info['ms']:>6}ms {info['note']}")

    write(a.out, "meta.json", meta)
    run_alerts(a.out, meta)
    ok = sum(s["status"] == "ok" for s in meta["sources"].values())
    print(f"selesai: {ok}/{len(meta['sources'])} langkah ok")
    return 0 if ok else 1          # gagal total -> job merah (dapat email dari GitHub)


if __name__ == "__main__":
    sys.exit(main())
