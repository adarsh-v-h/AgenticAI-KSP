# Deployment — KSP Crime Intelligence

This document explains **how this application is deployed to Zoho Catalyst**,
what was set up to make it work, how to **make changes and redeploy safely**,
and the **issues that arise** and how to fix them.

For a first-time-from-scratch tool install walkthrough (installing Node, the
Catalyst CLI, logging in), see `FULL_DEPLOYMENT_WALKTHROUGH.md`. This document
is the practical reference for an already-configured project.

---

## 1. Architecture at a glance

The app has two independently deployed halves:

| Part | Tech | Catalyst component | Live URL |
|---|---|---|---|
| Backend | Python / FastAPI | AppSail (Catalyst-managed runtime) | `https://crime-intel-backend-50043099694.development.catalystappsail.in` |
| Frontend | React / Vite (static build) | Web Client Hosting | `https://datathon-60074122671.development.catalystserverless.in` |

The frontend calls the backend over HTTPS. The backend's URL is baked into the
frontend at build time via the `VITE_API_BASE_URL` env var (see
`frontend/src/config.js`). The backend restricts CORS to the frontend origin via
`ALLOWED_ORIGINS`.

```
Browser ──HTTPS──> Web Client (React)  ──HTTPS /api/*──>  AppSail (FastAPI)
                                                              │
                                        ┌─────────────────────┼───────────────────┐
                                        ▼                     ▼                   ▼
                                  AWS RDS MySQL         Catalyst NoSQL      Catalyst QuickML (LLM)
```

---

## 2. Files that make deployment work

| File | Purpose | In git? |
|---|---|---|
| `catalyst.json` | Links the AppSail service (`backend/`) and Web Client (`client-package/`) to the Catalyst project. | ✅ yes |
| `.catalystrc` | Local project/environment binding created by the CLI. Machine-local. | ❌ gitignored |
| `backend/app-config.template.json` | AppSail config **without secrets** — startup command, stack, memory, predeploy script. Source of truth for structure. | ✅ yes |
| `backend/app-config.json` | The real config `catalyst deploy` consumes. Generated from the template + `.env`. **Contains secrets.** | ❌ gitignored |
| `backend/requirements.txt` | Python deps for the AppSail runtime (separate from the root testing `requirements.txt`). | ✅ yes |
| `backend/.catalystignore` | Excludes tests/debug files from the deploy bundle. | ✅ yes |
| `scripts/gen_app_config.py` | Reads `.env`, fills the template, writes `backend/app-config.json`. Keeps secrets out of git. | ✅ yes |
| `client-package/client-package.json` | Web Client Hosting config (name, version, homepage). | ✅ yes |
| `client-package/` (build output) | The compiled React app copied from `frontend/dist/`. | ❌ gitignored (regenerated) |
| `deploy.sh` | One-command deploy for backend, frontend, or both. | ✅ yes |
| `.env` | All real secrets and config. | ❌ gitignored |

**Vendored Python dependencies:** Catalyst's managed runtime does **not**
`pip install` from `requirements.txt` on its side. Dependencies are installed
into `backend/` (via the `predeploy` script) and uploaded with the code. These
vendored package directories are gitignored and regenerated on each deploy.

---

## 3. How to deploy

### Prerequisites (once per machine)
- Node.js + npm, and the Catalyst CLI: `npm install -g zcatalyst-cli`
- `catalyst login` (authenticates the CLI to the Zoho account)
- A populated `.env` at the project root (copy from `.env.example`, fill values)
- A **fresh** `CATALYST_API_TOKEN` in `.env` (tokens expire ~1 hour — see §6)

### The easy way — `deploy.sh`
From the project root:
```bash
./deploy.sh            # deploy backend + frontend
./deploy.sh backend    # backend only
./deploy.sh frontend   # frontend only
```
`deploy.sh` handles everything: generating `app-config.json` from `.env`,
bundling backend deps, building the frontend with the backend URL baked in,
copying the build into `client-package/`, and running `catalyst deploy`.

### The manual way (if you need finer control)

**Backend:**
```bash
python3 scripts/gen_app_config.py                 # secrets .env -> app-config.json
catalyst deploy --only appsail                    # predeploy bundles deps, then deploys
curl <backend-url>/health                          # verify
```

**Frontend:**
```bash
cd frontend
VITE_API_BASE_URL=<backend-url> npm run build      # bake backend URL into the build
cd ..
# copy build into client-package, preserving client-package.json
find client-package -mindepth 1 ! -name 'client-package.json' -delete
cp -r frontend/dist/. client-package/
catalyst deploy --only client
```

---

## 4. Making changes to the codebase and redeploying

