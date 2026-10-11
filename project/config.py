from __future__ import annotations

"""
Global configuration for the Attijari Bank Tunisia branch scraper.

This module centralises:
- URLs
- timing / retry settings
- database configuration (via environment variables)
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
import os


# Load variables from a local .env file if present.
load_dotenv()


BASE_URL: str = "https://www.attijaribank.com.tn"
BRANCH_DIRECTORY_PATH: str = "/fr/reseaux-dagence"
BRANCH_DIRECTORY_URL: str = f"{BASE_URL}{BRANCH_DIRECTORY_PATH}"
ROBOTS_TXT_URL: str = f"{BASE_URL}/robots.txt"


# HTTP / scraping behaviour.
REQUEST_TIMEOUT_SECONDS: int = 20
MAX_RETRIES: int = 3
RETRY_BACKOFF_SECONDS: float = 1.5
POLITE_DELAY_SECONDS: float = 1.0


# Playwright configuration.
PLAYWRIGHT_HEADLESS: bool = True
PLAYWRIGHT_TIMEOUT_MS: int = 30_000


# Output paths.
PROJECT_ROOT: Path = Path(__file__).resolve().parent
OUTPUT_DIR: Path = PROJECT_ROOT / "output"
CSV_PATH: Path = OUTPUT_DIR / "branches.csv"
XLSX_PATH: Path = OUTPUT_DIR / "branches.xlsx"
JSON_PATH: Path = OUTPUT_DIR / "branches.json"


@dataclass
class DatabaseConfig:
    """Simple container for PostgreSQL connection settings."""

    host: str
    port: int
    dbname: str
    user: str
    password: str


def get_database_config() -> Optional[DatabaseConfig]:
    """
    Read PostgreSQL settings from environment variables and return a DatabaseConfig.

    Expected variables (you can set them in a local .env file):
      - POSTGRES_HOST
      - POSTGRES_PORT
      - POSTGRES_DB
      - POSTGRES_USER
      - POSTGRES_PASSWORD
    """
    host = os.getenv("POSTGRES_HOST")
    port_raw = os.getenv("POSTGRES_PORT")
    dbname = os.getenv("POSTGRES_DB")
    user = os.getenv("POSTGRES_USER")
    password = os.getenv("POSTGRES_PASSWORD")

    if not all([host, port_raw, dbname, user, password]):
        return None

    try:
        port = int(port_raw)
    except ValueError:
        raise ValueError("POSTGRES_PORT must be an integer.")

    return DatabaseConfig(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
    )


def ensure_output_dir() -> None:
    """Create the output directory if it does not exist."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

