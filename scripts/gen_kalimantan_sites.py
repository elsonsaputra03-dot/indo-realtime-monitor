"""
Bangkitkan site/assets/kalimantan.js untuk Network KPI Monitor.

- Geografi PUBLIK: batas & ibu kota 56 kab/kota Kalimantan dari reference/ (cahyadsn/wilayah, MIT; QC poligon dari scripts/risk.py).
- Lokasi site SINTETIS: titik acak berbiji tetap di dalam batas kabupaten (lebih rapat di sekitar ibu kota).
  Tidak memakai data operator apa pun.

Jalankan: GAZETTEER_CSV=reference/wilayah_indonesia.csv PYTHONPATH=scripts:airflow/dags python scripts/gen_kalimantan_sites.py
"""
import csv, json, math, random
from shapely.geometry import mapping, Point
import risk

random.seed(20260830)
ABBR = {"61": "KALBAR", "62": "KALTENG", "63": "KALSEL", "64": "KALTIM", "65": "KALTARA"}
gaz = {r["kode"]: r for r in csv.DictReader(open("reference/wilayah_indonesia.csv", encoding="utf-8"))}
regions = [r for r in risk.load_regions("reference/batas_kabkota.geojson", "reference/wilayah_indonesia.csv") if r["prov_kode"] in ABBR]
prov_cap = {k: (float(gaz[k]["lat"]), float(gaz[k]["lng"])) for k in ABBR}

def rnd(o):
    if isinstance(o, float): return round(o, 3)
    if isinstance(o, (list, tuple)): return [rnd(x) for x in o]
    if isinstance(o, dict): return {k: rnd(v) for k, v in o.items()}
    return o

clusters = {}
for pk in ABBR:
    ks = sorted([r for r in regions if r["prov_kode"] == pk], key=lambda r: float(gaz[r["kode"]]["lng"]))
    n = 3 if len(ks) >= 12 else 2
    size = math.ceil(len(ks) / n)
    for i in range(n):
        grp = ks[i * size:(i + 1) * size]
        if not grp: continue
        anchor = next((g for g in grp if g["nama"].startswith("Kota")), max(grp, key=lambda g: g["luas_km2"]))
        name = f"{ABBR[pk]}-{i + 1:02d} " + anchor["nama"].replace("Kabupaten ", "").replace("Kota ", "")
        for g in grp: clusters[g["kode"]] = name

kabs, feats, sites = [], [], []
for r in regions:
    g = gaz[r["kode"]]; lat, lng = float(g["lat"]), float(g["lng"])
    kota = r["nama"].startswith("Kota")
    n = random.randint(20, 42) if kota else int(min(70, 6 + r["luas_km2"] ** .4 * random.uniform(.7, 1.0)))
    poly = r["geom"]; minx, miny, maxx, maxy = poly.bounds
    sig = .05 if kota else .18
    pts, tries = [], 0
    while len(pts) < n and tries < n * 400:
        tries += 1
        x, y = (random.gauss(lng, sig), random.gauss(lat, sig)) if random.random() < .6 else (random.uniform(minx, maxx), random.uniform(miny, maxy))
        if poly.contains(Point(x, y)): pts.append((round(y, 3), round(x, 3)))
    pc = prov_cap[r["prov_kode"]]
    for y, x in pts:
        d_cap = math.hypot((y - lat) * 111, (x - lng) * 111)
        d_prov = math.hypot((y - pc[0]) * 111, (x - pc[1]) * 111)
        sites.append([r["kode"], y, x, 1 if (kota or d_cap < 12) else 0, round(d_prov)])
    kabs.append({"k": r["kode"], "n": r["nama"], "p": r["prov_nama"], "pk": r["prov_kode"], "c": clusters[r["kode"]],
                 "lat": lat, "lng": lng, "approx": 0 if r["batas_valid"] else 1})
    feats.append({"type": "Feature", "properties": {"k": r["kode"]},
                  "geometry": rnd(json.loads(json.dumps(mapping(r["geom"].simplify(.01, preserve_topology=True)))))})
random.shuffle(sites)
out = ("/* Geografi Kalimantan (publik) + lokasi site SINTETIS acak di dalam batas kabupaten. "
       "Dibangkitkan oleh scripts/gen_kalimantan_sites.py; bukan data operator. */\n")
out += "window.KALI=" + json.dumps({"kabs": kabs, "geo": {"type": "FeatureCollection", "features": feats}, "sites": sites}, separators=(",", ":")) + ";\n"
open("site/assets/kalimantan.js", "w", encoding="utf-8").write(out)
print(f"kab {len(kabs)}, site {len(sites)}, cluster {len(set(clusters.values()))}, {len(out) // 1024} KB")
