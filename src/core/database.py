from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from src.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.database_echo,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,  # auto-reconnect on stale connections
    pool_recycle=1800,  # recycle connections every 30 min (prevents DB timeout kills)
    pool_timeout=10,  # wait up to 10s for a connection from pool
    connect_args={"ssl": False},
)

async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def escape_like(s: str) -> str:
    """Escape SQL LIKE/ILIKE wildcard characters (%, _) in user input.

    Use this before interpolating user-supplied strings into ILIKE patterns
    to prevent wildcard injection attacks.
    """
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def get_db() -> AsyncSession:  # type: ignore[misc]
    """FastAPI dependency: yields a session that auto-commits on success.

    Handlers use ``await db.flush()`` to push changes within the transaction.
    If the handler completes without exception, this generator commits.
    If any exception propagates, the entire transaction is rolled back —
    including all prior flushes — so partial writes cannot occur.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
