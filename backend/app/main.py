from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models  # Registers SQLAlchemy models.
from app.db import Base, engine, get_db
from app.routers import assessments, villages


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Development bootstrap only.
    # Replace create_all with Alembic migrations before production.
    Base.metadata.create_all(bind=engine)
    yield
    engine.dispose()


app = FastAPI(
    title="GraminSetu API",
    version="0.1.0",
    description=(
        "Development MVP. Geography fixtures are explicitly labelled. "
        "No lending decisions are made by this build."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.include_router(villages.router)
app.include_router(assessments.router)


@app.get("/api/health", tags=["System"])
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))

    return {
        "status": "ok",
        "database": "connected",
        "version": "0.1.0",
        "geography_mode": "demo_fixtures",
    }
