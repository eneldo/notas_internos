import os
from urllib.parse import quote
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

def public_base_url(default: str = "http://localhost:8000") -> str:
    return os.getenv("PUBLIC_BASE_URL", default).rstrip("/")

def build_form_url(rotation_id: int, mes: str = "") -> str:
    url = f"{public_base_url()}/rate?r={rotation_id}"
    if mes:
        url += f"&mes={mes}"
    return url

def build_whatsapp_url(rotation_name: str, form_url: str, phone: str = "") -> tuple[str,str]:
    msg = f"Calificación Internado Médico (DS-F-01) – Rotación {rotation_name}: {form_url}"
    wa = "https://wa.me/"
    if phone:
        wa += phone
    wa += f"?text={quote(msg)}"
    return wa, msg

def numero_a_letras_nota(n: float) -> str:
    unidades = ["CERO","UNO","DOS","TRES","CUATRO","CINCO","SEIS","SIETE","OCHO","NUEVE"]
    entero = int(n)
    dec = int(round((n - entero) * 10))
    entero = max(0, min(entero, 5))
    dec = max(0, min(dec, 9))
    return f"{unidades[entero]} PUNTO {unidades[dec]}"

def render_rating_pdf(rating, rotation_name: str) -> bytes:
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    w, h = letter
    y = h - 50

    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, "DS-F-01 · CALIFICACIÓN PROGRAMA INTERNADO MÉDICO")
    y -= 22

    c.setFont("Helvetica", 10)
    c.drawString(50, y, f"Registro ID: {rating.id}   Fecha: {rating.created_at.strftime('%Y-%m-%d %H:%M')}")
    y -= 16
    c.drawString(50, y, f"Rotación: {rotation_name}   Mes: {rating.mes}   Semestre: {rating.semestre}")
    y -= 16
    c.drawString(50, y, f"Estudiante: {rating.estudiante_nombre}   Documento: {rating.estudiante_documento}")
    y -= 16
    c.drawString(50, y, f"Universidad: {rating.universidad}")
    y -= 18

    c.setFont("Helvetica-Bold", 11)
    c.drawString(50, y, "Calificaciones (0.0 – 5.0) — 20% cada una")
    y -= 16

    c.setFont("Helvetica", 10)
    for name, val in [
        ("Área cognitiva", rating.cognitiva),
        ("Área aptitudinal", rating.aptitudinal),
        ("Área actitudinal", rating.actitudinal),
        ("Evaluación", rating.evaluacion),
        ("Participación CPC", rating.cpc),
        ("% fallas", rating.porcentaje_fallas),
    ]:
        c.drawString(60, y, f"- {name}: {val}")
        y -= 14

    y -= 6
    c.setFont("Helvetica-Bold", 11)
    c.drawString(50, y, f"Nota definitiva: {rating.nota_definitiva:.2f}  ({rating.nota_en_letras})")
    y -= 16

    c.setFont("Helvetica", 10)
    estado = "ANULADO" if rating.is_void else ("CERRADO" if rating.is_closed else "ABIERTO")
    c.drawString(50, y, f"Estado del registro: {estado}")
    y -= 16
    if rating.is_void and rating.void_reason:
        c.drawString(50, y, f"Motivo anulación: {rating.void_reason}")
        y -= 16

    if rating.comentarios:
        c.setFont("Helvetica-Bold", 10)
        c.drawString(50, y, "Comentarios:")
        y -= 14
        c.setFont("Helvetica", 10)
        txt = rating.comentarios.strip()
        width = 90
        for i in range(0, len(txt), width):
            c.drawString(60, y, txt[i:i+width])
            y -= 12
            if y < 120:
                c.showPage()
                y = h - 50

    if y < 160:
        c.showPage()
        y = h - 50

    y -= 10
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "Firmas (nombre):")
    y -= 16
    c.setFont("Helvetica", 10)
    c.drawString(60, y, f"Especialista: {rating.especialista_nombre}")
    y -= 14
    c.drawString(60, y, f"Coordinador área: {rating.coordinador_nombre}")
    y -= 14
    c.drawString(60, y, f"Estudiante: {rating.estudiante_firma_nombre}")

    c.setFont("Helvetica-Oblique", 8)
    c.drawString(50, 40, "Documento generado por el Sistema de Calificación por QR (DS-F-01).")
    c.showPage()
    c.save()
    return buf.getvalue()
