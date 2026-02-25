"""Initial schema

Revision ID: 0001_init
Revises: 
Create Date: 2026-02-24
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "students",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("documento", sa.String(length=50), nullable=False, unique=True),
        sa.Column("nombre", sa.String(length=200), nullable=False),
        sa.Column("universidad", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("semestre", sa.String(length=50), nullable=False, server_default=""),
        sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_students_documento", "students", ["documento"])
    op.create_index("ix_students_nombre", "students", ["nombre"])

    op.create_table(
        "rotations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nombre", sa.String(length=120), nullable=False, unique=True),
        sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_rotations_nombre", "rotations", ["nombre"])

    op.create_table(
        "teachers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("documento", sa.String(length=50), nullable=False, unique=True),
        sa.Column("nombre", sa.String(length=200), nullable=False),
        sa.Column("especialidad", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("username", sa.String(length=120), nullable=True, unique=True),
        sa.Column("password_hash", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_teachers_documento", "teachers", ["documento"])
    op.create_index("ix_teachers_username", "teachers", ["username"])

    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=120), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("teacher_id", sa.Integer(), sa.ForeignKey("teachers.id"), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_accounts_username", "accounts", ["username"])
    op.create_index("ix_accounts_role", "accounts", ["role"])
    op.create_index("ix_accounts_teacher_id", "accounts", ["teacher_id"])

    op.create_table(
        "student_teachers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id"), nullable=False),
        sa.Column("teacher_id", sa.Integer(), sa.ForeignKey("teachers.id"), nullable=False),
        sa.Column("rotation_id", sa.Integer(), sa.ForeignKey("rotations.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_student_teachers_student_id", "student_teachers", ["student_id"])
    op.create_index("ix_student_teachers_teacher_id", "student_teachers", ["teacher_id"])
    op.create_index("ix_student_teachers_rotation_id", "student_teachers", ["rotation_id"])

    op.create_table(
        "ratings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("estudiante_nombre", sa.String(length=200), nullable=False),
        sa.Column("estudiante_documento", sa.String(length=50), nullable=False),
        sa.Column("universidad", sa.String(length=200), nullable=False),
        sa.Column("semestre", sa.String(length=50), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("mes", sa.String(length=30), nullable=False),
        sa.Column("rotation_id", sa.Integer(), sa.ForeignKey("rotations.id"), nullable=False),
        sa.Column("cognitiva", sa.Float(), nullable=False),
        sa.Column("aptitudinal", sa.Float(), nullable=False),
        sa.Column("actitudinal", sa.Float(), nullable=False),
        sa.Column("evaluacion", sa.Float(), nullable=False),
        sa.Column("cpc", sa.Float(), nullable=False),
        sa.Column("porcentaje_fallas", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("pierde_por_fallas", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("nota_definitiva", sa.Float(), nullable=False),
        sa.Column("nota_en_letras", sa.String(length=200), nullable=False),
        sa.Column("especialista_nombre", sa.String(length=200), nullable=False),
        sa.Column("especialista_documento", sa.String(length=50), nullable=False, server_default=""),
        sa.Column("coordinador_nombre", sa.String(length=200), nullable=False),
        sa.Column("estudiante_firma_nombre", sa.String(length=200), nullable=False),
        sa.Column("comentarios", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_void", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("void_reason", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("reopen_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reopen_reason", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("reopened_by", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("reopened_at", sa.DateTime(), nullable=True),
        sa.Column("actor", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_ratings_estudiante_documento", "ratings", ["estudiante_documento"])
    op.create_index("ix_ratings_rotation_id", "ratings", ["rotation_id"])
    op.create_index("ix_ratings_year", "ratings", ["year"])
    op.create_index("ix_ratings_mes", "ratings", ["mes"])
    op.create_index("ix_ratings_created_at", "ratings", ["created_at"])

    op.create_table(
        "rating_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rating_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("details", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_rating_audit_rating_id", "rating_audit", ["rating_id"])
    op.create_index("ix_rating_audit_action", "rating_audit", ["action"])
    op.create_index("ix_rating_audit_created_at", "rating_audit", ["created_at"])

    op.create_table(
        "month_control",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("mes", sa.String(length=30), nullable=False),
        sa.Column("rotation_id", sa.Integer(), sa.ForeignKey("rotations.id"), nullable=False),
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("actor", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_month_control_year", "month_control", ["year"])
    op.create_index("ix_month_control_mes", "month_control", ["mes"])
    op.create_index("ix_month_control_rotation_id", "month_control", ["rotation_id"])
    op.create_index("ix_month_control_is_closed", "month_control", ["is_closed"])
    op.create_index("ix_month_control_updated_at", "month_control", ["updated_at"])

    op.create_table(
        "admin_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("module", sa.String(length=80), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("details", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_admin_audit_module", "admin_audit", ["module"])
    op.create_index("ix_admin_audit_action", "admin_audit", ["action"])
    op.create_index("ix_admin_audit_created_at", "admin_audit", ["created_at"])

    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=120), nullable=False),
        sa.Column("ip", sa.String(length=80), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_failed_at", sa.DateTime(), nullable=True),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_login_attempts_username", "login_attempts", ["username"])
    op.create_index("ix_login_attempts_ip", "login_attempts", ["ip"])

    op.create_table(
        "auth_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("username", sa.String(length=120), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False, server_default=""),
        sa.Column("ip", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("user_agent", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("details", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_auth_events_event_type", "auth_events", ["event_type"])
    op.create_index("ix_auth_events_username", "auth_events", ["username"])
    op.create_index("ix_auth_events_role", "auth_events", ["role"])
    op.create_index("ix_auth_events_ip", "auth_events", ["ip"])
    op.create_index("ix_auth_events_created_at", "auth_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("auth_events")
    op.drop_table("login_attempts")
    op.drop_table("admin_audit")
    op.drop_table("month_control")
    op.drop_table("rating_audit")
    op.drop_table("ratings")
    op.drop_table("student_teachers")
    op.drop_table("accounts")
    op.drop_table("teachers")
    op.drop_table("rotations")
    op.drop_table("students")
