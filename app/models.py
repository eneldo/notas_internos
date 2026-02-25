from __future__ import annotations
from typing import Optional

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    documento: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    nombre: Mapped[str] = mapped_column(String(200), index=True)
    universidad: Mapped[str] = mapped_column(String(200), default="")
    semestre: Mapped[str] = mapped_column(String(50), default="")
    activa: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Rotation(Base):
    __tablename__ = "rotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nombre: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    activa: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Teacher(Base):
    __tablename__ = "teachers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    documento: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    nombre: Mapped[str] = mapped_column(String(200), index=True)
    especialidad: Mapped[str] = mapped_column(String(200), default="")
    username: Mapped[str | None] = mapped_column(String(120), unique=True, index=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(300), default="")
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)



class Account(Base):
    """Cuenta de acceso para el sistema (Admin/Coordinador/Evaluador/Docente).

    - Para docentes: `teacher_id` apunta a la tabla `teachers`.
    - Para admin/coord/eval: `teacher_id` queda en NULL.
    """

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300), default="")
    role: Mapped[str] = mapped_column(String(30), index=True)  # admin | coord | eval | docente

    teacher_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("teachers.id"), nullable=True, index=True)

    # MFA (TOTP) opcional, recomendado para admin
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mfa_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    teacher: Mapped[Optional["Teacher"]] = relationship("Teacher")



class RefreshToken(Base):
    """Refresh tokens con rotación.

    Guardamos solo el hash del token (sha256) para que, si la BD se filtra,
    no se puedan reutilizar tokens en claro.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), index=True)

    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), index=True)

    issued_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)

    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    replaced_by_jti: Mapped[str | None] = mapped_column(String(64), nullable=True)

    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(300), default="")

    account: Mapped["Account"] = relationship("Account")

class StudentTeacher(Base):
    """Asignación de docentes a estudiantes por rotación."""

    __tablename__ = "student_teachers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("students.id"), index=True)
    teacher_id: Mapped[int] = mapped_column(Integer, ForeignKey("teachers.id"), index=True)
    rotation_id: Mapped[int] = mapped_column(Integer, ForeignKey("rotations.id"), index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    student: Mapped["Student"] = relationship("Student")
    teacher: Mapped["Teacher"] = relationship("Teacher")
    rotation: Mapped["Rotation"] = relationship("Rotation")

class Rating(Base):
    __tablename__ = "ratings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    estudiante_nombre: Mapped[str] = mapped_column(String(200))
    estudiante_documento: Mapped[str] = mapped_column(String(50), index=True)
    universidad: Mapped[str] = mapped_column(String(200))
    semestre: Mapped[str] = mapped_column(String(50))

    # Año y mes para control de mes y reportes
    year: Mapped[int] = mapped_column(Integer, default=lambda: datetime.now().year, index=True)
    mes: Mapped[str] = mapped_column(String(30), index=True)

    rotation_id: Mapped[int] = mapped_column(Integer, ForeignKey("rotations.id"), index=True)
    rotation: Mapped["Rotation"] = relationship("Rotation")

    cognitiva: Mapped[float] = mapped_column(Float)
    aptitudinal: Mapped[float] = mapped_column(Float)
    actitudinal: Mapped[float] = mapped_column(Float)
    evaluacion: Mapped[float] = mapped_column(Float)
    cpc: Mapped[float] = mapped_column(Float)

    porcentaje_fallas: Mapped[float] = mapped_column(Float, default=0.0)
    pierde_por_fallas: Mapped[int] = mapped_column(Integer, default=0)

    nota_definitiva: Mapped[float] = mapped_column(Float)
    nota_en_letras: Mapped[str] = mapped_column(String(200))

    especialista_nombre: Mapped[str] = mapped_column(String(200))
    especialista_documento: Mapped[str] = mapped_column(String(50), default="", index=True)
    coordinador_nombre: Mapped[str] = mapped_column(String(200))
    estudiante_firma_nombre: Mapped[str] = mapped_column(String(200))

    comentarios: Mapped[str] = mapped_column(Text, default="")

    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_void: Mapped[bool] = mapped_column(Boolean, default=False)
    void_reason: Mapped[str] = mapped_column(String(300), default="")

    # Reapertura para correcciones (ADMIN)
    reopen_count: Mapped[int] = mapped_column(Integer, default=0)
    reopen_reason: Mapped[str] = mapped_column(String(300), default="")
    reopened_by: Mapped[str] = mapped_column(String(100), default="")
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    actor: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RatingAudit(Base):
    __tablename__ = "rating_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    rating_id: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(50), index=True)
    actor: Mapped[str] = mapped_column(String(100), default="")
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class MonthControl(Base):
    """Apertura/cierre del mes por rotación (con auditoría)."""

    __tablename__ = "month_control"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    mes: Mapped[str] = mapped_column(String(30), index=True)

    rotation_id: Mapped[int] = mapped_column(Integer, ForeignKey("rotations.id"), index=True)
    rotation: Mapped["Rotation"] = relationship("Rotation")

    is_closed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    actor: Mapped[str] = mapped_column(String(100), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class AdminAudit(Base):
    """Auditoría general (módulos ADMIN)."""

    __tablename__ = "admin_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    module: Mapped[str] = mapped_column(String(80), index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    actor: Mapped[str] = mapped_column(String(100), default="")
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)



class LoginAttempt(Base):
    """Estado de intentos de inicio de sesión por (username, ip).
    Usado para bloqueo tras N intentos fallidos y delay progresivo.
    """

    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(120), index=True)
    ip: Mapped[str] = mapped_column(String(80), index=True)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    last_failed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)



class AuthEvent(Base):
    """Auditoría de autenticación (login, logout, lockout, etc.)."""

    __tablename__ = "auth_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    event_type: Mapped[str] = mapped_column(String(60), index=True)  # login_success|login_failed|account_locked|logout
    username: Mapped[str] = mapped_column(String(120), index=True)
    role: Mapped[str] = mapped_column(String(30), default="", index=True)
    ip: Mapped[str] = mapped_column(String(80), default="", index=True)
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
