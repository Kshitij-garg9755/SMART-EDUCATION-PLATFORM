# Kshitij Coder

Kshitij Coder is a responsive Flask and HTML/CSS/JavaScript e-learning platform.

## Authoritative frontend

`E-Learning-Website-HTML-CSS-main/` is the source frontend. `www/` is synchronized from it for Netlify and Capacitor and must not be edited independently.

For the live Netlify + Render + Neon setup, follow [NETLIFY.md](NETLIFY.md). It covers the
frontend proxy, Flask/Socket.IO service, persistent PostgreSQL, free-tier file-storage
limitations, and the private environment variables required to launch.

```powershell
Copy-Item -Path "E-Learning-Website-HTML-CSS-main\*" -Destination "www" -Recurse -Force
npx cap sync android
```

## Local development

```powershell
python -m pip install -r requirements.txt
python -m flask --app backend.app db upgrade
python -m flask --app backend.app seed-courses
$env:FLASK_DEBUG="true"
python -m backend.app
```

Open `http://localhost:5000`.

Successful student login and signup return to the website homepage; signup creates the persistent student profile. Signed-in students can open **KHITIJ CHAT** from the floating button at the bottom-right of the site. The profile icon opens the student dashboard. Chat uses Flask-SocketIO and shares the existing signed-in student session.

## Create an admin

Set environment variables, then run:

```powershell
$env:ADMIN_NAME="Kshitij Coder Admin"
$env:ADMIN_EMAIL="admin@example.com"
$env:ADMIN_PASSWORD="use-a-long-random-password"
python -m flask --app backend.app create-admin
```

Never use placeholder or committed credentials.

The command creates or promotes the configured account to **Super Admin**. Sign in at
`http://localhost:5000/admin-login.html`; `/admin.html` is protected and redirects visitors
without an active administrator session. Super Admin can create scoped admin roles and accounts.

## Administration and student support

Open `/admin` or use the **Admin Login** link in the home-page footer to reach the restricted
administrator sign-in page. The dashboard is shown only after an active admin or super-admin signs
in; student accounts are sent back to the public site.

The dashboard includes student/course management, payment review, enrollment access,
support tickets, review moderation, announcements, public website content, analytics/CSV exports,
administrator roles, a read-only audit log, and platform configuration status. Admin actions are
permission-checked on the server and audited. Website content fields accept plain text; public
announcements and editable text are rendered without interpreting HTML.

Students can submit manual payment references and optional proof from their dashboard
(`POST /api/payments/manual`; view history with `GET /api/payments/mine`). Paid course access
remains pending until an administrator approves the request. Configure payment instructions in the
administration dashboard before accepting manual payments. Uploads use local storage under `instance/uploads`. Defaults are 500 MB per video, 25 MB per notes
PDF, 10 MB per support attachment, and 5 MB per payment proof; these can be adjusted with the
`MAX_*_UPLOAD_BYTES` environment variables. Configure matching reverse-proxy limits, backups, and
persistent storage for production deployments. External object-storage providers are not currently
implemented.

## UPI Gateway checkout

For a staged Sandbox deployment, environment-variable reference, migration sequence, service setup,
and acceptance checklist, see [SANDBOX_DEPLOYMENT.md](SANDBOX_DEPLOYMENT.md).

