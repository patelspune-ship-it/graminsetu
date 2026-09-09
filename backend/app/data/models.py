from datetime import datetime
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Dataset(Base):
    __tablename__ = "datasets"

    # Examples: osm:Nashik, census:Nashik
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False)

    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class OsmPlace(Base):
    __tablename__ = "osm_places"

    district: Mapped[str] = mapped_column(String(100), primary_key=True)
    osm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    names: Mapped[list] = mapped_column(JSONB, nullable=False)
    tags: Mapped[dict] = mapped_column(JSONB, nullable=False)

    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)

    geom: Mapped[Any] = mapped_column(
        Geography(geometry_type="POINT", srid=4326),
        nullable=False,
        spatial_index=True,
    )


class OsmPoi(Base):
    __tablename__ = "osm_pois"

    district: Mapped[str] = mapped_column(String(100), primary_key=True)
    osm_type: Mapped[str] = mapped_column(String(10), primary_key=True)
    osm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    category: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[dict] = mapped_column(JSONB, nullable=False)

    geom: Mapped[Any] = mapped_column(
        Geography(geometry_type="POINT", srid=4326),
        nullable=False,
        spatial_index=True,
    )


class Village(Base):
    __tablename__ = "villages"

    village_lgd: Mapped[str] = mapped_column(String(20), primary_key=True)
    census_code: Mapped[str | None] = mapped_column(String(20))

    name: Mapped[str] = mapped_column(Text, nullable=False)
    district: Mapped[str] = mapped_column(String(100), index=True)
    state: Mapped[str] = mapped_column(
        String(100), default="Maharashtra", nullable=False
    )

    population: Mapped[int] = mapped_column(BigInteger, nullable=False)
    households: Mapped[int | None] = mapped_column(BigInteger)
    workers: Mapped[int | None] = mapped_column(BigInteger)

    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)

    geom: Mapped[Any | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326),
        nullable=True,
        spatial_index=True,
    )

    coordinate_method: Mapped[str] = mapped_column(String(100))
    coordinate_match_score: Mapped[float | None] = mapped_column(Float)

    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False)


class ViabilityIndex(Base):
    __tablename__ = "viability_index"

    village_lgd: Mapped[str] = mapped_column(
        ForeignKey("villages.village_lgd", ondelete="CASCADE"),
        primary_key=True,
    )
    archetype_id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
    )

    # Contains the four geographic sub-scores, not a fictitious
    # personalised recommendation.
    geographic_scores: Mapped[list] = mapped_column(JSONB, nullable=False)
    features: Mapped[dict] = mapped_column(JSONB, nullable=False)
    warnings: Mapped[list] = mapped_column(JSONB, nullable=False)

    # 0..8000 because geographic weights total 80%.
    known_contribution_bps: Mapped[int] = mapped_column(Integer)
    known_weight_bps: Mapped[int] = mapped_column(Integer)

    dataset_signature: Mapped[str] = mapped_column(String(64))
    model_signature: Mapped[str] = mapped_column(String(64))

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )