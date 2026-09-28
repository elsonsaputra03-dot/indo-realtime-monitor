# Indonesia Realtime Monitor — Panduan Step by Step

Platform portofolio data engineering: ingestion realtime multi-sumber → Kafka (Redpanda) → ClickHouse → data quality → scoring → GIS dashboard + LLM, dideploy online.

Repo ini sudah berisi **Fase 1 (MVP) yang siap jalan**: gempa BMKG + USGS realtime, pipeline Kafka → ClickHouse, run log, DQ checks, API, peta live, dan Grafana. Fase 2–8 adalah langkah lanjutan dengan pola yang sama.

```
BMKG / USGS ──► producer (Python) ──► Redpanda ──► ClickHouse (Kafka engine + MV)
                     │                                  │
                     └── heartbeat ops.ingest_run ──────┤
                                                        ├──► DQ checker ──► dq_results
                                                        ├──► FastAPI ──► peta (Leaflet)
                                                        └──► Grafana (monitoring)
```

---

## Fase 0 — Persiapan (hari 1)

1. **Tools lokal**: Docker Desktop / Docker Engine + Compose v2, Git, Python 3.12, VS Code. RAM minimal 8 GB.
2. **Repo GitHub publik** bernama misalnya `indo-realtime-monitor`. Jangan pernah commit `.env`.
3. **Daftar akun / API key gratis** (yang belum dipakai di MVP boleh belakangan):
   | Kebutuhan | Tempat daftar | Dipakai di |
   |---|---|---|
   | NASA FIRMS MAP_KEY | firms.modaps.eosdis.nasa.gov/api | Fase 2 |
   | OpenAQ API key | explore.openaq.org | Fase 2 |
   | BPS WebAPI key | webapi.bps.go.id | Fase 5 |
   | GCP project (BigQuery sandbox) | console.cloud.google.com | Fase 2 (Google Trends, GH Archive) |
   | aisstream.io | aisstream.io | Fase 2 (opsional) |
   | LLM: Ollama lokal / API key provider | ollama.com | Fase 4 |
4. **Aturan main data**: hanya data publik, patuhi robots.txt & ToS, cantumkan atribusi sumber, tidak ada data/skema/kode dari kantor.

## Fase 1 — MVP pipeline realtime (minggu 1)

### 1.1 Jalankan

```bash
cp .env.example .env          # lalu ganti password
make up                       # = docker compose up -d --build
make ps                       # semua service harus running/healthy
make logs                     # lihat producer: "bmkg status=ok fetched=30 new=..."
```

Tunggu 1–2 menit, lalu:

```bash
make smoke
```

| URL | Isi |
|---|---|
| http://localhost:8000 | Peta gempa live + status pipeline |
| http://localhost:8000/docs | Swagger API |
| http://<IP-WSL>:3001 | Grafana (admin / GRAFANA_ADMIN_PASSWORD). IP: `make urls` |
| http://localhost:8080 | Redpanda Console (lihat topic & message) |

Semua port hanya di-bind ke `127.0.0.1`, jadi tidak terekspos ke jaringan.

### 1.2 Pahami alurnya

- `app/producers/earthquake.py` polling tiap `POLL_SECONDS`, normalisasi BMKG & USGS ke satu skema, kirim hanya event baru ke `raw.earthquake`, dan kirim heartbeat per run ke `ops.ingest_run`.
- `clickhouse/init/01_schema.sql`: Kafka engine table → Materialized View → `ReplacingMergeTree` (dedup final by `event_id`). Query serving pakai `FINAL`.
- `app/dq/checks.py` tiap menit menghitung freshness, error rate, validity, duplicate ratio, event lag → `dq_results`.
- `app/api/main.py`: API read-only dengan cache 30 detik; `web/index.html` peta Leaflet.

### 1.3 Cek manual di ClickHouse

```bash
make ch
```
```sql
SELECT source, count(), max(event_time) FROM earthquake_events FINAL GROUP BY source;
SELECT * FROM ingest_runs ORDER BY run_at DESC LIMIT 10;
SELECT source, check_name, status, value FROM dq_results ORDER BY checked_at DESC LIMIT 20;
```

### 1.4 Dashboard Grafana (buat manual, lalu export JSON ke repo)

Datasource ClickHouse sudah otomatis ter-provision. Buat dashboard "Pipeline Ops" dengan panel:

