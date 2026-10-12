from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from auth import router as auth_router, get_current_user
from database.queries import (
    search_cities, available_years, costs_by_year,
    city_history, city_forecast, compare_cities,
    population_groups, list_cities, model_performance,
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)

TARGETS = {"res_fee_5k_gal", "com_fee_50k_gal"}


def check_target(target: str):
    if target not in TARGETS:
        raise HTTPException(
            status_code=400,
            detail=f"target must be one of {sorted(TARGETS)}",
        )


@app.get("/")
def home():
    return {"message": "Wastewater Prediction Backend is running"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/api/cities")
def api_cities(q: str = "", user: str = Depends(get_current_user)):
    return search_cities(q)


@app.get("/api/years")
def api_years(user: str = Depends(get_current_user)):
    return available_years()


@app.get("/api/costs")
def api_costs(year: int, group: str | None = None, user: str = Depends(get_current_user)):
    return costs_by_year(year, group)


@app.get("/api/cities/{city}/history")
def api_history(city: str, user: str = Depends(get_current_user)):
    return city_history(city)


@app.get("/api/cities/{city}/forecast")
def api_forecast(city: str, target: str = "res_fee_5k_gal", user: str = Depends(get_current_user)):
    check_target(target)
    return city_forecast(city, target)


@app.get("/api/compare")
def api_compare(cities: str, target: str = "res_fee_5k_gal", user: str = Depends(get_current_user)):
    check_target(target)
    return compare_cities([c.strip() for c in cities.split(",")], target)


@app.get("/api/groups")
def api_groups(user: str = Depends(get_current_user)):
    return population_groups()


@app.get("/api/city-list")
def api_city_list(group: str = "", user: str = Depends(get_current_user)):
    return list_cities(group or None)


@app.get("/api/models")
def api_models(user: str = Depends(get_current_user)):
    return model_performance()