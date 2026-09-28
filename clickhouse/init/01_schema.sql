-- Dijalankan otomatis saat container ClickHouse pertama kali start.
-- Database `irm` dibuat oleh env CLICKHOUSE_DB.

-- ============ EVENT TABLE (serving) ============
CREATE TABLE IF NOT EXISTS irm.earthquake_events
(
    event_id     String,
    source       LowCardinality(String),      -- bmkg | usgs
    event_time   DateTime64(3, 'UTC'),
    lat          Float64,
    lon          Float64,
    magnitude    Float32,
    depth_km     Float32,
    region       String,
    felt         String,
    ingested_at  DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(event_time)
ORDER BY (source, event_id)
TTL toDateTime(event_time) + INTERVAL 2 YEAR;

-- ============ KAFKA INGEST ============
CREATE TABLE IF NOT EXISTS irm.kafka_earthquake
(
    event_id String, source String, event_time String,
    lat Float64, lon Float64, magnitude Float32, depth_km Float32,
    region String, felt String, ingested_at String
)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'redpanda:9092',
         kafka_topic_list = 'raw.earthquake',
         kafka_group_name = 'ch_earthquake',
         kafka_format = 'JSONEachRow',
         kafka_skip_broken_messages = 100;

CREATE MATERIALIZED VIEW IF NOT EXISTS irm.mv_earthquake TO irm.earthquake_events AS
SELECT
    event_id, source,
    parseDateTime64BestEffort(event_time, 3, 'UTC')  AS event_time,
    lat, lon, magnitude, depth_km, region, felt,
    parseDateTime64BestEffort(ingested_at, 3, 'UTC') AS ingested_at
FROM irm.kafka_earthquake;

-- ============ INGEST RUN LOG (monitoring) ============
CREATE TABLE IF NOT EXISTS irm.ingest_runs
(
    source      LowCardinality(String),
    run_at      DateTime64(3, 'UTC'),
    status      LowCardinality(String),        -- ok | error
    fetched     UInt32,
    new_records UInt32,
    latency_ms  UInt32,
    error       String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(run_at)
ORDER BY (source, run_at)
TTL toDateTime(run_at) + INTERVAL 90 DAY;

CREATE TABLE IF NOT EXISTS irm.kafka_ingest_run
(
    source String, run_at String, status String,
    fetched UInt32, new_records UInt32, latency_ms UInt32, error String
)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'redpanda:9092',
         kafka_topic_list = 'ops.ingest_run',
         kafka_group_name = 'ch_ingest_run',
         kafka_format = 'JSONEachRow',
         kafka_skip_broken_messages = 100;

CREATE MATERIALIZED VIEW IF NOT EXISTS irm.mv_ingest_run TO irm.ingest_runs AS
SELECT source, parseDateTime64BestEffort(run_at, 3, 'UTC') AS run_at, status,
       fetched, new_records, latency_ms, error
FROM irm.kafka_ingest_run;

-- ============ DATA QUALITY RESULTS ============
CREATE TABLE IF NOT EXISTS irm.dq_results
(
    checked_at  DateTime64(3, 'UTC'),
    source      LowCardinality(String),
    check_name  LowCardinality(String),
    status      LowCardinality(String),        -- pass | warn | fail
    value       Float64,
    threshold   Float64,
    detail      String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(checked_at)
ORDER BY (source, check_name, checked_at)
TTL toDateTime(checked_at) + INTERVAL 90 DAY;
