"""
"Tanya Data": AI menjawab pertanyaan HANYA dari data platform ini.

Pola tool calling (bukan text-to-SQL bebas):
  1. Router LLM memilih 1-3 alat + parameter (JSON schema, temperature 0).
  2. Backend menjalankan query ter-parameterisasi milik alat tsb (tidak ada SQL dari LLM).
  3. Answer LLM menyusun jawaban hanya dari hasil alat; data kosong -> bilang tidak ada.
Lokasi di-resolve dengan gazetteer yang sama dengan geotagging berita (llm_lib.resolve).
"""
import csv
import json
import math
import os
import re
import time
from functools import lru_cache

import httpx

import llm_lib  # di-mount dari airflow/dags/llm_lib.py (satu sumber kebenaran gazetteer)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:3b")
MAX_DATA_CHARS = 2500

TOOLS = {
    "gempa": "daftar gempa (BMKG & USGS): parameter hari, min_magnitudo, lokasi",
    "titik_panas": "jumlah titik panas/kebakaran (NASA FIRMS) per provinsi: parameter hari, lokasi",
    "kualitas_udara": "kualitas udara terbaru (US AQI, PM2.5) 38 ibu kota provinsi: parameter lokasi",
    "harga_pangan": "harga pangan harian per provinsi (PIHPS BI): parameter komoditas, lokasi",
    "berita": "berita terbaru terkait bencana/cuaca/udara/pangan: parameter topik, lokasi, hari, kata_kunci",
    "kesehatan_pipeline": "status kualitas data & pipeline platform (tanpa parameter)",
    "cuaca": "prakiraan cuaca BMKG (suhu, hujan) untuk lokasi pantau: parameter lokasi",
    "internet_outage": "gangguan/outage internet Indonesia (Cloudflare Radar): parameter hari, lokasi",
    "internet_operator": "kecepatan, penurunan trafik, porsi trafik per provinsi, dan BGP operator seluler (Cloudflare Radar): parameter hari, lokasi",
    "sebaran_sel": "jumlah sel/BTS seluler per kab/kota, provinsi, operator, 2G-5G (OpenCelliD): parameter lokasi",
    "tidak_ada": "pertanyaan di luar cakupan data platform",
}
COMMODITIES = [  # (kata kunci, id, nama) -- urutan penting: yang spesifik dulu
    ("rawit", 8, "Cabai Rawit"), ("cabai merah", 7, "Cabai Merah"), ("cabai", 7, "Cabai Merah"),
    ("bawang putih", 6, "Bawang Putih"), ("bawang merah", 5, "Bawang Merah"), ("bawang", 5, "Bawang Merah"),
    ("daging sapi", 3, "Daging Sapi"), ("sapi", 3, "Daging Sapi"), ("daging ayam", 2, "Daging Ayam"),
    ("ayam", 2, "Daging Ayam"), ("telur", 4, "Telur Ayam"), ("minyak", 9, "Minyak Goreng"),
    ("gula", 10, "Gula Pasir"), ("beras", 1, "Beras"),
]

ROUTER_PROMPT = f"""Kamu memilih alat data untuk menjawab pertanyaan pengguna tentang Indonesia.
Alat yang tersedia:
{chr(10).join(f"- {k}: {v}" for k, v in TOOLS.items())}
Contoh:
- "Berapa titik panas di Kalteng hari ini?" -> alat ["titik_panas"], lokasi "Kalteng", hari 1
- "Gempa terbesar minggu ini?" -> alat ["gempa"], hari 7
- "Harga telur di Sulawesi Utara?" -> alat ["harga_pangan"], komoditas "telur", lokasi "Sulawesi Utara"
- "Provinsi mana yang beras paling murah?" -> alat ["harga_pangan"], komoditas "beras", lokasi ""
- "Kualitas udara Palembang dan berita kabut asapnya" -> alat ["kualitas_udara", "berita"], lokasi "Palembang", topik "kualitas_udara"
- "Besok Jakarta hujan?" -> alat ["cuaca"], lokasi "Jakarta"
- "Ada gangguan internet minggu ini?" -> alat ["internet_outage"], hari 7
- "Kecepatan internet Telkomsel vs XL?" -> alat ["internet_operator"]
- "Berapa BTS di Kalimantan Tengah?" -> alat ["sebaran_sel"], lokasi "Kalimantan Tengah"
Aturan: lokasi HANYA diisi jika nama tempat itu tertulis di pertanyaan; jangan menyalin lokasi dari contoh. Pilih 1-3 alat; "tidak_ada" HANYA jika pertanyaan sama sekali tidak terkait gempa, titik panas/kebakaran,
kualitas udara, harga pangan, cuaca, internet/operator seluler, sel/BTS, berita bencana/cuaca/pangan, atau status data. lokasi/komoditas/topik/kata_kunci = "" jika tidak disebut.
hari: default 3; "hari ini"/"24 jam" = 1; "seminggu" = 7. Balas HANYA JSON sesuai skema."""

ROUTER_SCHEMA = {
    "type": "object",
    "properties": {
        "alat": {"type": "array", "items": {"type": "string", "enum": list(TOOLS)}},
        "lokasi": {"type": "string"}, "hari": {"type": "integer"}, "min_magnitudo": {"type": "number"},
        "komoditas": {"type": "string"}, "topik": {"type": "string"}, "kata_kunci": {"type": "string"},
    },
    "required": ["alat", "lokasi", "hari", "min_magnitudo", "komoditas", "topik", "kata_kunci"],
}

# Router aturan (jaring pengaman bila LLM kecil salah memilih alat)
RULE_TOOLS = [
    ("titik_panas", ["titik panas", "hotspot", "karhutla", "kebakaran hutan", "kebakaran lahan", "titik api", "firms"]),
    ("gempa", ["gempa", "tsunami", "magnitudo", "lindu"]),
    ("kualitas_udara", ["kualitas udara", "udara", "aqi", "polusi", "pm2", "pm 2", "kabut asap", "ispa"]),
    ("harga_pangan", ["harga", "beras", "cabai", "cabe", "bawang", "telur", "daging", "minyak goreng", "gula", "pangan"]),
    ("berita", ["berita", "kabar", "liputan", "diberitakan"]),
    ("kesehatan_pipeline", ["pipeline", "kualitas data", "data quality", "status data", "sumber data", "freshness"]),
    ("cuaca", ["cuaca", "prakiraan", "hujan", "suhu", "berawan", "gerimis", "kelembapan"]),
    ("internet_outage", ["gangguan internet", "internet mati", "internet down", "internet putus", "internet lumpuh",
                         "outage", "pemadaman internet", "blackout", "anomali trafik", "internet error"]),
    ("internet_operator", ["operator", "sinyal", "kecepatan internet", "internet", "telkomsel", "indosat", "im3", "re:\\bxl\\b",
                           "re:\\btri\\b", "indihome", "telkom", "smartfren", "trafik", "traffic", "latensi", "re:\\bping\\b",
                           "re:\\bbgp\\b", "rpki", "mbps"]),
    ("sebaran_sel", ["bts", "menara", "sel seluler", "jumlah sel", "sebaran sel", "opencellid", "cakupan sinyal", "coverage",
                     "re:\\b[2345]g\\b", "sinyal"]),
]


NET_GENERIC = ["internet", "kecepatan", "trafik", "traffic", "latensi", "re:\\bping\\b", "re:\\bbgp\\b", "rpki", "mbps", "speed"]
FOLLOWUP = re.compile(r"^\s*(kalau|kalo|klo|bagaimana dengan|gimana dengan|terus|lalu|trus|dan|yang)\b", re.I)


def is_followup(question: str) -> bool:
    """Pertanyaan lanjutan pendek ("kalau di Jawa Barat?", "yang di Riau?") yang bergantung pada pertanyaan sebelumnya."""
    return bool(FOLLOWUP.match(question)) and len(question.split()) <= 6


