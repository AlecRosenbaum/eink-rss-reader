from datetime import datetime
from time import mktime
from typing import Any

import feedparser
import httpx

from app.config import settings
from app.database import Database


class FeedParseError(Exception):
    """Raised when feed parsing fails."""

    pass


class FeedFetchError(Exception):
    """Raised when feed fetching fails."""

    pass


def parse_datetime(entry: dict[str, Any]) -> datetime | None:
    """Parse datetime from feed entry."""
    for field in ("published_parsed", "updated_parsed", "created_parsed"):
        if field in entry and entry[field]:
            try:
                return datetime.fromtimestamp(mktime(entry[field]))
            except (ValueError, OverflowError):
                continue
    return None


def get_content(entry: dict[str, Any]) -> str | None:
    """Extract content from feed entry."""
    # Try content field first
    if "content" in entry and entry["content"]:
        content = entry["content"][0].get("value", "")
        if content:
            return content[: settings.max_article_content_length]

    # Fall back to summary
    if "summary" in entry and entry["summary"]:
        return entry["summary"][: settings.max_article_content_length]

    return None


def get_guid(entry: dict[str, Any]) -> str:
    """Get unique identifier for feed entry."""
    # Try id first, then link, then title
    if "id" in entry and entry["id"]:
        return entry["id"]
    if "link" in entry and entry["link"]:
        return entry["link"]
    if "title" in entry and entry["title"]:
        return entry["title"]
    return str(hash(str(entry)))


async def fetch_feed_content(url: str) -> str:
    """Fetch feed content from URL."""
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            return response.text
        except httpx.HTTPStatusError as e:
            raise FeedFetchError(f"HTTP error {e.response.status_code}: {url}") from e
        except httpx.RequestError as e:
            raise FeedFetchError(f"Request failed: {e}") from e


def parse_feed(content: str) -> feedparser.FeedParserDict:
    """Parse feed content."""
    feed = feedparser.parse(content)

    if feed.bozo and not feed.entries:
        raise FeedParseError(f"Feed parsing error: {feed.bozo_exception}")

    return feed


async def fetch_and_parse_feed(url: str) -> tuple[str, list[dict[str, Any]]]:
    """Fetch and parse a feed, returning (title, entries)."""
    content = await fetch_feed_content(url)
    feed = parse_feed(content)

    title = feed.feed.get("title", url)
    entries = []

    for entry in feed.entries:
        entries.append(
            {
                "guid": get_guid(entry),
                "title": entry.get("title"),
                "link": entry.get("link"),
                "content": get_content(entry),
                "summary": entry.get("summary", "")[:500] if entry.get("summary") else None,
                "published_at": parse_datetime(entry),
            }
        )

    return title, entries


async def refresh_feed(db: Database, feed_id: int) -> int:
    """Refresh a single feed and return number of new articles."""
    conn = db.connection

    # Get feed URL
    cursor = await conn.execute("SELECT url, title FROM feeds WHERE id = ?", (feed_id,))
    row = await cursor.fetchone()
    if not row:
        raise ValueError(f"Feed {feed_id} not found")

    url = row["url"]
    current_title = row["title"]

    try:
        title, entries = await fetch_and_parse_feed(url)
    except (FeedFetchError, FeedParseError):
        # Update last_fetched even on failure to avoid hammering
        await conn.execute(
            "UPDATE feeds SET last_fetched = ? WHERE id = ?",
            (datetime.now(), feed_id),
        )
        await conn.commit()
        raise

    # Update feed title if changed or not set
    if title and title != current_title:
        await conn.execute("UPDATE feeds SET title = ? WHERE id = ?", (title, feed_id))

    # Insert new articles
    new_count = 0
    for entry in entries:
        try:
            await conn.execute(
                """
                INSERT INTO articles (feed_id, guid, title, link, content, summary, published_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feed_id,
                    entry["guid"],
                    entry["title"],
                    entry["link"],
                    entry["content"],
                    entry["summary"],
                    entry["published_at"],
                ),
            )
            new_count += 1
        except Exception:
            # Duplicate guid, skip
            pass

    # Update last_fetched
    await conn.execute(
        "UPDATE feeds SET last_fetched = ? WHERE id = ?",
        (datetime.now(), feed_id),
    )
    await conn.commit()

    return new_count


async def refresh_all_feeds(db: Database, user_id: int) -> dict[int, int | str]:
    """Refresh all feeds for a user. Returns dict of feed_id -> new_count or error."""
    conn = db.connection

    cursor = await conn.execute("SELECT id FROM feeds WHERE user_id = ?", (user_id,))
    feeds = await cursor.fetchall()

    results: dict[int, int | str] = {}
    for feed in feeds:
        feed_id = feed["id"]
        try:
            count = await refresh_feed(db, feed_id)
            results[feed_id] = count
        except Exception as e:
            results[feed_id] = str(e)

    return results


async def cleanup_old_articles(db: Database) -> int:
    """Delete articles older than retention period. Returns count deleted."""
    conn = db.connection

    cutoff = datetime.now().timestamp() - (settings.article_retention_days * 24 * 60 * 60)
    cutoff_dt = datetime.fromtimestamp(cutoff)

    cursor = await conn.execute(
        "DELETE FROM articles WHERE fetched_at < ?",
        (cutoff_dt,),
    )
    await conn.commit()

    return cursor.rowcount
