"""Tren teknologi dari GitHub Search API (resmi; scraping HTML GitHub tidak dipakai karena dilarang ketentuannya).

1. Jumlah repository baru per bahasa per hari: q="language:X created:YYYY-MM-DD" -> total_count
2. Repository teratas per topik (bintang, fork, issue) -> snapshot harian, sehingga pertumbuhan bintang terlihat
Batas Search API: 10 permintaan/menit tanpa token, 30 dengan token (env GITHUB_TOKEN). Jeda disesuaikan otomatis.
"""
from __future__ import annotations

import os
from datetime import datetime

from scrape_lib import Polite

API = "https://api.github.com/search/repositories"
LANGUAGES = ["Python", "JavaScript", "TypeScript", "Java", "Go", "Rust", "Kotlin", "PHP", "C#", "SQL"]
TOPICS = ["data-engineering", "apache-kafka", "clickhouse", "airflow", "bigquery", "web-scraping"]


def client() -> Polite:
    token = os.getenv("GITHUB_TOKEN", "")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return Polite(min_gap=2.2 if token else 6.5, respect_robots=False, headers=headers)


def parse_count(doc: dict, language: str, day: str) -> dict:
    return {"day": day, "language": language, "new_repos": int(doc.get("total_count", 0)),
            "incomplete": bool(doc.get("incomplete_results", False))}


def parse_repos(doc: dict, topic: str, snapshot_date: str) -> list[dict]:
    out = []
    for r in doc.get("items", []):
        out.append({"snapshot_date": snapshot_date, "topic": topic, "full_name": r.get("full_name", ""),
                    "stars": r.get("stargazers_count", 0), "forks": r.get("forks_count", 0),
                    "open_issues": r.get("open_issues_count", 0), "language": r.get("language") or "",
                    "created_at": (r.get("created_at") or "").replace("T", " ").rstrip("Z"),
                    "pushed_at": (r.get("pushed_at") or "").replace("T", " ").rstrip("Z"),
                    "description": (r.get("description") or "")[:300], "url": r.get("html_url", "")})
    return out


def fetch(day: str, snapshot_date: str, c: Polite | None = None, per_topic: int = 20) -> dict:
    c = c or client()
    counts, repos, errors, t0 = [], [], [], datetime.now()
    for lang in LANGUAGES:
        try:
            counts.append(parse_count(c.get(API, params={"q": f'language:"{lang}" created:{day}', "per_page": 1}).json(), lang, day))
        except Exception as e:  # noqa: BLE001
            errors.append(f"language {lang}: {e}"[:200])
    for topic in TOPICS:
        try:
            repos += parse_repos(c.get(API, params={"q": f"topic:{topic}", "sort": "stars", "order": "desc",
                                                   "per_page": per_topic}).json(), topic, snapshot_date)
        except Exception as e:  # noqa: BLE001
            errors.append(f"topic {topic}: {e}"[:200])
    return {"counts": counts, "repos": repos, "errors": errors, "ms": int((datetime.now() - t0).total_seconds() * 1000), "stats": c.stats}
