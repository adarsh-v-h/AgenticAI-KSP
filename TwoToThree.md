# TwoToThree — Step 3 of 5

> **Context:** Step 2 is done. `POST /api/chat` works end-to-end — NL question goes in, structured JSON with answer, table data, and media refs comes out. Both LLMs confirmed working with correct auth format (`Bearer`, `prompt`/`system_prompt`, `max_tokens=4000` minimum, `CATALYST-ORG` header required).
> Step 3 makes the platform usable as an actual chatbot: SSE streaming so the answer appears token by token, conversation history stored in Catalyst NoSQL so officers can ask follow-up questions, simple JWT auth protecting all routes, and a minimal React frontend that connects to the streaming endpoint and renders the chat interface with table display.
> Read `BLUEPRINT.md` fully. It is still the source of truth.

---

## What Step 3 Is

Step 3 is **the demo layer**. When done, you can open a browser, log in, type a question, and watch the answer stream in token by token. Ask a follow-up question without repeating context and get a coherent answer. See tabular results rendered as a clean table. This is what the judges will see.

---

## What "Done" Looks Like for Step 3

Check every one of these before calling Step 3 complete.

- [ ] `POST /api/auth/login` with valid badge number returns a JWT token
- [ ] `POST /api/chat` without a token returns HTTP 401
- [ ] `GET /api/chat/stream` streams SSE events — tokens appear one by one
- [ ] A follow-up question ("now filter by open cases only") uses the previous question's context without repeating it
- [ ] Conversation history persists across requests for the same session_id
- [ ] Frontend loads at `http://localhost:5173`
- [ ] Login page works — badge number + password → redirects to chat
- [ ] Chat input sends a question and streams the answer into the UI
- [ ] Multi-row results render as a table in the UI
- [ ] A new session starts with empty history
- [ ] Token expiry returns 401, frontend shows "session expired, please log in"

---

## Important: Lessons from Steps 1 and 2

Before writing any code, lock these in — they were learned the hard way:

- **LLM auth is `Bearer`, not `Zoho-oauthtoken`**
- **LLM body uses `prompt` / `system_prompt`, not `messages` array**
- **`max_tokens` is total context (input + output combined) — always use 4000 minimum**
- **`CATALYST-ORG` header is required on every LLM call**
- **Model names: `crm-di-qwen_coder_7b-it` and `crm-di-qwen_text_14b-fp8-it`**
- **aiomysql `%` in SQL strings — always call `cursor.execute(sql)` without params when params is empty, never pass empty tuple**
- **`.env` is at project root, not inside `backend/` — dotenv path must walk up three levels from `config/settings.py`**
- **NoSQL and Cache are Catalyst services — they require the same Bearer token and CATALYST-ORG header as LLM calls**
- **No WebSockets — SSE only for streaming**

---

## Files to Create in Step 3

```
backend/
├── conversation/
│   └── history.py              ← read/write conversation history in Catalyst NoSQL
├── cache/
│   └── catalyst_cache.py       ← Catalyst Cache read/write wrappers
├── auth/
│   └── simple_auth.py          ← JWT creation, verification, FastAPI dependency
└── routers/
    ├── auth.py                 ← POST /api/auth/login, POST /api/auth/logout
    └── chat.py                 ← UPDATE: add GET /api/chat/stream (SSE), protect with auth

frontend/
├── package.json
├── vite.config.js
├── index.html
└── src/
    ├── main.jsx
    ├── App.jsx
    ├── api/
    │   ├── auth.js             ← login/logout API calls
    │   └── chat.js             ← SSE stream handler
    ├── components/
    │   ├── LoginPage.jsx       ← badge number + password form
    │   ├── ChatWindow.jsx      ← main chat layout
    │   ├── MessageBubble.jsx   ← single message with table support
    │   └── TableRenderer.jsx   ← renders table_data as HTML table
    ├── hooks/
    │   └── useAuth.js          ← auth state (token in memory only)
    └── styles/
        └── main.css            ← minimal government-appropriate styles per Design.md
```

Also update:
- `backend/pipeline/query_pipeline.py` — wire in real history from NoSQL
- `backend/main.py` — register auth router, protect chat router
- `backend/.env` — add `NOSQL_BASE_URL` (already there) — no new vars needed

