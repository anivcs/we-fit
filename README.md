# we-fit
Motion Controlled Subway Surfer

## Running locally

1. Backend + PostgreSQL: `docker compose up -d --build` (API at `http://localhost:8000/api/v1`).
2. Frontend: `cd frontend && npm install && npm run dev`, then open `http://localhost:5173` on the display device.

Frontend URL options:
- `?api=http://<backend-host>:8000/api/v1` if the backend isn't on the same host as the page.
- `?controller=ws://<esp32-ip>:81` to connect the ESP32 over WebSocket. It may send plain moves (`JUMP`, `DUCK`, `LEFT`, `RIGHT`), JSON (`{"move": "JUMP"}`), or raw accelerometer samples in g (`{"ax": 0.1, "ay": 2.3, "az": 0.0}`, +y up, +x right).

Keyboard fallback: ← → lanes, ↑ / Space jump, ↓ duck, P pause.

Tests: `uv run pytest` (backend) and `cd frontend && npm test`.
