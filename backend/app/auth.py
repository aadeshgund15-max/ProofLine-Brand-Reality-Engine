"""Authentication and workspace authorization.

Every protected route depends on `current_user` (verified JWT) and, for workspace data,
`member_of(roles)` which checks membership in the *database* on every request. A workspace id in
the URL is never trusted by itself.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from typing import Callable, Optional
from uuid import UUID, uuid4

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import Connection

from app.config import settings
from app.db import ex, get_conn, q1

_jwks_client: Optional[jwt.PyJWKClient] = None


@dataclass
class User:
    id: UUID
    email: str


# ------------------------------------------------------------ passwords (local mode)
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(h).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_b64, h_b64 = stored.split("$")
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(h_b64)
    except ValueError:
        return False
    h = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return hmac.compare_digest(h, expected)


def issue_local_token(user_id: UUID, email: str, ttl_s: int = 8 * 3600) -> str:
    if len(settings.local_jwt_secret) < 32:
        raise HTTPException(500, "LOCAL_JWT_SECRET must be set to at least 32 characters")
    now = int(time.time())
    return jwt.encode({"sub": str(user_id), "email": email, "aud": "authenticated", "iat": now,
                       "exp": now + ttl_s, "iss": "proofline-local"}, settings.local_jwt_secret, algorithm="HS256")


# ----------------------------------------------------------------- token verification
def _decode(token: str) -> dict:
    try:
        if settings.auth_mode == "local":
            if len(settings.local_jwt_secret) < 32:
                raise HTTPException(500, "LOCAL_JWT_SECRET is not configured")
            return jwt.decode(token, settings.local_jwt_secret, algorithms=["HS256"], audience="authenticated")
        header = jwt.get_unverified_header(token)
        if header.get("alg") == "HS256":
            if not settings.supabase_jwt_secret:
                raise HTTPException(500, "SUPABASE_JWT_SECRET is not configured")
            return jwt.decode(token, settings.supabase_jwt_secret, algorithms=["HS256"], audience="authenticated")
        global _jwks_client
        if _jwks_client is None:
            _jwks_client = jwt.PyJWKClient(f"{settings.supabase_url}/auth/v1/.well-known/jwks.json")
        key = _jwks_client.get_signing_key_from_jwt(token).key
        return jwt.decode(token, key, algorithms=["ES256", "RS256"], audience="authenticated")
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired session")


def current_user(request: Request, conn: Connection = Depends(get_conn)) -> User:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(401, "Not authenticated")
    claims = _decode(auth[7:].strip())
    try:
        uid = UUID(claims["sub"])
    except (KeyError, ValueError):
        raise HTTPException(401, "Invalid session")
    email = (claims.get("email") or "").lower()
    if not email:
        raise HTTPException(401, "Session has no email")
    ex(conn, """insert into app_users (id, email) values (:id, :email)
                on conflict (id) do update set email = excluded.email""", id=uid, email=email)
    return User(uid, email)


# ---------------------------------------------------------------- workspace roles
@dataclass
class Member:
    user: User
    workspace_id: UUID
    role: str


def member_of(*roles: str) -> Callable[..., Member]:
    """Dependency factory: user must belong to {workspace_id} with one of `roles` (any role if empty).
    A non-member gets 404 so workspace ids cannot be probed."""
    def dep(workspace_id: UUID, user: User = Depends(current_user), conn: Connection = Depends(get_conn)) -> Member:
        row = q1(conn, "select role from workspace_members where workspace_id = :w and user_id = :u",
                 w=workspace_id, u=user.id)
        if row is None:
            raise HTTPException(404, "Workspace not found")
        if roles and row["role"] not in roles:
            raise HTTPException(403, f"Your role ({row['role']}) cannot perform this action")
        return Member(user, workspace_id, row["role"])
    return dep


EDIT_ROLES = ("owner", "editor")
DECIDE_ROLES = ("owner", "reviewer")
