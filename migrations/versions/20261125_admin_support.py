"""Add administrator permissions, platform operations, and student support.

Revision ID: 20261125_admin_support
Revises: 20261125_chat
Create Date: 2026-11-25
"""

from alembic import op
import sqlalchemy as sa
from datetime import datetime


revision = "20261125_admin_support"
down_revision = "20261125_chat"
branch_labels = None
depends_on = None


PERMISSIONS = [
    ("dashboard.read", "View the administration dashboard"),
    ("students.read", "View student records"),
    ("students.manage", "Update student records and status"),
    ("courses.read", "View courses and categories"),
    ("courses.manage", "Create and update courses"),
    ("lessons.manage", "Manage lessons and videos"),
    ("notes.manage", "Manage course notes"),
    ("enrollments.read", "View enrollments"),
    ("enrollments.manage", "Grant and revoke enrollments"),
    ("payments.read", "View payment records"),
    ("payments.manage", "Review manual payment requests"),
    ("certificates.read", "View certificates"),
    ("certificates.manage", "Revoke and reissue certificates"),
    ("activity.read", "View student activity"),
    ("support.read", "View support tickets"),
    ("support.manage", "Reply to and manage support tickets"),
    ("reviews.manage", "Moderate student reviews"),
    ("announcements.manage", "Manage announcements"),
    ("content.manage", "Manage public site content"),
    ("reports.read", "View and export analytics"),
    ("settings.manage", "Manage platform settings"),
    ("admins.manage", "Create admins and assign permissions"),
]


