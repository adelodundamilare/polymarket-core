from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from polymarket_core.config import settings
from polymarket_core.logger import get_logger

logger = get_logger(__name__)

Base = declarative_base()

def get_engine():
    return create_engine(
        settings.database_url,
        pool_size=settings.database_pool_size,
        echo=False,
    )

def get_session_factory():
    engine = get_engine()
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )

def create_tables() -> None:
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created")

def drop_tables() -> None:
    engine = get_engine()
    Base.metadata.drop_all(bind=engine)
    logger.info("Database tables dropped")

def get_session():
    SessionLocal = get_session_factory()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
