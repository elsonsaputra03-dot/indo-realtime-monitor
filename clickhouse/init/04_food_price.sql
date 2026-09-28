-- Fase 3b: harga pangan harian per provinsi (PIHPS Nasional, Bank Indonesia)
CREATE TABLE IF NOT EXISTS irm.food_prices
(
    price_date    Date,
    prov_id       UInt16,
    province      LowCardinality(String),
    commodity_id  UInt8,
    commodity     LowCardinality(String),
    price         Float64,          -- Rp per kg/liter (sesuai satuan PIHPS)
    national_avg  Float64,
    pct_change    Float32,          -- % vs prev_date
    prev_date     Date,
    price_group   UInt8,            -- 'Kelompok' dari PIHPS (kategori sebaran harga)
    ingested_at   DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(price_date)
ORDER BY (commodity_id, prov_id, price_date)
TTL price_date + INTERVAL 5 YEAR;

CREATE TABLE IF NOT EXISTS irm.kafka_food_price
(
    price_date String, prov_id UInt16, province String, commodity_id UInt8, commodity String,
    price Float64, national_avg Float64, pct_change Float32, prev_date String, price_group UInt8,
    ingested_at String
)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'redpanda:9092',
         kafka_topic_list = 'raw.food_price',
         kafka_group_name = 'ch_food_price',
         kafka_format = 'JSONEachRow',
         kafka_skip_broken_messages = 100;

CREATE MATERIALIZED VIEW IF NOT EXISTS irm.mv_food_price TO irm.food_prices AS
SELECT toDate(price_date) AS price_date, prov_id, province, commodity_id, commodity,
       price, national_avg, pct_change, toDate(prev_date) AS prev_date, price_group,
       parseDateTime64BestEffort(ingested_at, 3, 'UTC') AS ingested_at
FROM irm.kafka_food_price;
