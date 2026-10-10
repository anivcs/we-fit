from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from .models import Score, User

XP_PER_SCORE_POINT = 0.01


def calculate_xp(final_score: int) -> int:
    return int(final_score * XP_PER_SCORE_POINT)


async def get_or_create_user(
    db: AsyncSession, user_id: str, username: str | None, now: datetime
) -> User:
    user = await db.get(User, user_id)
    if user is None:
        user = User(
            user_id=user_id,
            username=username or user_id,
            total_games_played=0,
            highest_score=0,
            total_distance=0,
            total_coins=0,
            total_xp=0,
            created_at=now,
            updated_at=now,
        )
        db.add(user)
    elif username:
        user.username = username
    return user


def record_game(
    db: AsyncSession,
    user: User,
    *,
    score: int,
    coins: int,
    distance: int,
    xp: int,
    now: datetime,
    session_id: str | None = None,
) -> bool:
    """Apply one finished game to a user's lifetime stats. Returns True if it set a new personal best."""
    high_score_updated = score > user.highest_score
    user.total_games_played += 1
    user.total_coins += coins
    user.total_distance += distance
    user.total_xp += xp
    user.highest_score = max(user.highest_score, score)
    user.updated_at = now
    db.add(Score(user_id=user.user_id, session_id=session_id, score=score, created_at=now))
    return high_score_updated
