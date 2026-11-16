"""Train and evaluate wastewater fee forecasting models.

Run from the repository root:
    python ml/train_models.py

Inputs:
    data_cleaning/wastewater_costs_2017_2025.csv

Outputs:
    ml/outputs/predictions.csv
    ml/outputs/model_metrics.csv

The model predicts annual fee changes (not fee levels) and recursively rolls
those changes forward. Population, customer count, and population group are
held at each city's latest reported values during future forecasting.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from xgboost import XGBRegressor

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data_cleaning" / "wastewater_costs_2017_2025.csv"
OUTPUT_DIR = ROOT / "ml" / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TARGETS = ["res_fee_5k_gal", "com_fee_50k_gal"]
CATEGORICAL_FEATURES = ["city", "previous_population_group"]
NUMERIC_FEATURES = [
    "year",
    "previous_population",
    "previous_customers",
    "previous_fee",
    "years_since_previous",
]
FEATURES = CATEGORICAL_FEATURES + NUMERIC_FEATURES
TRAIN_THROUGH_YEAR = 2023
VALIDATION_YEARS = [2024, 2025]
FORECAST_YEARS = list(range(2026, 2041))
RANDOM_STATE = 42


def make_models() -> dict[str, object]:
    """Return a fresh instance of each rubric model."""
    return {
        "linear_regression": LinearRegression(),
        "random_forest": RandomForestRegressor(
            n_estimators=300,
            max_features=0.8,
            min_samples_leaf=3,
            random_state=RANDOM_STATE,
            n_jobs=-1,
        ),
        "xgboost": XGBRegressor(
            n_estimators=350,
            max_depth=3,
            learning_rate=0.035,
            subsample=0.85,
            colsample_bytree=0.85,
            reg_lambda=5,
            objective="reg:squarederror",
            random_state=RANDOM_STATE,
            n_jobs=4,
        ),
    }


def make_pipeline(estimator: object) -> Pipeline:
    """Encode city/group and scale numeric features before fitting."""
    preprocess = ColumnTransformer(
        transformers=[
            (
                "categories",
                OneHotEncoder(handle_unknown="ignore"),
                CATEGORICAL_FEATURES,
            ),
            ("numbers", StandardScaler(), NUMERIC_FEATURES),
        ]
    )
    return Pipeline([("preprocess", preprocess), ("model", estimator)])


def prepare_target_data(data: pd.DataFrame, target: str) -> pd.DataFrame:
    """Create one-step-ahead training rows using only prior reported values."""
    clean = data.copy()
    # In this survey, a zero fee means not reported / no applicable customers.
    clean.loc[clean[target] == 0, target] = np.nan
    clean = clean.dropna(subset=[target]).sort_values(["city", "year"]).copy()

    grouped = clean.groupby("city", sort=False)
    clean["previous_fee"] = grouped[target].shift(1)
    clean["previous_year"] = grouped["year"].shift(1)
    clean["previous_population"] = grouped["population"].shift(1)
    clean["previous_customers"] = grouped["total_customers"].shift(1)
    clean["previous_population_group"] = grouped["population_group"].shift(1)
    clean["years_since_previous"] = clean["year"] - clean["previous_year"]
    clean["fee_change"] = clean[target] - clean["previous_fee"]

    return clean


def initial_city_states(rows: pd.DataFrame, through_year: int) -> dict[str, dict]:
    """Get each city's latest known fee and exogenous features at a cutoff."""
    history = rows[rows["year"] <= through_year].sort_values(["city", "year"])
    states: dict[str, dict] = {}
    for city, group in history.groupby("city"):
        last = group.iloc[-1]
        states[city] = {
            "fee": float(last["target_fee"]),
            "year": int(last["year"]),
            "population": float(last["population"]),
            "customers": float(last["total_customers"]),
            "population_group": str(last["population_group"]),
        }
    return states


def state_features(states: dict[str, dict], year: int) -> pd.DataFrame:
    """Build model inputs for every city using its latest known state."""
    records = []
    for city, state in states.items():
        records.append(
            {
                "city": city,
                "previous_population_group": state["population_group"],
                "year": year,
                "previous_population": state["population"],
                "previous_customers": state["customers"],
                "previous_fee": state["fee"],
                "years_since_previous": year - state["year"],
            }
        )
    return pd.DataFrame(records, columns=FEATURES)


def score_predictions(actual: list[float], predicted: list[float]) -> dict:
    return {
        "mae": float(mean_absolute_error(actual, predicted)),
        "rmse": float(mean_squared_error(actual, predicted) ** 0.5),
        "r2": float(r2_score(actual, predicted)),
        "test_rows": len(actual),
    }


def rolling_validation(
    model: Pipeline,
    target_rows: pd.DataFrame,
    target: str,
    model_name: str,
) -> dict:
    """Forecast 2024 and 2025 sequentially without using future covariates."""
    states = initial_city_states(
        target_rows.rename(columns={target: "target_fee"}), TRAIN_THROUGH_YEAR
    )
    actual_values: list[float] = []
    predicted_values: list[float] = []

    for year in VALIDATION_YEARS:
        X_future = state_features(states, year)
        if X_future.empty:
            continue

        predicted_change = model.predict(X_future[FEATURES])
        predicted_fee = np.maximum(
            0.0, X_future["previous_fee"].to_numpy() + predicted_change
        )
        predictions_by_city = dict(zip(X_future["city"], predicted_fee))

        observed = target_rows[target_rows["year"] == year].set_index("city")[target]
        for city, actual in observed.items():
            if city in predictions_by_city:
                actual_values.append(float(actual))
                predicted_values.append(float(predictions_by_city[city]))

        # Advance every city, including cities without a survey row that year.
        # This mirrors a real recursive forecast and avoids using 2024 actuals
        # as inputs when predicting 2025.
        for city, value in predictions_by_city.items():
            states[city]["fee"] = float(value)
            states[city]["year"] = year

    return score_predictions(actual_values, predicted_values)


