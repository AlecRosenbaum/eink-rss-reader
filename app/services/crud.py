from datetime import datetime
from math import ceil

from app.config import settings
from app.database import Database
from app.models import (
    Article,
    ArticleDetail,
    Feed,
    PaginatedArticles,
    User,
    generate_user_key,
)

# ============== User Operations ==============


async def get_user_by_key(db: Database, key: str) -> User | None:
    """Get user by their key."""
    cursor = await db.connection.execute(
        "SELECT id, key, created_at FROM users WHERE key = ?",
        (key.lower(),),
    )
    row = await cursor.fetchone()
    if row:
        return User(id=row["id"], key=row["key"], created_at=row["created_at"])
    return None


async def create_user(db: Database, key: str | None = None) -> User:
    """Create a new user with optional key."""
    if key is None:
        key = generate_user_key()
    key = key.lower()

    cursor = await db.connection.execute(
        "INSERT INTO users (key) VALUES (?)",
        (key,),
    )
    await db.connection.commit()

    return User(id=cursor.lastrowid, key=key, created_at=datetime.now())


async def get_or_create_user(db: Database, key: str) -> User:
    """Get existing user or create new one."""
    user = await get_user_by_key(db, key)
    if user:
        return user
    return await create_user(db, key)


# ============== Feed Operations ==============


async def get_feed_labels(db: Database, feed_id: int) -> list[str]:
    """Get labels for a feed."""
    cursor = await db.connection.execute(
        "SELECT label FROM feed_labels WHERE feed_id = ? ORDER BY label",
        (feed_id,),
    )
    rows = await cursor.fetchall()
    return [row["label"] for row in rows]


async def set_feed_labels(db: Database, feed_id: int, labels: list[str]) -> None:
    """Set labels for a feed (replaces existing)."""
    # Delete existing labels
    await db.connection.execute(
        "DELETE FROM feed_labels WHERE feed_id = ?",
        (feed_id,),
    )
    # Insert new labels
    for label in labels:
        await db.connection.execute(
            "INSERT INTO feed_labels (feed_id, label) VALUES (?, ?)",
            (feed_id, label.lower()),
        )
    await db.connection.commit()


async def get_user_feeds(db: Database, user_id: int) -> list[Feed]:
    """Get all feeds for a user with article counts."""
    cursor = await db.connection.execute(
        """
        SELECT
            f.id, f.user_id, f.url, f.title, f.last_fetched, f.created_at,
            COUNT(a.id) as article_count
        FROM feeds f
        LEFT JOIN articles a ON f.id = a.feed_id
        WHERE f.user_id = ?
        GROUP BY f.id
        ORDER BY f.title, f.url
        """,
        (user_id,),
    )
    rows = await cursor.fetchall()

    feeds = []
    for row in rows:
        labels = await get_feed_labels(db, row["id"])
        feeds.append(
            Feed(
                id=row["id"],
                user_id=row["user_id"],
                url=row["url"],
                title=row["title"],
                labels=labels,
                last_fetched=row["last_fetched"],
                created_at=row["created_at"],
                article_count=row["article_count"],
            )
        )
    return feeds


async def get_feed(db: Database, feed_id: int) -> Feed | None:
    """Get a single feed by ID."""
    cursor = await db.connection.execute(
        """
        SELECT
            f.id, f.user_id, f.url, f.title, f.last_fetched, f.created_at,
            COUNT(a.id) as article_count
        FROM feeds f
        LEFT JOIN articles a ON f.id = a.feed_id
        WHERE f.id = ?
        GROUP BY f.id
        """,
        (feed_id,),
    )
    row = await cursor.fetchone()
    if not row:
        return None

    labels = await get_feed_labels(db, row["id"])
    return Feed(
        id=row["id"],
        user_id=row["user_id"],
        url=row["url"],
        title=row["title"],
        labels=labels,
        last_fetched=row["last_fetched"],
        created_at=row["created_at"],
        article_count=row["article_count"],
    )


async def create_feed(db: Database, user_id: int, url: str, labels: list[str] | None = None) -> Feed:
    """Create a new feed."""
    cursor = await db.connection.execute(
        "INSERT INTO feeds (user_id, url) VALUES (?, ?)",
        (user_id, url),
    )
    feed_id = cursor.lastrowid
    await db.connection.commit()

    if labels:
        await set_feed_labels(db, feed_id, labels)

    return await get_feed(db, feed_id)  # type: ignore


async def delete_feed(db: Database, feed_id: int) -> bool:
    """Delete a feed and its articles."""
    cursor = await db.connection.execute(
        "DELETE FROM feeds WHERE id = ?",
        (feed_id,),
    )
    await db.connection.commit()
    return cursor.rowcount > 0


