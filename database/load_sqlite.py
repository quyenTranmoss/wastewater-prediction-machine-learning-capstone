"""
Build the project's SQLite database from the cleaned CSV.

Usage (from the project root):
    python database/load_sqlite.py

Creates database/wastewater.db with:
    cities            one row per city
    wastewater_costs  one row per city per year (UNIQUE on city_id + year)
    users             login accounts (Hannah/Emily fill this in; passwords are hashed, never plain)
    model_metadata    which ML model is deployed, its accuracy, when it was trained (Quyen)

Re-running is safe: the data tables are rebuilt from the CSV; users/model_metadata are kept.
Adding a new year later = drop the PDF in OneDrive_1_9-5-2026/, run
data_cleaning/extract_pdfs.py, then run this script again. No UI change needed.
"""
import csv
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "..", "data_cleaning", "wastewater_costs_2017_2025.csv")
DB_PATH = os.path.join(HERE, "wastewater.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS cities (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS wastewater_costs (
    id                INTEGER PRIMARY KEY,
    city_id           INTEGER NOT NULL REFERENCES cities(id),
    year              INTEGER NOT NULL,
    population_group  TEXT,
    population        INTEGER,
    total_customers   INTEGER,
    res_fee_5k_gal    REAL,   -- residential monthly bill at 5,000 gal  (prediction target)
    res_fee_10k_gal   REAL,   -- NULL for 2024-2025
    com_fee_50k_gal   REAL,   -- commercial monthly bill at 50,000 gal (prediction target)
    com_fee_200k_gal  REAL,   -- NULL for 2024-2025
    UNIQUE (city_id, year)
);
CREATE INDEX IF NOT EXISTS idx_costs_year ON wastewater_costs(year);

-- 15-year forecasts produced by Quyen's trained model. One row per
-- city + future year + target. Re-running the model replaces rows for that
-- (model_name, target) pair rather than appending, so the table never doubles up.
CREATE TABLE IF NOT EXISTS predictions (
    id              INTEGER PRIMARY KEY,
    city_id         INTEGER NOT NULL REFERENCES cities(id),
    year            INTEGER NOT NULL,        -- future year, e.g. 2026-2040
    target          TEXT NOT NULL,           -- 'res_fee_5k_gal' or 'com_fee_50k_gal'
    predicted_value REAL NOT NULL,           -- predicted monthly bill in USD
    lower_bound     REAL,                    -- optional confidence interval
    upper_bound     REAL,
    model_name      TEXT NOT NULL,           -- matches model_metadata.model_name
    generated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (city_id, year, target, model_name)
);
CREATE INDEX IF NOT EXISTS idx_pred_city_year ON predictions(city_id, year);

CREATE TABLE IF NOT EXISTS users (
    id             INTEGER PRIMARY KEY,
    username       TEXT NOT NULL UNIQUE,
    password_hash  TEXT NOT NULL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS model_metadata (
    id          INTEGER PRIMARY KEY,
    model_name  TEXT NOT NULL,        -- e.g. 'random_forest', 'xgboost', 'linear_regression'
    target      TEXT NOT NULL,        -- 'res_fee_5k_gal' or 'com_fee_50k_gal'
    r2          REAL,
    rmse        REAL,
    mae         REAL,
    is_deployed INTEGER NOT NULL DEFAULT 0,
    trained_at  TEXT NOT NULL DEFAULT (datetime('now')),
    file_path   TEXT                  -- saved model file the backend loads
);
"""


def fee(v):
    """$0.00 in the survey means 'not reported', not a real price -> store NULL."""
    if v in ("", None):
        return None
    v = float(v)
    return None if v == 0 else v


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    # Rebuild data tables from scratch so re-runs never double-insert
    conn.execute("DELETE FROM wastewater_costs")
    conn.execute("DELETE FROM cities")

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    for name in sorted({r["city"] for r in rows}):
        conn.execute("INSERT INTO cities(name) VALUES (?)", (name,))
    city_id = {name: cid for cid, name in conn.execute("SELECT id, name FROM cities")}

    conn.executemany(
        """INSERT INTO wastewater_costs
           (city_id, year, population_group, population, total_customers,
            res_fee_5k_gal, res_fee_10k_gal, com_fee_50k_gal, com_fee_200k_gal)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        [(city_id[r["city"]], int(r["year"]), r["population_group"],
          int(r["population"]) if r["population"] else None,
          int(r["total_customers"]) if r["total_customers"] else None,
          fee(r["res_fee_5k_gal"]), fee(r["res_fee_10k_gal"]),
          fee(r["com_fee_50k_gal"]), fee(r["com_fee_200k_gal"])) for r in rows],
    )
    conn.commit()

    n_cities = conn.execute("SELECT COUNT(*) FROM cities").fetchone()[0]
    n_rows = conn.execute("SELECT COUNT(*) FROM wastewater_costs").fetchone()[0]
    print(f"Loaded {n_rows} cost rows for {n_cities} cities into {DB_PATH}")
    conn.close()


if __name__ == "__main__":
    main()
