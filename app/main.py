import io
import os
from datetime import datetime
from pathlib import Path
from fastapi import Request
from starlette.requests import Request

from fastapi import FastAPI, Depends, Request, Form, HTTPException
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse, Response, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, desc
import qrcode
from openpyxl import Workbook
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from .logging_setup import setup_json_logging, AccessLogMiddleware

# ✅ Cargar .env (recomendado)
try:
    from dotenv import load_dotenv
    if os.getenv("ENV","development").lower() not in ("prod","production"):
        load_dotenv()
except Exception:
    pass

from .db import Base, engine, get_db, SessionLocal
from sqlalchemy import text, inspect

from .models import Rating, Rotation, RatingAudit, Student, MonthControl, AdminAudit, Teacher, StudentTeacher, Account
from .schemas import RatingCreate, RatingOut
from .security import hash_password, verify_password, create_session_token, verify_session_token, require_roles, make_csrf_token, verify_csrf_token, get_app_secret
from .auth_utils import get_client_ip, ensure_not_locked, register_failed_login, register_success_login
from .api_auth import router as api_auth_router
from .utils import (
    public_base_url,
    build_form_url,
    build_whatsapp_url,
    numero_a_letras_nota,
    render_rating_pdf,
)

setup_json_logging()

app = FastAPI(title="Calificación Internado Médico (DS-F-01) v3")

# Logging estructurado (JSON) + correlación X-Request-ID
setup_json_logging()
app.add_middleware(AccessLogMiddleware)



# -------------------- Rate limiting (SlowAPI) --------------------
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return PlainTextResponse("Demasiadas solicitudes. Intenta de nuevo más tarde.", status_code=429)

app.add_middleware(SlowAPIMiddleware)


@app.middleware("http")
async def secure_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Basic CSP for templates/static served from same origin
    response.headers["Content-Security-Policy"] = "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; form-action 'self'"
    return response

os.makedirs("data", exist_ok=True)
# NOTE: DB schema is managed by Alembic in production.
# For local dev you can set ENV=development to allow create_all.
if os.getenv("ENV", "development").lower() not in ("prod", "production"):
    Base.metadata.create_all(bind=engine)


def ensure_schema(db: Session):
    """Mini-migración automática (solo para SQLite).

    Este proyecto usa `create_all()` para crear tablas, pero SQLite no actualiza
    columnas nuevas automáticamente. Aquí garantizamos (sin romper BD existente):
    - Tablas nuevas: students, month_control, admin_audit, teachers, student_teachers
    - Columnas nuevas: ratings.year, ratings.especialista_documento
    """

    if not str(engine.url).startswith("sqlite"):
        return

    insp = inspect(engine)
    tables = set(insp.get_table_names())

    # ✅ Crear tablas nuevas (idempotente)
    required = {"students", "month_control", "admin_audit", "teachers", "student_teachers"}
    if not required.issubset(tables):
        Base.metadata.create_all(bind=engine)
        tables = set(inspect(engine).get_table_names())

    # ✅ Migraciones de columnas en ratings
    if "ratings" in tables:
        cols = {c["name"] for c in insp.get_columns("ratings")}

        if "year" not in cols:
            db.execute(text("ALTER TABLE ratings ADD COLUMN year INTEGER"))
            db.execute(text("UPDATE ratings SET year = CAST(strftime('%Y', created_at) AS INTEGER) WHERE year IS NULL"))
            db.commit()
            # refrescar
            insp = inspect(engine)
            cols = {c["name"] for c in insp.get_columns("ratings")}

        if "especialista_documento" not in cols:
            db.execute(text("ALTER TABLE ratings ADD COLUMN especialista_documento VARCHAR(50) DEFAULT ''"))
            db.execute(text("UPDATE ratings SET especialista_documento = '' WHERE especialista_documento IS NULL"))
            db.commit()



        # ✅ Columna nueva: ratings.actor (quién registró la nota)
        if "actor" not in cols:
            db.execute(text("ALTER TABLE ratings ADD COLUMN actor VARCHAR(100) DEFAULT ''"))
            db.execute(text("UPDATE ratings SET actor = '' WHERE actor IS NULL"))
            db.commit()
        # ✅ Reapertura por ADMIN (corrección de notas)
        if "reopen_count" not in cols:
            db.execute(text("ALTER TABLE ratings ADD COLUMN reopen_count INTEGER DEFAULT 0"))
            db.execute(text("UPDATE ratings SET reopen_count = 0 WHERE reopen_count IS NULL"))
            db.commit()
            insp = inspect(engine)
            cols = {c["name"] for c in insp.get_columns("ratings")}

        if "reopen_reason" not in cols:
            db.execute(text("ALTER TABLE ratings ADD COLUMN reopen_reason VARCHAR(300) DEFAULT ''"))
            db.execute(text("UPDATE ratings SET reopen_reason = '' WHERE reopen_reason IS NULL"))
            db.commit()

        if "reopened_by" not in cols:
            db.execute(text("ALTER TABLE ratings ADD COLUMN reopened_by VARCHAR(100) DEFAULT ''"))
            db.execute(text("UPDATE ratings SET reopened_by = '' WHERE reopened_by IS NULL"))
            db.commit()

        if "reopened_at" not in cols:
            db.execute(text("ALTER TABLE ratings ADD COLUMN reopened_at DATETIME"))
            db.commit()


    # ✅ Migraciones de columnas en teachers (portal docente)
    if "teachers" in tables:
        teacher_cols = {c["name"] for c in insp.get_columns("teachers")}
        # columnas base
        if "documento" not in teacher_cols:
            db.execute(text("ALTER TABLE teachers ADD COLUMN documento VARCHAR(50)"))
            db.commit()
        if "nombre" not in teacher_cols:
            db.execute(text("ALTER TABLE teachers ADD COLUMN nombre VARCHAR(200) DEFAULT ''"))
            db.commit()
        if "especialidad" not in teacher_cols:
            db.execute(text("ALTER TABLE teachers ADD COLUMN especialidad VARCHAR(200) DEFAULT ''"))
            db.commit()
        if "activo" not in teacher_cols:
            db.execute(text("ALTER TABLE teachers ADD COLUMN activo BOOLEAN DEFAULT 1"))
            db.commit()
        if "created_at" not in teacher_cols:
            db.execute(text("ALTER TABLE teachers ADD COLUMN created_at DATETIME"))
            db.commit()
        # credenciales / PIN (guardado en password_hash)
        if "username" not in teacher_cols:
            db.execute(text("ALTER TABLE teachers ADD COLUMN username VARCHAR(120)"))
            db.commit()
        if "password_hash" not in teacher_cols:
            db.execute(text("ALTER TABLE teachers ADD COLUMN password_hash VARCHAR(300) DEFAULT ''"))
            db.commit()

    # ✅ Migraciones de columnas en student_teachers (asignaciones)
    if "student_teachers" in tables:
        st_cols = {c["name"] for c in insp.get_columns("student_teachers")}
        # columnas nuevas idempotentes
        if "student_id" not in st_cols:
            db.execute(text("ALTER TABLE student_teachers ADD COLUMN student_id INTEGER"))
            db.commit()
        if "teacher_id" not in st_cols:
            db.execute(text("ALTER TABLE student_teachers ADD COLUMN teacher_id INTEGER"))
            db.commit()
        if "rotation_id" not in st_cols:
            db.execute(text("ALTER TABLE student_teachers ADD COLUMN rotation_id INTEGER"))
            db.commit()
        if "created_at" not in st_cols:
            db.execute(text("ALTER TABLE student_teachers ADD COLUMN created_at DATETIME"))
            db.commit()

        # Backfill si existen columnas antiguas (documentos) — sin romper si no existen
        insp2 = inspect(engine)
        st_cols = {c["name"] for c in insp2.get_columns("student_teachers")}
        legacy_student = next((c for c in ["student_documento","estudiante_documento","student_doc","doc_estudiante"] if c in st_cols), None)
        legacy_teacher = next((c for c in ["teacher_documento","docente_documento","teacher_doc","doc_docente"] if c in st_cols), None)

        if legacy_student and "student_id" in st_cols:
            # llenar student_id uniendo por documento
            db.execute(text(f"""
                UPDATE student_teachers
                SET student_id = (SELECT id FROM students s WHERE s.documento = student_teachers.{legacy_student})
                WHERE (student_id IS NULL OR student_id = 0) AND {legacy_student} IS NOT NULL AND {legacy_student} <> ''
            """))
            db.commit()

        if legacy_teacher and "teacher_id" in st_cols:
            db.execute(text(f"""
                UPDATE student_teachers
                SET teacher_id = (SELECT id FROM teachers t WHERE t.documento = student_teachers.{legacy_teacher})
                WHERE (teacher_id IS NULL OR teacher_id = 0) AND {legacy_teacher} IS NOT NULL AND {legacy_teacher} <> ''
            """))
            db.commit()



# ✅ STATIC robusto
BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app.include_router(api_auth_router)

# -------------------- CSRF helpers (ADMIN forms) --------------------
def _csrf_for(request: Request, auth_user: str) -> str:
    # Usamos el path como 'salt' para que el token no sirva en otro endpoint.
    return make_csrf_token(auth_user, salt=str(request.url.path))

def _verify_csrf_or_400(token: str, request: Request, auth_user: str):
    if not verify_csrf_token(token or "", auth_user, salt=str(request.url.path)):
        raise HTTPException(status_code=400, detail="Solicitud inválida (CSRF). Refresca la página e inténtalo de nuevo.")

# -------------------- Rate limit login docente --------------------
# In-memory (reinicia al reiniciar el servidor). Suficiente para entorno LAN.
LOGIN_ATTEMPTS = {}  # ip -> {"count": int, "reset": epoch}
LOGIN_WINDOW_SECONDS = 10 * 60
LOGIN_MAX_ATTEMPTS = 8

SESSION_COOKIE_NAME = "session"

def get_current_session_payload(request: Request) -> dict:
    token = request.cookies.get(SESSION_COOKIE_NAME, "")
    payload = verify_session_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Sesión no válida")
    return payload

def get_current_teacher(request: Request, db: Session) -> Teacher:
    payload = get_current_session_payload(request)
    if str(payload.get("r", "")) != "docente":
        raise HTTPException(status_code=403, detail="Acceso solo para Docente")
    tid = payload.get("tid", None)
    if tid is None:
        raise HTTPException(status_code=401, detail="Sesión docente inválida")
    teacher = db.query(Teacher).filter(Teacher.id == int(tid), Teacher.activo == True).first()
    if not teacher:
        raise HTTPException(status_code=401, detail="Docente no válido o inactivo")
    return teacher

def require_teacher(request: Request, db: Session = Depends(get_db)) -> Teacher:
    return get_current_teacher(request, db)



# -------------------- Helpers --------------------

MONTHS_ES = {
    1: "Enero",
    2: "Febrero",
    3: "Marzo",
    4: "Abril",
    5: "Mayo",
    6: "Junio",
    7: "Julio",
    8: "Agosto",
    9: "Septiembre",
    10: "Octubre",
    11: "Noviembre",
    12: "Diciembre",
}


def teacher_identifier(teacher: 'Teacher') -> str:
    """Identificador estable del docente para cruces y auditoría.

    Preferimos documento; si no existe, usamos username (PIN login).
    """
    doc = (getattr(teacher, 'documento', '') or '').strip()
    if doc:
        return doc
    return (getattr(teacher, 'username', '') or '').strip()


def now_year_month() -> tuple[int, str]:
    dt = datetime.now()
    return dt.year, MONTHS_ES.get(dt.month, "")

def normalize_mes(mes: str) -> str:
    m = (mes or "").strip().lower()
    mapa = {
        "enero": "Enero",
        "febrero": "Febrero",
        "marzo": "Marzo",
        "abril": "Abril",
        "mayo": "Mayo",
        "junio": "Junio",
        "julio": "Julio",
        "agosto": "Agosto",
        "septiembre": "Septiembre",
        "setiembre": "Septiembre",
        "octubre": "Octubre",
        "noviembre": "Noviembre",
        "diciembre": "Diciembre",
    }
    return mapa.get(m, (mes or "").strip().title())


def is_month_open(db: Session, rotation_id: int, year: int, mes: str) -> bool:
    """True si el mes está abierto (o no está configurado) para esa rotación."""
    mes_norm = normalize_mes(mes)
    mc = (
        db.query(MonthControl)
        .filter(MonthControl.rotation_id == rotation_id, MonthControl.year == year, MonthControl.mes == mes_norm)
        .first()
    )
    # Si no hay configuración, asumimos ABIERTO (por defecto).
    if not mc:
        return True
    return not bool(mc.is_closed)





@app.on_event("startup")
def _startup_migrations():
    # Ejecutar migraciones SQLite una sola vez para evitar locks por múltiples requests.
    db = SessionLocal()
    try:
        ensure_schema(db)
    finally:
        db.close()

def seed_rotations(db: Session):
    # ensure_schema() se ejecuta en startup
    if db.query(Rotation).count() == 0:
        for name in ["Urgencias", "Hospitalización", "UCI", "Cirugía", "Imágenes", "Laboratorio"]:
            db.add(Rotation(nombre=name, activa=True))
        db.commit()


def ensure_default_accounts(db: Session):
    """Crea cuentas iniciales si la BD está vacía.

    En producción (Hostinger/VPS), configura variables:
    - INIT_ADMIN_USER / INIT_ADMIN_PASS
    - INIT_COORD_USER / INIT_COORD_PASS (opcional)
    """
    if db.query(Account).count() > 0:
        return

    admin_user = (os.getenv("INIT_ADMIN_USER", "admin") or "admin").strip()
    env = (os.getenv("ENV", "development") or "development").lower()
    admin_pass_env = (os.getenv("INIT_ADMIN_PASS", "") or "").strip()
    if env in ("prod","production") and not admin_pass_env:
        raise RuntimeError("INIT_ADMIN_PASS es obligatorio en producción si la BD está vacía.")
    admin_pass = (admin_pass_env or "Admin123*").strip()

    db.add(Account(
        username=admin_user,
        password_hash=hash_password(admin_pass),
        role="admin",
        teacher_id=None,
        activo=True,
    ))

    coord_user = (os.getenv("INIT_COORD_USER", "") or "").strip()
    coord_pass = (os.getenv("INIT_COORD_PASS", "") or "").strip()
    if coord_user and coord_pass:
        db.add(Account(
            username=coord_user,
            password_hash=hash_password(coord_pass),
            role="coord",
            teacher_id=None,
            activo=True,
        ))

    db.commit()