The Flask platform connects to the Laravel UPI Gateway as a separate payment service. Do not copy
Laravel files into this repository. Deploy the gateway independently using its
[production package and browser installer](https://github.com/mynkdev-21/upi-gateway#installation),
with PHP 8.2+, MySQL, HTTPS, and the gateway's production web root set to its `public/` directory.
Follow the gateway's cPanel, VPS, and installation guides for the hosting-specific configuration.

Create separate Sandbox and Live merchant credentials in the gateway. Configure the matching
values in the Flask server's private environment (see `.env.example`):

For local development, create the ignored environment file before starting Flask:

```powershell
Copy-Item .env.example .env
```

Edit `.env` with the gateway's Sandbox URL, merchant key/secret, and matching webhook secret.
The application loads this file for both Flask CLI and `python -m backend.app`; `.env` is ignored
by Git, while `.env.example` contains placeholders only.

- `UPI_GATEWAY_BASE_URL`: the gateway HTTPS origin.
- `UPI_GATEWAY_API_KEY` and `UPI_GATEWAY_API_SECRET`: the selected environment's merchant pair.
- `UPI_GATEWAY_WEBHOOK_SECRET`: webhook signing secret for that same environment.
- `UPI_GATEWAY_ENVIRONMENT`: `sandbox` or `live`; Sandbox credentials must use the `test_key_` /
  `test_sec_` pair. Live requires the Live key pair and HTTPS.
- `UPI_GATEWAY_RETURN_URL`: optional HTTPS return URL. Add its hostname to the merchant's
  **Allowed redirect domains** in the gateway dashboard before using it. Use `{payment_id}` in
  the URL if the return page should receive the internal payment id, for example
  `https://learn.example.com/upi-payment.html?id={payment_id}`.
- `UPI_GATEWAY_TIMEOUT_SECONDS` and `UPI_GATEWAY_MAX_WEBHOOK_BYTES`: bounded request settings.

Never put these credentials in frontend files or commit production secrets. Configure the gateway's
webhook destination as `https://<flask-host>/api/payments/upi/webhook` and select the matching
environment secret. The endpoint verifies the timestamped `X-Signature` against the exact raw body,
requires a timestamp within five minutes, and deduplicates `X-Event-Id` using the signed event
sequence. Successful orders are also fetched from the authenticated gateway order-status API before
Live course access is granted. Sandbox confirmations never activate course access. Payment amount is
always read from the published course record; the browser cannot set it.

The home page and Courses catalog render published database courses. Free courses use the
authenticated enrollment endpoint; courses with a non-zero admin-set price open the UPI checkout
and display a returned UPI intent or the gateway's hosted payment option. The API does not
document a QR image URL, so the Flask frontend does not construct one. Set course prices in Admin → Courses rather
than editing frontend markup. The course player loads lessons for the selected course and only
returns preview lessons to students without active enrollment. A verified Live payment activates
enrollment before the payment page offers course access.

Apply the Flask schema migration after configuring the application:

```powershell
python -m flask --app backend.app db upgrade
```

The protected student endpoints are:

- `POST /api/payments/upi/orders` — create or reuse the active order for a published course.
- `GET /api/payments/upi/<payment_id>` — retrieve the student's own checkout details.
- `POST /api/payments/upi/<payment_id>/check` — query the gateway's authenticated status API.
- `GET /api/payments/mine` — list only the signed-in student's payment history.
- `GET /api/payments/<payment_id>/receipt` — download a receipt for a verified Live payment.
- `POST /api/payments/upi/webhook` — gateway callback protected by raw-body HMAC validation.

Students can start checkout from a paid course card or Dashboard → Course payments. The payment page
displays the returned UPI intent or hosted checkout, status, expiry, and a verified Live receipt.
Students can only view their own payment records. Super Admins can filter payments by status,
student/order search, and environment, and inspect webhook processing and per-payment verification
history. The gateway API does not provide an order-cancellation endpoint; leaving checkout does not
cancel the provider-side order, which expires according to the gateway.

Automated tests mock the gateway and cover server-side pricing, order reuse, Sandbox isolation,
ownership checks, signed webhook verification, duplicate delivery, out-of-order events, and receipts.
Complete Sandbox tests against your deployed gateway and a real-device UPI flow before considering
Live mode. This repository has no provider credentials configured by default, so a fresh local
installation will not create real payment orders until the server environment and gateway are set up.

Student support is available from the dashboard. Its HTTP API uses
`GET/POST /api/support/tickets`, `GET/POST /api/support/tickets/<id>/messages`,
`POST /api/support/tickets/<id>/attachments`, and `POST /api/support/tickets/<id>/read`.
Administrators use `/api/admin/support/tickets`; access to ticket details, replies, assignments,
and internal notes is checked against the current session and role permissions.

Authenticated Socket.IO support events are `support_join_ticket`, `support_leave_ticket`,
`support_send_message`, `support_mark_read`, `support_user_typing`, and
`support_user_stop_typing`. Every event checks ticket ownership or the required administrator
permission; internal notes use a separate room and are not delivered to students. Socket message
content is stored in the database before it is broadcast.

Key admin APIs are under `/api/admin`: `/auth/login`, `/auth/me`, `/stats`, `/users`,
`/courses`, `/categories`, `/courses/<id>/lessons`, `/notes`, `/payments`, `/enrollments`,
`/certificates`, `/activity`, `/support/tickets`, `/support/assignees`, `/reviews`,
`/announcements`, `/content`, `/reports`, `/reports/export.csv`, `/admins`, `/roles`,
`/audit-logs`, and `/settings`. Run `python -m flask --app backend.app db upgrade` after
pulling schema changes.

## Tests

```powershell
python -m pytest -q
```

## Database

Development uses SQLite. Set `DATABASE_URL` to a PostgreSQL URL for production.

```text
postgresql+psycopg://user:password@host/database
```

Run migrations with:

```powershell
python -m flask --app backend.app db upgrade
```

## Production

```powershell
$env:FLASK_DEBUG="false"
$env:SECRET_KEY="<random-long-secret>"
$env:DATABASE_URL="<postgresql-url>"
$env:SESSION_COOKIE_SECURE="true"
$env:CORS_ORIGINS="<frontend-origin>"
gunicorn --worker-class geventwebsocket.gunicorn.workers.GeventWebSocketWorker --workers 1 --bind 0.0.0.0:$env:PORT backend.app:app
```

Configure payment and AI integrations using `.env.example`. Razorpay and OpenAI features remain unavailable until credentials are configured.

## Private student chat

Chat data is stored in the application's SQL database. Apply the migration with `python -m flask --app backend.app db upgrade`. Students are discovered from existing active `student` records; no separate chat accounts are created. The pair uniqueness constraint ensures only one private conversation exists for any two students. The chat API returns student name/avatar only (plus the internal conversation/student IDs needed to open a conversation); it never includes student email or password data.

Socket.IO authenticates using the same secure Flask session cookie. Configure `CORS_ORIGINS` to the exact frontend origin(s) in production; the default is restricted to local development origins. Use a shared Socket.IO message queue such as Redis if running multiple workers/instances.
