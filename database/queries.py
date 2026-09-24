"""
The filtering queries the backend (FastAPI) will call. Each returns plain dicts so
Hannah can return them straight from an endpoint as JSON.

Try it:  python database/queries.py
"""
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wastewater.db")


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def search_cities(prefix: str, limit: int = 20):
    """City search box: 'hou' -> ['Houston', ...]."""
    with connect() as c:
        return [r["name"] for r in c.execute(
            "SELECT name FROM cities WHERE name LIKE ? ORDER BY name LIMIT ?",
            (prefix + "%", limit))]


def city_history(city: str):
    """All years for one city -> feeds the trend chart."""
    with connect() as c:
        return [dict(r) for r in c.execute(
            """SELECT w.year, w.population, w.total_customers,
                      w.res_fee_5k_gal, w.com_fee_50k_gal
               FROM wastewater_costs w JOIN cities ci ON ci.id = w.city_id
               WHERE ci.name = ? ORDER BY w.year""", (city,))]


def costs_by_year(year: int, population_group: str | None = None):
    """Data table filtered by year (and optionally by population bracket)."""
    sql = """SELECT ci.name AS city, w.population_group, w.population,
                    w.total_customers, w.res_fee_5k_gal, w.com_fee_50k_gal
             FROM wastewater_costs w JOIN cities ci ON ci.id = w.city_id
             WHERE w.year = ?"""
    args = [year]
    if population_group:
        sql += " AND w.population_group = ?"
        args.append(population_group)
    with connect() as c:
        return [dict(r) for r in c.execute(sql + " ORDER BY w.population DESC", args)]


def city_forecast(city: str, target: str = "res_fee_5k_gal"):
    """Historical values + 15-year predictions for one city, ready to plot.

    Returns {"history": [{year, value}], "predictions": [{year, value, lower, upper}]}
    so the chart can draw one continuous line with the forecast dashed.
    """
    col = {"res_fee_5k_gal": "res_fee_5k_gal", "com_fee_50k_gal": "com_fee_50k_gal"}[target]
    with connect() as c:
        history = [{"year": r["year"], "value": r[col]} for r in c.execute(
            f"""SELECT w.year, w.{col} FROM wastewater_costs w
                JOIN cities ci ON ci.id = w.city_id
                WHERE ci.name = ? AND w.{col} IS NOT NULL ORDER BY w.year""", (city,))]
        predictions = [{"year": r["year"], "value": r["predicted_value"],
                        "lower": r["lower_bound"], "upper": r["upper_bound"]}
                       for r in c.execute(
            """SELECT p.year, p.predicted_value, p.lower_bound, p.upper_bound
               FROM predictions p JOIN cities ci ON ci.id = p.city_id
               JOIN model_metadata m ON m.model_name = p.model_name AND m.is_deployed = 1
               WHERE ci.name = ? AND p.target = ? ORDER BY p.year""", (city, target))]
    return {"city": city, "target": target, "history": history, "predictions": predictions}


def compare_cities(cities: list[str], target: str = "res_fee_5k_gal"):
    """Side-by-side history for several cities -> the city-comparison chart."""
    return [city_forecast(c, target) for c in cities]


def available_years():
    with connect() as c:
        return [r["year"] for r in c.execute(
            "SELECT DISTINCT year FROM wastewater_costs ORDER BY year")]


if __name__ == "__main__":
    print("years:", available_years())
    print("search 'Mc':", search_cities("Mc"))
    print("Houston history:")
    for row in city_history("Houston"):
        print("  ", row)
    print("2025, MORE THAN 500,000:", costs_by_year(2025, "MORE THAN 500,000"))
    print("2024 row count:", len(costs_by_year(2024)))
    print("Houston forecast:", city_forecast("Houston"))
