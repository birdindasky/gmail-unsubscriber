# -*- coding: utf-8 -*-
"""
Database module - SQLite state management.
Manages three tables: unsubscribe history, scan history, and the user whitelist.
"""

import os
import sqlite3
import logging
from datetime import datetime

import config

logger = logging.getLogger(__name__)


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initialize the database and create the required tables if missing."""
    conn = _get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS unsubscribed_senders (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_email    TEXT NOT NULL UNIQUE,
            sender_name     TEXT,
            unsubscribed_at TEXT NOT NULL,
            method          TEXT,
            success         INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS scan_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            scanned_at      TEXT NOT NULL,
            days            INTEGER,
            total_emails    INTEGER,
            candidates      INTEGER,
            unsubscribed    INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS user_whitelist (
            domain          TEXT PRIMARY KEY,
            added_at        TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()
    # Ensure the database file is 0o600 because it contains scan history and other PII
    try:
        os.chmod(config.DB_PATH, 0o600)
    except OSError:
        pass
    logger.debug("Database initialization complete")


def record_unsubscribe(sender_email: str, sender_name: str, method: str, success: bool) -> None:
    """Record an unsubscribe attempt. Existing records are replaced."""
    conn = _get_connection()
    conn.execute(
        """
        INSERT OR REPLACE INTO unsubscribed_senders
            (sender_email, sender_name, unsubscribed_at, method, success)
        VALUES (?, ?, ?, ?, ?)
        """,
        (sender_email, sender_name, datetime.now().isoformat(), method, int(success)),
    )
    conn.commit()
    conn.close()
    logger.debug(f"Saved unsubscribe record: {sender_email} ({'success' if success else 'failed'})")


def is_already_unsubscribed(sender_email: str) -> bool:
    """Check whether this sender has already been successfully unsubscribed."""
    conn = _get_connection()
    row = conn.execute(
        "SELECT id FROM unsubscribed_senders WHERE sender_email = ? AND success = 1",
        (sender_email,),
    ).fetchone()
    conn.close()
    return row is not None


def get_history(limit: int = 50) -> list[dict]:
    """Return unsubscribe history in reverse chronological order."""
    conn = _get_connection()
    rows = conn.execute(
        "SELECT * FROM unsubscribed_senders ORDER BY unsubscribed_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def record_scan(days: int, total_emails: int, candidates: int, unsubscribed: int) -> None:
    """Record summary stats for a scan run."""
    conn = _get_connection()
    conn.execute(
        """
        INSERT INTO scan_history (scanned_at, days, total_emails, candidates, unsubscribed)
        VALUES (?, ?, ?, ?, ?)
        """,
        (datetime.now().isoformat(), days, total_emails, candidates, unsubscribed),
    )
    conn.commit()
    conn.close()


def add_to_user_whitelist(domain: str) -> bool:
    """Add a domain to the user whitelist. Returns True if added, False if it already exists."""
    domain = domain.lower().strip()
    conn = _get_connection()
    try:
        conn.execute(
            "INSERT INTO user_whitelist (domain, added_at) VALUES (?, ?)",
            (domain, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()
        logger.info(f"Added domain to whitelist: {domain}")
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False


def get_user_whitelist() -> list[str]:
    """Return the list of user-defined whitelist domains."""
    conn = _get_connection()
    rows = conn.execute("SELECT domain FROM user_whitelist").fetchall()
    conn.close()
    return [r["domain"] for r in rows]
