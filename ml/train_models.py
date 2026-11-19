"""Train and evaluate wastewater fee forecasting models.

Run from the repository root:
    python ml/train_models.py

Input:
    data_cleaning/wastewater_costs_2017_2025.csv

Outputs (under ml/outputs):
    predictions.csv                 Production forecasts for 2026-2040
    model_metrics.csv               API-compatible model metadata metrics
    cross_validation_metrics.csv    Metrics for every validation fold
    cross_validation_summary.csv    Pooled and macro-per-city CV metrics
    per_city_metrics.csv            City-level CV errors
    final_test_metrics.csv          Pooled/macro 2025 test metrics
    final_test_fold_metrics.csv     Metrics for each 2025 test fold
    final_test_per_city_metrics.csv City-level 2025 test errors

Evaluation design:
- Known-city track: expanding-window temporal validation. Each fold trains only
  on transitions before its validation year and tests cities with prior history.
- Unseen-city track: GroupKFold by city, repeated across validation years. A
  held-out city's records never enter model fitting, but its prior fee is used
  as an input when that city has historical data.
- 2025 is reserved for final testing and is not used for model selection.
- Models predict annual dollar fee changes and forecasts add the predicted
  change to the previous fee. Future population/customer/group values are held
  constant at the latest known values during production forecasting.

This first pass establishes a benchmark using the existing features and three
existing algorithms. Hyperparameter tuning and additional features are deferred
until these results are reviewed.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from xgboost import XGBRegressor

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data_cleaning" /  "wastewater_costs_2017_2025_checked.csv"
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
CV_YEARS = [2020, 2021, 2022, 2023, 2024]
FINAL_TEST_YEAR = 2025
N_CITY_FOLDS = 3
FORECAST_YEARS = list(range(2026, 2041))
RANDOM_STATE = 42
BASELINE_NAME = "last_value_baseline"


def make_models() -> dict[str, object]:
    """Return fresh candidate models; RF uses 100 trees for a practical CV baseline."""
    return {
        "linear_regression": LinearRegression(),
        "random_forest": RandomForestRegressor(
            n_estimators=100,
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
            tree_method="hist",
        ),
    }


def make_pipeline(estimator: object) -> Pipeline:
    """Fit preprocessing only on the current training fold."""
    preprocess = ColumnTransformer(
        transformers=[
            ("categories", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
            ("numbers", StandardScaler(), NUMERIC_FEATURES),
        ]
    )
    return Pipeline([("preprocess", preprocess), ("model", estimator)])


def prepare_target_data(data: pd.DataFrame, target: str) -> pd.DataFrame:
    """Create rows whose features use only the previous reported observation."""
    clean = data.copy()
    # A zero fee represents not reported / no applicable customers in this data.
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


def temporal_folds(rows: pd.DataFrame, years: list[int] = CV_YEARS):
    """Yield expanding-window train/validation frames for known-city testing."""
    for year in years:
        train = rows[(rows["year"] < year) & rows["previous_fee"].notna()].copy()
        test = rows[(rows["year"] == year) & rows["previous_fee"].notna()].copy()
        if not train.empty and not test.empty:
            yield year, train, test


def grouped_temporal_folds(
    rows: pd.DataFrame,
    years: list[int] = CV_YEARS,
    n_splits: int = N_CITY_FOLDS,
):
    """Yield temporal folds where each validation city's full history is held out."""
    cities = np.array(sorted(rows["city"].dropna().unique()))
    if len(cities) < 2:
        return
    splits = min(n_splits, len(cities))
    splitter = GroupKFold(n_splits=splits)
    city_frame = pd.DataFrame({"city": cities, "dummy": np.zeros(len(cities))})
    for year in years:
        train_year = rows[(rows["year"] < year) & rows["previous_fee"].notna()]
        test_year = rows[(rows["year"] == year) & rows["previous_fee"].notna()]
        if train_year.empty or test_year.empty:
            continue
        for fold_number, (train_idx, heldout_idx) in enumerate(
            splitter.split(city_frame, groups=city_frame["city"]), start=1
        ):
            train_cities = set(cities[train_idx])
            heldout_cities = set(cities[heldout_idx])
            train = train_year[train_year["city"].isin(train_cities)].copy()
            test = test_year[test_year["city"].isin(heldout_cities)].copy()
            if not train.empty and not test.empty:
                yield year, fold_number, train, test


