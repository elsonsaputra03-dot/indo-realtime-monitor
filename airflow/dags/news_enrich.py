"""
DAG news_enrich: berita yang belum di-enrich -> LLM lokal (Ollama) -> topik, ringkasan, lokasi
-> geotag ke kab/kota/provinsi via gazetteer -> Kafka raw.news_enriched + heartbeat ops.ingest_run.

Jadwal: menit 5,20,35,50 (5 menit setelah news_ingest). Batch maks 40 berita per run, sekuensial
(1 GPU). Bila Ollama/model belum siap, run tetap sukses tapi heartbeat berstatus error (terlihat di DQ).
"""
from datetime import datetime, timedelta, timezone

from airflow.decorators import dag, task

SOURCE = "llm_enrich"
BATCH = 40


@dag(
    dag_id="news_enrich",
    schedule="5-59/15 * * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 0},
    tags=["llm", "enrich", "geotag"],
    doc_md=__doc__,
)
def news_enrich():

    @task
    def enrich_batch() -> dict:
        import httpx
        from confluent_kafka import Producer

        from llm_lib import LLM_MODEL, enrich, ollama_ready
        from news_lib import ch_client, dumps, kafka_config

        t0 = datetime.now(timezone.utc)
        producer = Producer(kafka_config())
        run = {"source": SOURCE, "run_at": t0.isoformat(timespec="milliseconds"), "status": "ok",
               "fetched": 0, "new_records": 0, "latency_ms": 0, "error": ""}
        with httpx.Client(timeout=httpx.Timeout(20, read=180)) as client:
            ready, msg = ollama_ready(client, LLM_MODEL)
            if not ready:
                run.update(status="error", error=msg)
            else:
                rows = ch_client().query(
                    """
                    SELECT n.news_id, n.title, n.summary, toString(n.published_at), n.topics
                    FROM news AS n FINAL
                    WHERE n.ingested_at >= now() - INTERVAL 3 DAY
                      -- belum pernah sukses; yang gagal dicoba ulang paling cepat 1 jam kemudian
                      AND n.news_id NOT IN (SELECT news_id FROM news_enriched
                                            WHERE model = {m:String}
                                              AND (status = 'ok' OR enriched_at >= now() - INTERVAL 1 HOUR))
                    ORDER BY n.published_at DESC
                    LIMIT {b:UInt32}
                    """, parameters={"m": LLM_MODEL, "b": BATCH}).result_rows
                run["fetched"] = len(rows)
                errors, geo_ok, lat = 0, 0, []
                enriched_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
                for nid, title, summary, pub, topics in rows:
                    e = enrich(client, {"news_id": nid, "title": title, "summary": summary,
                                        "published_at": pub.replace(" ", "T") + "Z", "topics": list(topics)})
                    errors += e["status"] != "ok"
                    geo_ok += bool(e["kode_wilayah"])
                    lat.append(e["latency_ms"])
                    producer.produce("raw.news_enriched", key=nid, value=dumps({**e, "enriched_at": enriched_at}))
                run["new_records"] = len(rows) - errors
                run["latency_ms"] = int(sum(lat) / len(lat)) if lat else 0
                if rows and errors == len(rows):
                    run["status"] = "error"
                if errors:
                    run["error"] = f"{errors}/{len(rows)} berita gagal diproses LLM"
                print(f"enrich: {len(rows)} berita, gagal={errors}, ter-geotag={geo_ok}, avg={run['latency_ms']}ms")
        producer.produce("ops.ingest_run", key=SOURCE, value=dumps(run))
        producer.flush(15)
        return run

    enrich_batch()


news_enrich()
