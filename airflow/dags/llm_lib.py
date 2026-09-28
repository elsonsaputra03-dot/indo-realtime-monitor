"""
Helper Fase 4 (bukan DAG): enrichment berita dengan LLM lokal (Ollama) + geotagging ke wilayah.

Alur per berita:
  1. LLM (JSON terstruktur, temperature 0): topik, ringkasan 1 kalimat, daftar lokasi, lokasi utama.
  2. Resolver deterministik: cocokkan nama lokasi ke gazetteer (38 provinsi + 514 kab/kota).
     LLM hanya mengekstrak teks; koordinat SELALU dari gazetteer, bukan dari LLM (anti-halusinasi).
  3. Fallback rule-based bila LLM tidak menyebut lokasi yang bisa di-resolve.

CLI evaluasi (di container airflow):
  python /opt/airflow/dags/llm_lib.py --eval 15 [--model qwen2.5:3b]
"""
import csv
import json
import os
import re
import time
from functools import lru_cache

import httpx

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:3b")
GAZETTEER = os.getenv("GAZETTEER_CSV", "/opt/airflow/reference/wilayah_indonesia.csv")

TOPICS = ["gempa", "banjir_longsor", "kebakaran", "gunung_api", "cuaca", "kualitas_udara", "pangan", "lainnya"]

SYSTEM_PROMPT = """Kamu adalah asisten ekstraksi informasi untuk berita Indonesia.
Balas HANYA dengan JSON sesuai skema. Aturan:
- topik: pilih SEMUA yang relevan dari daftar: gempa, banjir_longsor, kebakaran, gunung_api, cuaca, kualitas_udara, pangan, lainnya.
  gempa = gempa bumi/tsunami, termasuk mitigasi dan kesiapsiagaan gempa.
  banjir_longsor = banjir, banjir bandang, rob, tanah longsor.
  kebakaran = kebakaran hutan/lahan (karhutla), termasuk kebijakan/pencegahannya; BUKAN kebakaran rumah/gedung.
  gunung_api = erupsi, aktivitas vulkanik, gas vulkanik, status gunung api.
  cuaca = hujan deras, angin kencang, cuaca ekstrem, kekeringan, gelombang tinggi, musim hujan/kemarau.
  kualitas_udara = polusi udara, kabut asap, ISPA. pangan = harga/stok bahan pangan.
  Pakai "lainnya" HANYA jika tidak ada satu pun topik di atas yang relevan.
- ringkasan: satu kalimat bahasa Indonesia, maksimal 25 kata, hanya berdasarkan teks yang diberikan.
- lokasi: semua nama tempat DI INDONESIA yang disebut di teks (kabupaten, kota, provinsi, kecamatan, gunung),
  tulis persis seperti di teks. Kosongkan jika tidak ada. Jangan menebak lokasi yang tidak disebut.
- lokasi_utama: tempat kejadian utama berita (kabupaten/kota/provinsi) jika disebut, selain itu string kosong."""

SCHEMA = {
    "type": "object",
    "properties": {
        "topik": {"type": "array", "items": {"type": "string", "enum": TOPICS}},
        "ringkasan": {"type": "string"},
        "lokasi": {"type": "array", "items": {"type": "string"}},
        "lokasi_utama": {"type": "string"},
    },
    "required": ["topik", "ringkasan", "lokasi", "lokasi_utama"],
}

