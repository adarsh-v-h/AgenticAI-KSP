# Benchmarking Plan — Prototype Performance Report

> **Design goal:** one file, zero new dependencies beyond `httpx`, zero backend code changes
> required to run it (it hits the live API over HTTP, same as a real client would). Covers five
> angles — latency, concurrency, pipeline breakdown, AI quality, and optimization deltas — because
> a single "average response time: 2.3s" number on a slide invites the question "compared to
> what, and where does the time actually go," and this answers both.

---

## What to measure, and why each one earns its place on the slide

| Measurement | What it shows | Why a judge would care |
|---|---|---|
| **Per-endpoint latency sweep** | p50/p95/max across every major route | "We tested the whole system, not just the demo path" |
| **Concurrency ladder** | throughput/latency at 1/5/10/20 simultaneous requests | Honest answer to "how many officers can use this at once" — ties directly to your 2 vCPU / pool size 10 constraints |
| **Pipeline stage breakdown** | where time inside one chat turn actually goes (schema link → SQL gen → execute → format) | Turns "it takes ~10s" into "8.5s of that is two LLM calls, 40ms is the actual database" — much more credible than a black-box number |
| **AI engine quality suite** | SQL generation success rate, retry rate, avg latency across your existing 14 documented test scenarios | Reuses `DATABASE_SCHEMA_AND_REDESIGN_GUIDE.md`'s own test suite — near-zero new work, and "100% success across 13 varied query patterns" is a strong, verifiable headline number |
| **Before/after deltas** | measured improvement from the 3 fixes already identified this conversation (N+1 query, sequential recompute, lookup-table caching) | The single most compelling slide content you can produce — "we found X was slow, fixed it, here's the measured number" beats any static benchmark |

---

## The script — `backend/benchmark.py`

Standalone, run against local (`http://localhost:8000`) or the deployed AppSail URL. Produces
console tables for a quick look and a JSON dump for archival / pasting into the deck.

