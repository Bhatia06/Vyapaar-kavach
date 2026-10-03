"""Authentication & authorization dependencies.

Sessions are opaque tokens stored server-side and delivered as an HttpOnly
cookie (the token is also returned in the login body so API clients/tests can
use `Authorization: Bearer <token>`). Every dependency resolves the role from
the membership table — never from client-supplied claims.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session as OrmSession

from .config import settings
from .db import get_db
from . import models


@dataclass
class Principal:
    """The authenticated caller, scoped to one tenant and one role."""

    user: models.User
    tenant: models.Tenant
    role: str

    @property
    def user_id(self) -> str:
        return self.user.id

    @property
    def tenant_id(self) -> str:
        return self.tenant.id


def _extract_token(request: Request) -> str | None:
    token = request.cookies.get(settings.SESSION_COOKIE)
    if token:
        return token
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def require_principal(
    request: Request, db: OrmSession = Depends(get_db)
) -> Principal:
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail={"code": "AUTH_REQUIRED", "error": "Sign in required."})
    sess = db.get(models.Session, token)
    now = datetime.now(timezone.utc)
    if sess is None or sess.expires_at.replace(tzinfo=timezone.utc) < now:
        raise HTTPException(status_code=401, detail={"code": "SESSION_EXPIRED", "error": "Session is invalid or expired."})
    membership = (
        db.query(models.Membership)
        .filter(
            models.Membership.user_id == sess.user_id,
            models.Membership.tenant_id == sess.tenant_id,
            models.Membership.active.is_(True),
        )
        .first()
    )
    if membership is None:
        raise HTTPException(status_code=403, detail={"code": "NOT_A_MEMBER", "error": "No active membership for this tenant."})
    return Principal(user=sess.user, tenant=sess.tenant, role=membership.role)


def require_role(*roles: str):
    """Endpoint dependency enforcing an allowed-role set."""

    def _dep(principal: Principal = Depends(require_principal)) -> Principal:
        if principal.role not in roles:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "FORBIDDEN_ROLE",
                    "error": f"This action requires one of: {', '.join(roles)}.",
                },
            )
        return principal

    return _dep


def make_session(db: OrmSession, user: models.User, tenant_id: str) -> models.Session:
    """Create a session for the user's membership in the given tenant."""
    expires = datetime.now(timezone.utc) + timedelta(hours=settings.SESSION_TTL_HOURS)
    sess = models.Session(
        id=__import__("secrets").token_urlsafe(32),
        user_id=user.id,
        tenant_id=tenant_id,
        expires_at=expires,
    )
    db.add(sess)
    return sess