```sql
-- Time series: record baru per source per 5 menit
SELECT toStartOfFiveMinutes(run_at) AS time, source, sum(new_records) AS new_records
FROM ingest_runs WHERE $__timeFilter(run_at) GROUP BY time, source ORDER BY time;

-- Time series: latency fetch
SELECT toStartOfFiveMinutes(run_at) AS time, source, avg(latency_ms) AS latency_ms
FROM ingest_runs WHERE $__timeFilter(run_at) GROUP BY time, source ORDER BY time;

-- Table: status DQ terbaru
SELECT source, check_name, argMax(status, checked_at) AS status, argMax(value, checked_at) AS value
FROM dq_results WHERE checked_at > now() - INTERVAL 1 HOUR GROUP BY source, check_name;

-- Geomap: gempa (pakai kolom lat, lon, magnitude)
SELECT lat, lon, magnitude, region FROM earthquake_events FINAL WHERE $__timeFilter(event_time);
```

Export dashboard (Share → Export → JSON) ke `grafana/dashboards/` supaya ikut ter-versioning.

**Selesai Fase 1 = commit + tag `v0.1`.**

## Fase 2 — Tambah sumber data (minggu 2–3)

**Status: FIRMS (titik panas) dan Open-Meteo (kualitas udara 38 ibu kota provinsi) sudah ada di repo.**

Upgrade dari Fase 1 (data lama tetap aman):

```bash
nano .env                 # isi FIRMS_MAP_KEY (+ variabel Fase 2 dari .env.example)
make up                   # build & start service baru
make migrate              # buat topic + tabel Fase 2 di ClickHouse yang sudah jalan
docker compose restart dq api
make smoke                # tunggu 1-2 menit setelah migrate
```

Yang ditambahkan:
- `app/producers/base.py`: runner generik (fetch → dedup → Kafka + heartbeat). Producer baru cukup menulis `fetch()`.
- `producers/hotspot.py` (NASA FIRMS VIIRS, poll 15 menit) dan `producers/air_quality.py` (Open-Meteo, 38 kota, poll 15 menit).
- `clickhouse/init/02_phase2.sql`: `hotspots`, `air_quality` + Kafka engine + MV.
- DQ digeneralisasi per source; lag check hanya menghitung event di dalam window (backfill tidak lagi memicu merah); satu source gagal tidak menghentikan check source lain.
- API: `/api/hotspots`, `/api/air-quality/latest`. Peta: layer titik panas, layer AQI, tab kualitas udara.

Sumber berikutnya mengikuti pola yang sama:

Pola untuk setiap sumber baru (ikuti `earthquake.py`):

1. Buat `app/producers/<nama>.py`: fetch → normalize → `send(topic, key, value)` + heartbeat ke `ops.ingest_run`.
2. Buat topic di service `topics-init` (`raw.<nama>`).
3. Tambah `clickhouse/init/0X_<nama>.sql`: tabel serving + Kafka engine + MV. Untuk DB yang sudah jalan, eksekusi manual lewat `make ch`.
4. Tambah service di `docker-compose.yml` (copy blok `producer-earthquake`).
5. Tambah entry di `SOURCES` pada `dq/checks.py` dengan threshold freshness yang sesuai frekuensi sumber.

Urutan yang disarankan:

| # | Sumber | Topic | Frekuensi polling | Catatan |
|---|---|---|---|---|
| 1 | NASA FIRMS (VIIRS, bbox Indonesia) | `raw.hotspot` | 15 menit | Butuh `FIRMS_MAP_KEY` |
| 2 | Open-Meteo Air Quality (grid ibu kota provinsi) | `raw.air_quality` | 1 jam | Tanpa key |
| 3 | BMKG prakiraan cuaca (per kode adm4) | `raw.weather` | 1 jam | Pilih ±100 kelurahan sampel |
| 4 | Google News RSS + RSS portal | `raw.news` | 10 menit | Simpan judul, link, sumber, waktu |
| 5 | Wikimedia EventStreams (SSE) | `raw.wiki` | streaming | Showcase throughput tinggi |
| 6 | aisstream.io (WebSocket) | `raw.ais` | streaming | Opsional, volume besar → atur TTL pendek |
| 7 | Google Trends / GH Archive / PyPI (BigQuery) | `raw.trends` | harian | Airflow job, filter partisi wajib |

## Fase 3 — Scraper + orkestrasi batch (minggu 3–4)

**Status: 3a (berita) dan 3b (harga pangan) sudah ada di repo.**

