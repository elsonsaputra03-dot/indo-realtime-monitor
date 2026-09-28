"""
Runner generik untuk producer polling:
fetch() -> list[dict] -> dedup (seen-cache) -> Kafka topic + heartbeat ops.ingest_run.
Producer baru cukup menulis fungsi fetch dan memanggil run_source().
"""
import logging
import time
from collections import OrderedDict
from typing import Callable

import httpx

from common import kafka_producer, send, utcnow_iso

RUN_TOPIC = "ops.ingest_run"
USER_AGENT = "indo-realtime-monitor/0.2 (portfolio project)"


class SeenCache:
    def __init__(self, maxsize: int = 20000):
        self._d: OrderedDict[str, None] = OrderedDict()
        self.maxsize = maxsize

    def add_if_new(self, key: str) -> bool:
        if key in self._d:
            self._d.move_to_end(key)
            return False
        self._d[key] = None
        if len(self._d) > self.maxsize:
            self._d.popitem(last=False)
        return True


def http_client() -> httpx.Client:
    return httpx.Client(
        transport=httpx.HTTPTransport(retries=3),
        timeout=30,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )


def run_source(name: str, topic: str, fetch: Callable[[httpx.Client], list[dict]],
               key: Callable[[dict], str], poll_seconds: int) -> None:
    log = logging.getLogger(f"producer.{name}")
    producer = kafka_producer()
    seen = SeenCache()
    with http_client() as client:
        while True:
            t0 = time.monotonic()
            run = {"source": name, "run_at": utcnow_iso(), "status": "ok",
                   "fetched": 0, "new_records": 0, "latency_ms": 0, "error": ""}
            try:
                records = fetch(client)
                run["fetched"] = len(records)
                ingested_at = utcnow_iso()
                for rec in records:
                    k = key(rec)
                    if seen.add_if_new(k):
                        send(producer, topic, k, {**rec, "ingested_at": ingested_at})
                        run["new_records"] += 1
            except Exception as exc:  # noqa: BLE001
                run["status"] = "error"
                run["error"] = f"{type(exc).__name__}: {exc}"[:500]
                log.error("fetch gagal: %s", run["error"])
            run["latency_ms"] = int((time.monotonic() - t0) * 1000)
            send(producer, RUN_TOPIC, name, run)
            producer.flush(10)
            log.info("%s status=%s fetched=%d new=%d %dms", name, run["status"],
                     run["fetched"], run["new_records"], run["latency_ms"])
            time.sleep(poll_seconds)