def _kw_hit(ql: str, kws: list[str]) -> bool:
    return any(re.search(k[3:], ql) if k.startswith("re:") else k in ql for k in kws)
RULE_TOPICS = [("kebakaran", ["karhutla", "kebakaran", "titik panas"]), ("banjir_longsor", ["banjir", "longsor"]),
               ("gempa", ["gempa", "tsunami"]), ("gunung_api", ["erupsi", "gunung", "vulkanik"]),
               ("cuaca", ["cuaca", "hujan", "kekeringan", "angin"]), ("kualitas_udara", ["udara", "asap", "polusi"]),
               ("pangan", ["harga", "pangan", "beras", "cabai"])]


def grounded(question: str, value: str) -> bool:
    """Apakah nilai parameter dari LLM benar-benar disebut di pertanyaan (langsung atau via alias)?"""
    q, v = llm_lib.norm(question), llm_lib.norm(value)
    if not v:
        return True
    if v in q or v.replace(" ", "") in q.replace(" ", ""):
        return True
    if any(w in q.split() for w in v.split() if len(w) >= 4 and w not in ("kota", "kabupaten", "provinsi")):
        return True
    return any(re.search(rf"\b{re.escape(a)}\b", q) and full.endswith(v.replace("kota ", "").replace("kabupaten ", ""))
               for a, full in llm_lib.ALIASES.items())


def rule_route(question: str) -> dict:
    ql = question.lower()
    tools = [t for t, kws in RULE_TOOLS if _kw_hit(ql, kws)]
    if "internet_outage" in tools and "internet_operator" in tools and not _operators(ql):
        tools.remove("internet_operator")         # "gangguan internet" saja -> cukup outage
    if "cuaca" in tools and "berita" not in tools and any(k in ql for k in ("banjir", "longsor")):
        tools.append("berita")
    if "berita" in tools and len(tools) > 1:          # "berita karhutla" -> cukup berita
        tools = ["berita"] + [t for t in tools if t not in ("berita", "titik_panas", "harga_pangan")][:1]
    m = re.search(r"(\d+)\s*(hari|jam|minggu)", ql)
    hari = 3
    if m:
        n, unit = int(m.group(1)), m.group(2)
        hari = max(1, n // 24) if unit == "jam" else n * 7 if unit == "minggu" else n
    elif any(k in ql for k in ("hari ini", "sekarang", "terkini", "24 jam")):
        hari = 1
    elif re.search(r"\b(seminggu|minggu ini|sepekan|pekan ini)\b", ql):
        hari = 7
    hari_explicit = bool(m) or hari != 3
    names = llm_lib.rule_scan(question) + llm_lib.rule_scan(question.title())
    hit = llm_lib.resolve(names, question) if names else None
    mag = re.search(r"\b(?:m|mag|magnitudo)\s*(?:>=?|di atas|lebih dari)?\s*(\d+(?:[.,]\d)?)\b", ql)
    topik = next((t for t, kws in RULE_TOPICS if any(k in ql for k in kws)), "")
    if not tools and topik:        # banjir, erupsi, cuaca: satu-satunya sumber di platform adalah berita
        tools = ["berita"]
    return {"alat": tools[:3], "lokasi": hit["matched"] if hit else "", "hari": hari,
            "min_magnitudo": float(mag.group(1).replace(",", ".")) if mag and "gempa" in tools else 0,
            "komoditas": next((k for k, _, _ in COMMODITIES if k in ql), ""), "topik": topik, "kata_kunci": "",
            "_explicit": {"hari": hari_explicit, "min_magnitudo": bool(mag)}}


ANSWER_PROMPT = """Kamu adalah asisten data untuk platform Indonesia Realtime Monitor.
Jawab pertanyaan pengguna dalam bahasa Indonesia HANYA berdasarkan DATA di bawah.
Aturan:
- Jangan menambah fakta, angka, atau lokasi yang tidak ada di DATA. Jangan menebak.
- Sebut angka, satuan, tanggal/rentang waktu, dan sumber data (mis. BMKG, NASA FIRMS, PIHPS BI, Cloudflare Radar, OpenCelliD).
- Jika DATA kosong atau tidak cukup, katakan terus terang bahwa datanya belum tersedia di platform.
- Jika DATA memuat "catatan", sampaikan keterbatasan itu secara singkat.
- Setiap alat punya daftar "fakta" berisi kalimat yang PASTI benar. Jadikan fakta itu dasar jawaban:
  boleh diparafrasekan dan dirangkai, tetapi angka, nama tempat, dan artinya tidak boleh diubah.
- Jangan menyebut nama alat atau nama field (mis. kesehatan_pipeline, titik_panas, sebaran_sel).
- Ringkas: maksimal 6 kalimat atau daftar pendek."""


# ---------------------------------------------------------------- helpers
@lru_cache(maxsize=1)
def _gaz_by_kode() -> dict:
    return {r["kode"]: r for r in csv.DictReader(open(llm_lib.GAZETTEER, encoding="utf-8"))}


def resolve_place(name: str) -> dict | None:
    """Nama tempat -> wilayah gazetteer + radius perkiraan (km) dari luas wilayah."""
    if not name.strip():
        return None
    hit = llm_lib.resolve([name], name, primary=name)
    if not hit:
        return None
    luas = _gaz_by_kode().get(hit["kode"], {}).get("luas_km2") or ""
    area = float(luas) if luas else (50000 if hit["level"] == 1 else 2000)
    hit["radius_km"] = round(max(30.0, 1.3 * math.sqrt(area / math.pi)), 0)
    return hit


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(a))


REFERENCE_DIR = os.path.dirname(llm_lib.GAZETTEER)


@lru_cache(maxsize=2)
def boundaries(level: int) -> dict:
    """Poligon batas (1 = provinsi, 2 = kab/kota) + STRtree untuk point-in-polygon massal."""
    from shapely import STRtree
    from shapely.geometry import shape
    name = "batas_provinsi.geojson" if level == 1 else "batas_kabkota.geojson"
    from shapely.geometry import Point
    fc = json.load(open(os.path.join(REFERENCE_DIR, name), encoding="utf-8"))
    props = [f["properties"] for f in fc["features"]]
    gaz = _gaz_by_kode()
    geoms = []
    for p, f in zip(props, fc["features"]):
        g, row = shape(f["geometry"]), gaz.get(p["kode"], {})
        # QC poligon sumber (sama dengan scripts/risk.py): luas menyimpang >3x dari luas resmi -> lingkaran perkiraan
        luas = float(row["luas_km2"]) if row.get("luas_km2") else None
        if row.get("lat"):
            area = g.area * 111.0 ** 2
            cap = Point(float(row["lng"]), float(row["lat"]))
            ratio_ok = True if not luas else 1 / 3 <= area / luas <= 3
            if g.is_empty or not ratio_ok or g.distance(cap) * 111.0 > 40:
                r_km = math.sqrt((luas or max(area, 100.0)) / math.pi)
                g = cap.buffer(r_km / 111.0, 24)
                p["batas_perkiraan"] = True
        geoms.append(g)
    return {"props": props, "geoms": geoms, "tree": STRtree(geoms),
            "by_kode": {p["kode"]: g for p, g in zip(props, geoms)}}


def assign_regions(points: list[tuple[float, float]], level: int = 1) -> list[dict | None]:
    """[(lat, lon)] -> properti wilayah yang memuat titik (None bila di laut/luar Indonesia)."""
    import shapely
    if not points:
        return []
    b = boundaries(level)
    pts = shapely.points([(lon, lat) for lat, lon in points])
    out: list[dict | None] = [None] * len(points)
    pi, gi = b["tree"].query(pts, predicate="intersects")
    for p_idx, g_idx in zip(pi, gi):
        if out[p_idx] is None:
            out[p_idx] = b["props"][g_idx]
    return out


