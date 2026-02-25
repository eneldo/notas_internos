from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .models import LoginAttempt, AuthEvent




def log_auth_event(db: Session, event_type: str, username: str, role: str = '', ip: str = '', user_agent: str = '', details: str = '') -> None:
    db.add(AuthEvent(event_type=event_type, username=username, role=role or '', ip=ip or '', user_agent=user_agent or '', details=details or ''))
def utcnow() -> datetime:
    # naive utc to match existing models defaults (datetime.utcnow)
    return datetime.utcnow()


def progressive_delay_seconds(failed_count: int) -> int:
    """Exponential backoff delay (in seconds) capped to 8s.
    failed_count is the number of consecutive failures (>=1).
    """
    if failed_count <= 0:
        return 0
    return int(min(2 ** (failed_count - 1), 8))


def lockout_minutes_for_failures(failed_count: int) -> int:
    """Lockout duration after reaching threshold. Caps at 60 minutes."""
    # after 5 failures: 15 min, then 30, then 60...
    if failed_count < 5:
        return 0
    steps = failed_count - 5
    return int(min(15 * (2 ** steps), 60))


def get_client_ip(request) -> str:
    # Behind Dokploy/Traefik/Nginx you may have X-Forwarded-For
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return getattr(request.client, "host", "") or ""


def audit_event(db: Session, *, event_type: str, username: str, role: str = "", ip: str = "", user_agent: str = "", details: str = ""):
    db.add(AuthEvent(
        event_type=event_type,
        username=(username or "")[:120],
        role=(role or "")[:30],
        ip=(ip or "")[:80],
        user_agent=(user_agent or "")[:300],
        details=details or "",
        created_at=utcnow(),
    ))


def get_or_create_attempt(db: Session, username: str, ip: str) -> LoginAttempt:
    row = (
        db.query(LoginAttempt)
        .filter(LoginAttempt.username == username, LoginAttempt.ip == ip)
        .first()
    )
    if row:
        return row
    row = LoginAttempt(username=username, ip=ip, failed_count=0, last_failed_at=None, locked_until=None, updated_at=utcnow())
    db.add(row)
    db.flush()
    return row


def is_locked(row: LoginAttempt) -> bool:
    if not row.locked_until:
        return False
    return row.locked_until > utcnow()


def register_failed_login(db: Session, *, username: str, ip: str, user_agent: str = "") -> tuple[int, datetime | None]:
    """Increment failure counter, compute delay and lockout if needed.
    Returns (delay_seconds, locked_until).
    """
    row = get_or_create_attempt(db, username, ip)
    row.failed_count = int(row.failed_count or 0) + 1
    row.last_failed_at = utcnow()
    row.updated_at = utcnow()

    delay = progressive_delay_seconds(row.failed_count)

    mins = lockout_minutes_for_failures(row.failed_count)
    if mins:
        row.locked_until = utcnow() + timedelta(minutes=mins)
        audit_event(db, event_type="account_locked", username=username, ip=ip, user_agent=user_agent, details=f"locked {mins}m after {row.failed_count} failures")
    else:
        row.locked_until = None

    audit_event(db, event_type="login_failed", username=username, ip=ip, user_agent=user_agent, details=f"failed_count={row.failed_count}")

    return delay, row.locked_until


def register_success_login(db: Session, *, username: str, role: str, ip: str, user_agent: str = ""):
    row = get_or_create_attempt(db, username, ip)
    row.failed_count = 0
    row.last_failed_at = None
    row.locked_until = None
    row.updated_at = utcnow()
    audit_event(db, event_type="login_success", username=username, role=role, ip=ip, user_agent=user_agent)


def ensure_not_locked(db: Session, *, username: str, ip: str, user_agent: str = ""):
    row = (
        db.query(LoginAttempt)
        .filter(LoginAttempt.username == username, LoginAttempt.ip == ip)
        .first()
    )
    if row and is_locked(row):
        audit_event(db, event_type="login_failed", username=username, ip=ip, user_agent=user_agent, details=f"blocked_until={row.locked_until}")
        raise PermissionError(f"Cuenta temporalmente bloqueada hasta {row.locked_until} UTC")
