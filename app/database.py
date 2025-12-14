import aiosqlite
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from app.config import settings

# SQL schema for creating tables
SCHEMA = """
-- Users (just a key, no auth)
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    key TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- RSS/Atom Feeds
CREATE TABLE IF NOT EXISTS feeds (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    last_fetched TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    UNIQUE(user_id, url)
);

-- Feed Labels (many-to-many)
CREATE TABLE IF NOT EXISTS feed_labels (
    feed_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    PRIMARY KEY (feed_id, label),
    FOREIGN KEY (feed_id) REFERENCES feeds(id) ON DELETE CASCADE
);

-- Articles
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY,
    feed_id INTEGER NOT NULL,
    guid TEXT NOT NULL,
    title TEXT,
    link TEXT,
    content TEXT,
    summary TEXT,
    published_at TIMESTAMP,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (feed_id) REFERENCES feeds(id) ON DELETE CASCADE,
    UNIQUE(feed_id, guid)
);

-- Reading History
CREATE TABLE IF NOT EXISTS read_articles (
    user_id INTEGER NOT NULL,
    article_id INTEGER NOT NULL,
    read_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, article_id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE
);

-- Index for faster article queries
CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_feed_id ON articles(feed_id);
CREATE INDEX IF NOT EXISTS idx_feed_labels_label ON feed_labels(label);
"""


class Database:
    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path) if db_path else settings.database_path
        self._connection: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Initialize database connection and create tables."""
        # Ensure the directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(self.db_path)
        self._connection.row_factory = aiosqlite.Row
        # Enable foreign keys
        await self._connection.execute("PRAGMA foreign_keys = ON")
        # Create tables
        await self._connection.executescript(SCHEMA)
        await self._connection.commit()

    async def disconnect(self) -> None:
        """Close database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None

    @property
    def connection(self) -> aiosqlite.Connection:
        """Get the current connection."""
        if self._connection is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._connection

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """Context manager for database transactions."""
        try:
            yield self.connection
            await self.connection.commit()
        except Exception:
            await self.connection.rollback()
            raise


# Global database instance
db = Database()


async def get_db() -> Database:
    """Dependency for getting database instance."""
    return db
