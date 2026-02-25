from __future__ import annotations

import os, secrets, json, time, base64, hashlib, hmac
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from jose import jwt, JWTError
from passlib.context import CryptContext

security = HTTPBasic()

# Password hashing (prefer bcrypt; keep pbkdf2 legacy verify)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_env(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or default).strip()


def get_app_secret() -> str:
    """Return APP_SECRET_KEY, enforcing presence in production.

    - In production, it MUST be set.
    - In development, it can fall back to a generated process-local key.
    """
    secret = os.getenv("APP_SECRET_KEY", "")
    env = get_env("ENV", "development").lower()
    if secret:
        return secret
    if env in ("prod", "production"):
        raise RuntimeError("APP_SECRET_KEY no configurado (obligatorio en producción).")
    # dev fallback (not stable across restarts)
    return "dev-" + secrets.token_urlsafe(32)

# ---------------------------
# Token helpers (JWT access + opaque refresh)
# ---------------------------

def sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def new_jti() -> str:
    return secrets.token_urlsafe(24)


def create_access_token(subject: str, role: str, expires_minutes: int = 60) -> str:
    secret = get_app_secret()
    now = datetime.utcnow()
    exp = now + timedelta(minutes=expires_minutes)
    payload = {"sub": subject, "role": role, "iat": int(now.timestamp()), "exp": exp, "jti": new_jti()}
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    secret = get_app_secret()
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")


def create_refresh_token_plain() -> str:
    # 256+ bits of entropy
    return secrets.token_urlsafe(48)


def refresh_token_hash(refresh_token_plain: str) -> str:
    return sha256_hex(refresh_token_plain)


# ---------------------------
# MFA (TOTP) helpers
# ---------------------------

def generate_totp_secret() -> str:
    try:
        import pyotp
        return pyotp.random_base32()
    except Exception as e:
        raise RuntimeError("pyotp no está instalado") from e


def verify_totp_code(secret_b32: str, code: str) -> bool:
    try:
        import pyotp
        totp = pyotp.TOTP(secret_b32)
        # valid_window=1 tolera un desfase de ~30s
        return bool(totp.verify(code.strip().replace(" ", ""), valid_window=1))
    except Exception:
        return False




# ---------------------------
# Legacy Basic Auth (deprecated)
# ---------------------------

def _check(user: str, pwd: str, env_user: str, env_pass: str) -> bool:
    return secrets.compare_digest(user, os.getenv(env_user, "")) and secrets.compare_digest(pwd, os.getenv(env_pass, ""))


def require_eval(credentials: HTTPBasicCredentials = Depends(security)):
    if _check(credentials.username, credentials.password, "EVAL_USER", "EVAL_PASS"):
        return {"role": "eval", "user": credentials.username}
    if _check(credentials.username, credentials.password, "COORD_USER", "COORD_PASS"):
        return {"role": "coord", "user": credentials.username}
    if _check(credentials.username, credentials.password, "ADMIN_USER", "ADMIN_PASS"):
        return {"role": "admin", "user": credentials.username}
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autorizado", headers={"WWW-Authenticate": "Basic"})


def require_coord(credentials: HTTPBasicCredentials = Depends(security)):
    if _check(credentials.username, credentials.password, "COORD_USER", "COORD_PASS"):
        return {"role": "coord", "user": credentials.username}
    if _check(credentials.username, credentials.password, "ADMIN_USER", "ADMIN_PASS"):
        return {"role": "admin", "user": credentials.username}
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autorizado", headers={"WWW-Authenticate": "Basic"})


def require_admin(credentials: HTTPBasicCredentials = Depends(security)):
    if _check(credentials.username, credentials.password, "ADMIN_USER", "ADMIN_PASS"):
        return {"role": "admin", "user": credentials.username}
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autorizado", headers={"WWW-Authenticate": "Basic"})


# ---------------------------
# Password hashing helpers
# ---------------------------

