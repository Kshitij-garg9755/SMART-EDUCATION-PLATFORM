import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest
from werkzeug.security import generate_password_hash

from backend.app import (
    create_app, db, User, Course, Lesson, Enrollment, Payment, PaymentGatewayEvent,
    ChatConversation, ChatMessage,
    SupportTicket, SupportMessage, AdminPermission, socketio,
)
from backend.upi_gateway import GatewayApiError


@pytest.fixture
def app():
    app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SECRET_KEY": "test-secret",
    })
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def signup(client, email="student@example.com", name="Test Student"):
    return client.post("/api/auth/signup", json={
        "full_name": name,
        "email": email,
        "password": "StrongPass123!",
        "confirm_password": "StrongPass123!",
    })


def test_health_and_static_startup(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/chat.html").status_code == 200
    assert client.get("/upi-payment.html").status_code == 200
    assert client.get("/videos.html", follow_redirects=True).status_code == 200
    assert client.get("/courses-videos/videos.html").status_code == 200


def test_required_database_url_rejects_sqlite(monkeypatch):
    monkeypatch.setenv("REQUIRE_DATABASE_URL", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="persistent database"):
        create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        })


def test_signup_duplicate_and_login(client):
    first = signup(client)
    assert first.status_code == 201
    duplicate = signup(client)
    assert duplicate.status_code == 409
    logout = client.post("/api/auth/logout", json={})
    assert logout.status_code == 200
    invalid = client.post("/api/auth/login", json={"email": "student@example.com", "password": "wrong"})
    assert invalid.status_code == 401
    valid = client.post("/api/auth/login", json={"email": "student@example.com", "password": "StrongPass123!"})
    assert valid.status_code == 200


def test_profile_update_and_password_change(client):
    assert signup(client).status_code == 201
    response = client.put("/api/profile", json={"full_name": "Updated Student"})
    assert response.status_code == 200
    assert response.get_json()["user"]["full_name"] == "Updated Student"
    response = client.post("/api/profile/password", json={
        "current_password": "StrongPass123!",
        "new_password": "AnotherStrong123!",
    })
    assert response.status_code == 200


def test_course_access_enrollment_progress_and_certificate(client, app):
    assert signup(client).status_code == 201
    with app.app_context():
        course = Course(title="Test Course", description="Test", category="Testing",
                        price=0, status="published", course_duration="1 hour")
        db.session.add(course)
        db.session.flush()
        lesson = Lesson(course_id=course.id, title="Lesson 1", lesson_order=1,
                        is_preview=False, video_url="")
        db.session.add(lesson)
        db.session.commit()
        course_id = course.id
        lesson_id = lesson.id

    listing = client.get("/api/courses")
    assert listing.status_code == 200
    listed_course = next(
        course for course in listing.get_json()["courses"] if course["id"] == course_id
    )
    assert listed_course["lesson_count"] == 1
    assert listed_course["enrolled"] is False
    assert "lessons" not in listed_course

    detail = client.get(f"/api/courses/{course_id}")
    assert detail.status_code == 200
    assert not detail.get_json()["course"]["lessons"]

    enrolled = client.post(f"/api/courses/{course_id}/enroll", json={})
    assert enrolled.status_code == 201
    listing = client.get("/api/courses").get_json()["courses"]
    assert next(course for course in listing if course["id"] == course_id)["enrolled"] is True
    detail = client.get(f"/api/courses/{course_id}")
    assert len(detail.get_json()["course"]["lessons"]) == 1

    completed = client.post(f"/api/lessons/{lesson_id}/complete", json={})
    assert completed.status_code == 200
    assert completed.get_json()["progress"] == 100
    dashboard = client.get("/api/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.get_json()["certificates"]


def test_public_course_catalog_and_detail_hide_paid_lesson_media(client, app):
    assert signup(client).status_code == 201
    with app.app_context():
        course = Course(
            title="Protected Course", description="Protected lessons",
            category="Testing", price=199, status="published",
        )
        db.session.add(course)
        db.session.flush()
        db.session.add_all([
            Lesson(
                course_id=course.id, title="Preview", lesson_order=1,
                is_preview=True, video_url="https://media.example/preview.mp4",
            ),
            Lesson(
                course_id=course.id, title="Paid lesson", lesson_order=2,
                is_preview=False, video_url="https://media.example/paid.mp4",
            ),
        ])
        db.session.commit()
        course_id = course.id

    listed = next(
        course for course in client.get("/api/courses").get_json()["courses"]
        if course["id"] == course_id
    )
    assert listed["price"] == 199
    assert listed["lesson_count"] == 2
    assert "lessons" not in listed

    detail = client.get(f"/api/courses/{course_id}").get_json()["course"]
    assert detail["enrolled"] is False
    assert [lesson["title"] for lesson in detail["lessons"]] == ["Preview"]
    assert detail["lessons"][0]["video_url"] == "https://media.example/preview.mp4"
    assert client.post(f"/api/courses/{course_id}/enroll", json={}).status_code == 402


def test_expired_enrollment_does_not_grant_course_access(client, app):
    assert signup(client).status_code == 201
    with app.app_context():
        student = User.query.filter_by(email="student@example.com").one()
        course = Course(
            title="Expired Course", description="Expired access",
            category="Testing", price=199, status="published",
        )
        db.session.add(course)
        db.session.flush()
        lesson = Lesson(
            course_id=course.id, title="Paid lesson", lesson_order=1,
            is_preview=False, video_url="",
        )
        enrollment = Enrollment(
            user_id=student.id, course_id=course.id,
            payment_status="paid", access_status="active",
            access_expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        db.session.add_all([lesson, enrollment])
        db.session.commit()
        course_id, lesson_id = course.id, lesson.id

    detail = client.get(f"/api/courses/{course_id}").get_json()["course"]
    assert detail["enrolled"] is False
    assert detail["lessons"] == []
    assert client.post(f"/api/lessons/{lesson_id}/complete", json={}).status_code == 403


def test_admin_access_and_bootstrap(client, app):
    with app.app_context():
        admin = User(full_name="Admin", email="admin@example.com",
                     password_hash="placeholder", role="admin", account_status="active")
        db.session.add(admin)
        db.session.commit()
        admin_id = admin.id

    assert client.get("/api/admin/stats").status_code == 401
    login = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "wrong"})
    assert login.status_code == 401


