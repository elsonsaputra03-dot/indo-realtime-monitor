"""
Kualitas udara per ibu kota provinsi (38 provinsi) dari Open-Meteo Air Quality API.
Tanpa API key. Satu request untuk semua koordinat.
"""
import os

import httpx

from producers.base import run_source

URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
POLL_SECONDS = int(os.getenv("AQ_POLL_SECONDS", "900"))
VARS = ["pm2_5", "pm10", "nitrogen_dioxide", "ozone", "carbon_monoxide", "us_aqi"]

# (kota, provinsi, lat, lon)
CITIES = [
    ("Banda Aceh", "Aceh", 5.55, 95.32), ("Medan", "Sumatera Utara", 3.59, 98.67),
    ("Padang", "Sumatera Barat", -0.95, 100.35), ("Pekanbaru", "Riau", 0.51, 101.45),
    ("Tanjung Pinang", "Kepulauan Riau", 0.92, 104.45), ("Jambi", "Jambi", -1.61, 103.61),
    ("Palembang", "Sumatera Selatan", -2.98, 104.76), ("Pangkalpinang", "Kep. Bangka Belitung", -2.13, 106.11),
    ("Bengkulu", "Bengkulu", -3.80, 102.27), ("Bandar Lampung", "Lampung", -5.43, 105.26),
    ("Jakarta", "DKI Jakarta", -6.20, 106.85), ("Serang", "Banten", -6.12, 106.15),
    ("Bandung", "Jawa Barat", -6.92, 107.61), ("Semarang", "Jawa Tengah", -6.97, 110.42),
    ("Yogyakarta", "DI Yogyakarta", -7.80, 110.37), ("Surabaya", "Jawa Timur", -7.25, 112.75),
    ("Denpasar", "Bali", -8.65, 115.22), ("Mataram", "Nusa Tenggara Barat", -8.58, 116.12),
    ("Kupang", "Nusa Tenggara Timur", -10.17, 123.61), ("Pontianak", "Kalimantan Barat", -0.03, 109.33),
    ("Palangka Raya", "Kalimantan Tengah", -2.21, 113.92), ("Banjarbaru", "Kalimantan Selatan", -3.44, 114.83),
    ("Samarinda", "Kalimantan Timur", -0.50, 117.15), ("Tanjung Selor", "Kalimantan Utara", 2.84, 117.37),
    ("Manado", "Sulawesi Utara", 1.47, 124.84), ("Gorontalo", "Gorontalo", 0.54, 123.06),
    ("Palu", "Sulawesi Tengah", -0.90, 119.87), ("Mamuju", "Sulawesi Barat", -2.68, 118.89),
    ("Makassar", "Sulawesi Selatan", -5.15, 119.43), ("Kendari", "Sulawesi Tenggara", -3.97, 122.51),
    ("Ambon", "Maluku", -3.70, 128.18), ("Sofifi", "Maluku Utara", 0.74, 127.56),
    ("Jayapura", "Papua", -2.53, 140.72), ("Manokwari", "Papua Barat", -0.86, 134.08),
    ("Sorong", "Papua Barat Daya", -0.88, 131.26), ("Nabire", "Papua Tengah", -3.37, 135.50),
    ("Wamena", "Papua Pegunungan", -4.10, 138.94), ("Merauke", "Papua Selatan", -8.49, 140.40),
]


def normalize(city: tuple, payload: dict) -> dict | None:
    cur = payload.get("current") or {}
    if not cur.get("time"):
        return None
    name, prov, lat, lon = city

    def v(k):
        x = cur.get(k)
        return float(x) if x is not None else -1.0   # -1 = tidak tersedia (dicek DQ)

    return {
        "city": name, "province": prov, "lat": lat, "lon": lon,
        "obs_time": cur["time"] + ":00Z" if len(cur["time"]) == 16 else cur["time"],
        "pm2_5": v("pm2_5"), "pm10": v("pm10"), "no2": v("nitrogen_dioxide"),
        "o3": v("ozone"), "co": v("carbon_monoxide"), "us_aqi": v("us_aqi"),
    }


def fetch(client: httpx.Client) -> list[dict]:
    r = client.get(URL, params={
        "latitude": ",".join(str(c[2]) for c in CITIES),
        "longitude": ",".join(str(c[3]) for c in CITIES),
        "current": ",".join(VARS),
        "timezone": "UTC",
    })
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict):     # satu lokasi -> dict, banyak lokasi -> list
        data = [data]
    return [e for e in (normalize(c, p) for c, p in zip(CITIES, data)) if e]


if __name__ == "__main__":
    run_source("openmeteo_aq", "raw.air_quality", fetch,
               key=lambda e: f"{e['city']}|{e['obs_time']}", poll_seconds=POLL_SECONDS,
               seed_sql="SELECT DISTINCT concat(toString(city), '|', formatDateTime(obs_time, '%Y-%m-%dT%H:%i:%SZ')) "
                        "FROM air_quality WHERE obs_time >= now() - INTERVAL 1 DAY")
