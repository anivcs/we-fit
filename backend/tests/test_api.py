import os
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.database import Base
from backend.models import Score, utcnow

API = "/api/v1"


@pytest.fixture
def client(tmp_path):
    # Set TEST_DATABASE_URL to run against a disposable Postgres; its tables are dropped after each test.
    external_url = os.getenv("TEST_DATABASE_URL")
    app = create_app(external_url or f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    with TestClient(app) as test_client:
        yield test_client
        if external_url:

            async def drop_tables():
                async with app.state.sessionmaker() as db:
                    conn = await db.connection()
                    await conn.run_sync(Base.metadata.drop_all)
                    await db.commit()

            test_client.portal.call(drop_tables)


def start(client, session_id="sess_1", **extra):
    return client.post(f"{API}/game/start/", json={"session_id": session_id, **extra})


def end(client, session_id="sess_1", score=14500, coins=35, distance=950):
    return client.post(
        f"{API}/game/end/",
        json={
            "session_id": session_id,
            "final_score": score,
            "coins_collected": coins,
            "distance_traveled": distance,
        },
    )


def post_stats(client, user_id, score, coins=0, distance=0, **extra):
    return client.post(
        f"{API}/user/stats/",
        json={
            "user_id": user_id,
            "game_score": score,
            "coins_collected": coins,
            "distance_traveled": distance,
            **extra,
        },
    )


def test_health_check(client):
    res = client.get(f"{API}/health_check/")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "healthy"
    assert body["database"] == "connected"
    assert body["timestamp"].endswith("Z")


def test_game_lifecycle(client):
    res = start(client)
    assert res.status_code == 201
    body = res.json()
    assert body["session_id"] == "sess_1"
    assert body["status"] == "started"
    assert isinstance(body["seed"], int)
    assert "started_at" in body

    res = client.post(f"{API}/game/sync/", json={"session_id": "sess_1", "movement_type": "JUMP"})
    assert res.status_code == 200
    assert res.json()["status"] == "synced"
    assert "server_timestamp" in res.json()

    res = end(client)
    assert res.status_code == 200
    assert res.json() == {
        "session_id": "sess_1",
        "status": "ended",
        "high_score_updated": True,
        "earned_rewards": {"coins": 35, "xp": 145},
    }


def test_start_duplicate_session_conflicts(client):
    assert start(client).status_code == 201
    assert start(client).status_code == 409


def test_sync_and_end_unknown_session_404(client):
    res = client.post(f"{API}/game/sync/", json={"session_id": "nope", "movement_type": "JUMP"})
    assert res.status_code == 404
    assert end(client, session_id="nope").status_code == 404


def test_cannot_sync_or_end_after_end(client):
    start(client)
    end(client)
    res = client.post(f"{API}/game/sync/", json={"session_id": "sess_1", "movement_type": "LEFT"})
    assert res.status_code == 409
    assert end(client).status_code == 409


def test_invalid_payloads_rejected(client):
    start(client)
    res = client.post(f"{API}/game/sync/", json={"session_id": "sess_1", "movement_type": "FLY"})
    assert res.status_code == 422
    assert end(client, score=-1).status_code == 422
    assert start(client, session_id="").status_code == 422


def test_anonymous_high_score_compares_against_previous_sessions(client):
    start(client, "a")
    assert end(client, "a", score=100).json()["high_score_updated"] is True
    start(client, "b")
    assert end(client, "b", score=50).json()["high_score_updated"] is False


def test_end_game_updates_linked_user_stats(client):
    start(client, "s1", user_id="user_987", username="WiiMaster")
    end(client, "s1", score=24500, coins=100, distance=5000)
    start(client, "s2", user_id="user_987")
    res = end(client, "s2", score=1000, coins=10, distance=200)
    assert res.json()["high_score_updated"] is False

    res = client.get(f"{API}/user/stats/", params={"user_id": "user_987"})
    assert res.status_code == 200
    assert res.json() == {
        "user_id": "user_987",
        "total_games_played": 2,
        "highest_score": 24500,
        "total_distance": 5200,
        "total_coins": 110,
    }


def test_user_stats_create_and_update(client):
    res = post_stats(client, "user_1", 14500, coins=35, distance=950)
    assert res.status_code == 200
    assert res.json()["status"] == "updated"
    assert "updated_at" in res.json()

    post_stats(client, "user_1", 20000, coins=5, distance=50)
    stats = client.get(f"{API}/user/stats/", params={"user_id": "user_1"}).json()
    assert stats["total_games_played"] == 2
    assert stats["highest_score"] == 20000
    assert stats["total_coins"] == 40
    assert stats["total_distance"] == 1000


def test_user_stats_unknown_user_404(client):
    assert client.get(f"{API}/user/stats/", params={"user_id": "ghost"}).status_code == 404


def test_user_stats_requires_user_id(client):
    assert client.get(f"{API}/user/stats/").status_code == 422


def test_leaderboard_ranks_best_score_per_user(client):
    post_stats(client, "user_123", 54200, username="RunnerKing")
    post_stats(client, "user_987", 48900, username="WiiMaster")
    post_stats(client, "user_987", 1000)
    post_stats(client, "user_555", 100)

    res = client.get(f"{API}/leaderboard/", params={"limit": 2})
    assert res.status_code == 200
    assert res.json() == {
        "timeframe": "all_time",
        "rankings": [
            {"rank": 1, "user_id": "user_123", "username": "RunnerKing", "score": 54200},
            {"rank": 2, "user_id": "user_987", "username": "WiiMaster", "score": 48900},
        ],
    }


def test_leaderboard_timeframe_filters_old_scores(client):
    post_stats(client, "old_user", 99999)
    post_stats(client, "new_user", 10)

    async def age_old_scores():
        async with client.app.state.sessionmaker() as db:
            score = (await db.execute(Score.__table__.select().where(Score.user_id == "old_user"))).first()
            await db.execute(
                Score.__table__.update()
                .where(Score.id == score.id)
                .values(created_at=utcnow() - timedelta(days=3))
            )
            await db.commit()

    client.portal.call(age_old_scores)

    daily = client.get(f"{API}/leaderboard/", params={"timeframe": "daily"}).json()
    assert [r["user_id"] for r in daily["rankings"]] == ["new_user"]

    weekly = client.get(f"{API}/leaderboard/", params={"timeframe": "weekly"}).json()
    assert [r["user_id"] for r in weekly["rankings"]] == ["old_user", "new_user"]


def test_leaderboard_validates_params(client):
    assert client.get(f"{API}/leaderboard/", params={"limit": 0}).status_code == 422
    assert client.get(f"{API}/leaderboard/", params={"timeframe": "monthly"}).status_code == 422