3b: DAG `food_price_ingest` mengambil harga harian 10 kelompok komoditas per provinsi dari **PIHPS Nasional (Bank Indonesia)**, pasar tradisional.
- Endpoint dipakai halaman publik PIHPS, dapat diakses tanpa login/cookie; robots.txt bi.go.id tidak melarang `/hargapangan`.
- Sopan: 2 run/hari (14.00 & 18.00 WIB), maks 2 request paralel, jeda 3 detik, User-Agent menunjuk repo ini.
- Backfill: Airflow → Trigger DAG w/ config `{"days_back": 30}`.
- Tabel `food_prices` (ReplacingMergeTree, key komoditas+provinsi+tanggal), DQ source `pihps`, endpoint `/api/food-prices/latest`, tab **Harga pangan**.
- Panel Harga Badan Pangan tidak dipakai: situs sedang pemeliharaan dan API-nya hanya untuk integrasi antar-instansi (SPLP).

```bash
echo "AIRFLOW_DB_PASSWORD=ganti_password_airflow" >> .env
make up && make migrate          # topic raw.news + tabel news
docker compose restart dq api
make batch-up                    # build image Airflow (pertama kali ±5-10 menit)
make airflow-pass                # password user admin
make urls                        # URL Airflow (port 8081, via IP WSL)
```

- `airflow/dags/news_ingest.py`: DAG tiap 15 menit, `load_seen` → `fetch` (dynamic task mapping, 1 task per feed, maks 3 paralel) → `publish` ke `raw.news` + heartbeat `ops.ingest_run`.
- `airflow/dags/news_lib.py`: 7 query Google News RSS per topik + RSS Antara, CNN Indonesia, Tempo; cek robots.txt per host, jeda antar request, hanya judul + ringkasan ≤280 karakter + link; klasifikasi topik rule-based (Fase 4: LLM).
- `clickhouse/init/03_phase3.sql`: tabel `news` (ReplacingMergeTree by `news_id`) + Kafka engine + MV.
- DQ source `news`, endpoint `/api/news?hours=&topic=`, tab **Berita** di peta.
- Airflow memakai profile `batch`: `make up` saja tidak menjalankannya. Saat Airflow mati, DQ `news freshness` akan merah (memang disengaja).

Rencana awal Fase 3 (referensi):

1. Tambah Airflow (image resmi `apache/airflow`, mode `LocalExecutor` + Postgres) ke compose sebagai profile terpisah (`docker compose --profile batch up`).
2. DAG harian:
   - `scrape_harga_pangan`: PIHPS / Panel Harga Badan Pangan → `raw.food_price`.
   - `apps_top_chart`: Apple RSS top chart `id` + iTunes Lookup + `google-play-scraper` → `raw.app_rank`, `raw.app_review`.
   - `bq_extract_trends`: Google Trends & PyPI dari BigQuery → ClickHouse.
3. Standar scraper: `User-Agent` jelas, rate limit, retry dengan backoff, cek robots.txt, simpan HTML mentah ke volume untuk debugging, tidak menyimpan data pribadi (nama/foto reviewer).
4. Heartbeat tiap task tetap ke `ops.ingest_run` supaya monitoring & DQ seragam antara streaming dan batch.

## Fase 4 — LLM enrichment (minggu 5)

**Status: sudah ada di repo.** LLM lokal via Ollama (GPU), tanpa biaya API.

```bash
echo "OLLAMA_URL=http://ollama:11434" >> .env
echo "LLM_MODEL=qwen2.5:3b" >> .env
make up && make migrate && docker compose restart dq api
make batch-up          # Airflow membaca mount ./reference + DAG news_enrich
make llm-up            # Ollama (butuh NVIDIA Container Toolkit)
make llm-pull          # download model (~2 GB)
make llm-eval          # uji 15 berita terbaru, cek topik & lokasi secara manual
```

- `airflow/dags/llm_lib.py`: prompt + JSON schema (structured output, temperature 0), resolver gazetteer, fallback rule-based, CLI evaluasi.
- **Koordinat tidak pernah berasal dari LLM.** LLM hanya mengekstrak nama tempat; koordinat diambil dari gazetteer `reference/wilayah_indonesia.csv` (38 provinsi + 514 kab/kota, sumber cahyadsn/wilayah, MIT). Mencegah titik halusinasi di peta.
- Disambiguasi: awalan "Kota"/"Kabupaten" di teks, nama provinsi yang disebut di teks, alias media (Kotim, Kukar, Jabar, ...). Kasus ambigu ditandai `geo_ambiguous`.
- `airflow/dags/news_enrich.py`: tiap 15 menit (offset 5 menit), maks 40 berita, retry item gagal setelah 1 jam.
- Tabel `news_enriched`, DQ source `llm_enrich`, endpoint `/api/news/geo`, layer peta **Berita (lokasi)**, ringkasan LLM + chip lokasi di tab Berita.
- Ganti model: ubah `LLM_MODEL` di `.env`, `make llm-pull`, `make llm-eval`, lalu `docker compose --profile batch up -d airflow`. Hasil per model disimpan terpisah (`ORDER BY (news_id, model)`), jadi bisa dibandingkan.

