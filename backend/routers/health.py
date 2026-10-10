from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import utcnow
from schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get(
    "/health_check/",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
async def health_check(response: Response, db: AsyncSession = Depends(get_db)) -> HealthResponse:
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="unhealthy", database="disconnected", timestamp=utcnow())
    return HealthResponse(status="healthy", database="connected", timestamp=utcnow())
