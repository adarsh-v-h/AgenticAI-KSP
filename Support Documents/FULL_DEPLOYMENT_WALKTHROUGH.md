# Deployment Guide — Zoho Catalyst (Full Walkthrough)

This is a complete, self-contained walkthrough for deploying this application to Zoho Catalyst — from installing the tools for the very first time, through to a verified live deployment. Follow it top to bottom, in order. No prior Catalyst experience is assumed.

The application has two parts that get deployed separately:
- **Backend** (Python/FastAPI) → deployed to **Catalyst AppSail** as a Managed Runtime
- **Frontend** (React/Vite) → deployed to **Catalyst Web Client Hosting** as a static build

---

## Part 0 — One-time setup (skip anything you already have)

### 0.1 Check if Node.js and npm are already installed

Open a terminal and run:
```
node -v
npm -v
```
If both print version numbers, skip to 0.2. If either command fails ("command not found"), install Node.js:
- Go to https://nodejs.org and download the LTS version for your operating system.
- Run the installer. npm is bundled with Node.js, so installing Node.js installs both.
- Close and reopen your terminal, then re-run `node -v` and `npm -v` to confirm.

### 0.2 Install the Catalyst CLI

Run:
```
npm install -g zcatalyst-cli
```
On macOS/Linux, if you get a permissions error, run it with `sudo`:
```
sudo npm install -g zcatalyst-cli
```
On Windows, if you get a permissions error, close your terminal, reopen it "as Administrator," and re-run the command.

Confirm the install worked:
```
catalyst --version
```
This should print a version number (e.g. `1.25.1`). If it doesn't, close and reopen your terminal and try again — sometimes the terminal needs a restart to pick up a newly installed global command.

### 0.3 Log in to the Catalyst CLI

Run:
```
catalyst login
```
- Your default browser will open automatically to a Zoho Accounts sign-in page. If it doesn't open automatically, the terminal will print a URL — copy and open that manually.
- Sign in with the Zoho account that has access to this Catalyst project.
- Approve the permission request Catalyst CLI asks for.
- You'll be asked whether to allow error-reporting information to be collected — press `Y` or `N`, either is fine, it doesn't affect deployment.
- You may be asked to select a data center — choose the one this project's account is registered under (India, unless you know otherwise).
- Once you see a success message in the browser, close that tab and return to the terminal — it should also show a "login successful" message.

You only need to do Part 0 once per machine.

---

## Part 1 — Get the project set up on this machine

### 1.1 Get the code

If you don't already have the project folder on this machine, clone it:
```
git clone <repository-url>
cd <project-folder-name>
```
Make sure you're on the correct branch (confirm the branch name before proceeding — do not deploy from an unmerged feature branch).

### 1.2 Confirm the project is already linked to Catalyst

From inside the project's root folder (the one containing a file named `catalyst.json`), run:
```
catalyst project:list
```
This shows the Catalyst projects associated with this folder. You should see this project listed. If `catalyst.json` is missing entirely, stop and check with the person who set up the project originally — that means the Catalyst project link itself needs to be re-established, which is a different step than what this guide covers.

---

## Part 2 — Deploy the backend (AppSail)

The backend must be deployed **first**, because the frontend build needs the backend's live URL.

### 2.1 Check if an AppSail service already exists for this project

Run:
```
catalyst appsail:list
```
- **If a service is already listed**, note its name — you'll deploy updates to it directly (skip to 2.3).
- **If nothing is listed**, you need to add one — continue to 2.2.

### 2.2 Add a new AppSail service (only if 2.1 showed nothing)

