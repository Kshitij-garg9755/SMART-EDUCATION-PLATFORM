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

## 3. Create Render services

In Render, create a Blueprint from the same GitHub repository and select the root
`render.yaml`. It provisions the Flask web service, PostgreSQL database, and a persistent
uploads disk. The service runs database migrations at startup and exposes `/api/health`
as its health check.

Set `CORS_ORIGINS` to the exact Netlify origin, including `https://` and no trailing
slash (for example `https://your-site.netlify.app`). Add a custom frontend domain here too
if you use one. After the Render service is ready, copy its `https://...onrender.com`
origin into Netlify's `RENDER_API_URL` and redeploy the site.

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

The Blueprint uses a paid Render web plan because the service needs a persistent disk for
uploaded videos, notes, attachments, and payment proofs. The Render database is separate
and durable. Render's free web services can sleep and its free PostgreSQL database expires,
so they are not suitable for a continuously available production site.
