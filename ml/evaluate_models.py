"""Multi-horizon backtesting, metrics and model selection.

Backtest design (matches how the app is used: forecast many years ahead from a
city's last report):
- CV: for each cutoff year C, train only on pairs whose target year is <= C,
  then forecast every later target year (up to CV_MAX_TARGET_YEAR) from each
  city's latest report on or before C.
- Final test: cutoff FINAL_CUTOFF, targets 2024-2025. Never used to select
  models, damping or interval widths.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import r2_score

from ml.forecast import (
    DAMPING_GRID, DEPLOYABLE, HORIZON_BUCKETS, LAST_VALUE, MODEL_NAMES,
    GrowthModel, predict_levels,
)

CV_CUTOFFS = [2019, 2020, 2021, 2022]
CV_MAX_TARGET_YEAR = 2023
FINAL_CUTOFF = 2023
FINAL_TARGET_YEARS = (2024, 2025)
# Model selection only looks at horizons of 3+ years. The app forecasts 2026-2040,
# so ~87% of the forecast horizons are 3+ years. At 1-2 years more than half of
# fees are exactly unchanged and "no change" is nearly unbeatable, which says
# little about 15-year accuracy. All horizons are still reported separately.
SELECTION_MIN_HORIZON = 3


def split_pairs(pairs: pd.DataFrame, cutoff: int, max_target_year: int):
    """Train on pairs resolved by the cutoff; test on later targets, latest origin only."""
    train = pairs[pairs["b_year"] <= cutoff]
    test = pairs[(pairs["a_year"] <= cutoff) & (pairs["b_year"] > cutoff)
                 & (pairs["b_year"] <= max_target_year)]
    test = test.sort_values("a_year").groupby(["city", "b_year"], as_index=False).tail(1)
    return train, test.copy()


def backtest(pairs: pd.DataFrame, target: str, cutoffs: list[int],
             max_target_year: int) -> pd.DataFrame:
    """Out-of-sample predictions for every model and damping value."""
    records: list[pd.DataFrame] = []
    for cutoff in cutoffs:
        train, test = split_pairs(pairs, cutoff, max_target_year)
        if train.empty or test.empty:
            continue
        for name in MODEL_NAMES:
            model = GrowthModel(name).fit(train)
            for damping in ([1.0] if name == LAST_VALUE else DAMPING_GRID):
                predicted = predict_levels(model, test, test["h_raw"].to_numpy(), damping)
                records.append(pd.DataFrame({
                    "target": target, "cutoff": cutoff, "model_name": name,
                    "damping": damping, "city": test["city"].to_numpy(),
                    "b_year": test["b_year"].to_numpy(), "h": test["h_raw"].to_numpy(),
                    "actual": test["fee_b"].to_numpy(), "predicted": predicted,
                }))
    return pd.concat(records, ignore_index=True) if records else pd.DataFrame()


def metric_row(actual: np.ndarray, predicted: np.ndarray) -> dict:
    actual, predicted = np.asarray(actual, float), np.asarray(predicted, float)
    ape = np.abs(predicted - actual) / actual
    return {
        "mae": float(np.mean(np.abs(predicted - actual))),
        "rmse": float(np.sqrt(np.mean((predicted - actual) ** 2))),
        "r2": float(r2_score(actual, predicted)) if len(actual) > 1 else np.nan,
        "median_ape_pct": float(np.median(ape) * 100),
        "capped_mape_pct": float(np.mean(np.minimum(ape, 1.0)) * 100),
        "bias_pct": float(np.median((predicted - actual) / actual) * 100),
        "n_predictions": int(len(actual)),
    }


def summarize(records: pd.DataFrame) -> pd.DataFrame:
    rows = [{"target": t, "model_name": m, "damping": d, **metric_row(g["actual"], g["predicted"])}
            for (t, m, d), g in records.groupby(["target", "model_name", "damping"])]
    return pd.DataFrame(rows)


def summarize_by_horizon(records: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (t, m, d), group in records.groupby(["target", "model_name", "damping"]):
        for low, high in HORIZON_BUCKETS:
            part = group[(group["h"] >= low) & (group["h"] <= high)]
            if len(part):
                rows.append({"target": t, "model_name": m, "damping": d,
                             "horizon_years": f"{low}-{high}", **metric_row(part["actual"], part["predicted"])})
    return pd.DataFrame(rows)


def score_against_benchmark(summary: pd.DataFrame) -> pd.DataFrame:
    """Combined score: mean of MAE, median-APE and capped-MAPE ratios vs last value.

    Below 1.0 means better than 'no change'. Ratios keep residential dollars,
    commercial dollars and percentages on the same scale.
    """
    out = summary.copy()
    out["score"] = np.nan
    for target, group in summary.groupby("target"):
        base = group[group["model_name"] == LAST_VALUE].iloc[0]
        ratios = [group[c] / base[c] for c in ("mae", "median_ape_pct", "capped_mape_pct")]
        out.loc[group.index, "score"] = np.mean(ratios, axis=0)
    return out


def choose_models(scored: pd.DataFrame) -> dict[str, tuple[str, float]]:
    """Best deployable (model, damping) per target using CV only.

    last_value_baseline is a benchmark: a flat 15-year forecast is not a usable
    product, so drift_baseline is the fallback when no ML model beats it.
    """
    chosen: dict[str, tuple[str, float]] = {}
    for target, group in scored.groupby("target"):
        group = group[group["model_name"].isin(DEPLOYABLE)]
        best = group.loc[group["score"].idxmin()]
        chosen[target] = (str(best["model_name"]), float(best["damping"]))
    return chosen


def interval_coverage(records: pd.DataFrame, table, lower_upper_fn) -> float:
    """Share of actual values inside the interval (used on the final test)."""
    lower, upper = lower_upper_fn(records["predicted"].to_numpy(), records["h"].to_numpy(), table)
    return float(np.mean((records["actual"] >= lower) & (records["actual"] <= upper)))