async def get_all_user_labels(db: Database, user_id: int) -> list[str]:
    """Get all unique labels used by a user's feeds."""
    cursor = await db.connection.execute(
        """
        SELECT DISTINCT fl.label
        FROM feed_labels fl
        JOIN feeds f ON fl.feed_id = f.id
        WHERE f.user_id = ?
        ORDER BY fl.label
        """,
        (user_id,),
    )
    rows = await cursor.fetchall()
    return [row["label"] for row in rows]


# ============== Article Operations ==============


async def get_articles(
    db: Database,
    user_id: int,
    page: int = 1,
    hide_read: bool = False,
    label: str | None = None,
) -> PaginatedArticles:
    """Get paginated articles for a user."""
    per_page = settings.articles_per_page
    offset = (page - 1) * per_page

    # Build query with optional filters
    where_clauses = ["f.user_id = ?"]
    params: list = [user_id]

    if hide_read:
        where_clauses.append("ra.article_id IS NULL")

    if label:
        where_clauses.append("fl.label = ?")
        params.append(label.lower())

    where_sql = " AND ".join(where_clauses)

    # Get total count
    count_sql = f"""
        SELECT COUNT(DISTINCT a.id) as count
        FROM articles a
        JOIN feeds f ON a.feed_id = f.id
        LEFT JOIN read_articles ra ON a.id = ra.article_id AND ra.user_id = ?
        {"LEFT JOIN feed_labels fl ON f.id = fl.feed_id" if label else ""}
        WHERE {where_sql}
    """
    count_params = [user_id] + params
    cursor = await db.connection.execute(count_sql, count_params)
    row = await cursor.fetchone()
    total_count = row["count"]
    total_pages = max(1, ceil(total_count / per_page))

    # Get articles
    articles_sql = f"""
        SELECT DISTINCT
            a.id, a.feed_id, a.guid, a.title, a.link, a.summary,
            a.published_at, a.fetched_at,
            f.title as feed_title,
            CASE WHEN ra.article_id IS NOT NULL THEN 1 ELSE 0 END as is_read
        FROM articles a
        JOIN feeds f ON a.feed_id = f.id
        LEFT JOIN read_articles ra ON a.id = ra.article_id AND ra.user_id = ?
        {"LEFT JOIN feed_labels fl ON f.id = fl.feed_id" if label else ""}
        WHERE {where_sql}
        ORDER BY a.published_at DESC NULLS LAST, a.fetched_at DESC
        LIMIT ? OFFSET ?
    """
    articles_params = [user_id] + params + [per_page, offset]
    cursor = await db.connection.execute(articles_sql, articles_params)
    rows = await cursor.fetchall()

    articles = [
        Article(
            id=row["id"],
            feed_id=row["feed_id"],
            guid=row["guid"],
            title=row["title"],
            link=row["link"],
            summary=row["summary"],
            published_at=row["published_at"],
            fetched_at=row["fetched_at"],
            feed_title=row["feed_title"],
            is_read=bool(row["is_read"]),
        )
        for row in rows
    ]

    return PaginatedArticles(
        articles=articles,
        page=page,
        total_pages=total_pages,
        total_count=total_count,
        has_prev=page > 1,
        has_next=page < total_pages,
    )


async def get_article(db: Database, article_id: int, user_id: int) -> ArticleDetail | None:
    """Get a single article with full content."""
    cursor = await db.connection.execute(
        """
        SELECT
            a.id, a.feed_id, a.guid, a.title, a.link, a.content, a.summary,
            a.published_at, a.fetched_at,
            f.title as feed_title,
            CASE WHEN ra.article_id IS NOT NULL THEN 1 ELSE 0 END as is_read
        FROM articles a
        JOIN feeds f ON a.feed_id = f.id
        LEFT JOIN read_articles ra ON a.id = ra.article_id AND ra.user_id = ?
        WHERE a.id = ?
        """,
        (user_id, article_id),
    )
    row = await cursor.fetchone()
    if not row:
        return None

    return ArticleDetail(
        id=row["id"],
        feed_id=row["feed_id"],
        guid=row["guid"],
        title=row["title"],
        link=row["link"],
        content=row["content"],
        summary=row["summary"],
        published_at=row["published_at"],
        fetched_at=row["fetched_at"],
        feed_title=row["feed_title"],
        is_read=bool(row["is_read"]),
    )


async def mark_article_read(db: Database, user_id: int, article_id: int) -> None:
    """Mark an article as read."""
    await db.connection.execute(
        """
        INSERT OR IGNORE INTO read_articles (user_id, article_id)
        VALUES (?, ?)
        """,
        (user_id, article_id),
    )
    await db.connection.commit()


async def mark_article_unread(db: Database, user_id: int, article_id: int) -> None:
    """Mark an article as unread."""
    await db.connection.execute(
        "DELETE FROM read_articles WHERE user_id = ? AND article_id = ?",
        (user_id, article_id),
    )
    await db.connection.commit()