def calcular_nota(payload: RatingCreate) -> tuple[float, int]:
    pierde = 1 if payload.porcentaje_fallas > 10.0 else 0
    if pierde:
        return 0.0, pierde
    suma = payload.cognitiva + payload.aptitudinal + payload.actitudinal + payload.evaluacion + payload.cpc
    return round(suma * 0.2, 2), pierde


def add_audit(db: Session, rating_id: int, action: str, actor: str, details: str = ""):
    db.add(RatingAudit(rating_id=rating_id, action=action, actor=actor, details=details))
    db.commit()


def add_admin_audit(db: Session, module: str, action: str, actor: str, details: str = ""):
    db.add(AdminAudit(module=module, action=action, actor=actor, details=details))
    db.commit()


def auto_close_if_complete(db: Session, student: Student, rotation_id: int, year: int, mes: str, actor: str):
    """Cierra automáticamente la rotación (registro de calificación) cuando TODOS los docentes asignados ya evaluaron.

    - Asignados: student_teachers (Teacher.activo=True) por estudiante y rotación
    - Evaluados: ratings (is_void=False) del mismo (estudiante_documento, rotation_id, year, mes)
      y docente (especialista_documento) dentro de los asignados.

    Si está completo: marca is_closed=True en TODOS los ratings de ese estudiante/rotación/mes/año.
    """
    mes = (mes or "").strip()
    if not mes:
        return

    ass = (
        db.query(StudentTeacher, Teacher)
        .join(Teacher, StudentTeacher.teacher_id == Teacher.id)
        .filter(
            StudentTeacher.student_id == student.id,
            StudentTeacher.rotation_id == rotation_id,
            Teacher.activo == True,
        )
        .all()
    )
    assigned_docs = [(t.documento or "").strip() for _, t in ass if (t.documento or "").strip()]
    assigned_count = len(assigned_docs)

    if assigned_count == 0:
        return

    rated = (
        db.query(Rating)
        .filter(
            Rating.estudiante_documento == student.documento,
            Rating.rotation_id == rotation_id,
            Rating.year == year,
            Rating.mes == mes,
            Rating.is_void == False,
            Rating.especialista_documento.in_(assigned_docs),
        )
        .all()
    )

    if len(rated) < assigned_count:
        return

    # ✅ Completo => cerrar todos
    changed_any = False
    for r in rated:
        if not r.is_closed:
            r.is_closed = True
            r.updated_at = func.now()
            changed_any = True

    if not changed_any:
        return

    # Auditoría en una sola transacción
    details = f"AUTO_CLOSE estudiante={student.documento} rotation_id={rotation_id} year={year} mes={mes}"
    for r in rated:
        db.add(RatingAudit(rating_id=r.id, action="AUTO_CLOSE", actor=actor, details=details))

    db.commit()


def query_ratings(
    db: Session,
    q: str = "",
    rotation_id: int | None = None,
    mes: str = "",
    status: str = "",
    limit: int = 50,
    offset: int = 0,
):
    qry = db.query(Rating).join(Rotation, Rating.rotation_id == Rotation.id)

    if q:
        like = f"%{q.strip()}%"
        qry = qry.filter(
            or_(
                Rating.estudiante_nombre.ilike(like),
                Rating.estudiante_documento.ilike(like),
                Rating.universidad.ilike(like),
                Rating.especialista_nombre.ilike(like),
                Rating.especialista_documento.ilike(like),
            )
        )

    if rotation_id:
        qry = qry.filter(Rating.rotation_id == rotation_id)

    if mes:
        qry = qry.filter(Rating.mes == mes)

    if status == "abierto":
        qry = qry.filter(Rating.is_void == False, Rating.is_closed == False)
    elif status == "cerrado":
        qry = qry.filter(Rating.is_void == False, Rating.is_closed == True)
    elif status == "anulado":
        qry = qry.filter(Rating.is_void == True)

    total = qry.count()
    items = qry.order_by(desc(Rating.created_at)).limit(limit).offset(offset).all()
    return total, items


def parse_rotation_id(rotation_id) -> int | None:
    """Parse rotation_id safely from query params.

    Browsers submit empty select values as an empty string (rotation_id=).
    Some links also include rotation_id='' for convenience. If we type
    endpoints as int, FastAPI raises 422. This helper coerces values safely.
    """
    if rotation_id is None:
        return None

    # Already an int
    if isinstance(rotation_id, int):
        return rotation_id

    raw = str(rotation_id).strip()
    if not raw:
        return None

    try:
        return int(raw)
    except ValueError:
        return None


@app.get("/", response_class=HTMLResponse)
def root():
    return RedirectResponse(url="/login", status_code=302)

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    ensure_default_accounts(db)
    return templates.TemplateResponse(
        "auth/login.html",
        {"request": request, "csrf_token": make_csrf_token("login", salt=str(request.url.path)), "error": ""},
    )

@app.post("/login")
@limiter.limit("10/minute")
def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    otp: str = Form(""),
    role_hint: str = Form(""),
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    if not verify_csrf_token(csrf_token, "login", salt=str(request.url.path)):
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "csrf_token": make_csrf_token("login", salt=str(request.url.path)), "error": "Solicitud inválida (CSRF). Refresca la página e inténtalo de nuevo."},
            status_code=400,
        )
    u = (username or "").strip()
    p = (password or "").strip()

    ip = get_client_ip(request)
    ua = request.headers.get("user-agent", "")
    try:
        ensure_not_locked(db, username=u, ip=ip, user_agent=ua)
    except PermissionError as e:
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "csrf_token": make_csrf_token("login", salt=str(request.url.path)), "error": str(e)},
            status_code=429,
        )

    acct = db.query(Account).filter(Account.username == u).first()
    if not acct or not acct.activo:
        delay, locked_until = register_failed_login(db, username=u, ip=ip, user_agent=ua)
        db.commit()
        if delay:
            import time
            time.sleep(delay)
        if locked_until:
            return templates.TemplateResponse(
                "auth/login.html",
                {"request": request, "csrf_token": make_csrf_token("login", salt=str(request.url.path)), "error": f"Cuenta bloqueada hasta {locked_until} UTC"},
                status_code=429,
            )
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "csrf_token": make_csrf_token("login", salt=str(request.url.path)), "error": "Usuario o contraseña inválidos."},
            status_code=401,
        )
    if not verify_password(p, acct.password_hash):
        delay, locked_until = register_failed_login(db, username=u, ip=ip, user_agent=ua)
        db.commit()
        if delay:
            import time
            time.sleep(delay)
        if locked_until:
            return templates.TemplateResponse(
                "auth/login.html",
                {"request": request, "csrf_token": make_csrf_token("login", salt=str(request.url.path)), "error": f"Cuenta bloqueada hasta {locked_until} UTC"},
                status_code=429,
            )
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "csrf_token": make_csrf_token("login", salt=str(request.url.path)), "error": "Usuario o contraseña inválidos."},
            status_code=401,
        )

    # (Opcional) Si el usuario eligió un rol en la UI, validarlo para evitar confusiones.
    rh = (role_hint or "").strip().lower()
    if rh in ("admin", "docente"):
        if rh == "admin" and acct.role not in ("admin", "coord", "eval"):
            return templates.TemplateResponse(
                "auth/login.html",
                {"request": request, "csrf_token": make_csrf_token("login", salt=str(request.url.path)), "error": "Tu cuenta no tiene rol Administrador."},
                status_code=403,
            )
        if rh == "docente" and acct.role in ("admin", "coord", "eval"):
            return templates.TemplateResponse(
                "auth/login.html",
                {"request": request, "csrf_token": make_csrf_token("login", salt=str(request.url.path)), "error": "Tu cuenta no es de Docente."},
                status_code=403,
            )

    # MFA (TOTP) opcional para admin
    if acct.role == "admin" and getattr(acct, "mfa_enabled", False):
        code = (otp or "").strip()
        if not code:
            register_failed_login(db, username=u, ip=ip, user_agent=ua)
            log_auth_event(db, "mfa_required", username=u, role=acct.role, ip=ip, user_agent=ua)
            db.commit()
            return templates.TemplateResponse(
                "auth/login.html",
                {"request": request, "csrf_token": make_csrf_token("login", salt=str(request.url.path)), "error": "OTP requerido (MFA)."},
                status_code=401,
            )
        if (not acct.mfa_secret) or (not verify_totp_code(acct.mfa_secret, code)):
            delay, locked_until = register_failed_login(db, username=u, ip=ip, user_agent=ua)
            log_auth_event(db, "mfa_failed", username=u, role=acct.role, ip=ip, user_agent=ua)
            db.commit()
            if delay:
                import time
                time.sleep(delay)
            if locked_until:
                return templates.TemplateResponse(
                    "auth/login.html",
                    {"request": request, "csrf_token": make_csrf_token("login", salt=str(request.url.path)), "error": f"Cuenta bloqueada hasta {locked_until} UTC"},
                    status_code=429,
                )
            return templates.TemplateResponse(
                "auth/login.html",
                {"request": request, "csrf_token": make_csrf_token("login", salt=str(request.url.path)), "error": "OTP inválido."},
                status_code=401,
            )
    
    register_success_login(db, username=u, role=acct.role, ip=ip, user_agent=ua)

    db.commit()

    token = create_session_token(acct.id, acct.username, acct.role, teacher_id=acct.teacher_id)
    # Redirección por rol
    if acct.role in ("admin", "coord", "eval"):
        resp = RedirectResponse(url="/admin", status_code=302)
    else:
        resp = RedirectResponse(url="/profesor", status_code=302)

    secure_cookie = (os.getenv("ENV", "development").lower() in ("prod", "production"))
    resp.set_cookie("session", token, httponly=True, samesite="lax", secure=secure_cookie)
    return resp

@app.get("/logout")
def logout():
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie("session")
    return resp



# -------------------- Portal Docente --------------------

@app.get("/profesor/login", response_class=HTMLResponse)
def profesor_login_page():
    return RedirectResponse(url="/login", status_code=302)

@app.post("/profesor/login")
def profesor_login():
    return RedirectResponse(url="/login", status_code=302)

@app.get("/profesor/logout")
def profesor_logout():
    return RedirectResponse(url="/logout", status_code=302)

