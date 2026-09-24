# Data cleaning — Wastewater Cost Prediction (CSE 496)

Source: Texas Municipal League "Residential and Commercial Wastewater Costs Details"
survey PDFs, 2017–2025 (in `../source_pdfs/`, shared via the team OneDrive).

## How to rebuild the dataset

```
pip install pdfplumber
python data_cleaning/extract_pdfs.py
```

Produces `wastewater_costs_2017_2025.csv` (one row per city per year) and
`extraction_report.txt` (row counts + data-quality flags). Row counts per year match
the "Total Number of Cities Reporting" line printed in each PDF.

## Columns

| column             | meaning                                                   |
|--------------------|-----------------------------------------------------------|
| year               | survey year (2017–2025)                                   |
| population_group   | TML size bracket the city was listed under, e.g. `2,001 - 5,000` |
| city               | city name as printed                                      |
| population         | city population reported that year                        |
| total_customers    | number of sewer customers                                 |
| res_fee_5k_gal     | residential monthly sewer bill at 5,000 gal (USD)         |
| res_fee_10k_gal    | residential bill at 10,000 gal — **blank for 2024–2025**  |
| com_fee_50k_gal    | commercial monthly sewer bill at 50,000 gal (USD)         |
| com_fee_200k_gal   | commercial bill at 200,000 gal — **blank for 2024–2025**  |

The two fees every year has (`res_fee_5k_gal`, `com_fee_50k_gal`) are the ones the
sponsor spec calls out, so those are the prediction targets.

## Known data issues (decide with Quyen before training)

1. **Uneven coverage.** 885 distinct cities, but only 9 appear in all 9 years.
   2022 (125 cities) and 2025 (158) are much thinner than 2017 (661).
   Suggest: for the dashboard keep everything; for ML training, filter to cities
   with N+ years of data (e.g. ≥5) or use population_group as a feature so sparse
   cities can borrow strength from similar-sized ones.
2. **$0.00 fees** — 282 rows have a $0 residential-5k or commercial-50k fee. Usually
   means "no commercial customers" or "flat rate not reported", not a real price.
   Suggest: treat 0 as missing (NULL) for the fee columns.
3. **Duplicate rows in the source.** 12 cities appear twice in one year. 9 were exact
   copies (dropped). 3 conflict — Tatum 2020, Martindale 2024, Kermit 2025 — the
   script keeps the first and lists both in `extraction_report.txt`.
4. **Typo in source, corrected (team decision 9/16):** Houston 2017 `total_customers`
   is printed as 44,841; every other year is ~460,000. The script overrides it to
   448,410 (see `CORRECTIONS` in `extract_pdfs.py`). Add future fixes there.
5. **Column layout changes by year.** 2017 prints Customers between the residential
   and commercial fees; 2024–2025 dropped the 10k/200k gallon columns. The script
   handles this — just be aware if you look at the raw PDFs.
6. **City names are as-printed.** Spot-check for the same city spelled two ways
   before using `city` as a join key (e.g. "Pecos City" vs "Pecos").

## Next step (Database milestone, Sept 13–17)

Load the CSV into SQLite: one `cities` table (id, name) and one `wastewater_costs`
table (city_id, year, population_group, population, total_customers, the four fees),
with `UNIQUE(city_id, year)`. Adding a 2026 PDF later = rerun the script + reload —
no UI change needed.