```python
"""
backend/benchmark.py -- lightweight, standalone benchmark harness for the
KSP Crime Intelligence Platform. Hits the running API over HTTP, no
instrumentation of the backend required. Produces console tables + a JSON
dump for the PPT.

Usage:
    pip install httpx   # if not already a dependency
    python backend/benchmark.py --base-url http://localhost:8000 \
        --badge 7295834 --password 7295834123
"""
import argparse
import asyncio
import json
import statistics
import time
import httpx


def pct(values, p):
    if not values:
        return None
    return statistics.quantiles(values, n=100)[p - 1] if len(values) > 1 else values[0]


def summarize(name, values):
    if not values:
        return {"name": name, "n": 0}
    return {
        "name": name, "n": len(values),
        "min_ms": round(min(values) * 1000, 1),
        "p50_ms": round(pct(values, 50) * 1000, 1),
        "p95_ms": round(pct(values, 95) * 1000, 1),
        "max_ms": round(max(values) * 1000, 1),
    }


async def login(client, base_url, badge, password):
    r = await client.post(f"{base_url}/api/auth/login",
                           json={"badge_number": badge, "password": password})
    r.raise_for_status()
    return r.json()["access_token"]


# ---------- 1. Per-endpoint latency sweep ----------

ENDPOINTS = [
    ("GET", "/api/chat/sessions"),
    ("GET", "/api/analytics/trends/monthly?months_back=12"),
    ("GET", "/api/analytics/trends/crime-type"),
    ("GET", "/api/analytics/trends/stations?limit=10"),
    ("GET", "/api/analytics/status-breakdown"),
    ("GET", "/api/analytics/mo-clusters?min_occurrences=2"),
    ("GET", "/api/analytics/seasonal"),
    ("GET", "/api/profiling/top-risk?limit=10"),
    ("GET", "/api/decision-support/similar-cases/2"),
    ("GET", "/api/decision-support/timeline/2"),
]

async def sweep_endpoints(client, base_url, token, reps=20):
    headers = {"Authorization": f"Bearer {token}"}
    results = []
    for method, path in ENDPOINTS:
        timings = []
        for _ in range(reps):
            t0 = time.perf_counter()
            r = await client.request(method, f"{base_url}{path}", headers=headers)
            timings.append(time.perf_counter() - t0)
            if r.status_code >= 500:
                print(f"  WARN {path} -> {r.status_code}")
        results.append(summarize(path, timings))
    return results


# ---------- 2. Concurrency ladder ----------

async def concurrency_ladder(client, base_url, token, path="/api/analytics/status-breakdown"):
    headers = {"Authorization": f"Bearer {token}"}
    results = []
    for concurrency in (1, 5, 10, 20):
        async def one():
            t0 = time.perf_counter()
            r = await client.get(f"{base_url}{path}", headers=headers)
            return time.perf_counter() - t0, r.status_code

        t0 = time.perf_counter()
        outcomes = await asyncio.gather(*[one() for _ in range(concurrency)])
        wall = time.perf_counter() - t0
        latencies = [o[0] for o in outcomes]
        errors = sum(1 for o in outcomes if o[1] >= 500)
        results.append({
            "concurrency": concurrency, "wall_s": round(wall, 2),
            "throughput_rps": round(concurrency / wall, 1),
            "p50_ms": round(pct(latencies, 50) * 1000, 1),
            "p95_ms": round(pct(latencies, 95) * 1000, 1),
            "errors": errors,
        })
    return results


# ---------- 3. NL2SQL pipeline stage breakdown (via SSE event gaps -- no backend changes needed) ----------

async def stream_stage_timing(client, base_url, token, question):
    headers = {"Authorization": f"Bearer {token}"}
    params = {"question": question, "session_id": f"bench-{int(time.time())}", "token": token}
    stages = []
    last_t = time.perf_counter()
    async with client.stream("GET", f"{base_url}/api/chat/stream", headers=headers,
                              params=params, timeout=60) as resp:
        buf = ""
        async for chunk in resp.aiter_text():
            buf += chunk
            while "\n\n" in buf:
                frame, buf = buf.split("\n\n", 1)
                if not frame.startswith("data:"):
                    continue
                now = time.perf_counter()
                try:
                    event = json.loads(frame[5:].strip())
                except json.JSONDecodeError:
                    continue
                stages.append({"type": event.get("type"), "gap_ms": round((now - last_t) * 1000, 1)})
                last_t = now
    return stages


# ---------- 4. AI engine quality suite (your own documented 13-scenario test set) ----------

TEST_QUESTIONS = [
    "Show me the last 5 cases registered",
    "How many open cases are there in total?",
    "List all police stations",
    "How many cases were registered in 2024?",
    "Show all theft cases registered in 2024",
    "Find all cases involving an accused named Mahesh Gowda",
    "Which officer is investigating the highest number of open cases?",
    "List all accused persons who have not been arrested yet",
    "Find top 5 crime subheads with the highest number of cases",
    "Show monthly breakdown of crime cases registered in 2024",
    "List offenders who are accused in more than 1 case",
    "Find all victims aged under 18",
    "Show distribution of cases across different police stations and their statuses",
]

async def quality_suite(client, base_url, token):
    headers = {"Authorization": f"Bearer {token}"}
    results = []
    for q in TEST_QUESTIONS:
        t0 = time.perf_counter()
        r = await client.post(f"{base_url}/api/chat", headers=headers,
                               json={"question": q, "session_id": f"bench-q-{int(time.time()*1000)}"})
        elapsed = time.perf_counter() - t0
        body = r.json()
        results.append({
            "question": q[:50], "status": r.status_code, "elapsed_s": round(elapsed, 2),
            "had_sql": bool(body.get("sql_generated")),
            "row_count": len(body.get("table_data") or []),
            "error": body.get("error"),
        })
    success = sum(1 for x in results if x["status"] == 200 and not x["error"])
    return {
        "results": results, "success_rate": f"{success}/{len(results)}",
        "avg_elapsed_s": round(statistics.mean(x["elapsed_s"] for x in results), 2),
    }


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--badge", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--out", default="benchmark_results.json")
    args = ap.parse_args()

    async with httpx.AsyncClient() as client:
        token = await login(client, args.base_url, args.badge, args.password)

        print("\n== Endpoint latency sweep ==")
        endpoint_results = await sweep_endpoints(client, args.base_url, token)
        for r in endpoint_results:
            print(f"{r['name']:<50} p50={r.get('p50_ms')}ms  p95={r.get('p95_ms')}ms  max={r.get('max_ms')}ms")

        print("\n== Concurrency ladder (status-breakdown) ==")
        conc_results = await concurrency_ladder(client, args.base_url, token)
        for r in conc_results:
            print(f"concurrency={r['concurrency']:<3} throughput={r['throughput_rps']}req/s  "
                  f"p50={r['p50_ms']}ms  p95={r['p95_ms']}ms  errors={r['errors']}")

        print("\n== Pipeline stage breakdown (sample question) ==")
        stage_results = await stream_stage_timing(client, args.base_url, token,
                                                    "How many open cases are there in total?")
        for s in stage_results:
            print(f"{s['type']:<20} +{s['gap_ms']}ms")

        print("\n== AI engine quality suite ==")
        quality_results = await quality_suite(client, args.base_url, token)
        print(f"success rate: {quality_results['success_rate']}   avg latency: {quality_results['avg_elapsed_s']}s")

        json.dump({
            "endpoint_sweep": endpoint_results,
            "concurrency_ladder": conc_results,
            "pipeline_stages_sample": stage_results,
            "quality_suite": quality_results,
        }, open(args.out, "w"), indent=2)
        print(f"\nFull results written to {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
```

**Why the pipeline breakdown needs no backend instrumentation:** `chat_stream()` already emits
`status`/`sql`/`token`/`table`/`done` SSE events in sequence. Timing the *gaps between when each
event arrives* client-side reconstructs stage-by-stage timing without touching
`query_pipeline.py` at all. Not nanosecond-precise (network jitter is in there too), but plenty
accurate for "SQL generation took ~2s, execution took ~50ms, formatting took ~3s" bucket-level
numbers on a slide.

---

## Before/after deltas — the highest-value slide content, and nearly free

You're already planning three fixes from earlier in this conversation. Wrap each in a bare timer,
run once on the old code, once on the new — that's the whole "before/after" methodology, no
separate harness needed:

```python
import time

async def time_it(fn, *args):
    t0 = time.perf_counter()
    result = await fn(*args)
    return result, time.perf_counter() - t0

# Before the N+1 fix in similar_cases.py:
_, elapsed_before = await time_it(find_similar_cases, case_id, 5)
# After applying the batched-query fix:
_, elapsed_after = await time_it(find_similar_cases, case_id, 5)
print(f"similar_cases: {elapsed_before:.2f}s -> {elapsed_after:.2f}s ({elapsed_before/elapsed_after:.1f}x)")
```

Same pattern for `recompute_all_risk_scores()` (sequential vs. `asyncio.gather` + semaphore) and
for lookup-table caching (time a chat question that joins `CrimeSubHead`/`CaseStatusMaster` before
and after adding an in-memory cache). Three numbers, three real fixes you're making anyway —
this is the part of the slide that actually differentiates you from "we ran a benchmark once."


Run it locally first against `localhost:8000` before pointing it at the deployed AppSail URL —
same reasoning as every other change in this conversation: cheaper to catch a bug against your own
machine than against the one judges might be watching.
