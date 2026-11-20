"""Load forecasts and model evaluation metadata into the project SQLite DB.

Run from the repository root:
    python database/load_predictions.py ml/outputs/predictions.csv ml/outputs/model_metrics.csv

The metadata file is important: database/queries.py only returns forecasts whose
model_metadata row has is_deployed = 1.
"""
from __future__ import annotations

import csv
import math
import os
import sqlite3
import sys
from pathlib import Path

# Vercel's app folder is read-only, so there the database lives in /tmp.
# WASTEWATER_DB_PATH overrides both defaults.
DB_PATH = os.environ.get("WASTEWATER_DB_PATH") or (
    "/tmp/wastewater.db" if os.environ.get("VERCEL")
    else os.path.join(os.path.dirname(os.path.abspath(__file__)), "wastewater.db"))
VALID_TARGETS = {"res_fee_5k_gal", "com_fee_50k_gal"}
PREDICTION_COLUMNS = {
    "city", "year", "target", "predicted_value",
    "lower_bound", "upper_bound", "model_name",
}
METADATA_COLUMNS = {"model_name", "target", "r2", "rmse", "mae", "is_deployed"}


def read_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def optional_float(value: str | None) -> float | None:
    if value in ("", None):
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Expected a finite number, got {value!r}")
    return number


def main(predictions_path: str, metrics_path: str) -> None:
    predictions = read_csv(predictions_path)
    metadata = read_csv(metrics_path)

    if not predictions:
        raise ValueError("The predictions CSV is empty.")
    if not metadata:
        raise ValueError("The model metrics CSV is empty.")

    missing_prediction_columns = PREDICTION_COLUMNS - set(predictions[0])
    missing_metadata_columns = METADATA_COLUMNS - set(metadata[0])
    if missing_prediction_columns:
        raise ValueError(f"Predictions CSV is missing columns: {sorted(missing_prediction_columns)}")
    if missing_metadata_columns:
        raise ValueError(f"Metrics CSV is missing columns: {sorted(missing_metadata_columns)}")

    conn = sqlite3.connect(DB_PATH)
    try:
        city_ids = {
            name: city_id
            for city_id, name in conn.execute("SELECT id, name FROM cities")
        }

        problems: list[str] = []
        unknown_cities: set[str] = set()
        prediction_keys: set[tuple] = set()
        metadata_targets: set[str] = set()
        deployed_by_target: dict[str, int] = {}
        metadata_keys: set[tuple[str, str]] = set()

        for line, row in enumerate(predictions, start=2):
            if row["city"] not in city_ids:
                unknown_cities.add(row["city"])
            if row["target"] not in VALID_TARGETS:
                problems.append(f"line {line}: invalid target {row['target']!r}")
                continue
            try:
                year = int(row["year"])
                value = float(row["predicted_value"])
                if not math.isfinite(value) or value < 0:
                    raise ValueError("predicted_value must be a finite, non-negative number")
                optional_float(row.get("lower_bound"))
                optional_float(row.get("upper_bound"))
            except (TypeError, ValueError) as exc:
                problems.append(f"line {line}: {exc}")
                continue
            key = (row["city"], year, row["target"], row["model_name"])
            if key in prediction_keys:
                problems.append(f"line {line}: duplicate prediction key {key}")
            prediction_keys.add(key)

        for city in sorted(unknown_cities):
            problems.append(f"unknown city {city!r}; spelling must match the cities table")

        for line, row in enumerate(metadata, start=2):
            target = row["target"]
            model_name = row["model_name"]
            if target not in VALID_TARGETS:
                problems.append(f"metrics line {line}: invalid target {target!r}")
                continue
            metadata_targets.add(target)
            key = (model_name, target)
            if key in metadata_keys:
                problems.append(f"metrics line {line}: duplicate model/target pair {key}")
            metadata_keys.add(key)
            try:
                for metric in ("r2", "rmse", "mae"):
                    optional_float(row.get(metric))
                deployed = int(row["is_deployed"])
                if deployed not in (0, 1):
                    raise ValueError("is_deployed must be 0 or 1")
                deployed_by_target[target] = deployed_by_target.get(target, 0) + deployed
            except (TypeError, ValueError) as exc:
                problems.append(f"metrics line {line}: {exc}")

        for target in metadata_targets:
            if deployed_by_target.get(target, 0) != 1:
                problems.append(
                    f"target {target!r} must have exactly one deployed model; "
                    f"found {deployed_by_target.get(target, 0)}"
                )

        deployed_pairs = {
            (row["model_name"], row["target"])
            for row in metadata
            if int(row["is_deployed"]) == 1
        }
        prediction_pairs = {(row["model_name"], row["target"]) for row in predictions}
        if prediction_pairs != deployed_pairs:
            problems.append(
                "prediction model/target pairs must exactly match the deployed "
                f"metadata pairs; predictions={sorted(prediction_pairs)}, "
                f"deployed={sorted(deployed_pairs)}"
            )

        if problems:
            raise ValueError("Validation failed; nothing was loaded:\n- " + "\n- ".join(problems))

        # Replace only the model/target pairs represented by this training run.
        # This avoids leaving old predictions or duplicate metadata behind.
        for model_name, target in prediction_pairs:
            conn.execute(
                "DELETE FROM predictions WHERE model_name = ? AND target = ?",
                (model_name, target),
            )
        for target in metadata_targets:
            conn.execute("DELETE FROM model_metadata WHERE target = ?", (target,))

        conn.executemany(
            """INSERT INTO predictions
               (city_id, year, target, predicted_value, lower_bound, upper_bound, model_name)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    city_ids[row["city"]],
                    int(row["year"]),
                    row["target"],
                    float(row["predicted_value"]),
                    optional_float(row.get("lower_bound")),
                    optional_float(row.get("upper_bound")),
                    row["model_name"],
                )
                for row in predictions
            ],
        )

        conn.executemany(
            """INSERT INTO model_metadata
               (model_name, target, r2, rmse, mae, is_deployed)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (
                    row["model_name"],
                    row["target"],
                    optional_float(row.get("r2")),
                    optional_float(row.get("rmse")),
                    optional_float(row.get("mae")),
                    int(row["is_deployed"]),
                )
                for row in metadata
            ],
        )

        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
        print(f"Loaded {len(predictions):,} predictions.")
        print(f"Loaded {len(metadata):,} model-metadata rows.")
        print(f"Predictions table now contains {total:,} rows.")
        print("One model per target is marked deployed; API forecast queries can now return results.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
