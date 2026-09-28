"""
DAG news_ingest: setiap 15 menit ambil RSS berita (Google News per topik + portal nasional),
klasifikasi topik rule-based, dedup terhadap ClickHouse, publish ke Kafka raw.news,
dan kirim heartbeat ke ops.ingest_run (dipakai DQ & dashboard Pipeline Ops).

Task graph: load_seen ─┐
            fetch_feed (dynamic mapping, 1 task per feed) ─┴─> publish
"""
from datetime import datetime, timedelta, timezone

from airflow.decorators import dag, task

from news_lib import FEEDS, ch_client, dumps, fetch_feed, kafka_config

SOURCE = "news"


@dag(
    dag_id="news_ingest",
    schedule="*/15 * * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=2)},
    tags=["ingest", "scraper", "news"],
    doc_md=__doc__,
)
def news_ingest():

    @task
    def load_seen() -> list[str]:
        try:
            rows = ch_client().query(
                "SELECT DISTINCT news_id FROM news WHERE ingested_at >= now() - INTERVAL 3 DAY").result_rows
            return [r[0] for r in rows]
        except Exception as exc:  # noqa: BLE001 - tabel belum ada / CH belum siap: lanjut tanpa dedup awal
            print(f"load_seen gagal: {exc}")
            return []

    @task(max_active_tis_per_dagrun=3)       # rate limit: maksimal 3 feed paralel
    def fetch(feed: dict) -> dict:
        res = fetch_feed(feed)
        print(f"{res['feed']}: {res['status']} items={len(res['items'])} {res['ms']}ms {res['error']}")
        return res

    @task
    def publish(results: list[dict], seen: list[str]) -> dict:
        from confluent_kafka import Producer

        seen_set, new, fetched = set(seen), 0, 0
        producer = Producer(kafka_config())
        ingested_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        for res in results:
            fetched += len(res["items"])
            for item in res["items"]:
                if item["news_id"] in seen_set:
                    continue
                seen_set.add(item["news_id"])
                producer.produce("raw.news", key=item["news_id"], value=dumps({**item, "ingested_at": ingested_at}))
                new += 1
        failed = [f"{r['feed']}({r['status']})" for r in results if r["status"] != "ok"]
        ok_feeds = len(results) - len(failed)
        run = {
            "source": SOURCE, "run_at": ingested_at,
            "status": "ok" if ok_feeds > 0 else "error",
            "fetched": fetched, "new_records": new,
            "latency_ms": max((r["ms"] for r in results), default=0),
            "error": ("tidak berhasil: " + ", ".join(failed))[:500] if failed else "",
        }
        producer.produce("ops.ingest_run", key=SOURCE, value=dumps(run))
        producer.flush(15)
        print(f"news: feeds_ok={ok_feeds}/{len(results)} fetched={fetched} new={new} failed={failed}")
        return run

    publish(fetch.expand(feed=FEEDS), load_seen())


news_ingest()
