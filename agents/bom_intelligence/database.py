from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import (
    JSON, Boolean, Column, DateTime, Float, Integer, String, Text, create_engine,
)
from sqlalchemy.orm import Session, declarative_base, sessionmaker

Base = declarative_base()

_engine = None
_SessionLocal = None


def init_db(database_url: str | None = None) -> None:
    """
    Initialize the database engine and create tables.

    Falls back gracefully if PostgreSQL is unavailable, logging a warning.
    The in-memory cache in api.py remains the source of truth for the POC.

    Phase 2: migrate to Alembic for schema migrations.
    """
    global _engine, _SessionLocal
    url = database_url or os.environ.get(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/bom_intelligence",
    )
    try:
        _engine = create_engine(url, pool_pre_ping=True)
        _SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(_engine)
        print(f"[db] Connected to {url.split('@')[-1]}")
    except Exception as exc:
        print(f"[db] WARNING: could not connect to database — {exc}")
        print("[db] Running in memory-only mode (POC). Set DATABASE_URL in .env to persist.")
        _engine = None
        _SessionLocal = None


@contextmanager
def get_session():
    """Yield a database session. No-op if database is unavailable."""
    if _SessionLocal is None:
        yield None
        return
    session: Session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ── ORM Models ────────────────────────────────────────────────────────────────

class DBComponent(Base):
    """Stores all BOM rows (primary + substitutes) for a loaded SKU."""
    __tablename__ = "bom_components"

    id                     = Column(Integer, primary_key=True, autoincrement=True)
    sku_id                 = Column(String, nullable=False, index=True)
    item_number            = Column(String, nullable=False, index=True)
    substitute_for         = Column(String, nullable=True)
    description            = Column(Text, nullable=True)
    manufacturer           = Column(String, nullable=True)
    mpn                    = Column(String, nullable=True)
    lifecycle_phase        = Column(String, nullable=True)
    criticality_type       = Column(String, nullable=True)
    country_of_origin      = Column(String, nullable=True)
    quantity               = Column(Float, nullable=True)
    lead_time_days         = Column(Float, nullable=True)
    moq                    = Column(Float, nullable=True)
    multiple_source_status = Column(String, nullable=True)
    unique_to_samsara      = Column(Boolean, nullable=True)
    is_substitute          = Column(Boolean, default=False)
    vendor                 = Column(String, nullable=True)
    vendor_part            = Column(String, nullable=True)
    flag_risk_review       = Column(Boolean, nullable=True)
    loaded_at              = Column(DateTime, default=datetime.utcnow)


class DBRiskScore(Base):
    """Stores computed risk scores per SKU load event."""
    __tablename__ = "risk_scores"

    id                          = Column(Integer, primary_key=True, autoincrement=True)
    sku_id                      = Column(String, nullable=False, index=True)
    sku_description             = Column(Text, nullable=True)
    total_components            = Column(Integer)
    single_source_count         = Column(Integer)
    components_with_substitutes = Column(Integer)
    weak_substitute_count       = Column(Integer)   # same mfr or same region
    at_risk_lifecycle_count     = Column(Integer)   # EOL / LTB / NRND
    critical_parts_count        = Column(Integer)   # Field / Safety / Field & Safety
    unique_to_samsara_count     = Column(Integer)   # Unique to Samsara ecosystem
    risk_score                  = Column(Float)
    risk_level                  = Column(String)
    top_risks                   = Column(JSON)
    component_risks             = Column(JSON)      # serialized list[ComponentRisk]
    computed_at                 = Column(DateTime, default=datetime.utcnow)
