/**
 * API client — all calls go through /api (proxied to localhost:8000 in dev).
 * user_id is NEVER sent in the body — always derived from the JWT on the backend.
 */

const BASE = '/api'

function authHeader(token) {
  return { Authorization: `Bearer ${token}` }
}

async function request(method, path, { token, body } = {}) {
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? authHeader(token) : {}),
  }
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  })

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
export const debateStart = (token, { topic_id, student_explanation, predicted_score, slider_touched }) =>
  request('POST', '/debate/start', {
    token,
    body: { topic_id, student_explanation, predicted_score, slider_touched: slider_touched ?? false },
  })

export const debateRespond = (token, { round_id, student_rebuttal }) =>
  request('POST', '/debate/respond', { token, body: { round_id, student_rebuttal } })

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

