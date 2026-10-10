export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

const ID_MAX_LENGTH = 64;

export function generateId(prefix) {
  const bytes = crypto.getRandomValues(new Uint8Array(8));
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  return `${prefix}_${hex}`;
}

// The backend only accepts [A-Za-z0-9_-] ids, so derive a stable id from the display name.
export function userIdFromName(name) {
  const slug = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '_')
    .replace(/^_+|_+$/g, '');
  return slug ? `user_${slug}`.slice(0, ID_MAX_LENGTH) : null;
}

export function createApi(baseUrl, { fetchImpl = (...args) => fetch(...args), timeoutMs = 4000 } = {}) {
  async function request(path, { method = 'GET', body, query } = {}) {
    const url = new URL(`${baseUrl}${path}`);
    for (const [key, value] of Object.entries(query ?? {})) {
      if (value !== undefined && value !== null) url.searchParams.set(key, value);
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    let response;
    try {
      response = await fetchImpl(url.toString(), {
        method,
        headers: body ? { 'Content-Type': 'application/json' } : undefined,
        body: body ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });
    } catch (err) {
      throw new ApiError(`Backend unreachable: ${err.message}`, 0);
    } finally {
      clearTimeout(timer);
    }

    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = typeof data?.detail === 'string' ? data.detail : response.statusText;
      throw new ApiError(detail || `HTTP ${response.status}`, response.status);
    }
    return data;
  }

  return {
    healthCheck: () => request('/health_check/'),

    startGame: ({ sessionId, userId, username }) =>
      request('/game/start/', {
        method: 'POST',
        body: {
          session_id: sessionId,
          ...(userId ? { user_id: userId, username } : {}),
        },
      }),

    syncMove: (sessionId, movementType) =>
      request('/game/sync/', {
        method: 'POST',
        body: { session_id: sessionId, movement_type: movementType },
      }),

    endGame: ({ sessionId, finalScore, coinsCollected, distanceTraveled }) =>
      request('/game/end/', {
        method: 'POST',
        body: {
          session_id: sessionId,
          final_score: finalScore,
          coins_collected: coinsCollected,
          distance_traveled: distanceTraveled,
        },
      }),

    async getUserStats(userId) {
      try {
        return await request('/user/stats/', { query: { user_id: userId } });
      } catch (err) {
        if (err.status === 404) return null;
        throw err;
      }
    },

    getLeaderboard: ({ limit = 10, timeframe = 'all_time' } = {}) =>
      request('/leaderboard/', { query: { limit, timeframe } }),
  };
}
