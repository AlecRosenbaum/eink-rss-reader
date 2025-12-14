from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Data directory - can be set via DATA_DIR environment variable
    data_dir: Path = Path(__file__).parent.parent / "data"

    @property
    def database_path(self) -> Path:
        """Full path to the database file."""
        return self.data_dir / "eink_reader.db"

    # App settings
    app_name: str = "E-Ink Reader"
    debug: bool = False

    # Pagination
    articles_per_page: int = 5

    # Data retention (days)
    article_retention_days: int = 90

    # Feed refresh interval (seconds)
    refresh_interval_seconds: int = 3600  # 1 hour

    # Article content limits
    max_article_content_length: int = 50000  # 50KB

    # User key settings
    user_key_length: int = 8


settings = Settings()