---

## Step-by-Step Instructions

Follow this order exactly.

---

### 1. Create `backend/conversation/history.py`

Catalyst NoSQL stores documents as JSON. Use it as a simple key-value store where the key is `session_id` and the value is the conversation history array.

```python
"""
Conversation history stored in Catalyst NoSQL.
Key: session_id
Value: JSON array of {role, content} dicts, max 10 turns kept.
"""
import httpx
import json
import sys
from config.settings import get

MAX_TURNS = 10  # keep last 10 turns (5 user + 5 assistant)

def _nosql_headers() -> dict:
    """
    Headers for Catalyst NoSQL API calls.
    Same auth pattern as LLM: Bearer token + CATALYST-ORG.
    """
    return {
        "Authorization": f"Bearer {get('CATALYST_API_TOKEN')}",
        "Content-Type": "application/json",
        "CATALYST-ORG": get("CATALYST_ORG_ID"),
    }

def _nosql_url(session_id: str) -> str:
    """Build the NoSQL document URL for a session."""
    base = get("NOSQL_BASE_URL")
    return f"{base}/table/conversation_history/document/{session_id}"


async def get_history(session_id: str) -> list[dict]:
    """
    Fetch conversation history for this session from Catalyst NoSQL.
    Returns list of {role, content} dicts — last MAX_TURNS turns.
    Returns empty list if session not found or on any error.
    Never raises — history failure should not block the pipeline.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                _nosql_url(session_id),
                headers=_nosql_headers(),
                timeout=5.0
            )
            if response.status_code == 200:
                data = response.json()
                # Catalyst NoSQL returns document in data.data field
                raw = data.get("data", {}).get("history", "[]")
                turns = json.loads(raw) if isinstance(raw, str) else raw
                return turns[-MAX_TURNS:] if turns else []
            return []
    except Exception as e:
        print(f"WARNING: Failed to fetch history for {session_id}: {e}", file=sys.stderr)
        return []


async def save_turn(session_id: str, user_message: str, assistant_message: str):
    """
    Append a user+assistant turn to the session history in Catalyst NoSQL.
    Fetches existing history, appends new turn, saves back.
    Keeps only the last MAX_TURNS turns.
    Never raises — history failure should not block the response.
    """
    try:
        existing = await get_history(session_id)
        existing.append({"role": "user", "content": user_message})
        existing.append({"role": "assistant", "content": assistant_message})
        # Keep only last MAX_TURNS
        trimmed = existing[-MAX_TURNS:]

        document = {"history": json.dumps(trimmed)}

        async with httpx.AsyncClient() as client:
            # Try to update first, insert if not found
            url = _nosql_url(session_id)
            response = await client.put(
                url,
                headers=_nosql_headers(),
                json={"data": document},
                timeout=5.0
            )
            if response.status_code == 404:
                # Document doesn't exist yet — create it
                create_url = get("NOSQL_BASE_URL") + "/table/conversation_history/document"
                await client.post(
                    create_url,
                    headers=_nosql_headers(),
                    json={"data": {**document, "id": session_id}},
                    timeout=5.0
                )
    except Exception as e:
        print(f"WARNING: Failed to save history for {session_id}: {e}", file=sys.stderr)


async def clear_history(session_id: str):
    """Delete all history for this session."""
    try:
        async with httpx.AsyncClient() as client:
            await client.delete(
                _nosql_url(session_id),
                headers=_nosql_headers(),
                timeout=5.0
            )
    except Exception as e:
        print(f"WARNING: Failed to clear history for {session_id}: {e}", file=sys.stderr)
```

> **Important about Catalyst NoSQL:** The exact API path and document structure depends on how the NoSQL table is configured in your Catalyst console. Before wiring this in, go to Catalyst console → NoSQL → create a table called `conversation_history` with a string field called `history`. If the API paths don't work as written, check the Catalyst NoSQL docs for the exact endpoint format and adjust `_nosql_url()` accordingly. The logic stays the same — only the URL structure may differ.

---

### 2. Create `backend/cache/catalyst_cache.py`

