"""
JWT verification for MetaMind.

Supabase newer projects sign access tokens with ES256 (ECDSA P-256).
Older projects used HS256. We support both:
  - ES256 / RS256 → verify via Supabase's public JWKS endpoint
  - HS256          → verify with SUPABASE_JWT_SECRET from .env

JWKS are cached in memory for 5 minutes to avoid hitting Supabase on
every request. The cache is invalidated on startup and cleared whenever
the TTL expires.

user_id is ALWAYS derived from the verified JWT — never from the request
body. This is a hard constraint per Section 5 of the dev plan.
"""

import json
import time
import httpx
import jwt
from jwt.algorithms import ECAlgorithm, RSAAlgorithm
from jwt.exceptions import InvalidTokenError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from config import get_settings

bearer_scheme = HTTPBearer()

# ── JWKS cache ────────────────────────────────────────────────────
# Avoids fetching public keys from Supabase on every single request.
# 5-minute TTL is short enough that a key rotation is picked up quickly.
_jwks_cache: dict = {"keys": [], "fetched_at": 0.0}
_JWKS_TTL_SECONDS = 300


async def _get_jwks(supabase_url: str) -> list[dict]:
    """Return cached JWKS keys, refreshing from Supabase if stale."""
    now = time.monotonic()
    if now - _jwks_cache["fetched_at"] < _JWKS_TTL_SECONDS and _jwks_cache["keys"]:
        return _jwks_cache["keys"]

    jwks_url = f"{supabase_url}/auth/v1/.well-known/jwks.json"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(jwks_url)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Could not reach Supabase JWKS endpoint: {e}",
        )

    _jwks_cache["keys"] = data.get("keys", [])
    _jwks_cache["fetched_at"] = now
    return _jwks_cache["keys"]


def _public_key_from_jwk(jwk: dict):
    """Convert a JWK dict to a public key object that PyJWT can use."""
    kty = jwk.get("kty", "")
    if kty == "EC":
        return ECAlgorithm.from_jwk(json.dumps(jwk))
    if kty == "RSA":
        return RSAAlgorithm.from_jwk(json.dumps(jwk))
    raise ValueError(f"Unsupported JWK key type: {kty}")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> str:
    """
    Verifies the Supabase-issued JWT and returns the user's UUID.
    Supports both ES256 (asymmetric, JWKS) and HS256 (symmetric, JWT secret).
    """
    settings = get_settings()
    token = credentials.credentials

    # ── 1. Peek at the unverified header ─────────────────────────
    # This tells us which algorithm to use for verification.
    # We do NOT trust the claimed algorithm to select a key —
    # we use it only to choose the verification path.
    try:
        header = jwt.get_unverified_header(token)
        claimed_alg = header.get("alg", "unknown")
        kid = header.get("kid")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Malformed token header: {e}",
        )

    try:
        # ── 2a. Asymmetric (ES256 / RS256) → JWKS ────────────────
        if claimed_alg in ("ES256", "RS256", "RS384", "RS512", "ES384", "ES512"):
            keys = await _get_jwks(settings.supabase_url)

            payload = None
            last_error: Exception | None = None
            for k in keys:
                if kid and k.get("kid") != kid:
                    continue
                try:
                    public_key = _public_key_from_jwk(k)
                except Exception as e:
                    last_error = e
                    continue
                try:
                    payload = jwt.decode(
                        token,
                        public_key,
                        algorithms=[claimed_alg],
                        audience="authenticated",
                    )
                    break
                except InvalidTokenError as e:
                    last_error = e
                    continue

            if payload is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"No matching public key verified this token: {last_error}",
                )

        # ── 2b. Symmetric (HS256) → JWT secret ───────────────────
        elif claimed_alg == "HS256":
            payload = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
            )

        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Unsupported token algorithm: {claimed_alg}",
            )

        # ── 3. Extract user_id from verified payload ──────────────
        user_id: str = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing subject claim",
            )

        return user_id

    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
        )