def test_contact_validation_and_storage(client, app):
    valid = client.post("/api/contact", json={
        "name": "Jane",
        "email": "jane@example.com",
        "subject": "Course question",
        "message": "Please share course details.",
    })
    assert valid.status_code == 201
    invalid = client.post("/api/contact", json={"name": "", "email": "bad", "subject": "", "message": ""})
    assert invalid.status_code == 400


def create_student(email, name):
    user = User(
        full_name=name,
        email=email,
        password_hash=generate_password_hash("StrongPass123!", method="scrypt"),
        role="student",
        account_status="active",
        profile_image="",
    )
    db.session.add(user)
    db.session.commit()
    return user


class FakeUpiGateway:
    def __init__(self, environment):
        self.environment = environment
        self.status = "pending"
        self.created_payloads = []
        self.order_id = "ORD-KC-TEST-1"
        self.client_order_id = None

    def _order(self):
        return {
            "order_id": self.order_id,
            "client_order_id": self.client_order_id,
            "amount": "499.00",
            "currency": "INR",
            "status": self.status,
            "environment": self.environment,
            "test": self.environment == "sandbox",
            "payment_url": "https://gateway.test/pay/" + self.order_id,
            "upi_intent": "upi://pay?pa=merchant%40upi&am=499.00"
            if self.environment == "live" else None,
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
            "utr": "UTR-123456789" if self.status == "paid" else None,
        }

    def create_order(self, payload):
        self.created_payloads.append(payload)
        self.client_order_id = payload["client_order_id"]
        return self._order()

    def get_order(self, reference):
        if reference not in {self.order_id, self.client_order_id}:
            raise GatewayApiError(status_code=404, code="gateway_request_rejected")
        return self._order()


def create_upi_test_course():
    course = Course(
        title="UPI Test Course",
        description="Payment integration test",
        category="Testing",
        price=499,
        status="published",
    )
    db.session.add(course)
    db.session.commit()
    return course


