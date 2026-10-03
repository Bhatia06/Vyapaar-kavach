"""Auth routes: login, logout, current principal."""
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session as OrmSession

from ... import models
from ...auth import Principal, make_session, require_principal
from ...db import get_db
from ...schemas import LoginRequest, MeResponse, MembershipOut
from ...security import verify_password

router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.post("/login", response_model=MeResponse)
def login(body: LoginRequest, response: Response, db: OrmSession = Depends(get_db)):
    """Authenticate and start a demo session.

    If the user has multiple memberships, pass ``tenant_id`` to select one;
    otherwise the first active membership is used.
    """
    user = db.query(models.User).filter(models.User.username == body.username).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail={"code": "BAD_CREDENTIALS", "error": "Invalid username or password."})

    memberships = (
        db.query(models.Membership)
        .filter(models.Membership.user_id == user.id, models.Membership.active.is_(True))
        .all()
    )
    if not memberships:
        raise HTTPException(status_code=403, detail={"code": "NO_MEMBERSHIP", "error": "No active tenant membership."})

    if body.tenant_id:
        chosen = next((m for m in memberships if m.tenant_id == body.tenant_id), None)
        if chosen is None:
            # Do not leak which tenants exist.
            raise HTTPException(status_code=403, detail={"code": "NO_MEMBERSHIP", "error": "No active membership for that tenant."})
    else:
        chosen = memberships[0]

    sess = make_session(db, user, chosen.tenant_id)
    db.add(sess)
    db.commit()

    from ...config import settings

    response.set_cookie(
        settings.SESSION_COOKIE,
        sess.id,
        httponly=True,
        samesite="lax",
        secure=settings.SESSION_SECURE,
        max_age=settings.SESSION_TTL_HOURS * 3600,
    )
    return _me_payload(chosen.user, chosen.tenant, chosen)


@router.post("/logout")
def logout(response: Response, principal: Principal = Depends(require_principal), db: OrmSession = Depends(get_db)):
    from ...config import settings

    token = None
    # token is the cookie value — delete matching server-side session rows
    # for this user+tenant (demo simplicity: expire all their sessions).
    db.query(models.Session).filter(
        models.Session.user_id == principal.user_id,
        models.Session.tenant_id == principal.tenant_id,
    ).delete()
    db.commit()
    response.delete_cookie(settings.SESSION_COOKIE)
    return {"ok": True}


@router.get("/me", response_model=MeResponse)
def me(principal: Principal = Depends(require_principal), db: OrmSession = Depends(get_db)):
    membership = (
        db.query(models.Membership)
        .filter(
            models.Membership.user_id == principal.user_id,
            models.Membership.tenant_id == principal.tenant_id,
        )
        .first()
    )
    return _me_payload(principal.user, principal.tenant, membership)


def _me_payload(user: models.User, tenant: models.Tenant, membership: models.Membership) -> MeResponse:
    return MeResponse(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        tenant_id=tenant.id,
        role=membership.role,
        memberships=[MembershipOut(tenant_id=tenant.id, tenant_name=tenant.name, role=membership.role)],
        environment=tenant.environment,
    )
