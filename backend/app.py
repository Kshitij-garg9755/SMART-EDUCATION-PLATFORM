import hashlib
import hmac
import csv
import io
import json
import os
import re
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from flask import Flask, Response, abort, jsonify, redirect, request, send_from_directory, session
from flask_cors import CORS
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_wtf.csrf import CSRFProtect, generate_csrf
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from backend.upi_gateway import GatewayApiError, UpiGatewayClient


db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=["200 per minute"])
socketio = SocketIO()
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
INSTANCE_PATH = os.path.join(PROJECT_ROOT, "instance")
FRONTEND_PATH = os.path.join(PROJECT_ROOT, "E-Learning-Website-HTML-CSS-main")
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, index=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="student")
    admin_role_id = db.Column(db.Integer, db.ForeignKey("admin_roles.id"))
    profile_image = db.Column(db.String(255))
    account_status = db.Column(db.String(20), nullable=False, default="active")
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    enrollments = db.relationship("Enrollment", back_populates="user", cascade="all, delete-orphan")
    progress = db.relationship("LessonProgress", back_populates="user", cascade="all, delete-orphan")
    admin_role = db.relationship("AdminRole", foreign_keys=[admin_role_id])


class Course(db.Model):
    __tablename__ = "courses"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    thumbnail = db.Column(db.String(255))
    category = db.Column(db.String(100), index=True)
    instructor_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    price = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    discount_percent = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    course_duration = db.Column(db.String(50))
    level = db.Column(db.String(30), nullable=False, default="beginner")
    objectives = db.Column(db.Text, nullable=False, default="")
    is_featured = db.Column(db.Boolean, nullable=False, default=False)
    status = db.Column(db.String(20), nullable=False, default="published")
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    instructor = db.relationship("User", foreign_keys=[instructor_id])
    lessons = db.relationship("Lesson", back_populates="course", cascade="all, delete-orphan", order_by="Lesson.lesson_order")
    enrollments = db.relationship("Enrollment", back_populates="course", cascade="all, delete-orphan")


class Lesson(db.Model):
    __tablename__ = "lessons"
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    video_url = db.Column(db.String(500))
    video_path = db.Column(db.String(500))
    lesson_order = db.Column(db.Integer, nullable=False, default=1)
    duration = db.Column(db.String(50))
    is_preview = db.Column(db.Boolean, nullable=False, default=False)

    course = db.relationship("Course", back_populates="lessons")
    progress = db.relationship("LessonProgress", back_populates="lesson", cascade="all, delete-orphan")


class Enrollment(db.Model):
    __tablename__ = "enrollments"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False, index=True)
    enrollment_date = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    payment_status = db.Column(db.String(20), nullable=False, default="free")
    access_status = db.Column(db.String(20), nullable=False, default="active")
    access_expires_at = db.Column(db.DateTime(timezone=True))
    __table_args__ = (db.UniqueConstraint("user_id", "course_id", name="uq_user_course"),)

    user = db.relationship("User", back_populates="enrollments")
    course = db.relationship("Course", back_populates="enrollments")


class LessonProgress(db.Model):
    __tablename__ = "lesson_progress"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey("lessons.id"), nullable=False, index=True)
    completion_status = db.Column(db.Boolean, nullable=False, default=False)
    completed_at = db.Column(db.DateTime(timezone=True))
    __table_args__ = (db.UniqueConstraint("user_id", "lesson_id", name="uq_user_lesson"),)

    user = db.relationship("User", back_populates="progress")
    lesson = db.relationship("Lesson", back_populates="progress")


class Payment(db.Model):
    __tablename__ = "payments"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False, index=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    payment_provider = db.Column(db.String(30), nullable=False)
    transaction_id = db.Column(db.String(255), unique=True, index=True)
    payment_status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    gateway_order_id = db.Column(db.String(100), unique=True, index=True)
    client_order_id = db.Column(db.String(64), unique=True, index=True)
    gateway_event_id = db.Column(db.String(80), index=True)
    payment_environment = db.Column(db.String(10), index=True)
    currency = db.Column(db.String(3), nullable=False, default="INR")
    event_sequence = db.Column(db.Integer, nullable=False, default=0)
    verified_at = db.Column(db.DateTime(timezone=True))
    expires_at = db.Column(db.DateTime(timezone=True))
    checkout_url = db.Column(db.String(500))
    upi_intent = db.Column(db.String(1000))
    active_attempt_key = db.Column(db.String(150), unique=True, index=True)
    payment_method = db.Column(db.String(50))
    proof_path = db.Column(db.String(500))
    review_remarks = db.Column(db.Text)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    reviewed_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    user = db.relationship("User", foreign_keys=[user_id])
    course = db.relationship("Course")
    reviewer = db.relationship("User", foreign_keys=[reviewed_by_id])
    gateway_events = db.relationship(
        "PaymentGatewayEvent", back_populates="payment", order_by="PaymentGatewayEvent.id"
    )


class PaymentGatewayEvent(db.Model):
    __tablename__ = "payment_gateway_events"
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payments.id", ondelete="SET NULL"), index=True)
    environment = db.Column(db.String(10), nullable=False, index=True)
    source = db.Column(db.String(20), nullable=False, index=True)
    event_id = db.Column(db.String(80), index=True)
    event_type = db.Column(db.String(80))
    event_sequence = db.Column(db.Integer)
    gateway_order_id = db.Column(db.String(100), index=True)
    client_order_id = db.Column(db.String(64), index=True)
    signature_valid = db.Column(db.Boolean)
    result = db.Column(db.String(30), nullable=False, index=True)
    error_code = db.Column(db.String(100))
    body_sha256 = db.Column(db.String(64))
    received_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    processed_at = db.Column(db.DateTime(timezone=True))

    payment = db.relationship("Payment", back_populates="gateway_events")
    __table_args__ = (
        db.Index("ix_payment_gateway_events_env_received", "environment", "received_at"),
    )


class ProcessedPaymentWebhook(db.Model):
    __tablename__ = "processed_payment_webhooks"
    id = db.Column(db.Integer, primary_key=True)
    environment = db.Column(db.String(10), nullable=False)
    event_id = db.Column(db.String(80), nullable=False)
    payment_id = db.Column(db.Integer, db.ForeignKey("payments.id", ondelete="SET NULL"))
    event_sequence = db.Column(db.Integer, nullable=False)
    processed_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    __table_args__ = (
        db.UniqueConstraint("environment", "event_id", name="uq_processed_payment_webhook"),
        db.Index("ix_processed_payment_webhooks_payment_id", "payment_id"),
    )


class Certificate(db.Model):
    __tablename__ = "certificates"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False, index=True)
    certificate_number = db.Column(db.String(100), unique=True, index=True, nullable=False)
    issue_date = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    verification_code = db.Column(db.String(100), unique=True, index=True, nullable=False)
    revoked_at = db.Column(db.DateTime(timezone=True))
    revoked_reason = db.Column(db.String(500))
    __table_args__ = (db.UniqueConstraint("user_id", "course_id", name="uq_certificate_user_course"),)


class ContactMessage(db.Model):
    __tablename__ = "contact_messages"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    status = db.Column(db.String(20), nullable=False, default="new")


class Review(db.Model):
    __tablename__ = "reviews"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False, index=True)
    rating = db.Column(db.Integer, nullable=False)
    review = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="published", index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    __table_args__ = (db.CheckConstraint("rating >= 1 AND rating <= 5", name="ck_review_rating"),)


class AdminRole(db.Model):
    __tablename__ = "admin_roles"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=False, default="")
    is_system = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                           nullable=False)
    permissions = db.relationship("AdminRolePermission", back_populates="role",
                                  cascade="all, delete-orphan")


class AdminPermission(db.Model):
    __tablename__ = "admin_permissions"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=False, default="")


class AdminRolePermission(db.Model):
    __tablename__ = "admin_role_permissions"
    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey("admin_roles.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    permission_id = db.Column(db.Integer, db.ForeignKey("admin_permissions.id", ondelete="CASCADE"),
                              nullable=False, index=True)
    __table_args__ = (db.UniqueConstraint("role_id", "permission_id",
                                          name="uq_admin_role_permission"),)

    role = db.relationship("AdminRole", back_populates="permissions")
    permission = db.relationship("AdminPermission")


class AdminAuditLog(db.Model):
    __tablename__ = "admin_audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    action = db.Column(db.String(100), nullable=False)
    module = db.Column(db.String(80), nullable=False, index=True)
    target_type = db.Column(db.String(80), nullable=False)
    target_id = db.Column(db.String(80))
    previous_value = db.Column(db.Text)
    new_value = db.Column(db.Text)
    reason = db.Column(db.String(500))
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                           nullable=False, index=True)
    admin = db.relationship("User", foreign_keys=[admin_id])


class StudentActivity(db.Model):
    __tablename__ = "student_activity"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    event = db.Column(db.String(100), nullable=False, index=True)
    details = db.Column(db.Text, nullable=False, default="{}")
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                           nullable=False, index=True)
    user = db.relationship("User")


class CourseCategory(db.Model):
    __tablename__ = "course_categories"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String(500), nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                           nullable=False)


class CourseNote(db.Model):
    __tablename__ = "course_notes"
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey("lessons.id", ondelete="SET NULL"), index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(1000), nullable=False, default="")
    file_path = db.Column(db.String(500), nullable=False)
    file_name = db.Column(db.String(255), nullable=False)
    is_published = db.Column(db.Boolean, nullable=False, default=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                           nullable=False)
    course = db.relationship("Course")
    lesson = db.relationship("Lesson")
    created_by = db.relationship("User")


class SupportTicket(db.Model):
    __tablename__ = "support_tickets"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    assigned_admin_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    subject = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="open", index=True)
    priority = db.Column(db.String(20), nullable=False, default="normal", index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                           nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    resolved_at = db.Column(db.DateTime(timezone=True))
    student = db.relationship("User", foreign_keys=[student_id])
    assigned_admin = db.relationship("User", foreign_keys=[assigned_admin_id])
    messages = db.relationship("SupportMessage", back_populates="ticket",
                               cascade="all, delete-orphan", order_by="SupportMessage.id")


class SupportMessage(db.Model):
    __tablename__ = "support_messages"
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("support_tickets.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    body = db.Column(db.Text, nullable=False, default="")
    attachment_path = db.Column(db.String(500))
    attachment_name = db.Column(db.String(255))
    is_internal = db.Column(db.Boolean, nullable=False, default=False)
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                           nullable=False, index=True)
    ticket = db.relationship("SupportTicket", back_populates="messages")
    sender = db.relationship("User")


class Notification(db.Model):
    __tablename__ = "notifications"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    kind = db.Column(db.String(60), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.String(1000), nullable=False, default="")
    target_url = db.Column(db.String(500))
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                           nullable=False, index=True)
    read_at = db.Column(db.DateTime(timezone=True))
    user = db.relationship("User")


class Announcement(db.Model):
    __tablename__ = "announcements"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    is_published = db.Column(db.Boolean, nullable=False, default=False)
    starts_at = db.Column(db.DateTime(timezone=True))
    ends_at = db.Column(db.DateTime(timezone=True))
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                           nullable=False)
    created_by = db.relationship("User")


class SiteContent(db.Model):
    __tablename__ = "site_content"
    key = db.Column(db.String(100), primary_key=True)
    content = db.Column(db.Text, nullable=False, default="")
    updated_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    updated_by = db.relationship("User")


class ChatConversation(db.Model):
    __tablename__ = "chat_conversations"
    id = db.Column(db.Integer, primary_key=True)
    user_low_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    user_high_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    __table_args__ = (
        db.UniqueConstraint("user_low_id", "user_high_id", name="uq_chat_conversation_pair"),
        db.CheckConstraint("user_low_id < user_high_id", name="ck_chat_conversation_order"),
        db.Index("ix_chat_conversations_updated_at", "updated_at"),
    )

    participants = db.relationship("ChatParticipant", back_populates="conversation",
                                   cascade="all, delete-orphan")
    messages = db.relationship("ChatMessage", back_populates="conversation",
                               cascade="all, delete-orphan", order_by="ChatMessage.id")


class ChatParticipant(db.Model):
    __tablename__ = "chat_participants"
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("chat_conversations.id", ondelete="CASCADE"),
                                nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    joined_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    __table_args__ = (db.UniqueConstraint("conversation_id", "user_id", name="uq_chat_participant"),)

    conversation = db.relationship("ChatConversation", back_populates="participants")
    user = db.relationship("User")


class ChatMessage(db.Model):
    __tablename__ = "chat_messages"
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("chat_conversations.id", ondelete="CASCADE"),
                                nullable=False, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    message = db.Column(db.Text, nullable=False)
    message_type = db.Column(db.String(20), nullable=False, default="text")
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    delivered_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                           nullable=False, index=True)
    read_at = db.Column(db.DateTime(timezone=True))

    conversation = db.relationship("ChatConversation", back_populates="messages")
    sender = db.relationship("User")


