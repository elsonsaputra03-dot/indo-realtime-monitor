"""Menara telekomunikasi Indonesia dari OpenStreetMap (ODbL), diringkas per kabupaten/kota.

Sumber: ekstrak Geofabrik `indonesia-latest.osm.pbf` (diunduh mingguan oleh .github/workflows/osm.yml, bukan Overpass,
supaya tidak membebani server publik). Yang dihitung:
  - man_made=communications_tower, atau
  - man_made=tower/mast yang ditandai telekomunikasi: tower:type=communication, kunci communication:*, atau
    operator/owner/name berisi nama operator seluler atau penyedia menara.
Node dan way (titik tengah) dihitung; batas kab/kota sama dengan OpenCelliD (sudah di-QC).
Kelengkapan OSM tidak merata: angka ini "menara yang tercatat di OSM", bukan jumlah resmi.

Contoh: python scripts/osm_towers_snapshot.py --pbf indonesia-latest.osm.pbf --out site/data
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from opencellid_snapshot import qc_boundaries  # noqa: E402  (QC batas wilayah yang sama)

ATTRIBUTION = {"source": "OpenStreetMap contributors", "url": "https://www.openstreetmap.org/copyright",
               "license": "ODbL 1.0", "license_url": "https://opendatacommons.org/licenses/odbl/1-0/",
               "extract": "Geofabrik (download.geofabrik.de)", "boundaries": "cahyadsn/wilayah (MIT)"}
# label dinormalisasi dari operator/owner/name/brand; urutan penting (yang spesifik dulu)
OWNERS = [
    ("Telkomsel", r"telkomsel|t-sel\b|tsel\b"),
    ("Indosat", r"indosat|\bim3\b|ooredoo|\bioh\b"),
    ("XL Axiata", r"\bxl\b|axiata|\baxis\b|xlsmart"),
    ("Tri (IOH)", r"hutchison|\btri\b|\bthree\b|\b3 indonesia"),
    ("Smartfren", r"smartfren|smart ?telecom|fren\b"),
    ("Telkom Indonesia", r"telkom indonesia|\btelkom\b|indihome|telekomunikasi indonesia"),
    ("Mitratel", r"mitratel|dayamitra"),
    ("Protelindo", r"protelindo|sarana menara"),
    ("Tower Bersama", r"tower bersama|\btbig\b"),
    ("STP", r"solusi tunas|\bstp\b"),
    ("Lainnya", r".+"),
]
OWNER_RE = [(lab, re.compile(rx, re.I)) for lab, rx in OWNERS]
TELCO_HINT = re.compile("|".join(rx for lab, rx in OWNERS if lab != "Lainnya") + r"|\bbts\b|seluler|cellular|telekomunikasi|telecom", re.I)


def owner_of(tags: dict) -> str:
    text = " ".join(tags.get(k, "") for k in ("operator", "owner", "brand", "name"))
    if not text.strip():
        return "Tidak disebut"
    return next(lab for lab, rx in OWNER_RE if rx.search(text))


def is_telecom(tags: dict) -> bool:
    mm = tags.get("man_made")
    if mm == "communications_tower":
        return True
    if mm not in ("tower", "mast"):
        return False
    if tags.get("tower:type") in ("communication", "telecommunication", "telecom", "cellular", "communications"):
        return True
    if any(k.startswith("communication:") and tags[k] not in ("no",) for k in tags):
        return True
    return bool(TELCO_HINT.search(" ".join(tags.get(k, "") for k in ("operator", "owner", "brand", "name", "description"))))


def extract(pbf: Path) -> tuple[list[tuple[float, float, str]], dict]:
    """[(lat, lon, owner)] dari file PBF + info header (timestamp replikasi)."""
    import osmium
    from osmium.filter import TagFilter
    pts, stats = [], Counter()
    fp = (osmium.FileProcessor(str(pbf), osmium.osm.NODE | osmium.osm.WAY).with_locations()
          .with_filter(TagFilter(("man_made", "tower"), ("man_made", "mast"), ("man_made", "communications_tower"))))
    for o in fp:
        tags = {t.k: t.v for t in o.tags}
        stats["kandidat_" + tags.get("man_made", "")] += 1
        if not is_telecom(tags):
            continue
        if o.is_node():
            lat, lon = o.location.lat, o.location.lon
        else:
            locs = [(n.location.lat, n.location.lon) for n in o.nodes if n.location.valid()]
            if not locs:
                continue
            lat, lon = sum(a for a, _ in locs) / len(locs), sum(b for _, b in locs) / len(locs)
        pts.append((round(lat, 5), round(lon, 5), owner_of(tags)))
        stats["way" if o.is_way() else "node"] += 1
    hdr = osmium.io.Reader(str(pbf), osmium.osm.NOTHING).header()
    ts = hdr.get("osmosis_replication_timestamp") or ""
    return pts, {"data_timestamp": ts, **stats}


def aggregate(pts, boundary: Path, gazetteer: Path) -> dict:
    import numpy as np
    import shapely
    kodes, geoms, approx = qc_boundaries(boundary, gazetteer)
    tree, areas = shapely.STRtree(geoms), np.array([g.area for g in geoms])
    owner = np.full(len(pts), -1)
    if pts:
        pi, gi = tree.query(shapely.points([(lo, la) for la, lo, _ in pts]), predicate="within")
        order = np.argsort(-areas[gi], kind="stable")          # wilayah terkecil menang (sama dengan OpenCelliD)
        owner[pi[order]] = gi[order]
    kab: dict[str, dict] = defaultdict(lambda: {"total": 0, "op": Counter()})
    outside = 0
    for i, (_, _, op) in enumerate(pts):
        if owner[i] < 0:
            outside += 1
            continue
        k = kab[kodes[owner[i]]]
        k["total"] += 1
        k["op"][op] += 1
    inside = [p for i, p in enumerate(pts) if owner[i] >= 0]          # ekstrak Geofabrik ikut memuat wilayah perbatasan
    by_op = Counter(op for _, _, op in inside)
    ops = [o for o, _ in by_op.most_common()]
    return {"total": len(inside), "outside_boundaries": outside, "by_op": dict(by_op.most_common()), "ops": ops,
            "kab": [{"k": k, "total": v["total"], "op": dict(v["op"])} for k, v in sorted(kab.items())],
            # titik untuk peta: [lat, lon, indeks pemilik/operator]
            "points": [[la, lo, ops.index(op)] for la, lo, op in inside]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", required=True)
    ap.add_argument("--out", default="site/data")
    ap.add_argument("--boundary", default="reference/batas_kabkota.geojson")
    ap.add_argument("--gazetteer", default="reference/wilayah_indonesia.csv")
    a = ap.parse_args()
    pts, info = extract(Path(a.pbf))
    if not pts:
        print("osm: tidak ada menara telekomunikasi ditemukan, data lama dipertahankan", file=sys.stderr)
        return 0
    agg = aggregate(pts, Path(a.boundary), Path(a.gazetteer))
    snap = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "attribution": ATTRIBUTION,
            "data_timestamp": info.pop("data_timestamp"), "stats": dict(info), **agg}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "osm_towers_id.json").write_text(json.dumps(snap, separators=(",", ":")), encoding="utf-8")
    print(f"osm: {agg['total']:,} menara telekomunikasi, {agg['outside_boundaries']:,} di luar batas, per pemilik {agg['by_op']}, "
          f"kandidat {info}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