# Singkatan umum di media Indonesia -> nama resmi (lowercase)
ALIASES = {
    # provinsi
    "jakarta": "daerah khusus ibukota jakarta", "dki jakarta": "daerah khusus ibukota jakarta",
    "dki": "daerah khusus ibukota jakarta", "jabar": "jawa barat", "jateng": "jawa tengah",
    "jatim": "jawa timur", "diy": "daerah istimewa yogyakarta", "yogyakarta": "daerah istimewa yogyakarta",
    "jogja": "daerah istimewa yogyakarta", "sumut": "sumatera utara", "sumbar": "sumatera barat",
    "sumsel": "sumatera selatan", "kalbar": "kalimantan barat", "kalteng": "kalimantan tengah",
    "kalsel": "kalimantan selatan", "kaltim": "kalimantan timur", "kaltara": "kalimantan utara",
    "sulut": "sulawesi utara", "sulteng": "sulawesi tengah", "sulsel": "sulawesi selatan",
    "sultra": "sulawesi tenggara", "sulbar": "sulawesi barat", "ntb": "nusa tenggara barat",
    "ntt": "nusa tenggara timur", "babel": "kepulauan bangka belitung", "bangka belitung": "kepulauan bangka belitung",
    "kepri": "kepulauan riau", "kep riau": "kepulauan riau", "kep bangka belitung": "kepulauan bangka belitung",
    "di yogyakarta": "daerah istimewa yogyakarta", "d i yogyakarta": "daerah istimewa yogyakarta",
    "malut": "maluku utara", "papua barat daya": "papua barat daya",
    # kabupaten (singkatan populer)
    "palangka raya": "kota palangkaraya",
    "kotim": "kotawaringin timur", "kobar": "kotawaringin barat", "kukar": "kutai kartanegara",
    "kutim": "kutai timur", "kubar": "kutai barat", "oki": "ogan komering ilir", "oku": "ogan komering ulu",
    "muba": "musi banyuasin", "mura": "musi rawas", "pali": "penukal abab lematang ilir",
    "tanjabtim": "tanjung jabung timur", "tanjabbar": "tanjung jabung barat", "inhu": "indragiri hulu",
    "inhil": "indragiri hilir", "kuansing": "kuantan singingi", "rohil": "rokan hilir", "rohul": "rokan hulu",
    "jaksel": "kota jakarta selatan", "jaktim": "kota jakarta timur", "jakbar": "kota jakarta barat",
    "jakut": "kota jakarta utara", "jakpus": "kota jakarta pusat",
}
# Gunung (api) populer -> kabupaten/kota lokasi utama. Gunung yang melintasi beberapa wilayah
# dipetakan ke satu wilayah representatif dan ditandai ambigu.
MOUNTAINS = {
    "papandayan": ("kabupaten garut", False), "guntur": ("kabupaten garut", False),
    "galunggung": ("kabupaten tasikmalaya", False), "ciremai": ("kabupaten kuningan", True),
    "gede": ("kabupaten cianjur", True), "pangrango": ("kabupaten cianjur", True), "salak": ("kabupaten bogor", True),
    "tangkuban parahu": ("kabupaten bandung barat", True), "tangkuban perahu": ("kabupaten bandung barat", True),
    "anak krakatau": ("kabupaten lampung selatan", False), "krakatau": ("kabupaten lampung selatan", False),
    "merapi": ("kabupaten sleman", True), "semeru": ("kabupaten lumajang", False), "bromo": ("kabupaten probolinggo", True),
    "kelud": ("kabupaten kediri", True), "ijen": ("kabupaten banyuwangi", True), "raung": ("kabupaten banyuwangi", True),
    "lawu": ("kabupaten karanganyar", True), "slamet": ("kabupaten purbalingga", True), "dieng": ("kabupaten banjarnegara", True),
    "agung": ("kabupaten karangasem", False), "batur": ("kabupaten bangli", False),
    "rinjani": ("kabupaten lombok timur", True), "tambora": ("kabupaten dompu", True),
    "sinabung": ("kabupaten karo", False), "sibayak": ("kabupaten karo", False), "marapi": ("kabupaten agam", True),
    "kerinci": ("kabupaten kerinci", True), "dempo": ("kota pagar alam", False), "talang": ("kabupaten solok", False),
    "seulawah agam": ("kabupaten aceh besar", False),
    "lewotobi": ("kabupaten flores timur", False), "lewotobi laki laki": ("kabupaten flores timur", False),
    "lewotolok": ("kabupaten lembata", False), "ile lewotolok": ("kabupaten lembata", False),
    "kelimutu": ("kabupaten ende", False), "egon": ("kabupaten sikka", False),
    "ibu": ("kabupaten halmahera barat", False), "dukono": ("kabupaten halmahera utara", False),
    "gamalama": ("kota ternate", False), "lokon": ("kota tomohon", False), "soputan": ("kabupaten minahasa selatan", True),
    "karangetang": ("kabupaten kep siau tagulandang biaro", False),
    "ruang": ("kabupaten kep siau tagulandang biaro", False), "awu": ("kabupaten kepulauan sangihe", False),
}

