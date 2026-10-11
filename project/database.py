from __future__ import annotations

"""
PostgreSQL persistence layer for Attijari Bank branch records.

This module is responsible for:
- Establishing a connection using config-provided settings.
- Creating the `branches` table if it does not exist.
- Inserting a batch of branch records.
"""

from typing import Iterable, Dict

import psycopg2
from psycopg2.extras import execute_batch
from loguru import logger

try:
    from .config import get_database_config
except ImportError:
    from config import get_database_config  # type: ignore


TABLE_DDL = """
CREATE TABLE IF NOT EXISTS branches (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    branch_type TEXT,
    address TEXT,
    postal_code TEXT,
    city TEXT,
    telephone TEXT,
    fax TEXT,
    email TEXT,
    latitude TEXT,
    longitude TEXT
);
"""


INSERT_SQL = """
INSERT INTO branches (
    name,
    branch_type,
    address,
    postal_code,
    city,
    telephone,
    fax,
    email,
    latitude,
    longitude
) VALUES (
    %(name)s,
    %(branch_type)s,
    %(address)s,
    %(postal_code)s,
    %(city)s,
    %(telephone)s,
    %(fax)s,
    %(email)s,
    %(latitude)s,
    %(longitude)s
);
"""


def initialise_database() -> None:
    """
    Ensure the target database and `branches` table exist.

    Connection parameters are loaded from environment variables via config.
    """
    cfg = get_database_config()
    if cfg is None:
        logger.warning("Database configuration missing; skipping table creation.")
        return

    conn = psycopg2.connect(
        host=cfg.host,
        port=cfg.port,
        dbname=cfg.dbname,
        user=cfg.user,
        password=cfg.password,
    )
    try:
        with conn, conn.cursor() as cur:
            cur.execute(TABLE_DDL)
        logger.info("Verified that table 'branches' exists.")
    finally:
        conn.close()


def insert_branches(records: Iterable[Dict[str, str]]) -> int:
    """
    Insert a sequence of branch dictionaries into PostgreSQL.

    Returns the number of successfully inserted rows.
    """
    cfg = get_database_config()
    if cfg is None:
        logger.warning("Database configuration missing; not inserting into PostgreSQL.")
        return 0

    records = list(records)
    if not records:
        return 0

    conn = psycopg2.connect(
        host=cfg.host,
        port=cfg.port,
        dbname=cfg.dbname,
        user=cfg.user,
        password=cfg.password,
    )
    try:
        with conn:
            with conn.cursor() as cur:
                execute_batch(cur, INSERT_SQL, records, page_size=100)
        logger.info("Inserted {} branches into PostgreSQL.", len(records))
        return len(records)
    finally:
        conn.close()