```python
"""
Catalyst Cache wrappers.
Used for: schema string caching (1 hour TTL).
"""
import httpx
import json
import sys
from config.settings import get

def _cache_headers() -> dict:
    return {
        "Authorization": f"Bearer {get('CATALYST_API_TOKEN')}",
        "Content-Type": "application/json",
        "CATALYST-ORG": get("CATALYST_ORG_ID"),
    }


async def cache_get(key: str) -> str | None:
    """
    GET a value from Catalyst Cache.
    Returns the string value or None on miss or error.
    Never raises.
    """
    try:
        url = f"{get('CACHE_BASE_URL')}/{key}"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=_cache_headers(), timeout=3.0)
            if response.status_code == 200:
                data = response.json()
                return data.get("data", {}).get("value")
        return None
    except Exception as e:
        print(f"WARNING: Cache GET failed for key {key}: {e}", file=sys.stderr)
        return None


async def cache_set(key: str, value: str, ttl_seconds: int = 3600):
    """
    SET a value in Catalyst Cache with TTL.
    Never raises — cache failure is non-fatal.
    """
    try:
        url = f"{get('CACHE_BASE_URL')}/{key}"
        async with httpx.AsyncClient() as client:
            await client.put(
                url,
                headers=_cache_headers(),
                json={"value": value, "ttl": ttl_seconds},
                timeout=3.0
            )
    except Exception as e:
        print(f"WARNING: Cache SET failed for key {key}: {e}", file=sys.stderr)


async def get_cached_schema(table_names: list[str]) -> str | None:
    """
    Try to get pre-formatted schema string from cache.
    Cache key: "schema_" + sorted joined table names (no colons/slashes in keys).
    """
    key = "schema_" + "_".join(sorted(table_names))
    return await cache_get(key)


async def set_cached_schema(table_names: list[str], schema_str: str):
    """Cache schema string. TTL: 1 hour."""
    key = "schema_" + "_".join(sorted(table_names))
    await cache_set(key, schema_str, ttl_seconds=3600)
```

> **Same note as NoSQL:** Catalyst Cache API paths may differ slightly from the above. Check the Catalyst Cache docs for exact endpoint format if you get 404s. The key/value logic stays the same.

---

### 3. Create `backend/auth/simple_auth.py`

Temporary JWT auth for local dev. Replaced by Catalyst Authentication on production deploy — but designed so the swap requires only changing `get_current_officer`, not any routes.

```python
"""
Simple JWT auth for local development.
REPLACE with Catalyst Authentication before production deployment.
The get_current_officer dependency is the only thing routes touch —
swapping the implementation here requires zero route changes.
"""
import os
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from config.settings import get

TOKEN_EXPIRE_HOURS = 24
ALGORITHM = "HS256"

security = HTTPBearer()


def create_access_token(officer_id: int, badge_number: str) -> str:
    """
    Create a signed JWT.
    Payload: officer_id, badge_number, exp (24 hours from now).
    Signed with APP_SECRET_KEY.
    """
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {
        "officer_id": officer_id,
        "badge_number": badge_number,
        "exp": expire,
    }
    return jwt.encode(payload, get("APP_SECRET_KEY"), algorithm=ALGORITHM)


def verify_token(token: str) -> dict:
    """
    Verify JWT signature and expiry.
    Returns payload dict on success.
    Raises HTTPException 401 on invalid or expired token.
    """
    try:
        payload = jwt.decode(token, get("APP_SECRET_KEY"), algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_officer(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """
    FastAPI dependency. Extracts Bearer token from Authorization header.
    Verifies it. Returns payload dict with officer_id and badge_number.
    Inject into any protected route: officer = Depends(get_current_officer)
    Raises HTTP 401 immediately on failure. No retry, no fallback.
    """
    return verify_token(credentials.credentials)


async def login(badge_number: str, password: str, pool) -> str:
    """
    Authenticate an officer.
    Looks up officer by badge_number in the officers table.
    Password check: for now, password must equal badge_number + "123".
    Example: badge KSP-2019-0042 → password KSP-2019-0042123
    Returns JWT token string on success.
    Raises HTTPException 401 on wrong badge or password.
    """
    from db.connection import execute_query

    results = await execute_query(
        "SELECT officer_id, badge_number, full_name FROM officers WHERE badge_number = %s AND is_active = TRUE",
        (badge_number,)
    )

    if not results:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid badge number or password.",
        )

    officer = results[0]
    expected_password = badge_number + "123"
    if password != expected_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid badge number or password.",
        )

    return create_access_token(officer["officer_id"], officer["badge_number"])
```

