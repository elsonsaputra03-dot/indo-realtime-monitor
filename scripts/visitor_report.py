"""Laporan kunjungan portofolio harian dari GoatCounter, dikirim lewat email (dijalankan oleh GitHub Actions).

Email hanya dikirim bila ada kunjungan dalam 24 jam terakhir (ubah dengan SEND_EMPTY=1). Isinya: jumlah kunjungan, sumber
(?ref=cv, linkedin, nama perusahaan, atau situs perujuk), halaman yang dibuka per sumber, dan negara. Semua angka adalah
agregat GoatCounter; tidak ada data yang mengidentifikasi pengunjung.

Variabel lingkungan (GitHub → Settings → Secrets and variables → Actions):
  GOATCOUNTER_CODE      kode situs, mis. elsonsaputra
  GOATCOUNTER_TOKEN     API token GoatCounter dengan izin baca statistik
  SMTP_USER             alamat Gmail pengirim
  SMTP_PASSWORD         Gmail App Password (bukan password akun)
  REPORT_TO             alamat penerima (boleh sama dengan SMTP_USER)
Opsional: SMTP_HOST (smtp.gmail.com), SMTP_PORT (465), HOURS (24), SEND_EMPTY (0), DRY_RUN (1 = cetak saja, tanpa kirim)
"""
from __future__ import annotations

import html
import json
import os
import smtplib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

WIB = timezone(timedelta(hours=7))
SITE = "https://elsonsaputra03-dot.github.io/indo-realtime-monitor/"