def place_filter(place: dict, points: list[tuple[float, float]], buffer_deg: float = 0.0) -> list[bool]:
    """Titik mana yang berada di dalam wilayah `place` (opsional diperluas buffer_deg derajat)."""
    import shapely
    b = boundaries(place["level"])
    geom = b["by_kode"].get(place["kode"])
    if geom is None:
        return [haversine_km(place["lat"], place["lng"], la, lo) <= place["radius_km"] for la, lo in points]
    if buffer_deg:
        geom = geom.buffer(buffer_deg)
    return list(shapely.contains_xy(geom, [lo for _, lo in points], [la for la, _ in points]))


def _rp(v) -> str:
    return "Rp" + f"{round(v):,}".replace(",", ".")


def _hari(h: int) -> str:
    return "24 jam terakhir" if h == 1 else f"{h} hari terakhir"


def _clamp(v, lo, hi, default):
    try:
        return max(lo, min(hi, type(default)(v)))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- tools
def tool_gempa(ch, a: dict) -> dict:
    hari, mag = _clamp(a.get("hari"), 1, 30, 3), _clamp(a.get("min_magnitudo"), 0.0, 9.9, 0.0)
    place = resolve_place(a.get("lokasi", ""))
    rows = ch.query(
        """
        SELECT toString(event_time), magnitude, depth_km, region, source, lat, lon
        FROM earthquake_events FINAL
        WHERE event_time >= now() - toIntervalDay({d:UInt32}) AND magnitude >= {m:Float32}
        ORDER BY magnitude DESC, event_time DESC LIMIT 500
        """, parameters={"d": hari, "m": mag}).result_rows
    note = "BMKG dan USGS bisa mencatat gempa yang sama; keduanya ditampilkan."
    if place:
        keep = place_filter(place, [(r[5], r[6]) for r in rows], buffer_deg=0.5)
        rows = [r for r, k in zip(rows, keep) if k]
        note += f" Filter lokasi: episentrum di dalam atau ±50 km dari batas {place['nama']}."
    items = [{"waktu_utc": r[0], "magnitudo": round(r[1], 1), "kedalaman_km": round(r[2]), "wilayah": r[3],
              "sumber": r[4].upper()} for r in rows[:10]]
    where = f" di sekitar {place['nama']}" if place else " di wilayah Indonesia dan sekitarnya"
    fakta = [f"Tercatat {len(rows)} gempa{f' bermagnitudo {mag} ke atas' if mag else ''}{where} dalam {_hari(hari)} "
             f"(sumber BMKG dan USGS)."]
    if items:
        g = items[0]
        fakta.append(f"Gempa terbesar M{g['magnitudo']} di {g['wilayah']} pada {g['waktu_utc'][:16]} UTC, "
                     f"kedalaman {g['kedalaman_km']} km ({g['sumber']}).")
    return {"alat": "gempa", "fakta": fakta, "rentang_hari": hari, "min_magnitudo": mag, "jumlah": len(rows),
            "magnitudo_terbesar": items[0]["magnitudo"] if items else None, "gempa": items, "catatan": note,
            "_focus": place}


def tool_titik_panas(ch, a: dict) -> dict:
    hari = _clamp(a.get("hari"), 1, 10, 1)
    place = resolve_place(a.get("lokasi", ""))
    rows = ch.query(
        """
        SELECT lat, lon, frp, toString(acq_time) FROM hotspots FINAL
        WHERE acq_time >= now() - toIntervalDay({d:UInt32}) AND confidence IN ('n', 'h')
        """, parameters={"d": hari}).result_rows
    note = "Hanya confidence nominal/high. Provinsi ditentukan dari batas wilayah (poligon disederhanakan)."
    if place:
        keep = place_filter(place, [(r[0], r[1]) for r in rows])
        rows = [r for r, k in zip(rows, keep) if k]
        note += f" Filter lokasi: di dalam batas {place['nama']}."
    regions = assign_regions([(r[0], r[1]) for r in rows], level=1)
    per_prov: dict[str, int] = {}
    outside = 0
    for reg in regions:
        if reg is None:
            outside += 1
        else:
            per_prov[reg["nama"]] = per_prov.get(reg["nama"], 0) + 1
    top = sorted(per_prov.items(), key=lambda x: -x[1])[:8]
    n_id = len(rows) - outside
    where = f"di dalam batas {place['nama']}" if place else "di wilayah Indonesia"
    fakta = [f"Terdapat {n_id} titik panas {where} dalam {_hari(hari)} (NASA FIRMS VIIRS, confidence nominal dan high)."]
    if not place and top:
        fakta.append("Provinsi dengan titik panas terbanyak: " + ", ".join(f"{k} ({v})" for k, v in top[:5]) + ".")
    if rows:
        fakta.append(f"Kekuatan api (FRP) tertinggi {round(max(r[2] for r in rows), 1)} MW.")
    if outside and not place:
        fakta.append(f"{outside} titik lain berada di luar batas Indonesia (negara tetangga/perairan) dan tidak dihitung.")
    return {"alat": "titik_panas", "fakta": fakta, "sumber": "NASA FIRMS (VIIRS)", "rentang_hari": hari,
            "jumlah_di_indonesia": len(rows) - outside, "di_luar_batas_indonesia": outside,
            "frp_maks_mw": round(max((r[2] for r in rows), default=0), 1),
            "per_provinsi": [{"provinsi": k, "titik": v} for k, v in top],
            "catatan": note, "_focus": place}


def tool_kualitas_udara(ch, a: dict) -> dict:
    place = resolve_place(a.get("lokasi", ""))
    rows = ch.query(
        """
        SELECT city, province, any(lat), any(lon), toString(max(obs_time)),
               argMax(us_aqi, obs_time), argMax(pm2_5, obs_time), argMax(pm10, obs_time)
        FROM air_quality FINAL WHERE obs_time >= now() - INTERVAL 1 DAY
        GROUP BY city, province
        """).result_rows
    cat = lambda v: ("Baik" if v <= 50 else "Sedang" if v <= 100 else "Tidak sehat bagi kelompok sensitif"
                     if v <= 150 else "Tidak sehat" if v <= 200 else "Sangat tidak sehat" if v <= 300 else "Berbahaya")
    items = [{"kota": r[0], "provinsi": r[1], "waktu_utc": r[4], "us_aqi": round(r[5]), "kategori": cat(r[5]),
              "pm2_5_ugm3": round(r[6], 1), "_lat": r[2], "_lon": r[3]} for r in rows]
    if place:
        items.sort(key=lambda x: haversine_km(place["lat"], place["lng"], x["_lat"], x["_lon"]))
        pick, note = items[:1], f"Data dari kota pemantauan terdekat dengan {place['nama']} (platform memantau 38 ibu kota provinsi)."
    else:
        items.sort(key=lambda x: -x["us_aqi"])
        pick, note = items[:5] + items[-2:], "5 kota dengan AQI tertinggi dan 2 terendah dari 38 ibu kota provinsi."
    seen, clean = set(), []
    for x in pick:
        if x["kota"] not in seen:
            seen.add(x["kota"])
            clean.append({k: v for k, v in x.items() if not k.startswith("_")})
    fakta = [f"{x['kota']} ({x['provinsi']}): US AQI {x['us_aqi']}, kategori {x['kategori']}, PM2.5 {x['pm2_5_ugm3']} µg/m³ "
             f"(data {x['waktu_utc'][:16]} UTC, Open-Meteo)." for x in clean[:3]]
    return {"alat": "kualitas_udara", "fakta": fakta, "sumber": "Open-Meteo Air Quality", "kota": clean, "catatan": note,
            "_focus": place}


