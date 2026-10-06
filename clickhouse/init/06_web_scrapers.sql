-- Sumber web baru: tabel tujuan (ReplacingMergeTree, idempoten) + Kafka engine + materialized view, pola yang sama
-- dengan food_prices. BMKG wajib dicantumkan sebagai sumber data cuaca di setiap tampilan.

CREATE TABLE IF NOT EXISTS irm.weather_forecast (
    adm4 String, desa String, kecamatan String, kotkab LowCardinality(String), provinsi LowCardinality(String),
    lat Float64, lon Float64, forecast_utc DateTime('UTC'), local_datetime String,
    t Float32, hu Float32, tcc Float32, tp Float32, ws Float32, wd LowCardinality(String),
    weather_code UInt16, weather_desc LowCardinality(String), vs UInt32, analysis_date DateTime('UTC'),
    ingested_at DateTime64(3, 'UTC')
) ENGINE = ReplacingMergeTree(ingested_at) ORDER BY (adm4, forecast_utc);

CREATE TABLE IF NOT EXISTS irm.kafka_weather_forecast (
    adm4 String, desa String, kecamatan String, kotkab String, provinsi String, lat Float64, lon Float64,
    forecast_utc String, local_datetime String, t Float32, hu Float32, tcc Float32, tp Float32, ws Float32, wd String,
    weather_code UInt16, weather_desc String, vs UInt32, analysis_date String, ingested_at String
) ENGINE = Kafka SETTINGS kafka_broker_list = 'redpanda:9092', kafka_topic_list = 'raw.weather_forecast',
    kafka_group_name = 'ch_weather_forecast', kafka_format = 'JSONEachRow', kafka_skip_broken_messages = 100;

CREATE MATERIALIZED VIEW IF NOT EXISTS irm.mv_weather_forecast TO irm.weather_forecast AS
SELECT adm4, desa, kecamatan, kotkab, provinsi, lat, lon, parseDateTimeBestEffort(forecast_utc, 'UTC') AS forecast_utc,
       local_datetime, t, hu, tcc, tp, ws, wd, weather_code, weather_desc, vs,
       parseDateTimeBestEffortOrZero(analysis_date, 'UTC') AS analysis_date,
       parseDateTime64BestEffort(ingested_at, 3, 'UTC') AS ingested_at
FROM irm.kafka_weather_forecast;

CREATE TABLE IF NOT EXISTS irm.github_lang_daily (
    day Date, language LowCardinality(String), new_repos UInt32, incomplete UInt8, ingested_at DateTime64(3, 'UTC')
) ENGINE = ReplacingMergeTree(ingested_at) ORDER BY (day, language);

CREATE TABLE IF NOT EXISTS irm.kafka_github_lang_daily (day String, language String, new_repos UInt32, incomplete UInt8, ingested_at String)
ENGINE = Kafka SETTINGS kafka_broker_list = 'redpanda:9092', kafka_topic_list = 'raw.github_lang_daily',
    kafka_group_name = 'ch_github_lang_daily', kafka_format = 'JSONEachRow', kafka_skip_broken_messages = 100;

CREATE MATERIALIZED VIEW IF NOT EXISTS irm.mv_github_lang_daily TO irm.github_lang_daily AS
SELECT toDate(day) AS day, language, new_repos, incomplete, parseDateTime64BestEffort(ingested_at, 3, 'UTC') AS ingested_at
FROM irm.kafka_github_lang_daily;

CREATE TABLE IF NOT EXISTS irm.github_repo_snapshot (
    snapshot_date Date, topic LowCardinality(String), full_name String, stars UInt32, forks UInt32, open_issues UInt32,
    language LowCardinality(String), created_at DateTime('UTC'), pushed_at DateTime('UTC'), description String, url String,
    ingested_at DateTime64(3, 'UTC')
) ENGINE = ReplacingMergeTree(ingested_at) ORDER BY (snapshot_date, topic, full_name);

CREATE TABLE IF NOT EXISTS irm.kafka_github_repo (
    snapshot_date String, topic String, full_name String, stars UInt32, forks UInt32, open_issues UInt32, language String,
    created_at String, pushed_at String, description String, url String, ingested_at String
) ENGINE = Kafka SETTINGS kafka_broker_list = 'redpanda:9092', kafka_topic_list = 'raw.github_repo',
    kafka_group_name = 'ch_github_repo', kafka_format = 'JSONEachRow', kafka_skip_broken_messages = 100;

CREATE MATERIALIZED VIEW IF NOT EXISTS irm.mv_github_repo TO irm.github_repo_snapshot AS
SELECT toDate(snapshot_date) AS snapshot_date, topic, full_name, stars, forks, open_issues, language,
       parseDateTimeBestEffortOrZero(created_at, 'UTC') AS created_at, parseDateTimeBestEffortOrZero(pushed_at, 'UTC') AS pushed_at,
       description, url, parseDateTime64BestEffort(ingested_at, 3, 'UTC') AS ingested_at