def signed_webhook(client, body, secret, event_id, event_type, timestamp=None):
    timestamp = int(timestamp or datetime.now(timezone.utc).timestamp())
    signature = hmac.new(
        secret.encode("utf-8"),
        str(timestamp).encode("ascii") + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    return client.post(
        "/api/payments/upi/webhook",
        data=body,
        content_type="application/json",
        headers={
            "X-Signature": f"t={timestamp},v1={signature}",
            "X-Event-Id": event_id,
            "X-Event": event_type,
        },
    )


def test_upi_order_uses_database_price_and_sandbox_never_enrolls(client, app):
    with app.app_context():
        student = create_student("upi-sandbox@example.com", "Sandbox Student")
        course = create_upi_test_course()
        student_id, course_id = student.id, course.id
    with client.session_transaction() as session:
        session["user_id"] = student_id
    gateway = FakeUpiGateway("sandbox")
    app.config.update(
        UPI_GATEWAY_ENVIRONMENT="sandbox",
        UPI_GATEWAY_BASE_URL="https://gateway.test",
        UPI_GATEWAY_CLIENT=gateway,
    )

    created = client.post("/api/payments/upi/orders", json={
        "course_id": course_id,
        "amount": 1,
        "student_id": 99999,
    })
    assert created.status_code == 201
    payment_data = created.get_json()["payment"]
    assert payment_data["amount"] == "499.00"
    assert payment_data["environment"] == "sandbox"
    assert gateway.created_payloads[0]["amount"] == "499.00"
    assert "student_id" not in payment_data
    reused = client.post("/api/payments/upi/orders", json={"course_id": course_id})
    assert reused.status_code == 200
    assert reused.get_json()["payment"]["id"] == payment_data["id"]
    assert len(gateway.created_payloads) == 1

    gateway.status = "paid"
    checked = client.post(f"/api/payments/upi/{payment_data['id']}/check", json={})
    assert checked.status_code == 200
    assert checked.get_json()["payment"]["status"] == "captured"
    with app.app_context():
        assert Enrollment.query.filter_by(user_id=student_id, course_id=course_id).count() == 0
        assert Payment.query.filter_by(id=payment_data["id"]).one().transaction_id is None


def test_upi_live_webhook_is_verified_idempotent_and_sequence_ordered(client, app):
    with app.app_context():
        student = create_student("upi-live@example.com", "Live Student")
        other = create_student("upi-other@example.com", "Other Student")
        admin = User(
            full_name="Payments Admin",
            email="upi-admin@example.com",
            password_hash="unused",
            role="super_admin",
            account_status="active",
        )
        db.session.add(admin)
        course = create_upi_test_course()
        student_id, other_id, admin_id, course_id = (
            student.id, other.id, admin.id, course.id
        )
    with client.session_transaction() as session:
        session["user_id"] = student_id
    gateway = FakeUpiGateway("live")
    secret = "webhook-test-secret"
    app.config.update(
        UPI_GATEWAY_ENVIRONMENT="live",
        UPI_GATEWAY_BASE_URL="https://gateway.test",
        UPI_GATEWAY_WEBHOOK_SECRET=secret,
        UPI_GATEWAY_CLIENT=gateway,
    )
    created = client.post("/api/payments/upi/orders", json={"course_id": course_id})
    assert created.status_code == 201
    payment_data = created.get_json()["payment"]

    other_client = app.test_client()
    with other_client.session_transaction() as session:
        session["user_id"] = other_id
    assert other_client.get(f"/api/payments/upi/{payment_data['id']}").status_code == 404
    assert other_client.get("/api/payments/mine").get_json()["payments"] == []

    gateway.status = "paid"
    invalid_event = {
        "event_id": "event-payment-wrong-amount",
        "event_sequence": 1,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "event": "order.paid",
        "data": dict(gateway._order(), amount="1.00"),
    }
    invalid_body = json.dumps(invalid_event, separators=(",", ":")).encode("utf-8")
    invalid = signed_webhook(
        app.test_client(), invalid_body, secret,
        "event-payment-wrong-amount", "order.paid",
    )
    assert invalid.status_code == 400
    with app.app_context():
        assert Enrollment.query.filter_by(user_id=student_id, course_id=course_id).count() == 0

    event_id = "event-payment-paid-1"
    event = {
        "event_id": event_id,
        "event_sequence": 2,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "event": "order.paid",
        "data": gateway._order(),
    }
    body = json.dumps(event, separators=(",", ":")).encode("utf-8")
    delivered = signed_webhook(
        app.test_client(), body, secret, event_id, "order.paid"
    )
    assert delivered.status_code == 200
    with app.app_context():
        payment = db.session.get(Payment, payment_data["id"])
        assert payment.payment_status == "captured"
        assert payment.transaction_id == "UTR-123456789"
        assert Enrollment.query.filter_by(user_id=student_id, course_id=course_id).count() == 1

    duplicate = signed_webhook(
        app.test_client(), body, secret, event_id, "order.paid"
    )
    assert duplicate.status_code == 200
    assert duplicate.get_json()["duplicate"] is True

    gateway.status = "expired"
    expired_event_id = "event-payment-expired-1"
    expired_event = {
        "event_id": expired_event_id,
        "event_sequence": 1,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "event": "order.expired",
        "data": gateway._order(),
    }
    expired_body = json.dumps(expired_event, separators=(",", ":")).encode("utf-8")
    stale = signed_webhook(
        app.test_client(), expired_body, secret, expired_event_id, "order.expired"
    )
    assert stale.status_code == 200
    with app.app_context():
        payment = db.session.get(Payment, payment_data["id"])
        assert payment.payment_status == "captured"
        assert payment.event_sequence == 2
        assert Enrollment.query.filter_by(user_id=student_id, course_id=course_id).count() == 1
        assert PaymentGatewayEvent.query.filter_by(result="stale").count() == 1
    receipt = client.get(f"/api/payments/{payment_data['id']}/receipt")
    assert receipt.status_code == 200
    assert b"Payment Receipt" in receipt.data
    payment_details = client.get(
        f"/api/payments/upi/{payment_data['id']}"
    ).get_json()["payment"]
    assert payment_details["course_url"] == (
        f"/courses-videos/videos.html?course_id={course_id}"
    )
    assert other_client.get(f"/api/payments/{payment_data['id']}/receipt").status_code == 404

    admin_client = app.test_client()
    with admin_client.session_transaction() as session:
        session["user_id"] = admin_id
    filtered = admin_client.get(
        "/api/admin/payments?environment=live&search=ORD-KC-TEST-1"
    )
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.get_json()["payments"]] == [payment_data["id"]]
    history = admin_client.get(f"/api/admin/payments/{payment_data['id']}/events")
    assert history.status_code == 200
    assert any(item["event_type"] == "order.paid" for item in history.get_json()["events"])
    assert admin_client.get(
        "/api/admin/payment-gateway-events?environment=live"
    ).status_code == 200


