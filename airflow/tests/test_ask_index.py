"""Indeks Ask the Data versi publik: titik panas/gempa dipetakan ke kab/kota dengan batas yang sudah di-QC."""
import json
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("shapely")
ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("GAZETTEER_CSV", str(ROOT / "reference" / "wilayah_indonesia.csv"))
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "airflow" / "dags")]
import ask_index  # noqa: E402


def test_index_and_gazetteer(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    (tmp_path / "hotspots.json").write_text(json.dumps({"points": [
        [-2.21, 113.92, 12.5, "n", "2026-10-09T05:30"],      # pusat Kota Palangkaraya (poligon sumber salah -> batas perkiraan)
        [-2.0, 113.5, 40, "h", "2026-10-09T06:00"], [2.0, 103.0, 5, "n", "2026-10-09T05:00"]]}))   # titik terakhir: Malaysia
    (tmp_path / "earthquakes.json").write_text(json.dumps({"features": [
        {"geometry": {"coordinates": [110.42, -7.5]}, "properties": {"id": "q1"}},
        {"geometry": {"coordinates": [125.0, -9.9]}, "properties": {"id": "q2"}}]}))
    idx = ask_index.build_index(str(tmp_path), "reference/batas_kabkota.geojson", os.environ["GAZETTEER_CSV"])
    day = idx["hotspots"]["2026-10-09"]
    assert day["total"] == 3 and day["outside"] == 1 and day["kab"]["62.71"] == [1, 12.5]
    assert idx["quakes"]["q1"]["kab"].startswith("33.") and "33" in idx["quakes"]["q1"]["near_prov"]
    assert idx["quakes"]["q2"]["kab"] is None and idx["quakes"]["q2"]["near_prov"] == ["53"]
    g = ask_index.build_gazetteer()
    assert g["keys"]["kalteng"] == ["62"] and g["keys"]["jakarta"] == ["31"] and g["keys"]["semeru"] == ["35.08"]
    assert "barat" in g["ambiguous"] and len(g["rows"]) > 500
