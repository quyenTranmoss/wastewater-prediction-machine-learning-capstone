"""Build the SQLite database on demand, so a fresh server needs no committed .db file.

main.py calls ensure_database() when the API starts. On Vercel the app folder is
read-only and nothing persists between servers, so every cold start rebuilds the
database in /tmp from files that ARE in the repository:

    data_cleaning/wastewater_costs_2017_2025_checked.csv   historical fees
    ml/outputs/predictions.csv, ml/outputs/model_metrics.csv   forecasts + metrics

Login accounts come from the APP_USERS environment variable, a JSON object of
username -> Argon2 hash. Only hashes are accepted, so no password (and no .db file
containing hashes) ever has to live in the repository:

    python database/users.py hash alice
    -> {"alice": "$argon2id$v=19$..."}      paste this as the APP_USERS value

Locally nothing changes: an existing database is left alone. It is only built when
the file is missing, when running on Vercel, or when AUTO_BUILD_DB=1.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from . import load_predictions, load_sqlite

ROOT = Path(__file__).resolve().parents[1]
PREDICTIONS_CSV = ROOT / "ml" / "outputs" / "predictions.csv"
METRICS_CSV = ROOT / "ml" / "outputs" / "model_metrics.csv"
DB_PATH = load_sqlite.DB_PATH
REQUIRED_TABLES = ("wastewater_costs", "predictions", "model_metadata")


def _is_ready() -> bool:
    if not os.path.exists(DB_PATH):
        return False
    conn = sqlite3.connect(DB_PATH)
    try:
        return all(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0
                   for table in REQUIRED_TABLES)
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def seed_users() -> int:
    """Create/refresh accounts from APP_USERS. Returns how many were written."""
    raw = os.environ.get("APP_USERS", "").strip()
    if not raw:
        return 0
    hint = ('APP_USERS must be JSON like {"alice": "<argon2 hash>"}; create it with '
            "`python database/users.py hash alice`.")
    try:
        users = json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError(hint) from None
    if not isinstance(users, dict) or not users:
        raise RuntimeError(hint)
    for name, hashed in users.items():
        if not str(name).strip() or not isinstance(hashed, str) or not hashed.startswith("$argon2"):
            # Never echo the value: it might be a plain password pasted by mistake.
            raise RuntimeError("Every APP_USERS value must be an Argon2 hash, never a plain "
                               "password. " + hint)
    conn = sqlite3.connect(DB_PATH)
    try:
        with conn:
            conn.executemany(
                "INSERT INTO users (username, password_hash) VALUES (?, ?) "
                "ON CONFLICT(username) DO UPDATE SET password_hash = excluded.password_hash",
                list(users.items()))
    finally:
        conn.close()
    return len(users)


def ensure_database() -> None:
    allowed = (bool(os.environ.get("VERCEL")) or os.environ.get("AUTO_BUILD_DB") == "1"
               or not os.path.exists(DB_PATH))
    if allowed and not _is_ready():
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        load_sqlite.main()
        load_predictions.main(str(PREDICTIONS_CSV), str(METRICS_CSV))
    if os.path.exists(DB_PATH):
        seed_users()


if __name__ == "__main__":  # python -m database.bootstrap
    ensure_database()
    print(f"Database ready at {DB_PATH}")
