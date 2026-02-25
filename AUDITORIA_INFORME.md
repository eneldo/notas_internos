# Auditoría técnica – platafora_NOtas_funcional

Fecha: 2026-01-30 20:49:02

## 1) Resumen ejecutivo
Se revisó el proyecto **Sistema de calificación por QR – Internado Médico (DS-F-01) v3** (Portal Docente + Admin/Coordinador/Evaluador).
El objetivo fue verificar que:
- No existan errores críticos (500 por validaciones, templates faltantes, rutas rotas).
- El módulo docente **guarde calificaciones** sin errores.
- Se incluya validación **0–5** con **toast (✅/⚠️/⛔)** sin recargar y bloqueo estricto de entrada.
- La configuración de BD y rutas sea consistente para entorno local.

**Resultado:** El software queda funcional para uso local con SQLite (por defecto) y soporta PostgreSQL vía `DATABASE_URL`.

## 2) Qué hace el software (funcionalidades)
### 2.1 Flujo principal de calificación
- Los estudiantes se registran y se asignan a rotaciones.
- Se generan enlaces/QR por rotación y mes.
- Un usuario autorizado diligencia el formato (DS-F-01) y se almacena la calificación.
- Se calcula promedio y se guarda evidencia para auditoría.

### 2.2 Módulos / Roles
**Inicio**
- `/` Página de inicio.

**Admin / Coordinador / Evaluador (HTTP Basic Auth)**
- Admin: gestión completa (rotaciones, estudiantes, reportes, auditoría).
- Coordinador: listado y reportes.
- Evaluador: evaluación (según reglas del proyecto).

**Portal Docente**
- Login docente `/profesor/login` (sesión por cookie).
- Dashboard `/profesor` con asignaciones.
- Formulario docente `/profesor/calificar?student_id=...&rotation_id=...&mes=...`
- Guardado docente `POST /profesor/ratings/create`

### 2.3 Reportes y evidencias
- Export Excel/CSV.
- Generación PDF por registro (evidencia).
- Anulación/cierre y auditoría mínima.

## 3) Arquitectura técnica (alto nivel)
- **Backend:** FastAPI + Jinja2
- **ORM:** SQLAlchemy
- **BD por defecto:** SQLite `./data/app.db` (cambiable con `DATABASE_URL`)
- **Archivos estáticos:** `/static` (CSS/JS)
- **Plantillas:** `app/templates/*`

## 4) Revisión de rutas/plantillas (verificación)
Se validó que todas las plantillas referenciadas por `TemplateResponse(...)` existen:
- `home.html`
- `rate.html`
- `profesor/login.html`, `profesor/dashboard.html`, `profesor/rate.html`
- `admin/*.html` (auditoría, estudiantes, reportes, rotaciones, etc.)

No se detectaron referencias a plantillas inexistentes.

## 5) Validaciones críticas implementadas
### 5.1 Notas 0–5 (Docente)
- **Frontend:** inputs `min=0 max=5`, bloqueo de teclado/pegado y clamping.
- **Toast sin recargar:** muestra aviso y ajusta valores.
- **Backend:** validación defensiva 0–5 (evita 500 si el navegador permite valores fuera de rango).

### 5.2 CSRF (Docente)
- Token CSRF firmado por usuario + salt del path del POST.
- El formulario docente incluye `csrf_token` y el servidor lo verifica en el POST.

## 6) Cambios/correcciones aplicadas en esta versión
1. Se eliminó del formulario docente la sección **“Firmas y validación”** (Coordinador/Firma estudiante) por no ser relevante.
2. Se corrigió el guardado docente para que **no falle** por campos inexistentes/ vacíos.
3. Se agregó **toast con iconos** (✅/⚠️/⛔) y validación estricta para impedir valores fuera del rango.
4. Se añadió `APP_SECRET_KEY` en `.env` para no depender de contraseñas como secreto criptográfico.

## 7) Configuración (importante)
### 7.1 Variables de entorno
En `.env`:
- `PUBLIC_BASE_URL`: base para links/QR (en local: `http://127.0.0.1:8000`)
- `APP_SECRET_KEY`: secreto para firmar tokens (CSRF y sesión docente).
- Credenciales Basic Auth:
  - `ADMIN_USER`, `ADMIN_PASS`
  - `COORD_USER`, `COORD_PASS`
  - `EVAL_USER`, `EVAL_PASS`
- `DATABASE_URL` (opcional):
  - SQLite (default): `sqlite:///./data/app.db`
  - PostgreSQL: `postgresql+psycopg2://user:pass@host:5432/db`

> Si usas PostgreSQL instala driver (`psycopg2-binary` o `psycopg`).

### 7.2 Puertos
Por defecto corre en **8000**. Puedes cambiar con `--port`.

## 8) Recomendaciones (no bloqueantes)
- En despliegue HTTPS: marcar cookie docente con `secure=True` y `samesite="lax/strict"` según necesidad.
- Rotar credenciales por ambiente (no dejar contraseñas por defecto).
- Agregar logs de auditoría más detallados (usuario, IP, user-agent).

## 9) Estado final
✅ Proyecto empaquetado como **platafora_NOtas_funcional** y listo para ejecutar en Windows con VS Code.
