"""
Alert email bersama untuk GitHub Actions (snapshot per jam) dan stack lokal (DQ loop).

Prinsip:
- Kirim hanya saat STATUS BERUBAH: masalah baru (open) dan pulih (resolve). Tidak ada email berulang tiap run.
- Satu email per run berisi semua perubahan.
- Email tidak dikonfigurasi -> dilewati dengan log, tidak pernah menggagalkan pipeline.

Konfigurasi (env / GitHub secrets):
  SMTP_USER, SMTP_PASSWORD (Gmail App Password 16 karakter), ALERT_EMAIL_TO (koma untuk >1 penerima)
  opsional: SMTP_HOST (default smtp.gmail.com), SMTP_PORT (default 465, SSL), ALERT_EMAIL_FROM
"""
import json
import logging
import os
import smtplib
import socket
import ssl
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

log = logging.getLogger("alerting")


def email_configured() -> bool:
    return all(os.getenv(k, "").strip() for k in ("SMTP_USER", "SMTP_PASSWORD", "ALERT_EMAIL_TO"))


@contextmanager
def _ipv4_only():
    """Container Docker di WSL sering tanpa rute IPv6: 'Network is unreachable' saat DNS memberi alamat IPv6.
    Paksa resolusi IPv4 selama koneksi SMTP (nama host tetap dipakai untuk verifikasi sertifikat TLS)."""
    if os.getenv("SMTP_FORCE_IPV4", "1") != "1":
        yield
        return
    orig = socket.getaddrinfo

    def v4(host, port, family=0, *args, **kwargs):
        return orig(host, port, socket.AF_INET, *args, **kwargs)
    socket.getaddrinfo = v4
    try:
        yield
    finally:
        socket.getaddrinfo = orig


def send_email(subject: str, body: str) -> bool:
    if not email_configured():
        log.info("email alert tidak dikonfigurasi; dilewati: %s", subject)
        return False
    user, pwd = os.environ["SMTP_USER"].strip(), os.environ["SMTP_PASSWORD"].replace(" ", "").strip()
    to = [x.strip() for x in os.environ["ALERT_EMAIL_TO"].split(",") if x.strip()]
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, os.getenv("ALERT_EMAIL_FROM", user), ", ".join(to)
    msg.set_content(body)
    host, port = os.getenv("SMTP_HOST", "smtp.gmail.com"), int(os.getenv("SMTP_PORT", "465"))
    ctx = ssl.create_default_context()
    try:
        with _ipv4_only():
            return _send(host, port, ctx, user, pwd, msg, to, subject)
    except Exception as exc:  # noqa: BLE001 - alert gagal tidak boleh menjatuhkan pipeline
        # pesan error jaringan/SMTP tidak memuat password; aman ditampilkan
        log.warning("email alert gagal via %s:%d (%s: %s): %s", host, port, type(exc).__name__,
                    str(exc)[:200], subject)
        return False


def _send(host, port, ctx, user, pwd, msg, to, subject) -> bool:
    if port == 465:                                       # SSL langsung
        conn = smtplib.SMTP_SSL(host, port, context=ctx, timeout=20)
    else:                                                 # 587: plain lalu STARTTLS
        conn = smtplib.SMTP(host, port, timeout=20)
        conn.ehlo()
        conn.starttls(context=ctx)
        conn.ehlo()
    with conn as s:
        s.login(user, pwd)
        s.send_message(msg)
    log.info("email alert terkirim ke %d penerima: %s", len(to), subject)
    return True


class AlertState:
    """Status alert persisten (file JSON). key -> {active, streak, since, title, detail, last_seen}."""

    def __init__(self, path: str):
        self.path = path
        try:
            self.data = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        self.events: list[dict] = []

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)

    def is_active(self, key: str) -> bool:
        return bool(self.data.get(key, {}).get("active"))

    def update(self, key: str, failing: bool, title: str, detail: str = "", open_after: int = 1,
               now: datetime | None = None) -> str | None:
        """Kondisi berkelanjutan. Buka alert setelah `open_after` run gagal berturut-turut; tutup saat pulih."""
        now = now or datetime.now(timezone.utc)
        st = self.data.setdefault(key, {"active": False, "streak": 0})
        st["last_seen"] = now.isoformat(timespec="seconds")
        if failing:
            st["streak"] = st.get("streak", 0) + 1
            st["detail"] = detail
            if not st["active"] and st["streak"] >= open_after:
                st.update(active=True, since=now.isoformat(timespec="seconds"), title=title)
                self.events.append({"type": "open", "key": key, "title": title, "detail": detail})
                return "open"
            return None
        was = st["active"]
        st.update(active=False, streak=0)
        if was:
            self.events.append({"type": "resolve", "key": key, "title": st.get("title", title),
                                "detail": f"pulih; bermasalah sejak {st.get('since', '?')}"})
            return "resolve"
        return None

    def once(self, key: str, title: str, detail: str = "", now: datetime | None = None) -> bool:
        """Kejadian sekali (mis. gempa besar): kirim sekali per key."""
        now = now or datetime.now(timezone.utc)
        if key in self.data:
            return False
        self.data[key] = {"once": True, "at": now.isoformat(timespec="seconds"), "title": title}
        self.events.append({"type": "event", "key": key, "title": title, "detail": detail})
        return True

    def prune(self, days: int = 14, now: datetime | None = None) -> None:
        """Buang entri lama yang tidak aktif supaya file state tidak membengkak."""
        cutoff = ((now or datetime.now(timezone.utc)) - timedelta(days=days)).isoformat()
        self.data = {k: v for k, v in self.data.items()
                     if k == "_pending" or v.get("active") or (v.get("at") or v.get("last_seen") or "9999") >= cutoff}

    def flush(self, origin: str, footer: str = "") -> bool:
        """Kirim satu email berisi semua perubahan run ini (bila ada)."""
        pending = self.data.pop("_pending", [])          # event yang gagal terkirim di run sebelumnya
        self.events = pending + self.events
        if not self.events:
            return False
        opened = [e for e in self.events if e["type"] in ("open", "event")]
        resolved = [e for e in self.events if e["type"] == "resolve"]
        parts = []
        if opened:
            parts.append(f"{len(opened)} masalah/kejadian baru")
        if resolved:
            parts.append(f"{len(resolved)} pulih")
        subject = f"[IRM {origin}] " + ", ".join(parts)
        lines = [f"Indonesia Realtime Monitor · {origin} · {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC", ""]
        for label, items in (("BARU", opened), ("PULIH", resolved)):
            if items:
                lines.append(f"{label}:")
                lines += [f"  - {e['title']}" + (f"\n      {e['detail']}" if e.get("detail") else "") for e in items]
                lines.append("")
        if footer:
            lines.append(footer)
        sent = send_email(subject, "\n".join(lines))
        if not sent and email_configured():
            self.data["_pending"] = self.events[-50:]      # SMTP error: coba kirim lagi di run berikutnya
        self.events = []
        return sent
