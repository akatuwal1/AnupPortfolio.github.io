"""
Hacker News article collector and cleaner.

Fetches top stories from the Hacker News API, filters and deduplicates
them by URL, normalises metadata, and saves a clean JSON dataset.
Demonstrates API pagination, JSON processing, and data cleaning patterns.
"""

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
HN_API_BASE = "https://hacker-news.firebaseio.com/v0"
OUTPUT_FILE = Path("hn_clean_articles.json")

MIN_SCORE = 50          # drop low-signal stories
MAX_STORIES = 200       # how many top-story IDs to fetch
REQUEST_TIMEOUT = 10    # seconds per API call

EXCLUDED_DOMAINS = {    # domains to strip from the results
    "youtube.com",
    "twitter.com",
    "x.com",
    "reddit.com",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def get(url: str, retries: int = 3) -> dict | list | None:
    """GET with simple exponential back-off on failure."""
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            wait = 2 ** attempt
            log.warning("Attempt %d/%d failed (%s). Retrying in %ds.", attempt, retries, exc, wait)
            if attempt < retries:
                time.sleep(wait)
    log.error("All retries exhausted for: %s", url)
    return None


def fetch_top_story_ids(limit: int = MAX_STORIES) -> list[int]:
    ids = get(f"{HN_API_BASE}/topstories.json") or []
    return ids[:limit]


def fetch_story(story_id: int) -> dict | None:
    return get(f"{HN_API_BASE}/item/{story_id}.json")


# ---------------------------------------------------------------------------
# Cleaning and normalisation
# ---------------------------------------------------------------------------

def normalise_url(url: str) -> str:
    """Lowercase scheme/host, strip tracking params and fragments."""
    url = url.strip()
    parsed = urlparse(url)

    query_parts = [
        p for p in parsed.query.split("&")
        if p and not re.match(r"utm_|fbclid|gclid|ref=|source=", p, re.I)
    ]

    cleaned = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower().lstrip("www."),
        query="&".join(query_parts),
        fragment="",
    )
    return urlunparse(cleaned).rstrip("/")


def extract_domain(url: str) -> str:
    return urlparse(url).netloc.lstrip("www.").lower()


def clean_title(title: str) -> str:
    """Strip common HN title noise like [pdf], (2021), ask HN: prefix."""
    title = re.sub(r"\s*\[pdf\]", "", title, flags=re.I)
    title = re.sub(r"\s*\(\d{4}\)\s*$", "", title)
    title = re.sub(r"^(ask|show|tell)\s+hn:\s*", "", title, flags=re.I)
    return title.strip()


def is_valid_story(story: dict) -> bool:
    """Keep only link-type stories that meet the quality bar."""
    return (
        story.get("type") == "story"
        and "url" in story
        and story.get("score", 0) >= MIN_SCORE
        and not story.get("dead")
        and not story.get("deleted")
    )


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def collect_articles() -> list[dict]:
    log.info("Fetching top %d story IDs...", MAX_STORIES)
    ids = fetch_top_story_ids()
    log.info("Got %d IDs. Fetching story details...", len(ids))

    seen_urls: set[str] = set()
    articles: list[dict] = []

    for story_id in ids:
        story = fetch_story(story_id)
        if not story or not is_valid_story(story):
            continue

        norm_url = normalise_url(story["url"])
        domain = extract_domain(norm_url)

        if domain in EXCLUDED_DOMAINS:
            log.debug("Excluded domain: %s", domain)
            continue

        if norm_url in seen_urls:
            log.debug("Duplicate URL skipped: %s", norm_url)
            continue

        seen_urls.add(norm_url)
        articles.append({
            "id": story["id"],
            "title": clean_title(story.get("title", "")),
            "url": norm_url,
            "domain": domain,
            "score": story.get("score", 0),
            "comments": story.get("descendants", 0),
            "author": story.get("by", ""),
            "published_at": datetime.fromtimestamp(
                story.get("time", 0), tz=timezone.utc
            ).isoformat(),
        })

    # Sort by score descending
    articles.sort(key=lambda a: a["score"], reverse=True)
    return articles


def save(articles: list[dict], path: Path) -> None:
    path.write_text(json.dumps(articles, indent=2, ensure_ascii=False))
    log.info("Saved %d articles to %s", len(articles), path)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    log.info("=== HN article collector started ===")
    articles = collect_articles()

    if not articles:
        log.warning("No articles collected.")
        return

    log.info("Clean articles: %d", len(articles))
    save(articles, OUTPUT_FILE)

    # Quick summary
    top5 = articles[:5]
    log.info("Top 5 stories:")
    for i, a in enumerate(top5, 1):
        log.info("  %d. [%d pts] %s", i, a["score"], a["title"])

    log.info("=== Done ===")


if __name__ == "__main__":
    main()
