-- Fase 3a: berita (RSS) dari Airflow DAG news_ingest
CREATE TABLE IF NOT EXISTS irm.news
(
    news_id      String,
    feed         LowCardinality(String),
    publisher    String,
    title        String,
    link         String,
    summary      String,
    published_at DateTime('UTC'),
    topics       Array(LowCardinality(String)),
    ingested_at  DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(published_at)
ORDER BY (news_id)
TTL published_at + INTERVAL 1 YEAR;

CREATE TABLE IF NOT EXISTS irm.kafka_news
(
    news_id String, feed String, publisher String, title String, link String, summary String,
    published_at String, topics Array(String), ingested_at String
)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'redpanda:9092',
         kafka_topic_list = 'raw.news',
         kafka_group_name = 'ch_news',
         kafka_format = 'JSONEachRow',
         kafka_skip_broken_messages = 100;

CREATE MATERIALIZED VIEW IF NOT EXISTS irm.mv_news TO irm.news AS
SELECT news_id, feed, publisher, title, link, summary,
       toDateTime(parseDateTimeBestEffort(published_at), 'UTC') AS published_at,
       topics,
       parseDateTime64BestEffort(ingested_at, 3, 'UTC') AS ingested_at
FROM irm.kafka_news;
