from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field

Identifier = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")]
Username = Annotated[str, Field(min_length=1, max_length=64)]
NonNegativeInt = Annotated[int, Field(ge=0)]


class MovementType(StrEnum):
    JUMP = "JUMP"
    DUCK = "DUCK"
    LEFT = "LEFT"
    RIGHT = "RIGHT"


class Timeframe(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    ALL_TIME = "all_time"


class HealthResponse(BaseModel):
    status: Literal["healthy", "unhealthy"]
    database: Literal["connected", "disconnected"]
    timestamp: datetime


class GameStartRequest(BaseModel):
    session_id: Identifier
    user_id: Identifier | None = Field(
        default=None,
        description="Optional player to attribute this session's results to.",
    )
    username: Username | None = None


class GameStartResponse(BaseModel):
    session_id: str
    status: Literal["started"]
    seed: int
    started_at: datetime


class GameSyncRequest(BaseModel):
    session_id: Identifier
    movement_type: MovementType


class GameSyncResponse(BaseModel):
    session_id: str
    status: Literal["synced"]
    server_timestamp: datetime


class GameEndRequest(BaseModel):
    session_id: Identifier
    final_score: NonNegativeInt
    coins_collected: NonNegativeInt
    distance_traveled: NonNegativeInt


class EarnedRewards(BaseModel):
    coins: int
    xp: int


class GameEndResponse(BaseModel):
    session_id: str
    status: Literal["ended"]
    high_score_updated: bool
    earned_rewards: EarnedRewards


class UserStatsResponse(BaseModel):
    user_id: str
    total_games_played: int
    highest_score: int
    total_distance: int
    total_coins: int


class UserStatsUpdateRequest(BaseModel):
    user_id: Identifier
    username: Username | None = None
    game_score: NonNegativeInt
    coins_collected: NonNegativeInt
    distance_traveled: NonNegativeInt


class UserStatsUpdateResponse(BaseModel):
    user_id: str
    status: Literal["updated"]
    updated_at: datetime


class LeaderboardEntry(BaseModel):
    rank: int
    user_id: str
    username: str
    score: int


class LeaderboardResponse(BaseModel):
    timeframe: Timeframe
    rankings: list[LeaderboardEntry]
