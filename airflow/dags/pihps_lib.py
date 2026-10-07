"""
Helper DAG food_price_ingest (bukan DAG).
Sumber: PIHPS Nasional, Bank Indonesia (https://www.bi.go.id/hargapangan).
robots.txt bi.go.id tidak melarang /hargapangan. Etika: 2 run/hari, jeda antar request,
User-Agent jelas, atribusi sumber di UI & README.
"""
import json
import time
from datetime import date, datetime

import httpx

BASE = "https://www.bi.go.id/hargapangan/WebSite/Home/GetHistogramData"
USER_AGENT = "indo-realtime-monitor/0.3 (+https://github.com/elsonsaputra03-dot/indo-realtime-monitor)"
REQUEST_GAP_SECONDS = 3

# ID kelompok komoditas dari endpoint GetCommoditiesTree (TreeID level atas)
COMMODITIES = {
    1: "Beras", 2: "Daging Ayam", 3: "Daging Sapi", 4: "Telur Ayam", 5: "Bawang Merah",
    6: "Bawang Putih", 7: "Cabai Merah", 8: "Cabai Rawit", 9: "Minyak Goreng", 10: "Gula Pasir",
}
PRICE_TYPE_TRADITIONAL = 1   # sesuai request halaman beranda PIHPS


# Bulan bisa berbahasa Indonesia ("01 Okt 26", "15 Mei 26", "17 Agu 26", "25 Des 26") atau Inggris.
# Sebelumnya hanya format Inggris (%b) yang dibaca, sehingga sejak 1 Oktober semua baris terbuang ("Okt" bukan "Oct").
MONTHS = {m: i + 1 for i, names in enumerate([
    ("jan", "januari", "january"), ("feb", "februari", "february"), ("mar", "maret", "march"), ("apr", "april"),
    ("mei", "may"), ("jun", "juni", "june"), ("jul", "juli", "july"), ("agu", "agt", "ags", "aug", "agustus", "august"),
    ("sep", "sept", "september"), ("okt", "oct", "oktober", "october"), ("nov", "nop", "november"),
    ("des", "dec", "desember", "december")]) for m in names}
ID_MONTH = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


def parse_short_date(s: str) -> date | None:
    """'28 Sep 26' / '01 Okt 26' / '1 Oktober 2026' -> date."""
    try:
        d, m, y = str(s).strip().replace("-", " ").split()[:3]
        year = int(y) + (2000 if len(y) == 2 else 0)
        return date(year, MONTHS[m.lower().rstrip(".")], int(d))
    except (ValueError, KeyError, AttributeError):
        return None


def normalize(row: dict, commodity_id: int) -> dict | None:
    d = parse_short_date(row.get("Tanggal", ""))
    price = row.get("Nilai")
    if d is None or price is None or float(price) <= 0 or row.get("ProvID") is None:
        return None
    prev = parse_short_date(row.get("TanggalLast", "") or "")
    return {
        "price_date": d.isoformat(),
        "prov_id": int(row["ProvID"]),
        "province": str(row.get("Provinsi", "")).strip(),
        "commodity_id": commodity_id,
        "commodity": str(row.get("Komoditas") or COMMODITIES.get(commodity_id, "")).strip(),
        "price": float(price),
        "national_avg": float(row.get("SemuaProvinsi") or 0),
        "pct_change": float(row.get("Percentage") or 0),
        "prev_date": prev.isoformat() if prev else "1970-01-01",
        "price_group": int(row.get("Kelompok") or 0),
    }


def fetch_commodity(commodity_id: int, dates: list[date]) -> dict:
    """Satu komoditas untuk beberapa tanggal. Tidak pernah raise (dipakai di task mapping)."""
    t0 = time.monotonic()
    out = {"commodity_id": commodity_id, "status": "ok", "items": [], "error": "", "ms": 0}
    try:
        with httpx.Client(headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                          timeout=httpx.Timeout(20, read=90),
                          transport=httpx.HTTPTransport(retries=2)) as client:
            for d in dates:
                # tanggal dikirim berbahasa Inggris seperti sebelumnya; bila tidak ada baris yang terbaca, coba sekali
                # lagi dengan nama bulan Indonesia (format yang dipakai server berbeda per bulan untuk Okt/Mei/Agu/Des)
                labels = [d.strftime("%d %b %Y")]
                alt = f"{d.day:02d} {ID_MONTH[d.month - 1]} {d.year}"
                if alt != labels[0]:
                    labels.append(alt)
                for label in labels:
                    r = client.get(BASE, params={
                        "tanggal": label, "commodity": commodity_id,
                        "priceType": PRICE_TYPE_TRADITIONAL, "isPasokan": 1, "jenis": 1,
                        "periode": 1, "provId": 0,
                    })
                    r.raise_for_status()
                    rows = r.json()
                    if isinstance(rows, str):   # server kadang mengirim JSON ter-encode dua kali
                        rows = json.loads(rows)
                    if not isinstance(rows, list):
                        raise ValueError(f"format respons tidak dikenal: {str(rows)[:120]}")
                    got = [x for x in (normalize(row, commodity_id) for row in rows) if x]
                    out["rows_raw"] = out.get("rows_raw", 0) + len(rows)
                    if rows and not got and not out.get("sample"):
                        out["sample"] = {k: rows[0].get(k) for k in ("Tanggal", "Nilai", "ProvID")}
                    time.sleep(REQUEST_GAP_SECONDS)
                    if got:
                        out["items"] += got
                        break
    except Exception as exc:  # noqa: BLE001
        out.update(status="error", error=f"{type(exc).__name__}: {exc}"[:300])
    # server mengembalikan data terakhir yang tersedia untuk tanggal mana pun yang diminta: hari ini dan kemarin bisa
    # menghasilkan baris yang sama persis, jadi satu baris per (provinsi, tanggal)
    out["items"] = list({(x["prov_id"], x["price_date"]): x for x in out["items"]}.values())
    out["ms"] = int((time.monotonic() - t0) * 1000)
    return out
