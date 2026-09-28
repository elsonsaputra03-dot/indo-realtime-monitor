"""
Evaluasi LLM yang jujur untuk README: label manual pada berita BARU yang belum pernah dipakai saat pengembangan.

1) Export sampel (butuh stack lokal jalan + news_enriched terisi):
     PYTHONPATH=airflow/dags python scripts/eval_llm.py export --n 50 --since 2026-10-01
   -> docs/eval/labels.csv. Isi kolom gold_topics dan gold_wilayah secara MANUAL tanpa melihat kolom pred_*
      (sembunyikan kolom pred_* di spreadsheet saat memberi label).
        gold_topics : topik dipisah ';' dari: gempa, banjir_longsor, kebakaran, gunung_api, cuaca, kualitas_udara, pangan, lainnya
        gold_wilayah: nama/kode kab-kota atau provinsi lokasi kejadian utama; '-' bila tidak ada lokasi Indonesia

2) Hitung skor:
     PYTHONPATH=airflow/dags python scripts/eval_llm.py score
   -> docs/eval/RESULTS.md (angka ini yang boleh dikutip di README / CV).
"""
import argparse
import csv
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, "airflow/dags")
os.environ.setdefault("GAZETTEER_CSV", "reference/wilayah_indonesia.csv")
import llm_lib  # noqa: E402

LABELS = "docs/eval/labels.csv"
RESULTS = "docs/eval/RESULTS.md"
FIELDS = ["news_id", "published_at", "title", "summary", "gold_topics", "gold_wilayah", "catatan",
          "pred_topics", "pred_wilayah", "pred_kode", "pred_method", "model"]


def ch():
    import clickhouse_connect
    return clickhouse_connect.get_client(host=os.getenv("CLICKHOUSE_HOST", "localhost"), port=8123,
                                         username=os.getenv("CLICKHOUSE_USER", "irm"),
                                         password=os.getenv("CLICKHOUSE_PASSWORD", ""), database="irm")


def export(n: int, since: str) -> None:
    rows = ch().query(
        """
        SELECT n.news_id, toString(n.published_at), n.title, n.summary,
               arrayStringConcat(e.topics_llm, ';'), e.nama_wilayah, e.kode_wilayah, e.geo_method, e.model
        FROM news AS n FINAL
        INNER JOIN (SELECT * FROM news_enriched FINAL WHERE status = 'ok'
                    ORDER BY enriched_at DESC LIMIT 1 BY news_id) AS e ON e.news_id = n.news_id
        WHERE n.published_at >= parseDateTimeBestEffort({s:String})
        ORDER BY cityHash64(n.news_id)          -- urutan acak tapi stabil, bukan yang terbaru saja
        LIMIT {n:UInt32}
        """, parameters={"s": since, "n": n}).result_rows
    os.makedirs(os.path.dirname(LABELS), exist_ok=True)
    with open(LABELS, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({"news_id": r[0], "published_at": r[1], "title": r[2], "summary": r[3], "gold_topics": "",
                        "gold_wilayah": "", "catatan": "", "pred_topics": r[4], "pred_wilayah": r[5],
                        "pred_kode": r[6], "pred_method": r[7], "model": r[8]})
    print(f"{len(rows)} berita diekspor ke {LABELS}. Isi gold_topics & gold_wilayah secara manual.")


def gold_kode(value: str) -> str | None:
    v = value.strip()
    if v in ("", "-"):
        return None
    if all(c.isdigit() or c == "." for c in v):
        return v
    hit = llm_lib.resolve([v], v, primary=v)
    return hit["kode"] if hit else f"?{v}"


def score() -> None:
    rows = [r for r in csv.DictReader(open(LABELS, encoding="utf-8")) if r["gold_topics"].strip()]
    if not rows:
        sys.exit("Belum ada baris berlabel (gold_topics kosong semua).")
    tp = fp = fn = exact = 0
    geo_ok = geo_prov = geo_none_ok = geo_n = geo_none_n = 0
    errors = []
    for r in rows:
        gold = {t.strip() for t in r["gold_topics"].split(";") if t.strip()}
        pred = {t.strip() for t in r["pred_topics"].split(";") if t.strip()}
        tp += len(gold & pred); fp += len(pred - gold); fn += len(gold - pred)
        exact += gold == pred
        g, p = gold_kode(r["gold_wilayah"]), (r["pred_kode"].strip() or None)
        if g is None:
            geo_none_n += 1
            geo_none_ok += p is None
            if p is not None:
                errors.append(f"- lokasi palsu: \"{r['title'][:90]}\" → {r['pred_wilayah']}")
        else:
            geo_n += 1
            if p == g:
                geo_ok += 1
            elif p and p.split(".")[0] == g.split(".")[0]:
                geo_prov += 1
                errors.append(f"- provinsi benar, wilayah beda: \"{r['title'][:80]}\" → {r['pred_wilayah']} (gold: {r['gold_wilayah']})")
            else:
                errors.append(f"- salah/terlewat: \"{r['title'][:80]}\" → {r['pred_wilayah'] or '-'} (gold: {r['gold_wilayah']})")
    prec = tp / (tp + fp) if tp + fp else 0
    rec = tp / (tp + fn) if tp + fn else 0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0
    model = rows[0]["model"]
    pct = lambda a, b: f"{a / b * 100:.0f}% ({a}/{b})" if b else "n/a"
    md = f"""# LLM evaluation

Model: `{model}` · labeled articles: **{len(rows)}** · generated {datetime.now(timezone.utc):%Y-%m-%d}

Articles were sampled from news published after the development period and labeled manually without looking at predictions.

| Metric | Result |
|---|---|
| Topic precision (micro) | {prec * 100:.0f}% |
| Topic recall (micro) | {rec * 100:.0f}% |
| Topic F1 (micro) | {f1 * 100:.0f}% |
| Exact topic set match | {pct(exact, len(rows))} |
| Location: exact regency/province | {pct(geo_ok, geo_n)} |
| Location: correct province only | {pct(geo_prov, geo_n)} |
| No-location articles left untagged (no false pins) | {pct(geo_none_ok, geo_none_n)} |

## Errors
{chr(10).join(errors) if errors else "- none"}
"""
    open(RESULTS, "w", encoding="utf-8").write(md)
    print(md)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--n", type=int, default=50)
    e.add_argument("--since", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    sub.add_parser("score")
    a = ap.parse_args()
    export(a.n, a.since) if a.cmd == "export" else score()
