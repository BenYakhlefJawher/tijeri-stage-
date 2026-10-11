from __future__ import annotations

"""
Main entry point for scraping the Attijari Bank Tunisia branch directory.

This script:
- Respects robots.txt.
- Tries a fast `requests + BeautifulSoup` mode first.
- Falls back to Playwright if static HTML does not expose branch data.
- Extracts, cleans, deduplicates, and exports branches.
- Inserts data into PostgreSQL.
- Prints a short summary at the end.
"""

from typing import List, Dict, Tuple, Any
import sys
import time
from urllib.parse import urljoin
import urllib.robotparser as robotparser

import pandas as pd
import requests
from loguru import logger
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from tqdm import tqdm

try:
    # Package mode: python -m project.scraper
    from . import parser
    from .config import (
        BRANCH_DIRECTORY_URL,
        BRANCH_DIRECTORY_PATH,
        ROBOTS_TXT_URL,
        REQUEST_TIMEOUT_SECONDS,
        MAX_RETRIES,
        RETRY_BACKOFF_SECONDS,
        POLITE_DELAY_SECONDS,
        PLAYWRIGHT_HEADLESS,
        PLAYWRIGHT_TIMEOUT_MS,
        CSV_PATH,
        XLSX_PATH,
        JSON_PATH,
        ensure_output_dir,
    )
    from .database import initialise_database, insert_branches
except ImportError:
    # Script mode: python scraper.py
    import parser  # type: ignore
    from config import (  # type: ignore
        BRANCH_DIRECTORY_URL,
        BRANCH_DIRECTORY_PATH,
        ROBOTS_TXT_URL,
        REQUEST_TIMEOUT_SECONDS,
        MAX_RETRIES,
        RETRY_BACKOFF_SECONDS,
        POLITE_DELAY_SECONDS,
        PLAYWRIGHT_HEADLESS,
        PLAYWRIGHT_TIMEOUT_MS,
        CSV_PATH,
        XLSX_PATH,
        JSON_PATH,
        ensure_output_dir,
    )
    from database import initialise_database, insert_branches  # type: ignore


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


def configure_logging() -> None:
    """Set up loguru logging for the scraper."""
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{message}</cyan>",
    )


def create_session() -> requests.Session:
    """Create a requests Session with retry and timeout behaviour."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=RETRY_BACKOFF_SECONDS,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD", "OPTIONS"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def is_allowed_by_robots(user_agent: str, path: str) -> bool:
    """
    Determine whether scraping the given path is allowed by robots.txt.
    """
    rp = robotparser.RobotFileParser()
    rp.set_url(ROBOTS_TXT_URL)
    try:
        rp.read()
    except Exception as exc:
        logger.warning("Could not read robots.txt: {}", exc)
        return True
    return rp.can_fetch(user_agent, path)


def fetch_html_via_requests(session: requests.Session, url: str) -> str:
    """
    Fetch static HTML via requests.
    Raises requests.RequestException on failure.
    """
    logger.info("Fetching (requests) {}", url)
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.text


def fetch_html_via_playwright(url: str) -> str:
    """
    Fetch fully rendered HTML via Playwright.
    """
    logger.info("Fetching (Playwright) {}", url)
    try:
        from playwright.sync_api import (  # imported lazily on purpose
            sync_playwright,
            TimeoutError as PlaywrightTimeoutError,  # noqa: F401
        )
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is not installed. Install it with: pip install playwright "
            "and run: python -m playwright install"
        ) from exc

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=PLAYWRIGHT_HEADLESS)
        try:
            page = browser.new_page(user_agent=USER_AGENT)
            page.set_default_timeout(PLAYWRIGHT_TIMEOUT_MS)
            page.goto(url, wait_until="networkidle")
            # Give the page a moment to finish any dynamic rendering.
            time.sleep(2.0)
            html = page.content()
        finally:
            browser.close()
    return html


def discover_pagination_urls(html: str, base_url: str) -> List[str]:
    """
    Extract additional page URLs, if the directory is paginated.

    This performs a best-effort search for anchor tags that look like
    pagination links (by CSS class or rel attribute).
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")

    candidates = soup.select(
        "ul.pagination a, nav.pager a, a.page-link, a[rel='next'], a[rel='prev']"
    )
    urls = {base_url}

    for a in candidates:
        href = a.get("href")
        if not href:
            continue
        full = urljoin(base_url, href)
        urls.add(full)

    return sorted(urls)


