-- Fase 2: hotspot (NASA FIRMS) + kualitas udara (Open-Meteo)
-- Volume ClickHouse yang sudah ada: jalankan `make migrate` (init script hanya otomatis saat volume kosong).

-- ============ HOTSPOT ============
CREATE TABLE IF NOT EXISTS irm.hotspots
(
    event_id     String,
    sensor       LowCardinality(String),
    satellite    LowCardinality(String),
    acq_time     DateTime('UTC'),
    lat          Float64,
    lon          Float64,
    confidence   LowCardinality(String),   -- VIIRS: l/n/h
    frp          Float32,                  -- fire radiative power (MW)
    brightness   Float32,
    daynight     LowCardinality(String),
    ingested_at  DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(acq_time)
ORDER BY (event_id)
TTL acq_time + INTERVAL 1 YEAR;

CREATE TABLE IF NOT EXISTS irm.kafka_hotspot
(
    event_id String, sensor String, satellite String, acq_time String,
    lat Float64, lon Float64, confidence String, frp Float32, brightness Float32,
    daynight String, ingested_at String
)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'redpanda:9092',
         kafka_topic_list = 'raw.hotspot',
         kafka_group_name = 'ch_hotspot',
         kafka_format = 'JSONEachRow',
         kafka_skip_broken_messages = 100;

CREATE MATERIALIZED VIEW IF NOT EXISTS irm.mv_hotspot TO irm.hotspots AS
SELECT event_id, sensor, satellite,
       toDateTime(parseDateTimeBestEffort(acq_time), 'UTC') AS acq_time,
       lat, lon, confidence, frp, brightness, daynight,
       parseDateTime64BestEffort(ingested_at, 3, 'UTC') AS ingested_at
FROM irm.kafka_hotspot;

-- ============ AIR QUALITY ============
CREATE TABLE IF NOT EXISTS irm.air_quality
(
    city         LowCardinality(String),
    province     LowCardinality(String),
    lat          Float64,
    lon          Float64,
    obs_time     DateTime('UTC'),
    pm2_5        Float32,
    pm10         Float32,
    no2          Float32,
    o3           Float32,
    co           Float32,
    us_aqi       Float32,
    ingested_at  DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(obs_time)
ORDER BY (city, obs_time)
TTL obs_time + INTERVAL 2 YEAR;

CREATE TABLE IF NOT EXISTS irm.kafka_air_quality
(
    city String, province String, lat Float64, lon Float64, obs_time String,
    pm2_5 Float32, pm10 Float32, no2 Float32, o3 Float32, co Float32, us_aqi Float32,
    ingested_at String
)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'redpanda:9092',
         kafka_topic_list = 'raw.air_quality',
         kafka_group_name = 'ch_air_quality',
         kafka_format = 'JSONEachRow',
         kafka_skip_broken_messages = 100;

CREATE MATERIALIZED VIEW IF NOT EXISTS irm.mv_air_quality TO irm.air_quality AS
SELECT city, province, lat, lon,
       toDateTime(parseDateTimeBestEffort(obs_time), 'UTC') AS obs_time,
       pm2_5, pm10, no2, o3, co, us_aqi,
       parseDateTime64BestEffort(ingested_at, 3, 'UTC') AS ingested_at
FROM irm.kafka_air_quality;
