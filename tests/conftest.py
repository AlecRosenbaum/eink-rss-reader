import pytest
import tempfile
from pathlib import Path

from app.database import Database


@pytest.fixture
async def db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    database = Database(db_path)
    await database.connect()

    yield database

    await database.disconnect()
    db_path.unlink(missing_ok=True)


@pytest.fixture
async def user(db: Database):
    """Create a test user."""
    from app.services.crud import create_user

    return await create_user(db, "testuser")


@pytest.fixture
async def feed(db: Database, user):
    """Create a test feed."""
    from app.services.crud import create_feed

    return await create_feed(db, user.id, "https://example.com/feed.xml", ["tech", "news"])
