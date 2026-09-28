"""
Indeks risiko komposit per kabupaten/kota (eksperimental, untuk portofolio, BUKAN penilaian resmi).

Skor 0-100 = 100 x rata-rata tertimbang komponen yang TERSEDIA (bobot dinormalisasi ulang
bila komponen tidak punya data, mis. PIHPS belum mencakup provinsi hasil pemekaran Papua).
Setiap komponen dinormalisasi 0-1 dengan rumus sederhana & terdokumentasi di bawah.

Komponen (bobot):
  gempa        0.25  max over gempa 7 hari: mag_norm x peluruhan jarak x peluruhan waktu
  titik_panas  0.30  kepadatan titik panas (confidence n/h) per 1.000 km2, skala log
  udara        0.20  US AQI kota pemantau di provinsi yang sama (proksi tingkat provinsi)
  pangan       0.10  rata-rata selisih harga di atas nasional, 10 komoditas (tingkat provinsi)
  berita       0.15  jumlah berita bencana yang menyebut wilayah (geotag rule-based)
"""
import csv
import json
import math
import os
from functools import lru_cache
from datetime import datetime, timezone

import llm_lib

WEIGHTS = {"gempa": 0.25, "titik_panas": 0.30, "udara": 0.20, "pangan": 0.10, "berita": 0.15}
DISASTER_TOPICS = {"gempa", "banjir_longsor", "kebakaran", "gunung_api", "cuaca", "kualitas_udara"}
KM_PER_DEG = 111.0


def clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def validate_geom(geom, luas_km2: float | None, lat: float | None, lng: float | None):
    """DQ poligon sumber: 20 dari 514 batas kab/kota luasnya menyimpang >3x dari luas resmi
    (tertukar dengan wilayah tetangga atau degenerate). Ganti dengan lingkaran seluas luas resmi
    di koordinat ibu kota. Return (geom, valid)."""
    from shapely.geometry import Point
    area = geom.area * KM_PER_DEG ** 2
    if not luas_km2 or lat is None:
        return geom, True
    ratio = area / luas_km2 if luas_km2 else 1
    if 1 / 3 <= ratio <= 3 and not geom.is_empty:
        return geom, True
    radius_deg = math.sqrt(luas_km2 / math.pi) / KM_PER_DEG
    return Point(lng, lat).buffer(radius_deg, 24), False


def load_regions(boundary_path: str, gazetteer_path: str) -> list[dict]:
    from shapely.geometry import shape
    gaz = {r["kode"]: r for r in csv.DictReader(open(gazetteer_path, encoding="utf-8"))}
    provs = {k: v for k, v in gaz.items() if v["level"] == "1"}
    out = []
    for f in json.load(open(boundary_path, encoding="utf-8"))["features"]:
        kode = f["properties"].get("kode") or f["properties"].get("k")
        g = gaz.get(kode, {})
        luas_resmi = float(g["luas_km2"]) if g.get("luas_km2") else None
        geom, valid = validate_geom(shape(f["geometry"]), luas_resmi,
                                    float(g["lat"]) if g.get("lat") else None, float(g["lng"]) if g.get("lng") else None)
        luas = luas_resmi or geom.area * KM_PER_DEG ** 2
        out.append({"kode": kode, "nama": g.get("nama", kode), "prov_kode": kode.split(".")[0],
                    "prov_nama": provs.get(kode.split(".")[0], {}).get("nama", ""), "luas_km2": max(luas, 1.0),
                    "geom": geom, "batas_valid": valid})
    return out


@lru_cache(maxsize=512)
def prov_code(name: str) -> str | None:
    hit = llm_lib.resolve([name], name)
    return hit["prov_kode"] if hit else None


# ---------------------------------------------------------------- komponen
def comp_gempa(regions, quakes, now) -> dict:
    """mag_norm = (M-3)/4 (M3 -> 0, M7 -> 1); jarak: exp(-d/100 km); waktu: exp(-umur_hari/3)."""
    out = {}
    if not quakes:
        return out
    from shapely.geometry import Point
    pts = []
    for q in quakes:
        p = q["properties"]
        age_d = (now - datetime.fromisoformat(p["time"].replace("Z", "+00:00"))).total_seconds() / 86400
        pts.append((Point(q["geometry"]["coordinates"]), clip01((p["magnitude"] - 3) / 4), math.exp(-max(age_d, 0) / 3), p))
    for r in regions:
        best, src = 0.0, None
        for pt, mag_n, age_f, p in pts:
            if mag_n <= 0:
                continue
            d_km = r["geom"].distance(pt) * KM_PER_DEG
            v = mag_n * math.exp(-d_km / 100) * age_f
            if v > best:
                best, src = v, p
        if src and best >= 0.01:
            out[r["kode"]] = (best, f"M{src['magnitude']} {src['region'][:60]}")
        else:
            out[r["kode"]] = (0.0, "tidak ada gempa ≥M3 berdekatan")
    return out