# Nama kab/kota yang juga kata umum: tidak dicari lewat rule-based scan tanpa awalan "Kabupaten/Kota"
AMBIGUOUS_WORDS = {"batu", "bone", "pati", "buru", "agam", "banjar", "barat", "timur", "tengah", "selatan",
                   "utara", "seram", "tanah laut", "lebak", "bangli", "kota", "siak", "kaur", "maybrat"}

_PREFIX = re.compile(r"^(provinsi|prov\.?|kabupaten|kab\.?|kota administrasi|kota adm\.?|kota|kecamatan|kec\.?)\s+")


def norm(s: str) -> str:
    s = s.lower().replace("’", "'").strip()
    s = re.sub(r"[^\w\s']", " ", s)
    return re.sub(r"\s+", " ", s).strip()


@lru_cache(maxsize=1)
def gazetteer() -> dict:
    rows = list(csv.DictReader(open(GAZETTEER, encoding="utf-8")))
    by_name: dict[str, list[dict]] = {}
    for r in rows:
        r["level"] = int(r["level"])
        r["lat"], r["lng"] = float(r["lat"]), float(r["lng"])
        keys = {norm(r["nama"]), norm(r["nama_pendek"])}
        if r["level"] == 2:
            keys.add(("kota " if r["jenis"] == "kota" else "kabupaten ") + norm(r["nama_pendek"]))
        for k in keys | {k.replace(" ", "") for k in keys}:      # 'palangka raya' == 'palangkaraya'
            by_name.setdefault(k, []).append(r)
    provinces = {r["prov_kode"]: r for r in rows if r["level"] == 1}
    return {"rows": rows, "by_name": by_name, "provinces": provinces}


def _candidates(name: str) -> tuple[list[dict], str | None]:
    """Nama lokasi -> kandidat baris gazetteer + preferensi jenis ('kota'/'kabupaten'/None)."""
    g = gazetteer()
    n = norm(name)
    prefer = "kota" if n.startswith("kota ") else "kabupaten" if n.startswith(("kabupaten ", "kab ")) else None
    bare = _PREFIX.sub("", n)
    peak = re.sub(r"^(gunung api|gunung|gn)\s+", "", n)
    if peak != n or n in MOUNTAINS:
        target, _amb = MOUNTAINS.get(peak, (None, False))
        if target and target in g["by_name"]:
            return g["by_name"][target], "kota" if target.startswith("kota ") else "kabupaten"
    for key in (n, ALIASES.get(n, ""), bare, ALIASES.get(bare, ""), n.replace(" ", ""), bare.replace(" ", "")):
        if key and key in g["by_name"]:
            return g["by_name"][key], prefer
    return [], prefer