def upgrade():
    op.create_table(
        "admin_roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=80), nullable=False, unique=True),
        sa.Column("description", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "admin_permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=100), nullable=False, unique=True),
        sa.Column("description", sa.String(length=255), nullable=False, server_default=""),
    )
    op.create_table(
        "admin_role_permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("admin_roles.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("permission_id", sa.Integer(),
                  sa.ForeignKey("admin_permissions.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_admin_role_permission"),
    )
    op.create_index("ix_admin_role_permissions_role_id", "admin_role_permissions", ["role_id"])
    op.create_index("ix_admin_role_permissions_permission_id", "admin_role_permissions", ["permission_id"])
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("admin_role_id", sa.Integer()))
        batch_op.create_foreign_key(
            "fk_users_admin_role_id_admin_roles", "admin_roles",
            ["admin_role_id"], ["id"],
        )

    op.create_table(
        "admin_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("admin_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("module", sa.String(length=80), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=False),
        sa.Column("target_id", sa.String(length=80)),
        sa.Column("previous_value", sa.Text()),
        sa.Column("new_value", sa.Text()),
        sa.Column("reason", sa.String(length=500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_admin_audit_logs_admin_id", "admin_audit_logs", ["admin_id"])
    op.create_index("ix_admin_audit_logs_module", "admin_audit_logs", ["module"])
    op.create_index("ix_admin_audit_logs_created_at", "admin_audit_logs", ["created_at"])

    op.create_table(
        "student_activity",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("event", sa.String(length=100), nullable=False),
        sa.Column("details", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_student_activity_user_id", "student_activity", ["user_id"])
    op.create_index("ix_student_activity_event", "student_activity", ["event"])
    op.create_index("ix_student_activity_created_at", "student_activity", ["created_at"])

    op.create_table(
        "course_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False, unique=True),
        sa.Column("description", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "course_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("lesson_id", sa.Integer(), sa.ForeignKey("lessons.id", ondelete="SET NULL")),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_course_notes_course_id", "course_notes", ["course_id"])
    op.create_index("ix_course_notes_lesson_id", "course_notes", ["lesson_id"])

    op.create_table(
        "support_tickets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("assigned_admin_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="normal"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_support_tickets_student_id", "support_tickets", ["student_id"])
    op.create_index("ix_support_tickets_assigned_admin_id", "support_tickets", ["assigned_admin_id"])
    op.create_index("ix_support_tickets_status", "support_tickets", ["status"])
    op.create_index("ix_support_tickets_priority", "support_tickets", ["priority"])
    op.create_index("ix_support_tickets_updated_at", "support_tickets", ["updated_at"])
    op.create_table(
        "support_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("support_tickets.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("sender_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("attachment_path", sa.String(length=500)),
        sa.Column("attachment_name", sa.String(length=255)),
        sa.Column("is_internal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_support_messages_ticket_id", "support_messages", ["ticket_id"])
    op.create_index("ix_support_messages_sender_id", "support_messages", ["sender_id"])
    op.create_index("ix_support_messages_created_at", "support_messages", ["created_at"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("kind", sa.String(length=60), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("target_url", sa.String(length=500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])

    op.create_table(
        "announcements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("starts_at", sa.DateTime(timezone=True)),
        sa.Column("ends_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "site_content",
        sa.Column("key", sa.String(length=100), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.add_column("courses", sa.Column("discount_percent", sa.Numeric(5, 2),
                                       nullable=False, server_default="0"))
    op.add_column("courses", sa.Column("level", sa.String(length=30),
                                       nullable=False, server_default="beginner"))
    op.add_column("courses", sa.Column("objectives", sa.Text(),
                                       nullable=False, server_default=""))
    op.add_column("courses", sa.Column("is_featured", sa.Boolean(),
                                       nullable=False, server_default=sa.false()))
    op.add_column("lessons", sa.Column("video_path", sa.String(length=500)))
    op.add_column("enrollments", sa.Column("access_expires_at", sa.DateTime(timezone=True)))
    op.add_column("payments", sa.Column("payment_method", sa.String(length=50)))
    op.add_column("payments", sa.Column("proof_path", sa.String(length=500)))
    op.add_column("payments", sa.Column("review_remarks", sa.Text()))
    with op.batch_alter_table("payments") as batch_op:
        batch_op.add_column(sa.Column("reviewed_by_id", sa.Integer()))
        batch_op.create_foreign_key(
            "fk_payments_reviewed_by_id_users", "users", ["reviewed_by_id"], ["id"],
        )
    op.add_column("payments", sa.Column("reviewed_at", sa.DateTime(timezone=True)))
    op.create_index("ix_payments_payment_status", "payments", ["payment_status"])
    op.add_column("certificates", sa.Column("revoked_at", sa.DateTime(timezone=True)))
    op.add_column("certificates", sa.Column("revoked_reason", sa.String(length=500)))
    op.add_column("reviews", sa.Column("status", sa.String(length=20),
                                       nullable=False, server_default="published"))
    op.create_index("ix_reviews_status", "reviews", ["status"])

    now = datetime(2026, 11, 25)
    op.bulk_insert(
        sa.table("admin_roles",
                 sa.column("id", sa.Integer), sa.column("name", sa.String),
                 sa.column("description", sa.String), sa.column("is_system", sa.Boolean),
                 sa.column("created_at", sa.DateTime)),
        [
            {"id": 1, "name": "admin", "description": "Configurable platform administrator",
             "is_system": True, "created_at": now},
            {"id": 2, "name": "super_admin", "description": "Full platform access",
             "is_system": True, "created_at": now},
        ],
    )
    op.bulk_insert(
        sa.table("admin_permissions", sa.column("id", sa.Integer),
                 sa.column("code", sa.String), sa.column("description", sa.String)),
        [{"id": index, "code": code, "description": description}
         for index, (code, description) in enumerate(PERMISSIONS, start=1)],
    )
    admin_default_permissions = {code for code, _ in PERMISSIONS} - {
        "admins.manage", "settings.manage",
    }
    op.bulk_insert(
        sa.table("admin_role_permissions", sa.column("role_id", sa.Integer),
                 sa.column("permission_id", sa.Integer)),
        [{"role_id": 1, "permission_id": index}
         for index, (code, _) in enumerate(PERMISSIONS, start=1)
         if code in admin_default_permissions],
    )
    op.execute("UPDATE users SET admin_role_id = 1 WHERE role = 'admin'")


def downgrade():
    op.drop_index("ix_reviews_status", table_name="reviews")
    op.drop_column("reviews", "status")
    op.drop_column("certificates", "revoked_reason")
    op.drop_column("certificates", "revoked_at")
    op.drop_index("ix_payments_payment_status", table_name="payments")
    op.drop_column("payments", "reviewed_at")
    with op.batch_alter_table("payments") as batch_op:
        batch_op.drop_constraint("fk_payments_reviewed_by_id_users", type_="foreignkey")
        batch_op.drop_column("reviewed_by_id")
    op.drop_column("payments", "review_remarks")
    op.drop_column("payments", "proof_path")
    op.drop_column("payments", "payment_method")
    op.drop_column("enrollments", "access_expires_at")
    op.drop_column("courses", "is_featured")
    op.drop_column("courses", "objectives")
    op.drop_column("courses", "level")
    op.drop_column("courses", "discount_percent")
    op.drop_column("lessons", "video_path")
    op.drop_table("site_content")
    op.drop_table("announcements")
    op.drop_index("ix_notifications_created_at", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_support_messages_created_at", table_name="support_messages")
    op.drop_index("ix_support_messages_sender_id", table_name="support_messages")
    op.drop_index("ix_support_messages_ticket_id", table_name="support_messages")
    op.drop_table("support_messages")
    op.drop_index("ix_support_tickets_updated_at", table_name="support_tickets")
    op.drop_index("ix_support_tickets_priority", table_name="support_tickets")
    op.drop_index("ix_support_tickets_status", table_name="support_tickets")
    op.drop_index("ix_support_tickets_assigned_admin_id", table_name="support_tickets")
    op.drop_index("ix_support_tickets_student_id", table_name="support_tickets")
    op.drop_table("support_tickets")
    op.drop_index("ix_course_notes_lesson_id", table_name="course_notes")
    op.drop_index("ix_course_notes_course_id", table_name="course_notes")
    op.drop_table("course_notes")
    op.drop_table("course_categories")
    op.drop_index("ix_student_activity_created_at", table_name="student_activity")
    op.drop_index("ix_student_activity_event", table_name="student_activity")
    op.drop_index("ix_student_activity_user_id", table_name="student_activity")
    op.drop_table("student_activity")
    op.drop_index("ix_admin_audit_logs_created_at", table_name="admin_audit_logs")
    op.drop_index("ix_admin_audit_logs_module", table_name="admin_audit_logs")
    op.drop_index("ix_admin_audit_logs_admin_id", table_name="admin_audit_logs")
    op.drop_table("admin_audit_logs")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("fk_users_admin_role_id_admin_roles", type_="foreignkey")
        batch_op.drop_column("admin_role_id")
    op.drop_index("ix_admin_role_permissions_permission_id", table_name="admin_role_permissions")
    op.drop_index("ix_admin_role_permissions_role_id", table_name="admin_role_permissions")
    op.drop_table("admin_role_permissions")
    op.drop_table("admin_permissions")
    op.drop_table("admin_roles")
