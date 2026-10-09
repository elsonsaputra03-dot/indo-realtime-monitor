"""Indeks kecil untuk "Ask the Data" versi publik (Cloudflare Worker, tanpa ClickHouse dan tanpa shapely).

Worker tidak bisa menghitung titik-dalam-poligon dengan cepat, jadi pekerjaan geospasial dilakukan di sini (GitHub Actions,
tiap jam, setelah snapshot):
  ask_index.json     titik panas per kab/kota per hari (jumlah + FRP maks) dan wilayah tiap gempa (kab/kota yang memuat
                     episentrum + provinsi dalam jarak ±50 km), memakai batas wilayah yang sama dengan indeks risiko.
  ask_gazetteer.json nama wilayah -> kode (gazetteer + alias + gunung api), dipakai Worker untuk mengenali lokasi di
                     pertanyaan. Lokasi selalu dari gazetteer, tidak pernah dari model.
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "airflow", "dags"))
sys.path.insert(0, os.path.dirname(__file__))

NEAR_DEG = 0.45          # ±50 km dari batas provinsi untuk gempa (sama dengan filter lokasi di app/api/ask.py)


def _load(d: str, name: str, default):
    p = os.path.join(d, name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default


def build_index(data_dir: str, boundary: str, gazetteer: str) -> dict:
    import shapely
    from pathlib import Path
    from shapely import STRtree
    from opencellid_snapshot import qc_boundaries      # QC batas yang sama dengan OpenCelliD/OSM (kota enklave ikut benar)
    kodes, geoms, _approx = qc_boundaries(Path(boundary), Path(gazetteer))
    regions = [{"kode": k, "prov_kode": k.split(".")[0], "area": g.area} for k, g in zip(kodes, geoms)]
    tree = STRtree(geoms)

    def pick(idx) -> int:          # titik di beberapa wilayah (lingkaran perkiraan tumpang tindih): wilayah terkecil
        return min((int(j) for j in idx), key=lambda j: regions[j]["area"])

    pts = _load(data_dir, "hotspots.json", {"points": []})["points"]
    days: dict[str, dict] = defaultdict(lambda: {"kab": defaultdict(lambda: [0, 0.0]), "outside": 0, "total": 0})
    owner = [-1] * len(pts)
    if pts:
        pi, gi = tree.query(shapely.points([(p[1], p[0]) for p in pts]), predicate="intersects")
        for a, b in zip(pi, gi):
            if owner[a] < 0 or regions[int(b)]["area"] < regions[owner[a]]["area"]:
                owner[a] = int(b)
    for i, p in enumerate(pts):
        day = str(p[4])[:10] if len(p) > 4 and p[4] else "?"
        d = days[day]
        d["total"] += 1
        if owner[i] < 0:
            d["outside"] += 1
            continue
        c = d["kab"][regions[owner[i]]["kode"]]
        c[0] += 1
        c[1] = max(c[1], float(p[2] or 0))
    hotspots = {day: {"total": v["total"], "outside": v["outside"],
                      "kab": {k: [n, round(f, 1)] for k, (n, f) in sorted(v["kab"].items())}} for day, v in sorted(days.items())}

    quakes = {}
    for f in _load(data_dir, "earthquakes.json", {"features": []})["features"]:
        lon, lat = f["geometry"]["coordinates"][:2]
        pt = shapely.Point(lon, lat)
        hit = tree.query(pt, predicate="intersects")
        kab = regions[pick(hit)]["kode"] if len(hit) else None
        near = sorted({regions[int(j)]["prov_kode"] for j in tree.query(pt.buffer(NEAR_DEG), predicate="intersects")})
        quakes[f["properties"]["id"]] = {"kab": kab, "near_prov": near}

    return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "note": "Titik panas: confidence nominal/high, dipetakan ke batas kab/kota (poligon yang tidak valid diganti "
                    "batas perkiraan). Gempa: kab/kota episentrum dan provinsi dalam ±50 km.",
            "hotspots": hotspots, "quakes": quakes}


def build_gazetteer() -> dict:
    """Kunci nama (sudah dinormalisasi) -> daftar kode, plus data ringkas tiap wilayah."""
    import llm_lib
    g = llm_lib.gazetteer()
    rows = {r["kode"]: {"k": r["kode"], "lv": r["level"], "j": r["jenis"], "n": r["nama"], "lat": r["lat"], "lng": r["lng"],
                        "pk": r["prov_kode"], "luas": float(r["luas_km2"]) if r.get("luas_km2") else None,
                        "pend": int(float(r["penduduk"])) if r.get("penduduk") else None} for r in g["rows"]}
    keys: dict[str, list[str]] = {}
    for key, cands in g["by_name"].items():
        keys[key] = sorted({c["kode"] for c in cands})
    for alias, target in llm_lib.ALIASES.items():
        if target in g["by_name"]:
            keys.setdefault(llm_lib.norm(alias), sorted({c["kode"] for c in g["by_name"][target]}))
    for peak, (target, _amb) in llm_lib.MOUNTAINS.items():
        if target in g["by_name"]:
            codes = sorted({c["kode"] for c in g["by_name"][target]})
            keys.setdefault("gunung " + peak, codes)
            if len(peak) >= 5 and peak not in llm_lib.AMBIGUOUS_WORDS:
                keys.setdefault(peak, codes)
    return {"rows": rows, "keys": keys, "ambiguous": sorted(llm_lib.AMBIGUOUS_WORDS)}


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "site/data"
    gaz_csv = os.environ.get("GAZETTEER_CSV", "reference/wilayah_indonesia.csv")
    os.environ.setdefault("GAZETTEER_CSV", gaz_csv)
    idx = build_index(out, "reference/batas_kabkota.geojson", gaz_csv)
    json.dump(idx, open(os.path.join(out, "ask_index.json"), "w", encoding="utf-8"), separators=(",", ":"))
    json.dump(build_gazetteer(), open(os.path.join(out, "ask_gazetteer.json"), "w", encoding="utf-8"),
              separators=(",", ":"), ensure_ascii=False)
    n = sum(v["total"] for v in idx["hotspots"].values())
    print(f"ask_index: {n} titik panas di {len(idx['hotspots'])} hari, {len(idx['quakes'])} gempa")
    return 0


if __name__ == "__main__":
    sys.exit(main())