### Tanya Data (AI menjawab dari data platform)

Tab **Tanya AI** di peta dan endpoint `POST /api/ask {"question": "..."}`.

- Pola **tool calling**, bukan text-to-SQL bebas: router LLM memilih 1–3 alat (`gempa`, `titik_panas`, `kualitas_udara`, `harga_pangan`, `berita`, `kesehatan_pipeline`) + parameter; backend menjalankan query ter-parameterisasi; LLM kedua menyusun jawaban **hanya** dari hasil alat. Tidak ada SQL dari LLM → aman dari injection & query liar.
- Lokasi di-resolve dengan gazetteer yang sama (Kotim, Kalteng, Babel, gunung, ...). Filter wilayah memakai **poligon batas** (`reference/batas_*.geojson`, point-in-polygon via Shapely STRtree, ±50 ms untuk 20 ribu titik); gempa memakai buffer ±50 km supaya episentrum laut dekat pantai ikut.
- Transparansi: UI menampilkan label "jawaban dibuat AI", alat yang dipakai, data mentah yang diberikan ke AI, dan link sumber berita. Peta otomatis zoom ke lokasi yang ditanyakan.
- Batasan: rate limit 10 pertanyaan/menit per IP, pertanyaan ≤300 karakter, di luar cakupan → dijawab tidak tersedia.

Rencana awal Fase 4 (referensi):

1. Service `llm-worker`: consume `raw.news` & `raw.app_review` → produce `enriched.news` / `enriched.review`.
2. Tugas LLM (output JSON ketat, divalidasi pakai Pydantic, yang gagal masuk `dlq.llm`):
   - kategori (bencana, ekonomi, kesehatan, politik, teknologi), sentimen, ringkasan 1 kalimat;
   - ekstraksi lokasi → geocode ke kode kabupaten (lookup tabel wilayah dulu, LLM hanya untuk teks).
3. Model: mulai dengan Ollama lokal (model kecil) untuk klasifikasi; API berbayar hanya untuk fitur chat.
4. Fitur **Tanya Data** (text-to-SQL) di API:
   - user ClickHouse khusus `readonly = 1`, whitelist tabel/view `mart_*`, paksa `LIMIT`, `max_execution_time`;
   - rate limit per IP dan batas biaya harian di akun provider;
   - tampilkan SQL yang dihasilkan ke user (transparansi).
5. Evaluasi: buat 50 sampel berita berlabel manual, ukur akurasi kategori & lokasi, tulis hasilnya di README.

## Fase 5 — GIS & scoring (minggu 6–7)

1. **Referensi wilayah**: batas provinsi/kab/kota (geoBoundaries atau BIG) → tabel `ref_region` (kode, nama, centroid, polygon WKT). Tambah H3 index (res 7–8) untuk agregasi grid.
2. **Penduduk**: BPS WebAPI (kab/kota) + WorldPop/Kontur (grid) → `ref_population`.
3. **POI**: Overture Maps Places + Foursquare OS Places + OSM (cafe, wisata, faskes) → `ref_poi` (update bulanan).
4. **Spatial join**: event titik → kabupaten via `pointInPolygon` atau pre-computed H3.
5. **Risk score per kabupaten** (`mart_region_risk`, refresh 15 menit):
   ```
   score = 100 × Σ wᵢ · normᵢ
   komponen: gempa (magnitudo × kedekatan, 72 jam), hotspot density (24 jam),
             AQI rata-rata (24 jam), cuaca ekstrem (prakiraan 24 jam),
             anomali harga pangan (z-score vs 30 hari), sentimen berita negatif (24 jam)
   ```
   Bobot di tabel config, simpan histori skor, sediakan breakdown per komponen (explainability).
