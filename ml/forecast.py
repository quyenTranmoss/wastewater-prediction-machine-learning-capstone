"""Models, damped multi-year forecasting and prediction intervals.

Every model predicts the *annual log growth rate* of a city's fee. A forecast
for a target year is then:

    fee = last_fee * exp(rate * effective_years)

effective_years equals the horizon when damping = 1 and shrinks for damping < 1,
so growth fades instead of compounding forever. This avoids the two failure
modes of the old recursive forecast (flat line for residential, runaway
drift for commercial).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

from ml.prepare_data import FEATURES, MAX_HORIZON

RANDOM_STATE = 42
RATE_MIN, RATE_MAX = -0.03, 0.15  # plausible annual change: -3% to +15%
LAST_VALUE = "last_value_baseline"   # benchmark only, never deployed
DRIFT = "drift_baseline"
MODEL_NAMES = [
    LAST_VALUE, DRIFT, "ridge_regression", "random_forest",
    "xgboost", "hist_gradient_boosting",
]
# Both baselines are benchmarks only. A flat 15-year line is not a usable product,
# and the project requires an ML model. To allow drift_baseline to be deployed when
# it wins, change this to: [n for n in MODEL_NAMES if n != LAST_VALUE]
DEPLOYABLE = [name for name in MODEL_NAMES if name not in (LAST_VALUE, DRIFT)]
DAMPING_GRID = (1.0, 0.95, 0.90)
INTERVAL_QUANTILES = (0.10, 0.90)  # 80% prediction interval
HORIZON_BUCKETS = [(1, 2), (3, 5), (6, 8)]


def effective_years(horizon: np.ndarray, damping: float) -> np.ndarray:
    horizon = np.asarray(horizon, dtype=float)
    if damping >= 1.0:
        return horizon
    return (1.0 - damping ** horizon) / (1.0 - damping)


class GrowthModel:
    """Common interface: fit(pairs) then rate(frame) -> annual log growth."""

    def __init__(self, name: str):
        self.name = name
        self.estimator = None
        self.drift = 0.0
        self.train_clip = 0.25

    def _make_estimator(self):
        if self.name == "ridge_regression":
            return Pipeline([("impute", SimpleImputer(strategy="median")),
                             ("scale", StandardScaler()), ("model", Ridge(alpha=10.0))])
        if self.name == "random_forest":
            return Pipeline([("impute", SimpleImputer(strategy="median")),
                             ("model", RandomForestRegressor(
                                 n_estimators=200, min_samples_leaf=30, max_features=0.7,
                                 random_state=RANDOM_STATE, n_jobs=-1))])
        if self.name == "xgboost":
            self.train_clip = 0.5
            return XGBRegressor(
                n_estimators=300, max_depth=3, learning_rate=0.04, subsample=0.8,
                colsample_bytree=0.8, min_child_weight=20, reg_lambda=10,
                objective="reg:pseudohubererror", huber_slope=0.15,
                random_state=RANDOM_STATE, n_jobs=4, tree_method="hist")
        if self.name == "hist_gradient_boosting":
            return HistGradientBoostingRegressor(
                max_depth=3, learning_rate=0.04, max_iter=250, min_samples_leaf=40,
                l2_regularization=5.0, random_state=RANDOM_STATE)
        raise ValueError(f"Unknown model: {self.name}")

    def fit(self, pairs: pd.DataFrame) -> "GrowthModel":
        if self.name == LAST_VALUE:
            return self
        if self.name == DRIFT:
            low, high = pairs["ann"].quantile([0.05, 0.95])
            self.drift = float(pairs["ann"].clip(low, high).mean())
            return self
        self.estimator = self._make_estimator()
        self.estimator.fit(pairs[FEATURES], pairs["ann"].clip(-self.train_clip, self.train_clip))
        return self

    def rate(self, frame: pd.DataFrame) -> np.ndarray:
        if self.name == LAST_VALUE:
            return np.zeros(len(frame))
        if self.name == DRIFT:
            return np.full(len(frame), self.drift)
        return np.asarray(self.estimator.predict(frame[FEATURES]), dtype=float)


def predict_levels(model: GrowthModel, frame: pd.DataFrame, horizon: np.ndarray,
                   damping: float) -> np.ndarray:
    """Fee level `horizon` years after each row's origin."""
    X = frame.copy()
    horizon = np.asarray(horizon, dtype=float)
    X["h"] = np.minimum(horizon, MAX_HORIZON)
    rate = np.clip(model.rate(X), RATE_MIN, RATE_MAX)
    return X["fee_a"].to_numpy(float) * np.exp(rate * effective_years(horizon, damping))


def _bucket(horizon: int) -> int:
    for number, (low, high) in enumerate(HORIZON_BUCKETS):
        if low <= horizon <= high:
            return number
    return len(HORIZON_BUCKETS) - 1


def build_interval_table(residuals: pd.DataFrame) -> dict[int, tuple[float, float]]:
    """Quantiles of log(actual / predicted) per horizon bucket, from backtests."""
    table: dict[int, tuple[float, float]] = {}
    work = residuals.assign(
        log_error=np.log(residuals["actual"] / residuals["predicted"]),
        bucket=residuals["h"].map(_bucket),
    )
    pooled = work["log_error"].quantile(INTERVAL_QUANTILES).to_numpy()
    for bucket in range(len(HORIZON_BUCKETS)):
        errors = work.loc[work["bucket"] == bucket, "log_error"]
        low, high = (errors.quantile(INTERVAL_QUANTILES).to_numpy()
                     if len(errors) >= 30 else pooled)
        # Interval must contain the point forecast and never narrow with horizon.
        low, high = min(float(low), -0.01), max(float(high), 0.01)
        if bucket > 0:
            low, high = min(low, table[bucket - 1][0]), max(high, table[bucket - 1][1])
        table[bucket] = (low, high)
    return table


def interval_bounds(point: np.ndarray, horizon: np.ndarray,
                    table: dict[int, tuple[float, float]]) -> tuple[np.ndarray, np.ndarray]:
    """Beyond the backtest range, widen the last bucket by sqrt(horizon / 8)."""
    lower = np.empty(len(point))
    upper = np.empty(len(point))
    for i, (value, h) in enumerate(zip(point, horizon)):
        low, high = table[_bucket(int(min(h, MAX_HORIZON)))]
        if h > MAX_HORIZON:
            scale = float(np.sqrt(h / MAX_HORIZON))
            low, high = low * scale, high * scale
        lower[i], upper[i] = value * np.exp(low), value * np.exp(high)
    return lower, upper


def forecast_cities(model: GrowthModel, model_name: str, damping: float,
                    origins: pd.DataFrame, target: str, years: list[int],
                    interval_table: dict[int, tuple[float, float]]) -> list[dict]:
    """Rows matching database/load_predictions.py for every city and year."""
    records: list[dict] = []
    for year in years:
        horizon = (year - origins["a_year"]).to_numpy()
        keep = horizon >= 1
        frame = origins[keep]
        point = predict_levels(model, frame, horizon[keep], damping)
        lower, upper = interval_bounds(point, horizon[keep], interval_table)
        for city, value, low, high in zip(frame["city"], point, lower, upper):
            records.append({
                "city": city, "year": year, "target": target,
                "predicted_value": round(float(value), 2),
                "lower_bound": round(float(low), 2),
                "upper_bound": round(float(high), 2),
                "model_name": model_name,
            })
    return records
