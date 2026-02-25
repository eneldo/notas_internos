#!/usr/bin/env python3
from __future__ import annotations
import os, sys, re, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]

def fail(msg: str) -> None:
    print(f"[FAIL] {msg}")
    sys.exit(1)

def warn(msg: str) -> None:
    print(f"[WARN] {msg}")

def ok(msg: str) -> None:
    print(f"[OK] {msg}")

def read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")

def main() -> None:
    # 1) secrets in repo
    if (ROOT / ".env").exists():
        fail(".env existe en el repositorio. NO lo subas a GitHub. Usa variables en Dokploy.")
    ok("No hay .env en el repo")

    # 2) docker-compose syntax (basic)
    compose = read(ROOT / "docker-compose.yml")
    if "traefik.http.routers.notas_internos.rule" not in compose:
        warn("No se detectó router Traefik 'notas_internos'. Verifica labels si usarás Traefik.")
    ok("docker-compose.yml presente")

    # 3) CSP strict in middleware
    main_py = read(ROOT / "app" / "main.py")
    if "Content-Security-Policy" not in main_py:
        warn("No se detectó CSP en main.py.")
    if "unsafe-inline" in main_py:
        fail("CSP contiene 'unsafe-inline'. Debe ser estricto para production hardening.")
    ok("CSP estricto (sin unsafe-inline)")

    # 4) templates inline checks
    tpl_dir = ROOT / "app" / "templates"
    inline_hits = []
    for p in tpl_dir.rglob("*.html"):
        s = read(p)
        if re.search(r"<script[^>]*>(?!\s*</script>)", s, re.I) or re.search(r"<style", s, re.I) or re.search(r"\sstyle\s*=", s, re.I):
            inline_hits.append(str(p.relative_to(ROOT)))
    if inline_hits:
        fail("Templates con inline script/style (incompatibles con CSP strict):\n  - " + "\n  - ".join(inline_hits))
    ok("Templates compatibles con CSP strict (sin inline)")

    # 5) alembic
    if not (ROOT / "alembic.ini").exists() or not (ROOT / "alembic").exists():
        fail("Alembic no está configurado (falta alembic.ini o carpeta alembic/).")
    ok("Alembic presente")

    # 6) env example sanity
    envex = read(ROOT / ".env.example")
    if "APP_SECRET_KEY=change-me" in envex:
        warn("APP_SECRET_KEY en .env.example es placeholder. En Dokploy debe ser un valor largo/aleatorio.")
    ok("Preflight completado")

if __name__ == "__main__":
    main()