def comp_titik_panas(regions, points) -> dict:
    """kepadatan = titik per 1.000 km2 (luas minimum 1.000 km2 supaya 1 titik di kota kecil tidak
    langsung bernilai maksimum); norm = log1p(k)/log1p(100) (100 titik/1.000 km2 -> 1)."""
    import shapely
    from shapely import STRtree
    counts = {r["kode"]: 0 for r in regions}
    if points:
        tree = STRtree([r["geom"] for r in regions])
        pi, gi = tree.query(shapely.points([(p[1], p[0]) for p in points]), predicate="intersects")
        seen = set()
        for a, b in zip(pi, gi):
            if a not in seen:
                seen.add(a)
                counts[regions[b]["kode"]] += 1
    out = {}
    for r in regions:
        n = counts[r["kode"]]
        dens = n / max(r["luas_km2"], 1000.0) * 1000
        out[r["kode"]] = (clip01(math.log1p(dens) / math.log1p(100)), f"{n} titik ({dens:.1f}/1.000 km²)")
    return out


def comp_udara(regions, aq_rows) -> dict:
    """norm = (AQI-50)/450 (AQI 50 -> 0, 500 -> 1). Proksi provinsi: kota pemantau di provinsi yang sama."""
    by_prov = {}
    for a in aq_rows:
        pk = prov_code(a["province"])
        if pk and a.get("us_aqi", -1) >= 0:
            by_prov[pk] = a
    out = {}
    for r in regions:
        a = by_prov.get(r["prov_kode"])
        if a:
            out[r["kode"]] = (clip01((a["us_aqi"] - 50) / 450), f"AQI {round(a['us_aqi'])} di {a['city']}")
    return out


def comp_pangan(regions, food_items) -> dict:
    """rata-rata max(0, (harga-nasional)/nasional) atas komoditas; norm = x/0.5 (50% di atas nasional -> 1)."""
    agg: dict[str, list[float]] = {}
    for it in food_items:
        if it.get("national_avg"):
            pk = prov_code(it["province"])
            if pk:
                agg.setdefault(pk, []).append(max(0.0, (it["price"] - it["national_avg"]) / it["national_avg"]))
    out = {}
    for r in regions:
        xs = agg.get(r["prov_kode"])
        if xs:
            m = sum(xs) / len(xs)
            out[r["kode"]] = (clip01(m / 0.5), f"rata-rata {m * 100:.0f}% di atas nasional ({len(xs)} komoditas)")
    return out


def comp_berita(regions, news) -> dict:
    """berita bencana ter-geotag: kab/kota = 1 poin, provinsi = 0,5 poin ke semua kab/kota; norm = poin/3."""
    pts: dict[str, float] = {}
    prov_pts: dict[str, float] = {}
    for n in news:
        if not DISASTER_TOPICS & set(n.get("topics", [])):
            continue
        text = f"{n['title']}. {n.get('summary', '')}"
        hit = llm_lib.resolve(llm_lib.rule_scan(text), text)
        if not hit:
            continue
        if hit["level"] == 2:
            pts[hit["kode"]] = pts.get(hit["kode"], 0) + 1
        else:
            prov_pts[hit["prov_kode"]] = prov_pts.get(hit["prov_kode"], 0) + 0.5
    out = {}
    for r in regions:
        p = pts.get(r["kode"], 0) + prov_pts.get(r["prov_kode"], 0)
        out[r["kode"]] = (clip01(p / 3), f"{p:g} poin berita bencana")
    return out


# ---------------------------------------------------------------- skor
def compute(regions, quakes, hotspots, aq_rows, food_items, news, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    comps = {"gempa": comp_gempa(regions, quakes, now), "titik_panas": comp_titik_panas(regions, hotspots),
             "udara": comp_udara(regions, aq_rows), "pangan": comp_pangan(regions, food_items),
             "berita": comp_berita(regions, news)}
    items = []
    for r in regions:
        parts, wsum, acc = {}, 0.0, 0.0
        for name, w in WEIGHTS.items():
            v = comps[name].get(r["kode"])
            if v is None:
                parts[name] = None
                continue
            val, why = v
            parts[name] = {"nilai": round(val, 3), "bobot": w, "kontribusi": 0.0, "ket": why}
            wsum += w
            acc += w * val
        score = round(100 * acc / wsum, 1) if wsum else 0.0
        for name, p in parts.items():
            if p:
                p["kontribusi"] = round(100 * p["bobot"] * p["nilai"] / wsum, 1) if wsum else 0.0
        items.append({"kode": r["kode"], "nama": r["nama"], "prov": r["prov_nama"], "skor": score,
                      "cakupan": round(wsum, 2), "batas_valid": r["batas_valid"], "komponen": parts})
    items.sort(key=lambda x: -x["skor"])
    return {"generated_at": now.isoformat(timespec="seconds"), "bobot": WEIGHTS,
            "catatan": "Indeks komposit eksperimental untuk demonstrasi, bukan penilaian risiko resmi (rujukan resmi: BNPB InaRISK).",
            "batas_diperkirakan": sum(1 for r in regions if not r["batas_valid"]),
            "items": items}


def build_from_dir(data_dir: str, boundary_path: str, gazetteer_path: str) -> dict:
    def load(name, default):
        p = os.path.join(data_dir, name)
        return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default
    regions = load_regions(boundary_path, gazetteer_path)
    return compute(regions,
                   load("earthquakes.json", {"features": []})["features"],
                   load("hotspots.json", {"points": []})["points"],
                   load("air_quality.json", []),
                   load("food_prices.json", {"items": []})["items"],
                   load("news.json", []))
