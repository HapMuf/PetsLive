import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .auth_routes import router as auth_router
from .db import init_db
from .pages import router as pages_router
from .pet_routes import pet_loop, router as pet_router
from .request_routes import router as request_router
from .user_routes import router as user_router

app = FastAPI(title="Tamagotchi Server")

BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.on_event("startup")
async def startup_event():
    init_db()
    asyncio.create_task(pet_loop())


@app.get("/")
def root():
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(user_router)
app.include_router(pages_router)
app.include_router(pet_router)
app.include_router(request_router)
