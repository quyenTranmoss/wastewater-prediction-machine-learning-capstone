"""
To fix the typos in the fees like one year commmercial fee for alma is 500 then next year it's 55 then next year it's 600
Conservative decimal-typo detector for wastewater fee CSVs.

Run from repository root:
    python data_cleaning/detect_fee_typos.py

Writes a checked copy and an audit CSV; never overwrites the source.
Only auto-corrects a cell when:
  1) its corrected value fits between similar previous and next observations
     for the same city and fee column; AND
  2) at least one other fee column in the same city/year independently indicates
     the same decimal shift.
Single-column anomalies are flagged for manual review, not changed.
Zero fees are treated as missing/not applicable.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import pandas as pd

FEE_COLUMNS = [
    "res_fee_5k_gal", "res_fee_10k_gal",
    "com_fee_50k_gal", "com_fee_200k_gal",
]
DECIMAL_FACTORS = (0.01, 0.1, 10.0, 100.0)
MAX_GAP = 2
MAX_RATIO = 1.5
MIN_CORROBORATING_COLUMNS = 2


def spread(values):
    values = [float(x) for x in values if pd.notna(x) and float(x) > 0]
    return max(values) / min(values) if len(values) >= 2 else float("inf")


def find_candidates(data):
    found = []
    for city, city_rows in data.groupby("city", dropna=False):
        city_rows = city_rows.sort_values("year")
        for col in FEE_COLUMNS:
            series = city_rows[["year", col]].copy()
            series[col] = pd.to_numeric(series[col], errors="coerce")
            series = series[series[col].notna() & (series[col] > 0)]
            records = series.to_dict("records")
            for i in range(1, len(records) - 1):
                prev, cur, nxt = records[i - 1:i + 2]
                if cur["year"] - prev["year"] > MAX_GAP or nxt["year"] - cur["year"] > MAX_GAP:
                    continue
                before, observed, after = float(prev[col]), float(cur[col]), float(nxt[col])
                if spread([before, after]) > MAX_RATIO:
                    continue
                for factor in DECIMAL_FACTORS:
                    suggested = observed * factor
                    if spread([before, suggested, after]) <= MAX_RATIO:
                        found.append({
                            "city": city, "year": int(cur["year"]), "column": col,
                            "observed_value": observed, "suggested_value": suggested,
                            "factor": factor, "previous_year": int(prev["year"]),
                            "previous_value": before, "next_year": int(nxt["year"]),
                            "next_value": after,
                            "evidence": "two_sided_temporal_pattern",
                        })
                        break
    return pd.DataFrame(found)



def find_latest_year_candidates(data):
    """Flag suspicious newest observations using prior history only.

    These are never auto-corrected because there is no later observation yet
    to confirm whether the apparent jump is a typo or a genuine rate change.
    """
    found = []
    for city, city_rows in data.groupby("city", dropna=False):
        city_rows = city_rows.sort_values("year")
        latest_year = int(city_rows["year"].max())
        latest = city_rows[city_rows["year"] == latest_year].iloc[-1]
        history = city_rows[city_rows["year"] < latest_year]
        for col in FEE_COLUMNS:
            observed = pd.to_numeric(pd.Series([latest[col]]), errors="coerce").iloc[0]
            if pd.isna(observed) or observed <= 0:
                continue
            prior = history[["year", col]].copy()
            prior[col] = pd.to_numeric(prior[col], errors="coerce")
            prior = prior[prior[col].notna() & (prior[col] > 0)]
            if prior.empty:
                continue
            prev = prior.sort_values("year").iloc[-1]
            if latest_year - int(prev["year"]) > MAX_GAP:
                continue
            before = float(prev[col])
            for factor in DECIMAL_FACTORS:
                suggested = float(observed) * factor
                if spread([before, suggested]) <= MAX_RATIO:
                    found.append({
                        "city": city, "year": latest_year, "column": col,
                        "observed_value": float(observed), "suggested_value": suggested,
                        "factor": factor, "previous_year": int(prev["year"]),
                        "previous_value": before, "next_year": np.nan,
                        "next_value": np.nan, "evidence": "latest_year_one_sided_pattern",
                    })
                    break
    return pd.DataFrame(found)


def detect_and_correct(data):
    required = {"city", "year", *FEE_COLUMNS}
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")
    result = data.copy()
    result["year"] = pd.to_numeric(result["year"], errors="raise").astype(int)

    # First, find retrospective anomalies that have both earlier and later
    # observations. Apply only multi-column corroborated corrections.
    historical = find_candidates(result)
    audit_rows = []
    if not historical.empty:
        historical["corroborating_columns"] = historical.groupby(
            ["city", "year", "factor"]
        )["column"].transform("nunique")
        for _, c in historical.iterrows():
            confirmed = int(c["corroborating_columns"]) >= MIN_CORROBORATING_COLUMNS
            status = "AUTO_CORRECTED" if confirmed else "REVIEW_REQUIRED"
            if confirmed:
                mask = result["city"].eq(c["city"]) & result["year"].eq(int(c["year"]))
                result.loc[mask, c["column"]] = float(c["suggested_value"])
            row = c.to_dict()
            row.update({
                "confidence": "high" if confirmed else "medium",
                "status": status,
                "evidence": (
                    "same decimal shift in multiple fee columns and two-sided history"
                    if confirmed else
                    "isolated two-sided decimal-shift pattern; manual confirmation required"
                ),
            })
            audit_rows.append(row)

    # Then check the latest year against the now-corrected history. Since no
    # later year exists to confirm the pattern, these are always review-only.
    latest = find_latest_year_candidates(result)
    if not latest.empty:
        existing = {
            (r["city"], int(r["year"]), r["column"])
            for r in audit_rows
        }
        for _, c in latest.iterrows():
            key = (c["city"], int(c["year"]), c["column"])
            if key in existing:
                continue
            row = c.to_dict()
            row.update({
                "corroborating_columns": 1,
                "confidence": "low",
                "status": "REVIEW_REQUIRED",
                "evidence": "latest-year jump has no later observation; manual confirmation required",
            })
            audit_rows.append(row)

    if not audit_rows:
        return result, pd.DataFrame(columns=[
            "city", "year", "column", "observed_value", "suggested_value",
            "factor", "confidence", "status", "evidence"
        ])
    audit = pd.DataFrame(audit_rows).sort_values(
        ["status", "city", "year", "column"]
    )
    return result, audit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data_cleaning/wastewater_costs_2017_2025.csv")
    parser.add_argument("--output", default=None)
    parser.add_argument("--audit", default=None)
    args = parser.parse_args()

    source = Path(args.input)
    if not source.exists():
        raise FileNotFoundError(f"Input CSV not found: {source}")
    output = Path(args.output) if args.output else source.with_name(source.stem + "_checked.csv")
    audit_path = Path(args.audit) if args.audit else source.with_name("fee_typo_audit.csv")
    if output.resolve() == source.resolve():
        raise ValueError("Output path must differ from input path; source files are never overwritten.")

    original = pd.read_csv(source)
    corrected, audit = detect_and_correct(original)
    output.parent.mkdir(parents=True, exist_ok=True)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    corrected.to_csv(output, index=False)
    audit.to_csv(audit_path, index=False)

    auto = int((audit["status"] == "AUTO_CORRECTED").sum()) if not audit.empty else 0
    review = int((audit["status"] == "REVIEW_REQUIRED").sum()) if not audit.empty else 0
    print(f"Rows scanned: {len(original):,}")
    print(f"Candidate fee cells: {len(audit):,}")
    print(f"Auto-corrected cells: {auto:,}")
    print(f"Manual-review cells: {review:,}")
    print(f"Checked dataset: {output}")
    print(f"Audit report: {audit_path}")
    print("Original input was not modified.")


if __name__ == "__main__":
    main()
