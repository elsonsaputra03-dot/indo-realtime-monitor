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
Aturan: lokasi HANYA diisi jika nama tempat itu tertulis di pertanyaan; jangan menyalin lokasi dari contoh. Pilih 1-3 alat; "tidak_ada" HANYA jika pertanyaan sama sekali tidak terkait gempa, titik panas/kebakaran,
kualitas udara, harga pangan, berita bencana/cuaca/pangan, atau status data. lokasi/komoditas/topik/kata_kunci = "" jika tidak disebut.
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
]
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
    tools = [t for t, kws in RULE_TOOLS if any(k in ql for k in kws)]
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
- Sebut angka, satuan, tanggal/rentang waktu, dan sumber data (mis. BMKG, NASA FIRMS, PIHPS BI).
- Jika DATA kosong atau tidak cukup, katakan terus terang bahwa datanya belum tersedia di platform.
- Jika DATA memuat "catatan", sampaikan keterbatasan itu secara singkat.
- Setiap alat punya daftar "fakta" berisi kalimat yang PASTI benar. Jadikan fakta itu dasar jawaban:
  boleh diparafrasekan dan dirangkai, tetapi angka, nama tempat, dan artinya tidak boleh diubah.
- Jangan menyebut nama alat atau nama field (mis. kesehatan_pipeline, titik_panas).
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
    fc = json.load(open(os.path.join(REFERENCE_DIR, name), encoding="utf-8"))
    props = [f["properties"] for f in fc["features"]]
    geoms = [shape(f["geometry"]) for f in fc["features"]]
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


TOOL_FUNCS = {"gempa": tool_gempa, "titik_panas": tool_titik_panas, "kualitas_udara": tool_kualitas_udara,
              "harga_pangan": tool_harga_pangan, "berita": tool_berita, "kesehatan_pipeline": tool_kesehatan}


# ---------------------------------------------------------------- orchestration
def _chat(client: httpx.Client, system: str, user: str, schema: dict | None, temperature: float) -> str:
    body = {"model": LLM_MODEL, "stream": False, "options": {"temperature": temperature, "num_ctx": 4096},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if schema:
        body["format"] = schema
    r = client.post(f"{OLLAMA_URL}/api/chat", json=body)
    r.raise_for_status()
    return r.json()["message"]["content"]


def ask(ch, question: str, client: httpx.Client | None = None) -> dict:
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
        tools = list(dict.fromkeys(llm_tools + rules["alat"]))[:3]      # LLM dulu, aturan melengkapi
        explicit = rules.pop("_explicit")
        dropped = [k for k in ("lokasi", "komoditas", "kata_kunci")
                   if llm_plan.get(k) and not grounded(question, str(llm_plan[k]))]
        for k in dropped:                     # parameter halusinasi (tidak ada di pertanyaan) -> buang
            llm_plan[k] = ""
        params = {k: (rules[k] if explicit.get(k) or llm_plan.get(k) in (None, "", 0) else llm_plan[k])
                  for k in ("lokasi", "hari", "min_magnitudo", "komoditas", "topik", "kata_kunci")}
        calls = [{"nama": t, **params} for t in tools]
        for c in calls:
            c["_q"] = question.lower()
        router_debug = {"llm": llm_plan, "aturan": rules, "parameter_llm_dibuang": dropped}
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
                      "titik panas, kualitas udara, harga pangan, berita bencana/cuaca/pangan, dan status pipeline data.")
        else:
            data = json.dumps(results, ensure_ascii=False, default=str)[:MAX_DATA_CHARS * len(results)]
            answer = _chat(client, ANSWER_PROMPT, f"PERTANYAAN: {question}\n\nDATA:\n{data}", None, 0).strip()
        return {"answer": answer, "tools": [{"nama": c["nama"], "parameter": {k: v for k, v in c.items()
                                              if k not in ("nama", "_q") and v not in ("", 0, None)}} for c in calls],
                "facts": [f for r in results for f in r.get("fakta", [])],
                "data": results, "sources": sources[:8], "focus": focus, "model": LLM_MODEL, "router": router_debug,
                "ms": int((time.monotonic() - t0) * 1000)}
    finally:
        if own:
            client.close()
