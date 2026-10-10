import { describe, expect, it, vi } from 'vitest';

import { ApiError, createApi, generateId, userIdFromName } from '../src/api.js';

const BASE = 'http://backend:8000/api/v1';

function mockFetch(status, body) {
  return vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    statusText: 'status',
    json: async () => body,
  }));
}

describe('api client', () => {
  it('starts a game with the session id and optional user', async () => {
    const fetchImpl = mockFetch(201, { session_id: 'sess_1', status: 'started', seed: 42 });
    const api = createApi(BASE, { fetchImpl });

    const res = await api.startGame({ sessionId: 'sess_1', userId: 'user_ann', username: 'Ann' });

    expect(res.seed).toBe(42);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe(`${BASE}/game/start/`);
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({ session_id: 'sess_1', user_id: 'user_ann', username: 'Ann' });
  });

  it('omits user fields for anonymous sessions', async () => {
    const fetchImpl = mockFetch(201, { seed: 1 });
    await createApi(BASE, { fetchImpl }).startGame({ sessionId: 'sess_1', userId: null });
    expect(JSON.parse(fetchImpl.mock.calls[0][1].body)).toEqual({ session_id: 'sess_1' });
  });

  it('sends sync and end payloads in the backend contract shape', async () => {
    const fetchImpl = mockFetch(200, {});
    const api = createApi(BASE, { fetchImpl });

    await api.syncMove('sess_1', 'JUMP');
    await api.endGame({ sessionId: 'sess_1', finalScore: 14500, coinsCollected: 35, distanceTraveled: 950 });

    expect(fetchImpl.mock.calls[0][0]).toBe(`${BASE}/game/sync/`);
    expect(JSON.parse(fetchImpl.mock.calls[0][1].body)).toEqual({ session_id: 'sess_1', movement_type: 'JUMP' });
    expect(fetchImpl.mock.calls[1][0]).toBe(`${BASE}/game/end/`);
    expect(JSON.parse(fetchImpl.mock.calls[1][1].body)).toEqual({
      session_id: 'sess_1',
      final_score: 14500,
      coins_collected: 35,
      distance_traveled: 950,
    });
  });

  it('passes leaderboard and stats query params', async () => {
    const fetchImpl = mockFetch(200, { rankings: [] });
    const api = createApi(BASE, { fetchImpl });

    await api.getLeaderboard({ limit: 5, timeframe: 'weekly' });
    await api.getUserStats('user_ann');

    expect(fetchImpl.mock.calls[0][0]).toBe(`${BASE}/leaderboard/?limit=5&timeframe=weekly`);
    expect(fetchImpl.mock.calls[1][0]).toBe(`${BASE}/user/stats/?user_id=user_ann`);
  });

  it('returns null stats for unknown users', async () => {
    const api = createApi(BASE, { fetchImpl: mockFetch(404, { detail: 'not found' }) });
    expect(await api.getUserStats('ghost')).toBeNull();
  });

  it('raises ApiError with the backend detail and status', async () => {
    const api = createApi(BASE, { fetchImpl: mockFetch(409, { detail: 'Session already ended' }) });
    await expect(api.syncMove('s', 'JUMP')).rejects.toMatchObject({ status: 409, message: 'Session already ended' });
  });

  it('raises ApiError with status 0 when the backend is unreachable', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    });
    const err = await createApi(BASE, { fetchImpl }).healthCheck().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(0);
  });
});

describe('ids', () => {
  const BACKEND_ID = /^[A-Za-z0-9_-]{1,64}$/;

  it('generates backend-valid session ids', () => {
    const id = generateId('sess');
    expect(id).toMatch(BACKEND_ID);
    expect(id).not.toBe(generateId('sess'));
  });

  it('derives backend-valid user ids from display names', () => {
    expect(userIdFromName('Wii Master!')).toBe('user_wii_master');
    expect(userIdFromName('  ')).toBeNull();
    expect(userIdFromName('🔥🔥')).toBeNull();
    expect(userIdFromName('x'.repeat(100))).toMatch(BACKEND_ID);
  });
});
