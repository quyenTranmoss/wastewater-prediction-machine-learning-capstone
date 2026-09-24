"""
Load Quyen's 15-year forecasts into the database.

Quyen's model script should write a CSV with exactly these columns:

    city,year,target,predicted_value,lower_bound,upper_bound,model_name

    city            city name exactly as it appears in wastewater_costs_2017_2025.csv
    year            future year, e.g. 2026 ... 2040
    target          'res_fee_5k_gal' or 'com_fee_50k_gal'
    predicted_value predicted monthly bill in USD
    lower_bound     optional - leave blank if the model doesn't produce intervals
    upper_bound     optional
    model_name      'linear_regression' | 'random_forest' | 'xgboost'

Then run:
    python database/load_predictions.py path/to/predictions.csv

Re-running replaces that model's rows for those targets, so it is safe to
regenerate forecasts as often as needed.
"""
import csv
import sqlite3
import sys
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wastewater.db")
VALID_TARGETS = {"res_fee_5k_gal", "com_fee_50k_gal"}


def optional_float(v):
    return float(v) if v not in ("", None) else None


def main(csv_path):
    conn = sqlite3.connect(DB_PATH)
    city_id = {name: cid for cid, name in conn.execute("SELECT id, name FROM cities")}

    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # Validate before writing anything, so a bad file can't half-load.
    problems, unknown_cities = [], set()
    for i, r in enumerate(rows, start=2):  # row 1 is the header
        if r["city"] not in city_id:
            unknown_cities.add(r["city"])
        if r["target"] not in VALID_TARGETS:
            problems.append(f"  line {i}: target {r['target']!r} is not one of {sorted(VALID_TARGETS)}")
        try:
            float(r["predicted_value"])
            int(r["year"])
        except (ValueError, TypeError):
            problems.append(f"  line {i}: year/predicted_value not numeric -> {r}")
    for c in sorted(unknown_cities):
        problems.append(f"  city {c!r} is not in the cities table (check spelling against the CSV)")

    if problems:
        print(f"{len(problems)} problem(s) found - nothing was loaded:")
        print("\n".join(problems))
        sys.exit(1)

    pairs = {(r["model_name"], r["target"]) for r in rows}
    for model_name, target in pairs:
        conn.execute("DELETE FROM predictions WHERE model_name = ? AND target = ?",
                     (model_name, target))

    conn.executemany(
        """INSERT INTO predictions
           (city_id, year, target, predicted_value, lower_bound, upper_bound, model_name)
           VALUES (?,?,?,?,?,?,?)""",
        [(city_id[r["city"]], int(r["year"]), r["target"], float(r["predicted_value"]),
          optional_float(r.get("lower_bound")), optional_float(r.get("upper_bound")),
          r["model_name"]) for r in rows])
    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
    print(f"Loaded {len(rows)} predictions for {len(pairs)} model/target pair(s). "
          f"Table now holds {total} rows.")
    conn.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
