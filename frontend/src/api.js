/**
 * API client — all calls go through /api (proxied to localhost:8000 in dev).
 * user_id is NEVER sent in the body — always derived from the JWT on the backend.
 */

const BASE = '/api'
const REFRESH_KEY = 'metamind_refresh_token'
const TOKEN_KEY  = 'metamind_token'

function authHeader(token) {
  return { Authorization: `Bearer ${token}` }
}

/**
 * Attempt a silent token refresh via Supabase's refresh_token grant.
 * Returns the new access_token string on success, null on failure.
 */
export async function refreshSession() {
  const refreshToken = localStorage.getItem(REFRESH_KEY)
  if (!refreshToken) return null
  try {
    const res = await fetch(`${SUPABASE_URL}/auth/v1/token?grant_type=refresh_token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'apikey': SUPABASE_ANON_KEY },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
    const data = await res.json()
    if (!res.ok || data.error) return null
    // Persist the new tokens
    localStorage.setItem(TOKEN_KEY, data.access_token)
    if (data.refresh_token) localStorage.setItem(REFRESH_KEY, data.refresh_token)
    return data.access_token
  } catch {
    return null
  }
}

async function request(method, path, { token, body } = {}) {
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? authHeader(token) : {}),
  }
  let res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  })

  // Auto-refresh on 401: try once with a fresh token
  if (res.status === 401 && token) {
    const newToken = await refreshSession()
    if (newToken) {
      res = await fetch(`${BASE}${path}`, {
        method,
        headers: { 'Content-Type': 'application/json', ...authHeader(newToken) },
        body: body ? JSON.stringify(body) : undefined,
      })
    }
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

// ── Auth (Supabase REST directly) ─────────────────────────────────
const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL
const SUPABASE_ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY

export async function signUp(email, password) {
  const res = await fetch(`${SUPABASE_URL}/auth/v1/signup`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'apikey': SUPABASE_ANON_KEY,
    },
    body: JSON.stringify({ email, password }),
  })
  const data = await res.json()
  if (data.error) throw new Error(data.error.message || data.error)
  return data
}

export async function signIn(email, password) {
  const res = await fetch(`${SUPABASE_URL}/auth/v1/token?grant_type=password`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'apikey': SUPABASE_ANON_KEY,
    },
    body: JSON.stringify({ email, password }),
  })
  const data = await res.json()
  if (data.error) throw new Error(data.error.message || data.error)
  if (data.error_description) throw new Error(data.error_description)
  // Persist refresh token so refreshSession() can use it on expiry
  if (data.refresh_token) localStorage.setItem(REFRESH_KEY, data.refresh_token)
  return data  // { access_token, refresh_token, user, ... }
}

// ── Topics ────────────────────────────────────────────────────────
export const getTopics = (token) =>
  request('GET', '/topics', { token })

export const createTopic = (token, { name, course, reference_notes }) =>
  request('POST', '/topics', { token, body: { name, course, reference_notes } })

export const addReferenceMaterial = (token, topic_id, { content, source_type }) =>
  request('POST', `/topics/${topic_id}/reference`, { token, body: { content, source_type } })

export const getReferenceMaterials = (token, topic_id) =>
  request('GET', `/topics/${topic_id}/reference`, { token })

// ── Debate ────────────────────────────────────────────────────────
/**
 * debateStart — Phase 2: includes confidence calibration fields.
 * predicted_score is 0.0–1.0; slider_touched distinguishes a real prediction
 * from an untouched 50% default (see models.py comment for why this matters).
 */
export const debateStart = (token, { topic_id, student_explanation, predicted_score, slider_touched, mode }) =>
  request('POST', '/debate/start', {
    token,
    body: { topic_id, student_explanation, predicted_score, slider_touched: slider_touched ?? false, mode: mode || "adult" },
  })

export const debateRespond = (token, { round_id, student_rebuttal, mode }) =>
  request('POST', '/debate/respond', { token, body: { round_id, student_rebuttal, mode: mode || "adult" } })

/**
 * debateCompress — Phase 2 (10.3): submit one-sentence compression summary.
 * Returns 409 if compression was already submitted for this round.
 * Returns 400 if the round has not been scored yet.
 */
export const debateCompress = (token, round_id, { summary }) =>
  request('POST', `/debate/${round_id}/compress`, { token, body: { summary } })

/**
 * flagDebateRound — Phase 4 (12.2): flag a counterargument as factually incorrect or unsupported.
 */
export const flagDebateRound = (token, round_id, { reason }) =>
  request('POST', `/debate/${round_id}/flag`, { token, body: { reason } })

// ── Dashboard ─────────────────────────────────────────────────────
export const getDashboard = (token) =>
  request('GET', '/dashboard', { token })

// ── Gamification ──────────────────────────────────────────────────
export const getStreaks = (token) =>
  request('GET', '/gamification/streaks', { token })

export const getAchievements = (token) =>
  request('GET', '/gamification/achievements', { token })

