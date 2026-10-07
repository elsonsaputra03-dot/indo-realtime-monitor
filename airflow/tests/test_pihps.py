"""PIHPS: tanggal berbahasa Indonesia maupun Inggris harus terbaca (bug Oktober: 'Okt' dibuang)."""
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "dags"))
import pihps_lib as P  # noqa: E402


@pytest.mark.parametrize("s,d", [("28 Sep 26", date(2026, 9, 28)), ("01 Okt 26", date(2026, 10, 1)), ("02 Oct 26", date(2026, 10, 2)),
                                 ("15 Mei 26", date(2026, 5, 15)), ("17 Agu 26", date(2026, 8, 17)), ("25 Des 26", date(2026, 12, 25)),
                                 ("1 Oktober 2026", date(2026, 10, 1)), ("", None), ("bukan tanggal", None)])
def test_parse_short_date(s, d):
    assert P.parse_short_date(s) == d


def test_normalize_oktober():
    r = P.normalize({"Tanggal": "01 Okt 26", "Nilai": 15600, "ProvID": 32, "Provinsi": "Jawa Barat",
                     "TanggalLast": "30 Sep 26", "SemuaProvinsi": 16350}, 1)
    assert r["price_date"] == "2026-10-01" and r["prev_date"] == "2026-09-30" and r["price"] == 15600


def test_fetch_tanpa_duplikat(monkeypatch):
    rows = [{"Tanggal": "07 Okt 26", "Nilai": 15600, "ProvID": 32, "Provinsi": "Jawa Barat", "SemuaProvinsi": 16350}]

    class R:
        def raise_for_status(self): pass
        def json(self): return rows

    class C:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def get(self, *a, **k): return R()

    monkeypatch.setattr(P.httpx, "Client", C)
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    res = P.fetch_commodity(1, [date(2026, 10, 8), date(2026, 10, 7)])     # dua tanggal -> data terakhir yang sama
    assert res["status"] == "ok" and len(res["items"]) == 1
