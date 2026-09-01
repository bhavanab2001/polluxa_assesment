"""SQLAlchemy declarative base and database session management."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.config import settings


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""
    pass


# Engine and session factory — lazy initialization
_engine = None
_SessionFactory = None


def get_engine():
    """Get or create the SQLAlchemy engine."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.db_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            echo=False,
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Get or create the session factory."""
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionFactory


def get_session() -> Session:
    """Create a new database session."""
    factory = get_session_factory()
    return factory()


def init_db() -> None:
    """Create all tables defined in the models."""
    # Explicitly import all model modules so Base.metadata is fully populated
    import src.models.dimensions  # noqa: F401
    import src.models.facts  # noqa: F401
    import src.models.staging  # noqa: F401

    Base.metadata.create_all(get_engine())
