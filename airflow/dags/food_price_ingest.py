"""
DAG food_price_ingest: harga pangan harian per provinsi dari PIHPS Nasional (Bank Indonesia).

- Jadwal 07:00 dan 11:00 UTC (14:00 & 18:00 WIB) supaya data hari itu sudah terupdate.
- 10 kelompok komoditas -> dynamic task mapping (maks 2 paralel, jeda 3 detik per request).
- Backfill: Trigger DAG w/ config {"days_back": 30}. Default 1 (hari ini, WIB).
- Idempotent: key (commodity_id, prov_id, price_date) di ReplacingMergeTree.
"""
from datetime import datetime, timedelta, timezone

from airflow.decorators import dag, task
from airflow.models.param import Param

from news_lib import dumps, kafka_config
from pihps_lib import COMMODITIES, fetch_commodity

SOURCE = "pihps"
WIB = timezone(timedelta(hours=7))


@dag(
    dag_id="food_price_ingest",
    schedule="0 7,11 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    params={"days_back": Param(1, type="integer", minimum=1, maximum=60)},
    default_args={"retries": 1, "retry_delay": timedelta(minutes=5)},
    tags=["ingest", "scraper", "food-price"],
    doc_md=__doc__,
)
def food_price_ingest():

    @task
    def target_dates(**context) -> list[str]:
        n = int(context["params"]["days_back"])
        today = datetime.now(WIB).date()
        return [(today - timedelta(days=i)).isoformat() for i in range(n)]

    @task(max_active_tis_per_dagrun=2)
    def fetch(commodity_id: int, dates: list[str]) -> dict:
        from datetime import date
        res = fetch_commodity(commodity_id, [date.fromisoformat(d) for d in dates])
        print(f"commodity {commodity_id}: {res['status']} rows={len(res['items'])} {res['ms']}ms {res['error']}")
        return res

    @task
    def publish(results: list[dict]) -> dict:
        from confluent_kafka import Producer

        producer = Producer(kafka_config())
        ingested_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        fetched = 0
        for res in results:
            for item in res["items"]:
                key = f"{item['commodity_id']}|{item['prov_id']}|{item['price_date']}"
                producer.produce("raw.food_price", key=key, value=dumps({**item, "ingested_at": ingested_at}))
                fetched += 1
        failed = [str(r["commodity_id"]) for r in results if r["status"] != "ok"]
        run = {
            "source": SOURCE, "run_at": ingested_at,
            "status": "ok" if len(failed) < len(results) else "error",
            "fetched": fetched, "new_records": fetched,   # upsert idempotent; dedup di ClickHouse
            "latency_ms": max((r["ms"] for r in results), default=0),
            "error": ("komoditas gagal: " + ", ".join(failed))[:500] if failed else "",
        }
        producer.produce("ops.ingest_run", key=SOURCE, value=dumps(run))
        producer.flush(15)
        print(f"pihps: rows={fetched} failed={failed}")
        return run

    dates = target_dates()
    publish(fetch.partial(dates=dates).expand(commodity_id=list(COMMODITIES)))


food_price_ingest()