def resolve(names: list[str], context_text: str = "", primary: str = "") -> dict | None:
    """Pilih satu wilayah terbaik. `primary` (lokasi utama dari LLM) menang bila bisa di-resolve;
    selain itu pilih yang paling spesifik dari `names` (urutan = prioritas). None bila tidak cocok."""
    if primary:
        hit = resolve([primary], context_text)
        if hit:
            return hit
    g = gazetteer()
    ctx = norm(context_text)
    mentioned_prov = {r["prov_kode"] for r in g["provinces"].values()
                      if norm(r["nama"]) in ctx or any(a in ctx.split() and v == norm(r["nama"])
                                                       for a, v in ALIASES.items() if " " not in a)}
    best = None
    for idx, name in enumerate(names):
        cands, prefer = _candidates(name)
        if not cands:
            continue
        if prefer:
            cands = [c for c in cands if c["level"] == 1 or c["jenis"] == prefer] or cands
        in_ctx = [c for c in cands if c["prov_kode"] in mentioned_prov]
        pool = in_ctx or cands
        same_name_prov = [c for c in pool if c["level"] == 1 and norm(c["nama"]) == _PREFIX.sub("", norm(name))]
        if same_name_prov and not prefer:
            # "Jambi", "Bengkulu", "Gorontalo" tanpa awalan "Kota" -> provinsi (media menulis "Kota Jambi" utk kota)
            pool = same_name_prov + [c for c in pool if c not in same_name_prov]
        else:
            pool = sorted(pool, key=lambda c: (-c["level"], c["jenis"] != "kabupaten"))   # kab/kota > provinsi
        pick = pool[0]
        ambiguous = len({c["kode"] for c in pool if c["level"] == pick["level"]}) > 1
        cand = {"kode": pick["kode"], "nama": pick["nama"], "level": pick["level"], "lat": pick["lat"],
                "lng": pick["lng"], "prov_kode": pick["prov_kode"],
                "prov_nama": g["provinces"].get(pick["prov_kode"], {}).get("nama", pick["prov_nama"]),
                "matched": name, "ambiguous": ambiguous, "rank": idx}
        # ambil yang paling spesifik (kab/kota) dengan prioritas urutan; provinsi hanya bila tak ada lain
        if best is None or (cand["level"] > best["level"]):
            best = cand
        if best["level"] == 2 and not ambiguous:
            break
    return best


def rule_scan(text: str) -> list[str]:
    """Fallback tanpa LLM: cari nama wilayah di teks (case-sensitive, kapitalisasi awal)."""
    g = gazetteer()
    found = []
    for r in g["rows"]:
        short = r["nama_pendek"]
        if norm(short) in AMBIGUOUS_WORDS or len(short) < 4:
            patterns = [rf"\b(Kabupaten|Kab\.|Kota)\s+{re.escape(short)}\b"]
        else:
            patterns = [rf"\b{re.escape(short)}\b"]
        if any(re.search(p, text) for p in patterns):
            if r["level"] == 2:   # "Kota X" vs "Kabupaten X": ikuti awalan yang tertulis
                has_kota = re.search(rf"\bKota\s+{re.escape(short)}\b", text)
                has_kab = re.search(rf"\b(Kabupaten|Kab\.)\s+{re.escape(short)}\b", text)
                if (r["jenis"] == "kabupaten" and has_kota and not has_kab) or \
                   (r["jenis"] == "kota" and has_kab and not has_kota):
                    continue
            found.append(r["nama"])
    for a, v in ALIASES.items():
        if re.search(rf"\b{re.escape(a)}\b", text, flags=re.I) and len(a) >= 4:
            found.append(v)
    for m in re.finditer(r"\b(?:Gunung|Gn\.)\s+([A-Z][\w-]+)(?:\s+([A-Z][\w-]+))?", text):
        two = f"{m.group(1)} {m.group(2)}" if m.group(2) else None
        found.append("gunung " + (two if two and norm(two) in MOUNTAINS else m.group(1)))
    return found


def call_llm(client: httpx.Client, title: str, summary: str, model: str = LLM_MODEL) -> dict:
    text = f"Judul: {title}\nRingkasan: {summary or '-'}"
    r = client.post(f"{OLLAMA_URL}/api/chat", json={
        "model": model, "stream": False, "format": SCHEMA,
        "options": {"temperature": 0, "num_ctx": 2048},
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": text}],
    })
    r.raise_for_status()
    data = r.json()
    out = json.loads(data["message"]["content"])
    out["topik"] = [t for t in out.get("topik", []) if t in TOPICS] or ["lainnya"]
    out["ringkasan"] = str(out.get("ringkasan", "")).strip()[:300]
    out["lokasi"] = [str(x).strip() for x in out.get("lokasi", []) if str(x).strip()][:10]
    out["lokasi_utama"] = str(out.get("lokasi_utama", "")).strip()
    out["_ms"] = int(data.get("total_duration", 0) / 1e6)
    return out


