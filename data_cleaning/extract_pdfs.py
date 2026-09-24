"""
Extract the Texas Municipal League "Residential and Commercial Wastewater Costs
Details" PDFs (2017-2025) into one tidy CSV.

Usage (from the project root):
    python data_cleaning/extract_pdfs.py

Output:
    data_cleaning/wastewater_costs_2017_2025.csv   (one row per city per year)
    data_cleaning/extraction_report.txt            (row counts + data-quality notes)

Column layouts differ by year, so we detect the layout from the header text:
    2017        : Population, Res 5k, Res 10k, Customers, Com 50k, Com 200k
    2018-2023   : Population, Customers, Res 5k, Res 10k, Com 50k, Com 200k
    2024-2025   : Population, Customers, Res 5k, Com 50k
"""
import csv
import glob
import os
import re

import pdfplumber

HERE = os.path.dirname(os.path.abspath(__file__))
PDF_DIR = os.path.join(HERE, "..", "OneDrive_1_9-5-2026")
OUT_CSV = os.path.join(HERE, "wastewater_costs_2017_2025.csv")
OUT_REPORT = os.path.join(HERE, "extraction_report.txt")

# Known typos in the source PDFs, agreed with the team (see README "Known data issues").
# (year, city, column) -> corrected value
CORRECTIONS = {
    (2017, "Houston", "total_customers"): 448_410,  # PDF says 44,841; every other year ~460k
}

COLUMNS = [
    "year", "population_group", "city", "population", "total_customers",
    "res_fee_5k_gal", "res_fee_10k_gal", "com_fee_50k_gal", "com_fee_200k_gal",
]

# A number like 2,296,224 or 32.23 or 0.00
NUM = r"-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?"
NUM_RE = re.compile(NUM)
# Population-group header lines, e.g. "MORE THAN 500,000", "200,001 - 350,000", "2,000 OR LESS"
GROUP_RE = re.compile(r"^(MORE THAN [\d,]+|[\d,]+ - [\d,]+|[\d,]+ OR LESS)$")
SKIP_PREFIXES = (
    "Residential and Commercial Wastewater Costs", "Details", "Residential Sewer",
    "Population Group", "City Name", "5,000 Gal.", "Total Number of Cities",
)


def to_number(s: str):
    s = s.replace(",", "")
    return float(s) if "." in s else int(s)


def detect_layout(first_page_text: str):
    """Return (year, list of field names in the order numbers appear on a row)."""
    m = re.search(r"Details\s*\n\s*(\d{4})", first_page_text)
    year = int(m.group(1))
    if "10,000 Gal." not in first_page_text:
        fields = ["population", "total_customers", "res_fee_5k_gal", "com_fee_50k_gal"]
    elif year == 2017:
        # 2017 prints Customers between the residential and commercial fee columns
        fields = ["population", "res_fee_5k_gal", "res_fee_10k_gal",
                  "total_customers", "com_fee_50k_gal", "com_fee_200k_gal"]
    else:
        fields = ["population", "total_customers", "res_fee_5k_gal",
                  "res_fee_10k_gal", "com_fee_50k_gal", "com_fee_200k_gal"]
    return year, fields


def parse_pdf(path: str, notes: list):
    rows = []
    with pdfplumber.open(path) as pdf:
        year, fields = detect_layout(pdf.pages[0].extract_text() or "")
        n_fields = len(fields)
        group = None
        for page_no, page in enumerate(pdf.pages, start=1):
            for line in (page.extract_text() or "").splitlines():
                line = line.strip()
                if not line or line.startswith(SKIP_PREFIXES) or re.fullmatch(r"\d{4}", line):
                    continue
                if GROUP_RE.match(line):
                    group = line
                    continue
                if "Averages" in line:
                    continue  # summary row, not a city
                # Split into leading city-name text and trailing numbers
                tokens = line.split()
                nums = []
                while tokens and NUM_RE.fullmatch(tokens[-1]):
                    nums.insert(0, tokens.pop())
                city = " ".join(tokens)
                if not city or len(nums) != n_fields:
                    notes.append(f"{year} p{page_no}: could not parse -> {line!r}")
                    continue
                row = {"year": year, "population_group": group, "city": city}
                row.update({f: to_number(v) for f, v in zip(fields, nums)})
                rows.append(row)
    return year, rows


def main():
    notes = []
    all_rows = []
    per_year = {}
    for pdf_path in sorted(glob.glob(os.path.join(PDF_DIR, "*.pdf"))):
        if "Machine Learning" in os.path.basename(pdf_path):
            continue  # project description, not data
        year, rows = parse_pdf(pdf_path, notes)
        per_year[year] = (os.path.basename(pdf_path), len(rows))
        all_rows.extend(rows)

    for r in all_rows:
        for col in ("population", "total_customers", "res_fee_5k_gal", "res_fee_10k_gal",
                    "com_fee_50k_gal", "com_fee_200k_gal"):
            fix = CORRECTIONS.get((r["year"], r["city"], col))
            if fix is not None:
                notes.append(f"{r['year']} {r['city']}: {col} corrected {r[col]} -> {fix}")
                r[col] = fix

    all_rows.sort(key=lambda r: (r["year"], r["city"]))

    # The source survey lists a few cities twice in the same year. Drop exact
    # copies; when the two rows disagree keep the first and flag it for review.
    seen, conflicts, deduped = {}, [], []
    for r in all_rows:
        key = (r["year"], r["city"])
        if key not in seen:
            seen[key] = r
            deduped.append(r)
        elif r != seen[key]:
            conflicts.append((seen[key], r))
    all_rows = deduped
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(all_rows)

    # ---- data-quality checks ----
    zero_fee = [r for r in all_rows if r["res_fee_5k_gal"] == 0 or r["com_fee_50k_gal"] == 0]
    cities_per_year = {}
    for r in all_rows:
        cities_per_year.setdefault(r["city"], set()).add(r["year"])
    all_years = sorted(per_year)
    full_coverage = sorted(c for c, ys in cities_per_year.items() if ys == set(all_years))

    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        f.write("Rows extracted per year\n")
        for y in all_years:
            f.write(f"  {y}: {per_year[y][1]:4d} cities   ({per_year[y][0]})\n")
        f.write(f"\nTotal rows: {len(all_rows)}\n")
        f.write(f"Distinct cities: {len(cities_per_year)}\n")
        f.write(f"Cities present in ALL {len(all_years)} years: {len(full_coverage)}\n")
        f.write("  " + ", ".join(full_coverage) + "\n")
        f.write(f"\nCities listed twice in one year with DIFFERENT values (kept first, review these): {len(conflicts)}\n")
        for kept, dropped in conflicts:
            f.write(f"  {kept['year']} {kept['city']}\n    kept:    {kept}\n    dropped: {dropped}\n")
        f.write(f"\nRows with a $0.00 residential-5k or commercial-50k fee: {len(zero_fee)}\n")
        f.write(f"\nUnparsed lines: {len(notes)}\n")
        for n in notes:
            f.write("  " + n + "\n")

    print(open(OUT_REPORT, encoding="utf-8").read())
    print(f"Wrote {OUT_CSV}")


if __name__ == "__main__":
    main()
