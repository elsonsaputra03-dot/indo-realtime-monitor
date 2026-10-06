"""Test scraper web tanpa jaringan: respons asli (BMKG, GitHub) dan halaman HTML contoh, serta klien HTTP sopan."""
import json
import sys
from pathlib import Path

import httpx
import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "dags"))

import scrape_lib as L                      # noqa: E402
import src_bmkg_weather as BMKG             # noqa: E402
import src_github as GH                     # noqa: E402
import src_news_meta as NEWS                # noqa: E402
import src_practice as PR                   # noqa: E402
import src_wikipedia as WIKI                # noqa: E402

FX = HERE / "fixtures"
read = lambda n: (FX / n).read_text(encoding="utf-8")       # noqa: E731


# ---------- klien sopan ----------
class FakeClock:
    def __init__(self): self.t, self.slept = 0.0, []
    def clock(self): return self.t
    def sleep(self, s): self.slept.append(round(s, 2)); self.t += s


def polite(handler, **kw):
    fc = FakeClock()
    return L.Polite(transport=httpx.MockTransport(handler), sleep=fc.sleep, clock=fc.clock, **kw), fc


def test_robots_disallow_blocks_and_missing_robots_allows():
    def h(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/") if req.url.host == "a.test" else httpx.Response(404)
        return httpx.Response(200, text="ok")
    p, _ = polite(h)
    assert p.get("https://a.test/public/x").text == "ok"
    with pytest.raises(L.RobotsDisallowed):
        p.get("https://a.test/private/x")
    assert p.get("https://b.test/anything").text == "ok"                  # robots.txt 404 -> tidak ada larangan
    assert p.stats["robots_blocked"] == 1


def test_per_host_gap_and_retry_after():
    calls = {"n": 0}
    def h(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json={"ok": True})
    p, fc = polite(h, min_gap=2.0, respect_robots=False)
    assert p.get("https://api.test/x").json() == {"ok": True}
    assert 7.0 in fc.slept and p.stats["retries"] == 1                    # menghormati Retry-After
    p.get("https://api.test/y")
    assert fc.slept[-1] == 2.0                                            # jeda minimum per host


def test_conditional_get_reuses_cached_body():
    def h(req):
        if req.headers.get("If-None-Match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, text="body", headers={"ETag": '"v1"'})
    p, _ = polite(h, respect_robots=False, min_gap=0)
    assert p.get("https://x.test/a").text == "body" and p.get("https://x.test/a").text == "body"
    assert p.stats["not_modified"] == 1


def test_health_flags_layout_change():
    assert L.health([{"a": 1}] * 10, ["a"], min_records=5)["ok"]
    assert not L.health([], ["a"])["ok"]
    h = L.health([{"a": 1, "b": ""}] * 10, ["a", "b"])
    assert not h["ok"] and "b (10/10)" in h["reason"]


# ---------- BMKG (contoh resmi BMKG) ----------
def test_bmkg_parse_official_sample():
    rows = BMKG.parse(json.loads(read("bmkg_forecast_31.71.01.1001.json")))
    assert len(rows) >= 8 and {r["adm4"] for r in rows} == {"31.71.01.1001"}
    r = rows[0]
    assert r["desa"] == "Gambir" and r["provinsi"] == "DKI Jakarta"
    assert r["forecast_utc"] == "2025-10-12 08:00:00" and r["local_datetime"] == "2025-10-12 15:00:00"
    assert isinstance(r["t"], (int, float)) and r["weather_desc"]
    assert L.health(rows, BMKG.REQUIRED, min_records=8)["ok"]


def test_bmkg_fetch_isolates_a_bad_code():
    sample = json.loads(read("bmkg_forecast_31.71.01.1001.json"))
    def h(req):
        return httpx.Response(200, json=sample if req.url.params["adm4"] == "31.71.01.1001" else {"data": []})
    p, _ = polite(h, respect_robots=False, min_gap=0)
    res = BMKG.fetch(["31.71.01.1001", "99.99.99.9999"], client=p)
    assert res["rows"] and res["errors"] == ["99.99.99.9999: no forecast in response"]


# ---------- GitHub (respons asli Search API) ----------
def test_github_count_and_repos_from_real_responses():
    c = GH.parse_count(json.loads(read("gh_count_python.json")), "Python", "2026-10-04")
    assert c["new_repos"] > 1000 and c["incomplete"] is False
    repos = GH.parse_repos(json.loads(read("gh_topic_data-engineering.json")), "data-engineering", "2026-10-06")
    assert len(repos) == 5 and repos[0]["stars"] >= repos[-1]["stars"]
    assert all(r["full_name"] and r["url"].startswith("https://github.com/") for r in repos)
    assert repos[0]["created_at"] and "T" not in repos[0]["created_at"]


# ---------- Wikipedia (tabel MediaWiki) ----------
def test_wikitable_rowspan_colspan_and_footnotes():
    tables = WIKI.parse_tables(read("wiki_provinsi.html"))
    assert len(tables) == 2                                                    # navbox bukan wikitable, tidak ikut
    t = WIKI.pick(tables, ["provinsi", "ibu kota"])
    assert t["header"] == ["Lambang", "Provinsi", "Kode / BPS", "Kode / ISO ( ID- )", "Kep.", "Ibu kota", "Wilayah geografis"]
    assert [r["Provinsi"] for r in t["rows"]] == ["Aceh", "Sumatera Utara", "Jawa Timur"]     # header ke-2 bukan data; [2] dibuang
    assert [(r["Kode / BPS"], r["Kode / ISO ( ID- )"]) for r in t["rows"]] == [("11", "AC"), ("12", "SU"), ("35", "JI")]
    assert [r["Wilayah geografis"] for r in t["rows"]] == ["Sumatra", "Sumatra", "Jawa"]      # rowspan dikembangkan
    assert WIKI.pick(tables, ["tidak", "ada"]) is None


def test_wikipedia_falls_back_to_the_next_candidate_page():
    html_ok = read("wiki_provinsi.html")
    navbox_only = '<div class="mw-parser-output"><table class="navbox-inner"><tr><td>x</td></tr></table></div>'
    def h(req):
        page = req.url.params["page"]
        if page == "Halaman A":
            return httpx.Response(200, json={"parse": {"title": page, "revid": 1, "text": navbox_only}})
        return httpx.Response(200, json={"parse": {"title": page, "revid": 2, "text": html_ok}})
    p, _ = polite(h, respect_robots=False, min_gap=0)
    WIKI.DATASETS, saved = {"provinsi": (["Halaman A", "Halaman B"], ["provinsi", "ibu kota"])}, WIKI.DATASETS
    try:
        res = WIKI.fetch(c=p)
    finally:
        WIKI.DATASETS = saved
    assert res["used"] == {"provinsi": "Halaman B"} and len(res["rows"]) == 3 and not res["errors"]
    assert json.loads(res["rows"][0]["cells"])["Ibu kota"] == "Banda Aceh"


# ---------- berita: metadata saja ----------
def test_news_jsonld_in_graph():
    m = NEWS.extract(read("news_jsonld_graph.html"), "https://contoh.id/a/1")
    assert m["method"] == "json-ld" and m["headline"] == "Pemerintah umumkan kebijakan baru"
    assert m["published_at"] == "2026-10-06T08:15:00+07:00" and m["section"] == "Nasional"
    assert m["authors"] == ["Rina Ayu", "Budi"] and m["keywords"] == ["kebijakan", "ekonomi", "pemerintah"]
    assert "Isi artikel" not in json.dumps(m)                                     # isi artikel tidak disimpan


def test_news_jsonld_list_and_broken_block():
    m = NEWS.extract(read("news_jsonld_list.html"), "https://contoh.id/b")
    assert m["headline"].startswith("Gempa") and m["authors"] == ["Redaksi"] and m["keywords"] == ["gempa", "bmkg"]


def test_news_opengraph_fallback():
    m = NEWS.extract(read("news_opengraph_only.html"), "https://contoh.id/c")
    assert m["method"] == "opengraph" and m["section"] == "Ekonomi" and m["authors"] == ["Sari"]
    assert m["published_at"].startswith("2026-10-04")


def test_news_fetch_respects_robots():
    def h(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /tag/")
        return httpx.Response(200, text=read("news_opengraph_only.html"))
    p, _ = polite(h, min_gap=0)
    res = NEWS.fetch(["https://n.test/berita/1", "https://n.test/tag/x"], c=p)
    assert len(res["rows"]) == 1 and res["robots_blocked"] == 1


# ---------- situs latihan ----------
def test_books_categories_listing_pagination_and_price():
    cats = PR.parse_categories(read("books_index.html"))
    assert cats[0] == ("Travel", "https://books.toscrape.com/catalogue/category/books/travel_2/index.html")
    url = cats[0][1]
    books, nxt = PR.parse_listing(read("books_travel_page1.html"), url, "Travel")
    assert nxt == "https://books.toscrape.com/catalogue/category/books/travel_2/page-2.html"
    assert books[0] == {"title": "It's Only the Himalayas", "url": "https://books.toscrape.com/catalogue/its-only-the-himalayas_981/index.html",
                        "category": "Travel", "price_gbp": 45.17, "rating": 2, "in_stock": True}       # "Â£" salah encoding tetap terbaca
    assert books[1]["title"].startswith("Full Moon over Noah") and books[1]["rating"] == 5
    books2, nxt2 = PR.parse_listing(read("books_travel_page2.html"), nxt, "Travel")
    assert len(books2) == 1 and nxt2 is None


def test_books_crawl_follows_pagination():
    pages = {"/": "books_index.html", "/catalogue/category/books/travel_2/index.html": "books_travel_page1.html",
             "/catalogue/category/books/travel_2/page-2.html": "books_travel_page2.html",
             "/catalogue/category/books/mystery_3/index.html": "books_travel_page2.html"}
    def h(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=read(pages[req.url.path]))
    p, _ = polite(h, min_gap=0)
    res = PR.fetch_books(c=p)
    assert len(res["rows"]) == 4 and res["pages"] == 4 and not res["errors"]
    assert {r["category"] for r in res["rows"]} == {"Travel", "Mystery"}


def test_quotes_from_embedded_javascript():
    q = PR.parse_quotes_js(read("quotes_js_page1.html"))
    assert len(q) == 2 and q[0]["author"] == "Albert Einstein" and q[0]["tags"][0] == "change"
    assert q[0]["text"].startswith("The world as we have created it") and not q[0]["text"].startswith("“")
    assert PR.parse_quotes_js("<html>no data</html>") == []


def test_news_site_refusing_bots_is_respected_and_skipped():
    calls = []
    def h(req):
        calls.append(req.url.path)
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.host == "tolak.test":
            return httpx.Response(403)
        return httpx.Response(200, text=read("news_opengraph_only.html"))
    p, _ = polite(h, min_gap=0)
    urls = ["https://tolak.test/a/1", "https://tolak.test/a/2", "https://tolak.test/a/3", "https://ok.test/b/1"]
    res = NEWS.fetch(urls, c=p)
    assert len(res["rows"]) == 1 and res["errors"] == []
    assert res["refused"] == {"tolak.test": 3}
    assert calls.count("/a/2") == 0 and calls.count("/a/3") == 0          # setelah 403 pertama, host itu tidak diketuk lagi


def test_duplicate_single_row_headers_stay_unique():
    html = ('<table class="wikitable"><tr><th>Nama</th><th colspan="2">Nilai</th></tr>'
            '<tr><td>a</td><td>1</td><td>2</td></tr></table>')
    t = WIKI.parse_tables(html)[0]
    assert t["header"] == ["Nama", "Nilai", "Nilai (2)"] and t["rows"] == [{"Nama": "a", "Nilai": "1", "Nilai (2)": "2"}]
