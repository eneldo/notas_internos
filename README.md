# Sistema de calificación – Internado Médico (DS-F-01)

Versión base con **Login único** (usuario/contraseña) y redirección automática por **ROL**:
- **Admin / Coordinador / Evaluador** → Módulo **Administración**
- **Docente** → **Portal Docente**

Incluye:
- Módulo Administración (estudiantes, rotaciones, docentes, auditoría, reportes, exportes)
- Portal Docente (asignaciones por rotación, calificación, evidencias)
- Base de datos configurable por `DATABASE_URL` (SQLite local / PostgreSQL producción)

---

## Ejecutar en local (VS Code / Windows)
```bat
cd plataforma_notas
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## URLs
- Login:            http://127.0.0.1:8000/login
- Admin:            http://127.0.0.1:8000/admin
- Portal Docente:   http://127.0.0.1:8000/profesor
- Cerrar sesión:    http://127.0.0.1:8000/logout

---

## Credenciales iniciales (solo primera instalación)
Si la tabla `accounts` está vacía, el sistema crea automáticamente:
- **Usuario:** `admin`
- **Contraseña:** `Admin123*`

⚠️ En producción **cámbialo** usando variables de entorno:
- `INIT_ADMIN_USER`
- `INIT_ADMIN_PASS`
- `INIT_COORD_USER` (opcional)
- `INIT_COORD_PASS` (opcional)

---

## Producción (Hostinger)
Recomendado: **Hostinger VPS** (Ubuntu) + **Docker** o ejecución directa con Python.

Variables importantes:
- `APP_SECRET_KEY` (obligatorio en producción)
- `DATABASE_URL` (PostgreSQL recomendado)
  - Ejemplo: `postgresql+psycopg2://USER:PASS@HOST:5432/DBNAME`

Notas:
- En local puedes usar SQLite: `sqlite:///./data/app.db`
- Para internet, usa PostgreSQL y un reverse proxy (Nginx) con HTTPS.


## Producción (VPS/Dokploy): Migraciones + Seguridad

- Define `ENV=production`.
- Define `APP_SECRET_KEY` (obligatorio en producción).
- Si la base de datos está vacía, define `INIT_ADMIN_USER` y `INIT_ADMIN_PASS`.

### Migraciones con Alembic

1. Instala dependencias:

```bash
pip install -r requirements.txt
```

2. Aplica migraciones:

```bash
alembic upgrade head
```

3. Ejecuta la app.

### Auth
- **Web:** cookie de sesión firmada (HttpOnly + Secure en producción) + CSRF.
- **API:** JWT en `/api/auth/token`.
- **Rate limiting:** SlowAPI.
- **Lockout:** bloqueo tras 5 intentos fallidos, auditoría en `auth_events`.


## Seguridad - Nivel Enterprise

- JWT Access Token: 60 min
- Refresh token (rotación): 30 días. Endpoint `POST /api/auth/refresh`
- Detección de reutilización de refresh token: revoca todos los refresh tokens activos.
- Logs JSON con `X-Request-ID` (correlación).
- CSP estricto sin `unsafe-inline`.
- MFA TOTP opcional para `admin` (UI: `/admin/mfa/setup`).
- Preflight: `python scripts/preflight_check.py`

### Traefik (Dokploy)
El `docker-compose.yml` incluye labels ejemplo para HSTS y headers.
Configura `DOMAIN` en Dokploy.


## Deploy en Dokploy (VPS) — Repo `notas_internos` + dominio `vaner.cloud`

### Recomendación de dominio
Usa un **subdominio dedicado** para la app:
- `notas_internos.vaner.cloud` (recomendado)

En Dokploy define `DOMAIN=notas_internos.vaner.cloud`.

### Variables de entorno mínimas (Dokploy)
- `ENV=production`
- `APP_SECRET_KEY=<valor largo y aleatorio>`
- `DOMAIN=notas_internos.vaner.cloud`
- `POSTGRES_DB=B_D_Internos`
- `POSTGRES_USER=internos_user`
- `POSTGRES_PASSWORD=<fuerte>`
- `DATABASE_URL=postgresql+psycopg2://internos_user:<password>@db:5432/B_D_Internos`
- `INIT_ADMIN_USER=admin`
- `INIT_ADMIN_PASS=<fuerte>`

### HSTS / Preload
El compose deja `stsPreload=false` por seguridad.
Actívalo (`true`) **solo si**:
1) Tu dominio y **todos** los subdominios van a estar siempre en HTTPS
2) Estás listo para mantener HTTPS permanente

### MFA (admin)
Después del primer login como admin:
- entra a `/admin/mfa/setup`
- escanea el QR con Google Authenticator / Authy
- verifica el código para activar MFA

## Verificaciones antes de exponer a Internet
En local (o en el contenedor) ejecuta:
- `python scripts/preflight_check.py`
- `bash scripts/smoke.sh`

Luego en staging (con HTTPS) valida:
- rate limiting en `/login` (debe dar 429 tras abusar)
- lockout tras 5 fallos
- refresh token rotation (reuso debe invalidar sesiones)
- CSP strict: no debe bloquear recursos legítimos
