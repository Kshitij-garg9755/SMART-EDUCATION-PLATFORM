# Live deployment: Netlify + Render

The site uses Netlify for the static frontend and Render for Flask, Socket.IO,
PostgreSQL, and persistent uploads. `www/` is the Netlify publish directory.

## 1. Push the project to GitHub

Commit and push the intended project files to the connected repository. Do not commit
`.env`, database files, uploaded student files, or credentials.

## 2. Create the Netlify site

Import the GitHub repository in Netlify. The root `netlify.toml` sets `www` as the
publish directory and runs `node scripts/configure-netlify.js` during the build.
After Render is created, set this Netlify environment variable and redeploy:

| Variable | Value |
| --- | --- |
| `RENDER_API_URL` | Render backend origin, for example `https://kshitij-coder-api.onrender.com` |

The build writes same-origin `/api/*` and `/socket.io/*` proxy rules to the generated
`www/_redirects`. Browser requests stay on the Netlify site URL, so the login session
cookie is first-party while the Netlify edge forwards API and Socket.IO traffic to Render.

## 3. Configure the Render service and persistent database

The Flask service can use PostgreSQL through `DATABASE_URL`; SQLite is only suitable for
local development. Render free web services have an ephemeral filesystem, so SQLite data
can disappear after a restart or redeploy. Create a PostgreSQL database with a provider
such as Neon, then add its connection string as the private `DATABASE_URL` environment
variable in Render. Never commit or share the connection string.

Set `REQUIRE_DATABASE_URL=true` in Render as well. This makes the service fail at startup
instead of silently accepting student registrations into temporary SQLite storage when
the database URL is missing or points to SQLite. The root `render.yaml` declares both
variables; for an already-created manual Render service, add them in its Environment
settings yourself. The startup command applies database migrations.

Set `CORS_ORIGINS` to the exact Netlify origin, including `https://` and no trailing slash
(for example `https://your-site.netlify.app`). Add a custom frontend domain here too if you
use one. After the Render service is ready, copy its `https://...onrender.com` origin into
Netlify's `RENDER_API_URL` and redeploy the site.

Do not change `SESSION_COOKIE_SECURE=true` or `SESSION_SAMESITE=Lax`; the frontend uses
the same-origin Netlify proxy for authenticated API requests and chat.

## 4. Create the first administrator and seed courses

After the Render service is live, open its Shell and run:

```sh
flask --app backend.app create-admin
flask --app backend.app seed-courses
```

For the first command, set `ADMIN_EMAIL` and `ADMIN_PASSWORD` in the Render service's
private environment first. Use a unique password and remove `ADMIN_PASSWORD` from the
service environment after the administrator has been created. Do not share credentials
in chat or commit them to Git.

## Existing local data

The Render database starts empty. Deploying the code does not copy local student accounts,
course edits, payments, chat history, or uploaded files. Decide separately whether existing
records should be migrated; handle any student information and payment records carefully,
and make a verified backup before a migration.

## Payment and optional integrations

The Blueprint leaves UPI payments in Sandbox mode. Keep payment checkout disabled until the
gateway's Sandbox credentials and webhook are configured in Render and verified. Live
payment credentials require a separate deliberate setup. `OPENAI_API_KEY` is optional and
must only be set in Render's private environment, never in frontend files.

## Persistence and availability

PostgreSQL keeps student accounts, enrollments, lesson progress, payments, and chat data
across web-service restarts. Uploaded videos, notes, attachments, and payment proofs are
stored on the web service filesystem by default; on a free Render web service those files
are ephemeral and need a separate persistent disk or object-storage setup. Free web
services can also sleep while idle, which may delay the first request.
