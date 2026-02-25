#!/usr/bin/env bash
set -euo pipefail

echo "[1/4] Preflight checks"
python scripts/preflight_check.py

echo "[2/4] Import checks"
python -c "import importlib, sys; 
missing=[]
for m in ('fastapi','slowapi','sqlalchemy'):
    try: importlib.import_module(m)
    except Exception: missing.append(m)
if missing:
    print('[SKIP] Dependencias no instaladas en este entorno:', ','.join(missing))
    sys.exit(0)
import app.main; print('Imports OK')"

echo "[3/4] Alembic config check (no DB connection)"
python -c "from configparser import ConfigParser; c=ConfigParser(); c.read('alembic.ini'); assert c.get('alembic','script_location'); print('Alembic config OK')"

echo "[4/4] Done"
echo "Si quieres probar con BD real: export DATABASE_URL=... y ejecuta: alembic upgrade head"