From the project root, run:
```
catalyst appsail:add
```
You'll be asked a series of questions — answer as follows:
- **Runtime type** → choose **Catalyst-Managed Runtime** (do NOT choose Docker Image)
- **Start with a sample app?** → No / N (this is our own existing app)
- **Source directory** → point this to the `backend/` folder inside the project
- **App name** → give it a clear name, e.g. `crime-intel-backend`
- **Runtime** → select **Python** (and the specific version if asked — match whatever version is in the project's `requirements.txt` or `runtime.txt`, or use the latest Python 3.x option offered)
- **Startup command** → enter exactly:
  ```
  uvicorn main:app --host 0.0.0.0 --port 8000
  ```

This creates an `app-config.json` file describing the service — you can leave it as generated.

### 2.3 Enter environment variables in the Catalyst console

This part is done in the browser, not the terminal.

1. Go to https://console.catalyst.zoho.com and open this project.
2. In the left sidebar, go to **Serverless** → **AppSail**.
3. Click on the backend service you just created (or the existing one from 2.1).
4. Go to the **Configuration** tab, then find **Environment Variables**.
5. Click **Create Variable** for each of the following, entering the key exactly as shown and the correct value for production:

| Key | Value to enter |
|---|---|
| `APP_SECRET_KEY` | A brand-new random secret — do NOT reuse the local development value. Generate one with `python3 -c "import secrets; print(secrets.token_hex(32))"` and paste the output. |
| `ALLOWED_ORIGINS` | For now, enter a placeholder: `http://localhost:5173` — you will come back and fix this in Part 4. |
| *(every other key in the project's `.env.example` file)* | Copy the production value for each — database credentials, Catalyst org ID, API tokens, QuickML URLs, NoSQL URL, and anything else listed there. Do not skip any — the app will fail to start if even one required variable is missing. |

Click **Save** after adding each variable.

### 2.4 Deploy the backend

From the project root in your terminal, run:
```
catalyst deploy --only appsail
```
Wait for it to finish. When it completes, the terminal will print a live URL for this service — it will look something like:
```
https://crime-intel-backend-xxxxx.development.catalystserverless.in
```
**Copy this URL somewhere safe — you need it in the next part.**

### 2.5 Confirm the backend is actually running

Open a browser and go to:
```
https://<the-url-from-2.4>/health
```
You should see a healthy/OK response. If instead you see an error or the page fails to load, go to the AppSail service page in the console and check its **Logs** tab — the most common cause at this stage is a missing environment variable from step 2.3.

---

## Part 3 — Deploy the frontend (Web Client Hosting)

### 3.1 Build the frontend with the real backend address

From the project's frontend folder, run (replacing the URL with the one you copied in 2.4, no trailing slash):
```
VITE_API_BASE_URL=https://crime-intel-backend-xxxxx.development.catalystserverless.in npm run build
```
On Windows (Command Prompt), the syntax is different — use:
```
set VITE_API_BASE_URL=https://crime-intel-backend-xxxxx.development.catalystserverless.in
npm run build
```
On Windows PowerShell:
```
$env:VITE_API_BASE_URL="https://crime-intel-backend-xxxxx.development.catalystserverless.in"
npm run build
```
This produces a `dist/` (or `build/`) folder containing the production-ready static files, with the backend address baked directly into them.

### 3.2 Deploy the built frontend

From the project root, run:
```
catalyst deploy --only client
```
When it completes, the terminal prints the live frontend URL — something like:
```
https://your-project-name.development.catalystserverless.in
```
**Copy this URL too.**

---

## Part 4 — Close the loop: fix the CORS setting

Now that the frontend's real URL exists, go back and update the placeholder from step 2.3.

1. Go back to the Catalyst console → **Serverless** → **AppSail** → your backend service → **Configuration** → **Environment Variables**.
2. Find `ALLOWED_ORIGINS` and edit it.
3. Replace the placeholder with the frontend URL from step 3.2, exactly as printed (including `https://`, no trailing slash).
4. Click **Save**.

This takes effect immediately — no redeploy needed, since the backend reads this value from the environment at request time.

---

## Part 5 — Verify everything end-to-end

Go through this checklist in order. Do not skip steps even if earlier ones look fine.

- [ ] Open the frontend URL from step 3.2 in a browser (use an incognito/private window to avoid any cached local session).
- [ ] Confirm the login page loads correctly.
- [ ] Log in with a real account.
- [ ] Send a real chat query and confirm you get an actual answer back — not a spinner that never resolves, not an error.
- [ ] Open browser developer tools (F12) → **Network** tab → refresh and send another query → confirm the requests are going to the AppSail URL from Part 2, not `localhost` and not a relative path like `/api/...` with no domain.
- [ ] Check for any red CORS errors in the browser console. If present, double check Part 4 was saved correctly and that the URL matches exactly (`https://` vs `http://`, no trailing slash mismatches).
- [ ] Directly visit `https://<backend-url>/health` one more time to confirm it's still healthy after real traffic.

If every box is checked, the deployment is live and working.

---

## Troubleshooting reference

| Symptom | Likely cause | Fix |
|---|---|---|
| `catalyst` command not found after install | Terminal hasn't picked up the new global path | Close and reopen the terminal completely |
| Backend deploy succeeds but `/health` fails | A required environment variable is missing | Check the **Logs** tab on the AppSail service in the console for the exact error |
| Frontend loads, but every request fails with a CORS error | `ALLOWED_ORIGINS` not updated, or updated with a mismatched URL | Redo Part 4, check for exact match including `https://` and no trailing slash |
| Login works, but chat queries silently fail or hang | A database/QuickML/NoSQL-related environment variable is wrong | Recheck each value against `.env.example` line by line |
| Frontend deployed but still calling `localhost` or relative paths | The build in step 3.1 ran without `VITE_API_BASE_URL` set correctly | Redo step 3.1 exactly as written, then redeploy with `catalyst deploy --only client` |
| Need to redeploy just one part after a small fix | — | Use `catalyst deploy --only appsail` or `catalyst deploy --only client` to avoid redeploying the whole project unnecessarily |

---

## Quick command reference (all commands used in this guide, in order)

```
node -v
npm -v
npm install -g zcatalyst-cli
catalyst --version
catalyst login
catalyst project:list
catalyst appsail:list
catalyst appsail:add
catalyst deploy --only appsail
npm run build                      # (with VITE_API_BASE_URL set beforehand)
catalyst deploy --only client
```
