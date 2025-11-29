"""
Alfa Operations Platform - Database Configuration
SQLite with SQLAlchemy async support
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from pathlib import Path

# Database file location
DATABASE_PATH = Path(__file__).parent.parent.parent / "data" / "alfa_platform.db"
DATABASE_URL = f"sqlite+aiosqlite:///{DATABASE_PATH}"


class Base(DeclarativeBase):
    """Base class for all models"""
    pass


# Create async engine
engine = create_async_engine(
    DATABASE_URL,
    echo=False,  # Set to True for SQL debugging
    future=True
)

# Session factory
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def init_db():
    """Initialize database and create all tables"""
    # Import models to register them with Base.metadata
    from app.models import database_models  # noqa: F401

    # Ensure data directory exists
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print(f"✅ Database initialized at {DATABASE_PATH}")


async def get_db() -> AsyncSession:
    """Dependency to get database session"""
    async with async_session() as session:
        yield session
