# Integration contract: database → FastAPI

Everything below is **real output** from `database/queries.py` against the current
database, not an example I made up. Build the endpoints against these shapes and
integration should be a merge, not a debugging session.

```python
from database.queries import (
    search_cities, available_years, costs_by_year,
    city_history, city_forecast, compare_cities,
)
```

Every function returns plain lists/dicts, so a FastAPI route can `return` the result
directly and it serializes to JSON as-is.

---

## `search_cities(prefix, limit=20)` → city search box

`search_cities("Mc", 5)`

```json
["McAllen", "McCamey", "McGregor", "McKinney", "McLean"]
```

Case-insensitive prefix match. Returns `[]` for no matches — not an error.

## `available_years()` → year dropdown

```json
[2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]
```

Read this rather than hardcoding the range, so a future year appears automatically.

## `costs_by_year(year, population_group=None)` → data table

`costs_by_year(2025)` → 157 rows, sorted by population descending:

```json
[
  {
    "city": "Houston",
    "population_group": "MORE THAN 500,000",
    "population": 2325502,
    "total_customers": 481640,
    "res_fee_5k_gal": 63.01,
    "com_fee_50k_gal": 556.96
  },
  {
    "city": "McKinney",
    "population_group": "200,001 - 350,000",
    "population": 213509,
    "total_customers": 73438,
    "res_fee_5k_gal": 64.0,
    "com_fee_50k_gal": 466.8
  }
]
```

Row counts vary a lot by year (661 in 2017, 125 in 2022, 157 in 2025) — that is the
source data, not a bug. Paginate if the table feels heavy.

## `city_history(city)` → trend chart / city detail

`city_history("Houston")` → one row per year that city reported:

```json
[
  {"year": 2017, "population": 2296224, "total_customers": 448410,
   "res_fee_5k_gal": 32.23, "com_fee_50k_gal": 316.15},
  {"year": 2018, "population": 2303482, "total_customers": 462000,
   "res_fee_5k_gal": 45.49, "com_fee_50k_gal": 325.49}
]
```

**Years can be missing.** Houston has 8 rows, not 9 — it did not report in 2024. Do not
assume a fixed-length array or index by `year - 2017`.

## `city_forecast(city, target="res_fee_5k_gal")` → the main dashboard chart

`target` is `"res_fee_5k_gal"` (residential) or `"com_fee_50k_gal"` (commercial).

```json
{
  "city": "Houston",
  "target": "res_fee_5k_gal",
  "history": [{"year": 2017, "value": 32.23}, {"year": 2018, "value": 45.49}],
  "predictions": []
}
```

`predictions` is **empty until the ML model is loaded** — that is expected right now,
not a failure. Once Quyen's forecasts are in it fills with 15 entries:

```json
{"year": 2026, "value": 66.16, "lower": 59.54, "upper": 72.78}
```

`lower`/`upper` may be `null` if the model does not produce confidence intervals, so
guard the chart against that.

## `compare_cities([...], target)` → comparison view

Returns a list of `city_forecast` objects, one per city, in the order requested.

---

## Nulls — the one thing likely to break a chart

A `$0.00` fee in the source survey means "not reported", not "free", so those are
stored as `NULL` and arrive as `null` in JSON. Any fee field can be null:

- `res_fee_10k_gal` and `com_fee_200k_gal` are null for **every** 2024 and 2025 row —
  the survey stopped publishing those columns.
- Scattered nulls elsewhere where a city reported no commercial customers.

`city_history` and `costs_by_year` return nulls as-is. `city_forecast` filters them
out, so it is the safer one to hand a chart.

## Suggested routes

| function | endpoint |
|---|---|
| `search_cities(q)` | `GET /api/cities?q=hou` |
| `available_years()` | `GET /api/years` |
| `costs_by_year(year, group)` | `GET /api/costs?year=2025&group=...` |
| `city_history(city)` | `GET /api/cities/{city}/history` |
| `city_forecast(city, target)` | `GET /api/cities/{city}/forecast?target=res_fee_5k_gal` |
| `compare_cities(cities, target)` | `GET /api/compare?cities=Houston,Plano` |

Naming is a suggestion — the shapes are what matter.

## Checking any of this yourself

```bash
python database/load_sqlite.py    # build the database from the committed CSV
python database/queries.py        # prints live output from every function
```

---

# Authentication: `database/users.py`

Argon2 via `argon2-cffi`, per Hannah. The plain password is never stored, logged, or
written to a file — only the hash goes in the `users` table.

```python
from database.users import verify_user, create_user

verify_user("alice", "hunter2")   # -> True / False
create_user("alice", "hunter2")   # raises sqlite3.IntegrityError if taken
```

`verify_user` is what the login endpoint calls. Two behaviours worth knowing:

- It returns `False` for an unknown username **and** a wrong password, and hashes a
  throwaway value in the unknown-username case so both take the same time. A faster
  "no such user" response would let someone probe which usernames exist.
- If the Argon2 parameters ever change, it transparently re-hashes the stored password
  on the next successful login.

Stored hashes look like `$argon2id$v=19$m=65536,t=3,p=4$...` — argon2id with the
RFC 9106 default parameters. The salt is inside the hash string, so there is no
separate salt column.

### Making a test account

Each of us creates our own locally — nothing shared, nothing committed:

```bash
python database/users.py add <username>   # prompts for a password, twice
python database/users.py list             # usernames only
```

The database file is gitignored, so these accounts stay on your own machine.

### What this does *not* cover

Session tokens are yours, not the database's. `verify_user` answers "are these
credentials correct" and nothing else — issuing and checking JWTs, expiry, and
logout all live in the backend. If tokens ever need to survive a server restart,
tell me and I will add a `sessions` table.