def persistence_baseline(target_rows: pd.DataFrame, target: str) -> dict:
    """Score a no-change forecast for comparison against ML models."""
    states = initial_city_states(
        target_rows.rename(columns={target: "target_fee"}), TRAIN_THROUGH_YEAR
    )
    actual_values: list[float] = []
    predicted_values: list[float] = []

    for year in VALIDATION_YEARS:
        for city, actual in target_rows[target_rows["year"] == year].set_index("city")[target].items():
            if city in states:
                actual_values.append(float(actual))
                predicted_values.append(float(states[city]["fee"]))
        for state in states.values():
            state["year"] = year

    return score_predictions(actual_values, predicted_values)


def forecast_15_years(
    model: Pipeline,
    target_rows: pd.DataFrame,
    target: str,
    model_name: str,
) -> list[dict]:
    """Generate 2026-2040 forecasts, recursively updating each city's fee."""
    latest_year = int(target_rows["year"].max())
    states = initial_city_states(
        target_rows.rename(columns={target: "target_fee"}), latest_year
    )
    output: list[dict] = []

    for year in FORECAST_YEARS:
        X_future = state_features(states, year)
        if X_future.empty:
            continue
        predicted_change = model.predict(X_future[FEATURES])
        predicted_fee = np.maximum(
            0.0, X_future["previous_fee"].to_numpy() + predicted_change
        )

        for city, value in zip(X_future["city"], predicted_fee):
            output.append(
                {
                    "city": city,
                    "year": year,
                    "target": target,
                    "predicted_value": round(float(value), 2),
                    "lower_bound": "",
                    "upper_bound": "",
                    "model_name": model_name,
                }
            )
            states[city]["fee"] = float(value)
            states[city]["year"] = year

    return output


def main() -> None:
    if not DATA_PATH.exists():
        raise FileNotFoundError(
            f"Dataset not found: {DATA_PATH}\n"
            "Place the cleaned CSV at data_cleaning/wastewater_costs_2017_2025.csv."
        )

    data = pd.read_csv(DATA_PATH)
    required = {
        "year", "population_group", "city", "population", "total_customers",
        *TARGETS,
    }
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"Dataset is missing required columns: {sorted(missing)}")

    all_metrics: list[dict] = []
    all_predictions: list[dict] = []

    for target in TARGETS:
        target_rows = prepare_target_data(data, target)
        train_rows = target_rows[
            (target_rows["year"] <= TRAIN_THROUGH_YEAR)
            & target_rows["previous_fee"].notna()
        ].copy()
        if train_rows.empty:
            raise ValueError(f"No training rows available for {target}.")

        print(f"\nTraining target: {target}")
        print(f"Training transitions: {len(train_rows):,}")

        fitted_models: dict[str, Pipeline] = {}
        for model_name, estimator in make_models().items():
            pipeline = make_pipeline(estimator)
            pipeline.fit(train_rows[FEATURES], train_rows["fee_change"])
            fitted_models[model_name] = pipeline
            metrics = rolling_validation(pipeline, target_rows, target, model_name)
            all_metrics.append(
                {
                    "model_name": model_name,
                    "target": target,
                    **metrics,
                    "is_deployed": 0,
                }
            )
            print(
                f"  {model_name:18s} MAE=${metrics['mae']:.2f} "
                f"RMSE=${metrics['rmse']:.2f} R2={metrics['r2']:.3f}"
            )

        baseline = persistence_baseline(target_rows, target)
        all_metrics.append(
            {
                "model_name": "last_value_baseline",
                "target": target,
                **baseline,
                "is_deployed": 0,
            }
        )
        print(
            f"  {'last_value_baseline':18s} MAE=${baseline['mae']:.2f} "
            f"RMSE=${baseline['rmse']:.2f} R2={baseline['r2']:.3f}"
        )

        # RMSE is the deployment selection metric because large dollar errors
        # matter for municipal budgeting. MAE is also reported for context.
        target_results = [
            row for row in all_metrics
            if row["target"] == target and row["model_name"] != "last_value_baseline"
        ]
        best = min(target_results, key=lambda row: row["rmse"])
        best["is_deployed"] = 1
        best_name = best["model_name"]
        print(f"  Selected for {target}: {best_name} (lowest validation RMSE)")

        # Refit the selected algorithm on all available historical transitions.
        full_estimator = make_models()[best_name]
        final_model = make_pipeline(full_estimator)
        final_training_rows = target_rows[target_rows["previous_fee"].notna()].copy()
        final_model.fit(final_training_rows[FEATURES], final_training_rows["fee_change"])
        all_predictions.extend(
            forecast_15_years(final_model, target_rows, target, best_name)
        )

    predictions_path = OUTPUT_DIR / "predictions.csv"
    metrics_path = OUTPUT_DIR / "model_metrics.csv"
    pd.DataFrame(all_predictions).to_csv(predictions_path, index=False)
    pd.DataFrame(all_metrics).to_csv(metrics_path, index=False)

    print("\nFinished.")
    print(f"Predictions: {predictions_path}")
    print(f"Model metrics: {metrics_path}")
    print(f"Prediction rows: {len(all_predictions):,}")
    print("Note: lower/upper bounds are blank until prediction intervals are calibrated.")


if __name__ == "__main__":
    main()