def safe_r2(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Return NaN when R2 is undefined for a tiny or constant sample."""
    if len(actual) < 2 or np.nanvar(actual) == 0:
        return float("nan")
    return float(r2_score(actual, predicted))


def metric_values(actual, predicted) -> dict:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    if len(actual) == 0:
        return {"mae": np.nan, "rmse": np.nan, "r2": np.nan, "n_predictions": 0}
    return {
        "mae": float(mean_absolute_error(actual, predicted)),
        "rmse": float(mean_squared_error(actual, predicted) ** 0.5),
        "r2": safe_r2(actual, predicted),
        "n_predictions": int(len(actual)),
    }


def add_prediction_records(
    records: list[dict], target: str, scenario: str, fold: str,
    model_name: str, test: pd.DataFrame, predicted_fee: np.ndarray,
) -> None:
    for (_, row), prediction in zip(test.iterrows(), predicted_fee):
        records.append({
            "target": target,
            "scenario": scenario,
            "fold": fold,
            "validation_year": int(row["year"]),
            "city": row["city"],
            "model_name": model_name,
            "actual": float(row[target]),
            "predicted": float(prediction),
        })


def predict_fee_levels(model: Pipeline, test: pd.DataFrame) -> np.ndarray:
    """Convert predicted annual dollar changes back into fee levels."""
    change = model.predict(test[FEATURES])
    return np.maximum(0.0, test["previous_fee"].to_numpy(dtype=float) + change)


def run_cv_for_target(target_rows: pd.DataFrame, target: str) -> list[dict]:
    """Run known-city temporal and unseen-city grouped CV for all candidates."""
    prediction_records: list[dict] = []
    fold_metrics: list[dict] = []
    model_names = list(make_models()) + [BASELINE_NAME]

    # Track A: cities may contribute older transitions to model fitting.
    for year, train, test in temporal_folds(target_rows):
        for model_name in model_names:
            if model_name == BASELINE_NAME:
                predicted = test["previous_fee"].to_numpy(dtype=float)
            else:
                model = make_pipeline(make_models()[model_name])
                model.fit(train[FEATURES], train["fee_change"])
                predicted = predict_fee_levels(model, test)
            fold = f"year_{year}"
            add_prediction_records(prediction_records, target, "known_city", fold,
                                   model_name, test, predicted)
            metrics = metric_values(test[target], predicted)
            fold_metrics.append({
                "target": target, "scenario": "known_city", "fold": fold,
                "validation_year": year, "model_name": model_name,
                **metrics, "n_cities": int(test["city"].nunique()),
            })

    # Track B: all rows for held-out cities are excluded from model fitting.
    for year, fold_number, train, test in grouped_temporal_folds(target_rows):
        for model_name in model_names:
            if model_name == BASELINE_NAME:
                predicted = test["previous_fee"].to_numpy(dtype=float)
            else:
                model = make_pipeline(make_models()[model_name])
                model.fit(train[FEATURES], train["fee_change"])
                predicted = predict_fee_levels(model, test)
            fold = f"year_{year}_cityfold_{fold_number}"
            add_prediction_records(prediction_records, target, "unseen_city", fold,
                                   model_name, test, predicted)
            metrics = metric_values(test[target], predicted)
            fold_metrics.append({
                "target": target, "scenario": "unseen_city", "fold": fold,
                "validation_year": year, "model_name": model_name,
                **metrics, "n_cities": int(test["city"].nunique()),
            })

    return prediction_records, fold_metrics


def summarize_predictions(predictions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create pooled and macro-per-city summaries using vectorized aggregation."""
    if predictions.empty:
        return pd.DataFrame(), pd.DataFrame()

    work = predictions.copy()
    work["absolute_error"] = (work["actual"] - work["predicted"]).abs()
    work["squared_error"] = (work["actual"] - work["predicted"]) ** 2
    group_cols = ["target", "scenario", "model_name"]
    city_cols = group_cols + ["city"]

    city_metrics = (
        work.groupby(city_cols, as_index=False)
        .agg(
            mae=("absolute_error", "mean"),
            mean_squared_error=("squared_error", "mean"),
            n_predictions=("actual", "size"),
        )
    )
    city_metrics["rmse"] = np.sqrt(city_metrics["mean_squared_error"])
    city_metrics = city_metrics.drop(columns=["mean_squared_error"])

    summary_rows: list[dict] = []
    for keys, group in work.groupby(group_cols, sort=False):
        target, scenario, model_name = keys
        pooled = metric_values(group["actual"], group["predicted"])
        city_group = city_metrics[
            (city_metrics["target"] == target)
            & (city_metrics["scenario"] == scenario)
            & (city_metrics["model_name"] == model_name)
        ]
        summary_rows.append({
            "target": target,
            "scenario": scenario,
            "model_name": model_name,
            "pooled_mae": pooled["mae"],
            "pooled_rmse": pooled["rmse"],
            "pooled_r2": pooled["r2"],
            "n_predictions": pooled["n_predictions"],
            "n_cities": int(group["city"].nunique()),
            "macro_city_mae": float(city_group["mae"].mean()),
            "macro_city_rmse": float(city_group["rmse"].mean()),
        })
    return pd.DataFrame(summary_rows), city_metrics


def run_final_test(target_rows: pd.DataFrame, target: str):
    """Evaluate 2025 once, after all model choices have been made from CV."""
    train_all = target_rows[(target_rows["year"] < FINAL_TEST_YEAR)
                            & target_rows["previous_fee"].notna()].copy()
    test_all = target_rows[(target_rows["year"] == FINAL_TEST_YEAR)
                           & target_rows["previous_fee"].notna()].copy()
    records: list[dict] = []
    fold_rows: list[dict] = []
    if train_all.empty or test_all.empty:
        return records, fold_rows

    # Known-city final test.
    for model_name in list(make_models()) + [BASELINE_NAME]:
        if model_name == BASELINE_NAME:
            predicted = test_all["previous_fee"].to_numpy(dtype=float)
        else:
            model = make_pipeline(make_models()[model_name])
            model.fit(train_all[FEATURES], train_all["fee_change"])
            predicted = predict_fee_levels(model, test_all)
        add_prediction_records(records, target, "known_city", "final_2025",
                               model_name, test_all, predicted)
        fold_rows.append({
            "target": target, "scenario": "known_city", "fold": "final_2025",
            "validation_year": FINAL_TEST_YEAR, "model_name": model_name,
            **metric_values(test_all[target], predicted),
            "n_cities": int(test_all["city"].nunique()),
        })

    # Unseen-city final test: 2025 cities are grouped; all their history is held out.
    cities = np.array(sorted(target_rows["city"].dropna().unique()))
    if len(cities) >= 2:
        splitter = GroupKFold(n_splits=min(N_CITY_FOLDS, len(cities)))
        city_frame = pd.DataFrame({"city": cities})
        for fold_number, (train_idx, heldout_idx) in enumerate(
            splitter.split(city_frame, groups=city_frame["city"]), start=1
        ):
            train_cities, heldout_cities = set(cities[train_idx]), set(cities[heldout_idx])
            train = train_all[train_all["city"].isin(train_cities)].copy()
            test = test_all[test_all["city"].isin(heldout_cities)].copy()
            if train.empty or test.empty:
                continue
            for model_name in list(make_models()) + [BASELINE_NAME]:
                if model_name == BASELINE_NAME:
                    predicted = test["previous_fee"].to_numpy(dtype=float)
                else:
                    model = make_pipeline(make_models()[model_name])
                    model.fit(train[FEATURES], train["fee_change"])
                    predicted = predict_fee_levels(model, test)
                fold = f"final_2025_cityfold_{fold_number}"
                add_prediction_records(records, target, "unseen_city", fold,
                                       model_name, test, predicted)
                fold_rows.append({
                    "target": target, "scenario": "unseen_city", "fold": fold,
                    "validation_year": FINAL_TEST_YEAR, "model_name": model_name,
                    **metric_values(test[target], predicted),
                    "n_cities": int(test["city"].nunique()),
                })
    return records, fold_rows



def build_model_selection_report(cv_summary: pd.DataFrame, production_choices: dict[str, str]) -> pd.DataFrame:
    """Report the best candidate per target/track plus the production compromise."""
    rows: list[dict] = []
    for target in TARGETS:
        subset = cv_summary[cv_summary["target"] == target]
        for scenario in ["known_city", "unseen_city"]:
            scenario_rows = subset[subset["scenario"] == scenario].set_index("model_name")
            if BASELINE_NAME not in scenario_rows.index:
                continue
            baseline = scenario_rows.loc[BASELINE_NAME]
            ranked = []
            for model_name in make_models():
                if model_name not in scenario_rows.index:
                    continue
                candidate = scenario_rows.loc[model_name]
                ratios = []
                for metric in ["pooled_mae", "pooled_rmse"]:
                    base_value, model_value = baseline[metric], candidate[metric]
                    if pd.notna(base_value) and base_value > 0 and pd.notna(model_value):
                        ratios.append(float(model_value / base_value))
                if ratios:
                    ranked.append((float(np.mean(ratios)), model_name))
            if ranked:
                score, winner = min(ranked)
                rows.append({
                    "target": target, "scenario": scenario,
                    "selection_type": "best_for_this_scenario",
                    "selected_model": winner, "normalized_combined_score": score,
                })
        # The API supports one deployed model per target, so production uses
        # the candidate with the best average across both tracks and both errors.
        rows.append({
            "target": target, "scenario": "both_tracks",
            "selection_type": "production_model_for_existing_api",
            "selected_model": production_choices[target],
            "normalized_combined_score": np.nan,
        })
    return pd.DataFrame(rows)


def initial_city_states(rows: pd.DataFrame, through_year: int) -> dict[str, dict]:
    history = rows[rows["year"] <= through_year].sort_values(["city", "year"])
    states: dict[str, dict] = {}
    for city, group in history.groupby("city"):
        last = group.iloc[-1]
        states[city] = {
            "fee": float(last["target_fee"]), "year": int(last["year"]),
            "population": float(last["population"]),
            "customers": float(last["total_customers"]),
            "population_group": str(last["population_group"]),
        }
    return states


def state_features(states: dict[str, dict], year: int) -> pd.DataFrame:
    records = [{
        "city": city,
        "previous_population_group": state["population_group"],
        "year": year,
        "previous_population": state["population"],
        "previous_customers": state["customers"],
        "previous_fee": state["fee"],
        "years_since_previous": year - state["year"],
    } for city, state in states.items()]
    return pd.DataFrame(records, columns=FEATURES)


def forecast_15_years(model: Pipeline, target_rows: pd.DataFrame,
                      target: str, model_name: str) -> list[dict]:
    latest_year = int(target_rows["year"].max())
    states = initial_city_states(target_rows.rename(columns={target: "target_fee"}), latest_year)
    output: list[dict] = []
    for year in FORECAST_YEARS:
        X_future = state_features(states, year)
        if X_future.empty:
            continue
        if model_name == BASELINE_NAME:
            predicted_fee = X_future["previous_fee"].to_numpy(dtype=float)
        else:
            predicted_fee = np.maximum(
                0.0, X_future["previous_fee"].to_numpy() + model.predict(X_future[FEATURES])
            )
        for city, value in zip(X_future["city"], predicted_fee):
            output.append({
                "city": city, "year": year, "target": target,
                "predicted_value": round(float(value), 2),
                "lower_bound": "", "upper_bound": "", "model_name": model_name,
            })
            states[city]["fee"] = float(value)
            states[city]["year"] = year
    return output


def choose_models(cv_summary: pd.DataFrame) -> dict[str, str]:
    """Choose one production model per target using both tracks and both errors.

    Each MAE/RMSE is normalized against its matching last-value baseline. The
    four ratios (known MAE/RMSE, unseen MAE/RMSE) receive equal weight. This
    makes the two scenarios and the two requested error metrics equally
    influential without mixing residential and commercial dollar scales.
    """
    selections: dict[str, str] = {}
    for target in TARGETS:
        subset = cv_summary[cv_summary["target"] == target]
        baseline = subset[subset["model_name"] == BASELINE_NAME].set_index("scenario")
        candidate_scores = []
        for model_name in make_models():
            candidate = subset[subset["model_name"] == model_name].set_index("scenario")
            ratios = []
            for scenario in ["known_city", "unseen_city"]:
                if scenario not in baseline.index or scenario not in candidate.index:
                    continue
                for metric in ["pooled_mae", "pooled_rmse"]:
                    base_value = baseline.loc[scenario, metric]
                    model_value = candidate.loc[scenario, metric]
                    if pd.notna(base_value) and base_value > 0 and pd.notna(model_value):
                        ratios.append(float(model_value / base_value))
            if ratios:
                candidate_scores.append((float(np.mean(ratios)), model_name))
        if not candidate_scores:
            raise ValueError(f"Could not select a model for {target}: CV metrics are incomplete.")
        best_score, best_name = min(candidate_scores)
        # Do not deploy an ML candidate when the no-change baseline is better
        # on the combined MAE/RMSE score across both evaluation tracks.
        selections[target] = best_name if best_score < 1.0 else BASELINE_NAME
    return selections


def main() -> None:
    if not DATA_PATH.exists():
        raise FileNotFoundError(
            f"Dataset not found: {DATA_PATH}\n"
            "Place the cleaned CSV at data_cleaning/wastewater_costs_2017_2025.csv."
        )
    data = pd.read_csv(DATA_PATH)
    required = {"year", "population_group", "city", "population", "total_customers", *TARGETS}
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"Dataset is missing required columns: {sorted(missing)}")

    all_cv_predictions: list[dict] = []
    all_fold_metrics: list[dict] = []
    all_final_predictions: list[dict] = []
    all_final_fold_metrics: list[dict] = []
    target_data: dict[str, pd.DataFrame] = {}

    for target in TARGETS:
        print(f"\nCross-validating {target}...")
        target_rows = prepare_target_data(data, target)
        target_data[target] = target_rows
        cv_predictions, fold_metrics = run_cv_for_target(target_rows, target)
        final_predictions, final_metrics = run_final_test(target_rows, target)
        all_cv_predictions.extend(cv_predictions)
        all_fold_metrics.extend(fold_metrics)
        all_final_predictions.extend(final_predictions)
        all_final_fold_metrics.extend(final_metrics)

    cv_predictions_df = pd.DataFrame(all_cv_predictions)
    cv_fold_metrics_df = pd.DataFrame(all_fold_metrics)
    cv_summary_df, per_city_df = summarize_predictions(cv_predictions_df)
    final_predictions_df = pd.DataFrame(all_final_predictions)
    final_fold_metrics_df = pd.DataFrame(all_final_fold_metrics)
    final_summary_df, final_per_city_df = summarize_predictions(final_predictions_df)

    # Selection uses CV only. The 2025 test is not consulted here.
    selections = choose_models(cv_summary_df)
    selection_report_df = build_model_selection_report(cv_summary_df, selections)
    print("\nSelected production candidates (CV only):")
    for target, model_name in selections.items():
        print(f"  {target}: {model_name}")

    # Keep the existing API metadata contract: one row per model/target and
    # exactly one deployed model per target. Metadata metrics use known-city CV;
    # the separate reports retain both tracks and the untouched 2025 test.
    metadata_rows: list[dict] = []
    for target in TARGETS:
        known = cv_summary_df[cv_summary_df["target"] == target]
        known = known[known["scenario"] == "known_city"].set_index("model_name")
        for model_name in list(make_models()) + [BASELINE_NAME]:
            if model_name not in known.index:
                continue
            row = known.loc[model_name]
            metadata_rows.append({
                "model_name": model_name, "target": target,
                "r2": row["pooled_r2"], "rmse": row["pooled_rmse"],
                "mae": row["pooled_mae"],
                "is_deployed": int(model_name == selections[target]),
            })

    # Fit selected production models on every valid transition through 2025.
    all_production_predictions: list[dict] = []
    for target in TARGETS:
        rows = target_data[target]
        training = rows[rows["previous_fee"].notna()].copy()
        selected_name = selections[target]
        if selected_name == BASELINE_NAME:
            final_model = None
        else:
            final_model = make_pipeline(make_models()[selected_name])
            final_model.fit(training[FEATURES], training["fee_change"])
        all_production_predictions.extend(
            forecast_15_years(final_model, rows, target, selected_name)
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(all_production_predictions).to_csv(OUTPUT_DIR / "predictions.csv", index=False)
    pd.DataFrame(metadata_rows).to_csv(OUTPUT_DIR / "model_metrics.csv", index=False)
    cv_fold_metrics_df.to_csv(OUTPUT_DIR / "cross_validation_metrics.csv", index=False)
    cv_summary_df.to_csv(OUTPUT_DIR / "cross_validation_summary.csv", index=False)
    selection_report_df.to_csv(OUTPUT_DIR / "model_selection.csv", index=False)
    per_city_df.to_csv(OUTPUT_DIR / "per_city_metrics.csv", index=False)
    final_summary_df.to_csv(OUTPUT_DIR / "final_test_metrics.csv", index=False)
    final_fold_metrics_df.to_csv(OUTPUT_DIR / "final_test_fold_metrics.csv", index=False)
    final_per_city_df.to_csv(OUTPUT_DIR / "final_test_per_city_metrics.csv", index=False)

    print("\nModel selection report:")
    print(selection_report_df.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    print("\nCross-validation summary (pooled and macro-per-city):")
    if not cv_summary_df.empty:
        print(cv_summary_df.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    print("\nUntouched 2025 final-test fold metrics:")
    if not final_fold_metrics_df.empty:
        print(final_fold_metrics_df.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    print("\nFinished. Outputs saved to:", OUTPUT_DIR)
    print("Prediction rows:", len(all_production_predictions))
    print("2025 results were not used for model selection.")
    print("Note: lower/upper forecast bounds remain blank until prediction intervals are calibrated.")


if __name__ == "__main__":
    main()