def tool_harga_pangan(ch, a: dict) -> dict:
    kom = (a.get("komoditas") or "").lower()
    cid, cname = next(((i, n) for k, i, n in COMMODITIES if k in kom), (1, "Beras"))
    place = resolve_place(a.get("lokasi", ""))
    rows = ch.query(
        """
        SELECT province, price, national_avg, pct_change, toString(price_date), toString(prev_date)
        FROM food_prices FINAL
        WHERE commodity_id = {c:UInt8}
          AND price_date = (SELECT max(price_date) FROM food_prices WHERE commodity_id = {c:UInt8})
        ORDER BY price DESC
        """, parameters={"c": cid}).result_rows
    if not rows:
        return {"alat": "harga_pangan", "komoditas": cname, "data": [], "catatan": "belum ada data harga"}
    fmt = lambda r: {"provinsi": r[0], "harga_rp": round(r[1]), "selisih_dari_nasional_pct":
                     round((r[1] - r[2]) / r[2] * 100, 1) if r[2] else None, "perubahan_pct": round(r[3], 1)}
    out = {"alat": "harga_pangan", "sumber": "PIHPS Nasional, Bank Indonesia (pasar tradisional)",
           "komoditas": cname, "tanggal": rows[0][4], "rata_rata_nasional_rp": round(rows[0][2]),
           "_focus": place}
    unit = "liter" if cid == 9 else "kg"
    nat = rows[0][2]
    head = f"Harga {cname} (pasar tradisional, PIHPS BI) tanggal {rows[0][4]}: rata-rata nasional {_rp(nat)}/{unit}."

    def rel(r) -> str:
        d = (r[1] - nat) / nat * 100 if nat else 0
        if abs(d) < 0.05:
            return "sama dengan rata-rata nasional"
        return f"{abs(d):.1f}% lebih {'tinggi' if d > 0 else 'rendah'} dari rata-rata nasional"

    def trend(r) -> str:
        if not r[3]:
            return f"tidak berubah dibanding data {r[5]}"
        return f"{'naik' if r[3] > 0 else 'turun'} {abs(r[3]):.1f}% dibanding data {r[5]}"

    q = a.get("_q", "")
    want_hi = any(k in q for k in ("mahal", "tinggi", "tertinggi"))
    want_lo = any(k in q for k in ("murah", "rendah", "terendah"))
    if place:
        match = [r for r in rows if (llm_lib.resolve([r[0]], r[0]) or {}).get("prov_kode") == place["prov_kode"]]
        out["provinsi_diminta"] = [fmt(r) for r in match]
        out["catatan"] = ("Harga di tingkat provinsi." if match else
                          f"Provinsi {place['prov_nama']} tidak ada di data PIHPS untuk tanggal ini.")
        out["fakta"] = [head] + [f"{r[0]}: {_rp(r[1])}/{unit}, {rel(r)}; {trend(r)}." for r in match] \
            + ([] if match else [out["catatan"]])
    else:
        hi, lo = rows[:3], rows[-3:][::-1]
        out["fakta"] = [head]
        if want_hi or not want_lo:
            out["tertinggi"] = [fmt(r) for r in hi]
            out["fakta"].append(f"Provinsi dengan harga {cname} PALING MAHAL: {hi[0][0]} {_rp(hi[0][1])}/{unit} "
                                f"({rel(hi[0])}).")
            out["fakta"].append("Urutan termahal: " + ", ".join(f"{r[0]} {_rp(r[1])}" for r in hi) + ".")
        if want_lo or not want_hi:
            out["terendah"] = [fmt(r) for r in lo]
            out["fakta"].append(f"Provinsi dengan harga {cname} PALING MURAH: {lo[0][0]} {_rp(lo[0][1])}/{unit} "
                                f"({rel(lo[0])}).")
            out["fakta"].append("Urutan termurah: " + ", ".join(f"{r[0]} {_rp(r[1])}" for r in lo) + ".")
    return out


def tool_berita(ch, a: dict) -> dict:
    hari = _clamp(a.get("hari"), 1, 7, 3)
    topik = a.get("topik") if a.get("topik") in llm_lib.TOPICS else ""
    kata = (a.get("kata_kunci") or "").strip()[:40]
    place = resolve_place(a.get("lokasi", ""))
    prov = place["prov_kode"] if place else ""
    rows = ch.query(
        """
        SELECT n.title, n.link, n.publisher, toString(n.published_at), e.summary_llm, e.nama_wilayah
        FROM news AS n FINAL
        LEFT JOIN (SELECT * FROM news_enriched FINAL
                   ORDER BY status = 'ok' DESC, enriched_at DESC LIMIT 1 BY news_id) AS e ON e.news_id = n.news_id
        WHERE n.published_at >= now() - toIntervalDay({d:UInt32})
          AND ({t:String} = '' OR has(if(notEmpty(e.topics_llm), e.topics_llm, n.topics), {t:String}))
          AND ({p:String} = '' OR e.prov_kode = {p:String})
          AND ({k:String} = '' OR positionCaseInsensitiveUTF8(n.title, {k:String}) > 0)
        ORDER BY n.published_at DESC LIMIT 8
        """, parameters={"d": hari, "t": topik, "p": prov, "k": kata}).result_rows
    items = [{"judul": r[0], "link": r[1], "media": r[2], "waktu_utc": r[3], "ringkasan": r[4], "lokasi": r[5]}
             for r in rows]
    fakta = [f"Ditemukan {len(items)} berita{' topik ' + topik.replace('_', ' ') if topik else ''}"
             f"{' terkait ' + place['nama'] if place else ''} dalam {_hari(hari)}."]
    fakta += [f"{b['media']}: \"{b['judul']}\"" for b in items[:3]]
    return {"alat": "berita", "fakta": fakta, "rentang_hari": hari, "topik": topik, "jumlah": len(items), "berita": items,
            "catatan": "Berita dari 8 portal nasional; lokasi hasil geotagging otomatis." if items else
            "Tidak ada berita yang cocok di platform.", "_focus": place}


def tool_kesehatan(ch, a: dict) -> dict:
    rows = ch.query(
        """
        SELECT source, check_name, argMax(status, checked_at) AS st, round(argMax(value, checked_at), 1),
               argMax(detail, checked_at)
        FROM dq_results WHERE checked_at > now() - INTERVAL 1 HOUR
        GROUP BY source, check_name
        """).result_rows
    bad = [{"sumber": r[0], "cek": r[1], "status": r[2], "nilai": r[3], "detail": r[4]} for r in rows if r[2] != "pass"]
    fakta = ([f"Semua {len(rows)} cek kualitas data dalam 1 jam terakhir lulus."] if not bad else
             [f"{len(bad)} dari {len(rows)} cek kualitas data bermasalah:"] +
             [f"{b['sumber']} {b['cek']} = {b['nilai']} ({b['status']})" for b in bad[:5]])
    return {"alat": "kesehatan_pipeline", "fakta": fakta, "total_cek": len(rows), "bermasalah": bad,
            "catatan": "Semua cek lulus." if not bad else f"{len(bad)} cek berstatus warn/fail."}


