"""Privacy-preserving, opt-in disease lookup analytics."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from backend.data_sources import normalize_disease

DEFAULT_ANALYTICS_DB = Path(__file__).resolve().parent.parent / "data" / "analytics.db"

def analytics_db_path() -> Path:
    return Path(os.getenv("ANALYTICS_DB_PATH", str(DEFAULT_ANALYTICS_DB)))

@contextmanager
def connection():
    path = analytics_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    try:
        db.execute("PRAGMA busy_timeout = 5000")
        yield db
        db.commit()
    finally:
        db.close()

def initialize_analytics() -> None:
    with connection() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS disease_lookup_stats (
            disease_key TEXT NOT NULL, lookup_date TEXT NOT NULL,
            lookup_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (disease_key, lookup_date), CHECK (lookup_count >= 0)
        )""")

def record_disease_lookup(disease: str) -> str:
    """Increment today's aggregate; no identifying information is accepted."""
    canonical = normalize_disease(disease)
    with connection() as db:
        db.execute("""INSERT INTO disease_lookup_stats
            (disease_key, lookup_date, lookup_count) VALUES (?, ?, 1)
            ON CONFLICT(disease_key, lookup_date)
            DO UPDATE SET lookup_count = lookup_count + 1""",
            (canonical, date.today().isoformat()))
    return canonical
