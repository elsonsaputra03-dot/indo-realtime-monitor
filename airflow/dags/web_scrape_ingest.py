"""
DAG pengumpulan data web (5 sumber, 6 DAG). Semua mengikuti pola IRM: ambil -> Kafka raw.* -> ClickHouse (Kafka engine
+ materialized view), plus heartbeat ke ops.ingest_run.

| DAG                    | Sumber                         | Teknik                                         | Jadwal (UTC)          |
|------------------------|--------------------------------|------------------------------------------------|-----------------------|
| scrape_bmkg_weather    | API prakiraan cuaca BMKG       | API JSON, batas 60/menit                       | 01:30 dan 13:30       |
| scrape_github_trends   | GitHub Search API              | pagination, batas laju 10/menit tanpa token    | 02:00                 |
| scrape_wikipedia       | API MediaWiki + HTML           | parsing tabel (rowspan/colspan, catatan kaki)  | Senin 03:00           |
| scrape_news_meta       | halaman artikel dari RSS       | HTML: JSON-LD / Open Graph, robots.txt         | setiap jam menit 20   |
| scrape_practice_books  | books.toscrape.com             | indeks kategori + pagination, riwayat harga    | 04:00                 |
| scrape_practice_quotes | quotes.toscrape.com/js         | data JavaScript yang tertanam di halaman       | 04:30                 |

Status di ops.ingest_run: ok | partial (sebagian sumber gagal) | layout_changed (halaman berubah: baris terlalu sedikit
atau kolom wajib kosong) | error (tidak ada data).
"""
from datetime import datetime, timedelta, timezone

from airflow.decorators import dag, task

from news_lib import FEEDS, dumps, fetch_feed, kafka_config
from scrape_lib import health

DEFAULTS = {"retries": 1, "retry_delay": timedelta(minutes=10)}


def publish(source: str, batches: list[tuple[str, list[dict], callable]], errors: list[str], hc: dict, ms: int,
            notes: list[str] | None = None) -> dict:
    """Kirim baris ke topic masing-masing + heartbeat. batches: [(topic, rows, key_fn)]."""
    from confluent_kafka import Producer

    p = Producer(kafka_config())
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    n = 0
    for topic, rows, key in batches:
        for r in rows:
            p.produce(topic, key=key(r), value=dumps({**r, "ingested_at": now}))
            n += 1
    status = "error" if n == 0 else "layout_changed" if not hc["ok"] else "partial" if errors else "ok"
    err = "; ".join(([hc["reason"]] if hc["reason"] else []) + errors + (notes or []))[:500]
    run = {"source": source, "run_at": now, "status": status, "fetched": n, "new_records": n, "latency_ms": ms, "error": err}
    p.produce("ops.ingest_run", key=source, value=dumps(run))
    p.flush(20)
    print(f"{source}: {status} rows={n} {err}")
    return run


def make(dag_id: str, schedule: str, body):
    @dag(dag_id=dag_id, schedule=schedule, start_date=datetime(2026, 1, 1), catchup=False, max_active_runs=1,
         default_args=DEFAULTS, tags=["ingest", "scraper", "web"], doc_md=__doc__)
    def _d():
        task(task_id="scrape_and_publish")(body)()
    return _d()


def bmkg_weather():
    import src_bmkg_weather as S
    res = S.fetch()
    return publish("bmkg_weather", [("raw.weather_forecast", res["rows"], lambda r: f"{r['adm4']}|{r['forecast_utc']}")],
                   res["errors"], health(res["rows"], S.REQUIRED, min_records=8), res["ms"])


def github_trends():
    import src_github as S
    now = datetime.now(timezone.utc)
    res = S.fetch(day=(now - timedelta(days=1)).date().isoformat(), snapshot_date=now.date().isoformat())
    hc = health(res["repos"], ["full_name", "stars"], min_records=len(S.TOPICS))
    return publish("github_trends", [("raw.github_lang_daily", res["counts"], lambda r: f"{r['day']}|{r['language']}"),
                                     ("raw.github_repo", res["repos"], lambda r: f"{r['snapshot_date']}|{r['topic']}|{r['full_name']}")],
                   res["errors"], hc, res["ms"])


def wikipedia():
    import src_wikipedia as S
    res = S.fetch()
    return publish("wikipedia", [("raw.wiki_table", res["rows"], lambda r: f"{r['page']}|{r['table_idx']}|{r['row_idx']}")],
                   res["errors"], health(res["rows"], ["cells"], min_records=30), res["ms"],
                   notes=[f"{k} from '{v}'" for k, v in res["used"].items()])


def news_meta():
    import src_news_meta as S
    urls = []
    for f in FEEDS:
        urls += [i["link"] for i in fetch_feed(f)["items"][:5]]        # 5 artikel terbaru per feed per jam
    res = S.fetch(urls)
    hc = health(res["rows"], S.REQUIRED, min_records=max(1, len(urls) // 3))
    notes = ([f"{res['robots_blocked']} URL disallowed by robots.txt"] if res["robots_blocked"] else []) + \
            [f"{h} refused bots (HTTP 403), {n} URL skipped" for h, n in res["refused"].items()]
    # penolakan situs dan robots.txt adalah kebijakan situs yang dihormati, bukan kegagalan: dicatat tanpa membuat status partial
    run = publish("news_meta", [("raw.news_meta", res["rows"], lambda r: r["url"])], res["errors"], hc, res["ms"], notes=notes)
    return run


def practice_books():
    import src_practice as S
    res = S.fetch_books()
    today = datetime.now(timezone.utc).date().isoformat()
    rows = [{**r, "snapshot_date": today} for r in res["rows"]]
    return publish("practice_books", [("raw.book_price", rows, lambda r: f"{today}|{r['url']}")],
                   res["errors"], health(rows, S.BOOK_REQUIRED, min_records=500), res["ms"])


def practice_quotes():
    import src_practice as S
    res = S.fetch_quotes()
    return publish("practice_quotes", [("raw.practice_quote", res["rows"], lambda r: f"{r['author']}|{r['text'][:60]}")],
                   res["errors"], health(res["rows"], ["text", "author"], min_records=50), 0)


scrape_bmkg_weather = make("scrape_bmkg_weather", "30 1,13 * * *", bmkg_weather)
scrape_github_trends = make("scrape_github_trends", "0 2 * * *", github_trends)
scrape_wikipedia = make("scrape_wikipedia", "0 3 * * 1", wikipedia)
scrape_news_meta = make("scrape_news_meta", "20 * * * *", news_meta)
scrape_practice_books = make("scrape_practice_books", "0 4 * * *", practice_books)
scrape_practice_quotes = make("scrape_practice_quotes", "30 4 * * *", practice_quotes)