def window(hours: int, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Rentang [mulai, akhir) dibulatkan ke jam, sesuai anjuran API GoatCounter."""
    end = (now or datetime.now(timezone.utc)).replace(minute=0, second=0, microsecond=0)
    return end - timedelta(hours=hours), end


class GoatCounter:
    """Klien API GoatCounter dengan jeda antarpermintaan dan retry.

    API GoatCounter dibatasi ~4 permintaan/detik per token. collect() memanggil satu permintaan per halaman yang dikunjungi,
    jadi pada hari dengan banyak halaman dibuka, rentetan permintaan tanpa jeda bisa kena HTTP 429 dan job gagal dalam
    hitungan detik (run 8 Okt 2026). Kini: jeda minimal antarpermintaan, retry untuk 429/5xx/timeout dengan menghormati
    header X-Rate-Limit-Reset / Retry-After, dan pesan error yang menyebut status serta isi respons.
    """
    RETRY_STATUS = {429, 500, 502, 503, 504}

    def __init__(self, code: str, token: str, opener=urllib.request.urlopen, sleep=time.sleep, clock=time.monotonic,
                 min_interval: float = 0.35, retries: int = 4):
        self.base, self.token, self.opener = f"https://{code}.goatcounter.com/api/v0", token, opener
        self.sleep, self.clock, self.min_interval, self.retries = sleep, clock, min_interval, retries
        self._last = None

    def _throttle(self) -> None:
        if self._last is not None:
            wait = self.min_interval - (self.clock() - self._last)
            if wait > 0:
                self.sleep(wait)
        self._last = self.clock()

    @staticmethod
    def _retry_after(err: urllib.error.HTTPError, attempt: int) -> float:
        for h in ("X-Rate-Limit-Reset", "Retry-After"):
            v = err.headers.get(h) if err.headers else None
            try:
                if v is not None:
                    return min(max(float(v), 1.0), 30.0)
            except ValueError:
                pass
        return min(2 ** attempt, 30)

    def get(self, path: str, start: datetime, end: datetime, **params) -> dict:
        q = urllib.parse.urlencode({"start": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"), **params})
        req = urllib.request.Request(f"{self.base}{path}?{q}", headers={"Authorization": f"Bearer {self.token}",
                                                                         "Content-Type": "application/json"})
        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                with self.opener(req, timeout=30) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code in self.RETRY_STATUS and attempt < self.retries:
                    wait = self._retry_after(e, attempt)
                    print(f"GoatCounter {path}: HTTP {e.code}, coba lagi dalam {wait:.0f} dtk ({attempt + 1}/{self.retries})")
                    self.sleep(wait)
                    continue
                detail = ""
                try:
                    detail = e.read().decode("utf-8", "replace")[:300]
                except Exception:
                    pass
                raise RuntimeError(f"GoatCounter {path}: HTTP {e.code} {e.reason} {detail}".strip()) from e
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < self.retries:
                    wait = min(2 ** attempt, 30)
                    print(f"GoatCounter {path}: {e}, coba lagi dalam {wait} dtk ({attempt + 1}/{self.retries})")
                    self.sleep(wait)
                    continue
                raise RuntimeError(f"GoatCounter {path}: {e}") from e
        raise AssertionError("unreachable")


# Kunjungan tanpa informasi asal: alamat diketik / bookmark, atau dibuka dari aplikasi yang menyembunyikan asal
# (WhatsApp, Telegram, aplikasi email, aplikasi LinkedIn, CV PDF). Pakai ?ref= di tautan supaya asalnya tetap terbaca.
NO_REF = "tanpa asal (langsung, WhatsApp, email, PDF)"
AI_EVENT = "ask-portfolio"
HOME = "halaman utama"


def collect(gc: GoatCounter, start: datetime, end: datetime) -> dict:
    total = gc.get("/stats/total", start, end).get("total", 0)
    if not total:
        return {"total": 0, "page_views": 0, "entries": 0, "ai_questions": 0, "pages": [], "refs": [], "locations": []}
    hits = gc.get("/stats/hits", start, end, limit=100).get("hits", [])
    pages = [{"path": h["path"], "title": h.get("title", ""), "count": h["count"], "path_id": h["path_id"]}
             for h in hits if h.get("count") and not h.get("event")]
    # Event bukan kunjungan halaman. /stats/total ikut menghitungnya, sehingga total di email pertama (5) tidak sama dengan
    # jumlah halaman (4): selisihnya satu pertanyaan ke chatbot. Total kini = jumlah kunjungan halaman; event ditampilkan terpisah.
    ai_questions = sum(h["count"] for h in hits if h.get("event") and AI_EVENT in h.get("path", "") and h.get("count"))
    # /indo-realtime-monitor, /indo-realtime-monitor/ dan /index.html adalah halaman yang sama tetapi path berbeda di
    # GoatCounter; digabung supaya tidak muncul dua kali di email (terlihat di email pertama)
    refs = [{"name": s.get("name") or NO_REF, "count": s["count"]}
            for s in gc.get("/stats/toprefs", start, end, limit=100).get("stats", []) if s.get("count")]
    by_ref: dict[str, list] = {}
    for p in pages:                                       # sumber per halaman: halaman apa yang dibaca dari tiap sumber
        for r in gc.get(f"/stats/hits/{p['path_id']}", start, end, limit=100).get("refs", []):
            if r.get("count"):
                by_ref.setdefault(r.get("name") or NO_REF, []).append((p["path"], r["count"]))
    for r in refs:
        r["pages"] = _merge(by_ref.get(r["name"], []))
    locs = [{"name": s.get("name") or "?", "count": s["count"]}
            for s in gc.get("/stats/locations", start, end, limit=20).get("stats", []) if s.get("count")]
    merged = {}
    for p in pages:
        merged[short(p["path"])] = merged.get(short(p["path"]), 0) + p["count"]
    pages = [{"path": k, "count": v} for k, v in sorted(merged.items(), key=lambda x: -x[1])]
    # Angka utama = jumlah orang yang membuka halaman utama (GoatCounter: unik per halaman per hari). Halaman lain hanya
    # rincian, tidak dijumlahkan, karena satu orang yang menjelajah 15 halaman sebelumnya terhitung 15.
    home = sum(p["count"] for p in pages if p["path"] == HOME)
    return {"total": home, "page_views": sum(p["count"] for p in pages), "entries": sum(r["count"] for r in refs), "ai_questions": ai_questions,
            "pages": pages, "refs": refs, "locations": locs}


def _merge(items: list) -> list:
    out = {}
    for path, n in items:
        out[short(path)] = out.get(short(path), 0) + n
    return sorted(out.items(), key=lambda x: -x[1])


def short(path: str) -> str:
    p = path.replace("/indo-realtime-monitor", "", 1).rstrip("/") or "/"
    return {"/": "halaman utama", "/index.html": "halaman utama"}.get(p, p.lstrip("/"))


def compose(d: dict, start: datetime, end: datetime) -> tuple[str, str, str]:
    period = f"{start.astimezone(WIB):%d %b %H:%M} – {end.astimezone(WIB):%d %b %H:%M} WIB"
    ai = d.get("ai_questions", 0)
    top = ", ".join(f"{r['name'].split(' (')[0]} {r['count']}" for r in d["refs"][:3])
    if d["total"] or d.get("page_views") or ai:
        subject = f"Portofolio: {d['total']} orang masuk" + (f" ({top})" if top else "") + (f", {ai} tanya AI" if ai else "")
    else:
        subject = "Portofolio: tidak ada kunjungan"
    summary = f"{d['total']} orang membuka halaman utama, {d.get('page_views', 0)} halaman dibuka total" + (f", {ai} pertanyaan ke chatbot" if ai else "")
    lines = [f"Kunjungan portofolio {period}", summary, ""]
    if d["refs"]:
        lines.append("Masuk dari (asal kunjungan):")
        for r in d["refs"]:
            lines.append(f"  - {r['name']}: {r['count']}")
            for path, n in r["pages"]:
                lines.append(f"      {short(path)} ({n})")
        lines.append("")
    if d["pages"]:
        lines.append("Halaman yang dibuka (rincian, tidak dijumlahkan ke angka utama):")
        lines += [f"  - {short(p['path'])}: {p['count']}" for p in d["pages"]]
        lines.append("")
    if ai:
        lines += [f"Tanya AI (chatbot portofolio): {ai} pertanyaan", ""]
    if d["locations"]:
        lines.append("Negara" + (" (termasuk pertanyaan ke chatbot)" if ai else "") + ": " + ", ".join(f"{l['name']} {l['count']}" for l in d["locations"]))
    lines += ["", NOTE, f"Dashboard: https://{os.getenv('GOATCOUNTER_CODE', 'elsonsaputra')}.goatcounter.com", f"Portofolio: {SITE}"]
    text = "\n".join(lines)
    e = html.escape
    rows = "".join(f"<tr><td style='padding:4px 10px'><b>{e(r['name'])}</b></td><td style='padding:4px 10px;text-align:right'>{r['count']}</td>"
                   f"<td style='padding:4px 10px;color:#5D6D78'>{e(', '.join(f'{short(p)} ({n})' for p, n in r['pages']))}</td></tr>" for r in d["refs"])
    pages = "".join(f"<li>{e(short(p['path']))}: {p['count']}</li>" for p in d["pages"])
    body = f"""<div style="font-family:Arial,sans-serif;font-size:14px;color:#1D2A33">
<p style="font-size:16px"><b>{d['total']} orang masuk</b> ke portofolio (membuka halaman utama), {e(period)}<br>
<span style="font-size:14px;color:#5D6D78">{d.get('page_views', 0)} halaman dibuka total{f' · <b>{ai} pertanyaan ke chatbot</b>' if ai else ''}</span></p>
{f'<p><b>Masuk dari</b></p><table style="border-collapse:collapse">{rows}</table>' if rows else ''}
{f'<p><b>Halaman yang dibuka</b> <span style="color:#5D6D78">(rincian)</span></p><ul>{pages}</ul>' if pages else ''}
{f'<p><b>Tanya AI:</b> {ai} pertanyaan ke chatbot portofolio</p>' if ai else ''}
{f'<p>Negara{" (termasuk pertanyaan ke chatbot)" if ai else ""}: {e(", ".join(f"{l["name"]} {l["count"]}" for l in d["locations"]))}</p>' if d["locations"] else ''}
<p style="color:#5D6D78;font-size:12px">{e(NOTE)}<br>
<a href="https://{e(os.getenv('GOATCOUNTER_CODE', 'elsonsaputra'))}.goatcounter.com">Buka dashboard</a> · <a href="{SITE}">Portofolio</a></p></div>"""
    return subject, text, body


NOTE = ("Cara membaca: GoatCounter menghitung pengunjung per halaman per hari (satu orang yang membuka 3 halaman = 3). "
        "'Masuk dari' hanya menghitung pintu masuk dari luar; klik antarhalaman di dalam situs tidak dihitung sebagai asal. "
        "Tanpa cookie; pengunjung dengan ad blocker tidak tercatat. Pakai ?ref= di tautan (cv, linkedin, nama perusahaan) agar asalnya terbaca.")


def send(subject: str, text: str, body: str, smtp_factory=smtplib.SMTP_SSL) -> None:
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, os.environ["SMTP_USER"], os.environ["REPORT_TO"]
    msg.set_content(text)
    msg.add_alternative(body, subtype="html")
    with smtp_factory(os.getenv("SMTP_HOST", "smtp.gmail.com"), int(os.getenv("SMTP_PORT", "465")), timeout=30) as s:
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        s.send_message(msg)


REQUIRED = ("GOATCOUNTER_CODE", "GOATCOUNTER_TOKEN", "SMTP_USER", "SMTP_PASSWORD", "REPORT_TO")


def check_env() -> None:
    """GitHub Actions mengisi secret yang belum dibuat dengan string KOSONG, bukan menghapusnya; tanpa cek ini, kode situs
    kosong menghasilkan host '.goatcounter.com' dan error 'label empty or too long' yang membingungkan (terjadi di run pertama)."""
    missing = [k for k in REQUIRED if not os.getenv(k, "").strip()]
    if missing:
        print("::error title=visitor-report::secret belum diisi: " + ", ".join(missing))
        sys.exit("secret belum diisi: " + ", ".join(missing) + " (GitHub: Settings -> Secrets and variables -> Actions)")
    code = os.environ["GOATCOUNTER_CODE"].strip()
    if not code.replace("-", "").isalnum() or code != code.lower():
        sys.exit(f"GOATCOUNTER_CODE harus kode situs saja, mis. elsonsaputra (bukan URL); sekarang: {code!r}")


def main() -> int:
    check_env()
    start, end = window(int(os.getenv("HOURS", "24")))
    d = collect(GoatCounter(os.environ["GOATCOUNTER_CODE"], os.environ["GOATCOUNTER_TOKEN"]), start, end)
    subject, text, body = compose(d, start, end)
    print(subject); print(text)
    if not d["total"] and not d.get("page_views") and not d.get("ai_questions") and os.getenv("SEND_EMPTY", "0") != "1":
        print("tidak ada kunjungan: email tidak dikirim"); return 0
    if os.getenv("DRY_RUN", "0") == "1":
        print("DRY_RUN: email tidak dikirim"); return 0
    send(subject, text, body)
    print(f"email terkirim ke {os.environ['REPORT_TO']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - tulis penyebab ke annotation GitHub (log job tidak selalu bisa dibuka)
        import traceback
        traceback.print_exc()
        where = traceback.extract_tb(exc.__traceback__)[-1]
        msg = f"{type(exc).__name__}: {exc} (baris {where.lineno}, {where.name})".replace("\n", " ")[:900]
        print(f"::error title=visitor-report::{msg}")
        sys.exit(1)
