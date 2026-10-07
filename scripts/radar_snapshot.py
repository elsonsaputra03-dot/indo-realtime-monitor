"""Snapshot data publik Cloudflare Radar untuk tampilan "Internet publik" di Network KPI Monitor.

Isi: gangguan internet (outage) dan anomali trafik Indonesia, tren trafik per operator (ASN), kualitas (speed test)
per operator, statistik routing BGP, dan kejadian BGP hijack/leak yang melibatkan Indonesia.

Lisensi data API Cloudflare Radar: CC BY-NC 4.0 (atribusi, non-komersial). Atribusi ditulis ke JSON dan ditampilkan.
Token: env CF_RADAR_TOKEN (Account > Radar > Read). Tanpa token, file lama dibiarkan (tidak ditimpa).

Pemakaian:  CF_RADAR_TOKEN=... python scripts/radar_snapshot.py --out site/data [--max-age-hours 3]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.cloudflare.com/client/v4/radar"
# ASN operator Indonesia; nama resmi diambil dari Radar (entities/asns), label pendek hanya kalau namanya cocok
ASNS = [23693, 4761, 24203, 45727, 7713]
LABEL_RULES = [("TELKOMSEL", "Telkomsel"), ("INDOSAT", "Indosat"), ("HUTCHISON", "Tri (IOH)"), ("THREE", "Tri (IOH)"),
               ("XL", "XL Axiata"), ("SMART", "Smartfren"), ("TELKOM", "Telkom Indonesia")]
ATTRIBUTION = {"source": "Cloudflare Radar", "url": "https://radar.cloudflare.com/id",
               "license": "CC BY-NC 4.0", "license_url": "https://creativecommons.org/licenses/by-nc/4.0/"}
FILE = "radar_id.json"
SCHEMA = 3                      # naikkan saat isi snapshot berubah: snapshot lama langsung diambil ulang


class Radar:
    def __init__(self, token: str):
        self.token, self.errors, self.calls = token, [], 0

    def get(self, path: str, **params):
        params = {k: v for k, v in params.items() if v is not None}
        params.setdefault("format", "json")
        url = f"{API}/{path}?{urllib.parse.urlencode(params, doseq=True)}"
        for attempt in range(3):
            self.calls += 1
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.token}", "User-Agent": "indo-realtime-monitor"})
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    body = json.load(r)
                if not body.get("success", True):
                    raise RuntimeError(str(body.get("errors"))[:200])
                return body.get("result") or {}
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503) and attempt < 2:
                    time.sleep(float(e.headers.get("Retry-After") or 5 * (attempt + 1)))
                    continue
                self.errors.append(f"{path}: HTTP {e.code}")
                return None
            except Exception as e:  # noqa: BLE001 - satu endpoint gagal tidak boleh menggagalkan snapshot
                self.errors.append(f"{path}: {str(e)[:160]}")
                return None
        return None


def label_for(name: str, asn: int) -> str:
    up = (name or "").upper()
    for key, lab in LABEL_RULES:
        if key in up:
            return lab
    return name or f"AS{asn}"


def series(res) -> dict | None:
    """Ambil seri pertama dari respons timeseries Radar (serie_0 atau nama seri lain)."""
    if not res:
        return None
    s = res.get("serie_0") or next((v for k, v in res.items() if k != "meta" and isinstance(v, dict) and "timestamps" in v), None)
    if not s or not s.get("timestamps"):
        return None
    vals = [None if v is None else round(float(v), 4) for v in s.get("values", [])]
    return {"t": s["timestamps"], "v": vals}


def pick(d: dict, *keys):
    return {k: d.get(k) for k in keys if k in d}


def collect(radar: Radar) -> dict:
    out = {"schema": SCHEMA, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "attribution": ATTRIBUTION,
           "asns": {}, "outages": [], "anomalies": [], "traffic": {}, "speed": [], "speed_ops": [], "adm1": {}, "geo": None, "probe": {}, "bgp": {}, "hijacks": [], "leaks": []}

    for asn in ASNS:
        r = radar.get(f"entities/asns/{asn}")
        a = (r or {}).get("asn") or {}
        name = a.get("name") or a.get("aka") or a.get("orgName") or ""
        out["asns"][str(asn)] = {"asn": asn, "name": name, "org": a.get("orgName"), "country": a.get("country"), "label": label_for(name, asn)}

    r = radar.get("annotations/outages", location="ID", dateRange="52w", limit=200)
    for x in (r or {}).get("annotations", []):
        o = x.get("outage") or {}
        out["outages"].append({**pick(x, "id", "startDate", "endDate", "scope", "description", "linkedUrl", "eventType", "dataSource"),
            "cause": o.get("outageCause"), "type": o.get("outageType"), "asns": x.get("asns") or [],
            "asn_names": [d.get("name") for d in x.get("asnsDetails") or []],
            "locations": [d.get("name") or d.get("code") for d in x.get("locationsDetails") or []] or x.get("locations") or []})

    seen = set()
    for params in [{"location": "ID"}] + [{"asn": a} for a in ASNS]:
        r = radar.get("traffic_anomalies", dateRange="52w", limit=100, **params)
        for x in (r or {}).get("trafficAnomalies", []):
            key = x.get("uuid") or (x.get("startDate"), str(x.get("asnDetails")), str(x.get("locationDetails")))
            if key in seen:
                continue
            seen.add(key)
            ad, ld = x.get("asnDetails") or {}, x.get("locationDetails") or {}
            out["anomalies"].append({**pick(x, "uuid", "type", "status", "startDate", "endDate", "visibleInDataSources"),
                "asn": ad.get("asn"), "asn_name": ad.get("name"), "location": ld.get("name") or ld.get("code")})

    for key, params in [("ID", {"location": "ID"})] + [(str(a), {"asn": a}) for a in ASNS]:
        http = series(radar.get("http/timeseries", dateRange="28d", aggInterval="1h", normalization="MIN0_MAX", **params))
        flows = series(radar.get("netflows/timeseries", dateRange="28d", aggInterval="1h", normalization="MIN0_MAX", **params))
        out["traffic"][key] = {"http": http, "netflows": flows}

    r = radar.get("quality/speed/top/ases", location="ID", orderBy="BANDWIDTH_DOWNLOAD", limit=25)
    for x in (r or {}).get("top_0", []):
        out["speed"].append(pick(x, "clientASN", "clientASName", "bandwidthDownload", "bandwidthUpload", "latencyIdle",
                                 "latencyLoaded", "jitterIdle", "jitterLoaded", "numTests", "rankPower"))

    # kecepatan per operator (median speed test pengguna 90 hari) dan Indonesia secara keseluruhan
    for key, params in [("ID", {"location": "ID"})] + [(str(a), {"asn": a}) for a in ASNS]:
        r = radar.get("quality/speed/summary", dateRange="90d", **params)
        sm = (r or {}).get("summary_0")
        if sm:
            out["speed_ops"].append({"key": key, **{k: sm.get(k) for k in ("bandwidthDownload", "bandwidthUpload", "latencyIdle",
                                                                          "latencyLoaded", "jitterIdle", "jitterLoaded", "packetLoss")}})

    # level provinsi (ADM1, tersedia di Radar sejak Sep 2025): porsi trafik per provinsi, untuk Indonesia dan tiap operator
    for key, params in [("ID", {})] + [(str(a), {"asn": a}) for a in ASNS]:
        r = radar.get("netflows/summary/ADM1", location="ID", dateRange="7d", limitPerGroup=60, **params)
        if r:
            out["adm1"][key] = {k: v for k, v in r.items() if k != "meta"}
    out["geo"] = radar.get("geolocations", location="ID", limit=100)
    for name, path, params in [("http_tsg_adm1", "http/timeseries_groups/ADM1", {"location": "ID", "dateRange": "28d", "aggInterval": "1d", "limitPerGroup": 40}),
                               ("netflows_tsg_adm1", "netflows/timeseries_groups/ADM1", {"location": "ID", "dateRange": "28d", "aggInterval": "1d", "limitPerGroup": 40})]:
        r = radar.get(path, **params)   # percobaan: struktur dicatat di status untuk dipakai tampilan berikutnya
        if r:
            out["probe"][name] = r

    for asn in ASNS:
        r = radar.get("bgp/routes/stats", asn=asn)
        if r and r.get("stats"):
            out["bgp"][str(asn)] = {**r["stats"], "updated": (r.get("meta") or {}).get("data_time")}

    for kind, path in [("hijacks", "bgp/hijacks/events"), ("leaks", "bgp/leaks/events")]:
        r = radar.get(path, involvedCountry="ID", dateRange="52w", per_page=100, sortBy="TIME", sortOrder="DESC")
        for x in (r or {}).get("events", []):
            out[kind].append({k: v for k, v in x.items() if not isinstance(v, (list, dict)) or k in ("victim_asns", "prefixes", "tags")})

    out["errors"], out["api_calls"] = radar.errors, radar.calls
    return out


def write_status(path: Path) -> None:
    """Ringkasan kecil di samping snapshot (jumlah per bagian + error), untuk pemantauan tanpa membuka file besar."""
    try:
        snap = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    st = {"generated_at": snap.get("generated_at"), "api_calls": snap.get("api_calls"), "errors": snap.get("errors", []),
          "counts": {k: len(snap.get(k) or []) for k in ("outages", "anomalies", "speed", "speed_ops", "bgp", "hijacks", "leaks")},
          "traffic": {k: {"http": len((v.get("http") or {}).get("t", [])), "netflows": len((v.get("netflows") or {}).get("t", []))}
                      for k, v in (snap.get("traffic") or {}).items()},
          "asns": {k: v.get("label") for k, v in (snap.get("asns") or {}).items()},
          "adm1_sample": {k: (json.dumps(v)[:1500]) for k, v in list((snap.get("adm1") or {}).items())[:2]},
          "geo_sample": json.dumps(snap.get("geo"))[:1500],
          "probe_sample": {k: json.dumps(v)[:1500] for k, v in (snap.get("probe") or {}).items()},
          "samples": {k: (snap.get(k) or [None])[0] for k in ("outages", "anomalies", "speed_ops", "hijacks", "leaks")}
                     | {"bgp": next(iter((snap.get("bgp") or {}).values()), None)}}
    path.with_name("radar_status.json").write_text(json.dumps(st, indent=1), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site/data")
    ap.add_argument("--max-age-hours", type=float, default=3.0, help="lewati jika snapshot lebih baru dari ini")
    a = ap.parse_args()
    path = Path(a.out) / FILE
    token = os.environ.get("CF_RADAR_TOKEN", "").strip()
    if path.exists():
        try:
            old = json.loads(path.read_text())
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(old["generated_at"])).total_seconds() / 3600
            if age < a.max_age_hours and old.get("schema") == SCHEMA:
                print(f"radar: snapshot {age:.1f} jam, dilewati"); write_status(path); return 0
        except Exception:  # noqa: BLE001
            pass
    if not token:
        print("radar: CF_RADAR_TOKEN kosong, snapshot lama dipertahankan", file=sys.stderr); return 0
    snap = collect(Radar(token))
    filled = sum(bool(snap[k]) for k in ("outages", "anomalies", "speed", "bgp")) + sum(bool(v["http"] or v["netflows"]) for v in snap["traffic"].values())
    if not filled:
        print(f"radar: semua endpoint gagal, snapshot lama dipertahankan: {snap['errors'][:5]}", file=sys.stderr); return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap, separators=(",", ":")), encoding="utf-8")
    print(f"radar: {len(snap['outages'])} outage, {len(snap['anomalies'])} anomali, {len(snap['speed'])} ASN speed, "
          f"{len(snap['bgp'])} BGP, {len(snap['hijacks'])} hijack, {len(snap['leaks'])} leak, {snap['api_calls']} call, {len(snap['errors'])} error")
    for e in snap["errors"]:
        print("  error:", e, file=sys.stderr)
    write_status(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