> **Note on the login query:** This uses parameterized query with `%s` placeholder and passes `(badge_number,)` as params tuple — this is correct aiomysql syntax. The `execute_query` function will use the params path, not the no-params path, so `%s` will be handled correctly by the driver.

---

### 4. Create `backend/routers/auth.py`

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from auth.simple_auth import login

router = APIRouter()


class LoginRequest(BaseModel):
    badge_number: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    badge_number: str


@router.post("/api/auth/login", response_model=LoginResponse)
async def login_route(request: LoginRequest):
    """
    Login endpoint. No auth required.
    Validates badge_number and password.
    Returns JWT token on success.
    Always HTTP 200 on success, HTTP 401 on failure.
    Never return 500 — catch all exceptions.
    """
    token = await login(request.badge_number, request.password, pool=None)
    return LoginResponse(
        access_token=token,
        badge_number=request.badge_number
    )


@router.post("/api/auth/logout")
async def logout_route():
    """
    Logout endpoint. JWT is stateless — just tell frontend to drop the token.
    Returns success always.
    """
    return {"message": "Logged out successfully."}
```

---

### 5. Update `backend/routers/chat.py`

Add the SSE streaming endpoint and protect both endpoints with auth. Also wire in real conversation history.

```python
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from pipeline.query_pipeline import run_pipeline
from conversation.history import get_history, save_turn
from auth.simple_auth import get_current_officer
import json
import asyncio

router = APIRouter()


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    session_id: str = Field(..., min_length=1, max_length=128)


class ChatResponse(BaseModel):
    answer_text: str
    table_data: list[dict]
    media_attachments: list[dict]
    sql_generated: str
    graph_available: bool
    error: str | None


@router.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, officer: dict = Depends(get_current_officer)):
    """
    Non-streaming chat. Kept for testing/fallback.
    Now includes real conversation history from NoSQL.
    """
    history = await get_history(request.session_id)
    result = await run_pipeline(request.question, history)

    if not result.error:
        await save_turn(request.session_id, request.question, result.answer_text)

    return ChatResponse(
        answer_text=result.answer_text,
        table_data=result.table_data,
        media_attachments=result.media_attachments,
        sql_generated=result.sql_generated,
        graph_available=result.graph_available,
        error=result.error,
    )


