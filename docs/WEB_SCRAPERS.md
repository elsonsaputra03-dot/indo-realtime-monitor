# Web scrapers

Six Airflow DAGs collect public web data with a shared polite client (`airflow/dags/scrape_lib.py`): identifiable
User-Agent, per-host delay, robots.txt for HTML pages, retries honouring `Retry-After`, conditional GET, and a parse
health check that reports `layout_changed` when a page stops yielding the expected fields.

| DAG | Source | Technique | Policy followed |
|---|---|---|---|
| `scrape_bmkg_weather` | BMKG public forecast API | JSON API, per-village 3-hourly forecasts | ≤ 60 requests/minute; **BMKG must be credited as the data source** |
| `scrape_github_trends` | GitHub Search API | new repositories per language per day, top repositories per topic | Search API limit (10/min without token, 30 with `GITHUB_TOKEN`) |
| `scrape_wikipedia` | MediaWiki API + HTML | `wikitable` parsing with rowspan/colspan expansion and footnote removal | Wikimedia API etiquette: identifiable User-Agent, sequential requests |
| `scrape_news_meta` | article pages linked from the RSS feeds | JSON-LD (`NewsArticle`, incl. `@graph`) with Open Graph fallback | robots.txt per URL, 2 s per host, 5 newest articles per feed per hour, **metadata only (no article text)** |
| `scrape_practice_books` | books.toscrape.com | category index, pagination, daily price snapshots | site built for scraping practice |
| `scrape_practice_quotes` | quotes.toscrape.com/js | data embedded in page JavaScript, without a headless browser | site built for scraping practice |

Data lands in ClickHouse through Kafka topics (`raw.weather_forecast`, `raw.github_lang_daily`, `raw.github_repo`,
`raw.wiki_table`, `raw.news_meta`, `raw.book_price`, `raw.practice_quote`); see `clickhouse/init/06_web_scrapers.sql`.
Every run sends a heartbeat to `ops.ingest_run` with status `ok`, `partial`, `layout_changed` or `error`.

Tests (`airflow/tests`, no network): BMKG's official sample response, recorded GitHub API responses, and HTML fixtures.
Found while testing: a `colspan` header produced two columns with the same name, so the second silently overwrote the
first when rows became dictionaries; repeated headers are now suffixed (`Wilayah`, `Wilayah (2)`).

Notes: the books site's prices are static, so the price history shows the technique, not market movement. The BMKG
location list holds only codes verified from BMKG's own documentation; add more Kepmendagri adm4 codes as needed.
