import secrets
import string
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import settings


def generate_user_key() -> str:
    """Generate a random alphanumeric key for user identification."""
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(settings.user_key_length))


# ============== User Models ==============


class UserBase(BaseModel):
    key: str = Field(..., min_length=1, max_length=8)

    @field_validator("key")
    @classmethod
    def validate_key(cls, v: str) -> str:
        if not v.isalnum():
            raise ValueError("Key must be alphanumeric")
        return v.lower()


class UserCreate(UserBase):
    pass


class User(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


# ============== Feed Models ==============


class FeedBase(BaseModel):
    url: str = Field(..., min_length=1)


class FeedCreate(FeedBase):
    labels: list[str] = Field(default_factory=list)

    @field_validator("labels")
    @classmethod
    def validate_labels(cls, v: list[str]) -> list[str]:
        # Normalize labels: lowercase, strip whitespace, remove empties
        return [label.strip().lower() for label in v if label.strip()]


class FeedUpdate(BaseModel):
    labels: list[str] = Field(default_factory=list)

    @field_validator("labels")
    @classmethod
    def validate_labels(cls, v: list[str]) -> list[str]:
        return [label.strip().lower() for label in v if label.strip()]


class Feed(FeedBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    title: str | None = None
    labels: list[str] = Field(default_factory=list)
    last_fetched: datetime | None = None
    created_at: datetime
    article_count: int = 0


# ============== Article Models ==============


class ArticleBase(BaseModel):
    title: str | None = None
    link: str | None = None
    summary: str | None = None


class Article(ArticleBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    feed_id: int
    guid: str
    content: str | None = None
    published_at: datetime | None = None
    fetched_at: datetime
    # Joined fields
    feed_title: str | None = None
    is_read: bool = False


class ArticleDetail(Article):
    """Article with full content for single article view."""

    content: str | None = None


# ============== Pagination Models ==============


class PaginatedArticles(BaseModel):
    articles: list[Article]
    page: int
    total_pages: int
    total_count: int
    has_prev: bool
    has_next: bool


class PaginatedFeeds(BaseModel):
    feeds: list[Feed]
    page: int
    total_pages: int
    total_count: int


# ============== Form Models ==============


class AddFeedForm(BaseModel):
    url: str
    labels: str = ""  # Comma-separated labels

    def get_labels(self) -> list[str]:
        """Parse comma-separated labels."""
        if not self.labels:
            return []
        return [label.strip().lower() for label in self.labels.split(",") if label.strip()]


class UpdateLabelsForm(BaseModel):
    labels: str = ""

    def get_labels(self) -> list[str]:
        if not self.labels:
            return []
        return [label.strip().lower() for label in self.labels.split(",") if label.strip()]


class SetUserKeyForm(BaseModel):
    key: str = Field(..., min_length=1, max_length=8)

    @field_validator("key")
    @classmethod
    def validate_key(cls, v: str) -> str:
        if not v.isalnum():
            raise ValueError("Key must be alphanumeric")
        return v.lower()
