from fastapi import APIRouter

router = APIRouter(tags=["api"])


@router.get("/status")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}
