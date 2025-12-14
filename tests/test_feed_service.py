import pytest
from datetime import datetime

from app.services.feed import (
    parse_feed,
    get_guid,
    get_content,
    parse_datetime,
    FeedParseError,
)


SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <link>https://example.com</link>
    <description>A test feed</description>
    <item>
      <title>First Article</title>
      <link>https://example.com/1</link>
      <guid>article-1</guid>
      <description>Summary of first article</description>
      <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Second Article</title>
      <link>https://example.com/2</link>
      <guid>article-2</guid>
      <description>Summary of second article</description>
      <pubDate>Tue, 02 Jan 2024 12:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

SAMPLE_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Test Atom Feed</title>
  <link href="https://example.com"/>
  <entry>
    <title>Atom Entry</title>
    <link href="https://example.com/atom/1"/>
    <id>urn:uuid:1234</id>
    <updated>2024-01-01T12:00:00Z</updated>
    <summary>Atom summary</summary>
    <content type="html">&lt;p&gt;Full content&lt;/p&gt;</content>
  </entry>
</feed>
"""

INVALID_XML = """This is not valid XML or a feed"""


class TestParseFeed:
    def test_parse_rss(self):
        feed = parse_feed(SAMPLE_RSS)
        assert feed.feed.title == "Test Feed"
        assert len(feed.entries) == 2
        assert feed.entries[0].title == "First Article"

    def test_parse_atom(self):
        feed = parse_feed(SAMPLE_ATOM)
        assert feed.feed.title == "Test Atom Feed"
        assert len(feed.entries) == 1
        assert feed.entries[0].title == "Atom Entry"

    def test_parse_invalid_raises(self):
        with pytest.raises(FeedParseError):
            parse_feed(INVALID_XML)


class TestGetGuid:
    def test_uses_id(self):
        entry = {"id": "unique-id", "link": "https://example.com", "title": "Title"}
        assert get_guid(entry) == "unique-id"

    def test_falls_back_to_link(self):
        entry = {"link": "https://example.com", "title": "Title"}
        assert get_guid(entry) == "https://example.com"

    def test_falls_back_to_title(self):
        entry = {"title": "My Title"}
        assert get_guid(entry) == "My Title"

    def test_generates_hash_as_last_resort(self):
        entry = {}
        guid = get_guid(entry)
        assert guid is not None


class TestGetContent:
    def test_prefers_content(self):
        entry = {
            "content": [{"value": "<p>Full content</p>"}],
            "summary": "Short summary",
        }
        assert get_content(entry) == "<p>Full content</p>"

    def test_falls_back_to_summary(self):
        entry = {"summary": "Just a summary"}
        assert get_content(entry) == "Just a summary"

    def test_returns_none_when_empty(self):
        entry = {}
        assert get_content(entry) is None

    def test_truncates_long_content(self):
        long_content = "x" * 100000
        entry = {"content": [{"value": long_content}]}
        content = get_content(entry)
        assert len(content) == 50000  # Default max length


class TestParseDatetime:
    def test_parses_published(self):
        import time

        parsed_time = time.strptime("2024-01-01 12:00:00", "%Y-%m-%d %H:%M:%S")
        entry = {"published_parsed": parsed_time}
        dt = parse_datetime(entry)
        assert dt is not None
        assert dt.year == 2024
        assert dt.month == 1

    def test_falls_back_to_updated(self):
        import time

        parsed_time = time.strptime("2024-06-15 10:30:00", "%Y-%m-%d %H:%M:%S")
        entry = {"updated_parsed": parsed_time}
        dt = parse_datetime(entry)
        assert dt is not None
        assert dt.month == 6

    def test_returns_none_when_missing(self):
        entry = {}
        assert parse_datetime(entry) is None
