# Machine Learning Wastewater Cost Prediction

CSE 496 capstone. Web app that shows Texas municipal wastewater costs for 2017–2025
and predicts residential and commercial fees for the next 15 years.

**Team:** Hannah Winstead (backend & login) · Quyen Tran (machine learning) ·
Adriana Patino (database & integration) · Emily Gilkes (UI/UX)
**Sponsors:** Brown & Caldwell / University of Louisville — Dr. Yagnambhatt, Dr. Betgeri

## Repository layout

```
data_cleaning/     PDF -> CSV extraction and the cleaned dataset
database/          SQLite schema, loaders, and the query layer the API calls
source_pdfs/       source survey PDFs (shared via OneDrive, not in the repo)
```

## Getting set up

```bash
pip install pdfplumber
python data_cleaning/extract_pdfs.py    # PDFs  -> wastewater_costs_2017_2025.csv
python database/load_sqlite.py          # CSV   -> database/wastewater.db
python database/queries.py              # smoke test: prints sample query results
```

`wastewater.db` is not committed — it is rebuilt from the CSV in one command, so
everyone stays in sync from the same source data.

## Database schema

| table | holds |
|---|---|
| `cities` | one row per city (885) |
| `wastewater_costs` | one row per city per year, 2017–2025 (3,955), `UNIQUE(city_id, year)` |
| `predictions` | 15-year forecasts from the ML model, `UNIQUE(city_id, year, target, model_name)` |
| `model_metadata` | which model is deployed and its accuracy scores |
| `users` | login accounts — store password **hashes**, never plain text |

The two prediction targets are `res_fee_5k_gal` (residential monthly bill at 5,000 gal)
and `com_fee_50k_gal` (commercial at 50,000 gal). These are the only two fees reported
in every year 2017–2025, and they are the ones named in the sponsor spec.

## Query layer — for the FastAPI endpoints

`database/queries.py` returns plain dicts, ready to serialize as JSON:

| function | suggested endpoint |
|---|---|
| `search_cities(prefix)` | `GET /api/cities?q=hou` |
| `available_years()` | `GET /api/years` |
| `costs_by_year(year, population_group=None)` | `GET /api/costs?year=2025` |
| `city_history(city)` | `GET /api/cities/{city}/history` |
| `city_forecast(city, target)` | `GET /api/cities/{city}/forecast` |
| `compare_cities([...], target)` | `GET /api/compare?cities=a,b` |

`city_forecast` returns `{history: [...], predictions: [...]}` so the chart can draw
one continuous line with the forecast portion dashed. It only returns predictions from
the model flagged `is_deployed = 1` in `model_metadata`.

## Handing predictions to the database (ML → DB)

The model script writes a CSV with these columns:

```
city,year,target,predicted_value,lower_bound,upper_bound,model_name
```

Then:

```bash
python database/load_predictions.py predictions.csv
```

The loader validates every row before writing anything — unknown city spellings and
invalid target names are reported and nothing is loaded. Re-running replaces that
model's rows rather than appending, so forecasts can be regenerated freely.

## Adding a new year of data

The survey PDFs are not tracked in git (they are large and never change). Get them
from the team OneDrive folder and put them in a `source_pdfs/` directory at the
project root — you only need this if you want to regenerate the CSV. Building the
database from the committed CSV does not require them.

To add a new year: drop the new survey PDF into `source_pdfs/`, then re-run the two
commands in *Getting set up*. No schema or UI changes are needed — this is what
satisfies the scalability requirement.

Known data-quality issues and the decisions made about them are documented in
[data_cleaning/README.md](data_cleaning/README.md).