def create_app(test_config=None):
    app = Flask(__name__, static_folder=FRONTEND_PATH, instance_path=INSTANCE_PATH)
    database_url = os.getenv("DATABASE_URL", "sqlite:///kshitij_coder.db")
    if database_url.startswith("postgres://"):
        database_url = "postgresql+psycopg://" + database_url[len("postgres://"):]
    elif database_url.startswith("postgresql://"):
        database_url = "postgresql+psycopg://" + database_url[len("postgresql://"):]
    max_video_upload_bytes = int(os.getenv("MAX_VIDEO_UPLOAD_BYTES", str(500 * 1024 * 1024)))
    max_note_upload_bytes = int(os.getenv("MAX_NOTE_UPLOAD_BYTES", str(25 * 1024 * 1024)))
    max_support_attachment_bytes = int(os.getenv(
        "MAX_SUPPORT_ATTACHMENT_BYTES", str(10 * 1024 * 1024)
    ))
    max_payment_proof_bytes = int(os.getenv("MAX_PAYMENT_PROOF_BYTES", str(5 * 1024 * 1024)))
    upi_gateway_timeout = int(os.getenv("UPI_GATEWAY_TIMEOUT_SECONDS", "10"))
    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY", "dev-only-change-this-secret"),
        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE=os.getenv("SESSION_SAMESITE", "Lax"),
        SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        MAX_CONTENT_LENGTH=max_video_upload_bytes + 64 * 1024,
        UPLOAD_FOLDER=os.getenv("UPLOAD_FOLDER", os.path.join(app.instance_path, "uploads")),
        MAX_VIDEO_UPLOAD_BYTES=max_video_upload_bytes,
        MAX_NOTE_UPLOAD_BYTES=max_note_upload_bytes,
        MAX_SUPPORT_ATTACHMENT_BYTES=max_support_attachment_bytes,
        MAX_PAYMENT_PROOF_BYTES=max_payment_proof_bytes,
        UPI_GATEWAY_BASE_URL=os.getenv("UPI_GATEWAY_BASE_URL", "").rstrip("/"),
        UPI_GATEWAY_API_KEY=os.getenv("UPI_GATEWAY_API_KEY", ""),
        UPI_GATEWAY_API_SECRET=os.getenv("UPI_GATEWAY_API_SECRET", ""),
        UPI_GATEWAY_WEBHOOK_SECRET=os.getenv("UPI_GATEWAY_WEBHOOK_SECRET", ""),
        UPI_GATEWAY_ENVIRONMENT=os.getenv("UPI_GATEWAY_ENVIRONMENT", "sandbox").strip().lower(),
        UPI_GATEWAY_TIMEOUT_SECONDS=upi_gateway_timeout,
        UPI_GATEWAY_RETURN_URL=os.getenv("UPI_GATEWAY_RETURN_URL", "").strip(),
        UPI_GATEWAY_MAX_WEBHOOK_BYTES=int(os.getenv("UPI_GATEWAY_MAX_WEBHOOK_BYTES", "65536")),
    )
    if test_config:
        app.config.update(test_config)
    app.config["UPI_GATEWAY_ENVIRONMENT"] = str(
        app.config["UPI_GATEWAY_ENVIRONMENT"]
    ).strip().lower()
    if app.config["UPI_GATEWAY_ENVIRONMENT"] not in {"live", "sandbox"}:
        raise ValueError("UPI_GATEWAY_ENVIRONMENT must be 'live' or 'sandbox'.")
    if not 1 <= int(app.config["UPI_GATEWAY_TIMEOUT_SECONDS"]) <= 30:
        raise ValueError("UPI_GATEWAY_TIMEOUT_SECONDS must be between 1 and 30.")
    if int(app.config["UPI_GATEWAY_MAX_WEBHOOK_BYTES"]) < 1024:
        raise ValueError("UPI_GATEWAY_MAX_WEBHOOK_BYTES must be at least 1024.")
    return_url = app.config["UPI_GATEWAY_RETURN_URL"]
    if return_url:
        parsed_return_url = urlsplit(return_url)
        if (parsed_return_url.scheme != "https" or not parsed_return_url.hostname or
                parsed_return_url.username or parsed_return_url.password or
                parsed_return_url.fragment):
            raise ValueError("UPI_GATEWAY_RETURN_URL must be an HTTPS URL without credentials or a fragment.")

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)
    allowed_origins = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5000,http://127.0.0.1:5000,capacitor://localhost,http://localhost",
    ).split(",")
    allowed_origins = [origin.strip().rstrip("/") for origin in allowed_origins if origin.strip()]
    CORS(app, supports_credentials=True, origins=allowed_origins)
    socketio.init_app(
        app,
        cors_allowed_origins=allowed_origins,
        manage_session=False,
        async_mode="gevent",
        logger=app.config.get("SOCKETIO_LOGGER", False),
        engineio_logger=app.config.get("SOCKETIO_LOGGER", False),
    )
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    reset_serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="password-reset")

    def json_error(message, status=400):
        return jsonify({"error": message}), status

    def upi_gateway_client():
        configured_client = app.config.get("UPI_GATEWAY_CLIENT")
        if configured_client is not None:
            return configured_client
        environment = app.config["UPI_GATEWAY_ENVIRONMENT"]
        api_key = app.config["UPI_GATEWAY_API_KEY"]
        api_secret = app.config["UPI_GATEWAY_API_SECRET"]
        if not app.config["UPI_GATEWAY_BASE_URL"] or not api_key or not api_secret:
            raise GatewayApiError(code="gateway_not_configured")
        if not app.config["UPI_GATEWAY_WEBHOOK_SECRET"]:
            raise GatewayApiError(code="gateway_webhook_not_configured")
        api_secret = app.config["UPI_GATEWAY_API_SECRET"]
        if environment == "sandbox" and (
                not api_key.startswith("test_key_") or not api_secret.startswith("test_sec_")):
            raise GatewayApiError(code="gateway_environment_mismatch")
        if environment == "live" and (
                not api_key.startswith("key_") or api_key.startswith("test_key_") or
                not api_secret.startswith("sec_") or api_secret.startswith("test_sec_")):
            raise GatewayApiError(code="gateway_environment_mismatch")
        base_url = app.config["UPI_GATEWAY_BASE_URL"]
        try:
            parsed_url = urlsplit(base_url)
            hostname = parsed_url.hostname
            _ = parsed_url.port
        except ValueError:
            raise GatewayApiError(code="gateway_invalid_url") from None
        if (not hostname or parsed_url.username or parsed_url.password or
                parsed_url.query or parsed_url.fragment):
            raise GatewayApiError(code="gateway_invalid_url")
        if (environment == "live" and parsed_url.scheme != "https") or (
                parsed_url.scheme == "http" and
                not (environment == "sandbox" and hostname in {"localhost", "127.0.0.1", "::1"})):
            raise GatewayApiError(code="gateway_invalid_url")
        return UpiGatewayClient(
            base_url, api_key, api_secret, app.config["UPI_GATEWAY_TIMEOUT_SECONDS"]
        )

    def record_upi_event(payment, source, result, error_code=None, event_id=None,
                         event_type=None, event_sequence=None, gateway_order_id=None,
                         client_order_id=None, signature_valid=None, body_sha256=None):
        db.session.add(PaymentGatewayEvent(
            payment_id=payment.id if payment else None,
            environment=(payment.payment_environment if payment else
                         app.config["UPI_GATEWAY_ENVIRONMENT"]),
            source=source,
            result=result,
            error_code=error_code,
            event_id=event_id,
            event_type=event_type,
            event_sequence=event_sequence,
            gateway_order_id=gateway_order_id,
            client_order_id=client_order_id,
            signature_valid=signature_valid,
            body_sha256=body_sha256,
            processed_at=datetime.now(timezone.utc),
        ))

    def parse_gateway_time(value):
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)

    def datetime_iso_utc(value):
        if not value:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

    def validate_gateway_order(payment, data, expected_order_id=None):
        if not isinstance(data, dict):
            raise ValueError("invalid_gateway_data")
        order_id = data.get("order_id")
        client_order_id = data.get("client_order_id")
        environment = data.get("environment")
        status = data.get("status")
        currency = data.get("currency")
        test_mode = data.get("test")
        try:
            amount = Decimal(str(data.get("amount"))).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError("invalid_gateway_amount") from None
        expected_amount = Decimal(str(payment.amount)).quantize(Decimal("0.01"))
        if amount != expected_amount or currency != "INR":
            raise ValueError("gateway_amount_or_currency_mismatch")
        if (not isinstance(order_id, str) or not order_id or len(order_id) > 100 or
                not isinstance(client_order_id, str) or
                client_order_id != payment.client_order_id):
            raise ValueError("gateway_order_reference_mismatch")
        if expected_order_id and order_id != expected_order_id:
            raise ValueError("gateway_order_reference_mismatch")
        if payment.gateway_order_id and order_id != payment.gateway_order_id:
            raise ValueError("gateway_order_reference_mismatch")
        if (environment != payment.payment_environment or not isinstance(status, str) or status not in {
                "pending", "paid", "expired", "failed", "review", "under_review"}):
            raise ValueError("gateway_environment_or_status_mismatch")
        if test_mode is not (environment == "sandbox"):
            raise ValueError("gateway_environment_or_status_mismatch")
        payment_url = data.get("payment_url")
        if not isinstance(payment_url, str) or not payment_url or len(payment_url) > 500:
            raise ValueError("gateway_checkout_url_invalid")
        try:
            base = urlsplit(app.config["UPI_GATEWAY_BASE_URL"])
            target = urlsplit(payment_url)
        except ValueError:
            raise ValueError("gateway_checkout_url_invalid") from None
        base_path = base.path.rstrip("/")
        try:
            same_origin = (
                target.scheme == base.scheme and target.hostname == base.hostname and
                target.port == base.port
            )
        except ValueError:
            same_origin = False
        if (not same_origin or target.username or target.password or target.fragment or
                (base_path and not (
                    target.path == base_path or target.path.startswith(base_path + "/")))):
            raise ValueError("gateway_checkout_url_invalid")
        upi_intent = data.get("upi_intent")
        if upi_intent is not None and (
                not isinstance(upi_intent, str) or len(upi_intent) > 1000 or
                not upi_intent.startswith("upi://pay?")):
            raise ValueError("gateway_upi_intent_invalid")
        expires_at = parse_gateway_time(data.get("expires_at"))
        if expires_at is None:
            raise ValueError("gateway_expiry_invalid")
        return {
            "order_id": order_id,
            "client_order_id": client_order_id,
            "status": status,
            "payment_url": payment_url,
            "upi_intent": upi_intent,
            "expires_at": expires_at,
            "utr": data.get("utr"),
        }

    def activate_gateway_enrollment(payment):
        enrollment = Enrollment.query.filter_by(
            user_id=payment.user_id, course_id=payment.course_id
        ).first()
        if enrollment:
            enrollment.access_status = "active"
            enrollment.payment_status = "paid"
            enrollment.access_expires_at = None
        else:
            db.session.add(Enrollment(
                user_id=payment.user_id,
                course_id=payment.course_id,
                payment_status="paid",
                access_status="active",
            ))
        create_notification(
            payment.user_id,
            "payment_approved",
            "Payment approved",
            f"Your payment for {payment.course.title} was verified. Course access is active.",
            "/dashboard.html",
        )

    def apply_gateway_status(payment, data, source, event_id=None, event_type=None,
                             event_sequence=None, body_sha256=None):
        normalized = validate_gateway_order(payment, data)
        if event_sequence is not None and event_sequence <= payment.event_sequence:
            record_upi_event(
                payment, source, "stale", event_id=event_id, event_type=event_type,
                event_sequence=event_sequence, gateway_order_id=normalized["order_id"],
                client_order_id=payment.client_order_id, signature_valid=True,
                body_sha256=body_sha256,
            )
            return "stale"
        payment.gateway_order_id = normalized["order_id"]
        payment.checkout_url = normalized["payment_url"]
        payment.upi_intent = normalized["upi_intent"]
        payment.expires_at = normalized["expires_at"]
        status = normalized["status"]
        if payment.payment_status == "captured" and status != "paid":
            result = "terminal_state_ignored"
        elif status == "paid":
            if payment.payment_environment == "live":
                utr = normalized["utr"]
                if not isinstance(utr, str) or not utr.strip() or len(utr) > 255:
                    raise ValueError("gateway_transaction_reference_missing")
                if payment.payment_status == "captured" and payment.transaction_id != utr.strip():
                    raise ValueError("gateway_transaction_reference_conflict")
                transaction = Payment.query.filter(
                    Payment.transaction_id == utr.strip(),
                    Payment.id != payment.id,
                ).first()
                if transaction:
                    raise ValueError("gateway_transaction_reference_conflict")
                payment.transaction_id = utr.strip()
                if payment.payment_status != "captured":
                    activate_gateway_enrollment(payment)
            payment.payment_status = "captured"
            if not payment.verified_at:
                payment.verified_at = datetime.now(timezone.utc)
            payment.active_attempt_key = None
            result = "verified"
        elif payment.payment_status == "captured":
            result = "terminal_state_ignored"
        else:
            payment.payment_status = {
                "pending": "pending",
                "expired": "expired",
                "failed": "failed",
                "review": "under_review",
                "under_review": "under_review",
            }[status]
            if status in {"expired", "failed"}:
                payment.active_attempt_key = None
            result = "updated"
        if event_sequence is not None:
            payment.event_sequence = event_sequence
        if event_id:
            payment.gateway_event_id = event_id
        record_upi_event(
            payment, source, result, event_id=event_id, event_type=event_type,
            event_sequence=event_sequence, gateway_order_id=normalized["order_id"],
            client_order_id=payment.client_order_id,
            signature_valid=True if source == "webhook" else None,
            body_sha256=body_sha256,
        )
        return result

    def upi_payment_json(payment):
        return {
            "id": payment.id,
            "course_id": payment.course_id,
            "course_title": payment.course.title,
            "course_thumbnail": payment.course.thumbnail,
            "student_name": payment.user.full_name,
            "amount": f"{Decimal(str(payment.amount)):.2f}",
            "currency": payment.currency,
            "provider": payment.payment_provider,
            "environment": payment.payment_environment,
            "status": payment.payment_status,
            "transaction_reference": payment.transaction_id,
            "gateway_order_id": payment.gateway_order_id,
            "checkout_url": payment.checkout_url,
            "upi_intent": payment.upi_intent,
            # The gateway API does not document a QR image URL. Render only
            # payment intents or the hosted checkout URL it actually returns.
            "qr_url": None,
            "expires_at": datetime_iso_utc(payment.expires_at),
            "created_at": datetime_iso_utc(payment.created_at),
            "verified_at": datetime_iso_utc(payment.verified_at),
            "receipt_url": f"/api/payments/{payment.id}/receipt"
            if payment.payment_environment == "live" and payment.verified_at else None,
            "course_url": f"/courses-videos/videos.html?course_id={payment.course_id}"
            if (payment.payment_environment == "live" and
                payment.payment_status == "captured" and payment.verified_at) else None,
        }

    def uploaded_file_size(upload):
        position = upload.stream.tell()
        upload.stream.seek(0, os.SEEK_END)
        size = upload.stream.tell()
        upload.stream.seek(position)
        return size

    @app.before_request
    def enforce_request_size_limit():
        if request.content_length is None:
            return None
        if request.path.startswith("/api/admin/lessons/") and request.path.endswith("/video"):
            maximum = app.config["MAX_VIDEO_UPLOAD_BYTES"]
        elif request.path == "/api/admin/notes":
            maximum = app.config["MAX_NOTE_UPLOAD_BYTES"]
        elif request.path.startswith("/api/support/tickets/") and request.path.endswith("/attachments"):
            maximum = app.config["MAX_SUPPORT_ATTACHMENT_BYTES"]
        elif request.path == "/api/payments/manual" or request.path.endswith("/proof"):
            maximum = app.config["MAX_PAYMENT_PROOF_BYTES"]
        elif request.path == "/api/payments/upi/webhook":
            maximum = app.config["UPI_GATEWAY_MAX_WEBHOOK_BYTES"]
        else:
            maximum = 5 * 1024 * 1024
        allowed_size = maximum if request.path == "/api/payments/upi/webhook" else maximum + 64 * 1024
        if request.content_length > allowed_size:
            return json_error("Request is larger than the upload limit.", 413)
        return None

    def current_user():
        user_id = session.get("user_id")
        if not user_id:
            return None
        return db.session.get(User, user_id)

    def login_required(fn):
        from functools import wraps
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                return json_error("Authentication required.", 401)
            if user.account_status != "active":
                return json_error("Account is inactive.", 403)
            return fn(user, *args, **kwargs)
        return wrapper

    def has_admin_permission(user, permission):
        if user.role == "super_admin":
            return True
        if user.role != "admin" or not user.admin_role_id:
            return False
        return db.session.query(AdminRolePermission.id).join(
            AdminPermission, AdminPermission.id == AdminRolePermission.permission_id
        ).filter(
            AdminRolePermission.role_id == user.admin_role_id,
            AdminPermission.code == permission,
        ).first() is not None

    def roles_required(*roles, permission=None, super_admin_only=False):
        def decorator(fn):
            from functools import wraps
            @wraps(fn)
            def wrapper(*args, **kwargs):
                user = current_user()
                if not user:
                    return json_error("Authentication required.", 401)
                if user.account_status != "active":
                    return json_error("Account is inactive.", 403)
                permitted_roles = set(roles)
                if "admin" in permitted_roles:
                    permitted_roles.add("super_admin")
                if user.role not in permitted_roles:
                    return json_error("Forbidden.", 403)
                if super_admin_only and user.role != "super_admin":
                    return json_error("Super Admin access required.", 403)
                if permission and not has_admin_permission(user, permission):
                    return json_error("Forbidden.", 403)
                return fn(user, *args, **kwargs)
            return wrapper
        return decorator

    def record_student_activity(user, event, details=None):
        if user.role != "student":
            return
        db.session.add(StudentActivity(
            user_id=user.id,
            event=event,
            details=json.dumps(details or {}, separators=(",", ":"), sort_keys=True),
        ))

    def create_notification(user_id, kind, title, body="", target_url=None):
        notification = Notification(user_id=user_id, kind=kind, title=title,
                                    body=body[:1000], target_url=target_url)
        db.session.add(notification)
        return notification

    def admin_audit(admin, action, module, target_type, target_id=None,
                    previous=None, new=None, reason=None):
        db.session.add(AdminAuditLog(
            admin_id=admin.id,
            action=action,
            module=module,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            previous_value=json.dumps(previous, default=str, sort_keys=True) if previous is not None else None,
            new_value=json.dumps(new, default=str, sort_keys=True) if new is not None else None,
            reason=str(reason).strip()[:500] if reason else None,
        ))

    def support_ticket_for_user(ticket_id, user):
        ticket = db.session.get(SupportTicket, ticket_id)
        if not ticket:
            return None
        if user.role == "student":
            return ticket if ticket.student_id == user.id else None
        if user.role in {"admin", "super_admin"} and has_admin_permission(user, "support.read"):
            return ticket
        return None

    def chat_user_allowed(user):
        return bool(
            user and user.account_status == "active" and (
                user.role == "student" or
                (user.role in {"admin", "super_admin"} and
                 has_admin_permission(user, "support.read"))
            )
        )

    def chat_student_required(fn):
        from functools import wraps
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                return json_error("Authentication required.", 401)
            if not chat_user_allowed(user):
                return json_error("An active student or support administrator account is required.", 403)
            return fn(user, *args, **kwargs)
        return wrapper

    def chat_member(conversation_id, user_id):
        return ChatParticipant.query.filter_by(
            conversation_id=conversation_id, user_id=user_id
        ).first() is not None

    socket_users_by_sid = {}

    def chat_user_in_room(user_id, room):
        if not socketio.server:
            return False
        participants = socketio.server.manager.get_participants("/", room)
        return any(socket_users_by_sid.get(sid) == user_id for sid, _ in participants)

    def mark_chat_messages_delivered(conversation_id, recipient_id):
        messages = ChatMessage.query.filter(
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.sender_id != recipient_id,
            ChatMessage.delivered_at.is_(None),
        ).all()
        if not messages:
            return
        delivered_at = datetime.now(timezone.utc)
        for message in messages:
            message.delivered_at = delivered_at
        db.session.commit()
        socketio.emit("message_delivered", {
            "conversation_id": conversation_id,
            "message_ids": [message.id for message in messages],
            "delivered_at": delivered_at.isoformat(),
        }, room=f"conversation:{conversation_id}")

    def chat_peer(conversation, user_id):
        peer_id = conversation.user_high_id if conversation.user_low_id == user_id else conversation.user_low_id
        return db.session.get(User, peer_id)

    def chat_avatar(user):
        return user.profile_image or ""

    def chat_message_json(message, current_user_id):
        sender = message.sender
        return {
            "id": message.id,
            "conversation_id": message.conversation_id,
            "sender_id": sender.id,
            "sender_name": sender.full_name,
            "sender_profile_image": chat_avatar(sender),
            "message": message.message,
            "message_type": message.message_type,
            "created_at": message.created_at.isoformat(),
            "is_read": message.is_read,
            "delivered_at": message.delivered_at.isoformat() if message.delivered_at else None,
            "read_at": message.read_at.isoformat() if message.read_at else None,
            "status": "read" if message.is_read else ("delivered" if message.delivered_at else "sent"),
            "is_mine": message.sender_id == current_user_id,
        }

    def chat_conversation_json(conversation, user_id):
        peer = chat_peer(conversation, user_id)
        latest = ChatMessage.query.filter_by(conversation_id=conversation.id).order_by(
            ChatMessage.id.desc()).first()
        unread = ChatMessage.query.filter(
            ChatMessage.conversation_id == conversation.id,
            ChatMessage.sender_id != user_id,
            ChatMessage.is_read.is_(False),
        ).count()
        return {
            "id": conversation.id,
            "student": {
                "id": peer.id,
                "full_name": peer.full_name,
                "profile_image": chat_avatar(peer),
            },
            "last_message": latest.message if latest else "",
            "last_message_at": latest.created_at.isoformat() if latest else conversation.updated_at.isoformat(),
            "unread_count": unread,
        }

    def valid_email(email):
        return isinstance(email, str) and len(email) <= 255 and "@" in email and "." in email.rsplit("@", 1)[-1]

    def user_json(user):
        return {"id": user.id, "full_name": user.full_name, "email": user.email, "role": user.role,
                "profile_image": user.profile_image, "account_status": user.account_status}

    def course_json(course, include_lessons=True):
        data = {"id": course.id, "title": course.title, "description": course.description,
                "thumbnail": course.thumbnail, "category": course.category, "price": float(course.price),
                "discount_percent": float(course.discount_percent or 0),
                "course_duration": course.course_duration, "level": course.level,
                "objectives": course.objectives, "is_featured": course.is_featured,
                "status": course.status, "lesson_count": len(course.lessons)}
        if include_lessons:
            data["lessons"] = [
                {"id": lesson.id, "title": lesson.title, "lesson_order": lesson.lesson_order,
                 "duration": lesson.duration, "is_preview": lesson.is_preview,
                 "video_url": lesson.video_url}
                for lesson in course.lessons
            ]
        return data

    def payment_json(payment):
        return {
            "id": payment.id,
            "student": user_json(payment.user),
            "course": {"id": payment.course.id, "title": payment.course.title},
            "amount": float(payment.amount),
            "provider": payment.payment_provider,
            "method": payment.payment_method,
            "transaction_id": payment.transaction_id,
            "status": payment.payment_status,
            "proof_url": f"/api/admin/payments/{payment.id}/proof" if payment.proof_path else None,
            "remarks": payment.review_remarks,
            "reviewed_by": payment.reviewer.full_name if payment.reviewer else None,
            "reviewed_at": payment.reviewed_at.isoformat() if payment.reviewed_at else None,
            "created_at": payment.created_at.isoformat() if payment.created_at else None,
            "environment": payment.payment_environment,
            "gateway_order_id": payment.gateway_order_id,
            "client_order_id": payment.client_order_id,
            "currency": payment.currency,
            "verified_at": payment.verified_at.isoformat() if payment.verified_at else None,
        }

    def create_or_recover_upi_order(payment):
        try:
            client = upi_gateway_client()
            payload = {
                "amount": f"{Decimal(str(payment.amount)):.2f}",
                "client_order_id": payment.client_order_id,
            }
            redirect_url = app.config.get("UPI_GATEWAY_RETURN_URL")
            if redirect_url:
                payload["redirect_url"] = redirect_url.replace(
                    "{payment_id}", str(payment.id)
                )
            created = False
            if payment.gateway_order_id:
                data = client.get_order(payment.gateway_order_id)
            else:
                try:
                    data = client.get_order(payment.client_order_id)
                except GatewayApiError as error:
                    if error.status_code != 404:
                        raise
                    try:
                        data = client.create_order(payload)
                        created = True
                    except GatewayApiError as create_error:
                        if create_error.status_code != 409:
                            raise
                        data = client.get_order(payment.client_order_id)
            normalized = validate_gateway_order(payment, data)
            if created and normalized["status"] == "paid":
                data = client.get_order(normalized["order_id"])
            apply_gateway_status(payment, data, "order_create" if created else "order_recovery")
            db.session.commit()
            return True, None
        except GatewayApiError as error:
            db.session.rollback()
            payment = db.session.get(Payment, payment.id)
            if error.status_code in {400, 401, 403, 422}:
                payment.payment_status = "failed"
                payment.active_attempt_key = None
            record_upi_event(
                payment, "order_create", "failed",
                error_code=f"{error.code}_{error.status_code}" if error.status_code else error.code,
                gateway_order_id=payment.gateway_order_id,
                client_order_id=payment.client_order_id,
            )
            db.session.commit()
            return False, error.code
        except ValueError as error:
            db.session.rollback()
            payment = db.session.get(Payment, payment.id)
            record_upi_event(
                payment, "order_create", "failed", error_code=str(error),
                gateway_order_id=payment.gateway_order_id,
                client_order_id=payment.client_order_id,
            )
            payment.payment_status = "failed"
            payment.active_attempt_key = None
            db.session.commit()
            return False, str(error)

    def support_message_json(message, include_internal=False):
        data = {
            "id": message.id,
            "ticket_id": message.ticket_id,
            "sender_id": message.sender_id,
            "sender_name": message.sender.full_name,
            "body": message.body,
            "attachment_name": message.attachment_name,
            "attachment_url": f"/api/support/messages/{message.id}/attachment"
            if message.attachment_path else None,
            "created_at": message.created_at.isoformat(),
            "is_read": message.is_read,
        }
        if include_internal:
            data["is_internal"] = message.is_internal
        return data

    def support_ticket_json(ticket, viewer, include_internal=False):
        message_filter = [SupportMessage.ticket_id == ticket.id]
        if not include_internal:
            message_filter.append(SupportMessage.is_internal.is_(False))
        latest = SupportMessage.query.filter(*message_filter).order_by(
            SupportMessage.id.desc()
        ).first()
        unread_filter = [
            SupportMessage.ticket_id == ticket.id,
            SupportMessage.sender_id != viewer.id,
            SupportMessage.is_read.is_(False),
        ]
        if not include_internal:
            unread_filter.append(SupportMessage.is_internal.is_(False))
        return {
            "id": ticket.id,
            "student": {"id": ticket.student.id, "full_name": ticket.student.full_name,
                        "profile_image": chat_avatar(ticket.student)},
            "subject": ticket.subject,
            "status": ticket.status,
            "priority": ticket.priority,
            "assigned_admin_id": ticket.assigned_admin_id,
            "last_message": latest.body if latest else "",
            "last_message_at": latest.created_at.isoformat() if latest else ticket.updated_at.isoformat(),
            "unread_count": SupportMessage.query.filter(*unread_filter).count(),
            "created_at": ticket.created_at.isoformat(),
            "updated_at": ticket.updated_at.isoformat(),
        }

    def course_note_json(note):
        return {
            "id": note.id, "course_id": note.course_id, "lesson_id": note.lesson_id,
            "title": note.title, "description": note.description,
            "file_name": note.file_name, "is_published": note.is_published,
            "created_at": note.created_at.isoformat(),
        }

    def enrollment_is_unexpired(enrollment):
        expires_at = enrollment.access_expires_at
        if expires_at is None:
            return True
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at > datetime.now(timezone.utc)

    @app.get("/api/health")
    def health():
        db.session.execute(db.text("SELECT 1"))
        return jsonify({"status": "ok"})

    @app.get("/api/csrf")
    def csrf_token():
        return jsonify({"csrfToken": generate_csrf()})

    @app.get("/api/auth/me")
    def auth_me():
        user = current_user()
        return jsonify({"authenticated": bool(user), "user": user_json(user) if user else None})

    @app.post("/api/auth/signup")
    @limiter.limit("10 per minute")
    def signup():
        data = request.get_json(silent=True) or {}
        full_name = str(data.get("full_name", "")).strip()
        email = str(data.get("email", "")).strip().lower()
        password = data.get("password") or ""
        confirm_password = data.get("confirm_password") or ""
        if not full_name or len(full_name) > 120:
            return json_error("Valid full name is required.")
        if not valid_email(email):
            return json_error("Valid email is required.")
        if len(password) < 8:
            return json_error("Password must be at least 8 characters.")
        if password != confirm_password:
            return json_error("Passwords do not match.")
        if User.query.filter_by(email=email).first():
            return json_error("An account with this email already exists.", 409)
        user = User(full_name=full_name, email=email,
                    password_hash=generate_password_hash(password, method="scrypt"))
        db.session.add(user)
        db.session.commit()
        record_student_activity(user, "registered")
        for administrator in User.query.filter(
                User.role.in_(("admin", "super_admin")), User.account_status == "active").all():
            create_notification(administrator.id, "student_registered", "New student registration",
                                full_name, "/admin.html#students")
        db.session.commit()
        session.clear()
        session.permanent = True
        session["user_id"] = user.id
        return jsonify({"message": "Account created.", "user": user_json(user)}), 201

    @app.post("/api/auth/login")
    @limiter.limit("10 per minute")
    def login():
        data = request.get_json(silent=True) or {}
        email = str(data.get("email", "")).strip().lower()
        password = data.get("password") or ""
        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password_hash, password):
            return json_error("Invalid email or password.", 401)
        if user.account_status != "active":
            return json_error("Account is inactive.", 403)
        record_student_activity(user, "login")
        db.session.commit()
        session.clear()
        session.permanent = True
        session["user_id"] = user.id
        return jsonify({"message": "Login successful.", "user": user_json(user)})

    @app.post("/api/admin/auth/login")
    @limiter.limit("10 per minute")
    def admin_login():
        data = request.get_json(silent=True) or {}
        email = str(data.get("email", "")).strip().lower()
        password = data.get("password") or ""
        user = User.query.filter_by(email=email).first()
        if (not user or user.role not in {"admin", "super_admin"} or
                not check_password_hash(user.password_hash, password)):
            return json_error("Invalid administrator credentials.", 401)
        if user.account_status != "active":
            return json_error("Administrator account is inactive.", 403)
        record_student_activity(user, "admin_login")
        db.session.commit()
        session.clear()
        session.permanent = True
        session["user_id"] = user.id
        return jsonify({"message": "Administrator login successful."})

    @app.post("/api/auth/logout")
    @login_required
    def logout(user):
        session.clear()
        return jsonify({"message": "Logged out."})

    @app.post("/api/auth/forgot-password")
    @limiter.limit("5 per minute")
    def forgot_password():
        data = request.get_json(silent=True) or {}
        email = str(data.get("email", "")).strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            token = reset_serializer.dumps(email)
            app.logger.info("Password reset token for %s: %s", email, token)
        return jsonify({"message": "If an account exists, password reset instructions have been prepared."})

    @app.post("/api/auth/reset-password")
    def reset_password():
        data = request.get_json(silent=True) or {}
        token = data.get("token", "")
        password = data.get("password") or ""
        if len(password) < 8:
            return json_error("Password must be at least 8 characters.")
        try:
            email = reset_serializer.loads(token, max_age=3600)
        except (BadSignature, SignatureExpired):
            return json_error("Reset link is invalid or expired.", 400)
        user = User.query.filter_by(email=email).first()
        if not user:
            return json_error("Reset link is invalid.", 400)
        user.password_hash = generate_password_hash(password, method="scrypt")
        db.session.commit()
        return jsonify({"message": "Password updated."})

    @app.get("/api/profile")
    @login_required
    def profile(user):
        return jsonify({"user": user_json(user)})

    @app.put("/api/profile")
    @login_required
    def update_profile(user):
        data = request.get_json(silent=True) or {}
        full_name = str(data.get("full_name", "")).strip()
        if not full_name or len(full_name) > 120:
            return json_error("Valid full name is required.")
        user.full_name = full_name
        db.session.commit()
        return jsonify({"message": "Profile updated.", "user": user_json(user)})

    @app.post("/api/profile/password")
    @login_required
    def change_password(user):
        data = request.get_json(silent=True) or {}
        current = data.get("current_password") or ""
        new_password = data.get("new_password") or ""
        if not check_password_hash(user.password_hash, current):
            return json_error("Current password is incorrect.", 400)
        if len(new_password) < 8:
            return json_error("New password must be at least 8 characters.")
        user.password_hash = generate_password_hash(new_password, method="scrypt")
        db.session.commit()
        return jsonify({"message": "Password changed."})

    @app.get("/api/courses")
    def courses():
        query = Course.query.filter_by(status="published")
        search = str(request.args.get("search", "")).strip()
        category = str(request.args.get("category", "")).strip()
        if search:
            query = query.filter(db.or_(Course.title.ilike(f"%{search}%"), Course.description.ilike(f"%{search}%")))
        if category:
            query = query.filter_by(category=category)
        user = current_user()
        enrolled_ids = set()
        if user and user.role == "student" and user.account_status == "active":
            enrollments = Enrollment.query.filter_by(
                user_id=user.id, access_status="active"
            ).all()
            enrolled_ids = {
                item.course_id for item in enrollments if enrollment_is_unexpired(item)
            }
        items = []
        for course in query.order_by(Course.created_at.desc()).all():
            item = course_json(course, include_lessons=False)
            item["enrolled"] = course.id in enrolled_ids
            items.append(item)
        return jsonify({"courses": items})

    @app.get("/api/courses/<int:course_id>")
    def course_detail(course_id):
        course = db.session.get(Course, course_id)
        if not course or course.status != "published":
            return json_error("Course not found.", 404)
        user = current_user()
        enrolled = False
        if user and user.role == "student" and user.account_status == "active":
            enrollment = Enrollment.query.filter_by(
                user_id=user.id, course_id=course.id, access_status="active"
            ).first()
            enrolled = bool(enrollment and enrollment_is_unexpired(enrollment))
            record_student_activity(user, "course_opened", {"course_id": course.id})
            db.session.commit()
        data = course_json(course)
        if not enrolled:
            data["lessons"] = [lesson for lesson in data["lessons"] if lesson["is_preview"]]
        data["enrolled"] = enrolled
        return jsonify({"course": data})

    @app.post("/api/courses/<int:course_id>/enroll")
    @login_required
    def enroll(user, course_id):
        if user.role != "student":
            return json_error("Student account required.", 403)
        course = db.session.get(Course, course_id)
        if not course or course.status != "published":
            return json_error("Course not found.", 404)
        existing = Enrollment.query.filter_by(user_id=user.id, course_id=course.id).first()
        if existing and enrollment_is_unexpired(existing):
            return jsonify({"message": "Already enrolled.", "enrollment": existing.id})
        if float(course.price) > 0:
            return jsonify({"requires_payment": True, "amount": float(course.price), "course_id": course.id}), 402
        if existing:
            existing.payment_status = "free"
            existing.access_status = "active"
            existing.access_expires_at = None
        else:
            existing = Enrollment(
                user_id=user.id, course_id=course.id,
                payment_status="free", access_status="active",
            )
            db.session.add(existing)
        record_student_activity(user, "enrolled", {"course_id": course.id, "payment_status": "free"})
        db.session.commit()
        return jsonify({"message": "Enrolled successfully.", "enrollment": existing.id}), 201

    @app.get("/api/dashboard")
    @login_required
    def dashboard(user):
        enrollments = [
            item for item in Enrollment.query.filter_by(
                user_id=user.id, access_status="active"
            ).all() if enrollment_is_unexpired(item)
        ]
        data = []
        for enrollment in enrollments:
            course = enrollment.course
            total = len(course.lessons)
            completed = LessonProgress.query.join(Lesson).filter(
                LessonProgress.user_id == user.id, Lesson.course_id == course.id,
                LessonProgress.completion_status.is_(True)).count()
            data.append({"course": course_json(course),
                         "progress": round((completed / total * 100), 1) if total else 0,
                         "completed_lessons": completed, "total_lessons": total})
        certificates = Certificate.query.filter_by(user_id=user.id).all()
        return jsonify({"user": user_json(user), "courses": data,
                        "certificates": [{"certificate_number": c.certificate_number,
                                          "verification_code": c.verification_code,
                                          "issue_date": c.issue_date.isoformat()} for c in certificates]})

    @app.post("/api/lessons/<int:lesson_id>/complete")
    @login_required
    def complete_lesson(user, lesson_id):
        if user.role != "student":
            return json_error("Student account required.", 403)
        lesson = db.session.get(Lesson, lesson_id)
        if not lesson:
            return json_error("Lesson not found.", 404)
        enrollment = Enrollment.query.filter_by(user_id=user.id, course_id=lesson.course_id, access_status="active").first()
        if not enrollment or not enrollment_is_unexpired(enrollment):
            return json_error("Enroll in this course first.", 403)
        progress = LessonProgress.query.filter_by(user_id=user.id, lesson_id=lesson.id).first()
        if not progress:
            progress = LessonProgress(user_id=user.id, lesson_id=lesson.id)
            db.session.add(progress)
        progress.completion_status = True
        progress.completed_at = datetime.now(timezone.utc)
        record_student_activity(user, "lesson_completed", {
            "course_id": lesson.course_id, "lesson_id": lesson.id,
        })
        db.session.commit()
        total = len(lesson.course.lessons)
        completed = LessonProgress.query.join(Lesson).filter(
            LessonProgress.user_id == user.id, Lesson.course_id == lesson.course_id,
            LessonProgress.completion_status.is_(True)).count()
        percent = round(completed / total * 100, 1) if total else 0
        if percent == 100:
            certificate = Certificate.query.filter_by(user_id=user.id, course_id=lesson.course_id).first()
            if not certificate:
                certificate = Certificate(user_id=user.id, course_id=lesson.course_id,
                                          certificate_number=f"KC-{uuid.uuid4().hex[:12].upper()}",
                                          verification_code=secrets.token_urlsafe(16))
                db.session.add(certificate)
                create_notification(user.id, "certificate_issued", "Certificate issued",
                                    lesson.course.title, "/dashboard.html")
                db.session.commit()
        return jsonify({"message": "Lesson completed.", "progress": percent})

    @app.post("/api/contact")
    @limiter.limit("10 per minute")
    def contact():
        data = request.get_json(silent=True) or {}
        name = str(data.get("name", "")).strip()
        email = str(data.get("email", "")).strip().lower()
        subject = str(data.get("subject", "")).strip()
        message = str(data.get("message", "")).strip()
        if not name or len(name) > 120:
            return json_error("Valid name is required.")
        if not valid_email(email):
            return json_error("Valid email is required.")
        if not subject or len(subject) > 200:
            return json_error("Subject is required.")
        if not message or len(message) > 5000:
            return json_error("Message must be between 1 and 5000 characters.")
        entry = ContactMessage(name=name, email=email, subject=subject, message=message)
        db.session.add(entry)
        db.session.commit()
        return jsonify({"message": "Your message has been received.", "id": entry.id}), 201

    @app.post("/api/reviews")
    @login_required
    def create_review(user):
        data = request.get_json(silent=True) or {}
        course_id = data.get("course_id")
        rating = data.get("rating")
        text = str(data.get("review", "")).strip()
        if not isinstance(rating, int) or rating < 1 or rating > 5:
            return json_error("Rating must be from 1 to 5.")
        if not text or len(text) > 3000:
            return json_error("Review text is required.")
        course = db.session.get(Course, course_id)
        if not course:
            return json_error("Course not found.", 404)
        if not Enrollment.query.filter_by(user_id=user.id, course_id=course.id, access_status="active").first():
            return json_error("Only enrolled students can review this course.", 403)
        review = Review.query.filter_by(user_id=user.id, course_id=course.id).first()
        if review:
            review.rating, review.review = rating, text
        else:
            review = Review(user_id=user.id, course_id=course.id, rating=rating, review=text)
            db.session.add(review)
        db.session.commit()
        return jsonify({"message": "Review saved."})

    @app.post("/api/payments/razorpay/order")
    @login_required
    def razorpay_order(user, course_id=None):
        data = request.get_json(silent=True) or {}
        course = db.session.get(Course, data.get("course_id"))
        key_id = os.getenv("RAZORPAY_KEY_ID")
        key_secret = os.getenv("RAZORPAY_KEY_SECRET")
        if not course:
            return json_error("Course not found.", 404)
        if not key_id or not key_secret:
            return json_error("Razorpay is not configured.", 503)
        try:
            import razorpay
            client = razorpay.Client(auth=(key_id, key_secret))
            order = client.order.create({"amount": int(float(course.price) * 100), "currency": "INR",
                                         "receipt": f"kc_{user.id}_{course.id}_{secrets.token_hex(4)}"})
        except Exception as exc:
            app.logger.error("Razorpay order creation failed: %s", exc)
            return json_error("Payment provider unavailable.", 502)
        payment = Payment(user_id=user.id, course_id=course.id, amount=course.price,
                          payment_provider="razorpay", transaction_id=order["id"], payment_status="pending")
        db.session.add(payment)
        db.session.commit()
        return jsonify({"key_id": key_id, "order_id": order["id"], "amount": int(float(course.price) * 100),
                        "currency": "INR", "course_id": course.id})

    @app.post("/api/payments/razorpay/verify")
    @login_required
    def razorpay_verify(user):
        data = request.get_json(silent=True) or {}
        key_secret = os.getenv("RAZORPAY_KEY_SECRET")
        if not key_secret:
            return json_error("Razorpay is not configured.", 503)
        order_id = str(data.get("razorpay_order_id", ""))
        payment_id = str(data.get("razorpay_payment_id", ""))
        signature = str(data.get("razorpay_signature", ""))
        expected = hmac.new(key_secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return json_error("Payment signature invalid.", 400)
        payment = Payment.query.filter_by(transaction_id=order_id, user_id=user.id).first()
        if not payment:
            return json_error("Payment record not found.", 404)
        if payment.payment_status == "captured":
            return jsonify({"message": "Payment already verified."})
        payment.transaction_id = payment_id
        payment.payment_status = "captured"
        existing = Enrollment.query.filter_by(user_id=user.id, course_id=payment.course_id).first()
        if not existing:
            db.session.add(Enrollment(user_id=user.id, course_id=payment.course_id,
                                      payment_status="paid", access_status="active"))
        db.session.commit()
        return jsonify({"message": "Payment verified and course enrolled."})

    @app.post("/api/payments/razorpay/webhook")
    def razorpay_webhook():
        secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")
        signature = request.headers.get("X-Razorpay-Signature", "")
        if not secret:
            return json_error("Webhook is not configured.", 503)
        expected = hmac.new(secret.encode(), request.get_data(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return json_error("Webhook signature invalid.", 400)
        data = request.get_json(silent=True) or {}
        event = data.get("event")
        if event == "payment.captured":
            entity = data.get("payload", {}).get("payment", {}).get("entity", {})
            order_id = entity.get("order_id")
            payment_id = entity.get("id")
            payment = Payment.query.filter_by(transaction_id=order_id).first()
            if payment and payment.payment_status != "captured":
                payment.transaction_id = payment_id
                payment.payment_status = "captured"
                if not Enrollment.query.filter_by(user_id=payment.user_id, course_id=payment.course_id).first():
                    db.session.add(Enrollment(user_id=payment.user_id, course_id=payment.course_id,
                                              payment_status="paid", access_status="active"))
                db.session.commit()
        return jsonify({"received": True})

    @app.post("/api/payments/upi/orders")
    @login_required
    @limiter.limit("10 per minute")
    def create_upi_order(user):
        if user.role != "student":
            return json_error("Student account required.", 403)
        data = request.get_json(silent=True) or {}
        try:
            course_id = int(data.get("course_id"))
        except (TypeError, ValueError):
            return json_error("A valid course is required.")
        course = db.session.get(Course, course_id)
        if not course or course.status != "published" or Decimal(str(course.price)) <= 0:
            return json_error("Paid course not found.", 404)
        active_enrollment = Enrollment.query.filter_by(
            user_id=user.id, course_id=course.id, access_status="active"
        ).first()
        if active_enrollment and enrollment_is_unexpired(active_enrollment):
            return json_error("You already have active access to this course.", 409)

        environment = app.config["UPI_GATEWAY_ENVIRONMENT"]
        attempt_key = f"upi:{environment}:{user.id}:{course.id}"
        payment = Payment.query.filter_by(active_attempt_key=attempt_key).first()
        if payment:
            expires_at = payment.expires_at
            if expires_at and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if payment.checkout_url and expires_at and expires_at > datetime.now(timezone.utc):
                return jsonify({"payment": upi_payment_json(payment)}), 200
        else:
            payment = Payment(
                user_id=user.id,
                course_id=course.id,
                amount=course.price,
                payment_provider="upi_gateway",
                payment_status="processing",
                currency="INR",
                payment_environment=environment,
                client_order_id=f"kc_{environment}_{uuid.uuid4().hex}",
                active_attempt_key=attempt_key,
            )
            db.session.add(payment)
            try:
                db.session.flush()
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                payment = Payment.query.filter_by(active_attempt_key=attempt_key).first()
                if not payment:
                    raise

        succeeded, error_code = create_or_recover_upi_order(payment)
        payment = db.session.get(Payment, payment.id)
        if not succeeded and not payment.checkout_url:
            code = 503 if error_code in {
                "gateway_not_configured", "gateway_webhook_not_configured",
                "gateway_environment_mismatch",
                "gateway_invalid_url", "gateway_unavailable",
            } else 502
            return jsonify({
                "error": "Unable to initialize the payment with the UPI gateway.",
                "payment": upi_payment_json(payment),
            }), code
        return jsonify({"payment": upi_payment_json(payment)}), 201 if succeeded else 202

    @app.get("/api/payments/upi/<int:payment_id>")
    @login_required
    def get_upi_payment(user, payment_id):
        payment = Payment.query.filter_by(
            id=payment_id, user_id=user.id, payment_provider="upi_gateway"
        ).first()
        if not payment:
            return json_error("Payment not found.", 404)
        return jsonify({"payment": upi_payment_json(payment)})

    @app.post("/api/payments/upi/<int:payment_id>/check")
    @login_required
    @limiter.limit("20 per minute")
    def check_upi_payment(user, payment_id):
        if user.role != "student":
            return json_error("Student account required.", 403)
        payment = Payment.query.filter_by(
            id=payment_id, user_id=user.id, payment_provider="upi_gateway"
        ).first()
        if not payment:
            return json_error("Payment not found.", 404)
        if payment.payment_status == "captured":
            return jsonify({"payment": upi_payment_json(payment)})
        try:
            client = upi_gateway_client()
            reference = payment.gateway_order_id or payment.client_order_id
            data = client.get_order(reference)
            apply_gateway_status(payment, data, "status_check")
            db.session.commit()
        except GatewayApiError as error:
            db.session.rollback()
            payment = db.session.get(Payment, payment_id)
            record_upi_event(
                payment, "status_check", "failed", error_code=error.code,
                gateway_order_id=payment.gateway_order_id,
                client_order_id=payment.client_order_id,
            )
            db.session.commit()
            return jsonify({
                "error": "The gateway status could not be checked. Try again shortly.",
                "payment": upi_payment_json(payment),
            }), 503
        except ValueError as error:
            db.session.rollback()
            payment = db.session.get(Payment, payment_id)
            record_upi_event(
                payment, "status_check", "failed", error_code=str(error),
                gateway_order_id=payment.gateway_order_id,
                client_order_id=payment.client_order_id,
            )
            db.session.commit()
            return jsonify({
                "error": "The gateway returned an invalid payment status.",
                "payment": upi_payment_json(payment),
            }), 502
        return jsonify({"payment": upi_payment_json(payment)})

    @app.get("/api/payments/<int:payment_id>/receipt")
    @login_required
    def student_payment_receipt(user, payment_id):
        payment = Payment.query.filter_by(
            id=payment_id,
            user_id=user.id,
            payment_provider="upi_gateway",
            payment_environment="live",
            payment_status="captured",
        ).first()
        if not payment or not payment.verified_at:
            return json_error("Verified payment receipt not found.", 404)
        lines = [
            "Kshitij Coder - Payment Receipt",
            f"Receipt: KC-UPI-{payment.id}",
            f"Student: {payment.user.full_name}",
            f"Course: {payment.course.title}",
            f"Amount: INR {Decimal(str(payment.amount)):.2f}",
            f"Transaction reference: {payment.transaction_id}",
            f"Gateway order: {payment.gateway_order_id}",
            f"Verified: {payment.verified_at.isoformat()}",
        ]
        return Response(
            "\n".join(lines) + "\n",
            mimetype="text/plain",
            headers={"Content-Disposition": f'attachment; filename="receipt-{payment.id}.txt"'},
        )

    @app.post("/api/payments/upi/webhook")
    @csrf.exempt
    @limiter.limit("120 per minute")
    def upi_payment_webhook():
        raw_body = request.stream.read(app.config["UPI_GATEWAY_MAX_WEBHOOK_BYTES"] + 1)
        if len(raw_body) > app.config["UPI_GATEWAY_MAX_WEBHOOK_BYTES"]:
            return json_error("Webhook payload is larger than the allowed limit.", 413)
        body_hash = hashlib.sha256(raw_body).hexdigest()
        secret = app.config.get("UPI_GATEWAY_WEBHOOK_SECRET", "")
        signature = request.headers.get("X-Signature", "")
        match = re.fullmatch(r"t=([0-9]{1,12}),v1=([a-fA-F0-9]{64})", signature)
        if not secret:
            record_upi_event(
                None, "webhook", "rejected",
                error_code="webhook_secret_missing",
                signature_valid=False, body_sha256=body_hash,
            )
            db.session.commit()
            return json_error("Webhook verification is not configured.", 503)
        if not match:
            record_upi_event(
                None, "webhook", "rejected", error_code="webhook_signature_invalid",
                signature_valid=False, body_sha256=body_hash,
            )
            db.session.commit()
            return json_error("Webhook signature invalid.", 401)
        timestamp = int(match.group(1))
        if abs(int(time.time()) - timestamp) > 300:
            record_upi_event(
                None, "webhook", "rejected", error_code="webhook_timestamp_expired",
                signature_valid=False, body_sha256=body_hash,
            )
            db.session.commit()
            return json_error("Webhook timestamp is outside the accepted window.", 401)
        signed = f"{match.group(1)}.".encode("ascii") + raw_body
        expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, match.group(2).lower()):
            record_upi_event(
                None, "webhook", "rejected", error_code="webhook_signature_invalid",
                signature_valid=False, body_sha256=body_hash,
            )
            db.session.commit()
            return json_error("Webhook signature invalid.", 401)
        try:
            event = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            record_upi_event(
                None, "webhook", "rejected", error_code="webhook_invalid_json",
                signature_valid=True, body_sha256=body_hash,
            )
            db.session.commit()
            return json_error("Webhook payload is invalid.", 400)
        if not isinstance(event, dict) or not isinstance(event.get("data"), dict):
            record_upi_event(
                None, "webhook", "rejected", error_code="webhook_invalid_payload",
                signature_valid=True, body_sha256=body_hash,
            )
            db.session.commit()
            return json_error("Webhook payload is invalid.", 400)

        event_id = event.get("event_id")
        event_type = event.get("event")
        event_sequence = event.get("event_sequence")
        event_data = event["data"]
        header_event_id = request.headers.get("X-Event-Id", "")
        header_event_type = request.headers.get("X-Event", "")
        sequence_valid = (
            isinstance(event_sequence, int) and not isinstance(event_sequence, bool) and
            1 <= event_sequence <= 2147483647
        )
        if (not isinstance(event_id, str) or not event_id or len(event_id) > 80 or
                event_id != header_event_id or not isinstance(event_type, str) or
                len(event_type) > 80 or event_type != header_event_type or not sequence_valid):
            record_upi_event(
                None, "webhook", "rejected", error_code="webhook_event_identity_invalid",
                event_id=event_id if isinstance(event_id, str) else None,
                event_type=event_type if isinstance(event_type, str) else None,
                event_sequence=event_sequence if sequence_valid else None,
                signature_valid=True, body_sha256=body_hash,
            )
            db.session.commit()
            return json_error("Webhook event identity is invalid.", 400)
        order_id = event_data.get("order_id")
        client_order_id = event_data.get("client_order_id")
        if (not isinstance(order_id, str) or not order_id or len(order_id) > 100 or
                not isinstance(client_order_id, str) or not client_order_id or
                len(client_order_id) > 64):
            record_upi_event(
                None, "webhook", "rejected", error_code="webhook_order_reference_invalid",
                event_id=event_id, event_type=event_type, event_sequence=event_sequence,
                signature_valid=True, body_sha256=body_hash,
            )
            db.session.commit()
            return json_error("Webhook order reference is invalid.", 400)
        if event_data.get("environment") != app.config["UPI_GATEWAY_ENVIRONMENT"]:
            record_upi_event(
                None, "webhook", "rejected", error_code="webhook_environment_mismatch",
                event_id=event_id, event_type=event_type, event_sequence=event_sequence,
                signature_valid=True, body_sha256=body_hash,
            )
            db.session.commit()
            return json_error("Webhook environment does not match this integration.", 400)

        event_status = {
            "order.paid": "paid",
            "order.expired": "expired",
            "order.under_review": "review",
            "order.failed": "failed",
            "order.pending": "pending",
            "order.timeout": "pending",
        }.get(event_type)
        if event_type in {"order.paid", "order.expired", "order.under_review",
                          "order.failed", "order.pending", "order.timeout"} and (
                event_data.get("status") != event_status):
            record_upi_event(
                None, "webhook", "rejected", error_code="webhook_status_mismatch",
                event_id=event_id, event_type=event_type, event_sequence=event_sequence,
                signature_valid=True, body_sha256=body_hash,
            )
            db.session.commit()
            return json_error("Webhook status does not match its event.", 400)

        existing_event = ProcessedPaymentWebhook.query.filter_by(
            environment=event_data.get("environment"), event_id=event_id
        ).first()
        if existing_event:
            payment = db.session.get(Payment, existing_event.payment_id) if existing_event.payment_id else None
            record_upi_event(
                payment, "webhook", "duplicate", event_id=event_id, event_type=event_type,
                event_sequence=event_sequence, signature_valid=True, body_sha256=body_hash,
            )
            db.session.commit()
            return jsonify({"received": True, "duplicate": True})

        payment = Payment.query.filter_by(
            payment_provider="upi_gateway",
            payment_environment=event_data.get("environment"),
            gateway_order_id=event_data.get("order_id"),
            client_order_id=event_data.get("client_order_id"),
        ).first()
        if not payment:
            record_upi_event(
                None, "webhook", "rejected", error_code="webhook_order_not_found",
                event_id=event_id, event_type=event_type, event_sequence=event_sequence,
                gateway_order_id=event_data.get("order_id"),
                client_order_id=event_data.get("client_order_id"),
                signature_valid=True, body_sha256=body_hash,
            )
            db.session.commit()
            return json_error("Payment order not found.", 404)
        try:
            validate_gateway_order(payment, event_data)
            result = "unsupported"
            if event_type in {
                    "order.paid", "order.expired", "order.under_review", "order.failed",
                    "order.pending", "order.timeout"}:
                if event_type == "order.paid":
                    data = upi_gateway_client().get_order(payment.gateway_order_id)
                    if data.get("status") != "paid":
                        raise GatewayApiError(code="gateway_payment_not_verified")
                    apply_gateway_status(
                        payment, data, "webhook", event_id=event_id, event_type=event_type,
                        event_sequence=event_sequence, body_sha256=body_hash,
                    )
                else:
                    apply_gateway_status(
                        payment, event_data, "webhook", event_id=event_id, event_type=event_type,
                        event_sequence=event_sequence, body_sha256=body_hash,
                    )
                result = "processed"
            else:
                record_upi_event(
                    payment, "webhook", result, event_id=event_id, event_type=event_type,
                    event_sequence=event_sequence, gateway_order_id=payment.gateway_order_id,
                    client_order_id=payment.client_order_id, signature_valid=True,
                    body_sha256=body_hash,
                )
            db.session.add(ProcessedPaymentWebhook(
                environment=payment.payment_environment,
                event_id=event_id,
                payment_id=payment.id,
                event_sequence=event_sequence,
            ))
            db.session.commit()
        except GatewayApiError as error:
            db.session.rollback()
            payment = Payment.query.filter_by(
                payment_provider="upi_gateway",
                payment_environment=event_data.get("environment"),
                client_order_id=event_data.get("client_order_id"),
            ).first()
            record_upi_event(
                payment, "webhook", "retryable", error_code=error.code,
                event_id=event_id, event_type=event_type, event_sequence=event_sequence,
                gateway_order_id=event_data.get("order_id"),
                client_order_id=event_data.get("client_order_id"),
                signature_valid=True, body_sha256=body_hash,
            )
            db.session.commit()
            return json_error("Payment verification is temporarily unavailable.", 503)
        except ValueError as error:
            db.session.rollback()
            payment = Payment.query.filter_by(
                payment_provider="upi_gateway",
                payment_environment=event_data.get("environment"),
                client_order_id=event_data.get("client_order_id"),
            ).first()
            record_upi_event(
                payment, "webhook", "rejected", error_code=str(error),
                event_id=event_id, event_type=event_type, event_sequence=event_sequence,
                gateway_order_id=event_data.get("order_id"),
                client_order_id=event_data.get("client_order_id"),
                signature_valid=True, body_sha256=body_hash,
            )
            db.session.commit()
            return json_error("Webhook payment data did not match the stored order.", 400)
        except IntegrityError:
            db.session.rollback()
            existing_event = ProcessedPaymentWebhook.query.filter_by(
                environment=event_data.get("environment"), event_id=event_id
            ).first()
            if existing_event:
                return jsonify({"received": True, "duplicate": True})
            raise
        return jsonify({"received": True, "result": result})

    @app.post("/api/ai/chat")
    @limiter.limit("20 per minute")
    def ai_chat():
        api_key = os.getenv("OPENAI_API_KEY")
        data = request.get_json(silent=True) or {}
        message = str(data.get("message", "")).strip()
        if not message:
            return json_error("Message is required.")
        if not api_key:
            return json_error("AI assistant is not configured.", 503)
        try:
            import openai
            client = openai.OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[{"role": "system", "content": "You are the helpful Kshitij Coder e-learning assistant."},
                          {"role": "user", "content": message[:4000]}],
                temperature=0.3,
            )
            return jsonify({"reply": response.choices[0].message.content})
        except Exception as exc:
            app.logger.error("AI request failed: %s", exc)
            return json_error("AI assistant is temporarily unavailable.", 502)

    @app.get("/api/admin/stats")
    @roles_required("admin", permission="dashboard.read")
    def admin_stats(user):
        revenue = db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0)).filter(
            Payment.payment_status.in_(("captured", "approved"))
        ).scalar()
        completed_by_student_course = db.session.query(
            LessonProgress.user_id.label("user_id"),
            Lesson.course_id.label("course_id"),
            db.func.count(db.distinct(LessonProgress.lesson_id)).label("completed_count"),
        ).join(
            Lesson, Lesson.id == LessonProgress.lesson_id
        ).filter(
            LessonProgress.completion_status.is_(True)
        ).group_by(
            LessonProgress.user_id, Lesson.course_id
        ).subquery()
        course_lesson_counts = db.session.query(
            Lesson.course_id.label("course_id"),
            db.func.count(Lesson.id).label("lesson_count"),
        ).group_by(Lesson.course_id).subquery()
        completed_courses = db.session.query(
            completed_by_student_course.c.course_id
        ).join(
            course_lesson_counts,
            course_lesson_counts.c.course_id == completed_by_student_course.c.course_id,
        ).filter(
            completed_by_student_course.c.completed_count == course_lesson_counts.c.lesson_count
        ).count()
        return jsonify({
            "students": User.query.filter_by(role="student").count(),
            "active_students": User.query.filter_by(role="student", account_status="active").count(),
            "courses": Course.query.filter_by(status="published").count(),
            "enrollments": Enrollment.query.count(),
            "completed_courses": completed_courses,
            "pending_payments": Payment.query.filter_by(payment_status="pending").count(),
            "approved_payments": Payment.query.filter_by(payment_status="approved").count(),
            "rejected_payments": Payment.query.filter_by(payment_status="rejected").count(),
            "revenue": float(revenue or 0),
            "open_support_tickets": SupportTicket.query.filter(
                SupportTicket.status.in_(("open", "in_progress"))
            ).count(),
            "recent_users": [user_json(item) for item in User.query.filter_by(
                role="student"
            ).order_by(User.created_at.desc()).limit(5).all()],
            "recent_payments": [payment_json(item) for item in Payment.query.order_by(
                Payment.created_at.desc()
            ).limit(5).all()],
            "messages": ContactMessage.query.filter_by(status="new").count(),
        })

    @app.get("/api/admin/auth/me")
    @roles_required("admin", permission="dashboard.read")
    def admin_auth_me(user):
        if user.role == "super_admin":
            permissions = [item.code for item in AdminPermission.query.order_by(
                AdminPermission.code
            ).all()]
        else:
            permissions = [row.permission.code for row in AdminRolePermission.query.filter_by(
                role_id=user.admin_role_id
            ).all()]
        return jsonify({"user": user_json(user), "permissions": permissions,
                        "is_super_admin": user.role == "super_admin"})

    @app.route("/api/admin/users")
    @roles_required("admin", permission="students.read")
    def admin_users(user):
        search = str(request.args.get("search", "")).strip()
        query = User.query.filter_by(role="student")
        if search:
            query = query.filter(db.or_(User.full_name.ilike(f"%{search}%"), User.email.ilike(f"%{search}%")))
        registered_after = request.args.get("registered_after")
        registered_before = request.args.get("registered_before")
        if registered_after:
            try:
                query = query.filter(User.created_at >= datetime.fromisoformat(registered_after))
            except ValueError:
                return json_error("Invalid registration start date.")
        if registered_before:
            try:
                query = query.filter(User.created_at < datetime.fromisoformat(registered_before))
            except ValueError:
                return json_error("Invalid registration end date.")
        page = max(request.args.get("page", 1, type=int), 1)
        limit = min(max(request.args.get("limit", 25, type=int), 1), 100)
        pagination = query.order_by(User.created_at.desc()).paginate(
            page=page, per_page=limit, error_out=False
        )
        return jsonify({"users": [user_json(item) for item in pagination.items],
                        "page": pagination.page, "pages": pagination.pages,
                        "total": pagination.total})

    @app.get("/api/admin/users/<int:user_id>")
    @roles_required("admin", permission="students.read")
    def admin_student_detail(user, user_id):
        student = db.session.get(User, user_id)
        if not student or student.role != "student":
            return json_error("Student not found.", 404)
        enrollments = Enrollment.query.filter_by(user_id=student.id).order_by(
            Enrollment.enrollment_date.desc()
        ).all()
        payments = Payment.query.filter_by(user_id=student.id).order_by(
            Payment.created_at.desc()
        ).limit(50).all()
        certificates = Certificate.query.filter_by(user_id=student.id).order_by(
            Certificate.issue_date.desc()
        ).all()
        activity = StudentActivity.query.filter_by(user_id=student.id).order_by(
            StudentActivity.created_at.desc()
        ).limit(50).all()
        return jsonify({
            "student": user_json(student),
            "enrollments": [{
                "id": item.id, "course_id": item.course_id, "course_title": item.course.title,
                "enrollment_date": item.enrollment_date.isoformat() if item.enrollment_date else None,
                "payment_status": item.payment_status, "access_status": item.access_status,
                "access_expires_at": item.access_expires_at.isoformat()
                if item.access_expires_at else None,
            } for item in enrollments],
            "payments": [payment_json(item) for item in payments],
            "certificates": [{
                "id": item.id, "certificate_number": item.certificate_number,
                "course_id": item.course_id, "course_title": db.session.get(
                    Course, item.course_id
                ).title, "issue_date": item.issue_date.isoformat() if item.issue_date else None,
                "revoked_at": item.revoked_at.isoformat() if item.revoked_at else None,
            } for item in certificates],
            "activity": [{
                "event": item.event, "details": item.details,
                "created_at": item.created_at.isoformat(),
            } for item in activity],
        })

    @app.route("/api/admin/users/<int:user_id>", methods=["PUT"])
    @roles_required("admin", permission="students.manage")
    def admin_update_user(user, user_id):
        target = db.session.get(User, user_id)
        if not target or target.role != "student":
            return json_error("User not found.", 404)
        data = request.get_json(silent=True) or {}
        previous = {"full_name": target.full_name, "account_status": target.account_status}
        if "full_name" in data:
            full_name = str(data["full_name"]).strip()
            if not full_name or len(full_name) > 120:
                return json_error("Valid student name is required.")
            target.full_name = full_name
        if "account_status" in data:
            if data["account_status"] not in {"active", "inactive"}:
                return json_error("Account status must be active or inactive.")
            target.account_status = data["account_status"]
        reason = str(data.get("reason", "")).strip()
        admin_audit(user, "student_updated", "students", "user", target.id,
                    previous, {"full_name": target.full_name,
                               "account_status": target.account_status}, reason)
        db.session.commit()
        return jsonify({"message": "User updated.", "user": user_json(target)})

    @app.route("/api/admin/courses", methods=["POST"])
    @roles_required("admin", permission="courses.manage")
    def admin_create_course(user):
        data = request.get_json(silent=True) or {}
        title = str(data.get("title", "")).strip()
        if not title:
            return json_error("Course title is required.")
        try:
            price = float(data.get("price", 0))
            discount = float(data.get("discount_percent", 0))
        except (TypeError, ValueError):
            return json_error("Price and discount must be valid numbers.")
        status = data.get("status", "draft")
        if price < 0 or not 0 <= discount <= 100:
            return json_error("Price must be non-negative and discount must be between 0 and 100.")
        if status not in {"draft", "published", "archived"}:
            return json_error("Invalid course status.")
        is_featured = data.get("is_featured", False)
        if not isinstance(is_featured, bool):
            return json_error("Featured must be a boolean.")
        course = Course(
            title=title[:200],
            description=str(data.get("description", "")).strip(),
            thumbnail=str(data.get("thumbnail", "")).strip() or None,
            category=str(data.get("category", "")).strip()[:100] or "General",
            instructor_id=user.id, price=price, discount_percent=discount,
            course_duration=str(data.get("course_duration", "")).strip()[:50],
            level=str(data.get("level", "beginner")).strip()[:30],
            objectives=str(data.get("objectives", "")).strip(),
            is_featured=is_featured,
            status=status,
        )
        db.session.add(course)
        db.session.commit()
        return jsonify({"message": "Course created.", "course": course_json(course)}), 201

    @app.get("/api/admin/courses")
    @roles_required("admin", permission="courses.read")
    def admin_courses(user):
        query = Course.query
        search = str(request.args.get("search", "")).strip()
        status = str(request.args.get("status", "")).strip()
        category = str(request.args.get("category", "")).strip()
        if search:
            query = query.filter(Course.title.ilike(f"%{search[:100]}%"))
        if status:
            if status not in {"draft", "published", "archived"}:
                return json_error("Invalid course status filter.")
            query = query.filter_by(status=status)
        if category:
            query = query.filter_by(category=category)
        return jsonify({"courses": [course_json(item) for item in query.order_by(
            Course.created_at.desc()
        ).all()]})

    @app.post("/api/admin/courses/<int:course_id>/duplicate")
    @roles_required("admin", permission="courses.manage")
    def admin_duplicate_course(user, course_id):
        original = db.session.get(Course, course_id)
        if not original:
            return json_error("Course not found.", 404)
        duplicate = Course(
            title=(original.title[:185] + " (Copy)"),
            description=original.description, thumbnail=original.thumbnail,
            category=original.category, instructor_id=user.id, price=original.price,
            discount_percent=original.discount_percent, course_duration=original.course_duration,
            level=original.level, objectives=original.objectives,
            is_featured=False, status="draft",
        )
        db.session.add(duplicate)
        db.session.flush()
        for lesson in original.lessons:
            db.session.add(Lesson(
                course_id=duplicate.id, title=lesson.title, description=lesson.description,
                video_url=None if lesson.video_path else lesson.video_url,
                lesson_order=lesson.lesson_order,
                duration=lesson.duration, is_preview=lesson.is_preview,
            ))
        admin_audit(user, "course_duplicated", "courses", "course", duplicate.id,
                    {"source_course_id": original.id}, {"title": duplicate.title})
        db.session.commit()
        return jsonify({"message": "Course duplicated as a draft.",
                        "course": course_json(duplicate)}), 201

    @app.route("/api/admin/categories", methods=["GET", "POST"])
    @roles_required("admin", permission="courses.read")
    def admin_categories(user):
        if request.method == "GET":
            categories = {
                item.name: {"id": item.id, "description": item.description}
                for item in CourseCategory.query.all()
            }
            for name, in db.session.query(Course.category).filter(
                    Course.category.isnot(None), Course.category != "").distinct().all():
                categories.setdefault(name, {"id": None, "description": ""})
            return jsonify({"categories": [
                {"name": name, "id": item["id"], "description": item["description"]}
                for name, item in sorted(categories.items())
            ]})
        if not has_admin_permission(user, "courses.manage"):
            return json_error("Forbidden.", 403)
        data = request.get_json(silent=True) or {}
        name = str(data.get("name", "")).strip()
        if not name or len(name) > 100:
            return json_error("Category name is required and must be at most 100 characters.")
        if CourseCategory.query.filter(db.func.lower(CourseCategory.name) == name.lower()).first():
            return json_error("Category already exists.", 409)
        category = CourseCategory(name=name, description=str(data.get("description", "")).strip()[:500])
        db.session.add(category)
        admin_audit(user, "category_created", "courses", "category", name,
                    None, {"name": name, "description": category.description})
        db.session.commit()
        return jsonify({"message": "Category created.", "name": name}), 201

    @app.route("/api/admin/categories/<int:category_id>", methods=["PUT", "DELETE"])
    @roles_required("admin", permission="courses.manage")
    def admin_manage_category(user, category_id):
        category = db.session.get(CourseCategory, category_id)
        if not category:
            return json_error("Category not found.", 404)
        used = Course.query.filter_by(category=category.name).count()
        if request.method == "DELETE":
            if used:
                return json_error("Move or archive courses in this category before deleting it.", 409)
            admin_audit(user, "category_deleted", "courses", "category", category.id,
                        {"name": category.name}, None)
            db.session.delete(category)
            db.session.commit()
            return jsonify({"message": "Category deleted."})
        data = request.get_json(silent=True) or {}
        name = str(data.get("name", "")).strip()
        if not name or len(name) > 100:
            return json_error("Category name is required.")
        previous = {"name": category.name, "description": category.description}
        old_name = category.name
        category.name = name
        category.description = str(data.get("description", category.description)).strip()[:500]
        if old_name != name:
            Course.query.filter_by(category=old_name).update(
                {Course.category: name}, synchronize_session=False
            )
        admin_audit(user, "category_updated", "courses", "category", category.id,
                    previous, {"name": category.name, "description": category.description})
        db.session.commit()
        return jsonify({"message": "Category updated.", "name": category.name})

    @app.route("/api/admin/courses/<int:course_id>/lessons", methods=["GET", "POST"])
    @roles_required("admin", permission="courses.read")
    def admin_course_lessons(user, course_id):
        course = db.session.get(Course, course_id)
        if not course:
            return json_error("Course not found.", 404)
        if request.method == "GET":
            return jsonify({"lessons": [{
                "id": lesson.id, "title": lesson.title, "description": lesson.description,
                "video_url": lesson.video_url, "lesson_order": lesson.lesson_order,
                "duration": lesson.duration, "is_preview": lesson.is_preview,
            } for lesson in course.lessons]})
        if not has_admin_permission(user, "lessons.manage"):
            return json_error("Forbidden.", 403)
        data = request.get_json(silent=True) or {}
        title = str(data.get("title", "")).strip()
        if not title or len(title) > 200:
            return json_error("Lesson title is required.")
        video_url = str(data.get("video_url", "")).strip()
        if video_url and not video_url.startswith(("https://", "http://", "/api/lessons/")):
            return json_error("Video URL must use HTTPS or a protected application video route.")
        try:
            order = int(data.get("lesson_order", len(course.lessons) + 1))
        except (TypeError, ValueError):
            return json_error("Lesson order must be a whole number.")
        is_preview = data.get("is_preview", False)
        if not isinstance(is_preview, bool):
            return json_error("is_preview must be a boolean.")
        lesson = Lesson(
            course_id=course.id, title=title, description=str(data.get("description", "")).strip(),
            video_url=video_url or None, lesson_order=max(order, 1),
            duration=str(data.get("duration", "")).strip()[:50],
            is_preview=is_preview,
        )
        db.session.add(lesson)
        db.session.flush()
        admin_audit(user, "lesson_created", "lessons", "lesson", lesson.id,
                    None, {"course_id": course.id, "title": lesson.title})
        db.session.commit()
        return jsonify({"message": "Lesson created.", "lesson_id": lesson.id}), 201

    @app.route("/api/admin/lessons/<int:lesson_id>", methods=["PUT", "DELETE"])
    @roles_required("admin", permission="lessons.manage")
    def admin_manage_lesson(user, lesson_id):
        lesson = db.session.get(Lesson, lesson_id)
        if not lesson:
            return json_error("Lesson not found.", 404)
        if request.method == "DELETE":
            if LessonProgress.query.filter_by(lesson_id=lesson.id).first():
                return json_error("Lessons with student progress cannot be deleted.", 409)
            admin_audit(user, "lesson_deleted", "lessons", "lesson", lesson.id,
                        {"title": lesson.title, "course_id": lesson.course_id}, None)
            db.session.delete(lesson)
            db.session.commit()
            return jsonify({"message": "Lesson deleted."})
        data = request.get_json(silent=True) or {}
        previous = {"title": lesson.title, "lesson_order": lesson.lesson_order,
                    "is_preview": lesson.is_preview}
        if "title" in data:
            title = str(data["title"]).strip()
            if not title or len(title) > 200:
                return json_error("Valid lesson title is required.")
            lesson.title = title
        if "lesson_order" in data:
            try:
                lesson.lesson_order = max(int(data["lesson_order"]), 1)
            except (TypeError, ValueError):
                return json_error("Lesson order must be a whole number.")
        if "video_url" in data:
            video_url = str(data["video_url"]).strip()
            if video_url and not video_url.startswith(("https://", "http://", "/api/lessons/")):
                return json_error("Video URL must use HTTPS or a protected application video route.")
            lesson.video_url = video_url or None
        if "description" in data:
            lesson.description = str(data["description"]).strip()
        if "duration" in data:
            lesson.duration = str(data["duration"]).strip()[:50]
        if "is_preview" in data:
            if not isinstance(data["is_preview"], bool):
                return json_error("is_preview must be a boolean.")
            lesson.is_preview = data["is_preview"]
        admin_audit(user, "lesson_updated", "lessons", "lesson", lesson.id,
                    previous, {"title": lesson.title, "lesson_order": lesson.lesson_order,
                               "is_preview": lesson.is_preview})
        db.session.commit()
        return jsonify({"message": "Lesson updated."})

    @app.route("/api/admin/courses/<int:course_id>", methods=["PUT", "DELETE"])
    @roles_required("admin", permission="courses.manage")
    def admin_manage_course(user, course_id):
        course = db.session.get(Course, course_id)
        if not course:
            return json_error("Course not found.", 404)
        if request.method == "DELETE":
            archived = False
            if Enrollment.query.filter_by(course_id=course.id).first() or Payment.query.filter_by(
                    course_id=course.id).first():
                previous = {"status": course.status}
                course.status = "archived"
                archived = True
                admin_audit(user, "course_archived", "courses", "course", course.id,
                            previous, {"status": course.status}, "Records are retained for student history.")
            else:
                admin_audit(user, "course_deleted", "courses", "course", course.id,
                            {"title": course.title}, None, "No enrollments or payments exist.")
                db.session.delete(course)
            db.session.commit()
            return jsonify({"message": "Course archived." if archived else "Course deleted."})
        data = request.get_json(silent=True) or {}
        previous = course_json(course)
        if "title" in data:
            title = str(data["title"]).strip()
            if not title or len(title) > 200:
                return json_error("Valid course title is required.")
            course.title = title
        if "price" in data:
            try:
                price = float(data["price"])
            except (TypeError, ValueError):
                return json_error("Price must be a valid number.")
            if price < 0:
                return json_error("Price must be non-negative.")
            course.price = price
        if "discount_percent" in data:
            try:
                discount = float(data["discount_percent"])
            except (TypeError, ValueError):
                return json_error("Discount must be a valid number.")
            if not 0 <= discount <= 100:
                return json_error("Discount must be between 0 and 100.")
            course.discount_percent = discount
        if "status" in data:
            if data["status"] not in {"draft", "published", "archived"}:
                return json_error("Invalid course status.")
            course.status = data["status"]
        if "is_featured" in data:
            if not isinstance(data["is_featured"], bool):
                return json_error("Featured must be a boolean.")
            course.is_featured = data["is_featured"]
        for field, max_length in (("description", None), ("thumbnail", 255), ("category", 100),
                                  ("course_duration", 50), ("level", 30), ("objectives", None)):
            if field in data:
                value = str(data[field]).strip()
                setattr(course, field, value[:max_length] if max_length else value)
        admin_audit(user, "course_updated", "courses", "course", course.id,
                    previous, course_json(course))
        db.session.commit()
        return jsonify({"message": "Course updated.", "course": course_json(course)})

    @app.get("/api/admin/contact")
    @roles_required("admin", permission="support.read")
    def admin_contact(user):
        messages = ContactMessage.query.order_by(ContactMessage.created_at.desc()).all()
        return jsonify({"messages": [{"id": m.id, "name": m.name, "email": m.email, "subject": m.subject,
                                      "message": m.message, "status": m.status,
                                      "created_at": m.created_at.isoformat()} for m in messages]})

    @app.get("/api/admin/payments")
    @roles_required("admin", permission="payments.read")
    def admin_payments(user):
        query = Payment.query
        status = str(request.args.get("status", "")).strip()
        search = str(request.args.get("search", "")).strip()
        environment = str(request.args.get("environment", "")).strip().lower()
        if status:
            if status not in {
                    "pending", "processing", "under_review", "expired", "approved",
                    "rejected", "captured", "failed", "refunded"}:
                return json_error("Invalid payment status filter.")
            query = query.filter_by(payment_status=status)
        if environment:
            if environment not in {"live", "sandbox"}:
                return json_error("Invalid payment environment filter.")
            query = query.filter_by(
                payment_provider="upi_gateway", payment_environment=environment
            )
        if search:
            query = query.join(User, User.id == Payment.user_id).filter(db.or_(
                User.full_name.ilike(f"%{search[:100]}%"),
                User.email.ilike(f"%{search[:100]}%"),
                Payment.transaction_id.ilike(f"%{search[:100]}%"),
                Payment.gateway_order_id.ilike(f"%{search[:100]}%"),
            ))
        return jsonify({"payments": [payment_json(item) for item in query.order_by(
            Payment.created_at.desc()
        ).limit(500).all()]})

    @app.get("/api/admin/payment-gateway-events")
    @roles_required("admin", permission="payments.read")
    def admin_payment_gateway_events(user):
        query = PaymentGatewayEvent.query
        environment = str(request.args.get("environment", "")).strip().lower()
        result = str(request.args.get("result", "")).strip()
        if environment:
            if environment not in {"live", "sandbox"}:
                return json_error("Invalid payment environment filter.")
            query = query.filter_by(environment=environment)
        if result:
            query = query.filter_by(result=result[:30])
        events = query.order_by(PaymentGatewayEvent.received_at.desc()).limit(200).all()
        return jsonify({"events": [{
            "id": item.id,
            "payment_id": item.payment_id,
            "environment": item.environment,
            "source": item.source,
            "event_id": item.event_id,
            "event_type": item.event_type,
            "event_sequence": item.event_sequence,
            "gateway_order_id": item.gateway_order_id,
            "client_order_id": item.client_order_id,
            "signature_valid": item.signature_valid,
            "result": item.result,
            "error_code": item.error_code,
            "received_at": item.received_at.isoformat() if item.received_at else None,
            "processed_at": item.processed_at.isoformat() if item.processed_at else None,
        } for item in events]})

    @app.get("/api/admin/payments/<int:payment_id>/events")
    @roles_required("admin", permission="payments.read")
    def admin_payment_gateway_history(user, payment_id):
        payment = db.session.get(Payment, payment_id)
        if not payment or payment.payment_provider != "upi_gateway":
            return json_error("UPI payment not found.", 404)
        events = PaymentGatewayEvent.query.filter_by(payment_id=payment.id).order_by(
            PaymentGatewayEvent.received_at.desc()
        ).limit(100).all()
        return jsonify({"events": [{
            "id": item.id,
            "environment": item.environment,
            "source": item.source,
            "event_id": item.event_id,
            "event_type": item.event_type,
            "event_sequence": item.event_sequence,
            "result": item.result,
            "error_code": item.error_code,
            "signature_valid": item.signature_valid,
            "received_at": item.received_at.isoformat() if item.received_at else None,
            "processed_at": item.processed_at.isoformat() if item.processed_at else None,
        } for item in events]})

    @app.get("/api/payments/mine")
    @login_required
    def student_payments(user):
        if user.role != "student":
            return json_error("Student account required.", 403)
        payments = Payment.query.filter_by(user_id=user.id).order_by(
            Payment.created_at.desc()
        ).limit(100).all()
        return jsonify({"payments": [{
            "id": item.id, "course_title": item.course.title,
            "amount": f"{Decimal(str(item.amount)):.2f}", "provider": item.payment_provider,
            "method": item.payment_method, "status": item.payment_status,
            "remarks": item.review_remarks,
            "environment": item.payment_environment,
            "currency": item.currency,
            "transaction_reference": item.transaction_id
            if item.payment_provider != "manual" else None,
            "gateway_order_id": item.gateway_order_id,
            "created_at": datetime_iso_utc(item.created_at),
            "verified_at": datetime_iso_utc(item.verified_at),
            "receipt_url": f"/api/payments/{item.id}/receipt"
            if item.payment_provider == "upi_gateway" and
            item.payment_environment == "live" and item.verified_at and
            item.payment_status == "captured" else None,
            "checkout_url": item.checkout_url if item.payment_provider == "upi_gateway" else None,
        } for item in payments]})

    @app.post("/api/payments/manual")
    @login_required
    @limiter.limit("10 per minute")
    def create_manual_payment(user):
        if user.role != "student":
            return json_error("Student account required.", 403)
        data = request.form if request.form else (request.get_json(silent=True) or {})
        try:
            course_id = int(data.get("course_id"))
        except (TypeError, ValueError):
            return json_error("A valid course is required.")
        course = db.session.get(Course, course_id)
        if not course or course.status != "published" or float(course.price) <= 0:
            return json_error("Paid course not found.", 404)
        if Enrollment.query.filter_by(user_id=user.id, course_id=course.id,
                                      access_status="active").first():
            return json_error("You already have active access to this course.", 409)
        if Payment.query.filter_by(user_id=user.id, course_id=course.id,
                                   payment_status="pending").first():
            return json_error("A payment request for this course is already pending.", 409)
        transaction_id = str(data.get("transaction_id", "")).strip()
        method = str(data.get("payment_method", "")).strip().lower()
        if not transaction_id or len(transaction_id) > 255:
            return json_error("Payment reference is required.")
        if method not in {"upi", "bank_transfer", "cash"}:
            return json_error("Payment method must be UPI, bank_transfer, or cash.")
        transaction_key = f"manual-{user.id}-{course.id}-{transaction_id}"
        if Payment.query.filter_by(transaction_id=transaction_key).first():
            return json_error("This payment reference was already submitted.", 409)
        proof = request.files.get("proof")
        proof_path = None
        if proof and proof.filename:
            if uploaded_file_size(proof) > app.config["MAX_PAYMENT_PROOF_BYTES"]:
                return json_error("Payment proof exceeds the upload size limit.", 413)
            safe_name = secure_filename(proof.filename)
            extension = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
            if extension not in {"png", "jpg", "jpeg", "pdf"}:
                return json_error("Payment proof must be a PNG, JPG, or PDF file.")
            folder = os.path.join(app.config["UPLOAD_FOLDER"], "payments")
            os.makedirs(folder, exist_ok=True)
            stored_name = f"{uuid.uuid4().hex}.{extension}"
            proof.save(os.path.join(folder, stored_name))
            proof_path = os.path.join("payments", stored_name)
        payment = Payment(
            user_id=user.id, course_id=course.id, amount=course.price,
            payment_provider="manual", payment_method=method,
            transaction_id=transaction_key, payment_status="pending", proof_path=proof_path,
        )
        db.session.add(payment)
        record_student_activity(user, "manual_payment_submitted", {"course_id": course.id})
        for administrator in User.query.filter(
                User.role.in_(("admin", "super_admin")), User.account_status == "active").all():
            create_notification(administrator.id, "payment_pending", "Payment approval required",
                                f"{user.full_name} submitted a manual payment request.",
                                "/admin.html#payments")
        db.session.commit()
        socketio.emit("admin_payment_pending", {"payment_id": payment.id}, room="support:admins")
        return jsonify({"message": "Payment submitted for review. Course access is pending.",
                        "payment": {"id": payment.id, "status": payment.payment_status}}), 201

    @app.post("/api/payments/manual/<int:payment_id>/proof")
    @login_required
    def upload_manual_payment_proof(user, payment_id):
        payment = db.session.get(Payment, payment_id)
        if not payment or payment.user_id != user.id or payment.payment_provider != "manual":
            return json_error("Payment request not found.", 404)
        if payment.payment_status != "pending":
            return json_error("Proof can only be updated while payment is pending.", 409)
        proof = request.files.get("proof")
        if not proof or not proof.filename:
            return json_error("Payment proof file is required.")
        if uploaded_file_size(proof) > app.config["MAX_PAYMENT_PROOF_BYTES"]:
            return json_error("Payment proof exceeds the upload size limit.", 413)
        safe_name = secure_filename(proof.filename)
        extension = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
        if extension not in {"png", "jpg", "jpeg", "pdf"}:
            return json_error("Payment proof must be a PNG, JPG, or PDF file.")
        folder = os.path.join(app.config["UPLOAD_FOLDER"], "payments")
        os.makedirs(folder, exist_ok=True)
        stored_name = f"{uuid.uuid4().hex}.{extension}"
        proof.save(os.path.join(folder, stored_name))
        payment.proof_path = os.path.join("payments", stored_name)
        db.session.commit()
        return jsonify({"message": "Payment proof uploaded."})

    @app.get("/api/admin/payments/<int:payment_id>/proof")
    @roles_required("admin", permission="payments.read")
    def admin_payment_proof(user, payment_id):
        payment = db.session.get(Payment, payment_id)
        if not payment or not payment.proof_path:
            return json_error("Payment proof not found.", 404)
        return send_from_directory(
            app.config["UPLOAD_FOLDER"], payment.proof_path, as_attachment=True,
            download_name=os.path.basename(payment.proof_path),
        )

    @app.post("/api/admin/payments/<int:payment_id>/approve")
    @roles_required("admin", permission="payments.manage")
    def admin_approve_payment(user, payment_id):
        payment = db.session.get(Payment, payment_id)
        if not payment:
            return json_error("Payment not found.", 404)
        if payment.payment_provider != "manual":
            return json_error("Only manual payment requests can be approved here.", 409)
        if payment.payment_status != "pending":
            return json_error("Only pending requests can be approved.", 409)
        previous = {"status": payment.payment_status}
        payment.payment_status = "approved"
        payment.reviewed_by_id = user.id
        payment.reviewed_at = datetime.now(timezone.utc)
        payment.review_remarks = str((request.get_json(silent=True) or {}).get("remarks", "")).strip()[:2000]
        enrollment = Enrollment.query.filter_by(
            user_id=payment.user_id, course_id=payment.course_id
        ).first()
        if enrollment:
            enrollment.access_status = "active"
            enrollment.payment_status = "paid"
            enrollment.access_expires_at = None
        else:
            db.session.add(Enrollment(
                user_id=payment.user_id, course_id=payment.course_id,
                payment_status="paid", access_status="active",
            ))
        admin_audit(user, "manual_payment_approved", "payments", "payment", payment.id,
                    previous, {"status": "approved", "user_id": payment.user_id,
                               "course_id": payment.course_id}, payment.review_remarks)
        create_notification(payment.user_id, "payment_approved", "Payment approved",
                            f"Your payment for {payment.course.title} was approved. Course access is active.",
                            "/dashboard.html")
        record_student_activity(db.session.get(User, payment.user_id), "payment_approved",
                                {"payment_id": payment.id, "course_id": payment.course_id})
        db.session.commit()
        return jsonify({"message": "Payment approved and course access activated."})

    @app.post("/api/admin/payments/<int:payment_id>/reject")
    @roles_required("admin", permission="payments.manage")
    def admin_reject_payment(user, payment_id):
        payment = db.session.get(Payment, payment_id)
        if not payment:
            return json_error("Payment not found.", 404)
        if payment.payment_provider != "manual" or payment.payment_status != "pending":
            return json_error("Only pending manual payments can be rejected.", 409)
        data = request.get_json(silent=True) or {}
        reason = str(data.get("reason", "")).strip()
        if not reason or len(reason) > 2000:
            return json_error("A rejection reason is required.")
        previous = {"status": payment.payment_status}
        payment.payment_status = "rejected"
        payment.reviewed_by_id = user.id
        payment.reviewed_at = datetime.now(timezone.utc)
        payment.review_remarks = reason
        admin_audit(user, "manual_payment_rejected", "payments", "payment", payment.id,
                    previous, {"status": "rejected"}, reason)
        create_notification(payment.user_id, "payment_rejected", "Payment rejected",
                            reason, "/dashboard.html")
        record_student_activity(db.session.get(User, payment.user_id), "payment_rejected",
                                {"payment_id": payment.id, "course_id": payment.course_id})
        db.session.commit()
        return jsonify({"message": "Payment rejected. No course access was granted."})

    @app.get("/api/admin/enrollments")
    @roles_required("admin", permission="enrollments.read")
    def admin_enrollments(user):
        query = Enrollment.query.join(User, User.id == Enrollment.user_id)
        student_search = str(request.args.get("student", "")).strip()
        course_id = request.args.get("course_id", type=int)
        if student_search:
            query = query.filter(db.or_(
                User.full_name.ilike(f"%{student_search[:100]}%"),
                User.email.ilike(f"%{student_search[:100]}%"),
            ))
        if course_id:
            query = query.filter(Enrollment.course_id == course_id)
        items = query.order_by(Enrollment.enrollment_date.desc()).limit(500).all()
        return jsonify({"enrollments": [{
            "id": item.id, "student": user_json(item.user), "course_id": item.course_id,
            "course_title": item.course.title, "enrollment_date": item.enrollment_date.isoformat()
            if item.enrollment_date else None, "payment_status": item.payment_status,
            "access_status": item.access_status,
            "access_expires_at": item.access_expires_at.isoformat()
            if item.access_expires_at else None,
        } for item in items]})

    @app.post("/api/admin/enrollments")
    @roles_required("admin", permission="enrollments.manage")
    def admin_grant_enrollment(user):
        data = request.get_json(silent=True) or {}
        reason = str(data.get("reason", "")).strip()
        if not reason or len(reason) > 500:
            return json_error("A reason is required for complimentary course access.")
        student = db.session.get(User, data.get("student_id"))
        course = db.session.get(Course, data.get("course_id"))
        if not student or student.role != "student" or not course:
            return json_error("Student or course not found.", 404)
        enrollment = Enrollment.query.filter_by(
            user_id=student.id, course_id=course.id
        ).first()
        previous = {"access_status": enrollment.access_status} if enrollment else None
        if enrollment:
            enrollment.access_status = "active"
            enrollment.payment_status = "complimentary"
            enrollment.access_expires_at = None
        else:
            enrollment = Enrollment(
                user_id=student.id, course_id=course.id,
                payment_status="complimentary", access_status="active",
            )
            db.session.add(enrollment)
            db.session.flush()
        admin_audit(user, "complimentary_enrollment_granted", "enrollments", "enrollment",
                    enrollment.id, previous, {"access_status": "active",
                    "student_id": student.id, "course_id": course.id}, reason)
        create_notification(student.id, "enrollment_activated", "Course access activated",
                            f"Access to {course.title} has been granted.",
                            "/dashboard.html")
        db.session.commit()
        return jsonify({"message": "Course access granted.", "enrollment_id": enrollment.id}), 201

    @app.patch("/api/admin/enrollments/<int:enrollment_id>")
    @roles_required("admin", permission="enrollments.manage")
    def admin_update_enrollment(user, enrollment_id):
        enrollment = db.session.get(Enrollment, enrollment_id)
        if not enrollment:
            return json_error("Enrollment not found.", 404)
        data = request.get_json(silent=True) or {}
        reason = str(data.get("reason", "")).strip()
        if not reason or len(reason) > 500:
            return json_error("A reason is required for enrollment access changes.")
        previous = {"access_status": enrollment.access_status,
                    "access_expires_at": enrollment.access_expires_at}
        if "access_status" in data:
            if data["access_status"] not in {"active", "suspended", "revoked"}:
                return json_error("Invalid enrollment access status.")
            enrollment.access_status = data["access_status"]
        if "access_expires_at" in data:
            raw_expiry = data["access_expires_at"]
            if raw_expiry:
                try:
                    expiry = datetime.fromisoformat(str(raw_expiry).replace("Z", "+00:00"))
                except ValueError:
                    return json_error("Invalid access expiry date.")
                enrollment.access_expires_at = expiry
            else:
                enrollment.access_expires_at = None
        admin_audit(user, "enrollment_access_updated", "enrollments", "enrollment",
                    enrollment.id, previous, {
                        "access_status": enrollment.access_status,
                        "access_expires_at": enrollment.access_expires_at,
                    }, reason)
        create_notification(enrollment.user_id, "enrollment_updated", "Course access updated",
                            f"Your access to {enrollment.course.title} was updated.",
                            "/dashboard.html")
        db.session.commit()
        return jsonify({"message": "Enrollment access updated."})

    @app.get("/api/admin/notes")
    @roles_required("admin", permission="notes.manage")
    def admin_notes(user):
        return jsonify({"notes": [course_note_json(item) for item in CourseNote.query.order_by(
            CourseNote.created_at.desc()
        ).limit(500).all()]})

    @app.post("/api/admin/notes")
    @roles_required("admin", permission="notes.manage")
    def admin_create_note(user):
        data = request.form
        try:
            course_id = int(data.get("course_id", ""))
        except (TypeError, ValueError):
            return json_error("A valid course is required.")
        course = db.session.get(Course, course_id)
        title = str(data.get("title", "")).strip()
        upload = request.files.get("file")
        if not course or not title or len(title) > 200:
            return json_error("Course and valid note title are required.")
        if not upload or not upload.filename:
            return json_error("A PDF file is required.")
        if uploaded_file_size(upload) > app.config["MAX_NOTE_UPLOAD_BYTES"]:
            return json_error("Study note exceeds the upload size limit.", 413)
        file_name = secure_filename(upload.filename)
        if not file_name.lower().endswith(".pdf"):
            return json_error("Study notes must be PDF files.")
        lesson_id = data.get("lesson_id", type=int)
        if lesson_id and not Lesson.query.filter_by(id=lesson_id, course_id=course.id).first():
            return json_error("Lesson does not belong to the selected course.")
        folder = os.path.join(app.config["UPLOAD_FOLDER"], "notes")
        os.makedirs(folder, exist_ok=True)
        stored_name = f"{uuid.uuid4().hex}.pdf"
        upload.save(os.path.join(folder, stored_name))
        note = CourseNote(
            course_id=course.id, lesson_id=lesson_id, title=title,
            description=str(data.get("description", "")).strip()[:1000],
            file_path=os.path.join("notes", stored_name), file_name=file_name,
            is_published=data.get("is_published") == "true", created_by_id=user.id,
        )
        db.session.add(note)
        db.session.flush()
        admin_audit(user, "course_note_created", "notes", "course_note", note.id,
                    None, {"course_id": course.id, "title": note.title})
        db.session.commit()
        return jsonify({"message": "Study note added.", "note": course_note_json(note)}), 201

    @app.delete("/api/admin/notes/<int:note_id>")
    @roles_required("admin", permission="notes.manage")
    def admin_delete_note(user, note_id):
        note = db.session.get(CourseNote, note_id)
        if not note:
            return json_error("Study note not found.", 404)
        file_path = note.file_path
        admin_audit(user, "course_note_deleted", "notes", "course_note", note.id,
                    {"course_id": note.course_id, "title": note.title}, None)
        db.session.delete(note)
        db.session.commit()
        try:
            os.remove(os.path.join(app.config["UPLOAD_FOLDER"], file_path))
        except FileNotFoundError:
            app.logger.warning("Study note file missing for note %s", note_id)
        return jsonify({"message": "Study note deleted."})

    @app.get("/api/courses/<int:course_id>/notes")
    @login_required
    def student_course_notes(user, course_id):
        course = db.session.get(Course, course_id)
        if not course or course.status != "published":
            return json_error("Course not found.", 404)
        enrollment = Enrollment.query.filter_by(
            user_id=user.id, course_id=course.id, access_status="active"
        ).first()
        if float(course.price) > 0 and (not enrollment or not enrollment_is_unexpired(enrollment)):
            return json_error("Enroll in this course to access its study notes.", 403)
        notes = CourseNote.query.filter_by(course_id=course.id, is_published=True).order_by(
            CourseNote.created_at.desc()
        ).all()
        record_student_activity(user, "notes_accessed", {"course_id": course.id})
        db.session.commit()
        return jsonify({"notes": [course_note_json(note) for note in notes]})

    @app.get("/api/notes/<int:note_id>/download")
    @login_required
    def download_course_note(user, note_id):
        note = db.session.get(CourseNote, note_id)
        if not note or not note.is_published:
            return json_error("Study note not found.", 404)
        course = db.session.get(Course, note.course_id)
        enrollment = Enrollment.query.filter_by(
            user_id=user.id, course_id=course.id, access_status="active"
        ).first()
        is_admin = user.role == "super_admin" or has_admin_permission(user, "notes.manage")
        if not is_admin and not (
                float(course.price) <= 0 or enrollment and enrollment_is_unexpired(enrollment)):
            return json_error("Course enrollment required.", 403)
        record_student_activity(user, "note_downloaded", {"note_id": note.id, "course_id": course.id})
        db.session.commit()
        return send_from_directory(
            app.config["UPLOAD_FOLDER"], note.file_path, as_attachment=True,
            download_name=note.file_name,
        )

    @app.post("/api/admin/lessons/<int:lesson_id>/video")
    @roles_required("admin", permission="lessons.manage")
    def admin_upload_lesson_video(user, lesson_id):
        lesson = db.session.get(Lesson, lesson_id)
        upload = request.files.get("file")
        if not lesson:
            return json_error("Lesson not found.", 404)
        if not upload or not upload.filename:
            return json_error("A video file is required.")
        if uploaded_file_size(upload) > app.config["MAX_VIDEO_UPLOAD_BYTES"]:
            return json_error("Video exceeds the upload size limit.", 413)
        safe_name = secure_filename(upload.filename)
        extension = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
        if extension not in {"mp4", "webm", "mov"}:
            return json_error("Video must be MP4, WebM, or MOV.")
        folder = os.path.join(app.config["UPLOAD_FOLDER"], "videos")
        os.makedirs(folder, exist_ok=True)
        stored_name = f"{uuid.uuid4().hex}.{extension}"
        upload.save(os.path.join(folder, stored_name))
        previous = {"video_url": lesson.video_url}
        lesson.video_path = os.path.join("videos", stored_name)
        lesson.video_url = f"/api/lessons/{lesson.id}/video"
        admin_audit(user, "lesson_video_uploaded", "lessons", "lesson", lesson.id,
                    previous, {"video_url": lesson.video_url})
        db.session.commit()
        return jsonify({"message": "Lesson video uploaded.", "video_url": lesson.video_url})

    @app.get("/api/lessons/<int:lesson_id>/video")
    def serve_lesson_video(lesson_id):
        lesson = db.session.get(Lesson, lesson_id)
        if not lesson:
            return json_error("Lesson not found.", 404)
        if lesson.course.status != "published":
            return json_error("Course not found.", 404)
        user = current_user()
        if not lesson.is_preview:
            if not user or user.account_status != "active":
                return json_error("Authentication required.", 401)
            if user.role == "student":
                enrollment = Enrollment.query.filter_by(
                    user_id=user.id, course_id=lesson.course_id, access_status="active"
                ).first()
                if not enrollment or not enrollment_is_unexpired(enrollment):
                    return json_error("Course enrollment required.", 403)
            elif not has_admin_permission(user, "lessons.manage"):
                return json_error("Forbidden.", 403)
        if not lesson.video_path:
            return json_error("Uploaded video not found.", 404)
        return send_from_directory(
            app.config["UPLOAD_FOLDER"], lesson.video_path,
            as_attachment=False,
        )

    @app.get("/api/admin/activity")
    @roles_required("admin", permission="activity.read")
    def admin_activity(user):
        query = StudentActivity.query.join(User, User.id == StudentActivity.user_id)
        search = str(request.args.get("search", "")).strip()
        if search:
            query = query.filter(db.or_(
                User.full_name.ilike(f"%{search[:100]}%"),
                User.email.ilike(f"%{search[:100]}%"),
            ))
        return jsonify({"activity": [{
            "id": item.id, "student_id": item.user_id, "student_name": item.user.full_name,
            "event": item.event, "details": item.details, "created_at": item.created_at.isoformat(),
        } for item in query.order_by(StudentActivity.created_at.desc()).limit(500).all()]})

    @app.get("/api/admin/certificates")
    @roles_required("admin", permission="certificates.read")
    def admin_certificates(user):
        query = Certificate.query.join(User, User.id == Certificate.user_id)
        search = str(request.args.get("search", "")).strip()
        if search:
            query = query.filter(db.or_(
                User.full_name.ilike(f"%{search[:100]}%"),
                Certificate.certificate_number.ilike(f"%{search[:100]}%"),
            ))
        items = query.order_by(Certificate.issue_date.desc()).limit(500).all()
        return jsonify({"certificates": [{
            "id": item.id, "student_id": item.user_id, "student_name": item.user.full_name,
            "course_id": item.course_id, "course_title": db.session.get(
                Course, item.course_id
            ).title, "certificate_number": item.certificate_number,
            "verification_code": item.verification_code,
            "issue_date": item.issue_date.isoformat() if item.issue_date else None,
            "revoked_at": item.revoked_at.isoformat() if item.revoked_at else None,
            "revoked_reason": item.revoked_reason,
        } for item in items]})

    @app.post("/api/admin/certificates/<int:certificate_id>/revoke")
    @roles_required("admin", permission="certificates.manage")
    def admin_revoke_certificate(user, certificate_id):
        certificate = db.session.get(Certificate, certificate_id)
        if not certificate:
            return json_error("Certificate not found.", 404)
        if certificate.revoked_at:
            return json_error("Certificate is already revoked.", 409)
        reason = str((request.get_json(silent=True) or {}).get("reason", "")).strip()
        if not reason or len(reason) > 500:
            return json_error("A revocation reason is required.")
        certificate.revoked_at = datetime.now(timezone.utc)
        certificate.revoked_reason = reason
        admin_audit(user, "certificate_revoked", "certificates", "certificate", certificate.id,
                    {"revoked_at": None}, {"revoked_at": certificate.revoked_at}, reason)
        create_notification(certificate.user_id, "certificate_revoked", "Certificate revoked",
                            reason, "/dashboard.html")
        db.session.commit()
        return jsonify({"message": "Certificate revoked."})

    @app.post("/api/admin/certificates/<int:certificate_id>/reissue")
    @roles_required("admin", permission="certificates.manage")
    def admin_reissue_certificate(user, certificate_id):
        certificate = db.session.get(Certificate, certificate_id)
        if not certificate:
            return json_error("Certificate not found.", 404)
        completed_count = LessonProgress.query.join(Lesson).filter(
            LessonProgress.user_id == certificate.user_id,
            Lesson.course_id == certificate.course_id,
            LessonProgress.completion_status.is_(True),
        ).count()
        lesson_count = Lesson.query.filter_by(course_id=certificate.course_id).count()
        if not lesson_count or completed_count < lesson_count:
            return json_error("Student has not completed all course lessons.", 409)
        previous = {"certificate_number": certificate.certificate_number,
                    "revoked_at": certificate.revoked_at}
        certificate.certificate_number = f"KC-{uuid.uuid4().hex[:12].upper()}"
        certificate.verification_code = secrets.token_urlsafe(16)
        certificate.issue_date = datetime.now(timezone.utc)
        certificate.revoked_at = None
        certificate.revoked_reason = None
        admin_audit(user, "certificate_reissued", "certificates", "certificate", certificate.id,
                    previous, {"certificate_number": certificate.certificate_number})
        create_notification(certificate.user_id, "certificate_issued", "Certificate reissued",
                            "Your course certificate has been reissued.", "/dashboard.html")
        db.session.commit()
        return jsonify({"message": "Certificate reissued.",
                        "certificate_number": certificate.certificate_number})

    @app.get("/api/certificates/<string:verification_code>")
    def verify_certificate(verification_code):
        certificate = Certificate.query.filter_by(verification_code=verification_code).first()
        if not certificate:
            return json_error("Certificate not found.", 404)
        if certificate.revoked_at:
            return jsonify({"valid": False, "status": "revoked",
                            "certificate_number": certificate.certificate_number})
        student = db.session.get(User, certificate.user_id)
        course = db.session.get(Course, certificate.course_id)
        return jsonify({"valid": True, "status": "valid",
                        "student_name": student.full_name, "course_name": course.title,
                        "certificate_number": certificate.certificate_number,
                        "issue_date": certificate.issue_date.isoformat()
                        if certificate.issue_date else None})

    @app.route("/api/support/tickets", methods=["GET", "POST"])
    @login_required
    def student_support_tickets(user):
        if user.role != "student":
            return json_error("Student account required.", 403)
        if request.method == "GET":
            tickets = SupportTicket.query.filter_by(student_id=user.id).order_by(
                SupportTicket.updated_at.desc()
            ).all()
            return jsonify({"tickets": [support_ticket_json(ticket, user) for ticket in tickets]})
        data = request.get_json(silent=True) or {}
        subject = str(data.get("subject", "")).strip()
        body = str(data.get("message", "")).strip()
        if not subject or len(subject) > 200:
            return json_error("A support subject is required.")
        if not body or len(body) > 4000:
            return json_error("Support message must be between 1 and 4000 characters.")
        ticket = SupportTicket(student_id=user.id, subject=subject, priority="normal")
        db.session.add(ticket)
        db.session.flush()
        message = SupportMessage(ticket_id=ticket.id, sender_id=user.id, body=body)
        db.session.add(message)
        record_student_activity(user, "support_ticket_created", {"ticket_id": ticket.id})
        for administrator in User.query.filter(
                User.role.in_(("admin", "super_admin")), User.account_status == "active").all():
            if has_admin_permission(administrator, "support.read"):
                create_notification(administrator.id, "support_ticket", "New support ticket",
                                    subject, "/admin.html#support")
        db.session.commit()
        socketio.emit("support_new_ticket", support_ticket_json(ticket, user),
                      room="support:admins")
        socketio.emit("support_message", support_message_json(message),
                      room=f"support:ticket:{ticket.id}")
        return jsonify({"message": "Support ticket created.",
                        "ticket": support_ticket_json(ticket, user)}), 201

    @app.route("/api/support/tickets/<int:ticket_id>/messages", methods=["GET", "POST"])
    @login_required
    def support_ticket_messages(user, ticket_id):
        ticket = support_ticket_for_user(ticket_id, user)
        if not ticket:
            return json_error("Support conversation not found.", 404)
        is_admin = user.role in {"admin", "super_admin"}
        if request.method == "GET":
            query = SupportMessage.query.filter_by(ticket_id=ticket.id).order_by(
                SupportMessage.id.asc()
            )
            if not is_admin:
                query = query.filter(SupportMessage.is_internal.is_(False))
            return jsonify({"messages": [support_message_json(item, include_internal=is_admin)
                                         for item in query.limit(500).all()]})
        if is_admin and not has_admin_permission(user, "support.manage"):
            return json_error("Forbidden.", 403)
        data = request.get_json(silent=True) or {}
        body = str(data.get("message", "")).strip()
        if not body or len(body) > 4000:
            return json_error("Message must be between 1 and 4000 characters.")
        if ticket.status == "resolved" and not is_admin:
            ticket.status = "open"
            ticket.resolved_at = None
        is_internal = data.get("is_internal") is True if is_admin else False
        message = SupportMessage(ticket_id=ticket.id, sender_id=user.id,
                                 body=body, is_internal=is_internal)
        ticket.updated_at = datetime.now(timezone.utc)
        db.session.add(message)
        if is_internal:
            recipient_ids = [admin.id for admin in User.query.filter(
                User.role.in_(("admin", "super_admin")), User.account_status == "active"
            ).all() if has_admin_permission(admin, "support.read")]
            room = f"support:ticket:{ticket.id}:internal"
            for recipient_id in recipient_ids:
                if recipient_id != user.id:
                    create_notification(recipient_id, "support_internal_note",
                                        "Internal support note", ticket.subject, "/admin.html#support")
        elif is_admin:
            create_notification(ticket.student_id, "support_reply", "Support replied",
                                ticket.subject, "/dashboard.html#support")
            room = f"support:ticket:{ticket.id}"
        else:
            for administrator in User.query.filter(
                    User.role.in_(("admin", "super_admin")), User.account_status == "active").all():
                if has_admin_permission(administrator, "support.read"):
                    create_notification(administrator.id, "support_message", "New support message",
                                        ticket.subject, "/admin.html#support")
            room = f"support:ticket:{ticket.id}"
        db.session.commit()
        socketio.emit("support_message", support_message_json(message, include_internal=is_admin),
                      room=room)
        if not is_internal:
            socketio.emit("support_ticket_updated", support_ticket_json(ticket, user),
                          room=f"support:ticket:{ticket.id}")
        socketio.emit("support_ticket_updated", support_ticket_json(ticket, user, True),
                      room="support:admins")
        return jsonify({"message": "Support message sent.",
                        "support_message": support_message_json(message, include_internal=is_admin)}), 201

    @app.post("/api/support/tickets/<int:ticket_id>/attachments")
    @login_required
    @limiter.limit("20 per minute")
    def support_upload_attachment(user, ticket_id):
        ticket = support_ticket_for_user(ticket_id, user)
        if not ticket:
            return json_error("Support conversation not found.", 404)
        is_admin = user.role in {"admin", "super_admin"}
        if is_admin and not has_admin_permission(user, "support.manage"):
            return json_error("Forbidden.", 403)
        upload = request.files.get("file")
        if not upload or not upload.filename:
            return json_error("Attachment file is required.")
        if uploaded_file_size(upload) > app.config["MAX_SUPPORT_ATTACHMENT_BYTES"]:
            return json_error("Support attachment exceeds the upload size limit.", 413)
        safe_name = secure_filename(upload.filename)
        extension = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
        if extension not in {"png", "jpg", "jpeg", "pdf", "txt"}:
            return json_error("Attachments must be PNG, JPG, PDF, or TXT files.")
        folder = os.path.join(app.config["UPLOAD_FOLDER"], "support")
        os.makedirs(folder, exist_ok=True)
        stored_name = f"{uuid.uuid4().hex}.{extension}"
        upload.save(os.path.join(folder, stored_name))
        is_internal = is_admin and request.form.get("is_internal") == "true"
        message = SupportMessage(
            ticket_id=ticket.id, sender_id=user.id,
            body=str(request.form.get("message", "")).strip()[:4000],
            attachment_path=os.path.join("support", stored_name),
            attachment_name=safe_name, is_internal=is_internal,
        )
        ticket.updated_at = datetime.now(timezone.utc)
        db.session.add(message)
        if not is_admin and not is_internal:
            for administrator in User.query.filter(
                    User.role.in_(("admin", "super_admin")), User.account_status == "active").all():
                if has_admin_permission(administrator, "support.read"):
                    create_notification(administrator.id, "support_message", "New support attachment",
                                        ticket.subject, "/admin.html#support")
        elif is_admin and not is_internal:
            create_notification(ticket.student_id, "support_reply", "Support replied",
                                ticket.subject, "/dashboard.html#support")
        db.session.commit()
        room = (f"support:ticket:{ticket.id}:internal" if is_internal
                else f"support:ticket:{ticket.id}")
        socketio.emit("support_message", support_message_json(message, include_internal=is_admin),
                      room=room)
        if not is_internal:
            socketio.emit("support_ticket_updated", support_ticket_json(ticket, user),
                          room=f"support:ticket:{ticket.id}")
        socketio.emit("support_ticket_updated", support_ticket_json(ticket, user, True),
                      room="support:admins")
        return jsonify({"message": "Attachment sent.",
                        "support_message": support_message_json(message, include_internal=is_admin)}), 201

    @app.get("/api/support/messages/<int:message_id>/attachment")
    @login_required
    def support_download_attachment(user, message_id):
        message = db.session.get(SupportMessage, message_id)
        if not message or not message.attachment_path:
            return json_error("Attachment not found.", 404)
        ticket = support_ticket_for_user(message.ticket_id, user)
        if not ticket or (message.is_internal and user.role == "student"):
            return json_error("Attachment not found.", 404)
        return send_from_directory(
            app.config["UPLOAD_FOLDER"], message.attachment_path, as_attachment=True,
            download_name=message.attachment_name,
        )

    @app.post("/api/support/tickets/<int:ticket_id>/read")
    @login_required
    def support_mark_read(user, ticket_id):
        ticket = support_ticket_for_user(ticket_id, user)
        if not ticket:
            return json_error("Support conversation not found.", 404)
        query = SupportMessage.query.filter(
            SupportMessage.ticket_id == ticket.id,
            SupportMessage.sender_id != user.id,
            SupportMessage.is_read.is_(False),
        )
        if user.role == "student":
            query = query.filter(SupportMessage.is_internal.is_(False))
        messages = query.all()
        for message in messages:
            message.is_read = True
        db.session.commit()
        return jsonify({"marked_read": len(messages)})

    @app.get("/api/admin/support/tickets")
    @roles_required("admin", permission="support.read")
    def admin_support_tickets(user):
        query = SupportTicket.query.join(User, User.id == SupportTicket.student_id)
        status = str(request.args.get("status", "")).strip()
        priority = str(request.args.get("priority", "")).strip()
        search = str(request.args.get("search", "")).strip()
        unread = request.args.get("unread", "").lower() == "true"
        if status and status in {"open", "in_progress", "resolved"}:
            query = query.filter(SupportTicket.status == status)
        elif status:
            return json_error("Invalid support status filter.")
        if priority and priority in {"low", "normal", "high", "urgent"}:
            query = query.filter(SupportTicket.priority == priority)
        elif priority:
            return json_error("Invalid support priority filter.")
        if search:
            query = query.filter(db.or_(
                User.full_name.ilike(f"%{search[:100]}%"),
                SupportTicket.subject.ilike(f"%{search[:100]}%"),
            ))
        tickets = query.order_by(SupportTicket.updated_at.desc()).limit(500).all()
        payload = [support_ticket_json(ticket, user, include_internal=True) for ticket in tickets]
        if unread:
            payload = [item for item in payload if item["unread_count"]]
        return jsonify({"tickets": payload})

    @app.get("/api/admin/support/assignees")
    @roles_required("admin", permission="support.manage")
    def admin_support_assignees(user):
        admins = User.query.filter(
            User.role.in_(("admin", "super_admin")), User.account_status == "active"
        ).order_by(User.full_name).all()
        return jsonify({"admins": [{
            "id": item.id, "full_name": item.full_name,
        } for item in admins if has_admin_permission(item, "support.read")]})

    @app.patch("/api/admin/support/tickets/<int:ticket_id>")
    @roles_required("admin", permission="support.manage")
    def admin_update_support_ticket(user, ticket_id):
        ticket = db.session.get(SupportTicket, ticket_id)
        if not ticket:
            return json_error("Support ticket not found.", 404)
        data = request.get_json(silent=True) or {}
        previous = {"status": ticket.status, "priority": ticket.priority,
                    "assigned_admin_id": ticket.assigned_admin_id}
        if "status" in data:
            if data["status"] not in {"open", "in_progress", "resolved"}:
                return json_error("Invalid support status.")
            ticket.status = data["status"]
            ticket.resolved_at = datetime.now(timezone.utc) if ticket.status == "resolved" else None
        if "priority" in data:
            if data["priority"] not in {"low", "normal", "high", "urgent"}:
                return json_error("Invalid support priority.")
            ticket.priority = data["priority"]
        if "assigned_admin_id" in data:
            assigned_id = data["assigned_admin_id"]
            if assigned_id is not None:
                assigned = db.session.get(User, assigned_id)
                if not assigned or assigned.role not in {"admin", "super_admin"} or \
                        assigned.account_status != "active" or not has_admin_permission(assigned, "support.read"):
                    return json_error("Assigned user must be an active support administrator.")
            ticket.assigned_admin_id = assigned_id
        ticket.updated_at = datetime.now(timezone.utc)
        admin_audit(user, "support_ticket_updated", "support", "support_ticket", ticket.id,
                    previous, {"status": ticket.status, "priority": ticket.priority,
                               "assigned_admin_id": ticket.assigned_admin_id})
        db.session.commit()
        socketio.emit("support_ticket_updated", support_ticket_json(ticket, user),
                      room=f"support:ticket:{ticket.id}")
        socketio.emit("support_ticket_updated", support_ticket_json(ticket, user, True),
                      room="support:admins")
        socketio.emit("support_ticket_updated", {
            "id": ticket.id, "status": ticket.status, "priority": ticket.priority,
        }, room=f"user:{ticket.student_id}")
        return jsonify({"message": "Support ticket updated."})

    @app.get("/api/notifications")
    @login_required
    def user_notifications(user):
        notifications = Notification.query.filter_by(user_id=user.id).order_by(
            Notification.created_at.desc()
        ).limit(100).all()
        return jsonify({
            "unread_count": sum(1 for item in notifications if item.read_at is None),
            "notifications": [{
                "id": item.id, "kind": item.kind, "title": item.title,
                "body": item.body, "target_url": item.target_url,
                "created_at": item.created_at.isoformat(),
                "read_at": item.read_at.isoformat() if item.read_at else None,
            } for item in notifications],
        })

    @app.post("/api/notifications/<int:notification_id>/read")
    @login_required
    def mark_notification_read(user, notification_id):
        notification = db.session.get(Notification, notification_id)
        if not notification or notification.user_id != user.id:
            return json_error("Notification not found.", 404)
        if notification.read_at is None:
            notification.read_at = datetime.now(timezone.utc)
            db.session.commit()
        return jsonify({"id": notification.id, "read": True})

    @app.get("/api/public/content")
    def public_site_content():
        now = datetime.now(timezone.utc)
        announcements = Announcement.query.filter_by(is_published=True).order_by(
            Announcement.created_at.desc()
        ).all()
        visible = []
        for item in announcements:
            starts = item.starts_at
            ends = item.ends_at
            if starts and starts.tzinfo is None:
                starts = starts.replace(tzinfo=timezone.utc)
            if ends and ends.tzinfo is None:
                ends = ends.replace(tzinfo=timezone.utc)
            if (starts is None or starts <= now) and (ends is None or ends >= now):
                visible.append({"title": item.title, "content": item.content})
        return jsonify({
            "content": {item.key: item.content for item in SiteContent.query.all()},
            "announcements": visible,
        })

    @app.get("/api/admin/content")
    @roles_required("admin", permission="content.manage")
    def admin_site_content(user):
        return jsonify({"content": [{
            "key": item.key, "content": item.content,
            "updated_at": item.updated_at.isoformat(),
            "updated_by": item.updated_by.full_name,
        } for item in SiteContent.query.order_by(SiteContent.key).all()]})

    @app.put("/api/admin/content/<string:key>")
    @roles_required("admin", permission="content.manage")
    def admin_update_site_content(user, key):
        allowed_keys = {
            "home_hero_title": 200, "home_hero_subtitle": 500,
            "home_about_title": 200, "home_about_body": 3000,
            "contact_email": 255, "contact_phone": 50, "footer_text": 500,
            "payment_instructions": 2000,
            "social_twitter": 500, "social_facebook": 500,
            "social_youtube": 500, "social_linkedin": 500,
        }
        if key not in allowed_keys:
            return json_error("This site content field cannot be edited.")
        data = request.get_json(silent=True) or {}
        value = str(data.get("content", "")).strip()
        if not value or len(value) > allowed_keys[key]:
            return json_error(f"Content must be between 1 and {allowed_keys[key]} characters.")
        if "<" in value or ">" in value:
            return json_error("Website content accepts plain text only.")
        if key.startswith("social_") and not value.startswith("https://"):
            return json_error("Social links must use HTTPS.")
        previous = SiteContent.query.filter_by(key=key).first()
        old_value = previous.content if previous else None
        item = previous or SiteContent(key=key, content=value, updated_by_id=user.id)
        item.content = value
        item.updated_by_id = user.id
        db.session.add(item)
        admin_audit(user, "site_content_updated", "content", "site_content", key,
                    {"content": old_value} if old_value is not None else None,
                    {"content": value})
        db.session.commit()
        return jsonify({"message": "Website content updated.", "key": key, "content": value})

    @app.get("/api/announcements")
    def public_announcements():
        response = public_site_content().get_json()
        return jsonify({"announcements": response["announcements"]})

    @app.route("/api/admin/announcements", methods=["GET", "POST"])
    @roles_required("admin", permission="announcements.manage")
    def admin_announcements(user):
        if request.method == "GET":
            return jsonify({"announcements": [{
                "id": item.id, "title": item.title, "content": item.content,
                "is_published": item.is_published,
                "starts_at": item.starts_at.isoformat() if item.starts_at else None,
                "ends_at": item.ends_at.isoformat() if item.ends_at else None,
                "created_at": item.created_at.isoformat(),
            } for item in Announcement.query.order_by(Announcement.created_at.desc()).all()]})
        data = request.get_json(silent=True) or {}
        title = str(data.get("title", "")).strip()
        content = str(data.get("content", "")).strip()
        if not title or len(title) > 200 or not content or len(content) > 5000:
            return json_error("Valid announcement title and content are required.")
        try:
            starts_at = (datetime.fromisoformat(str(data["starts_at"]).replace("Z", "+00:00"))
                         if data.get("starts_at") else None)
            ends_at = (datetime.fromisoformat(str(data["ends_at"]).replace("Z", "+00:00"))
                       if data.get("ends_at") else None)
        except ValueError:
            return json_error("Announcement dates must be valid ISO timestamps.")
        if starts_at and starts_at.tzinfo is None:
            starts_at = starts_at.replace(tzinfo=timezone.utc)
        if ends_at and ends_at.tzinfo is None:
            ends_at = ends_at.replace(tzinfo=timezone.utc)
        if starts_at and ends_at and starts_at > ends_at:
            return json_error("Announcement start must be before its end.")
        announcement = Announcement(
            title=title, content=content, created_by_id=user.id,
            is_published=data.get("is_published") is True,
            starts_at=starts_at, ends_at=ends_at,
        )
        db.session.add(announcement)
        db.session.flush()
        admin_audit(user, "announcement_created", "announcements", "announcement",
                    announcement.id, None, {"title": title, "is_published": announcement.is_published})
        db.session.commit()
        return jsonify({"message": "Announcement created.", "id": announcement.id}), 201

    @app.patch("/api/admin/announcements/<int:announcement_id>")
    @roles_required("admin", permission="announcements.manage")
    def admin_update_announcement(user, announcement_id):
        announcement = db.session.get(Announcement, announcement_id)
        if not announcement:
            return json_error("Announcement not found.", 404)
        data = request.get_json(silent=True) or {}
        previous = {"title": announcement.title, "content": announcement.content,
                    "is_published": announcement.is_published}
        if "title" in data:
            title = str(data["title"]).strip()
            if not title or len(title) > 200:
                return json_error("Valid announcement title is required.")
            announcement.title = title
        if "content" in data:
            content = str(data["content"]).strip()
            if not content or len(content) > 5000:
                return json_error("Announcement content is required.")
            announcement.content = content
        if "is_published" in data:
            if not isinstance(data["is_published"], bool):
                return json_error("is_published must be a boolean.")
            announcement.is_published = data["is_published"]
        try:
            if "starts_at" in data:
                announcement.starts_at = (
                    datetime.fromisoformat(str(data["starts_at"]).replace("Z", "+00:00"))
                    if data["starts_at"] else None
                )
            if "ends_at" in data:
                announcement.ends_at = (
                    datetime.fromisoformat(str(data["ends_at"]).replace("Z", "+00:00"))
                    if data["ends_at"] else None
                )
        except ValueError:
            return json_error("Announcement dates must be valid ISO timestamps.")
        if announcement.starts_at and announcement.starts_at.tzinfo is None:
            announcement.starts_at = announcement.starts_at.replace(tzinfo=timezone.utc)
        if announcement.ends_at and announcement.ends_at.tzinfo is None:
            announcement.ends_at = announcement.ends_at.replace(tzinfo=timezone.utc)
        if (announcement.starts_at and announcement.ends_at and
                announcement.starts_at > announcement.ends_at):
            return json_error("Announcement start must be before its end.")
        admin_audit(user, "announcement_updated", "announcements", "announcement",
                    announcement.id, previous, {"title": announcement.title,
                    "is_published": announcement.is_published})
        db.session.commit()
        return jsonify({"message": "Announcement updated."})

    @app.delete("/api/admin/announcements/<int:announcement_id>")
    @roles_required("admin", permission="announcements.manage")
    def admin_delete_announcement(user, announcement_id):
        announcement = db.session.get(Announcement, announcement_id)
        if not announcement:
            return json_error("Announcement not found.", 404)
        admin_audit(user, "announcement_deleted", "announcements", "announcement",
                    announcement.id, {"title": announcement.title}, None)
        db.session.delete(announcement)
        db.session.commit()
        return jsonify({"message": "Announcement deleted."})

    @app.get("/api/courses/<int:course_id>/reviews")
    def published_course_reviews(course_id):
        course = db.session.get(Course, course_id)
        if not course or course.status != "published":
            return json_error("Course not found.", 404)
        reviews = Review.query.filter_by(course_id=course_id, status="published").order_by(
            Review.created_at.desc()
        ).limit(100).all()
        return jsonify({"reviews": [{
            "student_name": db.session.get(User, item.user_id).full_name,
            "rating": item.rating, "review": item.review,
            "created_at": item.created_at.isoformat(),
        } for item in reviews]})

    @app.get("/api/admin/reviews")
    @roles_required("admin", permission="reviews.manage")
    def admin_reviews(user):
        reviews = Review.query.order_by(Review.created_at.desc()).limit(500).all()
        return jsonify({"reviews": [{
            "id": item.id, "student": user_json(db.session.get(User, item.user_id)),
            "course_id": item.course_id,
            "course_title": db.session.get(Course, item.course_id).title,
            "rating": item.rating, "review": item.review, "status": item.status,
            "created_at": item.created_at.isoformat(),
        } for item in reviews]})

    @app.patch("/api/admin/reviews/<int:review_id>")
    @roles_required("admin", permission="reviews.manage")
    def admin_moderate_review(user, review_id):
        review = db.session.get(Review, review_id)
        if not review:
            return json_error("Review not found.", 404)
        status = (request.get_json(silent=True) or {}).get("status")
        if status not in {"published", "hidden"}:
            return json_error("Review status must be published or hidden.")
        previous = {"status": review.status}
        review.status = status
        admin_audit(user, "review_moderated", "reviews", "review", review.id,
                    previous, {"status": status})
        db.session.commit()
        return jsonify({"message": "Review status updated."})

    @app.get("/api/admin/reports")
    @roles_required("admin", permission="reports.read")
    def admin_reports(user):
        preset = str(request.args.get("range", "30d"))
        end = datetime.now(timezone.utc)
        if preset == "today":
            start = end.replace(hour=0, minute=0, second=0, microsecond=0)
        elif preset == "7d":
            start = end - timedelta(days=7)
        elif preset == "this_month":
            start = end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        elif preset == "custom":
            try:
                start = datetime.fromisoformat(request.args.get("start", "").replace("Z", "+00:00"))
                end = datetime.fromisoformat(request.args.get("end", "").replace("Z", "+00:00"))
            except ValueError:
                return json_error("Custom date range is invalid.")
            if start > end:
                return json_error("Report start date must be before its end date.")
        else:
            start = end - timedelta(days=30)
        registrations = User.query.filter(
            User.role == "student", User.created_at >= start, User.created_at <= end
        ).count()
        payments = Payment.query.filter(
            Payment.created_at >= start, Payment.created_at <= end
        ).all()
        verified = [item for item in payments if item.payment_status in {"captured", "approved"}]
        enrollments = Enrollment.query.filter(
            Enrollment.enrollment_date >= start, Enrollment.enrollment_date <= end
        ).count()
        tickets = SupportTicket.query.filter(
            SupportTicket.created_at >= start, SupportTicket.created_at <= end
        ).count()
        return jsonify({
            "range": {"start": start.isoformat(), "end": end.isoformat()},
            "new_students": registrations,
            "enrollments": enrollments,
            "pending_payments": sum(1 for item in payments if item.payment_status == "pending"),
            "rejected_payments": sum(1 for item in payments if item.payment_status == "rejected"),
            "approved_payments": sum(1 for item in payments
                                     if item.payment_status in {"approved", "captured"}),
            "verified_revenue": sum(float(item.amount) for item in verified),
            "support_tickets": tickets,
            "course_enrollments": [{
                "course_id": course.id, "title": course.title,
                "enrollments": Enrollment.query.filter_by(course_id=course.id).filter(
                    Enrollment.enrollment_date >= start, Enrollment.enrollment_date <= end
                ).count(),
            } for course in Course.query.order_by(Course.title).all()],
        })

    @app.get("/api/admin/reports/export.csv")
    @roles_required("admin", permission="reports.read")
    def export_admin_report(user):
        report_type = str(request.args.get("type", "students"))
        output = io.StringIO()
        writer = csv.writer(output)
        if report_type == "students":
            writer.writerow(["id", "full_name", "email", "status", "registered_at"])
            for student in User.query.filter_by(role="student").order_by(User.created_at.desc()).all():
                writer.writerow([student.id, student.full_name, student.email,
                                 student.account_status,
                                 student.created_at.isoformat() if student.created_at else ""])
        elif report_type == "payments":
            writer.writerow(["id", "student", "course", "amount", "provider", "status", "created_at"])
            for payment in Payment.query.order_by(Payment.created_at.desc()).all():
                writer.writerow([payment.id, payment.user.full_name, payment.course.title,
                                 float(payment.amount), payment.payment_provider,
                                 payment.payment_status,
                                 payment.created_at.isoformat() if payment.created_at else ""])
        elif report_type == "enrollments":
            writer.writerow(["id", "student", "course", "access_status", "payment_status", "date"])
            for item in Enrollment.query.order_by(Enrollment.enrollment_date.desc()).all():
                writer.writerow([item.id, item.user.full_name, item.course.title,
                                 item.access_status, item.payment_status,
                                 item.enrollment_date.isoformat() if item.enrollment_date else ""])
        else:
            return json_error("Export type must be students, payments, or enrollments.")
        return Response(
            output.getvalue(), mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename=kshitij-{report_type}.csv"},
        )

    @app.get("/api/admin/audit-logs")
    @roles_required("admin", super_admin_only=True)
    def admin_audit_logs(user):
        logs = AdminAuditLog.query.order_by(AdminAuditLog.created_at.desc()).limit(1000).all()
        return jsonify({"logs": [{
            "id": item.id, "admin_id": item.admin_id, "admin_name": item.admin.full_name,
            "action": item.action, "module": item.module, "target_type": item.target_type,
            "target_id": item.target_id, "previous_value": item.previous_value,
            "new_value": item.new_value, "reason": item.reason,
            "created_at": item.created_at.isoformat(),
        } for item in logs]})

    @app.get("/api/admin/roles")
    @roles_required("admin", super_admin_only=True)
    def admin_roles(user):
        roles = AdminRole.query.order_by(AdminRole.name).all()
        return jsonify({"roles": [{
            "id": role.id, "name": role.name, "description": role.description,
            "is_system": role.is_system,
            "permissions": [row.permission.code for row in role.permissions],
        } for role in roles],
            "permissions": [{"code": item.code, "description": item.description}
                            for item in AdminPermission.query.order_by(AdminPermission.code).all()]})

    @app.post("/api/admin/roles")
    @roles_required("admin", super_admin_only=True)
    def admin_create_role(user):
        data = request.get_json(silent=True) or {}
        name = str(data.get("name", "")).strip().lower()
        if (not name or len(name) > 80 or not name.isascii() or
                not name.replace("_", "").replace("-", "").isalnum()):
            return json_error("Role name must use letters, numbers, underscores, or hyphens.")
        if name in {"admin", "super_admin", "student"}:
            return json_error("This role name is reserved.")
        if AdminRole.query.filter_by(name=name).first():
            return json_error("Role already exists.", 409)
        permissions = data.get("permissions", [])
        if not isinstance(permissions, list) or not all(isinstance(code, str) for code in permissions):
            return json_error("Permissions must be an array of permission codes.")
        permission_rows = []
        permission_codes = set(permissions)
        permission_codes.add("dashboard.read")
        for code in permission_codes:
            permission = AdminPermission.query.filter_by(code=code).first()
            if not permission:
                return json_error("Unknown permission.")
            permission_rows.append(permission)
        role = AdminRole(name=name, description=str(data.get("description", "")).strip()[:255])
        db.session.add(role)
        db.session.flush()
        for permission in permission_rows:
            db.session.add(AdminRolePermission(role_id=role.id, permission_id=permission.id))
        admin_audit(user, "admin_role_created", "admins", "admin_role", role.id,
                    None, {"name": role.name, "permissions": sorted(permission_codes)})
        db.session.commit()
        return jsonify({"message": "Administrator role created.", "id": role.id}), 201

    @app.put("/api/admin/roles/<int:role_id>")
    @roles_required("admin", super_admin_only=True)
    def admin_update_role(user, role_id):
        role = db.session.get(AdminRole, role_id)
        if not role or role.is_system:
            return json_error("Custom administrator role not found.", 404)
        data = request.get_json(silent=True) or {}
        permissions = data.get("permissions")
        if not isinstance(permissions, list) or not all(isinstance(code, str) for code in permissions):
            return json_error("Permissions must be an array of permission codes.")
        permission_rows = []
        permission_codes = set(permissions)
        permission_codes.add("dashboard.read")
        for code in permission_codes:
            permission = AdminPermission.query.filter_by(code=code).first()
            if not permission:
                return json_error("Unknown permission.")
            permission_rows.append(permission)
        previous = {"permissions": [row.permission.code for row in role.permissions]}
        role.permissions.clear()
        role.permissions.extend([
            AdminRolePermission(permission=permission) for permission in permission_rows
        ])
        if "description" in data:
            role.description = str(data["description"]).strip()[:255]
        admin_audit(user, "admin_role_permissions_updated", "admins", "admin_role",
                    role.id, previous, {"permissions": sorted(permission_codes)})
        db.session.commit()
        return jsonify({"message": "Administrator permissions updated."})

    @app.get("/api/admin/admins")
    @roles_required("admin", super_admin_only=True)
    def list_admin_accounts(user):
        admins = User.query.filter(User.role.in_(("admin", "super_admin"))).order_by(
            User.created_at.desc()
        ).all()
        return jsonify({"admins": [{
            "id": item.id, "full_name": item.full_name, "email": item.email,
            "role": item.role, "admin_role_id": item.admin_role_id,
            "admin_role": item.admin_role.name if item.admin_role else None,
            "account_status": item.account_status,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        } for item in admins]})

    @app.post("/api/admin/admins")
    @roles_required("admin", super_admin_only=True)
    def create_admin_account(user):
        data = request.get_json(silent=True) or {}
        full_name = str(data.get("full_name", "")).strip()
        email = str(data.get("email", "")).strip().lower()
        password = data.get("password") or ""
        role = db.session.get(AdminRole, data.get("admin_role_id"))
        if not full_name or len(full_name) > 120 or not valid_email(email):
            return json_error("Valid administrator name and email are required.")
        if not isinstance(password, str) or len(password) < 12:
            return json_error("Administrator passwords must be at least 12 characters.")
        if not role or role.name == "super_admin":
            return json_error("Select a non-super-admin role.")
        if User.query.filter_by(email=email).first():
            return json_error("An account with this email already exists.", 409)
        administrator = User(
            full_name=full_name, email=email,
            password_hash=generate_password_hash(password, method="scrypt"),
            role="admin", admin_role_id=role.id,
        )
        db.session.add(administrator)
        db.session.flush()
        admin_audit(user, "admin_account_created", "admins", "user", administrator.id,
                    None, {"email": email, "admin_role_id": role.id})
        db.session.commit()
        return jsonify({"message": "Administrator account created.",
                        "admin_id": administrator.id}), 201

    @app.patch("/api/admin/admins/<int:admin_id>")
    @roles_required("admin", super_admin_only=True)
    def update_admin_account(user, admin_id):
        administrator = db.session.get(User, admin_id)
        if not administrator or administrator.role != "admin":
            return json_error("Administrator not found.", 404)
        data = request.get_json(silent=True) or {}
        previous = {"admin_role_id": administrator.admin_role_id,
                    "account_status": administrator.account_status}
        if "admin_role_id" in data:
            role = db.session.get(AdminRole, data["admin_role_id"])
            if not role or role.name == "super_admin":
                return json_error("Select a non-super-admin role.")
            administrator.admin_role_id = role.id
        if "account_status" in data:
            if data["account_status"] not in {"active", "inactive"}:
                return json_error("Account status must be active or inactive.")
            administrator.account_status = data["account_status"]
        admin_audit(user, "admin_account_updated", "admins", "user", administrator.id,
                    previous, {"admin_role_id": administrator.admin_role_id,
                               "account_status": administrator.account_status})
        db.session.commit()
        return jsonify({"message": "Administrator updated."})

    @app.get("/api/admin/settings")
    @roles_required("admin", permission="settings.manage")
    def admin_settings(user):
        return jsonify({
            "storage_backend": "local",
            "upload_folder_configured": bool(app.config.get("UPLOAD_FOLDER")),
            "max_video_upload_bytes": app.config["MAX_VIDEO_UPLOAD_BYTES"],
            "max_note_upload_bytes": app.config["MAX_NOTE_UPLOAD_BYTES"],
            "max_support_attachment_bytes": app.config["MAX_SUPPORT_ATTACHMENT_BYTES"],
            "max_payment_proof_bytes": app.config["MAX_PAYMENT_PROOF_BYTES"],
            "session_lifetime_seconds": int(app.config["PERMANENT_SESSION_LIFETIME"].total_seconds()),
            "razorpay_configured": bool(os.getenv("RAZORPAY_KEY_ID") and
                                        os.getenv("RAZORPAY_KEY_SECRET")),
        })

    @app.get("/api/chat/students")
    @chat_student_required
    def chat_students(user):
        search = str(request.args.get("search", "")).strip()
        if user.role == "student":
            contacts = User.query.filter_by(role="student", account_status="active").filter(
                User.id != user.id
            ).order_by(User.full_name.asc()).all()
            admins = User.query.filter(
                User.role.in_(("admin", "super_admin")),
                User.account_status == "active",
            ).order_by(User.full_name.asc()).all()
            contacts.extend(admin for admin in admins if has_admin_permission(admin, "support.read"))
        else:
            query = User.query.filter_by(role="student", account_status="active")
            contacts = query.order_by(User.full_name.asc()).all()
        if search:
            contacts = [contact for contact in contacts
                        if search[:80].casefold() in contact.full_name.casefold()]
        return jsonify({"students": [
            {"id": contact.id, "full_name": contact.full_name, "profile_image": chat_avatar(contact)}
            for contact in contacts
        ]})

    @app.get("/api/chat/conversations")
    @chat_student_required
    def chat_conversations(user):
        participants = ChatParticipant.query.filter_by(user_id=user.id).all()
        items = [chat_conversation_json(item.conversation, user.id) for item in participants]
        items.sort(key=lambda item: item["last_message_at"], reverse=True)
        return jsonify({"conversations": items})

    @app.post("/api/chat/conversations")
    @chat_student_required
    @limiter.limit("30 per minute")
    def create_chat_conversation(user):
        data = request.get_json(silent=True) or {}
        try:
            target_id = int(data.get("student_id"))
        except (TypeError, ValueError):
            return json_error("A valid student is required.")
        if target_id == user.id:
            return json_error("You cannot start a conversation with yourself.")
        target = db.session.get(User, target_id)
        valid_target = bool(target and target.account_status == "active" and (
            (user.role == "student" and (
                target.role == "student" or
                (target.role in {"admin", "super_admin"} and has_admin_permission(target, "support.read"))
            )) or
            (user.role in {"admin", "super_admin"} and target.role == "student")
        ))
        if not valid_target:
            return json_error("Chat contact not found.", 404)

        low_id, high_id = sorted((user.id, target.id))
        conversation = ChatConversation.query.filter_by(
            user_low_id=low_id, user_high_id=high_id
        ).first()
        created = conversation is None
        if created:
            conversation = ChatConversation(user_low_id=low_id, user_high_id=high_id)
            db.session.add(conversation)
            db.session.flush()
            db.session.add_all([
                ChatParticipant(conversation_id=conversation.id, user_id=low_id),
                ChatParticipant(conversation_id=conversation.id, user_id=high_id),
            ])
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                conversation = ChatConversation.query.filter_by(
                    user_low_id=low_id, user_high_id=high_id
                ).first()
                if not conversation:
                    raise
        if created:
            payload = chat_conversation_json(conversation, target.id)
            socketio.emit("new_conversation", payload, room=f"user:{target.id}")
        return jsonify({"conversation": chat_conversation_json(conversation, user.id)}), 201 if created else 200

    @app.get("/api/chat/conversations/<int:conversation_id>/messages")
    @chat_student_required
    def chat_history(user, conversation_id):
        if not chat_member(conversation_id, user.id):
            return json_error("Conversation not found.", 404)
        before_id = request.args.get("before_id", type=int)
        query = ChatMessage.query.filter_by(conversation_id=conversation_id)
        if before_id:
            query = query.filter(ChatMessage.id < before_id)
        messages = query.order_by(ChatMessage.id.desc()).limit(100).all()
        incoming = [message for message in messages if message.sender_id != user.id and not message.is_read]
        if incoming:
            now = datetime.now(timezone.utc)
            for message in incoming:
                if message.delivered_at is None:
                    message.delivered_at = now
                message.is_read = True
                message.read_at = now
            db.session.commit()
            socketio.emit("message_read", {
                "conversation_id": conversation_id,
                "message_ids": [message.id for message in incoming],
                "read_at": now.isoformat(),
            }, room=f"conversation:{conversation_id}")
        messages.reverse()
        return jsonify({"messages": [chat_message_json(item, user.id) for item in messages]})

    @app.post("/api/chat/conversations/<int:conversation_id>/messages")
    @chat_student_required
    @limiter.limit("60 per minute")
    def create_chat_message(user, conversation_id):
        if not chat_member(conversation_id, user.id):
            return json_error("Conversation not found.", 404)
        data = request.get_json(silent=True) or {}
        text = data.get("message")
        if not isinstance(text, str):
            return json_error("Message must be text.")
        text = text.strip()
        if not text or len(text) > 4000:
            return json_error("Message must be between 1 and 4000 characters.")
        conversation = db.session.get(ChatConversation, conversation_id)
        message = ChatMessage(
            conversation_id=conversation.id,
            sender_id=user.id,
            message=text,
            message_type="text",
        )
        peer = chat_peer(conversation, user.id)
        if chat_user_in_room(peer.id, f"conversation:{conversation.id}"):
            message.delivered_at = datetime.now(timezone.utc)
        conversation.updated_at = datetime.now(timezone.utc)
        db.session.add(message)
        db.session.commit()
        payload = chat_message_json(message, user.id)
        socketio.emit("receive_message", payload, room=f"conversation:{conversation.id}")
        socketio.emit("conversation_updated", chat_conversation_json(conversation, peer.id),
                      room=f"user:{peer.id}")
        return jsonify({"message": payload}), 201

    @app.post("/api/chat/messages/<int:message_id>/read")
    @chat_student_required
    def mark_chat_message_read(user, message_id):
        message = db.session.get(ChatMessage, message_id)
        if not message or not chat_member(message.conversation_id, user.id):
            return json_error("Message not found.", 404)
        if message.sender_id == user.id:
            return json_error("You cannot mark your own message as read.", 400)
        if not message.is_read:
            message.is_read = True
            message.read_at = datetime.now(timezone.utc)
            db.session.commit()
            socketio.emit("message_read", {
                "conversation_id": message.conversation_id,
                "message_ids": [message.id],
                "read_at": message.read_at.isoformat(),
            }, room=f"conversation:{message.conversation_id}")
        return jsonify({"message_id": message.id, "is_read": True,
                        "read_at": message.read_at.isoformat() if message.read_at else None})

    socket_message_times = {}

    @socketio.on("connect")
    def socket_connect(auth=None):
        user = current_user()
        if not user or user.account_status != "active" or user.role not in {
                "student", "admin", "super_admin"}:
            return False
        join_room(f"user:{user.id}")
        socket_users_by_sid[request.sid] = user.id
        if user.role in {"admin", "super_admin"} and has_admin_permission(user, "support.read"):
            join_room("support:admins")
        return True

    @socketio.on("disconnect")
    def socket_disconnect(reason=None):
        socket_users_by_sid.pop(request.sid, None)

    @socketio.on("join_conversation")
    def socket_join_conversation(data):
        user = current_user()
        if not chat_user_allowed(user):
            return {"error": "Authentication required."}
        try:
            conversation_id = int((data or {}).get("conversation_id"))
        except (TypeError, ValueError):
            return {"error": "Invalid conversation."}
        if not chat_member(conversation_id, user.id):
            return {"error": "Conversation not found."}
        join_room(f"conversation:{conversation_id}")
        mark_chat_messages_delivered(conversation_id, user.id)
        return {"joined": True, "conversation_id": conversation_id}

    @socketio.on("leave_conversation")
    def socket_leave_conversation(data):
        user = current_user()
        try:
            conversation_id = int((data or {}).get("conversation_id"))
        except (TypeError, ValueError):
            return {"error": "Invalid conversation."}
        if not user or not chat_member(conversation_id, user.id):
            return {"error": "Conversation not found."}
        leave_room(f"conversation:{conversation_id}")
        return {"left": True}

    @socketio.on("send_message")
    def socket_send_message(data):
        user = current_user()
        if not chat_user_allowed(user):
            return {"error": "Authentication required."}
        try:
            conversation_id = int((data or {}).get("conversation_id"))
        except (TypeError, ValueError):
            return {"error": "Invalid conversation."}
        if not chat_member(conversation_id, user.id):
            return {"error": "Conversation not found."}
        now = datetime.now(timezone.utc)
        recent = [item for item in socket_message_times.get(user.id, []) if item > now - timedelta(seconds=10)]
        if len(recent) >= 20:
            socket_message_times[user.id] = recent
            return {"error": "You are sending messages too quickly."}
        text = (data or {}).get("message")
        if not isinstance(text, str):
            return {"error": "Message must be text."}
        text = text.strip()
        if not text or len(text) > 4000:
            return {"error": "Message must be between 1 and 4000 characters."}
        recent.append(now)
        socket_message_times[user.id] = recent
        conversation = db.session.get(ChatConversation, conversation_id)
        peer = chat_peer(conversation, user.id)
        message = ChatMessage(conversation_id=conversation_id, sender_id=user.id,
                              message=text, message_type="text")
        if chat_user_in_room(peer.id, f"conversation:{conversation_id}"):
            message.delivered_at = now
        conversation.updated_at = now
        db.session.add(message)
        db.session.commit()
        payload = chat_message_json(message, user.id)
        socketio.emit("receive_message", payload, room=f"conversation:{conversation_id}")
        socketio.emit("conversation_updated", chat_conversation_json(conversation, peer.id),
                      room=f"user:{peer.id}")
        return {"message": payload}

    @socketio.on("user_typing")
    def socket_user_typing(data):
        user = current_user()
        try:
            conversation_id = int((data or {}).get("conversation_id"))
        except (TypeError, ValueError):
            return {"error": "Invalid conversation."}
        if not chat_user_allowed(user) or not chat_member(conversation_id, user.id):
            return {"error": "Conversation not found."}
        emit("user_typing", {"conversation_id": conversation_id, "user_id": user.id,
                             "full_name": user.full_name}, room=f"conversation:{conversation_id}", include_self=False)
        return {"sent": True}

    @socketio.on("user_stop_typing")
    def socket_user_stop_typing(data):
        user = current_user()
        try:
            conversation_id = int((data or {}).get("conversation_id"))
        except (TypeError, ValueError):
            return {"error": "Invalid conversation."}
        if not chat_user_allowed(user) or not chat_member(conversation_id, user.id):
            return {"error": "Conversation not found."}
        emit("user_stop_typing", {"conversation_id": conversation_id, "user_id": user.id},
             room=f"conversation:{conversation_id}", include_self=False)
        return {"sent": True}

    support_socket_message_times = {}

    @socketio.on("support_join_ticket")
    def socket_support_join_ticket(data):
        user = current_user()
        if not user or user.account_status != "active":
            return {"error": "Authentication required."}
        try:
            ticket_id = int((data or {}).get("ticket_id"))
        except (TypeError, ValueError):
            return {"error": "Invalid support conversation."}
        ticket = support_ticket_for_user(ticket_id, user)
        if not ticket:
            return {"error": "Support conversation not found."}
        join_room(f"support:ticket:{ticket.id}")
        if user.role in {"admin", "super_admin"} and has_admin_permission(user, "support.read"):
            join_room(f"support:ticket:{ticket.id}:internal")
        return {"joined": True, "ticket_id": ticket.id}

    @socketio.on("support_leave_ticket")
    def socket_support_leave_ticket(data):
        user = current_user()
        if not user or user.account_status != "active":
            return {"error": "Authentication required."}
        try:
            ticket_id = int((data or {}).get("ticket_id"))
        except (TypeError, ValueError):
            return {"error": "Invalid support conversation."}
        ticket = support_ticket_for_user(ticket_id, user)
        if not ticket:
            return {"error": "Support conversation not found."}
        leave_room(f"support:ticket:{ticket.id}")
        leave_room(f"support:ticket:{ticket.id}:internal")
        return {"left": True, "ticket_id": ticket.id}

    @socketio.on("support_send_message")
    def socket_support_send_message(data):
        user = current_user()
        if not user or user.account_status != "active":
            return {"error": "Authentication required."}
        try:
            ticket_id = int((data or {}).get("ticket_id"))
        except (TypeError, ValueError):
            return {"error": "Invalid support conversation."}
        ticket = support_ticket_for_user(ticket_id, user)
        if not ticket:
            return {"error": "Support conversation not found."}
        is_admin = user.role in {"admin", "super_admin"}
        if is_admin and not has_admin_permission(user, "support.manage"):
            return {"error": "Forbidden."}
        now = datetime.now(timezone.utc)
        recent = [item for item in support_socket_message_times.get(user.id, [])
                  if item > now - timedelta(seconds=10)]
        if len(recent) >= 20:
            support_socket_message_times[user.id] = recent
            return {"error": "You are sending messages too quickly."}
        body = (data or {}).get("message")
        if not isinstance(body, str):
            return {"error": "Message must be text."}
        body = body.strip()
        if not body or len(body) > 4000:
            return {"error": "Message must be between 1 and 4000 characters."}
        is_internal = (data or {}).get("is_internal") is True if is_admin else False
        if ticket.status == "resolved" and not is_admin:
            ticket.status = "open"
            ticket.resolved_at = None
        message = SupportMessage(
            ticket_id=ticket.id, sender_id=user.id, body=body, is_internal=is_internal
        )
        ticket.updated_at = now
        recent.append(now)
        support_socket_message_times[user.id] = recent
        db.session.add(message)
        if is_internal:
            for administrator in User.query.filter(
                    User.role.in_(("admin", "super_admin")),
                    User.account_status == "active").all():
                if administrator.id != user.id and has_admin_permission(administrator, "support.read"):
                    create_notification(
                        administrator.id, "support_internal_note", "Internal support note",
                        ticket.subject, "/admin.html#support",
                    )
            target_room = f"support:ticket:{ticket.id}:internal"
        elif is_admin:
            create_notification(ticket.student_id, "support_reply", "Support replied",
                                ticket.subject, "/dashboard.html#support")
            target_room = f"support:ticket:{ticket.id}"
        else:
            for administrator in User.query.filter(
                    User.role.in_(("admin", "super_admin")),
                    User.account_status == "active").all():
                if has_admin_permission(administrator, "support.read"):
                    create_notification(
                        administrator.id, "support_message", "New support message",
                        ticket.subject, "/admin.html#support",
                    )
            target_room = f"support:ticket:{ticket.id}"
        db.session.commit()
        payload = support_message_json(message, include_internal=is_internal)
        socketio.emit("support_message", payload, room=target_room)
        if not is_internal:
            socketio.emit("support_ticket_updated", support_ticket_json(ticket, user),
                          room=f"support:ticket:{ticket.id}")
        socketio.emit("support_ticket_updated", support_ticket_json(ticket, user, True),
                      room="support:admins")
        return {"message": payload}

    @socketio.on("support_mark_read")
    def socket_support_mark_read(data):
        user = current_user()
        if not user or user.account_status != "active":
            return {"error": "Authentication required."}
        try:
            ticket_id = int((data or {}).get("ticket_id"))
        except (TypeError, ValueError):
            return {"error": "Invalid support conversation."}
        ticket = support_ticket_for_user(ticket_id, user)
        if not ticket:
            return {"error": "Support conversation not found."}
        query = SupportMessage.query.filter(
            SupportMessage.ticket_id == ticket.id,
            SupportMessage.sender_id != user.id,
            SupportMessage.is_read.is_(False),
        )
        if user.role == "student":
            query = query.filter(SupportMessage.is_internal.is_(False))
        messages = query.all()
        for message in messages:
            message.is_read = True
        db.session.commit()
        return {"marked_read": len(messages)}

    @socketio.on("support_user_typing")
    def socket_support_user_typing(data):
        user = current_user()
        if not user or user.account_status != "active":
            return {"error": "Authentication required."}
        try:
            ticket_id = int((data or {}).get("ticket_id"))
        except (TypeError, ValueError):
            return {"error": "Invalid support conversation."}
        ticket = support_ticket_for_user(ticket_id, user)
        if not ticket:
            return {"error": "Support conversation not found."}
        if user.role in {"admin", "super_admin"} and not has_admin_permission(user, "support.manage"):
            return {"error": "Forbidden."}
        emit("support_user_typing", {"ticket_id": ticket.id, "user_id": user.id},
             room=f"support:ticket:{ticket.id}", include_self=False)
        return {"sent": True}

    @socketio.on("support_user_stop_typing")
    def socket_support_user_stop_typing(data):
        user = current_user()
        if not user or user.account_status != "active":
            return {"error": "Authentication required."}
        try:
            ticket_id = int((data or {}).get("ticket_id"))
        except (TypeError, ValueError):
            return {"error": "Invalid support conversation."}
        ticket = support_ticket_for_user(ticket_id, user)
        if not ticket:
            return {"error": "Support conversation not found."}
        if user.role in {"admin", "super_admin"} and not has_admin_permission(user, "support.manage"):
            return {"error": "Forbidden."}
        emit("support_user_stop_typing", {"ticket_id": ticket.id, "user_id": user.id},
             room=f"support:ticket:{ticket.id}", include_self=False)
        return {"sent": True}

    html_files = ["index.html", "about.html", "contact.html", "courses.html", "instructor.html",
                  "login.html", "signup.html", "single.html", "team.html", "testimonial.html",
                  "chat-bot.html", "3D.html", "dashboard.html", "admin-login.html", "chat.html"]
    for html_file in html_files:
        route_path = "/" if html_file == "index.html" else f"/{html_file}"

        def make_route(file):
            def route():
                return send_from_directory(app.static_folder, file)
            route.__name__ = f"route_{file.replace('.', '_')}"
            return route
        app.route(route_path, methods=["GET"])(make_route(html_file))

    @app.get("/videos.html")
    def serve_legacy_videos_url():
        return redirect("/courses-videos/videos.html")

    @app.get("/admin")
    def serve_admin_portal():
        user = current_user()
        if user and user.role in {"admin", "super_admin"} and user.account_status == "active":
            return redirect("/admin.html")
        return redirect("/admin-login.html")

    @app.get("/admin.html")
    def serve_admin_dashboard():
        user = current_user()
        if not user:
            return redirect("/admin-login.html")
        if user.role not in {"admin", "super_admin"} or user.account_status != "active":
            return redirect("/")
        return send_from_directory(app.static_folder, "admin.html")

    @app.route("/<path:filename>")
    def serve_static(filename):
        return send_from_directory(app.static_folder, filename)

    @app.cli.command("create-admin")
    def create_admin_command():
        import click
        email = os.getenv("ADMIN_EMAIL")
        password = os.getenv("ADMIN_PASSWORD")
        full_name = os.getenv("ADMIN_NAME", "Kshitij Coder Admin")
        if not email or not password:
            raise click.ClickException("Set ADMIN_EMAIL and ADMIN_PASSWORD environment variables.")
        if len(password) < 12:
            raise click.ClickException("ADMIN_PASSWORD must be at least 12 characters.")
        admin_role = AdminRole.query.filter_by(name="super_admin").first()
        if not admin_role:
            raise click.ClickException("Run database migrations before creating an administrator.")
        existing = User.query.filter_by(email=email.lower()).first()
        if existing:
            existing.role = "super_admin"
            existing.admin_role_id = admin_role.id
            existing.account_status = "active"
            existing.password_hash = generate_password_hash(password, method="scrypt")
            db.session.commit()
            click.echo("Super Admin account updated.")
            return
        db.session.add(User(full_name=full_name, email=email.lower(),
                            password_hash=generate_password_hash(password, method="scrypt"),
                            role="super_admin", admin_role_id=admin_role.id))
        db.session.commit()
        click.echo("Super Admin account created.")

    @app.cli.command("seed-courses")
    def seed_courses_command():
        import click
        if Course.query.count():
            click.echo("Courses already exist.")
            return
        samples = [
            ("HTML Course for Beginners", "Learn HTML fundamentals and build structured web pages.", "img/course-1.jpg", "Web Development", 0),
            ("Front End Development-CSS", "Create responsive layouts and polished interfaces with CSS.", "img/course-2.jpg", "Web Development", 0),
            ("Introduction to JavaScript", "Learn JavaScript fundamentals for interactive websites.", "img/course-3.jpg", "Programming", 0),
        ]
        for title, description, thumbnail, category, price in samples:
            course = Course(title=title, description=description, thumbnail=thumbnail,
                            category=category, price=price, course_duration="2 hours", status="published")
            db.session.add(course)
            db.session.flush()
            db.session.add(Lesson(course_id=course.id, title="Introduction", description="Course introduction",
                                  video_url="", lesson_order=1, duration="10 min", is_preview=True))
        db.session.commit()
        click.echo("Sample courses created.")

    app.extensions["socketio"] = socketio
    return app


app = create_app()

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "5000")),
                 debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
                 allow_unsafe_werkzeug=True)
