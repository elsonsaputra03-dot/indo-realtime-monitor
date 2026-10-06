"""Tabel dari artikel Wikipedia lewat API MediaWiki (action=parse), lalu diurai dari HTML.

Kebijakan Wikimedia: pakai API (bukan merayapi halaman), User-Agent dengan kontak, permintaan berurutan dan jarang.
Tabel wikitable sering memakai rowspan/colspan dan catatan kaki [1]; parser ini mengembangkan rowspan/colspan menjadi
grid penuh dan membuang catatan kaki, sehingga setiap baris menjadi {header: nilai}.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from bs4 import BeautifulSoup

from scrape_lib import Polite

API = "https://id.wikipedia.org/w/api.php"
# dataset -> (halaman kandidat berurutan, kata kunci header yang WAJIB ada). Halaman pertama yang memuat tabel cocok
# yang dipakai. Kandidat diperlukan karena isi artikel berubah: "Daftar provinsi di Indonesia" tidak lagi memuat tabel
# data (hanya navbox) saat run pertama 6 Okt 2026; tabelnya ada di "Provinsi di Indonesia" (39 baris).
DATASETS = {
    "provinsi": (["Provinsi di Indonesia", "Daftar provinsi di Indonesia"], ["provinsi", "ibu kota"]),
}


def _text(cell) -> str:
    for sup in cell.find_all(["sup"]):
        sup.decompose()
    for br in cell.find_all("br"):
        br.replace_with(" ")
    return re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip()


def parse_tables(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for t_idx, table in enumerate(soup.select("table.wikitable")):
        grid: list[list[str]] = []
        head_rows = 0                                       # baris header di awal (semua sel <th>), bisa lebih dari satu
        pending: dict[int, tuple[str, int]] = {}            # kolom -> (teks, sisa baris rowspan)
        for tr in table.find_all("tr"):
            row, col = [], 0
            cells = tr.find_all(["th", "td"], recursive=False)
            if cells and head_rows == len(grid) and all(c.name == "th" for c in cells):
                head_rows += 1
            ci = 0
            while ci < len(cells) or col in pending:
                if col in pending:
                    txt, left = pending[col]
                    row.append(txt)
                    if left <= 1:
                        del pending[col]
                    else:
                        pending[col] = (txt, left - 1)
                    col += 1
                    continue
                cell = cells[ci]; ci += 1
                txt = _text(cell)
                span = int(cell.get("colspan", 1) or 1)
                rspan = int(cell.get("rowspan", 1) or 1)
                for k in range(span):
                    row.append(txt)
                    if rspan > 1:
                        pending[col + k] = (txt, rspan - 1)
                col += span
            if row:
                grid.append(row)
        if len(grid) < 2:
            continue
        # Header bertingkat digabung per kolom: "Kode" (colspan 2) di atas "BPS" / "ISO (ID-)" menjadi
        # "Kode / BPS" dan "Kode / ISO (ID-)". Versi awal hanya memakai baris pertama, sehingga baris header kedua
        # tersimpan sebagai data (ditemukan pada run sungguhan "Provinsi di Indonesia", 6 Okt 2026).
        head_rows = max(head_rows, 1)
        width = max(len(r) for r in grid[:head_rows])
        merged = []
        for i in range(width):
            parts = []
            for r in grid[:head_rows]:
                v = r[i] if i < len(r) else ""
                if v and v not in parts:
                    parts.append(v)
            merged.append(" / ".join(parts))
        # nama yang tetap kembar dibuat unik: tanpa ini, kolom kedua MENIMPA kolom pertama saat baris diubah menjadi
        # dict dan datanya hilang diam-diam (ditemukan oleh test dengan header colspan)
        header, seen = [], {}
        for h in merged:
            seen[h] = seen.get(h, 0) + 1
            header.append(h if seen[h] == 1 else f"{h} ({seen[h]})")
        rows = [dict(zip(header, r)) for r in grid[head_rows:] if any(r)]
        out.append({"table_idx": t_idx, "header": header, "rows": rows})
    return out


def pick(tables: list[dict], keywords: list[str]) -> dict | None:
    for t in tables:
        h = " | ".join(x.lower() for x in t["header"])
        if all(k in h for k in keywords):
            return t
    return None


def fetch(c: Polite | None = None) -> dict:
    c = c or Polite(min_gap=2.0, respect_robots=False)
    rows, errors, used, t0 = [], [], {}, datetime.now()
    for name, (pages, keywords) in DATASETS.items():
        tried = []
        for page in pages:
            try:
                d = c.get(API, params={"action": "parse", "page": page, "prop": "text|revid", "format": "json",
                                       "formatversion": 2, "redirects": 1}).json()
            except Exception as e:  # noqa: BLE001
                tried.append(f"{page}: {type(e).__name__}"); continue
            if "error" in d:
                tried.append(f"{page}: {d['error'].get('info', '')}"); continue
            t = pick(parse_tables(d["parse"]["text"]), keywords)
            if not t:
                tried.append(f"{page}: no table with headers {keywords}"); continue
            title = d["parse"].get("title", page)
            for i, r in enumerate(t["rows"]):
                rows.append({"page": title, "revid": d["parse"].get("revid", 0), "table_idx": t["table_idx"], "row_idx": i,
                             "cells": json.dumps(r, ensure_ascii=False)})
            used[name] = title
            break
        else:
            errors.append(f"{name}: no candidate page had the table (layout changed?) - " + "; ".join(tried)[:300])
    return {"rows": rows, "errors": errors, "used": used, "ms": int((datetime.now() - t0).total_seconds() * 1000), "stats": c.stats}
