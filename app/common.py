"""Shared helpers: config, Kafka producer, ClickHouse client, logging."""
import json
import logging
import os
from datetime import datetime, timezone

import clickhouse_connect
from confluent_kafka import Producer

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def kafka_producer() -> Producer:
    return Producer({
        "bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP", "redpanda:9092"),
        "enable.idempotence": True,
        "compression.type": "zstd",
        "linger.ms": 50,
    })


def send(producer: Producer, topic: str, key: str | None, value: dict) -> None:
    producer.produce(topic, key=key, value=json.dumps(value, ensure_ascii=False))
    producer.poll(0)


def ch_client():
    return clickhouse_connect.get_client(
        host=os.getenv("CLICKHOUSE_HOST", "clickhouse"),
        port=int(os.getenv("CLICKHOUSE_PORT", "8123")),
        username=os.getenv("CLICKHOUSE_USER", "default"),
        password=os.getenv("CLICKHOUSE_PASSWORD", ""),
        database=os.getenv("CLICKHOUSE_DB", "irm"),
    )