### Backend code change (Python)
1. Edit code under `backend/`.
2. Run tests locally: `.venv/bin/pytest backend/tests/ -q`
3. Redeploy: `./deploy.sh backend`
4. Verify: `curl <backend-url>/health`

No dependency change → the bundled deps are reused. If you **added a Python
dependency**, add it to `backend/requirements.txt` first; the `predeploy` script
reinstalls into `backend/` on the next deploy.

### Frontend code change (React)
1. Edit code under `frontend/src/`.
2. Run tests locally: `cd frontend && npm test`
3. Redeploy: `./deploy.sh frontend`
4. Hard-refresh the browser (or use an incognito window) to bypass cache.

### Changing an environment variable / secret
1. Edit the value in `.env` (never in a committed file).
2. `./deploy.sh backend` — this regenerates `app-config.json` from `.env` and
   redeploys. (CORS `ALLOWED_ORIGINS` is read from the environment at request
   time, but on AppSail it is set as an env variable, so a redeploy is the
   reliable way to apply it.)

### Adding a new backend env variable
1. Add it to `.env` and `.env.example` (document it).
2. If the app **requires** it at startup, add it to `REQUIRED_VARS` in
   `backend/config/settings.py`; otherwise add it to `OPTIONAL_VARS`.
3. Add a mapping in `scripts/gen_app_config.py` so the generator injects it
   into `app-config.json`:
   - Add to `_REQUIRED_ENV_VAR_SOURCES` if the app must have it to start.
   - Add to `_OPTIONAL_ENV_VAR_SOURCES` if it backs an optional feature
     (injected when present in `.env`, skipped silently when absent).
   - If its name starts with `CATALYST_`, map it to a `KSP_CATALYST_*` key
     (Catalyst rejects the reserved prefix) and rely on the `get()` fallback in
     `settings.py`.
4. `./deploy.sh backend`.

> **Lesson learned (voice 502):** the Zia voice URLs (`ZIA_STT_URL`,
> `ZIA_TTS_URL`, `ZIA_TRANSLATE_URL`) were in `.env` but the generator didn't
> map them, so they never reached the deployment and `/api/voice/speak`
> returned 502. Any env var a feature reads at runtime MUST be in one of the
> generator's mapping dicts, or it won't exist on AppSail. The smoke test now
> guards this.

### Changing the frontend↔backend URL
- If the **backend URL** changes: update `DEFAULT_BACKEND_URL` in `deploy.sh`
  (or export `VITE_API_BASE_URL`), rebuild + redeploy the frontend, and update
  `_DEFAULT_ALLOWED_ORIGINS` in `scripts/gen_app_config.py` if the frontend URL
  changed too.
- If the **frontend URL** changes: update `ALLOWED_ORIGINS`
  (`_DEFAULT_ALLOWED_ORIGINS` in `scripts/gen_app_config.py`) and redeploy the
  backend so CORS accepts the new origin.

---

## 5. What was set up (change history / what I did)

1. **Fixed the Catalyst project structure.** `catalyst.json` now points the
   AppSail `source` at `backend/` and registers `client-package/` as the web
   client. The AppSail `app-config.json` lives inside `backend/`.
2. **Correct startup command.** `python3 -m uvicorn main:app --host 0.0.0.0
   --port 9000` (the runtime has `python3`, not `python`; Catalyst serves on
   port 9000 by default).
3. **Dependency bundling.** Added the `predeploy` script
   (`pip install -r requirements.txt -t .`) because Catalyst's managed runtime
   does not install from `requirements.txt`. Added the missing
   `python-multipart` dependency (needed by file-upload endpoints).
4. **Reserved-name workaround.** Catalyst rejects env variables starting with
   `CATALYST_`. Renamed them to `KSP_CATALYST_*` and added a fallback in
   `backend/config/settings.py` so the code still reads `CATALYST_API_TOKEN` /
   `CATALYST_ORG_ID` transparently.
5. **Frontend cross-domain support.** All frontend API calls prepend
   `API_BASE` (`frontend/src/config.js`, fed by `VITE_API_BASE_URL`) so the
   static build can call the AppSail backend on a different domain.
6. **Secret hygiene.** Removed committed secrets from git. Introduced
   `app-config.template.json` (committed, no secrets) +
   `scripts/gen_app_config.py` (injects secrets from `.env` at deploy time).
   `backend/app-config.json` is now gitignored. (`.env` itself IS committed —
   see §7 — because the repo is private with a single shared deployment.)
7. **`deploy.sh`.** One-command deploy that ties all the above together.
8. **Frontend asset base path.** Catalyst serves the SPA under `/app/`, but
   Vite built absolute `/assets/...` paths → blank page + 404s. Fixed with
   `base: './'` in `vite.config.js` (relative asset paths).
