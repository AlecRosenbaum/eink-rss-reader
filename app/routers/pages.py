from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.database import Database, get_db
from app.services import crud
from app.services.feed import refresh_feed, refresh_all_feeds, FeedFetchError, FeedParseError
from app.models import generate_user_key

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def get_user_key(request: Request) -> str | None:
    """Get user key from cookie."""
    return request.cookies.get("user_key")


def relative_time(dt: datetime | None) -> str:
    """Convert datetime to relative time string."""
    if dt is None:
        return "unknown"

    now = datetime.now()
    diff = now - dt

    seconds = diff.total_seconds()
    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        return f"{minutes}m ago"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f"{hours}h ago"
    elif seconds < 604800:
        days = int(seconds / 86400)
        return f"{days}d ago"
    else:
        return dt.strftime("%b %d")


# Add filter to templates
templates.env.filters["relative_time"] = relative_time


# ============== Home Page ==============


@router.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    db: Annotated[Database, Depends(get_db)],
    page: int = Query(1, ge=1),
    label: str | None = Query(None),
    hide_read: bool = Query(False),
):
    """Home page with article list."""
    user_key = get_user_key(request)
    if not user_key:
        return RedirectResponse(url="/settings", status_code=302)

    user = await crud.get_user_by_key(db, user_key)
    if not user:
        return RedirectResponse(url="/settings", status_code=302)

    # Get articles
    articles = await crud.get_articles(db, user.id, page=page, hide_read=hide_read, label=label)

    # Get all labels for filter dropdown
    all_labels = await crud.get_all_user_labels(db, user.id)

    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "articles": articles,
            "labels": all_labels,
            "current_label": label,
            "hide_read": hide_read,
            "page": page,
        },
    )


# ============== Article Page ==============


@router.get("/article/{article_id}", response_class=HTMLResponse)
async def article_detail(
    request: Request,
    article_id: int,
    db: Annotated[Database, Depends(get_db)],
):
    """Single article view."""
    user_key = get_user_key(request)
    if not user_key:
        return RedirectResponse(url="/settings", status_code=302)

    user = await crud.get_user_by_key(db, user_key)
    if not user:
        return RedirectResponse(url="/settings", status_code=302)

    article = await crud.get_article(db, article_id, user.id)
    if not article:
        return templates.TemplateResponse(
            request,
            "error.html",
            {"message": "Article not found"},
            status_code=404,
        )

    # Mark as read
    await crud.mark_article_read(db, user.id, article_id)

    return templates.TemplateResponse(
        request,
        "article.html",
        {"article": article},
    )


@router.post("/article/{article_id}/read")
async def mark_read(
    article_id: int,
    db: Annotated[Database, Depends(get_db)],
    request: Request,
):
    """Mark article as read."""
    user_key = get_user_key(request)
    if not user_key:
        return RedirectResponse(url="/settings", status_code=302)

    user = await crud.get_user_by_key(db, user_key)
    if user:
        await crud.mark_article_read(db, user.id, article_id)

    referer = request.headers.get("referer", "/")
    return RedirectResponse(url=referer, status_code=302)


@router.post("/article/{article_id}/unread")
async def mark_unread(
    article_id: int,
    db: Annotated[Database, Depends(get_db)],
    request: Request,
):
    """Mark article as unread."""
    user_key = get_user_key(request)
    if not user_key:
        return RedirectResponse(url="/settings", status_code=302)

    user = await crud.get_user_by_key(db, user_key)
    if user:
        await crud.mark_article_unread(db, user.id, article_id)

    referer = request.headers.get("referer", "/")
    return RedirectResponse(url=referer, status_code=302)


# ============== Feeds Page ==============


@router.get("/feeds", response_class=HTMLResponse)
async def feeds_page(
    request: Request,
    db: Annotated[Database, Depends(get_db)],
    message: str | None = Query(None),
    error: str | None = Query(None),
):
    """Feeds management page."""
    user_key = get_user_key(request)
    if not user_key:
        return RedirectResponse(url="/settings", status_code=302)

    user = await crud.get_user_by_key(db, user_key)
    if not user:
        return RedirectResponse(url="/settings", status_code=302)

    feeds = await crud.get_user_feeds(db, user.id)

    return templates.TemplateResponse(
        request,
        "feeds.html",
        {
            "feeds": feeds,
            "message": message,
            "error": error,
        },
    )


@router.post("/feeds/add")
async def add_feed(
    request: Request,
    db: Annotated[Database, Depends(get_db)],
    url: Annotated[str, Form()],
    labels: Annotated[str, Form()] = "",
):
    """Add a new feed."""
    user_key = get_user_key(request)
    if not user_key:
        return RedirectResponse(url="/settings", status_code=302)

    user = await crud.get_user_by_key(db, user_key)
    if not user:
        return RedirectResponse(url="/settings", status_code=302)

    # Parse labels
    label_list = [l.strip().lower() for l in labels.split(",") if l.strip()]

    try:
        feed = await crud.create_feed(db, user.id, url, label_list)
        # Try to refresh it immediately
        try:
            await refresh_feed(db, feed.id)
            return RedirectResponse(url="/feeds?message=Feed+added+successfully", status_code=302)
        except (FeedFetchError, FeedParseError) as e:
            return RedirectResponse(url=f"/feeds?error=Feed+added+but+refresh+failed:+{str(e)[:50]}", status_code=302)
    except Exception as e:
        return RedirectResponse(url=f"/feeds?error=Failed+to+add+feed", status_code=302)


