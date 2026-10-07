"""Test alat Ask the Data yang membaca snapshot JSON (cuaca, internet_outage, internet_operator, sebaran_sel).

Tanpa jaringan dan tanpa LLM: snapshot kecil ditulis ke folder sementara; prakiraan cuaca memakai respons asli BMKG.
Yang diuji: fakta dihitung kode dengan benar, filter lokasi/operator, dan router aturan memilih alat yang tepat.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
os.environ.setdefault("GAZETTEER_CSV", str(ROOT / "reference" / "wilayah_indonesia.csv"))
sys.path.insert(0, str(HERE.parent / "dags"))
sys.path.insert(0, str(ROOT / "app" / "api"))

import ask as A                              # noqa: E402
import src_bmkg_weather as BMKG              # noqa: E402

UTC = timezone.utc


def _hourly(start: datetime, hours: int, drop_at: set[int] = frozenset(), gap: range = range(0)) -> dict:
    t, v = [], []
    for i in range(hours):
        ts = start + timedelta(hours=i)
        t.append(ts.isoformat().replace("+00:00", "Z"))
        v.append(0.0 if i in gap else 0.3 if i in drop_at else 0.8)
    return {"t": t, "v": v}


NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
START = NOW - timedelta(days=28)
DROP_I = 28 * 24 - 10                       # 10 jam sebelum NOW


@pytest.fixture()
def snapdir(tmp_path, monkeypatch):
    doc = json.loads((HERE / "fixtures" / "bmkg_forecast_31.71.01.1001.json").read_text(encoding="utf-8"))
    (tmp_path / "web_weather.json").write_text(json.dumps({"generated_at": "2025-10-12T06:00:00+00:00",
                                                           "rows": BMKG.parse(doc), "count": 1}), encoding="utf-8")
    radar = {
        "generated_at": NOW.isoformat(),
        "asns": {"23693": {"label": "Telkomsel"}, "24203": {"label": "XL Axiata"}, "45727": {"label": "Tri (IOH)"}},
        "outages": [
            {"startDate": "2026-10-05T01:00:00Z", "endDate": "2026-10-05T04:30:00Z", "cause": "POWER_OUTAGE",
             "type": "REGIONAL", "scope": "West Java", "asns": [23693], "asn_names": ["TELKOMSEL-AS-AP"], "locations": ["Indonesia"]},
            {"startDate": "2026-03-01T00:00:00Z", "endDate": None, "cause": "CABLE_CUT", "scope": "Maluku",
             "asns": [], "asn_names": [], "locations": ["Indonesia"]},
        ],
        "anomalies": [{"startDate": "2026-10-06T10:00:00Z", "status": "UNVERIFIED", "asn": 24203, "asn_name": "XL"}],
        "traffic": {"23693": {"netflows": _hourly(START, 28 * 24, drop_at={DROP_I})},
                    "45727": {"netflows": _hourly(START, 28 * 24, gap=range(DROP_I - 20, DROP_I - 10))},
                    "24203": {"netflows": _hourly(START, 28 * 24)}},
        "speed_ops": [{"key": "ID", "bandwidthDownload": "30.5", "bandwidthUpload": "15", "latencyIdle": "25"},
                      {"key": "23693", "bandwidthDownload": "35.25", "bandwidthUpload": "12", "latencyIdle": "28"},
                      {"key": "24203", "bandwidthDownload": "22", "bandwidthUpload": "10", "latencyIdle": "31"}],
        "geo": [{"geoId": "1", "name": "West Java"}, {"geoId": "2", "name": "Jakarta"}, {"geoId": "3", "name": "Central Kalimantan"}],
        "adm1": {"ID": {"summary_0": {"1": "20.5", "2": "30", "3": "1.2"}},
                 "23693": {"summary_0": {"1": "18", "2": "25", "3": "2.5"}}},
        "adm1_ts": {"netflows": {"t": ["d"] * 10, "s": {"3": [1.0] * 9 + [0.5]}}},
        "bgp": {"23693": {"routes_total": 200, "routes_valid": 190, "routes_invalid": 2}},
    }
    (tmp_path / "radar_id.json").write_text(json.dumps(radar), encoding="utf-8")
    kab = lambda k, nama, prov, pk, tot, op, radio, pend: {  # noqa: E731
        "k": k, "nama": nama, "prov": prov, "prov_k": pk, "pend": pend, "total": tot, "recent": tot // 2, "op": op, "radio": radio}
    cells = {"generated_at": "2026-10-04T20:41:00+00:00", "cells_indonesia": 160,
             "by_op": {"Telkomsel": 100, "Indosat": 50, "XL Axiata": 10}, "by_radio": {"4G": 150, "2G": 10},
             "kab": [kab("62.71", "Kota Palangka Raya", "Kalimantan Tengah", "62", 40, {"Telkomsel": 30, "Indosat": 10},
                         {"4G": 36, "2G": 4}, 300000),
                     kab("62.01", "Kabupaten Kotawaringin Barat", "Kalimantan Tengah", "62", 0, {}, {}, 280000),
                     kab("31.71", "Kota Adm. Jakarta Pusat", "DKI Jakarta", "31", 120, {"Telkomsel": 70, "Indosat": 40, "XL Axiata": 10},
                         {"4G": 114, "2G": 6}, 1000000)]}
    (tmp_path / "cells_id.json").write_text(json.dumps(cells), encoding="utf-8")
    (tmp_path / "osm_towers_id.json").write_text(json.dumps({"data_timestamp": "2026-10-06T20:21:06Z", "total": 9,
        "by_op": {"Telkomsel": 4, "Tidak disebut": 5}, "kab": [{"k": "62.71", "total": 3, "op": {"Telkomsel": 2, "Tidak disebut": 1}},
                                                              {"k": "31.71", "total": 6, "op": {"Telkomsel": 2, "Tidak disebut": 4}}]}), encoding="utf-8")
    monkeypatch.setattr(A, "SNAPSHOT_DIR", str(tmp_path))
    A._SNAP_CACHE.clear()
    return tmp_path


def run(tool, q, lokasi="", hari=3, explicit=False, now=NOW):
    return A.TOOL_FUNCS[tool](None, {"_q": q.lower(), "lokasi": lokasi, "hari": hari, "_hari_explicit": explicit, "_now": now})


# ---------- cuaca
def test_cuaca_lokasi_tersedia(snapdir):
    r = run("cuaca", "cuaca jakarta besok?", "Jakarta", now=datetime(2025, 10, 12, 6, 0, tzinfo=UTC))
    assert r["alat"] == "cuaca" and r["prakiraan"][0]["periode"] == "besok"
    assert "Gambir" in r["fakta"][0] and "°C" in r["fakta"][0]
    slots = r["prakiraan"][0]["slot"]
    assert slots and all(s["waktu"].startswith("13-10") for s in slots)


def test_cuaca_lokasi_belum_dicakup(snapdir):
    r = run("cuaca", "cuaca di makassar", "Makassar")
    assert "belum termasuk" in r["fakta"][0] and "Kota Makassar" in r["fakta"][0]


# ---------- internet_outage
def test_outage_default_12_bulan_dan_penyebab(snapdir):
    r = run("internet_outage", "ada gangguan internet?")
    assert "2 gangguan internet" in r["fakta"][0] and "12 bulan" in r["fakta"][0]
    assert "pemadaman listrik" in r["fakta"][1] and "3,5 jam" in r["fakta"][1]


def test_outage_hari_eksplisit_dan_operator(snapdir):
    r = run("internet_outage", "outage telkomsel minggu ini", hari=7, explicit=True)
    assert "1 gangguan" in r["fakta"][0] and "Telkomsel" in r["fakta"][0]
    assert any("0 kejadian" in f for f in r["fakta"])      # anomaly milik XL, bukan Telkomsel


def test_outage_filter_provinsi_nama_inggris(snapdir):
    r = run("internet_outage", "internet mati di jawa barat", "Jawa Barat")
    assert "1 gangguan" in r["fakta"][0]


# ---------- internet_operator
def test_operator_kecepatan_dan_penurunan(snapdir):
    r = run("internet_operator", "kecepatan internet telkomsel")
    f = " ".join(r["fakta"])
    assert "Telkomsel: median unduh 35,2 Mbps" in f or "Telkomsel: median unduh 35,3 Mbps" in f
    assert "turun di bawah 60% dari normal selama 1 jam" in f and "37% dari normal" in f
    assert "95,0% valid RPKI" in f


def test_operator_celah_data_bukan_gangguan(snapdir):
    r = run("internet_operator", "trafik tri", hari=7, explicit=True)
    f = " ".join(r["fakta"])
    assert "tidak menunjukkan penurunan" in f and "10 jam tanpa data" in f


def test_operator_porsi_provinsi(snapdir):
    r = run("internet_operator", "internet di kalteng", "Kalimantan Tengah")
    f = " ".join(r["fakta"])
    assert "Kalimantan Tengah menyumbang 1,20% dari trafik internet Indonesia" in f and "peringkat 3 dari 3" in f
    assert "(-50,0%)" in f


def test_operator_smartfren_tidak_dipantau(snapdir):
    r = run("internet_operator", "sinyal smartfren")
    assert r["fakta"][0].startswith("Smartfren belum termasuk")


# ---------- sebaran_sel
def test_sel_nasional(snapdir):
    r = run("sebaran_sel", "berapa bts di indonesia")
    assert "160 sel" in r["fakta"][0] and "Telkomsel 100" in r["fakta"][1]
    assert "crowdsourced" in r["catatan"]


def test_sel_provinsi_dan_operator(snapdir):
    r = run("sebaran_sel", "jumlah bts telkomsel di kalimantan tengah", "Kalimantan Tengah")
    assert "30 sel Telkomsel" in r["fakta"][0] and "peringkat 2 dari 2" in r["fakta"][0]
    assert any("1 kab/kota" in f for f in r["fakta"])


def test_sel_kabkota(snapdir):
    r = run("sebaran_sel", "bts di palangka raya", "Palangka Raya")
    assert "Kota Palangka Raya" in r["fakta"][0] and "40 sel" in r["fakta"][0] and "13,3 sel per 100 ribu" in r["fakta"][0]
    assert "Porsi 4G/5G 90%" in r["fakta"][1]


# ---------- router aturan
@pytest.mark.parametrize("q,expect", [
    ("Besok Jakarta hujan nggak?", ["cuaca"]),
    ("Ada gangguan internet minggu ini?", ["internet_outage"]),
    ("Kecepatan internet Telkomsel vs XL?", ["internet_operator"]),
    ("Berapa BTS di Kalimantan Tengah?", ["sebaran_sel"]),
    ("Outage XL bulan ini", ["internet_outage", "internet_operator"]),
    ("Titik panas di Riau hari ini", ["titik_panas"]),
])
def test_rule_route(q, expect):
    assert A.rule_route(q)["alat"] == expect


def test_tri_bukan_substring():
    assert "internet_operator" not in A.rule_route("Harga beras di Nusa Tenggara Timur")["alat"]


# ---------- orkestrasi: pertanyaan lanjutan & pemangkasan alat (LLM dipalsukan)
def _fake_llm(monkeypatch, router_tools):
    def chat(client, system, user, schema, temperature):
        if schema:
            return json.dumps({"alat": router_tools, "lokasi": "", "hari": 3, "min_magnitudo": 0, "komoditas": "",
                               "topik": "", "kata_kunci": ""})
        return "jawaban"
    monkeypatch.setattr(A, "_chat", chat)


def test_followup_memakai_alat_sebelumnya(snapdir, monkeypatch):
    _fake_llm(monkeypatch, ["kualitas_udara", "harga_pangan", "cuaca"])     # tebakan LLM yang salah (kejadian nyata)
    r = A.ask(None, "kalau di Kalimantan Tengah?", client=object(), context="Berapa BTS Telkomsel di DKI Jakarta?")
    assert [t["nama"] for t in r["tools"]] == ["sebaran_sel"] and r["router"]["lanjutan"]
    assert "30 sel Telkomsel" in r["facts"][0]


def test_bts_dengan_nama_operator_tanpa_internet_operator(snapdir, monkeypatch):
    _fake_llm(monkeypatch, ["sebaran_sel", "internet_operator"])
    r = A.ask(None, "Berapa BTS Telkomsel di Kalimantan Tengah?", client=object())
    assert [t["nama"] for t in r["tools"]] == ["sebaran_sel"]


def test_trafik_provinsi_tanpa_angka_nasional(snapdir):
    r = run("internet_operator", "bagaimana trafik internet di kalimantan tengah", "Kalimantan Tengah")
    f = " ".join(r["fakta"])
    assert "hanya tersedia secara nasional" in f and "Mbps" not in f and "Telkomsel" not in f


@pytest.mark.parametrize("q,yes", [("kalau di Jawa Barat?", True), ("Yang di Riau?", True),
                                   ("Bagaimana trafik internet di Jawa Timur?", False), ("Kalau harga beras di provinsi yang paling murah di Indonesia mana?", False)])
def test_is_followup(q, yes):
    assert A.is_followup(q) is yes


def test_sel_dengan_menara_osm(snapdir):
    r = run("sebaran_sel", "jumlah bts telkomsel di kalimantan tengah", "Kalimantan Tengah")
    assert "OpenStreetMap mencatat 2 menara telekomunikasi milik/operator Telkomsel di Provinsi Kalimantan Tengah" in r["fakta"][-1]
    r = run("sebaran_sel", "berapa bts di indonesia")
    assert "OpenStreetMap mencatat 9 menara telekomunikasi di Indonesia (data 2026-10-06)." == r["fakta"][-1]