9. **Duplicate CORS header.** Catalyst's proxy injects its own
   `Access-Control-Allow-Origin` for the linked web-client origin; our
   `CORSMiddleware` added a second one → browser rejected every API response
   ("Cannot reach the server"). Fixed by gating `CORSMiddleware` to
   non-production only (`main.py`), letting Catalyst own CORS in prod.
10. **Voice env vars + empty-session 404.** The `ZIA_*` URLs weren't injected by
    the config generator (voice 502), and `POST /api/chat/sessions` only wrote
    to NoSQL — not MySQL `chat_sessions` — so ownership checks 404'd on empty
    sessions. Both fixed and now covered by the smoke test.
11. **CI/CD with auto-revert.** GitHub Actions runs tests → deploys → smoke
    tests the live deployment → tags `last-good-deploy` on success or rolls
    back to it on failure (see §8).

---

## 6. Issues that arise (and how to fix them)

| Symptom | Cause | Fix |
|---|---|---|
| `/health` returns 503 `Execution failed. Please check the startup command or port.` | The Python process crashed on startup, or the startup command is wrong. | Open Catalyst console → AppSail → the service → **Logs**. The traceback pinpoints it (missing dep, bad import, wrong binary). |
| Logs: `exec: python: not found` | Used `python` instead of `python3`. | The template already uses `python3`. Don't change it back. |
| Logs: `No module named uvicorn` (or fastapi, pydantic, etc.) | Dependencies were not bundled into `backend/`. | Run `./deploy.sh backend` (runs the `predeploy` bundling), or manually `pip install -r requirements.txt -t backend/`. |
| Logs: `No module named 'pydantic_core._pydantic_core'` | Bundled binary wheels don't match the runtime's Python version. | Ensure the local Python used for bundling matches the `stack` (currently `python_3_10` → build with Python 3.10). |
| Logs: `Form data requires "python-multipart"` | `python-multipart` missing. | It's in `requirements.txt`; re-bundle + redeploy. |
| Deploy fails: `environment_variables must not contain reserved keywords` | An env var name starts with the reserved `CATALYST_` prefix. | Use `KSP_CATALYST_*` (the generator already does this). |
| `/health` → `"status":"degraded"`, `"db":"connected"`, `"llm_coder":"error"` | The Catalyst API token expired (~1 hour lifetime). | Refresh the token (snippet at the bottom of `.env`), paste into `.env` as `CATALYST_API_TOKEN`, run `./deploy.sh backend`. |
| `/health` → `"db":"error"` | RDS MySQL unreachable or bad credentials. | Verify `DB_*` values in `.env`; check the RDS instance is up and its security group allows Catalyst egress. |
| Frontend loads but every API call fails with a CORS error | `ALLOWED_ORIGINS` doesn't match the frontend origin. | Set `_DEFAULT_ALLOWED_ORIGINS` in `scripts/gen_app_config.py` to the exact frontend origin (`https://`, no trailing slash) and redeploy the backend. |
| Frontend calls `localhost` / relative paths in production | Built without `VITE_API_BASE_URL`. | Rebuild with the backend URL: `./deploy.sh frontend` (it sets it automatically). |
| Deploy uploads "in 0 seconds" then 503 | No deps were bundled (used `--ignore-scripts` with an empty `backend/`). | Let the `predeploy` script run, or bundle deps manually before deploying. |
| Frontend page is **blank**; console shows `404` for `/assets/*.js` and a CSS MIME error | Vite built absolute `/assets/...` paths but the app is served under `/app/`. | Ensure `base: './'` is set in `vite.config.js`, rebuild + redeploy the frontend. |
| Login (or every API call) shows "Cannot reach the server" even though the backend is healthy | Duplicate `Access-Control-Allow-Origin` headers (our `CORSMiddleware` + Catalyst proxy) → browser rejects the response. | Keep `CORSMiddleware` gated to non-production in `main.py`; let Catalyst handle CORS in prod. Verify with `curl -sD- ... \| grep -ci access-control-allow-origin` → must be `1`. |
| `/api/voice/speak` returns 502 `TTS not configured: ... ZIA_TTS_URL is not set` | A feature's env var is in `.env` but not mapped in the config generator, so it never reached AppSail. | Add it to `_OPTIONAL_ENV_VAR_SOURCES` (or `_REQUIRED_...`) in `scripts/gen_app_config.py`, then `./deploy.sh backend`. |
| `GET /api/chat/sessions/{id}/messages` returns 404 for a session you just created | Session was written to NoSQL but not MySQL `chat_sessions`, which ownership checks read. | Fixed: `create_chat_session` now writes both. If reintroduced, ensure any new session-creation path registers the MySQL row. |

