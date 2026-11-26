"""Create initial Kshitij Coder schema

Revision ID: 20261125_initial
Revises:
Create Date: 2026-11-25
"""

from alembic import op
import sqlalchemy as sa


revision = "20261125_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("profile_image", sa.String(length=255)),
        sa.Column("account_status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "courses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("thumbnail", sa.String(length=255)),
        sa.Column("category", sa.String(length=100)),
        sa.Column("instructor_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("course_duration", sa.String(length=50)),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_courses_category", "courses", ["category"])

    op.create_table(
        "lessons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("video_url", sa.String(length=500)),
        sa.Column("lesson_order", sa.Integer(), nullable=False),
        sa.Column("duration", sa.String(length=50)),
        sa.Column("is_preview", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_lessons_course_id", "lessons", ["course_id"])

    op.create_table(
        "enrollments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("enrollment_date", sa.DateTime(timezone=True)),
        sa.Column("payment_status", sa.String(length=20), nullable=False),
        sa.Column("access_status", sa.String(length=20), nullable=False),
        sa.UniqueConstraint("user_id", "course_id", name="uq_user_course"),
    )
    op.create_index("ix_enrollments_user_id", "enrollments", ["user_id"])
    op.create_index("ix_enrollments_course_id", "enrollments", ["course_id"])

    op.create_table(
        "lesson_progress",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("lesson_id", sa.Integer(), sa.ForeignKey("lessons.id"), nullable=False),
        sa.Column("completion_status", sa.Boolean(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "lesson_id", name="uq_user_lesson"),
    )
    op.create_index("ix_lesson_progress_user_id", "lesson_progress", ["user_id"])
    op.create_index("ix_lesson_progress_lesson_id", "lesson_progress", ["lesson_id"])

    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("payment_provider", sa.String(length=30), nullable=False),
        sa.Column("transaction_id", sa.String(length=255)),
        sa.Column("payment_status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_payments_transaction_id", "payments", ["transaction_id"], unique=True)
    op.create_index("ix_payments_user_id", "payments", ["user_id"])
    op.create_index("ix_payments_course_id", "payments", ["course_id"])

    op.create_table(
        "certificates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("certificate_number", sa.String(length=100), nullable=False),
        sa.Column("issue_date", sa.DateTime(timezone=True)),
        sa.Column("verification_code", sa.String(length=100), nullable=False),
        sa.UniqueConstraint("user_id", "course_id", name="uq_certificate_user_course"),
    )
    op.create_index("ix_certificates_certificate_number", "certificates", ["certificate_number"], unique=True)
    op.create_index("ix_certificates_verification_code", "certificates", ["verification_code"], unique=True)
    op.create_index("ix_certificates_user_id", "certificates", ["user_id"])

    op.create_table(
        "contact_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(length=20), nullable=False),
    )

    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("review", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("rating >= 1 AND rating <= 5", name="ck_review_rating"),
    )
    op.create_index("ix_reviews_user_id", "reviews", ["user_id"])
    op.create_index("ix_reviews_course_id", "reviews", ["course_id"])


def downgrade():
    op.drop_table("reviews")
    op.drop_table("contact_messages")
    op.drop_table("certificates")
    op.drop_table("payments")
    op.drop_table("lesson_progress")
    op.drop_table("enrollments")
    op.drop_table("lessons")
    op.drop_table("courses")
    op.drop_table("users")
