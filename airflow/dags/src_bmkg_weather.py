"""Prakiraan cuaca BMKG per kelurahan/desa (API publik, JSON, per 3 jam untuk 3 hari).

Kebijakan BMKG: maksimal 60 permintaan per menit per IP, data diperbarui 2 kali sehari, dan BMKG WAJIB dicantumkan
sebagai sumber data (lihat https://data.bmkg.go.id/prakiraan-cuaca/).
Kode adm4 mengikuti Kepmendagri No. 100.1.1-6117 Tahun 2022. Daftar di bawah hanya berisi kode yang terverifikasi dari
dokumentasi dan contoh resmi BMKG; tambahkan kode lain di LOCATIONS (respons tanpa 'lokasi' ditandai error).
"""
from __future__ import annotations

from datetime import datetime

from scrape_lib import Polite

URL = "https://api.bmkg.go.id/publik/prakiraan-cuaca"
LOCATIONS = ["31.71.01.1001", "31.71.03.1001", "33.11.04.1012"]
REQUIRED = ["adm4", "forecast_utc", "t", "weather_desc"]


def parse(doc: dict) -> list[dict]:
    rows = []
    for block in doc.get("data", []):
        loc = block.get("lokasi") or doc.get("lokasi") or {}
        for day in block.get("cuaca", []):
            for f in day:
                rows.append({
                    "adm4": loc.get("adm4", ""), "desa": loc.get("desa", ""), "kecamatan": loc.get("kecamatan", ""),
                    "kotkab": loc.get("kotkab", ""), "provinsi": loc.get("provinsi", ""),
                    "lat": loc.get("lat"), "lon": loc.get("lon"),
                    "forecast_utc": (f.get("utc_datetime") or f.get("datetime", "").replace("T", " ").rstrip("Z")),
                    "local_datetime": f.get("local_datetime", ""), "t": f.get("t"), "hu": f.get("hu"), "tcc": f.get("tcc"),
                    "tp": f.get("tp"), "ws": f.get("ws"), "wd": f.get("wd", ""), "weather_code": f.get("weather"),
                    "weather_desc": f.get("weather_desc", ""), "vs": f.get("vs"),
                    "analysis_date": (f.get("analysis_date") or "").replace("T", " "),
                })
    return rows


def fetch(codes: list[str] | None = None, client: Polite | None = None) -> dict:
    c = client or Polite(min_gap=1.1, respect_robots=False)       # API resmi: 60/menit -> jeda > 1 detik
    rows, errors, t0 = [], [], datetime.now()
    for code in codes or LOCATIONS:
        try:
            doc = c.get(URL, params={"adm4": code}).json()
            got = parse(doc)
            if not got:
                errors.append(f"{code}: no forecast in response")
            rows += got
        except Exception as e:  # noqa: BLE001 - satu kode gagal tidak menghentikan yang lain
            errors.append(f"{code}: {e}"[:200])
    return {"rows": rows, "errors": errors, "ms": int((datetime.now() - t0).total_seconds() * 1000), "stats": c.stats}