@app.get("/profesor", response_class=HTMLResponse)
def profesor_dashboard(
    request: Request,
    mes: str = "",
    rotation_id: int = 0,
    teacher: Teacher = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    seed_rotations(db)
    year_now, mes_now = now_year_month()
    mes_sel = normalize_mes((mes or mes_now).strip() or mes_now)

    # Identificador estable del docente para cruces (documento o username/PIN)
    tid = teacher_identifier(teacher)

    rot_rows = (
        db.query(Rotation)
        .join(StudentTeacher, StudentTeacher.rotation_id == Rotation.id)
        .filter(StudentTeacher.teacher_id == teacher.id)
        .distinct()
        .order_by(Rotation.nombre.asc())
        .all()
    )
    rot_filter = rotation_id or (rot_rows[0].id if rot_rows else 0)

    q = (
        db.query(StudentTeacher, Student, Rotation)
        .join(Student, StudentTeacher.student_id == Student.id)
        .join(Rotation, StudentTeacher.rotation_id == Rotation.id)
        .filter(StudentTeacher.teacher_id == teacher.id)
    )
    if rot_filter:
        q = q.filter(StudentTeacher.rotation_id == rot_filter)

    assignments = q.order_by(Student.nombre.asc()).all()

    rows = []
    pending_simple = 0
    for stt, st, rot in assignments:
        my_done = db.query(Rating).filter(
            Rating.estudiante_documento == st.documento,
            Rating.rotation_id == rot.id,
            Rating.year == year_now,
            Rating.mes == mes_sel,
            Rating.is_void == False,
            Rating.especialista_documento == tid,
        ).first()

        assigned_ids = [r.teacher_id for r in db.query(StudentTeacher).filter(StudentTeacher.student_id == st.id, StudentTeacher.rotation_id == rot.id).all()]
        assigned_count = len(set(assigned_ids))

        evaluated_docs = [
            r.especialista_documento
            for r in db.query(Rating).filter(
                Rating.estudiante_documento == st.documento,
                Rating.rotation_id == rot.id,
                Rating.year == year_now,
                Rating.mes == mes_sel,
                Rating.is_void == False,
            ).all()
        ]
        evaluated_count = len(set([d for d in evaluated_docs if d]))
        completo = (assigned_count > 0 and evaluated_count >= assigned_count)

        rows.append({
            "student": st,
            "rotation": rot,
            "mes": mes_sel,
            "my_done": bool(my_done),
            "completo": completo,
            "can_create": is_month_open(db, rot.id, year_now, mes_sel),
        })
        if not my_done:
            pending_simple += 1

    # Actividad reciente del docente (últimas calificaciones emitidas)
    recent_my = []
    try:
        last = (
            db.query(Rating)
            .filter(Rating.especialista_documento == tid, Rating.is_void == False)
            .order_by(Rating.created_at.desc())
            .limit(6)
            .all()
        )
        for r in last:
            recent_my.append({
                "time": r.created_at.strftime('%d %b %H:%M') if r.created_at else "",
                "title": f"Calificaste a {r.estudiante_nombre}",
                "sub": f"{r.mes} · {r.rotation.nombre if r.rotation else ''} · Nota {r.nota_definitiva:.1f}",
            })
    except Exception:
        recent_my = []

    return templates.TemplateResponse(
        "profesor/dashboard.html",
        {
            "request": request,
            "teacher": teacher,
            "rows": rows,
            "mes": mes_sel,
            "year": year_now,
            "rotations": rot_rows,
            "rotation_id": rot_filter,
            "kpi_total": len(rows),
            "kpi_pending": pending_simple,
            "kpi_done": max(0, len(rows) - pending_simple),
            "recent_my": recent_my,
            "title": "Portal Docente",
        },
    )

@app.get("/profesor/calificar", response_class=HTMLResponse)
def profesor_calificar_page(
    request: Request,
    student_id: int,
    rotation_id: int,
    mes: str = "",
    saved: int = 0,
    teacher: Teacher = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    year_now, mes_now = now_year_month()
    mes_sel = (mes or mes_now).strip() or mes_now
    tid = teacher_identifier(teacher)

    st = db.query(Student).filter(Student.id == student_id, Student.activa == True).first()
    rot = db.query(Rotation).filter(Rotation.id == rotation_id, Rotation.activa == True).first()
    if not st or not rot:
        raise HTTPException(status_code=404, detail="Estudiante o rotación inválidos")

    assigned = db.query(StudentTeacher).filter(
        StudentTeacher.student_id == st.id,
        StudentTeacher.teacher_id == teacher.id,
        StudentTeacher.rotation_id == rot.id,
    ).first()
    if not assigned:
        raise HTTPException(status_code=403, detail="No tienes asignación para este estudiante/rotación")

    dup = db.query(Rating).filter(
        Rating.estudiante_documento == st.documento,
        Rating.rotation_id == rot.id,
        Rating.year == year_now,
        Rating.mes == mes_sel,
        Rating.is_void == False,
        Rating.especialista_documento == tid,
    ).first()
    already_done = bool(dup)

    return templates.TemplateResponse(
        "profesor/rate.html",
        {
            "request": request,
            "csrf_token": make_csrf_token(tid, salt="/profesor/ratings/create"),
            "teacher": teacher,
            "student": st,
            "rotation": rot,
            "mes": mes_sel,
            "year": year_now,
            "already_done": already_done,
            "rating": dup,
            "saved": bool(saved),
        },
    )


@app.get("/profesor/api/ratings/detail")
def profesor_rating_detail(
    student_id: int,
    rotation_id: int,
    mes: str,
    teacher: Teacher = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """Devuelve el detalle de la calificación del docente (modo 'Ver' en dashboard)."""
    year_now, mes_now = now_year_month()
    mes_sel = (mes or mes_now).strip() or mes_now

    tid = teacher_identifier(teacher)

    st = db.query(Student).filter(Student.id == student_id, Student.activa == True).first()
    rot = db.query(Rotation).filter(Rotation.id == rotation_id, Rotation.activa == True).first()
    if not st or not rot:
        raise HTTPException(status_code=404, detail="Estudiante o rotación inválidos")

    assigned = db.query(StudentTeacher).filter(
        StudentTeacher.student_id == st.id,
        StudentTeacher.teacher_id == teacher.id,
        StudentTeacher.rotation_id == rot.id,
    ).first()
    if not assigned:
        raise HTTPException(status_code=403, detail="No tienes asignación para este estudiante/rotación")

    r = db.query(Rating).filter(
        Rating.estudiante_documento == st.documento,
        Rating.rotation_id == rot.id,
        Rating.year == year_now,
        Rating.mes == mes_sel,
        Rating.is_void == False,
        Rating.especialista_documento == tid,
    ).first()
    if not r:
        raise HTTPException(status_code=404, detail="No existe calificación registrada")

    try:
        pct = float((getattr(r, 'pct_fallas', None) if hasattr(r, 'pct_fallas') else None) or getattr(r, 'porcentaje_fallas', 0) or 0)
    except Exception:
        pct = 0.0

    if pct > 10:
        regla = "Fallas > 10% ⇒ la nota final queda en 0.00"
    else:
        regla = "Sin penalización por fallas (≤ 10%)"

    def fmt(x):
        try:
            return round(float(x), 2)
        except Exception:
            return None

    return {
        "student_name": st.nombre,
        "student_document": st.documento,
        "rotation": rot.nombre,
        "mes": mes_sel,
        "year": year_now,
        "cognitiva": fmt(r.cognitiva),
        "aptitudinal": fmt(r.aptitudinal),
        "actitudinal": fmt(r.actitudinal),
        "evaluacion": fmt(r.evaluacion),
        "cpc": fmt(r.cpc),
        "pct_fallas": fmt(pct),
        "regla_fallas": regla,
        "nota_definitiva": fmt(r.nota_definitiva),
        "comentarios": (r.comentarios or "").strip(),
        "created_at_local": (r.created_at.strftime("%Y-%m-%d %H:%M") if getattr(r, "created_at", None) else ""),
        "teacher_name": teacher.nombre,
    }


@app.get("/profesor/ratings/receipt.pdf")
def profesor_rating_receipt_pdf(
    student_id: int,
    rotation_id: int,
    mes: str,
    teacher: Teacher = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """PDF mini de comprobante de calificación del docente (solo su evaluación)."""
    year_now, mes_now = now_year_month()
    mes_sel = (mes or mes_now).strip() or mes_now

    tid = teacher_identifier(teacher)

    st = db.query(Student).filter(Student.id == student_id, Student.activa == True).first()
    rot = db.query(Rotation).filter(Rotation.id == rotation_id, Rotation.activa == True).first()
    if not st or not rot:
        raise HTTPException(status_code=404, detail="Estudiante o rotación inválidos")

    assigned = db.query(StudentTeacher).filter(
        StudentTeacher.student_id == st.id,
        StudentTeacher.teacher_id == teacher.id,
        StudentTeacher.rotation_id == rot.id,
    ).first()
    if not assigned:
        raise HTTPException(status_code=403, detail="No tienes asignación para este estudiante/rotación")

    r = db.query(Rating).filter(
        Rating.estudiante_documento == st.documento,
        Rating.rotation_id == rot.id,
        Rating.year == year_now,
        Rating.mes == mes_sel,
        Rating.is_void == False,
        Rating.especialista_documento == tid,
    ).first()
    if not r:
        raise HTTPException(status_code=404, detail="No existe calificación registrada")

    # PDF simple (ReportLab)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter

    y = height - 50
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, "Comprobante de Calificación (Docente)")
    y -= 18
    c.setFont("Helvetica", 10)
    c.drawString(50, y, f"DS-F-01 · Año {r.year} · Mes {r.mes}")
    y -= 20

    c.setFont("Helvetica-Bold", 11)
    c.drawString(50, y, "Docente:")
    c.setFont("Helvetica", 11)
    c.drawString(120, y, f"{teacher.nombre} ({teacher.documento})")
    y -= 16

    c.setFont("Helvetica-Bold", 11)
    c.drawString(50, y, "Estudiante:")
    c.setFont("Helvetica", 11)
    c.drawString(120, y, f"{st.nombre} ({st.documento})")
    y -= 16

    c.setFont("Helvetica-Bold", 11)
    c.drawString(50, y, "Rotación:")
    c.setFont("Helvetica", 11)
    c.drawString(120, y, rot.nombre)
    y -= 22

    def row(label, value):
        nonlocal y
        c.setFont("Helvetica", 10)
        c.drawString(60, y, label)
        c.drawRightString(width - 60, y, value)
        y -= 14

    row("Área cognitiva (20%)", f"{float(r.cognitiva):.2f}")
    row("Área aptitudinal (20%)", f"{float(r.aptitudinal):.2f}")
    row("Área actitudinal (20%)", f"{float(r.actitudinal):.2f}")
    row("Evaluación (20%)", f"{float(r.evaluacion):.2f}")
    row("Participación CPC (20%)", f"{float(r.cpc):.2f}")
    y -= 6

    pct = float(getattr(r, "pct_fallas", getattr(r, "porcentaje_fallas", 0.0)) or 0.0)
    row("% fallas", f"{pct:.2f}%")

    nota = float(r.nota_definitiva or 0.0)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(60, y, "Nota definitiva:")
    c.drawRightString(width - 60, y, f"{nota:.2f}")
    y -= 18

    c.setFont("Helvetica", 9)
    created = getattr(r, "created_at", None)
    if created:
        c.drawString(60, y, f"Registrado: {created.strftime('%Y-%m-%d %H:%M')} (hora local)")
        y -= 12

    c.setFont("Helvetica-Oblique", 9)
    c.drawString(60, 40, "Elaborado por Eneldo Vanstralhen · Ingeniero de Sistemas")

    c.showPage()
    c.save()
    buf.seek(0)

    filename = f"comprobante_{st.documento}_{rot.id}_{r.mes}_{teacher.documento}.pdf"
    headers = {"Content-Disposition": f'inline; filename="{filename}"'}
    return StreamingResponse(buf, media_type="application/pdf", headers=headers)



@app.post("/profesor/ratings/create")
def profesor_create_rating(
    request: Request,
    csrf_token: str = Form(""),
    student_id: int = Form(...),
    rotation_id: int = Form(...),
    mes: str = Form(...),
    universidad: str = Form(""),
    semestre: str = Form(""),
    cognitiva: float = Form(...),
    aptitudinal: float = Form(...),
    actitudinal: float = Form(...),
    evaluacion: float = Form(...),
    cpc: float = Form(...),
    porcentaje_fallas: float = Form(0.0),
    coordinador_nombre: str = Form("N/A"),
    estudiante_firma_nombre: str = Form("N/A"),
    comentarios: str = Form(""),
    teacher: Teacher = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    tid = teacher_identifier(teacher)
    _verify_csrf_or_400(csrf_token, request, tid)
    year_now, _ = now_year_month()
    mes_sel = (mes or "").strip()

    # Validación defensiva (evita 500 si el navegador permite valores fuera de rango)
    campos_notas = {
        "Área cognitiva": cognitiva,
        "Área aptitudinal": aptitudinal,
        "Área actitudinal": actitudinal,
        "Evaluación": evaluacion,
        "Participación CPC": cpc,
    }
    for label, val in campos_notas.items():
        try:
            v = float(val)
        except Exception:
            v = None
        if v is None or v < 0 or v > 5:
            # Re-render del formulario con mensaje amigable
            st_tmp = db.query(Student).filter(Student.id == student_id, Student.activa == True).first()
            rot_tmp = db.query(Rotation).filter(Rotation.id == rotation_id, Rotation.activa == True).first()
            return templates.TemplateResponse(
                "profesor/rate.html",
                {
                    "request": request,
                    "csrf_token": make_csrf_token(tid, salt="/profesor/ratings/create"),
                    "teacher": teacher,
                    "student": st_tmp,
                    "rotation": rot_tmp,
                    "mes": mes_sel,
                    "year": year_now,
                    "already_done": False,
                    "rating": None,
                    "saved": False,
                    "error": f"{label}: el valor debe estar entre 0 y 5.",
                    "prefill": {
                        "universidad": universidad,
                        "semestre": semestre,
                        "cognitiva": cognitiva,
                        "aptitudinal": aptitudinal,
                        "actitudinal": actitudinal,
                        "evaluacion": evaluacion,
                        "cpc": cpc,
                        "porcentaje_fallas": porcentaje_fallas,
                        "comentarios": comentarios,
                    },
                },
                status_code=400,
            )

    # % fallas
    if porcentaje_fallas is not None:
        try:
            pf = float(porcentaje_fallas)
        except Exception:
            pf = 0.0
        if pf < 0 or pf > 100:
            st_tmp = db.query(Student).filter(Student.id == student_id, Student.activa == True).first()
            rot_tmp = db.query(Rotation).filter(Rotation.id == rotation_id, Rotation.activa == True).first()
            return templates.TemplateResponse(
                "profesor/rate.html",
                {
                    "request": request,
                    "csrf_token": make_csrf_token(tid, salt="/profesor/ratings/create"),
                    "teacher": teacher,
                    "student": st_tmp,
                    "rotation": rot_tmp,
                    "mes": mes_sel,
                    "year": year_now,
                    "already_done": False,
                    "rating": None,
                    "saved": False,
                    "error": "Porcentaje de fallas: el valor debe estar entre 0 y 100.",
                    "prefill": {
                        "universidad": universidad,
                        "semestre": semestre,
                        "cognitiva": cognitiva,
                        "aptitudinal": aptitudinal,
                        "actitudinal": actitudinal,
                        "evaluacion": evaluacion,
                        "cpc": cpc,
                        "porcentaje_fallas": porcentaje_fallas,
                        "comentarios": comentarios,
                    },
                },
                status_code=400,
            )

    st = db.query(Student).filter(Student.id == student_id, Student.activa == True).first()
    rot = db.query(Rotation).filter(Rotation.id == rotation_id, Rotation.activa == True).first()
    if not st or not rot:
        raise HTTPException(status_code=404, detail="Estudiante o rotación inválidos")

    assigned = db.query(StudentTeacher).filter(
        StudentTeacher.student_id == st.id,
        StudentTeacher.teacher_id == teacher.id,
        StudentTeacher.rotation_id == rot.id,
    ).first()
    if not assigned:
        raise HTTPException(status_code=403, detail="No tienes asignación para este estudiante/rotación")

    mc = db.query(MonthControl).filter(MonthControl.rotation_id == rot.id, MonthControl.year == year_now, MonthControl.mes == mes_sel).first()
    if mc and mc.is_closed:
        raise HTTPException(status_code=403, detail="El mes está CERRADO para esta rotación.")

    dup = db.query(Rating).filter(
        Rating.estudiante_documento == st.documento,
        Rating.rotation_id == rot.id,
        Rating.year == year_now,
        Rating.mes == mes_sel,
        Rating.is_void == False,
        Rating.especialista_documento == tid,
    ).first()
    if dup:
        raise HTTPException(status_code=409, detail="Ya registraste una calificación para este estudiante en esta rotación/mes.")

    payload = RatingCreate(
        estudiante_nombre=st.nombre,
        estudiante_documento=st.documento,
        universidad=universidad,
        semestre=semestre,
        mes=mes_sel,
        rotation_id=rot.id,
        cognitiva=cognitiva,
        aptitudinal=aptitudinal,
        actitudinal=actitudinal,
        evaluacion=evaluacion,
        cpc=cpc,
        porcentaje_fallas=porcentaje_fallas,
        especialista_nombre=teacher.nombre,
        especialista_documento=tid,
        coordinador_nombre="N/A",
        estudiante_firma_nombre="N/A",
        comentarios=comentarios,
    )

    nota, pierde = calcular_nota(payload)
    data = payload.model_dump()
    rating = Rating(
        **data,
        year=year_now,
        pierde_por_fallas=pierde,
        nota_definitiva=nota,
        nota_en_letras=numero_a_letras_nota(nota),
        actor=teacher.username or tid,
    )
    db.add(rating)
    db.commit()
    db.refresh(rating)
    add_audit(db, rating.id, "CREATE", teacher.username or teacher.documento, f"rotation={rot.nombre} docente={tid}")
    auto_close_if_complete(db, st, rot.id, year_now, mes_sel, teacher.username or tid)

    return RedirectResponse(url=f"/profesor?toast=saved&student_id={st.id}&rotation_id={rot.id}&mes={mes_sel}", status_code=303)


@app.get("/rate", response_class=HTMLResponse)
def rate_form(request: Request, r: int | None = None, mes: str = "", auth=Depends(require_roles(["admin","coord","eval","docente"])), db: Session = Depends(get_db)):
    seed_rotations(db)

    rotations = (
        db.query(Rotation)
        .filter(Rotation.activa == True)
        .order_by(Rotation.nombre.asc())
        .all()
    )
    if not rotations:
        raise HTTPException(status_code=404, detail="No hay rotaciones activas configuradas")

    meses = [
        "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
    ]
    mes_actual = meses[datetime.now().month - 1]
    mes_prefill = mes.strip() if mes and mes.strip() in meses else mes_actual

    selected_rotation_id = r if r else rotations[0].id
    if not any(rot.id == selected_rotation_id for rot in rotations):
        selected_rotation_id = rotations[0].id

    return templates.TemplateResponse(
        "rate.html",
        {
            "request": request,
            "rotations": rotations,
            "selected_rotation_id": selected_rotation_id,
            "meses": meses,
            "mes_prefill": mes_prefill,
        },
    )


# ✅ NUEVO: Check de duplicado (Documento + Rotación + Mes) - no requiere auth


@app.get("/api/teachers/assigned")
def api_teachers_assigned(estudiante_documento: str, rotation_id: int, db: Session = Depends(get_db)):
    """Lista de docentes asignados a un estudiante para una rotación (para el formulario público)."""
    estudiante_documento = (estudiante_documento or "").strip()
    if not estudiante_documento or rotation_id < 1:
        return {"items": []}

    st = db.query(Student).filter(Student.documento == estudiante_documento, Student.activa == True).first()
    if not st:
        return {"items": []}

    rows = (
        db.query(StudentTeacher)
        .join(Teacher, StudentTeacher.teacher_id == Teacher.id)
        .filter(
            StudentTeacher.student_id == st.id,
            StudentTeacher.rotation_id == rotation_id,
            Teacher.activo == True,
        )
        .order_by(Teacher.nombre.asc())
        .all()
    )

    items = [
        {
            "id": r.teacher.id,
            "documento": r.teacher.documento,
            "nombre": r.teacher.nombre,
            "especialidad": r.teacher.especialidad,
        }
        for r in rows
    ]
    return {"items": items}


@app.get("/api/ratings/check")
def check_rating_exists(
    documento: str,
    rotation_id: int,
    mes: str,
    especialista_documento: str = "",
    db: Session = Depends(get_db),
):
    documento = (documento or "").strip()
    mes = (mes or "").strip()
    especialista_documento = (especialista_documento or "").strip()

    if not documento or not mes or rotation_id < 1:
        return {"exists": False}

    existing = (
        db.query(Rating)
        .filter(
            Rating.estudiante_documento == documento,
            Rating.rotation_id == rotation_id,
            Rating.mes == mes,
            Rating.is_void == False,  # si está anulado, sí permitimos
            *([Rating.especialista_documento == especialista_documento] if especialista_documento else []),
        )
        .order_by(desc(Rating.created_at))
        .first()
    )

    if not existing:
        return {"exists": False}

    return {
        "exists": True,
        "id": existing.id,
        "created_at": existing.created_at.isoformat(sep=" ", timespec="minutes"),
        "estado": "ANULADO" if existing.is_void else ("CERRADO" if existing.is_closed else "ABIERTO"),
    }


# ✅ NUEVO: Autocompletar datos del estudiante por documento (cédula)
@app.get("/api/students/lookup")
def lookup_student(documento: str, db: Session = Depends(get_db)):
    """Devuelve datos para autocompletar el formulario al digitar el documento.

    Estrategia:
    - Busca en tabla `students`.
    - Si no existe (o faltan campos), intenta con la última calificación registrada (ratings).
    - Para `mes` y `rotation_id` usa la última calificación (si existe); si no, usa mes actual.
    """

    documento = (documento or "").strip()
    if not documento or len(documento) < 3:
        return {"found": False}

    # Importante: el formulario SOLO debe autocompletar desde el módulo ADMIN (tabla students).
    # Aun así, mantenemos la lectura de la última calificación como "fallback" informativo.
    student = db.query(Student).filter(Student.documento == documento, Student.activa == True).first()

    last_rating = (
        db.query(Rating)
        .filter(Rating.estudiante_documento == documento, Rating.is_void == False)
        .order_by(desc(Rating.created_at))
        .first()
    )

    nombre = (student.nombre if student else "") or (last_rating.estudiante_nombre if last_rating else "") or ""
    universidad = (student.universidad if student else "") or (last_rating.universidad if last_rating else "") or ""
    semestre = (student.semestre if student else "") or (last_rating.semestre if last_rating else "") or ""

    # Defaults
    _, mes_actual = now_year_month()
    mes = (last_rating.mes if last_rating else "") or mes_actual
    rotation_id = int(last_rating.rotation_id) if last_rating else None

    return {
        # found = hay información para autocompletar
        "found": bool(student or last_rating),
        # found_student = existe en Students (creado por ADMIN)
        "found_student": bool(student),
        "documento": documento,
        "nombre": nombre,
        "universidad": universidad,
        "semestre": semestre,
        "mes": mes,
        "rotation_id": rotation_id,
    }


# ✅ NUEVO: Buscar estudiantes (para datalist/autosuggest en el formulario)
@app.get("/api/students/search")
def search_students(
    q: str = "",
    limit: int = 20,
    mes: str | None = None,
    rotacion: int | None = None,
    db: Session = Depends(get_db),
):
    """Devuelve una lista corta de estudiantes para autocompletar/seleccionar.

    - Busca por: documento / nombre / universidad.
    - Retorna máximo `limit` (por defecto 20).
    """

    q = (q or "").strip()
    # Para modal (<300 estudiantes), permitimos cargar hasta 300.
    limit = max(1, min(int(limit or 20), 300))

    qry = db.query(Student)
    if q:
        like = f"%{q}%"
        qry = qry.filter(
            or_(
                Student.documento.ilike(like),
                Student.nombre.ilike(like),
                Student.universidad.ilike(like),
            )
        )

    students = qry.order_by(Student.nombre.asc()).limit(limit).all()

    # (Opcional) Agregar columna: calificado este mes/rotación
    # Si el frontend manda ?mes=Enero&rotacion=4, marcamos True/False por estudiante.
    calificados: set[str] = set()
    if mes and rotacion:
        mes = (mes or "").strip()
        try:
            rotacion_int = int(rotacion)
        except Exception:
            rotacion_int = None

        if mes and rotacion_int:
            rows = (
                db.query(Rating.estudiante_documento)
                .filter(
                    Rating.mes == mes,
                    Rating.rotation_id == rotacion_int,
                    Rating.is_void == False,
                )
                .distinct()
                .all()
            )
            calificados = {r[0] for r in rows if r and r[0]}

    return {
        "items": [
            {
                "documento": s.documento,
                "nombre": s.nombre,
                "universidad": s.universidad,
                "semestre": s.semestre,
                "activa": bool(s.activa),
                "calificado": (s.documento in calificados) if (mes and rotacion) else None,
            }
            for s in students
        ]
    }


@app.post("/api/ratings", response_model=RatingOut)
def create_rating(payload: RatingCreate, auth=Depends(require_roles(["admin","coord","eval"])), db: Session = Depends(get_db)):
    # ✅ Regla: NO se pueden "crear" estudiantes desde el formulario.
    # El estudiante DEBE existir previamente en el módulo ADMIN (tabla students).
    estudiante_doc = (payload.estudiante_documento or "").strip()
    st = (
        db.query(Student)
        .filter(Student.documento == estudiante_doc, Student.activa == True)
        .first()
    )
    if not st:
        raise HTTPException(
            status_code=400,
            detail="Estudiante no registrado. Debe estar creado/activo en el módulo Administrador.",
        )

    rotation = db.query(Rotation).filter(Rotation.id == payload.rotation_id, Rotation.activa == True).first()
    if not rotation:
        raise HTTPException(status_code=400, detail="Rotación inválida o inactiva")

    # ✅ Docente (profesor) debe existir y estar asignado al estudiante en esa rotación
    teacher_doc = (payload.especialista_documento or "").strip()
    teacher = (
        db.query(Teacher)
        .filter(Teacher.documento == teacher_doc, Teacher.activo == True)
        .first()
    )
    if not teacher:
        raise HTTPException(status_code=400, detail="Docente no registrado o inactivo. Debe existir en el módulo ADMIN: Profesores.")

    assigned = (
        db.query(StudentTeacher)
        .filter(
            StudentTeacher.student_id == st.id,
            StudentTeacher.teacher_id == teacher.id,
            StudentTeacher.rotation_id == payload.rotation_id,
        )
        .first()
    )
    if not assigned:
        raise HTTPException(status_code=403, detail="Docente no asignado a este estudiante en esta rotación.")

    # ✅ Control de mes por rotación (si está cerrado, bloquear calificación)
    year_now = datetime.now().year
    mes_now = (payload.mes or "").strip()
    mc = (
        db.query(MonthControl)
        .filter(MonthControl.rotation_id == payload.rotation_id, MonthControl.year == year_now, MonthControl.mes == mes_now)
        .first()
    )
    if mc and mc.is_closed:
        raise HTTPException(
            status_code=403,
            detail="El mes está CERRADO para esta rotación. Si requiere cambios, diríjase con el Administrador/Coordinación.",
        )

    # ✅ BLOQUEO EN BACKEND: evitar duplicado
    dup = (
        db.query(Rating)
        .filter(
            Rating.estudiante_documento == payload.estudiante_documento.strip(),
            Rating.rotation_id == payload.rotation_id,
            Rating.mes == payload.mes.strip(),
            Rating.is_void == False,
            Rating.especialista_documento == payload.especialista_documento.strip(),
        )
        .first()
    )
    if dup:
        # 409 = Conflict
        raise HTTPException(
            status_code=409,
            detail="Este estudiante ya fue calificado por ESTE profesor para esta rotación y mes. Si requiere cambiar la nota, diríjase con el Administrador.",
        )

    nota, pierde = calcular_nota(payload)

    data = payload.model_dump()
    data["especialista_nombre"] = teacher.nombre
    data["especialista_documento"] = teacher.documento

    rating = Rating(
        **data,
        year=year_now,
        pierde_por_fallas=pierde,
        nota_definitiva=nota,
        nota_en_letras=numero_a_letras_nota(nota),
        actor=auth["user"],
    )
    db.add(rating)
    db.commit()
    db.refresh(rating)

    add_audit(db, rating.id, "CREATE", auth["user"], f"rotation={rotation.nombre}")

    # ✅ Auto-cierre cuando la definitiva final esté lista (todos los docentes asignados ya evaluaron)
    auto_close_if_complete(db, st, payload.rotation_id, year_now, mes_now, auth["user"])

    return rating


@app.post("/api/ratings/{rating_id}/close")
def close_rating(rating_id: int, auth=Depends(require_roles(["admin","coord"])), db: Session = Depends(get_db)):
    r = db.query(Rating).filter(Rating.id == rating_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="No existe")
    if r.is_void:
        raise HTTPException(status_code=400, detail="Registro anulado, no se puede cerrar")

    r.is_closed = True
    r.updated_at = func.now()
    db.commit()
    add_audit(db, rating_id, "CLOSE", auth["user"])
    return {"ok": True}


@app.post("/api/ratings/{rating_id}/void")
def void_rating(rating_id: int, reason: str = Form(...), auth=Depends(require_roles(["admin","coord"])), db: Session = Depends(get_db)):
    r = db.query(Rating).filter(Rating.id == rating_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="No existe")

    r.is_void = True
    r.is_closed = False
    r.void_reason = (reason or "").strip()[:300]
    r.updated_at = func.now()
    db.commit()
    add_audit(db, rating_id, "VOID", auth["user"], r.void_reason)
    return {"ok": True}



@app.post("/api/ratings/{rating_id}/reopen")
def reopen_rating(
    rating_id: int,
    reason: str = Form(""),
    auth=Depends(require_roles(["admin","coord"])),
    db: Session = Depends(get_db),
):
    """Reabre una calificación CERRADA para permitir corrección por el docente (ADMIN)."""
    ensure_schema(db)
    r = db.query(Rating).filter(Rating.id == rating_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="No existe")
    if r.is_void:
        raise HTTPException(status_code=400, detail="Registro ANULADO, no se puede reabrir")

    # Si ya está abierta, no hacemos nada (idempotente)
    if not r.is_closed:
        add_audit(db, rating_id, "REOPEN", auth["user"], "Ya estaba abierta")
        return {"ok": True, "already_open": True}

    r.is_closed = False
    try:
        r.reopen_count = int(getattr(r, "reopen_count", 0) or 0) + 1
    except Exception:
        r.reopen_count = 1
    r.reopen_reason = (reason or "").strip()[:300]
    r.reopened_by = auth["user"]
    r.reopened_at = datetime.utcnow()
    r.updated_at = func.now()
    db.commit()

    add_audit(db, rating_id, "REOPEN", auth["user"], r.reopen_reason)
    add_admin_audit(db, "Calificaciones", "REOPEN", auth["user"], f"id={rating_id} reason={r.reopen_reason}")
    return {"ok": True}

@app.get("/qr/{rotation_id}")
def qr_rotation(rotation_id: int, mes: str = "", auth=Depends(require_roles(["admin","coord","eval","docente"])), db: Session = Depends(get_db)):
    rotation = db.query(Rotation).filter(Rotation.id == rotation_id, Rotation.activa == True).first()
    if not rotation:
        raise HTTPException(status_code=404, detail="Rotación no encontrada o inactiva")

    url = build_form_url(rotation_id, mes)
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")


@app.get("/share/wa")
def share_whatsapp(r: int, mes: str = "", phone: str = "", db: Session = Depends(get_db)):
    rotation = db.query(Rotation).filter(Rotation.id == r).first()
    if not rotation:
        raise HTTPException(status_code=404, detail="Rotación no encontrada")

    form_url = build_form_url(r, mes)
    wa_url, msg = build_whatsapp_url(rotation.nombre, form_url, phone)
    return {"whatsapp_url": wa_url, "form_url": form_url, "message": msg}


@app.get("/go/wa")
def go_whatsapp(r: int, mes: str = "", phone: str = "", auth=Depends(require_roles(["admin","coord","eval","docente"])), db: Session = Depends(get_db)):
    data = share_whatsapp(r=r, mes=mes, phone=phone, db=db)
    return RedirectResponse(url=data["whatsapp_url"])


# -------------------- ADMIN UI --------------------


@app.get("/logout")
def logout():
    """Forzar re-autenticación en navegadores (HTTP Basic)."""
    raise HTTPException(
        status_code=401,
        detail="Sesión cerrada",
        headers={"WWW-Authenticate": "Basic"},
    )

@app.get("/admin", response_class=HTMLResponse)
def admin_home(request: Request, auth=Depends(require_roles(["admin","coord"])), db: Session = Depends(get_db)):
    current_year, current_month = now_year_month()
    # KPIs
    kpi_students = db.query(Student).filter(Student.activa == True).count()
    kpi_teachers = db.query(Teacher).filter(Teacher.activo == True).count()
    kpi_ratings = db.query(Rating).filter(Rating.is_void == False).count()
    kpi_pending = db.query(Rating).filter(Rating.is_void == False, Rating.is_closed == False).count()

    # Deltas simples (se dejan en 0 si no hay histórico mensual aún)
    kpi_students_delta = 0
    kpi_teachers_delta = 0
    kpi_ratings_ratio = 0
    try:
        if kpi_ratings > 0:
            kpi_ratings_ratio = int(round(100 * (kpi_ratings - kpi_pending) / max(1, kpi_ratings)))
    except Exception:
        kpi_ratings_ratio = 0

    # Actividad reciente (Admin + Auditoría de calificaciones)
    recent = []
    a1 = db.query(AdminAudit).order_by(AdminAudit.created_at.desc()).limit(4).all()
    a2 = db.query(RatingAudit).order_by(RatingAudit.created_at.desc()).limit(4).all()
    def fmt_dt(dt: datetime):
        try:
            return dt.strftime('%H:%M')
        except Exception:
            return ''
    for a in a1:
        recent.append({
            "time": fmt_dt(a.created_at),
            "title": f"{a.actor} · {a.module}",
            "sub": (a.action + (" — " + a.details if a.details else ""))[:140],
        })
    for a in a2:
        recent.append({
            "time": fmt_dt(a.created_at),
            "title": f"{a.actor} · Calificación",
            "sub": (a.action + (" — " + a.details if a.details else ""))[:140],
        })
    recent = sorted(recent, key=lambda x: x.get("time", ""), reverse=True)[:6]

    # Rotaciones activas + conteo de estudiantes asignados
    active_rotations = []
    rot_list = db.query(Rotation).filter(Rotation.activa == True).order_by(Rotation.nombre.asc()).all()
    for idx, r in enumerate(rot_list[:6]):
        st_count = db.query(StudentTeacher).filter(StudentTeacher.rotation_id == r.id).count()
        # Progreso visual (placeholder): escalonado para dar feedback visual
        progress = 55 + (idx * 7)
        progress = min(92, max(10, progress))
        active_rotations.append({"nombre": r.nombre, "students": st_count, "progress": progress})

    # Tabla: pendientes recientes
    import calendar
    from datetime import date
    last_day = calendar.monthrange(datetime.now().year, datetime.now().month)[1]
    venc = date(datetime.now().year, datetime.now().month, last_day).strftime('%d %b')
    pend = (
        db.query(Rating, Rotation)
        .join(Rotation, Rating.rotation_id == Rotation.id)
        .filter(Rating.is_void == False, Rating.is_closed == False)
        .order_by(Rating.created_at.desc())
        .limit(8)
        .all()
    )
    pending_rows = []
    for r, rot in pend:
        pending_rows.append({
            "estudiante_nombre": r.estudiante_nombre,
            "estudiante_documento": r.estudiante_documento,
            "rotation_nombre": rot.nombre,
            "docente": r.especialista_nombre or "—",
            "vencimiento": venc,
        })

    return templates.TemplateResponse(
        "admin/home.html",
        {
            "request": request,
            "csrf_token": _csrf_for(request, auth["user"]),
            "kpi_students": kpi_students,
            "kpi_teachers": kpi_teachers,
            "kpi_ratings": kpi_ratings,
            "kpi_pending": kpi_pending,
            "kpi_students_delta": kpi_students_delta,
            "kpi_teachers_delta": kpi_teachers_delta,
            "kpi_ratings_ratio": kpi_ratings_ratio,
            "recent": recent,
            "active_rotations": active_rotations,
            "pending_rows": pending_rows,
            "role": auth["role"],
            "user": auth["user"],
            "public_base": public_base_url(),
            "current_year": current_year,
            "current_month": current_month,
            "active": "home",
            "title": "Panel principal",
        },
    )


@app.get("/admin/list", response_class=HTMLResponse)
def admin_list(
    request: Request,
    q: str = "",
    rotation_id: str = "",
    mes: str = "",
    status: str = "",
    page: int = 1,
    auth=Depends(require_roles(["admin","coord"])),
    db: Session = Depends(get_db),
):
    current_year, current_month = now_year_month()
    rotations = db.query(Rotation).order_by(Rotation.nombre.asc()).all()
    page = max(1, page)
    limit = 25
    offset = (page - 1) * limit
    rotation_id_int = parse_rotation_id(rotation_id)
    total, items = query_ratings(db, q=q, rotation_id=rotation_id_int, mes=mes, status=status, limit=limit, offset=offset)
    pages = max(1, (total + limit - 1) // limit)

    return templates.TemplateResponse(
        "admin/list.html",
        {
            "request": request,
            "csrf_token": _csrf_for(request, auth["user"]),
            "items": items,
            "rotations": rotations,
            "q": q,
            "rotation_id": rotation_id_int,
            "mes": mes,
            "status": status,
            "page": page,
            "pages": pages,
            "total": total,
            "role": auth["role"],
            "user": auth["user"],
            "current_year": current_year,
            "current_month": current_month,
            "active": "list",
            "title": "Calificaciones",
        },
    )


@app.get("/admin/rating/{rating_id}/pdf")
def admin_pdf(rating_id: int, auth=Depends(require_roles(["admin","coord"])), db: Session = Depends(get_db)):
    r = db.query(Rating).filter(Rating.id == rating_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="No existe")

    rot = db.query(Rotation).filter(Rotation.id == r.rotation_id).first()
    pdf_bytes = render_rating_pdf(r, rot.nombre if rot else "N/A")

    return Response(
        pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=DS-F-01_{rating_id}.pdf"},
    )


@app.get("/admin/export.csv")
def export_csv(
    q: str = "",
    rotation_id: str = "",
    mes: str = "",
    status: str = "",
    auth=Depends(require_roles(["admin","coord"])),
    db: Session = Depends(get_db),
):
    rotation_id_int = parse_rotation_id(rotation_id)
    total, items = query_ratings(db, q=q, rotation_id=rotation_id_int, mes=mes, status=status, limit=100000, offset=0)

    import csv
    from io import StringIO

    out = StringIO()
    w = csv.writer(out)
    w.writerow(["id","fecha","rotacion","mes","estudiante","documento","universidad","semestre","nota","fallas%","pierde","estado","especialista","coordinador","evaluador_usuario"])

    for r in items:
        estado = "ANULADO" if r.is_void else ("CERRADO" if r.is_closed else "ABIERTO")
        w.writerow([
            r.id,
            r.created_at.isoformat(sep=" ", timespec="minutes"),
            r.rotation.nombre,
            r.mes,
            r.estudiante_nombre,
            r.estudiante_documento,
            r.universidad,
            r.semestre,
            f"{r.nota_definitiva:.2f}",
            r.porcentaje_fallas,
            r.pierde_por_fallas,
            estado,
            r.especialista_nombre,
            r.coordinador_nombre,
            r.actor,
        ])

    data = out.getvalue().encode("utf-8-sig")
    return Response(data, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=calificaciones_DS-F-01.csv"})


@app.get("/admin/export.xlsx")
def export_xlsx(
    q: str = "",
    rotation_id: str = "",
    mes: str = "",
    status: str = "",
    auth=Depends(require_roles(["admin","coord"])),
    db: Session = Depends(get_db),
):
    rotation_id_int = parse_rotation_id(rotation_id)
    total, items = query_ratings(db, q=q, rotation_id=rotation_id_int, mes=mes, status=status, limit=100000, offset=0)

    wb = Workbook()
    ws = wb.active
    ws.title = "Calificaciones"
    ws.append(["id","fecha","rotacion","mes","estudiante","documento","universidad","semestre","nota","fallas%","pierde","estado","especialista","coordinador","evaluador_usuario"])

    for r in items:
        estado = "ANULADO" if r.is_void else ("CERRADO" if r.is_closed else "ABIERTO")
        ws.append([
            r.id,
            r.created_at.strftime("%Y-%m-%d %H:%M"),
            r.rotation.nombre,
            r.mes,
            r.estudiante_nombre,
            r.estudiante_documento,
            r.universidad,
            r.semestre,
            float(r.nota_definitiva),
            float(r.porcentaje_fallas),
            int(r.pierde_por_fallas),
            estado,
            r.especialista_nombre,
            r.coordinador_nombre,
            r.actor,
        ])

    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)

    return Response(
        bio.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=calificaciones_DS-F-01.xlsx"},
    )


@app.get("/admin/rotaciones", response_class=HTMLResponse)
def admin_rotaciones(request: Request, auth=Depends(require_roles(["admin"])), db: Session = Depends(get_db)):
    current_year, current_month = now_year_month()
    rotations = db.query(Rotation).order_by(Rotation.nombre.asc()).all()
    return templates.TemplateResponse(
        "admin/rotaciones.html",
        {
            "request": request,
            "csrf_token": _csrf_for(request, auth["user"]),
            "rotations": rotations,
            "public_base": public_base_url(),
            "role": auth["role"],
            "user": auth["user"],
            "current_year": current_year,
            "current_month": current_month,
            "active": "rotaciones",
            "title": "Rotaciones",
        },
    )


@app.post("/admin/rotaciones/create")
def admin_rotaciones_create(request: Request, nombre: str = Form(...), csrf_token: str = Form(""), auth=Depends(require_roles(["admin"])), db: Session = Depends(get_db)):
    _verify_csrf_or_400(csrf_token, request, auth["user"])
    nombre = (nombre or "").strip()
    if len(nombre) < 2:
        raise HTTPException(status_code=400, detail="Nombre inválido")

    if db.query(Rotation).filter(Rotation.nombre == nombre).first():
        raise HTTPException(status_code=400, detail="Ya existe")

    db.add(Rotation(nombre=nombre, activa=True))
    db.commit()
    return RedirectResponse(url="/admin/rotaciones", status_code=303)


@app.post("/admin/rotaciones/toggle")
def admin_rotaciones_toggle(request: Request, rotation_id: int = Form(...), csrf_token: str = Form(""), auth=Depends(require_roles(["admin"])), db: Session = Depends(get_db)):
    _verify_csrf_or_400(csrf_token, request, auth["user"])
    rot = db.query(Rotation).filter(Rotation.id == rotation_id).first()
    if not rot:
        raise HTTPException(status_code=404, detail="No existe")

    rot.activa = not rot.activa
    db.commit()
    return RedirectResponse(url="/admin/rotaciones", status_code=303)


# -------------------- ADMIN: ESTUDIANTES --------------------



def _qr_png_base64(data: str) -> str:
    import qrcode
    import base64
    import io
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


@app.get("/admin/mfa/setup", response_class=HTMLResponse)
def admin_mfa_setup(request: Request, session=Depends(require_session_admin), db: Session = Depends(get_db)):
    # Solo admin (no coord/eval) para habilitar MFA
    if session.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede configurar MFA")
    acct = db.query(Account).filter(Account.id == session["account_id"]).first()
    if not acct:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")

    # Generar/rotar secreto (aún no se activa hasta verificar)
    secret = generate_totp_secret()
    acct.mfa_secret = secret
    acct.mfa_enabled = False
    acct.mfa_verified_at = None
    db.add(acct)
    log_auth_event(db, "mfa_setup_started", username=acct.username, role=acct.role, ip=get_client_ip(request), user_agent=request.headers.get("user-agent",""))
    db.commit()

    issuer = os.getenv("MFA_ISSUER", "Calificaciones")
    otpauth = f"otpauth://totp/{issuer}:{acct.username}?secret={secret}&issuer={issuer}&algorithm=SHA1&digits=6&period=30"
    qr_b64 = _qr_png_base64(otpauth)

    return templates.TemplateResponse(
        "admin/mfa_setup.html",
        {"request": request, "qr_b64": qr_b64, "secret": secret, "csrf_token": make_csrf_token("mfa_setup", salt="/admin/mfa/setup"), "csrf_disable": make_csrf_token("mfa_disable", salt="/admin/mfa/disable"), "error": "", "ok": ""},
    )


@app.post("/admin/mfa/verify", response_class=HTMLResponse)
def admin_mfa_verify(
    request: Request,
    otp: str = Form(...),
    csrf_token: str = Form(""),
    session=Depends(require_session_admin),
    db: Session = Depends(get_db),
):
    if session.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede configurar MFA")
    if not verify_csrf_token(csrf_token, "mfa_setup", salt="/admin/mfa/setup"):
        return RedirectResponse(url="/admin/mfa/setup", status_code=302)

    acct = db.query(Account).filter(Account.id == session["account_id"]).first()
    if not acct or not acct.mfa_secret:
        return RedirectResponse(url="/admin/mfa/setup", status_code=302)

    if not verify_totp_code(acct.mfa_secret, otp):
        log_auth_event(db, "mfa_setup_failed", username=acct.username, role=acct.role, ip=get_client_ip(request), user_agent=request.headers.get("user-agent",""))
        db.commit()
        issuer = os.getenv("MFA_ISSUER", "Calificaciones")
        otpauth = f"otpauth://totp/{issuer}:{acct.username}?secret={acct.mfa_secret}&issuer={issuer}"
        qr_b64 = _qr_png_base64(otpauth)
        return templates.TemplateResponse(
            "admin/mfa_setup.html",
            {"request": request, "qr_b64": qr_b64, "secret": acct.mfa_secret, "csrf_token": make_csrf_token("mfa_setup", salt="/admin/mfa/setup"), "csrf_disable": make_csrf_token("mfa_disable", salt="/admin/mfa/disable"), "error": "OTP inválido. Intenta de nuevo.", "ok": ""},
            status_code=400,
        )

    acct.mfa_enabled = True
    acct.mfa_verified_at = datetime.utcnow()
    db.add(acct)
    log_auth_event(db, "mfa_enabled", username=acct.username, role=acct.role, ip=get_client_ip(request), user_agent=request.headers.get("user-agent",""))
    db.commit()
    return RedirectResponse(url="/admin", status_code=302)


@app.post("/admin/mfa/disable", response_class=HTMLResponse)
def admin_mfa_disable(
    request: Request,
    password: str = Form(...),
    otp: str = Form(...),
    csrf_token: str = Form(""),
    session=Depends(require_session_admin),
    db: Session = Depends(get_db),
):
    if session.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede desactivar MFA")
    if not verify_csrf_token(csrf_token, "mfa_disable", salt=str(request.url.path)):
        return RedirectResponse(url="/admin", status_code=302)

    acct = db.query(Account).filter(Account.id == session["account_id"]).first()
    if not acct:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")

    if not verify_password(password, acct.password_hash) or (acct.mfa_secret and not verify_totp_code(acct.mfa_secret, otp)):
        log_auth_event(db, "mfa_disable_failed", username=acct.username, role=acct.role, ip=get_client_ip(request), user_agent=request.headers.get("user-agent",""))
        db.commit()
        raise HTTPException(status_code=401, detail="Credenciales/OTP inválidos")

    acct.mfa_enabled = False
    acct.mfa_secret = None
    acct.mfa_verified_at = None
    db.add(acct)
    log_auth_event(db, "mfa_disabled", username=acct.username, role=acct.role, ip=get_client_ip(request), user_agent=request.headers.get("user-agent",""))
    db.commit()
    return RedirectResponse(url="/admin", status_code=302)

@app.get("/admin/estudiantes", response_class=HTMLResponse)
def admin_estudiantes(
    request: Request,
    q: str = "",
    page: int = 1,
    auth=Depends(require_roles(["admin"])),
    db: Session = Depends(get_db),
):
    seed_rotations(db)
    current_year, current_month = now_year_month()

    page = max(1, page)
    limit = 25
    offset = (page - 1) * limit

    qry = db.query(Student)
    if q:
        like = f"%{q.strip()}%"
        qry = qry.filter(or_(Student.nombre.ilike(like), Student.documento.ilike(like), Student.universidad.ilike(like)))

    total = qry.count()
    students = qry.order_by(Student.nombre.asc()).limit(limit).offset(offset).all()
    pages = max(1, (total + limit - 1) // limit)

    return templates.TemplateResponse(
        "admin/estudiantes.html",
        {
            "request": request,
            "csrf_token": _csrf_for(request, auth["user"]),
            "students": students,
            "q": q,
            "page": page,
            "pages": pages,
            "total": total,
            "role": auth["role"],
            "user": auth["user"],
            "current_year": current_year,
            "current_month": current_month,
            "active": "estudiantes",
            "title": "Estudiantes",
        },
    )


@app.post("/admin/estudiantes/create")
def admin_estudiantes_create(
    documento: str = Form(...),
    nombre: str = Form(...),
    universidad: str = Form(""),
    semestre: str = Form(""),
    activa: str = Form("1"),
    auth=Depends(require_roles(["admin"])),
    db: Session = Depends(get_db),
):
    seed_rotations(db)
    documento = (documento or "").strip()
    nombre = (nombre or "").strip()
    if len(documento) < 3 or len(nombre) < 3:
        raise HTTPException(status_code=400, detail="Documento/Nombre inválidos")

    if db.query(Student).filter(Student.documento == documento).first():
        raise HTTPException(status_code=400, detail="Ya existe un estudiante con ese documento")

    st = Student(
        documento=documento,
        nombre=nombre,
        universidad=(universidad or "").strip(),
        semestre=(semestre or "").strip(),
        activa=(activa == "1"),
    )
    db.add(st)
    db.commit()
    add_admin_audit(db, "ESTUDIANTES", "CREATE", auth["user"], f"documento={documento}")
    return RedirectResponse(url="/admin/estudiantes", status_code=303)


@app.post("/admin/estudiantes/update")
def admin_estudiantes_update(
    student_id: int = Form(...),
    documento: str = Form(...),
    nombre: str = Form(...),
    universidad: str = Form(""),
    semestre: str = Form(""),
    activa: str = Form("1"),
    auth=Depends(require_roles(["admin"])),
    db: Session = Depends(get_db),
):
    seed_rotations(db)
    st = db.query(Student).filter(Student.id == student_id).first()
    if not st:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")

    documento = (documento or "").strip()
    nombre = (nombre or "").strip()
    if len(documento) < 3 or len(nombre) < 3:
        raise HTTPException(status_code=400, detail="Documento/Nombre inválidos")

    # evitar duplicado por documento
    exists = db.query(Student).filter(Student.documento == documento, Student.id != student_id).first()
    if exists:
        raise HTTPException(status_code=400, detail="Ya existe otro estudiante con ese documento")

    st.documento = documento
    st.nombre = nombre
    st.universidad = (universidad or "").strip()
    st.semestre = (semestre or "").strip()
    st.activa = (activa == "1")

    db.commit()
    add_admin_audit(db, "ESTUDIANTES", "UPDATE", auth["user"], f"id={student_id} documento={documento}")
    return RedirectResponse(url="/admin/estudiantes", status_code=303)


@app.post("/admin/estudiantes/delete")
def admin_estudiantes_delete(
    student_id: int = Form(...),
    auth=Depends(require_roles(["admin"])),
    db: Session = Depends(get_db),
):
    seed_rotations(db)
    st = db.query(Student).filter(Student.id == student_id).first()
    if not st:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")

    # Si ya tiene calificaciones asociadas por documento, no borrar (seguridad histórica)
    used = db.query(Rating).filter(Rating.estudiante_documento == st.documento).first()
    if used:
        raise HTTPException(
            status_code=400,
            detail="No se puede eliminar: el estudiante tiene calificaciones registradas. (Recomendado: inactivar).",
        )

    doc = st.documento
    db.delete(st)
    db.commit()
    add_admin_audit(db, "ESTUDIANTES", "DELETE", auth["user"], f"documento={doc}")
    return RedirectResponse(url="/admin/estudiantes", status_code=303)




# -------------------- ADMIN: PROFESORES + ASIGNACIÓN (POR ESTUDIANTE/ROTACIÓN) --------------------


@app.get("/admin/profesores", response_class=HTMLResponse)
def admin_profesores(
    request: Request,
    student_id: int = 0,
    rotation_id: int = 0,
    q: str = "",
    auth=Depends(require_roles(["admin"])),
    db: Session = Depends(get_db),
):
    seed_rotations(db)
    current_year, current_month = now_year_month()

    # Listado de profesores
    tq = db.query(Teacher)
    if q:
        like = f"%{q.strip()}%"
        tq = tq.filter(or_(Teacher.nombre.ilike(like), Teacher.documento.ilike(like), Teacher.especialidad.ilike(like)))
    teachers = tq.order_by(Teacher.nombre.asc()).all()

    # Para asignaciones
    students = db.query(Student).order_by(Student.nombre.asc()).all()
    rotations = db.query(Rotation).order_by(Rotation.nombre.asc()).all()

    if not students:
        student_id = 0
    elif student_id == 0:
        student_id = students[0].id

    if not rotations:
        rotation_id = 0
    elif rotation_id == 0:
        rotation_id = rotations[0].id

    assigned_rows = []
    assigned_ids = set()
    if student_id and rotation_id:
        assigned_rows = (
            db.query(StudentTeacher)
            .join(Teacher, StudentTeacher.teacher_id == Teacher.id)
            .filter(StudentTeacher.student_id == student_id, StudentTeacher.rotation_id == rotation_id)
            .order_by(Teacher.nombre.asc())
            .all()
        )
        assigned_ids = {r.teacher_id for r in assigned_rows}

    return templates.TemplateResponse(
        "admin/profesores.html",
        {
            "request": request,
            "csrf_token": _csrf_for(request, auth["user"]),
            "teachers": teachers,
            "students": students,
            "rotations": rotations,
            "student_id": student_id,
            "rotation_id": rotation_id,
            "assigned_rows": assigned_rows,
            "assigned_ids": assigned_ids,
            "q": q,
            "role": auth["role"],
            "user": auth["user"],
            "current_year": current_year,
            "current_month": current_month,
            "active": "profesores",
            "title": "Profesores",
        },
    )


@app.post("/admin/profesores/create")
def admin_profesores_create(
    documento: str = Form(...),
    nombre: str = Form(...),
    pin: str = Form(...),
    especialidad: str = Form(""),
    activo: str = Form("1"),
    auth=Depends(require_roles(["admin"])),
    db: Session = Depends(get_db),
):
    seed_rotations(db)
    documento = (documento or "").strip()
    nombre = (nombre or "").strip()
    if len(documento) < 3 or len(nombre) < 3:
        raise HTTPException(status_code=400, detail="Documento/Nombre inválidos")

    if db.query(Teacher).filter(Teacher.documento == documento).first():
        raise HTTPException(status_code=400, detail="Ya existe un profesor con ese documento")

    raw_pin = (pin or "").strip()
    if not raw_pin.isdigit() or len(raw_pin) < 4 or len(raw_pin) > 8:
        raise HTTPException(status_code=400, detail="PIN inválido (solo números, 4 a 8 dígitos)")

    t = Teacher(
        documento=documento,
        nombre=nombre,
        username=None,
        password_hash=hash_password(raw_pin),
        especialidad=(especialidad or "").strip(),
        activo=(activo == "1"),
    )
    db.add(t)
    db.commit()
    db.refresh(t)

    # Crear cuenta de acceso para el docente
    db.add(Account(username=documento, password_hash=hash_password(raw_pin), role="docente", teacher_id=t.id, activo=t.activo))
    db.commit()
    add_admin_audit(db, "PROFESORES", "CREATE", auth["user"], f"documento={documento}")
    return RedirectResponse(url="/admin/profesores", status_code=303)


@app.post("/admin/profesores/update")
def admin_profesores_update(
    teacher_id: int = Form(...),
    documento: str = Form(...),
    nombre: str = Form(...),
    pin: str = Form(""),
    especialidad: str = Form(""),
    activo: str = Form("1"),
    auth=Depends(require_roles(["admin"])),
    db: Session = Depends(get_db),
):
    seed_rotations(db)
    t = db.query(Teacher).filter(Teacher.id == teacher_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Profesor no encontrado")

    documento = (documento or "").strip()
    nombre = (nombre or "").strip()
    if len(documento) < 3 or len(nombre) < 3:
        raise HTTPException(status_code=400, detail="Documento/Nombre inválidos")

    exists = db.query(Teacher).filter(Teacher.documento == documento, Teacher.id != teacher_id).first()
    if exists:
        raise HTTPException(status_code=400, detail="Ya existe otro profesor con ese documento")

    t.documento = documento
    t.nombre = nombre
    t.especialidad = (especialidad or "").strip()
    t.activo = (activo == "1")


    acct = db.query(Account).filter(Account.teacher_id == t.id, Account.role == "docente").first()
    if acct:
        acct.username = documento
        acct.activo = t.activo
    else:
        db.add(Account(username=documento, password_hash=t.password_hash, role="docente", teacher_id=t.id, activo=t.activo))

    if (pin or "").strip():
        raw_pin = pin.strip()
        if not raw_pin.isdigit() or len(raw_pin) < 4 or len(raw_pin) > 8:
            raise HTTPException(status_code=400, detail="PIN inválido (solo números, 4 a 8 dígitos)")
        t.password_hash = hash_password(raw_pin)
        if acct:
            acct.password_hash = t.password_hash
    db.commit()
    add_admin_audit(db, "PROFESORES", "UPDATE", auth["user"], f"id={teacher_id} documento={documento}")
    return RedirectResponse(url="/admin/profesores", status_code=303)


@app.post("/admin/profesores/delete")
def admin_profesores_delete(
    teacher_id: int = Form(...),
    auth=Depends(require_roles(["admin"])),
    db: Session = Depends(get_db),
):
    seed_rotations(db)
    t = db.query(Teacher).filter(Teacher.id == teacher_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Profesor no encontrado")

    # Seguridad: si ya hay ratings asociados a ese docente, NO borrar (mejor inactivar)
    used = db.query(Rating).filter(Rating.especialista_documento == t.documento).first()
    if used:
        raise HTTPException(status_code=400, detail="No se puede eliminar: el profesor ya tiene calificaciones registradas. (Recomendado: inactivar).")

    # borrar asignaciones
    db.query(StudentTeacher).filter(StudentTeacher.teacher_id == t.id).delete()
    db.query(Account).filter(Account.teacher_id == t.id, Account.role == "docente").delete()
    doc = t.documento
    db.delete(t)
    db.commit()
    add_admin_audit(db, "PROFESORES", "DELETE", auth["user"], f"documento={doc}")
    return RedirectResponse(url="/admin/profesores", status_code=303)


@app.post("/admin/profesores/assign")
def admin_profesores_assign(
    student_id: int = Form(...),
    rotation_id: int = Form(...),
    teacher_id: int = Form(...),
    auth=Depends(require_roles(["admin"])),
    db: Session = Depends(get_db),
):
    seed_rotations(db)

    st = db.query(Student).filter(Student.id == student_id).first()
    rot = db.query(Rotation).filter(Rotation.id == rotation_id).first()
    t = db.query(Teacher).filter(Teacher.id == teacher_id, Teacher.activo == True).first()
    if not st or not rot or not t:
        raise HTTPException(status_code=400, detail="Asignación inválida")

    exists = (
        db.query(StudentTeacher)
        .filter(StudentTeacher.student_id == student_id, StudentTeacher.rotation_id == rotation_id, StudentTeacher.teacher_id == teacher_id)
        .first()
    )
    if not exists:
        db.add(StudentTeacher(student_id=student_id, rotation_id=rotation_id, teacher_id=teacher_id))
        db.commit()
        add_admin_audit(db, "ASIGNACION_DOCENTES", "ASSIGN", auth["user"], f"student_id={student_id} rotation_id={rotation_id} teacher_id={teacher_id}")

    return RedirectResponse(url=f"/admin/profesores?student_id={student_id}&rotation_id={rotation_id}", status_code=303)


@app.post("/admin/profesores/unassign")
def admin_profesores_unassign(
    assign_id: int = Form(...),
    student_id: int = Form(...),
    rotation_id: int = Form(...),
    auth=Depends(require_roles(["admin"])),
    db: Session = Depends(get_db),
):
    seed_rotations(db)
    row = db.query(StudentTeacher).filter(StudentTeacher.id == assign_id).first()
    if row:
        db.delete(row)
        db.commit()
        add_admin_audit(db, "ASIGNACION_DOCENTES", "UNASSIGN", auth["user"], f"assign_id={assign_id}")
    return RedirectResponse(url=f"/admin/profesores?student_id={student_id}&rotation_id={rotation_id}", status_code=303)


# -------------------- ADMIN: CONTROL DE MES (POR ROTACIÓN) --------------------


def get_month_status(db: Session, rotation_id: int, year: int, mes: str) -> MonthControl:
    mc = (
        db.query(MonthControl)
        .filter(MonthControl.rotation_id == rotation_id, MonthControl.year == year, MonthControl.mes == mes)
        .first()
    )
    if not mc:
        mc = MonthControl(rotation_id=rotation_id, year=year, mes=mes, is_closed=False)
        db.add(mc)
        db.commit()
        db.refresh(mc)
    return mc


@app.get("/admin/mes", response_class=HTMLResponse)
def admin_mes(
    request: Request,
    year: int | None = None,
    mes: str = "",
    auth=Depends(require_roles(["admin","coord"])),
    db: Session = Depends(get_db),
):
    seed_rotations(db)
    current_year, current_month = now_year_month()
    year = year or current_year
    mes = (mes or "").strip() or current_month

    rotations = db.query(Rotation).order_by(Rotation.nombre.asc()).all()
    rows = []
    for rot in rotations:
        mc = get_month_status(db, rot.id, year, mes)
        rows.append({"rotation": rot, "mc": mc})

    return templates.TemplateResponse(
        "admin/mes.html",
        {
            "request": request,
            "csrf_token": _csrf_for(request, auth["user"]),
            "rows": rows,
            "year": year,
            "mes": mes,
            "role": auth["role"],
            "user": auth["user"],
            "current_year": current_year,
            "current_month": current_month,
            "active": "mes",
            "title": "Control de mes",
        },
    )


@app.post("/admin/mes/set")
def admin_mes_set(
    rotation_id: int = Form(...),
    year: int = Form(...),
    mes: str = Form(...),
    action: str = Form(...),
    notes: str = Form(""),
    auth=Depends(require_roles(["admin","coord"])),
    db: Session = Depends(get_db),
):
    seed_rotations(db)
    mes = (mes or "").strip()
    if not mes:
        raise HTTPException(status_code=400, detail="Mes inválido")

    rot = db.query(Rotation).filter(Rotation.id == rotation_id).first()
    if not rot:
        raise HTTPException(status_code=404, detail="Rotación no encontrada")

    mc = get_month_status(db, rotation_id, year, mes)
    if action == "close":
        mc.is_closed = True
        mc.actor = auth["user"]
        mc.notes = (notes or "").strip()
        mc.updated_at = datetime.utcnow()
        db.commit()
        add_admin_audit(db, "CONTROL_MES", "CLOSE", auth["user"], f"rotation={rot.nombre} {year}-{mes}")
    elif action == "open":
        mc.is_closed = False
        mc.actor = auth["user"]
        mc.notes = (notes or "").strip()
        mc.updated_at = datetime.utcnow()
        db.commit()
        add_admin_audit(db, "CONTROL_MES", "OPEN", auth["user"], f"rotation={rot.nombre} {year}-{mes}")
    else:
        raise HTTPException(status_code=400, detail="Acción inválida")

    return RedirectResponse(url=f"/admin/mes?year={year}&mes={mes}", status_code=303)


# -------------------- ADMIN: AUDITORÍA --------------------



@app.get("/admin/notas/detalle", response_class=HTMLResponse)
def admin_notas_detalle(
    request: Request,
    student_doc: str,
    rotation_id: int,
    mes: str,
    auth=Depends(require_roles(["admin","coord"])),
    db: Session = Depends(get_db),
):
    """Detalle de calificación por docente (desglose por áreas) para un estudiante en una rotación/mes."""
    seed_rotations(db)
    ensure_schema(db)

    student = db.query(Student).filter(Student.documento == student_doc).first()
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")

    rot = db.query(Rotation).filter(Rotation.id == rotation_id).first()
    if not rot:
        raise HTTPException(status_code=404, detail="Rotación no encontrada")

    # Docentes asignados activos
    ass_rows = (
        db.query(StudentTeacher, Teacher)
        .join(Teacher, StudentTeacher.teacher_id == Teacher.id)
        .filter(StudentTeacher.student_id == student.id, StudentTeacher.rotation_id == rotation_id, Teacher.activo == True)
        .all()
    )
    teachers = [t for _, t in ass_rows]
    teachers.sort(key=lambda x: (x.nombre or "").lower())

    # Ratings (no anulados) para el mes/rotación del estudiante
    ratings = (
        db.query(Rating)
        .filter(
            Rating.estudiante_documento == student.documento,
            Rating.rotation_id == rotation_id,
            Rating.mes == mes,
            Rating.is_void == False,
        )
        .all()
    )
    rating_by_teacher_doc = {}
    for r in ratings:
        tdoc = (getattr(r, "especialista_documento", "") or "").strip()
        rating_by_teacher_doc[tdoc] = r

    items = []
    for t in teachers:
        r = rating_by_teacher_doc.get((t.documento or "").strip())
        items.append({
            "teacher": t,
            "rating": r,
        })

    # promedios
    notas = [float(it["rating"].nota_definitiva) for it in items if it["rating"] and it["rating"].nota_definitiva is not None]
    promedio_parcial = round(sum(notas) / len(notas), 2) if notas else None
    definitiva_final = None
    if teachers and len(notas) == len(teachers) and promedio_parcial is not None:
        definitiva_final = promedio_parcial

    return templates.TemplateResponse(
        "admin/notas_detalle.html",
        {
            "request": request,
            "csrf_token": _csrf_for(request, auth["user"]),
            "student": student,
            "rotation": rot,
            "mes": mes,
            "items": items,
            "asignados": len(teachers),
            "evaluados": len(notas),
            "definitiva_provisional": promedio_parcial,
            "definitiva_final": definitiva_final,
            "role": auth["role"],
            "user": auth["user"],
            "active": "notas",
            "title": "Detalle de notas",
        },
    )



@app.get("/admin/auditoria", response_class=HTMLResponse)
def admin_auditoria(
    request: Request,
    tipo: str = "ratings",  # ratings | admin
    q: str = "",
    page: int = 1,
    auth=Depends(require_roles(["admin","coord"])),
    db: Session = Depends(get_db),
):
    seed_rotations(db)
    current_year, current_month = now_year_month()
    page = max(1, page)
    limit = 30
    offset = (page - 1) * limit

    like = f"%{q.strip()}%" if q else ""

    if tipo == "admin":
        qry = db.query(AdminAudit)
        if q:
            qry = qry.filter(or_(AdminAudit.module.ilike(like), AdminAudit.action.ilike(like), AdminAudit.actor.ilike(like), AdminAudit.details.ilike(like)))
        total = qry.count()
        items = qry.order_by(desc(AdminAudit.created_at)).limit(limit).offset(offset).all()
    else:
        qry = db.query(RatingAudit)
        if q:
            qry = qry.filter(or_(RatingAudit.action.ilike(like), RatingAudit.actor.ilike(like), RatingAudit.details.ilike(like)))
        total = qry.count()
        items = qry.order_by(desc(RatingAudit.created_at)).limit(limit).offset(offset).all()

    pages = max(1, (total + limit - 1) // limit)

    return templates.TemplateResponse(
        "admin/auditoria.html",
        {
            "request": request,
            "csrf_token": _csrf_for(request, auth["user"]),
            "tipo": tipo,
            "items": items,
            "q": q,
            "page": page,
            "pages": pages,
            "total": total,
            "role": auth["role"],
            "user": auth["user"],
            "current_year": current_year,
            "current_month": current_month,
            "active": "audit",
            "title": "Auditoría",
        },
    )


# -------------------- ADMIN: REPORTES --------------------


@app.get("/admin/reportes", response_class=HTMLResponse)
def admin_reportes(
    request: Request,
    q: str = "",
    # In HTML forms, an empty <select> value is submitted as an empty string
    # (rotation_id=). If we typed this as int, FastAPI would raise a 422.
    # So we accept str and coerce safely.
    rotation_id: str = "",
    mes: str = "",
    status: str = "",
    auth=Depends(require_roles(["admin","coord"])),
    db: Session = Depends(get_db),
):
    seed_rotations(db)
    current_year, current_month = now_year_month()
    rotations = db.query(Rotation).order_by(Rotation.nombre.asc()).all()

    rotation_id_int = parse_rotation_id(rotation_id)

    total, items = query_ratings(
        db,
        q=q,
        rotation_id=rotation_id_int,
        mes=mes,
        status=status,
        # We keep a high limit for exports, but for the dashboard we also
        # show a quick preview table. Datasets are usually small (< a few
        # thousand). Adjust if needed.
        limit=5000,
        offset=0,
    )

    # ✅ Stats based on filtered results (more intuitive for users)
    if total:
        avg = round(sum((r.nota_definitiva or 0) for r in items) / total, 2)
        abiertos = sum(1 for r in items if (not r.is_void and not r.is_closed))
        cerrados = sum(1 for r in items if (not r.is_void and r.is_closed))
        anulados = sum(1 for r in items if r.is_void)
    else:
        avg = None
        abiertos = cerrados = anulados = 0

    preview = items[:25]

    # ✅ Consolidado por estudiante/rotación/mes (promedio de profesores)
    # Solo toma registros NO anulados.
    consol_map = {}
    for r in items:
        if r.is_void:
            continue
        key = (
            r.estudiante_documento,
            r.estudiante_nombre,
            r.rotation_id,
            r.rotation.nombre if r.rotation else "",
            r.mes,
            getattr(r, "year", current_year),
        )
        obj = consol_map.get(key)
        if not obj:
            obj = {
                "documento": r.estudiante_documento,
                "nombre": r.estudiante_nombre,
                "rotation_id": r.rotation_id,
                "rotacion": r.rotation.nombre if r.rotation else "",
                "mes": r.mes,
                "year": getattr(r, "year", current_year),
                "profesores": set(),
                "notas": [],
                "all_closed": True,
            }
            consol_map[key] = obj

        # Profesor (documento si existe, si no, nombre)
        prof_key = (getattr(r, "especialista_documento", "") or "").strip() or (r.especialista_nombre or "").strip()
        if prof_key:
            obj["profesores"].add(prof_key)

        if r.nota_definitiva is not None:
            obj["notas"].append(float(r.nota_definitiva))

        if not r.is_closed:
            obj["all_closed"] = False

    consolidated = []
    for _, obj in consol_map.items():
        if obj["notas"]:
            obj["promedio"] = round(sum(obj["notas"]) / len(obj["notas"]), 2)
        else:
            obj["promedio"] = None
        obj["n_profes"] = len(obj["profesores"])
        obj["estado"] = "CERRADO" if obj["all_closed"] else "ABIERTO"
        consolidated.append(obj)

    # Orden: peor promedio primero (si existe), luego nombre
    consolidated.sort(
        key=lambda x: (
            x["promedio"] is None,
            x["promedio"] if x["promedio"] is not None else 999,
            x["nombre"],
        )
    )

    return templates.TemplateResponse(
        "admin/reportes.html",
        {
            "request": request,
            "csrf_token": _csrf_for(request, auth["user"]),
            "rotations": rotations,
            "q": q,
            "rotation_id": rotation_id_int,
            "mes": mes,
            "status": status,
            "total": total,
            "avg": avg,
            "abiertos": abiertos,
            "cerrados": cerrados,
            "anulados": anulados,
            "preview": preview,
            "consolidated": consolidated,
            "role": auth["role"],
            "user": auth["user"],
            "current_year": current_year,
            "current_month": current_month,
            "active": "reports",
            "title": "Reportes",
        },
    )




# -------------------- ADMIN: NOTAS (por docente) --------------------

@app.get("/admin/notas", response_class=HTMLResponse)
def admin_notas(
    request: Request,
    rotation_id: int | None = None,
    mes: str = "",
    auth=Depends(require_roles(["admin","coord"])),
    db: Session = Depends(get_db),
):
    seed_rotations(db)
    current_year, current_month = now_year_month()

    # Meses (mismo catálogo del formulario)
    meses = [
        "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
    ]
    mes_actual = meses[datetime.now().month - 1]
    mes_sel = mes.strip() if mes and mes.strip() in meses else mes_actual

    rotations = db.query(Rotation).filter(Rotation.activa == True).order_by(Rotation.nombre.asc()).all()
    if not rotations:
        rotations = db.query(Rotation).order_by(Rotation.nombre.asc()).all()

    rot_id = rotation_id if rotation_id else (rotations[0].id if rotations else 1)

    # Traer estudiantes activos
    students = db.query(Student).filter(Student.activa == True).order_by(Student.nombre.asc()).all()

    # Asignaciones por estudiante (solo para esta rotación)
    ass_rows = (
        db.query(StudentTeacher, Teacher)
        .join(Teacher, StudentTeacher.teacher_id == Teacher.id)
        .filter(StudentTeacher.rotation_id == rot_id, Teacher.activo == True)
        .all()
    )

    teachers_by_student_id: dict[int, list[Teacher]] = {}
    for stt, t in ass_rows:
        teachers_by_student_id.setdefault(stt.student_id, []).append(t)

    # Ordenar profesores por nombre dentro de cada estudiante
    for sid, tlist in teachers_by_student_id.items():
        tlist.sort(key=lambda x: (x.nombre or "").lower())

    # Máximo de docentes asignados (para slots de columna Docente 1..N)
    teacher_slots = max([len(v) for v in teachers_by_student_id.values()] + [0])
    teacher_slots = max(teacher_slots, 1)

    # Ratings del mes/rotación (NO anulados)
    ratings = (
        db.query(Rating)
        .filter(
            Rating.rotation_id == rot_id,
            Rating.mes == mes_sel,
            Rating.is_void == False,
        )
        .all()
    )

    # index por (doc_estudiante, docente_documento)
    rating_map = {}
    for r in ratings:
        tdoc = ((getattr(r, "especialista_documento", "") or "").strip() or (getattr(r, "actor", "") or "").strip())
        key = (r.estudiante_documento, tdoc)
        rating_map[key] = r

    rows = []
    # construimos tabla: un registro por estudiante (aunque no tenga asignación)
    for st in students:
        tlist = teachers_by_student_id.get(st.id, [])

        teachers_out = []
        notas = []
        evaluados = 0

        for t in tlist:
            tkey = ((t.documento or "").strip() or (t.username or "").strip())
            r = rating_map.get((st.documento, tkey))
            nota = None
            if r and r.nota_definitiva is not None:
                nota = float(r.nota_definitiva)
                notas.append(nota)
                evaluados += 1
            teachers_out.append({
                "nombre": t.nombre,
                "documento": t.documento,
                "nota": nota,
            })

        asignados = len(tlist)
        promedio_parcial = None
        if notas:
            promedio_parcial = round(sum(notas) / len(notas), 2)

        definitiva = None
        if asignados > 0 and evaluados == asignados and promedio_parcial is not None:
            # ✅ Promedio simple de las notas definitivas de los docentes asignados
            definitiva = promedio_parcial

        rows.append({
            "documento": st.documento,
            "nombre": st.nombre,
            "rotation_id": rot_id,
            "rotation_nombre": (db.query(Rotation).filter(Rotation.id == rot_id).first().nombre if rot_id else ""),
            "mes": mes_sel,
            "teachers": teachers_out,
            "asignados": asignados,
            "evaluados": evaluados,
            "definitiva_provisional": promedio_parcial,
            "definitiva_final": definitiva,
            "promedio_parcial": promedio_parcial,
            "definitiva": definitiva,
        })

    # Ordenar: pendientes primero, luego definitiva asc, luego nombre
    def sort_key(x):
        pending = (x["asignados"] > 0 and x["evaluados"] < x["asignados"])
        # definitiva None -> big
        d = x["definitiva"] if x["definitiva"] is not None else 999
        return (not pending, d, x["nombre"] or "")

    rows.sort(key=sort_key)

    return templates.TemplateResponse(
        "admin/notas.html",
        {
            "request": request,
            "csrf_token": _csrf_for(request, auth["user"]),
            "rotations": rotations,
            "rotation_id": rot_id,
            "meses": meses,
            "mes": mes_sel,
            "teacher_slots": teacher_slots,
            "rows": rows,
            "role": auth["role"],
            "user": auth["user"],
            "current_year": current_year,
            "current_month": current_month,
            "active": "notas",
            "title": "Notas",
        },
    )




@app.get("/admin/notas.xlsx")
def admin_notas_export_excel(
    rotation_id: int,
    mes: str = "",
    auth=Depends(require_roles(["admin","coord"])),
    db: Session = Depends(get_db),
):
    """Exporta el módulo Notas a Excel (XLSX)."""
    seed_rotations(db)
    meses = ["Enero","Febrero","Marzo","Abril","Mayo","Junio","Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]
    mes_actual = meses[datetime.now().month - 1]
    mes_sel = mes.strip() if mes and mes.strip() in meses else mes_actual

    rot = db.query(Rotation).filter(Rotation.id == rotation_id).first()
    rot_name = rot.nombre if rot else str(rotation_id)

    # Estudiantes activos
    students = db.query(Student).filter(Student.activa == True).order_by(Student.nombre.asc()).all()

    # Asignaciones docentes por estudiante (solo para esta rotación)
    ass_rows = (
        db.query(StudentTeacher, Teacher)
        .join(Teacher, StudentTeacher.teacher_id == Teacher.id)
        .filter(StudentTeacher.rotation_id == rotation_id, Teacher.activo == True)
        .all()
    )
    teachers_by_student_id: dict[int, list[Teacher]] = {}
    for stt, t in ass_rows:
        teachers_by_student_id.setdefault(stt.student_id, []).append(t)
    for sid, tlist in teachers_by_student_id.items():
        tlist.sort(key=lambda x: (x.nombre or "").lower())
    teacher_slots = max([len(v) for v in teachers_by_student_id.values()] + [0])
    teacher_slots = max(teacher_slots, 1)

    # Ratings del mes/rotación (NO anulados)
    ratings = (
        db.query(Rating)
        .filter(
            Rating.rotation_id == rotation_id,
            Rating.mes == mes_sel,
            Rating.is_void == False,
        )
        .all()
    )
    rating_map = {}
    for r in ratings:
        tdoc = (getattr(r, "especialista_documento", "") or "").strip()
        rating_map[(r.estudiante_documento, tdoc)] = r

    wb = Workbook()
    ws = wb.active
    ws.title = "Notas"

    headers = ["Documento", "Estudiante", "Rotación", "Mes", "Asignados", "Evaluados", "Definitiva provisional", "Definitiva final", "Estado"]
    for i in range(teacher_slots):
        headers.extend([f"Docente {i+1}", f"Docente {i+1} Doc", f"Nota {i+1}"])
    ws.append(headers)

    for st in students:
        tlist = teachers_by_student_id.get(st.id, [])
        asignados = len(tlist)
        notas = []
        evaluados = 0

        teacher_cells = []
        for t in tlist:
            tkey = ((t.documento or "").strip() or (t.username or "").strip())
            r = rating_map.get((st.documento, tkey))
            nota = None
            if r and r.nota_definitiva is not None:
                nota = float(r.nota_definitiva)
                notas.append(nota)
                evaluados += 1
            teacher_cells.extend([t.nombre, t.documento, (round(nota,2) if nota is not None else "")])

        # rellenar slots
        missing = teacher_slots - len(tlist)
        for _ in range(missing):
            teacher_cells.extend(["", "", ""])

        prov = round(sum(notas)/len(notas), 2) if notas else None
        final = prov if (asignados > 0 and evaluados == asignados and prov is not None) else None

        if asignados == 0:
            estado = "SIN ASIGNACION"
        elif evaluados < asignados:
            estado = "PENDIENTE"
        else:
            estado = "COMPLETO"

        row = [
            st.documento,
            st.nombre,
            rot_name,
            mes_sel,
            asignados,
            evaluados,
            prov if prov is not None else "",
            final if final is not None else "",
            estado,
        ] + teacher_cells
        ws.append(row)

    # autosize simple
    for col in ws.columns:
        max_len = 0
        col_letter = col[0].column_letter
        for cell in col:
            val = "" if cell.value is None else str(cell.value)
            max_len = max(max_len, len(val))
        ws.column_dimensions[col_letter].width = min(max_len + 2, 40)

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)

    filename = f"Notas_{rot_name}_{mes_sel}.xlsx".replace(" ", "_")
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(out, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=headers)


def render_acta_pdf_bytes(
    estudiante: Student,
    rotation: Rotation,
    mes: str,
    year: int,
    teachers: list[Teacher],
    ratings_by_teacher_doc: dict[str, Rating],
    definitiva_prov: float | None,
    definitiva_final: float | None,
) -> bytes:
    """Genera el Acta de Calificación consolidada (PDF) por estudiante y rotación."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    w, h = letter
    y = h - 50

    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, "ACTA DE CALIFICACIÓN · INTERNADO MÉDICO (DS-F-01)")
    y -= 22

    # Marca de agua cuando aún no está consolidada la definitiva final
    if definitiva_final is None:
        c.saveState()
        c.setFillGray(0.85)
        c.setFont("Helvetica-Bold", 60)
        c.translate(w/2, h/2)
        c.rotate(30)
        c.drawCentredString(0, 0, "PRELIMINAR")
        c.restoreState()

    c.setFont("Helvetica", 10)
    c.drawString(50, y, f"Fecha de generación: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    y -= 14
    c.drawString(50, y, f"Estudiante: {estudiante.nombre}  |  Documento: {estudiante.documento}")
    y -= 14
    c.drawString(50, y, f"Universidad: {estudiante.universidad}  |  Semestre: {estudiante.semestre}")
    y -= 14
    c.drawString(50, y, f"Rotación: {rotation.nombre}  |  Mes/Año: {mes} {year}")
    y -= 18

    c.setFont("Helvetica-Bold", 11)
    c.drawString(50, y, "Notas por docente (nota definitiva)")
    y -= 16
    c.setFont("Helvetica", 10)

    if not teachers:
        c.drawString(60, y, "SIN DOCENTES ASIGNADOS")
        y -= 14
    else:
        for idx, t in enumerate(teachers, start=1):
            r = ratings_by_teacher_doc.get((t.documento or "").strip())
            nota = (f"{float(r.nota_definitiva):.2f}" if r and r.nota_definitiva is not None else "-")
            fecha_txt = (r.created_at.strftime("%Y-%m-%d %H:%M") if r and getattr(r, "created_at", None) else "-")
            especialista = (r.especialista_nombre if r and getattr(r, "especialista_nombre", None) else "-")
            c.setFont("Helvetica-Bold", 10)
            c.drawString(60, y, f"{idx}. {t.nombre} ({t.documento})  ->  {nota}")
            y -= 12
            c.setFont("Helvetica", 9)
            c.drawString(72, y, f"Registrada: {fecha_txt}  |  Especialista: {especialista}")
            y -= 10
            if r:
                c.drawString(72, y, f"Cognitiva: {r.cognitiva}  |  Aptitudinal: {r.aptitudinal}  |  Actitudinal: {r.actitudinal}")
                y -= 10
                c.drawString(72, y, f"Evaluacion: {r.evaluacion}  |  CPC: {r.cpc}  |  % Fallas: {r.fallas_percent}")
                y -= 12
            else:
                y -= 6
            if y < 120:
                c.showPage()
                y = h - 50
                c.setFont("Helvetica", 10)

    y -= 8
    c.setFont("Helvetica-Bold", 11)
    c.drawString(50, y, "Resultado")
    y -= 16
    c.setFont("Helvetica", 10)

    prov_txt = f"{definitiva_prov:.2f}" if definitiva_prov is not None else "—"
    fin_txt = f"{definitiva_final:.2f}" if definitiva_final is not None else "—"

    c.drawString(60, y, f"Definitiva provisional: {prov_txt}")
    y -= 14
    c.drawString(60, y, f"Definitiva final: {fin_txt}")

    y -= 18
    estado = "SIN ASIGNACIÓN" if not teachers else ("PENDIENTE" if definitiva_final is None else "COMPLETO")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, f"Estado: {estado}")

    c.setFont("Helvetica-Oblique", 8)
    c.drawString(50, 40, "Elaborado por Eneldo Vanstralhen · Ingeniero de Sistemas.")
    c.showPage()
    c.save()
    return buf.getvalue()


@app.get("/admin/acta.pdf")
def admin_acta_pdf(
    student_doc: str,
    rotation_id: int,
    mes: str = "",
    auth=Depends(require_roles(["admin","coord"])),
    db: Session = Depends(get_db),
):
    """Acta PDF consolidada por estudiante + rotación + mes."""
    seed_rotations(db)
    meses = ["Enero","Febrero","Marzo","Abril","Mayo","Junio","Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]
    mes_actual = meses[datetime.now().month - 1]
    mes_sel = mes.strip() if mes and mes.strip() in meses else mes_actual
    year_now = datetime.now().year

    st = db.query(Student).filter(Student.documento == student_doc.strip()).first()
    if not st:
        raise HTTPException(status_code=404, detail="Estudiante no existe")

    rot = db.query(Rotation).filter(Rotation.id == rotation_id).first()
    if not rot:
        raise HTTPException(status_code=404, detail="Rotación no existe")

    # Docentes asignados (activos) en esa rotación
    ass_rows = (
        db.query(StudentTeacher, Teacher)
        .join(Teacher, StudentTeacher.teacher_id == Teacher.id)
        .filter(
            StudentTeacher.student_id == st.id,
            StudentTeacher.rotation_id == rotation_id,
            Teacher.activo == True,
        )
        .all()
    )
    teachers = [t for _, t in ass_rows]
    teachers.sort(key=lambda x: (x.nombre or "").lower())

    # Ratings
    rated = (
        db.query(Rating)
        .filter(
            Rating.estudiante_documento == st.documento,
            Rating.rotation_id == rotation_id,
            Rating.year == year_now,
            Rating.mes == mes_sel,
            Rating.is_void == False,
        )
        .all()
    )
    ratings_by_teacher_doc = {(getattr(r,"especialista_documento","") or "").strip(): r for r in rated}

    notas = []
    evaluados = 0
    for t in teachers:
        r = ratings_by_teacher_doc.get((t.documento or "").strip())
        if r and r.nota_definitiva is not None:
            notas.append(float(r.nota_definitiva))
            evaluados += 1

    asignados = len(teachers)
    prov = round(sum(notas)/len(notas), 2) if notas else None
    final = prov if (asignados > 0 and evaluados == asignados and prov is not None) else None

    pdf_bytes = render_acta_pdf_bytes(st, rot, mes_sel, year_now, teachers, ratings_by_teacher_doc, prov, final)
    filename = f"Acta_{st.documento}_{rot.nombre}_{mes_sel}_{year_now}.pdf".replace(" ", "_")
    headers = {"Content-Disposition": f'inline; filename="{filename}"'}
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)



# -------------------- ADMIN: QR / ENLACES --------------------


@app.get("/admin/qr", response_class=HTMLResponse)
def admin_qr(
    request: Request,
    rotation_id: int | None = None,
    mes: str = "",
    auth=Depends(require_roles(["admin","coord"])),
    db: Session = Depends(get_db),
):
    seed_rotations(db)
    current_year, current_month = now_year_month()

    rotations = db.query(Rotation).order_by(Rotation.nombre.asc()).all()
    if not rotations:
        raise HTTPException(status_code=400, detail="No hay rotaciones")

    selected_rotation_id = rotation_id or rotations[0].id
    if not any(r.id == selected_rotation_id for r in rotations):
        selected_rotation_id = rotations[0].id

    mes_sel = (mes or "").strip() or current_month
    form_url = build_form_url(selected_rotation_id, mes_sel)
    wa_url, _msg = build_whatsapp_url(
        next(r.nombre for r in rotations if r.id == selected_rotation_id),
        form_url,
        "",
    )

    return templates.TemplateResponse(
        "admin/qr.html",
        {
            "request": request,
            "csrf_token": _csrf_for(request, auth["user"]),
            "rotations": rotations,
            "selected_rotation_id": selected_rotation_id,
            "mes": mes_sel,
            "form_url": form_url,
            "wa_url": wa_url,
            "public_base": public_base_url(),
            "role": auth["role"],
            "user": auth["user"],
            "current_year": current_year,
            "current_month": current_month,
            "active": "qr",
            "title": "QR / Enlaces",
        },
    )
