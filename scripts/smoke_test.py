#!/usr/bin/env python3
"""
Post-deploy smoke test — exercises the LIVE deployment end-to-end.

Catches the class of bugs that unit tests cannot: missing env variables,
CORS/proxy misconfig, auth breakage, and integration failures that only appear
once deployed (e.g. the voice TTS 502 caused by an unset ZIA_TTS_URL).

Usage:
    python3 scripts/smoke_test.py                    # uses SMOKE_BASE_URL or default
    SMOKE_BASE_URL=https://... python3 scripts/smoke_test.py
    python3 scripts/smoke_test.py --base https://...

Exit code:
    0  — all critical checks passed
    1  — one or more critical checks failed (CI should block / roll back)

Checks are tagged CRITICAL or WARN:
    CRITICAL failure  -> non-zero exit (blocks deploy / triggers rollback)
    WARN failure      -> logged, does not fail the run (data-dependent endpoints
                         that may legitimately return empty/404 on a fresh DB)
"""

import argparse
import os
import sys
import json
import urllib.request
import urllib.error

DEFAULT_BASE_URL = "https://crime-intel-backend-50043099694.development.catalystappsail.in"

# Seeded supervisor account (password formula: <KGID>123). Used only to obtain a
# token for authenticated smoke checks against the seeded demo database.
SMOKE_BADGE = os.getenv("SMOKE_BADGE", "3254123")
SMOKE_PASSWORD = os.getenv("SMOKE_PASSWORD", "3254123123")

_TIMEOUT = 30

_passed = 0
_failed = 0
_warned = 0


def _color(txt, code):
    return f"\033[{code}m{txt}\033[0m" if sys.stdout.isatty() else txt


def _req(method, url, headers=None, body=None, timeout=_TIMEOUT):
    """Return (status_code, body_bytes, content_type). Never raises for HTTP errors."""
    data = None
    hdrs = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Content-Type", "")
    except Exception as e:  # noqa: BLE001 — network error, report as status 0
        return 0, str(e).encode(), ""


def check(label, ok, detail="", critical=True):
    global _passed, _failed, _warned
    if ok:
        _passed += 1
        print(f"  {_color('PASS', 92)}  {label}")
    elif critical:
        _failed += 1
        print(f"  {_color('FAIL', 91)}  {label}" + (f" — {detail}" if detail else ""))
    else:
        _warned += 1
        print(f"  {_color('WARN', 93)}  {label}" + (f" — {detail}" if detail else ""))