@router.get("/api/chat/stream")
async def chat_stream(
    question: str,
    session_id: str,
    officer: dict = Depends(get_current_officer)
):
    """
    SSE streaming chat endpoint.
    Runs the full pipeline, then streams the answer_text token by token.
    
    SSE event format (each line starts with "data: "):
    data: {"type": "status", "content": "Analyzing your question..."}
    data: {"type": "status", "content": "Querying database..."}
    data: {"type": "token", "content": "There"}
    data: {"type": "token", "content": " are"}
    data: {"type": "token", "content": " 20"}
    data: {"type": "table", "data": [...]}
    data: {"type": "media", "attachments": [...]}
    data: {"type": "graph_available", "fir_ids": []}
    data: {"type": "error", "message": "..."}
    data: {"type": "done"}
    
    Implementation note:
    The Catalyst LLM API does not support true streaming (it returns the full
    response at once). So we simulate streaming by:
    1. Sending status events while the pipeline runs
    2. Running the pipeline (this takes 60-120 seconds)
    3. Splitting answer_text by words and yielding each word as a token event
       with a small delay (0.03 seconds) between tokens
    This gives a natural streaming feel in the UI without requiring
    true LLM streaming support.
    """
    if not question or not question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    if len(question) > 500:
        raise HTTPException(status_code=400, detail="Question too long.")

    async def event_generator():
        try:
            # Status events while pipeline runs
            yield f"data: {json.dumps({'type': 'status', 'content': 'Analyzing your question...'})}\n\n"
            await asyncio.sleep(0.1)

            # Fetch history
            history = await get_history(session_id)

            yield f"data: {json.dumps({'type': 'status', 'content': 'Generating database query...'})}\n\n"
            await asyncio.sleep(0.1)

            # Run the full pipeline
            result = await run_pipeline(question, history)

            if result.error:
                yield f"data: {json.dumps({'type': 'error', 'message': result.error})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                return

            yield f"data: {json.dumps({'type': 'status', 'content': 'Formatting answer...'})}\n\n"
            await asyncio.sleep(0.1)

            # Stream answer_text word by word
            words = result.answer_text.split(" ")
            for i, word in enumerate(words):
                token = word if i == len(words) - 1 else word + " "
                yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
                await asyncio.sleep(0.03)

            # Send table data if present
            if result.table_data:
                yield f"data: {json.dumps({'type': 'table', 'data': result.table_data})}\n\n"

            # Send media attachments if present
            if result.media_attachments:
                yield f"data: {json.dumps({'type': 'media', 'attachments': result.media_attachments})}\n\n"

            # Send graph available flag
            if result.graph_available:
                yield f"data: {json.dumps({'type': 'graph_available'})}\n\n"

            # Save turn to history
            await save_turn(session_id, question, result.answer_text)

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': 'An unexpected error occurred.'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            print(f"SSE stream error: {e}", file=__import__('sys').stderr)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )
```

---

### 6. Update `backend/main.py`

Add two lines — register the auth router. The chat router is already registered. Also add the NoSQL table creation check on startup.

```python
# Add after existing router registration:
from routers.auth import router as auth_router
app.include_router(auth_router)
```

Also update the lifespan to try creating the NoSQL table on startup:

```python
# In lifespan, after DB pool creation, add:
# Try to initialize NoSQL conversation_history table
# If it fails, print a warning — NoSQL not critical for Step 3 local dev
try:
    from conversation.history import init_nosql_table
    await init_nosql_table()
    print("NoSQL conversation_history table ready.")
except Exception as e:
    print(f"WARNING: NoSQL init failed (history will not persist): {e}")
```

Add `init_nosql_table()` to `conversation/history.py`:

```python
async def init_nosql_table():
    """
    Ensure the conversation_history table exists in Catalyst NoSQL.
    Called once at startup. Safe to call multiple times.
    """
    # Implementation depends on Catalyst NoSQL table creation API
    # Check Catalyst NoSQL docs for the exact create-table endpoint
    # If table already exists, this should be a no-op
    pass  # Implement based on Catalyst NoSQL docs
```

---

### 7. Create the Frontend

The frontend is a minimal React SPA. Follow `Design.md` exactly for all visual decisions. Government portal aesthetic — no gradients, no animations beyond token streaming, no dark mode toggle. Clean, functional, professional.

**`frontend/package.json`:**
```json
{
  "name": "ksp-intelligence",
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.0",
    "react-dom": "^18.3.0"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.3.0",
    "vite": "^5.4.0"
  }
}
```

**`frontend/vite.config.js`:**
```js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      }
    }
  }
})
```

The proxy means the frontend calls `/api/...` and Vite forwards it to the backend. No CORS issues in dev. No need to hardcode the backend URL in frontend code.

**`frontend/.env`:**
```
VITE_APP_NAME=KSP Crime Intelligence
```

---

### `frontend/src/api/auth.js`

```javascript
// Auth API calls
// Token is stored in memory only — never localStorage, never sessionStorage

let _token = null;

export function getToken() {
    return _token;
}

export function setToken(token) {
    _token = token;
}

export function clearToken() {
    _token = null;
}

export function isLoggedIn() {
    return _token !== null;
}

export async function login(badgeNumber, password) {
    /*
    POST /api/auth/login
    Body: { badge_number, password }
    On success: call setToken(data.access_token), return { success: true }
    On 401: return { success: false, message: "Invalid badge number or password." }
    On other error: return { success: false, message: "Login failed. Please try again." }
    Never throws — always returns a result object.
    */
}

