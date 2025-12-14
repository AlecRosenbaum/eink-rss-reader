from datetime import datetime

from app.database import Database
from app.services.crud import (
    create_feed,
    create_user,
    delete_feed,
    get_all_user_labels,
    get_article,
    get_articles,
    get_feed,
    get_feed_labels,
    get_or_create_user,
    get_user_by_key,
    get_user_feeds,
    mark_article_read,
    mark_article_unread,
    set_feed_labels,
)


class TestUserOperations:
    async def test_create_user(self, db: Database):
        user = await create_user(db, "testkey1")
        assert user.key == "testkey1"
        assert user.id is not None

    async def test_create_user_generates_key(self, db: Database):
        user = await create_user(db)
        assert len(user.key) == 8
        assert user.key.isalnum()

    async def test_get_user_by_key(self, db: Database):
        created = await create_user(db, "findme01")
        found = await get_user_by_key(db, "findme01")
        assert found is not None
        assert found.id == created.id
        assert found.key == "findme01"

    async def test_get_user_by_key_not_found(self, db: Database):
        found = await get_user_by_key(db, "notexist")
        assert found is None

    async def test_get_user_by_key_case_insensitive(self, db: Database):
        await create_user(db, "testcase")
        found = await get_user_by_key(db, "TESTCASE")
        assert found is not None
        assert found.key == "testcase"

    async def test_get_or_create_user_existing(self, db: Database):
        created = await create_user(db, "existing")
        fetched = await get_or_create_user(db, "existing")
        assert fetched.id == created.id

    async def test_get_or_create_user_new(self, db: Database):
        user = await get_or_create_user(db, "newuser1")
        assert user.key == "newuser1"


class TestFeedOperations:
    async def test_create_feed(self, db: Database, user):
        feed = await create_feed(db, user.id, "https://example.com/rss")
        assert feed.url == "https://example.com/rss"
        assert feed.user_id == user.id
        assert feed.id is not None

    async def test_create_feed_with_labels(self, db: Database, user):
        feed = await create_feed(db, user.id, "https://example.com/rss", ["tech", "news"])
        assert set(feed.labels) == {"tech", "news"}

    async def test_get_feed(self, db: Database, feed):
        fetched = await get_feed(db, feed.id)
        assert fetched is not None
        assert fetched.id == feed.id
        assert fetched.url == feed.url

    async def test_get_feed_not_found(self, db: Database):
        fetched = await get_feed(db, 9999)
        assert fetched is None

    async def test_get_user_feeds(self, db: Database, user):
        await create_feed(db, user.id, "https://example1.com/rss")
        await create_feed(db, user.id, "https://example2.com/rss")
        feeds = await get_user_feeds(db, user.id)
        assert len(feeds) == 2

    async def test_delete_feed(self, db: Database, user):
        feed = await create_feed(db, user.id, "https://todelete.com/rss")
        deleted = await delete_feed(db, feed.id)
        assert deleted is True
        fetched = await get_feed(db, feed.id)
        assert fetched is None

    async def test_delete_feed_not_found(self, db: Database):
        deleted = await delete_feed(db, 9999)
        assert deleted is False

    async def test_set_feed_labels(self, db: Database, feed):
        await set_feed_labels(db, feed.id, ["python", "rust"])
        labels = await get_feed_labels(db, feed.id)
        assert set(labels) == {"python", "rust"}

    async def test_set_feed_labels_replaces(self, db: Database, feed):
        await set_feed_labels(db, feed.id, ["old"])
        await set_feed_labels(db, feed.id, ["new1", "new2"])
        labels = await get_feed_labels(db, feed.id)
        assert set(labels) == {"new1", "new2"}

    async def test_get_all_user_labels(self, db: Database, user):
        await create_feed(db, user.id, "https://f1.com/rss", ["tech", "news"])
        await create_feed(db, user.id, "https://f2.com/rss", ["tech", "python"])
        labels = await get_all_user_labels(db, user.id)
        assert set(labels) == {"tech", "news", "python"}


