# Demo video script (≈2.5 minutes)

Record at 1920×1080 with OBS, Loom, or Windows `Win+Alt+R`. Speak slowly; cut pauses afterwards.
Upload to YouTube as *Unlisted* (or LinkedIn native video) and link it from the README and portfolio.

| # | Time | Screen | Narration (EN) |
|---|---|---|---|
| 1 | 0:00–0:15 | Portfolio page, scroll to *Featured project* | "I'm Elson, a data engineer. This is Indonesia Realtime Monitor: a data platform that ingests public Indonesian data, checks its quality continuously, and turns it into a risk map and a question-answering assistant." |
| 2 | 0:15–0:40 | Public demo → *Risiko* tab, click the top regency popup | "Every hour, a GitHub Action pulls earthquakes, NASA wildfire hotspots, air quality, food prices and disaster news, then scores all 514 regencies. Each score is explainable: here Central Kalimantan is driven by hotspot density and hazardous air quality." |
| 3 | 0:40–0:55 | Status panel (all green), point at a dashed boundary | "Source health is visible to visitors. Dashed borders are regencies whose source polygons failed my quality checks: 24 out of 514 were wrong, so they're approximated and flagged instead of silently used." |
| 4 | 0:55–1:20 | Terminal: `make ps`, then Redpanda Console topics, then Grafana *Pipeline Ops* | "The full platform runs on one machine: Python producers stream into Redpanda, ClickHouse ingests through Kafka engine tables, and every source has freshness, error-rate, validity, duplicate and lag checks, shown here in Grafana." |
| 5 | 1:20–1:35 | Airflow UI: `news_ingest` Graph view with mapped tasks | "Airflow runs the scrapers. They respect robots.txt: Google News disallows scraping, so it's skipped, and the portal list was verified with a feed-check script." |
| 6 | 1:35–2:10 | `tanya.html`: ask "Berapa titik panas di Kalimantan Tengah 24 jam terakhir?", then "kalau di Sumatera Selatan?" | "A local 3-billion-parameter model on a laptop GPU answers questions in Indonesian. It never writes SQL: it picks predefined queries, and the numbers come from the system. The green box shows the facts the answer is built on, and follow-up questions keep the context." |
| 7 | 2:10–2:30 | GitHub README → *Engineering log* table | "Most of the design came from real failures: a leaked-key risk, double-encoded JSON, shifted polygons, a model copying locations from its own prompt. Each one is documented with how it was caught and fixed. Thanks for watching." |

## Screenshot checklist for the README (save to `docs/img/`)

- `demo-risk.png`: public demo, *Risiko* tab open, a regency popup visible
- `tanya-data.png`: `tanya.html` with one answer and the *Ringkasan data* box
- `grafana-pipeline-ops.png`: Pipeline Ops dashboard, 6-hour range

Then uncomment the image block near the top of `README.md`.
