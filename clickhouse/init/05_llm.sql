-- Fase 4: hasil enrichment LLM + geotagging berita
CREATE TABLE IF NOT EXISTS irm.news_enriched
(
    news_id        String,
    model          LowCardinality(String),
    status         LowCardinality(String),       -- ok | error (error: hanya rule-based geotag)
    error          String,
    published_at   DateTime('UTC'),
    topics_llm     Array(LowCardinality(String)),
    summary_llm    String,
    locations_raw  Array(String),
    location_main  String,
    geo_method     LowCardinality(String),       -- llm | rule | none
    kode_wilayah   String,                        -- kode Kemendagri, mis. 62.02
    nama_wilayah   String,
    level_wilayah  UInt8,                         -- 1 provinsi, 2 kab/kota, 0 tidak ada
    prov_kode      LowCardinality(String),
    prov_nama      LowCardinality(String),
    lat            Float64,
    lng            Float64,
    geo_ambiguous  Bool,
    latency_ms     UInt32,
    enriched_at    DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(enriched_at)
PARTITION BY toYYYYMM(published_at)
ORDER BY (news_id, model)
TTL published_at + INTERVAL 1 YEAR;

CREATE TABLE IF NOT EXISTS irm.kafka_news_enriched
(
    news_id String, model String, status String, error String, published_at String,
    topics_llm Array(String), summary_llm String, locations_raw Array(String), location_main String,
    geo_method String, kode_wilayah String, nama_wilayah String, level_wilayah UInt8,
    prov_kode String, prov_nama String, lat Float64, lng Float64, geo_ambiguous Bool,
    latency_ms UInt32, enriched_at String
)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'redpanda:9092',
         kafka_topic_list = 'raw.news_enriched',
         kafka_group_name = 'ch_news_enriched',
         kafka_format = 'JSONEachRow',
         kafka_skip_broken_messages = 100;

CREATE MATERIALIZED VIEW IF NOT EXISTS irm.mv_news_enriched TO irm.news_enriched AS
SELECT news_id, model, status, error,
       toDateTime(parseDateTimeBestEffort(published_at), 'UTC') AS published_at,
       topics_llm, summary_llm, locations_raw, location_main, geo_method, kode_wilayah, nama_wilayah,
       level_wilayah, prov_kode, prov_nama, lat, lng, geo_ambiguous, latency_ms,
       parseDateTime64BestEffort(enriched_at, 3, 'UTC') AS enriched_at
FROM irm.kafka_news_enriched;