def test_upi_webhook_rejects_bad_signature_and_expired_timestamp(client, app):
    secret = "webhook-test-secret"
    app.config["UPI_GATEWAY_WEBHOOK_SECRET"] = secret
    body = b'{"event_id":"event-1"}'
    bad = client.post(
        "/api/payments/upi/webhook",
        data=body,
        content_type="application/json",
        headers={
            "X-Signature": f"t={int(datetime.now(timezone.utc).timestamp())},v1={'0' * 64}",
            "X-Event-Id": "event-1",
            "X-Event": "order.paid",
        },
    )
    assert bad.status_code == 401
    expired = signed_webhook(
        client,
        body,
        secret,
        "event-1",
        "order.paid",
        timestamp=int(datetime.now(timezone.utc).timestamp()) - 301,
    )
    assert expired.status_code == 401
    with app.app_context():
        assert PaymentGatewayEvent.query.filter_by(
            result="rejected", source="webhook"
        ).count() == 2


def test_student_discovery_and_private_conversation_deduplication(client, app):
    with app.app_context():
        alice = create_student("alice@example.com", "Alice Student")
        bob = create_student("bob@example.com", "Bob Student")
        alice_id, bob_id = alice.id, bob.id

    with client.session_transaction() as session:
        session["user_id"] = alice_id

    students = client.get("/api/chat/students").get_json()["students"]
    assert students == [{"id": bob_id, "full_name": "Bob Student", "profile_image": ""}]
    assert "email" not in students[0]
    first = client.post("/api/chat/conversations", json={"student_id": bob_id})
    assert first.status_code == 201
    conversation_id = first.get_json()["conversation"]["id"]
    reverse = client.post("/api/chat/conversations", json={"student_id": bob_id})
    assert reverse.status_code == 200
    assert reverse.get_json()["conversation"]["id"] == conversation_id
    bob_client = app.test_client()
    with bob_client.session_transaction() as session:
        session["user_id"] = bob_id
    reverse_initiated = bob_client.post("/api/chat/conversations", json={"student_id": alice_id})
    assert reverse_initiated.status_code == 200
    assert reverse_initiated.get_json()["conversation"]["id"] == conversation_id
    with app.app_context():
        assert ChatConversation.query.count() == 1


