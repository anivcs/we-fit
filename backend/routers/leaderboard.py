from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Score, User, utcnow
from schemas import LeaderboardEntry, LeaderboardResponse, Timeframe

router = APIRouter(tags=["leaderboard"])

TIMEFRAME_WINDOWS = {
    Timeframe.DAILY: timedelta(days=1),
    Timeframe.WEEKLY: timedelta(weeks=1),
}


@router.get("/leaderboard/", response_model=LeaderboardResponse)
async def get_leaderboard(
    limit: int = Query(10, ge=1, le=100, description="Number of results to return."),
    timeframe: Timeframe = Query(Timeframe.ALL_TIME),
    db: AsyncSession = Depends(get_db),
) -> LeaderboardResponse:
    best_score = func.max(Score.score).label("score")
    query = (
        select(User.user_id, User.username, best_score)
        .join(Score, Score.user_id == User.user_id)
        .group_by(User.user_id, User.username)
        .order_by(best_score.desc(), User.user_id)
        .limit(limit)
    )
    if timeframe in TIMEFRAME_WINDOWS:
        query = query.where(Score.created_at >= utcnow() - TIMEFRAME_WINDOWS[timeframe])

    rows = (await db.execute(query)).all()
    return LeaderboardResponse(
        timeframe=timeframe,
        rankings=[
            LeaderboardEntry(rank=i, user_id=row.user_id, username=row.username, score=row.score)
            for i, row in enumerate(rows, start=1)
        ],
    )