def hash_password_pbkdf2(password: str, salt: str | None = None) -> str:
    """Return a salted PBKDF2 hash in the form: pbkdf2$<salt_b64>$<hash_b64>"""
    password_b = (password or "").encode("utf-8")
    if salt is None:
        salt_bytes = secrets.token_bytes(16)
    else:
        salt_bytes = base64.urlsafe_b64decode(salt.encode("utf-8"))
    dk = hashlib.pbkdf2_hmac("sha256", password_b, salt_bytes, 120_000)
    return "pbkdf2$%s$%s" % (
        base64.urlsafe_b64encode(salt_bytes).decode("utf-8"),
        base64.urlsafe_b64encode(dk).decode("utf-8"),
    )


def verify_password_pbkdf2(password: str, stored: str) -> bool:
    try:
        algo, salt_b64, _hash_b64 = (stored or "").split("$", 2)
        if algo != "pbkdf2":
            return False
        candidate = hash_password_pbkdf2(password, salt=salt_b64)
        return secrets.compare_digest(candidate, stored)
    except Exception:
        return False


def hash_password(password: str) -> str:
    """Preferred hasher for new passwords (bcrypt)."""
    return pwd_context.hash(password or "")


def verify_password(password: str, stored: str) -> bool:
    stored = stored or ""
    if stored.startswith("pbkdf2$"):
        return verify_password_pbkdf2(password, stored)
    try:
        return pwd_context.verify(password or "", stored)
    except Exception:
        return False


# ---------------------------
# Signed cookie sessions (HMAC)
# ---------------------------

def _sign(data: bytes, secret: str) -> str:
    sig = hmac.new(secret.encode("utf-8"), data, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode("utf-8")


def create_session_token(account_id: int, username: str, role: str, teacher_id: int | None = None, ttl_seconds: int = 60*60*12) -> str:
    """Create a signed token for cookie-based sessions (admin/coord/eval/docente)."""
    secret = get_app_secret()
    payload = {
        "aid": int(account_id),
        "u": username,
        "r": role,
        "tid": int(teacher_id) if teacher_id is not None else None,
        "exp": int(time.time()) + int(ttl_seconds),
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    body = base64.urlsafe_b64encode(raw)
    sig = _sign(body, secret)
    return body.decode("utf-8") + "." + sig


def verify_session_token(token: str) -> dict | None:
    try:
        secret = get_app_secret()
        body_b64, sig = (token or "").split(".", 1)
        body = body_b64.encode("utf-8")
        if not secrets.compare_digest(_sign(body, secret), sig):
            return None
        payload = json.loads(base64.urlsafe_b64decode(body))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def require_roles(allowed_roles: list[str]):
    """Dependency factory: requires an authenticated session cookie with one of the allowed roles."""
    from fastapi import Request

    def _dep(request: Request):
        token = request.cookies.get("session", "")
        payload = verify_session_token(token)
        if not payload:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")
        role = str(payload.get("r", ""))
        if role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")
        return {
            "user": payload.get("u"),
            "role": payload.get("r"),
            "account_id": payload.get("aid"),
            "teacher_id": payload.get("tid"),
            "payload": payload,
        }

    return _dep


# ---------------------------
# CSRF tokens (stateless HMAC)
# ---------------------------

def make_csrf_token(user: str, salt: str = "", ttl_seconds: int = 60*60*12) -> str:
    secret = get_app_secret()
    payload = {"u": (user or ""), "s": (salt or ""), "exp": int(time.time()) + int(ttl_seconds)}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    body = base64.urlsafe_b64encode(raw)
    sig = _sign(body, secret)
    return body.decode("utf-8") + "." + sig


def verify_csrf_token(token: str, user: str, salt: str = "") -> bool:
    try:
        secret = get_app_secret()
        body_b64, sig = (token or "").split(".", 1)
        body = body_b64.encode("utf-8")
        if not secrets.compare_digest(_sign(body, secret), sig):
            return False
        payload = json.loads(base64.urlsafe_b64decode(body))
        if int(payload.get("exp", 0)) < int(time.time()):
            return False
        if (payload.get("u") or "") != (user or ""):
            return False
        if (payload.get("s") or "") != (salt or ""):
            return False
        return True
    except Exception:
        return False


        raise HTTPException(status_code=401, detail="Token inválido o expirado") from e
