"""Train, evaluate and forecast wastewater fees (residential and commercial).

Run from the repository root:
    python ml/train_models.py

Input:
    data_cleaning/wastewater_costs_2017_2025_checked.csv

Outputs (under ml/outputs):
    predictions.csv                  2026-2040 forecasts + 80% intervals (loaded into the DB)
    model_metrics.csv                one row per model/target, exactly one is_deployed
    model_selection.csv              which model/damping won and why
    cross_validation_summary.csv     multi-cutoff backtest metrics, horizons >= 3 years
                                     (the basis for model selection and model_metrics.csv)
    cross_validation_by_horizon.csv  same, split by forecast horizon
    final_test_metrics.csv           untouched 2024-2025 test
    final_test_by_horizon.csv        same, split by forecast horizon
    cleaning_report.csv              every fee value removed as a likely typo
    model_config.json                deployed model, damping and interval table

Pipeline: clean -> build (origin, target-year) pairs -> backtest all models ->
select with CV only -> report on final test -> refit on everything -> forecast.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # lets `python ml/train_models.py` find the ml package
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from ml.evaluate_models import (
    CV_CUTOFFS, CV_MAX_TARGET_YEAR, FINAL_CUTOFF, FINAL_TARGET_YEARS,
    SELECTION_MIN_HORIZON, backtest, choose_models, interval_coverage, score_against_benchmark,
    summarize, summarize_by_horizon,
)
from ml.forecast import (
    LAST_VALUE, MODEL_NAMES, GrowthModel, build_interval_table, forecast_cities,
    interval_bounds,
)
from ml.prepare_data import TARGETS, build_pairs, clean_target, latest_origins, load_raw

OUTPUT_DIR = ROOT / "ml" / "outputs"
FORECAST_YEARS = list(range(2026, 2041))


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data = load_raw()

    cleaned, pairs_by_target, removals = {}, {}, []
    for target in TARGETS:
        cleaned[target], removed = clean_target(data, target)
        pairs_by_target[target] = build_pairs(cleaned[target], target)
        removals.append(removed)
        print(f"{target}: {len(cleaned[target])} valid rows, {len(removed)} spikes removed, "
              f"{len(pairs_by_target[target])} training pairs")
    pd.concat(removals).to_csv(OUTPUT_DIR / "cleaning_report.csv", index=False)

    cv_records, final_records = [], []
    for target in TARGETS:
        print(f"Backtesting {target}...")
        pairs = pairs_by_target[target]
        cv_records.append(backtest(pairs, target, CV_CUTOFFS, CV_MAX_TARGET_YEAR))
        final_records.append(backtest(pairs, target, [FINAL_CUTOFF], max(FINAL_TARGET_YEARS)))
    cv = pd.concat(cv_records, ignore_index=True)
    final = pd.concat(final_records, ignore_index=True)

    # Selection uses cross-validation only, on horizons relevant to 15-year forecasts.
    cv_scored = score_against_benchmark(summarize(cv[cv["h"] >= SELECTION_MIN_HORIZON]))
    chosen = choose_models(cv_scored)

    # Report every model at its own best CV damping on the untouched final test.
    best_damping = (cv_scored.sort_values("score").groupby(["target", "model_name"])
                    .first()["damping"].to_dict())
    final = final[[best_damping[(t, m)] == d for t, m, d in
                   zip(final["target"], final["model_name"], final["damping"])]]
    final_summary = summarize(final)
    final_scored = score_against_benchmark(final_summary)

    selection_rows, metadata_rows, predictions, config = [], [], [], {}
    for target in TARGETS:
        name, damping = chosen[target]
        cv_best = cv_scored[(cv_scored["target"] == target) & (cv_scored["model_name"] == name)
                            & (cv_scored["damping"] == damping)].iloc[0]
        print(f"{target}: deployed {name} (damping {damping}), CV score {cv_best['score']:.3f} "
              "(<1.0 beats 'no change')")

        # Intervals come from CV residuals of the deployed model only.
        residuals = cv[(cv["target"] == target) & (cv["model_name"] == name)
                       & (cv["damping"] == damping)]
        table = build_interval_table(residuals)
        final_part = final[(final["target"] == target) & (final["model_name"] == name)]
        coverage = interval_coverage(final_part, table, interval_bounds)

        selection_rows.append({
            "target": target, "selected_model": name, "damping": damping,
            "cv_score_vs_last_value": cv_best["score"], "cv_mae": cv_best["mae"],
            "cv_median_ape_pct": cv_best["median_ape_pct"],
            "final_test_interval_coverage_80pct": coverage,
        })
        for model_name in MODEL_NAMES:
            row = cv_scored[(cv_scored["target"] == target)
                            & (cv_scored["model_name"] == model_name)
                            & (cv_scored["damping"] == best_damping[(target, model_name)])].iloc[0]
            metadata_rows.append({
                "model_name": model_name, "target": target, "r2": row["r2"],
                "rmse": row["rmse"], "mae": row["mae"],
                "is_deployed": int(model_name == name),
                "median_ape_pct": row["median_ape_pct"], "damping": row["damping"],
            })

        # Refit on every available pair, then forecast from each city's last report.
        model = GrowthModel(name).fit(pairs_by_target[target])
        origins = latest_origins(cleaned[target], target)
        predictions.extend(forecast_cities(model, name, damping, origins, target,
                                           FORECAST_YEARS, table))
        config[target] = {
            "model": name, "damping": damping,
            "interval_log_quantiles_by_horizon_bucket": {str(k): v for k, v in table.items()},
        }

    pd.DataFrame(predictions).to_csv(OUTPUT_DIR / "predictions.csv", index=False)
    pd.DataFrame(metadata_rows).to_csv(OUTPUT_DIR / "model_metrics.csv", index=False)
    pd.DataFrame(selection_rows).to_csv(OUTPUT_DIR / "model_selection.csv", index=False)
    cv_scored.to_csv(OUTPUT_DIR / "cross_validation_summary.csv", index=False)
    summarize_by_horizon(cv).to_csv(OUTPUT_DIR / "cross_validation_by_horizon.csv", index=False)
    final_scored.to_csv(OUTPUT_DIR / "final_test_metrics.csv", index=False)
    summarize_by_horizon(final).to_csv(OUTPUT_DIR / "final_test_by_horizon.csv", index=False)
    (OUTPUT_DIR / "model_config.json").write_text(json.dumps(config, indent=2))

    show = ["target", "model_name", "damping", "mae", "median_ape_pct", "bias_pct", "score"]
    print("\nCross-validation (lower score is better; <1.0 beats no-change):")
    print(cv_scored.sort_values(["target", "score"])[show].to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    print("\nUntouched final test (2024-2025 targets):")
    print(final_scored.sort_values(["target", "score"])[show].to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    print("\nInterval coverage on final test (target 80%):")
    for row in selection_rows:
        print(f"  {row['target']}: {row['final_test_interval_coverage_80pct']:.0%}")
    print(f"\nWrote {len(predictions)} prediction rows to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