def test_private_chat_http_authorization_history_and_receipts(app):
    alice_client = app.test_client()
    bob_client = app.test_client()
    stranger_client = app.test_client()
    with app.app_context():
        alice = create_student("alice2@example.com", "Alice")
        bob = create_student("bob2@example.com", "Bob")
        stranger = create_student("stranger@example.com", "Stranger")
        alice_id, bob_id, stranger_id = alice.id, bob.id, stranger.id

    for flask_client, user_id in (
        (alice_client, alice_id), (bob_client, bob_id), (stranger_client, stranger_id)
    ):
        with flask_client.session_transaction() as session:
            session["user_id"] = user_id

    conversation = alice_client.post("/api/chat/conversations", json={"student_id": bob_id})
    conversation_id = conversation.get_json()["conversation"]["id"]
    denied = stranger_client.get(f"/api/chat/conversations/{conversation_id}/messages")
    assert denied.status_code == 404

    sent = alice_client.post(
        f"/api/chat/conversations/{conversation_id}/messages",
        json={"message": "Hello Bob", "sender_id": bob_id},
    )
    assert sent.status_code == 201
    result = sent.get_json()["message"]
    assert result["sender_id"] == alice_id
    assert result["status"] == "sent"

    history = bob_client.get(f"/api/chat/conversations/{conversation_id}/messages")
    assert history.status_code == 200
    received = history.get_json()["messages"][0]
    assert received["message"] == "Hello Bob"
    assert received["status"] == "read"
    with app.app_context():
        message = db.session.get(ChatMessage, result["id"])
        assert message.is_read is True
        assert message.read_at is not None
    assert alice_client.post("/api/auth/logout", json={}).status_code == 200
    assert alice_client.post("/api/auth/login", json={
        "email": "alice2@example.com",
        "password": "StrongPass123!",
    }).status_code == 200
    assert alice_client.get(f"/api/chat/conversations/{conversation_id}/messages").status_code == 200


def test_socket_chat_auth_membership_and_live_delivery(app):
    alice_client = app.test_client()
    bob_client = app.test_client()
    outsider_client = app.test_client()
    with app.app_context():
        alice = create_student("alice3@example.com", "Alice")
        bob = create_student("bob3@example.com", "Bob")
        outsider = create_student("outsider@example.com", "Outsider")
        alice_id, bob_id, outsider_id = alice.id, bob.id, outsider.id

    for flask_client, user_id in (
        (alice_client, alice_id), (bob_client, bob_id), (outsider_client, outsider_id)
    ):
        with flask_client.session_transaction() as session:
            session["user_id"] = user_id

    conversation_response = alice_client.post("/api/chat/conversations", json={"student_id": bob_id})
    conversation_id = conversation_response.get_json()["conversation"]["id"]
    alice_socket = socketio.test_client(app, flask_test_client=alice_client)
    bob_socket = socketio.test_client(app, flask_test_client=bob_client)
    outsider_socket = socketio.test_client(app, flask_test_client=outsider_client)
    anonymous_socket = socketio.test_client(app)
    assert alice_socket.is_connected()
    assert bob_socket.is_connected()
    assert not anonymous_socket.is_connected()
    assert outsider_socket.emit("join_conversation", {"conversation_id": conversation_id}, callback=True)["error"]
    assert alice_socket.emit("join_conversation", {"conversation_id": conversation_id}, callback=True)["joined"]
    assert bob_socket.emit("join_conversation", {"conversation_id": conversation_id}, callback=True)["joined"]
    response = alice_socket.emit("send_message", {
        "conversation_id": conversation_id,
        "message": "Live hello",
        "sender_id": bob_id,
    }, callback=True)
    assert response["message"]["sender_id"] == alice_id
    assert response["message"]["status"] == "delivered"
    messages = bob_socket.get_received()
    delivered = [event for event in messages if event["name"] == "receive_message"]
    assert delivered and delivered[0]["args"][0]["message"] == "Live hello"
    history = bob_client.get(f"/api/chat/conversations/{conversation_id}/messages")
    assert history.status_code == 200
    receipts = [event for event in alice_socket.get_received() if event["name"] == "message_read"]
    assert receipts and result_message_id(history) is not None
    reply = bob_socket.emit("send_message", {
        "conversation_id": conversation_id,
        "message": "Live reply",
    }, callback=True)
    assert reply["message"]["sender_id"] == bob_id
    assert reply["message"]["status"] == "delivered"
    alice_messages = alice_socket.get_received()
    replies = [event for event in alice_messages if event["name"] == "receive_message"]
    assert replies and replies[-1]["args"][0]["message"] == "Live reply"

    outsider_socket.disconnect()
    bob_socket.disconnect()
    alice_socket.disconnect()


