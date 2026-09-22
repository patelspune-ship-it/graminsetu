from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Assessment(Base):
    __tablename__ = "assessments"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    # MVP profile payload; monetary values remain JSON integers.
    # Normalize into dedicated tables when the schema stabilizes.
    profile: Mapped[dict] = mapped_column(JSON, nullable=False)

    status: Mapped[str] = mapped_column(
        String(40),
        default="profile_saved",
        nullable=False,
    )


class AdvisorySession(Base):
    __tablename__ = "advisory_sessions"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    # Optional: direct financial modelling need not start with a village.
    # No FK until the existing village storage interface is confirmed.
    village_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )

    # Application-controlled workflow state, not a credit approval.
    # An infeasible capital stack is a completed calculation, not a failure.
    status: Mapped[str] = mapped_column(
        String(40),
        default="created",
        nullable=False,
    )

    # Version of our stored payload contract, not the database schema.
    payload_version: Mapped[int] = mapped_column(
        default=1,
        nullable=False,
    )

    # Validated inputs sufficient to reproduce the stored calculations.
    # Assign a fresh dictionary when updating; plain SQLAlchemy JSON does
    # not track arbitrary nested in-place mutations.
    session_data: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
    )

    # These snapshots must correspond to session_data. Services must clear
    # dependent snapshots and DPR metadata when their inputs change.
    #
    # Money: integer paise.
    # Ratios: explicit numerator/denominator objects, never float.
    # None: SQL NULL, meaning this result has not been stored.
    viability_result: Mapped[dict | None] = mapped_column(
        JSON(none_as_null=True),
        nullable=True,
    )

    financial_model: Mapped[dict | None] = mapped_column(
        JSON(none_as_null=True),
        nullable=True,
    )

    capital_stack: Mapped[dict | None] = mapped_column(
        JSON(none_as_null=True),
        nullable=True,
    )

    # Opaque server-generated artifact identifier, not a filesystem path.
    # The download route will resolve it under the configured DPR directory.
    # A UUID is an identifier, not a substitute for access control.
    dpr_artifact_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        unique=True,
    )

    dpr_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Safe machine-readable failure code only.
    # Do not persist raw exceptions, tracebacks or filesystem paths here.
    last_error_code: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )


class FeasibilityReportCache(Base):
    """Persistent cache of Gemini-generated feasibility reports, keyed on
    everything that can change the narrative content (see
    app.llm.feasibility_report_cache.cache_key). A cache hit is returned
    verbatim and never calls Gemini — this exists so a demo/recording
    never depends on live Gemini quota for villages/archetypes/languages
    that have already been generated once.
    """

    __tablename__ = "feasibility_report_cache"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)

    village_lgd: Mapped[str] = mapped_column(String(20), index=True)
    archetype_id: Mapped[str] = mapped_column(String(100), index=True)
    lang: Mapped[str] = mapped_column(String(5))

    report: Mapped[dict] = mapped_column(JSON, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )