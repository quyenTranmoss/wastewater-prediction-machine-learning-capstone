"""Data cleaning and feature building for wastewater fee forecasting.

Used by train_models.py. Nothing here changes the CSV or the database: the
cleaning below only decides which fee values the *models* may learn from.

Key ideas
---------
1. Zero fees mean "not reported", so they become missing.
2. Isolated spikes (a fee that jumps 2.5x and falls back, or a value far from
   its own history and from similar-sized cities) are treated as typos and
   dropped from ML training. Every drop is logged in cleaning_report.csv so the
   team can review it.
3. Training rows are (origin year, target year) pairs for the same city. Every
   feature describes the city as of the origin year only, so there is no
   look-ahead leakage. The model learns the annualized log growth of the fee:
       growth = log(fee_target / fee_origin) / horizon_years
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data_cleaning" / "wastewater_costs_2017_2025_checked.csv"

TARGETS = ["res_fee_5k_gal", "com_fee_50k_gal"]
MAX_HORIZON = 8  # longest gap the history supports (2017 -> 2025)

# Spike detector thresholds (see drop_spikes).
SPIKE_JUMP = 2.5        # value is >= 2.5x (or <= 1/2.5x) both neighbours
NEIGHBOUR_AGREE = 1.8   # ...while the two neighbours agree within 1.8x
EDGE_JUMP = 5.0         # first/last observation: >= 5x its only neighbour
PEER_RANGE = (0.4, 2.5)  # ...and that neighbour is typical for its size group
EXTREME_PEER = 10.0     # value is 10x (or 1/10) its size-group median that year...
EXTREME_OWN = 8.0       # ...and 8x (or 1/8) the median of the city's other reports

FEATURES = [
    "log_fee",           # fee level at the origin year
    "log_pop",           # city size
    "log_cust",          # number of sewer customers
    "cust_per_pop",      # share of residents who are customers
    "group_lower",       # log of the population-group lower bound
    "rel",               # log(fee / median fee of its size group that year)
    "n_obs",             # how many reports the city has so far
    "hist_growth",       # city's own annualized growth since first report
    "n_changes",         # how many times the fee has changed so far
    "yrs_since_change",  # years since the fee last changed
    "span",              # years between first report and origin
    "last_ann",          # growth over the most recent reporting gap
    "a_year",            # origin year (captures inflation-era effects)
    "h",                 # horizon in years (capped at MAX_HORIZON)
]


def group_lower_bound(label: str) -> float:
    """'2,001 - 5,000' -> 2001, '2,000 OR LESS' -> 0, 'MORE THAN 500,000' -> 500001."""
    numbers = [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", str(label))]
    if not numbers:
        return 0.0
    text = str(label).upper()
    if "LESS" in text:
        return 0.0
    if "MORE" in text:
        return float(numbers[0] + 1)
    return float(numbers[0])


def load_raw(path: Path = DATA_PATH) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")
    data = pd.read_csv(path)
    required = {"year", "population_group", "city", "population", "total_customers", *TARGETS}
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"Dataset is missing required columns: {sorted(missing)}")
    return data


def drop_spikes(data: pd.DataFrame, target: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (cleaned frame, removal log). Removed values become NaN."""
    df = data.copy()
    df.loc[df[target] <= 0, target] = np.nan
    df["_group_median"] = df.groupby(["year", "population_group"])[target].transform("median")
    removed: list[dict] = []

    for city, group in df.sort_values(["city", "year"]).groupby("city"):
        group = group[group[target].notna()]
        values = group[target].to_numpy(float)
        years = group["year"].to_numpy()
        index = group.index.to_numpy()
        peer_median = group["_group_median"].to_numpy(float)
        for k in range(len(values)):
            prev = values[k - 1] if k > 0 else None
            nxt = values[k + 1] if k < len(values) - 1 else None
            cur = values[k]
            reason = None
            others = np.delete(values, k)
            if peer_median[k] > 0 and len(others) > 0:
                peer_ratio = cur / peer_median[k]
                own_ratio = cur / float(np.median(others))
                too_high = peer_ratio >= EXTREME_PEER and own_ratio >= EXTREME_OWN
                too_low = peer_ratio <= 1 / EXTREME_PEER and own_ratio <= 1 / EXTREME_OWN
                if too_high or too_low:
                    reason = "extreme_vs_peers_and_own_history"
            if reason:
                pass
            elif prev is not None and nxt is not None:
                up = cur / prev >= SPIKE_JUMP and cur / nxt >= SPIKE_JUMP
                down = cur / prev <= 1 / SPIKE_JUMP and cur / nxt <= 1 / SPIKE_JUMP
                agree = max(prev / nxt, nxt / prev) < NEIGHBOUR_AGREE
                if (up or down) and agree:
                    reason = "spike_between_agreeing_neighbours"
            else:
                neighbour = prev if prev is not None else nxt
                if neighbour is not None and peer_median[k] > 0:
                    ratio = cur / neighbour
                    typical = PEER_RANGE[0] < neighbour / peer_median[k] < PEER_RANGE[1]
                    if (ratio >= EDGE_JUMP or ratio <= 1 / EDGE_JUMP) and typical:
                        reason = "edge_value_far_from_only_neighbour"
            if reason:
                removed.append({
                    "target": target, "city": city, "year": int(years[k]),
                    "removed_value": float(cur), "reason": reason,
                })
                df.loc[index[k], target] = np.nan

    df = df.drop(columns="_group_median")
    return df, pd.DataFrame(removed, columns=["target", "city", "year", "removed_value", "reason"])


