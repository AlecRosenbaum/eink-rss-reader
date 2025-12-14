"""Background scheduler for periodic feed refresh."""

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.database import db
from app.services.feed import refresh_all_feeds, cleanup_old_articles

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def refresh_all_users_feeds():
    """Refresh feeds for all users."""
    try:
        conn = db.connection
        cursor = await conn.execute("SELECT id FROM users")
        users = await cursor.fetchall()

        total_new = 0
        for user in users:
            try:
                results = await refresh_all_feeds(db, user["id"])
                new_count = sum(v for v in results.values() if isinstance(v, int))
                total_new += new_count
            except Exception as e:
                logger.error(f"Error refreshing feeds for user {user['id']}: {e}")

        logger.info(f"Scheduled refresh complete: {total_new} new articles across {len(users)} users")
    except Exception as e:
        logger.error(f"Error in scheduled refresh: {e}")


async def cleanup_articles():
    """Clean up old articles."""
    try:
        deleted = await cleanup_old_articles(db)
        if deleted > 0:
            logger.info(f"Cleaned up {deleted} old articles")
    except Exception as e:
        logger.error(f"Error cleaning up articles: {e}")


def start_scheduler():
    """Start the background scheduler."""
    # Add refresh job
    scheduler.add_job(
        refresh_all_users_feeds,
        trigger=IntervalTrigger(seconds=settings.refresh_interval_seconds),
        id="refresh_feeds",
        name="Refresh all feeds",
        replace_existing=True,
    )

    # Add daily cleanup job
    scheduler.add_job(
        cleanup_articles,
        trigger=IntervalTrigger(hours=24),
        id="cleanup_articles",
        name="Clean up old articles",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(f"Scheduler started. Feeds will refresh every {settings.refresh_interval_seconds} seconds")


def stop_scheduler():
    """Stop the background scheduler."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped")
