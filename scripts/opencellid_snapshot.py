"""Sebaran sel seluler Indonesia dari OpenCelliD (data terbuka, CC BY-SA 4.0), diringkas per kabupaten/kota.

Isi output (site/data/cells_id.json): jumlah sel per kab/kota, per operator (MNC), per teknologi (GSM/UMTS/LTE/NR),
kepadatan per luas wilayah dan per penduduk, serta porsi sel yang masih terlihat dalam 12 bulan terakhir.
Posisi sel di OpenCelliD adalah PERKIRAAN dari pengukuran crowdsourcing, bukan koordinat BTS resmi operator,
jadi data hanya ditampilkan teragregasi per wilayah, tidak per titik.

Batas & gazetteer wilayah: reference/ (cahyadsn/wilayah, MIT).
Token: env OPENCELLID_KEY (akun gratis di opencellid.org). Tanpa token atau unduhan gagal, file lama dipertahankan.

Pemakaian:  OPENCELLID_KEY=... python scripts/opencellid_snapshot.py --out site/data
            python scripts/opencellid_snapshot.py --csv 510.csv.gz --out site/data      # dari file lokal
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import os
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

URLS = ["https://opencellid.org/ocid/downloads?token={key}&type=mcc&file=510.csv.gz",
        "https://download.unwiredlabs.com/ocid/downloads?token={key}&type=mcc&file=510.csv.gz"]
# MNC Indonesia (MCC 510) menurut penomoran publik; MNC lain dilaporkan sebagai "Lainnya"
MNC = {"10": "Telkomsel", "01": "Indosat", "21": "Indosat", "89": "Tri (IOH)", "11": "XL Axiata", "08": "XL Axiata",
       "09": "Smartfren", "28": "Smartfren"}
OPS = ["Telkomsel", "Indosat", "Tri (IOH)", "XL Axiata", "Smartfren", "Lainnya"]
RADIO = {"GSM": "2G", "CDMA": "2G", "UMTS": "3G", "LTE": "4G", "NR": "5G"}
ATTRIBUTION = {"source": "OpenCelliD", "url": "https://opencellid.org", "license": "CC BY-SA 4.0",
               "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
               "boundaries": "cahyadsn/wilayah (MIT)"}
COLS = ["radio", "mcc", "net", "area", "cell", "unit", "lon", "lat", "range", "samples", "changeable", "created", "updated", "averageSignal"]


def download(key: str) -> bytes | None:
    for u in URLS:
        try:
            req = urllib.request.Request(u.format(key=key), headers={"User-Agent": "indo-realtime-monitor (portfolio, weekly)"})
            with urllib.request.urlopen(req, timeout=300) as r:
                body = r.read()
            if body[:2] == b"\x1f\x8b":
                return body
            print(f"opencellid: respons bukan gzip dari {u.split('?')[0]}: {body[:200]!r}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"opencellid: unduhan gagal dari {u.split('?')[0]}: {str(e)[:200]}", file=sys.stderr)
        time.sleep(3)
    return None


def rows(gz: bytes):
    with gzip.open(io.BytesIO(gz), "rt", encoding="utf-8", errors="replace", newline="") as f:
        for r in csv.reader(f):
            if not r or r[0] == "radio":
                continue
            if len(r) < 13:
                continue
            yield dict(zip(COLS, r))


def qc_boundaries(boundary: Path, gazetteer: Path) -> tuple[list[str], list, set[str]]:
    """Poligon kab/kota + QC (sama dengan app/api/ask.py): sebagian poligon sumber salah (luas menyimpang >3x dari luas resmi,
    ibu kota >40 km dari poligonnya, atau pusat kota di luar poligon kota itu sendiri, mis. Kota Semarang, Kota Palangkaraya).
    Poligon seperti itu diganti lingkaran perkiraan seluas luas resmi di sekitar ibu kota."""
    import math
    from shapely.geometry import Point, shape
    gaz = {r["kode"]: r for r in csv.DictReader(open(gazetteer, encoding="utf-8"))}
    feats = json.loads(boundary.read_text(encoding="utf-8"))["features"]
    kodes, geoms, approx = [], [], set()
    for f in feats:
        kode = f["properties"].get("kode") or f["properties"].get("k")
        g, row = shape(f["geometry"]).buffer(0), gaz.get(kode, {})
        if row.get("lat"):
            luas = float(row["luas_km2"]) if row.get("luas_km2") else None
            area, cap = g.area * 111.0 ** 2, Point(float(row["lng"]), float(row["lat"]))
            dist = g.distance(cap) * 111.0
            bad = g.is_empty or (luas and not 1 / 3 <= area / luas <= 3) or dist > 40 or (row.get("jenis") == "kota" and dist > 1)
            if bad:
                g = cap.buffer(math.sqrt((luas or max(area, 100.0)) / math.pi) / 111.0, 32)
                approx.add(kode)
        kodes.append(kode); geoms.append(g)
    return kodes, geoms, approx


def simplify_geojson(boundary: Path, gazetteer: Path, dst: Path, tol: float = 0.02) -> None:
    """Salinan batas kab/kota (sudah di-QC) yang lebih ringan untuk peta di browser (cukup untuk peta tematik)."""
    from shapely.geometry import mapping
    kodes, geoms, approx = qc_boundaries(boundary, gazetteer)
    feats = []
    for kode, g in zip(kodes, geoms):
        m = json.loads(json.dumps(mapping(g.simplify(tol, preserve_topology=True))), parse_float=lambda x: round(float(x), 3))
        feats.append({"type": "Feature", "properties": {"k": kode, **({"approx": 1} if kode in approx else {})}, "geometry": m})
    dst.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")), encoding="utf-8")


def aggregate(records, boundary: Path, gazetteer: Path) -> dict:
    import numpy as np
    import shapely


    gaz = {r["kode"]: r for r in csv.DictReader(open(gazetteer, encoding="utf-8"))}
    kodes, geoms, approx = qc_boundaries(boundary, gazetteer)
    tree = shapely.STRtree(geoms)
    areas = np.array([g.area for g in geoms])

    lon, lat, op, radio, upd = [], [], [], [], []
    now = time.time()
    total_rows, skipped = 0, 0
    for r in records:
        total_rows += 1
        try:
            if r["mcc"] != "510":
                skipped += 1; continue
            x, y = float(r["lon"]), float(r["lat"])
        except (ValueError, KeyError):
            skipped += 1; continue
        if not (94 <= x <= 142 and -12 <= y <= 7):
            skipped += 1; continue
        lon.append(x); lat.append(y)
        op.append(MNC.get(r["net"].zfill(2), "Lainnya"))
        radio.append(RADIO.get(r["radio"].upper(), "Lainnya"))
        try:
            upd.append(int(float(r["updated"])))
        except ValueError:
            upd.append(0)
    pts = shapely.points(np.array(lon), np.array(lat))
    pi, gi = tree.query(pts, predicate="within") if len(pts) else (np.array([], int), np.array([], int))
    owner = np.full(len(pts), -1)
    # titik yang masuk >1 wilayah (lingkaran perkiraan tumpang tindih tetangga): wilayah terkecil menang,
    # sehingga kota enklave (mis. Kota Blitar di dalam Kabupaten Blitar) tidak tertelan kabupaten di sekitarnya
    order = np.argsort(-areas[gi], kind="stable")
    owner[pi[order]] = gi[order]
    recent_cut = now - 365 * 86400

    kab = defaultdict(lambda: {"total": 0, "op": Counter(), "radio": Counter(), "recent": 0, "op_radio": Counter()})
    outside = 0
    for i in range(len(pts)):
        if owner[i] < 0:
            outside += 1; continue
        k = kab[kodes[owner[i]]]
        k["total"] += 1; k["op"][op[i]] += 1; k["radio"][radio[i]] += 1; k["op_radio"][f"{op[i]}|{radio[i]}"] += 1
        k["recent"] += upd[i] >= recent_cut

    out_kab = []
    for kode in kodes:
        g = gaz.get(kode, {}); a = kab.get(kode)
        prov = gaz.get(kode.split(".")[0], {})
        out_kab.append({"k": kode, "nama": g.get("nama", kode), "prov": prov.get("nama", ""), "prov_k": kode.split(".")[0],
                        "luas": float(g["luas_km2"]) if g.get("luas_km2") else None,
                        "pend": int(float(g["penduduk"])) if g.get("penduduk") else None,
                        "lat": float(g["lat"]) if g.get("lat") else None, "lng": float(g["lng"]) if g.get("lng") else None,
                        "total": a["total"] if a else 0, "recent": a["recent"] if a else 0,
                        "op": dict(a["op"]) if a else {}, "radio": dict(a["radio"]) if a else {},
                        "op_radio": dict(a["op_radio"]) if a else {}, **({"approx": 1} if kode in approx else {})})
    tot = Counter(); trad = Counter()
    for k in out_kab:
        tot.update(k["op"]); trad.update(k["radio"])
    return {"rows_in_file": total_rows, "cells_indonesia": len(pts), "outside_boundaries": outside, "skipped": skipped,
            "by_op": dict(tot), "by_radio": dict(trad), "approx_boundaries": len(approx), "kab": out_kab}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site/data")
    ap.add_argument("--csv", help="file 510.csv.gz lokal (tanpa unduh)")
    ap.add_argument("--boundary", default="reference/batas_kabkota.geojson")
    ap.add_argument("--gazetteer", default="reference/wilayah_indonesia.csv")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    if a.csv:
        gz = Path(a.csv).read_bytes()
    else:
        key = os.environ.get("OPENCELLID_KEY", "").strip()
        if not key:
            print("opencellid: OPENCELLID_KEY kosong, data lama dipertahankan", file=sys.stderr); return 0
        gz = download(key)
        if gz is None:
            print("opencellid: tidak ada data baru, data lama dipertahankan", file=sys.stderr); return 0
    agg = aggregate(rows(gz), Path(a.boundary), Path(a.gazetteer))
    if not agg["cells_indonesia"]:
        print("opencellid: file tidak berisi sel MCC 510, data lama dipertahankan", file=sys.stderr); return 0
    snap = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "attribution": ATTRIBUTION,
            "ops": OPS, "mnc": MNC, **agg}
    (out / "cells_id.json").write_text(json.dumps(snap, separators=(",", ":")), encoding="utf-8")
    simplify_geojson(Path(a.boundary), Path(a.gazetteer), out / "kabkota_id.geojson")
    print(f"opencellid: {agg['cells_indonesia']:,} sel Indonesia dari {agg['rows_in_file']:,} baris, "
          f"{agg['outside_boundaries']:,} di luar batas, per operator {agg['by_op']}, per teknologi {agg['by_radio']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
