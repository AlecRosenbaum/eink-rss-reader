import pytest
from httpx import AsyncClient, ASGITransport
import tempfile
from pathlib import Path

from app.main import app
from app.database import db, Database
from app.services.crud import create_user, create_feed


@pytest.fixture
async def test_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    # Replace the global db with our test db
    test_database = Database(db_path)
    await test_database.connect()

    # Monkey-patch the global db
    original_connection = db._connection
    original_path = db.db_path
    db._connection = test_database._connection
    db.db_path = test_database.db_path

    yield test_database

    # Restore original
    db._connection = original_connection
    db.db_path = original_path

    await test_database.disconnect()
    db_path.unlink(missing_ok=True)


@pytest.fixture
async def client(test_db):
    """Create a test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def user_key(test_db):
    """Create a test user and return their key."""
    user = await create_user(test_db, "testuser")
    return user.key


class TestHealthCheck:
    async def test_status_endpoint(self, client: AsyncClient):
        response = await client.get("/api/status")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestSettingsPage:
    async def test_settings_page_no_user(self, client: AsyncClient):
        response = await client.get("/settings")
        assert response.status_code == 200
        assert b"Enter key" in response.content or b"Enter a key" in response.content

    async def test_settings_page_with_user(self, client: AsyncClient, user_key: str):
        response = await client.get("/settings", cookies={"user_key": user_key})
        assert response.status_code == 200
        assert user_key.encode() in response.content

    async def test_set_user_key(self, client: AsyncClient):
        response = await client.post(
            "/user/key",
            data={"key": "newkey01"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "user_key" in response.cookies

    async def test_set_user_key_invalid(self, client: AsyncClient):
        response = await client.post(
            "/user/key",
            data={"key": "invalid!@#"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "error" in response.headers.get("location", "")

    async def test_generate_key(self, client: AsyncClient):
        response = await client.post("/user/generate", follow_redirects=False)
        assert response.status_code == 302
        assert "user_key" in response.cookies


class TestHomePage:
    async def test_home_redirects_without_user(self, client: AsyncClient):
        response = await client.get("/", follow_redirects=False)
        assert response.status_code == 302
        assert "/settings" in response.headers.get("location", "")

    async def test_home_with_user(self, client: AsyncClient, user_key: str):
        response = await client.get("/", cookies={"user_key": user_key})
        assert response.status_code == 200
        assert b"Reader" in response.content

    async def test_home_empty_state(self, client: AsyncClient, user_key: str):
        response = await client.get("/", cookies={"user_key": user_key})
        assert response.status_code == 200
        assert b"No articles" in response.content


class TestFeedsPage:
    async def test_feeds_page_redirects_without_user(self, client: AsyncClient):
        response = await client.get("/feeds", follow_redirects=False)
        assert response.status_code == 302
        assert "/settings" in response.headers.get("location", "")

    async def test_feeds_page_with_user(self, client: AsyncClient, user_key: str):
        response = await client.get("/feeds", cookies={"user_key": user_key})
        assert response.status_code == 200
        assert b"Manage Feeds" in response.content

    async def test_feeds_page_empty_state(self, client: AsyncClient, user_key: str):
        response = await client.get("/feeds", cookies={"user_key": user_key})
        assert response.status_code == 200
        assert b"No feeds yet" in response.content

    async def test_add_feed_form_present(self, client: AsyncClient, user_key: str):
        response = await client.get("/feeds", cookies={"user_key": user_key})
        assert response.status_code == 200
        assert b"Add Feed" in response.content
        assert b'name="url"' in response.content


class TestArticlePage:
    async def test_article_not_found(self, client: AsyncClient, user_key: str):
        response = await client.get("/article/9999", cookies={"user_key": user_key})
        assert response.status_code == 404
        assert b"not found" in response.content.lower()


class TestRefreshEndpoints:
    async def test_refresh_all_redirects(self, client: AsyncClient, user_key: str):
        response = await client.post(
            "/feeds/refresh",
            cookies={"user_key": user_key},
            follow_redirects=False,
        )
        assert response.status_code == 302


class TestPagination:
    async def test_pagination_params(self, client: AsyncClient, user_key: str):
        # Test that pagination params are accepted
        response = await client.get(
            "/?page=1&hide_read=true&label=test",
            cookies={"user_key": user_key},
        )
        assert response.status_code == 200