class TestArticleOperations:
    async def test_get_articles_empty(self, db: Database, user):
        result = await get_articles(db, user.id)
        assert result.articles == []
        assert result.total_count == 0
        assert result.page == 1

    async def test_get_articles_with_data(self, db: Database, user, feed):
        # Insert test articles directly
        await db.connection.execute(
            """
            INSERT INTO articles (feed_id, guid, title, link, published_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (feed.id, "guid1", "Article 1", "https://example.com/1", datetime.now()),
        )
        await db.connection.execute(
            """
            INSERT INTO articles (feed_id, guid, title, link, published_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (feed.id, "guid2", "Article 2", "https://example.com/2", datetime.now()),
        )
        await db.connection.commit()

        result = await get_articles(db, user.id)
        assert len(result.articles) == 2
        assert result.total_count == 2

    async def test_get_articles_pagination(self, db: Database, user, feed):
        # Insert 10 articles
        for i in range(10):
            await db.connection.execute(
                """
                INSERT INTO articles (feed_id, guid, title, published_at)
                VALUES (?, ?, ?, ?)
                """,
                (feed.id, f"guid{i}", f"Article {i}", datetime.now()),
            )
        await db.connection.commit()

        # Page 1 (default 5 per page)
        page1 = await get_articles(db, user.id, page=1)
        assert len(page1.articles) == 5
        assert page1.total_pages == 2
        assert page1.has_next is True
        assert page1.has_prev is False

        # Page 2
        page2 = await get_articles(db, user.id, page=2)
        assert len(page2.articles) == 5
        assert page2.has_next is False
        assert page2.has_prev is True

    async def test_get_articles_hide_read(self, db: Database, user, feed):
        # Insert articles
        cursor = await db.connection.execute(
            """
            INSERT INTO articles (feed_id, guid, title)
            VALUES (?, ?, ?)
            """,
            (feed.id, "guid1", "Article 1"),
        )
        article1_id = cursor.lastrowid
        await db.connection.execute(
            """
            INSERT INTO articles (feed_id, guid, title)
            VALUES (?, ?, ?)
            """,
            (feed.id, "guid2", "Article 2"),
        )
        await db.connection.commit()

        # Mark one as read
        await mark_article_read(db, user.id, article1_id)

        # Get all
        all_articles = await get_articles(db, user.id, hide_read=False)
        assert all_articles.total_count == 2

        # Get unread only
        unread = await get_articles(db, user.id, hide_read=True)
        assert unread.total_count == 1

    async def test_get_articles_filter_by_label(self, db: Database, user):
        # Create feeds with different labels
        feed1 = await create_feed(db, user.id, "https://f1.com/rss", ["tech"])
        feed2 = await create_feed(db, user.id, "https://f2.com/rss", ["news"])

        # Add articles to each
        await db.connection.execute(
            "INSERT INTO articles (feed_id, guid, title) VALUES (?, ?, ?)",
            (feed1.id, "g1", "Tech Article"),
        )
        await db.connection.execute(
            "INSERT INTO articles (feed_id, guid, title) VALUES (?, ?, ?)",
            (feed2.id, "g2", "News Article"),
        )
        await db.connection.commit()

        # Filter by label
        tech_articles = await get_articles(db, user.id, label="tech")
        assert tech_articles.total_count == 1
        assert tech_articles.articles[0].title == "Tech Article"

    async def test_get_article(self, db: Database, user, feed):
        cursor = await db.connection.execute(
            """
            INSERT INTO articles (feed_id, guid, title, content)
            VALUES (?, ?, ?, ?)
            """,
            (feed.id, "guid1", "Test Article", "<p>Content here</p>"),
        )
        article_id = cursor.lastrowid
        await db.connection.commit()

        article = await get_article(db, article_id, user.id)
        assert article is not None
        assert article.title == "Test Article"
        assert article.content == "<p>Content here</p>"

    async def test_get_article_not_found(self, db: Database, user):
        article = await get_article(db, 9999, user.id)
        assert article is None

    async def test_mark_article_read_unread(self, db: Database, user, feed):
        cursor = await db.connection.execute(
            "INSERT INTO articles (feed_id, guid, title) VALUES (?, ?, ?)",
            (feed.id, "guid1", "Test"),
        )
        article_id = cursor.lastrowid
        await db.connection.commit()

        # Initially unread
        article = await get_article(db, article_id, user.id)
        assert article.is_read is False

        # Mark as read
        await mark_article_read(db, user.id, article_id)
        article = await get_article(db, article_id, user.id)
        assert article.is_read is True

        # Mark as unread
        await mark_article_unread(db, user.id, article_id)
        article = await get_article(db, article_id, user.id)
        assert article.is_read is False
