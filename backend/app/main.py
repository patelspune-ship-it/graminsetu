from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models  # Registers SQLAlchemy models.
from app.api_errors import install_error_handlers
from app.db import Base, engine, get_db
from app.routers import advisory, assessments, llm, villages, voice


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
        "Development MVP. Geography is imported from Census 2011 and "
        "OpenStreetMap; unknown evidence is reported as unknown. "
        "No lending decisions are made by this build."
    ),
    lifespan=lifespan,
)

install_error_handlers(app)

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
app.include_router(advisory.router)
app.include_router(llm.router)
app.include_router(voice.router)


@app.get("/api/health", tags=["System"])
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))

    return {
        "status": "ok",
        "database": "connected",
        "version": "0.1.0",
        "geography_mode": "imported_dataset",
    }