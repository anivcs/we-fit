import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import GameSession, MovementEvent, utcnow
from schemas import (
    EarnedRewards,
    GameEndRequest,
    GameEndResponse,
    GameStartRequest,
    GameStartResponse,
    GameSyncRequest,
    GameSyncResponse,
)
from services import calculate_xp, get_or_create_user, record_game

router = APIRouter(prefix="/game", tags=["game"])

STATUS_STARTED = "started"
STATUS_ENDED = "ended"
MAX_SEED = 2**31 - 1


async def get_active_session(db: AsyncSession, session_id: str) -> GameSession:
    session = await db.get(GameSession, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Session '{session_id}' not found")
    if session.status != STATUS_STARTED:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Session '{session_id}' has already ended")
    return session


@router.post("/start/", status_code=status.HTTP_201_CREATED, response_model=GameStartResponse)
async def start_game(
    payload: GameStartRequest, db: AsyncSession = Depends(get_db)
) -> GameStartResponse:
    if await db.get(GameSession, payload.session_id) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Session '{payload.session_id}' already exists"
        )

    now = utcnow()
    if payload.user_id:
        await get_or_create_user(db, payload.user_id, payload.username, now)

    session = GameSession(
        session_id=payload.session_id,
        user_id=payload.user_id,
        status=STATUS_STARTED,
        seed=secrets.randbelow(MAX_SEED),
        started_at=now,
    )
    db.add(session)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Session '{payload.session_id}' already exists"
        )

    return GameStartResponse(
        session_id=session.session_id,
        status=STATUS_STARTED,
        seed=session.seed,
        started_at=now,
    )


@router.post("/sync/", response_model=GameSyncResponse)
async def sync_game(payload: GameSyncRequest, db: AsyncSession = Depends(get_db)) -> GameSyncResponse:
    await get_active_session(db, payload.session_id)

    now = utcnow()
    db.add(
        MovementEvent(
            session_id=payload.session_id,
            movement_type=payload.movement_type.value,
            created_at=now,
        )
    )
    await db.commit()

    return GameSyncResponse(session_id=payload.session_id, status="synced", server_timestamp=now)


@router.post("/end/", response_model=GameEndResponse)
async def end_game(payload: GameEndRequest, db: AsyncSession = Depends(get_db)) -> GameEndResponse:
    session = await get_active_session(db, payload.session_id)

    now = utcnow()
    xp = calculate_xp(payload.final_score)

    if session.user_id:
        user = await get_or_create_user(db, session.user_id, None, now)
        high_score_updated = record_game(
            db,
            user,
            score=payload.final_score,
            coins=payload.coins_collected,
            distance=payload.distance_traveled,
            xp=xp,
            now=now,
            session_id=session.session_id,
        )
    else:
        # Anonymous sessions compete against the best score on this backend.
        previous_best = await db.scalar(
            select(func.max(GameSession.final_score)).where(GameSession.status == STATUS_ENDED)
        )
        high_score_updated = payload.final_score > (previous_best or 0)

    session.status = STATUS_ENDED
    session.ended_at = now
    session.final_score = payload.final_score
    session.coins_collected = payload.coins_collected
    session.distance_traveled = payload.distance_traveled
    await db.commit()

    return GameEndResponse(
        session_id=session.session_id,
        status=STATUS_ENDED,
        high_score_updated=high_score_updated,
        earned_rewards=EarnedRewards(coins=payload.coins_collected, xp=xp),
    )