export async function logout() {
    /*
    POST /api/auth/logout
    Call clearToken()
    Return void.
    Never throws.
    */
}
```

---

### `frontend/src/api/chat.js`

```javascript
import { getToken } from './auth.js'

export function startChatStream(question, sessionId, callbacks) {
    /*
    Open an SSE connection to GET /api/chat/stream?question=...&session_id=...
    Include Authorization header — but EventSource doesn't support custom headers.
    
    Solution: Use fetch with ReadableStream instead of EventSource.
    
    Implementation:
    
    const response = await fetch(
        `/api/chat/stream?question=${encodeURIComponent(question)}&session_id=${encodeURIComponent(sessionId)}`,
        {
            headers: {
                'Authorization': `Bearer ${getToken()}`
            }
        }
    )
    
    if (response.status === 401) {
        callbacks.onError('Session expired. Please log in again.')
        callbacks.onAuthExpired()
        return
    }
    
    Read the response body as a stream.
    Parse each line that starts with "data: " as JSON.
    Route to callbacks based on event type:
    - status → callbacks.onStatus(content)
    - token → callbacks.onToken(content)
    - table → callbacks.onTable(data)
    - media → callbacks.onMedia(attachments)
    - graph_available → callbacks.onGraphAvailable()
    - error → callbacks.onError(message)
    - done → callbacks.onDone()
    
    Return a cancel function that aborts the fetch.
    */
}
```

---

### `frontend/src/hooks/useAuth.js`

```javascript
import { useState, useCallback } from 'react'
import { login as apiLogin, logout as apiLogout, isLoggedIn } from '../api/auth.js'

export function useAuth() {
    /*
    Manages auth state for the app.
    
    State:
    - isAuthenticated: bool
    - isLoading: bool
    - error: string | null
    
    Functions:
    - login(badgeNumber, password): calls apiLogin, updates isAuthenticated
    - logout(): calls apiLogout, sets isAuthenticated false
    
    Returns: { isAuthenticated, isLoading, error, login, logout }
    */
}
```

---

### `frontend/src/components/LoginPage.jsx`

```jsx
/*
Simple login form. Government portal style.

Layout:
- Centered card on white background
- KSP logo text at top (no image needed — just text "Karnataka State Police")
- Subtitle: "Crime Intelligence Platform"
- Badge Number input field
- Password input field (type="password")
- Login button
- Error message below button if login fails

On submit:
- Disable button, show "Authenticating..."
- Call login(badgeNumber, password) from useAuth
- On success: parent App.jsx handles redirect to chat
- On failure: show error message

No "forgot password" link.
No "remember me" checkbox.
No social login.
This is a police internal tool.

Validation:
- Both fields required
- No other validation — keep it simple
*/
```

---

### `frontend/src/components/ChatWindow.jsx`

```jsx
/*
Main chat interface. Takes up full viewport after login.

Layout:
- Top bar: "KSP Crime Intelligence" title + session ID display + logout button
- Message list: scrollable, takes remaining height
- Input area at bottom: fixed, text input + send button

State:
- messages: array of { id, role ('user'|'assistant'), content, tableData, mediaAttachments, isStreaming }
- inputValue: string
- isStreaming: bool (prevents sending while streaming)
- sessionId: generated once per login (use crypto.randomUUID())

On send:
1. Add user message to messages array
2. Add empty assistant message with isStreaming: true
3. Call startChatStream(question, sessionId, callbacks)
4. Callbacks update the last assistant message:
   - onStatus: update a status indicator (small text above input)
   - onToken: append to the assistant message content
   - onTable: set tableData on the assistant message
   - onMedia: set mediaAttachments on the assistant message
   - onDone: set isStreaming false on the assistant message
   - onError: set content to error message, isStreaming false
   - onAuthExpired: call logout(), redirect to login

Auto-scroll to bottom when new content arrives.
Disable input while isStreaming is true.

No voice button yet (Step 5).
No export button yet (Step 5).
No network graph button yet (Step 4).
*/
```

---

### `frontend/src/components/MessageBubble.jsx`

```jsx
/*
Renders a single message.

Props: { role, content, tableData, mediaAttachments, isStreaming }

For role='user':
- Right-aligned bubble with question text
- Simple background

For role='assistant':
- Left-aligned
- content rendered as plain text (markdown rendering is NOT required — keep it simple)
- If isStreaming: show a blinking cursor after content
- If tableData is non-empty: render <TableRenderer data={tableData} />
- If mediaAttachments is non-empty: render a simple list of attachment links
  (just filename and type — real media viewing comes in Step 4)

Keep it simple. No markdown parser. No syntax highlighting.
Just text, table, and attachment list.
*/
```

---

### `frontend/src/components/TableRenderer.jsx`

```jsx
/*
Renders table_data as an HTML table.

Props: { data: array of objects }

- Extract column names from Object.keys(data[0])
- Render a <table> with a <thead> row of column names
- Render a <tbody> with one <tr> per data row
- If value is boolean: render "Yes" or "No"
- If value is null/undefined: render "-"
- If value is a long string (>100 chars): truncate with "..." and show full on hover (title attribute)
- No external table library
- No sorting (keep it simple for now)
- Max 50 rows displayed (slice if needed)

Style: clean bordered table, alternating row background, fits within message bubble width.
*/
```

---

### `frontend/src/App.jsx`

```jsx
/*
Root component. Manages auth state.

If not authenticated: render <LoginPage onLoginSuccess={handleLoginSuccess} />
If authenticated: render <ChatWindow onLogout={handleLogout} />

Uses useAuth hook.

No routing library needed — just conditional rendering.
Two states: logged in or logged out.
*/
```

---

## Verify Step 3 — Run These Tests in Order

**Setup:**
```bash
# Terminal 1 — backend
pkill -f uvicorn
cd /home/venzz/Work/Dataathon
.venv/bin/uvicorn backend.main:app --reload --port 8000

