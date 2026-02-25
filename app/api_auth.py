from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .db import get_db
from .models import Account, RefreshToken
from .security import (
    verify_password,
    create_access_token,
    create_refresh_token_plain,
    refresh_token_hash,
    new_jti,
    decode_access_token,
    verify_totp_code,
)
from .auth_utils import (
    get_client_ip,
    ensure_not_locked,
    register_failed_login,
    register_success_login,
    log_auth_event,
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RefreshRequest(BaseModel):
    refresh_token: str


REFRESH_EXPIRES_DAYS = 30


def _issue_refresh_token(
    db: Session,
    account: Account,
    ip: str,
    user_agent: str,
    *,
    replace: RefreshToken | None = None,
) -> tuple[str, RefreshToken]:
    plain = create_refresh_token_plain()
    jti = new_jti()
    rt = RefreshToken(
        account_id=account.id,
        jti=jti,
        token_hash=refresh_token_hash(plain),
        issued_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(days=REFRESH_EXPIRES_DAYS),
        ip=ip,
        user_agent=user_agent or "",
    )
    if replace is not None:
        replace.revoked_at = datetime.utcnow()
        replace.replaced_by_jti = jti
        log_auth_event(db, "refresh_rotated", username=account.username, role=account.role, ip=ip, user_agent=user_agent, details=f"replaced_jti={replace.jti}")
    db.add(rt)
    return plain, rt


@router.post("/token")
async def token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    username = (form_data.username or "").strip()
    password = (form_data.password or "").strip()

    form = await request.form()
    otp = (form.get("otp") or "").strip()

    ip = get_client_ip(request)
    ua = request.headers.get("user-agent", "")

    # lockout check
    try:
        ensure_not_locked(db, username=username, ip=ip, user_agent=ua)
    except PermissionError as e:
        raise HTTPException(status_code=429, detail=str(e))

    acct = db.query(Account).filter(Account.username == username, Account.activo == True).first()
    if (not acct) or (not verify_password(password, acct.password_hash)):
        delay, locked_until = register_failed_login(db, username=username, ip=ip, user_agent=ua)
        db.commit()
        if delay:
            import time
            time.sleep(delay)
        if locked_until:
            raise HTTPException(status_code=429, detail=f"Cuenta bloqueada hasta {locked_until} UTC")
        raise HTTPException(status_code=401, detail="Usuario o contraseña inválidos")

    # MFA for admin (optional)
    if acct.role == "admin" and getattr(acct, "mfa_enabled", False):
        if not otp:
            register_failed_login(db, username=username, ip=ip, user_agent=ua)
            log_auth_event(db, "mfa_required", username=username, role=acct.role, ip=ip, user_agent=ua)
            db.commit()
            raise HTTPException(status_code=401, detail="OTP requerido (MFA)")
        if (not acct.mfa_secret) or (not verify_totp_code(acct.mfa_secret, otp)):
            delay, locked_until = register_failed_login(db, username=username, ip=ip, user_agent=ua)
            log_auth_event(db, "mfa_failed", username=username, role=acct.role, ip=ip, user_agent=ua)
            db.commit()
            if delay:
                import time
                time.sleep(delay)
            if locked_until:
                raise HTTPException(status_code=429, detail=f"Cuenta bloqueada hasta {locked_until} UTC")
            raise HTTPException(status_code=401, detail="OTP inválido")

    register_success_login(db, username=username, role=acct.role, ip=ip, user_agent=ua)

    access_token = create_access_token(subject=acct.username, role=acct.role, expires_minutes=60)
    refresh_plain, _ = _issue_refresh_token(db, acct, ip=ip, user_agent=ua)

    db.commit()
    return {"access_token": access_token, "refresh_token": refresh_plain, "token_type": "bearer", "role": acct.role}


@router.post("/refresh")
def refresh(
    request: Request,
    body: RefreshRequest,
    db: Session = Depends(get_db),
):
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent", "")

    token_plain = (body.refresh_token or "").strip()
    if not token_plain:
        raise HTTPException(status_code=400, detail="refresh_token requerido")

    token_h = refresh_token_hash(token_plain)
    rt = db.query(RefreshToken).filter(RefreshToken.token_hash == token_h).first()
    if not rt:
        raise HTTPException(status_code=401, detail="Refresh token inválido")

    acct = db.query(Account).filter(Account.id == rt.account_id, Account.activo == True).first()
    if not acct:
        raise HTTPException(status_code=401, detail="Cuenta no válida")

    # Expired
    if rt.expires_at and rt.expires_at < datetime.utcnow():
        rt.revoked_at = datetime.utcnow()
        log_auth_event(db, "refresh_expired", username=acct.username, role=acct.role, ip=ip, user_agent=ua)
        db.commit()
        raise HTTPException(status_code=401, detail="Refresh token expirado")

    # Reuse detection
    if rt.revoked_at is not None:
        # Possible token theft: revoke all outstanding refresh tokens
        db.query(RefreshToken).filter(RefreshToken.account_id == acct.id, RefreshToken.revoked_at.is_(None)).update(
            {"revoked_at": datetime.utcnow()}
        )
        log_auth_event(db, "refresh_reuse_detected", username=acct.username, role=acct.role, ip=ip, user_agent=ua, details=f"jti={rt.jti}")
        db.commit()
        raise HTTPException(status_code=401, detail="Refresh token ya fue usado (posible compromiso). Inicia sesión de nuevo.")

    # Rotate
    access_token = create_access_token(subject=acct.username, role=acct.role, expires_minutes=60)
    refresh_plain, _new = _issue_refresh_token(db, acct, ip=ip, user_agent=ua, replace=rt)

    db.commit()
    return {"access_token": access_token, "refresh_token": refresh_plain, "token_type": "bearer", "role": acct.role}


def get_current_account_jwt(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> Account:
    payload = decode_access_token(token)
    username = payload.get("sub", "")
    acct = db.query(Account).filter(Account.username == username, Account.activo == True).first()
    if not acct:
        raise HTTPException(status_code=401, detail="Usuario no válido")
    return acct
