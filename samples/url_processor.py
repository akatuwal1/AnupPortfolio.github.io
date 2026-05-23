"""
Email-triggered URL processing pipeline.

Monitors an inbox for a forwarded email with a zipped JSON attachment,
cleans and deduplicates the URLs inside, then submits each one to a
supplied API endpoint. Designed to run on a Mon/Wed/Fri schedule.
"""

import imaplib
import email
import zipfile
import json
import io
import logging
import re
import time
from urllib.parse import urlparse, urlunparse
import requests
import schedule

# ---------------------------------------------------------------------------
# Configuration  (replace values or load from environment variables)
# ---------------------------------------------------------------------------
IMAP_HOST = "imap.gmail.com"
IMAP_USER = "your_email@gmail.com"
IMAP_PASS = "your_app_password"
SENDER_FILTER = "forwarded@example.com"   # only process mail from this sender

API_ENDPOINT = "https://api.example.com/submit"
API_KEY = "your_api_key"

# URLs containing any of these substrings are dropped before submission
EXCLUDED_PATTERNS = [
    "example.com",
    "localhost",
    "127.0.0.1",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Step 1 – Fetch the latest unread email with a ZIP attachment
# ---------------------------------------------------------------------------

def fetch_zip_attachment() -> bytes | None:
    """
    Connect to the inbox, find the most recent unread email from
    SENDER_FILTER that has a .zip attachment, mark it as read, and
    return the raw ZIP bytes. Returns None if no matching email is found.
    """
    with imaplib.IMAP4_SSL(IMAP_HOST) as conn:
        conn.login(IMAP_USER, IMAP_PASS)
        conn.select("INBOX")

        _, ids = conn.search(None, f'(UNSEEN FROM "{SENDER_FILTER}")')
        mail_ids = ids[0].split()

        if not mail_ids:
            log.info("No new emails from %s.", SENDER_FILTER)
            return None

        # Process the most recent matching message
        _, data = conn.fetch(mail_ids[-1], "(RFC822)")
        raw = data[0][1]
        msg = email.message_from_bytes(raw)

        for part in msg.walk():
            filename = part.get_filename() or ""
            if filename.lower().endswith(".zip"):
                conn.store(mail_ids[-1], "+FLAGS", "\\Seen")
                log.info("Found ZIP attachment: %s", filename)
                return part.get_payload(decode=True)

    log.warning("Email found but no .zip attachment.")
    return None


# ---------------------------------------------------------------------------
# Step 2 – Extract and parse the JSON inside the ZIP
# ---------------------------------------------------------------------------

def extract_urls_from_zip(zip_bytes: bytes) -> list[str]:
    """
    Open a ZIP from raw bytes, locate the first .json file inside,
    and return the list of URL strings it contains.

    Expected JSON shape:  ["https://...", "https://...", ...]
    or:                   {"urls": ["https://...", ...]}
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        json_files = [n for n in zf.namelist() if n.lower().endswith(".json")]
        if not json_files:
            raise ValueError("No JSON file found inside the ZIP.")

        with zf.open(json_files[0]) as f:
            payload = json.load(f)

    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and "urls" in payload:
        return payload["urls"]

    raise ValueError(f"Unexpected JSON structure: {type(payload)}")


# ---------------------------------------------------------------------------
# Step 3 – Clean and deduplicate URLs
# ---------------------------------------------------------------------------

def normalize_url(url: str) -> str:
    """
    Lowercase scheme and host, strip trailing slashes and common tracking
    query parameters, and remove URL fragments.
    """
    url = url.strip()
    parsed = urlparse(url)

    # Drop fragment, lowercase scheme + host
    cleaned = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        fragment="",
    )

    # Remove UTM and similar tracking params
    if cleaned.query:
        kept = [
            p for p in cleaned.query.split("&")
            if not re.match(r"utm_|fbclid|gclid|mc_", p, re.I)
        ]
        cleaned = cleaned._replace(query="&".join(kept))

    return urlunparse(cleaned).rstrip("/")


def is_valid_url(url: str) -> bool:
    try:
        p = urlparse(url)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False


def clean_urls(raw_urls: list[str]) -> list[str]:
    """
    Normalize, validate, remove excluded patterns, and deduplicate.
    Returns a stable-ordered list of clean URLs.
    """
    seen: set[str] = set()
    clean: list[str] = []

    for url in raw_urls:
        try:
            normalized = normalize_url(url)
        except Exception:
            log.debug("Could not normalize, skipping: %s", url)
            continue

        if not is_valid_url(normalized):
            log.debug("Invalid URL skipped: %s", normalized)
            continue

        if any(pat in normalized for pat in EXCLUDED_PATTERNS):
            log.debug("Excluded pattern match, skipping: %s", normalized)
            continue

        if normalized in seen:
            log.debug("Duplicate skipped: %s", normalized)
            continue

        seen.add(normalized)
        clean.append(normalized)

    log.info("URLs after cleaning: %d (from %d raw)", len(clean), len(raw_urls))
    return clean


# ---------------------------------------------------------------------------
# Step 4 – Submit URLs to the API
# ---------------------------------------------------------------------------

def submit_to_api(urls: list[str]) -> None:
    """
    POST each URL to the configured API endpoint.
    Retries up to 3 times on transient errors with exponential back-off.
    """
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {API_KEY}"})

    for url in urls:
        for attempt in range(1, 4):
            try:
                resp = session.post(API_ENDPOINT, json={"url": url}, timeout=10)
                resp.raise_for_status()
                log.info("Submitted (%d): %s", resp.status_code, url)
                break
            except requests.RequestException as exc:
                wait = 2 ** attempt
                log.warning("Attempt %d failed for %s: %s. Retrying in %ds.",
                            attempt, url, exc, wait)
                if attempt < 3:
                    time.sleep(wait)
                else:
                    log.error("Giving up on: %s", url)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_pipeline() -> None:
    log.info("=== Pipeline started ===")

    zip_bytes = fetch_zip_attachment()
    if zip_bytes is None:
        log.info("Nothing to process.")
        return

    raw_urls = extract_urls_from_zip(zip_bytes)
    log.info("Raw URLs extracted: %d", len(raw_urls))

    clean = clean_urls(raw_urls)
    if not clean:
        log.warning("No URLs survived cleaning.")
        return

    submit_to_api(clean)
    log.info("=== Pipeline finished ===")


# ---------------------------------------------------------------------------
# Scheduling  (Mon / Wed / Fri)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    schedule.every().monday.at("09:00").do(run_pipeline)
    schedule.every().wednesday.at("09:00").do(run_pipeline)
    schedule.every().friday.at("09:00").do(run_pipeline)

    log.info("Scheduler running — waiting for Mon/Wed/Fri at 09:00 ...")
    while True:
        schedule.run_pending()
        time.sleep(60)