# Terminal 2 — frontend
cd /home/venzz/Work/Dataathon/frontend
npm install
npm run dev
```

**Test 1 — Login:**
```bash
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"badge_number": "KSP-2019-0042", "password": "KSP-2019-0042123"}' | python3 -m json.tool
```
Expected: `access_token` in response.

**Test 2 — Protected route without token:**
```bash
curl -s -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "test", "session_id": "s1"}' | python3 -m json.tool
```
Expected: HTTP 403 or 401.

**Test 3 — Protected route with token:**
```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"badge_number": "KSP-2019-0042", "password": "KSP-2019-0042123"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"question": "How many theft cases are open?", "session_id": "s1"}' | python3 -m json.tool
```
Expected: Same working response as Step 2.

**Test 4 — SSE stream:**
```bash
curl -N -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/chat/stream?question=How+many+theft+cases+are+open%3F&session_id=s1"
```
Expected: SSE events streaming in, ending with `data: {"type": "done"}`.

**Test 5 — Multi-turn (history):**
```bash
# First question
curl -s -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"question": "Show me cases in Koramangala", "session_id": "multi1"}' | python3 -m json.tool

# Follow-up — should use context from first question
curl -s -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"question": "Now show only the open ones", "session_id": "multi1"}' | python3 -m json.tool
```
Expected: Second response references Koramangala cases without being told again.

**Test 6 — Frontend:**
Open `http://localhost:5173` in browser.
- Login page appears
- Use badge number from DB + badge+"123" as password
- Chat interface appears after login
- Type "How many theft cases are open?" and send
- Answer streams in word by word
- Table appears below the answer

All 6 passing = Step 3 is done.

---

## What Is NOT in Step 3

- Network graph endpoint and `NetworkGraph.jsx` — Step 4
- `MediaViewer.jsx` with lightbox/audio/video — Step 4
- Voice input (`VoiceInput.jsx`, Zia STT/TTS) — Step 5
- PDF export (SmartBrowz) — Step 5
- Real Catalyst Authentication (session-based) — production deployment
- Real Stratus signed URLs for media — Step 5
- Catalyst Cache integration for schema caching — optional optimization, add if time permits

---

## What Step 4 Will Build

Step 4 adds the network graph (backend endpoint + vis.js frontend panel), the media viewer (image lightbox, audio and video HTML5 players), and the "View network" button in the chat UI that appears when `graph_available` is true. After Step 4, the platform is feature-complete for the demo. Step 5 adds voice and PDF export as polish.