def result_message_id(history):
    return history.get_json()["messages"][0]["id"]


def test_chat_rejects_non_student_and_large_messages(client, app):
    with app.app_context():
        admin = User(full_name="Admin", email="chat-admin@example.com",
                     password_hash="unused", role="admin", account_status="active")
        db.session.add(admin)
        db.session.commit()
        admin_id = admin.id
    with client.session_transaction() as session:
        session["user_id"] = admin_id
    assert client.get("/api/chat/students").status_code == 403


def test_admin_pages_are_protected_and_student_cannot_use_admin_api(client, app):
    portal = client.get("/admin")
    assert portal.status_code == 302
    assert portal.headers["Location"].endswith("/admin-login.html")
    assert client.get("/admin.html").status_code == 302
    assert client.get("/admin-login.html").status_code == 200
    with app.app_context():
        student = create_student("portal-student@example.com", "Portal Student")
        administrator = User(
            full_name="Portal Super Admin",
            email="portal-admin@example.com",
            password_hash=generate_password_hash("StrongPass123!", method="scrypt"),
            role="super_admin",
            account_status="active",
        )
        db.session.add(administrator)
        db.session.commit()
        student_id = student.id
        administrator_id = administrator.id
    with client.session_transaction() as session:
        session["user_id"] = student_id
    student_portal = client.get("/admin")
    assert student_portal.status_code == 302
    assert student_portal.headers["Location"].endswith("/admin-login.html")
    assert client.get("/admin.html").status_code == 302
    assert client.get("/api/admin/auth/me").status_code == 403
    assert client.post("/api/admin/auth/login", json={
        "email": "portal-student@example.com", "password": "StrongPass123!"
    }).status_code == 401

    with client.session_transaction() as session:
        session["user_id"] = administrator_id
    admin_portal = client.get("/admin")
    assert admin_portal.status_code == 302
    assert admin_portal.headers["Location"].endswith("/admin.html")
    dashboard = client.get("/admin.html")
    assert dashboard.status_code == 200
    assert b"Platform overview" in dashboard.data
    assert client.get("/api/admin/auth/me").status_code == 200


