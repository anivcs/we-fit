# WeFit Game: Full Stack Architecture & API Specification

This document outlines the complete full-stack architecture, data flow, and detailed API contract specifications for the Wii-sports-inspired, Subway Surfers-style motion-controlled game.

---

## 1. Full Stack Overview

* **Hardware:** ESP32 + Gyrosensor (MPU6050 / BNO055) streaming high-frequency motion data locally via Wi-Fi (UDP/WebSockets).
* **Local HDMI Display Device:** Mini-PC, Laptop, or Raspberry Pi outputting 3D rendering directly to a TV via HDMI.
* **Frontend:** HTML + JS (Three.js) running client-side physics and rendering at 60 FPS.
* **Backend:** FastAPI (Python) managing session lifecycles, player telemetry persistence, and leaderboards.
* **Database:** PostgreSQL storing lifetime user stats, session metrics, and high scores.

---

## 2. System Architecture Diagram

```text
 +------------------------+             +----------------------------------+
 |  ESP32 Controller      |             |  Frontend Display                |
 |  (Gyroscope / MPU6050) |             |  (HTML + JS / Three.js)          |
 +-----------+------------+             +----------------+-----------------+
             |                                           |
             | 1. High-Frequency Motion Data            | 2. Game Lifecycle
             |    (UDP / WebSockets - Local Network)     |    (REST HTTP)
             v                                           v
 +-----------+-------------------------------------------+-----------------+
 |                                                                         |
 |                      Local HDMI Display Device                          |
 |            (Mini-PC / Laptop / Raspberry Pi output to TV)              |
 |                                                                         |
 +-------------------------------------+-----------------------------------+
                                       |
                                       | 3. High-Score & Stats Persistence
                                       |    (Async REST APIs)
                                       v
                        +--------------+---------------+
                        |  FastAPI Backend             |
                        |  (Session, Leaderboards, DB) |
                        +------------------------------+
```

---

## 3. API Endpoints & Contracts

- **Base URL:** `http://<server-ip>:8000/api/v1`
- **Protocol:** HTTP/1.1 REST API
- **Running locally:** `cd backend && uv run uvicorn api:app --reload` (or `uv run uvicorn api:app --app-dir backend --reload` from the repo root). Interactive docs at `/docs`.
- **Configuration:** `DATABASE_URL` (e.g. `postgresql://user:pass@host:5432/wefit`; defaults to a local SQLite file `wefit.db`), `CORS_ORIGINS` (comma-separated, default `*`).
- **Errors:** `404` unknown session/user, `409` duplicate session or session already ended, `422` invalid payload or query parameters, `503` health check when the database is unreachable.

### 3.1. System Health

#### GET /health_check/

Checks if the FastAPI backend server and database connection are operational.

* **Response Status:** `200 OK`
* **Response Body (JSON):**

```json
{
  "status": "healthy",
  "database": "connected",
  "timestamp": "2026-10-10T11:08:00Z"
}
```

---

### 3.2. Game Session Management

#### POST /game/start/
Initializes a new game session.

* **Request Payload (JSON):**
```json
{
  "session_id": "sess_abc123xyz"
}
```
* **Optional fields:** `user_id` and `username`. When `user_id` is provided, `/game/end/` applies the result to that player's lifetime stats and the leaderboard, and `high_score_updated` reflects their personal best. Otherwise it reflects the best score across all sessions on this backend.
* **Response Status:** `201 Created`
* **Response Body (JSON):**
```json
{
  "session_id": "sess_abc123xyz",
  "status": "started",
  "seed": 42,
  "started_at": "2026-10-10T11:08:00Z"
}
```

#### POST /game/sync/
Synchronizes game state or logs movement events during gameplay.

* **Request Payload (JSON):**
```json
{
  "session_id": "sess_abc123xyz",
  "movement_type": "JUMP"
}
```
* `movement_type` is one of `JUMP`, `DUCK`, `LEFT`, `RIGHT`.
* **Response Status:** `200 OK`
* **Response Body (JSON):**
```json
{
  "session_id": "sess_abc123xyz",
  "status": "synced",
  "server_timestamp": "2026-10-10T11:08:05Z"
}
```

#### POST /game/end/
Finalizes the game session, records final score, and triggers post-game calculations.

* **Request Payload (JSON):**
```json
{
  "session_id": "sess_abc123xyz",
  "final_score": 14500,
  "coins_collected": 35,
  "distance_traveled": 950
}
```
* `earned_rewards.xp` is currently `final_score / 100` (rounded down).
* **Response Status:** `200 OK`
* **Response Body (JSON):**
```json
{
  "session_id": "sess_abc123xyz",
  "status": "ended",
  "high_score_updated": true,
  "earned_rewards": {
    "coins": 35,
    "xp": 150
  }
}
```

---

### 3.3. User Statistics & Persistence

#### GET /user/stats/
Retrieves lifetime statistics and performance metrics for a specific user from PostgreSQL.

* **Query Parameters:**
  * `user_id` (string, required): The unique identifier of the player.
* **Response Status:** `200 OK`
* **Response Body (JSON):**
```json
{
  "user_id": "user_987",
  "total_games_played": 12,
  "highest_score": 24500,
  "total_distance": 12400,
  "total_coins": 450
}
```

#### POST /user/stats/
Creates or updates lifetime user statistics in PostgreSQL.

* **Request Payload (JSON):**
```json
{
  "user_id": "user_987",
  "game_score": 14500,
  "coins_collected": 35,
  "distance_traveled": 950
}
```
* **Optional fields:** `username` (display name shown on the leaderboard; defaults to `user_id`).
* **Response Status:** `200 OK`
* **Response Body (JSON):**
```json
{
  "user_id": "user_987",
  "status": "updated",
  "updated_at": "2026-10-10T11:09:00Z"
}
```

---

### 3.4. Leaderboard

#### GET /leaderboard/
Fetches top player rankings from the PostgreSQL database.

* **Query Parameters:**
  * `limit` (integer, optional): Number of results to return (default: 10, max: 100).
  * `timeframe` (string, optional): `daily` (last 24 hours), `weekly` (last 7 days), or `all_time` (default: `all_time`).
* Each player appears once, ranked by their best score within the timeframe.
* **Response Status:** `200 OK`
* **Response Body (JSON):**
```json
{
  "timeframe": "all_time",
  "rankings": [
    {
      "rank": 1,
      "user_id": "user_123",
      "username": "RunnerKing",
      "score": 54200
    },
    {
      "rank": 2,
      "user_id": "user_987",
      "username": "WiiMaster",
      "score": 48900
    }
  ]
}
```