@router.post("/feeds/{feed_id}/delete")
async def delete_feed(
    feed_id: int,
    request: Request,
    db: Annotated[Database, Depends(get_db)],
):
    """Delete a feed."""
    user_key = get_user_key(request)
    if not user_key:
        return RedirectResponse(url="/settings", status_code=302)

    user = await crud.get_user_by_key(db, user_key)
    if not user:
        return RedirectResponse(url="/settings", status_code=302)

    # Verify feed belongs to user
    feed = await crud.get_feed(db, feed_id)
    if feed and feed.user_id == user.id:
        await crud.delete_feed(db, feed_id)
        return RedirectResponse(url="/feeds?message=Feed+deleted", status_code=302)

    return RedirectResponse(url="/feeds?error=Feed+not+found", status_code=302)


@router.post("/feeds/{feed_id}/refresh")
async def refresh_single_feed(
    feed_id: int,
    request: Request,
    db: Annotated[Database, Depends(get_db)],
):
    """Refresh a single feed."""
    user_key = get_user_key(request)
    if not user_key:
        return RedirectResponse(url="/settings", status_code=302)

    user = await crud.get_user_by_key(db, user_key)
    if not user:
        return RedirectResponse(url="/settings", status_code=302)

    feed = await crud.get_feed(db, feed_id)
    if not feed or feed.user_id != user.id:
        return RedirectResponse(url="/feeds?error=Feed+not+found", status_code=302)

    try:
        count = await refresh_feed(db, feed_id)
        return RedirectResponse(url=f"/feeds?message=Refreshed,+{count}+new+articles", status_code=302)
    except (FeedFetchError, FeedParseError) as e:
        return RedirectResponse(url=f"/feeds?error=Refresh+failed", status_code=302)


@router.post("/feeds/refresh")
async def refresh_all(
    request: Request,
    db: Annotated[Database, Depends(get_db)],
):
    """Refresh all feeds."""
    user_key = get_user_key(request)
    if not user_key:
        return RedirectResponse(url="/settings", status_code=302)

    user = await crud.get_user_by_key(db, user_key)
    if not user:
        return RedirectResponse(url="/settings", status_code=302)

    results = await refresh_all_feeds(db, user.id)
    total_new = sum(v for v in results.values() if isinstance(v, int))

    referer = request.headers.get("referer", "/")
    # Add message to referer URL
    sep = "&" if "?" in referer else "?"
    return RedirectResponse(url=f"{referer}{sep}message=Refreshed,+{total_new}+new+articles", status_code=302)


@router.post("/feeds/{feed_id}/labels")
async def update_labels(
    feed_id: int,
    request: Request,
    db: Annotated[Database, Depends(get_db)],
    labels: Annotated[str, Form()] = "",
):
    """Update feed labels."""
    user_key = get_user_key(request)
    if not user_key:
        return RedirectResponse(url="/settings", status_code=302)

    user = await crud.get_user_by_key(db, user_key)
    if not user:
        return RedirectResponse(url="/settings", status_code=302)

    feed = await crud.get_feed(db, feed_id)
    if not feed or feed.user_id != user.id:
        return RedirectResponse(url="/feeds?error=Feed+not+found", status_code=302)

    label_list = [l.strip().lower() for l in labels.split(",") if l.strip()]
    await crud.set_feed_labels(db, feed_id, label_list)

    return RedirectResponse(url="/feeds?message=Labels+updated", status_code=302)


# ============== Settings Page ==============


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    db: Annotated[Database, Depends(get_db)],
):
    """Settings page for user key management."""
    user_key = get_user_key(request)
    user = None
    if user_key:
        user = await crud.get_user_by_key(db, user_key)

    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "user": user,
            "user_key": user_key,
        },
    )


@router.post("/user/key")
async def set_user_key(
    request: Request,
    db: Annotated[Database, Depends(get_db)],
    key: Annotated[str, Form()],
):
    """Set or change user key."""
    key = key.strip().lower()

    if not key:
        return RedirectResponse(url="/settings?error=Key+required", status_code=302)

    if len(key) > 8:
        return RedirectResponse(url="/settings?error=Key+too+long", status_code=302)

    if not key.isalnum():
        return RedirectResponse(url="/settings?error=Key+must+be+alphanumeric", status_code=302)

    # Get or create user
    await crud.get_or_create_user(db, key)

    # Set cookie and redirect
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key="user_key",
        value=key,
        max_age=365 * 24 * 60 * 60,  # 1 year
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/user/generate")
async def generate_key(
    request: Request,
    db: Annotated[Database, Depends(get_db)],
):
    """Generate a new random key."""
    key = generate_user_key()
    await crud.create_user(db, key)

    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key="user_key",
        value=key,
        max_age=365 * 24 * 60 * 60,
        httponly=True,
        samesite="lax",
    )
    return response
