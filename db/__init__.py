from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

from config import Config
from db.models import Base

engine = create_engine(Config.DATABASE_URL, future=True)
SessionLocal = scoped_session(sessionmaker(bind=engine, future=True))


def init_db():
    """Create tables if they don't exist. Safe to call on every startup."""
    Base.metadata.create_all(engine)
