from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import User, utcnow
from schemas import (
    Identifier,
    UserStatsResponse,
    UserStatsUpdateRequest,
    UserStatsUpdateResponse,
)
from services import calculate_xp, get_or_create_user, record_game

router = APIRouter(prefix="/user", tags=["user"])


@router.get("/stats/", response_model=UserStatsResponse)
async def get_user_stats(
    user_id: Identifier = Query(..., description="The unique identifier of the player."),
    db: AsyncSession = Depends(get_db),
) -> UserStatsResponse:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"User '{user_id}' not found")
    return UserStatsResponse(
        user_id=user.user_id,
        total_games_played=user.total_games_played,
        highest_score=user.highest_score,
        total_distance=user.total_distance,
        total_coins=user.total_coins,
    )


@router.post("/stats/", response_model=UserStatsUpdateResponse)
async def update_user_stats(
    payload: UserStatsUpdateRequest, db: AsyncSession = Depends(get_db)
) -> UserStatsUpdateResponse:
    now = utcnow()
    user = await get_or_create_user(db, payload.user_id, payload.username, now)
    record_game(
        db,
        user,
        score=payload.game_score,
        coins=payload.coins_collected,
        distance=payload.distance_traveled,
        xp=calculate_xp(payload.game_score),
        now=now,
    )
    await db.commit()
    return UserStatsUpdateResponse(user_id=user.user_id, status="updated", updated_at=now)