def section(title):
    print(f"\n=== {title} ===")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=os.getenv("SMOKE_BASE_URL", DEFAULT_BASE_URL))
    args = parser.parse_args()
    base = args.base.rstrip("/")

    print(f"Smoke testing: {base}")

    # ── Health ────────────────────────────────────────────────────────────
    section("Health")
    status, raw, _ = _req("GET", f"{base}/health")
    health_ok = status == 200
    check("GET /health returns 200", health_ok, f"got {status}")
    if health_ok:
        try:
            h = json.loads(raw)
            check("health.db == connected", h.get("db") == "connected", f"db={h.get('db')}")
            check("health.llm_coder == ok", h.get("llm_coder") == "ok", f"llm_coder={h.get('llm_coder')}")
            check("health.llm_answer == ok", h.get("llm_answer") == "ok", f"llm_answer={h.get('llm_answer')}")
        except json.JSONDecodeError:
            check("health body is JSON", False, "unparseable")

    # ── Auth ──────────────────────────────────────────────────────────────
    section("Auth")
    status, raw, _ = _req("POST", f"{base}/api/auth/login",
                          body={"badge_number": SMOKE_BADGE, "password": SMOKE_PASSWORD})
    login_ok = status == 200
    check("POST /api/auth/login returns 200", login_ok, f"got {status}")
    token = None
    if login_ok:
        try:
            token = json.loads(raw).get("access_token")
            check("login returns access_token", bool(token))
        except json.JSONDecodeError:
            check("login body is JSON", False)

    status, _, _ = _req("POST", f"{base}/api/auth/login",
                        body={"badge_number": "0000000", "password": "wrong"})
    check("login rejects bad creds with 401", status == 401, f"got {status}")

    if not token:
        print("\nCannot continue authenticated checks without a token.")
        return _summary()

    auth = {"Authorization": f"Bearer {token}"}

    # ── Authenticated read endpoints ────────────────────────────────────────
    # (endpoint, critical?) — critical endpoints must return 200; WARN ones may
    # legitimately 404/empty on some data.
    section("Chat & sessions")
    status, raw, _ = _req("GET", f"{base}/api/chat/sessions", headers=auth)
    check("GET /api/chat/sessions", status == 200, f"got {status}")

    status, raw, _ = _req("POST", f"{base}/api/chat/sessions", headers=auth,
                          body={})
    new_session_id = None
    if status in (200, 201):
        try:
            new_session_id = json.loads(raw).get("session_id")
        except json.JSONDecodeError:
            pass
    check("POST /api/chat/sessions (create)", status in (200, 201), f"got {status}")
    if new_session_id:
        status, _, _ = _req("GET", f"{base}/api/chat/sessions/{new_session_id}/messages", headers=auth)
        check("GET /api/chat/sessions/{id}/messages", status == 200, f"got {status}")

    section("Analytics — trends")
    for path in [
        "/api/analytics/trends/monthly",
        "/api/analytics/trends/crime-type",
        "/api/analytics/trends/stations",
        "/api/analytics/status-breakdown",
        "/api/analytics/mo-clusters",
        "/api/analytics/seasonal",
    ]:
        status, _, _ = _req("GET", f"{base}{path}", headers=auth)
        check(f"GET {path}", status == 200, f"got {status}")

    section("Analytics — demographics")
    for path in [
        "/api/analytics/demographics/accused-age",
        "/api/analytics/demographics/crime-by-gender",
        "/api/analytics/demographics/victim-profile",
        "/api/analytics/demographics/crime-by-occupation",
        "/api/analytics/demographics/risk-profile",
    ]:
        status, _, _ = _req("GET", f"{base}{path}", headers=auth)
        check(f"GET {path}", status == 200, f"got {status}")

    section("Analytics — forecasting")
    for path in [
        "/api/analytics/forecasting/summary",
        "/api/analytics/forecasting/hotspots",
        "/api/analytics/forecasting/repeat-crimes",
        "/api/analytics/forecasting/gang-activity",
    ]:
        status, _, _ = _req("GET", f"{base}{path}", headers=auth)
        check(f"GET {path}", status == 200, f"got {status}")

    section("Profiling")
    status, _, _ = _req("GET", f"{base}/api/profiling/top-risk", headers=auth)
    check("GET /api/profiling/top-risk", status == 200, f"got {status}")

    section("Voice (env-var sensitive — these caught the ZIA_TTS_URL bug)")
    # TTS: text -> audio. Requires ZIA_TTS_URL to be set on the deployment.
    status, _, _ = _req("POST", f"{base}/api/voice/speak", headers=auth,
                        body={"text": "There are twelve open theft cases.", "language": "en"})
    check("POST /api/voice/speak (TTS) — needs ZIA_TTS_URL", status == 200, f"got {status}")
    # STT: expects an audio file. With no file we expect 422 (validation), NOT
    # 502 (which would mean ZIA_STT_URL is unset / misconfigured).
    status, _, _ = _req("POST", f"{base}/api/voice/transcribe", headers=auth)
    check("POST /api/voice/transcribe (STT) reachable (422, not 502)",
          status == 422, f"got {status}")

    section("Governance (RBAC)")
    # Supervisor token -> audit-log should be 200.
    status, _, _ = _req("GET", f"{base}/api/audit-log", headers=auth)
    check("GET /api/audit-log (supervisor allowed)", status == 200, f"got {status}")

    return _summary()


def _summary() -> int:
    print(f"\n{'='*50}")
    print(f"  {_color('PASSED', 92)}: {_passed}   "
          f"{_color('FAILED', 91)}: {_failed}   "
          f"{_color('WARN', 93)}: {_warned}")
    print(f"{'='*50}")
    if _failed:
        print(_color("\nSMOKE TEST FAILED — deployment is not healthy.", 91))
        return 1
    print(_color("\nSMOKE TEST PASSED.", 92))
    return 0


if __name__ == "__main__":
    sys.exit(main())