# ---------------------------------------------------------------- tools dari snapshot JSON (data publik situs)
# Snapshot dibuat GitHub Actions (cuaca BMKG, Cloudflare Radar, OpenCelliD). Dibaca dari folder lokal bila ada,
# kalau tidak dari salinan publik di GitHub Pages. Semua angka dihitung di sini, bukan oleh LLM.
SNAPSHOT_DIR = os.getenv("SNAPSHOT_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "site", "data"))
SNAPSHOT_URL = os.getenv("SNAPSHOT_URL", "https://elsonsaputra03-dot.github.io/indo-realtime-monitor/data/")
_SNAP_CACHE: dict[str, tuple[float, dict]] = {}


def _snap(name: str, ttl_s: int = 1800) -> dict:
    hit = _SNAP_CACHE.get(name)
    if hit and time.monotonic() - hit[0] < ttl_s:
        return hit[1]
    path = os.path.join(SNAPSHOT_DIR, name)
    if os.path.exists(path):
        doc = json.load(open(path, encoding="utf-8"))
    else:
        r = httpx.get(SNAPSHOT_URL + name, timeout=20, follow_redirects=True)
        r.raise_for_status()
        doc = r.json()
    _SNAP_CACHE[name] = (time.monotonic(), doc)
    return doc


def _now(a: dict):
    from datetime import datetime, timezone
    return a.get("_now") or datetime.now(timezone.utc)


def _dt(s: str):
    from datetime import datetime, timezone
    d = datetime.fromisoformat(str(s).replace("Z", "+00:00").replace(" ", "T"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _wib(s: str) -> str:
    from datetime import timedelta
    return (_dt(s) + timedelta(hours=7)).strftime("%d-%m-%Y %H:%M") + " WIB"


def _num(v):
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def _f(v, d=1) -> str:
    return f"{v:,.{d}f}".replace(",", "#").replace(".", ",").replace("#", ".")


def _n(v) -> str:
    return _f(v, 0)


def _in_place(place: dict, kode: str) -> bool:
    """Kode wilayah (prov 'xx', kab 'xx.yy', desa 'xx.yy.zz.nnnn') berada di dalam `place`?"""
    return kode.startswith(place["kode"] + ".") or kode == place["kode"] if place["level"] == 2 \
        else kode.split(".")[0] == place["prov_kode"]


# ---- cuaca (BMKG)
def tool_cuaca(ch, a: dict) -> dict:
    from datetime import timedelta
    doc = _snap("web_weather.json")
    rows = [r for r in doc.get("rows", []) if r.get("forecast_utc") and r.get("adm4")]
    place = resolve_place(a.get("lokasi", ""))
    locs: dict[str, dict] = {}
    for r in rows:
        locs.setdefault(r["adm4"], {"desa": r.get("desa"), "kec": r.get("kecamatan"), "kab": r.get("kotkab"),
                                    "prov": r.get("provinsi"), "rows": []})["rows"].append(r)
    names = [f"{v['desa']}, {v['kab']}" for v in locs.values()]
    out = {"alat": "cuaca", "sumber": "BMKG (prakiraan per 3 jam)", "snapshot_utc": doc.get("generated_at"),
           "lokasi_tersedia": names, "_focus": place}
    if place:
        locs = {k: v for k, v in locs.items() if _in_place(place, k)}
        if not locs:
            out["fakta"] = [f"Prakiraan cuaca BMKG di platform ini baru mencakup {len(names)} lokasi "
                            f"({'; '.join(names)}); {place['nama']} belum termasuk."]
            out["catatan"] = "Cakupan lokasi cuaca masih terbatas."
            return out
    q, now = a.get("_q", ""), _now(a)
    fakta, detail = [], []
    for code, v in list(locs.items())[:3]:
        rs = sorted(v["rows"], key=lambda r: r["forecast_utc"])
        r0 = rs[0]
        off = _dt(r0["local_datetime"]) - _dt(r0["forecast_utc"]) if r0.get("local_datetime") else timedelta(hours=7)
        zone = {7: "WIB", 8: "WITA", 9: "WIT"}.get(round(off.total_seconds() / 3600), "waktu setempat")
        local_now = now + off
        if "lusa" in q:
            day, label = (local_now + timedelta(days=2)).date(), "lusa"
        elif "besok" in q:
            day, label = (local_now + timedelta(days=1)).date(), "besok"
        else:
            day, label = None, "24 jam ke depan"
        if day:
            pick = [r for r in rs if (_dt(r["forecast_utc"]) + off).date() == day]
        else:
            pick = [r for r in rs if now - timedelta(hours=1, minutes=30) <= _dt(r["forecast_utc"]) <= now + timedelta(hours=24)]
        where = f"{v['desa']} ({v['kab']})"
        if not pick:
            fakta.append(f"{where}: prakiraan untuk {label} belum ada di snapshot terakhir "
                         f"(prakiraan tersedia sampai {(_dt(rs[-1]['forecast_utc']) + off).strftime('%d-%m-%Y %H:%M')} {zone}).")
            continue
        ts = [_num(r.get("t")) for r in pick if _num(r.get("t")) is not None]
        rain = [r for r in pick if "hujan" in str(r.get("weather_desc", "")).lower()]
        tp = max((_num(r.get("tp")) or 0 for r in pick), default=0)
        jam = lambda r: (_dt(r["forecast_utc"]) + off).strftime("%d-%m %H:%M")
        first = pick[0]
        s = (f"{where}, {label}: suhu {_f(min(ts), 0)}–{_f(max(ts), 0)}°C" if ts else f"{where}, {label}:")
        s += (f"; hujan diprakirakan pada {len(rain)} dari {len(pick)} slot 3-jam (mulai {jam(rain[0])} {zone}, "
              f"'{rain[0]['weather_desc']}'), curah hujan tertinggi {_f(tp)} mm per 3 jam." if rain
              else f"; tidak ada prakiraan hujan ({len(pick)} slot 3-jam).")
        fakta.append(s)
        if not day:
            fakta.append(f"{where} sekitar {jam(first)} {zone}: {first.get('weather_desc')}, {first.get('t')}°C, "
                         f"kelembapan {first.get('hu')}%.")
        detail.append({"lokasi": where, "provinsi": v["prov"], "periode": label,
                       "slot": [{"waktu": jam(r) + " " + zone, "cuaca": r.get("weather_desc"), "suhu_c": r.get("t"),
                                 "kelembapan": r.get("hu"), "hujan_mm": r.get("tp")} for r in pick[:8]]})
    out.update(fakta=fakta, prakiraan=detail,
               catatan=f"Prakiraan BMKG untuk {len(names)} lokasi pantau (tingkat kelurahan/desa), diperbarui 2x sehari."
                       + ("" if place else " Sebut nama kota untuk memilih lokasi."))
    return out


# ---- Cloudflare Radar: helper operator & provinsi
OPERATORS = [  # (regex di pertanyaan, ASN di snapshot Radar, label, nama operator di OpenCelliD)
    (r"\btelkomsel\b|\bsimpati\b|\bby\.u\b", "23693", "Telkomsel", "Telkomsel"),
    (r"\bindosat\b|\bim3\b|\booredoo\b", "4761", "Indosat", "Indosat"),
    (r"\bxl\b|\baxis\b", "24203", "XL Axiata", "XL Axiata"),
    (r"\btri\b|\bthree\b|\bkartu 3\b", "45727", "Tri (IOH)", "Tri (IOH)"),
    (r"\bindihome\b|\btelkom indonesia\b|\btelkom\b", "7713", "Telkom Indonesia", None),
    (r"\bsmartfren\b", None, "Smartfren", "Smartfren"),
]


def _operators(q: str) -> list[tuple]:
    return [o for o in OPERATORS if re.search(o[0], q)]


_EN_DIR = [("Southeast", "Tenggara"), ("Southwest", "Barat Daya"), ("Northeast", "Timur Laut"), ("North", "Utara"),
           ("South", "Selatan"), ("East", "Timur"), ("West", "Barat"), ("Central", "Tengah"), ("Highland", "Pegunungan")]
_EN_FIXED = {"Jakarta": "DKI Jakarta", "Special Region of Yogyakarta": "DI Yogyakarta", "Yogyakarta": "DI Yogyakarta",
             "Riau Islands": "Kepulauan Riau", "Bangka-Belitung Islands": "Kepulauan Bangka Belitung",
             "Bangka–Belitung Islands": "Kepulauan Bangka Belitung", "Bangka Belitung Islands": "Kepulauan Bangka Belitung"}


def prov_name_id(n: str) -> str:
    """Nama provinsi Radar (Inggris, mis. 'West Java') -> nama Indonesia ('Jawa Barat'); sama dengan provName di situs."""
    n = str(n or "")
    if n in _EN_FIXED:
        return _EN_FIXED[n]
    x = re.sub(r"\bJava\b", "Jawa", n)
    x = re.sub(r"\bSumatra\b", "Sumatera", x)
    x = re.sub(r" Province$", "", x)
    for en, idn in _EN_DIR:
        if x.startswith(en + " "):
            return x[len(en) + 1:] + " " + idn
    return x


def _radar_geo(d: dict) -> dict:
    """geoId Radar -> {nama, prov_kode} (lewat gazetteer)."""
    out = {}
    for g in d.get("geo") or []:
        nm = prov_name_id(g.get("name"))
        hit = llm_lib.resolve([nm], nm, primary=nm)
        out[str(g.get("geoId"))] = {"nama": nm, "prov_kode": hit["prov_kode"] if hit and hit["level"] == 1 else None}
    return out


def _label(d: dict, asn) -> str:
    return ((d.get("asns") or {}).get(str(asn)) or {}).get("label") or f"AS{asn}"


def _series_drops(s: dict | None, since) -> dict:
    """Port dari drops()/gaps() di pub-views.js: jam dengan trafik < 60% median jam yang sama (hari-dalam-minggu sama)
    di minggu lain; jam di dalam celah data (>= 6 jam beruntun hampir nol) tidak dihitung."""
    if not s or not s.get("t"):
        return {"ada_data": False}
    t = [_dt(x) for x in s["t"]]
    v = [_num(x) for x in s.get("v", [])]
    gap, run = set(), []
    for i, x in enumerate(v):
        if x is None or x <= 0.02:
            run.append(i)
        else:
            if len(run) >= 6:
                gap.update(run)
            run = []
    if len(run) >= 6:
        gap.update(run)
    by_how: dict[int, list[int]] = {}
    for i, d in enumerate(t):
        by_how.setdefault(d.weekday() * 24 + d.hour, []).append(i)
    drops = []
    for i, d in enumerate(t):
        if d < since or v[i] is None or i in gap:
            continue
        others = sorted(v[j] for j in by_how[d.weekday() * 24 + d.hour] if j != i and v[j] is not None and j not in gap)
        if len(others) < 2:
            continue
        med = others[len(others) // 2]
        if med > 0.1 and v[i] < 0.6 * med:
            drops.append((d, v[i] / med))
    return {"ada_data": True, "jam_turun": len(drops), "jam_celah": sum(1 for i in gap if t[i] >= since),
            "terendah": min(drops, key=lambda x: x[1]) if drops else None, "terakhir": t[-1]}


# ---- internet_outage
CAUSE_ID = {"POWER_OUTAGE": "pemadaman listrik", "CABLE_CUT": "kabel putus", "WEATHER": "cuaca",
            "GOVERNMENT_DIRECTED": "perintah pemerintah", "TECHNICAL_PROBLEM": "masalah teknis", "MAINTENANCE": "pemeliharaan",
            "EARTHQUAKE": "gempa", "FIRE": "kebakaran", "CYBERATTACK": "serangan siber", "MILITARY_ACTION": "aksi militer",
            "UNKNOWN": "tidak diketahui"}


def tool_internet_outage(ch, a: dict) -> dict:
    from datetime import timedelta
    d = _snap("radar_id.json")
    now = _now(a)
    hari = _clamp(a.get("hari"), 1, 365, 3) if a.get("_hari_explicit") else 365
    since = now - timedelta(days=hari)
    ops = [o for o in _operators(a.get("_q", "")) if o[1]]
    place = resolve_place(a.get("lokasi", ""))
    win = "12 bulan terakhir" if hari == 365 else _hari(hari)

    def keep(asns) -> bool:
        return not ops or any(str(x) in {o[1] for o in ops} for x in asns)

    outs = [o for o in d.get("outages") or [] if o.get("startDate") and _dt(o["startDate"]) >= since and keep(o.get("asns") or [])]
    if place:   # outage Radar umumnya tingkat negara/operator; cocokkan nama provinsi di teks scope/deskripsi
        names = {llm_lib.norm(place["prov_nama"])} | {llm_lib.norm(g.get("name", "")) for g in d.get("geo") or []
                                                     if prov_name_id(g.get("name")) == place["prov_nama"]}
        names.discard("")
        outs = [o for o in outs if any(nm in llm_lib.norm(f"{o.get('scope') or ''} {o.get('description') or ''} "
                                                         f"{' '.join(o.get('locations') or [])}") for nm in names)]
    outs.sort(key=lambda o: o["startDate"], reverse=True)
    anom = [x for x in d.get("anomalies") or [] if x.get("startDate") and _dt(x["startDate"]) >= since
            and (not ops or str(x.get("asn")) in {o[1] for o in ops})]
    anom.sort(key=lambda x: x["startDate"], reverse=True)
    who = " / ".join(o[2] for o in ops) if ops else "Indonesia"
    where = f" yang menyebut {place['prov_nama']}" if place else ""
    fakta = [f"Cloudflare Radar mencatat {len(outs)} gangguan internet (outage) terverifikasi untuk {who}{where} dalam {win} "
             f"(snapshot {_wib(d['generated_at'])})."]
    for o in outs[:3]:
        end = o.get("endDate")
        lama = ""
        if end:
            h = (_dt(end) - _dt(o["startDate"])).total_seconds() / 3600
            lama = f", durasi {_f(h * 60, 0)} menit" if h < 1 else f", durasi {_f(h)} jam" if h < 48 else f", durasi {_f(h / 24)} hari"
        fakta.append(f"Outage {_wib(o['startDate'])}: penyebab {CAUSE_ID.get(o.get('cause'), o.get('cause') or 'tidak disebut')}"
                     f"{', operator ' + ', '.join(n for n in o.get('asn_names') or [] if n) if o.get('asn_names') else ''}"
                     f"{', wilayah ' + o['scope'] if o.get('scope') else ''}{lama or ', belum ada waktu selesai'}.")
    fakta.append(f"Deteksi otomatis Radar (traffic anomaly) untuk {who}: {len(anom)} kejadian dalam {win}"
                 + (f", terakhir {_wib(anom[0]['startDate'])} ({anom[0].get('asn_name') or anom[0].get('location') or ''}, "
                    f"status {anom[0].get('status', '').lower() or '-'})." if anom else "."))
    if place:
        fakta.append("Catatan: outage di Radar biasanya dicatat per negara atau per operator, jarang per provinsi.")
    return {"alat": "internet_outage", "fakta": fakta, "sumber": "Cloudflare Radar (CC BY-NC 4.0)",
            "outage": [{"mulai": _wib(o["startDate"]), "selesai": _wib(o["endDate"]) if o.get("endDate") else None,
                        "penyebab": CAUSE_ID.get(o.get("cause"), o.get("cause")), "operator": o.get("asn_names"),
                        "wilayah": o.get("scope"), "keterangan": (o.get("description") or "")[:200]} for o in outs[:5]],
            "catatan": "Outage = kejadian yang diverifikasi tim Radar; anomaly = deteksi otomatis yang belum tentu outage. "
                       "Data dilihat dari luar jaringan operator (trafik yang melewati Cloudflare).", "_focus": place}


# ---- internet_operator
def tool_internet_operator(ch, a: dict) -> dict:
    from datetime import timedelta
    d = _snap("radar_id.json")
    q, now = a.get("_q", ""), _now(a)
    hari = _clamp(a.get("hari"), 1, 28, 7) if a.get("_hari_explicit") else 7
    named = _operators(q)
    ops = [o for o in named if o[1]] or [o for o in OPERATORS if o[1] and o[1] in (d.get("asns") or {})]
    place = resolve_place(a.get("lokasi", ""))
    fakta, tabel = [], []
    if any(not o[1] for o in named):
        fakta.append("Smartfren belum termasuk operator yang dipantau dari Cloudflare Radar di platform ini.")
    # kecepatan (median speed test 90 hari)
    sp = {x["key"]: x for x in d.get("speed_ops") or []}
    nat = sp.get("ID")
    for o in ops:
        x = sp.get(o[1])
        if not x:
            continue
        dl, ul, lat = _num(x.get("bandwidthDownload")), _num(x.get("bandwidthUpload")), _num(x.get("latencyIdle"))
        tabel.append({"operator": _label(d, o[1]), "unduh_mbps": dl, "unggah_mbps": ul, "latensi_ms": lat})
    tabel.sort(key=lambda r: -(r["unduh_mbps"] or 0))
    local_only = bool(place) and not named      # "trafik di Jawa Timur": hanya fakta provinsi
    if local_only:
        fakta.append("Kecepatan dan penurunan trafik per operator hanya tersedia secara nasional, bukan per provinsi.")
    if tabel and not local_only:
        if named:
            fakta += [f"{r['operator']}: median unduh {_f(r['unduh_mbps'])} Mbps, unggah {_f(r['unggah_mbps'])} Mbps, "
                      f"latensi {_f(r['latensi_ms'], 0)} ms (speed test pengguna Cloudflare, 90 hari)." for r in tabel]
        else:
            fakta.append("Median kecepatan unduh per operator (speed test pengguna Cloudflare, 90 hari): "
                         + ", ".join(f"{r['operator']} {_f(r['unduh_mbps'])} Mbps" for r in tabel) + ".")
    if nat and not local_only:
        fakta.append(f"Rata-rata Indonesia (semua jaringan): unduh {_f(_num(nat.get('bandwidthDownload')))} Mbps, "
                     f"latensi {_f(_num(nat.get('latencyIdle')), 0)} ms.")
    # penurunan trafik
    since = now - timedelta(days=hari)
    for o in [] if local_only else ops:
        tr = (d.get("traffic") or {}).get(o[1]) or {}
        s, src = (tr.get("netflows"), "NetFlows") if tr.get("netflows") else (tr.get("http"), "HTTP")
        r = _series_drops(s, since)
        if not r["ada_data"]:
            continue
        nm = _label(d, o[1])
        if r["jam_turun"]:
            lo = r["terendah"]
            fakta.append(f"Trafik {nm} ({src}) turun di bawah 60% dari normal selama {r['jam_turun']} jam dalam {_hari(hari)}; "
                         f"terendah {_wib(lo[0].isoformat())} ({_f(lo[1] * 100, 0)}% dari normal"
                         + ("; trafik hampir nol, bisa gangguan atau data yang tidak terlihat Cloudflare)." if lo[1] < 0.05 else ")."))
        elif named:
            fakta.append(f"Trafik {nm} ({src}) tidak menunjukkan penurunan tidak normal dalam {_hari(hari)}.")
        if r["jam_celah"] and named:
            fakta.append(f"{nm}: {r['jam_celah']} jam tanpa data (celah data, tidak dihitung sebagai gangguan).")
    if not named and not local_only:
        turun = [f for f in fakta if f.startswith("Trafik ")]
        if not turun:
            fakta.append(f"Tidak ada operator dengan penurunan trafik tidak normal dalam {_hari(hari)}.")
    # provinsi
    if place:
        geo = _radar_geo(d)
        gid = next((k for k, g in geo.items() if g["prov_kode"] == place["prov_kode"]), None)
        if not gid:
            fakta.append(f"Data trafik per provinsi untuk {place['prov_nama']} tidak ada di snapshot Radar.")
        else:
            for key in ([o[1] for o in ops] if named else ["ID"]):
                share = (((d.get("adm1") or {}).get(key) or {}).get("summary_0") or {})
                vals = {k: _num(v) for k, v in share.items() if k in geo and _num(v) is not None}
                if gid in vals:
                    rank = sorted(vals.values(), reverse=True).index(vals[gid]) + 1
                    who = "trafik internet Indonesia" if key == "ID" else f"trafik {_label(d, key)}"
                    fakta.append(f"{place['prov_nama']} menyumbang {_f(vals[gid], 2)}% dari {who} yang terlihat Cloudflare "
                                 f"(NetFlows 7 hari), peringkat {rank} dari {len(vals)} provinsi.")
            ts = (d.get("adm1_ts") or {}).get("netflows") or (d.get("adm1_ts") or {}).get("http")
            ser = [_num(x) for x in ((ts or {}).get("s") or {}).get(gid, [])]
            ser = [x for x in ser if x is not None]
            if len(ser) >= 8:
                med = sorted(ser[:-1])[len(ser[:-1]) // 2]
                chg = (ser[-1] - med) / med * 100 if med else 0
                fakta.append(f"Porsi harian {place['prov_nama']} hari terakhir {_f(ser[-1], 2)}% vs median {len(ser) - 1} hari "
                             f"sebelumnya {_f(med, 2)}% ({'+' if chg >= 0 else ''}{_f(chg)}%).")
    # BGP
    if named or re.search(r"\bbgp\b|rpki|routing|hijack", q):
        for o in ops:
            b = (d.get("bgp") or {}).get(o[1])
            if b and b.get("routes_total"):
                fakta.append(f"BGP {_label(d, o[1])}: {b['routes_total']} route, {_f((b.get('routes_valid') or 0) / b['routes_total'] * 100)}% "
                             f"valid RPKI, {b.get('routes_invalid') or 0} invalid.")
    return {"alat": "internet_operator", "fakta": fakta, "sumber": "Cloudflare Radar (CC BY-NC 4.0)",
            "snapshot": _wib(d["generated_at"]), "kecepatan": tabel,
            "catatan": "Dilihat dari luar jaringan operator: trafik yang melewati Cloudflare (dinormalisasi, bukan volume "
                       "absolut) dan speed test sukarela pengguna; bukan KPI jaringan internal operator.", "_focus": place}


# ---- sebaran_sel (OpenCelliD)
def tool_sebaran_sel(ch, a: dict) -> dict:
    c = _snap("cells_id.json", ttl_s=6 * 3600)
    kab = c.get("kab") or []
    q = a.get("_q", "")
    place = resolve_place(a.get("lokasi", ""))
    named = [o for o in _operators(q) if o[3]]
    op = named[0][3] if named else None
    val = (lambda k: k["op"].get(op, 0)) if op else (lambda k: k["total"])
    who = f" {op}" if op else ""
    fakta = []
    if any(not o[3] for o in _operators(q)):
        fakta.append("Telkom Indonesia/IndiHome adalah jaringan tetap, tidak ada di data sel seluler OpenCelliD.")

    def mix(ks: list) -> str:
        tot = sum(k["total"] for k in ks)
        if not tot:
            return ""
        per_op: dict[str, int] = {}
        r4 = sum(k["radio"].get("4G", 0) + k["radio"].get("5G", 0) for k in ks)
        for k in ks:
            for o, n in k["op"].items():
                per_op[o] = per_op.get(o, 0) + n
        top = ", ".join(f"{o} {_n(n)}" for o, n in sorted(per_op.items(), key=lambda x: -x[1]) if o != "Lainnya")
        rec = sum(k["recent"] for k in ks)
        return f"Per operator: {top}. Porsi 4G/5G {_f(r4 / tot * 100, 0)}%; {_f(rec / tot * 100, 0)}% sel diperbarui dalam 12 bulan terakhir."

    if place and place["level"] == 2:
        k = next((k for k in kab if k["k"] == place["kode"]), None)
        if not k:
            fakta.append(f"{place['nama']} tidak ada di data sebaran sel.")
        else:
            rank = sorted((val(x) for x in kab), reverse=True).index(val(k)) + 1
            fakta.append(f"{k['nama']} ({k['prov']}): {_n(val(k))} sel{who} tercatat di OpenCelliD, peringkat {rank} dari {len(kab)} kab/kota"
                         + (f"; {_f(val(k) / k['pend'] * 1e5)} sel per 100 ribu penduduk." if k.get("pend") else "."))
            if not op and k["total"]:
                fakta.append(mix([k]))
            if k.get("approx"):
                fakta.append(f"Batas wilayah {k['nama']} di data sumber tidak akurat, jadi dipakai batas perkiraan (lingkaran seluas wilayah resmi).")
    elif place:
        ks = [k for k in kab if k.get("prov_k") == place["prov_kode"]]
        prov: dict[str, int] = {}
        for k in kab:
            prov[k["prov_k"]] = prov.get(k["prov_k"], 0) + val(k)
        n = prov.get(place["prov_kode"], 0)
        rank = sorted(prov.values(), reverse=True).index(n) + 1 if prov else 0
        pend = sum(k.get("pend") or 0 for k in ks)
        fakta.append(f"Provinsi {place['prov_nama']}: {_n(n)} sel{who} tercatat di OpenCelliD di {len(ks)} kab/kota, peringkat {rank} "
                     f"dari {len(prov)} provinsi" + (f"; {_f(n / pend * 1e5)} sel per 100 ribu penduduk." if pend else "."))
        top = sorted(ks, key=lambda k: -val(k))
        if top and val(top[0]):
            fakta.append("Kab/kota dengan sel terbanyak: " + ", ".join(f"{k['nama']} ({_n(val(k))})" for k in top[:3]) + ".")
        kosong = [k for k in ks if not val(k)]
        if kosong:
            fakta.append(f"{len(kosong)} kab/kota di provinsi ini belum punya data sel{who} sama sekali.")
        if not op and n:
            fakta.append(mix(ks))
    else:
        tot = c.get("cells_indonesia") or sum(c.get("by_op", {}).values())
        fakta.append(f"OpenCelliD mencatat {_n(c['by_op'].get(op, 0) if op else tot)} sel seluler{who} di Indonesia "
                     f"(data {c['generated_at'][:10]}).")
        if not op:
            fakta.append("Per operator: " + ", ".join(f"{o} {_n(n)}" for o, n in sorted(c["by_op"].items(), key=lambda x: -x[1])
                                                       if o != "Lainnya") + ".")
            fakta.append("Per teknologi: " + ", ".join(f"{r} {_n(n)}" for r, n in sorted(c["by_radio"].items(), key=lambda x: -x[1])) + ".")
        top = sorted(kab, key=lambda k: -val(k))[:5]
        fakta.append("Kab/kota dengan sel terbanyak: " + ", ".join(f"{k['nama']} ({_n(val(k))})" for k in top) + ".")
        fakta.append(f"{sum(1 for k in kab if not val(k))} dari {len(kab)} kab/kota belum punya data sel{who}.")
    return {"alat": "sebaran_sel", "fakta": [f for f in fakta if f], "sumber": "OpenCelliD (CC BY-SA 4.0)",
            "catatan": "OpenCelliD adalah data crowdsourced (dikumpulkan aplikasi/relawan), bukan jumlah BTS resmi operator; "
                       "banyak daerah tercatat jauh lebih sedikit dari kenyataan.", "_focus": place}


TOOL_FUNCS = {"gempa": tool_gempa, "titik_panas": tool_titik_panas, "kualitas_udara": tool_kualitas_udara,
              "harga_pangan": tool_harga_pangan, "berita": tool_berita, "kesehatan_pipeline": tool_kesehatan,
              "cuaca": tool_cuaca, "internet_outage": tool_internet_outage, "internet_operator": tool_internet_operator,
              "sebaran_sel": tool_sebaran_sel}


# ---------------------------------------------------------------- orchestration
def _chat(client: httpx.Client, system: str, user: str, schema: dict | None, temperature: float) -> str:
    body = {"model": LLM_MODEL, "stream": False, "options": {"temperature": temperature, "num_ctx": 4096},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if schema:
        body["format"] = schema
    r = client.post(f"{OLLAMA_URL}/api/chat", json=body)
    r.raise_for_status()
    return r.json()["message"]["content"]


def ask(ch, question: str, client: httpx.Client | None = None, context: str = "") -> dict:
    t0 = time.monotonic()
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(10, read=120))
    try:
        try:
            llm_plan = json.loads(_chat(client, ROUTER_PROMPT, question, ROUTER_SCHEMA, 0))
        except (ValueError, httpx.HTTPError):
            llm_plan = {"alat": []}
        rules = rule_route(question)
        llm_tools = [t for t in llm_plan.get("alat", []) if t in TOOL_FUNCS]
        followup = False
        if context and not rules["alat"] and (not llm_tools or is_followup(question)):
            # pertanyaan lanjutan ("kalau di Riau?"): alat & topik dari pertanyaan sebelumnya,
            # lokasi/waktu dari pertanyaan sekarang bila disebut
            prev = rule_route(context)
            if prev["alat"]:
                followup = True
                keep = {k: rules[k] for k in ("lokasi", "komoditas") if rules[k]}
                if rules["_explicit"]["hari"]:
                    keep["hari"] = rules["hari"]
                rules = {**prev, **keep, "_explicit": {**prev["_explicit"], "hari": rules["_explicit"]["hari"] or prev["_explicit"]["hari"]}}
        if followup:
            llm_tools = []                    # "kalau di Jawa Barat?": alat ikut pertanyaan sebelumnya, bukan tebakan LLM
        tools = list(dict.fromkeys(llm_tools + rules["alat"]))[:3]      # LLM dulu, aturan melengkapi
        if "sebaran_sel" in tools and "internet_operator" in tools and not _kw_hit(question.lower(), NET_GENERIC):
            tools.remove("internet_operator")  # "BTS Telkomsel di X": nama operator saja bukan pertanyaan trafik/kecepatan
        explicit = rules.pop("_explicit")
        dropped = [k for k in ("lokasi", "komoditas", "kata_kunci")
                   if llm_plan.get(k) and not grounded(question, str(llm_plan[k]))]
        for k in dropped:                     # parameter halusinasi (tidak ada di pertanyaan) -> buang
            llm_plan[k] = ""
        params = {k: (rules[k] if explicit.get(k) or llm_plan.get(k) in (None, "", 0) else llm_plan[k])
                  for k in ("lokasi", "hari", "min_magnitudo", "komoditas", "topik", "kata_kunci")}
        calls = [{"nama": t, **params} for t in tools]
        for c in calls:
            c["_q"] = (f"{context} {question}" if followup else question).lower()   # operator/"besok" dari pertanyaan sebelumnya
            c["_hari_explicit"] = bool(explicit.get("hari"))
        router_debug = {"llm": llm_plan, "aturan": rules, "parameter_llm_dibuang": dropped, "lanjutan": followup}
        results, sources, focus = [], [], None
        for c in calls:
            try:
                res = TOOL_FUNCS[c["nama"]](ch, c)
            except Exception as exc:  # noqa: BLE001 - satu alat gagal tidak menggagalkan jawaban
                res = {"alat": c["nama"], "error": f"{type(exc).__name__}"}
            f = res.pop("_focus", None)
            focus = focus or (f and {"lat": f["lat"], "lng": f["lng"], "zoom": 7 if f["level"] == 1 else 9,
                                      "nama": f["nama"]})
            if c.get("lokasi") and res.get("alat") != "kesehatan_pipeline" and f is None and c["lokasi"].strip():
                res["catatan_lokasi"] = f"Lokasi '{c['lokasi']}' tidak dikenali sebagai wilayah Indonesia; filter lokasi tidak dipakai."
            sources += [{"judul": b["judul"], "link": b["link"]} for b in res.get("berita", [])]
            results.append(res)
        if not results:
            answer = ("Maaf, pertanyaan itu di luar cakupan data platform ini. Saya bisa menjawab tentang gempa, "
                      "titik panas, kualitas udara, harga pangan, prakiraan cuaca, gangguan dan kecepatan internet per operator, "
                      "sebaran sel/BTS seluler, berita bencana/cuaca/pangan, dan status pipeline data.")
        else:
            data = json.dumps(results, ensure_ascii=False, default=str)[:MAX_DATA_CHARS * len(results)]
            answer = _chat(client, ANSWER_PROMPT, (f"PERTANYAAN SEBELUMNYA: {context}\n" if followup else "") + f"PERTANYAAN: {question}\n\nDATA:\n{data}", None, 0).strip()
        return {"answer": answer, "tools": [{"nama": c["nama"], "parameter": {k: v for k, v in c.items()
                                              if not k.startswith("_") and k != "nama" and v not in ("", 0, None)}} for c in calls],
                "facts": [f for r in results for f in r.get("fakta", [])],
                "data": results, "sources": sources[:8], "focus": focus, "model": LLM_MODEL, "router": router_debug,
                "ms": int((time.monotonic() - t0) * 1000)}
    finally:
        if own:
            client.close()
