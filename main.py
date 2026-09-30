from fastapi import FastAPI
from auth import router as auth_router

app = FastAPI()

app.include_router(auth_router)


@app.get("/")
def home():
    return {
        "message": "Wastewater Prediction Backend is running"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }