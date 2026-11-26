"""Extend existing payments with UPI gateway order and webhook state.

Revision ID: 20261125_upi_gateway
Revises: 20261125_admin_support
Create Date: 2026-11-25
"""

from alembic import op
import sqlalchemy as sa


revision = "20261125_upi_gateway"
down_revision = "20261125_admin_support"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("payments", sa.Column("gateway_order_id", sa.String(length=100)))
    op.add_column("payments", sa.Column("client_order_id", sa.String(length=64)))
    op.add_column("payments", sa.Column("gateway_event_id", sa.String(length=80)))
    op.add_column("payments", sa.Column("payment_environment", sa.String(length=10)))
    op.add_column(
        "payments",
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="INR"),
    )
    op.add_column(
        "payments",
        sa.Column("event_sequence", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("payments", sa.Column("verified_at", sa.DateTime(timezone=True)))
    op.add_column("payments", sa.Column("expires_at", sa.DateTime(timezone=True)))
    op.add_column("payments", sa.Column("checkout_url", sa.String(length=500)))
    op.add_column("payments", sa.Column("upi_intent", sa.String(length=1000)))
    op.add_column("payments", sa.Column("active_attempt_key", sa.String(length=150)))
    op.create_index("ix_payments_gateway_order_id", "payments", ["gateway_order_id"], unique=True)
    op.create_index("ix_payments_client_order_id", "payments", ["client_order_id"], unique=True)
    op.create_index("ix_payments_gateway_event_id", "payments", ["gateway_event_id"])
    op.create_index("ix_payments_payment_environment", "payments", ["payment_environment"])
    op.create_index("ix_payments_active_attempt_key", "payments", ["active_attempt_key"], unique=True)

    op.create_table(
        "payment_gateway_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payment_id", sa.Integer(), sa.ForeignKey("payments.id", ondelete="SET NULL")),
        sa.Column("environment", sa.String(length=10), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("event_id", sa.String(length=80)),
        sa.Column("event_type", sa.String(length=80)),
        sa.Column("event_sequence", sa.Integer()),
        sa.Column("gateway_order_id", sa.String(length=100)),
        sa.Column("client_order_id", sa.String(length=64)),
        sa.Column("signature_valid", sa.Boolean()),
        sa.Column("result", sa.String(length=30), nullable=False),
        sa.Column("error_code", sa.String(length=100)),
        sa.Column("body_sha256", sa.String(length=64)),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_payment_gateway_events_payment_id", "payment_gateway_events", ["payment_id"])
    op.create_index("ix_payment_gateway_events_environment", "payment_gateway_events", ["environment"])
    op.create_index("ix_payment_gateway_events_source", "payment_gateway_events", ["source"])
    op.create_index("ix_payment_gateway_events_event_id", "payment_gateway_events", ["event_id"])
    op.create_index(
        "ix_payment_gateway_events_gateway_order_id", "payment_gateway_events", ["gateway_order_id"]
    )
    op.create_index(
        "ix_payment_gateway_events_client_order_id", "payment_gateway_events", ["client_order_id"]
    )
    op.create_index("ix_payment_gateway_events_result", "payment_gateway_events", ["result"])
    op.create_index(
        "ix_payment_gateway_events_env_received",
        "payment_gateway_events",
        ["environment", "received_at"],
    )

    op.create_table(
        "processed_payment_webhooks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("environment", sa.String(length=10), nullable=False),
        sa.Column("event_id", sa.String(length=80), nullable=False),
        sa.Column("payment_id", sa.Integer(), sa.ForeignKey("payments.id", ondelete="SET NULL")),
        sa.Column("event_sequence", sa.Integer(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("environment", "event_id", name="uq_processed_payment_webhook"),
    )
    op.create_index(
        "ix_processed_payment_webhooks_payment_id",
        "processed_payment_webhooks",
        ["payment_id"],
    )


def downgrade():
    connection = op.get_bind()
    upi_payments = connection.execute(
        sa.text("SELECT COUNT(*) FROM payments WHERE payment_provider = 'upi_gateway'")
    ).scalar()
    webhook_events = connection.execute(
        sa.text("SELECT COUNT(*) FROM payment_gateway_events")
    ).scalar()
    processed_events = connection.execute(
        sa.text("SELECT COUNT(*) FROM processed_payment_webhooks")
    ).scalar()
    if upi_payments or webhook_events or processed_events:
        raise RuntimeError(
            "Cannot remove UPI gateway schema while payment or webhook history exists."
        )
    op.drop_index("ix_processed_payment_webhooks_payment_id", table_name="processed_payment_webhooks")
    op.drop_table("processed_payment_webhooks")
    op.drop_index("ix_payment_gateway_events_env_received", table_name="payment_gateway_events")
    op.drop_index("ix_payment_gateway_events_result", table_name="payment_gateway_events")
    op.drop_index("ix_payment_gateway_events_client_order_id", table_name="payment_gateway_events")
    op.drop_index("ix_payment_gateway_events_gateway_order_id", table_name="payment_gateway_events")
    op.drop_index("ix_payment_gateway_events_event_id", table_name="payment_gateway_events")
    op.drop_index("ix_payment_gateway_events_source", table_name="payment_gateway_events")
    op.drop_index("ix_payment_gateway_events_environment", table_name="payment_gateway_events")
    op.drop_index("ix_payment_gateway_events_payment_id", table_name="payment_gateway_events")
    op.drop_table("payment_gateway_events")
    op.drop_index("ix_payments_active_attempt_key", table_name="payments")
    op.drop_index("ix_payments_payment_environment", table_name="payments")
    op.drop_index("ix_payments_gateway_event_id", table_name="payments")
    op.drop_index("ix_payments_client_order_id", table_name="payments")
    op.drop_index("ix_payments_gateway_order_id", table_name="payments")
    op.drop_column("payments", "active_attempt_key")
    op.drop_column("payments", "expires_at")
    op.drop_column("payments", "verified_at")
    op.drop_column("payments", "event_sequence")
    op.drop_column("payments", "currency")
    op.drop_column("payments", "payment_environment")
    op.drop_column("payments", "upi_intent")
    op.drop_column("payments", "checkout_url")
    op.drop_column("payments", "gateway_event_id")
    op.drop_column("payments", "client_order_id")
    op.drop_column("payments", "gateway_order_id")