FROM irm.kafka_github_repo;

CREATE TABLE IF NOT EXISTS irm.wiki_table_rows (
    page String, revid UInt64, table_idx UInt16, row_idx UInt32, cells String, ingested_at DateTime64(3, 'UTC')
) ENGINE = ReplacingMergeTree(ingested_at) ORDER BY (page, table_idx, row_idx);

CREATE TABLE IF NOT EXISTS irm.kafka_wiki_table (page String, revid UInt64, table_idx UInt16, row_idx UInt32, cells String, ingested_at String)
ENGINE = Kafka SETTINGS kafka_broker_list = 'redpanda:9092', kafka_topic_list = 'raw.wiki_table',
    kafka_group_name = 'ch_wiki_table', kafka_format = 'JSONEachRow', kafka_skip_broken_messages = 100;

CREATE MATERIALIZED VIEW IF NOT EXISTS irm.mv_wiki_table TO irm.wiki_table_rows AS
SELECT page, revid, table_idx, row_idx, cells, parseDateTime64BestEffort(ingested_at, 3, 'UTC') AS ingested_at
FROM irm.kafka_wiki_table;

CREATE TABLE IF NOT EXISTS irm.news_meta (
    url String, site LowCardinality(String), headline String, published_at Nullable(DateTime('UTC')),
    modified_at Nullable(DateTime('UTC')), section LowCardinality(String), authors Array(String), keywords Array(String),
    method LowCardinality(String), ingested_at DateTime64(3, 'UTC')
) ENGINE = ReplacingMergeTree(ingested_at) ORDER BY url;

CREATE TABLE IF NOT EXISTS irm.kafka_news_meta (
    url String, site String, headline String, published_at String, modified_at String, section String,
    authors Array(String), keywords Array(String), method String, ingested_at String
) ENGINE = Kafka SETTINGS kafka_broker_list = 'redpanda:9092', kafka_topic_list = 'raw.news_meta',
    kafka_group_name = 'ch_news_meta', kafka_format = 'JSONEachRow', kafka_skip_broken_messages = 100;

CREATE MATERIALIZED VIEW IF NOT EXISTS irm.mv_news_meta TO irm.news_meta AS
SELECT url, site, headline, parseDateTimeBestEffortOrNull(published_at, 'UTC') AS published_at,
       parseDateTimeBestEffortOrNull(modified_at, 'UTC') AS modified_at, section, authors, keywords, method,
       parseDateTime64BestEffort(ingested_at, 3, 'UTC') AS ingested_at
FROM irm.kafka_news_meta;

CREATE TABLE IF NOT EXISTS irm.book_prices (
    snapshot_date Date, url String, title String, category LowCardinality(String), price_gbp Decimal(10, 2),
    rating UInt8, in_stock UInt8, ingested_at DateTime64(3, 'UTC')
) ENGINE = ReplacingMergeTree(ingested_at) ORDER BY (snapshot_date, url);

CREATE TABLE IF NOT EXISTS irm.kafka_book_price (
    snapshot_date String, url String, title String, category String, price_gbp Float64, rating UInt8, in_stock UInt8, ingested_at String
) ENGINE = Kafka SETTINGS kafka_broker_list = 'redpanda:9092', kafka_topic_list = 'raw.book_price',
    kafka_group_name = 'ch_book_price', kafka_format = 'JSONEachRow', kafka_skip_broken_messages = 100;

CREATE MATERIALIZED VIEW IF NOT EXISTS irm.mv_book_price TO irm.book_prices AS
SELECT toDate(snapshot_date) AS snapshot_date, url, title, category, toDecimal64(price_gbp, 2) AS price_gbp, rating, in_stock,
       parseDateTime64BestEffort(ingested_at, 3, 'UTC') AS ingested_at
FROM irm.kafka_book_price;

CREATE TABLE IF NOT EXISTS irm.practice_quotes (
    author LowCardinality(String), text String, tags Array(String), page UInt16, ingested_at DateTime64(3, 'UTC')
) ENGINE = ReplacingMergeTree(ingested_at) ORDER BY (author, text);

CREATE TABLE IF NOT EXISTS irm.kafka_practice_quote (author String, text String, tags Array(String), page UInt16, ingested_at String)
ENGINE = Kafka SETTINGS kafka_broker_list = 'redpanda:9092', kafka_topic_list = 'raw.practice_quote',
    kafka_group_name = 'ch_practice_quote', kafka_format = 'JSONEachRow', kafka_skip_broken_messages = 100;

CREATE MATERIALIZED VIEW IF NOT EXISTS irm.mv_practice_quote TO irm.practice_quotes AS
SELECT author, text, tags, page, parseDateTime64BestEffort(ingested_at, 3, 'UTC') AS ingested_at FROM irm.kafka_practice_quote;