### Refreshing the Catalyst API token
Catalyst OAuth access tokens last ~1 hour. To mint a new one (credentials are in
the commented refresh snippet at the bottom of `.env`):
```bash
curl -X POST "https://accounts.zoho.in/oauth/v2/token" \
  -d "grant_type=refresh_token" \
  -d "client_id=YOUR_CLIENT_ID" \
  -d "client_secret=YOUR_CLIENT_SECRET" \
  -d "refresh_token=YOUR_REFRESH_TOKEN"
```
Copy the `access_token` from the response into `.env` as `CATALYST_API_TOKEN`,
then `./deploy.sh backend`.

---

## 7. Security notes

- **`.env` IS committed — deliberately.** The repo is **private** with a small
  set of trusted contributors, and there is a **single shared deployment**
  (one backend, one DB, one Catalyst project), so every contributor works
  against the same environment. Both `.env` (backend) and `frontend/.env` are
  version-controlled so the team stays in sync without out-of-band secret
  sharing. **This is a deliberate tradeoff that only holds while the repo is
  private.**
- **If the repo is ever made public** (or a contributor is removed), you MUST:
  remove both `.env` files from tracking, purge them from git history
  (`git filter-repo`), and rotate every secret — RDS password,
  `APP_SECRET_KEY`, and the Catalyst token.
- **`backend/app-config.json` stays gitignored.** It's a generated artifact
  (from `.env` + the template); no need to duplicate secrets there in git.
- **CORS is locked to the frontend origin**, never `*`.
- **Never echo secret values** in logs, terminal output, PR descriptions, or
  documentation.
- **DB password + `APP_SECRET_KEY` were rotated** after being exposed in early
  git history. The old Catalyst token was rotated too. If you suspect further
  exposure, rotate again: `python3 -c "import secrets; print(secrets.token_hex(32))"`
  for the secret key, and change the RDS master password in the AWS console.

---

## 8. CI/CD — auto-deploy with smoke test and auto-revert

GitHub Actions automates the whole pipeline so deploy-only bugs (like the voice
502 or the login CORS failure) are caught by the machine, not by hand.

### Workflows
- **`.github/workflows/ci.yml`** — runs on every push/PR. Backend pytest +
  frontend vitest + a production build check. Pure gate, no deploy.
- **`.github/workflows/deploy.yml`** — runs on push to `main` (or manual
  "Run workflow"). The pipeline:
  1. **Test gate** — backend + frontend tests must pass, or nothing deploys.
  2. **Deploy** — `.github/scripts/ci_deploy.sh` generates `app-config.json`
     from the `ENV_FILE` secret, bundles deps, builds the frontend with the
     backend URL, and deploys both AppSail + Web Client using a Catalyst CLI
     token.
  3. **Smoke test** — `scripts/smoke_test.py` runs against the LIVE URL
     (health, auth, all analytics/profiling/voice/governance endpoints).
  4. **Promote or revert:**
     - Smoke **passes** → the commit is tagged `last-good-deploy`.
     - Smoke **fails** → the workflow checks out the `last-good-deploy` tag,
       redeploys it, and fails the run. The live deployment automatically ends
       up back on the last known-good version.

### One-time setup (per repo)
Add these in **GitHub → Settings → Secrets and variables → Actions**:

| Secret | How to get it |
|---|---|
| `CATALYST_TOKEN` | On a logged-in machine run `catalyst token:generate`, complete the browser verification, copy the token. It does not expire until revoked. |
| `ENV_FILE` | Paste the **entire contents** of the backend `.env`. The workflow writes it back to `.env` before deploying so the config generator has all secrets. |

That's it. Push to `main` and the pipeline deploys, verifies, and self-heals on
failure.

### Notes / limits
- The auto-revert redeploys the previous **git-tagged** build, not a Catalyst
  platform snapshot — this is deterministic and needs no Catalyst-native
  rollback feature.
- The `CATALYST_TOKEN` maps to the user who generated it; keep it in GitHub
  secrets only. Revoke with `catalyst token:revoke` if leaked.
- The first successful deploy creates the `last-good-deploy` tag; until then,
  a smoke failure can't auto-revert (it warns instead).

---

## 9. Smoke test (run it anytime)

`scripts/smoke_test.py` exercises the live deployment end-to-end and is the
same script CI uses. Run it manually after any manual deploy:

```bash
python3 scripts/smoke_test.py                       # default backend URL
SMOKE_BASE_URL=https://... python3 scripts/smoke_test.py
```

It logs in as a seeded supervisor and checks health, auth, chat/sessions,
every analytics/demographics/forecasting endpoint, profiling, voice (TTS +
STT reachability), and RBAC. Exit code `0` = healthy, `1` = something is broken
(CI blocks/rolls back on non-zero). This is the layer that catches env-var,
CORS, and integration bugs that unit tests structurally cannot.
