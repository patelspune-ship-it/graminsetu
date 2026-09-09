"""Create the advisory_sessions table for the hackathon MVP.

Run from backend:
    python -m app.create_advisory_tables

This is not a schema migration system. If the table already exists,
its columns and constraints are not modified or verified.
"""

from app.db import engine
from app.models import AdvisorySession


def create_advisory_tables() -> None:
    with engine.begin() as connection:
        AdvisorySession.__table__.create(
            bind=connection,
            checkfirst=True,
        )


def main() -> None:
    create_advisory_tables()
    print(
        "advisory_sessions table creation completed "
        "(existing table left unchanged)."
    )


if __name__ == "__main__":
    main()