def clean_target(data: pd.DataFrame, target: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """One tidy frame per target: valid fee rows plus peer-relative level."""
    cleaned, removal_log = drop_spikes(data, target)
    cleaned = cleaned.dropna(subset=[target]).sort_values(["city", "year"]).copy()
    peer = cleaned.groupby(["year", "population_group"])[target].transform("median")
    cleaned["rel"] = np.log(cleaned[target] / peer)
    cleaned["group_lower"] = np.log1p(cleaned["population_group"].map(group_lower_bound))
    return cleaned.reset_index(drop=True), removal_log


def origin_features(city: str, history: pd.DataFrame, target: str) -> dict:
    """Features describing a city using only rows up to (and including) the origin."""
    origin, first = history.iloc[-1], history.iloc[0]
    fees = history[target].to_numpy(float)
    changed = np.r_[False, np.diff(fees) != 0]
    span = int(origin["year"] - first["year"])
    last_change_year = history["year"].to_numpy()[changed].max() if changed.any() else first["year"]
    if len(history) > 1:
        gap = origin["year"] - history["year"].iloc[-2]
        last_ann = float(np.log(fees[-1] / fees[-2]) / gap)
    else:
        last_ann = np.nan
    return {
        "city": city,
        "a_year": int(origin["year"]),
        "fee_a": float(origin[target]),
        "log_fee": float(np.log(origin[target])),
        "log_pop": float(np.log(max(origin["population"], 1))),
        "log_cust": float(np.log(max(origin["total_customers"], 1))),
        "cust_per_pop": float(origin["total_customers"] / max(origin["population"], 1)),
        "group_lower": float(origin["group_lower"]),
        "rel": float(origin["rel"]),
        "n_obs": len(history),
        "hist_growth": float(np.log(fees[-1] / fees[0]) / span) if span > 0 else np.nan,
        "n_changes": int(changed.sum()),
        "yrs_since_change": int(origin["year"] - last_change_year),
        "span": span,
        "last_ann": last_ann,
    }


def build_pairs(clean: pd.DataFrame, target: str) -> pd.DataFrame:
    """All (origin, later target year) pairs per city, with annualized log growth."""
    rows: list[dict] = []
    for city, group in clean.groupby("city", sort=False):
        group = group.reset_index(drop=True)
        for i in range(len(group) - 1):
            base = origin_features(city, group.iloc[: i + 1], target)
            for j in range(i + 1, len(group)):
                later = group.iloc[j]
                horizon = int(later["year"] - base["a_year"])
                rows.append({
                    **base,
                    "b_year": int(later["year"]),
                    "h_raw": horizon,
                    "h": min(horizon, MAX_HORIZON),
                    "fee_b": float(later[target]),
                    "ann": float(np.log(later[target] / base["fee_a"]) / horizon),
                })
    return pd.DataFrame(rows)


def latest_origins(clean: pd.DataFrame, target: str) -> pd.DataFrame:
    """One feature row per city, taken at that city's most recent report."""
    rows = [origin_features(city, group, target)
            for city, group in clean.groupby("city", sort=False)]
    return pd.DataFrame(rows)