def scrape_pages(
    initial_html: str,
    session: requests.Session,
    use_playwright: bool,
    base_url: str,
) -> List[Dict[str, str]]:
    """
    Scrape all pages (single or paginated) using either requests or Playwright.
    """
    # Discover page URLs from the first page.
    page_urls = discover_pagination_urls(initial_html, base_url)
    logger.info("Discovered {} page URL(s) in the directory.", len(page_urls))

    all_raw_branches: List[Dict[str, str]] = []

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    except ImportError:
        PlaywrightTimeoutError = Exception  # type: ignore[assignment]

    for url in tqdm(page_urls, desc="Scraping pages", unit="page"):
        if url == base_url:
            html = initial_html
        else:
            if use_playwright:
                try:
                    html = fetch_html_via_playwright(url)
                except PlaywrightTimeoutError as exc:
                    logger.error("Playwright timed out for {}: {}", url, exc)
                    continue
            else:
                try:
                    html = fetch_html_via_requests(session, url)
                except requests.RequestException as exc:
                    logger.error("Requests failed for {}: {}", url, exc)
                    continue

        raw_branches = parser.parse_branches_from_html(html)
        logger.info("Parsed {} raw branches from {}", len(raw_branches), url)
        all_raw_branches.extend(raw_branches)

        time.sleep(POLITE_DELAY_SECONDS)

    return all_raw_branches


def choose_scraping_mode(session: requests.Session) -> Tuple[bool, str]:
    """
    Decide whether Playwright is required.

    Strategy:
      1. Try a simple requests GET.
      2. Parse the HTML. If we find any branches, stay in requests mode.
      3. If not, fall back to Playwright.

    Returns (use_playwright, initial_html).
    """
    try:
        html = fetch_html_via_requests(session, BRANCH_DIRECTORY_URL)
        raw_branches = parser.parse_branches_from_html(html)
        if raw_branches:
            logger.info(
                "Static HTML already contains branch data; Playwright not required."
            )
            return False, html
        logger.info(
            "Static HTML did not yield branches; switching to Playwright rendering."
        )
    except requests.RequestException as exc:
        logger.warning(
            "Requests mode failed for the initial page; falling back to Playwright: {}",
            exc,
        )
        html = ""

    try:
        html = fetch_html_via_playwright(BRANCH_DIRECTORY_URL)
        return True, html
    except RuntimeError as exc:
        logger.warning("Playwright unavailable; continuing with requests mode only: {}", exc)
        try:
            html = fetch_html_via_requests(session, BRANCH_DIRECTORY_URL)
            return False, html
        except requests.RequestException as req_exc:
            logger.error("Requests mode also failed: {}", req_exc)
            raise


def export_to_files(records: List[Dict[str, str]]) -> None:
    """
    Write the branch records to CSV, Excel, and JSON.
    """
    ensure_output_dir()
    df = pd.DataFrame(records)

    df.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
    df.to_excel(XLSX_PATH, index=False, engine="openpyxl")
    df.to_json(JSON_PATH, orient="records", force_ascii=False, indent=2)

    logger.info("Exported data to:")
    logger.info("  CSV  : {}", CSV_PATH)
    logger.info("  XLSX : {}", XLSX_PATH)
    logger.info("  JSON : {}", JSON_PATH)


def main() -> None:
    """Run the full scraping workflow."""
    configure_logging()

    if not is_allowed_by_robots(USER_AGENT, BRANCH_DIRECTORY_PATH):
        logger.error(
            "Scraping {} is disallowed by robots.txt. Aborting.", BRANCH_DIRECTORY_PATH
        )
        sys.exit(1)

    session = create_session()

    use_playwright, initial_html = choose_scraping_mode(session)

    raw_branches = scrape_pages(
        initial_html=initial_html,
        session=session,
        use_playwright=use_playwright,
        base_url=BRANCH_DIRECTORY_URL,
    )

    # Clean and deduplicate.
    cleaned = [parser.clean_branch(b) for b in raw_branches]
    deduped = parser.deduplicate_branches(cleaned)

    total_raw = len(cleaned)
    total_unique = len(deduped)
    duplicates_removed = total_raw - total_unique

    records_dicts = parser.branches_to_dicts(deduped)

    # Export to files.
    export_to_files(records_dicts)

    # PostgreSQL.
    initialise_database()
    inserted_rows = insert_branches(records_dicts)

    # Summary statistics.
    unique_cities = {b.city for b in deduped if b.city}

    print()  # final human-friendly summary
    print("Scraping summary")
    print("================")
    print(f"Total branches scraped          : {total_unique}")
    print(f"Total distinct cities           : {len(unique_cities)}")
    print(f"Duplicate records removed       : {duplicates_removed}")
    print(f"Rows inserted into PostgreSQL   : {inserted_rows}")


if __name__ == "__main__":
    main()