def enrich(client: httpx.Client, item: dict, model: str = LLM_MODEL) -> dict:
    """item: news row (news_id, title, summary, published_at). Tidak pernah raise."""
    t0 = time.monotonic()
    text = f"{item['title']}. {item.get('summary', '')}"
    base = {"news_id": item["news_id"], "model": model, "published_at": item["published_at"]}
    try:
        llm = call_llm(client, item["title"], item.get("summary", ""), model)
        names = ([llm["lokasi_utama"]] if llm["lokasi_utama"] else []) + llm["lokasi"]
        kw = [t for t in item.get("topics", []) if t in TOPICS]
        merged = sorted((set(llm["topik"]) - {"lainnya"}) | set(kw))
        llm["topik"] = merged or ["lainnya"]
        geo, method = resolve(llm["lokasi"], text, primary=llm["lokasi_utama"]), "llm"
        if geo is None:
            geo, method = resolve(rule_scan(text), text), "rule"
        status, err = "ok", ""
    except Exception as exc:  # noqa: BLE001
        llm = {"topik": [], "ringkasan": "", "lokasi": [], "lokasi_utama": ""}
        geo, method = resolve(rule_scan(text), text), "rule"
        status, err = "error", f"{type(exc).__name__}: {exc}"[:300]
    return {
        **base,
        "status": status, "error": err,
        "topics_llm": llm["topik"], "summary_llm": llm["ringkasan"],
        "locations_raw": llm["lokasi"], "location_main": llm["lokasi_utama"],
        "geo_method": method if geo else "none",
        "kode_wilayah": geo["kode"] if geo else "", "nama_wilayah": geo["nama"] if geo else "",
        "level_wilayah": geo["level"] if geo else 0,
        "prov_kode": geo["prov_kode"] if geo else "", "prov_nama": geo["prov_nama"] if geo else "",
        "lat": geo["lat"] if geo else 0.0, "lng": geo["lng"] if geo else 0.0,
        "geo_ambiguous": bool(geo and geo["ambiguous"]),
        "latency_ms": int((time.monotonic() - t0) * 1000),
    }


def ollama_ready(client: httpx.Client, model: str = LLM_MODEL) -> tuple[bool, str]:
    try:
        tags = client.get(f"{OLLAMA_URL}/api/tags", timeout=10).json().get("models", [])
    except Exception as exc:  # noqa: BLE001
        return False, f"Ollama tidak bisa dihubungi: {type(exc).__name__}"
    names = {m.get("name", "") for m in tags} | {m.get("model", "") for m in tags}
    if model not in names and f"{model}:latest" not in names:
        return False, f"model {model} belum di-pull (make llm-pull)"
    return True, ""


if __name__ == "__main__":   # evaluasi manual terhadap berita terbaru
    import argparse
    import clickhouse_connect

    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", type=int, default=10)
    ap.add_argument("--model", default=LLM_MODEL)
    a = ap.parse_args()
    ch = clickhouse_connect.get_client(host=os.getenv("CLICKHOUSE_HOST", "clickhouse"),
                                       username=os.getenv("CLICKHOUSE_USER"), password=os.getenv("CLICKHOUSE_PASSWORD"),
                                       database=os.getenv("CLICKHOUSE_DB", "irm"))
    rows = ch.query(f"SELECT news_id, title, summary, toString(published_at), topics FROM news FINAL "
                    f"ORDER BY published_at DESC LIMIT {int(a.eval)}").result_rows
    with httpx.Client(timeout=httpx.Timeout(20, read=180)) as c:
        ok, msg = ollama_ready(c, a.model)
        if not ok:
            raise SystemExit(msg)
        for nid, title, summary, pub, topics in rows:
            e = enrich(c, {"news_id": nid, "title": title, "summary": summary, "published_at": pub,
                           "topics": list(topics)}, a.model)
            print(f"\n• {title[:110]}")
            print(f"  topik={e['topics_llm']} lokasi={e['locations_raw']} utama='{e['location_main']}'")
            print(f"  geo={e['nama_wilayah'] or '-'} ({e['prov_nama'] or '-'}) via {e['geo_method']}"
                  f"{' [ambigu]' if e['geo_ambiguous'] else ''}  {e['latency_ms']} ms  {e['error']}")
            print(f"  ringkasan: {e['summary_llm']}")