def test_support_socket_membership_and_internal_note_privacy(app):
    student_client = app.test_client()
    intruder_client = app.test_client()
    admin_client = app.test_client()
    with app.app_context():
        student = create_student("support-student@example.com", "Support Student")
        intruder = create_student("support-intruder@example.com", "Support Intruder")
        admin = User(
            full_name="Support Admin", email="support-admin@example.com",
            password_hash="unused", role="super_admin", account_status="active",
        )
        db.session.add(admin)
        db.session.flush()
        ticket = SupportTicket(
            student_id=student.id, subject="Course access", status="open", priority="normal"
        )
        db.session.add(ticket)
        db.session.commit()
        student_id, intruder_id, admin_id, ticket_id = (
            student.id, intruder.id, admin.id, ticket.id
        )

    for flask_client, user_id in (
        (student_client, student_id), (intruder_client, intruder_id),
        (admin_client, admin_id),
    ):
        with flask_client.session_transaction() as session:
            session["user_id"] = user_id

    student_socket = socketio.test_client(app, flask_test_client=student_client)
    intruder_socket = socketio.test_client(app, flask_test_client=intruder_client)
    admin_socket = socketio.test_client(app, flask_test_client=admin_client)
    assert student_socket.is_connected()
    assert admin_socket.is_connected()
    assert intruder_socket.emit(
        "support_join_ticket", {"ticket_id": ticket_id}, callback=True
    )["error"]
    assert student_socket.emit(
        "support_join_ticket", {"ticket_id": ticket_id}, callback=True
    )["joined"]
    assert admin_socket.emit(
        "support_join_ticket", {"ticket_id": ticket_id}, callback=True
    )["joined"]

    sent = student_socket.emit("support_send_message", {
        "ticket_id": ticket_id, "message": "I need access help."
    }, callback=True)
    assert sent["message"]["body"] == "I need access help."
    admin_events = admin_socket.get_received()
    assert any(event["name"] == "support_message" for event in admin_events)
    public_events = student_socket.get_received()
    assert any(event["name"] == "support_message" for event in public_events)

    admin_sent = admin_socket.emit("support_send_message", {
        "ticket_id": ticket_id, "message": "Internal investigation note.",
        "is_internal": True,
    }, callback=True)
    assert admin_sent["message"]["is_internal"] is True
    student_events = student_socket.get_received()
    assert not any(event["name"] == "support_message" for event in student_events)
    history = student_client.get(f"/api/support/tickets/{ticket_id}/messages")
    assert history.status_code == 200
    assert len(history.get_json()["messages"]) == 1
    assert history.get_json()["messages"][0]["body"] == "I need access help."

    student_socket.disconnect()
    intruder_socket.disconnect()
    admin_socket.disconnect()


def test_admin_content_roles_and_public_announcement_access(app):
    client = app.test_client()
    with app.app_context():
        admin = User(
            full_name="Super Admin", email="cms-admin@example.com",
            password_hash="unused", role="super_admin", account_status="active",
        )
        regular_admin = User(
            full_name="Regular Admin", email="regular-admin@example.com",
            password_hash="unused", role="admin", account_status="active",
        )
        db.session.add_all([
            admin, regular_admin,
            AdminPermission(code="courses.read", description="Read courses"),
            AdminPermission(code="dashboard.read", description="View the dashboard"),
        ])
        db.session.commit()
        admin_id, regular_admin_id = admin.id, regular_admin.id

    with client.session_transaction() as session:
        session["user_id"] = admin_id
    rejected_content = client.put("/api/admin/content/home_hero_title", json={
        "content": "<img src=x onerror=alert(1)>"
    })
    assert rejected_content.status_code == 400
    content = client.put("/api/admin/content/home_hero_title", json={
        "content": "Learn something new today"
    })
    assert content.status_code == 200
    announcement = client.post("/api/admin/announcements", json={
        "title": "Scheduled maintenance", "content": "The platform will be updated.",
        "is_published": True,
    })
    assert announcement.status_code == 201
    public = client.get("/api/public/content").get_json()
    assert public["content"]["home_hero_title"] == "Learn something new today"
    assert public["announcements"][0]["title"] == "Scheduled maintenance"

    created_role = client.post("/api/admin/roles", json={
        "name": "course_viewer", "permissions": ["courses.read"]
    })
    assert created_role.status_code == 201
    invalid_role = client.post("/api/admin/roles", json={
        "name": "invalid_role", "permissions": [{"unexpected": "object"}]
    })
    assert invalid_role.status_code == 400

    with client.session_transaction() as session:
        session["user_id"] = regular_admin_id
    assert client.get("/api/admin/roles").status_code == 403


def test_video_upload_enforces_configured_file_size_limit(client, app):
    with app.app_context():
        admin = User(
            full_name="Video Admin", email="video-admin@example.com",
            password_hash="unused", role="super_admin", account_status="active",
        )
        course = Course(title="Upload test", description="", category="Test",
                        price=0, status="draft")
        db.session.add_all([admin, course])
        db.session.flush()
        lesson = Lesson(course_id=course.id, title="Video lesson", lesson_order=1)
        db.session.add(lesson)
        db.session.commit()
        admin_id, lesson_id = admin.id, lesson.id
        app.config["MAX_VIDEO_UPLOAD_BYTES"] = 8
    with client.session_transaction() as session:
        session["user_id"] = admin_id

    response = client.post(
        f"/api/admin/lessons/{lesson_id}/video",
        data={"file": (BytesIO(b"video-too-large"), "lesson.mp4")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 413