6. **Location score per hexagon** (Jakarta dulu): kepadatan penduduk × jumlah cafe × wisata × akses (jalan/transport) → peta peluang lokasi.
7. Frontend: layer toggle (gempa, hotspot, AQI, berita, risk choropleth, H3 heatmap), detail panel per kabupaten.

## Fase 6 — Monitoring & alerting (minggu 8)

1. Tambah Prometheus + exporter: Redpanda metrics (bawaan di `:9644/public_metrics`), ClickHouse (`/metrics`), cAdvisor/node-exporter.
2. Grafana: dashboard Kafka consumer lag, throughput per topic, disk ClickHouse, error rate scraper, SLA per source.
3. Alert (Grafana alerting → Telegram bot): freshness fail > 15 menit, consumer lag naik terus, disk > 80%, gempa M ≥ 6.
4. Test chaos kecil: matikan satu producer, pastikan DQ & alert menangkapnya. Dokumentasikan dengan screenshot.

## Demo publik gratis (GitHub Pages + GitHub Actions)

Biaya hosting Rp0. `site/` berisi halaman portofolio (`index.html`) dan peta statis (`demo.html`).
Workflow `.github/workflows/snapshot.yml` berjalan tiap jam: `scripts/snapshot.py` mengambil data (memakai ulang
normalizer producer/DAG), menulis `site/data/*.json` + `meta.json` (status per sumber), lalu mem-publish ke GitHub Pages.
Stack lengkap (Kafka, ClickHouse, Airflow, DQ, AI lokal) tetap dijalankan lokal dengan Docker Compose.

Setup sekali: repo public → Settings → Pages → Source: **GitHub Actions**; Settings → Secrets → Actions →
`FIRMS_MAP_KEY`; Actions → "Publish live snapshot" → Run workflow. Catatan: GitHub menonaktifkan jadwal workflow
setelah 60 hari tanpa aktivitas repo; aktifkan lagi dari tab Actions bila perlu.

## Fase 7 — Deploy online (minggu 9)

1. VPS 4 vCPU / 8 GB (atau Oracle Cloud Always Free ARM), Ubuntu LTS, user non-root, SSH key only, `ufw` hanya buka 22.
2. Domain murah (`.my.id`) → Cloudflare DNS → **Cloudflare Tunnel** ke `api:8000` dan `grafana:3000` (tanpa buka port 80/443).
3. `docker-compose.prod.yml`: network `public` (api, grafana) dan `internal` (redpanda, clickhouse, airflow); `restart: unless-stopped`; batas memori per service.
4. Grafana: anonymous read-only untuk dashboard publik, admin dilindungi Cloudflare Access. Airflow & Redpanda Console hanya via Cloudflare Access / SSH tunnel.
5. CI/CD GitHub Actions: lint + test → build image → push GHCR → SSH deploy (`docker compose pull && up -d`).
6. Operasional: UptimeRobot ke `/api/health`, backup harian `mart_*` & config ke object storage, TTL di semua tabel raw.

## Fase 8 — Poles portofolio (minggu 10)

1. README publik (English): problem, arsitektur (diagram), keputusan & trade-off (kenapa ClickHouse, kenapa Redpanda, kenapa dedup di MV), angka nyata (event/hari, latency end-to-end, jumlah DQ checks, uptime), keterbatasan.
2. Halaman **Data Sources & Attribution** di web.
3. Video demo 2–3 menit + GIF di README.
4. Tulis 1–2 artikel teknis (Medium/LinkedIn), misal "Realtime DQ untuk sumber data publik yang tidak stabil".
5. Pin repo di GitHub, cantumkan link live demo di CV & LinkedIn.

---

## Troubleshooting

| Gejala | Cek |
|---|---|
| Producer `status=error` | `make logs`; BMKG/USGS kadang timeout, akan pulih di run berikutnya dan terlihat di DQ |
| Tidak ada data di ClickHouse | Redpanda Console: apakah message masuk topic? `SELECT * FROM system.kafka_consumers` di ClickHouse |
| Schema SQL tidak jalan | Init script hanya jalan saat volume kosong: `make reset` lalu `make up` (menghapus data) |
| Grafana datasource error | Pastikan plugin terpasang (`docker compose logs grafana`), user/password sama dengan `.env` |
| Peta kosong tapi API ada data | Buka console browser; tile CARTO butuh koneksi internet |

## Atribusi data

Data gempa: BMKG (Badan Meteorologi, Klimatologi, dan Geofisika) dan USGS Earthquake Hazards Program. Peta dasar: © OpenStreetMap contributors, © CARTO.
